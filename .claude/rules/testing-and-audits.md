---
paths:
  - "tests/**"
  - "scripts/_mutate_*.py"
  - "scripts/verify_architecture.py"
---

# Tests, mutation harnesses and audit oracles

> Extracted from CLAUDE.md. Loads only when Claude opens a matching file.
> Each entry states the mechanism, the measurement, and why the obvious fix is wrong.

## An audit oracle that is BLIND does not under-report - it INVENTS (2026-08-21)
The audit's log oracle named three tags the app has never emitted
(`UPDATE-MODIFIED` / `DELETED-CANVAS` / `DELETED-LOCAL` against the app's
`UPDATE-EDIT` / `CANVAS-DEL` / `LOCAL-DEL`, which it has written since
2026-06-02, two months before the oracle was authored). So every per-file row for
three of the six analysis categories was dropped on the floor, silently, from the
suite's first day. **This entry is about what was built ON that, because that is
the part that cost a session.**
- **A defect in the audit was written down as a fact about the PRODUCT.** A later
  session measured the effect - *"a run whose analysis reported 2
  deleted-on-Canvas and 2 ignored: the log contained zero rows for either"* - and
  recorded the conclusion in `crosscheck._LOG_DETAILED_CATS` as the app only
  logging two categories per file. The app's own source says the opposite two
  lines above the loop (*"One line per file, for EVERY category the analyzer
  produced"*). That false premise then routed four of six categories to the
  review screen as their ONLY witness.
- **And the review screen does not exist on a Quick Sync row.** Which is how a
  43-row sync matrix produced **14 HIGH "was not offered" findings** - across
  `updated_modified` and `deleted_on_canvas`, the categories that decide whether
  a student's edited file is protected - against an app that had classified every
  one of them correctly and named the files in its own log.
- **The blind guard covered ONE oracle** (`oracle == "O2"`), so an O1 verdict
  with no rows asserted that O1 *"listed other files under X and this was not
  among them"* - unchecked - and filled `peers_in_category` from the LOG, i.e.
  from the oracle it had not consulted. For O1-only categories that list is empty
  by construction, so the finding's own evidence contradicted its sentence and an
  empty list read as *"there simply were none"*.
- **"No rows" is TWO OPPOSITE VERDICTS and the rows cannot tell them apart**: the
  app placed nothing there (so "not offered" is right), or the oracle could not
  see what it placed (so it is a fabrication). The arbiter is the app's own
  `Analysis complete` tally, written by the same function in the same run - which
  is also the guard the suite now runs on every row
  (`_log_tally_matches_its_own_rows`): `candel: 2` with zero parsed rows would
  have fired on day one.
- **A vocabulary written twice drifts, so it is now written once**: `_LOG_CAT` is
  imported from `oracles.log.ANALYSIS_ROW_TAGS`, `_LOG_DETAILED_CATS` is derived
  from its values, and `tests/test_audit_log_tag_vocabulary.py` reads the tags
  straight out of `sync/analysis.py` so an app-side rename fails the SUITE in the
  commit that makes it. Same lesson as `make_long_path`'s duplicate in
  `core/sync_manager.py` and the three AppleScript escapers.
- **The audit's comparison primitives were weaker than the code they audit.**
  `core.sync_manager._path_key` folds to NFC; `crosscheck._norm`/`_stem`/`_key`
  did not. Measured inside a SINGLE log line: the app wrote the Canvas display
  name `Svarark - Gode råd til projektet.docx` as **NFD** and the local path of
  the same file as **NFC**, while the seed plan is NFC throughout. Danish `å`
  decomposes and `ø`/`æ` do not, which is why it presents as random.
- **A re-check must be fed exactly what the live pass was fed.** `recheck` fell
  back from the review capture to the COMPLETION capture for sync rows; the probe
  runs its review extraction against whatever screen is showing, so a completion
  capture carries `review: {courses: [], seen: {categoryContainers: 0}}` -
  truthy, structurally empty, and an impostor to anything that only tests for
  truthiness. 29 HIGH on re-check against 20 live. `_selected_stems` had the
  mirror of it, answering `set()` ("ticked nothing") where its contract demands
  `None` ("unknown") - the direction that HIDES defects. Its test passed for a
  year because it fed a hand-made capture rather than one the harness had
  written; the real ones were on disk the whole time.
- **The result: 29 HIGH -> 13, ZERO new findings**, on both the sync matrix and
  the 275-finding download matrix. The 13 that survived were a REAL defect (see
  the section above), which is the argument for fixing a blind oracle BEFORE
  running a matrix: while it was blind, the one genuine finding in its categories
  was indistinguishable from the fourteen it had invented.
- **`RUNBOOK.md` checker defect 26 had already found the tag mismatch on
  2026-08-08, prescribed the exact safe fix order, and said "fix it BEFORE the
  next sync matrix". The matrix ran first.** The delay is not what it cost: a
  blind oracle makes every other finding in its categories unfalsifiable, so the
  43-row run had to be re-adjudicated by hand afterwards - more work than the fix.
  Defect 26 also judged it *"not a false-finding source today"*, on the reasoning
  that the checker "correctly falls back to the review screen". That fallback is
  only correct when a review screen exists.

## A test skipped on YOUR platform runs only where you cannot see it (2026-08-22)
`tests/test_longpath_gate_check.py:test_off_windows_is_not_applicable_and_exits_clean`
is `@skipif(os.name == "nt")`. It was written on Windows, so it was skipped in
every run its author made, and it ran for the first time when the macOS session
pulled - where it **failed immediately**: `main()` took no `argv`, so
`parse_args()` read `sys.argv`, which under pytest is the RUNNER's arguments,
and it died on `-q` with `SystemExit(2)`.
- **The rule: a platform-guarded test is only covered by the platform it is NOT
  skipped on.** Writing `skipif(os.name == "nt")` on Windows is writing a test
  you have structurally guaranteed you will never execute. Same shape as
  `pdf_looks_real` landing on two of three delete sites, one level up: not a fix
  that reached too few places, but a GUARD that ran in too few.
- **The remedy is cheap and it is a habit, not a mechanism**: when you add a
  test that skips on your own platform, say so in the handoff so the other
  session runs it. Cross-platform work in this repo is now routinely two
  sessions on two machines, and the other one is the only place that guard
  exists.
- **`main()` must take `argv`** for exactly this reason - a CLI entry point that
  parses `sys.argv` implicitly cannot be called in-process by anything, and the
  first caller is always a test. `parse_args(argv)` with `argv=None` defaulting
  to `sys.argv[1:]` costs nothing and keeps the shell behaviour identical.
- The wider lesson this session kept re-learning, in three separate places: the
  laptop's guards were blind (`os.makedirs` invisible to a census, a scanner
  window measured in physical lines that a comment pushed the target out of),
  the audit's oracles were blind at depth, and this test never ran. **A guard
  that passes gets recorded as protection**, so a blind one is worse than none.

