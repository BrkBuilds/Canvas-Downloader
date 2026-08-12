# The macOS 26.6 (Tahoe) audit — session record and state of the app

**Tracked in git on purpose.** Assistant memory does not survive a machine
being reimaged and does not travel between the operator's three checkouts, so
anything durable about this audit lives here, in `CLAUDE.md`, or in
`AUDIT_FINDINGS.md`. This file began as the Office-conversion handoff and now
carries the whole Tahoe session; the Office detail is unchanged below.

---

## STATE OF THE APP — 2026-08-12, end of the Tahoe session

**Launch-ready for macOS, with one written-down untested area (iCloud).**

| | |
|---|---|
| branch | `macos-audit-26`, 55 commits, pushed |
| test suite | **3680 passed, 26 skipped** (run on this Mac) |
| architecture audit | **0 violations** (Rules 4–10) |
| artifact | `dist/Canvas_Downloader_v2.0.2_macOS.dmg`, 105 MB, arm64 |
| signature | `codesign --verify --deep --strict` rc=0, `apple-events` entitlement intact |
| packaged app | boots, health 200, renders the course list, **0 exceptions / 0 console errors** |
| version | `version.py` = 2.0.2, leads every shipped tag |

The DMG was built with CI's own recipe (`npx create-dmg`, drag-to-Applications)
and verified by MOUNTING it and checking the app inside — signature,
entitlement, architecture, and the presence of every fix from this session by
its distinctive strings.

### What was PROVEN on real hardware this session

* **Office → PDF, all three apps, both starting states.** Cold: 12/12 convert,
  all three quit, Recents 0. Busy (the user editing a dirty document in each):
  12/12 convert, **3/3 user documents survive**, all three left running.
  Repeated through the REAL app on course 43660 with PDFs deleted first to
  force genuine conversions: cold 8/8, busy 6/6, zero failures either way.
* **Crash recovery.** PowerPoint killed mid-batch → **6/6 files still convert**,
  with and without CPU+memory pressure. Under the old code this is exactly
  where 57 files were abandoned.
* **Volumes.** Case-sensitive and case-insensitive APFS images (`hdiutil`), NFC
  and NFD names, and a real READ-ONLY mount — the manifest survives untouched
  with an honest error, no corrupt-backup, no deletion.
* **Sync matrix** 43/43 and **download matrix** 56/56, 0 failed.

### Known gaps — stated, not hidden

1. **iCloud Drive eviction is UNTESTED.** No iCloud account on the audit box.
   Nothing in the app is aware of dataless files. Reasoning (not measurement)
   says the likely effect is a slow or failing read rather than a missing file.
   `brctl evict` makes it testable in ~30 minutes on a Mac with an account.
2. **D4's crash artefact cannot be read** — Microsoft routes its own crashes to
   MER, which uploads and discards, so `~/Library/Logs/DiagnosticReports` is
   empty. The root cause was established by reproduction instead (see D4).
3. **No fresh 56-row matrix against the final code.** Verification is targeted
   controls plus real-app runs, not another full sweep.
4. **Intel Macs are not supported** — arm64-only, stated in the README. A
   documented product decision, not an oversight.

### What still needs a Mac, and what does not

* **Does NOT need a Mac**: copy changes, CSS changes, Python changes, the test
  suite, the architecture audit. All cross-platform.
* **Does NOT need a Mac**: building the release DMG — `.github/workflows/
  build-macos.yml` does it on a `macos-14` (arm64) runner via
  `workflow_dispatch`, using the same `create-dmg` recipe verified here.
* **DOES need a Mac**: verifying anything platform-specific — Office
  automation, TCC prompts, Keychain, WKWebView rendering, the packaged
  bundle's behaviour, and iCloud.
* **The one residual risk in giving up the Mac**: macOS renders in **WKWebView**,
  not Chromium, and this repo already ships a WebKit compatibility patch for
  Streamlit. A CSS change verified only in Chrome is *probably* fine when it
  copies a pattern already proven elsewhere in this app — but it is not
  verified. Re-renting for an hour is the remedy if a rendering report comes in.

