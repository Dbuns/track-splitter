"""Separate read-only bundled resources from writable user data."""

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
SOURCE_ROOT = Path(__file__).resolve().parent.parent
RESOURCE_ROOT = Path(sys._MEIPASS) if FROZEN else SOURCE_ROOT
ASSET_DIR = RESOURCE_ROOT / "assets"


def data_directory():
    override = os.environ.get("TRACK_SPLITTER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if not FROZEN:
        return SOURCE_ROOT
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
            / "TrackSplitter"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/TrackSplitter"
    return (
        Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "TrackSplitter"
    )


DATA_ROOT = data_directory()


def configure_runtime():
    """Create writable caches before audio or model libraries are imported."""
    for path in (DATA_ROOT, DATA_ROOT / ".tmp", DATA_ROOT / ".cache/torch"):
        path.mkdir(parents=True, exist_ok=True)
    if FROZEN:
        os.environ["IMAGEIO_FFMPEG_EXE"] = str(RESOURCE_ROOT / "ffmpeg/ffmpeg.exe")
    os.environ["TORCH_HOME"] = str(DATA_ROOT / ".cache/torch")
    os.environ["TEMP"] = os.environ["TMP"] = str(DATA_ROOT / ".tmp")
