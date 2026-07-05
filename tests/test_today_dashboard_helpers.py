"""Tests for ui.today_dashboard's pure helpers.

``_group_widget_id`` pins expand/collapse state (and per-file action-button
keys) to the course they belong to - a regression back to positional keys
makes card state jump between courses when the list reorders.

``_css_content_safe`` guards the import dialog against a user-typed group
name like ``</style>`` breaking out of an injected style element.

Importing ui.today_dashboard pulls in streamlit in "bare mode" (no runtime),
which is supported for module import + pure function calls.
"""

from __future__ import annotations

from ui.today_dashboard import (
    _css_content_safe,
    _css_escape_content,
    _entry_logical_date,
    _group_widget_id,
)


# ── _group_widget_id ─────────────────────────────────────────────────────────

def test_widget_id_is_stable_across_calls():
    grp = {"course_id": 42, "local_folder": "C:/Users/x/Downloads/Algo"}
    assert _group_widget_id(grp) == _group_widget_id(dict(grp))


def test_widget_id_ignores_list_position_inputs():
    # identity depends ONLY on (course_id, local_folder) - not on files/name
    a = {"course_id": 42, "local_folder": "C:/algo", "files": [1, 2], "course_name": "A"}
    b = {"course_id": 42, "local_folder": "C:/algo", "files": [1, 2, 3], "course_name": "B"}
    assert _group_widget_id(a) == _group_widget_id(b)


def test_widget_id_distinct_per_course_and_folder():
    ids = {
        _group_widget_id({"course_id": 1, "local_folder": "C:/a"}),
        _group_widget_id({"course_id": 2, "local_folder": "C:/a"}),
        _group_widget_id({"course_id": 1, "local_folder": "C:/b"}),
        _group_widget_id({"course_id": None, "local_folder": "C:/a"}),
    }
    assert len(ids) == 4


def test_widget_id_is_key_and_css_safe():
    gid = _group_widget_id({
        "course_id": 42,
        "local_folder": "C:/Users/Æøå spaces & symbols/#weird",
    })
    assert gid.replace("_", "").isalnum()


# ── CSS content escaping ─────────────────────────────────────────────────────

def test_escape_content_quotes_and_backslashes():
    assert _css_escape_content('a"b\\c') == 'a\\"b\\\\c'


def test_css_content_safe_neutralizes_style_breakout():
    out = _css_content_safe('my group </style><script>alert(1)</script>')
    # The HTML parser scans raw text for the literal "</style" - it must be gone
    assert "</style" not in out.lower()
    assert "<script" not in out.lower()


# ── History-entry logical date ───────────────────────────────────────────────

def test_entry_logical_date_rolls_at_4am():
    assert _entry_logical_date("2026-07-05 03:59") == "2026-07-04"
    assert _entry_logical_date("2026-07-05 04:00") == "2026-07-05"


def test_entry_logical_date_falls_back_on_malformed_timestamp():
    # Unparseable -> first 10 chars (date prefix) rather than raising
    assert _entry_logical_date("2026-07-05T09:00:00Z") == "2026-07-05"
    assert _entry_logical_date("") == ""
    assert _entry_logical_date(None) == ""
