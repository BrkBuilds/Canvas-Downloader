# macOS 26 audit — continuation brief (written 2026-08-11, mid-run)

This is a **handoff for the session that picks the macOS 26.6 audit back up**,
written because the run is not finished and the Mac is rented. Everything below
was measured on this machine today. Read `MAC_RUNBOOK.md` for the phase plan and
`RUNBOOK.md` for the oracle rules; this file is only "where we are and what is
left", so it does not repeat either.

Run: `_audit_runs/20260811_155557_macos-26-v2.0.2`. Branch `macos-audit-26`.

---

## Machine state — do NOT re-derive any of this

| fact | value |
|---|---|
| OS / arch | macOS **26.6** Tahoe, M4-S arm64, `is_macos_15_plus()` is **True** |
| agent shell | Aqua, Keychain usable, Screen Recording + Automation **granted** |
| `has_full_disk_access()` in that shell | **False** — this is the FDA-nudge route on Tahoe (the SSH recipe does NOT work here; `sshd-keygen-wrapper` HAS FDA) |
| doctor | READY (1 warning: FDA, which is the state we want) |
| `pyinstaller` | installed into `.venv` by hand — it is in **neither** `requirements.txt` nor the bootstrap |
| bundle | built + ad-hoc signed at `dist/Canvas Downloader.app`, `--verify --deep --strict` rc=0 |
| bundle config dir | `~/Library/Application Support/CanvasDownloader/` — settings seeded by hand; the bundle was granted **Always Allow** on the Keychain item |
| whisper model | `tiny` installed (74.6 MB) under `panopto_models/` |
| snapshot | `c43660_base` — 255 files, 217 manifest rows, integrity ok |
| app / browser | **stopped** at handoff. Restart with `app start` then `browser open` |

**The audit config's `panopto_notice_ack_version` is PRESENT again** — item 3
used it and the app re-recorded it, which is correct. To re-arm the dialog for
another test, delete that key from the run config AND restart the app: the
positive answer is memoised in session state (`shared/legal.py`), so removing
it from the file alone changes nothing in a running process.

### Harness traps this session paid for

* `finding add` — `title` is POSITIONAL; `--evidence` takes **JSON or `@file`**,
  NOT a path (a path dies in a `JSONDecodeError`); `--category` must be one of
  the fixed list (there is no `environment` — use `observation`).
* **Never pass prose to `--detail` in double quotes.** Write it to a file and
  use `--detail "$(cat file)"`.
* `mac_smoke.py --bundle` takes a path argument.
* `mac_eyes dialogs` now suppresses Tahoe's titled phantom alert and PRINTS that
  it did. A genuine TCC prompt BLOCKS `osascript`, so if a script hangs, check it.
* git identity is set repo-local (it was unset on this box).

---

## What is DONE (do not repeat)

M1 Office, M2 Panopto (shortcuts + `.webloc`/Finder + URL compiler + transcription
+ cancel + **mp3**), M3 the packaged bundle, M4 `_path_key`/HFS+/case-probe, M5
Keychain cycle + Reveal in Finder + FDA nudge, and a full seeded Phase 2 sync.
Details are in the register (`AUDIT_FINDINGS.md`) and in `MAC_RUNBOOK.md`'s
"What the macOS 26 run settled".

Product fixes shipped: `91c7c58` (case probe). Checker fixes: `13c70c7`,
`56fa5f6`, `aade2c0`. Docs: `2d5e6d6`.

---

## READ FIRST: `MAC_OFFICE_FIXES.md`

**2026-08-11, late.** An operator report during the download matrix (PowerPoint
crashed, then every conversion showed a full-screen window) uncovered FOUR
Office-conversion defects, one of them DATA LOSS - all three converters can
close the USER'S document with `saving no`. The investigation is COMPLETE and
measured; the fixes are NOT written.

That work is the top priority and lives in its own file:
**`tests/audit/MAC_OFFICE_FIXES.md`**. It carries the causal chain, the exact
fix for each defect, the operator's decisions, the verified-safe recipe for
cleaning 490 rows out of Office's shared Recents store, and two harness bugs
found alongside.

