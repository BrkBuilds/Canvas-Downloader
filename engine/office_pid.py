"""
Utilities for tracking and killing a specific Office COM process by PID.

Motivation: the legacy `taskkill /F /IM EXCEL.EXE` approach kills EVERY running
Excel instance, including files the user had open. This module tracks the PID of
the COM instance we spawned so the watchdog timer can target it precisely.
"""
import subprocess
import logging

logger = logging.getLogger(__name__)


def snapshot_office_pids(exe_name: str) -> set:
    """Return the set of PIDs currently running under *exe_name* (case-insensitive)."""
    try:
        import psutil
        upper = exe_name.upper()
        return {p.pid for p in psutil.process_iter(['pid', 'name'])
                if (p.info['name'] or '').upper() == upper}
    except Exception:
        return set()


#: Windows marks a COM-activated Office process on its command line. Measured
#: twice on real Windows by the audit and recorded in the register:
#: ``EXCEL.EXE /automation -Embedding``, ParentProcessId = RPCSS - "COM-launched
#: and headless, NOT a user's own Excel window". A document the user opened by
#: double-clicking never carries it, which is exactly the distinction this
#: module needs and previously did not make.
_COM_ACTIVATION_MARKERS = ("-embedding", "/embedding")

#: After the first candidate appears, wait this long and look again before
#: deciding. A second COM instance racing ours would otherwise be missed
#: entirely, and "I saw one" would be mistaken for "there is one".
_ATTRIBUTION_SETTLE_SECONDS = 0.15


def _is_com_launched(proc) -> bool:
    """Was *proc* started by COM activation rather than by the user?

    Answers **False** when the command line cannot be read (``AccessDenied``, a
    process that exited mid-query). That is the safe direction: an unreadable
    process is simply not adopted, so the worst case is a leaked headless Office
    - roughly 175 MB - instead of a force-kill aimed at a process we cannot
    identify.
    """
    try:
        cmdline = " ".join(proc.cmdline() or ()).lower()
    except Exception:
        return False
    return any(marker in cmdline for marker in _COM_ACTIVATION_MARKERS)


def _new_com_pids(psutil, upper: str, pre_pids: set) -> set:
    """Every COM-launched process named *upper* that is not in *pre_pids*."""
    found = set()
    for p in psutil.process_iter(['pid', 'name']):
        try:
            if (p.info['name'] or '').upper() != upper or p.pid in pre_pids:
                continue
            if _is_com_launched(p):
                found.add(p.pid)
        except Exception:
            pass
    return found


def find_new_office_pid(exe_name: str, pre_pids: set) -> int | None:
    """PID of the Office process WE spawned, or ``None`` when it cannot be told.

    Polls for up to ~1 second in 50 ms increments so the process has time to
    appear in the process table after ``DispatchEx`` returns.

    THE RETURN VALUE DECIDES WHAT GETS FORCE-KILLED, so it must never be a
    guess. This used to return the FIRST process of that name that was not in
    the snapshot, with nothing checking it was ours. Measured on Windows
    2026-08-21 against ``Application.Hwnd`` -> ``GetWindowThreadProcessId`` as
    ground truth: two concurrent instances gave lane A ``guessed=2448
    TRUE=9816`` and lane B ``guessed=2448 TRUE=2448`` - so lane A held a PID
    belonging to lane B, and 9816 was tracked by nobody, which is the 5h54m
    orphan the register carries.

    **It was not only a harness problem.** Single process, no harness: the user
    opens their own workbook, the app dispatches, and the user's PID is
    returned. The 180 s watchdog then force-kills *their* unsaved document - the
    precise thing this module's own docstring says it exists to prevent. The
    window is small but reopens on every conversion batch: measured 0.506 s for
    Excel, 2.344 s for Word, 2.357 s for PowerPoint.

    Two rules close it, and the first is why the second is affordable:

    1. **Only a COM-ACTIVATED process can be ours** (``-Embedding``). A document
       the user opened themselves can no longer be adopted at all, which is the
       entire data-loss scenario.
    2. **More than one candidate is ambiguous, so answer ``None``.** Two
       COM-launched instances means a second automation client - in practice a
       second copy of this app, which ``start.py``'s lock prevents for ordinary
       users and the audit harness creates by design.

    Rule 1 is what keeps rule 2 cheap: for an ordinary single instance the
    candidate set is exactly one whether or not the user has Office open, so
    ``None`` does NOT become more common for them, and the ``/IM`` fallback in
    ``kill_office_pid`` is no more reachable than it was before. That decoupling
    is deliberate - it is what makes this shippable on its own.
    """
    import time as _t
    try:
        import psutil
    except Exception:
        return None

    upper = exe_name.upper()
    for _ in range(20):
        candidates = _new_com_pids(psutil, upper, pre_pids)
        if candidates:
            # Let a racing sibling show up before committing to an answer.
            _t.sleep(_ATTRIBUTION_SETTLE_SECONDS)
            candidates = _new_com_pids(psutil, upper, pre_pids)
            if len(candidates) == 1:
                return next(iter(candidates))
            logger.warning(
                "Cannot attribute a %s process to this run: %d COM-launched "
                "candidates appeared (%s). Not tracking a PID - a leaked "
                "headless instance is recoverable, force-killing the wrong "
                "process is not.",
                exe_name, len(candidates), sorted(candidates) or "none survived",
            )
            return None
        _t.sleep(0.05)
    return None


def pid_is_process(pid: int, exe_name: str) -> bool:
    """True iff *pid* is currently a live process named *exe_name*.

    Used to force-kill a leaked Office COM process SAFELY: it confirms the PID we
    tracked at init is still the Office exe we spawned before killing it, so a
    PID the OS may have recycled (after a clean Quit already exited the process)
    is never mistaken for our orphan and killed.
    """
    if not pid:
        return False
    try:
        import psutil
        return (psutil.Process(pid).name() or '').upper() == exe_name.upper()
    except Exception:
        return False


def kill_office_pid(pid: int, exe_name_fallback: str) -> None:
    """Kill the Office process with *pid*.

    If *pid* is 0 / None, falls back to ``taskkill /F /IM exe_name_fallback``
    (which kills all instances - acceptable as a last resort when PID tracking
    failed, but avoids it when we have a precise target).
    """
    if pid:
        try:
            subprocess.run(
                ['taskkill', '/F', '/PID', str(pid)],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return
        except Exception as e:
            logger.warning(f"PID kill failed for PID {pid}: {e}. Falling back to /IM kill.")

    # Fallback: broad kill by image name
    logger.warning(
        f"Killing all {exe_name_fallback} processes (PID unknown). "
        "Any unsaved work in other open documents may be lost."
    )
    try:
        subprocess.run(
            ['taskkill', '/F', '/IM', exe_name_fallback],
            capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        # L-12: Signal that a broad /IM kill fired so the completion screen can
        # warn the user that other open Office documents may have been closed.
        try:
            import streamlit as _st
            _st.session_state['pp_force_kill_warning'] = True
        except Exception:
            pass
    except Exception:
        pass
