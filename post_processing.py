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
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import theme
from ui_helpers import esc
from engine.progress_dashboard import (
    render_active_file, build_terminal_html,
    log_line, log_divider, log_meta, file_icon_svg,
)

logger = logging.getLogger(__name__)

# ── Color map per conversion type for dashboard accent ──
_COLOR_MAP = {
    'Archives':           '#a78bfa',
    'PowerPoint files':   '#f97316',
    'HTML files':         '#34D399',
    'Code files':         '#FBBF24',
    'Legacy Word files':  theme.BLUE_PRIMARY,
    'Excel files':        '#22c55e',
    'Excel data files':   '#14b8a6',
    'Video files':        theme.WARNING,
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
    pp_success_count: int = 0   # Post-processing files converted successfully
    pp_failure_count: int = 0   # Post-processing files that failed conversion
    generated_sidecar_paths: list = field(default_factory=list)  # _Data.txt paths for UI ledger injection


# ─────────────────────────────────────────────────────
# Shared UI Rendering Helpers
# ─────────────────────────────────────────────────────

def _render_dashboard(ui: UIBridge, current: int, total: int, task_name: str):
    """Render the post-processing progress dashboard into the caller's placeholders."""
    try:
        if ui.is_cancelled():
            return
        accent = _COLOR_MAP.get(task_name, theme.SUCCESS)
        pct = min(100, int((current / total) * 100) if total > 0 else 0)

        ui.header_placeholder.markdown(f'''
        <div style="margin-bottom: 0.5rem;">
            <p style="margin: 0; font-size: 0.8rem; color: {theme.TEXT_SECONDARY}; text-transform: uppercase;">Post-Processing</p>
            <h3 style="margin: 0; padding-top: 0.1rem; color: {theme.TEXT_PRIMARY};">Converting {esc(task_name)}</h3>
        </div>
        ''', unsafe_allow_html=True)

        ui.progress_placeholder.markdown(f'''
        <div style="background-color: {theme.BG_CARD}; border-radius: 8px; width: 100%; height: 24px; position: relative; margin-bottom: 10px;">
            <div style="background-color: {accent}; width: {pct}%; height: 100%; border-radius: 8px; transition: width 0.3s ease;"></div>
            <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: {theme.WHITE}; font-size: 12px; font-weight: bold; text-shadow: 0px 0px 2px rgba(0,0,0,0.5);">
                {pct}%
            </div>
        </div>
        ''', unsafe_allow_html=True)

        ui.metrics_placeholder.markdown(f'''
        <div style="display: flex; justify-content: center; gap: 4rem; background-color: {theme.BG_DARK}; padding: 15px 25px; border-radius: 8px; border: 1px solid {theme.BG_CARD}; margin-top: 5px; margin-bottom: 15px;">
            <div style="display: flex; flex-direction: column; align-items: center;">
                <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Converted</span>
                <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{current} <span style="font-size: 0.9rem; color: {accent};">/ {total}</span></span>
            </div>
            <div style="display: flex; flex-direction: column; align-items: center;">
                <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Type</span>
                <span style="color: {accent}; font-size: 1.2rem; font-weight: bold;">{esc(task_name)}</span>
            </div>
        </div>
        ''', unsafe_allow_html=True)

        # Re-render log so it stays in sync with progress/metrics
        ui.log_placeholder.markdown(build_terminal_html(ui.log_lines), unsafe_allow_html=True)

        time.sleep(0.05)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.debug(f"_render_dashboard swallowed: {type(e).__name__}: {e}")


def _log_msg(ui: UIBridge, msg: str, *, is_error: bool = False):
    """Append a pre-built log-line HTML string, mirror to the Python logger, and re-render."""
    try:
        if ui.is_cancelled():
            return
        plain = re.sub(r'<[^>]+>', ' ', msg).strip()
        if is_error:
            logger.error(plain)
        else:
            logger.info(plain)

        ui.log_lines.append(msg)
        ui.log_placeholder.markdown(build_terminal_html(ui.log_lines), unsafe_allow_html=True)
    except Exception as e:
        logger.debug(f"_log_msg swallowed: {type(e).__name__}: {e}")


def _emit(ui: UIBridge, status: str, text: str, *, filename: str | None = None,
          detail: str | None = None):
    """Build and append one unified post-processing log line.

    status: 'success' | 'error' | 'attention' | 'skip'  -> a normal log row
            'divider'                                    -> a centered phase break
            'meta'                                       -> a quiet centered note
    filename (optional) selects the content-type icon for normal rows.
    """
    if status == 'divider':
        line = log_divider(text)
    elif status == 'meta':
        line = log_meta(text)
    else:
        icon = file_icon_svg(filename) if filename else None
        line = log_line(status, text, icon=icon, detail=detail)
    _log_msg(ui, line, is_error=(status == 'error'))


def _show_active_file(ui: UIBridge, filename: str):
    """Update the active-file indicator during post-processing."""
    try:
        render_active_file(ui.active_file_placeholder, filename, phase='postprocess')
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        pass


# ─────────────────────────────────────────────────────
# Database & Error Helpers
# ─────────────────────────────────────────────────────

def _resolve_conversion_target(sm, src_path, target_ext: str):
    """Pick the OUTPUT path for converting *src_path* (H-7 collision guard).

    Default target is ``<stem><target_ext>`` beside the source. If that file
    already exists, overwriting is allowed ONLY when the manifest proves it is
    this entry's OWN previous conversion product (recorded by
    ``update_converted_file``); anything else - a teacher-provided X.pdf next
    to X.pptx, an X.xlsx whose PDF would collide with X.pptx's, the user's own
    file - diverts to the first free ``<stem> (n)<target_ext>``. The recorded
    product makes the diverted name STABLE across future updates (the next
    re-conversion overwrites its own ``X (1).pdf`` instead of minting X (2)).
    """
    src = Path(src_path)
    default = src.with_suffix(target_ext)

    if sm is not None:
        try:
            src_rel = str(src.relative_to(sm.local_path)).replace('\\', '/')
        except (ValueError, AttributeError):
            src_rel = None
        if src_rel is not None:
            try:
                manifest = sm.load_manifest()
                row_id = None
                for fid, info in manifest.get('files', {}).items():
                    if info.get('local_path', '') == src_rel:
                        row_id = fid
                        break
                if row_id is not None:
                    prod_rel = sm.get_conversion_products().get(str(row_id), '')
                    if prod_rel:
                        prod_path = sm.local_path / prod_rel
                        if (prod_path.suffix.lower() == target_ext.lower()
                                and prod_path.parent == src.parent):
                            return prod_path  # own product → overwrite in place
            except Exception as e:
                logger.debug(f"_resolve_conversion_target ownership lookup failed: {e}")

    if not default.exists():
        return default
    n = 1
    while True:
        cand = default.parent / f"{default.stem} ({n}){default.suffix}"
        if not cand.exists():
            logger.info(
                f"Conversion target '{default.name}' exists and is not this file's "
                f"own product - diverting to '{cand.name}' (H-7)."
            )
            return cand
        n += 1


def _update_manifest_path(sm, original_file: Path, converted_path: Path):
    """Update the sync manifest to point from the original file to the converted file.

    Uses SyncManager exclusively - no raw sqlite3.  Fixes the audit inconsistency.
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
    from ui_helpers import _err_log_lock
    err_file = error_log_path / "download_errors.txt"
    try:
        error_log_path.mkdir(parents=True, exist_ok=True)
        with _err_log_lock:
            with open(err_file, "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] [Post-Processing] {filename}: {error_msg}\n")
    except OSError:
        pass


def _applescript_last_error() -> tuple[str, str | None]:
    """Describe the most recent macOS AppleScript conversion failure.

    Returns (per_file_suffix, fatal_phase_message). per_file_suffix is
    appended to the generic "Conversion failed" line so the user sees the
    real reason (timeout, permission, ...). fatal_phase_message is non-None
    for failures that will identically doom every remaining file in the
    phase (Automation/TCC permission denied, Office app missing) - callers
    abort early with one actionable message instead of spamming dozens of
    generic errors.
    """
    if sys.platform != 'darwin':
        return '', None
    try:
        from engine.applescript_bridge import get_last_error, FATAL_CATEGORIES
    except ImportError:
        return '', None
    last = get_last_error()
    if not last:
        return '', None
    category, detail = last
    short = detail if len(detail) <= 160 else detail[:157] + '…'
    return f" - {short}", (detail if category in FATAL_CATEGORIES else None)


def _abort_applescript_phase(ui: UIBridge, fatal_msg: str, remaining: int, phase_label: str) -> None:
    """Log a single actionable message and mark the remaining files as skipped."""
    if remaining > 0:
        ui.pp_failure_count += remaining
    _emit(ui, 'error', fatal_msg, detail=f"skipping remaining {remaining} {phase_label} file(s)")


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
    try:
        from archive_extractor import extract_archive
    except ImportError as _imp_err:
        logger.error(f"archive_extractor unavailable: {_imp_err}")
        _emit(ui, 'error', "Archive extraction unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    _emit(ui, 'divider', f"Extracting {total} archive files")
    _render_dashboard(ui, 0, total, "Archives")
    time.sleep(0.2)

    for i, (archive_file, sm, ctx) in enumerate(files, 1):
        if ui.is_cancelled():
            _emit(ui, 'divider', "Process cancelled by user")
            break
        old_name = archive_file.name
        _show_active_file(ui, old_name)

        success = extract_archive(archive_file)

        if success:
            # No manifest update needed - the Sync Engine bypass will
            # silently ignore the missing archive on future sync runs.
            _emit(ui, 'success', old_name, filename=old_name)
            ui.pp_success_count += 1
        else:
            _emit(ui, 'error', old_name, filename=old_name, detail='Extraction failed')
            _log_error_to_file(ui.error_log_path, old_name, "Archive extraction failed")
            ui.pp_failure_count += 1
        _render_dashboard(ui, i, total, "Archives")

    _emit(ui, 'meta', "Archive extraction complete")
    ui.active_file_placeholder.empty()


def run_pptx_conversion(files, ui: UIBridge):
    """Convert PowerPoint files to PDF."""
    if not files:
        return
    try:
        from pdf_converter import PowerPointToPDF
    except ImportError as _imp_err:
        logger.error(f"pdf_converter unavailable: {_imp_err}")
        _emit(ui, 'error', "PowerPoint conversion unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    pptx_error_log = ui.error_log_path

    _emit(ui, 'divider', f"Converting {total} PowerPoint files to PDF")
    _render_dashboard(ui, 0, total, "PowerPoint files")
    time.sleep(0.2)

    with PowerPointToPDF(error_log_path=pptx_error_log) as converter:
        # L-6: Guard COM init failure - self.app is None when CoInitialize or
        # DispatchEx failed. Without this check the loop runs silently with no
        # conversions and no error visible to the user.
        if getattr(converter, 'app', None) is None and sys.platform != 'darwin':
            _emit(ui, 'error', "PowerPoint COM init failed - conversions skipped")
            ui.pp_failure_count += total
        else:
            for i, (pptx_file, sm, ctx) in enumerate(files, 1):
                if ui.is_cancelled():
                    _emit(ui, 'divider', "Process cancelled by user")
                    break
                old_name = pptx_file.name
                _show_active_file(ui, old_name)

                pdf_path_str = converter.convert(
                    pptx_file, dst=_resolve_conversion_target(sm, pptx_file, '.pdf'))

                if pdf_path_str:
                    pdf_path = Path(pdf_path_str)
                    _update_manifest_path(sm, pptx_file, pdf_path)
                    if ui.on_detail_update:
                        ui.on_detail_update(ctx, old_name, pdf_path.name)
                    _emit(ui, 'success', old_name, filename=old_name, detail='→ PDF')
                    ui.pp_success_count += 1
                else:
                    _reason, _fatal = _applescript_last_error()
                    _emit(ui, 'error', old_name, filename=old_name, detail=f'Conversion failed{_reason}')
                    _log_error_to_file(ui.error_log_path, old_name, f"PDF conversion failed{_reason}")
                    ui.pp_failure_count += 1
                    if _fatal:
                        _abort_applescript_phase(ui, _fatal, total - i, "PowerPoint")
                        _render_dashboard(ui, i, total, "PowerPoint files")
                        break
                _render_dashboard(ui, i, total, "PowerPoint files")

    _emit(ui, 'meta', "PDF conversion complete")
    ui.active_file_placeholder.empty()


def run_html_conversion(files, ui: UIBridge):
    """Convert Canvas Pages (HTML) to Markdown."""
    if not files:
        return
    try:
        from md_converter import convert_html_to_md
    except ImportError as _imp_err:
        logger.error(f"md_converter unavailable: {_imp_err}")
        _emit(ui, 'error', "HTML→Markdown conversion unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    _emit(ui, 'divider', f"Converting {total} HTML files to Markdown")
    _render_dashboard(ui, 0, total, "HTML files")
    time.sleep(0.2)

    for i, (html_file, sm, ctx) in enumerate(files, 1):
        if ui.is_cancelled():
            _emit(ui, 'divider', "Process cancelled by user")
            break
        old_name = html_file.name
        _show_active_file(ui, old_name)

        md_path = convert_html_to_md(
            html_file, dst=_resolve_conversion_target(sm, html_file, '.md'))

        if md_path:
            _update_manifest_path(sm, html_file, md_path)
            if ui.on_detail_update:
                ui.on_detail_update(ctx, old_name, md_path.name)
            _emit(ui, 'success', md_path.name, filename=md_path.name)
            ui.pp_success_count += 1
        else:
            _emit(ui, 'error', old_name, filename=old_name, detail='Conversion failed')
            _log_error_to_file(ui.error_log_path, old_name, "Markdown conversion failed")
            ui.pp_failure_count += 1
        _render_dashboard(ui, i, total, "HTML files")

    _emit(ui, 'meta', "Markdown conversion complete")
    ui.active_file_placeholder.empty()


def run_code_conversion(files, ui: UIBridge):
    """Convert code & data files to .txt."""
    if not files:
        return
    try:
        from code_converter import convert_code_to_txt
    except ImportError as _imp_err:
        logger.error(f"code_converter unavailable: {_imp_err}")
        _emit(ui, 'error', "Code→TXT conversion unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    _emit(ui, 'divider', f"Converting {total} code & data files to TXT")
    _render_dashboard(ui, 0, total, "Code files")
    time.sleep(0.2)

    for i, (code_file, sm, ctx) in enumerate(files, 1):
        if ui.is_cancelled():
            _emit(ui, 'divider', "Process cancelled by user")
            break
        old_name = code_file.name
        _show_active_file(ui, old_name)

        txt_path_str = convert_code_to_txt(code_file)

        if txt_path_str:
            txt_path = Path(txt_path_str)
            _update_manifest_path(sm, code_file, txt_path)
            if ui.on_detail_update:
                ui.on_detail_update(ctx, old_name, txt_path.name)
            _emit(ui, 'success', old_name, filename=old_name, detail='→ TXT')
            ui.pp_success_count += 1
        else:
            _emit(ui, 'error', old_name, filename=old_name, detail='Conversion failed')
            _log_error_to_file(ui.error_log_path, old_name, "Code to TXT conversion failed")
            ui.pp_failure_count += 1
        _render_dashboard(ui, i, total, "Code files")

    _emit(ui, 'meta', "Code to TXT conversion complete")
    ui.active_file_placeholder.empty()


def run_url_compilation(folders, ui: UIBridge):
    """Compile .url shortcuts into a NotebookLM text file.

    folders: list of (course_folder_path: Path, course_name: str)
    """
    if not folders:
        return
    try:
        from url_compiler import compile_urls_to_txt
    except ImportError as _imp_err:
        logger.error(f"url_compiler unavailable: {_imp_err}")
        _emit(ui, 'error', "URL compilation unavailable: module not found", detail=str(_imp_err))
        return

    _emit(ui, 'divider', "Compiling external links")

    for course_folder, course_name in folders:
        if ui.is_cancelled():
            _emit(ui, 'divider', "Process cancelled by user")
            break

        if course_folder.exists():
            try:
                compiled_path, processed_shortcuts = compile_urls_to_txt(course_folder, course_name)
            except Exception as e:
                _emit(ui, 'error', f"URL compilation failed: {course_name}", detail=str(e))
                _log_error_to_file(ui.error_log_path, course_name, f"URL compilation error: {e}")
                ui.pp_failure_count += 1
                continue
            if compiled_path:
                _emit(ui, 'success', "Compiled_External_Links.txt", filename="Compiled_External_Links.txt", detail=course_name)
                ui.pp_success_count += 1

            # Delete processed shortcuts whether new links were compiled or they were
            # already in the file (deduplication handled inside compile_urls_to_txt).
            for shortcut in processed_shortcuts:
                try:
                    shortcut.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Failed to purely delete shortcut {shortcut.name}: {e}")
                    _log_error_to_file(ui.error_log_path, shortcut.name, f"Shortcut deletion failed: {e}")
                    continue


def run_word_conversion(files, ui: UIBridge):
    """Convert legacy Word documents (.doc, .rtf, .odt) to PDF."""
    if not files:
        return
    try:
        from word_converter import WordToPDF
    except ImportError as _imp_err:
        logger.error(f"word_converter unavailable: {_imp_err}")
        _emit(ui, 'error', "Word→PDF conversion unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    _emit(ui, 'divider', f"Converting {total} legacy Word files to PDF")
    _render_dashboard(ui, 0, total, "Legacy Word files")
    time.sleep(0.2)

    with WordToPDF() as converter:
        if getattr(converter, 'app', None) is None and sys.platform != 'darwin':
            _emit(ui, 'error', "Word COM init failed - conversions skipped")
            ui.pp_failure_count += total
        else:
            for i, (word_file, sm, ctx) in enumerate(files, 1):
                if ui.is_cancelled():
                    _emit(ui, 'divider', "Process cancelled by user")
                    break
                old_name = word_file.name
                _show_active_file(ui, old_name)

                pdf_path_str = converter.convert(
                    word_file, dst=_resolve_conversion_target(sm, word_file, '.pdf'))

                if pdf_path_str:
                    pdf_path = Path(pdf_path_str)
                    _update_manifest_path(sm, word_file, pdf_path)
                    if ui.on_detail_update:
                        ui.on_detail_update(ctx, old_name, pdf_path.name)
                    _emit(ui, 'success', old_name, filename=old_name, detail='→ PDF')
                    ui.pp_success_count += 1
                else:
                    _reason, _fatal = _applescript_last_error()
                    _emit(ui, 'error', old_name, filename=old_name, detail=f'Conversion failed{_reason}')
                    _log_error_to_file(ui.error_log_path, old_name, f"Word to PDF conversion failed{_reason}")
                    ui.pp_failure_count += 1
                    if _fatal:
                        _abort_applescript_phase(ui, _fatal, total - i, "Word")
                        _render_dashboard(ui, i, total, "Legacy Word files")
                        break
                _render_dashboard(ui, i, total, "Legacy Word files")

    _emit(ui, 'meta', "Legacy Word to PDF conversion complete")
    ui.active_file_placeholder.empty()


def run_excel_data_conversion(files, ui: UIBridge):
    """Extract Excel data into a structured _Data.txt sidecar.

    Produces a single _Data.txt file per workbook containing Markdown-headed
    sheet sections with CSV-formatted cell data, optimized for AI ingestion.

    Does NOT delete the original file or update the sync manifest - the
    _Data.txt is an untracked secondary artifact (Approach A).
    """
    if not files:
        return
    try:
        from excel_converter import ExcelToData
    except ImportError as _imp_err:
        logger.error(f"excel_converter (ExcelToData) unavailable: {_imp_err}")
        _emit(ui, 'error', "Excel data extraction unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    _emit(ui, 'divider', f"Extracting data from {total} Excel files")
    _render_dashboard(ui, 0, total, "Excel data files")
    time.sleep(0.2)

    with ExcelToData() as extractor:
        for i, (excel_file, sm, ctx) in enumerate(files, 1):
            if ui.is_cancelled():
                _emit(ui, 'divider', "Process cancelled by user")
                break
            old_name = excel_file.name
            _show_active_file(ui, old_name)

            try:
                abs_path = str(excel_file.absolute())
                data_path, data_error_msg = extractor.convert(abs_path)

                if data_path:
                    data_name = Path(data_path).name
                    # Do NOT update manifest - _Data.txt is an untracked sidecar
                    _emit(ui, 'success', old_name, filename=old_name, detail=f'→ {data_name}')
                    ui.pp_success_count += 1
                    ui.generated_sidecar_paths.append(str(data_path))
                else:
                    err_detail = data_error_msg if data_error_msg else "Excel data extraction failed"
                    _emit(ui, 'error', old_name, filename=old_name, detail=err_detail)
                    _log_error_to_file(ui.error_log_path, old_name, err_detail)
                    ui.pp_failure_count += 1
            except Exception as e:
                _emit(ui, 'error', old_name, filename=old_name, detail='System Error')
                _log_error_to_file(ui.error_log_path, old_name, f"System Error: {e}")
                ui.pp_failure_count += 1
            _render_dashboard(ui, i, total, "Excel data files")
    _emit(ui, 'meta', "Excel AI data extraction complete")
    ui.active_file_placeholder.empty()


def run_excel_conversion(files, ui: UIBridge):
    """Convert Excel files (.xlsx, .xls, .xlsm) to PDF.

    AUDIT FIX: Uses _update_manifest_path (SyncManager) instead of raw sqlite3.
    """
    if not files:
        return
    try:
        from excel_converter import ExcelToPDF
    except ImportError as _imp_err:
        logger.error(f"excel_converter (ExcelToPDF) unavailable: {_imp_err}")
        _emit(ui, 'error', "Excel→PDF conversion unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    _emit(ui, 'divider', f"Converting {total} Excel files to PDF")
    _render_dashboard(ui, 0, total, "Excel files")
    time.sleep(0.2)

    with ExcelToPDF() as converter:
        if getattr(converter, 'app', None) is None and sys.platform != 'darwin':
            _emit(ui, 'error', "Excel COM init failed - conversions skipped")
            ui.pp_failure_count += total
        else:
            for i, (excel_file, sm, ctx) in enumerate(files, 1):
                if ui.is_cancelled():
                    _emit(ui, 'divider', "Process cancelled by user")
                    break
                old_name = excel_file.name
                _show_active_file(ui, old_name)

                abs_path = str(excel_file.absolute())
                new_pdf_path, excel_error_msg = converter.convert(
                    abs_path, dst=_resolve_conversion_target(sm, excel_file, '.pdf'))

                if new_pdf_path:
                    pdf_path = Path(new_pdf_path)
                    _update_manifest_path(sm, excel_file, pdf_path)
                    if ui.on_detail_update:
                        ui.on_detail_update(ctx, old_name, pdf_path.name)
                    _emit(ui, 'success', old_name, filename=old_name, detail='→ PDF')
                    ui.pp_success_count += 1
                else:
                    _reason, _fatal = _applescript_last_error()
                    err_detail = excel_error_msg if excel_error_msg else f"Excel to PDF conversion failed{_reason}"
                    _emit(ui, 'error', old_name, filename=old_name, detail=err_detail)
                    _log_error_to_file(ui.error_log_path, old_name, err_detail)
                    ui.pp_failure_count += 1
                    if _fatal:
                        _abort_applescript_phase(ui, _fatal, total - i, "Excel")
                        _render_dashboard(ui, i, total, "Excel files")
                        break
                _render_dashboard(ui, i, total, "Excel files")

    _emit(ui, 'meta', "Excel to PDF conversion complete")
    ui.active_file_placeholder.empty()


def run_video_conversion(files, ui: UIBridge):
    """Extract audio from video files (.mp4, .mov, .mkv) to MP3."""
    if not files:
        return
    try:
        from video_converter import convert_video_to_mp3
    except ImportError as _imp_err:
        logger.error(f"video_converter unavailable: {_imp_err}")
        _emit(ui, 'error', "Video→MP3 conversion unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    _emit(ui, 'divider', f"Extracting audio from {total} video files")
    _render_dashboard(ui, 0, total, "Video files")
    time.sleep(0.2)

    for i, (video_file, sm, ctx) in enumerate(files, 1):
        if ui.is_cancelled():
            _emit(ui, 'divider', "Process cancelled by user")
            break
        old_name = video_file.name
        _show_active_file(ui, old_name)

        mp3_path_str = convert_video_to_mp3(
            video_file, dst=_resolve_conversion_target(sm, video_file, '.mp3'))

        if mp3_path_str:
            mp3_path = Path(mp3_path_str)
            _update_manifest_path(sm, video_file, mp3_path)
            if ui.on_detail_update:
                ui.on_detail_update(ctx, old_name, mp3_path.name)
            _emit(ui, 'success', old_name, filename=old_name, detail='→ MP3')
            ui.pp_success_count += 1
        else:
            _emit(ui, 'error', old_name, filename=old_name, detail='Audio extraction failed')
            _log_error_to_file(ui.error_log_path, old_name, "Video to MP3 extraction failed")
            ui.pp_failure_count += 1
        _render_dashboard(ui, i, total, "Video files")

    _emit(ui, 'meta', "Video to MP3 conversion complete")
    ui.active_file_placeholder.empty()


# ─────────────────────────────────────────────────────
# Convenience: Glob + Run All (for app.py Download flow)
# ─────────────────────────────────────────────────────

_PACKAGE_DIRS = {
    'node_modules', '.git', '__pycache__', '.cache',
    'venv', '.venv', 'env', '.env',
    'site-packages', 'dist-packages',
}

def _glob_files(course_folder: Path, extensions: set, explicit_files: list = None) -> list:
    """Glob course folder for files matching extensions, filtering OS junk and package dirs."""
    if not course_folder.exists():
        return []

    explicit_set = {Path(p).resolve() for p in explicit_files} if explicit_files else None

    return [
        f for f in course_folder.rglob('*')
        if f.is_file()
        and not f.name.startswith('._')
        and not f.name.startswith('~$')
        and "__MACOSX" not in f.parts
        and not _PACKAGE_DIRS.intersection(f.parts)
        and f.suffix.lower() in extensions
        and not ('.part.' in f.name.lower() or f.name.lower().endswith('.part'))
        and (not explicit_set or f.resolve() in explicit_set)
    ]


def run_all_conversions(course_folder: Path, sm, contract: dict, ui: UIBridge, course_name: str = '', explicit_files: list = None):
    """Run all converters for a single course folder based on contract settings.

    Used by the Download flow in app.py.  Each converter is gated by its
    contract key (e.g. contract['convert_pptx'] == True).
    """
    # Archive Extraction
    if contract.get('convert_zip', False):
        archive_exts = {'.zip', '.tar'}
        archive_files = _glob_files(course_folder, archive_exts, explicit_files)
        # Also catch .tar.gz by full name (since .gz alone may match other files)
        explicit_set = {Path(p).resolve() for p in explicit_files} if explicit_files else None
        extra_targz = [
            f for f in course_folder.rglob('*')
            if f.is_file() and f.name.lower().endswith('.tar.gz')
            and not f.name.startswith('._') and "__MACOSX" not in f.parts
            and f not in archive_files
            and (not explicit_set or f.resolve() in explicit_set)
        ] if course_folder.exists() else []
        archive_files.extend(extra_targz)
        if archive_files:
            run_archive_extraction([(f, sm, course_name) for f in archive_files], ui)

    # PPTX → PDF
    if contract.get('convert_pptx', False):
        pptx_files = _glob_files(course_folder, {'.ppt', '.pptx', '.pptm', '.pot', '.potx'}, explicit_files)
        if pptx_files:
            run_pptx_conversion([(f, sm, course_name) for f in pptx_files], ui)

    # HTML → Markdown
    if contract.get('convert_html', False):
        html_files = _glob_files(course_folder, {'.html'}, explicit_files)
        if html_files:
            run_html_conversion([(f, sm, course_name) for f in html_files], ui)

    # Code → TXT
    if contract.get('convert_code', False):
        from code_converter import CODE_EXTENSIONS
        code_files = _glob_files(course_folder, CODE_EXTENSIONS, explicit_files)
        if code_files:
            run_code_conversion([(f, sm, course_name) for f in code_files], ui)

    # URL Compilation
    if contract.get('convert_urls', False):
        if explicit_files is not None:
             # PATH NORMALIZATION CONSTRAINT: Resolve paths to avoid slashes breaking isolation
             has_shortcut = any(Path(p).resolve().suffix.lower() in {'.url', '.webloc'} for p in explicit_files)
             if has_shortcut:
                 run_url_compilation([(course_folder, course_name)], ui)
        else:
             run_url_compilation([(course_folder, course_name)], ui)

    # Legacy Word → PDF
    if contract.get('convert_word', False):
        word_files = _glob_files(course_folder, {'.doc', '.rtf', '.odt'}, explicit_files)
        if word_files:
            run_word_conversion([(f, sm, course_name) for f in word_files], ui)

    # Excel → AI Data + PDF (single toggle, dual pipeline)
    # CRITICAL ORDERING: Data extraction FIRST (reads .xlsx), PDF SECOND (deletes .xlsx).
    # Each call to _glob_files produces an independent list - no iterator exhaustion.
    if contract.get('convert_excel', False):
        # .xls (Excel 97-2003) is binary format openpyxl cannot read; exclude from data extraction.
        # ExcelToPDF via COM/AppleScript handles .xls fine - it stays in the PDF glob below.
        excel_data_files = _glob_files(course_folder, {'.xlsx', '.xlsm'}, explicit_files)
        if excel_data_files:
            run_excel_data_conversion([(f, sm, course_name) for f in excel_data_files], ui)

        excel_pdf_files = _glob_files(course_folder, {'.xlsx', '.xls', '.xlsm'}, explicit_files)
        if excel_pdf_files:
            run_excel_conversion([(f, sm, course_name) for f in excel_pdf_files], ui)

    # Video → MP3
    if contract.get('convert_video', False):
        video_files = _glob_files(course_folder, {'.mp4', '.mov', '.mkv', '.avi', '.m4v'}, explicit_files)
        if video_files:
            run_video_conversion([(f, sm, course_name) for f in video_files], ui)
