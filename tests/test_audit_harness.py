"""Guards for the live-audit harness itself.

An audit suite that is quietly wrong is worse than no audit suite: it reports
green and stops anyone looking. These tests cover the three ways this harness
could become quietly wrong.

1. The isolation seam stops working, and a run writes over the developer's real
   settings, sync pairs and history.
2. The covering array stops covering, and the "100% of 2-way combinations"
   claim in the report becomes a lie.
3. The restated contracts in ``crosscheck.py`` drift away from the code they
   describe. Those are duplicated ON PURPOSE - importing the app's own tables
   would make the expectation agree with the implementation by construction -
   so the duplication needs a guard, which is what ``test_converter_contract``
   and ``test_secondary_offsets`` are.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import crosscheck, matrix          # noqa: E402
from tests.audit.harness.oracles import db as odb           # noqa: E402
from tests.audit.harness.oracles import disk as odisk       # noqa: E402
from tests.audit.harness.oracles import log as olog         # noqa: E402
from tests.audit.harness.seed import Seeder                 # noqa: E402


# ---------------------------------------------------------------- isolation

def _fresh_helpers():
    """Re-import shared.helpers so the env var is read at call time, not cached."""
    import shared.helpers as h
    return importlib.reload(h)


def test_config_dir_override_isolates_state(tmp_path, monkeypatch):
    target = tmp_path / "isolated"
    target.mkdir()
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(target))
    h = _fresh_helpers()
    assert Path(h.get_config_dir()) == target


def test_config_dir_override_ignored_when_missing(tmp_path, monkeypatch):
    """A bad path must fall through, never silently create an empty config dir.

    An empty config dir looks to the app exactly like a fresh install, which
    signs the user out - a far worse failure than ignoring a typo.
    """
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path / "does-not-exist"))
    h = _fresh_helpers()
    assert Path(h.get_config_dir()) == Path(h._REPO_ROOT)


def test_config_dir_default_unchanged(monkeypatch):
    monkeypatch.delenv("CANVAS_DL_CONFIG_DIR", raising=False)
    h = _fresh_helpers()
    assert Path(h.get_config_dir()) == Path(h._REPO_ROOT)


def test_every_state_file_routes_through_get_config_dir():
    """No state file may be written to a hard-coded path.

    The seam only isolates what goes through ``get_config_dir()``. A new manager
    that joins its filename onto the repo root instead would escape isolation
    and let an audit trample real data - invisibly, because the audit would
    still pass.
    """
    names = ("canvas_sync_pairs.json", "canvas_sync_history.json",
             "saved_sync_groups.json", "saved_download_presets.json",
             "canvas_downloader_settings.json", "today_dashboard.json")
    offenders = []
    for py in REPO.rglob("*.py"):
        parts = set(py.parts)
        if parts & {"dist", "build", "__pycache__", "tests", "_audit_runs", "scripts"}:
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if any(n in line for n in names) and "_REPO_ROOT" in line:
                offenders.append(f"{py.relative_to(REPO)}: {line.strip()[:110]}")
    assert not offenders, (
        "State file joined onto the repo root instead of get_config_dir(); "
        "this escapes audit isolation:\n" + "\n".join(offenders))


# ------------------------------------------------------------ covering array

def test_pairwise_coverage_is_complete():
    plan = matrix.build_plan()
    cov = plan["coverage_2way"]
    assert cov["percent"] == 100.0, (
        f"2-way coverage dropped to {cov['percent']}%; "
        f"uncovered: {cov['uncovered_examples'][:5]}")


def test_triple_coverage_on_interacting_factors():
    plan = matrix.build_plan()
    cov = plan["coverage_3way_interacting"]
    assert cov["percent"] == 100.0, cov["uncovered_examples"][:5]


def test_plan_is_deterministic():
    """Two runs must produce the identical list, or runs cannot be compared
    against their own history and a regression looks like a reshuffle."""
    a = [dict(sorted(r.items())) for r in matrix.build_plan()["runs"]]
    b = [dict(sorted(r.items())) for r in matrix.build_plan()["runs"]]
    assert a == b


def test_plan_emits_only_reachable_configurations():
    for run in matrix.build_plan()["runs"]:
        assert matrix.constraints_ok(run), run


def test_every_factor_level_appears():
    runs = matrix.build_plan()["runs"]
    for f in matrix.DOWNLOAD_FACTORS:
        seen = {r.get(f.name) for r in runs}
        for lv in f.levels:
            probe = {g.name: (lv if g.name == f.name else g.levels[0])
                     for g in matrix.DOWNLOAD_FACTORS}
            if matrix.constraints_ok(probe) or lv in seen:
                assert lv in seen, f"{f.name}={lv!r} never exercised"


# --------------------------------------------------------- contract drift

def test_converter_contract_matches_the_pipeline():
    """The restated converter table must still describe the real globs.

    ``crosscheck.CONVERTERS`` is a deliberate duplicate of what
    ``converters/post_processing.py`` does. Duplicated so the expectation is
    independent of the implementation - but an independent expectation that has
    silently gone stale asserts the wrong thing, so the two are compared here
    rather than in the checks themselves.
    """
    src = (REPO / "converters" / "post_processing.py").read_text(encoding="utf-8")
    globs = {}
    for m in re.finditer(r"(\w+)\s*=\s*_glob_files\(course_folder,\s*\{([^}]*)\}", src):
        exts = {e.strip().strip("'\"").lower()
                for e in m.group(2).split(",") if e.strip()}
        globs[m.group(1)] = exts

    expected = {
        "pptx_files": crosscheck.CONVERTERS["convert_pptx"]["sources"],
        "html_files": crosscheck.CONVERTERS["convert_html"]["sources"],
        "word_files": crosscheck.CONVERTERS["convert_word"]["sources"],
        "video_files": crosscheck.CONVERTERS["convert_video"]["sources"],
    }
    for var, want in expected.items():
        assert var in globs, f"{var} no longer built with _glob_files - contract moved"
        assert globs[var] == want, (
            f"{var} now globs {sorted(globs[var])} but crosscheck.CONVERTERS "
            f"expects {sorted(want)}. Update the table in crosscheck.py.")

    # .docx must stay OUT of the legacy-Word set: expecting a PDF beside every
    # Word file would make the audit report correct behaviour as a defect.
    assert ".docx" not in crosscheck.CONVERTERS["convert_word"]["sources"]
    assert ".docx" not in globs["word_files"]


def test_code_extensions_match():
    from converters.code import CODE_EXTENSIONS
    assert crosscheck.CONVERTERS["convert_code"]["sources"] == CODE_EXTENSIONS


def test_secondary_offsets_match():
    from core.sync_manager import SECONDARY_ID_OFFSETS
    assert odb.SECONDARY_OFFSETS == SECONDARY_ID_OFFSETS


@pytest.mark.parametrize("fid,want", [
    (12345, "file"), (-1, "module_item"), (-10_000_042, "assignment"),
    (-80_000_000, "submission"), (-90_000_001, "attachment"),
    (-50_107_373, "quiz"), (-40_167_903, "discussion"),
])
def test_entity_type_classification(fid, want):
    assert odb.entity_type(fid) == want


# ------------------------------------------------------------- log parsing

def test_log_parser_reads_a_sync_run():
    sample = """--- Debug Log Started: 2026-07-27 15:19:42 ---
