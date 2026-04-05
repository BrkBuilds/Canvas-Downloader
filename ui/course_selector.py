"""
ui.course_selector — Shared course selection components + Step 1 for Download mode.

Shared Components (imported by sync_dialogs.py, hub_dialog.py):
  - ``inject_course_selector_css()`` — Premium CSS for CBS filter trays.
  - ``render_cbs_filters()``         — CBS toggle + filter criteria.
  - ``render_course_list()``         — Course checkbox list (multi or single select).

Download-specific:
  - ``render_course_selector()``     — Full Step 1 page.
"""

from __future__ import annotations

import streamlit as st

import theme
from ui_helpers import (
    esc,
    get_course_display_parts,
    parse_cbs_metadata,
    render_download_wizard,
    get_base64_image,
)


# ═══════════════════════════════════════════════════════════════════════
# Shared Components — reused by Download, Sync Dialog, and Hub Dialog
# ═══════════════════════════════════════════════════════════════════════

# ── SVG data-URI constants (icon color variants) ──────────────────────
_STAR_BLUE = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 24 24' fill='%2338bdf8'%3E%3Cpath d='M11.99 2C11.53 "
    "2 11.08 2.24 10.85 2.69L8.6 7.51L3.38 8.16C2.36 8.29 1.95 9.56 "
    "2.7 10.25L6.61 13.88L5.56 19.01C5.35 19.98 6.42 20.76 7.3 "
    "20.25L11.99 17.61L16.68 20.25C17.56 20.76 18.63 19.98 18.42 "
    "19.01L17.37 13.88L21.28 10.25C22.03 9.56 21.62 8.29 20.6 "
    "8.16L15.38 7.51L13.13 2.69C12.9 2.24 12.45 2 11.99 2Z'"
    "/%3E%3C/svg%3E")
_STAR_GREY = _STAR_BLUE.replace("%2338bdf8", "%236b7280")

_LIST_BLUE = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 512 512'%3E"
    "%3Crect x='48' y='52' width='96' height='96' rx='24' fill='%2338bdf8'/%3E"
    "%3Crect x='184' y='64' width='280' height='72' rx='36' fill='%2338bdf8'/%3E"
    "%3Crect x='48' y='208' width='96' height='96' rx='24' fill='%2338bdf8'/%3E"
    "%3Crect x='184' y='220' width='280' height='72' rx='36' fill='%2338bdf8'/%3E"
    "%3Crect x='48' y='364' width='96' height='96' rx='24' fill='%2338bdf8'/%3E"
    "%3Crect x='184' y='376' width='280' height='72' rx='36' fill='%2338bdf8'/%3E"
    "%3C/svg%3E")
_LIST_GREY = _LIST_BLUE.replace("%2338bdf8", "%236b7280")


def inject_course_selector_css():
    """Inject premium CSS for CBS filter containers, course lists,
    and the favorites pill toggle.

    Uses wildcard attribute selectors so the same stylesheet governs
    every instance regardless of namespace.
    """
    st.markdown(f"""<style>
    /* ── Premium Elevated Tray: CBS Filter Container ────────── */
    div[class*="st-key-cbs_container_"] {{
        background-color: rgba(255, 255, 255, 0.02) !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 8px !important;
        margin-top: -5px !important;
        margin-bottom: 5px !important;
    }}
    /* ── CBS Filter Tags: Subtle blue highlight ──────────────── */
    div[class*="st-key-cbs_container_"] span[data-baseweb="tag"] {{
        background-color: rgba(56, 189, 248, 0.15) !important;
        border: 1px solid rgba(56, 189, 248, 0.3) !important;
        color: #e2e8f0 !important;
    }}
    </style>""", unsafe_allow_html=True)


