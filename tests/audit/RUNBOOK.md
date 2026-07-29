# Live audit runbook

You are auditing the **running application**, not its source. Your job is to
drive it like a user, then prove — or disprove — that the files it produced and
the things it said about them are true.

Read this once, then work from the phase list. Every command prints one JSON
object. **Do not write ad-hoc Python or JavaScript**; if a check you need does
not exist, add it to `harness/crosscheck.py` so the next run gets it too.

---

## The one idea that makes this suite work

There are **five independent views of the same truth**, and a finding is any
disagreement between two of them:

| | Oracle | Answers |
|---|---|---|
| **O1** | UI (Playwright) | what the app **tells the user** |
| **O2** | `debug_log.txt` | what the app **says it did** |
| **O3** | Disk inventory | what **actually exists** |
| **O4** | `.canvas_sync.db` | what the app **believes exists** |
| **O5** | Canvas API, fetched outside the app | what **should exist** |

O1, O2 and O3 are all downstream of the app's own discovery. If discovery misses
thirty files, all three agree and all three are wrong — the UI says 234, the log
says 234 saved, the disk holds 234. **O5 is the only external check**, and
**O4 is the only view of the app's internal model**, which is where the silent
failures live: a manifest row pointing at a moved file makes that file read as
"deleted locally" forever, and no other oracle can see it.

Always name the oracle pair when you record a finding. "The sync review looked
wrong" is an opinion. "O1 shows this under New Files while O4 has a row for it
whose path exists on disk with a matching md5" is a defect with a repro.

---

## Ground rules

1. **Never point the audit at real user data.** Every run gets its own
   directory and its own `CANVAS_DL_CONFIG_DIR`, so the app's settings, sync
   pairs, history, saved groups and Today list are all isolated. `run new` does
   this; do not bypass it.
2. **Report, never fix — and the exception is not a loophole.** Fixing the
   PRODUCT during an audit invalidates every row after it: lanes run with
   `--server.fileWatcherType=none`, so the rows already running keep the old
   code and the rows after a restart do not, and the run stops being comparable
   with itself. Fixing the **CHECKER** mid-run is different and expected — that
   is what `matrix recheck` exists for. Always say which you did.
3. **The checker is under test too, and it fails more often than the app.**
   Over two days this suite produced **24 checker defects**; on one 43-row sync
   matrix, 40 of 40 non-info findings were the audit and none were the product
   — twice reporting it for doing exactly what it was told. Before filing
   anything, ask: *what precisely is the app doing, and is it wrong?* An
   invented finding costs more than a missed one, because the real finding then
   hides among the inventions. The full list is at the bottom of this file;
   read it before adding a check.
4. **A wait that times out is a finding**, not an error to retry around. Record
   it with the screen state and move on.
5. **Judge the screenshots.** The mechanical checks catch disagreement between
   numbers. They cannot see a bar at 100% above a "0 of 2" counter, a card
   rendered inside another card, or a sentence that contradicts the panel under
   it. `Read` the PNGs — that is what you are for.
6. **Trust nothing that was not measured.** If you assert the app did something,
   point at the oracle output that shows it.
7. **Validate a new check in BOTH directions, against real logs.** It must FIRE
   on evidence known to contain the defect and stay SILENT on evidence known
   not to. A check that cannot fire is worse than none: it reads as coverage
   and provides none.

---

## How to read this file

Top to bottom once, then work from the phase list. The parts, in order:

| Section | Read it |
|---|---|
| The five oracles, ground rules, setup | first, always |
| Phases 1-5 | as you run them |
| The sync matrix | before any sync work — it is a different space, not a mirror |
| Traps this harness already knows about | before debugging anything odd |
| **Checker defects (2026-07-28 and 2026-07-29)** | **before adding or trusting a check** — 24 entries, each a confident wrong answer |
| Do NOT report: `Page X (1).html` | before filing any duplicate — identity is the entity id, never the name |
| Known limitation: the GPU lane | when planning how long a run takes |
| Verifying the two engine fixes | when re-verifying those specific fixes |
| Two KINDS of stale finding | before reporting any matrix result |

---

## Setup (once per audit)

```bash
python -m tests.audit run new --label <what-this-audit-is-for>
python -m tests.audit app start          # isolated app, prints its port
python -m tests.audit browser open       # persistent Chrome; survives CLI calls
python -m tests.audit canvas courses     # ids + course codes
```

Take Canvas ground truth for every course you will touch **before** downloading
it, so O5 is never contaminated by the run:

```bash
python -m tests.audit canvas snapshot <course_id>
```

### The reference courses

| id | Code | What it is for |
|---|---|---|
| `45899` | BINTO1064U.LA_E25 | zips, code, pptx, assignments+attachments, quizzes. Files tab **403** — 115 files reachable only through modules, plus **9 inline `/files/` links** reachable only by parsing Canvas Content bodies. |
| `43665` | BINTO2063U.LA_E25 | Excel-heavy, complex pptx. Files tab **403**, 121 module files. |
| `43660` | BINTO1060U.LA_E25 | **36 Panopto recordings**, legacy `.doc`, 35 Pages, 22 quizzes, 140 files / 890 MB. The big one. |
| `43667` | BINTS1SEMU.LA_E25 | One ExternalUrl. Finishes in seconds — use it to smoke-test the pipeline and to look at the completion screen. |

---

## Going faster: snapshots and lanes

Two mechanisms, for two different costs. Use both; they are independent.

### Snapshots — download once, exercise many

Every sync-side scenario needs the same expensive precondition: a course folder
the app really downloaded, with a real `.canvas_sync.db`. Downloading it again
per scenario is the same work repeated until the suite is too slow to run.

```bash
# after ONE download of a course, freeze the result
python -m tests.audit snapshot capture "<run>/downloads/<Course Folder>"
python -m tests.audit snapshot list

# per scenario: a pristine copy, in seconds, with the pair registered
python -m tests.audit snapshot restore c45899_base --pair
```

Measured on course 45899: **21,825 files / 241 MB restored and verified in 26s**,
against minutes of download. Restore is a real copy, not a link — scenarios
*mutate* what they restore, which is what seeding is.

Three things to know:

* **The manifest is captured through SQLite's `backup()`, never by copying the
  file.** With WAL journalling the newest rows live in the `-wal` sidecar: a
  byte copy of a live database shows **0 rows** where the backup shows all of
  them (measured). A snapshot with an empty manifest still restores and still
  syncs — it just classifies every file as New, and the scenario looks healthy.
* **The golden copy is read-only.** A snapshot silently written to invalidates
  every run derived from it with no error and no way to notice afterwards.
* **Check the summary.** `manifest_rows` and `manifest_integrity` must be
  populated; a `MANIFEST_WARNING` field means the checkpointed copy failed and
  the snapshot is only trustworthy if the app was not running.

Snapshots are portable between runs because `sync_manifest.local_path` is
relative to the sync root and `sync_metadata` holds no absolute paths. Pinned by
`tests/test_audit_snapshot_parallel.py` — if it ever stops being true, every
restored scenario silently reasons about files that are not where it thinks.

