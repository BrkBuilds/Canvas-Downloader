"""A lane runs dozens of rows through ONE app. Two things leak between them.

**The folder.** ``core/canvas_logic.py`` skips a file that already exists at
the matching size ("Skipping existing file"). The matrix runs 73 rows over five
courses, so without a prune the second row against a course downloads nothing,
passes every check and proves nothing - the failure mode this whole harness
exists to avoid, arriving through the harness itself.

**The batch log.** ``downloads/debug_log.txt`` is cleared once per Streamlit
SESSION (app.py, ``_debug_log_cleared``) and appended to for ever after. Oracle
O2 read it whole, so row 40 would be judged against the concatenated output of
rows 1-40, with every earlier row's errors attributed to it.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import parallel as P        # noqa: E402


class _RP:
    """The four attributes the isolation helpers touch."""
    def __init__(self, root: Path):
        self.root = root
        self.downloads = root / "downloads"
        self.evidence = root / "evidence"
        self.logs = self.evidence / "logs"
        for d in (self.downloads, self.evidence, self.logs):
            d.mkdir(parents=True, exist_ok=True)

    def batch_debug_log(self) -> Path:
        return self.downloads / "debug_log.txt"


def _course_folder(rp: _RP, name: str, course_id: int, files=("a.pdf",)) -> Path:
    d = rp.downloads / name
    d.mkdir(parents=True, exist_ok=True)
    for f in files:
        (d / f).write_text("payload", encoding="utf-8")
    con = sqlite3.connect(d / ".canvas_sync.db")
    con.execute("CREATE TABLE sync_metadata (key TEXT, value TEXT)")
    con.execute("INSERT INTO sync_metadata VALUES ('course_id', ?)", (str(course_id),))
    con.commit()
    con.close()
    return d


@pytest.fixture
def rp(tmp_path):
    return _RP(tmp_path)


# --------------------------------------------------------------------------
# the folder
# --------------------------------------------------------------------------

def test_a_leftover_folder_for_this_course_is_removed(rp):
    d = _course_folder(rp, "Org 1060", 43660)
    assert P._prune_course_folder(rp, 43660) == str(d)
    assert not d.exists()


def test_another_course_is_left_alone(rp):
    keep = _course_folder(rp, "Prog 1064", 45899)
    _course_folder(rp, "Org 1060", 43660)
    P._prune_course_folder(rp, 43660)
    assert keep.exists(), "pruning one course took another course's folder"


def test_pruning_when_there_is_nothing_to_prune_is_quiet(rp):
    assert P._prune_course_folder(rp, 43660) == ""


def test_a_read_only_file_does_not_block_the_prune(rp):
    """Audit fixtures deliberately create read-only files."""
    d = _course_folder(rp, "Org 1060", 43660)
    p = d / "locked.pdf"
    p.write_text("x", encoding="utf-8")
    p.chmod(0o444)
    P._prune_course_folder(rp, 43660)
    assert not d.exists()


def test_harvest_keeps_the_small_artefacts_and_drops_the_payload(rp):
    d = _course_folder(rp, "Org 1060", 43660, files=("big.mp4", "a.pdf"))
    (d / "debug_log.txt").write_text("per-course log", encoding="utf-8")
    (d / "download_errors.txt").write_text("boom", encoding="utf-8")

    res = P._harvest_and_prune(rp, "m001", d)

    assert res["removed"] is True
    assert not d.exists(), "the payload survived, so the disk budget is fiction"
    out = Path(res["evidence"])
    assert sorted(p.name for p in out.iterdir()) == [
        ".canvas_sync.db", "debug_log.txt", "download_errors.txt"]
    assert (out / "debug_log.txt").read_text(encoding="utf-8") == "per-course log"


def test_harvest_survives_a_folder_with_none_of_the_artefacts(rp):
    d = rp.downloads / "bare"
    d.mkdir()
    (d / "x.pdf").write_text("x", encoding="utf-8")
    res = P._harvest_and_prune(rp, "m002", d)
    assert res["kept"] == [] and res["removed"] is True


def test_each_row_harvests_into_its_own_directory(rp):
    for i in (1, 2):
        d = _course_folder(rp, f"C{i}", 100 + i)
        P._harvest_and_prune(rp, f"m00{i}", d)
    rows = sorted(p.name for p in (Path(rp.evidence) / "rows").iterdir())
    assert rows == ["m001", "m002"]


# --------------------------------------------------------------------------
# the log
# --------------------------------------------------------------------------

HDR = "--- Debug Log Started: 2026-07-28 15:16:25 ---\n"
HDR2 = "--- Debug Log Started: 2026-07-28 15:20:00 ---\n"


def test_a_row_sees_only_what_was_logged_during_it(rp):
    """The append case: same file, no clear in between."""
    log = rp.batch_debug_log()
    log.write_text(HDR + "row one line\n", encoding="utf-8")
    mark = P._log_size(log)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("row two line\n")

    text = Path(P._log_slice(rp, "m002", mark)).read_text(encoding="utf-8")
    assert text == "row two line\n"
    assert "row one" not in text, \
        "an earlier row's output would be attributed to this one"


def test_a_log_the_app_cleared_between_rows_is_read_whole(rp):
    """THE regression, measured on the smoke run.

    Every row opens a new browser session and the app clears the batch log per
    session, so the mark taken before the flow indexes a file that no longer
    exists. Here the recreated log is LONGER than the old mark, so nothing
    looks wrong - and slicing from the stale offset threw away the whole first
    course of a two-course row, which the log-vs-disk check then reported as
    missing files."""
    log = rp.batch_debug_log()
    log.write_text("x" * 400 + "\n", encoding="utf-8")          # row 1's log
    mark = P._log_size(log)
    log.write_text(HDR2 + "y" * 900 + "\n", encoding="utf-8")   # cleared, then row 2

    text = Path(P._log_slice(rp, "m003", mark)).read_text(encoding="utf-8")
    assert text.startswith(HDR2)
    assert "y" * 900 in text, "the start of this row's log was discarded"
    assert "x" not in text


def test_a_clear_that_lands_inside_the_slice_cuts_to_the_last_session(rp):
    log = rp.batch_debug_log()
    log.write_text(HDR + "row one\n", encoding="utf-8")
    mark = P._log_size(log)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("stray tail\n" + HDR2 + "row two\n")

    text = Path(P._log_slice(rp, "m004", mark)).read_text(encoding="utf-8")
    assert text == HDR2 + "row two\n"


def test_the_first_row_of_a_lane_sees_the_whole_log(rp):
    rp.batch_debug_log().write_text(HDR + "from the start\n", encoding="utf-8")
    text = Path(P._log_slice(rp, "m000", (0, b""))).read_text(encoding="utf-8")
    assert text == HDR + "from the start\n"


def test_a_rotated_log_falls_back_to_the_whole_file(rp):
    """log_debug rotates at 5 MB, so the file SHRINKS. A stale offset past the
    end would slice to nothing, and every O2 check would then pass by default."""
    log = rp.batch_debug_log()
    log.write_text(HDR + "x" * 5000, encoding="utf-8")
    mark = P._log_size(log)
    log.write_text(HDR + "after rotation\n", encoding="utf-8")   # much smaller

    text = Path(P._log_slice(rp, "m005", mark)).read_text(encoding="utf-8")
    assert text == HDR + "after rotation\n", "the slice silently read an empty log"


def test_a_missing_log_is_an_empty_slice_not_a_crash(rp):
    assert Path(P._log_slice(rp, "m006", (0, b""))).read_text(encoding="utf-8") == ""
    assert P._log_size(rp.batch_debug_log()) == (0, b"")


def test_the_slice_is_kept_as_evidence_under_the_row_id(rp):
    rp.batch_debug_log().write_text("hello\n", encoding="utf-8")
    p = Path(P._log_slice(rp, "m007", (0, b"")))
    assert p.name == "m007.txt" and p.parent == Path(rp.logs)


def test_non_utf8_bytes_in_the_log_do_not_break_the_slice(rp):
    """Canvas filenames arrive in the log; the app writes utf-8 but a truncated
    multi-byte sequence at a rotation boundary must not raise here."""
    log = rp.batch_debug_log()
    log.write_bytes(HDR.encode() + b"start\n")
    mark = P._log_size(log)
    with log.open("ab") as fh:
        fh.write(b"\xc3 broken\n")
    assert Path(P._log_slice(rp, "m008", mark)).read_bytes() == b"\xc3 broken\n"


# --------------------------------------------------------------------------
# and one course's share of a row's log
# --------------------------------------------------------------------------

def _banner(cid, name="Course"):
    return (f"\n{'='*50}\n--- Download: {name} (ID: {cid}) Mode: modules ---\n"
            f"{'='*50}\n")


TWO_COURSE_LOG = (
    HDR
    + "[2026-07-28 15:16:54.859] Page-stub fallback: resolved 11 module Page item(s)\n"   # shared scan
    + _banner(43658, "How to Uni")
    + "[2026-07-28 15:16:54.859] File Saved: a.png (10 bytes)\n"
    + "[2026-07-28 15:16:54.859] Saving discussion: Refleksionsopgave -> x/Discussions/R.md\n"
    + "[2026-07-28 15:16:54.859] === Course Finished: How to Uni | Downloaded: 2 items | Errors: 0 ===\n"
    + _banner(44428, "Introduction to Information Systems")
    + "[2026-07-28 15:16:54.859] File Saved: b.pdf (20 bytes)\n"
    + "[2026-07-28 15:16:54.859] File Saved: c.pdf (30 bytes)\n"
    + "[2026-07-28 15:16:54.859] === Course Finished: Introduction | Downloaded: 2 items | Errors: 0 ===\n"
)


def _split(rp, cid, text=TWO_COURSE_LOG):
    src = Path(rp.logs) / "row.txt"
    src.write_text(text, encoding="utf-8")
    return Path(P._log_for_course(str(src), cid, Path(rp.logs) / f"c{cid}.txt")
                ).read_text(encoding="utf-8")


def test_a_course_gets_only_its_own_writes(rp):
    """The regression: one log across N courses, judged against ONE folder's
    disk, reported 39 logged writes against 18 files - twice, once per course."""
    first = _split(rp, 43658)
    assert "a.png" in first and "Refleksionsopgave" in first
    assert "b.pdf" not in first and "c.pdf" not in first


def test_the_last_course_runs_to_the_end_of_the_log(rp):
    last = _split(rp, 44428)
    assert "b.pdf" in last and "c.pdf" in last
    assert "a.png" not in last


def test_the_shared_scan_preamble_belongs_to_no_course(rp):
    """It carries no delivery events, and attributing it to the first course
    would make that course's log differ by where it happened to sit."""
    assert "Page-stub fallback" not in _split(rp, 43658)


