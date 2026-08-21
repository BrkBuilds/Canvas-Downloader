# Windows verification pass - 2026-08-21

Windows 11 Pro 26200, Python 3.13.1, `main` @ f415a41.
Previous Windows audit: 2026-08-08. Everything shipped since was verified on
macOS or by making `sys.platform` answer `darwin`.

**`LongPathsEnabled = 1` on this machine.** `CLAUDE.md` records two separate
long-path defects that were invisible on a dev box in exactly this state, so
every long-path result below states which value it was measured at.

---

## Baseline gate

`python -m pytest -q` -> **9 failed, 4211 passed, 21 skipped** (260s).
`python scripts/verify_architecture.py` -> see below.

The brief's expected baseline (4215 passed / 26 skipped / 0 failed) is a **macOS**
number. Same total collected on both platforms (4241), so this is a platform
split rather than a different suite.

**All 9 failures are fixture-construction `OSError`s. Zero assertion failures -
no product code is reached by any of them.** Classified:

| file | n | cause |
|---|---|---|
| `test_office_staging_short_names.py` | 3 | `OSError [Errno 22]` - the fixture writes a file named `Lec\rture.doc` / `Lec\nture.doc` / `a\r\nb.doc`. Windows forbids `\r` and `\n` in a filename, so the fixture cannot be built. The code under test is the macOS AppleScript literal escaper. |
| `test_conversion_repoint_spelling.py` | 6 | `OSError [WinError 1314]` - `os.symlink` needs a privilege this account does not hold. The guard is `skipif(not hasattr(Path, "symlink_to"))`, but that attribute **always** exists on Windows; it fails at call time, so the guard tests the wrong thing. |

Neither indicates a product defect. Recommended (not applied - shared-file
rule): guard the symlink group on a *capability* probe rather than `hasattr`,
and skip the line-break group on `os.name == 'nt'`.

I proceeded rather than stopping. The gate exists to stop me measuring a broken
product; the product is not broken, the tests are macOS-shaped.

---

## Area 1 - sync engine conservation / path layer - **PASS**

The conservation logic itself is platform-independent and covered by
`test_analysis_conservation.py`. What differs between platforms is the path
layer beneath it: `os.path.normcase` is a no-op on macOS and **active** on
Windows, and `_path_key` skips its own explicit fold on `os.name == 'nt'` for
exactly that reason.

`_path_key` primitive, on this NTFS volume:

| case | same key? | expected |
|---|---|---|
| `Notes.pdf` vs `notes.pdf` | yes | yes |
| `sub/file.pdf` vs `sub\file.pdf` | yes | yes |
| Danish `Forelæsning år.pdf` NFC vs NFD | yes | yes |
| `Notes.pdf` vs `Notes2.pdf` (negative control) | no | no |

End to end against the **real `SyncManager`**, real NTFS: recorded one row,
renamed the file case-only on disk (`Notes.pdf` -> `notes.pdf`, confirmed by
`iterdir`), then re-asked the untracked-file question:

- before rename: `untracked=0`
- after rename: `untracked=0` - still recognised as tracked, review screen not inflated
- `heal_manifest` afterwards: **1 row**, no duplicate invented

### The 6 unrunnable repoint tests do not hide a Windows defect

A **junction** is the Windows analogue of the symlinked course root those tests
model, and needs no privilege. Driving the real `_course_relative` through
`mklink /J`:

| case | result |
|---|---|
| root via junction, src arrives resolved (*the macOS bug shape*) | `sub/Lecture.docx` |
| root resolved, src via junction (mirror) | `sub/Lecture.docx` |
| both via junction | `sub/Lecture.docx` |
| both resolved (control) | `sub/Lecture.docx` |
| source **already deleted** (every source-consuming converter deletes first) | `sub/Lecture.docx` |
| genuinely outside the course | `None` |

**Positive control**: the pre-fix expression, `Path(src).relative_to(root)` with
no realpath fallback, raises `ValueError` on case 1 - so this probe could have
failed, and did not.

---

## Area 2 - the PDF trailer gate - **PASS**

Site count per converter: `word.py`, `excel.py`, `pdf.py` each carry **2**
`pdf_looks_real` calls against **2** source `unlink()`s (macOS branch + Windows
branch), gate before delete in each pair. (`pdf.py`'s third `unlink` targets the
*output*, not the source.)

