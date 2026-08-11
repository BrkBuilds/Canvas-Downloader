# The macOS Office-conversion defects — investigation complete, fixes NOT written

**Written 2026-08-11 on the Tahoe audit box, immediately before a context
compaction.** Everything below is MEASURED on this machine unless it says
otherwise. Read `MAC_RUNBOOK.md` for the phase plan and `RUNBOOK.md` for the
oracle rules; this file is one subject only.

The trigger was an operator report: *"a powerpoint somehow crashed and I got an
error message… clicking the blue button caused ppt to come up flashing for every
ppt file converting, full screen, until the conversions ended"* — followed by a
screenshot of PowerPoint's Recents list full of `src` entries pointing into our
temp staging directory.

Chasing it found FOUR defects, one of which is data loss.

---

## THE CAUSAL CHAIN (hypothesis, and the reason to fix D1 first)

    D1  `active <doc>` is trusted        -> a FAILED conversion never closes OUR document
      -> documents accumulate in PowerPoint
      -> memory exhaustion -> D4 PowerPoint CRASHES
      -> Microsoft Error Reporting restarts it VISIBLE ("Recover work and
         restart" is ticked by default and the operator clicked OK)
      -> D2 every subsequent conversion shows a full-screen window

`converters/pdf.py`'s own docstring already predicts the first hop: *"a batch of
N failures stacked N presentations on top of each other in PowerPoint (which
could exhaust memory / crash the machine)"*. The error handler that was supposed
to prevent it closes `active presentation` — which, when `active` is the wrong
document, leaves ours open. **Verify this chain before asserting it in a commit
message**; it is currently reasoning plus one strong corroborating docstring.

---

## D1 — all three converters can close the USER'S document without saving

**Severity HIGH (data loss). Filed as `mac_office_active_document`.**

`converters/pdf.py` (PowerPoint), `converters/word.py`, `converters/excel.py`
share the shape:

    open POSIX file "<ours>"
    set theDoc to active presentation | active document | active workbook
    save theDoc ... as PDF
    close theDoc saving no
    on error
        close active presentation saving no      <- closes whatever is FRONTMOST

Two ways it goes wrong:

1. **The error handler closes a document it never opened.** When `open` fails —
   and it does; this run logged `[AppleScript] PowerPoint failed (other):
   710:716: execution error: Microsoft PowerPoint got an error: Parameter error.
   (-50)` plus ten more conversion failures across rows m029/m030/m032 — control
   jumps to `on error`, where `active` is the user's document. `saving no`
   discards their unsaved edits.
2. **The success path can export the wrong document**, if `open` has not won the
   race or the app is in crash-recovery with a recovered deck frontmost. Their
   document is saved as our PDF (wrong content, silently) and then closed.

Reachable by any student with Word or PowerPoint open while a sync converts.
The codebase already guards the same risk from the other side: the Windows
branch kills *"only that PID (targeted, never a broad /IM that would close the
user's own open presentations)"*.

### The fix

`engine/applescript_bridge.office_container_stage` stages every conversion as
**`src.<ext>` inside a per-conversion uuid work dir** (verified in source:
`staged_src = work / ("src" + src.suffix)`), and its own comment says *"nothing
reads the staged basename"* — so we own a unique, known name. Bind to it:

    set theDoc to missing value
    try
        open POSIX file "<staged src>"
        set theDoc to (first presentation whose name is "src.pptx")
        save theDoc in POSIX file "<staged dst>" as save as PDF
        close theDoc saving no
    on error errMsg number errNum
        try
            if theDoc is not missing value then close theDoc saving no
        end try
        error errMsg number errNum
    end try

`missing value` is load-bearing: it makes *"we never got a document"*
expressible, which `active` cannot say. Apply to all three converters — the
counting rule from the `pdf_looks_real` episode applies (**two delete sites
needed two gates**; here it is three converters and two `active` references
each).

**The test that matters does not exist yet**: feed a corrupt/unopenable file
with a second document open, and assert that second document is still open
afterwards. That is the branch that loses data.

---

## D2 — after a crash-restart, every conversion shows a full-screen window

**Severity MEDIUM (UX). Filed as `mac_office_window_flash`.**

`engine/applescript_bridge.py` carries a long measured note concluding that
doing NOTHING is quietest (`with NEITHER -> visible 0/7, twice, repeatable`).
**That measurement is correct and INCOMPLETE.** Its own trace reads
`absent -> false` — the app was NOT RUNNING, and an Apple event launched it
without activating it. It says nothing about an app already running and visible,
which is exactly what Error Reporting leaves behind. Normally
`prime_office_automation` launches with `open -g -j` (hidden), which is why this
is invisible until a crash.

The note itself invites the report: *"If window-flashing is ever reported again,
re-measure with the trace above before adding anything back; do not reach for
System Events."*

### The fix, and the three constraints it must satisfy

Hide **our own document's window**, not the process. Read out of the app
bundles' `.sdef` rather than assumed — all three expose the Standard Suite
`window` class with BOTH `visible` and `document`:

| app | `application.visible` | `window.visible` | `window.document` |
|---|---|---|---|
| Word | no | **yes** | **yes** |
| Excel | no | **yes** | **yes** |
| PowerPoint | no | **yes** | **yes** |

PowerPoint's own `document window` class has NO `visible` — only the standard
`window` does. That distinction is the whole reason this is possible.

Per-window hiding uses the app's OWN dictionary, so it needs **Automation**
(already granted, answerable in place) and never **Accessibility** — which this
codebase removed on purpose. It cannot touch a document the user opened.

`scripts/measure_office_window.py` IS ALREADY WRITTEN for this. It reproduces
the REPORTED state (`--state visible`), not the cold one, because **a cold-app
control passes with the bug fully present** — the exact mistake the original
measurement made. Run `--state visible` before and after.

---

## D3 — 490 nodes polluting Office's shared Recents store

**Severity MEDIUM. Not yet filed as its own finding.**

The operator's screenshot showed PowerPoint's Recents list full of `src` entries
pointing into `.../CanvasDownloaderTmp/cd_<uuid>/`. Removing them by hand is
per-entry and horrible.

**THE WEB ADVICE IS STALE — do not follow it.** Every result says the list lives
in `com.microsoft.<App>.securebookmarks.plist`; the best article's own update
admits the method "no longer works with current versions", and MEASUREMENT
agrees: that plist held **1 entry, 0 ours**. It stores sandbox security-scoped
bookmarks, not the display list.

**The real store**, measured:

    ~/Library/Group Containers/UBF8T346G9.Office/MicrosoftRegistrationDB.reg

a SQLite registry-tree shared by every Office app:

    HKEY_CURRENT_USER(node_id, parent_id, name, write_time)
    HKEY_CURRENT_USER_values(node_id, name, type, value)

Our entries are node NAMES (full `file://` URLs) under exactly:

    Software/Microsoft/Office/15.0/Common/MruUserData/UnsignedUser/<App>/Local/Documents/

| app | our entries | the user's |
|---|---|---|
| PowerPoint | **350** | 3 |
| Excel | 129 | 0 |
| Word | 11 | 0 |

We are 99% of the operator's PowerPoint Recents list.

### Why targeted deletion is SAFE here — all four verified, not assumed

* **490** nodes match the marker `/CanvasDownloaderTmp/`, which is a directory
  name **we own**;
* **0** of them sit outside an `MruUserData` subtree;
* **0** have children — every one is a leaf, so there is no tree surgery;
* 702 value rows hang off them with a fixed schema (`Application`,
  `DocumentUrl`, `FileName`, `FileSizeInBytes`, `FutureAccessToken`, `IsPinned`,
  `Path`, `StorageHost`, `Timestamp`) — 9 per node, so the cleanup must delete
  the node row AND its value rows.

**DOUBLE GATE, and neither half is sufficient alone**: delete a node only when
its name contains the marker AND its parent key path is an
`MruUserData/.../Documents` key. Back the DB up first; refuse if it is locked or
if Office is running; never touch a row that fails either gate.

### Prevention where the API allows it

`open` accepts `add to recent files` in **Word only** — verified in the sdefs.
PowerPoint and Excel expose no such parameter, and PowerPoint has no
`recent file` class either (Word and Excel do).

**The asymmetry is Microsoft's and it is real**, inherited from the VBA object
model: `Application.RecentFiles` exists for Word and Excel and has never existed
for PowerPoint. Do not spend time looking for a PowerPoint equivalent again.

---

## D4 — PowerPoint crashes. UNDIAGNOSED, and stated as such.

Twice, during repeated open/save-as-PDF/close cycles, under two-lane memory
pressure. Course 43660 contains a macro-enabled `.pptm`.

**No crash artefact exists to read**: `~/Library/Logs/DiagnosticReports` is
empty (Microsoft routes its own crashes to MER, which uploads and discards). So
the cause cannot be established from disk. The D1 chain above is the leading
hypothesis; if D1's fix stops the crashes, that is the evidence.

Bounded already: `run_applescript` has a per-file timeout (`_timeout_for`), so a
wedged Office call cannot hang the unattended daily sync.

---

## OPERATOR DECISIONS (2026-08-11) — do not re-litigate

* **Quit Office only if WE launched it.** Record whether the app was running
  before the batch; quit at the end only if it was not. Matches the existing
  "targeted, never a broad /IM" rule. This ALSO makes the D3 sweep safe, because
  Office cannot rewrite the MRU from memory afterwards.
* **Do not corrupt Office's shared registry** — but do not give up on
  PowerPoint either. The double-gated sweep above is the answer.
* **Notification denial: respect it, do not circumvent** (already shipped,
  588bead).
* **Download matrix: one transcription row only** (already applied; 96.0% of
  2-way tuples retained, all 44 lost tuples involve a transcription axis).

---

## TWO HARNESS BUGS FOUND ALONGSIDE — fix after the product work

1. **`REC_COST_MB["transcribe"] = 65.0` is the CUDA figure**, not the CPU one.
   `19.1 s x 3.4 MB/s = 64.9`, and the comment quotes both 19.1 s (CUDA) and
   65.0 s (CPU) while the constant encodes only the GPU case. So the scheduler
   under-prices transcription by 3.4x on any CPU-only box — and **on macOS it is
   always wrong, because CUDA does not exist there**. CPU-correct value is
   `65.0 s x 3.4 = 221.0`. Fix by probing, not by swapping one wrong constant
   for another.
2. **`matrix lanes` counts rows from a PREVIOUS matrix.** Lane directories are
   reused between matrices, so after the sync matrix it reported the download
   matrix as `23/37 done` when the real figure was `2/37`. Count only ids
   present in the CURRENT `lane_spec.json` — `/tmp/mprog.py` (throwaway) does
   this and is the pattern to fold in.

---

## STATE AT COMPACTION

* Branch `macos-audit-26`, 12 commits pushed, HEAD `255080d`.
* **Download matrix 55/56, 0 failed.** Only `m001` left — the single
  transcription row, ~28 min elapsed against a ~39 min estimate. `free1` is
  finished (37/37).
* Uncommitted: `tests/audit/AUDIT_FINDINGS.md` (register annotations for the
  flash + notification fixes) and `scripts/measure_office_window.py` (new, the
  D2 rig).
* **DO NOT edit `converters/*.py` or `engine/applescript_bridge.py` until the
  matrix finishes** — the office lane is still executing conversions through
  them.
* After the matrix: `matrix collect`, triage findings product-vs-checker,
  then implement D1 -> D3 -> D2 in that order (severity), then the two harness
  bugs, then full suite + `register update` + push.
