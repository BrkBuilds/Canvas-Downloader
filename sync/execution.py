"""
sync.execution — Sync download execution loop and post-processing.

Extracted from ``sync_ui.py`` L4107-5039 (Phase 4).
Strict physical move — NO logic changes.

Contains:
  - ``run_sync()``  (was ``_run_sync``)
  - ``download_sync_files_batch()`` async loop (inner function)
  - Post-processing pipeline orchestration
  - Sync history recording

CRITICAL: This module contains file-level mutexes, rate-limit handlers,
and delayed SQLite ACID commits.  Do NOT refactor, clean up, or
optimise the async logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import time as _time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import aiofiles
import aiohttp
import streamlit as st

import theme
from canvas_logic import CanvasManager
from sync_manager import (
    SyncFileInfo, SyncHistoryManager, CanvasFileInfo,
)
from ui_helpers import (
    esc,
    render_progress_bar,
    render_sync_wizard,
    friendly_course_name,
    robust_filename_normalize,
    make_long_path,
)
from styles import inject_css
from engine.progress_dashboard import build_metrics_html, build_terminal_html

logger = logging.getLogger(__name__)


def run_sync():
    """Execute the full sync pipeline: download files, post-process, record history.

    Strict physical move of the original ``_run_sync`` from ``sync_ui.py``.
    No logic has been changed.
    """
    # --- Backward-compatible import of persistence helper ---
    from sync.persistence import update_last_synced_batch as _update_last_synced_batch
    # --- Backward-compatible import of cancel callback ---
    from core.cancellation import cancel_sync as cancel_process_callback

    # Initialize phase flags explicitly at start of run — but ONLY if not already cancelled.
    # If a Phase 3 cancel triggered the rerun, we must preserve is_post_processing=True
    # so that _show_sync_cancelled can read it for the correct status message.
    if not st.session_state.get('sync_cancel_requested', False) and not st.session_state.get('sync_cancelled', False):
        st.session_state['is_post_processing'] = False

    # Step wizard
    render_sync_wizard(st, 3)

    st.markdown(
        f'<div class="step-header">{"Syncing..."}</div>',
        unsafe_allow_html=True,
    )

    sync_selections = st.session_state.get('sync_selections', [])
    if not sync_selections:
        st.session_state['download_status'] = 'sync_complete'
        st.session_state['synced_count'] = 0
        st.rerun()

    status_text = st.empty()
    progress_container = st.empty()
    metrics_dashboard = st.empty()
    active_file_placeholder = st.empty()
    log_container = st.empty()

    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    cancel_placeholder = st.empty()
    if cancel_placeholder.button('Cancel Sync', key="cancel_sync_btn", type="secondary"):
        st.session_state['sync_cancelled'] = True
        st.session_state['sync_cancel_requested'] = True
        
        # Smart routing:
        if st.session_state.get('qs_cancel_route', False):
            st.session_state['step'] = 1
            st.session_state['download_status'] = 'select'
            st.session_state.pop('qs_cancel_route', None)
        else:
            st.session_state['step'] = 2
            st.session_state['download_status'] = 'review'
            
        st.rerun()

    # --- Inject red hover CSS for cancel buttons (dynamic — requires theme vars) ---
    st.markdown(f"""
    <style>
    .st-key-cancel_download_btn button:hover,
    .st-key-cancel_pp_download button:hover,
    .st-key-cancel_sync_btn button:hover,
    .st-key-cancel_pp_btn button:hover {{
        border-color: {theme.ERROR} !important;
        background-color: {theme.ERROR_BG} !important;
        color: {theme.ERROR} !important;
        transition: all 0.2s ease-in-out;
    }}
    </style>
    """, unsafe_allow_html=True)

    # --- Hide stale UI elements from previous step (extracted to styles/) ---
    inject_css('sync_progress.css')
    st.markdown(
        '<div class="sync-progress-end-marker"></div>',
        unsafe_allow_html=True,
    )

    # Accumulate metrics if this is a Retry pass, otherwise reset for fresh syncs
    is_retry = bool(st.session_state.get('retry_selections'))
    if is_retry:
        synced_counter = [
            st.session_state.get('synced_count', 0),
            st.session_state.get('synced_bytes', 0)
        ]
    else:
        synced_counter = [0, 0]  # [count, bytes]
    error_list = []

    # --- Task 2 Fix: Wipe error state at start of every sync run ---
    st.session_state['sync_errors'] = []

    # Format helpers for the injected HTML UI
    def format_time(seconds):
        if seconds < 0 or seconds > 86400: return "--:--"
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"

    def render_metrics_html_compat(current_file_idx, total_files, d_mb, t_mb, speed_mb_s, eta_string):
        """Backward-compatible alias for build_metrics_html (engine)."""
        return build_metrics_html(current_file_idx, total_files, d_mb, t_mb, speed_mb_s, eta_string)
        
    def render_terminal_html_compat(lines):
        """Backward-compatible alias for build_terminal_html (engine)."""
        return build_terminal_html(lines)

    async def download_sync_files_batch(sync_api_token, sync_api_url):
        cm = CanvasManager(sync_api_token, sync_api_url)
        timeout = aiohttp.ClientTimeout(total=None, sock_read=60, sock_connect=15)
        
        # Respect global concurrency limit from session state
        concurrent_limit = st.session_state.get('concurrent_downloads', 5)
        sem = asyncio.Semaphore(concurrent_limit)
        
        # Track synced files per pair for the results screen dropdowns
        # Key: pair_idx (int), Value: list of strings (filenames)
        synced_details = defaultdict(list)
        retry_selections = []
        
        async with aiohttp.ClientSession(
            headers={'Authorization': f'Bearer {cm.api_key}'}, timeout=timeout
        ) as session:
            total_files = sum(
                len(sel['new']) + len(sel['updates']) + len(sel['redownload'])
                for sel in sync_selections
            )
            total_mb = 0.0
            for sel in sync_selections:
                total_mb += sum(getattr(f, 'size', 0) or 0 for f in sel['new'])
                total_mb += sum(getattr(f, 'size', 0) or 0 for f, info in sel['updates'])
                cfmap = {str(f.id): f for f in sel['res_data']['canvas_files']}
                for si in sel['redownload']:
                    cf = cfmap.get(str(si.canvas_file_id))
                    total_mb += (getattr(cf, 'size', 0) or getattr(si, 'original_size', 0) or 0)
            total_mb /= (1024 * 1024)

            current_file = 0
            downloaded_mb = 0.0
            total_pairs = len(sync_selections)

            render_progress_bar(progress_container, 0, total_files)
            
            # Setup Tracking Variables
            start_time = _time.time()
            last_ui_update = 0
            terminal_log = deque(maxlen=10)
            
            # Initial UI Draw
            metrics_dashboard.markdown(render_metrics_html_compat(0, total_files, 0.0, total_mb, 0.0, "--:--"), unsafe_allow_html=True)
            active_file_placeholder.markdown("<p style='color: {theme.TERMINAL_TEXT}; font-size: 0.9rem;'>🔄 Preparing sync...</p>", unsafe_allow_html=True)
            log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
            progress_container.progress(0, text="0%")

            for pair_idx, sel in enumerate(sync_selections):
                if st.session_state.get('sync_cancel_requested', False):
                    break
                
                failed_files_for_pair = []

                res_data = sel['res_data']
                sync_mgr = res_data.get('sync_manager')
                manifest = res_data.get('manifest')
                canvas_files_map = {f.id: f for f in res_data['canvas_files']}
                pair = res_data['pair']

                course_name = friendly_course_name(pair['course_name'])

                if sync_mgr is None:
                    error_list.append(f"Skipping {course_name}: Database failed to initialize.")
                    failed_files_for_pair.extend(sel.get('new', []) + sel.get('updates', []))
                    continue
                header_html = f"""
                <div style="margin-bottom: 0.5rem;">
                    <p style="margin: 0; font-size: 0.8rem; color: {theme.TEXT_SECONDARY}; text-transform: uppercase;">📦 Course {pair_idx + 1} of {total_pairs}</p>
                    <h3 style="margin: 0; padding-top: 0.1rem; color: {theme.TEXT_PRIMARY};">{esc(course_name)}</h3>
                </div>
                """
                status_text.markdown(header_html, unsafe_allow_html=True)
                
                # Re-hydration Injection
                course = res_data.get('course')
                if course is None:
                    terminal_log.append(f"<span style='color:{theme.TEXT_SECONDARY}'>[ℹ️] Establishing secure connection to {esc(course_name)}...</span>")
                    log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                    try:
                        course = await asyncio.to_thread(cm.get_course, pair['course_id'])
                        res_data['course'] = course
                    except Exception as e:
                        err_str = f"Connection failure to {esc(course_name)}: {str(e)}"
                        error_list.append(err_str)
                        terminal_log.append(f"<span style='color:{theme.ERROR_ALT}'>[❌] Reconnection Failed: {esc(course_name)} ({str(e)})</span>")
                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                        failed_files_for_pair.extend(sel.get('new', []))
                        continue

                # Task 4: State Leakage Fix
                # We save the auto-healed manifest + any newly ignored files only ONCE per folder, 
                # exactly when the sync is executing (after user confirmation)
                if sel['ignore']:
                    manifest = sync_mgr.mark_files_ignored(manifest, sel['ignore'])
                # Selective persist: only save ignored/healed entries to DB before download
                # (NOT the full auto-discovered manifest, to avoid premature commit)
                for file_id_str, entry in manifest.get('files', {}).items():
                    if entry.get('is_ignored'):
                        sync_mgr._save_single_file_to_db(entry)

                all_files = list(sel['new']) + [f for f, info in sel['updates']]
                for sync_info in sel['redownload']:
                    # 1. Direct ID match (Real Files)
                    if str(sync_info.canvas_file_id) in {str(k) for k in canvas_files_map.keys()}:
                        # Map string ID to the proper canvas file map object safely
                        _mapped_id = next(k for k in canvas_files_map.keys() if str(k) == str(sync_info.canvas_file_id))
                        all_files.append(canvas_files_map[_mapped_id])
                    
                    # --- CRITICAL PATCH: Synthetic Proxy Reconstruction ---
                    elif int(sync_info.canvas_file_id) < 0:
                        import types
                        proxy = types.SimpleNamespace(
                            id=int(sync_info.canvas_file_id),
                            filename=sync_info.canvas_filename,
                            display_name=sync_info.canvas_filename,
                            size=getattr(sync_info, 'original_size', 0),
                            modified_at=getattr(sync_info, 'canvas_updated_at', ''),
                            url=""
                        )
                        all_files.append(proxy)
                    # ----------------------------------------------------
                    
                    else:
                        # 3. Fallback: Try to match by filename (handle URL encoding + vs space, case insensitivity)
                        # Files may be re-uploaded (new ID) but keep same name.
                        target_name = robust_filename_normalize(sync_info.canvas_filename)
                        found_file = None
                        
                        for f in res_data['canvas_files']:
                            # Compare robustly
                            if robust_filename_normalize(f.filename) == target_name:
                                found_file = f
                                break
                        
                        if found_file:
                            # Prevent duplicates: If file is already in 'new' list (new ID) but matched here via fallback
                            if found_file not in all_files:
                                all_files.append(found_file)
                        else:
                            # Log error if file is truly gone
                            error_list.append(f"File removed from Canvas before download: {sync_info.canvas_filename}")

                local_path = sync_mgr.local_path
                Path(make_long_path(local_path)).mkdir(parents=True, exist_ok=True)

                for file in all_files:
                    if st.session_state.get('sync_cancel_requested', False):
                        break

                    current_file += 1
                    display_file_name = file.display_name or file.filename
                    
                    # UNCONDITIONAL status text update — fires instantly for every file (no throttle)
                    active_file_placeholder.markdown(f"<div style='color: {theme.ACCENT_LINK}; margin-bottom: 10px; font-weight: 500;'>🔄 Currently downloading: {esc(display_file_name)}...</div>", unsafe_allow_html=True)
                    
                    # Throttled progress update (Prevent Streamlit from choking on rapid tiny files)
                    curr_time = _time.time()
                    if curr_time - last_ui_update > 0.4:
                        pct = min(1.0, (current_file - 1) / total_files) if total_files > 0 else 0.0
                        progress_container.progress(pct, text=f"{int(pct * 100)}%")
                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                        last_ui_update = curr_time

                    try:
                        # file.filename may contain subfolder prefixes
                        # (e.g. "Assignments/Name/doc.pdf"). Sanitize each
                        # path component individually to preserve hierarchy,
                        # then extract only the basename — the parent
                        # directory is already handled by calc_path routing.
                        _fn_parts = Path(file.filename).parts
                        filename = cm._sanitize_filename(_fn_parts[-1]) if _fn_parts else cm._sanitize_filename(file.filename)
                        
                        # Task 4: Target Path Resolution
                        target_dir = local_path
                        calc_path = getattr(file, '_target_local_path', '')
                        
                        # Fallback to sync_info properties explicitly
                        if not calc_path:
                            for f, info in sel['res_data']['result'].updated_files:
                                if f == file:
                                    calc_path = info.target_local_path
                                    break
                            
                        if not calc_path:
                            for info in sel['redownload']:
                                if str(info.canvas_file_id) == str(getattr(file, 'id', None)) or str(info.canvas_file_id) == str(getattr(file, 'canvas_file_id', None)):
                                    calc_path = info.target_local_path
                                    break
                                    
                        if calc_path:
                            calc_dir = Path(calc_path).parent
                            if str(calc_dir) != '.':
                                target_dir = local_path / calc_dir
                                
                        Path(make_long_path(target_dir)).mkdir(parents=True, exist_ok=True)
                        
                        filepath = target_dir / filename

                        is_update = file in sel['updates']
                        if is_update and filepath.exists():
                            base = filepath.stem
                            ext = filepath.suffix
                            filepath = local_path / f"{base}{'_NewVersion'}{ext}"
                            filepath = cm._handle_conflict(filepath)
                        elif filepath.exists():
                            filepath = cm._handle_conflict(filepath)

                        if getattr(file, 'id', 0) < 0:
                            # ── Secondary Content Entities (Assignment, Quiz, etc.) ──
                            from sync_manager import is_secondary_id, secondary_id_type
                            _sec_entity_type = secondary_id_type(file.id)
                            if _sec_entity_type != 'attachment' and _sec_entity_type not in ('module_item', 'unknown'):
                                # Load secondary contract for this pair
                                _raw_sec = sync_mgr._load_metadata('secondary_content_contract')
                                _sec_settings = json.loads(_raw_sec) if _raw_sec else {}

                                try:
                                    sec_filepath, sec_id, sec_attachments, canvas_updated = cm.download_secondary_entity(
                                        course=res_data['course'],
                                        canvas_file_info=file,
                                        base_path=Path(local_path),
                                        sync_manager=sync_mgr,
                                        secondary_content_settings=_sec_settings,
                                        course_name=course_name,
                                    )
                                except Exception as _sec_err:
                                    # Let the error bubble up to the outer retry loop
                                    raise _sec_err

                                if sec_filepath:
                                    synced_counter[0] += 1
                                    st.session_state['sync_cancelled_file_count'] = synced_counter[0]
                                    synced_details[pair_idx].append(sec_filepath.name)
                                    terminal_log.append(f"<span style='color:{theme.SUCCESS_ALT}'>[✅] Synced: </span> {esc(sec_filepath.name)}")
                                    log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)

                                    # ── Inject attachments into the async download queue ──
                                    # Attachments have REAL positive Canvas file IDs, so they
                                    # bypass the `file.id < 0` branch and enter the standard
                                    # HTTP download path with full retry + cancellation support.
                                    if sec_attachments:
                                        from sync_manager import CanvasFileInfo as _CFI
                                        attach_dir = sec_filepath.parent
                                        
                                        # Deduplication guard: prevent double-queueing if
                                        # the attachment was already in the sync selection
                                        # (e.g. both HTML + attachment were locally deleted)
                                        _queued_ids = {getattr(f, 'id', None) for f in all_files}
                                        for att in sec_attachments:
                                            att_id = att.get('id')
                                            att_url = att.get('url', '')
                                            att_filename = att.get('filename', att.get('display_name', 'attachment'))
                                            
                                            if not att_url or not att_id:
                                                continue
                                                
                                            # Guard against cross-queue and intra-document duplicates
                                            if att_id in _queued_ids:
                                                continue  
                                                
                                            # Add the ID to the set to prevent duplicate links 
                                            # within the same HTML document from firing twice
                                            _queued_ids.add(att_id)
                                            att_info = _CFI(
                                                id=att_id,
                                                filename=att_filename,
                                                display_name=att.get('display_name', att_filename),
                                                size=att.get('size', 0),
                                                modified_at=att.get('modified_at', ''),
                                                url=att_url,
                                            )
                                            # Set target path so the download loop routes correctly
                                            try:
                                                att_info._target_local_path = str(
                                                    (attach_dir / cm._sanitize_filename(att_filename)).relative_to(local_path)
                                                )
                                            except ValueError:
                                                # Fallback: attachment dir is outside local_path — use filename only
                                                att_info._target_local_path = cm._sanitize_filename(att_filename)
                                            all_files.append(att_info)
                                            total_files += 1
                                            terminal_log.append(f"<span style='color:{theme.ACCENT_BLUE}'>[📎] Queued attachment: </span> {esc(att_filename)}")
                                            log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                            
                                    # ACID Fix: Delay DB commit until attachments are safely queued
                                    if sync_mgr and sec_id and canvas_updated is not None:
                                        try:
                                            rel_path = str(sec_filepath.relative_to(local_path)).replace('\\', '/')
                                            sync_mgr.record_downloaded_file(
                                                canvas_file_id=sec_id,
                                                canvas_filename=sec_filepath.name,
                                                local_path=rel_path,
                                                canvas_updated_at=canvas_updated,
                                                original_size=0,
                                            )
                                        except Exception:
                                            pass
                                else:
                                    terminal_log.append(f"<span style='color:{theme.ERROR_LIGHT}'>[⚠️] Skipped: </span> {esc(display_file_name)}")
                                    log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                continue

                            # ── Legacy Synthetic Shortcuts (Pages, External URLs) ──
                            Path(make_long_path(filepath.parent)).mkdir(parents=True, exist_ok=True)

                            is_url_ext = filepath.name.lower().endswith('.url') or filepath.name.lower().endswith('.webloc')
                            is_html_ext = filepath.name.lower().endswith('.html')

                            if is_url_ext:
                                if platform.system() == 'Darwin':
                                    import plistlib
                                    plist_data = {'URL': file.url}
                                    async with aiofiles.open(str(make_long_path(filepath)), 'wb') as f:
                                        await f.write(plistlib.dumps(plist_data, fmt=plistlib.FMT_XML))
                                else:
                                    shortcut_content = f"[InternetShortcut]\nURL={file.url}\n"
                                    async with aiofiles.open(str(make_long_path(filepath)), 'w', encoding='utf-8') as f:
                                        await f.write(shortcut_content)
                            elif is_html_ext:
                                html_content = f"<html><body><script>window.location.href='{file.url}';</script></body></html>"
                                async with aiofiles.open(str(make_long_path(filepath)), 'w', encoding='utf-8') as f:
                                    await f.write(html_content)

                            if is_url_ext or is_html_ext:
                                rel_path = filepath.relative_to(local_path)
                                sync_mgr.add_file_to_manifest(manifest, file, str(rel_path))
                                synced_counter[0] += 1
                                st.session_state['sync_cancelled_file_count'] = synced_counter[0]
                                synced_details[pair_idx].append(display_file_name)
                                terminal_log.append(f"<span style='color:{theme.SUCCESS_ALT}'>[✅] Recreated: </span> {esc(display_file_name)}")
                                log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                continue
                                
                            continue # Ensure Legacy Synthetic block definitively skips binary downloader

                        # Refresh download URL from Canvas API (signed URLs expire quickly)
                        download_url = file.url
                        try:
                            course = res_data['course']
                            
                            real_id = file.id
                            if real_id < 0:
                                from sync_manager import secondary_id_type, SECONDARY_ID_OFFSETS
                                if secondary_id_type(real_id) == 'attachment':
                                    real_id = abs(real_id) - SECONDARY_ID_OFFSETS['attachment']
                            fresh_file = course.get_file(real_id)
                            fresh_url = getattr(fresh_file, 'url', '')
                            if fresh_url:
                                download_url = fresh_url
                        except Exception:
                            pass  # Keep original URL as fallback

                        if download_url:
                            # --- Retry constants (mirrors canvas_logic.py) ---
                            SYNC_MAX_RETRIES = 5
                            SYNC_RETRY_DELAY = 2  # Base delay in seconds
                            
                            for attempt in range(SYNC_MAX_RETRIES):
                                if st.session_state.get('sync_cancel_requested', False):
                                    break
                                
                                should_sleep_duration = 0
                                
                                try:
                                    async with sem:
                                        async with session.get(download_url) as response:
                                            if response.status == 200:
                                                # --- Atomic .part Pattern ---
                                                part_path = filepath.parent / (filepath.name + '.part')
                                                download_interrupted = False
                                                atomic_rename_done = False
                                                
                                                try:
                                                    try:
                                                        async with aiofiles.open(make_long_path(part_path), 'wb') as f:
                                                            while True:
                                                                # Instant cancel check INSIDE the chunk loop
                                                                if st.session_state.get('sync_cancel_requested', False) or st.session_state.get('sync_cancelled', False):
                                                                    download_interrupted = True
                                                                    break
                                                                
                                                                chunk = await response.content.read(1024 * 1024)
                                                                if not chunk:
                                                                    break
                                                                await f.write(chunk)
                                                                chunk_size = len(chunk)
                                                                downloaded_mb += chunk_size / (1024 * 1024)
                                                                synced_counter[1] += chunk_size
                                                            
                                                                # Throttled UI math update
                                                                c_t = _time.time()
                                                                if c_t - last_ui_update > 0.4:
                                                                    # Calculate Speed & ETA
                                                                    elapsed = c_t - start_time
                                                                    speed = downloaded_mb / elapsed if elapsed > 0 else 0
                                                                    
                                                                    rem_mb = max(0, total_mb - downloaded_mb)
                                                                    eta_sec = rem_mb / speed if speed > 0 else 0
                                                                    
                                                                    # Apply to UI
                                                                    metrics_dashboard.markdown(render_metrics_html_compat(
                                                                        current_file, total_files, downloaded_mb, total_mb, speed, format_time(eta_sec)
                                                                    ), unsafe_allow_html=True)
                                                                    
                                                                    pct = min(1.0, current_file / total_files) if total_files > 0 else 0.0
                                                                    progress_container.progress(pct, text=f"{int(pct * 100)}%")
                                                                    last_ui_update = c_t
                                                    except Exception as write_err:
                                                        download_interrupted = True
                                                        raise write_err
                                                    
                                                    # Handle interrupted download: delete partial file
                                                    if download_interrupted:
                                                        continue  # Skip to next file (outer cancel guard will catch)
                                                    
                                                    # 100% success: atomic rename .part → final path
                                                    try:
                                                        os.replace(make_long_path(part_path), make_long_path(filepath))
                                                    except PermissionError:
                                                        error_msg = f"Cannot overwrite file (it may be open in another program): {filepath}"
                                                        logger.error(error_msg)
                                                        try:
                                                            os.unlink(make_long_path(part_path))
                                                        except Exception:
                                                            pass
                                                        raise RuntimeError(error_msg)
                                                    
                                                    atomic_rename_done = True
                                                    
                                                    # Only commit to DB AFTER file is physically complete on disk
                                                    rel_path = filepath.relative_to(local_path)
                                                    sync_mgr.add_file_to_manifest(manifest, file, str(rel_path))
                                                    synced_counter[0] += 1
                                                    st.session_state['sync_cancelled_file_count'] = synced_counter[0]
                                                    
                                                    # Track success for UI dropdown
                                                    final_name = filepath.name
                                                    synced_details[pair_idx].append(final_name)
                                                    terminal_log.append(f"<span style='color:{theme.SUCCESS_ALT}'>[✅] Finished: </span> {esc(final_name)}")
                                                    log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                                finally:
                                                    # GUARD: Always clean up .part if rename didn't complete
                                                    # Catches: write errors, network drops, disk-full, any exception
                                                    if not atomic_rename_done:
                                                        try:
                                                            if Path(make_long_path(part_path)).exists():
                                                                Path(make_long_path(part_path)).unlink()
                                                        except OSError:
                                                            pass
                                                
                                                break  # Success — exit retry loop
                                            
                                            elif response.status == 429:
                                                # Rate limited — respect Retry-After header
                                                should_sleep_duration = int(response.headers.get('Retry-After', SYNC_RETRY_DELAY * (2 ** attempt)))
                                                terminal_log.append(f"<span style='color:{theme.WARNING}'>[⏳] Rate limited: </span> {esc(display_file_name)} <span style='color:{theme.TEXT_MUTED}'>(retry in {should_sleep_duration}s)</span>")
                                                log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                            
                                            elif 500 <= response.status < 600:
                                                # Server error — retry with exponential backoff
                                                should_sleep_duration = SYNC_RETRY_DELAY * (2 ** attempt)
                                                if attempt < SYNC_MAX_RETRIES - 1:
                                                    terminal_log.append(f"<span style='color:{theme.WARNING}'>[⏳] Server error ({response.status}): </span> {esc(display_file_name)} <span style='color:{theme.TEXT_MUTED}'>(retry {attempt + 1}/{SYNC_MAX_RETRIES})</span>")
                                                    log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                                else:
                                                    # Max retries exhausted for 5xx
                                                    failed_files_for_pair.append(file)
                                                    error_list.append(f"Error syncing {esc(display_file_name)}: HTTP {response.status} after {SYNC_MAX_RETRIES} retries")
                                                    terminal_log.append(f"<span style='color:{theme.ERROR_ALT}'>[❌] Failed: </span> {esc(display_file_name)} <span style='color:{theme.TEXT_MUTED}'>(HTTP {response.status} after {SYNC_MAX_RETRIES} retries)</span>")
                                                    log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                                    break
                                            
                                            else:
                                                # Non-retryable HTTP error (4xx except 429)
                                                failed_files_for_pair.append(file)
                                                error_list.append(f"Error syncing {esc(display_file_name)}: HTTP {response.status}")
                                                terminal_log.append(f"<span style='color:{theme.ERROR_ALT}'>[❌] Failed: </span> {esc(display_file_name)} <span style='color:{theme.TEXT_MUTED}'>(HTTP {response.status})</span>")
                                                log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                                break  # Don't retry client errors
                                
                                except (aiohttp.ClientError, asyncio.TimeoutError) as net_err:
                                    # Network error — retry with backoff
                                    if attempt < SYNC_MAX_RETRIES - 1:
                                        should_sleep_duration = SYNC_RETRY_DELAY * (2 ** attempt)
                                        terminal_log.append(f"<span style='color:{theme.WARNING}'>[⏳] Network error: </span> {esc(display_file_name)} <span style='color:{theme.TEXT_MUTED}'>(retry {attempt + 1}/{SYNC_MAX_RETRIES})</span>")
                                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                    else:
                                        failed_files_for_pair.append(file)
                                        error_list.append(f"Error syncing {esc(display_file_name)}: Network error: {net_err}")
                                        terminal_log.append(f"<span style='color:{theme.ERROR_ALT}'>[❌] Failed: </span> {esc(display_file_name)} <span style='color:{theme.TEXT_MUTED}'>(Network error after {SYNC_MAX_RETRIES} retries)</span>")
                                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                        break
                                        
                                # WE ARE NOW OUTSIDE THE SEMAPHORE LOCK
                                if should_sleep_duration > 0:
                                    await asyncio.sleep(should_sleep_duration)
                                    continue # Retry
                        else:
                            # Check for LTI/Media streams
                            ext_lower = filepath.suffix.lower()
                            media_exts = ['.mp4', '.mov', '.avi', '.mkv', '.mp3']
                            if ext_lower in media_exts:
                                err_msg = "LTI/Media Stream (Cannot directly download)"
                            else:
                                err_msg = "No download URL"
                            
                            failed_files_for_pair.append(file)
                            error_list.append(f"Error syncing {esc(display_file_name)}: {esc(err_msg)}")
                            terminal_log.append(f"<span style='color:{theme.ERROR_ALT}'>[❌] Skipped: </span> {esc(display_file_name)} <span style='color:{theme.TEXT_MUTED}'>({esc(err_msg)})</span>")
                            log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)

                    except Exception as e:
                        failed_files_for_pair.append(file)
                        error_list.append(f"Error syncing {esc(display_file_name)}: {str(e)}")
                        str_err = str(e).replace('<', '&lt;').replace('>', '&gt;')
                        terminal_log.append(f"<span style='color:{theme.ERROR_ALT}'>[❌] Error: </span> {esc(display_file_name)} <span style='color:{theme.TEXT_MUTED}'>({str_err})</span>")
                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                        

                
                if failed_files_for_pair:
                    safe_res_data = sel['res_data'].copy()
                    # Strip heavy objects to protect Streamlit memory integrity
                    safe_res_data.pop('course', None)
                    safe_res_data.pop('sync_manager', None)
                    
                    # BUG FIX: Restore failed items to their exact correct buckets using O(1) Dictionaries
                    update_map: Dict[int, CanvasFileInfo] = {getattr(f, 'id', None): f for f in sel['updates']}
                    redownload_map: Dict[int, SyncFileInfo] = {getattr(r, 'canvas_file_id', r[0] if isinstance(r, tuple) else None): r for r in sel['redownload']}
                    
                    retry_new: List[CanvasFileInfo] = []
                    retry_updates: List[CanvasFileInfo] = []
                    retry_redownload: List[SyncFileInfo] = []
                    
                    for failed_item in failed_files_for_pair:
                        # --- FIX: Tuple Identity Loss ---
                        # Mirror O(1) redownload_map logic: try 'id', then 'canvas_file_id', then tuple explicit index
                        f_id = getattr(failed_item, 'id', getattr(failed_item, 'canvas_file_id', failed_item[0] if isinstance(failed_item, tuple) else None))
                        if f_id in update_map:
                            retry_updates.append(update_map[f_id])
                        elif f_id in redownload_map:
                            retry_redownload.append(redownload_map[f_id])
                        else:
                            retry_new.append(failed_item)
                            
                    retry_selections.append({
                        'pair_idx': pair_idx,
                        'res_data': safe_res_data,
                        'new': retry_new,
                        'updates': retry_updates,
                        'redownload': retry_redownload,
                        'ignore': []
                    })
                        
            # Final 100% UI Paint after the loop
            elapsed_final = _time.time() - start_time
            speed_final = (downloaded_mb / elapsed_final) if elapsed_final > 0 else 0
            render_progress_bar(progress_container, total_files, total_files)
            metrics_dashboard.markdown(render_metrics_html_compat(synced_counter[0], total_files, downloaded_mb, total_mb, speed_final, "00:00"), unsafe_allow_html=True)
            active_file_placeholder.markdown("<p style='color: {theme.TERMINAL_TEXT}; font-size: 0.9rem;'>✨ Sync Finalizing...</p>", unsafe_allow_html=True)
            log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)

            # CANCEL GUARD: Skip all post-download state mutations if cancelled
            if st.session_state.get('sync_cancelled', False) or st.session_state.get('sync_cancel_requested', False):
                st.session_state['download_status'] = 'sync_cancelled'
                st.rerun()

            for sel in sync_selections:
                res_data = sel['res_data']
                sync_mgr = res_data['sync_manager']
                manifest = res_data['manifest']
                local_path = sync_mgr.local_path

                sync_mgr.save_manifest(manifest)
                
                # Setup updates reference explicitly to fix `updates is not defined` NameError traceback
                updates = sel['updates']
                deletions = res_data['result'].deleted_on_canvas
                if updates or deletions:
                    log_file_path = local_path / "☁️ Canvas Updates & Deletions.txt"
                    try:
                        with open(make_long_path(log_file_path), "a", encoding="utf-8") as lf:
                            lf.write(f"\n--- Sync on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                            if updates:
                                lf.write("UPDATED FILES (New versions downloaded, check local folder for numbered copies):\n")
                                for f in updates:
                                    lf.write(f"  - {f.filename}\n")
                            if deletions:
                                lf.write("DELETED ON CANVAS (These were preserved locally but removed by teacher):\n")
                                for si in deletions:
                                    lf.write(f"  - {si.canvas_filename}\n")
                            lf.write("\n")
                    except Exception as e:
                        logging.warning(f"Failed to write updates log: {e}")
                
        return synced_details, retry_selections, list(terminal_log)

    # Extract variables locally to preserve streamli ThreadContext boundary
    local_sync_api_token = st.session_state.get('api_token', '')
    local_sync_api_url = st.session_state.get('api_url', '')
    synced_details, retry_selections, _download_log_history = asyncio.run(download_sync_files_batch(local_sync_api_token, local_sync_api_url))

    # --- Shared post-processing helpers ---
    def get_synced_file_paths(target_exts, conversion_key=None):
        """Return list of (Path, sync_mgr, pair_idx) for synced files matching target_exts.
           If conversion_key is provided, evaluates the pair's contract first."""
        results = []
        for sel in sync_selections:
            if conversion_key:
                contract = sel.get('res_data', {}).get('contract', {})
                # For Quick Sync, 'contract' exists. For Manual Sync, fallback to global persistent state.
                should_convert = contract.get(conversion_key.replace('persistent_', ''), st.session_state.get(conversion_key, False))
                if not should_convert:
                    continue  # Skip this pair's files
                    
            pair_idx = sel['pair_idx']
            res_data = sel['res_data']
            sm = res_data['sync_manager']
            for fname in synced_details.get(pair_idx, []):
                if Path(fname).suffix.lower() in target_exts:
                    matches = list(sm.local_path.rglob(fname))
                    for m in matches:
                        if m.is_file() and not m.name.startswith('._') and "__MACOSX" not in m.parts:
                            results.append((m, sm, pair_idx))
        return results

    def update_synced_detail(pair_idx, old_name, new_name):
        """Update a filename in synced_details so the final success screen shows the converted extension."""
        details = synced_details.get(pair_idx, [])
        for i, fname in enumerate(details):
            if fname == old_name:
                details[i] = new_name
                break

    # ==========================================
    # SECONDARY GUARD (defense-in-depth): Catch any cancel that slipped past the primary guard above save_manifest
    # ==========================================
    if st.session_state.get('sync_cancelled', False) or st.session_state.get('sync_cancel_requested', False):
        st.session_state['download_status'] = 'sync_cancelled'
        st.rerun()

    # ==========================================
    # POST-PROCESSING PIPELINE (Shared Module)
    # ==========================================
    from post_processing import (
        UIBridge, run_archive_extraction, run_pptx_conversion,
        run_html_conversion, run_code_conversion, run_url_compilation,
        run_word_conversion, run_excel_data_conversion, run_excel_conversion,
        run_video_conversion,
    )

    # 1. Clear Phase 2 download UI to prevent stacking
    cancel_placeholder.empty()
    active_file_placeholder.empty()

    # 2. Inject cancel button hover CSS
    st.markdown("""
    <style>
    .st-key-cancel_download_btn button:hover,
    .st-key-cancel_pp_download button:hover,
    .st-key-cancel_sync_btn button:hover,
    .st-key-cancel_pp_btn button:hover,
    .st-key-cancel_pp_btn_sync_phase3 button:hover {
        border-color: {theme.ERROR} !important;
        background-color: {theme.ERROR_BG} !important;
        color: {theme.ERROR} !important;
        transition: all 0.2s ease-in-out;
    }
    </style>
    """, unsafe_allow_html=True)

    st.session_state['is_post_processing'] = True

    # 3. Render cancel button
    cancel_placeholder.button(
        "Cancel Post-Processing",
        key="cancel_pp_btn_sync_phase3",
        type="secondary",
        on_click=cancel_process_callback
    )

    # 4. Force render flush before heavy COM operations
    _time.sleep(0.3)

    # 5. Build UIBridge for shared module
    def _on_detail_update(ctx, old_name, new_name):
        update_synced_detail(ctx, old_name, new_name)

    pp_ui = UIBridge(
        header_placeholder=status_text,
        progress_placeholder=progress_container,
        metrics_placeholder=metrics_dashboard,
        log_placeholder=log_container,
        active_file_placeholder=active_file_placeholder,
        log_lines=_download_log_history,
        is_cancelled=lambda: st.session_state.get('sync_cancelled', False) or st.session_state.get('sync_cancel_requested', False),
        on_detail_update=_on_detail_update,
    )

    # 6. Run each converter with per-course contract evaluation via get_synced_file_paths

    # Archive Extraction
    run_archive_extraction(
        get_synced_file_paths({'.zip', '.tar', '.tar.gz', '.gz'}, 'persistent_convert_zip'), pp_ui
    )

    # PPTX -> PDF
    run_pptx_conversion(
        get_synced_file_paths({'.ppt', '.pptx', '.pptm', '.pot', '.potx'}, 'persistent_convert_pptx'), pp_ui
    )

    # HTML -> Markdown
    run_html_conversion(
        get_synced_file_paths({'.html'}, 'persistent_convert_html'), pp_ui
    )

    # Code -> TXT
    from code_converter import CODE_EXTENSIONS
    run_code_conversion(
        get_synced_file_paths(CODE_EXTENSIONS, 'persistent_convert_code'), pp_ui
    )

    # URL Compilation (requires folder-level iteration, not file-level)
    _url_folders = []
    _processed_roots = set()
    for sel in sync_selections:
        _contract = sel.get('res_data', {}).get('contract', {})
        _should_compile = _contract.get('convert_urls', st.session_state.get('persistent_convert_urls', False))
        if _should_compile:
            _sm = sel.get('res_data', {}).get('sync_manager')
            if _sm and _sm.local_path.exists() and _sm.local_path not in _processed_roots:
                _processed_roots.add(_sm.local_path)
                _url_folders.append((_sm.local_path, _sm.course_name))
    run_url_compilation(_url_folders, pp_ui)

    # Legacy Word -> PDF
    run_word_conversion(
        get_synced_file_paths({'.doc', '.rtf', '.odt'}, 'persistent_convert_word'), pp_ui
    )

    # Excel → AI Data + PDF (single toggle, dual pipeline)
    # CRITICAL ORDERING: Data extraction FIRST (reads .xlsx), PDF SECOND (deletes .xlsx).
    run_excel_data_conversion(
        get_synced_file_paths({'.xlsx', '.xls', '.xlsm'}, 'persistent_convert_excel'), pp_ui
    )

    # Excel → PDF
    run_excel_conversion(
        get_synced_file_paths({'.xlsx', '.xls', '.xlsm'}, 'persistent_convert_excel'), pp_ui
    )

    # Video -> MP3
    run_video_conversion(
        get_synced_file_paths({'.mp4', '.mov', '.mkv', '.avi', '.m4v'}, 'persistent_convert_video'), pp_ui
    )

    # --- Inject post-processing sidecars into sync UI ledger ---
    _sidecar_paths = pp_ui.generated_sidecar_paths
    if _sidecar_paths:
        # Build reverse lookup: resolved local_path -> pair_idx
        _pair_lookup = {}
        for sel in sync_selections:
            _sm = sel.get('res_data', {}).get('sync_manager')
            if _sm and _sm.local_path.exists():
                _pair_lookup[str(_sm.local_path.resolve())] = sel['pair_idx']

        for sp in _sidecar_paths:
            sp_path = Path(sp)
            sidecar_name = sp_path.name  # e.g., "Grades_Data.txt"
            # Walk up the path to find which pair's local_path contains this file
            matched_pair_idx = None
            for parent in sp_path.parents:
                resolved_parent = str(parent.resolve())
                if resolved_parent in _pair_lookup:
                    matched_pair_idx = _pair_lookup[resolved_parent]
                    break
            if matched_pair_idx is not None:
                existing = synced_details.get(matched_pair_idx, [])
                if sidecar_name not in existing:
                    synced_details[matched_pair_idx].append(sidecar_name)
                    synced_counter[0] += 1  # Bump global synced count for completion card


    # Clear the blue status text so it doesn't linger on completion
    active_file_placeholder.empty()

    st.session_state['synced_count'] = synced_counter[0]
    st.session_state['synced_bytes'] = synced_counter[1]
    st.session_state['sync_errors'] = error_list
    st.session_state['pp_failure_count'] = pp_ui.pp_failure_count
    # Store detailed synced files for the completion screen dropdowns
    # synced_details is a dict: { pair_idx: [ "filename1", "filename2", ... ] }
    st.session_state['synced_details'] = dict(synced_details)
    st.session_state['retry_selections'] = retry_selections

    # Update last_synced timestamps atomically
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    updates = []
    pairs = st.session_state.get('sync_pairs', [])
    for sel in sync_selections:
        pair_idx = sel['pair_idx']
        if pair_idx < len(pairs):
            updates.append((pairs[pair_idx].get('course_id'), pairs[pair_idx].get('local_folder'), now_str))
    
    if updates:
        _update_last_synced_batch(updates)

    # Record sync history
    if synced_counter[0] > 0:
        try:
            from ui_helpers import get_config_dir
            history_mgr = SyncHistoryManager(get_config_dir())
            
            # Extract names of courses that actually had files synced
            synced_course_names = []
            for sel in sync_selections:
                if sel['pair_idx'] in synced_details and len(synced_details[sel['pair_idx']]) > 0:
                    synced_course_names.append(sel['res_data']['pair']['course_name'])

            history_mgr.add_entry({
                'timestamp': now_str,
                'files_synced': synced_counter[0],
                'courses': len(sync_selections),
                'course_names': synced_course_names,
                'errors': len(error_list),
            })
        except Exception as e:
            logger.error(f"Failed to record sync history: {e}")

    if st.session_state.get('sync_cancel_requested', False) or st.session_state.get('sync_cancelled', False):
        st.session_state['download_status'] = 'sync_cancelled'
        st.session_state['sync_cancelled_file_count'] = synced_counter[0]
    else:
        st.session_state['download_status'] = 'sync_complete'
        
    st.session_state['step'] = 4
    st.rerun()