Live, via real COM on this machine:

- genuine conversion -> 333,675-byte PDF, gate accepts (control)
- truncated to **exactly 65,536 bytes** - the 2026-08-21 regression shape -
  gate **rejects**: *"the PDF written is incomplete - it has no %%EOF trailer,
  so the converter stopped part-way"*

**Kill the COM server mid-export** (`taskkill /F /PID` the tracked Excel during
`ExportAsFixedFormat` on a 254 KB / 6-sheet workbook):

- conversion returns `(None, "COM Error: (-2147023170, RPC failed)")`
- **the source .xlsx is still on disk** - the user's original was not deleted
- no PDF left at the destination - clean rejection, no stub promoted
- no leftover `EXCEL.EXE`

---

## Area 3 - long paths - **PASS on everything measurable here; one half BLOCKED**

`make_long_path` output shapes, all 9 correct:

| given | produced |
|---|---|
| `C:\Users\x\f.pdf` | `\?\C:\Users\x\f.pdf` |
| `\server\share\f.pdf` | `\?\UNC\server\share\f.pdf` |
| `C:/Users/x/f.pdf` | `\?\C:\Users\x\f.pdf` |
| `//server/share/f.pdf` | `\?\UNC\server\share\f.pdf` |
| `C:\a\.\b\..\c\f.pdf` | `\?\C:\a\c\f.pdf` |
| already-prefixed / device / drive-relative / relative | returned untouched |

**UNC judged by error KIND**, malformed vs well-formed side by side, which is
the discriminator `CLAUDE.md` prescribes:

- malformed `\?\\nosuchhost12345\share\...` -> `errno 22, Invalid argument`
- well-formed `\?\UNC\nosuchhost12345\share\...` -> `errno 2, No such file or directory`

(Python surfaces WinError 123 as EINVAL and 53/ENOENT as errno 2, so the
`winerror` attribute is `None` here - judge on errno, not on the literal 123.)
The probe host contains no underscore, per the note in `CLAUDE.md`.

**Forward slashes**, positive control: the raw prefix + forward-slash form
`exists()` -> `False` (the silent-absence bug) while `make_long_path`'s output
`exists()` -> `True`.

**A real 675-character write** via `make_long_path` succeeds; `stat` reads back 15 bytes.

**A real 454-character Office COM conversion works end to end**: PDF produced at
the long destination, `pdf_looks_real` accepts it (113,007 bytes), source
consumed only after verification. This one is registry-independent - Office COM
has its own ~260 limit and ignores `LongPathsEnabled`, which is why
`office_safe_path` / `office_container_stage` exist.

### BLOCKED - could not test

**Whether any code path has FORGOTTEN `make_long_path`.** Measured directly: an
unprefixed `open()` on a 675-character path **succeeded** on this machine, i.e.
`LongPathsEnabled=1` masks exactly the defect the check is looking for.

- This session is **not elevated** (`BIRKDESKTOP\birkl`, `IsInRole(Administrator)=False`),
  so `HKLM\...\FileSystem\LongPathsEnabled` cannot be set to 0 from here.
- The shipped `dist` exe **does** declare `longPathAware: true`, so it is
  long-path aware - but that only takes effect *with* the registry at 1, so it
  does not substitute for the test.
- Structural coverage that DID run and pass: `test_unc_uses_the_UNC_prefix_form`,
  `test_nothing_hand_rolls_the_prefix`, `test_the_shadow_copy_and_move_back_are_prefixed`,
  `test_what_is_YIELDED_stays_unprefixed`, and the
  `core.sync_manager` / `shared.helpers` agreement test. Those pin the KNOWN
  sites; nothing pins a newly added one.