### Lanes — run the matrix in parallel

```bash
python -m tests.audit matrix build --courses 45899,43665,43660,43667 --save
python -m tests.audit matrix prepare --lanes 4
python -m tests.audit matrix launch          # blocks; --no-wait to detach
python -m tests.audit matrix lanes           # progress, any time
python -m tests.audit matrix collect         # fold lane findings into this run
python -m tests.audit register update
```

A lane is just another run directory, so **every command above works against a
lane** with `--run <parent>__<lane>`. That is what makes the isolation real:
separate `CANVAS_DL_CONFIG_DIR`, Streamlit port, Chrome, profile and download
root, so no pair, history entry or preset can cross between lanes.

**Two resources cannot be shared, and they define the lane classes.**

| class | rows | why it must be serial |
|---|---|---|
| `office` | `convert_word`, `convert_excel`, `convert_pptx` | Win32 COM. `Dispatch` attaches to the machine-wide Application object, so two lanes converting are two threads steering **one** Excel. It hangs rather than raising. |
| `gpu` | `pan_out_txt`, `pan_out_srt` | One device, and this project already carries an OpenMP clash that **segfaults** rather than erroring — the reason `panopto/transcribe_worker.py` exists. |
| `free` | everything else | spreads across the remaining lanes |

A row needing both goes to `gpu`: one lane can only serialise one resource, and
the GPU failure is the one that takes the process down. The scheduler is static
rather than a work queue — a queue balances better, but a lane assignment that
depends on timing cannot be compared against the previous audit, which is the
same reason the covering array is generated deterministically.

Progress is per row: a killed worker resumes, and a **failed** row is retried
while a successful one is not repeated.

---

## Phase 1 — Download mode

The root of everything: the course configuration decided here is written into
the folder's contract and shapes every later sync.

Build the run plan. It is a **covering array**, not a cross product — the
configuration space is 2²⁴ ≈ 16.7M combinations, and this covers every pair of
option values (and every triple among the factors that share code paths) in ~73
runs, with the coverage proven rather than claimed:

```bash
python -m tests.audit matrix build --courses 45899,43665,43660,43667 --save
python -m tests.audit matrix show      # composition + coverage percentages
```

For each run in the plan:

```bash
python -m tests.audit flow download <name> --courses <id> --config @cfg.json
python -m tests.audit check download "<course folder>" --course-id <id> \
    --scenario <name> --capture <name>_complete --expect @cfg.json
```

Then **look at the captures** — `<name>_phase_scan`, `<name>_phase_download`,
`<name>_complete` — and record anything the numbers cannot express.

### What each configuration must prove

- **`mode: flat`** → no subfolders at all (except a Panopto "separate" folder,
  zip extraction targets, and isolated Canvas Content).
- **`mode: modules`** → module subfolders exist and files are inside them.
- **`file_filter: study`** → only slides/PDFs/docs plus conversion outputs.
- **`max_file_size`** → over-cap files absent from disk **and** absent from the
  manifest. A row for a skipped file makes it read as up to date forever, so
  raising the cap later would never bring it in.
- **Each converter alone** → its sources consumed, its outputs present. Note
  which converters **delete their source**: zip, code, urls, video, pptx, word,
  excel. `convert_word` is **legacy only** (`.doc`/`.rtf`/`.odt`) — a `.docx`
  is never converted, so do not expect a PDF beside one.
- **Each Canvas Content type alone** → its entities present as negative-id rows
  in the right offset range, and **nothing else's**.
- **A converter that is OFF** must not have consumed anything. That check is
  `critical`: the user asked to keep their originals.

### The discovery check is the one that matters most

`check download` compares O5's enumeration against O4's manifest. On courses
45899 and 43665 the Files tab is **403**, so everything comes from the module
scan plus inline link parsing — exactly the path most likely to lose files, and
the only way to see it is from outside the app.

---

## Phase 2 — Sync mode

Sync is judged against **fabricated pre-states**, because the courses are static
and Canvas cannot be edited. Fabrication happens on the manifest side, which is
exactly equivalent at the analyzer's input boundary — it compares live Canvas
metadata against manifest rows either way. Those findings are marked
`synthetic` so a reader always knows.

```bash
python -m tests.audit disk scan "<folder>" --save before
python -m tests.audit seed apply "<folder>"          # all 20 fixture kinds
python -m tests.audit flow sync <name>               # full Analyze/Review/Sync
python -m tests.audit disk scan "<folder>" --save after
python -m tests.audit check sync "<folder>" \
    --plan "<run>/evidence/seed_<folder>.json" \
    --capture <name>_review --after after --scenario <name>
```

Every fixture carries its own **predicted category** and **predicted on-disk
outcome**, written next to the mutation that causes it. The check fails if the
review screen or the log disagrees.

### The rename fixtures — read this before interpreting them

There are **two md5s** and confusing them will make you file correct behaviour
as a bug:

- **`original_md5` is computed locally by the app** from the bytes it wrote. It
  is on every row, including negative-id entities with `original_size = 0`.
- **`c_file.md5` from the Canvas API** feeds only `analyze_course` adoption tier
  (b). Measured: **0 of 140 files** on 43660 expose one, so that tier is inert
  against this instance.

Renames are normally recovered by **`heal_manifest`, which runs before the
analyzer** and matches local-to-local:

| Tier | Match | Fixture that isolates it |
|---|---|---|
| 1 | exact normalised filename | `moved_deep` |
| 2 | `original_md5` + exact size | `renamed_row_intact`, `moved_and_renamed`, `unicode_rename` |
| 3 | fuzzy stem containment ≥ 0.90, ambiguity reject | — |

Healing only runs **while the row still exists**. So:

- `renamed_row_intact` → **up to date** (Tier 2).
- `renamed_row_dropped` → **up to date** via the analyzer's weak size+extension
  fallback, because size+ext is unique for that candidate.
- `renamed_ambiguous` → **New**. The uniqueness guard must refuse; binding a
  coincidentally same-sized file would mark a missing file present.
- `renamed_substitution` → **deleted locally**. Every tier must refuse a
  single-character substitution — "Lecture1" and "Lecture2" are different
  documents. This is the safe outcome, not a failure.

### The other categories

| Fixture | Must land in | Must happen on disk |
|---|---|---|
| `new_regular`, `new_secondary` | New Files | re-downloaded to its original path |
| `clean_update` | Updates (Clean) | overwritten in place, same name and folder |
| `edited_update` | Updates — You've Edited | **`_NewVersion` sibling; the edited bytes untouched** |
| `deleted_locally` | Deleted Locally | left absent — Quick Sync always skips these |
| `deleted_on_canvas` | Deleted on Canvas | local copy untouched; the app never deletes |
| `ignored` | Ignored Files | untouched, restorable |
| `duplicate_copy`, `foreign_content`, `partial_artifact` | **nowhere** | untouched, never claimed |
| `readonly_target` | Updates (Clean) | `_NewVersion` fallback, no hard error |

