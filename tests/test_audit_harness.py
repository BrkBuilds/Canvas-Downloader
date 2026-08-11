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


def test_the_sync_confirm_step_RECORDS_whether_the_notice_was_raised():
    """`SyncFlow.confirm` answered the notice and then dropped the answer.

    Measured 2026-08-11: a completed review sync's trace carried
    `panopto_notice` under `analyze` and nothing at all under `confirm_sync`,
    so "did the review path raise it?" - the one question this step exists to
    answer - was unanswerable from the evidence. It must go into the trace
    under the SAME key `analyze` uses, or a checker reading one and not the
    other silently sees half the runs.
    """
    body = _func_body(_flows_src(), "confirm")
    assert "panopto_notice=" in body, (
        "SyncFlow.confirm must log the notice result as `panopto_notice=`, the "
        "same key SyncFlow.analyze uses")


# ---------------------------------------------------------------------------
# Quick Sync has no review screen, so it has no `confirm` to click
# ---------------------------------------------------------------------------
#
# `flow sync --quick` could never complete: the CLI called `SyncFlow.confirm`
# unconditionally, and `confirm` is a REVIEW-SCREEN action (it clicks
# `btn_sync_selected`, then the Confirm Sync dialog). Quick Sync skips review by
# design and, because `sync_past_analysis` counts `sync` as an arrival, is
# already RUNNING by the time `analyze` returns.
#
# Measured on macOS 26.6, 2026-08-11: `flow sync p3quick --quick` died with
# `no host for key btn_sync_selected` - which reads as a missing button on the
# app rather than as the wrong action for the mode, and would have been filed
# against the product by anyone who did not read the flow.

def _cli_sync_branch() -> str:
    src = (REPO / "tests" / "audit" / "cli.py").read_text(encoding="utf-8")
    i = src.index('elif c == "sync":')
    j = src.index('elif c == "today":', i)
    return src[i:j]


def _enclosing_if_tests(src: str, want_attr: str) -> "list[list[str]]":
    """For every `<x>.<want_attr>(...)` call in *src*, the `if` tests above it.

    A parent map rather than a hand-rolled walk: the first version of this
    helper recursed and lost a level, so it reported a call as unguarded when
    the guard was right there - a test that fails against correct code is
    worse than no test.
    """
    import ast
    tree = ast.parse(src)
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == want_attr):
            continue
        tests, cur = [], node
        while cur in parent:
            up = parent[cur]
            # Only a statement in the BODY (or orelse) of an `if` is guarded by
            # it; the test expression itself is not.
            if isinstance(up, ast.If):
                if any(cur is s for s in up.body):
                    tests.append(ast.unparse(up.test))
                elif any(cur is s for s in up.orelse):
                    tests.append("not (" + ast.unparse(up.test) + ")")
            cur = up
        out.append(tests)
    return out


def test_the_helper_that_reads_guards_can_actually_see_one():
    """Positive control. Without it, a helper that finds no guards anywhere
    would make every assertion below vacuous.

    Compared as a SET: `ast.walk` is breadth-first, so it reaches the shallow
    `else` arm before the nested one and source order is not what comes back.
    """
    src = ("def f():\n"
           "    if landed == 'review':\n"
           "        if ok:\n"
           "            res = flow.confirm('x')\n"
           "    else:\n"
           "        res = flow.confirm('y')\n")
    stacks = {tuple(t) for t in _enclosing_if_tests(src, "confirm")}
    assert stacks == {("ok", "landed == 'review'"),
                      ("not (landed == 'review')",)}


def test_quick_sync_does_not_click_the_review_screens_confirm():
    """`confirm` must be reachable only when the run landed on the review
    screen - it clicks `btn_sync_selected`, which no other screen has."""
    stacks = _enclosing_if_tests(_func_body(_flows_src(), "after_analysis"),
                                 "confirm")
    assert stacks, "after_analysis must still confirm a review-screen run"
    for tests in stacks:
        assert any("review" in t for t in tests), (
            "self.confirm() must be guarded by the analysis having landed on "
            f"the review screen; guards seen: {tests}")