- A whole-project grep found **no hand-rolled `\?\` prefixes** in app code.

**To close it**: from an elevated prompt set the value to 0, reboot, and re-run a
real download into a destination deep enough to exceed 260 characters.

---

## Area 4 - the Windows DPAPI token fallback - **PASS**

Isolated so the operator's real credential was never touched:
`CANVAS_DL_CONFIG_DIR` sandboxes `.token_fallback`, and `KEYRING_SERVICE` was
patched to `CanvasDownloader__WINAUDIT_SANDBOX`. Both asserted before the probe
would run. Sandbox entries deleted afterwards and confirmed gone; the real
service reads clean.

| check | result |
|---|---|
| `store_token` -> True, Credential Manager holds the token | PASS |
| a SECOND Canvas URL does not evict the first | PASS |
| Credential Manager broken -> `store_token` still True, DPAPI fallback carries it | PASS |
| the on-disk fallback is ciphertext, not the plaintext token | PASS |
| a second account added while keyring is broken - first survives | PASS |
| fallback store unreadable (`OSError`) -> write **declined**, other accounts intact, new one not written | PASS |
| **both** stores broken -> `store_token` returns **False** | PASS |

That last row is the 2026-08-21 rewrite working as documented: the return value
describes the STORED STATE, not one call's return code, which is what makes it
safe for a caller to drop its own copy on True.

---

## Area 5 - the COM-spawned Office leak - **TRIGGER PINNED, and it escalates**

The register carries two open findings on a `EXCEL.EXE` that outlived the whole
2026-08-08 audit (5h54m), both saying the trigger was never identified and that
the leak appeared inside a row *"whose convert_excel toggle was never applied"*.

### The mechanism

`engine/office_pid.find_new_office_pid` returns **the first process of that image
name that is not in the pre-snapshot**. Nothing tests that it is the one we
spawned. `converters/{word,excel,pdf}.py` all use it identically.

Ground truth is available - `Application.Hwnd` -> `GetWindowThreadProcessId`
gives the true pid of OUR instance - so the guess can be checked. Two concurrent
lanes, each dispatching Excel exactly as the app does:

```
laneA: guessed=2448  TRUE=9816   <<< MISATTRIBUTED
laneB: guessed=2448  TRUE=2448   OK

distinct TRUE pids spawned : [2448, 9816]
distinct pids TRACKED      : [2448]
>>> 1 spawned Excel tracked by NOBODY: [9816]
    lanes that would kill the WRONG process: 1