---

## D11 — a CANCELLED run left all three apps open, with temp files in Recents

**Found by the operator's own "chill test": two courses, all conversions plus
Panopto, cancelled during PowerPoint conversion.** All three apps still
running, Recents full of our staged `src_*` files. Process times settled who
launched them (app 02:03:50, PowerPoint 02:05:16), so the gate should have
taken them.

**No scenario in this session exercised CANCEL** — that is the gap the operator
closed, and it is worth remembering that the cancel path reaches the same
teardown but leaves the apps in a different state.

Two causes:

1. **Our OWN staged document blocked the quit.** It has a real path on disk, so
   the "is this the user's?" test called it user-owned and kept the app alive
   for ever. A path carrying the `CanvasDownloaderTmp` marker is ours by
   construction, whoever launched the app, and can never be a blocker now.
2. **A regression from earlier the same day.** `full name` had been loosened
   from `contains "/"` to "any non-empty name" to fix Word's HFS colon path.
   Too loose: an UNSAVED document's full name is just its NAME. Measured —

       Book1 || path=[] || full name=[Book1] || saved=true

   so Excel's own auto-created blank read as user-owned. That is precisely the
   *"a single pristine blank keeps Excel in the dock forever"* failure the
   function was originally written to fix. The test is now for a path
   SEPARATOR, and needs BOTH: `/` for Excel and PowerPoint, which report
   POSIX, and `:` for Word, which reports HFS.

Verified against the operator's actually-stuck apps — the app's own quit script
took Excel immediately after the fix — then both scenarios re-run end to end:
busy 8/8 converted with 3/3 user documents surviving and all three left
running; cold 8/8 converted, all three quit, **Recents 40 → 0**.

**The lesson for the next session**: a fix that loosens a predicate to make one
app work can break a different app in the opposite direction. Word needed the
colon; Excel needed the separator requirement kept. Both apps had to be driven
to see it.

---

## WHAT THIS SESSION DID — 55 commits

Grouped by what a reader would look for. Every entry was measured on this
machine; the commit named in each carries its evidence.

### Product fixes — macOS, data loss (all HIGH)

| fix | commit | what it destroyed |
|---|---|---|
| `active document` is whoever is FRONTMOST | `066b6da` | a failed conversion closed the USER'S open document `saving no` (1 → 0, reproduced) |
| the teardown quit Word | `70ce78c` | quit an app the user was editing in and discarded the document; Excel and PowerPoint did not, which is why it needed all three to surface |
| …and its follow-on | `a934cec` | the "who launched it" observation was taken AFTER priming had launched everything, so the gate protected nothing — caught only by the real app |
| a failed conversion's stub was promoted | `f2692dd` | an 870-byte "PDF" orphaned in the course folder AND the good PDF from a previous run destroyed |
| two instances, one PowerPoint | `9854a8d` | 0/16 files converted and PowerPoint crashed — the root cause of the operator's original report |
| an EMPTY case-sensitive volume | `e64e800` | answered "case-insensitive", merging two distinct files onto one manifest row |

### Product fixes — macOS, correctness and UX

| fix | commit | |
|---|---|---|
| a CRASHED app read as "not installed" | `2c11a0e` | abandoned **57 files** mid-phase; now retried once, still bounded by the wedge threshold |
| the Recents purge never removed an entry | `745d99b`, `3360b80` | deleted values, not nodes: 495 rows / **0 entries**. Now node-based, triple-gated, per-app |
| the cold-launch WHITE flash | `255080d` | the WKWebView painted it, not the window |
| a notification DENIAL | `588bead` | is the user's decision, not a delivery failure to route around |
| the case probe flipped the directory | `91c7c58` | which lives on its PARENT volume |

### Checker / harness defects — four of the eight issues triaged were the CHECKER

