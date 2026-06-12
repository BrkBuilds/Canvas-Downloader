"""
engine.notifications - Cross-platform completion notification helper.

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
    except Exception:
        toast = None

# ── macOS Dependencies ──
if system == 'Darwin':
    import subprocess
    try:
        from pync import Notifier as _PyncNotifier
    except ImportError:
        _PyncNotifier = None

logger = logging.getLogger(__name__)

_WINDOWS_AUMID = 'CanvasDownloader.App'

# AppId portion of the MSIX package AUMID. MUST stay in sync with the
# <Application Id="..."> value in msix/AppxManifest.template.xml.
_MSIX_APP_ID = 'CanvasDownloader'

_msix_pfn_cached = False
_msix_pfn = None


def _is_packaged() -> bool:
    return getattr(sys, 'frozen', False)


def _get_package_family_name():
    """Return this process's MSIX PackageFamilyName, or None when unpackaged.

    Distinguishes the Microsoft Store (MSIX) build from the standalone Inno Setup
    build: both are PyInstaller-frozen (so ``_is_packaged()`` is True for both),
    but only the Store build runs inside a package. Result is cached. Always None
    on non-Windows or on any API error, so the unpackaged code path is unaffected.
    """
    global _msix_pfn_cached, _msix_pfn
    if _msix_pfn_cached:
        return _msix_pfn
    _msix_pfn_cached = True

    if system != 'Windows' or ctypes is None:
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        length = ctypes.c_uint32(0)
        APPMODEL_ERROR_NO_PACKAGE = 15700
        rc = kernel32.GetCurrentPackageFamilyName(ctypes.byref(length), None)
        if rc == APPMODEL_ERROR_NO_PACKAGE:
            return None  # standalone / CLI build
        buf = ctypes.create_unicode_buffer(length.value)
        if kernel32.GetCurrentPackageFamilyName(ctypes.byref(length), buf) != 0:
            return None
        _msix_pfn = buf.value
        return _msix_pfn
    except Exception:
        return None


# ── Windows ───────────────────────────────────────────────────────────

def _play_windows_sound():
    """Play the Windows Notify Calendar chime (a pleasant, recognizable ding)."""
    if winsound is None:
        logger.debug("winsound not available - skipping completion sound")
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
    if system != 'Windows' or ctypes is None:
        logger.debug("ctypes not available - skipping window focus")
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


def _ensure_aumid_registered(icon_path: str = ''):
    """Register the AUMID in HKCU so Windows attributes notifications to Canvas Downloader.

    Without a registered AUMID, Windows tries to activate an unknown app on
    notification click, which can foreground whatever window it finds (e.g. Notion).
    Writing to HKCU works for per-user installs without elevation.
    """
    try:
        import winreg
        key_path = f'SOFTWARE\\Classes\\AppUserModelId\\{_WINDOWS_AUMID}'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, 'DisplayName', 0, winreg.REG_SZ, 'Canvas Downloader')
            if icon_path and os.path.exists(icon_path):
                winreg.SetValueEx(key, 'IconUri', 0, winreg.REG_SZ, icon_path)
    except Exception as e:
        logger.debug(f"AUMID registration failed: {e}")


def _show_windows_toast(title: str, body: str):
    """Display a native Windows 10/11 toast notification.

    MSIX (Store) build: attributes the toast via the package's own AUMID
    (PackageFamilyName!AppId) so Windows shows the manifest DisplayName
    "Canvas Downloader", and focuses the PyWebView window on click.

    Standalone (Inno Setup) build: registers a custom HKCU AUMID, attributes the
    toast to Canvas Downloader, and focuses the window on click.

    CLI mode: omits app_id entirely so Windows never tries to activate an
    unregistered AUMID (which was causing random apps like Notion to foreground).
    Clicking the notification in CLI mode does nothing, which is intentional.
    """
    if toast is None:
        logger.debug("win11toast not installed - skipping native notification")
        return

    try:
        if _is_packaged():
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

        icon_path = os.path.join(base_dir, 'assets', 'icon.png')

        kwargs = {
            'audio': {'silent': 'true'},
            'on_dismissed': lambda _args: None,
            'on_failed': lambda _args: None,
        }

        pfn = _get_package_family_name()
        if pfn:
            # MSIX (Store) build: use the package's own AUMID so Windows shows
            # the manifest DisplayName "Canvas Downloader". A custom AUMID here
            # makes Windows fall back to the raw package family name. HKCU AUMID
            # registration is skipped — it is virtualized and ignored in-package.
            kwargs['app_id'] = f'{pfn}!{_MSIX_APP_ID}'
            kwargs['on_click'] = lambda _args: _focus_canvas_window()
        elif _is_packaged():
            # Standalone (Inno Setup) build — unchanged. Register AUMID so Windows
            # attributes the click to Canvas Downloader, then focus the window.
            _ensure_aumid_registered(icon_path)
            kwargs['app_id'] = _WINDOWS_AUMID
            kwargs['on_click'] = lambda _args: _focus_canvas_window()
        # CLI mode: no app_id, no on_click — notification appears and clicking
        # closes it without activating any window.

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
    """Display a native macOS Notification Center notification.

    Each call posts an independent banner. We deliberately do NOT set a constant
    terminal-notifier ``group``: a fixed group ID makes every notification after
    the first one *replace* the previous one in-place (updating it silently in
    Notification Center) instead of alerting a fresh banner — which is exactly
    why only the very first notification was ever visible. Omitting the group
    lets "Download Complete", "Sync Review Ready", etc. each pop their own banner.

    No click action is attached: the app is now a single PyWebView window (the
    old Chrome-tab flow is gone), and opening the Streamlit URL on click would
    spawn a confusing second copy of the UI in the default browser.

    Fallback: osascript display notification (no click handler, as the osascript
    API doesn't support one).
    """
    if _PyncNotifier is not None:
        try:
            # No 'sound' here on purpose: _play_macos_sound() already afplays a
            # chime alongside this, so adding -sound would double up.
            kwargs = {
                'title': 'Canvas Downloader',
                'subtitle': title,
            }
            _PyncNotifier.notify(body, **kwargs)
            return
        except Exception as e:
            logger.debug(f"pync notification failed: {e}")

    # Fallback: osascript (notification appears from 'Script Editor', no click handler)
    try:
        safe_title = title.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
        safe_body = body.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
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
        logger.debug(f"macOS osascript notification failed: {e}")


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
    Any failure is logged at debug level - notifications are a polish
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
        else 'All files are already synced - nothing to download.' if mode in ('sync_uptodate', 'quick_sync_uptodate')
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
