"""The Recents purge deleted values and left every entry on screen.

MEASURED on macOS 26.6 against the real
``~/Library/Group Containers/UBF8T346G9.Office/MicrosoftRegistrationDB.reg``:

    before   ours=636   user's nodes=1041   value rows=3233
    purge    -> removed 495 VALUE ROWS and 0 NODES
    after    ours=636   (still listed, now stripped of their values)

Office's start-screen Recent list is driven by the rows in
``HKEY_CURRENT_USER`` - each entry is a node whose ``name`` IS the full
``file://`` URL. The old implementation selected
``HKEY_CURRENT_USER_values WHERE name='path'`` and deleted only value rows, so
it never removed an entry; and the whole database held just 36 rows named
``path``. A half-mutation of Office's SHARED registry is worse than not running
at all - it leaves the user's Recents full of our temp files AND breaks those
rows.

After the fix, on the same real database: **636 removed, 0 of the user's 1041
nodes touched, 0.04s.**

THREE GATES, each doing separate work, and the tests below check them
independently because any one of them alone would be unsafe:

  * the node's name carries ``CanvasDownloaderTmp``, a directory name we own;
  * the node is a LEAF, so this can never amputate a subtree;
  * an ancestor is an ``MruUserData`` key, so a marker appearing anywhere
    unexpected still cannot take a row outside the Recents subtree.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import engine.applescript_bridge as AB  # noqa: E402

MARK = "CanvasDownloaderTmp"


def _build(db: Path, rows, values=()):
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE HKEY_CURRENT_USER "
                "(node_id INTEGER, parent_id INTEGER, name TEXT, write_time INTEGER)")
    con.execute("CREATE TABLE HKEY_CURRENT_USER_values "
                "(node_id INTEGER, name TEXT, type INTEGER, value BLOB)")
    con.executemany("INSERT INTO HKEY_CURRENT_USER VALUES (?,?,?,0)", rows)
    con.executemany("INSERT INTO HKEY_CURRENT_USER_values VALUES (?,?,1,?)", values)
    con.commit()
    con.close()


def _nodes(db: Path) -> set:
    con = sqlite3.connect(db)
    out = {r[0] for r in con.execute("SELECT node_id FROM HKEY_CURRENT_USER")}
    con.close()
    return out


def _value_nodes(db: Path) -> set:
    con = sqlite3.connect(db)
    out = {r[0] for r in con.execute("SELECT node_id FROM HKEY_CURRENT_USER_values")}
    con.close()
    return out


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """A registry shaped like the real one, at a fake home."""
    home = tmp_path / "home"
    db = home / "Library" / "Group Containers" / "UBF8T346G9.Office" \
        / "MicrosoftRegistrationDB.reg"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(AB, "_any_office_running", lambda: False)
    # 1 root -> Software/.../MruUserData/.../Documents -> entries
    rows = [
        (1, 0, "Software"),
        (2, 1, "MruUserData"),
        (3, 2, "Documents"),
        (10, 3, f"file:///var/folders/x/{MARK}/cd_aaa/src_112233.pptx"),
        (11, 3, f"file:///var/folders/x/{MARK}/cd_bbb/src_445566.docx"),
        (12, 3, "file:///Users/me/Desktop/My%20Thesis.docx"),   # the user's
        (13, 3, "file:///Users/me/Desktop/Budget.xlsx"),        # the user's
    ]
    values = [(n, "Path", b"x") for n in (10, 11, 12, 13)]
    _build(db, rows, values)
    return db


def test_it_deletes_the_NODE_rows_not_only_their_values(registry):
    """The defect: Recents is driven by the nodes, so deleting values leaves
    every entry on screen."""
    AB._purge_recents_sqlite()
    left = _nodes(registry)
    assert 10 not in left and 11 not in left, (
        "our entries are still listed - the purge removed values but not nodes")


def test_it_never_touches_the_users_documents(registry):
    AB._purge_recents_sqlite()
    left = _nodes(registry)
    assert {12, 13} <= left, "a genuine recent document was deleted"
    assert {1, 2, 3} <= left, "a structural key was deleted"


def test_it_removes_the_orphaned_value_rows_too(registry):
    """A node row without its values is the half-state the old code produced."""
    AB._purge_recents_sqlite()
    assert not ({10, 11} & _value_nodes(registry))
    assert {12, 13} <= _value_nodes(registry)


def test_a_marked_node_OUTSIDE_MruUserData_is_left_alone(tmp_path, monkeypatch):
    """The marker is a directory name, so it could in principle appear in a key
    that is not the Recents list. Deleting there would edit an unrelated part
    of Office's shared registry."""
    home = tmp_path / "home"
    db = home / "Library" / "Group Containers" / "UBF8T346G9.Office" \
        / "MicrosoftRegistrationDB.reg"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(AB, "_any_office_running", lambda: False)
    _build(db, [(1, 0, "Software"),
                (2, 1, "SomethingElse"),
                (20, 2, f"file:///x/{MARK}/cd_aaa/src_1.pptx")])
    AB._purge_recents_sqlite()
    assert 20 in _nodes(db), "deleted a marked node outside the Recents subtree"


