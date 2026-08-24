"""
UI Helper utilities for Canvas LMS Batch File Downloader.
Shared helpers used by both download and sync modes.
"""

import functools
import html
import logging
import os
import re
import json
import shutil
import sys
import tempfile
import time
import platform
import subprocess
from contextlib import contextmanager
from pathlib import Path
import threading
import uuid

import urllib.parse
import base64
import unicodedata

from core.sync_manager import format_file_size  # re-exported for ui.sync_review / ui.sync_confirmation  # noqa: F401

_sync_pairs_lock = threading.RLock()
_err_log_lock = threading.Lock()

logger = logging.getLogger(__name__)

# Repo root = parent of the shared/ package dir. Assets and the dev-mode config
# dir live at the project root, so resolve them relative to it regardless of
# this module's package location (it moved from root into shared/).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def resolve_path(path):
    """Resolve path for frozen (PyInstaller) vs normal execution."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, path)
    return os.path.join(_REPO_ROOT, path)

@functools.lru_cache(maxsize=128)
def _get_base64_image_cached(image_path: str) -> str:
    """Cached disk read - only called on success; exceptions propagate uncached."""
    with open(resolve_path(image_path), "rb") as f:
        return base64.b64encode(f.read()).decode()


def get_base64_image(image_path) -> str:
    """Reads a local file and returns its Base64 string representation.

    Successes are cached (assets are static at runtime). Failures are NOT
    cached so that a missing asset during startup doesn't permanently break
    subsequent renders after the asset becomes available (M-20).
    """
    try:
        return _get_base64_image_cached(str(image_path))
    except Exception as e:
        logger.error(f"Failed to encode image {image_path}: {e}")
        return ""




def make_long_path(p: str | Path) -> str:
    """Prepend Windows long path prefix to absolute paths to prevent WinError 206.

    The ``\\\\?\\`` prefix turns OFF Win32 path parsing, which is exactly what
    lifts MAX_PATH - and exactly why the path handed to it must already be in
    the one form the kernel accepts. Two shapes were being produced that the
    kernel rejects, both measured on 2026-08-06:

    * **UNC.** ``\\\\server\\share\\f`` became ``\\\\?\\\\\\server\\share\\f``,
      which fails with **WinError 123** ("the filename, directory or volume
      label syntax is incorrect"). A UNC path takes the ``UNC\\`` form instead:
      ``\\\\?\\UNC\\server\\share\\f``. Verified by error KIND - the malformed
      prefix gives WinError 123 while the correct one gives the ordinary
      WinError 53 ("network path not found"). Anyone syncing to a network share
      hit this on *every* file write, sqlite connect and existence check.
    * **Forward slashes.** ``\\\\?\\C:/Users/x`` does not resolve at all -
      ``os.path.exists`` returns **False** and ``open`` raises "No such file or
      directory", so the file silently looks absent rather than erroring. Tk's
      ``filedialog.askdirectory`` (the fallback folder picker, used whenever the
      COM shell picker fails) returns forward slashes on Windows, so this was
      reachable from the UI.

    ``normpath`` fixes both by canonicalising separators and resolving ``.`` /
    ``..`` - which the prefix would otherwise take literally, since it disables
    the normalisation that would ordinarily do it.

    Paths that are already extended-length (``\\\\?\\``) or Win32 device paths
    (``\\\\.\\``) are returned untouched, as are relative paths (unchanged from
    the original behaviour: the caller's relative path is its own business).
    """
    s = str(p)
    if os.name != 'nt':
        return s
    # Already extended-length, or a device path (\\.\pipe\..., \\.\PhysicalDrive0)
    # - both are parsed raw by the kernel already; prefixing again corrupts them.
    if s.startswith('\\\\?\\') or s.startswith('\\\\.\\'):
        return s
    try:
        # Path.is_absolute() is the ORIGINAL gate and is kept deliberately: it
        # is False for a drive-relative root like "\Users\x" (no drive letter),
        # which cannot be expressed as an extended-length path at all. Widening
        # this to ntpath.isabs() would start emitting "\\?\\Users\x", which is
        # invalid.
        if not Path(s).is_absolute():
            return s
        norm = os.path.normpath(s)
    except (OSError, ValueError):
        return s
    if norm.startswith('\\\\'):
        return '\\\\?\\UNC\\' + norm[2:]
    return '\\\\?\\' + norm


def archive_file_limit() -> int | None:
    """Max files an archive may contain before extraction is declined.

    ``None`` when the user has not asked for a limit, which is the default -
    extraction behaviour is unchanged until they do.

    Read here, once, rather than passed down from each flow. That is deliberate:
    download and sync reach archive extraction through completely different call
    chains, and a value threaded through both is a value that can differ between
    them. This is a machine-level preference like the file-size cap, NOT part of
    a folder's sync contract - the contract records what a folder was downloaded
    WITH, while this is a guard the user can change at any time and expect to
    apply everywhere at once.
    """
    try:
        import streamlit as st
        if not st.session_state.get('archive_max_files_enabled', False):
            return None
        n = int(st.session_state.get('archive_max_files', 0) or 0)
        return n if n > 0 else None
    except Exception:
        # No Streamlit context (a worker thread, a test, the CLI) - never guess
        # a limit into existence; the safe default is the app's default, which
        # is to extract.
        return None


def path_exists(p: str | Path) -> bool:
    """``exists()``, but correct for a path over Windows' 260-character limit.

    ``Path.exists()`` on an over-long path does not raise - it returns **False**,
    which is indistinguishable from "the file is not there". Anything that asks
    "did we already download this?" therefore answers *no* every single time and
    re-fetches a file that is sitting right there, for ever.

    Only the *query* is rewritten; nothing is stored in this form, because a
    ``\\\\?\\`` prefix that reaches a manifest breaks every later comparison
    against a clean path.
    """
    try:
        return os.path.exists(make_long_path(p))
    except (OSError, ValueError):
        return False


def walk_files_long(root: str | Path):
    """Every file under ``root``, as CLEAN (unprefixed) ``Path`` objects.

    The long-path counterpart of ``Path.rglob('*')``, and it exists because
    rglob fails in TWO different silent ways past Windows' limit (both measured
    2026-08-22, on a machine with ``LongPathsEnabled=0``):

    * **The root itself over the limit** - ``rglob`` yields **nothing at all**,
      because the walk cannot open a directory it cannot name.
    * **The root reachable but a file past the limit** - ``rglob`` DOES yield
      the entry, and then ``f.is_file()`` answers **False**, so every caller
      that filters on it drops a file that is sitting right there.

    Neither raises. Post-processing's ``_glob_files`` hit both, and because it
    is the single discovery helper every converter goes through, one silent
    ``[]`` starved all nine of them at once - a course downloaded into a deep
    folder produced no PDFs, no compiled links and no message saying why.

    **Yields clean paths on purpose.** Callers put these into manifest rows and
    hand them to Office COM, and both reject a ``\\\\?\\`` prefix - the same
    asymmetry ``office_safe_path`` documents. So the walk happens THROUGH the
    prefix and each hit is mapped back onto the caller's own spelling of
    ``root``; nothing is ever textually stripped, which would be the fragile way
    to do it.

    Directories are never yielded, matching the ``f.is_file()`` filter this
    replaces. Symlinked directories are not followed, matching ``rglob``.
    """
    root = Path(root)
    walk_root = make_long_path(str(root))
    # No try around os.walk: it is a GENERATOR, so it cannot raise here, and
    # during iteration its default `onerror=None` already swallows a directory
    # it cannot read. That is the same behaviour as the os.walk loops this
    # replaced - a missing or unreadable root yields nothing rather than
    # raising, which every caller relies on (several iterate it inside a list
    # comprehension with no handler of their own).
    for dirpath, _dirnames, filenames in os.walk(walk_root):
        try:
            rel = os.path.relpath(dirpath, walk_root)
        except ValueError:
            continue
        clean_dir = root if rel in ('.', '') else root / rel
        for name in filenames:
            yield clean_dir / name


# ── Temp File Shadowing for Office COM APIs ────────────────────────────

_MAX_PATH_THRESHOLD = 240  # 15-char safety margin below Win32 MAX_PATH (255)


@contextmanager
def office_safe_path(original_path: Path, dst: Path | None = None):
    """Shadow long Windows paths into a temp dir for Office COM APIs.

    ``dst`` (H-7): explicit final PDF target. When omitted, defaults to the
    source path with a .pdf suffix (the historical behavior).

    Win32 COM APIs (PowerPoint, Word, Excel) hard-crash when given file
    paths >= 255 characters.  This context manager transparently copies
    the source file to a short temp path, yields the safe paths for COM
    to work with, and moves the generated PDF result back on exit.

    On short paths (< 240 chars) the context manager is a zero-cost
    pass-through that yields the original paths unchanged.

    Yields:
        (safe_source_path: Path, safe_pdf_target: Path, original_pdf_target: Path)
        - The first two are what COM should receive. The third is the true
          long-path destination where the PDF ultimately belongs.
    """
    resolved = original_path.resolve()
    original_pdf = Path(dst) if dst is not None else original_path.with_suffix('.pdf')

    # macOS/Linux: MAX_PATH is not a concern - always pass-through.
    # This context manager exists exclusively for Win32 COM API limitations.
    if platform.system() != 'Windows':
        yield original_path, original_pdf, original_pdf
        return

    if len(str(resolved)) < _MAX_PATH_THRESHOLD:
        # Short path - pass-through, zero overhead
        yield original_path, original_pdf, original_pdf
        return

    # ── Long path detected: shadow into temp directory ──
    suffix = original_path.suffix  # e.g. '.pptx'
    short_name = f"canvas_{uuid.uuid4().hex[:12]}"
    temp_dir = Path(tempfile.gettempdir())
    temp_source = temp_dir / f"{short_name}{suffix}"
    temp_pdf = temp_dir / f"{short_name}.pdf"

    try:
        # Copy the source file to the short temp path.
        #
        # Through make_long_path, and note the asymmetry: OUR OWN file
        # operations need the prefix, while the paths we YIELD must not have it
        # (Office COM is what chokes on long paths, and it chokes on a "\\?\"
        # prefix too - that asymmetry is the whole reason this shadowing
        # exists). This branch only runs for paths >= 240 chars, so without the
        # prefix the copy fails on a DEFAULT Windows install, where
        # LongPathsEnabled is 0 - i.e. the function whose only purpose is long
        # paths could not read the long source or write the long destination.
        # Not reproducible on a machine with LongPathsEnabled=1; same reasoning
        # (and same fix) as the note in panopto/stream.py.
        shutil.copy2(make_long_path(resolved), str(temp_source))
        logger.debug(
            f"[Path Shadow] Shadowed long path ({len(str(resolved))} chars) "
            f"to temp: {temp_source.name}"
        )

        yield temp_source, temp_pdf, original_pdf

    finally:
        try:
            # ── Ghost PDF Guard: only move if COM actually produced a PDF ──
            if temp_pdf.exists():
                try:
                    # Ensure the true destination directory exists
                    Path(make_long_path(original_pdf.parent)).mkdir(
                        parents=True, exist_ok=True)
                    # Cross-drive safe move with overwrite
                    shutil.move(str(temp_pdf), make_long_path(original_pdf))
                    logger.debug(
                        f"[Path Shadow] Moved PDF back: {temp_pdf.name} → "
                        f"{original_pdf.name}"
                    )
                except Exception as e:
                    logger.error(
                        f"[Path Shadow] Failed to move PDF back from temp: {e}"
                    )
            else:
                logger.debug(
                    "[Path Shadow] No temp PDF generated (COM conversion failed), "
                    "skipping move-back."
                )
        finally:
            # ── Unconditional cleanup of both temp files ──
            temp_source.unlink(missing_ok=True)
            temp_pdf.unlink(missing_ok=True)


def esc(value) -> str:
    """HTML-escape a value for safe interpolation into unsafe_allow_html markup."""
    return html.escape(str(value), quote=True)


def css_content_safe(value) -> str:
    """Escape untrusted text for a CSS ``content: "…"`` inside a ``<style>``.

    Three characters matter and ``esc()`` handles none of them correctly here -
    it produces HTML entities, which render literally as ``&amp;`` in CSS:

    * ``\\`` starts a CSS escape sequence,
    * ``"`` closes the content string,
    * ``<`` is the one that actually bites. The HTML parser scans a ``<style>``
      element's raw text for the literal ``</style``, so a stray one in a course
      code or a user-typed group name **terminates the style element early** and
      every rule after it dies silently - the failure mode CLAUDE.md warns about
      under "Never write a literal angle-bracket tag name inside an
      ``st.html(<style>)`` block". ``\\00003c `` renders as ``<`` for display but
      is not a literal ``<`` to the parser. The trailing space terminates the
      hex escape and is required.

    This is THE definition. It previously existed as two local copies - a weak
    one that stopped at the quote and a hardened one that did not - so the same
    Canvas string was safe on the Today page and unsafe in the course list.
    """
    return (str(value)
            .replace('\\', '\\\\')
            .replace('"', '\\"')
            .replace('<', '\\00003c '))

def robust_filename_normalize(name: str) -> str:
    """Normalize filename for robust comparison (unquote, strip, lower, NFC)."""
    if not name:
        return ""
    try:
        # Handle potential non-string input safely
        val = urllib.parse.unquote_plus(str(name)).strip().lower()
    except Exception:
        val = str(name).strip().lower()
    return unicodedata.normalize('NFC', val)


# --- Pluralization ---


# --- Config Paths ---

SYNC_PAIRS_FILENAME = "canvas_sync_pairs.json"


# APPMODEL_ERROR_NO_PACKAGE - the documented return of every package-identity
# API for a process that has none. Any OTHER return means identity exists
# (a zero-length buffer legitimately answers ERROR_INSUFFICIENT_BUFFER).
_APPMODEL_ERROR_NO_PACKAGE = 15700

_msix_packaged: bool | None = None


def is_msix_package() -> bool:
    """True when this process runs from an MSIX package (the Microsoft Store).

    Asks Windows itself, via ``kernel32.GetCurrentPackageFullName``. That is the
    ONLY authoritative answer: package identity is a property the loader gives
    the process, not something inferable from where the file sits.

    Do NOT go back to a path heuristic. ``core.health_log`` carries the older
    one - ``os.environ.get("MSIX_PACKAGE_ID") or "WindowsApps" in
    sys.executable`` - and half of it is dead: nothing in this repo ever sets
    that variable (build_msix.py included), so it rested entirely on the path
    substring. That is *usually* right and quietly wrong at the edges - a
    sideloaded dev package lands in WindowsApps too, and a repackaged or
    relocated build does not - which is fine for a telemetry field and not
    fine for a gate on a user-facing surface.

    Memoised: identity cannot change inside a process, and callers ask on a
    render path. Never raises - off Windows the DLL has no such export, and
    "not packaged" is the safe answer everywhere (it is what suppresses the
    Store rating card on macOS and on the Inno .exe build).
    """
    global _msix_packaged
    if _msix_packaged is not None:
        return _msix_packaged
    packaged = False
    try:
        if sys.platform == "win32":
            import ctypes
            length = ctypes.c_uint32(0)
            rc = ctypes.windll.kernel32.GetCurrentPackageFullName(
                ctypes.byref(length), None)
            packaged = (rc != _APPMODEL_ERROR_NO_PACKAGE)
    except Exception:
        packaged = False
    _msix_packaged = packaged
    return packaged


def get_config_dir() -> str:
    """Get the directory where config files are stored.

    On macOS frozen bundles:  ~/Library/Application Support/CanvasDownloader/
    On Windows frozen EXEs:   %APPDATA%/CanvasDownloader/
    When running as script:   same directory as this source file

    ``CANVAS_DL_CONFIG_DIR`` overrides all of the above. It exists for ONE
    caller - the live-audit harness in ``tests/audit`` - and it is the reason
    that suite can drive the real app without touching the developer's own
    settings, sync pairs, history, saved groups or Today list, all of which a
    dev run otherwise writes straight into the repo root. Checked first and
    unconditionally, because a half-redirected config dir (settings isolated,
    history not) is worse than none: the audit would report against state it
    had itself polluted. Unset in every shipped build, so behaviour there is
    byte-identical to before this seam existed.

    The override must name a directory that already exists - the harness
    creates and provisions it (see ``tests/audit/harness/state.py``). A missing
    or unusable path falls through to the normal resolution rather than
    silently creating an empty config dir, which would look to the app exactly
    like a fresh install and would sign the user out.
    """
    _override = os.environ.get('CANVAS_DL_CONFIG_DIR', '').strip()
    if _override and os.path.isdir(_override):
        return _override

    if getattr(sys, 'frozen', False) and platform.system() == 'Darwin':
        base = Path.home() / 'Library' / 'Application Support' / 'CanvasDownloader'
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create Darwin config directory {base}: {e}. Falling back to temp.")
            base = Path(tempfile.gettempdir()) / 'CanvasDownloader'
            base.mkdir(parents=True, exist_ok=True)
        return str(base)
    elif getattr(sys, 'frozen', False) and platform.system() == 'Windows':
        appdata = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
        base = Path(appdata) / 'CanvasDownloader'
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create Windows config directory {base}: {e}. Falling back to temp.")
            base = Path(tempfile.gettempdir()) / 'CanvasDownloader'
            base.mkdir(parents=True, exist_ok=True)
        return str(base)
    elif getattr(sys, 'frozen', False):
        # Other frozen platforms: fall back to executable directory
        return os.path.dirname(sys.executable)
    else:
        return _REPO_ROOT


def quarantine_corrupt_json(path, reason: str) -> None:
    """Move a damaged JSON config aside so its content survives on disk.

    Never overwrites an existing quarantine file: the FIRST one is the copy
    closest to the last good state, so later ones take a numeric suffix. Mirrors
    ``core.library._quarantine`` and ``core.preset_manager``.
    """
    path = str(path)
    try:
        base = os.path.splitext(path)[0]
        target = f"{base}.corrupt.json"
        n = 1
        while os.path.exists(target):
            n += 1
            target = f"{base}.corrupt-{n}.json"
        os.replace(path, target)
        logger.warning("Config file %s was unreadable (%s); moved it to %s",
                       path, reason, target)
    except OSError as e:
        logger.warning("Could not quarantine the damaged config file %s: %s", path, e)


def read_json_for_update(path, expect: type = dict) -> tuple:
    """``(data, may_write)`` for a read-modify-write of a shared JSON config.

    **THE ONE implementation of this decision.** ``canvas_downloader_settings.json``
    is CO-OWNED by four modules - ``ui.auth`` (the Settings dialog and the login
    path), ``panopto.settings`` (the ``"panopto"`` engine block *and* the global
    on/off preference) and ``shared.legal`` (the acceptable-use acknowledgement) -
    and each of them has to read the WHOLE file before changing its own key, or it
    destroys everybody else's.

    Every one of those readers degraded a failed read to ``{}`` and wrote anyway.
    ``ui.auth`` was hardened for this on 2026-08-08; the other two modules were
    never swept with it, so three writers still reduced a full settings file to a
    single key. Reproduced against the real functions: one unreadable read cost
    ``panopto_notice_ack_version`` (an ACCEPTED LEGAL NOTICE - the user is asked
    to accept it again), the whole ``"panopto"`` engine block, ``canvas_url``,
    ``default_download_path``, ``show_help_text`` and ``use_12h_format`` - and
    each writer returned ``True``, reporting success.

    This lives in ``shared.helpers`` rather than in any one of them because the
    repo has already paid for the alternative once: ``make_long_path`` had a
    second copy in ``core.sync_manager`` and the fix reached none of the 26
    manifest call sites. A shared decision with two implementations is a fix that
    lands on half the app, silently.

    Split by CAUSE, because the right answer genuinely differs:

    * **damaged content** - malformed JSON, or bytes that are not valid UTF-8.
      ``UnicodeDecodeError`` is a *sibling* of ``json.JSONDecodeError``, not a
      subclass (both are ``ValueError``), which is why it has to be named by a
      handler that means to catch "the file is broken". One editor re-saving one
      of these files in a local ANSI codepage is enough, and they are full of
      ``æøå``. The file cannot be preserved in place, so it is quarantined - its
      content survives on disk - and writing PROCEEDS, so the user gets a working
      config back instead of a permanently unwritable one.
    * **transient ``OSError``** - the config dir on a share that is offline, an
      antivirus lock, a permissions blip. Nothing is wrong with the FILE, so the
      caller must NOT write: ``may_write`` is False and this one change is not
      persisted, which is recoverable. Silently discarding the user's accepted
      notice, their Panopto engine settings and their download folder is not.
    * **missing file** - a genuinely fresh install. ``({}, True)``.

    A payload of the wrong shape is damaged content too: callers subscript the
    result, so returning it would raise inside the writer.

    *expect* is the top-level JSON type the caller needs - ``dict`` for the
    settings files, ``list`` for ``canvas_sync_history.json``. It exists so the
    history store can reuse THIS decision instead of restating it: that store
    had the identical defect (``load_history`` degraded every failure to ``[]``
    and ``add_entry`` wrote it back, so one transient read replaced up to 50
    recorded runs with the single entry being added), and writing a second
    list-shaped copy of this logic is the mistake the paragraph above is about.
    The empty value returned on damage/absence is ``expect()``, so a caller that
    asks for a list is never handed a dict.
    """
    path = str(path)
    empty = expect()
    if not os.path.exists(path):
        return empty, True
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except OSError as e:
        logger.warning(
            "Could not read config at %s (%s); skipping this write so the "
            "existing settings are not discarded.", path, e)
        return empty, False
    except Exception as e:
        quarantine_corrupt_json(path, f"{type(e).__name__}: {e}")
        return empty, True
    if not isinstance(data, expect):
        quarantine_corrupt_json(
            path, f"top level is {type(data).__name__}, not {expect.__name__}")
        return empty, True
    return data, True


def help_text_enabled() -> bool:
    """True when optional explanatory copy should be rendered.

    Backs the Settings toggle "Show help text" (default ON). It gates exactly
    one category: **copy that explains the UI and occupies permanent screen
    space** - the Help buttons/cards (``shared.components.render_help_card``),
    the one-line captions under the primary action buttons, and the sync page's
    intro line.

    It deliberately does NOT gate:
      * anything operational - errors, warnings, empty states, "folder not
        found", counts and statuses. Those are results, not tuition.
      * the reason a control is unavailable ("Select at least one course above
        first"). Hiding that turns a disabled button into a dead end.
      * option labels and card descriptions in the download settings. Those are
        how you know what a toggle does; without them the page is unusable.
      * ``help=`` tooltips. They cost no space until asked for, so there is
        nothing to reclaim by hiding them.

    The distinction that decides it: would a power user who already knows the
    app still need this on screen? If no, it is help text.
    """
    import streamlit as st
    return bool(st.session_state.get('show_help_text', True))


def format_time_display(time_str: str) -> str:
    """Format a 24-hour HH:MM time string respecting the user's 12h/24h preference.

    Reads ``st.session_state['use_12h_format']`` (default ``False`` = 24-hour).
    When the toggle is on, converts e.g. ``'14:30'`` → ``'2:30 PM'``.
    Returns the original string unchanged on parse error or when 24h is selected.
    """
    try:
        import streamlit as st
        if not st.session_state.get('use_12h_format', False):
            return time_str
    except Exception:
        return time_str

    from datetime import datetime as _dt
    try:
        parsed = _dt.strptime(time_str, '%H:%M')
        return parsed.strftime('%I:%M %p').lstrip('0')
    except Exception:
        return time_str


def format_relative_date(raw_time: str, include_time: bool = False, include_emoji: bool = False) -> str:
    """Format a timestamp string (YYYY-MM-DD HH:MM) into a friendly relative date.
    
    Conventions:
    - Under 1 hour: "15 minutes ago" (No exact time needed)
    - Same day: "Today at 14:30"
    - Previous day: "Yesterday at 09:15"
    - Within the last 7 days: "Thursday at 16:45"
    - More than 7 days ago (current year): "24 Apr at 11:20"
    - Previous year: "12 Nov 2025"
    """
    from datetime import datetime, timezone
    try:
        # Primary format written by save_manifest and _save_metadata after C-5 fix.
        # Fallback chain handles legacy UTC ISO strings that may exist in older DBs.
        dt = None
        for _fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(raw_time, _fmt)
                if dt.tzinfo is not None:
                    # Convert UTC-aware datetime to naive local time for comparison
                    dt = dt.astimezone().replace(tzinfo=None)
                break
            except ValueError:
                continue
        if dt is None:
            return raw_time
        now = datetime.now()
        
        diff_total_seconds = (now - dt).total_seconds()
        diff_days = (now.date() - dt.date()).days
        time_str = format_time_display(dt.strftime('%H:%M'))
        
        if diff_total_seconds < 3600 and diff_total_seconds >= 0:
            minutes = int(diff_total_seconds // 60)
            if minutes == 0:
                date_key = "just now"
            elif minutes == 1:
                date_key = "1 minute ago"
            else:
                date_key = f"{minutes} minutes ago"
            include_time = False
        elif diff_days == 0:
            date_key = "Today"
        elif diff_days == 1:
            date_key = "Yesterday"
        elif diff_days < 7 and diff_days > 0:
            date_key = dt.strftime('%A')
        elif dt.year == now.year:
            import streamlit as _st
            if _st.session_state.get('use_12h_format', False):
                date_key = f"{dt.strftime('%b')} {dt.day}"       # American: "Apr 24"
            else:
                date_key = f"{dt.day} {dt.strftime('%b')}"       # European: "24 Apr"
        else:
            import streamlit as _st
            if _st.session_state.get('use_12h_format', False):
                date_key = f"{dt.strftime('%b')} {dt.day}, {dt.year}"  # American: "Nov 12, 2025"
            else:
                date_key = f"{dt.day} {dt.strftime('%b')} {dt.year}"   # European: "12 Nov 2025"
            include_time = False
            
        parts = []
        if include_emoji:
            parts.append("📅")
        parts.append(date_key)
        if include_time:
            parts.append(f"at {time_str}")
            
        return " ".join(parts)
    except Exception as _frd_exc:
        import logging as _logging
        _logging.getLogger(__name__).debug(
            f"format_relative_date: could not parse %r: %s", raw_time, _frd_exc
        )
        return raw_time


# --- Persistent Sync Pairs (the working "active" sync list) ---
#
# An entry is EITHER a reference to a saved library pair (it carries ``saved_id``)
# or a RAW, unsaved pair (no ``saved_id``). A referenced entry is resolved against
# ``core.library`` on every read/write, so a hub rename or re-linked folder shows
# up on the working list with no reconcile - the id is stable, so it even survives
# a folder move. If the saved pair is deleted, the entry degrades to a raw copy
# (keeps its last-known fields, drops the dangling ``saved_id``) rather than
# vanishing from the user's working list.

def _resolve_active_pairs(raw_entries) -> list[dict]:
    """Bind active-list entries to their library pairs and refresh their fields.

    ``course_id`` / ``local_folder`` / ``course_name`` for a referenced entry come
    from the library (current), so a stale on-disk cache can never be authoritative
    for a saved pair. Entries with no ``saved_id`` are bound opportunistically by
    link, so pre-existing lists (and this feature's first run) pick up a reference.
    """
    if not isinstance(raw_entries, list):
        return []
    try:
        import core.library as _library
        by_id = {p["id"]: p for p in _library.pairs()}
    except Exception:
        _library, by_id = None, {}

    out = []
    for e in raw_entries:
        if not isinstance(e, dict):
            continue
        p = None
        sid = e.get("saved_id")
        if sid:
            p = by_id.get(sid)
        elif _library is not None:
            p = _library.pair_for(e.get("course_id"), e.get("local_folder"))
        if p is not None:
            # Preserve the entry's own keys (last_synced, ...); override only the
            # fields the library is authoritative for, and stamp the reference.
            merged = dict(e)
            merged["course_id"] = p["course_id"]
            merged["local_folder"] = p["local_folder"]
            # Prefer the library's cached name, but a BLANK library name must
            # not wipe a good one the entry already carries: `.get(k, default)`
            # returns the stored "" (the key is always present), so fall back
            # with `or`, not a default. A saved pair claimed without a course
            # name (e.g. via the daily set) would otherwise blank the sync-list
            # card's course name on every resolve.
            merged["course_name"] = (
                (p.get("course_name") or "").strip()
                or merged.get("course_name", ""))
            merged["saved_id"] = p["id"]
            out.append(merged)
        else:   # raw (unsaved), or a reference whose saved pair was deleted
            raw = dict(e)
            raw.pop("saved_id", None)   # drop a dangling reference
            out.append(raw)
    return out


def load_sync_pairs(config_dir: str = None) -> list[dict]:
    """Load the working sync list from disk, resolved against the library.

    Returns:
        List of dicts with keys: course_id, local_folder, course_name,
        last_synced (+ saved_id for entries that reference a saved library pair).
    """
    if config_dir is None:
        config_dir = get_config_dir()

    path = Path(config_dir) / SYNC_PAIRS_FILENAME

    with _sync_pairs_lock:
        if not path.exists():
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                pairs = json.load(f)
            return _resolve_active_pairs(pairs)
        except (json.JSONDecodeError, IOError, ValueError):
            # ValueError also covers UnicodeDecodeError, which is a SIBLING of
            # JSONDecodeError (both ValueError), not a subclass - so the old
            # tuple let a file re-saved in a non-UTF-8 codepage escape and crash
            # the sync page instead of degrading to an empty list.
            logging.getLogger(__name__).warning(
                "Could not read sync pairs at %s; treating the list as empty.", path)
            return []


def atomic_update_sync_pairs(modifier_func: callable, config_dir: str = None) -> list[dict]:
    """Atomically update sync pairs, solving TOCTOU race conditions.
    
    Args:
        modifier_func: A callable that takes the current list of pairs and returns the new list.
        config_dir: Config directory path
        
    Returns:
        The updated list of pairs.
    """
    if config_dir is None:
        config_dir = get_config_dir()
        
    path = Path(config_dir) / SYNC_PAIRS_FILENAME
    temp_path = path.with_suffix('.tmp')
    
    with _sync_pairs_lock:
        # 1. READ
        pairs = []
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        pairs = data
            except OSError as e:
                # The file is there but unreachable right now. It is NOT empty,
                # and continuing would write the caller's single change over the
                # whole list - the same silent-wipe shape that cost the daily
                # sync its pairs. Abort the write; nothing is lost.
                logging.getLogger(__name__).warning(
                    f"Sync pairs at {path} could not be read ({e}); skipping this "
                    "update rather than overwriting the file.")
                return _resolve_active_pairs(pairs)
            except Exception as e:
                # Damaged CONTENT (bad JSON, or bytes that are not valid UTF-8 -
                # a sibling of JSONDecodeError, so the old handler missed it).
                # Move it aside so the list can be rebuilt without destroying
                # what was there; mirrors core.library._quarantine.
                try:
                    for _n in range(1, 20):
                        _bak = path.with_name(
                            f"{path.stem}.corrupt{'' if _n == 1 else f'-{_n}'}{path.suffix}")
                        if not _bak.exists():
                            os.replace(str(path), str(_bak))
                            break
                    logging.getLogger(__name__).error(
                        f"Sync pairs at {path} are unreadable ({type(e).__name__}: {e}); "
                        "moved aside and starting from an empty list.")
                except OSError as _mv:
                    logging.getLogger(__name__).error(
                        f"Sync pairs at {path} are unreadable and could not be moved "
                        f"aside: {_mv}")

        # Resolve references against the library BEFORE the modifier runs, so it
        # matches the caller's signatures against CURRENT (course_id, folder) - a
        # saved pair re-linked in the hub is found by its new folder, not the
        # stale one on disk.
        pairs = _resolve_active_pairs(pairs)

        # 2. MODIFY
        new_pairs = modifier_func(pairs)
        
        # 3. WRITE
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(new_pairs, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
            return new_pairs
        except OSError as e:
            logging.getLogger(__name__).warning(f"Failed to save sync pairs: {e}")
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            # Return what's currently on disk so callers don't act on uncommitted data (M-22).
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            return data
                except Exception:
                    pass
            return pairs


# --- Disk Space ---

def check_disk_space(path: str, required_bytes: int = 0, min_free_gb: float = 1.0) -> tuple[bool, float, float]:
    """Check if there's enough disk space.
    
    Uses dynamic threshold: max(min_free_gb, required_bytes * 1.2).
    This ensures large downloads (e.g., 10GB course) are properly accounted for
    instead of only checking against a static 1GB minimum.
    
    Args:
        path: Path on the target volume
        required_bytes: Bytes needed for the download payload
        min_free_gb: Minimum free space floor in GB
        
    Returns:
        Tuple of (has_enough_space, available_mb, total_mb)
    """
    try:
        check_path = Path(path).resolve()
        # Find the first existing parent directory
        while not check_path.exists() and check_path.parent != check_path:
            check_path = check_path.parent
            
        if not check_path.exists():
            # If we still can't find an existing path (e.g. invalid drive), assume okay
            return True, -1, -1
            
        stat = shutil.disk_usage(str(check_path))
        available_mb = stat.free / (1024 * 1024)
        total_mb = stat.total / (1024 * 1024)
        # Dynamic threshold: at least min_free_gb, or payload + 20% buffer
        min_required = max(min_free_gb * 1024 * 1024 * 1024, int(required_bytes * 1.2))
        has_enough = stat.free >= min_required
        return has_enough, available_mb, total_mb
    except OSError as e:
        logger.warning(f"Could not check disk space at {path!r}: {e}")
        return True, -1, -1
    except Exception as e:
        logger.warning(f"Unexpected error checking disk space: {e}")
        return True, -1, -1


#: What ``check_disk_space`` reports for available/total when it could not
#: determine them at all (invalid drive, disconnected share, any OSError). It is
#: a SENTINEL, not a measurement, and every surface that shows free space has to
#: know that - which is why the renderer for it lives here, beside the function
#: that produces it, rather than being spelled out again at each call site.
DISK_SPACE_UNKNOWN = -1


def disk_fill_percent(total_bytes, avail_mb):
    """How much of the remaining space this run would take, or ``None``.

    THREE outcomes, because the caller has three things to say and the inline
    arithmetic this replaces could only say two:

    * ``None``  - the volume was never measured (``check_disk_space``'s -1
      sentinel). Nothing may be drawn or warned about. The dialog's own comment
      claimed its maths "suppresses the bar instead of drawing a false one", and
      it did not: the 1% floor applied whenever ``total_bytes > 0``, so an
      offline share rendered a 1% bar, which reads as plenty of room.
    * ``100.0`` - measured, and there is no room at all. The old expression gated
      the ratio on ``avail_bytes > 0``, so a genuinely FULL volume fell to the 1%
      floor and the "your disk is getting full" notice - which fires above 70% -
      could not fire. Measured: 0.4 MB free warned, 0 B free did not. The one
      case the warning exists for was the only one it could not reach.
    * otherwise  - the linear ratio, with a 1% floor so a small run is still visible.

    ``ui/sync_review.py`` blocks a full volume before the dialog is ever reached
    (``check_disk_space`` demands 1 GB), so the 100.0 case is belt-and-braces; the
    ``None`` case is not - an unreadable volume passes that gate by design.

    Extracted rather than left inline for the reason ``format_available_space``'s
    own history records: a test that re-implements the dialog's expression tests
    the copy, and four mutants survived on exactly that.
    """
    try:
        avail = float(avail_mb)
        total = float(total_bytes)
    except (TypeError, ValueError):
        return None
    if avail != avail or total != total:        # NaN
        return None
    if avail < 0:                              # the "could not determine" sentinel
        return None
    if total <= 0:
        return 0.0
    avail_bytes = avail * 1024 * 1024
    if avail_bytes <= 0:
        return 100.0
    return min(100.0, max(1.0, total / avail_bytes * 100))


def format_available_space(avail_mb) -> str:
    """Human-readable free space, or ``"Unknown"`` for the sentinel above.

    The Confirm Sync dialog used to multiply ``avail_mb`` out and print it
    verbatim, so a target whose volume could not be read rendered
    **"Available Disk Space: -1048576 B"**.

    "0 B" is NOT the fix and must not be substituted: it reads as a completely
    full disk, which is wrong in the opposite direction and would make a user
    cancel a sync that had plenty of room. The only honest answer for a value
    that was never measured is that it is unknown.

    A genuine zero (a real, genuinely full volume) is distinct from the sentinel
    and still formats as "0 B".
    """
    try:
        mb = float(avail_mb)
    except (TypeError, ValueError):
        return "Unknown"
    if mb != mb or mb < 0:          # NaN, or the "could not determine" sentinel
        return "Unknown"
    return format_file_size(mb * 1024 * 1024)


# --- Folder Opener ---

def picker_start_for_existing(path: str | None) -> str | None:
    """Where a folder picker should OPEN when RE-choosing an already-set folder.

    Returns the folder's PARENT, so the panel lists the current folder among its
    siblings with everything else you might pick instead. Passing the folder
    itself makes the panel open *inside* it, which is right for "choose a
    destination" and wrong for "change this folder": you land in a directory
    whose contents are all irrelevant (a course folder's own PDFs) and have to
    navigate UP before you can choose anything, and re-pointing a pair at a
    moved or renamed sibling is the common case. Reported on macOS and Windows.

    Non-existent, empty or root paths fall through unchanged so the caller's own
    fallback chain (session default -> ~/Downloads) still applies. ONE function
    because this is a rule, and the two platforms' pickers must not disagree
    about it - `choose folder default location` on macOS and IFileOpenDialog on
    Windows both take the same directory from here.
    """
    if not path:
        return path
    try:
        p = Path(path)
        if not p.is_dir():
            return path
        parent = p.parent
        if parent == p or not parent.is_dir():
            return path            # a volume root has no useful parent
        return str(parent)
    except (OSError, ValueError):
        return path


def native_folder_picker(initial_dir: str | None = None) -> str | None:
    """Open native folder picker dialog safely across threads inside Streamlit.
    Builds the Tkinter root with correct attributes, destroys it on close,
    and handles missing assets gracefully.

    Args:
        initial_dir: Preferred starting directory. Falls back to default_download_path
                     session state, then the user's Downloads folder.
    Returns:
        Absolute path to selected folder as string, or None if cancelled.
    """
    # Resolve the best starting directory: given path → session default → Downloads
    start_dir: str | None = None
    if initial_dir and os.path.isdir(initial_dir):
        start_dir = initial_dir
    if start_dir is None:
        try:
            import streamlit as st
            default = st.session_state.get('default_download_path', '') or ''
            if default and os.path.isdir(default):
                start_dir = default
        except Exception:
            pass
    if start_dir is None:
        downloads = str(Path.home() / 'Downloads')
        start_dir = downloads if os.path.isdir(downloads) else str(Path.home())

    import platform
    if platform.system() == 'Darwin':
        import subprocess
        try:
            # Escape backslash, double-quote and both line breaks so a path
            # containing any of them can never break out of the AppleScript
            # string literal. Through the shared escaper: this copy happened to
            # be correct, but keeping it meant the rule was written three times
            # and one of the three was wrong (see applescript_string).
            from engine.applescript_bridge import applescript_string
            safe_dir = applescript_string(start_dir)
            script = f'POSIX path of (choose folder default location (POSIX file "{safe_dir}"))'
            # No timeout: the user may take an arbitrarily long time to choose
            # a folder.  A subprocess.TimeoutExpired here would silently
            # cancel the picker mid-interaction.
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True, text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            return None
        except Exception:
            return None

    # Windows: the modern shell picker (IFileOpenDialog), shown modal to the app
    # window so it opens as a proper owned dialog instead of a stray top-level
    # window with its own taskbar button. Only a genuine COM error falls through
    # to the tkinter picker below; a user cancel returns None with no fallback.
    if platform.system() == 'Windows':
        try:
            res = _win_shell_folder_picker(
                start_dir, multi=False, owner_hwnd=_app_owner_hwnd())
            if res is not None:
                return res[0] if res else None
        except Exception as e:
            logger.warning(f"Windows shell folder picker failed, using tkinter: {e}")

    # tkinter is the FALLBACK picker (a COM failure above, plus Linux/dev). tk.Tk()
    # raises tkinter.TclError if no display is available (headless container,
    # broken X server, etc.). Wrap the whole construction so a missing GUI
    # surfaces as "no folder selected" instead of crashing the script thread.
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:
        logger.warning(f"tkinter not available for folder picker: {e}")
        return None

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)

        try:
            icon_path = os.path.join(_REPO_ROOT, 'assets', 'icon.ico')
            if os.path.exists(icon_path):
                root.iconbitmap(icon_path)
        except Exception:
            pass

        folder_path = filedialog.askdirectory(master=root, initialdir=start_dir)
        return folder_path if folder_path else None
    except Exception as e:
        logger.warning(f"Folder picker failed: {e}")
        return None
    finally:
        # Always destroy the Tk root so it can never leak across Streamlit reruns.
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def _resolve_picker_start_dir(initial_dir: str | None) -> str:
    """Best starting directory for a folder picker: given path → session
    default → the user's Downloads folder → home. Shared by the single- and
    multi-folder pickers so they always open in the same place."""
    if initial_dir and os.path.isdir(initial_dir):
        return initial_dir
    try:
        import streamlit as st
        default = st.session_state.get('default_download_path', '') or ''
        if default and os.path.isdir(default):
            return default
    except Exception:
        pass
    downloads = str(Path.home() / 'Downloads')
    return downloads if os.path.isdir(downloads) else str(Path.home())


def _app_owner_hwnd() -> int:
    """HWND of this process's top-level ``Canvas Downloader`` window (the pywebview
    shell), or ``0`` when there is none - e.g. under ``streamlit run`` in dev,
    where the picker stays an un-owned standalone dialog exactly as before.

    Used as the OWNER of the native folder dialog so it opens as a proper modal of
    the app window instead of spawning its own top-level window with its own
    taskbar button (which reads as "a second Canvas Downloader instance"). Matching
    on PID + title needs no coupling to pywebview and degrades to ``0`` safely, so a
    wrong/missing match can never do worse than the old un-owned behaviour.

    Explicit ``argtypes``/``restype`` on a private ``WinDLL`` (not the shared
    ``windll`` cache) keep 64-bit handles from being passed as 32-bit ``c_int``.
    """
    if os.name != 'nt':
        return 0
    import ctypes
    from ctypes import wintypes
    try:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                    ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL

        our_pid = ctypes.windll.kernel32.GetCurrentProcessId()
        found: list[int] = []

        @_WNDENUMPROC
        def _enum(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindow(hwnd, 4):        # GW_OWNER set -> owned window, skip
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != our_pid:
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value == 'Canvas Downloader':
                found.append(int(hwnd) if hwnd else 0)
                return False                     # found it - stop enumerating
            return True

        user32.EnumWindows(_enum, 0)
        return found[0] if found else 0
    except Exception as e:
        logger.warning(f"Could not resolve app owner window for folder picker: {e}")
        return 0


# The shared Windows folder picker: drives the shell's IFileOpenDialog directly
# over its COM vtables via ctypes. It backs BOTH the single picker (native_folder_
# picker) and the multi picker (native_folder_multi_picker) - FOS_ALLOWMULTISELECT
# is the only native Windows control that lets the user pick SEVERAL folders in one
# dialog (tkinter's askdirectory is single-folder only), and single-select is the
# same dialog without that flag. It runs on a dedicated STA thread (the shell
# dialog requires apartment threading); any failure returns None so the caller
# falls back (to the single picker for multi, to tkinter for single).
#
# The multi picker used to shell out to PowerShell + Add-Type, which showed a
# PowerShell window and took ~1s to JIT-compile on every open; the single picker
# used tkinter. The in-process COM call is the same native Explorer dialog for
# both, opens instantly, never flashes a console, and (given an owner_hwnd) opens
# as a proper owned modal of the app window.

def _win_shell_folder_picker(start_dir: str, *, multi: bool,
                             owner_hwnd: int = 0) -> list[str] | None:
    """Windows native folder picker via the shell ``IFileOpenDialog``.

    ``multi=True`` sets ``FOS_ALLOWMULTISELECT`` so several folders can be chosen
    at once; ``multi=False`` is an ordinary single-folder picker. Either way
    ``GetResults`` returns an ``IShellItemArray``, so one code path serves both.

    ``owner_hwnd`` is the window the dialog is shown modal to - pass the app's main
    window (see :func:`_app_owner_hwnd`) so it opens as an OWNED modal instead of
    an un-owned top-level window that spawns its own taskbar button. ``0``/NULL
    keeps the old un-owned behaviour (e.g. dev, where there is no app window).

    Returns a list of absolute paths (empty on cancel), or None if the picker
    could not run at all - the caller then falls back. Driven by ctypes over the
    COM vtables on a dedicated STA thread.
    """
    import ctypes
    import threading
    from ctypes import wintypes, POINTER, byref, c_void_p

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    def _guid(s: str) -> "_GUID":
        g = _GUID()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), byref(g))
        return g

    def _method(ptr, index, restype, *argtypes):
        """Bind vtable slot *index* of the interface at *ptr* as a callable."""
        vtable = ctypes.cast(ptr, POINTER(c_void_p))[0]
        fn_addr = ctypes.cast(vtable, POINTER(c_void_p))[index]
        return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(fn_addr)

    HR = ctypes.c_long
    DW = wintypes.DWORD
    # vtable indices (IUnknown 0-2 first): see the CLR interface above for order.
    _RELEASE = 2
    _DLG_SHOW, _DLG_SETOPTS, _DLG_GETOPTS, _DLG_SETFOLDER, _DLG_GETRESULTS = 3, 9, 10, 12, 27
    _ARR_GETCOUNT, _ARR_GETITEMAT = 7, 8
    _ITEM_GETDISPLAYNAME = 5
    _FOS = 0x20 | 0x40           # PICKFOLDERS | FORCEFILESYSTEM
    if multi:
        _FOS |= 0x200            # ALLOWMULTISELECT
    _SIGDN_FILESYSPATH = 0x80058000
    _CLSID_FileOpenDialog = "{DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7}"
    _IID_IFileOpenDialog = "{D57C7288-D4AD-4768-BE02-9D969532D960}"
    _IID_IShellItem = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"

    result: dict = {"paths": None, "error": None}

    def _worker():
        ole32 = ctypes.oledll.ole32
        # CoTaskMemFree and CoUninitialize return void, so their "HRESULT" is a
        # garbage register: calling them through oledll (which validates the
        # return) can raise OSError spuriously and abort the whole pick. Drive
        # those two through windll, which ignores the return, so a successful
        # multi-select is never mistaken for a failure.
        ole32_void = ctypes.windll.ole32
        initialized = False
        try:
            try:
                ole32.CoInitializeEx(None, 0x2)   # COINIT_APARTMENTTHREADED
                initialized = True
            except OSError:
                pass  # already initialised on this thread - fine
            p_dlg = c_void_p()
            clsid = _guid(_CLSID_FileOpenDialog)
            iid = _guid(_IID_IFileOpenDialog)
            ole32.CoCreateInstance(byref(clsid), None, 1, byref(iid), byref(p_dlg))  # CLSCTX_INPROC_SERVER
            try:
                opts = DW()
                _method(p_dlg, _DLG_GETOPTS, HR, POINTER(DW))(p_dlg, byref(opts))
                _method(p_dlg, _DLG_SETOPTS, HR, DW)(p_dlg, DW(opts.value | _FOS))
                if start_dir:
                    try:
                        item_iid = _guid(_IID_IShellItem)
                        p_start = c_void_p()
                        ctypes.oledll.shell32.SHCreateItemFromParsingName(
                            ctypes.c_wchar_p(start_dir), None, byref(item_iid), byref(p_start))
                        if p_start:
                            _method(p_dlg, _DLG_SETFOLDER, HR, c_void_p)(p_dlg, p_start)
                            _method(p_start, _RELEASE, ctypes.c_ulong)(p_start)
                    except OSError:
                        pass  # bad initial dir - open at the default location
                owner = c_void_p(owner_hwnd) if owner_hwnd else None
                hr = _method(p_dlg, _DLG_SHOW, HR, c_void_p)(p_dlg, owner)
                if hr != 0:
                    result["paths"] = []   # user cancelled (or dialog closed)
                    return
                p_arr = c_void_p()
                _method(p_dlg, _DLG_GETRESULTS, HR, POINTER(c_void_p))(p_dlg, byref(p_arr))
                if not p_arr:
                    result["paths"] = []
                    return
                try:
                    count = DW()
                    _method(p_arr, _ARR_GETCOUNT, HR, POINTER(DW))(p_arr, byref(count))
                    paths = []
                    for i in range(count.value):
                        p_item = c_void_p()
                        _method(p_arr, _ARR_GETITEMAT, HR, DW, POINTER(c_void_p))(
                            p_arr, DW(i), byref(p_item))
                        if not p_item:
                            continue
                        try:
                            p_name = c_void_p()
                            _method(p_item, _ITEM_GETDISPLAYNAME, HR, ctypes.c_uint, POINTER(c_void_p))(
                                p_item, _SIGDN_FILESYSPATH, byref(p_name))
                            if p_name:
                                s = ctypes.wstring_at(p_name)
                                ole32_void.CoTaskMemFree(p_name)
                                if s:
                                    paths.append(s)
                        finally:
                            _method(p_item, _RELEASE, ctypes.c_ulong)(p_item)
                    result["paths"] = paths
                finally:
                    _method(p_arr, _RELEASE, ctypes.c_ulong)(p_arr)
            finally:
                _method(p_dlg, _RELEASE, ctypes.c_ulong)(p_dlg)
        except OSError as e:
            result["error"] = e
        finally:
            # Never leave the app window disabled if the modal loop is torn down
            # abnormally (a clean dialog close re-enables its owner itself). The
            # owner lives on the pywebview UI thread; EnableWindow is cross-thread
            # safe, and re-enabling an already-enabled window is a no-op.
            if owner_hwnd:
                try:
                    ctypes.windll.user32.EnableWindow(wintypes.HWND(owner_hwnd), True)
                except Exception:
                    pass
            if initialized:
                try:
                    ole32_void.CoUninitialize()
                except Exception:
                    pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()
    if result["error"] is not None:
        logger.warning(f"Shell folder picker (Windows COM) failed: {result['error']}")
        return None
    return result["paths"]


def _mac_multi_folder_picker(start_dir: str) -> list[str] | None:
    """macOS native multi-folder picker via AppleScript ``choose folder`` with
    ``multiple selections allowed``. Returns a list of POSIX paths (empty on
    cancel), or None on a genuine failure so the caller falls back."""
    import subprocess
    safe_dir = (
        (start_dir or '')
        .replace('\\', '\\\\')
        .replace('"', '\\"')
        .replace('\n', ' ')
        .replace('\r', ' ')
    )
    script = (
        f'set theFolders to choose folder default location (POSIX file "{safe_dir}") '
        'with multiple selections allowed\n'
        'set out to ""\n'
        'repeat with f in theFolders\n'
        '  set out to out & POSIX path of f & linefeed\n'
        'end repeat\n'
        'return out'
    )
    try:
        result = subprocess.run(
            ['osascript', '-e', script], capture_output=True, text=True,
        )
    except Exception as e:
        logger.warning(f"Multi-folder picker (macOS) failed to launch: {e}")
        return None
    if result.returncode != 0:
        err = (result.stderr or '')
        # -128 is a normal cancel, not a failure.
        #
        # BOTH spellings, because macOS emits the BRITISH one: measured on
        # 26.6.1, `osascript -e 'error number -128'` says **"User cancelled."**
        # with two L's, so the American clause here was DEAD and the verdict
        # rested entirely on the number beside it. Same defect this app already
        # had in `_classify_stderr`, where macOS's "Not authorised" never
        # matched an American-only clause.
        #
        # It matters which one answers: `[]` means the user cancelled, `None`
        # means the picker could not run - and the caller answers `None` by
        # falling back to the SINGLE picker, i.e. by opening a second dialog at
        # someone who just pressed Cancel.
        _low = err.lower()
        if 'user cancelled' in _low or 'user canceled' in _low or '-128' in err:
            return []
        logger.warning("Multi-folder picker (macOS) error: %s", err.strip())
        return None
    out = result.stdout or ''
    return [line.strip() for line in out.splitlines() if line.strip()]


def native_folder_multi_picker(initial_dir: str | None = None) -> list[str]:
    """Open a native picker that allows selecting MULTIPLE folders at once.

    Used by the Sync page's "Add Course" flow to add several course folders in
    one action. Supported on Windows (IFileOpenDialog) and macOS (AppleScript);
    on any other platform, or if the multi-picker can't run, it falls back to
    the single :func:`native_folder_picker` and returns a one-element list.

    Returns a list of absolute folder paths - empty if the user cancelled.
    """
    start_dir = _resolve_picker_start_dir(initial_dir)

    import platform
    system = platform.system()
    try:
        if system == 'Windows':
            res = _win_shell_folder_picker(
                start_dir, multi=True, owner_hwnd=_app_owner_hwnd())
            if res is not None:
                return res
        elif system == 'Darwin':
            res = _mac_multi_folder_picker(start_dir)
            if res is not None:
                return res
    except Exception as e:
        logger.warning(f"Multi-folder picker failed, falling back to single: {e}")

    # Fallback: the single-folder picker (also covers Linux and any error above).
    single = native_folder_picker(initial_dir=initial_dir)
    return [single] if single else []


def _win_short_path(path: str) -> str:
    """Return the Windows 8.3 short path for *path* (unchanged on failure or
    non-Windows). Every component of an 8.3 path is <= 12 chars, so a deeply
    nested path stays under MAX_PATH (~260) - which the legacy shell commands
    ``explorer /select`` and the ShellExecute "open" verb need (a longer path
    makes them silently open Documents/Desktop instead). Requires the path to
    exist (callers check first)."""
    if os.name != 'nt':
        return path
    try:
        import ctypes
        from ctypes import wintypes
        _GetShort = ctypes.windll.kernel32.GetShortPathNameW
        _GetShort.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        _GetShort.restype = wintypes.DWORD
        buf = ctypes.create_unicode_buffer(4096)
        n = _GetShort(path, buf, len(buf))
        if n and n < len(buf) and buf.value:
            return buf.value
    except Exception:
        pass
    return path


def open_folder(path: str):
    """
    Opens a folder in the native file explorer and forces it to the foreground.
    """

    path = os.path.normpath(path)
    if not os.path.exists(path):
        return

    sys_platform = platform.system()

    if sys_platform == "Windows":
        try:
            # Long folder paths (>~260) can't be opened via the shell - use the
            # 8.3 short path when needed so the correct folder actually opens.
            _open_target = path
            if len(path) >= 240:
                _short = _win_short_path(path)
                if _short != path and len(_short) < 240:
                    _open_target = _short
            os.startfile(_open_target)
        except OSError as e:
            logger.warning(f"Could not open folder {path!r}: {e}")
            return
        
        # --- HACK: Bypass Windows Focus Stealing Prevention ---
        # Windows prevents background processes (like the Streamlit backend) from 
        # stealing focus. Simulating an Alt-key press tricks the OS into allowing it.
        try:
            import ctypes
            time.sleep(0.15) # Give File Explorer a tiny fraction of a second to initialize
            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0) # Alt key down
            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0) # Alt key up
        except Exception:
            pass
            
    elif sys_platform == "Darwin":  # macOS
        subprocess.Popen(["open", path])
    else:  # Linux
        subprocess.Popen(["xdg-open", path])


def _windows_foreground_nudge():
    """Trick Windows out of focus-stealing prevention so a freshly launched
    Explorer / default-app window comes to the foreground. Simulates a tap of
    the Alt key (the same hack used by open_folder)."""
    try:
        import ctypes
        time.sleep(0.15)  # let the new window initialize
        ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)  # Alt down
        ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)  # Alt up
    except Exception:
        pass


def open_file(path: str) -> bool:
    """Open a single file in the OS default application and foreground it.

    Returns True if the open was dispatched, False if the file is missing or
    the OS call failed. Never raises - callers render UI from the bool.
    """
    if not path:
        return False
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        return False

    sys_platform = platform.system()
    try:
        if sys_platform == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
            _windows_foreground_nudge()
        elif sys_platform == "Darwin":
            subprocess.Popen(["open", path])
        else:  # Linux
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        logger.warning(f"Could not open file {path!r}: {e}")
        return False
    return True


def reveal_in_folder(path: str) -> bool:
    """Reveal a file in the native file manager with the file itself selected
    (Explorer /select, Finder reveal). On Linux - which has no portable
    'select' verb - falls back to opening the containing folder.

    Returns True if dispatched, False if the file is missing or the call
    failed. Never raises.
    """
    if not path:
        return False
    path = os.path.normpath(path)
    if not os.path.exists(path):
        # File moved/deleted - degrade gracefully to its parent folder.
        parent = os.path.dirname(path)
        if parent and os.path.isdir(parent):
            open_folder(parent)
            return True
        return False

    sys_platform = platform.system()
    try:
        if sys_platform == "Windows":
            # explorer.exe has non-standard command-line parsing: the list-arg
            # form (subprocess auto-quotes) makes it ignore the path and fall
            # back to opening Documents whenever the path contains spaces. Pass
            # a single command STRING so CreateProcess hands explorer exactly
            # `/select,"<path>"` - the form it actually honours. (Returns exit
            # code 1 even on success, so Popen, not check_call.)
            #
            # explorer /select ALSO silently opens Documents/Desktop when the
            # path is at/over MAX_PATH (~260). Use the 8.3 short path so it can
            # still select the real file; if 8.3 is unavailable on this volume
            # and the path is long, degrade to opening the containing folder.
            sel_path = path
            if len(path) >= 240:
                _short = _win_short_path(path)
                if _short != path and len(_short) < 240:
                    sel_path = _short
                else:
                    open_folder(os.path.dirname(path))
                    return True
            subprocess.Popen(f'explorer /select,"{sel_path}"')
            _windows_foreground_nudge()
        elif sys_platform == "Darwin":
            subprocess.Popen(["open", "-R", path])
        else:  # Linux - no universal 'select'; open the parent folder instead.
            open_folder(os.path.dirname(path))
    except Exception as e:
        logger.warning(f"Could not reveal file {path!r}: {e}")
        return False
    return True


# --- Friendly Course Name ---

def friendly_course_name(raw_name: str) -> str:
    """Strip Canvas technical metadata from a course name.
    
    Canvas course names often look like:
        'Virksomhedens styring (2): Regnskab (LA F26 BINTO1057U) (BINTO1057U.LA_F26 (...))'
    
    This strips semester codes, course IDs, and duplicate bracket content to return:
        'Virksomhedens styring (2): Regnskab'
    
    Args:
        raw_name: Raw course name from Canvas API
        
    Returns:
        Clean, student-friendly course name
    """
    if not raw_name:
        return raw_name
    
    name = raw_name.strip()
    
    # Remove trailing parenthetical blocks that contain course codes or semester IDs.
    # Canvas names often look like:
    #   'Course Name (LA F26 BINTO1057U) (BINTO1057U.LA_F26 (...))'
    # Strategy: find the last balanced (...) at the end and strip it if it looks technical.
    
    found_codes = set()
    
    while True:
        stripped = name.rstrip()
        if not stripped.endswith(')'):
            break
        # Walk backwards to find the matching opening '('
        depth = 0
        open_pos = None
        for i in range(len(stripped) - 1, -1, -1):
            if stripped[i] == ')':
                depth += 1
            elif stripped[i] == '(':
                depth -= 1
                if depth == 0:
                    open_pos = i
                    break
        if open_pos is None:
            break
        paren_content = stripped[open_pos:]
        
        # Check if it contains course-code-like patterns
        has_course_code = bool(re.search(r'[A-Z]{2,}\d{2,}', paren_content))
        has_semester = bool(re.search(r'[FELS]\d{2}\b', paren_content))
        has_dots = '...' in paren_content
        
        if has_course_code or has_semester or has_dots:
            # Extract Class Codes (e.g., LA, XB) from the block being stripped
            # Matches "XA", "LA", "XB" as standalone words
            codes = re.findall(r'\b([XL][A-Z])\b', paren_content)
            if codes:
                found_codes.update(codes)
            
            name = stripped[:open_pos].strip()
        else:
            break
    
    # Clean up any trailing whitespace or stray characters
    name = name.rstrip(' ---')
    
    # Append found group codes (e.g., " (LA)")
    if found_codes:
        # Sort to ensure deterministic order (e.g. LA, XB)
        code_str = ', '.join(sorted(found_codes))
        name = f"{name} ({code_str})"
    
    return name if name else raw_name


def get_course_display_parts(course) -> tuple[str, str]:
    """Extract a clean display name and course code from a Canvas course.

    The display name is built by applying ``friendly_course_name()`` to
    strip Canvas metadata and append class-type codes (e.g. "(LA)").

    Prefers ``friendly_name`` (user-set nickname) when present, otherwise
    falls back to ``name``.  All attribute access is guarded with
    ``getattr`` so the app never crashes on incomplete course objects.

    Returns:
        (display_name, course_code) - both guaranteed to be strings (never None).
        display_name: Cleaned name with class codes, e.g. "Regnskab (LA)"
        course_code:  Raw Canvas code, e.g. "BINTO1060U.LA_E25"
    """
    raw_name = (getattr(course, 'friendly_name', None)
                or getattr(course, 'name', '') or '')
    display_name = friendly_course_name(raw_name)
    code = getattr(course, 'course_code', '') or ''
    # Canvas often appends the course name to the code field, e.g.
    # "BINTO1078U.LA_E25 (Introduction to Information Systems)"
    # Strip everything from the first '(' to keep only the code.
    if '(' in code:
        code = code[:code.index('(')].strip()
    return display_name, code


def short_path(full_path: str) -> str:
    """Return just the folder name from a full path.

    Args:
        full_path: Full filesystem path

    Returns:
        Just the last component (folder name)
    """
    return Path(full_path).name or full_path


_MD_SPECIALS = re.compile(r"([\\`*_{}\[\]()#+\-.!~|<>$])")


def md_escape(text: str) -> str:
    """Neutralise Markdown in a string that will become a WIDGET LABEL.

    Streamlit renders ``st.button``/``st.checkbox``/``st.expander`` labels as
    Markdown, so any user-supplied text in one is markup. The failure is
    cosmetic but total and silent - the step tracker hit the same thing from the
    other side (CLAUDE.md): a label of ``1. Select Courses`` is an ORDERED LIST
    ITEM and Streamlit eats the ``1.`` entirely.

    Real names people give a course trip this constantly: "1. Semester",
    "Math_2", "Stats (week 1-3)", "**Important**". Escaping is the only way to
    show back exactly what they typed.

    This is NOT a substitute for :func:`esc` - it is the opposite problem.
    ``esc`` protects HTML; this protects Markdown. A string interpolated into
    ``unsafe_allow_html`` markup still needs ``esc``.
    """
    if not text:
        return text
    return _MD_SPECIALS.sub(r"\\\1", str(text))


def norm_folder_key(path) -> str:
    """Case- and separator-normalised folder key for pair-identity matching.

    A sync pair is identified by ``(course_id, local_folder)``, but the folder
    string reaching each consumer came from a different place: the daily set
    stores the string the user picked, sync history stores
    ``str(sync_manager.local_path)``, and the hub stores whatever the folder
    picker returned. Those describe the same folder while differing in
    separators, trailing slashes or (on Windows) case, so neither side can be
    compared raw.

    This is the ONE normaliser - ``ui.today_dashboard._norm_folder`` and
    ``core.pair_labels`` both route through it. Writing the rule twice is how
    two consumers of the same identity drift apart (the daily-list bug in
    CLAUDE.md is the worked example).
    """
    try:
        return os.path.normcase(os.path.normpath(str(path or "")))
    except Exception:
        return str(path or "")


# --- Progress Bar Helper ---

def render_progress_bar(container, current: int, total: int,
                        mode: str = 'files', mb_current: float = 0, mb_total: float = 0,
                        custom_text: str = None):
    """Render a styled progress bar using Streamlit's st.markdown.
    
    Args:
        container: Streamlit container to render into
        current: Current count (files downloaded)
        total: Total count (files to download)
        mode: 'files' for file count, 'mb' for MB, 'complete' for finished
        mb_current: Current MB downloaded (for 'mb' mode)
        mb_total: Total MB to download (for 'mb' mode)
        custom_text: Optional override for the status text (e.g. for complete mode)
    """
    from shared import theme
    # ONE clamp, imported rather than copied. `engine.progress_dashboard._pct` is
    # this app's rule for "a drawable percent" and carries the reasoning: the value
    # goes straight into `width: N%`, where -3 and nan are INVALID CSS, so the
    # browser drops the declaration and a block div falls back to the full track -
    # "less than nothing happened" renders identically to "finished". That
    # hardening reached `build_progress_bar_html` and not this function, which is
    # the OTHER live progress-bar renderer (sync/execution.py's three call sites).
    # Measured here before the fix: NaN raised ValueError, inf raised
    # OverflowError and None raised TypeError - from inside the sync run loop,
    # where the values arrive from counters owned by several subsystems.
    # Function-scoped: progress_dashboard imports `shared.theme`, so a
    # module-level import here would risk closing a cycle.
    from engine.progress_dashboard import _num, _pct

    if mode == 'complete':
        progress_pct = 100
        display_text = custom_text if custom_text else 'Done!'
        bar_color = theme.SUCCESS_ALT
    elif mode == 'complete_warning':
        progress_pct = 100
        display_text = custom_text if custom_text else 'Sync completed with errors.'
        bar_color = theme.WARNING
    elif mode == 'complete_error':
        progress_pct = 100
        display_text = custom_text if custom_text else 'Sync failed for all files.'
        bar_color = theme.ERROR_ALT
    elif mode == 'mb':
        _mb_cur, _mb_tot = _num(mb_current), _num(mb_total)
        progress_pct = _pct(_mb_cur / _mb_tot * 100) if _mb_tot > 0 else 0
        display_text = f'Downloading: {_mb_cur:.1f} / {_mb_tot:.1f} MB'
        bar_color = theme.ACCENT_BLUE
    else:  # files
        _cur, _tot = _num(current), _num(total)
        progress_pct = _pct(_cur / _tot * 100) if _tot > 0 else 0
        display_text = custom_text if custom_text else f'{progress_pct}%'
        bar_color = theme.ACCENT_BLUE
    
    progress_html = f'''
    <div style="background-color: {theme.BG_CARD}; border-radius: 8px; width: 100%; height: 24px; position: relative; margin-bottom: 10px;">
        <div style="background-color: {bar_color}; width: {progress_pct}%; height: 100%; border-radius: 8px; transition: width 0.3s ease;"></div>
        <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold;">
            {display_text}
        </div>
    </div>
    '''
    container.html(progress_html)


# --- Step Wizard ---
#
# Steps are identified by a STRING id, never by their position. Two things made
# the old integer contract untenable:
#   * the sync flow rendered the ANALYSIS phase and the REVIEW screen both as
#     "step 2", so the whole analysis phase sat under the label "Review
#     Changes" - it was describing a screen the user had not reached yet;
#   * Quick Sync never visits review at all (``sync/analysis.py`` jumps straight
#     to the sync), yet the tracker advertised it as the next thing to happen.
# An id also lets a step be INSERTED - the download flow's scan phase, which
# used to hide inside "Downloading" - without renumbering eleven call sites.
#
# Every glyph, colour and size lives in the "Step wizard" block of
# ``styles/global.css``, selected off each button's key. Nothing here injects
# CSS, and that is deliberate: a ``<style>`` element is a flex item in the page's
# vertical block (the ghost-box purge rule in global.css is inert - see
# CLAUDE.md), and this tracker is the FIRST element on six screens, so a single
# injection above it would push every one of them down by a full gap slot.

# (step id, label). Display numbers are the position + 1, so a skipped step
# still occupies its number - see ``render_wizard_step``.
SYNC_WIZARD_STEPS = [
    ('select',   'Select Courses'),
    ('analyze',  'Analyzing'),
    ('review',   'Review Changes'),
    ('sync',     'Download & Sync'),
    ('complete', 'Complete'),
]

DOWNLOAD_WIZARD_STEPS = [
    ('select',    'Select Courses'),
    ('configure', 'Configure Download'),
    ('analyze',   'Analyzing'),
    ('download',  'Downloading'),
    ('complete',  'Complete'),
]


def render_wizard_step(container, flow: str, steps: list, current: str,
                       *, nav: dict | None = None, skipped=()) -> None:
    """Render the horizontal step tracker as a row of native Streamlit buttons.

    No circles, no pill shape. Each step is [icon] N. Label. Separator lines
    flex-grow to fill the page width evenly.

    States (all painted from global.css off the button's key):
      done    - soft light-blue, slightly faded: "already visited"
      active  - cool near-white, bold, larger icon, drop-shadow glow
      idle    - medium-dark blue-grey: visible but clearly still ahead
      skipped - struck through: a step this MODE does not visit at all

    Why native buttons rather than the HTML this used to be
    ------------------------------------------------------
    Users try to click the previous step - so it has to be clickable, and the
    tracker was an ``st.html`` block, i.e. a shadow root that outside CSS and
    JS cannot reasonably reach. The obvious alternative - keep the HTML and have
    a ``components.html`` bridge click a hidden button - is a mechanism this
    codebase has already removed once for being silently unreliable (see the
    two-pass comment in ``sync_ui.py``): its iframe realm is destroyed on every
    rerun, and a dead bridge fails without a trace. A real button needs no
    bridge, is keyboard-reachable, and cannot fall out of sync with the page.

    Non-navigable steps are rendered ``disabled`` - they are INFORMATION, not
    controls the user has failed to unlock, which is why global.css exempts them
    from the app's disabled-button paint (the same exemption the card-header
    rerun locks carry).

    Args:
        container: the Streamlit container to render into (always ``st``).
        flow:      'sync' | 'download' - namespaces the widget keys.
        steps:     list of (step_id, label).
        current:   the id of the step in progress.
        nav:       {step_id: callable} for steps the user may click back to.
                   Wired as ``on_click``, so the handler mutates session state
                   and the click's own rerun does the rest - an explicit
                   ``st.rerun()`` here would render the page twice and drop the
                   browser's scroll anchor.
        skipped:   ids this run will never visit (Quick Sync skips 'review').
    """
    nav = nav or {}
    skipped = set(skipped)
    ids = [s[0] for s in steps]
    cur_idx = ids.index(current) if current in ids else 0

    slot = container.container(key=f"cd_wizard_{flow}")
    for idx, (step_id, label) in enumerate(steps):
        if step_id in skipped:
            state = 'skipped'
        elif idx < cur_idx:
            state = 'done'
        elif idx == cur_idx:
            state = 'active'
        else:
            state = 'idle'

        # The separator LEAVING a step tracks progress, not the skip: the line
        # after a skipped step still joins two steps the run has passed.
        lead = 'donesep' if idx < cur_idx else 'idlesep'

        # Only a settled, already-visited screen is a destination. The current
        # step is never a link to itself, and a running phase is left via Cancel.
        handler = nav.get(step_id) if idx < cur_idx else None

        # The backslash is load-bearing: a button label is MARKDOWN, and a bare
        # "1. Select Courses" is an ordered-list item - Streamlit swallowed the
        # number and rendered just the label. `1\.` is the CommonMark escape.
        text = (f"{idx + 1}\\. ~~{label}~~ (skipped)" if state == 'skipped'
                else f"{idx + 1}\\. {label}")

        # The key carries the step id AND the state: that is what lets the whole
        # stylesheet be static (see the note above about injecting CSS here).
        slot.button(
            text,
            key=f"cd_wiz_{flow}_{idx}_{step_id}_st_{state}_{lead}",
            disabled=handler is None,
            on_click=handler,
            use_container_width=False,
        )


def render_sync_wizard(container, current: str, *, nav: dict | None = None,
                       quick: bool | None = None) -> None:
    """Render the wizard for the Sync flow.

    ``quick`` defaults to the live Quick Sync flag. On step 1 the mode has not
    been chosen yet and the flag is absent, so every phase is shown - which is
    the point: the tracker states what the flow CAN do before it states what
    this particular run will do.
    """
    if quick is None:
        import streamlit as st
        quick = bool(st.session_state.get('sync_quick_mode'))
    render_wizard_step(container, 'sync', SYNC_WIZARD_STEPS, current,
                       nav=nav, skipped=('review',) if quick else ())


def render_download_wizard(container, current: str, *, nav: dict | None = None) -> None:
    """Render the wizard for the Download flow."""
    render_wizard_step(container, 'download', DOWNLOAD_WIZARD_STEPS, current, nav=nav)


# --- CBS Metadata Parser ---

def parse_cbs_metadata(raw_name: str) -> dict:
    """Extract CBS-specific metadata from course name.
    
    Expected patterns in parenthetical blocks:
    - Class Type: L* (Lecture) or X* (Exercise) -> e.g. LA, XB
    - Semester/Year: E[YY] (Autumn 20YY) or F[YY] (Spring 20YY) -> e.g. E25, F26
    
    Returns:
        dict with keys: 'type', 'semester', 'year', 'year_full'
        Values are None if not found.
    """
    if not raw_name:
        return {'type': 'Other', 'semester': None, 'year': None}
        
    meta = {
        'type': 'Other', # Default to Other if no L/X found
        'semester': None,
        'year': None,
        'year_full': None
    }
    
    # Look for patterns in the whole string, but prioritized match
    # Regex for Class Type: Word boundary, starts with L or X, followed by 1 uppercase letter
    # We look for "LA", "XB", etc.
    type_match = re.search(r'\b([LX])[A-Z]\b', raw_name)
    if type_match:
        code = type_match.group(1)
        if code == 'L':
            meta['type'] = 'Lecture'
        elif code == 'X':
            meta['type'] = 'Exercise'
            
    # Regex for Semester/Year: Word boundary, starts with E or F, followed by 2 digits
    # E25 = Autumn 2025, F26 = Spring 2026
    sem_match = re.search(r'\b([EF])(\d{2})\b', raw_name)
    if sem_match:
        sem_code = sem_match.group(1)
        year_short = sem_match.group(2)
        
        meta['semester'] = 'Autumn' if sem_code == 'E' else 'Spring'
        meta['year'] = year_short
        meta['year_full'] = f"20{year_short}"

    return meta


# ── Effective (post-conversion) file type ────────────────────────────────────
# One source of truth for "what extension will this Canvas file have ON DISK
# once this course's post-processing contract has run". Every sync surface
# (Smart Select pills, review row tags, the Confirm Sync dialog) must show THIS
# type, never the raw Canvas type: a course that converts pptx→pdf downloads a
# .pptx but the user only ever sees/keeps a .pdf, and mixing the two labels in
# one screen (PPTX in Smart Select, PDF on the same file's row) reads as a bug
# and destroys trust. Ext sets mirror the converter dispatch in
# sync/execution.py + converters/post_processing.py exactly - update BOTH when
# a converter's coverage changes. (Archives and .url/.webloc shortcuts keep
# their extension: extraction/compilation has no 1:1 product file.)

_EFFECTIVE_EXT_MAP = (
    ('convert_pptx',  {'.ppt', '.pptx', '.pptm', '.pot', '.potx'}, '.pdf'),
    ('convert_word',  {'.doc', '.rtf', '.odt'},                    '.pdf'),
    ('convert_excel', {'.xlsx', '.xls', '.xlsm'},                  '.pdf'),
    ('convert_video', {'.mp4', '.mov', '.mkv', '.avi', '.m4v'},    '.mp3'),
    ('convert_html',  {'.html'},                                   '.md'),
)


def effective_ext(filename: str, contract: dict | None) -> str:
    """The lowercase extension *filename* will have on disk after conversion.

    ``contract`` is the course's sync contract (``res_data['contract']``). A
    key missing from the contract falls back to the session's persistent
    toggle - the same fallback the execution engine applies - so the display
    always matches what post-processing will actually do. Returns the original
    extension when no enabled converter claims it ('' for extension-less
    names).
    """
    ext = os.path.splitext(filename or '')[1].lower()
    if not ext:
        return ext
    contract = contract or {}

    def _enabled(key: str) -> bool:
        val = contract.get(key)
        if val is None:
            try:
                import streamlit as st
                val = st.session_state.get(f'persistent_{key}', False)
            except Exception:
                val = False
        return bool(val)

    for _key, _exts, _target in _EFFECTIVE_EXT_MAP:
        if ext in _exts:
            return _target if _enabled(_key) else ext
    if _enabled('convert_code'):
        try:
            from converters.code import CODE_EXTENSIONS
        except Exception:
            CODE_EXTENSIONS = ()
        if ext in CODE_EXTENSIONS:
            return '.txt'
    return ext




# ── Cross-run ETA calibration ───────────────────────────────────────────────
# The estimator learns this machine's per-item overhead and sustained transfer
# rate during a run. Those numbers are far better starting points for the NEXT
# phase or run than the module's generic defaults, and carrying them forward is
# the difference between a first estimate that is roughly right and one that
# has to converge from scratch every single time. Session-scoped on purpose:
# these describe the current network and machine, not a durable preference, so
# persisting them to disk would just let a stale campus-wifi number follow the
# user home.

# --- What went WRONG vs what Canvas simply will not serve --------------------
#
# Two of the outcomes a download or sync can produce are not failures at all:
# a file the teacher locked, and a video Canvas streams through a plugin rather
# than storing as a file. No retry, no setting and no amount of waiting changes
# either - they are the state of the course, not of the run.
#
# Both flows must agree about this or the same course reports differently
# depending on how the user reached it, so the rule lives here once. The
# messages are CONSTANTS because the sync flow's errors are plain strings and
# the classifier has to recognise them: with the text inlined at the producer,
# rewording it would silently reclassify every locked file as a hard failure.
LOCKED_FILE_REASON = "Locked by the teacher on Canvas (not downloadable)"
LTI_STREAM_REASON = "LTI/Media Stream (Cannot directly download)"

# The download flow carries objects rather than strings; these are the
# ``error_type`` values its engine stamps for the same two outcomes.
LOCKED_FILE_ERROR_TYPE = "Locked File"
LTI_STREAM_ERROR_TYPE = "LTI/Media Stream"

#: Extensions that mark a URL-less Canvas file as a STREAM rather than a failure.
#:
#: When Canvas serves a file with no download URL, the two engines decide from
#: the extension whether this is "a video the plugin streams" (a permanent fact
#: about the course - no retry, setting or wait can ever fetch it) or a genuine
#: failure. That verdict feeds ``LTI_STREAM_REASON`` / ``LTI_STREAM_ERROR_TYPE``
#: above, which the completion screen classifies to decide what to colour as an
#: error - so getting it wrong reports the app as broken for something Canvas
#: simply declined to hand over.
#:
#: It lives HERE, beside the two constants it selects, because it was written
#: TWICE - ``core.canvas_logic`` (download) and ``sync.execution`` (sync) - and
#: the copies had already drifted: both omitted ``.m4v`` while the size-mismatch
#: tolerance in ``core.canvas_logic`` lists it as media, so an ``.m4v`` stream
#: was counted as a hard failure in both engines. The message and the error type
#: were unified into this module long ago; the predicate that chooses them was
#: left behind, which is the same "a rule written more than once" shape that
#: ``make_long_path`` and the three AppleScript escapers already cost this repo.
LTI_STREAM_EXTENSIONS = frozenset({
    '.mp4', '.mov', '.avi', '.mkv', '.mp3', '.m4v',
})


def is_lti_stream_ext(name_or_ext: str) -> bool:
    """True when a URL-less Canvas file of this name is a streamed medium.

    Accepts a full filename or a bare extension. Case-insensitive, because
    Canvas serves ``.MP4`` as readily as ``.mp4``.
    """
    if not name_or_ext:
        return False
    s = str(name_or_ext).lower()
    dot = s.rfind('.')
    return (s if dot < 0 else s[dot:]) in LTI_STREAM_EXTENSIONS

# A Panopto recording whose session Panopto reports as gone (deleted or moved).
# It is the SAME kind of outcome as the two above - a permanent fact about the
# course, not a failure of the run: no retry, setting or wait brings it back.
# Counting it as a failure made a Today quick-sync that hit two deleted lectures
# render amber "Sync Completed with Errors", the colour that is supposed to mean
# "look at this". The producer (panopto.stream.friendly_stream_error) returns
# this exact REASON string; the download flow stamps this ERROR_TYPE on the
# DownloadError object, so both shapes classify identically.
PANOPTO_UNAVAILABLE_REASON = ("This Panopto recording is no longer available - "
                              "it may have been deleted or moved.")
PANOPTO_UNAVAILABLE_ERROR_TYPE = "Recording No Longer Available"


def declined_reason_sentence(reasons: dict, total: int = 0) -> str:
    """Name WHY Canvas would not serve these items, in one sentence.

    A bare "3 Cannot Be Downloaded" reads as an unexplained loss; naming the
    cause turns it into a fact the user can dismiss. It lives here, not at
    either call site, because the same sentence has to appear identically
    whichever screen the user reached - and because the counts arrive from
    ``split_delivery_errors``, which is the one classifier both flows share.

    ``total`` is the fallback when the reasons dict is empty or unrecognised:
    we would rather say "Canvas will not serve 3 items" than invent a cause we
    did not measure.
    """
    reasons = reasons or {}
    locked = int(reasons.get('locked', 0) or 0)
    stream = int(reasons.get('stream', 0) or 0)
    unavailable = int(reasons.get('unavailable', 0) or 0)
    other = int(reasons.get('other', 0) or 0)
    bits = []
    if locked:
        bits.append(f"{locked} {'file is' if locked == 1 else 'files are'} locked "
                    f"by your teacher on Canvas")
    if stream:
        bits.append(f"{stream} {'video is' if stream == 1 else 'videos are'} "
                    f"streamed through a Canvas plugin and cannot be saved as a file")
    if unavailable:
        bits.append(f"{unavailable} Panopto {'recording is' if unavailable == 1 else 'recordings are'} "
                    f"no longer available (deleted or moved)")
    if other or not bits:
        n = other or total or (locked + stream + unavailable)
        bits.append(f"Canvas will not serve {n} {'item' if n == 1 else 'items'}")
    joined = bits[0] if len(bits) == 1 else "; ".join(bits)
    return (joined[0].upper() + joined[1:]
            + ". Nothing is missing that could have been fetched.")


def split_delivery_errors(errors) -> dict:
    """Split a run's errors into what failed and what was merely declined.

    Accepts either the download flow's ``DownloadError`` objects or the sync
    flow's ``list[str]`` messages, because the two flows genuinely carry
    different shapes and the alternative is two copies of this rule that drift.

    Returns ``{'retriable', 'unresolvable', 'app', 'reasons': {...}}``:

    * **retriable** - failed, and a retry could plausibly succeed (network,
      HTTP, a locked destination). These colour the completion card.
    * **app** - the engine itself broke. These colour the card too.
    * **unresolvable** - Canvas declined to serve it. Reported, never coloured;
      ``reasons`` breaks it down so the screen can say WHICH, because a bare
      count reads as an unexplained loss.
    """
    out = {'retriable': 0, 'unresolvable': 0, 'app': 0,
           'reasons': {'locked': 0, 'stream': 0, 'unavailable': 0, 'other': 0}}
    for err in (errors or []):
        if isinstance(err, str):
            if LOCKED_FILE_REASON in err:
                out['unresolvable'] += 1
                out['reasons']['locked'] += 1
            elif LTI_STREAM_REASON in err:
                out['unresolvable'] += 1
                out['reasons']['stream'] += 1
            elif PANOPTO_UNAVAILABLE_REASON in err:
                out['unresolvable'] += 1
                out['reasons']['unavailable'] += 1
            else:
                out['retriable'] += 1
            continue

        if not hasattr(err, 'error_type'):
            # An entry this function cannot read - a dict, or some future shape.
            # `app.py` already guards for `isinstance(err, dict)` in the retry
            # pass, so it is not hypothetical.
            #
            # Counted as a FAILURE, deliberately. The two mistakes are not
            # symmetric: calling a harmless outcome a failure shows an amber
            # card the user investigates and dismisses, while calling a failure
            # harmless hides it behind a green one. When the shape cannot be
            # read, the safe guess is the loud one.
            out['retriable'] += 1
            continue

        if getattr(err, 'is_app_error', False):
            out['app'] += 1
            continue

        etype = getattr(err, 'error_type', '') or ''
        ctx = getattr(err, 'context', None)
        if etype == LOCKED_FILE_ERROR_TYPE:
            out['unresolvable'] += 1
            out['reasons']['locked'] += 1
        elif etype == LTI_STREAM_ERROR_TYPE:
            out['unresolvable'] += 1
            out['reasons']['stream'] += 1
        elif etype == PANOPTO_UNAVAILABLE_ERROR_TYPE:
            out['unresolvable'] += 1
            out['reasons']['unavailable'] += 1
        elif isinstance(ctx, dict) and ctx.get('filepath') \
                and not getattr(err, 'retry_exhausted', False):
            # A real file failure with somewhere to retry TO.
            out['retriable'] += 1
        else:
            # Permanently stuck, but not one of the two named causes - e.g. a
            # module item Canvas exposes with no URL at all. Counted as
            # unresolvable (a retry cannot help) but reported generically,
            # because claiming a cause we have not established would be worse
            # than admitting we do not know.
            out['unresolvable'] += 1
            out['reasons']['other'] += 1
    return out


_ETA_PRIORS_KEY = '_eta_learned_transfer_priors'


def learned_transfer_priors() -> dict:
    """Priors measured by an earlier transfer in this session (``{}`` if none)."""
    try:
        import streamlit as st
        priors = st.session_state.get(_ETA_PRIORS_KEY) or {}
        return dict(priors) if isinstance(priors, dict) else {}
    except Exception:
        return {}


def remember_transfer_priors(estimator) -> None:
    """Store what *estimator* measured, for the next transfer to start from.

    A no-op when the estimator never gathered real evidence - otherwise a phase
    that finished before it learned anything would pass its own defaults on as
    if they had been measured.
    """
    try:
        priors = estimator.export_priors()
        if not priors:
            return
        import streamlit as st
        st.session_state[_ETA_PRIORS_KEY] = priors
    except Exception as e:
        logger.debug(f"remember_transfer_priors skipped: {e}")
