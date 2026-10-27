"""Tests on small made-up sessions whose records follow the app's DATA_GUIDE.md.

Run: python -m unittest discover -s tests   (from the repository folder; nothing to install)
"""

import csv
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fauna_pulse_export.compare import compare, read_faunapulse, read_post  # noqa: E402
from fauna_pulse_export.insect_detect import Export, Options, clean_name_part, write_session  # noqa: E402
from fauna_pulse_export.session_reader import SessionError, read_session  # noqa: E402

TZ = timezone(timedelta(hours=2))
START = datetime(2026, 7, 14, 15, 30, 0, tzinfo=TZ)


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def photo_name(dt: datetime, token="k7x2", with_ms=True) -> str:
    stamp = f"{dt:%Y-%m-%d_%H%M%S}"
    return f"roi_{token}_{stamp}_{dt.microsecond // 1000:03d}.jpg" if with_ms else f"roi_{token}_{stamp}.jpg"


def start_record(**config):
    return {"type": "start_of_session", "time_ms": ms(START), "session_id": str(ms(START)),
            "time_iso": START.isoformat(timespec="milliseconds"), "file_token": "k7x2",
            "device": {"model": "Redmi Note 9S"}, "app_version": "0.9.0",
            "field": {"plant": "Daucus carota", "site": "meadow", "location": None},
            "location": {"lat": 51.3, "lon": 12.4, "accuracy_m": 8},
            "config": {"captureTrigger": "detector", "stepSeconds": 1, "durationSeconds": 10, **config}}


def track(tid, box=(0.1, 0.2, 0.3, 0.4), jpeg=None, conf=0.8, **extra):
    e = {"track_id": tid, "class_name": "insect", "confidence": conf,
         "box_in_roi": dict(zip(("left", "top", "right", "bottom"), box)), **extra}
    if jpeg:
        e["jpeg"] = jpeg
    return e


def frame(t: datetime, *tracks):
    return {"type": "detections", "time_ms": ms(t), "frame_ms": ms(t), "tracks": list(tracks)}


def make_session(root: Path, name: str, log: list, photos: list, post_tracks: list | None = None,
                 extra_files: dict | None = None) -> Path:
    d = root / name
    (d / "roi_frames").mkdir(parents=True)
    (d / "session.jsonl").write_text("".join(json.dumps(r) + "\n" for r in log))
    if post_tracks is not None:
        (d / "post_tracks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in post_tracks))
    for p in photos:
        (d / "roi_frames" / p).write_bytes(b"\xff\xd8 not a real photo")
    for rel, text in (extra_files or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    return d


def post_crop_key(photo_filename: str, track_id: int) -> tuple[str, int]:
    """How insect-detect-post v1.1.0 matches a crop back to its CSV row: the crop is named
    `<photo stem>_ID<track>_crop.jpg` (image_processor.py) and parsed by parse_crop_stem
    (dataset_harmonizer.py) + parse_crop_name (classifier_utils.py). Reduced to the current
    name format; the real code is checked separately against post itself."""
    stem = f"{Path(photo_filename).stem}_ID{track_id}_crop"
    i = stem.find("_ID")
    ts_part, tid = stem[:i], int(re.match(r"\d+", stem[i + 3:]).group())
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})-(\d{6})", ts_part)
    return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}.{m.group(5)}", tid


class LiveSessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        t1 = START + timedelta(seconds=45, milliseconds=123)
        t2 = t1 + timedelta(seconds=1)
        t3 = t2 + timedelta(seconds=1)
        self.p1, self.p2, self.p3 = photo_name(t1), photo_name(t2), photo_name(t3)
        self.live2 = self.p2.replace(".jpg", "_live.jpg")
        ref = photo_name(t3 + timedelta(seconds=5)).replace("roi_", "ref_")
        log = [
            start_record(),
            frame(t1 - timedelta(milliseconds=70), track(1)),  # no photo on this frame
            # Track 1 was due a photo; track 2 is on the same photo (shared frame photo).
            frame(t1, track(1, jpeg=self.p1), track(2, box=(0.5, 0.5, 0.7, 0.8), conf=0.6)),
            {"type": "capture", "file": self.p1, "captured_at_ms": ms(t1), "time_ms": ms(t1) + 90},
            # High-res photo with its in-sync companion on disk: the companion is used.
            frame(t2, track(1, jpeg=self.p2)),
            {"type": "capture", "file": self.p2, "captured_at_ms": ms(t2), "live_jpeg": self.live2},
            # A predicted box and a second box of the same track ID on one photo.
            frame(t3, track(1, jpeg=self.p3), track(3, coasted=True), track(1, box=(0, 0, 0.1, 0.1))),
            {"type": "gt_capture", "jpeg": ref, "captured_at_ms": ms(t3) + 5000},
            '{"type": "detections", "tracks": [',  # line cut by a crash
        ]
        d = self.root / "2026-07-14_153000 meadow"
        (d / "roi_frames").mkdir(parents=True)
        (d / "session.jsonl").write_text("".join((json.dumps(r) if isinstance(r, dict) else r) + "\n" for r in log))
        for p in (self.p1, self.p2, self.live2, self.p3, ref):
            (d / "roi_frames" / p).write_bytes(b"x")
        self.folder = d

    def tearDown(self):
        self.tmp.cleanup()

    def test_reader_follows_the_planner(self):
        s = read_session(self.folder)
        self.assertEqual(s.track_source, "live")
        self.assertEqual(s.device_id, "Redmi Note 9S")
        self.assertEqual(s.session_id, "2026-07-14_153000 meadow_k7x2")
        self.assertEqual([p.name for p in s.photos], [self.p1, self.p2, self.p3])
        self.assertEqual([b.track_id for b in s.photos[0].boxes], [1, 2])
        self.assertEqual((s.photos[1].source, s.photos[1].box_source), (self.live2, "live"))
        self.assertEqual((s.photos[0].source, s.photos[0].box_source), (self.p1, "trigger"))
        self.assertEqual([b.track_id for b in s.photos[2].boxes], [1])
        self.assertEqual(s.skipped["predicted_box"], 1)
        self.assertEqual(s.skipped["second_box_same_track_id"], 1)
        self.assertEqual(s.local_time(s.photos[0]), datetime(2026, 7, 14, 15, 30, 45, 123000))

    def test_written_rows_match_post_rules(self):
        out = self.root / "out"
        entry = write_session(read_session(self.folder), Export(out), Options())
        self.assertEqual((entry["photos"], entry["rows"], entry["track_ids"]), (3, 4, 2))
        folder = Path(entry["folder"])
        self.assertEqual(folder, out / "Redmi-Note-9S" / "data" / "2026-07-14" / "2026-07-14_153000 meadow_k7x2")
        with open(folder / "2026-07-14_153000 meadow_k7x2_metadata.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(list(rows[0])[:15], [
            "device_id", "session_id", "timestamp", "label", "confidence", "track_id", "track_status",
            "x_min", "y_min", "x_max", "y_max", "lens_position", "iso_sensitivity", "exposure_time",
            "filename"])
        self.assertEqual(rows[0]["filename"], "Redmi-Note-9S_k7x2_2026-07-14_15-30-45-123000.jpg")
        self.assertEqual(rows[0]["timestamp"], "2026-07-14T15:30:45.123000")
        for r in rows:
            self.assertTrue((folder / r["filename"]).is_file())
            self.assertNotRegex(r["filename"].lower(), "crop|overlay|timelapse")
            self.assertEqual(post_crop_key(r["filename"], int(r["track_id"])), (r["timestamp"], int(r["track_id"])))
        self.assertEqual(rows[1]["x_min"], "0.5")
        config = json.loads((folder / "2026-07-14_153000 meadow_k7x2_config.json").read_text())
        self.assertEqual(config["deployment"]["setting"], "Daucus carota")
        self.assertEqual(config["deployment"]["location"]["latitude"], 51.3)
        self.assertEqual(len(list(folder.glob("*config*.json"))), 1)

    def test_no_location_and_overwrite(self):
        out = self.root / "out"
        export = Export(out)
        write_session(read_session(self.folder), export, Options(location=False))
        again = write_session(read_session(self.folder), Export(out), Options())
        self.assertIn("refused", again)
        entry = write_session(read_session(self.folder), Export(out), Options(overwrite=True, location=False))
        self.assertEqual(entry["timestamps_moved_by_microseconds"], 0)
        config = json.loads(next(Path(entry["folder"]).glob("*_config.json")).read_text())
        self.assertIsNone(config["deployment"]["location"])


class TrackSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_video_session_reads_post_tracks_only(self):
        t = START + timedelta(seconds=3)
        kept = photo_name(t)
        start = start_record()
        del start["config"]  # imported-video sessions have no camera config: no live tracker
        log = [start, frame(t, track(9, jpeg=kept))]  # must be ignored
        post = [{"type": "post_track_start", "run_id": 4, "keep_frames": {"step_seconds": 0.5, "duration_seconds": 30},
                 "detection_settings": {"model": "/data/user/0/app/files/models/det_256.tflite"}},
                frame(t, track(1, jpeg=kept)),
                {"type": "capture", "file": kept, "captured_at_ms": ms(t), "source": "video", "clip": "a.mp4", "pts_us": 3000000}]
        d = make_session(self.root, "video", log, [kept], post)
        s = read_session(d)
        self.assertEqual(s.track_source, "afterwards")
        self.assertEqual([b.track_id for b in s.photos[0].boxes], [1])
        entry = write_session(s, Export(self.root / "out"), Options())
        config = json.loads(next(Path(entry["folder"]).glob("*_config.json")).read_text())
        self.assertEqual(config["faunapulse"]["photo_step_s"], 0.5)
        self.assertEqual(config["faunapulse"]["detector_model"], "det_256.tflite")

    def test_live_session_ignores_post_tracks(self):
        t = START + timedelta(seconds=3)
        p = photo_name(t)
        d = make_session(self.root, "live", [start_record(), frame(t, track(5, jpeg=p))], [p],
                         [frame(t, track(1, jpeg=p))])
        self.assertEqual([b.track_id for b in read_session(d).photos[0].boxes], [5])

    def test_faunalapse_import_with_photo_track_ids(self):
        t = START + timedelta(seconds=10, milliseconds=640)
        p = photo_name(t, token="ab12", with_ms=False)  # imports name whole seconds
        start = start_record(captureTrigger="timelapse")
        log = [start, {"type": "timelapse_capture", "jpeg": p, "captured_at_ms": ms(t)},
               {"type": "capture", "file": p, "path": "still", "saved_px": 1280, "time_ms": ms(t)}]
        post = [{"type": "post_track_start", "source": "photos"}, frame(t, track(1, jpeg=p))]
        d = make_session(self.root, "lapse", log, [p], post)
        s = read_session(d)
        self.assertEqual(s.track_source, "afterwards")
        # No milliseconds in the name: captured_at_ms in the session's time zone.
        self.assertEqual(s.local_time(s.photos[0]), datetime(2026, 7, 14, 15, 30, 10, 640000))

    def test_boxes_without_track_ids_are_refused(self):
        t = START + timedelta(seconds=1)
        p = photo_name(t)
        d = make_session(self.root, "untracked", [start_record(captureTrigger="timelapse"),
                         {"type": "timelapse_capture", "jpeg": p, "captured_at_ms": ms(t)}], [p],
                         extra_files={"post_detections.jsonl": json.dumps(
                             {"type": "post_detection", "jpeg": p, "boxes": [{"box": [0, 0, 0.5, 0.5], "conf": 0.9}]}) + "\n"})
        with self.assertRaisesRegex(SessionError, "Find track IDs"):
            read_session(d)


