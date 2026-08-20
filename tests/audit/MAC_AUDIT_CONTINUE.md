# macOS audit — continuation brief

**Rewritten 2026-08-20, end of the third macOS session.** This file is only
"where we are and what is left"; `MAC_RUNBOOK.md` has the phase plan,
`RUNBOOK.md` the oracle rules, `MAC_OFFICE_FIXES.md` the Tahoe session record,
and `AUDIT_FINDINGS.md` the register. Nothing here repeats them.

Run: `_audit_runs/20260820_143238_macos-26-v2.0.2`. Branch `macos-audit-26`.

---

## Machine state — do NOT re-derive

| fact | value |
|---|---|
| OS / arch | macOS **26.6.1** Tahoe, M4 arm64 |
| agent shell | Aqua (VS Code terminal), Keychain usable, Screen Recording + Automation granted |
| Accessibility | granted to **Canvas Downloader** and **Visual Studio Code** this session (see Cleanup) |
| Full Disk Access | absent, and that is the INTENDED state — the FDA nudge needs it ungranted |
| `pyinstaller` | installed into `.venv` by hand — in neither `requirements.txt` nor the bootstrap |
| bundle | built + ad-hoc signed at `dist/Canvas Downloader.app`, `--verify --deep --strict` rc=0 |
| packaged app config | driven with `open --env CANVAS_DL_CONFIG_DIR=/tmp/pkgcfg "dist/Canvas Downloader.app"` |
| iCloud | account signed in, iCloud Drive ON, ~5 GB free tier (see Cleanup) |
| whisper model | **none** installed — which is what makes the transcription-setup notice render |
| suite / audit | **3924 passed, 26 skipped**; architecture audit **0 violations** |
| register | **138 total · 8 open · 75 fixed** |

Token: in the login Keychain under service `CanvasDownloader`, username
`https://cbscanvas.instructure.com`. Readable from a plain venv python with
`ui.auth._safe_keyring_get(...)` — no prompt. **`CanvasManager(api_key, api_url)`
takes the TOKEN FIRST**; the other order makes requests parse the token as a
hostname and print it in the traceback. Always run Canvas scripts with
`2>/dev/null` or a `try/except` that truncates.

---

## What this session settled (12 commits, all pushed)

* **fp:989c128a238d CLOSED** — the per-run Office quit gate finally ran on a Mac.
  All three Phase M1 step 8 checks pass. The destructive half is **load-dependent**:
  Word's documents stay describable at 2 converted files and go undescribable at
  3+. `verify_office_end_to_end.py` now refuses a below-threshold `--files`.
* **fp:ad96dfaae9ad CLOSED** — a CR in a filename converts; container staging had
  already fixed it. 13/13 hostile names.
* **fp:8e7fc38cea3d re-confirmed** on 26.6.1, decision unchanged, plus the new
  detail that the read-only mode is **erased** (0444 → 0644), not just bypassed.
* **iCloud is SUPPORTED** and the properties that make it work are now a portable
  contract — see `CLAUDE.md`, `tests/test_icloud_dataless.py`.
* **A data-loss defect fixed**: a skip-existing re-download rewrote
  `original_md5` from the on-disk bytes, erasing `_NewVersion` protection for a
  same-size edit. No heal pass is possible (investigated; recorded on the
  finding).
* **Two Panopto completion-card defects fixed** (a structurally impossible
  "0 Downloaded", and the card rendering when the run produced nothing).
* **WKWebView spot-check** of everything shipped after 2026-08-11, including the
  transcription notice's full dismiss/re-spawn cycle.
* The osascript notification fallback **delivers** but paints no banner
  (confounded by NoMachine — recorded as unresolved).

---

## What is LEFT

**None of the 8 open register findings is macOS-specific.** They are Windows
(the two COM `EXCEL.EXE` leaks, `bridged_warning`) or cross-platform (the
identical-size orphan pair, the Panopto-formats config gap, the model-delete UX,
the read-only `os.replace` note). Investigate those OFF this machine.

So "what needs a Mac" is the runbook steps never driven:

* **M1.3** force a conversion failure — a password-protected `.doc`, and
  revoking Automation for Word mid-run (must abort ONCE with one actionable
  message, not one error per file).
* **M1.5 / M1.6** Office leak check and Dock recents tiles after a real phase.
* **M1.7** long paths — a deep course folder, `office_safe_path`'s ≥240-char
  shadowing, against macOS's 255-BYTE-per-component limit.
* **M2.3** `converters/url.py` must spare our `.webloc` while compiling foreign
  shortcuts, and keep a Windows-written `.url`.
* **M2.5** transcription on Apple silicon — the CPU path, the out-of-process
  worker surviving a crash, and cancel mid-transcription leaving no `.part`.
  **A model must be downloaded first**, which also clears the setup notice.
* **M2.6** model download + the "Manage installed models" dialog.
* **M3.3 / M3.4 / M3.8** argv drop, phantom instance, and quit → orphan reaping
  in the PACKAGED app.
* **M4.1** HFS+ / NFD — needs an HFS+ image (`mac_smoke.py --with-hfs` covers
  part of it).

---

## Traps this session paid for

* `mac_eyes shot --window "Canvas Downloader"` matches by TITLE, and **VS Code's
  own window title contains that string** — it silently captured the editor.
  Activate the app by PID and take a full-desktop shot.
* Driving a WKWebView: System Events needs Accessibility (which the app
  deliberately never requests) and **the grant does not apply to already-running
  processes**; even then `click at {x,y}` returns **-25208**. What works is a
  CoreGraphics event — `CGWarpMouseCursorPosition` then
  `CGEventCreateMouseEvent` posted to `kCGHIDEventTap`. Coordinates map 1:1 on
  this 1920x1080 display; read them off a `screencapture`.
* A genuine TCC prompt **blocks** osascript. If a script hangs, check for one.
  macOS ignores synthetic clicks on consent prompts — screenshot and ask.
* Launching a freshly re-signed bundle raises a **Keychain prompt** that blocks
  session restore until a human answers it.
* `brctl status` answers *"Client zone not found"* for a file that is plainly
  synced. Detect dataless with `st_blocks == 0` at nonzero `st_size`.
* Creating a `.pptx` by driving PowerPoint times out (-1712) and crashes it into
  Microsoft Error Reporting. Word samples come from `textutil -convert doc`,
  Excel's from `openpyxl`; there is no cheap PowerPoint equivalent — use real
  downloaded course files.

---

## Cleanup owed before the machine is released

Nothing on a rented box survives reimaging, but these are the operator's:

1. **iCloud** — an Apple ID is signed in with their own gmail. Sign out.
2. **Accessibility** — revoke Canvas Downloader and Visual Studio Code. The app
   does not need it; it was granted so the agent could drive the WebView.
3. Test folders under `/tmp/wkwebview_course`, `/tmp/pkgcfg` and
   `~/Library/Mobile Documents/com~apple~CloudDocs/CD*` are disposable.
