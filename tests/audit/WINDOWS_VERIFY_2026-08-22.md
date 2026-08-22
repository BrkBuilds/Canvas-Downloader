# Windows verification — the 2026-08-22 changes

Paste everything below the line into a fresh agent session on the **Windows
PC**, in a clone of `BrkBuilds/Canvas-Downloader` at `main`.

This is **narrower** than `WINDOWS_AUDIT_PROMPT.md` — it is not a general audit.
It verifies one day's changes, several of which touch the engine and none of
which have run on Windows at all.

---

You are the Windows verification gate for a specific set of changes. Be
autonomous and thorough, sceptical of your own results, and willing to write
"I could not prove this" rather than assume.

## Why you exist

On 2026-08-22 a macOS session made six commits. Two of them change
`core/canvas_logic.py` and `core/sync_manager.py` — the engine every download
and every sync goes through — and **all of it was verified on macOS only**.

This repo's own history is that a fix lands on one platform and sits broken on
the other for months: `pdf_looks_real` was Windows-only for eight months;
`office_safe_path`'s long-path bug could not be reproduced on a dev box with
`LongPathsEnabled=1`. **Windows is ~94% of installs.**

Read `CLAUDE.md` first — search it for the four new sections dated 2026-08-22.
They state the mechanism, the measurement, and why the obvious fix was wrong.
Then `tests/audit/RUNBOOK.md`'s "Do NOT report" sections.

## The one rule

A finding names the two things that disagree and the measurement that settles
it. "It looks wrong" is not a finding. If you cannot reproduce it, say so.

---

## 1 · THE HIGHEST-VALUE CHECK: `.url` shortcut ownership

**This is the one thing most likely to be broken on Windows, and it was
verified only against macOS `.webloc` plists.**

`core/canvas_logic._create_link` now refuses to overwrite a shortcut this app
produced (a Panopto Shortcut output). The check is
`path_exists(filepath) and is_produced_shortcut(filepath)`.

On macOS a shortcut is a `.webloc` — a **plist**, and the marker is a sibling
plist key. On Windows it is a `.url` — an **INI file**, and the marker is a
`[CanvasDownloader]` section. Those are different code paths in
`shared/shortcuts.py`. Verify the Windows one:

```python
# in a venv python, from the repo root
from pathlib import Path
import tempfile
from shared.shortcuts import write_shortcut, is_produced_shortcut, SOURCE_PANOPTO
d = Path(tempfile.mkdtemp())
ours = d / "Lecture.url"; write_shortcut(ours, "https://panopto/x", source=SOURCE_PANOPTO)
print("ours    ->", is_produced_shortcut(ours), "(must be True)")
canvas = d / "Canvas.url"; canvas.write_text("[InternetShortcut]\nURL=https://canvas/x", encoding="utf-8")
print("canvas  ->", is_produced_shortcut(canvas), "(must be False)")
```

Then drive the REAL method, which is what actually matters:

```python
from core.canvas_logic import CanvasManager
m = object.__new__(CanvasManager)          # no __init__: no network, no creds
before = ours.read_bytes()
out = m._create_link("Lecture", "https://canvas/modules/items/9", d, None)
print("untouched:", ours.read_bytes() == before, "(must be True)")
# and the control - a stale Canvas link MUST still be regenerated:
m._create_link("Canvas", "https://canvas/NEW", d, None)
print("regenerated:", b"NEW" in canvas.read_bytes(), "(must be True)")
```

**AT DEPTH.** Both halves of the check are long-path safe on paper
(`path_exists` and `read_shortcut` both go through `make_long_path`) — confirm
it empirically. **First run `python scripts/check_longpath_gate.py`**: if it
exits 1 the machine has `LongPathsEnabled=1` and a long-path test there passes
whether or not the bug exists, which is worse than no test. If the gate is
enforcing, repeat the above with the folder nested past 260 characters.

## 2 · Build the Windows installer — `scripts/build_windows.py` was rewritten

