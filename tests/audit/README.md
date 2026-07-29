# Live application audit

A real-life, repeatable audit of the **running** Canvas Downloader: it launches
the app, drives it through a browser the way a user would, performs genuine
downloads and syncs against real Canvas courses, and then reconciles the result
against five independent views of the same truth.

This is not a unit-test suite. `tests/test_*.py` proves that individual
functions behave. This proves that the assembled product **delivers the right
files to the right places and tells the user the truth about it**.

```bash
python -m tests.audit --help
```

Or, as an agent task: **`/audit-live`** (see `.claude/skills/audit-live/`).
The manuscript the agent follows is [`RUNBOOK.md`](RUNBOOK.md).

---

## The five oracles

| | Oracle | Answers | Source |
|---|---|---|---|
| **O1** | UI | what the app **tells the user** | Playwright over CDP |
| **O2** | Debug log | what the app **says it did** | `debug_log.txt`, parsed into typed events |
| **O3** | Disk | what **actually exists** | folder inventory + hashes |
| **O4** | Sync manifest | what the app **believes exists** | `.canvas_sync.db` |
| **O5** | Canvas API | what **should exist** | `canvasapi`, fetched outside the app |

**A finding is any disagreement between two oracles**, and every finding names
the pair. That framing is the point of the suite.

O1, O2 and O3 are all downstream of the app's own discovery — if it misses
thirty files, all three agree and all three are wrong. **O5 is the only view
computed outside the application.** **O4 is the only view of the app's internal
model**, which is where the silent failures live: a manifest row pointing at a
moved file makes it read as "deleted locally" forever, invisible to everything
else.

---

## Isolation

Every run redirects the app's entire persistent state via
**`CANVAS_DL_CONFIG_DIR`** into `_audit_runs/<run_id>/config/`. Settings, sync
pairs, sync history, saved groups, presets and the Today list are all isolated,
so an audit can never read or trample the developer's real state — which in dev
mode lives in the repo root.

Isolation is total or it is worthless: an audit that isolated settings but
shared sync history would draw conclusions from state it had polluted itself.
`shared.helpers.get_config_dir()` is the single chokepoint every state manager
already routes through, and `tests/test_audit_harness.py` fails the build if a
new one bypasses it.

Whisper models and the CUDA runtime are **junctioned**, not copied.

---

## Combinatorial coverage

The download configuration has 24 independent binary factors. The literal cross
product is **2²⁴ ≈ 16.7 million runs**. That is not thoroughness; it is noise.

What finds configuration bugs is *interaction* coverage, so the plan is a
**covering array**:

| Tier | Runs | What it guarantees |
|---|---|---|
| extremes | 2 | all-off and all-on |
| isolation | 23 | every option tested **alone**, so no converter can hide behind another |
| pairwise | 36 | every **pair** of option values occurs together |
| triple | 21 | every **triple** among factors that share code paths |
| **total** | **73** | **100% of 817 reachable 2-way tuples, 100% of 364 3-way** |

`coverage()` re-derives this from the generated rows, so the report states a
measured number rather than a claim. Generation is deterministic, so run lists
are comparable between audits.

**The sync matrix is a different space, not a mirror of this one** (43 rows).
A download row varies *configuration*; a sync row's configuration is already
fixed — it is the contract baked into the folder at download time. What varies
at sync time is the **world**: what changed since the last run, and which of it
the user accepts through which screen. The two dimensions also differ wildly in
cost, which is why one is replayed against frozen snapshots. See the RUNBOOK.

---

## The checker is under test too

**This is the most important thing on this page.** Over two days the suite
produced **24 checker defects** — and only a handful were crashes. The rest
returned a confident, specific, *wrong* answer: a HIGH against a product that
had done exactly the right thing, or a silent pass on a rule nobody was
enforcing any more.

The scale is not incidental, and both matrices measured it end to end:

| matrix | as-run defects | re-derived | classes | blocking |
|---|---|---|---|---|
| sync, 43 rows | 40 | **0** | 8 → 0 | 4 → 0 |
| download, 73 rows | 311 | **48** | 13 → 7 | 64 → 8 |

