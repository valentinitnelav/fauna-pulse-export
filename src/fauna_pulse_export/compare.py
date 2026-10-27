"""Put FaunaPulse's and insect-detect-post's answers per track ID side by side.

FaunaPulse's `identification/tracks_<pack>.csv` (one row per track ID, written on the phone by
"Identify organisms") and insect-detect-post's `metadata/*_classified_final.csv` (one row per
track ID, written on the computer from the exported photos) share the taxon columns
(`bioclip_<rank>`) and the key (`device_id`, `session_id`, `track_id`). The device name and the
session ID are the ones the export wrote (device name rule, folder name + token), worked out again
from the session folder: `tracks_<pack>.csv` of app versions up to 0.9.0-beta.1 holds the phone
model as device_id, a session without a device name has none (the export may name it with
--device-id), and every one keeps the name the folder had when Identify ran. The two answers are computed differently (see README), so this compares
them; it does not say which one is right.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .session_reader import SESSION_LOG, UNKNOWN_DEVICE, device_id_of, export_session_id, read_start

RANKS = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]


class CompareError(Exception):
    pass


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _key(device, session_id, track_id) -> tuple[str, str, int]:
    """insect-detect-post's track key. A session_id made only of digits comes back from post
    as a number ("007" becomes 7: polars reads the CSV column as integers), so compare it as one."""
    sid = str(session_id or "").strip()
    if re.fullmatch(r"[+-]?\d+(\.\d+)?", sid):
        sid = repr(float(sid))
    return (str(device or "").strip() or UNKNOWN_DEVICE, sid, track_id)


def _int(text) -> int | None:
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def read_faunapulse(session_dirs: list[Path], pack: str | None,
                    device_id: str | None = None) -> tuple[dict, list[str]]:
    """{track key: row} and notes about sessions without results. [device_id]: the --device-id
    given to the export, for sessions without a device name of their own."""
    out: dict[tuple[str, str, int], dict] = {}
    notes: list[str] = []
    for d in map(Path, session_dirs):
        files = sorted((d / "identification").glob("tracks_*.csv"))
        if pack:
            files = [f for f in files if f.stem == f"tracks_{pack}"]
        if not files:
            notes.append(f"{d.name}: no identification results"
                         + (f" for pack {pack}" if pack else "") + " (run Identify in the app)")
            continue
        if len(files) > 1:
            names = ", ".join(f.stem.removeprefix("tracks_") for f in files)
            raise CompareError(f"{d.name} has results for several packs ({names}): choose one with --pack")
        # The device name and session ID the export wrote, from the folder as it is now: a session
        # renamed after Identify keeps its old name in the CSV's session_id.
        start = (read_start(d / SESSION_LOG) if (d / SESSION_LOG).is_file() else None) or {}
        session_id = export_session_id(d.name, start)
        device = device_id_of(start, device_id)[0]
        for row in _rows(files[0]):
            members = [_int(m) for m in (row.get("merged_track_ids") or "").split(";")]
            members = [m for m in members if m is not None] or [_int(row.get("track_id"))]
            for m in members:
                if m is None:  # a crop without a track ID (no-AI photo): nothing to compare
                    continue
                out[_key(device, session_id, m)] = dict(
                    row, _merged="1" if len(members) > 1 else "", _session_id=session_id)
    return out, notes


def read_post(run: Path) -> dict:
    """{track key: row} from a post run folder or one `_classified_final.csv`."""
    run = Path(run)
    if run.is_file():
        files = [run]
    else:
        files = [f for f in sorted((run / "metadata").glob("*_classified_final.csv"))]
    if not files:
        raise CompareError(f"no *_classified_final.csv in {run / 'metadata'}")
    out = {}
    for f in files:
        for row in _rows(f):
            tid = _int(row.get("track_id"))
            if tid is not None:
                out[_key(row.get("device_id"), row.get("session_id"), tid)] = row
    return out


def _norm(v) -> str:
    return " ".join(str(v or "").split()).lower()


def compare(fp: dict, post: dict) -> tuple[list[dict], dict]:
    ranks = [r for r in RANKS
             if any(f"bioclip_{r}" in row for row in fp.values())
             and any(f"bioclip_{r}" in row for row in post.values())]
    rows = []
    per_rank = {r: [0, 0] for r in ranks}  # compared, agreeing
    for key in sorted(set(fp) | set(post)):
        a, b = fp.get(key), post.get(key)
        row = {
            "device_id": key[0],
            "session_id": (a or {}).get("_session_id") or (b or {}).get("session_id", ""),
            "track_id": key[2],
            "in_faunapulse": int(a is not None),
            "in_post": int(b is not None),
            "fp_merged": (a or {}).get("_merged", ""),
            "fp_identified_rank": (a or {}).get("identified_rank", ""),
            "fp_headline": (a or {}).get("headline", ""),
            "fp_pred": (a or {}).get("pred", ""),
            "fp_pred_prob_weighted": (a or {}).get("pred_prob_weighted", ""),
            "post_pred": (b or {}).get("pred", ""),
            "post_pred_prob_weighted": (b or {}).get("pred_prob_weighted", ""),
            "fp_track_imgs": (a or {}).get("track_imgs", ""),
            "post_track_imgs": (b or {}).get("track_imgs", ""),
            "fp_duration_s": (a or {}).get("duration_s", ""),
            "post_duration_s": (b or {}).get("duration_s", ""),
        }
        for r in ranks:
            x = (a or {}).get(f"bioclip_{r}", "")
            y = (b or {}).get(f"bioclip_{r}", "")
            row[f"fp_{r}"], row[f"post_{r}"] = x, y
            if _norm(x) and _norm(y):
                same = _norm(x) == _norm(y)
                row[f"agree_{r}"] = int(same)
                per_rank[r][0] += 1
                per_rank[r][1] += same
            else:
                row[f"agree_{r}"] = ""
        rows.append(row)
    summary = {
        "track_ids_in_both": sum(1 for r in rows if r["in_faunapulse"] and r["in_post"]),
        "only_in_faunapulse": sum(1 for r in rows if r["in_faunapulse"] and not r["in_post"]),
        "only_in_post": sum(1 for r in rows if r["in_post"] and not r["in_faunapulse"]),
        "agreement": {r: {"compared": n, "agree": k, "share": round(k / n, 3) if n else None}
                      for r, (n, k) in per_rank.items()},
    }
    return rows, summary


def summary_text(summary: dict, notes: list[str]) -> str:
    lines = [
        f"Track IDs in both: {summary['track_ids_in_both']}",
        f"Only in FaunaPulse: {summary['only_in_faunapulse']}"
        " (no photo exported, or removed by a filter in insect-detect-post)",
        f"Only in insect-detect-post: {summary['only_in_post']}"
        " (session not identified on the phone, or another pack)",
    ]
    lines.append("Same taxon, per rank (track IDs where both give one):")
    for r, a in summary["agreement"].items():
        share = "" if a["share"] is None else f" ({a['share']:.0%})"
        lines.append(f"  {r:8s} {a['agree']} of {a['compared']}{share}")
    lines += [f"Note: {n}" for n in notes]
    return "\n".join(lines)


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        raise CompareError("no track IDs to compare")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