def test_neither_runner_calls_confirm_behind_the_shared_decision():
    """A caller that reaches past `after_analysis` is a second copy of the rule
    in the making - which is how these two came to disagree in the first place."""
    par = (REPO / "tests" / "audit" / "harness" / "parallel.py").read_text(encoding="utf-8")
    sources = {
        # cli.py's branch is a fragment, so it needs a wrapper to parse.
        "cli.py": "if True:\n" + "\n".join(
            "    " + ln for ln in _cli_sync_branch().splitlines()[1:]),
        "parallel.py": _func_body(par, "_execute_sync"),
    }
    for who, src in sources.items():
        assert not _enclosing_if_tests(src, "confirm"), (
            f"{who} must route through SyncFlow.after_analysis, not call "
            f"confirm itself")
        assert "wait_terminal(" not in src, (
            f"{who} must not reach past after_analysis to wait itself")


def test_a_quick_sync_is_still_followed_to_its_completion_screen():
    """Abandoning a running sync would leave the next row analysing a folder
    that is still moving under it, so the non-review path must wait."""
    branch = _cli_sync_branch()
    assert "after_analysis" in branch, (
        "the CLI must route through SyncFlow.after_analysis, which follows an "
        "already-started Quick Sync to its terminal screen")


def test_ONE_post_analysis_decision_serves_both_runners():
    """The single-row runner and the matrix runner had two copies of it, and
    only one knew about Quick Sync - so the path an operator reaches for when
    a matrix row looks wrong was broken in exactly that situation."""
    assert "after_analysis" in _cli_sync_branch()
    par = (REPO / "tests" / "audit" / "harness" / "parallel.py").read_text(encoding="utf-8")
    assert "after_analysis" in par, (
        "parallel.py must use the same post-analysis decision as cli.py")


def test_landing_on_complete_is_not_reported_as_up_to_date_without_looking():
    """A Quick Sync that FINISHED is not a Quick Sync that had nothing to do.

    Both land on the completion screen. `analyze`'s settle() waits up to 180s
    for the DOM to go quiet, so a short sync finishes inside it - measured
    2026-08-11: the wizard read `sync` at 2/14 files and `complete` a moment
    later, and the run that downloaded 14 files was recorded as
    "already up to date".
    """
    import ast
    body = _func_body(_flows_src(), "after_analysis")
    tree = ast.parse(body)
    arm = next(n for n in ast.walk(tree)
               if isinstance(n, ast.If) and 'landed == "complete"'
               in ast.unparse(n.test).replace("'", '"'))
    # unparse, so a COMMENT quoting the old label cannot trip this - the same
    # reason verify_architecture.py blanks comments before scanning.
    code = "\n".join(ast.unparse(s) for s in arm.body)
    assert "_why_already_complete" in code, (
        "the complete-arm must ASK the screen which case it is, not hard-code "
        "a label")
    assert "already up to date" not in code, (
        "the literal must live in the prober that checks it, not in the arm "
        "that cannot know")


def test_the_up_to_date_probe_matches_the_card_the_app_actually_renders():
    """Both titles, one substring - and if the app renames the card this fails
    here rather than silently mislabelling every run."""
    import tests.audit.harness.flows as F
    probe = F.SyncFlow._UP_TO_DATE_TITLE
    components = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    for title in ("Quick Sync done - everything up to date",
                  "Sync done - everything up to date"):
        assert f"'{title}'" in components, f"app no longer renders {title!r}"
        assert probe in title, f"{probe!r} does not match {title!r}"


def test_an_unreadable_screen_is_not_reported_as_a_measured_outcome():
    import ast
    body = _func_body(_flows_src(), "_why_already_complete")
    handlers = [h for h in ast.walk(ast.parse(body))
                if isinstance(h, ast.ExceptHandler)]
    assert handlers, "the screen read must be guarded - it drives a browser"
    for h in handlers:
        code = "\n".join(ast.unparse(s) for s in h.body)
        assert "already up to date" not in code, (
            "a failed read must not fall back to claiming the folder was in sync")


def test_confirm_and_quick_share_ONE_definition_of_finished():
    """Two waits for one question is how the two modes come to disagree about
    what 'finished' means - and the checker reads this field."""
    import ast
    src = _flows_src()
    assert "wait_terminal" in _func_body(src, "confirm"), (
        "SyncFlow.confirm must reuse wait_terminal rather than keeping its own "
        "copy of the sync_terminal wait")
    assert 'conditions.get("sync_terminal")' in _func_body(src, "wait_terminal")
    tree = ast.parse(src)
    others = []
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for fn in cls.body:
            if (isinstance(fn, ast.FunctionDef)
                    and fn.name != "wait_terminal"
                    and 'conditions.get("sync_terminal")' in
                    (ast.get_source_segment(src, fn) or "")):
                others.append(f"{cls.name}.{fn.name}")
    assert not others, f"sync_terminal is waited on outside wait_terminal: {others}"


