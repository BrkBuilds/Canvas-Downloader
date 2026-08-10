"""Unit tests for core.library - the unified saved-pairs/groups store."""

import importlib
import json
import os

import pytest


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    """A fresh library rooted at an isolated temp config dir."""
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    import core.library as library
    importlib.reload(library)
    # bust the name_index memo between tests
    library._memo = None
    return library


def test_empty_library_is_wellformed(lib):
    data = lib.load_library()
    assert data == {"version": 2, "pairs": [], "groups": []}
    assert lib.pairs() == [] and lib.groups() == [] and lib.daily_pairs() == []


def test_save_pair_is_idempotent_by_link(lib):
    a = lib.save_pair(123, "C:/x", "Course X")
    b = lib.save_pair(123, "C:/x", "Course X")   # same link
    assert a == b                                 # stable id, not duplicated
    assert len(lib.pairs()) == 1


def test_save_pair_matches_link_across_id_type_and_trailing_slash(lib):
    """The spellings that collapse on EVERY platform.

    A folder picked through the macOS native picker arrives with a trailing
    slash (AppleScript's "POSIX path of" appends one) while a typed or
    manifest-read one does not, so this is the form that actually differs in
    practice rather than a synthetic case.
    """
    a = lib.save_pair(123, "/School/Macro")
    b = lib.save_pair("123", "/School/Macro/")
    assert a == b
    assert len(lib.pairs()) == 1


@pytest.mark.skipif(os.name != "nt", reason="separator and case folding are "
                                            "Windows path semantics")
def test_save_pair_matches_link_across_windows_separators_and_case(lib):
    """Windows-only: a backslash is a legal filename character on POSIX and
    os.path.normcase is the identity there, so neither half of this holds off
    Windows. It used a hard-coded C:\\ path and so failed on macOS against
    correct code. The macOS case question is recorded as its own finding."""
    a = lib.save_pair(123, "C:/School/Macro")
    b = lib.save_pair("123", "c:\\school\\macro\\")
    assert a == b
    assert len(lib.pairs()) == 1


def test_rename_and_name_index(lib):
    pid = lib.save_pair(1, "C:/a", "Canvas A")
    assert lib.name_index() == {}          # no user name yet
    lib.rename_pair(pid, "Macro")
    lib._memo = None
    assert lib.name_index()[lib.link_key(1, "C:/a")] == "Macro"
    # empty name reverts to Canvas name
    lib.rename_pair(pid, "")
    lib._memo = None
    assert lib.name_index() == {}


def test_relink_keeps_name_and_daily(lib):
    pid = lib.save_pair(1, "C:/old", "Canvas A", name="Macro")
    lib.set_daily(pid, True)
    lib.relink_pair(pid, 1, "C:/new", "Canvas A")
    p = lib.get_pair(pid)
    assert p["local_folder"] == "C:/new"
    assert p["name"] == "Macro"            # name followed the move
    assert p["in_daily_sync"] is True      # daily membership followed too
    lib._memo = None
    # the name now resolves at the NEW link, not the old one
    assert lib.link_key(1, "C:/new") in lib.name_index()
    assert lib.link_key(1, "C:/old") not in lib.name_index()


def test_delete_pair_removes_name_and_group_membership(lib):
    p1 = lib.save_pair(1, "C:/a", name="Macro")
    p2 = lib.save_pair(2, "C:/b")
    gid = lib.save_group("Semester", [p1, p2])
    lib.delete_pair(p1)
    assert lib.get_pair(p1) is None
    assert [g["member_ids"] for g in lib.groups()] == [[p2]]   # dropped from group
    lib._memo = None
    assert lib.name_index() == {}                              # name forgotten


def test_daily_flag_drives_daily_pairs(lib):
    p1 = lib.save_pair(1, "C:/a")
    lib.save_pair(2, "C:/b")
    assert lib.daily_pairs() == []
    lib.set_daily(p1, True)
    assert [p["id"] for p in lib.daily_pairs()] == [p1]


def test_groups_reference_pairs_by_id(lib):
    p1 = lib.save_pair(1, "C:/a", "Canvas A")
    p2 = lib.save_pair(2, "C:/b", "Canvas B")
    gid = lib.save_group("Semester 1", [p1, p2, "pair_bogus", p1])  # bogus + dup dropped
    assert [g["member_ids"] for g in lib.groups()] == [[p1, p2]]
    assert [p["id"] for p in lib.group_pairs(gid)] == [p1, p2]
    # deleting the group keeps its pairs
    lib.delete_group(gid)
    assert lib.groups() == []
    assert len(lib.pairs()) == 2


def test_standalone_flag_controls_pair_cards(lib):
    p1 = lib.save_pair(1, "C:/a")                      # standalone (default)
    p2 = lib.save_pair(2, "C:/b", standalone=False)    # group-only
    assert {p["id"] for p in lib.standalone_pairs()} == {p1}
    # saving p2 standalone later RAISES the flag (never lowered)
    lib.save_pair(2, "C:/b", standalone=True)
    assert {p["id"] for p in lib.standalone_pairs()} == {p1, p2}
    # and it can't be lowered back
    lib.save_pair(2, "C:/b", standalone=False)
    assert lib.get_pair(p2)["standalone"] is True


def test_delete_group_gcs_exclusive_members(lib):
    a = lib.save_pair(1, "C:/a")                        # standalone
    b = lib.save_pair(2, "C:/b", standalone=False)      # group-only
    c = lib.save_pair(3, "C:/c", standalone=False)      # group-only AND daily
    lib.set_daily(c, True)
    d = lib.save_pair(4, "C:/d", standalone=False)      # group-only, in TWO groups
    g1 = lib.save_group("G1", [a, b, c, d])
    lib.save_group("G2", [d])
    lib.delete_group(g1)
    kept = {p["id"] for p in lib.pairs()}
    assert a in kept        # standalone stays
    assert d in kept        # still referenced by G2
    assert b not in kept    # exclusive orphan -> removed
    assert c not in kept    # exclusive orphan leaves daily too
    assert lib.daily_pairs() == []


def test_corrupt_file_degrades_to_empty(lib):
    lib._path().write_text("{ this is not json", encoding="utf-8")
    assert lib.load_library() == {"version": 2, "pairs": [], "groups": []}
    assert lib.name_index() == {}


def test_load_drops_pairs_without_folder_and_stale_group_ids(lib):
    raw = {
        "version": 2,
        "pairs": [
            {"id": "pair_ok", "course_id": 1, "local_folder": "C:/a", "name": "X"},
            {"id": "pair_bad", "course_id": 2, "local_folder": ""},   # unusable
        ],
        "groups": [{"id": "grp_1", "name": "G", "member_ids": ["pair_ok", "pair_gone"]}],
    }
    lib._path().write_text(json.dumps(raw), encoding="utf-8")
    data = lib.load_library()
    assert [p["id"] for p in data["pairs"]] == ["pair_ok"]
    assert data["groups"][0]["member_ids"] == ["pair_ok"]   # stale id pruned
