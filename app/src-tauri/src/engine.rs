use crate::{
    audio_toolkit::audio::{AudioRecorder, VadPolicy},
    cleanup, mac, ui,
};
use serde::{Deserialize, Serialize};
use std::{
    fs,
    io::Write,
    os::unix::fs::OpenOptionsExt,
    path::PathBuf,
    sync::{
        atomic::{AtomicU64, Ordering},
        mpsc, Arc, Mutex,
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tauri::{AppHandle, Emitter, Manager};
use transcribe_rs::{
    onnx::{gigaam::GigaAMModel, Quantization},
    SpeechModel, TranscribeOptions,
};

#[derive(Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub shortcut: String,
    pub hold: bool,
    pub auto_insert: bool,
    pub cleanup: bool,
    pub history_enabled: bool,
    pub sounds: bool,
    pub microphone: Option<String>,
    pub cleanup_model_path: Option<String>,
}
impl Default for Settings {
    fn default() -> Self {
        Self {
            shortcut: "optionright".into(),
            hold: false,
            auto_insert: false,
            cleanup: true,
            history_enabled: true,
            sounds: true,
            microphone: None,
            cleanup_model_path: None,
        }
    }
}
#[derive(Clone, Serialize, Deserialize)]
pub struct Entry {
    pub id: u64,
    pub timestamp: u64,
    pub raw: String,
    pub edited: String,
}
#[derive(Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ShortcutStatus {
    Checking,
    PermissionRequired,
    ListenerUnavailable,
    RegistrationFailed,
    Ready,
}
#[derive(Clone, Serialize)]
pub struct Snapshot {
    pub phase: String,
    pub text: String,
    pub raw_text: String,
    pub cleanup_model_status: String,
    pub error: Option<String>,
    pub settings: Settings,
    pub history: Vec<Entry>,
    pub shortcut_ready: bool,
    pub shortcut_status: ShortcutStatus,
    pub asr_ready: bool,
}
impl Default for Snapshot {
    fn default() -> Self {
        Self {
            phase: "idle".into(),
            text: String::new(),
            raw_text: String::new(),
            cleanup_model_status: "missing".into(),
            error: None,
            settings: Settings::default(),
            history: vec![],
            shortcut_ready: false,
            shortcut_status: ShortcutStatus::Checking,
            asr_ready: false,
        }
    }
}
pub enum Command {
    Press(u64),
    Release,
    TimeLimit,
    Cancel,
    Insert(String),
    Settings(Settings),
    Delete(u64),
    Clear,
    TestFile(PathBuf, Option<i32>, bool),
    Shutdown,
    CleanupModel(PathBuf),
    RestoreRaw,
}
pub struct State {
    pub snapshot: Arc<Mutex<Snapshot>>,
    pub sender: mpsc::Sender<Command>,
    pub generation: Arc<AtomicU64>,
    pub cleanup_process: cleanup::Process,
}
pub fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
fn persist(path: &PathBuf, value: &impl Serialize) -> Result<(), String> {
    let bytes = serde_json::to_vec(value).map_err(|_| "storage")?;
    let temp = path.with_extension("tmp");
    let mut file = fs::OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .mode(0o600)
        .open(&temp)
        .map_err(|_| "storage")?;
    file.write_all(&bytes)
        .and_then(|_| file.sync_all())
        .map_err(|_| "storage")?;
    fs::rename(temp, path).map_err(|_| "storage".into())
}
fn publish(app: &AppHandle, snapshot: &Arc<Mutex<Snapshot>>) {
    if let Ok(value) = snapshot.lock() {
        let _ = app.emit("snapshot", value.clone());
    }
}
fn phase(app: &AppHandle, snapshot: &Arc<Mutex<Snapshot>>, name: &str, error: Option<&str>) {
    if let Ok(mut value) = snapshot.lock() {
        value.phase = name.into();
        value.error = error.map(str::to_string);
    }
    publish(app, snapshot);
    ui::show_overlay(app, name == "preview" || name == "error");
}
pub fn initialize(app: AppHandle) -> Result<State, String> {
    let data = app.path().app_local_data_dir().map_err(|_| "storage")?;
    fs::create_dir_all(&data).map_err(|_| "storage")?;
    let settings_path = data.join("settings.json");
    let history_path = data.join("history.json");
    let settings: Settings = fs::read(&settings_path)
        .ok()
        .and_then(|b| serde_json::from_slice(&b).ok())
        .unwrap_or_default();
    let mut history: Vec<Entry> = fs::read(&history_path)
        .ok()
        .and_then(|b| serde_json::from_slice(&b).ok())
        .unwrap_or_default();
    history.retain(|e| now().saturating_sub(e.timestamp) < 7 * 86400);
    persist(&history_path, &history)?;
    let cleanup_model_status = if settings.cleanup_model_path.is_some() {
        "linked"
    } else {
        "missing"
    }
    .into();
    let snapshot = Arc::new(Mutex::new(Snapshot {
        settings,
        cleanup_model_status,
        history,
        ..Snapshot::default()
    }));
    let generation = Arc::new(AtomicU64::new(1));
    let (sender, receiver) = mpsc::channel();
    let shared = snapshot.clone();
    let epoch = generation.clone();
    let cleanup_process = Arc::new(Mutex::new(None));
    let cleanup_child = cleanup_process.clone();
    std::thread::spawn(move || {
        let resources = match app.path().resource_dir() {
            Ok(p) => p,
            Err(_) => return,
        };
        let mut model =
            GigaAMModel::load(&resources.join("models/gigaam"), &Quantization::Int8).ok();
        let mut cleaner =
            cleanup::Cleaner::new(cleanup_child, resources.join("runtime/llama"), data);
        if let Ok(mut s) = shared.lock() {
            s.asr_ready = model.is_some();
        }
        publish(&app, &shared);
        let app_level = app.clone();
        let mut recorder = match AudioRecorder::new() {
            Ok(r) => r.with_level_callback(move |levels| {
                let level = levels.iter().copied().fold(0.0_f32, f32::max);
                let _ = app_level.emit("mic-level", level);
            }),
            Err(_) => return,
        };
        let mut recording = false;
        let mut started = Instant::now();
        let mut pruned = Instant::now();
        let mut target = None;
        let mut stopped_focus = None;
        let mut test_document = false;
        let mut read_only_test = false;
        let mut test_stop_cursor = false;
        let mut session = 0;
        let mut current_entry = None;
        loop {
            cleaner.idle();
            let mut command = match receiver.recv_timeout(Duration::from_millis(30)) {
                Ok(c) => Some(c),
                Err(mpsc::RecvTimeoutError::Timeout) => None,
                Err(_) => break,
            };
            // Clicking the panel may make Voxsyl frontmost before Insert is
            // delivered. Track the latest external destination while previewing.
            if !read_only_test
                && !test_document
                && shared.lock().map(|s| s.phase == "preview").unwrap_or(false)
            {
                if let Some(pid) = mac::insertion_pid() {
                    target = Some(pid);
                }
            }
            if recording && recorder.needs_reopen() {
                let _ = recorder.stop();
                let _ = recorder.close();
                recording = false;
                phase(&app, &shared, "error", Some("microphone"));
            }
            if recording && command.is_none() && started.elapsed() >= Duration::from_secs(240) {
                command = Some(Command::TimeLimit);
            }
            if pruned.elapsed() > Duration::from_secs(60) {
                if let Ok(mut s) = shared.lock() {
                    let before = s.history.len();
                    s.history
                        .retain(|e| now().saturating_sub(e.timestamp) < 7 * 86400);
                    if s.history.len() != before {
                        let _ = persist(&history_path, &s.history);
                    }
                }
                pruned = Instant::now();
                publish(&app, &shared);
            }
            let Some(command) = command else { continue };
            let settings = match shared.lock() {
                Ok(s) => s.settings.clone(),
                Err(_) => break,
            };
            match command {
                Command::Shutdown => {
                    let _ = recorder.close();
                    break;
                }
                Command::Cancel => {
                    cleaner.reset();
                    if recording {
                        let _ = recorder.stop();
                        let _ = recorder.close();
                        recording = false;
                    }
                    phase(&app, &shared, "closing", None);
                }
                Command::Press(id) if !recording => {
                    if shared.lock().map(|s| s.phase != "idle").unwrap_or(true) {
                        continue;
                    }
                    if epoch.load(Ordering::SeqCst) != id {
                        continue;
                    }
                    // The destination is selected later, not when recording starts.
                    target = None;
                    if cleaner.test_debug {
                        cleaner.reset();
                        cleaner.test_debug = false;
                    }
                    stopped_focus = None;
                    test_document = false;
                    read_only_test = false;
                    test_stop_cursor = false;
                    current_entry = None;
                    session = id;
                    if let Ok(mut s) = shared.lock() {
                        s.text.clear();
                        s.raw_text.clear();
                    }
                    phase(&app, &shared, "arming", None);
                    let device = if let Some(name) = &settings.microphone {
                        match crate::audio_toolkit::audio::list_input_devices()
                            .ok()
                            .and_then(|devices| devices.into_iter().find(|d| &d.name == name))
                        {
                            Some(d) => Some(d.device),
                            None => {
                                phase(&app, &shared, "error", Some("microphone"));
                                continue;
                            }
                        }
                    } else {
                        None
                    };
                    let ready = recorder
                        .open(device)
                        .and_then(|_| recorder.start(VadPolicy::Disabled));
                    match ready {
                        Ok(rx) if rx.recv_timeout(Duration::from_secs(3)).is_ok() => {
                            if epoch.load(Ordering::SeqCst) != session {
                                let _ = recorder.close();
                                phase(&app, &shared, "closing", None);
                                continue;
                            }
                            recording = true;
                            started = Instant::now();
                            phase(&app, &shared, "recording", None);
                            if settings.sounds {
                                mac::cue(&resources, "activate")
                            }
                        }
                        _ => {
                            let _ = recorder.close();
                            phase(&app, &shared, "error", Some("microphone"));
                        }
                    }
                }
                Command::Press(_) | Command::Release | Command::TimeLimit if recording => {
                    if matches!(command, Command::Press(_)) && settings.hold {
                        continue;
                    }
                    if matches!(command, Command::Release) && !settings.hold {
                        continue;
                    }
                    // Freeze the auto-insert destination at the stop gesture,
                    // before transcription can take time or change focus.
                    stopped_focus = mac::capture_insertion_focus(&app);
                    target = stopped_focus.as_ref().map(|focus| focus.pid);
                    let samples = recorder.stop();
                    let _ = recorder.close();
                    recording = false;
                    if settings.sounds {
                        mac::cue(&resources, "deactivate")
                    }
                    phase(&app, &shared, "processing", None);
                    if model.is_none() {
                        model = GigaAMModel::load(
                            &resources.join("models/gigaam"),
                            &Quantization::Int8,
                        )
                        .ok();
                    }
                    let result = samples.ok().and_then(|audio| {
                        model
                            .as_mut()
                            .and_then(|m| m.transcribe(&audio, &TranscribeOptions::default()).ok())
                    });
                    if epoch.load(Ordering::SeqCst) != session {
                        phase(&app, &shared, "closing", None);
                        continue;
                    }
                    match result {
                        Some(r) if r.text.trim().is_empty() => {
                            phase(&app, &shared, "closing", None)
                        }
                        Some(r) => {
                            let raw = r.text.trim().to_string();
                            let experimental =
                                settings.cleanup && settings.cleanup_model_path.is_some();
                            let corrected = if experimental {
                                cleaner.correct(
                                    std::path::Path::new(
                                        settings.cleanup_model_path.as_ref().unwrap(),
                                    ),
                                    &raw,
                                    &epoch,
                                    session,
                                )
                            } else {
                                Ok(raw.clone())
                            };
                            if epoch.load(Ordering::SeqCst) != session {
                                phase(&app, &shared, "closing", None);
                                continue;
                            }
                            let cleanup_error = corrected.as_ref().err().copied();
                            let text = corrected.unwrap_or_else(|_| raw.clone());
                            let id = now() * 1000 + session;
                            if let Ok(mut s) = shared.lock() {
                                s.text = text.clone();
                                s.raw_text = raw.clone();
                                s.asr_ready = true;
                                if settings.history_enabled {
                                    s.history.insert(
                                        0,
                                        Entry {
                                            id,
                                            timestamp: now(),
                                            raw: raw.clone(),
                                            edited: text.clone(),
                                        },
                                    );
                                    current_entry = Some(id);
                                    if persist(&history_path, &s.history).is_err() {
                                        s.error = Some("storage".into());
                                    }
                                }
                            }
                            // This experimental model is always preview-confirmed.
                            if settings.auto_insert && !experimental {
                                phase(&app, &shared, "inserting", None);
                                match mac::paste(
                                    &app,
                                    target,
                                    text,
                                    test_document,
                                    stopped_focus.take(),
                                ) {
                                    Ok(()) => phase(&app, &shared, "closing", None),
                                    Err(_) => phase(&app, &shared, "preview", Some("paste")),
                                }
                            } else {
                                phase(&app, &shared, "preview", cleanup_error)
                            }
                        }
                        None => phase(&app, &shared, "error", Some("asr")),
                    }
                }
                Command::Insert(text) => {
                    if shared.lock().map(|s| s.phase != "preview").unwrap_or(true)
                        || text.trim().is_empty()
                    {
                        continue;
                    }
                    // A nonactivating preview can be clicked while another app
                    // remains frontmost. Use that app's current cursor, rather
                    // than the application present when recording began.
                    if !read_only_test && !test_document {
                        target = mac::insertion_pid().or(target);
                    }
                    if let Ok(mut s) = shared.lock() {
                        s.text = text.clone();
                        if let Some(e) = s.history.iter_mut().find(|e| Some(e.id) == current_entry)
                        {
                            e.edited = text.clone();
                        }
                        let _ = persist(&history_path, &s.history);
                    }
                    phase(&app, &shared, "inserting", None);
                    let focus = if test_stop_cursor {
                        stopped_focus.take()
                    } else {
                        None
                    };
                    match mac::paste(&app, target, text, test_document, focus) {
                        Ok(()) => phase(&app, &shared, "closing", None),
                        Err(_) => phase(&app, &shared, "preview", Some("paste")),
                    }
                }
                Command::Settings(value) => {
                    if recording {
                        continue;
                    }
                    if let Ok(mut s) = shared.lock() {
                        if persist(&settings_path, &value).is_ok() {
                            if !value.cleanup
                                || value.cleanup_model_path != s.settings.cleanup_model_path
                            {
                                cleaner.reset();
                            }
                            s.cleanup_model_status = if value.cleanup_model_path.is_some() {
                                "linked"
                            } else {
                                "missing"
                            }
                            .into();
                            s.settings = value;
                            s.error = None
                        } else {
                            s.error = Some("storage".into())
                        }
                    }
                    publish(&app, &shared);
                }
                Command::Delete(id) => {
                    if let Ok(mut s) = shared.lock() {
                        s.history.retain(|e| e.id != id);
                        let _ = persist(&history_path, &s.history);
                    }
                    publish(&app, &shared)
                }
                Command::Clear => {
                    if let Ok(mut s) = shared.lock() {
                        s.history.clear();
                        let _ = persist(&history_path, &s.history);
                    }
                    publish(&app, &shared)
                }
                Command::TestFile(path, test_target, stop_cursor) => {
                    cleaner.test_debug = true;
                    // Default WAV mode is read-only. A separate explicit flag
                    // permits preview-confirmed paste into the disposable test
                    // document validated before startup; never opens the mic.
                    target = test_target;
                    test_document = test_target.is_some();
                    read_only_test = test_target.is_none();
                    test_stop_cursor = stop_cursor;
                    stopped_focus = if stop_cursor {
                        test_target.and_then(|pid| mac::capture_test_focus(&app, pid))
                    } else {
                        None
                    };
                    if stop_cursor && stopped_focus.is_none() {
                        phase(&app, &shared, "error", Some("paste"));
                        continue;
                    }
                    current_entry = None;
                    session = epoch.load(Ordering::SeqCst);
                    phase(&app, &shared, "processing", None);
                    match model
                        .as_mut()
                        .and_then(|m| m.transcribe_file(&path, &TranscribeOptions::default()).ok())
                    {
                        Some(r) => {
                            let raw = r.text;
                            let corrected = if settings.cleanup {
                                settings
                                    .cleanup_model_path
                                    .as_ref()
                                    .map(|path| {
                                        cleaner.correct(
                                            std::path::Path::new(path),
                                            &raw,
                                            &epoch,
                                            session,
                                        )
                                    })
                                    .unwrap_or_else(|| Ok(raw.clone()))
                            } else {
                                Ok(raw.clone())
                            };
                            if epoch.load(Ordering::SeqCst) != session {
                                phase(&app, &shared, "closing", None);
                                continue;
                            }
                            let cleanup_error = corrected.as_ref().err().copied();
                            if let Ok(mut s) = shared.lock() {
                                s.text = corrected.unwrap_or_else(|_| raw.clone());
                                s.raw_text = raw;
                            }
                            phase(&app, &shared, "preview", cleanup_error);
                        }
                        None => phase(&app, &shared, "error", Some("asr")),
                    }
                }
                Command::CleanupModel(path) => {
                    if shared.lock().map(|s| s.phase != "idle").unwrap_or(true) {
                        continue;
                    }
                    if let Ok(mut s) = shared.lock() {
                        s.cleanup_model_status = "checking".into();
                        s.error = None;
                    }
                    publish(&app, &shared);
                    let result = cleanup::verify_model(&path);
                    if let Ok(mut s) = shared.lock() {
                        if result.is_ok() {
                            let mut value = s.settings.clone();
                            value.cleanup_model_path = Some(path.to_string_lossy().into());
                            if persist(&settings_path, &value).is_ok() {
                                cleaner.reset();
                                s.settings = value;
                                s.cleanup_model_status = "linked".into();
                            } else {
                                s.error = Some("storage".into());
                            }
                        } else {
                            s.error = Some("cleanup_model".into());
                        }
                        if s.cleanup_model_status == "checking" {
                            s.cleanup_model_status = if s.settings.cleanup_model_path.is_some() {
                                "linked"
                            } else {
                                "missing"
                            }
                            .into();
                        }
                    }
                    publish(&app, &shared);
                }
                Command::RestoreRaw => {
                    if let Ok(mut s) = shared.lock() {
                        if s.phase == "preview" {
                            s.text = s.raw_text.clone();
                            s.error = None;
                            let text = s.text.clone();
                            if let Some(entry) =
                                s.history.iter_mut().find(|e| Some(e.id) == current_entry)
                            {
                                entry.edited = text;
                                let _ = persist(&history_path, &s.history);
                            }
                        }
                    }
                    publish(&app, &shared);
                }
                _ => {}
            }
        }
    });
    Ok(State {
        snapshot,
        sender,
        generation,
        cleanup_process,
    })
}
