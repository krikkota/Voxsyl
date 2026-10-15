"""Advance the local app patch version consistently before packaging."""
import json
from pathlib import Path


def bump_version(app: Path) -> str:
    package_path = app / 'package.json'
    config_path = app / 'src-tauri/tauri.conf.json'
    cargo_path = app / 'src-tauri/Cargo.toml'
    lock_path = app / 'src-tauri/Cargo.lock'
    package = json.loads(package_path.read_text())
    config = json.loads(config_path.read_text())
    old = package['version']
    major, minor, patch = map(int, old.split('.'))
    new = f'{major}.{minor}.{patch + 1}'
    cargo = cargo_path.read_text()
    lock = lock_path.read_text()
    cargo_old = f'version = "{old}"'
    lock_old = f'name = "voxsyl"\nversion = "{old}"'
    if config['version'] != old or cargo_old not in cargo.split('[build-dependencies]')[0] or lock_old not in lock:
        raise RuntimeError('App version manifests disagree; reconcile them before building.')
    # Compute every replacement before writing any of the version manifests.
    package['version'] = config['version'] = new
    cargo = cargo.replace(cargo_old, f'version = "{new}"', 1)
    lock = lock.replace(lock_old, f'name = "voxsyl"\nversion = "{new}"', 1)
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n')
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
    cargo_path.write_text(cargo)
    lock_path.write_text(lock)
    return new
