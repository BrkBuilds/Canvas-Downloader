"""The Panopto **Shortcut** output: one link file per recording.

A shortcut is a first-class output kind (``"url"``) alongside mp4/mp3/txt/srt.
It costs no bandwidth, no disk and no time, and it answers the one thing a
transcript cannot: *take me back to the lecture*, with the slides, the screen
capture and Panopto's own search still attached.

Three things live here, all of them the kind that break silently when they are
written twice:

**1. A kind is not always its own extension.** Every other kind names its file
(``<stem>.mp3``), and both the runner (which writes) and ``panopto.sync_plan``
(which looks for what was written) build paths as ``stem + "." + kind``. The
shortcut kind does not: the file is ``.url`` on Windows and ``.webloc`` on
macOS. If the writer and the analyzer ever disagree about that, nothing crashes
- every recording simply reads as missing on every sync, for ever. So both go
through :func:`kind_extension`, and both SEARCH through
:func:`kind_extensions`, which lists the other platform's suffix too: a folder
first synced on Windows and later opened on a Mac already holds ``.url`` files,
and writing a second ``.webloc`` beside each one is not a fix for anything.

**2. Which URL the shortcut points at.** Best is Panopto's own viewer, which is
a deep link to the recording. The host is captured during discovery
(``PanoptoVideo.panopto_host``) at zero cost, because discovery already performs
the LTI launches that reveal it - which is what lets a shortcut-only run skip
the per-course authentication entirely.

**3. The Canvas fallback is only valid for a module-linked recording.** When no
Panopto host is known at all, a link to the Canvas module item still opens the
lecture (Canvas runs the LTI launch itself). But ``PanoptoVideo.module_item_id``
does NOT identify the recording for every source: a ``source="folder"``
recording carries the item id of whichever module item's launch happened to
enumerate the folder, so using it there would point every recording in the
course at the SAME lecture - thirty shortcuts, one destination, no error
anywhere. The fallback is therefore restricted to ``source == "module"``.
"""

from __future__ import annotations

from pathlib import Path

from shared.helpers import path_exists
from shared.shortcuts import (
    SHORTCUT_SUFFIXES, SOURCE_PANOPTO, is_produced_shortcut,
    shortcut_extension, write_shortcut,
)

#: The output kind this module implements.
SHORTCUT_KIND = "url"

#: Kinds that are downloaded/produced media, i.e. every kind whose extension IS
#: its name. Kept next to SHORTCUT_KIND so "which kinds cost bandwidth" has one
#: answer - the runner's auth bootstrap and the size estimator both ask it.
MEDIA_KINDS = ("mp4", "mp3", "txt", "srt")


def kind_extensions(kind: str) -> tuple[str, ...]:
    """Every file suffix *kind* may be stored under, this platform's FIRST.

    Used to FIND an artifact. For the shortcut kind the second entry is the
    other platform's suffix, so a folder written on Windows is adopted on macOS
    (and the reverse) instead of being re-produced under a second name.
    """
    if kind == SHORTCUT_KIND:
        native = shortcut_extension()
        return (native, *sorted(s for s in SHORTCUT_SUFFIXES if s != native))
    return ("." + kind,)


def kind_extension(kind: str) -> str:
    """The file suffix to WRITE for *kind* on this platform (leading dot)."""
    return kind_extensions(kind)[0]


#: Appended to the stem when the plain name is already taken by a shortcut this
#: app did not produce. Reads as a label rather than a collision artifact,
#: because that is exactly what it is - two links to the same lecture by two
#: different routes.
_DISAMBIGUATOR = " (Panopto)"

#: How many disambiguated names to try before giving up. Reaching even the
#: second is close to impossible; the bound exists so a pathological folder
#: cannot spin.
_MAX_DISAMBIGUATIONS = 8


def _shortcut_path_candidates(base: Path):
    """Every path a recording's link file may legitimately occupy, best first."""
    exts = kind_extensions(SHORTCUT_KIND)
    yield from (Path(str(base) + e) for e in exts)
    for n in range(1, _MAX_DISAMBIGUATIONS + 1):
        tag = _DISAMBIGUATOR if n == 1 else f"{_DISAMBIGUATOR[:-1]} {n})"
        yield from (Path(str(base) + tag + e) for e in exts)


