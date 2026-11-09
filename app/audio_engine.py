"""One shared audio clock for every stem. Mixing is independent of the UI."""

import threading
from pathlib import Path

import numpy as np
import soundfile as sf

ORDER = ("vocals", "drums", "bass", "guitar", "other")
DRUM_CHILDREN = ("kick", "snare", "cymbals", "toms")


class Mixer:
    def __init__(self):
        self.lock = threading.RLock()
        self.tracks = {}
        self.drum_children = ()
        self.tempo_factor = 1.0
        self._tempo = None
        self.gains = {}
        self.muted = set()
        self.solo = set()
        self.master = 0.75
        self.rate = 44100
        self.frames = 0
        self.position = 0
        self.playing = False
        self.loop = None
        self.ranges = []
        self.range_index = 0
        self.stream = None
        self.peak = 0.0
        self.underruns = 0

    def load(self, folder):
        tracks = {}
        shape = None
        rate = None
        for name in ORDER:
            path = Path(folder) / (name + ".wav")
            if not path.exists():
                continue
            data, current_rate = sf.read(path, dtype="float32", always_2d=True)
            if data.shape[1] != 2 or not len(data) or not np.isfinite(data).all():
                raise ValueError(f"{name}: expected finite stereo audio")
            if shape is not None and (data.shape != shape or current_rate != rate):
                raise ValueError("Stems must have matching duration, sample rate and channels.")
            tracks[name] = np.ascontiguousarray(data)
            shape, rate = data.shape, current_rate
        piano = Path(folder) / "piano.wav"
        if piano.exists():
            data, current_rate = sf.read(piano, dtype="float32", always_2d=True)
            if (
                shape is None
                or data.shape != shape
                or current_rate != rate
                or not np.isfinite(data).all()
            ):
                raise ValueError("Piano must match the other stems.")
            tracks["other"] = tracks.get("other", np.zeros_like(data)) + data
        if not tracks:
            raise ValueError("This folder has no recognised WAV stems.")
        self.close()
        with self.lock:
            self.tracks = tracks
            self.drum_children = ()
            self.tempo_factor = 1.0
            self._tempo = None
            self.rate = rate
            self.frames = shape[0]
            self.position = 0
            self.gains = {name: 1.0 for name in tracks}
            self.muted.clear()
            self.solo.clear()
            self.loop = None
            self.ranges = []
            self.range_index = 0
            self.peak = 0.0
            self.underruns = 0

    def load_drum_children(self, folder):
        if "drums" not in self.tracks:
            raise ValueError("Load a song with a drum stem first.")
        tracks = {}
        for name in DRUM_CHILDREN:
            data, rate = sf.read(Path(folder) / (name + ".wav"), dtype="float32", always_2d=True)
            if rate != self.rate or data.shape != (self.frames, 2) or not np.isfinite(data).all():
                raise ValueError(
                    "Drum sub-tracks must match the song length, stereo channels and sample rate."
                )
            tracks[name] = np.ascontiguousarray(data)
        with self.lock:
            self._tempo = None
            self.tempo_factor = 1.0
            self.tracks.update(tracks)
            for name in tracks:
                self.gains.setdefault(name, 1.0)
            self.drum_children = DRUM_CHILDREN

    def set_tempo_tracks(self, tracks=None, factor=1.0):
        if tracks is None or abs(factor - 1) < 1e-8:
            with self.lock:
                self._tempo = None
                self.tempo_factor = 1.0
            return
        if not 0.5 <= factor <= 1.5 or set(tracks) != set(self.tracks):
            raise ValueError("Invalid prepared tempo.")
        count = round(self.frames / factor)
        if any(a.shape != (count, 2) or not np.isfinite(a).all() for a in tracks.values()):
            raise ValueError("Tempo tracks are not aligned.")
        prepared = Mixer()
        prepared.tracks = tracks
        prepared.frames = count
        prepared.rate = self.rate
        prepared.drum_children = self.drum_children
        prepared.position = min(count, round(self.position / factor))
        with self.lock:
            self._tempo = prepared
            self.tempo_factor = factor

    @property
    def duration(self):
        return self.frames / self.rate

    def configure(self, name, gain=None, mute=None, solo=None):
        with self.lock:
            if name not in self.tracks:
                raise ValueError("Unknown track")
            if gain is not None:
                self.gains[name] = max(0.0, min(2.0, float(gain)))
            for value, target in ((mute, self.muted), (solo, self.solo)):
                if value is not None:
                    target.add(name) if value else target.discard(name)

    def seek(self, seconds):
        with self.lock:
            self.position = min(self.frames, max(0, round(seconds * self.rate)))
            if self._tempo is not None:
                self._tempo.seek(seconds / self.tempo_factor)
            if self.ranges:
                self.range_index = next(
                    (i for i, (a, b) in enumerate(self.ranges) if a <= self.position < b), 0
                )

    def set_ranges(self, ranges):
        import math

        converted = []
        for start, end in sorted(ranges):
            if not math.isfinite(start) or not math.isfinite(end):
                raise ValueError("Section times must be finite.")
            a, b = round(start * self.rate), round(end * self.rate)
            if not 0 <= a < b <= self.frames:
                raise ValueError("Each section must end after it starts, within the song.")
            converted.append((a, b))
        with self.lock:
            self.ranges = converted
            self.loop = None
            self.range_index = next(
                (i for i, (a, b) in enumerate(converted) if a <= self.position < b), 0
            )

    def set_loop(self, start, end, enabled):
        with self.lock:
            self.ranges = []
            self.range_index = 0
            if enabled:
                a, b = round(start * self.rate), round(end * self.rate)
                if not 0 <= a < b <= self.frames:
                    raise ValueError("Loop end must be after its start and within the song.")
                self.loop = (a, b)
            else:
                self.loop = None

    def render(self, count):
        """Render exactly count frames, wrapping short loops without clock drift."""
        with self.lock:
            if self._tempo is not None:
                prepared = self._tempo
                factor = self.tempo_factor
                prepared.gains = dict(self.gains)
                prepared.muted = set(self.muted)
                prepared.solo = set(self.solo)
                prepared.master = self.master
                prepared.playing = self.playing
                ranges = self.ranges or ([self.loop] if self.loop else [])
                converted = [
                    (
                        min(prepared.frames - 1, round(a / factor)),
                        min(prepared.frames, max(round(a / factor) + 1, round(b / factor))),
                    )
                    for a, b in ranges
                ]
                if converted != prepared.ranges:
                    prepared.ranges = converted
                    prepared.range_index = next(
                        (i for i, (a, b) in enumerate(converted) if a <= prepared.position < b), 0
                    )
                data = prepared.render(count)
                self.position = min(self.frames, round(prepared.position * factor))
                self.playing = prepared.playing
                self.peak = prepared.peak
                return data
        output = np.zeros((count, 2), dtype="float32")
        with self.lock:
            if not self.playing or not self.tracks:
                self.peak = 0.0
                return output
            cursor = 0
            while cursor < count:
                active = self.ranges or ([self.loop] if self.loop else [])
                if active:
                    self.range_index %= len(active)
                    a, b = active[self.range_index]
                    if not a <= self.position < b:
                        self.position = a
                    end = b
                else:
                    end = self.frames
                length = min(count - cursor, end - self.position)
                if length <= 0:
                    self.playing = False
                    break
                children = set(self.drum_children)
                child_solos = self.solo & children
                for name, data in self.tracks.items():
                    if name in children or (name == "drums" and children):
                        continue
                    if name not in self.muted and (not self.solo or name in self.solo):
                        output[cursor : cursor + length] += (
                            data[self.position : self.position + length] * self.gains[name]
                        )
                if (
                    children
                    and "drums" not in self.muted
                    and (not self.solo or "drums" in self.solo or child_solos)
                ):
                    for name in self.drum_children:
                        if name not in self.muted and (not child_solos or name in child_solos):
                            output[cursor : cursor + length] += (
                                self.tracks[name][self.position : self.position + length]
                                * self.gains[name]
                                * self.gains["drums"]
                            )
                self.position += length
                cursor += length
                if active and self.position >= active[self.range_index][1]:
                    self.range_index = (self.range_index + 1) % len(active)
                    self.position = active[self.range_index][0]
                elif self.position >= self.frames:
                    self.playing = False
                    break
            output *= self.master
            self.peak = float(np.max(np.abs(output))) if count else 0.0
            np.clip(output, -1, 1, out=output)
        return output

    def _callback(self, outdata, frames, timing, status):
        if status:
            self.underruns += 1
        outdata[:] = self.render(frames)

    def play(self):
        if not self.tracks:
            return
        if self.stream is None:
            import sounddevice as sd

            stream = sd.OutputStream(
                samplerate=self.rate,
                channels=2,
                dtype="float32",
                callback=self._callback,
                blocksize=2048,
            )
            try:
                stream.start()
            except Exception:
                stream.close()
                raise
            self.stream = stream
        with self.lock:
            if self.position >= self.frames:
                self.seek(
                    (self.ranges[0][0] if self.ranges else (self.loop[0] if self.loop else 0))
                    / self.rate
                )
            self.playing = True

    def pause(self):
        with self.lock:
            self.playing = False

    def stop(self):
        with self.lock:
            self.playing = False
            self.seek(
                (self.ranges[0][0] if self.ranges else (self.loop[0] if self.loop else 0))
                / self.rate
            )

    def close(self):
        self.pause()
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
