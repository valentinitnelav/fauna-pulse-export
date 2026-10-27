"""Read a FaunaPulse session folder: which saved photo shows which track ID, with which box.

The rules follow the app's identification crop planner, so that an exported session holds
exactly the photo and box pairs that the phone's "Identify organisms" used. Keep in sync with
the app (https://github.com/valentinitnelav/fauna-pulse):

- which file holds the track IDs: `lib/fauna_pulse/logging/track_source.dart`
  (`trackSourceOf`, `liveTrackerRan`);
- photos and their boxes: `lib/fauna_pulse/logging/session_log_index.dart`
  (`_IndexBuilder._apply`, `_addPhotoEntry`, `_readCapture`);
- which file is read and which box is used: `lib/fauna_pulse/identification/crop_planner.dart`
  (`planFromIndex`);
- device name: `lib/fauna_pulse/models/field_notes.dart` (`deviceNameOf`, `phoneModelOf`; the
  device_id of `tracks_<pack>.csv` since app round 335), here `device_id_of`; session ID: the
  folder name, as `lib/fauna_pulse/identification/identification_job.dart` writes it, plus the
  session token (`export_session_id`).

The record dictionary is the app's `docs/DATA_GUIDE.md`. Two deliberate differences from the
planner: every photo is kept (the planner keeps at most 10 per track ID for Identify), and a
box marked `coasted` (a tracker prediction, not a detection; normally never written) is left
out, because insect-detect-post would cut a crop where no animal was seen.
"""

from __future__ import annotations

import json
import math
import re
import string
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

SESSION_LOG = "session.jsonl"
POST_TRACKS = "post_tracks.jsonl"
POST_DETECTIONS = "post_detections.jsonl"
PHOTOS_DIR = "roi_frames"

# Record types that describe tracked animals: read only from the file that holds the track IDs.
# `capture` records describe photos wherever they are and are read from both files.
_TRACK_TYPES = {"detection", "detections", "track_event"}

# Lines worth decoding. Frame records without a photo name add nothing to the photos, and most
# frames have none, so they are skipped before the (slow) JSON decode.
_PHOTO_TYPES = ('"capture"', '"motion_capture"', '"timelapse_capture"', '"gt_capture"')
_HEAD_TYPES = ('"start_of_session"', '"post_track_start"')

# Photo name written by the app (`roiPhotoFileName` in lib/fauna_pulse/capture/roi_capture.dart):
# roi_<token>_<yyyy-MM-dd>_<HHmmss>_<SSS>.jpg in local time; FaunaLapse imports have no _<SSS>.
_PHOTO_NAME = re.compile(r"^roi_([a-z0-9]+)_(\d{4}-\d{2}-\d{2})_(\d{6})(?:_(\d{3}))?\.jpg$")


class SessionError(Exception):
    """The folder cannot be exported; the message says why in plain words."""


@dataclass
class PhotoBox:
    track_id: int
    left: float
    top: float
    right: float
    bottom: float
    confidence: float | None
    class_name: str | None


@dataclass
class Photo:
    name: str  # the photo's name in the log
    source: str  # the file in roi_frames/ that is used (the `_live` companion when it exists)
    box_source: str  # 'live' (companion, exact) or 'trigger' (main photo, trigger-frame box)
    capture_ms: int
    boxes: list[PhotoBox]


