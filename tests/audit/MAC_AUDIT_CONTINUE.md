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

**Everything the fourth session listed as outstanding has now been driven.**
A fifth pass (2026-08-20, late) closed the lot in one real packaged-app run of
course 43660 plus a real HFS+ volume - see `MAC_RUNBOOK.md`:

| item | outcome |
|---|---|
| **M1.3** Automation revoke | CLOSED - a real Don't Allow in the PACKAGED app. `-1743`, classified `permission`, aborted, `.doc` intact, no stub PDF. Exposed and fixed a retry defect (`fp:6c1a2474d09e`). |
| **M2.1** discovery | CLOSED - 36 recordings, 38 LTI handshakes |
| **M2.2** `.webloc` | CLOSED - 77 files, 0 malformed, all 36 of ours collision-resolved to `(Panopto)`; Safari opens one onto the real SSO login |
| **M2.4** mp3 via bundled ffmpeg | CLOSED - 36 mp3 in ~55 s, real streams and durations |
| **M3.8** with a real media child | CLOSED - quit mid-transcription reaped a 577 MB worker, 0 leftovers, `clean_exit: True` |
| **M4.1** HFS+ / NFD | CLOSED - on a real HFS+ image; 0 orphans, 0 untracked, and the control shows 2 would fail without `_path_key` |

So there is **no remaining runbook step that needs this Mac**. What is left is
off-machine work: none of the register's 8 open findings is macOS-specific -
they are Windows (the two COM `EXCEL.EXE` leaks, `bridged_warning`) or
cross-platform (the identical-size orphan pair, the Panopto-formats config gap,
the model-delete UX, the read-only `os.replace` note).

### What is NOT proven - written down deliberately, because a closed list
### of steps is not the same as a covered surface

Ranked. The first is the one that would keep me up at night.

1. ~~The PACKAGED app has never successfully converted an Office file.~~
   **CLOSED 2026-08-20**: 184,741-byte real `%PDF-`, source consumed, Word
   correctly quit, under `com.canvasdownloader.app`'s own identity.

2. ~~A DENIED powerbox prompt is an untested user state.~~ **CLOSED, and it
   was a real defect** - `fp:f6924f2b9dbc`, fixed and verified in the
   rebuilt bundle.

2b. ~~A denied KEYCHAIN prompt costs ~90 seconds of bare "Connecting…".~~
   **FIXED AND VERIFIED IN THE PACKAGED APP, 2026-08-21** (register
   `fp` "The macOS Keychain ACL prompt ran on the SCRIPT THREAD"). It was
   worse than recorded: after the boot overlay's 30 s cap the window was
   **completely EMPTY**, not "Connecting…", and on Deny the user landed on a
   login page with **no explanation at all**. `keyring_get_without_prompting`
   now probes with keychain UI suppressed (4.3 ms / 9.6 ms measured), the
   login screen explains the dialog and steers to **Always Allow**, and a 1 Hz
   fragment adopts the answer. Packaged app: notice up at **t=3 s**, signs
   itself in ~3 s after the click, next launch silent in 1.15 s.
   Full mechanism in `CLAUDE.md`; how to reproduce it in `MAC_RUNBOOK.md`.

3. **The transcription phase never COMPLETED in the packaged app.** The worker
   spawned correctly at `[1/36]` and was deliberately killed there for M3.8,
   so no transcript was recorded to a manifest by the bundle. The frozen
   worker itself IS proven (byte-identical output to dev, `routed_via=env`),
   and so is the runner's spawn - only the tail of the chain is unseen.
   The Panopto COMPLETION SCREEN was never reached either.

4. **The `.part` self-heal is reasoned, not measured in situ.** Calling
   `_clean_part_files` on the orphan removed it (1 -> 0), and the code shows
   the recording would be a task again next run - but no second Panopto pass
   was run to watch the sweep happen by itself.

5. **"Quitting while a TCC prompt is pending records an unclean exit" was not
   reproduced** - and the stated CONSEQUENCE was wrong, so it is worth less
   than it looks. `_post_mortem` writes that line through `_write()`, i.e. into
   `diagnostics/health.log`; a whole-tree grep finds **no UI surface** for it,
   so no user ever sees it. The residual is a confusing line in a diagnostic
   file. Do not spend rental time reproducing it.