`479cd29`, `bd03305`, `6bad460`, `aade2c0`, `13c70c7` — the archive-conversion
rule the repo had deliberately reversed and the checker kept re-filing; `matrix
lanes` counting a previous matrix's rows (23/37 reported against a true 2/37);
`REC_COST_MB` encoding the CUDA figure so transcription was under-priced 3.4x
and always wrong on macOS; the over-cap check demanding a row the app
deliberately stopped writing; four name-matching defects; `mac_eyes` crying
wolf on Tahoe's titled phantom alert.

### Tests and tooling

Seven new test files, every one mutation-verified: **15/15, 10/10, 9/9, 8/9,
4/4, 9/10, 6/6** (two documented equivalent mutants). New instruments kept for
the next session: `verify_office_document_guard.py`,
`verify_office_crash_recovery.py`, `verify_office_end_to_end.py`,
`probe_office_document_binding.py`, `probe_office_open_latency.py`,
`measure_office_window.py`, `measure_launch_flash.py`.

### The methodological lesson worth carrying forward

**Every harness in this repo passed the priming-order defect.** They drive the
converters directly and never call `prime_office_automation`, so they
structurally could not see that our own priming launches the apps before the
"was it already running?" question is asked. Only the real app caught it. That
is the strongest evidence this session produced for the rule the repo already
states: *verify in the REAL app, not a mock.*

---

# The macOS Office-conversion defect set — SHIPPED 2026-08-11/12

**All measurements on the Tahoe (macOS 26.6) audit box, against the real
applications.** Read `MAC_RUNBOOK.md` for the phase plan and `RUNBOOK.md` for
the oracle rules; this file is one subject only.

The trigger was an operator report: *"a powerpoint somehow crashed and I got an
error message… clicking the blue button caused ppt to come up flashing for every
ppt file converting, full screen, until the conversions ended"* — followed by a
screenshot of PowerPoint's Recents list full of `src` entries pointing into our
temp staging directory.

That one report, plus the download matrix that ran afterwards, produced **seven
product defects and four checker defects** — and the operator's own
hypothesis about two concurrent lanes is what led to the root cause, D4.

Three of the four product defects were a class this repo already documents,
surviving in a module the earlier fix did not reach — the playbook's thesis for
the fourth pass running. The fourth (D4) is new, and it is the one that
actually crashes PowerPoint.

---

## THE CAUSAL CHAIN — reproduced end to end, and it starts at D4

    D4  two app instances drive the ONE PowerPoint macOS gives a user session
      -> one instance's `open` lands between the other's `open` and `save`
      -> -609 / "success but no output" / a raced destination -> PowerPoint CRASHES
      -> the next Apple event returns -600 "Application isn't running"
      -> D6 that is misread as "not installed" -> 57 files abandoned
      -> Microsoft Error Reporting restarts PowerPoint VISIBLE
      -> D2 every subsequent conversion shows a full-screen window
      -> a live PowerPoint rewrites the shared Recents DB on exit
      -> D3's purge is undone -> 490 `src` entries in the operator's Recents

The chain was corroborated twice: `converters/pdf.py`'s own docstring predicted
the first hop, and while probing this the audit accidentally reproduced the MER
hop — a wedged Excel, killed, produced exactly the "click the blue button and
the app comes back visible" dialog the operator described.

D1 makes each failure worse (a failed conversion never closed OUR document, so
they accumulate), but the CRASH itself is D4 - two instances, one application.
That was established by reproducing it on demand; see D4 below.

**D2 and D3 are downstream, and fixing D4/D1/D5/D6 is what removes them.** See
"D2 / D3" for why neither gets a direct fix.

---

## D1 — all three converters could close the USER'S document `saving no`

**HIGH, data loss. Shipped in `066b6da`.**

`converters/{pdf,word,excel}.py` bound the document they were about to export
with a bare `active presentation` / `active document` / `active workbook` — the
FRONTMOST one — and the `on error` handler did `close active <doc> saving no`.

* a conversion that fails while the user has a document open **discards their
  unsaved edits**. The matrix logged eleven PowerPoint failures (`Parameter
  error. (-50)`) in one course;
