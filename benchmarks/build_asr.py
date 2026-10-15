#!/usr/bin/env python3
"""Build the Handy-compatible ASR bench without touching global Cargo/ORT caches."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parent.parent
environment = os.environ.copy()
environment.update({
    "CARGO_HOME":str(ROOT / ".cache/cargo"),
    "ORT_LIB_PATH":str(ROOT / ".cache/benchmark/runtime/ort/onnxruntime-osx-arm64-1.24.2/lib"),
    "ORT_PREFER_DYNAMIC_LINK":"1", "ORT_SKIP_DOWNLOAD":"1",
    "MACOSX_DEPLOYMENT_TARGET":"14.0",
})
subprocess.run(["cargo", "build", "--release", "--locked", "--manifest-path", str(ROOT / "benchmarks/asr-runner/Cargo.toml")], cwd=ROOT, env=environment, check=True)
