"""Which converters ran is read from EVIDENCE, never from what a caller passed.

Three checks in the audit depend on knowing whether a source-consuming
converter was on. All three were gated on the caller handing in a config in one
particular shape, and all three went silently quiet when it did not:

* ``convert_urls`` consumes every ``.url`` and writes one
  ``Compiled_External_Links.txt``. The exemption for that read
  ``expect["converters"]`` while ``check download`` is handed a FLAT config, so
  25 rows the engine had deliberately consumed were reported as a broken
  manifest — on a folder the app had just downloaded perfectly. The comment
  beside the check even predicted the number.
* The compiled output itself has no manifest row by design, and was the entire
  content of the standing "1 content file on disk with no manifest row"
  finding.
* Archive extraction produces thousands of untracked files. That exemption was
  gated the same way, so the identical folder reported 1 orphan through
  ``check download`` and 21,641 through ``check sync``.

The fix in every case is the same: the ``sync_contract`` the app stored in the
folder is what the engine itself obeys, so it cannot drift from reality the way
a caller's argument can.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import crosscheck  # noqa: E402


def _ev(*, contract=None, expect=None):
    return crosscheck.Evidence(
        folder=Path("/x"), db={"exists": True, "rows": [],
                               "contracts": {"sync": contract or {}}},
        expect=expect or {},
        log={"tracebacks": 0, "unexpected": [], "total_lines": 0})


# --------------------------------------------------------------------------
# where the answer comes from
# --------------------------------------------------------------------------

def test_the_stored_contract_is_the_source_of_truth():
    ev = _ev(contract={"convert_urls": True, "convert_zip": False})
    on = crosscheck._converters_on(ev)
    assert on["convert_urls"] is True and on["convert_zip"] is False


def test_the_contract_beats_a_caller_who_says_otherwise():
    """The folder knows what it was built with; the caller is guessing."""
    ev = _ev(contract={"convert_urls": True},
             expect={"converters": {"convert_urls": False}})
    assert crosscheck._converters_on(ev)["convert_urls"] is True


def test_a_flat_expect_is_accepted_when_there_is_no_contract():
    """The shape ``check download`` actually passes, and the bug's root cause."""
    ev = _ev(expect={"convert_urls": True, "mode": "modules", "file_filter": "all"})
    on = crosscheck._converters_on(ev)
    assert on.get("convert_urls") is True
    assert "mode" not in on and "file_filter" not in on


def test_a_nested_expect_is_accepted_too():
    ev = _ev(expect={"converters": {"convert_urls": True}})
    assert crosscheck._converters_on(ev).get("convert_urls") is True


def test_no_evidence_at_all_yields_nothing_rather_than_guessing():
    assert crosscheck._converters_on(_ev()) == {}


# --------------------------------------------------------------------------
# the aggregate output
# --------------------------------------------------------------------------

def test_the_compiled_links_file_is_recognised_as_a_conversion_product():
    ev = _ev(contract={"convert_urls": True})
    assert crosscheck._key("Compiled_External_Links.txt") in \
        crosscheck._conversion_aggregates(ev)


def test_nothing_is_exempted_when_the_converter_was_off():
    """The exemption must be earned. With convert_urls off, a file by that name
    on disk really is an orphan and should be reported."""
    ev = _ev(contract={"convert_urls": False})
    assert crosscheck._conversion_aggregates(ev) == set()


def test_only_converters_that_declare_an_aggregate_contribute_one():
    ev = _ev(contract={k: True for k in crosscheck.CONVERTERS})
    aggs = crosscheck._conversion_aggregates(ev)
    declared = {crosscheck._key(s["aggregate"])
                for s in crosscheck.CONVERTERS.values() if s.get("aggregate")}
    assert aggs == declared


# --------------------------------------------------------------------------
# end to end through invariants
# --------------------------------------------------------------------------

def _folder_ev(tmp_path, *, contract, rows, files):
    disk = {"exists": True, "content_count": len(files), "partials": [],
            "zero_bytes": [], "long_paths": [], "app_generated": [],
            "secondary_html": [], "dirs": [],
            "files": [{"rel": r, "name": Path(r).name, "size": 1, "ext": Path(r).suffix,
                       "app_generated": False, "partial": False,
                       "secondary_html": False, "new_version": False, "md5": "m"}
                      for r in files]}
    db = {"exists": True, "contracts": {"sync": contract},
          "rows": [{"canvas_file_id": i, "canvas_filename": Path(r).name,
                    "local_path": r, "is_ignored": False, "entity": "file",
                    "original_size": 1, "original_md5": "m"}
                   for i, r in enumerate(rows, 1)]}
    return crosscheck.Evidence(
        folder=tmp_path, disk=disk, db=db,
        log={"tracebacks": 0, "unexpected": [], "total_lines": 0})


def test_consumed_url_rows_are_an_observation_not_a_broken_manifest(tmp_path):
    ev = _folder_ev(tmp_path, contract={"convert_urls": True},
                    rows=["a.url", "b.url"], files=["Compiled_External_Links.txt"])
    found = crosscheck.invariants(ev)
    titles = [f.title for f in found]
    assert not any("point at files that do not exist" in t for t in titles), titles
    assert any("a converter consumed" in t for t in titles)
    assert not any("no manifest row" in t for t in titles), titles


def test_with_the_converter_off_the_same_folder_is_genuinely_broken(tmp_path):
    """Proves the exemption is doing work rather than blanket-silencing."""
    ev = _folder_ev(tmp_path, contract={"convert_urls": False},
                    rows=["a.url", "b.url"], files=["Compiled_External_Links.txt"])
    titles = [f.title for f in crosscheck.invariants(ev)]
    assert any("point at files that do not exist" in t for t in titles)
    assert any("no manifest row" in t for t in titles)


def test_a_genuinely_missing_pdf_is_still_reported_alongside_consumed_urls(tmp_path):
    """The exemption is per-extension, not per-run: it must not hide a real one."""
    ev = _folder_ev(tmp_path, contract={"convert_urls": True},
                    rows=["a.url", "lecture.pdf"], files=[])
    titles = [f.title for f in crosscheck.invariants(ev)]
    assert any("1 manifest row(s) point at files that do not exist" in t
               for t in titles), titles
