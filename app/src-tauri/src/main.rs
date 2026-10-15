#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod audio_toolkit;
mod cleanup;
mod engine;
mod mac;
mod ui;
use engine::{Command, Settings, ShortcutStatus, Snapshot, State};
use handy_keys::{Hotkey, HotkeyManager, HotkeyState};
use std::{
    sync::atomic::Ordering,
    time::{Duration, Instant},
};
use tauri::{Emitter, Manager};
use tauri_nspanel::ManagerExt;

#[tauri::command]
fn snapshot(state: tauri::State<State>) -> Result<Snapshot, String> {
    state
        .snapshot
        .lock()
        .map(|s| s.clone())
        .map_err(|_| "state".into())
}
#[tauri::command]
fn save_settings(value: Settings, state: tauri::State<State>) -> Result<(), String> {
    value.shortcut.parse::<Hotkey>().map_err(|_| "hotkey")?;
    if state
        .snapshot
        .lock()
        .map(|s| !["idle", "preview", "error"].contains(&s.phase.as_str()))
        .unwrap_or(true)
    {
        return Err("busy".into());
    }
    state
        .sender
        .send(Command::Settings(value))
        .map_err(|_| "state".into())
}
#[tauri::command]
fn insert_text(text: String, state: tauri::State<State>) -> Result<(), String> {
    state
        .sender
        .send(Command::Insert(text))
        .map_err(|_| "state".into())
}
#[tauri::command]
fn close_preview(state: tauri::State<State>) -> Result<(), String> {
    state.generation.fetch_add(1, Ordering::SeqCst);
    state
        .sender
        .send(Command::Cancel)
        .map_err(|_| "state".into())
}
#[tauri::command]
async fn choose_cleanup_model(
    app: tauri::AppHandle,
    state: tauri::State<'_, State>,
) -> Result<(), String> {
    if state
        .snapshot
        .lock()
        .map(|s| s.phase != "idle")
        .unwrap_or(true)
    {
        return Err("busy".into());
    }
    let sender = state.sender.clone();
    let selected = tauri::async_runtime::spawn_blocking(move || mac::choose_cleanup_model(&app))
        .await
        .map_err(|_| "state")??;
    if let Some(path) = selected {
        sender
            .send(Command::CleanupModel(path))
            .map_err(|_| "state")?;
    }
    Ok(())
}
#[tauri::command]
fn restore_raw_text(state: tauri::State<State>) -> Result<(), String> {
    state
        .sender
        .send(Command::RestoreRaw)
        .map_err(|_| "state".into())
}
#[tauri::command]
fn overlay_hidden(app: tauri::AppHandle, state: tauri::State<State>) {
    if let Ok(mut s) = state.snapshot.lock() {
        if s.phase == "closing" {
            s.phase = "idle".into();
            s.text.clear();
            s.raw_text.clear();
            s.error = None;
            if let Ok(p) = app.get_webview_panel("overlay") {
                p.hide();
            }
            let _ = app.emit("snapshot", s.clone());
        }
    }
}
#[tauri::command]
fn delete_entry(id: u64, state: tauri::State<State>) -> Result<(), String> {
    state
        .sender
        .send(Command::Delete(id))
        .map_err(|_| "state".into())
}
#[tauri::command]
fn clear_history(state: tauri::State<State>) -> Result<(), String> {
    state
        .sender
        .send(Command::Clear)
        .map_err(|_| "state".into())
}
#[tauri::command]
fn input_devices() -> Result<Vec<String>, String> {
    audio_toolkit::audio::list_input_devices()
        .map(|devices| devices.into_iter().map(|d| d.name).collect())
        .map_err(|_| "microphone".into())
}
#[tauri::command]
fn copy_text(text: String) -> Result<(), String> {
    let pb = objc2_app_kit::NSPasteboard::generalPasteboard();
    pb.clearContents();
    if unsafe {
        pb.setString_forType(
            &objc2_foundation::NSString::from_str(&text),
            objc2_app_kit::NSPasteboardTypeString,
        )
    } {
        Ok(())
    } else {
        Err("clipboard".into())
    }
}
#[tauri::command]
fn open_permission_settings() -> Result<(), String> {
    std::process::Command::new("/usr/bin/open")
        .arg("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
        .status()
        .map(|_| ())
        .map_err(|_| "permission".into())
}
fn shortcut_status(app: &tauri::AppHandle, status: ShortcutStatus) {
    if let Ok(mut snapshot) = app.state::<State>().snapshot.lock() {
        if snapshot.shortcut_status == status {
            return;
        }
        snapshot.shortcut_ready = matches!(status, ShortcutStatus::Ready);
        snapshot.shortcut_status = status;
        let _ = app.emit("snapshot", snapshot.clone());
    }
}
fn shortcuts(app: tauri::AppHandle) {
    std::thread::spawn(move || loop {
        if !mac::trusted() {
            shortcut_status(&app, ShortcutStatus::PermissionRequired);
            std::thread::sleep(Duration::from_secs(2));
            continue;
        }
        let manager = match HotkeyManager::new_with_blocking() {
            Ok(m) => m,
            Err(error) => {
                shortcut_status(
                    &app,
                    if matches!(error, handy_keys::Error::AccessibilityNotGranted) {
                        ShortcutStatus::PermissionRequired
                    } else {
                        ShortcutStatus::ListenerUnavailable
                    },
                );
                std::thread::sleep(Duration::from_secs(2));
                continue;
            }
        };
        let state = app.state::<State>();
        let mut binding = None;
        let mut name = String::new();
        let mut escape = None;
        let mut held = false;
        let mut checked_permission = Instant::now();
        loop {
            if checked_permission.elapsed() >= Duration::from_secs(1) {
                checked_permission = Instant::now();
                if !mac::trusted() {
                    let recording = state
                        .snapshot
                        .lock()
                        .map(|s| ["arming", "recording"].contains(&s.phase.as_str()))
                        .unwrap_or(false);
                    if recording {
                        state.generation.fetch_add(1, Ordering::SeqCst);
                        let _ = state.sender.send(Command::Cancel);
                    }
                    shortcut_status(&app, ShortcutStatus::PermissionRequired);
                    // Dropping the manager removes the old event tap. The outer
                    // loop creates a fresh one when the user restores access.
                    break;
                }
            }
            let (shortcut, phase, hold) = match state.snapshot.lock() {
                Ok(s) => (
                    s.settings.shortcut.clone(),
                    s.phase.clone(),
                    s.settings.hold,
                ),
                Err(_) => return,
            };
            if shortcut != name {
                if let Some(id) = binding.take() {
                    let _ = manager.unregister(id);
                }
                name = shortcut;
                binding = name
                    .parse::<Hotkey>()
                    .ok()
                    .and_then(|k| manager.register(k).ok());
                held = false;
                shortcut_status(
                    &app,
                    if binding.is_some() {
                        ShortcutStatus::Ready
                    } else {
                        ShortcutStatus::RegistrationFailed
                    },
                );
            }
            let active = phase != "idle";
            if active && escape.is_none() {
                escape = "escape"
                    .parse::<Hotkey>()
                    .ok()
                    .and_then(|k| manager.register(k).ok())
            }
            if !active {
                if let Some(id) = escape.take() {
                    let _ = manager.unregister(id);
                }
            }
            while let Some(event) = manager.try_recv() {
                if Some(event.id) == escape && event.state == HotkeyState::Pressed {
                    state.generation.fetch_add(1, Ordering::SeqCst);
                    let _ = state.sender.send(Command::Cancel);
                } else if Some(event.id) == binding {
                    if event.state == HotkeyState::Pressed && !held {
                        held = true;
                        let id = if phase == "idle" {
                            state.generation.fetch_add(1, Ordering::SeqCst) + 1
                        } else {
                            state.generation.load(Ordering::SeqCst)
                        };
                        let _ = state.sender.send(Command::Press(id));
                    } else if event.state == HotkeyState::Released {
                        held = false;
                        if hold && ["idle", "arming"].contains(&phase.as_str()) {
                            state.generation.fetch_add(1, Ordering::SeqCst);
                            let _ = state.sender.send(Command::Cancel);
                        } else {
                            let _ = state.sender.send(Command::Release);
                        }
                    }
                }
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    });
}
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let test_file = args
        .windows(2)
        .find(|pair| pair[0] == "--test-wav")
        .map(|pair| std::path::PathBuf::from(&pair[1]));
    let test_target = if args.iter().any(|arg| arg == "--test-paste-into-textedit") {
        if test_file.is_none() {
            eprintln!("--test-paste-into-textedit requires --test-wav");
            std::process::exit(2);
        }
        Some(())
    } else {
        None
    };
    let test_stop_cursor = args.iter().any(|arg| arg == "--test-stop-cursor");
    if test_stop_cursor && test_target.is_none() {
        eprintln!("--test-stop-cursor requires --test-paste-into-textedit and --test-wav");
        std::process::exit(2);
    }
    let app = tauri::Builder::default()
        .plugin(tauri_nspanel::init())
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            ui::show_main(app)
        }))
        .invoke_handler(tauri::generate_handler![
            snapshot,
            save_settings,
            insert_text,
            close_preview,
            overlay_hidden,
            delete_entry,
            clear_history,
            open_permission_settings,
            input_devices,
            copy_text,
            choose_cleanup_model,
            restore_raw_text
        ])
        .setup(move |app| {
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            let handle = app.handle().clone();
            let test_target = if test_target.is_some() {
                match mac::textedit_test_target() {
                    Some(pid) => Some(pid),
                    None => {
                        eprintln!("Open TextEdit with voxsyl-insertion-test.txt first.");
                        std::process::exit(2);
                    }
                }
            } else {
                None
            };
            tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::App("index.html".into()),
            )
            .title("Voxsyl")
            .theme(Some(tauri::Theme::Dark))
            .inner_size(900.0, 620.0)
            .min_inner_size(700.0, 500.0)
            .build()?;
            ui::create_overlay(&handle)?;
            app.manage(engine::initialize(handle.clone()).map_err(std::io::Error::other)?);
            if let Some(path) = test_file {
                let _ = app.state::<State>().sender.send(Command::TestFile(
                    path,
                    test_target,
                    test_stop_cursor,
                ));
            }
            use tauri::{
                image::Image,
                menu::{Menu, MenuItem},
                tray::TrayIconBuilder,
            };
            let settings =
                MenuItem::with_id(app, "settings", "Настройки Voxsyl…", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Завершить Voxsyl", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&settings, &quit])?;
            let mut pixels = vec![0_u8; 32 * 32 * 4];
            for y in 0..32 {
                for x in 0..32 {
                    let dx = x as f32 - 15.5;
                    let dy = y as f32 - 15.5;
                    let angle = dy.atan2(dx);
                    let r = 10.0 + (angle * 3.0).sin();
                    let alpha = ((1.8 - ((dx * dx + dy * dy).sqrt() - r).abs()) * 255.0)
                        .clamp(0.0, 255.0) as u8;
                    pixels[(y * 32 + x) * 4 + 3] = alpha;
                }
            }
            TrayIconBuilder::new()
                .icon(Image::new_owned(pixels, 32, 32))
                .icon_as_template(true)
                .tooltip("Voxsyl")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "settings" => ui::show_main(app),
                    "quit" => {
                        let _ = app.state::<State>().sender.send(Command::Shutdown);
                        app.exit(0)
                    }
                    _ => {}
                })
                .build(app)?;
            shortcuts(handle);
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("Voxsyl initialization failed");
    app.run(|app, event| {
        if matches!(
            event,
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
        ) {
            let state = app.state::<State>();
            state.generation.fetch_add(1, Ordering::SeqCst);
            cleanup::stop(&state.cleanup_process);
            let _ = state.sender.send(Command::Shutdown);
        }
        if matches!(event, tauri::RunEvent::Reopen { .. }) {
            ui::show_main(app);
        }
    });
}