6. **mp4** was deliberately left off (bandwidth); only the mp3 muxer path is
   proven. M2.4's video half is untested.

7. **Notifications: mostly SETTLED 2026-08-21, and the earlier reading was
   wrong.** The primary `UNUserNotificationCenter` path DOES work in the
   packaged bundle and is attributed to **Canvas Downloader** - confirmed in the
   usernoted delivery DB and visually in Notification Centre (app icon, correct
   body). The osascript fallback is not being reached at all. Only "does a
   BANNER flash" remains, confounded by the remote session, and it is not worth
   another prompt storm. NOTE: `com.apple.ncprefs` is the WRONG oracle - the app
   is absent from it even after delivering.

8. ~~A genuinely FIRST-RUN machine.~~ **CLOSED 2026-08-21** - driven end to end
   in the PACKAGED app after `tccutil reset` + an empty config dir (which is
   enough, and avoids touching the Keychain). A CLEAN PASS on every axis: the
   three Office Automation prompts batched **within 11 s** of Start, the
   powerbox at +18 s, run complete at +30 s; 23 files, the one Office file
   converted with its source consumed (proven by the manifest row
   `04_Exercise.pptx -> Exercise 4/04_Exercise.pdf`), all three Office apps
   quit, **0** entries left in Office Recents, **0** staging leftovers, and a
   completion notification delivered under the app's OWN identity. The keychain
   notice correctly did NOT render (a fresh install has no saved token). Method
   and traps in `MAC_RUNBOOK.md`.

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
4. `/tmp/m2 m13 m17 m17c m17x m23 m26 m34 m5 nfd2 nfd_apfs case_apfs`
   - disposable. `/tmp/m5/downloads` holds a full copy of course 43660
   (~1.3 GB with the Panopto mp3s).
6. **The HFS+ test image**: `hdiutil detach /Volumes/NFDTest && rm /tmp/nfd.dmg`.
7. **TCC already reset** for `com.canvasdownloader.app` (AppleEvents and
   SystemPolicyAppData), so the app is NOT left denied - but it will
   prompt again on its next Office conversion, which is the correct
   first-run state.
5. The **small Whisper model** at `panopto_models/small` (464 MiB, gitignored).
   Keep it if the next session does Panopto work; delete it to get the
   transcription-setup notice back.


---

# THE FIFTH SESSION - the overnight full audit (2026-08-21)

Run `_audit_runs/20260821_022815_macos26-full-night` (matrix) and
`20260821_night_pkg` (packaged). Branch `macos-audit-26`, 10 commits, all pushed.

## What ran

| | |
|---|---|
| bundle | REBUILT from HEAD and ad-hoc signed; `--verify --deep --strict` rc=0 |
| download matrix | **56/56 rows, 0 failures** - 100% 2-way and 3-way coverage, 4 courses, 3 lanes |
| packaged Panopto | **maximal**: 43660, all five outputs, 408 files / 3.3 GB in 2h35m |
| suite / audit | **4085 passed, 26 skipped**; architecture audit **0 violations** |
| register | **156 total, 8 open** - the same 8 as before the night, none macOS-specific |

## Unproven items CLOSED

* **#3 transcription in the packaged app.** 36/36 transcribed, `panopto_manifest`
  holds 36 of every kind (mp3/mp4/srt/txt/url), **0 `.part` leftovers**, and the
  Panopto completion screen was reached and reads *36 downloaded · 36
  transcribed · 36 links*.
* **#6 mp4.** 36 real h264/AAC files; the first probes at 9m37s, 1920x960, 60fps.
* Total transcription workload measured: **8.21 h of audio, 36 recordings, mean
  13.7 min**, at ~4.1 min per recording with `small` on this M4 CPU.

## Four product defects and one harness defect, all fixed

1. **The manifest repoint depended on how the path was SPELLED** - 62 of 63
   Office conversions left their row on the source they had just deleted.
   Measured consequence, on the app's own review screen: **"63 Deleted
   locally"**. Mechanism and fix in `CLAUDE.md`.
