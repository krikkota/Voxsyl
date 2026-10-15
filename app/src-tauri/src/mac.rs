use enigo::{Direction, Enigo, Key, Keyboard};
use objc2::{rc::Retained, runtime::ProtocolObject};
use objc2_app_kit::{
    NSApplicationActivationOptions, NSOpenPanel, NSPasteboard, NSPasteboardItem,
    NSPasteboardTypeString, NSPasteboardWriting, NSRunningApplication, NSWorkspace,
};
use objc2_foundation::{NSArray, NSData, NSString};
use std::{ffi::c_void, path::Path, sync::mpsc, time::Duration};
use tauri::AppHandle;
use tauri_nspanel::ManagerExt;

#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn AXIsProcessTrusted() -> bool;
    fn AXUIElementCreateApplication(pid: i32) -> *const c_void;
    fn AXUIElementCopyAttributeValue(
        element: *const c_void,
        attribute: *const c_void,
        value: *mut *const c_void,
    ) -> i32;
    fn AXUIElementSetAttributeValue(
        element: *const c_void,
        attribute: *const c_void,
        value: *const c_void,
    ) -> i32;
}
#[link(name = "CoreFoundation", kind = "framework")]
extern "C" {
    fn CFRelease(value: *const c_void);
    fn CFEqual(a: *const c_void, b: *const c_void) -> bool;
    static kCFBooleanTrue: *const c_void;
}
pub fn trusted() -> bool {
    unsafe { AXIsProcessTrusted() }
}
pub fn frontmost_pid() -> Option<i32> {
    NSWorkspace::sharedWorkspace()
        .frontmostApplication()
        .map(|app| app.processIdentifier())
}
pub fn insertion_pid() -> Option<i32> {
    frontmost_pid().filter(|pid| *pid != std::process::id() as i32)
}
// Owned CF handles cross the actor channel as addresses. All AX reads/writes
// happen on the main thread; Drop releases the owned CopyAttribute references.
pub struct InsertionFocus {
    pub pid: i32,
    field: usize,
    selection: usize,
}
impl Drop for InsertionFocus {
    fn drop(&mut self) {
        unsafe {
            CFRelease(self.field as *const c_void);
            if self.selection != 0 {
                CFRelease(self.selection as *const c_void);
            }
        }
    }
}
pub fn capture_insertion_focus(app: &AppHandle) -> Option<InsertionFocus> {
    on_main(app, || {
        let pid = insertion_pid().ok_or("paste")?;
        read_insertion_focus(pid)
    })
    .ok()
}
pub fn capture_test_focus(app: &AppHandle, pid: i32) -> Option<InsertionFocus> {
    on_main(app, move || {
        if !test_document_matches(pid) {
            return Err("paste".into());
        }
        read_insertion_focus(pid)
    })
    .ok()
}
fn read_insertion_focus(pid: i32) -> Result<InsertionFocus, String> {
    unsafe {
        let application = AXUIElementCreateApplication(pid);
        if application.is_null() {
            return Err("paste".into());
        }
        let mut field = std::ptr::null();
        let status = AXUIElementCopyAttributeValue(
            application,
            Retained::as_ptr(&NSString::from_str("AXFocusedUIElement")).cast(),
            &mut field,
        );
        CFRelease(application);
        if status != 0 || field.is_null() {
            return Err("paste".into());
        }
        let mut selection = std::ptr::null();
        let _ = AXUIElementCopyAttributeValue(
            field,
            Retained::as_ptr(&NSString::from_str("AXSelectedTextRange")).cast(),
            &mut selection,
        );
        Ok(InsertionFocus {
            pid,
            field: field as usize,
            selection: selection as usize,
        })
    }
}
fn restore_insertion_focus(focus: &InsertionFocus) -> Result<(), String> {
    unsafe {
        let field = focus.field as *const c_void;
        if AXUIElementSetAttributeValue(
            field,
            Retained::as_ptr(&NSString::from_str("AXFocused")).cast(),
            kCFBooleanTrue,
        ) != 0
        {
            return Err("paste".into());
        }
        if focus.selection != 0
            && AXUIElementSetAttributeValue(
                field,
                Retained::as_ptr(&NSString::from_str("AXSelectedTextRange")).cast(),
                focus.selection as *const c_void,
            ) != 0
        {
            return Err("paste".into());
        }
        let application = AXUIElementCreateApplication(focus.pid);
        if application.is_null() {
            return Err("paste".into());
        }
        let mut current = std::ptr::null();
        let status = AXUIElementCopyAttributeValue(
            application,
            Retained::as_ptr(&NSString::from_str("AXFocusedUIElement")).cast(),
            &mut current,
        );
        CFRelease(application);
        let matches = status == 0 && !current.is_null() && CFEqual(current, field);
        if !current.is_null() {
            CFRelease(current);
        }
        if matches {
            Ok(())
        } else {
            Err("paste".into())
        }
    }
}
// Explicit developer integration test: only the known disposable TextEdit
// document may receive fixture output, and only after the preview is confirmed.
pub fn textedit_test_target() -> Option<i32> {
    let running = NSRunningApplication::runningApplicationsWithBundleIdentifier(
        &NSString::from_str("com.apple.TextEdit"),
    );
    (running.len() == 1)
        .then(|| running.firstObject().map(|app| app.processIdentifier()))
        .flatten()
}
fn test_document_matches(pid: i32) -> bool {
    unsafe {
        let application = AXUIElementCreateApplication(pid);
        if application.is_null() {
            return false;
        }
        let mut window = std::ptr::null();
        let status = AXUIElementCopyAttributeValue(
            application,
            Retained::as_ptr(&NSString::from_str("AXFocusedWindow")).cast(),
            &mut window,
        );
        CFRelease(application);
        if status != 0 || window.is_null() {
            return false;
        }
        let mut title = std::ptr::null();
        let status = AXUIElementCopyAttributeValue(
            window,
            Retained::as_ptr(&NSString::from_str("AXTitle")).cast(),
            &mut title,
        );
        CFRelease(window);
        if status != 0 || title.is_null() {
            return false;
        }
        let matches = CFEqual(
            title,
            Retained::as_ptr(&NSString::from_str("voxsyl-insertion-test.txt")).cast(),
        );
        CFRelease(title);
        matches
    }
}
pub fn cue(resources: &Path, event: &str) {
    let name = if event == "activate" {
        "voxsyl-activate-v3-gentle.wav"
    } else {
        "voxsyl-deactivate-v3-gentle.wav"
    };
    let path = resources.join("sounds").join(name);
    std::thread::spawn(move || {
        let _ = std::process::Command::new("/usr/bin/afplay")
            .arg(path)
            .status();
    });
}
fn on_main<T: Send + 'static>(
    app: &AppHandle,
    f: impl FnOnce() -> Result<T, String> + Send + 'static,
) -> Result<T, String> {
    let (tx, rx) = mpsc::channel();
    app.run_on_main_thread(move || {
        let _ = tx.send(f());
    })
    .map_err(|_| "paste")?;
    rx.recv_timeout(Duration::from_secs(10))
        .map_err(|_| "paste".to_string())?
}
pub fn choose_cleanup_model(app: &AppHandle) -> Result<Option<std::path::PathBuf>, String> {
    // Unlike paste, a user-owned file dialog must not time out while choosing.
    let (tx, rx) = mpsc::channel();
    app.run_on_main_thread(move || {
        let result = objc2::MainThreadMarker::new().and_then(|mtm| {
            let panel = NSOpenPanel::openPanel(mtm);
            panel.setCanChooseFiles(true);
            panel.setCanChooseDirectories(false);
            panel.setAllowsMultipleSelection(false);
            panel.setTitle(Some(&NSString::from_str("Qwen3.5-4B · GGUF")));
            #[allow(deprecated)]
            panel.setAllowedFileTypes(Some(&NSArray::from_slice(&[&*NSString::from_str("gguf")])));
            if panel.runModal() == 1 {
                panel
                    .URL()
                    .and_then(|url| url.path())
                    .map(|p| std::path::PathBuf::from(p.to_string()))
            } else {
                None
            }
        });
        let _ = tx.send(result);
    })
    .map_err(|_| "state")?;
    rx.recv().map_err(|_| "state".into())
}
fn safe_field(pid: i32) -> bool {
    unsafe {
        let element = AXUIElementCreateApplication(pid);
        if element.is_null() {
            return false;
        }
        let attribute = NSString::from_str("AXFocusedUIElement");
        let mut focused = std::ptr::null();
        let status = AXUIElementCopyAttributeValue(
            element,
            Retained::as_ptr(&attribute).cast(),
            &mut focused,
        );
        CFRelease(element);
        if status != 0 || focused.is_null() {
            return false;
        }
        let attr = NSString::from_str("AXSubrole");
        let mut role = std::ptr::null();
        let _ = AXUIElementCopyAttributeValue(focused, Retained::as_ptr(&attr).cast(), &mut role);
        CFRelease(focused);
        if role.is_null() {
            return true;
        }
        let secure = NSString::from_str("AXSecureTextField");
        let result = !CFEqual(role, Retained::as_ptr(&secure).cast());
        CFRelease(role);
        result
    }
}
type ClipboardSnapshot = Vec<Vec<(String, Vec<u8>)>>;
fn snapshot_clipboard(pasteboard: &NSPasteboard) -> Result<ClipboardSnapshot, String> {
    let mut snapshot = vec![];
    let mut bytes = 0;
    if let Some(items) = pasteboard.pasteboardItems() {
        for item in items.iter() {
            let mut formats = vec![];
            for kind in item.types().iter() {
                let data = item.dataForType(&kind).ok_or("paste")?.to_vec();
                bytes += data.len();
                if bytes > 32 * 1024 * 1024 {
                    return Err("paste".into());
                }
                formats.push((kind.to_string(), data));
            }
            snapshot.push(formats);
        }
    }
    Ok(snapshot)
}
fn restore_clipboard(pasteboard: &NSPasteboard, snapshot: ClipboardSnapshot) -> Result<(), String> {
    let items: Vec<Retained<NSPasteboardItem>> = snapshot
        .into_iter()
        .map(|formats| {
            let item = NSPasteboardItem::new();
            for (kind, data) in formats {
                item.setData_forType(&NSData::with_bytes(&data), &NSString::from_str(&kind));
            }
            item
        })
        .collect();
    let objects: Vec<&ProtocolObject<dyn NSPasteboardWriting>> = items
        .iter()
        .map(|item| ProtocolObject::from_ref(&**item))
        .collect();
    pasteboard.clearContents();
    if objects.is_empty() {
        return Ok(());
    }
    if !pasteboard.writeObjects(&NSArray::from_slice(&objects)) {
        return Err("paste".into());
    }
    Ok(())
}
pub fn paste(
    app: &AppHandle,
    pid: Option<i32>,
    text: String,
    test_document: bool,
    focus: Option<InsertionFocus>,
) -> Result<(), String> {
    if test_document {
        eprintln!(
            "Voxsyl paste test: target_present={}, trusted={}",
            pid.is_some(),
            trusted()
        );
    }
    let pid = pid
        .filter(|pid| *pid != std::process::id() as i32)
        .ok_or("paste")?;
    if !trusted() {
        return Err("paste".into());
    }
    let owner = app.clone();
    on_main(app, move || {
        if let Ok(panel) = owner.get_webview_panel("overlay") {
            panel.resign_key_window();
        }
        let target =
            NSRunningApplication::runningApplicationWithProcessIdentifier(pid).ok_or("paste")?;
        let bundle = target
            .bundleIdentifier()
            .map(|s| s.to_string())
            .unwrap_or_default();
        if test_document {
            eprintln!(
                "Voxsyl paste test: expected_app={}",
                bundle == "com.apple.TextEdit"
            );
        }
        if test_document && bundle != "com.apple.TextEdit" {
            return Err("paste".into());
        }
        if !target.activateWithOptions(NSApplicationActivationOptions::empty()) {
            return Err("paste".into());
        }
        Ok(())
    })?;
    std::thread::sleep(Duration::from_millis(160));
    let (snapshot, count) = on_main(app, move || {
        if let Some(focus) = &focus {
            if focus.pid != pid {
                return Err("paste".into());
            }
            restore_insertion_focus(focus)?;
        }
        let focused = frontmost_pid() == Some(pid);
        let editable = safe_field(pid);
        let document = !test_document || test_document_matches(pid);
        if test_document {
            eprintln!("Voxsyl paste test: target_active={focused}, safe_field={editable}, expected_document={document}");
        }
        if !focused || !editable || !document {
            return Err("paste".into());
        }
        let pb = NSPasteboard::generalPasteboard();
        let snapshot = snapshot_clipboard(&pb)?;
        pb.clearContents();
        if !unsafe { pb.setString_forType(&NSString::from_str(&text), NSPasteboardTypeString) } {
            let _ = restore_clipboard(&pb, snapshot);
            return Err("paste".into());
        }
        Ok((snapshot, pb.changeCount()))
    })?;
    let result = (|| {
        if frontmost_pid() != Some(pid) {
            return Err("paste".to_string());
        }
        let mut keyboard = Enigo::new(&enigo::Settings::default()).map_err(|_| "paste")?;
        keyboard
            .key(Key::Meta, Direction::Press)
            .map_err(|_| "paste")?;
        // kVK_ANSI_V (0x09) is a physical key. Unicode lookup becomes keycode 0
        // when the current layout has no Latin v, sending Command-A instead.
        let pressed = keyboard.raw(0x09, Direction::Click);
        let released = keyboard.key(Key::Meta, Direction::Release);
        pressed.and(released).map_err(|_| "paste".to_string())
    })();
    std::thread::sleep(Duration::from_millis(450));
    on_main(app, move || {
        let pb = NSPasteboard::generalPasteboard();
        if pb.changeCount() == count {
            restore_clipboard(&pb, snapshot)?;
        }
        Ok(())
    })?;
    result
}
