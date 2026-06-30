"""
sync.execution - Sync download execution loop and post-processing.

Extracted from ``sync_ui.py`` L4107-5039 (Phase 4).
Strict physical move - NO logic changes.

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
import glob as _glob
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
from core.cancellation import cancel_sync, is_sync_cancelled
# NOTE: never re-import these names *locally* inside a function in this
# module - a local `from sync_manager import secondary_id_type` makes the
# name function-local for the ENTIRE enclosing function scope, so earlier
# uses raise UnboundLocalError ("cannot access local variable
# 'secondary_id_type'"). This bit the sync download loop on 2026-06-11.
from sync_manager import (
    SyncFileInfo, SyncHistoryManager, CanvasFileInfo,
    secondary_id_type, SECONDARY_ID_OFFSETS,
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
from engine.progress_dashboard import (
    build_metrics_html, build_terminal_html, render_active_file,
    log_line, log_meta, file_icon_svg,
)
from canvas_debug import log_debug

logger = logging.getLogger(__name__)

# L-10: Hoist retry constants to module level for easy post-launch tuning.
SYNC_MAX_RETRIES = 5
SYNC_RETRY_DELAY = 2  # Base delay in seconds for exponential backoff


def _release_sync_worker() -> None:
    """Drop the re-attachable sync worker references from session state.

    Called once the worker result has been consumed, on worker failure, and
    from the Cancel handler. shutdown(wait=False) lets an in-flight worker
    wind down on its own (it observes the sync-cancel Event per chunk); we
    only need to guarantee the NEXT sync starts with a fresh pool/future.
    """
    st.session_state.pop('sync_worker_future', None)
    _pool = st.session_state.pop('sync_worker_pool', None)
    if _pool is not None:
        try:
            _pool.shutdown(wait=False)
        except Exception:
            pass
    return None


def _basename_variants(value: str) -> set[str]:
    """NFC-normalized basename variants of a path or filename.

    Decodes BOTH ``%XX`` and ``+`` so a form-URL-encoded Canvas filename
    (e.g. ``'Klyngevejledning+-+Upload.pptx'``) matches the real on-disk basename
    (``'Klyngevejledning - Upload.pptx'``). ``urllib.parse.unquote`` alone leaves
    ``+`` untouched - that was why locally-deleted files re-downloaded this run were
    mis-labelled brand-'new' instead of 'restored'. Returns ``set()`` for falsy input.
    """
    import urllib.parse as _urlparse
    import unicodedata as _ud
    if not value:
        return set()
    base = Path(value).name
    out: set[str] = set()
    for variant in (base, _urlparse.unquote(base), _urlparse.unquote_plus(base)):
        try:
            out.add(_ud.normalize('NFC', variant))
        except Exception:
            out.add(variant)
    return out


def _redownload_restore_keys(redownload_items) -> set[str]:
    """NFC-normalized basename keys identifying the locally-deleted files chosen for
    re-download this run, so the completion screen and sync history label them
    'restored' (re-downloaded) rather than mis-labelling them brand-'new'.

    A locally-deleted ``SyncFileInfo`` carries the real on-disk relative path in
    ``local_path`` (real spaces); ``target_local_path`` is empty (it is only filled
    for new/updated files) and ``canvas_filename`` is form-URL-encoded. We harvest
    basename variants from all three attributes via :func:`_basename_variants` so the
    real on-disk synced name resolves regardless of which form Canvas supplied.
    """
    keys: set[str] = set()
    for _si in (redownload_items or []):
        for _attr in ('local_path', 'target_local_path', 'canvas_filename'):
            keys |= _basename_variants(getattr(_si, _attr, '') or '')
    return keys


def _build_synced_groups(sync_selections, synced_details):
    """Build a per-course breakdown of the files synced this run.

    Resolves every synced file to its on-disk location (relative to the course
    folder) so the completion screen and the landing-page "New files since last
    sync" panel can offer Open / Reveal actions per file. Runs once at finalize
    on the script thread - AFTER post-processing - so converted names (e.g.
    .pptx → .pdf) and sidecar artifacts are already reflected in synced_details.

    Returns ``list[dict]`` - one entry per course that received files::

        {'course_name', 'course_id', 'local_folder',
         'files': [{'name', 'rel', 'category'}]}

    ``rel`` is POSIX-style and relative to ``local_folder``; ``category`` is one
    of ``'new' | 'updated' | 'restored' | 'protected'`` (``'restored'`` = a file
    the user had deleted locally and chose to re-download this run). Best-effort
    and total: any failure degrades to ``rel == name`` rather than raising into
    the sync finalizer.
    """
    import unicodedata as _ud

    def _norm(s):
        # Canonical NFC form so a Canvas-supplied name and the on-disk name that
        # differ ONLY by Unicode normalization (e.g. Danish 'æ'/'ø'/'å' stored
        # NFD vs NFC) still resolve to the same key. Without this the lookup
        # misses and the file silently loses its subfolder path.
        try:
            return _ud.normalize('NFC', s)
        except Exception:
            return s

    groups = []
    for sel in sync_selections:
        pair_idx = sel.get('pair_idx')
        names = synced_details.get(pair_idx, [])
        if not names:
            continue
        res_data = sel.get('res_data', {})
        pair = res_data.get('pair', {})

        # Resolve the course root: prefer the live SyncManager, fall back to the
        # pair's configured folder.
        course_root = None
        sm = res_data.get('sync_manager')
        if sm is not None:
            try:
                course_root = sm.local_path
            except Exception:
                course_root = None
        if course_root is None:
            _lf = pair.get('local_folder')
            course_root = Path(_lf) if _lf else None

        # Pre-conversion names of files Canvas updated - drives 'updated' category.
        # Harvest basename variants from BOTH the Canvas filename and the tracked
        # SyncFileInfo.local_path (the real on-disk name) so the match survives the
        # same '+'-encoding pitfall that broke 'restored'.
        updates_for_pair = set()
        result = res_data.get('result')
        if result is not None and hasattr(result, 'updated_files'):
            try:
                for _cf, _sf in result.updated_files:
                    updates_for_pair |= _basename_variants(getattr(_cf, 'filename', '') or '')
                    updates_for_pair |= _basename_variants(getattr(_sf, 'local_path', '') or '')
            except Exception:
                updates_for_pair = set()

        # Locally-deleted files the user chose to re-download this run - drives
        # the 'restored' category so they're no longer mis-labelled as brand-new.
        # A file is in exactly one selection bucket, so 'restored' never collides
        # with 'updated'.
        redownloads_for_pair = _redownload_restore_keys(sel.get('redownload'))

        # Walk the folder ONCE to build basename -> [rel paths]; Finding each
        # name against this index is O(1) and tolerates module subfolders.
        name_index = {}
        if course_root is not None:
            try:
                root_str = str(course_root)
                for dirpath, _dirnames, filenames in os.walk(root_str):
                    for fn in filenames:
                        if fn.startswith('._') or fn == '.canvas_sync.db':
                            continue
                        rel = os.path.relpath(os.path.join(dirpath, fn), root_str).replace('\\', '/')
                        # Key on the NFC-normalized basename so the lookup below
                        # is resilient to NFC/NFD mismatches between disk and the
                        # Canvas-supplied filename.
                        name_index.setdefault(_norm(fn), []).append(rel)
            except Exception:
                name_index = {}

        files = []
        # Paths already assigned to an earlier record this course, so two synced
        # entries that share a basename but genuinely live in DIFFERENT subfolders
        # each resolve to their OWN path instead of both collapsing onto the
        # freshest copy (which would hide one behind a duplicate-looking row).
        used_rels: set[str] = set()
        for nm in names:
            _nm_key = _norm(nm)
            if "_NewVersion" in nm:
                category = 'protected'
            elif _nm_key in updates_for_pair:
                category = 'updated'
            elif _nm_key in redownloads_for_pair:
                category = 'restored'
            else:
                category = 'new'

            rel = nm
            candidates = name_index.get(_nm_key)
            if candidates:
                # Prefer candidates not yet claimed by a prior record; only fall
                # back to the full list if every copy is already spoken for.
                pool = [c for c in candidates if c not in used_rels] or candidates
                if len(pool) == 1:
                    rel = pool[0]
                else:
                    # Same basename in multiple subfolders - prefer the freshest,
                    # which is the copy this run just wrote.
                    try:
                        rel = max(
                            pool,
                            key=lambda r: os.path.getmtime(os.path.join(str(course_root), r)),
                        )
                    except Exception:
                        rel = pool[0]
                used_rels.add(rel)

            files.append({'name': nm, 'rel': rel, 'category': category})

        groups.append({
            'pair_idx': pair_idx,
            'course_name': pair.get('course_name', ''),
            'course_id': pair.get('course_id'),
            'local_folder': str(course_root) if course_root is not None else '',
            'files': files,
        })
    return groups


def run_sync():
    """Execute the full sync pipeline: download files, post-process, record history.

    Strict physical move of the original ``_run_sync`` from ``sync_ui.py``.
    No logic has been changed.
    """
    # --- Backward-compatible import of persistence helper ---
    from sync.persistence import update_last_synced_batch as _update_last_synced_batch
    # --- Backward-compatible import of cancel callback ---
    from core.cancellation import cancel_sync as cancel_process_callback

    # Capture Streamlit script-run context on the script thread so it can be
    # propagated to the background thread that runs the async download loop.
    # (asyncio.run() must execute in a fresh thread to avoid RuntimeError when
    # Tornado's event loop is already running in this process.)
    from streamlit.runtime.scriptrunner import get_script_run_ctx as _get_run_ctx
    _script_ctx = _get_run_ctx()

    # Initialize phase flags explicitly at start of run - but ONLY if not already cancelled.
    # If a Phase 3 cancel triggered the rerun, we must preserve is_post_processing=True
    # so that _show_sync_cancelled can read it for the correct status message.
    if not is_sync_cancelled():
        st.session_state['is_post_processing'] = False
        # Re-arm the completion notification for THIS sync. The sentinel is
        # shared with the download flow and only otherwise reset on cleanup, so
        # a preceding download that left it True would swallow this sync's
        # "Sync Complete" notification. Safe to reset on every execution-phase
        # rerun: the notification fires from the separate completion screen.
        st.session_state['completion_beep_fired'] = False
        # Re-arm the "quit Office apps on completion" one-shot for this sync.
        st.session_state['_office_quit_fired'] = False
        # Drop any stale Panopto results from a prior sync on a FRESH run (but keep
        # them on a Retry, which re-enters run_sync after the Panopto pass already
        # produced the real summary the completion card must still show).
        if not st.session_state.get('retry_selections'):
            st.session_state.pop('panopto_summary', None)
            st.session_state.pop('panopto_uptodate_total', None)
            # Clear the prior run's history timestamp so this sync's Panopto pass
            # amends THIS run's entry (or creates one), never a stale earlier entry.
            st.session_state.pop('_sync_history_ts', None)
        # macOS: forget Office apps primed by a previous run (quit at its completion)
        # so this sync launches them fresh + scoped to the files it actually converts.
        import sys as _sys_reset
        if _sys_reset.platform == 'darwin':
            try:
                from engine.applescript_bridge import (
                    reset_office_priming, first_run_permission_setup,
                )
                reset_office_priming()
                # One-time per machine: fire ALL outstanding Office permission
                # prompts NOW, while the user is at the screen (they just started
                # the sync) - instead of letting each app's prompt ambush a later
                # run mid-conversion. Unscoped toggles on purpose; the in-run
                # prime stays file-scoped. Idempotent across reruns (module flag
                # + persisted record inside first_run_permission_setup).
                if first_run_permission_setup({
                    'convert_pptx': st.session_state.get('persistent_convert_pptx', False),
                    'convert_word': st.session_state.get('persistent_convert_word', False),
                    'convert_excel': st.session_state.get('persistent_convert_excel', False),
                }):
                    st.session_state['_tcc_batch_active'] = True
            except Exception:
                pass

    # Daily auto-sync (Today dashboard) requests a SLIM progress view: only a
    # progress bar + status line, no wizard / metrics / terminal log. The proven
    # async loop is untouched - it just writes its metrics/active-file/log into a
    # hidden container (see placeholder creation below).
    _today_minimal = st.session_state.get('today_sync_active', False)

    # Step wizard
    if not _today_minimal:
        render_sync_wizard(st, 3)
        st.markdown('<h2 class="step-header">Syncing...</h2>', unsafe_allow_html=True)
    else:
        st.markdown('<h2 class="step-header">Daily sync in progress…</h2>', unsafe_allow_html=True)

    # First-run macOS permission batch is in flight: tell the user the upcoming
    # system dialogs are expected and one-time (mirrors the download flow).
    if st.session_state.get('_tcc_batch_active'):
        from ui.amber_notice import render_info_notice
        render_info_notice(
            "<b>First-time macOS setup:</b> macOS will show a few one-time permission "
            "dialogs (control of Microsoft PowerPoint / Word / Excel, System Events, "
            "and folder access). Click <b>Allow / OK</b> on each - Canvas Downloader uses them "
            "only to convert Office files to PDF on your own Mac.",
            icon="🔐",
            allow_html=True,
        )

    sync_selections = st.session_state.get('sync_selections') or []
    if not isinstance(sync_selections, list):
        sync_selections = []
    if not sync_selections:
        st.session_state['download_status'] = 'sync_complete'
        st.session_state['synced_count'] = 0
        st.rerun()

    status_text = st.empty()
    progress_container = st.empty()
    if _today_minimal:
        # Keep only the status line + progress bar visible. The metrics/active-file/
        # log placeholders still exist (the async loop writes to them) but live in a
        # hidden container so the Today page stays a single clean progress bar.
        _today_hidden = st.container(key="today_hidden_sync_ui")
        with _today_hidden:
            metrics_dashboard = st.empty()
            active_file_placeholder = st.empty()
            log_container = st.empty()
        st.markdown(
            '<style>div[class*="st-key-today_hidden_sync_ui"]{display:none !important;}</style>',
            unsafe_allow_html=True,
        )
    else:
        metrics_dashboard = st.empty()
        active_file_placeholder = st.empty()
        log_container = st.empty()

    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    cancel_placeholder = st.empty()
    if cancel_placeholder.button('Cancel Sync', key="cancel_sync_btn", type="secondary"):
        cancel_sync()  # sets threading.Event + sync_cancelled + sync_cancel_requested
        # Release the background worker references. The worker itself observes
        # the cancel Event per chunk and winds down within ~a second; per-file
        # DB commits have already persisted everything downloaded so far.
        _release_sync_worker()
        st.session_state.pop('sync_worker_result', None)

        # Smart routing:
        if st.session_state.get('qs_cancel_route', False):
            st.session_state['step'] = 1
            st.session_state['download_status'] = 'select'
            st.session_state.pop('qs_cancel_route', None)
        else:
            # Route to the sync cancelled screen (step 4 handles all sync
            # sub-states).  Previous code sent users to step=2 which is
            # the Download Settings page - wrong mode entirely.
            st.session_state['download_status'] = 'sync_cancelled'
            
        st.rerun()

    # --- Inject red hover CSS for cancel buttons (dynamic - requires theme vars) ---
    st.markdown(f"""
    <style>
    .st-key-cancel_download_btn button:hover,
    .st-key-cancel_pp_download button:hover,
    .st-key-cancel_sync_btn button:hover,
    .st-key-cancel_pp_btn button:hover,
    .st-key-cancel_pp_btn_sync_phase3 button:hover {{
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
        import threading as _threading
        from streamlit.runtime.scriptrunner import add_script_run_ctx as _add_ctx
        _add_ctx(_threading.current_thread(), _script_ctx)
        from canvas_logic import safe_thread_wrapper
        current_ctx = _script_ctx  # captured on script thread above
        
        cm = CanvasManager(sync_api_token, sync_api_url)
        cm.error_log_enabled = st.session_state.get('error_log_enabled', False)
        from canvas_debug import log_debug
        _sync_debug_mode = st.session_state.get('debug_mode', False)
        timeout = aiohttp.ClientTimeout(total=3600, sock_read=60, sock_connect=15)
        
        # Respect global concurrency limit from session state (with safety clamp:
        # negative or zero values would crash asyncio.Semaphore; insanely large
        # values would fork too many sockets and likely 429-rate-limit Canvas).
        try:
            concurrent_limit = int(st.session_state.get('concurrent_downloads', 5) or 5)
        except (TypeError, ValueError):
            concurrent_limit = 5
        concurrent_limit = max(1, min(concurrent_limit, 20))
        sem = asyncio.Semaphore(concurrent_limit)

        # Max-file-size gate (0/None = disabled). Read once up-front so the
        # entire sync batch applies a consistent limit.
        if st.session_state.get('max_file_size_enabled', False):
            _mb_limit = int(st.session_state.get('max_file_size_mb', 0) or 0)
            max_file_size_bytes = _mb_limit * 1024 * 1024 if _mb_limit > 0 else None
        else:
            max_file_size_bytes = None
        
        # Track synced files per pair for the results screen dropdowns
        # Key: pair_idx (int), Value: list of strings (filenames)
        synced_details = defaultdict(list)
        # Parallel set of FINAL relative paths already recorded this run, per
        # pair. The on-disk path (computed AFTER conflict resolution) is the
        # single source of truth for "what files exist": a file that reaches the
        # download queue from two sources (e.g. a regular File AND a secondary
        # attachment of the same physical file) overwrites the same path, so it
        # must be counted and listed ONCE. Two same-named files that land in
        # DIFFERENT folders have different paths and are correctly both kept.
        synced_rel_paths = defaultdict(set)
        retry_selections = []
        
        # certifi-backed SSL context: frozen macOS builds have no OpenSSL default
        # CA paths, so aiohttp must be pointed at certifi explicitly (see
        # canvas_logic.get_ssl_context).
        from canvas_logic import get_ssl_context
        _sync_connector = aiohttp.TCPConnector(
            limit=concurrent_limit, limit_per_host=concurrent_limit, ssl=get_ssl_context()
        )
        async with aiohttp.ClientSession(
            headers={'Authorization': f'Bearer {cm.api_key}'}, timeout=timeout,
            connector=_sync_connector
        ) as session:
            total_files = sum(
                len(sel['new']) + len(sel['updates']) + len(sel['redownload'])
                for sel in sync_selections
            )
            total_mb = 0.0
            for sel in sync_selections:
                total_mb += sum(getattr(f, 'size', 0) or 0 for f in sel['new'])
                total_mb += sum(getattr(f, 'size', 0) or 0 for f in sel['updates'])
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
            terminal_log = deque(maxlen=200)

            # Initial UI Draw
            metrics_dashboard.markdown(render_metrics_html_compat(0, total_files, 0.0, total_mb, 0.0, "--:--"), unsafe_allow_html=True)
            render_active_file(active_file_placeholder, "Preparing sync...")
            log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)

            for pair_idx, sel in enumerate(sync_selections):
                if is_sync_cancelled():
                    break

                failed_files_for_pair = []

                res_data = sel['res_data']
                sync_mgr = res_data.get('sync_manager')
                manifest = res_data.get('manifest')
                canvas_files_map = {f.id: f for f in res_data['canvas_files']}
                pair = res_data['pair']

                course_name = friendly_course_name(pair['course_name']) or 'Unnamed Course'

                # Same-name secondary entity guard: per-pair registry so two
                # DISTINCT entities with identical sanitized names get " (1)"
                # suffixes instead of silently overwriting each other.
                cm._sec_registry = {}

                if sync_mgr is None:
                    error_list.append(f"Skipping {course_name}: Database failed to initialize.")
                    failed_files_for_pair.extend(sel.get('new', []) + sel.get('updates', []))
                    continue

                # Set up local_path and debug_file early so all pair-level events are logged
                local_path = sync_mgr.local_path
                _debug_file = str(local_path / 'debug_log.txt') if _sync_debug_mode else None
                if _debug_file:
                    # Register for the logging bridge (mirrors all app-module
                    # logger output, incl. post-processing, into this file).
                    from canvas_debug import set_active_debug_file as _set_dbg, log_session_header as _dbg_header
                    _set_dbg(_debug_file)
                    if pair_idx == 0:
                        _dbg_header(_debug_file, context=f"Sync execution | {total_pairs} pair(s)")
                    _sync_mode_label = "Quick Sync" if st.session_state.get('sync_quick_mode') else "Analyze, Review & Sync"
                    log_debug(f"=== Sync Execution: {course_name} | Mode: {_sync_mode_label} ===", _debug_file)
                    log_debug(f"Pair {pair_idx + 1}/{total_pairs} | Folder: {local_path}", _debug_file)
                    log_debug(
                        f"Concurrency: {concurrent_limit} | "
                        f"Max file size: {str(max_file_size_bytes // (1024 * 1024)) + ' MB' if max_file_size_bytes else 'disabled'}",
                        _debug_file,
                    )

                _counter_html = f"<p style='margin: 0; font-size: 0.8rem; color: {theme.TEXT_SECONDARY}; text-transform: uppercase;'>Syncing Course {pair_idx + 1}/{total_pairs}</p>" if total_pairs > 1 else ""
                header_html = f"""
                <div style="margin-bottom: 0.5rem;">
                    {_counter_html}
                    <h3 style="margin: 0; padding-top: 0.1rem; color: {theme.TEXT_PRIMARY};">{esc(course_name)}</h3>
                </div>
                """
                status_text.html(header_html)
                
                # Re-hydration Injection
                course = res_data.get('course')
                if course is None:
                    terminal_log.append(log_meta(f"Connecting to {course_name}…"))
                    log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                    try:
                        # CanvasManager has no get_course() of its own - the
                        # method lives on the canvasapi client (cm.canvas).
                        # Calling cm.get_course crashed every retry run with
                        # AttributeError and produced a phantom history entry.
                        course = await asyncio.to_thread(safe_thread_wrapper, cm.canvas.get_course, current_ctx, pair['course_id'])
                        res_data['course'] = course
                    except Exception as e:
                        err_str = f"Connection failure to {esc(course_name)}: {esc(str(e))}"
                        error_list.append(err_str)
                        terminal_log.append(log_line('error', f"Reconnection failed: {course_name}", detail=str(e)))
                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                        if _debug_file:
                            from canvas_debug import log_debug_exc
                            log_debug_exc(f"✗ Reconnection failed: {course_name}: {e}", _debug_file, exc=e)
                        failed_files_for_pair.extend(sel.get('new', []))
                        continue

                # Task 4: State Leakage Fix
                # We save the auto-healed manifest + any newly ignored files only ONCE per folder, 
                # exactly when the sync is executing (after user confirmation)
                if sel['ignore']:
                    # Update SQLite DB (bulk UPSERT with is_ignored=1)
                    sync_mgr.bulk_ignore_files([
                        (getattr(f, 'id', getattr(f, 'canvas_file_id', None)),
                         getattr(f, 'filename', getattr(f, 'canvas_filename', '')),
                         getattr(f, 'size', getattr(f, 'original_size', 0)) or 0)
                        for f in sel['ignore']
                    ])
                    # Mirror the DB state into the in-memory manifest so the
                    # persistence loop below sees is_ignored=True immediately.
                    _ignore_ids = {
                        str(getattr(f, 'id', getattr(f, 'canvas_file_id', None)))
                        for f in sel['ignore']
                    }
                    _files_sec = manifest.setdefault('files', {})
                    for _fid in _ignore_ids:
                        if _fid in _files_sec:
                            _files_sec[_fid]['is_ignored'] = True
                        else:
                            _files_sec[_fid] = {'is_ignored': True, 'local_path': '', 'canvas_filename': ''}
                    res_data['manifest'] = manifest   # keep res_data in sync
                # Selective persist: only save ignored/healed entries to DB before download
                # (NOT the full auto-discovered manifest, to avoid premature commit)
                for file_id_str, entry in manifest.get('files', {}).items():
                    if entry.get('is_ignored'):
                        sync_mgr._save_single_file_to_db(entry)

                all_files = list(sel['new']) + list(sel['updates'])

                def _adopt_redownload(target_obj, sync_info):
                    """Stamp the queued file with the analyzer's resolved
                    target path + a flag marking it as a locally-deleted
                    redownload. This is what lets the routing block read
                    ``_target_local_path`` directly instead of searching
                    ``sel['redownload']`` by id, and what enables the
                    clean-overwrite branch for locally-deleted conflicts.
                    """
                    try:
                        if getattr(sync_info, 'target_local_path', ''):
                            target_obj._target_local_path = sync_info.target_local_path
                    except Exception:
                        pass
                    try:
                        target_obj._is_redownload = True
                    except Exception:
                        pass
                    return target_obj

                for sync_info in sel['redownload']:
                    # 1. Direct ID match (Real Files)
                    if str(sync_info.canvas_file_id) in {str(k) for k in canvas_files_map.keys()}:
                        # Map string ID to the proper canvas file map object safely
                        _mapped_id = next(k for k in canvas_files_map.keys() if str(k) == str(sync_info.canvas_file_id))
                        all_files.append(_adopt_redownload(canvas_files_map[_mapped_id], sync_info))

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
                        all_files.append(_adopt_redownload(proxy, sync_info))
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
                                all_files.append(_adopt_redownload(found_file, sync_info))
                        else:
                            # Log error if file is truly gone
                            error_list.append(f"File removed from Canvas before download: {sync_info.canvas_filename}")

                Path(make_long_path(local_path)).mkdir(parents=True, exist_ok=True)
                if _debug_file:
                    _pair_mb = sum(getattr(_f, 'size', 0) or 0 for _f in all_files) / (1024 * 1024)
                    log_debug(f"Files queued: {len(all_files)} ({_pair_mb:.1f} MB)", _debug_file)

                for file in all_files:
                    if is_sync_cancelled():
                        break

                    current_file += 1
                    display_file_name = file.display_name or file.filename

                    # Max-file-size gate: skip oversized files silently
                    # (counts as a non-error skip, keeps progress totals honest).
                    # Applies to real Canvas files (positive id) AND Mode B
                    # attachments (negative attachment-range id, real bytes) -
                    # other synthetic entities carry size=0 anyway.
                    _f_size = getattr(file, 'size', 0) or 0
                    _gate_id = getattr(file, 'id', 0)
                    if (
                        max_file_size_bytes
                        and _f_size > max_file_size_bytes
                        and (_gate_id > 0 or secondary_id_type(_gate_id) == 'attachment')
                    ):
                        _f_mb = _f_size / (1024 * 1024)
                        # Track for completion screen display
                        if 'size_skipped_files' not in st.session_state:
                            st.session_state['size_skipped_files'] = []
                        st.session_state['size_skipped_files'].append(f"{display_file_name} ({_f_mb:.1f} MB)")
                        total_files = max(0, total_files - 1)  # keep denominator accurate
                        current_file -= 1  # undo the increment - this file never ran
                        terminal_log.append(log_line('skip', display_file_name, icon=file_icon_svg(display_file_name), detail=f'Skipped - Exceeds filesize limit · {_f_mb:.1f} MB'))
                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                        if _debug_file:
                            log_debug(f"⏭ Skipped (too large, {_f_mb:.1f} MB): {display_file_name}", _debug_file)
                            
                        # Register as ignored in the sync DB so future syncs
                        # don't surface these files as "new".
                        if sync_mgr:
                            try:
                                await asyncio.to_thread(
                                    sync_mgr.ignore_file,
                                    _gate_id,
                                    getattr(file, 'filename', ''),
                                    _f_size
                                )
                            except Exception as e:
                                if _debug_file: log_debug(f"Warning: Failed to ignore large file in DB: {e}", _debug_file)
                                
                        if manifest and 'files' in manifest:
                            _manifest_fid = str(_gate_id)
                            if _manifest_fid in manifest['files']:
                                manifest['files'][_manifest_fid]['is_ignored'] = True
                            else:
                                manifest['files'][_manifest_fid] = {'is_ignored': True, 'local_path': '', 'canvas_filename': getattr(file, 'filename', '')}
                            res_data['manifest'] = manifest
                            
                        continue

                    # UNCONDITIONAL status text update - fires instantly for every file (no throttle)
                    render_active_file(active_file_placeholder, display_file_name)
                    
                    # Throttled progress update (Prevent Streamlit from choking on rapid tiny files)
                    curr_time = _time.time()
                    if curr_time - last_ui_update > 0.4:
                        render_progress_bar(progress_container, max(0, current_file - 1), total_files)
                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                        last_ui_update = curr_time

                    try:
                        # file.filename may contain subfolder prefixes
                        # (e.g. "Assignments/Name/doc.pdf"). Sanitize each
                        # path component individually to preserve hierarchy,
                        # then extract only the basename - the parent
                        # directory is already handled by calc_path routing.
                        _fn_parts = Path(file.filename).parts
                        filename = cm._sanitize_filename(_fn_parts[-1]) if _fn_parts else cm._sanitize_filename(file.filename)
                        
                        # Task 4: Target Path Resolution
                        target_dir = local_path
                        calc_path = getattr(file, '_target_local_path', '')

                        # Fallback to sync_info properties explicitly. With Fix 2
                        # (`_adopt_redownload` stamping target_local_path onto the
                        # queued file) this fallback is rarely needed, but it's
                        # kept as a safety net for any future code path that
                        # appends to ``all_files`` without going through the
                        # redownload promotion.
                        if not calc_path:
                            # Union of clean + modified updates (updated_files is a
                            # computed property returning their concatenation).
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

                        # Update routing:
                        #  - CLEAN update (md5 matches original): overwrite in place.
                        #    The local file is byte-identical to what we downloaded,
                        #    so replacing it loses nothing and avoids `_NewVersion` clutter.
                        #  - MODIFIED update (student edited locally): save alongside
                        #    as `_NewVersion` so annotations survive.
                        #  - LOCALLY-DELETED redownload: clean overwrite. The file is
                        #    by definition not on disk at this path, so any sibling
                        #    we encounter is something the user kept intentionally
                        #    (e.g. an earlier `_NewVersion`). Reclaim the original
                        #    name without a numeric suffix.
                        is_update_clean = file in sel.get('updates_clean', [])
                        is_update_modified = file in sel.get('updates_modified', [])
                        is_redownload = bool(getattr(file, '_is_redownload', False))

                        if is_update_modified and filepath.exists():
                            base = filepath.stem
                            ext = filepath.suffix
                            # Place _NewVersion alongside the original, not at course root
                            filepath = filepath.parent / f"{base}_NewVersion{ext}"
                            filepath = cm._handle_conflict(filepath)
                        elif is_update_clean or is_redownload:
                            # Clean update / locally-deleted redownload → claim the
                            # EXACT path. We deliberately do NOT pre-delete the
                            # existing file: the atomic os.replace(.part → filepath)
                            # below overwrites it in a single step, so there is never
                            # a window where the file is missing if the download
                            # fails or the app crashes mid-transfer. A locked target
                            # is handled gracefully at the os.replace site, which
                            # falls back to a _NewVersion sibling so the user's open
                            # file is preserved and the new bytes still land on disk.
                            pass
                        elif filepath.exists():
                            filepath = cm._handle_conflict(filepath)

                        _file_id_val = getattr(file, 'id', 0)
                        if _file_id_val < 0 and secondary_id_type(_file_id_val) == 'attachment':
                            # ── Mode B Attachments → Binary Download Path ──
                            # Attachments are REAL Canvas files tracked under synthetic
                            # negative IDs when isolate_secondary_content is on (the
                            # default). They must NOT enter the synthetic-entity branch
                            # below (which only handles regenerable entities and
                            # .url/.html shortcuts and would silently skip a PDF).
                            # Fall through to the binary downloader - its URL-refresh
                            # block maps the negative ID back to the raw Canvas file ID.
                            if _debug_file:
                                log_debug(f"  Secondary [attachment → binary downloader]: {display_file_name}", _debug_file)
                        elif _file_id_val < 0:
                            # ── Secondary Content Entities (Assignment, Quiz, etc.) ──
                            _sec_entity_type = secondary_id_type(file.id)
                            if _debug_file:
                                log_debug(f"  Secondary [{_sec_entity_type}]: {display_file_name}", _debug_file)
                            if _sec_entity_type != 'attachment' and _sec_entity_type not in ('module_item', 'unknown'):
                                # Load secondary contract for this pair
                                _raw_sec = sync_mgr._load_metadata('secondary_content_contract')
                                if _raw_sec is None:
                                    # H-3: First-ever sync for this pair - seed the secondary
                                    # contract from session state so future syncs don't use
                                    # an empty contract and silently skip secondary content.
                                    _fallback_sec = {
                                        'download_assignments':   st.session_state.get('persistent_dl_assignments', False),
                                        'download_syllabus':      st.session_state.get('persistent_dl_syllabus', False),
                                        'download_announcements': st.session_state.get('persistent_dl_announcements', False),
                                        'download_discussions':   st.session_state.get('persistent_dl_discussions', False),
                                        'download_quizzes':       st.session_state.get('persistent_dl_quizzes', False),
                                        'download_rubrics':       st.session_state.get('persistent_dl_rubrics', False),
                                        'download_submissions':   st.session_state.get('persistent_dl_submissions', False),
                                        'isolate_secondary_content': st.session_state.get('persistent_dl_isolate_secondary', True),
                                    }
                                    try:
                                        sync_mgr._save_metadata('secondary_content_contract', json.dumps(_fallback_sec))
                                    except Exception:
                                        pass
                                    _raw_sec = json.dumps(_fallback_sec)
                                try:
                                    _sec_settings = json.loads(_raw_sec) if _raw_sec else {}
                                except (json.JSONDecodeError, TypeError, ValueError):
                                    _sec_settings = {}

                                # Mode A inline: derive the module subfolder from
                                # the analyzer's target_local_path so the entity
                                # writes to the right module folder. (In Mode B,
                                # _resolve_secondary_path always routes to the
                                # category folder, so module_path is ignored.)
                                _sec_module_path = None
                                if not _sec_settings.get('isolate_secondary_content', True):
                                    _calc_dir = Path(calc_path).parent if calc_path else Path('.')
                                    if str(_calc_dir) not in ('.', ''):
                                        _sec_module_path = local_path / _calc_dir

                                # H-8: cancel check before blocking Canvas API call
                                if is_sync_cancelled():
                                    break

                                try:
                                    # H-7: rate-limit secondary API calls with the
                                    # same semaphore as regular file downloads so
                                    # they don't bypass the concurrency cap.
                                    async with sem:
                                        sec_filepath, sec_id, sec_attachments, canvas_updated = await asyncio.to_thread(
                                            safe_thread_wrapper,
                                            cm.download_secondary_entity,
                                            current_ctx,
                                            res_data['course'],
                                            file,
                                            Path(local_path),
                                            sync_mgr,
                                            _sec_settings,
                                            None, None, Path(local_path), course_name,
                                            _sec_module_path,
                                        )
                                except Exception as _sec_err:
                                    # Re-raise preserving the original traceback
                                    raise

                                if sec_filepath:
                                    synced_counter[0] += 1
                                    st.session_state['sync_cancelled_file_count'] = synced_counter[0]
                                    synced_details[pair_idx].append(sec_filepath.name)
                                    terminal_log.append(log_line('success', sec_filepath.name, icon=file_icon_svg(sec_filepath.name)))
                                    log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                    if _debug_file:
                                        log_debug(f"✓ Secondary: {sec_filepath.name}", _debug_file)

                                    # ── Inject attachments into the async download queue ──
                                    # Attachments have REAL positive Canvas file IDs, so they
                                    # bypass the `file.id < 0` branch and enter the standard
                                    # HTTP download path with full retry + cancellation support.
                                    if sec_attachments:
                                        from sync_manager import (
                                            CanvasFileInfo as _CFI,
                                            make_secondary_id as _make_sec_id,
                                        )
                                        attach_dir = sec_filepath.parent

                                        # Deduplication guard: prevent double-queueing if
                                        # the attachment was already in the sync selection
                                        # (e.g. both HTML + attachment were locally deleted)
                                        _queued_ids = {getattr(f, 'id', None) for f in all_files}

                                        # On-disk dedup: attachments whose manifest entry
                                        # already points to a file currently present on
                                        # disk should not be re-queued - that's the
                                        # "delete only the .html, redownload it" failure
                                        # mode that produces ``attachment (1).pdf``.
                                        # Attachment IDs are positive in Mode A and
                                        # synthetic-negative in Mode B, so we look up
                                        # both forms.
                                        _isolate_now = _sec_settings.get('isolate_secondary_content', True)
                                        _files_section = manifest.get('files', {})

                                        for att in sec_attachments:
                                            att_id = att.get('id')
                                            att_url = att.get('url', '')
                                            att_filename = att.get('filename', att.get('display_name', 'attachment'))

                                            if not att_url or not att_id:
                                                continue

                                            # H-2: Look up BOTH the positive and synthetic-negative
                                            # manifest IDs. If the user toggled isolate_secondary_content
                                            # between syncs, the old entry uses the opposite ID form
                                            # and a single-form lookup would always miss it, causing the
                                            # same attachment to be re-downloaded every sync forever.
                                            _pos_entry = _files_section.get(str(att_id))
                                            _neg_entry = _files_section.get(str(_make_sec_id('attachment', att_id)))
                                            _manifest_entry = _pos_entry or _neg_entry
                                            _manifest_att_id = (
                                                _make_sec_id('attachment', att_id) if _isolate_now else att_id
                                            )
                                            if _manifest_entry:
                                                _existing_path = local_path / _manifest_entry.get('local_path', '')
                                                if _existing_path.exists():
                                                    continue  # Already on disk - skip re-queue

                                            # Guard against cross-queue and intra-document duplicates
                                            if att_id in _queued_ids or _manifest_att_id in _queued_ids:
                                                continue

                                            # Add the ID to the set to prevent duplicate links
                                            # within the same HTML document from firing twice
                                            _queued_ids.add(att_id)
                                            att_info = _CFI(
                                                id=_manifest_att_id,
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
                                                ).replace('\\', '/')
                                            except ValueError:
                                                # Fallback: attachment dir is outside local_path - use filename only
                                                att_info._target_local_path = cm._sanitize_filename(att_filename)
                                            all_files.append(att_info)
                                            total_files += 1
                                            terminal_log.append(log_line('queued', att_filename, icon=file_icon_svg(att_filename)))
                                            log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                            if _debug_file:
                                                log_debug(
                                                    f"  Attachment queued: {att_filename} → {getattr(att_info, '_target_local_path', '?')}",
                                                    _debug_file,
                                                )

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
                                    # L-7: Count unknown/failed secondary entities in the error
                                    # list so the completion screen shows a non-zero error count
                                    # rather than silently dropping them.
                                    terminal_log.append(log_line('skip', display_file_name, icon=file_icon_svg(display_file_name)))
                                    log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                    error_list.append(f"Skipped secondary entity: {display_file_name}")
                                    if _debug_file:
                                        log_debug(f"⚠ Skipped secondary: {display_file_name}", _debug_file)
                                continue

                            # ── Legacy Synthetic Shortcuts (Pages, External URLs) ──
                            Path(make_long_path(filepath.parent)).mkdir(parents=True, exist_ok=True)

                            is_url_ext = filepath.name.lower().endswith('.url') or filepath.name.lower().endswith('.webloc')
                            is_html_ext = filepath.name.lower().endswith('.html')

                            # H-1: Guard against empty/missing URL before writing shortcut.
                            # An ExternalUrl module item with a stale or empty URL would
                            # produce a broken [InternetShortcut]\nURL=\n file.
                            if (is_url_ext or is_html_ext) and not getattr(file, 'url', ''):
                                terminal_log.append(log_line('skip', display_file_name, icon=file_icon_svg(display_file_name), detail='no URL'))
                                log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                error_list.append(f"Skipped {display_file_name}: no URL for shortcut")
                                continue

                            if is_url_ext:
                                if platform.system() == 'Darwin':
                                    import plistlib
                                    plist_data = {'URL': file.url}
                                    async with aiofiles.open(str(make_long_path(filepath)), 'wb') as f:
                                        await f.write(plistlib.dumps(plist_data, fmt=plistlib.FMT_XML))
                                else:
                                    _safe_url = file.url.replace('\r', '').replace('\n', '%0A')
                                    shortcut_content = f"[InternetShortcut]\nURL={_safe_url}\n"
                                    async with aiofiles.open(str(make_long_path(filepath)), 'w', encoding='utf-8') as f:
                                        await f.write(shortcut_content)
                            elif is_html_ext:
                                html_content = f'<meta http-equiv="refresh" content="0; url={esc(file.url)}">'
                                async with aiofiles.open(str(make_long_path(filepath)), 'w', encoding='utf-8') as f:
                                    await f.write(html_content)

                            if is_url_ext or is_html_ext:
                                rel_path = str(filepath.relative_to(local_path)).replace('\\', '/')
                                sync_mgr.add_file_to_manifest(manifest, file, rel_path)
                                # One record per final on-disk path (see binary-download note).
                                _rel_key = os.path.normcase(rel_path)
                                if _rel_key not in synced_rel_paths[pair_idx]:
                                    synced_rel_paths[pair_idx].add(_rel_key)
                                    synced_counter[0] += 1
                                    st.session_state['sync_cancelled_file_count'] = synced_counter[0]
                                    synced_details[pair_idx].append(display_file_name)
                                terminal_log.append(log_line('success', display_file_name, icon=file_icon_svg(display_file_name)))
                                log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                if _debug_file:
                                    _sc_type = "URL shortcut" if is_url_ext else "HTML redirect"
                                    log_debug(f"✓ Shortcut ({_sc_type}): {display_file_name}", _debug_file)
                                continue

                            continue # Ensure Legacy Synthetic block definitively skips binary downloader

                        if _debug_file:
                            _rtype = (
                                "modified update (_NewVersion)" if is_update_modified else
                                "clean update (overwrite)" if is_update_clean else
                                "redownload (overwrite)" if is_redownload else
                                "new file"
                            )
                            try:
                                _rel = filepath.relative_to(local_path)
                            except ValueError:
                                _rel = filepath
                            log_debug(f"  → [{_rtype}] {display_file_name} → {_rel}", _debug_file)

                        # Refresh download URL from Canvas API (signed URLs expire quickly)
                        download_url = file.url
                        try:
                            course = res_data['course']
                            
                            real_id = file.id
                            if real_id < 0:
                                if secondary_id_type(real_id) == 'attachment':
                                    real_id = abs(real_id) - SECONDARY_ID_OFFSETS['attachment']
                            fresh_file = await asyncio.to_thread(safe_thread_wrapper, course.get_file, current_ctx, real_id)
                            fresh_url = getattr(fresh_file, 'url', '')
                            if fresh_url:
                                download_url = fresh_url
                        except Exception:
                            pass  # Keep original URL as fallback

                        if download_url:
                            for attempt in range(SYNC_MAX_RETRIES):
                                if is_sync_cancelled():
                                    break

                                should_sleep_duration = 0
                                # Bytes written during THIS attempt - rolled back from the
                                # MB counters if the attempt fails and is retried, so the
                                # dashboard never double-counts re-downloaded chunks.
                                _attempt_bytes = 0

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
                                                                if is_sync_cancelled():
                                                                    download_interrupted = True
                                                                    break
                                                                
                                                                chunk = await response.content.read(1024 * 1024)
                                                                if not chunk:
                                                                    break
                                                                await f.write(chunk)
                                                                chunk_size = len(chunk)
                                                                _attempt_bytes += chunk_size
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
                                                                    
                                                                    render_progress_bar(progress_container, current_file, total_files)
                                                                    last_ui_update = c_t
                                                    except Exception as write_err:
                                                        download_interrupted = True
                                                        raise write_err
                                                    
                                                    # Handle interrupted download: clean up and stop retrying
                                                    if download_interrupted:
                                                        if is_sync_cancelled():
                                                            break  # Cancel confirmed - exit retry loop immediately
                                                        continue  # Non-cancel interrupt - retry
                                                    
                                                    # 100% success: atomic rename .part → final path
                                                    try:
                                                        os.replace(make_long_path(part_path), make_long_path(filepath))
                                                    except PermissionError:
                                                        # Target is locked (open in another app). Don't lose the
                                                        # freshly-downloaded bytes - deliver them alongside as a
                                                        # _NewVersion sibling so the user's open file is untouched
                                                        # and the new version still lands on disk. The manifest is
                                                        # recorded against this resolved path below.
                                                        try:
                                                            _alt = filepath.parent / f"{filepath.stem}_NewVersion{filepath.suffix}"
                                                            _alt = cm._handle_conflict(_alt)
                                                            os.replace(make_long_path(part_path), make_long_path(_alt))
                                                            filepath = _alt
                                                            terminal_log.append(log_line('attention', _alt.name, icon=file_icon_svg(_alt.name), detail='original in use'))
                                                            log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                                            if _debug_file:
                                                                log_debug(f"  Target locked; delivered as {_alt.name}", _debug_file)
                                                        except (PermissionError, OSError) as _alt_err:
                                                            error_msg = f"Cannot write file (it may be open in another program): {filepath}"
                                                            logger.error(f"{error_msg} :: {_alt_err}")
                                                            try:
                                                                os.unlink(make_long_path(part_path))
                                                            except OSError:
                                                                pass
                                                            raise RuntimeError(error_msg)

                                                    atomic_rename_done = True
                                                    
                                                    # Only commit to DB AFTER file is physically complete on disk
                                                    rel_path = str(filepath.relative_to(local_path)).replace('\\', '/')
                                                    sync_mgr.add_file_to_manifest(manifest, file, rel_path)

                                                    # Count + list each final on-disk path ONCE. A second queue
                                                    # entry that resolved to this exact path (same physical file
                                                    # reached via two sources, e.g. regular File + attachment)
                                                    # just overwrote it - so it must not inflate "files synced"
                                                    # nor show a duplicate row on the completion screen.
                                                    final_name = filepath.name
                                                    _rel_key = os.path.normcase(rel_path)
                                                    if _rel_key not in synced_rel_paths[pair_idx]:
                                                        synced_rel_paths[pair_idx].add(_rel_key)
                                                        synced_counter[0] += 1
                                                        st.session_state['sync_cancelled_file_count'] = synced_counter[0]
                                                        synced_details[pair_idx].append(final_name)
                                                    terminal_log.append(log_line('success', final_name, icon=file_icon_svg(final_name)))
                                                    log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                                    if _debug_file:
                                                        log_debug(f"✓ {final_name}", _debug_file)
                                                finally:
                                                    # GUARD: Always clean up .part if rename didn't complete
                                                    # Catches: write errors, network drops, disk-full, any exception
                                                    if not atomic_rename_done:
                                                        try:
                                                            if Path(make_long_path(part_path)).exists():
                                                                Path(make_long_path(part_path)).unlink()
                                                        except OSError:
                                                            pass
                                                
                                                break  # Success - exit retry loop
                                            
                                            elif response.status == 429:
                                                # Rate limited - respect Retry-After (RFC 7231: seconds int or HTTP-date string)
                                                _retry_after_raw = response.headers.get('Retry-After', '')
                                                try:
                                                    should_sleep_duration = int(_retry_after_raw)
                                                except (ValueError, TypeError):
                                                    should_sleep_duration = SYNC_RETRY_DELAY * (2 ** attempt)
                                                terminal_log.append(log_line('attention', display_file_name, icon=file_icon_svg(display_file_name), detail=f'rate limited · retry in {should_sleep_duration}s'))
                                                log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                                if _debug_file:
                                                    log_debug(f"Rate limited: {display_file_name} (retry in {should_sleep_duration}s, attempt {attempt + 1}/{SYNC_MAX_RETRIES})", _debug_file)
                                            
                                            elif 500 <= response.status < 600:
                                                # Server error - retry with exponential backoff
                                                should_sleep_duration = SYNC_RETRY_DELAY * (2 ** attempt)
                                                if attempt < SYNC_MAX_RETRIES - 1:
                                                    terminal_log.append(log_line('attention', display_file_name, icon=file_icon_svg(display_file_name), detail=f'server {response.status} · retry {attempt + 1}/{SYNC_MAX_RETRIES}'))
                                                    log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                                    if _debug_file:
                                                        log_debug(
                                                            f"  Server {response.status}: {display_file_name} (retry {attempt + 1}/{SYNC_MAX_RETRIES}, wait {should_sleep_duration}s)",
                                                            _debug_file,
                                                        )
                                                else:
                                                    # Max retries exhausted for 5xx
                                                    failed_files_for_pair.append(file)
                                                    error_list.append(f"Error syncing {esc(display_file_name)}: HTTP {response.status} after {SYNC_MAX_RETRIES} retries")
                                                    terminal_log.append(log_line('error', display_file_name, icon=file_icon_svg(display_file_name), detail=f'HTTP {response.status} after {SYNC_MAX_RETRIES} retries'))
                                                    log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                                    if _debug_file:
                                                        log_debug(f"✗ Server {response.status}: {display_file_name} (exhausted {SYNC_MAX_RETRIES} retries)", _debug_file)
                                                    break
                                            
                                            else:
                                                # Non-retryable HTTP error (4xx except 429)
                                                failed_files_for_pair.append(file)
                                                error_list.append(f"Error syncing {esc(display_file_name)}: HTTP {response.status}")
                                                terminal_log.append(log_line('error', display_file_name, icon=file_icon_svg(display_file_name), detail=f'HTTP {response.status}'))
                                                log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                                if _debug_file:
                                                    log_debug(f"✗ HTTP {response.status}: {display_file_name}", _debug_file)
                                                break  # Don't retry client errors
                                
                                except (aiohttp.ClientError, asyncio.TimeoutError) as net_err:
                                    # Roll back this attempt's partial bytes so the retry
                                    # doesn't double-count them in the MB dashboard.
                                    if _attempt_bytes:
                                        downloaded_mb = max(0.0, downloaded_mb - _attempt_bytes / (1024 * 1024))
                                        synced_counter[1] = max(0, synced_counter[1] - _attempt_bytes)
                                    # TLS verification failures are permanent for this run -
                                    # the trust store won't change between retries, so fail
                                    # fast instead of burning the backoff budget per file.
                                    if isinstance(net_err, aiohttp.ClientConnectorCertificateError) or 'CERTIFICATE_VERIFY_FAILED' in str(net_err):
                                        failed_files_for_pair.append(file)
                                        error_list.append(f"Error syncing {esc(display_file_name)}: Secure connection to Canvas could not be verified (SSL certificate error)")
                                        terminal_log.append(log_line('error', display_file_name, icon=file_icon_svg(display_file_name), detail='SSL certificate error'))
                                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                        if _debug_file:
                                            log_debug(f"✗ SSL certificate error (permanent, no retry): {display_file_name}: {net_err}", _debug_file)
                                        break
                                    # Network error - retry with backoff
                                    if attempt < SYNC_MAX_RETRIES - 1:
                                        should_sleep_duration = SYNC_RETRY_DELAY * (2 ** attempt)
                                        terminal_log.append(log_line('attention', display_file_name, icon=file_icon_svg(display_file_name), detail=f'network error · retry {attempt + 1}/{SYNC_MAX_RETRIES}'))
                                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                        if _debug_file:
                                            log_debug(
                                                f"  Network error: {display_file_name} (retry {attempt + 1}/{SYNC_MAX_RETRIES}): {net_err}",
                                                _debug_file,
                                            )
                                    else:
                                        failed_files_for_pair.append(file)
                                        error_list.append(f"Error syncing {esc(display_file_name)}: Network error: {net_err}")
                                        terminal_log.append(log_line('error', display_file_name, icon=file_icon_svg(display_file_name), detail=f'network error after {SYNC_MAX_RETRIES} retries'))
                                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                                        if _debug_file:
                                            log_debug(f"✗ Network error: {display_file_name}: {net_err}", _debug_file)
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
                            terminal_log.append(log_line('error', display_file_name, icon=file_icon_svg(display_file_name), detail=err_msg))
                            log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                            if _debug_file:
                                log_debug(f"✗ No URL: {display_file_name} ({err_msg})", _debug_file)

                    except Exception as e:
                        failed_files_for_pair.append(file)
                        error_list.append(f"Error syncing {esc(display_file_name)}: {esc(str(e))}")
                        terminal_log.append(log_line('error', display_file_name, icon=file_icon_svg(display_file_name), detail=str(e)))
                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                        if _debug_file:
                            # Full traceback: this broad handler catches genuine
                            # code bugs (e.g. the 2026-06-11 UnboundLocalError),
                            # and str(e) alone doesn't say WHERE they happened.
                            from canvas_debug import log_debug_exc
                            log_debug_exc(f"✗ Exception: {display_file_name}: {e}", _debug_file, exc=e)
                        

                
                if failed_files_for_pair:
                    safe_res_data = sel['res_data'].copy()
                    # Strip heavy objects to protect Streamlit memory integrity
                    safe_res_data.pop('course', None)
                    safe_res_data.pop('sync_manager', None)
                    
                    # BUG FIX: Restore failed items to their exact correct buckets using O(1) Dictionaries
                    # Preserve the clean/modified split so retries honour the
                    # same overwrite-vs-`_NewVersion` routing as the initial run.
                    modified_ids = {getattr(f, 'id', None) for f in sel.get('updates_modified', [])}
                    update_map: Dict[int, CanvasFileInfo] = {getattr(f, 'id', None): f for f in sel['updates']}
                    # M-12: Skip entries with None/zero ID - a corrupt manifest entry
                    # with canvas_file_id=None would key the dict as None, then match
                    # every failed file that also has id=None, causing infinite retries.
                    redownload_map: Dict[int, SyncFileInfo] = {}
                    for _r in sel['redownload']:
                        _rid = getattr(_r, 'canvas_file_id', _r[0] if isinstance(_r, tuple) else None)
                        if _rid is not None:
                            redownload_map[_rid] = _r

                    retry_new: List[CanvasFileInfo] = []
                    retry_updates_clean: List[CanvasFileInfo] = []
                    retry_updates_modified: List[CanvasFileInfo] = []
                    retry_redownload: List[SyncFileInfo] = []

                    for failed_item in failed_files_for_pair:
                        # --- FIX: Tuple Identity Loss ---
                        # Mirror O(1) redownload_map logic: try 'id', then 'canvas_file_id', then tuple explicit index
                        f_id = getattr(failed_item, 'id', getattr(failed_item, 'canvas_file_id', failed_item[0] if isinstance(failed_item, tuple) else None))
                        if f_id in update_map:
                            recovered = update_map[f_id]
                            if f_id in modified_ids:
                                retry_updates_modified.append(recovered)
                            else:
                                retry_updates_clean.append(recovered)
                        elif f_id in redownload_map:
                            retry_redownload.append(redownload_map[f_id])
                        else:
                            retry_new.append(failed_item)

                    retry_selections.append({
                        'pair_idx': pair_idx,
                        'res_data': safe_res_data,
                        'new': retry_new,
                        'updates': retry_updates_clean + retry_updates_modified,
                        'updates_clean': retry_updates_clean,
                        'updates_modified': retry_updates_modified,
                        'redownload': retry_redownload,
                        'ignore': [],
                    })
                        
            # Final 100% UI Paint after the loop
            elapsed_final = _time.time() - start_time
            speed_final = (downloaded_mb / elapsed_final) if elapsed_final > 0 else 0
            render_progress_bar(progress_container, total_files, total_files)
            metrics_dashboard.markdown(render_metrics_html_compat(synced_counter[0], total_files, downloaded_mb, total_mb, speed_final, "00:00"), unsafe_allow_html=True)
            active_file_placeholder.markdown(f"<p style='color: {theme.TEXT_SECONDARY}; font-size: 0.9rem; font-style: italic;'>Finalizing sync…</p>", unsafe_allow_html=True)
            log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)

            # CANCEL GUARD: Skip all post-download state mutations if cancelled.
            # Do NOT call st.rerun() here - this coroutine runs in a background
            # ThreadPoolExecutor thread. RerunException escaping the thread would
            # bypass the post-processing pipeline. Signal cancellation via early
            # return and let the script thread handle the rerun after .result().
            if is_sync_cancelled():
                st.session_state['download_status'] = 'sync_cancelled'
                return synced_details, retry_selections, list(terminal_log)

            for sel in sync_selections:
                res_data = sel['res_data']
                sync_mgr = res_data.get('sync_manager')
                manifest = res_data.get('manifest')
                if sync_mgr is None or manifest is None:
                    continue
                local_path = sync_mgr.local_path

                sync_mgr.save_manifest(manifest)

                # H-5: Force WAL checkpoint so all committed pages are merged
                # into the main DB file. Without this, a crash immediately after
                # a bulk sync leaves the manifest in the WAL rather than the DB.
                try:
                    import sqlite3 as _sqlite3
                    from ui_helpers import make_long_path as _mlp
                    with _sqlite3.connect(_mlp(str(sync_mgr.db_path)), timeout=10.0) as _ckpt_conn:
                        _ckpt_conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                except Exception as _ckpt_err:
                    logger.warning(f"WAL checkpoint failed for {sync_mgr.db_path}: {_ckpt_err}")

                # Setup updates reference explicitly to fix `updates is not defined` NameError traceback
                updates = sel['updates']
                _exec_result = res_data.get('result')
                deletions = _exec_result.deleted_on_canvas if _exec_result else []
                if updates or deletions:
                    log_file_path = local_path / "☁️ Canvas Updates & Deletions.txt"
                    
                    import urllib.parse
                    now = datetime.now()
                    day = now.day
                    ordinal = str(day) + ("th" if 4 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th"))
                    if st.session_state.get('use_12h_format', False):
                        nice_date = now.strftime(f"%A, %B {ordinal}, %Y")       # American: "Monday, April 28th, 2026"
                    else:
                        nice_date = now.strftime(f"%A the {ordinal} of %B, %Y")  # European: "Monday the 28th of April, 2026"
                    
                    course_name = friendly_course_name(res_data['pair']['course_name']) or 'Unnamed Course'
                    
                    try:
                        with open(make_long_path(log_file_path), "a", encoding="utf-8") as lf:
                            lf.write(f"\n{'='*60}\n")
                            lf.write(f" ☁️ CANVAS DOWNLOADER: SYNC REPORT \n")
                            lf.write(f" Course: {course_name}\n")
                            from ui_helpers import format_time_display
                            lf.write(f" Date:   {nice_date} at {format_time_display(now.strftime('%H:%M'))}\n")
                            lf.write(f"{'='*60}\n\n")
                            
                            lf.write("💡 HOW TO USE THIS LOG:\n")
                            lf.write("This document tracks files that were modified or deleted by your teacher on Canvas.\n")
                            lf.write("Canvas Downloader NEVER deletes your local files. If a file is deleted on Canvas,\n")
                            lf.write("it is listed here so you know the teacher removed it, but you still have your local copy.\n")
                            lf.write("If a file was updated, we downloaded the new version and kept your old version safely alongside it.\n\n")
                            
                            if updates:
                                lf.write("🔄 UPDATED FILES (New versions downloaded):\n")
                                for f in updates:
                                    clean_name = urllib.parse.unquote(f.filename)
                                    lf.write(f"  - {clean_name}\n")
                                lf.write("\n")
                            if deletions:
                                lf.write("🗑️ DELETED ON CANVAS (Your local copies are safe):\n")
                                for si in deletions:
                                    clean_name = urllib.parse.unquote(si.canvas_filename)
                                    lf.write(f"  - {clean_name}\n")
                            lf.write("\n")
                    except Exception as e:
                        logging.warning(f"Failed to write updates log: {e}")
                
        return synced_details, retry_selections, list(terminal_log)

    # Extract variables locally to preserve Streamlit ThreadContext boundary.
    # Run the async download loop in a dedicated thread with its own event loop
    # so that asyncio.run() never conflicts with Tornado's running loop.
    local_sync_api_token = st.session_state.get('api_token', '')
    local_sync_api_url = st.session_state.get('api_url', '')
    import concurrent.futures as _cf

    # ── Re-attachable worker + script-thread heartbeat ──────────────────
    # Streamlit only delivers pending button clicks (as a RerunException) at
    # the next st.* call made ON THE SCRIPT THREAD. A plain blocking
    # future.result() therefore deferred Cancel until the whole batch had
    # finished downloading in the background. The heartbeat below yields to
    # Streamlit every 0.5s, so a Cancel click reruns the script immediately;
    # the rerun re-enters run_sync, the Cancel branch sets the threading
    # Event, and the worker's per-chunk is_sync_cancelled() checks stop the
    # batch within ~a second. Non-cancel reruns RE-ATTACH to the running
    # worker (or reuse the cached result) instead of submitting a duplicate.
    _cached_run = st.session_state.get('sync_worker_result')
    if _cached_run is None:
        if st.session_state.get('sync_worker_future') is None:
            _pool = _cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="canvas-sync-worker")
            st.session_state['sync_worker_pool'] = _pool
            st.session_state['sync_worker_future'] = _pool.submit(
                asyncio.run,
                download_sync_files_batch(local_sync_api_token, local_sync_api_url)
            )
        _future = st.session_state['sync_worker_future']
        _heartbeat = st.empty()
        try:
            while True:
                try:
                    synced_details, retry_selections, _download_log_history = _future.result(timeout=0.5)
                    break
                except _cf.TimeoutError:
                    # Script-thread yield point - lets Streamlit deliver
                    # pending clicks while the worker keeps downloading.
                    _heartbeat.markdown("")
                    continue
        except Exception as _worker_exc:
            # An unhandled exception in the async download worker (e.g. SQLite
            # write failure, aiohttp teardown error) propagates here. Surface it
            # as a clean sync-failed state instead of a raw Streamlit traceback.
            # (RerunException is a BaseException and passes through untouched.)
            logging.error(f"Sync worker thread raised an unexpected exception: {_worker_exc}", exc_info=True)
            _release_sync_worker()
            st.session_state['download_status'] = 'sync_failed'
            st.session_state['sync_worker_error'] = str(_worker_exc)
            st.rerun()
        _heartbeat.empty()
        _release_sync_worker()
        # Snapshot the worker outcome so a rerun during the post-processing
        # phase (any click) resumes HERE instead of re-downloading the batch.
        _cached_run = {
            'synced_details': synced_details,
            'retry_selections': retry_selections,
            'log': _download_log_history,
            'synced_count': synced_counter[0],
            'synced_bytes': synced_counter[1],
            'errors': list(error_list),
        }
        st.session_state['sync_worker_result'] = _cached_run
    else:
        # Post-processing-phase rerun: restore the completed worker outcome.
        synced_details = _cached_run['synced_details']
        retry_selections = _cached_run['retry_selections']
        _download_log_history = _cached_run['log']
        synced_counter[0] = _cached_run['synced_count']
        synced_counter[1] = _cached_run['synced_bytes']
        error_list[:] = _cached_run['errors']

    # Deferred cancel: checked here on the script thread so RerunException
    # never escapes the background coroutine and skips post-processing.
    # L-11: Pre-set status so the rerun doesn't re-enter 'syncing' for one pass.
    if is_sync_cancelled():
        st.session_state.pop('sync_worker_result', None)
        st.session_state['download_status'] = 'sync_cancelled'
        st.rerun()

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
            sm = res_data.get('sync_manager')
            if sm is None:
                continue
            for fname in synced_details.get(pair_idx, []):
                fname_path = Path(fname)
                # Match on the primary suffix OR on the full compound suffix
                # (e.g. '.tar.gz') so .tar.gz is caught precisely without
                # accidentally matching standalone .gz files.
                all_suffixes = ''.join(fname_path.suffixes).lower()
                if fname_path.suffix.lower() in target_exts or all_suffixes in target_exts:
                    matches = list(sm.local_path.rglob(_glob.escape(fname)))
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
    if is_sync_cancelled():
        st.session_state.pop('sync_worker_result', None)
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

    # Cancel button hover CSS already injected at top of run_sync() - no duplicate needed.

    st.session_state['is_post_processing'] = True

    # Log post-processing phase per pair to each course's debug file
    if st.session_state.get('debug_mode'):
        for _pp_sel in sync_selections:
            _pp_sm = _pp_sel.get('res_data', {}).get('sync_manager')
            if not _pp_sm:
                continue
            _pp_dbg = str(_pp_sm.local_path / 'debug_log.txt')
            _pp_name = friendly_course_name(_pp_sel['res_data']['pair']['course_name'])
            _pp_contract = _pp_sel.get('res_data', {}).get('contract', {})
            log_debug(f"--- Post-Processing: {_pp_name} ---", _pp_dbg)
            _conv_status = {
                'ZIP extract':  _pp_contract.get('convert_zip',   st.session_state.get('persistent_convert_zip',   False)),
                'PPTX→PDF':     _pp_contract.get('convert_pptx',  st.session_state.get('persistent_convert_pptx',  False)),
                'HTML→Markdown':_pp_contract.get('convert_html',  st.session_state.get('persistent_convert_html',  False)),
                'Code→TXT':     _pp_contract.get('convert_code',  st.session_state.get('persistent_convert_code',  False)),
                'URL compile':  _pp_contract.get('convert_urls',  st.session_state.get('persistent_convert_urls',  False)),
                'Word→PDF':     _pp_contract.get('convert_word',  st.session_state.get('persistent_convert_word',  False)),
                'Excel→PDF+Data':_pp_contract.get('convert_excel',st.session_state.get('persistent_convert_excel', False)),
                'Video→MP3':    _pp_contract.get('convert_video', st.session_state.get('persistent_convert_video', False)),
            }
            _active_convs = [k for k, v in _conv_status.items() if v]
            log_debug(f"Active converters: {', '.join(_active_convs) if _active_convs else 'none'}", _pp_dbg)
            _pp_idx = _pp_sel['pair_idx']
            log_debug(f"Synced files available for conversion: {len(synced_details.get(_pp_idx, []))}", _pp_dbg)

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

    # Resolve error_log_path for post-processing: respect the toggle,
    # and use the first sync pair's local_path as the error log directory.
    _sync_error_log_path = None
    if st.session_state.get('error_log_enabled', False) and sync_selections:
        _first_sm = sync_selections[0].get('res_data', {}).get('sync_manager')
        if _first_sm and hasattr(_first_sm, 'local_path'):
            _sync_error_log_path = _first_sm.local_path

    pp_ui = UIBridge(
        header_placeholder=status_text,
        progress_placeholder=progress_container,
        metrics_placeholder=metrics_dashboard,
        log_placeholder=log_container,
        active_file_placeholder=active_file_placeholder,
        log_lines=_download_log_history,
        is_cancelled=is_sync_cancelled,
        on_detail_update=_on_detail_update,
        error_log_path=_sync_error_log_path,
    )

    # macOS: prime Office automation before the converters run. The download
    # flow primes at download-start; a sync that was NOT preceded by a download
    # would otherwise launch Office cold here - re-introducing the "contains
    # macros" dialog and the per-file dock-bounce. Priming writes the suite-wide
    # macro-security pref (DisabledWithoutWarnings) and launches the needed apps
    # hidden, well before run_excel_conversion (the last converter) opens a file.
    # Once per run via the shared sentinel (reset on cleanup).
    import sys as _sys_prime
    if _sys_prime.platform == 'darwin':
        try:
            from engine.applescript_bridge import prime_office_automation
            # Scope to the file types ACTUALLY queued for conversion this sync, so a
            # sync that only converts PowerPoint never opens Word or Excel. Each app
            # is launched at most once per run (idempotent inside prime_office_automation).
            prime_office_automation({
                'convert_pptx': bool(get_synced_file_paths({'.ppt', '.pptx', '.pptm', '.pot', '.potx'}, 'persistent_convert_pptx')),
                'convert_word': bool(get_synced_file_paths({'.doc', '.rtf', '.odt'}, 'persistent_convert_word')),
                'convert_excel': bool(get_synced_file_paths({'.xlsx', '.xls', '.xlsm'}, 'persistent_convert_excel')),
            })
        except Exception as _sync_prime_err:
            logger.warning(f"Failed to prime Office automation for sync: {_sync_prime_err}")

    # 6. Run each converter with per-course contract evaluation via get_synced_file_paths

    # Archive Extraction
    run_archive_extraction(
        get_synced_file_paths({'.zip', '.tar', '.tar.gz'}, 'persistent_convert_zip'), pp_ui
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

    # M-13: URL Compilation operates on the whole course folder by design -
    # new and existing .url shortcuts both need to land in the compiled
    # Compiled_External_Links.txt. Do NOT scope this to synced files only.
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
    # .xls (Excel 97-2003) is a binary format openpyxl cannot read - exclude it
    # from data extraction (mirrors run_all_conversions in the download flow).
    # ExcelToPDF via COM/AppleScript handles .xls fine in the PDF step below.
    run_excel_data_conversion(
        get_synced_file_paths({'.xlsx', '.xlsm'}, 'persistent_convert_excel'), pp_ui
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
                existing = synced_details.setdefault(matched_pair_idx, [])
                if sidecar_name not in existing:
                    existing.append(sidecar_name)
                    # M-2: Do NOT bump synced_counter for sidecars - they are bonus
                    # artifacts tied to a parent file already counted. Bumping here
                    # would show "3 files synced" for 1 Excel → 1 PDF + 1 .txt sidecar.


    # Clear the blue status text so it doesn't linger on completion
    active_file_placeholder.empty()

    # Post-processing finished - reset the flag so the cancelled-screen
    # phase detection (used by show_sync_cancelled) doesn't misreport
    # the phase if a follow-on cancel arrives before cleanup_sync_state.
    st.session_state['is_post_processing'] = False

    # Write per-pair completion summary to debug log
    if st.session_state.get('debug_mode'):
        for _fin_sel in sync_selections:
            _fin_sm = _fin_sel.get('res_data', {}).get('sync_manager')
            if not _fin_sm:
                continue
            _fin_dbg = str(_fin_sm.local_path / 'debug_log.txt')
            _fin_name = friendly_course_name(_fin_sel['res_data']['pair']['course_name'])
            _fin_idx = _fin_sel['pair_idx']
            _fin_files = synced_details.get(_fin_idx, [])
            log_debug(f"=== Sync Complete: {_fin_name} ===", _fin_dbg)
            log_debug(
                f"This pair: {len(_fin_files)} files synced | "
                f"Total across all pairs: {synced_counter[0]} | "
                f"Errors: {len(error_list)} | PP failures: {pp_ui.pp_failure_count}",
                _fin_dbg,
            )
            for _fn in _fin_files:
                log_debug(f"  [SYNCED] {_fn}", _fin_dbg)
            if error_list:
                log_debug(f"Errors ({len(error_list)}):", _fin_dbg)
                for _err in error_list:
                    log_debug(f"  [ERROR] {_err}", _fin_dbg)

    st.session_state['synced_count'] = synced_counter[0]
    st.session_state['synced_bytes'] = synced_counter[1]
    st.session_state['sync_errors'] = error_list
    st.session_state['pp_failure_count'] = pp_ui.pp_failure_count

    # Retry feedback: if this was a retry pass, compute how many errors were
    # resolved so the completion card can show "Recovered X of Y".
    if is_retry:
        _retry_total = st.session_state.get('retry_total_attempted', 0)
        st.session_state['retry_resolved_count'] = max(0, _retry_total - len(error_list))
        st.session_state['retry_attempted'] = True
    # Store detailed synced files for the completion screen dropdowns
    # synced_details is a dict: { pair_idx: [ "filename1", "filename2", ... ] }
    st.session_state['synced_details'] = dict(synced_details)
    st.session_state['retry_selections'] = retry_selections

    # Per-course breakdown with resolved file paths - powers the per-file
    # Open / Reveal actions on the completion screen and the landing-page
    # "New files since last sync" panel. Built once here, after post-processing.
    try:
        synced_groups = _build_synced_groups(sync_selections, synced_details)
    except Exception as e:
        logger.warning(f"Failed to build synced file groups: {e}")
        synced_groups = []
    st.session_state['synced_groups'] = synced_groups

    # Update last_synced timestamps atomically
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    updates = []
    pairs = st.session_state.get('sync_pairs', [])
    for sel in sync_selections:
        pair_idx = sel['pair_idx']
        
        # Save securely to folder database
        try:
            if 'res_data' in sel and 'sync_manager' in sel['res_data']:
                sel['res_data']['sync_manager']._save_metadata('last_synced', now_str)
        except Exception as e:
            logger.warning(f"Failed to save last_synced to db: {e}")
            
        if pair_idx < len(pairs):
            updates.append((pairs[pair_idx].get('course_id'), pairs[pair_idx].get('local_folder'), now_str))
    
    if updates:
        _update_last_synced_batch(updates)

    # Record sync history - also for all-failed runs (synced 0, errors > 0)
    # so the user can see in the Hub that a sync was attempted and failed.
    if synced_counter[0] > 0 or error_list:
        try:
            from ui_helpers import get_config_dir
            history_mgr = SyncHistoryManager(get_config_dir())
            
            import unicodedata as _ud_hist
            categorized_files = {'new': [], 'updated': [], 'restored': [], 'protected': []}
            synced_course_names = []

            for sel in sync_selections:
                pair_idx = sel['pair_idx']
                pair_files = synced_details.get(pair_idx, [])
                if pair_files:
                    synced_course_names.append(sel['res_data']['pair']['course_name'])

                # Updates / restores categorisation MUST mirror _build_synced_groups
                # exactly so the history panel and completion screen agree. Both use
                # the shared basename-variant helpers (which decode '+' and %XX and
                # NFC-normalize) instead of the bare unquote that mis-labelled
                # form-encoded names as brand-'new'.
                updates_for_pair = set()
                res_data = sel.get('res_data', {})
                if res_data and 'result' in res_data and hasattr(res_data['result'], 'updated_files'):
                    for _cf, _sf in res_data['result'].updated_files:
                        updates_for_pair |= _basename_variants(getattr(_cf, 'filename', '') or '')
                        updates_for_pair |= _basename_variants(getattr(_sf, 'local_path', '') or '')

                redownloads_for_pair = _redownload_restore_keys(sel.get('redownload'))

                for fname in pair_files:
                    try:
                        _fn_key = _ud_hist.normalize('NFC', fname)
                    except Exception:
                        _fn_key = fname
                    if "_NewVersion" in fname:
                        categorized_files['protected'].append(fname)
                    elif _fn_key in updates_for_pair:
                        categorized_files['updated'].append(fname)
                    elif _fn_key in redownloads_for_pair:
                        categorized_files['restored'].append(fname)
                    else:
                        categorized_files['new'].append(fname)

            history_mgr.add_entry({
                'timestamp': now_str,
                'files_synced': synced_counter[0],
                'courses': len(sync_selections),
                'course_names': list(set(synced_course_names)),
                'errors': len(error_list),
                'error_details': error_list,
                'synced_files': [fname for pair_files in synced_details.values() for fname in pair_files],
                'categorized_files': categorized_files,
                # Per-course breakdown (course + rel path + category) so the
                # "New files since last sync" panel can group, sort, Open & Reveal.
                'synced_groups': synced_groups,
                'sync_mode': st.session_state.get('sync_mode', 'normal')
            })
            # M-1: Invalidate the step-1 history cache so the next render
            # re-reads from disk and shows the entry we just wrote.
            st.session_state.pop('_sync_history_cache', None)
            # Remember this entry's timestamp so the terminal Panopto pass can
            # amend THIS entry with the recordings it downloads afterwards
            # (instead of them being silently absent from sync history).
            st.session_state['_sync_history_ts'] = now_str
        except Exception as e:
            logger.error(f"Failed to record sync history: {e}")

    # Run fully consumed - drop the cached worker snapshot so the next sync
    # (including the Retry path, which re-enters with status='syncing')
    # starts a fresh download batch.
    st.session_state.pop('sync_worker_result', None)

    if is_sync_cancelled():
        st.session_state['download_status'] = 'sync_cancelled'
        st.session_state['sync_cancelled_file_count'] = synced_counter[0]
    else:
        # Stash how many recordings analysis found already up to date, so the
        # completion card can show an honest "N already up to date" note instead
        # of the old misleading "Skipped" count - regardless of whether the
        # Panopto pass runs.
        _pan_uptodate = 0
        _pan_selected = 0
        for _sel in sync_selections:
            _pan_uptodate += sum(
                1 for _c in (_sel.get('res_data', {}).get('panopto') or {}).get('changes', [])
                if _c.bucket is None  # uptodate
            )
            _pan_selected += len(_sel.get('panopto', []))
        st.session_state['panopto_uptodate_total'] = _pan_uptodate

        # Terminal Panopto pass (premium feature) runs after the file sync, before
        # the completion screen - mirrors the Download-mode 'panopto' phase. It runs
        # whenever the user actually selected at least one recording in Review.
        # Selection is already gated per-folder by each folder's contract (a folder
        # with no Panopto outputs configured surfaces no recordings to select), so
        # the selection count alone is the correct, per-folder-aware trigger.
        if _pan_selected > 0:
            st.session_state['download_status'] = 'sync_panopto'
        else:
            st.session_state['download_status'] = 'sync_complete'
            # No recordings to process, but surface the up-to-date count on the
            # completion card when there were recordings in the course(s). Guard:
            # never clobber a real summary already produced by the Panopto pass
            # (e.g. on a post-Panopto file Retry, which re-enters run_sync with
            # no recordings selected but the real results still on screen).
            if _pan_uptodate > 0 and not st.session_state.get('panopto_summary'):
                st.session_state['panopto_summary'] = {
                    'found': 0, 'downloaded': 0, 'transcribed': 0, 'skipped': 0,
                    'failed': 0, 'courses': 0, 'selected': 0,
                    'uptodate': _pan_uptodate,
                }

    st.session_state['step'] = 4
    st.rerun()
