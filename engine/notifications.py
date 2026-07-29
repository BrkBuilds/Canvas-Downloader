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

# Whether we've already asked the user for notification permission this process
# (UNUserNotificationCenter). Requested once, early, so the first completion
# banner isn't silently dropped while a fresh install's permission is pending.
_un_auth_requested = False

# Strong reference to the UNUserNotificationCenter delegate. MUST be kept alive
# for the lifetime of the process (PyObjC won't retain it for us) or the OS drops
# the delegate and foreground notifications go silent again.
_un_delegate = None

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
            # registration is skipped - it is virtualized and ignored in-package.
            kwargs['app_id'] = f'{pfn}!{_MSIX_APP_ID}'
            kwargs['on_click'] = lambda _args: _focus_canvas_window()
        elif _is_packaged():
            # Standalone (Inno Setup) build - unchanged. Register AUMID so Windows
            # attributes the click to Canvas Downloader, then focus the window.
            _ensure_aumid_registered(icon_path)
            kwargs['app_id'] = _WINDOWS_AUMID
            kwargs['on_click'] = lambda _args: _focus_canvas_window()
        # CLI mode: no app_id, no on_click - notification appears and clicking
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


def _show_macos_notification_native(title: str, body: str) -> bool:
    """Post a Notification Center banner from INSIDE this app process via PyObjC.

    This is the robust primary path. The Streamlit script runner shares the
    process with the PyWebView Cocoa ``NSApplication`` (see start.py), so a
    notification posted here is attributed to **Canvas Downloader.app itself**
    and uses the app's own notification permission - no external helper, no
    separate "terminal-notifier" entry in System Settings → Notifications.

    Why not pync/terminal-notifier: pync bundles an old, unsigned x86_64
    ``terminal-notifier`` (~2017) that fails silently on Apple-Silicon macOS 15
    (the afplay chime still works, which is why only the *sound* survived). The
    native ``NSUserNotification`` API ships with Foundation - which PyObjC always
    bundles for the Cocoa WebView - so it is arm64-native and always importable
    in the frozen app.

    ``NSUserNotification`` is formally deprecated but remains functional through
    macOS 15. Returns True only if the banner was actually delivered, so the
    caller can fall through to osascript otherwise.
    """
    try:
        from Foundation import (
            NSUserNotification,
            NSUserNotificationCenter,
        )
    except Exception as e:
        logger.debug(f"Foundation (PyObjC) unavailable for native notification: {e}")
        return False

    try:
        center = NSUserNotificationCenter.defaultUserNotificationCenter()
        if center is None:
            # Returns nil when the process is not a proper app bundle (e.g. a
            # bare `python` dev run). The frozen .app always has a bundle id.
            return False
        # Foreground suppression also applies here: NSUserNotificationCenter
        # hides a banner while the app is active unless its delegate returns YES
        # from shouldPresentNotification. Install one (idempotent, retained).
        _ensure_nsun_delegate(center)
        note = NSUserNotification.alloc().init()
        note.setTitle_('Canvas Downloader')
        note.setSubtitle_(title)
        note.setInformativeText_(body)
        center.deliverNotification_(note)
        logger.info("NSUserNotification delivered (fallback path)")
        return True
    except Exception as e:
        logger.info(f"Native NSUserNotification failed: {e}")
        return False


# Strong reference to the NSUserNotificationCenter delegate (fallback path).
_nsun_delegate = None


def _ensure_nsun_delegate(center) -> None:
    """Force NSUserNotificationCenter to present banners while app is frontmost.

    Mirrors the UN delegate, for the deprecated fallback path: the delegate's
    ``userNotificationCenter:shouldPresentNotification:`` returns YES (BOOL) so
    macOS shows the banner even when Canvas Downloader is the active app.
    """
    global _nsun_delegate
    if _nsun_delegate is not None:
        return
    try:
        from Foundation import NSObject

        def _should_present(self, center, notification):
            return True

        _D = type('_CanvasNSUNDelegate', (NSObject,), {
            'userNotificationCenter_shouldPresentNotification_': _should_present,
        })
        _nsun_delegate = _D.alloc().init()
        center.setDelegate_(_nsun_delegate)
        logger.info("NSUserNotification delegate installed (shouldPresent=YES)")
    except Exception as e:
        logger.info(f"Failed to install NSUserNotification delegate: {e}")


