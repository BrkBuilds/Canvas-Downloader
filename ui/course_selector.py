"""
ui.course_selector - Shared course selection components + Step 1 for Download mode.

Shared Components (imported by sync_dialogs.py, hub_dialog.py):
  - ``inject_course_selector_css()`` - Premium CSS for CBS filter trays.
  - ``render_cbs_filters()``         - CBS toggle + filter criteria.
  - ``render_course_list()``         - Course checkbox list (multi or single select).

Download-specific:
  - ``render_course_selector()``     - Full Step 1 page.
"""

from __future__ import annotations

import re

import streamlit as st

import theme
from ui_helpers import (
    get_course_display_parts,
    parse_cbs_metadata,
    render_download_wizard,
    get_base64_image,
)


def _css_escape_content(text: str) -> str:
    """Escape a string for safe use inside a CSS quoted string (e.g. content: "...").

    html.escape() (used by esc()) produces HTML entities like &amp; which render
    literally in CSS rather than as their intended characters.  CSS strings only
    require escaping backslashes and the enclosing quote character.
    """
    return text.replace('\\', '\\\\').replace('"', '\\"')
from ui_shared import render_help_card, HELP_ICONS


# ═══════════════════════════════════════════════════════════════════════
# Shared Components - reused by Download, Sync Dialog, and Hub Dialog
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

# Outlined magnifier - URL-encoded for use as a CSS background-image.
_SEARCH_ICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 24 24' fill='none' stroke='%23ffffff' stroke-width='2' "
    "stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Ccircle cx='11' cy='11' r='7'/%3E"
    "%3Cline x1='21' y1='21' x2='16.65' y2='16.65'/%3E%3C/svg%3E"
)


# ═══════════════════════════════════════════════════════════════════════
# Smart course search (relevance ranking)
# ═══════════════════════════════════════════════════════════════════════

# Split a course name into searchable words on whitespace and punctuation so
# token matches can be anchored to word boundaries (e.g. "info" → "Information").
_WORD_SPLIT_RE = re.compile(r"[\s\-_/().,&]+")


def _is_subsequence(needle: str, haystack: str) -> bool:
    """True if every char of ``needle`` appears in ``haystack`` in order.

    Powers a forgiving fuzzy fallback so typos / abbreviations like
    "infosys" still surface "Introduction to Information Systems".
    """
    it = iter(haystack)
    return all(ch in it for ch in needle)


def _token_score(tok: str, name_l: str, code_l: str) -> int:
    """Score a single query token against one course (higher = better).

    Ranking intent, strongest to weakest signal:
    full-name prefix > word-start prefix > name substring >
    code prefix > code substring > fuzzy subsequence.
    Returns ``0`` when the token does not match at all.
    """
    if name_l.startswith(tok):
        return 100
    if any(w.startswith(tok) for w in _WORD_SPLIT_RE.split(name_l) if w):
        return 80
    if tok in name_l:
        return 50
    if code_l.startswith(tok):
        return 45
    if tok in code_l:
        return 30
    if len(tok) >= 2 and _is_subsequence(tok, name_l):
        return 12
    return 0


def _course_match_score(query: str, name: str, code: str) -> int:
    """Relevance score for a course against a (possibly multi-word) query.

    Every whitespace-separated token must match *something* (AND semantics),
    so "intro info" only matches a course containing both. Contiguous
    whole-query hits earn a bonus so the most literal matches rank first.
    An empty query matches everything (score ``1``).
    """
    q = query.lower().strip()
    if not q:
        return 1
    name_l = name.lower()
    code_l = code.lower()
    total = 0
    for tok in q.split():
        score = _token_score(tok, name_l, code_l)
        if score == 0:
            return 0
        total += score
    if name_l.startswith(q):
        total += 60
    elif q in name_l:
        total += 25
    return total


def _filter_and_rank_courses(courses: list, query: str) -> list:
    """Return ``courses`` filtered by ``query`` and ordered by relevance.

    With an empty query the list is returned unchanged (the caller applies
    its usual alphabetical sort). With a query, only matching courses are
    kept, ranked best-first with an alphabetical tie-break.
    """
    q = (query or "").strip()
    if not q:
        return list(courses)
    scored = []
    for c in courses:
        name, code = get_course_display_parts(c)
        score = _course_match_score(q, name, code)
        if score > 0:
            scored.append((score, name.lower(), c))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [c for _, _, c in scored]


