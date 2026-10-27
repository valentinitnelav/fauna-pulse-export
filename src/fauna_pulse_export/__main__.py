"""Command line: `fauna-pulse-export insect-detect ...` and `fauna-pulse-export compare ...`."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .compare import CompareError, compare, read_faunapulse, read_post, summary_text, write_csv
from .insect_detect import SETTING_FIELDS, Export, Options, write_session
from .session_reader import SessionError, find_sessions, read_session


def _insect_detect(args) -> int:
    sessions = find_sessions(args.sessions)
    if not sessions:
        print("No FaunaPulse session folder found (a session folder holds session.jsonl).")
        return 1
    out = Path(args.out)
    export = Export(out)
    opts = Options(copy=args.copy, setting=args.setting, location=not args.no_location,
                   overwrite=args.overwrite)
    report = []
    for folder in sessions:
        try:
            entry = write_session(read_session(folder, args.device_id), export, opts)
        except SessionError as e:
            entry = {"session": folder.name, "refused": str(e)}
        report.append(entry)
        if "refused" in entry:
            print(f"{entry['session']}: not exported: {entry['refused']}")
            continue
        skipped = ", ".join(f"{k} {v}" for k, v in entry["skipped"].items() if v)
        print(f"{entry['session']}: {entry['photos']} photos, {entry['rows']} rows, "
              f"{entry['track_ids']} track IDs ({entry['track_source']}), "
              f"device '{entry['device_id']}' ({entry['device_id_source']})"
              + (f"; left out: {skipped}" if skipped else ""))
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    with open(out / f"export_report_{stamp}.json", "w", encoding="utf-8") as f:
        json.dump({"fauna_pulse_export": __version__, "sessions": report}, f, indent=2,
                  ensure_ascii=False)
    done = sum("refused" not in e for e in report)
    print(f"{done} of {len(report)} sessions exported to {out}")
    return 0 if done else 1


def _compare(args) -> int:
    try:
        fp, notes = read_faunapulse(find_sessions(args.faunapulse), args.pack, args.device_id)
        rows, summary = compare(fp, read_post(Path(args.post)))
        write_csv(rows, Path(args.out))
    except CompareError as e:
        print(f"Cannot compare: {e}")
        return 1
    print(summary_text(summary, notes))
    print(f"One row per track ID: {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="fauna-pulse-export", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("insect-detect", help="write sessions in the Insect Detect camera layout, "
                       "for insect-detect-post")
    a.add_argument("sessions", nargs="+", help="session folders, or folders that hold them")
    a.add_argument("--out", required=True, help="output folder (select it in insect-detect-post)")
    a.add_argument("--copy", action="store_true",
                   help="copy the photos (default: hard links where the disk allows them, "
                   "which take no extra space)")
    a.add_argument("--setting", choices=[*SETTING_FIELDS, "none"], default="plant",
                   help="field note used as the session's 'setting' in insect-detect-post "
                   "(default: plant)")
    a.add_argument("--no-location", action="store_true",
                   help="leave the session's position out of the config file")
    a.add_argument("--overwrite", action="store_true",
                   help="replace sessions that were exported to this folder before")
    a.add_argument("--device-id", metavar="NAME",
                   help="device name for sessions that carry none (imported videos; default: "
                   "'unknown camera'). A 'Device ID' field in the session's field notes, "
                   "FaunaLapse's phone ID and the phone model come first")
    a.set_defaults(func=_insect_detect)

    c = sub.add_parser("compare", help="FaunaPulse's and insect-detect-post's names per track ID")
    c.add_argument("--faunapulse", nargs="+", required=True,
                   help="the original session folders (with identification/), or folders of them")
    c.add_argument("--post", required=True,
                   help="insect-detect-post run folder (data_processed/<run>) or its _final.csv")
    c.add_argument("--pack", help="name list of the FaunaPulse results, when a session has several")
    c.add_argument("--device-id", metavar="NAME",
                   help="the --device-id given to insect-detect, if any")
    c.add_argument("--out", default="comparison.csv", help="output CSV (default: comparison.csv)")
    c.set_defaults(func=_compare)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