## A documented test that was never committed measures nothing (2026-08-21)
`tests/test_website_social_proof.py` and `scripts/_mutate_social_proof.py` were
described by **four** marketing documents, including a recorded "15 of 15
mutations caught". Neither file had ever existed in any commit. Same decay class
as a stale mutation anchor, one level worse: an anchor that no longer resolves
can at least be detected by `tests/test_mutation_anchors.py`, whereas a file that
was never written is invisible to it.
- **Writing them found a real drift** (the homepage and `llms.txt` disagreeing),
  which is the argument for the class of guard - but **the product owner then
  ruled the guard itself wrong** and both files were deleted the same day. The
  published figure is a rounded-down floor on a number that only grows, so any
  hard-coded ceiling is wrong the week after it is written. **Do not re-open the
  installs-vs-downloads question**; it is settled in `marketing/FINDINGS.md`.
- The reusable half: when a document names a test, **check the file exists**
  before quoting its score. Three of this session's findings were documents
  describing something that was not there - this one, the register header
  ("19 open", actually 7), and "the GitHub social preview is not set".
- **CORRECTED 2026-08-23, and the correction is the better lesson.** That last
  one was re-stated here as *"it is set, and it is the 1024x1024 app icon on a
  surface that renders 2:1"* - **also wrong, and wrong in a way that reads as
  authoritative because it names a size**. Measured properly: the repo's
  `og:image` is on `repository-images.githubusercontent.com`, i.e. the
  CUSTOM-upload host, and that URL answers **HTTP 404 `WebContentNotFound`**.
  The record exists and the blob does not, most likely orphaned by the
  `birkls` -> `BrkBuilds` move. One fact explaining three symptoms: an empty box
  in GitHub's own Settings UI, an upload that "does not show up", and a shared
  link with no card image. **Two documented claims about one field, both from
  reading rather than fetching, both wrong** - so the rule is not merely "check
  the file exists" but **resolve the URL**: `curl -sI <og:image>` and require
  `200`. Full diagnosis and the repair order (remove the image FIRST, then
  upload) in `marketing/FINDINGS.md`.
- **RESOLVED 2026-08-27, by GitHub, after the operator escalated with exactly
  the evidence above.** The write path was repaired server-side and the upload
  now takes: `og:image` is on `repository-images.githubusercontent.com` and
  answers **200**, PNG **1280x640**, 384,637 bytes. **The lesson is unchanged
  and is in fact what confirmed the fix** - the same two-step check (read the
  tag, then resolve the URL) is the only thing that can tell "the image is
  set" from "a record exists and the blob does not", and those two states are
  identical from GitHub's own Settings UI. Expected pass is now the custom host
  plus 200; `opengraph.githubassets.com` plus 200 means the custom image was
  removed again, and anything plus 404 is the broken state returning.

## The Windows suite was RED and nothing could see it - there was no Windows CI (2026-08-23)
Found by running the suite on Windows for the first time in this repo's life. **5 failed, 4367 passed** at `c1f218b`, and `.github/workflows/` held only `test-macos.yml` and `build-macos.yml`. **Windows is the large majority of installs and had zero automated coverage; the platform that had coverage is the RENTED one.**
- **All five failures were TEST-side, not product-side**, and that distinction is the reusable part: four in `tests/test_shortcut_ownership.py` hard-coded `.webloc` while `_create_link` derives `.url` from `platform.system()`, so fixture and method compared two different paths; one in `tests/test_office_instance_scoping.py` asserted a warning that a correct `sys.platform != 'darwin'` guard prevents. The PRODUCT was verified correct on Windows separately - driving the real `_create_link` against real `.url` files gave 8/8 shallow and 8/8 at a 265-character path with `LongPathsEnabled=0`.
- **A RED suite silently DISARMS the mutation harnesses, and that is worse than the failures.** `scripts/_mutate_shortcut_ownership.py` refuses with `BASELINE IS RED - fix that first` (exit 2), correctly - so the recorded **9/9** protecting the 2026-08-22 shortcut-ownership fix was **unmeasurable on Windows** for as long as the suite stayed red. It is 9/9 here now, measured for the first time.
- **This is one degree worse than the class this file already records.** "A test skipped on YOUR platform runs only where you cannot see it" is about a SKIP; these did not skip, they FAILED, and no machine on earth was running them.
- **`.github/workflows/test-windows.yml`** now runs the unit suite plus the architecture audit on `windows-latest`, with the failure history written into the file so nobody deletes it as redundant. It prints `scripts/check_longpath_gate.py`'s verdict as CONTEXT (not a failure) because the long-path tests skip their behavioural half when the gate is masked, and it names the Windows-relevant guards in a final step so a future silent SKIP is visible.
- **PYTHON VERSION, and it is deliberately NOT a blocker (product owner, 2026-08-23):** both CI jobs pin **3.11** while releases are built with **3.13** (`python313.dll` in the bundle). The operator runs the full suite locally in the IDE on the app's own Python, which is what actually closes the gap. Do not re-raise this as a finding; adding 3.13 to the matrix is a nice-to-have, not a defect.

