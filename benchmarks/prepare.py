#!/usr/bin/env python3
"""Fetch pinned public benchmark artifacts. No inference, mic or telemetry."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache/benchmark"


def verified(path, artifact):
    if not path.is_file() or path.stat().st_size != artifact["bytes"]:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == artifact["sha256"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-comparisons", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--only", help="Comma-separated artifact ids; overrides the default core set")
    args = parser.parse_args()
    wanted = set(args.only.split(",")) if args.only else None
    artifacts = json.loads((ROOT / "benchmarks/artifacts.json").read_text())["artifacts"]
    if wanted and not wanted.issubset({a["id"] for a in artifacts}):
        raise ValueError("Unknown artifact id")
    for artifact in artifacts:
        if wanted is not None:
            if artifact["id"] not in wanted: continue
        elif artifact["group"] != "core" and not args.include_comparisons:
            continue
        path = CACHE / artifact["path"]
        if not verified(path, artifact):
            if args.offline:
                raise ValueError(f"Missing or corrupt artifact: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".download")
            print("Downloading", artifact["id"], artifact["bytes"], "bytes", flush=True)
            with urllib.request.urlopen(artifact["url"], timeout=60) as response, temporary.open("wb") as stream:
                shutil.copyfileobj(response, stream, length=1024*1024)
            if not verified(temporary, artifact):
                raise ValueError(f"Checksum mismatch: {temporary}; file has not been promoted")
            temporary.replace(path)
        print("Verified", artifact["id"], flush=True)
        if artifact.get("extract_to"):
            target = CACHE / artifact["extract_to"]
            target.mkdir(parents=True, exist_ok=True)
            with tarfile.open(path) as archive:
                archive.extractall(target, filter="data")


if __name__ == "__main__": main()
