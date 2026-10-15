#!/usr/bin/env python3
"""Rebuild Voxsyl's first Pearl switch cues. No samples or network access.

Requires Python 3 and NumPy. Writes PCM WAVs and measured provenance next
to this script. These are audition candidates, not approved product sounds.
"""

from pathlib import Path
import hashlib
import json
import wave

import numpy as np


ROOT = Path(__file__).resolve().parent
RATE = 48_000
VERSION = "pearl-switch-v1"


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def voice(t, start, duration, low, high, level, decay, phase, gloss=False):
    local = t - start
    progress = np.clip(local / duration, 0.0, 1.0)
    frequency = low + (high - low) * smoothstep(progress)
    # A continuous phase prevents discontinuities during the pitch contour.
    angle = 2.0 * np.pi * np.cumsum(frequency) / RATE + phase
    envelope = smoothstep(local / 0.012)
    envelope *= np.exp(-np.maximum(local, 0.0) / decay)
    envelope *= 1.0 - smoothstep((local - duration + 0.045) / 0.045)
    envelope *= (local >= 0.0) & (local < duration)
    wave_body = np.sin(angle + 0.045 * np.sin(1.47 * angle))
    wave_body += 0.145 * np.sin(1.996 * angle + 0.37)
    wave_body += (0.085 if gloss else 0.036) * np.sin(2.731 * angle + 0.83)
    wave_body += (0.027 if gloss else 0.012) * np.sin(4.113 * angle + 1.19)
    return level * envelope * wave_body


def render(kind):
    opening = kind == "activate"
    duration = 0.240 if opening else 0.210
    t = np.arange(round(duration * RATE), dtype=np.float64) / RATE
    if opening:
        body = voice(t, 0.0, 0.214, 548.0, 658.0, 1.0, 0.078, 0.0)
        sheen = voice(t, 0.035, 0.198, 815.0, 985.0, 0.21, 0.060, 0.39, True)
        core = voice(t, 0.005, 0.151, 281.0, 310.0, 0.11, 0.051, 0.12)
    else:
        body = voice(t, 0.0, 0.190, 649.0, 516.0, 1.0, 0.072, 0.0)
        sheen = voice(t, 0.003, 0.150, 972.0, 812.0, 0.16, 0.045, 0.39, True)
        core = voice(t, 0.027, 0.166, 316.0, 259.0, 0.14, 0.049, 0.12)

    dry = body + sheen + core
    # Two quiet, very short reflections soften the surface without a long tail.
    left = dry.copy()
    right = dry.copy()
    for delay, gain, side in [(0.0093, 0.048, left), (0.0127, 0.046, right)]:
        samples = round(delay * RATE)
        side[samples:] += gain * dry[:-samples]
    stereo = np.column_stack((left, right))
    stereo -= np.mean(stereo, axis=0)
    fade = smoothstep(t / 0.003) * (1.0 - smoothstep((t - duration + 0.012) / 0.012))
    stereo *= fade[:, None]
    stereo[[0, -1], :] = 0.0
    target_peak = 10.0 ** (-10.0 / 20.0)
    stereo *= target_peak / np.max(np.abs(stereo))
    return stereo


def write_wav(name, samples):
    path = ROOT / name
    pcm = np.rint(samples * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes(pcm.tobytes())
    decoded = pcm.astype(np.float64) / 32768.0
    mono = decoded.mean(axis=1)
    peak = float(np.max(np.abs(decoded)))
    rms = float(np.sqrt(np.mean(decoded ** 2)))
    spectrum = np.abs(np.fft.rfft(mono)) ** 2
    frequency = np.fft.rfftfreq(len(mono), 1.0 / RATE)
    high_energy = float(spectrum[frequency > 8000].sum() / spectrum.sum())
    assert np.isfinite(decoded).all()
    assert peak < 0.32
    assert np.all(pcm[[0, -1], :] == 0)
    assert np.max(np.abs(np.mean(decoded, axis=0))) < 0.001
    assert high_energy < 0.001
    assert np.max(np.abs(np.diff(decoded, axis=0))) < 0.045
    return {
        "file": name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "duration_ms": round(len(decoded) * 1000 / RATE, 3),
        "peak_dbfs": round(20 * np.log10(peak), 3),
        "rms_dbfs": round(20 * np.log10(rms), 3),
        "dc_offset": np.mean(decoded, axis=0).tolist(),
        "energy_above_8khz_ratio": high_energy,
        "first_last_sample_zero": True,
        "clipped_samples": int(np.sum(np.abs(pcm.astype(np.int32)) >= 32767)),
    }


def main():
    activate = render("activate")
    deactivate = render("deactivate")
    files = [
        write_wav("voxsyl-activate-v1.wav", activate),
        write_wav("voxsyl-deactivate-v1.wav", deactivate),
    ]
    # Audition only. The app will play the individual cues, never this sequence.
    sequence = np.concatenate((
        np.zeros((round(0.100 * RATE), 2)),
        activate,
        np.zeros((round(0.700 * RATE), 2)),
        deactivate,
        np.zeros((round(0.150 * RATE), 2)),
    ))
    files.append(write_wav("voxsyl-switch-pair-v1.wav", sequence))
    provenance = {
        "schema_version": 1,
        "version": VERSION,
        "created": "2026-10-14",
        "project": "Voxsyl",
        "status": "candidate_for_user_audition_not_approved",
        "source": "Original procedural synthesis authored in this project conversation",
        "generator": "generate.py",
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "generation_dependencies": {"python": "3", "numpy": np.__version__},
        "external_samples": [],
        "third_party_audio": False,
        "format": {"container": "WAV", "encoding": "PCM signed 16-bit little-endian", "sample_rate": RATE, "channels": 2},
        "uniqueness": "Designed from scratch for Voxsyl; global acoustic uniqueness has not been verified and is not guaranteed.",
        "own_asset_license": "Pending the project's own-code and asset license decision; no external audio license applies.",
        "files": files,
        "verification": "File and signal measurements only; hardware playback and speaker/headphone audition remain pending.",
    }
    (ROOT / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"files": files}, indent=2))


if __name__ == "__main__":
    main()
