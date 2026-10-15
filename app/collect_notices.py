#!/usr/bin/env python3
"""Collect installed dependency license files; inventory, not legal approval."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess

APP = Path(__file__).resolve().parent
ROOT = APP.parent
OUT = ROOT / 'licenses/dependencies'


def collect(ecosystem, name, version, directory, declared, source, license_file=None):
    directory = Path(directory).resolve()
    candidates = list(directory.iterdir())
    for sub in ['licenses', 'LICENSES']:
        if (directory/sub).is_dir(): candidates.extend((directory/sub).iterdir())
    if license_file:
        candidate = (directory/license_file).resolve()
        if candidate.is_relative_to(directory): candidates.append(candidate)
    files = []
    for path in sorted(set(candidates)):
        if not path.is_file() or not path.resolve().is_relative_to(directory): continue
        stem = path.name.upper()
        if not (stem.startswith(('LICENSE', 'LICENCE', 'COPYING', 'NOTICE', 'COPYRIGHT')) or (license_file and path.resolve() == (directory/license_file).resolve())): continue
        if path.stat().st_size > 2*1024*1024: continue
        target = OUT/ecosystem/(name.replace('/', '__')+'-'+version)/path.relative_to(directory)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        files.append({'path':str(target.relative_to(ROOT)), 'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    return {'ecosystem':ecosystem, 'name':name, 'version':version, 'declared_license':declared,
            'source':source, 'files':files, 'status':'files_collected_not_audited' if files else 'license_file_not_found_manual_review_required'}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CARGO_HOME=str(ROOT/'.cache/cargo'))
    base = ['cargo', '--offline']
    manifest = str(APP/'src-tauri/Cargo.toml')
    tree = subprocess.check_output(base+['tree','--locked','--manifest-path',manifest,'--target','aarch64-apple-darwin','--edges','normal,build','--prefix','none','--format','{p}'], env=env, text=True)
    selected = {' '.join(line.split()[:2]) for line in tree.splitlines()}
    metadata = json.loads(subprocess.check_output(base+['metadata','--locked','--manifest-path',manifest,'--format-version','1','--filter-platform','aarch64-apple-darwin'], env=env))
    entries = []
    for package in metadata['packages']:
        if package['name']=='voxsyl' or f"{package['name']} v{package['version']}" not in selected: continue
        entries.append(collect('rust', package['name'], package['version'], Path(package['manifest_path']).parent,
                               package.get('license'), package.get('source'), package.get('license_file')))
    # Over-inclusive frontend inventory also retains build-tool notices; it is
    # not presented as a precise list of modules inside the JavaScript bundle.
    seen = set()
    npm_paths = sorted(set((APP/'node_modules/.pnpm').glob('*/node_modules/*/package.json')) |
                       set((APP/'node_modules/.pnpm').glob('*/node_modules/@*/*/package.json')))
    for path in npm_paths:
        package = json.loads(path.read_text())
        identity = (package['name'], package['version'])
        if identity in seen: continue
        seen.add(identity)
        entries.append(collect('npm', *identity, path.parent, package.get('license'), 'npm registry / pnpm-lock.yaml'))
    report={'scope':'Automatic collection of installed license/notice files. Rust normal+build macOS dependency graph; over-inclusive npm inventory. Not a compatibility or completeness audit. Native ONNX notices and font license are supplied separately.',
            'cargo_lock_sha256':hashlib.sha256((APP/'src-tauri/Cargo.lock').read_bytes()).hexdigest(),
            'pnpm_lock_sha256':hashlib.sha256((APP/'pnpm-lock.yaml').read_bytes()).hexdigest(),
            'packages':entries}
    (OUT/'inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    missing=[p for p in entries if not p['files']]
    (OUT/'MANUAL_REVIEW.md').write_text('# Автоматический сбор уведомлений\n\nЭто инвентаризация, а не завершённый аудит лицензий. Источники и SHA файлов находятся в inventory.json. Файлы не переписывались. Пакеты без найденного текста требуют ручной проверки:\n\n'+''.join(f"- {p['ecosystem']}: {p['name']} {p['version']} — {p['declared_license']}\n" for p in missing))
    print(f'Collected notices for {len(entries)} installed packages; {len(missing)} need manual file lookup.')


if __name__=='__main__': main()
