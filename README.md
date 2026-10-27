# fauna-pulse-export

Command-line tools that turn sessions recorded with the Android app
[FaunaPulse](https://github.com/valentinitnelav/fauna-pulse) into formats that other software reads.

The first format is the one written by the [Insect Detect](https://github.com/maxsitt/insect-detect)
camera trap, so that [insect-detect-post](https://github.com/maxsitt/insect-detect-post)
(Sittinger 2026) can process FaunaPulse sessions: cut the crops, name the animals with BioCLIP 2 or
a YOLO classifier, sum up each track ID, and check the names by hand in its validation window. A
second command puts FaunaPulse's own names (from *Identify organisms* on the phone) and
insect-detect-post's names side by side, per track ID.

Status: version 0.1.0.

- Tested on small made-up sessions (`tests/`) and on three real sessions (videos imported into
  FaunaPulse: a bee, two deer, several bees on flowers) through the whole insect-detect-post
  v1.1.0 pipeline with BioCLIP 2. Every exported row was matched to its photo, the boxes drawn by
  insect-detect-post sit on the animals, and `compare` joined every track ID.
- Not yet tried with live sessions, or with FaunaLapse imports on real data.

More details:

- [docs/EXPORT_FORMAT.md](docs/EXPORT_FORMAT.md): the folders and columns the export writes, how
  the device name is chosen, and the rules of insect-detect-post the export takes care of.
- [docs/COMPARING.md](docs/COMPARING.md): what to know before comparing the names of the two
  programs.

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
   has its hostname. In FaunaPulse, open the field notes (on the camera screen, the pin with a
   pencil) and type the name in **Device ID**, for example `cam-03`. FaunaPulse 0.9.0-beta.1 and
   FaunaLapse have no such field yet: there, tap **Add a field** (FaunaLapse: card 2, *Field
   metadata*), call it `Device ID` and type the name. The apps keep the value for the next
   sessions. Without it, phones of the same model look like one device in insect-detect-post's
   results.
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
   `--device-id`, give `compare` the same one. Read [docs/COMPARING.md](docs/COMPARING.md) before
   drawing conclusions from it.

Options of `insect-detect`:

| Option | What it does |
|---|---|
| `--copy` | Copy the photos. By default they are hard links where the disk allows it: the same photo under a second name, taking no extra space (insect-detect-post only reads them). On disks without hard links (many USB drives) the photos are copied anyway. |
| `--setting plant\|site\|habitat\|none` | Which field note becomes the session's *setting* in insect-detect-post (default `plant`). insect-detect-post can select tracks by setting during validation. |
| `--no-location` | Leave the session's position out of the config file, for example before sharing the folder. |
| `--overwrite` | Replace sessions that were exported to the same folder before. Without it they are refused. |
| `--device-id NAME` | Device name for sessions that carry none, such as imported videos (the phone did not film them), for example the camera that did. Without it they are `unknown camera`. |

## Other kinds of FaunaPulse sessions

insect-detect-post needs boxes and track IDs. For the sessions below, add them in FaunaPulse
first, then export as above. A session with boxes but no track IDs is refused with a message
saying so.

- **Videos imported into FaunaPulse:** run *Find animals in videos*, then *Find track IDs* (which
  keeps frames in `roi_frames/`).
- **FaunaLapse photo sessions** (the sister app takes time-lapse photos without AI): pack the
  session in FaunaLapse, import it in FaunaPulse (Sessions, menu, *Import a FaunaLapse session*),
  run *Find animals in photos* and then *Find track IDs* in the photos.
- **Time-lapse or motion sessions recorded in FaunaPulse:** the same as FaunaLapse sessions,
  without the import.

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
