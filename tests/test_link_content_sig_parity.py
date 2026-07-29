"""A shortcut's signature must describe the URL that is inside the shortcut.

``.url`` / ``.webloc`` files are written for module items, and their
``content_sig`` is what a later analysis compares to decide "changed or not".
The signature therefore has to be computed from the SAME url the file received.
It was not, for one item type, and the consequence was permanent:

    ExternalUrl   file holds external_url, signature used external_url    OK
    ExternalTool  file holds html_url,     signature used external_url    BROKEN

For a Panopto ExternalTool item ``external_url`` is the LTI launch endpoint -
``https://<host>/Panopto/LTI/LTI.aspx`` - literally the same string for every
recording in the course. So the recorded signature described a URL the file did
not contain and could never match the one stored at download time. Measured on
course 43660: **36 phantom "clean updates" on a folder downloaded minutes
earlier, with 0 md5 mismatches**. Every analysis, for ever; the user can never
reach "all up to date", and a daily auto-sync rewrites 36 shortcuts a day and
reports them as arrivals on the Today page.

The first attempt at the fix used one ordering for every type and turned the 5
correct ExternalUrl rows into phantoms instead - the same bug, moved. Hence the
tests below run BOTH directions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.canvas_logic import link_content_sig  # noqa: E402

SRC = (REPO / "core" / "canvas_logic.py").read_text(encoding="utf-8")

LTI = "https://cbs.cloud.panopto.eu/Panopto/LTI/LTI.aspx"


class _Item:
    def __init__(self, type_, title, html_url="", external_url=""):
        self.type = type_
        self.title = title
        self.html_url = html_url
        self.external_url = external_url


def _link_url(item):
    """The rule under test, mirrored from core.canvas_logic."""
    if item.type == "ExternalTool":
        return item.html_url or item.external_url or ""
    return item.external_url or item.html_url or ""


# --------------------------------------------------------------------------
# the rule
# --------------------------------------------------------------------------

def test_an_external_tool_is_identified_by_its_canvas_item_url():
    it = _Item("ExternalTool", "Forelæsningsvideo (1)",
               html_url="https://cbscanvas.instructure.com/courses/43660/modules/items/1128498",
               external_url=LTI)
    assert _link_url(it) == it.html_url


def test_an_external_url_is_identified_by_its_target():
    it = _Item("ExternalUrl", "Link til Saxo",
               html_url="https://cbscanvas.instructure.com/courses/43660/modules/items/9",
               external_url="https://www.linkedin.com/in/saxo-merrild/")
    assert _link_url(it) == it.external_url, \
        "switching this to html_url turned 5 correct rows into phantom updates"


def test_two_recordings_in_one_course_get_DIFFERENT_signatures():
    """The heart of it: the LTI endpoint cannot identify a recording.

    Every ExternalTool item in a course shares one external_url, so a signature
    built from it collapses all 36 recordings onto a handful of values that
    depend only on the title.
    """
    a = _Item("ExternalTool", "Forelæsningsvideo (1)",
              html_url="https://c.instructure.com/courses/43660/modules/items/1", external_url=LTI)
    b = _Item("ExternalTool", "Forelæsningsvideo (2)",
              html_url="https://c.instructure.com/courses/43660/modules/items/2", external_url=LTI)
    assert link_content_sig(a.title, _link_url(a)) != link_content_sig(b.title, _link_url(b))


def test_the_signature_matches_the_url_written_into_the_file():
    """The invariant the whole bug violated."""
    for it, written in (
        (_Item("ExternalTool", "Rec", html_url="https://c/modules/items/1",
               external_url=LTI), "https://c/modules/items/1"),
        (_Item("ExternalUrl", "Link", html_url="https://c/modules/items/2",
               external_url="https://example.org/x"), "https://example.org/x"),
    ):
        assert link_content_sig(it.title, _link_url(it)) == \
            link_content_sig(it.title, written)


def test_a_changed_target_still_changes_the_signature():
    """The feature must survive the fix: a re-pointed link re-syncs."""
    before = _Item("ExternalUrl", "Link", external_url="https://example.org/a")
    after = _Item("ExternalUrl", "Link", external_url="https://example.org/b")
    assert link_content_sig(before.title, _link_url(before)) != \
        link_content_sig(after.title, _link_url(after))


def test_a_renamed_link_still_changes_the_signature():
    a = _Item("ExternalTool", "Old name", html_url="https://c/modules/items/1")
    b = _Item("ExternalTool", "New name", html_url="https://c/modules/items/1")
    assert link_content_sig(a.title, _link_url(a)) != link_content_sig(b.title, _link_url(b))


@pytest.mark.parametrize("type_", ["ExternalTool", "ExternalUrl"])
def test_a_missing_url_never_raises(type_):
    assert isinstance(link_content_sig("t", _link_url(_Item(type_, "t"))), str)


# --------------------------------------------------------------------------
# the implementation still carries the rule
# --------------------------------------------------------------------------

def test_the_engine_special_cases_external_tool():
    i = SRC.find("_link_url = (")
    assert i > 0, "the link-signature rule moved; re-verify it against a real folder"
    block = SRC[i:i + 400]
    assert "item.type == 'ExternalTool'" in block, \
        "the ExternalTool special case is gone - 36 phantom updates come back"
    assert "html_url" in block and "external_url" in block


def test_the_signature_is_not_computed_from_actual_url():
    """``actual_url`` is html_url-first for EVERY type, which is right for the
    file's contents on ExternalTool and wrong on ExternalUrl."""
    i = SRC.find("_link_url = (")
    assert "link_content_sig(getattr(item, 'title', 'Untitled'),\n" in SRC[i:i + 900] \
        or "_link_url)" in SRC[i:i + 900]
    seg = SRC[i:i + 900]
    assert "actual_url)" not in seg, \
        "computing the signature from actual_url breaks the ExternalUrl case"
