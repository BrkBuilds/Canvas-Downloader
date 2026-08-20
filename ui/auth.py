"""
ui.auth - Sidebar authentication, navigation, and global settings.

Extracted from ``app.py`` (Phase 7).
Strict physical move - NO logic changes.

Contains:
  - ``render_sidebar()`` - full sidebar: auth form, token loading,
    navigation buttons, global settings dialog, logout, version badge
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import threading
from html import escape as _he

import streamlit as st

from core.canvas_logic import CanvasManager
from version import __version__

logger = logging.getLogger(__name__)


# Streamlit's own tooltip glyph, byte-for-byte: the 16x16 lucide help-circle,
# stroke-width 2, at #fafafa - read off the live [data-testid="stTooltipIcon"]
# svg on 2026-07-26 so an inline help icon in raw card HTML is
# indistinguishable from the one a `help=` argument renders right beside it.
#
# Shipped as an <img> data URI, NOT an inline <svg>: st.html() sanitises its
# input and DROPS svg elements (measured - the span rendered with an empty
# innerHTML), while <img> survives. That is also how every card icon in this
# dialog is already drawn. Paired with the `.stg-help` wrapper in the CSS.
_STG_HELP_GLYPH = (
    '<img alt="" width="16" height="16" src="data:image/svg+xml;base64,'
    + base64.b64encode(
        # #fafafa is 1.00 CIEDE2000 from theme.WHITE and Rule 8 flags it. It is
        # NOT drift: it is the literal colour Streamlit paints its own tooltip
        # icon (config.toml `textColor`), read off the live DOM. The whole point
        # of this glyph is to be indistinguishable from the native one sitting
        # in the neighbouring card, so it must track Streamlit, not our palette.
        b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
        # audit-ignore
        b'viewBox="0 0 24 24" fill="none" stroke="#fafafa" stroke-width="2" '
        b'stroke-linecap="round" stroke-linejoin="round">'
        b'<circle cx="12" cy="12" r="10"/>'
        b'<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
        b'<line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
    ).decode()
    + '" />'
)


def _get_config_path() -> str:
    """Return the path to the persistent config JSON file (lazy import)."""
    from shared.helpers import get_config_dir
    return os.path.join(get_config_dir(), 'canvas_downloader_settings.json')

# Evaluated once at first render (not at import-time of the module).
# All reads/writes use CONFIG_FILE as a stable module-level constant.
try:
    CONFIG_FILE = _get_config_path()
except Exception:
    import tempfile
    CONFIG_FILE = os.path.join(tempfile.gettempdir(), 'canvas_downloader_settings.json')
KEYRING_SERVICE = "CanvasDownloader"

# ── Config migration ─────────────────────────────────────────────────────────
# Settings keys belonging to features that have been REMOVED, plus legacy secret
# fields. Without a migration these live forever in a long-lived config file:
# `numbering_enabled` was still sitting in real user configs long after the
# file-numbering feature was pulled, where it reads like an active option to
# anyone who opens the JSON.
#
# Deliberately a DENY-list, never an allow-list. This file is CO-OWNED:
# panopto/settings.py writes the entire "panopto" subtree into it independently
# of this module (see panopto/settings.SETTINGS_KEY), so an allow-list here would
# silently delete the user's transcription engine config - model, device,
# language - on their next login. A deny-list can only ever drop a key we have
# explicitly retired, so an unknown key owned by another module is always safe.
RETIRED_CONFIG_KEYS = {
    'numbering_enabled',  # file-number prefixes: shipped, worked badly, removed
    'api_token',          # legacy plaintext token - now the OS keyring
    'mac_api_token',      # ditto, the macOS-specific variant
}


def _migrate_config(cfg: dict) -> dict:
    """Drop retired keys from a loaded config, in place. Returns the same dict.

    Cheap and idempotent, so it is safe to call on every read. The pruned dict is
    what the write paths persist, which is how the keys actually leave the file.
    """
    if not isinstance(cfg, dict):
        return {}
    dropped = [k for k in RETIRED_CONFIG_KEYS if k in cfg]
    for k in dropped:
        cfg.pop(k, None)
    if dropped:
        logger.info("Config migration: removed retired setting(s) %s",
                    ", ".join(sorted(dropped)))
    return cfg

# Watchdog timeout for keyring operations.
# macOS: Keychain access can legitimately BLOCK on an interactive prompt
# ("Canvas Downloader wants to use your confidential information... enter the
# login keychain password" - shown on every rebuild of an ad-hoc-signed app
# because the code signature changes). Users need time to read and answer it;
# abandoning at 5s made the login render without the saved token even though
# the user clicked Allow, which looked like saving had failed. 90s gives them
# time while still defending against a genuinely hung backend (daemon thread,
# never blocks app exit).
# Windows: Credential Manager never prompts - keep the tight 5s watchdog.
_KEYRING_TIMEOUT = 90.0 if sys.platform == 'darwin' else 5.0

# Budget for a keychain read that is only an OPTIMISATION, never the operation
# the user is waiting for.
#
# store_token reads before writing so it can skip a write that cannot change
# anything - which is what stops a refused write destroying a good credential.
# But macOS can PROMPT on a keychain access (a rebuilt app with a new ad-hoc
# signature reading the previous build's item is the documented case, and it was
# hit on this very machine), and the prompt blocks until answered. With the full
# 90s watchdog on both, that turns one 90-second worst case at login into two.
# The skip is worth having only if it is cheap: give up quickly and fall through
# to the write, which keeps the full budget it always had.
_KEYRING_PROBE_TIMEOUT = 5.0

def _run_keyring_op(fn, *args, timeout: float = _KEYRING_TIMEOUT):
    """Run a keyring operation on a DAEMON thread with a hard timeout.

    The previous implementation used ``with ThreadPoolExecutor(...)`` - but
    the context manager's ``__exit__`` calls ``shutdown(wait=True)``, which
    blocks on a truly-hung keyring backend and defeated the 5s watchdog
    (login could freeze forever). A daemon thread + queue is genuinely
    non-blocking: a hung backend thread is simply abandoned and can never
    block the app (or interpreter exit).

    Raises TimeoutError on timeout; re-raises the backend's own exception.
    """
    import queue as _queue
    import threading as _threading
    _result: _queue.Queue = _queue.Queue(maxsize=1)

    def _worker():
        try:
            _result.put(('ok', fn(*args)))
        except Exception as e:  # noqa: BLE001 - backend errors are surfaced to caller
            _result.put(('err', e))

    _threading.Thread(target=_worker, daemon=True, name="keyring-op").start()
    try:
        kind, value = _result.get(timeout=timeout)
    except _queue.Empty:
        raise TimeoutError(f"keyring operation timed out after {timeout:.1f}s")
    if kind == 'err':
        raise value
    return value


def _safe_keyring_get(service: str, username: str,
                      timeout: float = _KEYRING_TIMEOUT) -> str | None:
    """Read password from keyring with a daemon-thread watchdog (see _KEYRING_TIMEOUT).

    *timeout* is overridable so a read that is only an OPTIMISATION can give up
    quickly - see ``_KEYRING_PROBE_TIMEOUT`` and ``store_token``.
    """
    import keyring
    try:
        return _run_keyring_op(keyring.get_password, service, username,
                               timeout=timeout)
    except TimeoutError:
        logger.warning(f"Keyring get_password timed out ({timeout:.0f}s). Environment might be headless or restricted. Falling back.")
        return None
    except Exception as e:
        logger.warning(f"Keyring get_password failed: {e}")
        return None

def _safe_keyring_set(service: str, username: str, password: str) -> bool:
    """Write password to keyring with a daemon-thread watchdog (see _KEYRING_TIMEOUT)."""
    import keyring
    try:
        _run_keyring_op(keyring.set_password, service, username, password)
        return True
    except TimeoutError:
        logger.warning(f"Keyring set_password timed out ({_KEYRING_TIMEOUT:.0f}s). Falling back.")
        return False
    except Exception as e:
        logger.warning(f"Keyring set_password failed: {e}")
        return False

def _safe_keyring_delete(service: str, username: str) -> bool:
    """Delete password from keyring with a daemon-thread watchdog (see _KEYRING_TIMEOUT)."""
    import keyring
    try:
        _run_keyring_op(keyring.delete_password, service, username)
        return True
    except TimeoutError:
        logger.warning(f"Keyring delete_password timed out ({_KEYRING_TIMEOUT:.0f}s).")
        return False
    except Exception as e:
        logger.warning(f"Keyring delete_password failed: {e}")
        return False


# ---------------------------------------------------------------------------
# macOS Keychain: the ACL prompt must never block the first paint
# ---------------------------------------------------------------------------
# `keyring`'s macOS backend calls SecItemCopyMatching with NO UI-suppression
# flag, so when the item's ACL does not trust the running binary that call
# BLOCKS on a GUI prompt. restore_saved_session() runs on the Streamlit SCRIPT
# THREAD during init, before anything renders - so the whole window is dead for
# as long as the prompt is up (measured on macOS 26.6.1, packaged app: the boot
# overlay shows "Connecting..." for its 30s cap and then the window is
# COMPLETELY EMPTY until the user answers or the 90s watchdog fires).
#
# It fires on every app UPDATE, not once: the bundle is ad-hoc signed
# (TeamIdentifier not set), and BOTH halves of a keychain item's access control
# key on the code signature - the trusted-application list and, since 10.11, the
# PARTITION LIST. Measured, so the obvious escapes are closed rather than
# assumed:
#   * `security add-generic-password -A` (trusted-app list = <null>) STILL
#     prompts, because the partition list says `apple-tool:`.
#   * The app cannot silently repair its own ACL after the user allows: the
#     delete half of delete+add needs authorisation we do not have and fails
#     -25244. (It fails SAFELY - the item survives - which is why the repair is
#     attempted UI-suppressed or not at all.)
#
# So the prompt is unavoidable while the app is ad-hoc signed. What is fixable
# is that it costs the user a dead window, and that is what these two helpers
# are for: probe WITHOUT letting macOS prompt (4ms on success, ~9ms when a
# prompt would be needed - both measured), then raise the prompt off the script
# thread while the login screen explains it.
#
# Codes, not prose - these are stable API constants, so matching them is not the
# locale-fragile predicate this codebase has been bitten by:
#   -25293 errSecAuthFailed             (ad-hoc-signed caller; needs the prompt)
#   -25308 errSecInteractionNotAllowed  (we suppressed UI and UI was required)
#   -25300 errSecItemNotFound           (no saved token - NOT a prompt)
#      -128 errSecUserCanceled          (the user pressed Deny)
_KEYCHAIN_PROMPT_STATUSES = ('-25293', '-25308')
_KEYCHAIN_DENIED_STATUSES = ('-128',)

# SecKeychainSetUserInteractionAllowed is PROCESS-GLOBAL, so a suppressed probe
# would silently suppress any concurrent keychain call too. This lock makes the
# suppressed window exclusive; callers never BLOCK on it (see below).
_keychain_ui_lock = threading.Lock()


def _set_keychain_ui_allowed(allowed: bool) -> bool:
    """Toggle macOS keychain UI. Returns False if the call is unavailable."""
    if sys.platform != 'darwin':
        return False
    try:
        import ctypes
        from ctypes.util import find_library
        _sec = ctypes.CDLL(find_library('Security'))
        fn = _sec.SecKeychainSetUserInteractionAllowed
        fn.restype = ctypes.c_int32
        fn.argtypes = (ctypes.c_ubyte,)
        return fn(1 if allowed else 0) == 0
    except Exception as e:                                         # noqa: BLE001
        logger.warning("Could not toggle keychain UI (%s); "
                       "falling back to an interactive read.", e)
        return False


def keyring_get_without_prompting(service: str, username: str) -> tuple[str | None, bool]:
    """``(token_or_None, needs_prompt)`` - read the keyring, never prompting.

    On every platform but macOS this is the ordinary watchdogged read and
    *needs_prompt* is always False, so Windows behaviour is untouched.

    On macOS the read runs with keychain UI suppressed, which turns "macOS would
    put a modal in front of the user" from an unbounded block into an error we
    can see in milliseconds. ``needs_prompt=True`` means exactly that and
    nothing else - a missing item, a locked-out backend or any other failure
    answers ``(None, False)``, because prompting cannot fix those.
    """
    if sys.platform != 'darwin':
        return (_safe_keyring_get(service, username), False)

    # An unlock is already in flight (the thread below holds this lock for as
    # long as the prompt is up). We do not wait for it - we already know the
    # answer, and waiting is the blocking this function exists to remove.
    if not _keychain_ui_lock.acquire(blocking=False):
        return (None, True)
    try:
        if not _set_keychain_ui_allowed(False):
            # Cannot suppress - do not gamble the first paint on a read that
            # might prompt. Report it as needing one; the unlock thread will
            # perform the real read off the script thread.
            return (None, True)
        try:
            import keyring
            return (_run_keyring_op(keyring.get_password, service, username,
                                    timeout=_KEYRING_PROBE_TIMEOUT), False)
        except TimeoutError:
            logger.warning("Suppressed keychain read did not answer in %.0fs.",
                           _KEYRING_PROBE_TIMEOUT)
            return (None, False)
        except Exception as e:                                     # noqa: BLE001
            text = str(e)
            if any(code in text for code in _KEYCHAIN_PROMPT_STATUSES):
                logger.info("Saved sign-in needs a Keychain prompt "
                            "(the app signature changed since it was saved).")
                return (None, True)
            logger.warning("Keychain read failed without prompting: %s", e)
            return (None, False)
        finally:
            _set_keychain_ui_allowed(True)
    finally:
        _keychain_ui_lock.release()


# Single-flight interactive unlock. Process-global rather than session state on
# purpose: it is driven by a background thread, which has no ScriptRunContext -
# the same reason core/course_cache.py and core/cancellation.py keep their state
# here. States: idle | running | ok | denied | error.
_kc_unlock: dict = {'state': 'idle', 'token': '', 'key': ''}
_kc_unlock_lock = threading.Lock()


def begin_keychain_unlock(service: str, username: str) -> None:
    """Raise the Keychain prompt on a DAEMON THREAD. Idempotent per account.

    Called from the login screen AFTER it has emitted its explanation, so the
    prompt lands on a painted, self-explaining page instead of an empty window.
    Nothing waits on this thread: if the user never answers, the login form
    below the notice still works.
    """
    key = f"{service}\x00{username}"
    with _kc_unlock_lock:
        if _kc_unlock['state'] == 'running' and _kc_unlock['key'] == key:
            return
        if _kc_unlock['state'] in ('ok', 'denied', 'error') and _kc_unlock['key'] == key:
            return
        _kc_unlock.update({'state': 'running', 'token': '', 'key': key})

    def _worker():
        import keyring
        # Take the SAME lock the suppressed probe uses, so a probe can never
        # switch UI off underneath this read and turn the prompt into an error.
        with _keychain_ui_lock:
            _set_keychain_ui_allowed(True)
            try:
                token = keyring.get_password(service, username) or ''
                state, err = ('ok', '') if token else ('error', 'no token stored')
            except Exception as e:                                 # noqa: BLE001
                text = str(e)
                if any(code in text for code in _KEYCHAIN_DENIED_STATUSES):
                    state, token, err = 'denied', '', ''
                else:
                    state, token, err = 'error', '', text
        if err:
            logger.warning("Keychain unlock failed: %s", err)
        with _kc_unlock_lock:
            if _kc_unlock['key'] == key:
                _kc_unlock.update({'state': state, 'token': token})

    threading.Thread(target=_worker, daemon=True, name="keychain-unlock").start()


def keychain_unlock_status() -> str:
    """One of ``idle`` / ``running`` / ``ok`` / ``denied`` / ``error``."""
    with _kc_unlock_lock:
        return _kc_unlock['state']


def unlocked_token() -> str:
    """A resolved unlock's token (empty if there is none). Does NOT consume it.

    The first version consumed it, on hygiene grounds, and that was wrong -
    found by driving the real app, not by the tests. The unlock state is
    process-global (a background thread has no ScriptRunContext) while
    ``keychain_unlock_pending`` is per SESSION, so a SECOND Streamlit session in
    the same process - a reload, or a second window - would set pending, find the
    unlock already 'ok', receive an EMPTY token because session one had taken it,
    and land on the login page with no notice and no explanation. Observed
    exactly that.

    Keeping the value costs nothing: it is already in the Keychain and in the
    first session's ``api_token``. ``reset_keychain_unlock`` clears it whenever
    the credential it refers to is dropped.
    """
    with _kc_unlock_lock:
        return _kc_unlock['token'] if _kc_unlock['state'] == 'ok' else ''


def reset_keychain_unlock() -> None:
    """Forget any unlock state - used by logout and by force_reauth."""
    with _kc_unlock_lock:
        _kc_unlock.update({'state': 'idle', 'token': '', 'key': ''})


def read_config_for_update() -> tuple[dict, bool]:
    """``(config, may_write)`` for a read-modify-write of the settings file.

    Every handler that changes ONE setting has to read the whole file first,
    because the file is shared: ``panopto`` (the engine block),
    ``panopto_notice_ack_version`` (a legal acknowledgement), the download
    defaults, ``show_help_text``, ``default_download_path``, and more. The
    Settings dialog's own comment already states the rule - "this handler is a
    read-modify-write of the whole config, so panopto_notice_ack_version and the
    'panopto' engine block survive untouched - which is exactly why it must not
    be rewritten as a fresh dict."

    Its ``except`` branch did exactly that. A read that FAILED degraded to ``{}``
    and the handler wrote anyway, so one unreadable read silently replaced every
    key it had not been given a new value for. This is the same class the sync
    stores were hardened against (``core.library._update``,
    ``shared.helpers.atomic_update_sync_pairs``); the settings file was simply
    never swept with them.

    Split by CAUSE, exactly as those two do, because the right answer differs:

    * **damaged content** - malformed JSON, or bytes that are not valid UTF-8
      (``UnicodeDecodeError`` is a *sibling* of ``JSONDecodeError``, not a
      subclass; both are ``ValueError``). The file cannot be preserved in place,
      so it is quarantined to ``*.corrupt.json`` - the ``core.preset_manager``
      pattern, which keeps the data on disk - and writing proceeds, so the user
      gets a working settings file back.
    * **transient ``OSError``** - the config dir on a share that is offline, an
      antivirus lock, a permissions blip. Nothing is wrong with the file, so the
      caller must NOT write: ``may_write`` is False and the settings the user
      just changed are not persisted this time, which is recoverable. Silently
      discarding their Panopto model, their acknowledged notice and their
      download folder is not.
    * **missing file** - a genuinely fresh install. ``({}, True)``.

    The read/verdict/quarantine logic itself lives in
    ``shared.helpers.read_json_for_update`` - ONE implementation for the four
    modules that co-own this file (this one, ``panopto.settings`` twice, and
    ``shared.legal``). Three of those still degraded to ``{}`` and wrote anyway
    until 2026-08-09, because this fix was written here and nowhere else. The
    path is passed in rather than resolved there so ``CONFIG_FILE``'s
    import-time tempdir fallback stays this module's own business.

    ``_migrate_config`` is layered on HERE and not in the shared primitive: it
    moves a legacy token out of the JSON and into the keyring, which must not
    happen as a side effect of another module saving its own settings block.
    """
    from shared.helpers import read_json_for_update
    config, may_write = read_json_for_update(CONFIG_FILE)
    return (_migrate_config(config) if config else config), may_write


def _quarantine_config(reason: str) -> None:
    """Move a damaged settings file aside so its content survives on disk.

    Delegates to the shared helper; kept as a named function because the login
    and Settings paths call it directly.
    """
    from shared.helpers import quarantine_corrupt_json
    quarantine_corrupt_json(CONFIG_FILE, reason)


def write_config_atomically(config: dict) -> bool:
    """Persist the settings file without a window where it is truncated.

    ``open(CONFIG_FILE, 'w')`` truncates FIRST and writes second, so a crash,
    a full disk or a kill in between leaves the user's settings file empty or
    half-written. tmp + fsync + ``os.replace`` never exposes that state: the
    old file is intact until the new one is complete.

    This exists because the config was being written in FIVE places and only
    three of them did it safely. The two that did not were the legacy
    token-migration paths in ``restore_saved_session`` - which run at STARTUP,
    on the run that moves a token out of the JSON and into the keyring, i.e.
    exactly when the file is most worth not corrupting.

    Returns False (never raises) if nothing reached disk; a settings write must
    not be able to abort a login.
    """
    tmp = CONFIG_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(config, f)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, CONFIG_FILE)
        return True
    except Exception as e:
        logger.warning("Could not write settings to %s: %s", CONFIG_FILE, e)
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        return False


def store_token(username: str, token: str) -> bool:
    """Persist *token*, and answer whether it is RETRIEVABLE afterwards.

    Exists because ``keyring.set_password`` on macOS DELETES any existing item
    before adding the new one, so a failed save destroys the credential that was
    already there. Measured on macOS 15 (2026-08-10) against the real library: a
    stored value of "probe-value-before", one ``set_password`` that raised
    ``PasswordSetError (-25308)``, and the item read back as **None**. Combined
    with ``_save_fallback_token`` being a deliberate no-op off Windows, the user
    lost a working saved login and had to fetch a fresh Canvas token - while the
    only trace was a ``logger.warning`` claiming it had been "Saved to
    DPAPI-encrypted fallback storage", which on macOS is nothing at all.

    Three things, in this order, because each one alone is insufficient:

    1. **Skip a write that cannot change anything.** If the stored value already
       equals *token* there is nothing to gain from re-writing it and a
       credential to lose, and this is the common path - re-logging in with the
       same token, and both legacy-migration sites.
    2. Write, then fall back (Windows DPAPI; nothing on macOS by design).
    3. **Verify by reading back**, so the return value describes the stored
       state rather than the return code of one attempt. That is what makes it
       safe for a caller to delete its own copy of the token on True.

    Never raises: a persistence failure must not be able to abort a login.
    """
    # Both reads run on the SHORT budget: they are optimisation and confirmation,
    # never the thing the user is waiting for. Only the write keeps the full
    # watchdog it always had, so this cannot make a login slower than before -
    # see _KEYRING_PROBE_TIMEOUT for the prompting-keychain case that forces it.
    try:
        if _safe_keyring_get(KEYRING_SERVICE, username,
                             timeout=_KEYRING_PROBE_TIMEOUT) == token:
            return True
    except Exception:                                              # noqa: BLE001
        pass
    ok = False
    try:
        ok = _safe_keyring_set(KEYRING_SERVICE, username, token)
    except Exception as e:                                         # noqa: BLE001
        logger.warning(f"Keyring save raised: {e}")
    if not ok:
        try:
            _save_fallback_token(username, token)
        except Exception as e:                                     # noqa: BLE001
            logger.warning(f"Fallback token save failed: {e}")
    try:
        if _safe_keyring_get(KEYRING_SERVICE, username,
                             timeout=_KEYRING_PROBE_TIMEOUT) == token:
            return True
    except Exception:                                              # noqa: BLE001
        pass
    try:
        if _load_fallback_token(username) == token:
            return True
    except Exception:                                              # noqa: BLE001
        pass
    logger.warning(
        "Could not persist the Canvas token for %s: the OS credential store "
        "rejected the write and %s. The previously saved token may have been "
        "cleared by the failed write, so the next launch will ask for a token.",
        username,
        "there is no disk fallback on this platform" if sys.platform != 'win32'
        else "the encrypted fallback did not take either")
    return False


def _get_fallback_path() -> Path:
    from shared.helpers import get_config_dir
    from pathlib import Path
    return Path(get_config_dir()) / ".token_fallback"

def _save_fallback_token(username: str, token: str) -> None:
    """Write an encrypted fallback token for Windows only.

    Uses Windows DPAPI (CryptProtectData) so the ciphertext is tied to the
    current Windows user account and is unreadable by other users or if the
    file is copied off the machine.  The file format is JSON v2:
        {"_version": 2, "<url>": "<base64-of-DPAPI-ciphertext>"}

    Not implemented on macOS: Keychain is reliable there and the app should
    not persist tokens to disk when the OS credential store is unavailable.
    """
    if sys.platform != 'win32':
        return
    try:
        import win32crypt
        encrypted_bytes = win32crypt.CryptProtectData(
            token.encode('utf-8'), "CanvasDownloader", None, None, None, 0
        )
        encrypted_b64 = base64.b64encode(encrypted_bytes).decode('utf-8')

        fallback_path = _get_fallback_path()
        data: dict = {"_version": 2}
        if fallback_path.exists():
            try:
                with open(fallback_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if existing.get("_version") == 2:
                    data = existing
            except OSError as e:
                # Intact but unreadable right now (antivirus lock, share
                # offline). Writing would replace the store with just THIS
                # account, silently logging the user out of every other Canvas
                # they have saved. A token that is not cached is a re-login;
                # a token that is deleted is the same re-login for every other
                # account too, so decline the write. (Damaged content still
                # falls through to a fresh v2 store below - there is nothing
                # to preserve, and refusing would strand the user with no
                # fallback at all on the one path where keyring already failed.)
                logger.warning(
                    "Fallback token store unreadable (%s); not overwriting it.", e)
                return
            except Exception:
                pass
        data[username] = encrypted_b64

        tmp_path = fallback_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, fallback_path)
    except Exception as e:
        logger.warning(f"Failed to save fallback token: {e}")
        try:
            tmp_path = _get_fallback_path().with_suffix(".tmp")
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass

def _load_fallback_token(username: str) -> str:
    """Load a DPAPI-encrypted fallback token from disk (Windows only)."""
    if sys.platform != 'win32':
        return ""
    try:
        fallback_path = _get_fallback_path()
        if not fallback_path.exists():
            return ""
        with open(fallback_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        stored = data.get(username, "")
        if not stored or data.get("_version") != 2:
            return ""
        import win32crypt
        encrypted_bytes = base64.b64decode(stored.encode('utf-8'))
        _, plaintext = win32crypt.CryptUnprotectData(
            encrypted_bytes, None, None, None, 0
        )
        return plaintext.decode('utf-8')
    except Exception as e:
        logger.warning(f"Failed to load fallback token: {e}")
    return ""

def _delete_fallback_token(username: str) -> None:
    try:
        fallback_path = _get_fallback_path()
        if not fallback_path.exists():
            return
        data: dict = {}
        try:
            with open(fallback_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
        if username in data:
            data.pop(username)
            tmp_path = fallback_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp_path, fallback_path)
    except Exception as e:
        logger.warning(f"Failed to delete fallback token: {e}")


def normalize_canvas_url(raw: str) -> str:
    """Best-effort normalize a user-entered Canvas URL.

    - strips whitespace and trailing slashes
    - bare shorthand with no dot (e.g. ``cbscanvas``) → ``https://cbscanvas.instructure.com``
    - adds ``https://`` when no scheme is present
    - strips any path, keeping only ``scheme://host``

    Returns ``''`` for empty input. Non-destructive: the resolved URL is shown to
    the user and the original field is never silently rewritten without feedback.
    """
    import re as _re
    s = (raw or '').strip().rstrip('/')
    if not s:
        return ''
    has_scheme = s.lower().startswith(('http://', 'https://'))
    body = s.split('://', 1)[1] if has_scheme else s
    # Bare subdomain shorthand: no dot, no slash, no space → expand to instructure.com
    if '.' not in body and '/' not in body and ' ' not in body:
        return f"https://{body}.instructure.com"
    if not has_scheme:
        s = 'https://' + s
    m = _re.match(r'(https?://[^/]+)', s)
    return m.group(1) if m else s


def _looks_like_token(s: str) -> bool:
    """Heuristic: does this value look like a Canvas access token, not a URL?

    Deliberately conservative - only UNAMBIGUOUS signals, so a correctly typed
    URL is never mistaken for a token. Canvas tokens commonly look like
    ``<id>~<letters+digits>`` (a tilde no hostname ever contains), or a long
    dot-free/slash-free code. Any real Canvas URL has a dot, and the bare
    shorthand form (e.g. ``cbscanvas``) is far shorter than 40 chars.
    """
    s = (s or '').strip()
    if not s:
        return False
    if '~' in s:
        return True
    return (len(s) >= 40 and '.' not in s and '/' not in s and ' ' not in s
            and not s.lower().startswith(('http://', 'https://')))


def _looks_like_url(s: str) -> bool:
    """Heuristic: does this value look like a Canvas URL, not a token?

    Conservative twin of :func:`_looks_like_token` - only fires on signals a
    token cannot produce (an ``http(s)://`` scheme, or the literal
    ``instructure.com``), so a real token is never flagged as a URL.
    """
    s = (s or '').strip().lower()
    if not s:
        return False
    return s.startswith(('http://', 'https://')) or 'instructure.com' in s


# `_canvas_url_reachable` was deleted here on 2026-08-15 along with its only
# caller, the token guide's copy of the "open my settings page" button. Its job
# was to avoid sending a first-run user to a dead browser tab, and it worked by
# running a one-shot HTTP GET on CLICK - which the replacement button cannot do
# from inside st.form, where a click cannot rerun. Recorded rather than left in
# place: a function with no callers reads as an applied decision.


def force_reauth(reason: str = "") -> None:
    """Clear the stored credential and route back to the login page.

    Bulletproof reconnect: every keyring/fallback clear is watchdog-guarded
    (``_safe_keyring_delete``) and wrapped, so a hung credential backend can
    never block the route back to login. Pre-fills the known Canvas URL so the
    user only needs to paste a fresh token. Idempotent within a rerun.
    """
    keyring_user = st.session_state.get('api_url') or 'default'
    try:
        _safe_keyring_delete(KEYRING_SERVICE, keyring_user)
    except Exception:
        pass
    try:
        _delete_fallback_token(keyring_user)
    except Exception:
        pass
    st.session_state['api_token'] = ''
    st.session_state['is_authenticated'] = False
    # The credential this refers to has just been deleted, so any cached
    # Keychain-unlock verdict is now about nothing. Left standing, a previous
    # 'denied' would make begin_keychain_unlock a no-op for the rest of the
    # process and the notice would advertise a prompt that never appears.
    reset_keychain_unlock()
    st.session_state.pop('keychain_unlock_pending', None)
    st.session_state.pop('keychain_unlock_failed', None)
    # Re-arm the course selector's cold-boot spinner: the next fetch after a
    # reconnect is a genuine first load with nothing on screen to preserve.
    st.session_state.pop('_dl_courses_loaded_once', None)
    # Skip the login page's one-shot token auto-load so we don't immediately
    # re-read a token we just deleted; keep the URL handy for a quick reconnect.
    st.session_state['token_loaded'] = True
    if st.session_state.get('api_url'):
        st.session_state['url_input'] = st.session_state['api_url']
        # The URL we're reconnecting to was already verified by a prior login,
        # so the token-settings link can point at it directly (no re-check).
        st.session_state['url_verified'] = True
    if reason:
        st.session_state['reauth_reason'] = reason
    st.rerun(scope="app")


def render_sidebar(fetch_courses_fn):
    """Render the full sidebar: navigation, settings, logout.

    Must be called inside ``with st.sidebar:``.

    Args:
        fetch_courses_fn: The ``@st.cache_resource``-wrapped ``fetch_courses()``
            function from app.py.  Needed so logout can call ``.clear()``.
    """
    if not st.session_state.get('is_authenticated'):
        return

    # Kick off the once-per-launch update check on a daemon thread (non-blocking).
    try:
        from ui.update_banner import ensure_update_check
        ensure_update_check()
    except Exception:
        pass

    from shared.helpers import get_base64_image
    icon_b64    = get_base64_image("assets/icon.png")

    # ── Sidebar nav CSS lives in styles/global.css ──────────────────────
    # It is static, and it must NOT be a style-only `st.html()`: that is an
    # event-container write, the event container is index-addressed, and on a
    # login run `render_login_page`'s stylesheet takes this exact slot - which
    # stripped the icons and heights off the still-visible sidebar for the
    # whole logout transition. See the block comment in global.css.

    with st.container(border=False, key="sidebar_top"):
        # ── Header: icon + title + separator (single HTML block) ─────────
        st.html(f"""
