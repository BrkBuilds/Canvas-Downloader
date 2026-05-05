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
from ui_shared import render_help_card


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
_STAR_GREY = _STAR_BLUE.replace("%2338bdf8", "%23cbd5e1")

_LIST_BLUE = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 512 512'%3E"
    "%3Crect x='48' y='52' width='96' height='96' rx='24' fill='%2338bdf8'/%3E"
    "%3Crect x='184' y='64' width='280' height='72' rx='36' fill='%2338bdf8'/%3E"
    "%3Crect x='48' y='208' width='96' height='96' rx='24' fill='%2338bdf8'/%3E"
    "%3Crect x='184' y='220' width='280' height='72' rx='36' fill='%2338bdf8'/%3E"
    "%3Crect x='48' y='364' width='96' height='96' rx='24' fill='%2338bdf8'/%3E"
    "%3Crect x='184' y='376' width='280' height='72' rx='36' fill='%2338bdf8'/%3E"
    "%3C/svg%3E")
_LIST_GREY = _LIST_BLUE.replace("%2338bdf8", "%23cbd5e1")


def inject_course_selector_css():
    """Inject premium CSS for CBS filter containers, course lists,
    and the favorites pill toggle.

    Uses wildcard attribute selectors so the same stylesheet governs
    every instance regardless of namespace.
    """
    st.html(f"""<style>
    /* ── Premium Elevated Tray: CBS Filter Container ────────── */
    div[class*="st-key-cbs_container_"] {{
        background-color: rgba(255, 255, 255, 0.02) !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 8px !important;
        margin-top: -5px !important;
        margin-bottom: -5px !important;
    }}
    /* ── CBS Filter Tags: Subtle blue highlight ──────────────── */
    div[class*="st-key-cbs_container_"] span[data-baseweb="tag"] {{
        background-color: rgba(56, 189, 248, 0.15) !important;
        border: 1px solid rgba(56, 189, 248, 0.3) !important;
        color: #e2e8f0 !important;
    }}
    /* ── Toggle Switch ────────── */
    div[class*="st-key-"][class$="_show_cbs_filters"] {{
        margin-top: 8px !important;
        margin-bottom: 8px !important;
    }}
    </style>""")


