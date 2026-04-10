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
    
    Uses st.markdown(unsafe_allow_html=True) instead of st.html() because
    st.html() renders inside an iframe, meaning its <style> tags cannot
    reach the parent page DOM (sidebar, main content, etc.).
    st.markdown injects directly into the page DOM.
    """
    css_path = _STYLES_DIR / filename
    if not css_path.exists():
        raise FileNotFoundError(f"CSS file not found: {css_path}")
    
    css_content = css_path.read_text(encoding='utf-8')
    st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)