`edited_update` is the most consequential check in the suite. If the edited md5
changes, that is **data loss** and it is `critical`.

### Seed ONCE, and take a scan on both sides

```bash
python -m tests.audit snapshot restore c45899_base --pair
python -m tests.audit seed apply "<folder>"
python -m tests.audit disk scan "<folder>" --save p2_before
python -m tests.audit flow sync p2
python -m tests.audit disk scan "<folder>" --save p2_after
python -m tests.audit check sync "<folder>" --plan <evidence>/seed_<folder>.json \
       --capture p2_review --before p2_before --after p2_after
```

**Never seed a folder twice.** The second pass reads a folder the first already
rearranged, so fixtures land on fixtures and the plan it writes describes only
its own half — every category then disagrees with the screen and the
disagreement looks exactly like an application bug. This cost a full Phase 2
run: a `seed apply` that appeared to time out had in fact completed in its own
process, the retry stacked on top, and the review screen came back with New at
20 against a plan predicting 10. `seed apply` now refuses a second pass; restore
a snapshot instead, which is seconds and gives a folder whose history is known.

`--before` is what enables the **untouched** assertions. Without it a sync that
quietly rewrites or deletes a decoy, a foreign file or an up-to-date file passes
silently — nothing on screen would ever mention it.

### What a passing Phase 2 looks like (measured 2026-07-28, course 45899)

On a **pristine** baseline (fresh download, 44 fixtures, 21 kinds, seeded once):

| category | expected | on screen |
|---|---|---|
| new | 11 | **11** |
| updated_clean | 4 | **4** |
| updated_modified | 2 | **2** (0/2 ticked) |
| deleted_locally | 4 | **4** (0/4 ticked) |
| deleted_on_canvas | 2 | **2**, "kept locally" |
| ignored | 2 | **2** |

15 files downloaded = 11 + 4, exactly the ticked set. Every on-disk outcome
assertion passed: `restored`, `absent`, `new_version` and `unchanged`, with
**zero criticals**. Anything other than an exact match here is worth chasing —
every mismatch seen while building this turned out to be a poisoned baseline or
a matcher gap, never the app.

**The categories that matter most are unchecked by default**, so the default run
never exercises them. Use `--select` for a second pass:

```bash
python -m tests.audit flow sync p2_edits --select updated_modified,deleted_locally
```

### Sync scenarios to run

1. **Analyze → Review → Sync** with default selections — the full path.
2. **Quick Sync** on the same seeded state — must skip edited and
   locally-deleted, sync new and clean.
3. **Deselect some rows + "Move deselected to Ignored"** — the ignore must
   persist to `panopto_ignored`/`is_ignored` and be gone next analysis.
4. **Restore from Ignored** — must return to its origin category.
5. **Sync with nothing changed** — the "all up to date" completion card.
6. **Cancel mid-sync** — no `.part` left, manifest intact.
7. **Sync a folder whose contract has converters on** — the source-consuming
   converters delete files, and the next analysis must not call them deleted.

---

## Phase 3 — Today mode

Today is a **lens** on `canvas_sync_history.json`, filtered on two independent
axes: the curated daily course set, and arrival category (`new`/`updated`/
`protected` only — never `restored`). Membership is **retroactive and
stateless**, so adding a course reveals files that arrived earlier the same day.

Check:

1. Add a course → its earlier arrivals appear.
2. Remove it → they disappear again.
3. Sync a **non-daily** course → the off-list footnote counts it; dismissing
   stores the tally, so three more off-list courses later must re-show it.
4. Rename a daily folder on disk → that course goes amber and is **skipped**,
   the rest sync normally, and there is **no "sync paused" screen**.
5. Both sync modes feed Today — a review-mode sync of a daily course must
   appear there too.

### Do NOT report: the Quick Sync shortcut is inert while Today mode is off

With auto-sync off — the default — every section of the Today page is dimmed
with `pointer-events: none`, and that property is inherited, so the "Quick Sync
now" button is enabled server-side and physically unclickable. All of that is
measurable and all of it is **intended**.

Quick Sync's real home is the Sync page. The Today copy is a **shortcut**, for
someone who has turned Today mode on and uses the page daily. With the mode off
the page is not activated, and the shortcut is inert along with it; the action
is still one click away where it lives. The dimming expresses the state of the
**page**, not of that one button — "enabled server-side, inert in CSS" is the
normal shape of that, not a defect.

Raised and reverted on 2026-07-28. `tests/test_today_quick_sync_clickable.py`
now fails if the section is removed from the dimming list again.

---

## Phase 4 — Panopto (course 43660)

Bounded by design: download all 36 recordings, transcribe 2–3.

- mp3 / mp4 / both, and `layout: match` vs `separate`.
- Transcript + subtitles on a small subset; the tiny model is installed and
  CUDA is provisioned, so run **both GPU and CPU** and confirm the CPU
  downgrade path works.
- Ignore a recording → it must persist in `panopto_ignored` and vanish from
  later analyses.
- A recording with mp3 present but srt missing must appear as
  **"new / missing outputs"**, not as up to date.
- Cancel mid-transcription → no orphaned worker process, no `.part` files.

---

## The sync matrix — a different space, not a mirrored one

`matrix build --kind sync` measures what a download matrix structurally cannot.
A download row is **configuration × configuration**: 24 switches the user picks,
which the run either honours or does not. A sync row's configuration is already
fixed — the folder's contract, baked in at download time and read back from
`.canvas_sync.db`, with no on-the-fly overrides by design. What varies at sync
time is the **world**: what changed since the last run, and which of it the user
accepts through which screen.

So the two dimensions have wildly different costs. A contract shape costs a full
download; a world state costs a snapshot restore plus a seed, in seconds. The
plan is a covering array over the cheap dimensions — 43 rows, 100% pairwise and
100% triple over `sync_mode × confirm × edited_update × readonly_target ×
renamed_row_dropped × renamed_ambiguous` — replayed against frozen folders.

```
python -m tests.audit matrix build --kind sync --save
python -m tests.audit matrix prepare --kind sync --lanes 4
python -m tests.audit matrix launch
```

Two rules the generator enforces, both learned the hard way:

- **Quick Sync can never be asked to cancel.** It has no review screen, so
  `sync_mode=quick, confirm=False` is unreachable — and a row that landed there
  would be held to an "untouched folder" expectation a Quick Sync legitimately
  violates.
- **A snapshot must hold enough tracked rows to seed** (`_MIN_SEED_ROWS = 20`).
  Almost every fixture works by picking a tracked file and doing something to
  it; the seeder just reports *"no eligible candidate in this folder"* and moves
  on, so a thin folder yields a row that seeds nothing, analyses nothing and
  **passes**. Measured: with cost as the only tie-break, 34 of 43 rows were
  assigned to a 2-file, 1-row snapshot.

**The contract shapes exist and are spread across.** Captured 2026-07-28:

