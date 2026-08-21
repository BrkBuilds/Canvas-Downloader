"""Oracle O2 - the debug log, parsed into structured events.

The debug log is the app's own account of what it did, and it is unusually
good: every phase writes a delimited header, every saved file writes its
absolute path and byte count, and the analysis writes one line per file with
its category. That makes it a genuine quantitative source rather than prose to
skim.

Two decisions worth stating.

**Parse, never grep.** A regex run at the moment a question is asked answers
only that question, and the next question re-scans a 150,000-line file with a
slightly different pattern. Parsing once into typed events means every check
downstream reasons about the same objects, and a line the grammar does not
recognise is *counted* rather than silently dropped - an unrecognised line
volume that jumps between versions is itself a signal that the log changed
shape and some check has quietly stopped matching.

**Tracebacks and bridged records are first-class.** ``core.canvas_debug``
mirrors the ``logging`` module into this file with a ``[LEVEL] [logger]``
prefix, and ``log_debug_exc`` appends full tracebacks between ``--- traceback
---`` markers. Those are multi-line, so a line-at-a-time reader would report
the first line of a crash as an ordinary message and lose the rest.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

TS = r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]"

# The tags `sync/analysis.py:_row` actually writes, mapped to the audit's
# category names. THIS IS THE ONLY PLACE THE VOCABULARY IS SPELLED, and it is
# the audit's single most load-bearing constant: it decides which of the six
# analysis categories oracle O2 can speak about at all.
#
# It was wrong for the whole life of the suite, in the way that is hardest to
# see - three of the six tags named something the app has never emitted. The
# app has written `UPDATE-EDIT`, `CANVAS-DEL` and `LOCAL-DEL` since 2026-06-02;
# the oracle was written on 2026-07-29 expecting `UPDATE-MODIFIED`,
# `DELETED-CANVAS` and `DELETED-LOCAL` - names invented rather than read off a
# log. So every per-file row for `updated_modified`, `deleted_on_canvas` and
# `deleted_locally` was dropped on the floor, silently, from day one.
#
# What makes that worse than a missed parse is what was built ON it. A later
# session measured the effect - "a run whose analysis reported 2
# deleted-on-Canvas and 2 ignored: the log contained zero rows for either" -
# and wrote the conclusion into `crosscheck._LOG_DETAILED_CATS` as a FACT ABOUT
# THE PRODUCT: that the app only logs two categories per file. The app's own
# source says the opposite two lines above the loop ("One line per file, for
# EVERY category the analyzer produced"). That false premise routed four of six
# categories to the review screen as their only witness, and the review screen
# does not exist on a Quick Sync row - which is how the 2026-08-21 sync matrix
# produced 14 HIGH "was not offered" findings against an app whose log named
# every one of those files, in the right category, on the line above.
#
# `tests/test_audit_log_tag_vocabulary.py` reads the tags straight out of
# `sync/analysis.py` and fails the SUITE when the two drift, so a rename in the
# app can never again be discovered by a six-hour audit.
ANALYSIS_ROW_TAGS: dict[str, str] = {
    "NEW": "new",
    "UPDATE-CLEAN": "updated_clean",
    "UPDATE-EDIT": "updated_modified",
    "CANVAS-DEL": "deleted_on_canvas",
    "LOCAL-DEL": "deleted_locally",
    "IGNORED": "ignored",
}

# `_row` appends "   -> <local path>" only where the local basename DIFFERS
# from the Canvas display name - which is exactly the case a plain `(?P<name>.+)`
# gets wrong, because it swallows the arrow and the path into the filename.
# Both halves are legitimate spellings of the same file (a display name may
# carry no extension at all: `Eksempel - Gruppekontrakt` on disk is
# `Eksempel - Gruppekontrakt.docx`), so both are captured and both are offered
# for matching. The separator is TWO-OR-MORE spaces before the arrow, matching
# what `_row` writes, so a filename that legitimately contains " -> " is not
# split.
_ANALYSIS_ROW_RE = re.compile(
    r"^\s+\[(?P<cat>" + "|".join(map(re.escape, ANALYSIS_ROW_TAGS)) + r")\]"
    r"\s+(?P<name>.+?)(?:\s{2,}->\s*(?P<local>.+))?$")

PATTERNS: list[tuple[str, re.Pattern]] = [
    # -- download ------------------------------------------------------
    ("download_start", re.compile(
        r"=== Download Start: (?P<course>.+?) \| Course (?P<idx>\d+)/(?P<total>\d+) ===")),
    ("download_config", re.compile(
        r"^Mode: (?P<mode>\w+) \| Filter: (?P<filter>\w+)$")),
    ("download_pp", re.compile(r"^Post-processing: \[(?P<converters>.*)\]$")),
    ("download_secondary", re.compile(r"^Secondary content: \[(?P<types>.*)\]$")),
    ("download_params", re.compile(
        r"^Filter: (?P<filter>\w+) \| Concurrency: (?P<conc>\d+) \| "
        r"Max file size: (?P<maxsize>[^|]+?) \| Estimated payload: (?P<payload>[^\n]+)$")),
    ("save_dir", re.compile(r"^Save Dir: (?P<dir>.+)$")),
    ("file_saved", re.compile(r"^File Saved: (?P<path>.+?) \((?P<bytes>\d+) bytes\)$")),
    ("http_status", re.compile(
        r"^Response Status: (?P<code>\d+) Content-Type: (?P<ctype>.+)$")),
    ("skip_existing", re.compile(r"^Skipping existing file: (?P<name>.+)$")),
    ("size_skip", re.compile(r"skipped .*(?:too large|exceeds).*", re.I)),
    ("download_complete", re.compile(
        r"--- Download Complete: (?P<course>.+?) \| (?P<items>\d+) items \| "
        r"(?P<mb>[\d.]+) MB downloaded ---")),
    ("course_finished", re.compile(
        r"=== Course Finished: (?P<course>.+?) \| Downloaded: (?P<items>\d+) items \| "
        r"Errors: (?P<errors>\d+) ===")),
    ("module", re.compile(r"^Processing Module: (?P<name>.+?) \(ID: (?P<id>\d+)\)$")),
    ("module_items", re.compile(
        r"^Found (?P<count>\d+) items in module '(?P<name>.+)'$")),
    ("catchall_found", re.compile(
        r"^Catch-All found new file: (?P<name>.+?) \(ID: (?P<id>-?\d+)\)$")),
    ("catchall_skip", re.compile(
        r"^Catch-All skipping module file: (?P<name>.+?) \(ID: (?P<id>-?\d+)\)$")),
    # The sweep yielding to Canvas Content, which owns this file's only manifest
    # row. Distinct from the module skip above because it is a DIFFERENT rule
    # with a different failure: get it wrong and the file is fetched twice and
    # the first copy is orphaned.
    ("catchall_defer", re.compile(
        r"^Files-tab sweep skipping Canvas Content attachment: (?P<name>.+?) "
        r"\(ID: (?P<id>-?\d+)\) -> (?P<dest>.+)$")),
    # A file that landed WITHOUT a fetch, from a copy this run already had.
    # It must be counted as a write or the delivery check goes blind to it -
    # the file is on disk with no "File Saved" line to answer for it.
    ("file_placed", re.compile(
        r"^(?P<verb>Moving|Copying) already-downloaded file \(ID: (?P<id>\d+)\): "
        r"(?P<src>.+?) -> (?P<dest>.+)$")),
    ("secondary_saved", re.compile(
        r"^Saving (?P<etype>\w+): (?P<name>.+?) -> (?P<path>.+)$")),
    # A .url shortcut for an ExternalUrl/ExternalTool item. It IS a file the app
    # wrote, announced with a different verb, so leaving it uncounted put every
    # course with a link one file above its own claim - slack that would hide a
    # genuinely missing file from the delivery check.
    ("link_created", re.compile(
        r"^Creating Link: (?P<name>.+?) \((?P<url>.+?)\) -> (?P<path>.+)$")),
    # The runner declines to transcribe - with a warning and no error - when the
    # engine or the configured model is not installed. Captured so the checks
    # can tell "the app failed to produce transcripts" from "this machine was
    # never able to", which look identical on disk.
    ("panopto_tx_unavailable", re.compile(
        r"Transcription (?:engine|model) not (?:installed|set up).*will be skipped")),
    # A recording the user's own max-file-size setting excluded. Lecture videos
    # run 70-300 MB, so a modest cap legitimately takes ALL of them - and the
    # delivery check, reading only the empty manifest, then reports the app for
    # discovering 36 recordings and delivering none.
    ("panopto_size_skip", re.compile(
        r"Panopto size gate: skipping '(?P<title>.+?)' \(~(?P<mb>[\d.]+) MB est "
        r"> (?P<limit>[\d.]+) MB limit\)")),
    # The batch's own tally, which names what it did rather than leaving it to
    # be inferred from the manifest.
    ("panopto_batch_done", re.compile(
        r"Panopto batch done: found=(?P<found>\d+) downloaded=(?P<downloaded>\d+) "
        r"transcribed=(?P<transcribed>\d+) skipped=(?P<skipped>\d+) "
        r"failed=(?P<failed>\d+)")),
    ("inline_link", re.compile(
        r"Inline link: fetching metadata for file (?P<fid>\d+) \('(?P<text>.*)'\)")),
    ("inline_link_dead", re.compile(
        r"Inline link: file (?P<fid>\d+) is inaccessible or deleted - skipping")),
    ("hybrid_gap", re.compile(
        r"Hybrid Fetch: Found (?P<count>\d+) files in Modules that were missing "
        r"from 'Files' tab")),

    # -- sync ----------------------------------------------------------
    ("sync_analysis_start", re.compile(
        r"=== Sync Analysis: (?P<course>.+?) \(ID: (?P<cid>\d+)\) ===")),
    ("sync_mode", re.compile(r"^Mode: (?P<mode>Quick Sync|Analyze, Review & Sync|.+)$")),
    ("sync_folder", re.compile(r"^Course Folder: (?P<folder>.+)$")),
    ("sync_manifest", re.compile(
        r"^Loaded local manifest: (?P<rows>\d+) tracked entrie\(s\)")),
    ("sync_contract", re.compile(
        r"^Secondary contract: source=(?P<source>\w+) \| enabled=\[(?P<enabled>.*)\] "
        r"\| isolate=(?P<isolate>\w+)$")),
    ("sync_fetched", re.compile(
        r"^Fetched (?P<count>\d+) files from Canvas")),
    ("sync_structure", re.compile(r"^Detected folder structure: (?P<structure>\w+)$")),
    ("sync_healed", re.compile(r"^Manifest healed \| DB was reset: (?P<reset>\w+)")),
    ("analysis_complete", re.compile(
        r"^Analysis complete \([^)]*\): (?P<new>\d+) new \| (?P<clean>\d+) clean updates "
        r"\| (?P<modified>\d+) locally-edited updates \| (?P<candel>\d+) deleted on Canvas "
        r"\| (?P<locdel>\d+) deleted locally$")),
    ("analysis_row", _ANALYSIS_ROW_RE),
    ("qs_select", re.compile(
        r"^\s+\[QS-SELECT-(?P<cat>NEW|UPDATE)\]\s+(?P<name>.+?)"
        r"(?:\s{2,}->\s*(?P<local>.+))?$")),
    ("qs_skip", re.compile(
        r"^\s+\[QS-SKIP-(?P<cat>EDITED|LOCDEL|CANDEL)\]\s+(?P<name>.+?)"
        r"(?:\s{2,}->\s*(?P<local>.+))?$")),
    ("qs_summary", re.compile(
        r"^Quick Sync summary: (?P<queued>\d+) files queued \| skipped (?P<edited>\d+) "
        r"edited, (?P<locdel>\d+) locally-deleted, (?P<candel>\d+) Canvas-deleted$")),
    ("sync_route", re.compile(r"^→ Routing to: (?P<route>\w+)")),
    ("sync_exec_start", re.compile(
        r"=== Sync Execution: (?P<course>.+?) \| Mode: (?P<mode>.+?) ===")),
    ("sync_queued", re.compile(
        r"^Files queued: (?P<count>\d+) \((?P<mb>[\d.]+) MB\)$")),
    ("sync_plan_row", re.compile(
        r"^\s+→ \[(?P<action>[^\]]+)\] (?P<name>.+?) → (?P<target>.+)$")),
    ("sync_ok", re.compile(r"^✓ (?P<name>.+)$")),
    ("sync_synced", re.compile(r"^\s+\[SYNCED\] (?P<name>.+)$")),
    ("sync_complete", re.compile(r"=== Sync Complete: (?P<course>.+?) ===")),
    ("sync_totals", re.compile(
        r"^This pair: (?P<pair>\d+) files synced \| Total across all pairs: (?P<total>\d+) "
        r"\| Errors: (?P<errors>\d+) \| PP failures: (?P<pp>\d+)$")),

    # -- post-processing -----------------------------------------------
    ("pp_start", re.compile(r"--- Post-Processing: (?P<course>.+?) ---")),
    ("pp_converters", re.compile(r"^Active converters: (?P<list>.+)$")),
    ("pp_available", re.compile(
        r"^(?:Synced files|Files) available for conversion: (?P<count>\d+)$")),
    ("pp_converted", re.compile(
        r"(?:Converted|Extracted|Compiled) (?P<src>.+?) (?:->|→) (?P<dst>.+)$")),

    # -- panopto -------------------------------------------------------
    ("panopto_discovered", re.compile(
        r"Panopto: discovered (?P<count>\d+) recording\(s\) \| new/missing (?P<new>\d+) "
        r"\| deleted-locally (?P<locdel>\d+) \| ignored (?P<ignored>\d+) \| "
        r"up to date (?P<uptodate>\d+)")),
    ("panopto_downloaded", re.compile(
        r"Panopto downloaded (?P<name>.+?) \((?P<mb>[\d.]+) MB in (?P<secs>[\d.]+)s\)")),
    ("panopto_transcribe_start", re.compile(
        r"Transcribing \[(?P<idx>\d+)/(?P<total>\d+)\] '(?P<title>.+?)' "
        r"\(device=(?P<device>\w+)")),
    ("panopto_transcribe_ok", re.compile(
        r"Transcribe worker \(pid=(?P<pid>\d+)\) OK in (?P<secs>[\d.]+)s: (?P<outputs>.+)$")),
    ("panopto_transcribed", re.compile(
        r"Transcribed (?P<name>.+?): (?P<segments>\d+) segments, lang=(?P<lang>\w+)")),
    ("panopto_batch", re.compile(
        r"Panopto batch start \(pid=\d+\): (?P<targets>\d+) target\(s\) \| "
        r"model=(?P<model>\S+) device=(?P<device>\S+) lang=(?P<lang>\S+)")),

    # -- failures ------------------------------------------------------
    ("error", re.compile(r"^ERROR: (?P<msg>.+)$")),
    ("soft_warning", re.compile(r"^Soft Warning: (?P<msg>.+)$")),
    ("cancel", re.compile(r"cancellation requested|Cancelled:", re.I)),

    # -- high-volume routine lines -------------------------------------
    # Matched last and only so they stop inflating ``unmatched``. That counter
    # is meant to answer "has the log changed shape since this grammar was
    # written" - a question it cannot answer while 60% of a normal log is
    # unmatched by construction.
    ("request_url", re.compile(r"^Requesting URL: (?P<url>\S+) \(Attempt (?P<n>\d+)\)$")),
    ("session_env", re.compile(r"^(?:=== Session Environment ===|===========================|"
                               r"\s+(?:App|OS|Python|CA bundle|Context):)")),
    ("rate_limited", re.compile(r"^Rate limited \((?P<code>\d+)\)\. Sleeping (?P<secs>[\d.]+)s")),
    ("panopto_auth", re.compile(r"Panopto LTI handshake OK")),
]

BRIDGED = re.compile(r"^\[(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\] "
                     r"\[(?P<logger>[\w.]+)\] (?P<msg>.*)$")

# Warnings the app emits as part of normal operation on these courses. Anything
# NOT on this list is surfaced. The list is deliberately short and specific -
# a broad pattern here would hide the next real regression.
BENIGN_WARNINGS = (
    "Hybrid Fetch: Found",                 # restricted Files tab; app compensates
    "Page-stub fallback: resolved",        # Pages list restricted; app compensates
    "Files tab restricted for",            # same condition, stated once per course
    "Catch-All Phase Error",               # the Files tab 403 reaching the catch-all
    "ignoring embedded stale id",          # Panopto link carries an outdated id
    "Invalid color passed for",            # Streamlit 1.51 sidebar theme noise
    "Updated manifest entry",              # routine: a conversion moved a row
    # The RECOVERY working, not a failure. When an Office app dies mid-file
    # (-600, or -609 connectionInvalid) the bridge relaunches it and retries
    # that one file; both halves of that are logged. Reporting the warning
    # trains a reader to treat a successful self-heal as a defect - and the
    # pair is what proves the retry ran at all. A retry that FAILS is reported
    # by its own error line, which is not benign and is not listed here.
    "was not usable",                      # ...relaunching and retrying <file> once
    "recovered after a crash",             # ...<file> converted on the retry
    # A teacher-locked Canvas file. Permanent, Canvas-side, nothing the app can
    # do, and it already reports it precisely ("The teacher has locked this file
    # on Canvas"). Course 43660 carries two. Surfacing them every run trains a
    # reader to skim past findings, which is the one thing this suite cannot
    # afford - the CONDITION is still visible in the run's error count.
    "[Locked File]",
    # Panopto discovery LAUNCHES every ExternalTool item and sees where it
    # lands, because a module item carries only the generic tool URL and there
    # is no way to know from Canvas alone. Landing somewhere else is the normal
    # NEGATIVE result of that strategy, not a failure - course 45899's twelve
    # items are Alma library citations and every one of them says so.
    #
    # This one message accounted for 48 of the 59 medium findings on a 37-row
    # re-check. Left in, it buries the real ones; the app is behaving exactly
    # as designed, and a genuine auth failure looks different ("TotalNumber 0",
    # "no folder grants") and is still surfaced.
    "LTI handshake did not reach a Panopto host",
    # The Files tab is 403 for the student on several courses. The app has a
    # documented hybrid fetch for precisely this and says so on the line above;
    # the condition is already reported once per course as an observation.
    "Files tab listing failed, falling back to",
)


# A SUMMARY line reporting zero failures is the opposite of a failure. Covers
# both shapes the app writes: "Errors: 0" and the Panopto batch line's
# "failed=0". Without it, `Panopto batch done: found=36 downloaded=36
# transcribed=0 skipped=0 failed=0` was flagged as suspicious purely because
# the word "failed" appeared in it - a perfect run reported as a problem.
# A NON-zero count still matches the heuristic and is still surfaced.
_ZERO_FAILURES = re.compile(r"\b(?:failed|failures|errors?)\s*[:=]\s*0\b", re.I)


@dataclass
class LogEvent:
    ts: str
    kind: str
    raw: str
    line_no: int
    data: dict = field(default_factory=dict)


@dataclass
class ParsedLog:
    path: str
    events: list[LogEvent] = field(default_factory=list)
    tracebacks: list[dict] = field(default_factory=list)
    unmatched: int = 0
    unmatched_samples: list[dict] = field(default_factory=list)
    total_lines: int = 0
    # Raw "ERROR [kind] ..." lines, counted off the text rather than the event
    # grammar - see _error_lines for why that independence is load-bearing.
    error_lines: list[dict] = field(default_factory=list)

    def of(self, *kinds: str) -> list[LogEvent]:
        ks = set(kinds)
        return [e for e in self.events if e.kind in ks]

    def last(self, kind: str) -> LogEvent | None:
        for e in reversed(self.events):
            if e.kind == kind:
                return e
        return None


def parse(path: str | Path) -> ParsedLog:
    p = Path(path)
    out = ParsedLog(path=str(p))
    if not p.is_file():
        return out

    raw = p.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    out.total_lines = len(lines)
    out.error_lines = _error_lines(raw)

    i = 0
    cur_ts = ""
    while i < len(lines):
        line = lines[i]
        m = re.match(TS + r"\s?(.*)$", line)
        if m:
            cur_ts, body = m.group(1), m.group(2)
        else:
            body = line

        # A traceback block spans lines and must be consumed whole, or its
        # first line is filed as an ordinary message and the rest as noise.
        if body.strip() == "--- traceback ---" or "--- traceback ---" in body:
            tb, j = [], i + 1
            while j < len(lines) and not lines[j].startswith("-----------------"):
                tb.append(lines[j])
                j += 1
            out.tracebacks.append({"ts": cur_ts, "line_no": i + 1,
                                   "text": "\n".join(tb)[:4000]})
            i = j + 1
            continue

        matched = False
        bm = BRIDGED.match(body)
        payload = bm.group("msg") if bm else body
        base = {"level": bm.group("level"), "logger": bm.group("logger")} if bm else {}

        for kind, pat in PATTERNS:
            pm = pat.search(payload)
            if pm:
                out.events.append(LogEvent(cur_ts, kind, line[:600], i + 1,
                                           {**base, **pm.groupdict()}))
                matched = True
                break

        if not matched:
            if bm and bm.group("level") in ("WARNING", "ERROR", "CRITICAL"):
                out.events.append(LogEvent(cur_ts, "bridged_" + bm.group("level").lower(),
                                           line[:600], i + 1,
                                           {**base, "msg": payload[:400]}))
            # Match the failure words only where a MESSAGE would put them, never
            # inside a path. Course material is full of legitimate names like
            # "Forelæsning 7. Error-handling, Moduler", and matching those made
            # every conversion of that folder look like a failure.
            elif re.search(r"(?:^|[:\s])(Traceback|Exception|ERROR|Failed|failed)\b",
                           payload.split(" -> ")[0].split(" → ")[0]) \
                    and not _ZERO_FAILURES.search(payload) \
                    and not re.search(r"[\\/][^\\/]*\b(Error|Failed)\b", payload):
                out.events.append(LogEvent(cur_ts, "suspicious", line[:600], i + 1,
                                           {"msg": payload[:400]}))
            elif bm:
                # A bridged INFO record with no specific pattern. Recognised, not
                # unmatched: these are routine progress notes from our own
                # modules, and counting them as "grammar miss" would drown the
                # signal ``unmatched`` exists to carry.
                out.events.append(LogEvent(cur_ts, "info", line[:600], i + 1,
                                           {**base, "msg": payload[:400]}))
            elif not payload.strip():
                pass
            else:
                out.unmatched += 1
                if len(out.unmatched_samples) < 25:
                    out.unmatched_samples.append({"line": i + 1, "text": payload[:200]})
        i += 1

    return out


_LOCKED_RE = re.compile(r"\[Locked File\][^:]*::\s*(?P<name>[^:]+?)\s*::")


def _locked_names(pl: "ParsedLog") -> list[str]:
    """Filenames the app reported as locked by the teacher on Canvas.

    The app writes these as::

        ERROR [Locked File] <course> :: <filename> :: The teacher has locked ...

    Pulled out by name so a later check can say WHY a file is missing instead of
    only that it is. Course 43660 carries two, permanently.
    """
    names = []
    for e in pl.events:
        m = _LOCKED_RE.search(e.raw)
        if m:
            nm = m.group("name").strip()
            if nm and nm not in names:
                names.append(nm)
    return names


# Every error the engine counts, it also prints with this prefix - "ERROR
# [Locked File]", "ERROR [Discussion Dispatch Error]", and so on.
_ERROR_LINE_RE = re.compile(r"ERROR\s+\[(?P<kind>[^\]]+)\]\s*(?P<msg>.*)")


def _error_lines(raw: str) -> list[dict]:
    """The errors a course's log slice reports IN ITS OWN RIGHT.

    This exists to be independent of two things at once, and it has to be both.

    It is independent of the **grammar**: counted straight off the raw text, so
    an error kind no PATTERN recognises still counts. That is not hypothetical -
    ``ERROR [Discussion Dispatch Error]`` reaches the event list only as
    ``suspicious``, and ``ERROR [Locked File]`` only as a locked-name match, so
    every error in the 2026-07-28 matrix was invisible to ``pl.of("error")``,
    which returned ``[]`` on all 73 rows.

    It is independent of the **app's own counter**, which is the point. The
    engine's ``Errors: N`` on the ``Course Finished`` line accumulates across
    the whole batch, so the second course of a two-course run inherits the
    first's total. Comparing this count against that one is what tells those two
    situations apart - and reading the counter alone made the audit file 32 HIGH
    "delivery" findings against courses that had not failed at anything.
    """
    out = []
    for n, line in enumerate(raw.splitlines(), 1):
        m = _ERROR_LINE_RE.search(line)
        if m:
            out.append({"line": n, "kind": m.group("kind").strip(),
                        "msg": m.group("msg").strip()[:300]})
    return out


_FILE_DOWNLOAD_URL = re.compile(r"/files/(\d+)/download")


def _fetch_starts_by_file_id(pl: ParsedLog) -> dict:
    """``{canvas file id: how many times this run STARTED downloading it}``.

    Attempt > 1 is a retry of the SAME download - a rate limit, a 5xx, a
    dropped connection - and must not be counted, or every flaky network makes
    the duplicate-fetch check fire. Only a fresh ``Attempt 1`` for an id that
    already had one means two phases both went to the network for it.
    """
    out: dict[str, int] = {}
    for e in pl.of("request_url"):
        try:
            if int(e.data.get("n", 1)) != 1:
                continue
        except (TypeError, ValueError):
            continue
        m = _FILE_DOWNLOAD_URL.search(e.data.get("url", "") or "")
        if m:
            out[m.group(1)] = out.get(m.group(1), 0) + 1
    return out


def summarize(pl: ParsedLog) -> dict:
    """A flat, comparable digest of one log file."""
    saved = pl.of("file_saved")
    bytes_saved = sum(int(e.data.get("bytes", 0)) for e in saved)
    statuses: dict[str, int] = {}
    for e in pl.of("http_status"):
        statuses[e.data["code"]] = statuses.get(e.data["code"], 0) + 1

    analysis = pl.last("analysis_complete")
    totals = pl.last("sync_totals")
    finished = pl.of("course_finished")

    unexpected = []
    for e in pl.of("bridged_warning", "bridged_error", "bridged_critical",
                   "error", "suspicious"):
        msg = e.data.get("msg", e.raw)
        if not any(b in msg for b in BENIGN_WARNINGS):
            # `raw` carries the ORIGINAL line, level marker and all. `msg` is
            # the payload with the `[LEVEL] [module]` prefix already stripped,
            # so a consumer that needs to tell a bridged INFO progress note from
            # a real outcome cannot do it from `msg` alone - and a check written
            # against `msg` for that purpose silently never fires.
            unexpected.append({"line": e.line_no, "kind": e.kind, "msg": msg[:300],
                               "raw": e.raw[:400]})

    return {
        "path": pl.path,
        "total_lines": pl.total_lines,
        "unmatched_lines": pl.unmatched,
        "unmatched_samples": pl.unmatched_samples,
        "tracebacks": len(pl.tracebacks),
        "traceback_text": [t["text"][:1500] for t in pl.tracebacks[:5]],
        "files_saved": len(saved),
        "bytes_saved": bytes_saved,
        "http_status_counts": statuses,
        "skipped_existing": len(pl.of("skip_existing")),
        # Files placed from a copy this run already had (one Canvas file, one
        # fetch). They are writes with no "File Saved" line, so they belong in
        # any count of what the app claims to have delivered.
        "files_placed": len(pl.of("file_placed")),
        "catchall_deferred": len(pl.of("catchall_defer")),
        # Bandwidth is only the visible half: two phases fetching one Canvas
        # file means two copies on disk, and the manifest can describe only one
        # of them. `request_url` had been parsed all along with nothing reading
        # it, so the original duplicate was found by hand.
        "fetch_starts_by_file_id": _fetch_starts_by_file_id(pl),
        # Recordings the user's max-file-size setting excluded, by title, and
        # the batch's own closing tally.
        "panopto_size_skipped": sorted({
            e.data.get("title", "") for e in pl.of("panopto_size_skip")} - {""}),
        "panopto_batch": (pl.last("panopto_batch_done").data
                          if pl.last("panopto_batch_done") else None),
        "secondary_saved": len(pl.of("secondary_saved")),
        "links_created": len(pl.of("link_created")),
        "courses_finished": [
            {"course": e.data["course"], "items": int(e.data["items"]),
             "errors": int(e.data["errors"])} for e in finished],
        "download_complete": [
            {"course": e.data["course"], "items": int(e.data["items"]),
             "mb": float(e.data["mb"])} for e in pl.of("download_complete")],
        "analysis": (analysis.data if analysis else None),
        "analysis_rows": _rows_by_cat(pl),
        "analysis_row_detail": _row_detail(pl),
        "sync_planned": [e.data for e in pl.of("sync_plan_row")],
        "sync_ok": [e.data["name"] for e in pl.of("sync_ok")],
        "sync_synced": [e.data["name"] for e in pl.of("sync_synced")],
        "sync_totals": (totals.data if totals else None),
        "quick_sync": (pl.last("qs_summary").data if pl.last("qs_summary") else None),
        # "Mode: Quick Sync" / "Mode: Analyze, Review & Sync". The pattern has
        # always been parsed; nothing surfaced it, so the only Quick-Sync
        # signal a check could reach was the presence of the QS summary line -
        # true, but incidental. Which mode ran decides what the run was even
        # ALLOWED to do: Quick Sync declines locally-edited and locally-deleted
        # files by design.
        "sync_mode": (pl.last("sync_mode").data.get("mode")
                      if pl.last("sync_mode") else None),
        "converters": (pl.last("pp_converters").data.get("list")
                       if pl.last("pp_converters") else None),
        "panopto": _panopto(pl),
        "errors": [e.data.get("msg", e.raw)[:300] for e in pl.of("error")],
        # What this course's log says failed, in its own right - as opposed to
        # `courses_finished[].errors`, which is the engine's BATCH-cumulative
        # counter. The two disagreeing is itself the signal (see _error_lines).
        "error_lines": pl.error_lines[:20],
        "error_line_count": len(pl.error_lines),
        "error_kinds": sorted({e["kind"] for e in pl.error_lines}),
        # Files Canvas itself refuses to serve. Extracted by NAME so a discovery
        # gap can be attributed rather than merely counted: "2 files exist on
        # Canvas but were never tracked" and "2 files the teacher locked" are
        # the same number and completely different news.
        "locked_files": _locked_names(pl),
        "unexpected": unexpected,
        "cancelled": bool(pl.of("cancel")),
        "hybrid_gap": [int(e.data["count"]) for e in pl.of("hybrid_gap")],
        # The engine's own echo of the parameters it is about to run with. The
        # size cap is set in a global dialog far from the download page, so this
        # line is the only place a run states the value it actually used.
        "download_params": (pl.last("download_params").data
                            if pl.last("download_params") else None),
        "panopto_tx_unavailable": bool(pl.of("panopto_tx_unavailable")),
    }


def _rows_by_cat(pl: ParsedLog) -> dict:
    """Every spelling of every classified file, keyed by the app's own tag.

    A row carries up to two names - the Canvas DISPLAY name and, where it
    differs, the LOCAL path - and both are returned, because a consumer
    matching a fixture cannot know which one the app happened to use. The two
    are the same file in the same category, so a duplicate key can never invent
    an ambiguity; it only widens what will match.

    Use `analysis_row_detail` when you need one entry PER ROW (counting), and
    this when you need every name that identifies a row (matching). Conflating
    them double-counts every row that carries a path.
    """
    out: dict[str, list[str]] = {}
    for e in pl.of("analysis_row"):
        bucket = out.setdefault(e.data["cat"], [])
        for v in (e.data.get("name"), e.data.get("local")):
            if v and v not in bucket:
                bucket.append(v)
    for e in pl.of("qs_select"):
        bucket = out.setdefault("QS-" + e.data["cat"], [])
        for v in (e.data.get("name"), e.data.get("local")):
            if v and v not in bucket:
                bucket.append(v)
    for e in pl.of("qs_skip"):
        bucket = out.setdefault("QS-SKIP-" + e.data["cat"], [])
        for v in (e.data.get("name"), e.data.get("local")):
            if v and v not in bucket:
                bucket.append(v)
    return out


def _row_detail(pl: ParsedLog) -> dict:
    """One entry per analysis ROW: ``{tag: [{"display", "local"}, ...]}``.

    The counting view. `_rows_by_cat` returns every NAME, which is two per row
    wherever the local path differs - so counting that would report twice the
    files the app said it classified, and the counts-vs-rows invariant that
    guards this oracle would fire on every healthy run.
    """
    out: dict[str, list[dict]] = {}
    for e in pl.of("analysis_row"):
        out.setdefault(e.data["cat"], []).append(
            {"display": e.data.get("name") or "", "local": e.data.get("local") or ""})
    return out


def _panopto(pl: ParsedLog) -> dict:
    disc = pl.last("panopto_discovered")
    batch = pl.last("panopto_batch")
    return {
        "discovery": (disc.data if disc else None),
        "batch": (batch.data if batch else None),
        "downloaded": [{"name": e.data["name"], "mb": float(e.data["mb"])}
                       for e in pl.of("panopto_downloaded")],
        "transcribed": [{"name": e.data["name"], "segments": int(e.data["segments"]),
                         "lang": e.data["lang"]} for e in pl.of("panopto_transcribed")],
        "transcribe_ok": len(pl.of("panopto_transcribe_ok")),
    }


def parse_and_summarize(path: str | Path) -> dict:
    return summarize(parse(path))


if __name__ == "__main__":
    import sys
    print(json.dumps(parse_and_summarize(sys.argv[1]), indent=2, ensure_ascii=False))
