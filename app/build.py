#!/usr/bin/env python3
"""Build the local macOS prototype with pinned resources. Not a release pipeline."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dev_signing import load_identity, sign
from versioning import bump_version

APP = Path(__file__).resolve().parent
ROOT = APP.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--node', default='node', help='Node executable; installed package dependencies are required')
    args = parser.parse_args()
    # Never silently fall back to a build-specific ad-hoc identity: doing so
    # invalidates previously granted Accessibility access after every update.
    load_identity()
    running = subprocess.run(['/usr/bin/pgrep', '-x', 'voxsyl'], capture_output=True)
    if running.returncode == 0:
        raise SystemExit('Quit Voxsyl with Command-Q before rebuilding. The running app must not be replaced.')
    if running.returncode != 1:
        raise SystemExit('Could not check whether Voxsyl is running. Build needs permission to check its own process first.')
    print(f'Building Voxsyl {bump_version(APP)}', flush=True)
    # Verify and re-extract model/runtime from pinned archives before bundling.
    subprocess.run([sys.executable, str(ROOT/'benchmarks/prepare.py'), '--only', 'gigaam,ort,llama', '--offline'], check=True)
    for script, options in [('typescript/bin/tsc', []), ('vite/bin/vite.js', ['build'])]:
        subprocess.run([args.node, str(APP/'node_modules'/script), *options], cwd=APP, check=True)
    subprocess.run([sys.executable, str(APP/'collect_notices.py')], check=True)
    env = dict(os.environ)
    env.update({'CARGO_HOME':str(ROOT/'.cache/cargo'), 'ORT_LIB_PATH':str(ROOT/'.cache/benchmark/runtime/ort/onnxruntime-osx-arm64-1.24.2/lib'),
                'ORT_PREFER_DYNAMIC_LINK':'1', 'ORT_SKIP_DOWNLOAD':'1', 'MACOSX_DEPLOYMENT_TARGET':'14.0'})
    bundle=APP/'src-tauri/target/debug/bundle/macos/Voxsyl.app'
    # Preserve the last usable signed bundle if compilation or signing fails.
    with tempfile.TemporaryDirectory(prefix='voxsyl-bundle-backup-', dir=ROOT/'.cache') as temporary:
        previous = Path(temporary)/'Voxsyl.app'
        if bundle.exists(): bundle.replace(previous)
        try:
            subprocess.run([args.node, str(APP/'node_modules/@tauri-apps/cli/tauri.js'), 'build', '--debug', '--bundles', 'app'], cwd=APP, env=env, check=True)
            sign(bundle)
        except BaseException:
            if bundle.exists(): shutil.rmtree(bundle)
            if previous.exists(): previous.replace(bundle)
            raise
    print(bundle)


if __name__ == '__main__': main()
