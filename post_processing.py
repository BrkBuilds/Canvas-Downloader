"""
Post-Processing Pipeline for Canvas Downloader
Unified conversion logic shared between Download (app.py) and Sync (sync_ui.py) flows.

Eliminates ~800 lines of duplicated code by providing:
  - UIBridge: Abstracts Streamlit placeholder references between callers
  - Individual run_* functions: One per converter type
  - run_all_conversions: Convenience entry point for the Download flow (globs + runs all)
  - Consistent DB updates via SyncManager (fixes raw-sqlite3 audit bug)
"""

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ── Color map per conversion type for dashboard accent ──
_COLOR_MAP = {
    'Archives':           '#a78bfa',
    'PowerPoint files':   '#f97316',
    'HTML files':         '#34D399',
    'Code files':         '#FBBF24',
    'Legacy Word files':  '#3b82f6',
    'Excel files':        '#22c55e',
    'Video files':        '#f59e0b',
}


@dataclass
class UIBridge:
    """Abstracts Streamlit placeholder references between Download and Sync flows.

    Each caller passes its own placeholder objects and cancel-check callable.
    app.py  passes: header_placeholder, progress_placeholder, metrics_placeholder, log_placeholder, ...
    sync_ui passes: status_text,        progress_container,   metrics_dashboard,    log_container, ...
    """
    header_placeholder: Any
    progress_placeholder: Any
    metrics_placeholder: Any
    log_placeholder: Any
    active_file_placeholder: Any
    log_lines: Any  # mutable list or deque of HTML log strings
    is_cancelled: Callable[[], bool] = field(default_factory=lambda: lambda: False)
    on_detail_update: Optional[Callable] = None   # (context, old_name, new_name)
    error_log_path: Optional[Path] = None


# ─────────────────────────────────────────────────────
# Shared UI Rendering Helpers
# ─────────────────────────────────────────────────────

def _render_dashboard(ui: UIBridge, current: int, total: int, task_name: str):
    """Render the post-processing progress dashboard into the caller's placeholders."""
    try:
        if ui.is_cancelled():
            return
        accent = _COLOR_MAP.get(task_name, '#4ade80')
        pct = min(100, int((current / total) * 100) if total > 0 else 0)

        ui.header_placeholder.markdown(f'''
        <div style="margin-bottom: 0.5rem;">
            <p style="margin: 0; font-size: 0.8rem; color: #8A91A6; text-transform: uppercase;">🪄 Post-Processing</p>
            <h3 style="margin: 0; padding-top: 0.1rem; color: #FFFFFF;">Converting {task_name}</h3>
        </div>
        ''', unsafe_allow_html=True)

        ui.progress_placeholder.markdown(f'''
        <div style="background-color: #2D3248; border-radius: 8px; width: 100%; height: 24px; position: relative; margin-bottom: 10px;">
            <div style="background-color: {accent}; width: {pct}%; height: 100%; border-radius: 8px; transition: width 0.3s ease;"></div>
            <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: #ffffff; font-size: 12px; font-weight: bold; text-shadow: 0px 0px 2px rgba(0,0,0,0.5);">
                {pct}%
            </div>
        </div>
        ''', unsafe_allow_html=True)

        ui.metrics_placeholder.markdown(f'''
        <div style="display: flex; justify-content: center; gap: 4rem; background-color: #1A1D27; padding: 15px 25px; border-radius: 8px; border: 1px solid #2D3248; margin-top: 5px; margin-bottom: 15px;">
            <div style="display: flex; flex-direction: column; align-items: center;">
                <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Converted</span>
                <span style="color: #FFFFFF; font-size: 1.2rem; font-weight: bold;">{current} <span style="font-size: 0.9rem; color: {accent};">/ {total}</span></span>
            </div>
            <div style="display: flex; flex-direction: column; align-items: center;">
                <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Type</span>
                <span style="color: {accent}; font-size: 1.2rem; font-weight: bold;">{task_name}</span>
            </div>
        </div>
        ''', unsafe_allow_html=True)

        # Re-render log so it stays in sync with progress/metrics
        log_content = "<br>".join(reversed(list(ui.log_lines)))
        ui.log_placeholder.markdown(f'''
        <div style="background-color: #0D1117; color: #A5D6FF; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; font-size: 0.85rem; height: 140px; border: 1px solid #30363D; line-height: 1.6; overflow-y: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.5);">
            {log_content}
        </div>
        ''', unsafe_allow_html=True)

        time.sleep(0.05)
    except BaseException:
        pass