```

That is the whole of the 2026-08-08 observation, and it explains both loose ends:

- *"the app correctly killed every instance it tracked"* - it tracked 2448 twice.
- *"appeared inside m014's window, a row whose convert_excel toggle was never
  applied"* - attribution is **cross-lane**, so the creation time falls in one
  lane's window while a different lane spawned it. **There is no special row.
  The trigger is any two concurrent `_init_app` calls.**

The 5h54m orphan follows: the watchdog fires, kills `_pid` (another lane's
healthy Excel), our genuinely hung one keeps running; `_kill_app` then finds
`Quit()` throwing and `pid_is_process(wrong_pid)` False - so nothing kills it.

### It is NOT harness-only - it reaches a single-instance user

`start.py`'s flock/mutex prevents a second GUI and conversions are sequential
within one instance, so two *app* instances are harness-only. But the race does
not need a second app instance - it needs a second **Office process**, and the
user supplies that themselves.

Measured, single process, no harness:

```
pre-snapshot: []
user's Excel now running: [23236]      <- user opens their own workbook
OUR instance TRUE pid   : 23244
find_new_office_pid says: 23236        <- THE USER'S EXCEL
```

The app adopted the user's own Excel. Consequences, all from existing code paths:

1. `_on_timeout` (`Excel hung >180s`) -> `taskkill /F /PID 23236` - **the user's
   unsaved workbook killed without saving.** This is precisely what
   `engine/office_pid.py`'s docstring says it exists to prevent: *"the legacy
   `taskkill /F /IM EXCEL.EXE` approach kills EVERY running Excel instance,
   including files the user had open. This module tracks the PID of the COM
   instance we spawned so the watchdog timer can target it precisely."* The
   precision is illusory whenever the race occurs.
2. `_kill_app` on a failed `Quit()` - same kill.
3. Our real instance (23244) is tracked by nobody -> it leaks for the session.

`pid_is_process` does not help: it only confirms the pid is *an* `EXCEL.EXE`,
which the user's own process also is.

### Window width, measured per app

| app | snapshot | DispatchEx | find_pid | **window** |
|---|---|---|---|---|
| Excel | 0.002s | 0.503s | 0.002s | **0.506s** |
| Word | 0.002s | 2.340s | 0.002s | **2.344s** |
| PowerPoint | 0.002s | 2.353s | 0.002s | **2.357s** |

Word's is the widest, and Word is where an unsaved essay lives. The window
reopens on every `_init_app` - once per converter per batch, plus once per
`_ensure_app` self-heal, across a conversion phase that can run for minutes
while the user has been told the app is busy.

### Why `Quit()` usually saves it

Driven directly: with `find_new_office_pid` forced to return `None`, an ordinary
convert still leaks nothing, because `Quit()` succeeds on a healthy channel. The
leak needs **a lost/wrong pid AND a failed `Quit()`** - which is exactly the hung
instance the watchdog exists for. That is why it is intermittent rather than
constant.

Also noted: `find_new_office_pid`'s docstring says *"callers must fall back to
`/IM` kill in that case"*. `_kill_app` does not - it does nothing when
`_com_pid` is None - while `_on_timeout` does (`kill_office_pid(_pid or 0, ...)`
falls into the broad `/IM` branch). The two callers disagree about the contract.

### NOT FIXED - deliberately

The fix touches process-killing semantics where a wrong choice destroys the
user's unsaved work, and `CLAUDE.md` records a structurally identical macOS
decision (Office ownership being instance-blind) being deferred for exactly that
reason: *"it deserves its own measured pass."* Recommended direction, in
severity order:

1. **Stop guessing when ambiguous.** If more than one candidate process appears,
   return `None` rather than picking one. Fails safe: no targeted kill.
2. **Then make `None` safe.** `_on_timeout`'s `_pid or 0` currently degrades to
   a broad `/IM` kill, which is *worse* than doing nothing - it kills every
   Excel the user has open. With (1) in place this path becomes reachable more
   often, so the two must land together.
3. **Take ground truth where it exists.** Excel and PowerPoint expose
   `Application.Hwnd`; `GetWindowThreadProcessId` then gives the true pid
   exactly, no heuristic. Word's `Application` has no `Hwnd` (only
   `ActiveWindow.Hwnd`, which needs an open document), so Word would still need
   (1) + (2).

---

## Smoke test - the app itself on Windows - **PASS**

Not one of the six areas, but "safe to ship" needs the thing to start. Run with
`CANVAS_DL_CONFIG_DIR` pointed at a temp dir, so the operator's real state was
never touched.

Leftover-harness trap honoured: before launching, **0** python processes and
**0** listeners on 8501-8620. After launching, port 8577's owner was confirmed
to be PID 33452 with my exact command line.

| | |
|---|---|
| `/_stcore/health` | 200 in 1s (binds early - not a readiness signal, per `CLAUDE.md`) |
| page title | `Canvas Downloader` |
| `stException` count | **0** |
| console errors | **0** (11 warnings, all Streamlit boilerplate: unrecognised permissions-policy features, and the same-origin `components.html` sandbox notice these JS bridges rely on by design) |
| `window.prerenderReady` | `true` |
| element containers | 24 |
| institution picker | 4,757 rows / 211 KB payload; `kobenhavn` -> Københavns Universitet, `erhvervsakademi` -> Erhvervsakademi Aarhus, `copenhagen business` -> CBS, `harvard` -> Harvard University |

An isolated config dir means no saved session, so it correctly degraded to the
login page rather than erroring - the "a persistence failure must never block a
login" rule, observed.

---

## Area 6 - full matrix - **NOT RUN**

Stated rather than omitted. Machine had **14.45 GB free of 31.91 GB total** at
session start, which is more headroom than the 13.9 GB box that produced the
2026-08-08 cascade, so RAM was not the reason.

It was not run because a multi-lane matrix cannot produce trustworthy **Office**
rows right now, and Office is precisely what Windows most needs measured:

- `fp:37cb30ec4fa7` (ownership is instance-blind) already blocks it, with
  "run the converting lane alone" as the standing workaround;
- the finding above adds a second, independent contamination path in the same
  area - cross-lane PID misattribution - so a multi-lane run would generate
  Office failures that then need isolation re-runs plus an unchanged control row
  to adjudicate, which is more work than the fix.

The brief ranks pinning the Excel trigger above "another clean matrix". That is
done, and it is a better result than a matrix would have produced.

**Residual risk this leaves open**: nothing here exercised a real Canvas
download or sync end to end on Windows. Every engine result above is from
driving real product code against real local files, not from a live course.

---

## Teardown

`EXCEL.EXE` / `WINWORD.EXE` / `POWERPNT.EXE` after every probe and after the
smoke test: **none running**. No `/automation -Embedding` orphan was produced by
any measurement in this session - consistent with the mechanism above, since
every probe ran a single instance with a healthy `Quit()`.

---

## Verdict

**v2.0.2 is safe to ship on Windows**, with one finding the operator should
decide on first.

Verified working on this platform: the conservation/path layer including
case-only renames and junction-reached course roots; the PDF trailer gate,
including that killing the COM server mid-export keeps the user's original and
promotes no stub; long-path handling for every shape and a real 454-character
Office conversion; the DPAPI token fallback in all seven states including
multi-account preservation and decline-on-unreadable; and the app itself booting
clean with 0 exceptions.

**Residual risk I could not close, in order:**

1. **The Office PID misattribution (new, `fp:a41c7e0b93d2`).** Not a v2.0.2
   regression - the primitive is older - but it is now known to be reachable by
   an ordinary single-instance user and to cost them unsaved work. It is
   narrow (needs a hung Office instance *and* a second Office process inside a
   0.5-2.4s window) which is why it presents as rare. I did not fix it because
   the fix decides which process gets force-killed, and the two halves must land
   together or the `/IM` fallback makes it worse.
2. **Whether any code path forgot `make_long_path`** - untestable at
   `LongPathsEnabled=1`, and this session is not elevated. Needs the registry at
   0 plus a reboot and a deep-destination download.
3. **No live Canvas download or sync was run on Windows.** The engine is
   verified against real local files and real COM, not against a real course.
4. **9 suite failures are macOS-shaped tests, not product defects** - but they
   mean the Windows suite is not green, so a future regression in
   `test_conversion_repoint_spelling.py` would land in an already-red file.

# Live audit - 2026-08-21 (run `20260821_213837_windows-small-transcription`)

Closes the biggest gap in the offline pass above: no live Canvas download or
sync had been run on Windows.

**Credential handling**: the operator's token was seeded as a **DPAPI-encrypted
`.token_fallback` inside the run's isolated config dir**, never
`keyring.set_password`. The app's restore order is keyring ->
`_load_fallback_token(config_dir)`, and this account had no keyring entry for
the URL, so the fallback is what signs it in. Verified: round-trips, is
ciphertext not plaintext on disk, the global Credential Manager entry is still
absent, and `.gitignore:112` (`_audit_runs/**/config/*`) means it cannot be
committed - `git add -An` on the run dir offers exactly one file, `run.json`.
O5 used `CANVAS_DL_AUDIT_TOKEN` from the environment, which persists nothing.

Ground truth (O5) taken for all three courses BEFORE any download:

| course | files tab | module files | expected ids | modules |
|---|---|---|---|---|
| 43667 | 0 | 0 | 0 | 1 |
| 43665 | 403-restricted | 121 | 121 | 16 |
| 43660 | 140 (889.8 MB) | 97 | 143 | 28 |

## Row 1 - smoke, 43667 - **PASS**

`flow download r1_smoke --courses 43667`. Terminal state "Download Complete!",
1 course / 1 file / 0 MB / URL 1, **0 exceptions**. The whole Windows pipeline
works end to end: isolated app start (`verified_owner: true`), sign-in from the
DPAPI fallback, course select, config, scan, download, completion screen.

### A false finding I produced myself - recorded, not filed

The crosscheck reported **MEDIUM `Completion screen shows 1 but 41 files were
saved`** (O1 vs O2). It is **invalid, and the cause was me**: I ran the row-1
crosscheck while row 2 was still downloading into the same run, and `--log`
defaults to the shared **batch** log, so the check counted row 2's in-flight
files against row 1's completion screen.

Disproving evidence: the row-1 course folder holds **exactly 1 file**, matching
its completion screen, while the concurrently-downloading 43665 folder held 126
at that moment.

**Rule for this harness: do not crosscheck a row while another row is writing
to the same batch log.** Same family as the contamination lessons already in
`RUNBOOK.md` - and a reminder that "a correlation can confirm a contaminating
cause but can never establish that something is genuine".

Two other row-1 findings, both INFO and both expected: a manifest row describing
a file a converter consumed (the engine's documented bypass), and *"Debug log
parser missed 57% of lines"* - the audit's own O2 oracle, worth attention given
`CLAUDE.md`'s rule that a blind oracle does not under-report, it INVENTS.