def render_favorites_pill(namespace: str, default_favorites: bool = True) -> bool:
    """Render a segmented favorites / all-courses toggle with icons.

    Uses the proven 'Native Button Segmented Control' architecture
    (see ``download_settings.py`` ``_get_sec_org_segmented_css``).

    Args:
        namespace: Unique key prefix (e.g. ``'dl'``, ``'sync_d'``, ``'hub_cs'``).
        default_favorites: Initial selection on first render.

    Returns:
        ``True`` if *Favorites Only* is selected.
    """
    # ── Session state ──────────────────────────────────────────
    state_key = f"fav_mode_{namespace}"
    if state_key not in st.session_state:
        st.session_state[state_key] = "favorites" if default_favorites else "all"

    active_key = st.session_state[state_key]          # "favorites" | "all"

    # ── Dynamic icon URLs (blue when active, grey otherwise) ──
    star_url = _STAR_BLUE if active_key == "favorites" else _STAR_GREY
    list_url = _LIST_BLUE if active_key == "all" else _LIST_GREY

    # ── HOISTED CSS (Section 8 guardrail: inject BEFORE buttons) ─
    st.markdown(f"""<style>
    /* ── Outer tray (border=True used purely for st-key- class) ── */
    div[class*="st-key-fav_seg_"] {{
        background-color: rgba(0, 0, 0, 0.25) !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
        border-radius: 12px !important;
        padding: 4px !important;
        margin-top: 2px !important;
        max-width: 380px !important;
    }}
    div[class*="st-key-fav_seg_"] [data-testid="stHorizontalBlock"] {{
        gap: 4px !important;
    }}
    /* Stretch columns for equal height */
    div[class*="st-key-fav_seg_"] [data-testid="column"] > div,
    div[class*="st-key-fav_seg_"] div[data-testid="stButton"],
    div[class*="st-key-fav_seg_"] button {{
        height: 100% !important;
    }}

    /* ── Base button ─────────────────────────────────────────── */
    div[class*="st-key-btn_fav_"] button {{
        background-color: transparent !important;
        border: 1px solid transparent !important;
        border-radius: 8px !important;
        padding: 10px 16px 10px 40px !important;
        color: #a0a0a0 !important;
        opacity: 0.75 !important;
        transition: all 0.2s ease !important;
        background-repeat: no-repeat !important;
        background-position: 14px center !important;
        background-size: 18px !important;
    }}
    div[class*="st-key-btn_fav_"] button p {{
        font-size: 1rem !important;
        font-weight: 500 !important;
        color: inherit !important;
    }}

    /* ── Icon assignment (dynamic: blue=active, grey=inactive) ── */
    div[class*="st-key-btn_fav_favorites"] button {{
        background-image: url("{star_url}") !important;
    }}
    div[class*="st-key-btn_fav_all"] button {{
        background-image: url("{list_url}") !important;
    }}

    /* ── Hover (inactive buttons) ────────────────────────────── */
    div[class*="st-key-btn_fav_"] button:hover {{
        background-color: rgba(255, 255, 255, 0.05) !important;
        border-color: rgba(56, 189, 248, 0.3) !important;
        opacity: 1 !important;
        color: #ffffff !important;
    }}
    /* Hover always shows blue icons */
    div[class*="st-key-btn_fav_favorites"] button:hover {{
        background-image: url("{_STAR_BLUE}") !important;
    }}
    div[class*="st-key-btn_fav_all"] button:hover {{
        background-image: url("{_LIST_BLUE}") !important;
    }}

    /* ── Active state ────────────────────────────────────────── */
    div.st-key-btn_fav_{active_key}_{namespace} button {{
        background-color: rgba(56, 189, 248, 0.1) !important;
        border: 1px solid rgba(56, 189, 248, 0.3) !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25) !important;
        opacity: 1 !important;
        color: #ffffff !important;
    }}
    /* Specificity shield — protect active from hover degradation */
    div.st-key-btn_fav_{active_key}_{namespace} button:hover {{
        background-color: rgba(56, 189, 248, 0.15) !important;
        border-color: rgba(56, 189, 248, 0.4) !important;
        opacity: 1 !important;
        color: #ffffff !important;
    }}
    </style>""", unsafe_allow_html=True)

    # ── "Show:" label ──────────────────────────────────────────
    st.markdown(
        "<p style='font-size: 0.9rem; font-weight: 600; color: #cbd5e1; "
        "margin-top: 0px; margin-bottom: 2px;'>Show:</p>",
        unsafe_allow_html=True
    )

    # ── Callbacks ──────────────────────────────────────────────
    def _set_fav_mode(mode):
        st.session_state[state_key] = mode

    # ── Buttons (proven segmented control pattern) ─────────────
    with st.container(border=True, key=f"fav_seg_{namespace}"):
        col_fav, col_all = st.columns(2, gap="small")
        with col_fav:
            st.button("Favorites Only",
                      key=f"btn_fav_favorites_{namespace}",
                      use_container_width=True,
                      on_click=_set_fav_mode, args=("favorites",))
        with col_all:
            st.button("All Courses",
                      key=f"btn_fav_all_{namespace}",
                      use_container_width=True,
                      on_click=_set_fav_mode, args=("all",))

    return st.session_state[state_key] == "favorites"


