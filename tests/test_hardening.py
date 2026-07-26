"""Regression tests for the robustness pass over value-critical paths.

Each test here corresponds to a defect found by re-reviewing code written earlier
in the same session, so they are the guard against it coming back.
"""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.sync_manager import (                     # noqa: E402
    SECONDARY_ID_OFFSETS, make_secondary_id, secondary_id_type,
)
from core.canvas_logic import (                     # noqa: E402
    _submission_comment_attachments, _submission_entity_id, humanize_canvas_error,
)


def _sub(**kw):
    return types.SimpleNamespace(**kw)


# ---------------------------------------------------------------------------
# Synthetic-id range boundary
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entity_type", sorted(SECONDARY_ID_OFFSETS))
def test_raw_id_zero_stays_in_its_own_range(entity_type):
    """`make_secondary_id(t, 0)` lands exactly on t's offset. With a strict `>`
    that was classified as the range BELOW - submission read as 'calendar' - and
    sync/execution.py gates real routing on `== 'attachment'`."""
    got = secondary_id_type(make_secondary_id(entity_type, 0))
    expected = "unknown" if entity_type == "module_item" else entity_type
    assert got == expected


@pytest.mark.parametrize("entity_type", sorted(SECONDARY_ID_OFFSETS))
def test_ordinary_ids_still_classify(entity_type):
    assert secondary_id_type(make_secondary_id(entity_type, 12345)) == entity_type


def test_positive_and_zero_ids_are_unknown():
    assert secondary_id_type(0) == "unknown"
    assert secondary_id_type(5_000) == "unknown"


# ---------------------------------------------------------------------------
# Submission identity - the enumerator and the downloader must agree
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sub,expected", [
    (_sub(assignment_id=42),                                    42),
    (_sub(assignment_id=None, assignment={"id": 7}),             7),
    (_sub(assignment_id=None, assignment=_sub(id=9)),            9),
    (_sub(assignment_id="15", assignment=None),                 15),
    (_sub(assignment_id=-3, assignment=None),                    3),
    (_sub(assignment_id=None, assignment=None),               None),
    (_sub(assignment_id=0, assignment=None),                  None),
    (_sub(assignment_id="abc", assignment=None),              None),
    (_sub(),                                                  None),
])
def test_submission_entity_id(sub, expected):
    assert _submission_entity_id(sub) == expected


def test_id_less_submissions_do_not_collide():
    """The whole point of returning None: fabricating 0 gave EVERY id-less
    submission the same synthetic id, so two would share one manifest row and one
    feedback file would overwrite the other."""
    a = _sub(assignment_id=None, assignment=None)
    b = _sub(assignment_id=None, assignment=None)
    assert _submission_entity_id(a) is None and _submission_entity_id(b) is None


# ---------------------------------------------------------------------------
# "Never returns the student's own uploads"
# ---------------------------------------------------------------------------

def test_never_returns_own_submission_attachments():
    """`sub.attachments` is the student's own upload and must never be collected -
    only files a teacher attached to a comment."""
    sub = _sub(
        attachments=[{"id": 111, "url": "https://x/own.pdf", "filename": "own.pdf"}],
        submission_comments=[
            {"comment": "see notes",
             "attachments": [{"id": 222, "url": "https://x/marked.pdf",
                              "filename": "marked.pdf"}]},
        ],
    )
    got = _submission_comment_attachments(sub)
    ids = {a["id"] for a in got}
    assert ids == {222}, "must contain ONLY the teacher's comment attachment"
    assert 111 not in ids


def test_comment_attachments_dedupe_and_skip_incomplete():
    sub = _sub(submission_comments=[
        {"attachments": [{"id": 1, "url": "u1", "filename": "a"},
                         {"id": 1, "url": "u1", "filename": "a"}]},   # dup
        {"attachments": [{"id": 2, "filename": "no-url"}]},           # no url -> skip
        {"attachments": [{"url": "u3", "filename": "no-id"}]},        # no id  -> skip
        {"attachments": "not-a-list"},                                # malformed
    ])
    assert [a["id"] for a in _submission_comment_attachments(sub)] == [1]


