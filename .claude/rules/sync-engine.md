---
paths:
  - "core/**"
  - "sync/**"
---

# Sync engine, manifest and analysis

> Extracted from CLAUDE.md. Loads only when Claude opens a matching file.
> Each entry states the mechanism, the measurement, and why the obvious fix is wrong.

## A SENTINEL is not a measurement, and a display cell must never print one (2026-08-07)
`shared/helpers.check_disk_space` fails OPEN and reports **-1** for available/total when it cannot read the volume at all (invalid drive letter, disconnected share, any `OSError`). The Confirm Sync dialog multiplied that straight out and printed it: an unreachable target rendered **"Available Disk Space: -1048576 B"**. Reproduced against the real helper on `Q:
onexistent`.
- **`format_file_size` is a DISPLAY CELL** in exactly the sense `engine/progress_dashboard.py` means, and is bound by the same rule that module already states ("nothing a counter can hold may raise or render as a non-number"). It is simply the one such cell that lives OUTSIDE that module - in `core/sync_manager.py` - so the hardening pass there never reached it, while **18 render sites** call it, several inside an `@st.dialog` where a raised exception blanks the modal. It now coerces non-numeric/NaN/inf to 0 and **clamps negatives**, so it can never emit a negative byte count whatever a subsystem hands it.
- **The `None` half is not hypothetical**: Canvas sizes are read as `getattr(file_obj, 'size', 0)`, and that default applies only when the attribute is ABSENT - present-and-null yields `None`. `core/canvas_logic.py` writes `... or 0` at ONE `original_size=` site and not at the four others, so the codebase is already split on whether that happens, and a `None` reaching a manifest row comes back out of it into `ui/sync_dialogs.py`'s `format_file_size(f.original_size)`.
- **"0 B" is NOT the fix for the sentinel and must never be substituted** - it reads as a completely full disk, which is wrong in the opposite direction and would make a user cancel a sync that had plenty of room. `shared/helpers.format_available_space()` is the ONE renderer that says **"Unknown"**, and it lives beside `check_disk_space` because the sentinel is that function's convention (`DISK_SPACE_UNKNOWN`). A genuine zero still formats as "0 B" - the two mean opposite things and must not collapse.
- **The first version of the test re-implemented the dialog's expression instead of calling it**, and two mutations survived because of it - the same "verify the REAL thing, not a copy" trap this file already documents. Extracting the decision into one named function is what made it testable. `tests/test_file_size_display.py`; all **11** mutations caught.

## Secondary content: seven independent categories, and work already IN FLIGHT
`_download_secondary_content` ran its seven `_fetch_and_save_*` categories as seven bare calls in a row. A malformed quiz says nothing about the user's submissions, but the first category to raise took out two things:
- **every category after it**, silently - the user asked for quizzes + submissions + rubrics and got one generic "Canvas Content Error" with no way to tell which parts ran (the outer handler in `_canvas_content_phase` catches it, so this was never a crash - just missing content);
- **the `asyncio.gather` at the end**, which is what awaits the attachment tasks assignments/announcements have already `create_task`'d. Skipping it means `asyncio.run` cancels them at loop close and those files silently never arrive.
`_sec_category(label, fn, *args)` isolates each one and names it in the error; the gather moved into a `finally`, because work already scheduled must survive a failure in a LATER category. Same principle as `_run_phase` in post-processing: **guard at the boundary the siblings are already independent across.**

## The `_NewVersion` redirect must be COMMITTED before it is announced
`_download_file_async` diverted an edited local file to `<stem>_NewVersion<ext>`, then announced it via `progress_callback`, and only THEN assigned `filepath = _diverted`. Anything the callback raised therefore skipped the assignment, left `filepath` pointing at the user's edited copy, and the download below overwrote it - with the enclosing handler a bare `pass`, so nothing recorded that the protection had been bypassed. A UI callback is precisely the kind of thing that raises. **Commit to the safe path first; the cosmetic step follows.** Reordering means `filename` is already the new name when the message is built, so the original is captured in `_original_name` - the sentence is about the file the user edited, not the one being written. Note the INNER handler was always correct (`_pristine = False` on failure → divert), which is what made the outer one easy to miss.

## `result.new_files` was rebuilt from a dict keyed by FILENAME (2026-08-21)
Canvas keeps **one `filename`** when a file is uploaded twice and disambiguates
only the `display_name` (`X.pptx`, `X-1.pptx`). `analyze_course` built
`new_name_map` so the teacher-re-upload check could look a new file up by name,
and then rebuilt `result.new_files` **from that map's values** - and a dict keyed
by name cannot hold two files that share one. The loser of the `setdefault` was
dropped from the offer entirely: **not new, not up to date, not deleted on
Canvas, not deleted locally - absent from every category the review screen can
show.**
- **`_match_key` UNQUOTES, which is what makes it reachable with ordinary data.**
  Canvas's `+`-encoded upload name and the plain display name of the same file
  collapse to ONE key, so the copy whose `display_name` still equals its
  `filename` has a single key while its sibling has two. If the sibling is listed
  first that key is already taken - **so which copy vanishes is decided by the
  order Canvas happened to list them in**, which is why it looked arbitrary.
- **It self-heals on the NEXT sync** (the offered copy gains a manifest row and
  stops competing for the key), which is exactly why it was carried for ten days
  as *"re-offered one per sync, not both"* with its mechanism unestablished. The
  cost is real anyway: until the user syncs a second time, a file Canvas is
  offering is one the app never mentions.
