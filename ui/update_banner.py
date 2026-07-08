"""
ui.update_banner - In-app "Update available" notice.

A single GitHub Releases API call is made once per app launch, on a daemon
thread (never blocks startup, never blocks interpreter exit). If the published
release is newer than the bundled ``version.__version__``, a small notice is
rendered in the sidebar linking to the website's Downloads & Releases page.

Design notes:
  - The check is fully best-effort: offline, rate-limited, or any other failure
    simply yields "no update" and no banner (never an error to the user).
  - State lives on a module-global guarded by a lock - NOT in st.session_state -
    because the worker runs on a background thread and Streamlit forbids touching
    session_state from other threads. The banner reads the global on each rerun.
  - The same releases page is linked for every distribution channel (Inno .exe,
    macOS .dmg, and the Microsoft Store MSIX). The page itself surfaces the Store
    badge for Windows, so Store users land on the right place.
  - The banner is dismissible. Dismissal is keyed to the exact release tag and
    persisted to disk (in get_config_dir(), alongside the other small per-user
    JSON files), so closing it stays closed across app restarts and only clears
    itself once a *newer* release ships - matching "closeable, reappears on the
    next version bump" rather than a per-session snooze.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from html import escape as _he

import streamlit as st

from version import __version__

logger = logging.getLogger(__name__)

# api.github.com/.../releases/latest excludes drafts and pre-releases by default,
# so we only ever nag about a release explicitly marked "latest".
_GITHUB_API = "https://api.github.com/repos/birkls/Canvas_LMS_batch_file_downloader/releases/latest"
RELEASES_PAGE = "https://birkls.github.io/Canvas_LMS_batch_file_downloader/releases.html"

_state: dict = {"checked": False, "latest": None, "update_available": False}
_lock = threading.Lock()
_started = False

# Dismissal - separate from _state above (that dict is wholesale-replaced by
# the worker thread every run; keeping dismissal on its own globals means the
# worker can never clobber it). Loaded lazily from disk once per process.
_dismissed_loaded = False
_dismissed_version: str | None = None


def _numeric_tuple(v: str) -> tuple:
    """Dumb-but-total version key: every digit run in order, e.g.
    ``"2.1.0-beta3"`` -> ``(2, 1, 0, 3)``. Never raises."""
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums) if nums else (0,)


def _is_newer(remote: str, local: str) -> bool:
    """True when *remote* is a strictly newer version than *local*.

    Both strings are parsed through the SAME scheme: ``packaging.Version`` for
    both, else numeric tuples for both. Parsing them independently (the old
    behaviour) could yield a ``Version`` on one side and a ``tuple`` on the
    other - e.g. a well-formed GitHub tag vs. a malformed local dev version -
    and ``Version > tuple`` raises ``TypeError``, silently killing the banner.
    """
    try:
        from packaging.version import Version
        return Version(remote) > Version(local)  # both or neither
    except Exception:
        return _numeric_tuple(remote) > _numeric_tuple(local)


def _worker() -> None:
    global _state
    result = {"checked": True, "latest": None, "update_available": False}
    try:
        import requests
        resp = requests.get(
            _GITHUB_API,
            timeout=4,
            headers={"Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        tag = (resp.json().get("tag_name") or "").lstrip("vV").strip()
        if tag:
            result["latest"] = tag
            # Only flag an update when the remote is strictly newer. Equal (or a
            # dev build whose local version is ahead of the last release) shows
            # nothing - this is exactly why a naive equality/inequality check
            # would mis-fire while local is 2.0.0 and the newest release is 1.0.0.
            result["update_available"] = _is_newer(tag, __version__)
    except Exception as e:  # noqa: BLE001 - any failure = silently no banner
        logger.info(f"Update check skipped: {e}")
    with _lock:
        _state = result


def ensure_update_check() -> None:
    """Kick off the background update check once per process. Idempotent and
    non-blocking - safe to call on every sidebar render."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_worker, daemon=True, name="update-check").start()


def _get_info() -> dict:
    with _lock:
        return dict(_state)


def _dismiss_state_path() -> str:
    from shared.helpers import get_config_dir
    return os.path.join(get_config_dir(), "update_banner_dismissed.json")


def _load_dismissed_version() -> None:
    """Populate _dismissed_version from disk, once per process (best-effort)."""
    global _dismissed_loaded, _dismissed_version
    with _lock:
        if _dismissed_loaded:
            return
        _dismissed_loaded = True
    version = None
    try:
        with open(_dismiss_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        version = (data.get("dismissed_version") or "").strip() or None
    except Exception:
        version = None
    with _lock:
        _dismissed_version = version


def _dismiss_version(version: str) -> None:
    """Persist *version* as dismissed - the banner stays hidden until a newer tag ships."""
    global _dismissed_version
    with _lock:
        _dismissed_version = version
    try:
        path = _dismiss_state_path()
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"dismissed_version": version}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception as e:  # noqa: BLE001 - best-effort; in-memory dismissal still applies
        logger.info(f"Could not persist dismissed update banner state: {e}")


def _is_dismissed(latest: str) -> bool:
    _load_dismissed_version()
    with _lock:
        return bool(latest) and _dismissed_version == latest