def test_a_marked_node_WITH_CHILDREN_is_left_alone(tmp_path, monkeypatch):
    """Our entries are leaves. Anything with children is a key, and removing a
    key would amputate whatever hangs off it."""
    home = tmp_path / "home"
    db = home / "Library" / "Group Containers" / "UBF8T346G9.Office" \
        / "MicrosoftRegistrationDB.reg"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(AB, "_any_office_running", lambda: False)
    _build(db, [(1, 0, "Software"), (2, 1, "MruUserData"), (3, 2, "Documents"),
                (30, 3, f"file:///x/{MARK}/cd_aaa"),
                (31, 30, "a child that would be orphaned")])
    AB._purge_recents_sqlite()
    left = _nodes(db)
    assert 30 in left and 31 in left, "amputated a subtree"


def test_it_declines_while_an_office_app_is_running(registry, monkeypatch):
    """A live app holds Recents in memory and rewrites this DB when it exits,
    resurrecting whatever was deleted - so a purge that races it produces the
    half-state for a different reason."""
    monkeypatch.setattr(AB, "_any_office_running", lambda: True)
    AB._purge_recents_sqlite()
    assert {10, 11} <= _nodes(registry), "purged while Office was running"


def test_the_running_check_does_not_LAUNCH_office(monkeypatch):
    """Asking the app over Apple events would start it - the opposite of what a
    'has everything shut down?' test wants."""
    import inspect
    src = inspect.getsource(AB._any_office_running)
    assert "pgrep" in src
    assert "osascript" not in src and "tell application" not in src


def test_the_running_check_is_TRUE_on_doubt(monkeypatch):
    """A skipped purge costs clutter; a purge racing a live app costs a
    half-rewritten shared registry."""
    def boom(*_a, **_k):
        raise OSError("pgrep unavailable")
    monkeypatch.setattr(AB.subprocess, "run", boom)
    assert AB._any_office_running() is True


def test_a_missing_registry_is_a_no_op(tmp_path, monkeypatch):
    home = tmp_path / "empty"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(AB, "_any_office_running", lambda: False)
    AB._purge_recents_sqlite()          # must not raise


def test_an_unexpected_schema_is_a_no_op(tmp_path, monkeypatch):
    """Office's schema is not ours to rely on; a deviation must no-op rather
    than guess at a shared registry."""
    home = tmp_path / "home"
    db = home / "Library" / "Group Containers" / "UBF8T346G9.Office" \
        / "MicrosoftRegistrationDB.reg"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE something_else (a INTEGER)")
    con.commit()
    con.close()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(AB, "_any_office_running", lambda: False)
    AB._purge_recents_sqlite()          # must not raise


def test_a_cycle_in_the_parent_chain_cannot_hang_the_walk(tmp_path, monkeypatch):
    """The ancestor walk follows parent_id through data we do not own."""
    home = tmp_path / "home"
    db = home / "Library" / "Group Containers" / "UBF8T346G9.Office" \
        / "MicrosoftRegistrationDB.reg"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(AB, "_any_office_running", lambda: False)
    _build(db, [(1, 2, "A"), (2, 1, "B"),
                (40, 1, f"file:///x/{MARK}/cd_aaa/src_1.pptx")])
    AB._purge_recents_sqlite()          # must terminate
    assert 40 in _nodes(db), "no MruUserData ancestor, so it must be left alone"
