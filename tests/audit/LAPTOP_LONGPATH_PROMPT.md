# Laptop agent brief - the long-path gate, and cleaning that machine's audit runs

Paste everything below the line into a fresh agent session **on the laptop**, in
a clone of `BrkBuilds/Canvas-Downloader` at `main`.

Written 2026-08-21 by the Windows verification session on the desktop. That
session closed every Windows question **except one**, and this machine is the
only one that can answer it.

---

You have two jobs, in this order. The first protects the operator's privacy and
must be finished before the second, because the second creates more artifacts.

## Why you specifically

This laptop has **`LongPathsEnabled` at the Windows default**, and that single
registry value is the whole reason you exist for this task. The desktop that ran
the main Windows audit has it set to `1`, which **masks** the entire class of
defect being hunted: an unprefixed `open()` on a 675-character path *succeeded*
there, so a code path that forgot `make_long_path` is undetectable on that
machine. `CLAUDE.md` records two separate long-path defects that survived
precisely because a dev box had this enabled.

**This laptop is not powerful: 8 GB RAM, and a previous audit here crashed with
4 lanes.** Use **one lane**, always. Never `--lanes 2` or more. Measure free RAM
before you start and state it in your report; if Office rows start timing out,
suspect memory pressure before suspecting the product - the desktop audit
recorded Excel COM hanging 180s per workbook under exactly that condition, and a
controlled re-run later logged zero timeouts.

## Read first

1. `CLAUDE.md` - search it for `long path`, `LongPathsEnabled`, `office_safe_path`
   and `make_long_path` before investigating anything. Most of what you are about
   to wonder is answered there with the measurement that settled it.
2. `tests/audit/WINDOWS_FINDINGS_2026-08.md` - the desktop session's results.
   Its area 3 tells you exactly what is already proven and what is not.
3. `tests/audit/RUNBOOK.md` - the five oracles and the long "do NOT report" list.
4. `tests/audit/AUDIT_FINDINGS.md` - the register.

---

# JOB 1 - clean this machine's audit runs, then commit them

This laptop has audit-run files from an earlier local audit that are now in
commit scope (the policy changed: runs are tracked for their RESULT). They have
never been scrubbed. **The app is driven against a REAL Canvas account, so those
artifacts carry the operator's identity and, on at least one run, third-party
email addresses belonging to other people.**

```bash
git pull --ff-only
python scripts/scrub_audit_pii.py --check     # report only, exit 1 if dirty
python scripts/scrub_audit_pii.py             # redact in place
python scripts/scrub_audit_pii.py --check     # must now say CLEAN (idempotent)
```

### Four traps that were hit for real on the desktop. Do not re-learn them.

**1. THE ORDERING TRAP - this one nearly published real emails.**
If anything staged those files *before* you scrubbed (an IDE's git integration
is the usual culprit - Antigravity IDE ran `git add -A` unprompted on the
desktop), then the **index still holds the unscrubbed blobs** while the working
tree looks clean. Committing then publishes them.

```bash
git add -- _audit_runs        # ALWAYS re-stage after scrubbing
```

**2. Verify the staged BLOBS, not the working tree.** The scrubber's own
"CLEAN" is about the working tree. What gets published is the index:

```bash
git show ":<path>" | grep -cE "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
```

Do that across every staged text blob, not one sample.

**3. Every PII scan needs a POSITIVE CONTROL.** `CLAUDE.md` records a scan that
returned CLEAN only because `xargs` escaping had broken it. Before believing any
"no hits", make the same scanner find something you know is present (e.g. count
blobs containing the word `Canvas`). If it cannot say YES, its NO is worthless.

**4. Never `git add -A` blind.** Scope every git command to your own paths.
Check `git status` after staging documentation - an ignored path simply will not
appear, and `git add` on it is a silent no-op.

### What must never be committed

`.gitignore:112` (`_audit_runs/**/config/*`) is what keeps a stored Canvas token
out of the repo. Confirm it still holds on this machine before committing:

```bash
git check-ignore -v _audit_runs/<run>/config/.token_fallback
```

Also confirm nothing token-shaped is in your commit:
`git show <sha> | grep -cE "[0-9]{4,5}~[A-Za-z0-9]{20,}"` must be `0`.

Then commit and push. Say in the message what was redacted and how you verified
it (blob scan + control), not just "scrubbed".

---

# JOB 2 - the long-path gate

## Step 0 - PROVE the machine can fail. Do this first or everything after is worthless.

```powershell
reg query "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled
```

Expect `0x0` or **absent** (absent means 0). If it is `1`, **stop and tell the
operator** - this machine has lost the property that makes it useful, and you
would produce the same masked pass the desktop did.

Then take the **positive control**, which is the single most important command
in this brief:

```python
# build a path over 260 chars, then open it WITHOUT the prefix
open(str(long_path), "wb")     # MUST raise OSError / FileNotFoundError
open(make_long_path(long_path), "wb")   # must succeed
```

If the unprefixed open **succeeds**, long paths are enabled somewhere (the
process manifest plus the registry are both required, and `python.exe` ships
`longPathAware`) and your whole run proves nothing. Say so and stop.

Record both results in your report. A clean result is only worth something if it
says what would have made it dirty.

## Step 1 - what is already proven, so do not re-derive it

The desktop verified all of this and the macOS session swept it independently:

- `make_long_path` gets all shapes right - UNC -> `\\?\UNC\...`, forward slashes
  normalised, dot segments resolved, drive-relative root correctly left alone,
  already-prefixed and device paths untouched, idempotent.