| snapshot | rows | shape |
|---|---|---|
| `c43657_flat` | 50 | flat — where does a new file belong |
| `c43657_isolated` | 50 | modules + Canvas Content in its own folder |
| `c43657_study` | 43 | study filter — a filtered-out file must not come back as "new" |
| `c45899_base` | 215 | modules + all converters + archives + long paths |

Rows are spread across **interchangeable** snapshots (same capability SET) by
round-robin on the row index, not sent to the cheapest. Nothing in the plan
names a shape, so cost alone put every row on one snapshot and the other three
— a full download each to capture — were never synced at all. "Interchangeable"
is deliberately the capability *set* and not the match count: a row that needs
nothing in particular matches a 1-row folder and a 21,822-file one equally, and
spreading across those two is 26 seconds of restore for nothing.

Still missing: a **Panopto** shape. Recordings live in their own manifest table
and take no part in the rename/edit/restore fixtures, so it is the least
valuable of the five — but a sync that has to re-classify 36 recordings is
untested.

### Four things the sync lane got wrong, all found by smoke-testing two rows

Every one would have failed all 43 rows, and three of them looked like app bugs:

1. **The categories that matter are UNCHECKED by design.** "You've edited
   these" and "deleted locally" are unticked so the app never overwrites your
   work or resurrects a file you deleted — so a row seeding `edited_update`
   left the primary action `<button disabled>` and the flow spent 20 seconds
   timing out against it. Rows now tick the categories their fixtures land in.
2. **A sync with nothing to do never reaches Review.** It runs straight to
   "Sync done — everything up to date. Checked N files in this course — your
   folder already matches Canvas." That is a terminal screen and the right
   behaviour; treating it as a review screen produced "no host for key
   btn_sync_selected", which reads like the app lost its own button.
3. **A terminal screen persists between rows.** Navigating to
   `?mode=sync&step=1` does not clear the previous row's finished sync, so row
   2 came up on row 1's completion screen with no Analyze button anywhere. The
   flow now leaves via the screen's own "Go to front page", which is what a
   person does.
4. **A pruned folder leaves a broken pair, and one broken pair disables the
   whole page.** `sync_ui._can_sync` is `bool(sync_pairs) and not
   _has_missing_folders` — correct, the app should not sync a pair whose folder
   is gone. But the audit deletes each row's folder once its evidence is out,
   so every row after the first found Analyze disabled. A sync row now
   unregisters its pair as part of the same cleanup.

## Phase 5 — Always-on invariants

Run after **every** flow, whatever it was:

```bash
python -m tests.audit check invariants "<folder>" --capture <last capture>
```

It fails on: tracebacks in the log, unexpected warnings/errors, `.part`
leftovers, zero-byte deliveries, manifest rows pointing at nothing, content
files with no row, duplicate `local_path` claims, size/md5 baseline drift,
Streamlit exceptions on screen, and uncaught browser errors.

---

## Recording what you find

Mechanical findings are recorded by `check`. **Your own judgment findings** —
the ones that come from looking — go in the same ledger:

```bash
python -m tests.audit finding add "Review screen says 8 files, list shows 6" \
    --severity high --category ui-truth --oracles O1,O2 \
    --detail "..." --evidence @some.json --scenario <name>
```

Severity is about consequence to the user:

- `critical` — data loss, or a wrong file delivered and presented as correct
- `high` — a file that should exist does not, or is silently mis-categorised
- `medium` — the app says something untrue but the files are right
- `low` — cosmetic or recoverable
- `info` — worth recording, not wrong

Finish with **both** of these:

```bash
python -m tests.audit report build      # evidence for THIS run (HTML)
python -m tests.audit register update   # the cumulative work list
```

`report build` renders the run's own evidence. **`register update` is the one
that makes findings actionable**: it merges them into `tests/audit/AUDIT_FINDINGS.md`,
a hand-editable register checked into the repo where each finding carries a
status (`open` / `fixed` / `accepted` / `wontfix` / `invalid`) and any notes you
add. Findings are keyed by a fingerprint that ignores run-specific counts, so
"7 files survived" and "9 files survived" stay one entry whose count moved
rather than becoming two.

The audit refreshes the facts around a status and **never overwrites the status
itself**. Anything marked `fixed` that reappears is reported as a
**regression** — report that line first, it is the most valuable output the
register produces.

---

## Teardown

```bash
python -m tests.audit seed unlock "<folder>"   # clears read-only fixtures
python -m tests.audit browser close
python -m tests.audit app stop
```

The run directory is left intact — it **is** the evidence. Compare it against
the previous run to spot regressions.

**Check for orphaned apps at the end of a long session.** Lane workers stop
their own app in a `finally`, so a matrix never leaks one — but every manual
`app start` is yours to close, and a session that drives twenty one-off
scenarios can leave several Streamlit processes holding ports and an isolated
config dir. Three were still alive after the 2026-07-28 audit, from runs that
had finished hours earlier. They are harmless but they are not free: each holds
a port in the audit's band, so the next run's port scan works around them.

An audit-owned app is `python ... streamlit run app.py --server.port <N>`; the
real app is launched by `start.py` through pywebview and looks nothing like it,
so the two are never confused. Match the port back to a run with its
`run.json` before killing anything.

---

## Do NOT report: `Page X (1).html` beside `Page X.html` is not a duplicate

Course 43660 lands 7 pairs of identically-titled pages in one folder, the second
of each suffixed `(1)`. It looks exactly like the duplicate-download defect - the
log even shows the same title saved twice, 8 seconds apart, from two different
modules ("Klyngevejledning 1" and "Klyngevejledning 2").

**It is two different sets of Canvas pages that share titles**, and O4 settles it
in one query: 15 distinct entity ids in two consecutive runs
(`-279274..-279282` and `-280715..-280722`), different sizes, different md5s,
and the second set contains a `Klynge 8` the first does not. The teacher copied
the page set for the second cluster session. The app fetched 15 distinct pages
and disambiguated 7 title collisions, which is correct.

The reasoning that nearly filed it as a HIGH was "the same title, saved twice,
from two modules" - true, and not evidence of anything. **Consecutive id ranges
mean created together; a shared title means nothing at all.** Check O4 before
believing a duplicate: identity lives in the entity id, never in the name.

What IS real in that folder is the finding filed beside it - pages ignore the
isolation setting, so all 35 sit at the course root.

## Traps this harness already knows about

- Streamlit **lowercases widget keys** in the DOM class; every lookup lowercases.
- A checkbox's real `<input>` is **0×0 opacity 0** — read state from it, click
  the `<label>`.
- Download settings are **buttons, not checkboxes**; ON is a **chromatic border
  colour**, OFF is `rgba(255,255,255,0.1)`.
- Cards 2/3/4 **do not exist in the DOM until expanded**.
- A collapsed category expander renders **no rows**, so a review captured
  without expanding reports every category empty and every check passes.
- Course 43667 and others are **not in the Favorites view** — select courses
  from All Courses.
