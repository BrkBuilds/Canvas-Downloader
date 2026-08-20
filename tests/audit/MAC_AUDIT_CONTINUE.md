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
| Accessibility | granted to **Canvas Downloader** and **Visual Studio Code** (see Cleanup) |
| Automation | the editor's **System Events** grant was toggled off and back on during M1.3 - if window queries start returning -1743, that is why |
| Full Disk Access | absent, and that is the INTENDED state — the FDA nudge needs it ungranted |
| `pyinstaller` | installed into `.venv` by hand — in neither `requirements.txt` nor the bootstrap |
| bundle | built + ad-hoc signed at `dist/Canvas Downloader.app`, `--verify --deep --strict` rc=0 |
| packaged app config | driven with `open --env CANVAS_DL_CONFIG_DIR=/tmp/pkgcfg "dist/Canvas Downloader.app"` |
| iCloud | account signed in, iCloud Drive ON, ~5 GB free tier (see Cleanup) |
| whisper model | **none** installed — which is what makes the transcription-setup notice render |
| suite / audit | **3951 passed, 26 skipped**; architecture audit **0 violations** |
| register | **139 total · 8 open · 76 fixed** |

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

## The fourth session (2026-08-20 evening) - 9 commits, all pushed

Every runbook step the third session listed as "needs a Mac" has now been
driven, except the two noted below. **One real product defect was found and
fixed**; everything else came back clean, and three of my OWN checks were wrong
before they were right - those corrections are the reusable part.

| step | outcome |
|---|---|
| M2.5 transcription | CPU path, crash containment, cancel - all pass |
| M2.6 model download + manager | pass, both global-switch states |
| M1.3 conversion failure | pass; the Automation-revoke half is NOT provable mid-session |
| M1.5 / M1.6 | pass, after correcting which store M1.6 reads |
| M1.7 long paths | pass; the limit is **255 UTF-16 units**, correcting two docs |
| M2.3 shortcuts | pass, including idempotence |
| M3.3 / M3.4 / M3.8 | pass |

**The defect** (register `fp:259a4ac3ac81`, fixed): an uninstalled Office app
classified as `other`, not `app_missing`, so a user without Office got three
generic errors and then advice to "quit Microsoft Word" - an app they do not
have. Three of four wording clauses in `_classify_stderr` were locale-dead.
Found sideways, because the operator's Automation toggle made macOS hand me its
real denial string.

**Three checks of mine that were wrong first** - read these before trusting a
result in the same area:

* M1.6 read the **Dock plist**; Office Recents is a different store entirely.
  The operator caught it by opening Word.
* A teardown or purge called from a **fresh interpreter** always reports "we
  never drove it this run" and does nothing. Same process, always.
* `pgrep -f <pattern>` **matches its own shell**, manufacturing fake orphans.

Full detail for all of it is in `MAC_RUNBOOK.md`, in dated sections at the end.

---

## What is LEFT

**None of the 8 open register findings is macOS-specific.** They are Windows
(the two COM `EXCEL.EXE` leaks, `bridged_warning`) or cross-platform (the
identical-size orphan pair, the Panopto-formats config gap, the model-delete UX,
the read-only `os.replace` note). Investigate those OFF this machine.

So what still needs a Mac is short:

* **M1.3's Automation revoke.** Revoking Word's Automation for the editor does
  NOTHING to a session already running - macOS caches the TCC decision in the
  responsible process. Five convertible `.doc` files still converted in 3.9 s.
  Do it as the FIRST action after a fresh login, or from a Terminal whose grant
  you then clear with `tccutil reset AppleEvents com.apple.Terminal`. What is
  unproven is narrow - whether macOS's denial WORDING reaches the classifier -
  and after this session's fix the classifier accepts both spellings anyway.
* **A quit taken DURING a Panopto download or transcription.** M3.8 passed, but
  with no ffmpeg or worker child alive, so `_terminate_child_processes` was
  never exercised against a real media child - only the WebKit teardown.
* **M2.1 / M2.2 / M2.4** - Panopto discovery, double-clicking a `.webloc` in
  Finder, and mp3/mp4 through the bundled ffmpeg. Not on this session's list.
* **M4.1 HFS+ / NFD** - needs an HFS+ image (`hdiutil`); `mac_smoke.py
  --with-hfs` covers part of it.

None of the register's 8 open findings is macOS-specific - they are Windows or
cross-platform. Investigate those OFF this machine.

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
4. `/tmp/m2 m13 m17 m17c m17x m23 m26 m34` (this session, ~43 MB total,
   mostly a generated lecture mp3) - disposable.
5. The **small Whisper model** at `panopto_models/small` (464 MiB, gitignored).
   Keep it if the next session does Panopto work; delete it to get the
   transcription-setup notice back.
