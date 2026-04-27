"""
engine.notifications — Cross-platform completion notification helper.

Plays a short, non-blocking system sound AND shows a native OS notification
to signal that a long-running download or sync has finished, so users who
tabbed out can tell.

Call ``play_completion_beep(mode, summary)`` at the moment a download/sync
transitions to its terminal state. Everything is dispatched on daemon threads
so it never blocks the Streamlit script runner.
"""

from __future__ import annotations

import logging
import platform
import threading
import sys
import os

system = platform.system()

# ── Windows Dependencies ──
if system == 'Windows':
    try:
        import winsound
    except ImportError:
        winsound = None
        
    try:
        import ctypes
    except ImportError:
        ctypes = None
        
    try:
        from win11toast import toast
    except ImportError:
        toast = None

# ── macOS Dependencies ──
if system == 'Darwin':
    import subprocess

logger = logging.getLogger(__name__)


# ── Windows ───────────────────────────────────────────────────────────

def _play_windows_sound():
    """Play the Windows Notify Calendar chime (a pleasant, recognizable ding)."""
    if winsound is None:
        logger.debug("winsound not available — skipping completion sound")
        return

    try:
        sound_path = r"C:\Windows\Media\Windows Notify Calendar.wav"
        if os.path.exists(sound_path):
            winsound.PlaySound(
                sound_path, 
                winsound.SND_FILENAME | winsound.SND_NODEFAULT | winsound.SND_ASYNC
            )
        else:
            # Safe fallback: standard positive ding
            winsound.MessageBeep(winsound.MB_OK)
    except Exception as e:
        logger.debug(f"Windows completion sound failed: {e}")


def _focus_canvas_window():
    """Bring the PyWebView 'Canvas Downloader' window to the foreground."""
    if ctypes is None:
        logger.debug("ctypes not available — skipping window focus")
        return

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "Canvas Downloader")
        if hwnd:
            SW_RESTORE = 9
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
    except Exception as e:
        logger.debug(f"Failed to focus Canvas Downloader window: {e}")


def _show_windows_toast(title: str, body: str):
    """Display a native Windows 10/11 toast notification.

    - Reverted app_id to 'Canvas Downloader' because Windows 11 blocks header icons for
      portable executables without a registered Start Menu shortcut.
    - Added an inline body icon (`appLogoOverride`) utilizing the local assets folder.
    - Audio is silenced because we already play our own sound via winsound.
    - On click, focuses the existing PyWebView 'Canvas Downloader' window.
    """
    if toast is None:
        logger.debug("win11toast not installed — skipping native notification")
        return

    try:
        # Resolve absolute path to the app's icon
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            
        icon_path = os.path.join(base_dir, 'assets', 'icon.png')
        
        kwargs = {
            'app_id': 'Canvas Downloader',
            'audio': {'silent': 'true'},
            'on_click': lambda _args: _focus_canvas_window(),
            'on_dismissed': lambda _args: None,
            'on_failed': lambda _args: None,
        }
        
        # Inject the body icon if the asset exists
        if os.path.exists(icon_path):
            kwargs['icon'] = {
                'src': icon_path,
                'placement': 'appLogoOverride',
                'hint-crop': 'none'
            }

        toast(title, body, **kwargs)
    except Exception as e:
        logger.debug(f"Windows toast notification failed: {e}")


def _windows_notify(title: str, body: str):
    """Play the completion sound AND show a native toast on Windows."""
    _play_windows_sound()
    _show_windows_toast(title, body)


# ── macOS ─────────────────────────────────────────────────────────────

def _play_macos_sound():
    """macOS: afplay the Glass chime (a pleasant stock system sound)."""
    try:
        subprocess.Popen(
            ['afplay', '/System/Library/Sounds/Glass.aiff'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.debug(f"macOS completion sound failed: {e}")


def _show_macos_notification(title: str, body: str):
    """Display a native macOS Notification Center notification via osascript."""
    try:
        # Escape double quotes in strings for AppleScript safety
        safe_title = title.replace('"', '\\"')
        safe_body = body.replace('"', '\\"')
        script = (
            f'display notification "{safe_body}" '
            f'with title "Canvas Downloader" '
            f'subtitle "{safe_title}"'
        )
        subprocess.Popen(
            ['osascript', '-e', script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.debug(f"macOS notification failed: {e}")


def _macos_notify(title: str, body: str):
    """Play the completion chime AND show a Notification Center alert on macOS."""
    _play_macos_sound()
    _show_macos_notification(title, body)


# ── Public API ────────────────────────────────────────────────────────

def play_completion_beep(
    mode: str = 'download',
    summary: str = '',
) -> None:
    """Fire the native completion sound + notification without blocking.

    Parameters
    ----------
    mode : str
        Either ``'download'`` or ``'sync'``. Used to build the notification
        title if no explicit *summary* is given.
    summary : str
        Human-readable body text for the notification popup, e.g.
        ``"Downloaded 42 files across 3 courses"``.  If empty, a generic
        message is used.

    Safe to call from the main Streamlit thread or from async contexts.
    Any failure is logged at debug level — notifications are a polish
    feature and must never interrupt download/sync lifecycle.
    """
    if mode == 'sync':
        title = 'Sync Complete'
    elif mode == 'sync_review':
        title = 'Sync Review Ready'
    elif mode == 'sync_uptodate':
        title = 'Sync done! All files up to date'
    elif mode == 'quick_sync_uptodate':
        title = 'Quick Sync done! All files up to date'
    else:
        title = 'Download Complete'

    body = summary or (
        'Your files are ready.' if mode == 'download'
        else 'Your courses are up to date.' if mode == 'sync'
        else 'All files are already synced — nothing to download.' if mode in ('sync_uptodate', 'quick_sync_uptodate')
        else 'Course analysis completed. Waiting for your review.'
    )

    system = platform.system()
    if system == 'Windows':
        worker = lambda: _windows_notify(title, body)
    elif system == 'Darwin':
        worker = lambda: _macos_notify(title, body)
    else:
        return  # Linux/other: silent (app is not shipped there)

    try:
        threading.Thread(target=worker, daemon=True).start()
    except Exception as e:
        logger.debug(f"Failed to dispatch completion notification thread: {e}")