class NamesAndTimesTest(unittest.TestCase):
    def test_reserved_words_removed(self):
        self.assertEqual(clean_name_part("Crop Master 5", "phone"), "Master-5")
        self.assertEqual(clean_name_part("crcropop", "phone"), "phone")
        self.assertEqual(clean_name_part("", "phone"), "phone")

    def test_same_moment_on_two_phones_gets_distinct_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            t = START + timedelta(seconds=2)
            p = photo_name(t)
            a = make_session(root, "a", [start_record(), frame(t, track(1, jpeg=p))], [p])
            other = start_record()
            other["device"] = {"model": "Pixel 7"}
            other["file_token"] = "q9w8"  # same start moment, another recording
            b = make_session(root, "b", [other, frame(t, track(1, jpeg=p))], [p])
            export = Export(root / "out")
            write_session(read_session(a), export, Options())
            entry = write_session(read_session(b), export, Options())
            self.assertEqual(entry["timestamps_moved_by_microseconds"], 1)
            # A later run into the same folder sees the photos already there.
            later = Export(root / "out")
            self.assertEqual(len(later.used), 2)


class CompareTest(unittest.TestCase):
    def test_join_and_agreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            s = make_session(root, "sess", [start_record()], [])
            (s / "identification").mkdir(parents=True)
            fp_rows = [
                {"device_id": "Redmi Note 9S", "session_id": "old name", "track_id": "1", "pred": "Apidae",
                 "bioclip_family": "Apidae", "bioclip_species": "Apis mellifera", "merged_track_ids": "1"},
                {"device_id": "Redmi Note 9S", "session_id": "old name", "track_id": "2", "pred": "Syrphidae",
                 "bioclip_family": "Syrphidae", "bioclip_species": "", "merged_track_ids": "2;3"},
            ]
            with open(s / "identification" / "tracks_europe.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(fp_rows[0]))
                w.writeheader()
                w.writerows(fp_rows)
            run = root / "run" / "metadata"
            run.mkdir(parents=True)
            post_rows = [
                {"device_id": "Redmi Note 9S", "session_id": "sess_k7x2", "track_id": "1", "pred": "Apis mellifera",
                 "bioclip_family": "apidae", "bioclip_species": "Apis  mellifera"},
                {"device_id": "Redmi Note 9S", "session_id": "sess_k7x2", "track_id": "3", "pred": "Eristalis tenax",
                 "bioclip_family": "Syrphidae", "bioclip_species": "Eristalis tenax"},
                {"device_id": "Redmi Note 9S", "session_id": "sess_k7x2", "track_id": "7", "pred": "x",
                 "bioclip_family": "Muscidae", "bioclip_species": "y"},
            ]
            with open(run / "x_metadata_merged_classified_final.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(post_rows[0]))
                w.writeheader()
                w.writerows(post_rows)
            fp, notes = read_faunapulse([s], None)
            rows, summary = compare(fp, read_post(root / "run"))
            self.assertEqual(summary["track_ids_in_both"], 2)
            self.assertEqual(summary["only_in_faunapulse"], 1)  # merged member 2
            self.assertEqual(summary["only_in_post"], 1)
            self.assertEqual(summary["agreement"]["family"], {"compared": 2, "agree": 2, "share": 1.0})
            self.assertEqual(summary["agreement"]["species"], {"compared": 1, "agree": 1, "share": 1.0})


class ReviewFindingsTest(unittest.TestCase):
    """Cases found by the review of version 0.1.0 before its first use."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.t = START + timedelta(seconds=2)
        self.p = photo_name(self.t)

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, name, start=None, tracks=None):
        start = start or start_record()
        return make_session(self.root, name, [start, frame(self.t, *(tracks or [track(1, jpeg=self.p)]))], [self.p])

    def test_dot_path_keeps_the_folder_name(self):
        d = self.session("plot1")
        cwd = Path.cwd()
        try:
            import os
            os.chdir(d)
            s = read_session(Path("."))
        finally:
            os.chdir(cwd)
        self.assertEqual(s.session_id, "plot1_k7x2")

    def test_missing_phone_model_gets_a_name(self):
        start = start_record()
        del start["device"]
        s = read_session(self.session("nomodel", start))
        self.assertEqual(s.device_id, "unknown camera")

    def test_same_folder_name_on_two_phones_of_one_model(self):
        a = self.session("plot1")
        other = start_record()
        other["file_token"] = "q9w8"
        b = make_session(self.root / "phone2", "plot1", [other, frame(self.t, track(1, jpeg=self.p))], [self.p])
        export = Export(self.root / "out")
        first = write_session(read_session(a), export, Options())
        second = write_session(read_session(b), export, Options())
        self.assertNotIn("refused", second)
        self.assertNotEqual(first["folder"], second["folder"])

    def test_renamed_session_replaces_its_earlier_export(self):
        d = self.session("plot1")
        out = self.root / "out"
        old = write_session(read_session(d), Export(out), Options())
        renamed = d.with_name("plot1 daucus")
        d.rename(renamed)
        refused = write_session(read_session(renamed), Export(out), Options())
        self.assertIn("already exported", refused["refused"])
        new = write_session(read_session(renamed), Export(out), Options(overwrite=True))
        self.assertFalse(Path(old["folder"]).exists())
        self.assertTrue(Path(new["folder"]).exists())

    def test_earlier_export_under_another_device_name_is_found(self):
        out = self.root / "out"
        old = Path(write_session(read_session(self.session("plot1")), Export(out), Options())["folder"])
        moved = out / "unknown-phone" / old.relative_to(out).parts[1] / old.parent.name / old.name
        moved.parent.mkdir(parents=True)
        old.rename(moved)  # as written by a version that named the device differently
        refused = write_session(read_session(self.root / "plot1"), Export(out), Options())
        self.assertIn("already exported", refused["refused"])
        write_session(read_session(self.root / "plot1"), Export(out), Options(overwrite=True))
        self.assertFalse(moved.exists())

    def test_overwrite_never_deletes_a_foreign_folder(self):
        from fauna_pulse_export.insect_detect import _remove_export
        out = self.root / "out"
        stranger = out / "Redmi-Note-9S" / "data" / "2026-07-14" / "plot1_k7x2"
        stranger.mkdir(parents=True)
        (stranger / "notes.txt").write_text("not an export")
        with self.assertRaises(SessionError):
            _remove_export(stranger, out)
        with self.assertRaises(SessionError):
            _remove_export(stranger.parent, out)
        self.assertTrue((stranger / "notes.txt").exists())

    def test_empty_own_photo_name_is_not_replaced(self):
        # Dart `own ?? frameJpeg`: an entry with "jpeg": "" gets no photo, not the frame's.
        q = photo_name(self.t + timedelta(seconds=1))
        empty = track(2)
        empty["jpeg"] = ""
        d = make_session(self.root, "empty_name", [start_record(), frame(self.t, track(1, jpeg=q), empty)], [q])
        self.assertEqual([b.track_id for b in read_session(d).photos[0].boxes], [1])

    def test_missing_confidence_is_one_like_the_app(self):
        entry = track(1, jpeg=self.p)
        del entry["confidence"]
        s = read_session(self.session("noconf", tracks=[entry]))
        self.assertEqual(s.photos[0].boxes[0].confidence, 1.0)

    def test_session_named_twice_is_found_once(self):
        from fauna_pulse_export.session_reader import find_sessions
        d = self.session("plot1")
        self.assertEqual(find_sessions([self.root, d]), [d.resolve()])

    def test_numeric_session_id_from_post_still_joins(self):
        from fauna_pulse_export.compare import _key
        self.assertEqual(_key("Redmi Note 9S", "007", 1), _key("Redmi Note 9S", "7", 1))
        self.assertEqual(_key("", "a", 1)[0], "unknown camera")


if __name__ == "__main__":
    unittest.main()
