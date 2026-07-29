# Audit findings register

Cumulative work list produced by the live audit (`/audit-live`, or
`python -m tests.audit`). **This file is meant to be edited by hand.**

Set `**Status**` on any entry to one of `open`, `fixed`, `accepted`,
`wontfix`, `invalid`, and add anything you like under `**Notes**`. The
audit refreshes the facts around your decision on every run and never
overwrites it. Anything you marked `fixed` that appears again is
reported as a **regression** — that is the line worth watching.

Last updated by run `20260728_145153_matrix` on 2026-07-29.

**2 open** · 40 total · 23 fixed · 15 invalid

---

### Canvas Pages ignore the 'isolate secondary content' setting; every other entity type honours it
<!-- fp:7e2221df01e0 -->

**Status**: fixed
**Severity**: medium
**Category**: config
**Oracles**: O2,O3
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 3
**Scenario**: m051_c43660 · 43660

**Detail**:

Both Page call sites pass isolate=False literally, so with isolation ON in flat mode every Page lands at the course root - the one folder the setting exists to keep clean - while assignments, quizzes and discussions from the same run go to their category folders. _ENTITY_ROUTING already defines 'Pages' as the destination, so the routing supports it; only the two call sites never ask for it. Reported, not fixed: lanes were still running.

**Notes**: Fixed 2026-07-29, flat mode only (decided with the user; modules mode deliberately unchanged - a module Page belongs with its module, and that path carries legacy_sync_id back-compat machinery precisely because page keying moved once before). In FLAT mode there is no module folder, so 'module placement' degenerates to the course root and the isolate setting is the only instruction left. TWO halves had to move together: the writer (_download_flat_async -> isolate_pages) and the analyzer's expectation (_get_files_from_modules emits 'Pages/<name>.html', because analyze_course only fills target_paths in modules mode and preferred_disk_name passes a name_locked negative-id name through verbatim). If they disagree nothing crashes - every page just reads as new on every sync for ever. VERIFIED IN THE REAL APP: flat+isolate download of course 43660 -> 28 module scans, 35 pages, all 35 in Pages/, no Processing Error; then TWO sync runs, both 'Sync done - everything up to date, Checked 152 files'. Guarded by tests/test_page_isolation_flat_mode.py.

---

### Canvas Content isolation requested but 35 entity file(s) sit at the folder root
<!-- fp:c52480b4f905 -->

**Status**: fixed
**Severity**: medium
**Category**: placement
**Oracles**: O1,O3
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 3
**Scenario**: m051_c43660 · m051_c43660

**Notes**: Fixed 2026-07-29, flat mode only (decided with the user; modules mode deliberately unchanged - a module Page belongs with its module, and that path carries legacy_sync_id back-compat machinery precisely because page keying moved once before). In FLAT mode there is no module folder, so 'module placement' degenerates to the course root and the isolate setting is the only instruction left. TWO halves had to move together: the writer (_download_flat_async -> isolate_pages) and the analyzer's expectation (_get_files_from_modules emits 'Pages/<name>.html', because analyze_course only fills target_paths in modules mode and preferred_disk_name passes a name_locked negative-id name through verbatim). If they disagree nothing crashes - every page just reads as new on every sync for ever. VERIFIED IN THE REAL APP: flat+isolate download of course 43660 -> 28 module scans, 35 pages, all 35 in Pages/, no Processing Error; then TWO sync runs, both 'Sync done - everything up to date, Checked 152 files'. Guarded by tests/test_page_isolation_flat_mode.py.

---

### ~~'readonly:gk2 vejl_løsn_js.txt' was locally edited but no _NewVersion sibling was created~~~~~~~~~~~~~~~~~~~~
<!-- fp:6a83c06e72be -->

**Status**: invalid
**Severity**: critical
**Category**: delivery
**Oracles**: O5,O3
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 10
**Scenario**: p2nv_pass2 · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

The product's stated contract is that local edits are never overwritten and the new copy lands alongside.

**Notes**: AUDIT FIXTURE DEFECT, fixed. `readonly_target` had chmod'ed a CONVERSION OUTPUT (`x_js.txt`) rather than a download target. The engine writes the Canvas file first (`x.js`, writable) and the converter renames it afterwards, so the write path was never blocked - no PermissionError, no _NewVersion, and the fixture was silently exercising the converter's failure path instead of the locked-target fallback it was written for. The fixture now only picks rows whose local extension matches their Canvas filename. The locked-target fallback itself is verified working elsewhere (run 20260728_010431: two read-only PDFs, both forked correctly).  
> Not observed in the latest run.

---

### ~~Local edits to a CONVERTED file are overwritten - _NewVersion protects the download, but post-processing regenerates the output on top of your work~~~~~~
<!-- fp:bc9703c2e9f2 -->

**Status**: fixed
**Severity**: critical
**Category**: delivery
**Oracles**: O3,O2
**First seen**: 2026-07-28 (20260728_211019_syncmatrix)
**Last seen**: 2026-07-28 (20260728_211019_syncmatrix)
**Occurrences**: 1
**Scenario**: s001 · 45899

**Detail**:

Measured, both bytes and log, on sync row s001.

The user edited two files that are CONVERSION OUTPUTS - hints.md (from hints.html) and Create_ILearn_tables_sql.txt (from Create_ILearn_tables.sql). The row ticked 'updated_modified', so this is the accepted path.

The analysis is right: it maps the source to the converted target, '[UPDATE-EDIT] hints.html -> .../hints.md'. The plan even says '[modified update (_NewVersion)]'.

But the fork is applied to the DOWNLOADED file's name. The fresh hints.html lands at its own plain path - where nothing needs protecting - and post-processing then regenerates hints.md at its canonical name, straight over the file the user edited.

Result: md5 0cf8870d -> 44b3b792 and 1e213dd3 -> d18bff9a, with NO _NewVersion sibling for either. The edits are gone.

This defeats the one guarantee the feature exists to make. The completion screen says 'Saved next to your copy, which was left untouched' - and for a converted file that is not what happened.

SCOPE: any locally-edited conversion output - convert_html (.md), convert_code (.txt), convert_excel (.pdf/_Data.txt), convert_word/pptx (.pdf), convert_video (.mp3). Quick Sync is NOT affected: it declines locally-edited files entirely and says so ('Quick Sync always skips locally-deleted and locally-edited files').

NOT YET FIXED - the fix belongs where the fork name is chosen, which must become the name of the file actually being replaced (the conversion OUTPUT) rather than the downloaded source. That is the same delicate write path as the open duplicate-download finding, and it needs a verifying re-run.

**Notes**: EXACT SITE: `sync/execution.py:1354` - `if is_update_modified and filepath.exists():`. `filepath` is the DOWNLOAD target (the source name), so the test asks whether the SOURCE is on disk, not whether the file the user edited is. Two ways it fails:
  - `convert_html` keeps its source, so `hints.html` exists and gets forked to `hints_NewVersion.html` - protecting a file nobody edited, while post-processing still regenerates `hints.md` over the edit.
  - `convert_code` CONSUMES its source, so `Create_ILearn_tables.sql` does not exist, no fork happens at all, and the fresh source converts straight over `Create_ILearn_tables_sql.txt`.

TWO WAYS TO FIX:
  (a) Keep the promise exactly - the user's file stays at its own name and the NEW copy lands as `<stem>_NewVersion<ext>`. That means the conversion output name has to be diverted, so post-processing needs to be told the canonical name is taken by an edited file.
  (b) Smaller, and it fully prevents the data loss: EXCLUDE the source from this run's conversion set when its output was locally edited. The chokepoint already exists - `sync/execution.py:2045 get_synced_file_paths()` is the one place sync decides what post-processing may touch, and it already carries a comment about a previous bug where a broader scope 'converted-then-DELETED' the user's own files. The user then keeps their edited output AND gets the fresh source beside it; they simply do not get the new content in converted form until they resolve it.

(b) is the one to land first: it is contained, it stops the data loss, and it needs no change to the converters. (a) is the complete answer and can follow. Either needs a verifying re-run - seed `edited_update` on a snapshot with converters (c45899_base), sync with `updated_modified` ticked, and confirm the edited output's md5 is unchanged.

