use tauri::{AppHandle, Manager, WebviewUrl};
use tauri_nspanel::{
    tauri_panel, CollectionBehavior, ManagerExt, PanelBuilder, PanelLevel, StyleMask,
};
tauri_panel! { panel!(VoxsylPanel {config:{can_become_key_window:true,is_floating_panel:true}}) }

pub fn create_overlay(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let panel = PanelBuilder::<_, VoxsylPanel>::new(app, "overlay")
        .url(WebviewUrl::App("overlay.html".into()))
        .title("Voxsyl")
        .size(tauri::Size::Logical(tauri::LogicalSize::new(400.0, 260.0)))
        .level(PanelLevel::Status)
        .has_shadow(false)
        .transparent(true)
        .no_activate(true)
        .corner_radius(0.0)
        .style_mask(StyleMask::empty().borderless().nonactivating_panel())
        .with_window(|w| {
            w.decorations(false)
                .transparent(true)
                .focusable(true)
                .skip_taskbar(true)
                .visible(false)
        })
        .collection_behavior(
            CollectionBehavior::new()
                .can_join_all_spaces()
                .full_screen_auxiliary(),
        )
        .build()?;
    panel.hide();
    Ok(())
}
pub fn show_overlay(app: &AppHandle, key: bool) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if let Some(w) = handle.get_webview_window("overlay") {
            if let Ok(Some(monitor)) = w.current_monitor().or_else(|_| handle.primary_monitor()) {
                let area = monitor.work_area();
                let scale = monitor.scale_factor();
                let width = (area.size.width as f64 / scale).clamp(300.0, 400.0);
                let height = (area.size.height as f64 / scale * 0.32).clamp(200.0, 260.0);
                let _ = w.set_size(tauri::LogicalSize::new(width, height));
                let x =
                    area.position.x as f64 / scale + (area.size.width as f64 / scale - width) / 2.0;
                let y =
                    area.position.y as f64 / scale + area.size.height as f64 / scale - height - 8.0;
                let _ = w.set_position(tauri::LogicalPosition::new(x, y));
            }
        }
        if let Ok(panel) = handle.get_webview_panel("overlay") {
            if key {
                panel.show_and_make_key()
            } else {
                panel.show()
            }
        }
    });
}
pub fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
}
