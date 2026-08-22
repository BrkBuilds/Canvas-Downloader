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

from shared import theme
from core.canvas_logic import CanvasManager
from core.cancellation import cancel_sync, is_sync_cancelled
# NOTE: never re-import these names *locally* inside a function in this
# module - a local `from core.sync_manager import secondary_id_type` makes the
# name function-local for the ENTIRE enclosing function scope, so earlier
# uses raise UnboundLocalError ("cannot access local variable
# 'secondary_id_type'"). This bit the sync download loop on 2026-06-11.
from core.sync_manager import (
    SyncFileInfo, SyncHistoryManager, CanvasFileInfo,
    secondary_id_type, SECONDARY_ID_OFFSETS,
    _path_key,
)
from shared.helpers import (
    path_exists,
    esc,
    learned_transfer_priors,
    remember_transfer_priors,
    render_progress_bar,
    render_sync_wizard,
    friendly_course_name,  # noqa: F401 - debug-log call sites keep the Canvas name
    robust_filename_normalize,
    make_long_path,
    LOCKED_FILE_REASON,
    LTI_STREAM_REASON,
    is_lti_stream_ext,
)
from styles import inject_css
from engine.estimation import transfer_estimator
from engine.progress_dashboard import (
    build_metrics_row, build_terminal_html, render_active_file,
    transfer_metrics, log_line, log_meta, file_icon_svg,
)
from core.canvas_debug import log_debug
from core.pair_labels import pair_display_name

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


def _redownload_target(local_path: Path, recorded_rel: str, filename: str):
    """Resolve the on-disk target for restoring a locally-deleted file.

    ``recorded_rel`` is the manifest's tracked relative path; ``filename`` is
    the sanitized name of the file the download will actually fetch from
    Canvas. When the extensions match, the restore claims the EXACT recorded
    path (survives the user's folder reorganization). When they differ, the
    recorded path is a conversion PRODUCT (e.g. the .pdf produced from this
    .pptx; the source was deleted after converting) - writing raw source bytes
    under the product's name would corrupt it, so the SOURCE is restored into
    the recorded folder and the ownership-aware converter regenerates the
    product in place (mirrors the clean-update routing).

    Returns ``(filepath, target_dir)``, or ``(None, None)`` when the recorded
    parent no longer exists (caller falls back to the canonical calc_path).
    """
    recorded = local_path / Path(recorded_rel)
    if str(recorded.parent) == '.' or not path_exists(recorded.parent):
        return None, None
    if recorded.suffix.lower() == Path(filename).suffix.lower():
        return recorded, recorded.parent
    return recorded.parent / filename, recorded.parent


