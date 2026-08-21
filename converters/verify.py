"""Did the converter actually produce a document? - the check that guards a delete.

Every Office converter finishes by deleting the file it converted FROM. That is
the intended behaviour (the PDF replaces the legacy .doc/.xls/.ppt), and it is
also the one irreversible step in the whole pipeline: the source is the user's
own document, and unlike a Canvas file it may be the only copy.

Word and Excel were performing that delete on the strength of "the COM call did
not raise". Office does not always raise. ``SaveAs`` /
``ExportAsFixedFormat`` can return normally and leave nothing on disk - a
password-protected or repaired document, a locked-down AutomationSecurity
policy, or (for Excel) a broken/absent printer driver, which is what its PDF
export goes through. The result was an original deleted with no PDF to show for
it. PowerPoint tested ``exists()``, which is better but still passes a 0-byte
stub.

So the source may only be deleted once the output has been shown to be a real
PDF. ``%PDF`` is the format's magic number and costs one short read.

A magic number alone is not enough, and the 2026-08-21 audit measured why: a
conversion that dies PART-WAY does not leave a stub, it leaves a plausible file
of whatever Office had flushed - `Øvelse 9 - VL.pdf` at exactly 65,536 bytes,
one 64 KB buffer, with correct magic and far above any size floor. So the tail
is checked too: a PDF ends with ``%%EOF``.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# A PDF is "%PDF-x.y" + at least a trailer; anything under this is a stub, not a
# document. Deliberately generous - the point is to catch nothing/empty/truncated,
# not to validate PDF structure.
_MIN_PDF_BYTES = 512

# How far back to look for the %%EOF trailer. Generous: some producers append
# whitespace or an incremental-update trailer after it. Measured across 121 real
# PDFs from the 2026-08-21 audit, every one carried %%EOF inside the last 2 KB.
_PDF_TRAILER_WINDOW = 4096


def file_has_content(path: str | Path, min_bytes: int = 1,
                     what: str = "file") -> tuple[bool, str]:
    """``(ok, reason)`` - whether *path* exists and carries at least *min_bytes*.

    The generic form of the same guard: whenever a converter is about to delete
    the file it converted FROM, this is the question it has to answer first.
    Never raises - an unreadable output reports as not-real, which keeps the
    source, and keeping a file is always the recoverable outcome.
    """
    try:
        from shared.helpers import make_long_path
        p = Path(make_long_path(path))
        if not p.exists():
            return False, f"no {what} was written to disk"
        size = p.stat().st_size
        if size == 0:
            return False, f"the {what} written was empty (0 bytes)"
        if size < min_bytes:
            return False, f"the {what} written is implausibly small ({size} bytes)"
        return True, ""
    except OSError as e:
        return False, f"the {what} written could not be read back ({e})"


def pdf_looks_real(path: str | Path) -> tuple[bool, str]:
    """``(ok, reason)`` - whether *path* is a plausible, non-empty PDF.

    Never raises: an unreadable output is reported as not-real, which keeps the
    source file, and keeping a file is always the recoverable outcome.
    """
    try:
        from shared.helpers import make_long_path
        p = Path(make_long_path(path))
        if not p.exists():
            return False, "no PDF was written to disk"
        size = p.stat().st_size
        if size == 0:
            return False, "the PDF written was empty (0 bytes)"
        with open(p, "rb") as fh:
            head = fh.read(5)
        if not head.startswith(b"%PDF"):
            return False, f"the file written is not a PDF (starts with {head!r})"
        if size < _MIN_PDF_BYTES:
            return False, f"the PDF written is truncated ({size} bytes)"
        # A PDF ENDS with %%EOF. The size floor above only catches a stub, and
        # a conversion that dies part-way does not produce a stub - it produces
        # a plausible-looking file of whatever Office had flushed so far.
        #
        # Measured 2026-08-21, matrix row m048: Excel's PDF export died with
        # `Connection is invalid. (-609)` and left `Øvelse 9 - VL.pdf` at
        # EXACTLY 65,536 bytes - one 64 KB buffer. It has the %PDF magic and it
        # is far above the floor, so it passed this gate, was promoted out of
        # the Office container into the student's folder, and sat there
        # untracked beside the .xlsx that had NOT been deleted. It also occupies
        # the destination, so the retry diverts to `<stem> (1).pdf` - which is
        # where the duplicate PDFs seen in that run come from.
        #
        # This gate also guards the DELETE of the user's only copy, so a partial
        # file passing it is the dangerous direction. Requiring the trailer errs
        # the other way: a false negative keeps a file the user already has.
        # Verified against every PDF produced by that audit - 121 files, Canvas
        # downloads and Word/Excel/PowerPoint conversions alike - all of which
        # carry %%EOF inside the last 2 KB.
        with open(p, "rb") as fh:
            fh.seek(max(0, size - _PDF_TRAILER_WINDOW))
            tail = fh.read(_PDF_TRAILER_WINDOW)
        if b"%%EOF" not in tail:
            return False, ("the PDF written is incomplete - it has no %%EOF "
                           "trailer, so the converter stopped part-way")
        return True, ""
    except OSError as e:
        return False, f"the PDF written could not be read back ({e})"
