---
name: audit-live
description: Run the live application audit - launch the real app, drive it through a browser, perform genuine downloads and syncs against real Canvas courses, and reconcile the result against five independent oracles. Use when asked to audit the running product, verify an engine change end to end, or reproduce a user-reported delivery bug.
---

# Live application audit

This drives the **assembled product** against **real Canvas**. It is not the
unit suite: `tests/test_*.py` proves individual functions behave;
this proves the app **delivers the right files to the right places and tells
the user the truth about it**.

Two long documents back this skill, and they are the manuscript - read them,
do not improvise:

- **`tests/audit/RUNBOOK.md`** - the phase-by-phase script, the reference
  courses, the fixtures, and a long list of traps that look like defects and
  are not. Read the "Do NOT report" sections before filing anything.
- **`tests/audit/README.md`** - the design: the five oracles, the isolation
  guarantee, and why the plan is a covering array rather than a cross product.

```bash
python -m tests.audit --help
```

## The one rule

**A finding is a disagreement between two oracles, and every finding names the
pair.** O1 UI · O2 debug log · O3 disk · O4 sync manifest · O5 Canvas API.

O1/O2/O3 are all downstream of the app's own discovery - if it misses thirty
files, all three agree and all three are wrong. **O5 is the only view computed
outside the application; O4 is the only view of its internal model.**

## Setup (once per audit)

```bash
python -m tests.audit run new --label <what-this-audit-is-for>
python -m tests.audit app start
python -m tests.audit browser open
python -m tests.audit canvas courses
```

Take Canvas ground truth **before** touching a course, or O5 is contaminated by
your own run:

```bash
python -m tests.audit canvas snapshot <course_id>
```

## The matrix is how a full audit runs

Driving 73 rows by hand is the failure this section exists to prevent. The
matrix is deterministic, resumable, and partitioned into lanes that cannot
share Office or the GPU.

```bash
python -m tests.audit matrix build --courses 45899,43665,43660,43667 --save
python -m tests.audit matrix prepare --lanes 4
python -m tests.audit matrix launch
python -m tests.audit matrix lanes
python -m tests.audit matrix collect
python -m tests.audit register update
```

`matrix lanes` reports progress at any time; a killed worker resumes, a failed
row is retried, a passed row is not repeated. Every command works against one
lane with `--run <parent>__<lane>`.

**Two resources cannot be shared and they define the lane classes**: `office`
(Win32 COM `Dispatch` attaches to the machine-wide Application object - two
lanes converting are two threads steering one Excel, and it hangs rather than
raising) and `gpu` (one device, plus an OpenMP clash that segfaults rather than
erroring). Everything else is `free`.

## The re-check contract, and its limit

A finding is a function of **(evidence, checker)**. `matrix recheck` replaces
the **checker** and re-runs the verdict against stored evidence:

```bash
python -m tests.audit matrix recheck
python -m tests.audit matrix collect --rechecked
```

**Nothing replaces the evidence except running the row again.** So there are
two kinds of stale finding and re-check only fixes one:

- **Checker-stale** - the row ran fine, the checker was wrong at the time.
  `recheck` clears it. A re-check that reaches a *different* verdict than the
  live pass is a checker defect **by definition**: the evidence is identical,
  so only the checker changed.
- **Product-stale** - the row's log was written by the code as it was when the
  lane started, and lanes run with `--server.fileWatcherType=none`, so a
  product fix mid-run does **not** reach a lane already running. Only re-running
  the row clears it.

## The checker is under test too - and it fails more often than the app

Over two days this suite produced **24 checker defects**. Treat a red row as a
question, not a verdict. Before filing against the product, ask whether the
*check* is wrong - `RUNBOOK.md` lists the ones already found.

A new or edited check must be validated in **both directions**: prove it fires
on a genuine defect *and* stays quiet on a known-good row. A check validated in
one direction only is routinely a check that can never fire.

## Recording

```bash
python -m tests.audit finding add --scenario <id> --category <cat> --severity <sev> --evidence <path>
python -m tests.audit finding list
python -m tests.audit finding classes --defects-only
python -m tests.audit report build
python -m tests.audit report summary
```

## Smallest useful smoke test

Course `43667` finishes in seconds (one ExternalUrl) - use it to prove the
pipeline is wired before spending time on the big courses.

```bash
python -m tests.audit flow download --courses 43667
python -m tests.audit check download --course-id 43667
```

## Teardown

```bash
python -m tests.audit browser close
python -m tests.audit app stop
```

Every run redirects the app's entire persistent state via
`CANVAS_DL_CONFIG_DIR` into `_audit_runs/<run_id>/config/`, so an audit can
never read or trample the developer's real state. Isolation is total or it is
worthless - see `README.md`.
