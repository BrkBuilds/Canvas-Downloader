# Static audit playbook

How to run an offline (no-network) crash/data-loss audit of this codebase, written
after the 2026-08-08 sweep that found **12 defects in six rounds**. Its companion is
the LIVE audit (`tests/audit/README.md` + `RUNBOOK.md`, driven by
`.claude/skills/audit-live/SKILL.md`), which exercises the assembled product against
real Canvas. This file covers the half you can do with no token and no network.

Read this before starting. Half of it is *what not to bother repeating*.

---

## The result that shapes everything else

**Twelve defects, and not one was a new kind of mistake.** Every single one was a bug
class this repo had already found, documented in `CLAUDE.md`, and fixed — in one place,
while an identical instance survived somewhere the original sweep did not reach.

So the highest-yield question is never *"what could be wrong here?"*. It is:

> **Which module did the last fix for this class NOT reach?**

`CLAUDE.md` is therefore the audit's primary input, not background reading. Each of its
hard-won sections names a class. Take the class, scan the whole repo for it, and expect
to find the sibling that was missed.

---

## The six techniques, ranked by what they actually returned

### 1. Sweep the class, not the symptom (rounds 1–2: 6 defects)

Write a small AST scanner per documented class and run it over every file. This beat
reading code by a wide margin.

Scanners that paid off (all trivial, ~60 lines each):

| Scanner | Found |
|---|---|
| `load → degrade to {} → save` | settings file wiped on an unreadable read (2 sites) |
| duplicate function names, divergent bodies | three path keys that disagreed |
| `Thread.start()` outside a try, after a state claim | two workers pinned "running" forever |
| datetime parsed in a `try`, compared outside it | `TypeError` escaping `analyze_course` |

**Why it works:** a class has a *shape*, and shapes are greppable. Prose is not.

### 2. Sibling asymmetry (rounds 1, 4, 5, 6: 5 defects — the highest-severity ones)

Compare parallel implementations **function by function**. Where one sibling carries a
guard and its twin does not, the twin is the bug — **and the guard's own comment usually
states the failure mode you are about to confirm.**

Worked examples from this session:

- `word/excel/pdf::_init_app` — PowerPoint guarded its property sets with the comment
  *"Some Office 365 builds restrict these flags"*; Word and Excel did not, and leaked an
  Office process.
- **Windows branch vs macOS branch of the same function** — the single most valuable
  axis. `pdf_looks_real` had been added to the COM path of all three Office converters
  and to the AppleScript path of none. That one is a data-loss bug on macOS.
- `code.py` checks `st_size`, `video.py` calls `file_has_content`, `md.py` checked bare
  `exists()`.
- `humanize_canvas_error._messages` is depth-capped *with a comment saying why*;
  `render_entry`, forty lines away in the same file, was not.

**Platform branches are the richest seam in this repo**, because every fix is written and
tested on Windows.

### 3. Counting guards against dangerous operations (rounds 4–5: 2 data-loss defects)

Do not ask "is this guarded?". **Count.** `grep -n "unlink\|remove\|rmtree" converters/*.py`
against `grep -n "pdf_looks_real\|file_has_content"` showed **2 delete sites and 1
verification** per Office converter. That ratio *was* the bug.

Generalised into a census (see "Reusable scanners" below): list every destructive call,
list what the enclosing function verified **before** it, and triage the empty column.

This is now enforced as a test — `test_every_source_deleting_converter_verifies_content_not_just_existence`
asserts `len(content gates) >= len(source deletes)` per file, so a seventh converter
cannot join the family without one.

### 4. Guard scope: does it cover the statement it was written for? (round 2)

```python
try:
    canvas_dt   = datetime.fromisoformat(...)
    manifest_dt = datetime.fromisoformat(...)
except (ValueError, TypeError):     # names TypeError
    return False
if canvas_dt <= manifest_dt:        # ...but the TypeError happens HERE
```

The author's intent is visible in the handler; the guard just landed one line short. Look
for `try` blocks whose dangerous operation sits **after** the block rather than inside it.

### 5. Cosmetic bounds (round 6)