def render_update_banner() -> None:
    """Render the sidebar 'Update available' notice if a newer release exists
    and the user hasn't already dismissed that exact release.

    Renders nothing when no update is available, the check hasn't finished, or
    this release was already dismissed. The visual card is a self-contained
    st.html block (scoped <style> + anchor, isolated in the component shadow
    root so it neither leaks CSS nor is reachable by page CSS); the dismiss
    "x" is a real st.button - shadow-root content can't talk back to Python,
    so it has to live outside the st.html block - absolutely positioned over
    the card's top-right corner via a keyed wrapper container.
    """
    info = _get_info()
    if not info.get("update_available"):
        return

    latest_raw = info.get("latest") or ""
    if _is_dismissed(latest_raw):
        return

    latest = _he(latest_raw)
    href = RELEASES_PAGE

    # Hoisted above the container per project convention: Streamlit can drop
    # <style> payloads injected below/inside nested containers. st.markdown
    # (not st.html) so the ghost element-container collapses instead of
    # eating a flex gap slot in the sidebar's vertical block.
    st.markdown("""
<style>
section[data-testid="stSidebar"] div[class*="st-key-update_banner_box"] {
    position: relative !important;
}
section[data-testid="stSidebar"] div[class*="st-key-update_banner_box"] div.st-key-update_banner_dismiss {
    position: absolute !important;
    top: 18px !important;
    right: 22px !important;
    width: 20px !important;
    min-width: 20px !important;
    margin: 0 !important;
    z-index: 2;
}
section[data-testid="stSidebar"] div[class*="st-key-update_banner_box"] div.st-key-update_banner_dismiss button {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
    width: 20px !important;
    height: 20px !important;
    min-height: 20px !important;
    min-width: 20px !important;
    padding: 0 !important;
    border-radius: 5px !important;
    margin: 0 !important;
    position: relative !important;
}
section[data-testid="stSidebar"] div[class*="st-key-update_banner_box"] div.st-key-update_banner_dismiss button > div {
    display: none !important;
}
section[data-testid="stSidebar"] div[class*="st-key-update_banner_box"] div.st-key-update_banner_dismiss button::before {
    content: '';
    position: absolute !important;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 11px;
    height: 11px;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2393b4d8' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'%3E%3Cline x1='18' y1='6' x2='6' y2='18'%3E%3C/line%3E%3Cline x1='6' y1='6' x2='18' y2='18'%3E%3C/line%3E%3C/svg%3E") !important;
    background-position: center !important;
    background-repeat: no-repeat !important;
    background-size: contain !important;
    transition: filter 0.15s ease;
}
section[data-testid="stSidebar"] div[class*="st-key-update_banner_box"] div.st-key-update_banner_dismiss button:hover {
    background: rgba(255, 255, 255, 0.14) !important;
}
section[data-testid="stSidebar"] div[class*="st-key-update_banner_box"] div.st-key-update_banner_dismiss button:hover::before {
    filter: brightness(0) invert(1);
}
</style>
""", unsafe_allow_html=True)

    with st.container(key="update_banner_box"):
        # Bottom padding is 8px shorter than top to cancel out the separator
        # hr's own 8px margin-top below - keeps the visual gap above the card
        # (to Settings) equal to the gap below it (to the hr).
        st.html(f"""
<div style="padding: 10px 1rem 2px 20px;">
  <a class="cd-update-banner" href="{href}" target="_blank" rel="noopener" title="Open the downloads page">
    <span class="cd-up-icon">
      <span class="cd-up-glyph"></span>
      <span class="cd-up-dot"></span>
    </span>
    <span class="cd-up-text">
      <span class="cd-up-title">Update available</span>
      <span class="cd-up-sub">Version {latest} &middot; download</span>
    </span>
  </a>
</div>
<style>
  .cd-update-banner {{
    display: flex;
    align-items: center;
    gap: 11px;
    width: 100%;
    box-sizing: border-box;
    padding: 10px 30px 10px 12px;
    border-radius: 10px;
    text-decoration: none;
    background: rgba(31, 119, 180, 0.12);
    border: 1px solid rgba(96, 165, 250, 0.38);
    transition: background-color 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
  }}
  .cd-update-banner:hover {{
    background: rgba(31, 119, 180, 0.20);
    border-color: rgba(96, 165, 250, 0.65);
    box-shadow: 0 4px 16px rgba(31, 119, 180, 0.18);
  }}
  .cd-up-icon {{
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }}
  .cd-up-glyph {{
    display: inline-block;
    width: 16px;
    height: 16px;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2360a5fa' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/%3E%3Cpolyline points='7 10 12 15 17 10'/%3E%3Cline x1='12' y1='15' x2='12' y2='3'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: center;
    background-size: contain;
  }}
  .cd-up-dot {{
    position: absolute;
    top: -3px;
    right: -3px;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #68d4a3;
    box-shadow: 0 0 0 2px rgba(31, 119, 180, 0.0), 0 0 8px 1px rgba(104, 212, 163, 0.85);
    animation: cd-up-pulse 2s ease-in-out infinite;
  }}
  @keyframes cd-up-pulse {{
    0%, 100% {{ box-shadow: 0 0 6px 0px rgba(104, 212, 163, 0.55); }}
    50%      {{ box-shadow: 0 0 10px 2px rgba(104, 212, 163, 0.95); }}
  }}
  .cd-up-text {{
    display: flex;
    flex-direction: column;
    line-height: 1.25;
    min-width: 0;
  }}
  .cd-up-title {{
    color: #dbeafe;
    font-size: 0.9rem;
    font-weight: 600;
  }}
  .cd-up-sub {{
    color: #93b4d8;
    font-size: 0.72rem;
    font-weight: 500;
  }}
</style>
""")

        if st.button("​", use_container_width=False, key="update_banner_dismiss"):
            _dismiss_version(latest_raw)
            st.rerun(scope="app")