- **The inspection that stalled the previous pass was right as far as it went.**
  The file DOES reach `raw_new_files` and no auto-discovery tier defers it; the
  drop is ~120 lines further down, in a loop whose comment says *"Deduplicate new
  files that were registered under two name keys"* - written to undo a DOUBLE
  registration, and discarding single ones too.
- **The fix keeps the map as a lookup index only.** The re-upload branch records
  what it takes over in `_reupload_consumed` **by identity** - the whole point is
  that names collide - and `_unique_new` is every regular new file that set does
  not name, in Canvas order. Both halves of the map's key registration are
  load-bearing and a test pins each: an OLD manifest row records the raw Canvas
  `filename`, a new one records the display-derived on-disk name, and they are
  different strings whenever a teacher curated the display name.
- **Measured twice against the real product**, not against a mock: ids 1560011 /
  1560205 driven through the real `SyncManager` against an APFS clone of the real
  course folder and its real 262-row manifest with the run's own O5 Canvas
  metadata (`new=1`, 1560011 nowhere -> `new=2`, both offered); and the
  `CBS_SolbjergPlads_ImageHeader.jpg` TRIPLE (2 of 3 -> 3 of 3), where the
  missing copy is exactly the one whose display_name equals its filename, as the
  live run had shown. **NOT yet seen on the review SCREEN** - that needs a live
  sync matrix.
- `tests/test_new_files_are_not_name_keyed.py` (14);
  `scripts/_mutate_new_files_name_key.py` **7/7 caught**, so re-run the mutation
  pass rather than just the suite. Three mutants survived the first version of
  the tests and each was a real gap.

## …and a DELETED row took a file with it - the same class, one loop down (2026-08-21)
Found by asking what ELSE removes a file from the offer without accounting for
it. Two mechanisms, each correct alone, wrong together - which is exactly why
nothing caught it:
- **The teacher-re-upload branch takes a NEW Canvas file OFF `new_files`** and
  rides it on a locally-deleted row. That is M-6 policy and it is right: the
  user deleted their copy, so the replacement must not be offered as if nothing
  had happened.
- **The phantom-row prune then DELETES that row**, when its basename is owned by
  another tracked row whose file exists. The file was in `new_files`, is now in
  neither, and **is a file the user has never had**.
- Measured against the real analyzer: row 100 (`A/notes.pdf`, gone from Canvas,
  deleted locally) consumes new Canvas id 200 (`notes.pdf`); row 100 is pruned
  as superseded by row 101 (`B/notes.pdf`, same basename, different folder,
  present); **200 lands in NO category and `new=0`**.
- **The fix is that a row being deleted gives back what it had taken**, and the
  offer is computed BELOW the pruning block. Not that the prune should match
  more narrowly: `_live_name_keys` is keyed by BASENAME on purpose, narrowing it
  risks resurrecting the "Deleted Locally on every sync for ever" defect it
  exists to fix, and it costs nothing here - the row's own id is gone from
  Canvas, so the local file it described is unrecoverable either way. **The only
  thing a dying row must not take with it is a file that is still on Canvas.**
- Note the contrast one prune up: the *case-B* prune keys on `_path_owner_map`,
  i.e. on a real PATH identity, and is correct. Two prunes for one idea, two
  strengths of identity - the weaker one is the one that bit.
- It self-heals on the next sync (the prune really does delete the row, so
  nothing consumes the file twice), the same shape as the name-keyed drop above
  and worth just as little.

## CONSERVATION is the invariant that makes both of those impossible
Both defects are the same shape and NEITHER is a wrong classification - which is
what every other check looks for. Both are a file that is simply **absent**: not
new, not up to date, not updated, not deleted anywhere. **Nothing on the review
screen can show a row that was never produced**, so the only way to see it is to
count.
- **The property**: every `CanvasFileInfo` handed to `analyze_course` appears
  exactly once across `new_files` · `uptodate_files` · `updated_clean_files` ·
  `updated_modified_files` · `ignored_files` · `locally_deleted_files` ·
  `deleted_on_canvas` · riding on a locally-deleted row - or is counted in
  `out_of_scope_files`, the one place the analyzer legitimately declines to
  produce a row and says so with a number.
- **`locally_deleted` and `deleted_on_canvas` ARE landing places for an input
  file.** Leaving them out is how the first version of this accounting reported
  a false loss on a perfectly healthy shape; a row whose local file is gone is a
  legitimate answer about a file Canvas still has.
- **`tests/test_analysis_conservation.py` asserts it over 500 deterministic
  generated states**, whose generator draws names from a SMALL vocabulary and
  ids from a small pool - collisions are the entire point, and a generator
  producing unique names everywhere would exercise none of this.
- **The control is part of the definition of it working.** Mutating either fix
  back out makes the sweep report **49** and **15** losing seeds out of 600. A
  property test that passes on broken code is worth nothing.
- Mechanical sweeps for the literal pattern came back clean and are worth not
  repeating: every other name-keyed structure in `core`/`sync` uses
  `setdefault(k, []).append(...)` (a list, which cannot drop), the only
  scalar-valued one left is `pair_labels`' label index (first-wins is its
  DOCUMENTED precedence rule), Panopto's `videos` dict is keyed by delivery id
  and its one re-key is guarded by `taken`, and `all_files_map` is keyed by
  Canvas id. Four `if <name> in <seen>: continue` sites exist and all four are
  benign (app-owned filenames, and one keyed on a real PATH).


