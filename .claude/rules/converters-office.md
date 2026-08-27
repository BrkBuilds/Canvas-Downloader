---
paths:
  - "converters/**"
  - "engine/applescript_bridge.py"
  - "engine/post_processing_bridge.py"
---

# Converters and the Office pipeline

> Extracted from CLAUDE.md. Loads only when Claude opens a matching file.
> Each entry states the mechanism, the measurement, and why the obvious fix is wrong.

## Post-processing: a phase is a sibling, and BOOKKEEPING must not undo finished work
- **One phase failing must not cancel the ones after it.** The nine `run_*` conversion runners are independent - a wedged COM server has no bearing on HTML→Markdown - but only `run_excel_data_conversion` had a per-item handler and `run_all_conversions` called all nine bare. One unexpected exception therefore took out every later phase **and `retry_failed_conversions`**, which is the thing that would otherwise have recovered the files. `_run_phase(runner, items, ui)` is the single guard, at the boundary the phases are already independent across; it cannot be forgotten when a tenth converter is added, and a test asserts every call site goes through it. It also clears `active_file_placeholder`, which the runners only do on their normal exit - otherwise the line stays stuck on whichever file blew up.
- **`_update_manifest_path` must never raise.** By the time it runs the converted file is on disk and the original is deleted; all that is left is repointing a manifest row. But `load_manifest` deliberately RE-RAISES database errors ("Aborting to prevent data loss"), so a manifest briefly locked - by antivirus, or by the sync that has just finished writing to it - aborted the whole conversion phase mid-way. The trade is explicit: swallowing it costs one stale row that the next sync's heal pass fixes, propagating it costs every remaining file in the phase. Logged at warning, never silent.
- Note the interaction with the sqlite classification above: making a transient DB error *stop resetting the manifest* means `_db_init_failed` is now reachable where it previously was not, and `load_manifest` raises on it. That is the intended trade (loud beats silent), but it is only safe because post-processing no longer treats a manifest failure as fatal.

### …and the repoint must not depend on how the path is SPELLED (2026-08-21)
Measured by the live macOS audit driving the PACKAGED app through a real run of course 43660: **62 of the 63 Office files converted in that run left their manifest row pointing at the source the converter had just deleted.** The one that repointed was an Excel file - and `converters/excel.py` is the only one of the three Office converters that does not call `resolve()` on the path it returns.
- **`Path.relative_to` is a STRING operation.** `converters/pdf.py` and `converters/word.py` both return `str(dst.resolve().absolute())` from their macOS branch while `sm.local_path` carries whatever spelling the destination was CONFIGURED with. Wherever the course folder is reached through a symlink - `/tmp` → `/private/tmp`, or a course folder linked onto an external drive, which is an ordinary thing for the small-SSD student this product is aimed at - the two spellings differ, `relative_to` raises, and **both** call sites swallowed it without a word. Same app, same course, same converter, silently different outcome depending on how the destination happened to be spelled.
- **It is not untidy bookkeeping, and the sync engine's own code says why.** `analyze_course`'s missing-local-file branch carries an explicit **URL Compiler bypass** (`.url`/`.webloc` gone while `convert_urls` is on → `uptodate_files`) and an **Archive Extraction bypass** - because those two converters are many→one and one→many and *cannot* repoint. There is deliberately **no such bypass for Office**, because Office is 1:1 and is supposed to repoint. So a stale Office row falls to `locally_deleted_files` and is re-offered as a **restore** on every later sync, its PDF sits untracked, and a re-download plus re-conversion then overwrites that PDF - which is how a student's annotated copy is lost.
- **`_course_relative(sm, path)` is the one primitive** both sites use: try the paths as given, then compare **realpaths** - the one spelling both sides can always agree on. `os.path.realpath` rather than `Path.resolve` because it is defined on a path that no longer EXISTS, which `original_file` never does by then (every source-consuming converter deletes its source before reporting success).
- **Both silent paths are now loud, because the silence is why it shipped**: a path genuinely outside the course warns, and a lookup that matched no row is logged at debug instead of being indistinguishable from a successful repoint. A conversion whose source was never tracked (an extracted archive member, a secondary-content render) is ORDINARY, so that one is debug and not a warning.
- **The mutation pass found the fix INCOMPLETE, and that is the reusable part.** `_resolve_conversion_target`'s "is the recorded product beside the source" test compared **absolute** parents (`prod_path.parent == src.parent`), so a resolved `src` still disabled the ownership check even once the relativisation was fixed - and that check is the one that diverts to `_NewVersion` when the student has annotated the product. Both comparisons are now course-relative (`PurePosixPath(prod_rel).parent == PurePosixPath(src_rel).parent`).
- **The user-visible consequence is MEASURED, not reasoned.** A live sync analysis of the packaged run's folder renders **"63 Deleted locally"** on the review screen - 0/63 selected, Smart Select offering them as DOC / PPTM / PPTX - which are exactly the 63 Office sources the conversion consumed. Header: *"63 files pending sync, 199 files up to date"*. Nothing re-downloads silently (the boxes default unchecked), so it is a reporting defect rather than data loss - but it recurs on every sync, and "Select All here" is the natural response to being told 63 files are missing, which re-downloads ~180 MB of PowerPoints and then overwrites the PDFs the user already has.
- Covered by `tests/test_conversion_repoint_spelling.py` (12); all **8** mutations caught (`scripts/_mutate_conversion_repoint.py`), so re-run the mutation pass rather than just the suite. **Two of those mutants were surviving gaps in my own tests** - one asserted a rootless manager only for a path outside the cwd, and there was no test at all for the ownership site.

