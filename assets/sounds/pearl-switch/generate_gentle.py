#!/usr/bin/env python3
"""Gentle v3: a small refinement of the user-liked Warm v2 motif.

Original synthesis, no external samples. Python 3 and NumPy are only needed
to rebuild the files. Prior versions are not overwritten.
"""

from pathlib import Path
import hashlib
import json

import numpy as np

from generate import RATE, smoothstep, write_wav


ROOT = Path(__file__).resolve().parent


def soft_note(t, onset, frequency, duration, level, decay):
    local = t - onset
    active = np.maximum(local, 0.0)
    hz = frequency * (1.0 - 0.002 * np.exp(-active / 0.040))
    phase = np.cumsum(hz) * (2.0 * np.pi / RATE)
    envelope = smoothstep(local / 0.026)
    envelope *= np.exp(-np.maximum(local - 0.026, 0.0) / decay)
    envelope *= 1.0 - smoothstep((local - duration + 0.075) / 0.075)
    envelope *= (local >= 0.0) & (local < duration)
    tone = np.sin(phase)
    tone += 0.035 * np.exp(-active / 0.055) * np.sin(2.0 * phase + 0.16)
    tone += 0.004 * np.exp(-active / 0.033) * np.sin(3.0 * phase + 0.27)
    return level * envelope * tone


def render(kind):
    opening = kind == "activate"
    duration = 0.350 if opening else 0.320
    t = np.arange(round(duration * RATE), dtype=np.float64) / RATE
    if opening:
        dry = soft_note(t, 0.0, 392.0, 0.253, 0.80, 0.080)
        dry += soft_note(t, 0.072, 493.883, 0.262, 0.85, 0.087)
        dry += soft_note(t, 0.0, 196.0, 0.240, 0.145, 0.083)
        dry += soft_note(t, 0.103, 587.330, 0.185, 0.018, 0.062)
    else:
        dry = soft_note(t, 0.0, 493.883, 0.190, 0.46, 0.060)
        dry += soft_note(t, 0.054, 392.0, 0.252, 0.88, 0.083)
        dry += soft_note(t, 0.054, 196.0, 0.249, 0.17, 0.081)

    left, right = dry.copy(), dry.copy()
    for delay, gain, channel in [(0.017, 0.024, left), (0.021, 0.023, right)]:
        offset = round(delay * RATE)
        channel[offset:] += gain * dry[:-offset]
    stereo = np.column_stack((left, right))
    stereo -= np.mean(stereo, axis=0)
    fade = smoothstep(t / 0.010) * (1.0 - smoothstep((t - duration + 0.024) / 0.024))
    stereo *= fade[:, None]
    stereo[[0, -1], :] = 0.0
    # Keep v2's peak level: the change comes from timbre and envelopes.
    stereo *= (10.0 ** (-12.0 / 20.0)) / np.max(np.abs(stereo))
    return stereo


def main():
    activate, deactivate = render("activate"), render("deactivate")
    files = [
        write_wav("voxsyl-activate-v3-gentle.wav", activate),
        write_wav("voxsyl-deactivate-v3-gentle.wav", deactivate),
    ]
    sequence = np.concatenate((
        np.zeros((round(0.100 * RATE), 2)), activate,
        np.zeros((round(0.650 * RATE), 2)), deactivate,
        np.zeros((round(0.150 * RATE), 2)),
    ))
    files.append(write_wav("voxsyl-switch-pair-v3-gentle.wav", sequence))
    provenance = {
        "schema_version": 1,
        "version": "pearl-switch-v3-gentle",
        "created": "2026-10-14",
        "project": "Voxsyl",
        "status": "selected_by_user_not_integrated",
        "approved": {"date": "2026-10-14", "user_reply": "ладно пойдет оставляем"},
        "feedback": "User likes Warm v2 and requests a little more kindness. Retains the same notes and motif; softer upper harmonics, slower onset and a slightly warmer tail.",
        "source": "Original procedural synthesis authored in this project conversation",
        "generator": "generate_gentle.py",
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
    (ROOT / "provenance-v3-gentle.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"files": files}, indent=2))


if __name__ == "__main__":
    main()
