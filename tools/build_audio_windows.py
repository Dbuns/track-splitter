"""Build the Windows audio libraries and collect their exact source archives."""

import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache/build-toolchain"
BUILD = ROOT / ".local/build"
COMPILER = "w64devkit-x64-2.11.0.7z.exe"
COMPILER_URL = "https://github.com/skeeto/w64devkit/releases/download/v2.11.0/" + COMPILER
COMPILER_SHA256 = "54c2bb9962e8a30c8270e34c5efc3d5fee579f53087fa7d435b95fbba2af7b2b"
CMAKE = "cmake-4.4.5-windows-x86_64"
CMAKE_URL = "https://github.com/Kitware/CMake/releases/download/v4.4.5/" + CMAKE + ".zip"
CMAKE_SHA256 = "326c826486d46a23cf9d5a1c9ee3a567d427bdd02c4a34071937a2a675cff004"
FFMPEG_FLAGS = [
    "--target-os=mingw32", "--arch=x86_64", "--disable-everything",
    "--disable-autodetect", "--disable-network", "--disable-x86asm",
    "--disable-doc", "--disable-debug", "--disable-avdevice", "--disable-swscale",
    "--disable-programs", "--enable-ffmpeg", "--enable-protocol=file",
    "--enable-demuxer=wav,mp3,mov,flac,ogg,aac,aiff,asf",
    "--enable-parser=aac,mpegaudio,flac,opus,vorbis",
    "--enable-decoder=aac,aac_fixed,alac,flac,mp3float,mp3,vorbis,opus,wmav1,wmav2,"
    "pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,pcm_u8,pcm_s16be,pcm_s24be,"
    "pcm_s32be,pcm_f32be,pcm_f64be,pcm_mulaw,pcm_alaw",
    "--enable-encoder=pcm_s16le,pcm_f32le", "--enable-muxer=wav",
    "--enable-filter=atempo,aresample,aformat,anull,anullsrc", "--extra-ldflags=-static",
]
SNDFILE_FLAGS = [
    "-G", "MinGW Makefiles", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
    "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=ON",
    "-DENABLE_EXTERNAL_LIBS=OFF", "-DENABLE_MPEG=OFF", "-DBUILD_PROGRAMS=OFF",
    "-DBUILD_EXAMPLES=OFF", "-DBUILD_TESTING=OFF",
    "-DCMAKE_SHARED_LINKER_FLAGS=-static-libgcc -static",
]


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, path, expected):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(path.suffix + ".download")
        urlretrieve(url, temporary)
        if sha256(temporary) != expected:
            temporary.unlink()
            raise RuntimeError("Download checksum mismatch: " + url)
        temporary.replace(path)
    if sha256(path) != expected:
        raise RuntimeError("Cached file checksum mismatch: " + str(path))
    return path


def sources():
    manifest = json.loads((ROOT / "tools/packaging/library_sources.json").read_text())
    result = []
    for item in manifest:
        cached = CACHE / item["filename"]
        if not cached.exists():
            cached = ROOT / ".cache/license-sources" / item["filename"]
        result.append((item, download(item["url"], cached, item["sha256"])))
    return result


def short_path(path):
    # FFmpeg's makefiles require paths without spaces, including temporary paths.
    buffer = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer)):
        raise OSError("Cannot resolve Windows short path: " + str(path))
    return buffer.value.replace("\\", "/")


def build():
    if sys.platform != "win32":
        raise SystemExit("Build these audio libraries on Windows x64.")
    archives = sources()
    compiler = download(COMPILER_URL, CACHE / COMPILER, COMPILER_SHA256)
    binary_dir = CACHE / "w64devkit/bin"
    if not (binary_dir / "gcc.exe").exists():
        subprocess.run([str(compiler), "-y", "-o" + str(CACHE)], check=True)
    cmake_zip = download(CMAKE_URL, CACHE / (CMAKE + ".zip"), CMAKE_SHA256)
    cmake = CACHE / CMAKE / "bin/cmake.exe"
    if not cmake.exists():
        with zipfile.ZipFile(cmake_zip) as archive:
            archive.extractall(CACHE)
    env = os.environ.copy()
    env["PATH"] = short_path(binary_dir) + os.pathsep + str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
    env["CC"] = "gcc"
    for name in ("ffmpeg", "libsndfile"):
        archive_path = next(path for item, path in archives if item["component"] == name)
        source = CACHE / ("ffmpeg-9.0.2" if name == "ffmpeg" else "libsndfile-1.2.2")
        if not source.exists():
            with tarfile.open(archive_path) as archive:
                archive.extractall(CACHE, filter="data")
        folder = BUILD / name
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / ("ffmpeg.exe" if name == "ffmpeg" else "libsndfile.dll")
        stamp = folder / "track-splitter-build.json"
        flags = FFMPEG_FLAGS if name == "ffmpeg" else SNDFILE_FLAGS
        signature = dict(source_sha256=sha256(archive_path), flags=flags,
                         compiler_sha256=COMPILER_SHA256, cmake_sha256=CMAKE_SHA256)
        if target.exists() and stamp.exists() and json.loads(stamp.read_text()) == signature:
            continue
        temporary = folder / "tmp"
        temporary.mkdir(exist_ok=True)
        env["TMPDIR"] = env["TEMP"] = env["TMP"] = short_path(temporary)
        with (folder / "build.log").open("w") as log:
            if name == "ffmpeg":
                commands = [
                    [str(binary_dir / "sh.exe"), short_path(source / "configure"), *flags],
                    [str(binary_dir / "make.exe"), "-j4", "V=1", "ffmpeg.exe"],
                ]
            else:
                commands = [
                    [str(cmake), "-S", short_path(source), "-B", short_path(folder), *flags],
                    [str(cmake), "--build", short_path(folder), "-j", "4"],
                ]
            for command in commands:
                subprocess.run(command, cwd=short_path(folder), env=env, check=True,
                               stdout=log, stderr=subprocess.STDOUT)
        if not target.is_file():
            raise RuntimeError("Build output missing: " + str(target))
        stamp.write_text(json.dumps(signature, indent=2) + "\n", encoding="utf-8")
    output = subprocess.check_output([str(BUILD / "ffmpeg/ffmpeg.exe"), "-L"],
                                     stderr=subprocess.STDOUT, text=True)
    if "GNU Lesser General Public License" not in " ".join(output.split()) or "--enable-gpl" in output:
        raise RuntimeError("Unexpected FFmpeg licence configuration")
    return archives


def source_archive(version, archives):
    destination = ROOT / ".local/releases" / f"Track-Splitter-{version}-Library-Sources.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for item, path in archives:
            archive.write(path, "library-sources/" + item["filename"])
        for name in ("tools/build_audio_windows.py", "tools/packaging/library_sources.json",
                     "docs/THIRD_PARTY.md"):
            archive.write(ROOT / name, "library-sources/" + name)
        archive.write(CACHE / "w64devkit/COPYING.MinGW-w64-runtime.txt",
                      "library-sources/MinGW-runtime-LICENSE.txt")
    destination.with_suffix(".sha256").write_text(
        sha256(destination) + "  " + destination.name + "\n", encoding="utf-8")
    print("Library sources:", destination)
    return destination


if __name__ == "__main__":
    build()
