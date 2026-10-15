#!/usr/bin/env python3
"""WAV → resident GigaAM → owned offline LLM; developer experiment, not the app.

No microphone capture. Explicit input WAVs only. Audio/text reports stay local.
Long inputs are split for a performance profile, not a production VAD algorithm.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache/benchmark"


def read_event(stream, event):
    while line := stream.readline():
        row = json.loads(line)
        if row.get("event") == "error": raise RuntimeError(row.get("error"))
        if row.get("event") == event: return row
    raise RuntimeError("ASR process ended before its response")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", nargs="+", type=Path, help="Explicit 16 kHz mono PCM16 WAVs; no recording")
    parser.add_argument("--output", default="outputs/benchmarks/audio-pipeline.json", type=Path)
    parser.add_argument("--model", default=".cache/benchmark/models/Vikhr-Qwen-2.5-1.5b-Instruct-Q4_K_M.gguf")
    parser.add_argument("--prompt", default="benchmarks/prompts/conservative-v1.txt")
    parser.add_argument("--temperature", default=0.0, type=float)
    parser.add_argument("--input-format", choices=["json", "dictation"], default="json")
    parser.add_argument("--asr-only", action="store_true")
    parser.add_argument("--edit-plan", action="store_true")
    parser.add_argument("--non-thinking", action="store_true")
    parser.add_argument("--chunk-seconds", default=20, type=int)
    args = parser.parse_args()
    if not 1 <= args.chunk_seconds <= 30: parser.error("Chunk duration must be 1–30 seconds")
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"status":"running", "cases":[], "scope":"Explicit local test WAVs, not microphone capture. Fixed chunking is a performance experiment; no quality or production segmentation claim."}
    def save(): output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    env = dict(os.environ)
    env["DYLD_LIBRARY_PATH"] = str(CACHE / "runtime/ort/onnxruntime-osx-arm64-1.24.2/lib")
    binary = ROOT / "benchmarks/asr-runner/target/release/voxsyl-asr-bench"
    runtime = CACHE / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="audio-bench-", dir=runtime) as temp, (runtime / (output.stem + "-asr.log")).open("w") as log:
        process = subprocess.Popen([str(binary), str(CACHE / "models/gigaam")], env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
        try:
            report["asr_ready"] = read_event(process.stdout, "ready")
            for index, audio in enumerate(args.audio):
                audio = audio.resolve(strict=True)
                with wave.open(str(audio), "rb") as reader:
                    if (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getcomptype()) != (1, 2, 16000, "NONE"):
                        raise ValueError(f"Expected 16 kHz mono PCM16: {audio}")
                    frames = reader.readframes(reader.getnframes())
                row = {"id":f"audio-{index+1}", "file":audio.name, "sha256":hashlib.sha256(audio.read_bytes()).hexdigest(),
                       "audio_seconds":len(frames)/32000, "chunks":[]}
                start = time.monotonic()
                size = args.chunk_seconds * 32000
                for offset in range(0, len(frames), size):
                    chunk = Path(temp) / f"chunk-{index}-{offset}.wav"
                    with wave.open(str(chunk), "wb") as writer:
                        writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                        writer.writeframes(frames[offset:offset+size])
                    process.stdin.write(json.dumps({"id":row["id"], "path":str(chunk)}) + "\n")
                    process.stdin.flush()
                    row["chunks"].append(read_event(process.stdout, "result"))
                row["asr_wall_ms"] = (time.monotonic() - start) * 1000
                row["raw_text"] = " ".join(c["text"].strip() for c in row["chunks"] if c["text"].strip())
                report["cases"].append(row)
                save()
                print(audio.name, f"ASR {row['asr_wall_ms']:.0f} ms", row["raw_text"], flush=True)
            if not args.asr_only:
                corpus = Path(temp) / "asr-transcripts.json"
                # The ASR string is only a preservation reference, not a gold
                # corrected transcript. Its match flag is not a success score.
                corpus.write_text(json.dumps({"cases":[{"id":r["id"], "split":"requirement", "input":r["raw_text"], "expected":r["raw_text"]} for r in report["cases"]]}, ensure_ascii=False))
                llm_output = output.with_name(output.stem + "-cleanup.json")
                command = [sys.executable, str(ROOT / "benchmarks/llm_bench.py"), "--model", args.model,
                           "--prompt", args.prompt, "--corpus", str(corpus), "--output", str(llm_output),
                           "--input-format", args.input_format, "--temperature", str(args.temperature)]
                if args.edit_plan: command.append("--edit-plan")
                if args.non_thinking: command.append("--non-thinking")
                # GigaAM remains resident here: the chain really has both
                # models loaded, rather than independent memory estimates.
                subprocess.run(command, cwd=ROOT, check=True)
                cleanup = json.loads(llm_output.read_text())
                report["llm_report"] = str(llm_output)
                report["both_models_resident_during_cleanup"] = True
                for audio, result in zip(report["cases"], cleanup["cases"], strict=True):
                    audio["cleanup"] = result
                    audio["warm_pipeline_ms"] = audio["asr_wall_ms"] + result["elapsed_ms"]
            report["status"] = "complete"
        except Exception as error:
            report.update({"status":"failed", "error":str(error)})
            raise
        finally:
            process.stdin.close()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.terminate(); process.wait(timeout=5)
            save()


if __name__ == "__main__": main()
