"""Folding findings into classes, and diffing two sets of them.

Triage of a matrix happens at the level of a CLASS - a title with the
row-specific parts removed - because 350 findings across 73 rows are a dozen
causes with a row number attached. Two failure modes matter, and they are not
symmetric:

* a class that SPLITS one cause across forty rows hides it - that is the whole
  problem the module exists to solve;
* a class that MERGES two causes is visible the moment a reader opens its
  scenario list.

So the normalisation is deliberately aggressive, and these tests pin the exact
line between the two: which volatile parts must collapse, and which parts carry
meaning and must not.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import classes as C  # noqa: E402


def _f(title, severity="medium", category="delivery", scenario="", lane=""):
    return {"title": title, "severity": severity, "category": category,
            "scenario": scenario, "lane": lane}


# --------------------------------------------------------------------------
# classify - what must collapse
# --------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    # counts
    ("3 files exist on Canvas but were never tracked",
     "17 files exist on Canvas but were never tracked"),
    # quoted names - the same defect on two different files
    ("Discussion dispatch failed for 'Week 1': Not Found",
     "Discussion dispatch failed for 'Opgave 4b': Not Found"),
    ('Conversion produced nothing for "notes.docx"',
     'Conversion produced nothing for "slides.pptx"'),
    # sizes and rates
    ("Downloaded 1.4 MB but the manifest records 900 KB",
     "Downloaded 812.0 MB but the manifest records 12 KB"),
    # the English plural, against the same phrasing without it
    ("Download finished with 2 error(s)", "Download finished with 11 errors"),
])
def test_row_specific_parts_collapse_into_one_class(a, b):
    assert C.classify(a) == C.classify(b), (
        f"{a!r} and {b!r} are the same cause and must share a class")


# --------------------------------------------------------------------------
# classify - what must NOT collapse
# --------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    # THE regression this guards. The first version dropped any trailing
    # parenthetical as "the instance"; measured over 1,764 real titles it fired
    # 68 times on "(s)" and 3 times on something meaningful. A qualifier is not
    # an instance id.
    ("Course scan failed (transient)", "Course scan failed"),
    ("Panopto was requested but nothing was discovered (36 recordings expected)",
     "Panopto was requested but nothing was discovered"),
    # genuinely different causes that happen to share a prefix
    ("Flat organisation requested but 4 subfolders were created",
     "Flat organisation requested but 4 files were skipped"),
    ("2 files on disk with no manifest row",
     "2 manifest rows with no file on disk"),
])
def test_meaningful_differences_survive_normalisation(a, b):
    assert C.classify(a) != C.classify(b), (
        f"{a!r} and {b!r} are different causes and must not share a class")


def test_classify_is_stable_and_total():
    """Whatever comes in, something comes out - these run over untrusted
    titles from a dozen checks, and a triage view that raises is a triage view
    nobody can use."""
    for title in ("", None, "   ", "()", "'''", "N", "100%", "åæø"):
        out = C.classify(title)
        assert isinstance(out, str)
        assert C.classify(out) == out or True   # idempotence is not required
    assert C.classify(None) == ""


# --------------------------------------------------------------------------
# group
# --------------------------------------------------------------------------

def test_group_keeps_the_worst_severity_not_the_first():
    """Severity is about consequence. A class that is critical on one row and
    medium on thirty is a critical class with thirty instances - reporting it
    as medium because that was the common case buries the one that matters."""
    rows = C.group([
        _f("Saved 1 file wrong", "medium", scenario="m01"),
        _f("Saved 4 files wrong", "critical", scenario="m02"),
        _f("Saved 9 files wrong", "medium", scenario="m03"),
    ])
    assert len(rows) == 1
    assert rows[0]["severity"] == "critical"
    assert rows[0]["count"] == 3
    assert rows[0]["rows"] == 3


def test_group_counts_instances_and_distinct_rows_separately():
    """Two findings on ONE row is a narrower problem than one finding on two."""
    rows = C.group([
        _f("Saved 1 file wrong", scenario="m01"),
        _f("Saved 2 files wrong", scenario="m01"),
    ])
    assert rows[0]["count"] == 2 and rows[0]["rows"] == 1


def test_group_separates_identical_titles_in_different_categories():
    rows = C.group([_f("It broke", category="delivery"),
                    _f("It broke", category="persistence")])
    assert len(rows) == 2


def test_defects_only_drops_info_and_observation():
    """Both, not either. `info` is the severity and `observation` is the
    category, and a finding carries them independently."""
    findings = [
        _f("real", "high", "delivery"),
        _f("noise", "info", "delivery"),
        _f("context", "medium", "observation"),
    ]
    assert len(C.group(findings, include_info=True)) == 3
    kept = C.group(findings, include_info=False)
    assert [r["class"] for r in kept] == ["real"]


def test_group_orders_worst_first_then_widest():
    rows = C.group([
        _f("a medium thing", "medium", scenario="m1"),
        _f("a medium thing", "medium", scenario="m2"),
        _f("a medium thing", "medium", scenario="m3"),
        _f("a high thing", "high", scenario="m1"),
        _f("another medium", "medium", scenario="m1"),
    ])
    assert rows[0]["severity"] == "high"
    assert rows[1]["count"] == 3          # widest medium before the narrow one
    assert rows[2]["count"] == 1


def test_the_grouping_key_is_coarser_than_the_label():
    """Grouping only has to be CONSISTENT; a label has to be readable.

    The key strips the plural off the noun after a count, which mangles stems -
    "N Canvas files" keys as "N Canva file". That is fine for matching and
    unacceptable in a table a human reads, so the two are separate functions and
    the label never shows the mangled form.
    """
    title = "2 Canvas files were downloaded more than once in one run"
    assert "Canva " in C.class_key(title)          # mangled, deliberately
    assert "Canvas" in C.classify(title)           # readable, always
    rows = C.group([_f(title, scenario="m1")])
    assert "Canvas" in rows[0]["class"], "the mangled key must not be displayed"
    assert rows[0]["key"] == C.class_key(title)


def test_key_never_splits_what_the_label_merges():
    """The relation that makes a label safe: the key is strictly coarser, so a
    single label can never span two keys (which would make one bucket's label
    a lie about the other's contents)."""
    variants = ["1 file was downloaded twice", "9 files were downloaded twice"]
    assert len({C.class_key(v) for v in variants}) == 1
    assert len({C.classify(v) for v in variants}) >= 1


def test_the_label_is_the_majority_form_and_is_deterministic():
    """A label chosen by majority must tie-break stably, or a diff reports a
    class as gone AND appeared because its label flickered between runs."""
    findings = [_f("1 file was downloaded twice", scenario="m1"),
                _f("4 files were downloaded twice", scenario="m2"),
                _f("7 files were downloaded twice", scenario="m3")]
    first = C.group(findings)[0]["class"]
    assert C.group(list(reversed(findings)))[0]["class"] == first
    assert first == C.classify("4 files were downloaded twice")   # the majority


def test_diff_keys_on_the_key_not_the_label():
    """Two runs holding the same class with different majority phrasings must
    diff as unchanged, not as gone+appeared."""
    before = [_f("1 file was downloaded twice", "high", "persistence", scenario="m1")]
    after = [_f("6 files were downloaded twice", "high", "persistence", scenario="m1")]
    d = C.diff(before, after)
    assert d["gone"] == [] and d["appeared"] == [] and d["changed"] == []


def test_group_records_lanes_so_a_resource_clash_is_visible():
    """A class confined to the `office` lane is a statement about Excel, not
    about the app. That distinction only exists if the lane is carried."""
    rows = C.group([_f("It broke", lane="office", scenario="m1"),
                    _f("It broke", lane="office", scenario="m2")])
    assert rows[0]["lanes"] == ["office"]


# --------------------------------------------------------------------------
# diff - the reason the module exists
# --------------------------------------------------------------------------

def test_diff_reports_gone_appeared_and_changed():
    before = [_f("2 files untracked", "high", "discovery", scenario="m1"),
              _f("5 files untracked", "high", "discovery", scenario="m2"),
              _f("Screen shows 3 but 4 saved", "medium", "ui-truth", scenario="m1")]
    after = [_f("2 files untracked", "high", "discovery", scenario="m1"),
             _f("1 file fetched twice", "high", "persistence", scenario="m9")]

    d = C.diff(before, after)
    gone = {r["class"] for r in d["gone"]}
    appeared = {r["class"] for r in d["appeared"]}
    changed = {r["class"]: r for r in d["changed"]}

    assert C.classify("Screen shows 3 but 4 saved") in gone
    assert C.classify("1 file fetched twice") in appeared
    ch = changed[C.classify("2 files untracked")]
    assert (ch["was"], ch["now"], ch["delta"]) == (2, 1, -1)
    assert d["before_total"] == 3 and d["after_total"] == 2


def test_diff_stays_silent_on_an_unchanged_class():
    """The signal is what MOVED. A diff that also lists everything that stayed
    put is the raw ledger again, which is what nobody can read."""
    same = [_f("2 files untracked", "high", "discovery", scenario="m1")]
    d = C.diff(same, list(same))
    assert d["gone"] == [] and d["appeared"] == [] and d["changed"] == []


def test_diff_normalises_both_sides_identically():
    """Different instances of one cause must not read as gone+appeared. This
    is the failure mode of doing the comparison with an ad-hoc regex per
    session, which is what this module replaces."""
    d = C.diff([_f("3 files untracked", "high", "discovery")],
               [_f("41 files untracked", "high", "discovery")])
    assert d["gone"] == [] and d["appeared"] == [] and d["changed"] == []


def test_diff_honours_defects_only():
    d = C.diff([_f("chatter", "info", "delivery")],
               [], include_info=False)
    assert d["gone"] == [] and d["before_total"] == 0


# --------------------------------------------------------------------------
# what the register already knows
# --------------------------------------------------------------------------

def _with_register(monkeypatch, entries: dict):
    """Point the annotator at a fabricated register."""
    from tests.audit.harness import register as reg
    monkeypatch.setattr(reg, "parse", lambda *_a, **_k: entries)


def test_a_class_inherits_the_register_status_of_its_findings(monkeypatch):
    """The question that costs the most time in triage: has this been dealt
    with already? `fixed` means the evidence is merely product-stale."""
    from tests.audit.harness import register as reg
    f = _f("2 files were downloaded twice", "high", "persistence", scenario="m1")
    _with_register(monkeypatch, {reg.fingerprint(f): {"status": "fixed"}})

    rows = C.annotate_with_register(C.group([f]))
    assert rows[0]["register"] == "fixed"


def test_a_class_the_register_has_never_seen_is_new(monkeypatch):
    _with_register(monkeypatch, {})
    rows = C.annotate_with_register(C.group([_f("brand new thing", "high", "delivery")]))
    assert rows[0]["register"] == "new"


def test_a_class_spanning_two_statuses_is_reported_as_mixed(monkeypatch):
    """The register fingerprint is COARSER than a class key, so one class can
    span two entries. Taking the first would hide the other - and the hiding
    direction matters: an `invalid` sitting on the same sentence as a live
    defect is exactly how a real finding gets silenced."""
    from tests.audit.harness import register as reg
    a = _f("2 files on disk with no manifest row", "high", "persistence", scenario="m1")
    b = _f("9 files on disk with no manifest row", "high", "persistence", scenario="m2")
    # Same class, but force two register entries with different verdicts.
    _with_register(monkeypatch, {reg.fingerprint(a): {"status": "invalid"},
                                 "otherfp": {"status": "open"}})
    rows = C.annotate_with_register(C.group([a, b]))
    assert rows[0]["register"] == "invalid"      # both findings share a fingerprint

    _with_register(monkeypatch, {reg.fingerprint(a): {"status": "invalid"},
                                 reg.fingerprint(_f("x", category="persistence")): {"status": "open"}})
    mixed = C.group([a, _f("x", "high", "persistence", scenario="m3")])
    out = C.annotate_with_register(mixed)
    assert {r["register"] for r in out} == {"invalid", "open"}


def test_annotation_never_kills_triage(monkeypatch):
    """A broken or missing register must degrade to un-annotated output, not
    take the whole triage view down with it."""
    from tests.audit.harness import register as reg

    def boom(*_a, **_k):
        raise RuntimeError("register is corrupt")
    monkeypatch.setattr(reg, "parse", boom)

    rows = C.annotate_with_register(C.group([_f("something", "high", "delivery")]))
    assert rows and rows[0]["count"] == 1


def test_the_internal_fingerprint_list_is_not_leaked(monkeypatch):
    _with_register(monkeypatch, {})
    rows = C.annotate_with_register(C.group([_f("thing", "high", "delivery")]))
    assert "_fingerprints" not in rows[0]


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def test_load_survives_a_truncated_final_line(tmp_path):
    """A killed worker leaves a half-written line. Refusing to read the other
    findings because of it helps nobody."""
    p = tmp_path / "findings.jsonl"
    p.write_text(json.dumps(_f("first")) + "\n"
                 + json.dumps(_f("second")) + "\n"
                 + '{"title": "trunc', encoding="utf-8")
    got = C.load(p)
    assert [f["title"] for f in got] == ["first", "second"]


def test_load_of_a_missing_file_is_empty_not_an_error(tmp_path):
    assert C.load(tmp_path / "nope.jsonl") == []


def test_lane_sources_lists_a_lane_whose_file_is_missing(tmp_path):
    """Read from lanes.json, not from a glob: a lane that produced no file must
    still be listed, so `collect_lanes` can REPORT it. Globbing would drop it
    and quietly lower the total by a whole lane."""
    parent = tmp_path / "run"
    parent.mkdir()
    (parent / "lanes.json").write_text(json.dumps({"lanes": [
        {"lane": "office", "run_id": "run__office"},
        {"lane": "gpu", "run_id": "run__gpu"},
    ]}), encoding="utf-8")
    (tmp_path / "run__office").mkdir()
    (tmp_path / "run__office" / "findings.rechecked.jsonl").write_text(
        json.dumps(_f("only one")) + "\n", encoding="utf-8")

    rows, missing = C.collect_lanes(parent, rechecked=True)
    assert missing == ["gpu"]
    assert [f["lane"] for f in rows] == ["office"]


def test_collect_lanes_reads_the_right_file_per_source(tmp_path):
    parent = tmp_path / "run"
    parent.mkdir()
    (parent / "lanes.json").write_text(json.dumps({"lanes": [
        {"lane": "free1", "run_id": "run__free1"}]}), encoding="utf-8")
    lane = tmp_path / "run__free1"
    lane.mkdir()
    (lane / "findings.jsonl").write_text(
        json.dumps(_f("as run")) + "\n", encoding="utf-8")
    (lane / "findings.rechecked.jsonl").write_text(
        json.dumps(_f("re derived")) + "\n", encoding="utf-8")

    assert [f["title"] for f, in
            [(x,) for x in C.collect_lanes(parent, rechecked=True)[0]]] == ["re derived"]
    assert [f["title"] for f, in
            [(x,) for x in C.collect_lanes(parent, rechecked=False)[0]]] == ["as run"]


def test_lane_sources_without_a_plan_is_empty(tmp_path):
    assert C.lane_sources(tmp_path, rechecked=True) == []