### Corollaries found while fixing it - each is a class, not an instance
- **DRIVE the platform branch, do not skip it.** The cheap fix for the office test was `skipif(sys.platform != "darwin")`. That is wrong here for the reason this file already gives - a platform-guarded test is only covered by the platform it is NOT skipped on - and **macOS is the rare machine**. So the test now ANSWERS the guard (`monkeypatch.setattr(br.sys, "platform", "darwin")`), the technique this file documents for driving macOS branches from Windows. Safe because the function returns at the very next statement; `subprocess.run` is patched to raise if anything executes, which pins it. A SECOND test covers the arm nothing had: off macOS it must be a **silent** no-op, not a warning - without it, "just move the platform guard below the unknown-name check" looks correct while making every non-macOS run emit a warning the audit's log oracle turns into a finding.
- **A test that hard-codes ONE platform's format should usually be parametrised over BOTH.** `shared/shortcuts.py` documents that readers accept `.url` and `.webloc` on ANY host (a folder synced on Windows and opened on macOS carries `.url`), so exercising only the native suffix tested half the contract - and specifically the cross-platform-adoption half. The format-agnostic checks now run both; only the four `_create_link` sites use `NATIVE_EXT`. 19 tests -> 21, and strictly more coverage than before the file was broken.
- **A per-FUNCTION census is not a per-CALL-SITE census.** `tests/test_office_automation_lock_coverage.py` asked `"always" in _lock_kinds(fn)`, i.e. *does this function contain a lock anywhere*. `_terminate_gallery_stuck` has TWO `with _office_app_lock(app):` blocks, so the mutant unlocking the first left the second in place and **SURVIVED**. Same "count the sites" discipline as `pdf_looks_real` landing on two of three delete sites, one level in. `_unlocked_osascript_calls()` now walks the function tracking lexical lock state; it carries its own positive control built from the surviving mutant's exact shape, because a checker that cannot say no is not a checker.
- **The behavioural proof of a POSIX-only primitive leaves a structural gap worth closing.** `test_the_conditional_helper_REALLY_LOCKS...` is necessarily macOS-only (flock), so a mutant reducing `_office_app_lock_unless` to a bare `yield` - unlocking all EIGHT call sites - was visible only on the rented machine. An AST test now asserts both arms survive on every platform. `scripts/_mutate_office_lock_coverage.py`: **11/13 -> 13/13 on Windows**, and two of those are now caught without a Mac at all.

## Do NOT edit source while a background test suite is running (2026-08-23)
Walked into this and lost a cycle to it. `inspect.getsource` resolves by LINE NUMBER against the file on disk, so editing a module mid-run makes tests that anchor on source read the wrong lines. It surfaced as `tests/test_folder_scope.py::test_the_metadata_scan_drops_out_of_scope_items` failing with *"the page/link branch moved - re-anchor"* - which reads exactly like a real regression in a guard, and passes in isolation. Same family as this file's existing warning about a concurrent COMMIT capturing a mutant, and the same remedy: **freeze the tree for the duration of the run**, and before believing any suite failure that follows an edit or a mutation pass, check the SOURCE rather than the test output.

## Auditing this app: two playbooks, and the one input that matters
- **THIS FILE IS THE CROSS-MACHINE MEMORY, and that is why it is enormous.** The operator works from at least three checkouts (laptop, main desktop, and a rented macOS audit box) and any per-session assistant memory lives OUTSIDE the repo, so it does not travel and does not survive a machine being reimaged - which the audit box periodically is. Anything durable therefore belongs here, in `tests/audit/AUDIT_FINDINGS.md`, `tests/audit/MAC_RUNBOOK.md` or `AUDIT_PLAYBOOK.md`, written mechanism-first (what breaks, the measurement, why the obvious fix is wrong) rather than as a summary. Assistant memory is for facts about the PERSON and the working relationship; anything the repo should own goes in the repo, and goes in the same commit as the fix.
- **Marketing, SEO and the launch live in `marketing/`, not here.** Same rule and same reason as the audit documents above: a website change, a search-visibility finding or a positioning decision is durable, so it belongs in the repo and travels between machines. `marketing/README.md` is the index; **`FINDINGS.md`** is the register (every defect found, its evidence, its status, and why anything deferred was deferred); **`STRATEGY.md`** holds the SETTLED decisions; **`SITE_RUNBOOK.md`** is what to read before touching `docs/`; **`PLAYBOOK.md`** is the off-site plan; **`CHANGELOG.md`** records what exists now. Four facts from it that bite ENGINEERING and not just copy: (a) the website must advertise the newest shipped **TAG**, never `version.py`, which `tests/test_version_leads_tags.py` deliberately keeps AHEAD of every tag - the homepage advertised a 2.0.2 nobody could download; (b) a `<button>` that receives a scripted `.href` is a **dead control**, and that shipped - both download buttons on `/releases.html` did nothing for six days after three `<a href="#">` were converted to buttons and only one got a handler; (c) `preload="none"` is **ignored while `autoplay` is present**, so deferring a video means withholding the `src`, which took mobile LCP from 5300 ms to 2764 ms; (d) student-facing copy says **"Canvas", never "LMS"** - a product-owner ruling that overrides SEO instinct and applies to app strings too, not only the website.

