"""Validate a relocated Windows ZIP using isolated data and a Python-free PATH."""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--models", action="store_true")
    parser.add_argument("--download-drum-model", action="store_true")
    args = parser.parse_args()
    archive = args.archive.resolve()
    output = ROOT / ".tmp/test-results"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="relocated app é with spaces ", dir=ROOT / ".tmp"
    ) as temporary:
        temporary = Path(temporary)
        with zipfile.ZipFile(archive) as bundle:
            paths = bundle.namelist()
            forbidden = ("/library/", "/outputs/", "/audio/", "/.cache/", "/.venv/")
            assert not any(any(part in p.replace("\\", "/") for part in forbidden) for p in paths)
            assert not any(
                Path(p).suffix.lower() in (".mp3", ".wav", ".th", ".pt", ".pth") for p in paths
            )
            normalized = [p.replace("\\", "/") for p in paths]
            assert any(p.endswith("/ffmpeg/ffmpeg.exe") for p in normalized)
            assert not any("/imageio_ffmpeg/binaries/" in p and p.endswith(".exe") for p in normalized)
            assert not any(p.endswith(("/Qt6Pdf.dll", "/Qt6VirtualKeyboard.dll")) for p in normalized)
            assert any(p.endswith("/licenses/THIRD_PARTY.md") for p in normalized)
            bundle.extractall(temporary)
        data = temporary / "isolated user data"
        if args.models:
            checkpoints = ROOT / ".cache/torch/hub/checkpoints"
            target = data / ".cache/torch/hub/checkpoints"
            if checkpoints.exists():
                shutil.copytree(checkpoints, target)
            if not args.download_drum_model:
                model = ROOT / ".cache/drumsep/models/49469ca8.th"
                if model.exists():
                    target = data / ".cache/drumsep/models/49469ca8.th"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(model, target)
        env = os.environ.copy()
        for key in (
            "PYTHONPATH",
            "PYTHONHOME",
            "IMAGEIO_FFMPEG_EXE",
            "QT_PLUGIN_PATH",
            "QT_QPA_PLATFORM_PLUGIN_PATH",
        ):
            env.pop(key, None)
        windows = Path(env.get("SystemRoot", "C:/Windows"))
        env["PATH"] = os.pathsep.join(
            str(p) for p in (windows / "System32", windows, windows / "System32/Wbem")
        )
        env["TRACK_SPLITTER_DATA_DIR"] = str(data)
        env["QT_QPA_PLATFORM"] = "offscreen"
        name = "frozen-models" if args.models else "frozen-startup"
        report = output / (name + ".json")
        report.unlink(missing_ok=True)
        command = [str(temporary / "Track Splitter/Track Splitter.exe"), "--self-test", str(report)]
        if args.models:
            command.append("--models")
        result = subprocess.run(command, cwd=temporary, env=env, timeout=600, capture_output=True)
        (output / (name + ".stdout.log")).write_bytes(result.stdout)
        (output / (name + ".stderr.log")).write_bytes(result.stderr)
        if not report.exists():
            log = data / "library/logs/desktop.log"
            if log.exists():
                shutil.copy2(log, output / (name + ".desktop.log"))
            raise RuntimeError(
                f"Executable returned {result.returncode} before producing a report. See {output}."
            )
        contents = json.loads(report.read_text(encoding="utf-8"))
        print(json.dumps(contents, indent=2), flush=True)
        assert result.returncode == 0 and contents["ok"], "Executable diagnostics failed"
        assert not (temporary / "Track Splitter/library").exists()
        assert not (temporary / "Track Splitter/_internal/library").exists()
    print("PASS: relocated ZIP, isolated data, no Python or external FFmpeg on PATH.")


if __name__ == "__main__":
    main()