def _query_matches_any(query: str, courses: list) -> bool:
    """True if at least one course in ``courses`` matches ``query``."""
    q = (query or "").strip()
    if not q:
        return bool(courses)
    return any(
        _course_match_score(q, *get_course_display_parts(c)) > 0
        for c in courses
    )


def _course_search_field_css(key: str, prefix: str = "") -> str:
    """Return the borderless search-field + magnifier-icon CSS for a text_input.

    Shared by Download mode (inline in the buttons row) and the dialog search
    component so the field looks identical everywhere. Only the field *visuals*
    live here; layout (the download flex row / divider) stays at the call site.

    Args:
        key: The text_input ``key`` (its ``st-key-`` class, lowercased here).
        prefix: Optional selector prefix. Pass ``'div[data-testid="stDialog"] '``
            for dialogs so the rules outrank Streamlit's high-specificity modal
            portal styles (CLAUDE.md "Modal Specificity Rule").
    """
    k = key.lower()
    p = prefix
    return f"""
    {p}div.st-key-{k} [data-testid="stTextInput"] {{ margin: 0 !important; }}
    {p}div.st-key-{k} [data-testid="stTextInput"] > label {{ display: none !important; }}
    /* Input shell - no fill until hover/focus. */
    {p}div.st-key-{k} div[data-baseweb="input"],
    {p}div.st-key-{k} div[data-baseweb="input"] > div {{
        position: relative !important;
        background-color: transparent !important;
        border: none !important;
        border-radius: 8px !important;
        min-height: 38px !important;
        box-shadow: none !important;
        transition: background-color 0.2s ease !important;
    }}
    /* Hover + focus: match the Select All / Clear button fill exactly. */
    {p}div.st-key-{k} div[data-baseweb="input"]:hover,
    {p}div.st-key-{k} div[data-baseweb="input"]:hover > div,
    {p}div.st-key-{k} div[data-baseweb="input"]:focus-within,
    {p}div.st-key-{k} div[data-baseweb="input"]:focus-within > div {{
        border: none !important;
        box-shadow: none !important;
        background-color: rgba(255, 255, 255, 0.02) !important;
    }}
    /* Magnifier icon, overlaid at the left of the field. */
    {p}div.st-key-{k} div[data-baseweb="input"]::before {{
        content: "" !important;
        position: absolute !important;
        left: 11px !important;
        top: 50% !important;
        transform: translateY(-50%) !important;
        width: 16px !important;
        height: 16px !important;
        background-image: url("{_SEARCH_ICON}") !important;
        background-size: contain !important;
        background-repeat: no-repeat !important;
        background-position: center !important;
        opacity: 0.45 !important;
        pointer-events: none !important;
        z-index: 1 !important;
        transition: opacity 0.2s ease !important;
    }}
    {p}div.st-key-{k} div[data-baseweb="input"]:focus-within::before {{
        opacity: 0.9 !important;
    }}
    /* The input field itself: transparent, with room for the icon. */
    {p}div.st-key-{k} div[data-baseweb="input"] input {{
        background-color: transparent !important;
        padding-left: 42px !important;
        font-size: 0.95rem !important;
        color: #e2e8f0 !important;
        outline: none !important;
        box-shadow: none !important;
    }}
    {p}div.st-key-{k} div[data-baseweb="input"] input::placeholder {{
        color: rgba(148, 163, 184, 0.7) !important;
    }}
    """


