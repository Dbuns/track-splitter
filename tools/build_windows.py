"""Build the Windows application folder, ZIP and SHA256 file."""

import hashlib
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from build_audio_windows import build, source_archive
from collect_notices import collect

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("Build this Windows x64 package on Windows x64.")
    sys.path.insert(0, str(ROOT / "app"))
    from version import VERSION

    archives = build()
    collect(ROOT / ".local/build/notices")
    release_root = (ROOT / ".local/releases").resolve()
    bundle = (release_root / "Track Splitter").resolve()
    if bundle.parent != release_root or bundle.name != "Track Splitter":
        raise RuntimeError("Unexpected build output path")
    if bundle.exists():
        def remove_readonly(function, path, error):
            if not isinstance(error, PermissionError):
                raise error
            Path(path).chmod(stat.S_IWRITE)
            function(path)

        shutil.rmtree(bundle, onexc=remove_readonly)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--distpath",
            str(ROOT / ".local/releases"),
            "--workpath",
            str(ROOT / ".local/build/pyinstaller"),
            str(ROOT / "tools/packaging/track_splitter.spec"),
        ],
        cwd=ROOT,
        check=True,
    )
    bundle = ROOT / ".local/releases/Track Splitter"
    (bundle / "START-HERE.txt").write_text(
        f"Track Splitter {VERSION}\n\n"
        "Extract the whole ZIP, then double-click Track Splitter.exe. "
        "Keep the _internal folder beside it.\n\n"
        "Python is not required. Models download on first use; audio processing runs locally.\n\n"
        "Add a song with + or drag an audio file into the window.\n\n"
        "Saved data: %LOCALAPPDATA%/TrackSplitter\n\n"
        "Licences: LICENSE.txt and _internal/licenses/THIRD_PARTY.md\n\n"
        f"Matching library sources: Track-Splitter-{VERSION}-Library-Sources.zip\n\n"
        "This Windows build is unsigned.\n",
        encoding="utf-8",
    )
    shutil.copy2(ROOT / "LICENSE", bundle / "LICENSE.txt")
    archive = Path(
        shutil.make_archive(
            str(ROOT / ".local/releases" / ("Track-Splitter-" + VERSION + "-Windows-x64")),
            "zip",
            root_dir=ROOT / ".local/releases",
            base_dir="Track Splitter",
        )
    )
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    checksum = archive.with_suffix(".sha256")
    checksum.write_text(digest.hexdigest() + "  " + archive.name + "\n", encoding="utf-8")
    source_archive(VERSION, archives)
    print("Built:", archive)
    print("ZIP size MiB:", round(archive.stat().st_size / 1024**2, 1))
    print("SHA256:", digest.hexdigest())


if __name__ == "__main__":
    main()