2. **A part-way conversion's 64 KB partial PDF passed `pdf_looks_real`** and was
   promoted into the folder. That gate also guards deleting the user's only
   copy. Now requires a `%%EOF` trailer.
3. **-609 (`connectionInvalid`) was classified `other`**, so a dead Office
   connection was never retried. Now `app_crashed`. Verified live: row m001
   recovered in 4 s from the same condition row m048 reported as a dead loss.
4. **-30001 deliberately left as `other`** - our own frontmost guard; retrying
   it would tell the user a running app had stopped.
5. **HARNESS: office+gpu rows ran in two concurrent lanes** - 7 of 9 gpu rows
   also convert Office. Only avoided this run because the gpu lane was started
   by hand.

## Traps, and things that are NOT defects

All recorded in `MAC_RUNBOOK.md` under "The fifth macOS session". The two that
cost the most time:

* **`open --env` is not sticky.** A second launch runs with no override, the two
  instances have different config dirs so their single-instance locks cannot see
  each other, and the audit silently ran a 152-file download against the
  developer's real config. `pkgdrive.launch()` now reads the override back off
  the running process and refuses otherwise.
* **Seven of my own analyses were wrong before they were right** - `files_tab`
  is not `files`, `local_path` is RELATIVE, Panopto lives in its own
  `panopto_manifest` table, `_cost_mb` belongs to `_course_ids` not
  `_course_id`, `estimated_cost_mb` is a scheduling cost and not bytes, the
  Canvas-link collision was ordering not overwriting, and the `(n)` PDFs were
  directory reuse. Measure with the harness's own oracles before believing an
  ad-hoc query.

## What is LEFT

* **The SYNC matrix was not run.** A snapshot of the packaged folder is captured
  (`c43660_panopto_maximal`, 405 files, 2.7 GB, manifest integrity ok) and one
  targeted sync analysis was run against it - that is what produced the "63
  Deleted locally" measurement. The full `--kind sync` matrix is the main
  remaining coverage gap.
* The 8 open register findings are Windows or cross-platform; investigate them
  off this machine.
* FDA is now GRANTED to the app, so the FDA nudge and the per-session powerbox
  re-arm are untestable until it is revoked.

---

# RESUME HERE — the sync matrix adjudication (written 2026-08-21, mid-session)

Everything below is state that existed only in a conversation. Read this before
touching the sync findings; it assumes no memory of that conversation.

## Where the evidence is

| thing | where |
|---|---|
| sync matrix run | `_audit_runs/20260821_113342_sync-matrix` (+ `__free1/2/3` lanes) |
| download matrix | `_audit_runs/20260821_022815_macos26-full-night` (+ 3 lanes) |
| packaged maximal | `_audit_runs/20260821_night_pkg`, folder at `/tmp/audit_night/downloads/...` |
| CLEAN sync fixture | snapshot `c43660_postfix_clean` — post-fix, conversions ran |
| PRE-FIX fixture | snapshot `c43660_panopto_maximal` — carries the 63 stale Office rows |
| per-row seed plan | `_audit_runs/…__free1/evidence/seed_s018.json` (one per row) |
| per-row review DOM | `_audit_runs/…__free1/evidence/ui/s018_after_analysis.json` |

Both snapshots are of course **43660**. The clean one is the right fixture for
new work; the pre-fix one exists only to demonstrate the repoint defect.

## The sync matrix result, and how the 29 highs break down

**43/43 rows, 0 row failures.** 29 high findings, which collapse by fingerprint
to 5 register entries. Adjudicated by comparing each fixture's expected name
against `evidence.peers_in_category` (the files the app really put in that
category), on EXACT stems:

