"""
ui.amber_notice - Reusable amber/gold notice card for non-fatal warnings.

Use this to surface system boundaries, informational warnings, or state
constraints without resorting to error-red UI.  Matches the "linked folder"
notice aesthetic (warm golden background, structured title/detail layout).

Usage:
    from ui.amber_notice import render_amber_notice

    render_amber_notice("Some folders couldn't be found - fix or remove them before syncing.")
    render_amber_notice(
        "Quick Sync skipped some files.",
        detail="Locally deleted files and edited files are skipped automatically.",
    )
"""

from __future__ import annotations

import streamlit as st


def render_amber_notice(
    message: str,
    *,
    icon: str = "⚠️",
    detail: str | None = None,
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
            f"'>{detail}</div>"
        )

    html = (
        f"<div style='"
        f"background: rgba(234, 179, 8, 0.12); "
        f"border: 1px solid rgba(234, 179, 8, 0.55); "
        f"border-radius: 6px; "
        f"padding: 10px 14px; "
        f"margin: 4px 0 2px 0; "
        f"font-size: 0.9rem; "
        f"line-height: 1.5;"
        f"'>"
        f"<div style='color: #fbbf24; font-weight: 700;'>"
        f"{icon} {message}"
        f"</div>"
        f"{detail_html}"
        f"</div>"
    )

    if key:
        with st.container(key=key):
            st.markdown(html, unsafe_allow_html=True)
    else:
        st.markdown(html, unsafe_allow_html=True)
