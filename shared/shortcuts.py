"""Internet-shortcut files (``.url`` / ``.webloc``) - written and read in ONE place.

Three parts of the app deal with the same two file formats:

* ``core.canvas_logic._create_link`` writes a shortcut for every Canvas
  ExternalUrl / ExternalTool module item,
* ``panopto.runner`` writes one for a recording when the user selects the
  **Shortcut** output,
* ``converters.url`` reads every shortcut in a course folder, compiles the links
  into ``Compiled_External_Links.txt`` and then **deletes** the file.

That last one is why this module exists rather than three private helpers.
A shortcut the user explicitly asked for as an *output* must survive the
compiler, while an ordinary Canvas link is exactly what the compiler is for -
and the only thing that can tell them apart is the file itself. So a produced
artifact carries a **source marker**, and the compiler skips anything that has
one.

Why a marker in the file and not a lookup in the folder's manifest: the marker
travels with the file. It works in download mode and sync mode alike, it cannot
drift from a manifest row, and it still answers correctly for a folder whose
manifest write failed - a documented, non-hypothetical state in this app (see
``panopto.settings.infer_contract_from_manifest``).

Marker format, chosen so the file stays a perfectly ordinary shortcut:

* ``.url`` is INI. Windows' shell reads the ``[InternetShortcut]`` section and
  ignores unknown ones (real shortcuts written by browsers carry a
  ``[{000214A0-0000-0000-C000-000000000046}]`` section), so the marker gets its
  own ``[CanvasDownloader]`` section rather than an invented key inside the
  section the shell parses.
* ``.webloc`` is a plist dict. Finder reads ``URL``; any sibling key is ignored.

The reader is deliberately hand-rolled for INI: ``configparser`` applies ``%``
interpolation, and a URL with an escaped character (``%20``, ``%3D`` - Panopto
and Canvas emit both) raises inside it.
"""

from __future__ import annotations

import logging
import os
import platform
import plistlib
from pathlib import Path

from shared.helpers import make_long_path

logger = logging.getLogger(__name__)

#: Every shortcut suffix the app can encounter, on any platform. A folder synced
#: on Windows and then opened on macOS holds ``.url`` files, so readers must
#: accept both regardless of the host - only the WRITER is platform-specific.
SHORTCUT_SUFFIXES = frozenset({".url", ".webloc"})

#: INI section + key holding the marker in a ``.url`` file.
_INI_SECTION = "CanvasDownloader"
_INI_KEY = "Source"
#: Sibling plist key holding the marker in a ``.webloc`` file.
_PLIST_KEY = "CanvasDownloaderSource"

#: Source value written by the Panopto shortcut output.
SOURCE_PANOPTO = "Panopto"


def shortcut_extension(system: str | None = None) -> str:
    """The shortcut extension this platform can open by double-click.

    macOS uses ``.webloc`` (Finder); everything else uses ``.url`` (the Windows
    shell, and the convention Linux desktops inherited). *system* exists so a
    test can ask for the other platform's answer without patching the process.
    """
    return ".webloc" if (system or platform.system()) == "Darwin" else ".url"


def is_shortcut_path(path) -> bool:
    """True if *path* names a shortcut file, on any platform."""
    return Path(path).suffix.lower() in SHORTCUT_SUFFIXES


def write_shortcut(path, url: str, *, source: str = "") -> None:
    """Write an internet shortcut at *path* pointing at *url*.

    The format follows *path*'s own suffix, not the host platform, so a caller
    that has resolved a destination from a manifest recorded on another machine
    writes the file that destination claims to be.

    *source* stamps the file as an app-produced artifact (see the module
    docstring); leave it empty for an ordinary Canvas link, which the URL
    compiler is meant to consume.

    Written to a sibling temp file and moved into place, so an interrupted write
    can never leave a half-written shortcut where the manifest records a good
    one. Raises ``OSError`` on failure - callers decide how to report it.
    """
    path = Path(path)
    url = (url or "").replace("\r", "").replace("\n", "")
    if not url:
        raise ValueError("refusing to write a shortcut with no URL")

    if path.suffix.lower() == ".webloc":
        payload = {"URL": url}
        if source:
            payload[_PLIST_KEY] = source
        data = plistlib.dumps(payload, fmt=plistlib.FMT_XML)
    else:
        body = f"[InternetShortcut]\nURL={url}\n"
        if source:
            body += f"\n[{_INI_SECTION}]\n{_INI_KEY}={source}\n"
        data = body.encode("utf-8")

    tmp = path.with_name(path.name + ".tmp")
    tmp_long = make_long_path(tmp)
    try:
        with open(tmp_long, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_long, make_long_path(path))
    except OSError:
        try:
            os.unlink(tmp_long)
        except OSError:
            pass
        raise


def read_shortcut(path) -> tuple[str | None, str]:
    """Return ``(url, source)`` for a shortcut file.

    ``url`` is None when the file cannot be read or holds no link; ``source`` is
    ``""`` for an ordinary shortcut. Never raises - a malformed file in a course
    folder must not abort the phase reading it.
    """
    path = Path(path)
    try:
        if path.suffix.lower() == ".webloc":
            with open(make_long_path(path), "rb") as f:
                data = plistlib.load(f)
            if not isinstance(data, dict):
                return None, ""
            url = data.get("URL")
            source = data.get(_PLIST_KEY) or ""
            return (str(url) if url else None,
                    str(source) if isinstance(source, str) else "")

        # INI. Section tracking matters: the marker is only the marker when it
        # sits in OUR section, so a Canvas link that happens to contain the word
        # cannot mark itself protected.
        with open(make_long_path(path), "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
        url = None
        source = ""
        section = ""
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().lower()
                continue
            if url is None and line.lower().startswith("url="):
                url = line[4:].strip()
            elif section == _INI_SECTION.lower() and line.lower().startswith(
                    _INI_KEY.lower() + "="):
                source = line[len(_INI_KEY) + 1:].strip()
        return (url or None), source
    except Exception as e:  # noqa: BLE001 - a bad file is data, not a bug
        logger.warning("Could not read shortcut %s: %s", path.name, e)
        return None, ""


def read_shortcut_url(path) -> str | None:
    """The link a shortcut points at, or None. See :func:`read_shortcut`."""
    return read_shortcut(path)[0]


def is_produced_shortcut(path) -> bool:
    """True if this shortcut is an app-produced ARTIFACT, not a Canvas link.

    The URL compiler consumes and deletes the shortcuts it compiles; an artifact
    the user selected as an output must not be one of them.
    """
    return bool(read_shortcut(path)[1])
