# PyInstaller one-folder Windows build. Never include user data or model weights.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parents[1]
datas = [(str(root / "assets"), "assets"), (str(root / ".local/build/notices"), "licenses")]
datas += collect_data_files("demucs")
datas += collect_data_files("imageio_ffmpeg", excludes=["binaries/*.exe"])
for distribution in ("demucs", "torch", "torchaudio", "PySide6", "soundfile", "sounddevice", "imageio-ffmpeg", "gdown"):
    datas += copy_metadata(distribution, recursive=True)
hidden = collect_submodules("demucs", filter=lambda name: not name.startswith("demucs.train"))
hidden += ["demucs.hdemucs", "demucs.htdemucs", "gdown", "omegaconf"]
analysis = Analysis(
    [str(root / "app/track_splitter.py")],
    pathex=[str(root / "app")],
    binaries=[(str(root / ".local/build/ffmpeg/ffmpeg.exe"), "ffmpeg")], datas=datas, hiddenimports=hidden,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["tkinter", "IPython", "matplotlib", "pandas", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtTest"],
    noarchive=False,
    module_collection_mode={"demucs": "pyz+py", "julius": "pyz+py"},
)
# These plugins introduce PDF/QML components that the Widgets interface does not use.
excluded = {
    "qt6pdf.dll", "qt6virtualkeyboard.dll", "qt6qml.dll", "qt6qmlmeta.dll",
    "qt6qmlmodels.dll", "qt6qmlworkerscript.dll", "qt6quick.dll",
    "qpdf.dll", "qtvirtualkeyboardplugin.dll",
}
analysis.binaries = [
    (name, str(root / ".local/build/libsndfile/libsndfile.dll"), kind)
    if name.replace("\\", "/").endswith("_soundfile_data/libsndfile_x64.dll")
    else (name, path, kind)
    for name, path, kind in analysis.binaries
    if Path(name).name.lower() not in excluded
    and not ("imageio_ffmpeg/binaries/" in name.replace("\\", "/") and name.endswith(".exe"))
]
analysis.datas = [
    item for item in analysis.datas
    if not ("imageio_ffmpeg/binaries/" in item[0].replace("\\", "/") and item[0].endswith(".exe"))
]
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True,
    name="Track Splitter", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
    icon=str(root / "assets/track_splitter.ico"),
)
collection = COLLECT(
    exe, analysis.binaries, analysis.datas,
    strip=False, upx=False, name="Track Splitter",
)
