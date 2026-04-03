"""
Post-Processing Bridge — Unified post-processing invocation for Canvas Downloader.

Wraps UIBridge setup, ``run_all_conversions()`` execution, and sidecar
ledger injection into a single function used by both the standard download
and the isolated retry flows.

Usage:
    from engine.post_processing_bridge import invoke_post_processing

Design decisions:
    - Streamlit placeholders are passed explicitly via DashboardPlaceholders.
    - The ``is_cancelled`` lambda dynamically maps to the correct cancel state
      using ``core.cancellation``.
    - Sidecar paths are injected back into ``st.session_state['download_file_details']``
      to preserve the completion-screen file ledger.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Sequence

import streamlit as st

from core.cancellation import is_download_cancelled, is_sync_cancelled
from engine.progress_dashboard import DashboardPlaceholders

logger = logging.getLogger(__name__)

# Intentionally lazy-imported at call time to avoid circular imports:
#   from post_processing import run_all_conversions, UIBridge
#   from sync_manager import SyncManager


# ═══════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════

_CONVERT_KEYS = [
    'convert_zip', 'convert_pptx', 'convert_word', 'convert_excel',
    'convert_html', 'convert_code', 'convert_urls', 'convert_video',
]


# ═══════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════

def build_conversion_contract() -> dict:
    """Build the conversion contract from persisted session state keys.

    Returns a dict like ``{'convert_zip': True, ...}`` based on the
    ``persistent_*`` keys written at the start of Step 3.
    """
    return {k: st.session_state.get(f'persistent_{k}', False) for k in _CONVERT_KEYS}


def invoke_post_processing(
    *,
    course_folder: Path,
    course_id: int,
    course_name: str,
    placeholders: DashboardPlaceholders,
    log_deque,
    error_log_path: Path,
    mode: str = 'download',
    contract: Optional[dict] = None,
    explicit_files: Optional[Sequence[str]] = None,
) -> int:
    """Run the full post-processing pipeline for a single course folder.

    Parameters
    ----------
    course_folder : Path
        Absolute path to the course folder on disk.
    course_id : int
        Canvas course ID (for SyncManager DB init).
    course_name : str
        Human-readable course name.
    placeholders : DashboardPlaceholders
        Explicit Streamlit placeholders — never touches global UI state.
    log_deque : collections.deque
        Terminal log lines (shared with the calling update_ui).
    error_log_path : Path
        Root directory for error log files.
    mode : str
        ``'download'`` or ``'sync'``. Controls which cancellation flag is checked.
    contract : dict, optional
        Conversion contract (e.g. ``{'convert_zip': True, ...}``).
        If None, built automatically from ``persistent_*`` session state.
    explicit_files : list[str], optional
        If provided, only process these specific files (used by isolated retry).

    Returns
    -------
    int
        Number of post-processing failures reported by the UIBridge.
    """
    # Lazy imports to avoid circular dependency chains
    from post_processing import run_all_conversions, UIBridge
    from sync_manager import SyncManager

    if contract is None:
        contract = build_conversion_contract()

    # Exit early if nothing to do
    if not any(contract.values()):
        return 0

    # Select the correct cancellation checker
    if mode == 'sync':
        cancel_fn = lambda: is_sync_cancelled()
    else:
        cancel_fn = lambda: is_download_cancelled()

    # Guard: don't start post-processing if already cancelled
    if cancel_fn():
        return 0

    pp_sm = SyncManager(course_folder, course_id, course_name)
    pp_ui = UIBridge(
        header_placeholder=placeholders.header,
        progress_placeholder=placeholders.progress,
        metrics_placeholder=placeholders.metrics,
        log_placeholder=placeholders.log,
        active_file_placeholder=placeholders.active_file,
        log_lines=log_deque,
        is_cancelled=cancel_fn,
        error_log_path=error_log_path,
    )

    run_all_conversions(
        course_folder=course_folder,
        sm=pp_sm,
        contract=contract,
        ui=pp_ui,
        course_name=course_name,
        **({"explicit_files": explicit_files} if explicit_files else {}),
    )

    # Track post-processing failures globally
    st.session_state['pp_failure_count'] = (
        st.session_state.get('pp_failure_count', 0) + pp_ui.pp_failure_count
    )

    # ── Sidecar Ledger Injection ──
    # Post-processing may generate .txt sidecar files alongside converted PDFs.
    # These must be injected into the download_file_details ledger so the
    # completion screen can show them.
    _inject_sidecar_paths(pp_ui.generated_sidecar_paths, course_name)

    return pp_ui.pp_failure_count


# ═══════════════════════════════════════════════
# Private Helpers
# ═══════════════════════════════════════════════

def _inject_sidecar_paths(sidecar_paths: list, course_name: str) -> None:
    """Merge generated sidecar file paths into the UI file ledger.

    Preserves existing entries (deduplication by set membership).
    Also increments downloaded_items and total_items so the completion
    screen counts are accurate.
    """
    if not sidecar_paths:
        return

    ledger = st.session_state.get('download_file_details', {})
    if course_name not in ledger:
        ledger[course_name] = []

    existing = set(ledger[course_name])
    new_count = 0
    for sp in sidecar_paths:
        if sp not in existing:
            ledger[course_name].append(sp)
            existing.add(sp)
            new_count += 1

    if new_count > 0:
        st.session_state['download_file_details'] = ledger
        st.session_state['downloaded_items'] = (
            st.session_state.get('downloaded_items', 0) + new_count
        )
        st.session_state['total_items'] = (
            st.session_state.get('total_items', 0) + new_count
        )
