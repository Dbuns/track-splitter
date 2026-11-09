"""Read-only integrity check for a local song library."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_audio(path, expected=None):
    with sf.SoundFile(path) as audio:
        shape = (audio.frames, audio.samplerate, audio.channels)
        assert audio.frames > 0 and audio.samplerate == 44100 and audio.channels == 2, path
        if expected is not None:
            assert shape == expected, (path, shape, expected)
        energy = 0.0
        for block in audio.blocks(blocksize=262144, dtype="float32", always_2d=True):
            assert np.isfinite(block).all(), path
            energy += float(np.sum(block.astype("float64") ** 2))
        assert energy > 0, f"Silent track: {path}"
        return shape


def main():
    from song_library import Library

    library = Library(ROOT, discover=False)
    results = []
    for entry in library.entries:
        source = library.resolve(entry["source"])
        assert sha256(source) == entry["fingerprint"], source
        folder = library.resolve(entry["output"])
        report = json.loads((folder / "verification.json").read_text(encoding="utf-8-sig"))
        assert Path(report["source"]).resolve() == source
        assert report["source_sha256"] == entry["fingerprint"]
        expected = None
        tracks = []
        for name in ("vocals", "drums", "bass", "guitar", "other"):
            expected = verify_audio(folder / (name + ".wav"), expected)
            tracks.append(name)
        drum_folder = folder / "drum tracks"
        if drum_folder.exists():
            drum_report = json.loads(
                (drum_folder / "verification.json").read_text(encoding="utf-8-sig")
            )
            assert drum_report["source_sha256"] == sha256(folder / "drums.wav")
            for name in ("kick", "snare", "cymbals", "toms"):
                verify_audio(drum_folder / (name + ".wav"), expected)
                tracks.append(name)
        session = library.read_session(entry, expected[0] / expected[1])
        results.append(
            dict(
                song=entry["title"],
                original_sha256=entry["fingerprint"],
                verified_tracks=tracks,
                frames=expected[0],
                sample_rate=expected[1],
                saved_sections=len(session.get("sections", [])),
            )
        )
    print(json.dumps(results, indent=2))
    print(
        f"PASS: {len(results)} songs; original hashes, saved sessions and matching non-silent stems."
    )


if __name__ == "__main__":
    main()