[2026-07-27 15:19:42.228] === Sync Analysis: Course X (ID: 43660) ===
[2026-07-27 15:19:42.228] Mode: Quick Sync
[2026-07-27 15:19:52.549] Analysis complete (67 ms): 2 new | 6 clean updates | 1 locally-edited updates | 3 deleted on Canvas | 4 deleted locally
[2026-07-27 15:19:52.550]   [NEW]          Alpha.docx
[2026-07-27 15:19:52.550]   [UPDATE-CLEAN] Beta.pdf
[2026-07-27 15:19:54.791]   → [new file] Alpha.docx → Module 1\\Alpha.docx
[2026-07-27 15:19:55.741] ✓ Alpha.docx
[2026-07-27 15:19:56.306] This pair: 8 files synced | Total across all pairs: 8 | Errors: 0 | PP failures: 0
"""
    p = Path(os.environ.get("PYTEST_TMP", ".")) / "_audit_log_sample.txt"
    p.write_text(sample, encoding="utf-8")
    try:
        s = olog.parse_and_summarize(p)
        assert s["analysis"] == {"new": "2", "clean": "6", "modified": "1",
                                 "candel": "3", "locdel": "4"}
        assert s["analysis_rows"]["NEW"] == ["Alpha.docx"]
        assert s["analysis_rows"]["UPDATE-CLEAN"] == ["Beta.pdf"]
        assert s["sync_ok"] == ["Alpha.docx"]
        assert s["sync_totals"]["errors"] == "0"
        assert s["tracebacks"] == 0
    finally:
        p.unlink(missing_ok=True)


def test_log_parser_captures_tracebacks_whole():
    sample = """[2026-07-27 15:19:42.228] Something failed
--- traceback ---
Traceback (most recent call last):
  File "x.py", line 1, in <module>
    boom()