- **`AUDIT_PLAYBOOK.md`** (repo root) - the OFFLINE crash/data-loss audit: the six techniques ranked by what they actually returned, the twelve sweeps that came back clean and must not be repeated, the reproduce→fix→test→mutate→verify workflow, and the mutation-harness hazards that cost this session two wasted passes.
- **`tests/audit/README.md` + `RUNBOOK.md`**, driven by **`.claude/skills/audit-live/SKILL.md`** - the LIVE audit: the real app, a real browser, real Canvas, five oracles.
- **The primary input to an offline audit is THIS FILE.** Every finding of the 2026-08-08 sweep was a class already documented here, surviving in a module the original fix did not reach. So the productive question is never "what could be wrong?" but **"which module did the last fix for this class NOT reach?"**
- **`.claude/skills/` is deliberately UN-ignored** in `.gitignore` (`.claude/*` + `!.claude/skills/`). `tests/test_audit_docs_match_cli.py` asserts the existence *and content* of the audit skill, so ignoring the whole tree made four tests unpassable on a fresh clone while presenting as a missing file rather than a packaging mistake. Note `.claude/*` and not `.claude/` - git will not descend into an excluded DIRECTORY, so a negation inside one can never re-include it.
- **The macOS audit has its own four files** (2026-08-10), because it runs on a RENTED machine where a wrong command costs money: `tests/audit/MAC_AUDIT_GUIDE.md` (renting, remote access, what to do the night before), `MAC_RUNBOOK.md` (the phase order and the traps), `MAC_AUDIT_PROMPT.md` (the agent's brief), plus `scripts/mac_audit_bootstrap.sh` (bare macOS → ready, idempotent because it is run once per OS install), `scripts/mac_audit_doctor.py` (preflight; refuses to pass outside an Aqua session) and `scripts/mac_smoke.py` (every macOS check that needs no human eye). Guarded by `tests/test_mac_audit_tooling.py`.
- **A documented command must satisfy its required POSITIONALS and required FLAGS, not just have real flag names.** `tests/test_audit_docs_match_cli.py` originally checked only that the flags *present* existed - which cannot notice an omitted one. Four real defects were hiding behind that: `finding add` (positional `title`), `flow download` (positional `name`), `seed apply` (positional `folder`) and `check download` (positional `folder` **and** required `--expect`). Every one of them is copy-pasted verbatim by a session that then loses time to an argparse error. The extractor also has to JOIN backslash continuations first - without that a correct multi-line command reads as missing everything after line one.

## Never run a mutation pass on a tree something might COMMIT (2026-08-10)
**The thing that commits is usually a SECOND CLAUDE SESSION, not a background job** (recorded 2026-08-11, after it was stated mid-audit: *"just letting you know a parallel session is editing right now aswell."*). This operator routinely runs more than one session against the SAME checkout - `/Users/m1/Canvas_Downloader`, not separate worktrees - and that changes three things:
- **The mutation window is not yours to control.** The measured incident below reads as a warning about background jobs; the realistic cause is another agent committing while your mutant is on disk.
- **Shared documents collide.** `CLAUDE.md`, `tests/audit/AUDIT_FINDINGS.md` and the runbooks are exactly what two sessions both want to append to, and all are large enough that a clobber is invisible afterwards. If another session is live, do the code and the tests and HAND the operator the prose rather than appending it yourself.
- **`git status` is not a picture of YOUR work.** A session-start snapshot said "clean" while six files were modified by the time it was read. Never read unexpected modifications as stale work to tidy up, and never `git add -A` blind - scope every git command to your own paths.
Check before a mutation pass and before a shared-doc write. If a pass already ran, `git log --since` for commits inside the window and re-run the FULL suite, not just the targeted file.

A mutation pass deliberately writes broken code into the working tree and restores it seconds later. A commit that lands inside that window captures the mutant, and the script's own `restore()` reports success **truthfully** - it simply ran after the snapshot was already taken.
- **Measured**: `panopto/shortcut.py` was committed with `kind_extensions` returning only the native suffix, so a folder synced on Windows would be re-produced under a second name on macOS instead of adopted - cross-platform shortcut adoption silently broken in HEAD, in the exact subsystem being prepared for a macOS audit.
- **The full suite is the detector, and only the full suite.** The targeted file passed; three `test_panopto_shortcut.py` tests - in a file the mutation pass never named - are what exposed it. **Re-run the whole suite after every mutation pass.**
- **The same commit captured a test's temp file.** A guard-on-the-guard wrote `_macos_branch_probe_tmp.py` into the REPO ROOT for the few milliseconds an assertion took. A test must never put a file where a concurrent `git add -A` can see it: give the scanner a root parameter and point the test at `tmp_path`.
- Also settled: a targeted mutation run (`pytest <file> -x -k <subset>`) costs **0.9 s** against ~75 s for the whole file, because the app-graph import dominates. If a targeted run cannot catch a mutant, no amount of unrelated tests would have.

### A recorded mutation score decays SILENTLY, because the anchors are literal strings (2026-08-13)
`scripts/_mutate_office_guard.py` mutates by exact string replacement, so a mutant whose `old` text has moved cannot run at all - and the score written down when it was last run keeps being quoted.
- **Measured**: `f6caf04` wrote the concurrency set and recorded **8/9**; `70ce78c` then inserted `_note_office_preexisting(app_name)` between `with _office_app_lock(app_name):` and `return _run_applescript_locked(`, invalidating the anchor for *"run_applescript stops taking the lock"*. From that commit the mutant could not run on any platform, while `tests/audit/MAC_OFFICE_FIXES.md` still said 8/9. The quit set WAS re-anchored in the same window (`7a2a674`) - so this rots one set at a time, and only whoever re-runs the pass would see it.
- **Re-anchored by hand and run: CAUGHT.** So the protection was real (`test_run_applescript_takes_the_lock` asserts the `with` through the AST); only the harness had gone stale. **Distinguish those two outcomes before concluding anything** - "anchor missing" is not "untested", it is "unmeasured".
- **`tests/test_mutation_anchors.py` makes staleness fail the SUITE**, in the same commit that moves the code, rather than at the next deliberate mutation pass. It discovers `*_MUTANTS` sets by NAME so a new set is covered without anyone extending it, checks each `old` still resolves, that each mutant actually changes the file, and that every `*_TEST` path exists (a set pointed at a deleted test file reports every mutant as *caught*, because pytest exits non-zero on a missing path). It has a positive control: breaking one anchor makes it fail.
- **It is NOT a substitute for the pass.** An anchor can resolve and the mutant still survive. It only guarantees that a recorded score describes mutants that could actually run.
- **Windows will report survivors that macOS catches, and that is not a regression.** Three of the concurrency mutants are covered only by `skipif(sys.platform != "darwin")` tests (the flock path), so a Windows pass reads 5/9 where macOS reads 8/9. Check *which* survivors before treating a number as a finding.
- **Writing a control for this needs the file tools, not a heredoc**: the anchors are full of literal `\n` two-character sequences and this shell mangles backslashes - the first version of the control silently replaced nothing and "passed", which is exactly the failure it exists to catch. That hazard is already recorded under the institution picker; it applies to every anchor-shaped test.

### The mutation window DESTROYS work too, and that direction is the silent one (2026-08-13)
The recorded hazard is a commit landing mid-pass and CAPTURING a mutant. The mirror is worse, because nothing reports it: `_clean()` runs ONCE at the start and restore was a hard `git checkout --`, so **an edit made to a target while the pass is running was restored away with no message**, and the pass went on reporting truthfully afterwards. Measured by walking into it: a docstring written into `engine/applescript_bridge.py` during a background pass, gone - noticed only because the editor warned the file had changed underneath it.
- **The guard is a per-mutant snapshot comparison, not a second `_clean()`**: before applying each mutant the source must still equal the snapshot taken at the start, or the pass ABORTS (rc 3) naming the file and the mutant.
- **On abort it restores NOTHING, and that is the whole point.** The check runs BEFORE the write and the previous mutant was already restored, so no mutant is on disk - the only thing there is somebody else's edit, and writing the snapshot over it is exactly the data loss being prevented. **The first version of the guard called `_restore()` on the abort path and destroyed the edit anyway**; the control is what caught it, not review.
- **Restore is from the snapshot, not from git.** `git checkout --` depends on HEAD still being what the pass started from (which the 2026-08-10 incident shows it may not be) and rewrites every target whether or not the pass touched it.
- A control has to edit the file **in the gap between two mutants** - waiting for it to go mutated, then back to original. Writing at t=0 is caught by the clean check instead, which is a different guard; the first version of that control did exactly that and reported a failure that was not one.
- **AN INTERRUPTED PASS RESTORES A STALE SNAPSHOT OVER NEWER WORK, and the abort guard cannot stop it (walked into 2026-08-22).** That guard runs BEFORE applying a mutant; the `finally` AFTER each mutant restores unconditionally. So a pass whose python outlives your kill writes back the snapshot it took at ITS start - which predates every edit you have made since. The compounding is what makes it expensive: a mutant that HANGS (here, `respect_retry_after_header=True` obeying a `Retry-After: 86400`) forces a kill from outside -> the stale restore silently reverted a fix AND its docstring -> the next full suite showed **4 failures**, three of them in tests that had passed minutes earlier -> which reads exactly like a product regression in the file you just changed. It is not. **Before believing a suite failure that follows a mutation pass, verify the SOURCE is what you wrote** - `git diff` the constant, not the test output. And `pgrep -f _mutate_` before running the suite at all.
- **A test for "this does not park" must run on a THREAD with a join timeout**, or the mutant that proves it does not park will hang instead of failing - which is what causes the kill above. The rule already exists in this file for the ffmpeg watchdog; it applies to EVERY unbounded-wait guard, and a per-mutant subprocess timeout is not a substitute because the damage happens while you wait out the 900s.

## The pre-release audit of the UNTOUCHED corners (2026-08-11)
A pass over the modules no previous audit had reached, chosen by cross-referencing every app module against its test-reference count and its mentions in this file. Three real defects, and the reusable result is again the playbook's thesis: **every one was a class this file already documents, surviving in the module the original fix did not reach.**

### ONE unreadable read at LAUNCH destroyed the whole sync library
The "unreadable is not empty" sweep hardened `core/library.py`, `core/preset_manager.py`, `ui/auth.py`, `core.today_store` and `atomic_update_sync_pairs`. **`core/library_migrate.py` was never swept** - and it is the worst possible member of that family to miss: it sits UPSTREAM of the hardened store, so it destroys the library before `load_library`'s guards can run, and it is the only one that runs on **every launch**.
- **The legacy stores are never deleted** (the migration only copies them to `*.bak`), so a re-run always has something to import - and importing REBUILDS the library from its state at first migration. `needs_migration` answered "yes, migrate" for any library file it could not read, and `_read_json` swallowed `OSError` alongside `JSONDecodeError`. **Reproduced against the real functions**: one transient `OSError` - an antivirus lock, a config dir on an offline share, a permissions blip - and a pair the user had renamed reverted to its original name while a second saved pair **disappeared entirely**. Every saved pair, name, group and daily-sync membership since the first migration, gone at launch, with a debug-level log as the only trace.
- **Three outcomes now, not two**: `None` (absent), `_DAMAGED` (read it, cannot use it), `_READ_FAILED` (could not read it). Transient -> **refuse to migrate, touch nothing** (one launch of Canvas names costs nothing; proceeding is permanent). Damaged -> **quarantine the bytes first, then rebuild** - which is the docstring's original reasoning, and it was only ever wrong for a blip. Same asymmetry, same verdict, as the sqlite corruption whitelist: destroy nothing on the strength of an error you have not identified.
- **A LEGACY file that exists and cannot be read aborts the migration**, writing nothing. Treating it as empty would build a library missing every pair it held, and `needs_migration` then answers False **for ever** - permanent and silent. Aborting costs one launch; the next retries.
- `UnicodeDecodeError` (a SIBLING of `JSONDecodeError`, both `ValueError`) escaped `_read_json` AND `needs_migration`, which `migrate_if_needed` calls **outside its own try** - so its "never raises" docstring was false. `app.py`'s blanket handler saved the launch, which is exactly why nobody noticed.
- Covered by `tests/test_library_migration_hardening.py` (13). **Its `_unreadable` is a context manager, not `monkeypatch` + `undo()`, and that is not style**: `undo()` reverts the fixture's `CANVAS_DL_CONFIG_DIR` too, so assertions after it read **the developer's real library in the repo root**. The tests caught it themselves by failing with an empty pair list; `_assert_isolated` now refuses to assert outside the tmp dir.

### The last gate before a sync could not warn about a FULL disk
`format_available_space` fixed what the Confirm Sync dialog PRINTS. The arithmetic beside it still could not tell three cases apart, and two were wrong.
- The ratio was gated on `avail_bytes > 0`, so a genuinely **full** volume fell to the same 1% floor as an empty one and the ">70% of remaining space" notice could not fire. Measured on the dialog's own expression: **0.4 MB free warned, 0 B free did not.** The one case the warning exists for was the only one it could not reach.
- An **unreadable** volume drew a 1% bar - while the code's own comment claimed the maths "suppresses the bar instead of drawing a false one". It did not: the floor applies whenever `total_bytes > 0`.
- `shared/helpers.disk_fill_percent` has three outcomes: **`None`** (never measured - draw nothing, warn nothing), **`100.0`** (measured, no room), else the linear ratio with the 1% floor. Extracted rather than left inline for the reason `format_available_space`'s own history records: a test that re-implements the dialog's expression tests the copy, and four mutants survived on exactly that.
- `ui/sync_review.py` blocks a full volume before the dialog is reached (it demands 1 GB), so the full-disk half is belt-and-braces; the unmeasured half is not. Verified in the browser in all four states - full 100% + amber, tight 83% + amber, plenty 1%, unknown an empty track reading as "not measured".

### TWO live progress-bar renderers, and only one was hardened
`_pct` exists because the value goes into `width: N%`, where `-3` and `nan` are **invalid CSS**: the browser drops the declaration and a block div falls back to the full track, so "less than nothing happened" renders as "finished". That hardening reached `build_progress_bar_html` and **not `shared/helpers.render_progress_bar`**, the other live renderer - called three times from `sync/execution.py`'s run loop. Measured before the fix: **NaN raised `ValueError`, inf raised `OverflowError`, None raised `TypeError`**, from inside a repaint path whose values come from counters owned by several subsystems. Now routed through the same `_pct`/`_num`: one clamp, imported rather than copied (function-scoped, because `progress_dashboard` imports `shared.theme`).
- The two renderers still have different signatures and different visuals (`engine/progress_dashboard` draws the dashboard bar; `shared/helpers` draws the sync-execution bar with a centred label). That is an observation, not a fixed defect - unifying them is a visual change to the sync run screen, which needs its own before/after pass.

### Sweeps that came back CLEAN - do not repeat them
Each was mechanical and whole-project, so a future hit is genuinely new code:
- **0** text-mode `open()` without an explicit `encoding` (the CP1252 rule is fully honoured).
- **0** JSON reads guarded without `UnicodeDecodeError`/`ValueError` - that sibling class is fully swept.
- Every truncate-in-place write is a log, a temp file or a write-probe; every user store goes through tmp + `os.replace`.
- Every `rmtree` target is an app-owned config path. `model_dir(model_id)` cannot take user input - `MODEL_REGISTRY` is hard-coded in the source.
- Both untimed `subprocess.run` calls are the macOS folder pickers, which must NOT time out (an arbitrarily long human decision); every other external process carries a timeout, and `panopto/hardware.py` probes at 4 s.
- `core/canvas_debug.py` is bounded at 5 MB with tail retention and a truncation marker; `core/cancellation.py` audits clean (events checked before session state, terminal states excluded so the user is never trapped).
- Of **17** function names defined in more than one module, all but `render_progress_bar` are thin aliases over a single shared implementation (`make_long_path`, `_cleanup_sync_state`, `_add_pair_lazy`, and the `panopto.settings`/`shared.legal` config trio, which both delegate to `shared.helpers.read_json_for_update`).
- Every numeric division on a counter is guarded. The one exception was cosmetic and is now closed: `converters/archive.py`'s bomb MESSAGE interpolated `uncompressed / archive_size` unguarded while the condition beside it guarded the same division, and the condition's other clause is true independently of `archive_size` - so the line meant to explain a declined archive could raise `ZeroDivisionError` instead. Unreachable today (a 0-byte file cannot parse as an archive), fixed anyway because the reachability argument depends on a fact two libraries away.

### Known, deliberately NOT changed
- **Deleting a Whisper model is one unconfirmed click.** `ui/panopto_page.py`'s trash icon calls `delete_model` immediately, while the CUDA libraries on the same page use a carefully-built schedule + undo flow with a comment explaining why a same-shaped second button reads as a confirm. The inconsistency is real and the cost is bandwidth and time, not data. It is left for a pass that can verify it properly: a confirm state changes the row's element SHAPE, which is the container-inheritance hazard, and that needs its own before/after browser pass rather than a hurried one.
- **The cancel Events in `core/cancellation.py` are process-global**, so two browser sessions against one server would share them. That is the correct trade, not an oversight: a background thread has no Streamlit session context, which is the whole reason the Events exist.

### Never run the mutation harness on a DIRTY source tree
This file already warns that a concurrent commit can CAPTURE a mutant. The same hazard runs the other way: the harness's `restore()` is a hard `git checkout`, so **any source change not yet committed is discarded silently**, and the results then describe a tree nobody wrote. It ate two finished fixes on 2026-08-11 (`file_in_scope`'s unquote and the duplicate-panel removal); the tests written for them are what noticed, by failing. Commit first, every time - the harness now refuses to start on a dirty tree.

