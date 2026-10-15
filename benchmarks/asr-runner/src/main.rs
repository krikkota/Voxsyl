//! Local GigaAM benchmark. JSON lines in/out; no microphone or network access.
use serde::Deserialize;
use serde_json::json;
use std::io::{self, BufRead, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;
use transcribe_rs::onnx::gigaam::GigaAMModel;
use transcribe_rs::onnx::Quantization;
use transcribe_rs::{SpeechModel, TranscribeOptions};

#[derive(Deserialize)]
struct Request {
    id: String,
    path: PathBuf,
    #[serde(default = "one")]
    repeats: usize,
}

fn one() -> usize { 1 }

fn peak_rss_bytes() -> Option<i64> {
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
        return None;
    }
    let rss = unsafe { usage.assume_init() }.ru_maxrss;
    // Darwin reports bytes, Linux reports KiB.
    Some(if cfg!(target_os = "macos") { rss } else { rss * 1024 })
}

fn emit(value: serde_json::Value) {
    println!("{value}");
    io::stdout().flush().ok();
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let model_path = std::env::args().nth(1).ok_or("Usage: voxsyl-asr-bench MODEL_DIRECTORY")?;
    let start = Instant::now();
    let mut model = GigaAMModel::load(Path::new(&model_path), &Quantization::Int8)?;
    emit(json!({"event":"ready", "engine":"transcribe-rs-0.3.8", "backend":"ONNX CPU", "load_ms":start.elapsed().as_secs_f64()*1000.0, "peak_rss_bytes":peak_rss_bytes()}));
    for line in io::stdin().lock().lines() {
        let line = line?;
        if line.trim().is_empty() { continue; }
        let request: Request = match serde_json::from_str(&line) {
            Ok(r) => r,
            Err(e) => { emit(json!({"event":"error", "error":e.to_string()})); continue; }
        };
        let audio_duration = hound::WavReader::open(&request.path)
            .map(|r| r.duration() as f64 / r.spec().sample_rate as f64);
        let audio_duration = match audio_duration {
            Ok(d) => d,
            Err(e) => { emit(json!({"event":"error","id":request.id,"error":e.to_string()})); continue; }
        };
        for iteration in 0..request.repeats.clamp(1, 5) {
            let start = Instant::now();
            let result = model.transcribe_file(&request.path, &TranscribeOptions::default());
            match result {
                Ok(result) => emit(json!({"event":"result", "id":request.id, "iteration":iteration, "audio_seconds":audio_duration, "transcribe_ms":start.elapsed().as_secs_f64()*1000.0, "text":result.text, "peak_rss_bytes":peak_rss_bytes()})),
                Err(error) => emit(json!({"event":"error","id":request.id,"error":error.to_string()})),
            }
        }
    }
    Ok(())
}
