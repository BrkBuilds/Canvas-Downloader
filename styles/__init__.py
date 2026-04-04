"""
Styles package — External CSS injection for Canvas Downloader.

All static CSS lives in .css files within this directory.
Dynamic CSS (requiring Python f-string values) remains inline in logic modules.

Usage:
    from styles import inject_css
    inject_css('global.css')
"""

import streamlit as st
from pathlib import Path

_STYLES_DIR = Path(__file__).parent
_CSS_CACHE: dict[str, str] = {}


def inject_css(filename: str) -> None:
    """Read a .css file from the styles/ directory and inject via st.markdown.

    Uses a module-level cache to avoid re-reading files from disk on
    every Streamlit rerun.

    Args:
        filename: Name of the CSS file (e.g., 'global.css').

    Raises:
        FileNotFoundError: If the CSS file does not exist.
    """
    if filename not in _CSS_CACHE:
        css_path = _STYLES_DIR / filename
        if not css_path.exists():
            raise FileNotFoundError(f"CSS file not found: {css_path}")
        _CSS_CACHE[filename] = css_path.read_text(encoding='utf-8')
    st.markdown(f"<style>{_CSS_CACHE[filename]}</style>", unsafe_allow_html=True)