def render_course_search(
    namespace: str,
    *,
    in_dialog: bool = False,
    placeholder: str = "Search courses by name or code…",
) -> str:
    """Render a standalone course-search field and return the typed query.

    Drop this between the CBS filters and the course list in a selection
    dialog. It injects its own scoped (borderless + magnifier) CSS and the live
    per-keystroke filter bridge, then returns the query for use with
    ``_filter_and_rank_courses`` and ``_render_search_empty_notice``.

    Args:
        namespace: The same prefix used for the list (e.g. ``'sync_d'``,
            ``'hub_cs'``). The widget key becomes ``f"{namespace}_course_search"``.
        in_dialog: ``True`` inside an ``@st.dialog`` so the CSS is scoped under
            the modal portal and a touch of top spacing is added.
        placeholder: Field placeholder text.

    Returns:
        The current search query string (``""`` when empty).
    """
    key = f"{namespace}_course_search"
    prefix = 'div[data-testid="stDialog"] ' if in_dialog else ''
    margin = "margin-top: 4px;" if in_dialog else ""
    # Use st.markdown (NOT st.html) for the CSS: its ghost-box element-container
    # is auto-collapsed by global.css, so the injection adds no gap slot to the
    # dialog's flex flow (st.html style blocks are NOT collapsed and would push
    # the field/list apart). See CLAUDE.md "Headless Injection Rule".
    st.markdown(
        f"<style>{_course_search_field_css(key, prefix=prefix)}"
        f"{prefix}div.st-key-{key.lower()} {{ {margin} }}</style>",
        unsafe_allow_html=True,
    )
    query = st.text_input(
        "Search courses",
        key=key,
        placeholder=placeholder,
        label_visibility="collapsed",
    )
    inject_search_live_bridge(key)
    return query


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
    # immediately after the stVerticalBlock gap - no negative compensation needed.
    _seg_margin_top = "0px" if in_dialog else "-30px"
    # In dialog portals, Streamlit's own button CSS wins at equal specificity
    # (loaded later in the cascade). Prefix with div[role="dialog"] to boost
    # our specificity to (0,2,*) so we always win regardless of source order.
    # Download mode (in_dialog=False) uses no prefix - it works as-is.
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
    /* Specificity shield - protect active from hover degradation */
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
    sort: bool = True,
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
        sort: When ``True`` (default) courses are sorted alphabetically.
            Pass ``False`` to preserve the caller's order - used when the
            list has already been relevance-ranked by the search box.

    Multi-select:
        Reads/writes ``st.session_state['selected_course_ids']``.
        Returns the updated list of selected course IDs.

    Single-select:
        Reads/writes ``st.session_state['{namespace}_selected_id']``.
        Returns ``None``.
    """
    if not courses:
        from ui.amber_notice import render_info_notice
        render_info_notice('No courses match the selected filters.')
        if multi_select:
            return []
        else:
            return None

    if sort:
        sorted_courses = sorted(
            courses, key=lambda c: (getattr(c, 'name', '') or '').lower())
    else:
        sorted_courses = list(courses)

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

    dynamic_css = []

    for course in courses:
        base_name, code = get_course_display_parts(course)
        code_clean = code.strip("()") if code else ""
        chk_key = f"{namespace}_chk_{course.id}"

        # Inject code subtext via CSS
        if code_clean:
            dynamic_css.append(f"""
            div.st-key-{chk_key} label[data-baseweb="checkbox"] div[data-testid="stMarkdownContainer"]::after {{
                content: "{_css_escape_content(code_clean)}";
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

    boundary_css = []
    if len(courses) > 0 and first_item_top_offset and first_item_top_offset != "0":
        f_key = f"{namespace}_chk_{courses[0].id}"
        boundary_css.append(f"""
        div.st-key-{f_key} {{ margin-top: {first_item_top_offset} !important; }}
        """)
    if len(courses) > 0:
        l_key = f"{namespace}_chk_{courses[-1].id}"
        boundary_css.append(f"""
        div.st-key-{l_key} {{ margin-bottom: 0px !important; }}
        """)

    combined_css = dynamic_css + boundary_css
    if combined_css:
        st.html(f'<style>{"".join(combined_css)}</style>')
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
                content: "{_css_escape_content(code_clean)}";
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

def inject_shift_select_bridge(namespace: str) -> None:
    """Enable Shift-click range selection on a multi-select course checkbox list.

    Streamlit checkboxes are server-side widgets and never expose the Shift
    modifier to Python, so the range logic must live in JavaScript.  This injects
    a ``components.html`` iframe whose script reaches into ``window.parent.document``
    (same origin) and attaches a delegated ``click`` listener.  It uses event
    delegation and re-queries the live row set on every click, so it works across
    fragment reruns and CBS-filter changes.

    Behaviour: click a row to set the anchor, then Shift-click another row to set
    every checkbox in between (inclusive) to the *new* state of the row you just
    clicked - matching the familiar file-explorer / Gmail range-select gesture.

    Reliability: ``components.html`` rebuilds a fresh iframe on every rerun and
    destroys the previous one; a listener attached from a destroyed iframe's
    realm silently stops firing.  A one-time "already bound" guard would
    therefore leave Shift-select permanently dead after the first iframe is torn
    down (most visibly after the favorites/all toggle's full-page rerun).  So
    this **re-binds a fresh listener (from the current, alive realm) on every
    injection**, removing the previous one first.  Mutable state (``anchorKey``,
    ``applying``) lives on ``window.parent`` so it survives across re-binds.
    The in-range checkboxes are toggled with **synchronous** ``input.click()``
    calls inside one JS tick, so Streamlit batches them into a single fragment
    rerun; the ``selected_course_ids`` reconciliation in
    ``_render_multi_select_list`` then picks up every change.

    Args:
        namespace: The same prefix passed to ``render_course_list`` (e.g. ``'dl'``).
            Rows are matched by their ``st-key-{namespace}_chk_<id>`` DOM class.
    """
    import streamlit.components.v1 as components

    ns = namespace.lower()
    components.html(
        f"""<script>
(function(){{
    // State lives on window.parent so it survives the iframe being recreated on
    // every rerun (components.html() makes a fresh iframe each time).
    var win = window.parent, doc = win.document;
    var NS = {ns!r};
    var reg = win._cdShift || (win._cdShift = {{}});
    var st  = reg[NS] || (reg[NS] = {{anchorKey: null, applying: false, handler: null}});

    var SELECTOR = 'div[class*="st-key-' + NS + '_chk_"]';
    var KEYRE = new RegExp('st-key-(' + NS + '_chk_[^ ]+)');

    function rowList() {{ return Array.prototype.slice.call(doc.querySelectorAll(SELECTOR)); }}
    function keyOf(row) {{ var m = row.className.match(KEYRE); return m ? m[1] : null; }}
    function inputOf(row) {{ return row.querySelector('input[type="checkbox"]'); }}

    // Drop the previous listener (its iframe realm may already be dead) and
    // re-attach a fresh one from this live realm.
    if (st.handler) {{
        try {{ doc.removeEventListener('click', st.handler, true); }} catch (_e) {{}}
    }}

    // Capture phase: runs before the native checkbox toggle, so input.checked is
    // still the OLD value and the post-click ("new") state is its negation.
    st.handler = function(e) {{
        if (st.applying) return;   // ignore the synthetic clicks we dispatch below
        var row = e.target.closest ? e.target.closest(SELECTOR) : null;
        if (!row) return;

        var list = rowList();
        var idx = list.indexOf(row);
        if (idx === -1) return;

        if (e.shiftKey && st.anchorKey) {{
            var aIdx = -1;
            for (var i = 0; i < list.length; i++) {{
                if (keyOf(list[i]) === st.anchorKey) {{ aIdx = i; break; }}
            }}
            var clicked = inputOf(row);
            if (aIdx !== -1 && aIdx !== idx && clicked) {{
                var target = !clicked.checked;   // state the clicked box is about to take
                var lo = Math.min(aIdx, idx), hi = Math.max(aIdx, idx);
                st.applying = true;
                for (var j = lo; j <= hi; j++) {{
                    if (j === idx) continue;     // the clicked box toggles itself natively
                    var inp = inputOf(list[j]);
                    if (inp && inp.checked !== target) inp.click();
                }}
                st.applying = false;
            }}
        }}
        st.anchorKey = keyOf(row);
    }};
    doc.addEventListener('click', st.handler, true);
}})();
</script>""",
        height=0,
    )


def inject_search_live_bridge(namespace: str = "course_search", debounce_ms: int = 200) -> None:
    """Make the course-search field filter as you type (no Enter / click-out).

    Streamlit only commits a text input's value to Python on blur or Enter.
    Dispatching a *synthetic* Enter is unreliable (Streamlit's React handler
    ignores untrusted key events), but a programmatic ``blur()`` reliably fires
    the same onBlur commit as clicking out of the field. So this bridge, after a
    short debounce, blurs the field to commit the typed value and then
    immediately refocuses it - restoring the caret - so typing continues
    uninterrupted while the list filters live.

    Reliability: ``components.html`` builds a *fresh* iframe on every rerun and
    destroys the previous one. A listener attached from inside a destroyed
    iframe's realm silently stops firing - so a one-time "already bound" guard
    would leave the page permanently dead after the first iframe is torn down
    (most visibly when the favorites/all toggle triggers a full-page rerun).
    Instead this re-binds a fresh listener (from the current, alive realm) on
    *every* injection, first removing the previous one to avoid pile-up. The
    debounce + last-committed-value guard keep reruns to roughly one per typing
    pause. Persistent state (last value, timer, handler ref) lives on
    ``window.parent`` so it survives across re-binds; timers use the parent's
    ``setTimeout`` so their ids stay valid no matter which realm clears them.

    Args:
        namespace: The text_input ``key`` (matched via its ``st-key-`` class).
        debounce_ms: Idle time after the last keystroke before committing.
    """
    import streamlit.components.v1 as components

    ns = namespace.lower()
    components.html(
        f"""<script>
(function(){{
    var win = window.parent, doc = win.document;
    var NS = {ns!r};
    var root = win._cdSearchLive || (win._cdSearchLive = {{}});
    var reg = root[NS] || (root[NS] =
        {{listeners: [], timer: null, last: null, composing: false}});
    var SELECTOR = 'div[class*="st-key-{ns}"] input';
    var DEBOUNCE = {int(debounce_ms)};

    // Drop previously-bound listeners (their iframe realm may already be dead)
    // and re-attach fresh ones from this live realm.
    (reg.listeners || []).forEach(function(l) {{
        try {{ doc.removeEventListener(l[0], l[1], true); }} catch (_e) {{}}
    }});
    reg.listeners = [];

    function isField(n) {{ return n && n.matches && n.matches(SELECTOR); }}

    function commit(inp) {{
        if (reg.composing) return;                // mid IME / dead-key (æøé): wait
        if (inp.value === reg.last) return;       // nothing new to push
        reg.last = inp.value;
        var s = inp.selectionStart, e = inp.selectionEnd;
        inp.blur();                               // → Streamlit onBlur commit + rerun
        inp.focus({{preventScroll: true}});       // keep the user typing
        try {{ inp.setSelectionRange(s, e); }} catch (_e) {{}}  // restore caret
    }}

    function schedule(inp) {{
        win.clearTimeout(reg.timer);
        reg.timer = win.setTimeout(function() {{ commit(inp); }}, DEBOUNCE);
    }}

    function bind(type, fn) {{ doc.addEventListener(type, fn, true); reg.listeners.push([type, fn]); }}

    bind('input', function(ev) {{ if (isField(ev.target)) schedule(ev.target); }});
    // Don't commit while composing accented/IME text; resume once it finishes.
    bind('compositionstart', function(ev) {{ if (isField(ev.target)) reg.composing = true; }});
    bind('compositionend', function(ev) {{
        if (isField(ev.target)) {{ reg.composing = false; schedule(ev.target); }}
    }});
}})();
</script>""",
        height=0,
    )


def _render_search_empty_notice(
    query: str, favorites_only: bool, courses: list,
    filtered_courses: list, all_courses: list,
) -> None:
    """Render a context-aware notice when a search yields no visible courses.

    The message is tailored to *why* nothing showed up so the user knows
    exactly what to do next:

    1. A match exists in this view but is hidden by active CBS filters.
    2. (Favorites view) a match exists in the full course list - offer to
       switch over to it.
    3. Nothing matches anywhere - likely a typo.
    """
    from ui.amber_notice import render_info_notice

    q = query.strip()

    # 1) CBS filters are hiding an otherwise-matching course in this same view.
    if _query_matches_any(q, courses) and not _query_matches_any(q, filtered_courses):
        render_info_notice(
            f'No courses match "{q}" with your current CBS filters.',
            detail="A matching course is hidden by your active CBS filters. "
                   "Clear them above to reveal it.",
            margin="0",
        )
        return

    # 2) Favorites view: the course probably lives in the full list. The
    #    "All Courses" toggle is right above, so just point the user to it.
    if favorites_only and _query_matches_any(q, all_courses):
        render_info_notice(
            f'None of your favorites match "{q}".',
            detail='A matching course exists in your full course list - '
                   'flip the "All Courses" toggle above to find it.',
            margin="0",
        )
        return

    # 3) Nothing matches anywhere - almost always a spelling slip.
    render_info_notice(
        f'No courses match "{q}".',
        detail="Double-check the spelling, or try a shorter or different "
               "search term.",
        margin="0",
    )


@st.fragment
def _course_list_section(
    courses: list, all_courses: list, favorites_only: bool
) -> None:
    """Fragment: CBS filters + Select All/Clear + search + checkbox list.

    Scopes checkbox-click and search reruns to this fragment only, keeping the
    wizard header and page chrome stable.

    Args:
        courses: Courses for the active view (favorites or all), pre-CBS.
        all_courses: The complete course list, used to tell the user when a
            searched course exists outside the current favorites view.
        favorites_only: Whether the favorites pill is currently active.
    """
    filtered_courses = render_cbs_filters(courses, "dl")

    # --- Action buttons row + inline search box ---
    # The search box lives in the same row as Select All / Clear Selection and
    # stretches to the far right (see the flex reflow CSS in
    # render_course_selector). Its query is held in `course_search` session
    # state, so it survives the favorites/all toggle (a full-page rerun)
    # seamlessly - the filter re-applies to whichever view is shown.
    with st.container(key="action_btns_row", border=True):
        select_all_clicked = st.button('Select All', key="btn_course_select_all")
        clear_sel_clicked = st.button('Clear Selection', key="btn_course_clear_selection")
        query = st.text_input(
            "Search courses",
            key="course_search",
            placeholder="Search courses by name or code…",
            label_visibility="collapsed",
        )

    # Relevance-rank the visible courses against the search query.
    displayed_courses = _filter_and_rank_courses(filtered_courses, query)
    # "Select All" applies to exactly what the user currently sees.
    visible_ids = {c.id for c in displayed_courses}

    if select_all_clicked:
        current_ids = set(st.session_state.get('selected_course_ids', []))
        st.session_state['selected_course_ids'] = list(current_ids.union(visible_ids))
        for cid in visible_ids:
            st.session_state[f"dl_chk_{cid}"] = True
        st.rerun(scope="fragment")

    if clear_sel_clicked:
        st.session_state['selected_course_ids'] = []
        # Reset checkbox widget state across the ENTIRE course universe, not just
        # the current view. selected_course_ids is global, so resetting only the
        # visible view would leave a stale dl_chk=True on a course selected in the
        # other view (e.g. a non-favorite picked in All Courses) - which the list
        # reconciliation would then resurrect as "selected" on the next switch.
        for c in all_courses:
            st.session_state[f"dl_chk_{c.id}"] = False
        st.rerun(scope="fragment")

    if displayed_courses:
        with st.container(key="course_list_box", border=True):
            render_course_list(
                displayed_courses, "dl", multi_select=True,
                first_item_top_offset="1px",
                sort=not query.strip(),  # already relevance-ranked when searching
            )
        # Shift-click range selection across the checkbox rows above.
        inject_shift_select_bridge("dl")
    else:
        # Distinct key → symmetric vertical padding so the notice sits evenly
        # between the top (buttons row) and bottom separators.
        with st.container(key="course_list_empty", border=True):
            if query.strip():
                _render_search_empty_notice(
                    query, favorites_only, courses, filtered_courses, all_courses
                )
            else:
                from ui.amber_notice import render_info_notice
                render_info_notice(
                    'No courses match the selected filters.', margin="0"
                )

    # Live (per-keystroke) filtering - commit the search field without Enter.
    inject_search_live_bridge()

    # Inject an invisible div so JavaScript knows if any courses are selected,
    # preventing the loading overlay from triggering when validation will fail.
    # Placed inside the fragment so it updates on every checkbox click/clear.
    sel_count = len(st.session_state.get('selected_course_ids', []))
    st.html(f"<div id='cdp_selected_courses_count' data-count='{sel_count}' style='display:none;'></div>")


# ═══════════════════════════════════════════════════════════════════════
# Download Mode - Step 1: Select Courses
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
        "<b>Select the courses you want to download, then press either of the download buttons.</b>"
        "<div style='font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-bottom: 8px; margin-top: 16px; display: flex; align-items: center; gap: 8px;'>Batch Downloading</div>"
        f"You can download as many courses as you want at once. The application will process them one after another.<br> "
        f"All selected courses will be downloaded into your output folder as separate folders (e.g., Programming 101, History 201)."
        f"<div style='font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-bottom: 8px; margin-top: 16px; display: flex; align-items: center; gap: 8px;'>{HELP_ICONS['star']} Favorites vs All Courses</div>"
        "The toggle at the top lets you filter between your favorited Canvas courses and your full course list.<br> "
        "Your favorited courses can be managed directly in Canvas. Canvas Downloader might require a restart to see changes."
        f"<div style='font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-bottom: 8px; margin-top: 16px; display: flex; align-items: center; gap: 8px;'>{HELP_ICONS['gear']} Download Settings &amp; Course Selection</div>"
        "You will configure your download settings in the next step.<br>"
        "<div style='background-color: rgba(245, 158, 11, 0.1); border-left: 3px solid #f59e0b; padding: 8px 12px; margin-top: 8px; border-radius: 0px 4px 4px 0px;'>"
        f"<span style='color: #fbd38d; font-weight: 600;'>{HELP_ICONS['warning']} Notice:</span> <b>The download settings you choose on the next page will apply to ALL courses selected here.</b><br>"
        "For example, if you select the 'Slides & PDFs Only' preset in Quick Download, all courses selected will be downloaded with the 'Slides & PDFs Only' download settings (configuration) applied. <br>"
        "If you need different settings for different courses, you must perform separate download runs."
        "</div>"
        "<hr>"
        f"<div style='font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-bottom: 8px; margin-top: 16px; display: flex; align-items: center; gap: 8px;'>{HELP_ICONS['question']} Frequently Asked Questions</div>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What happens if a folder with the course name already exists on my computer?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63, 217, 255, 0.05); font-size: 0.85rem; color: #d1d5db;'>"
        "The application will safely <b>merge</b> the new files into your existing folder (e.g., an old 'History 101' course folder will have its new (missing) files added to it if you download the same course to the same output folder).<br>"
        "It will not delete your files - only add what's missing. If a Canvas file has been updated and you haven't edited it, it will overwrite the old version safely but everything else remains untouched."
        "</div>"
        "</details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Can I download all my Canvas courses at once?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63, 217, 255, 0.05); font-size: 0.85rem; color: #d1d5db;'>"
        "Yes! Just click the <b>Select All</b> button at the top of the course list. "
        "Note that downloading dozens of courses simultaneously might take a while depending on your internet connection."
        "</div>"
        "</details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Does this download my Assignments and Quizzes?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63, 217, 255, 0.05); font-size: 0.85rem; color: #d1d5db;'>"
        "Short answer: Depends on the Quick Download Preset / Custom Download settings you choose.<br>"
        "Long answer: By default, we always download the course files uploaded by your teacher, but in the <b>Custom Download</b> page, you can manually choose exactly what else to include - such as assignments & quizzes (found in the Canvas Content card)! "
        "</div>"
        "</details>"
    )

    # Snug Header Hack - H2 + Help button on one flex row
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
                mode="button"
            )

    # Help Card Expansion (renders below the header row if open)
    render_help_card(
        key_prefix="course_selector",
        title=_cs_help_title,
        text_html=_cs_help_text,
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
       a single hairline border-bottom - this is the BOTTOM separator
       and is structurally identical to the top separator above. Pulled
       up by -1rem to cancel the parent stVerticalBlock's natural gap,
       so the top edge sits flush against the buttons-row's
       border-bottom (the top separator). */
    div.st-key-course_list_box,
    div.st-key-course_list_empty {{
        border: none !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 0 !important;
        margin: 0 !important;
        margin-top: -1rem !important;
        box-sizing: border-box !important;
    }}
    div.st-key-course_list_box {{ padding: 0 !important; }}
    /* Empty-state notice container: symmetric top/bottom padding so the notice
       sits evenly between the buttons-row separator and the bottom separator.
       The padding (vs a child margin) also defeats margin-collapse, which would
       otherwise let the notice's top margin escape and hug the top line. */
    div.st-key-course_list_empty {{ padding: 14px 0 28px 0 !important; }}

    /* ══ Inline Course Search box (right side of the buttons row) ══ */
    /* Override the shrink-to-fit rule above so the search wrapper grows to
       fill the remaining row width all the way to the far right edge. The
       added class makes this selector more specific than the generic
       "> div" rule, so it wins. */
    div[data-testid="stVerticalBlock"]:has(> div.st-key-btn_course_select_all) > div.st-key-course_search {{
        flex: 1 1 auto !important;
        width: auto !important;
        min-width: 150px !important;
    }}
    /* Short vertical divider between the buttons and the search field. */
    div.st-key-course_search {{
        position: relative !important;
        padding-left: 7px !important;
        margin-left: 9px !important;
    }}
    div.st-key-course_search::before {{
        content: "" !important;
        position: absolute !important;
        left: 0 !important;
        top: 50% !important;
        transform: translateY(-50%) !important;
        width: 1px !important;
        height: 20px !important;
        background-color: rgba(255, 255, 255, 0.15) !important;
        pointer-events: none !important;
    }}
    /* Shared borderless field + magnifier visuals. */
    {_course_search_field_css('course_search')}
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
    # A token that expired/was revoked mid-session surfaces here as an Unauthorized
    # error. Route to the clean reconnect flow instead of crashing the page.
    try:
        all_courses = fetch_courses_fn(
            st.session_state['api_token'],
            st.session_state['api_url'])
    except Exception as _fetch_err:
        from canvas_logic import is_auth_error
        if is_auth_error(_fetch_err):
            from ui.auth import force_reauth
            force_reauth("Your Canvas connection expired or the access token was revoked. Please reconnect with a new token.")
        raise
    courses = [c for c in all_courses if c.is_favorite] if favorites_only else all_courses

    if not courses:
        with _courses_area.container():
            from ui.amber_notice import render_amber_notice
            render_amber_notice('No courses found.')
        st.stop()

    # --- Replace spinner with fragment: CBS filters + action buttons + course list ---
    with _courses_area.container():
        _course_list_section(courses, all_courses, favorites_only)

    # --- Continue ---
    error_container = st.empty()



    # --- Load Premium Assets & Hoist Buttons CSS ---
    b64_custom = get_base64_image("assets/icon_custom_download.png")
    b64_quick = get_base64_image("assets/icon_sync_quick.png")

    st.html(f"""<style>
    /* Target buttons inside the main column containers - scoped to Custom/Quick Download */
    div.st-key-btn_custom_download button[kind="primary"],
    div.st-key-btn_quick_download button[kind="primary"] {{
        height: 3.2em !important;
        min-height: 3.2em !important;
        border-radius: 6px !important;
        width: 100% !important;
        padding: 0px 10px !important; /* Balanced vertical padding */
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
        /* rely on flex centering */
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
        /* rely on flex centering */
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

    col_custom, col_or, col_quick, _ = st.columns([0.75, 0.16, 0.75, 2.34], gap="small", vertical_alignment="center")
    with col_custom:
        advanced_clicked = st.button('Custom Download', type="primary", use_container_width=True, key="btn_custom_download")
    with col_or:
        st.markdown(f"<div style='text-align:center; font-weight:bold; color:{theme.TEXT_DIM}; font-size:0.9em; white-space:nowrap; word-break:keep-all;'>OR</div>", unsafe_allow_html=True)
    with col_quick:
        quick_clicked = st.button('Quick Download', type="primary", use_container_width=True, key="btn_quick_download")

    st.html("<div style='height: 20px;'></div>")

    if quick_clicked or advanced_clicked:
        if not st.session_state['selected_course_ids']:
            with error_container.container():
                from ui.amber_notice import render_amber_notice
                render_amber_notice('Please select at least one course.', margin="-16px 0 16px 0")
        else:
            if quick_clicked:
                # Always start Quick Download with no preset selected.
                st.session_state.pop('quick_preset_id', None)
            st.session_state['quick_download_mode'] = quick_clicked
            st.session_state['step'] = 2
            st.rerun()
