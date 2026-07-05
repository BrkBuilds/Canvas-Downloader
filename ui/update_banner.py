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
"""

from __future__ import annotations

import logging
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


def render_update_banner() -> None:
    """Render the sidebar 'Update available' notice if a newer release exists.

    Renders nothing when no update is available (or the check hasn't finished).
    Self-contained st.html block: scoped <style> + anchor card, isolated in the
    component shadow root so it neither leaks CSS nor is reachable by page CSS.
    """
    info = _get_info()
    if not info.get("update_available"):
        return

    latest = _he(info.get("latest") or "")
    href = RELEASES_PAGE

    st.html(f"""
<div style="padding: 0 1rem 0 20px;">
  <a class="cd-update-banner" href="{href}" target="_blank" rel="noopener" title="Open the downloads page">
    <span class="cd-up-icon">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="2.2"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="7 10 12 15 17 10"/>
        <line x1="12" y1="15" x2="12" y2="3"/>
      </svg>
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
    padding: 10px 12px;
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
