"""
Progress Dashboard — Unified progress UI rendering for Canvas Downloader.

Provides shared HTML rendering functions used by both the download flow
(app.py) and the sync flow (sync_ui.py).  All Streamlit placeholders are
passed explicitly as arguments — never imported from global state.

Usage:
    from engine.progress_dashboard import (
        DashboardPlaceholders, render_progress_dashboard, render_terminal_log,
    )
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Sequence

import theme


# ═══════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════

@dataclass
class DashboardPlaceholders:
    """Encapsulates the five Streamlit st.empty() slots that make up the
    progress dashboard.  Passed explicitly into every render call so the
    engine never touches global UI state.
    """
    header: object          # st.empty() — course name + phase label
    progress: object        # st.empty() — progress bar
    metrics: object         # st.empty() — 4-metric row (downloaded/speed/files/eta)
    active_file: object     # st.empty() — "Currently downloading: …"
    log: object             # st.empty() — terminal log widget


@dataclass
class DashboardMetrics:
    """Pure-data container holding all values needed to render a single
    frame of the dashboard.
    """
    current_files: int = 0
    total_files: int = 1
    downloaded_mb: float = 0.0
    total_mb: float = 0.0
    speed_mb_s: float = 0.0
    eta_string: str = "--:--"
    percent: int = 0
    # Header content
    header_label: str = "📦 Downloading Courses"
    course_name: str = ""


# ═══════════════════════════════════════════════
# Render Functions
# ═══════════════════════════════════════════════

def render_progress_header(placeholders: DashboardPlaceholders, label: str, course_name: str) -> None:
    """Render the header section (phase label + course name)."""
    placeholders.header.markdown(f'''
    <div style="margin-bottom: 0.5rem;">
        <p style="margin: 0; font-size: 0.8rem; color: {theme.TEXT_SECONDARY}; text-transform: uppercase;">{label}</p>
        <h3 style="margin: 0; padding-top: 0.1rem; color: {theme.TEXT_PRIMARY};">{course_name}</h3>
    </div>
    ''', unsafe_allow_html=True)


def render_progress_bar(placeholders: DashboardPlaceholders, percent: int) -> None:
    """Render the custom HTML progress bar."""
    placeholders.progress.markdown(f'''
    <div style="background-color: {theme.BG_CARD}; border-radius: 8px; width: 100%; height: 24px; position: relative; margin-bottom: 10px;">
        <div style="background-color: {theme.ACCENT_BLUE}; width: {percent}%; height: 100%; border-radius: 8px; transition: width 0.3s ease;"></div>
        <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold;">
            {percent}%
        </div>
    </div>
    ''', unsafe_allow_html=True)


def render_metrics_row(
    placeholders: DashboardPlaceholders,
    downloaded_mb: float,
    total_mb: float,
    speed_mb_s: float,
    current_files: int,
    total_files: int,
    eta_string: str,
    *,
    show_total_mb: bool = True,
) -> None:
    """Render the 4-metric row (Downloaded / Speed / Files / ETA).

    When ``show_total_mb`` is False the "Downloaded" column omits the
    "/ X.X MB" denominator (used by the retry dashboard where total_mb
    is not always meaningful).
    """
    mb_display = (
        f"{downloaded_mb:.1f} <span style=\"font-size: 0.9rem; color: {theme.ACCENT_BLUE};\">/ {total_mb:.1f} MB</span>"
        if show_total_mb
        else f"{downloaded_mb:.1f} <span style=\"font-size: 0.9rem; color: {theme.ACCENT_BLUE};\">MB</span>"
    )

    placeholders.metrics.markdown(f'''
    <div style="display: flex; justify-content: center; gap: 4rem; background-color: {theme.BG_DARK}; padding: 15px 25px; border-radius: 8px; border: 1px solid {theme.BG_CARD}; margin-top: 5px; margin-bottom: 15px;">
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Downloaded</span>
            <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{mb_display}</span>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Speed</span>
            <span style="color: #10B981; font-size: 1.2rem; font-weight: bold;">{speed_mb_s:.1f} <span style="font-size: 0.9rem;">MB/s</span></span>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Files</span>
            <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{current_files} <span style="font-size: 0.9rem; color: {theme.ACCENT_BLUE};">/ {total_files}</span></span>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Time Remaining</span>
            <span style="color: #F59E0B; font-size: 1.2rem; font-weight: bold;">{eta_string}</span>
        </div>
    </div>
    ''', unsafe_allow_html=True)


def render_terminal_log(placeholders: DashboardPlaceholders, log_deque) -> None:
    """Render the terminal-style log widget from a deque of HTML-safe lines."""
    log_content = "<br>".join(reversed(list(log_deque))) if log_deque else f"<span style='color: {theme.TEXT_SECONDARY};'>Waiting for files...</span>"
    placeholders.log.markdown(f'''
    <div style="background-color: {theme.BG_TERMINAL}; color: {theme.TERMINAL_TEXT}; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; font-size: 0.85rem; height: 140px; border: 1px solid {theme.BORDER_TERMINAL}; line-height: 1.6; overflow-y: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.5);">
        {log_content}
    </div>
    ''', unsafe_allow_html=True)


# ═══════════════════════════════════════════════
# Convenience: Full Dashboard Render
# ═══════════════════════════════════════════════

def render_full_dashboard(
    placeholders: DashboardPlaceholders,
    log_deque,
    *,
    header_label: str,
    course_name: str,
    current_files: int,
    total_files: int,
    downloaded_mb: float,
    total_mb: float,
    start_time: float,
    show_total_mb: bool = True,
) -> None:
    """One-call convenience that renders header + progress bar + metrics + log.

    Computes percent, speed, and ETA from the provided raw values.
    """
    # Percent
    if total_files > 0:
        percent = int((current_files / total_files) * 100)
        percent = min(100, percent)
        if current_files >= total_files:
            percent = 100
    else:
        percent = 0

    # Speed & ETA
    elapsed = time.time() - start_time
    speed_mb_s = (downloaded_mb / elapsed) if elapsed > 0 else 0.0
    remaining_mb = max(0, total_mb - downloaded_mb)
    eta_seconds = (remaining_mb / speed_mb_s) if speed_mb_s > 0 else 0
    eta_string = time.strftime('%M:%S', time.gmtime(max(0, eta_seconds)))

    render_progress_header(placeholders, header_label, course_name)
    render_progress_bar(placeholders, percent)
    render_metrics_row(
        placeholders,
        downloaded_mb=downloaded_mb,
        total_mb=total_mb,
        speed_mb_s=speed_mb_s,
        current_files=current_files,
        total_files=total_files,
        eta_string=eta_string,
        show_total_mb=show_total_mb,
    )
    render_terminal_log(placeholders, log_deque)


# ═══════════════════════════════════════════════
# Sync-specific HTML helpers (return strings instead of writing to placeholders)
# ═══════════════════════════════════════════════

def build_metrics_html(
    current_files: int,
    total_files: int,
    downloaded_mb: float,
    total_mb: float,
    speed_mb_s: float,
    eta_string: str,
) -> str:
    """Return the metrics-row HTML as a string (for sync_ui.py which uses
    placeholder.markdown(html) directly).
    """
    return f"""
    <div style="display: flex; justify-content: center; gap: 4rem; background-color: {theme.BG_DARK}; padding: 15px 25px; border-radius: 8px; border: 1px solid {theme.BG_CARD}; margin-top: 5px; margin-bottom: 15px;">
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Downloaded</span>
            <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{downloaded_mb:.1f} <span style="font-size: 0.9rem; color: {theme.ACCENT_BLUE};">/ {total_mb:.1f} MB</span></span>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Speed</span>
            <span style="color: #10B981; font-size: 1.2rem; font-weight: bold;">{speed_mb_s:.1f} <span style="font-size: 0.9rem;">MB/s</span></span>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Files</span>
            <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{current_files} <span style="font-size: 0.9rem; color: {theme.ACCENT_BLUE};">/ {total_files}</span></span>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Time Remaining</span>
            <span style="color: #F59E0B; font-size: 1.2rem; font-weight: bold;">{eta_string}</span>
        </div>
    </div>
    """


def build_terminal_html(lines) -> str:
    """Return the terminal-log HTML as a string (for sync_ui.py)."""
    joined = "<br>".join(reversed(list(lines))) if lines else f"<span style='color: {theme.TEXT_SECONDARY};'>Waiting for files...</span>"
    return f"""
    <div style="background: {theme.BG_TERMINAL}; border: 1px solid {theme.BORDER_TERMINAL}; border-radius: 6px; padding: 10px 14px; font-family: monospace; font-size: 0.85em; color: {theme.TERMINAL_TEXT}; line-height: 1.5; min-height: 200px; max-height: 250px; overflow-y: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.5);">
        {joined}
    </div>
    """
