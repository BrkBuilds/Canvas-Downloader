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
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# A PDF is "%PDF-x.y" + at least a trailer; anything under this is a stub, not a
# document. Deliberately generous - the point is to catch nothing/empty/truncated,
# not to validate PDF structure.
_MIN_PDF_BYTES = 512


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
        return True, ""
    except OSError as e:
        return False, f"the PDF written could not be read back ({e})"
