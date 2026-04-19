"""
ui.sync_review — Analysis review screen (Step 2 of sync flow).

Extracted from ``sync_ui.py`` (Phase 5).
Strict physical move — NO logic changes.

Contains:
  - ``show_analysis_review()`` — full review screen with per-course cards,
    file selection, sync confirmation trigger
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote_plus

import streamlit as st

import theme
from sync_manager import get_file_icon
from ui_helpers import (
    render_sync_wizard,
    friendly_course_name,
    format_file_size,
    short_path,
    check_disk_space,
    get_base64_image,
)
from core.state_registry import cleanup_sync_state


# Lazy imports to avoid circular dependency with sync_ui.py
def _get_filetype_selector(all_files, prefix, file_key_fn):
    from ui.sync_dialogs import render_filetype_selector
    return render_filetype_selector(all_files, prefix, file_key_fn)

def _ignored_files_dialog(ignored_by_course):
    """Lazy import wrapper to call the dialog in ui.sync_dialogs."""
    from ui.sync_dialogs import ignored_files_dialog_inner
    ignored_files_dialog_inner(ignored_by_course)



def _render_hub_config(pair):
    from ui.hub_dialog import render_hub_config
    render_hub_config(pair)

# ---- Analysis review ----

def show_analysis_review(on_confirm_sync):
    # Step wizard
    render_sync_wizard(st, 2)

    st.markdown("<h2 style='margin-bottom: 12px; margin-top: -5px;'>Review Changes</h2>", unsafe_allow_html=True)

    from sync_manager import SyncFileInfo, SyncManager

    def handle_ignore(pair_idx, canvas_file_id, source_list_name, item):
        pair_data = st.session_state['sync_analysis_results'][pair_idx]
        sm = SyncManager(pair_data['pair']['local_folder'], pair_data['pair']['course_id'], pair_data['pair']['course_name'])
        # Extract filename for UPSERT (works for new files not yet in DB)
        if isinstance(item, tuple):
            fname = item[0].display_name or item[0].filename if hasattr(item[0], 'filename') else ''
        elif hasattr(item, 'canvas_filename'):
            fname = item.canvas_filename
        elif hasattr(item, 'filename'):
            fname = item.display_name or item.filename
        else:
            fname = ''
        sm.ignore_file(canvas_file_id, fname)
        
        # 1. Safely remove from origin list
        source_list = getattr(pair_data['result'], source_list_name)
        def get_id(x):
            if isinstance(x, tuple): return x[0].id
            elif hasattr(x, 'canvas_file_id'): return x.canvas_file_id
            return x.id
            
        setattr(pair_data['result'], source_list_name, [x for x in source_list if get_id(x) != canvas_file_id])

        if isinstance(item, tuple):
            sync_info = item[1]
        elif hasattr(item, 'canvas_file_id'):
            sync_info = item
        else:
            sync_info = SyncFileInfo(
                canvas_file_id=item.id,
                canvas_filename=item.display_name or item.filename,
                local_path="", canvas_updated_at="", downloaded_at="", original_size=item.size
            )
        sync_info.is_ignored = True
        setattr(sync_info, 'origin_category', source_list_name)
        setattr(sync_info, 'original_item', item)
        
        if not hasattr(pair_data['result'], 'ignored_files'):
            pair_data['result'].ignored_files = []
            
        # 2. Append to ignored list ONLY if not already there
        if not any(f.canvas_file_id == canvas_file_id for f in pair_data['result'].ignored_files):
            pair_data['result'].ignored_files.append(sync_info)
            
        _fname_clean, _ = os.path.splitext(unquote_plus(fname))
        st.toast(f"🚫 Ignored '{_fname_clean}'")

    def handle_restore(pair_idx, sync_info):
        pair_data = st.session_state['sync_analysis_results'][pair_idx]
        sm = SyncManager(pair_data['pair']['local_folder'], pair_data['pair']['course_id'], pair_data['pair']['course_name'])
        sm.restore_file(sync_info.canvas_file_id)
        
        sync_info.is_ignored = False
        
        # 1. Safely remove from ignored_files list
        if hasattr(pair_data['result'], 'ignored_files'):
            pair_data['result'].ignored_files = [f for f in pair_data['result'].ignored_files if f.canvas_file_id != sync_info.canvas_file_id]
            
        origin = getattr(sync_info, 'origin_category', 'missing_files')
        dest_list = getattr(pair_data['result'], origin, pair_data['result'].missing_files)
        original_item = getattr(sync_info, 'original_item', sync_info)
        
        def get_id(x):
            if isinstance(x, tuple): return x[0].id
            elif hasattr(x, 'canvas_file_id'): return x.canvas_file_id
            return x.id
            
        # 2. Append to destination list ONLY if not already there
        if not any(get_id(x) == sync_info.canvas_file_id for x in dest_list):
            dest_list.append(original_item)
        
        prefixes = {
            'new_files': 'sync_new',
            'updated_files': 'sync_upd',
            'missing_files': 'sync_miss',
            'locally_deleted_files': 'sync_locdel'
        }
        prefix = prefixes.get(origin, 'sync_miss')
        st.session_state[f'{prefix}_{pair_data["pair"]["course_id"]}_{sync_info.canvas_file_id}'] = True
        st.session_state['keep_ignored_open'] = True
        
        fname = getattr(original_item, 'display_name', getattr(original_item, 'filename', getattr(sync_info, 'canvas_filename', 'file')))
        _fname_clean, _ = os.path.splitext(unquote_plus(fname))
        st.toast(f"↩️ Restored '{_fname_clean}'")

    def handle_restore_all(pair_idx):
        pair_data = st.session_state['sync_analysis_results'][pair_idx]
        sm = SyncManager(pair_data['pair']['local_folder'], pair_data['pair']['course_id'], pair_data['pair']['course_name'])
        
        if not hasattr(pair_data['result'], 'ignored_files') or not pair_data['result'].ignored_files:
            return
            
        file_ids = [f.canvas_file_id for f in pair_data['result'].ignored_files]
        sm.bulk_restore_files(file_ids)
        
        def get_id(x):
            if isinstance(x, tuple): return x[0].id
            elif hasattr(x, 'canvas_file_id'): return x.canvas_file_id
            return x.id
        
        for sync_info in list(pair_data['result'].ignored_files):
            sync_info.is_ignored = False
            origin = getattr(sync_info, 'origin_category', 'missing_files')
            dest_list = getattr(pair_data['result'], origin, pair_data['result'].missing_files)
            original_item = getattr(sync_info, 'original_item', sync_info)
            
            # append safely
            if not any(get_id(x) == sync_info.canvas_file_id for x in dest_list):
                dest_list.append(original_item)
            
            prefixes = {
                'new_files': 'sync_new',
                'updated_files': 'sync_upd',
                'missing_files': 'sync_miss',
                'locally_deleted_files': 'sync_locdel'
            }
            prefix = prefixes.get(origin, 'sync_miss')
            st.session_state[f'{prefix}_{pair_data["pair"]["course_id"]}_{sync_info.canvas_file_id}'] = True
            
        pair_data['result'].ignored_files.clear()
        st.session_state['keep_ignored_open'] = True
        
        st.toast(f"♻️ Restored {len(file_ids)} ignored files")

    def handle_sweep(pair_idx, source_list_name, item_key_prefix):
        pair_data = st.session_state['sync_analysis_results'][pair_idx]
        source_list = getattr(pair_data['result'], source_list_name)
        
        def get_id(x):
            if isinstance(x, tuple): return x[0].id
            elif hasattr(x, 'canvas_file_id'): return x.canvas_file_id
            return x.id

        def get_fname(x):
            if isinstance(x, tuple):
                return x[0].display_name or x[0].filename if hasattr(x[0], 'filename') else ''
            elif hasattr(x, 'canvas_filename'):
                return x.canvas_filename
            elif hasattr(x, 'filename'):
                return x.display_name or x.filename
            return ''
            
        items_to_ignore = []
        file_ids_and_names = []
        
        for item in list(source_list):
            fid = get_id(item)
            chk_key = f"{item_key_prefix}_{pair_data['pair']['course_id']}_{fid}"
            if not st.session_state.get(chk_key, True):
                items_to_ignore.append(item)
                file_ids_and_names.append((fid, get_fname(item)))
                
        if not items_to_ignore:
            return
            
        sm = SyncManager(pair_data['pair']['local_folder'], pair_data['pair']['course_id'], pair_data['pair']['course_name'])
        sm.bulk_ignore_files(file_ids_and_names)
        
        if not hasattr(pair_data['result'], 'ignored_files'):
            pair_data['result'].ignored_files = []
        
        # Build lookup set of IDs being ignored (Fix: was undefined — NameError)
        file_ids_to_ignore = {get_id(item) for item in items_to_ignore}
            
        # Rebuild origin list directly safely
        setattr(pair_data['result'], source_list_name, [x for x in source_list if get_id(x) not in file_ids_to_ignore])
            
        for item in items_to_ignore:
            fid = get_id(item)
            if isinstance(item, tuple):
                sync_info = item[1]
            elif hasattr(item, 'canvas_file_id'):
                sync_info = item
            else:
                sync_info = SyncFileInfo(
                    canvas_file_id=item.id,
                    canvas_filename=item.display_name or item.filename,
                    local_path="", canvas_updated_at="", downloaded_at="", original_size=item.size
                )
            sync_info.is_ignored = True
            setattr(sync_info, 'origin_category', source_list_name)
            setattr(sync_info, 'original_item', item)
            
            # append safely
            if not any(f.canvas_file_id == fid for f in pair_data['result'].ignored_files):
                pair_data['result'].ignored_files.append(sync_info)
                
        st.toast(f"🚫 Ignored {len(items_to_ignore)} deselected files")

    

    all_results = st.session_state.get('sync_analysis_results', [])
    if not all_results:
        st.error("Analysis failed. Please try again.")
        if st.button('Back'):
            st.session_state['step'] = 1
            st.rerun()
        st.stop()

    total_new = sum(len(r['result'].new_files) for r in all_results)
    total_upd = sum(len(r['result'].updated_files) for r in all_results)
    total_miss = sum(len(r['result'].missing_files) for r in all_results)
    total_loc_del = sum(len(r['result'].locally_deleted_files) for r in all_results)
    total_del = sum(len(r['result'].deleted_on_canvas) for r in all_results)
    total_uptodate = sum(len(r['result'].uptodate_files) + getattr(r['result'], 'untracked_shortcuts', 0) for r in all_results)
    total_ignored = sum(len(r['result'].ignored_files) if hasattr(r['result'], 'ignored_files') else 0 for r in all_results)

    

    # Load sync-type icons for metric cards and expander headers
    _b64_icon_new    = get_base64_image("assets/Icon_Sync_Review_New_File.png")
    _b64_icon_upd    = get_base64_image("assets/Icon_Sync_Review_Update.png")
    _b64_icon_miss   = get_base64_image("assets/Icon_Sync_Review_Missing_File.png")
    _b64_icon_locdel = get_base64_image("assets/Icon_Sync_Review_Locally_Deleted.png")
    _b64_icon_del    = get_base64_image("assets/Icon_Sync_Review_Deleted_On_Canvas.png")
    _b64_icon_ignore = get_base64_image("assets/Icon_Ignore.svg")
    _b64_icon_eye    = get_base64_image("assets/Icon_Eye.svg")
    _b64_icon_restore = get_base64_image("assets/icon_restore.png")

    def _sync_icon_img(b64, size=26):
        return f'<img src="data:image/png;base64,{b64}" style="width:{size}px; height:{size}px; object-fit:contain; display:block;" />'

    # Summary logic
    if total_new > 0 or total_upd > 0 or total_miss > 0 or total_del > 0 or total_loc_del > 0 or total_ignored > 0:

        sum_cols = st.columns([3, 2])
        with sum_cols[0]:
            c1, c2, c3, c4, c5 = st.columns(5)

            # Determine labels safely based on lang
            lbl_new = "New files"
            lbl_upd = "Updates available"
            lbl_miss = "Missing files"
            lbl_loc_del = "Deleted locally"
            lbl_del = "Deleted on Canvas"

            def _render_metric_card(val, lbl, icon, hex_start, hex_end, shadow_color):
                base_card_css = "border-radius:12px; padding:18px 14px; position:relative; overflow:hidden; min-height: 95px; transition: all 0.2s ease-in-out;"

                if val > 0:
                    bg_style = f"background: linear-gradient(135deg, {hex_start}, {hex_end}); box-shadow: 0 10px 20px -5px {shadow_color}; border: 1px solid transparent;"
                    text_opacity = "1"
                    icon_bg = "rgba(0,0,0,0.15)"
                    filter_style = ""
                else:
                    # Muted state: 3% white background, 8% opacity border, 30% text opacity, 100% greyscale
                    bg_style = f"background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); box-shadow: none;"
                    text_opacity = "0.3"
                    icon_bg = "rgba(255, 255, 255, 0.04)"
                    filter_style = "filter: grayscale(100%) brightness(0.8);"

                icon_css = f"position:absolute; top:14px; right:14px; background:{icon_bg}; border-radius:10px; width:42px; height:42px; display:flex; align-items:center; justify-content:center; opacity: {text_opacity};"
                num_css = f"font-size:2.7em; font-weight:700; color:rgba(255,255,255,{text_opacity}); line-height:1;"
                lbl_css = f"font-size:0.95em; color:rgba(255,255,255,{text_opacity}); font-weight:500; margin-top:8px; line-height:1.2; word-wrap:break-word;"

                return f'''
                <div style="{base_card_css} {bg_style} {filter_style}">
                    <div style="{num_css}">{val}</div>
                    <div style="{lbl_css}">{lbl}</div>
                    <div style="{icon_css}">{icon}</div>
                </div>
                '''

            with c1:
                st.markdown(_render_metric_card(total_new, lbl_new, _sync_icon_img(_b64_icon_new), "#4a90e2", "#2980b9", "rgba(74, 144, 226, 0.35)"), unsafe_allow_html=True)
            with c2:
                st.markdown(_render_metric_card(total_upd, lbl_upd, _sync_icon_img(_b64_icon_upd), theme.SUCCESS_ALT, "#27ae60", "rgba(46, 204, 113, 0.35)"), unsafe_allow_html=True)
            with c3:
                st.markdown(_render_metric_card(total_miss, lbl_miss, _sync_icon_img(_b64_icon_miss), theme.WARNING_ALT, "#e67e22", "rgba(241, 196, 15, 0.35)"), unsafe_allow_html=True)
            with c4:
                st.markdown(_render_metric_card(total_loc_del, lbl_loc_del, _sync_icon_img(_b64_icon_locdel), "#9b59b6", "#8e44ad", "rgba(155, 89, 182, 0.35)"), unsafe_allow_html=True)
            with c5:
                st.markdown(_render_metric_card(total_del, lbl_del, _sync_icon_img(_b64_icon_del), theme.ERROR_ALT, "#c0392b", "rgba(231, 76, 60, 0.35)"), unsafe_allow_html=True)
                
        st.markdown("<div style='margin-bottom: 25px;'></div>", unsafe_allow_html=True)

        # --- NotebookLM Compatible Download Toggle (Sync Mode) ---



    # Nothing actionable to sync — redirect to completion screen.
    # When only ignored files exist, the student manages those from the Sync Hub,
    # not from the review page.
    if total_new == 0 and total_upd == 0 and total_miss == 0 and total_del == 0 and total_loc_del == 0:
        # Advance to the completion screen (step 4) with zero-file success state
        st.session_state['synced_count'] = 0
        st.session_state['synced_bytes'] = 0
        st.session_state['sync_errors'] = []
        st.session_state['synced_details'] = {}
        st.session_state['retry_selections'] = []
        st.session_state['up_to_date_file_count'] = total_uptodate
        if total_ignored > 0:
            st.session_state['sync_has_ignored_files'] = True
        st.session_state['download_status'] = 'sync_complete'
        st.session_state['step'] = 4
        st.rerun()


    # Feature 1: Advanced filtering & Global Selection
    all_extensions = set()
    from collections import defaultdict
    files_by_ext = defaultdict(list)
    
    for idx, res_data in enumerate(all_results):
        res = res_data['result']
        cid = res_data['pair']['course_id']
        for f in res.new_files:
            ext = os.path.splitext(f.filename)[1].lower() or "Unknown"
            all_extensions.add(ext)
            files_by_ext[ext].append(f'sync_new_{cid}_{f.id}')
        for f, _ in res.updated_files:
            ext = os.path.splitext(f.filename)[1].lower() or "Unknown"
            all_extensions.add(ext)
            files_by_ext[ext].append(f'sync_upd_{cid}_{f.id}')
        for si in res.missing_files:
            ext = os.path.splitext(si.canvas_filename)[1].lower() or "Unknown"
            all_extensions.add(ext)
            files_by_ext[ext].append(f'sync_miss_{cid}_{si.canvas_file_id}')
        for si in res.locally_deleted_files:
            ext = os.path.splitext(si.canvas_filename)[1].lower() or "Unknown"
            all_extensions.add(ext)
            files_by_ext[ext].append(f'sync_locdel_{cid}_{si.canvas_file_id}')

    if all_extensions:
        all_exts_sorted = sorted(list(all_extensions))
        


        def toggle_single_ext(ext_name):
            new_state = st.session_state.get(f'sync_filter_ext_{ext_name}', True)
            ext_files = [k for k in files_by_ext[ext_name] if k.startswith('sync_')]
            for file_key in ext_files:
                st.session_state[file_key] = new_state

        b64_select_all = get_base64_image("assets/icon_select_all.png")
        b64_clear = get_base64_image("assets/icon_clear_selection.png")

        col_main, _ = st.columns([3.5, 8.5])
        with col_main:
            # Hoist CSS above card (CLAUDE.md: inject above target)
            # st-key-* class sits directly on stVerticalBlockBorderWrapper — target it flat.
            st.html(f"""<style>
            /* Card */
            div.st-key-sync_filter_box_outer {{
                background-color: {theme.BG_DARK} !important;
                border: none !important;
                border-radius: 12px !important;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.45) !important;
                margin-top: 8px !important;
                padding-top: 6px !important;
            }}
            /* Filetype box: strip border */
            div.st-key-filetypes_flex_box {{
                border: none !important;
                background: transparent !important;
                box-shadow: none !important;
                padding: 0 !important;
                margin-top: 0px !important;
            }}
            /* Checkbox ↔ label gap: use gap on the label flex container */
            div.st-key-sync_filter_box_outer [data-testid="stCheckbox"] label {{
                display: flex !important;
                align-items: center !important;
                gap: 0px !important;
                column-gap: 0px !important;
            }}
            div.st-key-sync_filter_box_outer [data-testid="stCheckbox"] label > div {{
                margin-left: -2px !important;
            }}
            /* Visual checkbox span — nudge up 1px for optical vertical alignment */
            div.st-key-sync_filter_box_outer [data-testid="stCheckbox"] label > span {{
                position: relative !important;
                top: -1px !important;
            }}
            div.st-key-sync_filter_box_outer [data-testid="stCheckbox"] label p {{
                margin: 0 !important;
                padding: 0 !important;
            }}
            /* Buttons row: strip border */
            div.st-key-bulk_btns_row {{
                border: none !important;
                background: transparent !important;
                box-shadow: none !important;
                padding: 0 !important;
                margin: 0 !important;
            }}
            div.st-key-bulk_btns_row > div[data-testid="stVerticalBlock"] {{
                gap: 0 !important;
                padding-bottom: 0 !important;
            }}
            /* Button styles */
            div.st-key-btn_bulk_select_all button,
            div.st-key-btn_bulk_deselect_all button {{
                background-color: rgba(255, 255, 255, 0.07) !important;
                border: none !important;
                border-radius: 8px !important;
                color: #ffffff !important;
                height: 33px !important;
                min-height: 33px !important;
                padding-left: 12px !important;
                padding-right: 14px !important;
                white-space: nowrap !important;
                width: 100% !important;
                transition: background-color 0.15s ease !important;
            }}
            div.st-key-btn_bulk_select_all button:hover,
            div.st-key-btn_bulk_deselect_all button:hover {{
                background-color: rgba(255, 255, 255, 0.15) !important;
                color: #ffffff !important;
            }}
            div.st-key-btn_bulk_select_all button p,
            div.st-key-btn_bulk_deselect_all button p {{
                display: flex !important;
                align-items: center !important;
                gap: 10px !important;
                margin: 0 !important;
                width: auto !important;
                line-height: 1 !important;
                white-space: nowrap !important;
            }}
            div.st-key-btn_bulk_select_all button p::before,
            div.st-key-btn_bulk_deselect_all button p::before {{
                content: "" !important;
                display: inline-block !important;
                width: 16px !important;
                height: 16px !important;
                background-size: contain !important;
                background-repeat: no-repeat !important;
                background-position: center !important;
                flex-shrink: 0 !important;
            }}
            div.st-key-btn_bulk_select_all button p::before {{
                background-image: url('data:image/png;base64,{b64_select_all}') !important;
            }}
            div.st-key-btn_bulk_deselect_all button p::before {{
                background-image: url('data:image/png;base64,{b64_clear}') !important;
            }}
            </style>""")

            with st.container(border=True, key="sync_filter_box_outer"):
                st.html("<h3 style='margin-top: 18px; margin-bottom: 0px; font-size: 1.25rem; font-weight: 700;'>Smart Select</h3>")

                if all_exts_sorted:
                    st.html("<div style='font-size: 0.75em; padding-top: 0px; padding-bottom: 3px; color: rgba(255,255,255,0.45); font-weight: 400;'>By filetype</div>")

                    css_blocks = []
                    css_blocks.append("""
                    div.st-key-filetypes_flex_box {
                        margin-top: 2px !important; /* Move down from the By filetype subtitle */
                    }
                    div.st-key-filetypes_flex_box div[data-testid="stHorizontalBlock"] {
                        flex-wrap: wrap !important;
                        row-gap: 8px !important;
                        column-gap: 8px !important;
                        margin-bottom: -16px !important;
                    }
                    div.st-key-filetypes_flex_box div[data-testid="stColumn"] {
                        width: auto !important;
                        flex: 0 0 auto !important;
                        min-width: 0 !important;
                        padding-bottom: 16px !important;
                    }
                    div.st-key-filetypes_flex_box div[data-testid="stColumn"] > div[data-testid="stVerticalBlock"] {
                        gap: 0 !important;
                    }
                    """)

                    with st.container(border=True, key="filetypes_flex_box"):
                        safe_len = min(len(all_exts_sorted), 90)
                        cols = st.columns(safe_len)
                        for i, ext in enumerate(all_exts_sorted):
                            col_idx = i % safe_len
                            ext_files = [k for k in files_by_ext[ext] if k.startswith('sync_')]
                            total = len(ext_files)
                            
                            safe_ext = ext.replace('.', '')
                            btn_key = f"sync_filter_btn_{safe_ext}"

                            if total > 0:
                                selected = sum(1 for k in ext_files if st.session_state.get(k, True))
                            else:
                                selected = 0

                            def _on_unit_click(ext_name=ext):
                                e_files = [k for k in files_by_ext[ext_name] if k.startswith('sync_')]
                                tot = len(e_files)
                                sel = sum(1 for k in e_files if st.session_state.get(k, True))
                                new_val = False if sel == tot else True
                                for k in e_files:
                                    st.session_state[k] = new_val

                            ext_label = ext[1:].upper() if ext.startswith('.') else ext.upper()

                            if selected == 0:
                                final_label = f"{ext_label} :grey[(none)]"
                                bg_color = "#11141a"
                                bg_color_hover = "#1a1e28"
                                border_color = "rgba(255, 255, 255, 0.25)"
                                border_color_hover = "rgba(255, 255, 255, 0.4)"
                                text_color = "#ffffff"
                            elif selected == total:
                                final_label = f"{ext_label} :grey[(all)]"
                                bg_color = "#1f486b"
                                bg_color_hover = "#285b86"
                                border_color = "#3498db"
                                border_color_hover = "#5dade2"
                                text_color = "#ffffff"
                            else:
                                final_label = f"{ext_label} :grey[({selected}/{total})]"
                                bg_color = "#0d1b2a"
                                bg_color_hover = "#142838"
                                border_color = "#3498db"
                                border_color_hover = "#5dade2"
                                text_color = "#ffffff"

                            css_blocks.append(f"""
                            div.st-key-{btn_key} button {{
                                background-color: {bg_color} !important;
                                border: 1px solid {border_color} !important;
                                color: {text_color} !important;
                                padding: 2px 14px !important;
                                min-height: 28px !important;
                                height: 28px !important;
                                border-radius: 6px !important;
                                transition: all 0.15s ease !important;
                                box-shadow: none !important;
                            }}
                            div.st-key-{btn_key} button:hover {{
                                background-color: {bg_color_hover} !important;
                                border-color: {border_color_hover} !important;
                            }}
                            div.st-key-{btn_key} button p {{
                                font-size: 0.8rem !important;
                                font-weight: 500 !important;
                                margin: 0 !important;
                            }}
                            /* Fix vertical alignment and styling for the grey tag partial numbers */
                            div.st-key-{btn_key} button p span {{
                                font-size: 0.7rem !important;
                                font-weight: 400 !important;
                                color: rgba(255, 255, 255, 0.55) !important;
                                margin-left: 3px !important;
                                letter-spacing: 0.3px !important;
                            }}
                            """)

                            with cols[col_idx]:
                                st.button(final_label, key=btn_key, on_click=_on_unit_click)

                    if css_blocks:
                        st.html(f"<style>{''.join(css_blocks)}</style>")

                # Separator + action buttons — padding wraps hr inside shadow root so spacing is real
                st.html("<div style='padding: 5px 0 10px 0;'><hr style='border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 0;' /></div>")

                # border=True required for st-key class to be reliably emitted (CLAUDE.md Border Strip rule)
                with st.container(border=True, key="bulk_btns_row"):
                    col_sel, col_clr = st.columns([1, 1])
                    with col_sel:
                        if st.button("Select All", key="btn_bulk_select_all", use_container_width=True):
                            for k in sum(files_by_ext.values(), []):
                                if k.startswith('sync_locdel_'):
                                    ignore_key = k.replace('sync_locdel_', 'ignore_')
                                    if st.session_state.get(ignore_key, False):
                                        continue
                                st.session_state[k] = True
                            st.rerun()
                    with col_clr:
                        if st.button("Deselect All", key="btn_bulk_deselect_all", use_container_width=True):
                            for k in sum(files_by_ext.values(), []):
                                st.session_state[k] = False
                            st.rerun()

    # Inject base64 icons into expander category headers via CSS ::before
    st.html(f"""<style>
    div[class*="st-key-cat_new_"] details > summary p::before {{
        content: "";
        display: inline-block;
        width: 18px;
        height: 18px;
        background-image: url('data:image/png;base64,{_b64_icon_new}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        vertical-align: middle;
        margin-right: 7px;
        position: relative;
        top: -1px;
    }}
    div[class*="st-key-cat_update_"] details > summary p::before {{
        content: "";
        display: inline-block;
        width: 18px;
        height: 18px;
        background-image: url('data:image/png;base64,{_b64_icon_upd}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        vertical-align: middle;
        margin-right: 7px;
        position: relative;
        top: -1px;
    }}
    div[class*="st-key-cat_missing_"] details > summary p::before {{
        content: "";
        display: inline-block;
        width: 18px;
        height: 18px;
        background-image: url('data:image/png;base64,{_b64_icon_miss}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        vertical-align: middle;
        margin-right: 7px;
        position: relative;
        top: -1px;
    }}
    div[class*="st-key-cat_deleted_local_"] details > summary p::before {{
        content: "";
        display: inline-block;
        width: 18px;
        height: 18px;
        background-image: url('data:image/png;base64,{_b64_icon_locdel}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        vertical-align: middle;
        margin-right: 7px;
        position: relative;
        top: -1px;
    }}
    div[class*="st-key-cat_deleted_canvas_"] details > summary p::before {{
        content: "";
        display: inline-block;
        width: 18px;
        height: 18px;
        background-image: url('data:image/png;base64,{_b64_icon_del}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        vertical-align: middle;
        margin-right: 7px;
        position: relative;
        top: -1px;
    }}
    div[class*="st-key-cat_ignored_"] details > summary p::before {{
        content: "";
        display: inline-block;
        width: 18px;
        height: 18px;
        background-image: url('data:image/svg+xml;base64,{_b64_icon_ignore}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        vertical-align: middle;
        margin-right: 7px;
        position: relative;
        top: -1px;
        filter: brightness(0) invert(1) opacity(0.9);
    }}
    }}
    </style>""")
    
    import streamlit.components.v1 as components
    components.html("""
        <script>
            const doc = window.parent.document;
            
            // Protect against duplicate injection on React rerender
            if (!doc.getElementById('premium-hover-tooltip')) {
                const tooltip = doc.createElement('div');
                tooltip.id = 'premium-hover-tooltip';
                
                Object.assign(tooltip.style, {
                    position: 'fixed',
                    backgroundColor: 'rgba(17, 24, 39, 0.95)',
                    color: '#e2e8f0',
                    padding: '6px 12px',
                    borderRadius: '6px',
                    fontSize: '0.82rem',
                    fontWeight: '500',
                    whiteSpace: 'nowrap',
                    zIndex: '9999999',
                    pointerEvents: 'none',
                    border: '1px solid rgba(255,255,255,0.1)',
                    opacity: '0',
                    transition: 'opacity 0.15s ease',
                    top: '0px',
                    left: '0px'
                });
                
                doc.body.appendChild(tooltip);
                
                // High-performance static tooltip tracker with UX debounce delays
                let activeSummary = null;
                let showTimer = null;
                let hideTimer = null;
                
                doc.addEventListener('mouseover', function(e) {
                    const summary = e.target.closest('div[class*="st-key-cat_"] details > summary');
                    
                    if (summary) {
                        // Cancel any pending hide timers immediately upon re-entry
                        clearTimeout(hideTimer);
                        hideTimer = null;
                        
                        if (activeSummary === summary) return;
                        
                        let text = "";
                        if(summary.closest('div[class*="st-key-cat_new_"]')) text = "Brand new files available on Canvas";
                        else if(summary.closest('div[class*="st-key-cat_update_"]')) text = "Files with a newer timestamp on Canvas";
                        else if(summary.closest('div[class*="st-key-cat_missing_"]')) text = "Files that are missing from your computer";
                        else if(summary.closest('div[class*="st-key-cat_deleted_local_"]')) text = "Files you deleted locally (will not be re-downloaded)";
                        else if(summary.closest('div[class*="st-key-cat_deleted_canvas_"]')) text = "Files the teacher removed from Canvas (preserved locally for your safety)";
                        else if(summary.closest('div[class*="st-key-cat_ignored_"]')) text = "Files you permanently ignored from syncing";
                        
                        if (text) {
                            // Queue the tooltip to show after a brief purposeful hover delay (200ms)
                            clearTimeout(showTimer);
                            showTimer = setTimeout(() => {
                                activeSummary = summary;
                                tooltip.innerText = text;
                                tooltip.style.left = e.clientX + 'px';
                                tooltip.style.top = (e.clientY - 45) + 'px';
                                tooltip.style.opacity = '1';
                            }, 200);
                        }
                    }
                });
                
                doc.addEventListener('mouseout', function(e) {
                    const summary = e.target.closest('div[class*="st-key-cat_"] details > summary');
                    if (summary) {
                        // Keep tooltip alive if moving gracefully between nested HTML elements
                        if (e.relatedTarget && summary.contains(e.relatedTarget)) {
                            return;
                        }
                        
                        // The user cleanly exited the element boundaries
                        clearTimeout(showTimer);
                        showTimer = null;
                        
                        // Add a let-go grace period before physically hiding the tooltip
                        clearTimeout(hideTimer);
                        hideTimer = setTimeout(() => {
                            activeSummary = null;
                            tooltip.style.opacity = '0';
                        }, 200);
                    }
                });
            }
        </script>
    """, height=0, width=0)
    
    st.html(f"""<style>
    /* ===== FILE SIZE AND EXTENSION TAGS ===== */
    div[class*="st-key-cat_"] del {{
        text-decoration: none !important;
        background-color: rgba(255, 255, 255, 0.1) !important;
        color: #ffffff !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        font-size: 0.70rem !important;
        font-weight: 500 !important;
        margin-left: 6px !important;
    }}
    div[class*="st-key-cat_"] code {{
        background-color: rgba(0, 0, 0, 0.25) !important;
        color: #9ca3af !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        font-size: 0.70rem !important;
        font-weight: 500 !important;
        border: none !important;
        margin-left: 6px !important;
    }}

    /* ===== INLINE IGNORE ICON BUTTONS ===== */
    /* Right-align: cascade flex through the keyed container AND Streamlit's stButton wrapper */
    div[class*="st-key-ign_new_"],
    div[class*="st-key-ign_upd_"],
    div[class*="st-key-ign_miss_"],
    div[class*="st-key-ign_locdel_"] {{
        display: flex !important;
        justify-content: flex-end !important;
        width: 100% !important;
    }}
    div[class*="st-key-ign_new_"] div[data-testid="stButton"],
    div[class*="st-key-ign_upd_"] div[data-testid="stButton"],
    div[class*="st-key-ign_miss_"] div[data-testid="stButton"],
    div[class*="st-key-ign_locdel_"] div[data-testid="stButton"] {{
        display: flex !important;
        justify-content: flex-end !important;
        width: 100% !important;
    }}
    div[class*="st-key-ign_new_"] button,
    div[class*="st-key-ign_upd_"] button,
    div[class*="st-key-ign_miss_"] button,
    div[class*="st-key-ign_locdel_"] button {{
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        min-height: 32px !important;
        height: 32px !important;
        width: 32px !important;
        min-width: 32px !important;
        position: relative !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    div[class*="st-key-ign_new_"] button p,
    div[class*="st-key-ign_upd_"] button p,
    div[class*="st-key-ign_miss_"] button p,
    div[class*="st-key-ign_locdel_"] button p {{
        display: none !important;
    }}
    /* Default state: eye icon — nudged up 1px to align visual center with the taller ignore icon */
    div[class*="st-key-ign_new_"] button::before,
    div[class*="st-key-ign_upd_"] button::before,
    div[class*="st-key-ign_miss_"] button::before,
    div[class*="st-key-ign_locdel_"] button::before {{
        content: '';
        position: absolute;
        width: 21px;
        height: 21px;
        background-image: url('data:image/svg+xml;base64,{_b64_icon_eye}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        filter: brightness(0) invert(1) opacity(0.9);
        transition: opacity 0.15s ease, transform 0.15s ease;
        opacity: 1;
        transform: translateY(-1px) scale(1);
        transform-origin: center;
    }}
    /* Hover state: ignore icon (eye with slash) — scales in from 1→1.2 as it fades in */
    div[class*="st-key-ign_new_"] button::after,
    div[class*="st-key-ign_upd_"] button::after,
    div[class*="st-key-ign_miss_"] button::after,
    div[class*="st-key-ign_locdel_"] button::after {{
        content: '';
        position: absolute;
        width: 21px;
        height: 21px;
        background-image: url('data:image/svg+xml;base64,{_b64_icon_ignore}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        filter: brightness(0) saturate(100%) invert(35%) sepia(100%) saturate(1500%) hue-rotate(330deg) brightness(140%);
        transition: opacity 0.15s ease, transform 0.15s ease;
        opacity: 0;
        transform: scale(1);
        transform-origin: center;
    }}
    div[class*="st-key-ign_new_"] button:hover,
    div[class*="st-key-ign_upd_"] button:hover,
    div[class*="st-key-ign_miss_"] button:hover,
    div[class*="st-key-ign_locdel_"] button:hover {{
        background: transparent !important;
        border: none !important;
    }}
    /* On hover: eye fades out while ALSO scaling to 1.2 — so the "grow" is continuous across both icons */
    div[class*="st-key-ign_new_"] button:hover::before,
    div[class*="st-key-ign_upd_"] button:hover::before,
    div[class*="st-key-ign_miss_"] button:hover::before,
    div[class*="st-key-ign_locdel_"] button:hover::before {{
        opacity: 0;
        transform: translateY(-1px) scale(1.2);
    }}
    div[class*="st-key-ign_new_"] button:hover::after,
    div[class*="st-key-ign_upd_"] button:hover::after,
    div[class*="st-key-ign_miss_"] button:hover::after,
    div[class*="st-key-ign_locdel_"] button:hover::after {{
        opacity: 1;
        transform: scale(1.2);
    }}

    /* ===== INLINE RESTORE ICON BUTTONS ===== */
    div[class*="st-key-restitem_"] {{
        display: flex !important;
        justify-content: flex-end !important;
        width: 100% !important;
    }}
    div[class*="st-key-restitem_"] div[data-testid="stButton"] {{
        display: flex !important;
        justify-content: flex-end !important;
        width: 100% !important;
    }}
    div[class*="st-key-restitem_"] button {{
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        min-height: 32px !important;
        height: 32px !important;
        width: 32px !important;
        min-width: 32px !important;
        position: relative !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    div[class*="st-key-restitem_"] button p {{
        display: none !important;
    }}
    /* Default state: restore icon */
    div[class*="st-key-restitem_"] button::before {{
        content: '';
        position: absolute;
        width: 17px;
        height: 17px;
        background-image: url('data:image/png;base64,{_b64_icon_restore}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        filter: brightness(0) invert(1) opacity(0.9);
        transition: opacity 0.15s ease, transform 0.15s ease;
        opacity: 1;
        transform: translateY(-1px) scale(1);
        transform-origin: center;
    }}
    div[class*="st-key-restitem_"] button:hover {{
        background: transparent !important;
        border: none !important;
    }}
    /* On hover: scale to 1.2 */
    div[class*="st-key-restitem_"] button:hover::before {{
        transform: translateY(-1px) scale(1.2);
    }}

    /* ===== 'RESTORE ALL IGNORED FILES' BULK BUTTON ===== */
    div[class*="st-key-restore_all_"] button p::before {{
        content: "";
        display: inline-block;
        width: 16px;
        height: 16px;
        margin-right: 8px;
        background-image: url('data:image/png;base64,{_b64_icon_restore}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        filter: brightness(0) invert(1) opacity(0.9);
        position: relative;
        vertical-align: middle;
        transform: translateY(-2px);
    }}
    div[class*="st-key-restore_all_"] button:disabled p::before {{
        opacity: 0.3 !important;
    }}

    /* ===== 'IGNORE UNCHECKED' BULK BUTTONS ===== */
    div[class*="st-key-sweep_"] button p::before {{
        content: "";
        display: inline-block;
        width: 16px;
        height: 16px;
        margin-right: 8px;
        background-image: url('data:image/svg+xml;base64,{_b64_icon_ignore}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        filter: brightness(0) invert(1) opacity(0.9);
        position: relative;
        vertical-align: middle;
        transform: translateY(-2px);
    }}
    div[class*="st-key-sweep_"] button:disabled p::before {{
        opacity: 0.3 !important;
    }}
    div[class*="st-key-sweep_"] button p em {{
        color: #9ca3af !important;
        font-style: normal !important;
        font-size: 0.88em !important;
        margin-left: 5px !important;
        vertical-align: baseline !important;
    }}
    /* Dim the counter when button is disabled to match parent text */
    div[class*="st-key-sweep_"] button:disabled p em {{
        color: rgba(255, 255, 255, 0.3) !important;
    }}
    </style>""")

    # Per-folder results
    for idx, res_data in enumerate(all_results):
        with st.container(border=True):
            pair = res_data['pair']
            result = res_data['result']

            display_name = friendly_course_name(pair['course_name'])
            folder_display = short_path(pair['local_folder'])
            
            # Build status pill — pending takes priority over up-to-date
            # Strictly use uptodate_files only — do NOT add untracked_shortcuts
            # as those are already counted in new_files or other actionable categories
            uptodate_count = len(result.uptodate_files)
            pending_count = (
                len(result.new_files)
                + len(result.updated_files)
                + len(result.missing_files)
                + len(result.locally_deleted_files)
            )
            _sync_icon_b64 = get_base64_image("assets/icon_sync.png")
            # Dimmed white sync icon for the pending-sync label
            _sync_icon_html = f'<img src="data:image/png;base64,{_sync_icon_b64}" style="width:12px; height:12px; vertical-align:middle; margin-right:4px; flex-shrink:0; filter: brightness(0) invert(1) opacity(0.5);" />'
            # Inline checkmark for the up-to-date label (base64 to avoid Streamlit SVG sanitization)
            import base64 as _b64
            _check_svg_raw = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="rgba(255,255,255,0.5)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="2,9 6,13 14,3"/></svg>'
            _check_b64 = _b64.b64encode(_check_svg_raw.encode()).decode()
            _checkmark_svg = f'<img src="data:image/svg+xml;base64,{_check_b64}" style="width:12px; height:12px; vertical-align:middle; margin-right:4px; flex-shrink:0;" />'
            # No background — plain grey text labels stacked on the right
            _tag_style = (
                "font-size: 0.73rem; color: rgba(255,255,255,0.45); font-weight: 500; "
                "display:inline-flex; align-items:center; white-space:nowrap;"
            )

            pending_pill = ""
            uptodate_pill = ""
            if pending_count:
                pending_word = "file" if pending_count == 1 else "files"
                pending_pill = f'<span style="{_tag_style}">{_sync_icon_html}{pending_count} {pending_word} pending sync</span>'
            if uptodate_count:
                uptodate_word = "file" if uptodate_count == 1 else "files"
                uptodate_pill = f'<span style="{_tag_style}">{_checkmark_svg}{uptodate_count} {uptodate_word} up to date</span>'

            # 2. THE FLUSH HEADER BAND (Negative Margin Bleed Trick)
            # Light-to-dark grey gradient (dark at top, lighter grey at bottom near expanders).
            # Tags stacked vertically on the far right with no background.
            header_html = f"""
            <div style="
                margin: -16px -16px 16px -16px;
                padding: 16px 16px;
                background: linear-gradient(180deg, #252830 0%, #32363f 100%);
                border: 1px solid rgba(255,255,255,0.1);
                border-bottom: 1px solid rgba(255,255,255,0.06);
                border-radius: 8px 8px 0 0;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
            ">
                <div style="min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 3px;">
                    <div style="display: flex; align-items: baseline; overflow: hidden; white-space: nowrap;">
                        <span style="color: {theme.WHITE}; font-size: 1rem; font-weight: 700; min-width: 26px; flex-shrink: 0;">{idx + 1}.</span>
                        <span style="color: {theme.WHITE}; font-size: 1.15rem; font-weight: 700; overflow: hidden; text-overflow: ellipsis; min-width: 0;">{display_name}</span>
                    </div>
                    <div style="display: flex; align-items: center; overflow: hidden; padding-left: 25px;">
                        <span style="font-size: 0.88rem; flex-shrink: 0; color: initial; filter: none; line-height: 1; margin-right: 5px;">📁</span>
                        <span style="color: rgba(255,255,255,0.75); font-size: 0.78rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0;">{folder_display}</span>
                    </div>
                </div>
                <div style="display: flex; flex-direction: column; gap: 4px; align-items: flex-end; flex-shrink: 0;">
                    {pending_pill}
                    {uptodate_pill}
                </div>
            </div>
            """
            st.markdown(header_html, unsafe_allow_html=True)

            has_new = bool(result.new_files)
            has_updated = bool(result.updated_files)
            has_missing = bool(result.missing_files)
            has_locally_deleted = bool(result.locally_deleted_files)
            has_ignored = hasattr(result, 'ignored_files') and bool(result.ignored_files)

            if not any([has_new, has_updated, has_missing, has_locally_deleted]) and not has_ignored:
                st.success('All files up-to-date')
                continue



            # New files — always starts OPEN
            if result.new_files:
                total_new = len(result.new_files)
                selected_new = sum(1 for f in result.new_files if st.session_state.get(f"sync_new_{pair['course_id']}_{f.id}", True))
                
                

                with st.container(key=f"cat_new_{pair['course_id']}"):
                    with st.expander(f"{'New Files'}"):
                        deselected_new = total_new - selected_new
                        st.button(f"Move deselected files to Ignored *({deselected_new})*", key=f"sweep_new_{pair['course_id']}", use_container_width=True, disabled=(selected_new == total_new), on_click=handle_sweep, args=(idx, 'new_files', 'sync_new'), help="These files will be moved to the Ignored Files section and skipped during sync.")
                        
                        with st.container(key=f"sync_review_file_list_{idx}_new"):
                            for file in result.new_files:
                                ext = os.path.splitext(file.filename)[1].lower() or "Unknown"
                                icon = get_file_icon(file.filename)
                                size = format_file_size(file.size) if file.size else ""
                                key = f"sync_new_{pair['course_id']}_{file.id}"
                                st.session_state.setdefault(key, True)
                                col1, col2 = st.columns([0.85, 0.15], vertical_alignment="center")
                                with col1:
                                    _disp_raw = unquote_plus(file.display_name or file.filename)
                                    _name, _ext = os.path.splitext(_disp_raw)
                                    _ext_clean = f" ~{_ext[1:].upper()}~" if _ext else ""
                                    _size_clean = f" `{size}`" if size else ""
                                    st.checkbox(f"{_name}{_ext_clean}{_size_clean}", key=key)
                                with col2:
                                    st.button("\u200b", key=f"ign_new_{pair['course_id']}_{file.id}", help="Ignore this file (remove from sync list)", on_click=handle_ignore, args=(idx, file.id, 'new_files', file))

            # Updated files — always starts OPEN
            if result.updated_files:
                total_upd = len(result.updated_files)
                selected_upd = sum(1 for f, _ in result.updated_files if st.session_state.get(f"sync_upd_{pair['course_id']}_{f.id}", True))
                
                

                with st.container(key=f"cat_update_{pair['course_id']}"):
                    with st.expander(f"{'Updates Available'}"):
                        deselected_upd = total_upd - selected_upd
                        st.button(f"Move deselected files to Ignored *({deselected_upd})*", key=f"sweep_upd_{pair['course_id']}", use_container_width=True, disabled=(selected_upd == total_upd), on_click=handle_sweep, args=(idx, 'updated_files', 'sync_upd'), help="These files will be moved to the Ignored Files section and skipped during sync.")
                        
                        with st.container(key=f"sync_review_file_list_{idx}_upd"):
                            for canvas_file, sync_info in result.updated_files:
                                ext = os.path.splitext(canvas_file.filename)[1].lower() or "Unknown"
                                icon = get_file_icon(canvas_file.filename)
                                size = format_file_size(canvas_file.size) if canvas_file.size else ""
                                key = f"sync_upd_{pair['course_id']}_{canvas_file.id}"
                                st.session_state.setdefault(key, True)
                                col1, col2 = st.columns([0.85, 0.15], vertical_alignment="center")
                                with col1:
                                    _disp_raw = Path(sync_info.local_path).name if getattr(sync_info, 'local_path', None) else unquote_plus(canvas_file.display_name or canvas_file.filename)
                                    _name, _ext = os.path.splitext(_disp_raw)
                                    _ext_clean = f" ~{_ext[1:].upper()}~" if _ext else ""
                                    _size_clean = f" `{size}`" if size else ""
                                    st.checkbox(f"{_name}{_ext_clean}{_size_clean}", key=key)
                                with col2:
                                    st.button("\u200b", key=f"ign_upd_{pair['course_id']}_{canvas_file.id}", help="Ignore this file (remove from sync list)", on_click=handle_ignore, args=(idx, canvas_file.id, 'updated_files', (canvas_file, sync_info)))

            # Missing files — always starts OPEN
            if result.missing_files:
                total_miss = len(result.missing_files)
                selected_miss = sum(1 for f in result.missing_files if st.session_state.get(f"sync_miss_{pair['course_id']}_{f.canvas_file_id}", True))
                
                

                with st.container(key=f"cat_missing_{pair['course_id']}"):
                    with st.expander(f"{'Missing Files'}"):
                        deselected_miss = total_miss - selected_miss
                        st.button(f"Move deselected files to Ignored *({deselected_miss})*", key=f"sweep_miss_{pair['course_id']}", use_container_width=True, disabled=(selected_miss == total_miss), on_click=handle_sweep, args=(idx, 'missing_files', 'sync_miss'), help="These files will be moved to the Ignored Files section and skipped during sync.")
                        
                        with st.container(key=f"sync_review_file_list_{idx}_miss"):
                            for sync_info in result.missing_files:
                                ext = os.path.splitext(sync_info.canvas_filename)[1].lower() or "Unknown"
                                icon = get_file_icon(sync_info.canvas_filename)
                                key = f"sync_miss_{pair['course_id']}_{sync_info.canvas_file_id}"
                                st.session_state.setdefault(key, True)
                                col1, col2 = st.columns([0.85, 0.15], vertical_alignment="center")
                                with col1:
                                    _disp_raw = Path(sync_info.local_path).name if getattr(sync_info, 'local_path', None) else unquote_plus(sync_info.canvas_filename)
                                    _name, _ext = os.path.splitext(_disp_raw)
                                    _ext_clean = f" ~{_ext[1:].upper()}~" if _ext else ""
                                    st.checkbox(f"{_name}{_ext_clean}", key=key)
                                with col2:
                                    st.button("\u200b", key=f"ign_miss_{pair['course_id']}_{sync_info.canvas_file_id}", help="Ignore this file (remove from sync list)", on_click=handle_ignore, args=(idx, sync_info.canvas_file_id, 'missing_files', sync_info))

            # Locally Deleted Files (Student deleted locally to save space)
            if result.locally_deleted_files:
                total_locdel = len(result.locally_deleted_files)
                selected_locdel = sum(1 for f in result.locally_deleted_files if st.session_state.get(f"sync_locdel_{pair['course_id']}_{f.canvas_file_id}", True))
                
                

                with st.container(key=f"cat_deleted_local_{pair['course_id']}"):
                    with st.expander("Locally Deleted"):
                        deselected_locdel = total_locdel - selected_locdel
                        st.button(f"Move deselected files to Ignored *({deselected_locdel})*", key=f"sweep_locdel_{pair['course_id']}", use_container_width=True, disabled=(selected_locdel == total_locdel), on_click=handle_sweep, args=(idx, 'locally_deleted_files', 'sync_locdel'), help="These files will be moved to the Ignored Files section and skipped during sync.")
                        
                        with st.container(key=f"sync_review_file_list_{idx}_locdel"):
                            for sync_info in result.locally_deleted_files:
                                ext = os.path.splitext(sync_info.canvas_filename)[1].lower() or "Unknown"
                                icon = get_file_icon(sync_info.canvas_filename)
                                key = f"sync_locdel_{pair['course_id']}_{sync_info.canvas_file_id}"
                                st.session_state.setdefault(key, True)
                                col1, col2 = st.columns([0.85, 0.15], vertical_alignment="center")
                                with col1:
                                    _disp_raw = Path(sync_info.local_path).name if getattr(sync_info, 'local_path', None) else unquote_plus(sync_info.canvas_filename)
                                    _name, _ext = os.path.splitext(_disp_raw)
                                    _ext_clean = f" ~{_ext[1:].upper()}~" if _ext else ""
                                    st.checkbox(f"{_name}{_ext_clean}", key=key)
                                with col2:
                                    st.button("\u200b", key=f"ign_locdel_{pair['course_id']}_{sync_info.canvas_file_id}", help="Ignore this file (remove from sync list)", on_click=handle_ignore, args=(idx, sync_info.canvas_file_id, 'locally_deleted_files', sync_info))

            # Deleted files — always starts OPEN
            if result.deleted_on_canvas:
                lbl_del = "Deleted on Canvas (Ignored)"
                
                

                with st.container(key=f"cat_deleted_canvas_{pair['course_id']}"):
                    with st.expander(f"{lbl_del}"):
                        st.caption("These files were deleted by the teacher on Canvas. They are preserved locally for your safety.")
                        for sync_info in result.deleted_on_canvas:
                            icon = get_file_icon(sync_info.canvas_filename)
                            _disp_raw = unquote_plus(sync_info.canvas_filename)
                            _name, _ext = os.path.splitext(_disp_raw)
                            _ext_clean = f" <del>{_ext[1:].upper()}</del>" if _ext else ""
                            st.markdown(f"<div style='color: rgba(255, 255, 255, 0.6); font-size: 16px; line-height: 1.6; padding: 3px 0 3px 2px; display: flex; align-items: center;'>{_name}{_ext_clean}</div>", unsafe_allow_html=True)

            # Ignored files Bucket
            if hasattr(result, 'ignored_files') and result.ignored_files:
                is_ignored_open = st.session_state.get('keep_ignored_open', False)
                with st.container(key=f"cat_ignored_{pair['course_id']}"):
                    with st.expander(f"Ignored Files", expanded=is_ignored_open):
                        st.session_state['keep_ignored_open'] = False
                        st.button("Restore All Ignored Files", key=f"restore_all_{pair['course_id']}", use_container_width=True, on_click=handle_restore_all, args=(idx,))
                        st.caption("These files are safely ignored and will not be synced.")
                        with st.container(key=f"sync_review_file_list_{idx}_ign"):
                            for sync_info in result.ignored_files:
                                icon = get_file_icon(sync_info.canvas_filename)
                                col1, col2 = st.columns([0.85, 0.15], vertical_alignment="center")
                                with col1:
                                    _disp_raw = unquote_plus(sync_info.canvas_filename)
                                    _name, _ext = os.path.splitext(_disp_raw)
                                    _ext_clean = f" <del>{_ext[1:].upper()}</del>" if _ext else ""
                                    st.markdown(f"<div style='color: rgba(255, 255, 255, 0.6); font-size: 16px; line-height: 1.6; padding: 3px 0 3px 2px; display: flex; align-items: center;'>{_name}{_ext_clean}</div>", unsafe_allow_html=True)
                                with col2:
                                    st.button("\u200b", key=f"restitem_{pair['course_id']}_{sync_info.canvas_file_id}", help="Restore this file to the sync list above", on_click=handle_restore, args=(idx, sync_info))
            
        # Inject 20px gap BETWEEN courses, outside the course's content container
        st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)

    # --- Action buttons (Back left, Sync right) ---
    total_active_files = sum(len(pd['result'].new_files) + len(pd['result'].updated_files) + len(pd['result'].missing_files) + len(pd['result'].locally_deleted_files) for pd in all_results)

    # Count only the files the user has actually checked
    total_selected_files = 0
    for pd in all_results:
        cid = pd['pair']['course_id']
        result = pd['result']
        total_selected_files += sum(1 for f in result.new_files if st.session_state.get(f'sync_new_{cid}_{f.id}', True))
        total_selected_files += sum(1 for f, _ in result.updated_files if st.session_state.get(f'sync_upd_{cid}_{f.id}', True))
        total_selected_files += sum(1 for si in result.missing_files if st.session_state.get(f'sync_miss_{cid}_{si.canvas_file_id}', False))
        total_selected_files += sum(1 for si in result.locally_deleted_files if st.session_state.get(f'sync_locdel_{cid}_{si.canvas_file_id}', False))

    if total_active_files == 0:
        st.success("All pending files have been addressed or ignored. You are fully up to date!")
        if st.button("Done - Return to Front Page", type="primary", use_container_width=True):
            cleanup_sync_state()
            st.rerun()
    else:

        col_back, col_sync, _ = st.columns([1, 1.2, 5])
        with col_sync:
            with st.container(key="btn_sync_selected"):
                sync_label = f'Sync & Download {total_selected_files} {"file" if total_selected_files == 1 else "files"}'
                if st.button(sync_label, type="primary", use_container_width=True, disabled=total_selected_files == 0):
                    # Collect selections
                    sync_selections = []
                    for idx, res_data in enumerate(all_results):
                        result = res_data['result']
                        cid = res_data['pair']['course_id']
                        selected_new = [
                            f for f in result.new_files
                            if st.session_state.get(f'sync_new_{cid}_{f.id}', True)
                        ]
                        selected_upd = [
                            f for f, _ in result.updated_files
                            if st.session_state.get(f'sync_upd_{cid}_{f.id}', True)
                        ]
                        selected_miss = [
                            si for si in result.missing_files
                            if st.session_state.get(f'sync_miss_{cid}_{si.canvas_file_id}', False)
                        ]
                        selected_locdel = [
                            si for si in result.locally_deleted_files
                            if st.session_state.get(f'sync_locdel_{cid}_{si.canvas_file_id}', False)
                        ]
                        # Combine both missing and locally deleted files that the user opted to redownload
                        selected_miss.extend(selected_locdel)

                        sync_selections.append({
                            'pair_idx': idx,
                            'res_data': res_data,
                            'new': selected_new,
                            'updates': selected_upd,
                            'redownload': selected_miss,
                            'ignore': [], # Let it pass empty, ignore was handled by immediate DB updates
                        })

                    # Total count & size for confirmation
                    total_count = sum(len(s['new']) + len(s['updates']) + len(s['redownload']) for s in sync_selections)
                    # Compute total byte size — new and updated CanvasFileInfo have .size,
                    # redownload items are SyncInfo; look up their size from canvas_files
                    total_bytes = 0
                    for s in sync_selections:
                        total_bytes += sum(getattr(f, 'size', 0) or 0 for f in s['new'])
                        total_bytes += sum(getattr(f, 'size', 0) or 0 for f, info in s['updates'])

                        # For redownloads, we need to map back to the Canvas file to get the real size (SyncFileInfo lacks size)
                        cfmap = {str(f.id): f for f in s['res_data']['canvas_files']}
                        for si in s['redownload']:
                            cf = cfmap.get(str(si.canvas_file_id))
                            total_bytes += (getattr(cf, 'size', 0) or getattr(si, 'original_size', 0) or 0)

                    if total_count == 0:
                        st.info('Nothing to sync - all files are up to date!')
                        st.stop()

                    # Disk space check (use first pair's folder)
                    first_folder = sync_selections[0]['res_data']['pair']['local_folder']
                    has_space, avail_mb, total_mb = check_disk_space(first_folder, required_bytes=total_bytes)
                    if not has_space:
                        st.error('Insufficient disk space on the target drive. Need at least 1 GB free to proceed safely.')
                        st.stop()

                    folders_count = len(set(
                        s['res_data']['pair']['local_folder'] for s in sync_selections
                        if s['new'] or s['updates'] or s['redownload']
                    ))

                    # Extract destination folder from the first selection
                    dest_folder = "Multiple folders"
                    if folders_count == 1:
                        # Find the single folder used
                        for s in sync_selections:
                            if s['new'] or s['updates'] or s['redownload']:
                                dest_folder = short_path(s['res_data']['pair']['local_folder'])
                                break

                    on_confirm_sync(sync_selections, total_count, format_file_size(total_bytes), folders_count, avail_mb, total_mb, dest_folder, total_bytes)

        with col_back:
            if st.button('Back', use_container_width=True):
                cleanup_sync_state()
                st.rerun()


def inject_dynamic_sync_review_css():
    """Injects dynamic CSS for the sync review page (e.g. counters).
    Must be called at the top of the orchestrator to prevent DOM flashing.
    """
    import streamlit as st
    import theme
    all_results = st.session_state.get('sync_analysis_results', [])
    if not all_results:
        return

    css_blocks = []
    for res_data in all_results:
        pair = res_data['pair']
        result = res_data['result']
        cid = pair['course_id']
        
        if result.new_files:
            total_new = len(result.new_files)
            selected_new = sum(1 for f in result.new_files if st.session_state.get(f"sync_new_{cid}_{f.id}", True))
            css_blocks.append(f"""
            div[class*="st-key-cat_new_{cid}"] div[data-testid="stExpander"] details summary p::after {{
                content: "\\00a0\\00a0 ({selected_new} / {total_new} selected)";
                color: {theme.TEXT_SECONDARY};
                font-weight: normal; font-size: 0.9rem;
            }}""")
            
        if result.updated_files:
            total_upd = len(result.updated_files)
            selected_upd = sum(1 for f, _ in result.updated_files if st.session_state.get(f"sync_upd_{cid}_{f.id}", True))
            css_blocks.append(f"""
            div[class*="st-key-cat_update_{cid}"] div[data-testid="stExpander"] details summary p::after {{
                content: "\\00a0\\00a0 ({selected_upd} / {total_upd} selected)";
                color: {theme.TEXT_SECONDARY}; font-weight: normal; font-size: 0.9rem;
            }}""")
            
        if result.missing_files:
            total_miss = len(result.missing_files)
            selected_miss = sum(1 for f in result.missing_files if st.session_state.get(f"sync_miss_{cid}_{f.canvas_file_id}", True))
            css_blocks.append(f"""
            div[class*="st-key-cat_missing_{cid}"] div[data-testid="stExpander"] details summary p::after {{
                content: "\\00a0\\00a0 ({selected_miss} / {total_miss} selected)"; color: {theme.TEXT_SECONDARY}; font-weight: normal; font-size: 0.9rem;
            }}""")
            
        if result.locally_deleted_files:
            total_locdel = len(result.locally_deleted_files)
            selected_locdel = sum(1 for f in result.locally_deleted_files if st.session_state.get(f"sync_locdel_{cid}_{f.canvas_file_id}", True))
            css_blocks.append(f"""
            div[class*="st-key-cat_deleted_local_{cid}"] div[data-testid="stExpander"] details summary p::after {{
                content: "\\00a0\\00a0 ({selected_locdel} / {total_locdel} selected)"; color: {theme.TEXT_SECONDARY}; font-weight: normal; font-size: 0.9rem;
            }}""")
            
        if result.deleted_on_canvas:
            total_del_canvas = len(result.deleted_on_canvas)
            css_blocks.append(f"""
            div[class*="st-key-cat_deleted_canvas_{cid}"] div[data-testid="stExpander"] details summary p::after {{
                content: "\\00a0\\00a0 ({total_del_canvas}) ignored"; color: {theme.TEXT_SECONDARY}; font-weight: normal; font-size: 0.9rem;
            }}""")

        has_ignored_files = hasattr(result, 'ignored_files') and bool(result.ignored_files)
        if has_ignored_files:
            ignored_count = len(result.ignored_files)
            css_blocks.append(f"""
            div[class*="st-key-cat_ignored_{cid}"] div[data-testid="stExpander"] details summary p::after {{
                content: "\\00a0\\00a0 ({ignored_count})"; 
                color: {theme.TEXT_SECONDARY}; 
                font-weight: normal; 
                font-size: 0.9rem;
            }}
            /* Perfect symmetrical divider above Ignored Files container */
            div[class*="st-key-cat_ignored_{cid}"] {{
                border-top: 1px solid rgba(255, 255, 255, 0.25) !important;
                padding-top: 16px !important;
            }}
            /* Slight tonal background diff for the Exact expander header */
            div[class*="st-key-cat_ignored_{cid}"] div[data-testid="stExpander"] details summary {{
                background-color: rgba(255, 255, 255, 0.01) !important;
                border-radius: 8px !important;
            }}""")

    css_blocks.append("""
    div.st-key-btn_sync_selected button {
        background-color: #1f77b4 !important;
        border: none !important;
        color: #ffffff !important;
        box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3) !important;
        transition: background-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
    }
    div.st-key-btn_sync_selected button:hover:not(:disabled) {
        background-color: #2b8cbe !important;
        box-shadow: 0 4px 15px rgba(31, 119, 180, 0.2), inset 0 1px 1px rgba(255, 255, 255, 0.4) !important;
        color: #ffffff !important;
    }
    div.st-key-btn_sync_selected button:disabled {
        background-color: #3a3a3a !important;
        color: #6b6b6b !important;
        box-shadow: none !important;
        border: 1px solid #4a4a4a !important;
    }
    """)

    if css_blocks:
        st.html(f"<style>{''.join(css_blocks)}</style>")