It has **never run on Windows**. It is also the release deliverable: v2.0.2 is
published as a prerelease with only the macOS DMG attached.

```
python scripts/build_windows.py
```

Expected, and each is a new guard:

* it prints the version and the git commit, and says **DIRTY** if the tree is dirty
* `version_info.py` is regenerated **and parsed back**
* the `.exe` and the installer are each verified to exist and be a real size
* it emits **`installer_output/Canvas_Downloader_v2.0.2_Windows.exe`** beside
  Inno's own `Canvas_Downloader_Setup_2.0.2.exe`, and the last line names
  exactly which file to upload

Then check the negatives:

* `python scripts/build_windows.py --no-installer` → builds the app, skips Inno, exit 0
* temporarily rename ISCC (or run where it is not on PATH) → it must **exit 1**
  and must NOT print "built successfully". The old version printed success and
  exited 0 with no installer.
* `iscc Canvas_Downloader_Setup.iss` with **no** `/DAppVersion` → must now
  **fail the compile** with an `#error`. It used to silently produce
  `Canvas_Downloader_Setup_2.0.0.exe` on a 2.0.2 tree.
* `powershell -File scripts\build_windows.ps1` → must delegate to the Python
  script (it was a second, divergent implementation that did all three of the
  wrong things above).

**Install the built exe and launch it.** Confirm the version in Explorer's file
properties and in the app sidebar both read 2.0.2.

## 3 · The Canvas metadata retry (`core/canvas_logic._CANVAS_RETRY`)

Transport-level retry mounted on every canvasapi session. `pytest
tests/test_canvas_metadata_retry.py` is portable — it drives a real local HTTP
server, no Canvas needed. It must pass.

Two Windows-specific things the tests do not cover:

* **Login latency must not regress.** The retry is `connect=0` deliberately: a
  connect retry costs another full 15s connect timeout. Point the app at an
  unreachable Canvas URL and confirm it reports failure in ~15s, not ~50s.
* **A real run.** Do one download of a real course and confirm the debug log
  contains no `Module items unavailable` line (it should stay silent when
  Canvas is healthy — that silence is the thing to confirm).

## 4 · The full suite and the mutation passes

```
python -m pytest -q
python scripts/verify_architecture.py
python scripts/_mutate_shortcut_ownership.py          # expect 9/9
python scripts/_mutate_canvas_metadata_retry.py       # expect 10/11, 1 documented equivalent
python scripts/_mutate_office_lock_coverage.py        # expect 9/9
```

macOS reports **4370 passed, 40 skipped**. Windows will differ — the skip SETS
are different per platform, which is the point. **Report the Windows skip list**,
because a test that skips on both platforms runs nowhere.

> **Before running any mutation pass**: `git status` must be clean, and no other
> pass may be running (`tasklist | findstr python`). A pass writes broken code
> into the tree and restores it seconds later. On 2026-08-22 an interrupted pass
> restored a **stale snapshot over newer edits**, silently reverting a fix and
> producing four phantom suite failures that read exactly like a regression. If
> a suite failure follows a mutation pass, `git diff` the SOURCE before
> believing it.

## 5 · Sanity, not investigation

`engine/applescript_bridge.py` changed (instance-scoped Office marker) but is
macOS-only. Just confirm nothing on Windows imports it eagerly and that the
suite is green.

---

## Working alongside the macOS session

`CLAUDE.md`, `tests/audit/AUDIT_FINDINGS.md` and the runbooks are shared and
both sessions want to append to them. If a macOS session is live, do the code
and the tests and **hand the operator the prose** rather than appending
yourself. Scope every git command to your own paths; never `git add -A`.

## Recording

Register is at **0 open / 180**. Anything you find goes in
`tests/audit/AUDIT_FINDINGS.md` with the measurement that settles it. If
everything passes, say so plainly and name what you could NOT prove — that list
is worth as much as the findings.