On the sync run, **40 of 40** non-info findings were the audit and none were the
app; the same evidence then yielded zero. On the download matrix a corrected
checker removed **85%** of the defects, whole classes at a time — and of the 48
that survived, **47 were product-stale**, already fixed in the tree by the same
session. One genuinely new defect came out of 73 rows.

> **An invented finding is worse than a missed one.** A missed defect costs you
> that defect. An invented one costs the trust that makes every other finding
> worth reading — and the real finding then hides among them. The genuine
> critical in that sync run sat among 90 fabrications.

**A finding is a function of (evidence, checker), and only the evidence is
expensive.** That is why `matrix recheck` exists: it re-derives every row's
findings from saved evidence with the *current* checker, in seconds, with no
network, browser or re-download. Anything derived — including the per-course
log slice — is part of the **checker**, not the evidence, and is recomputed on
a re-check so that fixing it is retroactive.

The corollary is the trap: a re-check cannot fix a **product**-stale finding.
Lanes run with `--server.fileWatcherType=none`, so a row's log was written by
the code as it stood when its lane started. Read a long matrix with both kinds
in mind; the RUNBOOK has the worked example.

### Three things that actually find checker defects

1. **Compare two runs, BY CLASS** — `finding classes --against`. A **class** is
   a title with the row-specific parts normalised out (counts, quoted names,
   sizes), so 350 findings across 73 rows resolve to the dozen causes they
   actually are. A class that appears or vanishes for no product reason is a
   checker defect, and nothing in a single run's output shows it:

   ```bash
   python -m tests.audit finding classes --defects-only          # the triage view
   python -m tests.audit finding classes --against as-run        # what the checker changed
   ```

   Both sides must normalise identically or the diff is noise, which is exactly
   what an ad-hoc regex per session produces — hence a module rather than a
   shell one-liner. It reads the LANES' ledgers, so it works on a matrix before
   anything has been collected.
2. **Chase the survivors.** Take the handful of findings that remain and ask of
   each: *what exactly is the app doing, and is it wrong?* Two of the last
   batch turned out to be the app being reported for doing precisely what it
   was told — honouring a max-file-size setting, and refusing to bind a `.txt`
   to a `.sql`.
3. **Validate a new check in BOTH directions, against real logs.** It must FIRE
   on evidence known to contain the defect and stay SILENT on evidence known
   not to. The duplicate-fetch check was swept over 92 per-course logs: it
   fired on exactly the 2 that carry the defect, 0 false positives, and the
   single retry line in the corpus was correctly ignored.

Write the test against the **documented** contract, not the observed behaviour —
a test written from the code can only ever agree with it. That is how
`_selected_stems` was found returning "nothing was ticked" where its own
docstring promised "unknown".

---

## What the seeder breaks on purpose, the checker must be told

The seeder deliberately creates the conditions the app is asked to handle:
dangling manifest rows, md5 drift, `.part` leftovers, untracked files. The
always-on invariants look for exactly those. So the seed plan publishes
`expected_*` lists and `crosscheck.invariants` suppresses each one.

**It is a contract between two files and it fails silently in both
directions** — an undeclared fixture is reported as a product defect, and a
declaration nothing reads suppresses nothing. Three rules keep it honest:

- **One mutation can have TWO consequences, and both must be declared.**
  `_backdate` falsifies the recorded *size*; only `edited_update` also rewrites
  the *bytes*. Relocating a file leaves a dangling *row* **and** an untracked
  *new path*. Each of those pairs was declared as one fact and got both halves
  wrong at once.
- **Declare the state that actually exists.** A dangling row points at where
  the file *was*, so it is declared at `original_path` — declaring the new path
  suppressed nothing. And the new path is deliberately *not* suppressed,
  because a row pointing there with no file is the genuine adoption failure the
  check is for.
- **Derive, don't store.** `seed.declarations()` computes every list from the
  fixture list, and `parallel.seed_expectations()` **unions** derived with
  stored. That is what makes a new expectation retroactive: adding one dropped
  a completed run from 6 defects to 0 with nothing re-run. Preferring the
  stored value would have left every older plan reporting the seeder's own
  renames for ever.

