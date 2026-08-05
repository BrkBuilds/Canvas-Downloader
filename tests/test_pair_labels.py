"""The user's own name for a course/folder pair (``core.pair_labels``).

Every test here is a rule from that module's docstring, plus the two traps that
would have shipped silently:

  * ``SavedGroupsManager`` rebuilds pair dicts from a fixed key list on EVERY
    write, so a member label was one group edit away from being erased with
    nothing raised and no way to notice except the names quietly reverting;
  * a label reaching the engine - the folder manifest, the debug log, history's
    stored ``course_names`` - would break identity, and one of those is parsed
    by the audit harness.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from core import pair_labels as pl
from core.sync_manager import SavedGroupsManager

REPO = Path(__file__).resolve().parent.parent


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def hub(tmp_path, monkeypatch):
    """A SavedGroupsManager on a temp config dir, with the label memo cleared.

    ``label_index`` memoises on the groups file's (mtime_ns, size). Two writes
    inside one test can land in the same stat tick on a coarse filesystem, so
    every test that reads back through the resolver clears the memo explicitly
    via ``fresh()`` rather than trusting the clock.
    """
    import core.library as _lib
    monkeypatch.setattr(_lib, "_memo", None, raising=False)
    monkeypatch.setattr("shared.helpers.get_config_dir", lambda: str(tmp_path))
    mgr = SavedGroupsManager(str(tmp_path))
    mgr._config_dir = str(tmp_path)
    return mgr


def fresh():
    """Drop the memo so the next resolve re-reads the file. The label memo lives
    in core.library (pair_labels delegates to it), so clear it there."""
    import core.library as _lib
    _lib._memo = None


def _pair(cid, folder, name="Makroøkonomi (XB E26 BINTO1035U)", **extra):
    return {"course_id": cid, "local_folder": folder, "course_name": name, **extra}


# ── the identity a label hangs off ──────────────────────────────────────────

def test_pair_key_normalises_folder_and_course_id():
    """The link is (course_id, local_folder), and both sides arrive in more than
    one form: the id has been through JSON (str vs int) and the folder came from
    a picker, a manifest or a history record (separators, trailing slash, case).
    Comparing either raw is what makes two consumers of one pair disagree.
    """
    canonical = pl.pair_key(46396, r"C:\Courses\Makro")
    assert pl.pair_key("46396", "c:/courses/makro/") == canonical
    assert pl.pair_key(46396, r"C:\Courses\Makro\\") == canonical
    # A DIFFERENT folder for the same course is a different pair - that is the
    # rule the whole daily-sync off-list tally depends on.
    assert pl.pair_key(46396, r"C:\Courses\Other") != canonical


# ── precedence ──────────────────────────────────────────────────────────────

def test_standalone_saved_pair_beats_a_group_member_label():
    """Nothing upstream stops one link being both, so "the label" has to be
    decided rather than discovered. The standalone pair wins because naming that
    one link is its entire purpose."""
    idx = pl.build_label_index([
        {"group_id": "g", "group_name": "Semester", "pairs": [
            _pair(1, "/x", label="from the group")]},
        {"group_id": "p", "group_name": "from the pair", "is_single_pair": True,
         "pairs": [_pair(1, "/x")]},
    ])
    assert idx[pl.pair_key(1, "/x")] == "from the pair"

    # Same rule with the flag stored EXPLICITLY false, which update_group can
    # write. Pass 1 must test the flag's truthiness, not its presence: a group
    # is named as a SET, so letting its group_name reach pass 1 would title
    # every one of its courses "Semester".
    idx = pl.build_label_index([
        {"group_id": "g", "group_name": "Semester", "is_single_pair": False,
         "pairs": [_pair(1, "/x"), _pair(2, "/y", label="Stats crunching")]},
        {"group_id": "p", "group_name": "from the pair", "is_single_pair": True,
         "pairs": [_pair(1, "/x")]},
    ])
    assert idx[pl.pair_key(1, "/x")] == "from the pair"
    assert idx[pl.pair_key(2, "/y")] == "Stats crunching"


def test_first_in_file_order_wins_within_a_pass():
    """Two groups labelling the same link: stable, not arbitrary."""
    idx = pl.build_label_index([
        {"group_id": "a", "group_name": "A", "pairs": [_pair(1, "/x", label="first")]},
        {"group_id": "b", "group_name": "B", "pairs": [_pair(1, "/x", label="second")]},
    ])
    assert idx[pl.pair_key(1, "/x")] == "first"


# ── auto-named ──────────────────────────────────────────────────────────────

def test_auto_named_pair_contributes_no_label():
    """Accepting the pre-filled course name means "I did not choose a name", so
    the screens must go on showing the LIVE Canvas name. Without this the pair
    would freeze whatever the course was called on the day it was saved."""
    idx = pl.build_label_index([
        {"group_id": "p", "group_name": "Makroøkonomi (XB)", "is_single_pair": True,
         "auto_named": True, "pairs": [_pair(1, "/x")]},
    ])
    assert idx == {}
    assert pl.saved_record_label(
        {"group_name": "X", "auto_named": True}) == ""
    assert pl.saved_record_label({"group_name": " X "}) == "X"


def test_renaming_clears_auto_named(hub):
    """A rename IS the user choosing a name. If the flag survived it, the new
    name would be stored and then ignored by the resolver - indistinguishable
    from the rename having silently failed."""
    rec = hub.save_group("Makroøkonomi (XB)", [_pair(1, "/x")],
                         is_single_pair=True, auto_named=True)
    fresh()
    assert pl.label_for(1, "/x") == ""

    hub.update_group(rec["group_id"], {"group_name": "My economics course"})
    fresh()
    assert pl.label_for(1, "/x") == "My economics course"
    # A named pair is no longer auto-named (behaviour, not storage shape: the
    # unified library carries the flag as False rather than dropping the key).
    assert hub.load_groups()[0].get("auto_named") is False


# ── the persistence trap ────────────────────────────────────────────────────

def test_a_group_edit_does_not_erase_member_labels(hub):
    """THE trap. Both writers project pair dicts through _project_pair, which
    used to hard-code three keys - so renaming a group, adding a course or
    re-linking one folder would have wiped every member label in it. Nothing
    raises; the names just start reverting.
    """
    rec = hub.save_group("Semester", [
        _pair(1, "/x", label="Stats crunching"),
        _pair(2, "/y"),
    ])
    fresh()
    assert pl.label_for(1, "/x") == "Stats crunching"

    # Every mutation the hub can perform on a group.
    hub.update_group(rec["group_id"], {"group_name": "Semester 2"})
    fresh()
    assert pl.label_for(1, "/x") == "Stats crunching", "rename wiped it"

    pairs = hub.load_groups()[0]["pairs"]
    hub.update_group(rec["group_id"], {"pairs": pairs + [_pair(3, "/z")]})
    fresh()
    assert pl.label_for(1, "/x") == "Stats crunching", "adding a course wiped it"

    pairs = hub.load_groups()[0]["pairs"]
    pairs[1] = {**pairs[1], "local_folder": "/y2"}
    hub.update_group(rec["group_id"], {"pairs": pairs})
    fresh()
    assert pl.label_for(1, "/x") == "Stats crunching", "re-linking a sibling wiped it"


def test_empty_label_is_not_stored(hub):
    """An empty string is "no name", not a name - it must not occupy the key."""
    hub.save_group("G", [_pair(1, "/x", label="   ")])
    assert "label" not in hub.load_groups()[0]["pairs"][0]
    fresh()
    assert pl.label_for(1, "/x") == ""


# ── resolution + fallback ───────────────────────────────────────────────────

def test_pair_display_falls_back_to_the_canvas_name(hub):
    """An unlabelled pair must render EXACTLY as it did before this feature."""
    fresh()
    label, canvas = pl.pair_display(_pair(1, "/nope"))
    assert label == ""
    assert canvas == "Makroøkonomi (XB)"          # friendly_course_name applied
    assert pl.pair_display_name(_pair(1, "/nope")) == "Makroøkonomi (XB)"


def test_pair_display_name_prefers_the_label(hub):
    hub.save_group("My economics course", [_pair(1, "/x")], is_single_pair=True)
    fresh()
    assert pl.pair_display_name(_pair(1, "/x")) == "My economics course"
    # ...and the Canvas name is still available beside it, because the screens
    # that show both need the identity too.
    assert pl.pair_display(_pair(1, "/x")) == ("My economics course",
                                               "Makroøkonomi (XB)")


def test_resolution_is_total_on_garbage():
    """A naming feature must never be able to break a sync screen."""
    assert pl.build_label_index(None) == {}
    assert pl.build_label_index([None, 42, {"pairs": "not a list"},
                                 {"is_single_pair": True, "pairs": [7]}]) == {}
    assert pl.pair_display(None) == ("", "Course")
    assert pl.pair_display_name({}) == "Course"


def test_label_index_refreshes_when_the_file_changes(hub):
    """The memo keys on the groups file's mtime+size, so a hub write invalidates
    it by construction - there is no invalidate() call anyone can forget. This
    is the ONLY reason a rename in the hub reaches the sync list."""
    rec = hub.save_group("First", [_pair(1, "/x")], is_single_pair=True)
    fresh()
    assert pl.label_for(1, "/x") == "First"

    hub.update_group(rec["group_id"], {"group_name": "Second"})
    # NO fresh() here - the point is that the memo notices on its own.
    assert pl.label_for(1, "/x") == "Second"


def test_canvas_name_fallback_index_covers_entries_with_no_link(hub):
    """Sync-history entries written before this version carry name STRINGS and
    no pair identity, so without this they would be the one surface still
    showing the Canvas name."""
    hub.save_group("My economics course", [_pair(1, "/x")], is_single_pair=True)
    fresh()
    names = pl.canvas_name_label_index()
    # Both the stored form and its friendly form resolve - a pair's course_name
    # may itself be the disambiguated raw name.
    assert names["makroøkonomi (xb e26 binto1035u)"] == "My economics course"
    assert names["makroøkonomi (xb)"] == "My economics course"


# ── what must NEVER see a label ─────────────────────────────────────────────

def test_the_debug_log_line_the_audit_harness_parses_uses_the_canvas_name():
    """tests/audit/harness/oracles/log.py regexes
    "=== Sync Execution: <course> | Mode:" to attribute every event to a course.
    A nickname there unhooks the audit harness from the run it is auditing -
    silently, because the regex still matches."""
    src = (REPO / "sync" / "execution.py").read_text(encoding="utf-8")
    # The log_debug CALL, not the comment above it that quotes the same string.
    line = next(ln for ln in src.splitlines()
                if "=== Sync Execution:" in ln and "log_debug(" in ln)
    assert "{_log_name}" in line, line
    assert "{course_name}" not in line, line
    # ...and _log_name really is the Canvas name, not another alias for the label.
    assert "_log_name = friendly_course_name(pair['course_name'])" in src


def test_history_records_the_canvas_name_and_the_pair_identity():
    """course_names stays Canvas (shared.components._course_id_from_sync_pairs
    matches error rows against it); course_sigs is what lets history RESOLVE a
    label at render instead of snapshotting one."""
    src = (REPO / "sync" / "execution.py").read_text(encoding="utf-8")
    assert "synced_course_names.append(sel['res_data']['pair']['course_name'])" in src
    assert "'course_sigs': course_sigs," in src


def test_a_label_never_reaches_the_sync_pairs_file(monkeypatch, tmp_path):
    """The hub hands its OWN pair dicts to the sync list - "Add to Sync List" for
    a group, and rescue mode - and a group member's dict carries ``label``.
    Without a strip, the name is written into canvas_sync_pairs.json as a second,
    silently-stale copy. Inert today because nothing reads it, and a trap for the
    first person who does: the whole model is that the label is resolved from the
    hub and copied nowhere.
    """
    import streamlit as st
    from sync import persistence

    monkeypatch.setattr("shared.helpers.get_config_dir", lambda: str(tmp_path))
    st.session_state.clear()

    def written():
        return json.loads(
            (tmp_path / "canvas_sync_pairs.json").read_text(encoding="utf-8"))

    def assert_clean(after):
        rows = written()
        assert rows, f"nothing written after {after} - the test proves nothing"
        for p in rows:
            assert "label" not in p, f"after {after}: {p}"

    labelled = {"course_id": 1, "local_folder": str(tmp_path / "x"),
                "course_name": "C1", "label": "Stats crunching"}

    # Each mutator is checked on its OWN write. Checking only at the end let a
    # later stripped write overwrite an earlier leaky one and hide it - the
    # mutation harness caught exactly that, with add_pair's strip removed.
    persistence.add_pair(dict(labelled))
    assert_clean("add_pair")

    persistence.add_pairs_batch([
        {"course_id": 2, "local_folder": str(tmp_path / "y"),
         "course_name": "C2", "label": "Other"}])
    assert_clean("add_pairs_batch")

    persistence.update_pair_by_signature(
        {"course_id": 1, "local_folder": str(tmp_path / "x")},
        dict(labelled, course_name="C1 renamed"))
    assert_clean("update_pair_by_signature")

    # ...and the strip must not damage the pair otherwise.
    assert {p["course_id"] for p in written()} == {1, 2}
    assert any(p["course_name"] == "C1 renamed" for p in written())


def test_history_names_are_not_deduped():
    """The count drives the header ("N courses" vs one name), and two entries can
    legitimately share a display name - the same course in two folders is two
    pairs, and nothing stops a user naming two pairs alike. Collapsing them
    reports a 2-course run as a 1-course run."""
    import sync_ui
    entry = {"synced_groups": [
        {"course_id": 1, "local_folder": "/a", "course_name": "Same", "files": [{}]},
        {"course_id": 1, "local_folder": "/b", "course_name": "Same", "files": [{}]},
    ]}
    assert len(sync_ui.history_course_display_names(entry, {})) == 2


def test_todays_stored_pairs_never_carry_a_label():
    """The daily list holds standalone COPIES. A label copied into one is a
    label that can drift from the hub, which is exactly the failure
    reconcile_daily_list_with_hub exists to clean up for folders. _norm_pair
    stripping unknown keys is what prevents it."""
    src = (REPO / "core" / "today_store.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_norm_pair")
    returned = next(n for n in ast.walk(fn) if isinstance(n, ast.Dict))
    keys = {k.value for k in returned.keys if isinstance(k, ast.Constant)}
    assert keys == {"course_id", "course_name", "local_folder"}, keys


def test_sync_manager_is_constructed_with_the_canvas_name_only():
    """course_name is written into .canvas_sync.db as the folder's BOUND
    identity - peek_bound_course_name reads it for auto-detect and for the
    "this folder is linked to a different course" notice. A label there would
    make the app disagree with itself about what a folder contains."""
    for rel in ("sync/analysis.py", "sync/execution.py", "ui/sync_review.py",
                "sync_ui.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "SyncManager"):
                continue
            third = node.args[2] if len(node.args) > 2 else None
            rendered = ast.unparse(third) if third is not None else ""
            assert "label" not in rendered and "display" not in rendered, (
                f"{rel}: SyncManager(..., {rendered}) - the manifest's "
                f"course_name must be the Canvas name")


# ── the max length is enforced where names are TYPED ────────────────────────

def test_every_name_input_caps_its_length():
    """A label is a title and becomes a heading on six screens; uncapped, one
    pasted paragraph is a broken card everywhere. Capped at the input rather
    than at render so what the user typed is always what they see."""
    src = (REPO / "ui" / "hub_dialog.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    inputs = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and ast.unparse(n.func).endswith("text_input")
              and any(isinstance(k.value, ast.Constant)
                      and isinstance(k.value.value, str)
                      and "name" in k.value.value.lower()
                      for k in n.keywords if k.arg == "key")]
    assert inputs, "no name inputs found - did the keys change?"
    for node in inputs:
        kw = {k.arg for k in node.keywords}
        assert "max_chars" in kw, ast.unparse(node)[:120]


def test_the_pill_row_markup_and_its_stylesheet_stay_coupled():
    """The pill row is raw HTML in sync_ui.py styled by class from
    styles/sync_hub.css - two files that a rename can silently decouple. An
    unstyled .sp-pill is not an error, it is two bare words where a chip should
    be, on the screen this whole feature exists for."""
    import re
    py = (REPO / "sync_ui.py").read_text(encoding="utf-8")
    css = (REPO / "styles" / "sync_hub.css").read_text(encoding="utf-8")

    # Every class TOKEN the markup emits, from the class="..." attributes -
    # matching on a quoted whole-attribute string is too literal, and broke the
    # moment "sp-pill" became "sp-pill sp-pill-course".
    emitted = set()
    for attr in re.findall(r'class="([^"{}]*)"', py):
        emitted.update(t for t in attr.split() if t.startswith("sp-"))

    assert emitted >= {"sp-pill-row", "sp-pill", "sp-pill-course", "sp-pill-folder"}, emitted
    for cls in emitted:
        assert f".{cls}" in css, f"{cls} is emitted but has no rule in sync_hub.css"

    # Scoped to the card key the markup renders inside, so it cannot be reached
    # on any other screen.
    assert 'div[class*="st-key-sync_pair_card_"] .sp-pill' in css

    # The identity chip must not shrink - truncating "(XB)" off a list that also
    # holds an "(LA)" removes the only thing that says which is which.
    course_rule = css.split('.sp-pill-course')[1].split('}')[0]
    assert "flex: 0 0 auto" in course_rule, course_rule


def test_markdown_is_escaped_in_widget_labels_carrying_user_text():
    """st.button labels are MARKDOWN. "1. Semester" renders as an ordered-list
    item with the "1." eaten - the same trap the step tracker hit. Only shows up
    for users who actually named their courses, which is why it needs a test."""
    from shared.helpers import md_escape
    assert md_escape("1. Semester") == r"1\. Semester"
    assert md_escape("Math_2 **x**") == r"Math\_2 \*\*x\*\*"
    assert md_escape("") == ""

    src = (REPO / "ui" / "today_dashboard.py").read_text(encoding="utf-8")
    for ln in src.splitlines():
        if "pair_display_name(p)" in ln and "name =" in ln:
            assert "md_escape(" in ln, ln
