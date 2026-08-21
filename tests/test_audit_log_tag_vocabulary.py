"""The audit's log oracle must know the tags the app actually writes.

This file exists because it did not, for the whole life of the suite, and the
failure was invisible in every direction a reviewer normally looks.

`sync/analysis.py` writes one line per file for each of the six analysis
categories, through a local `_row(tag, name, local)` helper. The tags are
``NEW``, ``UPDATE-CLEAN``, ``UPDATE-EDIT``, ``CANVAS-DEL``, ``LOCAL-DEL`` and
``IGNORED``, and they have been those since 2026-06-02. The audit's log oracle
was written on 2026-07-29 with a regex naming ``UPDATE-MODIFIED``,
``DELETED-CANVAS`` and ``DELETED-LOCAL`` - three names the product has never
emitted - so half the classification evidence was dropped on the floor.

Three properties made it survive:

* **A dropped row and an empty category look identical to a name lookup.** No
  check could tell "the app classified nothing here" from "the oracle saw
  nothing here", and the two are opposite verdicts.
* **The conclusion got written down as a fact about the product.**
  `crosscheck._LOG_DETAILED_CATS` recorded "the debug log only writes per-file
  rows for these two categories", citing a measurement that was really a
  measurement of this defect - and then routed four of six categories to the
  review screen as their only witness.
* **The review screen does not exist on a Quick Sync row.** So the 2026-08-21
  sync matrix produced 14 HIGH "was not offered" findings - across
  `updated_modified` and `deleted_on_canvas`, the categories that decide whether
  a student's edited file is protected - against an app whose own log named
  every one of those files, in the right category, on the line above.

The guard is a vocabulary comparison, read from both sides, so a rename in the
app fails the SUITE in the commit that makes it rather than being discovered by
a six-hour live audit six weeks later. Same discipline, same reason, as
`tests/test_mutation_anchors.py`.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness.oracles import log as olog        # noqa: E402

ANALYSIS_SRC = REPO / "sync" / "analysis.py"


def _tags_the_app_writes() -> set[str]:
    """Every literal tag passed to a `_row(...)`-style row emitter in the app.

    Read through the AST rather than by regex so a tag inside a comment or a
    docstring cannot be mistaken for one that is emitted.
    """
    tree = ast.parse(ANALYSIS_SRC.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "_row":
            continue
        if not node.args:
            continue
        first = node.args[0]
        assert isinstance(first, ast.Constant) and isinstance(first.value, str), (
            "a row tag must be a literal - a computed tag cannot be checked "
            f"from here: {ast.unparse(node)}")
        out.add(first.value)
    return out


# ── the vocabulary, from both sides ──────────────────────────────────────

def test_the_app_still_emits_rows_through_a_literal_tag():
    """The positive control. Without it every assertion below is vacuous the
    moment the helper is renamed or the tags become computed."""
    tags = _tags_the_app_writes()
    assert len(tags) >= 6, (
        f"only found {sorted(tags)} - has `_row` been renamed? This file's "
        "whole guard depends on finding them")


def test_every_tag_the_app_writes_is_known_to_the_oracle():
    """THE regression. Three of six were unknown, silently, for two months."""
    missing = _tags_the_app_writes() - set(olog.ANALYSIS_ROW_TAGS)
    assert not missing, (
        f"the app writes {sorted(missing)} and the log oracle does not parse "
        "them - every per-file verdict for those categories is unfounded. Add "
        "them to oracles.log.ANALYSIS_ROW_TAGS")


def test_the_oracle_knows_no_tag_the_app_never_writes():
    """The other direction, and it is the half that hid the bug.

    A map entry for a tag nobody emits is not inert: `_categories_match` builds
    its category list from these values, so a phantom entry advertises an oracle
    that can never produce a row - which is exactly how `deleted_on_canvas` came
    to be checked against a screen that does not exist on half the rows.
    """
    phantom = set(olog.ANALYSIS_ROW_TAGS) - _tags_the_app_writes()
    assert not phantom, (
        f"the oracle claims to parse {sorted(phantom)}, which the app never "
        "writes - a category that can never produce a row")


def test_every_category_name_is_distinct():
    """Two tags mapping to one category would make the tally check ambiguous."""
    vals = list(olog.ANALYSIS_ROW_TAGS.values())
    assert len(vals) == len(set(vals)), f"duplicate category in {vals}"


# ── the regex really matches a real line, per tag ────────────────────────

@pytest.mark.parametrize("tag", sorted(olog.ANALYSIS_ROW_TAGS))
def test_a_real_row_of_each_tag_parses(tmp_path, tag):
    """A vocabulary that agrees but a pattern that does not still sees nothing.

    Built in the app's own format: the tag is padded to a 14-column gutter by
    `_row`, so the row is `  [TAG]<pad><name>`.
    """
    pad = " " * max(1, 14 - len(tag))
    line = f"[2026-08-21 11:36:03.702]   [{tag}]{pad}Some Real File.docx"
    p = tmp_path / "debug_log.txt"
    p.write_text(line + "\n", encoding="utf-8")
    rows = olog.parse_and_summarize(str(p))["analysis_rows"]
    assert rows.get(tag) == ["Some Real File.docx"], rows


def test_the_arrow_suffix_is_split_off_the_filename():
    """`_row` appends "   -> <local path>" where the local basename differs.

    A plain `(?P<name>.+)` swallows it, so the filename becomes
    `Eksempel - Gruppekontrakt   -> Eksempel - Gruppekontrakt.docx` and matches
    nothing. That is not a corner case: the suffix is emitted precisely when the
    display name and the disk name differ, which is when a matcher needs both.
    """
    src = olog._ANALYSIS_ROW_RE
    m = src.match("  [UPDATE-EDIT]   Eksempel - Gruppekontrakt   -> "
                  "Eksempel - Gruppekontrakt.docx")
    assert m and m.group("cat") == "UPDATE-EDIT"
    assert m.group("name") == "Eksempel - Gruppekontrakt"
    assert m.group("local") == "Eksempel - Gruppekontrakt.docx"


def test_a_row_with_no_arrow_keeps_its_whole_name():
    m = olog._ANALYSIS_ROW_RE.match("  [NEW]           Uge 13 pensum.html")
    assert m and m.group("name") == "Uge 13 pensum.html" and not m.group("local")


def test_a_filename_containing_an_arrow_is_not_split():
    """The separator is TWO-or-more spaces then the arrow, which is what `_row`
    writes. A single-spaced " -> " inside a name is part of the name."""
    m = olog._ANALYSIS_ROW_RE.match("  [NEW]           a -> b.pdf")
    assert m and m.group("name") == "a -> b.pdf" and not m.group("local")


def test_both_spellings_reach_the_matcher_but_only_one_reaches_the_count(tmp_path):
    """`analysis_rows` is for MATCHING (every name), `analysis_row_detail` is
    for COUNTING (one per row). Conflating them makes the tally invariant fire
    on every healthy run that carries a path."""
    p = tmp_path / "debug_log.txt"
    p.write_text(
        "[2026-08-21 11:38:15.273] Analysis complete (19 ms): 0 new | 0 clean "
        "updates | 1 locally-edited updates | 0 deleted on Canvas | 0 deleted "
        "locally\n"
        "[2026-08-21 11:38:15.273]   [UPDATE-EDIT]   Disp   -> sub/Disp.docx\n",
        encoding="utf-8")
    d = olog.parse_and_summarize(str(p))
    assert d["analysis_rows"]["UPDATE-EDIT"] == ["Disp", "sub/Disp.docx"]
    assert len(d["analysis_row_detail"]["UPDATE-EDIT"]) == 1


# ── the runtime guard: the log's tally vs its own rows ───────────────────
#
# The vocabulary test above catches a rename at COMMIT time. This one catches
# anything else that loses rows - a format change, a padding change, a bridged
# prefix - at AUDIT time, on the first row that runs. Between them the class
# cannot hide again, which is the whole point: the original defect survived two
# months and a six-hour live audit precisely because no one was comparing the
# two halves of a log that contradicted itself on adjacent lines.

def _ev(log_dict):
    from tests.audit.harness.crosscheck import Evidence
    return Evidence(folder=Path("."), scenario="t", disk={}, db={}, log=log_dict)


def _summarise(tmp_path, body):
    p = tmp_path / "debug_log.txt"
    p.write_text(body, encoding="utf-8")
    return olog.parse_and_summarize(str(p))


_TALLY = ("[2026-08-21 11:36:03.702] Analysis complete (19 ms): 0 new | 0 clean "
          "updates | 0 locally-edited updates | 2 deleted on Canvas | 0 deleted "
          "locally\n")


def test_a_healthy_log_raises_no_tally_finding(tmp_path):
    from tests.audit.harness.crosscheck import _log_tally_matches_its_own_rows
    d = _summarise(tmp_path, _TALLY
                   + "[2026-08-21 11:36:03.702]   [CANVAS-DEL]    Ghost_0.docx\n"
                     "[2026-08-21 11:36:03.702]   [CANVAS-DEL]    Ghost_1.docx\n")
    assert _log_tally_matches_its_own_rows(_ev(d)) == []


def test_the_exact_defect_that_shipped_is_caught(tmp_path):
    """THE positive control: the app's real log, read by the OLD vocabulary.

    `candel = 2` with zero parsed rows is precisely the state the suite ran in
    for two months, and it must be impossible to be in it quietly again.
    """
    from tests.audit.harness.crosscheck import _log_tally_matches_its_own_rows
    d = _summarise(tmp_path, _TALLY
                   + "[2026-08-21 11:36:03.702]   [CANVAS-DEL]    Ghost_0.docx\n"
                     "[2026-08-21 11:36:03.702]   [CANVAS-DEL]    Ghost_1.docx\n")
    d["analysis_row_detail"] = {}          # what the old regex produced
    found = _log_tally_matches_its_own_rows(_ev(d))
    assert len(found) == 1
    f = found[0]
    assert "AUDIT PARSER DEFECT" in f.title and "deleted_on_canvas" in f.title
    assert "ANALYSIS_ROW_TAGS" in f.detail, (
        "the finding has to send the reader to the parser, not to the app")


def test_it_is_reported_against_the_AUDIT_not_the_product(tmp_path):
    """An audit that cannot read the log must say so - and must never let that
    read as a product defect. Anything above `medium` puts a parser bug in the
    same pile as data loss."""
    from tests.audit.harness.crosscheck import _log_tally_matches_its_own_rows
    d = _summarise(tmp_path, _TALLY)
    f = _log_tally_matches_its_own_rows(_ev(d))[0]
    assert f.severity == "medium" and f.category == "observation"


def test_a_log_with_no_analysis_line_is_silent(tmp_path):
    """A download row has no analysis tally. Absence is not a disagreement."""
    from tests.audit.harness.crosscheck import _log_tally_matches_its_own_rows
    assert _log_tally_matches_its_own_rows(_ev(_summarise(tmp_path, ""))) == []


def test_every_counted_category_is_reachable_from_the_tag_map():
    """`_CAT_COUNT_FIELD` and `ANALYSIS_ROW_TAGS` must agree, or a category is
    counted against a tag that does not exist and fires on every run."""
    from tests.audit.harness.crosscheck import _CAT_COUNT_FIELD
    cats = set(olog.ANALYSIS_ROW_TAGS.values())
    assert set(_CAT_COUNT_FIELD) <= cats, set(_CAT_COUNT_FIELD) - cats
    # `ignored` is deliberately absent - the summary line does not count it
    assert cats - set(_CAT_COUNT_FIELD) == {"ignored"}


def test_the_real_evidence_from_the_2026_08_21_matrix_now_parses_clean():
    """Measured, not constructed: every sync row of that run, tally vs rows.

    Skipped where the evidence is not on this machine, because the point is the
    code, and a corpus check that silently passes on an empty corpus is worse
    than none.
    """
    import glob
    from tests.audit.harness.crosscheck import _log_tally_matches_its_own_rows
    logs = sorted(glob.glob(str(
        REPO / "_audit_runs" / "20260821_113342_sync-matrix__free*"
        / "evidence" / "rows" / "*" / "debug_log.txt")))
    if len(logs) < 20:
        pytest.skip("the sync-matrix evidence is not on this machine")
    bad = []
    for lp in logs:
        d = olog.parse_and_summarize(lp)
        for f in _log_tally_matches_its_own_rows(_ev(d)):
            bad.append((Path(lp).parent.name, f.title))
    assert not bad, bad


# ── the gaps the mutation pass found in the tests above ──────────────────
#
# Every test below exists because a mutant SURVIVED the first version of this
# file. They are the difference between asserting that the fix is present and
# asserting that it does something.

def test_the_detailed_set_covers_every_category_the_log_can_speak_about():
    """`_LOG_DETAILED_CATS` must be DERIVED, not a hand-written pair.

    A mutant restoring `frozenset({"new", "updated_clean"})` survived the first
    version of this file, and that constant is the whole defect: it is what sent
    `updated_modified` and `deleted_on_canvas` to a review screen that does not
    exist on a Quick Sync row.
    """
    from tests.audit.harness.crosscheck import _LOG_DETAILED_CATS
    assert _LOG_DETAILED_CATS == frozenset(olog.ANALYSIS_ROW_TAGS.values())
    for cat in ("updated_modified", "deleted_on_canvas", "deleted_locally"):
        assert cat in _LOG_DETAILED_CATS, (
            f"{cat} has per-file log rows - routing it to O1 as its only "
            "witness is exactly the defect this file documents")


def test_the_tally_invariant_is_actually_WIRED_IN():
    """Testing the function is not testing that anything calls it.

    A mutant deleting the call from `invariants` survived, because every other
    test here invokes `_log_tally_matches_its_own_rows` directly.
    """
    import ast
    src = (REPO / "tests" / "audit" / "harness" / "crosscheck.py").read_text(
        encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "invariants")
    calls = {ast.unparse(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "_log_tally_matches_its_own_rows" in calls, (
        "the oracle's self-check must run on every row, or it guards nothing")


def test_an_empty_category_is_still_reported_as_not_offered(tmp_path):
    """The blind guard must not swallow a REAL miss.

    A mutant widening it to `blind = not _own_rows` survived: with no rows the
    guard fired whatever the app had said, so a fixture the analyzer genuinely
    failed to place was downgraded from HIGH to an observation. That is the
    direction that HIDES a defect, and it is the reason the guard consults the
    app's own tally rather than only the rows.
    """
    from tests.audit.harness.crosscheck import Evidence, _categories_match
    log = _summarise(tmp_path,
                     "[2026-08-21 11:36:03.702] Analysis complete (19 ms): 0 new "
                     "| 0 clean updates | 0 locally-edited updates | 0 deleted on "
                     "Canvas | 0 deleted locally\n")
    ev = Evidence(folder=Path("."), scenario="t", disk={}, db={}, log=log)
    plan = {"fixtures": [{"label": "ghost", "match_name": "Ghost.docx",
                          "expect_category": "deleted_on_canvas", "why": "x"}]}
    found = _categories_match(ev, plan, None)
    assert [f.severity for f in found] == ["high"], [
        (f.severity, f.title) for f in found]
    assert "was not offered" in found[0].title


def test_a_category_the_ORACLE_could_not_see_is_only_an_observation(tmp_path):
    """The mirror of the test above, and the two must not collapse.

    Same fixture, same silence from the oracle - but the app's tally says it
    placed two files there, so the silence is the parser's and nothing may be
    asserted about this fixture.
    """
    from tests.audit.harness.crosscheck import Evidence, _categories_match
    log = _summarise(tmp_path, _TALLY)          # candel = 2, no rows parsed
    log["analysis_rows"], log["analysis_row_detail"] = {}, {}
    ev = Evidence(folder=Path("."), scenario="t", disk={}, db={}, log=log)
    plan = {"fixtures": [{"label": "ghost", "match_name": "Ghost.docx",
                          "expect_category": "deleted_on_canvas", "why": "x"}]}
    sev = [f.severity for f in _categories_match(ev, plan, None)]
    assert "high" not in sev, f"a blind oracle must not assert: {sev}"
    assert sev, "and it must not be silent either - the gap has to be visible"


# ── Unicode: the fold has a DIRECTION, and it is the app's ───────────────

@pytest.mark.parametrize("fn_name", ["_norm", "_stem", "_key"])
def test_every_comparison_primitive_folds_unicode(fn_name):
    """`_stem` was missing from the first version of this test and a mutant
    dropping its fold survived - the same "landed on two of three sites" shape
    this repo has paid for before."""
    from tests.audit.harness import crosscheck
    fn = getattr(crosscheck, fn_name)
    import unicodedata
    nfc = unicodedata.normalize("NFC", "Svarark - Gode råd.docx")
    nfd = unicodedata.normalize("NFD", "Svarark - Gode råd.docx")
    assert nfc != nfd, "the fixture itself must exercise the difference"
    assert fn(nfc) == fn(nfd), f"{fn_name} does not fold Unicode"


@pytest.mark.parametrize("fn_name", ["_norm", "_stem", "_key"])
def test_the_fold_agrees_with_the_APP_and_the_seed_plan(fn_name):
    """NFC, not merely "some consistent form".

    A mutant folding to NFD survived, because folding either way makes the two
    spellings compare equal INSIDE the audit. It is still wrong: NFC is what
    `core.sync_manager._path_key` uses, what the seed plan carries throughout,
    and what a finding quotes back to a human. An audit that normalises the
    other way is one bridge away - any comparison against an app-normalised
    string, or against a plan value that skipped these helpers - from being
    silently wrong again, in the direction that is hardest to see.
    """
    import unicodedata
    from tests.audit.harness import crosscheck
    fn = getattr(crosscheck, fn_name)
    out = fn(unicodedata.normalize("NFD", "Gode råd.docx"))
    assert unicodedata.is_normalized("NFC", out), (
        f"{fn_name} normalises away from NFC, which is the app's own convention")


def test_the_app_really_does_use_NFC_so_the_direction_is_not_arbitrary():
    """The positive control for the rule above, read off the product."""
    src = (REPO / "core" / "sync_manager.py").read_text(encoding="utf-8")
    assert '"NFC"' in src or "'NFC'" in src, (
        "the app's own path key no longer normalises to NFC - the audit's fold "
        "direction is chosen to match it and must be revisited with it")


# ── a re-checked finding keeps the course it happened in ─────────────────

def test_a_rechecked_finding_is_attributed_to_the_real_course():
    """`Evidence.course` defaults to the FOLDER NAME, and a re-check points
    `folder` at the harvested evidence directory - named after the matrix row.

    So the same defect registered as "Indføring i organisationers opbygning og
    funktion (LA E25 BINTO1060U)" live and as "m012" on a re-check: two
    fingerprints for one finding, and the re-checked one much harder to act on.
    """
    from tests.audit.harness.parallel import _course_label
    scan = {"root": "/x/y/downloads/Indføring i organisationers opbygning"}
    assert _course_label(scan, "m012") == "Indføring i organisationers opbygning"
    # and it degrades to the row label rather than to an empty string
    assert _course_label({}, "m012") == "m012"
    assert _course_label({"root": ""}, "m012") == "m012"
    assert _course_label(None, "m012") == "m012"
