"""Export a snapshot of the full-song mix without changing playback settings."""

from datetime import datetime
from pathlib import Path

import soundfile as sf
from audio_engine import Mixer


def snapshot(mixer):
    copy = Mixer()
    with mixer.lock:
        copy.tracks = dict((mixer._tempo or mixer).tracks)
        copy.drum_children = tuple(mixer.drum_children)
        copy.gains = dict(mixer.gains)
        copy.muted = set(mixer.muted)
        copy.solo = set(mixer.solo)
        copy.master = mixer.master
        copy.rate = mixer.rate
        copy.frames = (mixer._tempo or mixer).frames
    return copy


def export_mix(mixer, folder, name, progress=lambda message: None):
    if not mixer.tracks:
        raise ValueError("Open stems before exporting a mix.")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".wav")
    mixer.position = 0
    mixer.loop = None
    mixer.playing = True
    clipped = False
    created = False
    try:
        with sf.SoundFile(
            path, mode="x", samplerate=mixer.rate, channels=2, subtype="PCM_24"
        ) as writer:
            created = True
            while mixer.position < mixer.frames:
                count = min(65536, mixer.frames - mixer.position)
                block = mixer.render(count)
                clipped = clipped or mixer.peak > 1
                writer.write(block)
        progress(
            "Mix exported"
            + (" (peaks clipped — reduce volume for a cleaner export)." if clipped else ".")
        )
        return path
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise
