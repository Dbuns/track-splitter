"""BPM estimation and phase-aligned, pitch-preserving practice tempo."""

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf


def estimate_bpm(audio, rate):
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    step = max(1, round(rate / 11025))
    mono = audio[::step][: int(180 * rate / step)]
    if len(mono) < max(1024, rate / step * 4) or np.max(np.abs(mono)) < 1e-7:
        return None
    size, hop = 1024, 256
    frames = np.lib.stride_tricks.sliding_window_view(mono, size)[::hop]
    envelope = []
    previous = np.zeros(size // 2 + 1)
    window = np.hanning(size)
    for start in range(0, len(frames), 128):
        spectra = np.abs(np.fft.rfft(frames[start : start + 128] * window, axis=1))
        differences = np.diff(np.vstack((previous, spectra)), axis=0)
        envelope.extend(np.maximum(differences, 0).sum(axis=1))
        previous = spectra[-1]
    onset = np.asarray(envelope)
    onset = np.maximum(onset - np.convolve(onset, np.ones(9) / 9, mode="same"), 0)
    if onset.std() < 1e-8:
        return None
    peaks = (
        np.flatnonzero(
            (onset[1:-1] > onset[:-2])
            & (onset[1:-1] >= onset[2:])
            & (onset[1:-1] > onset.max() * 0.25)
        )
        + 1
    )
    selected = []
    for peak in peaks:
        if not selected or peak - selected[-1] > (rate / step / hop) * 0.18:
            selected.append(peak)
        elif onset[peak] > onset[selected[-1]]:
            selected[-1] = peak
    if len(selected) < 4:
        return None
    hint = 60 * (rate / step / hop) / np.median(np.diff(selected))
    while hint > 240:
        hint /= 2
    while hint < 60:
        hint *= 2
    onset -= onset.mean()
    n = 1 << (2 * len(onset) - 1).bit_length()
    correlation = np.fft.irfft(np.abs(np.fft.rfft(onset, n)) ** 2, n)[: len(onset)]
    correlation /= np.maximum(1, np.arange(len(onset), 0, -1))
    env_rate = rate / step / hop
    low = max(2, int(60 * env_rate / 240))
    high = min(len(onset) // 4, int(60 * env_rate / 60))
    if high <= low:
        return None
    lags = np.arange(low, high + 1)
    bpm = 60 * env_rate / lags
    score = correlation[lags] + 0.4 * correlation[lags * 2] + 0.15 * correlation[lags * 3]
    if np.max(correlation[lags]) < correlation[0] * 0.04:
        return None
    score *= np.exp(-0.5 * (np.log2(bpm / hint) / 0.45) ** 2)
    lag = int(lags[np.argmax(score)])
    a, b, c = correlation[lag - 1 : lag + 2]
    denominator = a - 2 * b + c
    adjustment = 0.5 * (a - c) / denominator if abs(denominator) > 1e-12 else 0
    return round(float(60 * env_rate / (lag + np.clip(adjustment, -0.5, 0.5))), 1)


def prepare_tempo(tracks, rate, factor, cache, progress=lambda message: None):
    import imageio_ffmpeg

    if not 0.5 <= factor <= 1.5:
        raise ValueError("Practice speed must be between 50% and 150%.")
    if not tracks:
        raise ValueError("No tracks loaded.")
    names = list(tracks)
    frames = len(tracks[names[0]])
    if any(a.shape != (frames, 2) for a in tracks.values()):
        raise ValueError("Tracks are not aligned.")
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(json.dumps((names, rate, frames, round(factor, 8))).encode())
    progress("Checking practice-tempo cache…")
    for name in names:
        for start in range(0, frames, 65536):
            digest.update(tracks[name][start : start + 65536].tobytes())
    path = cache / (digest.hexdigest() + ".wav")
    if not path.exists():
        progress("Preparing pitch-preserving practice tempo…")
        with tempfile.TemporaryDirectory(prefix="tempo_", dir=cache) as temporary:
            source = Path(temporary) / "source.wav"
            destination = Path(temporary) / "stretched.wav"
            with sf.SoundFile(
                source, "w", samplerate=rate, channels=2 * len(names), subtype="FLOAT"
            ) as output:
                for start in range(0, frames, 65536):
                    output.write(
                        np.concatenate([tracks[n][start : start + 65536] for n in names], axis=1)
                    )
            result = subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(),
                    "-v",
                    "error",
                    "-nostdin",
                    "-i",
                    str(source),
                    "-af",
                    f"atempo={factor:.8f}",
                    "-c:a",
                    "pcm_f32le",
                    str(destination),
                ],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode:
                raise RuntimeError(result.stderr.decode(errors="replace"))
            info = sf.info(destination)
            if info.channels != 2 * len(names) or info.samplerate != rate or info.frames <= 0:
                raise ValueError("Prepared tempo failed validation.")
            os.replace(destination, path)
    data, actual_rate = sf.read(path, dtype="float32", always_2d=True)
    if actual_rate != rate or data.shape[1] != 2 * len(names) or not np.isfinite(data).all():
        raise ValueError("Invalid tempo cache.")
    expected = max(1, round(frames / factor))
    if len(data) < expected:
        data = np.pad(data, ((0, expected - len(data)), (0, 0)))
    else:
        data = data[:expected]
    os.utime(path, None)
    owned = sorted(
        (
            p
            for p in cache.glob("*.wav")
            if len(p.stem) == 64 and all(c in "0123456789abcdef" for c in p.stem)
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in owned[3:]:
        if old != path and old.resolve().parent == cache.resolve():
            old.unlink()
    return {name: data[:, 2 * i : 2 * i + 2] for i, name in enumerate(names)}