def resolve_shortcut_path(base: Path) -> Path | None:
    """Where this recording's link file goes, given what is already on disk.

    **The plain ``<stem>.url`` is frequently NOT free, and missing that shipped
    the feature as a silent no-op.** ``core.canvas_logic._create_link`` writes a
    shortcut for every Canvas ExternalTool module item, and a Panopto lecture IS
    an ExternalTool item named after the lecture - so in the *match* layout the
    Panopto pass computes a destination that Canvas has already filled with a
    link of its own. Measured on course 43660: 36 recordings discovered, 34
    identically-named ``.url`` files already on disk, **0 shortcuts written, 0
    manifest rows**, and a completion screen that said nothing at all.

    Overwriting that file is not the fix. It belongs to the Canvas file sync,
    which tracks its content signature and would rewrite it on the next run -
    two subsystems taking turns clobbering one path, for ever.

    So: adopt a link we produced ourselves wherever it sits, otherwise take the
    first free name, stepping over anything that belongs to somebody else. The
    two links coexist and point at different things - Canvas' one goes through
    the LTI launch, ours goes straight to the viewer.

    Returns None only if every candidate name is taken by a foreign file, which
    the caller must report rather than resolve by overwriting one of them.
    """
    base = Path(base)
    free: Path | None = None
    for cand in _shortcut_path_candidates(base):
        if path_exists(cand):
            if is_produced_shortcut(cand):
                return cand          # ours already - adopt, never rewrite
            continue                 # somebody else's - step over it
        if free is None and cand.suffix.lower() == shortcut_extension().lower():
            # First free slot in THIS platform's format. Recorded rather than
            # returned immediately: a link of ours may still be sitting further
            # down the list (the Canvas link that pushed us to a disambiguated
            # name on run 1 may since have been deleted).
            free = cand
    return free


def kind_from_path(path) -> str:
    """The output kind a produced file represents.

    The inverse of :func:`kind_extension`, and the reason the manifest recorder
    cannot simply strip the dot off a suffix: a ``.webloc`` is kind ``"url"``,
    and recording it as ``"webloc"`` would leave the analyzer looking for a kind
    that is never wanted while the real one reads as missing on every sync.
    """
    suffix = Path(path).suffix.lower()
    if suffix in SHORTCUT_SUFFIXES:
        return SHORTCUT_KIND
    return suffix.lstrip(".") or "file"


def viewer_url(panopto_host: str, video_id: str) -> str | None:
    """Panopto's own viewer page for *video_id*, or None if either part is missing.

    Same URL shape ``panopto.stream`` sends as a Referer on every download, so
    the two can never describe different pages.
    """
    host = (panopto_host or "").strip().rstrip("/")
    vid = (video_id or "").strip()
    if not host or not vid or "://" not in host:
        return None
    return f"{host}/Panopto/Pages/Viewer.aspx?id={vid}"


def canvas_module_item_url(canvas_base: str, course_id, module_item_id) -> str | None:
    """The Canvas module-item page that launches this recording, or None.

    Opening it in a browser makes Canvas run the LTI launch, which lands on the
    recording - so this works even at an institution whose direct Panopto links
    require a session the browser does not have yet.
    """
    base = (canvas_base or "").strip().rstrip("/")
    try:
        cid = int(course_id or 0)
        iid = int(module_item_id or 0)
    except (TypeError, ValueError):
        return None
    if not base or cid <= 0 or iid <= 0:
        return None
    return f"{base}/courses/{cid}/modules/items/{iid}"


def resolve_recording_url(video, *, panopto_base: str = "",
                          canvas_base: str = "", course_id=None) -> str | None:
    """The best browser-openable URL for *video*, or None if there is none.

    Order, best first:

    1. the recording's own Panopto host, captured during discovery;
    2. the course's Panopto host, resolved by the runner's auth bootstrap (only
       present when a media download made that bootstrap worth running);
    3. the Canvas module item - module-sourced recordings only, see the module
       docstring.

    Returning None is a real outcome and must be reported, not swallowed: it
    means we know the recording exists but have no address for it.
    """
    vid = getattr(video, "video_id", "") or ""

    url = viewer_url(getattr(video, "panopto_host", "") or "", vid)
    if url:
        return url

    url = viewer_url(panopto_base or "", vid)
    if url:
        return url

    if (getattr(video, "source", "") or "") == "module":
        return canvas_module_item_url(
            canvas_base, course_id, getattr(video, "module_item_id", 0))
    return None


def write_recording_shortcut(path, url: str) -> None:
    """Write a recording's shortcut, stamped as an app-produced artifact.

    The stamp is what keeps ``converters.url``'s link compiler from compiling
    this file into ``Compiled_External_Links.txt`` and deleting it - which would
    otherwise delete an output the user explicitly selected, on every run, and
    make the next sync restore it so the pair could do it all again.
    """
    write_shortcut(path, url, source=SOURCE_PANOPTO)