| n | group | verdict |
|---|---|---|
| 13 | `renamed-ambiguous:zz flertydig 0.pdf` | **KNOWN** — register `fp:5c1dc682e36c`, "Two orphaned Canvas files of identical size are re-offered one per sync". Severity of the BEHAVIOUR is low and self-healing; the HIGH is a checker artefact (one finding per fixture per row). Now reproduced on a second, independent pair — see that entry. |
| 2 | `new:Svarark - Gode råd til projektet.docx` | **CHECKER MISS** — the exact stem IS in the app's `new` list. |
| 14 | `edited-update` / `clean-update` / `readonly` / `deleted-on-canvas`, all on `Eksempel - Gruppekontrakt.docx` and `Svarark - Gode råd til projektet.docx` | **NOT ADJUDICATED — this is the open work.** Genuinely absent from the expected category. |

## The 14: why they matter and how to start

They touch `updated_modified`, `updated_clean` and `deleted_on_canvas` — the
categories that decide whether **a student's edited file is protected**. That is
where a real defect would hide, so they get the full treatment, not a verdict.

Start by reading one row's evidence end to end rather than reasoning:

```bash
R=_audit_runs/20260821_113342_sync-matrix
python - <<'PY'
import json
rows=[json.loads(l) for l in open("_audit_runs/20260821_113342_sync-matrix/findings.jsonl",encoding="utf-8") if l.strip()]
d=next(x for x in rows if x["severity"]=="high" and "edited-update" in x["title"])
print(json.dumps(d, indent=1, ensure_ascii=False)[:3000])
PY
```

Then the row's `seed_<id>.json` (what was planted) and `ui/<id>_after_analysis.json`
(what the screen showed). The seeder plants SEVERAL fixtures per row on the same
two docx files, so identify fixtures by `canvas_file_id`, never by name.

## TWO TRAPS THIS SESSION PAID FOR — do not repeat them

1. **Substring name matching inverts the answer.** A first triage used
   `want in peer or peer in want`, which makes `…Upload` match `…Upload-1` —
   a DIFFERENT Canvas file — and reported 16 checker-misses where the exact-stem
   comparison reports 2. Compare exact stems.

2. **Two attempts to "fix" `crosscheck._name_candidates` were NO-OPS, and both
   were reverted.** The reasoning that looked right and was not:
   * `ui_cat` is keyed by `_stem(token)` (no extension); `log_cat` is keyed by
     `_norm(n)` (WITH the extension).
   * `_DEDUP_SUFFIX` is `[ _-]\(?\d{1,3}\)?$` — anchored at the end — so on a
     log key it never fires: `upload-1.pptx` strips to itself.
   * `want in _LOG_DETAILED_CATS` sends `new` and `updated_clean` to the LOG
     oracle first, so the screen's existing dedup aliasing is not consulted for
     exactly the categories the seeder asserts most.
   Adding a stem-aware alias to `log_cat` STILL changed nothing measurable
   (recheck stayed at 29 high). So the alias is not the missing piece; do not
   re-derive this hypothesis a third time without instrumenting the actual
   lookup first.

   Note also: the LIVE pass reported 20 highs and `matrix recheck` reports 29
   from the same evidence with the SAME checker. That gap is itself unexplained
   and is worth one look — `RUNBOOK.md` says a recheck reaching a different
   verdict than the live pass is a checker defect by definition.

3. **The register already warns about this finding family.** `fp:2e38f73c0857`
   is an `invalid` twin of the renamed-ambiguous finding, closed as an audit
   MATCHER defect; and `fp:5c1dc682e36c` carries an explicit note that a
   previous session mis-diagnosed the app as "CORRECT" by **confusing the two
   fixtures** (fixture 0 was found, fixture 1 genuinely was not). Read both
   before concluding anything about a "not offered" finding.

## Product state, so it is not re-derived

* Suite **4085 passed / 26 skipped**; architecture audit **0 violations**.
* `main` now contains the whole audit branch (merge `c32a582`), pushed. Not tagged.
* Post-fix fixture verified: conversions ran (121 PDFs, 0 Office sources left),
  **0 stale manifest rows** — against 63 in the pre-fix packaged run.
* Panopto/Canvas `.webloc` collision proven in BOTH directions: with
  `convert_urls` OFF all 41 Canvas links survive and all 36 Panopto shortcuts
  divert to `(Panopto)`, 0 shared paths. Last night's "Panopto took the plain
  name" observation was an ORDERING interaction (convert_urls deletes the
  unmarked Canvas links first), not an overwrite.