A recursive function that takes a `depth` / `level` / `n` argument **looks** bounded. Check
that something actually **compares** it. `render_entry(entry, depth)` used `depth` only for
`margin = min(depth * 30, 150)` — the visual indent — while recursing over server data with a
network call per level.

> Whenever you see a bound-shaped parameter, grep for a comparison on it.

### 6. Who ends the loop — you or the server? (round 3)

Every pagination loop in `panopto/discovery.py` exited only when the server returned a
**short page**, making termination the other end's responsibility. Ask of every loop over
remote data: *what happens if the server never stops?* Then bound it yourself.

The tell here was again an asymmetry **inside one function**: `_discover_folder_sessions`
bounds its own folder walk (`depth <= 3`, `<= 40 folders`, cycle set) and its docstring
advertises that — while the page loops it calls up to 40 times had no bound at all.

---

## Sweeps that came back genuinely clean — do not repeat these

Re-running these is pure cost. They were done properly and found nothing.

| Sweep | Result |
|---|---|
| Platform guards | Every `windll` / `win32com` / `winreg` / `osascript` site is lazily imported **and** guarded. |
| Regex backtracking | 0 nested-quantifier patterns anywhere. |
| `return`/`break`/`continue` inside `finally` | 0. |
| Dead exception handlers (subclass after base) | 0. |
| Leaked sqlite connections | 0 — the one bare `connect` has a correct `try/finally`. |
| Fire-and-forget asyncio tasks | 0 — every `create_task` reaches a `gather`. |
| `open()` / `read_text()` without `encoding=` | 0 in app source. |
| Mutable default arguments | 0. |
| Symlink loops in folder walks | Safe — every `os.walk` uses the default `followlinks=False`. |
| AppleScript interpolation census | All 39 interpolations are `_as_posix`-escaped or from a fixed app map. |
| `win11toast` XML escaping | Safe — it sets `text.inner_text` through the WinRT **DOM**, which escapes. A course named "Marketing & Sales" cannot break a toast. |
| `getattr(obj, x, default)` present-but-null trap | The download hot path is guarded (`or 0`); 427 other sites are cosmetic. |
| `office_container_stage` | Safe — it **copies** the source, and its `dst.unlink()` only removes a resolver-approved prior product. |

---

## The workflow for a finding

Non-negotiable order. Skipping step 1 produces "fixes" for bugs that do not exist;
skipping step 4 produces tests that cannot fail.

1. **Reproduce against the REAL function.** Not a re-implementation of its logic — the
   actual import. A test that re-implements the expression under test passes against
   broken code (this repo already learned that on `format_file_size`).
2. **Fix**, preferring the correct answer over the merely safe one. The datetime fix
   normalises naive → UTC rather than widening the `except`, because falling into the
   handler would answer "not updated" and silently skip a genuine update.
3. **Test**, asserting the invariant rather than the current spelling.
4. **Mutate.** Revert the fix; the test must fail. Then try to *weaken* it (not just
   delete it) — see the mutation section.
5. **Verify in the real app** where the change is reachable from the UI.
6. **Document** the class in `CLAUDE.md`, not just the instance.

---

## Mutation testing: the part that keeps catching me out

**Two of six rounds left survivors on the first pass, and both were my test's fault, not
the mutation's.** Budget for a second pass.

### Mistakes made this session — watch for these

- **A difference too coarse to detect the mutation.** My datetime tests used timestamps a
  *month* apart, so mutating `timezone.utc` → a wrong zone (a ≤24h shift) changed nothing.
  Fix: make the fixture's margin **smaller than the mutation's effect** — one hour apart.
- **Matching a token instead of a call.** A structural test asserted `"file_has_content" in src`,
  which the leftover `from converters.verify import file_has_content` satisfied after I
  reverted the actual call. **Match on an AST call node.**
- **Mutating something already covered by an earlier guard.** After adding a pre-write
  check, the post-write gate became unreachable via normal input, so two mutations of it
  survived. That is not always a test gap — sometimes it is genuine defence in depth. Prove
  it by *injecting the failure the second gate exists for* (a write that silently commits
  nothing), or accept and say so. Do not delete a redundant gate to make a mutation die.