def render_cbs_filters(courses: list, namespace: str) -> list:
    """Render CBS toggle + filter criteria and return the filtered course list.

    Args:
        courses: Canvas course objects to filter.
        namespace: Unique prefix for widget keys (e.g. ``'dl'``, ``'sync_d'``).

    Returns:
        Filtered list of courses (unchanged if CBS filters are disabled globally).
    """
    # Gatekeep: if CBS filters are disabled globally, bypass entirely
    if not st.session_state.get('enable_cbs_filters', False):
        return list(courses)

    show_filters = st.toggle('CBS Filters', key=f"{namespace}_show_cbs_filters")

    filtered_courses = list(courses)

    if show_filters:
        course_meta = {}
        all_types = set()
        all_semesters = set()
        all_years = set()

        for c in courses:
            meta = parse_cbs_metadata(getattr(c, 'name', ''))
            course_meta[c.id] = meta
            if meta['type']: all_types.add(meta['type'])
            if meta['semester']: all_semesters.add(meta['semester'])
            if meta['year_full']: all_years.add(meta['year_full'])

        with st.container(border=True, key=f"cbs_container_{namespace}"):
            c1, c2, c3 = st.columns(3)
            with c1:
                sel_types = st.multiselect(
                    'Class Type', options=sorted(list(all_types)),
                    key=f"{namespace}_cbs_type")
            with c2:
                sel_semesters = st.multiselect(
                    'Semester', options=sorted(list(all_semesters)),
                    key=f"{namespace}_cbs_sem")
            with c3:
                sel_years = st.multiselect(
                    'Year', options=sorted(list(all_years), reverse=True),
                    key=f"{namespace}_cbs_year")

        if sel_types or sel_semesters or sel_years:
            temp_filtered = []
            for c in courses:
                meta = course_meta[c.id]
                match_type = meta['type'] in sel_types if sel_types else True
                match_sem = meta['semester'] in sel_semesters if sel_semesters else True
                match_year = meta['year_full'] in sel_years if sel_years else True
                if match_type and match_sem and match_year:
                    temp_filtered.append(c)
            filtered_courses = temp_filtered

    return filtered_courses


def render_course_list(
    courses: list,
    namespace: str,
    multi_select: bool = True,
) -> list | None:
    """Render a course selection list with checkboxes.

    Sorts courses alphabetically, then renders each with a checkbox and
    a styled HTML label showing the clean name + dimmed course code.

    Args:
        courses: Pre-filtered courses to display.
        namespace: Unique key prefix to prevent ``DuplicateWidgetID``.
        multi_select: ``True`` for multi-checkbox (Download);
                      ``False`` for radio-like single select (Sync/Hub).

    Multi-select:
        Reads/writes ``st.session_state['selected_course_ids']``.
        Returns the updated list of selected course IDs.

    Single-select:
        Reads/writes ``st.session_state['{namespace}_selected_id']``.
        Returns ``None``.
    """
    if not courses:
        st.info('No courses match the selected filters.')
        if multi_select:
            return []
        else:
            return None

    sorted_courses = sorted(
        courses, key=lambda c: (getattr(c, 'name', '') or '').lower())

    if multi_select:
        return _render_multi_select_list(sorted_courses, namespace)
    else:
        _render_single_select_list(sorted_courses, namespace)
        return None