* on the success path a slow `open`, or an app in crash-recovery with a
  recovered deck frontmost, exports THEIR document into our PDF and closes it.

### Reproduced and fixed, `scripts/verify_office_document_guard.py`

User document open **and dirty**, then a corrupt file fed to the real converter:

| | user documents | verdict |
|---|---|---|
| pre-fix | 1 → **0** | USER DOCUMENT WAS CLOSED — data loss |
| fixed | 1 → **1** | user document SURVIVED |

with the CONTROL converting a real PDF in both (1.2–1.9 s), so the guard did not
simply stop converting. **Excel demonstrated the live path while being
verified**: handed a corrupt file it opens nothing, leaving the user's workbook
frontmost, and the guard refused it with `-30001` exactly where the old code
closed it.

### Why a NAME comparison, and not a reference

Measured against the real applications
(`scripts/probe_office_document_binding.py`):

| form | Word | Excel | PowerPoint |
|---|---|---|---|
| `set d to (open POSIX file ...)` | -2753 | -2753 | -2753 |
| `first <klass> whose name is "src.x"` | ok | **NOT FOUND** | ok |
| `<klass> "src.x"` | – | – | **HUNG** |
| repeat over `<klass>s` comparing `name` | error | -50 | no result |
| repeat over `<klass>s` comparing `full name` | error | **HUNG** | **HUNG** |
| **`name of active <klass>`** | `src.docx` | `src.xlsx` | `src.pptx` |

Only the last row works in all three, and it is the only one that never
ENUMERATES — which matters, because two of the enumerating forms wedged the app
hard enough that MER offered to restart it, i.e. the enumeration would have
CAUSED the symptom it was meant to fix. `office_container_stage` already stages
as `src.<ext>` in a per-conversion uuid dir, so that name is one we own.

One definition (`our_document_test`), three uses. The tests COUNT the sites.
**15/15 mutations caught.**

---

## D5 — a failed conversion orphaned a stub AND destroyed a good PDF

**HIGH. Shipped in `f2692dd`.** Found by the matrix (O3 vs O4: content files on
disk with no manifest row) and confirmed by reading the staging exit:

    yield staged_src, staged_dst
    # Success path: relocate the produced PDF back to its real destination.
    if staged_dst.exists():
        if dst.exists(): dst.unlink()
        shutil.move(str(staged_dst), str(dst))

The comment says "success path". The CONDITION is only that a file exists.

* an **870-byte "PDF"** landed in course 43660 beside the `.pptx` it had failed
  to convert — tracked by nothing, so re-offered as NEW on every future sync;
* `dst.unlink()` runs FIRST, so a failed re-conversion **destroyed the good PDF
  a previous run had produced**. The folder went backwards.

The promotion is now gated on the same `converters.verify` pair every
source-deleting converter already applies afterwards, **at the promotion** — the
boundary all three cross. Asking in both places is not redundant: this decides
what the user's FOLDER gains, the converter's decides whether the ORIGINAL may
be deleted. The no-container path gates after the write, asymmetrically: a
reject that created a new file is removed, a reject that OVERWROTE something is
kept and reported (deleting it would turn a damaged file into a missing one, and
a manifest row may point there). **9/9 mutations caught.**

Same class as `converters/archive.py:_decline`, in the module that fix missed.

---

## D6 — a CRASHED Office app abandoned the rest of the phase

**HIGH. Shipped in `2c11a0e`.** Three log lines, three seconds apart:

    21:29:47  PowerPoint failed (other): ... Parameter error. (-50)
    21:29:50  PowerPoint failed (app_missing): ... Application isn't running. (-600)
    21:29:50  ... skipping remaining 57 PowerPoint file(s)

`-600` is `procNotFound` — "not running *right now*", exactly what a crash
leaves — and the next `tell application` relaunches the app. It was classified
`app_missing`, which is in `FATAL_CATEGORIES`, so **57 files were abandoned** and
the user was told an app they had just watched convert forty files "is not
installed".