# ---------------------------------------------------------------------------
# Name-based matching in the sync checker (macOS run, 2026-08-11)
# ---------------------------------------------------------------------------
#
# One seeded sync on course 43660 produced TEN highs. The app was correct in
# every case examined; eight were the checker matching files BY NAME. Identity
# lives in the path, never in the name - the same lesson RUNBOOK records for
# `Page X (1).html`.

def _cc():
    import importlib
    return importlib.import_module("tests.audit.harness.crosscheck")


def test_os_metadata_is_not_a_content_file():
    """A `.DS_Store` is written into any folder a user opens in Finder. Counting
    it as an untracked CONTENT file reported the operating system as an
    application defect - at high, claiming it "will be offered as a NEW file on
    every future sync", which is untrue of a file the analyzer never enumerates.
    It would have fired for every macOS user."""
    f = _cc()._is_os_metadata
    for junk in (".DS_Store", "sub/.DS_Store", "._Lecture.pdf", "Thumbs.db",
                 "desktop.ini", "notes/.localized"):
        assert f(junk) is True, junk
    for real in ("Lecture.pdf", "Real._file.pdf", "notes/Uge 13 pensum.html"):
        assert f(real) is False, real


def test_the_secondary_prefix_rule_is_case_insensitive():
    """`_stem` runs through os.path.normcase, WHICH IS THE IDENTITY OFF WINDOWS.
    The prefixes are lowercase, so on Windows the stem arrives lowercased and
    matches, while on macOS it keeps its capital and every secondary-entity rule
    silently fails - the whole half of the matcher was dead on this platform.

    Measured: `Page Uge 13 pensum.html` was placed correctly under New (the
    review screen shows the ENTITY TITLE, "Uge 13 pensum") and was reported as
    "no oracle placed it in any category"."""
    cands = _cc()._name_candidates("Page Uge 13 pensum.html")
    assert "Uge 13 pensum" in cands, (
        f"the 'page ' prefix must strip regardless of case; got {sorted(cands)}")
    # and the original case is preserved, because that is what the screen shows
    assert "uge 13 pensum" not in cands


def test_a_dedup_alias_two_real_names_claim_is_not_evidence():
    """`_DEDUP_SUFFIX` eats ANY trailing number, and these course files are
    `Klyngevejledning 1_grp 10 / 14 / 25`. All three collapse to one alias, so a
    healed file - which is UP TO DATE and therefore appears in no category at
    all - matched the IGNORED row of an unrelated sibling and was reported at
    high as "classified as ignored".

    The alias is only evidence when ONE real name claims it."""
    cc = _cc()
    strip = lambda s: cc._DEDUP_SUFFIX.sub("", s).strip()  # noqa: E731
    assert strip("Klyngevejledning 1_grp 10") == "Klyngevejledning 1_grp"
    assert strip("Klyngevejledning 1_grp 14") == "Klyngevejledning 1_grp"
    # the engine's own dedup suffix must still resolve - that is what the alias
    # is FOR, and over-suppressing it was the first version of this fix
    assert strip("CBS_SolbjergPlads_ImageHeader-1") == "CBS_SolbjergPlads_ImageHeader"


def test_ambiguous_basenames_are_reported_not_asserted():
    """Two fixtures legitimately shared a basename in different folders
    (`Øvelser i uge 16` edited_update, `uge 18` clean_update). The app handled
    both correctly - the edited copy came through byte-identical with the fresh
    copy forked to _NewVersion - and the checker produced FOUR highs, one of
    which reads exactly like data loss."""
    src = (REPO / "tests" / "audit" / "harness" / "crosscheck.py").read_text(
        encoding="utf-8")
    assert "is ambiguous by name - classification not asserted" in src
    # and the _NewVersion outcome check must look at the fixture's OWN path
    assert "fork_rel" in src, (
        "the _NewVersion check must resolve the fork at the fixture's relative "
        "path; a flat basename set sees a fork created for a different file")


