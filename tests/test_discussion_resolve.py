"""Canvas can LIST a discussion and then refuse the individual GET for it.

Measured on course 43660, topic 166950 ("Spørgsmål til pensum i
organisationskultur")::

    course.get_discussion_topics()      -> returns it, WITH its 254-byte message
    course.get_discussion_topic(166950) -> ResourceDoesNotExist: Not Found

It is not a group discussion, it is not locked, and it opens fine in a browser.

The module-item path only ever tried the individual GET, so the item failed
outright: **no file written for a discussion the user can plainly read**, plus
a "Discussion Dispatch Error" on the completion screen naming something the
user cannot act on. It also inflated the run's error count, which is what
pushed three otherwise-clean matrix rows to "Download finished with N errors".

The fix is the shape the assignment path already uses - prefer the richer
object, keep the other as a fallback - just in the other direction.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from canvasapi.exceptions import Forbidden, ResourceDoesNotExist

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.canvas_logic import resolve_discussion_topic     # noqa: E402


class _Topic:
    def __init__(self, tid, title="T", message="<p>body</p>"):
        self.id, self.title, self.message = tid, title, message


class _Course:
    """`individual` maps id -> topic or exception; `listed` is the collection."""
    def __init__(self, individual=None, listed=(), list_raises=None):
        self._individual = individual or {}
        self._listed = list(listed)
        self._list_raises = list_raises
        self.list_calls = 0

    def get_discussion_topic(self, tid):
        got = self._individual.get(tid, ResourceDoesNotExist("Not Found"))
        if isinstance(got, Exception):
            raise got
        return got

    def get_discussion_topics(self):
        self.list_calls += 1
        if self._list_raises:
            raise self._list_raises
        return list(self._listed)


REAL = _Topic(166950, "Spørgsmål til pensum i organisationskultur",
              "<p>Kære alle</p>")


# --------------------------------------------------------------------------

def test_the_regression_a_listed_topic_the_individual_get_refuses():
    c = _Course(individual={}, listed=[REAL])
    got = resolve_discussion_topic(c, 166950)
    assert got.id == 166950
    assert got.message, "the body is what makes the fallback worth having"


def test_the_fast_path_is_still_the_individual_get():
    """The collection is a fallback, not a replacement - it costs a request
    per discussion and returns every topic in the course."""
    c = _Course(individual={166950: REAL}, listed=[REAL])
    assert resolve_discussion_topic(c, 166950).id == 166950
    assert c.list_calls == 0


def test_a_topic_that_is_genuinely_gone_still_raises():
    """Falling back must not turn a real absence into silence."""
    with pytest.raises(ResourceDoesNotExist):
        resolve_discussion_topic(_Course(individual={}, listed=[]), 999999)


def test_the_original_error_is_what_propagates():
    """The individual GET's reason is the useful one; the list merely did not
    contain the id."""
    c = _Course(individual={1: Forbidden("no")}, listed=[])
    with pytest.raises(Forbidden):
        resolve_discussion_topic(c, 1)


def test_a_broken_list_endpoint_does_not_mask_the_first_failure():
    c = _Course(individual={}, listed=[], list_raises=RuntimeError("network"))
    with pytest.raises(ResourceDoesNotExist):
        resolve_discussion_topic(c, 166950)


def test_the_right_topic_is_picked_out_of_the_collection():
    c = _Course(individual={}, listed=[_Topic(1), _Topic(2), REAL, _Topic(3)])
    assert resolve_discussion_topic(c, 166950).title.startswith("Spørgsmål")


def test_a_collection_that_lacks_the_id_falls_through_to_raising():
    c = _Course(individual={}, listed=[_Topic(1), _Topic(2)])
    with pytest.raises(ResourceDoesNotExist):
        resolve_discussion_topic(c, 166950)


# --------------------------------------------------------------------------
# every fetch site goes through the resolver
# --------------------------------------------------------------------------

import re  # noqa: E402

SRC = re.sub(r"^\s*#.*$", "",
             (REPO / "core" / "canvas_logic.py").read_text(encoding="utf-8"),
             flags=re.M)


def test_no_site_calls_the_individual_endpoint_directly():
    """Three call sites had the same single-endpoint assumption; a fourth
    added later would reintroduce the defect for its own path."""
    direct = [m for m in re.findall(r"course\.get_discussion_topic\([^s]", SRC)]
    assert len(direct) == 1, (
        "get_discussion_topic is called outside resolve_discussion_topic; "
        f"found {len(direct)}")


def test_all_three_sites_route_through_the_resolver():
    assert SRC.count("resolve_discussion_topic(") == 4     # 3 call sites + def