def _get_un_center():
    """Return the UNUserNotificationCenter, or None if unusable.

    ``currentNotificationCenter()`` raises (→ Python exception → None here) when
    the process has no valid app bundle (e.g. an unfrozen ``python`` dev run);
    the frozen .app has CFBundleIdentifier set in the spec, so it returns a real
    center. Also None when pyobjc-framework-UserNotifications isn't bundled.
    """
    try:
        from UserNotifications import UNUserNotificationCenter
        return UNUserNotificationCenter.currentNotificationCenter()
    except Exception:
        return None


# UNNotificationPresentationOptions (macOS 11+): Banner=1<<4, List=1<<3.
# We omit Sound here - _play_macos_sound() already afplays a chime, and adding
# the system sound would double it up.
_UN_PRESENT_OPTS = (1 << 4) | (1 << 3)  # Banner | List = 24


def _ensure_un_delegate(center) -> None:
    """Install a UNUserNotificationCenterDelegate so banners appear even when the
    app is FRONTMOST.

    macOS suppresses a UN notification while the app that posts it is the focused
    app, UNLESS the app's notification-center delegate implements
    ``willPresentNotification`` and returns presentation options. The user is
    typically watching the window when a download/sync finishes (app frontmost),
    so without this delegate every banner is dropped on the floor.

    ROUND 8 - proper protocol conformance for correct block bridging:
    The completion handler is an ObjC block whose single argument is a raw
    ``NSUInteger`` (the presentation options bitmask). Previous attempts used
    ``objc.selector(signature=b'v@:@@@?')`` - this tells PyObjC the 5th arg
    is *a* block (``@?``), but not the block's *internal* signature
    (``v@?Q`` = void taking unsigned long). Without the block's own type
    metadata, ``completionHandler(24)`` may silently marshal 24 as a pointer
    rather than an integer, causing macOS to receive garbage presentation
    options - and the banner is suppressed even though the delegate fires.

    The definitive fix is to declare the class with
    ``protocols=[UNUserNotificationCenterDelegate]``. This gives PyObjC the
    full method metadata (including the block's internal ``v@?Q`` signature)
    from the protocol's type encodings, so the integer marshalling is correct
    by construction. We fall back to the manual ``objc.selector`` approach
    only if the protocol object can't be imported (framework missing).

    ROUND 8 also confirmed that notifications ARE correctly delivered to
    Notification Center on macOS 15 (verified via Notification Center panel).
    Banners may not appear in VNC/remote desktop sessions because macOS renders
    the ephemeral banner overlay through the WindowServer compositor, which
    VNC servers (TigerVNC, etc.) typically do not capture. On a physical display
    the banners work correctly.

    Idempotent; retains a strong module-level reference to the delegate. Defined
    lazily (PyObjC's NSObject base is macOS-only and unavailable on the dev box).
    """
    global _un_delegate
    if _un_delegate is not None:
        return
    try:
        import objc
        from Foundation import NSObject

        # --- Resolve the delegate protocol for correct block bridging ---
        _un_protocol = None
        try:
            from UserNotifications import UNUserNotificationCenterDelegate
            _un_protocol = UNUserNotificationCenterDelegate
        except ImportError:
            pass
        except AttributeError:
            # Some pyobjc builds export the framework but not the protocol object.
            pass

        # Build the delegate class - with protocol if available, manual signature
        # as fallback. Protocol conformance is strictly superior: PyObjC reads the
        # method type encodings from the protocol, including the completion handler
        # block's internal signature (v@?Q), so integer marshalling is correct by
        # construction.
        if _un_protocol is not None:
            class _CanvasUNDelegate(NSObject, protocols=[_un_protocol]):
                def userNotificationCenter_willPresentNotification_withCompletionHandler_(
                    self, center, notification, completionHandler
                ):
                    logger.info(
                        "UN willPresentNotification fired (app frontmost) "
                        "→ calling completionHandler(%d) [protocol-conformant]",
                        _UN_PRESENT_OPTS,
                    )
                    try:
                        completionHandler(_UN_PRESENT_OPTS)
                    except Exception as exc:
                        logger.info("UN completionHandler call failed: %s", exc)

            _delegate_mode = "protocol-conformant"
        else:
            # Fallback: explicit ObjC selector signature.
            # 'v@:@@@?' = void; self(_id), _cmd(SEL), center(@), notification(@), block(@?).
            class _CanvasUNDelegate(NSObject):
                def userNotificationCenter_willPresentNotification_withCompletionHandler_(
                    self, center, notification, completionHandler
                ):
                    logger.info(
                        "UN willPresentNotification fired (app frontmost) "
                        "→ calling completionHandler(%d) [selector-fallback]",
                        _UN_PRESENT_OPTS,
                    )
                    try:
                        completionHandler(_UN_PRESENT_OPTS)
                    except Exception as exc:
                        logger.info("UN completionHandler call failed: %s", exc)

                userNotificationCenter_willPresentNotification_withCompletionHandler_ = (
                    objc.selector(
                        userNotificationCenter_willPresentNotification_withCompletionHandler_,
                        signature=b'v@:@@@?',
                    )
                )
            _delegate_mode = "selector-fallback"

        _un_delegate = _CanvasUNDelegate.alloc().init()
        center.setDelegate_(_un_delegate)
        logger.info("UN delegate installed (%s)", _delegate_mode)
    except Exception as e:
        logger.info(f"Failed to install UN notification delegate: {e}")