- `health 200` ≠ app ready. Readiness is confirmed from the browser.
- Windows consoles are CP1252; the CLI forces UTF-8 on stdout.
- Git Bash `ps -p <pid>` **cannot see a native Windows pid**, so a
  `until ! ps -p $pid` wait loop exits instantly and reports a lane finished
  while it is still downloading. Poll with PowerShell's `Get-Process`, or use
  `matrix lanes`.

---

## Checker defects found while preparing the matrix (2026-07-28)

Every one of these produced GREEN or produced a HIGH, and every one was in the
audit, not the product. They are recorded because the same mistakes are easy to
make again, and because a finding is only worth as much as the checker that
produced it.

**Scheduling — rows that tested nothing**

1. `capabilities()` called **every `ExternalTool` item Panopto**. Course 45899's
   twelve are Alma library citations; because it is a quarter the size of the
   one real Panopto course, the assignment sent it **25 of 29 Panopto rows and
   17 of 18 transcription rows** — hours of GPU time against a course with zero
   recordings. Panopto is now decided by the launch URL's **host**, mirroring
   `panopto.auth.panopto_base_from_url`. Only **43660** has recordings, in the
   whole account.
2. `assign_courses()` seeded its best score with `-1`, so a row no course could
   satisfy kept `_course_id = None` — and `jobs_from_plan()` **skipped it
   silently**. "73 runs, 100% coverage" would have executed 72.
3. **One course per row is not enough.** No course has zip AND video AND legacy
   Word AND code AND Panopto, so single-course assignment left **42
   factor-instances switched ON against a course that could not exercise
   them**. Rows now cover their wants with a SET of courses (greedy set cover):
   unexercised factors **42 → 10**, all `syllabus`, for +27% download.
4. **`syllabus` is unreachable**: not one course in the account has a syllabus
   body (verified directly against the API, not inferred). Those 10 rows still
   run — "Syllabus on, course has none" is a real state — and
   `unreachable_requirements` says so in the plan.

**Isolation — rows contaminating each other**

5. A lane reuses ONE app for all its rows, and the engine **skips a file that
   already exists at the matching size**, so the second row against a course
   downloaded nothing and passed. Folders are now pruned before a row and
   harvested + deleted after it (which is also what keeps peak disk under one
   course per lane instead of ~90 GB against 64.5 GB free).
6. The batch log is cleared **once per Streamlit session** and appended to
   after, and every row opens a new browser session — so a byte offset taken
   before the flow indexes a file that no longer exists. It silently discarded
   the **entire first course of a two-course row**, and the log-vs-disk check
   filed it as missing files. The mark now carries the file's head, and a
   session header inside the slice cuts to it.
7. A row's log covers **all** its courses; comparing it against ONE course's
   folder counted the others' writes. Split per course on the
   `--- Download: … (ID: n) ---` banner. After: 18 = 18 and 23 = 23, exactly.

**Checks that were dead, or wrong**

8. `expect` arrives in two shapes — flat from a matrix row, nested from a
   hand-written scenario — and checks read whichever the author had in mind.
   **Three were dead and all failed by passing**: `_conversions` never ran,
   `_count_coherence` ran when it should not have, and `_size_limit` /
   `_discovery_gap` never saw the size cap. Normalised once in `Evidence`.
9. **The size cap was never applied at all.** It lives in the global Settings
   dialog, not on the download page, so `configure` accepted the factor and
   applied none of it — half the plan ran the uncapped path twice.
   `DownloadFlow.set_size_cap` drives the real dialog and `_size_cap_applied`
   proves it landed from the engine's own parameter line.
10. The oracle swept `/files/(\d+)` over raw HTML while the product reads
    **`<a href>` only**. It matched an `<img>` banner and the
    `data-api-endpoint` beside it, so a 15 KB decorative image became "1 file
    exists on Canvas but was never tracked", HIGH. Parity is now asserted
    against `_extract_canvas_file_links` itself.
11. Inline ids were pooled with no record of which body they came from, so a
    run with announcements OFF was judged on announcement attachments.
12. A file reached through a body is recorded under a **synthetic** id —
    `make_secondary_id('attachment', fid) == -(fid + 90_000_000)` — and
    `canvas_file_id > 0` erased all nine of course 45899's, on a run whose log
    shows it fetching each one by name.
13. `_conversions` did not know the converters **deliberately skip vendored
    package directories**, and reported 11,818 `node_modules` files as
    unconverted beside 68 genuine conversion products.

**Launching**

14. `launch()` built `matrix worker --run X`, but `--run` is a **top-level**
    option and must precede the subcommand — every lane would have died in its
    first second, leaving only a line in a per-lane `worker.log`. Fixed, plus a
    startup-liveness check that raises with the workers' own output. It caught
    a real dead lane (a leftover app holding port 8800) the first time it ran.

---

## Nine more checker defects (2026-07-29)

Two things found these, and neither is "reading the code":

**Comparing two runs.** The sync matrix was re-run after the converted-file
fix, purely as a regression proof. Diffing it against the pre-fix run exposed
15-18 - none of them is visible in a single run's output, because every one
produces a plausible, specific, wrong finding rather than a crash.

**Chasing the survivors instead of accepting them.** 19-23 came from taking the
handful of findings that remained and asking, of each, *what exactly is the app
doing and is it wrong?* Every one turned out to be the audit. Two of them were
the app being reported for doing precisely what it was told (honouring a
max-file-size setting; refusing to bind a `.txt` to a `.sql`).

**They all invent findings rather than lose them, which is the worse
direction.** A missed defect costs you that defect; an invented one costs the
trust that makes every other finding worth reading. Two of these fabricated
*criticals*, and 21 of those were a class already sitting in the register
marked `invalid` from an earlier round - i.e. the register had already paid for
this lesson once.

15. **Only ONE of the seed plan's four expectation lists was forwarded.** The
    seeder plants partial-write artifacts, md5 drift, untracked files and rows
    whose file it removed, and publishes each as `expected_*` in the plan;
    `invariants` already knows to suppress all four, keyed off exactly those
    names. `_execute_sync` passed `expected_untracked` alone, so the other
    three suppressions were never fed and the suite reported the harness's own
    fixtures as defects - **40 findings per run**, whose paths matched the seed
    plan's lists ITEM FOR ITEM. Now one `seed_expectations(plan)` used by both
    the live row and the re-check.

16. **`_recheck_sync` passed the after-scan unconditionally.** `_execute_sync`
    gates it on `job.confirm` and carries a comment saying why - the outcome
    checks ask "was this restored / left alone / forked to `_NewVersion`", and
    against a folder that stopped at the REVIEW screen every answer is a
    fabricated failure. The re-check had lost the gate and the comment with it:
    **26 criticals out of thin air** on a run whose live pass reported none.
    The rule now lives in `_sync_outcome_disk` so there cannot be a third copy.

17. **A re-check fed sync rows the COMPLETION capture instead of the REVIEW
    capture.** `ui = _ui_capture(..._complete) or _ui_capture(..._review)` is
    right for a download row and wrong for a sync row - both files exist for a
    synced row, so the fallback never even reached the review one. Half the
    outcome checks read expectations *through* the selection (a ticked
    "deleted locally" row flips its fixture from `absent` to `restored`), so
    the app was reported for restoring exactly what the harness had just asked
    it to restore. **4 fabricated HIGHs.** The choice is now made by
    `job.kind`, not by which file happens to exist.

