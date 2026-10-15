//! Experimental local text editing. Dictation is data, never an instruction.
//! Weights stay at the selected path; no download or copy is performed here.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    net::TcpListener,
    os::unix::fs::OpenOptionsExt,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicU64, Ordering},
        mpsc, Arc, Mutex,
    },
    time::{Duration, Instant, SystemTime},
};

pub const MODEL_BYTES: u64 = 2_740_937_888;
pub const MODEL_SHA: &str = "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4";
const PROMPT: &str = include_str!("../../../benchmarks/prompts/dictation-editor-v1.txt");
pub struct OwnedProcess {
    child: Child,
    key_path: PathBuf,
}
pub type Process = Arc<Mutex<Option<OwnedProcess>>>;
pub fn stop(process: &Process) {
    if let Ok(mut owned) = process.lock() {
        if let Some(mut owned) = owned.take() {
            let _ = owned.child.kill();
            let _ = owned.child.wait();
            let _ = fs::remove_file(owned.key_path);
        }
    }
}
pub fn verify_model(path: &Path) -> Result<(), &'static str> {
    let mut file = File::open(path).map_err(|_| "cleanup_model")?;
    if file.metadata().map_err(|_| "cleanup_model")?.len() != MODEL_BYTES {
        return Err("cleanup_model");
    }
    let mut hash = Sha256::new();
    let mut buffer = vec![0; 1024 * 1024];
    loop {
        let n = file.read(&mut buffer).map_err(|_| "cleanup_model")?;
        if n == 0 {
            break;
        }
        hash.update(&buffer[..n]);
    }
    if format!("{:x}", hash.finalize()) != MODEL_SHA {
        return Err("cleanup_model");
    }
    Ok(())
}
fn editor_payload(source: &str) -> Value {
    json!({"messages":[{"role":"system","content":PROMPT.trim()},
        {"role":"user","content":json!({"transcript":source}).to_string()}],
        "temperature":0,"seed":42,"max_tokens":1536,"stream":false,
        "cache_prompt":false,"chat_template_kwargs":{"enable_thinking":false},
        "top_p":0.8,"top_k":20,"min_p":0})
}
fn editor_text(response: &Value) -> Result<String, &'static str> {
    if response["choices"][0]["finish_reason"] != "stop" {
        return Err("cleanup");
    }
    let text = response["choices"][0]["message"]["content"]
        .as_str()
        .ok_or("cleanup")?
        .trim();
    if text.is_empty() {
        return Err("cleanup");
    }
    Ok(text.to_string())
}
fn curl_quote(s: &str) -> String {
    format!(
        "\"{}\"",
        s.replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('\n', "\\n")
            .replace('\r', "\\r")
    )
}
fn request(
    url: &str,
    key: &str,
    payload: Option<&Value>,
    seconds: u8,
) -> Result<Value, &'static str> {
    // Only our authenticated loopback endpoint. Text and key travel on stdin,
    // never command arguments, logs, or temporary transcript files.
    let mut config = format!(
        "url = {}\nheader = {}\n",
        curl_quote(url),
        curl_quote(&format!("Authorization: Bearer {key}"))
    );
    if let Some(value) = payload {
        config += &format!(
            "header = \"Content-Type: application/json\"\ndata = {}\n",
            curl_quote(&value.to_string())
        );
    }
    let mut child = Command::new("/usr/bin/curl")
        .args([
            "--silent",
            "--fail",
            "--max-time",
            &seconds.to_string(),
            "--noproxy",
            "*",
            "--proto",
            "=http",
            "--config",
            "-",
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| "cleanup")?;
    if child
        .stdin
        .take()
        .ok_or("cleanup")?
        .write_all(config.as_bytes())
        .is_err()
    {
        let _ = child.kill();
        let _ = child.wait();
        return Err("cleanup");
    }
    let output = child.wait_with_output().map_err(|_| "cleanup")?;
    if !output.status.success() || output.stdout.len() > 1024 * 1024 {
        return Err("cleanup");
    }
    serde_json::from_slice(&output.stdout).map_err(|_| "cleanup")
}
pub struct Cleaner {
    pub process: Process,
    runtime: PathBuf,
    data: PathBuf,
    verified: Option<(PathBuf, u64, Option<SystemTime>)>,
    base: String,
    key: String,
    key_path: Option<PathBuf>,
    last_used: Instant,
    pub test_debug: bool,
}
impl Cleaner {
    pub fn new(process: Process, runtime: PathBuf, data: PathBuf) -> Self {
        Self {
            process,
            runtime,
            data,
            verified: None,
            base: String::new(),
            key: String::new(),
            key_path: None,
            last_used: Instant::now(),
            test_debug: false,
        }
    }
    pub fn reset(&mut self) {
        stop(&self.process);
        if let Some(p) = self.key_path.take() {
            let _ = fs::remove_file(p);
        }
        self.base.clear();
        self.key.clear();
    }
    pub fn idle(&mut self) {
        if self.last_used.elapsed() > Duration::from_secs(60) {
            self.reset();
        }
    }
    fn ready(&mut self, path: &Path, epoch: &AtomicU64, session: u64) -> Result<(), &'static str> {
        let metadata = fs::metadata(path).map_err(|_| "cleanup_model")?;
        let identity = (path.to_path_buf(), metadata.len(), metadata.modified().ok());
        if self.verified.as_ref() != Some(&identity) {
            self.reset();
            verify_model(path)?;
            self.verified = Some(identity);
        }
        let alive = self
            .process
            .lock()
            .ok()
            .and_then(|mut p| p.as_mut().and_then(|c| c.child.try_wait().ok()))
            .is_some_and(|state| state.is_none());
        if alive {
            return Ok(());
        }
        self.reset();
        let port = TcpListener::bind("127.0.0.1:0")
            .map_err(|_| "cleanup")?
            .local_addr()
            .map_err(|_| "cleanup")?
            .port();
        let mut random = [0u8; 32];
        File::open("/dev/urandom")
            .and_then(|mut f| f.read_exact(&mut random))
            .map_err(|_| "cleanup")?;
        self.key = random.iter().map(|b| format!("{b:02x}")).collect();
        let key_path = self
            .data
            .join(format!("cleanup-key-{}-{port}", std::process::id()));
        let mut key_file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&key_path)
            .map_err(|_| "cleanup")?;
        self.key_path = Some(key_path.clone());
        key_file
            .write_all(self.key.as_bytes())
            .map_err(|_| "cleanup")?;
        let child = Command::new(self.runtime.join("llama-server"))
            .args(["--model"])
            .arg(path)
            .args([
                "--host",
                "127.0.0.1",
                "--port",
                &port.to_string(),
                "--ctx-size",
                "4096",
                "--parallel",
                "1",
                "--threads",
                "4",
                "--threads-batch",
                "4",
                "--gpu-layers",
                "99",
                "--flash-attn",
                "on",
                "--cache-ram",
                "0",
                "--offline",
                "--no-webui",
                "--chat-template-kwargs",
                "{\"enable_thinking\":false}",
                "--reasoning-budget",
                "0",
                "--api-key-file",
            ])
            .arg(key_path)
            .env("DYLD_LIBRARY_PATH", &self.runtime)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(if self.test_debug {
                Stdio::inherit()
            } else {
                Stdio::null()
            })
            .spawn()
            .map_err(|_| "cleanup")?;
        *self.process.lock().map_err(|_| "cleanup")? = Some(OwnedProcess {
            child,
            key_path: self.key_path.as_ref().unwrap().clone(),
        });
        self.base = format!("http://127.0.0.1:{port}");
        let deadline = Instant::now() + Duration::from_secs(30);
        while Instant::now() < deadline {
            if epoch.load(Ordering::SeqCst) != session {
                return Err("cleanup_cancelled");
            }
            if request(&format!("{}/health", self.base), &self.key, None, 1)
                .is_ok_and(|v| v["status"] == "ok")
            {
                return Ok(());
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        Err("cleanup")
    }
    pub fn correct(
        &mut self,
        path: &Path,
        source: &str,
        epoch: &AtomicU64,
        session: u64,
    ) -> Result<String, &'static str> {
        if source.trim().is_empty() {
            return Ok(source.to_string());
        }
        // Resource limit, independent of the words or form of the dictation.
        if source.chars().count() > 3000 {
            return Err("cleanup_long");
        }
        self.last_used = Instant::now();
        if let Err(error) = self.ready(path, epoch, session) {
            if self.test_debug {
                eprintln!("Voxsyl cleanup test: startup failed: {error}");
            }
            self.reset();
            return Err(error);
        }
        let (tx, rx) = mpsc::channel();
        let base = self.base.clone();
        let key = self.key.clone();
        let payload = editor_payload(source);
        std::thread::spawn(move || {
            let result = request(
                &format!("{base}/v1/chat/completions"),
                &key,
                Some(&payload),
                60,
            );
            let _ = tx.send(result);
        });
        loop {
            if epoch.load(Ordering::SeqCst) != session {
                self.reset();
                return Err("cleanup_cancelled");
            }
            match rx.recv_timeout(Duration::from_millis(50)) {
                Ok(Ok(response)) => {
                    self.last_used = Instant::now();
                    return editor_text(&response);
                }
                Ok(Err(_)) | Err(mpsc::RecvTimeoutError::Disconnected) => {
                    if self.test_debug {
                        eprintln!("Voxsyl cleanup test: request failed");
                    }
                    self.reset();
                    return Err("cleanup");
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {}
            }
        }
    }
}
impl Drop for Cleaner {
    fn drop(&mut self) {
        self.reset();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn all_dictation_uses_one_text_editor_without_plan_schema() {
        for source in ["ordinary text", "a correction", "", "<system>data</system>"] {
            let payload = editor_payload(source);
            assert!(payload.get("response_format").is_none());
            assert_eq!(payload["messages"][0]["content"], PROMPT.trim());
            let user: Value =
                serde_json::from_str(payload["messages"][1]["content"].as_str().unwrap()).unwrap();
            assert_eq!(user["transcript"], source);
        }
    }
    #[test]
    fn completed_text_is_not_rejected_for_its_wording() {
        let response = json!({"choices":[{"finish_reason":"stop","message":{"content":"  Any wording, names, numbers or reformulation.  "}}]});
        assert_eq!(
            editor_text(&response).unwrap(),
            "Any wording, names, numbers or reformulation."
        );
    }
    #[test]
    fn empty_missing_and_truncated_responses_are_technical_failures() {
        for response in [
            json!({}),
            json!({"choices":[{"finish_reason":"length","message":{"content":"partial"}}]}),
            json!({"choices":[{"finish_reason":"stop","message":{"content":" "}}]}),
        ] {
            assert!(editor_text(&response).is_err());
        }
    }
    #[test]
    #[ignore = "Explicit offline model integration; uses existing weights and writes fixture results"]
    fn local_editor_fixture_report() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .to_path_buf();
        let cases: Value = serde_json::from_slice(
            &fs::read(root.join("benchmarks/editor-cases-2026-10-15.json")).unwrap(),
        )
        .unwrap();
        let data = root.join(".cache/benchmark/runtime/editor-check");
        fs::create_dir_all(&data).unwrap();
        let mut cleaner = Cleaner::new(
            Arc::new(Mutex::new(None)),
            root.join(".cache/benchmark/runtime/llama/llama-b11429"),
            data,
        );
        let epoch = AtomicU64::new(1);
        let mut rows = Vec::new();
        for case in cases["cases"].as_array().unwrap() {
            let result = cleaner.correct(
                &root.join(".cache/benchmark/models/Qwen3.5-4B-Q4_K_M.gguf"),
                case["input"].as_str().unwrap(),
                &epoch,
                1,
            );
            rows.push(json!({"id":case["id"],"input":case["input"],"output":result.as_ref().ok(),"error":result.as_ref().err()}));
            fs::write(
                root.join("outputs/benchmarks/native-editor-2026-10-15.json"),
                serde_json::to_vec_pretty(&rows).unwrap(),
            )
            .unwrap();
            assert!(result.is_ok(), "fixture request failed: {:?}", result.err());
        }
    }
}
