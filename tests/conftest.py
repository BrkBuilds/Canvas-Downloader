"""Shared test bootstrap for Canvas Downloader.

The project uses a flat layout (modules import each other by top-level name:
``import ui_helpers``, ``from core.today_store import ...``), so the repo root
must be on ``sys.path`` before any test module imports application code.

Run the suite from the repo root with:  python -m pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