def render_favorites_pill(namespace: str, default_favorites: bool = True, in_dialog: bool = False) -> bool:
    """Render a segmented favorites / all-courses toggle with icons.

    Uses the proven 'Native Button Segmented Control' architecture
    (see ``download_settings.py`` ``_get_sec_org_segmented_css``).

    Args:
        namespace: Unique key prefix (e.g. ``'dl'``, ``'sync_d'``, ``'hub_cs'``).
        default_favorites: Initial selection on first render.
        in_dialog: Pass ``True`` when rendering inside a dialog or SPA sub-page.
            In that context the large negative margins that compensate for the
            download-mode wizard header are incorrect and will push content into
            the dialog title area.  When ``True``, the "Show:" label and
            segmented-control container use neutral (non-negative) margins.

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

    # ── HOISTED CSS FOR SEGMENTED CONTROL LIST VIEW TOGGLE) ─
    # In dialog mode, "Show:" uses st.html (margin-bottom: 0), so fav_seg sits
    # immediately after the stVerticalBlock gap — no negative compensation needed.
    _seg_margin_top = "0px" if in_dialog else "-30px"
    # In dialog portals, Streamlit's own button CSS wins at equal specificity
    # (loaded later in the cascade). Prefix with div[role="dialog"] to boost
    # our specificity to (0,2,*) so we always win regardless of source order.
    # Download mode (in_dialog=False) uses no prefix — it works as-is.
    _bp = 'div[role="dialog"] ' if in_dialog else ''
    st.html(f"""<style>
    /* ── Outer tray (border=True used purely for st-key- class) ── */
    div[class*="st-key-fav_seg_"] {{
        background-color: rgba(0, 0, 0, 0.25) !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        border-radius: 14px !important;
        padding: 6px !important;
        margin-top: {_seg_margin_top} !important;
        max-width: 380px !important;
        box-shadow: 0 0 8px rgba(255, 255, 255, 0.025) !important;
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
    {_bp}div[class*="st-key-btn_fav_"] button {{
        background-color: transparent !important;
        border: 1px solid transparent !important;
        border-radius: 8px !important;
        color: #cbd5e1 !important;
        opacity: 0.75 !important;
        transition: all 0.2s ease !important;
        background-repeat: no-repeat !important;
        background-position: 14px center !important;
        background-size: 22px !important;
        padding-left: 42px !important;
        padding-right: 20px !important;
    }}
    {_bp}div[class*="st-key-btn_fav_"] button p {{
        font-size: 1rem !important;
        font-weight: 500 !important;
        color: inherit !important;
    }}

    /* ── Icon assignment (dynamic: blue=active, grey=inactive) ── */
    {_bp}div[class*="st-key-btn_fav_favorites"] button {{
        background-image: url("{star_url}") !important;
    }}
    {_bp}div[class*="st-key-btn_fav_all"] button {{
        background-image: url("{list_url}") !important;
    }}

    /* ── Hover (inactive buttons) ────────────────────────────── */
    {_bp}div[class*="st-key-btn_fav_"] button:hover {{
        background-color: rgba(255, 255, 255, 0.05) !important;
        border-color: transparent !important;
        opacity: 1 !important;
        color: #ffffff !important;
    }}
    /* Hover always shows blue icons */
    {_bp}div[class*="st-key-btn_fav_favorites"] button:hover {{
        background-image: url("{_STAR_BLUE}") !important;
    }}
    {_bp}div[class*="st-key-btn_fav_all"] button:hover {{
        background-image: url("{_LIST_BLUE}") !important;
    }}

    /* ── Active state ────────────────────────────────────────── */
    {_bp}div.st-key-btn_fav_{active_key}_{namespace} button {{
        background-color: rgba(56, 189, 248, 0.1) !important;
        border: 1px solid rgba(56, 189, 248, 0.3) !important;
        box-shadow: 0 0 16px rgba(0, 0, 0, 1) !important;
        opacity: 1 !important;
        color: #ffffff !important;
        padding-left: 42px !important;
        padding-right: 20px !important;
    }}
    /* Specificity shield — protect active from hover degradation */
    {_bp}div.st-key-btn_fav_{active_key}_{namespace} button:hover {{
        background-color: rgba(56, 189, 248, 0.15) !important;
        border-color: rgba(56, 189, 248, 0.4) !important;
        opacity: 1 !important;
        color: #ffffff !important;
    }}
    </style>""")

    # ── "Show:" label ──────────────────────────────────────────
    # Use st.html() (not st.markdown) so the wrapper is a stHtml element with
    # margin-bottom: 0 (per global.css rule 3). st.markdown wraps in
    # stMarkdownContainer which adds 1rem bottom ghost margin, causing large
    # visual gaps in dialog contexts where compensation margins don't apply.
    _label_margin_top = "-10px" if in_dialog else "-25px"
    _label_margin_bottom = "0px" if in_dialog else "25px"
    st.html(
        f"<p style='font-size: 0.9rem; font-weight: 600; color: #cbd5e1; "
        f"margin-top: {_label_margin_top}; margin-bottom: {_label_margin_bottom};'>Show:</p>"
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


def render_cbs_filters(courses: list, namespace: str, custom_toggle_container=None) -> list:
    """Render CBS toggle + filter criteria and return the filtered course list.

    Args:
        courses: Canvas course objects to filter.
        namespace: Unique prefix for widget keys (e.g. ``'dl'``, ``'sync_d'``).
        custom_toggle_container: Optional container to place the toggle inside.

    Returns:
        Filtered list of courses (unchanged if CBS filters are disabled globally).
    """
    # Gatekeep: if CBS filters are disabled globally, bypass entirely
    if not st.session_state.get('enable_cbs_filters', False):
        return list(courses)

    if custom_toggle_container:
        with custom_toggle_container:
            show_filters = st.toggle('CBS Filters', key=f"{namespace}_show_cbs_filters")
    else:
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
    first_item_top_offset: str = "-40px",
) -> list | None:
    """Render a course selection list with checkboxes.

    Sorts courses alphabetically, then renders each with a checkbox and
    a styled HTML label showing the clean name + dimmed course code.

    Args:
        courses: Pre-filtered courses to display.
        namespace: Unique key prefix to prevent ``DuplicateWidgetID``.
        multi_select: ``True`` for multi-checkbox (Download);
                      ``False`` for radio-like single select (Sync/Hub).
        first_item_top_offset: CSS length applied as ``margin-top`` on the
            first course's element box. Used to pull the list flush against
            whatever the caller renders directly above it (an ``<hr>`` in
            the hub/sync dialogs, the buttons-row border in download mode).
            Prefer ``rem`` units so the offset scales with the surrounding
            ``stVerticalBlock`` gap and stays correct across DPI / zoom
            levels. Pass ``"0"`` to disable the offset entirely.

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
        return _render_multi_select_list(
            sorted_courses, namespace, first_item_top_offset)
    else:
        _render_single_select_list(
            sorted_courses, namespace, first_item_top_offset)
        return None


def _render_multi_select_list(
    courses: list, namespace: str, first_item_top_offset: str = "-40px"
) -> list:
    """Multi-select checkbox list (Download mode)."""
    selected_ids = st.session_state.get('selected_course_ids', [])
    visible_ids = {c.id for c in courses}
    new_selected_ids = []

    # Preserve off-screen selections (hidden by CBS filters)
    for sid in selected_ids:
        if sid not in visible_ids:
            new_selected_ids.append(sid)

    # ――― Inject global CSS for this list ―――
    st.html(f"""<style>
    div[class*="st-key-{namespace}_chk_"] {{
        border-radius: 6px !important;
        transition: background-color 0.2s !important;
        margin-bottom: -10px !important;
        padding-top: 4px !important;
        padding-bottom: 2px !important;
        padding-left: 10px !important;
        padding-right: 10px !important;
        width: 100% !important;
        display: block !important;
    }}
    div[class*="st-key-{namespace}_chk_"]:hover {{
        background-color: rgba(255, 255, 255, 0.03) !important;
    }}
    /* Row Background when checked */
    div[class*="st-key-{namespace}_chk_"]:has(input[type="checkbox"]:checked) {{
        background-color: rgba(56, 189, 248, 0.08) !important;
    }}

    /* Make sure checkbox area fills row */
    div[class*="st-key-{namespace}_chk_"] label[data-baseweb="checkbox"] {{
        width: 100% !important;
        align-items: flex-start !important;
        cursor: pointer !important;
    }}

    /* Title Styling */
    div[class*="st-key-{namespace}_chk_"] label[data-baseweb="checkbox"] p {{
        font-size: 1.05em !important;
        font-weight: 400 !important;
        color: #ffffff !important;
        margin: 0 !important;
        line-height: 1.2 !important;
    }}

    /* Center the checkbox itself vertically with the first line */
    div[class*="st-key-{namespace}_chk_"] label[data-baseweb="checkbox"] > div:first-child {{
        margin-top: 3px !important;
    }}
    </style>""")
    st.html('<div style="padding-bottom: 1rem;"></div>')

    dynamic_css = []

    for course in courses:
        base_name, code = get_course_display_parts(course)
        code_clean = code.strip("()") if code else ""
        chk_key = f"{namespace}_chk_{course.id}"

        # Inject code subtext via CSS
        if code_clean:
            dynamic_css.append(f"""
            div.st-key-{chk_key} label[data-baseweb="checkbox"] div[data-testid="stMarkdownContainer"]::after {{
                content: "{esc(code_clean)}";
                display: block !important;
                color: #94a3b8 !important;
                font-size: 0.85em !important;
                font-weight: 400 !important;
                margin-top: -2px !important;
            }}
            """)

        # NO columns! Just st.checkbox
        if chk_key not in st.session_state:
            checked = st.checkbox(
                base_name, value=(course.id in selected_ids),
                key=chk_key)
        else:
            checked = st.checkbox(base_name, key=chk_key)

        if checked:
            new_selected_ids.append(course.id)

    if dynamic_css:
        if len(courses) > 0 and first_item_top_offset and first_item_top_offset != "0":
            f_key = f"{namespace}_chk_{courses[0].id}"
            dynamic_css.append(f"""
            div.st-key-{f_key} {{ margin-top: {first_item_top_offset} !important; }}
            """)
        st.html(f'<style>{"".join(dynamic_css)}</style>')
        st.html('<div style="padding-bottom: 1rem;"></div>')

    st.session_state['selected_course_ids'] = new_selected_ids
    return new_selected_ids


def _render_single_select_list(
    courses: list, namespace: str, first_item_top_offset: str = "-40px"
):
    """Single-select radio-like checkbox list (Sync / Hub dialogs)."""
    selected_key = f"{namespace}_selected_id"

    # ――― Inject global CSS for this list ―――
    st.html(f"""<style>
    div[class*="st-key-{namespace}_chk_"] {{
        border-radius: 6px !important;
        transition: background-color 0.2s !important;
        margin-bottom: -10px !important;
        padding-top: 4px !important;
        padding-bottom: 2px !important;
        padding-left: 10px !important;
        padding-right: 10px !important;
        width: 100% !important;
        display: block !important;
    }}
    div[class*="st-key-{namespace}_chk_"]:hover {{
        background-color: rgba(255, 255, 255, 0.03) !important;
    }}
    /* Row Background when checked */
    div[class*="st-key-{namespace}_chk_"]:has(input[type="checkbox"]:checked) {{
        background-color: rgba(56, 189, 248, 0.08) !important;
    }}

    /* Make sure checkbox area fills row */
    div[class*="st-key-{namespace}_chk_"] label[data-baseweb="checkbox"] {{
        width: 100% !important;
        align-items: flex-start !important;
        cursor: pointer !important;
    }}

    /* Title Styling */
    div[class*="st-key-{namespace}_chk_"] label[data-baseweb="checkbox"] p {{
        font-size: 1.05em !important;
        font-weight: 400 !important;
        color: #e2e8f0 !important;
        margin: 0 !important;
        line-height: 1.2 !important;
    }}

    /* Center the checkbox itself vertically with the first line */
    div[class*="st-key-{namespace}_chk_"] label[data-baseweb="checkbox"] > div:first-child {{
        margin-top: 3px !important;
    }}
    </style>""")
    st.html('<div style="padding-bottom: 1rem;"></div>')

    dynamic_css = []

    for course in courses:
        base_name, code = get_course_display_parts(course)
        code_clean = code.strip("()") if code else ""
        chk_key = f"{namespace}_chk_{course.id}"

        if code_clean:
            dynamic_css.append(f"""
            div.st-key-{chk_key} label[data-baseweb="checkbox"] div[data-testid="stMarkdownContainer"]::after {{
                content: "{esc(code_clean)}";
                display: block !important;
                color: #94a3b8 !important;
                font-size: 0.72em !important;
                font-weight: 400 !important;
                margin-top: -2px !important;
            }}
            """)

        is_checked = (st.session_state.get(selected_key) == course.id)
        st.session_state[chk_key] = is_checked

        def _on_toggle(cid, ns=namespace):
            sk = f"{ns}_selected_id"
            ck = f"{ns}_chk_{cid}"
            if st.session_state.get(ck):
                st.session_state[sk] = cid
            elif st.session_state.get(sk) == cid:
                st.session_state[sk] = None

        st.checkbox(base_name, key=chk_key, on_change=_on_toggle, args=(course.id,))

    if dynamic_css:
        if len(courses) > 0 and first_item_top_offset and first_item_top_offset != "0":
            f_key = f"{namespace}_chk_{courses[0].id}"
            dynamic_css.append(f"""
            div.st-key-{f_key} {{ margin-top: {first_item_top_offset} !important; }}
            """)
        st.html(f'<style>{"".join(dynamic_css)}</style>')
        st.html('<div style="padding-bottom: 1rem;"></div>')

@st.fragment
def _course_list_section(courses: list) -> None:
    """Fragment: CBS filters + Select All/Clear + checkbox list.

    Scopes checkbox-click reruns to this fragment only, keeping the wizard
    header and page chrome stable.
    """
    filtered_courses = render_cbs_filters(courses, "dl")
    visible_ids = {c.id for c in filtered_courses}

    with st.container(key="action_btns_row", border=True):
        select_all_clicked = st.button('Select All', key="btn_course_select_all")
        clear_sel_clicked = st.button('Clear Selection', key="btn_course_clear_selection")

    if select_all_clicked:
        current_ids = set(st.session_state.get('selected_course_ids', []))
        st.session_state['selected_course_ids'] = list(current_ids.union(visible_ids))
        for cid in visible_ids:
            st.session_state[f"dl_chk_{cid}"] = True
        st.rerun(scope="fragment")

    if clear_sel_clicked:
        st.session_state['selected_course_ids'] = []
        for c in courses:
            st.session_state[f"dl_chk_{c.id}"] = False
        st.rerun(scope="fragment")

    with st.container(key="course_list_box", border=True):
        render_course_list(
            filtered_courses, "dl", multi_select=True, first_item_top_offset="-10px"
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

    # Help Card Content
    _cs_help_title = "How Course Selection Works"
    _cs_help_text = (
        "<b>Select the courses you want to download, then press Continue.</b>"
        "<br><br>"
        "<b>📦 Batch Downloading</b><br>"
        "You can download as many courses as you want at once. The application will process them sequentially.<br> "
        "All selected courses will be downloaded as separate folders (e.g. 📁 <em>Programming 101</em>, 📁 <em>History 201</em>)."
        "<br><br>"
        "<b>⭐ Favorites vs All Courses</b><br>"
        "The toggle at the top lets you filter between your favorited courses and your full course list.<br> "
        "Your favorited courses can be managed directly in Canvas.<br><br>"
        "<b>⚙️ Download Settings & Course Selection</b><br>"
        "You will configure your download settings in the next step.<br>"
        "<div style='background-color: rgba(245, 158, 11, 0.1); border-left: 3px solid #f59e0b; padding: 8px 12px; margin-top: 8px; border-radius: 0px 4px 4px 0px;'>"
        "<span style='color: #fbd38d; font-weight: 600;'>⚠️ Notice:</span> The download settings you choose in the next page, will apply to <b>ALL</b> courses selected here. <br>"
        "For example, if you enable AI Optimization, it will be applied to the entire batch. <br>"
        "If you need different settings for different courses, you must perform separate download runs."
        "</div>"
        "<hr>"
        "<b>❓ Frequently Asked Questions</b><br>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What happens if a folder with the course name already exists on my computer?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63, 217, 255, 0.05); font-size: 0.85rem; color: #d1d5db;'>"
        "The application will safely <b>merge</b> the new files into your existing folder (e.g. a previously downloaded version of the same course). "
        "It will not delete your files - only add whats missing. If a Canvas file has been updated, it will overwrite the old version, "
        "but everything else remains untouched."
        "</div>"
        "</details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Can I download all my Canvas courses at once?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63, 217, 255, 0.05); font-size: 0.85rem; color: #d1d5db;'>"
        "Yes! Just click the <b>Select All</b> button at the bottom of the course list. "
        "Note that downloading dozens of courses simultaneously might take a while depending on your internet connection."
        "</div>"
        "</details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Does this download my Assignments and Quizzes?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63, 217, 255, 0.05); font-size: 0.85rem; color: #d1d5db;'>"
        "By default, we only download <b>Files uploaded by your teacher</b>, however, in Step 2, you can enable <b>Canvas Content</b>, "
        "to automatically download your course Assignments, Quizzes, Discussions, etc. as readable documents into your course folder."
        "</div>"
        "</details>"
    )

    # Snug Header Hack — H2 + Help button on one flex row
    st.html("""
        <style>
        div.st-key-cs_title_help_row [data-testid="stHorizontalBlock"] {
            display: flex !important;
            flex-direction: row !important;
            align-items: center !important;
            gap: 0px !important;
            justify-content: flex-start !important;
        }
        div.st-key-cs_title_help_row [data-testid="column"],
        div.st-key-cs_title_help_row [data-testid="stColumn"] {
            width: auto !important;
            flex: 0 0 auto !important;
            min-width: 0px !important;
            padding: 0 !important;
        }
        div.st-key-cs_title_help_row h2 {
            margin-right: 0 !important;
            padding-right: 0 !important;
        }
        div.st-key-cs_title_help_row div[class*="st-key-course_selector_explainer_help_btn"] {
            margin-bottom: -20px !important;
            margin-top: 10px !important;
            margin-left: 0 !important;
        }
        </style>
    """)
    with st.container(key="cs_title_help_row"):
        _c1, _c2 = st.columns([1, 10])
        with _c1:
            st.markdown("<h2 style='margin: 0; white-space: nowrap;'>Select Courses</h2>", unsafe_allow_html=True)
        with _c2:
            render_help_card(
                key_prefix="course_selector",
                title=_cs_help_title,
                text_html=_cs_help_text,
                icon="💡",
                mode="button"
            )

    # Help Card Expansion (renders below the header row if open)
    render_help_card(
        key_prefix="course_selector",
        title=_cs_help_title,
        text_html=_cs_help_text,
        icon="💡",
        mode="card"
    )

    # --- Select All / Clear button icons (download-mode specific) ---
    b64_select_all = get_base64_image("assets/icon_select_all.png")
    b64_clear = get_base64_image("assets/icon_clear_selection.png")

    st.html(f"""<style>
    /* ── Action Buttons Row: reflow vertical stack → horizontal ── */
    div[data-testid="stVerticalBlock"]:has(> div.st-key-btn_course_select_all) {{
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        gap: 5px !important;
        align-items: center !important;
    }}
    /* Set shrink-to-fit for the button containers */
    div[data-testid="stVerticalBlock"]:has(> div.st-key-btn_course_select_all) > div {{
        width: auto !important;
        flex: 0 0 auto !important;
    }}
    /* Button base styles */
    div.st-key-btn_course_select_all button,
    div.st-key-btn_course_clear_selection button {{
        background-color: rgba(255, 255, 255, 0) !important;
        border-radius: 8px !important;
        border: 0px solid rgba(255, 255, 255, 0.1) !important;
        min-height: 38px !important;
        height: 38px !important;
        padding-left: 8px !important;
        padding-right: 8px !important;
        white-space: nowrap !important;
        width: auto !important;
        min-width: max-content !important;
    }}
    div.st-key-btn_course_select_all button:hover,
    div.st-key-btn_course_clear_selection button:hover {{
        background-color: rgba(255, 255, 255, 0.02) !important;
        border-color: rgba(255, 255, 255, 0.00) !important;
    }}
    div.st-key-btn_course_select_all button > div,
    div.st-key-btn_course_select_all button div[data-testid="stMarkdownContainer"],
    div.st-key-btn_course_clear_selection button > div,
    div.st-key-btn_course_clear_selection button div[data-testid="stMarkdownContainer"] {{
        width: auto !important;
        display: flex !important;
        justify-content: left !important;
        align-items: center !important;
    }}
    div.st-key-btn_course_select_all button p,
    div.st-key-btn_course_clear_selection button p {{
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 12px !important;
        margin: 0 !important;
        width: auto !important;
        line-height: 1 !important;
        white-space: nowrap !important;
    }}
    div.st-key-btn_course_select_all button p::before,
    div.st-key-btn_course_clear_selection button p::before {{
        content: "" !important;
        display: inline-block !important;
        width: 18px !important;
        height: 18px !important;
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
    /* ── Action Buttons Row container ──
       Strip the native st.container border and replace with a single
       hairline border-bottom that acts as the TOP section separator.
       Anchoring the separator to the row's OWN box (instead of a sibling
       div pulled up with negative margins) makes alignment DPI- and
       zoom-independent: the border is literally the bottom edge of the
       box that contains the buttons, with no inter-element gap to
       compensate for. */
    div.st-key-action_btns_row {{
        border: none !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
        box-sizing: border-box !important;
    }}
    /* ── Course List Box container ──
       Wraps the course checkbox list. Strip the native border and apply
       a single hairline border-bottom — this is the BOTTOM separator
       and is structurally identical to the top separator above. Pulled
       up by -1rem to cancel the parent stVerticalBlock's natural gap,
       so the top edge sits flush against the buttons-row's
       border-bottom (the top separator). */
    div.st-key-course_list_box {{
        border: none !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
        margin-top: -1rem !important;
        box-sizing: border-box !important;
    }}
    </style>""")
    st.html('<div style="padding-bottom: 1rem;"></div>')

    # --- Favorites / All Courses pill toggle ---
    favorites_only = render_favorites_pill("dl")

    # Show a loading placeholder immediately so the UI above is visible
    # while courses are being fetched. On cache hits (all transitions after
    # first load) this is replaced so fast the spinner is imperceptible.
    _courses_area = st.empty()
    with _courses_area.container():
        st.html("""
            <div style="display:flex;align-items:center;justify-content:center;
                        gap:12px;padding:56px 20px;
                        border:1px solid rgba(255,255,255,0.1);border-radius:8px;">
                <div style="width:20px;height:20px;
                            border:2px solid rgba(255,255,255,0.07);
                            border-top-color:#38bdf8;border-radius:50%;
                            animation:_cs_spin .75s linear infinite;flex-shrink:0">
                </div>
                <span style="color:rgba(255,255,255,0.5);
                             font:14px/1 system-ui,sans-serif">
                    Loading your courses…
                </span>
            </div>
            <style>@keyframes _cs_spin{to{transform:rotate(360deg)}}</style>
        """)

    # --- Fetch (spinner above is visible during cache miss) ---
    all_courses = fetch_courses_fn(
        st.session_state['api_token'],
        st.session_state['api_url'])
    courses = [c for c in all_courses if c.is_favorite] if favorites_only else all_courses

    if not courses:
        with _courses_area.container():
            st.warning('No courses found.')
        st.stop()

    # --- Replace spinner with fragment: CBS filters + action buttons + course list ---
    with _courses_area.container():
        _course_list_section(courses)

    # --- Continue ---
    error_container = st.empty()

    # Inject an invisible div so JavaScript knows if any courses are selected,
    # preventing the loading overlay from triggering when validation will fail.
    sel_count = len(st.session_state.get('selected_course_ids', []))
    st.html(f"<div id='cdp_selected_courses_count' data-count='{sel_count}' style='display:none;'></div>")

    # --- Load Premium Assets & Hoist Buttons CSS ---
    b64_custom = get_base64_image("assets/icon_custom_download.png")
    b64_quick = get_base64_image("assets/icon_sync_quick.png")

    st.html(f"""<style>
    /* Target buttons inside the main column containers — scoped to Custom/Quick Download */
    div.st-key-btn_custom_download button[kind="primary"],
    div.st-key-btn_quick_download button[kind="primary"] {{
        height: 3.2em !important;
        min-height: 3.2em !important;
        border-radius: 6px !important;
        width: 100% !important;
        padding: 0px 10px 4px 10px !important; /* Optical adjustment: pushes text up */
        float: none !important;
        margin: 0 auto !important;
    }}
    /* RECURSIVE CENTERING: START - Universal child selector */
    div.st-key-btn_custom_download button[kind="primary"] > div,
    div.st-key-btn_custom_download button[kind="primary"] > div > p,
    div.st-key-btn_quick_download button[kind="primary"] > div,
    div.st-key-btn_quick_download button[kind="primary"] > div > p {{
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        text-align: center !important;
        width: 100% !important;
        height: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
    }}
    div.st-key-btn_custom_download button[kind="primary"] *,
    div.st-key-btn_quick_download button[kind="primary"] * {{
        text-align: center !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    div.st-key-btn_custom_download button[kind="primary"] p,
    div.st-key-btn_quick_download button[kind="primary"] p {{
        font-size: 1rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
    }}

    div.st-key-btn_custom_download button p::before {{
        content: "" !important;
        display: inline-block !important;
        position: relative !important;
        top: 2px !important;
        width: 18px !important;
        height: 18px !important;
        margin-right: 5px !important;
        background-image: url("data:image/png;base64,{b64_custom}") !important;
        background-repeat: no-repeat !important;
        background-size: contain !important;
    }}
    div.st-key-btn_quick_download button p::before {{
        content: "" !important;
        display: inline-block !important;
        position: relative !important;
        top: 4px !important;
        width: 18px !important;
        height: 18px !important;
        margin-right: 5px !important;
        background-image: url("data:image/png;base64,{b64_quick}") !important;
        background-repeat: no-repeat !important;
        background-size: contain !important;
    }}

    /* Custom Download Colors - Solid Physical Volume */
    div.st-key-btn_custom_download button {{
        background-color: #1f77b4 !important;
        border: none !important;
        color: #ffffff !important;
        box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3) !important;
        transition: background-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
    }}
    div.st-key-btn_custom_download button:hover {{
        background-color: #2b8cbe !important;
        box-shadow: 0 4px 15px rgba(31, 119, 180, 0.2),
                    inset 0 1px 1px rgba(255, 255, 255, 0.4) !important;
        color: #ffffff !important;
    }}

    /* Quick Download Colors - Dramatic Teal Gradient Physical Volume */
    div.st-key-btn_quick_download button {{
        background: linear-gradient(135deg, #1e3a8a 0%, #06b6d4 100%) !important;
        border: none !important;
        color: #ffffff !important;
        box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3) !important;
        transition: filter 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
    }}
    div.st-key-btn_quick_download button:hover {{
        filter: brightness(1.15) !important;
        box-shadow: 0 4px 15px rgba(37, 99, 235, 0.2),
                    inset 0 1px 1px rgba(255, 255, 255, 0.4) !important;
        color: #ffffff !important;
    }}
    </style>""")

    col_custom, col_or, col_quick, _ = st.columns([0.75, 0.12, 0.75, 2.38], gap="small", vertical_alignment="center")
    with col_custom:
        advanced_clicked = st.button('Custom Download', type="primary", use_container_width=True, key="btn_custom_download")
    with col_or:
        st.markdown(f"<div style='text-align:center; font-weight:bold; color:{theme.TEXT_DIM}; font-size:0.9em;'>OR</div>", unsafe_allow_html=True)
    with col_quick:
        quick_clicked = st.button('Quick Download', type="primary", use_container_width=True, key="btn_quick_download")

    if quick_clicked or advanced_clicked:
        if not st.session_state['selected_course_ids']:
            error_container.error('Please select at least one course.')
        else:
            st.session_state['quick_download_mode'] = quick_clicked
            st.session_state['step'] = 2
            st.rerun()
