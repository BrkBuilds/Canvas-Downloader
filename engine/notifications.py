"""
engine.notifications — Cross-platform completion sound helper.

Plays a short, non-blocking system sound to signal that a long-running
download or sync has finished, so users who tabbed out can tell.

Call ``play_completion_beep()`` at the moment a download/sync transitions
to its terminal state. The sound call is dispatched on a daemon thread so
it never blocks the Streamlit script runner — even if the audio backend
stalls, the UI keeps ticking.
"""

from __future__ import annotations

import logging
import platform
import threading

logger = logging.getLogger(__name__)


def _play_windows():
    """Windows: Play the standard system notification sound instead of an error beep."""
    try:
        import winsound
        import os
        sound_path = r"C:\Windows\Media\Windows Notify System Generic.wav"
        if os.path.exists(sound_path):
            # SND_NODEFAULT prevents fallback to the default (error) beep if file is missing
            winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        else:
            # Safe fallback that plays a standard positive 'ding', not an error
            winsound.MessageBeep(winsound.MB_OK)
    except Exception as e:
        logger.debug(f"Windows completion beep failed: {e}")


def _play_macos():
    """macOS: afplay a stock system sound (Glass is a pleasant chime)."""
    try:
        import subprocess
        subprocess.Popen(
            ['afplay', '/System/Library/Sounds/Glass.aiff'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.debug(f"macOS completion beep failed: {e}")


def play_completion_beep() -> None:
    """Fire the native completion sound without blocking the caller.

    Safe to call from the main Streamlit thread or from async contexts.
    Any failure is logged at debug level — notifications are a polish
    feature and must never interrupt download/sync lifecycle.
    """
    system = platform.system()
    if system == 'Windows':
        worker = _play_windows
    elif system == 'Darwin':
        worker = _play_macos
    else:
        return  # Linux/other: silent (app is not shipped there)

    try:
        threading.Thread(target=worker, daemon=True).start()
    except Exception as e:
        logger.debug(f"Failed to dispatch completion beep thread: {e}")