FIXED 2026-07-28 with (a), the complete answer - (b) was skipped because it trades data loss for a silently WRONG folder (the user keeps their edit but never gets the new content in converted form, and nothing says so). The code had already documented the gap in its own words at `sync/execution.py:1305`: *"the ownership-aware converter then overwrites the tracked PDF in place"* - the design deliberately delegates to the converter and never told it the file was edited. Three parts:

1. `core/sync_manager.py:protect_conversion_target(path)` / `is_conversion_target_protected(path)` - an in-memory, per-run set. `sync/execution.py` marks the edited OUTPUT at the point that already knows it is edited (the analyzer's own `is_update_modified` verdict). This is the authoritative signal and the only one that works on folders created before this version.
2. `converters/post_processing.py:_resolve_conversion_target(sm, src, ext, default_name=)` - the single destination resolver every converter already shared - now diverts to `<stem>_NewVersion<ext>` when the target is protected, or (durable backstop) when the recorded product md5 no longer matches what is on disk.
3. `core/sync_manager.py` now records the product's **md5 alongside its path** (`_record_conversion_product`), with `conversion_product()` reading both the new dict form and the legacy bare-string form. The backstop needed this because by the time post-processing runs, the manifest row has been repointed at the freshly downloaded SOURCE and no longer describes the product at all.

A fourth change was required and is the reason the first attempt failed: `convert_code` never went through the shared resolver, computing its own `<stem>_<ext>.txt` destination - which is exactly why `Create_ILearn_tables_sql.txt` got no diversion whatsoever. It now takes a `dst=` override (`converters/code.py`), passed with an explicit `default_name` because its output is a stem rewrite rather than a suffix swap.

Self-correction worth recording: the first version relied on the recorded md5 ALONE. Every unit test passed, but the verification snapshot predates the record - so real users' existing folders would have received no protection at all. The seeded run caught it. That is why the run-scoped mark is primary and the hash is only a backstop.

VERIFIED in the real app - run `20260728_224830_fixverify`, snapshot `c45899_base`, `seed apply --kinds edited_update` (2 files), `flow sync --select updated_modified` -> landed on review, 2 touched, confirm ok:
```
g1 darts vejl_løsn_js.txt    73678d0d -> 73678d0d   PRESERVED   (+ ..._NewVersion.txt, 1280 B)
gk2 vejl_løsn_js.txt         50199ba0 -> 50199ba0   PRESERVED   (+ ..._NewVersion.txt, 1298 B)
```
Both edits byte-identical, fresh content alongside - exactly what the completion screen promises.

THE OTHER DIRECTION, verified separately and at least as important: this resolver runs on EVERY conversion, so a false positive would fork every product on every sync. Run `20260728_234157_cleanconv`, same snapshot, `seed apply --kinds clean_update` on the same two files, synced **twice**:
- pass 1 - log reads `[UPDATE-CLEAN]` -> `[clean update (overwrite)]` -> `Updated manifest entry ... to new file: ..._js.txt` -> `[SYNCED]`. Products overwritten in place. **0 `_NewVersion` files.**
- pass 2, with the product hash record now live for those two files - again in place, **0 `_NewVersion` files**, and every recorded hash still matches its file on disk. (Pass 2 is the one that matters: pass 1 cannot exercise a record it is itself creating.)
- The restored snapshot carries **103 legacy bare-string product records** alongside the 2 new dict-form ones, so the mixed-format read and the "no recorded hash -> previous behaviour" branch were exercised against real data rather than a fixture. No churn on folders converted by an older version.

1216 tests pass; `verify_architecture.py` clean.  
> Not observed in the latest run.

---

### ~~'renamed-ambiguous:zz flertydig 1.pdf' expected as new but no oracle placed it in any category~~~~~~~~~~~~~~~~~~
<!-- fp:2e38f73c0857 -->

**Status**: invalid
**Severity**: high
**Category**: classification
**Oracles**: O5,O2
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 18
**Scenario**: p2r_defaults · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

Renamed, row dropped, and another file shares its size and extension. The uniqueness guard must REFUSE to adopt, so New is correct - binding here would silently mark a missing file present and the user would never get it back.

**Notes**: AUDIT MATCHER DEFECT, fixed. The app placed all 11 New rows correctly; the matcher did not know three of the app's own naming conventions, so it could not find them on the screen. A fixture records the name a file has ON DISK; the review screen shows the name it has ON CANVAS, and between them sit: a converter rename (`x.js` -> `x_js.txt`), a secondary-entity prefix (`Quiz <title>.md` shown as `<title>` + an HTML chip), and an attachment inside an entity (`Assignment <entity> - <file>.pdf` shown as just `<file>`, sometimes with a `-1` dedup suffix). `crosscheck._name_candidates` now derives every legitimate form. Re-checked on the same folder: 6 of these became 0.  
> Not observed in the latest run.

---

### ~~Adoption tier (c) binds a same-size, same-extension file of UNRELATED content~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:1d964fc34314 -->

**Status**: fixed
**Severity**: high
**Category**: classification
**Oracles**: O5,O4
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-28 (20260727_165705_bootstrap)
**Occurrences**: 4
**Scenario**: p2_sync_45899 · Programmering (45899)

**Detail**:

core/sync_manager.analyze_course tier (c) adopts an untracked on-disk file when exactly one orphan shares the Canvas file's size AND extension. It performs no name comparison and no content comparison.

Proven live: a file of identical byte-length but entirely different content ('decoy N unrelated.pdf', all zero bytes) was silently bound to a deleted Canvas file. The real file was never offered as New and will never be re-downloaded; the user keeps junk under the manifest row of the file they lost. Both decoy fixtures were adopted; both renamed_ambiguous fixtures were correctly REFUSED, so the uniqueness guard itself works.

Why it matters more than the code comment assumes: tier (c) is documented as the fallback for when tier (b) - the md5 content match - is unavailable. Measured on course 43660, Canvas exposes md5 for 0 of 140 files, so tier (b) NEVER fires against this instance and tier (c) is doing all the work, content-blind, on every rename. The safety net the design assumed is not there.

Note heal_manifest is unaffected: its Tier 2 compares original_md5 local-to-local and is exact. This only concerns files whose manifest ROW is gone.

Options: require a name-similarity floor for tier (c) as heal Tier 3 already does (>=0.90 stem containment, ambiguity reject); or mark such adoptions low-confidence and re-verify on next sync; or accept it and document that a size collision can shadow a file.

**Notes**: Fixed 2026-07-27 (option 1: name-similarity floor). core/sync_manager._name_floor_reject now requires stem CONTAINMENT before tier (c) may bind, and every adoption and refusal is logged. Containment was chosen over a similarity ratio by measurement: heal Tier 3's 0.90 ratio rejects genuine renames (Intro->Intro_v2 = 0.857, Lecture 1->Lecture 1 (annotated) = 0.684) while PASSING the substitutions it is meant to stop (Lecture1->Lecture2 = 0.917). Verified live on course 45899: both planted decoys refused, both real files recovered (New went 7 -> 11), and every row-intact rename still adopted via heal Tier 2. Guarded by tests/test_tier_c_name_floor.py (23 tests, incl. the calibration itself) + test_engine_fixes.py.  
> Not observed in the latest run.

---

### ~~Every Panopto shortcut is offered as a 'clean update' on every analysis, for ever~~~~~~~~~~~~
<!-- fp:6fe18c5a9b2f -->

**Status**: fixed
**Severity**: high
**Category**: classification
**Oracles**: O1,O2,O4
**First seen**: 2026-07-28 (20260728_130002_phase4_panopto_full)
**Last seen**: 2026-07-28 (20260728_130002_phase4_panopto_full)
**Occurrences**: 2
**Scenario**: p4_panopto_sig · 43660

**Detail**:

A module ExternalTool item is written to disk as a .url shortcut, and its content_sig is what a later analysis compares to decide changed-or-not. The signature was computed from a DIFFERENT url than the one the file received:

  file contents : html_url        (https://<canvas>/courses/43660/modules/items/1128498 - unique per recording)
  signature     : external_url    (https://cbs.cloud.panopto.eu/Panopto/LTI/LTI.aspx - the LTI launch endpoint)

That endpoint is the SAME string for all 36 recordings in the course, so it cannot identify one, and the signature could never match the one recorded at download time.

Measured on a folder downloaded minutes earlier: 36 rows in 'Updates Available', 0 md5 mismatches, every one a .url shortcut. Verified by recomputing both candidate signatures against the stored value - sig(url-in-file) matched, sig(external_url) did not, for all 36.

Consequences, all permanent:
  - the course can never reach 'all up to date'
  - every sync rewrites 36 shortcut files
  - Quick Sync and the daily auto-sync do it every day
  - the Today page counts them as 'updated' arrivals daily, so a user on Today mode sees 36 files land every morning that did not change

Same family as the Pages identity bug documented immediately below it in the source ('35 new files on a fresh download', 2026-07-09): the download path and the scan path must agree on what identifies an entity.

FIXED: the signature is now computed from the url the file actually receives, special-cased by type. ExternalUrl keeps its original ordering (external_url first) - a first attempt used one ordering for every type and turned the 5 correct ExternalUrl rows into phantoms instead, the same bug moved. Verified in the running app across three analyses of the same folder: 36 -> 5 -> 0 updates, with the 3 genuine transcript jobs and 33 ignored recordings unaffected throughout.

Guarded by tests/test_link_content_sig_parity.py, which runs BOTH directions and asserts two recordings in one course get different signatures.

**Notes**: Fixed and verified end to end in the running app (36 -> 5 -> 0 across three analyses of the same folder). The intermediate 5 was a wrong first fix that moved the bug to ExternalUrl; both directions are now covered by tests.  
> Not observed in the latest run.

---

### ~~'deleted-locally:Debug - grades - 1.txt' should have been left alone but was written to Uge 48 Forelæsning 12. Node.js og debugger samt eksamensforberedelse/Debug - grades - 1.txt~~~~~~~~~~~~~~~~~~~~
<!-- fp:91d640ef7d5a -->

**Status**: invalid
**Severity**: high
**Category**: delivery
**Oracles**: O5,O3
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 2
**Scenario**: p2nv_selected · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

File removed but its manifest row kept, which is what a real user deletion looks like. The deletion must be respected: unchecked by default, and always skipped by Quick Sync.

**Notes**: AUDIT DEFECT, fixed. The fixture predicts 'absent' because a deleted-locally row is UNCHECKED by default. This run ticked it on purpose (`--select deleted_locally`, the second Phase 2 scenario), so restoring the file is exactly what the user asked for. `_sync_outcome` is now selection-aware in BOTH directions: an unticked restore/new_version becomes 'unchanged', and a ticked 'absent' becomes 'restored'. Re-checked: 2 of these became 0.  
> Not observed in the latest run.

---

### ~~'deleted-locally:minefeltVEJL_js.txt' should have been left alone but was written to Uge 44 Forelæsning 8. JavaScript og Browseren, HTML 1/minefeltVEJL_js.txt~~~~~~~~~~~~~~~~~~~~
<!-- fp:78c7871b2180 -->

**Status**: invalid
**Severity**: high
**Category**: delivery
**Oracles**: O5,O3
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 2
**Scenario**: p2nv_selected · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

File removed but its manifest row kept, which is what a real user deletion looks like. The deletion must be respected: unchecked by default, and always skipped by Quick Sync.

**Notes**: AUDIT DEFECT, fixed. The fixture predicts 'absent' because a deleted-locally row is UNCHECKED by default. This run ticked it on purpose (`--select deleted_locally`, the second Phase 2 scenario), so restoring the file is exactly what the user asked for. `_sync_outcome` is now selection-aware in BOTH directions: an unticked restore/new_version becomes 'unchanged', and a ticked 'absent' becomes 'restored'. Re-checked: 2 of these became 0.  
> Not observed in the latest run.

---

### ~~Download finished with 1 unexplained error(s)~~
<!-- fp:fa2cae30e286 -->

**Status**: fixed
**Severity**: high
**Category**: delivery
**Oracles**: O2,O3
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 15
**Scenario**: m036 · m036

**Detail**:

Errors this course logged that are not teacher-locked files. Each names the item the engine could not deliver.

**Notes**: The undeliverable discussion on course 43660, fixed 2026-07-28 by resolve_discussion_topic() (defined core/canvas_logic.py:290, called at 3 sites). Registered separately as "A discussion Canvas lists but will not serve individually is never downloaded". This title is the reworded check from checker defect 24, which now NAMES the failing item instead of printing a bare count. product-stale evidence from a pre-fix run.

---

### ~~A discussion Canvas lists but will not serve individually is never downloaded, and is reported as an error~~
<!-- fp:fa247ec01d02 -->

**Status**: fixed
**Severity**: high
**Category**: discovery
**Oracles**: O5,O2,O3
**First seen**: 2026-07-28 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 4
**Scenario**: m025 · 43660

**Detail**:

Canvas returns discussion topic 166950 in get_discussion_topics() COMPLETE WITH ITS MESSAGE BODY, and raises ResourceDoesNotExist for get_discussion_topic(166950). It is not a group discussion, it is not locked, and it opens normally in a browser.

The module-item path only ever tried the individual GET. So the item failed outright: no file for a discussion the user can plainly read, an 'ERROR [Discussion Dispatch Error]' entry naming something they cannot act on, and an inflated error count - this is what pushed three otherwise-clean matrix rows to 'Download finished with N errors'.

The data was already in hand on the path the app takes anyway.

FIXED: resolve_discussion_topic() tries the individual endpoint first and falls back to the collection, which is the same 'prefer the richer object, keep the other as fallback' shape the assignment path already uses. A genuinely absent topic still raises, and the individual endpoint's error is the one that propagates. All three call sites route through it; a test fails if a fourth calls the endpoint directly.

**Notes**: Fixed 2026-07-28 and verified against the live API. `resolve_discussion_topic()` tries the individual endpoint first and falls back to the collection - the same 'prefer the richer object, keep the other as fallback' shape the assignment path already uses, in the other direction. A genuinely absent topic still raises, and the individual endpoint's error is the one that propagates. All three call sites route through it; tests/test_discussion_resolve.py fails if a fourth calls the endpoint directly.

---

### ~~2 Canvas file(s) were downloaded more than once in one run~~
<!-- fp:d05cc83d973a -->

**Status**: fixed
**Severity**: high
**Category**: persistence
**Oracles**: O2,O4
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 6
**Scenario**: m001_c46396 · m001_c46396

**Detail**:

Each of these ids went to the network twice. Two phases both claimed the file, so two copies are on disk and only one can hold the manifest row - the other is an untracked orphan. Canvas Content must run before every Files-tab sweep; see _defer_to_canvas_content.

**Notes**: DUPLICATE of "A file that is both a Files-tab file and a Canvas Content attachment is downloaded twice", fixed 2026-07-28 by running Canvas Content before all THREE Files-tab sweeps. This is the mechanical check added the same day, so it fires on pre-fix rows by construction. Verified fixed on 5 targeted post-fix runs (modules+inline, modules+isolate, flat+inline, each twice; a repeat run made ZERO HTTP requests). product-stale evidence from a pre-fix run.

---

### ~~2 content file(s) on disk with no manifest row~~
<!-- fp:371b678dbdf1 -->

**Status**: invalid
**Severity**: high
**Category**: persistence
**Oracles**: O3,O4
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 16
**Scenario**: m025_c46396 · m025_c46396

**Detail**:

Each of these will be offered as a NEW file on every future sync unless the analyzer's adoption tiers reclaim it. This is the 'wrongfully shows up as new' failure.

**Notes**: The file was `Compiled_External_Links.txt` — the single aggregate output `convert_urls` writes for the whole course after consuming every `.url`. It is a conversion product, so it has no manifest row BY DESIGN, exactly like the 21,630 archive-extracted files beside it. || SECOND CAUSE, 2026-07-29 - this entry now covers TWO different defects and the `invalid` above applies only to the first. On m025_c46396 the two files were 'Grupper til Klyngevejledning 1-1.pdf' and 'Grupper til Klyngevejledning 2.pdf': the orphaned second copies of the duplicate-download bug (fetch counts name file ids 1784620/1807289, the exact pair CLAUDE.md records for it), not a conversion product. That cause is FIXED - see the duplicate-download entry - and the evidence here is product-stale from a pre-fix run. HAZARD worth remembering: the register fingerprint is (category + digit-normalised title), so 'N content files on disk with no manifest row' is ONE entry no matter which files or which cause. A status set for one cause silences the other. Before trusting an `invalid`, check that the CURRENT evidence matches the cause the note describes.

The audit's own exemption for this existed and never fired: it read `expect["converters"]` while `check download` is handed a FLAT config. The same shape mismatch was also reporting the 25 consumed `.url` rows as a broken manifest. Both now read the `sync_contract` the app stored in the folder, which is what the engine itself obeys.

Verified on a fresh, never-seeded download of 45899 with every converter on: 0 defects. Guarded by tests/test_audit_converter_evidence.py, including a control proving the exemption still reports a genuinely missing .pdf.

---

### ~~4 manifest row(s) point at files that do not exist~~~~~~~~~~~~~~~~~~
<!-- fp:09c8ffb50041 -->

**Status**: invalid
**Severity**: high
**Category**: persistence
**Oracles**: O4,O3
**First seen**: 2026-07-28 (20260728_005027_baseline_45899_pristine)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 4
**Scenario**: p2r_defaults · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

The app believes these files are present. On the next sync each reads as 'deleted locally', which is unchecked by default and always skipped by Quick Sync - so they are never re-downloaded and never mentioned again.

**Notes**: Same root cause as the `Compiled_External_Links.txt` entry above, and fixed by the same change. These 25 rows are the `.url` files `convert_urls` consumed; the engine documents a bypass that treats a missing source of a source-consuming converter as 'converted away'. The audit's exemption for exactly this existed but read `expect["converters"]` while `check download` passes a flat config, so it never fired — the comment beside it even predicts 25 rows.

Now derived from the folder's stored `sync_contract`. Re-checked on the same pristine folder: reported as an observation, 0 defects. The exemption is per-extension, so a genuinely missing .pdf alongside consumed .url rows is still reported (guarded).  
> Not observed in the latest run.

---

### ~~A file that is both a Files-tab file and a Canvas Content attachment is downloaded twice, and the first copy is orphaned~~
<!-- fp:f5c9f9d3c10f -->

**Status**: fixed
**Severity**: high
**Category**: persistence
**Oracles**: O2,O3,O4
**First seen**: 2026-07-28 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 4
**Scenario**: m025 · 46396

**Detail**:

Two HTTP fetches of the same Canvas file id, 21 seconds apart, in one run.

The Catch-All phase downloads every Files-tab file whose id is not already in _downloaded_ids | _module_ids. That set is computed when the Catch-All runs - and the Canvas Content phase runs AFTER it, so a file that phase is about to fetch as an announcement or assignment attachment cannot possibly be in the set yet.

Three consequences, in ascending order of harm:

1. The file is downloaded TWICE. Wasted bandwidth on every run.
2. TWO copies land on disk under different names - the Catch-All writes to the course root under Canvas display_name, the attachment writes under an entity-prefixed name.
3. The manifest ends up holding only the attachment path, so the root copy has NO manifest row. That is the wrongfully-shows-up-as-new failure: every future sync offers it again, for ever.

Measured on course 46396, ids 1784620 and 1807289.

NOT the app own conflict resolution: the 1-1 suffix is Canvas duplicate-upload naming; _handle_conflict appends ' (N)'.

FIX NOT YET APPLIED, deliberately. The candidates all touch download phase ordering or the dedupe contract: pre-compute the secondary attachment ids before the Catch-All, or run Canvas Content first, or dedupe by canvas_file_id at write time. This project already carries one duplicate-files fix in this area, so the change needs the full matrix result and a verifying re-run rather than a same-hour patch.

**Notes**: ROOT CAUSE CONFIRMED, and the design question is settled by the app's own precedent. `sync_manifest.canvas_file_id` is the PRIMARY KEY, so the model is one Canvas file -> one local file; two copies cannot both be tracked, which is why the second write left the first orphaned rather than adding a row. The app already resolves the identical situation for MODULE files: when a file is reachable both through a module and through the Files tab it keeps the content-context copy and logs 'Catch-All skipping module file: X (ID: n)'. By exact analogy the announcement/assignment attachment copy should win and the Catch-All should skip it - which is also the placement a user wants, the file sitting beside the announcement that refers to it.

So the fix is: give the Catch-All the ids the Canvas Content phase is about to claim, the same way it is already given `module_file_ids`. Rejected alternatives: reordering the phases (moves the 'Canvas Content Phase' log marker and the progress UI's phase sequence, for no extra correctness), and deduping at write time by canvas_file_id (same outcome, but it decides the winner by arrival order rather than by which placement is right).

NOT YET IMPLEMENTED: it needs a verifying re-run of an affected configuration (course 46396, dl_announcements on), and the matrix currently owns the machine. The evidence is preserved under _audit_runs/20260728_145153_matrix/evidence/.

WHICH COPY WINS - settled by the app's own placement logic, not by preference. `_resolve_secondary_path` creates an entity's own folder (`Announcements/<Entity Name>/`) ONLY when `has_attachments` is true, so in the default isolate mode the attachment copy is structurally load-bearing: drop it and you get a folder shaped like an entity that has no attachments. The attachment copy must therefore win and the Catch-All must yield.

(The module precedent cited above is weaker than it first looks - `module_file_ids` wins because modules are processed FIRST, not because anything prefers them. The placement logic is the real argument.)

TWO WAYS TO IMPLEMENT, both needing a verifying run:
  (a) give the Catch-All the ids the Canvas Content phase will claim. Complete, but the API-attachment half of that set needs a per-assignment refetch that the secondary phase already performs - so it either costs the calls twice or needs the secondary enumeration split into plan-then-execute.
  (b) let the secondary phase MOVE an already-downloaded copy into the entity folder instead of re-fetching it. One download, correct placement, one manifest row, no pre-pass - but it changes the engine's write path.
(b) is the smaller change and fixes all three symptoms; (a) is the more conservative one. Deferred rather than guessed at: this area already carries one duplicate-files fix, and the matrix owns the machine until the GPU lane finishes.

---

### ~~2 partial-write artifact(s) left on disk~~~~~~~~~~~~~~~~~~
<!-- fp:62da7c0a9988 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O3
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 3
**Scenario**: p2r_defaults · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

A `.part` file after the run means an atomic write was abandoned without cleanup. The next analysis must ignore it, and the user sees a junk file in their course folder.

**Notes**: AUDIT DEFECT, fixed. These are the seeder's own `partial_artifact` fixtures (`interrupted download.pdf.part`, `recording.part.mp4`) - created on purpose to prove the app ignores partials. Counting the fixture that proves correct behaviour as evidence of incorrect behaviour is exactly backwards. The seed plan now DECLARES what it deliberately broke (`seed.declarations`) and the invariants honour it.  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: Failed to convert code file g1 darts vejl_løsn.js: [Errno 13] Permission denied: 'G:\\18 A~~~~~~~~~~~~~~~~~~~~
<!-- fp:18cc3b9d802a -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 5
**Scenario**: p2nv_pass2 · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

Failed to convert code file g1 darts vejl_løsn.js: [Errno 13] Permission denied: 'G:\\18 AI\\ANTIGRAVITY WORKSPACES\\Canvas Downloader\\_audit_runs\\20260728_013336_phase2_newversion\\downloads\\Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)\\Obligatoriske afleveringer

**Notes**: NOT A PRODUCT DEFECT - the app correctly reporting a failure the audit caused. The `readonly_target` fixture had made a conversion OUTPUT read-only, so the converter genuinely could not write it and said so, in download_errors.txt and in the completion screen's post-processing warning. The fixture is fixed (see the _NewVersion entry). The underlying asymmetry it exposed - graceful fallback on a locked download target, hard failure on a locked conversion target - is recorded separately as its own low finding.  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: Failed to convert code file gk2 vejl_løsn.js: [Errno 13] Permission denied: 'G:\\18 AI\\AN~~~~~~~~~~~~~~~~~~~~
<!-- fp:8224b9e3a4a1 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 5
**Scenario**: p2nv_pass2 · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

Failed to convert code file gk2 vejl_løsn.js: [Errno 13] Permission denied: 'G:\\18 AI\\ANTIGRAVITY WORKSPACES\\Canvas Downloader\\_audit_runs\\20260728_013336_phase2_newversion\\downloads\\Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)\\Obligatoriske afleveringer efte

**Notes**: NOT A PRODUCT DEFECT - the app correctly reporting a failure the audit caused. The `readonly_target` fixture had made a conversion OUTPUT read-only, so the converter genuinely could not write it and said so, in download_errors.txt and in the completion screen's post-processing warning. The fixture is fixed (see the _NewVersion entry). The underlying asymmetry it exposed - graceful fallback on a locked download target, hard failure on a locked conversion target - is recorded separately as its own low finding.  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: g1 darts vejl_løsn.js  Conversion failed~~~~~~~~~~~~~~~~~~~~
<!-- fp:0995f8315ce5 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 5
**Scenario**: p2nv_pass2 · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

g1 darts vejl_løsn.js  Conversion failed

**Notes**: NOT A PRODUCT DEFECT - the app correctly reporting a failure the audit caused. The `readonly_target` fixture had made a conversion OUTPUT read-only, so the converter genuinely could not write it and said so, in download_errors.txt and in the completion screen's post-processing warning. The fixture is fixed (see the _NewVersion entry). The underlying asymmetry it exposed - graceful fallback on a locked download target, hard failure on a locked conversion target - is recorded separately as its own low finding.  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: gk2 vejl_løsn.js  Conversion failed~~~~~~~~~~~~~~~~~~~~
<!-- fp:ac0b7c1a10e5 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 5
**Scenario**: p2nv_pass2 · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

gk2 vejl_løsn.js  Conversion failed

**Notes**: NOT A PRODUCT DEFECT - the app correctly reporting a failure the audit caused. The `readonly_target` fixture had made a conversion OUTPUT read-only, so the converter genuinely could not write it and said so, in download_errors.txt and in the completion screen's post-processing warning. The fixture is fixed (see the _NewVersion entry). The underlying asymmetry it exposed - graceful fallback on a locked download target, hard failure on a locked conversion target - is recorded separately as its own low finding.  
> Not observed in the latest run.

---

### ~~'Quick Sync now' was physically unclickable whenever auto-sync was OFF - the default state~~~~~~~~~~~~~~~~
<!-- fp:8badba1fc12c -->

**Status**: invalid
**Severity**: high
**Category**: ui-truth
**Oracles**: O1
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 1
**Scenario**: t3_quick_sync · Today page

**Detail**:

The Today page dims its sections when auto-sync is off, and the dimming carried pointer-events: none. That property is INHERITED, so it reached the button inside the 'Sync on demand' card.

Measured in the running app, both states, same session:

  auto-sync OFF   button in viewport, disabled=false, computed pointer-events 'none',
                  elementFromPoint at the button's centre returned the WRAPPER div,
                  and a real click TIMED OUT ('element does not receive pointer events')
  auto-sync ON    button in viewport, disabled=false, computed pointer-events 'auto'

Flipping the toggle alone moved it, which is what establishes the cause.

Why it matters: auto-sync off is the DEFAULT, the button is a primary action painted with its full brand gradient, and the card it sits in says 'trigger a manual Quick Sync any time to bring these courses up to date right now'. The button was enabled server-side (disabled=not runnable or sync_running - auto_sync_enabled is deliberately not part of that), so the app believed it was offering the action. Nothing about this is visible in a screenshot and nothing logs it; only a hit test or a real click finds it.

FIXED: the two reasons for dimming are now separate. Auto-sync off dims the daily-sync sections only (today_courses_card, today_files_hero) - the manual action is the one thing that must still work in that state. A running sync dims the Quick Sync card too, which is honest because the button is disabled server-side then anyway.

Verified after the fix + app restart, auto-sync still off: pointer-events 'auto', section opacity 1 (was 0.45), hit test reaches the button, and a real Playwright click succeeds. The other two sections still dim at 0.45, so the intended visual signal is intact.

Guarded by tests/test_today_quick_sync_clickable.py, including a general check that no future section may be added to the dimming rules without confirming it holds no enabled control.

**Notes**: INVALID - the behaviour is intentional, and the change has been REVERTED.

Quick Sync's real home is the Sync page. What sits on the Today page is a SHORTCUT, for someone who has turned Today mode on and lives on that page day to day, so they can pull the newest files without switching pages. With Today mode off - the default - the page reads "NOT ACTIVATED", every section is dimmed, and the shortcut is inert along with them. The action is still one click away where it actually lives.

The measurements in the Detail above are all correct; the CONCLUSION drawn from them was not. What the dimming expresses is the state of the PAGE, not the state of that one button, and a shortcut into a mode you have not activated is correctly unavailable. "Enabled server-side but inert in CSS" is the normal shape of that, not evidence of a defect.

Reverted to the original single dimming rule and verified in the running app: pointer-events none, section opacity 0.45, identical to the two sections beside it. tests/test_today_quick_sync_clickable.py now guards the INTENDED behaviour - it fails if the Quick Sync section is ever removed from the dimming list again - and carries the reasoning so the next reader does not have to rediscover it.  
> Not observed in the latest run.

---

### ~~Files extracted from archives are never converted (root cause: explicit_files excludes extraction output)~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:815c4edf0cb8 -->

**Status**: fixed
**Severity**: medium
**Category**: conversion
**Oracles**: —
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-27 (20260727_165705_bootstrap)
**Occurrences**: 1

**Detail**:

app.py:1778 passes explicit_files=success_paths - only paths the DOWNLOADER wrote - into invoke_post_processing, and converters/post_processing._glob_files filters every converter with 'f.resolve() in explicit_set'. run_archive_extraction runs FIRST (post_processing.py:820) and creates new files on disk, but those paths are never added to the explicit set, so every converter after it skips them.

Measured with all 8 converters on: 7 .pptx and 11,872 code/data files inside extracted archives were left unconverted, while the same types at module level converted normally (97 PDFs produced). The user enabled both 'Unpack Archives' and 'Code & Data -> .txt'; only the first reached that content.

Not data loss - files are present and usable - but it defeats the AI-optimisation feature for any course shipping material in a zip, which is common for code-heavy courses. Fix: append run_archive_extraction's output paths to the explicit set (or drop the explicit filter for converters that run after extraction).

**Notes**: Fixed 2026-07-27: `run_archive_extraction` now returns its extraction roots and `_glob_files` accepts anything under them, so unpacked files get the same treatment as any other teacher-uploaded file. Guarded by `tests/test_archive_conversion_scope.py`.  
> Not observed in the latest run.

---

### ~~Sync mode had the same archive-conversion gap as download, via a different mechanism~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:689a00875c36 -->

**Status**: fixed
**Severity**: medium
**Category**: conversion
**Oracles**: O1,O3
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-28 (20260727_165705_bootstrap)
**Occurrences**: 4
**Scenario**: parity_audit

**Detail**:

The download fix alone was not enough. sync/execution.py does NOT call run_all_conversions - it drives each converter itself and scopes them with get_synced_file_paths(), which returns only the exact relative paths THIS run downloaded (_synced_actual_rels). Files unpacked from an archive were never downloaded, so they were invisible to every sync converter too.

Fixed by routing both flows through one shared helper (converters.post_processing.iter_extracted_files) and having run_archive_extraction return its extraction roots to both callers. Guarded by tests/test_archive_conversion_scope.py, which now also asserts the two flows keep the SAME converter ordering and that neither reverts to a downloaded-files-only scope.

**Notes**:   
> Not observed in the latest run.

---

### ~~convert_code did not reach 11872 file(s) unpacked from archives~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:5a22b016415d -->

**Status**: fixed
**Severity**: medium
**Category**: conversion
**Oracles**: —
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-27 (20260727_165705_bootstrap)
**Occurrences**: 1

**Detail**:

convert_zip extracted these, but post-processing filters every converter through explicit_files - the list of paths the DOWNLOADER wrote - and extraction output is never added to it. So enabling both toggles applies only the first to archive contents.

**Notes**: Fixed 2026-07-27: `run_archive_extraction` now returns its extraction roots and `_glob_files` accepts anything under them, so unpacked files get the same treatment as any other teacher-uploaded file. Guarded by `tests/test_archive_conversion_scope.py`.  
> Not observed in the latest run.

---

### ~~convert_pptx did not reach 7 file(s) unpacked from archives~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:24e9563de29e -->

**Status**: fixed
**Severity**: medium
**Category**: conversion
**Oracles**: —
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-27 (20260727_165705_bootstrap)
**Occurrences**: 1

**Detail**:

convert_zip extracted these, but post-processing filters every converter through explicit_files - the list of paths the DOWNLOADER wrote - and extraction output is never added to it. So enabling both toggles applies only the first to archive contents.

**Notes**: Fixed 2026-07-27: `run_archive_extraction` now returns its extraction roots and `_glob_files` accepts anything under them, so unpacked files get the same treatment as any other teacher-uploaded file. Guarded by `tests/test_archive_conversion_scope.py`.  
> Not observed in the latest run.

---

### ~~2 file(s) differ from their recorded md5~~~~~~~~~~~~~~~~~~
<!-- fp:8a7f0ead05f4 -->

**Status**: invalid
**Severity**: medium
**Category**: persistence
**Oracles**: O4,O3
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 3
**Scenario**: p2r_defaults · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

original_md5 is what classifies the next update as clean (overwrite) or modified (_NewVersion). A wrong baseline silently decides whether the user's edits survive.

**Notes**: AUDIT DEFECT, fixed. These are the `edited_update` fixtures: bytes appended so the file no longer matches its recorded baseline, then left UNCHECKED on the review screen by design. The file therefore MUST still differ - that divergence is the user's edit, and preserving it is the product's data-safety guarantee. The audit was reporting that guarantee working as a persistence defect. Covered by the same `expected_md5_drift` declaration.  
> Not observed in the latest run.

---

### ~~2 manifest row(s) record the wrong size~~~~~~~~~~~~~~~~~~
<!-- fp:72054c302758 -->

**Status**: invalid
**Severity**: medium
**Category**: persistence
**Oracles**: O4,O3
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 3
**Scenario**: p2r_defaults · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

original_size decides whether the next Canvas change is treated as a real update or vetoed as a metadata touch.

**Notes**: AUDIT DEFECT, fixed. Same cause as the md5 entry above and fixed by the same declaration - an edited-locally file left unchecked legitimately differs from its recorded size.  
> Not observed in the latest run.

---

### ~~Analysis log omitted the Ignored category and printed URL-encoded filenames~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:4b3b4fd09677 -->

**Status**: fixed
**Severity**: medium
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-28 (20260727_165705_bootstrap)
**Occurrences**: 4
**Scenario**: p2_sync_45899

**Detail**:

CORRECTION of an earlier finding in this register that claimed only 2 of 7 categories were logged - that was an audit error (the grep used tag names UPDATE-MODIFIED/DELETED-CANVAS/DELETED-LOCAL; the real tags are UPDATE-EDIT/CANVAS-DEL/LOCAL-DEL). Five categories were already logged per file.

Two genuine defects remained:
1. CANVAS-DEL and LOCAL-DEL printed sync_info.canvas_filename raw, which is URL-encoded as it comes off the Canvas API. A Danish filename logged as 'Eksamen+2023E+Ordin%C3%A6r+Klasse+opgave.pdf' cannot be matched by eye against the 'Eksamen 2023E Ordinaer Klasse opgave.pdf' the review screen shows.
2. Ignored files were listed nowhere - the one category where 'missing on purpose' is the answer, and the log could not give it.

Fixed in sync/analysis.py: every category now writes one line per file through a shared _row() helper that decodes with unquote_plus and appends the local path wherever post-processing renamed the file (x.sql -> x_sql.txt). Up-to-date files are summarised as a count rather than listed, because on a healthy folder they are every file in the course.

**Notes**:   
> Not observed in the latest run.

---

### ~~Cancelling a transcription leaves .part sidecars in the course folder, invisibly and for ever~~~~~~~~~~
<!-- fp:d433d4f13087 -->

**Status**: fixed
**Severity**: medium
**Category**: robustness
**Oracles**: O3,O2
**First seen**: 2026-07-28 (20260728_130002_phase4_panopto_full)
**Last seen**: 2026-07-28 (20260728_130002_phase4_panopto_full)
**Occurrences**: 1
**Scenario**: p4_cancel · 43660

**Detail**:

The write path is correctly atomic: the worker streams into <name>.txt.part / <name>.srt.part and only os.replace()s them onto the final names when a recording completes. The CLEANUP was broken in two independent ways, both found by cancelling a real run.

1. THE KILL IS ASYNCHRONOUS. transcribe_in_subprocess called proc.kill() and cleaned up immediately. On Windows the dying worker still holds its output handles, so os.remove raised PermissionError - an OSError, swallowed by a bare except. Every cancel left both files.

2. ONLY ONE EXIT FROM THE PHASE CLEANED UP AT ALL. The transcription loop leaves through 'except PanoptoCancelled' (which cleans, via the call above), through 'if is_cancelled() or engine_failed: break' at the loop head (which does not), and through an engine failure (which does not). The two cancel routes are distinguishable in the log - one writes 'Transcription cancelled by user', the other writes nothing - and only the logged one ever cleaned. Both routes were observed: two cancels of the same folder produced different logs and identical leftovers.

Why it is worse than two stray files: the engine deliberately IGNORES .part artifacts everywhere else - never healed onto a manifest row, never auto-discovered, never counted as study material, never post-processed. So a leftover is invisible to the app from then on, and nothing would ever remove or even mention it again.

FIXED, both halves:
  - the cancel path now waits for the worker to actually die before cleaning, and the remove retries briefly and LOGS a persistent failure instead of swallowing it;
  - the phase sweeps every target's sidecars on the way out, whatever ended it - which covers exit routes added later, the thing that went wrong here.

Verified by cancelling three real runs: before, both .part files remained; after, none, with the worker process reaped and the app on a clean 'Sync Cancelled' screen. The no-orphaned-worker half of the runbook check passed throughout.

**Notes**: Fixed and verified by cancelling three real runs. Both halves were needed - the first fix (waiting for the kill) addressed only the route that logs, and a second cancel proved a silent route existed that never called the cleanup at all.  
> Not observed in the latest run.

---

### ~~Unexpected bridged_warning in debug log: Discussion dispatch failed for 'Spørgsmål til pensum i organisationskultur': Not Found~~
<!-- fp:98608167bec2 -->

**Status**: fixed
**Severity**: medium
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 15
**Scenario**: m036 · m036

**Detail**:

Discussion dispatch failed for 'Spørgsmål til pensum i organisationskultur': Not Found

**Notes**: Same cause as the undeliverable-discussion entry, fixed 2026-07-28 by resolve_discussion_topic(). This is the generic 'unexpected log line' net catching the WARNING half of that event. product-stale evidence from a pre-fix run.

---

### ~~Unexpected suspicious in debug log: ERROR [Discussion Dispatch Error] Indføring i organisationers opbygning og funktion (LA E2~~
<!-- fp:257805fd303c -->

**Status**: fixed
**Severity**: medium
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 15
**Scenario**: m036 · m036

**Detail**:

ERROR [Discussion Dispatch Error] Indføring i organisationers opbygning og funktion (LA E25 BINTO1060U) :: Spørgsmål til pensum i organisationskultur :: Not Found

**Notes**: Same cause as the undeliverable-discussion entry, fixed 2026-07-28. This is the generic net catching the ERROR half of the SAME log event - a known redundancy with the dedicated check, documented in RUNBOOK 'Known redundancy: one Canvas condition, three findings'. product-stale evidence from a pre-fix run.

---

### ~~An online quiz reached through a module Assignment item is saved a second time, saying '(No content provided)'~~
<!-- fp:92e8dcc3c9f9 -->

**Status**: fixed
**Severity**: medium
**Category**: ui-truth
**Oracles**: O3,O2
**First seen**: 2026-07-28 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 4
**Scenario**: m001 · 43660

**Detail**:

Canvas exposes an online_quiz as BOTH a quiz (107362) and its shadow assignment (32347). With dl_assignments and dl_quizzes both on, the app saves it twice, and the two copies disagree.

The Quizzes/ copy is right: canvas_logic.py:5860-5889 calls get_questions(), Canvas answers 'user not authorised to perform that action' for a student, and the file says 'Could not load quiz questions.'

The Assignments/ copy goes through canvas_logic.py:4621-4646, which never fetches questions at all - it saves the assignment description, which for an online_quiz is empty by nature because the content IS the questions. _save_secondary_entity then renders the generic empty-body placeholder, so the file reads '(No content provided)'.

That is the wrong statement. The quiz has content; Canvas will not serve it to a student. A user reading it concludes the teacher left the quiz empty. The app knows the true reason - it logged it - and the sibling file two folders away says it correctly.

Measured on course 43660: 10 quizzes saved via the quiz path all explain themselves properly; the one quiz that also sits in a module as an Assignment item is the only one that produced a second, misleading file.

**Notes**: Fixed 2026-07-28 and verified against the live API. TWO defects, one root: questions were fetched in exactly ONE of the five places a quiz can be saved, and that one caught the wrong exception - `Forbidden` is a SIBLING of `Unauthorized` under `CanvasException`, not a subclass, so the informative handler was dead code for every student. Now one `quiz_body_html` helper at all three quiz sites and `assignment_body_html` at all three assignment sites, with copy that states the truth. NOTE: the first version of the fix was wrong and only the live API caught it - `get_questions()` returns a lazy PaginatedList, so guarding the CALL catches nothing; the iteration must be inside the try. 21 unit tests passed against an eagerly-raising double. Guarded by tests/test_quiz_body.py, whose fixtures now raise on iteration.

---

### ~~Course Finished reports 2 error(s) but this course's log records 0~~
<!-- fp:eee718626a2e -->

**Status**: fixed
**Severity**: medium
**Category**: ui-truth
**Oracles**: O2,O2
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 87
**Scenario**: m068_c45899 · m068_c45899

**Detail**:

The engine's error counter is not reset per course, so a later course in a batch reports its predecessors' failures as its own.

**Notes**: DUPLICATE of "The per-course 'Course Finished' line reports the whole batch's error count", which this same matrix produced and which was fixed on 2026-07-28 (app.py:1450 filters download_errors_list by course_name; tests/test_per_course_error_count.py). This entry is the MECHANICAL detection of it, added by checker defect 24 on 2026-07-29 - so it necessarily fires on the whole matrix, whose lanes started 18:34 on 2026-07-28 with --server.fileWatcherType=none and therefore ran pre-fix code for all 73 rows. product-stale evidence from a pre-fix run; a fresh run is the only thing that can clear it.

---

### ~~Recordings skipped by the size cap are unexplained, while files skipped by the same cap are explained on the same screen~~~~~~~~~~
<!-- fp:6b8c9476a66a -->

**Status**: fixed
**Severity**: medium
**Category**: ui-truth
**Oracles**: O1,O2
**First seen**: 2026-07-28 (20260728_125433_phase4_panopto)
**Last seen**: 2026-07-28 (20260728_125433_phase4_panopto)
**Occurrences**: 1
**Scenario**: p4_size_gate · 43660

**Detail**:

With the skip-large-files setting at 5 MB, a download of 43660 produced:

  FILES:      '61 files skipped because they exceeded the 5 MB limit. See 61 skipped files'
  RECORDINGS: 'Panopto Recordings - 36 found across 1 course / 0 DOWNLOADED'

All 36 recordings were skipped by the SAME size gate (estimated 6-24 MB each). The debug log says so per recording, with the reason and the estimate: 'Panopto size gate: skipping <title> (~12 MB est > 5 MB limit)'. The completion card says only '0 DOWNLOADED'.

The app already counts this: panopto/runner.py maintains summary['size_skipped'] and increments it at line 752. shared/components.py:render_panopto_summary never reads that key.

The card deliberately does NOT show a generic 'Skipped' stat, and that decision is sound and documented - a big '24 skipped' reads as '24 missing from my course' when those recordings are simply already present. But size_skipped is the opposite case: those recordings are genuinely absent, for a reason the USER chose and the app knows exactly. It is the same class of information the file half of the screen states plainly one line above.

Effect: a user who has ever set a size limit sees '36 found / 0 downloaded' and no reason, on a screen that explains the identical situation for files. The likeliest reading is that Panopto is broken.

Suggested shape, matching the file line already there: 'N recordings skipped because they exceeded the 5 MB limit.'

Not a delivery defect - nothing was lost and the gate did what it was asked. Recorded as ui-truth.

**Notes**: FIXED - but the original finding was HALF WRONG and the correction matters.

The merge it asked for already existed: `app.py`'s Panopto progress handler appends every size-skipped recording to `size_skipped_files`, so the '61 files skipped because they exceeded the 5 MB limit' line ALREADY included them. Verified by counting the run's log: 25 over-limit Canvas files + 36 over-limit recordings = the 61 reported.

What was actually wrong was only the other half - the Panopto card rendering '36 found across 1 course / 0 DOWNLOADED' directly beside that line. Two panels describing one event, one of them phrased as a success metric reading zero.

`render_panopto_summary` had a '_did_work' guard for SYNC mode only; download mode tested `found <= 0`, which is true of neither. The guard is now shared. A failure still renders - suppressing a zero must never suppress an error.  
> Not observed in the latest run.

---

### ~~The per-course 'Course Finished' line reports the whole batch's error count, not the course's~~
<!-- fp:eb27c313381a -->

**Status**: fixed
**Severity**: medium
**Category**: ui-truth
**Oracles**: O2
**First seen**: 2026-07-28 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 4
**Scenario**: m025 · 45899

**Detail**:

app.py computed the per-course error count as len(download_errors_list). That list is created once before the course loop and never reset - the completion screen reads the very same list under the name global_errors - so every course after the first was charged with all the earlier ones' errors.

The download count on the SAME LINE is per-course (download_file_details[course.name]), so the two halves of one line disagreed about what they were counting.

Measured on the three-course row m025: the third course contributed ZERO errors and its line said 'Errors: 5'. Across the run, 124 course-lines reported 312 errors where only 222 exist.

It is a debug-log line rather than a UI one, but it is the line anybody judging a course's health reads - and it sent this audit hunting 90 errors that do not exist across 40 rows before the arithmetic gave it away.

FIXED: count only entries whose DownloadError.course_name matches the course. Guarded by tests/test_per_course_error_count.py, which also asserts the download half of the line stays per-course - fixing one and not the other just moves the disagreement.

**Notes**: Fixed 2026-07-28. Counts only entries whose DownloadError.course_name matches the course. tests/test_per_course_error_count.py also asserts the DOWNLOAD half of the same line stays per-course - fixing one and not the other just moves the disagreement.

---

### ~~A read-only destination leaves the previous copy on disk, untracked and unexplained~~~~~~~~~~~~~~~~~~
<!-- fp:7eaa8671abd1 -->

**Status**: fixed
**Severity**: low
**Category**: delivery
**Oracles**: O3,O4
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 3
**Scenario**: p2r_defaults · 45899

**Detail**:

When a clean update's destination cannot be written (the classic 'the file is open in Word' case), the engine correctly writes X_NewVersion.pdf instead of failing the run - no data is lost and one locked file does not cost the whole sync. It then REPOINTS the manifest row to the _NewVersion sibling, which leaves the original X.pdf on disk with no manifest row.

Verified on disk after the sync: both files present, the original still read-only, the row on the sibling. A SECOND analysis was run to test whether the orphan would be re-offered as New or re-adopted by heal Tier 1 (its name is an exact match for the Canvas filename) - it is neither. The state is stable, so this is not a loop and not a correctness bug.

What remains is a small user-facing cost: the folder now holds two copies, the one with the ORIGINAL name is the stale one, and nothing in the app says so. Raised as low rather than as a defect because the alternative - overwriting a file the user has open - is far worse, and because the app is silent rather than wrong. Worth a decision: leave as is, or mention it on the completion screen alongside the existing 'files were skipped' notice.

**Notes**: FIXED 2026-07-28, and the original finding was partly wrong - it said "nothing in the app says so". There IS a "Modified Files Protected" card listing every _NewVersion file with its folder; it just sits inside the collapsed "Files added" expander, so a user who never expands it sees nothing.

Two changes shipped:

1. A short INFO notice on the sync completion screen, directly below the "files were skipped because you ignored them" one: *"N files were saved as a separate copy so we didn't overwrite your version"*, with the _NewVersion naming, an example filename, and what to do (compare, keep one, delete the other). Verified rendering in the real app.

2. The card's subtitle said *"Saved alongside the files you had edited"*, which is FALSE for the locked-file route - the category is assigned purely from the "_NewVersion" filename, so a file that was merely open in another program landed there too and the user was told they had edited something they never touched. Now *"Saved next to your copy, which was left untouched"*, true of both routes. The category legend on the sync page was corrected the same way. Verified in the real app via the sync-history panel, which shares the renderer.

Guarded by tests/test_newversion_notice.py, including a check that every _NewVersion construction site in the sync engine is instrumented, so a third route added later cannot silently under-report the count.  
> Not observed in the latest run.

---

### ~~A locked DOWNLOAD target falls back gracefully; a locked CONVERSION target fails hard~~~~~~~~~~
<!-- fp:fa5b7101bfd4 -->

**Status**: fixed
**Severity**: low
**Category**: robustness
**Oracles**: O2,O3
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 2
**Scenario**: p2nv_selected · 45899

**Detail**:

Two write paths, two different behaviours for the same user situation (a file open in another program):

DOWNLOAD: os.replace onto a locked target raises PermissionError, and the engine delivers the bytes alongside as X_NewVersion.ext. The run continues, nothing is lost, and the completion screen now explains it.

CONVERSION: the converter writing its output onto a locked target (e.g. code.js -> code_js.txt where the .txt is open) raises 'Permission denied' and the file is simply counted as a post-processing failure. No _NewVersion fallback exists on this path.

Not silent, and not destructive: the failure appears in the post-processing warning on the completion screen and in download_errors.txt, and the downloaded source survives, so the user can close the file and re-sync. Rated low for that reason. Recorded because the asymmetry is invisible from the code - the download fallback reads like a general policy and it is not - and because the same locked file produces a tidy outcome through one path and an error through the other.

Found while building the readonly_target fixture: it had been locking a CONVERSION OUTPUT rather than a download target, so it was silently exercising this path instead of the one it was written for. The fixture now picks only files whose local extension matches their Canvas filename.

**Notes**: Fixed with B then C. (B) One retry pass runs at the end of post-processing, in BOTH flows, over every conversion whose source is still on disk - which is the whole failure set, because every source-consuming converter deletes its source on success. That single signal is what let one pass cover all nine runners without touching any of them. (C) Whatever fails twice is reported by name, and when a locked file sharing the source's stem can be found the message names it: "'code_py.txt' is open in another program. Close it and sync again." Failure counts are reconciled so a recovered file is not still counted as failed and a twice-failed one is counted once. A crashing retry can never take down the run.  
> Not observed in the latest run.

---

### ~~Debug log records per-file rows for only 2 of the 7 sync categories~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:f695845da958 -->

**Status**: invalid
**Severity**: low
**Category**: robustness
**Oracles**: —
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-27 (20260727_165705_bootstrap)
**Occurrences**: 1

**Detail**:

sync/analysis.py:247,250 log a [NEW] and [UPDATE-CLEAN] line per file. The other five categories - locally-edited updates, deleted on Canvas, deleted locally, ignored, up to date - appear only as counts on the 'Analysis complete' line. Verified on a run reporting 2 deleted-on-Canvas and 2 ignored: zero per-file rows for either.

Consequence: a shared debug log cannot answer WHICH file the app put in those categories, so 'why did it not re-download X?' is undiagnosable after the fact, and any log-based verification is blind to five sevenths of the classification logic. Extending the existing one-line-per-file treatment to the remaining categories is a few lines and makes the log a complete record of the decision.

**Notes**: AUDIT ERROR, not a product defect. The grep used tag names that do not exist (UPDATE-MODIFIED/DELETED-CANVAS/DELETED-LOCAL); the real tags are UPDATE-EDIT/CANVAS-DEL/LOCAL-DEL, and five categories were already logged. Superseded by the 'omitted the Ignored category and printed URL-encoded filenames' entry, which is the accurate version and is fixed. ---  
> Not observed in the latest run.

---

### ~~Sync review: 'Updates Available — You've Edited These' rendered untinted while its five siblings matched their icons~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:70a043d21429 -->

**Status**: fixed
**Severity**: low
**Category**: ui-truth
**Oracles**: O1
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-28 (20260727_165705_bootstrap)
**Occurrences**: 3
**Scenario**: p2_sync_45899

**Detail**:

styles/sync_review.css colour-codes each category expander with a substring selector. div[class*="st-key-cat_update"] reads as though it covers cat_updmod_ and does NOT: the keys diverge at upd-M-od vs upd-A-te. So the edited-updates category rendered with an amber icon and an amber summary tile on top of an untinted card, breaking the one visual cue that distinguishes six stacked categories at a glance.

Nothing errors and nothing logs - a substring selector that stops matching is invisible in review, which is why it survived.

Fixed with its own rule using rgba(245,158,11) = theme.WARNING, which is the colour the legend card in ui/sync_review.py (_cc_edited) already assigns to this category, so the expander and the legend explaining it cannot drift. Verified live: all six categories now report the accent their icon uses. Guarded by tests/test_sync_review_category_colours.py, which also fails if a NEW category is rendered without a tint, and asserts no two category selectors can match each other's containers.

**Notes**: Fixed 2026-07-27. Own rule in styles/sync_review.css using theme.WARNING, verified live on all six categories. Guarded by tests/test_sync_review_category_colours.py. ---  
> Not observed in the latest run.

---

### ~~Today says 'You're all caught up' while a daily course is broken and its 15 arrivals are hidden~~~~~~~~~~
<!-- fp:aa56baa0771b -->

**Status**: fixed
**Severity**: low
**Category**: ui-truth
**Oracles**: O1,O2
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 2
**Scenario**: t3_missing_folder · 45899

**Detail**:

With a daily course whose folder has been renamed or moved, the Today page correctly: keeps the course listed, marks its chip amber (today_chip_missing_0), skips it rather than pausing the daily sync, and shows no per-course state for it. All of that matches the documented contract and is right.

The 'Today's files' panel then reads: 'No new files today. You're all caught up.'

That is a positive assertion, and in this state it is not quite true - 15 files DID arrive today for that course; they are simply in the folder the user moved, and the page cannot resolve it. The off-list footnote does not cover the case either, and correctly so: its wording is 'a course that isn't in your daily sync', and this course IS in it.

So the only signal is the amber chip. That is arguably enough - a user who sees amber investigates - which is why this is low and not a defect. Recorded because the Today page's stated principle is that it must SAY what it is hiding, and this is the one state where it hides something and says the opposite. A one-line variant of the empty state when any daily course is amber ('N course needs attention above') would close it without touching the rest.

Verified: folder renamed on disk, page reloaded, chip amber, no outage screen, no error text, Quick Sync still offered.

**Notes**: Fixed with option A - the empty state is now conditioned on the unreachable list rather than replaced wholesale. A broken daily course reads "No new files today / N course above needs attention, so it was skipped." The healthy case still says "You're all caught up." and the no-courses case is untouched. Verified live in all three states. The contract is unchanged: an unreachable course still gets no card and no file list of its own, and the daily sync still skips it rather than pausing.  
> Not observed in the latest run.

---
