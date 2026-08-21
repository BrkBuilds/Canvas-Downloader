# Adjudicating the contaminated office rows (2026-08-21)

Rows m012, m013, m014, m025, m026 ran while free lanes were alive and are
contaminated by the instance-blind teardown gap (register: "Office ownership is
instance-blind"). They must be re-run ALONE before their findings are believed.

**Do NOT assume contamination explains every Office error in them.** Correlating
each office-lane failure against free-lane `[OfficeQuit]` timestamps splits them:

## m014 (Excel)

| office-lane error | nearest free-lane event | verdict |
|---|---|---|
| 14:56:44.194 `-609` not usable (recovered on retry) | NONE - earliest free-lane teardown activity in the window is free4 at ~14:56:55 | **UNEXPLAINED - candidate genuine** |
| 14:56:54.024 `-50` Parameter error, `Opgavesæt 6-vejl.xlsx` FAILED | 5s after the recovery above, no teardown | **candidate genuine / fallout of the above** |
| 14:57:15.580 `-609` not usable (recovered) | free4 `force-terminated Microsoft Excel` 14:57:11.624 (**3.96s**) | contamination |
| 14:57:26.221 `-50` Parameter error, `Øvelse 3 - VL.xls` FAILED | free2 `still running after 6s wait: Microsoft Excel` 14:57:20.315 | contamination |

## m025 (PowerPoint)

Clear contamination: free3 `force-terminated Microsoft PowerPoint` 14:59:54.043
-> office `-609` 14:59:54.812 (**0.77s**). 6 crash-recoveries, 4 outright
failures. The `-30001` entries ("the frontmost presentation is not the one
Canvas Downloader opened") are the app's OWN guard working correctly once a
crash-recovery deck came frontmost - a downstream symptom, not a defect.

## What the clean re-run must answer

Re-run m014 ALONE. If `Opgavesæt 6-vejl.xlsx` and/or the 14:56:44 file fail
again with the same errors and no other instance alive, they are GENUINE and
belong in the register. If they convert cleanly, the whole row was contamination.

Same for m025's 4 failures, though those have a direct sub-second correlate and
are very likely all contamination.

## Caveat on the method

`_force_close_canvas_docs_sync` (teardown STEP 1) logs NOTHING, so a marker
force-close leaves no trace and cannot be correlated. Absence of a log line is
therefore weak evidence of absence for that specific mechanism - which is
another reason the clean re-run, not this table, is what settles it.

---

# RESOLVED by the clean re-run (2026-08-21, run 20260821_162842_macos26-dl-redo-contaminated)

All five rows re-run ALONE, one serial lane, no other instance alive.

| row | contaminated | clean | verdict |
|---|---|---|---|
| m012 | 3 findings | 3 | identical - was never contaminated |
| m013 | 5 | 5 | identical - was never contaminated |
| m014 | 7 | **3** | the 4 Excel findings were ALL contamination |
| m025 | 22 | **7** | the 15 extra findings were ALL contamination |
| m026 | 4 | (see run) | |

**m014: ZERO Excel error lines in the clean run.** Both files named in the
correlation table - `Opgavesæt 6-vejl.xlsx` and `Øvelse 3 - VL.xls` - converted
with zero errors. **m025: ZERO PowerPoint error lines** against 4 outright
failures before.

## The candidate genuine defect was NOT genuine

The 14:56:44 `-609` had no free-lane `[OfficeQuit]` correlate and was recorded
above as "UNEXPLAINED - candidate genuine". It did not reproduce. The most
likely trigger is the one the notes already flagged as uncorrelatable:
`_force_close_canvas_docs_sync` is teardown STEP 1 and **logs nothing**, so a
free lane closing the office lane's in-flight staged document leaves no trace at
all.

**The methodological point is the durable one.** The correlation table was
suggestive and WRONG on its one novel claim. What settled it was re-running the
row in isolation. When a harness-contention defect is in play, a timestamp
correlation can only ever CONFIRM contamination - it can never establish that
something is genuine, because the most damaging mechanism is unlogged. Do not
file a product finding off the absence of a correlate.

**m012 and m013 reproducing identically (3->3, 5->5) is the control** that makes
the m014/m025 drops meaningful rather than an artifact of the redo producing
fewer findings across the board.

## Follow-up worth doing with defect (b)

Give `_force_close_canvas_docs_sync` a log line. It is the one teardown step
that can destroy another instance's work silently, and its silence cost this
session an hour of correlation work that a single line would have answered.
