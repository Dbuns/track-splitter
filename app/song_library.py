"""Local song catalogue, atomic autosave, and reversible library deletion."""

import hashlib
import json
import math
import os
import uuid
from pathlib import Path


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def migrate_session(data):
    if data.get("version") == 2:
        return data
    if data.get("version", 1) != 1:
        raise ValueError("Unsupported session version.")
    markers = sorted(data.get("markers", []), key=lambda m: m["time"])
    duration = data.get("duration", 0)
    sections = []
    for i, marker in enumerate(markers):
        end = markers[i + 1]["time"] if i + 1 < len(markers) else duration
        if end > marker["time"]:
            sections.append(
                dict(
                    id=uuid.uuid4().hex,
                    name=marker["name"],
                    start=marker["time"],
                    end=end,
                    enabled=False,
                )
            )
    old_loop = data.get("loop", {})
    if old_loop.get("enabled") and old_loop.get("end", 0) > old_loop.get("start", 0):
        match = next(
            (
                s
                for s in sections
                if abs(s["start"] - old_loop["start"]) < 0.02
                and abs(s["end"] - old_loop["end"]) < 0.02
            ),
            None,
        )
        if match:
            match["enabled"] = True
        else:
            sections.append(
                dict(
                    id=uuid.uuid4().hex,
                    name="Saved loop",
                    start=old_loop["start"],
                    end=old_loop["end"],
                    enabled=True,
                )
            )
    return dict(
        version=2,
        position=data.get("position", 0),
        master=data.get("master", 0.75),
        tracks=data.get("tracks", {}),
        sections=sections,
    )