def request_macos_notification_permission() -> None:
    """Ask the user once for notification permission via the modern UN framework.

    Called early (app startup) so the FIRST completion banner isn't dropped while
    a fresh install's permission is still pending. Idempotent per process and a
    safe no-op off macOS / when UserNotifications isn't available. Authorization,
    once granted, persists across launches - so on every later run notifications
    work from the very first one. Also installs the presentation delegate so
    foreground banners aren't suppressed.
    """
    global _un_auth_requested
    if system != 'Darwin' or _un_auth_requested:
        return
    _un_auth_requested = True
    center = _get_un_center()
    if center is None:
        logger.info("UN center unavailable at startup (not a bundle / framework missing)")
        return
    # Delegate first, so it's in place before the first notification is delivered.
    _ensure_un_delegate(center)
    try:
        # UNAuthorizationOptions bitmask: badge(1) | sound(2) | alert(4) = 7.
        # (Stable, documented Apple constants.) Completion handler logs the
        # outcome; delivery is attempted regardless and the OS drops it silently
        # if denied.
        def _auth_cb(granted, error):
            logger.info(
                f"UN authorization result: granted={bool(granted)} "
                f"error={error if error else 'none'}"
            )
        center.requestAuthorizationWithOptions_completionHandler_(7, _auth_cb)
        logger.info("UN authorization requested (badge|sound|alert)")
    except Exception as e:
        logger.info(f"UN authorization request failed: {e}")


def _log_un_settings(center) -> None:
    """Asynchronously log the app's current UN authorization + alert settings.

    ``authorizationStatus``: 0=notDetermined 1=denied 2=authorized
    3=provisional 4=ephemeral. ``alertSetting``: 0=notSupported 1=disabled
    2=enabled. This is the single most diagnostic line - if status != 2 the OS
    will never show a banner no matter what we post.
    """
    try:
        def _cb(settings):
            try:
                logger.info(
                    f"UN settings: authorizationStatus={settings.authorizationStatus()} "
                    f"alertSetting={settings.alertSetting()} "
                    f"notificationCenterSetting={settings.notificationCenterSetting()}"
                )
            except Exception as e:
                logger.info(f"UN settings read failed: {e}")
        center.getNotificationSettingsWithCompletionHandler_(_cb)
    except Exception as e:
        logger.info(f"UN getNotificationSettings failed: {e}")


def _show_macos_notification_un(title: str, body: str) -> bool:
    """Post a banner via the modern UserNotifications framework (the right way).

    Preferred over the deprecated ``NSUserNotification``. Requires (a) the .app to
    carry a bundle identifier - set in the PyInstaller spec - and (b) pyobjc-
    framework-UserNotifications to be importable/bundled. Returns False on ANY
    failure so the caller falls back to NSUserNotification, keeping us strictly no
    worse than before even if the framework is missing or a future macOS changes
    the API. Attributed to Canvas Downloader.app and uses its own permission.

    Foreground banners are handled by the presentation delegate installed in
    ``_ensure_un_delegate`` (which returns Banner|List from willPresentNotification);
    without it macOS silently suppresses banners while the app is the active app.
    """
    try:
        from UserNotifications import (
            UNMutableNotificationContent,
            UNNotificationRequest,
        )
    except Exception:
        return False
    center = _get_un_center()
    if center is None:
        return False
    try:
        request_macos_notification_permission()  # ensure we've asked at least once
        _ensure_un_delegate(center)              # belt-and-suspenders: delegate present
        _log_un_settings(center)                 # diagnostic: actual auth status
        content = UNMutableNotificationContent.alloc().init()
        content.setTitle_('Canvas Downloader')
        content.setSubtitle_(title)
        content.setBody_(body)
        import uuid as _uuid
        # nil trigger = deliver immediately.
        req = UNNotificationRequest.requestWithIdentifier_content_trigger_(
            _uuid.uuid4().hex, content, None
        )

        def _add_cb(error):
            if error:
                logger.info(f"UN addNotificationRequest error: {error}")
            else:
                logger.info("UN addNotificationRequest accepted (no error)")
        center.addNotificationRequest_withCompletionHandler_(req, _add_cb)
        logger.info("UN notification posted via UNUserNotificationCenter")
        return True
    except Exception as e:
        logger.info(f"UNUserNotificationCenter delivery failed: {e}")
        return False