18. **`_selected_stems` collapsed its own tri-state contract** - and this is
    the ROOT of 17, which was patched first as a symptom. Its docstring says
    `None` means "no review capture" and is "different from 'nothing was
    selected' and must not be confused with it". The code said
    `if not ui_review: return None`, so **any** non-empty dict without a
    `courses` key - a completion capture, say - returned an empty set: "the
    user ticked nothing". The discriminator is the PRESENCE of the `courses`
    key. A review screen that genuinely lists no courses still carries it, so
    `set()` stays reachable and means what it says.

    Found by writing the test against the **documented** contract rather than
    the observed behaviour. It is worth doing that deliberately: a test written
    from the code can only ever agree with it.

19. **The seed plan declared ONE fact where there were two.** `_backdate`
    falsifies the manifest's `original_size` by a byte - that is its mechanism,
    without which `_is_canvas_newer` vetoes the change as a metadata touch - so
    every fixture calling it leaves the recorded SIZE diverging. Only
    `edited_update` also rewrites the file, so only it leaves the recorded MD5
    diverging. One combined `expected_md5_drift` got both halves wrong at once:
    `readonly_target`'s size went unsuppressed (**6 medium findings a run**,
    every one the seeder's own falsification), while `clean_update`'s md5 was
    over-suppressed - and `clean_update`'s whole premise is that original_md5
    STILL MATCHES, so a genuine mismatch there could not have been reported at
    all. Now `expected_size_drift` alongside it, with
    `_PERTURBS_RECORDED_SIZE` listing every kind that calls `_backdate` and a
    test that derives that list from the SOURCE rather than trusting it.

20. **A fixture asked for a match that cannot exist.** `renamed_row_dropped`
    asserts tier (c) adoption, which keys on unique **size + extension** - and
    it picked its candidate from every tracked row, including conversion
    products. A conversion product differs from its Canvas source in both
    ("x.js" -> "x_js.txt", plus the header the converter prepends), so the
    analyzer cannot match it and correctly says New. The audit reported that
    correct verdict as a HIGH, on the two rows where the pick happened to land
    on a `convert_code` output. **The guard already existed** - `readonly_target`
    filters on exactly this, with a comment explaining exactly this - it was
    simply written once and needed three times. Now `_direct_targets()`, used
    by all three, with a static test that they use it.

    Note the sibling needs it for the OPPOSITE reason:
    `renamed_row_dropped_unrecognisable` asserts a REFUSAL, and a conversion
    product is refused on the extension before the name floor is consulted - so
    it would have passed without testing the thing it exists to test. A fixture
    that passes for the wrong reason is the same defect as one that fails for
    the wrong reason, and it is harder to notice.

21. **The log slicer cannot split a BATCH-LEVEL phase.** `_log_for_course`
    assumes everything for a course sits between its banner and the next.
    Panopto breaks that: it runs ONCE for the whole batch, *after* every
    banner, so all of it landed in the LAST course's slice - including
    `Discovered 36 recording(s) in 'Indføring ...'`, a line about a different
    course. The delivery check read 43660's empty slice and reported the one
    course that had found all 36. Those lines name their course, so they are
    now routed by name, and taken OUT of the last course's body as well as
    added to the right one - routing in only one direction fixes half of it.

22. **A user's own setting reported as a product failure.** m041 ran with a
    5 MB cap; every recording on 43660 is 74-284 MB, so the size gate skipped
    all 36, logged a line for each and closed `found=36 downloaded=0`. Reading
    only the empty `panopto_manifest`, the check called that a discovery
    failure. **The fact cannot be split per course at all** - a size-gate line
    names a recording TITLE, and the gate runs in the download phase, after all
    discovery - so it lives only in the row's whole log. `Evidence.batch_log`
    existed for exactly this and had never been populated by anything; it is
    now, and `_panopto_delivery` falls back to it. Capped recordings leave the
    denominator, the same way an over-cap Canvas file already does.

23. **A declaration naming the wrong path.** Relocating a tracked file has two
    consequences - a dangling row AND an untracked new path - and only the row
    was declared. Worse, it was declared at the file's NEW path while the row
    still points at the OLD one, so it suppressed nothing. Both halves are now
    derived from `_RELOCATES_A_TRACKED_FILE`, and the dangling row is declared
    at `original_path`. The new path is deliberately still NOT suppressed: a
    row pointing there with no file is a genuine adoption failure, which is the
    one thing that check is for.

24. **Reading the app's error TALLY instead of its error LINES** - the largest
    single class the download matrix ever produced. `Course Finished | Errors:
    N` is **cumulative across the batch**, so the second course of a two-course
    row reports the first course's failures as its own. The check compared that
    N against the *current* course's locked files, concluded something
    unexplained had failed, and filed **32 HIGH `delivery` findings against
    courses whose own logs recorded not one failure**. The tell was in every one
    of them: `log_errors: []`. **A delivery HIGH that cannot name a failing file
    is not a delivery finding** - if the check cannot say what failed, it does
    not know that anything did.

    Fixed by giving the oracle an independent count: `_error_lines` counts
    `ERROR [kind] ...` straight off the raw text, so it is independent of the
    grammar *and* of the counter. The grammar independence is not decoration -
    `ERROR [Locked File]` only ever reached the events as a locked-name match
    and `ERROR [Discussion Dispatch Error]` only as `suspicious`, so
    `pl.of("error")` returned `[]` on **all 73 rows**. The check now reports two
    independent facts: the tally disagreeing with the log (`ui-truth`), and any
    error that is not a teacher-locked file (`delivery`, naming the item).

    Swept over all **115** per-course logs in the corpus: 28 counter mismatches,
    5 genuine delivery failures (all `Discussion Dispatch Error`, all with
    `counted == own` so the counter check correctly stays silent on them), 54
    all-locked, 28 clean. Blocking pile 32 → 5, and those 5 name the item.

### A register `invalid` can silence a DIFFERENT defect with the same sentence

`register.fingerprint` is `(category + digit-normalised + quote-stripped title)`,
so **"N content file(s) on disk with no manifest row" is one entry no matter
which files, or which cause**. That merge is deliberate and usually right - it
is what stops "7 files today, 9 next week" opening a new entry every run - but a
human `status` attaches to the entry, and a status is a silencer.

It bit on 2026-07-29. That entry was marked `invalid` in an earlier round with a
correct note: the file was `Compiled_External_Links.txt`, the single aggregate
`convert_urls` writes for a whole course, which legitimately has no manifest
row. The download matrix then produced the same sentence for a completely
different reason - `Grupper til Klyngevejledning 1-1.pdf`, an orphaned second
copy from the duplicate-download bug - and it arrived pre-silenced.

**Before trusting an `invalid`, check that the CURRENT evidence matches the
cause the note describes.** This is exactly why the register requires a note
saying *why*, not just a status: without the `Compiled_External_Links.txt`
sentence there would have been no way to notice the mismatch at all.