def _build_synced_groups(sync_selections, synced_details, synced_actual_rels=None):
    """Build a per-course breakdown of the files synced this run.

    Resolves every synced file to its on-disk location (relative to the course
    folder) so the completion screen and the landing-page "New files since last
    sync" panel can offer Open / Reveal actions per file. Runs once at finalize
    on the script thread - AFTER post-processing.

    ``synced_actual_rels`` is the authoritative source: it holds, 1:1 with each
    pair's ``synced_details`` entries, the REAL relative path the sync engine
    wrote (post conflict-resolution - e.g. display name "Filer til Klynge 1.html"
    was written as "Page Filer til Klynge 1 (1).html"). Resolution starts from
    that path; when post-processing converted the file (html -> md, office ->
    pdf, ...) and deleted the original, the stem of the ACTUAL name - not the
    display name - is matched against the files on disk (all converters keep
    the stem; the code converter folds the old extension into it). Display-name
    lookups remain as the final fallback for entries without an actual path
    (e.g. sidecar artifacts appended after the download phase).

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
        actual_rels = (synced_actual_rels or {}).get(pair_idx, [])
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
        # stem_index (filename sans extension -> [rel paths]) backs the
        # converted-file fallback below.
        name_index = {}
        stem_index = {}
        if course_root is not None:
            try:
                root_str = str(course_root)
                # Walk THROUGH the prefix, and take the relative path against
                # the prefixed root too, so `rel` still comes out clean. A deep
                # course folder enumerates NOTHING under a bare os.walk, and
                # every synced file would then fail to resolve.
                _root_lp = make_long_path(root_str)
                for dirpath, _dirnames, filenames in os.walk(_root_lp):
                    for fn in filenames:
                        if fn.startswith('._') or fn == '.canvas_sync.db':
                            continue
                        rel = os.path.relpath(os.path.join(dirpath, fn), _root_lp).replace('\\', '/')
                        # Key on the NFC-normalized basename so the lookup below
                        # is resilient to NFC/NFD mismatches between disk and the
                        # Canvas-supplied filename.
                        name_index.setdefault(_norm(fn), []).append(rel)
                        stem_index.setdefault(_norm(os.path.splitext(fn)[0]), []).append(rel)
            except Exception:
                name_index = {}
                stem_index = {}

        files = []
        # Paths already assigned to an earlier record this course, so two synced
        # entries that share a basename but genuinely live in DIFFERENT subfolders
        # each resolve to their OWN path instead of both collapsing onto the
        # freshest copy (which would hide one behind a duplicate-looking row).
        used_rels: set[str] = set()
        for _i, nm in enumerate(names):
            # The REAL path the engine wrote this entry to (1:1 with names for
            # everything registered during the download phase; sidecars appended
            # afterwards have no actual path and use the display-name fallback).
            _act_rel = actual_rels[_i].replace('\\', '/') if _i < len(actual_rels) else None
            _act_base = os.path.basename(_act_rel) if _act_rel else ''

            _nm_key = _norm(nm)
            _act_key = _norm(_act_base) if _act_base else None
            if "_NewVersion" in nm or "_NewVersion" in _act_base:
                category = 'protected'
            elif _nm_key in updates_for_pair or (_act_key and _act_key in updates_for_pair):
                category = 'updated'
            elif _nm_key in redownloads_for_pair or (_act_key and _act_key in redownloads_for_pair):
                category = 'restored'
            else:
                category = 'new'

            rel = None
            candidates = None
            if _act_rel and course_root is not None:
                if os.path.isfile(make_long_path(os.path.join(str(course_root), _act_rel))):
                    # Still on disk exactly where it was written - done. This is
                    # what makes display-name/on-disk-name divergence (module
                    # Pages: "X.html" recorded, "Page X (1).html" written)
                    # irrelevant to resolution.
                    rel = _act_rel
                else:
                    # CONVERTED-FILE fallback: post-processing converted the
                    # written file (html→md, pptx/docx/xlsx→pdf, mp4→mp3,
                    # code→"stem_ext.txt") and deleted the original. All
                    # converters keep the stem (the code converter folds the
                    # old extension INTO it), so match the ACTUAL name's stem -
                    # never the display name's, which may not share it -
                    # preferring hits in the directory the file was written to.
                    _stem, _ext = os.path.splitext(_act_base)
                    _ext = _ext.lstrip('.').lower()
                    _act_dir = os.path.dirname(_act_rel)
                    for _skey in ((f"{_stem}_{_ext}" if _ext else None), _stem):
                        if not _skey:
                            continue
                        _cands = stem_index.get(_norm(_skey))
                        if _cands:
                            _same_dir = [c for c in _cands
                                         if os.path.dirname(c) == _act_dir]
                            candidates = _same_dir or _cands
                            break

            if rel is None and not candidates:
                # Display-name fallback (entries without an actual path, or
                # whose written file vanished entirely): exact basename first,
                # then the same conversion-stem match on the display name.
                candidates = name_index.get(_nm_key)
                if not candidates:
                    _stem, _ext = os.path.splitext(nm)
                    _ext = _ext.lstrip('.').lower()
                    for _skey in ((f"{_stem}_{_ext}" if _ext else None), _stem):
                        if _skey:
                            candidates = stem_index.get(_norm(_skey))
                            if candidates:
                                break

            if rel is None and candidates:
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
                            key=lambda r: os.path.getmtime(
                                make_long_path(os.path.join(str(course_root), r))),
                        )
                    except Exception:
                        rel = pool[0]

            if rel is not None:
                used_rels.add(rel)
                display_name = os.path.basename(rel)
            else:
                # Nothing resolvable - degrade to the recorded name (buttons
                # disabled) rather than guessing at an unrelated file.
                rel = nm
                display_name = nm

            files.append({'name': display_name, 'rel': rel, 'category': category})

        groups.append({
            'pair_idx': pair_idx,
            'course_name': pair.get('course_name', ''),
            'course_id': pair.get('course_id'),
            'local_folder': str(course_root) if course_root is not None else '',
            # The saved library pair id (if this pair references one), so history
            # can resolve the user's name by the STABLE id even after the folder
            # is later moved - see core.pair_labels.label_for_id.
            'saved_id': pair.get('saved_id'),
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
                    arm_app_data_access,
                )
                reset_office_priming()
                # One-time per machine: fire ALL outstanding Office permission
                # prompts NOW, while the user is at the screen (they just started
                # the sync) - instead of letting each app's prompt ambush a later
                # run mid-conversion. Unscoped toggles on purpose; the in-run
                # prime stays file-scoped. Idempotent across reruns (module flag
                # + persisted record inside first_run_permission_setup).
                _conv_contract = {
                    'convert_pptx': st.session_state.get('persistent_convert_pptx', False),
                    'convert_word': st.session_state.get('persistent_convert_word', False),
                    'convert_excel': st.session_state.get('persistent_convert_excel', False),
                }
                if first_run_permission_setup(_conv_contract):
                    st.session_state['_tcc_batch_active'] = True
                # Every session (not one-time): the macOS 15+ App Data consent
                # is forgotten at quit by OS design, so re-fire its single
                # prompt at run start rather than mid-conversion.
                arm_app_data_access(_conv_contract)
            except Exception:
                pass

    # Daily auto-sync (Today dashboard) requests a SLIM progress view: only a
    # progress bar + status line, no wizard / metrics / terminal log. The proven
    # async loop is untouched - it just writes its metrics/active-file/log into a
    # hidden container (see placeholder creation below).
    _today_minimal = st.session_state.get('today_sync_active', False)

    # Step wizard. In Today mode the surrounding in-page card already shows the
    # "Running daily sync / Quick Sync" title + phase description, so no wizard or
    # duplicate step-header here - just the slim status line + progress bar below.
    if not _today_minimal:
        render_sync_wizard(st, 'sync')
        st.markdown('<h2 class="step-header">Syncing...</h2>', unsafe_allow_html=True)

    # First-run macOS permission batch is in flight: tell the user the upcoming
    # system dialogs are expected and one-time (mirrors the download flow).
    if st.session_state.get('_tcc_batch_active'):
        from ui.amber_notice import render_info_notice
        from engine.applescript_bridge import TCC_FIRST_RUN_NOTICE
        render_info_notice(
            TCC_FIRST_RUN_NOTICE,  # audit-ignore: TCC_FIRST_RUN_NOTICE is a static module constant
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

    if _today_minimal:
        status_text = st.empty()
        progress_container = st.empty()
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
        # One card around the whole readout (see the "Run dashboard card" block
        # in global.css). Today mode is excluded above: the Today page already
        # hosts this inside its own titled card.
        with st.container(key="progress_dashboard"):
            status_text = st.empty()
            progress_container = st.empty()
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
        if _today_minimal:
            # Today dashboard run: hand back to render_sync_step4's today handler
            # (status == 'sync_cancelled'), which cleans up and returns to the
            # idle Today page. Keep step==4 so that handler is reached.
            st.session_state['download_status'] = 'sync_cancelled'
        elif st.session_state.get('qs_cancel_route', False):
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
    # Full-page sync only. The rule hides every sibling AFTER the marker within
    # the enclosing stVerticalBlock, matched by *descendant* :has(). In the Today
    # in-page card the marker sits deep inside `today_running_card`, so that same
    # :has() also matches main_col's wrapper div for the card and would hide its
    # following sibling - the whole `today_content_area` (courses + today's files
    # + Quick Sync). That is why the dimmed content vanished the moment the run
    # entered the download phase. The slim card has no stale wizard elements to
    # hide (its metrics/log live in the hidden today_hidden_sync_ui container),
    # so skip the marker entirely in Today mode.
    if not _today_minimal:
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

    def render_terminal_html_compat(lines):
        """Backward-compatible alias for build_terminal_html (engine)."""
        return build_terminal_html(lines)

    async def download_sync_files_batch(sync_api_token, sync_api_url):
        import threading as _threading
        from streamlit.runtime.scriptrunner import add_script_run_ctx as _add_ctx
        _add_ctx(_threading.current_thread(), _script_ctx)
        from core.canvas_logic import safe_thread_wrapper
        current_ctx = _script_ctx  # captured on script thread above

        cm = CanvasManager(sync_api_token, sync_api_url)
        cm.error_log_enabled = st.session_state.get('error_log_enabled', False)
        from core.canvas_debug import log_debug
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
        # H-3: binary downloads now run CONCURRENTLY (bounded by this semaphore),
        # matching the download engine. Secondary-entity generation stays
        # sequential - it discovers and enqueues attachment downloads.
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
        # H-8: original-case relative paths of every file written this run, per
        # pair. Post-processing resolves its conversion targets from THIS list -
        # never by globbing bare filenames across the whole course tree (which
        # used to convert-and-delete unrelated same-named files).
        synced_actual_rels = defaultdict(list)
        retry_selections = []

        # certifi-backed SSL context: frozen macOS builds have no OpenSSL default
        # CA paths, so aiohttp must be pointed at certifi explicitly (see
        # canvas_logic.get_ssl_context).
        from core.canvas_logic import get_ssl_context
        from core.sync_manager import preferred_disk_name as _pref_name
        from core.sync_manager import compute_local_md5 as _compute_md5
        import hashlib as _hashlib
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

            files_done = 0        # completed (success/skip/fail) - drives the bar
            downloaded_mb = 0.0
            total_pairs = len(sync_selections)

            render_progress_bar(progress_container, 0, total_files)

            # Setup Tracking Variables
            start_time = _time.time()
            last_ui_update = 0
            terminal_log = deque(maxlen=200)

            # One estimator for the whole batch, seeded with whatever the last
            # transfer in this session measured so the first seconds of a sync
            # are not spent re-learning the connection from scratch.
            estimator = transfer_estimator(**learned_transfer_priors())
            estimator.update(units_total=total_files, bytes_total=total_mb * 1024 * 1024,
                             now=start_time)

            # Initial UI Draw
            metrics_dashboard.markdown(build_metrics_row(transfer_metrics(
                estimator, done_files=0, total_files=total_files,
                done_bytes=0.0, total_bytes=total_mb * 1024 * 1024,
            )), unsafe_allow_html=True)
            render_active_file(active_file_placeholder, "Preparing sync...")
            log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)

            def _register_new_version(path, reason):
                """Record a file delivered as a ``_NewVersion`` sibling.

                Both routes here end the same way for the user - a second file
                appears next to the one they already had - and until 2026-07-28
                neither said so anywhere. The locked-target route is the worse
                of the two because the user made no choice at all: they had the
                file open, the sync quietly wrote the fresh copy beside it, and
                the name they recognise is now the STALE one.
                """
                try:
                    _lst = st.session_state.get('sync_newversion_files') or []
                    _lst.append({'name': path.name, 'reason': reason})
                    st.session_state['sync_newversion_files'] = _lst
                except Exception:
                    pass      # never let bookkeeping break a sync

            def _register_synced_path(pair_idx, rel_path, display_name):
                """Count + list each final on-disk path ONCE (see synced_rel_paths)."""
                _rel_key = os.path.normcase(rel_path)
                if _rel_key not in synced_rel_paths[pair_idx]:
                    synced_rel_paths[pair_idx].add(_rel_key)
                    synced_counter[0] += 1
                    st.session_state['sync_cancelled_file_count'] = synced_counter[0]
                    synced_details[pair_idx].append(display_name)
                    synced_actual_rels[pair_idx].append(rel_path)

            def _paint_metrics():
                """Throttled progress/metrics repaint - safe to call from any
                coroutine (they all share this one event-loop thread)."""
                nonlocal last_ui_update
                c_t = _time.time()
                # Feed the model on EVERY call, not only on the ones that
                # repaint: the throttle exists to spare the browser, and
                # sampling the estimator at 2.5 Hz instead of per chunk would
                # throw away most of what it has to learn from.
                estimator.update(units_done=files_done, bytes_done=downloaded_mb * 1024 * 1024,
                                 units_total=total_files, bytes_total=total_mb * 1024 * 1024,
                                 now=c_t)
                if c_t - last_ui_update > 0.4:
                    metrics_dashboard.markdown(build_metrics_row(transfer_metrics(
                        estimator,
                        done_files=files_done, total_files=total_files,
                        done_bytes=downloaded_mb * 1024 * 1024,
                        total_bytes=total_mb * 1024 * 1024,
                    )), unsafe_allow_html=True)
                    # Hold the bar off 100% while secondary content is still
                    # arriving - it raises both counters together, so the ratio
                    # pins at "done" while real work continues.
                    _bar_done = files_done
                    if estimator.is_open_ended and total_files > 0:
                        _bar_done = min(files_done, total_files - 1)
                    render_progress_bar(progress_container, _bar_done, total_files)
                    log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                    last_ui_update = c_t

            for pair_idx, sel in enumerate(sync_selections):
                if is_sync_cancelled():
                    break

                failed_files_for_pair = []

                res_data = sel['res_data']
                sync_mgr = res_data.get('sync_manager')
                manifest = res_data.get('manifest')
                canvas_files_map = {f.id: f for f in res_data['canvas_files']}
                pair = res_data['pair']

                # TWO names, and which one goes where is deliberate.
                #   course_name  - what the USER calls this course (their name
                #                  from Saved Groups & Pairs, else the Canvas
                #                  name). Screens and messages the user reads.
                #   _log_name    - always the CANVAS name. The debug log is a
                #                  diagnostic artefact read against Canvas, and
                #                  tests/audit/harness/oracles/log.py parses the
                #                  "=== Sync Execution: <course> | Mode:" line to
                #                  attribute every event to a course - putting a
                #                  nickname there would silently unhook the audit
                #                  harness from the run it is auditing.
                course_name = pair_display_name(pair, fallback='Unnamed Course')
                _log_name = friendly_course_name(pair['course_name']) or 'Unnamed Course'

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
                    from core.canvas_debug import set_active_debug_file as _set_dbg, log_session_header as _dbg_header
                    _set_dbg(_debug_file)
                    if pair_idx == 0:
                        _dbg_header(_debug_file, context=f"Sync execution | {total_pairs} pair(s)")
                    _sync_mode_label = "Quick Sync" if st.session_state.get('sync_quick_mode') else "Analyze, Review & Sync"
                    log_debug(f"=== Sync Execution: {_log_name} | Mode: {_sync_mode_label} ===", _debug_file)
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
                        course = await asyncio.to_thread(safe_thread_wrapper, cm.canvas.get_course, current_ctx, pair['course_id'])
                        res_data['course'] = course
                    except Exception as e:
                        err_str = f"Connection failure to {esc(course_name)}: {esc(str(e))}"
                        error_list.append(err_str)
                        terminal_log.append(log_line('error', f"Reconnection failed: {course_name}", detail=str(e)))
                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                        if _debug_file:
                            from core.canvas_debug import log_debug_exc
                            log_debug_exc(f"✗ Reconnection failed: {course_name}: {e}", _debug_file, exc=e)
                        failed_files_for_pair.extend(sel.get('new', []))
                        continue

                # M-10: load this pair's secondary-content contract ONCE (the
                # old code re-read it from SQLite for every secondary file).
                # H-3 seed: first-ever sync for this pair - persist the session
                # settings so future syncs don't silently use an empty contract.
                _raw_sec = sync_mgr._load_metadata('secondary_content_contract')
                if _raw_sec is None:
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
                    _pair_sec_settings = json.loads(_raw_sec) if _raw_sec else {}
                except (json.JSONDecodeError, TypeError, ValueError):
                    _pair_sec_settings = {}

                all_files = list(sel['new']) + list(sel['updates'])

                # H-2: stamp every queued update with its analyzer SyncFileInfo
                # so target resolution can honour the HEALED on-disk location
                # (the folder/name the user moved or renamed the file to)
                # instead of re-materializing the canonical Canvas layout.
                _result_obj = res_data.get('result')
                if _result_obj is not None and hasattr(_result_obj, 'updated_files'):
                    _queued_by_ident = {id(f): f for f in all_files}
                    for _u_cf, _u_si in _result_obj.updated_files:
                        _q = _queued_by_ident.get(id(_u_cf))
                        if _q is not None:
                            try:
                                _q._update_sync_info = _u_si
                            except Exception:
                                pass

                def _adopt_redownload(target_obj, sync_info):
                    """Stamp the queued file with the analyzer's resolved
                    target path + a flag marking it as a locally-deleted
                    redownload, plus the SyncFileInfo itself so H-2 can
                    restore the file to its previously recorded location.
                    """
                    try:
                        if getattr(sync_info, 'target_local_path', ''):
                            target_obj._target_local_path = sync_info.target_local_path
                    except Exception:
                        pass
                    try:
                        target_obj._is_redownload = True
                        target_obj._redownload_info = sync_info
                    except Exception:
                        pass
                    return target_obj

                for sync_info in sel['redownload']:
                    # 0. M-6: teacher re-upload - the analyzer attached the NEW
                    # canvas file object directly; adopt it without guessing.
                    _reup = getattr(sync_info, '_reupload_new_file', None)
                    if _reup is not None:
                        all_files.append(_adopt_redownload(_reup, sync_info))
                        continue

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
                            url="",
                            name_locked=True,
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

                # Targets claimed by dispatched downloads this pair, so two
                # same-named files resolved concurrently can never collide on
                # one .part path (dispatch is sequential; only the downloads
                # themselves overlap).
                _dispatched_targets: set = set()
                pair_tasks: list = []

                def _claim_target(p):
                    """Reserve a final path for one dispatch; suffix on collision."""
                    cand = p
                    # _path_key, not normcase - on a case-insensitive volume
                    # "Notes.pdf" and "notes.pdf" ARE one file, so two Canvas
                    # files whose sanitized names differ only in case would each
                    # claim a "free" path and then write over each other.
                    key = _path_key(cand)
                    counter = 1
                    while key in _dispatched_targets:
                        cand = cand.parent / f"{cand.stem} ({counter}){cand.suffix}"
                        key = _path_key(cand)
                        counter += 1
                    _dispatched_targets.add(key)
                    return cand

                async def _download_binary(file, filepath, display_file_name,
                                            is_update_clean, is_update_modified,
                                            is_redownload):
                    """Download ONE binary file (concurrent; sem-bounded).

                    Owns the full lifecycle: signed-URL refresh, retry loop with
                    Retry-After/backoff (429 AND 403 - Canvas uses 403 for rate
                    limiting), atomic .part write with inline md5 hashing, the
                    locked-target _NewVersion fallback, manifest record, and
                    progress bookkeeping. All state mutations happen on the one
                    event-loop thread, so no locks are needed.
                    """
                    nonlocal downloaded_mb, files_done
                    try:
                        render_active_file(active_file_placeholder, display_file_name)

                        # Refresh download URL from Canvas API (signed URLs expire
                        # quickly). Sem-bounded so refreshes respect the same
                        # concurrency cap as the downloads themselves.
                        download_url = getattr(file, 'url', '')
                        fresh_file = None
                        try:
                            real_id = file.id
                            if real_id < 0:
                                if secondary_id_type(real_id) == 'attachment':
                                    real_id = abs(real_id) - SECONDARY_ID_OFFSETS['attachment']
                            async with sem:
                                fresh_file = await asyncio.to_thread(
                                    safe_thread_wrapper, res_data['course'].get_file, current_ctx, real_id)
                            fresh_url = getattr(fresh_file, 'url', '')
                            if fresh_url:
                                download_url = fresh_url
                        except Exception:
                            pass  # Keep original URL as fallback

                        if not download_url:
                            # Check for LTI/Media streams
                            if is_lti_stream_ext(filepath.suffix):
                                # The exact wording is a CONSTANT: the completion
                                # screen classifies these strings to decide what
                                # is a failure and what Canvas simply declined,
                                # so rewording it here would recolour the screen.
                                err_msg = LTI_STREAM_REASON
                            elif (getattr(file, 'locked_for_user', False)
                                  or getattr(fresh_file, 'locked_for_user', False)):
                                # Teacher-locked file: Canvas strips the URL for
                                # students; nothing (not even a browser) can fetch
                                # it until the teacher unlocks it.
                                err_msg = LOCKED_FILE_REASON
                            else:
                                err_msg = "No download URL"
                            failed_files_for_pair.append(file)
                            error_list.append(f"Error syncing {esc(display_file_name)}: {esc(err_msg)}")
                            terminal_log.append(log_line('error', display_file_name, icon=file_icon_svg(display_file_name), detail=err_msg))
                            _paint_metrics()
                            if _debug_file:
                                log_debug(f"✗ No URL: {display_file_name} ({err_msg})", _debug_file)
                            return

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
                                            # Hash inline so the manifest baseline never
                                            # needs a second full read of the file (M-10).
                                            _dl_hasher = _hashlib.md5()

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
                                                            _dl_hasher.update(chunk)
                                                            chunk_size = len(chunk)
                                                            _attempt_bytes += chunk_size
                                                            downloaded_mb += chunk_size / (1024 * 1024)
                                                            synced_counter[1] += chunk_size
                                                            _paint_metrics()
                                                except Exception as write_err:
                                                    download_interrupted = True
                                                    raise write_err

                                                # Handle interrupted download: clean up and stop retrying
                                                if download_interrupted:
                                                    if is_sync_cancelled():
                                                        break  # Cancel confirmed - exit retry loop immediately
                                                    continue  # Non-cancel interrupt - retry

                                                # 100% success: atomic rename .part → final path
                                                final_path = filepath
                                                try:
                                                    os.replace(make_long_path(part_path), make_long_path(final_path))
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
                                                        final_path = _alt
                                                        _register_new_version(_alt, 'in_use')
                                                        terminal_log.append(log_line('attention', _alt.name, icon=file_icon_svg(_alt.name), detail='original in use'))
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

                                                # Only commit to DB AFTER file is physically complete on disk.
                                                # Inline hash → no second full read (M-10). add_file_to_manifest
                                                # also mirrors the entry into the in-memory manifest, so the
                                                # finalize-phase save_manifest can never clobber it with stale data.
                                                rel_path = str(final_path.relative_to(local_path)).replace('\\', '/')
                                                sync_mgr.add_file_to_manifest(manifest, file, rel_path,
                                                                              local_md5=_dl_hasher.hexdigest())

                                                _register_synced_path(pair_idx, rel_path, final_path.name)
                                                terminal_log.append(log_line('success', final_path.name, icon=file_icon_svg(final_path.name)))
                                                _paint_metrics()
                                                if _debug_file:
                                                    log_debug(f"✓ {final_path.name}", _debug_file)
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

                                        elif response.status in (403, 429):
                                            # Rate limited - respect Retry-After (RFC 7231). M-2: Canvas
                                            # returns BOTH 403 ("Rate Limit Exceeded") and 429 under
                                            # pressure; the download engine already retried 403 - the
                                            # sync engine now matches it instead of failing the file.
                                            # Clamped: an unbounded server-chosen
                                            # Retry-After parks the whole sync on a
                                            # cancel-polling sleep that reads as a hang.
                                            from core.canvas_logic import parse_retry_after
                                            should_sleep_duration = parse_retry_after(
                                                response.headers.get('Retry-After', ''),
                                                SYNC_RETRY_DELAY * (2 ** attempt))
                                            if attempt < SYNC_MAX_RETRIES - 1:
                                                terminal_log.append(log_line('attention', display_file_name, icon=file_icon_svg(display_file_name), detail=f'rate limited ({response.status}) · retry in {should_sleep_duration}s'))
                                                _paint_metrics()
                                                if _debug_file:
                                                    log_debug(f"Rate limited ({response.status}): {display_file_name} (retry in {should_sleep_duration}s, attempt {attempt + 1}/{SYNC_MAX_RETRIES})", _debug_file)
                                            else:
                                                failed_files_for_pair.append(file)
                                                error_list.append(f"Error syncing {esc(display_file_name)}: HTTP {response.status} after {SYNC_MAX_RETRIES} retries")
                                                terminal_log.append(log_line('error', display_file_name, icon=file_icon_svg(display_file_name), detail=f'HTTP {response.status} after {SYNC_MAX_RETRIES} retries'))
                                                _paint_metrics()
                                                if _debug_file:
                                                    log_debug(f"✗ Rate limit ({response.status}): {display_file_name} (exhausted {SYNC_MAX_RETRIES} retries)", _debug_file)
                                                break

                                        elif 500 <= response.status < 600:
                                            # Server error - retry with exponential backoff
                                            should_sleep_duration = SYNC_RETRY_DELAY * (2 ** attempt)
                                            if attempt < SYNC_MAX_RETRIES - 1:
                                                terminal_log.append(log_line('attention', display_file_name, icon=file_icon_svg(display_file_name), detail=f'server {response.status} · retry {attempt + 1}/{SYNC_MAX_RETRIES}'))
                                                _paint_metrics()
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
                                                _paint_metrics()
                                                if _debug_file:
                                                    log_debug(f"✗ Server {response.status}: {display_file_name} (exhausted {SYNC_MAX_RETRIES} retries)", _debug_file)
                                                break

                                        else:
                                            # Non-retryable HTTP error (4xx except 403/429)
                                            failed_files_for_pair.append(file)
                                            error_list.append(f"Error syncing {esc(display_file_name)}: HTTP {response.status}")
                                            terminal_log.append(log_line('error', display_file_name, icon=file_icon_svg(display_file_name), detail=f'HTTP {response.status}'))
                                            _paint_metrics()
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
                                    _paint_metrics()
                                    if _debug_file:
                                        log_debug(f"✗ SSL certificate error (permanent, no retry): {display_file_name}: {net_err}", _debug_file)
                                    break
                                # Network error - retry with backoff
                                if attempt < SYNC_MAX_RETRIES - 1:
                                    should_sleep_duration = SYNC_RETRY_DELAY * (2 ** attempt)
                                    terminal_log.append(log_line('attention', display_file_name, icon=file_icon_svg(display_file_name), detail=f'network error · retry {attempt + 1}/{SYNC_MAX_RETRIES}'))
                                    _paint_metrics()
                                    if _debug_file:
                                        log_debug(
                                            f"  Network error: {display_file_name} (retry {attempt + 1}/{SYNC_MAX_RETRIES}): {net_err}",
                                            _debug_file,
                                        )
                                else:
                                    failed_files_for_pair.append(file)
                                    error_list.append(f"Error syncing {esc(display_file_name)}: Network error: {net_err}")
                                    terminal_log.append(log_line('error', display_file_name, icon=file_icon_svg(display_file_name), detail=f'network error after {SYNC_MAX_RETRIES} retries'))
                                    _paint_metrics()
                                    if _debug_file:
                                        log_debug(f"✗ Network error: {display_file_name}: {net_err}", _debug_file)
                                    break

                            # WE ARE NOW OUTSIDE THE SEMAPHORE LOCK
                            if should_sleep_duration > 0:
                                # Cancel-aware backoff sleep
                                for _ in range(max(1, int(should_sleep_duration))):
                                    if is_sync_cancelled():
                                        return
                                    await asyncio.sleep(1)
                                continue  # Retry

                    except Exception as e:
                        failed_files_for_pair.append(file)
                        error_list.append(f"Error syncing {esc(display_file_name)}: {esc(str(e))}")
                        terminal_log.append(log_line('error', display_file_name, icon=file_icon_svg(display_file_name), detail=str(e)))
                        _paint_metrics()
                        if _debug_file:
                            from core.canvas_debug import log_debug_exc
                            log_debug_exc(f"✗ Exception: {display_file_name}: {e}", _debug_file, exc=e)
                    finally:
                        files_done += 1
                        _paint_metrics()

                for file in all_files:
                    if is_sync_cancelled():
                        break

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

                    # Throttled progress update while dispatching
                    _paint_metrics()

                    try:
                        # file.filename may contain subfolder prefixes
                        # (e.g. "Assignments/Name/doc.pdf"). Sanitize each
                        # path component individually to preserve hierarchy,
                        # then extract only the basename - the parent
                        # directory is already handled by calc_path routing.
                        # Regular files prefer the display name (matching the
                        # download engine); constructed names are locked.
                        _disk_name = _pref_name(file) or file.filename
                        _fn_parts = Path(_disk_name).parts
                        filename = cm._sanitize_filename(_fn_parts[-1]) if _fn_parts else cm._sanitize_filename(_disk_name)

                        # Routing state
                        is_update_clean = file in sel.get('updates_clean', [])
                        is_update_modified = file in sel.get('updates_modified', [])
                        is_redownload = bool(getattr(file, '_is_redownload', False))
                        _upd_info = getattr(file, '_update_sync_info', None)
                        _redl_info = getattr(file, '_redownload_info', None)

                        # ── Target Path Resolution ──
                        # H-2 ("Respect name + location"): updates overwrite the
                        # file WHERE THE USER KEEPS IT (heal-resolved local_path),
                        # keeping their chosen name when the extension matches.
                        # Redownloads restore to the previously recorded location.
                        # Only genuinely new files use the canonical calc_path.
                        target_dir = local_path
                        filepath = None

                        if (is_update_clean or is_update_modified) and _upd_info is not None \
                                and getattr(_upd_info, 'local_path', ''):
                            _healed = local_path / Path(_upd_info.local_path)
                            if path_exists(_healed):
                                _dl_ext = Path(filename).suffix.lower()
                                if _healed.suffix.lower() == _dl_ext:
                                    # Same type → the user's file IS the target
                                    # (their name, their folder).
                                    filepath = _healed
                                    target_dir = _healed.parent
                                else:
                                    # Converted file (e.g. manifest tracks the
                                    # .pdf produced from this .pptx): download
                                    # the source into the user's folder; the
                                    # ownership-aware converter then overwrites
                                    # the tracked PDF in place.
                                    target_dir = _healed.parent
                                    filepath = target_dir / filename
                                    # ...and if the student EDITED that tracked
                                    # product, "in place" would destroy their
                                    # work. `_NewVersion` guards the download's
                                    # own target, which for a converted file is
                                    # the SOURCE - a different file that needs
                                    # no guarding. Measured: hints.md and
                                    # Create_ILearn_tables_sql.txt were both
                                    # regenerated straight over the edits, with
                                    # no _NewVersion anywhere.
                                    #
                                    # Told to the converter here, at the one
                                    # point that knows both facts, rather than
                                    # re-derived from hashes later: by the time
                                    # post-processing runs, this row has been
                                    # re-pointed at the freshly downloaded
                                    # source and no longer describes the
                                    # product at all.
                                    if is_update_modified and sync_mgr is not None:
                                        try:
                                            sync_mgr.protect_conversion_target(_healed)
                                        except Exception as _prot_err:
                                            # `_debug_file`, not `debug_file` -
                                            # the latter is bound nowhere in this
                                            # module, so this handler raised
                                            # NameError instead of logging. It
                                            # guards the edit-protection call, so
                                            # the one path that needed to be loud
                                            # about failing was the one that
                                            # could not say anything at all.
                                            log_debug(
                                                f"could not protect edited "
                                                f"conversion target {_healed}: "
                                                f"{_prot_err}", _debug_file)
                        elif is_redownload and _redl_info is not None \
                                and getattr(_redl_info, 'local_path', ''):
                            # Exact recorded path when the type matches; the
                            # SOURCE (for the converter to regenerate) when the
                            # record is a conversion product - see helper.
                            _redl_fp, _redl_dir = _redownload_target(
                                local_path, _redl_info.local_path, filename)
                            if _redl_fp is not None:
                                filepath = _redl_fp
                                target_dir = _redl_dir

                        if filepath is None:
                            calc_path = getattr(file, '_target_local_path', '')
                            if not calc_path and _upd_info is not None:
                                calc_path = getattr(_upd_info, 'target_local_path', '')
                            if not calc_path and _redl_info is not None:
                                calc_path = getattr(_redl_info, 'target_local_path', '')
                            if calc_path:
                                calc_dir = Path(calc_path).parent
                                if str(calc_dir) != '.':
                                    target_dir = local_path / calc_dir
                            filepath = target_dir / filename

                        Path(make_long_path(target_dir)).mkdir(parents=True, exist_ok=True)

                        # Update routing:
                        #  - CLEAN update (md5 matches original): overwrite in place.
                        #  - MODIFIED update (student edited locally): save alongside
                        #    as `_NewVersion` so annotations survive.
                        #  - LOCALLY-DELETED redownload: clean overwrite of the
                        #    recorded path (not on disk by definition).
                        if is_update_modified and path_exists(filepath):
                            base = filepath.stem
                            ext = filepath.suffix
                            # Place _NewVersion alongside the original, not at course root
                            filepath = filepath.parent / f"{base}_NewVersion{ext}"
                            filepath = cm._handle_conflict(filepath)
                            _register_new_version(filepath, 'edited')
                        elif is_update_clean or is_redownload:
                            # Clean update / redownload → claim the EXACT path. The
                            # atomic os.replace(.part → filepath) overwrites in a
                            # single step; a locked target falls back to _NewVersion
                            # at the os.replace site.
                            pass
                        elif path_exists(filepath):
                            filepath = cm._handle_conflict(filepath)

                        _file_id_val = getattr(file, 'id', 0)
                        if _file_id_val < 0 and secondary_id_type(_file_id_val) == 'attachment':
                            # ── Mode B Attachments → Binary Download Path ──
                            # Attachments are REAL Canvas files tracked under synthetic
                            # negative IDs when isolate_secondary_content is on (the
                            # default). They must NOT enter the synthetic-entity branch
                            # below - fall through to the binary downloader (its
                            # URL-refresh maps the negative ID back to the raw file ID).
                            if _debug_file:
                                log_debug(f"  Secondary [attachment → binary downloader]: {display_file_name}", _debug_file)
                        elif _file_id_val < 0:
                            # ── Secondary Content Entities (Assignment, Quiz, etc.) ──
                            _sec_entity_type = secondary_id_type(file.id)
                            if _debug_file:
                                log_debug(f"  Secondary [{_sec_entity_type}]: {display_file_name}", _debug_file)
                            if _sec_entity_type != 'attachment' and _sec_entity_type not in ('module_item', 'unknown'):
                                _sec_settings = _pair_sec_settings

                                # Mode A inline: derive the module subfolder from
                                # the analyzer's target_local_path so the entity
                                # writes to the right module folder. (In Mode B,
                                # _resolve_secondary_path always routes to the
                                # category folder, so module_path is ignored.)
                                _sec_module_path = None
                                if not _sec_settings.get('isolate_secondary_content', True):
                                    _calc_for_sec = getattr(file, '_target_local_path', '')
                                    _calc_dir = Path(_calc_for_sec).parent if _calc_for_sec else Path('.')
                                    if str(_calc_dir) not in ('.', ''):
                                        _sec_module_path = local_path / _calc_dir

                                # H-2: updates regenerate INTO the directory the
                                # user's copy lives in; redownloads restore into
                                # the previously recorded directory.
                                _sec_explicit_dir = None
                                _sec_old_path = None
                                if (is_update_clean or is_update_modified) and _upd_info is not None \
                                        and getattr(_upd_info, 'local_path', ''):
                                    _sec_old_path = local_path / Path(_upd_info.local_path)
                                    if path_exists(_sec_old_path.parent):
                                        _sec_explicit_dir = _sec_old_path.parent
                                elif is_redownload and _redl_info is not None \
                                        and getattr(_redl_info, 'local_path', ''):
                                    _redl_parent = (local_path / Path(_redl_info.local_path)).parent
                                    if str(_redl_parent) != '.' and path_exists(_redl_parent):
                                        _sec_explicit_dir = _redl_parent

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
                                            _sec_explicit_dir,
                                            is_update_modified,   # preserve_existing
                                        )
                                except Exception as _sec_err:
                                    # Re-raise preserving the original traceback
                                    raise

                                if sec_filepath:
                                    # H-1 clean update of a RENAMED entity file: the
                                    # regenerate wrote the canonical name into the
                                    # user's folder - remove the superseded (pristine)
                                    # old copy so exactly one current version remains.
                                    # Modified updates never delete (preserve edits).
                                    # _path_key, NOT normcase: normcase is the
                                    # IDENTITY off Windows, so on macOS (whose
                                    # default volume is case-INSENSITIVE) a
                                    # case-only Canvas rename - "week 1
                                    # assignment" -> "Week 1 Assignment", an
                                    # ordinary edit - made these two strings
                                    # differ while naming ONE file. The guard
                                    # then read "safe to remove the superseded
                                    # copy" and unlinked the file the regenerate
                                    # had just written, leaving the user with
                                    # NOTHING and a manifest row pointing at a
                                    # path that no longer exists. Reproduced
                                    # 2026-08-10; see _path_key's docstring.
                                    if (is_update_clean and _sec_old_path is not None
                                            and path_exists(_sec_old_path)
                                            and _path_key(_sec_old_path) != _path_key(sec_filepath)):
                                        try:
                                            Path(make_long_path(_sec_old_path)).unlink()
                                            if _debug_file:
                                                log_debug(f"  Superseded old copy removed: {_sec_old_path.name}", _debug_file)
                                        except OSError:
                                            pass

                                    rel_path = str(sec_filepath.relative_to(local_path)).replace('\\', '/')
                                    _register_synced_path(pair_idx, rel_path, sec_filepath.name)
                                    files_done += 1
                                    terminal_log.append(log_line('success', sec_filepath.name, icon=file_icon_svg(sec_filepath.name)))
                                    _paint_metrics()
                                    if _debug_file:
                                        log_debug(f"✓ Secondary: {sec_filepath.name}", _debug_file)

                                    # ── Inject attachments into the async download queue ──
                                    # Attachments have REAL positive Canvas file IDs, so they
                                    # bypass the `file.id < 0` branch and enter the standard
                                    # HTTP download path with full retry + cancellation support.
                                    if sec_attachments:
                                        from core.sync_manager import (
                                            CanvasFileInfo as _CFI,
                                            make_secondary_id as _make_sec_id,
                                        )
                                        attach_dir = sec_filepath.parent

                                        # Deduplication guard: prevent double-queueing if
                                        # the attachment was already in the sync selection
                                        # (e.g. both HTML + attachment were locally deleted)
                                        _queued_ids = {getattr(f, 'id', None) for f in all_files}

                                        _isolate_now = _sec_settings.get('isolate_secondary_content', True)
                                        _files_section = manifest.get('files', {})

                                        for att in sec_attachments:
                                            att_id = att.get('id')
                                            att_url = att.get('url', '')
                                            att_filename = att.get('filename', att.get('display_name', 'attachment'))

                                            if not att_url or not att_id:
                                                continue

                                            # H-2 (legacy fix): Look up BOTH the positive and
                                            # synthetic-negative manifest IDs. If the user toggled
                                            # isolate_secondary_content between syncs, the old entry
                                            # uses the opposite ID form and a single-form lookup would
                                            # always miss it, re-downloading forever.
                                            _pos_entry = _files_section.get(str(att_id))
                                            _neg_entry = _files_section.get(str(_make_sec_id('attachment', att_id)))
                                            _manifest_entry = _pos_entry or _neg_entry
                                            _manifest_att_id = (
                                                _make_sec_id('attachment', att_id) if _isolate_now else att_id
                                            )
                                            if _manifest_entry:
                                                _existing_path = local_path / _manifest_entry.get('local_path', '')
                                                if path_exists(_existing_path):
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
                                                name_locked=True,
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

                                    # Mirror the fresh manifest state in memory so the
                                    # finalize-phase save_manifest never clobbers the
                                    # DB row (written inside _save_secondary_entity)
                                    # with pre-sync values - THE historic source of
                                    # "keeps showing as updated" churn.
                                    if sync_mgr and sec_id:
                                        try:
                                            manifest.setdefault('files', {})[str(sec_id)] = {
                                                'canvas_file_id': sec_id,
                                                'canvas_filename': sec_filepath.name,
                                                'local_path': rel_path,
                                                'canvas_updated_at': canvas_updated or '',
                                                'downloaded_at': datetime.now().isoformat(),
                                                'original_size': 0,
                                                'is_ignored': False,
                                                'original_md5': _compute_md5(sec_filepath) or '',
                                                'content_sig': getattr(file, 'content_sig', '') or '',
                                            }
                                            res_data['manifest'] = manifest
                                        except Exception:
                                            pass
                                else:
                                    # L-7: Count unknown/failed secondary entities in the error
                                    # list so the completion screen shows a non-zero error count
                                    # rather than silently dropping them.
                                    files_done += 1
                                    terminal_log.append(log_line('skip', display_file_name, icon=file_icon_svg(display_file_name)))
                                    _paint_metrics()
                                    error_list.append(f"Skipped secondary entity: {display_file_name}")
                                    if _debug_file:
                                        log_debug(f"⚠ Skipped secondary: {display_file_name}", _debug_file)
                                continue

                            # ── Legacy Synthetic Module Items (Pages, External URLs) ──
                            Path(make_long_path(filepath.parent)).mkdir(parents=True, exist_ok=True)

                            is_url_ext = filepath.name.lower().endswith('.url') or filepath.name.lower().endswith('.webloc')
                            is_html_ext = filepath.name.lower().endswith('.html')

                            if is_html_ext:
                                # M-1: Pages regenerate with their REAL offline
                                # content (full HTML document, exactly like the
                                # download engine) instead of a redirect stub
                                # that needs a Canvas login. Slug comes from the
                                # analyzer stash, else parsed from the page URL.
                                _page_written = False
                                _slug = getattr(file, '_page_slug', '') or ''
                                if not _slug:
                                    _u = getattr(file, 'url', '') or ''
                                    if '/pages/' in _u:
                                        _slug = _u.rstrip('/').split('/pages/')[-1].split('?')[0]
                                if _slug:
                                    try:
                                        async with sem:
                                            _page_obj = await asyncio.to_thread(
                                                safe_thread_wrapper,
                                                res_data['course'].get_page, current_ctx, _slug)
                                        _page_html = cm._build_entity_html(
                                            getattr(_page_obj, 'title', display_file_name),
                                            getattr(_page_obj, 'body', '') or '',
                                        )
                                        _pg_part = filepath.parent / (filepath.name + '.part')
                                        async with aiofiles.open(str(make_long_path(_pg_part)), 'w', encoding='utf-8') as f:
                                            await f.write(_page_html)
                                        os.replace(make_long_path(_pg_part), make_long_path(filepath))
                                        _page_written = True
                                        if _debug_file:
                                            log_debug(f"✓ Page content regenerated: {filepath.name}", _debug_file)
                                    except Exception as _pg_err:
                                        if _debug_file:
                                            log_debug(f"  Page fetch failed ({_pg_err}); falling back to redirect stub", _debug_file)

                                if not _page_written:
                                    # H-1 guard: no URL at all → nothing to write
                                    if not getattr(file, 'url', ''):
                                        files_done += 1
                                        terminal_log.append(log_line('skip', display_file_name, icon=file_icon_svg(display_file_name), detail='no URL'))
                                        _paint_metrics()
                                        error_list.append(f"Skipped {display_file_name}: no URL for shortcut")
                                        continue
                                    html_content = f'<meta http-equiv="refresh" content="0; url={esc(file.url)}">'
                                    async with aiofiles.open(str(make_long_path(filepath)), 'w', encoding='utf-8') as f:
                                        await f.write(html_content)
                            elif is_url_ext:
                                # H-1 guard: an ExternalUrl item with a stale or empty
                                # URL would produce a broken shortcut - skip instead.
                                if not getattr(file, 'url', ''):
                                    files_done += 1
                                    terminal_log.append(log_line('skip', display_file_name, icon=file_icon_svg(display_file_name), detail='no URL'))
                                    _paint_metrics()
                                    error_list.append(f"Skipped {display_file_name}: no URL for shortcut")
                                    continue
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

                            if is_url_ext or is_html_ext:
                                rel_path = str(filepath.relative_to(local_path)).replace('\\', '/')
                                sync_mgr.add_file_to_manifest(manifest, file, rel_path)
                                _register_synced_path(pair_idx, rel_path, display_file_name)
                                files_done += 1
                                terminal_log.append(log_line('success', display_file_name, icon=file_icon_svg(display_file_name)))
                                _paint_metrics()
                                if _debug_file:
                                    _sc_type = "URL shortcut" if is_url_ext else "HTML page"
                                    log_debug(f"✓ Shortcut ({_sc_type}): {display_file_name}", _debug_file)
                                continue

                            continue # Ensure Legacy Synthetic block definitively skips binary downloader

                        # ── Binary download: dispatch as a concurrent task (H-3) ──
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

                        filepath = _claim_target(filepath)
                        pair_tasks.append(asyncio.create_task(_download_binary(
                            file, filepath, display_file_name,
                            is_update_clean, is_update_modified, is_redownload,
                        )))

                    except Exception as e:
                        failed_files_for_pair.append(file)
                        error_list.append(f"Error syncing {esc(display_file_name)}: {esc(str(e))}")
                        terminal_log.append(log_line('error', display_file_name, icon=file_icon_svg(display_file_name), detail=str(e)))
                        log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)
                        if _debug_file:
                            # Full traceback: this broad handler catches genuine
                            # code bugs, and str(e) alone doesn't say WHERE.
                            from core.canvas_debug import log_debug_exc
                            log_debug_exc(f"✗ Exception: {display_file_name}: {e}", _debug_file, exc=e)

                # H-3: wait for this pair's concurrent downloads to finish before
                # the retry-bucket build and before moving to the next pair.
                if pair_tasks:
                    _task_results = await asyncio.gather(*pair_tasks, return_exceptions=True)
                    for _tr in _task_results:
                        if isinstance(_tr, Exception):
                            # _download_binary handles its own errors; anything
                            # arriving here is an engine bug - log it loudly.
                            logger.error(f"Sync download task crashed: {_tr}", exc_info=_tr)
                            error_list.append(f"Sync engine task error: {_tr}")

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
            estimator.update(units_done=total_files, bytes_done=downloaded_mb * 1024 * 1024,
                             units_total=total_files, bytes_total=total_mb * 1024 * 1024)
            # Hand this connection's measured rates to whatever runs next.
            remember_transfer_priors(estimator)
            render_progress_bar(progress_container, total_files, total_files)
            metrics_dashboard.markdown(build_metrics_row(transfer_metrics(
                estimator, done_files=synced_counter[0], total_files=total_files,
                done_bytes=downloaded_mb * 1024 * 1024,
                total_bytes=total_mb * 1024 * 1024,
            )), unsafe_allow_html=True)
            active_file_placeholder.markdown(f"<p style='color: {theme.TEXT_SECONDARY}; font-size: 0.9rem; font-style: italic;'>Finalizing sync…</p>", unsafe_allow_html=True)
            log_container.markdown(render_terminal_html_compat(terminal_log), unsafe_allow_html=True)

            # CANCEL GUARD: Skip all post-download state mutations if cancelled.
            # Do NOT call st.rerun() here - this coroutine runs in a background
            # ThreadPoolExecutor thread. RerunException escaping the thread would
            # bypass the post-processing pipeline. Signal cancellation via early
            # return and let the script thread handle the rerun after .result().
            if is_sync_cancelled():
                st.session_state['download_status'] = 'sync_cancelled'
                return synced_details, retry_selections, list(terminal_log), dict(synced_actual_rels)

            for sel in sync_selections:
                res_data = sel['res_data']
                sync_mgr = res_data.get('sync_manager')
                manifest = res_data.get('manifest')
                if sync_mgr is None or manifest is None:
                    continue

                sync_mgr.save_manifest(manifest)

                # H-5: Force WAL checkpoint so all committed pages are merged
                # into the main DB file. Without this, a crash immediately after
                # a bulk sync leaves the manifest in the WAL rather than the DB.
                try:
                    import sqlite3 as _sqlite3
                    from contextlib import closing as _closing
                    from shared.helpers import make_long_path as _mlp
                    # closing() so the handle is released immediately (a handle
                    # lingering until GC transiently locks the .db on Windows);
                    # the inner `_ckpt_conn` CM keeps commit-on-exit semantics.
                    with _closing(_sqlite3.connect(_mlp(str(sync_mgr.db_path)), timeout=10.0)) as _ckpt_conn, _ckpt_conn:
                        _ckpt_conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                except Exception as _ckpt_err:
                    logger.warning(f"WAL checkpoint failed for {sync_mgr.db_path}: {_ckpt_err}")

        return synced_details, retry_selections, list(terminal_log), dict(synced_actual_rels)

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
                    (synced_details, retry_selections, _download_log_history,
                     _synced_actual_rels) = _future.result(timeout=0.5)
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
            'actual_rels': _synced_actual_rels,
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
        _synced_actual_rels = _cached_run.get('actual_rels', {})

    def _finalize_sync_records(*, cancelled: bool = False):
        """Build the per-course synced_groups + write THIS run's history entry.

        Called on the normal completion path AND from the cancel guards below:
        a cancelled run's already-synced files are on disk and in the folder
        manifests, so Sync History and the Today page's "Today's files" must
        list them (the Today page merges + de-dupes multiple quick entries of
        the same day, so a later run simply appends). On cancel the entry is
        flagged ``cancelled`` (history shows a Cancelled chip) and last_synced
        is NOT stamped - a partial run must not masquerade as a completed sync.
        Single-fire per run: the cancel guards st.rerun() immediately after
        calling this, so the normal-path call can never run in the same pass.
        """
        # Per-course breakdown with resolved file paths - powers the per-file
        # Open / Reveal actions on the completion screen and the landing-page
        # "New files since last sync" panel. Built after post-processing on the
        # normal path; on cancel it reflects everything synced so far.
        try:
            synced_groups = _build_synced_groups(sync_selections, synced_details,
                                                 _synced_actual_rels)
        except Exception as e:
            logger.warning(f"Failed to build synced file groups: {e}")
            synced_groups = []
        st.session_state['synced_groups'] = synced_groups

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        if not cancelled:
            # Update last_synced timestamps atomically (completed runs only).
            updates = []
            for sel in sync_selections:
                # Save securely to folder database
                try:
                    if 'res_data' in sel and 'sync_manager' in sel['res_data']:
                        sel['res_data']['sync_manager']._save_metadata('last_synced', now_str)
                except Exception as e:
                    logger.warning(f"Failed to save last_synced to db: {e}")

                # H-6: identify the pair by ITS OWN course_id + folder (carried in
                # res_data), never by indexing st.session_state['sync_pairs'] with
                # pair_idx - the indexes drift apart whenever analysis skipped a pair
                # (missing folder / analysis error), which used to stamp last_synced
                # onto the WRONG pair.
                _own_pair = sel.get('res_data', {}).get('pair', {})
                if _own_pair.get('local_folder'):
                    updates.append((_own_pair.get('course_id'), _own_pair.get('local_folder'), now_str))

            if updates:
                _update_last_synced_batch(updates)

        # Record sync history - also for all-failed runs (synced 0, errors > 0)
        # so the user can see in the Hub that a sync was attempted and failed.
        if synced_counter[0] > 0 or error_list:
            try:
                from shared.helpers import get_config_dir
                history_mgr = SyncHistoryManager(get_config_dir())

                import unicodedata as _ud_hist
                categorized_files = {'new': [], 'updated': [], 'restored': [], 'protected': []}
                synced_course_names = []
                # The pair IDENTITY of every course in the run, alongside the
                # Canvas name. Sync History renders a course the way the rest of
                # the app does - through the user's own name when they gave one -
                # and that name is keyed on (course_id, local_folder), which a
                # list of name STRINGS cannot supply. Recorded for every selected
                # pair, not just the ones that received files, so a run that
                # changed nothing is still resolvable.
                # course_name stays the CANVAS name here: this is the record of
                # what was synced, and shared.components._course_id_from_sync_pairs
                # still matches error rows against it.
                course_sigs = []

                for sel in sync_selections:
                    pair_idx = sel['pair_idx']
                    pair_files = synced_details.get(pair_idx, [])
                    _hp = sel.get('res_data', {}).get('pair', {}) or {}
                    course_sigs.append([
                        _hp.get('course_id'), _hp.get('local_folder', ''),
                        _hp.get('course_name', ''),
                        _hp.get('saved_id'),   # STABLE id -> name survives a later folder move
                    ])
                    if pair_files:
                        synced_course_names.append(sel['res_data']['pair']['course_name'])

                # Prefer the RESOLVED per-file records from _build_synced_groups:
                # they carry the on-disk (post-conversion) name AND the category,
                # already computed with the authoritative actual-path data - so the
                # history panel lists "Page X.md", not the pre-conversion "X.html".
                _group_files = [f for g in synced_groups for f in g.get('files', [])]
                if _group_files:
                    for _gf in _group_files:
                        categorized_files.setdefault(
                            _gf.get('category', 'new'), []).append(_gf.get('name', ''))
                    _synced_files_flat = [_gf.get('name', '') for _gf in _group_files]
                else:
                    # Group build failed (or produced nothing) - fall back to the
                    # display names with the same categorisation rules the groups
                    # would have applied.
                    _synced_files_flat = [
                        fname for pair_files in synced_details.values() for fname in pair_files
                    ]
                    for sel in sync_selections:
                        pair_idx = sel['pair_idx']
                        pair_files = synced_details.get(pair_idx, [])

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

                _entry = {
                    'timestamp': now_str,
                    'files_synced': synced_counter[0],
                    'courses': len(sync_selections),
                    'course_names': list(set(synced_course_names)),
                    'course_sigs': course_sigs,
                    'errors': len(error_list),
                    'error_details': error_list,
                    'synced_files': _synced_files_flat,
                    'categorized_files': categorized_files,
                    # Per-course breakdown (course + rel path + category) so the
                    # "New files since last sync" panel can group, sort, Open & Reveal.
                    'synced_groups': synced_groups,
                    # Record the RUN TYPE (quick vs review), not the sync-vs-download
                    # boolean 'sync_mode' session flag. The Sync History label AND the
                    # Today page's "today's files" filter both key off 'quick' here.
                    # (sync_quick_mode is still set at this point - analysis never pops
                    # it; see sync/analysis.py:908.)
                    'sync_mode': 'quick' if st.session_state.get('sync_quick_mode') else 'normal',
                }
                if cancelled:
                    # Honest labelling: the history card shows a Cancelled chip
                    # instead of "Success" for a partial, user-stopped run.
                    _entry['cancelled'] = True
                history_mgr.add_entry(_entry)
                # M-1: Invalidate the step-1 history cache so the next render
                # re-reads from disk and shows the entry we just wrote.
                st.session_state.pop('_sync_history_cache', None)
                if not cancelled:
                    # Remember this entry's timestamp so the terminal Panopto pass
                    # can amend THIS entry with the recordings it downloads
                    # afterwards (no pass follows a cancelled run).
                    st.session_state['_sync_history_ts'] = now_str
            except Exception as e:
                logger.error(f"Failed to record sync history: {e}")

    def _cancel_exit():
        """Route to the cancelled screen WITHOUT losing this run's results.

        Records history/groups first (files synced before the cancel are real
        and on disk), mirrors the counters the cancelled screen reads, then
        drops the worker snapshot and reruns into 'sync_cancelled'.
        """
        _finalize_sync_records(cancelled=True)
        st.session_state['synced_details'] = dict(synced_details)
        st.session_state['synced_count'] = synced_counter[0]
        st.session_state['synced_bytes'] = synced_counter[1]
        st.session_state['sync_errors'] = error_list
        st.session_state['sync_cancelled_file_count'] = synced_counter[0]
        st.session_state.pop('sync_worker_result', None)
        st.session_state['download_status'] = 'sync_cancelled'
        st.rerun()

    # Deferred cancel: checked here on the script thread so RerunException
    # never escapes the background coroutine and skips post-processing.
    # L-11: Pre-set status so the rerun doesn't re-enter 'syncing' for one pass.
    if is_sync_cancelled():
        _cancel_exit()

    # --- Shared post-processing helpers ---
    def get_synced_file_paths(target_exts, conversion_key=None):
        """Return list of (Path, sync_mgr, pair_idx) for THIS RUN's synced files
        matching target_exts. If conversion_key is provided, evaluates the
        pair's contract first.

        H-8: targets are resolved from the EXACT relative paths the download
        loop recorded for this run - never by globbing bare filenames across
        the whole course tree. The old rglob-by-name approach also picked up
        unrelated same-named files elsewhere in the folder (old copies, the
        user's own files) and converted-then-DELETED them.
        """
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
            for rel in _synced_actual_rels.get(pair_idx, []):
                rel_path = Path(rel)
                # Match on the primary suffix OR on the full compound suffix
                # (e.g. '.tar.gz') so .tar.gz is caught precisely without
                # accidentally matching standalone .gz files.
                all_suffixes = ''.join(rel_path.suffixes).lower()
                if rel_path.suffix.lower() in target_exts or all_suffixes in target_exts:
                    m = sm.local_path / rel_path
                    # os.path.isfile(make_long_path(...)), NOT Path.is_file():
                    # past Windows' limit is_file() answers False rather than
                    # raising, so every file in a deep course folder dropped out
                    # of the conversion list SILENTLY - the sync-side twin of the
                    # download ledger bug measured on 2026-08-22 (1 of 124 files
                    # survived the equivalent check there).
                    if (os.path.isfile(make_long_path(m))
                            and not m.name.startswith('._')
                            and "__MACOSX" not in m.parts):
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
        _cancel_exit()

    # ==========================================
    # POST-PROCESSING PIPELINE (Shared Module)
    # ==========================================
    from converters.post_processing import (
        UIBridge, run_archive_extraction, run_pptx_conversion,
        run_html_conversion, run_code_conversion, run_url_compilation,
        run_word_conversion, run_excel_data_conversion, run_excel_conversion,
        run_video_conversion, retry_failed_conversions,
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

    # Every (runner, items) pair that ran, so ONE retry pass at the end can cover
    # all of them - the same contract as run_all_conversions in the download
    # flow, which is where this pattern came from.
    #
    # MUST be declared here. The retry pass was copied into this function
    # WITHOUT this line (commit 4b98b2e), so the first `_attempts.append` below
    # raised NameError on every sync that reached post-processing - i.e. every
    # sync that transferred a single file, on every contract shape. It is
    # unconditional here, unlike the download flow which guards each append
    # behind `if <files>:`, so nothing narrowed the blast radius. The whole
    # test suite passes with it missing; only a real sync reaches this line.
    _attempts: list = []

    # Archive Extraction
    #
    # A zip is UNPACKED, and its contents are then left exactly as they are.
    # Nothing inside an archive is ever converted - by design, decided
    # 2026-07-29, and the same rule holds in the download flow.
    #
    # This reverses an earlier change that widened conversion scope to include
    # extracted trees. That widening was correct about the symptom and wrong
    # about the cure: an archive is an opaque payload the teacher uploaded, and
    # unpacking it is a convenience, not an invitation to rewrite what is
    # inside. Measured on one real lecture zip from course 45899 - a JavaScript
    # project with node_modules - it meant 21,824 extracted files, 11,818 of
    # which a converter would rewrite, 9,730 of those landing on paths past
    # Windows' 260-character limit. Office conversion cannot reach those at all:
    # COM rejects a long path AND rejects the \?\ prefix (measured), so there
    # is no depth at which that half could ever have worked.
    #
    # The user's own files inside the archive also stop being their own files
    # the moment a converter deletes a .js to leave a .txt behind.
    run_archive_extraction(
        get_synced_file_paths({'.zip', '.tar', '.tar.gz'}, 'persistent_convert_zip'), pp_ui
    )

    def _from_archives(target_exts, conversion_key=None):
        """This run's synced files. The CONTENTS of an archive are never
        converted - see the note above ``run_archive_extraction``.

        The name is kept because every converter below calls it and the shape of
        the call is what guarantees download and sync agree; what changed is the
        answer, in both flows at once.
        """
        return list(get_synced_file_paths(target_exts, conversion_key))

    _items = _from_archives({'.ppt', '.pptx', '.pptm', '.pot', '.potx'}, 'persistent_convert_pptx')
    run_pptx_conversion(_items, pp_ui)
    _attempts.append((run_pptx_conversion, _items))

    # HTML -> Markdown
    _items = _from_archives({'.html'}, 'persistent_convert_html')
    run_html_conversion(_items, pp_ui)
    _attempts.append((run_html_conversion, _items))

    # Code -> TXT
    from converters.code import CODE_EXTENSIONS
    _items = _from_archives(CODE_EXTENSIONS, 'persistent_convert_code')
    run_code_conversion(_items, pp_ui)
    _attempts.append((run_code_conversion, _items))

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
            if _sm and path_exists(_sm.local_path) and _sm.local_path not in _processed_roots:
                _processed_roots.add(_sm.local_path)
                _url_folders.append((_sm.local_path, _sm.course_name))
    run_url_compilation(_url_folders, pp_ui)

    # Legacy Word -> PDF
    _items = _from_archives({'.doc', '.rtf', '.odt'}, 'persistent_convert_word')
    run_word_conversion(_items, pp_ui)
    _attempts.append((run_word_conversion, _items))

    # Excel → AI Data + PDF (single toggle, dual pipeline)
    # CRITICAL ORDERING: Data extraction FIRST (reads .xlsx), PDF SECOND (deletes .xlsx).
    # .xls (Excel 97-2003) is a binary format openpyxl cannot read - exclude it
    # from data extraction (mirrors run_all_conversions in the download flow).
    # ExcelToPDF via COM/AppleScript handles .xls fine in the PDF step below.
    run_excel_data_conversion(
        _from_archives({'.xlsx', '.xlsm'}, 'persistent_convert_excel'), pp_ui
    )

    # Excel → PDF
    _items = _from_archives({'.xlsx', '.xls', '.xlsm'}, 'persistent_convert_excel')
    run_excel_conversion(_items, pp_ui)
    _attempts.append((run_excel_conversion, _items))

    # Video -> MP3
    _items = _from_archives({'.mp4', '.mov', '.mkv', '.avi', '.m4v'}, 'persistent_convert_video')
    run_video_conversion(_items, pp_ui)
    _attempts.append((run_video_conversion, _items))

    # One retry pass, then a precise reason for whatever failed twice.
    retry_failed_conversions(_attempts, pp_ui)

    # --- Inject post-processing sidecars into sync UI ledger ---
    _sidecar_paths = pp_ui.generated_sidecar_paths
    if _sidecar_paths:
        # Build reverse lookup: resolved local_path -> pair_idx
        _pair_lookup = {}
        for sel in sync_selections:
            _sm = sel.get('res_data', {}).get('sync_manager')
            if _sm and path_exists(_sm.local_path):
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
    st.session_state['pp_archives_skipped'] = list(pp_ui.archives_skipped)
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

    # Build synced_groups + record history (moved into _finalize_sync_records
    # so the cancel guards above can record partial runs too). A cancel set
    # DURING post-processing lands here with the event already set - the
    # conversion runners stop gracefully - so pass the live cancel state:
    # the entry is then flagged cancelled and last_synced stays unstamped.
    _finalize_sync_records(cancelled=is_sync_cancelled())

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
