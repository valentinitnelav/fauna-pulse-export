# fauna-pulse-export

Command-line tools that turn sessions recorded with the Android app
[FaunaPulse](https://github.com/valentinitnelav/fauna-pulse) into formats that other software reads.

The first format is the one written by the [Insect Detect](https://github.com/maxsitt/insect-detect)
camera trap, so that [insect-detect-post](https://github.com/maxsitt/insect-detect-post)
(Sittinger 2026) can process FaunaPulse sessions: cut the crops, name the animals with BioCLIP 2 or
a YOLO classifier, sum up each track ID, and check the names by hand in its validation window. A
second command puts FaunaPulse's own names (from *Identify organisms* on the phone) and
insect-detect-post's names side by side, per track ID.

Status: version 0.1.0. Tested on small made-up sessions (`tests/`) and on three real sessions
(videos imported into FaunaPulse: a bee, two deer, several bees on flowers) through the whole
insect-detect-post v1.1.0 pipeline with BioCLIP 2: every exported row was matched to its photo,
the boxes drawn by insect-detect-post sit on the animals, and `compare` joined every track ID.
Not yet tried with live sessions or FaunaLapse imports on real data.

## What you need

Python 3.10 or newer; no other packages. Install from this folder:

```bash
python -m pip install .
```

or, without installing, run it from the `src` folder: `cd src` and use `python -m fauna_pulse_export`
wherever `fauna-pulse-export` is written below.

## From FaunaPulse to insect-detect-post

1. *Optional, needed for the comparison:* in FaunaPulse, run **Identify organisms** on the sessions.
2. *Recommended when several phones record:* give each phone a name, as the Insect Detect camera
   has its hostname. Open the field notes (FaunaPulse: on the camera screen, the pin with a
   pencil; FaunaLapse: card 2, *Field metadata*), tap **Add a field**, call it `Device ID` and type the
   name, for example `cam-03`. Both apps keep the field and its value for the next sessions. Without it, insect-detect-post sees only the phone model, so phones of the same
   model look like one device in its results.
3. Copy the session folders to the computer: connect the phone by USB and copy them from
   `Android/data/com.faunapulse.app/files/sessions/` (see the app's
   [FIELD_GUIDE.md](https://github.com/valentinitnelav/fauna-pulse/blob/main/docs/FIELD_GUIDE.md)).
   Keep the originals: the export never changes them.
4. Export:

   ```bash
   fauna-pulse-export insect-detect path/to/sessions --out path/to/for_insect_detect
   ```

   You can name single session folders or folders that hold them. Each session gets one line on
   screen (photos, rows, track IDs, anything left out and why), and `export_report_<time>.json`
   in the output folder keeps the same.
5. In insect-detect-post, select `path/to/for_insect_detect` as the source directory and run the
   pipeline as for camera data. Its BioCLIP filter keeps only insects and arachnids by default:
   for mammals, birds or other animals, turn that filter off (`filter_arthropods`), or BioCLIP
   can only answer with an insect or arachnid name.
6. *Optional:* compare the names, per track ID:

   ```bash
   fauna-pulse-export compare --faunapulse path/to/sessions \
       --post path/to/output/data_processed/<run folder> --out comparison.csv
   ```

   It prints how many track IDs both have and how often the two agree at each rank (kingdom to
   species), and writes one row per track ID to `comparison.csv`. If the export was given
   `--device-id`, give `compare` the same one.

Options of `insect-detect`:

| Option | What it does |
|---|---|
| `--copy` | Copy the photos. By default they are hard links where the disk allows it: the same photo under a second name, taking no extra space (insect-detect-post only reads them). On disks without hard links (many USB drives) the photos are copied anyway. |
| `--setting plant\|site\|habitat\|none` | Which field note becomes the session's *setting* in insect-detect-post (default `plant`). insect-detect-post can select tracks by setting during validation. |
| `--no-location` | Leave the session's position out of the config file, for example before sharing the folder. |
| `--overwrite` | Replace sessions that were exported to the same folder before. Without it they are refused. |
| `--device-id NAME` | Device name for sessions that carry none, such as imported videos (the phone did not film them), for example the camera that did. Without it they are `unknown camera`. |

## Other kinds of FaunaPulse sessions

- **Videos imported into FaunaPulse:** run *Find animals in videos*, then *Find track IDs* (which
  keeps frames in `roi_frames/`), then export as above.
- **FaunaLapse photo sessions** (the sister app takes time-lapse photos without AI):
  insect-detect-post needs boxes and track IDs, which time-lapse photos do not have. Pack the
  session in FaunaLapse, import it in FaunaPulse (Sessions, menu, *Import a FaunaLapse session*),
  run *Find animals in photos* and then *Find track IDs* in the photos, then export as above.
  A session with boxes but no track IDs is refused with a message saying so.
- **Time-lapse or motion sessions recorded in FaunaPulse:** the same as FaunaLapse sessions,
  without the import.

## What the export writes

The folder layout and the metadata columns of the Insect Detect camera (insect-detect v2.0.0):

```text
<out>/
├── export_report_<time>.json
└── <device>/data/<YYYY-MM-DD>/<session ID>/
    ├── <session ID>_metadata.csv      # one row per photo and track ID
    ├── <session ID>_config.json       # deployment block (start, location, setting, notes) + FaunaPulse settings
    └── <device>_<token>_<YYYY-MM-DD_HH-MM-SS-ffffff>.jpg   # the photos, renamed
```

| Column | From FaunaPulse |
|---|---|
| `device_id` | the first of: a field of your own named `Device ID` in the session's field notes (case, spaces, `_` and `-` do not matter); FaunaLapse's phone ID (8 characters, for FaunaLapse imports); the phone model (`device.model`, as in `tracks_<pack>.csv`); `--device-id`; `unknown camera` (insect-detect-post drops rows without a device). Characters that file names cannot hold (`/ \ : * ? " < > \|`) become `-`, because insect-detect-post puts the name in folder names. The config's `device_id_source` says which one was used. |
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

A session exported before (also under another folder name, after a rename or as a copied folder)
is refused, because insect-detect-post would count its photos twice; `--overwrite` replaces the
earlier export. The export only ever deletes folders it wrote itself.

## Things to know before comparing

- **Visit length.** insect-detect-post measures a track ID from its first to its last photo.
  FaunaPulse takes photos of a track ID only during the *Photo duration* (default 10 s), so a long
  visit looks at most 10 s long there; `comparison.csv` shows both lengths. For sessions meant for
  comparison, set *Photo duration* long (up to 24 h): storage grows with the time animals are
  present (about 640 to 820 MB per hour of animal presence at a 1 s *Photo step* on the phones
  tested). The Insect Detect camera saves one photo per second for the whole track.
- **Why the names can differ:** insect-detect-post cuts a square on the box's longer side without
  a margin, FaunaPulse adds a margin; the phone runs a smaller-precision copy of BioCLIP 2;
  FaunaPulse pools a track's crops with "Average Logit" (Dussert et al. 2025), insect-detect-post
  with the probability of the winning name weighted by its share of votes; the lists of possible
  names differ (FaunaPulse's name list vs insect-detect-post's GBIF region filter); and the two
  may stop at different ranks. The comparison counts agreement; it does not say which is right.
- **Species names** are compared as text, ignoring upper case and extra spaces; both programs
  write genus and epithet (for example `Apis mellifera`).
- **`pred` is not always at the same rank.** insect-detect-post gives `pred` at the rank chosen in
  its settings (default species), FaunaPulse at the rank of its name list, so the two
  probabilities can be for different things. Compare the per-rank columns
  (`fp_<rank>`, `post_<rank>`, `agree_<rank>`).
- **A track ID seen on one photo** lasts 0 s in insect-detect-post (first to last photo), so its
  duration filter (off by default) removes it.
- **High-res photos:** the boxes come from the detector frame that triggered the photo. When the
  fast photo saved with each high-res photo exists, that one is exported (its content matches the
  box); otherwise the high-res photo is used and a fast animal may have moved.

## Credits

The target format is the one written by the Insect Detect camera trap and read by
insect-detect-post, both by Maximilian Sittinger:

- Sittinger, M. (2026). Software for post-processing of data captured with the Insect Detect
  camera trap. Zenodo. https://doi.org/10.5281/zenodo.21822140
- Sittinger, M., Uhler, J., Pink, M., Herz, A. (2024). Insect detect: An open-source DIY camera
  trap for automated insect monitoring. PLOS ONE 19(4): e0295474.
  https://doi.org/10.1371/journal.pone.0295474

No code of either project is copied here; this tool writes files in the layout the camera
produces. Questions about insect-detect-post itself belong to its repository.

## Licence

GNU Affero General Public License v3.0 (AGPL-3.0), the same as FaunaPulse and insect-detect-post.
