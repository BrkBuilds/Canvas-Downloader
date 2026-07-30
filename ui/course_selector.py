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
import time

import streamlit as st

from shared import theme
from shared.helpers import (
    get_course_display_parts,
    parse_cbs_metadata,
    render_download_wizard,
    get_base64_image,
    help_text_enabled,
    esc,
    css_content_safe,
)


# The "fetching courses" placeholder, used from TWO places that must look
# identical: the page's cold-boot slot (whole section not built yet) and the
# list box during a Refresh (toolbar stays, only the list is replaced).
_COURSES_LOADING_HTML = """
    <div style="display:flex;align-items:center;justify-content:center;
                gap:12px;padding:56px 20px;">
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
"""

# The same spinner inside the list's own outline (a bottom separator, exactly
# like st-key-course_list_box), used while Refresh re-fetches. min-height keeps
# the page from collapsing and re-expanding around it.
_COURSES_LOADING_BOX = (
    "<div style=\"border-bottom:1px solid rgba(255,255,255,0.1);min-height:220px;"
    "display:flex;align-items:center;justify-content:center;margin-top:-1rem;\">"
    + _COURSES_LOADING_HTML +
    "</div>"
)

# One line under each primary action saying what it does. Deliberately NOT a
# tooltip: a tooltip fires every single time you move to click the button, which
# a returning user reads as the app nagging them. A caption is there when you
# are choosing and invisible once you have chosen (see `.cd-action-hint` in
# global.css - it fades out while the sticky bar is floating).
_CUSTOM_DOWNLOAD_HINT = "Choose exactly what to download, and how"
_QUICK_DOWNLOAD_HINT = "Pick a preset and download"


def _css_escape_content(text: str) -> str:
    """Escape a string for a CSS ``content: "…"`` value.

    Delegates to ``shared.helpers.css_content_safe``, which additionally
    neutralises ``<``. That matters here because the caller interpolates a
    Canvas-supplied course code into ``st.html(f'<style>…</style>')``: a code
    containing ``</style>`` used to close the element early and silently kill
    every rule after it. The Today page already hardened its copy of this
    function; the course list did not, and there is now only one definition.
    """
    return css_content_safe(text)
from shared.components import render_help_card, HELP_ICONS


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

# ── Toolbar divider geometry (course-list action row) ──
# The row is a flex box with a fixed gap. Each divider is drawn as a ::before at
# the LEFT edge of the element it precedes, so the space BEFORE a divider is
# (row gap + that element's margin-left) while the space AFTER it is that
# element's padding-left. Those two must come out equal or the control between a
# pair of dividers sits visibly off-centre - which is exactly how the Refresh
# button ended up 7px from its left divider and 14px from its right one.
# Deriving _TB_PRE from the other two keeps them in step if the gap ever changes.
_TB_GAP = 5     # must match the `gap` on the row's flex container
_TB_PAD = 10    # breathing room on EACH side of every divider
_TB_PRE = _TB_PAD - _TB_GAP

