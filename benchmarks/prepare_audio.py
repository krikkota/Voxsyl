#!/usr/bin/env python3
"""Make explicitly synthetic audio fixtures, not evidence of real mic quality."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import wave

ROOT = Path(__file__).resolve().parent.parent
DIRECTORY = ROOT / ".cache/benchmark/audio"
TEXT = "Привет Джон как твои дела ой не Джон а Мики давай увидимся сегодня в шестнадцать ой нет в пятнадцать дня"


def write_wav(path, frames):
    with wave.open(str(path), "wb") as writer:
        writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        writer.writeframes(frames)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthesize", action="store_true", help="Explicitly synthesize the owned demo text with installed macOS Milena")
    args = parser.parse_args()
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    source = DIRECTORY / "miki-source.txt"
    source.write_text(TEXT + "\n")
    voice = DIRECTORY / "miki-tts.wav"
    if args.synthesize:
        subprocess.run(["/usr/bin/say", "-v", "Milena", "-r", "170", "-f", str(source), "-o", str(voice),
                        "--file-format=WAVE", "--data-format=LEI16@16000"], check=True)
    with wave.open(str(voice), "rb") as reader:
        if (reader.getnchannels(), reader.getsampwidth(), reader.getframerate()) != (1, 2, 16000):
            raise ValueError("Expected 16 kHz mono PCM16 TTS fixture")
        frames = reader.readframes(reader.getnframes())
    if not frames: raise ValueError("TTS returned empty audio; no benchmark can use it")
    write_wav(DIRECTORY / "silence.wav", bytes(3 * 32000))
    # Deliberately repeated synthesis tests duration/cost only. A pause separates
    # phrases; these fixtures are not a 30/120-second natural speech evaluation.
    unit = frames + bytes(16000)
    for seconds in [30, 120]:
        count = seconds * 32000
        profile = (unit * ((count + len(unit)-1)//len(unit)))[:count]
        write_wav(DIRECTORY / f"synthetic-repeat-{seconds}s.wav", profile)
    manifest = {"scope":"Synthetic Milena speech plus silence; no user recording; repeated long clips are performance fixtures only.",
                "tts":{"voice":"Milena", "words_per_minute":170, "text":TEXT}, "files":[]}
    for name in ["miki-tts.wav", "silence.wav", "synthetic-repeat-30s.wav", "synthetic-repeat-120s.wav"]:
        path = DIRECTORY / name
        with wave.open(str(path), "rb") as reader: duration = reader.getnframes()/reader.getframerate()
        manifest["files"].append({"file":name, "bytes":path.stat().st_size, "sha256":hashlib.sha256(path.read_bytes()).hexdigest(), "seconds":duration})
    (ROOT / "outputs/benchmarks/audio-fixtures.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print("Prepared synthetic fixtures; microphone was not used.")


if __name__ == "__main__": main()
