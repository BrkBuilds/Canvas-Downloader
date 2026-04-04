"""
ui.course_selector — Step 1 course selection for Download mode.

Extracted from ``app.py`` (Phase 6).
Strict physical move — NO logic changes.

Contains:
  - ``render_course_selector()`` — full Step 1: radio filter, CBS filters,
    select all / clear, course checkbox list, continue button.
"""

from __future__ import annotations

import streamlit as st

import theme
from ui_helpers import esc, friendly_course_name, parse_cbs_metadata, render_download_wizard


def render_course_selector(fetch_courses_fn):
    """Render the Step 1 course selection page for Download mode.

    Args:
        fetch_courses_fn: The ``@st.cache_data``-wrapped ``fetch_courses()``
            function from app.py.
    """
    render_download_wizard(st, 1)
    st.markdown(f'<div class="step-header">{"Step 1: Select Courses"}</div>', unsafe_allow_html=True)

    filter_mode = st.radio(
        'Show:',
        ['Favorites Only', 'All Courses'],
        horizontal=True
    )
    favorites_only = (filter_mode == 'Favorites Only')

    courses = fetch_courses_fn(st.session_state['api_token'], st.session_state['api_url'], favorites_only)

    if not courses:
        st.warning('No courses found.')
        st.stop()

    # CBS Metadata Filters
    show_filters = st.toggle(f'Enable CBS Filters', key="dl_show_cbs_filters")

    filtered_courses = list(courses)

    if show_filters:
        course_meta = {}
        all_types = set()
        all_semesters = set()
        all_years = set()

        for c in courses:
            full_name_str = f"{c.name} ({c.course_code})" if hasattr(c, 'course_code') else c.name
            meta = parse_cbs_metadata(full_name_str)
            course_meta[c.id] = meta
            if meta['type']: all_types.add(meta['type'])
            if meta['semester']: all_semesters.add(meta['semester'])
            if meta['year_full']: all_years.add(meta['year_full'])

        with st.container(border=True, key="dl_cbs_container"):
            st.markdown(f"**{'Filter Criteria'}**")
            c1, c2, c3 = st.columns(3)
            with c1:
                sel_types = st.multiselect('Class Type', options=sorted(list(all_types)), key="dl_cbs_type")
            with c2:
                sel_semesters = st.multiselect('Semester', options=sorted(list(all_semesters)), key="dl_cbs_sem")
            with c3:
                sel_years = st.multiselect('Year', options=sorted(list(all_years), reverse=True), key="dl_cbs_year")

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

            if not filtered_courses:
                st.info(f'No courses match the selected filters.')

    # Select All / Clear buttons
    visible_ids = {c.id for c in filtered_courses}

    col_sel, col_clear, _ = st.columns([1, 1, 5])

    with col_sel:
        select_all_clicked = st.button('Select All', use_container_width=True)
    with col_clear:
        clear_sel_clicked = st.button('Clear Selection', use_container_width=True)

    if select_all_clicked:
        current_ids = set(st.session_state['selected_course_ids'])
        new_ids = current_ids.union(visible_ids)
        st.session_state['selected_course_ids'] = list(new_ids)
        for cid in visible_ids:
            st.session_state[f"chk_{cid}"] = True
        st.rerun()

    if clear_sel_clicked:
        st.session_state['selected_course_ids'] = []
        for c in courses:
            st.session_state[f"chk_{c.id}"] = False
        st.rerun()

    # Error container for validation messages
    error_container = st.empty()

    # ── Course list with checkboxes ─────────────────────────────────
    selected_ids = st.session_state['selected_course_ids']
    new_selected_ids = []

    filtered_ids = {fc.id for fc in filtered_courses}

    # Sorting: selected first, then alphabetical
    saved_selection_set = set(st.session_state['selected_course_ids'])
    filtered_courses.sort(key=lambda c: (c.id not in saved_selection_set, (c.name or "").lower()))

    for sid in selected_ids:
        if sid not in filtered_ids:
            new_selected_ids.append(sid)

    for course in filtered_courses:
        full_name_str = f"{esc(course.name)} ({course.course_code})" if hasattr(course, 'course_code') else course.name
        friendly = friendly_course_name(full_name_str)

        checkbox_key = f"chk_{course.id}"

        c1, c2 = st.columns([0.035, 0.965])

        with c1:
            is_checked = False
            if checkbox_key in st.session_state:
                pass
            else:
                if course.id in selected_ids:
                    is_checked = True

            checked = False
            if checkbox_key in st.session_state:
                checked = st.checkbox(friendly, key=checkbox_key, label_visibility="collapsed")
            else:
                checked = st.checkbox(friendly, value=is_checked, key=checkbox_key, label_visibility="collapsed")

        with c2:
            st.markdown(
                f'<div style="margin-top: 8px;">'
                f'<strong>{friendly}</strong> '
                f'<span style="color:{theme.TEXT_DIM}; font-size:0.9em;">({full_name_str})</span>'
                f'</div>',
                unsafe_allow_html=True
            )

        if checked:
            new_selected_ids.append(course.id)

    st.session_state['selected_course_ids'] = new_selected_ids

    st.markdown("---")
    if st.button('Continue', type="primary"):
        if not st.session_state['selected_course_ids']:
            error_container.error('Please select at least one course.')
        else:
            st.session_state['step'] = 2
            st.rerun()
