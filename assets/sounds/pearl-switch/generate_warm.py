#!/usr/bin/env python3
"""Warm revision of Voxsyl's switch cues; original synthesis, no samples.

Run beside generate.py, whose WAV writer and signal checks are reused.
The v1 sounds and provenance are preserved. Requires Python 3 and NumPy.
"""

from pathlib import Path
import hashlib
import json

import numpy as np

from generate import RATE, smoothstep, write_wav


ROOT = Path(__file__).resolve().parent


def soft_note(t, onset, frequency, duration, level, decay):
    local = t - onset
    active_time = np.maximum(local, 0.0)
    # A small settling pitch gesture adds softness without a pronounced chirp.
    hz = frequency * (1.0 - 0.004 * np.exp(-active_time / 0.035))
    phase = np.cumsum(hz) * (2.0 * np.pi / RATE)
    envelope = smoothstep(local / 0.019)
    envelope *= np.exp(-np.maximum(local - 0.019, 0.0) / decay)
    envelope *= 1.0 - smoothstep((local - duration + 0.065) / 0.065)
    envelope *= (local >= 0.0) & (local < duration)
    # Quiet harmonic partials instead of bright, inharmonic glass resonances.
    tone = np.sin(phase)
    tone += 0.065 * np.exp(-active_time / 0.060) * np.sin(2.0 * phase + 0.16)
    tone += 0.012 * np.exp(-active_time / 0.038) * np.sin(3.0 * phase + 0.27)
    return level * envelope * tone


def render(kind):
    opening = kind == "activate"
    duration = 0.335 if opening else 0.305
    t = np.arange(round(duration * RATE), dtype=np.float64) / RATE
    if opening:
        dry = soft_note(t, 0.0, 392.0, 0.240, 0.80, 0.074)
        dry += soft_note(t, 0.072, 493.883, 0.250, 0.85, 0.079)
        dry += soft_note(t, 0.0, 196.0, 0.225, 0.12, 0.077)
        dry += soft_note(t, 0.103, 587.330, 0.185, 0.032, 0.062)
    else:
        dry = soft_note(t, 0.0, 493.883, 0.180, 0.46, 0.057)
        dry += soft_note(t, 0.054, 392.0, 0.239, 0.88, 0.076)
        dry += soft_note(t, 0.054, 196.0, 0.235, 0.15, 0.074)

    # Nearly centred playback with two restrained room reflections.
    left, right = dry.copy(), dry.copy()
    for delay, gain, channel in [(0.017, 0.024, left), (0.021, 0.023, right)]:
        offset = round(delay * RATE)
        channel[offset:] += gain * dry[:-offset]
    stereo = np.column_stack((left, right))
    stereo -= np.mean(stereo, axis=0)
    edge = smoothstep(t / 0.008) * (1.0 - smoothstep((t - duration + 0.020) / 0.020))
    stereo *= edge[:, None]
    stereo[[0, -1], :] = 0.0
    stereo *= (10.0 ** (-12.0 / 20.0)) / np.max(np.abs(stereo))
    return stereo


def main():
    activate, deactivate = render("activate"), render("deactivate")
    files = [
        write_wav("voxsyl-activate-v2-warm.wav", activate),
        write_wav("voxsyl-deactivate-v2-warm.wav", deactivate),
    ]
    sequence = np.concatenate((
        np.zeros((round(0.100 * RATE), 2)),
        activate,
        np.zeros((round(0.650 * RATE), 2)),
        deactivate,
        np.zeros((round(0.150 * RATE), 2)),
    ))
    files.append(write_wav("voxsyl-switch-pair-v2-warm.wav", sequence))
    provenance = {
        "schema_version": 1,
        "version": "pearl-switch-v2-warm",
        "created": "2026-10-14",
        "project": "Voxsyl",
        "status": "candidate_for_user_audition_not_approved",
        "feedback": "User rejected v1 and requested a kinder sound. This revision uses lower, harmonic tones, gentler attacks and a warmer major-third motif.",
        "source": "Original procedural synthesis authored in this project conversation",
        "generator": "generate_warm.py",
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "helper": "generate.py (WAV writer, sample rate and smoothstep only)",
        "helper_sha256": hashlib.sha256((ROOT / "generate.py").read_bytes()).hexdigest(),
        "generation_dependencies": {"python": "3", "numpy": np.__version__},
        "external_samples": [],
        "third_party_audio": False,
        "format": {"container": "WAV", "encoding": "PCM signed 16-bit little-endian", "sample_rate": RATE, "channels": 2},
        "uniqueness": "Designed from scratch for Voxsyl; global acoustic uniqueness is not guaranteed.",
        "own_asset_license": "Pending the project's own-code and asset license decision; no external audio license applies.",
        "files": files,
        "verification": "Signal and file checks only; user audition and native integration pending.",
    }
    (ROOT / "provenance-v2-warm.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"files": files}, indent=2))


if __name__ == "__main__":
    main()