def _log_msg(ui: UIBridge, msg: str):
    """Append an HTML log message, log to Python logger, and re-render the terminal."""
    try:
        if ui.is_cancelled():
            return
        plain = re.sub(r'<[^>]+>', '', msg)
        if '❌' in plain:
            logger.error(plain)
        else:
            logger.info(plain)

        ui.log_lines.append(msg)

        log_content = "<br>".join(reversed(list(ui.log_lines)))
        ui.log_placeholder.markdown(f'''
        <div style="background-color: #0D1117; color: #A5D6FF; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; font-size: 0.85rem; height: 140px; border: 1px solid #30363D; line-height: 1.6; overflow-y: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.5);">
            {log_content}
        </div>
        ''', unsafe_allow_html=True)
        time.sleep(0.05)
    except BaseException:
        pass


def _show_active_file(ui: UIBridge, filename: str):
    """Update the 'Currently processing' status line."""
    try:
        ui.active_file_placeholder.markdown(
            f"<div style='color: #38bdf8; margin-bottom: 10px; font-weight: 500;'>⚙️ Currently processing: {filename}</div>",
            unsafe_allow_html=True,
        )
    except BaseException:
        pass


# ─────────────────────────────────────────────────────
# Database & Error Helpers
# ─────────────────────────────────────────────────────

def _update_manifest_path(sm, original_file: Path, converted_path: Path):
    """Update the sync manifest to point from the original file to the converted file.

    Uses SyncManager exclusively — no raw sqlite3.  Fixes the audit inconsistency.
    """
    try:
        original_rel = str(original_file.relative_to(sm.local_path)).replace('\\', '/')
        new_rel = str(converted_path.relative_to(sm.local_path)).replace('\\', '/')
    except ValueError:
        return

    manifest = sm.load_manifest()
    for file_id, info in manifest.get('files', {}).items():
        if info.get('local_path', '') == original_rel:
            sm.update_converted_file(int(file_id), new_rel)
            break


def _log_error_to_file(error_log_path: Path | None, filename: str, error_msg: str):
    """Write a post-processing error to download_errors.txt."""
    if error_log_path is None:
        return
    from datetime import datetime
    err_file = error_log_path / "download_errors.txt"
    try:
        error_log_path.mkdir(parents=True, exist_ok=True)
        with open(err_file, "a", encoding="utf-8") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] [Post-Processing] {filename}: {error_msg}\n")
    except OSError:
        pass


# ─────────────────────────────────────────────────────
# Individual Converter Runners
#
# Each accepts:
#   files: list of (Path, SyncManager, context)
#     - context is opaque; passed back to on_detail_update
#     - app.py passes None; sync_ui passes pair_idx
#   ui: UIBridge
# ─────────────────────────────────────────────────────