<div style="padding: 25px 1rem 25px 20px;">
    <a href="https://canvasdownloader.app/" target="_blank" title="Go to website" style="text-decoration: none; display: flex; align-items: center; gap: 12px;">
        <img src="data:image/png;base64,{icon_b64}"
             style="width: 42px; height: 42px; border-radius: 8px;
                    box-shadow: 0 4px 10px rgba(0,0,0,0.3); display: block;" />
        <div style="display: flex; flex-direction: column; justify-content: center; height: 42px;">
            <span style="font-weight: 700; font-size: 1.25rem; color: #f3f4f6; line-height: 1; margin: 0;">
                Canvas Downloader
            </span>
        </div>
    </a>
</div>
<hr style="margin: 0 0 10px 0; border: none; border-bottom: 1px solid rgba(255,255,255,0.08);" />
""")

        _render_authenticated_nav_top()

    _render_authenticated_nav_bottom(fetch_courses_fn)

    # Warm the lazy JS chunks for the dialog-only widgets so they don't flash a
    # grey skeleton the first time the user opens Settings / Panopto. Rendered
    # last, hidden, on every authenticated page - see the function docstring.
    _prewarm_widget_chunks()



def _prewarm_widget_chunks() -> None:
    """Preload the lazy-loaded JS chunks for widgets that ONLY appear in dialogs.

    Streamlit code-splits every widget's React implementation into its own JS
    chunk, fetched on FIRST mount and shown behind a ``<Suspense>`` skeleton
    (the solid grey box) until it arrives. Widgets used all over the app -
    button, checkbox/toggle, text input - are always warm, so they never
    skeleton. But ``slider`` / ``number_input`` (Settings) and ``selectbox`` /
    ``multiselect`` (Panopto, sync-history filter, CBS filters) live only in
    dialogs and rarely-visited screens, so their chunk is COLD until that screen
    first opens - and on a slow machine that is a visible second of grey boxes
    over the fields (reported 2026-08-03: the three Settings number inputs and
    the Panopto Language dropdown).

    Mounting one hidden instance of each here - the sidebar renders on every
    authenticated page - triggers the ``import()`` during the normal page load,
    so by the time the user opens the dialog the chunk is already cached and the
    real widgets mount instantly. ``display:none`` (global.css) does NOT unmount
    a React node, so the lazy import still fires; the container just never
    paints and is out of layout flow. The widgets' return values and keys are
    throwaway and collide with nothing real.

    Rendered ONCE per session: the browser keeps an imported JS module in memory
    for the page's lifetime, so a single mount is enough to warm the chunk - the
    node can then unmount on the next rerun with no cost. It is the last element
    in the sidebar, so dropping it shifts nothing after it.
    """
    if st.session_state.get('_widget_chunks_prewarmed'):
        return
    st.session_state['_widget_chunks_prewarmed'] = True
    try:
        with st.container(border=True, key="cd_widget_prewarm"):
            st.slider("pw", 0, 1, 0, key="_pw_slider", label_visibility="collapsed")
            st.number_input("pw", value=0, key="_pw_number", label_visibility="collapsed")
            st.selectbox("pw", ("-",), key="_pw_select", label_visibility="collapsed")
            st.multiselect("pw", ("-",), key="_pw_multiselect", label_visibility="collapsed")
    except Exception:
        # A prewarm is pure optimisation; it must never break the sidebar.
        logger.debug("Widget-chunk prewarm failed", exc_info=True)


def restore_saved_session() -> None:
    """Load saved settings + token and sign the user in, once per session.

    Called from ``app.py`` during session init - BEFORE the sidebar and the page
    body render - and it must stay there.  This block used to live inside
    ``render_login_page`` and end in ``st.rerun()``, which made every launch with
    a saved login cost TWO script runs: the first one rendered nothing at all
    (it only did keyring + network I/O behind an empty window) and then threw
    itself away.  Measured 2026-07-27 in the real app: ~4.0s of blank page, of
    which ~2.1s was this block and the rest the wasted rerun.  Running it during
    init means the very first run lands on the finished screen.

    Two further consequences of the old placement, both fixed by the move:
      * every setting in the config file (concurrent downloads, help text, debug
        mode, default download path, ...) was applied AFTER the sidebar had
        already rendered on the run that adopted them;
      * the once-per-session stale-debug-log clear in app.py ran before
        ``debug_mode`` had been read from disk, so it could never fire.

    Safe to call unconditionally: it is a no-op once ``token_loaded`` is set,
    and a no-op when there is no config file (a genuinely fresh install).
    """
    if st.session_state.get('token_loaded') or st.session_state.get('is_authenticated'):
        return
    st.session_state['token_loaded'] = True
    if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding='utf-8') as f:
                    config = _migrate_config(json.load(f))
                    st.session_state['api_url'] = config.get('api_url', '')
                    # A URL only gets persisted to config after a successful
                    # login, so a saved api_url is implicitly verified.
                    st.session_state['url_verified'] = bool(st.session_state['api_url'])
                    # ...and the field is PRE-FILLED with it, which the login
                    # page used to leave blank. Reaching that page with a saved
                    # api_url means one thing: the token is gone (expired,
                    # revoked, or never stored) - the school has not changed.
                    # Making the user find their institution again to fix a
                    # token problem is friction the app already has the answer
                    # to, and force_reauth has pre-filled it on the mid-session
                    # path all along; this is the same courtesy on the launch
                    # path. It is still just a default: the field is editable,
                    # so switching schools is typing over it.
                    #
                    # Assigned only when the widget has no value yet, because
                    # writing a widget key Streamlit is already tracking would
                    # overwrite what the user has typed.
                    if st.session_state['api_url'] and not st.session_state.get('url_input'):
                        st.session_state['url_input'] = st.session_state['api_url']

                    if 'concurrent_downloads' in config:
                        st.session_state['concurrent_downloads'] = config.get('concurrent_downloads', 5)

                    if 'debug_mode' in config:
                        st.session_state['debug_mode'] = config.get('debug_mode', False)

                    if 'enable_cbs_filters' in config:
                        st.session_state['enable_cbs_filters'] = config.get('enable_cbs_filters', False)

                    if 'error_log_enabled' in config:
                        st.session_state['error_log_enabled'] = config.get('error_log_enabled', False)

                    if 'max_file_size_enabled' in config:
                        st.session_state['max_file_size_enabled'] = config.get('max_file_size_enabled', False)
                    if 'max_file_size_mb' in config:
                        st.session_state['max_file_size_mb'] = int(config.get('max_file_size_mb', 500))

                    if 'archive_max_files_enabled' in config:
                        st.session_state['archive_max_files_enabled'] = config.get('archive_max_files_enabled', False)
                    if 'archive_max_files' in config:
                        st.session_state['archive_max_files'] = int(config.get('archive_max_files', 1000))

                    if 'notifications_enabled' in config:
                        st.session_state['notifications_enabled'] = config.get('notifications_enabled', True)
                    if 'sync_history_retention' in config:
                        st.session_state['sync_history_retention'] = int(config.get('sync_history_retention', 50))

                    if 'use_12h_format' in config:
                        st.session_state['use_12h_format'] = config.get('use_12h_format', False)

                    if 'show_help_text' in config:
                        st.session_state['show_help_text'] = bool(config.get('show_help_text', True))

                    # Mirrored into session state so the Settings dialog's
                    # unsaved-changes check has something to compare against.
                    # panopto.settings.is_globally_enabled() reads the file
                    # directly and stays the source of truth for the engine -
                    # this is a UI convenience, not a second store.
                    if 'panopto_globally_enabled' in config:
                        st.session_state['panopto_globally_enabled'] = bool(
                            config.get('panopto_globally_enabled', True))

                    if 'default_download_path' in config:
                        saved_default = config.get('default_download_path', '') or ''
                        st.session_state['default_download_path'] = saved_default
                        # Pre-fill download_path with the saved default on fresh session
                        import os as _os
                        from pathlib import Path as _Path
                        _downloads_default = str(_Path.home() / "Downloads")
                        current_path = st.session_state.get('download_path', '')
                        if saved_default and _os.path.isdir(saved_default) and current_path == _downloads_default:
                            st.session_state['download_path'] = saved_default

                    loaded_token = ''
                    # Unified keyring load for all platforms with watchdog and fallback.
                    #
                    # This read is on the SCRIPT THREAD, before a single element
                    # has rendered, so it must never be allowed to block: on
                    # macOS an untrusted ACL turns it into a modal prompt and the
                    # window stays empty for as long as it is up. The probe below
                    # cannot prompt (see keyring_get_without_prompting); when it
                    # reports that a prompt IS required we leave the token empty
                    # and let the login screen raise it, explained, off this
                    # thread. Windows takes the same path it always did.
                    try:
                        keyring_user = st.session_state['api_url'] or 'default'
                        loaded_token, _needs_prompt = keyring_get_without_prompting(
                            KEYRING_SERVICE, keyring_user)
                        loaded_token = loaded_token or ''
                        if _needs_prompt:
                            st.session_state['keychain_unlock_pending'] = True
                        if not loaded_token and not _needs_prompt:
                            # Try fallback storage
                            loaded_token = _load_fallback_token(keyring_user) or ''
                    except Exception as _kr_err:
                        logger.warning(f"Keyring/fallback unavailable during token load: {_kr_err}")

                    # Legacy migration: macOS base64 token stored in JSON
                    if not loaded_token and config.get('mac_api_token', ''):
                        try:
                            loaded_token = base64.b64decode(
                                config['mac_api_token'].encode('utf-8')
                            ).decode('utf-8')
                            try:
                                keyring_user = st.session_state['api_url'] or 'default'
                                # Only drop the JSON copy once the token is
                                # PROVABLY retrievable elsewhere. This is the run
                                # that moves a token out of the config file, so a
                                # failed keyring write here used to lose the only
                                # copy - and on macOS the failed write also
                                # cleared whatever was already in the Keychain.
                                if store_token(keyring_user, loaded_token):
                                    config.pop('mac_api_token', None)
                                    write_config_atomically(config)
                            except Exception:
                                pass
                        except Exception:
                            pass

                    # Legacy migration: Windows plain-JSON token
                    if not loaded_token and config.get('api_token', ''):
                        loaded_token = config['api_token']
                        try:
                            keyring_user = st.session_state['api_url'] or 'default'
                            # Same rule as the macOS migration above: the JSON
                            # copy is the only one there is until the store
                            # confirms it holds the token.
                            if store_token(keyring_user, loaded_token):
                                config.pop('api_token', None)
                                write_config_atomically(config)
                        except Exception:
                            pass

                    st.session_state['api_token'] = loaded_token

                    if st.session_state['api_token']:
                        _adopt_restored_token(st.session_state['api_token'])
            except Exception:
                logger.warning("Saved session could not be restored", exc_info=True)


def _adopt_restored_token(token: str) -> None:
    """Validate a token recovered from the credential store and sign in.

    Extracted so the two ways a saved token can arrive - the ordinary
    non-prompting read during init, and a macOS Keychain unlock that resolved
    later - reach EXACTLY the same verdict. Writing this decision twice is how
    the two would come to disagree about what a network blip means.
    """
    st.session_state['api_token'] = token
    cm = CanvasManager(token, st.session_state.get('api_url', ''))
    valid, msg = cm.validate_token()
    if valid:
        st.session_state['is_authenticated'] = True
        st.session_state['user_name'] = msg.split(": ", 1)[1] if ": " in msg else msg
        # No st.rerun() here: this runs during session init,
        # so the SAME run goes on to render the signed-in
        # page. The rerun this replaced was a whole wasted
        # script run against a blank window.
        return
    # The saved token could not be CONFIRMED this launch.
    # Only a genuine AUTH rejection (expired/revoked/401)
    # should drop the user to the login page - that is the
    # one case a fresh token actually fixes. Everything
    # else is a TRANSIENT reachability failure (offline,
    # captive-portal wifi, a cross-continent timeout, a
    # corporate/university TLS intercept, or Canvas being
    # momentarily down) - none of which the user can fix
    # by re-pasting the same token, and all of which would
    # otherwise strand a valid, previously-verified
    # session behind a blip. So restore OPTIMISTICALLY:
    # trust the token (it validated on a prior launch),
    # and let the first real Canvas call be the arbiter -
    # a truly dead token surfaces there as an auth error
    # and is routed to the clean reconnect flow
    # (force_reauth), while a still-offline launch gets a
    # calm, retryable "couldn't reach Canvas" screen
    # instead of a red traceback. This is the single most
    # important robustness property of the login path for
    # users on unreliable or high-latency networks.
    from core.canvas_logic import is_auth_error
    if is_auth_error(msg):
        logger.info("Saved token rejected (auth error) - "
                    "routing to login for a fresh token.")
    else:
        st.session_state['is_authenticated'] = True
        logger.info(
            "Saved session restored optimistically; the "
            "token could not be confirmed this launch due "
            "to a non-auth (network) error: %s", msg)


def adopt_pending_keychain_unlock() -> bool:
    """Finish a sign-in whose Keychain prompt the user has now answered.

    Called once per rerun from ``app.py`` right after ``restore_saved_session``.
    It is the ONLY thing that turns a resolved background unlock into a signed-in
    session, and it is deliberately a separate pass rather than re-entering
    ``restore_saved_session`` - that function adopts the config's settings and
    must stay once-per-session.

    Returns True when it signed the user in, so the caller can decide whether the
    rest of the run still needs the login page.
    """
    if not st.session_state.get('keychain_unlock_pending'):
        return False
    if st.session_state.get('is_authenticated'):
        st.session_state['keychain_unlock_pending'] = False
        return False
    status = keychain_unlock_status()
    if status == 'running' or status == 'idle':
        return False
    if status != 'ok':
        # Denied, or the store failed. Stop waiting: the login screen owns the
        # explanation from here, and the token field below it still works.
        st.session_state['keychain_unlock_pending'] = False
        st.session_state['keychain_unlock_failed'] = status
        return False
    token = unlocked_token()
    st.session_state['keychain_unlock_pending'] = False
    if not token:
        return False
    try:
        _adopt_restored_token(token)
    except Exception:
        logger.warning("Could not adopt the unlocked Keychain token", exc_info=True)
        return False
    return bool(st.session_state.get('is_authenticated'))


_KC_LOCK_SVG = (
    "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='currentColor' "
    "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
    "<rect x='3' y='11' width='18' height='11' rx='2' ry='2'/>"
    "<path d='M7 11V7a5 5 0 0 1 10 0v4'/></svg>"
)


def _kc_notice_html(state: str) -> str:
    """Markup for the Keychain notice. ONE element, every state.

    Every character here is a literal - no Canvas data, no user data, nothing
    interpolated - which is what makes the raw-HTML render safe by construction
    rather than by an escaping call someone could later drop.

    The copy is doing real work, so it is worth saying what each line is for.
    A student who has just updated the app meets a system dialog claiming an app
    wants their "confidential information" and demanding their Mac password; the
    honest default reaction is to refuse. So the notice (a) says WE caused it and
    nothing is lost, (b) says the password goes to macOS and not to us, (c) names
    the exact button, and (d) offers a way out that still works. Point (c) is not
    a nicety: MEASURED on macOS 26.6.1, plain "Allow" leaves the item's ACL
    untouched, so the prompt returns on EVERY launch, while "Always Allow"
    updates it and the prompt does not come back until the next update.
    """
    if state == 'checking':
        return (
            "<div class='kc-notice kc-notice-quiet'>"
            f"<div class='kc-head'>{_KC_LOCK_SVG}"
            "<span>Checking your saved sign-in…</span>"
            "<span class='kc-spin'></span></div></div>"
        )
    if state == 'denied':
        return (
            "<div class='kc-notice'>"
            f"<div class='kc-head'>{_KC_LOCK_SVG}"
            "<span>Your saved sign-in stayed locked</span></div>"
            "<div class='kc-body'>macOS kept your saved Canvas login locked, so it "
            "wasn't used. <b>Nothing is lost</b> - it is still in your Keychain.</div>"
            "<ul class='kc-steps'>"
            "<li>To use it: quit Canvas Downloader, open it again, and choose "
            "<b>Always Allow</b>.</li>"
            "<li>Or paste a Canvas access token below to carry on right now.</li>"
            "</ul></div>"
        )
    if state == 'error':
        return (
            "<div class='kc-notice'>"
            f"<div class='kc-head'>{_KC_LOCK_SVG}"
            "<span>Couldn't read your saved sign-in</span></div>"
            "<div class='kc-body'>macOS did not hand over your saved Canvas login "
            "this time. Paste a token below to continue - your saved one is "
            "untouched, and the next launch will try again.</div></div>"
        )
    # 'waiting' - the prompt is on screen right now.
    return (
        "<div class='kc-notice'>"
        f"<div class='kc-head'>{_KC_LOCK_SVG}"
        "<span>macOS is asking permission - this is expected</span></div>"
        "<div class='kc-body'>Canvas Downloader was updated, so macOS sees a new "
        "version and is asking whether it may reuse the Canvas login you already "
        "saved. <b>You have not been logged out and nothing is lost.</b></div>"
        "<ul class='kc-steps'>"
        "<li>In the macOS dialog, type your <b>Mac login password</b> - it goes "
        "to macOS, never to Canvas Downloader.</li>"
        "<li>Click <b>Always Allow</b>. Plain <i>Allow</i> works only once, and "
        "macOS will ask you again every time you open the app.</li>"
        "<li>Would rather not? Click <b>Deny</b> and paste a Canvas token below "
        "instead - everything still works.</li>"
        "</ul>"
        "<div class='kc-foot'><span class='kc-spin'></span>"
        "Waiting for your answer - this screen continues on its own.</div></div>"
    )


@st.fragment(run_every=1.0)
def _kc_unlock_poll() -> None:
    """Poll the background unlock while the prompt is up.

    A fragment, so the wait costs one small rerun a second instead of holding the
    script thread. It emits EXACTLY ONE element in every state it renders, and
    deliberately writes nothing to the event container - no style-only st.html,
    no st.toast - because a fragment rerun rewinds that container's write index
    and an extra write there would land on a neighbouring stylesheet's host.
    """
    status = keychain_unlock_status()
    if status in ('ok', 'denied', 'error'):
        # Terminal: hand back to a full run, where adopt_pending_keychain_unlock
        # either signs the user in or records why it could not.
        st.rerun(scope="app")
    st.markdown(_kc_notice_html('waiting' if status == 'running' else 'checking'),
                unsafe_allow_html=True)


def render_keychain_unlock_notice() -> None:
    """Explain the macOS Keychain prompt, above the login form.

    Renders nothing at all off macOS, and nothing on macOS unless a saved token
    genuinely could not be read without prompting - so the ordinary login screen
    is untouched.
    """
    pending = bool(st.session_state.get('keychain_unlock_pending'))
    failed = st.session_state.get('keychain_unlock_failed') or ''
    if not pending and not failed:
        return
    # One keyed slot holding exactly one child in either branch, so the elements
    # BELOW it never shift when the notice changes state - Streamlit reconciles
    # by position and hands a block the children of whatever sat at its index.
    with st.container(key="kc_unlock_slot"):
        if pending:
            _kc_unlock_poll()
        else:
            st.markdown(_kc_notice_html('denied' if failed == 'denied' else 'error'),
                        unsafe_allow_html=True)


def render_login_page(fetch_courses_fn):
    """Render the full-page, premium login portal in the main page body."""
    # Normally already done during session init (app.py). Kept as a guard so the
    # login page is still correct if it is ever reached by another route.
    restore_saved_session()
    if st.session_state.get('is_authenticated'):
        return

    from shared.helpers import get_base64_image, help_text_enabled
    from ui import institution_picker

    icon_b64 = get_base64_image("assets/icon.png")

    # Scoped physical volume styles for the main page login card
    st.html("""<style>
    /* Centered portal container */
    .login-portal-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        max-width: 480px;
        margin: clamp(5px, 2vh, 20px) auto 0 auto;
        padding: 0 10px;
    }

    /* Branded Header */
    .login-brand-header {
        text-align: center;
        margin-bottom: clamp(5px, 1.5vh, 15px);
    }

    .login-brand-logo {
        width: 56px;
        height: 56px;
        border-radius: 12px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45), inset 0 1px 1px rgba(255, 255, 255, 0.15);
        margin-bottom: clamp(4px, 1vh, 8px);
        display: inline-block;
    }

    .login-brand-title {
        font-size: 1.8rem;
        font-weight: 800;
        color: #f1f5f9;
        letter-spacing: -0.02em;
        line-height: 1.1;
    }

    .login-brand-subtitle {
        font-size: 0.9rem;
        color: #64748b;
        margin-top: 6px;
    }

    /* The "Physical Volume" card tray */
    div[class*="st-key-login_card_wrapper"] {
        background: #151c24 !important; /* Shade or two lighter than #0d1117, teal-ish blue */
        border: none !important;
        border-radius: 12px !important;
        box-shadow: 0 0px 50px rgba(0, 0, 0, 0.5) !important;
        padding: 20px 24px !important;
        width: 100% !important;
    }

    div[class*="st-key-login_card_wrapper"] > div[data-testid="stVerticalBlock"] {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        padding: 0 !important;
    }

    /* Add borders around the input fields inside the card */
    div[class*="st-key-login_card_wrapper"] div[data-testid="stTextInput"] [data-baseweb="input"] {
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        background-color: rgba(0, 0, 0, 0.2) !important;
        border-radius: 6px !important;
        transition: border-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
        overflow: hidden !important;
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stTextInput"] [data-baseweb="base-input"],
    div[class*="st-key-login_card_wrapper"] div[data-testid="stTextInput"] input {
        background-color: transparent !important;
    }

    /* Hide native browser password reveal eyes (e.g. Edge) to prevent duplicate double-eyes */
    div[class*="st-key-login_card_wrapper"] div[data-testid="stTextInput"] input::-ms-reveal,
    div[class*="st-key-login_card_wrapper"] div[data-testid="stTextInput"] input::-ms-clear {
        display: none !important;
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stTextInput"] [data-baseweb="input"]:focus-within {
        border-color: #1f77b4 !important;
        box-shadow: 0 0 0 2px rgba(31, 119, 180, 0.2) !important;
    }

    /* Style Streamlit's native help trigger button/icon next to the label */
    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] {
        display: flex !important;
        justify-content: flex-start !important;
        align-items: center !important;
        gap: 6px !important;
        width: 100% !important;
        position: relative !important;
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] label {
        margin: 0 !important;
        flex: 0 0 auto !important;
    }

    /* The help "?" belongs NEXT TO the label, not at the far end of the row.
       Measured in 1.51: the widget label is itself a LABEL element (so every
       rule above that says div + that testid matches nothing here), and it
       holds two children - the label text, and an UNNAMED wrapper carrying
       the tooltip icon at `flex: 1 1 0%; justify-content: flex-end`. That
       wrapper is what pushed the icon 343px away from the word it explains.
       Collapsing it to its content is the whole fix; the margin restores the
       gap the flex-grow used to provide.

       Direct-child `:has(> ...)`: the descendant form would also match every
       ancestor that merely CONTAINS a tooltip icon. Only the token field has
       a help tooltip on this page, so nothing else moves. */
    div[class*="st-key-login_card_wrapper"]
        [data-testid="stWidgetLabel"] > div:has(> [data-testid="stTooltipIcon"]) {
        flex: 0 0 auto !important;
        justify-content: flex-start !important;
        margin-left: 6px !important;
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] div[data-testid="stTooltipHoverTarget"] {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        margin: 0 !important;
        flex: 0 0 auto !important;
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] div[data-testid="stTooltipHoverTarget"] button {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        margin: 0 !important;
        min-height: unset !important;
        min-width: unset !important;
        height: auto !important;
        width: auto !important;
        display: flex !important;
        align-items: center !important;
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] div[data-testid="stTooltipHoverTarget"] button [data-testid="stIconMaterial"],
    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] div[data-testid="stTooltipHoverTarget"] button svg {
        display: none !important; /* Hide native icon */
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] div[data-testid="stTooltipHoverTarget"] button::before {
        content: "";
        display: inline-block;
        width: 16px;
        height: 16px;
        background-color: rgba(255, 255, 255, 0.4) !important;
        -webkit-mask-image: url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnIHdpZHRoPScxNicgaGVpZ2h0PScxNicgdmlld0JveD0nMCAwIDI0IDI0JyBmaWxsPSdub25lJyBzdHJva2U9J2N1cnJlbnRDb2xvcicgc3Ryb2tlLXdpZHRoPScyLjUnIHN0cm9rZS1saW5lY2FwPSdyb3VuZCcgc3Ryb2tlLWxpbmVqb2luPSdyb3VuZCc+PGNpcmNsZSBjeD0nMTInIGN5PScxMicgcj0nMTAnPjwvY2lyY2xlPjxwYXRoIGQ9J005LjA5IDlhMyAzIDAgMCAxIDUuODMgMWMwIDItMyAzLTMgMyc+PC9wYXRoPjxsaW5lIHgxPScxMicgeTE9JzE3JyB4Mj0nMTIuMDEnIHkyPScxNyc+PC9saW5lPjwvc3ZnPg==') !important;
        mask-image: url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnIHdpZHRoPScxNicgaGVpZ2h0PScxNicgdmlld0JveD0nMCAwIDI0IDI0JyBmaWxsPSdub25lJyBzdHJva2U9J2N1cnJlbnRDb2xvcicgc3Ryb2tlLXdpZHRoPScyLjUnIHN0cm9rZS1saW5lY2FwPSdyb3VuZCcgc3Ryb2tlLWxpbmVqb2luPSdyb3VuZCc+PGNpcmNsZSBjeD0nMTInIGN5PScxMicgcj0nMTAnPjwvY2lyY2xlPjxwYXRoIGQ9J005LjA5IDlhMyAzIDAgMCAxIDUuODMgMWMwIDItMyAzLTMgMyc+PC9wYXRoPjxsaW5lIHgxPScxMicgeTE9JzE3JyB4Mj0nMTIuMDEnIHkyPScxNyc+PC9saW5lPjwvc3ZnPg==') !important;
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-position: center;
        transition: background-color 0.15s ease !important;
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] div[data-testid="stTooltipHoverTarget"] button:hover::before {
        background-color: #60a5fa !important; /* Thicker and lighter blue color on hover */
    }

    /* Native Streamlit Tooltip Overrides */
    div[data-baseweb="tooltip"],
    div[data-baseweb="popover"] {
        background: transparent !important;
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        margin: 0 !important;
        max-height: none !important;
        height: auto !important;
        overflow: visible !important;
    }

    div[role="tooltip"] {
        background-color: #181c20 !important; /* Neutral dark grey */
        border: 1px solid rgba(255, 255, 255, 0.15) !important; /* Clean white border */
        border-radius: 8px !important;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5) !important;
        padding: 20px !important; /* Uniform, harmonious padding on all sides */
        width: 320px !important; /* Fixed elegant width */
        box-sizing: border-box !important;
        max-height: none !important;
        height: auto !important;
        overflow: visible !important;
    }

    div[role="tooltip"] * {
        max-height: none !important;
        height: auto !important;
        overflow: visible !important;
        background-color: transparent !important;
    }

    div[role="tooltip"] div,
    div[role="tooltip"] span {
        margin: 0 !important;
        padding: 0 !important;
    }

    div[role="tooltip"] p {
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        font-size: 0.85rem !important;
        line-height: 1.5 !important;
        color: #ffffff !important;
        margin: 0 !important; /* Reset margins on text lines for absolute symmetry */
        padding: 0 !important;
    }

    div[role="tooltip"] p + p {
        margin-top: 14px !important; /* Spacing between sections */
    }

    .login-brand-header-separator {
        width: 160px !important;
        height: 1px !important;
        background-color: rgba(255, 255, 255, 0.12) !important;
        margin: clamp(1vh, 2vh, 16px) auto clamp(0.5vh, 1.5vh, 12px) auto !important;
    }

    .login-github-header-tag {
        margin-top: 0px !important;
        margin-bottom: clamp(1vh, 3vh, 28px) !important; /* Spacing below the github tag to the login form */
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        gap: 16px !important; /* Spacing between the tags */
        width: 100% !important;
    }

    .github-link {
        display: inline-flex !important;
        align-items: center !important;
        gap: 6px !important;
        color: #64748b !important;
        text-decoration: none !important;
        font-size: 0.8rem !important;
        font-weight: 500 !important;
        transition: color 0.2s ease-in-out !important;
    }

    .github-link:hover {
        color: #f1f5f9 !important;
    }

    .github-icon {
        opacity: 0.85 !important;
    }

    /* The video is now the LAST RESORT, so it has to look like a control.
       Deleting the token expander left it as the only walkthrough on the page
       beyond the two lines under the field - and it was drawn as grey text on
       a 4%-white slab with a grey glyph, i.e. the quietest thing on a dark
       screen. A confused user found it late or not at all.

       Three changes, no new colour: the YouTube red the icon already used on
       hover is on at rest (that red IS the recognition - a grey play button is
       just a triangle); the text steps up to the same #b8c5d6 as the rest of
       the card's body copy; and the slab gains enough contrast to read as a
       button. It stays a quiet button, not a second CTA - it competes with
       nothing above it, because there is nothing above it any more. */
    .youtube-link {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 9px !important;
        color: #b8c5d6 !important;
        text-decoration: none !important;
        font-size: 0.85rem !important;
        font-weight: 600 !important;
        transition: all 0.2s ease-in-out !important;
        margin: clamp(1vh, 2vh, 16px) auto 0 auto !important;
        max-width: fit-content !important;
        background-color: rgba(255, 255, 255, 0.06) !important;
        border: 1px solid rgba(255, 255, 255, 0.14) !important;
        border-radius: 8px !important;
        padding: 8px 16px !important;
    }

    .youtube-link:hover {
        color: #ffffff !important;
        background-color: rgba(255, 255, 255, 0.10) !important;
        border-color: rgba(239, 68, 68, 0.45) !important;
    }

    .youtube-icon {
        color: #ef4444 !important;
        transition: transform 0.2s ease-in-out !important;
    }

    .youtube-link:hover .youtube-icon {
        transform: scale(1.12) !important;
    }


    .login-page-security-footer {
        font-size: 0.84rem !important;
        color: #64748b !important;
        text-align: center !important;
        margin-top: clamp(1.5vh, 4vh, 36px) !important;
        margin-bottom: 4px !important;
        max-width: 480px !important;
        margin-left: auto !important;
        margin-right: auto !important;
        line-height: 1.55 !important;
        display: flex !important;
        align-items: flex-start !important;
        justify-content: center !important;
        gap: 8px !important;
    }

    .security-shield-icon {
        color: #8a99ad !important;
        flex-shrink: 0 !important;
        margin-top: 2px !important;
        opacity: 0.8 !important;
    }

    .login-form-title {
        font-size: 1.3rem;
        font-weight: 700;
        color: #ffffff;
        margin-bottom: clamp(1vh, 2.5vh, 20px);
        letter-spacing: -0.01em;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        padding-bottom: 12px;
    }

    /* Submit Button styling: Solid Blue Physical Volume matching Analyze, Review & Sync */
    div.st-key-login_submit_btn button {
        background-color: #1f77b4 !important;
        border: none !important;
        border-radius: 6px !important;
        color: #ffffff !important;
        box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3) !important;
        font-size: 1rem !important;
        font-weight: 600 !important;
        height: 3.2em !important;
        min-height: 3.2em !important;
        width: 100% !important;
        transition: background-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
    }

    div.st-key-login_submit_btn button:hover {
        background-color: #2b8cbe !important;
        box-shadow: 0 4px 15px rgba(31, 119, 180, 0.2),
                    inset 0 1px 1px rgba(255, 255, 255, 0.4) !important;
        color: #ffffff !important;
    }

    /* RECURSIVE CENTERING: START - Universal child selector */
    div.st-key-login_submit_btn button > div,
    div.st-key-login_submit_btn button > div > p {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        text-align: center !important;
        width: 100% !important;
        height: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div.st-key-login_submit_btn button p {
        font-size: 1rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
    }

    /* Scoped styling for help expanders */
    div[class*="st-key-login_help_expanders"] {
        max-width: 480px !important;
        margin: 0 auto !important;
        width: 100% !important;
    }

    /* Remove borders, backgrounds, and shadows from expanders inside this container */
    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        margin-bottom: 0px !important;
        padding: 0 !important;
    }

    /* Target details and summary to remove all borders/backgrounds */
    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] details {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
    }

    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        padding-left: 0px !important;
        padding-right: 0px !important;
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        gap: 8px !important;
        width: 100% !important;
    }

    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary > * {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        flex-grow: 0 !important;
        width: auto !important;
        margin: 0 !important;
        gap: 8px !important;
    }

    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary > * > * {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        flex-grow: 0 !important;
        width: auto !important;
        margin: 0 !important;
    }

    /* Style the summary text inside modern Streamlit expander */
    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary p {
        color: #94a3b8 !important; /* Elegant muted color */
        font-weight: 500 !important;
        transition: color 0.2s ease-in-out !important;
        text-align: center !important;
    }

    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary:hover p {
        color: #f1f5f9 !important; /* Brighter on hover */
    }

    /* Style the chevron arrow inside help expanders to match the grey text */
    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary svg {
        color: #94a3b8 !important;
        transition: color 0.1s ease-in-out !important;
    }

    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary:hover svg {
        color: #f1f5f9 !important;
    }

    /* Turn header text & chevron white when help expanders are open/expanded */
    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] details[open] summary p {
        color: #ffffff !important;
    }
    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] details[open] summary svg {
        color: #ffffff !important;
    }

    /* Reset Streamlit flex block gap inside the help expanders for precise spacing control */
    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] div[data-testid="stVerticalBlock"] {
        gap: 0px !important;
    }

    /* Style inline code blocks to look like soft, non-nerdy badges/pills */
    div[class*="st-key-login_help_expanders"] code {
        color: #93c5fd !important;
        background-color: rgba(147, 197, 253, 0.1) !important;
        border: 1px solid rgba(147, 197, 253, 0.25) !important;
        padding: 2px 5px !important;
        border-radius: 4px !important;
        font-family: inherit !important;
        font-size: 0.9em !important;
        font-weight: 600 !important;
    }

    /* Reset Streamlit flex block gap inside the footer container for precise spacing control */
    div[class*="st-key-login_footer_container"] div[data-testid="stVerticalBlock"] {
        gap: 0px !important;
    }

    /* Scoped styling for the privacy expander */
    div[class*="st-key-login_privacy_expander"] {
        max-width: 420px !important;
        margin: 0 auto !important;
        width: 100% !important;
    }

    .login-privacy-separator {
        width: 160px !important;
        height: 1px !important;
        background-color: rgba(255, 255, 255, 0.08) !important;
        margin: clamp(0.5vh, 2vh, 18px) auto !important; 
    }

    .login-privacy-separator-bottom {
        margin-top: 0px !important; /* Pull visually closer to the privacy expander above it */
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        margin-bottom: 0px !important;
        padding: 0 !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] details {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        padding-left: 0px !important;
        padding-right: 0px !important;
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        gap: 8px !important;
        width: 100% !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary > * {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        flex-grow: 0 !important;
        width: auto !important;
        margin: 0 !important;
        gap: 8px !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary > * > * {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        flex-grow: 0 !important;
        width: auto !important;
        margin: 0 !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary p {
        font-size: 0.86rem !important;
        color: #64748b !important; /* Elegant muted slate color */
        font-weight: 600 !important; /* Semi-bold */
        transition: color 0.2s ease-in-out !important;
        text-align: center !important;
        width: 100% !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary p::before {
        content: "" !important;
        display: inline-block !important;
        width: 14px !important;
        height: 14px !important;
        margin-right: 6px !important;
        background-color: currentColor !important;
        -webkit-mask: url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2024%2024%22%3E%3Cpath%20d%3D%22M12%2022s8-4%208-10V5l-8-3-8%203v7c0%206%208%2010%208%2010z%22%2F%3E%3C%2Fsvg%3E') no-repeat center / contain !important;
        mask: url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2024%2024%22%3E%3Cpath%20d%3D%22M12%2022s8-4%208-10V5l-8-3-8%203v7c0%206%208%2010%208%2010z%22%2F%3E%3C%2Fsvg%3E') no-repeat center / contain !important;
        flex-shrink: 0 !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary:hover p {
        color: #f1f5f9 !important; /* Brighter slate on hover */
    }

    /* Style the chevron arrow inside the privacy expander to match the grey text */
    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary svg {
        color: #64748b !important;
        transition: color 0.1s ease-in-out !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary:hover svg {
        color: #f1f5f9 !important;
    }

    /* Turn header text, mask shield icon, & chevron white when privacy expander is open/expanded */
    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] details[open] summary p {
        color: #ffffff !important;
    }
    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] details[open] summary svg {
        color: #ffffff !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] [data-testid="stMarkdownContainer"] {
        font-size: 0.88rem !important;
        line-height: 1.55 !important;
        color: #b8c5d6 !important;
    }

    /* Custom styles for precise list items and spacing */
    .privacy-list-item {
        display: flex !important;
        align-items: flex-start !important;
        justify-content: flex-start !important;
        gap: 8px !important;
        margin-bottom: 12px !important;
        text-align: left !important;
    }
    .privacy-list-icon {
        color: #8a99ad !important;
        flex-shrink: 0 !important;
        margin-top: 3px !important;
        width: 14px !important;
        height: 14px !important;
        overflow: visible !important;
    }
    .privacy-list-content {
        flex: 1 !important;
    }
    .privacy-list-title {
        font-weight: 700 !important;
        color: #b8c5d6 !important; /* Soft grey aesthetic */
        font-size: 0.88rem !important;
        margin-bottom: 1px !important;
    }
    .privacy-list-desc {
        font-size: 0.88rem !important;
        line-height: 1.45 !important;
        color: #b8c5d6 !important; /* Matches title color precisely */
    }
    .privacy-list-desc a {
        color: #1f77b4 !important;
        text-decoration: none !important;
        font-weight: 600 !important;
        transition: color 0.2s ease-in-out !important;
    }
    .privacy-list-desc a:hover {
        color: #2ba2ec !important;
        text-decoration: underline !important;
    }
    .login-student-signature {
        text-align: center !important;
        font-size: 0.78rem !important;
        color: #475569 !important; /* Soft, very muted slate color */
        margin-top: 0px !important; /* Matches exactly the 18px bottom margin of the separator above it */
        margin-bottom: clamp(0.5vh, 2.5vh, 20px) !important;
        font-weight: 500 !important;
        letter-spacing: 0.01em !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 6px !important;
        transition: color 0.2s ease-in-out !important;
    }
    .login-student-signature:hover {
        color: #64748b !important; /* Slightly brighter on hover */
    }
    .signature-heart-icon {
        color: #f97316 !important; /* Premium warm orange colored heart */
        opacity: 0.8 !important;
        flex-shrink: 0 !important;
        overflow: visible !important;
        transition: transform 0.2s ease-in-out, opacity 0.2s ease-in-out !important;
    }
    .login-student-signature:hover .signature-heart-icon {
        transform: scale(1.1) !important; /* Delicate heart scale pulse on hover */
        opacity: 1 !important;
    }

    /* First-run "getting started" strip - shown only when there is no saved
       config (a truly fresh install). Turns the bare credential form into a
       short, guided first run and pre-empts the "is this safe?" fear. */
    .login-getstarted {
        background: rgba(31, 119, 180, 0.06) !important;
        border: 1px solid rgba(31, 119, 180, 0.22) !important;
        border-radius: 8px !important;
        padding: 10px 14px 12px 14px !important;
        /* Top margin is NEGATIVE on purpose: it collapses with the title's
           20px margin-bottom, so only a negative value can shrink the gap
           above the strip. Bottom margin gives the URL field real breathing
           room (was glued 4px below). Balanced ~14px on each side. */
        margin: -6px 0 14px 0 !important;
    }
    .lgs-head {
        font-size: 0.9rem !important;
        font-weight: 700 !important;
        color: #cfe0f0 !important;
        margin-bottom: 8px !important;
    }
    /* .lgs-step / .lgs-num are GONE with the three numbered steps - see the
       comment on _getstarted_html. Nothing else used them. */
    .lgs-safe {
        display: flex !important;
        align-items: flex-start !important;
        gap: 7px !important;
        padding-top: 8px !important;
        border-top: 1px solid rgba(255, 255, 255, 0.07) !important;
        font-size: 0.8rem !important;
        line-height: 1.4 !important;
        color: #8a99ad !important;
    }
    .lgs-safe svg {
        flex: 0 0 auto !important;
        margin-top: 2px !important;
        color: #8a99ad !important;
    }

    /* Cut-to-the-bone reconnect header (reauth mode): the token expired
       mid-use, the URL is already known, so this replaces the full login
       header with just a reason + the saved URL + a nudge to paste a token. */
    .lra-title {
        font-size: 1.3rem !important;
        font-weight: 700 !important;
        color: #ffffff !important;
        letter-spacing: -0.01em !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06) !important;
        padding-bottom: 12px !important;
        margin-bottom: 14px !important;
    }
    .lra-reason {
        display: flex !important;
        align-items: flex-start !important;
        gap: 9px !important;
        background: rgba(249, 115, 22, 0.10) !important;
        border: 1px solid rgba(249, 115, 22, 0.35) !important;
        border-radius: 8px !important;
        padding: 11px 13px !important;
        color: #fcd9b6 !important;
        font-size: 0.9rem !important;
        line-height: 1.5 !important;
        margin-bottom: 14px !important;
    }
    .lra-reason svg { flex: 0 0 auto !important; margin-top: 2px !important; }
    .lra-url {
        font-size: 0.85rem !important;
        color: #94a3b8 !important;
        margin-bottom: 8px !important;
        display: flex !important;
        align-items: center !important;
        flex-wrap: wrap !important;
        gap: 6px !important;
    }
    .lra-url-chip {
        color: #93c5fd !important;
        background: rgba(147, 197, 253, 0.1) !important;
        border: 1px solid rgba(147, 197, 253, 0.25) !important;
        padding: 2px 8px !important;
        border-radius: 5px !important;
        font-weight: 600 !important;
        word-break: break-all !important;
    }
    .lra-hint {
        font-size: 0.9rem !important;
        color: #b8c5d6 !important;
        line-height: 1.5 !important;
    }
    /* The "use the full sign-in screen" escape - a quiet, link-like button */
    div[class*="st-key-reauth_full_login"] button {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: #64748b !important;
        font-size: 0.85rem !important;
        font-weight: 500 !important;
        min-height: unset !important;
        height: auto !important;
        padding: 4px 6px !important;
        text-decoration: underline !important;
        text-underline-offset: 3px !important;
        transition: color 0.15s ease !important;
    }
    div[class*="st-key-reauth_full_login"] button:hover {
        color: #cbd5e1 !important;
        background: transparent !important;
    }

    /* ── Institution picker ────────────────────────────────────────────────
       A searchable directory sitting to the RIGHT of the Canvas URL field.
       Picking writes into that field; the field itself stays fully editable,
       so the picker is a shortcut and never a gate.

       It is hand-built markup rather than st.selectbox for two reasons: a
       Streamlit widget inside st.form cannot rerun, so a native picker could
       not fill the field until submit; and the baseweb select cannot be
       styled into this card without fighting its portal. Both buttons and the
       search input are inside a real form element, so every control carries
       type="button" and the bridge swallows Enter - otherwise clicking an
       option would SUBMIT the login form. (Note the deliberate absence of an
       angle-bracket tag name in this comment: one would close the style
       element early and silently kill every rule below it.) */
    div[class*="st-key-login_card_wrapper"] .cd-inst {
        position: relative !important;
        width: 100% !important;
    }
    /* The row's markdown must not shrink its own container: Streamlit puts
       margin-bottom:-16px on every stMarkdownContainer, which would pull the
       trigger up out of alignment with the input beside it. */
    div[class*="st-key-login_card_wrapper"]
        [data-testid="stMarkdownContainer"]:has(> .cd-inst) {
        margin-bottom: 0 !important;
    }
    /* The panel is absolutely positioned, so every ancestor between it and the
       card must not clip. Streamlit's column/block wrappers default to visible,
       but the keyed card sets overflow on its inputs - restate it here so a
       future change to the card cannot silently crop the dropdown. */
    div[class*="st-key-login_card_wrapper"] div[data-testid="stHorizontalBlock"],
    div[class*="st-key-login_card_wrapper"] div[data-testid="stColumn"] {
        overflow: visible !important;
    }

    div[class*="st-key-login_card_wrapper"] .cd-inst-trigger {
        display: flex !important;
        align-items: center !important;
        gap: 8px !important;
        width: 100% !important;
        height: 40px !important;
        padding: 0 10px !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 6px !important;
        background-color: rgba(0, 0, 0, 0.2) !important;
        color: #b8c5d6 !important;
        font-size: 0.86rem !important;
        font-weight: 500 !important;
        font-family: inherit !important;
        cursor: pointer !important;
        text-align: left !important;
        transition: border-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out,
                    background-color 0.2s ease-in-out !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-trigger:hover {
        border-color: rgba(255, 255, 255, 0.22) !important;
        background-color: rgba(0, 0, 0, 0.28) !important;
        color: #cfe0f0 !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst[data-open="1"] .cd-inst-trigger {
        border-color: #1f77b4 !important;
        box-shadow: 0 0 0 2px rgba(31, 119, 180, 0.2) !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-ico {
        flex: 0 0 auto !important;
        color: #64748b !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst[data-picked="1"] .cd-inst-ico {
        color: #4ade80 !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-label {
        flex: 1 1 auto !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        white-space: nowrap !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-chev {
        flex: 0 0 auto !important;
        color: #64748b !important;
        transition: transform 0.18s ease !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst[data-open="1"] .cd-inst-chev {
        transform: rotate(180deg) !important;
    }

    div[class*="st-key-login_card_wrapper"] .cd-inst-panel {
        display: none !important;
        position: absolute !important;
        top: calc(100% + 6px) !important;
        right: 0 !important;
        width: min(430px, 86vw) !important;
        z-index: 60 !important;
        background: #1a222c !important;
        border: 1px solid rgba(255, 255, 255, 0.14) !important;
        border-radius: 8px !important;
        box-shadow: 0 18px 40px -8px rgba(0, 0, 0, 0.65) !important;
        padding: 8px !important;
        box-sizing: border-box !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst[data-open="1"] .cd-inst-panel {
        display: block !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-searchwrap {
        display: flex !important;
        align-items: center !important;
        gap: 8px !important;
        padding: 0 9px !important;
        height: 36px !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 6px !important;
        background-color: rgba(0, 0, 0, 0.25) !important;
        margin-bottom: 8px !important;
        transition: border-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-searchwrap:focus-within {
        border-color: #1f77b4 !important;
        box-shadow: 0 0 0 2px rgba(31, 119, 180, 0.2) !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-searchwrap svg {
        flex: 0 0 auto !important;
        color: #64748b !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-input {
        flex: 1 1 auto !important;
        min-width: 0 !important;
        border: none !important;
        outline: none !important;
        background: transparent !important;
        color: #e2e8f0 !important;
        font-size: 0.86rem !important;
        font-family: inherit !important;
        padding: 0 !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-input::placeholder {
        color: #64748b !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-list {
        max-height: 264px !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        scrollbar-width: thin !important;
        scrollbar-color: rgba(255, 255, 255, 0.18) transparent !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-list::-webkit-scrollbar {
        width: 8px !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-list::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.18) !important;
        border-radius: 4px !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-opt {
        display: flex !important;
        flex-direction: column !important;
        align-items: flex-start !important;
        gap: 1px !important;
        width: 100% !important;
        padding: 7px 9px !important;
        border: none !important;
        border-radius: 6px !important;
        background: transparent !important;
        color: #e2e8f0 !important;
        font-family: inherit !important;
        text-align: left !important;
        cursor: pointer !important;
        transition: background-color 0.12s ease !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-opt:hover {
        background-color: rgba(31, 119, 180, 0.20) !important;
    }
    /* The KEYBOARD-active row is deliberately stronger than hover and carries a
       left rail: with a mouse hover and an arrow-key cursor both on screen, two
       identical highlights make it impossible to tell which one Enter takes. */
    div[class*="st-key-login_card_wrapper"] .cd-inst-opt[data-active="1"] {
        background-color: rgba(31, 119, 180, 0.32) !important;
        box-shadow: inset 3px 0 0 0 #4da8da !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-opt[hidden] {
        display: none !important;
    }
    /* Search-term highlighting. `mark` is a real element, so it must be
       repainted for a dark surface or it renders as black-on-yellow. */
    div[class*="st-key-login_card_wrapper"] .cd-inst-opt mark {
        background: rgba(77, 168, 218, 0.28) !important;
        color: #ffffff !important;
        border-radius: 3px !important;
        padding: 0 1px !important;
    }
    /* Live result count. Fixed height so a query that goes from matches to no
       matches cannot change the panel's height and shift the list under the
       pointer mid-selection. */
    div[class*="st-key-login_card_wrapper"] .cd-inst-meta {
        height: 15px !important;
        margin: 0 2px 6px 2px !important;
        font-size: 0.72rem !important;
        line-height: 15px !important;
        color: #64748b !important;
        overflow: hidden !important;
        white-space: nowrap !important;
        text-overflow: ellipsis !important;
    }
    /* With no matches the count row has nothing to say, and its reserved height
       plus margin sat as ~21px of dead space above the "Not in the list"
       panel. The height is only reserved to stop the list jumping BETWEEN
       result counts - a state with no list at all does not need it. */
    div[class*="st-key-login_card_wrapper"] .cd-inst[data-empty="1"] .cd-inst-meta {
        display: none !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst[data-empty="1"] .cd-inst-list {
        display: none !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-nm {
        font-size: 0.86rem !important;
        font-weight: 600 !important;
        line-height: 1.3 !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-dm {
        font-size: 0.75rem !important;
        color: #64748b !important;
        line-height: 1.3 !important;
    }
    /* Empty state. Worded as an instruction, not a failure: a student whose
       school is missing must not read it as "this app does not support me". */
    div[class*="st-key-login_card_wrapper"] .cd-inst-none {
        display: none !important;
        padding: 2px 10px 8px 10px !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst[data-empty="1"] .cd-inst-none {
        display: block !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-none-h {
        font-size: 0.85rem !important;
        font-weight: 700 !important;
        color: #cfe0f0 !important;
        margin-bottom: 5px !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-none-b {
        font-size: 0.8rem !important;
        line-height: 1.5 !important;
        color: #8a99ad !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-inst-none-b b {
        color: #b8c5d6 !important;
        font-weight: 600 !important;
    }


    /* Live URL feedback. One row, three states, driven by the bridge - never
       rendered from Python, so it costs no rerun and no element-count change. */
    /* A SILENT status row must cost nothing. Both rows are rendered on every
       run and hidden until the bridge gives them a `data-state` - which is
       correct (a row that comes and goes shifts every element below it), but
       `display: none` on the row only removes its HEIGHT. Its element-
       container is still a flex item in the form's 16px gap, so two silent
       rows were charging 32px for saying nothing - measured, and worth ~a
       fifth of what the whole first-run strip was cut to.

       This is NOT the global ghost-box purge rule, which is deliberately inert
       (every main-app screen is signed off WITH those slots present). It is
       one targeted rule, scoped to this card, keyed on the row's own state, so
       the container comes back the instant there is something to say -
       verified live in both directions. Note the chain: stElementContainer >
       stMarkdown > stMarkdownContainer > the row. Skipping stMarkdown matches
       nothing and fails silently. */
    div[class*="st-key-login_card_wrapper"] [data-testid="stElementContainer"]:has(
        > [data-testid="stMarkdown"] > [data-testid="stMarkdownContainer"]
        > .cd-url-status:not([data-state])),
    div[class*="st-key-login_card_wrapper"] [data-testid="stElementContainer"]:has(
        > [data-testid="stMarkdown"] > [data-testid="stMarkdownContainer"]
        > .cd-tok-status:not([data-state])) {
        display: none !important;
    }

    /* THE TWO STATUS ROWS ARE ONE COMPONENT (institution_picker's
       _status_row_html), so they are one block of rules. They differ in
       exactly one thing - the margin that groups each with the field it
       describes - and writing them out twice is how "the token row warns in a
       slightly different amber" happens six months from now. */
    div[class*="st-key-login_card_wrapper"] .cd-url-status,
    div[class*="st-key-login_card_wrapper"] .cd-tok-status {
        display: none !important;
        align-items: flex-start !important;
        gap: 7px !important;
        font-size: 0.79rem !important;
        line-height: 1.45 !important;
    }
    /* Grouped with the field ABOVE, which is what each describes. Their own
       markdown blocks sit in Streamlit's 1rem flow, which put 24px above and 0
       below - i.e. visually attached to the NEXT field's label, the opposite
       of what they mean.

       ONE margin declaration each. A `margin-top` above a `margin` shorthand
       is silently overwritten by it - which is exactly what made the first
       attempt at this look like the CSS was not applying at all. */
    div[class*="st-key-login_card_wrapper"] .cd-url-status {
        margin: -0.65rem 0 0.75rem 0 !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-tok-status {
        margin: -0.5rem 0 0.5rem 0 !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-url-status[data-state],
    div[class*="st-key-login_card_wrapper"] .cd-tok-status[data-state] {
        display: flex !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-url-status svg,
    div[class*="st-key-login_card_wrapper"] .cd-tok-status svg {
        flex: 0 0 auto !important;
        margin-top: 2px !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-tok-status[data-state="warn"] { color: #fbbf24 !important; }
    div[class*="st-key-login_card_wrapper"] .cd-tok-status[data-state="ok"] { color: #4ade80 !important; }
    div[class*="st-key-login_card_wrapper"] .cd-tok-status b { font-weight: 700 !important; }
    /* ── "Get my Canvas token" ─────────────────────────────────────────────
       A copy of the guide's token-settings link, sitting beside the access
       token field the way the picker sits beside the URL field. It is an
       anchor and not an st.button because it lives inside st.form, where a
       button cannot rerun; its href is derived from the URL field by the
       picker's bridge (ui/institution_picker.py:token_link_html).

       DISABLED here means "no href", so the anchor keeps receiving hover and
       its title can say why - see the app's one disabled recipe below, and
       note the deliberate absence of pointer-events:none, which would take
       the explanation away along with the click. */
    div[class*="st-key-login_card_wrapper"] .cd-tokenlink {
        width: 100% !important;
    }
    /* Streamlit's -16px stMarkdownContainer margin would pull the button up
       out of line with the input beside it - the same correction the picker
       trigger needs one row above. */
    div[class*="st-key-login_card_wrapper"]
        [data-testid="stMarkdownContainer"]:has(> .cd-tokenlink) {
        margin-bottom: 0 !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-tokenlink-btn {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 8px !important;
        width: 100% !important;
        height: 40px !important;
        padding: 0 10px !important;
        border-radius: 6px !important;
        background-color: #1f77b4 !important;
        color: #ffffff !important;
        font-size: 0.86rem !important;
        font-weight: 600 !important;
        font-family: inherit !important;
        text-decoration: none !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3) !important;
        transition: background-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-tokenlink-btn:hover {
        background-color: #2b8cbe !important;
        box-shadow: 0 4px 15px rgba(31, 119, 180, 0.2),
                    inset 0 1px 1px rgba(255, 255, 255, 0.4) !important;
        color: #ffffff !important;
    }
    /* The app's ONE disabled paint. Nothing on top of it: no opacity (it
       multiplies), no second filter (it replaces), no flat grey repaint. */
    div[class*="st-key-login_card_wrapper"] .cd-tokenlink-btn[aria-disabled="true"] {
        filter: brightness(0.5) saturate(0.5) !important;
        cursor: not-allowed !important;
        box-shadow: none !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-tokenlink-ico {
        flex: 0 0 auto !important;
    }
    div[class*="st-key-login_card_wrapper"] .cd-tokenlink-tx {
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }

    /* The token walkthrough, under the field it describes. Pulled up tight
       against the token row the way the URL status row is pulled up under the
       URL field - Streamlit's 1rem block flow would otherwise attach it to the
       Log In button below, which is the opposite of what it means. */
    div[class*="st-key-login_card_wrapper"] .login-tokensteps {
        margin: -0.55rem 0 0.6rem 0 !important;
        font-size: 0.79rem !important;
        line-height: 1.5 !important;
        color: #8a99ad !important;
    }
    div[class*="st-key-login_card_wrapper"] .login-tokensteps b {
        color: #b8c5d6 !important;
        font-weight: 600 !important;
    }
    /* The "copy it now" half is EMPHASIS, not a warning. It was amber, which
       in this app means something is wrong - and nothing is. It gets bold and
       a clipboard glyph instead, and it stays in the same grey as the path it
       continues, so the two read as one sentence.

       `inline` (not a flex row): it must flow on the same line as the path
       when there is room and wrap as ordinary text when there is not - a
       block would reserve a second row at every width.

       `.lts-keep` holds the glyph and the words it marks together, so a wrap
       can never leave a lone clipboard icon dangling at the end of a line
       above the phrase it belongs to. It is deliberately the SHORT half
       (~145px): making the whole sentence unbreakable would overflow the card
       long before that. */
    div[class*="st-key-login_card_wrapper"] .lts-note {
        display: inline !important;
    }
    div[class*="st-key-login_card_wrapper"] .lts-keep {
        white-space: nowrap !important;
    }
    div[class*="st-key-login_card_wrapper"] .lts-note svg {
        vertical-align: -2px !important;
        margin-right: 4px !important;
        opacity: 0.85 !important;
    }

    div[class*="st-key-login_card_wrapper"] .cd-url-status[data-state="ok"] { color: #4ade80 !important; }
    div[class*="st-key-login_card_wrapper"] .cd-url-status[data-state="info"] { color: #8a99ad !important; }
    div[class*="st-key-login_card_wrapper"] .cd-url-status[data-state="warn"] { color: #fbbf24 !important; }
    div[class*="st-key-login_card_wrapper"] .cd-url-status b { font-weight: 700 !important; }

    /* The macOS Keychain-unlock notice. Lives in this UNCONDITIONAL stylesheet
       on purpose: the notice itself renders only in one branch, and a style
       block emitted conditionally shifts every later style host by one (they
       reconcile by index), which is a documented way to strip a neighbouring
       component of its CSS for a frame. */
    div[class*="st-key-kc_unlock_slot"] { gap: 0 !important; }
    .kc-notice {
        background: rgba(56, 130, 246, 0.10);
        border: 1px solid rgba(56, 130, 246, 0.35);
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 16px;
    }
    .kc-notice-quiet {
        background: rgba(148, 163, 184, 0.08);
        border-color: rgba(148, 163, 184, 0.28);
    }
    .kc-head {
        display: flex; align-items: center; gap: 9px;
        color: #cfe0ff; font-weight: 700; font-size: 0.95rem;
    }
    .kc-notice-quiet .kc-head { color: #cbd5e1; font-weight: 600; }
    .kc-head svg { flex-shrink: 0; }
    .kc-body {
        color: #dbe6f5; font-size: 0.88rem; line-height: 1.55; margin-top: 8px;
    }
    .kc-steps {
        margin: 8px 0 0 0; padding-left: 18px;
        color: #dbe6f5; font-size: 0.86rem; line-height: 1.55;
    }
    .kc-steps li { margin: 4px 0; }
    .kc-steps b, .kc-body b { color: #ffffff; font-weight: 700; }
    .kc-foot {
        display: flex; align-items: center; gap: 8px;
        margin-top: 10px; color: #9fb3d0; font-size: 0.82rem;
    }
    .kc-spin {
        width: 13px; height: 13px; flex-shrink: 0;
        border: 2px solid rgba(159, 179, 208, 0.30);
        border-top-color: #9fb3d0; border-radius: 50%;
        display: inline-block; animation: kc-spin 0.9s linear infinite;
    }
    @keyframes kc-spin { to { transform: rotate(360deg); } }
    </style>""")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        # Portal container
        st.markdown(f"""
        <div class="login-portal-container">
            <div class="login-brand-header">
                <img class="login-brand-logo" src="data:image/png;base64,{icon_b64}" style="width: 56px; height: 56px;" />
                <div class="login-brand-title">Canvas Downloader</div>
                <div class="login-brand-subtitle">Your Canvas courses.<br/>Downloaded. Up to date. Optimized for AI.</div>
                <div class="login-brand-header-separator"></div>
                <div class="login-github-header-tag">
                    <a href="https://github.com/BrkBuilds/Canvas-Downloader" target="_blank" class="github-link">
                        <svg class="github-icon" viewBox="0 0 16 16" width="14" height="14"><path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
                        View Source Code on GitHub
                    </a>
                    <a href="https://canvasdownloader.app/" target="_blank" class="github-link">
                        <svg class="github-icon" viewBox="0 0 16 16" width="14" height="14"><path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
                        Go to website
                    </a>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # First-run onboarding signal: a config file only exists after a
        # successful login on this machine, so its absence means this user has
        # never completed login here. Used to (a) show a compact "getting
        # started" strip in the card and (b) auto-open the URL/token help guides,
        # so a first-time user is guided instead of facing a bare credential
        # form. A returning-but-logged-out user has a config file and keeps the
        # quieter layout. The value is constant for the whole logged-out
        # lifetime (config is only written on the login that leaves this page),
        # so nothing below changes its element COUNT between reruns - the strip
        # is folded into the title markdown and the expanders always render.
        _first_run = not os.path.exists(CONFIG_FILE)

        # Reauth mode: force_reauth cleared an expired/revoked token mid-use and
        # routed here, and we still hold the previously-verified Canvas URL. Show
        # a cut-to-the-bone reconnect screen (token field + "how to get one"
        # guide only) instead of the full login form - the only thing that
        # changed is the token. An escape link drops to the full sign-in screen.
        _reauth_reason = st.session_state.get('reauth_reason')
        _saved_url = (st.session_state.get('api_url') or '').strip()
        _reauth_mode = bool(_reauth_reason) and bool(_saved_url)

        with st.container(key="login_card_wrapper"):
            # macOS only: says why the Keychain dialog is on screen and which
            # button to press. Above everything else in the card, because it is
            # the answer to "why am I looking at a login screen at all".
            render_keychain_unlock_notice()

            if _reauth_mode:
                # Prominent, self-contained reconnect header (replaces the title
                # + form heading). Both interpolations are HTML-escaped via _he.
                st.markdown(
                    "<div class='lra-title'>Reconnect to Canvas</div>"
                    "<div class='lra-reason'>"
                    "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='#f97316' "
                    "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
                    "<path d='M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'/>"
                    "<line x1='12' y1='9' x2='12' y2='13'/><line x1='12' y1='17' x2='12.01' y2='17'/></svg>"
                    f"<span>{_he(str(_reauth_reason))}</span></div>"  # audit-ignore: escaped via _he
                    "<div class='lra-url'>Your Canvas address is saved:"
                    f"<span class='lra-url-chip'>{_he(_saved_url)}</span></div>"  # audit-ignore: escaped via _he
                    "<div class='lra-hint'>Generate a fresh access token (guide below) and paste it here "
                    "- that's the only thing that changed.</div>",
                    unsafe_allow_html=True,
                )
            elif _reauth_reason:
                # Reason set but no saved URL to run reauth mode - keep the
                # compact banner above the full login form.
                st.markdown(
                    "<div style='display:flex; align-items:flex-start; gap:10px; "
                    "background:rgba(249,115,22,0.10); border:1px solid rgba(249,115,22,0.35); "
                    "border-radius:8px; padding:12px 14px; margin-bottom:16px;'>"
                    "<svg viewBox='0 0 24 24' width='18' height='18' style='flex-shrink:0; margin-top:1px;' "
                    "fill='none' stroke='#f97316' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
                    "<path d='M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'/>"
                    "<line x1='12' y1='9' x2='12' y2='13'/><line x1='12' y1='17' x2='12.01' y2='17'/></svg>"
                    f"<span style='color:#fcd9b6; font-size:0.9rem; line-height:1.5;'>{_he(str(_reauth_reason))}</span>"  # audit-ignore: already html-escaped via _he
                    "</div>",
                    unsafe_allow_html=True,
                )

            # Title + (first-run only) a compact "getting started" strip, in ONE
            # markdown call so the element count is identical whether or not the
            # strip shows, and so there is no Streamlit block gap between them
            # (the gap is controlled purely by CSS - same reason the dialog
            # title/subtitle are combined). Content is Markdown-safe raw HTML.
            # In reauth mode both are empty (the reconnect header above stands in),
            # but the st.markdown still renders so the element count never shifts.
            # TWO LINES, and the length is the point. This strip used to carry
            # three numbered steps and measured 262px - the largest element on
            # the page - which at the app's MINIMUM window (1024x700, i.e. 636px
            # of usable viewport) pushed the token field to y=715 and the Log In
            # button to y=799: a first-time user saw a wall of instructions and
            # neither input nor the button. It also said everything the two
            # guides below said, so the page explained itself three times.
            #
            # What survives is the only thing that is not written anywhere else
            # above the fold: an orienting sentence, and the answer to "is this
            # safe?". The steps live where they are needed - the school picker
            # and "Get a token" are beside the fields they fill, and the token
            # walkthrough sits under the token field.
            _getstarted_html = (
                "<div class='login-getstarted'>"
                "<div class='lgs-head'>New here? Find your school, get a token, "
                "log in - about 2 minutes.</div>"
                "<div class='lgs-safe'>"
                "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' "
                "stroke='currentColor' stroke-width='2' stroke-linecap='round' "
                "stroke-linejoin='round'><rect x='3' y='11' width='18' height='11' "
                "rx='2' ry='2'/><path d='M7 11V7a5 5 0 0 1 10 0v4'/></svg>"
                "<span>Your token is stored only on this device, in your operating "
                "system - nothing is ever uploaded.</span></div></div>"
            ) if (_first_run and not _reauth_mode) else ""
            _title_html = "" if _reauth_mode else '<div class="login-form-title">Log in to Canvas Downloader</div>'
            st.markdown(
                _title_html + _getstarted_html,
                unsafe_allow_html=True,
            )

            with st.form("auth_form", clear_on_submit=False, border=False):
                # In reauth mode the URL is already known and shown as a saved
                # chip above - only the token needs re-entering. The full form
                # renders the URL field.
                if not _reauth_mode:
                    # The institution picker sits to the RIGHT of the field and
                    # writes into it; the field stays editable, so a school that
                    # is not in the list is never blocked - it is typed or
                    # pasted exactly as before. `vertical_alignment="bottom"`
                    # is what lines the trigger up with the input rather than
                    # with the input's LABEL.
                    _c_url, _c_pick = st.columns([1.6, 1], vertical_alignment="bottom")
                    with _c_url:
                        st.text_input(
                            'Your Canvas URL',
                            key="url_input",
                            placeholder="https://schoolname.instructure.com"
                        )
                    with _c_pick:
                        st.markdown(institution_picker.picker_html(),
                                    unsafe_allow_html=True)
                    # The live status line, pulled up tight under the URL
                    # field it describes. There is no standing "not listed"
                    # caveat here any more: it repeated what the picker's own
                    # empty state says, and it belongs THERE - beside the
                    # search that just came up empty - not permanently under a
                    # field it has nothing to do with.
                    st.markdown(institution_picker.url_status_html(),
                                unsafe_allow_html=True)

                # Same two-column shape as the URL row above, so the token
                # shortcut lines up under the institution picker: one column
                # of controls that fill the field beside them. The link's
                # target is derived from the URL field by the picker's bridge
                # (a form widget's value never reaches Python before submit),
                # and `fallback` covers reauth mode, which renders no URL
                # field because the address is already known and verified.
                _c_tok, _c_link = st.columns([1.6, 1], vertical_alignment="bottom")
                with _c_tok:
                    st.text_input(
                        'Your Canvas Access Token',
                        type="password",
                        key="token_input",
                        help=(
                            "**Why is this needed?**  \n"
                            "This token acts as a private key that allows the app to fetch your course files directly from your school's Canvas instance, which it connects to.\n\n"
                            "**Is it safe?**  \n"
                            "Yes! Your token is stored securely on your device, in your operating system."
                        )
                    )
                with _c_link:
                    # What to point at when the FIELD says nothing. Two cases,
                    # and both hold a URL this machine has already logged in
                    # with: reauth mode renders no field, and a returning login
                    # renders an empty one (the address lives in config, not in
                    # the widget). Only ever a verified URL - the same rule the
                    # guide's copy of this button uses, so the two cannot sit
                    # on one page disagreeing about whether we know the school.
                    _link_fallback = _saved_url if (
                        _reauth_mode or st.session_state.get('url_verified')) else ''
                    st.markdown(institution_picker.token_link_html(_link_fallback),
                                unsafe_allow_html=True)

                # The walkthrough, AT THE POINT OF NEED. It used to live in an
                # expander at the bottom of the page - which is the one place
                # it cannot be read from, because the work happens in ANOTHER
                # APP: the user clicks "Get a token", lands in Canvas, and the
                # instructions are on a screen they can no longer see. Two
                # lines they can carry beat four they have to scroll back for.
                #
                # Kept to the two facts that are not self-evident once you are
                # on Canvas's settings page: WHERE the control is, and that the
                # token is shown exactly once.
                #
                # Emitted unconditionally with the CONTENT gated, never the
                # element: Streamlit reconciles by position, and a row that
                # comes and goes hands the next element its DOM node.
                # THE PATH STARTS AT ACCOUNT, not at Approved Integrations.
                # "Get a token" lands the user directly on /profile/settings,
                # so the first two hops are ones the button walks for them -
                # which is exactly why they have to be written down. The button
                # is the only thing that can fail here (a wrong address, a
                # blocked pop-up, an unusual Canvas), and when it does, the
                # instructions that assume it worked are worth nothing.
                #
                # ONE flowing line, not two rows. The "copy it now" half used
                # to be a second row in amber - which is this app's colour for
                # something being WRONG, and nothing is wrong; it was reaching
                # for emphasis and borrowing a meaning. Bold carries it, the
                # clipboard glyph marks it, and the sentence simply continues
                # on the same line, wrapping only when the card is too narrow.
                st.markdown(
                    "<div class='login-tokensteps'>"
                    "<span class='lts-path'>In Canvas: <b>Account</b> "
                    "&rarr; <b>Settings</b> &rarr; <b>Approved Integrations</b> "
                    "&rarr; <b>+ New Access Token</b>.</span> "
                    "<span class='lts-note'>"
                    "Once you have your token, copy it straight away and paste it here."
                    "</span></div>"
                    if help_text_enabled() else "",
                    unsafe_allow_html=True)

                # Live feedback on what was pasted, mirroring the URL field's
                # status row. It speaks ONLY when it knows something is wrong -
                # see the bridge for the three cases and why silence is the
                # default everywhere else.
                st.markdown(institution_picker.token_status_html(),
                            unsafe_allow_html=True)

                submitted = st.form_submit_button(
                    'Reconnect' if _reauth_mode else 'Log In',
                    type="primary", use_container_width=True, key="login_submit_btn")

            if submitted:
                # Cheap, specific input checks BEFORE the network round-trip.
                # Without them the two most common first-run mistakes produce
                # misleading errors: an empty token + a URL comes back as "your
                # token was revoked" (they never entered one), and a token pasted
                # into the URL field is expanded by normalize_canvas_url into a
                # garbage `https://<token>.instructure.com` that fails as a
                # generic "Connection Failed". Naming the real mistake is the
                # lowest-friction fix there is - no round-trip, no guesswork.
                # In reauth mode there is no URL field - use the saved, already-
                # verified Canvas URL. Otherwise read what the user typed.
                raw_url = _saved_url if _reauth_mode else (st.session_state.get('url_input') or '').strip()
                input_token = (st.session_state.token_input or '').strip()
                input_url = normalize_canvas_url(raw_url)

                from ui.amber_notice import render_amber_notice
                _input_error = None
                if not raw_url and not input_token:
                    _input_error = ("Enter your details",
                                    "Add your Canvas URL and access token above, then press Log In. "
                                    "The guides below walk you through finding each one.")
                elif not raw_url:
                    _input_error = ("Canvas URL needed",
                                    "Add your Canvas web address (e.g. https://schoolname.instructure.com). "
                                    "See 'How to find your Canvas URL' below.")
                elif not input_token:
                    _input_error = ("Access token needed",
                                    "Paste your Canvas access token above. See 'How to get a Canvas "
                                    "Access Token' below - it takes about a minute to generate one.")
                elif _reauth_mode and _looks_like_url(input_token):
                    # Reauth has no URL field, so "swapped" would be nonsense -
                    # the user simply pasted a URL where the token goes.
                    _input_error = ("That looks like a URL, not a token",
                                    "Paste the access token you generate in Canvas (a long code) - "
                                    "not a web address. Your Canvas URL is already saved.")
                elif _looks_like_token(raw_url) or _looks_like_url(input_token):
                    # The two fields look swapped (a token in the URL box, or a
                    # URL in the token box). Say so instead of failing obscurely.
                    _input_error = ("Check your URL and token",
                                    "Your Canvas URL and access token look swapped. The URL is your "
                                    "school's web address (e.g. https://schoolname.instructure.com); "
                                    "the token is the long code you generate in Canvas.")

                if _input_error:
                    render_amber_notice(_input_error[0], detail=_input_error[1])
                    is_valid, message, manager = False, None, None
                else:
                    st.session_state['api_url'] = input_url
                    st.session_state['api_token'] = input_token
                    # Optimistically un-verify: this URL is only "trusted" once the
                    # token validates against it below. A failed attempt must not
                    # leave a stale verified flag pointing at the wrong URL.
                    st.session_state['url_verified'] = False

                    manager = CanvasManager(input_token, input_url)
                    is_valid, message = manager.validate_token()

                if is_valid:
                    st.session_state['api_token'] = input_token
                    st.session_state['api_url'] = manager.api_url
                    st.session_state['url_verified'] = True
                    st.session_state['is_authenticated'] = True
                    st.session_state['user_name'] = message.split(": ", 1)[1] if ": " in message else message
                    # Successful reconnect clears any "your connection expired" banner.
                    st.session_state.pop('reauth_reason', None)

                    # Setup base config data. Through the shared helper so an
                    # unreadable-but-intact settings file SKIPS the write below
                    # instead of replacing it with just the three keys set here
                    # - which is what the old `except Exception: pass` did, on
                    # the one run per install that migrates a token to the
                    # keyring. See read_config_for_update.
                    config_data, _cfg_may_write = read_config_for_update()

                    config_data['api_url'] = st.session_state['api_url']
                    if 'concurrent_downloads' in st.session_state:
                        config_data['concurrent_downloads'] = st.session_state['concurrent_downloads']
                    if 'debug_mode' in st.session_state:
                        config_data['debug_mode'] = st.session_state['debug_mode']

                    # Save token to OS keyring (macOS Keychain / Windows Credential Manager) with fallback
                    try:
                        keyring_user = st.session_state['api_url'] or 'default'
                        token_to_save = st.session_state['api_token']
                        # store_token skips an identical write (so a re-login
                        # cannot destroy a working credential - see its
                        # docstring), tries the fallback, and then VERIFIES.
                        kr_success = store_token(keyring_user, token_to_save)
                        if kr_success:
                            # Stored in the keyring - remove any leftover
                            # fallback file entry. Only safe because the return
                            # value means "retrievable", not "the call returned".
                            if _safe_keyring_get(KEYRING_SERVICE, keyring_user) == token_to_save:
                                _delete_fallback_token(keyring_user)
                        else:
                            # Nothing holds the token. The old advice was a
                            # logger.warning claiming a DPAPI save, which off
                            # Windows is nothing at all - so the user was logged
                            # out on the next launch with no explanation.
                            from ui.amber_notice import render_amber_notice
                            render_amber_notice(
                                "Your login could not be saved on this device",
                                detail=("You are signed in now, but this Mac's keychain "
                                        "refused to store your access token, so the app "
                                        "will ask for it again next time you open it. "
                                        "Keep your token somewhere you can find it. If your "
                                        "keychain is locked, unlocking it and logging in "
                                        "again is usually enough."
                                        if sys.platform != 'win32' else
                                        "You are signed in now, but Windows would not store "
                                        "your access token, so the app may ask for it again "
                                        "next time you open it."),
                            )

                        # Ensure no legacy insecure fields remain in the config JSON
                        config_data.pop('mac_api_token', None)
                        config_data.pop('api_token', None)
                    except Exception as e:
                        from ui.amber_notice import render_amber_notice
                        render_amber_notice(
                            "Token Storage Warning",
                            detail=f"Could not save your token securely to your device ({e}). You can continue using the app, but you may need to log in again next time."
                        )

                    # A login must never be blocked by a settings write, so an
                    # unwritable config is skipped silently here rather than
                    # surfaced: the token is already in the keyring and the
                    # session is live. Writing anyway is the one thing that
                    # would do damage.
                    if _cfg_may_write:
                        try:
                            _tmp_config = CONFIG_FILE + '.tmp'
                            with open(_tmp_config, 'w', encoding='utf-8') as f:
                                json.dump(config_data, f)
                                f.flush()
                                os.fsync(f.fileno())
                            os.replace(_tmp_config, CONFIG_FILE)
                        except Exception as e:
                            # Clean up orphaned temp file on failure
                            try:
                                if os.path.exists(_tmp_config):
                                    os.unlink(_tmp_config)
                            except OSError:
                                pass
                            from ui.amber_notice import render_amber_notice
                            render_amber_notice(
                                "Settings Storage Warning",
                                detail=f"Could not save your preferences ({e}). Your session is active, but your settings may not persist."
                            )

                    st.rerun()
                # `message is None` only when an input pre-check above already
                # rendered its own specific notice (empty field / swapped
                # fields) - don't stack a second, generic error on top of it.
                elif message is not None:
                    err_text_lower = str(message).lower()
                    from ui.amber_notice import render_amber_notice

                    if any(kw in err_text_lower for kw in ["missing schema", "no connection adapters", "invalid url"]):
                        render_amber_notice(
                            "That Canvas address didn't work",
                            detail="We couldn't read that as a Canvas web address. Copy it straight from your browser's address bar while you're logged in to Canvas (e.g. https://schoolname.instructure.com)."
                        )
                    # Expiry is checked FIRST because it is the more specific
                    # diagnosis, and it must stay specific: `validate_token`
                    # deliberately does NOT put the word "expired" in its generic
                    # Unauthorized text, or every revoked/deleted token would be
                    # mis-reported here as "Token Expired".
                    elif "expired" in err_text_lower:
                        render_amber_notice(
                            "Token Expired",
                            detail="Your Canvas Access Token has expired. Access tokens are set to expire periodically for security. Use 'Get a token' next to the field above to generate a new one, then paste it here."
                        )
                    # "invalid access token" is Canvas's OWN wording and contains
                    # none of "invalid token"/"unauthorized"/"401" - without it here
                    # a revoked token fell through to the generic branch below and
                    # printed the raw error payload as "Technical Details".
                    elif any(kw in err_text_lower for kw in [
                        "revoked", "invalid token", "invalid access token",
                        "access token is invalid", "unauthorized", "401",
                    ]):
                        render_amber_notice(
                            "Authentication Failed",
                            detail="Your Canvas Access Token is invalid or has been revoked. Use 'Get a token' next to the field above to generate a new one."
                        )
                    elif "403" in err_text_lower or "forbidden" in err_text_lower:
                        render_amber_notice(
                            "Access Denied",
                            detail="Your token does not have the required permissions. Please generate a new token without restrictions."
                        )
                    elif any(kw in err_text_lower for kw in ["expecting value", "jsondecodeerror", "json decoder"]):
                        render_amber_notice(
                            "Invalid Canvas URL",
                            detail="Your Canvas URL points to a login portal instead of the actual Canvas server. Please ensure you are using the true base Canvas URL (typically ending in .instructure.com). Follow the 'How to find your Canvas URL' guide below."
                        )
                    elif any(kw in err_text_lower for kw in ["500", "502", "503", "504", "server error"]):
                        render_amber_notice(
                            "Canvas Server Down",
                            detail="Your university's Canvas server is currently returning an error or undergoing maintenance. Please try again later."
                        )
                    elif any(kw in err_text_lower for kw in ["ssl", "certificate verify failed", "handshake"]):
                        render_amber_notice(
                            "Secure Connection Failed",
                            detail="We couldn't establish a secure connection. If you're on a campus network, you may need to log in to the Wi-Fi portal first, or disable any active VPNs."
                        )
                    elif any(kw in err_text_lower for kw in ["url", "not found", "404", "connection", "timeout", "max retries", "name or service not known"]):
                        render_amber_notice(
                            "Connection Failed",
                            detail="We couldn't connect to your Canvas URL. Please verify that the URL is typed correctly (e.g., https://canvas.schoolname.edu or https://schoolname.instructure.com) and that you are connected to the internet."
                        )
                    else:
                        render_amber_notice(
                            "Login Failed",
                            detail=f"An unexpected error occurred during authentication. Please double-check your URL and token. Technical Details: {message}"
                        )

            pass

        # Standardized expandable help vertically below the card
        st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
        with st.container(key="login_help_expanders"):
            # URL guide is hidden in reauth mode - the address is already saved
            # and shown as a chip, so "how to find your URL" is just noise there.
            if not _reauth_mode:
                # COLLAPSED even on a first run. It used to open automatically,
                # which put "open Canvas, copy the address bar" above the token
                # guide - the harder of the two - for every new user. The
                # institution picker answers this question for 4,750 schools in
                # one click, so the guide is now the fallback it describes
                # itself as, one click away for the schools it is not.
                with st.expander('How to find your Canvas URL?', expanded=False):
                    st.markdown(
                        # Kept deliberately lean: normalize_canvas_url + CanvasManager's
                        # redirect resolution already add https://, strip paths and follow
                        # a vanity domain to its .instructure.com target, so the old
                        # "include https / use .instructure.com" caveats were explaining
                        # friction the code already removes. The one real edge case (a
                        # vanity domain that lands on an SSO portal) is covered just-in-time
                        # by its own submit error, so here it is only a quiet footnote.
                        "1. Open Canvas in your web browser.\n"
                        "2. Copy the address from your browser's address bar - for example "
                        "`schoolname.instructure.com` or `canvas.schoolname.edu`.\n"
                        "3. Paste it here - the exact format doesn't matter.\n\n"
                        "If a login attempt fails, use the address ending in `.instructure.com` "
                        "(you'll see it in the address bar once you're inside Canvas) - that's the most reliable one.\n"
                    )

            # THE TOKEN GUIDE IS GONE FROM HERE ON PURPOSE - it now sits under
            # the token field, where the user is standing (see the
            # `.login-tokensteps` block above). What used to be here was a
            # second copy of the "Get a token" button plus the same four steps,
            # i.e. the page explaining tokens twice, ~200px below the fold, in
            # the one place a user who has just clicked through to Canvas
            # cannot read them.
            #
            # Deleted with it: the click-time reachability check that button
            # ran (`_canvas_url_reachable`), and its `_token_link_ready` /
            # `_token_link_error` state. It cannot survive the move - the field
            # -side button lives inside st.form, where a click cannot rerun -
            # and what it bought was one dead browser tab avoided for a user
            # who typed a bad address. The cost of losing it is bounded: the
            # login attempt itself still names a bad URL, and the status row
            # under the field flags an address that looks wrong before then.

        st.markdown(
            '<a href="https://youtu.be/VadvcIvrrhU" target="_blank" class="youtube-link">'
            '<svg class="youtube-icon" viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>'
            'Watch tutorial: How to get your Canvas Access Token'
            '</a>',
            unsafe_allow_html=True
        )

        # Reauth-mode escape hatch: drop the cut-to-the-bone reconnect screen for
        # the full sign-in form (to change the Canvas URL or use a different
        # account). Screen-replacing navigation, so `if st.button(): ...; rerun`
        # is correct. The saved URL is pre-filled so it need not be retyped.
        if _reauth_mode:
            _esc1, _esc2, _esc3 = st.columns([1, 3, 1])
            with _esc2:
                if st.button(
                    "Use the full sign-in screen (different account or URL)",
                    key="reauth_full_login",
                    use_container_width=True,
                ):
                    st.session_state['url_input'] = _saved_url
                    st.session_state.pop('reauth_reason', None)
                    st.rerun()

        # No dynamic spacer used to guarantee footer visibility at all times

        # Open a unified footer container to completely eliminate nested Streamlit block gaps!
        with st.container(key="login_footer_container"):
            # Elegant subtle separator between help section and security footer
            st.markdown("<div class='login-privacy-separator'></div>", unsafe_allow_html=True)

            with st.container(key="login_privacy_expander"):
                with st.expander('100% Local & Secure'):
                    st.markdown(
                        "<div class='privacy-list-item'>"
                        "<svg class='privacy-list-icon' viewBox='-2 -2 28 28' width='14' height='14'><path fill='currentColor' d='M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z'/></svg>"
                        "<div class='privacy-list-content'>"
                        "<div class='privacy-list-title'>Native Encryption</div>"
                        "<div class='privacy-list-desc'>Your Canvas Access Token is securely stored in your operating system's native keychain (Windows Credential Manager / macOS Keychain), never in plain text.</div>"
                        "</div>"
                        "</div>"
                        "<div class='privacy-list-item'>"
                        "<svg class='privacy-list-icon' viewBox='-2 -2 28 28' width='14' height='14'><path fill='currentColor' d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z'/></svg>"
                        "<div class='privacy-list-content'>"
                        "<div class='privacy-list-title'>Direct Connection</div>"
                        "<div class='privacy-list-desc'>Your courses and files come straight from the Canvas URL you provide - no proxies, no intermediaries. "
                        "The app makes three other connections, and none of them carry your data: your university's <b>Panopto</b> server, only if you download lecture recordings; "
                        "<b>Hugging Face</b> and <b>PyPI</b>, only if you set up on-device transcription or GPU acceleration (a one-time download, like any other file); "
                        "and a version check against <b>GitHub</b> when the app starts, which sends nothing but the request itself.</div>"
                        "</div>"
                        "</div>"
                        "<div class='privacy-list-item'>"
                        "<svg class='privacy-list-icon' viewBox='-2 -2 28 28' width='14' height='14'><path fill='currentColor' d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8 0-1.85.63-3.55 1.69-4.9L16.9 18.31C15.55 19.37 13.85 20 12 20zm6.31-4.69L7.69 4.69C9.04 3.63 10.74 3 12 3c4.41 0 8 3.59 8 8 0 1.85-.63 3.55-1.69 4.9z'/></svg>"
                        "<div class='privacy-list-content'>"
                        "<div class='privacy-list-title'>Zero Telemetry</div>"
                        "<div class='privacy-list-desc'>No tracking, no analytics, no accounts, and no third-party data collection. There is no backend to send anything to - the developer never receives anything from your machine.</div>"
                        "</div>"
                        "</div>"
                        "<div class='privacy-list-item'>"
                        "<svg class='privacy-list-icon' viewBox='-2 -2 28 28' width='14' height='14'><path fill='currentColor' d='M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-6 10H6v-2h8v2zm4-4H6v-2h12v2z'/></svg>"
                        "<div class='privacy-list-content'>"
                        "<div class='privacy-list-title'>Isolated File Access</div>"
                        "<div class='privacy-list-desc'>The application acts as a one-way street. It only downloads course materials into the specific destination folder you choose. It does not scan, read, or upload any personal files from your computer. Your credentials and data remain entirely under your control and are never shared with external servers.</div>"
                        "</div>"
                        "</div>"
                        "<div class='privacy-list-item'>"
                        "<svg class='privacy-list-icon' viewBox='-2 -2 28 28' width='14' height='14'><path fill='currentColor' d='M9.4 16.6L4.8 12l4.6-4.6L8 6l-6 6 6 6 1.4-1.4zm5.2 0l4.6-4.6-4.6-4.6L16 6l6 6-6 6-1.4-1.4z'/></svg>"
                        "<div class='privacy-list-content'>"
                        "<div class='privacy-list-title'>Open Source & Verifiable</div>"
                        "<div class='privacy-list-desc'>Trust shouldn't be blind. The source code is entirely public, allowing anyone to independently verify these security standards. "
                        "<a href='https://github.com/BrkBuilds/Canvas-Downloader' target='_blank'>View Source Code on GitHub</a></div>"
                        "</div>"
                        "</div>",
                        unsafe_allow_html=True
                    )

            # Elegant subtle separator between security footer and student footer
            st.markdown("<div class='login-privacy-separator login-privacy-separator-bottom'></div>", unsafe_allow_html=True)

            # Delicate humanized student footer with SVG heart hover micro-animation
            st.markdown(
                "<div class='login-student-signature'>"
                "For students, by a student"
                "<svg class='signature-heart-icon' viewBox='-2 -2 28 28' width='14' height='14'>"
                "<path fill='currentColor' d='M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z'/>"
                "</svg>"
                "</div>",
                unsafe_allow_html=True
            )

    # The picker's behaviour, mounted LAST and UNCONDITIONALLY.
    #   * last, because a components.html iframe is a real element and emitting
    #     it mid-page would sit between the card and the help expanders;
    #   * unconditionally, so reauth mode (which renders no URL field and no
    #     picker) keeps the same element count as the full form - a component
    #     that comes and goes shifts every element after it by one slot, and
    #     Streamlit hands a block the CHILDREN of whatever held its index.
    # Every handler in the script is guarded on the picker actually being on
    # the page, so in reauth mode it simply finds nothing and does nothing.
    institution_picker.inject_bridge()

    # LAST THING ON THE PAGE, and the position is the whole point: this raises
    # the macOS Keychain prompt, and the script run ends on the next line - so
    # the explanation above has already been emitted and the window paints
    # before the system dialog can land on top of it. Starting it any earlier
    # risks the prompt appearing over a window that is still empty, which is the
    # exact experience this change exists to remove. Idempotent per account, so
    # the once-a-second poll above cannot spawn a second prompt.
    if st.session_state.get('keychain_unlock_pending'):
        begin_keychain_unlock(KEYRING_SERVICE,
                              st.session_state.get('api_url') or 'default')


# ─── Private helpers ────────────────────────────────────────────────────


def _render_authenticated_nav_top():
    """Render the top part of the authenticated sidebar: navigation buttons."""
    # ── Navigation buttons ─────────────────────────────────────────
    mode = st.session_state.get('current_mode', 'download')
    step = st.session_state.get('step', 1)

    # Lock all mode switching while a download/sync is actively running. The app
    # is single-operation: switching modes mid-run would fire cleanup_*_state()
    # (below), orphaning the background worker and wiping the live progress card.
    # The running operation's own Cancel button stays the one deliberate exit.
    from core.cancellation import is_operation_in_progress
    _locked = is_operation_in_progress()
    # Passed as help= ONLY while locked - a tooltip that stays on an enabled
    # button would claim the button is unavailable when it plainly is not.
    _NAV_LOCKED_HELP = ("Switching pages is locked while a download or sync is "
                        "running. Use the run's own Cancel button to stop it.")

    # Expose the current screen for the JS overlay logic (read via getElementById).
    #
    # `data-screen` is the SCREEN IDENTITY, and it is what tells the navigation
    # overlay that the page it is covering has actually been replaced. It has to
    # be an app-authored value: the overlay used to infer this from a geometry
    # fingerprint, and the fingerprint collided. Measured 2026-07-31 - sync step
    # 1, the Today page and the sync review screen all render at exactly
    # scrollHeight 1049, so "the page changed" never became true and the overlay
    # could only exit through its 8-second safety valve. Every sync<->today
    # navigation, and every Analyze run, was covered for a flat 8 seconds.
    #
    # Every field is load-bearing; each is the ONLY one that moves for at least
    # one navigation:
    #   mode   sidebar nav, login, logout
    #   step   Custom Download (1->2), Back (2->1), Confirm and Download (2->3)
    #   quick  "Customize configuration" - Quick Download and Custom Download are
    #          BOTH mode=download step=2, so without this they are one screen
    #   status the run phases (scanning / running / panopto / done / cancelled),
    #          which is what makes starting a download a screen change at all
    #
    # `data-busy` is the app's own "a long operation is in flight", taken from
    # the same call that locks the nav buttons - so the overlay cannot disagree
    # with the rest of the app about whether a run is under way. It is what lets
    # the overlay uncover a progress dashboard while its script is still
    # running: a download holds the script thread for minutes, so "wait for the
    # script to finish" can never be the rule there.
    _quick = 'q' if st.session_state.get('quick_download_mode') else ''
    _status = st.session_state.get('download_status') or ''
    _screen = _he(f"{mode}|{step}|{_quick}|{_status}", quote=True)
    st.html(f"<span id='cdp_nav_state' data-mode='{mode}' data-step='{step}' "
            f"data-screen='{_screen}' data-busy='{'1' if _locked else '0'}' "
            f"style='display:none;position:absolute;pointer-events:none'></span>")

    # Active-state CSS is dynamic (depends on session state) - inject separately.
    #
    # Unconditional, like the run-lock block below, and for the same reason: the
    # guard was self-gating. Every rule keys off `st-key-nav_btn_{mode}`, so for
    # a mode with no such button the whole block matches nothing and paints
    # nothing - while emitting it only on some runs moved the EVENT container's
    # index boundaries, and the sidebar renders BEFORE the main page, so those
    # boundaries sit ahead of every main-page stylesheet.
    active_key = f"st-key-nav_btn_{mode}"
    st.html(f"""<style>
    section[data-testid="stSidebar"] div.{active_key} button {{ background-color: rgba(255, 255, 255, 0.10) !important; }}
    section[data-testid="stSidebar"] div.{active_key} button p {{ color: #ffffff !important; font-weight: 600 !important; }}
    section[data-testid="stSidebar"] div.{active_key} button p::before,
    section[data-testid="stSidebar"] div.{active_key} button:hover p::before {{ filter: brightness(0) invert(1) !important; }}
    section[data-testid="stSidebar"] div.{active_key} button:hover {{ background-color: rgba(255, 255, 255, 0.10) !important; cursor: default !important; }}
    section[data-testid="stSidebar"] div.{active_key} button:hover p {{ color: #ffffff !important; }}
    </style>""")

    # Disabled-state CSS: dim the inactive nav buttons and kill their hover
    # feedback so it's visually clear they can't be used mid-run. The CURRENT
    # (running) mode's button is excluded from the dimming so it keeps its
    # highlight - "you are here, and it's running".
    #
    # EMITTED UNCONDITIONALLY, and the `if _locked:` that used to wrap it must
    # not come back. Every rule below is scoped to `button:disabled`, and these
    # buttons are disabled exactly when `_locked` - so the guard changed nothing
    # about what the page LOOKS like, and cost an index shift instead. A
    # style-only st.html goes to the EVENT root container, one ordered
    # index-addressed list, and the sidebar renders BEFORE the main page, so
    # this host sits ahead of every main-page stylesheet in it.
    #
    # Measured 2026-08-20 by sampling that list per animation frame across a
    # real Analyze on the sync page: at rest the list was 5 hosts with the
    # page's 277KB main stylesheet at index 2; 242ms after the click index 2
    # had been REWRITTEN with this block and the 277KB sheet was gone from the
    # list entirely, while indices 3 and 4 still held the PREVIOUS screen's
    # stylesheets - the mis-styled window lasted 46ms. Emitting it always makes
    # the list invariant across run start and end, and costs nothing: a
    # style-only st.html takes no flex slot.
    st.html(f"""<style>
    /* No `opacity` here: global.css's single `button[disabled]` recipe
       (brightness/saturate) paints these, and an opacity on top multiplies
       with it. The old `:not(.st-key-nav_btn_MODE)` exclusion is expressed
       the other way round now - see the running-mode rule below, which
       cancels the shared filter so that one button keeps its highlight.
       (It previously only set `opacity: 1`, which did NOT undo the shared
       filter, so the "you are here, and it's running" button was dimmed
       anyway - the exclusion had been silently broken.) */
    section[data-testid="stSidebar"] div[class*="st-key-nav_btn_"]:not([class*="logout"]) button:disabled {{
        cursor: not-allowed !important;
    }}
    section[data-testid="stSidebar"] div[class*="st-key-nav_btn_"]:not([class*="logout"]) button:disabled:hover {{
        background-color: transparent !important;
    }}
    section[data-testid="stSidebar"] div[class*="st-key-nav_btn_"]:not([class*="logout"]) button:disabled:hover p {{
        color: #9ca3af !important;
    }}
    section[data-testid="stSidebar"] div[class*="st-key-nav_btn_"]:not([class*="logout"]) button:disabled:hover p::before {{
        filter: brightness(0) invert(0.65) !important;
    }}
    /* The running mode keeps its highlight (never dimmed) but shows a plain cursor. */
    section[data-testid="stSidebar"] div.st-key-nav_btn_{mode} button:disabled {{
        filter: none !important; opacity: 1 !important; cursor: default !important;
    }}
    section[data-testid="stSidebar"] div.st-key-nav_btn_{mode} button:disabled:hover {{
        background-color: rgba(255, 255, 255, 0.10) !important;
    }}
    section[data-testid="stSidebar"] div.st-key-nav_btn_{mode} button:disabled:hover p {{
        color: #ffffff !important;
    }}
    section[data-testid="stSidebar"] div.st-key-nav_btn_{mode} button:disabled:hover p::before {{
        filter: brightness(0) invert(1) !important;
    }}
    </style>""")

    # Download mode button - always navigates to download step 1.
    if st.button('Download Courses', use_container_width=True, key="nav_btn_download", disabled=_locked,
                 help=_NAV_LOCKED_HELP if _locked else None) and not _locked:
        if mode != 'download' or step != 1:
            from core.state_registry import cleanup_download_state
            cleanup_download_state()
            st.session_state['current_mode'] = 'download'
            st.session_state['sync_mode'] = False
            st.session_state['sync_pairs'] = []
            st.session_state.pop('sync_pairs_loaded', None)
            st.rerun()

    # Sync mode button - always navigates to sync step 1.
    if st.button('Sync Course Folders', use_container_width=True, key="nav_btn_sync", disabled=_locked,
                 help=_NAV_LOCKED_HELP if _locked else None) and not _locked:
        if mode != 'sync' or step != 1:
            from core.state_registry import cleanup_sync_state
            cleanup_sync_state()
            st.session_state['current_mode'] = 'sync'
            st.session_state['step'] = 1
            st.session_state['sync_mode'] = True
            st.session_state['sync_pairs'] = []
            st.session_state.pop('sync_pairs_loaded', None)
            st.rerun()

    # Today dashboard button - the daily home (auto-sync + today's files).
    # `disabled=_locked` blocks the click in the browser; the extra `not _locked`
    # guard is defense-in-depth so a click queued in the instant before the run
    # began can never fire cleanup_*_state() and abandon the in-flight operation.
    if st.button("Today's files", use_container_width=True, key="nav_btn_today", disabled=_locked,
                 help=_NAV_LOCKED_HELP if _locked else None) and not _locked:
        if mode != 'today' or step != 1:
            from core.state_registry import cleanup_sync_state
            cleanup_sync_state()
            st.session_state['current_mode'] = 'today'
            st.session_state['step'] = 1
            st.session_state['sync_mode'] = False
            st.session_state['sync_pairs'] = []
            st.session_state.pop('sync_pairs_loaded', None)
            st.rerun()

    # NOTE: Panopto no longer has a standalone nav entry. It is configured
    # per-download in Section 4 of the download settings, and its transcription
    # engine setup is a dialog opened from there.


def open_pending_global_dialog() -> None:
    """Open the global Settings dialog, AFTER the main page has rendered.

    Why this exists - measured in-browser 2026-07-26:

    Opening a dialog from the sidebar made the whole page behind it flash
    mis-styled for ~110ms: titles collapsed (a 287px column snapped to 39px),
    negative margins reset to 0, icons vanished and came back.

    The cause is NOT that CSS is "re-applied". A plain main-page rerun (toggling
    a card) produces zero bad frames with exactly the same stylesheets. What
    breaks is ORDERING. ``render_sidebar()`` runs before the main page, so a
    dialog opened from it inserts its own elements ahead of every main-page
    ``st.html(<style>)`` block. Streamlit reuses the existing style hosts and
    reconciles them by INDEX, so each host is rewritten with its neighbour's
    stylesheet - for a few frames the page is not unstyled, it is *mis*-styled
    with the CSS of the block next to it. (Verified: a dialog opened from inside
    the main page - Presets - shifts nothing and produces zero bad frames.)

    Deferring the call to the end of the script puts the dialog's elements after
    every main-page block, so no index shifts and nothing is restyled. The main
    page genuinely does not change while a dialog is open - which is the point.
    """
    if not st.session_state.get('_stg_dialog_open'):
        return
    dialog_fn = st.session_state.get('_stg_dialog_fn')
    if dialog_fn is None:
        # Should be unreachable: the sidebar publishes the closure in the same
        # run that can set the flag, and app.py st.stop()s before reaching here
        # when unauthenticated. Guard anyway - a set flag with no callable would
        # otherwise be UNRECOVERABLE: every later click just re-sets an
        # already-true flag, so Settings would look permanently dead. Clearing it
        # costs one click instead.
        st.session_state.pop('_stg_dialog_open', None)
        logger.warning("Settings dialog was requested but no dialog callable was "
                       "published; cleared the flag so the button works again.")
        return
    dialog_fn()


def _render_authenticated_nav_bottom(fetch_courses_fn):
    """Render the bottom part of the authenticated sidebar"""
    import os
    import json
    import platform


    # ── Global Settings dialog ─────────────────────────────────────
    def _stg_ico(path_d, evenodd=False):
        # evenodd makes EVERY inner subpath a hole regardless of its winding
        # direction, which is what lets a glyph be composed out of separate
        # hand-written subpaths (outline + fold + symbol) without having to get
        # each one's direction right by inspection.
        _fr = ' fill-rule="evenodd"' if evenodd else ''
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="{path_d}" fill="#a0aec0"{_fr}/></svg>'
        return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

    _stg_i_speed  = _stg_ico("M7 2v11h3v9l7-12h-4l4-8z")
    _stg_i_filter = _stg_ico("M4.25 5.61C6.27 8.2 10 13 10 13v6c0 .55.45 1 1 1h2c.55 0 1-.45 1-1v-6s3.72-4.8 5.74-7.39c.51-.66.04-1.61-.79-1.61H5.04c-.83 0-1.3.95-.79 1.61z")
    # Material "archive" (a lidded box) - the zip guard below.
    _stg_i_archive = _stg_ico("M20.54 5.23l-1.39-1.68C18.88 3.21 18.47 3 18 3H6c-.47 0-.88.21-1.16.55L3.46 5.23C3.17 5.57 3 6.02 3 6.5V19c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V6.5c0-.48-.17-.93-.46-1.27zM12 17.5L6.5 12H10v-2h4v2h3.5L12 17.5zM5.12 5l.81-1h12l.94 1H5.12z")
    _stg_i_folder = _stg_ico("M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z")
    _stg_i_bell   = _stg_ico("M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z")
    _stg_i_grad   = _stg_ico("M5 13.18v4L12 21l7-3.82v-4L12 17l-7-3.82zM12 3L1 9l11 6 9-4.91V17h2V9L12 3z")
    _stg_i_errlog = _stg_ico("M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm-1 9h-2v2h2v2h-2v2h-2v-2H9v-2h2v-2H9V9h2V7h2v2h2v2zM13 9V3.5L18.5 9H13z")
    # The health record. Same document body and folded corner as the error log
    # above - they ARE both files the app writes, and reading as a family is
    # right - with a heartbeat where that one has a cross, which is the whole
    # difference the user has to see. It previously reused _stg_i_errlog
    # verbatim, so the two cards in the same row carried an identical glyph.
    # A literal "?" was the obvious alternative and is declined on purpose:
    # the ? glyph means "there is a tooltip here" everywhere else in this
    # dialog (see _STG_HELP_GLYPH), so it would collide with itself.
    _stg_i_health = _stg_ico(
        "M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6z"
        "M13 9V3.5L18.5 9H13z"
        "M11.6 10.8l-1.85 4.3-.72-1.5H6.9v1.5h1.18l1.42 2.95h1.02l1.72-4 1.28 2.85"
        "h1.03l.92-1.8h1.63v-1.5h-2.55l-.5.98-1.42-3.18z",
        evenodd=True)
    _stg_i_clock  = _stg_ico("M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z")
    _stg_i_caption = _stg_ico("M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zM4 12h4v2H4v-2zm10 6H4v-2h10v2zm6 0h-4v-2h4v2zm0-4H10v-2h10v2z")
    # Film strip - the Panopto master switch. Distinct from _stg_i_caption
    # (subtitles), which sits one card below it and means transcription.
    _stg_i_movie = _stg_ico("M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4z")
    # Lifebuoy - reads as "help/support" without reusing the ? glyph, which
    # in this app means "there is a tooltip here".
    _stg_i_help = "data:image/svg+xml;base64," + base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#a0aec0" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/><line x1="4.93" y1="4.93" x2="9.17" y2="9.17"/><line x1="14.83" y1="14.83" x2="19.07" y2="19.07"/><line x1="14.83" y1="9.17" x2="19.07" y2="4.93"/><line x1="4.93" y1="19.07" x2="9.17" y2="14.83"/></svg>').decode()
    _stg_i_history = "data:image/svg+xml;base64," + base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#a0aec0" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>').decode()

    # ── The ONE card-header recipe ────────────────────────────────────
    # Every card in this dialog opens with icon + title + description, and
    # each of the 13 used to hand-write its own ~600-character f-string
    # repeating the same margin-top:-5px / margin-bottom:3px / padding:0 0 4px
    # tuple. Any drift between them was invisible in review and read to the
    # user as the dialog getting less harmonious the further they scrolled.
    # Stating the spacing exactly once makes the cards structurally identical
    # rather than coincidentally identical - which is the whole point.
    #
    # `tip` folds a long secondary explanation into the inline ? glyph instead
    # of paying for it in card height (see the .stg-help note in the CSS);
    # `extra` carries a card-specific trailer such as a status dot row.
    def _stg_card_head(icon, title, desc, tip=None, extra=""):
        _tip = (f'<span class="stg-help" title="{_he(tip)}">{_STG_HELP_GLYPH}</span>'
                if tip else "")
        return (
            '<div style="padding:0 0 4px 0;">'
            '<div style="display:flex;align-items:center;gap:7px;'
            'margin-bottom:3px;margin-top:-5px;">'
            f'<img src="{icon}" width="18" height="18" style="flex-shrink:0;">'
            '<span style="font-size:1.1rem;font-weight:600;color:#e2e8f0;">'
            f'{title}</span></div>'
            '<div style="font-size:0.78rem;color:#94a3b8;line-height:1.4;">'
            f'{desc}{_tip}</div>{extra}</div>'
        )

    # Section rule. `first` drops the leading air so the topmost header sits
    # flush against the scroll body's edge.
    def _stg_section(label, first=False):
        return (f'<div style="padding:{"2px" if first else "10px"} 0 1px 0;">'
                '<span style="font-size:0.7rem;font-weight:800;'
                'text-transform:uppercase;letter-spacing:0.12em;color:#e2e8f0;">'
                f'{label}</span></div>')

    # Clear all staged (unsaved) settings state on dismissal. Save and Cancel
    # already pop '_temp_default_path', but a backdrop/ESC dismiss runs neither -
    # so a picked-but-unsaved folder (and any toggled temp_* control) would
    # linger and look applied when the dialog is reopened. Passing a callable to
    # on_dismiss both reruns the app and runs this cleanup first.
    # Does the dialog currently hold a staged value that differs from what is
    # actually applied? Read straight out of session_state (Streamlit writes
    # every widget's value there before the script body runs), so this answers
    # correctly from BOTH exit paths - Cancel, which has the locals, and the
    # backdrop/ESC dismiss callback, which has nothing but session state.
    # A missing key means the widget never rendered -> nothing staged for it.
    def _stg_has_unsaved_changes():
        _ss = st.session_state
        _pairs = (
            ('temp_max_downloads', 'concurrent_downloads', 5, int),
            ('temp_cbs_filters', 'enable_cbs_filters', False, bool),
            ('temp_max_size_enabled', 'max_file_size_enabled', False, bool),
            ('temp_max_size_mb', 'max_file_size_mb', 500, int),
            ('temp_archive_max_enabled', 'archive_max_files_enabled', False, bool),
            ('temp_archive_max_files', 'archive_max_files', 1000, int),
            ('temp_notifications_enabled', 'notifications_enabled', True, bool),
            ('temp_error_log_enabled', 'error_log_enabled', False, bool),
            ('temp_debug_mode', 'debug_mode', False, bool),
            ('temp_use_12h_format', 'use_12h_format', False, bool),
            ('temp_sync_history_retention', 'sync_history_retention', 50, int),
            ('temp_show_help_text', 'show_help_text', True, bool),
            ('temp_panopto_globally_enabled', 'panopto_globally_enabled', True, bool),
        )
        for _tkey, _skey, _default, _cast in _pairs:
            if _tkey not in _ss:
                continue
            try:
                if _cast(_ss[_tkey]) != _cast(_ss.get(_skey, _default)):
                    return True
            except (TypeError, ValueError):
                # A value that will not cast is not a reason to lose the
                # dialog - treat it as "no change" and keep going.
                continue
        # The folder picker stages into its own key, not a widget key.
        if '_temp_default_path' in _ss:
            if (_ss.get('_temp_default_path') or '') != (
                    _ss.get('default_download_path', '') or ''):
                return True
        return False

    def _stg_dismiss_cleanup():
        # Warn BEFORE the staged values are wiped below - once they are gone
        # there is no way to tell a dismissed edit from a dismissed no-op.
        if _stg_has_unsaved_changes():
            st.session_state['_stg_unsaved_toast'] = True
        for _k in ('_temp_default_path', '_stg_reopen_dialog', '_stg_dialog_open',
                   'temp_max_downloads', 'temp_max_size_enabled', 'temp_max_size_mb',
                   'temp_error_log_enabled', 'temp_debug_mode',
                   'temp_notifications_enabled', 'temp_cbs_filters',
                   'temp_use_12h_format', 'temp_sync_history_retention',
                   'temp_show_help_text'):
            st.session_state.pop(_k, None)

    @st.dialog("\u200b", width="large", on_dismiss=_stg_dismiss_cleanup)
    def _global_settings_dialog():
        # Warm the transcription hardware probe in the background the moment
        # Settings opens, so "Configure transcription" (which imports the heavy
        # faster-whisper/ctranslate2 backend on first use) opens promptly instead
        # of blocking for a beat. Idempotent + non-blocking; safe on every rerun.
        try:
            from panopto.hardware import warm_compute_hardware_async
            warm_compute_hardware_async()
        except Exception:
            pass

        st.html("""<style>
        div[data-testid="stDialog"] button[aria-label="Close"] { display: none !important; }

        /* NOTE (Streamlit 1.51): stDialogScrollableBody no longer exists, and there
           is no separate padded body wrapper left to compact - the content
           stVerticalBlock scrolls directly and carries no padding of its own.
           `div[role="dialog"] > div:first-child` is the HEADER (it holds the title),
           so squeezing its padding clips the custom -70px header. Nothing to do here. */

        /* Tight global vertical gap */
        div[data-testid="stDialog"] [data-testid="stVerticalBlock"] { gap: 0.3rem !important; }

        /* ── Cards ──
           1.51 puts the st-key-* class directly ON the container's stVerticalBlock
           (the old stVerticalBlockBorderWrapper element no longer exists), so the
           card skin goes on the keyed div itself. Streamlit's own border=True
           border/radius/padding lives on the same element but loses to !important.

           The surface is the app's standard card idiom - a faint white wash over
           the dark ground, measured off the Custom Download cards - NOT the navy
           BG_CARD. (An earlier pass keyed this rule off the retired
           stVerticalBlockBorderWrapper, so it never applied; moving it onto the
           keyed div switched a #2D3248 navy on for the first time and every card
           went grey-purple.) */
        div[data-testid="stDialog"] div[class*="st-key-stg_card_"] {
            background: rgba(255,255,255,0.04) !important;
            border: 1px solid rgba(250,250,250,0.2) !important;
            border-radius: 10px !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.35) !important;
            position: relative !important;
            padding: 11px !important;
            gap: 0.25rem !important;
        }

        /* The transcription card is a PANOPTO surface, so it wears the same
           purple as every other Panopto card (pan_info_card on Custom Download,
           the tx_setup_card notice). Must come AFTER the blanket rule above -
           "stg_card_pan" contains "stg_card_", so the generic selector matches it
           too and would otherwise win on source order. */
        div[data-testid="stDialog"] div[class*="st-key-stg_card_pan"] {
            background: rgba(176,157,254,0.06) !important;
            border: 1px solid rgba(176,157,254,0.28) !important;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_pan button {
            background: rgba(176,157,254,0.10) !important;
            border: 1px solid rgba(176,157,254,0.35) !important;
            color: #d8caff !important;
            font-weight: 600 !important;
            border-radius: 8px !important;
            transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_pan button:hover {
            background-color: rgba(176,157,254,0.18) !important;
            border-color: #b89dfe !important;
            color: #ffffff !important;
        }
        div[data-testid="stDialog"] div[class*="st-key-stg_card_"] [data-testid="stVerticalBlock"] {
            gap: 0.25rem !important;
        }

        /* ── Equal-height cards: ONE rule for every row ──
           This was three near-identical per-key blocks (speed/maxsize/errlog,
           sound/cbs/time, helptext/history) that had to be extended by hand for
           every new card - which is exactly why the later cards never got it.
           Keyed on the shared st-key-stg_card_ prefix instead, so a new card is
           height-matched for free.

           Scoped INSIDE stHorizontalBlock on purpose. `flex: 1` on a card whose
           parent is a column-direction flex box means "grow vertically", which
           is the equal-height trick when the card sits in a columns row - but
           would make a standalone full-width card (the macOS Full Disk Access
           one) stretch to fill the fixed-height scroll body whenever the
           content happens to be shorter than it. */
        div[data-testid="stDialog"] [data-testid="stHorizontalBlock"] [data-testid="stLayoutWrapper"]:has(> div[class*="st-key-stg_card_"]) {
            flex: 1 !important;
        }
        div[data-testid="stDialog"] [data-testid="stHorizontalBlock"] div[class*="st-key-stg_card_"] {
            flex: 1 !important;
            display: flex !important;
            flex-direction: column !important;
            height: 100% !important;
        }
        /* A row's direct children are stColumn - NOT stLayoutWrapper - so the
           `:has(> stLayoutWrapper)` form of this matches nothing. */
        div[data-testid="stDialog"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] div[class*="st-key-stg_card_"]) {
            align-items: stretch !important;
        }

        /* Every card's controls sit on the same line across a row, however long
           each description ran. The auto margin goes on the FIRST control (the
           card's second child - child one is always the header block), never on
           the last: on a two-control card like the error log's, a last-child
           auto margin splits the pair and strands the divider mid-card. */
        div[data-testid="stDialog"] [data-testid="stHorizontalBlock"] div[class*="st-key-stg_card_"] > div:nth-child(2) {
            margin-top: auto !important;
        }
        /* ...except the Panopto master switch, which is a third of the width of
           a card carrying a description, a status line AND a button, so the
           bottom of that row is a long way from its own copy. Bottom-aligning
           earns nothing across a gap that large - the toggle just floats alone
           in the middle of the card, disowned by the sentence it belongs to.

           The selector has to out-specify the auto rule above, not merely come
           after it: both are !important, so specificity decides, and the first
           version of this exemption lost 3-to-4 and did nothing at all. Naming
           the card's own testid (it IS a vertical block) puts it ahead. */
        div[data-testid="stDialog"] [data-testid="stHorizontalBlock"] div[data-testid="stVerticalBlock"][class*="st-key-stg_card_pan_enabled"] > div:nth-child(2) {
            margin-top: 0 !important;
        }

        /* ── Row rhythm: both axes agree ──
           Streamlit puts 16px between the cards INSIDE a row, while the dialog's
           vertical block gap is 0.3rem - so a grid of cards read as tight bands
           with airy columns. Each band adds the remainder itself, which keeps
           the tight gap under a section header (that one is deliberate) while
           making card-to-card spacing identical in both directions.

           The band is the stLayoutWrapper that CONTAINS the horizontal block,
           not the horizontal block itself - that wrapper is the scroll body's
           flex item, and it is the only element whose margin lands between two
           rows. (Measured chain: scroll body > stLayoutWrapper >
           stHorizontalBlock > stColumn > stVerticalBlock > stLayoutWrapper >
           card. A row's children are stColumn, so any `:has(> stLayoutWrapper)`
           form matches nothing.)
           `stg_card_path` is named separately because a full-width card is its
           own band, and a blanket rule on every card's wrapper would also hit
           the per-column wrappers that carry the equal-height flex chain. */
        div[data-testid="stDialog"] [data-testid="stLayoutWrapper"]:has(> [data-testid="stHorizontalBlock"] div[class*="st-key-stg_card_"]),
        div[data-testid="stDialog"] [data-testid="stLayoutWrapper"]:has(> div[class*="st-key-stg_card_path"]) {
            margin-bottom: calc(16px - 0.3rem) !important;
        }

        /* ── The transcription card while Panopto is switched off ──
           The app's ONE disabled recipe (global.css button[disabled]), applied
           to the card so the description, the status line and the button all
           go unavailable together - the button alone would read as a broken
           control on a live card.

           `filter` COMPOSES down the tree: the disabled button inside would
           otherwise be rendered through brightness(0.5) twice and land at a
           quarter of its paint, which is the "never stack a second dim on the
           shared recipe" rule. So the card carries the dim exactly once and the
           button opts out - the same explicit `filter: none` exemption the
           card-header rerun locks use. */
        div[data-testid="stDialog"] div[class*="st-key-stg_card_pan_off"] {
            filter: brightness(0.5) saturate(0.5) !important;
        }
        div[data-testid="stDialog"] div[class*="st-key-stg_card_pan_off"] button[disabled] {
            filter: none !important;
        }
        /* A disabled button carrying help= is wrapped in stTooltipHoverTarget,
           so it is no longer a direct child of stButton and silently loses the
           full-width sizing - it would render narrower than the enabled state
           it replaces. */
        div[data-testid="stDialog"] div.st-key-stg_btn_pan [data-testid="stTooltipHoverTarget"] {
            display: block !important; width: 100% !important;
        }

        /* ── Toggles ──
           st.toggle renders through [data-testid="stCheckbox"] in 1.51; there is no
           stToggle testid. Label sits left, the switch is pinned to the card's right
           edge.

           Two traps, both learned by measuring the live DOM:
           (a) EVERY label selector must use the DIRECT-CHILD form '> label'. A plain
               descendant '[data-testid="stCheckbox"] label' ALSO matches the nested
               label element that wraps a help= tooltip icon; forcing that one to
               width:100% makes it consume the whole row and starves the real label
               text, which then wraps one word per line (or clips to an ellipsis).
               (Never write a literal angle-bracket tag name in a comment inside an
               st.html style block - it terminates the style element and silently
               kills every rule in it.)
           (b) A toggle's element-container gets a CONTENT-based explicit width in
               1.51, so without the width:100% chain below the switch never reaches
               the card's right edge and space-between squeezes the text instead. */
        div[data-testid="stDialog"] div[class*="st-key-stg_card_"] > div[data-testid="stElementContainer"]:has([data-testid="stCheckbox"]),
        div[data-testid="stDialog"] div[class*="st-key-stg_card_"] div[data-testid="stCheckbox"],
        div[data-testid="stDialog"] div[class*="st-key-stg_card_"] div[data-testid="stCheckbox"] > label {
            width: 100% !important; max-width: 100% !important;
        }
        /* (c) The switch sits IMMEDIATELY after its label with one 8px gap, not
               pinned to the card's right edge. In `row-reverse` the main-axis
               start is on the RIGHT, so packing the pair against the left edge
               is `justify-content: flex-end` (this used to be `space-between`,
               which flung the switch to the far edge and left a big dead gap
               between a short label and its own control). */
        div[data-testid="stDialog"] div[class*="st-key-stg_card_"] div[data-testid="stCheckbox"] > label {
            display: flex !important; flex-direction: row-reverse !important;
            justify-content: flex-end !important; align-items: center !important;
            padding: 2px 0 0 0 !important; cursor: pointer !important; gap: 8px !important;
        }
        /* (d) The label block must shrink-wrap its text, or it would still eat
               the whole row and push the switch back out to the right edge -
               AND it must give back BaseWeb's 8px left padding.

               The real flex item here is an UNNAMED wrapper div; stWidgetLabel
               is its child, not the label's, so the old form of this rule
               ('> label > [data-testid=stWidgetLabel]') matched nothing at all.
               BaseWeb puts padding-left on that wrapper because Streamlit
               renders the control with the label placed to the right of the
               switch. Reversing the row moves the wrapper to the card's LEFT
               edge, where the padding stops separating label from switch and
               instead indents the text past the description above it - by
               exactly 8.0px on all nine toggles (measured 2026-07-31), which
               is what made every toggle row look mysteriously inset. The
               separation is already supplied by the label's own gap: 8px. */
        div[data-testid="stDialog"] div[class*="st-key-stg_card_"] div[data-testid="stCheckbox"] > label > div:has(> [data-testid="stWidgetLabel"]) {
            flex: 0 1 auto !important; width: auto !important;
            padding-left: 0 !important;
        }
        div[data-testid="stDialog"] div[class*="st-key-stg_card_"] div[data-testid="stCheckbox"] p {
            font-size: 0.8rem !important; color: #94a3b8 !important;
            font-weight: 400 !important; margin: 0 !important; line-height: 1.3 !important;
        }
        /* The label text takes the free space; the tooltip icon keeps its own size. */
        div[data-testid="stDialog"] div[class*="st-key-stg_card_"] [data-testid="stWidgetLabel"] {
            align-items: center !important; gap: 5px !important; min-width: 0 !important;
        }
        div[data-testid="stDialog"] div[class*="st-key-stg_card_"] [data-testid="stWidgetLabel"] > label {
            flex: 0 0 auto !important; width: auto !important;
        }

        /* ── Number input ──
           Streamlit's dark theme leaves the field's shell borderless, so a
           number input read as floating text rather than an editable control.
           Give it the same faint outline the read-only path box already uses. */
        div[data-testid="stDialog"] [data-testid="stNumberInput"] { margin-top: 4px !important; }
        div[data-testid="stDialog"] [data-testid="stNumberInput"] label p {
            font-size: 0.78rem !important; color: #64748b !important;
        }
        /* ONE border, on stNumberInputContainer - the element that wraps the
           field AND the -/+ steppers. Two things went wrong when it sat on the
           inner div[data-baseweb="input"] instead:
             - that element spans only the field (291px of a 357px control), so
               the steppers hung outside the outline; and its 0.909px
               fractional border anti-aliased the horizontal edges away at this
               device pixel ratio while the corner arcs survived, which is why
               it read as "left and right only".
             - Streamlit's own focus styling then lit the container, the
               steppers AND the divider between them independently, so clicking
               the field produced three separate blue edges.
           So: one solid 1px outline on the outer container, and every inner
           surface/border explicitly cleared. */
        div[data-testid="stDialog"] [data-testid="stNumberInputContainer"] {
            background: rgba(255,255,255,0.03) !important;
            border: 1px solid rgba(255,255,255,0.16) !important;
            border-radius: 8px !important;
            box-shadow: none !important;
            transition: border-color 0.15s ease !important;
        }
        div[data-testid="stDialog"] [data-testid="stNumberInputContainer"]:hover {
            border-color: rgba(255,255,255,0.28) !important;
        }
        div[data-testid="stDialog"] [data-testid="stNumberInputContainer"]:focus-within {
            border-color: rgba(63,217,255,0.45) !important;
        }
        div[data-testid="stDialog"] [data-testid="stNumberInputContainer"] div[data-baseweb="input"],
        div[data-testid="stDialog"] [data-testid="stNumberInputContainer"] div[data-baseweb="base-input"],
        div[data-testid="stDialog"] [data-testid="stNumberInputStepUp"],
        div[data-testid="stDialog"] [data-testid="stNumberInputStepDown"] {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            outline: none !important;
        }
        div[data-testid="stDialog"] [data-testid="stNumberInputStepUp"]:hover,
        div[data-testid="stDialog"] [data-testid="stNumberInputStepDown"]:hover {
            background: rgba(255,255,255,0.06) !important;
        }
        /* Dim the whole number input block when disabled (Skip large files toggle off) */
        div[data-testid="stDialog"] div[class*="st-key-stg_card_maxsize"] [data-testid="stNumberInput"]:has(input:disabled) {
            opacity: 0.35 !important;
            pointer-events: none !important;
        }

        /* ── Debug toggle ──
           Same weight as "Create error log" above it, sitting directly under a
           divider - NOT a shrunken afterthought floated to the card's bottom
           edge. It used to carry margin-top:auto + scale(0.9) + opacity 0.55 +
           a 0.72rem label, which left it hanging alone in dead space and
           reading as a different class of control from its sibling toggle. */
        div[data-testid="stDialog"] div[class*="st-key-stg_card_errlog"] > div.st-key-temp_debug_mode {
            margin-top: 0 !important;
            padding-top: 9px !important;
            border-top: 1px solid rgba(255,255,255,0.08) !important;
        }
        /* Recessed until it matters. Same SIZE and weight as "Create error log"
           above it - only the opacity differs - so the two read as the same
           class of control while still ranking debug logging as the secondary,
           troubleshooting-only one. State-aware rather than a flat dim: full
           brightness on hover, and stays lit while it is switched on. */
        div[data-testid="stDialog"] div.st-key-temp_debug_mode [data-testid="stCheckbox"] {
            opacity: 0.5 !important;
            transition: opacity 0.15s ease !important;
        }
        div[data-testid="stDialog"] div.st-key-temp_debug_mode [data-testid="stCheckbox"]:hover,
        div[data-testid="stDialog"] div.st-key-temp_debug_mode [data-testid="stCheckbox"]:has(input:checked) {
            opacity: 1 !important;
        }

        /* ── Folder buttons ──
           Both are pinned to the SAME explicit 34px. Clear carries a `help=`
           while it is disabled, and Streamlit then wraps its button in a
           [data-testid="stTooltipHoverTarget"] so it is no longer a direct
           child of .stButton - which silently drops the shared button sizing
           and rendered Clear taller than Choose Folder right next to it.
           `height: auto` cannot fix that (the two boxes just grow differently),
           so the height is stated once and the tooltip wrapper is made a
           full-width block that passes it through. */
        div[data-testid="stDialog"] div.st-key-stg_btn_clear [data-testid="stTooltipHoverTarget"] {
            display: block !important; width: 100% !important; height: 34px !important;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_pick button,
        div[data-testid="stDialog"] div.st-key-stg_btn_clear button {
            background: rgba(255,255,255,0.04) !important;
            border: 1px solid rgba(255,255,255,0.10) !important;
            min-height: 34px !important;
            height: 34px !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            font-size: 0.8rem !important;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_pick button:hover,
        div[data-testid="stDialog"] div.st-key-stg_btn_clear button:hover {
            background: rgba(255,255,255,0.08) !important;
            border-color: rgba(255,255,255,0.18) !important;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_pick button::before {
            content: ''; display: inline-block; width: 14px; height: 14px;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z'%3E%3C%2Fpath%3E%3C%2Fsvg%3E");
            background-size: contain; background-repeat: no-repeat;
            margin-right: 7px; vertical-align: middle;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_clear button::before {
            content: ''; display: inline-block; width: 13px; height: 13px;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cline x1='18' y1='6' x2='6' y2='18'%3E%3C%2Fline%3E%3Cline x1='6' y1='6' x2='18' y2='18'%3E%3C%2Fline%3E%3C%2Fsvg%3E");
            background-size: contain; background-repeat: no-repeat;
            margin-right: 7px; vertical-align: middle;
        }

        /* ── Panopto transcription "Configure" button (purple accent) ── */
        div[data-testid="stDialog"] div.st-key-stg_btn_pan button {
            background: rgba(176,157,254,0.10) !important;
            border: 1px solid rgba(176,157,254,0.35) !important;
            color: #d8caff !important;
            min-height: unset !important; height: auto !important;
            padding-top: 6px !important; padding-bottom: 6px !important;
            font-size: 0.82rem !important; font-weight: 600 !important;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_pan button:hover {
            background: rgba(176,157,254,0.18) !important;
            border-color: #b89dfe !important; color: #ffffff !important;
        }

        /* ── App health record "Reveal" button (neutral slate accent) ──
           Same shape as the Panopto configure button above so the two read as
           one class of control, but in the neutral family: purple is Panopto's
           colour in this app and this card has nothing to do with Panopto.
           (It shipped as a bare default st.button next to an st.download_button
           - the only two unstyled controls left in the dialog.) */
        div[data-testid="stDialog"] div.st-key-stg_btn_diag_reveal button {
            background: rgba(255,255,255,0.05) !important;
            border: 1px solid rgba(255,255,255,0.14) !important;
            color: #cbd5e1 !important;
            min-height: unset !important; height: auto !important;
            padding-top: 6px !important; padding-bottom: 6px !important;
            font-size: 0.82rem !important; font-weight: 600 !important;
            transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_diag_reveal button:hover {
            background: rgba(255,255,255,0.10) !important;
            border-color: rgba(255,255,255,0.30) !important; color: #ffffff !important;
        }
        /* Folder-open glyph, drawn the same way as the Choose Folder button's.
           Grey at rest, white on hover, matching the label's own transition. */
        div[data-testid="stDialog"] div.st-key-stg_btn_diag_reveal button p::before {
            content: ''; display: inline-block; width: 14px; height: 14px;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23cbd5e1' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M6 14l1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.55 6a2 2 0 0 1-1.94 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2'%3E%3C%2Fpath%3E%3C%2Fsvg%3E");
            background-size: contain; background-repeat: no-repeat; flex-shrink: 0;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_diag_reveal button:hover p::before {
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M6 14l1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.55 6a2 2 0 0 1-1.94 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2'%3E%3C%2Fpath%3E%3C%2Fsvg%3E");
        }
        /* The full centring chain from the HACKS doc: flexing only the label p
           is not enough, because stMarkdownContainer is the button's actual
           flex child and stays uncentred. margin:0 on the p is required - its
           default bottom margin is part of the flex item's margin-box, so
           align-items:center would centre the margin-box and push the visible
           content up. Do NOT add line-height:1 here (it shrinks the line box
           below the glyph height and the text reads as mis-centred). */
        div[data-testid="stDialog"] div.st-key-stg_btn_diag_reveal button {
            align-items: center !important; justify-content: center !important;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_diag_reveal button [data-testid="stMarkdownContainer"] {
            display: flex !important; align-items: center !important;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_diag_reveal button p {
            display: inline-flex !important; align-items: center !important;
            gap: 8px !important; margin: 0 !important;
        }

        /* ── Full Disk Access "Open Settings" button (blue accent) ──
           Same shape as the Panopto configure button above, in the FDA
           card's blue family so the card reads as one story. */
        div[data-testid="stDialog"] div.st-key-stg_fda_grant_btn button {
            background: rgba(59,130,246,0.10) !important;
            border: 1px solid rgba(59,130,246,0.35) !important;
            color: #b6d3ff !important;
            min-height: unset !important; height: auto !important;
            padding-top: 6px !important; padding-bottom: 6px !important;
            font-size: 0.82rem !important; font-weight: 600 !important;
        }
        div[data-testid="stDialog"] div.st-key-stg_fda_grant_btn button:hover {
            background: rgba(59,130,246,0.18) !important;
            border-color: #60a5fa !important; color: #ffffff !important;
        }

        /* ── Inline help icon (used inside a card's description HTML) ──
           It exists so a long secondary explanation can be folded away instead
           of bloating a card's height - the Skip-large-files card was two lines
           taller than its neighbours purely because of one.

           The GLYPH is Streamlit's own tooltip icon, copied exactly: 16x16,
           `currentColor` at #fafafa, stroke-width 2, the lucide help-circle
           path. It has to be hand-rolled because it lives inside raw HTML where
           Streamlit's React-portal tooltip cannot be reached - but it must not
           LOOK hand-rolled, and the first version (a bordered circle with a
           text "?" at #94a3b8) sat right next to the real thing in the
           neighbouring card and read as a different control.
           The tooltip itself is a native `title`; a CSS bubble would have to
           escape the card's stacking context. */
        .stg-help {
            display: inline-flex; align-items: center; justify-content: center;
            width: 16px; height: 16px; margin-left: 5px;
            cursor: help; vertical-align: -3px;
            opacity: 0.75; transition: opacity 0.15s ease;
        }
        .stg-help:hover { opacity: 1; }
        .stg-help img { display: block; width: 16px; height: 16px; }
        </style>""")

        st.markdown("""
<div style="display:flex;align-items:center;gap:10px;margin-top:-70px;">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#e2e8f0" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
<span style="font-size:1.6rem;font-weight:600;color:#f1f5f9;letter-spacing:-0.01em;">Settings</span>
</div>
""", unsafe_allow_html=True)

        with st.container(height=620, border=False):

            # ── DOWNLOADS & STORAGE ───────────────────────────────────
            # One section for everything that shapes a run plus everything the
            # app keeps on disk as a result. It absorbed the old standalone
            # SAVE FOLDER section (a single card never earned a heading of its
            # own) and Sync history, which is a retention setting rather than a
            # look-and-feel preference. The two log toggles went the other way,
            # down to TROUBLESHOOTING - they produce diagnostic artefacts and
            # do not change which files a run fetches.
            st.html(_stg_section("DOWNLOADS & STORAGE", first=True))

            # Row 1 - the four numeric settings, one anatomy across all of them
            # so the row reads as one set. Skip large files and Skip huge
            # archives are deliberately IDENTICAL in shape (toggle ABOVE its
            # number input, never beside it): they answer the same kind of
            # question, and looked like two unrelated controls only because the
            # archive one had been given a full-width row and split its pair
            # into side-by-side columns to fill it.
            _stg_skip_tip = (
                "Skipped files are marked as ignored, so future syncs don't re-list them. "
                "You can restore them at any time from the Sync Hub's ignored-files list - "
                "including after you raise this limit."
            )
            _stg_arch_tip = (
                "Applies to downloads and syncs alike. All archives over the limit are left as archives in your course folder, so nothing is lost and you can extract it yourself."
            )

            _dc1, _dc2, _dc3, _dc4 = st.columns(4)
            with _dc1:
                with st.container(border=True, key="stg_card_speed"):
                    st.html(_stg_card_head(
                        _stg_i_speed, "Simultaneous downloads",
                        "How many files download at once. Higher values may "
                        "increase download speed.",
                        extra='<div style="font-size:0.75rem;color:#f59e0b;'
                              'line-height:1.35;margin-top:5px;">Lower this if you '
                              'encounter download issues. Default = 5.</div>'))
                    temp_max = st.slider("Speed", min_value=1, max_value=15, value=st.session_state.get('concurrent_downloads', 5), key="temp_max_downloads", label_visibility="collapsed")
            with _dc2:
                with st.container(border=True, key="stg_card_maxsize"):
                    # The "skipped files are ignored" explanation is folded into
                    # the inline ? badge: as visible copy it made this card two
                    # lines taller than its two neighbours, and since the three
                    # are height-matched it stretched the whole row.
                    st.html(_stg_card_head(
                        _stg_i_filter, "Skip large files",
                        "Skip files above a set size, so a few huge files can't "
                        "bloat your drive.",
                        tip=_stg_skip_tip))
                    temp_size_enabled = st.toggle("Enable limit", value=st.session_state.get('max_file_size_enabled', False), key="temp_max_size_enabled")
                    # step=1, NOT 50. Streamlit disables the minus button while
                    # `value - step < min_value`, so a step of 50 greyed it out
                    # for every value at or below 50 - while typing 5 straight
                    # into the field worked fine. One control, two answers.
                    # 1 MB is the floor (the old 50 was arbitrary: most slides
                    # and PDFs are 1-2 MB, so a limit under 50 MB is a perfectly
                    # ordinary thing to want). It is re-clamped on save.
                    temp_size_mb = st.number_input("Max size (MB)", min_value=1, max_value=100000, step=1, value=max(1, int(st.session_state.get('max_file_size_mb', 500))), key="temp_max_size_mb", disabled=not temp_size_enabled)
            with _dc3:
                with st.container(border=True, key="stg_card_archive"):
                    st.html(_stg_card_head(
                        _stg_i_archive, "Skip huge archives",
                        "Don't unpack a .zip that would add an enormous number "
                        "of files to your course folder.",
                        tip=_stg_arch_tip))
                    temp_arch_enabled = st.toggle(
                        "Enable limit",
                        value=st.session_state.get('archive_max_files_enabled', False),
                        key="temp_archive_max_enabled")
                    # step=1 for the same reason as the size cap: Streamlit
                    # greys the minus button whenever value - step < min_value.
                    temp_arch_files = st.number_input(
                        "Max files inside an archive", min_value=1, max_value=1000000, step=1,
                        value=max(1, int(st.session_state.get('archive_max_files', 1000))),
                        key="temp_archive_max_files", disabled=not temp_arch_enabled)

            with _dc4:
                # L-13: Sync history retention - exposed so power users who sync
                # multiple times daily can extend beyond the default 50 entries.
                # Fourth in the row rather than beside the path card: it is a
                # bare number input, the same amount of chrome as the two limit
                # cards beside it, and pairing it with the path card left that
                # card at two thirds for no reason.
                with st.container(border=True, key="stg_card_history"):
                    st.html(_stg_card_head(
                        _stg_i_history, "Sync history",
                        "How many past sync operations to keep in the history "
                        "panel. Higher values use slightly more disk space."))
                    temp_history_retention = st.number_input(
                        "Keep last N syncs", min_value=10, max_value=500, step=10,
                        value=int(st.session_state.get('sync_history_retention', 50)),
                        key="temp_sync_history_retention",
                    )

            # Row 2 - where files land. Full width, and the one card in this
            # dialog that earns it: the path box is the only value display here
            # that has to render an arbitrarily long absolute path, and it reads
            # as the section's conclusion under the row of limits above it.
            with st.container(border=True, key="stg_card_path"):
                st.html(_stg_card_head(
                    _stg_i_folder, "Default save location",
                    "The output folder every download starts from, so you "
                    "don't have to set it each time. Default = your Downloads folder."))

                if '_temp_default_path' not in st.session_state:
                    st.session_state['_temp_default_path'] = st.session_state.get('default_download_path', '') or ''

                _display_path = st.session_state['_temp_default_path'] or "Set to default: Downloads folder"
                _esc_path = (_display_path.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;").replace('"', "&quot;"))
                # The box truncates with an ellipsis, so a very long path still
                # cannot break the layout - but a truncated path the user cannot
                # read is a poor trade, so the full string is carried in a
                # native title.
                st.html(f"""<div style="padding:0 0 6px 0;"><div title="{_esc_path}" style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.1);border-radius:7px;padding:6px 12px;font-size:0.79rem;color:rgba(255,255,255,0.45);font-family:monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.5;">{_esc_path}</div></div>""")

                _pc1, _pc2 = st.columns([3, 1])
                with _pc1:
                    if st.button("Choose Folder", key="stg_btn_pick", use_container_width=True):
                        from shared.helpers import native_folder_picker
                        picked = native_folder_picker(initial_dir=st.session_state.get('_temp_default_path') or None)
                        if picked:
                            st.session_state['_temp_default_path'] = picked
                            st.session_state['_stg_reopen_dialog'] = True
                            st.rerun(scope="app")
                with _pc2:
                    if st.button("Clear", key="stg_btn_clear", use_container_width=True,
                                 disabled=not st.session_state['_temp_default_path'],
                                 help=None if st.session_state['_temp_default_path'] else
                                      "No custom folder is set, so there is nothing to clear."):
                        st.session_state['_temp_default_path'] = ''
                        st.session_state['_stg_reopen_dialog'] = True
                        st.rerun(scope="app")

            # ── PREFERENCES ───────────────────────────────────────────
            # Four single-toggle cards, four across. They are the same control
            # with the same anatomy, so they belong on one line - as two rows of
            # three-plus-one they cost twice the height and read as two
            # unrelated groups. At quarter width the copy has to be one tight
            # sentence; anything longer goes in the ? glyph rather than being
            # cut, which is the same trade the two limit cards above make.
            st.html(_stg_section("PREFERENCES"))

            _p1, _p2, _p3, _p4 = st.columns(4)
            with _p1:
                with st.container(border=True, key="stg_card_sound"):
                    st.html(_stg_card_head(
                        _stg_i_bell, "Notifications",
                        "A sound and a native notification when a download or "
                        "sync finishes."))
                    temp_notifications = st.toggle("Enable notifications", value=st.session_state.get('notifications_enabled', True), key="temp_notifications_enabled")
            with _p2:
                with st.container(border=True, key="stg_card_cbs"):
                    st.html(_stg_card_head(
                        _stg_i_grad, "CBS filters",
                        "Adds course type, semester and year filters to every "
                        "course list. For CBS students."))
                    temp_cbs = st.toggle("Enable CBS filters", value=st.session_state.get('enable_cbs_filters', False), key="temp_cbs_filters")
            with _p3:
                with st.container(border=True, key="stg_card_time"):
                    st.html(_stg_card_head(
                        _stg_i_clock, "Time format",
                        "Show all times as 12-hour AM/PM instead of the default "
                        "24-hour clock."))
                    temp_time_12h = st.toggle("Use 12-hour format", value=st.session_state.get('use_12h_format', False), key="temp_use_12h_format")
            with _p4:
                # Lets an experienced user reclaim the screen space the
                # onboarding copy occupies, without hiding anything they would
                # actually need. See shared/helpers.py:help_text_enabled for the
                # exact boundary between "help" and "information".
                with st.container(border=True, key="stg_card_helptext"):
                    st.html(_stg_card_head(
                        _stg_i_help, "Show help text",
                        "Keeps the Help buttons and the short explanations under "
                        "the main action buttons.",
                        tip="Turn it off for a cleaner screen once you know your way "
                            "around. Warnings, errors, empty states and anything you "
                            "need in order to make a choice always stay - only the "
                            "onboarding copy is hidden."))
                    temp_help_text = st.toggle("Show help text", value=st.session_state.get('show_help_text', True), key="temp_show_help_text")

            # ── PANOPTO TRANSCRIPTION ─────────────────────────────────
            # The transcription engine (model / language / compute device) is a
            # GLOBAL, persisted config - per-download output formats live in
            # Section 4 of the download settings, not here. Exposing the engine
            # dialog from Settings lets users configure it without first starting
            # a download or sync. Streamlit forbids nested dialogs, so the button
            # closes Settings, opens the transcription dialog (hosted in app.py),
            # and returns here when done (_pan_return_to_settings).
            st.html(_stg_section("PANOPTO LECTURE RECORDINGS"))

            from shared.helpers import esc

            # ── Global Panopto on/off ─────────────────────────────────
            # The master switch, and the permanent answer to "stop asking me".
            # Off means: no institution lookup, no discovery, no acceptable-use
            # dialog, and no recordings in any download or sync. It exists for
            # two independent reasons that happen to share one control:
            #   * the user simply does not want lecture recordings, and
            #   * their university may not use Panopto at all - in which case
            #     every run currently pays for an LTI handshake per external
            #     tool in every course (measured: 48 across one real account,
            #     ~1-2s each) that can only ever return nothing.
            # Auto-detection (panopto/institution.py) fixes the second case
            # without anyone touching this switch; the switch is what makes it
            # a choice rather than a diagnosis.
            _pan_on = st.session_state.get('panopto_globally_enabled')
            if _pan_on is None:
                from panopto.settings import is_globally_enabled
                _pan_on = is_globally_enabled()

            # Status line ONLY when the scan is already cached. Never trigger a
            # lookup from here: this renders inside a dialog, and a ~230ms
            # network call on the render path would stall it for no benefit.
            _scan = st.session_state.get('_panopto_institution_scan')
            _pan_status = ""
            if _scan is not None and getattr(_scan, 'resolved', False):
                if getattr(_scan, 'has_panopto', False):
                    _pan_status = ('<div style="display:flex;align-items:center;gap:7px;margin-top:7px;'
                                   'font-size:0.78rem;color:#cbd5e1;"><span style="width:8px;height:8px;'
                                   'border-radius:50%;background:#22c55e;flex-shrink:0;"></span>'
                                   '<span>Your institution provides Panopto.</span></div>')
                else:
                    _pan_status = ('<div style="display:flex;align-items:center;gap:7px;margin-top:7px;'
                                   'font-size:0.78rem;color:#cbd5e1;"><span style="width:8px;height:8px;'
                                   'border-radius:50%;background:#8b949e;flex-shrink:0;"></span>'
                                   '<span>No Panopto integration found at your institution.</span></div>')

            try:
                from panopto.models import transcription_status as _tx_status
                _tx = _tx_status()
            except Exception:
                _tx = {"ready": False, "model_id": "small",
                       "reason": "the local transcription engine isn't available yet"}

            # The master switch is a single toggle and the engine card carries a
            # full-width button, so they are sized accordingly rather than each
            # being handed the whole dialog width for one control.
            _pn1, _pn2 = st.columns([1, 2])
            with _pn1:
                with st.container(border=True, key="stg_card_pan_enabled"):
                    st.html(_stg_card_head(
                        _stg_i_movie, "Panopto lecture recordings",
                        "Look for Panopto recordings in your courses and offer "
                        "them as downloads.",
                        tip="Turn this off if your university doesn't use Panopto, or "
                            "if you never want lecture recordings - the search is "
                            "skipped entirely, so downloads and syncs finish faster.",
                        extra=_pan_status))
                    temp_pan_enabled = st.toggle(
                        "Include Panopto recordings", value=bool(_pan_on),
                        key="temp_panopto_globally_enabled")
            # The engine is a SUBORDINATE of the master switch: with Panopto off
            # there are no recordings to transcribe, so the whole card goes
            # unavailable rather than sitting there fully lit offering to
            # configure something that can never run. Read off `temp_pan_enabled`
            # (the toggle above, already rendered this run) so it tracks the
            # switch immediately, not one save later.
            #
            # The state carries in THREE places at once, because any one of them
            # alone is a dead end: the status line says why, the tooltip says it
            # again on the control the user will actually reach for, and the
            # dimming makes it visible without reading anything.
            # ...WITH ONE EXCEPTION: the engine card is the ONLY route to the
            # model manager, which is the only place a downloaded Whisper model
            # or the CUDA libraries can be DELETED - and those run to multiple
            # GB. Making the card unavailable therefore stranded that disk space
            # with no way to reclaim it: the user had to switch Panopto back on,
            # delete, and switch it off again, which nobody discovers on their
            # own. So while something is actually installed the card stays
            # reachable and is relabelled as cleanup rather than setup; with
            # nothing installed there is nothing to manage and it dims as
            # before. "Subordinate" was always about not offering to configure
            # a feature that cannot run - never about trapping the user's disk.
            _pan_installed = bool(_tx.get("any_installed"))
            try:
                from panopto import cuda_provision as _cuda_prov
                _pan_installed = _pan_installed or bool(_cuda_prov.is_provisioned())
            except Exception:
                pass
            _pan_card_live = bool(temp_pan_enabled or _pan_installed)

            if not temp_pan_enabled and _pan_installed:
                _tx_dot = "#8b949e"
                _tx_txt = ("Panopto is switched off &middot; open to remove the "
                           "installed model or GPU libraries and reclaim the space")
            elif not temp_pan_enabled:
                _tx_dot = "#8b949e"
                _tx_txt = ("Panopto is switched off &middot; turn it on to view "
                           "and configure the engine")
            elif _tx.get("ready"):
                _tx_dot, _tx_txt = "#22c55e", (
                    f"Ready &middot; active model: <b>{esc(str(_tx.get('model_id', '')))}</b>")
            else:
                _tx_dot, _tx_txt = "#f59e0b", esc(
                    (_tx.get("reason") or "not set up yet").capitalize())

            with _pn2:
                # A distinct key while unavailable is what lets CSS find the card
                # - a container takes no attributes, and the dimming has to land
                # on the CARD (once) rather than on each control inside it.
                with st.container(border=True,
                                  key="stg_card_pan" if _pan_card_live else "stg_card_pan_off"):
                    st.html(_stg_card_head(
                        _stg_i_caption, "Panopto transcription engine",
                        "Configure the local model, language and compute device used "
                        "to transcribe Panopto recordings into <b>Transcripts</b> "
                        "&amp; <b>Subtitles</b>. These settings are shared across "
                        "every download and sync - nothing is uploaded.",
                        extra=f'<div style="display:flex;align-items:center;gap:7px;'
                              f'margin-top:7px;font-size:0.78rem;color:#cbd5e1;">'
                              f'<span style="width:8px;height:8px;border-radius:50%;'
                              f'background:{_tx_dot};flex-shrink:0;"></span>'
                              f'<span>{_tx_txt}</span></div>'))
                    if not temp_pan_enabled and _pan_installed:
                        _stg_pan_label = "Manage installed models"
                    elif _tx.get("ready"):
                        _stg_pan_label = "Manage transcription configuration"
                    else:
                        _stg_pan_label = "Configure transcription"
                    if st.button(_stg_pan_label, key="stg_btn_pan", use_container_width=True,
                                 disabled=not _pan_card_live,
                                 help=None if _pan_card_live else
                                      "Panopto lecture recordings are switched off. Turn "
                                      "them on in the card to the left to configure the "
                                      "transcription engine."):
                        st.session_state['_pan_dialog_open'] = True
                        st.session_state['_pan_return_to_settings'] = True
                        # Settings must close FIRST - Streamlit crashes with "only one
                        # dialog allowed open at a time" if both flags survive the
                        # rerun. panopto_page's close handler sets _stg_reopen_dialog
                        # to bring Settings back.
                        st.session_state.pop('_stg_dialog_open', None)
                        st.rerun(scope="app")

            # ── MACOS PERMISSIONS (Full Disk Access status card) ──────
            # PERMANENT card (its own section, own header) - never the
            # dismissible nudge: Settings is the durable home of the
            # hands-off story. Green status once granted, blue call-to-
            # action with the step-by-step guide until then. Renders
            # nothing on Windows / macOS ≤14. Interactions are rerun-safe
            # inside the dialog (plain button + toast).
            from shared.components import render_fda_settings_card
            render_fda_settings_card()

            # ── TROUBLESHOOTING ───────────────────────────────────────
            # The three artefacts you send with a bug report, together. The two
            # log toggles used to sit in the DOWNLOAD row purely because a run
            # is what writes them, which put a troubleshooting control in the
            # middle of the settings that decide which files you get; the health
            # record then got a section of its own for one card.
            #
            # The health record is the ONLY artefact for failures that leave
            # nothing behind (the app dying without running its exit path). It
            # deliberately lives HERE and nowhere else: it was briefly attached
            # to the completion screens' error-log dialog, which was wrong twice
            # over - that dialog answers "which files failed in the run I just
            # did", and a crash means nobody ever reaches a completion screen at
            # all. Settings is reachable at any time, including straight after a
            # crash, which is the one moment this matters.
            st.html(_stg_section("TROUBLESHOOTING"))

            _tb1, _tb2 = st.columns([1, 2])
            with _tb1:
                with st.container(border=True, key="stg_card_errlog"):
                    st.html(_stg_card_head(
                        _stg_i_errlog, "Error log file",
                        'Write a <code style="font-size:0.72rem;background:'
                        'rgba(255,255,255,0.08);padding:1px 4px;border-radius:3px;">'
                        'download_errors.txt</code> into the output folder, listing '
                        'any failed downloads or conversion errors.'))
                    temp_error_log = st.toggle("Create error log", value=st.session_state.get('error_log_enabled', False), key="temp_error_log_enabled")

                    # Second log of the same kind, at the same weight, directly
                    # under a divider. (The divider is drawn by the scoped
                    # border-top on st-key-temp_debug_mode in the dialog CSS, so
                    # it needs no element of its own - an extra st.html here
                    # would cost a flex gap slot and re-open the gap that made
                    # this row look marooned at the bottom of the card.)
                    temp_debug_mode = st.toggle(
                        "Save debug log",
                        value=st.session_state.get('debug_mode', False),
                        key="temp_debug_mode",
                        help="For troubleshooting only. Writes a detailed debug_log.txt to each output folder - not needed for normal use."
                    )
            with _tb2:
                with st.container(border=True, key="stg_card_diag"):
                    from core.health_log import health_log_path
                    _hl_path = health_log_path()
                    _hl_exists = False
                    try:
                        _hl_exists = bool(_hl_path) and os.path.exists(_hl_path)
                    except OSError:
                        _hl_exists = False

                    _hl_esc = esc(_hl_path or 'unavailable')
                    st.html(_stg_card_head(
                        _stg_i_health, "App health record",
                        "A short log of app startups, shutdowns and memory use, kept "
                        "automatically. If Canvas Downloader closes unexpectedly or "
                        "behaves oddly, send this file with your report. It contains "
                        "<b>no</b> personal data, access tokens, course names or file "
                        "names, and is never uploaded anywhere.",
                        extra=f'<div title="{_hl_esc}" style="margin-top:7px;'
                              f'font-size:0.72rem;color:rgba(255,255,255,0.45);'
                              f'font-family:monospace;white-space:nowrap;overflow:hidden;'
                              f'text-overflow:ellipsis;">{_hl_esc}</div>'))

                    # ONE action, and it is the one that helps. The card prints
                    # the file's own path directly above this button - a
                    # "Download record" next to it offered to copy a file the
                    # user already has, from their own disk, to their own disk.
                    # Revealing it in the file manager is the whole job: from
                    # there they can open it, or drag it into a bug report.
                    _reveal_label = ("Reveal in Finder" if sys.platform == "darwin"
                                     else "Show in Explorer")
                    if st.button(_reveal_label, key="stg_btn_diag_reveal",
                                 use_container_width=True, disabled=not _hl_exists,
                                 help=None if _hl_exists else
                                      "No health record has been written yet."):
                        from shared.helpers import reveal_in_folder
                        reveal_in_folder(_hl_path)

        # ── Sticky footer ─────────────────────────────────────────────
        st.html("""<div style="padding:6px 0 0 0;"><hr style="margin:0;border:none;border-top:1px solid rgba(255,255,255,0.08);"/></div><div style="padding:6px 0 0 0;"></div>""")

        c_cancel, c_save = st.columns([1, 1])
        with c_cancel:
            if st.button("Cancel", use_container_width=True):
                if _stg_has_unsaved_changes():
                    st.session_state['_stg_unsaved_toast'] = True
                st.session_state.pop('_temp_default_path', None)
                st.session_state.pop('_stg_dialog_open', None)
                st.rerun(scope="app")
        with c_save:
            # Keyed so the live audit can drive it. A dialog whose primary action
            # cannot be addressed by key is a dialog no automated run can get
            # past, which is why the settings path had no end-to-end coverage.
            if st.button("Save Settings", type="primary", use_container_width=True,
                         key="stg_btn_save"):
                new_default_path = st.session_state.get('_temp_default_path', '') or ''
                prev_default_path = st.session_state.get('default_download_path', '') or ''

                # Hard floor, server-side. `min_value=1` is enforced by the
                # widget, but the saved value is what the engine actually filters
                # on - clamping here means a hand-edited config or a future
                # widget change can never let a 0 MB (= skip everything) limit
                # through.
                temp_size_mb = max(1, int(temp_size_mb or 1))

                _changed = (
                    temp_max != st.session_state.get('concurrent_downloads', 5)
                    or temp_cbs != st.session_state.get('enable_cbs_filters', False)
                    or temp_size_enabled != st.session_state.get('max_file_size_enabled', False)
                    or int(temp_size_mb) != int(st.session_state.get('max_file_size_mb', 500))
                    or temp_arch_enabled != st.session_state.get('archive_max_files_enabled', False)
                    or int(temp_arch_files) != int(st.session_state.get('archive_max_files', 1000))
                    or temp_notifications != st.session_state.get('notifications_enabled', True)
                    or temp_error_log != st.session_state.get('error_log_enabled', False)
                    or temp_debug_mode != st.session_state.get('debug_mode', False)
                    or temp_time_12h != st.session_state.get('use_12h_format', False)
                    or new_default_path != prev_default_path
                    or int(temp_history_retention) != int(st.session_state.get('sync_history_retention', 50))
                    or temp_help_text != st.session_state.get('show_help_text', True)
                )

                st.session_state['concurrent_downloads'] = temp_max
                st.session_state['enable_cbs_filters'] = temp_cbs
                st.session_state['max_file_size_enabled'] = temp_size_enabled
                st.session_state['max_file_size_mb'] = int(temp_size_mb)
                st.session_state['archive_max_files_enabled'] = temp_arch_enabled
                st.session_state['archive_max_files'] = int(temp_arch_files)
                st.session_state['notifications_enabled'] = temp_notifications
                st.session_state['error_log_enabled'] = temp_error_log
                st.session_state['debug_mode'] = temp_debug_mode
                st.session_state['use_12h_format'] = temp_time_12h
                st.session_state['default_download_path'] = new_default_path
                st.session_state['sync_history_retention'] = int(temp_history_retention)
                st.session_state['show_help_text'] = bool(temp_help_text)
                st.session_state['panopto_globally_enabled'] = bool(temp_pan_enabled)

                from pathlib import Path as _Path
                _downloads_default = str(_Path.home() / "Downloads")
                live_path = st.session_state.get('download_path', '')
                if new_default_path and live_path in (prev_default_path, _downloads_default, ''):
                    st.session_state['download_path'] = new_default_path

                # Read-modify-write through the ONE helper that distinguishes
                # "the file is damaged" from "the file could not be read right
                # now". The old inline form degraded BOTH to {} and then wrote,
                # which discarded every key this handler does not set - the
                # Panopto engine block and the acknowledged legal notice
                # included. See read_config_for_update.
                config_data, _cfg_may_write = read_config_for_update()

                config_data['api_url'] = st.session_state.get('api_url', '')
                config_data.pop('api_token', None)
                config_data['concurrent_downloads'] = temp_max
                config_data['enable_cbs_filters'] = temp_cbs
                config_data['max_file_size_enabled'] = bool(temp_size_enabled)
                config_data['max_file_size_mb'] = int(temp_size_mb)
                config_data['archive_max_files_enabled'] = bool(temp_arch_enabled)
                config_data['archive_max_files'] = int(temp_arch_files)
                config_data['notifications_enabled'] = bool(temp_notifications)
                config_data['error_log_enabled'] = bool(temp_error_log)
                config_data['debug_mode'] = bool(temp_debug_mode)
                config_data['use_12h_format'] = bool(temp_time_12h)
                config_data['default_download_path'] = new_default_path
                config_data['sync_history_retention'] = int(temp_history_retention)
                config_data['show_help_text'] = bool(temp_help_text)
                # Written into the SAME atomic write as every other setting
                # rather than through panopto.settings.set_globally_enabled():
                # two writers racing on one file is how the other's keys get
                # lost. This handler is a read-modify-write of the whole config,
                # so panopto_notice_ack_version and the "panopto" engine block
                # survive untouched - which is exactly why it must not be
                # rewritten as a fresh dict.
                from panopto.settings import GLOBAL_ENABLED_KEY as _PAN_ENABLED_KEY
                config_data[_PAN_ENABLED_KEY] = bool(temp_pan_enabled)

                if not _cfg_may_write:
                    # The existing file is intact but unreadable right now, so
                    # writing would replace it with only the keys set above.
                    # Say so rather than reporting a save that discarded things.
                    from ui.amber_notice import render_error_notice
                    render_error_notice(
                        "Could not save settings: your settings file could not be "
                        "read just now, and saving would have discarded the "
                        "settings it holds. Please try again.")
                    st.session_state.pop('_temp_default_path', None)
                    st.session_state.pop('_stg_dialog_open', None)
                    st.rerun(scope="app")

                try:
                    _tmp_config = CONFIG_FILE + '.tmp'
                    with open(_tmp_config, 'w', encoding='utf-8') as f:
                        json.dump(config_data, f)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(_tmp_config, CONFIG_FILE)
                except Exception as e:
                    # Clean up orphaned temp file on failure
                    try:
                        if os.path.exists(_tmp_config):
                            os.unlink(_tmp_config)
                    except OSError:
                        pass
                    from ui.amber_notice import render_error_notice
                    render_error_notice(f"Could not save settings: {e}")

                st.session_state.pop('_temp_default_path', None)
                st.session_state.pop('_stg_dialog_open', None)
                if _changed:
                    st.session_state['_stg_saved_toast'] = True
                st.rerun(scope="app")

    user_name = st.session_state.get('user_name', '')
    display_user = user_name.replace("Logged in as:", "").replace("Logged in as", "").strip()

    # Single source of truth for "a run is active" - shared with the nav buttons
    # above (see is_operation_in_progress). Locks Settings + Logout during a run.
    from core.cancellation import is_operation_in_progress
    _is_executing = is_operation_in_progress()

    with st.container(border=False, key="sidebar_bottom_block"):
        # Settings button - also auto-reopens after native folder picker closes the dialog
        if st.button(
            "Settings",
            use_container_width=True,
            key="nav_btn_settings",
            disabled=_is_executing,
            help="Settings are unavailable while a download or sync is running" if _is_executing else None,
        ) and not _is_executing:
            st.session_state['_stg_dialog_open'] = True
        elif not _is_executing and st.session_state.pop('_stg_reopen_dialog', False):
            st.session_state['_stg_dialog_open'] = True

        # The dialog is NOT opened here - see open_pending_global_dialog(). The
        # freshly-built closure is published so the deferred opener at the end of
        # the script can invoke it. Session state (not a module global) because a
        # Streamlit server shares module globals across ALL user sessions.
        st.session_state['_stg_dialog_fn'] = _global_settings_dialog

        if st.session_state.pop('_stg_saved_toast', False):
            st.toast("✅ Settings saved")

        # Closing Settings discards staged edits, so the toast says what
        # happened rather than offering a "Save" that no longer has anything to
        # save (st.toast holds no widgets, and the values are gone by now).
        if st.session_state.pop('_stg_unsaved_toast', False):
            st.toast("⚠️ Some settings were changed, but not applied. Reopen, edit, and click 'save' to keep them.")

        # Update-available banner (renders only when a newer release exists).
        # Sits below the Settings section, above the user/logout section.
        try:
            from ui.update_banner import render_update_banner
            render_update_banner()
        except Exception:
            pass

        # Separator
        st.html("<hr style='margin: 8px 0 16px 0; border: none; border-bottom: 1px solid rgba(255,255,255,0.08);' />")

        # User info + logout - keyed container with absolute-positioned logout
        with st.container(border=False, key="user_info_row"):
            if display_user:
                first_name = display_user.split()[0] if display_user.split() else display_user
                safe_first_name = _he(first_name)
                # Calculate logout button left offset dynamically:
                # "Logged in as" at 0.75rem ≈ 65px, name at 0.9rem ≈ 8px/char
                name_px = len(first_name) * 8
                logged_in_px = 65  # "Logged in as" at 0.75rem is ~65px
                max_text_px = max(name_px, logged_in_px)
                logout_left = 20 + max_text_px + 5  # 20px pad + text + 5px gap
                st.html(f"""
<style>
section[data-testid="stSidebar"] div[class*="st-key-user_info_row"] div.st-key-nav_btn_logout {{
    left: {logout_left}px !important;
}}
</style>
<div style="line-height: 1.2; padding: 0 0 0 20px;">
    <div style="color: #9ca3af; font-size: 0.75rem; padding-bottom: 3px;">Logged in as</div>
    <div style="display: inline-block; color: #f3f4f6; font-size: 0.9rem; font-weight: 500; padding: 2px 6px; margin-top: 3px; margin-left: 0px;margin-bottom: 15px; background-color: rgba(255, 255, 255, 0.06); border-radius: 4px;">{safe_first_name}</div>
</div>""")
            # Logout is locked mid-run too: clearing the token + resetting state
            # would orphan the background worker and abandon the live progress.
            #
            # Unconditional for the same reason as the nav-lock block above, and
            # the `if _is_executing:` must not come back: every rule is scoped
            # to `button:disabled` and this button is disabled exactly when
            # executing, so the guard only ever moved the event container's
            # index boundaries around.
            st.html("""<style>
/* No `opacity`: global.css's single `button[disabled]` recipe paints this, and
   0.35 on top of brightness(0.5) left the glyph all but invisible. */
section[data-testid="stSidebar"] div.st-key-nav_btn_logout button:disabled {
cursor: not-allowed !important;
}
section[data-testid="stSidebar"] div.st-key-nav_btn_logout button:disabled:hover {
background-color: transparent !important;
}
section[data-testid="stSidebar"] div.st-key-nav_btn_logout button:disabled:hover::before {
filter: brightness(0) invert(0.65) !important;
}
section[data-testid="stSidebar"] div.st-key-nav_btn_logout button:disabled::after {
content: 'Unavailable while running' !important;
}
</style>""")
            if st.button('\u200b', use_container_width=False, key="nav_btn_logout", disabled=_is_executing) and not _is_executing:
                try:
                    keyring_user = st.session_state.get('api_url', '') or 'default'
                    _safe_keyring_delete(KEYRING_SERVICE, keyring_user)
                    _delete_fallback_token(keyring_user)
                except Exception:
                    pass

                st.session_state['is_authenticated'] = False
                st.session_state['api_token'] = ""
                st.session_state['token_loaded'] = False
                st.session_state['user_name'] = ''
                # Same reason as force_reauth: the credential this verdict was
                # about no longer exists, and a stale one would suppress the
                # next genuine unlock for the rest of the process.
                reset_keychain_unlock()
                st.session_state.pop('keychain_unlock_pending', None)
                st.session_state.pop('keychain_unlock_failed', None)
                st.session_state['step'] = 1
                st.session_state['current_mode'] = 'download'
                # Re-arm the course selector's cold-boot spinner - the next
                # login's fetch is a genuine first load.
                st.session_state.pop('_dl_courses_loaded_once', None)
                fetch_courses_fn.clear()
                if os.path.exists(CONFIG_FILE):
                    try:
                        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                            config_data = _migrate_config(json.load(f))
                        # (api_token / mac_api_token are in RETIRED_CONFIG_KEYS,
                        #  so _migrate_config has already removed them.)
                        tmp_path = CONFIG_FILE + '.tmp'
                        with open(tmp_path, 'w', encoding='utf-8') as f:
                            json.dump(config_data, f)
                            f.flush()
                            os.fsync(f.fileno())
                        os.replace(tmp_path, CONFIG_FILE)
                    except Exception as e:
                        logger.warning(f"Could not update config on logout: {e}")
                st.rerun()

        # Version and support badge
        st.html(
            f"<style>"
            f".kofi-tag {{"
            f"    display: inline-flex; align-items: center; gap: 6px; color:#9ca3af; font-size:0.75rem; font-weight:500; text-decoration:none;"
            f"    background-color: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px;"
            f"    padding: 4px 10px; align-self: flex-start; transition: all 0.2s ease-in-out;"
            f"}}"
            f".kofi-tag:hover {{"
            f"    color: #ffffff !important;"
            f"    background-color: rgba(255,255,255,0.08) !important;"
            f"    border-color: rgba(255,255,255,0.2) !important;"
            f"}}"
            f"</style>"
            f"<hr style='margin: 0px 0 0 0; border: none; border-bottom: 1px solid rgba(255,255,255,0.06);' />"
            f"<div style='display: flex; flex-direction: row; align-items: center; justify-content: flex-start; gap: 16px; padding: 15px 20px 0px 20px;'>"
            f"  <div style='color:#9ca3af; font-size:0.75rem; display: flex; align-items: center; line-height: 1;'>v{__version__}</div>"
            f"  <a href='https://ko-fi.com/brkbuilds' target='_blank' class='kofi-tag' style='margin: 0; align-self: center;'>"
            f"    <img src='data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgd2lkdGg9IjE0IiBmaWxsPSIjZjk3MzE2Ij48cGF0aCBkPSJNMTIgMjEuMzVsLTEuNDUtMS4zMkM1LjQgMTUuMzYgMiAxMi4yOCAyIDguNSAyIDUuNDIgNC40MiAzIDcuNSAzYzEuNzQgMCAzLjQxLjgxIDQuNSAyLjA5QzEzLjA5IDMuODEgMTQuNzYgMyAxNi41IDMgMTkuNTggMyAyMiA1LjQyIDIyIDguNWMwIDMuNzgtMy40IDYuODYtOC41NSAxMS41NEwxMiAyMS4zNXoiLz48L3N2Zz4=' width='14' height='14' alt='Heart' />"
            f"    Support the project"
            f"  </a>"
            f"</div>"
        )