# ---------------------------------------------------------------------------
# "-1" IS SOMETIMES CANVAS'S OWN NAME (macOS 26.6 run, 2026-08-11)
# ---------------------------------------------------------------------------
#
# `_DEDUP_SUFFIX` cannot tell the engine's dedup "-1" from a trailing "-1" that
# Canvas put there - and Canvas does. Course 43660 holds THREE distinct files
# whose `filename` is all `CBS_SolbjergPlads_ImageHeader.jpg`; Canvas
# disambiguates them as display names `...ImageHeader.jpg`, `...ImageHeader-1.jpg`
# and `...ImageHeader-1-1.jpg`. The seeder orphans two, so the plan carries one
# fixture named X and one named X-1.
#
# The screen's row for X-1 was then aliased onto X, the X fixture matched the
# OTHER fixture's row, and the run reported a disagreement between two oracles
# that had in fact agreed - both showed exactly one of the pair, which is what
# the app really did.

def _register_aliases(ui_cat: dict, fixtures: list[dict]) -> dict:
    """Drive the REAL alias rule out of crosscheck.py against a tiny plan.

    Extracted by executing the module's own source region would be fragile, so
    this mirrors ONLY the loop under test by calling the module's own
    `_DEDUP_SUFFIX` and `_stem` - the two pieces that decide it.
    """
    cc = _cc()
    out = dict(ui_cat)
    real = set(ui_cat) | {cc._stem(f.get("match_name", "")) for f in fixtures}
    exact = {cc._stem(f.get("match_name", "")) for f in fixtures}
    claims: dict = {}
    for k in list(out):
        s = cc._DEDUP_SUFFIX.sub("", k).strip()
        if s and s != k:
            claims.setdefault(s, set())
            claims[s] |= {n for n in real if n != s
                          and cc._DEDUP_SUFFIX.sub("", n).strip() == s}
    for k in list(out):
        s = cc._DEDUP_SUFFIX.sub("", k).strip()
        if not s or s == k or k in exact:
            continue
        if len(claims.get(s, ())) <= 1:
            out.setdefault(s, out[k])
    return out


def test_a_plan_name_ending_in_a_number_is_not_a_dedup_artefact():
    """The measured false positive: two fixtures, X and X-1, both real."""
    cc = _cc()
    x = cc._stem("CBS_SolbjergPlads_ImageHeader.jpg")
    x1 = cc._stem("CBS_SolbjergPlads_ImageHeader-1.jpg")
    fixtures = [{"match_name": "CBS_SolbjergPlads_ImageHeader.jpg"},
                {"match_name": "CBS_SolbjergPlads_ImageHeader-1.jpg"}]
    got = _register_aliases({x1: "new"}, fixtures)
    assert got.get(x) is None, (
        "the row for X-1 must not be lent to the fixture named X - they are "
        "different Canvas files")


def test_the_engines_real_dedup_suffix_still_resolves():
    """The other direction, and the one the alias exists for: no fixture is
    called X-1, so X-1 on screen really is the engine's output for X."""
    cc = _cc()
    x = cc._stem("Report.pdf")
    x1 = cc._stem("Report-1.pdf")
    got = _register_aliases({x1: "new"}, [{"match_name": "Report.pdf"}])
    assert got.get(x) == "new", (
        "over-suppressing the alias was the first version of this guard, and "
        "it broke every genuine dedup match")


def test_the_guard_is_wired_into_the_real_module():
    src = (REPO / "tests" / "audit" / "harness" / "crosscheck.py").read_text(
        encoding="utf-8")
    assert "_exact_plan_names" in src
    assert "k in _exact_plan_names" in src, (
        "the alias loop must skip a screen name the plan carries verbatim")


# ---------------------------------------------------------------------------
# "no oracle placed it" was a claim the branch had not checked
# ---------------------------------------------------------------------------

def test_absence_from_one_oracle_is_not_absence_from_all():
    """The old wording pointed the reader at a blind spot in the harness rather
    than at the app, and cost a session: the next run went looking for an
    oracle-selection bug that did not exist. Three situations, three answers."""
    src = (REPO / "tests" / "audit" / "harness" / "crosscheck.py").read_text(
        encoding="utf-8")
    assert "no oracle placed it in any category" not in src, (
        "that title claims something the branch never verified")
    assert "was not offered as" in src, "the genuinely-absent case needs a title"
    assert "but absent from" in src, "the two-oracle disagreement needs its own"
    # matched on a fragment that survives the source line-wrap; the full
    # sentence is split across two f-string pieces
    assert "oracle can see that category this run" in src, (
        "a log with no rows for the wanted category is BLIND, not evidence of "
        "absence - that must be an observation, not a high")