### A dialog's height belongs on its CONTENT region, never on the dialog (2026-08-11)
**`div[role="dialog"] > div:first-child` is NOT the padded body.** Measured in Chrome: the dialog has **three** children - `child[0]` a chrome wrapper (24/12 padding), `child[1]` the content body (12/24), `child[2]` the close button. A `min-height: 300px` on the first-child selector therefore inflated the WRAPPER, pushing the title from `top=62` to `top=290` and leaving a 300px empty band **above** it. The older note in this file about padding living on `> div:first-child` does not license putting a HEIGHT there.
- **The fix is to keep the region that normally holds content.** The Ignored Files dialog already had a sized `st.container(height=filelist_height, key=f"{prefix}_filelist")`; it was simply skipped when the list was empty, which is what let the dialog collapse. It now always renders, with the empty-state notice INSIDE it. Verified: an empty dialog is **777px, identical to a populated one**, content area 480px, notice inside it. The hub does the same via one `HUB_LIST_HEIGHT` constant read by both its populated card list and its empty-state container, so the two cannot drift.
- **The Smart Select collapsed header: the dead band IS the card's own `padding-bottom`, and removing it is the WHOLE fix.** Also pulling the label up by `-card_pad_y` double-counts, and the label keeps its own `padding-bottom` - measured **card 39px against label 49px**, i.e. the hover strip (which is the clickable area) hung 11px BELOW the card containing it. With only `padding-bottom: 0` the card is 51px and the label 49px, the 2px being the card's own borders: flush, no dead band, no overhang.
- **THE PROCESS RULE, from the operator and now non-negotiable: a UI change is not done until it has been looked at in a browser, BEFORE and AFTER.** Both defects above are geometry, invisible in code review and obvious in one screenshot. Two mechanics that make it cheap when the real screen needs a Canvas token: drive the REAL dialog function with a stubbed `sync_manager` (the CSS, keys and markup are the app's - only the data is fake), and remember the harness runs with `--server.fileWatcherType none`, so **restart it after every edit** or you will measure the previous version and conclude your fix did nothing.
- **Confirming a folder picker without navigating must look like a no-op.** `_folder_pick_callback` ran `_auto_detect_course_from_manifest` on every pick, so Edit -> Change Folder -> Choose announced a course auto-detected from a folder the user had not changed. Now gated on `norm_folder_key(new) != norm_folder_key(prev)` - the one folder normaliser, so a trailing separator is not a change; in ADD mode `prev` is empty, so the first pick still auto-detects, which is the case worth having.

### A folder picker must open where you can CHOOSE, not inside what you already have
`choose folder default location <the pair's own folder>` opens the panel INSIDE that folder, so "Change Folder" landed in a directory whose contents are all irrelevant (a course folder's own PDFs) and the user had to navigate **up** before picking anything - and re-pointing a pair at a moved or renamed sibling is the common case. Reported on macOS and Windows. `shared/helpers.picker_start_for_existing()` returns the PARENT, is applied at the four re-choose sites (sync add/edit, hub add/edit-pair, rescue mode), and is written **once** so the two platforms' pickers cannot disagree - macOS's `choose folder` and Windows' IFileOpenDialog both take their directory from it. Destination pickers (download path) are deliberately untouched: opening inside the last-used destination is right there. Non-existent, empty and root paths pass through unchanged so each caller's own fallback chain (session default -> ~/Downloads) still applies.

### A JS-gated button must never render UNGATED - the gate outlives the dialog (2026-08-11)
`shared/components.live_enable_button` greys a genuinely-enabled Save button while its name field is invalid. It does that by injecting CSS into the **PARENT document**, keyed on the button key (`cd-live-css-<key>`) behind `if (!doc.getElementById(STYLE_ID))` - so the style is written **once and never removed for the life of the session** - and its polarity is `button:not([data-cd-valid="1"])`, i.e. a MISSING marker means disabled, with only the bridge ever setting that marker.
- **So any render that shows the button WITHOUT calling the helper inherits a permanently greyed, `pointer-events: none` button.** Reported as *"I wrote the pair name but couldn't save"*, with the disabled cursor on hover. The Save Group and Save Pair dialogs are ONE function sharing ONE button key (`save_group_create`), and the pair path deliberately skips gating when the course supplies a suggested name (its Save must be live from frame 1, because empty means "use the course's own name"). Open Save as Group once - which always gates - and every later Save as Pair was dead. **Deleting the saved group does not help**: the style is already in the document, and nothing removes it.
- **Unique keys per dialog would NOT have been enough.** The same trap exists inside the pair dialog alone: a course whose name yields no suggestion gates and injects the style, and the next course that does supply one then renders ungated into a document that still greys it.
- **The fix is `active=`, and the call must be UNCONDITIONAL.** `live_enable_button(..., active=<condition>)` tears the previous gate down when it does not apply (removes the `<style>`, clears `data-cd-valid` and the reason tooltip) instead of leaving it standing. A conditional CALL is the bug; a conditional VALUE is fine.
- **Do NOT "fix" this by flipping the polarity to `[data-cd-valid="0"]`.** Fail-closed while the bridge is running is correct - an unmarked button that looks clickable lets a click land on an empty name and silently do nothing. A mutation asserting the polarity is caught.
- **The safe pattern already existed one screen over**: the hub's rename row renders the button and calls the gate inside the SAME `if`, so key and gate are always co-present. `tests/test_ui_leak_and_pair_scoping.py` encodes exactly that invariant - a conditional gate is only allowed when the `st.button(key=...)` it names renders inside the same branch - so the next gated button cannot repeat this without failing.

### A per-FOLDER fact keyed on the COURSE, and markup that dedent could not flatten (2026-08-11)
Both found by the operator driving the real app, and both are classes this file already states elsewhere - reached in modules the earlier fixes did not.
- **"Ignored Files (N)" was cached by `course_id` alone.** Ignored files live in ONE folder's `.canvas_sync.db`, so the identity is the LINK `(course_id, folder)`. With the same course synced into two folders - an ordinary thing, e.g. re-downloading somewhere tidier - the build loop OVERWROTE the entry and both cards read the last pair's data. Measured against the real manifests: folder A held **0** ignored rows, folder B **23**, and both cards said 23. **The dangerous half is not the number**: the cached entry carries the `sync_manager`, so opening the dialog from the wrong card handed it the OTHER folder's manifest and a restore there would have written to a folder the user was not looking at. The dialog's widget keys were `cign_{course_id}` too, so two pairs of one course shared every checkbox. Now keyed through **`core.pair_labels.pair_key`**, which already existed as this app's one answer to "which link is this?" - a second local key here is exactly how two consumers of one identity drift apart. The same raw-tuple comparison in `_saved_pair_sigs` was normalised with it (a JSON-roundtripped `"43660"` never matched an int `43660`, so an already-saved pair read as unsaved and could be saved twice).
- **`{pan_note}` alone on a line printed the config viewer's own `<div>` as text.** The blank-line trap this file documents for the hub pair card, in `render_config_summary_badges`. It fires only when the optional part is ABSENT - i.e. when Panopto is switched ON, the normal case.
  - **The reason the identical shape is harmless a dozen other places is `st.markdown`'s own transform**: `streamlit.string_util.clean_text` is `textwrap.dedent(...).strip()`. An f-string whose lines are UNIFORMLY indented is flattened to column 0, so its blank line is followed by an unindented line and nothing happens - that is the completion card. The Panopto case differed in one respect: the assembled grid also contains column-0 lines, so the common prefix is 0, **dedent removes nothing**, and the 4-space line survives as an indented CODE BLOCK.
  - **Fixing the one guilty interpolation is NOT enough, and the attempt proved it.** Rebuilding `pan_html` as a single line MOVED the fault: `grid_container` interpolates it at 4-space indent, so the blank line then preceded a 4-space line for the first time, in BOTH Panopto branches. The function now normalises `\s*\n\s*` to a single space at its one return, which removes the class rather than an instance. A space, not `""` - a newline between tags is already whitespace to the browser, so the rendering is unchanged.
  - **`scripts/verify_architecture.py` Rule 10 gates it** (0 violations): an interpolation alone on a line of element HTML, whose name is provably assignable to `""`, where the f-string also has a column-0 line so dedent is a no-op. All four conditions are load-bearing; without the dedent test it produces two false positives (the completion card and the sync-review header), and **`<style>`/`<script>`/`<pre>` are exempt because they are CommonMark type-1 blocks that end at their closing tag and are NOT terminated by a blank line** - three sites rely on that.
- **Three UI-truth fixes in the same pass.** The Settings FDA card rendered **no button once access was granted**, making the one screen that explains the permission a dead end - it now offers a monochrome "Manage access" in that state, which also makes the keyed container emit the same child count in both branches (it was 2 vs 1, and Streamlit hands a block the children of whatever occupied its index). The sync **analysis** phase was the only phase of its flow with no `step-header` heading while `Syncing...`, `Sync Complete!` and `Panopto Recordings` all have one. And the Ignored Files dialog had no empty states: Smart Select opened onto a bare divider once nothing was left to select, and restoring the last file left the dialog blank because the success notice is **popped as it renders** - so the empty state has to be an `elif` on it, or the next rerun shows nothing.
- Covered by `tests/test_ui_leak_and_pair_scoping.py` (22).

### The Accessibility permission was not EARNED - removed 2026-08-10, do not add it back
The app used to prepend `set visible of (first process whose name is "Microsoft Word") to false` (System Events) to **every** Office conversion, to stop Word's start-screen gallery flashing past. That one line raised **"Canvas Downloader would like to control this computer using accessibility features"** - and it is gone. `engine/applescript_bridge` now runs no AppleScript that touches another process at all.
- **Why it mattered more than a cosmetic tweak**: it is the worst prompt macOS has for a first run. It has **no Allow button** (only *Open System Settings* and a visually primary *Deny*), it cannot be granted from the dialog at all, and it says "control this computer" - on an app that ships **unsigned**, where the user's trust is already thin. Onboarding friction is the thing that kills adoption here, so a permission has to pay for itself.
- **It also hid the USER'S OWN Office session.** Hiding a *process* hides all of its windows, not only ours. Measured: a Word window the user had opened themselves, their own document on screen, went `visible=true -> false` the instant a conversion started. That is a worse defect than the flicker it was suppressing.
- **And it bought NOTHING.** Measured on the real converter, cold Word, two conversions back to back, sampling `visible of process` every 0.25 s - the only sound way to compare, since an in-vitro AppleScript run hits the powerbox trap instead (see below):

  | mechanism | Word visible |
  |---|---|
  | System Events hide (the old code) | 2/11 samples |
  | `open -g -j -a` instead | 1/12 - 2/11 |
  | **neither** | **0/7, repeatable** |

  **Doing nothing is the quietest of the three.** An Apple event to a not-running app (`tell application "Microsoft Word" to open ...`) launches it *without activating it*, so it comes up already hidden - the trace goes straight `absent -> false`. An explicit `open -g -j -a` is what introduces a brief visible blip, during its own launch. Verified identically for **Excel and PowerPoint** (`absent -> false`, never visible, frontmost stayed Finder): all three converters share ONE runner (`run_applescript`), which is why one deletion covered three apps - the same counting rule as the Office delete-gates.
- **`prime_office_automation` still launches with `open -g -j` and that is right**: its job is to batch the one-time Automation prompts up front, so it must launch the apps, and `-j` keeps that launch hidden. Its blip happens once per run, while the user is being shown a permission notice anyway.
- **What is UNAVOIDABLE is the dock ICON** appearing while Office runs - the app genuinely is running. It does not bounce, because nothing activates it.
- **Every prompt the app now raises can be answered in place**, which is what makes `TCC_FIRST_RUN_NOTICE`'s "Click Allow or OK on each" true for the first time: Automation (per Office app + System Events) → Allow; the macOS 15 "access data from other apps" powerbox → OK. That constant lives beside the mechanism precisely so the two cannot drift; a change that reintroduces an Accessibility prompt makes its copy a lie.
- **The prompt was introduced in v2.0.1 and shipped in no audited build** - `v2.0.0`'s bridge contains no `set visible of`, which is exactly why the operator's earlier macOS audits never saw the dialog and remembered conversions as clean. A "we always had this" instinct would have been wrong; check the tag.
- **THE MEASUREMENT TRAP, and it cost a full cycle**: driving the conversion AppleScript **directly** on a path outside the Office container makes macOS demand the per-folder *"Grant File Access"* powerbox prompt, which blocks and returns `AppleEvent timed out (-1712)` with no PDF - and reads exactly like the hide having broken the conversion. This is the same trap the staging note records from the other direction. **Always drive the REAL converter** (`converters.word.WordToPDF().convert`), which stages into the container first. Also: a hand-built minimal `.docx` makes Word raise a repair modal and hang; `textutil -convert doc` produces a genuine legacy `.doc` that Word opens silently.
- Covered by `tests/test_macos_no_accessibility_permission.py`; all 7 mutations of the real code are caught. **Its scanner strips COMMENTS but deliberately keeps STRING LITERALS** - AppleScript reaches osascript as a Python string, so a real regression lives inside a literal, and an earlier version that blanked literals let a re-added System Events hide survive. Synthetic-input words (`keystroke`, `click at`) are only scanned in files containing `osascript`: this app's JavaScript bridges say "one rerun per keystroke" in their comments, which produced four false positives.

### `normcase` was deciding an UNLINK, and it is the identity off Windows (2026-08-10)
The `_path_key` fix earlier the same day taught that `os.path.normcase` does nothing on macOS while the default volume is case-INSENSITIVE. The sweep for that class elsewhere found the same primitive deciding a **deletion**, and this one destroys the user's file:
- **`sync/execution.py`'s superseded-copy guard.** After a clean update of a RENAMED secondary entity, the regenerate writes the canonical name and the old pristine copy is removed - guarded by `normcase(old) != normcase(new)` so it can "never delete the file it just wrote". On macOS a **case-only** Canvas rename (`week 1 assignment` -> `Week 1 Assignment`, an ordinary lecturer edit) makes those two strings differ while naming ONE file. Reproduced: file written, guard says "different", `unlink()` - **the folder is left empty and the manifest row points at nothing.** Now keyed through `_path_key`.
- **`_claim_target`** reserved dispatch paths by `normcase`, so two Canvas files whose sanitized names differ only in case each claimed a "free" path and then wrote over each other.
- **`protect_conversion_target` / `is_conversion_target_protected`** keyed the `_NewVersion` protection set by `normcase(resolve())`. **`Path.resolve()` does NOT canonicalise case on macOS**, so a mark written as `Notes.md` and a lookup for `notes.md` miss - and a missed mark overwrites the student's edited conversion output, which is the single thing that set exists to prevent.
- **`_path_key('')` is `'.'`**, because `normpath('')` is - so an emptiness test must be made on the RAW value. Keying first turned "no recorded path" into a real lookup for the current directory; caught by a mutation, not by reading.

### Building the macOS bundle: two traps
- **`excludes` cannot beat `collect_all`.** Adding a package to `scripts/build_excludes.py` stops it being IMPORTED; `collect_all` also runs `collect_data_files`, which copies the package in as **DATA** regardless. `pync` survived an exclude for exactly that reason and had to be removed from the spec's `collect_all` list *and* its explicit `binaries` entry.
- **`pync` broke the whole signature.** It vendors a nested `terminal-notifier.app`, PyInstaller rewrites `.` to `__dot__` in those directory names, and `codesign --verify --strict` then fails for the ENTIRE app ("the main executable or Info.plist must be a regular file"). Harmless while the app ships ad-hoc/unsigned, so this is a **latent** blocker, not a current one - but notarization rejects it, and `--force --deep` silently produces an unverifiable artifact. Dropped: it is notification fallback #3 of 4, its import is already guarded, and the primary `UNUserNotificationCenter` path is verified working. After the change `--verify --strict` and `--verify --deep --strict` are both rc=0 with the `apple-events` entitlement intact.
- **Verify in the BUNDLE, not just in source - and know which half you verified.** Pointing a browser at the packaged app's Streamlit port exercises the frozen backend (bundled modules, real config dir, real keychain, signed binary) and **not** WKWebView rendering; that needs a screenshot of the app's own window. Both halves were covered separately. The packaged app was proven to: verify strictly, convert Word→PDF (genuine `%PDF`, source deleted only after verification, manifest repointed), honour the short keychain probe, record exactly one clean exit, and render the FDA nudge.