def _show_macos_notification(title: str, body: str):
    """Display a native macOS Notification Center notification.

    Order of attempts (most correct/reliable first):
      1. Modern ``UNUserNotificationCenter`` (UserNotifications framework) via
         PyObjC - the only API Apple still supports. See
         ``_show_macos_notification_un``. Requires the bundle id (set in the spec)
         + pyobjc-framework-UserNotifications bundled.
      2. ``NSUserNotification`` via Foundation - deprecated but functional through
         macOS 15; always available (Foundation ships with the Cocoa WebView).
      3. pync / terminal-notifier - vendored binary, unreliable on arm64 Sequoia.
      4. ``osascript display notification`` - last resort.

    Each call posts an independent banner. We deliberately do NOT set a constant
    terminal-notifier ``group``: a fixed group ID makes every notification after
    the first one *replace* the previous one in-place instead of alerting a fresh
    banner - which is exactly why only the very first one was ever visible.

    No click action is attached: the app is a single PyWebView window, and
    opening the Streamlit URL on click would spawn a confusing second copy of the
    UI in the default browser.
    """
    logger.info(f"Dispatching macOS notification: {title!r}")

    # 1. Modern UserNotifications framework - the right, future-proof path.
    if _show_macos_notification_un(title, body):
        return

    logger.info("UN path did not deliver - falling back to NSUserNotification")

    # 2. NSUserNotification (deprecated, but works today and always importable).
    if _show_macos_notification_native(title, body):
        return

    logger.info("NSUserNotification path failed - falling back to pync/osascript")

    # 3. pync fallback (best-effort; the vendored binary often no-ops on arm64).
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

    # 4. Fallback: osascript (notification appears from 'Script Editor', no click handler)
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
    # These three are worded to MATCH the completion card the user sees at the
    # same moment (shared/components.render_completion_card). They used to say
    # "Sync done! All files up to date" while the card said something slightly
    # different, so the toast and the screen disagreed on the same event.
    elif mode == 'sync_uptodate':
        title = 'Sync done - everything up to date'
    elif mode == 'quick_sync_uptodate':
        title = 'Quick Sync done - everything up to date'
    elif mode == 'daily_sync':
        title = 'Daily Sync Complete'
    elif mode == 'daily_sync_uptodate':
        title = 'Daily sync done - everything up to date'
    else:
        title = 'Download Complete'

    body = summary or (
        'Your files are ready.' if mode == 'download'
        else 'Your courses are up to date.' if mode == 'sync'
        else 'New course files are ready in your folders.' if mode == 'daily_sync'
        else 'All files are already synced - nothing to download.'
        if mode in ('sync_uptodate', 'quick_sync_uptodate', 'daily_sync_uptodate')
        else 'Course analysis completed. Waiting for your review.'
    )

    system = platform.system()
    if system == 'Windows':
        worker = lambda: _windows_notify(title, body)
        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as e:
            logger.debug(f"Failed to dispatch completion notification thread: {e}")
    elif system == 'Darwin':
        # macOS: play sound on a background thread (afplay is fire-and-forget),
        # but post the notification DIRECTLY on the calling thread.
        # addNotificationRequest: is internally async and returns instantly,
        # so it won't block the Streamlit script runner. Keeping the notification
        # post on the calling thread avoids run-loop issues - the daemon thread
        # context can differ from what UNUserNotificationCenter/its delegate
        # callbacks expect, and a daemon thread can be killed during process
        # shutdown before the completion handler fully executes.
        try:
            threading.Thread(target=_play_macos_sound, daemon=True).start()
        except Exception:
            pass
        try:
            _show_macos_notification(title, body)
        except Exception as e:
            logger.debug(f"macOS notification dispatch failed: {e}")
    # Linux/other: silent (app is not shipped there)
