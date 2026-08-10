"""Recordings are checked O5 -> O4 -> O3, because nothing else can see them.

A Panopto recording has no Canvas file id. It lives in its own
``panopto_manifest`` table, so every file-based check in ``crosscheck`` walks
straight past it: a run that discovers 6 of 36 recordings, or discovers 36 and
writes 0 files, produces a completion screen that looks entirely healthy.

Three numbers have to agree, and the gaps between them mean different things:

    O5 -> O4   discovery. This project has shipped "6 of 36 found" before, when
               a per-item LTI launch regressed to a generic tool launch.
    O4 -> O4   production. Discovered, but no output row for a requested kind.
    O4 -> O3   delivery. A row exists and the file is not on disk.

Separating them matters because the remedy differs: the first is an auth/launch
problem, the second a pipeline problem, the third a write problem.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import crosscheck  # noqa: E402


def _ev(*, expect=None, external_tools=36, discovered=36, kinds=None,
        disk_exts=None, ignored=0):
    files = []
    for ext, n in (disk_exts or {}).items():
        files += [{"rel": f"rec{i}{ext}", "name": f"rec{i}{ext}", "ext": ext,
                   "size": 1, "md5": "m", "app_generated": False,
                   "partial": False, "secondary_html": False,
                   "new_version": False} for i in range(n)]
    return crosscheck.Evidence(
        folder=Path("/x"),
        disk={"exists": True, "files": files, "content_count": len(files),
              "partials": [], "zero_bytes": [], "long_paths": [],
              "app_generated": [], "secondary_html": [], "dirs": []},
        db={"exists": True, "rows": [], "contracts": {"sync": {}},
            "panopto_discovery_cached": discovered,
            "panopto_kinds": kinds or {},
            "panopto_ignored": [{"video_id": str(i)} for i in range(ignored)]},
        canvas=_canvas(external_tools),
        log={"tracebacks": 0, "unexpected": [], "total_lines": 0},
        expect=expect or {"pan_out_mp3": True}, scenario="p4")


# Recordings are counted by the tool's HOST, not by the item TYPE - an
# ExternalTool is only a recording if it launches Panopto. Course 45899's
# twelve are Alma library citations, and counting the type would make every row
# against it report "Panopto found 0 of 12": a high-severity discovery failure
# invented out of a bibliography.
PANOPTO_URL = "https://cbs.cloud.panopto.eu/Panopto/LTI/LTI.aspx"
ALMA_URL = ("https://kbdk-cbs.alma.exlibrisgroup.com/lti/v3/launch/"
            "45KBDK_CBS/LMS_CANVAS_1.3?citation_id=4026745000005765")


def _canvas(panopto_tools: int, alma_tools: int = 0) -> dict:
    items = [{"type": "ExternalTool", "title": f"Forelæsningsvideo {i}",
              "external_url": PANOPTO_URL} for i in range(panopto_tools)]
    items += [{"type": "ExternalTool", "title": f"Reading {i}",
               "external_url": ALMA_URL} for i in range(alma_tools)]
    return {"modules": [{"items": items}],
            "module_item_types": {"ExternalTool": panopto_tools + alma_tools}}


def _titles(f):
    return [x.title for x in f]


# --------------------------------------------------------------------------
# scope
# --------------------------------------------------------------------------

def test_nothing_is_checked_when_no_panopto_output_was_requested():
    out = crosscheck._panopto_delivery(_ev(expect={"convert_zip": True}))
    assert out == []


def test_a_healthy_run_is_silent():
    out = crosscheck._panopto_delivery(
        _ev(kinds={"mp3": 36}, disk_exts={".mp3": 36}))
    assert out == [], _titles(out)


# --------------------------------------------------------------------------
# O5 -> O4 : discovery
# --------------------------------------------------------------------------

def test_a_short_discovery_is_reported():
    """The "6 of 36" regression, which looks healthy on screen."""
    out = crosscheck._panopto_delivery(
        _ev(discovered=6, kinds={"mp3": 6}, disk_exts={".mp3": 6}))
    assert any("found 6 of 36 recordings" in t for t in _titles(out))
    assert out[0].severity == "high"


def test_discovering_nothing_at_all_is_reported_separately():
    """TotalNumber 0 means the LTI cookie has no folder grants - a different
    problem from finding some but not all, and a different fix."""
    out = crosscheck._panopto_delivery(_ev(discovered=0, kinds={}))
    titles = _titles(out)
    assert any("nothing was discovered" in t for t in titles)
    assert not any("found 0 of" in t for t in titles), \
        "the two discovery failures must not both fire"


def test_discovering_more_than_expected_is_not_a_finding():
    """Not every ExternalTool has to be Panopto, and a course can carry
    recordings that are not module items."""
    out = crosscheck._panopto_delivery(
        _ev(external_tools=30, discovered=36, kinds={"mp3": 36},
            disk_exts={".mp3": 36}))
    assert out == [], _titles(out)


def test_a_download_run_has_no_discovery_cache_and_must_still_read_clean():
    """The cache is written by the SYNC path only.

    ``panopto_discovery_cache`` is a 24h reuse cache for Quick Sync and the
    Today auto-sync; a download run never writes it. Reading it alone reported
    "nothing was discovered" on a run that had just downloaded 36 of 36 - a
    fabricated high finding on a perfect run, measured on 2026-07-28.
    """
    out = crosscheck._panopto_delivery(
        _ev(discovered=0, kinds={"mp3": 36}, disk_exts={".mp3": 36}))
    assert out == [], _titles(out)


def test_the_manifest_still_reveals_a_short_run_without_a_cache():
    """Falling back to rows must not blind the discovery check."""
    out = crosscheck._panopto_delivery(
        _ev(discovered=0, kinds={"mp3": 6}, disk_exts={".mp3": 6}))
    assert any("found 6 of 36 recordings" in t for t in _titles(out))


def test_no_expectation_from_canvas_means_no_discovery_claim():
    out = crosscheck._panopto_delivery(
        _ev(external_tools=0, discovered=36, kinds={"mp3": 36},
            disk_exts={".mp3": 36}))
    assert out == []


# --------------------------------------------------------------------------
# O4 -> O4 : production
# --------------------------------------------------------------------------

def test_a_requested_output_with_no_rows_is_reported():
    out = crosscheck._panopto_delivery(_ev(kinds={}, disk_exts={}))
    assert any("no mp3 rows were recorded" in t for t in _titles(out))


def test_a_partial_output_is_medium_and_names_the_ignored_count():
    """Ignored recordings are excluded by design, so this must not read as a
    hard failure until panopto_ignored has been checked."""
    out = crosscheck._panopto_delivery(
        _ev(kinds={"mp3": 30}, disk_exts={".mp3": 30}, ignored=6))
    hit = next(f for f in out if "30 mp3 of 36" in f.title)
    assert hit.severity == "medium"
    assert hit.evidence["ignored"] == 6


@pytest.mark.parametrize("key,ext", list(crosscheck.PANOPTO_OUTPUTS.items()))
def test_every_output_kind_is_checked(key, ext):
    """The check must exist for every configured output.

    The token to look for is the KIND, not the extension with its dot removed.
    Those are the same word for mp3/mp4/txt/srt and NOT for the shortcut, which
    is kind ``url`` while its extension is ``.url`` on Windows and ``.webloc``
    on macOS - so an ext-derived token passed on Windows by coincidence and
    failed on macOS, looking for a kind the engine never records. The checker
    itself resolves this correctly through ``kind_from_path`` and says why in a
    comment; this test, which guards it, made the exact mistake that comment
    warns about. Resolve it the same way rather than restating the mapping.
    """
    from panopto.shortcut import kind_from_path
    token = kind_from_path("x" + ext) or ext.lstrip(".")
    out = crosscheck._panopto_delivery(
        _ev(expect={key: True}, kinds={}, disk_exts={}))
    titles = _titles(out)
    assert any(token in t for t in titles), (
        f"{key} produces no check at all (looked for {token!r} in {titles})")


def test_several_requested_outputs_are_each_checked():
    out = crosscheck._panopto_delivery(
        _ev(expect={"pan_out_mp3": True, "pan_out_srt": True},
            kinds={"mp3": 36}, disk_exts={".mp3": 36}))
    titles = _titles(out)
    assert any("srt" in t for t in titles)
    assert not any("mp3" in t for t in titles), "the healthy kind must stay quiet"


# --------------------------------------------------------------------------
# O4 -> O3 : delivery
# --------------------------------------------------------------------------

def test_rows_without_files_on_disk_are_reported():
    out = crosscheck._panopto_delivery(
        _ev(kinds={"mp3": 36}, disk_exts={".mp3": 30}))
    assert any("6 Panopto mp3 row(s) have no file on disk" in t
               for t in _titles(out))


def test_more_files_than_rows_is_not_a_delivery_failure():
    """A folder may hold recordings from an earlier run under a different
    contract; only a row with no file is a broken promise."""
    out = crosscheck._panopto_delivery(
        _ev(kinds={"mp3": 36}, disk_exts={".mp3": 40}))
    assert not any("no file on disk" in t for t in _titles(out))


# --------------------------------------------------------------------------
# a recording is a PANOPTO launch, not any ExternalTool
# --------------------------------------------------------------------------

def test_library_citations_are_not_counted_as_recordings():
    """Course 45899 has twelve Alma citations and zero recordings. Counting the
    item TYPE turned that into "Panopto found 0 of 12" - a high-severity
    discovery failure invented out of a bibliography."""
    ev = crosscheck.Evidence(
        folder=Path("/x"),
        disk={"exists": True, "files": [], "content_count": 0, "partials": [],
              "zero_bytes": [], "long_paths": [], "app_generated": [],
              "secondary_html": [], "dirs": []},
        db={"exists": True, "rows": [], "contracts": {"sync": {}},
            "panopto_discovery_cached": 0, "panopto_kinds": {},
            "panopto_ignored": []},
        canvas=_canvas(0, alma_tools=12),
        log={"tracebacks": 0, "unexpected": [], "total_lines": 0},
        expect={"pan_out_mp3": True}, scenario="p4")
    assert crosscheck._panopto_delivery(ev) == []


def test_a_mixed_course_counts_only_the_panopto_launches():
    out = crosscheck._panopto_delivery(
        _ev(external_tools=36, discovered=36, kinds={"mp3": 36},
            disk_exts={".mp3": 36}))
    assert out == [], _titles(out)


# --------------------------------------------------------------------------
# an uninstalled model is an environment problem, not a product defect
# --------------------------------------------------------------------------

def _tx_ev(unavailable: bool):
    ev = _ev(kinds={"mp3": 36}, disk_exts={".mp3": 36},
             expect={"pan_out_mp3": True, "pan_out_txt": True,
                     "pan_out_srt": True})
    ev.log["panopto_tx_unavailable"] = unavailable
    return ev


def test_a_missing_model_is_reported_once_as_an_observation():
    out = crosscheck._panopto_delivery(_tx_ev(True))
    assert [f.severity for f in out] == ["info"], _titles(out)
    assert "not installed" in out[0].title


def test_a_missing_model_never_files_transcripts_against_the_product():
    """Fifteen transcription rows would otherwise each report missing txt and
    srt at high severity for a machine setup problem."""
    out = crosscheck._panopto_delivery(_tx_ev(True))
    assert not any(f.severity == "high" for f in out), _titles(out)


def test_with_the_model_present_missing_transcripts_are_still_reported():
    out = crosscheck._panopto_delivery(_tx_ev(False))
    assert any("txt" in t for t in _titles(out)), _titles(out)
    assert any(f.severity == "high" for f in out)


def test_a_missing_model_does_not_mask_an_audio_failure():
    """Only txt/srt are excused; mp3/mp4 have nothing to do with the model."""
    ev = _ev(kinds={"mp3": 36}, disk_exts={},
             expect={"pan_out_mp3": True, "pan_out_txt": True})
    ev.log["panopto_tx_unavailable"] = True
    out = crosscheck._panopto_delivery(ev)
    assert any("mp3" in t and "no file on disk" in t for t in _titles(out)), \
        _titles(out)


# ── batch-level phases: the size gate, and where the fact lives ──────────
#
# Panopto downloads and transcribes EVERY course's recordings in one phase,
# after all discovery, and its size-gate lines name a recording TITLE rather
# than a course. So the fact cannot be split per course at all - it exists only
# in the row's whole log, which is what Evidence.batch_log carries.

SIZE_SKIP = ("[2026-07-28 21:57:08.621] [INFO] [panopto.runner] Panopto size gate: "
             "skipping 'Forelaesningsvideo (1): Forandringsledelse' "
             "(~197.0 MB est > 5.0 MB limit).")
BATCH_DONE = ("[2026-07-28 21:57:18.374] [INFO] [panopto.runner] Panopto batch done: "
              "found=36 downloaded=0 transcribed=0 skipped=0 failed=0 courses=1")


def _summarise(lines, tmp_path):
    from tests.audit.harness.oracles import log as logora
    p = tmp_path / "row.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return logora.summarize(logora.parse(str(p)))


def test_the_size_gate_line_is_parsed(tmp_path):
    s = _summarise([SIZE_SKIP], tmp_path)
    assert s["panopto_size_skipped"] == ["Forelaesningsvideo (1): Forandringsledelse"]
    assert s["unmatched_lines"] == 0


def test_the_batch_tally_is_parsed(tmp_path):
    s = _summarise([BATCH_DONE], tmp_path)
    assert s["panopto_batch"]["found"] == "36"
    assert s["panopto_batch"]["downloaded"] == "0"
    assert s["unmatched_lines"] == 0


def _capped(n_capped, *, external_tools=36):
    """A row whose max-file-size setting excluded *n_capped* recordings.

    Built on the file's own fixture rather than a second one, so a change to
    the Evidence shape cannot leave these three tests passing against a stale
    copy of it.
    """
    ev = _ev(external_tools=external_tools, discovered=0, kinds={})
    ev.batch_log = {"panopto_size_skipped": [f"rec {i}" for i in range(n_capped)]}
    return ev


def test_recordings_the_users_cap_excluded_leave_the_denominator():
    """The app honoured a setting it was given; that is not a discovery failure.

    Measured on m041 (5 MB cap, course 43660): all 36 recordings are 74-284 MB,
    the app logged a size-gate line for every one and closed with
    `found=36 downloaded=0`. Reading only the empty manifest, this check
    reported "Panopto was requested but nothing was discovered".
    """
    found = crosscheck._panopto_delivery(_capped(36))
    assert not [f for f in found if "nothing was discovered" in f.title]


def test_a_genuine_zero_delivery_is_still_reported():
    """The suppression must be narrow - no size gate, no excuse."""
    found = crosscheck._panopto_delivery(_capped(0))
    assert [f for f in found if "nothing was discovered" in f.title]


def test_a_partial_cap_still_reports_the_remainder():
    """30 of 36 capped leaves 6 that should have arrived."""
    found = [f for f in crosscheck._panopto_delivery(_capped(30))
             if "nothing was discovered" in f.title]
    assert found, "6 uncapped recordings still had to arrive"
    assert "6 recordings expected" in found[0].title
