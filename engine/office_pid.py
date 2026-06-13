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


def find_new_office_pid(exe_name: str, pre_pids: set) -> int | None:
    """Return the PID of the Office process that appeared after *pre_pids* was taken.

    Polls for up to ~1 second in 50 ms increments so the process has time to
    appear in the process table after ``DispatchEx`` returns.  Returns ``None``
    if no new process is found - callers must fall back to ``/IM`` kill in that
    case.
    """
    import time as _t
    try:
        import psutil
        upper = exe_name.upper()
        for _ in range(20):
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    if (p.info['name'] or '').upper() == upper and p.pid not in pre_pids:
                        return p.pid
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            _t.sleep(0.05)
    except Exception:
        pass
    return None


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
