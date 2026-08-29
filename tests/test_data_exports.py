"""The published dataset must not drift from the module it is generated from.

WHAT THIS GUARDS, and why it is shaped as a census
--------------------------------------------------
``docs/data/canvas-hosts.csv`` and ``.json`` are generated from
``shared/institutions.py`` by ``scripts/build_data_exports.py``. Nothing forces
anyone to re-run that script, so the realistic failure is silent: somebody
regenerates the institution list, ships a new picker, and the published data
keeps describing the old one. A dataset that quietly disagrees with its own
stated method is worse than no dataset, because the whole reason to publish it
was that it could be checked.

So the comparison is ROW BY ROW against ``DATA``, not a count. A count passes
when a hostname changes, and a hostname changing is exactly what this exists to
catch.

It also pins two decisions that are easy to undo by accident:

* **``canvas-data.html`` carries no CTA box.** Census 2026-08-29 found 12 of 12
  generated articles ending in a Download button, which is why nothing on this
  site is citable by the people who actually publish links. This page is
  addressed to a builder or a help desk and sells nothing. Adding one later
  would be a one-line change that quietly removes the only page on the site
  written for that reader.
* **The licence is stated once.** It lives in ``build_data_exports.LICENCE`` and
  reaches the page and the JSON from there. A hand-typed second copy is the
  defect this repo has recorded three times elsewhere, and on a licence it is
  the copy people rely on.
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from shared.institutions import DATA, COUNT  # noqa: E402
import build_data_exports as bde  # noqa: E402

CSV_PATH = DOCS / "data" / "canvas-hosts.csv"
JSON_PATH = DOCS / "data" / "canvas-hosts.json"
PAGE_PATH = DOCS / "canvas-data.html"


def _expected() -> list[tuple[str, str, str, str]]:
    """DATA in the exports' own shape: curated as "1"/"0" rather than a flag."""
    return [(name, host, cc, "1" if "s" in flags else "0")
            for name, host, cc, flags in DATA]


@pytest.fixture(scope="module")
def csv_rows() -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def json_doc() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE_PATH.read_text(encoding="utf-8")


def test_all_three_artifacts_exist() -> None:
    missing = [p.relative_to(REPO).as_posix()
               for p in (CSV_PATH, JSON_PATH, PAGE_PATH) if not p.is_file()]
    assert not missing, (
        f"missing published data: {missing}. Run "
        "`python scripts/build_data_exports.py`.")


def test_csv_matches_the_institution_module_row_for_row(csv_rows) -> None:
    got = [(r["institution"], r["canvas_host"], r["country"], r["curated"])
           for r in csv_rows]
    want = _expected()
    assert len(got) == len(want) == COUNT, (
        f"canvas-hosts.csv has {len(got)} rows, shared/institutions.py has "
        f"{len(want)}. Re-run scripts/build_data_exports.py.")
    diff = [(a, b) for a, b in zip(got, want) if a != b]
    assert not diff, (
        f"{len(diff)} row(s) in canvas-hosts.csv disagree with "
        f"shared/institutions.py. First: published {diff[0][0]!r} against "
        f"module {diff[0][1]!r}. Re-run scripts/build_data_exports.py.")


def test_json_matches_the_institution_module_row_for_row(json_doc) -> None:
    got = [(r["institution"], r["canvas_host"], r["country"],
            "1" if r["curated"] else "0")
           for r in json_doc["institutions"]]
    want = _expected()
    assert len(got) == len(want) == COUNT
    diff = [(a, b) for a, b in zip(got, want) if a != b]
    assert not diff, (
        f"{len(diff)} row(s) in canvas-hosts.json disagree with "
        f"shared/institutions.py. First: published {diff[0][0]!r} against "
        f"module {diff[0][1]!r}. Re-run scripts/build_data_exports.py.")


def test_json_count_is_the_real_count(json_doc) -> None:
    """The advertised figure and the array cannot disagree.

    The page, the meta description and the JSON all print a number, and a
    hand-maintained one is how `canvas-url-directory.html` ended up rendering
    the same count three different ways.
    """
    assert json_doc["count"] == COUNT == len(json_doc["institutions"])


def test_the_dataset_never_claims_to_be_exhaustive(json_doc, page) -> None:
    """The picker's honesty rule, carried into the published data.

    A student whose school is missing must never conclude the app does not
    support them, and a machine reading the JSON must not conclude the list is
    a census of Canvas.
    """
    assert json_doc["exhaustive"] is False
    assert "not exhaustive" in page.lower()


def test_the_licence_is_stated_once_and_reaches_both_surfaces(json_doc, page) -> None:
    assert json_doc["licence"] == bde.LICENCE
    assert json_doc["licence_url"] == bde.LICENCE_URL
    assert bde.LICENCE in page
    assert bde.LICENCE_URL in page


def test_the_page_links_both_files_and_they_resolve_on_disk(page) -> None:
    for rel in (bde.CSV_NAME, bde.JSON_NAME):
        assert f'href="{rel}"' in page, f"canvas-data.html does not link {rel}"
        assert (DOCS / rel).is_file(), f"{rel} is linked but not on disk"


def test_canvas_data_page_has_no_cta_box(page) -> None:
    """The one page on this site that must not end by selling the app.

    Its whole reason to exist is that a help desk, a builder or an assistant can
    cite it without editing it first.
    """
    assert "cta-box" not in page, (
        "canvas-data.html has acquired a CTA box. It is the only search-facing "
        "page written for the people who publish links rather than for a "
        "student mid-task, and a Download button is what stops such a page "
        "being cited. See .claude/rules/website.md.")


def test_verified_date_is_a_real_date_or_absent(json_doc) -> None:
    """A provenance date must be true or missing, never guessed.

    ``verified_date()`` reads git history for one file, and CI clones shallow,
    so an empty string is a legitimate answer rather than a failure.
    """
    when = json_doc["verified"]
    assert when == "" or (len(when) == 10 and when[4] == when[7] == "-"), when
