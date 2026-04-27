"""
Styles package — External CSS injection for Canvas Downloader.

All static CSS lives in .css files within this directory.
Dynamic CSS (requiring Python f-string values) remains inline in logic modules.

Usage:
    from styles import inject_css
    inject_css('global.css')
"""

import sys
import streamlit as st
from pathlib import Path

_STYLES_DIR = Path(__file__).parent
_CSS_CACHE: dict[str, str] = {}
_FROZEN = bool(getattr(sys, 'frozen', False))


def inject_css(filename: str) -> None:
    """Read a .css file from the styles/ directory and inject via st.markdown.

    Uses st.markdown(unsafe_allow_html=True) instead of st.html() because
    st.html() renders inside an iframe, meaning its <style> tags cannot
    reach the parent page DOM (sidebar, main content, etc.).
    st.markdown injects directly into the page DOM.

    Caches CSS content in frozen (PyInstaller) builds — assets ship
    immutable inside the bundle, so re-reading from disk on every rerun
    is pure waste. In dev (unfrozen) we always re-read so edits to .css
    files take effect on the next rerun without restarting Streamlit.
    """
    if _FROZEN and filename in _CSS_CACHE:
        css_content = _CSS_CACHE[filename]
    else:
        css_path = _STYLES_DIR / filename
        if not css_path.exists():
            raise FileNotFoundError(f"CSS file not found: {css_path}")
        css_content = css_path.read_text(encoding='utf-8')
        if _FROZEN:
            _CSS_CACHE[filename] = css_content

    st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)