### Known redundancy: one Canvas condition, three findings (measured, NOT fixed)

The undeliverable discussion on course 43660 is reported three times per row:

| # | check | finding |
|---|---|---|
| 1 | generic net | `Unexpected bridged_warning ... Discussion dispatch failed for 'X': Not Found` |
| 2 | generic net | `Unexpected suspicious ... ERROR [Discussion Dispatch Error] ...` |
| 3 | dedicated (defect 24) | `Download finished with 1 unexplained error(s)` — names the item |

\#2 is the same log line as #3. Corpus-wide the `unexpected` channel holds 46
entries — 41 `bridged_warning` and 5 `suspicious` — and **all 5 `suspicious`
ones are `ERROR [kind]` lines**, i.e. precisely what `_error_lines` now claims
and the dedicated check reports. Dropping `ERROR [` lines from `unexpected`
would remove exactly that class and touch nothing else.

**Do not make that change on its own.** The generic net is unconditional; the
dedicated check is not. `_count_coherence` returns early unless
`disk["exists"]`, and its error loop runs over `courses_finished` — so a run
that dies mid-course logs `ERROR [...]` lines, never writes a `Course Finished`
line, and after the narrowing would have those errors reported by **nothing**.
That is a silent under-report, which is the worse direction.

The safe order is: (1) make the dedicated check total — report `error_lines`
even with no `courses_finished` entry; (2) sweep both directions over the
corpus; (3) only then narrow the net. Left as-is deliberately: the redundancy
costs a reader one duplicated line, and the rushed fix costs a missing error.

**Prefer a UNION over a preference when forwarding expectations**

`expected_untracked` was present on every plan and merely INCOMPLETE, so
`stored or derived` would have left every plan written before the fix reporting
the seeder's own renames for ever. `seed_expectations` unions the two, which is
what made 23 retroactive: sync run 2 went from 6 defects to **0** on a re-check,
with nothing re-run. Deriving beats storing wherever both are possible - which
is why `expected_untracked` was moved out of `seed()` and into `declarations()`
alongside its three siblings.

**How to reproduce this class of comparison**

```bash
python -m tests.audit --run <parent> matrix recheck              # re-derive, no re-running
python -m tests.audit --run <parent> finding classes --against as-run --defects-only
```
A re-check that reaches a *different verdict* than the live pass is a checker
defect by definition - the evidence is identical, so only the checker changed.
`finding classes --against` is that comparison, done at the level of a **class**
(a title with counts, quoted names and sizes normalised out), because 350
findings across 73 rows are a dozen causes with a row number attached. It reads
the LANES' ledgers, not the parent's: the PARENT `findings.jsonl` holds only
what `collect` merged, so an earlier run whose parent shows 1 finding may have
102 in its lanes.

Measured on the 2026-07-28 download matrix, this is what the whole session's
checker work looks like in one table - **253 findings / 12 classes → 45 / 5**:

| bucket | class | count |
|---|---|---|
| gone | Unexpected `bridged_warning`: Panopto LTI handshake did not reach a host | 168 |
| gone | Unexpected `suspicious`: Files tab listing failed, falling back to module scan | 10 |
| gone | Completion screen shows N but N files were saved | 6 |
| gone | N over-cap files have a manifest row despite never being downloaded | 5 |
| gone | N files exist on Canvas but were never tracked | 4 |
| gone | Flat organisation requested but N subfolders were created | 3 |
| gone | `convert_video` enabled but N source files survived conversion | 2 |
| gone | Panopto was requested but nothing was discovered | 1 |
| **appeared** | **N Canvas files were downloaded more than once in one run** | **2** |
| changed | N content files on disk with no manifest row | 12 → 1 |

Read `appeared` as carefully as `gone`. A class that appears after a checker
change is a new check firing on old evidence - which is the proof it *can* fire.
**A new check that appears with a count of zero is not coverage**, and this
table is where that shows up.

---

## Known limitation: the GPU lane carries the run

Measured on the 73-row plan, in MB-equivalents of work:

| lane | rows | work | transcription rows | mp4 rows |
|---|---|---|---|---|
| office | 19 | 20.6 GB | 0 | 1 |
| **gpu** | **18** | **118.7 GB** | **18** | **14** |
| free1 | 18 | 14.0 GB | 0 | 1 |
| free2 | 18 | 9.7 GB | 0 | 0 |

**73% of the work sits in one serial lane**, so the other three finish in a
couple of hours and idle while the GPU lane grinds for six or seven. The run
still completes and is resumable, which is why it was left alone mid-flight.

**Measured end to end on 2026-07-28/29: launch 18:34 → last row 04:0x, about
9.5 hours, 0 failures and 0 retries across all four lanes.** Plan it as an
overnight run and say so up front — that is the honest number to give before
starting, not "a few hours". The other three lanes were done by ~20:45.
Nothing about this is bumpy; it is simply long, it survives being left alone,
and `matrix lanes` answers "how far along" at any moment.

The cause is that `classify()` gives a row ONE lane class, so a transcription
row's *download* is serialised behind transcription too — and 14 of the 18 also
want mp4, which is where the bulk of those bytes are.

**A cross-lane mutex on the GPU does not fix this, and the first version of
this note wrongly said it would.** The audit drives the app through its UI; it
does not control *when* the app transcribes. `run_panopto_batch` runs discovery
→ download → transcription as one batch behind a single click, so a lock the
worker could take would have to span the whole row — which is exactly what a
dedicated serial lane already is. The constraint is the app's batch structure,
not the scheduler's.

**Nor is it a scheduling bug — `classify()` is already right.** Measured on the
saved plan: 2 mp4-only rows run *outside* the GPU lane, and 0 transcription rows
leak out of it. Splitting download-bound Panopto work from GPU work is exactly
what it already does.

**The lever is the covering array.** Pairwise coverage needs the pair
`(pan_out_txt=True, pan_out_mp4=True)` to appear **once**. The generated plan
contains it **14 times**:

| `txt` × `mp4` | rows |
|---|---|
| False × False | 55 |
| **True × True** | **14** |
| False × True | 2 |
| True × False | 2 |

IPOG's horizontal growth extends every existing row with the level covering the
most new tuples, and nothing tells it that `mp4=True` on a row that already has
`txt=True` costs 3.8 GB and half an hour. **The fix is a cost-aware tie-break in
horizontal growth**: among levels with equal coverage gain, take the cheaper —
and prefer not to pile an expensive level onto a row that is already expensive.
That is a change to the generator, so it changes the run list; do it between
runs, never during one, or the results cannot be compared against their own
history.

Failing that, accept it: the run completes and resumes.

Measured per-row: the all-on extreme (3 courses, every converter including a
21k-file zip extraction, all four Panopto outputs) takes ~90 minutes; a plain
single-course Panopto row with all four outputs ~30–35. So the GPU lane is
roughly **10–11 hours** while the other three finish in three or four.

---