def _render_multi_select_list(courses: list, namespace: str) -> list:
    """Multi-select checkbox list (Download mode)."""
    selected_ids = st.session_state.get('selected_course_ids', [])
    visible_ids = {c.id for c in courses}
    new_selected_ids = []

    # Preserve off-screen selections (hidden by CBS filters)
    for sid in selected_ids:
        if sid not in visible_ids:
            new_selected_ids.append(sid)

    for course in courses:
        base_name, code = get_course_display_parts(course)
        display_str = f"{base_name} ({code})" if code else base_name
        code_html = (
            f' <span style="color:{theme.TEXT_DIM}; font-size:0.9em;">'
            f'({esc(code)})</span>' if code else ''
        )

        chk_key = f"{namespace}_chk_{course.id}"

        c1, c2 = st.columns([0.02, 0.98], gap="small")
        with c1:
            if chk_key not in st.session_state:
                checked = st.checkbox(
                    display_str, value=(course.id in selected_ids),
                    key=chk_key, label_visibility="collapsed")
            else:
                checked = st.checkbox(
                    display_str, key=chk_key, label_visibility="collapsed")

        with c2:
            st.markdown(
                f'<div style="margin-top: 8px;">'
                f'<strong>{esc(base_name)}</strong>{code_html}'
                f'</div>',
                unsafe_allow_html=True
            )

        if checked:
            new_selected_ids.append(course.id)

    st.session_state['selected_course_ids'] = new_selected_ids
    return new_selected_ids


def _render_single_select_list(courses: list, namespace: str):
    """Single-select radio-like checkbox list (Sync / Hub dialogs)."""
    selected_key = f"{namespace}_selected_id"

    for course in courses:
        base_name, code = get_course_display_parts(course)
        code_html = (
            f' <span style="color:{theme.TEXT_DIM}; font-size:0.9em;">'
            f'({esc(code)})</span>' if code else ''
        )

        is_checked = (st.session_state.get(selected_key) == course.id)
        chk_key = f"{namespace}_chk_{course.id}"

        # Force widget state to match single-source-of-truth before render
        st.session_state[chk_key] = is_checked

        def _on_toggle(cid, ns=namespace):
            sk = f"{ns}_selected_id"
            ck = f"{ns}_chk_{cid}"
            if st.session_state.get(ck):
                st.session_state[sk] = cid
            elif st.session_state.get(sk) == cid:
                st.session_state[sk] = None

        c1, c2 = st.columns([0.03, 0.97], gap="small")
        with c1:
            st.checkbox(
                "Select", key=chk_key,
                on_change=_on_toggle, args=(course.id,),
                label_visibility="collapsed"
            )
        with c2:
            st.markdown(
                f'<div style="margin-top: -2px; width: 100%;">'
                f'<strong>{esc(base_name)}</strong>{code_html}'
                f'</div>',
                unsafe_allow_html=True
            )


# ═══════════════════════════════════════════════════════════════════════
# Download Mode — Step 1: Select Courses
# ═══════════════════════════════════════════════════════════════════════