## `office_safe_path` is FOR long paths - so its own I/O has to be long-path safe
The context manager exists only for sources ≥ 240 chars (Office COM hard-crashes on them), and then read the source and wrote the destination **without the prefix** - so on a default Windows install, where `LongPathsEnabled` is 0, the one function meant to handle long paths could not read or write them. Fixed via `make_long_path` on the shadow copy, the destination `mkdir` and the move-back.
- **The asymmetry is the whole point and a test pins it**: OUR file operations need the prefix; the paths we **yield** must not have it, because Office COM chokes on a `\\?\` path too. That is why the shadowing exists at all.
- **Not reproducible on a machine with `LongPathsEnabled=1`** (this dev box has it), which is exactly why it survived: everything passes locally that fails on a stock install. Same reasoning and same fix as the note in `panopto/stream.py`. When a path-length fix "can't be reproduced", check that registry key before concluding there is no bug.

## Deleting the SOURCE is the one irreversible step - audit the six as a FAMILY
Six converters delete the file they converted FROM. The pattern was correct in three (`code.py`, `md.py`, `url.py` - fsync, then verify, then delete) and absent in three, which is precisely how it stayed unnoticed: any single file read as fine.
- **`video.py` was the worst of them.** `conversion_success = True` was set the instant `write_audiofile` RETURNED, with nothing looking at the result, and the `finally` then deleted the source. `write_audiofile` drives ffmpeg through a pipe and can return having produced no usable audio. The file deleted on that evidence is a lecture VIDEO - the largest and least replaceable artifact the app handles, and for a Panopto capture possibly not re-downloadable at all. **The check has to happen before the `return`, not in the `finally`**: by the time the finally runs the function has already returned the mp3 path, so the caller records a success and repoints the manifest at a file that is not there. Returning `None` leaves `conversion_success` False, so the video is kept and the failure is honest.
- **`archive.py` deleted the zip without checking anything came out.** Both paths can produce nothing while raising nothing: `_filter_zip_members` strips every `__MACOSX/` and `._*` entry, and tarfile's `data` filter SILENTLY SKIPS members it deems unsafe. An archive whose whole content is filtered away therefore left an empty folder and no archive.
- `converters/verify.py` holds both gates - `pdf_looks_real` (magic + size) and the generic `file_has_content(path, min_bytes)`. Err LOW on the floor: a false negative keeps a file the user already has, a false positive deletes it.
- **What the sync engine deletes, for the record**: only `.part` intermediates, plus a *superseded pristine* copy after a clean rename - guarded on `is_update_clean` (never a locally-modified file) and a `normcase` comparison so it can never delete the file it just wrote. It never deletes on the strength of a Canvas-side diff.

## A declined extraction must leave NOTHING behind (2026-08-07)
`converters/archive.extract_archive` creates the target folder **before** it can read the archive's member list, so every guard that trips afterwards - the zip-bomb ratio check, the zip-slip / tar traversal blocks, a corrupt archive - left an empty directory sitting next to the untouched archive. `_decline()` already existed for exactly this on the `max_files` path and says so in its own docstring; the exception path simply never called it. Now it does.
- **`_decline` uses `os.rmdir`, which removes ONLY an empty directory** - that is what makes this safe for a PARTIAL extraction. Anything already written keeps the folder, and the folder stays; a test drives a mid-extraction `OSError` to prove it.
- Do not "improve" it to `shutil.rmtree`: that would discard files a half-finished extraction had already produced, turning a recoverable failure into data loss. `tests/test_archive_decline_cleanup.py`; all **5** mutations caught, including the rmtree one.

## An Office converter deletes the user's original - so the PDF must be PROVEN first
Every Office converter ends by deleting the file it converted FROM. That is intended (the PDF replaces the legacy `.doc`/`.xls`/`.ppt`) and it is the one irreversible step in the pipeline, on a file that may be the user's only copy. **Word and Excel were doing it on the strength of "the COM call did not raise"** - and Office does not always raise: `SaveAs` / `ExportAsFixedFormat` can return normally having written nothing (a protected or repaired document, a locked-down `AutomationSecurity` policy, or for Excel a broken printer driver, which its PDF export goes through). PowerPoint tested `exists()`, which still passes a 0-byte stub. `converters/verify.py:pdf_looks_real` is the shared gate (present, non-empty, `%PDF` magic, not truncated) and all three call it BEFORE the delete; the tests assert the ordering, not mere presence.

**That fix landed on ONE PLATFORM ONLY, and the miss survived until 2026-08-08.** Each converter has TWO delete sites - the Windows/COM branch and the macOS/AppleScript branch - and only the COM one got the gate. The macOS branch deleted the original on `run_applescript` returning True, whose success test is **`dst.exists()`** - which is *precisely* the check the paragraph above records as too weak ("PowerPoint tested `exists()`, which is better but still passes a 0-byte stub"). So on macOS the very same stub that motivated this section still destroyed the user's only copy of a `.doc`/`.xls`/`.ppt`. Driven down the real macOS branch (by making `sys.platform` report `darwin` and letting the bridge leave a stub): before, all three deleted the original for a 0-byte, a truncated and a non-PDF output; after, all three keep it and report why, while a genuine PDF still replaces the source. **The lesson is the counting one**: a converter with two delete sites needs two gates, and `tests/test_crash_vector_hardening.py` now asserts `len(pdf_looks_real) >= len(source unlinks)` per file rather than "a gate exists".

## The tracked Office PID was a GUESS, and the watchdog force-kills it (2026-08-21)
`find_new_office_pid` returned the FIRST process of its name that was not in the
pre-dispatch snapshot, with nothing checking it was ours. Found by the Windows
session (`fp:a41c7e0b93d2`), measured against `Application.Hwnd` ->
`GetWindowThreadProcessId` as ground truth with two concurrent instances:

    lane A   guessed = 2448   TRUE = 9816
    lane B   guessed = 2448   TRUE = 2448

- **This resolves BOTH loose ends the register carried since 2026-08-08.** *"The
  app killed every instance it tracked"* is true because it tracked 2448 twice;
  the 5h54m orphan appearing *"inside a row whose `convert_excel` was never
  applied"* is because attribution was CROSS-LANE. **There is no special row -
  the trigger is any two concurrent `_init_app` calls.**
- **IT IS NOT HARNESS-ONLY, and that is why it was fixed rather than noted.**
  One process, no harness: the user opens their own workbook, the app
  dispatches, and `find_new_office_pid` returns THEIR pid. The 180 s watchdog
  then `taskkill /F`s their unsaved document - the precise outcome this module's
  own docstring says it exists to prevent. Window measured: **Excel 0.506 s,
  Word 2.344 s, PowerPoint 2.357 s**, reopening on every conversion batch.
- **The discriminator was already MEASURED, twice, and sitting in the register**:
  a COM-activated Office is `EXCEL.EXE /automation -Embedding`, parent RPCSS -
  *"COM-launched and headless, NOT a user's own Excel window"*. A document the
  user double-clicked never carries it. So the fix applies an established fact
  rather than a new heuristic; the answer had been written down for two weeks
  next to the finding it solves.
- **Two rules: only a COM-activated process can be ours; more than one candidate
  is AMBIGUOUS -> `None`**, decided after a settle re-check so a racing sibling
  cannot be missed by deciding on the first sighting.
- **WHY IT SHIPS WITHOUT THE SECOND HALF, which is the transferable part.** The
  Windows write-up said both halves must land together, because "stop guessing
  when ambiguous" makes `kill_office_pid`'s broad `/IM` fallback more reachable.
  That is true of an ambiguity rule ALONE. It is **not** true with the
  `-Embedding` filter: for an ordinary single instance the candidate set is
  exactly one whether or not the user has Office open - their process is
  FILTERED OUT rather than making the answer ambiguous - so `None` does not
  become more common and the fallback is no more reachable than before. Choosing
  a discriminator that *excludes* rather than one that *confuses* is what
  decoupled a "both halves or nothing" change into a shippable one.
- **Pure `psutil`, no COM, deliberately.** The exact answer is the window
  handle, and the Windows session proved it works - but
  `tests/test_crash_vector_hardening.py` pins that everything between
  `DispatchEx` and the PID capture is a window where a raise strands a real
  process, and a property read on a build that refuses it is exactly such a
  raise. A command line is readable from outside the process and adds nothing to
  that window.
- **The broad `/IM` fallback is a SEPARATE, pre-existing data-loss path and is
  deliberately untouched.** It closes every instance of that app, the user's
  documents included - but the kill is what unblocks the stalled COM call in the
  main thread, so simply refusing turns a 180 s hang into an unbounded one, and
  the daily auto-sync is unattended. A test pins it so it cannot be deleted as
  "obviously wrong" without that trade being decided.
- `tests/test_office_pid_attribution.py` (24, and they PASS on Windows - the
  first Mac-written code to execute there); `scripts/_mutate_office_pid_attribution.py`
  **10/10**. One survived first and was a real gap: every fixture let the
  `-Embedding` filter do `pre_pids`' job, so nothing covered a **leaked orphan
  from an earlier batch** - which is `-Embedding` too, and which only the
  snapshot excludes. Without it the next init sees orphan + ours, calls it
  ambiguous, tracks nothing, and **the leak compounds for the life of the
  session**.

### `_path_key`'s unconditional fold on Windows: MEASURED, and not reachable by default
Left open on 2026-08-21 when the macOS session found that `_path_key` gates its
case-sensitivity probe off on Windows (`if os.name != 'nt' and ...`), so the fold
is unconditional there - wrong inside a directory made case-SENSITIVE with
`fsutil file setCaseSensitiveInfo`, which WSL uses. **Answered the same day on
the real machine: WSL is installed, and Downloads, the home directory and the
repo all report case-sensitivity DISABLED.** So the asymmetry is not reachable
by default even with WSL present.
- **Do not "fix" it speculatively.** The fix means adding a `samefile` probe to
  a hot comparison loop on the platform with ~94% of installs, to serve a state
  a user must deliberately opt into per directory. The mirror-image macOS bug
  WAS worth fixing because the default there is case-insensitive and the
  probe answered wrongly at a mount point - i.e. it fired without the user
  doing anything.

## The staged product is promoted only if it is REAL (2026-08-11)
`office_container_stage`'s exit promoted anything that EXISTED, under a comment calling it the "success path". A conversion that errors part-way still leaves whatever Office had written.
- Measured: an **870-byte "PDF"** in course 43660 beside the `.pptx` it failed to convert - tracked by nothing, so re-offered as NEW on every future sync for ever. **And `dst.unlink()` runs first**, so a failed re-conversion DESTROYED the good PDF a previous run had produced. The folder went backwards.
- The gate is the same `converters.verify` pair every source-deleting converter already applies afterwards, placed **at the promotion** - the boundary all three converters cross, so a fourth gets it free. Asking in both places is not redundant: this decides what the user's FOLDER gains, the converter's decides whether the ORIGINAL may be deleted.
- **The no-container path is asymmetric on purpose**: a reject that created a new file is removed; a reject that OVERWROTE something is KEPT and reported, because deleting it would turn a damaged file into a missing one and a manifest row may point there.
- Same class as `converters/archive.py:_decline`, in the module that fix did not reach. `tests/test_office_product_gate.py`; all **9** mutations caught.