ValueError: boom
-----------------
[2026-07-27 15:19:43.000] Carrying on
"""
    p = Path("_audit_tb_sample.txt")
    p.write_text(sample, encoding="utf-8")
    try:
        parsed = olog.parse(p)
        assert len(parsed.tracebacks) == 1
        assert "ValueError: boom" in parsed.tracebacks[0]["text"]
    finally:
        p.unlink(missing_ok=True)


def test_benign_warnings_do_not_become_findings():
    sample = ("[2026-07-27 15:19:49.782] [WARNING] [core.canvas_logic] Hybrid Fetch: "
              "Found 93 files in Modules that were missing from 'Files' tab.\n")
    p = Path("_audit_warn_sample.txt")
    p.write_text(sample, encoding="utf-8")
    try:
        assert olog.parse_and_summarize(p)["unexpected"] == []
    finally:
        p.unlink(missing_ok=True)


# ------------------------------------------------------------- disk oracle

@pytest.mark.parametrize("name,expected", [
    ("notes.pdf.part", True),      # file engine
    ("recording.part.mp4", True),  # Panopto ffmpeg downloader
    ("notes.pdf", False),
    ("a.partial.pdf", False),
])
def test_partial_artifact_detection(name, expected):
    assert odisk._is_partial(name) is expected


def test_disk_scan_flags_the_things_that_matter(tmp_path):
    (tmp_path / "good.pdf").write_bytes(b"x" * 100)
    (tmp_path / "empty.pdf").write_bytes(b"")
    (tmp_path / "half.pdf.part").write_bytes(b"x" * 10)
    (tmp_path / "debug_log.txt").write_text("log", encoding="utf-8")
    (tmp_path / "Notes_NewVersion.pdf").write_bytes(b"y" * 50)
    sub = tmp_path / "Module 1"
    sub.mkdir()
    (sub / "deep.pdf").write_bytes(b"z" * 20)

    r = odisk.scan(tmp_path)
    assert r["zero_bytes"] == ["empty.pdf"]
    assert r["partials"] == ["half.pdf.part"]
    assert r["new_versions"] == ["Notes_NewVersion.pdf"]
    assert "debug_log.txt" in r["app_generated"]
    # app-generated and partial files are excluded from content
    assert r["content_count"] == 4
    assert r["max_depth"] == 1


def test_disk_diff_separates_changed_from_rewritten(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"one")
    before = odisk.scan(tmp_path)
    f.write_bytes(b"two-different-length")
    after = odisk.scan(tmp_path)
    d = odisk.diff(before, after)
    assert d["changed_count"] == 1 and d["added_count"] == 0


# ---------------------------------------------------------------- seeder

def test_every_declared_fixture_kind_is_implemented():
    for kind in Seeder.ALL:
        assert callable(getattr(Seeder, kind, None)), f"{kind} declared but missing"


def test_rename_fixtures_cover_both_healing_paths():
    """The rename fixtures must keep testing DIFFERENT mechanisms.

    ``renamed_row_intact`` exercises heal_manifest Tier 2 (local md5 + size);
    ``renamed_row_dropped`` exercises the analyzer's weak size+extension
    fallback because healing cannot run without a row. Collapsing them into one
    fixture would silently stop testing one of the two.
    """
    import inspect
    intact = inspect.getsource(Seeder.renamed_row_intact)
    dropped = inspect.getsource(Seeder.renamed_row_dropped)
    assert "_drop_row" not in intact, "row must survive for healing to run"
    assert "_drop_row" in dropped, "row must be dropped to bypass healing"
    assert "unique_size_ext=True" in dropped, "tier (c) needs a unique size+ext"


def test_ambiguous_and_substitution_expect_refusal():
    import inspect
    amb = inspect.getsource(Seeder.renamed_ambiguous)
    sub = inspect.getsource(Seeder.renamed_substitution)
    assert 'expect_category="new"' in amb
    assert 'expect_category="deleted_locally"' in sub


# ------------------------------------------------------------- crosscheck

def test_invariants_flag_a_broken_manifest(tmp_path):
    ev = crosscheck.Evidence(
        folder=tmp_path,
        disk={"exists": True, "files": [], "content_count": 0, "partials": [],
              "zero_bytes": [], "long_paths": [], "app_generated": [],
              "secondary_html": [], "dirs": []},
        db={"exists": True, "rows": [
            {"canvas_file_id": 1, "canvas_filename": "gone.pdf",
             "local_path": "gone.pdf", "is_ignored": False, "entity": "file",
             "original_size": 10, "original_md5": "abc"}]},
        log={"tracebacks": 0, "unexpected": [], "total_lines": 0})
    titles = [f.title for f in crosscheck.invariants(ev)]
    assert any("do not exist" in t for t in titles)


def test_invariants_exempt_seeded_untracked_files(tmp_path):
    disk = {"exists": True, "content_count": 1, "partials": [], "zero_bytes": [],
            "long_paths": [], "app_generated": [], "secondary_html": [], "dirs": [],
            "files": [{"rel": "decoy.pdf", "name": "decoy.pdf", "size": 5,
                       "ext": ".pdf", "app_generated": False, "partial": False,
                       "secondary_html": False, "new_version": False, "md5": "z"}]}
    base = dict(folder=tmp_path, disk=disk, db={"exists": True, "rows": []},
                log={"tracebacks": 0, "unexpected": [], "total_lines": 0})

    noisy = crosscheck.invariants(crosscheck.Evidence(**base))
    assert any("no manifest row" in f.title for f in noisy)

    quiet = crosscheck.invariants(crosscheck.Evidence(
        **base, expect={"expected_untracked": ["decoy.pdf"]}))
    assert not any("no manifest row" in f.title for f in quiet)


def test_finding_rejects_unknown_severity_and_category():
    from tests.audit.harness.findings import Finding
    with pytest.raises(ValueError):
        Finding(title="x", severity="catastrophic")
    with pytest.raises(ValueError):
        Finding(title="x", category="vibes")


# ---------------------------------------------------------------------------
# The Panopto acceptable-use notice is raised BY the primary action's click
# ---------------------------------------------------------------------------
#
# `shared.legal.require_panopto_notice` is called from four places - the
# download settings' Confirm handler, Quick Download's, the sync page's Analyze
# handler and the sync review's - and every one of them is an ACTION callback.
# None renders at page-render time. So a driver that probes for the dialog
# BEFORE clicking the action can never see it: on a fresh CANVAS_DL_CONFIG_DIR
# (which every audit run has) the row clicks Confirm, the dialog opens, and each
# later wait reports a phase that never started.
#
# Measured on macOS 26.6 2026-08-11 with the dialog on screen: the wizard still
# read step `configure`, and both `download_running_or_done` and
# `download_terminal` evaluated false - i.e. 900s + 5400s of dead wait for a row
# that had simply not been answered.
#
# These guard the ORDERING, not the mere presence of a call, because the first
# version of this fix had the call and was still blind.

def _flows_src() -> str:
    return (REPO / "tests" / "audit" / "harness" / "flows.py").read_text(encoding="utf-8")


def _func_body(src: str, name: str) -> str:
    import ast
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{name} not found in flows.py")


def test_download_answers_the_panopto_notice_AFTER_the_confirm_click():
    body = _func_body(_flows_src(), "confirm_and_run")
    click = body.index('click("action_dl_confirm"')
    waits = [i for i in range(len(body))
             if body.startswith("_accept_panopto_notice(wait_s=", i)]
    assert waits, ("confirm_and_run must answer the notice with a WAIT after the "
                   "click that raises it; a bare pre-click probe cannot see it")
    assert any(i > click for i in waits), (
        "the waiting _accept_panopto_notice call must come AFTER "
        "click('action_dl_confirm') - the click is what raises the dialog")


def test_the_notice_helper_is_available_to_the_sync_flow_too():
    """sync_ui.py and ui/sync_review.py raise the same notice from their own
    action handlers, so a Panopto-carrying sync row stalls identically. The
    helper therefore belongs on the base Flow, not on DownloadFlow."""
    import ast
    src = _flows_src()
    tree = ast.parse(src)
    owner = {}
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for fn in cls.body:
            if isinstance(fn, ast.FunctionDef):
                owner[fn.name] = cls.name
    assert owner.get("_accept_panopto_notice") == "Flow", (
        "_accept_panopto_notice must live on the base Flow so SyncFlow inherits "
        f"it; found on {owner.get('_accept_panopto_notice')!r}")
    for fn in ("analyze", "confirm"):
        assert "_accept_panopto_notice(wait_s=" in _func_body(src, fn), (
            f"SyncFlow.{fn} clicks an action that can raise the Panopto notice "
            f"and must answer it")


def test_the_notice_wait_can_exit_early_so_ordinary_rows_pay_nothing():
    """A budget with no early exit taxes every row that will never see the
    dialog. The helper must be able to stop as soon as the action is visibly
    under way - by condition or by a widget that means 'we moved on'."""
    body = _func_body(_flows_src(), "_accept_panopto_notice")
    assert "stop_key" in body and "until" in body
    assert "run_started_first" in body or "moved_on" in body
