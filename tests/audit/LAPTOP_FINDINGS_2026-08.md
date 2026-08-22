# Laptop session, 2026-08-21 - the long-path gate

> **UPDATE 2026-08-22 - THE GATE IS RESTORED AND THE CONVERTER FINDING IS
> NOW MEASURED.** The operator set `LongPathsEnabled=0` and rebooted, so areas
> 2 and 3 below are superseded as a statement about *today*. They are kept
> verbatim, because they are the record of what was true when measured and of
> why the gate could not run. **Read area 4 first.**

Written by the laptop agent briefed in `tests/audit/LAPTOP_LONGPATH_PROMPT.md`.
Machine: `LAPTOP-KE2TQ36T`, ASUS ExpertBook L1500CDA, `PCSystemType 2` (mobile),
battery present, 4 logical cores, **13.9 GB RAM (3.8 GB free at the time)**.
Windows 11 26200.

**Headline: the gate could not be run, because this machine can no longer fail.**
`LongPathsEnabled` is `1` here. Details in area 2. Job 1 (scrub and commit this
machine's audit runs) is complete, and it turned up a real defect of its own.

---

## Area 1 - Job 1: the audit runs are scrubbed, verified and committed

Committed as `f7d64ab`, pushed to `main`.

**What was there.** 133 local run directories dating 2026-07-27 to 2026-08-08 -
older than the run layout the 2026-08-21 ignore rules were written against, which
is exactly the case trap 5 of the brief exists to catch. **The shapes were
clean**: no `browser-profile/`, no `downloads/` beyond `debug_log.txt`, no
`config/` beyond `diagnostics/`, no course material. `git check-ignore` was
confirmed live for the token fallback (`.gitignore:112`), the browser profile
(`:111`) and course downloads (`:109`).

**What was redacted.** 47 Panopto unified logins and 46 Canvas login IDs across
33 files. **Zero emails, tokens, JWTs or bearer tokens.** That zero is worth
something only because the pattern set was positive-controlled first: a synthetic
`jane.doe@example.ac.uk` *does* get redacted, so the empty email count is a
measurement rather than a scanner that had quietly stopped working.

All 33 files were among this machine's **untracked** runs - zero tracked files
changed, so the desktop's committed 5,387 were already clean.

**How it was verified.** Against the **index**, not the working tree, since the
index is what gets published: an independent scanner over all 6,764 staged blobs,
with its own patterns, its own file list, and every suffix including binaries.
Result: nothing. Its positive control matched 6,293 blobs, so its "none" can say
yes. Seven email-shaped strings appear in `git show HEAD` and all seven
reconcile - two are git metadata (author, co-author trailer), two are the diff's
`+` prefix making `+@pytest.fixture` look like an address, and three are synthetic
literals in the test file added by this session.

### 1a. THE SCRUBBER WAS BLIND TO 46 OF ITS OWN IN-SCOPE FILES

Found while reconciling a suffix census against the scrubber's own file count.

`git ls-files` C-quotes any path holding a non-ASCII byte, and `core.quotepath`
is unset (defaults to true). A course folder named `...små systemer...` therefore
came back as `"..._audit_runs/.../seed_...sm\303\245 systemer....json"`. The
scrubber built `REPO / line.strip()` from that, `Path.is_file()` answered
**False**, and the entry was dropped by the filter **in silence**.

The arithmetic closes exactly: 6,764 staged blobs - 6,677 the scrubber saw = 87,
being the 41 binaries it correctly excludes by suffix plus these **46 quoted
paths**. 37 of the 46 were in-scope text types it was supposed to open.

It fails in the worst available direction for a privacy tool: **the report says
CLEAN for a file it never opened.** Every Danish course name in this operator's
runs hits it, so on this repo it is not an edge case.

- **Fix**: read the list NUL-delimited (`git ls-files -z`, bytes not `text=True`),
  which git does not quote. Coverage went 6,677 -> 6,714 files; a re-run over the
  now-complete set is still clean, so nothing was actually exposed.
- **Control, both directions, in a throwaway repo**: the pre-fix form sees only
  the ASCII sibling, the fixed form sees both. The ASCII sibling is the control -
  without it, a scanner that reached nothing at all would have "passed".
- **Pinned** by `tests/test_scrub_audit_pii.py` (11 tests), which asserts REACH as
  well as redaction, because reach is the half that fails silently. The regression
  test was confirmed to FAIL against the pre-fix code, restoring from an in-memory
  snapshot rather than `git checkout`, since a second session may be in this tree.

---

## Area 2 - Job 2 is BLOCKED: this machine can no longer fail

The brief's premise was that this laptop sits at the Windows default, which is
what makes a forgotten `make_long_path` detectable here. It does not, any more.

```
registry LongPathsEnabled : 1
python.exe longPathAware  : present
```

Both conditions for long-path support are satisfied, so the registry reading is
not the whole story - it was confirmed empirically, which is what the brief asks
for:

| probe | result |
|---|---|
| target path built from real directories | **321 characters** |
| `open(str(target), "wb")` - **no prefix** | **SUCCEEDED**, wrote normally |
| `open(make_long_path(target), "wb")` | SUCCEEDED |

**The unprefixed open succeeds.** Per the brief: *"If the unprefixed open
succeeds, long paths are enabled somewhere and your whole run proves nothing."*
A code path that forgot `make_long_path` cannot fail on this machine, so any
download, sync, Office, Panopto or archive row run here would be a **masked
pass** - the same result the desktop already produced, at the cost of a day.

I did not change the registry. It needs administrator rights and a reboot, it is
the operator's own machine, and the reboot would end this session. **That is the
one decision worth taking back to them**, because it is the only thing that
restores the fleet's ability to detect this class at all.

### Why this matters beyond one blocked job

`CLAUDE.md` records **two** long-path defects that survived precisely because a
dev box had this enabled (`office_safe_path`'s own I/O, and the
`panopto/transcribe.py` `.part` delete), and in both cases the stated remedy was
*"when a path-length fix cannot be reproduced, check that registry key first."*
The implicit mitigation was that some machine in the fleet still had it off.

**As of today, no known machine does.** The desktop has it on; this laptop now
has it on; macOS has no such concept (`make_long_path` is a documented no-op
there, and macOS caps at `PATH_MAX` 1024 with no escape hatch). So this class is
currently **undetectable by running the product anywhere.**

---

## Area 3 - what I did instead: a static sweep for the same question

The dynamic gate asks *"has some code path forgotten `make_long_path`?"* That
question can also be asked of the **source**, which answers on any machine - the
same move this repo already makes with `tests/test_unbound_names.py`.

An AST scan for filesystem calls whose path expression never passes through
`make_long_path` / `office_safe_path` returns **329 raw hits**, which is far too
many to all be real: most are config-dir, temp or app-owned paths that are short
by construction. **Provenance analysis is what this instrument lacks**, so the
raw number should not be quoted as a defect count.

The subset that is worth a dynamic run is the delete family from `CLAUDE.md`,
because those operate on **course-folder paths** - arbitrary depth under a root
the user chooses - and delete the file they converted from:

| converter | unprefixed FS calls | uses `make_long_path` |
|---|---|---|
| `converters/pdf.py`   | 1 | **no** |
| `converters/word.py`  | 0 | **no** |
| `converters/code.py`  | 3 | **no** |
| `converters/md.py`    | 3 | **no** |
| `converters/url.py`   | 4 | **no** |
| `converters/video.py` | 0 (3 `unlink`) | **no** |
| `converters/excel.py` | 3 | yes |
| `converters/archive.py` | 2 | yes |

`pdf.py` and `word.py` are partly covered in practice by `office_container_stage`,
which stages to a short `src_<hex>` path; `code.py`, `md.py`, `url.py` and
`video.py` have no such staging.

**Predicted behaviour at `LongPathsEnabled=0`, from reading the code - NOT
measured, because this machine cannot produce it.** `converters/code.py` reads at
line 44, writes, verifies `exists()` + `st_size`, and only then unlinks the
source. An over-long path raises at the *read*, so the outer `except Exception`
logs and returns `None` with the source intact. **The ordering is fail-safe** -
the delete-family discipline working as designed - so the expected symptom is not
data loss but:

- files in deeply-nested course folders **silently never convert**; and
- the logged reason is `[Errno 2] No such file or directory` about a file that is
  plainly there, which is actively misleading for diagnosis.

`converters/video.py`'s three `Path(...).unlink(missing_ok=True)` sites are the
ones I would point a dynamic run at first, because `missing_ok=True` swallows
`FileNotFoundError`, and `CLAUDE.md` records that an over-long path surfaces as
exactly that - the mechanism behind the `transcribe.py` `.part` leak ("no
removal, no retry, **no log**"). Here the consequence looks like a kept original
video plus an untracked file rather than data loss, but **I could not confirm
severity or even reachability**, and that is the point: confirming it needs the
machine that can fail.

Treat this table as **where to point the next dynamic run**, not as a findings
list. Nothing in it is confirmed.

---

## What I could not close

- **The long-path gate itself.** Unrunnable here. Steps 2, 3 and 4 of the brief
  (deep-destination download, Office/Panopto/archive at long paths, sync with
  `--select updated_modified,deleted_locally`) were **not attempted**, because
  running them would have produced a clean result that means nothing - and a
  recorded false pass is worse than a recorded gap.
- **Severity and reachability of the area-3 candidates.** Static only.
- **The 8 GB / 4-lane RAM caveat in the brief** is stale for this machine: it has
  13.9 GB. Untested, since no lanes were run.

## Verdict

**Does long-path handling hold at `LongPathsEnabled=0`? UNKNOWN - and it is now
unknown everywhere.** This laptop, the last machine expected to be at the Windows
default, is at `LongPathsEnabled=1`, an unprefixed 321-character `open()`
succeeds here, and no other machine in the fleet can fail either. The question
needs either that registry value turned off on one machine (administrator plus a
reboot, the operator's call) or a static guard promoted into the test suite; a
static sweep meanwhile names the delete-family converters as the place to look
first.

---

## Handoff - restoring the gate and re-running it

Decided 2026-08-21: the operator will turn the registry key off rather than have
the class covered statically. Everything below is what a later session needs so
it does not re-derive this.

**1. Restore the machine's ability to fail** (administrator, then REBOOT - the
value is read at process start, so a running shell will not pick it up):

```
reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 0 /f
```

Likely cause of it being on in the first place: the Python installer and Git for
Windows both offer to enable long paths during setup, so **re-check this key
after any Python or Git upgrade on this machine** - otherwise the gate silently
goes back to producing masked passes.

**2. Re-take the positive control BEFORE running anything.** It is the whole
premise, and it is two lines:

```python
open(str(long_path), "wb")               # MUST raise - path > 260 chars
open(make_long_path(long_path), "wb")    # must succeed
```

If the unprefixed open succeeds, stop: the registry did not take (reboot?) and
every row after that is worthless. Reference implementation and the exact fixture
used here is in this session's scratchpad script `probe_longpath.py`; it builds
the deep tree WITH the prefix so fixture creation cannot itself be the failure.

**3. Point the run at area 3's table first**, in this order:

- `converters/video.py` - three `Path(...).unlink(missing_ok=True)` sites. Most
  likely to hide a failure, because `missing_ok=True` swallows the
  `FileNotFoundError` an over-long path raises.
- `converters/code.py`, `md.py`, `url.py` - read/write/delete on course-folder
  paths with no prefix and no staging.
- Then the brief's steps 2 to 4 as written (deep-destination download reconciled
  O5 vs O3 vs O4, Panopto `.part` sweep with `url+mp3+txt+srt` and mp4 OFF, and
  sync with `--select updated_modified,deleted_locally`).

**4. Housekeeping already done here, do not repeat**: this machine's 133 audit
runs are scrubbed and committed (`f7d64ab`), and `_audit_runs/` is in this
clone's `.git/info/exclude`, so a new run will not stage 3,000+ files. That
exclude is local and uncommitted - it will not exist on a fresh clone.

---

## Area 4 - 2026-08-22: the gate is restored, and area 3 is now MEASURED

The operator set `LongPathsEnabled=0` and rebooted. Confirmed: the registry reads
`0x0`, and `LastBootUpTime` is 2026-08-22 00:04:01 - the reboot matters, because
the value is read at process start and a running shell keeps the old behaviour.

**This laptop is once again the only machine in the fleet that can fail.**

### 4a. The check is now a tracked script

`probe_longpath.py` lived in a session scratchpad, which dies with the session -
and `CLAUDE.md`'s own rule is never to leave the only copy there. It is now
`scripts/check_longpath_gate.py`, and there is exactly one of it.

```
$ python scripts/check_longpath_gate.py
platform                  : win32
registry LongPathsEnabled : 0
probe path length         : 351 chars
open() WITHOUT the prefix : FAILED (FileNotFoundError errno=2 winerror=None)
open() WITH make_long_path: SUCCEEDED (read successfully)

VALID - an unprefixed open at 351 characters failed while the prefixed open
succeeded. This machine enforces MAX_PATH, so a forgotten make_long_path will
show up as a real failure.                                            [exit 0]
```

**Note the error class: `FileNotFoundError`.** Windows reports an over-long path
as ERROR_PATH_NOT_FOUND, so Python raises the same exception as a genuinely
missing file. That single fact is the root of this whole defect family - it is
why `unlink(missing_ok=True)` swallows it, and why `except FileNotFoundError`
handlers read "too long" as "already gone".

Design points, each of which is load-bearing rather than decoration:

- **The fixture is built THROUGH the prefix.** Built the same unprefixed way it
  is probed, the *creation* would fail on an enforcing machine, the file would
  genuinely not exist, and the unprefixed open would raise for the wrong reason -
  reporting a working gate on evidence that only proves `mkdir` failed.
- **The prefixed open is a CONTROL, and the verdict checks it FIRST.** Without
  it, "unprefixed raised" is equally explained by a missing file, a permissions
  problem or a full disk. A failed control returns INCONCLUSIVE, never a verdict.
- **Exit 1 when masked**, so a CI step or a shell guard cannot sail past it;
  exit 2 inconclusive; exit 0 only for valid, or a clean not-applicable off
  Windows (`make_long_path` is a documented no-op there and macOS has no
  MAX_PATH to mask).
- **`--self-test` ships with it**, because a check that can only ever say PASS
  proves nothing. It drives `verdict()` to all three answers and takes a live
  control showing a SHORT path really does open unprefixed - the same
  observation the MASKED branch keys on.

Pinned by `tests/test_longpath_gate_check.py` (8 tests, 1 skipped off-platform).
Control: mutating `verdict()` so it can never return MASKED fails two of them.
Restored from an in-memory snapshot, not `git checkout`.

### 4b. Area 3's converters, measured - and the severity assessment HOLDS

Driven against the real converter functions, fixtures created through
`make_long_path` so a failure can only be about the converter's own I/O:

| converter | path | result | source file |
|---|---|---|---|
| `convert_code_to_txt` | 318 | `None`, logged `[Errno 2] No such file or directory` | **survived** |
| `convert_html_to_md` | 349 | `None`, logged `Invalid HTML file path` | **survived** |
| `compile_urls_to_txt` | 360 | `(None, [])`, **logged nothing at all** | **survived** |
| `unlink(missing_ok=True)` | 323 | returned normally, **deleted nothing** | n/a |

Every prediction in area 3 held, and so does the judgement that came with it:
**all four fail SAFE. The user's source survived in every case.** This is
degradation and misdiagnosis, not data loss, and it should not be escalated
beyond that.

What the measurement adds:

- **`compile_urls_to_txt` is the worst to diagnose**, which reading the code did
  not predict. It logs *nothing*: the glob simply matches no `.url` files, so the
  course silently compiles no links and reports success at compiling zero.
- **`convert_html_to_md` fails at an `exists()` check** before it opens anything,
  and says `Invalid HTML file path` - about a path that is perfectly valid.
- **The `video.py` mechanism is confirmed outright.** A real 323-character file,
  `unlink(missing_ok=True)`, returned normally and deleted nothing; the identical
  call at a short path deletes correctly, so the no-op is about length and not
  about the call.

The user-visible symptom on a default Windows install is therefore: **files in
deeply-nested course folders silently never convert**, and the reason given is
either a file-not-found error about a file that is plainly there, or nothing.

**Still open - nothing was fixed.** The remedy is `make_long_path` at those call
sites. Not applied here because the operator had not asked for it, and a fix to
the delete family deserves its own pass with the reproduce-fix-test-mutate cycle
this repo runs on - which this machine can now actually complete.

---

## Area 5 - 2026-08-22: the long-path defect CLUSTER, and the audit of the fix

Area 4 closed with the converters as "still open, nothing was fixed". Fixing
them turned out to require fixing four other layers first, because each one was
masking the next - the only way to find them was to fix one and re-run.

### 5a. Five layers, and why they hid each other

| # | layer | sites | effect at depth |
|---|---|---|---|
| 0 | `mkdir` | 10 | **crash, 0 files** - the download died before its own long-path-safe writes could run |
| 1 | discovery | 4 | `_glob_files` returned `[]`, starving all nine converters at once, SILENTLY |
| 2 | converter I/O | 14 | conversions fail per file; `url.py` logged nothing at all |
| 3 | the run LEDGER | 2 | conversions ran but were scoped to nothing |
| 4 | engine predicates | 49 | overwrite, re-download, and **lost edit protection** |
| 5 | UI + daily sync | 24 | amber "folder missing" on a folder that is right there |

**The measurement that pinned layer 3 is the transferable one.** After layers
0-2 were fixed the download succeeded (123 files) and still converted almost
nothing. Discovery was provably working - 50 Excel, 22 PowerPoint, 2 URL found
at 266-270 characters. The LEDGER that scopes post-processing was built with an
unprefixed `exists()`, and of **124 files exactly 1 passed it** (`FK.pdf`, 257
chars) - which is precisely the one file the debug log shows being converted.
Log, disk and mechanism agreed to the file.

**Two findings are worse than the original crash**, both in layer 4:

* `sync/execution.py` - `if is_update_modified and filepath.exists():`. At depth
  that is False, so the `_NewVersion` diversion never fires and the download
  **overwrites the student's edited file**. The app's headline promise, failing
  silently.
* `compute_local_md5` returned `""` for any file past 260 characters. That value
  is the whole basis of edit protection, and `""` means MISSING - a different
  verdict from unreadable.

Plus `core/auto_sync.resolve_today_pairs`, which dropped deep folders, so **the
daily sync silently skipped those courses** - the run nobody watches.

### 5b. `walk_files_long` - and why a prefixed `os.walk` is the wrong fix

`shared/helpers.walk_files_long` walks THROUGH the prefix and yields CLEAN
paths. The clean half is not tidiness: the manifest walks feed `_path_key`,
which compares against stored rows, so a leaked `\?\` would have mismatched
every one of them - a "fix" that looks right and quietly corrupts the manifest.

### 5c. THE ADVERSARIAL AUDIT OF THE FIX ITSELF

25 checks written to BREAK the fix, not confirm it. Three results worth keeping:

1. **`mkdir(parents=True)` through the prefix was an untested assumption under
   all 10 mkdir fixes.** pathlib builds parents by walking `.parent`, and the
   prefix changes what that yields near the drive root. Measured: full chain at
   300 chars from a root with no existing parent, idempotent, and a file can be
   written inside it. It holds - but nothing had checked.
2. **A finding of mine was DISPROVED by measuring it.** `panopto/transcribe.py`
   reads its source mp3 unprefixed while every write in that module is
   prefixed - the exact asymmetry this repo keeps hitting, and I was about to
   patch it. A real mp3 at **304 characters decodes fine**: `decode_audio` hands
   the path to **ffmpeg as a subprocess argument**, and ffmpeg is a separate
   process, so Python's MAX_PATH enforcement never applies. **A path handed to a
   subprocess is that subprocess's problem** - which is also why Office COM
   paths must stay UNPREFIXED (COM rejects the prefix; `office_safe_path` stages
   instead). Verified afterwards that no subprocess argument was wrongly
   prefixed.
3. **The 16 mkdir sites deliberately NOT patched were measured, not assumed.**
   With a 104-character username (the Windows maximum) the config-dir tree tops
   out at **180 chars**, under both limits. Patching them would be churn - and
   churn is how four of my own bugs got introduced today.

**Prefix leakage is the one bug the FIX can introduce**, so it is pinned by a
test: exactly 5 sites bind a prefixed path, each with a recorded reason.

### 5d. Four of my own edits were caught by existing guards

Recorded because it is the system working, and because each is a repeat of a
class this file already documents:

* `test_unbound_names` caught a `NameError` I introduced in `converters/excel.py`
  (module-level `make_long_path` missing).
* The crash-vector census caught me replacing `code.py`'s content gate with a
  spelling it could not recognise. The right fix was the shared
  `file_has_content` - better than what I had written.
* I patched `converters/archive.py` where it was **already correct**
  (`extract_dir` is rebound to the prefixed form upstream) and had to revert.
* I broke `core/auto_sync.py`'s syntax by inserting an import at column 0 after
  an INDENTED anchor.

**Five brittle test anchors** reported live guards as missing after the renames -
including the `_NewVersion` route and the iCloud contract. All re-anchored on the
PROPERTY rather than the spelling. The iCloud test is now stronger than before:
enumeration moved into a helper, so it follows it there.