def render_course_selector(fetch_courses_fn):
    """Render the Step 1 course selection page for Download mode.

    Args:
        fetch_courses_fn: The ``@st.cache_data``-wrapped ``fetch_courses()``
            function from app.py.
    """
    inject_course_selector_css()
    render_download_wizard(st, 1)
    st.markdown(
        f'<div class="step-header">{"Step 1: Select Courses"}</div>',
        unsafe_allow_html=True)

    # --- Select All / Clear button icons (download-mode specific) ---
    b64_select_all = get_base64_image("assets/icon_select_all.png")
    b64_clear = get_base64_image("assets/icon_clear_selection.png")

    st.markdown(f"""
    <style>
    /* Button base styles */
    div.st-key-btn_course_select_all button,
    div.st-key-btn_course_clear_selection button {{
        background-color: rgba(255, 255, 255, 0.03) !important;
        border-radius: 8px !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        min-height: 38px !important;
        height: 38px !important;
        padding-left: 16px !important;
        padding-right: 16px !important;
    }}
    div.st-key-btn_course_select_all button:hover,
    div.st-key-btn_course_clear_selection button:hover {{
        background-color: rgba(255, 255, 255, 0.1) !important;
        border-color: rgba(255, 255, 255, 0.15) !important;
    }}
    div.st-key-btn_course_select_all button > div,
    div.st-key-btn_course_select_all button div[data-testid="stMarkdownContainer"],
    div.st-key-btn_course_clear_selection button > div,
    div.st-key-btn_course_clear_selection button div[data-testid="stMarkdownContainer"] {{
        width: 100% !important;
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
    }}
    div.st-key-btn_course_select_all button p,
    div.st-key-btn_course_clear_selection button p {{
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 12px !important;
        margin: 0 !important;
        width: 100% !important;
        line-height: 1 !important;
        white-space: nowrap !important;
    }}
    div.st-key-btn_course_select_all button p::before,
    div.st-key-btn_course_clear_selection button p::before {{
        content: "" !important;
        display: inline-block !important;
        width: 20px !important;
        height: 20px !important;
        background-size: contain !important;
        background-repeat: no-repeat !important;
        background-position: center !important;
        flex-shrink: 0 !important;
    }}
    div.st-key-btn_course_select_all button p::before {{
        background-image: url('data:image/png;base64,{b64_select_all}') !important;
    }}
    div.st-key-btn_course_clear_selection button p::before {{
        background-image: url('data:image/png;base64,{b64_clear}') !important;
    }}
    </style>
    """, unsafe_allow_html=True)

    # --- Favorites / All Courses pill toggle ---
    favorites_only = render_favorites_pill("dl")

    courses = fetch_courses_fn(
        st.session_state['api_token'],
        st.session_state['api_url'], favorites_only)

    if not courses:
        st.warning('No courses found.')
        st.stop()

    # --- CBS Filters (centralized) ---
    filtered_courses = render_cbs_filters(courses, "dl")

    # --- Select All / Clear buttons ---
    visible_ids = {c.id for c in filtered_courses}

    with st.container(key="action_buttons_row"):
        select_all_clicked = st.button('Select All', key="btn_course_select_all")
        clear_sel_clicked = st.button('Clear Selection', key="btn_course_clear_selection")

    if select_all_clicked:
        current_ids = set(st.session_state['selected_course_ids'])
        new_ids = current_ids.union(visible_ids)
        st.session_state['selected_course_ids'] = list(new_ids)
        for cid in visible_ids:
            st.session_state[f"dl_chk_{cid}"] = True
        st.rerun()

    if clear_sel_clicked:
        st.session_state['selected_course_ids'] = []
        for c in courses:
            st.session_state[f"dl_chk_{c.id}"] = False
        st.rerun()

    # --- Course list (centralized) ---
    render_course_list(filtered_courses, "dl", multi_select=True)

    # --- Continue ---
    st.markdown("---")
    error_container = st.empty()

    c1, c2 = st.columns([1, 3])
    with c1:
        continue_clicked = st.button('Continue', type="primary", use_container_width=True)

    if continue_clicked:
        if not st.session_state['selected_course_ids']:
            error_container.error('Please select at least one course.')
        else:
            st.session_state['step'] = 2
            st.rerun()
