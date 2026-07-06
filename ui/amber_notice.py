"""
ui.amber_notice - Reusable notice cards for inline warnings and info messages.

Two variants:
  - ``render_amber_notice`` - amber/gold warning card for non-fatal warnings.
  - ``render_info_notice``  - blue/teal info card for informational messages.

Usage:
    from ui.amber_notice import render_amber_notice, render_info_notice, render_error_notice

    render_amber_notice("Some folders couldn't be found - fix or remove them before syncing.")
    render_info_notice(
        "Canvas Downloader automatically matched this folder to its corresponding course.",
    )
"""

from __future__ import annotations

import streamlit as st
from shared.helpers import esc


def render_amber_notice(
    message: str,
    *,
    icon: str = "⚠️",
    detail: str | None = None,
    margin: str = "4px 0 20px 0",
    key: str | None = None,
) -> None:
    """Render a styled amber/gold notice card.

    Parameters
    ----------
    message : str
        Primary message text (bold, golden).
    icon : str
        Leading emoji/icon.  Defaults to ⚠️.
    detail : str | None
        Optional secondary explanation line, rendered in a softer tone
        below the primary message.
    margin : str
        CSS margin string. Defaults to "4px 0 20px 0".
    key : str | None
        Optional Streamlit key to prevent duplicate rendering during
        fragment reruns.
    """
    detail_html = ""
    if detail:
        detail_html = (
            f"<div style='"
            f"color: rgba(253, 230, 138, 0.75); "
            f"font-size: 0.85rem; "
            f"margin-top: 5px; "
            f"line-height: 1.5;"
            f"'>{esc(detail)}</div>"
        )

    html = (
        f"<div style='"
        f"background: rgba(234, 179, 8, 0.12); "
        f"border: 1px solid rgba(234, 179, 8, 0.55); "
        f"border-radius: 6px; "
        f"padding: 10px 14px; "
        f"margin: {margin}; "
        f"font-size: 0.9rem; "
        f"line-height: 1.5;"
        f"'>"
        f"<div style='color: #fbbf24; font-weight: 700;'>"
        f"{icon} {esc(message)}"
        f"</div>"
        f"{detail_html}"
        f"</div>"
    )

    if key:
        with st.container(key=key):
            st.markdown(html, unsafe_allow_html=True)
    else:
        st.markdown(html, unsafe_allow_html=True)


def render_info_notice(
    message: str,
    *,
    icon: str = "ℹ️",
    detail: str | None = None,
    margin: str = "4px 0 20px 0",
    key: str | None = None,
    allow_html: bool = False,
    tooltip: str | None = None,
) -> None:
    """Render a styled blue/teal informational notice card.

    Same structure as ``render_amber_notice`` but with cool blue tones,
    appropriate for non-warning informational messages (e.g. auto-detection
    confirmations, status updates).

    Parameters
    ----------
    message : str
        Primary message text.
    icon : str
        Leading emoji/icon.  Defaults to ℹ️.
    detail : str | None
        Optional secondary explanation line, rendered in a softer tone
        below the primary message.
    margin : str
        CSS margin string. Defaults to "4px 0 20px 0".
    key : str | None
        Optional Streamlit key to prevent duplicate rendering during
        fragment reruns.
    allow_html : bool
        If True, the message is not HTML-escaped.
    tooltip : str | None
        Optional tooltip text to show on hover next to the main message.
    """
    detail_html = ""
    if detail:
        detail_html = (
            f"<div style='"
            f"color: rgba(186, 230, 253, 0.75); "
            f"font-size: 0.85rem; "
            f"margin-top: 5px; "
            f"line-height: 1.5;"
            f"'>{esc(detail) if not allow_html else detail}</div>"
        )

    msg_content = message if allow_html else esc(message)

    tooltip_html = ""
    if tooltip:
        tooltip_html = (
            f"<div class='info-tooltip' style='display: inline-flex; align-items: center; position: relative; cursor: help; margin-left: 6px; color: rgba(255,255,255,0.45);'>"
            f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='width: 15px; height: 15px;'><circle cx='12' cy='12' r='10'></circle><path d='M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3'></path><line x1='12' y1='17' x2='12.01' y2='17'></line></svg>"
            f"<span class='tooltiptext' style='visibility: hidden; width: max-content; max-width: 280px; background-color: #2c2d30; color: #fff; text-align: left; border-radius: 6px; padding: 8px 12px; position: absolute; z-index: 1; bottom: 125%; left: 50%; transform: translateX(-50%); opacity: 0; transition: opacity 0.2s; font-size: 0.8rem; font-weight: normal; line-height: 1.4; box-shadow: 0 4px 12px rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.1);'>{esc(tooltip)}</span>"
            f"</div>"
            f"<style>"
            f".info-tooltip:hover .tooltiptext {{ visibility: visible !important; opacity: 1 !important; }}"
            f".info-tooltip:hover {{ color: rgba(255,255,255,0.85) !important; }}"
            f"</style>"
        )

    html = (
        f"<div style='"
        f"background: rgba(14, 165, 233, 0.05); "
        f"border: 1px solid rgba(14, 165, 233, 0.2); "
        f"border-radius: 6px; "
        f"padding: 10px 14px; "
        f"margin: {margin}; "
        f"font-size: 0.9rem; "
        f"line-height: 1.5;"
        f"'>"
        f"<div style='color: #94a3b8; font-weight: 500; display: flex; align-items: center;'>"
        f"<span style='margin-right: 6px; color: #38bdf8;'>{icon}</span>"
        f"<span>{msg_content}</span>"
        f"{tooltip_html}"
        f"</div>"
        f"{detail_html}"
        f"</div>"
    )

    if key:
        with st.container(key=key):
            st.markdown(html, unsafe_allow_html=True)
    else:
        st.markdown(html, unsafe_allow_html=True)


