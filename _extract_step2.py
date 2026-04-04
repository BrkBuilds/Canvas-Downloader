"""Phase 6/7 extraction: read Step 2 from app.py, wrap in function, write to ui/download_settings.py"""
import re

# Read app.py
with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Step 2 body: lines 1022-2428 (1-indexed), so indices 1021-2427
# The original lines are indented 8 spaces (inside `with _main_content.container():` + `elif step == 2:`)
step2_lines = lines[1021:2428]  # L1022 to L2428

# Dedent by 8 spaces (the elif/with nesting level)
dedented = []
for line in step2_lines:
    text = line.rstrip('\r\n')
    if text.startswith('        '):
        dedented.append(text[8:] + '\n')
    elif text.strip() == '':
        dedented.append('\n')
    else:
        dedented.append(text + '\n')

# Build the module
header = '''"""
ui.download_settings — Step 2 download settings page.

Extracted from ``app.py`` (Phase 6).
Strict physical move — NO logic changes.

Contains:
  - ``render_download_settings()`` — full Step 2: preset buttons, Card 1
    (Core Course Files), Card 2 (Canvas Content), Card 3 (AI Engine),
    Output Path, Course Summary, Confirm button.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

import streamlit as st

import theme
from preset_manager import PresetManager
from ui_helpers import (
    esc,
    friendly_course_name,
    render_download_wizard,
    native_folder_picker,
    short_path,
    check_disk_space,
)
from ui_shared import (
    render_completion_card,
    render_folder_cards,
    render_error_section,
    render_pp_warning,
    SECONDARY_ENTITY_ICONS,
    render_config_summary_badges,
)
from styles import inject_css
from core.state_registry import (
    NOTEBOOK_SUB_KEYS,
    SECONDARY_CONTENT_KEYS,
    TOTAL_SECONDARY_SUBS,
)


def _resolve_path(path):
    """Resolve path for frozen (PyInstaller) vs normal execution."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, path)
    return path


def _select_folder():
    """Open native folder picker and store result in download_path."""
    folder_path = native_folder_picker()
    if folder_path:
        st.session_state['download_path'] = folder_path


def _get_chevron_base64(is_expanded):
    if is_expanded:
        svg = \'\'\'<svg xmlns="http://www.w3.org/2000/svg" width="1792" height="1792" viewBox="0 0 1792 1792" id="chevron"><path d="m1683 808-742 741q-19 19-45 19t-45-19L109 808q-19-19-19-45.5t19-45.5l166-165q19-19 45-19t45 19l531 531 531-531q19-19 45-19t45 19l166 165q19 19 19 45.5t-19 45.5z"></path></svg>\'\'\'
    else:
        svg = \'\'\'<svg xmlns="http://www.w3.org/2000/svg" width="1792" height="1792" viewBox="0 0 1792 1792" id="chevron"><path d="m1363 877-742 742q-19 19-45 19t-45-19l-166-166q-19-19-19-45t19-45l531-531-531-531q-19-19-19-45t19-45L531 45q19-19 45-19t45 19l742 742q19 19 19 45t-19 45z"></path></svg>\'\'\'
    b64_str = base64.b64encode(svg.encode('utf-8')).decode()
    return f"url('data:image/svg+xml;base64,{b64_str}')"


def render_download_settings(fetch_courses_fn):
    """Render the full Step 2 download settings page.

    Args:
        fetch_courses_fn: The cached ``fetch_courses()`` function from app.py.
    """
    # Import preset dialogs from extracted module
    from ui.presets import _save_config_dialog, _presets_hub_dialog

'''

# Write output
with open('ui/download_settings.py', 'w', encoding='utf-8', newline='') as f:
    f.write(header)
    # Now write the dedented body with 4-space indent (inside the function)
    for line in dedented:
        if line.strip() == '':
            f.write('\n')
        else:
            f.write('    ' + line)

print(f"Extracted {len(step2_lines)} lines from app.py L1022-L2428")
print(f"Written to ui/download_settings.py")
