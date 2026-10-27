"""Write FaunaPulse sessions in the folder layout of the Insect Detect camera trap.

insect-detect-post (Sittinger 2026, https://github.com/maxsitt/insect-detect-post, Zenodo
https://doi.org/10.5281/zenodo.21822140) reads what the Insect Detect camera writes (insect-detect
v2.0.0, `src/insectdetect/capture.py`, https://github.com/maxsitt/insect-detect): per recording
session a folder with one metadata CSV (one row per detected animal per saved photo), the photos
and a config JSON. This module writes that layout; no code of either project is copied.

Rules that insect-detect-post v1.1.0 relies on without stating them (checked in its code):
- each crop is matched back to its CSV row by the timestamp in the photo's file name
  (`YYYY-MM-DD_HH-MM-SS-ffffff`) plus the track ID, so the name must hold exactly the CSV
  `timestamp`, and two different photos must never share a timestamp;
- photo names are unique in the whole folder tree it reads, and a `.jpg` whose name contains
  `crop`, `overlay` or `timelapse` is not treated as a full photo;
- a CSV row without a photo still counts as one of the track's pictures and lowers its
  weighted probability, so only rows with a photo are written.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__
from .session_reader import Session, SessionError

# Column order of the camera's metadata CSV (insect-detect v2.0.0, capture.py), then ours.
CAMERA_COLUMNS = [
    "device_id", "session_id", "timestamp", "label", "confidence", "track_id", "track_status",
    "x_min", "y_min", "x_max", "y_max", "lens_position", "iso_sensitivity", "exposure_time",
    "filename",
]
FAUNAPULSE_COLUMNS = ["fp_photo", "fp_source_file", "fp_box_source", "fp_track_source"]

_NAME_TIME = "%Y-%m-%d_%H-%M-%S-%f"
_NAME_TIME_RE = re.compile(r"_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-\d{6})\.jpg$")
_RESERVED = re.compile(r"crop|overlay|timelapse", re.IGNORECASE)
SETTING_FIELDS = ("plant", "site", "habitat")


def clean_name_part(text: str, fallback: str) -> str:
    """Letters, digits and '-' only; never one of the words that change how post reads a file."""
    out = re.sub(r"[^A-Za-z0-9-]+", "-", text).strip("-")
    while _RESERVED.search(out):
        out = _RESERVED.sub("", out)
    return out.strip("-") or fallback


@dataclass
class Options:
    copy: bool = False  # True: copy the photos; False: hard link them where the disk allows it
    setting: str = "plant"  # field note used as the camera's `deployment.setting`, or "none"
    location: bool = True  # write the session's position into the config JSON
    overwrite: bool = False  # replace a session that was exported before


@dataclass
class Export:
    """Timestamps already used in the output folder, shared by every session of one export."""
    out: Path
    used: set[datetime] = field(default_factory=set)

    def __post_init__(self):
        self.rescan()

    def rescan(self) -> None:
        self.used.clear()
        if self.out.is_dir():
            for _dir, _subdirs, files in os.walk(self.out):
                for f in files:
                    m = _NAME_TIME_RE.search(f)
                    if m:
                        self.used.add(datetime.strptime(m.group(1), _NAME_TIME))

    def unique(self, t: datetime) -> tuple[datetime, bool]:
        nudged = False
        while t in self.used:
            t += timedelta(microseconds=1)
            nudged = True
        self.used.add(t)
        return t, nudged


def session_folder(out: Path, session: Session) -> Path:
    first = session.local_time(session.photos[0])
    device = clean_name_part(session.device_id, "phone")
    return out / device / "data" / f"{first:%Y-%m-%d}" / session.session_id


def earlier_exports(out: Path, session: Session) -> list[Path]:
    """Folders in `out` that already hold this session: the same name, or the same recording
    under an older name, for a session renamed after an export (insect-detect-post would
    otherwise count its photos twice). Same recording = same start moment
    (`start_of_session.session_id`, epoch ms) and same random session token: two phones can
    start in the same millisecond."""
    recording = (session.start.get("session_id"), session.start.get("file_token"))
    found = []
    for d in sorted((out / clean_name_part(session.device_id, "phone") / "data").glob("*/*")):
        if not d.is_dir():
            continue
        if d.name == session.session_id:
            found.append(d)
            continue
        for cfg in d.glob("*_config.json"):
            try:
                fp = json.loads(cfg.read_text(encoding="utf-8"))["faunapulse"]
                earlier = (fp["recording_id"], fp["file_token"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if recording[0] is not None and earlier == recording:
                found.append(d)
    return found


def _remove_export(folder: Path, out: Path) -> None:
    """Deletes one session folder written by this tool, and nothing else."""
    folder, out = folder.resolve(), out.resolve()
    ok = (out in folder.parents and len(folder.relative_to(out).parts) == 4
          and folder.parent.parent.name == "data" and any(folder.glob("*_metadata.csv")))
    if not ok:
        raise SessionError(f"will not delete {folder}: it does not look like an exported session")
    shutil.rmtree(folder)


def _place(src: Path, dst: Path, copy: bool) -> str:
    if not copy:
        try:
            os.link(src, dst)
            return "linked"
        except OSError:  # another disk, or a file system without hard links (FAT, exFAT)
            pass
    shutil.copy2(src, dst)
    return "copied"


def _config(session: Session, opts: Options) -> dict:
    start = session.start
    notes = start.get("field") if isinstance(start.get("field"), dict) else {}
    loc = start.get("location") if isinstance(start.get("location"), dict) else None
    setting = notes.get(opts.setting) if opts.setting in SETTING_FIELDS else None
    custom = notes.get("custom") if isinstance(notes.get("custom"), dict) else {}
    config = start.get("config") if isinstance(start.get("config"), dict) else {}
    # Frames kept from videos follow their "Find track IDs" run, photos the recording settings.
    keep = (session.post_track_start or {}).get("keep_frames")
    keep = keep if isinstance(keep, dict) else {}
    field_notes = {k: v for k, v in notes.items() if k != "location"} if notes else None
    return {
        # Same keys as the camera's `deployment` block (insect-detect configs/config.yaml).
        "deployment": {
            "start": start.get("time_iso"),
            "location": {
                "latitude": loc.get("lat"),
                "longitude": loc.get("lon"),
                "accuracy": loc.get("accuracy_m"),
            } if (loc and opts.location) else None,
            "setting": setting if isinstance(setting, str) and setting.strip() else None,
            "distance": None,  # unit differs from FaunaPulse's detection_distance_m (see field)
            "notes": custom.get("Notes"),
        },
        "faunapulse": {
            "session_folder": session.folder.name,
            "recording_id": session.start.get("session_id"),
            "file_token": session.start.get("file_token"),
            "app_version": start.get("app_version"),
            "app_build": start.get("app_build"),
            "track_source": session.track_source,
            "photo_step_s": keep.get("step_seconds", config.get("stepSeconds")),
            "photo_duration_s": keep.get("duration_seconds", config.get("durationSeconds")),
            "detector_model": start.get("model_path"),
            "field": field_notes,
            "exported_by": f"fauna-pulse-export {__version__}",
            "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    }


def write_session(session: Session, export: Export, opts: Options) -> dict:
    """Writes one session; returns its report entry."""
    folder = session_folder(export.out, session)
    earlier = earlier_exports(export.out, session)
    if earlier:
        if not opts.overwrite:
            return {"session": session.session_id, "refused": f"already exported to {earlier[0]} "
                    "(use --overwrite to replace it)"}
        for d in earlier:
            _remove_export(d, export.out)
        export.rescan()  # the removed photos' timestamps are free again
    folder.mkdir(parents=True)

    device = clean_name_part(session.device_id, "phone")
    token = clean_name_part(session.token(), "s")
    photos_dir = session.folder / "roi_frames"
    rows = []
    nudges = 0
    placed = {"linked": 0, "copied": 0}
    skipped = dict(session.skipped)
    for photo in session.photos:
        t, nudged = export.unique(session.local_time(photo))
        nudges += nudged
        name = f"{device}_{token}_{t.strftime(_NAME_TIME)}.jpg"
        boxes = []
        for b in photo.boxes:
            edges = [min(1.0, max(0.0, v)) for v in (b.left, b.top, b.right, b.bottom)]
            if edges[2] <= edges[0] or edges[3] <= edges[1]:
                skipped["empty_box"] = skipped.get("empty_box", 0) + 1
                continue
            boxes.append((b, edges))
        if not boxes:
            continue
        placed[_place(photos_dir / photo.source, folder / name, opts.copy)] += 1
        for b, (x0, y0, x1, y1) in sorted(boxes, key=lambda x: x[0].track_id):
            rows.append({
                "device_id": session.device_id,
                "session_id": session.session_id,
                # Six decimals always, equal to the name (post reads both and must match them).
                "timestamp": t.strftime("%Y-%m-%dT%H:%M:%S.%f"),
                "label": b.class_name or "unknown",  # post drops rows without a label
                "confidence": "" if b.confidence is None else round(b.confidence, 4),
                "track_id": b.track_id,
                "track_status": "TRACKED",
                "x_min": round(x0, 4), "y_min": round(y0, 4),
                "x_max": round(x1, 4), "y_max": round(y1, 4),
                "lens_position": "", "iso_sensitivity": "", "exposure_time": "",
                "filename": name,
                "fp_photo": photo.name,
                "fp_source_file": photo.source,
                "fp_box_source": photo.box_source,
                "fp_track_source": session.track_source,
            })

    stem = session.session_id
    with open(folder / f"{stem}_metadata.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMERA_COLUMNS + FAUNAPULSE_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with open(folder / f"{stem}_config.json", "w", encoding="utf-8") as f:
        json.dump(_config(session, opts), f, indent=2, ensure_ascii=False)

    return {
        "session": session.session_id,
        "folder": str(folder),
        "device_id": session.device_id,
        "track_source": session.track_source,
        "photos": placed["linked"] + placed["copied"],
        "photos_linked": placed["linked"],
        "photos_copied": placed["copied"],
        "rows": len(rows),
        "track_ids": len({r["track_id"] for r in rows}),
        "timestamps_moved_by_microseconds": nudges,
        "skipped": skipped,
    }
