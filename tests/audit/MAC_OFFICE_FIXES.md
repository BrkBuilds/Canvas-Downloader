# The macOS Office-conversion defect set — SHIPPED 2026-08-11

**All measurements on the Tahoe (macOS 26.6) audit box, against the real
applications.** Read `MAC_RUNBOOK.md` for the phase plan and `RUNBOOK.md` for
the oracle rules; this file is one subject only.

The trigger was an operator report: *"a powerpoint somehow crashed and I got an
error message… clicking the blue button caused ppt to come up flashing for every
ppt file converting, full screen, until the conversions ended"* — followed by a
screenshot of PowerPoint's Recents list full of `src` entries pointing into our
temp staging directory.

That one report, plus the download matrix that ran afterwards, produced **three
product defects (all HIGH) and three checker defects**. Every product defect was
a class this repo already documents, surviving in a module the earlier fix did
not reach — the playbook's thesis for the fourth pass running.

---

## THE CAUSAL CHAIN — confirmed, and it starts at D1

    D1  `active <doc>` is trusted        -> a FAILED conversion never closes OUR document
      -> documents accumulate in PowerPoint
      -> memory pressure -> PowerPoint CRASHES
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

**So D2 and D3 are downstream of D1/D5/D6, and fixing those is what removes
them.** See "D2 / D3" below for why neither gets a direct fix.

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

## D4 — PowerPoint crashes. Root cause NOT established.

Twice, under two-lane memory pressure. `~/Library/Logs/DiagnosticReports` is
empty (Microsoft routes its own crashes to MER, which uploads and discards), so
there is no artefact to read. The D1 chain is the leading hypothesis and D1 is
now fixed; **if the crashes stop, that is the evidence.** Not claimed as fixed.

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
* **D8: "N over-cap file(s) were skipped without an ignored row"** (MEDIUM, 3
  rows). NOT fixed and NOT dismissed. The download engine *does* call
  `sync_manager.ignore_file` at its size gate
  (`core/canvas_logic.py`, the `max_bytes` branch), a `SyncManager` *is*
  constructed in download mode, and that call is wrapped in
  `except Exception: pass` — a silent swallow of exactly the kind this repo has
  a rule against. Which of those explains the missing rows was not determined:
  it needs a reproduction with `max_file_size` set, checking the manifest
  immediately afterwards. Do that before changing anything.
* **The matrix findings were collected BEFORE the checker fix**, so
  `findings.jsonl` still contains the six archive rows as MEDIUMs. A re-run of
  `matrix collect` would reclassify them; it was not re-run.
