# Laptop session, 2026-08-21 - the long-path gate

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