`-600` now has its own `app_crashed` category: per-file, retried once after a
short pause, NOT fatal. An unrecoverable crash still ends the phase through
`SYSTEMIC_REPEAT_THRESHOLD` after three consecutive failures — the mechanism
that can actually tell "one bad deck" from "the app is gone". Genuine absence
(-10810, -10814) is untouched and still fatal.

**Office writes a TYPOGRAPHIC apostrophe**, so the pre-existing `"isn't
running"` test (straight quote) never matched and the classification rested on
the `-600` substring alone. Both forms are covered now. **10/10 mutations
caught** — three of them only after the first pass exposed the tests as weak.

---

## The REAL-APP verification (operator-requested)

Not a harness: the actual app, driven through the audit CLI, on course 43660
(the course that failed), with **"MY THESIS DRAFT.pptx" open and dirty in
PowerPoint for the whole run**, sampling PowerPoint once a second.

Six converted PDFs were deleted first so the app had to re-download their
`.pptx` sources and genuinely re-convert them.

| | result |
|---|---|
| the six PDFs | **all re-created**, 81 KB – 930 KB, real PDFs |
| their `.pptx` sources | correctly consumed, none left behind |
| the user's document | **still open, untouched** |
| PowerPoint windows VISIBLE | **0** of 353 samples |
| PowerPoint FRONTMOST | **0** |
| max documents open at once | **2** (theirs + ours) — no stacking |
| PowerPoint crashes | **0** |
| conversion failures / guard trips / declines | **0** |

And the teardown made the distinction the whole design rests on, by itself:

    [OfficeQuit] pass 1: Microsoft PowerPoint -> kept running (1 of 1 doc(s) look user-owned)
    [OfficeQuit] pass 1: Microsoft Word       -> quit sent (1 open doc(s), none user-owned)
    [OfficeQuit] pass 1: Microsoft Excel      -> quit sent (1 open doc(s), none user-owned)

PowerPoint was kept alive **because** it held the user's document; Word and
Excel, holding only ours, were quit.

---

## D9 — the teardown quit Word and DISCARDED THE USER'S DOCUMENT

**HIGH, data loss. Shipped in `70ce78c`.** Found by driving all three apps in
the "user is editing while a sync converts" state, which is the check the
operator asked for and the reason it surfaced:

    Word        docs 1 -> 0   THE USER'S DOCUMENT WAS CLOSED, app quit
    Excel       docs 1 -> 1   survived
    PowerPoint  docs 1 -> 1   survived

`_idle_quit_script` defaulted a failed property read to `hasPath=false` /
`isSaved=true` — which IS the definition of pristine — so an undescribable
document did not block the `quit saving no`. Its docstring claimed the
opposite.

And the documents ARE undescribable: before a conversion phase Word reports
`path=[Macintosh HD:…:MY WORD WORK.doc] saved=false`; after one, **name, path,
full name and saved ALL FAIL**, even inside a single `tell` block. Every app is
left holding one, and `_force_close_canvas_docs_sync` cannot close it because
it matches on those same properties.

Both defaults are wrong in one direction, so the fix stops asking the documents
and asks **who launched the app** — the rule the product owner chose. Verified:
cold 12/12 converted + all three quit + Recents 37 → 0; busy 12/12 converted +
**3/3 user documents survived** + all three left running.

**Then the real app found the follow-on defect the harness could not**:
`prime_office_automation` launches all three at run start, so the observation
had to move to the top of priming — otherwise every app is running by our own
hand and the gate calls them all the user's, leaving all three in the dock.
That is exactly why a harness pass is not a substitute for a real run.

## D10 — the Recents purge had never removed an entry

**Shipped in `745d99b` / `d9fc0ad`.** It selected
`HKEY_CURRENT_USER_values WHERE name='path'` and deleted only value rows:
measured on the real registry, **495 value rows removed, 0 nodes**, with every
entry still on screen and now stripped of its values. The list is driven by the
NODES, whose `name` is the `file://` URL; the database held 36 rows named
`path` in total.

