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

**The audit config's `panopto_notice_ack_version` was deliberately REMOVED** so
the acceptable-use dialog is armed. Leave it removed — item 3 below needs it.

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

## What is LEFT, ranked, with how to do it

### 1. A real notification DENIAL in the bundle — OPERATOR-GATED
Open finding `fp:3833d3d15043`: `_show_macos_notification_un` returns True
before the async completion handler sees an error, so a rejected request is
reported as success and **all three fallbacks are skipped**.

Half of it is now settled: the bundle registers with macOS under its **own**
identity (its permission banner appeared on first launch), where a source run
registers as an app called "Python" — which is why the macOS 15 run could not
test this at all.

To finish it: ask the operator to set System Settings → Notifications → **Canvas
Downloader → Allow notifications OFF**, then drive a notification from the
packaged app and assert that a fallback is attempted rather than the chain
reporting success. Note the app's own log lines `UN settings: authorizationStatus=…`
and `UN addNotificationRequest error: …` are the evidence to read.

### 2. The folder-picker MODAL — OPERATOR-GATED
`native_folder_picker` (osascript `choose folder`). The RETURN path was proven on
macOS 15 (a quoted folder name survives; the return carries a trailing slash and
the `/private` form, and `pair_key`/`_path_key` collapse both). What is unproven
is the modal itself, including a folder whose name contains a quote. Opening it
blocks on a human and macOS refuses synthetic clicks — use `mac_eyes dialogs`,
name the button, and continue.

### 3. The SYNC-side Panopto notice, against a LIVE dialog
`56fa5f6` moved the notice handling after the click that raises it and added it
to `SyncFlow.analyze` / `SyncFlow.confirm`, which previously had **none**. The
download side is validated against a real dialog; the sync side is **not** —
both attempts hit a folder that was already up to date, so no review screen
existed and the run failed at `btn_sync_selected` before the notice mattered.

Recipe: `snapshot restore c43660_base --pair` → `seed apply "<folder>"` (a seeded
folder HAS changes, so Review is reached) → confirm the ack is still absent from
the run config → `flow sync <name>`. Then assert the trace's `analyze` step
carries `panopto_notice: {"shown": true, "accepted": true}` and that
`panopto_notice_ack_version` reappears in the settings file.

### 4. The 2 surviving sync HIGHs
Both re-derivable with `check sync` against the existing evidence; no re-run needed.
* `2 content file(s) on disk with no manifest row` — these are the seeder's own
  two `ignored` fixtures, missing from `expected_untracked`. Documented
  checker-defect-15 family: the fix is in `seed_expectations`, and per RUNBOOK
  prefer **deriving** the list over storing it.
* `'renamed-ambiguous:zz flertydig 1.jpg' expected as new but no oracle placed it`
  — the app is CORRECT (the screen shows `CBS_SolbjergPlads_ImageHeader-1` under
  New). The fixture resolves in isolation, so the fault is in oracle SELECTION:
  `want="new"` is in `_LOG_DETAILED_CATS`, so the check consults O2 and never
  falls back to the review screen when the log map misses. Fix the selection, then
  sweep both directions over the corpus before trusting it — repairing the log
  path can CREATE findings (RUNBOOK defect 26 says exactly this).

### 5. The download + sync MATRICES
Not run at all. This run covered one real download, one seeded sync. Use
`matrix build` / `prepare` / `launch`. Two things from RUNBOOK that apply here:
lane apps restore their session from the **Keychain**, so launch from a session
that can reach it (this agent shell can); and this machine has 16 GB, so read the
lane-count table before choosing `--lanes`.

### 6. The cold-launch WHITE FLASH — product defect, deliberately unfixed
Recorded with full evidence (`mac_m3_white_flash`). `start.py` already passes
`background_color='#0d1117'`; pywebview applies it to the **NSWindow** while the
**WKWebView paints its own white** until first content paint. The plausible
repair is to stop the web view drawing its own background (pywebview's Cocoa
backend does something of that shape in its `transparent` branch via
`setValue_forKey_('drawsTransparentBackground')`).

**That changes how every screen composites**, in a WKWebView the harness cannot
drive, so it needs a before/after pass on the real screens — not a speculative
change. Reproduce with: rebuild + re-sign (a fresh signature is what makes the
launch cold), then 40 `screencapture` frames at 0.15 s and measure the mean
luminance of the window interior; the flash is ONE frame at ~0.75 s.

---

## Standing rules for whoever continues

* Re-run `python -m pytest tests/ -q` on the Mac before pushing. Last green here:
  **3506 passed, 26 skipped**. Green on macOS is not green on Windows — check any
  new test for platform assumptions (`normcase` is the identity off Windows, and
  that has now bitten twice: once in the product, once in the checker).
* Push early. The Mac is rented.
* A finding needs its **oracle pair**. Prefix macOS scenarios `mac_`.
* The checker still fails more often than the app: this run found **1** product
  defect against **7** checker defects, which is the same ratio RUNBOOK records.
  Interrogate a red row before filing it.