def render_success_notice(
    message: str,
    *,
    icon: str = "✅",
    detail: str | None = None,
    margin: str = "4px 0 20px 0",
    key: str | None = None,
    allow_html: bool = False,
    tooltip: str | None = None,
) -> None:
    """Render a styled green success notice card.

    Same structure as ``render_amber_notice`` but with green tones,
    appropriate for success messages.

    Parameters
    ----------
    message : str
        Primary message text.
    icon : str
        Leading emoji/icon. Defaults to ✅.
    detail : str | None
        Optional secondary explanation line, rendered in a softer tone
        below the primary message.
    margin : str
        CSS margin string. Defaults to "4px 0 20px 0".
    key : str | None
        Optional Streamlit key to prevent duplicate rendering during
        fragment reruns.
    allow_html : bool
        If True, the message is not HTML-escaped.
    tooltip : str | None
        Optional tooltip text to show on hover next to the main message.
    """
    detail_html = ""
    if detail:
        detail_html = (
            f"<div style='"
            f"color: rgba(167, 243, 208, 0.75); "
            f"font-size: 0.85rem; "
            f"margin-top: 5px; "
            f"line-height: 1.5;"
            f"'>{esc(detail) if not allow_html else detail}</div>"
        )

    msg_content = message if allow_html else esc(message)

    tooltip_html = ""
    if tooltip:
        tooltip_html = (
            f"<div class='success-tooltip' style='display: inline-flex; align-items: center; position: relative; cursor: help; margin-left: 6px; color: rgba(255,255,255,0.45);'>"
            f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='width: 15px; height: 15px;'><circle cx='12' cy='12' r='10'></circle><path d='M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3'></path><line x1='12' y1='17' x2='12.01' y2='17'></line></svg>"
            f"<span class='tooltiptext' style='visibility: hidden; width: max-content; max-width: 280px; background-color: #2c2d30; color: #fff; text-align: left; border-radius: 6px; padding: 8px 12px; position: absolute; z-index: 1; bottom: 125%; left: 50%; transform: translateX(-50%); opacity: 0; transition: opacity 0.2s; font-size: 0.8rem; font-weight: normal; line-height: 1.4; box-shadow: 0 4px 12px rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.1);'>{esc(tooltip)}</span>"
            f"</div>"
            f"<style>"
            f".success-tooltip:hover .tooltiptext {{ visibility: visible !important; opacity: 1 !important; }}"
            f".success-tooltip:hover {{ color: rgba(255,255,255,0.85) !important; }}"
            f"</style>"
        )

    html = (
        f"<div style='"
        f"background: rgba(34, 197, 94, 0.08); "
        f"border: 1px solid rgba(34, 197, 94, 0.3); "
        f"border-radius: 6px; "
        f"padding: 10px 14px; "
        f"margin: {margin}; "
        f"font-size: 0.9rem; "
        f"line-height: 1.5;"
        f"'>"
        f"<div style='color: #cbd5e1; font-weight: 500; display: flex; align-items: center;'>"
        f"<span style='margin-right: 6px; color: #4ade80;'>{icon}</span>"
        f"<span>{msg_content}</span>"
        f"{tooltip_html}"
        f"</div>"
        f"{detail_html}"
        f"</div>"
    )

    if key:
        with st.container(key=key):
            st.markdown(html, unsafe_allow_html=True)
    else:
        st.markdown(html, unsafe_allow_html=True)