Now matched on the node name and deleting node + values, behind three gates
(marker, leaf-only, `MruUserData` ancestor). **636 removed, 0 of the user's
1041 nodes touched, 0.04 s.** Per APP, so an open Word does not block cleaning
PowerPoint's and Excel's.

**It lands ~15 s after the last process dies**, on a daemon thread. Measuring
before that reports a working purge as broken — which cost one cycle here.

## D2 / D3 — NOT fixed directly, and that is the decision

**D3 (Recents pollution) and the "quit only what we launched" rule were already
shipped in `35b3de8` (June).** `_purge_recents_sqlite` / `_purge_canvas_recents`
do the double-gated MRU sweep, and `_idle_quit_script` refuses to quit an app
holding a user document. The 490 entries the operator saw are the **documented
resurrection mechanism**, stated in the code's own docstring: *"a still-alive app
keeps its Recent-files list in memory and rewrites the shared registry DB when it
eventually terminates, resurrecting the very entries the purge just deleted"* —
and MER had restarted PowerPoint. Fix the crash and the purge sticks. **Do not
reimplement this.** An earlier draft of this file described D3 as unbuilt; that
was wrong.

**D2 (a visible window after a crash-restart) gets no direct fix, deliberately.**
Hiding our own document's window requires locating it, and every locating form
is an enumeration — two of which were *measured to wedge the app*, which is the
very thing that summons MER. A fix whose mechanism can cause the defect it
treats is not a fix. The root cause is addressed by D1/D5/D6, and the real-app
run above shows 0 visible windows and 0 focus steals across a full conversion
phase. If it is ever reported again, re-measure with
`scripts/measure_office_window.py --state visible` first — a cold-app control
passes with the bug fully present, which is the mistake the original measurement
made.

---

## D4 — ROOT CAUSE FOUND AND FIXED: two instances, one PowerPoint

**Shipped in `9854a8d`.** Reproduced on demand, which is what turned this from
a hypothesis into a defect.

The operator's hypothesis was that the two audit lanes caused it. That was
right in mechanism and wrong in pressure: it is not memory or CPU contention.
**macOS gives a user session exactly ONE Microsoft PowerPoint**, so two Canvas
Downloader processes drive the same application - and a conversion is
`open` → `save active <doc>` → `close`, which is INDIVISIBLE. The other
instance's `open` lands between our `open` and our `save`.

Two batches started at the same moment against the real applications:

    batch A   8 files ->  0 converted, 8 failed
    batch B   8 files ->  0 converted, 8 failed
    errors    "Connection is invalid. (-609)"
              "reported success but no output file was created"
    artefact  `B8 (1).pdf` - two conversions racing for one destination
    result    PowerPoint CRASHED into Microsoft Error Reporting

i.e. the operator's original screenshot, on demand.

**It also exposed a hole in D1's fix.** The staged basename was the constant
`src.<ext>`, with the uuid only in the DIRECTORY - so `our_document_test`,
which identifies our document by NAME, answered "yes, mine" for the other
instance's document. `guard_trips` was **0** while all 16 files failed. The
basename now carries 6 hex of the work dir (15 bytes total, so Word's
~255-byte staged-path limit is untouched).

And `run_applescript` now holds a per-app `flock` for one conversion.
`flock` because the kernel releases it when the holder dies - a crashed
instance is the very thing this defends against. Bounded at 120 s, then
proceeds anyway, so the degraded case is the old behaviour rather than a
stalled run.

After both fixes, the identical run: **8/8 and 8/8**, no stray PDFs,
PowerPoint alive, batch B taking 14.2 s against A's 7.7 s.

### Ruled out by measurement - do not re-chase

* **A load-fragile guard.** `open` might have returned before the document
  became frontmost, which would make the D1 guard reject good conversions
  under load. It does not: **0 polls needed in 10/10 opens, cold and under
  full 10-core load** (`scripts/probe_office_open_latency.py`). The polling
  machinery was written and then dropped.
* **The 448 MB deck.** Course 43660 contains one, and the matrix named it among
  the failures. It converts in **3.0 s at 245 MB peak RSS**, no crash.