# ── Toolbar glyphs, used as CSS MASKS (not background-images) ──
# A mask paints with `background-color: currentColor`, so these inherit the
# button's own text colour and brighten on hover along with it. The stroke colour
# baked into the SVG is therefore irrelevant - only the shape matters.
# lucide "list-restart".
_REFRESH_MASK = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 24 24' fill='none' stroke='%23000' stroke-width='2' "
    "stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Cpath d='M21 5H3'/%3E%3Cpath d='M7 12H3'/%3E%3Cpath d='M7 19H3'/%3E"
    "%3Cpath d='M12 18a5 5 0 0 0 9-3 4.5 4.5 0 0 0-4.5-4.5c-1.33 0-2.54.54-3.41 1.41L11 14'/%3E"
    "%3Cpath d='M11 10v4h4'/%3E%3C/svg%3E"
)
# lucide "x".
_CLEAR_X_MASK = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 24 24' fill='none' stroke='%23000' stroke-width='2.5' "
    "stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Cpath d='M18 6 6 18'/%3E%3Cpath d='m6 6 12 12'/%3E%3C/svg%3E"
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
    /* The input field itself: transparent, with room for the magnifier on the
       left and the injected clear-"X" on the right (see the clear-button block
       in inject_course_selector_css + inject_search_live_bridge). The right
       padding is reserved unconditionally so the text does not reflow when the
       X appears and disappears. */
    {p}div.st-key-{k} div[data-baseweb="input"] input {{
        background-color: transparent !important;
        padding-left: 42px !important;
        padding-right: 34px !important;
        font-size: 0.95rem !important;
        color: #e2e8f0 !important;
        outline: none !important;
        box-shadow: none !important;
    }}
    {p}div.st-key-{k} div[data-baseweb="input"] input::placeholder {{
        color: rgba(148, 163, 184, 0.7) !important;
    }}

    /* ── Clear-search "X" (the node injected by inject_search_live_bridge) ──
       These MUST live here, with the rest of the field's visuals, not in the
       download page's own CSS block: every dialog search field runs the same
       bridge, so the button was being injected into dialogs where no rule
       reached it and it rendered as Streamlit's default button - a narrow
       solid-white slab with no glyph. Scoped to this field's key so the
       dialog prefix applies and it outranks the modal portal's styles. */
    {p}div.st-key-{k} button.cs-clear-search {{
        position: absolute !important;
        top: 50% !important;
        right: 8px !important;
        transform: translateY(-50%) !important;
        /* Square by construction - a hit target that is taller than it is wide
           reads as a scrollbar fragment, which is exactly how it looked. */
        width: 22px !important; height: 22px !important;
        min-width: 22px !important; min-height: 22px !important;
        padding: 0 !important; margin: 0 !important;
        border: none !important; border-radius: 5px !important;
        background: transparent !important;
        box-shadow: none !important;
        cursor: pointer !important;
        display: none;
        align-items: center !important; justify-content: center !important;
        z-index: 5 !important;
        transition: background-color 0.15s ease !important;
    }}
    {p}div.st-key-{k} button.cs-clear-search[data-visible="1"] {{ display: flex !important; }}
    {p}div.st-key-{k} button.cs-clear-search::after {{
        content: "" !important;
        width: 12px !important; height: 12px !important;
        background-color: rgba(255, 255, 255, 0.55) !important;
        -webkit-mask-image: url("{_CLEAR_X_MASK}");
        mask-image: url("{_CLEAR_X_MASK}");
        -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
        -webkit-mask-position: center;  mask-position: center;
        -webkit-mask-size: contain;    mask-size: contain;
    }}
    {p}div.st-key-{k} button.cs-clear-search:hover {{ background: rgba(255, 255, 255, 0.10) !important; }}
    {p}div.st-key-{k} button.cs-clear-search:hover::after {{ background-color: #ffffff !important; }}
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


def resolve_multi_selection(courses: list, namespace: str) -> list:
    """The selection as it WILL BE once ``courses`` render, computed up front.

    This is the single definition of the multi-select reconciliation rule:
    off-screen selections (hidden by the CBS filters or the search box) are
    preserved, and every visible course contributes according to its checkbox.

    It can run *before* the list renders because Streamlit applies widget state
    to ``st.session_state`` before the script body runs - so ``dl_chk_<id>``
    already holds the value the user just clicked. A course that has never been
    rendered has no key yet and falls back to ``selected_course_ids``, exactly
    as the ``value=`` argument in ``_render_multi_select_list`` does.

    **Why this is a function and not two copies:** the toolbar's live count has
    to print the post-click number while sitting ABOVE the list that produces
    it. It used to solve that with an ``st.empty()`` placeholder filled at the
    end of the fragment - which unmounted the count for ~60-80ms on every
    rerun (see the count in ``_course_list_section`` for the full story). The
    fix is for the toolbar to ask this function instead, and duplicating the
    rule here rather than sharing it is how the two would drift apart.

    Args:
        courses: The courses about to be rendered, in any order (only
            membership is used, so callers may pass a pre-sort list).
        namespace: The checkbox key prefix (e.g. ``'dl'``).

    Returns:
        The resolved list of selected course IDs.
    """
    selected_ids = st.session_state.get('selected_course_ids', [])
    visible_ids = {c.id for c in courses}
    # Preserve off-screen selections (hidden by CBS filters / the search box)
    resolved = [sid for sid in selected_ids if sid not in visible_ids]
    for course in courses:
        chk_key = f"{namespace}_chk_{course.id}"
        if st.session_state.get(chk_key, course.id in selected_ids):
            resolved.append(course.id)
    return resolved


def _render_multi_select_list(
    courses: list, namespace: str, first_item_top_offset: str = "-40px"
) -> list:
    """Multi-select checkbox list (Download mode)."""
    selected_ids = st.session_state.get('selected_course_ids', [])
    # Resolved from the SAME function the toolbar's live count calls, so the
    # number above the list and the list itself can never disagree.
    new_selected_ids = resolve_multi_selection(courses, namespace)

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
        # The return value is deliberately unused - `new_selected_ids` was
        # already resolved above by resolve_multi_selection(), which reads the
        # same widget state this call renders from.
        if chk_key not in st.session_state:
            st.checkbox(base_name, value=(course.id in selected_ids), key=chk_key)
        else:
            st.checkbox(base_name, key=chk_key)

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
        {{listeners: [], timer: null, last: null, composing: false,
          observer: null, healing: false}});
    var SELECTOR = 'div[class*="st-key-{ns}"] input';
    var DEBOUNCE = {int(debounce_ms)};

    // Drop previously-bound listeners (their iframe realm may already be dead)
    // and re-attach fresh ones from this live realm.
    (reg.listeners || []).forEach(function(l) {{
        try {{ doc.removeEventListener(l[0], l[1], true); }} catch (_e) {{}}
    }});
    reg.listeners = [];

    function isField(n) {{ return n && n.matches && n.matches(SELECTOR); }}

    // `blur()` is a NO-OP on an element that is not focused - so every commit
    // here has to know whether the field currently holds focus. See clearValue.
    function focused(inp) {{ return doc.activeElement === inp; }}

    function commit(inp) {{
        if (reg.composing) return;                // mid IME / dead-key (æøé): wait
        if (inp.value === reg.last) return;       // nothing new to push
        reg.last = inp.value;
        // The debounce can outlive the user's attention: type, then click a
        // checkbox within DEBOUNCE ms and this fires with focus already gone.
        // That real blur ALREADY committed the value, so there is nothing to
        // push - and blur/focus here would yank the caret back into the search
        // box a fifth of a second after the user left it.
        if (!focused(inp)) return;
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

    bind('input', function(ev) {{ if (isField(ev.target)) {{ schedule(ev.target); syncClear(ev.target); }} }});
    // Don't commit while composing accented/IME text; resume once it finishes.
    bind('compositionstart', function(ev) {{ if (isField(ev.target)) reg.composing = true; }});
    bind('compositionend', function(ev) {{
        if (isField(ev.target)) {{ reg.composing = false; schedule(ev.target); }}
    }});

    // ── Clear-search "X" ──
    // Streamlit has no clear affordance for text_input, so one real <button> is
    // injected into the field's shell. Styling lives in CSS (button.cs-clear-search).
    function clearValue(inp) {{
        // Assigning .value directly does NOT notify React - it tracks the last
        // value it set and would treat the change as a no-op. Go through the
        // native setter and dispatch a bubbling 'input' event, exactly as a real
        // keystroke does, then blur to trigger Streamlit's onBlur commit.
        try {{
            var d = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value');
            if (d && d.set) {{ d.set.call(inp, ''); }} else {{ inp.value = ''; }}
        }} catch (_e) {{ inp.value = ''; }}
        inp.dispatchEvent(new win.Event('input', {{bubbles: true}}));
        win.clearTimeout(reg.timer);
        reg.last = '';
        // The X commits by BLURRING, and `blur()` does nothing at all when the
        // element is not focused - so the field must be focused first or the
        // cleared value never reaches Python. The field is normally still
        // focused (mousedown is prevented below, so the click never moves
        // focus), but it is NOT after anything else took focus first: switch
        // the favorites/all pill, tick a checkbox, click the page - the field
        // is re-rendered unfocused and the X then cleared the text on screen
        // while the course list kept the old filter until the user clicked
        // somewhere else and that blur finally committed. Focusing first makes
        // the commit unconditional; the trailing focus() then leaves the caret
        // in the field exactly as before, ready to type a new query.
        if (!focused(inp)) inp.focus({{preventScroll: true}});
        inp.blur();
        inp.focus({{preventScroll: true}});
        syncClear(inp);
    }}

    // The X carries NO listeners of its own - see the delegated handlers below.
    // Attaching them here is what made the button permanently inert: they were
    // closures from the iframe realm alive at CREATION time, and because the
    // node survives Streamlit's reruns, `if (!btn)` never fired again, so they
    // were never replaced. The realm is torn down on the very next rerun and a
    // listener from a dead realm silently stops firing - the X worked once (or
    // not at all, if it was healed in by an already-dead observer) and then
    // ignored every click forever.
    function syncClear(inp) {{
        var shell = inp.closest('div[data-baseweb="input"]');
        if (!shell) return;
        var btn = shell.querySelector('button.cs-clear-search');
        if (!btn) {{
            btn = doc.createElement('button');
            btn.type = 'button';
            btn.className = 'cs-clear-search';
            btn.setAttribute('aria-label', 'Clear search');
            btn.title = 'Clear search';
            shell.appendChild(btn);
        }}
        btn.setAttribute('data-visible', inp.value ? '1' : '0');
    }}

    // Delegated on the document and REBOUND on every injection (`bind` above),
    // so the handler always belongs to the live realm no matter how long the X
    // node itself has been in the DOM.
    function clearTarget(ev) {{
        var t = ev.target;
        if (!t || !t.closest) return null;
        var btn = t.closest('button.cs-clear-search');
        if (!btn) return null;
        // Scope to THIS namespace: several search fields (page + dialog) can be
        // mounted at once, and a document-level handler sees all of their X's.
        var shell = btn.closest('div[data-baseweb="input"]');
        var field = shell && shell.querySelector('input');
        return (field && isField(field)) ? field : null;
    }}
    // mousedown default would blur the field first, firing an extra Streamlit
    // commit before the click lands.
    bind('mousedown', function(ev) {{ if (clearTarget(ev)) ev.preventDefault(); }});
    bind('click', function(ev) {{
        var field = clearTarget(ev);
        if (!field) return;
        ev.preventDefault(); ev.stopPropagation();
        clearValue(field);
    }});

    // ── Keep the X attached ──
    // The button must be SELF-HEALING, not attached once. It is injected into a
    // React-owned subtree (BaseWeb's input shell), so React discards it on its
    // next render pass - which is every Streamlit rerun. A one-shot attach (or
    // even a retry loop) therefore only appears to work right after an event that
    // happens to re-create it; on a cold load the X was measurably absent.
    //
    // A MutationObserver on the field's own subtree re-adds it whenever it goes
    // missing, and keeps data-visible in sync when Streamlit re-renders the input
    // with a value already in it. Observer + listeners are rebound on every
    // injection per the components.html rule (a callback created in an iframe
    // realm Streamlit later destroys stops firing), with the previous observer
    // disconnected first so they cannot pile up.
    function heal() {{
        var field = doc.querySelector(SELECTOR);
        if (field) syncClear(field);
    }}

    try {{ if (reg.observer) reg.observer.disconnect(); }} catch (_e) {{}}
    reg.observer = new win.MutationObserver(function() {{
        // Guard against reacting to our own insertion.
        if (reg.healing) return;
        reg.healing = true;
        try {{ heal(); }} finally {{ reg.healing = false; }}
    }});
    reg.observer.observe(doc.body, {{childList: true, subtree: true}});
    heal();
    bind('focusin', function(ev) {{ if (isField(ev.target)) syncClear(ev.target); }});
}})();
</script>""",
        height=0,
    )


def _gate_actions_on_selection(*button_keys: str) -> None:
    """Paint the given buttons as unavailable while no course is selected.

    Reads ``#cdp_selected_courses_count``, the hidden marker the course-list
    fragment already re-emits on every checkbox click, and mirrors it onto a
    ``data-cd-has-sel`` attribute on ``document.body`` plus a live ``title``
    tooltip on each button's wrapper.

    Why not Streamlit's ``disabled=``: the course list is an ``@st.fragment``, so
    a checkbox click reruns the fragment only. These buttons are rendered OUTSIDE
    it, so their ``disabled=`` would be evaluated from the selection as it was at
    the last FULL-page rerun and would stay stale after the user selects a course.
    ``shared.components.live_enable_button`` documents the same hazard for
    text-input-gated buttons; this is the checkbox-gated sibling.

    **The flag is on <body>, not on the buttons** (changed 2026-07-26). Streamlit
    re-creates the button elements on every full rerun, and a brand-new button
    carries no attribute - so for the ~50 measured milliseconds until the
    observer caught up, both primary actions painted at FULL brightness and then
    dropped back to the disabled paint. That is the "the buttons flash bright for
    half a second" report, and it fired on every rerun of this page, not just the
    Help one. ``<body>`` is never replaced, so the very first frame of a new
    button is already correct. The CSS is written as ``:not([...="1"])`` for the
    same reason: unknown state has to read as unavailable, never as available.

    A MutationObserver on the marker keeps the paint in sync without polling.
    Following the CLAUDE.md rule for ``components.html`` bridges, the observer and
    listeners are rebound on EVERY injection (a listener created inside an iframe
    realm that Streamlit later destroys silently stops firing), with the previous
    observer disconnected first so they cannot pile up.
    """
    import json
    import streamlit.components.v1 as components

    keys = [k.lower() for k in button_keys]
    wrappers = ', '.join(f'div[class*="st-key-{k}"]' for k in keys)
    # Same recipe as global.css `button[disabled]` and live_enable_button, so the
    # app has exactly ONE way of looking unavailable. These three used to differ:
    # this one and live_enable_button painted a flat rgba(255,255,255,0.075) slab
    # while native disabled desaturated the real colours.
    #
    # A `filter` on the button also dims its ::before icon glyphs, so the separate
    # opacity rule those needed under the old flat-slab approach is now redundant.
    _unsel = 'body:not([data-cd-has-sel="1"])'
    css = (
        f'{", ".join(f"""{_unsel} div[class*="st-key-{k}"] button""" for k in keys)} {{'
        '  filter: brightness(0.5) saturate(0.5) !important;'
        '  box-shadow: none !important;'
        '  cursor: not-allowed !important;'
        '  pointer-events: none !important;'
        '}'
        # cursor must also sit on the wrapper - pointer-events:none on the button
        # stops it resolving there, and it carries the explanatory title.
        f'{", ".join(f"""{_unsel} div[class*="st-key-{k}"]""" for k in keys)} {{'
        '  cursor: not-allowed !important;'
        '}'
    )

    components.html(
        f"""<script>