def render_error_notice(
    message: str,
    *,
    icon: str = "❌",
    detail: str | None = None,
    margin: str = "4px 0 20px 0",
    key: str | None = None,
    allow_html: bool = False,
    tooltip: str | None = None,
) -> None:
    """Render a styled red error notice card.

    Same structure as ``render_amber_notice`` but with red tones,
    appropriate for error messages.

    Parameters
    ----------
    message : str
        Primary message text.
    icon : str
        Leading emoji/icon. Defaults to ❌.
    detail : str | None
        Optional secondary explanation line, rendered in a softer tone
        below the primary message.
    margin : str
        CSS margin string. Defaults to "4px 0 20px 0".
    key : str | None
        Optional Streamlit key to prevent duplicate rendering during
        fragment reruns.
    allow_html : bool
        If True, the message is not HTML-escaped.
    tooltip : str | None
        Optional tooltip text to show on hover next to the main message.
    """
    detail_html = ""
    if detail:
        detail_html = (
            f"<div style='"
            f"color: rgba(254, 202, 202, 0.75); "
            f"font-size: 0.85rem; "
            f"margin-top: 5px; "
            f"line-height: 1.5;"
            f"'>{esc(detail) if not allow_html else detail}</div>"
        )

    msg_content = message if allow_html else esc(message)

    tooltip_html = ""
    if tooltip:
        tooltip_html = (
            f"<div class='error-tooltip' style='display: inline-flex; align-items: center; position: relative; cursor: help; margin-left: 6px; color: rgba(255,255,255,0.45);'>"
            f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='width: 15px; height: 15px;'><circle cx='12' cy='12' r='10'></circle><path d='M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3'></path><line x1='12' y1='17' x2='12.01' y2='17'></line></svg>"
            f"<span class='tooltiptext' style='visibility: hidden; width: max-content; max-width: 280px; background-color: #2c2d30; color: #fff; text-align: left; border-radius: 6px; padding: 8px 12px; position: absolute; z-index: 1; bottom: 125%; left: 50%; transform: translateX(-50%); opacity: 0; transition: opacity 0.2s; font-size: 0.8rem; font-weight: normal; line-height: 1.4; box-shadow: 0 4px 12px rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.1);'>{esc(tooltip)}</span>"
            f"</div>"
            f"<style>"
            f".error-tooltip:hover .tooltiptext {{ visibility: visible !important; opacity: 1 !important; }}"
            f".error-tooltip:hover {{ color: rgba(255,255,255,0.85) !important; }}"
            f"</style>"
        )

    html = (
        f"<div style='"
        f"background: rgba(239, 68, 68, 0.08); "
        f"border: 1px solid rgba(239, 68, 68, 0.3); "
        f"border-radius: 6px; "
        f"padding: 10px 14px; "
        f"margin: {margin}; "
        f"font-size: 0.9rem; "
        f"line-height: 1.5;"
        f"'>"
        f"<div style='color: #fca5a5; font-weight: 500; display: flex; align-items: center;'>"
        f"<span style='margin-right: 6px; color: #ef4444;'>{icon}</span>"
        f"<span>{msg_content}</span>"
        f"{tooltip_html}"
        f"</div>"
        f"{detail_html}"
        f"</div>"
    )

    if key:
        with st.container(key=key):
            st.markdown(html, unsafe_allow_html=True)
    else:
        st.markdown(html, unsafe_allow_html=True)