def test_the_blind_case_is_not_reported_as_a_defect():
    """`_LOG_DETAILED_CATS` exists because the log writes per-file rows for only
    two categories. Where it wrote none at all, absence proves nothing."""
    import ast
    src = (REPO / "tests" / "audit" / "harness" / "crosscheck.py").read_text(
        encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_categories_match")
    body = ast.unparse(fn)
    i = body.index("no oracle can see that category this run")
    # the nearest constructor before it must be `observation(`, not a disagreement
    assert "observation(" in body[max(0, i - 400):i], (
        "the blind case must be an observation")


# ---------------------------------------------------------------------------
# An IGNORED manifest row comes in two shapes (macOS 26.6 run, 2026-08-11)
# ---------------------------------------------------------------------------
#
# `SyncManager.ignore_file` is an UPSERT. A brand-new file INSERTs with
# `local_path=''` - nothing was written, and that is also how the engine records
# what it skipped. An ALREADY-DOWNLOADED file takes the `ON CONFLICT ... SET
# is_ignored = 1` arm, which leaves `local_path` and `downloaded_at` intact with
# the file still on disk.
#
# The oracle dropped BOTH from `tracked`, so the second shape read as an orphan:
# measured on course 43660, the two ignored fixtures were reported as "2 content
# file(s) on disk with no manifest row" at HIGH, whose detail says they "will be
# re-offered as New forever". They will not - the analyzer has a row and files
# them under Ignored, which is where the review screen showed them.

def _reconcile(rows: list[dict], files: list[dict]) -> dict:
    return odb.reconcile_with_disk(
        {"exists": True, "rows": rows},
        {"exists": True, "files": files})


def _row(fid, path, ignored=False, size=10):
    return {"canvas_file_id": fid, "canvas_filename": Path(path).name if path else "",
            "local_path": path, "is_ignored": ignored, "entity": "file",
            "original_size": size, "original_md5": "", "content_sig": ""}


def _file(rel, size=10):
    return {"rel": rel, "size": size, "ext": Path(rel).suffix.lower(),
            "app_generated": False, "partial": False, "secondary_html": False,
            "new_version": False, "md5": ""}


def test_an_ignored_row_with_a_file_on_disk_is_not_an_orphan():
    """The measured false positive: the user ignored a file they already had."""
    rec = _reconcile([_row(1, "notes.pdf", ignored=True)], [_file("notes.pdf")])
    assert [u["rel"] for u in rec["untracked_on_disk"]] == [], (
        "an ignored row accounts for its own file")
    assert rec["ignored_on_disk"], "and it must be visible in the evidence"


def test_an_ignored_row_with_no_path_is_still_dropped():
    """The other shape - the engine's record of a file it never wrote. Keying
    them all on '' made 23 of them collide as duplicate local paths."""
    rec = _reconcile([_row(1, "", ignored=True), _row(2, "", ignored=True)], [])
    assert rec["duplicate_local_paths"] == {}
    assert rec["missing_on_disk"] == []


def test_a_genuinely_untracked_file_is_still_reported():
    """The direction that matters: the fix must not blind the check."""
    rec = _reconcile([_row(1, "notes.pdf", ignored=True)],
                     [_file("notes.pdf"), _file("stranger.pdf")])
    assert [u["rel"] for u in rec["untracked_on_disk"]] == ["stranger.pdf"]


def test_an_ignored_row_whose_file_the_user_deleted_is_not_a_broken_row():
    """They told the app to leave it alone; deleting it is their business."""
    rec = _reconcile([_row(1, "gone.pdf", ignored=True)], [])
    assert rec["missing_on_disk"] == []


def test_an_ignored_file_is_not_size_or_md5_checked():
    """The app maintains no expectation about the bytes of a file it was told
    to skip, so a difference there is not a defect."""
    rows = [_row(1, "notes.pdf", ignored=True, size=10)]
    rec = _reconcile(rows, [_file("notes.pdf", size=999)])
    assert rec["size_mismatch"] == []
    assert rec["md5_mismatch"] == []


def test_a_TRACKED_row_still_reports_a_size_mismatch():
    """Positive control - without it the test above passes on a dead check."""
    rec = _reconcile([_row(1, "notes.pdf", size=10)], [_file("notes.pdf", size=999)])
    assert [m["local_path"] for m in rec["size_mismatch"]] == ["notes.pdf"]
