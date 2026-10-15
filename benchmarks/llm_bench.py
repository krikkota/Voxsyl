#!/usr/bin/env python3
"""Own and benchmark an offline llama.cpp server on loopback. Stdlib only."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from cleanup_plan import SCHEMA, apply_plan, conservative_surface, has_correction

ROOT = Path(__file__).resolve().parent.parent
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def reference_words(text):
    # Diagnostic reference match, not proof of equivalent meaning.
    return re.findall(r"\w+", text.casefold().replace("ё", "е"))


def request(url, key, data=None, timeout=60):
    encoded = None if data is None else json.dumps(data, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=encoded, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json",
    })
    with HTTP.open(req, timeout=timeout) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="benchmarks/prompts/conservative-v1.txt")
    parser.add_argument("--output", default="outputs/benchmarks/cleanup-v1.json")
    parser.add_argument("--split", choices=["all", "development", "acceptance", "requirement"], default="all")
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--model", default=".cache/benchmark/models/Vikhr-Qwen-2.5-1.5b-Instruct-Q4_K_M.gguf")
    parser.add_argument("--corpus", default="benchmarks/cleanup-cases.json")
    parser.add_argument("--memory-snapshot", action="store_true", help="Capture macOS footprint for the owned server at ready and after requests")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--non-thinking", action="store_true")
    parser.add_argument("--instruction-role", choices=["system", "user"], default="system")
    parser.add_argument("--edit-plan", action="store_true")
    parser.add_argument("--thinking-budget", type=int, default=0)
    parser.add_argument("--few-shot", action="store_true", help="Use only the six development examples as demonstrations")
    parser.add_argument("--few-shot-style", choices=["chat", "inline"], default="chat")
    parser.add_argument("--input-format", choices=["json", "dictation"], default="json")
    args = parser.parse_args()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    cache = ROOT / ".cache/benchmark"
    model = ROOT / args.model
    artifacts = json.loads((ROOT / "benchmarks/artifacts.json").read_text())["artifacts"]
    artifact = next((a for a in artifacts if (cache / a["path"]).resolve() == model.resolve() and a["kind"] == "model"), None)
    if artifact is None:
        raise ValueError("Model is not in the pinned artifact manifest")
    with model.open("rb") as stream:
        model_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if model.stat().st_size != artifact["bytes"] or model_hash != artifact["sha256"]:
        raise ValueError("Model checksum mismatch or incomplete download; inference was not started")
    binary = cache / "runtime/llama/llama-b11429/llama-server"
    prompt_path = ROOT / args.prompt
    prompt = prompt_path.read_text().strip()
    corpus_path = ROOT / args.corpus
    corpus = json.loads(corpus_path.read_text())
    cases = [c for c in corpus["cases"] if args.split == "all" or c["split"] == args.split]
    def user_content(value):
        if args.input_format == "json":
            return json.dumps({"transcript":value}, ensure_ascii=False)
        return "<dictation>\n" + html.escape(value, quote=False) + "\n</dictation>"
    demonstrations = []
    inline_examples = ""
    if args.few_shot:
        development = json.loads((ROOT / "benchmarks/cleanup-cases.json").read_text())
        for case in development["cases"]:
            if case["split"] == "development":
                if args.few_shot_style == "chat":
                    demonstrations += [{"role":"user", "content":user_content(case["input"])},
                                       {"role":"assistant", "content":case["expected"]}]
                else:
                    inline_examples += "Исходный текст: " + json.dumps(case["input"], ensure_ascii=False) + "\nГотовый текст: " + case["expected"] + "\n\n"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    key = secrets.token_hex(24)
    key_path = cache / "runtime" / f"benchmark-api-key-{port}.txt"
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream: stream.write(key + "\n")
    command = [str(binary), "--model", str(model), "--host", "127.0.0.1", "--port", str(port),
               "--ctx-size", "2048", "--parallel", "1", "--threads", "4", "--threads-batch", "4",
               "--gpu-layers", "0" if args.cpu else "99", "--flash-attn", "on",
               "--cache-ram", "0", "--api-key-file", str(key_path), "--no-webui", "--offline"]
    if args.cpu:
        command += ["--device", "none", "--no-kv-offload", "--no-op-offload"]
    if args.non_thinking:
        command += ["--chat-template-kwargs", '{"enable_thinking":false}', "--reasoning-budget", "0"]
    elif args.thinking_budget:
        command += ["--chat-template-kwargs", '{"enable_thinking":true}', "--reasoning", "on", "--reasoning-budget", str(args.thinking_budget)]
    log_path = cache / "runtime" / (output.stem + "-server.log")
    rows, samples = [], []
    stopped = threading.Event()
    report = {"status":"running", "started_at":datetime.now(timezone.utc).isoformat(),
              "model":model.name, "model_sha256_verified":model_hash,
              "backend_requested":"CPU" if args.cpu else "Metal", "context":2048,
              "prompt":args.prompt, "prompt_sha256":hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
              "corpus":args.corpus, "fixture_sha256":hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
              "temperature":args.temperature, "seed":42, "cases":rows, "non_thinking":args.non_thinking,
              "few_shot_development":args.few_shot, "input_format":args.input_format,
              "few_shot_style":args.few_shot_style,
              "instruction_role":args.instruction_role,
              "edit_plan":args.edit_plan,
              "thinking_budget":args.thinking_budget,
              "scope":"Diagnostic corpus only; no mic capture; no claim of general accuracy. Process-cold, filesystem caches not cleared."}
    def save(): output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    def memory_snapshot(pid, stage):
        if not args.memory_snapshot:
            return
        path = output.with_name(output.stem + f"-memory-{stage}.json")
        try:
            run = subprocess.run(["/usr/bin/footprint", "--pid", str(pid), "--json", str(path), "--format", "bytes"], capture_output=True, timeout=12)
            report.setdefault("footprint_snapshots", []).append({"stage":stage, "path":str(path.relative_to(ROOT)), "exit_code":run.returncode, "error":run.stderr.decode(errors="replace")[:500]})
        except (OSError, subprocess.SubprocessError) as error:
            report.setdefault("footprint_snapshots", []).append({"stage":stage, "error":str(error)})
    with log_path.open("w") as log:
        start = time.monotonic()
        process = subprocess.Popen(command, stdout=log, stderr=log)
        def sample_rss():
            while not stopped.is_set():
                try:
                    rss = subprocess.check_output(["/bin/ps", "-o", "rss=", "-p", str(process.pid)], stderr=subprocess.DEVNULL).strip()
                    if rss: samples.append(int(rss) * 1024)
                except (OSError, subprocess.SubprocessError, ValueError): pass
                stopped.wait(0.25)
        sampler = threading.Thread(target=sample_rss, daemon=True)
        sampler.start()
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = start + 90
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"llama-server exited {process.returncode}; see {log_path}")
                try:
                    if request(base + "/health", key, timeout=1).get("status") == "ok": break
                except (OSError, urllib.error.HTTPError): pass
                if time.monotonic() > deadline: raise TimeoutError("Model startup exceeded 90 seconds")
                time.sleep(0.15)
            report["startup_to_ready_ms"] = (time.monotonic() - start) * 1000
            report["server_props"] = request(base + "/props", key)
            memory_snapshot(process.pid, "ready")
            save()
            print(f"Model ready in {report['startup_to_ready_ms']:.0f} ms", flush=True)
            for case in cases:
                elapsed_start = time.monotonic()
                row = dict(case)
                if not case["input"].strip():
                    row.update({"text":"", "elapsed_ms":0.0, "model_called":False})
                elif args.edit_plan and not has_correction(case["input"]):
                    row.update({"text":conservative_surface(case["input"]), "elapsed_ms":0.0, "model_called":False, "edit_audit":[]})
                else:
                    content = user_content(case["input"])
                    if inline_examples:
                        content = "Оформи последнюю диктовку по этим образцам.\n\n" + inline_examples + "Исходный текст: " + json.dumps(case["input"], ensure_ascii=False) + "\nГотовый текст:"
                    if args.instruction_role == "user":
                        messages = [{"role":"system", "content":"Ты — редактор русской диктовки."}] + demonstrations + [{"role":"user", "content":prompt + "\n\n" + content}]
                    else:
                        messages = [{"role":"system", "content":prompt}] + demonstrations + [{"role":"user", "content":content}]
                    payload = {"messages":messages,
                               "temperature":args.temperature, "seed":42, "max_tokens":512 if args.thinking_budget else 256, "stream":False, "cache_prompt":False}
                    if args.non_thinking:
                        payload.update({"chat_template_kwargs":{"enable_thinking":False}, "top_p":0.8, "top_k":20, "min_p":0.0})
                    elif args.thinking_budget:
                        payload.update({"chat_template_kwargs":{"enable_thinking":True}, "top_p":0.95, "top_k":20, "min_p":0.0})
                    if args.edit_plan:
                        payload["response_format"] = {"type":"json_schema", "json_schema":{"name":"correction_plan", "strict":True, "schema":SCHEMA}}
                    answer = request(base + "/v1/chat/completions", key, payload)
                    row.update({"text":answer["choices"][0]["message"]["content"].strip(),
                                "elapsed_ms":(time.monotonic()-elapsed_start)*1000,
                                "usage":answer.get("usage"), "timings":answer.get("timings"),
                                "finish_reason":answer["choices"][0].get("finish_reason"), "model_called":True})
                    if args.edit_plan:
                        row["raw_plan"] = row["text"]
                        try:
                            edited, audit = apply_plan(case["input"], json.loads(row["raw_plan"]))
                            row.update({"text":conservative_surface(edited), "edit_audit":audit})
                            row["candidate_text"] = row["text"]
                            if any(a["status"] == "rejected" for a in audit) or has_correction(edited):
                                row.update({"text":case["input"], "preview_raw_required":True,
                                            "fallback_reason":"rejected_or_unresolved_correction"})
                        except (ValueError, TypeError, KeyError) as error:
                            row.update({"text":case["input"], "preview_raw_required":True,
                                        "fallback_reason":"invalid_plan", "edit_audit":[{"status":"rejected", "reason":str(error)}]})
                    if row["finish_reason"] != "stop":
                        row.update({"candidate_text":row["text"], "text":case["input"],
                                    "preview_raw_required":True, "fallback_reason":"incomplete_generation"})
                row["normalized_reference_match"] = reference_words(row["text"]) == reference_words(case["expected"])
                rows.append(row)
                report["sampled_peak_rss_bytes"] = max(samples, default=None)
                save()
                print(case["id"], f"{row['elapsed_ms']:.0f} ms", row["text"], flush=True)
            report["status"] = "complete"
            memory_snapshot(process.pid, "end")
        except Exception as error:
            report.update({"status":"failed", "error":str(error)})
            raise
        finally:
            stopped.set()
            sampler.join(timeout=2)
            process.terminate()
            try: process.wait(timeout=8)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
            report["sampled_peak_rss_bytes"] = max(samples, default=None)
            report["server_log"] = str(log_path.relative_to(ROOT))
            report["rss_note"] = "Sampled process RSS, not total device memory or a complete GPU memory measure."
            save()
            key_path.unlink(missing_ok=True)


if __name__ == "__main__": main()
