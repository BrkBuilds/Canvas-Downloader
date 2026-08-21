"""A conversion that dies PART-WAY does not leave a stub - it leaves a plausible file.

Measured by the live macOS audit, 2026-08-21, matrix row m048. Excel's PDF
export died mid-write with ``Connection is invalid. (-609)`` and left::

    Øvelse 9 - VL.pdf     65,536 bytes     (exactly one 64 KB buffer)

Correct ``%PDF`` magic, far above the 512-byte floor - so it passed
``pdf_looks_real``, was promoted out of the Office container into the student's
folder, and sat there untracked beside the ``.xlsx`` that had NOT been deleted.
Canvas has no file of that name in the course, so it can only have come from the
failed conversion.

Two costs, and the second is the one that matters:

* it occupies the destination, so the retry cannot overwrite it and diverts to
  ``<stem> (1).pdf`` - which is where the duplicate PDFs in that run came from;
* ``pdf_looks_real`` is also the gate in front of **deleting the user's only
  copy** of a legacy ``.doc``/``.xls``/``.ppt``. A partial file passing it is the
  dangerous direction, and only the -609 happening to be reported as a failure
  kept the source this time.

The floor cannot fix this: the partial was 128x the floor. What separates a
complete PDF from an interrupted one is the **trailer** - a PDF ends with
``%%EOF``.

The check errs the recoverable way by construction: a false negative keeps a
file the user already has, a false positive deletes it. Verified against every
PDF that audit produced - 121 files, Canvas downloads and Word / Excel /
PowerPoint conversions alike - all of which carry ``%%EOF`` inside the last 2 KB.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from converters.verify import (            # noqa: E402
    _MIN_PDF_BYTES,
    _PDF_TRAILER_WINDOW,
    pdf_looks_real,
)

HEAD = b"%PDF-1.4\n"
TRAILER = b"\ntrailer\n<</Size 4>>\nstartxref\n1234\n%%EOF\n"


def _write(tmp_path: Path, name: str, body: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(body)
    return p


# ---------------------------------------------------------------------------
# the defect, in the shape it actually shipped
# ---------------------------------------------------------------------------

def test_the_measured_64kb_partial_is_rejected(tmp_path):
    """THE regression: 65,536 bytes, correct magic, no trailer."""
    p = _write(tmp_path, "Øvelse 9 - VL.pdf", HEAD + b"x" * (65536 - len(HEAD)))
    assert p.stat().st_size == 65536
    ok, why = pdf_looks_real(p)
    assert not ok, ("a partial PDF passed the gate that guards deleting the "
                    "user's only copy")
    assert "%%EOF" in why or "incomplete" in why


@pytest.mark.parametrize("size", [_MIN_PDF_BYTES + 1, 4096, 65536, 500_000])
def test_no_size_makes_a_trailerless_pdf_acceptable(tmp_path, size):
    """The floor cannot express this - the measured partial was 128x the floor."""
    p = _write(tmp_path, f"p{size}.pdf", HEAD + b"x" * (size - len(HEAD)))
    ok, _ = pdf_looks_real(p)
    assert not ok


# ---------------------------------------------------------------------------
# the quiet direction - a check that only ever fires is not a check
# ---------------------------------------------------------------------------

def test_a_complete_pdf_still_passes(tmp_path):
    p = _write(tmp_path, "good.pdf", HEAD + b"x" * 2000 + TRAILER)
    assert pdf_looks_real(p) == (True, "")


def test_trailing_bytes_after_the_trailer_are_tolerated(tmp_path):
    """Producers append whitespace, and incremental updates append a second
    trailer. Neither is a truncated file."""
    p = _write(tmp_path, "ws.pdf", HEAD + b"x" * 2000 + TRAILER + b"\n\r\n   \n")
    assert pdf_looks_real(p)[0]


def test_a_large_pdf_is_not_rejected_for_having_its_trailer_at_the_end(tmp_path):
    """The window is anchored to the END of the file, not the start.

    Reading from the front would reject every PDF bigger than the window - i.e.
    almost all of them - and that failure keeps sources instead of deleting
    them, so it would have been invisible except as conversions that never
    replace anything.
    """
    p = _write(tmp_path, "big.pdf",
               HEAD + b"x" * (_PDF_TRAILER_WINDOW * 4) + TRAILER)
    assert pdf_looks_real(p)[0]


# ---------------------------------------------------------------------------
# the pre-existing rungs must keep working
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("why,body", [
    ("empty", b""),
    ("not a pdf", b"PK\x03\x04 this is a zip" + b"x" * 1000 + TRAILER),
    ("stub below the floor", HEAD + b"x" * 10 + TRAILER),
])
def test_the_earlier_rungs_are_unchanged(tmp_path, why, body):
    p = _write(tmp_path, "bad.pdf", body)
    assert not pdf_looks_real(p)[0], why


def test_a_missing_file_is_not_real_and_does_not_raise(tmp_path):
    ok, why = pdf_looks_real(tmp_path / "nope.pdf")
    assert not ok and "no PDF" in why


def test_a_directory_in_the_way_is_reported_not_raised(tmp_path):
    d = tmp_path / "d.pdf"
    d.mkdir()
    ok, _ = pdf_looks_real(d)
    assert not ok, "never raises - an unreadable output keeps the source"
