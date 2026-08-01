"""Acceptable-use acknowledgement for the Panopto lecture-download feature.

The app saves Panopto recordings by authenticating as the user (their own Canvas
token, the same LTI 1.3 handshake a browser performs) and reading the stream the
player itself is served. It breaks no encryption and escalates no permission -
but it also does **not** read Panopto's per-folder/per-recording "Downloads"
permission, so a recording whose download button the institution has switched
off is still saved. ``DISCLAIMER.md`` states that plainly, and this module is
what guarantees the user was told once, before the first such download.

Design notes:

* **Stored as a TOP-LEVEL key** in ``canvas_downloader_settings.json``, not
  inside ``panopto.settings.PANOPTO_DEFAULTS``. That dict is the schema for a
  per-run *contract*: ``save_settings`` sanitises to exactly its keys and
  ``compose_settings`` starts from ``dict(PANOPTO_DEFAULTS)``, so an
  acknowledgement stored there would be copied into every composed run config
  and persisted into every synced folder's manifest. It is a one-time global
  fact about the user, not a property of a download.
* **Versioned, not boolean.** Bumping ``PANOPTO_NOTICE_VERSION`` re-prompts
  everyone, which is the only way a material change to the terms can be made to
  reach existing users. A stored value that is absent, non-numeric or lower than
  the current version all mean "not acknowledged".
* **Fails CLOSED.** Any read error is treated as not-acknowledged: showing the
  notice twice is harmless, skipping it silently defeats the entire point.
* **A failed WRITE still lets the run proceed.** The user has read and accepted
  the notice; refusing to download because a settings file is read-only would
  punish them for it. The only cost is being asked again next launch.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: Bump this when the acceptable-use terms change materially. Every user is then
#: shown the notice once more, and must accept it again before the next Panopto
#: download. A cosmetic wording fix is NOT a reason to bump it.
PANOPTO_NOTICE_VERSION = 1

#: Top-level key in canvas_downloader_settings.json. See the module docstring
#: for why this does not live under the "panopto" key.
ACK_KEY = "panopto_notice_ack_version"

#: Published copy of DISCLAIMER.md. Defined here rather than in the dialog so the
#: modal and the card's permanent note cannot drift onto different URLs.
DISCLAIMER_URL = (
    "https://birkls.github.io/Canvas_LMS_batch_file_downloader/disclaimer.html"
)

#: Session-state key holding the open/closed state of the modal, and the key
#: recording a positive acknowledgement for the rest of this session (so the
#: guard does not re-read the settings file on every rerun).
NOTICE_OPEN_KEY = "_panopto_notice_open"
_SESSION_ACK_KEY = "_panopto_notice_ack_ok"

#: Session-state assignments to apply when the user answers the notice, so the
#: action they clicked actually happens instead of being swallowed by the modal.
#: Deliberately PLAIN DATA (a dict of session-state keys), never a stored
#: callable: the sync path's action is "open the confirm dialog", and invoking
#: that from inside this dialog would nest two modals, which Streamlit refuses
#: outright. A dict is applied by whoever is in a position to act on it.
RESUME_KEY = "_panopto_resume"

#: Set when the notice has been answered and its resume is waiting to fire. The
#: resume is NOT applied in the same run that closes the dialog, and that delay
#: is the whole point - see :func:`arm_resume`.
RESUME_PENDING_KEY = "_panopto_resume_pending"

#: Set when the user declined the notice for THIS run. Run-scoped on purpose: a
#: folder's stored panopto_contract is a configuration, and one run's decline
#: must not silently rewrite it. The global Settings toggle is the durable "no".
SKIP_RUN_KEY = "_panopto_skip_this_run"



def _config_path() -> Path:
    """Resolve the shared settings JSON path (lazy import of get_config_dir)."""
    from shared.helpers import get_config_dir
    return Path(get_config_dir()) / "canvas_downloader_settings.json"


def _read_full_config() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"Could not read settings file for the Panopto notice: {e}")
        return {}


def stored_ack_version() -> int:
    """Return the acknowledged notice version, or 0 when there is none.

    A missing file, unreadable JSON, or a non-numeric stored value all yield 0
    (see "fails closed" in the module docstring).
    """
    raw = _read_full_config().get(ACK_KEY)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def panopto_notice_acknowledged() -> bool:
    """True when this machine has accepted the CURRENT notice version."""
    return stored_ack_version() >= PANOPTO_NOTICE_VERSION


def record_panopto_acknowledgement() -> bool:
    """Persist acceptance of the current notice version. Returns True on success.

    Atomic read-modify-write (temp file + ``os.replace``) so the other top-level
    keys written by the Settings dialog and the ``"panopto"`` block written by
    ``panopto.settings`` are never clobbered.
    """
    full = _read_full_config()
    full[ACK_KEY] = PANOPTO_NOTICE_VERSION

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
        logger.warning(f"Could not save the Panopto notice acknowledgement: {e}")
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        return False


# ── Is the Panopto feature live for this user at all? ────────────────────────

#: Session cache for the institution scan. Only RESOLVED scans are stored, so a
#: transient network failure retries on the next call instead of freezing an
#: "unknown" answer for the whole session.
_SESSION_SCAN_KEY = "_panopto_institution_scan"


def _any_course_id():
    """Any course id this session knows about, or None.

    The institution's external-tool list is identical for every course (the
    Panopto install is account-level, ``context: null``), so which one we use is
    irrelevant - we only need one to get past Canvas's 403 on the account-level
    endpoint. Several session keys are tried because the id is needed from
    screens that populate different ones; finding none simply leaves the scan
    unresolved, which fails open.
    """
    import streamlit as st

    for key in ("all_courses", "courses", "courses_to_download"):
        for c in (st.session_state.get(key) or []):
            cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
            if cid:
                return cid
    # Sync/Today screens never populate the course-list keys above - they work
    # from PAIRS. Without this the scan stays unresolved there, which fails open
    # and shows the Today opt-in card even at a university with no Panopto at
    # all: a card offering a feature that cannot exist.
    for key in ("sync_pairs", "today_pairs"):
        for p in (st.session_state.get(key) or []):
            cid = p.get("course_id") if isinstance(p, dict) else None
            if cid:
                return cid
    try:
        from core.auto_sync import resolve_today_pairs
        for p in resolve_today_pairs():
            if p.get("course_id"):
                return p["course_id"]
    except Exception as e:
        logger.debug("Panopto scan: no course id from the daily list (%s)", e)
    return None


def institution_scan():
    """The institution's :class:`panopto.institution.ToolScan`. Never raises.

    Delegates to ``panopto.institution.cached_scan`` rather than keeping its own
    copy. An earlier version cached here in session state AND there in a module
    dict - two caches for one fact, which meant up to two network lookups and,
    worse, a window where the UI and the discovery engine could disagree about
    whether the institution has Panopto. ``cached_scan`` is the single memo; the
    session key below only remembers that we already asked, so a screen with no
    course id in reach does not retry on every rerun.
    """
    import streamlit as st
    from panopto.institution import ToolScan, cached_scan

    token = st.session_state.get("api_token")
    base = st.session_state.get("api_url")
    if not (token and base):
        return ToolScan()

    course_id = _any_course_id()
    if not course_id:
        return ToolScan()

    try:
        from panopto.discovery import _CanvasREST
        scan = cached_scan(_CanvasREST(base, token), course_id)
    except Exception as e:
        logger.debug("Panopto institution scan unavailable: %s", e)
        return ToolScan()

    if scan.resolved and not st.session_state.get(_SESSION_SCAN_KEY):
        st.session_state[_SESSION_SCAN_KEY] = True
        logger.info(
            "Panopto availability: institution %s Panopto (%d tool(s) listed).",
            "HAS" if scan.has_panopto else "does NOT have",
            len(scan.known_tool_ids),
        )
    return scan


def panopto_feature_available() -> bool:
    """False when Panopto cannot or must not run for this user.

    Two independent reasons, checked cheapest-first:

    1. The user switched Panopto off globally in Settings.
    2. The institution has no Panopto LTI tool at all - measured as one ~230ms
       call per session, versus the dozens of LTI handshakes a discovery pass
       costs at a university that does not even use Panopto.

    Unknown counts as AVAILABLE (see ``ToolScan.should_skip_panopto``): a
    network blip must never silently remove a feature the user configured.
    """
    from panopto.settings import is_globally_enabled

    if not is_globally_enabled():
        return False
    return not institution_scan().should_skip_panopto()


# ── The guard ────────────────────────────────────────────────────────────────

def require_panopto_notice(resume: dict | None = None) -> bool:
    """Gate any action that will download Panopto recordings.

    Returns ``True`` when the run may proceed. Otherwise it flags the modal to
    open and returns ``False``; the CALLER must then do nothing else (no status
    change, no ``st.rerun()``), so the current render falls through to the
    dialog host at the bottom of ``app.py``.

    Callers are every path by which a recording can be fetched:

    * starting a Custom Download whose contract includes Panopto,
    * starting a Quick Download preset that includes Panopto (three of the five
      do, and that path never opens the settings card - the reason the guard
      cannot live on the card alone),
    * confirming a review sync, or a Quick Sync, whose contract includes it.

    Args:
        resume: session-state assignments that carry out the action the user
            clicked. Without it the click is simply SWALLOWED by the modal:
            answering the notice would close it and leave the user staring at
            the same screen, having to click the button a second time. Whoever
            answers the dialog applies this dict, so the download the user asked
            for starts whether they accepted or declined.

    The positive result is memoised in session state: re-reading the settings
    file on every rerun would be pointless disk I/O for a fact that cannot
    change mid-session without going through :func:`accept_panopto_notice`.
    """
    import streamlit as st

    # Nothing to consent to when no recording can be fetched: the user switched
    # Panopto off, or their institution has no Panopto tool at all. Asking there
    # is a dialog about a thing that cannot happen - and at a non-Panopto
    # university it would be the ONLY time Panopto is ever mentioned.
    if not panopto_feature_available():
        # Logged because this is the single most likely thing to explain a
        # "why didn't it download my lectures?" report, and it is otherwise
        # completely invisible - no dialog, no message, nothing on screen.
        from panopto.settings import is_globally_enabled
        logger.info(
            "Panopto skipped: %s.",
            "turned off in Settings" if not is_globally_enabled()
            else "this institution has no Panopto integration",
        )
        return True

    # Already declined for the run now being started. Proceeding is correct:
    # the answer was "go ahead, without recordings", and re-asking would make
    # the decline unreachable - every retry would re-open the same modal.
    if st.session_state.get(SKIP_RUN_KEY):
        return True

    if st.session_state.get(_SESSION_ACK_KEY):
        return True
    if panopto_notice_acknowledged():
        st.session_state[_SESSION_ACK_KEY] = True
        return True
    st.session_state[NOTICE_OPEN_KEY] = True
    if resume:
        st.session_state[RESUME_KEY] = dict(resume)
    return False


def panopto_skipped_this_run() -> bool:
    """True when the user declined the notice for the run now starting."""
    import streamlit as st

    return bool(st.session_state.get(SKIP_RUN_KEY))


def clear_panopto_skip() -> None:
    """Drop the run-scoped decline. Called when a fresh run is configured."""
    import streamlit as st

    st.session_state.pop(SKIP_RUN_KEY, None)


def arm_resume() -> None:
    """Mark the interrupted action ready to fire on a LATER run, not this one.

    Applying it immediately is what produced the reported bug. The transition it
    performs (``step = 3``) sends the very next run into
    ``asyncio.run(download_course_async(...))`` at ``app.py:1359``, which blocks
    for the whole download - and the dialog host sits at ``app.py:2586``, over a
    thousand lines further down. The run therefore never reaches the host, and
    Streamlit only drops elements a completed run stopped producing
    (``clearStaleNodes``). The modal stayed painted on top of the running
    download, greyed by the stale fade because it had been marked stale but
    never removed. Measured symptom: "the dialog was there for 5-7 seconds while
    the download ran behind it".

    So one run must COMPLETE with the dialog gone before the blocking one
    starts. That is what ``ui.panopto_notice.render_pending_resume`` does, and
    it is the same two-step the sync flow already uses for the same reason
    (``sync_ui._advance_to_sync``'s "inline call during the teardown run").
    """
    import streamlit as st

    if RESUME_KEY in st.session_state:
        st.session_state[RESUME_PENDING_KEY] = True


def resume_is_pending() -> bool:
    """True while an answered notice still owes the user their action."""
    import streamlit as st

    return bool(st.session_state.get(RESUME_PENDING_KEY))


def apply_pending_resume() -> None:
    """Carry out the interrupted action. Called only once the dialog is gone."""
    import streamlit as st

    st.session_state.pop(RESUME_PENDING_KEY, None)
    resume = st.session_state.pop(RESUME_KEY, None)
    if isinstance(resume, dict):
        for k, v in resume.items():
            st.session_state[k] = v


def accept_panopto_notice() -> None:
    """Record acceptance and close the modal.

    The session flag is set even when the disk write fails, so a read-only
    config dir costs the user a repeat prompt next launch rather than blocking
    the download they just consented to.
    """
    import streamlit as st

    record_panopto_acknowledgement()
    st.session_state[_SESSION_ACK_KEY] = True
    logger.info("Panopto acceptable-use notice ACCEPTED (version %d).",
                PANOPTO_NOTICE_VERSION)
    st.session_state.pop(NOTICE_OPEN_KEY, None)
    st.session_state.pop(SKIP_RUN_KEY, None)
    arm_resume()


def skip_panopto_and_continue() -> None:
    """Decline the notice, and let the run the user asked for START ANYWAY.

    This is the escape hatch, and it is what makes the notice a genuine choice
    rather than a wall. Three of the five Quick Download presets include
    recordings and that page exposes no per-output toggles, so before this
    existed a user who wanted "Complete Canvas Download" without lecture
    recordings had no route at all: accept, or pick a narrower preset.

    Run-scoped by design. The folder's stored ``panopto_contract`` is untouched,
    so the next sync asks again - remembering a decline would silently omit
    recordings from a later run the user did want, and silent omission is the
    failure this whole feature exists to prevent. The Settings toggle is the
    durable "no".

    Consent is NOT recorded here: someone who declines every time is asked every
    time, which is correct, because they never agreed to anything.
    """
    import streamlit as st

    st.session_state[SKIP_RUN_KEY] = True
    st.session_state.pop(NOTICE_OPEN_KEY, None)
    logger.info("Panopto acceptable-use notice DECLINED - this run continues "
                "without lecture recordings.")

    # Actually strip Panopto from the run, here, centrally. The download engine
    # builds its contract from the persistent_pan_* keys, so zeroing them IS the
    # mechanism - setting a flag and hoping something downstream honours it is
    # how "skip" would quietly still download 4 GB of lectures. Only the
    # per-run copies are touched; the user's card selections (pan_out_*) and any
    # folder's stored panopto_contract are configuration and stay untouched.
    from core.state_registry import PANOPTO_OUTPUT_KEYS
    for _k in PANOPTO_OUTPUT_KEYS:
        st.session_state[f"persistent_{_k}"] = False

    arm_resume()


def dismiss_panopto_notice() -> None:
    """Close the modal without answering it (Escape / click-outside).

    Distinct from :func:`skip_panopto_and_continue`: dismissing is "I did not
    answer", so the interrupted action is DROPPED rather than resumed. The
    resume payload is discarded with it, otherwise a stale one would fire the
    next time the notice appeared from somewhere else entirely.
    """
    import streamlit as st

    st.session_state.pop(NOTICE_OPEN_KEY, None)
    st.session_state.pop(RESUME_KEY, None)
