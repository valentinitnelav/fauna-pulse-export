# What the export writes

What `fauna-pulse-export insect-detect` writes, and why. How to run it is in the
[README](../README.md).

The export writes the folder layout and the metadata columns of the Insect Detect camera
(insect-detect v2.0.0).

## Folders and files

```text
<out>/
├── export_report_<time>.json
└── <device>/data/<YYYY-MM-DD>/<session ID>/
    ├── <session ID>_metadata.csv      # one row per photo and track ID
    ├── <session ID>_config.json       # deployment block (start, location, setting, notes) + FaunaPulse settings
    └── <device>_<token>_<YYYY-MM-DD_HH-MM-SS-ffffff>.jpg   # the photos, renamed
```

## Columns of the metadata file

| Column | From FaunaPulse |
|---|---|
| `device_id` | the device name (see [The device name](#the-device-name) below) |
| `session_id` | the session folder name plus `_` and the session's random 4-character token (for example `plot1_k7x2`), so that two phones with the same device name and folder name stay apart: insect-detect-post tells track IDs apart by device, session and track ID only |
| `timestamp` | the photo's moment, the phone's local time, six decimals; equal to the time in the file name |
| `label`, `confidence` | the detector's class and confidence for that box |
| `track_id` | FaunaPulse's track ID (live, or found afterwards in videos or photos) |
| `track_status` | always `TRACKED` |
| `x_min` … `y_max` | the box as fractions of the photo (`box_in_roi`) |
| `lens_position`, `iso_sensitivity`, `exposure_time` | empty (not logged per photo) |
| `filename` | the renamed photo |
| `fp_photo`, `fp_source_file` | the photo's name in FaunaPulse, and the file used (the in-sync fast photo of a high-res photo, when it was saved) |
| `fp_box_source`, `fp_track_source` | `trigger` or `live` (as in FaunaPulse's identification); `live` or `afterwards` |

## The device name

The Insect Detect camera names its data by its hostname. The export takes the first of these
that the session has:

1. the field notes' **Device ID** (`field.device_id`, FaunaPulse after 0.9.0-beta.1);
2. a filled field of your own named `Device ID` in the session's field notes (case, spaces, `_`
   and `-` do not matter);
3. FaunaLapse's phone ID (8 characters, for FaunaLapse imports);
4. the phone model (`device.model`);
5. `--device-id`;
6. `unknown camera` (insect-detect-post drops rows without a device).

The config's `device_id_source` says which one was used.

Steps 1 to 4 are the app's own rule: in FaunaPulse versions after 0.9.0-beta.1,
`tracks_<pack>.csv` writes the same `device_id` (and the phone model in `phone_model`). Both are
tested with the same cases (`tests/fixtures/device_name_cases.json`).

insect-detect-post puts the name in folder names, so the name is cleaned:

- In the `device_id` column, characters that file names cannot hold (`/ \ : * ? " < > |`)
  become `-`, and `-`, `.` and spaces at the ends are dropped.
- The `<device>` part of the folder and photo names is shorter still: letters, digits and single
  `-` (`11T - check` becomes `11T-check`), without the words `crop`, `overlay` and `timelapse`
  (see the next section).

## Rules of insect-detect-post the export takes care of

Which photo shows which track ID follows the rule FaunaPulse's *Identify organisms* uses, so both
programs see the same photos and boxes, except that every photo is exported (Identify keeps at most
10 per track ID). insect-detect-post itself relies on a few rules the export takes care of:

- It matches each crop back to its row by the time in the photo's file name, so the photos are
  renamed and two photos never share a time: when two photos (on two phones, for example) fall on
  the same millisecond, the later one is moved by one microsecond (counted in the report).
- A photo name containing `crop`, `overlay` or `timelapse` is read as something else, so device
  names are cleaned (letters, digits and `-` only, without those words).
- A row without a photo would still count as one of the track's pictures and lower its
  probability, so only rows with a photo are written.
- It allows one row per photo and track ID. If the log ever holds two boxes of one track ID on
  one photo, the first is kept (counted in the report); FaunaPulse's Identify would use both.

## Exporting a session again

A session exported before (also under another folder name, after a rename or as a copied folder)
is refused, because insect-detect-post would count its photos twice; `--overwrite` replaces the
earlier export. The export only ever deletes folders it wrote itself.