## Verifying the two engine fixes (2026-07-28)

Both are recorded in `tests/audit/AUDIT_FINDINGS.md` with their measurements. What
follows is only the *recipe*, so either can be re-run after a change to the
write path.

### The Catch-All / Canvas Content duplicate — one file, one fetch

Course 46396 carries the fixture naturally: file ids **1784620** and **1807289**
are Files-tab files that are also announcement attachments.

```bash
python -m tests.audit run new --label dupfix
python -m tests.audit app start --port 8860
python -m tests.audit browser open --port 9460
# announcements ON, everything else OFF; secondary_isolated=false is the FLAT layout
python -m tests.audit flow download dupA --courses 46396 --config @cfg_dup_modeA.json
```

Then assert, from `<run>/downloads/debug_log.txt` and the folder's
`.canvas_sync.db`:

| what | flat | isolate |
|---|---|---|
| `grep -c "files/1784620/download"` | **1** | **1** |
| `Files-tab sweep skipping Canvas Content attachment` | **2** | 0 |
| `Copying already-downloaded file` | 0 | **2** |
| copies of that content on disk | 1 per Canvas id | 2 (Files-tab + attachment, by design) |
| manifest rows with no file / files with no row | **0 / 0** | **0 / 0** |

**Run the SAME download a second time into the same folder.** That is the case
the fix is really about: before the phase reorder, run 2 re-fetched the file
into the course root and recreated the orphan. After it, the repeat run makes
**zero HTTP requests** (`grep -c "Requesting URL"` → 0) and the counts above are
unchanged.

Then repeat the whole thing with `secondary_isolated=true` in a **fresh run
directory** — the two layouts produce different (both correct) folder shapes and
mixing them in one folder proves nothing.

Then two more fresh run directories: `secondary_isolated=true` (the isolate
layout, which legitimately keeps two copies — the check there is that only ONE
of them was fetched), and `"mode": "flat"`. **Flat is not optional cover.**
`_download_secondary_content` is a sibling of the mode dispatch, so it runs in
flat and folder-structure mode too — where the Files-tab sweep is the primary
loop itself and Canvas Content has to be moved ahead of *it*. The first version
of the fix passed every modules-mode check while flat still fetched twice.

### Local edits to a converted file survive a sync

```bash
python -m tests.audit snapshot restore c45899_base
python -m tests.audit seed apply --kinds edited_update
python -m tests.audit flow sync fixv --select updated_modified
```

Assert the edited outputs' md5 is **unchanged** and a `_NewVersion` sibling
exists beside each. Hash the files before seeding — the check is byte equality,
not "the file is still there".

**The snapshot predates the manifest's product-md5 record, and that is the
point**: it is the only state that catches a guard which silently depends on
data the fix itself started writing. Do not "fix" the fixture by re-recording
it.

### The duplicate-fetch check, and why a retry is not a duplicate

`crosscheck._one_fetch_per_file` is the standing guard for the finding above.
It counts **first-attempt** fetches per Canvas file id and reports any id that
went to the network twice.

Excluding retries is not a detail - it is the whole difference between a usable
check and a muted one. A rate limit, a 5xx or a dropped connection re-requests
the *same* download as `Attempt 2`; counting those would make every flaky
network look like the defect, someone would suppress the check, and the real
thing would walk straight through it.

Validate any change to it **in both directions against real logs**, never
against a fixture alone:

```bash
# fires, naming {1784620: 2, 1807289: 2}
_audit_runs/20260728_145153_matrix__office/evidence/logs/m025_c46396_course.txt
# silent
_audit_runs/2026072{8_232643_dupfix,8_233144_dupfixB,9_000133_dupflat}/downloads/debug_log.txt
```

Swept over all 92 per-course logs in the matrix it fires on exactly the 2 that
carry the defect, with 0 false positives - and the corpus contains exactly 1
real retry line, so the exclusion is exercised rather than assumed.

### Do NOT add the duplicate-fetch check to the sync suite

It would never fire, and a check that cannot fire is worse than no check: it
reads as coverage on the report and provides none.

The two flows log at different levels, measured 2026-07-29. A download run's
log carries the HTTP layer - `Requesting URL ... (Attempt n)`, `Response
Status`, `File Saved` - which is what the check counts. A **sync** run's
per-folder `debug_log.txt` records its *decisions* instead: `[UPDATE-CLEAN]`,
`[UPDATE-EDIT]`, `[SYNCED]`, the plan rows, the manifest updates. Zero
`Requesting URL` lines in a 50-line log covering two real re-downloads.

So on the sync side O2 can verify **what the engine decided**, and cannot
verify **what it fetched**. Anything about network behaviour there has to come
from O3/O4 (a file appeared, a row moved), not from the log. Adding HTTP
logging to `sync/execution.py` purely to serve the audit was considered and
declined - that log is user-facing, and no reported defect needs it.

### Two KINDS of stale finding, and only one of them re-check can fix

A finding is a function of (evidence, checker). `matrix recheck` replaces the
checker. **Nothing replaces the evidence except running the row again**, so read
a long matrix with both in mind:

- **Checker-stale** - the row ran fine, the checker was wrong at the time and
  has since been fixed. `recheck` removes these. Measured on the 2026-07-28
  download matrix: **550 findings -> 347**, defects **253 -> 46**, with entire
  classes vanishing (168 Panopto LTI handshake warnings, 10 "Files tab listing
  failed", 6 completion-count mismatches, 4 "exist on Canvas but were never
  tracked", 3 flat-layout violations, 2 convert_video sources).
- **Product-stale** - the row's LOG was written by the code as it was when the
  lane started, and lanes run with `--server.fileWatcherType=none`, so a product
  fix landing mid-run cannot appear until a fresh run. `recheck` cannot help;
  re-deriving a finding from an old log just re-reads the old behaviour.

Three of the 2026-07-28 matrix's surviving classes are product-stale, and each
is identifiable by the fix already being in the tree:

| surviving class | already fixed by |
|---|---|
| `Discussion dispatch failed ... Not Found` (5+5) | `resolve_discussion_topic` - its docstring cites the very topic these rows name, because it was diagnosed FROM this matrix |
| `Download finished with N error(s)` (32 high) | `app.py`'s per-course `_err_count_done`. Verified on m032: the batch log holds **2** `ERROR [` lines total and **both** course-finished lines claim "Errors: 2" - the second course contributed none |
| `N Canvas file(s) were downloaded more than once` (2) | the Canvas-Content-before-every-sweep reorder |

So the honest headline for a matrix is **the rechecked count, annotated with
which surviving classes are already fixed** - not the as-run count, and not the
rechecked count presented as if it were current behaviour.

### If you edit engine source while a matrix lane is running

The lanes launch Streamlit with `--server.fileWatcherType=none`, so a running
lane keeps the code it started with and the matrix stays internally consistent.
The exception is `parallel._recover`, which restarts the app after a **crashed
row** — those rows and everything after them would run the new code. Check
`matrix lanes` for a non-zero `failed`/`retried` before trusting a mixed run.