Also since this file was last written: the cold-launch WHITE FLASH is FIXED and
proven on the packaged bundle (255080d - 0 white frames, was 5 at 249 luma), and
the notification denial policy is settled (588bead - respect a denial, never
route around it via osascript's Script Editor identity).

---

## What is LEFT, ranked, with how to do it

**Updated 2026-08-11 evening.** Items 3, 4 and 5 are DONE; 1 and 2 are partly
done. Everything below is what genuinely remains.

### DONE since this file was written

* **Item 3 - the sync-side Panopto notice, against a LIVE dialog.** Validated on
  the QUICK SYNC path, which is where the sync-side notice actually lives
  (`sync_ui.py:1893`, gated on the folder's stored contract). The review path
  correctly asks nothing when no recording is pending (`_pan_selected == 0`),
  which is why two earlier attempts saw no dialog. With the ack removed:
  `panopto_notice: {"shown": true, "accepted": true}` and the ack reappeared.
  Commits b02e39c, 89830d1.
* **Item 4 - both surviving sync HIGHs were CHECKER defects, not product ones**
  (479cd29). The `expected_untracked` diagnosis was right in outcome but wrong
  in location - the fix belongs in `oracles/db.py`, because an ignored row with
  a real `local_path` is a shape any USER produces by ignoring a file they
  already have. **The `renamed-ambiguous` diagnosis in the old text below was
  WRONG**: it confused the two fixtures. O1 and O2 AGREE; the app offers one of
  two identically-sized orphans per sync and the next sync offers the other.
  Filed as a low-severity product observation with the evidence.
* **Item 5 - the SYNC matrix: 43/43 rows, 0 failed, all findings INFO.** Course
  46386 (97 files / 92.6 MB) snapshotted as `c46386_base`, 2 lanes, 100% 2-way
  and 3-way-interacting coverage. This also swept the checker fixes across the
  corpus in both directions.
* **Item 2 - the folder-picker MODAL** (operator clicked Choose). See
  MAC_RUNBOOK item 3; it also corrected a wrong claim there about `/private`.
* **Item 1 - the notification code defect is FIXED** (fd05d18) but the PRODUCT
  question is unresolved - see below.

### 1. Can ANY fallback display a banner while the app is DENIED? - the last gap
The code defect is fixed: `_show_macos_notification_un` now waits for the
completion handler and returns False on an explicit rejection, so the fallbacks
are reached. What is NOT established is whether reaching them achieves anything.

It needs **no packaged app and no login** - only a clear screen:

1. `python scripts/mac_eyes.py dialogs` - if a consent prompt is in the
   top-right corner, STOP; the measurement is meaningless. (That is exactly what
   contaminated the attempt on 2026-08-11: a Downloads-folder TCC prompt and a
   Keychain prompt were sitting where the banner appears.)
2. Full-screen `screencapture`, then
   `osascript -e 'display notification "x" with title "Canvas Downloader"'`,
   then capture again after ~1.2s and diff (PIL `ImageChops.difference` +
   `getbbox`). A changed bbox in the top-right **containing the text** is the
   answer.

If it displays, the fix is what makes it reachable and the finding closes. If
macOS suppresses every path for a denied app, the fix is inert-but-harmless and
the DOCSTRING is what should change instead.

### 2. The cold-launch WHITE FLASH - product defect, still deliberately unfixed
Unchanged from the original text, and the mechanism is now confirmed by reading
pywebview 6.1's Cocoa backend: `background_color` is applied with
`self.window.setBackgroundColor_(...)` - i.e. to the **NSWindow** - while
`drawsTransparentBackground` is set on the WKWebView **only** inside the
`if window.transparent:` branch, which also does `setOpaque_(False)` and
`setHasShadow_(False)`. So the web view paints its own white until first content
paint, and the window colour behind it never shows.

The targeted repair is to set that one KVC flag WITHOUT the rest of the
transparent branch. Two reasons it was not done on this run, both unchanged:
it changes how every screen composites, in a WKWebView the harness cannot drive;
and it needs a rebuild + re-sign per measurement (a fresh signature is what
makes the launch cold). Reproduce with 40 `screencapture` frames at 0.15s and
the mean luminance of the window interior; the flash is ONE frame at ~0.75s.

### 3. The DOWNLOAD matrix
Still not run on this machine. The sync matrix is the one that exercises the
analyzer; the download matrix is the config space and pulls in the Office
converters, which is what OOM-killed a 16 GB machine at 4 lanes. Use 1-2 lanes
and read the lane-count table in RUNBOOK before choosing.

### 4. The product observation filed this run
"Two orphaned Canvas files of identical size are re-offered one per sync, not
both." Self-healing, nothing lost, not a blocker - but the MECHANISM was not
found. `analyze_course` dedups by canvas id and seeds `claimed_paths` only from
TRACKED rows, so on inspection both ids should have been offered in run 1.

