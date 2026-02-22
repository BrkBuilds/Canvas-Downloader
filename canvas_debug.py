import os
from datetime import datetime
from pathlib import Path

DEFAULT_DEBUG_FILE = "debug_log.txt"

def log_debug(message, debug_file=None):
    """Writes a message to the debug log if enabled."""
    if not debug_file:
        return

    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        with open(debug_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"Debug logging failed: {e}")

def clear_debug_log(debug_file=None):
    """Clears the debug log at the start of a run."""
    if not debug_file:
        return
    try:
        with open(debug_file, "w", encoding="utf-8") as f:
            f.write(f"--- Debug Log Started: {datetime.now()} ---\n")
    except:
        pass