### Harness hazards

- **Restore with binary I/O.** Reading text-mode and writing with `newline=""` silently
  converted CRLF files to LF across the repo. Content survived, but always `md5sum -c` a
  pre-snapshot afterwards.
- **Make anchors line-ending aware** (`old.replace("\n", eol)`) or every mutation reports
  `SKIP (0x)` and you conclude, wrongly, that the code is fine.
- **Check the anchor matches exactly once.** `_kill_app()` appears three times per
  converter; an ambiguous anchor silently skips.
- **Never run two mutation scripts concurrently** (this repo has lost real code that way).
- Wrap the pytest call in a **timeout** and count a timeout as CAUGHT — a mutation that
  removes a loop bound makes the suite hang, which is the correct verdict.

### Termination tests must be able to FAIL, not hang

Run the call on a **thread with a join timeout** and assert `not t.is_alive()`. A
termination test written as a direct call turns a regression into a 900-second hang that
looks like infrastructure trouble.

```python
def _runs_to_completion(fn, seconds=20):
    box = {}
    t = threading.Thread(target=lambda: box.update(r=fn()), daemon=True)
    t.start(); t.join(seconds)
    return (not t.is_alive()), box
```

---

## Testing a macOS-only branch from Windows

This found a real data-loss bug on a platform I could not run:

```python
mod.sys.platform = "darwin"                 # module-level, so the branch is taken
setattr(cls, "_convert_applescript_word", fake)   # stub the bridge on the class
try:
    inst.convert(src)
finally:
    mod.sys.platform = real_platform
```

It exercises the **real** `convert()` down its macOS path. It cannot validate osascript,
Finder or Office themselves — say so explicitly when reporting, and treat anything it
proves as "the Python branch is correct", not "macOS works".

---

## Reusable scanners

All were throwaway and all are worth rewriting; each is ~60 lines of `ast`. The shapes:

- **`scan_crash.py`** — subprocess without `timeout`, `open()` without `encoding`,
  index-into-call-result, mutable defaults, division by a non-literal.
- **`scan_lostupdate.py`** — `try: read` … `except: default` … then a write in the same scope.
- **`scan_dupes.py`** — same function name, different body hash, across files.
- **`scan_destructive.py`** — every `unlink`/`remove`/`rmtree`/`kill` with the guards the
  enclosing function applied **before** it. **The highest-value one; write this first.**
- **`scan_handlers.py`** — control flow in `finally`; handler ordering (subclass after base).
- **`scan_dtcmp.py`** — datetime parsed in a `try` but compared outside it.
- **`scan_platform.py`** — platform API use that is neither platform-guarded nor try-guarded.
- **`scan_applescript.py`** — f-strings containing AppleScript, with each interpolation
  classified escaped / app-controlled / unknown.

Filter aggressively (skip `build/`, `dist/`, `tests/`, `scripts/`) and treat the output as
a **worksheet**, not a verdict. `scan_getattr.py` returned 427 hits and one useful lead —
that ratio means the scanner needed a narrower question, not that the code was bad.

---

## Baseline and gates

```bash
python -m pytest tests/ -q --deselect tests/test_audit_docs_match_cli.py   # while iterating
python -m pytest tests/ -q                                                 # before finishing
python scripts/verify_architecture.py                                      # must stay at 0
```

Then boot the real app and drive it — a green suite is not a working screen:

```bash
python -m streamlit run app.py --server.headless=true --server.port=8601 --server.fileWatcherType=none
```

…and check `[data-testid="stException"]` is 0 on every screen the change can reach.
Playwright is available in this environment and the app restores a saved session, so the
authenticated screens render without any setup.

---

## Knowing when to stop

Rounds 1–2 found several defects each from scanning. Rounds 3–6 each needed a **new
instrument** and each returned exactly one. That decay is the signal: when a round costs a
new technique and yields one finding, the cheap offline surface is exhausted.

That is *not* proof the code is clean. It means the remaining defects need **execution** —
the live audit, or real macOS hardware — rather than more analysis.
