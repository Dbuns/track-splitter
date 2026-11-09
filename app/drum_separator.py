"""Run the drumsep model against an existing Track Splitter drum stem."""

import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

from paths import DATA_ROOT as ROOT
from paths import configure_runtime

configure_runtime()
MODEL = ROOT / ".cache" / "drumsep" / "models" / "49469ca8.th"
NAMES = ("kick", "snare", "cymbals", "toms")
MODEL_SHA256 = "aefaa8543c9b9c75e22f5f32b53ab86dfe416457849af1383ff1aef83401423f"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_tracks(folder, expected_frames, expected_rate):
    import numpy as np
    import soundfile as sf

    checks = []
    for name in NAMES:
        path = Path(folder) / (name + ".wav")
        data, rate = sf.read(path, dtype="float32", always_2d=True)
        if (
            rate != expected_rate
            or data.shape != (expected_frames, 2)
            or not np.isfinite(data).all()
        ):
            raise ValueError(f"{name}: invalid rate, length, channels or samples")
        checks.append(
            dict(
                stem=name,
                filename=path.name,
                frames=len(data),
                sample_rate=rate,
                channels=2,
                duration_seconds=len(data) / rate,
                rms=float(np.sqrt(np.mean(data.astype("float64") ** 2))),
                peak=float(np.max(np.abs(data))),
                bytes=path.stat().st_size,
                sha256=sha256(path),
            )
        )
    return checks


def download_model(progress=print):
    """Download the pinned upstream model once, verifying before atomic installation."""
    import gdown

    MODEL.parent.mkdir(parents=True, exist_ok=True)
    temporary = MODEL.with_name(MODEL.name + "." + uuid.uuid4().hex + ".download")
    progress("Downloading the drum model for first use…")
    try:
        result = gdown.download(
            id="1-Dm666ScPkg8Gt2-lK3Ua0xOudWHZBGC",
            output=str(temporary),
            quiet=True,
            use_cookies=False,
        )
        if not result or not temporary.is_file() or sha256(temporary) != MODEL_SHA256:
            raise ValueError(
                "The drum model download is incomplete or has an unexpected checksum. Please retry."
            )
        os.replace(temporary, MODEL)
    finally:
        temporary.unlink(missing_ok=True)


def separate_drums(source, progress=print):
    import soundfile as sf

    source = Path(source).resolve()
    if not source.is_relative_to(ROOT) or not source.is_file() or source.suffix.lower() != ".wav":
        raise ValueError("Choose an existing WAV drum stem within Track Splitter.")
    if not MODEL.is_file():
        download_model(progress)
    source_hash = sha256(source)
    model_hash = sha256(MODEL)
    destination = source.parent / "drum tracks"
    info = sf.info(source)
    if info.channels != 2:
        raise ValueError("This runner expects a stereo drum stem.")
    if destination.exists():
        report_path = destination / "verification.json"
        if report_path.exists():
            saved = json.loads(report_path.read_text(encoding="utf-8"))
            if (
                saved.get("source_sha256") == source_hash
                and saved.get("model_sha256") == model_hash
            ):
                verified = verify_tracks(destination, info.frames, info.samplerate)
                if (
                    all(
                        item["sha256"] == old["sha256"]
                        for item, old in zip(verified, saved["tracks"])
                    )
                    and len(saved["tracks"]) == 4
                ):
                    progress("Using existing verified drum tracks. No new separation needed.")
                    return destination
        raise FileExistsError("The drum tracks folder already exists and was kept unchanged.")
    if model_hash != MODEL_SHA256:
        raise ValueError("The drum model checksum does not match the expected upstream model.")
    progress("Loading drumsep model on CPU…")
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    torch.set_num_threads(min(4, os.cpu_count() or 1))
    started = time.perf_counter()
    model = get_model("49469ca8", repo=MODEL.parent).cpu().eval()
    labels = {
        "bombo": "kick",
        "kick": "kick",
        "redoblante": "snare",
        "snare": "snare",
        "platillos": "cymbals",
        "cymbals": "cymbals",
        "toms": "toms",
    }
    sources = [labels.get(str(name).lower()) for name in model.sources]
    if len(sources) != 4 or set(sources) != set(NAMES):
        raise ValueError("Unexpected model sources: " + repr(model.sources))
    progress("Model sources: " + ", ".join(map(str, model.sources)))
    audio, rate = sf.read(source, dtype="float32", always_2d=True)
    if rate != model.samplerate or model.audio_channels != 2:
        raise ValueError("Model and drum stem audio formats do not match.")
    wav = torch.from_numpy(audio.T.copy())
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std()
    if not torch.isfinite(wav).all() or std < 1e-8:
        raise ValueError("The drum stem is silent or invalid.")
    stage = source.parent / ("_drum_tracks_pending_" + uuid.uuid4().hex)
    stage.mkdir(exist_ok=False)
    try:
        progress("Separating kick, snare, cymbals and toms…")
        with torch.inference_mode():
            result = apply_model(
                model,
                ((wav - mean) / std)[None],
                device="cpu",
                shifts=1,
                split=True,
                overlap=0.25,
                progress=sys.stderr is not None,
                num_workers=0,
            )[0]
        result = result * std + mean
        for name, track in zip(sources, result):
            sf.write(stage / (name + ".wav"), track.T.numpy(), rate, subtype="FLOAT")
        checks = verify_tracks(stage, len(audio), rate)
        if sha256(source) != source_hash:
            raise RuntimeError("Input drum stem changed during processing.")
        report = dict(
            source=str(source),
            source_sha256=source_hash,
            original_unchanged=True,
            model="49469ca8",
            model_sha256=model_hash,
            model_project="https://github.com/inagoy/drumsep",
            model_sources=list(model.sources),
            device="cpu",
            shifts=1,
            elapsed_seconds=time.perf_counter() - started,
            tracks=checks,
        )
        (stage / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        os.rename(stage, destination)
        progress("Complete: four drum tracks verified and saved to " + str(destination))
        return destination
    finally:
        if stage.exists():
            if stage.resolve().parent != source.parent:
                raise RuntimeError("Unexpected temporary output path")
            shutil.rmtree(stage)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python drum_separator.py "path/to/song/drums.wav"')
    print(separate_drums(sys.argv[1]))
