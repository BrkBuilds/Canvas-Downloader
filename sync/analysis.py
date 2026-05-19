"""
sync.analysis - Analysis phase logic for sync flow.

Extracted from ``sync_ui.py`` L2682-2941 (Phase 4).
Strict physical move - NO logic changes.

Fix 1 (2026-04): Eliminated duplicate module scan by threading the
    module_map from get_course_files_metadata → analyze_course.
Fix 2 (2026-04): Offloaded blocking Canvas API calls to a background
    thread via asyncio.to_thread + safe_thread_wrapper to improve
    UI responsiveness during the analysis phase.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
from pathlib import Path

import streamlit as st

import theme
from canvas_logic import CanvasManager, safe_thread_wrapper
from core.state_registry import NOTEBOOK_SUB_KEYS
from sync_manager import SyncManager
from ui_helpers import render_sync_wizard, friendly_course_name, esc
from engine.notifications import play_completion_beep

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fix 2: Background-thread helper for per-course analysis
# ---------------------------------------------------------------------------

def _analyze_course_blocking(cm, course_id, course_name, local_folder,
                             progress_hook):
    """Execute all blocking Canvas API calls for a single course.

    This function is designed to be called via ``asyncio.to_thread()`` with
    ``safe_thread_wrapper`` so that Streamlit's ScriptRunContext is preserved
    on the background thread (required for ``st.session_state`` reads inside
    the progress hook and for ``st.markdown`` UI pushes).

    Returns:
        Tuple of (course, sync_mgr, manifest, canvas_files, result, detected)
        - all data needed by the caller, with no side effects.
    """
    progress_hook(0, 1, "Connecting to Canvas API...")
    course = cm.canvas.get_course(course_id)

    sync_mgr = SyncManager(str(local_folder), course_id, course_name)

    progress_hook(0, 1, "Loading local sync manifest...")
    manifest = sync_mgr.load_manifest()

    # Load secondary content contract so analysis includes negative-ID entities
    _raw_secondary = sync_mgr._load_metadata('secondary_content_contract')
    if _raw_secondary is not None:
        try:
            _raw_secondary = json.loads(_raw_secondary)
        except (json.JSONDecodeError, TypeError, ValueError) as _sec_err:
            # Truncated or corrupt stored JSON — log a warning and fall through
            # to the session-state fallback so the user's current settings are used.
            logger.warning(
                f"Secondary content contract for course {course_id} is corrupt "
                f"({_sec_err}); falling back to current session settings."
            )
            _raw_secondary = None
    if _raw_secondary is None:
        # First-ever analysis for this pair — no DB contract yet.
        # Fall back to session state so the user's current settings are honoured.
        _raw_secondary = {
            'download_assignments':   st.session_state.get('persistent_dl_assignments', False),
            'download_syllabus':      st.session_state.get('persistent_dl_syllabus', False),
            'download_announcements': st.session_state.get('persistent_dl_announcements', False),
            'download_discussions':   st.session_state.get('persistent_dl_discussions', False),
            'download_quizzes':       st.session_state.get('persistent_dl_quizzes', False),
            'download_rubrics':       st.session_state.get('persistent_dl_rubrics', False),
            'download_submissions':   st.session_state.get('persistent_dl_submissions', False),
            'isolate_secondary_content': st.session_state.get('persistent_dl_isolate_secondary', True),
        }
    _secondary_settings = _raw_secondary  # may still be empty dict — that's fine

    progress_hook(0, 1, "Fetching files from Canvas...")
    canvas_files, sec_fetch_status, module_map = cm.get_course_files_metadata(
        course,
        progress_callback=progress_hook,
        secondary_content_settings=_secondary_settings,
    )

    progress_hook(1, 1, "Healing local sync manifest...")
    manifest = sync_mgr.heal_manifest(manifest)

    progress_hook(1, 1, "Comparing files...")
    detected = sync_mgr.detect_structure()
    # Pass the pre-built module_map so analyze_course skips the redundant
    # Canvas API fetch for module structure (Fix 1).
    result = sync_mgr.analyze_course(
        canvas_files, manifest, cm=cm,
        download_mode=detected,
        secondary_fetch_success=sec_fetch_status,
        module_map=module_map,
    )

    return course, sync_mgr, manifest, canvas_files, result, detected


def run_analysis(sync_pairs, main_placeholder=None):
    """Execute the analysis phase: compare local vs Canvas for each pair.

    This is a strict physical move of the original ``_run_analysis`` from
    ``sync_ui.py``.  No logic has been changed.
    """
    # Step wizard
    render_sync_wizard(st, 2)

    # Check if only syncing a single pair
    single_idx = st.session_state.get('sync_single_pair_idx')
    if single_idx is not None:
        sync_pairs = [sync_pairs[single_idx]]

    cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
    all_results = []
    total_pairs = len(sync_pairs)

    # ── Course-identity guard ──────────────────────────────────────────
    # Each folder's .canvas_sync.db is bound to the first course it was
    # synced against. If the pair's course_id no longer matches that
    # binding (e.g. user re-pointed the pair at a different course, or
    # picked the wrong folder), running analysis would treat the entire
    # bound course's manifest as "Deleted on Canvas" - terrifying and
    # wrong. Detect and route to a confirmation screen instead.
    mismatched = []
    for pair_idx, pair in enumerate(sync_pairs):
        try:
            local_folder = pair.get('local_folder')
            requested_id = pair.get('course_id')
            if not local_folder or not Path(local_folder).exists():
                continue  # downstream loop handles missing folder
            bound_id = SyncManager.peek_bound_course_id(local_folder)
            if bound_id is not None and bound_id != requested_id:
                bound_name = SyncManager.peek_bound_course_name(local_folder) or f"course #{bound_id}"
                mismatched.append({
                    'pair_idx': pair_idx,
                    'pair': pair,
                    'bound_course_id': bound_id,
                    'bound_course_name': bound_name,
                    'requested_course_id': requested_id,
                    'requested_course_name': pair.get('course_name', f"course #{requested_id}"),
                })
        except Exception as e:
            logger.warning(f"Course-binding peek failed for {pair.get('local_folder')}: {e}")
            continue

    if mismatched:
        # Route back to step 1 and open the inline editor on the first
        # mismatched pair so the user sees the binding-notice in context
        # and can fix the course/folder before syncing.
        first = mismatched[0]
        first_pair = first['pair']
        # Find the real index in the full (un-filtered) sync_pairs list
        full_pairs = st.session_state.get('sync_pairs', [])
        real_idx = next(
            (i for i, p in enumerate(full_pairs)
             if p.get('course_id') == first_pair.get('course_id')
             and p.get('local_folder') == first_pair.get('local_folder')),
            None,
        )
        if real_idx is not None:
            st.session_state['editing_pair_idx'] = real_idx
            st.session_state['pending_sync_folder'] = first_pair.get('local_folder', '')
            st.session_state['sync_selected_course_id'] = first_pair.get('course_id')
        st.session_state['download_status'] = ''
        st.session_state['step'] = 1
        st.session_state.pop('analysis_pass', None)
        st.rerun()

    # Completely wipe the Step 1 / Main UI container before blocking on analysis
    if main_placeholder:
        main_placeholder.empty()

    # Clean progress display - no stale cards
    analysis_ui_placeholder = st.empty()
    
    # RENDER GLOBAL CANCEL ABOVE THE ANALYSIS LOOP
    cancel_analysis_placeholder = st.empty()
    if cancel_analysis_placeholder.button('Cancel Sync', type="secondary", key="cancel_analysis_btn"):
        cancel_analysis_placeholder.empty()
        st.session_state['cancel_requested'] = True
        st.session_state['download_status'] = 'sync_cancelled'
        st.rerun()

    for pair_num, pair in enumerate(sync_pairs, 1):
        # CHECK FOR CANCEL INSIDE THE LOOP
        if st.session_state.get('cancel_requested', False):
            break
            
        # Folder-not-found guard
        if not Path(pair['local_folder']).exists():
            st.error(f"❌ Folder not found: {pair['local_folder']}. It may have been deleted, renamed, or the drive is disconnected.")
            continue

        display_name = friendly_course_name(pair['course_name'])
        
        # Default-argument capture binds pair_num and display_name to the
        # current iteration's values, preventing late-binding over loop variables.
        def sync_progress_hook(current, total, status_text,
                               _pair_num=pair_num, _display_name=display_name):
            try:
                if st.session_state.get('cancel_requested') or st.session_state.get('sync_cancelled'):
                    return
                percent = int((current / total) * 100) if total > 0 else 0
                analysis_ui_placeholder.markdown(f"""
                <div style="background-color: {theme.BG_DARK}; padding: 20px; border-radius: 8px; border: 1px solid {theme.BG_CARD}; margin-top: 20px; margin-bottom: 20px;">
                    <h4 style="color: {theme.TEXT_PRIMARY}; margin-top: 0;">🔍 Analyzing Course Data...</h4>
                    <p style="color: {theme.TEXT_SECONDARY}; font-size: 0.9rem;">Course {_pair_num} of {total_pairs}: <b>{esc(_display_name)}</b></p>
                    <p style="color: {theme.ACCENT_BLUE}; font-size: 0.8rem; margin-bottom: 5px;">{status_text}</p>
                    <div style="background-color: {theme.BG_CARD}; border-radius: 4px; width: 100%; height: 8px; overflow: hidden;">
                        <div style="background-color: {theme.ACCENT_BLUE}; width: {percent}%; height: 100%; transition: width 0.1s ease;"></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                time.sleep(0.05)
            except Exception:
                pass

        local_folder = pair['local_folder']
        course_id = pair['course_id']
        course_name = pair['course_name']

        try:
            # --- Fix 2: Offload blocking API work to a background thread ---
            # Capture script context on the script thread, then run asyncio in
            # a dedicated worker thread so asyncio.run() never conflicts with
            # Tornado's already-running event loop (would raise RuntimeError).
            from streamlit.runtime.scriptrunner import get_script_run_ctx, add_script_run_ctx as _add_ctx
            _current_ctx = get_script_run_ctx()

            async def _run_course_analysis():
                import threading as _th
                _add_ctx(_th.current_thread(), _current_ctx)
                return await asyncio.to_thread(
                    safe_thread_wrapper,
                    _analyze_course_blocking,
                    _current_ctx,
                    cm, course_id, course_name, local_folder,
                    sync_progress_hook,
                )

            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
                course, sync_mgr, manifest, canvas_files, result, detected = (
                    _pool.submit(asyncio.run, _run_course_analysis()).result()
                )

            # Do NOT save manifest here! Fixes Verify-Then-Commit state leakage if user hits Back.
            
            all_results.append({
                'pair': pair,
                'result': result,
                'manifest': manifest,
                'sync_manager': sync_mgr,
                'canvas_files': canvas_files,
                'course': course,
                'detected_structure': detected,
            })
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Sync Analysis Error: {str(e)}")
            st.error(f"Error accessing course {display_name}: {e}")
            continue

    # Clean up the UI when all courses are done analyzing
    analysis_ui_placeholder.empty()
    
    st.session_state['sync_analysis_results'] = all_results

    # Reset locally-deleted checkbox state so they always start deselected in the review.
    for k in list(st.session_state.keys()):
        if k.startswith('sync_locdel_'):
            del st.session_state[k]

    # Quick Sync mode - skip review and go straight to sync
    if st.session_state.get('sync_quick_mode'):
        
        def apply_file_filter(file_list, filter_mode, is_tuple=False):
            if filter_mode == 'all':
                return file_list
            elif filter_mode == 'study':
                allowed_exts = {'.pdf', '.ppt', '.pptx', '.pptm', '.pot', '.potx'}
                filtered = []
                for item in file_list:
                    # updated_files is a list of tuples: (canvas_file, local_file)
                    f = item[0] if is_tuple else item
                    
                    if hasattr(f, 'canvas_filename'):
                        fname = f.canvas_filename
                    elif hasattr(f, 'filename'):
                        fname = getattr(f, 'display_name', '') or getattr(f, 'filename', '')
                    else:
                        fname = getattr(f, 'display_name', '')
                        
                    if Path(fname).suffix.lower() in allowed_exts:
                        filtered.append(item)
                return filtered
            return file_list

        # Auto-select all new, updated, locally deleted, and missing files
        sync_selections = []
        for idx, res_data in enumerate(all_results):
            result = res_data['result']
            cid = res_data['pair']['course_id']
            
            # --- Load Sync Contract from DB for post-processing settings ---
            # Extract contract for *this specific course*
            _contract = {}
            try:
                _sm = res_data['sync_manager']
                _raw = _sm._load_metadata('sync_contract')
                if _raw:
                    _contract = json.loads(_raw)
            except Exception:
                pass  # Fall back to session_state defaults
            
            # Store contract in res_data so the sync backend can apply per-course post-processing
            res_data['contract'] = _contract
                
            current_filter = _contract.get('file_filter', 'all')

            # Apply the gatekeeper BEFORE execution
            actionable_new = apply_file_filter(result.new_files, current_filter, is_tuple=False)
            # Quick Sync processes CLEAN updates only. Modified updates stay
            # behind for the full Review flow so students can't accidentally
            # clutter their folder with `_NewVersion` siblings of files they
            # edited. (Confirmed by the user's design choice.)
            actionable_updated_clean = apply_file_filter(result.updated_clean_files, current_filter, is_tuple=True)
            actionable_del = apply_file_filter(result.locally_deleted_files, current_filter, is_tuple=False)

            # Set session state keys for UI consistency (if user goes Back)
            for f in actionable_new:
                st.session_state[f'sync_new_{cid}_{f.id}'] = True
            for f, _ in actionable_updated_clean:
                st.session_state[f'sync_upd_{cid}_{f.id}'] = True
            # Modified updates are explicitly left UNCHECKED so the Review UI
            # renders them with their default-off state.
            for f, _ in result.updated_modified_files:
                st.session_state.setdefault(f'sync_updmod_{cid}_{f.id}', False)
            for si in actionable_del:
                st.session_state[f'sync_locdel_{cid}_{si.canvas_file_id}'] = True

            clean_updates = [f for f, _ in actionable_updated_clean]
            sync_selections.append({
                'pair_idx': idx,
                'res_data': res_data,
                'new': list(actionable_new),
                'updates': clean_updates,
                'updates_clean': clean_updates,
                'updates_modified': [],
                'redownload': [],
                'ignore': [],
            })
            
        total_count = sum(len(s['new']) + len(s['updates']) + len(s['redownload']) for s in sync_selections)
        
        # 1. Tally skipped files globally using a bulletproof net
        total_locdel = 0
        total_canvasdel = 0
        total_edited = 0

        for pair_res in all_results:
            if not isinstance(pair_res, dict):
                continue

            res_obj = pair_res.get('result')
            if res_obj is None:
                continue

            # all_results always contains AnalysisResult objects (never plain dicts)
            if hasattr(res_obj, 'locally_deleted_files') and res_obj.locally_deleted_files is not None:
                total_locdel += len(res_obj.locally_deleted_files)
            if hasattr(res_obj, 'deleted_on_canvas') and res_obj.deleted_on_canvas is not None:
                total_canvasdel += len(res_obj.deleted_on_canvas)
            if hasattr(res_obj, 'updated_modified_files') and res_obj.updated_modified_files is not None:
                total_edited += len(res_obj.updated_modified_files)

        st.session_state['qs_skipped'] = {
            'local_del': total_locdel,
            'canvas_del': total_canvasdel,
            'edited': total_edited,
        }
        logger.debug(f"Quick Sync Skipped Payload: {st.session_state['qs_skipped']}")
        
        if total_count == 0:
            # 2. Bypass directly to completion
            st.session_state['synced_count'] = 0
            st.session_state['download_status'] = 'sync_complete'
            st.session_state.pop('sync_quick_mode', None)
            
            # 3. Force rerun to instantly show the success screen
            st.rerun()
        else:
            logger.debug(f"Quick Sync total_count={total_count} → jumping to 'pre_sync'")
            st.session_state['sync_selections'] = sync_selections
            st.session_state['download_status'] = 'pre_sync'
            st.session_state['qs_cancel_route'] = True # INDESTRUCTIBLE CANCEL FLAG
            
            # Inject "Start Sync" variables so Step 3 starts executing immediately
            for _k in NOTEBOOK_SUB_KEYS:
                st.session_state[f'persistent_{_k}'] = st.session_state.get(_k, False)

            # Do NOT pop `sync_quick_mode` here so the cancel routing knows we are in Quick Sync!
            st.rerun()
    else:
        # Tally files for sync review notification
        total_new = 0
        total_updated_clean = 0
        total_updated_modified = 0
        total_local_del = 0

        for res_data in all_results:
            result = res_data.get('result')
            if result:
                total_new += len(getattr(result, 'new_files', []) or [])
                total_updated_clean += len(getattr(result, 'updated_clean_files', []) or [])
                total_updated_modified += len(getattr(result, 'updated_modified_files', []) or [])
                total_local_del += len(getattr(result, 'locally_deleted_files', []) or [])

        total_updated = total_updated_clean + total_updated_modified
        total_changes = total_new + total_updated + total_local_del

        if total_changes == 0:
            # Nothing to review - skip review step, go straight to completion
            st.session_state['synced_count'] = 0
            st.session_state['download_status'] = 'sync_complete'
            # Pre-arm the flag so show_sync_complete doesn't fire a second notification
            st.session_state['completion_beep_fired'] = True
            play_completion_beep(mode='sync_uptodate', summary='All files are up to date - nothing to download.')
            st.rerun()

        parts = []
        if total_new > 0:
            parts.append(f"{total_new} new file{'s' if total_new != 1 else ''}")
        if total_updated > 0:
            parts.append(f"{total_updated} update{'s' if total_updated != 1 else ''}")
        if total_updated_modified > 0:
            parts.append(f"{total_updated_modified} edited locally")
        if total_local_del > 0:
            parts.append(f"{total_local_del} file{'s' if total_local_del != 1 else ''} deleted locally")

        summary = ", ".join(parts) + " found."
        play_completion_beep(mode='sync_review', summary=summary.strip())
        st.session_state['download_status'] = 'analyzed'