def test_comment_attachments_on_empty_submission():
    assert _submission_comment_attachments(_sub()) == []


# ---------------------------------------------------------------------------
# humanize_canvas_error must NEVER raise - it runs inside except blocks
# ---------------------------------------------------------------------------

class _Exc(Exception):
    def __init__(self, text, payload=None):
        super().__init__(text)
        self.message = payload if payload is not None else text


def test_extracts_the_human_message():
    e = _Exc("{'errors': [{'message': 'Invalid access token.'}]}")
    assert humanize_canvas_error(e) == "Invalid access token."


def test_survives_deeply_nested_repr():
    """A pathological payload must not raise RecursionError out of an except
    block - that would replace the real error with a confusing one."""
    e = _Exc("[" * 300 + "]" * 300)
    assert isinstance(humanize_canvas_error(e), str)


def test_survives_deeply_nested_payload_object():
    node = {"message": "deep"}
    for _ in range(600):
        node = {"wrap": node}
    assert isinstance(humanize_canvas_error(_Exc("fallback", payload=node)), str)


def test_oversized_payload_is_not_parsed_but_still_returns():
    e = _Exc("{'errors': [{'message': '" + "x" * 70_000 + "'}]}")
    assert isinstance(humanize_canvas_error(e), str)


@pytest.mark.parametrize("exc", [None, _Exc(""), _Exc("plain text error")])
def test_degenerate_inputs(exc):
    assert isinstance(humanize_canvas_error(exc), str)


# ---------------------------------------------------------------------------
# remove_provision - destructive, so guards matter
# ---------------------------------------------------------------------------

def test_remove_provision_refuses_while_provisioning(monkeypatch):
    import panopto.cuda_provision as cp
    monkeypatch.setattr(cp, "is_running", lambda: True)
    called = []
    monkeypatch.setattr(cp.shutil, "rmtree", lambda *a, **k: called.append(a))
    assert cp.remove_provision() is False
    assert called == [], "must not delete while an extract is in flight"


def test_remove_provision_true_when_already_absent(monkeypatch, tmp_path):
    import panopto.cuda_provision as cp
    monkeypatch.setattr(cp, "is_running", lambda: False)
    monkeypatch.setattr(cp, "cuda_libs_dir", lambda: tmp_path / "not-there")
    assert cp.remove_provision() is True


def test_remove_provision_reports_false_on_partial_delete(monkeypatch, tmp_path):
    """Windows keeps the CUDA DLLs loaded, so rmtree(ignore_errors=True) leaves
    them behind. Reporting True there made the caller's "may be in use" notice
    unreachable and claimed ~1.3 GB was freed when it was not."""
    import panopto.cuda_provision as cp
    libs = tmp_path / "cuda_libs"
    libs.mkdir()
    (libs / "locked.dll").write_bytes(b"x")
    monkeypatch.setattr(cp, "is_running", lambda: False)
    monkeypatch.setattr(cp, "cuda_libs_dir", lambda: libs)
    monkeypatch.setattr(cp.shutil, "rmtree", lambda *a, **k: None)   # simulate a no-op
    assert cp.remove_provision() is False


def test_remove_provision_true_on_real_delete(monkeypatch, tmp_path):
    import panopto.cuda_provision as cp
    libs = tmp_path / "cuda_libs"
    (libs / "sub").mkdir(parents=True)
    (libs / "sub" / "a.dll").write_bytes(b"x")
    monkeypatch.setattr(cp, "is_running", lambda: False)
    monkeypatch.setattr(cp, "cuda_libs_dir", lambda: libs)
    assert cp.remove_provision() is True
    assert not libs.exists()
