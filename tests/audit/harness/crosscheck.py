"""Reconcile the five oracles and emit findings.

Every check here answers "do two independent views of the same fact agree?".
Nothing in this module asks the application anything; it only compares what has
already been observed. That separation is what keeps a check honest - a check
that re-derives an expectation by calling the code under test can only ever
confirm that the code agrees with itself.

The checks are grouped by when they run:

    invariants()    after EVERY run, whatever it was. These are the properties
                    that must hold unconditionally, and most of them encode a
                    failure this project has actually shipped.
    download_run()  after a download, against the scenario's declared config.
    sync_run()      after a sync, against the seeder's predicted categories.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .findings import Finding, disagreement, observation

# --------------------------------------------------------------------------
# The post-processing contract, restated independently of the code.
#
#   sources           extensions the converter consumes
#   produces          extension it writes beside (or instead of) the source
#   removes_source    whether the original is deleted
#
# Restated rather than imported on purpose: importing converters/post_processing
# would make the expectation agree with the implementation by construction. The
# values were read off the pipeline on 2026-07-27 and any drift between this
# table and the code is itself a finding worth raising.
#
# The two that surprise people, and that both matter to sync:
#   * convert_word is LEGACY word only - .doc/.rtf/.odt. A .docx is never
#     converted, so expecting a PDF beside every Word file is wrong.
#   * convert_excel DELETES the .xlsx once the PDF exists. A later sync must
#     therefore not report the workbook as deleted locally.
# --------------------------------------------------------------------------
CONVERTERS = {
    "convert_pptx":  {"sources": {".ppt", ".pptx", ".pptm", ".pot", ".potx"},
                      "produces": ".pdf", "removes_source": True},
    "convert_word":  {"sources": {".doc", ".rtf", ".odt"},
                      "produces": ".pdf", "removes_source": True},
    "convert_excel": {"sources": {".xlsx", ".xls", ".xlsm"},
                      "produces": ".pdf", "removes_source": True,
                      "sidecar": "_Data.txt"},
    "convert_html":  {"sources": {".html"}, "produces": ".md", "removes_source": False},
    "convert_code":  {"sources": {".py", ".java", ".c", ".cpp", ".cs", ".h", ".hpp",
                                  ".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".php",
                                  ".rb", ".swift", ".go", ".rs", ".kt", ".scala", ".sh",
                                  ".bash", ".zsh", ".bat", ".ps1", ".pl", ".pm", ".r",
                                  ".rmd", ".m", ".sql", ".dart", ".lua", ".asm", ".vba",
                                  ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml",
                                  ".toml", ".ini", ".cfg", ".conf", ".env", ".log",
                                  ".mdx", ".vue", ".svelte"},
                      "produces": ".txt", "removes_source": True},
    "convert_urls":  {"sources": {".url", ".webloc"},
                      "produces": None, "removes_source": True,
                      "aggregate": "Compiled_External_Links.txt"},
    "convert_video": {"sources": {".mp4", ".mov", ".mkv", ".avi", ".m4v"},
                      "produces": ".mp3", "removes_source": True},
    "convert_zip":   {"sources": {".zip", ".tar", ".gz"},
                      "produces": None, "removes_source": True, "extracts": True},
}

# The "Slides & PDFs" filter. Restated here for the same reason as above.
STUDY_EXTS = {".pdf", ".ppt", ".pptx", ".pptm", ".doc", ".docx", ".odt", ".rtf"}

SECONDARY_UI_TO_ENTITY = {
    "dl_assignments": "assignment", "dl_syllabus": "syllabus",
    "dl_announcements": "announcement", "dl_discussions": "discussion",
    "dl_quizzes": "quiz", "dl_submissions": "submission",
}


def normalise_expect(expect: dict) -> dict:
    """One shape for the requested configuration, whatever the caller passed.

    Callers legitimately hold it two ways - the FLAT form a matrix row is
    (``{"convert_zip": true, "max_file_size": 5}``) and the NESTED form the
    hand-written scenarios use (``{"converters": {...}, "max_file_size_mb": 5}``)
    - and checks were reading whichever the author happened to have in mind.

    **Three checks were dead because of it, and every one failed SILENTLY by
    passing.** ``_conversions`` and ``_count_coherence`` read
    ``expect["converters"]``, absent from a matrix row, so one never ran and the
    other ran when it should not have; ``_size_limit`` and ``_discovery_gap``
    read ``max_file_size_mb`` while the matrix factor is ``max_file_size``, so
    the entire size-cap dimension - half the rows - was checked by nothing. A
    check whose correctness depends on the caller's spelling is a check that
    goes quiet the first time somebody adds a caller, so the shapes are
    reconciled once, here, where every check has to come through.

    Both directions are filled in, so a check may read either spelling.
    """
    out = dict(expect)

    convs = dict(out.get("converters") or {})
    for k, v in out.items():
        if k.startswith("convert_"):
            convs.setdefault(k, v)
    if convs:
        out["converters"] = convs
        for k, v in convs.items():
            out.setdefault(k, v)

    sec = dict(out.get("secondary") or {})
    for k, v in out.items():
        if k.startswith("dl_"):
            sec.setdefault(k, v)
    if sec:
        out["secondary"] = sec
        for k, v in sec.items():
            out.setdefault(k, v)

    pan = dict(out.get("panopto") or {})
    for k, v in out.items():
        if k.startswith("pan_"):
            pan.setdefault(k, v)
    if pan:
        # The layout is spelled `pan_layout` by a matrix row and `layout` by the
        # contract and the hand-written scenarios. Both are filled in, because
        # `_layout` read only the second: with `mode=flat, pan_layout=separate`
        # it did not recognise the "Panopto Recordings" folder the run had been
        # explicitly asked for, and reported the app's correct behaviour as
        # "Flat organisation requested but 1 subfolder(s) were created".
        if "pan_layout" in pan and "layout" not in pan:
            pan["layout"] = pan["pan_layout"]
        elif "layout" in pan and "pan_layout" not in pan:
            pan["pan_layout"] = pan["layout"]
        out["panopto"] = pan
        for k, v in pan.items():
            out.setdefault(k, v)

    cap = out.get("max_file_size_mb", out.get("max_file_size"))
    out["max_file_size_mb"] = int(cap) if cap else None
    out["max_file_size"] = out["max_file_size_mb"]
    return out


class Evidence:
    """Everything observed about one course folder after one run."""

    def __init__(self, *, folder, disk=None, db=None, log=None, canvas=None,
                 ui=None, expect=None, scenario="", course="", step="",
                 batch_log=None):
        self.folder = Path(folder) if folder else None
        self.disk = disk or {}
        self.db = db or {}
        self.log = log or {}
        self.batch_log = batch_log or {}
        self.canvas = canvas or {}
        self.ui = ui or {}
        self.expect = normalise_expect(expect or {})
        self.scenario = scenario
        self.course = course or (self.folder.name if self.folder else "")
        self.step = step

    def _f(self, **kw) -> Finding:
        kw.setdefault("scenario", self.scenario)
        kw.setdefault("course", self.course)
        kw.setdefault("step", self.step)
        return Finding(**kw)

    def _d(self, a, b, title, **kw) -> Finding:
        kw.setdefault("scenario", self.scenario)
        kw.setdefault("course", self.course)
        kw.setdefault("step", self.step)
        return disagreement(a, b, title, **kw)


# ==========================================================================
# always-on invariants
# ==========================================================================

def invariants(ev: Evidence) -> list[Finding]:
    out: list[Finding] = []
    disk, db, log = ev.disk, ev.db, ev.log

    # -- the app crashed, or nearly did ------------------------------------
    if log.get("tracebacks"):
        out.append(ev._f(
            title=f"{log['tracebacks']} traceback(s) in the debug log",
            severity="critical", category="robustness", oracles=("O2",),
            detail="An unhandled exception was logged during the run. Even when "
                   "the run appears to finish, a swallowed exception means some "
                   "branch did not execute.",
            evidence={"tracebacks": log.get("traceback_text", [])[:3],
                      "log": log.get("path")}))

    for u in log.get("unexpected", [])[:25]:
        sev = "high" if u["kind"] in ("bridged_error", "bridged_critical", "error") else "medium"
        out.append(ev._f(
            title=f"Unexpected {u['kind']} in debug log: {u['msg'][:90]}",
            severity=sev, category="robustness", oracles=("O2",),
            detail=u["msg"], evidence={"line": u["line"], "log": log.get("path")}))

    # A grammar that suddenly stops matching is how a log-based check goes
    # quietly blind, so the parser's own miss rate is monitored.
    if log.get("total_lines", 0) > 50:
        miss = log["unmatched_lines"] / log["total_lines"]
        if miss > 0.25:
            out.append(observation(
                title=f"Debug log parser missed {miss:.0%} of lines",
                detail="The log may have changed shape; log-derived checks could "
                       "be silently under-reporting. Review the samples and extend "
                       "PATTERNS in oracles/log.py.",
                scenario=ev.scenario, course=ev.course,
                evidence={"samples": log.get("unmatched_samples", [])[:10]}))

    if not disk.get("exists"):
        return out

    # -- leftovers and corruption ------------------------------------------
    # A seeded run creates .part files on purpose; counting the fixture that
    # proves the app ignores them as proof that it does not is exactly backwards.
    _seeded_partials = {_key(p) for p in (ev.expect.get("expected_partials") or [])}
    if _seeded_partials:
        disk = {**disk, "partials": [p for p in disk.get("partials", [])
                                     if _key(p.get("rel", p) if isinstance(p, dict) else p)
                                     not in _seeded_partials]}
    if disk.get("partials"):
        out.append(ev._f(
            title=f"{len(disk['partials'])} partial-write artifact(s) left on disk",
            severity="high", category="robustness", oracles=("O3",),
            detail="A `.part` file after the run means an atomic write was "
                   "abandoned without cleanup. The next analysis must ignore it, "
                   "and the user sees a junk file in their course folder.",
            evidence={"files": disk["partials"][:20]}))

    zero = [z for z in disk.get("zero_bytes", []) if not z.endswith(".url")]
    if zero:
        out.append(ev._d("O3", "O5",
            title=f"{len(zero)} zero-byte file(s) delivered",
            severity="high", category="delivery",
            detail="A zero-byte file is indistinguishable from a successful "
                   "download in the UI and in the manifest, but it is unusable. "
                   "Cross-check each against its Canvas size before dismissing.",
            evidence={"files": zero[:20]},
            scenario=ev.scenario, course=ev.course))

    if disk.get("long_paths"):
        out.append(observation(
            title=f"{len(disk['long_paths'])} path(s) exceed 255 characters",
            detail="Windows APIs without the \\\\?\\ prefix fail at 260. The engine "
                   "uses make_long_path, so this is recorded to confirm the guard "
                   "is exercised rather than as a defect.",
            scenario=ev.scenario, course=ev.course,
            evidence={"files": disk["long_paths"][:10]}))

    # -- manifest vs disk (O4 <-> O3) --------------------------------------
    if db.get("exists"):
        from .oracles.db import reconcile_with_disk
        rec = reconcile_with_disk(db, disk)
        ev.reconciliation = rec
        if rec.get("applicable"):
            # A converter that CONSUMES its source leaves the manifest row
            # pointing at a path that no longer exists, on purpose: the engine
            # documents a bypass that treats a missing .url/.webloc or archive
            # as "converted away" rather than deleted. Flagging those would
            # report the bypass working as a broken manifest, and on a run with
            # convert_urls enabled that is 25 rows of pure noise.
            on = _converters_on(ev)
            consumed_exts = set()
            for key, spec in CONVERTERS.items():
                if on.get(key) and spec["removes_source"]:
                    consumed_exts |= spec["sources"]
            # Fixtures that deliberately remove or rename a tracked file leave
            # its row pointing at nothing - that IS the scenario, and after a
            # sync where the user left "deleted locally" unchecked it is also
            # the correct end state.
            seeded_missing = {_key(p) for p in
                              (ev.expect.get("expected_missing_rows") or [])}
            miss = [m for m in rec["missing_on_disk"]
                    if Path(m["local_path"]).suffix.lower() not in consumed_exts
                    and _key(m["local_path"]) not in seeded_missing]
            if consumed_exts and len(miss) < len(rec["missing_on_disk"]):
                out.append(observation(
                    title=f"{len(rec['missing_on_disk']) - len(miss)} manifest row(s) "
                          f"describe files a converter consumed",
                    detail="Expected: the engine's bypass treats a missing source of "
                           "a source-consuming converter as 'converted away'. Listed "
                           "so the rows are visible without being counted as defects.",
                    scenario=ev.scenario, course=ev.course,
                    evidence={"exts": sorted(consumed_exts)}))
            if miss:
                out.append(ev._d("O4", "O3",
                    title=f"{len(miss)} manifest row(s) point at files that do not exist",
                    severity="high", category="persistence",
                    detail="The app believes these files are present. On the next "
                           "sync each reads as 'deleted locally', which is unchecked "
                           "by default and always skipped by Quick Sync - so they "
                           "are never re-downloaded and never mentioned again.",
                    evidence={"rows": miss[:20]},
                    scenario=ev.scenario, course=ev.course))

            # A seeded run deliberately leaves decoys, duplicates and the
            # student's own files unclaimed. Excluding them keeps this invariant
            # pointed at genuine orphans instead of the fixtures that prove the
            # analyzer was right to ignore them.
            exempt = {_key(p) for p in (ev.expect.get("expected_untracked") or [])}
            exempt |= _conversion_aggregates(ev)
            # Panopto outputs are tracked in their OWN table: a recording has no
            # Canvas file id, so it can never have a sync_manifest row. Without
            # this, a flawless run that downloaded 36 of 36 recordings reported
            # "36 content files on disk with no manifest row" - the app's
            # success counted as its failure.
            exempt |= {_key(r.get("local_path", ""))
                       for r in (ev.db.get("panopto_rows") or [])
                       if isinstance(r, dict) and r.get("local_path")}
            sidecars = _conversion_sidecars(ev)
            forked = _new_version_originals(ev)
            untracked = [u for u in rec["untracked_on_disk"]
                         if not u["new_version"] and _key(u["rel"]) not in exempt
                         and _key(u["rel"]) not in forked
                         and not (sidecars and
                                  u["rel"].lower().endswith(sidecars))]

            # Archive extraction legitimately produces thousands of files the
            # manifest never tracks - it tracks the ARCHIVE. Counting them as
            # orphans buried the real findings under 21,631 entries on the
            # first real run. They are reported as a count instead, because
            # "how much did unpacking add" is worth knowing.
            # Inferred from the FOLDER, never from what the caller declared.
            # This used to be gated on `expect.converters.convert_zip`, which
            # made the exemption depend on the check being handed a config it
            # does not otherwise need: `check download` passes one, `check sync`
            # does not, so the identical folder reported 1 orphan through one
            # command and 21,641 through the other. Whether an archive was
            # unpacked is a property of the manifest and the directory tree, and
            # _infer_extracted_roots reads exactly that - it needs BOTH an
            # archive manifest row and a directory of the same stem, so it can
            # never exempt files that did not come out of one.
            roots = set(ev.expect.get("extracted_roots") or []) \
                or _infer_extracted_roots(ev)
            prefixes = tuple(_key(r) + "/" for r in roots)
            if prefixes:
                # Partition by KEY, not by dict membership. `u not in inside`
                # over two 20k lists of dicts is ~450M comparisons and
                # depends on dict equality holding across the two passes -
                # slow, and silently a no-op if either assumption breaks.
                kept, inside = [], 0
                for u in untracked:
                    if _key(u["rel"]).startswith(prefixes):
                        inside += 1
                    else:
                        kept.append(u)
                if inside:
                    untracked = kept
                    out.append(observation(
                        title=f"{inside} file(s) unpacked from archives are "
                              f"untracked, as designed",
                        detail="The manifest tracks the archive, not its "
                               "contents.",
                        scenario=ev.scenario, course=ev.course,
                        evidence={"roots": sorted(roots)[:12]}))
            if untracked:
                out.append(ev._d("O3", "O4",
                    title=f"{len(untracked)} content file(s) on disk with no manifest row",
                    severity="high", category="persistence",
                    detail="Each of these will be offered as a NEW file on every "
                           "future sync unless the analyzer's adoption tiers reclaim "
                           "it. This is the 'wrongfully shows up as new' failure.",
                    evidence={"files": untracked[:20]},
                    scenario=ev.scenario, course=ev.course))

            if rec["duplicate_local_paths"]:
                out.append(ev._f(
                    title=f"{len(rec['duplicate_local_paths'])} local path(s) claimed "
                          f"by more than one manifest row",
                    severity="high", category="persistence", oracles=("O4",),
                    detail="Two Canvas ids resolving to one file means one of them "
                           "can never be up to date, and an update to either "
                           "overwrites the other.",
                    evidence={"paths": dict(list(rec["duplicate_local_paths"].items())[:10])}))

            # An edited-locally fixture MUST differ from its recorded md5 and
            # size - that divergence is what the app is being asked to notice,
            # and preserving it is the correct outcome when the row is left
            # unchecked. Counting it here reported the product's data-safety
            # guarantee working as two persistence defects.
            # TWO lists, because the seeder perturbs the two independently.
            # `_backdate` falsifies the recorded SIZE on every fixture that
            # needs Canvas to look newer (clean_update, edited_update,
            # readonly_target); only edited_update also rewrites the BYTES.
            # Filtering both halves by the md5 list left readonly_target's size
            # unsuppressed - 6 findings a run, all the seeder's own doing - and
            # suppressed clean_update's md5, whose whole premise is that the
            # recorded md5 STILL MATCHES, so a genuine mismatch there could not
            # have been reported at all.
            md5_drift = {_key(p) for p in (ev.expect.get("expected_md5_drift") or [])}
            size_drift = md5_drift | {
                _key(p) for p in (ev.expect.get("expected_size_drift") or [])}
            size_bad = [r for r in rec["size_mismatch"]
                        if _key(r.get("local_path", "")) not in size_drift]
            md5_bad = [r for r in rec["md5_mismatch"]
                       if _key(r.get("local_path", "")) not in md5_drift]

            if size_bad:
                out.append(ev._d("O4", "O3",
                    title=f"{len(size_bad)} manifest row(s) record the wrong size",
                    severity="medium", category="persistence",
                    detail="original_size decides whether the next Canvas change is "
                           "treated as a real update or vetoed as a metadata touch.",
                    evidence={"rows": size_bad[:15]},
                    scenario=ev.scenario, course=ev.course))

            if md5_bad:
                out.append(ev._d("O4", "O3",
                    title=f"{len(md5_bad)} file(s) differ from their recorded md5",
                    severity="medium", category="persistence",
                    detail="original_md5 is what classifies the next update as clean "
                           "(overwrite) or modified (_NewVersion). A wrong baseline "
                           "silently decides whether the user's edits survive.",
                    evidence={"rows": md5_bad[:15]},
                    scenario=ev.scenario, course=ev.course))

    # -- UI health ---------------------------------------------------------
    out.extend(ui_health(ev))
    return out


def ui_health(ev: Evidence) -> list[Finding]:
    out: list[Finding] = []
    ui = ev.ui or {}
    screen = ui.get("screen", {})
    for exc in screen.get("exceptions", []):
        out.append(ev._f(
            title="Streamlit exception rendered on screen",
            severity="critical", category="robustness", oracles=("O1",),
            detail=exc.get("text", "")[:1200],
            evidence={"capture": ui.get("name")}))
    console = ui.get("console", {})
    errs = console.get("errors", [])
    if errs:
        out.append(ev._f(
            title=f"{len(errs)} uncaught browser error(s) on {ui.get('name', 'screen')}",
            severity="medium", category="robustness", oracles=("O1",),
            detail="; ".join(e.get("text", "")[:150] for e in errs[:5]),
            evidence={"errors": errs[:8]}))
    return out


# ==========================================================================
# download
# ==========================================================================

def download_run(ev: Evidence) -> list[Finding]:
    """Compare a finished download against the config it was given and against
    what Canvas actually holds."""
    out: list[Finding] = []
    disk, db, log, snap, expect = ev.disk, ev.db, ev.log, ev.canvas, ev.expect

    out.extend(_contract_written(ev))
    out.extend(_discovery_gap(ev))
    out.extend(_one_fetch_per_file(ev))
    out.extend(_count_coherence(ev))
    out.extend(_layout(ev))
    out.extend(_file_filter(ev))
    out.extend(_size_limit(ev))
    out.extend(_conversions(ev))
    out.extend(_secondary_content(ev))
    out.extend(_panopto_delivery(ev))
    return out


# Outputs the Panopto pass can produce, and the extension each lands as.
PANOPTO_OUTPUTS = {"pan_out_mp3": ".mp3", "pan_out_mp4": ".mp4",
                   "pan_out_txt": ".txt", "pan_out_srt": ".srt"}


def _panopto_items(snap: dict) -> list:
    """Module items that genuinely launch Panopto. Shared with the scheduler."""
    from .matrix import panopto_items
    return panopto_items(snap or {})


def _model_missing(ev: Evidence) -> bool:
    """Did the runner decline to transcribe because nothing was installed?

    Its own words, via the log oracle's ``panopto_tx_unavailable`` pattern.
    The audit pins the model to one that IS installed
    (``paths.provision_config_dir``), so this should never fire - it is here
    because if it ever does, the alternative is fifteen high-severity delivery
    findings against the product for a machine setup problem.
    """
    return bool(ev.log.get("panopto_tx_unavailable"))


def _panopto_delivery(ev: Evidence) -> list[Finding]:
    """O5 -> O4 -> O3 for recordings, which no other check covers.

    Recordings are the one content type with NO Canvas file id, so they live in
    their own ``panopto_manifest`` table and are invisible to every file-based
    check in this module. Three numbers have to agree:

      O5  how many recordings the course exposes (its ExternalTool module items;
          on 43660 all 36 are Panopto, established previously)
      O4  how many the app reached, and how many it recorded per output kind
          (``panopto_manifest``)
      O3  how many files of that kind are actually on disk

    "How many it reached" has TWO sources and neither is always present.
    ``panopto_discovery_cache`` is written only by the SYNC analysis path, as a
    24h cache for Quick Sync and the Today auto-sync; a DOWNLOAD run never
    writes it. Reading it alone reported "nothing was discovered" on a run that
    had just downloaded 36 of 36 - a fabricated high finding on a perfect run.
    So the manifest rows are the fallback, and "nothing discovered" is only
    claimed when both are empty.

    A gap between the first two is a discovery failure - the failure mode this
    project has already shipped once, as "6 of 36 found" when a generic tool
    launch replaced the per-item one. A gap between the last two is a delivery
    failure. They need separating because the count on screen looks equally
    healthy either way.
    """
    out: list[Finding] = []
    wanted = {k for k in PANOPTO_OUTPUTS if ev.expect.get(k)}
    if not wanted or not ev.db.get("exists"):
        return out

    # Transcription is SKIPPED, with a warning and no error, when the configured
    # model is not on disk (panopto/runner.py). Every txt/srt check below would
    # then fire against the product for what is an environment problem - so the
    # environment is reported instead, once, and the transcript outputs are
    # dropped from the comparison rather than judged.
    if _model_missing(ev):
        out.append(observation(
            title="Transcription model is not installed, so txt/srt were skipped",
            detail="The app warns and continues by design. The transcript "
                   "outputs are excluded from the delivery comparison here - "
                   "install the configured model and re-run this row to test "
                   "them.",
            scenario=ev.scenario, course=ev.course))
        wanted -= {"pan_out_txt", "pan_out_srt"}
        if not wanted:
            return out

    # By HOST, not by item type: an ExternalTool is only a recording if it
    # launches Panopto. Course 45899's twelve are Alma library citations, and
    # counting the type would make every row against it report "Panopto found 0
    # of 12" - a high-severity discovery failure invented out of a bibliography.
    expected = len(_panopto_items(ev.canvas))
    kinds = {k: int(v or 0) for k, v in (ev.db.get("panopto_kinds") or {}).items()}
    cached = int(ev.db.get("panopto_discovery_cached") or 0)
    # The most any single output produced is a lower bound on how many
    # recordings the run actually reached.
    discovered = cached or (max(kinds.values()) if kinds else 0)

    # A recording the user's own max-file-size setting excluded was never going
    # to be delivered, so it must leave the denominator - exactly as an
    # over-cap Canvas file does. Lecture videos run 70-300 MB, so a modest cap
    # takes ALL of them: measured on m041 (5 MB cap, course 43660), the app
    # discovered all 36, logged "Panopto size gate: skipping ..." for every one
    # and closed with `found=36 downloaded=0`. Reading only the empty manifest,
    # this check called that a discovery failure - reporting the app for
    # honouring the setting it was given.
    # Read from the batch log when the per-course slice has none: Panopto
    # downloads EVERY course's recordings in one phase, after all discovery,
    # and its size-gate lines name a recording title rather than a course - so
    # they cannot be split per course at all. The row's whole log is the only
    # place the fact exists.
    size_gated = len(ev.log.get("panopto_size_skipped")
                     or ev.batch_log.get("panopto_size_skipped") or [])
    expected = max(0, expected - size_gated)

    if expected and discovered and discovered < expected:
        out.append(ev._d("O5", "O4",
            title=f"Panopto discovery found {discovered} of {expected} recordings",
            severity="high", category="discovery",
            detail="Every ExternalTool module item on this course is a Panopto "
                   "recording. A short count is the per-item launch regressing to "
                   "a generic tool launch - which this project has shipped before "
                   "and which looks like a healthy run on screen.",
            evidence={"expected": expected, "discovered": discovered},
            scenario=ev.scenario, course=ev.course))

    if expected and not discovered:
        out.append(ev._d("O5", "O4",
            title=f"Panopto was requested but nothing was discovered "
                  f"({expected} recordings expected)",
            severity="high", category="discovery",
            detail="A TotalNumber of 0 from the Panopto API means the LTI cookie "
                   "carries no folder grants - the session is authenticated but "
                   "entitled to nothing.",
            scenario=ev.scenario, course=ev.course))

    on_disk = {}
    for f in ev.disk.get("files", []):
        on_disk[f.get("ext", "")] = on_disk.get(f.get("ext", ""), 0) + 1

    for key in sorted(wanted):
        ext = PANOPTO_OUTPUTS[key]
        kind = ext.lstrip(".")
        rows = int(kinds.get(kind, 0) or 0)
        if discovered and not rows:
            out.append(ev._d("O1", "O4",
                title=f"Panopto '{kind}' was selected but no {kind} rows were recorded",
                severity="high", category="delivery",
                detail="The output was requested and recordings were discovered, "
                       "so the manifest should carry one row per recording.",
                evidence={"discovered": discovered, "kinds": kinds},
                scenario=ev.scenario, course=ev.course))
        elif rows and discovered and rows < discovered:
            out.append(ev._d("O4", "O4",
                title=f"Panopto produced {rows} {kind} of {discovered} discovered "
                      f"recordings",
                severity="medium", category="delivery",
                detail="Some recordings did not yield this output. Ignored "
                       "recordings are excluded from the manifest by design, so "
                       "check panopto_ignored before treating this as a failure.",
                evidence={"kinds": kinds, "ignored": len(ev.db.get("panopto_ignored") or [])},
                scenario=ev.scenario, course=ev.course))
        if rows and on_disk.get(ext, 0) < rows:
            out.append(ev._d("O4", "O3",
                title=f"{rows - on_disk.get(ext, 0)} Panopto {kind} row(s) have no "
                      f"file on disk",
                severity="high", category="delivery",
                evidence={"rows": rows, "on_disk": on_disk.get(ext, 0)},
                scenario=ev.scenario, course=ev.course))
    return out


def _contract_written(ev: Evidence) -> list[Finding]:
    """The DB is this project's declared single source of truth for what a
    folder was configured with. If the UI's choices did not reach it, every
    later sync of that folder runs under the wrong contract."""
    out = []
    want, db = ev.expect, ev.db
    if not want or not db.get("exists"):
        return out
    got = db.get("contracts", {})

    sync_c = got.get("sync") or {}
    for key, val in (want.get("converters") or {}).items():
        if key in sync_c and bool(sync_c[key]) != bool(val):
            out.append(ev._d("O1", "O4",
                title=f"Converter '{key}' was set to {val} but the folder contract says {sync_c[key]}",
                severity="high", category="config",
                detail="Sync reads this contract to decide post-processing for "
                       "every future sync of this folder.",
                evidence={"contract": sync_c}, scenario=ev.scenario, course=ev.course))

    sec_c = got.get("secondary") or {}
    for ui_key, want_on in (want.get("secondary") or {}).items():
        db_key = "download_" + ui_key.replace("dl_", "")
        if db_key in sec_c and bool(sec_c[db_key]) != bool(want_on):
            out.append(ev._d("O1", "O4",
                title=f"Canvas Content '{ui_key}' set to {want_on} but contract says {sec_c[db_key]}",
                severity="high", category="config",
                evidence={"contract": sec_c}, scenario=ev.scenario, course=ev.course))

    if want.get("mode") and db.get("download_mode") and db["download_mode"] != want["mode"]:
        out.append(ev._d("O1", "O4",
            title=f"Organisation mode requested '{want['mode']}' but folder records "
                  f"'{db['download_mode']}'",
            severity="high", category="config",
            detail="The recorded mode is what a later sync uses to compute where "
                   "a new file belongs.",
            scenario=ev.scenario, course=ev.course))

    pan_c = got.get("panopto") or {}
    for k, v in (ev.expect.get("panopto") or {}).items():
        if k in pan_c and bool(pan_c[k]) != bool(v):
            out.append(ev._d("O1", "O4",
                title=f"Panopto '{k}' set to {v} but contract says {pan_c[k]}",
                severity="high", category="config", evidence={"contract": pan_c},
                scenario=ev.scenario, course=ev.course))
    return out


# Canvas Content type -> the config toggle that fetches its bodies. A file
# linked only from inside one of these is reachable ONLY if the run asked for
# that type, because the app follows links in bodies it downloads.
_INLINE_SOURCE_TOGGLE = {
    "assignment": "dl_assignments",
    "discussion": "dl_discussions",
    "announcement": "dl_announcements",
    "syllabus": "dl_syllabus",
}


# A file the app reached by following a link inside a Canvas Content body is
# recorded under a SYNTHETIC id, not its Canvas one: `sync_manager.
# make_secondary_id('attachment', fid)` == -(fid + 90_000_000). Course 45899's
# nine assignment/announcement attachments are all stored that way, so a
# `canvas_file_id > 0` filter erased every one of them and the discovery check
# reported nine files "never tracked" on a run whose log shows it fetching each
# one by name. Mapping them back is what makes the check able to see the
# population it exists to police.
_ATTACHMENT_OFFSET = 90_000_000


def tracked_file_ids(db: dict) -> set[int]:
    """Canvas file ids the manifest holds, synthetic attachment rows included."""
    out: set[int] = set()
    for r in db.get("rows", []) or []:
        fid = r.get("canvas_file_id")
        if not isinstance(fid, int):
            continue
        if fid > 0:
            out.add(fid)
        elif abs(fid) > _ATTACHMENT_OFFSET:
            out.add(abs(fid) - _ATTACHMENT_OFFSET)
    return out


def _inline_not_requested(snap: dict, expect: dict) -> set:
    """Inline file ids the run could not have reached, and must not be judged on.

    A file that ALSO appears in the Files tab or on a module is reachable
    without its body, so only the inline-ONLY ones are excluded - the check
    stays exactly as strict as it can honestly be.

    A snapshot taken before ``inline_by_source`` existed cannot say which body
    an id came from, so every inline-only id is excluded. That is the safe
    direction: a stale cache then under-reports, where the alternative is to
    resurrect a high-severity finding that is indistinguishable from a real
    discovery gap.
    """
    reachable = {int(k) for k in (snap.get("files_tab") or {})}
    reachable |= {int(i) for i in snap.get("module_file_ids", [])}
    by_source = snap.get("inline_by_source")
    if by_source is None:
        return {int(i) for i in snap.get("inline_file_ids", [])} - reachable
    out: set = set()
    for source, ids in by_source.items():
        toggle = _INLINE_SOURCE_TOGGLE.get(source)
        if toggle and not expect.get(toggle):
            out |= {int(i) for i in ids}
    return out - reachable


def _discovery_gap(ev: Evidence) -> list[Finding]:
    """O5 vs O4: did the app find every file Canvas exposes?

    This is the check the other four oracles structurally cannot make. It is
    scoped to configurations where every file was requested - under a filter or
    a size cap an absent file is expected, and those are checked separately.
    """
    out: list[Finding] = []
    snap, db, expect = ev.canvas, ev.db, ev.expect
    if not snap or not db.get("exists"):
        return out
    if expect.get("file_filter", "all") != "all" or expect.get("max_file_size_mb"):
        return out

    expected = set(snap.get("expected_file_ids", []))
    expected -= _inline_not_requested(snap, expect)
    locked = {f["id"] for f in snap.get("files_tab", {}).values() if not f["has_url"]}
    expected -= locked

    # A lock that only surfaces ON ACCESS. Measured on 43660: two .pptx files
    # were listed by the Files tab WITH a url, so the snapshot above cannot see
    # they are locked - the app only learns it when the download returns "This
    # file is currently locked", and it says so precisely in the log. Without
    # this the audit reports them as an untracked discovery gap on every run,
    # for ever, which is the fastest way to teach a reader to skim findings.
    ft_all = snap.get("files_tab", {})
    # Both forms: the engine logs the name AFTER its own disk-conflict
    # resolution, so a locked file that collided with a same-named Files-tab
    # copy is reported as "Sensemaking slides 1 (1).pptx" while Canvas and the
    # module item both call it "Sensemaking slides 1.pptx". Matching only the
    # logged form excluded nothing and reported the two locked files as a
    # discovery gap.
    _raw_locked = ev.log.get("locked_files") or []
    log_locked = ({_norm(n) for n in _raw_locked} |
                  {_norm_unconflicted(n) for n in _raw_locked})
    if log_locked:
        # One filename can carry SEVERAL Canvas ids. Measured on 43660:
        # "Sensemaking slides 1.pptx" is id 1655085 in the Files tab and
        # content_id 1658057 as a module item - two separate file objects, and
        # it is the MODULE copy that is locked. A map built from the Files tab
        # alone resolved the name to the wrong id and excluded nothing.
        by_name: dict[str, set] = {}
        def _index(name, fid):
            for key in {_norm(name), _norm_unconflicted(name)}:
                if key and fid:
                    by_name.setdefault(key, set()).add(fid)

        for meta in ft_all.values():
            _index(meta.get("display_name") or meta.get("filename") or "",
                   meta.get("id"))
        for m in snap.get("modules", []):
            for it in m.get("items", []):
                if it.get("type") == "File" and it.get("content_id"):
                    _index(it.get("title") or "", it["content_id"])
        # Subtracted from `missing` only, so a downloadable same-named copy is
        # never excluded - if it downloaded, it is tracked and not missing.
        access_locked = {fid for n in log_locked for fid in by_name.get(n, ())}
        expected -= access_locked
        locked |= access_locked

    tracked = tracked_file_ids(db)
    missing = sorted(expected - tracked)

    if locked:
        out.append(observation(
            title=f"{len(locked)} file(s) are locked on Canvas and cannot be downloaded",
            detail="The teacher has locked them. Permanent and Canvas-side - the "
                   "app reports each one by name. Excluded from the discovery gap "
                   "below so a real gap is not buried under a standing condition.",
            evidence={"locked": sorted(ev.log.get("locked_files") or [])[:10]},
            scenario=ev.scenario, course=ev.course))

    if missing:
        ft = ft_all
        mod = set(snap.get("module_file_ids", []))
        inline = set(snap.get("inline_file_ids", []))
        detail_rows = []
        for fid in missing[:25]:
            meta = ft.get(fid) or ft.get(str(fid)) or {}
            detail_rows.append({
                "id": fid, "name": meta.get("display_name") or meta.get("filename", "?"),
                "size": meta.get("size"),
                "source": ("files_tab" if fid in {int(k) for k in ft} else "") +
                          ("+module" if fid in mod else "") +
                          ("+inline" if fid in inline else ""),
            })
        out.append(ev._d("O5", "O4",
            title=f"{len(missing)} file(s) exist on Canvas but were never tracked",
            severity="high", category="discovery",
            detail="These were enumerated independently of the app (Files tab, "
                   "module items and inline /files/ links in Canvas Content bodies) "
                   "and the folder's manifest has no row for them. Because the UI, "
                   "the log and the disk are all downstream of the app's own "
                   "discovery, a gap here is invisible to every other check.",
            evidence={"missing": detail_rows, "expected": len(expected),
                      "tracked": len(tracked), "locked_excluded": len(locked)},
            scenario=ev.scenario, course=ev.course))

    extra = sorted(tracked - set(snap.get("expected_file_ids", [])))
    if extra:
        out.append(ev._d("O4", "O5",
            title=f"{len(extra)} tracked file id(s) not found in the Canvas enumeration",
            severity="low", category="discovery",
            detail="Usually legitimate - the app follows inline links and "
                   "attachments the plain endpoints do not list. Recorded so the "
                   "independent enumeration can be widened if a pattern appears.",
            evidence={"ids": extra[:25]}, scenario=ev.scenario, course=ev.course))

    if snap.get("files_tab_restricted"):
        out.append(observation(
            title="Files tab is restricted for this course; discovery relies on modules",
            detail="The app compensates with a hybrid fetch. Worth knowing when "
                   "reading any discovery finding for this course.",
            scenario=ev.scenario, course=ev.course))

    # Whether the Canvas-side hash exists decides which rename-recovery paths
    # can fire at all, so it is recorded per course rather than assumed once.
    ft = snap.get("files_tab", {})
    if ft:
        with_md5 = sum(1 for f in ft.values() if f.get("md5"))
        if with_md5 == 0:
            out.append(observation(
                title=f"Canvas exposes no md5 for any of this course's {len(ft)} files",
                detail="analyze_course's adoption tier (b) - the content match - can "
                       "therefore never fire here, leaving only tier (c) (unique "
                       "size+extension) for a file whose manifest row is gone. Note "
                       "this does NOT weaken ordinary renames: heal_manifest Tier 2 "
                       "matches on original_md5, which the app computes locally from "
                       "the bytes it wrote, and works with no Canvas hash at all. "
                       "Recorded because the tier-(b) comment reads as though it were "
                       "the primary mechanism.",
                scenario=ev.scenario, course=ev.course,
                evidence={"files_with_md5": with_md5, "files": len(ft)}))
    return out


def _one_fetch_per_file(ev: Evidence) -> list[Finding]:
    """O2: no Canvas file may be downloaded twice in one run.

    ``sync_manifest.canvas_file_id`` is the primary key, so one Canvas file
    gets one local file and one row. Two fetches of the same id therefore
    cannot both be tracked: the second write takes the row and the first copy
    is left on disk with nothing describing it - never updated, never cleaned,
    silently diverging the day Canvas replaces the file.

    This exists because the original instance (course 46396, ids 1784620 and
    1807289, 21 seconds apart) was found by reading a log by hand. Nothing in
    the suite would have noticed it, and nothing would notice it coming back:
    the folder looks plausible, the counts add up, and the extra copy is a real
    file with real bytes.

    Retries are excluded upstream - only a second ``Attempt 1`` counts.
    """
    dupes = {fid: n for fid, n in (ev.log.get("fetch_starts_by_file_id") or {}).items()
             if n > 1}
    if not dupes:
        return []
    worst = sorted(dupes.items(), key=lambda kv: -kv[1])[:10]
    return [ev._d("O2", "O4",
        title=f"{len(dupes)} Canvas file(s) were downloaded more than once in one run",
        severity="high", category="persistence",
        detail="Each of these ids went to the network twice. Two phases both "
               "claimed the file, so two copies are on disk and only one can "
               "hold the manifest row - the other is an untracked orphan. "
               "Canvas Content must run before every Files-tab sweep; see "
               "_defer_to_canvas_content.",
        evidence={"file_id_fetch_counts": dict(worst),
                  "log": ev.log.get("path")},
        scenario=ev.scenario, course=ev.course)]


def _count_coherence(ev: Evidence) -> list[Finding]:
    """O1 vs O2 vs O3: do the three surfaces agree on how much was delivered?"""
    out: list[Finding] = []
    log, disk, ui = ev.log, ev.disk, ev.ui
    if not disk.get("exists"):
        return out

    saved = log.get("files_saved", 0)
    secondary = log.get("secondary_saved", 0)
    # A shortcut is a write the log announces with a different verb ("Creating
    # Link:", not "File Saved:"). Uncounted, every course with an ExternalUrl
    # item sat one file above its claim, which is the slack that would hide a
    # genuinely missing file.
    links = log.get("links_created", 0)
    # Likewise a file placed from a copy this run already had: a real write,
    # announced as "Copying/Moving already-downloaded file" because no bytes
    # crossed the network. Uncounted, it is slack in exactly the direction that
    # hides a missing file.
    placed = log.get("files_placed", 0)
    on_disk = disk.get("content_count", 0)

    # Only meaningful when nothing consumed its source; conversions legitimately
    # change the file count in both directions. Read through _converters_on:
    # `expect["converters"]` is the NESTED shape, and a matrix row is handed the
    # flat one - the same mismatch that silently killed the manifest check, in a
    # sibling that was never migrated. Here it fails open, so the check ran on
    # rows whose converters had legitimately consumed their sources.
    if not any(_converters_on(ev).values()) and saved:
        claimed = saved + placed + secondary + links
        if on_disk < claimed:
            out.append(ev._d("O2", "O3",
                title=f"Log records {claimed} writes but {on_disk} content files exist",
                severity="high", category="delivery",
                detail="Files the log says were saved are not present. With no "
                       "converters enabled nothing should have removed them.",
                evidence={"file_saved": saved, "files_placed": placed,
                          "secondary_saved": secondary,
                          "links_created": links, "on_disk": on_disk},
                scenario=ev.scenario, course=ev.course))

    ui_text = (ui.get("completion", {}) or {}).get("text", "") or \
              (ui.get("screen", {}) or {}).get("text", "")
    # The stat, by its LABEL. On the completion screen the number and its
    # caption are separate lines ("335\nFILES DOWNLOADED"), so a pattern of
    # "<number> files" cannot match it - and the first thing that DID match was
    # the sentence below it, "45 files skipped because they exceeded the 5 MB
    # limit". The check was comparing the SKIPPED count against the saved
    # count and reporting the difference as a miscount, on four rows.
    m = re.search(r"(\d[\d,]*)\s*\n\s*FILES?\s+DOWNLOADED", ui_text, re.I)
    mc = re.search(r"(\d[\d,]*)\s*\n\s*COURSES?\s+DOWNLOADED", ui_text, re.I)
    courses_shown = int(mc.group(1).replace(",", "")) if mc else 1
    # The screen totals the whole BATCH; this evidence is one course. Comparing
    # them across a multi-course row is a category error in both directions.
    if m and saved and courses_shown <= 1:
        shown = int(m.group(1).replace(",", ""))
        # The completion screen counts items (files + Canvas Content + Panopto),
        # so it legitimately exceeds the File Saved count. A screen showing FEWER
        # than were saved is the direction that indicates a real miscount.
        if shown < saved:
            out.append(ev._d("O1", "O2",
                title=f"Completion screen shows {shown} but {saved} files were saved",
                severity="medium", category="ui-truth",
                evidence={"ui_excerpt": ui_text[:400]},
                scenario=ev.scenario, course=ev.course))

    # What THIS course's log says failed, independent of the engine's counter.
    # Reading the counter alone is the mistake this replaced: it accumulates
    # across the batch, so the second course of a two-course row inherits the
    # first's total, and the audit filed 32 HIGH "delivery" findings - the
    # single largest class in the 2026-07-28 matrix - against courses whose own
    # logs recorded not one failure. Every one of them carried `log_errors: []`,
    # which is the tell: a delivery HIGH that cannot name a failing file is not
    # a delivery finding.
    own = log.get("error_lines") or []
    own_n = int(log.get("error_line_count", len(own)))
    unlocked = [e for e in own if e.get("kind") != "Locked File"]
    locked_names = sorted(log.get("locked_files") or [])

    for c in log.get("courses_finished", []):
        counted = int(c.get("errors") or 0)
        if not counted and not own_n:
            continue

        # 1. Is the engine's own tally honest about THIS course?
        if counted != own_n:
            over = counted > own_n
            out.append(ev._d(
                "O2", "O2",
                # No quotes around "Course Finished": a quoted span is exactly
                # what the class normaliser blanks, so quoting a LITERAL here
                # would render the whole class as "'X' reports N error(s)...".
                title=(f"Course Finished reports {counted} error(s) but this "
                       f"course's log records {own_n}"),
                severity="medium", category="ui-truth",
                detail=("The engine's error counter is not reset per course, so "
                        "a later course in a batch reports its predecessors' "
                        "failures as its own."
                        if over else
                        "The engine counted FEWER errors than its own log "
                        "printed - errors are reaching the log without reaching "
                        "the tally the user is shown."),
                evidence={"course": c["course"], "items": c["items"],
                          "counted": counted, "logged": own_n,
                          "error_lines": own[:10]},
                scenario=ev.scenario, course=ev.course))

        # 2. Did anything actually fail, and was it something the app could have
        #    done anything about? Teacher-locked files are a standing Canvas-side
        #    condition - the app names each one and there is no action available,
        #    so they are recorded at info rather than sitting in the blocking
        #    pile of every run for ever. Anything else is a delivery defect, and
        #    it is now reported WITH the failing item rather than as a bare count.
        if not own_n:
            continue
        if unlocked:
            out.append(ev._f(
                title=f"Download finished with {len(unlocked)} unexplained error(s)",
                severity="high", category="delivery", oracles=("O2", "O3"),
                detail="Errors this course logged that are not teacher-locked "
                       "files. Each names the item the engine could not deliver.",
                evidence={"course": c["course"], "items": c["items"],
                          "unexplained": unlocked[:10],
                          "kinds": sorted({e.get("kind", "") for e in unlocked}),
                          "locked_files": locked_names[:10]}))
        else:
            out.append(ev._f(
                title=f"Download finished with {own_n} error(s), all "
                      f"teacher-locked files",
                severity="info", category="observation", oracles=("O2",),
                detail="Canvas refuses to serve these; nothing the app can do. "
                       "Recorded so the count stays visible.",
                evidence={"course": c["course"], "items": c["items"],
                          "locked_files": locked_names[:10]}))
    return out


def _layout(ev: Evidence) -> list[Finding]:
    """Right file, right place. Flat must be flat; modules must be foldered."""
    out: list[Finding] = []
    mode, disk = ev.expect.get("mode"), ev.disk
    if not mode or not disk.get("exists"):
        return out

    # Panopto's 'separate' layout and zip extraction both create folders on
    # purpose, so a flat run is allowed exactly those.
    allowed = set()
    if (ev.expect.get("panopto") or {}).get("layout") == "separate":
        allowed.add("Panopto Recordings")
    if (ev.expect.get("converters") or {}).get("convert_zip"):
        allowed.update(Path(f["rel"]).parts[0] for f in disk["files"]
                       if "/" in f["rel"])
    if (ev.expect.get("secondary_isolated")):
        allowed.update(d for d in disk.get("dirs", []) if "/" not in d)

    if mode == "flat":
        stray = [d for d in disk.get("dirs", []) if "/" not in d and d not in allowed]
        if stray:
            out.append(ev._d("O1", "O3",
                title=f"Flat organisation requested but {len(stray)} subfolder(s) were created",
                severity="high", category="placement",
                detail="'All in One Folder' must put every course file at the root.",
                evidence={"dirs": stray[:15], "allowed": sorted(allowed)},
                scenario=ev.scenario, course=ev.course))
    elif mode in ("modules", "subfolders"):
        depth1 = [d for d in disk.get("dirs", []) if "/" not in d]
        if not depth1 and disk.get("content_count", 0) > 5:
            out.append(ev._d("O1", "O3",
                title="Module organisation requested but every file is at the folder root",
                severity="high", category="placement",
                evidence={"content_count": disk.get("content_count")},
                scenario=ev.scenario, course=ev.course))
    return out


def _file_filter(ev: Evidence) -> list[Finding]:
    out: list[Finding] = []
    if ev.expect.get("file_filter") != "study" or not ev.disk.get("exists"):
        return out
    convs = ev.expect.get("converters") or {}
    produced = {v["produces"] for k, v in CONVERTERS.items()
                if convs.get(k) and v["produces"]}
    # Panopto is a separate pass with its own outputs; "Slides & PDFs" filters
    # the Canvas FILES a course exposes, not the recordings the user asked for
    # by name. Measured on 43660 with study + mp3: all 36 recordings were
    # reported as "36 other file type(s) were downloaded" at HIGH. Only the
    # outputs this row actually requested are excused, so a stray .mp4 on an
    # audio-only row is still a finding.
    produced |= {ext for key, ext in PANOPTO_OUTPUTS.items() if ev.expect.get(key)}
    allowed = STUDY_EXTS | produced | {".html", ".md", ".txt"}
    offenders = [f["rel"] for f in ev.disk["files"]
                 if not f["app_generated"] and f["ext"] and f["ext"] not in allowed]
    if offenders:
        out.append(ev._d("O1", "O3",
            title=f"'Slides & PDFs' filter requested but {len(offenders)} other "
                  f"file type(s) were downloaded",
            severity="high", category="config",
            evidence={"files": offenders[:20],
                      "exts": sorted({Path(o).suffix.lower() for o in offenders})},
            scenario=ev.scenario, course=ev.course))
    return out


def _size_cap_applied(ev: Evidence) -> list[Finding]:
    """O1 vs O2: did the cap the row asked for actually reach the engine?

    Every other size-cap check reasons about CONSEQUENCES - no over-cap file on
    disk, no manifest row for a skipped one - and both are satisfied trivially
    when the cap was never applied at all. A run that silently ignored the
    setting looks identical to a run where the cap did its job, so it has to be
    checked at the source: the engine echoes what it is about to use
    ("Max file size: 5 MB" / "disabled") before it downloads anything.

    This is not hypothetical. The cap lives in the global Settings dialog, not
    on the download page, and the flow that applies a matrix row only knew the
    download page - so the factor was accepted into every row and applied to
    none, and nothing anywhere said so.
    """
    params = ev.log.get("download_params") or {}
    logged = (params.get("maxsize") or "").strip()
    if not logged:
        return []
    want = ev.expect.get("max_file_size_mb")
    m = re.search(r"(\d+)", logged)
    got = int(m.group(1)) if m else None
    if bool(want) == bool(got) and (not want or want == got):
        return []
    return [ev._d("O1", "O2",
        title=f"Size cap requested {want or 'disabled'} but the engine ran with "
              f"'{logged}'",
        severity="high", category="config",
        detail="The cap is a global setting, so a run that never received it "
               "passes every consequence-based size check by default.",
        evidence={"requested_mb": want, "logged": logged},
        scenario=ev.scenario, course=ev.course)]


def _size_limit(ev: Evidence) -> list[Finding]:
    """A skipped file must be absent from disk AND absent from the manifest.

    The manifest half is the one that bites: a row recorded for a file that was
    never written makes the next sync consider it up to date, so raising the
    limit later would never bring it in.
    """
    out = _size_cap_applied(ev)
    cap_mb = ev.expect.get("max_file_size_mb")
    if not cap_mb or not ev.disk.get("exists"):
        return out
    cap = cap_mb * 1024 * 1024

    over = [f for f in ev.disk["files"]
            if not f["app_generated"] and f["size"] > cap and f["ext"] != ".mp3"]
    if over:
        out.append(ev._d("O1", "O3",
            title=f"Size cap {cap_mb} MB set but {len(over)} file(s) exceed it on disk",
            severity="high", category="config",
            evidence={"files": [{"rel": f["rel"], "mb": round(f["size"] / 1e6, 1)}
                                for f in over[:15]]},
            scenario=ev.scenario, course=ev.course))

    snap, db = ev.canvas, ev.db
    if snap and db.get("exists"):
        big = {f["id"] for f in snap.get("files_tab", {}).values()
               if f["size"] > cap and f["has_url"]}
        # An over-cap file SHOULD have a row - an IGNORED one. That is the
        # mechanism, not a bug: the engine records what it skipped so a later
        # sync does not re-offer it, and Settings promises the user "you can
        # restore them at any time from the Sync Hub's ignored-files list -
        # including after you raise this limit". Reading every over-cap row as
        # a ghost inverted the product's design and reported 25 of them at
        # HIGH; all 25 were `is_ignored = 1` with an empty local_path.
        #
        # The real defect is the opposite one, so that is what is checked: a
        # LIVE row for a file that was never written. That one does read as up
        # to date for ever, and raising the cap would not bring it in.
        live = {r.get("canvas_file_id") for r in db.get("rows", []) or []
                if not r.get("is_ignored") and r.get("local_path")}
        ghosts = sorted(big & {abs(i) for i in live if isinstance(i, int)})
        if ghosts:
            out.append(ev._d("O5", "O4",
                title=f"{len(ghosts)} over-cap file(s) have a LIVE manifest row "
                      f"despite never being downloaded",
                severity="high", category="persistence",
                detail="Skipped files are supposed to be recorded as IGNORED, "
                       "which is what lets the user restore them later. A live "
                       "row instead makes the file read as up to date for ever, "
                       "so raising the cap would never bring it in.",
                evidence={"ids": ghosts[:20], "cap_mb": cap_mb},
                scenario=ev.scenario, course=ev.course))

        # The positive half: the skip must actually be recorded, or the next
        # sync offers the file again and the user is asked the same question
        # every time.
        ignored = {abs(r["canvas_file_id"]) for r in db.get("rows", []) or []
                   if r.get("is_ignored") and isinstance(r.get("canvas_file_id"), int)}
        unrecorded = sorted(big - ignored - {abs(i) for i in live
                                             if isinstance(i, int)})
        if unrecorded:
            out.append(ev._d("O5", "O4",
                title=f"{len(unrecorded)} over-cap file(s) were skipped without "
                      f"an ignored row",
                severity="medium", category="persistence",
                detail="Nothing records that these were deliberately skipped, so "
                       "the next sync lists them as new again and the Sync Hub "
                       "cannot offer them for restore.",
                evidence={"ids": unrecorded[:20], "cap_mb": cap_mb},
                scenario=ev.scenario, course=ev.course))
    return out


def _vendored(rel: str) -> bool:
    """Inside a directory the converters deliberately never enter.

    ``converters.post_processing._PACKAGE_DIRS`` skips ``node_modules``,
    ``.git``, ``__pycache__``, virtualenvs and ``site-packages`` - unpacking a
    student project's npm tree and rewriting 11,818 dependency files to ``.txt``
    would be absurd, and the exclusion is documented and tested.

    The audit did not know that, so the first archive row after this check came
    back to life reported "convert_code did not reach 11818 file(s) unpacked
    from archives" - every one of them under ``node_modules``, on a run where
    68 genuine conversion products sat beside them. The app's own set is
    imported rather than restated: a list copied into a checker is a list that
    drifts from the thing it checks.
    """
    from converters.post_processing import _PACKAGE_DIRS
    parts = set(re.split(r"[\\/]", rel))
    return bool(parts & _PACKAGE_DIRS) or "__MACOSX" in parts


def _conversions(ev: Evidence) -> list[Finding]:
    """Each enabled converter must have consumed its inputs and left its outputs."""
    out: list[Finding] = []
    convs = ev.expect.get("converters") or {}
    disk = ev.disk
    if not convs or not disk.get("exists"):
        return out

    # A Panopto output is not a converter input. The user asked for mp4 BY
    # NAME; consuming it into an mp3 would deliver the opposite of the request,
    # and the app is structurally right not to - post-processing is scoped to
    # the paths the DOWNLOADER wrote, and recordings are written by the Panopto
    # runner. Matched against the panopto manifest rather than by folder,
    # because `pan_layout=match` puts recordings alongside course files where
    # no path test could tell them apart. Measured: one row with pan_out_mp4
    # and convert_video both on reported all 36 recordings as "source files
    # that survived conversion".
    pan_paths = {_key(r.get("local_path", ""))
                 for r in (ev.db.get("panopto_rows") or [])
                 if isinstance(r, dict) and r.get("local_path")}
    files = [f for f in disk["files"]
             if not f["app_generated"] and not _vendored(f["rel"])
             and _key(f["rel"]) not in pan_paths]
    exts = {f["ext"] for f in files}
    names = {f["name"] for f in files}

    for key, on in convs.items():
        spec = CONVERTERS.get(key)
        if not on or not spec:
            continue
        leftovers = [f["rel"] for f in files if f["ext"] in spec["sources"]]

        if spec.get("aggregate"):
            if leftovers and spec["aggregate"] not in names:
                out.append(ev._d("O1", "O3",
                    title=f"{key} enabled but {spec['aggregate']} was not produced",
                    severity="high", category="conversion",
                    evidence={"sources_left": leftovers[:10]},
                    scenario=ev.scenario, course=ev.course))
            continue

        if spec.get("extracts"):
            if leftovers:
                out.append(ev._d("O1", "O3",
                    title=f"{key} enabled but {len(leftovers)} archive(s) were not extracted",
                    severity="high", category="conversion",
                    detail="An archive left on disk means extraction failed or was "
                           "skipped; the user gets a zip they must open themselves.",
                    evidence={"archives": leftovers[:10]},
                    scenario=ev.scenario, course=ev.course))
            continue

        if spec["removes_source"] and leftovers:
            # Split by WHERE the survivor is. A file left at module level means
            # the converter ran and failed on it. A file left inside an
            # extracted archive means the converter never saw it, because
            # explicit_files scopes conversion to what the DOWNLOADER wrote and
            # extraction output is not in that set. Same symptom, different bug,
            # and reporting one number for both hides the second.
            roots = _infer_extracted_roots(ev) if convs.get("convert_zip") else set()
            in_archive = [f for f in leftovers
                          if any(_key(f).startswith(_key(r) + "/") for r in roots)]
            top_level = [f for f in leftovers if f not in in_archive]

            if top_level:
                out.append(ev._d("O1", "O3",
                    title=f"{key} enabled but {len(top_level)} source file(s) survived "
                          f"conversion",
                    severity="medium", category="conversion",
                    detail="This converter is documented to replace its source. A "
                           "surviving source at module level means the conversion ran "
                           "and failed for that file - check whether the failure was "
                           "reported to the user or only swallowed.",
                    evidence={"files": top_level[:12]},
                    scenario=ev.scenario, course=ev.course))
            if in_archive:
                out.append(ev._d("O1", "O3",
                    title=f"{key} did not reach {len(in_archive)} file(s) unpacked "
                          f"from archives",
                    severity="medium", category="conversion",
                    detail="convert_zip extracted these, but post-processing filters "
                           "every converter through explicit_files - the list of paths "
                           "the DOWNLOADER wrote - and extraction output is never added "
                           "to it. So enabling both toggles applies only the first to "
                           "archive contents.",
                    evidence={"files": in_archive[:12], "roots": sorted(roots)[:8]},
                    scenario=ev.scenario, course=ev.course))

        if spec["produces"] and spec["produces"] not in exts:
            had_sources = ev.expect.get("had_sources", {}).get(key)
            if had_sources:
                out.append(ev._d("O1", "O3",
                    title=f"{key} enabled with {had_sources} source file(s) but no "
                          f"{spec['produces']} output exists",
                    severity="high", category="conversion",
                    scenario=ev.scenario, course=ev.course))

        if key == "convert_excel" and any(f["ext"] in spec["sources"] for f in files):
            if not any(f["name"].endswith("_Data.txt") for f in files):
                out.append(ev._d("O1", "O3",
                    title="Excel conversion enabled but no _Data.txt sidecar produced",
                    severity="medium", category="conversion",
                    detail="The workbook-to-text sidecar is the AI-optimisation "
                           "half of this toggle; the PDF alone is not the feature.",
                    scenario=ev.scenario, course=ev.course))

    # The mirror check: a converter that was OFF must not have run.
    for key, spec in CONVERTERS.items():
        if convs.get(key) or not spec["removes_source"]:
            continue
        if key in convs and not convs[key]:
            src_present = any(f["ext"] in spec["sources"] for f in files)
            expected_src = ev.expect.get("had_sources", {}).get(key)
            if expected_src and not src_present:
                out.append(ev._d("O1", "O3",
                    title=f"{key} was OFF but its {expected_src} source file(s) are gone",
                    severity="critical", category="conversion",
                    detail="A disabled converter consumed files anyway - the user "
                           "asked to keep the originals and they were deleted.",
                    scenario=ev.scenario, course=ev.course))
    return out


def _secondary_content(ev: Evidence) -> list[Finding]:
    """Each enabled Canvas Content type must produce its entities, and each
    disabled one must produce none."""
    out: list[Finding] = []
    want, db, snap = ev.expect.get("secondary") or {}, ev.db, ev.canvas
    if not want or not db.get("exists"):
        return out
    by_entity = db.get("by_entity", {})
    avail = snap.get("secondary_counts", {}) if snap else {}

    for ui_key, on in want.items():
        ent = SECONDARY_UI_TO_ENTITY.get(ui_key)
        if not ent:
            continue
        got = by_entity.get(ent, 0)
        canvas_has = avail.get(ent if ent != "syllabus" else "syllabus", None)
        if on and got == 0 and canvas_has:
            out.append(ev._d("O5", "O4",
                title=f"Canvas Content '{ent}' enabled and Canvas has {canvas_has}, "
                      f"but none were tracked",
                severity="high", category="discovery",
                evidence={"by_entity": by_entity, "canvas": avail},
                scenario=ev.scenario, course=ev.course))
        if not on and got:
            out.append(ev._d("O1", "O4",
                title=f"Canvas Content '{ent}' was OFF but {got} were downloaded",
                severity="high", category="config",
                evidence={"by_entity": by_entity},
                scenario=ev.scenario, course=ev.course))

    if ev.expect.get("secondary_isolated") and ev.disk.get("exists"):
        loose = [r for r in ev.disk.get("secondary_html", []) if "/" not in r]
        if loose:
            out.append(ev._d("O1", "O3",
                title=f"Canvas Content isolation requested but {len(loose)} entity "
                      f"file(s) sit at the folder root",
                severity="medium", category="placement",
                evidence={"files": loose[:15]},
                scenario=ev.scenario, course=ev.course))
    return out


# ==========================================================================
# sync
# ==========================================================================

def sync_run(ev: Evidence, plan: dict, ui_review: dict | None = None,
             after_disk: dict | None = None,
             before_disk: dict | None = None) -> list[Finding]:
    """Compare a sync against the seeder's PREDICTED categories.

    ``plan`` is the seeder's output: every fixture it created, with the category
    the analyzer is required to place it in and what must happen to it on disk.
    """
    out: list[Finding] = []
    out.extend(_categories_match(ev, plan, ui_review))
    out.extend(_ui_matches_log(ev, ui_review))
    if after_disk is not None:
        out.extend(_sync_outcome(ev, plan, after_disk, before_disk, ui_review))
    return out


_LOG_CAT = {"NEW": "new", "UPDATE-CLEAN": "updated_clean",
            "UPDATE-MODIFIED": "updated_modified",
            "DELETED-CANVAS": "deleted_on_canvas",
            "DELETED-LOCAL": "deleted_locally", "IGNORED": "ignored"}

# The debug log only writes PER-FILE rows for these two categories
# (sync/analysis.py:247,250). The other five appear in the "Analysis complete"
# counts and nowhere else, so absence from the log says nothing about them and
# must never be read as a mis-classification. Measured on a run whose analysis
# reported 2 deleted-on-Canvas and 2 ignored: the log contained zero rows for
# either. For those categories the REVIEW SCREEN (O1) is the only per-file
# evidence, so that is what they are checked against.
_LOG_DETAILED_CATS = frozenset({"new", "updated_clean"})


def _categories_match(ev: Evidence, plan: dict, ui_review: dict | None) -> list[Finding]:
    """The central sync assertion: every fixture landed in its predicted bucket."""
    out: list[Finding] = []
    rows = ev.log.get("analysis_rows", {}) or {}
    log_cat: dict[str, str] = {}
    for raw, names in rows.items():
        cat = _LOG_CAT.get(raw)
        if not cat:
            continue
        for n in names:
            log_cat[_norm(n)] = cat

    # The review screen renders a filename as STEM plus a separate uppercase
    # <del>EXT</del> chip, so its innerText never contains "name.ext" and a
    # full-filename comparison can never match. Both sides are reduced to a
    # stem, which is also what makes the comparison survive the conversion
    # renames (a .js tracked as .txt keeps its stem).
    ui_cat: dict[str, str] = {}
    if ui_review:
        for course in ui_review.get("courses", []):
            for cat, blob in course.get("categories", {}).items():
                for row in blob.get("rows", []):
                    for token in filter(None, (row.get("stem"), row.get("name"))):
                        ui_cat[_stem(token)] = cat
                    for token in _tokens(row.get("text", "")):
                        ui_cat.setdefault(_stem(token), cat)
        # The engine appends "-1" to a repeated attachment, so the SCREEN can
        # carry a suffix the fixture's on-disk name has no way to predict. Added
        # with setdefault and only after every exact stem is registered, so a
        # real filename that simply ends in a number ("Debug - shop - 1") always
        # wins its own key and can never be displaced by a stripped neighbour.
        for k in list(ui_cat):
            stripped = _DEDUP_SUFFIX.sub("", k).strip()
            if stripped and stripped != k:
                ui_cat.setdefault(stripped, ui_cat[k])

    # An extraction that saw the screen but produced nothing is a broken probe,
    # not a broken app, and must never be reported as 42 mis-classifications.
    if ui_review is not None:
        seen = ui_review.get("seen", {})
        if not ui_review.get("courses") and seen.get("categoryContainers"):
            out.append(ev._f(
                title="Review-screen extraction returned no categories although the "
                      "screen has them (AUDIT PROBE DEFECT)",
                severity="medium", category="observation", oracles=("O1",),
                detail="probe.SYNC_REVIEW found no categories while the DOM holds "
                       f"{seen.get('categoryContainers')} category container(s) and "
                       f"{seen.get('syncRows', 0)} row(s). Per-file placement cannot "
                       "be asserted this run; fix the probe before trusting any "
                       "classification result.",
                evidence={"seen": seen},
                scenario=ev.scenario, course=ev.course))
            ui_review = None
            ui_cat = {}

    for fx in plan.get("fixtures", []):
        want = fx.get("expect_category")
        if not want:
            continue
        name = _norm(fx.get("match_name") or Path(fx.get("path", "")).name)
        cands = _name_candidates(name)
        got_log = next((log_cat[c] for c in cands if c in log_cat), None)
        got_ui = next((ui_cat[c] for c in cands if c in ui_cat), None)
        if not got_log:
            got_log = next((c2 for n, c2 in log_cat.items()
                            if _stem(n) in cands), None)

        # Pick the oracle that can actually see this category. Only `new` and
        # `updated_clean` get per-file log rows; everything else is visible
        # solely on the review screen.
        if want in _LOG_DETAILED_CATS or got_log:
            observed, oracle = got_log, "O2"
        elif ui_review:
            observed, oracle = got_ui, "O1"
        else:
            continue      # nothing can see it; silence beats a guess

        if observed and observed != want:
            out.append(ev._d(oracle, "O5",
                title=f"'{fx.get('label', name)}' classified as {observed}, expected {want}",
                severity="high", category="classification",
                detail=fx.get("why", ""), synthetic=True,
                evidence={"fixture": fx, "observed": observed, "via": oracle},
                scenario=ev.scenario, course=ev.course))
        elif not observed and want != "uptodate":
            out.append(ev._d("O5", oracle,
                title=f"'{fx.get('label', name)}' expected as {want} but no oracle "
                      f"placed it in any category",
                severity="high", category="classification",
                detail=fx.get("why", ""), synthetic=True,
                evidence={"fixture": fx, "analysis": ev.log.get("analysis"),
                          "via": oracle},
                scenario=ev.scenario, course=ev.course))
        elif observed and want == "uptodate":
            out.append(ev._d(oracle, "O5",
                title=f"'{fx.get('label', name)}' should have been recognised as up to "
                      f"date but was offered as {observed}",
                severity="high", category="classification",
                detail=fx.get("why", "") + " This is the failure mode where a "
                       "renamed or moved file is re-downloaded as a duplicate.",
                synthetic=True, evidence={"fixture": fx},
                scenario=ev.scenario, course=ev.course))

        if ui_review and got_ui and got_log and got_ui != got_log:
            out.append(ev._d("O1", "O2",
                title=f"Review screen shows '{name}' under {got_ui} while the log "
                      f"classified it {got_log}",
                severity="high", category="ui-truth",
                detail="The review screen is the source of truth the user acts on.",
                evidence={"fixture": fx}, scenario=ev.scenario, course=ev.course))
    return out


def _ui_matches_log(ev: Evidence, ui_review: dict | None) -> list[Finding]:
    """Per-category counts on screen vs the analysis line in the log."""
    out: list[Finding] = []
    a = ev.log.get("analysis")
    if not a or not ui_review:
        return out
    want = {"new": int(a["new"]), "updated_clean": int(a["clean"]),
            "updated_modified": int(a["modified"]),
            "deleted_on_canvas": int(a["candel"]),
            "deleted_locally": int(a["locdel"])}
    for course in ui_review.get("courses", []):
        cats = course.get("categories", {})
        for cat, expected in want.items():
            shown = cats.get(cat, {}).get("rowCount")
            if shown is None:
                if expected:
                    out.append(ev._d("O2", "O1",
                        title=f"Analysis found {expected} {cat} file(s) but the review "
                              f"screen has no such category",
                        severity="high", category="ui-truth",
                        evidence={"course_id": course.get("course_id"),
                                  "categories": list(cats)},
                        scenario=ev.scenario, course=ev.course))
                continue
            # Panopto recordings render inside the file categories, so the screen
            # may legitimately show MORE rows than the file analysis counted.
            if shown < expected:
                out.append(ev._d("O2", "O1",
                    title=f"Review screen lists {shown} {cat} file(s) but the analysis "
                          f"found {expected}",
                    severity="high", category="ui-truth",
                    evidence={"course_id": course.get("course_id"), "category": cat},
                    scenario=ev.scenario, course=ev.course))
    return out


def _selected_stems(ui_review: dict | None) -> set[str] | None:
    """Stems of the rows that were actually TICKED on the review screen.

    None when there is no review capture, which is different from "nothing was
    selected" and must not be confused with it.

    **The discriminator is the presence of the ``courses`` key, not whether the
    dict is truthy.** Handed some OTHER screen's capture - a completion screen,
    say - the old test passed it as a real review with nothing ticked, and every
    caller then read "the user selected none of it". A review screen that
    genuinely lists no courses still carries the key, so `set()` stays reachable
    and means what it says.

    This is the root of a defect measured 2026-07-29: a re-check fed the
    completion capture reported 4 HIGHs against a live pass that reported none,
    because `_sync_outcome` flips a fixture's expectation from 'absent' to
    'restored' only for rows it can see were ticked.
    """
    if not ui_review or "courses" not in ui_review:
        return None
    out: set[str] = set()
    for course in ui_review.get("courses", []):
        for blob in course.get("categories", {}).values():
            for row in blob.get("rows", []):
                if row.get("checked"):
                    for tok in filter(None, (row.get("stem"), row.get("name"))):
                        out.add(_stem(tok))
    return out


def _was_quick_sync(ev: Evidence) -> bool:
    """Did this run go through Quick Sync? Asked of the log, which cannot lie."""
    mode = ((ev.log.get("sync_mode") or {}) if isinstance(ev.log.get("sync_mode"), dict)
            else {}).get("mode", "")
    if not mode:
        mode = str(ev.log.get("sync_mode") or "")
    return "quick sync" in mode.lower() or bool(ev.log.get("quick_sync"))


def _sync_outcome(ev: Evidence, plan: dict, after: dict,
                  before: dict | None = None,
                  ui_review: dict | None = None) -> list[Finding]:
    """After the sync ran: is each fixture where it was promised to be?

    Expectations are read against WHAT THE USER ACTUALLY SELECTED, not against
    what the fixture hoped for. An edited-locally row is unchecked by default -
    that is the product's deliberate behaviour and the fixture's own note says
    so - so demanding a ``_NewVersion`` sibling from it produced two critical
    "data loss" findings on a run where the app had behaved perfectly. The
    fixture declares the outcome for a row that IS synced; whether it was is a
    fact only the review screen holds.
    """
    out: list[Finding] = []
    have = {_key(f["rel"]): f for f in after.get("files", [])}
    names = {f["name"] for f in after.get("files", [])}
    was = {_key(f["rel"]): f for f in (before or {}).get("files", [])}
    selected = _selected_stems(ui_review)
    # QUICK SYNC HAS NOTHING TO TICK, and it is not a missing observation - the
    # mode deliberately declines the two categories that need a decision. The
    # app says so in its own log: "Quick Sync always skips locally-deleted and
    # locally-edited files", followed by a [QS-SKIP-EDITED] line per file.
    # Without this, `selected` was None, the gate above was skipped, and every
    # quick row seeding `edited_update` demanded a _NewVersion sibling from a
    # mode that never touches the file - eight CRITICAL "data loss" findings on
    # four runs where the app had protected the user's work exactly as designed.
    #
    # Read from the LOG, not from the caller: the run itself is the only thing
    # that knows which mode it was, and a flag passed down can be wrong.
    if selected is None and _was_quick_sync(ev):
        selected = set()

    for fx in plan.get("fixtures", []):
        expect = fx.get("expect_after")
        if not expect:
            continue
        rel = fx.get("expect_path") or fx.get("path", "")
        present = _key(rel) in have

        if selected is not None:
            stem = _stem(fx.get("match_name") or Path(fx.get("path", "")).name)
            was_ticked = bool(stem) and stem in selected
            if expect in ("restored", "new_version") and not was_ticked:
                # Offered but declined. The only promise left is that nothing
                # happened to it - which is exactly the 'unchanged' contract.
                expect = "unchanged"
            elif expect == "absent" and was_ticked:
                # The mirror image, and just as important: a fixture predicts
                # 'absent' because its row is UNCHECKED by default. Tick it -
                # which is the whole point of the second Phase 2 scenario - and
                # the file must now arrive. Without this the app was reported
                # for doing exactly what the user had just asked it to do.
                expect = "restored"

        if expect == "unchanged":
            # The other half of "never touch what the user did not ask for".
            # Decoys, foreign files, duplicates and up-to-date files must come
            # through a sync byte-identical; a sync that quietly rewrites one is
            # invisible on screen and only shows up here.
            prev = was.get(_key(rel))
            cur = have.get(_key(rel))
            if prev and not cur:
                out.append(ev._d("O3", "O3",
                    title=f"'{fx.get('label')}' was DELETED by a sync that should "
                          f"not have touched it",
                    severity="critical", category="delivery", synthetic=True,
                    detail=fx.get("why", "") or "This file was not part of the "
                           "requested changes.",
                    evidence={"fixture": fx, "path": rel},
                    scenario=ev.scenario, course=ev.course))
            elif prev and cur and prev.get("md5") and cur.get("md5") \
                    and prev["md5"] != cur["md5"]:
                out.append(ev._d("O3", "O3",
                    title=f"'{fx.get('label')}' was REWRITTEN by a sync that should "
                          f"not have touched it",
                    severity="critical", category="delivery", synthetic=True,
                    detail=fx.get("why", "") or "This file was not part of the "
                           "requested changes.",
                    evidence={"fixture": fx, "path": rel,
                              "md5_before": prev["md5"], "md5_after": cur["md5"]},
                    scenario=ev.scenario, course=ev.course))
            continue

        if expect == "restored" and not present:
            out.append(ev._d("O5", "O3",
                title=f"'{fx.get('label')}' was selected for sync but is not on disk at {rel}",
                severity="critical", category="delivery", synthetic=True,
                detail="The review screen offered it, the user accepted, and the "
                       "file did not arrive.",
                evidence={"fixture": fx}, scenario=ev.scenario, course=ev.course))
        elif expect == "restored" and present:
            # A file the app itself called an unmodified update must be
            # OVERWRITTEN IN PLACE. A _NewVersion sibling is the response to a
            # local edit, so producing one here contradicts the category the
            # screen showed and leaves the user a duplicate they never caused.
            p = Path(rel)
            fork = f"{p.stem}_NewVersion{p.suffix}"
            if fork in names:
                out.append(ev._d("O1", "O3",
                    title=f"'{fx.get('label')}' was shown as an unmodified update "
                          f"but the sync forked it to _NewVersion",
                    severity="high", category="delivery", synthetic=True,
                    detail="_NewVersion exists to protect a locally EDITED file. On "
                           "a clean update the file is meant to be replaced in "
                           "place, so a fork here is either a mis-classification on "
                           "the review screen or a needless duplicate on disk.",
                    evidence={"fixture": fx, "fork": fork},
                    scenario=ev.scenario, course=ev.course))
        elif expect == "absent" and present:
            out.append(ev._d("O5", "O3",
                title=f"'{fx.get('label')}' should have been left alone but was written to {rel}",
                severity="high", category="delivery", synthetic=True,
                detail=fx.get("why", ""), evidence={"fixture": fx},
                scenario=ev.scenario, course=ev.course))
        elif expect == "new_version":
            stem = Path(rel).stem
            if not any(n.startswith(stem) and "_NewVersion" in n for n in names):
                out.append(ev._d("O5", "O3",
                    title=f"'{fx.get('label')}' was locally edited but no _NewVersion "
                          f"sibling was created",
                    severity="critical", category="delivery", synthetic=True,
                    detail="The product's stated contract is that local edits are "
                           "never overwritten and the new copy lands alongside.",
                    evidence={"fixture": fx}, scenario=ev.scenario, course=ev.course))
            if fx.get("edited_md5") and _key(rel) in have:
                cur = have[_key(rel)].get("md5")
                if cur and cur != fx["edited_md5"]:
                    out.append(ev._d("O5", "O3",
                        title=f"'{fx.get('label')}' local edits were OVERWRITTEN",
                        severity="critical", category="delivery", synthetic=True,
                        detail="The user's annotated copy was replaced. This is data loss.",
                        evidence={"fixture": fx}, scenario=ev.scenario, course=ev.course))
    return out


# --------------------------------------------------------------------------

_DEDUP_SUFFIX = re.compile(r"[ _-]\(?\d{1,3}\)?$")


def _name_candidates(name: str) -> set[str]:
    """Every stem the SAME file can legitimately be shown under.

    A fixture records the name a file has ON DISK; the review screen shows the
    name it has ON CANVAS. Three of the app's own conventions sit between them,
    and each one silently broke the classification oracle on a run where the app
    had placed all eleven files correctly:

    1. **A converter rename.** ``code.py`` is written as ``code_py.txt`` - the
       source extension is folded into the stem. So ``g1 darts vejl_løsn_js.txt``
       on disk is ``g1 darts vejl_løsn`` with a JS chip on screen.
    2. **A secondary-entity prefix.** A quiz is written as ``Quiz <title>.md``
       while the screen shows ``<title>`` and its SOURCE type (html).
    3. **An attachment inside a secondary entity.** ``Assignment <entity> -
       <filename>.pdf`` on disk is just ``<filename>`` on screen - and if two
       entities carry the same attachment, one gains a ``-1`` dedup suffix.

    Returning a SET rather than picking one is deliberate: which convention
    applies depends on how the file was discovered, which the fixture does not
    record. A false match is near-impossible here because every candidate is
    still a full stem, and a miss costs a fabricated "no oracle placed it".
    """
    stem = _stem(name)
    out = {_norm(name), stem}

    # 1. converter rename: strip a trailing _<sourceext>
    for spec in CONVERTERS.values():
        for src in spec["sources"]:
            suffix = "_" + src.lstrip(".")
            if stem.endswith(suffix):
                out.add(_stem(stem[: -len(suffix)]))

    # 2. secondary-entity prefix
    for pre in ("announcement ", "assignment ", "quiz ", "discussion ",
                "page ", "syllabus", "submission ", "rubric "):
        if stem.startswith(pre):
            rest = stem[len(pre):].strip()
            if rest:
                out.add(rest)
                # 3. attachment inside that entity: "<entity> - <filename>"
                if " - " in rest:
                    out.add(rest.rsplit(" - ", 1)[-1].strip())

    # 3b. the dedup suffix the engine adds for a repeated attachment
    for c in list(out):
        stripped = _DEDUP_SUFFIX.sub("", c).strip()
        if stripped and stripped != c:
            out.add(stripped)

    return {c for c in out if c}


def _converters_on(ev: Evidence) -> dict:
    """Which converters this folder was actually built with.

    Read from the CONTRACT the app stored in ``sync_metadata.sync_contract``
    first, because that is what the engine itself obeys and it cannot drift
    from what the caller happened to pass. ``expect`` is only a fallback, and
    is accepted in both the nested (``{"converters": {...}}``) and flat
    (``{"convert_urls": true}``) shapes.

    That shape mismatch is exactly how this check silently died: the exemption
    below reads ``expect["converters"]`` while ``check download`` is handed a
    flat config, so ``consumed_exts`` came out empty and the 25 ``.url`` rows a
    converter had deliberately consumed were reported as a broken manifest -
    the comment beside it even predicts the number. A check whose correctness
    depends on the caller nesting a dict it does not otherwise need is a check
    that will keep going quiet.
    """
    contract = (ev.db.get("contracts") or {}).get("sync") or {}
    if any(k in contract for k in CONVERTERS):
        return contract
    nested = ev.expect.get("converters")
    if isinstance(nested, dict) and nested:
        return nested
    return {k: v for k, v in ev.expect.items() if k in CONVERTERS}


def _conversion_aggregates(ev: Evidence) -> set[str]:
    """Converter outputs that have no manifest row BY DESIGN.

    Two shapes, and only the first was handled:

    * **aggregate** - one file for the whole course. ``convert_urls`` compiles
      every ``.url`` into a single ``Compiled_External_Links.txt``. It is a
      product, not Canvas content, and was the entire content of the standing
      "1 content file on disk with no manifest row" finding.
    * **sidecar** - one file per converted source. ``convert_excel`` writes
      ``<stem>_Data.txt`` beside each workbook's PDF, and the product says so in
      its own words: *"Do NOT update manifest - _Data.txt is an untracked
      sidecar"* (``converters/post_processing.py``). The registry has declared
      ``"sidecar": "_Data.txt"`` all along; nothing read it, so the first
      Excel row of the matrix reported the sidecar as an orphan at HIGH -
      "wrongfully shows up as new", which is the opposite of what happens.

    A sidecar is matched by SUFFIX because its stem is the workbook's, which
    this function has no way to enumerate. ``_Data.txt`` is distinctive enough
    that a Canvas file colliding with it would be a deliberate act.
    """
    out = set()
    on = _converters_on(ev)
    for key, spec in CONVERTERS.items():
        if on.get(key) and spec.get("aggregate"):
            out.add(_key(spec["aggregate"]))
    return out


def _new_version_originals(ev: Evidence) -> set[str]:
    """Files the app deliberately forked and handed to the user.

    When a sync would overwrite a file you have edited (or that is open in
    another program), the engine writes the fresh copy as
    ``<stem>_NewVersion<ext>`` and leaves yours alone - "Saved next to your
    copy, which was left untouched". The manifest row then follows the NEW
    copy, because that is what the app's download of the Canvas file now is,
    and your edited original is left untracked ON PURPOSE.

    The untracked check called that a "wrongfully shows up as new" defect, and
    its stated consequence was testable, so it was tested: seed an edited file,
    sync, then sync the same folder AGAIN. The second pass reported "Sync done
    - everything up to date. Checked 50 files in this course - your folder
    already matches Canvas." It is never re-offered. The premise was false, and
    the product is keeping exactly the promise its own completion screen makes.

    The fork is identified by the SIBLING, not by any manifest state, because
    the whole point is that the original no longer has a row.
    """
    out: set[str] = set()
    for f in ev.disk.get("files", []):
        if not f.get("new_version"):
            continue
        rel = f["rel"]
        stem, _, ext = rel.rpartition(".")
        base = (stem or rel).replace("_NewVersion", "")
        out.add(_key(f"{base}.{ext}" if ext and stem else base))
    return out


def _conversion_sidecars(ev: Evidence) -> tuple[str, ...]:
    """Per-source converter outputs, as filename suffixes to match on."""
    on = _converters_on(ev)
    return tuple(spec["sidecar"].lower() for key, spec in CONVERTERS.items()
                 if on.get(key) and spec.get("sidecar"))


def _infer_extracted_roots(ev: Evidence) -> set[str]:
    """Folders that came from unpacking an archive.

    ``extract_archive`` writes into ``<archive>.with_suffix('')`` and then
    deletes the archive, so the giveaway is a manifest row whose ``local_path``
    is an archive alongside a directory of the same stem. Inferred rather than
    required as input, so the exemption still works when the caller does not
    know which archives a course happened to contain.
    """
    roots: set[str] = set()
    for r in ev.db.get("rows", []):
        lp = r.get("local_path", "")
        if Path(lp).suffix.lower() in CONVERTERS["convert_zip"]["sources"]:
            roots.add(str(Path(lp).with_suffix("")).replace("\\", "/"))
    known = {_key(d) for d in ev.disk.get("dirs", [])}
    return {r for r in roots if _key(r) in known}


def _key(p: str) -> str:
    """Case- and separator-insensitive path key, ALWAYS forward-slashed.

    The slash normalisation has to come AFTER ``normcase``, not before: on
    Windows ``os.path.normcase`` lowercases *and* rewrites ``/`` back to ``\\``,
    so normalising first and lowercasing second silently hands back a
    backslashed key. That is invisible while both sides of a comparison go
    through this function, and breaks the moment one side builds a prefix -
    ``_key(root) + "/"`` produced ``a\\b/`` and matched nothing, which is how
    21,631 archive files stayed in the orphan count after being exempted.
    """
    return os.path.normcase(str(p)).replace("\\", "/").strip("/")


def _norm(name: str) -> str:
    return os.path.normcase(Path(str(name).replace("\\", "/")).name.strip())


# " (1)", " (2)" ... appended by the engine's own disk-conflict resolution.
_CONFLICT_SUFFIX = re.compile(r"\s\(\d+\)(?=\.[^.]*$|$)")


def _norm_unconflicted(name: str) -> str:
    """A filename with the app's own conflict suffix removed.

    The engine resolves a disk collision by appending " (N)" BEFORE it tries to
    download, so an error is logged under the deduplicated name while Canvas
    and the module item still know the original. Measured on course 43660:
    the log says ``Sensemaking slides 1 (1).pptx`` is locked, the module item
    is titled ``Sensemaking slides 1.pptx`` - a name-to-id map built from
    Canvas therefore matched nothing, and the two locked files were reported as
    a discovery gap instead of being excluded from it.
    """
    return _CONFLICT_SUFFIX.sub("", _norm(name))


def _stem(name: str) -> str:
    """Filename without its extension, normalised.

    The unit of comparison across all five oracles: the review screen splits the
    extension into its own chip, the manifest may carry a post-conversion
    extension while the fixture remembers the original, and the log prints
    whichever the engine last wrote. The stem is the only part all of them agree
    on.
    """
    return os.path.normcase(Path(str(name).replace("\\", "/")).stem.strip())


def _tokens(text: str) -> list[str]:
    """Filenames plausibly present in a rendered review row."""
    out = []
    for part in re.split(r"\s*\|\s*|\s{2,}", text or ""):
        part = part.strip()
        if part and ("." in part or len(part) > 3):
            out.append(_norm(part))
    return out