def validate_session(data, duration):
    data = migrate_session(dict(data, duration=duration))

    def finite(value, low, high):
        if (
            not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ValueError("Invalid saved session setting.")

    finite(data.get("master", 0.75), 0, 1)
    finite(data.get("tempo_factor", 1.0), 0.5, 1.5)
    if data.get("base_bpm") is not None:
        finite(data["base_bpm"], 30, 300)
    finite(data.get("position", 0), 0, duration + 0.02)
    for track in data.get("tracks", {}).values():
        finite(track.get("gain", 1), 0, 2)
    for section in data.get("sections", []):
        if not isinstance(section.get("name"), str) or not section["name"].strip():
            raise ValueError("Invalid section name.")
        finite(section["start"], 0, duration)
        finite(section["end"], 0, duration + 0.02)
        section["end"] = min(section["end"], duration)
        if section["end"] <= section["start"]:
            raise ValueError("Invalid saved section range.")
        section.setdefault("id", uuid.uuid4().hex)
    return data


class Library:
    def __init__(self, root, discover=True):
        self.root = Path(root).resolve()
        self.path = self.root / "library" / "index.json"
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if self.data.get("version") != 1:
                raise ValueError("Unsupported library version.")
        else:
            self.data = dict(version=1, entries=[], active=None)
            if discover:
                self.discover()
            self.save()

    @property
    def entries(self):
        return self.data["entries"]

    def resolve(self, path):
        return (self.root / path).resolve()

    def relative(self, path):
        try:
            return os.path.relpath(Path(path).resolve(), self.root)
        except ValueError:
            return str(Path(path).resolve())

    def save(self):
        atomic_json(self.path, self.data)

    def find(self, entry_id):
        return next((e for e in self.entries if e["id"] == entry_id), None)

    def find_source(self, path):
        source = Path(path).resolve()
        for entry in self.entries:
            if self.resolve(entry["source"]) == source:
                return entry
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        return next((entry for entry in self.entries if entry["fingerprint"] == digest), None)

    def register(self, folder, save=True):
        folder = Path(folder).resolve()
        report = json.loads((folder / "verification.json").read_text(encoding="utf-8-sig"))
        source = Path(report["source"]).resolve()
        key = report.get("source_sha256") or str(source).casefold()
        entry = next((e for e in self.entries if e["fingerprint"] == key), None)
        if entry is None:
            identity = uuid.uuid4().hex
            entry = dict(
                id=identity,
                title=source.stem,
                source=self.relative(source),
                fingerprint=key,
                output=self.relative(folder),
                runs=[],
                session=f"library/sessions/{identity}.wavesplit",
            )
            self.entries.append(entry)
        relative = self.relative(folder)
        if relative not in entry["runs"]:
            entry["runs"].append(relative)
        entry["output"] = relative
        if save:
            self.save()
        return entry

    def discover(self):
        candidates = []
        for path in (self.root / "outputs").glob("*/verification.json"):
            try:
                report = json.loads(path.read_text(encoding="utf-8-sig"))
                candidates.append(
                    (
                        "guitar" in {s["stem"] for s in report["stems"]},
                        path.stat().st_mtime,
                        path.parent,
                    )
                )
            except (ValueError, KeyError, OSError, TypeError):
                continue
        # Register oldest/less complete first; the best existing guitar run wins.
        for _, _, folder in sorted(candidates):
            try:
                self.register(folder, save=False)
            except (ValueError, KeyError, OSError):
                continue
        for entry in self.entries:
            matches = []
            for project in self.root.glob("*.wavesplit"):
                try:
                    data = json.loads(project.read_text(encoding="utf-8-sig"))
                    if data.get("source") and (
                        project.parent / data["source"]
                    ).resolve() == self.resolve(entry["source"]):
                        matches.append((project.stat().st_mtime, data))
                except (ValueError, KeyError, OSError, TypeError):
                    continue
            if matches:
                legacy = max(matches, key=lambda p: p[0])[1]
                # Read the duration from the selected output.
                report = json.loads(
                    (self.resolve(entry["output"]) / "verification.json").read_text()
                )
                duration = report["stems"][0]["duration_seconds"]
                atomic_json(self.resolve(entry["session"]), validate_session(legacy, duration))
        if self.entries:
            self.data["active"] = self.entries[0]["id"]

    def ensure_five_tracks(self, entry):
        folder = self.resolve(entry["output"])
        if not (folder / "piano.wav").exists():
            return folder
        import shutil
        import time

        import numpy as np
        import soundfile as sf

        if folder.parent != (self.root / "outputs").resolve():
            raise ValueError("Cannot migrate stems outside the managed outputs folder.")
        destination = folder.with_name(folder.name + "_5tracks_" + uuid.uuid4().hex[:6])
        destination.mkdir(exist_ok=False)
        previous_output = entry["output"]
        previous_runs = list(entry.get("runs", []))
        started = time.perf_counter()
        try:
            other, rate = sf.read(folder / "other.wav", dtype="float32", always_2d=True)
            piano, piano_rate = sf.read(folder / "piano.wav", dtype="float32", always_2d=True)
            if rate != piano_rate or other.shape != piano.shape:
                raise ValueError("Piano and Other must match before migration.")
            sf.write(destination / "other.wav", other + piano, rate, subtype="FLOAT")
            for name in ("vocals", "drums", "bass", "guitar"):
                shutil.copy2(folder / (name + ".wav"), destination / (name + ".wav"))
            report = json.loads((folder / "verification.json").read_text(encoding="utf-8-sig"))
            checks = []
            for name in ("vocals", "drums", "bass", "guitar", "other"):
                path = destination / (name + ".wav")
                data, current_rate = sf.read(path, dtype="float32", always_2d=True)
                if current_rate != rate or data.shape != other.shape or not np.isfinite(data).all():
                    raise ValueError("Migrated stems failed validation.")
                checks.append(
                    dict(
                        stem=name,
                        path=str(path),
                        frames=len(data),
                        sample_rate=rate,
                        channels=data.shape[1],
                        duration_seconds=len(data) / rate,
                        rms=float(np.sqrt(np.mean(data**2))),
                        bytes=path.stat().st_size,
                    )
                )
            report.update(
                stems=checks,
                derived_from=self.relative(folder),
                migration="Piano summed into Other; remaining stems copied unchanged.",
                migration_seconds=time.perf_counter() - started,
            )
            atomic_json(destination / "verification.json", report)
            entry["output"] = self.relative(destination)
            entry["runs"] = previous_runs + [entry["output"]]
            self.save()
            return destination
        except Exception:
            entry["output"] = previous_output
            entry["runs"] = previous_runs
            if destination.resolve().parent != (self.root / "outputs").resolve():
                raise RuntimeError("Unexpected migration destination")
            shutil.rmtree(destination)
            raise

    def save_session(
        self, entry, mixer, sections, drums_expanded=False, base_bpm=None, tempo_factor=1.0
    ):
        with mixer.lock:
            data = dict(
                version=2,
                position=mixer.position / mixer.rate,
                master=mixer.master,
                drums_expanded=bool(drums_expanded),
                base_bpm=base_bpm,
                tempo_factor=tempo_factor,
                tracks={
                    name: dict(
                        gain=mixer.gains[name], mute=name in mixer.muted, solo=name in mixer.solo
                    )
                    for name in mixer.tracks
                },
                sections=[dict(s) for s in sections],
            )
        validate_session(data, mixer.duration)
        atomic_json(self.resolve(entry["session"]), data)

    def read_session(self, entry, duration):
        path = self.resolve(entry["session"])
        return (
            validate_session(json.loads(path.read_text(encoding="utf-8-sig")), duration)
            if path.exists()
            else dict(version=2, sections=[])
        )

    def activate(self, entry):
        self.data["active"] = entry["id"]
        self.save()

    def remove(self, entry):
        """Move only managed generated runs and session to local trash; keep source."""
        original = self.resolve(entry["source"])
        targets = []
        for value in entry.get("runs", [entry["output"]]):
            target = self.resolve(value)
            if not target.exists():
                continue
            if target.parent != (self.root / "outputs").resolve():
                raise ValueError(
                    "This stem folder is outside the managed outputs folder; it was kept."
                )
            if target.is_symlink() or original == target or target in original.parents:
                raise ValueError("The original audio is inside this folder. Nothing was removed.")
            if not (target / "verification.json").is_file():
                raise ValueError("Unrecognised output folder; nothing was removed.")
            if target not in targets:
                targets.append(target)
        session = self.resolve(entry["session"])
        if session.exists():
            if session.parent != (self.root / "library" / "sessions").resolve():
                raise ValueError("Unexpected session location.")
            targets.append(session)
        trash = self.root / ".trash" / uuid.uuid4().hex
        trash.mkdir(parents=True, exist_ok=False)
        moved = []
        previous = list(self.entries)
        previous_active = self.data["active"]
        try:
            for i, target in enumerate(targets):
                destination = trash / (str(i) + "_" + target.name)
                os.replace(target, destination)
                moved.append((target, destination))
            atomic_json(
                trash / "restore.json",
                dict(
                    entry=entry,
                    paths=[dict(original=self.relative(a), trash=b.name) for a, b in moved],
                ),
            )
            self.data["entries"] = [e for e in self.entries if e["id"] != entry["id"]]
            if self.data["active"] == entry["id"]:
                self.data["active"] = None
            self.save()
        except Exception:
            self.data["entries"] = previous
            self.data["active"] = previous_active
            for target, destination in reversed(moved):
                os.replace(destination, target)
            raise
        return trash
