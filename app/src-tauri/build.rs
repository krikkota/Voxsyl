fn main() {
    tauri_build::build();
    println!("cargo:rustc-link-arg=-Wl,-rpath,@executable_path/../Resources/runtime/ort/lib");
}
