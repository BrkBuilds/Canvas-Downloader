"""The discovery check may only demand files the run could actually reach.

A file linked only from inside an announcement body exists on Canvas whether or
not the run asked for announcements - but the app finds it by parsing bodies it
downloads, so with ``dl_announcements`` off it is out of scope, not missing.

Measured on the smoke run, course 43658 with only discussions and quizzes
enabled: one such attachment produced "1 file(s) exist on Canvas but were never
tracked", severity **high**. Most rows of a covering array enable only some
Canvas Content types, so that was a false high on most of the matrix - and a
false high is worse than no check, because it teaches the reader to skim.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness.crosscheck import _inline_not_requested  # noqa: E402

ALL_ON = {"dl_assignments": True, "dl_discussions": True,
          "dl_announcements": True, "dl_syllabus": True}


def _snap(**kw):
    base = {"files_tab": {}, "module_file_ids": [],
            "inline_by_source": {}, "inline_file_ids": []}
    base.update(kw)
    ids = set()
    for v in base["inline_by_source"].values():
        ids |= set(v)
    base.setdefault("inline_file_ids", sorted(ids))
    return base


def test_an_announcement_attachment_is_out_of_scope_when_announcements_are_off():
    """The regression."""
    snap = _snap(inline_by_source={"announcement": [1579688]})
    assert _inline_not_requested(snap, {"dl_discussions": True}) == {1579688}


def test_the_same_file_is_in_scope_when_announcements_are_on():
    snap = _snap(inline_by_source={"announcement": [1579688]})
    assert _inline_not_requested(snap, ALL_ON) == set()


@pytest.mark.parametrize("source,toggle", [
    ("assignment", "dl_assignments"),
    ("discussion", "dl_discussions"),
    ("announcement", "dl_announcements"),
    ("syllabus", "dl_syllabus"),
])
def test_every_source_is_gated_by_its_own_toggle(source, toggle):
    snap = _snap(inline_by_source={source: [99]})
    assert _inline_not_requested(snap, {}) == {99}
    assert _inline_not_requested(snap, {toggle: True}) == set()


def test_a_file_also_in_the_files_tab_is_never_excused():
    """It is reachable without the body, so an absent one IS a real gap."""
    snap = _snap(files_tab={"77": {"id": 77}},
                 inline_by_source={"announcement": [77]})
    assert _inline_not_requested(snap, {}) == set()


def test_a_file_also_on_a_module_is_never_excused():
    snap = _snap(module_file_ids=[77], inline_by_source={"announcement": [77]})
    assert _inline_not_requested(snap, {}) == set()


def test_only_the_off_sources_are_excluded():
    snap = _snap(inline_by_source={"announcement": [1], "discussion": [2]})
    assert _inline_not_requested(snap, {"dl_discussions": True}) == {1}


def test_a_snapshot_from_before_the_split_excludes_them_all():
    """Under-reporting is recoverable; a false high is not."""
    snap = {"files_tab": {}, "module_file_ids": [], "inline_file_ids": [1, 2, 3]}
    assert _inline_not_requested(snap, ALL_ON) == {1, 2, 3}


def test_a_pre_split_snapshot_still_respects_reachability():
    snap = {"files_tab": {"2": {"id": 2}}, "module_file_ids": [3],
            "inline_file_ids": [1, 2, 3]}
    assert _inline_not_requested(snap, {}) == {1}


def test_string_keyed_ids_from_a_json_round_trip_still_match():
    """Snapshots are cached as JSON, so every dict key comes back a string."""
    snap = _snap(files_tab={"77": {"id": 77}},
                 inline_by_source={"announcement": ["77"]})
    assert _inline_not_requested(snap, {}) == set()


def test_nothing_inline_is_a_quiet_empty_set():
    assert _inline_not_requested(_snap(), ALL_ON) == set()
    assert _inline_not_requested({}, {}) == set()


# --------------------------------------------------------------------------
# the oracle must mirror the product, not out-strict it
# --------------------------------------------------------------------------
#
# `core.canvas_logic._extract_canvas_file_links` reads `<a href>` and nothing
# else - a deliberate contract, since an `<img>` in a body is a banner rendered
# inside the saved page, not an attachment the student is missing. A raw
# `/files/(\d+)` sweep matched the `<img src>` AND the `data-api-endpoint`
# beside it, and course 43658's two discussions open with the same 15 KB
# banner, so the discovery check demanded a file the app is not supposed to
# fetch. An oracle stricter than the product does not find bugs, it invents
# them - and this one invented a HIGH.

from core.canvas_logic import _extract_canvas_file_links          # noqa: E402
from tests.audit.harness.oracles.canvas import (                  # noqa: E402
    inline_linked_file_ids)

BANNER = ('<p><img src="https://x/courses/43658/files/1579688/preview?verifier=A"'
          ' alt="banner" data-api-endpoint="https://x/api/v1/courses/43658/'
          'files/1579688"></p>')
ANCHOR = ('<p><a href="/courses/43658/files/98765/download?download_frd=1">'
          'Slides.pdf</a></p>')

PARITY_BODIES = [
    "", None, "<p>no files at all</p>",
    BANNER, ANCHOR, BANNER + ANCHOR,
    '<a href="https://cbs.dk/elsewhere">not canvas</a>',
    '<a href="/files/abc/download">malformed id</a>',
    '<a href="/courses/1/files/222?wrap=1">wrapped</a>',
    '<a href="/files/333/download">bare</a><a href="/files/333">dupe</a>',
    '<iframe src="/courses/1/files/444/preview"></iframe>',
]


@pytest.mark.parametrize("html", PARITY_BODIES)
def test_the_oracle_extracts_exactly_what_the_product_extracts(html):
    product = {d["file_id"] for d in _extract_canvas_file_links(html)}
    assert inline_linked_file_ids(html or "") == product


def test_a_banner_image_is_not_an_expected_file():
    """The regression, with the real markup from discussion 162603."""
    assert inline_linked_file_ids(BANNER) == set()


def test_a_linked_attachment_still_is():
    assert inline_linked_file_ids(ANCHOR) == {98765}


# --------------------------------------------------------------------------
# a file the app reached through a body is recorded under a SYNTHETIC id
# --------------------------------------------------------------------------
#
# `sync_manager.make_secondary_id('attachment', fid)` == -(fid + 90_000_000).
# Course 45899's nine assignment/announcement attachments are all stored that
# way, so a `canvas_file_id > 0` filter erased every one and the discovery
# check reported nine files "never tracked" on a run whose own log shows it
# fetching each one by name - the exact population inline scoping exists to
# police, invisible to the check that polices it.

from core.sync_manager import make_secondary_id                   # noqa: E402
from tests.audit.harness.crosscheck import tracked_file_ids       # noqa: E402


def test_an_attachment_row_resolves_back_to_its_canvas_id():
    row = {"canvas_file_id": make_secondary_id("attachment", 1808520)}
    assert tracked_file_ids({"rows": [row]}) == {1808520}


def test_the_encoding_matches_the_product_exactly():
    assert make_secondary_id("attachment", 1808520) == -91808520


def test_a_plain_file_row_is_unchanged():
    assert tracked_file_ids({"rows": [{"canvas_file_id": 1637104}]}) == {1637104}


@pytest.mark.parametrize("etype", ["assignment", "announcement", "discussion",
                                   "quiz", "page", "submission"])
def test_a_synthetic_ENTITY_is_not_mistaken_for_a_file(etype):
    """Only 'attachment' ids wrap a real Canvas file id. A page or assignment
    id wraps the ENTITY id, which shares a number space with nothing."""
    row = {"canvas_file_id": make_secondary_id(etype, 42)}
    assert tracked_file_ids({"rows": [row]}) == set()


def test_a_legacy_module_item_id_is_not_a_file():
    assert tracked_file_ids({"rows": [{"canvas_file_id": -251847}]}) == set()


def test_a_malformed_row_is_skipped_quietly():
    assert tracked_file_ids({"rows": [{"canvas_file_id": None}, {}, {"x": 1}]}) == set()
    assert tracked_file_ids({}) == set()


# --------------------------------------------------------------------------
# a converter's SIDECAR has no manifest row, by the product's own account
# --------------------------------------------------------------------------
#
# `convert_excel` writes `<stem>_Data.txt` beside each workbook's PDF, and
# `converters/post_processing.py` says so in its own words: "Do NOT update
# manifest - _Data.txt is an untracked sidecar". The registry has carried
# `"sidecar": "_Data.txt"` all along and nothing read it, so the first Excel
# row of the matrix reported the sidecar as an orphan at HIGH - "wrongfully
# shows up as new", which is the opposite of what happens.

from tests.audit.harness.crosscheck import (                      # noqa: E402
    CONVERTERS, Evidence, _conversion_sidecars)


def test_the_excel_sidecar_is_declared_by_the_registry():
    assert CONVERTERS["convert_excel"]["sidecar"] == "_Data.txt"


def test_the_sidecar_is_exempt_only_when_its_converter_ran():
    on = Evidence(folder=None, expect={"convert_excel": True}, db={})
    off = Evidence(folder=None, expect={"convert_excel": False}, db={})
    assert _conversion_sidecars(on) == ("_data.txt",)
    assert _conversion_sidecars(off) == ()


def test_the_contract_outranks_the_caller():
    """_converters_on reads the stored contract first, so a re-check with a
    stale `expect` still gets the exemption right."""
    ev = Evidence(folder=None, expect={"convert_excel": False},
                  db={"contracts": {"sync": {"convert_excel": True}}})
    assert _conversion_sidecars(ev) == ("_data.txt",)
