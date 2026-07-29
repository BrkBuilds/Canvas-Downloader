"""A file placed WITHOUT a fetch is still a write, and the checker must see it.

The engine now serves the second phase to want a Canvas file from the copy it
already has, so two new lines appear in the debug log and a real file lands on
disk with no ``File Saved:`` line to answer for it. A checker that does not
know them goes quiet in exactly the wrong direction: the delivery check asks
whether disk holds at least as many files as the log claimed, so an uncounted
write is slack that hides a genuinely missing file.

Both lines are taken verbatim from real runs on course 46396.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import crosscheck            # noqa: E402
from tests.audit.harness.oracles import log as logora  # noqa: E402


# Real lines, copied out of _audit_runs/.../debug_log.txt.
PLACED = ("[2026-07-28 23:33:02.101] Copying already-downloaded file (ID: 1784620): "
          r"Grupper til Klyngevejledning 1.pdf -> G:\x\Announcements\W1\Grupper til Klyngevejledning 1.pdf")
DEFERRED = ("[2026-07-28 23:29:05.536] Files-tab sweep skipping Canvas Content attachment: "
            "Grupper+til+Klyngevejledning+1.pdf (ID: 1784620) -> "
            "Announcement 2026-03-01 - Grupper og info - klyngevejledning 1 - "
            "Grupper til Klyngevejledning 1.pdf")


def _summary(lines, tmp_path):
    p = tmp_path / "debug_log.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return logora.summarize(logora.parse(str(p)))


def test_a_placed_file_is_parsed_and_counted(tmp_path):
    s = _summary([PLACED], tmp_path)
    assert s["files_placed"] == 1
    assert s["unmatched_lines"] == 0, "an unknown line silently lowers the miss rate too"


def test_both_verbs_parse(tmp_path):
    moved = PLACED.replace("Copying", "Moving")
    s = _summary([PLACED, moved], tmp_path)
    assert s["files_placed"] == 2


def test_a_deferred_sweep_is_parsed_and_counted(tmp_path):
    s = _summary([DEFERRED], tmp_path)
    assert s["catchall_deferred"] == 1
    assert s["unmatched_lines"] == 0


def test_the_two_catch_all_skips_stay_distinct(tmp_path):
    """The module skip and the Canvas Content deferral are different rules.

    They read almost the same and fail differently - collapsing them would
    make a regression in one look like normal traffic from the other.
    """
    module_skip = ("[2026-07-28 23:29:05.500] Catch-All skipping module file: "
                   "notes.pdf (ID: 1784795)")
    s = _summary([module_skip, DEFERRED], tmp_path)
    assert s["catchall_deferred"] == 1, "the module skip must not be counted here"
    assert s["unmatched_lines"] == 0


def test_delivery_check_counts_placed_files_as_writes(tmp_path):
    """Without this the check has slack for every placed file.

    Disk holds 3 files; the log announces 2 saved + 1 placed. Counting only
    the saved ones would let a third file go missing unnoticed.
    """
    def _ev(on_disk):
        return crosscheck.Evidence(
            folder=tmp_path, scenario="t", course="c",
            log={"files_saved": 2, "files_placed": 1, "secondary_saved": 0,
                 "links_created": 0},
            disk={"exists": True, "content_count": on_disk},
            ui={}, db={}, canvas={}, expect={})

    assert not [f for f in crosscheck._count_coherence(_ev(3))
                if "writes but" in f.title], "3 writes, 3 files - nothing to report"

    titles = [f.title for f in crosscheck._count_coherence(_ev(2))]
    assert any("3 writes but 2 content files" in t for t in titles), titles


# ── one Canvas file, one fetch: the check that would have caught it ──────
#
# The original duplicate was found by reading a log by hand - nothing in the
# suite noticed it, and nothing would notice it coming back. These pin the
# check that now does, including the one case that would make it useless if
# got wrong: a retry is not a second fetch.

def _req(fid, attempt=1, ts="[2026-07-28 18:48:19.252]"):
    return (f"{ts} Requesting URL: https://cbscanvas.instructure.com/files/"
            f"{fid}/download?download_frd=1&verifier=[REDACTED] (Attempt {attempt})")


def _fetch_counts(lines, tmp_path):
    return _summary(lines, tmp_path)["fetch_starts_by_file_id"]


def test_two_phases_fetching_one_file_is_counted(tmp_path):
    assert _fetch_counts([_req(1784620), _req(1784620)], tmp_path) == {"1784620": 2}


def test_a_retry_is_not_a_second_fetch(tmp_path):
    """The case that decides whether this check is usable at all.

    A rate limit, a 5xx or a dropped connection re-requests the SAME download.
    Counting those would make every flaky network look like the bug, the check
    would be muted, and the real defect would walk straight through it.
    """
    counts = _fetch_counts([_req(1784620, 1), _req(1784620, 2), _req(1784620, 3)], tmp_path)
    assert counts == {"1784620": 1}


def test_distinct_files_are_not_duplicates(tmp_path):
    counts = _fetch_counts([_req(1784620), _req(1807289)], tmp_path)
    assert counts == {"1784620": 1, "1807289": 1}


def test_non_file_requests_are_ignored(tmp_path):
    line = ("[2026-07-28 18:48:19.252] Requesting URL: "
            "https://cbscanvas.instructure.com/api/v1/courses/46396 (Attempt 1)")
    assert _fetch_counts([line], tmp_path) == {}


def test_the_check_fires_and_names_the_ids():
    ev = crosscheck.Evidence(
        folder=".", scenario="m025", course="46396",
        log={"fetch_starts_by_file_id": {"1784620": 2, "1807289": 2, "1784616": 1}})
    found = crosscheck._one_fetch_per_file(ev)
    assert len(found) == 1
    f = found[0]
    assert f.severity == "high"
    assert "2 Canvas file(s)" in f.title
    ids = f.evidence["file_id_fetch_counts"]
    assert set(ids) == {"1784620", "1807289"}, "only the duplicated ids belong in the evidence"


def test_the_check_is_silent_when_every_file_was_fetched_once():
    ev = crosscheck.Evidence(
        folder=".", scenario="t", course="c",
        log={"fetch_starts_by_file_id": {"1784620": 1, "1807289": 1}})
    assert crosscheck._one_fetch_per_file(ev) == []


def test_the_check_is_silent_on_a_log_it_could_not_parse():
    """A missing key must read as 'nothing observed', never as 'all clear'
    with a fabricated pass - and never as a crash inside the suite."""
    ev = crosscheck.Evidence(folder=".", scenario="t", course="c", log={})
    assert crosscheck._one_fetch_per_file(ev) == []