The couplings are enforced **from the source with AST checks** rather than by
convention (`tests/test_audit_seed_expectations.py`): every fixture calling
`_backdate` must declare size drift, every relocation must record where the
file was, and the fixtures whose expectation depends on matching Canvas
metadata must draw from `_direct_targets()` — because a conversion product
differs from its source in both the extension and the size, so asking the
analyzer to match one is asking for a match that cannot exist.

---

## Layout

```
tests/audit/
  RUNBOOK.md        the manuscript — read this to run an audit
  cli.py            every verb; one JSON object per command
  harness/
    paths.py        run dirs + the isolation boundary
    appctl.py       launch/stop the app under test
    browser.py      persistent Chrome over CDP, driven by widget key
    probe.py        the JS injected to read a screen (oracle O1)
    conditions.py   named phase waits, read off the step tracker
    oracles/        canvas.py (O5) disk.py (O3) db.py (O4) log.py (O2)
    crosscheck.py   reconciliation + always-on invariants
    seed.py         20 fixture kinds covering every sync category
    matrix.py       covering arrays + course capability matching
    parallel.py     lane scheduler, row execution, harvest/prune, re-check
    snapshot.py     freeze/restore a downloaded folder, for the sync matrix
    flows.py        download / sync / today drivers
    findings.py     the ledger
    classes.py      fold findings into classes; diff two sets of them
    AUDIT_FINDINGS.md  the register - memory between audits, hand-editable
    register.py     merge into AUDIT_FINDINGS.md, preserving decisions
    report.py       self-contained HTML report
```

**The register is the memory between audits.** `tests/audit/AUDIT_FINDINGS.md` is
hand-editable: set a finding's `**Status**` to `fixed` / `invalid` /
`accepted` / `wontfix` and the next run refreshes the facts around your
decision without overwriting it. Anything marked `fixed` that reappears is
reported as a **regression** — that is the line worth watching. Record *why*
something was invalid, not just that it was: several findings in there are the
audit's own defects, and the note is what stops the next reader re-filing them.

---

## Design notes worth knowing

**The browser outlives the CLI call.** Chrome is launched detached with a
remote-debugging port; each command attaches over CDP, acts, and detaches. A
Playwright-launched browser dies with its Python process, which would lose the
Streamlit *session* between steps — and session state is most of what this app
is.

**Everything is addressed by widget `key`.** Never by text (translated), never
by position (moves), never by accessibility snapshot (enormous on a 200-row
review screen). `st-key-<key>` is stable, unique and cheap.

**Contracts are restated, not imported.** `crosscheck.CONVERTERS` and
`oracles/db.SECONDARY_OFFSETS` deliberately duplicate tables that exist in the
app. Importing the app's own tables would make the expectation agree with the
implementation by construction. The duplication is guarded by drift tests.

**Fixtures carry their own predictions.** Every seeded scenario records the
category the analyzer must place it in and what must be true on disk afterwards,
written next to the mutation that causes it — so the two cannot drift apart.

**Synthetic findings are labelled.** The reference courses are static, so
"deleted on Canvas" and "Canvas has a newer version" are fabricated on the
manifest side. That is exactly equivalent at the analyzer's input boundary, but
the report marks those findings `fixture` so a reader always knows.

---

## Two measured facts that shape the sync fixtures

**There are two md5s.** `original_md5` in the manifest is computed **locally by
the app** from the bytes it wrote — it is present even on negative-id entities
whose `original_size` is 0. `c_file.md5` from the Canvas API feeds only
`analyze_course` adoption tier (b), and **0 of 140 files** on course 43660
expose one, so that tier is inert against this instance.

**Renames are recovered by `heal_manifest`, not by that tier.** Healing runs
before the analyzer and matches local-to-local, so it works with no Canvas hash
at all — but only while the manifest row still exists. The fixtures therefore
separate `renamed_row_intact` (Tier 2 must catch it), `renamed_row_dropped`
(only the weak size+extension fallback remains), `renamed_ambiguous` (the
uniqueness guard must **refuse**) and `renamed_substitution` (every tier must
refuse — "Lecture1" and "Lecture2" are different documents).

Expecting adoption in all four would file correct behaviour as a bug.