(function(){{
    var win = window.parent, doc = win.document;
    var WRAP_SEL = {json.dumps(wrappers)};
    var TIP = "Select at least one course above first.";
    var reg = win._cdSelGate || (win._cdSelGate = {{observer: null, styleId: 'cd-sel-gate-css'}});

    var st = doc.getElementById(reg.styleId);
    if (!st) {{
        st = doc.createElement('style'); st.id = reg.styleId; doc.head.appendChild(st);
    }}
    st.textContent = {json.dumps(css)};

    function apply() {{
        var marker = doc.getElementById('cdp_selected_courses_count');
        // No marker yet (list still loading) - treat as "no selection" so the
        // buttons never flash enabled before the real count arrives.
        var n = marker ? parseInt(marker.getAttribute('data-count') || '0', 10) : 0;
        var has = (n > 0) ? '1' : '0';
        // One write, on the one element Streamlit never replaces.
        if (doc.body.getAttribute('data-cd-has-sel') !== has) {{
            doc.body.setAttribute('data-cd-has-sel', has);
        }}
        // Only the BLOCKED reason is a tooltip. What the button does lives in
        // the caption under it - a tooltip that fires on every approach to a
        // button you already understand is noise, not help.
        //
        // NEVER put this title on the button itself: the disabled paint above
        // sets `pointer-events: none` on it, so a title there can never be
        // hovered - which is exactly why the "select a course first" tooltip
        // appeared to be missing. The WRAPPER still receives the hover.
        doc.querySelectorAll(WRAP_SEL).forEach(function(w) {{
            if (has === '0') {{ w.setAttribute('title', TIP); }}
            else {{ w.removeAttribute('title'); }}
            var b = w.querySelector('button');
            if (b) b.removeAttribute('title');
        }});
    }}

    // Rebind: disconnect the previous observer (its realm may be dead) and
    // observe the CURRENT document subtree for the marker being replaced.
    try {{ if (reg.observer) reg.observer.disconnect(); }} catch (_e) {{}}
    reg.observer = new win.MutationObserver(function() {{ apply(); }});
    reg.observer.observe(doc.body, {{childList: true, subtree: true, attributes: true,
                                    attributeFilter: ['data-count']}});
    apply();
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


def _cs_select_all(visible_ids: set) -> None:
    """Select every course currently on screen (Select All ``on_click``).

    ``visible_ids`` is captured when the button is RENDERED, which is the same
    view the user is looking at when they click it.
    """
    current_ids = set(st.session_state.get('selected_course_ids', []))
    st.session_state['selected_course_ids'] = list(current_ids.union(visible_ids))
    for cid in visible_ids:
        st.session_state[f"dl_chk_{cid}"] = True


def _cs_clear_selection(all_course_ids: list) -> None:
    """Clear the whole selection (Clear Selection ``on_click``).

    Resets checkbox widget state across the ENTIRE course universe, not just the
    current view. ``selected_course_ids`` is global, so resetting only the
    visible view would leave a stale ``dl_chk=True`` on a course selected in the
    other view (e.g. a non-favorite picked in All Courses) - which the list
    reconciliation would then resurrect as "selected" on the next switch.
    """
    st.session_state['selected_course_ids'] = []
    for cid in all_course_ids:
        st.session_state[f"dl_chk_{cid}"] = False


def _cs_start_refresh() -> None:
    """Raise the refresh flag (Refresh ``on_click``); step 2 does the fetch."""
    st.session_state['_dl_courses_refreshing'] = True


@st.fragment
def _course_list_section(
    courses: list, all_courses: list, favorites_only: bool, fetch_courses_fn=None
) -> None:
    """Fragment: CBS filters + Select All/Clear + count + refresh + search + list.

    ``fetch_courses_fn`` is the cached fetcher from render_course_selector; the
    Refresh button needs it to invalidate the cache before re-fetching.

    Scopes checkbox-click and search reruns to this fragment only, keeping the
    wizard header and page chrome stable.

    Args:
        courses: Courses for the active view (favorites or all), pre-CBS.
        all_courses: The complete course list, used to tell the user when a
            searched course exists outside the current favorites view.
        favorites_only: Whether the favorites pill is currently active.
    """
    filtered_courses = render_cbs_filters(courses, "dl")

    # ── Everything the toolbar PRINTS is resolved before the toolbar renders ──
    #
    # This ordering is the whole fix for the count flicker, so do not undo it.
    # The count used to be an `st.empty()` placeholder here, filled at the very
    # end of the fragment - because the checkbox list reconciles the selection
    # as it renders, and reading it inline showed the number from BEFORE the
    # user's click.
    #
    # The placeholder cost far more than it bought. `st.empty()` is not a
    # reservation, it is an ELEMENT: it enqueues an `Empty` delta immediately,
    # and Streamlit's runtime flushes the message queue on a ~10ms tick
    # (`Runtime._loop_coroutine`). The fill only happens after the 33-row list,
    # two `components.html` bridges and the marker div - far more than one tick
    # later - so the browser genuinely received "count → Empty", rendered it,
    # and only then received "Empty → count". Measured in-browser with a
    # MutationObserver on a single checkbox click:
    #     t=6302.3  REMOVED  stMarkdown "2 of 33 selected"
    #     t=6309.7  ADDED    stEmpty
    #     t=6378.0  REMOVED  stEmpty            (68ms later)
    #     t=6384.9  ADDED    stMarkdown "3 of 33 selected"
    # The count is a flex item, so for those ~76ms the row reflowed and the
    # search field and Refresh button slid 106px left (measured 764 → 658) and
    # back. On every keystroke in the search box that is one full cycle per
    # letter, which is the reported "unconsentual nightclub".
    #
    # `resolve_multi_selection()` removes the reason for the placeholder: the
    # post-click selection is knowable up front, because Streamlit applies
    # widget state before the script body runs. The count is now a plain
    # `st.markdown` in its final position, so a rerun only patches its text.
    query = st.session_state.get('course_search', '') or ''
    displayed_courses = _filter_and_rank_courses(filtered_courses, query)
    # "Select All" applies to exactly what the user currently sees.
    visible_ids = {c.id for c in displayed_courses}
    sel_count = len(resolve_multi_selection(displayed_courses, "dl"))

    # --- Action buttons row + inline search box ---
    # The search box lives in the same row as Select All / Clear Selection and
    # stretches to the far right (see the flex reflow CSS in
    # render_course_selector). Its query is held in `course_search` session
    # state, so it survives the favorites/all toggle (a full-page rerun)
    # seamlessly - the filter re-applies to whichever view is shown.
    #
    # All three buttons use `on_click=` rather than `if st.button(): ...;
    # st.rerun()`. A click already schedules a rerun, so the explicit one made
    # the fragment render TWICE - the first pass painting the pre-click count
    # and list before being thrown away. (Same rule as the sync-history toggle
    # in CLAUDE.md.) A callback runs before the script body, so the single
    # render that remains is already the post-click one.
    with st.container(key="action_btns_row", border=True):
        st.button(
            'Select All', key="btn_course_select_all",
            on_click=_cs_select_all, args=(visible_ids,),
        )
        st.button(
            'Clear Selection', key="btn_course_clear_selection",
            on_click=_cs_clear_selection, args=([c.id for c in all_courses],),
        )
        # Live selection count, grouped with the controls that change it.
        #
        # The hidden ghost span reserves the width. Both numbers shrink while
        # you type ("0 of 33" → "0 of 6"), and a narrower box drags the divider,
        # the Refresh button and the search field 7px left and back on every
        # keystroke that changes a digit count - small, but it is a moving
        # target right where the user is looking. The ghost is sized from
        # `all_courses`, which is the widest either number can ever get and is
        # constant until the list is re-fetched, so the box never resizes at all.
        # (Both spans carry the WHOLE string: splitting it across grid items
        # would drop the spaces between them - see the note on the CSS.)
        # The ghost carries the <b> too: bold digits are wider than plain ones,
        # so a plain-text sizer let the live label outgrow it by ~0.9px and the
        # box still twitched by a pixel. Same markup, same metrics.
        _ghost_html = f"<b>{len(all_courses)}</b> of {len(all_courses)} selected"
        st.markdown(
            f"<div class='cs-sel-count'>"
            f"<span class='cs-sel-count-ghost' aria-hidden='true'>{_ghost_html}</span>"
            f"<span class='cs-sel-count-live'>"
            f"<b>{sel_count}</b> of {len(displayed_courses)} selected</span></div>",
            unsafe_allow_html=True,
        )
        st.button(
            "​", key="btn_course_refresh",
            on_click=_cs_start_refresh,
            help="Refresh the course list from Canvas.",
        )
        st.text_input(
            "Search courses",
            key="course_search",
            placeholder="Search courses by name or code…",
            label_visibility="collapsed",
        )

    # Refresh is a TWO-STEP dance, and the two steps exist to keep this toolbar
    # mounted throughout.
    #
    # Step 1 is the `_cs_start_refresh` callback above: it only raises a flag,
    # and the click's own fragment rerun does the rest. The cache is
    # deliberately left warm, so that rerun is instant and re-renders the
    # toolbar in place (same elements, same order - React reconciles, nothing
    # unmounts) while swapping ONLY the list box below for a spinner.
    #
    # Step 2 is at the bottom of this function: with the spinner on screen it
    # clears the cache and reruns app-scoped, and the blocking network fetch
    # happens while the browser is still showing this frame.
    #
    # The old version cleared the cache and reran app-scoped immediately, which
    # meant the page-level boot spinner replaced this entire section - toolbar
    # included - and the row's contents visibly collapsed and re-formed on every
    # refresh.
    refreshing = bool(st.session_state.get('_dl_courses_refreshing'))

    # ONE slot, written exactly once per run. It has to be an st.empty():
    # rendering the spinner into a plain `st.container` with the same key left
    # the previous run's checkbox rows mounted underneath it (Streamlit only
    # trims a container's surplus children when the script run ends, and this
    # run ends in a rerun), so the spinner appeared ABOVE a greyed-out list
    # instead of replacing it. `st.empty()` swaps the whole subtree atomically.
    _list_slot = st.empty()

    if refreshing:
        # A plain ELEMENT in the slot, not a container. Two container-shaped
        # attempts both failed, in-browser, for the same underlying reason:
        # Streamlit reconciles a block by its DELTA PATH, and the `key` is only
        # a CSS class - so the spinner block was matched with the list block it
        # replaced and the previous run's 14 checkbox rows stayed mounted inside
        # it (Streamlit only trims a block's surplus children when the script
        # run ENDS, and this run ends in a rerun). Even a different key only
        # swapped the class. Writing an ELEMENT changes the node type, which
        # React cannot reconcile against a block - so the list is genuinely
        # unmounted and the swap is atomic.
        _list_slot.html(_COURSES_LOADING_BOX)
    elif displayed_courses:
        with _list_slot.container(key="course_list_box", border=True):
            render_course_list(
                displayed_courses, "dl", multi_select=True,
                first_item_top_offset="1px",
                sort=not query.strip(),  # already relevance-ranked when searching
            )
        # Shift-click range selection across the checkbox rows above.
        inject_shift_select_bridge("dl")
    else:
        # Distinct key → symmetric vertical padding so the notice sits evenly
        # between the top (buttons row) and bottom separators. Same slot, so
        # switching between list and empty-state is also an atomic swap.
        with _list_slot.container(key="course_list_empty", border=True):
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
    # Uses the SAME `sel_count` the toolbar printed - the JS gate and the label
    # the user reads must never be able to disagree about the selection.
    st.html(f"<div id='cdp_selected_courses_count' data-count='{sel_count}' style='display:none;'></div>")

    # Refresh, step 2 (see step 1 at the Refresh button). Everything above has
    # already been streamed to the browser, so the toolbar is on screen with a
    # spinner where the list was. The short sleep guarantees that frame paints
    # before the script blocks; then the cache is dropped and the app-scoped
    # rerun does the real network fetch. During that fetch the browser keeps
    # showing THIS frame - which is exactly the effect we want: toolbar intact,
    # spinner in the list.
    if refreshing:
        st.session_state['_dl_courses_refreshing'] = False
        # Long enough for the browser to actually PAINT the spinner frame
        # before the script blocks. At 0.15s the delta and the rerun landed so
        # close together that the frame was never observed in-browser at all.
        time.sleep(0.35)
        try:
            fetch_courses_fn.clear()
        except Exception:
            # A non-cached callable (or a Streamlit build without .clear) must
            # not break the button - the rerun below still re-renders.
            pass
        st.rerun(scope="app")

    # (The old 'course_selection_warning_shown' latch is gone: the Custom/Quick
    #  Download buttons are now disabled with an explanatory tooltip while nothing
    #  is selected, so there is no after-the-fact notice left to clear - and no
    #  extra rerun needed to clear it.)


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
    render_download_wizard(st, 'select')

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
    /* Button base styles. Refresh is included so it reads as the same kind of
       borderless, chrome-free control as its text siblings - without it the
       button keeps Streamlit's default secondary border/background and looks
       like a boxed-in outlier in the middle of the row. (Its explicit width is
       set further down; it is deliberately kept out of global.css's full-width
       button rules, which would stretch it across the row.) */
    div.st-key-btn_course_select_all button,
    div.st-key-btn_course_clear_selection button,
    div.st-key-btn_course_refresh button {{
        background-color: rgba(255, 255, 255, 0) !important;
        border-radius: 8px !important;
        border: 0px solid rgba(255, 255, 255, 0.1) !important;
        box-shadow: none !important;
        min-height: 38px !important;
        height: 38px !important;
        padding-left: 8px !important;
        padding-right: 8px !important;
        white-space: nowrap !important;
        width: auto !important;
        min-width: max-content !important;
    }}
    div.st-key-btn_course_select_all button:hover,
    div.st-key-btn_course_clear_selection button:hover,
    div.st-key-btn_course_refresh button:hover {{
        background-color: rgba(255, 255, 255, 0.02) !important;
        border-color: rgba(255, 255, 255, 0.00) !important;
    }}
    /* Kill the focus ring too - a lingering outline after clicking Refresh would
       re-introduce exactly the boxed look this section removes. */
    div.st-key-btn_course_refresh button:focus,
    div.st-key-btn_course_refresh button:focus-visible,
    div.st-key-btn_course_refresh button:active {{
        outline: none !important;
        box-shadow: none !important;
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
    /* ── Live selection count ──
       Sits with the Select All / Clear Selection controls it describes. Fixed
       to shrink-to-fit so it never competes with the flexible search field. */
    div[data-testid="stVerticalBlock"]:has(> div.st-key-btn_course_select_all) > div:has(> div > div > .cs-sel-count) {{
        flex: 0 0 auto !important;
        width: auto !important;
    }}
    /* Height 38px matches the buttons exactly, so the row's `align-items:center`
       lands the text on the same optical baseline as its neighbours instead of
       letting a short text box float above them.

       It draws only its LEFT divider. The divider on its right is the one the
       Refresh button already draws - reusing it keeps every divider in the row
       identical (a ::before at the left edge of the element it precedes) and
       avoids stacking two 1px lines into a double rule. */
    /* Vertical centring is done with `line-height: height`, NOT `display:flex`.
       Flex would turn the bold count element and the text node after it into two
       separate flex items, and whitespace BETWEEN flex items is discarded - the
       label rendered as "0of 15 selected". Matching line-height to height keeps
       the content in normal inline flow (space intact) while still centring it
       against the 38px buttons. */
    /* Streamlit's global -16px bottom margin on stMarkdownContainer shrank this
       label's element-container to 22px while its siblings are 38px. The row is
       `align-items: center`, so it centred that SHORT box and the 38px text
       inside it overhung 8px below the buttons' centre line - taking its own
       ::before divider with it. (Measured: siblings top 298.5 / h 38; this one
       top 306.5 / h 22 with 38px of content.) Zeroing the margin makes the
       container a true 38px, and centring then lands it exactly. */
    [data-testid="stMarkdownContainer"]:has(> .cs-sel-count) {{
        margin-bottom: 0 !important;
    }}
    /* A one-cell GRID with the live label and a hidden ghost stacked in it, so
       the box is as wide as the widest label it will ever hold and never
       resizes as the numbers shrink while the user types. Grid (not flex) and
       one span per COMPLETE string: flex discards the whitespace between flex
       items, which is what once rendered this label as "0of 15 selected".
       `line-height: 38px` still does the vertical centring inside each span. */
    .cs-sel-count {{
        position: relative !important;
        display: grid !important;
        grid-template-areas: "count" !important;
        height: 38px !important;
        line-height: 38px !important;
        font-size: 0.9rem !important;
        color: #ffffff !important;
        white-space: nowrap !important;
        margin: 0 0 0 {_TB_PRE}px !important;
        padding: 0 0 0 {_TB_PAD}px !important;
    }}
    .cs-sel-count > span {{
        grid-area: count !important;
        white-space: nowrap !important;
    }}
    /* Sizes the box; `visibility: hidden` keeps it out of sight AND out of the
       accessibility tree while still occupying its full width. */
    .cs-sel-count-ghost {{ visibility: hidden !important; }}
    .cs-sel-count b {{ color: #ffffff !important; font-weight: 700 !important; }}
    .cs-sel-count::before {{
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

    /* ── Refresh button (icon-only) ──
       An empty zero-width-space label + a masked lucide list-restart glyph, so
       the icon inherits the row's text colour and brightens on hover exactly
       like the neighbouring text buttons. */
    div.st-key-btn_course_refresh button {{
        min-width: 34px !important;
        width: 34px !important;
        padding: 0 !important;
    }}
    div.st-key-btn_course_refresh button p {{
        margin: 0 !important;
        width: 100% !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    div.st-key-btn_course_refresh button p::after {{
        content: "" !important;
        width: 17px !important;
        height: 17px !important;
        flex-shrink: 0 !important;
        background-color: currentColor !important;
        -webkit-mask-image: url("{_REFRESH_MASK}");
        mask-image: url("{_REFRESH_MASK}");
        -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
        -webkit-mask-position: center;  mask-position: center;
        -webkit-mask-size: contain;    mask-size: contain;
    }}

    /* Short vertical dividers split the row into four groups:
           [Select All · Clear Selection] │ [count] │ [Refresh] │ [search]
       Every divider is the same thing - a ::before at the left edge of the
       element it precedes - so the count's right-hand divider is simply the one
       Refresh draws.

       Spacing is symmetric BY CONSTRUCTION: _TB_PRE of margin sits before the
       divider (the row's own flex gap tops that up to _TB_PAD) and _TB_PAD of
       padding sits after it. Previously these were 9px and 7px, which - once the
       5px row gap is added - left the Refresh button 7px from its left divider
       and 14px from its right one, i.e. visibly off-centre between them. */
    div.st-key-course_search,
    div.st-key-btn_course_refresh {{
        position: relative !important;
        padding-left: {_TB_PAD}px !important;
        margin-left: {_TB_PRE}px !important;
    }}
    div.st-key-course_search::before,
    div.st-key-btn_course_refresh::before {{
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

    /* The clear-"X" is NOT styled here any more - its rules moved into
       _course_search_field_css() so every search field (this row AND every
       dialog's) gets them. Leaving them here made the button render as an
       unstyled white slab in the sync dialogs. */
    /* Shared borderless field + magnifier + clear-X visuals. */
    {_course_search_field_css('course_search')}
    </style>""")
    st.html('<div style="padding-bottom: 1rem;"></div>')

    # --- Favorites / All Courses pill toggle ---
    favorites_only = render_favorites_pill("dl")

    # Cold-boot placeholder, shown ONLY on the very first fetch of a session -
    # the one time there is genuinely nothing on screen to preserve.
    #
    # It is a SIBLING of the course section, never its parent. When it wrapped
    # the section, every later cache-miss (most visibly Refresh) tore the whole
    # thing down and rebuilt it, and the toolbar's controls were seen to
    # collapse and re-form. Now a later rerun leaves the previous frame on
    # screen while the fetch blocks, and only the parts that actually changed
    # are replaced.
    #
    # The placeholder is created unconditionally so the element index of
    # everything after it is identical on every run - only its CONTENT is
    # conditional.
    _first_load = not st.session_state.get('_dl_courses_loaded_once')
    _boot_area = st.empty()
    if _first_load:
        with _boot_area.container():
            st.html(
                '<div style="border:1px solid rgba(255,255,255,0.1);'
                'border-radius:8px;">' + _COURSES_LOADING_HTML + '</div>'
            )

    # --- Fetch (spinner above is visible during cache miss) ---
    # A token that expired/was revoked mid-session surfaces here as an Unauthorized
    # error. Route to the clean reconnect flow instead of crashing the page.
    try:
        all_courses = fetch_courses_fn(
            st.session_state['api_token'],
            st.session_state['api_url'])
    except Exception as _fetch_err:
        from core.canvas_logic import is_auth_error
        if is_auth_error(_fetch_err):
            from ui.auth import force_reauth
            if "expired" in str(_fetch_err).lower():
                force_reauth("Your Canvas Access Token has expired. Please reconnect with a new token.")
            else:
                force_reauth("Your Canvas connection expired or the access token was revoked. Please reconnect with a new token.")
        raise
    st.session_state['_dl_courses_loaded_once'] = True
    courses = [c for c in all_courses if c.is_favorite] if favorites_only else all_courses

    if not courses:
        with _boot_area.container():
            from ui.amber_notice import render_amber_notice
            render_amber_notice('No courses found.')
        st.stop()

    # Drop the cold-boot spinner (a no-op on every run after the first) and
    # render the section as its own sibling, at a fixed position in the tree.
    _boot_area.empty()
    _course_list_section(courses, all_courses, favorites_only, fetch_courses_fn)

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
    div.st-key-btn_custom_download button:hover:not(:disabled) {{
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
    /* `:not(:disabled)` - a hover `filter` would otherwise replace the shared
       disabled filter and make the greyed button brighter than its enabled self. */
    div.st-key-btn_quick_download button:hover:not(:disabled) {{
        filter: brightness(1.15) !important;
        box-shadow: 0 4px 15px rgba(37, 99, 235, 0.2),
                    inset 0 1px 1px rgba(255, 255, 255, 0.4) !important;
        color: #ffffff !important;
    }}
    </style>""")

    # `sticky_actions_` prefix = the shared sticky bottom bar (styled once in
    # global.css). This list is the page that needs it most: "All Courses" runs to
    # 30+ rows, and without it the two primary actions sit far below the fold.
    # Native `position: sticky`, so it self-disables on a page short enough not to
    # scroll - no JS, no scroll listeners.
    _hints = help_text_enabled()
    _action_cols = [0.75, 0.16, 0.75, 2.34]
    with st.container(key="sticky_actions_courses"):
        col_custom, col_or, col_quick, _ = st.columns(_action_cols, gap="small",
                                                      vertical_alignment="top")
        with col_custom:
            advanced_clicked = st.button('Custom Download', type="primary", use_container_width=True,
                                         key="btn_custom_download")
        with col_or:
            st.markdown(f"<div class='cd-action-or' style='text-align:center; font-weight:bold; color:{theme.TEXT_DIM}; font-size:0.9em; white-space:nowrap; word-break:keep-all;'>OR</div>", unsafe_allow_html=True)
        with col_quick:
            quick_clicked = st.button('Quick Download', type="primary", use_container_width=True,
                                      key="btn_quick_download")

    # The captions go AFTER the bar, not inside it. Inside, their height was
    # reserved in the pinned bar even though they are invisible while it floats,
    # which lifted both buttons 41 measured pixels and covered a course row for
    # no benefit. Out here the bar is exactly as tall as it is with help text
    # off, and the captions scroll into view under their own buttons as the bar
    # releases. Same column widths, so each caption stays under its button.
    # (See the ".cd-action-hint" block in global.css for why not opacity or
    # display:none.)
    if _hints:
        with st.container(key="action_hints_courses"):
            _hc, _ho, _hq, _ = st.columns(_action_cols, gap="small", vertical_alignment="top")
            with _hc:
                st.markdown(f"<div class='cd-action-hint'>{esc(_CUSTOM_DOWNLOAD_HINT)}</div>",
                            unsafe_allow_html=True)
            with _hq:
                st.markdown(f"<div class='cd-action-hint'>{esc(_QUICK_DOWNLOAD_HINT)}</div>",
                            unsafe_allow_html=True)

    # Paint both actions as unavailable (and unclickable) until a course is
    # selected, replacing the old after-the-fact "Please select at least one
    # course" amber notice.
    #
    # NOT `disabled=`: the course list is a FRAGMENT, so ticking a checkbox
    # reruns only the fragment - these buttons live outside it and would keep
    # their stale disabled state until some unrelated full-page rerun. (Measured:
    # checkbox ticked, marker div read 1, buttons still disabled.) This is the
    # same trap shared.components.live_enable_button documents for text inputs,
    # so the same remedy applies: keep the buttons genuinely enabled server-side
    # and gate appearance + pointer-events client-side off the live count marker.
    _gate_actions_on_selection("btn_custom_download", "btn_quick_download")

    st.html("<div style='height: 20px;'></div>")

    if quick_clicked or advanced_clicked:
        # Defensive: the client-side gate sets pointer-events:none while nothing
        # is selected, but never trust the DOM for correctness.
        if not st.session_state.get('selected_course_ids'):
            st.rerun()
        if quick_clicked:
            # Always start Quick Download with no preset selected.
            st.session_state.pop('quick_preset_id', None)
        st.session_state['quick_download_mode'] = quick_clicked
        st.session_state['step'] = 2
        st.rerun()