- UNC judged by error KIND: malformed gives `errno 22` (EINVAL, i.e. WinError
  123 "syntax is incorrect"), well-formed gives `errno 2`. **The probe hostname
  must contain no underscore** - an underscore is illegal in a hostname and
  Windows returns the very 123 the test reads as failure.
- `core/sync_manager`'s wrapper agrees with the shared one on 9/9 probes.
- `office_safe_path` yields UNPREFIXED paths while using the prefix for its own
  I/O - that asymmetry is the entire point of it.
- Nothing hand-rolls the prefix outside `make_long_path`.

**Your job is the opposite question**, and it is the one no test asks: *has some
code path forgotten `make_long_path` altogether?* At `LongPathsEnabled=1` that
is invisible. Here it fails loudly.

## Step 2 - a real download into a deep destination

Set a download destination deep enough that real Canvas files land past 260
characters. The desktop run saw 59, 8 and 64 over-255 paths naturally on courses
`43665`, `43660` and a sync - so you do not need anything exotic, just a deep
root.

**The failure mode you are hunting is a SILENTLY MISSING FILE, not an error.**
So do not read the completion screen and stop. Reconcile:

- **O5** (`python -m tests.audit canvas snapshot <id>`) - taken BEFORE the
  download - says how many files Canvas has.
- **O3** - count what actually landed on disk.
- **O4** - manifest rows.

A gap between them at a long path is the finding. `check download` will do this
for you; run it, and read the over-255 INFO note as *confirmation the guard was
exercised*, which is how the desktop run read it.

## Step 3 - the paths most likely to have forgotten the prefix

Ranked by evidence, not by guesswork. `CLAUDE.md` records each of these having
had a long-path defect at some point:

1. **Office conversion at a long path.** `office_safe_path`'s own I/O was
   long-path-unsafe once, and it is *for* long paths. Convert real `.doc`/`.xls`/
   `.ppt` at a deep destination and confirm the PDF appears **and the source is
   deleted only after it verifies**.
2. **`panopto/transcribe.py`'s `.part` sweep.** Every WRITE went through
   `make_long_path` and the **DELETE did not** - which fails as
   `FileNotFoundError`, read by the retry loop as "already gone": no removal, no
   retry, **no log**. Run a Panopto row with `txt`/`srt` at a long path and
   confirm **zero `.part` files remain**. The desktop measured 259 paths over 255
   characters in one course with the abandoned sidecars at 341.
3. **`converters/archive.py`** - had a hand-rolled `'\\?\' + path` once. Extract
   a zip at a deep destination.
4. **Sync at a long path**: analyze, heal, and the `_NewVersion` fork. Seed with
   `python -m tests.audit seed apply <folder> --kinds long_path,readonly_target,edited_update`
   and sync with `--select updated_modified,deleted_locally` (those two are
   unchecked by default, so without them the fork and restore paths never run).

## Step 4 - Panopto, sized for 8 GB

If you run a Panopto row: **turn `mp4` OFF**. macOS already proved that muxer
path end to end, and the runbook's measured data shows mp4 is where the bulk of
a Panopto row's cost sits. `url + mp3 + txt + srt` exercises the sidecar routing
and the `.part` sweep, which is what you actually need.

Check which Whisper model is installed **before** starting - if the configured
model is absent the app may want a multi-GB download mid-run. On the desktop the
run was configured for `tiny` on `cuda`; on this laptop it may be CPU, which is
much slower. A handful of recordings proves the routing and the sweep; 36 proves
nothing extra.

---

# Reporting

For each step: what you ran, what you measured, and **pass / fail / could not
test**, with "could not test" spelled out rather than quietly omitted.

Write findings to `tests/audit/AUDIT_FINDINGS.md` (append-only, one entry per
finding, never rewrite an existing one) and narrative to a **new** file,
`tests/audit/LAPTOP_FINDINGS_2026-08.md`, which nobody else will touch.

**Do not edit `CLAUDE.md`, `tests/audit/RUNBOOK.md` or
`tests/audit/MAC_RUNBOOK.md`** - other sessions may be in them. If something
belongs there, hand the operator the text.

End with one explicit sentence: **does the long-path handling hold at
`LongPathsEnabled=0`, and what could you not close?**

## Things that will waste your time if nobody tells you

- **A leftover harness can impersonate the app.** Stale Streamlit processes once
  answered a health check on the port the app failed to bind, and it read exactly
  like a clean boot. Always confirm the listening PID is yours.
- **`/_stcore/health` answers as soon as tornado BINDS**, long before the app can
  render. It is not a readiness signal.
- **A brittle test anchor reads like a missing guard.** Three times in this repo,
  documenting a fix moved a line and an adjacency-matching test then reported a
  live guard as absent. Resolve through the AST before concluding a guard is gone.
- **"No log line" is not "it did not happen."** An unlogged destructive action
  cost a session an hour of misattribution.
- **Correlation can confirm a contaminating cause but never establishes that
  something is genuine.** Only re-running a case in isolation promotes a finding
  to real - and you need an unchanged control row beside it, or "fewer findings
  on the re-run" proves nothing.
- **Do not crosscheck a row while another row is writing to the same batch log.**
  The desktop session produced a false MEDIUM finding that way and had to
  disprove its own result.
- **The app clears a stale debug log once per session.** If you restart the app
  between rows, the previous row's log is gone and its findings cannot be
  re-derived. Copy `downloads/debug_log.txt` aside after each row, or run rows
  through `matrix` (which captures per-row logs) rather than standalone `flow`.
- **Never run a mutation pass on a dirty tree or while another session might
  commit** - the harnesses write broken code to disk and restore seconds later.
