"""Collect installed dependency licences and notices for a Windows build."""

import json
import shutil
import sys
import tarfile
from collections import deque
from importlib import metadata
from pathlib import Path

from build_audio_windows import BUILD, CACHE, sources
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (
    "demucs",
    "torch",
    "torchaudio",
    "numpy",
    "PySide6",
    "soundfile",
    "sounddevice",
    "imageio-ffmpeg",
    "gdown",
    "pyinstaller",
)


def collect(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    pending = deque(RUNTIME)
    seen = set()
    inventory = []
    while pending:
        name = pending.popleft()
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        seen.add(key)
        dist = metadata.distribution(name)
        notices = []
        for file in dist.files or []:
            filename = str(file).lower()
            base = Path(file).name.lower()
            if not (
                base.startswith(("license", "licence", "copying", "notice"))
                or "/licenses/" in filename
            ):
                continue
            original = Path(dist.locate_file(file))
            if not original.is_file():
                continue
            relative = Path(*(p for p in Path(file).parts if p not in ("..", ".")))
            target = destination / "packages" / key / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
            notices.append(str(target.relative_to(destination)))
        inventory.append(
            dict(
                name=dist.metadata["Name"],
                version=dist.version,
                declared_license=dist.metadata.get("License-Expression")
                or dist.metadata.get("License", ""),
                notices=notices,
            )
        )
        for requirement in dist.requires or []:
            parsed = Requirement(requirement)
            if parsed.marker is None or parsed.marker.evaluate({"extra": ""}):
                pending.append(parsed.name)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, destination / "PYTHON-LICENSE.txt")
    for name in ("LICENSE", "README.md"):
        shutil.copy2(ROOT / name, destination / ("TRACK-SPLITTER-" + name))
    shutil.copy2(ROOT / "docs/THIRD_PARTY.md", destination / "THIRD_PARTY.md")
    shutil.copytree(ROOT / "docs/licenses", destination / "project-attributions", dirs_exist_ok=True)
    for item, archive_path in sources():
        with tarfile.open(archive_path) as archive:
            for member in archive:
                relative = Path(member.name)
                if not member.isfile() or relative.is_absolute() or ".." in relative.parts:
                    continue
                base = relative.name.lower()
                if not (base.startswith(("license", "licence", "copying", "notice", "copyright"))
                        or "LICENSES" in relative.parts):
                    continue
                target = destination / "library-sources" / item["component"] / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    shutil.copy2(CACHE / "w64devkit/COPYING.MinGW-w64-runtime.txt",
                 destination / "MinGW-runtime-LICENSE.txt")
    shutil.copy2(ROOT / "tools/packaging/library_sources.json", destination / "library-sources.json")
    for component in ("ffmpeg", "libsndfile"):
        shutil.copy2(BUILD / component / "track-splitter-build.json",
                     destination / (component + "-build.json"))
    (destination / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return inventory


if __name__ == "__main__":
    result = collect(ROOT / ".local/build/notices")
    print("Collected notices for", len(result), "installed runtime/build dependency distributions.")