### Two things conservation does NOT cover - stated rather than implied
- **A file can be CONSERVED and still be invisible.** The re-upload hand-over
  parks a genuinely new Canvas file on a locally-deleted row, and that row is
  **unchecked by default** (M-6 respects the user's deletion). So the file is
  accounted for, the review screen shows a row, and a user who leaves the
  default alone downloads nothing - while the row is labelled with the OLD
  file's name, not the new one. That is correct when the two really are the same
  file re-uploaded, and merely opaque when the name match was a coincidence
  across folders. Considered on 2026-08-21 and deliberately NOT changed: it is
  the documented M-6 policy, and changing which category a file lands in is a
  product decision, not a bug fix. Recorded so the next session does not
  re-derive the question and quietly answer it differently.
- **Only `analyze_course` is asserted.** The DOWNLOAD engine has the same shape
  of question - every Canvas file the scan produced either lands, is deferred to
  a later phase, or is reported - and it is covered only by the audit's own
  `_count_coherence`, which is a per-run check rather than a property over
  generated states. That is the obvious next place to point this instrument.

## The layer that decides WHAT to download had no retry; the one that fetches it always did (2026-08-22)
A single transient 502 on `GET /courses/{id}/modules/{mid}/items` dropped that module from the metadata scan for the whole run - silently, because the consumer does `if items is None: continue`. `get_course_files_metadata` feeds **both** `sync/analysis.py` and the download engine, so that module's Pages, links and `module_map` entries simply did not exist for that run. Meanwhile `sync/execution.py` has retried 5xx with backoff on the FILE-DOWNLOAD path all along. That asymmetry is the whole finding.
- **Fixed at the chokepoint, not the call site that failed.** `_new_canvas_client` is the ONLY place a canvasapi session is built (the main client and both per-worker clients), so one `Retry` on its adapter covers the bulk `get_files()`, `get_modules()`, the module-items fan-out and the per-file fan-out together. **Panopto is unaffected** - it builds its own `requests.Session`.
- **Every parameter is a decision AGAINST a default, and each was measured against a real local HTTP server** rather than read back off the `Retry` object, which would only prove you typed what you typed: 502 twice then 200 -> 200 in 1.01s; `503 + Retry-After: 86400` -> **200 in 1.01s, NOT parked**; 404 -> 1 request; 429 -> 1 request; 502 on POST -> never replayed.
- **`respect_retry_after_header=False` is load-bearing.** urllib3 honours the header by default, and this repo already has a finding where a literal `Retry-After` parked a download for a DAY.
- **429/403 stay OUT of the forcelist.** Canvas signals rate limiting with both, the app handles that with a CLAMPED `parse_retry_after` on the aiohttp path, and absorbing it here would hide the one signal that path watches for. Rate limiting on the metadata path is a separate question, left where it was rather than half-answered.
- **`raise_on_status=False`** so an exhausted retry still surfaces as canvasapi's own error with its existing message - every downstream handler unchanged.
- **`connect=0` AND `read=0` - STATUS retries only, and the connect half was a regression I reasoned myself into.** A retry of either kind only begins after a TIMEOUT has already elapsed (15s connect, 60s read), so it MULTIPLIES the wall clock on exactly the slow or unreachable link those timeouts exist for. Measured against a blackholed host at a 3s connect timeout: no-retry **3.01s**, `connect=2` **10.01s**. At the real 15s that is 15s -> ~50s before the user is told Canvas cannot be reached, **on the login path**, for zero benefit to a 502. *"Connect failures are cheap and transient"* is true of a REFUSED connection and false of a FILTERED one, and the filtered one is the case that hurts.
- **The second half is the silence.** A module that survives the retry is still dropped, so it now reports ONE summary line naming the count and the modules - mirroring the precedent the OUTER `get_modules` handler already set. Emitted from the **main thread**, because `progress_callback` drives Streamlit UI and the fan-out workers have no `ScriptRunContext`. One line, not one per module: the failure being guarded against is a 502 STORM.
- **Verified live, A/B, on the real app** (`20260822_201132_engine-regression-verify`): same course, same config, same folder state - `Module file tracked` 97 -> **97**, `Creating Link` 41 -> **41**, `Link SKIPPED` 36 -> **36**, download 300 files / 0 exceptions, sync *"everything up to date"*. Plus a fully clean unseeded run (1.3 GB, 300 files, 36 recordings, **0 ignored rows**).
- `tests/test_canvas_metadata_retry.py` (11) drives a real HTTP server through the real session - no Canvas, no network, no credentials, so it runs everywhere. `scripts/_mutate_canvas_metadata_retry.py` **10/11**, one documented equivalent (`status` caps status retries independently of `total`).

## A requests ADAPTER can never use `setdefault('timeout')` - the key is ALWAYS there (2026-08-23)
`_CanvasTimeoutAdapter` exists so `course.get_modules()` / `get_files()` cannot hang for ever; its own docstring says so. It did it with `kwargs.setdefault('timeout', ...)`, and that is a **no-op in an adapter**: `requests.Session.request` builds `send_kwargs = {"timeout": timeout, ...}` and passes it down EXPLICITLY, so by the time `send` runs the key is already present - with value **None** whenever the caller named no timeout, which is every canvasapi call. `setdefault` found a key and did nothing. **From 2026-05-21 to 2026-08-23 this class injected NOTHING.**
- **MEASURED on Windows** (requests 2.32.3, urllib3 2.5.0), against a socket that ACCEPTS and then sends no byte: **hung past 150s with a 60s read timeout configured**, and past 75s on a repeat. Dumping the real kwargs reaching `HTTPAdapter.send` shows `{'cert': None, 'proxies': OrderedDict(), 'stream': False, 'timeout': None, 'verify': True}` - the key is there, so `setdefault` can never fire.
- **`if 'timeout' not in kwargs` is the SAME no-op wearing different clothes** and is the obvious "fix" to reach for. The test is `kwargs.get('timeout') is None`: requests' explicit None means *the caller named no timeout*, which is exactly when ours applies. An explicit caller timeout is still honoured untouched, and a mutant that overrides it is caught.
- **What it could actually do to a user.** The adapter is on the SYNCHRONOUS metadata path only - login, the course list, and the scan feeding every analysis. Downloads were never affected (aiohttp, `sock_read=60`) and neither was Panopto (own session, explicit timeouts). The reachable failure is a **half-open socket**: wifi roaming, sleep/wake, a dropped VPN. The handshake completed, so nothing is refused; urllib3 sets `TCP_NODELAY` and not `SO_KEEPALIVE`, so `recv()` waits for ever. And these calls **hold the Streamlit script thread**, so the window freezes and **Cancel cannot help** - cancellation is polled between operations and the thread is parked inside a socket read. The daily auto-sync is the worst case because nobody is watching it. NOT observed in the field: the mechanism is measured, the reachability is reasoned.
- **A connect timeout was never in effect either.** A blackholed IP failed in **21.0s** - Windows' own TCP SYN schedule, not our 15s. So the retry section above costed `connect=0` as "15s -> ~50s on the login path" against a number that did not exist. The reasoning was right; the constant only became real with this fix.
- **Turning a timeout ON can regress the other way, so that was measured too.** A 2s read timeout against a server dripping for ~4s **succeeds** - requests' read timeout bounds the gap BETWEEN bytes, exactly like aiohttp's `sock_read`, not the total duration. So a large paginated reply is unaffected however long it takes, and "Canvas is slow today" cannot start failing. `test_a_slow_but_PROGRESSING_response_is_not_cut_off` pins it.
- **`CANVAS_TIMEOUT` is read inside `send`, i.e. on EVERY request**, so `int(os.environ.get(...))` on a malformed value raised ValueError out of the adapter and broke every Canvas API call in the app with the env var as the only clue. `_read_timeout_seconds()` degrades a bad or non-positive value to the default.
- **VERIFIED LIVE against real Canvas** (real token, real account): `validate_token` 0.23s, 32 courses in 1.00s, and the transport confirmed receiving `(15, 60)` on the real request - then end to end in the PACKAGED app: login, 14 courses, a 12-course sync analysis reporting *"Checked 352 files across 11 courses"*, **0 exceptions**, `failures: {}` in the health record.
- `tests/test_canvas_request_timeout.py` (17). **Every behavioural test runs the call on a THREAD with a join timeout** - this repo's existing rule for the ffmpeg watchdog, and it matters doubly here: without it a regression hangs the suite AND burns the whole per-mutant timeout during a mutation pass. `scripts/_mutate_canvas_request_timeout.py` **10/10 caught**, including the original `setdefault` verbatim.

## A re-download REWROTE the edit-protection baseline - one bookkeeping line (2026-08-20)
`original_md5` means **what we downloaded**. It is the sole basis of the app's
headline promise: `_classify_local_modification` compares the file on disk
against it to answer `clean` (safe to overwrite) or `modified` (preserve as
`_NewVersion`). `record_downloaded_file` rewrote it from whatever was on disk.

- **Found while measuring something else.** The iCloud pass asked "does a
  re-download materialise an evicted folder?" - it did, 19 of 19 - and chasing
  the cause landed on a line whose *other* effect is data loss. The materialise
  question was the symptom; this is the disease.
- **`record_downloaded_file` runs after EVERY file of a download, including the
  ones that were SKIPPED because they already existed** (`core/canvas_logic.py`,
  *"Sync Run #0: Record skipped-but-existing files to the DB"*), and that call
  site passes no md5. The function then hashed the file on disk and stored it -
  so a re-download replaced the baseline with the file's CURRENT content.
  Measured, driving the real class:

      first download        baseline = md5(original bytes)
      student edits it      classification -> 'modified'   (protected)
      re-download course    baseline = md5(THE EDIT)
                            classification -> 'clean'      (NOT protected)

  `clean` is the verdict that lets the next sync overwrite the file, and
  `_NewVersion` cannot fire because it reads this row.
- **The edit must preserve the file's SIZE**, because a size change is what
  sends the download down the overwrite branch instead of the skip branch. That
  makes it narrow - and silent, and aimed at the one thing the product promises
  about the user's own work.
- **The same line was the certain iCloud cost**: hashing READS the file, and
  reading an evicted file materialises it. Re-running a download over a folder
  macOS had evicted pulled the whole course back - **19 of 19** untouched files,
  against **0 of 22** for the sync path, measured on a real account.
- **`clear_ignored` already was the fresh-vs-skip discriminator** and its
  docstring already said so, so the fix needed no new state: a caller with no
  md5 is either recording bytes it just WROTE (`clear_ignored=True` - secondary
  HTML/URL renders, where the file is ours and hashing is right) or re-recording
  a skip-existing file (where it is NOT ours). The stored baseline is preferred
  whenever one exists; hashing stays the fallback for a row that has none, which
  keeps the original promise that a baseline is never silently dropped.
- **Verified end to end on the real folder**: after the fix a real download over
  a fully evicted iCloud course materialised **0** files. The one that changed
  blocks was the `.webloc`, which `_create_link` REWRITES every run - our own
  write resetting its blocks, not a fetch (confirmed by its mtime).
- `tests/test_download_baseline_preservation.py` (8) and
  `scripts/_mutate_download_baseline.py` - **4/4 caught, plus one documented
  EQUIVALENT** mutant (trusting an empty stored baseline changes nothing,
  because the fallback hashes on any falsy md5; the `and _prev[0]` guard is
  belt-and-braces). The mutation pass is what exposed a genuine gap in my own
  tests first - a row that is MISSING and a row that EXISTS WITH AN EMPTY md5
  reach different branches, and only the second distinguishes them.

### Download phases: ONE Canvas file, ONE fetch - and the ORDER is what guarantees it
- **`sync_manifest.canvas_file_id` is the PRIMARY KEY**, so the model is one Canvas file → one local file. Two copies can never both be tracked; the second write repoints the row and orphans the first.
- **Canvas Content must run before EVERY Files-tab sweep, and there are THREE of them.** A file reaches the engine once per phase that references it, each computing its own destination, and whichever runs first cannot know about the other. With a sweep first, one file was fetched **twice, 21 seconds apart** and landed as two copies (measured, course 46396, ids 1784620/1807289). The sweeps are the modules-mode **Catch-All**, the **flat** loop and the **folder-structure** loop; all three ask `_defer_to_canvas_content()` *before* reserving a filename, so a deferred file leaves its name free.
- **`_download_secondary_content` is a SIBLING of the mode dispatch, not part of the modules branch** - the single most missable fact here, and the reason the first version of the fix covered only modules mode. `_canvas_content_phase()` is therefore one closure with two call sites: ahead of the primary loop in flat/files (where the primary loop *is* the sweep), and between the module walk and the Catch-All in modules mode (the walk is what fills `module_handled_ids`; flat/files never do, so going first costs nothing). `tests/test_duplicate_download_claim.py` asserts both call sites and that there are exactly two, because every other guard in that file still passes with the calls moved.
- **`_file_registry` maps `real Canvas file id → (manifest row id, path)`**, per course, written by `_download_file_async` on every successful placement. **The row half is load-bearing, not bookkeeping** - it is what decides move vs copy, and reading the id's sign instead would move an isolate-mode attachment out of its own folder the moment the sweep asked for the same file.
- **`real_canvas_file_id()` is the identity rule: only the `attachment` synthetic band re-keys a real Canvas FILE id.** Every other band (assignment, quiz, discussion, …) holds an ENTITY id from a different namespace, so a quiz id of 1784620 must never match the file of the same number. `secondary_raw_id()` is the inverse of `make_secondary_id()`.
- **Which copy wins is answered by the manifest, and it differs by layout** - do not "unify" the two branches:
  - **Flat** (`isolate_secondary_content=False`): the attachment keeps the file's true id, so both want the ONE row that id allows. The sweep defers entirely (`_row_already_placed`). One fetch, one file, one row.
  - **Isolate**: the attachment holds a synthetic row, so the analyzer legitimately expects BOTH a Files-tab entry and an attachment entry, each with its own row and file. Deferring would leave the Files-tab row pointing at nothing and the next sync would re-download it to the root for ever. The sweep proceeds and `_claim_placed_copy` serves it from the local copy - two files as designed, one fetch.
- **Serving the second request from the first copy is NOT sufficient on its own** - that was built first and is why the reorder exists. It fixes run 1 only: on run 2 the sweep finds nothing at the root (run 1 moved it), fetches it again, and the attachment's destination now already exists, so the exists-check returns before any claim can run. The orphan comes back and every run re-fetches. Verified after the reorder: a repeat run made **zero HTTP requests**.
- Every failure path in `_claim_placed_copy` (missing source, another course's file, locked destination) returns `None` and falls through to an ordinary download, so it can never make an outcome worse than not having tried.
- **A placed file is a real write with no `File Saved:` line.** It emits `progress_type='skipped'` - the item is counted and reaches the run ledger (which is what scopes post-processing), while its size leaves the MB denominator because no bytes crossed the network. The audit checker was taught the same thing (`file_placed`, `catchall_defer`); leaving it out of `_count_coherence` would be slack in exactly the direction that hides a missing file.

### A converted file's `_NewVersion` must guard the OUTPUT, not the download
- `sync/execution.py` downloads the fresh SOURCE and lets the converter overwrite the product "in place" - so `_NewVersion`, which protects the *download target*, was guarding a file nobody edited. A student's edited `hints.md` / `Create_ILearn_tables_sql.txt` was regenerated straight over. It fails in both directions: `convert_html` KEEPS its source (so the fork happened, on the wrong file), `convert_code` CONSUMES it (so no fork happened at all).
- **The verdict is passed at the one point that knows both facts.** `sync_mgr.protect_conversion_target(path)` marks the edited output from the analyzer's own `is_update_modified` verdict; `converters/post_processing.py:_resolve_conversion_target()` - the single destination resolver every converter shares - diverts to `<stem>_NewVersion<ext>`.
- **The run-scoped mark is primary and the recorded product md5 is only a backstop.** The first version relied on the hash alone; every unit test passed, but folders created before this version have no such record, so **real users would have got no protection at all**. The seeded verification run caught it.
- The md5 has to be stored *with* the product path (`_record_conversion_product`) because by the time post-processing runs, the manifest row has been repointed at the freshly downloaded source and no longer describes the product.
- **`convert_code` must be passed an explicit `dst=`** - it computed its own `<stem>_<ext>.txt` and so bypassed the shared resolver entirely. Its `default_name` is a stem rewrite, not a suffix swap.
- Quick Sync is unaffected: it declines locally-edited files outright and says so.

### THE LIBRARY: one store for saved pairs, groups, and daily membership (2026-08-04)
A course linked to a folder used to live as up to THREE drifting copies keyed on a fragile PATH - the hub (`saved_sync_groups.json`), the active sync list (`canvas_sync_pairs.json`), and the daily set (`today_dashboard.json`) - which is why moving a folder lost its name, re-downloading resurrected a deleted one, and even the developer couldn't hold the model. That is now unified in **`core/library.py`**.
- **One first-class SAVED pair per `(course_id, folder)` link, with a STABLE id** (`pair_<uuid>`). The pair record is `{id, course_id, course_name, local_folder, name, standalone, in_daily_sync, created_at, updated_at}`. **The name lives on the id**, so `relink_pair` (a moved folder) carries the name with it, and `delete_pair` frees the id so re-adding the same path is a NEW pair with no name - both headline bugs fixed at the source, no `retarget` hack needed.
- **`name` replaces the `group_name`/`auto_named` warts**: `""` means "use the live Canvas name". **`standalone`** = the user saved it on its own (a hub "Pair" card); a pair that exists only because a GROUP references it is `standalone=False` (still named/daily-able, just not its own card). `standalone` is only ever raised, never lowered.
- **Groups reference pairs by id** (`{id, name, member_ids}`); a group names the SET and can never touch a member's name (the old `_project_pair` clobber trap is gone). `delete_group` keeps standalone members and GCs exclusive ones (including out of daily).
- **Today is a CHILD of the library, not a copy**: the daily set is `pairs where in_daily_sync` - a query, not a file. So `reconcile_daily_list_with_hub()` is now a **no-op**, `today_store` keeps only settings (`auto_sync_enabled`/`last_auto_sync_date`/`fda_nudge_dismissed`), and a hub re-link/delete reflects in daily instantly.
- **The mental model (from the user)**: the **sync list** is the working cart (raw, unsaved pairs allowed - forgotten on remove); the **hub/library** is where you SAVE pairs you care about, and saving is what lets you NAME them (naming stays a hub action); **Today** draws only from saved pairs.
- **Migration + adapters** (`core/library_migrate.py`, hooked in `app.py` init): idempotent (guarded by `sync_library.json` version), reversible (legacy files copied to `*.bak`). During the transition `SavedGroupsManager` and `today_store` are thin FACADES over the library (kept so the hub UI is unchanged); `pair_labels` reads `library.name_index()` directly. Validated in the real app: boots, migrates real data, hub renders all pairs+groups with names, Add-to-Sync-List resolves the name.
- **The three sections below describe the SUPERSEDED path** (labels resolved from the hub file, the daily-list copy + reconcile). The RULES they state still hold - a label belongs to the `(course_id, local_folder)` link; Today is a lens on history; Today's `sync_pairs` is a curated subset the engine must not overwrite - but the STORAGE is now `core/library.py`. Read this section first.

### A course has TWO names, and the user's one belongs to the LINK
- **The Canvas name is IDENTITY; the user's name is a LABEL, resolved at render and stored nowhere else** (`core/pair_labels.py`). Before this, the user could write a name - "Save as Pair" asks for one - but it was trapped in the hub: `Add to Sync List` copies `{local_folder, course_id, course_name}` and drops `group_name` on the floor, so the one place they had said what they call a course was the one place it was never shown.
- **A label belongs to the LINK `(course_id, local_folder)`**, the tuple every dedupe, update, remove and reconcile in the app already keys on. `pair_display(pair) -> (label, canvas_name)` and `pair_display_name(pair)` are the ONE call every surface makes; no label is copied anywhere, so there is nothing to reconcile and nothing that can go stale.
- **Stored in `saved_sync_groups.json`, in two places, and there is no new file.** A standalone saved pair uses its own name - which lives in a field called **`group_name`**, because `SavedGroupsManager` stores a saved PAIR as a group record holding one pair with `is_single_pair: True`. That field name is a wart; read it through `saved_record_label()` so nothing outside the manager has to say "group" when it means a pair. A course inside a multi-course group carries an optional **`label`** on its pair entry - a group's name names the SET and can never name one of its courses, and without this, importing a 5-course group gives five rows that cannot be named at all.
- **Precedence is DECIDED, not discovered**: standalone saved pair first (its whole purpose is naming that one link), then group members, first-in-file-order within each pass. Nothing upstream enforces uniqueness - the hub's Edit Pair can retarget a pair onto another's link - so this order is what makes the answer stable instead of dependent on file order. `build_label_index` is two passes *because* the passes are the rule.
- **THE TRAP: `SavedGroupsManager` rebuilds pair dicts from a fixed key list on EVERY write.** `save_group` and `update_group` both project through `_project_pair`, which used to hard-code three keys - so renaming a group, adding a course, or re-linking one folder would have **erased every member label in that group**, with nothing raised and no symptom except names quietly reverting. Add a key that must persist and it goes in `_project_pair` or it does not persist.
- **`auto_named` means "the user did not choose a name".** The Save as Pair dialog pre-fills the course name as a *placeholder* so saving is one click; accepting it records the text (the hub still has to call it something) plus this flag, and `pair_labels` then ignores it - every screen goes on showing the LIVE Canvas name, so a Canvas-side rename still reaches the user instead of freezing on the day they clicked Save. Renaming always clears the flag: a stored-but-ignored name is indistinguishable from a rename that silently failed. Groups keep a REQUIRED name - a set of courses has nothing honest to pre-fill.
- **The index memoises on the groups file's `(mtime_ns, size)`.** Correct by construction: every write goes through `_save_all`'s `os.replace`, which moves the mtime. The alternative - an explicit invalidate at each of the hub's seven mutation sites - is one forgotten call away from a rename that never appears.
- **A label must never be COPIED, and the hub hands its own pair dicts to the sync list.** "Add to Sync List" for a group, and rescue mode, pass the hub's dicts straight through - and a group member's dict carries `label`, so it was being written into `canvas_sync_pairs.json` as a second, silently-stale copy. Inert (nothing reads it) and therefore exactly the kind of thing someone starts reading later. `sync/persistence._strip_label` drops it at the three mutators rather than at the call sites, so a future caller cannot forget; `today_store._norm_pair` already does the same duty for the daily list.
- **What must NEVER see a label**, each for a different reason: `.canvas_sync.db`'s `course_name` (it is the folder's BOUND identity, read by `peek_bound_course_name` for auto-detect and the "linked to a different course" notice); the `=== Sync Execution: <course> | Mode:` debug line (`tests/audit/harness/oracles/log.py` parses it to attribute every event - a nickname there unhooks the audit harness *silently*, because the regex still matches, hence the separate `_log_name`); history's stored `course_names` (`shared/components._course_id_from_sync_pairs` matches error rows against it); the course PICKER; and Today's stored pairs, whose `_norm_pair` strips unknown keys and must keep doing so.
- **Sync history resolves RETROACTIVELY**, matching the Today page's membership decision - rename a course and its past runs relabel; delete the pair and they revert. `history_course_display_names()` is ONE function used by the filter dropdown, the filter and the card header (writing it three times is how a card ends up showing a name its own dropdown cannot select). Three sources, best first: `synced_groups` (carries the link), the new `course_sigs` field, then a canvas-name→label index for entries written before this existed.
- **`md_escape()` is the opposite of `esc()`.** `esc` protects HTML; `md_escape` protects Markdown, and a widget LABEL is Markdown - `st.button("1. Semester")` is an ordered-list item and Streamlit eats the `1.` (the same trap the step tracker hit). Real course nicknames trip this constantly. Verified in the running app: `Macro *lectures* 1. term` survives literally.
- **Two rendering traps found while building this, both in the real app, neither visible in review:**
  - **An optional interpolation on its own line inside an indented triple-quoted HTML string.** When it is empty the markup contains a **blank line**, which terminates the HTML block, and Markdown reads the 8-space-indented lines after it as a **CODE BLOCK** - the hub pair card printed its own folder `<div>` as literal source. It fails only in the branch where the optional part is ABSENT, i.e. the branch that looks safe. Build such markup as ONE concatenated line.
  - **Streamlit's markdown sanitiser STRIPS `title` from a span**, so "it truncates but you can hover" is not an available fallback (`.shist-pill` in sync history has carried a dead `title` for as long as it has existed). The sync card's course chip is therefore held at full width by CSS (`flex: 0 0 auto`) and only the folder chip shrinks - measured, letting both shrink rendered `Makroøkonomi…` for a user who has a Makroøkonomi **(XB)** *and* a **(LA)** on that very list.
- The named card renders title + a `.sp-pill` row (course chip + folder chip, `flex-wrap: nowrap`, squarer than Today's `.tcs-pill` so it does not read as a button); an unnamed card renders **exactly** as it did before. Both variants emit the same THREE children so neither can inherit the other's leftovers. The row carries `overflow: hidden` as a backstop: below a ~250px card the folder chip's min-width floor stops it shrinking and the row spills OUT of the card (measured 15px over at 200px, 27px at 160px). Streamlit stacks these columns long before that - at a 560px viewport the card is 488px - so it is unreachable until someone re-weights `st.columns([5, 1.5, 1.1, 1.5, 1.2])`.
- **History display names are deliberately NOT deduped.** The count drives the header ("N courses" vs one name), and two entries can legitimately share a display name - the same course synced into two folders is two pairs, and nothing stops a user naming two pairs alike. Collapsing them reports a 2-course run as a 1-course run.
- Covered by `tests/test_pair_labels.py` (21 tests; all **16** mutations of the real code caught). Two of those mutations exposed defects in the tests themselves - an anchor gone stale on CRLF, and a later stripped write masking an earlier leaky one - so re-run the mutation pass, not just the suite, after touching this.

### Today page ↔ Sync page: ONE record, TWO lenses
- **`canvas_sync_history.json` is the complete record of every sync, in both modes.** The Sync page's Sync History shows it whole and unfiltered. The Today page is a *lens* onto that same record, never a second record - nothing is written for Today's benefit, and Today never hides anything from history.
- **The lens is two filters, on two independent axes** (`ui/today_dashboard.py:_todays_groups`):
  1. **Course** - only pairs in the curated daily-sync set, read via **`core.auto_sync.resolve_today_pairs()`**. That set is the entire page's scope: the auto-sync toggle, "Quick Sync now", the "Courses in your daily sync" card and this file list all read that ONE function. Because it filters *display* and not *recording*, adding a course reveals what already landed in it earlier today and removing it hides those files again - the user can curate what "today" means after the fact.
     - **Read `resolve_today_pairs()`, never `load_today_config()["pairs"]` raw.** The difference is pairs whose folder no longer exists on disk, which the card hides. Reading the raw list here shipped a screen with a 40-file course card sitting directly under a panel that said "No courses in your daily sync yet" - the exact contradiction the course filter exists to prevent. Any new consumer of "is this course in the daily sync" goes through the same function; that rule being written twice is what let the two drift.
     - **A missing folder SKIPS that course - it never pauses the daily sync.** `resolve_today_pairs()` drops it, the rest of the list syncs normally, and `build_today_sync_notice()["skipped"]` reports it afterwards (the run otherwise just quietly covers fewer courses than the list claims). The course stays listed in amber (`today_chip_missing_` / `today_pair_card_missing_`, matching global.css's `sync_pair_card_missing_`), and "Today's files" shows no state of its own for it. Do **not** add a "sync paused" screen - a broken pair is one course's setup problem, not an outage.
     - **The hub is the source of truth for what a saved pair IS; `reconcile_daily_list_with_hub()` keeps the daily copies in line.** Delete a pair in Saved Groups & Pairs → it leaves the daily list too. Re-link its folder with Edit Pair → the daily copy adopts the new folder, so the same pair is never repaired twice. Runs from the hub callbacks AND on every Today render, because a list that predates this could hold courses the hub no longer has - **orphans are unfixable by definition**, since every instruction the UI can give points at a saved pair that isn't there. After reconciliation an amber course is always one the hub really has, which is what makes "fix it in Saved Groups & Pairs" a followable instruction. A hub read failure returns 0 and writes nothing - never mistake it for "the user deleted everything".
     - **Membership is RETROACTIVE and stateless - decided 2026-07-26, do not re-litigate.** The only question asked is "is this course on the list *right now*", so adding a course reveals files that arrived earlier the same day and removing it hides them again. The alternative (store `added_at` per pair, show only later arrivals) was rejected: it makes a freshly-added course with files already on disk render as an empty card with no explanation, it loses the day on an accidental remove + re-add, and it makes the off-list footnote's "add the course above and its files appear here" a lie.
  2. **Category** - only `new` / `updated` / `protected` (`_TODAY_ARRIVAL_CATEGORIES`): things Canvas gave you. Never `restored`, which is a file *you* deleted locally and asked back - curation, not an arrival.
- **Sync MODE is not a filter and must not become one again.** Both filters above used to be a single `sync_mode == 'quick'` check, which failed in both directions: with no course filter, an empty daily list still listed 43 files from Sync-page quick syncs (the reported bug); and as a stand-in for the category rule it discarded every genuinely new file a review sync brought into a daily course. A file downloaded through "Analyze, Review & Sync" arrived today just as much as one from Quick Sync.
- **The page must SAY what it is hiding.** `_todays_groups` returns `(groups, off_list)`; `off_list` counts today's arrivals in non-daily courses and renders as the `.today-files-offlist` footnote. Without it the scoping rule is invisible and the page just looks like it lost files. It is a count of real state, so it is **not** gated behind Settings → Show help text. Its dismiss button stores the **tally** (`today_offlist_dismissed`), not a bare flag - dismissing at 10am must not silence the line after three more off-list courses sync at 2pm, which would put the page straight back to under-reporting.
- **`_TODAY_HELP_TEXT` states this whole contract in user language** ("What counts as one of today's files" + a Common-questions FAQ) and is the only place a user can read it. Two of its sections were left factually wrong by an earlier pass here - if you change any rule above, change that copy in the same commit.
- Folder identity is normalised on both sides (`_norm_folder`): the daily set stores the string the user saved, history stores `str(sync_manager.local_path)`. Match is on the **pair** (course + folder) - the same course synced into a *different* folder is a different pair and belongs to the off-list tally, because the card's "Open Folder" button points at the daily folder.
- Covered by `tests/test_auto_sync.py` (add → appears, remove → disappears, both modes merge and dedupe, restored excluded, path-form and other-folder cases).

### Today's `sync_pairs` is a CURATED SUBSET the engine must not overwrite
- **`st.session_state['sync_pairs']` is the pair list of the RUN, and only on the Sync page is it also the contents of `canvas_sync_pairs.json`.** `core.auto_sync.start_today_sync` publishes it from `today_dashboard.json` and never writes it to the pairs file - by design, since the daily list is self-contained and survives hub edits. Anything in the engine that treats the two as interchangeable is wrong for Today.
- **`sync/persistence.py` has five mutators and only ONE is called by the engine.** The four Sync-page CRUD functions may end `st.session_state['sync_pairs'] = atomic_update_sync_pairs(modifier)` because there session == disk by construction. `update_last_synced_batch` is called from `sync/execution.py` at the end of *every* run, including Today's, and that assignment **replaced the running sync's own pair list with whatever the Sync page had saved**. For a user who only ever used Saved Groups & Pairs that file is `[]`. Measured 2026-07-31 against the real frozen build's config dir: 4 pairs → **0**. It now stamps the session list *in place*, with the same callable, so persisted and in-memory timestamps cannot drift.
- **`render_sync_step4`'s empty-pairs notice is what made it unrecoverable, and that is the more important half.** The `st.stop()` sat above the terminal-state routing, so a run that lost its pairs *while in flight* could never reach the handler that writes the Today notice and calls `cleanup_sync_state()` - nothing could clear the state causing the notice, so every rerun landed back on it. The user's 203 files had all downloaded successfully and `download_status` was `sync_complete` (confirmed in `diagnostics/session_state.json`), yet the screen said "No course folders found" and stayed there for ten minutes.
- **The guard is now scoped to the phases that actually READ the list** (`_STATUSES_NOT_NEEDING_PAIRS`), which is analysis and nothing else - everything from `analyzed` onward works off `sync_analysis_results` / `sync_selections`. **A terminal status must never be blocked by a precondition**: it is the only thing that can clean up after the state that failed the precondition. `tests/test_today_sync_completion_reachable.py` guards both directions and AST-checks that no later phase has started reading `sync_pairs` behind the exemption.
