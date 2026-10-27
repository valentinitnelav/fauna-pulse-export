# AGENTS.md

Guidance for AI coding agents (Claude Code, codex, ...) working in this repository. CLAUDE.md
points to this file. It holds working rules; what the tools do and write is in `README.md`.

## What this repository is for

PC tools that turn FaunaPulse sessions into formats other software reads. Today: the Insect
Detect camera layout for insect-detect-post (`insect_detect.py`) and a per-track comparison of
both programs' names (`compare.py`). Later candidates: a Camtrap DP package for FaunaLapse and
FaunaPulse sessions (see FaunaLapse `docs/PARKED.md`). The repository is public: everything tracked
must be safe to publish.

Sibling repositories, read in place, never copied here:

- the app, [fauna-pulse](https://github.com/valentinitnelav/fauna-pulse) (usually
  `~/InsectDetectApp/fauna-pulse`). Its `docs/DATA_GUIDE.md` is the record dictionary.
  `session_reader.py` repeats the app's rules for "which photo shows which track ID with which
  box"; its docstring names each Dart function it follows. When the app changes one of them (or
  its records), change the reader in the same piece of work and add a test. Changes to the app are
  made in an app session, following its own `AGENTS.md`.
- [insect-detect](https://github.com/maxsitt/insect-detect) and
  [insect-detect-post](https://github.com/maxsitt/insect-detect-post) by Maximilian Sittinger
  (clones usually in `~/InsectDetectApp/other_repos/`). The target is the camera's output
  (insect-detect v2.0.0), which insect-detect-post keeps reading across versions; the rules
  insect-detect-post relies on are listed at the top of `insect_detect.py`. Before a release,
  check them against insect-detect-post's current code (it changes often).

## General rules

- Less is more: Python standard library only, small functions, no new option without a need.
- Plain English in messages, README and comments (the owner and many users are not native
  speakers); no idioms. Avoid the em dash; use parentheses. Say "track ID", never "visit", and
  name things for any organism, not only insects.
- Code comments explain why (the reason, what must stay in sync), not what.
- Report checks honestly: say what was run (unit tests, a real export, insect-detect-post run)
  and never claim a check that was not run.
- No private data in tracked files: no e-mail addresses, keys, personal details or whereabouts,
  no phone serial numbers (name phones by model), no names of people whose data is not public,
  no real session data or photos in `tests/` (build made-up sessions in code).
- Credit follows academic practice: cite insect-detect-post (Sittinger 2026, Zenodo
  10.5281/zenodo.21822140) and the Insect Detect camera (Sittinger et al. 2024, PLOS ONE
  19(4): e0295474) for the format; credit the origin of an idea and its implementer separately,
  in neutral wording. Do not copy their code (AGPL-3.0 / GPL-3.0); writing their file layout is
  not copying.

## Tests

`python -m unittest discover -s tests` from the repository folder (nothing to install). Every rule
mirrored from the app or from insect-detect-post has a test on a made-up session.

## Git

- Commit or push only when the owner asks; never push to `main`, never force push.
- Commits use the repository's git config (GitHub noreply address); no author or attribution
  lines in messages. Stage files by name.
- Start a commit message with a short summary of what changed and why.