@dataclass
class Session:
    folder: Path
    session_id: str
    device_id: str
    device_id_source: str  # see device_id_of
    start: dict
    track_source: str  # 'live' or 'afterwards'
    post_track_start: dict | None
    photos: list[Photo]
    skipped: Counter = field(default_factory=Counter)

    @property
    def track_ids(self) -> set[int]:
        return {b.track_id for p in self.photos for b in p.boxes}

    def local_time(self, photo: Photo) -> datetime:
        """The photo's trigger moment in the phone's local time, without a time zone.

        The app's photo name holds exactly this moment (to the millisecond), so it is used when
        it can be read; it also stays right across a daylight-saving change. Otherwise (FaunaLapse
        imports name whole seconds) `captured_at_ms` is shifted by the session's UTC offset.
        """
        m = _PHOTO_NAME.match(photo.name)
        if m and m.group(4) is not None:
            return datetime.strptime(f"{m.group(2)} {m.group(3)} {m.group(4)}", "%Y-%m-%d %H%M%S %f")
        return datetime.fromtimestamp(photo.capture_ms / 1000, tz=self._utc_offset()).replace(tzinfo=None)

    def _utc_offset(self) -> timezone:
        iso = self.start.get("time_iso")
        if isinstance(iso, str):
            try:
                offset = datetime.fromisoformat(iso).utcoffset()
                if offset is not None:
                    return timezone(offset)
            except ValueError:
                pass
        # No usable start time: the offset that turns a photo name's local time into its
        # captured_at_ms (rounded to 15 minutes, the finest real-world offset step).
        for p in self.photos:
            m = _PHOTO_NAME.match(p.name)
            if m:
                local = datetime.strptime(f"{m.group(2)} {m.group(3)}", "%Y-%m-%d %H%M%S")
                utc = datetime.fromtimestamp(p.capture_ms // 1000, tz=timezone.utc).replace(tzinfo=None)
                quarters = round((local - utc).total_seconds() / 900)
                return timezone(timedelta(seconds=quarters * 900))
        raise SessionError("the session's time zone is unknown (no start time, no readable photo names)")

    def token(self) -> str:
        """The 4-character session token of the photo names (`file_token`), or ''."""
        t = self.start.get("file_token")
        if isinstance(t, str) and t:
            return t
        for p in self.photos:
            m = _PHOTO_NAME.match(p.name)
            if m:
                return m.group(1)
        return ""


def _lines(path: Path):
    # Same tolerance as the app: a line cut by a crash, or valid JSON of an unexpected shape,
    # is skipped (pattern of read_jsonl in fauna-pulse tool/video_eval/evaluate_track_ids.py).
    with open(path, encoding="utf-8", errors="replace") as f:
        yield from f


def _decode(line: str) -> dict | None:
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    return rec if isinstance(rec, dict) else None


def read_start(log: Path) -> dict | None:
    """The `start_of_session` record (the log's first line; a few lines are searched)."""
    for i, line in enumerate(_lines(log)):
        if i > 50:
            break
        if '"start_of_session"' in line:
            rec = _decode(line)
            if rec and rec.get("type") == "start_of_session":
                return rec
    return None


def live_tracker_ran(config) -> bool:
    """Mirrors `liveTrackerRan` (track_source.dart)."""
    if not isinstance(config, dict):
        return False
    trigger = config.get("captureTrigger")
    if isinstance(trigger, str):
        return trigger == "detector"
    return config.get("motionOnlyCapture") is not True


class _PhotoAcc:
    def __init__(self, name: str, capture_ms: int):
        self.name = name
        self.capture_ms = capture_ms
        self.boxes: list[PhotoBox] = []
        self.track_conf: dict[int, float] = {}
        self.live_name: str | None = None
        self.is_reference = False


class _Builder:
    """Mirrors `_IndexBuilder` (session_log_index.dart), only the parts about photos."""

    def __init__(self):
        self.order: list[str] = []
        self.photos: dict[str, _PhotoAcc] = {}
        self.post_track_start: dict | None = None
        self.skipped = Counter()

    def _photo(self, name: str, capture_ms: int) -> _PhotoAcc:
        p = self.photos.get(name)
        if p is None:
            p = self.photos[name] = _PhotoAcc(name, capture_ms)
            self.order.append(name)
        return p

    def feed(self, path: Path, tracks: bool, other: bool) -> None:
        for line in _lines(path):
            if not (('"jpeg"' in line and '"detection' in line)
                    or any(t in line for t in _PHOTO_TYPES)
                    or any(t in line for t in _HEAD_TYPES)):
                continue
            rec = _decode(line)
            if rec is None:
                continue
            try:
                self._apply(rec, tracks, other)
            except (TypeError, ValueError, AttributeError):
                pass  # a field of the wrong type: skip this line only, as the app does

    def _apply(self, rec: dict, tracks: bool, other: bool) -> None:
        kind = rec.get("type")
        if kind != "capture" and (not tracks if kind in _TRACK_TYPES else not other):
            if kind == "post_track_start" and self.post_track_start is None:
                self.post_track_start = rec
            return
        t = _int(rec.get("time_ms")) or 0
        if kind == "detection":  # one line per track ID (sessions up to round 68)
            self._add_entry(rec, t, None)
        elif kind == "detections":  # one line per frame (round 69+)
            entries = [e for e in rec.get("tracks") or [] if isinstance(e, dict)]
            # The frame's shared photo goes to the entries without their own, so every animal
            # visible in the photo gets its box (round 86).
            frame_jpeg = next((e["jpeg"] for e in entries if isinstance(e.get("jpeg"), str)), None)
            for e in entries:
                self._add_entry(e, t, frame_jpeg)
        elif kind == "capture":
            self._read_capture(rec)
        elif kind in ("motion_capture", "timelapse_capture", "gt_capture"):
            jpeg = rec.get("jpeg")
            if isinstance(jpeg, str) and jpeg and jpeg not in self.photos:
                p = self._photo(jpeg, _int(rec.get("captured_at_ms")) or t)
                p.is_reference = kind == "gt_capture"
        elif kind == "post_track_start" and self.post_track_start is None:
            self.post_track_start = rec

    def _read_capture(self, rec: dict) -> None:
        name = rec.get("file")
        if not isinstance(name, str) or not name:
            return
        p = self._photo(name, _int(rec.get("time_ms")) or 0)
        cap = _int(rec.get("captured_at_ms"))
        if cap is not None:
            p.capture_ms = cap
        live = rec.get("live_jpeg")
        if isinstance(live, str) and live:
            p.live_name = live

    def _add_entry(self, entry: dict, t: int, frame_jpeg: str | None) -> None:
        own = entry.get("jpeg") if isinstance(entry.get("jpeg"), str) else None
        jpeg = own if own is not None else frame_jpeg  # Dart `own ?? frameJpeg`: "" stays ""
        if not jpeg:
            return
        p = self._photo(jpeg, t)
        tid = _int(entry.get("track_id"))
        conf = _float(entry.get("confidence"))
        if tid is not None and conf is not None:
            p.track_conf[tid] = conf
        box = entry.get("box_in_roi")
        if not isinstance(box, dict):
            return
        if tid is None:
            self.skipped["box_without_track_id"] += 1
            return
        if entry.get("coasted") is True:
            self.skipped["predicted_box"] += 1
            return
        p.boxes.append(PhotoBox(
            track_id=tid,
            left=_float(box.get("left")) or 0.0,
            top=_float(box.get("top")) or 0.0,
            right=_float(box.get("right")) or 0.0,
            bottom=_float(box.get("bottom")) or 0.0,
            confidence=conf,
            class_name=entry.get("class_name") if isinstance(entry.get("class_name"), str) else None,
        ))


def _int(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _float(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


# insect-detect-post drops every row whose device_id is empty, so a session without any device
# name gets this one. Imported videos have none: the phone did not film them, so the camera is
# unknown unless the user names it (--device-id).
UNKNOWN_DEVICE = "unknown camera"

# A field of the user's own with this name (Field notes, "+ Add a field", in both apps; FaunaLapse's
# help suggests it) names the device, as the camera's hostname does. Matched without case, spaces,
# "_" or "-", so "device_id" and "Device-ID" count too.
DEVICE_ID_FIELD = "Device ID"


# insect-detect-post makes a folder `<device_id>_<session_id>_ID<track>` for each track ID when it
# sorts the crops (pipeline_runner.py), so a typed name must not hold what file names cannot.
_NOT_IN_FILE_NAMES = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')

# The spaces trimmed from names and ignored in field names. Spaces, letter case and number
# notation are spelled out here and in the app's deviceNameOf, because Dart and Python treat some
# characters differently (str.strip and Dart's trim, for example, disagree on the byte order mark).
_SPACES = " \t\n\r\x0b\x0c\u00a0\ufeff"
_FIELD_NAME_IGNORED = re.compile("[" + re.escape(_SPACES) + "_-]+")
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def _plain(name) -> str:
    """A field name compared without spaces, "_", "-" and the case of A to Z."""
    return _FIELD_NAME_IGNORED.sub("", str(name)).translate(_ASCII_LOWER)


def _safe(name: str | None) -> str:
    """[name] with what file names cannot hold as "-", and "-", "." and spaces dropped at the ends."""
    return _NOT_IN_FILE_NAMES.sub("-", name or "").strip(" .-")


def _text(v) -> str | None:
    """A record value that can be a name: text or a finite number, trimmed; None for anything else
    (a yes/no field is no name) or empty text. A whole number is written without decimals (7.0 as
    7, as a number field records it); the app writes numbers the same way."""
    if isinstance(v, bool) or not isinstance(v, (str, int, float)):
        return None
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        if v.is_integer():
            v = int(v)
    return str(v).strip(_SPACES) or None


def phone_model_of(start: dict) -> str | None:
    """Mirrors the app's `phoneModelOf`: `device.model`, else `device_model` (the phone_model of
    tracks_<pack>.csv since app round 335, its device_id before)."""
    d = start.get("device")
    return _text(d.get("model") if isinstance(d, dict) else None) or _text(start.get("device_model"))


def device_id_of(start: dict, fallback: str | None = None) -> tuple[str, str]:
    """The device's name in the export and where it came from: the first filled "Device ID" field, else
    FaunaLapse's phone ID (`field.phone_id`, 8 characters of Android's ID; always empty in
    FaunaPulse), else the phone model, else [fallback] (--device-id), else UNKNOWN_DEVICE.

    Up to the fallback this is the app's `deviceNameOf` (lib/fauna_pulse/models/field_notes.dart,
    since app round 335 the device_id of tracks_<pack>.csv); keep the two in sync. Both test the
    same cases: tests/fixtures/device_name_cases.json, copied in the app's test/fauna_pulse/fixtures/.
    """
    notes = start.get("field") if isinstance(start.get("field"), dict) else {}
    custom = notes.get("custom") if isinstance(notes.get("custom"), dict) else {}
    own = next((n for k, v in custom.items() if _plain(k) == _plain(DEVICE_ID_FIELD) and (n := _safe(_text(v)))), "")
    for name, source in ((own, "field " + DEVICE_ID_FIELD), (_safe(_text(notes.get("phone_id"))), "phone ID"),
                         (_safe(phone_model_of(start)), "phone model"), (_safe(_text(fallback)), "--device-id")):
        if name:
            return name, source
    return UNKNOWN_DEVICE, "none"


def export_session_id(folder_name: str, start: dict) -> str:
    """The session's ID in the export: its folder name plus the session token (`file_token`).

    insect-detect-post keys a track by (device_id, session_id, track_id) and device_id is often only
    the phone model, so two phones of the same model with the same folder name (a study naming its
    sessions "plot1" on every phone, or the default "session") would have their tracks merged.
    The token is drawn at random per session (4 base-36 characters, session_recorder.dart).
    """
    token = start.get("file_token")
    return f"{folder_name}_{token}" if isinstance(token, str) and token else folder_name


def read_session(folder: Path, device_id: str | None = None) -> Session:
    """[device_id] names the device of a session that carries no name of its own (--device-id)."""
    folder = Path(folder).resolve()  # "." would otherwise give an empty session name
    log = folder / SESSION_LOG
    if not log.is_file():
        raise SessionError("not a FaunaPulse session folder (no session.jsonl)")
    start = read_start(log) or {}
    afterwards = (folder / POST_TRACKS).is_file() and not live_tracker_ran(start.get("config"))

    b = _Builder()
    b.feed(log, tracks=not afterwards, other=True)
    if afterwards:
        b.feed(folder / POST_TRACKS, tracks=True, other=False)

    photos_dir = folder / PHOTOS_DIR
    photos: list[Photo] = []
    skipped = b.skipped
    for name in b.order:
        acc = b.photos[name]
        if acc.is_reference or not acc.boxes:
            continue
        # planFromIndex: the in-sync `_live` companion of a high-res photo when it exists,
        # because the logged boxes were observed on that frame.
        use_live = acc.live_name is not None and (photos_dir / acc.live_name).is_file()
        source = acc.live_name if use_live else name
        if not (photos_dir / source).is_file():
            skipped["photo_file_missing"] += 1
            continue
        seen: set[int] = set()
        boxes = []
        for box in acc.boxes:
            if box.track_id in seen:  # one row per (photo, track ID): insect-detect-post's key
                skipped["second_box_same_track_id"] += 1
                continue
            seen.add(box.track_id)
            if box.confidence is None:  # planFromIndex: box, else the track's, else 1.0
                box.confidence = acc.track_conf.get(box.track_id, 1.0)
            boxes.append(box)
        photos.append(Photo(name, source, "live" if use_live else "trigger", acc.capture_ms, boxes))

    if not photos:
        if (folder / POST_DETECTIONS).is_file():
            raise SessionError("its photos have boxes but no track IDs yet: in the app, run "
                               "Find track IDs in the photos first, then export again")
        raise SessionError("no saved photo with a track ID")
    device, device_source = device_id_of(start, device_id)
    return Session(
        folder=folder,
        session_id=export_session_id(folder.name, start),
        device_id=device,
        device_id_source=device_source,
        start=start,
        track_source="afterwards" if afterwards else "live",
        post_track_start=b.post_track_start,
        photos=photos,
        skipped=skipped,
    )


def find_sessions(paths: list[Path]) -> list[Path]:
    """Session folders among `paths`: each path is a session folder or a folder of them."""
    out: list[Path] = []
    for p in (Path(x).resolve() for x in paths):
        found = [p] if (p / SESSION_LOG).is_file() else (
            sorted(d for d in p.iterdir() if (d / SESSION_LOG).is_file()) if p.is_dir() else [])
        out += [d for d in found if d not in out]  # a session named twice is exported once
    return out
