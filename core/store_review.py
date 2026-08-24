"""core.store_review - when (and whether) to ask for a Microsoft Store rating.

THE ASK IS MSIX-ONLY. There is nothing to rate on the macOS .dmg or on the Inno
.exe build, so the gate is ``shared.helpers.is_msix_package()`` - which asks
Windows for package identity rather than guessing from a path. See that function
for why the older ``"WindowsApps" in sys.executable`` heuristic is not reused.

--------------------------------------------------------------------------------
"ALREADY RATED" IS UNKNOWABLE, SO THE CLICK IS THE TERMINAL STATE
--------------------------------------------------------------------------------
There is no API that answers "has this user reviewed this app". ``StoreContext``
exposes licences and collections, not reviews, and the ``ms-windows-store://``
deep link is fire-and-forget - it hands the user to the Store app and tells us
nothing about what they did there.

So *pressing the button* is what we record, not *leaving a review*. Anyone who
engages at all is spent, whether or not they followed through. That is the only
implementable reading of "do not ask someone who has already rated it", and it
is also the polite one: the failure mode is asking a would-be reviewer one time
fewer, never nagging someone who already did us the favour.

--------------------------------------------------------------------------------
WHY THE DEEP LINK AND NOT THE NATIVE PROMPT
--------------------------------------------------------------------------------
``StoreContext.RequestRateAndReviewAppAsync()`` is the real in-app modal, and it
was declined deliberately: it needs WinRT bindings in the bundle plus
``IInitializeWithWindow`` against the pywebview HWND, i.e. a new dependency and
COM interop, to put a XAML island inside a Python/Streamlit/WebView2 process.
The bundle-size section of CLAUDE.md is a standing pressure and this is one
prompt. ``os.startfile(ms-windows-store://review?ProductId=...)`` costs nothing
and opens the Store directly on the review pane.

--------------------------------------------------------------------------------
THE GATE
--------------------------------------------------------------------------------
Every condition below has to hold. They exist to make the ask rare and to make
it land at a moment the user is pleased, because an ask that arrives at a bad
moment costs a daily user, which is worth far more than a review.

* **MSIX** (caller's job - see above).
* **The run that just finished was CLEAN** (caller's job). Asking for five stars
  on the screen that just said "Completed with Errors" is the single worst thing
  this feature could do. "Clean" is the app's own definition - zero *retriable*
  errors - because a teacher-locked file and an LTI stream are not failures and
  the completion card already refuses to count them as such.
* **Three distinct days on which a clean run completed** (:data:`REQUIRED_RUN_DAYS`).
  Days rather than runs, deliberately: three runs in one evening is somebody
  trying the app out, three runs on three days is a habit. It is also
  idempotent by construction - recording today twice is a no-op - which matters
  because a completion screen re-renders on every rerun and a naive counter
  would burn the whole allowance on one screen.
* **Not snoozed** (:data:`SNOOZE_DAYS`, 7). It is a FLOOR, not a schedule:
  the card also needs a clean run on a later day to come back at all, so
  the copy says "at least a week" rather than naming a date it cannot
  promise.
* **At most three asks, ever** (:data:`MAX_ASKS`). This is the promise that makes
  the whole thing tolerable: the worst case for someone who ignores it
  completely is that they see it three times in the lifetime of the install.

``run_days`` stops growing once the threshold is met, so this module writes to
disk at most six times in an install's life (three days + three asks).
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: The Store listing this app is published under. The same id appears in the
#: website's install links (docs/index.html, docs/releases.html, README.md);
#: tests/test_store_review.py pins the two together so a re-listing cannot
#: leave the app pointing at a product the site no longer advertises.
STORE_PRODUCT_ID = "9n1dwwvrq5wc"

#: Opens the Store app directly on the listing's review pane.
#:
#: NOTE THE SLASH before the query, and do not "simplify" it away.
#:
#: MEASURED on Windows 11 Pro 26200 against the live Store app, 2026-08-24:
#: BOTH ``review?ProductId=`` and ``review/?ProductId=`` open the review dialog
#: over this app's listing. They are interchangeable today - so this is not a
#: bug fix, and anyone finding the slash odd should know it was tested rather
#: than assumed.
#:
#: The documented form is kept because it is the one Microsoft publishes for
#: every verb of this scheme (``pdp/?``, ``review/?``, ``navigate/?``), which is
#: the form most likely to survive a Store update. Two equally-working options,
#: so the tie goes to the contract.
#:
#: What makes this worth a comment at all is the FAILURE MODE, which is the
#: worst available: a URI this handler does not recognise opens the Store on its
#: HOME page. The user sees the app launch something, the click is recorded as a
#: rating, and nothing anywhere reports an error. There is no return value to
#: check - ``os.startfile`` succeeds either way - so a wrong URI here can only
#: ever be caught by a human clicking the button and looking at what opens.
STORE_REVIEW_URI = f"ms-windows-store://review/?ProductId={STORE_PRODUCT_ID}"

#: Top-level key in the co-owned settings file (beside panopto_globally_enabled
#: and transcription_setup_notice_dismissed).
STATE_KEY = "store_review"

REQUIRED_RUN_DAYS = 3
SNOOZE_DAYS = 7
MAX_ASKS = 3

_DEFAULT: dict = {"rated": False, "asks": 0, "snoozed_until": "", "run_days": []}


# ── The co-owned settings file ──────────────────────────────────────────────
# Same shape as panopto.settings and shared.legal: a thin wrapper over the ONE
# shared reader, plus a private atomic write. The read stays inline in each
# writer on purpose - that is the half tests/test_settings_coownership.py
# asserts per writer, and folding it away would make that census stop
# measuring anything.

def _config_path() -> Path:
    from shared.helpers import get_config_dir
    return Path(get_config_dir()) / "canvas_downloader_settings.json"


def _read_full_config_for_update() -> tuple[dict, bool]:
    """``(config, may_write)`` for a read-modify-write of the settings file.

    See :func:`shared.helpers.read_json_for_update` for why the verdict is split
    by cause rather than collapsed to a dict: degrading an unreadable file to
    ``{}`` and writing anyway is what destroyed every other module's settings
    before that primitive existed.
    """
    from shared.helpers import read_json_for_update
    return read_json_for_update(_config_path())


def _atomic_write_config(full: dict, what: str) -> bool:
    """Write the WHOLE settings dict back atomically. Returns True on success."""
    path = _config_path()
    tmp = str(path) + ".tmp"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(full, f, indent=2, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
        return True
    except Exception as e:
        logger.warning(f"Could not save {what}: {e}")
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        return False


def _coerce(raw) -> dict:
    """A total read of the stored block: any shape in, a usable state out.

    This runs on a render path, so a hand-edited or half-written settings file
    must degrade to "ask nobody" rather than raise into the completion screen.
    Unknown types fall back to the default for that field, and ``rated`` /
    ``asks`` are the two that matter: getting either wrong in the permissive
    direction re-opens an ask the user already answered.
    """
    state = dict(_DEFAULT)
    state["run_days"] = []
    if not isinstance(raw, dict):
        return state
    state["rated"] = bool(raw.get("rated", False))
    try:
        state["asks"] = max(0, int(raw.get("asks", 0)))
    except (TypeError, ValueError):
        state["asks"] = MAX_ASKS  # unreadable = assume spent, never = assume fresh
    su = raw.get("snoozed_until", "")
    state["snoozed_until"] = su if isinstance(su, str) else ""
    days = raw.get("run_days", [])
    if isinstance(days, list):
        state["run_days"] = [d for d in days if isinstance(d, str)][:REQUIRED_RUN_DAYS]
    return state


def load_state() -> dict:
    """The stored ask-state, or its defaults. Never raises."""
    try:
        full, _ = _read_full_config_for_update()
        return _coerce(full.get(STATE_KEY))
    except Exception:
        return _coerce(None)


def _save_state(state: dict, what: str) -> bool:
    full, may_write = _read_full_config_for_update()
    if not may_write:
        logger.warning(
            "Not saving %s: the settings file could not be read, so a write "
            "would discard the rest of it.", what)
        return False
    full[STATE_KEY] = state
    return _atomic_write_config(full, what)


# ── The decision ────────────────────────────────────────────────────────────

def _today() -> str:
    return _dt.date.today().isoformat()


def should_ask(state: dict | None = None, *, today: str | None = None) -> bool:
    """True when the rating card may be shown *right now*.

    Deliberately does NOT check packaging or run cleanliness - those are the
    caller's, because only the completion screen knows whether this run was
    clean, and keeping them out here is what makes this function testable
    without a Windows box. :func:`shared.components.render_store_review_card`
    is the one place all the conditions meet.
    """
    st = load_state() if state is None else state
    today = today or _today()
    if st.get("rated"):
        return False
    if int(st.get("asks", 0)) >= MAX_ASKS:
        return False
    if len(st.get("run_days", [])) < REQUIRED_RUN_DAYS:
        return False
    snoozed = st.get("snoozed_until") or ""
    # A malformed date sorts however it sorts; ISO strings compare correctly and
    # anything else is treated as "still snoozed", which is the quiet direction.
    if snoozed and snoozed > today:
        return False
    return True


def asks_remaining(state: dict | None = None) -> int:
    st = load_state() if state is None else state
    if st.get("rated"):
        return 0
    return max(0, MAX_ASKS - int(st.get("asks", 0)))


# ── The three writes ────────────────────────────────────────────────────────

def note_clean_run(today: str | None = None) -> bool:
    """Record that a clean run finished today. Idempotent within a day.

    Returns True when something was written. Stops recording once the threshold
    is met - nothing downstream asks "how many days" beyond that - so the whole
    feature costs at most three writes here, ever.
    """
    today = today or _today()
    state = load_state()
    days = state.get("run_days", [])
    if len(days) >= REQUIRED_RUN_DAYS or today in days:
        return False
    state["run_days"] = days + [today]
    return _save_state(state, "the Store-review run history")


def note_ask(today: str | None = None) -> bool:
    """Count one ask and start the snooze. Called when the card is SHOWN.

    Charged on display rather than on a click, because the alternative - only
    counting an answered ask - means a user who simply ignores the card meets it
    on every clean completion screen for ever, which is precisely the nagging
    this design exists to avoid.
    """
    today = today or _today()
    state = load_state()
    state["asks"] = int(state.get("asks", 0)) + 1
    until = _dt.date.fromisoformat(today) + _dt.timedelta(days=SNOOZE_DAYS)
    state["snoozed_until"] = until.isoformat()
    return _save_state(state, "the Store-review ask count")


def note_rated() -> bool:
    """Terminal. The user pressed the button; never ask again.

    Records the *press*, not a review - see the module docstring.
    """
    state = load_state()
    state["rated"] = True
    return _save_state(state, "the Store-review outcome")


# ── The action ──────────────────────────────────────────────────────────────

def open_store_review_page() -> bool:
    """Open the Store app on this product's review pane. Never raises.

    ``os.startfile`` is the Windows shell verb; the ``ms-windows-store:`` scheme
    is registered by the Store app itself. Returns False when the shell refused,
    which the caller reports rather than silently swallowing - a button that
    appears to do nothing is worse than an honest failure.
    """
    try:
        os.startfile(STORE_REVIEW_URI)  # noqa: S606 - fixed, module-level constant
        return True
    except Exception as e:
        logger.warning("Could not open the Store review page: %s", e)
        return False
