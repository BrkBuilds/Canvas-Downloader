"""
ui.download_settings - Step 2 download settings page.

Extracted from ``app.py`` (Phase 6).
Strict physical move - NO logic changes.

Contains:
  - ``render_download_settings()`` - full Step 2: preset buttons, Card 1
    (Core Course Files), Card 2 (Canvas Content), Card 3 (AI Engine),
    Output Path, Course Summary, Confirm button.
"""

from __future__ import annotations

import base64
import functools
import os
import sys
import time
from pathlib import Path

import streamlit as st

import theme
from ui_helpers import (
    esc,
    get_course_display_parts,
    render_download_wizard,
    native_folder_picker,
    get_base64_image,
)
from core.state_registry import (
    SECONDARY_CONTENT_KEYS,
    NOTEBOOK_SUB_KEYS,
    TOTAL_SECONDARY_SUBS,
)
from ui_shared import render_help_card, HELP_ICONS


def _resolve_path(path):
    """Resolve path for frozen (PyInstaller) vs normal execution."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, path)
    return path


@functools.lru_cache(maxsize=64)
def _load_b64(path):
    """Load a file and base64-encode it. Cached: assets don't change at runtime."""
    try:
        with open(_resolve_path(path), "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        return ""


def safe_b64(name):
    """Load an asset PNG by name and return base64 string, or "" on failure.

    Cached via the underlying ``get_base64_image`` lru_cache, so repeated
    calls during reruns are free.
    """
    try:
        res = get_base64_image(f"assets/{name}")
        return res if res else ""
    except Exception:
        return ""


def _select_folder():
    """Open native folder picker and store result in download_path."""
    folder_path = native_folder_picker(initial_dir=st.session_state.get('download_path') or None)
    if folder_path:
        st.session_state['download_path'] = folder_path


def _get_chevron_base64(is_expanded):
    if is_expanded:
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="1792" height="1792" viewBox="0 0 1792 1792" id="chevron"><path d="m1683 808-742 741q-19 19-45 19t-45-19L109 808q-19-19-19-45.5t19-45.5l166-165q19-19 45-19t45 19l531 531 531-531q19-19 45-19t45 19l166 165q19 19 19 45.5t-19 45.5z"></path></svg>'''
    else:
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="1792" height="1792" viewBox="0 0 1792 1792" id="chevron"><path d="m1363 877-742 742q-19 19-45 19t-45-19l-166-166q-19-19-19-45t19-45l531-531-531-531q-19-19-19-45t19-45L531 45q19-19 45-19t45 19l742 742q19 19 19 45t-19 45z"></path></svg>'''
    b64_str = base64.b64encode(svg.encode('utf-8')).decode()
    return f"url('data:image/svg+xml;base64,{b64_str}')"


def render_download_settings(fetch_courses_fn):
    """Render the full Step 2 download settings page.

    Args:
        fetch_courses_fn: The cached ``fetch_courses()`` function from app.py.
    """
    # Import preset dialogs from extracted module
    from ui.presets import _save_config_dialog, _presets_hub_dialog

    render_download_wizard(st, 2)

    # Hoisted CSS Overrides for Step 2 UI Component geometry
    # Use st.html (not st.markdown) to avoid ghost-box 1rem margin below the stepper.
    st.html("""<style>
    div[data-testid="stHorizontalBlock"]:has(.st-key-action_dl_back),
    div[data-testid="stHorizontalBlock"]:has(.st-key-action_dl_confirm) {
        margin-top: -15px !important;
    }
    </style>""")

    # Consume pending toasts from preset dialogs
    if 'pending_toast' in st.session_state:
        st.toast(st.session_state.pop('pending_toast'))

    # Step 2 Header with Preset Buttons
    _hdr_left, _hdr_right = st.columns([0.6, 0.4])
    
    # Define Help Content
    help_title = "Download Settings Guide"
    # Inner setting buttons: grey bg, white text, themed border; answer divs: dark bg, white text
    _b1 = "padding: 8px 12px; cursor: pointer; font-weight: 600; font-size: 0.85rem; color: #e2e8f0; background: rgba(255,255,255,0.08); border: 1px solid rgba(63,217,255,0.4); border-radius: 5px; user-select: none; list-style: none;"
    _b2 = "padding: 8px 12px; cursor: pointer; font-weight: 600; font-size: 0.85rem; color: #e2e8f0; background: rgba(255,255,255,0.08); border: 1px solid rgba(104,212,163,0.42); border-radius: 5px; user-select: none; list-style: none;"
    _b3 = "padding: 8px 12px; cursor: pointer; font-weight: 600; font-size: 0.85rem; color: #e2e8f0; background: rgba(255,255,255,0.08); border: 1px solid rgba(249,115,22,0.42); border-radius: 5px; user-select: none; list-style: none;"
    _ans1 = "padding: 9px 13px 11px 13px; font-size: 0.85rem; color: #e2e8f0; background: rgba(0,0,0,0.32); border-left: 2px solid rgba(63,217,255,0.5); margin-top: 1px; line-height: 1.6; cursor: default;"
    _ans2 = "padding: 9px 13px 11px 13px; font-size: 0.85rem; color: #e2e8f0; background: rgba(0,0,0,0.32); border-left: 2px solid rgba(104,212,163,0.5); margin-top: 1px; line-height: 1.6; cursor: default;"
    _ans3 = "padding: 9px 13px 11px 13px; font-size: 0.85rem; color: #e2e8f0; background: rgba(0,0,0,0.32); border-left: 2px solid rgba(249,115,22,0.5); margin-top: 1px; line-height: 1.6; cursor: default;"
    _row = "margin: 5px 0; border-radius: 5px; overflow: hidden;"
    _lbl = "font-size: 0.73rem; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; margin: 13px 0 5px 0; color: rgba(255,255,255,0.9);"
    # Shared badge styles (inline, placed after title text in HTML)
    _tag1 = "color: #3fd9ff; background: rgba(63,217,255,0.15); padding: 1px 8px; border-radius: 4px; font-size: 0.74rem; font-weight: 700; margin-left: 8px; vertical-align: middle;"
    _tag2 = "color: #68d4a3; background: rgba(104,212,163,0.18); padding: 1px 8px; border-radius: 4px; font-size: 0.74rem; font-weight: 700; margin-left: 8px; vertical-align: middle;"
    _tag3 = "color: #f97316; background: rgba(249,115,22,0.18); padding: 1px 8px; border-radius: 4px; font-size: 0.74rem; font-weight: 700; margin-left: 8px; vertical-align: middle;"
    help_text = (
        # ── Intro ─────────────────────────────────────────────────────────────
        "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.75); margin-bottom: 10px;'>"
        "<b style='color: #e2e8f0;'>Your task on this page:</b> Configure the three cards below, then scroll down and click <b>Confirm and Download</b>."
        "</div>"
        "<div style='margin: 6px 0; padding: 9px 12px 9px 14px; background: rgba(63,217,255,0.05); border-radius: 6px; border-left: 3px solid rgba(63,217,255,0.45);'>"
        "<div style='display: flex; align-items: center; gap: 8px; margin-bottom: 4px;'>"
        "<span style='color: #3fd9ff; background: rgba(63,217,255,0.15); padding: 1px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: 700; white-space: nowrap;'>Card 1</span>"
        "<b style='color: #e2e8f0; font-size: 0.85rem;'>File Filter &amp; Folder Structure</b>"
        "</div>"
        "<div style='color: rgba(255,255,255,0.7); font-size: 0.85rem;'>Always visible. Choose which files to download and how to organize them into folders. This is the only required card.</div>"
        "</div>"
        "<div style='margin: 6px 0; padding: 9px 12px 9px 14px; background: rgba(104,212,163,0.05); border-radius: 6px; border-left: 3px solid rgba(104,212,163,0.45);'>"
        "<div style='display: flex; align-items: center; gap: 8px; margin-bottom: 4px;'>"
        "<span style='color: #68d4a3; background: rgba(104,212,163,0.18); padding: 1px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: 700; white-space: nowrap;'>Card 2</span>"
        "<b style='color: #e2e8f0; font-size: 0.85rem;'>Canvas Content</b>"
        "</div>"
        "<div style='color: rgba(255,255,255,0.7); font-size: 0.85rem;'>Optional. Download extra course information that only exists as web pages in Canvas - assignment instructions, your syllabus, announcements, quiz questions, and graded feedback.</div>"
        "</div>"
        "<div style='margin: 6px 0; padding: 9px 12px 9px 14px; background: rgba(249,115,22,0.05); border-radius: 6px; border-left: 3px solid rgba(249,115,22,0.45);'>"
        "<div style='display: flex; align-items: center; gap: 8px; margin-bottom: 4px;'>"
        "<span style='color: #f97316; background: rgba(249,115,22,0.18); padding: 1px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: 700; white-space: nowrap;'>Card 3</span>"
        "<b style='color: #e2e8f0; font-size: 0.85rem;'>AI Optimization</b>"
        "</div>"
        "<div style='color: rgba(255,255,255,0.7); font-size: 0.85rem;'>Optional. After downloading, automatically convert your files into formats that work best with AI study tools like NotebookLM, ChatGPT, or Claude.</div>"
        "</div>"
        "<hr>"

        # ── Section title ─────────────────────────────────────────────────────
        f"<div style='font-weight: 700; color: #ffffff; font-size: 0.95rem; margin-bottom: 8px;'>{HELP_ICONS['gear']} Settings Explained in Detail</div>"

        # ── Card 1 ────────────────────────────────────────────────────────────
        "<details style='margin: 4px 0 8px 0; border: 1px solid rgba(255,255,255,0.13); border-radius: 7px; overflow: hidden;'>"
        f"<summary style='padding: 10px 14px; cursor: pointer; background: rgba(255,255,255,0.08); user-select: none;'><span style='color: #ffffff; font-weight: 600; font-size: 0.87rem;'>File Filter &amp; Folder Structure</span><span style='{_tag1}'>Card 1</span></summary>"
        "<div style='padding: 10px 14px 14px 14px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.03);'>"
        "<p style='font-size: 0.85rem; color: rgba(255,255,255,0.65); margin: 0 0 10px 0;'>Click any setting below to read what it does.</p>"
        f"<div style='{_lbl}'>Which files to download</div>"
        f"<details style='{_row}'><summary style='{_b1}'>All Files</summary>"
        f"<div style='{_ans1}'>Downloads every file your professor uploaded: PDFs, PowerPoint slides, Word documents, images, videos, spreadsheets, zip archives, and more. Best if you want a complete offline copy of your course.</div></details>"
        f"<details style='{_row}'><summary style='{_b1}'>Slides &amp; PDFs</summary>"
        f"<div style='{_ans1}'>Downloads only lecture slides (PowerPoint files) and PDF documents. Use this if you want to skip large videos or data sets and just get the study materials.</div></details>"
        f"<div style='{_lbl}'>Folder structure</div>"
        f"<details style='{_row}'><summary style='{_b1}'>With Subfolders</summary>"
        f"<div style='{_ans1}'>Mirrors the Canvas module layout on your computer. Each module becomes its own subfolder - for example: <em>CHEM101 / Week 3 - Thermodynamics / lecture.pdf</em>. Recommended for courses with many files across multiple topics.</div></details>"
        f"<details style='{_row}'><summary style='{_b1}'>All in One Folder</summary>"
        f"<div style='{_ans1}'>Puts every file directly in the course folder with no subfolders. Easier to search everything at once, but can get cluttered for larger courses.</div></details>"
        "</div></details>"

        # ── Card 2 ────────────────────────────────────────────────────────────
        "<details style='margin: 4px 0 8px 0; border: 1px solid rgba(255,255,255,0.13); border-radius: 7px; overflow: hidden;'>"
        f"<summary style='padding: 10px 14px; cursor: pointer; background: rgba(255,255,255,0.08); user-select: none;'><span style='color: #ffffff; font-weight: 600; font-size: 0.87rem;'>Canvas Content</span><span style='{_tag2}'>Card 2</span></summary>"
        "<div style='padding: 10px 14px 14px 14px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.03);'>"
        "<p style='font-size: 0.85rem; color: rgba(255,255,255,0.65); margin: 0 0 10px 0;'>These exist only as web pages in Canvas - the app converts them into local files you can open and search. Click any item to read more.</p>"
        f"<details style='{_row}'><summary style='{_b2}'>Assignments</summary>"
        f"<div style='{_ans2}'>Saves each assignment's full instructions, due date, and attached rubric as a file you can open in any browser. Useful for reading briefs offline or uploading to an AI tool.</div></details>"
        f"<details style='{_row}'><summary style='{_b2}'>Syllabus</summary>"
        f"<div style='{_ans2}'>Saves the course syllabus page, including grading policies, office hours, and weekly schedules if your professor set those up in Canvas.</div></details>"
        f"<details style='{_row}'><summary style='{_b2}'>Announcements</summary>"
        f"<div style='{_ans2}'>Saves all course announcements in order. Great for finding deadline changes or last-minute reminders your professor posted.</div></details>"
        f"<details style='{_row}'><summary style='{_b2}'>Discussions</summary>"
        f"<div style='{_ans2}'>Saves discussion board threads. Useful if your professor posts key content there, or if you want to review classmates' responses when studying.</div></details>"
        f"<details style='{_row}'><summary style='{_b2}'>Quizzes</summary>"
        f"<div style='{_ans2}'>Saves quiz questions and answer choices. What is visible depends on your professor's privacy settings in Canvas.</div></details>"
        f"<details style='{_row}'><summary style='{_b2}'>Rubrics</summary>"
        f"<div style='{_ans2}'>Saves the grading criteria for each assignment. Helpful for understanding exactly how your work will be marked before you submit.</div></details>"
        f"<details style='{_row}'><summary style='{_b2}'>Submissions (Results)</summary>"
        f"<div style='{_ans2}'>Saves feedback and grades you received on your own submitted work: professor comments, rubric scores, and the grade per assignment. This is your personal data - your professor is not notified.</div></details>"
        f"<div style='{_lbl}'>How to organize Canvas Content</div>"
        f"<details style='{_row}'><summary style='{_b2}'>Match Course Folder structure</summary>"
        f"<div style='{_ans2}'>Places Canvas Content files alongside your regular course files in the same module subfolders.</div></details>"
        f"<details style='{_row}'><summary style='{_b2}'>In Separate Folders</summary>"
        f"<div style='{_ans2}'>Creates a dedicated subfolder per content type (Assignments, Quizzes, Discussions, etc.) inside the course folder, separate from your regular files. Note: the organization buttons are greyed out until you select at least one content type above.</div></details>"
        "</div></details>"

        # ── Card 3 ────────────────────────────────────────────────────────────
        "<details style='margin: 4px 0 8px 0; border: 1px solid rgba(255,255,255,0.13); border-radius: 7px; overflow: hidden;'>"
        f"<summary style='padding: 10px 14px; cursor: pointer; background: rgba(255,255,255,0.08); user-select: none;'><span style='color: #ffffff; font-weight: 600; font-size: 0.87rem;'>AI Optimization</span><span style='{_tag3}'>Card 3</span></summary>"
        "<div style='padding: 10px 14px 14px 14px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.03);'>"
        "<p style='font-size: 0.85rem; color: rgba(255,255,255,0.65); margin: 0 0 10px 0;'>These run after downloading finishes. Each only touches the file types it handles - all others are left unchanged. Click any item to read more.</p>"
        f"<details style='{_row}'><summary style='{_b3}'>Unpack Archives</summary>"
        f"<div style='{_ans3}'>Automatically extracts zip files after downloading so the contents are immediately accessible. Most AI tools cannot read zip files directly.</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>PowerPoint to PDF</summary>"
        f"<div style='{_ans3}'>Converts PowerPoint slide decks to PDF. Most AI tools handle PDF better than PowerPoint. The original PowerPoint file is <b>replaced</b> by the PDF. Requires Microsoft PowerPoint or the free LibreOffice app.</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>Legacy Word Docs to PDF</summary>"
        f"<div style='{_ans3}'>Converts old Word document formats (.doc, .rtf, .odt) to PDF. Modern .docx files are not affected. The original is <b>replaced</b> by the PDF. Requires Microsoft Word or LibreOffice.</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>Excel to PDF &amp; AI Data</summary>"
        f"<div style='{_ans3}'>Converts Excel spreadsheets into two files: a visual PDF (preserves layout, charts, and formatting) and a structured plain text data file optimized for AI. The data file includes a cell coordinate grid (A1, B2...) that matches the PDF, formula annotations showing the math behind calculated cells, and merged cell values. The <b>original spreadsheet is kept</b> alongside both new files. <b>Note:</b> The AI data file is generated only for modern Excel formats (.xlsx, .xlsm). Legacy .xls files are converted to PDF only. Requires Microsoft Excel.</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>Canvas Pages to Plain Text</summary>"
        f"<div style='{_ans3}'>Converts Canvas web pages downloaded via Card 2 into clean plain text files, stripping all web formatting. Makes them easy to paste into or upload to AI tools.</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>Code &amp; Data to .txt</summary>"
        f"<div style='{_ans3}'>Adds a .txt extension to programming files so you can upload them to AI tools that only accept plain text. The file content is completely unchanged - only the filename gets .txt added.</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>Gather Web Links</summary>"
        f"<div style='{_ans3}'>Collects all website shortcut files across your course folder and combines them into a single text file per course. Useful for keeping track of every external link your professor added.</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>Video to Audio</summary>"
        f"<div style='{_ans3}'>Extracts the audio track from video files and saves it as an MP3. Lecture recordings become much smaller (typically 10 to 20 times smaller) and most AI tools support audio upload. The original video is <b>replaced</b> by the MP3.</div></details>"
        "<div style='background-color: rgba(245,158,11,0.1); border-left: 3px solid #f59e0b; padding: 8px 12px; border-radius: 0 4px 4px 0; margin-top: 10px; font-size: 0.85rem;'>"
        f"<span style='color: #fbd38d; font-weight: 600;'>{HELP_ICONS['warning']} Required software:</span> PowerPoint and Word conversions require Microsoft Office or the free LibreOffice app. Excel PDF conversion requires Microsoft Excel; AI data extraction works for .xlsx/.xlsm only (not legacy .xls). If the required software is not installed, that step is silently skipped and your original file is kept."
        "</div>"
        "</div></details>"

        # ── Output Folder ─────────────────────────────────────────────────────
        "<hr>"
        f"<div style='font-weight: 700; color: #ffffff; font-size: 0.95rem; margin-bottom: 6px;'>{HELP_ICONS['folder']} Output Folder</div>"
        "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.8);'>"
        "The folder where all downloaded courses are saved. Each course automatically gets its own named subfolder inside it. Click <b>Select Folder</b> to change the destination path."
        "</div>"
        "<hr>"

        # ── Presets ───────────────────────────────────────────────────────────
        f"<div style='font-weight: 700; color: #ffffff; font-size: 0.95rem; margin-bottom: 8px;'>{HELP_ICONS['save']} Download Settings Presets</div>"
        "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.8); margin-bottom: 10px;'>"
        "A Preset saves your entire Card 1, 2, and 3 configuration under a name you choose. Once saved, you can restore your full setup in one click instead of re-configuring everything from scratch."
        "</div>"
        "<div style='display: flex; gap: 10px; margin-bottom: 10px;'>"
        "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 7px; padding: 11px 13px;'>"
        f"<div style='font-weight: 700; color: #e2e8f0; font-size: 0.85rem; margin-bottom: 7px;'>{HELP_ICONS['save']} Saving a preset</div>"
        "<div style='color: rgba(255,255,255,0.75); font-size: 0.85rem; line-height: 1.6;'>"
        "Configure Cards 1, 2 &amp; 3, then click <b style='color: #e2e8f0;'>Save Preset</b> in the top right. Give it a name - like <em>AI Ready</em> - and click Save. Settings are stored locally on your computer."
        "</div>"
        "</div>"
        "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 7px; padding: 11px 13px;'>"
        f"<div style='font-weight: 700; color: #e2e8f0; font-size: 0.85rem; margin-bottom: 7px;'>{HELP_ICONS['folder_open']} Loading a preset</div>"
        "<div style='color: rgba(255,255,255,0.75); font-size: 0.85rem; line-height: 1.6;'>"
        "Click the <b style='color: #e2e8f0;'>Presets</b> button in the top right. The Preset Hub opens - click any preset name to instantly apply its settings to all three cards."
        "</div>"
        "</div>"
        "</div>"
        "<div style='background: rgba(255,255,255,0.04); border-radius: 7px; padding: 10px 13px;'>"
        "<div style='font-size: 0.73rem; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; color: rgba(255,255,255,0.4); margin-bottom: 7px;'>Example presets to get you started</div>"
        "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.75); line-height: 1.7;'>"
        "&#8226; <b style='color: #e2e8f0;'>AI Ready</b> - Card 3 fully enabled. Ideal for courses you feed to NotebookLM or ChatGPT.<br>"
        "&#8226; <b style='color: #e2e8f0;'>Quick Backup</b> - All Files selected, no conversions. Fast offline copy with no post-processing.<br>"
        "&#8226; <b style='color: #e2e8f0;'>Study Files</b> - Slides &amp; PDFs only, PowerPoint and Word converted to PDF."
        "</div>"
        "</div>"
        "<hr>"

        # ── FAQ ───────────────────────────────────────────────────────────────
        "<details style='margin-top: 4px;'>"
        f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 0.95rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['question']} Frequently Asked Questions</summary>"
        "<div style='margin-top: 6px; padding-left: 12px;'>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is the difference between All Files and Slides &amp; PDFs?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "<b>All Files</b> grabs everything your professor uploaded - PDFs, slides, Word documents, images, videos, spreadsheets, zip archives, and more. <b>Slides &amp; PDFs</b> only grabs lecture slides and PDF files. Use the filtered option if you want to skip large videos or data sets."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What does With Subfolders actually look like on my computer?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Each course gets a folder, and inside it, Canvas modules become subfolders. For example: <em>Downloads / CHEM101 / Week 3 - Thermodynamics / lecture.pdf</em>. With All in One Folder: <em>Downloads / CHEM101 / lecture.pdf</em> - every file at the same level with no subfolders."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is Canvas Content and why would I want to download it?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Canvas Content covers items that only exist as web pages inside Canvas - assignment instructions, announcements, discussion threads, quiz questions. The app converts these into local documents you can read offline or upload to AI tools. Your regular course files are always downloaded regardless of Card 2 settings."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>If I enable PowerPoint to PDF, does the original file get deleted?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Yes - the original PowerPoint file is replaced by the PDF to avoid duplicates. The same applies to Legacy Word to PDF and Video to Audio. <b>Exception:</b> Excel keeps the original spreadsheet alongside the PDF and the AI data file - you end up with three files per spreadsheet. If you need to keep originals for other converters, skip those conversions or make a backup first."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What does Submissions (Results) save, and will my professor know?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "It saves the feedback and grades you received on your own submitted assignments - professor comments, rubric scores, and your grade per assignment. This is your personal data - your professor is not notified."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Do I have to re-download everything every time, or can I just get new files?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Use <b>Sync Mode</b> (available from the navigation sidebar) for that. Download Mode always downloads a fresh copy of everything. Sync Mode tracks what is already on your computer and only fetches files that are new or updated since your last sync."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Why would I use Video to Audio instead of keeping the full video file?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Lecture videos are often hundreds of megabytes each, and most AI tools like NotebookLM do not support video uploads. Converting to audio gives a much smaller file (typically 10 to 20 times smaller) you can upload to AI tools for summaries or questions. If you want to watch the recording, leave this disabled."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Do the AI conversions in Card 3 work on all computers?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "It depends on the conversion. PowerPoint and Word conversions require <b>Microsoft Office</b> or the free <b>LibreOffice</b> app. Unpacking archives, converting Canvas pages, adding .txt to code files, and gathering web links all work on any computer with no extra software."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is a Preset and should I use one?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        f"A Preset saves your current settings (Cards 1, 2, and 3) under a name so you can reload them instantly next time. Click <b>{HELP_ICONS['save']} Save Preset</b> after configuring, and the <b>Presets</b> button to open the Preset Hub and apply a saved one."
        "</div></details>"
        "</div>"
        "</details>"
    )

    with _hdr_left:
        # Title + Help Tag in a Snug Flex Row
        st.html("""
            <style>
            /* Force the column container to justify left and have a tight gap */
            div.st-key-title_help_row [data-testid="stHorizontalBlock"] {
                display: flex !important;
                flex-direction: row !important;
                align-items: center !important;
                gap: 0px !important;
                justify-content: flex-start !important;
            }
            /* Force columns to hug their content instead of using percentages */
            div.st-key-title_help_row [data-testid="column"],
            div.st-key-title_help_row [data-testid="stColumn"] {
                width: auto !important;
                flex: 0 0 auto !important;
                min-width: 0px !important;
                padding: 0 !important;
            }
            /* Move it LEFT by ensuring the H2 has no trailing margin */
            div.st-key-title_help_row h2 {
                margin-right: 0 !important;
                padding-right: 0 !important;
            }
            /* Move it DOWN to align its bottom with the H2 baseline */
            div.st-key-title_help_row div[class*="st-key-download_settings_explainer_help_btn"] {
                margin-bottom: -20px !important;
                margin-top: 10px !important;
                margin-left: 0 !important;
            }
            </style>
        """)
        with st.container(key="title_help_row"):
            _c1, _c2 = st.columns([1, 10]) # Ratio doesn't matter much with width:auto
            with _c1:
                st.markdown("<h2 style='margin: 0; white-space: nowrap;'>Download Settings</h2>", unsafe_allow_html=True)
            with _c2:
                render_help_card(
                    key_prefix="download_settings",
                    title=help_title,
                    text_html=help_text,
                    mode="button"
                )


    with _hdr_right:
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        # Hoist Base64 icon CSS for the Presets button BEFORE it renders (Static Hoisting)
        _b64_preset_btn_icon = get_base64_image("assets/icon_preset_user.png")
        if _b64_preset_btn_icon:
            st.html(f"""<style>
            div.st-key-btn_presets_hub button div[data-testid="stMarkdownContainer"] p {{
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
            }}
            div.st-key-btn_presets_hub button div[data-testid="stMarkdownContainer"] p::before {{
                content: "";
                display: inline-block;
                width: 20px;
                height: 20px;
                min-width: 20px;
                margin-right: 6px;
                background-image: url('data:image/png;base64,{_b64_preset_btn_icon}');
                background-size: contain;
                background-repeat: no-repeat;
            }}
            </style>""")
        _pb1, _pb2 = st.columns([3, 5], gap="small")
        with _pb1:
            if st.button("💾 Save Preset", key="btn_save_config", use_container_width=True):
                _save_config_dialog()
        with _pb2:
            if st.button("Presets", key="btn_presets_hub", use_container_width=True):
                _presets_hub_dialog()

    # Help Card Expansion (renders below the header row if open)
    render_help_card(
        key_prefix="download_settings",
        title=help_title,
        text_html=help_text,
        mode="card"
    )

    # NOTE: Card 1 dynamic CSS (active include button state) is injected
    # inside `_card1_fragment` so it re-emits on Card 1 fragment-only reruns.

    step2_container = st.empty()
    with step2_container.container():
        # HOISTED CALLBACKS
        def _toggle_secondary_sub(target_key):
            st.session_state[target_key] = not st.session_state.get(target_key, False)
            active = sum(st.session_state.get(k, False) for k in SECONDARY_CONTENT_KEYS)
            st.session_state['dl_secondary_master'] = (active == TOTAL_SECONDARY_SUBS)

        def _toggle_secondary_master():
            new_state = not st.session_state.get('dl_secondary_master', False)
            st.session_state['dl_secondary_master'] = new_state
            for k in SECONDARY_CONTENT_KEYS:
                st.session_state[k] = new_state

        def _set_isolate_secondary(is_subfolders: bool):
            """Sets the secondary content organization mode."""
            st.session_state['dl_isolate_secondary'] = is_subfolders

        def _get_sec_org_segmented_css():
            b64_inline = _load_b64("assets/icon_sec_inline.png")
            b64_sub = _load_b64("assets/icon_sec_subfolders.png")

            is_sub = st.session_state.get('dl_isolate_secondary', False)
            active_key = "subfolders" if is_sub else "inline"

            return f"""
            <style>
            div[class*="st-key-sec_org_segmented_wrapper"] {{
                background-color: rgba(0, 0, 0, 0.25) !important;
                border: 1px solid rgba(255, 255, 255, 0.05) !important;
                border-radius: 12px !important;
                padding: 4px !important;
                margin-top: 5px !important;
            }}
            div[class*="st-key-sec_org_segmented_wrapper"] [data-testid="stHorizontalBlock"] {{
                gap: 4px !important;
            }}
            div[class*="st-key-sec_org_segmented_wrapper"] [data-testid="column"] > div, 
            div[class*="st-key-sec_org_segmented_wrapper"] div[data-testid="stButton"], 
            div[class*="st-key-sec_org_segmented_wrapper"] button {{
                height: 100% !important;
            }}
            div[class*="st-key-btn_sec_org_"] button {{
                background-color: transparent !important;
                border: 1px solid transparent !important;
                display: flex !important;
                flex-direction: column !important;
                padding: 12px 12px 12px 52px !important;
                border-radius: 8px !important;
                color: #a0a0a0 !important;
                opacity: 0.75 !important;
                transition: opacity 0.2s ease, background-color 0.2s ease, filter 0.2s ease, color 0.2s ease !important;
                position: relative !important;
                min-height: 62px !important;
            }}
            /* Nuke Streamlit's center alignment for the segmented control */
            div[class*="st-key-btn_sec_org_"] button > div,
            div[class*="st-key-btn_sec_org_"] button div[data-testid="stMarkdownContainer"] {{
                width: 100% !important;
                display: flex !important;
                justify-content: flex-start !important;
                text-align: left !important;
            }}
            div[class*="st-key-btn_sec_org_"] button p {{
                text-align: left !important;
                width: 100% !important;
                margin: 0 !important;
                font-size: 0.95rem !important;
                font-weight: 600 !important;
                line-height: 1.2 !important;
                color: inherit !important;
            }}
            div[class*="st-key-btn_sec_org_"] button {{
                background-size: 28px !important;
                background-repeat: no-repeat !important;
                background-position: 12px center !important;
            }}
            div.st-key-btn_sec_org_inline button {{ background-image: url('data:image/png;base64,{b64_inline}') !important; }}
            div.st-key-btn_sec_org_subfolders button {{ background-image: url('data:image/png;base64,{b64_sub}') !important; }}

            div[class*="st-key-btn_sec_org_"] button:hover {{
                background-color: rgba(255, 255, 255, 0.05) !important;
                border-color: #68d4a3 !important;
                opacity: 1 !important;
                color: #ffffff !important;
            }}

            /* Disabled State Overrides */
            div[class*="st-key-btn_sec_org_"] button[disabled] {{
                opacity: 0.4 !important;
                pointer-events: none !important;
                filter: grayscale(100%) !important;
            }}

            div.st-key-btn_sec_org_inline button::after {{ content: "Place Canvas Content alongside your other downloaded files." !important; }}
            div.st-key-btn_sec_org_subfolders button::after {{ content: "Create folders for each type (e.g. Assignments/, Quizzes/)" !important; }}
            div[class*="st-key-btn_sec_org_"] button::after {{
                text-align: left !important;
                width: 100% !important;
                display: block !important;
                font-size: 0.75rem !important;
                color: #a0a0a0 !important;
                margin-top: 2px !important;
                font-weight: 400 !important;
                white-space: normal !important;
                line-height: 1.2 !important;
            }}
            div.st-key-btn_sec_org_{active_key} button {{
                background-color: rgba(104, 212, 163, 0.15) !important; /* Muted Green */
                border: 1px solid rgba(104, 212, 163, 0.3) !important;
                box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important; /* Slight drop shadow for the pill */
                color: #ffffff !important;
                opacity: 1 !important;
            }}
            /* Protect Active Green Pill from Grey Hover Override */
            div.st-key-btn_sec_org_{active_key} button:hover {{
                background-color: rgba(104, 212, 163, 0.15) !important;
                border: 1px solid rgba(104, 212, 163, 0.3) !important;
                opacity: 1 !important;
            }}
            div[class*="st-key-btn_sec_org_"] button:hover::before {{ border-color: #68d4a3 !important; }}
            div.st-key-btn_sec_org_{active_key} button:hover::before {{ border-color: transparent !important; }}
            div.st-key-btn_sec_org_{active_key} button p {{ color: #ffffff !important; }}
            div.st-key-btn_sec_org_{active_key} button::before {{ 
                border: none !important;
                background-color: transparent !important;
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='10' fill='none' stroke='%2368d4a3' stroke-width='3'/%3E%3Ccircle cx='12' cy='12' r='5' fill='%2368d4a3'/%3E%3C/svg%3E") !important;
            }}
            </style>
            """

        notebook_sub_keys = NOTEBOOK_SUB_KEYS
        TOTAL_NOTEBOOK_SUBS = len(notebook_sub_keys)

        def _toggle_conv_master():
            # If master is currently True (or all subs are True), turn everything off. Otherwise, turn all on.
            current_master = st.session_state.get('notebooklm_master', False)
            new_state = not current_master
            st.session_state['notebooklm_master'] = new_state
            for k in notebook_sub_keys:
                st.session_state[k] = new_state

        def _toggle_conv_sub(key):
            # Flip the specific sub-toggle
            st.session_state[key] = not st.session_state.get(key, False)
            # Re-evaluate the master toggle based on the sum of active subs
            active_count = sum(1 for k in notebook_sub_keys if st.session_state.get(k, False))
            st.session_state['notebooklm_master'] = (active_count == TOTAL_NOTEBOOK_SUBS)

        # HOISTED CSS
        st.html("""
        <style>
        /* Tree-view styling for secondary content sub-checkboxes */
        .st-key-dl_assignments, .st-key-dl_syllabus, .st-key-dl_announcements,
        .st-key-dl_discussions, .st-key-dl_quizzes, .st-key-dl_rubrics,
        .st-key-dl_submissions {
            margin-left: 28px !important;
            padding-left: 15px !important;
            border-left: 2px solid """ + theme.BG_CARD_HOVER + """ !important;
            margin-top: -12px !important;
            padding-top: 4px !important;
            padding-bottom: 4px !important;
        }
        .st-key-dl_assignments { margin-top: 0px !important; padding-top: 8px !important; }
        .st-key-dl_submissions { margin-bottom: 10px !important; padding-bottom: 8px !important; }


        </style>
        """)

        # Card elevation CSS - Version-Agnostic Target for Streamlit 1.51+
        # NOTE: The conditional Card 2 flex rule (depends on `card2_expanded`)
        # is re-injected inside `_card2_fragment` so the height-sync updates
        # when only Card 2 reruns.
        st.html("""
    <style>
    /* 1. Target via the explicit Streamlit Keys (Most Reliable) */
    div[class*="st-key-card_core_files"],
    div[class*="st-key-card_native_content"],
    div[class*="st-key-card_ai_engine"],

    /* 2. Target via modern Streamlit 1.51+ Container ID + Trojan Class */
    div[data-testid="stContainer"]:has(.step-2-card-target) {
        background-color: rgba(255, 255, 255, 0.04) !important;
        border-radius: 8px !important;
    }

    /* === Card 1 ↔ Card 2: Height Synchronization ===
       Both cards get flex:1 unconditionally so the headers stay aligned
       whether Card 2 is collapsed or expanded. (Earlier the Card 2 rule
       was conditional on `card2_expanded`, which made the Canvas Content
       header drift upward when Card 2 collapsed.) */
    div[data-testid="stLayoutWrapper"]:has(> [class*="st-key-card_core_files"]),
    div[data-testid="stLayoutWrapper"]:has(> [class*="st-key-card_native_content"]) {
        flex: 1 !important;
    }
    div[class*="st-key-card_core_files"],
    div[class*="st-key-card_native_content"] {
        flex: 1 !important;
    }

    /* Vertical alignment shim - Card 2's trojan div has a more aggressive
       negative margin-top (-25px) than Card 1's (-10px), which makes its
       outer container collapse 15px higher up. Use padding-top (not margin-top)
       so Card 2's flex box still fills the full column height — margin would
       shrink the box and leave Card 2's bottom edge 15px short of Card 1's. */
    div[class*="st-key-card_native_content"] {
        margin-top: 15px !important;
    }

    </style>
    """)

        col1, col2 = st.columns([3, 5], gap="medium")

        # --- COLUMN 1: Organization & Include Files ---
        @st.fragment
        def _render_card1():
            # Card 1 dynamic CSS (active include + global button base).
            # Lives inside the fragment so the active-state CSS re-injects on
            # Card 1 fragment-only reruns (toggling include keeps the rest of
            # the page from rerunning, which is the whole point of fragments).
            b64_icon_all = _load_b64("assets/icon_all_files.png")
            b64_icon_study = _load_b64("assets/icon_study_files.png")
            active_include = st.session_state.get('file_filter', 'all')
            active_include_key = "all" if active_include == 'all' else "study"
            st.markdown(f'''
            <style>
            /* GLOBAL CHECKBOX PSEUDO-ELEMENT BASE */
            div[class*="st-key-btn_"] button::before {{
                content: "" !important;
                position: absolute !important;
                top: 10px !important;
                right: 10px !important;
                width: 16px !important;
                height: 16px !important;
                border: 2px solid rgba(255, 255, 255, 0.2) !important;
                border-radius: 4px !important;
                background-color: transparent !important;
                background-size: contain !important;
                background-repeat: no-repeat !important;
                background-position: center !important;
                transition: all 0.2s ease-in-out !important;
                box-sizing: border-box !important;
            }}
            /* Hide Checkboxes on Action Buttons & Master Toggles */
            div.st-key-btn_save_config button::before,
            div.st-key-btn_presets_hub button::before,
            div.st-key-btn_dl_secondary_master button::before,
            div.st-key-btn_convert_master button::before,
            div.st-key-btn_preset_hub_close button::before {{
                display: none !important;
            }}
            /* Circular Mutually Exclusive Toggles */
            div[class*="st-key-btn_include_"] button::before,
            div[class*="st-key-btn_org_"] button::before,
            div[class*="st-key-btn_sec_org_"] button::before {{
                border-radius: 50% !important;
            }}
            /* Apply generic buffer so text avoids the absolute checkboxes */
            div[class*="st-key-btn_"] button p,
            div[class*="st-key-btn_"] button::after {{
                padding-right: 16px !important;
                box-sizing: border-box !important;
            }}
            /* Exclude Organization Master Buttons from Text Buffer */
            div.st-key-btn_org_all button p, div.st-key-btn_org_all button::after,
            div.st-key-btn_org_modules button p, div.st-key-btn_org_modules button::after {{
                padding-right: 0px !important;
            }}

            /* 1. Outer Container & Crush horizontal gap */
            div[class*="st-key-include_files_segmented_wrapper"] {{
                margin-top: 5px !important;
            }}

            /* 2. Stretch column wrappers for dynamic height */
            div[class*="st-key-include_files_segmented_wrapper"] div[data-testid="column"] > div,
            div[class*="st-key-include_files_segmented_wrapper"] div[data-testid="stButton"] {{
                height: 100% !important;
            }}

            /* 3. Base Button: Flex Column + Relative Position */
            div[class*="st-key-btn_include_"] button {{
                position: relative !important;
                min-height: 150px !important;
                background-color: transparent !important;
                background-repeat: no-repeat !important;
                background-position: center 18px !important;
                background-size: 55px !important;
                padding-top: 85px !important;
                border: 1px solid rgba(255, 255, 255, 0.15) !important;
                border-radius: 8px !important;
                display: flex !important;
                flex-direction: column !important;
                align-items: center !important;
                justify-content: flex-start !important;
                transition: all 0.2s ease-in-out !important;
                opacity: 0.75 !important;
                color: #a0a0a0 !important;
            }}

            /* 4. Primary Title Styling (The native button label) */
            div[class*="st-key-btn_include_"] button p {{
                font-size: 1.1rem !important;
                font-weight: 600 !important;
                margin: 0 !important;
                margin-bottom: 0px !important;
                line-height: 1.2 !important;
                color: inherit !important;
            }}

            div[class*="st-key-btn_include_"] button::after {{
                margin-bottom: 0px !important;
                padding-bottom: 0px !important;
            }}

            /* 5. Geometry lockdown for radio pseudo-element on Card 1 */
            div[class*="st-key-btn_include_"] button::before {{
                top: 16px !important;
                right: 16px !important;
                box-sizing: border-box !important;
            }}

            /* Icon Layer (native background) */
            div.st-key-btn_include_all button {{ background-image: url('data:image/png;base64,{b64_icon_all}') !important; }}
            div.st-key-btn_include_study button {{ background-image: url('data:image/png;base64,{b64_icon_study}') !important; }}

            /* 6. Descriptions (::after) */
            div.st-key-btn_include_all button::after {{
                content: "Includes everything from the Canvas folder" !important;
                font-size: 0.85rem !important;
                line-height: 1.1 !important;
                color: #a0a0a0 !important;
                margin-top: -1px !important;
                font-weight: 400 !important;
            }}
            div.st-key-btn_include_study button::after {{
                content: "Download PDFs & PowerPoints only" !important;
                font-size: 0.85rem !important;
                line-height: 1.1 !important;
                color: #a0a0a0 !important;
                margin-top: -1px !important;
                font-weight: 400 !important;
            }}

            /* 6.5 Hover State (Inactive Buttons) */
            div[class*="st-key-btn_include_"] button:hover {{
                border-color: #3fd9ff !important;
                background-color: rgba(255, 255, 255, 0.02) !important;
                box-shadow: inset 0 0 0 1px #3fd9ff, 0 4px 12px rgba(0, 0, 0, 0.2) !important;
                opacity: 1 !important;
                color: #ffffff !important;
            }}

            /* 7. Active State Logic */
            div.st-key-btn_include_{active_include_key} button {{
                border: 1px solid #3fd9ff !important;
                background-color: rgba(56, 189, 248, 0.05) !important;
                box-shadow: inset 0 0 0 1px #3fd9ff, 0 4px 12px rgba(0, 0, 0, 0.2) !important;
                opacity: 1 !important;
                color: #ffffff !important;
            }}
            /* Protect Active Blue Pill from Grey Hover Override */
            div.st-key-btn_include_{active_include_key} button:hover {{
                border: 1px solid #3fd9ff !important;
                background-color: rgba(56, 189, 248, 0.08) !important;
                box-shadow: inset 0 0 0 1px #3fd9ff, 0 4px 12px rgba(0, 0, 0, 0.2) !important;
                opacity: 1 !important;
                color: #ffffff !important;
            }}

            div[class*="st-key-btn_include_"] button:hover::before {{ border-color: #3fd9ff !important; }}
            div.st-key-btn_include_{active_include_key} button:hover::before {{ border-color: transparent !important; }}
            div.st-key-btn_include_{active_include_key} button::before {{
                border: none !important;
                background-color: transparent !important;
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='10' fill='none' stroke='%233fd9ff' stroke-width='3'/%3E%3Ccircle cx='12' cy='12' r='5' fill='%233fd9ff'/%3E%3C/svg%3E") !important;
            }}
            </style>
            ''', unsafe_allow_html=True)

            with st.container(border=True, key="card_core_files"):
                b64_wf1 = _load_b64("assets/icon_workflow_1.png")
                st.markdown(f"""<div class='step-2-card-target' style='position: relative; margin-top: -10px; margin-bottom: 12px;'>
    <img src='data:image/png;base64,{b64_wf1}' style='position: absolute; width: 36px; height: 36px; top: -24px; left: -34px; z-index: 10;'>
    <div style='padding-left: 0px;'>
    <h3 style='margin: 0; line-height: 1.2;'>Core Course Files &amp; Structure</h3>
    </div>
    </div>
    <p style='font-size: 0.95rem; color: #e2e8f0; margin-top: -20px; margin-bottom: 0px;'>Select what to download and how to organize it on your computer.</p>
    <hr style='border: none; border-top: 1px solid rgba(255, 255, 255, 0.15); margin-top: 15px; margin-bottom: 15px;'>""", unsafe_allow_html=True)

                # 1. Include Files Block (Segmented Control)
                def update_include_state(mode):
                    st.session_state['file_filter'] = mode

                with st.container(key="card1_include_section"):
                    st.markdown(
                        "<p style='font-size: 0.9rem; font-weight: 600; color: #cbd5e1; margin-top: 0px; margin-bottom: 0px;'>Choose which files to download:</p>", 
                        unsafe_allow_html=True
                    )
                    with st.container(key="include_files_segmented_wrapper"):
                        inc_left, inc_right = st.columns(2, gap="small")
                        with inc_left:
                            st.button("All Files (default)", key="btn_include_all", use_container_width=True, on_click=update_include_state, args=("all",))
                        with inc_right:
                            st.button("Slides & PDFs", key="btn_include_study", use_container_width=True, on_click=update_include_state, args=("study",))

                st.html("<div style='padding-bottom: 0px;'></div>")

                # 2. Organization Block (Large Buttons)
                def update_org_state(mode):
                    st.session_state['download_mode'] = 'modules' if mode == 'subfolders' else mode

                st.markdown(
                    "<p style='font-size: 0.9rem; font-weight: 600; color: #cbd5e1; margin-top: 0px; margin-bottom: 0px;'>Choose how files should be organized:</p>", 
                    unsafe_allow_html=True
                )

                btn_left, btn_right = st.columns(2)
                b64_subfolders = get_base64_image("assets/icon_subfolders.png")
                b64_flat = get_base64_image("assets/icon_flat.png")

                with btn_left:
                    st.button("With Subfolders", key="btn_org_subfolders", use_container_width=True, on_click=update_org_state, args=("subfolders",))

                with btn_right:
                    st.button("All in One Folder", key="btn_org_flat", use_container_width=True, on_click=update_org_state, args=("flat",))

                active_mode = st.session_state.get('download_mode', 'modules')
                active_btn_key = "subfolders" if active_mode == 'modules' else "flat"

                try:
                    border_color = theme.PRIMARY_BLUE if hasattr(theme, 'PRIMARY_BLUE') else theme.ACCENT_LINK
                except Exception:
                    border_color = "#007bff"

                st.markdown(f'''
                <style>
                /* Base Card Styling for BOTH buttons */
                div[class*="st-key-btn_org_"] button {{
                    position: relative !important;
                    min-height: 150px !important;
                    background-color: transparent !important;
                    background-repeat: no-repeat !important;
                    background-position: center 18px !important;
                    background-size: 55px !important;
                    padding-top: 85px !important;
                    border: 1px solid rgba(255, 255, 255, 0.15) !important;
                    border-radius: 8px !important;
                    display: flex !important;
                    flex-direction: column !important;
                    align-items: center !important;
                    justify-content: flex-start !important;
                    transition: all 0.2s ease-in-out !important;
                    opacity: 0.75 !important;
                    color: #a0a0a0 !important;
                }}

                /* Primary Title Styling (The native button label) */
                div[class*="st-key-btn_org_"] button p {{
                    font-size: 1.1rem !important;
                    font-weight: 600 !important;
                    margin: 0 !important;
                    margin-bottom: 0px !important;
                    line-height: 1.2 !important;
                    color: inherit !important;
                }}

                div[class*="st-key-btn_org_"] button::after {{
                    margin-bottom: 0px !important;
                    padding-bottom: 0px !important;
                }}

                /* Geometry lockdown for radio pseudo-element on Card 1 */
                div[class*="st-key-btn_org_"] button::before {{
                    top: 16px !important;
                    right: 16px !important;
                    box-sizing: border-box !important;
                }}

                /* Hover State */
                div[class*="st-key-btn_org_"] button:hover {{
                    border-color: #3fd9ff !important;
                    background-color: rgba(255, 255, 255, 0.02) !important;
                    box-shadow: inset 0 0 0 1px #3fd9ff, 0 4px 12px rgba(0, 0, 0, 0.2) !important;
                    opacity: 1 !important;
                    color: #ffffff !important;
                }}

                /* ----- SUBFOLDERS SPECIFIC ----- */
                div.st-key-btn_org_subfolders button {{
                    background-image: url('data:image/png;base64,{b64_subfolders}') !important;
                }}
                div.st-key-btn_org_subfolders button::after {{
                    content: "Organize files exactly as they appear in Canvas." !important;
                    font-size: 0.85rem !important;
                    line-height: 1.1 !important;
                    color: #a0a0a0 !important;
                    margin-top: -1px !important;
                    font-weight: 400 !important;
                }}

                /* ----- FLAT SPECIFIC ----- */
                div.st-key-btn_org_flat button {{
                    background-image: url('data:image/png;base64,{b64_flat}') !important;
                }}
                div.st-key-btn_org_flat button::after {{
                    content: "Place all files together in the course folder." !important;
                    font-size: 0.85rem !important;
                    line-height: 1.1 !important;
                    color: #a0a0a0 !important;
                    margin-top: -1px !important;
                    font-weight: 400 !important;
                }}

                /* Active State Highlight */
                div.st-key-btn_org_{active_btn_key} button {{
                    border: 1px solid {border_color} !important;
                    background-color: rgba(56, 189, 248, 0.05) !important;
                    box-shadow: inset 0 0 0 1px {border_color}, 0 4px 12px rgba(0, 0, 0, 0.2) !important;
                    opacity: 1 !important;
                    color: #ffffff !important;
                }}
                /* Protect Active State from generic Hover Overrides */
                div.st-key-btn_org_{active_btn_key} button:hover {{
                    border: 1px solid {border_color} !important;
                    background-color: rgba(56, 189, 248, 0.08) !important;
                    box-shadow: inset 0 0 0 1px {border_color}, 0 4px 12px rgba(0, 0, 0, 0.2) !important;
                    opacity: 1 !important;
                    color: #ffffff !important;
                }}
                div[class*="st-key-btn_org_"] button:hover::before {{ border-color: #3fd9ff !important; }}
                div.st-key-btn_org_{active_btn_key} button:hover::before {{ border-color: transparent !important; }}
                div.st-key-btn_org_{active_btn_key} button::before {{
                    border: none !important;
                    background-color: transparent !important;
                    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='10' fill='none' stroke='%233fd9ff' stroke-width='3'/%3E%3Ccircle cx='12' cy='12' r='5' fill='%233fd9ff'/%3E%3C/svg%3E") !important;
                }}
                </style>
                ''', unsafe_allow_html=True)

        with col1:
            _render_card1()

        # --- COLUMN 2: Additional Course Content ---
        @st.fragment
        def _render_card2():
            with st.container(border=True, key="card_native_content"):
                m_active = st.session_state.get('dl_secondary_master', False)
                _sec_active = sum(1 for k in SECONDARY_CONTENT_KEYS if st.session_state.get(k, False))
                has_active_items2 = _sec_active > 0 or m_active

                _c2_is_exp = st.session_state.get('card2_expanded', False)
                c2_tag_bg = "rgba(104, 212, 163, 0.15)"
                c2_tag_col = "#68d4a3"
                c2_tag_bor = "1px solid transparent"

                if _sec_active == 0:
                    c2_tag_bg = "rgba(255, 255, 255, 0.05)"
                    c2_tag_col = "#94a3b8"
                    c2_tag_bor = "1px solid rgba(255, 255, 255, 0.1)"
                    if not _c2_is_exp:
                        dynamic_tag = "<strong>OFF</strong>"
                    else:
                        dynamic_tag = "<strong>OFF</strong>  |  None selected"
                elif _sec_active == TOTAL_SECONDARY_SUBS:
                    dynamic_tag = "<strong>ON</strong>  |  All selected"
                else:
                    dynamic_tag = f"<strong>ON</strong>  |  {_sec_active} selected"

                def toggle_card2():
                    st.session_state['card2_expanded'] = not st.session_state.get('card2_expanded', False)

                c2_exp = st.session_state.get('card2_expanded', False)
                chr_svg = _get_chevron_base64(c2_exp)
                b64_wf2 = _load_b64("assets/icon_workflow_2.png")
                c_filter = "grayscale(0%) brightness(100%)" if has_active_items2 else "grayscale(100%) brightness(60%)"

                # Compute chevron colors BEFORE the button renders
                c2_base_color = "#94a3b8" if c2_exp else "#64748b"
                c2_hover_color = "#cbd5e1" if c2_exp else "#94a3b8"

                # THE FIX: Inject chevron CSS BEFORE the button to prevent ghost flash
                st.markdown(f'''<style>
                div.st-key-header_wrap_card2 {{
                    display: flex !important;
                    flex-direction: row !important;
                    align-items: center !important;
                    justify-content: flex-start !important;
                    gap: 12px !important;
                    padding-top: 0px !important;
                    padding-bottom: 0px !important;
                    margin-top: -35px !important;
                }}
                div.st-key-header_wrap_card2 > div[data-testid="element-container"] {{
                    margin-bottom: 0px !important;
                }}
                div.st-key-header_wrap_card2 > div[data-testid="element-container"]:nth-child(1) {{
                    width: 24px !important;
                    min-width: 24px !important;
                    flex: 0 0 24px !important;
                }}
                div.st-key-header_wrap_card2 > div[data-testid="element-container"]:nth-child(2) {{
                    flex: 1 1 auto !important;
                    width: 100% !important;
                }}
                /* Kill focus rings on the parent wrappers */
                div.st-key-toggle_card2 div[data-testid="stButton"]:focus-within,
                div.st-key-toggle_card2 div[data-testid="stBaseButton-secondary"]:focus-within {{
                    box-shadow: none !important;
                    outline: none !important;
                    background: transparent !important;
                }}
                /* Kill focus rings on the button itself during focus shifts */
                div.st-key-toggle_card2 button:focus-visible,
                div.st-key-toggle_card2 button:focus:not(:active),
                div.st-key-toggle_card2 button:focus {{
                    box-shadow: none !important;
                    outline: none !important;
                    border: none !important;
                    background-color: {c2_base_color} !important; 
                }}
                /* Ensure the inner markdown div remains completely hidden */
                div.st-key-toggle_card2 button > div {{
                    display: none !important;
                }}
                /* BASE MASK STATE */
                div.st-key-toggle_card2 button {{
                    all: unset !important;
                    display: inline-block !important;
                    cursor: pointer !important;
                    width: 24px !important;
                    height: 24px !important;
                    position: relative !important;
                    top: 5px !important;
                    -webkit-mask-image: {chr_svg} !important;
                    -webkit-mask-size: contain !important;
                    -webkit-mask-repeat: no-repeat !important;
                    -webkit-mask-position: center !important;
                    background-color: {c2_base_color} !important;
                    transition: background-color 0.2s ease !important;
                    box-shadow: none !important;
                    outline: none !important;
                    border: none !important;
                    -webkit-tap-highlight-color: transparent !important;
                }}
                /* HOVER STATE */
                div.st-key-toggle_card2 button:hover {{ background-color: {c2_hover_color} !important; box-shadow: none !important; }}
                /* ACTIVE KILLER */
                div.st-key-toggle_card2 button:active {{
                    box-shadow: none !important;
                    outline: none !important;
                    border: none !important;
                    transform: none !important;
                }}
                /* RERUN LOCK */
                div.st-key-toggle_card2 button[disabled] {{
                    box-shadow: none !important;
                    outline: none !important;
                    border: none !important;
                    background-color: {c2_base_color} !important;
                    opacity: 0.8 !important;
                }}
                </style>''', unsafe_allow_html=True)

                st.markdown(f"<div class='step-2-card-target' style='position: relative; margin-top: -25px; margin-bottom: 0px;'><img src='data:image/png;base64,{b64_wf2}' style='position: absolute; width: 36px; height: 36px; top: -24px; left: -34px; z-index: 10; filter: {c_filter}; transition: all 0.2s ease;' /></div>", unsafe_allow_html=True)

                with st.container(key="header_wrap_card2"):
                    st.button("\u200B", key="toggle_card2", on_click=toggle_card2)
                    st.markdown(f"""<div style='display: flex; align-items: center; justify-content: space-between; padding-right: 10px; width: 100%; transform: translateY(-5px);'><h3 style='margin: 0px !important; padding: 0px !important; line-height: 1 !important;'>Canvas Content <span style='color: #64748b; font-size: 0.8em; font-weight: normal;'>(Optional)</span></h3><span style='background-color: {c2_tag_bg}; color: {c2_tag_col}; border: {c2_tag_bor}; font-size: 0.8rem; padding: 2px 12px; border-radius: 15px; font-weight: 600; transition: all 0.2s ease;'>{dynamic_tag}</span></div>""", unsafe_allow_html=True)

                css_blocks = []

                # Button data
                button_defs = [
                    ('dl_assignments', 'Assignments', 'Includes assignment descriptions and any attached files.', 'icon_assignments.png'),
                    ('dl_syllabus', 'Syllabus', 'Save the course syllabus page as HTML.', 'icon_syllabus.png'),
                    ('dl_announcements', 'Announcements', 'Save course announcements and any attached files.', 'icon_announcements.png'),
                    ('dl_discussions', 'Discussions', 'Save discussion threads as HTML.', 'icon_discussions.png'),
                    ('dl_quizzes', 'Quizzes', 'Save quiz questions and answers as HTML.', 'icon_quizzes.png'),
                    ('dl_rubrics', 'Rubrics', 'Save rubric criteria to text files.', 'icon_rubrics.png'),
                    ('dl_submissions', 'Submissions (Results)', 'Save feedback & grades from your submissions.', 'icon_submissions.png')
                ]

                css_blocks.append('''
                div.st-key-secondary_cards_grid [data-testid="stHorizontalBlock"] {
                    gap: 12px !important;
                }
                /* Nuke Streamlit's center alignment */
                div[class*="st-key-btn_dl_"] button > div,
                div[class*="st-key-btn_dl_"] button div[data-testid="stMarkdownContainer"] {
                    width: 100% !important;
                    display: flex !important;
                    justify-content: flex-start !important;
                    text-align: left !important;
                }
                div[class*="st-key-btn_dl_"] button p {
                    text-align: left !important;
                    width: 100% !important;
                    margin-top: 0px !important;
                    margin-bottom: 0px !important;
                    line-height: 1.2 !important;
                }
                div[class*="st-key-btn_dl_"] button::after {
                    text-align: left !important;
                    width: 100% !important;
                    display: block !important;
                }
                div[class*="st-key-btn_dl_"] button {
                    height: 58px !important;
                    min-height: 0px !important;
                    padding-top: 10px !important;
                    padding-bottom: 10px !important;
                    padding-right: 10px !important;
                    padding-left: 50px !important;
                    background-position: 15px center !important;
                    background-size: 24px !important;
                    background-repeat: no-repeat !important;
                    border-radius: 12px !important;
                    display: flex;
                    flex-direction: column;
                    -webkit-tap-highlight-color: transparent !important;
                }
                div.st-key-btn_dl_secondary_master button {
                    height: 48px !important;
                    padding-top: 0px !important;
                    padding-bottom: 0px !important;
                    justify-content: center !important;
                }
                ''')

                # Master CSS
                # Master CSS
                m_bg = "rgba(255, 255, 255, 0.12)" if m_active else "rgba(255, 255, 255, 0.1)"
                m_border = "rgba(255, 255, 255, 0.1)"
                m_ledge = "#68d4a3" if m_active else "transparent"
                m_ledge_border = "#68d4a3" if m_active else m_border
                b64_m = safe_b64('icon_canvas_content_select_all.png')
                m_img_rule = f"background-image: url('data:image/png;base64,{b64_m}') !important;" if b64_m else ""

                css_blocks.append(f'''
                div.st-key-btn_dl_secondary_master button {{
                    background-color: {m_bg} !important;
                    border: 1px solid {m_border} !important;
                    border-bottom: 1px solid {m_ledge_border} !important;
                    box-shadow: inset 0 -3px 0 0 {m_ledge} !important;
                    border-radius: 12px !important;
                    {m_img_rule}
                }}
                ''')

                if not m_active:
                    css_blocks.append('''
                    div.st-key-btn_dl_secondary_master button:hover {
                        border-bottom: 1px solid #3e8162 !important;
                        box-shadow: inset 0 -3px 0 0 #3e8162 !important;
                    }
                    ''')

                if m_active:
                    css_blocks.append('''
                    /* Master button checkbox intentionally hidden by global rule. Left empty here for compatibility. */
                    ''')

                # Child CSS
                for key, title, desc, icon in button_defs:
                    is_active = st.session_state.get(key, False)
                    c_bg = "rgba(104, 212, 163, 0.15)" if is_active else "rgba(255, 255, 255, 0.02)"
                    c_border = "#68d4a3" if is_active else "rgba(255, 255, 255, 0.1)"
                    b64_c = safe_b64(icon)
                    c_img_rule = f"background-image: url('data:image/png;base64,{b64_c}') !important;" if b64_c else ""

                    if is_active:
                        c_check = f'''
                        div.st-key-btn_{key} button::before {{
                            border: none !important;
                            background-color: transparent !important;
                            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cdefs%3E%3Cmask id='m'%3E%3Crect width='24' height='24' fill='white'/%3E%3Cpath d='M20 6L9 17l-5-5' fill='none' stroke='black' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/mask%3E%3C/defs%3E%3Crect width='24' height='24' rx='4' fill='%2368d4a3' mask='url(%23m)'/%3E%3C/svg%3E") !important;
                        }}
                        div.st-key-btn_{key} button:hover::before {{ border-color: transparent !important; }}
                        '''
                    else:
                        c_check = ""

                    css_blocks.append(f'''
                    div.st-key-btn_{key} button {{
                        background-color: {c_bg} !important;
                        border: 1px solid {c_border} !important;
                        {c_img_rule}
                    }}
                    div.st-key-btn_{key} button::after {{
                        content: "{desc}" !important;
                        font-size: 0.75rem !important; color: #a0a0a0; white-space: normal !important;
                        display: block !important; text-align: left !important; width: 100%; margin-top: -2px !important; line-height: 1.2 !important;
                    }}
                    div.st-key-btn_{key} button:hover {{
                        border-color: #68d4a3 !important;
                    }}
                    div.st-key-btn_{key} button:hover::before {{
                        border-color: #68d4a3 !important;
                    }}
                    {c_check}
                    ''')

                final_html = f"<style>{''.join(css_blocks)}</style>"

                if c2_exp:
                    st.markdown(f"""{final_html}
<p style='font-size: 0.95rem; color: #e2e8f0; margin-top: -15px; margin-bottom: 0px;'>Save information, pages and other content from Canvas to your local Course folder.</p>
<hr style='border: none; border-top: 1px solid rgba(255, 255, 255, 0.15); margin-top: 15px; margin-bottom: 15px;'>""", unsafe_allow_html=True)
                    st.button("Select All", key="btn_dl_secondary_master", on_click=_toggle_secondary_master, use_container_width=True)

                    with st.container(key="secondary_cards_grid"):
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            for key, title, _, _ in button_defs[:3]:
                                st.button(title, key=f"btn_{key}", on_click=_toggle_secondary_sub, args=(key,), use_container_width=True)
                        with c2:
                            for key, title, _, _ in button_defs[3:5]:
                                st.button(title, key=f"btn_{key}", on_click=_toggle_secondary_sub, args=(key,), use_container_width=True)
                        with c3:
                            for key, title, _, _ in button_defs[5:]:
                                st.button(title, key=f"btn_{key}", on_click=_toggle_secondary_sub, args=(key,), use_container_width=True)

                    # --- Section 2: Canvas-Native Content Organization ---
                    # Dim the label if no secondary content is active
                    sec_org_label_color = "#cbd5e1" if _sec_active > 0 else "#475569"

                    st.markdown(f"""
                    <p style='font-size: 0.9rem; font-weight: 600; color: {sec_org_label_color}; margin-top: 15px; margin-bottom: 0px;'>Choose how Canvas Content should be organized:</p>
                    {_get_sec_org_segmented_css()}
                    """, unsafe_allow_html=True)

                    with st.container(key="sec_org_segmented_wrapper"):
                        c1, c2 = st.columns(2, gap="small")

                        is_disabled = (_sec_active == 0)

                        with c1:
                            st.button(
                                "Match Course Folder structure", 
                                key="btn_sec_org_inline", 
                                on_click=_set_isolate_secondary, 
                                args=(False,), 
                                use_container_width=True,
                                disabled=is_disabled
                            )
                        with c2:
                            st.button(
                                "In Separate Folders", 
                                key="btn_sec_org_subfolders", 
                                on_click=_set_isolate_secondary, 
                                args=(True,), 
                                use_container_width=True,
                                disabled=is_disabled
                            )




        with col2:
            _render_card2()

        # Force a visual break between top and bottom rows
        st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

        # --- BOTTOM ROW: Conversion Settings / NotebookLM ---
        @st.fragment
        def _render_card3_inner():
            # --- Conversion Button Data ---
            conv_button_defs = [
                ('convert_zip',   'Unpack Archives',    'Auto-unzip .zip and .tar.gz archives.',        'icon_conv_zip.png', None),
                ('convert_pptx',  'PowerPoint ⭢ PDF',         'Convert .pptx/.ppt to PDF.',      'icon_conv_pptx.png', 'Requires Microsoft PowerPoint or LibreOffice'),
                ('convert_word',  'Legacy Word Docs ⭢ PDF',          'Convert unsupported older formats (.doc, .rtf, .odt) to PDF.',                    'icon_conv_word.png', 'Requires Microsoft Word or LibreOffice'),
                ('convert_excel', 'Excel ⭢ PDF & AI Data',              'Export each spreadsheet as PDF + structured .txt with all cell data.',                'icon_conv_excel.png', 'Requires Microsoft Excel. AI data file only for .xlsx/.xlsm (not .xls)'),
                ('convert_html',  'Canvas Pages ⭢ Plain Text',          'Convert Canvas web pages into AI-friendly text.',          'icon_conv_html.png', None),
                ('convert_code',  'Code & Data ⭢ .txt',       'Append .txt extension to programming files (e.g. code.js.txt).',          'icon_conv_code.png', None),
                ('convert_urls',  'Gather Web Links in .txt',        'Compile all internet shortcuts into one structured .txt file.',        'icon_conv_urls.png', None),
                ('convert_video', 'Video ⭢ Audio',            'Extract .mp3 audio from video files.',          'icon_conv_video.png', None),
            ]

            # --- Dynamic Tag Counter ---
            _conv_active = sum(1 for k in notebook_sub_keys if st.session_state.get(k, False))

            _c3_is_exp = st.session_state.get('card3_expanded', False)
            c3_tag_bg = "rgba(249, 115, 22, 0.15)"
            c3_tag_col = "#f97316"
            c3_tag_bor = "1px solid transparent"

            if _conv_active == 0:
                c3_tag_bg = "rgba(255, 255, 255, 0.05)"
                c3_tag_col = "#94a3b8"
                c3_tag_bor = "1px solid rgba(255, 255, 255, 0.1)"
                if not _c3_is_exp:
                    conv_tag = "<strong>OFF</strong>"
                else:
                    conv_tag = "<strong>OFF</strong>  |  None selected"
            elif _conv_active == TOTAL_NOTEBOOK_SUBS:
                conv_tag = "<strong>ON</strong>  |  All selected"
            else:
                conv_tag = f"<strong>ON</strong>  |  {_conv_active} selected"

            # --- Dynamic CSS only ---
            # Static layout/geometry/description/hover rules live in
            # styles/global.css (under "Card 3 - static button styling").
            # Here we only emit the parts that depend on session state:
            # icon URLs and active-state coloring + active checkmark SVG.
            conv_css_blocks = []

            # Master (Select All) - dynamic active state + icon
            m_active = st.session_state.get('notebooklm_master', False)
            b64_conv_m = safe_b64('icon_conv_select_all.png')
            m_conv_img_rule = f"background-image: url('data:image/png;base64,{b64_conv_m}') !important;" if b64_conv_m else ""

            if m_active:
                conv_css_blocks.append(
                    f'div.st-key-btn_convert_master button {{ background-color: rgba(255, 255, 255, 0.12) !important; border-bottom: 1px solid #f97316 !important; box-shadow: inset 0 -3px 0 0 #f97316 !important; {m_conv_img_rule} }}\n'
                )
            else:
                conv_css_blocks.append(
                    f'div.st-key-btn_convert_master button {{ {m_conv_img_rule} }}\n'
                    'div.st-key-btn_convert_master button:hover { border-bottom: 1px solid #a64d0f !important; box-shadow: inset 0 -3px 0 0 #a64d0f !important; }\n'
                )

            # Child buttons - icon (always) + active state colors + active checkmark
            ACTIVE_CHECK_SVG = (
                "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cdefs%3E%3Cmask id='m'%3E%3Crect width='24' height='24' fill='white'/%3E%3Cpath d='M20 6L9 17l-5-5' fill='none' stroke='black' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/mask%3E%3C/defs%3E%3Crect width='24' height='24' rx='4' fill='%23ff9838' mask='url(%23m)'/%3E%3C/svg%3E\")"
            )
            for conv_key, _conv_title, _conv_desc, conv_icon, _conv_req in conv_button_defs:
                is_conv_active = st.session_state.get(conv_key, False)
                b64_conv_c = safe_b64(conv_icon)
                c_conv_img_rule = f"background-image: url('data:image/png;base64,{b64_conv_c}') !important;" if b64_conv_c else ""

                if is_conv_active:
                    conv_css_blocks.append(
                        f'div.st-key-btn_{conv_key} button {{ background-color: rgba(249, 115, 22, 0.15) !important; border: 1px solid #f97316 !important; {c_conv_img_rule} }}\n'
                        f'div.st-key-btn_{conv_key} button::before {{ border: none !important; background-color: transparent !important; background-image: {ACTIVE_CHECK_SVG} !important; }}\n'
                        f'div.st-key-btn_{conv_key} button:hover::before {{ border-color: transparent !important; }}\n'
                    )
                else:
                    # Inactive - only the icon; defaults come from global.css
                    conv_css_blocks.append(
                        f'div.st-key-btn_{conv_key} button {{ {c_conv_img_rule} }}\n'
                    )

            # --- Header HTML (separate injection) ---
            def toggle_card3():
                st.session_state['card3_expanded'] = not st.session_state.get('card3_expanded', False)

            c3_exp = st.session_state.get('card3_expanded', False)
            chr3_svg = _get_chevron_base64(c3_exp)
            b64_wf3 = _load_b64("assets/icon_workflow_3.png")

            m_conv_active = st.session_state.get('notebooklm_master', False)
            has_active_items3 = _conv_active > 0 or m_conv_active
            c3_filter = "grayscale(0%) brightness(100%)" if has_active_items3 else "grayscale(100%) brightness(60%)"
            c3_base_color = "#94a3b8" if c3_exp else "#64748b"
            c3_hover_color = "#cbd5e1" if c3_exp else "#94a3b8"

            # THE FIX: Inject chevron CSS BEFORE the button to prevent ghost flash
            st.markdown(f'''<style>
            div.st-key-header_wrap_card3 {{
                display: flex !important;
                flex-direction: row !important;
                align-items: center !important;
                justify-content: flex-start !important;
                gap: 12px !important;
                padding-top: 0px !important;
                padding-bottom: 0px !important;
                margin-top: -35px !important;
            }}
            div.st-key-header_wrap_card3 > div[data-testid="element-container"] {{
                margin-bottom: 0px !important;
            }}
            div.st-key-header_wrap_card3 > div[data-testid="element-container"]:nth-child(1) {{
                width: 24px !important;
                min-width: 24px !important;
                flex: 0 0 24px !important;
            }}
            div.st-key-header_wrap_card3 > div[data-testid="element-container"]:nth-child(2) {{
                flex: 1 1 auto !important;
                width: 100% !important;
            }}
            /* Kill focus rings on the parent wrappers */
            div.st-key-toggle_card3 div[data-testid="stButton"]:focus-within,
            div.st-key-toggle_card3 div[data-testid="stBaseButton-secondary"]:focus-within {{
                box-shadow: none !important;
                outline: none !important;
                background: transparent !important;
            }}
            /* Kill focus rings on the button itself during focus shifts */
            div.st-key-toggle_card3 button:focus-visible,
            div.st-key-toggle_card3 button:focus:not(:active),
            div.st-key-toggle_card3 button:focus {{
                box-shadow: none !important;
                outline: none !important;
                border: none !important;
                background-color: {c3_base_color} !important;
            }}
            /* Ensure the inner markdown div remains completely hidden */
            div.st-key-toggle_card3 button > div {{
                display: none !important;
            }}
            /* BASE MASK STATE */
            div.st-key-toggle_card3 button {{
                all: unset !important;
                display: inline-block !important;
                cursor: pointer !important;
                width: 24px !important;
                height: 24px !important;
                position: relative !important;
                top: 5px !important;
                -webkit-mask-image: {chr3_svg} !important;
                -webkit-mask-size: contain !important;
                -webkit-mask-repeat: no-repeat !important;
                -webkit-mask-position: center !important;
                background-color: {c3_base_color} !important;
                transition: background-color 0.2s ease !important;
                box-shadow: none !important;
                outline: none !important;
                border: none !important;
                -webkit-tap-highlight-color: transparent !important;
            }}
            /* HOVER STATE */
            div.st-key-toggle_card3 button:hover {{ background-color: {c3_hover_color} !important; box-shadow: none !important; }}
            /* ACTIVE KILLER */
            div.st-key-toggle_card3 button:active {{
                box-shadow: none !important;
                outline: none !important;
                border: none !important;
                transform: none !important;
            }}
            /* RERUN LOCK */
            div.st-key-toggle_card3 button[disabled] {{
                box-shadow: none !important;
                outline: none !important;
                border: none !important;
                background-color: {c3_base_color} !important;
                opacity: 0.8 !important;
            }}
            </style>''', unsafe_allow_html=True)

            st.markdown(f"<div class='step-2-card-target' style='position: relative; margin-top: -25px; margin-bottom: 0px;'><img src='data:image/png;base64,{b64_wf3}' style='position: absolute; width: 36px; height: 36px; top: -24px; left: -34px; z-index: 10; filter: {c3_filter}; transition: all 0.2s ease;' /></div>", unsafe_allow_html=True)

            with st.container(key="header_wrap_card3"):
                st.button("\u200B", key="toggle_card3", on_click=toggle_card3)
                st.markdown(f"""<div style='display: flex; align-items: center; justify-content: space-between; padding-right: 10px; width: 100%; transform: translateY(-5px);'><h3 style='margin: 0px !important; padding: 0px !important; line-height: 1 !important;'>Optimize for AI Tools <span style='color: #64748b; font-size: 0.8em; font-weight: normal;'>(Optional)</span></h3><span style='background-color: {c3_tag_bg}; color: {c3_tag_col}; border: {c3_tag_bor}; font-size: 0.8rem; padding: 2px 12px; border-radius: 15px; font-weight: 600; transition: all 0.2s ease;'>{conv_tag}</span></div>""", unsafe_allow_html=True)

            # --- CSS injection (separate call, zero-indentation) ---
            conv_css_html = "<style>\n" + "".join(conv_css_blocks) + "</style>"

            if c3_exp:
                st.markdown(f"""{conv_css_html}
<p style='font-size: 0.95rem; color: #e2e8f0; margin-top: -15px; margin-bottom: 0px;'>Automatically convert files into drag-and-drop ready formats, optimized for NotebookLM, ChatGPT, Claude, Gemini, and other AI tools.</p>
<hr style='border: none; border-top: 1px solid rgba(255, 255, 255, 0.15); margin-top: 15px; margin-bottom: 15px;'>""", unsafe_allow_html=True)
                st.button("Select All", key="btn_convert_master", on_click=_toggle_conv_master, use_container_width=True)

                with st.container(key="conversion_cards_grid"):
                    cols = st.columns(4)
                    for idx, (conv_key, conv_title, _, _, conv_req) in enumerate(conv_button_defs):
                        col = cols[idx % 4]
                        with col:
                            if conv_req:
                                st.button(conv_title, key=f"btn_{conv_key}", on_click=_toggle_conv_sub, args=(conv_key,), use_container_width=True, help=conv_req)
                            else:
                                st.button(conv_title, key=f"btn_{conv_key}", on_click=_toggle_conv_sub, args=(conv_key,), use_container_width=True)

        with st.container(border=True, key="card_ai_engine"):
            _render_card3_inner()

        # Separator above Output Folder section
        st.markdown(
            "<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:28px 0 20px 0;'>",
            unsafe_allow_html=True,
        )

        st.markdown(
            "<div style='font-size: 1.15rem; font-weight: 700; color: #ffffff; margin-top: 10px; margin-bottom: 12px; display: flex; align-items: center; gap: 10px;'>"
            "Verify your download destination"
            "</div>",
            unsafe_allow_html=True,
        )

        dl_path = st.session_state['download_path']
        
        st.html("""<style>
div.st-key-review_browse_folder button {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #cbd5e1 !important;
    font-weight: 500 !important;
    border-radius: 8px !important;
    height: 58px !important;
    transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease !important;
    transform: none !important;
}
div.st-key-review_browse_folder button:hover {
    background: rgba(255,255,255,0.1) !important;
    color: #ffffff !important;
    border-color: rgba(255,255,255,0.25) !important;
    transform: none !important;
}
</style>""")

        f_col, btn_col = st.columns([4, 0.8], gap="small")
        with f_col:
            folder_name   = Path(dl_path).name or dl_path
            folder_parent = str(Path(dl_path).parent)
            st.markdown(
                f"""
                <div title="{esc(dl_path)}" style="
                    background: linear-gradient(160deg, rgba(255,255,255,0.055) 0%, rgba(255,255,255,0.02) 100%);
                    border: 1px solid rgba(255,255,255,0.08);
                    border-radius: 8px;
                    padding: 8px 16px;
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    min-height: 58px;
                    box-sizing: border-box;
                    cursor: default;">
                    <svg width="18" height="18" fill="none" stroke="#94a3b8" viewBox="0 0 24 24" style="flex-shrink:0;">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
                    </svg>
                    <div style="flex:1; min-width:0;">
                        <div style="font-weight:600; color:#ffffff; font-size:0.98rem; line-height:1.15;
                                    white-space:normal; overflow-wrap:anywhere;">
                            {esc(folder_name)}
                        </div>
                        <div style="font-size:0.83rem; color:#94a3b8; line-height:1.15;
                                    white-space:normal; overflow-wrap:anywhere; margin-top: 0px;">
                            {esc(folder_parent)}
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with btn_col:
            st.button("Change folder", key="review_browse_folder", use_container_width=True, on_click=_select_folder)

        # --- Unified Course Summary Dropdown (full-width, native <details>) ---
        _dl_courses = st.session_state.get('courses_to_download', [])
        if not _dl_courses:
            try:
                _all_c = fetch_courses_fn(st.session_state['api_token'], st.session_state['api_url'])
                _sel_ids = set(st.session_state.get('selected_course_ids', []))
                _dl_courses = [c for c in _all_c if c.id in _sel_ids]
            except Exception:
                _dl_courses = []
        _dl_count = len(_dl_courses)

        def _render_course_item(i, c):
            name, code = get_course_display_parts(c)
            code_clean = code.strip("()") if code else ""
            if code_clean:
                code_html = f"<div class='code'>{esc(code_clean)}</div>"
            else:
                code_html = ""
            return f"<li class='course-item'><span class='num'>{i}.</span> <div class='name-wrap'><div class='name'>{esc(name)}</div>{code_html}</div></li>"

        _dl_list_html = "".join([_render_course_item(i, c) for i, c in enumerate(_dl_courses, 1)])

        _dl_details_html = f"""
    <style>
    details.unified-course-dropdown {{
        margin-top: 0px;
        margin-bottom: 60px;
        width: 100%;
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 6px;
        background: transparent;
        transition: background 0.2s ease, border-color 0.2s ease;
    }}
    details.unified-course-dropdown[open] {{
        background: #111418;
        border-color: rgba(255, 255, 255, 0.2);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }}
    details.unified-course-dropdown summary {{
        cursor: pointer;
        padding: 12px 16px;
        list-style: none;
        user-select: none;
        outline: none;
        display: flex;
        align-items: center;
        justify-content: flex-start;
        gap: 12px;
    }}
    details.unified-course-dropdown summary::-webkit-details-marker {{
        display: none;
    }}
    .summary-chevron {{
        color: #a0a0a0;
        font-size: 1.3rem;
        line-height: 1;
        transition: transform 0.2s ease;
    }}
    details.unified-course-dropdown[open] .summary-chevron {{
        transform: rotate(90deg);
    }}
    .summary-text {{
        color: #ffffff;
        font-size: 0.92rem;
        font-weight: 700;
        display: flex;
        align-items: center;
        gap: 10px;
    }}
    .count-tag {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background-color: rgba(56, 189, 248, 0.15) !important;
        border: 1px solid rgba(56, 189, 248, 0.3) !important;
        color: #ffffff !important;
        font-size: 0.9rem;
        font-weight: 700;
        min-width: 20px;
        height: 24px;
        padding: 0 9px;
        border-radius: 8px;
        line-height: 1;
    }}
    .dropdown-body {{
        border-top: 1px solid rgba(255, 255, 255, 0.1);
        padding: 8px 0 10px 0;
        max-height: 300px;
        overflow-y: auto;
    }}
    ul.course-list-box {{
        margin: 0;
        padding: 0 16px 0 16px;
        list-style-type: none;
    }}
    li.course-item {{
        display: flex;
        align-items: flex-start;
        gap: 5px;
        padding: 8px 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    }}
    li.course-item:last-child {{
        border-bottom: none;
    }}
    li.course-item .num {{
        color: #888888;
        font-size: 1.05rem;
        min-width: 20px;
        margin-top: 1px;
    }}
    li.course-item .name-wrap {{
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }}
    li.course-item .name {{
        color: #ffffff;
        font-size: 1.05rem;
        font-weight: 400;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.2;
    }}
    li.course-item .code {{
        color: #94a3b8;
        font-size: 0.85rem;
        font-weight: 400;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        margin-top: 0px;
    }}
    .dropdown-body::-webkit-scrollbar {{
        width: 6px;
    }}
    .dropdown-body::-webkit-scrollbar-track {{
        background: transparent;
    }}
    .dropdown-body::-webkit-scrollbar-thumb {{
        background-color: rgba(255, 255, 255, 0.15);
        border-radius: 10px;
    }}
    .dropdown-body::-webkit-scrollbar-thumb:hover {{
        background-color: rgba(255, 255, 255, 0.25);
    }}
    </style>

    <details class="unified-course-dropdown">
    <summary>
    <div class="summary-chevron">▸</div>
    <div class="summary-text">Courses selected for download <span class="count-tag">{_dl_count}</span></div>
    </summary>
    <div class="dropdown-body">
    <ul class="course-list-box">
    {_dl_list_html}
    </ul>
    </div>
    </details>

    <style>
    /* Custom Confirm and Download Colors - Solid Physical Volume */
    div.st-key-action_dl_confirm button {{
        background-color: #1f77b4 !important;
        border: none !important;
        color: #ffffff !important;
        box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3) !important;
        transition: background-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
    }}

    /* Confirm and Download Hover - Glow + Lighter Shift */
    div.st-key-action_dl_confirm button:hover {{
        background-color: #2b8cbe !important;
        box-shadow: 0 4px 15px rgba(31, 119, 180, 0.2), 
                    inset 0 1px 1px rgba(255, 255, 255, 0.4) !important;
        color: #ffffff !important;
    }}
    </style>
    """

        st.markdown(_dl_details_html, unsafe_allow_html=True)
        col_back, col_conf, _ = st.columns([0.66, 1.2, 5])
        with col_conf:
            # Button label changes based on mode
            button_label = 'Sync (Download) Selected Files' if st.session_state['current_mode'] == 'sync' else 'Confirm and Download'
            if st.button(button_label, type="primary", use_container_width=True, key='action_dl_confirm'):
                try:
                    # ── PRE-FLIGHT: Writability probe ──
                    # Fail fast with a clear message if the download folder is
                    # read-only, missing, or otherwise unwritable - before the
                    # user wastes minutes on the course scanning phase.
                    _dl_path = Path(st.session_state.get('download_path', ''))
                    try:
                        _dl_path.mkdir(parents=True, exist_ok=True)
                        _probe = _dl_path / '.canvas_write_probe'
                        _probe.write_bytes(b'ok')
                        _probe.unlink()
                    except Exception as _wp_err:
                        st.error(
                            f"⚠️ Cannot write to the selected download folder.\n\n"
                            f"**Path:** `{_dl_path}`\n\n"
                            f"**Reason:** {_wp_err}\n\n"
                            f"Please select a different folder with write permissions."
                        )
                        st.stop()

                    # Initialize download state
                    all_courses = fetch_courses_fn(st.session_state['api_token'], st.session_state['api_url'])
                    course_map = {c.id: c for c in all_courses}
                    courses_to_download = [course_map[cid] for cid in st.session_state['selected_course_ids'] if cid in course_map]

                    # ── RESET all transient download state before starting fresh ──
                    # Without this, data from the PREVIOUS download (file lists,
                    # error counts, discovery warnings) bleeds into the new one.
                    for _stale_key in [
                        'download_file_details', 'download_errors_list', 'failed_items',
                        'downloaded_items', 'log_deque', 'skipped_discovery_errors',
                        'size_skipped_files', 'pp_failure_count', 'pp_success_count',
                        'log_content', 'seen_error_sigs', 'course_mb_downloaded',
                        'retry_attempted', 'retry_resolved_count', 'retry_total_attempted',
                        'isolated_retry_queue', 'retry_downloaded_items', 'retry_failed_items',
                        'retry_isolated_details', 'retry_mb_tracker', 'is_post_processing',
                        'start_time', 'total_items', 'total_mb',
                        'sync_has_ignored_files',
                    ]:
                        st.session_state.pop(_stale_key, None)

                    st.session_state['courses_to_download'] = courses_to_download
                    st.session_state['current_course_index'] = 0
                    st.session_state['cancel_requested'] = False
                    st.session_state['total_items'] = 0
                    st.session_state['downloaded_items'] = 0
                    st.session_state['course_mb_downloaded'] = {}
                    st.session_state['log_content'] = ""  # Initialize log content
                    st.session_state['seen_error_sigs'] = []  # List-backed dedup (Streamlit serialization safe)

                    # Task 1: Save the State on Button Click (Streamlit Widget Cleanup Fix)
                    st.session_state['persistent_convert_zip'] = st.session_state.get('convert_zip', False)
                    st.session_state['persistent_convert_pptx'] = st.session_state.get('convert_pptx', False)
                    st.session_state['persistent_convert_html'] = st.session_state.get('convert_html', False)
                    st.session_state['persistent_convert_code'] = st.session_state.get('convert_code', False)
                    st.session_state['persistent_convert_urls'] = st.session_state.get('convert_urls', False)
                    st.session_state['persistent_convert_word'] = st.session_state.get('convert_word', False)
                    st.session_state['persistent_convert_video'] = st.session_state.get('convert_video', False)
                    st.session_state['persistent_convert_excel'] = st.session_state.get('convert_excel', False)

                    # Task 1b: Save secondary content state on button click
                    for _sck in SECONDARY_CONTENT_KEYS:
                        st.session_state[f'persistent_{_sck}'] = st.session_state.get(_sck, False)
                    st.session_state['persistent_dl_isolate_secondary'] = st.session_state.get('dl_isolate_secondary', True)

                    # Clear debug log once at session start (subsequent courses append)
                    if st.session_state.get('debug_mode', False):
                        from canvas_debug import clear_debug_log
                        clear_debug_log(Path(st.session_state['download_path']) / "debug_log.txt")

                    if st.session_state['current_mode'] == 'sync':
                        # Sync mode - go to Step 4 (Analysis)
                        st.session_state['download_status'] = 'analyzing'
                        st.session_state['step'] = 4
                    else:
                        # Download mode - go to Step 3 (Progress)
                        st.session_state['download_status'] = 'scanning'
                        st.session_state['step'] = 3

                    # Brief pause to ensure state is saved before rerun
                    time.sleep(0.1)
                    step2_container.empty() # Clear EVERYTHING in Step 2
                    st.rerun()
                except Exception as e:
                    st.error(f"Error initializing: {e}")

        with col_back:
            if st.button('Back', use_container_width=True, key='action_dl_back'):
                if st.session_state.get('came_from_quick_dl', False):
                    st.session_state['quick_download_mode'] = True
                    st.session_state.pop('came_from_quick_dl', None)
                else:
                    st.session_state['step'] = 1
                st.rerun()

