# Things to know before comparing

`fauna-pulse-export compare` (step 6 in the [README](../README.md)) puts FaunaPulse's names and
insect-detect-post's names side by side, per track ID. The two programs reach their names in
different ways, so read this before drawing conclusions from `comparison.csv`.

## How long a track ID lasts

insect-detect-post measures a track ID from its first to its last photo. FaunaPulse takes photos
of a track ID only during the *Photo duration* (default 10 s), so a track ID seen for longer looks
at most 10 s long there; `comparison.csv` shows both lengths. For sessions meant for comparison,
set *Photo duration* long (up to 24 h): storage grows with the time animals are present (about
640 to 820 MB per hour of animal presence at a 1 s *Photo step* on the phones tested). The Insect
Detect camera saves one photo per second for the whole track.

## Why the names can differ

- insect-detect-post cuts a square on the box's longer side without a margin; FaunaPulse adds a
  margin.
- The phone runs a smaller-precision copy of BioCLIP 2.
- FaunaPulse pools a track's crops with "Average Logit" (Dussert et al. 2025), insect-detect-post
  with the probability of the winning name weighted by its share of votes.
- The lists of possible names differ (FaunaPulse's name list vs insect-detect-post's GBIF region
  filter).
- The two may stop at different ranks.

The comparison counts agreement; it does not say which is right.

## Species names

Species names are compared as text, ignoring upper case and extra spaces; both programs write
genus and epithet (for example `Apis mellifera`).

## `pred` is not always at the same rank

insect-detect-post gives `pred` at the rank chosen in its settings (default species), FaunaPulse
at the rank of its name list, so the two probabilities can be for different things. Compare the
per-rank columns (`fp_<rank>`, `post_<rank>`, `agree_<rank>`).

## A track ID seen on one photo

It lasts 0 s in insect-detect-post (first to last photo), so its duration filter (off by default)
removes it.

## High-res photos

The boxes come from the detector frame that triggered the photo. When the fast photo saved with
each high-res photo exists, that one is exported (its content matches the box); otherwise the
high-res photo is used and a fast animal may have moved.