* **Synthetic load alone.** 30 files under 10 CPU burners + 6 GB resident:
  30/30 converted, no crash.

### The recovery is proven independently of the cause

`scripts/verify_office_crash_recovery.py` INJECTS the crash - it kills
PowerPoint mid-batch, which forces the exact condition instead of racing for
it. With the D6 fix, and under CPU+memory pressure:

| run | result |
|---|---|
| control, no kill | 5/5 converted, user document intact |
| kill after 2 PDFs | **6/6 converted**, 0 failed, nothing left behind |
| kill + 10 burners + 5 GB | **6/6 converted**, 0 failed |

Under the old classification this is precisely where 57 files were abandoned.

**Note on one number**: in a kill run, `user_docs_after` is 0 because the
injected `pkill` closes the user's document - not the app. A real crash does
the same and PowerPoint's own auto-recovery is what offers the work back. Only
the control run can test whether OUR code closes it, and it does not.

---

## The three CHECKER defects (`bd03305`)

Found while triaging, and worth as much as the product fixes — the brief's rule
is that the checker is under test too, and historically fails more often.

1. **"convert_X did not reach N file(s) unpacked from archives"** asserted a
   rule the repo deliberately REVERSED on 2026-07-29, on measurement (one real
   lecture zip: 21,824 extracted files, 11,818 convertible, 9,730 past Windows'
   260-char limit; and a source-consuming converter would DELETE a student's own
   project files). The register already read *"invalid … must not be re-filed"*
   and the checker re-filed it six times. Now an observation carrying the reason.
2. **`matrix lanes` counted a PREVIOUS matrix's rows** — lane dirs are reused and
   the progress file is append-only. Measured: `23/37 done` when the truth was
   `2/37`; the free1 lane's file still holds 59 rows against a 37-row spec.
   Now scoped to the current `lane_spec`, and it reports a `total`. The scope
   matters more in `_completed`, where a reused id would make a lane SKIP real
   work — the macOS run escaped that only because the two matrices used `s0xx`
   and `m0xx` ids. Luck, not design.
3. **`REC_COST_MB["transcribe"]` encoded the CUDA figure only** (64.9 = 19.1 s ×
   3.4 MB/s), so transcription was under-priced 3.4x on any CPU-only box and
   ALWAYS on macOS. It now probes `panopto.hardware.detect_compute_hardware`
   — the app's own answer — rather than restating the test. 221.0 here.

---

## STILL OPEN — the honest list

* **D4's root cause** (above). No artefact exists; not claimed as fixed.
* **The matrix findings were collected BEFORE the checker fixes**, so
  `findings.jsonl` still contains the six archive rows and the three over-cap
  rows at their old severities. A re-run of `matrix collect` would reclassify
  them; it was not re-run.
* **No fresh matrix was run against the fixed code.** The verification is the
  targeted controls above (harness + real app), not another 56-row sweep.

## RESOLVED after this file was first written

**D8 — "N over-cap file(s) were skipped without an ignored row"** (MEDIUM, 3
rows) turned out to be a **fourth checker defect**, fixed in `6bad460`.

The check built its over-cap set from the whole Files tab with no regard for the
folder's `file_filter`. A file outside the folder's SCOPE never reaches the size
gate at all — `_download_file_async` returns above it — so there is no skip to
record and no ignored row to expect. Measured on the rows that reported it
(m025/m031, `file_filter=study`, cap 5 MB): **both "unrecorded" ids were 12.5 MB
`.jpg` files**, and `file_in_scope(name, "study")` is False for each.

It was asking the app to recreate a bug it had deliberately removed — *"out of
scope is NOT the same as ignored … it made a scope decision look like a per-file
decision the user had taken"*, after the Ignored Files dialog listed 23 such
files in a real folder and offered to restore them into a folder configured to
exclude them.

**Four of the six defects triaged in this pass were in the checker, not the
product.** That is the ratio the brief predicts, and the reason a red row is a
question before it is a finding.
