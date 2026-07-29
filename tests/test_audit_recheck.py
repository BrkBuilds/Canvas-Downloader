"""A finding is a function of (evidence, checker) - only the evidence is dear.

A lane worker imports ``crosscheck`` once, when it starts. So a checker defect
fixed forty minutes into a six-hour run keeps producing the OLD verdict for
every row after it. That happened: the Excel ``_Data.txt`` sidecar false HIGH
was fixed mid-run, and without re-deriving, every later Excel row would have
carried it into the register as a product defect.

This is also why a row harvests its manifest, its full-hash disk scan, its log
slice and its UI capture before deleting the payload: between them they are
everything the checks read, so re-deriving costs seconds and needs no network,
no browser and no re-download.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import parallel as P            # noqa: E402
from tests.audit.harness.paths import RunPaths           # noqa: E402


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """A parent run with one lane, one job, and complete evidence for it."""
    monkeypatch.setattr("tests.audit.harness.paths.RUNS_ROOT", tmp_path)
    monkeypatch.setattr("tests.audit.harness.parallel.RunPaths",
                        lambda rid: _rp(tmp_path, rid))
    parent = _rp(tmp_path, "parent")
    lrp = _rp(tmp_path, "parent__free1")

    (parent.root / "lanes.json").write_text(json.dumps(
        {"parent": "parent", "lanes": [{"lane": "free1",
                                        "run_id": "parent__free1"}]}),
        encoding="utf-8")
    (lrp.root / "lane_spec.json").write_text(json.dumps(
        {"lane": "free1", "jobs": [{"id": "m000", "kind": "download",
                                    "course_id": 1, "course_ids": [1],
                                    "config": {"mode": "flat"}}]}),
        encoding="utf-8")
    return parent, lrp


def _rp(root, rid):
    rp = RunPaths(rid)
    rp.root = root / rid
    rp.config = rp.root / "config"
    rp.downloads = rp.root / "downloads"
    rp.evidence = rp.root / "evidence"
    rp.ui = rp.evidence / "ui"
    rp.canvas = rp.evidence / "canvas"
    rp.logs = rp.evidence / "logs"
    rp.findings = rp.root / "findings.jsonl"
    for d in (rp.root, rp.evidence, rp.ui, rp.canvas, rp.logs, rp.downloads):
        d.mkdir(parents=True, exist_ok=True)
    return rp


def _complete_evidence(lrp, label="m000"):
    (Path(lrp.evidence) / f"disk_{label}.json").write_text(json.dumps(
        {"exists": True, "files": [], "content_count": 0, "partials": [],
         "zero_bytes": [], "long_paths": [], "app_generated": [],
         "secondary_html": [], "dirs": [], "duplicate_groups": []}),
        encoding="utf-8")
    rows = Path(lrp.evidence) / "rows" / label
    rows.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(rows / ".canvas_sync.db")
    con.execute("CREATE TABLE sync_metadata (key TEXT, value TEXT)")
    con.execute("INSERT INTO sync_metadata VALUES ('course_id','1')")
    con.execute("CREATE TABLE sync_manifest (canvas_file_id INT, "
                "canvas_filename TEXT, local_path TEXT, canvas_updated_at TEXT, "
                "downloaded_at TEXT, original_size INT, is_ignored INT, "
                "original_md5 TEXT, content_sig TEXT)")
    con.commit(); con.close()
    (Path(lrp.canvas) / "course_1.json").write_text(json.dumps(
        {"course_id": 1, "files_tab": {}, "modules": [],
         "expected_file_ids": []}), encoding="utf-8")


def test_a_row_with_complete_evidence_is_rechecked(lane):
    parent, lrp = lane
    _complete_evidence(lrp)
    res = P.recheck(parent)
    assert res["skipped"] == []
    assert (lrp.root / "findings.rechecked.jsonl").is_file()


def test_a_row_with_no_evidence_is_REPORTED_not_skipped_silently(lane):
    """A row missing from a re-check is a row nobody is checking."""
    parent, lrp = lane
    res = P.recheck(parent)
    assert [s["row"] for s in res["skipped"]] == ["m000"]


def test_recheck_replaces_rather_than_appends(lane):
    """Re-deriving twice must not double every finding."""
    parent, lrp = lane
    _complete_evidence(lrp)
    a = P.recheck(parent)["lanes"][0]["findings"]
    b = P.recheck(parent)["lanes"][0]["findings"]
    assert a == b
    lines = (lrp.root / "findings.rechecked.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert len(lines) == b


def test_recheck_never_touches_the_as_run_findings(lane):
    parent, lrp = lane
    lrp.findings.write_text('{"title":"as-run","severity":"high"}\n',
                            encoding="utf-8")
    _complete_evidence(lrp)
    P.recheck(parent)
    assert "as-run" in lrp.findings.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# collect chooses its source explicitly
# --------------------------------------------------------------------------

def test_collect_defaults_to_what_the_workers_wrote(lane):
    parent, lrp = lane
    lrp.findings.write_text(
        '{"title":"as-run","category":"x","scenario":"m000"}\n', encoding="utf-8")
    (lrp.root / "findings.rechecked.jsonl").write_text(
        '{"title":"rechecked","category":"x","scenario":"m000"}\n', encoding="utf-8")
    P.collect(parent)
    assert "as-run" in parent.findings.read_text(encoding="utf-8")


def test_collect_rechecked_merges_the_re_derived_verdicts(lane):
    parent, lrp = lane
    lrp.findings.write_text(
        '{"title":"as-run","category":"x","scenario":"m000"}\n', encoding="utf-8")
    (lrp.root / "findings.rechecked.jsonl").write_text(
        '{"title":"rechecked","category":"x","scenario":"m000"}\n', encoding="utf-8")
    res = P.collect(parent, rechecked=True)
    assert res["source"] == "rechecked"
    body = parent.findings.read_text(encoding="utf-8")
    assert "rechecked" in body and "as-run" not in body


def test_a_lane_with_no_findings_file_is_reported(lane):
    """The merge otherwise succeeds and reports a total quietly short by a
    whole lane."""
    parent, _ = lane
    res = P.collect(parent, rechecked=True)
    assert res["missing_lanes"], res


# --------------------------------------------------------------------------
# an empty lane is not a missing lane
# --------------------------------------------------------------------------

def test_a_clean_lane_produces_an_EMPTY_file_not_no_file(lane):
    parent, lrp = lane
    _complete_evidence(lrp)
    P.recheck(parent)
    p = lrp.root / "findings.rechecked.jsonl"
    assert p.is_file(), "a clean lane would be reported as never re-checked"
    assert p.read_text(encoding="utf-8").strip() == ""


def test_a_clean_lane_is_not_reported_as_missing(lane):
    parent, lrp = lane
    _complete_evidence(lrp)
    P.recheck(parent)
    assert "missing_lanes" not in P.collect(parent, rechecked=True)


# --------------------------------------------------------------------------
# a finished lane is not a dead lane
# --------------------------------------------------------------------------
#
# On a resumed run a lane whose rows are all complete exits in under a second
# with returncode 0. The startup-liveness check treated ANY early exit as
# death, so it reported the finished lane as broken and TERMINATED its
# still-working siblings - turning a clean resume into a stopped run.

class _Proc:
    def __init__(self, rc): self._rc = rc; self.terminated = False
    def poll(self): return self._rc
    def terminate(self): self.terminated = True


@pytest.mark.parametrize("rc,is_dead", [(0, False), (1, True), (255, True),
                                        (None, False)])
def test_only_a_nonzero_early_exit_counts_as_death(rc, is_dead):
    """`poll()` returns None while running, else the exit code."""
    assert (_Proc(rc).poll() not in (None, 0)) is is_dead


def test_the_check_reads_the_return_code_not_merely_liveness():
    import re
    from pathlib import Path as _P
    src = _P(REPO / "tests/audit/harness/parallel.py").read_text(encoding="utf-8")
    src = re.sub(r"^\s*#.*$", "", src, flags=re.M)
    assert 'd["proc"].poll() not in (None, 0)' in src, \
        "a lane that finished early is being reported as dead again"
