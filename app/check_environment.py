"""Check the source installation before launching the desktop window."""

import importlib
import struct
import sys
from importlib import metadata
from pathlib import Path


def check(full=True):
    errors = []
    if sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
        return ["Track Splitter requires 64-bit Python 3.12."]
    requirements = Path(__file__).with_name("requirements.txt")
    for line in requirements.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, expected = line.split("==", 1)
        try:
            actual = metadata.version(name)
            if actual != expected:
                errors.append(f"{name}: expected {expected}, found {actual}.")
        except metadata.PackageNotFoundError:
            errors.append(f"Missing dependency: {name}.")
    if errors:
        return errors
    modules = (
        "torch",
        "torchaudio",
        "numpy",
        "demucs",
        "PySide6.QtWidgets",
        "soundfile",
        "sounddevice",
        "imageio_ffmpeg",
        "gdown",
    )
    if not full:
        modules = ("PySide6.QtWidgets", "PySide6.QtSvg", "numpy", "soundfile")
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:
            errors.append(f"Cannot load {name}: {exc}")
    if not errors:
        try:
            import imageio_ffmpeg

            imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            errors.append(f"FFmpeg is unavailable: {exc}")
    return errors


if __name__ == "__main__":
    problems = check(full="--startup" not in sys.argv[1:])
    if problems:
        print("Track Splitter setup is incomplete or incompatible.")
        for problem in problems:
            print("  " + problem)
        print("Run Setup_Track_Splitter.bat, then try again.")
        sys.exit(1)