def run_archive_extraction(files, ui: UIBridge):
    """Extract archives (.zip, .tar, .tar.gz)."""
    if not files:
        return
    from archive_extractor import extract_and_stub

    total = len(files)
    _log_msg(ui, f"<span style='color: #8A91A6;'>[ 🪄 ] Queueing {total} Archive files for extraction...</span>")
    _render_dashboard(ui, 0, total, "Archives")
    time.sleep(0.2)

    for i, (archive_file, sm, ctx) in enumerate(files, 1):
        if ui.is_cancelled():
            _log_msg(ui, "<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
            break
        old_name = archive_file.name
        _show_active_file(ui, old_name)
        _render_dashboard(ui, i, total, "Archives")

        new_stub_path_str = extract_and_stub(archive_file)

        if new_stub_path_str:
            new_stub_path = Path(new_stub_path_str)
            _update_manifest_path(sm, archive_file, new_stub_path)
            if ui.on_detail_update:
                ui.on_detail_update(ctx, old_name, new_stub_path.name)
            _log_msg(ui, f"<span style='color: #4ade80;'>[ ✅ ] Extracted: {old_name}</span>")
        else:
            _log_msg(ui, f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} (Extraction failed)</span>")
            _log_error_to_file(ui.error_log_path, old_name, "Archive extraction failed")

    _log_msg(ui, "<span style='color: #8A91A6;'>[ ✨ ] Archive extraction complete!</span>")


def run_pptx_conversion(files, ui: UIBridge):
    """Convert PowerPoint files to PDF."""
    if not files:
        return
    from pdf_converter import PowerPointToPDF

    total = len(files)
    pptx_error_log = ui.error_log_path or files[0][1].local_path

    _log_msg(ui, f"<span style='color: #8A91A6;'>[ 🪄 ] Converting {total} PowerPoint files to PDF...</span>")
    _render_dashboard(ui, 0, total, "PowerPoint files")
    time.sleep(0.2)

    with PowerPointToPDF(error_log_path=pptx_error_log) as converter:
        for i, (pptx_file, sm, ctx) in enumerate(files, 1):
            if ui.is_cancelled():
                _log_msg(ui, "<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
                break
            old_name = pptx_file.name
            _show_active_file(ui, old_name)
            _render_dashboard(ui, i, total, "PowerPoint files")

            pdf_path_str = converter.convert(pptx_file)

            if pdf_path_str:
                pdf_path = Path(pdf_path_str)
                _update_manifest_path(sm, pptx_file, pdf_path)
                if ui.on_detail_update:
                    ui.on_detail_update(ctx, old_name, pdf_path.name)
                _log_msg(ui, f"<span style='color: #4ade80;'>[ ✅ ] Converted: {old_name} -> PDF</span>")
            else:
                _log_msg(ui, f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} (Conversion failed)</span>")
                _log_error_to_file(ui.error_log_path, old_name, "PDF conversion failed")

    _log_msg(ui, "<span style='color: #8A91A6;'>[ ✨ ] PDF conversion complete!</span>")


def run_html_conversion(files, ui: UIBridge):
    """Convert Canvas Pages (HTML) to Markdown."""
    if not files:
        return
    from md_converter import convert_html_to_md

    total = len(files)
    _log_msg(ui, f"<span style='color: #8A91A6;'>[ 🪄 ] Queueing {total} HTML files for Markdown conversion...</span>")
    _render_dashboard(ui, 0, total, "HTML files")
    time.sleep(0.2)

    for i, (html_file, sm, ctx) in enumerate(files, 1):
        if ui.is_cancelled():
            _log_msg(ui, "<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
            break
        old_name = html_file.name
        _show_active_file(ui, old_name)
        _render_dashboard(ui, i, total, "HTML files")

        md_path = convert_html_to_md(html_file)

        if md_path:
            _update_manifest_path(sm, html_file, md_path)
            if ui.on_detail_update:
                ui.on_detail_update(ctx, old_name, md_path.name)
            _log_msg(ui, f"<span style='color: #4ade80;'>[ ✅ ] Converted: {md_path.name}</span>")
        else:
            _log_msg(ui, f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} (Conversion failed)</span>")
            _log_error_to_file(ui.error_log_path, old_name, "Markdown conversion failed")

    _log_msg(ui, "<span style='color: #8A91A6;'>[ ✨ ] Markdown conversion complete!</span>")


def run_code_conversion(files, ui: UIBridge):
    """Convert code & data files to .txt."""
    if not files:
        return
    from code_converter import convert_code_to_txt

    total = len(files)
    _log_msg(ui, f"<span style='color: #8A91A6;'>[ 🪄 ] Queueing {total} Code & Data files for TXT conversion...</span>")
    _render_dashboard(ui, 0, total, "Code files")
    time.sleep(0.2)

    for i, (code_file, sm, ctx) in enumerate(files, 1):
        if ui.is_cancelled():
            _log_msg(ui, "<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
            break
        old_name = code_file.name
        _show_active_file(ui, old_name)
        _render_dashboard(ui, i, total, "Code files")

        txt_path_str = convert_code_to_txt(code_file)

        if txt_path_str:
            txt_path = Path(txt_path_str)
            _update_manifest_path(sm, code_file, txt_path)
            if ui.on_detail_update:
                ui.on_detail_update(ctx, old_name, txt_path.name)
            _log_msg(ui, f"<span style='color: #4ade80;'>[ ✅ ] Converted: {old_name} -> TXT</span>")
        else:
            _log_msg(ui, f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} (Conversion failed)</span>")
            _log_error_to_file(ui.error_log_path, old_name, "Code to TXT conversion failed")

    _log_msg(ui, "<span style='color: #8A91A6;'>[ ✨ ] Code to TXT conversion complete!</span>")


def run_url_compilation(folders, ui: UIBridge):
    """Compile .url shortcuts into a NotebookLM text file.

    folders: list of (course_folder_path: Path, course_name: str)
    """
    if not folders:
        return
    from url_compiler import compile_urls_to_txt

    _log_msg(ui, "<span style='color: #8A91A6;'>[ 🪄 ] Scanning downloaded modules for .url shortcuts...</span>")

    for course_folder, course_name in folders:
        if ui.is_cancelled():
            _log_msg(ui, "<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
            break

        if course_folder.exists():
            compiled_path = compile_urls_to_txt(course_folder, course_name)
            if compiled_path:
                _log_msg(ui, f"<span style='color: #4ade80;'>[ ✅ ] Compiled links for '{course_name}' into: NotebookLM_External_Links.txt</span>")


def run_word_conversion(files, ui: UIBridge):
    """Convert legacy Word documents (.doc, .rtf, .odt) to PDF."""
    if not files:
        return
    from word_converter import WordToPDF

    total = len(files)
    _log_msg(ui, f"<span style='color: #8A91A6;'>[ 🪄 ] Queueing {total} Legacy Word files for PDF conversion...</span>")
    _render_dashboard(ui, 0, total, "Legacy Word files")
    time.sleep(0.2)

    with WordToPDF() as converter:
        for i, (word_file, sm, ctx) in enumerate(files, 1):
            if ui.is_cancelled():
                _log_msg(ui, "<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
                break
            old_name = word_file.name
            _show_active_file(ui, old_name)
            _render_dashboard(ui, i, total, "Legacy Word files")

            pdf_path_str = converter.convert(word_file)

            if pdf_path_str:
                pdf_path = Path(pdf_path_str)
                _update_manifest_path(sm, word_file, pdf_path)
                if ui.on_detail_update:
                    ui.on_detail_update(ctx, old_name, pdf_path.name)
                _log_msg(ui, f"<span style='color: #4ade80;'>[ ✅ ] Converted: {old_name} -> PDF</span>")
            else:
                _log_msg(ui, f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} (Conversion failed)</span>")
                _log_error_to_file(ui.error_log_path, old_name, "Word to PDF conversion failed")

    _log_msg(ui, "<span style='color: #8A91A6;'>[ ✨ ] Legacy Word to PDF conversion complete!</span>")


def run_excel_conversion(files, ui: UIBridge):
    """Convert Excel files (.xlsx, .xls, .xlsm) to PDF.

    AUDIT FIX: Uses _update_manifest_path (SyncManager) instead of raw sqlite3.
    """
    if not files:
        return
    from excel_converter import ExcelToPDF

    total = len(files)
    _log_msg(ui, f"<span style='color: #8A91A6;'>[ 🪄 ] Queueing {total} Excel files for PDF conversion...</span>")
    _render_dashboard(ui, 0, total, "Excel files")
    time.sleep(0.2)

    with ExcelToPDF() as converter:
        for i, (excel_file, sm, ctx) in enumerate(files, 1):
            if ui.is_cancelled():
                _log_msg(ui, "<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
                break
            old_name = excel_file.name
            _show_active_file(ui, old_name)
            _render_dashboard(ui, i, total, "Excel files")

            abs_path = str(excel_file.absolute())
            new_pdf_path, excel_error_msg = converter.convert(abs_path)

            if new_pdf_path:
                pdf_path = Path(new_pdf_path)
                _update_manifest_path(sm, excel_file, pdf_path)
                if ui.on_detail_update:
                    ui.on_detail_update(ctx, old_name, pdf_path.name)
                _log_msg(ui, f"<span style='color: #4ade80;'>[ ✅ ] Converted: {old_name} -> PDF</span>")
            else:
                err_detail = excel_error_msg if excel_error_msg else "Excel to PDF conversion failed"
                _log_msg(ui, f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} ({err_detail})</span>")
                _log_error_to_file(ui.error_log_path, old_name, err_detail)

    _log_msg(ui, "<span style='color: #8A91A6;'>[ ✨ ] Excel to PDF conversion complete!</span>")


def run_video_conversion(files, ui: UIBridge):
    """Extract audio from video files (.mp4, .mov, .mkv) to MP3."""
    if not files:
        return
    from video_converter import convert_video_to_mp3

    total = len(files)
    _log_msg(ui, f"<span style='color: #8A91A6;'>[ 🪄 ] Queueing {total} Video files for audio extraction...</span>")
    _render_dashboard(ui, 0, total, "Video files")
    time.sleep(0.2)

    for i, (video_file, sm, ctx) in enumerate(files, 1):
        if ui.is_cancelled():
            _log_msg(ui, "<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
            break
        old_name = video_file.name
        _show_active_file(ui, old_name)
        _render_dashboard(ui, i, total, "Video files")

        mp3_path_str = convert_video_to_mp3(video_file)

        if mp3_path_str:
            mp3_path = Path(mp3_path_str)
            _update_manifest_path(sm, video_file, mp3_path)
            if ui.on_detail_update:
                ui.on_detail_update(ctx, old_name, mp3_path.name)
            _log_msg(ui, f"<span style='color: #4ade80;'>[ ✅ ] Extracted Audio: {old_name} -> MP3</span>")
        else:
            _log_msg(ui, f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} (Audio extraction failed)</span>")
            _log_error_to_file(ui.error_log_path, old_name, "Video to MP3 extraction failed")

    _log_msg(ui, "<span style='color: #8A91A6;'>[ ✨ ] Video to MP3 conversion complete!</span>")


# ─────────────────────────────────────────────────────
# Convenience: Glob + Run All (for app.py Download flow)
# ─────────────────────────────────────────────────────

def _glob_files(course_folder: Path, extensions: set) -> list:
    """Glob course folder for files matching extensions, filtering OS junk."""
    if not course_folder.exists():
        return []
    return [
        f for f in course_folder.rglob('*')
        if f.is_file()
        and not f.name.startswith('._')
        and not f.name.startswith('~$')
        and "__MACOSX" not in f.parts
        and f.suffix.lower() in extensions
    ]


def run_all_conversions(course_folder: Path, sm, contract: dict, ui: UIBridge, course_name: str = ''):
    """Run all converters for a single course folder based on contract settings.

    Used by the Download flow in app.py.  Each converter is gated by its
    contract key (e.g. contract['convert_pptx'] == True).
    """
    # Archive Extraction
    if contract.get('convert_zip', False):
        archive_exts = {'.zip', '.tar', '.gz'}
        archive_files = _glob_files(course_folder, archive_exts)
        # Also catch .tar.gz by full name (since .gz alone may match other files)
        extra_targz = [
            f for f in course_folder.rglob('*')
            if f.is_file() and f.name.lower().endswith('.tar.gz')
            and not f.name.startswith('._') and "__MACOSX" not in f.parts
            and f not in archive_files
        ] if course_folder.exists() else []
        archive_files.extend(extra_targz)
        if archive_files:
            run_archive_extraction([(f, sm, None) for f in archive_files], ui)

    # PPTX → PDF
    if contract.get('convert_pptx', False):
        pptx_files = _glob_files(course_folder, {'.ppt', '.pptx', '.pptm', '.pot', '.potx'})
        if pptx_files:
            run_pptx_conversion([(f, sm, None) for f in pptx_files], ui)

    # HTML → Markdown
    if contract.get('convert_html', False):
        html_files = _glob_files(course_folder, {'.html'})
        if html_files:
            run_html_conversion([(f, sm, None) for f in html_files], ui)

    # Code → TXT
    if contract.get('convert_code', False):
        from code_converter import CODE_EXTENSIONS
        code_files = _glob_files(course_folder, CODE_EXTENSIONS)
        if code_files:
            run_code_conversion([(f, sm, None) for f in code_files], ui)

    # URL Compilation
    if contract.get('convert_urls', False):
        run_url_compilation([(course_folder, course_name)], ui)

    # Legacy Word → PDF
    if contract.get('convert_word', False):
        word_files = _glob_files(course_folder, {'.doc', '.rtf', '.odt'})
        if word_files:
            run_word_conversion([(f, sm, None) for f in word_files], ui)

    # Excel → PDF
    if contract.get('convert_excel', False):
        excel_files = _glob_files(course_folder, {'.xlsx', '.xls', '.xlsm'})
        if excel_files:
            run_excel_conversion([(f, sm, None) for f in excel_files], ui)

    # Video → MP3
    if contract.get('convert_video', False):
        video_files = _glob_files(course_folder, {'.mp4', '.mov', '.mkv', '.avi', '.m4v'})
        if video_files:
            run_video_conversion([(f, sm, None) for f in video_files], ui)
