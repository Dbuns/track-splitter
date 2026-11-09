import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from paths import DATA_ROOT as ROOT
from paths import configure_runtime

configure_runtime()


def separate(source, progress=print, model_name="htdemucs", output_root=None):
    progress("Preparing separation engine…")
    import imageio_ffmpeg
    import numpy as np
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    if model_name not in {"htdemucs", "htdemucs_6s"}:
        raise ValueError("Unsupported model")
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError("Choose an existing audio file.")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    started = time.perf_counter()
    out = Path(output_root or (ROOT / "outputs")) / (
        source.stem + "_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    )
    out.mkdir(parents=True, exist_ok=False)
    progress("Decoding audio…")
    decoded = out / "_input.wav"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(source),
            "-ar",
            "44100",
            "-ac",
            "2",
            "-y",
            str(decoded),
        ],
        check=True,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        audio, sr = sf.read(decoded, dtype="float32", always_2d=True)
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        progress("Loading the separation model…")
        model = get_model(model_name).cpu().eval()
        wav = torch.from_numpy(audio.T.copy())
        ref = wav.mean(0)
        mean, std = ref.mean(), ref.std()
        if std < 1e-8:
            raise ValueError("The input is silent.")
        progress(
            "Separating vocals, drums, bass, guitar and other on this PC…"
            if model_name == "htdemucs_6s"
            else "Separating four tracks on this PC…"
        )
        with torch.inference_mode():
            stems = apply_model(
                model,
                ((wav - mean) / std)[None],
                device="cpu",
                shifts=1,
                split=True,
                overlap=0.25,
                progress=True,
                num_workers=0,
            )[0]
        stems = stems * std + mean
        checks = []
        stem_map = dict(zip(model.sources, stems))
        if "piano" in stem_map:
            stem_map["other"] = stem_map["other"] + stem_map.pop("piano")
        for name, stem in stem_map.items():
            path = out / (name + ".wav")
            sf.write(path, stem.T.numpy(), sr, subtype="FLOAT")
            data, rate = sf.read(path, always_2d=True)
            assert rate == sr and data.shape == audio.shape and np.isfinite(data).all()
            checks.append(
                dict(
                    stem=name,
                    path=str(path),
                    frames=len(data),
                    sample_rate=rate,
                    channels=data.shape[1],
                    duration_seconds=len(data) / rate,
                    rms=float(np.sqrt(np.mean(data**2))),
                    bytes=path.stat().st_size,
                )
            )
        assert set(stem_map) == (
            {"vocals", "drums", "bass", "other", "guitar"}
            if model_name == "htdemucs_6s"
            else {"vocals", "drums", "bass", "other"}
        )
        after = hashlib.sha256(source.read_bytes()).hexdigest()
        assert before == after, "Original file changed during separation"
        report = dict(
            source=str(source),
            source_sha256=before,
            original_unchanged=before == after,
            model=model_name,
            device="cpu",
            elapsed_seconds=time.perf_counter() - started,
            stems=checks,
        )
        (out / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        progress(f"Complete — {len(checks)} WAV files verified.")
        return out
    finally:
        decoded.unlink(missing_ok=True)


if __name__ == "__main__":
    print(separate(sys.argv[1], model_name=sys.argv[2] if len(sys.argv) > 2 else "htdemucs"))
