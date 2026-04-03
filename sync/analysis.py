"""
sync.analysis — Analysis phase logic for sync flow.

Extracted from ``sync_ui.py`` L2682-2941 (Phase 4).
Strict physical move — NO logic changes.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from pathlib import Path

import streamlit as st

import theme
from canvas_logic import CanvasManager
from sync_manager import SyncManager
from ui_helpers import render_sync_wizard, friendly_course_name

logger = logging.getLogger(__name__)


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

    # Completely wipe the Step 1 / Main UI container before blocking on analysis
    if main_placeholder:
        main_placeholder.empty()

    # Clean progress display — no stale cards
    analysis_ui_placeholder = st.empty()
    
    # RENDER GLOBAL CANCEL ABOVE THE ANALYSIS LOOP
    cancel_analysis_placeholder = st.empty()
    if cancel_analysis_placeholder.button('Cancel Download', type="secondary", key="cancel_analysis_btn"):
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
        
        # Define the granular hook for this specific course
        def sync_progress_hook(current, total, status_text):
            try:
                if st.session_state.get('cancel_requested') or st.session_state.get('sync_cancelled'):
                    return
                percent = int((current / total) * 100) if total > 0 else 0
                analysis_ui_placeholder.markdown(f"""
                <div style="background-color: {theme.BG_DARK}; padding: 20px; border-radius: 8px; border: 1px solid {theme.BG_CARD}; margin-top: 20px; margin-bottom: 20px;">
                    <h4 style="color: {theme.TEXT_PRIMARY}; margin-top: 0;">🔍 Analyzing Course Data...</h4>
                    <p style="color: {theme.TEXT_SECONDARY}; font-size: 0.9rem;">Course {pair_num} of {total_pairs}: <b>{display_name}</b></p>
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
            sync_progress_hook(0, 1, "Connecting to Canvas API...")
            course = cm.canvas.get_course(course_id)

            sync_mgr = SyncManager(str(local_folder), course_id, course_name)

            sync_progress_hook(0, 1, "Loading local sync manifest...")
            manifest = sync_mgr.load_manifest()

            # Load secondary content contract so analysis includes negative-ID entities
            _raw_secondary = sync_mgr._load_metadata('secondary_content_contract')
            _secondary_settings = json.loads(_raw_secondary) if _raw_secondary else None

            sync_progress_hook(0, 1, "Fetching files from Canvas...")
            canvas_files, sec_fetch_status = cm.get_course_files_metadata(
                course,
                progress_callback=sync_progress_hook,
                secondary_content_settings=_secondary_settings,
            )
            
            sync_progress_hook(1, 1, "Healing local sync manifest...")
            manifest = sync_mgr.heal_manifest(manifest)
            
            sync_progress_hook(1, 1, "Comparing files...")
            detected = sync_mgr.detect_structure()
            # Pass canvas manager and secondary fetch status to analyze_course for backend structure pre-calculation
            result = sync_mgr.analyze_course(
                canvas_files, manifest, cm=cm,
                download_mode=detected,
                secondary_fetch_success=sec_fetch_status
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

    # Quick Sync mode — skip review and go straight to sync
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
            actionable_missing = apply_file_filter(result.missing_files, current_filter, is_tuple=False)
            actionable_updated = apply_file_filter(result.updated_files, current_filter, is_tuple=True)
            actionable_del = apply_file_filter(result.locally_deleted_files, current_filter, is_tuple=False)
            
            # Set session state keys for UI consistency (if user goes back)
            # Use cid (course_id) to match the normal Review flow's key pattern
            for f in actionable_new:
                st.session_state[f'sync_new_{cid}_{f.id}'] = True
            for f, _ in actionable_updated:
                st.session_state[f'sync_upd_{cid}_{f.id}'] = True
            for mf in actionable_missing:
                st.session_state[f'sync_miss_{cid}_{mf.canvas_file_id}'] = True
            for si in actionable_del:
                st.session_state[f'sync_locdel_{cid}_{si.canvas_file_id}'] = True
            
            # Combine missing + locally deleted into 'redownload', mirroring the normal
            # Review flow at lines 2299-2304 (selected_miss.extend(selected_locdel))
            # FIX: Quick Sync explicitly only takes true missing files!
            true_missing = list(actionable_missing)
            
            sync_selections.append({
                'pair_idx': idx,
                'res_data': res_data,
                'new': list(actionable_new),
                # Note: updated_files is list of tuples (canvas_file, local_file)
                'updates': [f for f, _ in actionable_updated],
                'redownload': true_missing,
                'ignore': [],
            })
            
        total_count = sum(len(s['new']) + len(s['updates']) + len(s['redownload']) for s in sync_selections)
        
        # 1. Tally skipped files globally using a bulletproof net
        total_locdel = 0
        total_canvasdel = 0
        
        for pair_res in all_results:
            if not isinstance(pair_res, dict):
                continue
                
            # A. Check root level dictionary keys first (fallback from Step 2 logic)
            if 'locdel' in pair_res:
                total_locdel += len(pair_res['locdel'])
            if 'canvasdel' in pair_res: # Adjust if your root key is different
                total_canvasdel += len(pair_res['canvasdel'])
            
            # B. Check the 'result' object/dict
            res_obj = pair_res.get('result')
            if res_obj:
                # If it's an object with attributes:
                if hasattr(res_obj, 'locally_deleted_files') and res_obj.locally_deleted_files is not None:
                    total_locdel += len(res_obj.locally_deleted_files)
                if hasattr(res_obj, 'deleted_on_canvas') and res_obj.deleted_on_canvas is not None:
                    total_canvasdel += len(res_obj.deleted_on_canvas)
                
                # If it's a dictionary:
                if isinstance(res_obj, dict):
                    if 'locally_deleted_files' in res_obj and res_obj['locally_deleted_files'] is not None:
                        total_locdel += len(res_obj['locally_deleted_files'])
                    if 'deleted_on_canvas' in res_obj and res_obj['deleted_on_canvas'] is not None:
                        total_canvasdel += len(res_obj['deleted_on_canvas'])
                        
        st.session_state['qs_skipped'] = {'local_del': total_locdel, 'canvas_del': total_canvasdel}
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
            st.session_state['persistent_convert_zip'] = st.session_state.get('convert_zip', False)
            st.session_state['persistent_convert_pptx'] = st.session_state.get('convert_pptx', False)
            st.session_state['persistent_convert_html'] = st.session_state.get('convert_html', False)
            st.session_state['persistent_convert_code'] = st.session_state.get('convert_code', False)
            st.session_state['persistent_convert_urls'] = st.session_state.get('convert_urls', False)
            st.session_state['persistent_convert_word'] = st.session_state.get('convert_word', False)
            st.session_state['persistent_convert_video'] = st.session_state.get('convert_video', False)
            st.session_state['persistent_convert_excel'] = st.session_state.get('convert_excel', False)

            # Do NOT pop `sync_quick_mode` here so the cancel routing knows we are in Quick Sync!
            st.rerun()
    else:
        st.session_state['download_status'] = 'analyzed'