def test_a_single_course_row_is_unaffected(rp):
    text = HDR + _banner(44428) + "[2026-07-28 15:16:54.859] File Saved: b.pdf (20 bytes)\n"
    assert "b.pdf" in _split(rp, 44428, text)


def test_an_unknown_course_falls_back_to_the_whole_row(rp):
    """A log shape change must degrade to noisy, never to an empty file - an
    empty log makes every O2 check pass by default."""
    assert _split(rp, 999999) == TWO_COURSE_LOG


def test_a_log_with_no_banners_at_all_falls_back_whole(rp):
    text = HDR + "[2026-07-28 15:16:54.859] File Saved: b.pdf (20 bytes)\n"
    assert _split(rp, 44428, text) == text


def test_a_url_shortcut_counts_as_a_write():
    """"Creating Link:" is a file the app wrote, announced with another verb.
    Uncounted, every course with an ExternalUrl item sat one file above its own
    claim - slack that would hide a genuinely missing file."""
    from tests.audit.harness.oracles import log as olog
    import tempfile
    text = (HDR + "[2026-07-28 15:16:54.859] Creating Link: Course description "
            "(https://kursuskatalog.cbs.dk/x.aspx) -> C:/x/Course/desc.url\n")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8",
                                     delete=False) as fh:
        fh.write(text)
        p = fh.name
    s = olog.parse_and_summarize(p)
    assert s["links_created"] == 1


def test_a_bare_integer_mark_widens_rather_than_narrows(rp):
    """An int carries no evidence that the file is still the same one, and
    trusting it is precisely the bug: the smoke run's stale offset pointed into
    a recreated log and threw away a course. With no such evidence the slice
    must widen - over-reporting shows up as a finding somebody reads, while
    silently dropping a row's log makes every O2 check pass by default."""
    log = rp.batch_debug_log()
    log.write_text(HDR + "one\n", encoding="utf-8")
    n = log.stat().st_size
    with log.open("a", encoding="utf-8") as fh:
        fh.write("two\n")
    text = Path(P._log_slice(rp, "m009", n)).read_text(encoding="utf-8")
    assert text == HDR + "one\ntwo\n"
