"""
Shared UI components for Download and Sync completion screens.
Extracted to ensure perfect visual parity between both modes.
"""
import os
import streamlit as st
from pathlib import Path
from shared.helpers import (
    open_folder, open_file, reveal_in_folder, esc, short_path,
    declined_reason_sentence, split_delivery_errors,
)
from shared import theme
from core.sync_manager import format_file_size
from core.preset_manager import PresetManager


# --- Professional inline SVG icons for help card section headers ---
# Feather-style stroke icons. Use inside help card text_html to replace emojis.
# Sized at 18×18 with themed stroke colors for consistency.
_ICON_STYLE = 'display:inline-block;vertical-align:middle;position:relative;top:-1px;margin:0 4px;flex-shrink:0;'

# Inline SVG paths for each icon - keyed by Material icon name.
# Eliminates the Google Fonts dependency so icons work in the packaged app
# regardless of network access or font-load timing.
_MAT_SVG_INNER: dict[str, str] = {
    'lightbulb': "<line x1='9' y1='18' x2='15' y2='18'/><line x1='10' y1='22' x2='14' y2='22'/><path d='M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z'/>",
    'folder':    "<path d='M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z'/>",
    'shield':    "<path d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'/>",
    'database':  "<ellipse cx='12' cy='5' rx='9' ry='3'/><path d='M21 12c0 1.66-4 3-9 3s-9-1.34-9-3'/><path d='M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5'/>",
    'build':     "<path d='M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z'/>",
    'help':      "<circle cx='12' cy='12' r='10'/><path d='M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3'/><line x1='12' y1='17' x2='12.01' y2='17'/>",
    'star':      "<polygon points='12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2'/>",
    'inventory_2': "<path d='M21 8V21H3V8'/><rect x='1' y='3' width='22' height='5'/><line x1='10' y1='12' x2='14' y2='12'/>",
    'check_circle': "<path d='M22 11.08V12a10 10 0 1 1-5.93-9.14'/><polyline points='22 4 12 14.01 9 11.01'/>",
    'arrow_selector_tool': "<path d='M5 3l14 9-7 1-4 7z'/>",
    'visibility': "<path d='M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'/><circle cx='12' cy='12' r='3'/>",
    'archive':   "<polyline points='21 8 21 21 3 21 3 8'/><rect x='1' y='3' width='22' height='5'/><line x1='10' y1='12' x2='14' y2='12'/>",
    'menu':      "<line x1='3' y1='12' x2='21' y2='12'/><line x1='3' y1='6' x2='21' y2='6'/><line x1='3' y1='18' x2='21' y2='18'/>",
    'calendar_today': "<rect x='3' y='4' width='18' height='18' rx='2' ry='2'/><line x1='16' y1='2' x2='16' y2='6'/><line x1='8' y1='2' x2='8' y2='6'/><line x1='3' y1='10' x2='21' y2='10'/>",
    'error':     "<circle cx='12' cy='12' r='10'/><line x1='12' y1='8' x2='12' y2='12'/><line x1='12' y1='16' x2='12.01' y2='16'/>",
}


SVG_FOLDER_YELLOW = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#facc15" style="width:1.4em; height:1.4em; vertical-align:-0.2em; display:inline-block; margin-right:4px;"><path d="M20 5h-7.586l-2-2H4c-1.103 0-2 .897-2 2v14c0 1.103.897 2 2 2h16c1.103 0 2-.897 2-2V7c0-1.103-.897-2-2-2z"/></svg>'
SVG_EDIT_WHITE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#ffffff" style="width:1.4em; height:1.4em; vertical-align:-0.2em; display:inline-block; margin-right:4px;"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>'
SVG_TRASH_WHITE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#ffffff" style="width:1.4em; height:1.4em; vertical-align:-0.2em; display:inline-block; margin-right:4px;"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>'
SVG_CLOCK = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#8b949e" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="width:1.15em; height:1.15em; vertical-align:-0.2em; display:inline-block; margin-right:4px;"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/></svg>'
SVG_SAVE_COLORFUL = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" '
    'style="width:1.6em; height:1.6em; vertical-align:-0.3em; display:inline-block; margin-right:4px;">'
    '<path d="M36 106 A70 70 0 0 1 106 36 H404 L476 108 V406 A70 70 0 0 1 406 476 H106 A70 70 0 0 1 36 406 Z" fill="#5C5C94"/>'
    '<path d="M116 36 H396 V182 A26 26 0 0 1 370 208 H142 A26 26 0 0 1 116 182 Z" fill="#2E1A33"/>'
    '<path d="M176 36 H336 V158 A22 22 0 0 1 314 180 H198 A22 22 0 0 1 176 158 Z" fill="#E6E6E6"/>'
    '<rect x="288" y="56" width="36" height="104" rx="12" fill="#5C5C94"/>'
    '<path d="M96 244 A8 8 0 0 1 104 236 H408 A8 8 0 0 1 416 244 V450 A10 10 0 0 1 406 460 H106 A10 10 0 0 1 96 450 Z" fill="#E6E6E6"/>'
    '<path d="M96 244 A8 8 0 0 1 104 236 H408 A8 8 0 0 1 416 244 V280 H96 Z" fill="#ED3B34"/>'
    '</svg>'
)


SVG_SAVE_COLORFUL_SMALL = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" '
    'style="width:1.0em; height:1.0em; vertical-align:-0.15em; display:inline-block; margin-right:3px;">'
    '<path d="M36 106 A70 70 0 0 1 106 36 H404 L476 108 V406 A70 70 0 0 1 406 476 H106 A70 70 0 0 1 36 406 Z" fill="#5C5C94"/>'
    '<path d="M116 36 H396 V182 A26 26 0 0 1 370 208 H142 A26 26 0 0 1 116 182 Z" fill="#2E1A33"/>'
    '<path d="M176 36 H336 V158 A22 22 0 0 1 314 180 H198 A22 22 0 0 1 176 158 Z" fill="#E6E6E6"/>'
    '<rect x="288" y="56" width="36" height="104" rx="12" fill="#5C5C94"/>'
    '<path d="M96 244 A8 8 0 0 1 104 236 H408 A8 8 0 0 1 416 244 V450 A10 10 0 0 1 406 460 H106 A10 10 0 0 1 96 450 Z" fill="#E6E6E6"/>'
    '<path d="M96 244 A8 8 0 0 1 104 236 H408 A8 8 0 0 1 416 244 V280 H96 Z" fill="#ED3B34"/>'
    '</svg>'
)


# Small versions for compact configuration summary badges & tags
SVG_FOLDER_YELLOW_SMALL = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#facc15" style="width:1.35em; height:1.35em; vertical-align:-0.25em; display:inline-block; margin-right:4px;"><path d="M20 5h-7.586l-2-2H4c-1.103 0-2 .897-2 2v14c0 1.103.897 2 2 2h16c1.103 0 2-.897 2-2V7c0-1.103-.897-2-2-2z"/></svg>'

# Solid book/reader glyph - a filled silhouette with its text lines *subtracted*
# (fill-rule evenodd punches the inner rects into holes). The "this is a Canvas
# course" mark, used by Today's daily-sync chips and by the sync-list card's
# course pill. Defined ONCE here because those two are meant to read as the same
# chip; a second copy of the path is how they would stop being.
COURSE_BOOK_PATH = (
    "M6 3H18A2 2 0 0 1 20 5V19A2 2 0 0 1 18 21H6"
    "A2 2 0 0 1 4 19V5A2 2 0 0 1 6 3Z"
    "M7.5 8H16.5V9.4H7.5ZM7.5 11.3H16.5V12.7H7.5ZM7.5 14.6H13.5V16H7.5Z"
)


def svg_course_book(css_class: str = "", size_px: int = 16) -> str:
    """The course glyph, tinted by the parent's ``color``.

    The inline size is REQUIRED, not cosmetic: this markup can outlive the
    stylesheet that sizes it during a page transition (Streamlit briefly leaves
    the old DOM in place), and an unsized inline SVG balloons to its default
    replaced-element box - a full-width icon on the next screen.
    """
    cls = f" class='{css_class}'" if css_class else ""
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
        f"fill='currentColor'{cls} "
        f"style='width:{size_px}px;height:{size_px}px;flex-shrink:0;'>"
        f"<path fill-rule='evenodd' d='{COURSE_BOOK_PATH}'/></svg>"
    )


SVG_COURSE_PILL = svg_course_book()
SVG_EDIT_WHITE_SMALL = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#ffffff" style="width:1.1em; height:1.1em; vertical-align:-0.15em; display:inline-block; margin-right:4px;"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>'


def fresh_container(*, border: bool | None = None, key: str | None = None):
    """A ``st.container`` that cannot inherit the previous run's children.

    Streamlit reconciles by POSITION, and ``AppRoot.addBlock`` deliberately
    REUSES the children of whatever block already sits at that index (read out
    of the 1.51 bundle)::

        const existing = this.root.getIn(deltaPath);
        let children = [];
        if (existing instanceof BlockNode && existing.deltaBlock.type === block.type)
            children = existing.children;      // <- inherited

    A run dashboard and a completion card are both plain ``vertical`` blocks,
    so a completion card landing on the index the run's
    ``st.container(key="progress_dashboard")`` occupied is handed that node's
    children: the metrics row and the terminal log render INSIDE the green
    "Download Success" card. They only disappear when ``clearStaleNodes`` runs,
    which happens when the script run FINISHES - so they sit there for as long
    as the completion screen takes to build, with the folder cards stacking up
    underneath, and then the card shrinks and everything below it jumps up.
    (Reported 2026-07-26 for Panopto -> complete, retry -> complete, and every
    sync completion.)

    This emits a bare ``st.empty()`` FIRST, so:

    * the old block's node at that index is replaced by an ElementNode - the
      dashboard is torn down by the third element of the run, not at the end;
    * the card itself lands one index later, where the run screens have a plain
      markdown/button, and ``addBlock`` finds no block to inherit from.

    **The empty must land on a DIFFERENT index than the container** - measured
    2026-07-26. ``placeholder.container()`` reuses the placeholder's locked
    cursor, so both deltas carry the SAME delta path, and ``ForwardMsgQueue``
    composes two deltas at one path into the last one: the ``empty`` is dropped
    before it ever reaches the browser and the children are inherited exactly
    as before. (Streamlit's own comment there calls this out - it is the trick
    ``st.write`` relies on.) The extra slot is free: a bare ``st.empty()``
    renders a **zero-height** ``stElementContainer``, and the sync completion
    screen measures byte-identical with and without it (h2 bottom 243, card top
    243, card height 157 in both).

    Use this for any container a terminal screen renders at an index where a
    still-running screen also renders one.

    **Do NOT reach for this inside a LIST** - use :func:`pad_slot_children`
    instead. In a list every index already holds another row of the same shape,
    so the leading empty does not find a clean index, it just moves the block
    onto the NEXT row and inherits that one. See its docstring.
    """
    st.empty()
    return st.container(border=border, key=key)


# Every element that can occupy one slot of the sync list presents this many
# children. The number comes from the widest of them - the pair row's
# st.columns([5, 1.5, 1.1, 1.5, 1.2]) in sync_ui._sync_pairs_section.
SYNC_LIST_SLOT_CHILDREN = 5


def pad_slot_children(used: int, total: int = SYNC_LIST_SLOT_CHILDREN) -> None:
    """Emit blank children until this container has *total* of them.

    Streamlit reconciles by index, and ``AppRoot.addBlock`` hands a new block
    the CHILDREN of whatever block already sat at its index. Only the children
    your own elements overwrite go away; the rest survive until
    ``clearStaleNodes``, which runs when the script run FINISHES. So when two
    different widgets can render at one index, the one with FEWER children
    leaves the other's tail on screen - inside itself.

    Measured on the sync page 2026-07-30, both directions of the same slot:

    * pair row (5 children) -> edit form (4): the row's red **Remove** button
      rendered inside the open edit form, which stood at 247px instead of 193px;
    * add/edit form (5) -> "Add Course" row (3): the form's **Cancel** and
      **Confirm and Add** buttons stayed under the restored Add Course row for
      22ms, the slot at 112px instead of 48px.

    A bare ``st.empty()`` is a zero-height ``stElementContainer``, so the
    padding is free - but the container's own flex ``gap`` is NOT, and four
    zero-height children still cost four gaps. Any container padded this way
    must set ``gap: 0`` (see ``styles/global.css``).

    This is the right tool inside a list; :func:`fresh_container` is not.
    """
    for _ in range(max(0, total - used)):
        st.empty()


def resolve_courses_or_stop(fetch_courses_fn, *, retry_key: str = "courses_action_retry"):
    """Fetch the course list for an ACTION (Start Download / Start Sync) and
    handle failure gracefully - never let a raw exception reach the page.

    - **Auth failure** (expired/revoked token): route to the clean reconnect
      flow via ``force_reauth`` (which reruns into the cut-to-the-bone reauth
      screen), pre-serving the saved Canvas URL.
    - **Non-auth failure** (offline, captive portal, timeout, TLS intercept,
      Canvas down): show a calm amber notice + a Try-again button and
      ``st.stop()`` - the page stays put, the sidebar (logout/nav) is intact.

    Returns the course list on success. Mirrors the course-selector cold-fetch
    handling so every fetch site behaves the same. These action fetches almost
    always serve from the warm cache set at course selection, so this only
    fires in the rare cold-fail case - but when it does, it must not be a red
    traceback in the middle of starting a run.
    """
    try:
        return fetch_courses_fn(st.session_state['api_token'], st.session_state['api_url'])
    except Exception as _err:
        from core.canvas_logic import is_auth_error
        if is_auth_error(_err):
            from ui.auth import force_reauth
            if "expired" in str(_err).lower():
                force_reauth("Your Canvas Access Token has expired. Please reconnect with a new token.")
            else:
                force_reauth("Your Canvas connection expired or the access token was revoked. Please reconnect with a new token.")
        from ui.amber_notice import render_amber_notice
        render_amber_notice(
            "We couldn't reach Canvas",
            detail=("Check your internet connection and try again. On campus or office wifi you "
                    "may need to sign in to the network first, or switch off a VPN. Your login is still saved."),
        )
        if st.button("Try again", key=retry_key, type="primary"):
            try:
                fetch_courses_fn.clear()
            except Exception:
                pass
            st.rerun()
        st.stop()


def live_enable_button(input_key: str, button_key: str, *,
                       require_change_from: str | None = None,
                       reason: str = "") -> None:
    """Make a Save button look enabled/disabled live as the user types, while
    keeping it GENUINELY clickable server-side so a single click always works.

    Why the button must NOT be server-side ``disabled=``: Streamlit only commits
    a text input's value (and reruns to re-evaluate ``disabled=``) on blur/Enter.
    A validity-gated ``disabled=True`` button therefore stays disabled
    *server-side* until the value commits - so the user's first click is
    swallowed (it merely blurs the input and triggers the rerun that finally
    enables the button), and only the second click registers. Forcing the
    DOM ``disabled`` attribute off via JS does not help: React still has
    ``disabled=true`` internally and suppresses its synthetic onClick.

    The fix: render the button with ``disabled=False`` (always genuinely
    clickable) and gate the actual save inside the click handler. This helper
    then only handles the *appearance*: it toggles a ``data-cd-valid`` attribute
    on the button as the user types and injects parent-document CSS that greys
    the button out and sets ``pointer-events:none`` while invalid. When the
    value is valid the button looks and behaves like a normal enabled button, so
    one click both commits the typed value and fires the action - no two-click,
    no stale ``help`` tooltip (call sites pass no dynamic ``help``).

    Call this once, AFTER both the ``st.text_input`` and the ``st.button`` have
    been rendered (only their keys matter, not call order vs. this helper).

    Args:
        input_key:           ``key=`` of the ``st.text_input`` that gates the button.
        button_key:          ``key=`` of the ``st.button`` to grey out while invalid.
        require_change_from: if given, the button also looks disabled while the
                             trimmed input equals this baseline (used by rename
                             dialogs, where an unchanged name is a no-op).
        reason:              why the button is unavailable, shown as a native
                             tooltip while it is greyed. Set on the WRAPPER, not
                             the button - the button carries
                             ``pointer-events:none`` so a title on it would never
                             fire a hover. Cannot be Streamlit's ``help=``: that
                             is fixed at render time and so could not disappear
                             once the field becomes valid.
    """
    import json
    import streamlit.components.v1 as components

    # Streamlit lowercases widget keys when generating st-key-* DOM classes.
    in_cls = f"st-key-{input_key.lower()}"
    btn_cls = f"st-key-{button_key.lower()}"
    baseline_js = json.dumps(require_change_from or "")
    require_change = "true" if require_change_from is not None else "false"
    style_id = f"cd-live-css-{button_key.lower()}"
    # CSS that paints the (genuinely enabled) button as disabled while invalid.
    # Deliberately IDENTICAL to global.css's `button[disabled]` recipe, so a
    # JS-gated button and a natively disabled one are visually the same state.
    # They used to differ - this helper painted a flat rgba(255,255,255,0.075)
    # slab while native disabled desaturated the real colours - which read as two
    # unrelated "off" styles inside the same dialog. Keep the two in sync.
    # `cursor` sits on the WRAPPER because pointer-events:none on the button
    # stops it resolving there (and would also swallow the title tooltip).
    disabled_css = (
        f'div[class*="{btn_cls}"] button:not([data-cd-valid="1"]) {{'
        '  filter: brightness(0.5) saturate(0.5) !important;'
        '  box-shadow: none !important;'
        '  cursor: not-allowed !important;'
        '  pointer-events: none !important;'
        '}'
        f'div[class*="{btn_cls}"]:has(button:not([data-cd-valid="1"])) {{'
        '  cursor: not-allowed !important;'
        '}'
    )
    css_js = json.dumps(disabled_css)
    reason_js = json.dumps(reason or "")

    components.html(
        f"""
        <script>
        (function(){{
            var doc = window.parent.document;
            var IN_SEL   = '.{in_cls} input, .{in_cls} textarea';
            var BTN_SEL  = '.{btn_cls} button';
            var WRAP_SEL = '.{btn_cls}';
            var REQUIRE_CHANGE = {require_change};
            var BASELINE = {baseline_js};
            var STYLE_ID = {json.dumps(style_id)};
            var CSS = {css_js};
            var REASON = {reason_js};

            // Inject the "disabled look" CSS into the PARENT document once.
            if (!doc.getElementById(STYLE_ID)){{
                var st = doc.createElement('style');
                st.id = STYLE_ID;
                st.textContent = CSS;
                doc.head.appendChild(st);
            }}

            function isValid(v){{
                var t = (v || '').trim();
                if (t.length === 0) return false;
                if (REQUIRE_CHANGE && t === BASELINE) return false;
                return true;
            }}

            // Re-query the button on every call so a stale closure can never
            // point at a button node Streamlit replaced on the last rerun.
            function syncBtn(input){{
                var btn = doc.querySelector(BTN_SEL);
                if (!btn || !input) return;
                var wrap = doc.querySelector(WRAP_SEL);
                if (isValid(input.value)){{
                    btn.setAttribute('data-cd-valid', '1');
                    // Drop the tooltip the moment it stops being true.
                    if (wrap) wrap.removeAttribute('title');
                }} else {{
                    btn.removeAttribute('data-cd-valid');
                    // On the WRAPPER: the button has pointer-events:none, so a
                    // title there would never be hovered.
                    if (wrap && REASON) wrap.setAttribute('title', REASON);
                }}
            }}

            var tries = 0;
            (function bind(){{
                var input = doc.querySelector(IN_SEL);
                var wrap  = doc.querySelector(WRAP_SEL);
                if (!input || !doc.querySelector(BTN_SEL)){{
                    if (tries++ < 100) setTimeout(bind, 50);  // wait out render order
                    return;
                }}

                syncBtn(input);  // match the freshly-rendered button to live value

                if (input.dataset.cdLiveBound !== '1'){{
                    input.dataset.cdLiveBound = '1';
                    var handler = function(){{ syncBtn(input); }};
                    input.addEventListener('input', handler);
                    input.addEventListener('keyup', handler);
                }}

                // Streamlit re-renders the button node on each rerun, dropping
                // our data-cd-valid attribute. Watch the wrapper and re-apply so
                // a freshly-rendered valid button is never momentarily greyed.
                if (wrap && wrap.dataset.cdObserved !== '1'){{
                    wrap.dataset.cdObserved = '1';
                    var obs = new MutationObserver(function(){{ syncBtn(input); }});
                    obs.observe(wrap, {{ childList: true, subtree: true }});
                }}
            }})();
        }})();
        </script>
        """,
        height=0,
    )


def inject_material_icons_font() -> None:
    """No-op - Material Symbols font replaced by inline SVGs (issue 2 fix)."""
    pass


# The three selectors that identify a sticky action bar's layout wrapper. Kept
# byte-identical to the "Sticky action bar" block in styles/global.css - if a
# page opts in there, it opts in here too.
_STICKY_BAR_SELECTOR = (
    'div[data-testid="stLayoutWrapper"]:has(> div[class*="st-key-sticky_actions_"]),'
    'div[data-testid="stLayoutWrapper"]:has(> div[data-testid="stHorizontalBlock"] div[class*="st-key-action_dl_back"]),'
    'div[data-testid="stLayoutWrapper"]:has(> div[data-testid="stHorizontalBlock"] div[class*="st-key-btn_sync_selected"]),'
    'div[data-testid="stLayoutWrapper"]:has(> div[data-testid="stHorizontalBlock"] div[class*="st-key-btn_analyze_sync"])'
)


def inject_app_shell_bridge() -> None:
    """Two page-shell behaviours that CSS and Python alone cannot express.

    **1. Sticky-bar state.** Marks a pinned action bar with ``data-cd-stuck="1"``
    so global.css can show its lift-off shadow ONLY while it is actually
    floating. At rest the bar is simply the last row of the page, and a
    permanent upward shadow there read as detached. An IntersectionObserver
    against the scroll container with ``threshold: 1`` and a ``-1px`` bottom
    root margin is exact and costs nothing: while pinned the bar's bottom edge
    is flush with the scrollport bottom, so shrinking the root by one pixel
    clips it and the ratio drops below 1; once released it is fully inside
    again. No scroll listener, no polling, no layout reads.
    (CSS ``@container scroll-state(stuck: bottom)`` does this natively but is
    Chromium-only, and the macOS build renders in WKWebView.)

    **2. Scroll preservation across a dialog.** While a modal is open the page
    behind it CANNOT be scrolled by the user (Streamlit locks ``body``), so any
    change to the scroll position during that window is spurious by definition -
    which makes restoring it unconditionally safe. The position is captured when
    a dialog appears and re-applied for a short window after it disappears,
    guarded three ways so it can never fight the user: it gives up if the URL's
    query string changed (the dialog navigated to another page/step), if the
    user scrolls or types, or after 1.2s.

    Follows the ``components.html`` rule in CLAUDE.md: a fresh iframe is built
    on every rerun and the previous one destroyed, so every observer and
    listener is REBOUND here on each injection (a callback whose realm has been
    torn down silently stops firing), with the previous ones disconnected first
    so they cannot pile up. Mutable state lives on ``window.parent``.
    """
    import json
    import streamlit.components.v1 as components

    components.html(
        f"""<script>
(function(){{
    var win = window.parent, doc = win.document;
    var BAR_SEL = {json.dumps(_STICKY_BAR_SELECTOR)};
    var reg = win._cdShell || (win._cdShell = {{
        barObs: null, domObs: null, listeners: [], pending: null, timer: null,
        saved: null, wasOpen: false
    }});

    function scroller() {{ return doc.querySelector('section[data-testid="stMain"]'); }}
    function dialogOpen() {{ return !!doc.querySelector('div[data-testid="stDialog"]'); }}

    // Drop listeners bound from a previous (now dead) iframe realm.
    (reg.listeners || []).forEach(function(l) {{
        try {{ doc.removeEventListener(l[0], l[1], true); }} catch (_e) {{}}
    }});
    reg.listeners = [];
    function bind(type, fn) {{ doc.addEventListener(type, fn, true); reg.listeners.push([type, fn]); }}

    // ── 1. Sticky bar: pinned or at rest ──────────────────────────────────
    // The flag goes on <body>, NOT on the bar. Streamlit REPLACES the bar's
    // wrapper element on every rerun, so an attribute living there is gone
    // until the observer fires again - measured 2026-07-26 at ~50ms, during
    // which the pinned bar dropped its separator and put it straight back.
    // <body> is never replaced, so the flag survives the rerun and the bar
    // paints correctly on its very first frame. One page hosts at most one
    // action bar, so a single flag is exact.
    function watchBars() {{
        var root = scroller();
        if (!root) return;
        try {{ if (reg.barObs) reg.barObs.disconnect(); }} catch (_e) {{}}
        reg.barObs = new win.IntersectionObserver(function(entries) {{
            entries.forEach(function(e) {{
                // Pinned == the bar's bottom edge is flush with the scrollport
                // bottom, so the -1px root margin clips it out of full view.
                doc.body.setAttribute('data-cd-stuck', e.intersectionRatio < 1 ? '1' : '0');
            }});
        }}, {{root: root, threshold: [1], rootMargin: '0px 0px -1px 0px'}});
        var bars = doc.querySelectorAll(BAR_SEL);
        // A page with no bar must not inherit the previous page's flag.
        if (!bars.length) {{ doc.body.removeAttribute('data-cd-stuck'); return; }}
        bars.forEach(function(el) {{ reg.barObs.observe(el); }});
    }}

    // ── 2. Keep the page's scroll position across a dialog ────────────────
    function cancelRestore() {{
        if (reg.timer) {{ win.clearInterval(reg.timer); reg.timer = null; }}
        reg.pending = null;
    }}

    function beginRestore(saved) {{
        cancelRestore();
        if (!saved || !saved.top) return;
        reg.pending = saved;
        var until = win.Date.now() + 1200;
        reg.timer = win.setInterval(function() {{
            var p = reg.pending, el = scroller();
            // Give up the moment any assumption stops holding: time is up, the
            // page navigated (query string changed), or the element is gone.
            if (!p || !el || win.Date.now() > until || win.location.search !== p.search) {{
                cancelRestore();
                return;
            }}
            var max = el.scrollHeight - el.clientHeight;
            if (max < p.top - 4) return;          // page not tall enough (yet)
            if (Math.abs(el.scrollTop - p.top) > 1) el.scrollTop = p.top;
        }}, 60);
    }}

    function onDialogChange() {{
        var open = dialogOpen();
        if (open === reg.wasOpen) return;
        reg.wasOpen = open;
        var el = scroller();
        if (!el) return;
        if (open) {{
            cancelRestore();
            reg.saved = {{top: el.scrollTop, search: win.location.search}};
        }} else {{
            beginRestore(reg.saved);
            reg.saved = null;
        }}
    }}

    // One DOM observer drives both: dialogs mount/unmount and Streamlit
    // replaces the bar's wrapper on every rerun, so both need re-checking on
    // the same signal.
    try {{ if (reg.domObs) reg.domObs.disconnect(); }} catch (_e) {{}}
    reg.domObs = new win.MutationObserver(function() {{ onDialogChange(); watchBars(); }});
    reg.domObs.observe(doc.body, {{childList: true, subtree: true}});

    // Any deliberate user input outranks a queued restore.
    ['wheel', 'touchstart', 'keydown'].forEach(function(t) {{
        bind(t, function() {{ if (reg.pending) cancelRestore(); }});
    }});

    reg.wasOpen = dialogOpen();
    watchBars();
}})();
</script>""",
        height=0,
    )

def _mat(icon_name: str, color: str = '#bac2cc', size: int = 18) -> str:
    """Return an inline SVG icon. Replaces the Google Material Symbols font approach."""
    inner = _MAT_SVG_INNER.get(icon_name, _MAT_SVG_INNER['help'])
    adj = size + 4
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round" '
        f'width="{adj}" height="{adj}" style="{_ICON_STYLE}">'
        f'{inner}</svg>'
    )

def _img(filename, size=18):
    from shared.helpers import get_base64_image
    b64 = get_base64_image(f"assets/{filename}")
    mime = "image/svg+xml" if filename.lower().endswith('.svg') else "image/png"
    return f'<img src="data:{mime};base64,{b64}" width="{size}" height="{size}" style="{_ICON_STYLE} top: -2px;" />'

def _build_help_icons() -> dict:
    return {
        'lightbulb': _mat('lightbulb'),
        'folder': _mat('folder'),
        'gear': _img('icon_custom_download.png'),
        'bolt': _img('icon_sync_quick.png'),
        'bolt_small': _img('icon_sync_quick.png', size=11),
        'search': _img('icon_sync_review.png'),
        'search_small': _img('icon_sync_review.png', size=11),
        'save': _img('icon_preset_user.png'),
        'quick_download': _img('icon_quick_download.png'),
        'shield': _mat('shield'),
        'download': _img('icon_download.png'),
        'database': _mat('database'),
        'wrench': _mat('build'),
        'question': _mat('help'),
        'star': _mat('star'),
        'warning': '⚠️',
        'package': _mat('inventory_2'),
        'video': _mat('smart_display'),   # Panopto lecture recordings
        'check_circle': _mat('check_circle'),
        'cursor': _mat('arrow_selector_tool'),
        'eye': _mat('visibility'),
        'refresh': _img('icon_sync.png'),
        'compare': _img('icon_sync_pair.png'),
        'archive': _mat('archive'),
        'menu': _mat('menu'),
        'folder_open': _img('icon_preset_builtin.png'),
        'restore': _img('icon_restore.png', size=16),
        'calendar': _mat('calendar_today', color='#bac2cc'),
        'error': _mat('error', color='#ff7b72', size=12),
        'sync_hub': _img('icon_sync_hub.png'),
        'sync_pair': _img('icon_sync_pair.png'),
        'sync_group': _img('icon_sync_group.png'),
        # Sync Review Category Assets
        'cat_new': _img('Icon_Sync_Review_New_File.png', size=16),
        'cat_update': _img('Icon_Sync_Review_Update.png', size=16),
        'cat_miss': _img('Icon_Sync_Review_Missing_File.png', size=16),
        'cat_locdel': _img('Icon_Sync_Review_Locally_Deleted.png', size=16),
        'cat_candel': _img('Icon_Sync_Review_Deleted_On_Canvas.png', size=16),
        'cat_ignore': _img('Icon_Ignore.svg', size=16),
        'cat_uptodate': _mat('check_circle', color='#10B981', size=16),
    }

# Lazy singleton - computed on first access so missing assets at import time
# don't permanently bake broken icons into the cache (M-23).
_HELP_ICONS_CACHE: dict | None = None

class _LazyHelpIcons:
    """Dict-like proxy that builds HELP_ICONS on first access."""
    def __getitem__(self, key: str) -> str:
        global _HELP_ICONS_CACHE
        if _HELP_ICONS_CACHE is None:
            _HELP_ICONS_CACHE = _build_help_icons()
        return _HELP_ICONS_CACHE[key]

    def get(self, key: str, default=None):
        global _HELP_ICONS_CACHE
        if _HELP_ICONS_CACHE is None:
            _HELP_ICONS_CACHE = _build_help_icons()
        return _HELP_ICONS_CACHE.get(key, default)

    def __contains__(self, key: str) -> bool:
        global _HELP_ICONS_CACHE
        if _HELP_ICONS_CACHE is None:
            _HELP_ICONS_CACHE = _build_help_icons()
        return key in _HELP_ICONS_CACHE

HELP_ICONS = _LazyHelpIcons()


def render_completion_card(synced_count: int, error_count: int,
                           total_bytes: int, mode: str = 'download',
                           size_skipped_files: list = None, size_limit_mb: int = 0,
                           retry_attempted: bool = False, retry_resolved: int = 0,
                           retriable_count: int = 0,
                           unresolvable_count: int = 0,
                           app_error_count: int = 0,
                           courses_count: int = 0,
                           panopto_summary: dict = None):
    """Render the unified completion summary card.

    Single card that absorbs all status info: success/partial/failure,
    retry results, discovery warnings, and size-skipped annotations.
    """
    from styles import inject_css
    inject_css('completion.css')

    size_skipped_files = size_skipped_files or []
    size_skipped_count = len(size_skipped_files)

    # Only things that actually WENT WRONG decide the headline.
    #
    # A teacher-locked file, an LTI/media stream and a file the user's own size
    # cap excluded are all outcomes, not failures: nothing was lost, no retry
    # could change them, and two of the three are the app doing exactly what it
    # was told. Counting them made a course with two permanently-locked files
    # render amber "Partial Success" on every run for ever - which teaches the
    # user to ignore the one colour that is supposed to mean "look at this".
    # They are still REPORTED, in their own stat cards below; they just do not
    # colour the card. (Size skips never reached `error_count` in the first
    # place - they travel on their own progress channel - so this only had to
    # change for the other two.)
    #
    # Falls back to `error_count` when a caller supplies no split at all, so an
    # unmigrated call site still reports its errors rather than going silently
    # green.
    _has_split = (retriable_count or unresolvable_count or app_error_count)
    blocking_count = (retriable_count + app_error_count) if _has_split else error_count

    # Determine card variant
    if synced_count == 0 and blocking_count > 0:
        card_class = 'failure'
        title = 'Download Failed' if mode == 'download' else 'Sync Failed'
    elif blocking_count > 0:
        card_class = 'partial'
        title = 'Partial Success' if mode == 'download' else 'Sync Completed with Errors'
    elif synced_count > 0:
        card_class = 'success'
        title = 'Download Success' if mode == 'download' else 'Sync Success'
    elif unresolvable_count > 0:
        # Nothing went wrong and nothing arrived: every candidate was something
        # Canvas will not serve. Without this branch the run fell through to
        # "All Up to Date - nothing to download", which is the one reading that
        # is definitely false when N files were just declined.
        card_class = 'partial'
        title = ('Nothing Could Be Downloaded' if mode == 'download'
                 else 'Nothing Could Be Synced')
    else:
        # Same skin and the SAME even 24px inset as the other three variants
        # below - this block is a separate copy for the nothing-to-do card, and
        # it kept the old lopsided 35px bottom after the others were fixed.
        st.html("""
        <style>
        div[class*="st-key-completion_dashboard"] {
            background-color: rgba(22, 101, 52, 0.25) !important;
            border: 1px solid rgba(74, 222, 128, 0.5) !important;
            border-radius: 10px !important;
            padding: 24px !important;
            margin-bottom: 12px;
        }
        </style>
        """)
        # Title states the OUTCOME once; the line under it carries the evidence.
        # Both used to say the same thing twice ("Sync done! All files up to
        # date" over "Nothing to sync - all files are up to date!"), which read
        # as filler and, worse, gave no sign the app had actually compared
        # anything. The counts come from the analysis pass (see
        # sync/analysis.py, `sync_uptodate_stats`) and fall back to the old
        # generic line whenever they are unavailable.
        if mode == 'sync':
            _is_qs = st.session_state.get('sync_quick_mode', False)
            _card_title = 'Quick Sync done - everything up to date' if _is_qs \
                else 'Sync done - everything up to date'
            _stats = st.session_state.get('sync_uptodate_stats') or {}
            _f = int(_stats.get('files') or 0)
            _c = int(_stats.get('courses') or 0)
            _r = int(_stats.get('recordings') or 0)
            # Everything here agrees on the SAME count: one course means one
            # folder, so "your folders already match Canvas" was wrong copy on
            # the most common case of all (a single-course sync).
            _folder_word = "folder" if _c == 1 else "folders"
            if _f and _c:
                _bits = [f"{_f:,} file{'s' if _f != 1 else ''}"]
                if _r:
                    _bits.append(f"{_r:,} recording{'s' if _r != 1 else ''}")
                _scope = (f"across {_c} courses" if _c != 1
                          else "in this course")
                _sub = (f"Checked {' and '.join(_bits)} {_scope} - your "
                        f"{_folder_word} already {'match' if _c != 1 else 'matches'} Canvas.")
            else:
                _sub = (f"Your {_folder_word} already "
                        f"{'match' if _c != 1 else 'matches'} Canvas - nothing to download.")
        else:
            _card_title = 'All Up to Date'
            _sub = "Nothing to download - all files are up to date!"

        st.markdown(
            "<div class='completion-card success'>"
            f"<div class='card-title'>{_card_title}</div>"
            f"<p style='color:#86efac;font-size:1rem;margin:8px 0 0;'>{_sub}"
            "</p></div>",
            unsafe_allow_html=True,
        )
        if mode == 'download':
            st.markdown(
                "<div style='"
                "display:flex;align-items:flex-start;gap:10px;"
                "background:rgba(245,158,11,0.1);"
                "border:1px solid rgba(245,158,11,0.3);"
                "border-radius:8px;padding:12px 14px;"
                # No margin-top: it is a flex sibling of the card above,
                # so 14px here landed on top of the container's 16px gap
                # and opened 30px above the notice against the card's
                # 24px inset below it.
                "'>"
                "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
                "stroke='#f59e0b' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' "
                "style='width:18px;height:18px;flex-shrink:0;margin-top:2px;'>"
                "<path d='M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'></path>"
                "<line x1='12' y1='9' x2='12' y2='13'></line>"
                "<line x1='12' y1='17' x2='12.01' y2='17'></line>"
                "</svg>"
                "<div>"
                "<div style='color:#fbbf24;font-weight:600;font-size:0.88em;margin-bottom:3px;'>"
                "No files were found - possible connection issue"
                "</div>"
                "<p style='color:#d1d5db;font-size:0.82em;margin:0;line-height:1.5;'>"
                "Your Canvas account connected successfully, but no files or modules were returned. "
                "This can happen when your Canvas Access Token is geo-restricted (accessing from a different country than usual), "
                "when a firewall or VPN is affecting the connection to your university's server, "
                "or during a temporary Canvas outage. "
                "Try again on your usual network."
                "</p>"
                "</div>"
                "</div>",
                unsafe_allow_html=True,
            )
        # Reachable: Canvas files can all be up to date while the Panopto pass
        # still downloaded recordings, and that run has done real work this
        # card does not mention. render_panopto_summary self-guards on "did
        # this run actually do anything", so a run with no Panopto at all
        # still renders nothing.
        render_panopto_summary(panopto_summary)
        return

    # Stats grid
    file_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='width:18px;height:18px;flex-shrink:0;'><path d='M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z'></path><polyline points='13 2 13 9 20 9'></polyline></svg>"
    error_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='width:18px;height:18px;flex-shrink:0;'><circle cx='12' cy='12' r='10'></circle><line x1='12' y1='8' x2='12' y2='12'></line><line x1='12' y1='16' x2='12.01' y2='16'></line></svg>"
    size_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='width:18px;height:18px;flex-shrink:0;'><ellipse cx='12' cy='5' rx='9' ry='3'></ellipse><path d='M21 12c0 1.66-4 3-9 3s-9-1.34-9-3'></path><path d='M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5'></path></svg>"
    # Slash-circle icon for unresolvable files
    slash_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='width:18px;height:18px;flex-shrink:0;'><circle cx='12' cy='12' r='10'></circle><line x1='4.93' y1='4.93' x2='19.07' y2='19.07'></line></svg>"
    
    size_parts = format_file_size(total_bytes).split(" ", 1)
    size_val = size_parts[0]
    size_unit = size_parts[1] if len(size_parts) > 1 else "Bytes"
    if total_bytes == 0:
        size_unit = "MB"

    stats_html = (
'<div class="completion-stats-grid">'
    )
    if courses_count > 0:
        course_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='width:18px;height:18px;flex-shrink:0;'><path d='M4 19.5A2.5 2.5 0 0 1 6.5 17H20'></path><path d='M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z'></path></svg>"
        stats_html += (
'<div class="stat-card">'
f'<div class="stat-icon-wrapper">{course_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{courses_count}</div>'
f'<div class="stat-label">{"Course" if courses_count == 1 else "Courses"} {"Updated" if mode == "sync" else "Downloaded"}</div>'
'</div>'
'</div>'
        )
    stats_html += (
'<div class="stat-card">'
f'<div class="stat-icon-wrapper">{file_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{synced_count}</div>'
f'<div class="stat-label">{"File" if synced_count == 1 else "Files"} Downloaded</div>'
'</div>'
'</div>'
'<div class="stat-card">'
f'<div class="stat-icon-wrapper">{size_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{size_val}</div>'
f'<div class="stat-label">{size_unit} Downloaded</div>'
'</div>'
'</div>'
    )

    # Conditional error stat cards - split by retriable vs unresolvable vs app-level
    _warning_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='width:18px;height:18px;flex-shrink:0;'><path d='M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'></path><line x1='12' y1='9' x2='12' y2='13'></line><line x1='12' y1='17' x2='12.01' y2='17'></line></svg>"
    _split_cards = (retriable_count > 0 or unresolvable_count > 0 or app_error_count > 0)
    if _split_cards:
        # Show separate cards when split counts are provided
        if retriable_count > 0:
            stats_html += (
'<div class="stat-card stat-error">'
f'<div class="stat-icon-wrapper">{error_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{retriable_count}</div>'
f'<div class="stat-label">Failed {"Download" if retriable_count == 1 else "Downloads"}</div>'
'</div>'
'</div>'
            )

    # Recovered sits immediately RIGHT of Failed Downloads, so the pair reads as
    # one sentence: "2 failed, 3 recovered". It used to be a green line of prose
    # under the grid ("Recovered 3 of 5 failed items"), which restated a number
    # the grid was already showing and put the run's best news in the one place
    # on the card that is not a metric.
    #
    # Deliberately OUTSIDE the split-cards branch: a retry that fixed everything
    # leaves all three error counts at zero, and that is exactly the run that
    # most deserves to say so.
    if retry_attempted and retry_resolved > 0:
        _recovered_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='width:18px;height:18px;flex-shrink:0;'><path d='M3 12a9 9 0 1 0 3-6.7'></path><polyline points='3 3 3 9 9 9'></polyline></svg>"
        stats_html += (
'<div class="stat-card stat-recovered">'
f'<div class="stat-icon-wrapper">{_recovered_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{retry_resolved}</div>'
f'<div class="stat-label">{"File" if retry_resolved == 1 else "Files"} Recovered</div>'
'</div>'
'</div>'
        )

    if _split_cards:
        if unresolvable_count > 0:
            stats_html += (
'<div class="stat-card stat-skip">'
f'<div class="stat-icon-wrapper">{slash_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{unresolvable_count}</div>'
f'<div class="stat-label">Cannot Be Downloaded</div>'
'</div>'
'</div>'
            )
        if app_error_count > 0:
            stats_html += (
'<div class="stat-card stat-app-error">'
f'<div class="stat-icon-wrapper">{_warning_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{app_error_count}</div>'
f'<div class="stat-label">{"App Error" if app_error_count == 1 else "App Errors"}</div>'
'</div>'
'</div>'
            )
    elif error_count > 0:
        # Fallback: single combined error card (backward compat)
        stats_html += (
'<div class="stat-card stat-error">'
f'<div class="stat-icon-wrapper">{error_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{error_count}</div>'
f'<div class="stat-label">{"Error" if error_count == 1 else "Errors"}</div>'
'</div>'
'</div>'
        )
        
    stats_html += '</div>'

    # NO PROSE UNDER THE GRID.
    #
    # Two full-width rows of text used to live here - "Recovered 3 of 5 failed
    # items" and "2 files are locked by your teacher on Canvas; ...". Both said
    # something the card was already showing as a number, and both landed
    # between the stat grid and the expander below, so the card's one block of
    # metrics was split by paragraphs. The declined sentence was the worse of
    # the two: it duplicated, almost word for word, what the expander directly
    # beneath it says when opened.
    #
    # Where each went instead:
    #   * recovery  -> its own stat card, next to Failed Downloads (above);
    #   * declined  -> the expander's own subtitle, which is where a user goes
    #                  to find out WHICH files, via `declined_reason_sentence`
    #                  so the wording cannot drift between the two screens.
    notes_html = ''

    if card_class == 'failure':
        bg_color = 'rgba(127, 29, 29, 0.30)'
        border_color = 'rgba(239, 68, 68, 0.45)'
    elif card_class == 'partial':
        bg_color = 'rgba(120, 80, 0, 0.22)'
        border_color = 'rgba(245, 158, 11, 0.45)'
    else:
        bg_color = 'rgba(22, 101, 52, 0.25)'
        border_color = 'rgba(74, 222, 128, 0.5)'

    st.html(f"""
    <style>
    div[class*="st-key-completion_dashboard"] {{
        background-color: {bg_color} !important;
        border: 1px solid {border_color} !important;
        border-radius: 10px !important;
        /* Even inset on all four sides. The bottom used to be 35px against 20px
           elsewhere, which read as a gap under the last row rather than as the
           card breathing - most obvious on the partial-success card, where the
           Error Details expander sat visibly further from its border than the
           title did from the top. 24px reads as deliberate at this card size. */
        padding: 24px !important;
        margin-bottom: 12px;
    }}
    div[class*="st-key-completion_dashboard"] [data-testid="stExpanderDetails"] {{
        background-color: var(--secondary-background-color, #161b22) !important;
    }}
    </style>
    """)

    st.markdown(f"""
    <div class="completion-card {card_class}">
        <div class="card-title">{esc(title)}</div>
        {stats_html}
        {notes_html}
    </div>
    """, unsafe_allow_html=True)

    # THINGS OF THE SAME KIND SIT TOGETHER.
    #
    # The Panopto card is a stat grid, so it belongs directly under the run's
    # other stat grid - not four elements below it, with a warning notice and
    # two expanders in between, which is where it used to land because the call
    # sites rendered it in the order the features were built. Rendering it here
    # is also what makes the rest of the order possible: everything after this
    # point is a collapsible, and everything the CALLERS add after that is a
    # notice. See app.py / sync/completion.py for the other half of the rule.
    render_panopto_summary(panopto_summary)

    if size_skipped_count > 0:
        import os as _os, re as _re
        _SKIP_CHEVRON = _SKIP_CHEVRON_SVG
        _FUNNEL_SVG = _SKIP_FUNNEL_SVG
        _skip_word = 'file' if size_skipped_count == 1 else 'files'
        _rows_html = ''
        for _sf in size_skipped_files:
            _m = _re.match(r'^(.+?) \(([^)]+)\)$', _sf)
            if _m:
                _fname_full = _m.group(1)
                _size_str = _m.group(2)
            else:
                _fname_full = _sf
                _size_str = ''
            _ext = _os.path.splitext(_fname_full)[1].lower().lstrip('.')
            _fname_noext = _os.path.splitext(_fname_full)[0] if _ext else _fname_full
            _icon_url = _FILETYPE_SVGS.get(_ext, _FILETYPE_SVG_DEFAULT)
            _ext_badge = (
                f'<span class="skip-ext-badge">{esc(_ext.upper())}</span>'
            ) if _ext else ''
            _size_badge = (
                f'<span class="skip-file-size">{esc(_size_str)}</span>'
            ) if _size_str else ''
            _rows_html += (
                f'<div class="skip-file-row">'
                f'<img class="skip-file-icon" src="{_icon_url}" alt="{esc(_ext)}"/>'
                f'<span class="skip-file-name">{esc(_fname_noext)}</span>'
                f'{_ext_badge}'
                f'{_size_badge}'
                f'</div>'
            )
        
        # ONE row, not two. The statement of fact and the control that reveals
        # the detail used to be separate elements stacked on top of each other,
        # so the notice was twice as tall as it needed to be and the second row
        # ("See 20 skipped files") only restated the first. The summary IS the
        # sentence now, with the chevron leading it.
        st.markdown(
            f'<details class="skip-panel skip-panel-solo">'
            f'<summary class="skip-panel-header">'
            f'<div class="sp-header-row">'
            f'<img class="sp-chevron" src="{_SKIP_CHEVRON}" alt="toggle"/>'
            f'<img class="sp-funnel" src="{_FUNNEL_SVG}" alt=""/>'
            f'<span class="sp-title"><b>{size_skipped_count}</b> {_skip_word} skipped because they exceeded the <b>{size_limit_mb} MB limit</b>.</span>'
            f'</div>'
            f'</summary>'
            f'<div class="skip-panel-body">'
            f'<div class="sp-subtitle">These files are marked as ignored and won\'t appear as new during sync. You can manage them in the <b>Sync Mode front page</b>, with the <b>Ignored Files</b> button.</div>'
            f'<div class="skip-file-list">{_rows_html}</div>'
            f'</div>'
            f'</details>',
            unsafe_allow_html=True,
        )



_FC_FOLDER_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20'"
    " viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2'"
    " stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Cpath d='M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z'/%3E"
    "%3C/svg%3E"
)
_FC_CHEVRON_SVG = (
    "<svg class='ft-chevron' xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'"
    " width='16' height='16'"
    " fill='none' stroke='currentColor' stroke-width='2.5'"
    " stroke-linecap='round' stroke-linejoin='round'>"
    "<path d='M9 18l6-6-6-6'/>"
    "</svg>"
)


def render_folder_cards(file_details: dict, folder_paths: dict,
                        key_prefix: str = 'dl', show_files_expander: bool = False,
                        file_records: dict | None = None):
    """Render per-folder cards with filetype summary and Open Folder buttons.

    When ``file_records`` is provided (keyed identically to ``file_details``),
    the "Files added" list becomes interactive: each file gets Open / Reveal
    actions and a destination-subfolder chip. Each value is a list of
    ``{'name', 'rel', 'category'}`` records; the abs path is resolved as
    ``folder_path / rel``. Falls back to the static read-only list otherwise.
    """
    has_files = any(len(files) > 0 for files in file_details.values())
    if not has_files:
        return

    # This card's markup (folder header, filetype pills, per-file icons) is
    # styled entirely by completion.css. On the completion/sync screens it is
    # already injected by render_completion_card/render_download_stats, but the
    # Today page calls render_folder_cards standalone - so inject it here to make
    # the component self-sufficient. Without this, .ft-icon has no width/height
    # rule and every filetype icon renders at natural (full-width) size.
    from styles import inject_css
    inject_css('completion.css')

    if file_records:
        inject_file_action_css()

    # Folder glyph to the left of each "Open Folder" button's centred label
    # (light grey at rest, white on hover). Scoped to THIS call's key_prefix so
    # it targets only these folder buttons - never the per-file fileact_open_
    # icon buttons. The icon is a ::before on the label <p> (Streamlit button
    # labels are plain text), with the <p> flexed so icon + text stay centred.
    _ofp = key_prefix.lower()
    st.markdown(f"""<style>
    div[class*="st-key-{_ofp}_open_"] button {{
        align-items: center !important;
        justify-content: center !important;
    }}
    /* Flex the markdown container (the button's actual flex child) so the label
       block centres vertically; then flex the <p> so the icon + text sit on one
       centred line. margin:0 removes the label's default bottom margin that would
       otherwise bias the content upward. (No line-height override - that clips
       the glyphs.) */
    div[class*="st-key-{_ofp}_open_"] button [data-testid="stMarkdownContainer"] {{
        display: flex !important;
        align-items: center !important;
    }}
    div[class*="st-key-{_ofp}_open_"] button p {{
        display: inline-flex !important;
        align-items: center !important;
        gap: 8px !important;
        margin: 0 !important;
    }}
    div[class*="st-key-{_ofp}_open_"] button p::before {{
        content: "";
        display: inline-block;
        width: 15px; height: 15px;
        flex-shrink: 0;
        background-repeat: no-repeat;
        background-position: center;
        background-size: contain;
        background-image: url("{_FOLDER_ICON_GREY}");
    }}
    div[class*="st-key-{_ofp}_open_"] button:hover p::before {{
        background-image: url("{_FOLDER_ICON_WHITE}");
    }}
    </style>""", unsafe_allow_html=True)

    st.markdown('<div class="completion-section-header">Folders Updated</div>', unsafe_allow_html=True)

    for idx, (folder_key, files) in enumerate(file_details.items()):
        if not files:
            continue

        folder_path = folder_paths.get(folder_key, '')
        folder_name = short_path(folder_path) if folder_path else folder_key
        file_count = len(files)
        count_label = f"{file_count} file" if file_count == 1 else f"{file_count} files"
        expand_id = f"ft-expand-{key_prefix}-{idx}"
        pills_html = _build_filetype_pills_html(files)

        header_html = (
            f'<div class="fc-wrapper">'
            f'<input type="checkbox" id="{expand_id}" class="ft-expand-toggle"/>'
            f'<div class="fc-header">'
            f'<div class="fc-folder-icon" style="font-size:1.4rem; line-height:1; display:flex; align-items:center; justify-content:center; opacity:1; color:#facc15; width:1.4rem; height:1.4rem;"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" style="width:100%; height:100%;"><path d="M20 5h-7.586l-2-2H4c-1.103 0-2 .897-2 2v14c0 1.103.897 2 2 2h16c1.103 0 2-.897 2-2V7c0-1.103-.897-2-2-2z"/></svg></div>'
            f'<div class="fc-title">{esc(folder_name)}</div>'
            f'<label for="{expand_id}" class="ft-expander-trigger">'
            f'{_FC_CHEVRON_SVG}'
            f'<span class="ft-label">{count_label}</span>'
            f'</label>'
            f'</div>'
            f'<div class="ft-expander-pills">{pills_html}</div>'
            f'</div>'
        )

        records = (file_records or {}).get(folder_key) or []

        with st.container(border=True, key=f"{key_prefix}_fc_{idx}"):
            st.markdown(header_html, unsafe_allow_html=True)
            if records:
                # Interactive list: per-file Open / Reveal + subfolder chip,
                # grouped by category exactly like the sync-history panel.
                # Open by default for small batches (the common Quick Sync case
                # where the student wants the files immediately); keep big syncs
                # collapsed so the completion screen stays tidy.
                with st.expander("Files added", expanded=len(records) <= 12):
                    render_course_file_breakdown(
                        records, folder_path, key_scope=f"{key_prefix}_{idx}",
                    )
            elif show_files_expander and files:
                with st.expander("Files added"):
                    import os as _os
                    rows = []
                    for fname in sorted(files):
                        _ext = _os.path.splitext(fname)[1].lower().lstrip('.')
                        _name = _os.path.splitext(fname)[0]
                        _icon = _FILETYPE_SVGS.get(_ext, _FILETYPE_SVG_DEFAULT)
                        _badge = (
                            f"<span style='font-size:0.65rem;font-weight:700;letter-spacing:0.4px;"
                            f"color:#bababa;background:rgba(255,255,255,0.08);border-radius:3px;"
                            f"padding:1px 5px;margin-left:6px;white-space:nowrap;flex-shrink:0;'>{esc(_ext.upper())}</span>"
                        ) if _ext else ""
                        rows.append(
                            f"<div style='display:flex;align-items:center;gap:3px;padding:3px 0;flex-wrap:wrap;'>"
                            f'<img src="{_icon}" style="width:16px;height:16px;flex-shrink:0;" alt="{esc(_ext)}"/>'
                            f"<span style='font-size:0.85rem;color:#ffffff;word-break:break-word;'>{esc(_name)}</span>"
                            f"{_badge}"
                            f"</div>"
                        )
                    st.markdown(
                        "<div style='display:flex;flex-direction:column;gap:1px;'>" + "".join(rows) + "</div>",
                        unsafe_allow_html=True,
                    )
            if folder_path and Path(folder_path).exists():
                _open_folder_button(folder_path, f"{key_prefix}_open_{idx}")


@st.fragment
def _open_folder_button(folder_path: str, key: str):
    """Render an "Open Folder" button isolated in a fragment.

    Clicking a plain ``st.button`` triggers a FULL-script rerun, so the entire
    completion screen (stat cards, error details, every folder card) re-renders
    *before* the click handler reaches ``open_folder`` - a visible 1-2s lag
    before the folder actually opens. Wrapping the button in ``@st.fragment``
    scopes the click's rerun to just this button, so the folder opens instantly.
    """
    if st.button('Open Folder', key=key, use_container_width=False):
        open_folder(folder_path)


# ===================================================================
# Per-file Open / Reveal action rows (shared by the sync completion
# screen and the landing-page "New files since last sync" panel).
# ===================================================================

# URL-encoded inline SVGs (Lucide-style). Single quotes inside the SVG keep the
# outer CSS string intact; '#' is encoded as %23 per the SVG-data-URI rules.
_ACTION_ICON_OPEN = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
    "fill='none' stroke='%23b1bac4' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Cpath d='M15 3h6v6'/%3E%3Cpath d='M10 14 21 3'/%3E"
    "%3Cpath d='M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6'/%3E%3C/svg%3E"
)
_ACTION_ICON_REVEAL = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
    "fill='none' stroke='%23b1bac4' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Cpath d='m6 14 1.45-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.55 6a2 2 0 0 1-1.94 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.93a2 2 0 0 1 1.66.9l.82 1.2a2 2 0 0 0 1.66.9H18a2 2 0 0 1 2 2v2'/%3E%3C/svg%3E"
)
# Filled folder glyph for the destination-path chip (SVG, not an emoji).
_FOLDER_ICON_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23e0a836'%3E"
    "%3Cpath d='M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z'/%3E%3C/svg%3E"
)
# Same folder glyph in two neutral tints for the "Open Folder" button icon:
# light grey at rest, white on hover. Swapped via background-image on :hover.
_FOLDER_ICON_GREY = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23b1bac4'%3E"
    "%3Cpath d='M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z'/%3E%3C/svg%3E"
)
_FOLDER_ICON_WHITE = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23ffffff'%3E"
    "%3Cpath d='M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z'/%3E%3C/svg%3E"
)


def inject_file_action_css():
    """Inject the scoped CSS for the per-file Open / Reveal icon buttons.

    The icon is drawn with a ``::before`` pseudo-element (not the button's own
    ``background-image``) so Streamlit's hover restyle - which resets the
    button background - can never wipe the glyph. Buttons are fixed 1:1 squares.
    Idempotent; call once per render before any action rows. Selectors match
    every key starting ``fileact_open_`` / ``fileact_reveal_``.
    """
    st.markdown(f"""<style>
    /* Category sections are separated by a thin divider (the .cat-section-sep
       element rendered at the top of every category AFTER the first - see
       render_course_file_breakdown) instead of each sitting inside its own
       coloured box. Strip the box entirely; keep the content indent + a little
       bottom breathing room. */
    div[class*="st-key-fileactlist_"] {{
        border: none !important;
        background: transparent !important;
        border-radius: 0 !important;
        padding: 0 16px 2px 34px !important;
        margin: 0 !important;
    }}
    /* Collapse the gap between sibling category containers so the divider's own
       5px-above / 5px-below margin is the ONLY spacing between categories. The
       direct-child :has(> ...) matches only the immediate parent block, never an
       ancestor. */
    [data-testid="stVerticalBlock"]:has(> div[class*="st-key-fileactlist_"]) {{
        gap: 0 !important;
    }}
    /* The category separator line. The line is a border-bottom; the space ABOVE
       it is padding-top (NOT margin-top) so it is immune to margin-collapse - a
       margin-top collapses to zero inside the sync-history container (the divider
       then sits flush against the row above it), whereas padding always renders.
       Space below is margin-bottom (safe: the next header has margin-top:0). The
       negative left margin lines the rule up with the category header text. */
    .cat-section-sep {{
        height: 0 !important;
        border-bottom: 1px solid rgba(255,255,255,0.10) !important;
        padding-top: 6px !important;
        margin: 0 0 12px -26px !important;
    }}
    /* Pack rows close, but with a little breathing room between them. */
    div[class*="st-key-fileactlist_"] [data-testid="stVerticalBlock"] {{ gap: 4px !important; }}

    /* --- BULLETPROOF ROW LAYOUT ---------------------------------------- *
     * Each file row is ONE horizontal block of 4 columns:
     *   [filename] [Open] [Reveal] [path-chip]
     * The trick: the column flex weights Streamlit emits are overridden so
     * (1) the NAME column shrinks to its content, (2) the two BUTTON columns
     * shrink to content, (3) the PATH column absorbs the rest. The buttons
     * therefore ALWAYS sit exactly one flex-gap (6px) after the end of the
     * filename - never a fraction of the row width. align-items:center keeps
     * the buttons vertically centred on the filename; margin:0 kills the 5px
     * Streamlit injects, which is what made rows feel loose/unaligned. */
    div[class*="st-key-fileactlist_"] [data-testid="stHorizontalBlock"] {{
        gap: 6px !important;
        align-items: center !important;
        flex-wrap: nowrap !important;
        margin: 0 !important;
        min-height: 0 !important;
    }}
    div[class*="st-key-fileactlist_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
        padding: 0 !important; min-width: 0 !important; width: auto !important;
    }}
    /* (1) filename - shrink to content, capped so long names ellipsis instead
       of shoving the buttons off-screen. */
    div[class*="st-key-fileactlist_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1) {{
        flex: 0 1 auto !important; max-width: 60% !important;
    }}
    /* (2,3) the two icon buttons - shrink to content, hug the filename. */
    div[class*="st-key-fileactlist_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2),
    div[class*="st-key-fileactlist_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) {{
        flex: 0 0 auto !important;
    }}
    /* (4) path chip - absorbs remaining width (left-aligned, right after btns). */
    div[class*="st-key-fileactlist_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(4) {{
        flex: 1 1 auto !important;
    }}

    /* Compact 22px square icon buttons, vertically centred on the filename.
       The button sits high (the stButton wrapper reserves Streamlit's default
       button height and top-pins the square); the `top` nudge drops it onto the
       SAME centre line as the path chip - the reference element. */
    div[class*="st-key-fileact_open_"] button,
    div[class*="st-key-fileact_reveal_"] button {{
        height: 22px !important; min-height: 22px !important;
        width: 22px !important; min-width: 22px !important; max-width: 22px !important;
        padding: 0 !important; margin: 0 !important;
        position: relative !important; top: 8px !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
        border-radius: 5px !important;
        background-color: rgba(255,255,255,0.04) !important;
        border: 1px solid rgba(255,255,255,0.10) !important;
        box-shadow: none !important;
        transition: background-color 0.15s ease, border-color 0.15s ease !important;
    }}
    div[class*="st-key-fileact_open_"] button p,
    div[class*="st-key-fileact_reveal_"] button p {{
        display: flex !important; align-items: center !important; justify-content: center !important;
        line-height: 0 !important; margin: 0 !important;
    }}
    /* Icon as a hover-proof pseudo-element on the label's <p> (Streamlit's
       hover restyle resets the button background but never the pseudo-element). */
    div[class*="st-key-fileact_open_"] button p::before,
    div[class*="st-key-fileact_reveal_"] button p::before {{
        content: "";
        display: inline-block;
        width: 13px;
        height: 13px;
        background-repeat: no-repeat;
        background-position: center;
        background-size: contain;
    }}
    div[class*="st-key-fileact_open_"] button p::before {{ background-image: url("{_ACTION_ICON_OPEN}"); }}
    div[class*="st-key-fileact_reveal_"] button p::before {{ background-image: url("{_ACTION_ICON_REVEAL}"); }}
    div[class*="st-key-fileact_open_"] button:hover:not(:disabled),
    div[class*="st-key-fileact_reveal_"] button:hover:not(:disabled) {{
        background-color: rgba(88,166,255,0.15) !important;
        border-color: rgba(88,166,255,0.55) !important;
    }}
    /* No disabled rule: global.css's `button[disabled]` recipe owns it. These
       carried `opacity: 0.3` on top of that filter, and 0.5 x 0.3 left a 22px
       icon button at 15% of its enabled paint - effectively invisible on the
       dark card. */
    </style>""", unsafe_allow_html=True)


def _sort_file_records(files: list, mode: str) -> list:
    """Return a sorted copy of file records. mode: 'folder' | 'name' | 'type'."""
    import os as _os
    if mode == 'name':
        return sorted(files, key=lambda f: f.get('name', '').lower())
    if mode == 'type':
        return sorted(files, key=lambda f: (
            _os.path.splitext(f.get('name', ''))[1].lower(), f.get('name', '').lower()))
    # 'folder' (default): group by subfolder, then by name within each
    return sorted(files, key=lambda f: (
        _os.path.dirname(f.get('rel', f.get('name', '')) or '').lower(),
        f.get('name', '').lower()))


def render_synced_file_rows(files: list, course_root: str, key_scope: str,
                            sort_mode: str = 'folder', show_subfolder: bool = True,
                            header_html: str | None = None):
    """Render a tight, interactive file list:

        [filetype icon] filename   [Open][Reveal]   📁 destination subfolder

    The two icon buttons sit right after the filename (≈5px apart) with the
    destination path immediately to their right. Rows are packed close together
    vertically. No per-file category badge - the caller labels sections by
    category. Rows are wrapped in a keyed ``fileactlist_`` container that the
    scoped CSS in :func:`inject_file_action_css` strips and tightens.

    Args:
        files: list of {'name', 'rel', 'category'} records.
        course_root: absolute course folder; abs path = course_root / rel.
        key_scope: globally-unique string; button keys append the row index.
        sort_mode: 'folder' | 'name' | 'type'.
        show_subfolder: show the destination-subfolder path.
        header_html: optional HTML rendered tight above the rows (e.g. a
            category heading) so it hugs the list instead of floating above it.

    Call ``inject_file_action_css()`` once before using this.
    """
    import os as _os

    # Defensive: only dict records survive. A non-dict (legacy/corrupt data)
    # would otherwise crash inside _sort_file_records' .get() sort key - and
    # this function is shared with the completion screen, which doesn't wrap it.
    files = [fi for fi in (files or []) if isinstance(fi, dict)]
    if not files:
        return

    with st.container(border=True, key=f"fileactlist_{key_scope}"):
        if header_html:
            st.markdown(header_html, unsafe_allow_html=True)

        for i, fi in enumerate(_sort_file_records(files, sort_mode)):
            name = fi.get('name', '')
            rel = fi.get('rel', name) or name
            abs_path = _os.path.normpath(_os.path.join(course_root, rel)) if course_root else ''
            exists = bool(abs_path) and _os.path.isfile(abs_path)

            ext = _os.path.splitext(name)[1].lower().lstrip('.')
            icon = _FILETYPE_SVGS.get(ext, _FILETYPE_SVG_DEFAULT)
            subdir = _os.path.dirname(rel).replace('\\', '/')

            # NB: data-URIs use single quotes internally, so the src attribute
            # MUST be double-quoted or the first inner quote closes it.
            name_html = (
                "<div style='display:flex;align-items:center;gap:8px;min-width:0;'>"
                f'<img src="{icon}" style="width:16px;height:16px;flex-shrink:0;" alt="{esc(ext)}"/>'
                f"<span style='font-size:0.86rem;color:#e6edf3;overflow:hidden;text-overflow:ellipsis;"
                f"white-space:nowrap;' title=\"{esc(name)}\">{esc(name)}</span>"
                "</div>"
            )
            folder_html = ''
            if show_subfolder:
                # Path rendered as a dark, rounded chip so it reads as a distinct
                # "destination" token. inline-flex → the chip hugs its text.
                # Files at the course root show "Course folder" so students know
                # where to find them without seeing a blank path column.
                chip_label = subdir if subdir else "Course folder"
                chip_color = "#9aa4af" if subdir else "#6b7280"
                folder_html = (
                    "<div style='display:flex;align-items:center;min-width:0;'>"
                    "<span style='display:inline-flex;align-items:center;gap:6px;max-width:100%;"
                    "background:#161b22;border:1px solid rgba(255,255,255,0.06);"
                    "border-radius:6px;box-sizing:border-box;height:22px;padding:0 9px;'>"
                    f'<img src="{_FOLDER_ICON_SVG}" style="width:13px;height:13px;flex-shrink:0;" alt="folder"/>'
                    f"<span style='font-size:0.75rem;color:{chip_color};white-space:nowrap;"
                    f"overflow:hidden;text-overflow:ellipsis;' title=\"{esc(chip_label)}\">{esc(chip_label)}</span></span></div>"
                )

            # Column weights are placeholders only - the scoped CSS in
            # inject_file_action_css() overrides the flex so the name + button
            # columns shrink to content and the buttons hug the filename. (The
            # old approach sized the name column by len(name) heuristics, which
            # left an inconsistent, always-wrong gap before the first button.)
            # vertical_alignment="center" is Streamlit's native row centering
            # (CSS align-items overrides don't take); the 5px it injects is
            # killed by the margin:0 rule in inject_file_action_css().
            cols = st.columns([3, 1, 1, 4], vertical_alignment="center")
            with cols[0]:
                st.markdown(name_html, unsafe_allow_html=True)
            _help_missing = "File not found at its last known location"
            with cols[1]:
                _fileact_button(
                    f"fileact_open_{key_scope}_{i}",
                    "Open file" if exists else _help_missing,
                    not exists, open_file, abs_path,
                )
            with cols[2]:
                _fileact_button(
                    f"fileact_reveal_{key_scope}_{i}",
                    "Show in folder" if exists else _help_missing,
                    not exists, reveal_in_folder, abs_path,
                )
            with cols[3]:
                if folder_html:
                    st.markdown(folder_html, unsafe_allow_html=True)


@st.fragment
def _fileact_button(key: str, help_text: str, disabled: bool, action, arg):
    """Render a per-file Open/Reveal icon button isolated in a fragment.

    Same rationale as ``_open_folder_button``: a plain ``st.button`` click forces
    a full-script rerun, re-rendering the whole completion/history screen before
    the file actually opens. The fragment scopes the click's rerun to this button
    so the file opens instantly. The zero-width-space label and the
    ``fileact_open_``/``fileact_reveal_`` key prefixes (and thus the
    ``inject_file_action_css`` styling) are preserved.
    """
    if st.button("​", key=key, help=help_text,
                 disabled=disabled, use_container_width=True):
        action(arg)


# Synced-file categories, in display order: (record-key, header, HELP_ICONS-key).
# Shared by the sync completion screen and the sync-history panel so both group
# and label files identically.
SYNC_FILE_CATEGORIES = [
    ('new',       'New Files Added',                'cat_new'),
    ('updated',   'Updates Overwritten',           'cat_update'),
    ('restored',  'Locally-Deleted Files Restored', 'cat_locdel'),
    ('protected', 'Modified Files Protected',       'cat_miss'),
]


def render_course_file_breakdown(files: list, course_root: str, key_scope: str):
    """Render ONE course's synced files grouped by category, each with a header.

    This is the single source of truth for the per-file breakdown shown on BOTH
    the sync completion screen and the sync-history panel - guaranteeing the rows
    (filetype icon + name + Open/Reveal + destination chip) and the category
    headers are pixel-identical in both places.

    ``files`` is a list of ``{'name', 'rel', 'category'}`` records; ``course_root``
    is the absolute course folder (abs path = ``course_root / rel``). Call
    :func:`inject_file_action_css` once before using this.
    """
    files = [fi for fi in (files or []) if isinstance(fi, dict)]
    if not files:
        return

    by_cat: dict[str, list] = {}
    for fi in files:
        by_cat.setdefault(fi.get('category', 'new'), []).append(fi)

    rendered_any = False
    for cat_key, cat_title, cat_icon in SYNC_FILE_CATEGORIES:
        cfiles = by_cat.get(cat_key)
        if not cfiles:
            continue
        # 'protected' is assigned purely by the "_NewVersion" filename (see
        # sync/execution.py), and TWO routes produce that name: the user edited
        # the file, or the file could not be written because it was open in
        # another program. The old wording - "the files you had edited" - told
        # the second group they had edited something they had not touched. The
        # phrasing below is true of both and keeps the protective framing.
        _desc = ('Your unedited local copies were replaced with the newer versions'
                 if cat_key == 'updated' else
                 'Re-downloaded because your local copy was missing'
                 if cat_key == 'restored' else
                 'Saved next to your copy, which was left untouched'
                 if cat_key == 'protected' else '')
        _mb = "2px" if _desc else "8px"
        _desc_html = (f"<div style='color:#8b949e;font-size:0.75rem;margin-bottom:8px;'>{_desc}</div>"
                      if _desc else "")
        # Divider between categories (not above the first one).
        _sep = "<div class='cat-section-sep'></div>" if rendered_any else ""
        _hdr = (_sep
                + f"<div style='margin-top:0;margin-left:-26px;color:#fff;font-size:0.85rem;font-weight:600;margin-bottom:{_mb};'>"
                f"{HELP_ICONS[cat_icon]} {cat_title} "
                f"<span style='color:#b1bac4;font-weight:500;'>({len(cfiles)})</span></div>"
                + _desc_html)
        render_synced_file_rows(
            cfiles, course_root,
            key_scope=f"{key_scope}_{cat_key}",
            sort_mode='folder', header_html=_hdr,
        )
        rendered_any = True


# --- Base64 SVG icons for filetype pills ---
_FILETYPE_SVGS = {
    'pdf': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23ef4444'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23fca5a5'/%3E%3Ctext x='7' y='17' font-size='6' font-weight='bold' fill='white'%3EPDF%3C/text%3E%3C/svg%3E",
    'pptx': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23f97316'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23fdba74'/%3E%3Ctext x='7' y='17' font-size='5' font-weight='bold' fill='white'%3EPPT%3C/text%3E%3C/svg%3E",
    'ppt': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23f97316'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23fdba74'/%3E%3Ctext x='7' y='17' font-size='5' font-weight='bold' fill='white'%3EPPT%3C/text%3E%3C/svg%3E",
    'docx': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%233b82f6'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%2393c5fd'/%3E%3Ctext x='5' y='17' font-size='5' font-weight='bold' fill='white'%3EDOC%3C/text%3E%3C/svg%3E",
    'doc': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%233b82f6'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%2393c5fd'/%3E%3Ctext x='5' y='17' font-size='5' font-weight='bold' fill='white'%3EDOC%3C/text%3E%3C/svg%3E",
    'xlsx': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2322c55e'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%2386efac'/%3E%3Ctext x='6' y='17' font-size='5' font-weight='bold' fill='white'%3EXLS%3C/text%3E%3C/svg%3E",
    'xls': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2322c55e'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%2386efac'/%3E%3Ctext x='6' y='17' font-size='5' font-weight='bold' fill='white'%3EXLS%3C/text%3E%3C/svg%3E",
    'zip': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%238b5cf6'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23c4b5fd'/%3E%3Ctext x='7' y='17' font-size='5' font-weight='bold' fill='white'%3EZIP%3C/text%3E%3C/svg%3E",
    'html': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2306b6d4'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%2367e8f9'/%3E%3Ctext x='4' y='17' font-size='5' font-weight='bold' fill='white'%3EHTML%3C/text%3E%3C/svg%3E",
    'txt': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%236b7280'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23d1d5db'/%3E%3Ctext x='7' y='17' font-size='5' font-weight='bold' fill='white'%3ETXT%3C/text%3E%3C/svg%3E",
    'jpg': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23eab308'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23fde047'/%3E%3Ctext x='6' y='17' font-size='5' font-weight='bold' fill='white'%3EJPG%3C/text%3E%3C/svg%3E",
    'jpeg': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23eab308'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23fde047'/%3E%3Ctext x='6' y='17' font-size='5' font-weight='bold' fill='white'%3EJPG%3C/text%3E%3C/svg%3E",
    'png': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2314b8a6'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%235eead4'/%3E%3Ctext x='5' y='17' font-size='5' font-weight='bold' fill='white'%3EPNG%3C/text%3E%3C/svg%3E",
    'mp4': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23ec4899'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23f9a8d4'/%3E%3Ctext x='5' y='17' font-size='5' font-weight='bold' fill='white'%3EMP4%3C/text%3E%3C/svg%3E",
    'mp3': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23a855f7'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23d8b4fe'/%3E%3Ctext x='5' y='17' font-size='5' font-weight='bold' fill='white'%3EMP3%3C/text%3E%3C/svg%3E",
    'csv': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2322c55e'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%2386efac'/%3E%3Ctext x='6' y='17' font-size='5' font-weight='bold' fill='white'%3ECSV%3C/text%3E%3C/svg%3E",
    'url': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2338bdf8'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%237dd3fc'/%3E%3Ctext x='5' y='17' font-size='5' font-weight='bold' fill='white'%3EURL%3C/text%3E%3C/svg%3E",
    'other': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2364748b'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23cbd5e1'/%3E%3Ctext x='2' y='17' font-size='5' font-weight='bold' fill='white'%3EOTHER%3C/text%3E%3C/svg%3E",
}
_FILETYPE_SVG_DEFAULT = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%234b5563'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%239ca3af'/%3E%3C/svg%3E"


def _build_filetype_pills_html(files: list) -> str:
    """Return filetype pill HTML string for a list of filenames."""
    import os
    from collections import Counter

    WHITELIST = {'pdf', 'docx', 'pptx', 'xlsx', 'zip', 'mp4', 'mp3', 'js', 'html', 'css', 'txt', 'sql', 'jpg', 'png', 'doc', 'ppt', 'xls', 'md', 'csv', 'json', 'py', 'java', 'c', 'cpp', 'webloc', 'url'}

    ext_counts = Counter()
    for f in files:
        ext = os.path.splitext(f)[1].lower().lstrip('.')
        if ext in WHITELIST:
            ext_counts[ext] += 1
        else:
            ext_counts['other'] += 1

    specific_exts = {k: v for k, v in ext_counts.items() if k != 'other'}
    sorted_specific = sorted(specific_exts.items(), key=lambda x: -x[1])

    top_4 = sorted_specific[:4]
    remaining_count = sum(v for k, v in sorted_specific[4:])
    other_count = ext_counts.get('other', 0) + remaining_count

    html = ''
    for ext, count in top_4:
        icon_url = _FILETYPE_SVGS.get(ext, _FILETYPE_SVG_DEFAULT)
        html += (
            f'<div class="filetype-pill">'
            f'<img class="ft-icon" src="{icon_url}" alt="{ext}"/>'
            f'<span class="ft-label">{esc(ext.upper())}</span>'
            f'<span class="ft-count">{count}</span>'
            f'</div>'
        )
    if other_count > 0:
        html += (
            f'<div class="filetype-pill">'
            f'<img class="ft-icon" src="{_FILETYPE_SVG_DEFAULT}" alt="other"/>'
            f'<span class="ft-label">Other files</span>'
            f'<span class="ft-count">{other_count}</span>'
            f'</div>'
        )
    return html




# --- Error type to human-friendly message mapping ---
_ERROR_TRANSLATIONS = {
    'No URL': 'Canvas did not provide a download link for this file',
    'LTI/Media Stream': 'This is a streamed video that cannot be downloaded directly',
    'Locked File': 'The teacher has locked this file on Canvas - it may become downloadable when they unlock it',
    'URL Expiration': 'The download link expired and could not be refreshed',
    'Network Error': 'Network connection failed after multiple retries',
    'SSL Certificate Error': 'Your computer could not verify the secure connection to Canvas - check for a VPN, proxy or firewall intercepting traffic, or update Canvas Downloader',
    'Write Error': 'Could not save the file to disk - check available storage',
    '401 Unauthorized': 'Access denied - you may not have permission to download this file',
    'Missing Content ID': 'Canvas did not provide a file reference for this item',
    'Missing Page URL': 'Canvas did not provide a URL for this page',
    'Missing External URL': 'Canvas did not provide a URL for this link',
    'Missing Tool URL': 'Canvas did not provide a launch URL for this external tool',
    'Item Processing Error': 'An unexpected error occurred while processing this item',
    'Module Error': 'Could not load this module from Canvas',
    'Async Error': 'A download task failed unexpectedly',
    'Processing Error': 'An unexpected error occurred during download',
    'Hybrid Mode Error': 'An unexpected error occurred while scanning the course',
    'Canvas Content Error': 'Could not download Canvas Content',
    'Canvas Content Retry Error': 'Retry also failed for Canvas Content',
    'Fetch Error': 'Could not load this resource from Canvas',
    'Queue Error': 'Failed to queue this file for download',
    'Legacy Entity Save Error': 'Could not save this item to disk',
}

def _friendly_error_reason(err) -> str:
    """Translate a DownloadError into a human-readable reason string."""
    if not hasattr(err, 'error_type'):
        return 'Download failed'

    error_type = err.error_type or ''

    # Direct match
    if error_type in _ERROR_TRANSLATIONS:
        return _ERROR_TRANSLATIONS[error_type]

    # HTTP status codes
    if error_type.startswith('HTTP '):
        code = error_type.replace('HTTP ', '')
        if code == '401':
            return 'Access denied - you may not have permission to download this file'
        if code == '403':
            return 'Access forbidden by Canvas'
        if code == '404':
            return 'File not found on Canvas - it may have been removed'
        return f'Canvas returned an error (HTTP {code})'

    # Check message for common patterns
    msg = (getattr(err, 'message', '') or '').lower()
    if 'unauthorized' in msg or 'not authorised' in msg:
        return 'Access denied - you may not have permission to download this file'
    if 'not found' in msg:
        return 'File not found on Canvas - it may have been removed'
    if 'timeout' in msg:
        return 'Connection timed out while downloading'

    return 'Download failed - see error log for technical details'


# SVG chevron for error panel toggle
_CHEVRON_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M9 18l6-6-6-6'/%3E%3C/svg%3E"
# SVG alert circle for error rows
_ALERT_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f87171' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cline x1='12' y1='8' x2='12' y2='12'/%3E%3Cline x1='12' y1='16' x2='12.01' y2='16'/%3E%3C/svg%3E"
# Light version of alert for the error expander title, matching the stat-card.stat-error icon color
_ALERT_LIGHT_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23fca5a5' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cline x1='12' y1='8' x2='12' y2='12'/%3E%3Cline x1='12' y1='16' x2='12.01' y2='16'/%3E%3C/svg%3E"

# The same slash-circle the "Cannot Be Downloaded" stat card uses, in the same
# grey, so the card and the panel it explains are recognisably one thing.
_SLASH_GREY_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cline x1='4.93' y1='4.93' x2='19.07' y2='19.07'/%3E%3C/svg%3E"


def _course_id_from_sync_pairs(course_name: str):
    """Resolve a Canvas course id from the sync pairs, by course name.

    Sync mode has no ``courses_to_download`` (that is download-mode state), so
    without this the error rows for a SYNC run could never resolve a course id and
    every "Open in Canvas" link degraded to the course-less ``/files/<id>`` form.
    The previous fallback here read a ``sync_state`` session key that is **written
    nowhere in the codebase** - it always evaluated to ``{}``, so the branch could
    never execute. ``sync_pairs`` is the real source of truth.

    Matching is done on the friendly form of both sides: the engine reports the
    full Canvas name ("IT-projektledelse (LA F26 BINTO1059U)") while a pair may
    have been saved with the display name ("IT-projektledelse (LA)").
    """
    if not course_name:
        return None
    try:
        from shared.helpers import friendly_course_name
    except Exception:
        def friendly_course_name(n):  # pragma: no cover - import guard only
            return n

    def _keys(name: str) -> set:
        name = (name or '').strip()
        out = {name.casefold()}
        try:
            out.add((friendly_course_name(name) or '').strip().casefold())
        except Exception:
            pass
        return {k for k in out if k}

    wanted = _keys(course_name)
    for pair in st.session_state.get('sync_pairs', []) or []:
        if not isinstance(pair, dict):
            continue
        cid = pair.get('course_id')
        if not cid:
            continue
        if _keys(pair.get('course_name', '')) & wanted:
            return cid
    return None


def run_had_auth_failure(error_list) -> bool:
    """True only when a run's errors indicate the TOKEN itself died (expired or
    revoked) mid-run - NOT a per-endpoint 401.

    This distinction is the whole point. The download engine deliberately
    tolerates per-endpoint 401s - a hidden Pages tab, a restricted quiz - as
    normal, expected restrictions (most are skipped outright). Treating one of
    those as "your session expired" would tell a user to regenerate a token
    that is perfectly valid, which is worse friction than the errors themselves.

    So the signal must be SYSTEMIC, not per-item:
      - a DownloadError flagged ``is_app_error`` (a whole course/engine
        operation crashed) whose payload is an auth error - the token could not
        even list the course, so it is the token, not one restricted feature; or
      - several (>= 3) item-level auth errors - a dead token 401s everything
        after it, so one stray 401 can never trip this; or
      - a sync-error string that is an auth error - sync targets the teacher's
        own course files, which are not per-endpoint restricted, so an auth
        failure there is the token.
    All matching goes through the central :func:`is_auth_error`.
    """
    from core.canvas_logic import is_auth_error
    item_auth = 0
    for e in error_list or []:
        if isinstance(e, str):
            if is_auth_error(e):
                return True
            continue
        _is_auth = (
            str(getattr(e, 'error_type', '') or '').strip() in ('401', 'Unauthorized')
            or is_auth_error(str(getattr(e, 'raw_error', '') or ''))
            or is_auth_error(str(getattr(e, 'message', '') or ''))
        )
        if not _is_auth:
            continue
        if getattr(e, 'is_app_error', False):
            return True
        item_auth += 1
    return item_auth >= 3


def render_error_section(error_list: list, key_prefix: str = 'dl',
                         retry_btn_callback=None, has_retriable_errors: bool = False,
                         retry_failed: bool = False):
    """Render error details as a custom CSS panel with human-friendly messages.

    Args:
        error_list: List of error messages or DownloadError objects.
        key_prefix: Unique prefix for Streamlit widget keys.
        retry_btn_callback: If provided, renders the retry button inside the panel.
        has_retriable_errors: Whether retriable errors exist (controls retry btn visibility).
        retry_failed: True when a retry was already attempted and all items still failed.
    """
    if not error_list:
        return

    # A token that expired/was revoked DURING the run 401s everything after it.
    # Both the download and sync completion screens route their errors here, so
    # this one banner + button gives the user the clean reconnect flow from
    # either screen instead of leaving them staring at a wall of 401s. Rendered
    # above the error panel as real Streamlit elements. The presence of this CTA
    # is fixed for a finished run (the error list no longer changes), so it does
    # not flip-flop across reruns of the terminal screen.
    if run_had_auth_failure(error_list):
        st.markdown(
            "<div style='display:flex; align-items:flex-start; gap:11px; "
            "background:rgba(249,115,22,0.12); border:1px solid rgba(249,115,22,0.40); "
            "border-radius:8px; padding:13px 15px; margin-bottom:14px;'>"
            "<svg viewBox='0 0 24 24' width='19' height='19' style='flex-shrink:0; margin-top:1px;' "
            "fill='none' stroke='#f97316' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
            "<path d='M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'/>"
            "<line x1='12' y1='9' x2='12' y2='13'/><line x1='12' y1='17' x2='12.01' y2='17'/></svg>"
            "<div><div style='color:#fdba74; font-weight:700; font-size:0.95rem; margin-bottom:3px;'>"
            "Your Canvas session expired during this run</div>"
            "<div style='color:#fcd9b6; font-size:0.88rem; line-height:1.5;'>"
            "Some items couldn't be downloaded because your access token expired or was revoked. "
            "Reconnect with a new token, then run it again to pick up what's missing. "
            "Your Canvas address is still saved.</div></div></div>",
            unsafe_allow_html=True,
        )
        if st.button("Reconnect to Canvas", key=f"{key_prefix}_reconnect_expired", type="primary"):
            from ui.auth import force_reauth
            force_reauth("Your Canvas Access Token expired during your last run. "
                         "Please reconnect with a new token, then run it again.")

    import os
    import re
    from collections import defaultdict
    count = len(error_list)

    def _err_row_html(err):
        if hasattr(err, 'item_name'):
            fname = err.item_name or 'Unknown file'
            ext = os.path.splitext(fname)[1].lower().lstrip('.')
            fname = os.path.splitext(fname)[0] if ext else fname
            ft_icon_url = _FILETYPE_SVGS.get(ext, _FILETYPE_SVG_DEFAULT)
            
            link_html = ''
            
            api_url = st.session_state.get('api_url', '').rstrip('/')
            if api_url and not api_url.startswith(('http://', 'https://')):
                api_url = ''
            if api_url and hasattr(err, 'context') and isinstance(err.context, dict):
                f_dict = err.context.get('file_dict', {})
                fid = f_dict.get('id')
                furl = f_dict.get('url', '')
                
                course_id = None
                if hasattr(err, 'course_name'):
                    for c in st.session_state.get('courses_to_download', []):
                        if c.name == err.course_name:
                            course_id = c.id
                            break
                    if not course_id:
                        course_id = _course_id_from_sync_pairs(err.course_name)

                canvas_url = None
                if furl and ('/courses/' in furl or '/assignments/' in furl or '/discussion_topics/' in furl or '/quizzes/' in furl):
                    canvas_url = furl
                elif fid and str(fid).isdigit():
                    if course_id:
                        canvas_url = f"{api_url}/courses/{course_id}/files/{fid}"
                    else:
                        canvas_url = f"{api_url}/files/{fid}"
                    
                if canvas_url:
                    _LINK_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>'''
                    link_html = f'<a href="{esc(canvas_url)}" target="_blank" rel="noopener noreferrer" class="err-link-btn" title="Open in Canvas">{_LINK_SVG}</a>'

            return (
                f'<div class="error-row">'
                f'<img class="err-icon" src="{ft_icon_url}" alt="{ext}"/>'
                f'<div class="err-body">'
                f'<span class="err-filename">{esc(fname)}</span>'
                f'{link_html}'
                f'</div></div>'
            )
        else:
            # A sync error is a STRING - "Error syncing notes.pdf: Connection
            # reset by peer" - and it used to be printed whole, so the row read
            # like a log line that had been given a file icon. The technical
            # tail is not the filename, and the column's own subtitle already
            # says what happened to every file in it; naming the cause per row
            # tells the user nothing they can act on and buries the one thing
            # they need, which is WHICH file. Same row shape as the object
            # branch above, so the two flows are indistinguishable here.
            _m = re.match(r'^\s*Error syncing (.+?):\s', str(err))
            fname = _m.group(1) if _m else str(err)
            ext = os.path.splitext(fname)[1].lower().lstrip('.')
            label = os.path.splitext(fname)[0] if ext else fname
            return (
                f'<div class="error-row">'
                f'<img class="err-icon" src="{_FILETYPE_SVGS.get(ext, _FILETYPE_SVG_DEFAULT)}" alt="{esc(ext)}"/>'
                f'<div class="err-body">'
                f'<span class="err-filename">{esc(label)}</span>'
                f'</div></div>'
            )

    # Split into: retriable file errors / unresolvable file errors / app-level errors
    actionable, unresolvable, app_errors = [], [], []
    for err in error_list[:20]:
        if getattr(err, 'is_app_error', False):
            app_errors.append(err)
            continue
        is_retriable = (
            hasattr(err, 'item_name')
            and isinstance(getattr(err, 'context', None), dict)
            and err.context.get('filepath')
            and getattr(err, 'error_type', '') != 'LTI/Media Stream'
            and not getattr(err, 'retry_exhausted', False)
        )
        if is_retriable or not hasattr(err, 'item_name'):
            actionable.append(err)
        else:
            unresolvable.append(err)

    # Build left column: "Failed to Download" (actionable / retriable errors)
    left_col_html = ''
    if actionable:
        if retry_failed:
            subtitle = "We tried to download these files again, with no success. Please try downloading these files manually via Canvas."
            subtitle_class = 'err-col-subtitle err-col-subtitle-failed'
        else:
            subtitle = "These files timed out or failed. Click the <b>Retry</b> button below to try grabbing them again."
            subtitle_class = 'err-col-subtitle'
        rows = ''.join(_err_row_html(e) for e in actionable)
        left_col_html = (
            f'<div class="err-col">'
            f'<div class="err-col-header">'
            f'<span class="err-col-title">Failed to Download</span>'
            f'<span class="err-group-badge err-group-badge-error">{len(actionable)}</span>'
            f'</div>'
            f'<div class="{subtitle_class}">{subtitle}</div>'
            f'{rows}'
            f'</div>'
        )

    # Build right column: "Stream-Only Videos" or generic unresolvable
    right_col_html = ''
    if unresolvable:
        by_reason = defaultdict(list)
        for err in unresolvable:
            reason = _friendly_error_reason(err)
            by_reason[reason].append(err)

        lti_count = sum(1 for e in unresolvable if getattr(e, 'error_type', '') == 'LTI/Media Stream')
        if lti_count == len(unresolvable):
            col_title = 'Unavailable Files (Stream-Only)'
            badge_class = 'err-group-badge-neutral'
        else:
            col_title = 'Cannot Be Downloaded'
            badge_class = 'err-group-badge-muted'
        # The specific sentence, not "these files have a permanent issue" -
        # this is where the full-width prose row that used to sit under the
        # stat grid went, and it is the reason removing it loses nothing. Built
        # by the same helper the classifier feeds, so the two screens cannot
        # word it differently.
        col_subtitle = declined_reason_sentence(
            split_delivery_errors(unresolvable)['reasons'], len(unresolvable))

        sub_html = ''
        for reason, errs in by_reason.items():
            rows = ''.join(_err_row_html(e) for e in errs)
            if len(by_reason) > 1:
                sub_html += f'<div class="err-subgroup-reason">{esc(reason)}</div>'
            sub_html += rows

        right_col_html = (
            f'<div class="err-col">'
            f'<div class="err-col-header">'
            f'<span class="err-col-title">{col_title}</span>'
            f'<span class="err-group-badge {badge_class}">{len(unresolvable)}</span>'
            f'</div>'
            f'<div class="err-col-subtitle">{col_subtitle}</div>'
            f'{sub_html}'
            f'</div>'
        )

    body_html = f'<div class="error-columns">{left_col_html}{right_col_html}</div>'

    # App-level errors: separate section below the file columns
    if app_errors:
        _WARN_SVG = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='width:15px;height:15px;flex-shrink:0;margin-top:1px;'><path d='M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'/><line x1='12' y1='9' x2='12' y2='13'/><line x1='12' y1='17' x2='12.01' y2='17'/></svg>"
        app_rows_html = ''
        for err in app_errors:
            error_type = esc(getattr(err, 'error_type', 'Application Error') or 'Application Error')
            course_name = esc(getattr(err, 'course_name', '') or '')
            message = esc(getattr(err, 'message', '') or '')
            # Truncate long technical messages
            if len(message) > 220:
                message = message[:220] + '…'
            course_prefix = f'<span class="app-err-course">{course_name}</span> ' if course_name else ''
            app_rows_html += (
                f'<div class="app-error-row">'
                f'<div class="app-err-type-badge">{error_type}</div>'
                f'<div class="app-err-detail">'
                f'{course_prefix}'
                f'<span class="app-err-msg">{message}</span>'
                f'</div>'
                f'</div>'
            )
        # NOT "check your settings and API connection".
        #
        # That sentence was wrong in three ways at once. It blamed the user for
        # a fault in our code. It named "API connection", which most students
        # have never heard of and cannot check. And it was not actionable: no
        # setting on this machine fixes an UnboundLocalError in the engine.
        #
        # What is true, and what a person actually needs to know, is: this is a
        # bug, the rest of your download is fine, and here is how to tell the
        # developer.
        _n_app = len(app_errors)
        body_html += (
            f'<div class="app-error-section">'
            f'<div class="app-error-section-header">'
            f'{_WARN_SVG}'
            f'<span class="app-error-section-title">Something went wrong inside the app</span>'
            f'<span class="err-group-badge err-group-badge-warn">{_n_app}</span>'
            f'</div>'
            f'<div class="app-error-section-subtitle">'
            f'This is a bug in Canvas Downloader, not something you did, and it is '
            f'not caused by your settings. Everything else on this screen '
            f'downloaded normally. Sending the report is the only thing that '
            f'helps &mdash; it is what gets {"it" if _n_app == 1 else "these"} fixed.'
            f'</div>'
            f'{build_app_error_actions(app_errors)}'
            f'{app_rows_html}'
            f'</div>'
        )

    if count > 20:
        body_html += f'<div style="padding:6px 0;color:#6b7280;font-size:0.82em;">... and {count - 20} more errors</div>'

    # Footer
    footer_html = ''
    if st.session_state.get('error_log_enabled', False):
        footer_html = '<div class="error-panel-footer">Full error details are saved in <code>download_errors.txt</code> in each course folder.</div>'

    # THE PANEL IS NAMED AFTER WHAT IT CONTAINS.
    #
    # It was always "Error Details" behind a red alert glyph. On a run whose
    # only entries are teacher-locked files the card above says "Download
    # Success" and shows a neutral grey "3 Cannot Be Downloaded" - and then
    # this panel called the very same three files errors, in red. The user
    # meets the stat card first, so the panel has to answer the question that
    # card raises, with its own words and its own colour.
    #
    # "Blocking" is the same distinction the headline card makes: a retriable
    # failure or an app error is a problem, a declined item is an outcome.
    _blocking = bool(actionable or app_errors)
    if _blocking:
        _panel_title = 'Error Details'
        _panel_icon = _ALERT_LIGHT_SVG
        _panel_icon_bg = 'rgba(239, 68, 68, 0.2)'
    else:
        _panel_title = 'Cannot Be Downloaded'
        _panel_icon = _SLASH_GREY_SVG
        _panel_icon_bg = 'rgba(156, 163, 175, 0.18)'

    st.markdown(
        f'<details class="error-panel">'
        f'<summary class="error-panel-header">'
        f'<div class="ep-header-row">'
        f'<img class="chevron" src="{_CHEVRON_SVG}" alt="toggle"/>'
        f'<div style="display:flex; align-items:center; justify-content:center; width:26px; height:26px; background:{_panel_icon_bg}; border-radius:6px; flex-shrink:0;">'
        f'<img src="{_panel_icon}" alt="" style="width:16px; height:16px;"/>'
        f'</div>'
        f'<span class="ep-title" style="color: #d1d5db; font-weight: 400;">{esc(_panel_title)}</span>'
        f'</div>'
        f'</summary>'
        f'<div class="error-panel-body">'
        f'{body_html}{footer_html}'
        f'</div>'
        f'</details>',
        unsafe_allow_html=True,
    )

    # NO "View Full Error Log" BUTTON. It was a stock Streamlit button offering
    # a raw log file, and it appeared on runs that had succeeded - a green
    # "Download Success" screen whose only entries were locked files still
    # invited the user to go and read an error log. It is not actionable
    # either: every error the log holds is already on this screen, named, and
    # what a user does about one of them happens on Canvas, not in a text file.
    # `error_log_dialog` is kept for a future diagnostics surface.

    if app_errors:
        # The controls themselves are inside the notice, in the markdown above.
        # This only teaches the copy button how to copy.
        inject_app_error_copy_bridge()

    # Retry button - placed in half-width left column under the error panel
    # so it visually associates with the "Failed to Download" column only.
    if has_retriable_errors and retry_btn_callback:
        retriable_count = sum(
            1 for err in error_list
            if not getattr(err, 'is_app_error', False)
            and isinstance(getattr(err, 'context', None), dict)
            and err.context.get('filepath')
            and getattr(err, 'error_type', '') != 'LTI/Media Stream'
            and not getattr(err, 'retry_exhausted', False)
        )
        _dl_word = 'download' if retriable_count == 1 else 'downloads'
        btn_text = "Retry failed downloads" if retry_failed else (
            f"Retry {retriable_count} failed {_dl_word}" if retriable_count > 0 else "Retry failed downloads"
        )
        retry_tooltip = (
            "We couldn't download these files after retrying. "
            "You can find them directly on Canvas and download from there."
        ) if retry_failed else None
        col_retry, _ = st.columns(2)
        with col_retry:
            if st.button(btn_text, type="secondary", key=f"{key_prefix}_retry_failed_btn",
                         use_container_width=True, disabled=retry_failed,
                         help=retry_tooltip):
                retry_btn_callback()

    # Retries exhausted: name the next step. This lives HERE, not at the call
    # sites, so download mode and sync mode cannot drift apart - previously only
    # sync/completion.py rendered it, so a download user whose retry was spent got
    # a dead Retry button and no guidance at all. Rendered whenever retry_failed
    # is set, including when there is no retry callback left to offer.
    if retry_failed:
        from ui.amber_notice import render_amber_notice
        render_amber_notice(
            "Retry didn't work - these files may be temporarily unavailable.",
            detail="Check your internet connection and try again later, or download them directly from Canvas.",
            margin="0",  # the card's flex gap (16px) is the ONE rhythm; a margin here adds to it
        )


# Stop glyph for the cancelled card - lucide "octagon-x". An inline SVG, not the
# old 🛑 emoji: the emoji was the last one left on these screens in an otherwise
# all-SVG icon system, and it renders at a different weight per platform.
_CANCEL_OCTAGON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" style="flex-shrink:0;">'
    '<path d="m15 9-6 6"/><path d="m9 9 6 6"/>'
    '<path d="M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 '
    '2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 '
    '0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 '
    '1-1.414-.586z"/></svg>'
)


def cancel_summary_message(done: int, total: int) -> str:
    """The one-line "how far did it get" summary on a cancelled screen.

    Shared by download and sync so the wording cannot drift. ``total == 0`` means
    the run was still enumerating courses when it was cancelled - no file count
    exists yet, so saying "0 of 0 files" would be misleading.
    """
    if st.session_state.get('is_post_processing', False):
        return "Cancelled during post-processing."
    if total > 0:
        return f"Cancelled after {done} of {total} file{'s' if total != 1 else ''}."
    return "Cancelled during Course Analysis."


def quit_office_once() -> None:
    """macOS: force-close staged docs and quit idle Office apps, once per run.

    Identical in both cancelled screens (and the completion screens), so it lives
    here rather than being pasted at each call site. First force-closes any
    document a cancelled conversion left open in a hidden Office process
    (marker-matched, so the user's own documents are untouchable), then quits the
    now-idle apps and purges our Recents entries. No-op off macOS.
    """
    import sys
    if sys.platform != 'darwin' or st.session_state.get('_office_quit_fired'):
        return
    st.session_state['_office_quit_fired'] = True
    try:
        from engine.applescript_bridge import quit_idle_office_apps
        quit_idle_office_apps()
    except Exception:
        pass


def render_cancelled_card(what: str, done: int, total: int) -> None:
    """Render the "<what> Cancelled" card. THE single implementation.

    This card previously existed twice - once in app.py for download mode and once
    in sync/completion.py - as ~30 lines of duplicated inline CSS, with a comment
    in app.py saying it "matches sync_ui.py design". Two copies of one visual is
    exactly the mechanism by which the two modes drift apart, so there is now one.

    Deliberately renders NO error list: the user cancelled, so partial-run errors
    are noise. Errors are surfaced only on the completion screens, via
    render_error_section, where they are actionable.

    Args:
        what:  "Download" or "Sync" - used for both the heading and the sentence.
        done:  items finished before the cancel.
        total: items planned (0 when the run was still enumerating courses).
    """
    # ONE HUE. The gradient used to run from ERROR_BG to BG_PAGE, and BG_PAGE
    # (#0e1117) is a blue-black - so the right-hand half of a card whose entire
    # message is "cancelled" faded into a cool blue-violet, which is the one
    # colour on the completion screens that means "informational". Fading red
    # into transparent keeps the card sitting on whatever it is placed over
    # while staying red across its whole width.
    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, {theme.ERROR_BG} 0%, rgba(127, 29, 29, 0.04) 100%);
        border: 1px solid {theme.ERROR};
        border-radius: 12px;
        padding: 28px 32px;
        margin: 20px 0;
        box-shadow: 0 4px 20px rgba(239, 68, 68, 0.15);
    ">
        <div style="display: flex; align-items: center; gap: 14px; margin-bottom: 12px;
                    color: {theme.ERROR};">
            {_CANCEL_OCTAGON_SVG}
            <h2 style="margin: 0; color: {theme.ERROR}; font-size: 1.5rem; font-weight: 700;">{esc(what)} Cancelled</h2>
        </div>
        <p style="color: {theme.TEXT_LIGHT}; font-size: 1rem; margin: 0 0 8px 0;">
            {esc(what)} was cancelled.
        </p>
        <div style="
            background: rgba(239, 68, 68, 0.08);
            border-radius: 8px;
            padding: 12px 16px;
            margin-top: 12px;
            display: inline-block;
        ">
            <span style="color: {theme.ERROR_LIGHT}; font-size: 0.9rem; font-weight: 600;">
                {esc(cancel_summary_message(done, total))}
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)  # audit-ignore: SVG constant + esc()'d text only


# Icons for the "deliberately left alone" notices (size-skipped files,
# unpacked archives). Module level because BOTH notices use them and a second
# copy is a second chance to get the encoding wrong.
#
# NOTE the quoting rule: these data URIs contain SINGLE quotes (xmlns='...'),
# so the src attribute that carries them must be wrapped in DOUBLE quotes. Using
# single quotes terminates the attribute at the first one inside the URI and the
# browser renders a broken-image glyph - which is exactly what happened when the
# archive notice was written with 'src=...'.
_SKIP_CHEVRON_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'"
    " fill='none' stroke='%239ca3af' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Cpath d='M9 18l6-6-6-6'/%3E%3C/svg%3E"
)
_SKIP_FUNNEL_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'"
    " fill='%239ca3af' stroke='%239ca3af' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Cpolygon points='22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3'/%3E%3C/svg%3E"
)
# FILLED, not stroked. Its neighbour in the same panel stack is the solid
# funnel above, so a 2px outline glyph read as a lighter, thinner element of a
# different family - the two notices are meant to look like one thing. The
# "holes" (lid seam and handle) are punched with fill-rule: evenodd so the
# shape still reads as a box at 16px rather than as a filled rectangle.
_SKIP_ARCHIVE_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'"
    " fill='%239ca3af' fill-rule='evenodd'%3E"
    "%3Cpath d='M1 3h22v5H1V3zm2 6h18v12H3V9zm6 2h6v2H9v-2z'/%3E"
    "%3C/svg%3E"
)


def render_archives_skipped_notice():
    """Name the archives the file-count guard declined to unpack.

    Deliberately NOT an amber warning: nothing failed and nothing is missing.
    The archive is still in the course folder exactly as Canvas served it, and
    the user can unpack it themselves - which is the whole difference between a
    guard and a hard limit. It is stated here rather than only in the
    post-processing log because that log is gone by the time this screen is
    read, and a silent guard produces exactly one question: "why is my zip still
    a zip?"
    """
    import os as _os
    names = st.session_state.get('pp_archives_skipped') or []
    if not names:
        return
    limit = int(st.session_state.get('archive_max_files', 0) or 0)
    n = len(names)
    # Same one-row shape as the size-skip notice above: the sentence IS the
    # control, chevron leading. Two notices about "things deliberately left
    # alone" should not look like two different features.
    #
    # And the same ROW shape too: filetype icon, name, extension tag, size.
    # These were bare text on an indent while the size-skip list directly above
    # used the app's established file row, so one panel spoke the application's
    # visual language and its neighbour did not.
    #
    # Entries are {'name', 'bytes'}; a bare string is still accepted because a
    # session that started before this version can hold the old shape in
    # `pp_archives_skipped`, and a completion screen must never be the thing
    # that raises.
    _rows_html = ''
    for _entry in names[:50]:
        if isinstance(_entry, dict):
            _name = str(_entry.get('name') or '')
            _bytes = int(_entry.get('bytes') or 0)
        else:
            _name, _bytes = str(_entry), 0
        _ext = _os.path.splitext(_name)[1].lower().lstrip('.')
        _stem = _os.path.splitext(_name)[0] if _ext else _name
        _icon = _FILETYPE_SVGS.get(_ext, _FILETYPE_SVG_DEFAULT)
        _ext_badge = (f'<span class="skip-ext-badge">{esc(_ext.upper())}</span>'
                      if _ext else '')
        _size_badge = (f'<span class="skip-file-size">{esc(format_file_size(_bytes))}</span>'
                       if _bytes else '')
        _rows_html += (
            f'<div class="skip-file-row">'
            f'<img class="skip-file-icon" src="{_icon}" alt="{esc(_ext)}"/>'
            f'<span class="skip-file-name">{esc(_stem)}</span>'
            f'{_ext_badge}{_size_badge}'
            f'</div>'
        )
    st.markdown(
        "<details class='skip-panel skip-panel-solo'>"
        "<summary class='skip-panel-header'><div class='sp-header-row'>"
        f'<img class="sp-chevron" src="{_SKIP_CHEVRON_SVG}" alt="toggle"/>'
        f'<img class="sp-funnel" src="{_SKIP_ARCHIVE_SVG}" alt=""/>'
        f"<span class='sp-title'><b>{n}</b> archive{'s were' if n != 1 else ' was'} "
        f"left unpacked because {'they contain' if n != 1 else 'it contains'} more "
        f"than <b>{limit:,} files</b>.</span>"
        "</div></summary>"
        "<div class='skip-panel-body'>"
        "<div class='sp-subtitle'>The .zip "
        f"{'files are' if n != 1 else 'file is'} still in your course folder, so "
        "nothing is missing. Unpack "
        f"{'them' if n != 1 else 'it'} yourself, or raise the limit in "
        "<b>Settings &rsaquo; Skip huge archives</b>.</div>"
        f"<div class='skip-file-list'>{_rows_html}</div>"
        "</div></details>",
        unsafe_allow_html=True,
    )


DEVELOPER_EMAIL = "brkbuilds1@gmail.com"

# Gmail's compose endpoint, NOT mailto:.
#
# `mailto:` hands the URL to the OS, and the OS is the problem. On Windows a
# machine with no desktop mail client shows "You'll need a new app to open this
# mailto link", or nothing at all - and students who live in Gmail have no such
# client. On macOS it ALWAYS resolves to Mail.app, which is installed and is
# the default handler even when it has never been set up, so an unconfigured
# Mac opens the account-setup wizard: a worse dead end than nothing, because it
# reads as the app demanding their email password.
#
# An https URL opens in the default browser, which every machine has, and
# behaves identically on both platforms. Anyone not signed into Gmail uses the
# copy button beside it instead - which is why that button is not optional.
#
# `tf=cm`, NOT the older `view=cm&fs=1`. Both open a compose window, but
# `view=cm` opens the standalone compose PAGE - a text editor floating on an
# otherwise blank white canvas, with no Gmail around it - which is alarming
# when you have just been told to report a bug and reads as a broken page.
# `tf=cm` opens the full Gmail interface with the compose window inside it, and
# `fs` is documented as no longer doing anything at all.
_GMAIL_COMPOSE = "https://mail.google.com/mail/u/0/?tf=cm"

# Keep the whole URL inside what the OS will carry. pywebview hands the href to
# `webbrowser.open`, which on Windows reaches ShellExecuteW - historically
# ~2048 characters - and URL-encoding inflates log text (every newline becomes
# `%0A`). 1900 is comfortably inside that with room for the base URL and
# subject. The email therefore carries a CURATED extract; the clipboard, which
# has no such limit, carries everything.
_EMAIL_URL_LIMIT = 1900

# The tail of a debug log is verbose but bounded. 40 KB is a few hundred lines
# of real request/response history - enough to see what the run was doing when
# it broke, without pasting a 5 MB file into an email.
_DEBUG_TAIL_BYTES = 40 * 1024

# A ceiling on the WHOLE bundle. It is embedded in the page as a hidden span and
# re-escaped on every render of the completion screen, and the debug-tail budget
# is per FILE with one file per course - so a 12-course download could otherwise
# put ~750 KB of text into the DOM, on every rerun, to serve a button that most
# users never press. 192 KB is far more log than any bug report needs and keeps
# the page weight bounded regardless of how many courses ran.
_BUNDLE_MAX_CHARS = 192 * 1024

# The marker has to EXPLAIN ITSELF. "--- PASTE THE FULL REPORT BELOW ---" was
# meaningless to the person reading it: nothing on screen had told them a
# clipboard copy happened, so the instruction referred to something they did
# not know they had. It has to say what is on the clipboard, that it is already
# there, and that sending without pasting is still fine - otherwise a user who
# cannot paste assumes the whole report is void and abandons it.
_PASTE_MARKER = (
    "----------------------------------------------------------------\n"
    "The FULL log is already on your clipboard - click below this line\n"
    "and press Ctrl+V (Cmd+V on Mac) to add it, then send.\n"
    "(No paste? Send it as-is - the summary above is still useful.)\n"
    "----------------------------------------------------------------"
)

_REPORT_MAIL_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
    "stroke='currentColor' stroke-width='2' stroke-linecap='round' "
    "stroke-linejoin='round' aria-hidden='true'>"
    "<rect x='2' y='4' width='20' height='16' rx='2'/>"
    "<path d='m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7'/></svg>"
)
_REPORT_COPY_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
    "stroke='currentColor' stroke-width='2' stroke-linecap='round' "
    "stroke-linejoin='round' aria-hidden='true'>"
    "<rect x='9' y='9' width='13' height='13' rx='2'/>"
    "<path d='M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'/></svg>"
)


def build_app_error_actions(app_errors: list) -> str:
    """The report controls, as HTML, so they can live INSIDE the notice.

    This is markup rather than ``st.button`` for a structural reason, not a
    stylistic one: the app-error notice is rendered inside a raw-HTML
    ``<details>``, and a Streamlit widget cannot be nested in raw HTML. Putting
    the control anywhere a widget CAN go means putting it outside the box that
    explains it - which is where it was, and it read as an unrelated button
    floating under the panel.

    Being an anchor also settles the styling question permanently. There is no
    stock Streamlit button to override.

    ``target="_blank"`` is MANDATORY, not decoration. pywebview routes
    new-window requests to the system browser
    (``OPEN_EXTERNAL_LINKS_IN_BROWSER`` defaults True; edgechromium.py:252 and
    cocoa.py:257), and marks them handled so the app window stays put. A plain
    same-window link would navigate the app itself to Gmail and end the
    session.
    """
    import urllib.parse

    # Two different payloads, because the two channels have different limits.
    # The clipboard bundle is the whole record; the email carries a curated
    # extract that fits in a URL, plus a marker inviting the paste that turns
    # it into the whole record. Fitting is not assumed - the body is rebuilt
    # with fewer health lines until the finished URL is under the limit, so a
    # long environment line or a burst of unclean exits can never silently
    # produce a truncated or rejected link.
    bundle = build_app_error_bundle(app_errors)

    def _url_for(body: str) -> str:
        return (f"{_GMAIL_COMPOSE}"
                f"&to={urllib.parse.quote_plus(DEVELOPER_EMAIL)}"
                f"&su={urllib.parse.quote_plus('Canvas Downloader - application error')}"
                f"&body={urllib.parse.quote_plus(body)}")

    # Health lines go first, then errors: an unclean-exit line is cheap and
    # highly diagnostic, while the tenth copy of the same stack trace is
    # neither. Measured before adding the error cap: 12 maxed-out messages
    # produced 4,020 characters against the 1,900 limit, and trimming health
    # alone could not reach it.
    url = body = ""
    for _health, _errs in ((12, None), (8, None), (5, None), (3, None),
                           (3, 6), (2, 3), (0, 2), (0, 1)):
        body = (build_app_error_report(app_errors, max_health_lines=_health,
                                       max_errors=_errs)
                + f"\n\n{_PASTE_MARKER}\n")
        url = _url_for(body)
        if len(url) <= _EMAIL_URL_LIMIT:
            break
    else:
        # Even one error can be too long on its own. Cut the BODY rather than
        # ship a URL the OS may truncate at an arbitrary byte or refuse
        # outright - the whole record is on the clipboard either way.
        head = build_app_error_report(app_errors, max_health_lines=0,
                                      max_errors=1)
        while head and len(_url_for(head + f"\n\n{_PASTE_MARKER}\n")) > _EMAIL_URL_LIMIT:
            head = head[:-200]
        body = (head or "Canvas Downloader - application error") + \
            f"\n... (truncated)\n\n{_PASTE_MARKER}\n"
        url = _url_for(body)
    return (
        '<div class="app-err-actions">'
        f'<a class="app-err-report-btn" href="{esc(url)}" target="_blank" '
        f'rel="noopener noreferrer">{_REPORT_MAIL_SVG}'
        '<span>Report this to the developer</span></a>'
        # A span, not a <button>: Streamlit sanitises raw HTML and a span with
        # role/tabindex is certain to survive, where a <button> is not. The
        # bridge below binds the behaviour.
        '<span class="app-err-copy-btn" role="button" tabindex="0" '
        'title="Copy the full report - the errors, this session\'s health log, '
        'and the app\'s recent activity">'
        f'{_REPORT_COPY_SVG}</span>'
        # The payload lives in the DOM rather than in a data- attribute so the
        # bridge never depends on an attribute surviving sanitisation, and so a
        # multi-line report needs no escaping games. It is the FULL bundle:
        # both the copy button and the report link read it, the latter so one
        # paste in the compose window upgrades the curated extract to the whole
        # record.
        f'<span class="app-err-report-src">{esc(bundle)}</span>'
        '</div>'
        '<div class="app-err-actions-note">Opens Gmail with the details filled '
        'in, and copies the full log so you can paste it in. Not using Gmail? '
        'Use the copy button and email it to '
        f'<b>{_unlinkable_email(DEVELOPER_EMAIL)}</b>.</div>'
    )


def _unlinkable_email(address: str) -> str:
    """Render an email address as plain text Streamlit's markdown CANNOT
    autolink into a ``mailto:`` anchor.

    Measured: ``st.markdown(unsafe_allow_html=True)`` still runs the string
    through remark-gfm's autolink pass even though it is HTML, and it
    autolinks a bare address INSIDE an explicit ``<b>`` tag - so this line
    rendered as a live, blue, underlined ``mailto:`` link with no anchor tag
    anywhere in the source, defeating the entire point of the fallback (a
    plain address for the person the Gmail button doesn't work for).

    An HTML entity for the `@` does NOT work - measured - because the parser
    decodes entities to their literal character in the text AST before the
    autolink scanner runs, so `&#64;` and `@` are indistinguishable to it by
    the time it looks.

    What DOES work is breaking node adjacency rather than character identity:
    an empty ``<wbr>`` (word-break opportunity - void, zero visual/layout
    effect, and survives Streamlit's sanitizer where a `<span>` also would)
    splits the source into two separate text runs at the point remark builds
    its AST, before the autolink pass ever sees one contiguous
    `word@word.word` shape to match. Verified in the running app: no anchor in
    the rendered DOM, and the visible text is unchanged pixel-for-pixel.
    """
    esc_addr = esc(address)
    at = esc_addr.index('@')
    return esc_addr[:at] + '<wbr>' + esc_addr[at:]


def inject_app_error_copy_bridge() -> None:
    """Client-side clipboard for the copy button. No Streamlit round-trip.

    Re-binds on EVERY injection rather than guarding with a one-time flag:
    ``components.html`` builds a fresh iframe per rerun and destroys the
    previous one, so a listener attached from a dead realm silently stops
    firing (see the JS-bridge rules in CLAUDE.md). The handler ref is stashed
    on ``window.parent`` so it survives to be removed next time.

    Deliberately the SAFE class of bridge: it reads the DOM and writes the
    clipboard, and never tries to drive a Streamlit widget - the mechanism this
    repo has already removed once for being unreliable.

    It binds BOTH controls. The report link also copies, so the paste marker in
    the email body has something to paste: the URL can only carry a curated
    extract, and one Ctrl+V upgrades that to the full log. Crucially it does
    NOT preventDefault for the link - the navigation is the whole point, and
    the clipboard write is fire-and-forget alongside it.
    """
    import streamlit.components.v1 as _components
    _components.html(
        """<script>
(function () {
  var win = window.parent, doc = win.document;
  var reg = win._cdErrCopy || (win._cdErrCopy = {});
  try { doc.removeEventListener('click', reg.handler, true); } catch (e) {}

  reg.handler = function (ev) {
    if (!ev.target || !ev.target.closest) return;
    var btn = ev.target.closest('.app-err-copy-btn');
    var link = btn ? null : ev.target.closest('.app-err-report-btn');
    var el = btn || link;
    if (!el) return;
    // The copy button has no other job, so swallow its click. The link's
    // click MUST be left alone: cancelling it would stop pywebview handing
    // the URL to the system browser, i.e. the report would never open.
    if (btn) { ev.preventDefault(); ev.stopPropagation(); }

    var host = el.closest('.app-err-actions') || el.parentElement;
    var src = host && host.querySelector('.app-err-report-src');
    var text = src ? src.textContent : '';
    if (!text) return;

    var flag = function (cls) {
      if (!btn) return;                 // no confirmation state on the link
      btn.classList.remove('copied', 'failed');
      btn.classList.add(cls);
      win.clearTimeout(reg.timer);
      reg.timer = win.setTimeout(function () {
        btn.classList.remove('copied', 'failed');
      }, 2200);
    };
    var done = function () { flag('copied'); };

    // The async Clipboard API rejects with NotAllowedError when the document
    // is not focused - which is the normal state after the report link has
    // just opened Gmail in the system browser and the user has clicked back.
    // Asking for focus first costs nothing and removes that whole class of
    // failure.
    try { win.focus(); } catch (e) {}

    // The PARENT's clipboard object: the click's user activation belongs to
    // the parent document, not to this iframe's realm.
    try {
      win.navigator.clipboard.writeText(text).then(done, fallback);
    } catch (e) { fallback(); }

    function fallback() {
      // execCommand has different requirements from the async API (a live
      // selection and a user gesture, but no permission or focus check), so it
      // succeeds in cases the API refuses. Deprecated, universally supported,
      // and the only second chance available.
      try {
        var ta = doc.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        doc.body.appendChild(ta);
        ta.select();
        var ok = doc.execCommand('copy');
        doc.body.removeChild(ta);
        // A SILENT failure is the worst outcome: the user clicks, nothing
        // visibly happens, and they cannot tell a broken button from one that
        // worked. Both paths now end in a visible state.
        flag(ok ? 'copied' : 'failed');
      } catch (e2) { flag('failed'); }
    }
  };
  doc.addEventListener('click', reg.handler, true);
})();
</script>""",
        height=0,
    )

# mailto: URLs are handed to the OS as a command line, and both Windows and
# macOS truncate long ones (and some clients silently drop the whole body).
# 1,600 characters is comfortably inside every limit measured; anything longer
# is cut with a pointer to the full log, which the report names anyway.
_MAILTO_BODY_LIMIT = 1600


def _safe_mtime(path: str) -> float:
    """Modification time, or 0 for anything unreadable.

    Only used to ORDER debug logs, so a missing file must sort last rather than
    take the report down with it.
    """
    try:
        return os.path.getmtime(path)
    except Exception:                                   # noqa: BLE001
        return 0.0


def _read_text_tail(path: str, max_bytes: int) -> str:
    """Last ``max_bytes`` of a text file, trimmed to a line boundary.

    Seeks rather than reads the whole file: ``debug_log.txt`` rotates at 5 MB
    and this runs while a completion screen is painting.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            raw = fh.read()
        text = raw.decode("utf-8", errors="replace")
        if size > max_bytes:
            # The seek almost certainly landed mid-line.
            text = text.split("\n", 1)[-1]
        return text.strip("\n")
    except Exception:                                   # noqa: BLE001
        return ""


# The lines in health.log that are worth their bytes in a length-capped email.
# `core/health_log.py` calls the unclean-exit line "the single highest-value
# signal", and the failure tallies are what turn a phase into a diagnosis.
_HEALTH_SIGNALS = (
    "DID NOT EXIT CLEANLY",
    "failures=",
    "reaped",
)

# The opposite: lines that say only "the app opened and closed normally". One
# of each anchors the session; more of them is filler.
_ROUTINE_HEALTH = (
    "SESSION START",
    "SESSION END (clean)",
)


def _curated_health_lines(raw: str, max_lines: int = 12) -> list[str]:
    """The most diagnosable ``max_lines`` of a health log, in file order.

    A plain tail is the obvious thing and it is wrong: a user who has opened
    the app forty times has a log that is almost entirely SESSION START/END
    pairs, and a tail of those pushes the unclean-exit line - the whole reason
    `core/health_log.py` exists, and what it calls "the single highest-value
    signal" - clean out of the window.

    So lines are taken by TIER, newest first within each:

      1. every unclean-exit / failures= / reaped line,
      2. the last SESSION START (anchors when this run began),
      3. the last SESSION END (the previous run's peak memory - a baseline to
         compare the crash against),
      4. anything else, only if budget is left.

    Verified against generated samples before shipping: on a 120-line log of
    routine start/stop pairs with one unclean exit at the very end, a tail
    would have shown twelve clean sessions and missed the crash entirely.

    Survivors are re-sorted chronologically, because an out-of-order log is
    much harder to reason about than a short one, and the count of what was
    dropped is reported by the caller.
    """
    lines = [ln for ln in (raw or "").splitlines() if ln.strip()]
    if not lines:
        return []
    idx = range(len(lines) - 1, -1, -1)
    picked: set[int] = set()

    def take(pred, limit=None):
        for i in idx:
            if len(picked) >= max_lines:
                return
            if i in picked or not pred(lines[i]):
                continue
            picked.add(i)
            if limit is not None:
                limit -= 1
                if limit <= 0:
                    return

    take(lambda ln: any(s in ln for s in _HEALTH_SIGNALS))
    take(lambda ln: "SESSION START" in ln, limit=1)
    take(lambda ln: "SESSION END" in ln, limit=1)
    # Anything that is NOT a routine start/stop - unknown or future line types,
    # a non-clean SESSION END reason - rather than a plain recency fill.
    #
    # A generic "fill the remaining budget with the newest lines" was tried and
    # measured worse: on the 120-line routine-history sample it spent seven of
    # nine slots on identical "SESSION END (clean) uptime=1200s" lines and left
    # the one crash line sitting at the bottom of them. Noise does not become
    # informative by being recent, and the complete log is on the clipboard
    # anyway - the email's job is signal.
    take(lambda ln: not any(r in ln for r in _ROUTINE_HEALTH), limit=4)
    return [lines[i] for i in sorted(picked)]


def _error_lines(app_errors: list, max_errors: int | None = None) -> list[str]:
    """The errors themselves. ``max_errors`` caps how many are spelled out.

    The cap exists because the errors are the one part of the email whose size
    the user controls: measured, twelve maxed-out 220-character messages
    produced a 4,020-character URL against a 1,900 limit, and no amount of
    trimming HEALTH lines can rescue that. Distinct error TYPES are what
    identify a bug, so the surplus is reported as a count rather than dropped
    silently - and the full list is always in the clipboard bundle.
    """
    total = len(app_errors)
    shown = app_errors if max_errors is None else app_errors[:max_errors]
    out = [f"{total} application error{'' if total == 1 else 's'}:"]
    for i, err in enumerate(shown, 1):
        _type = getattr(err, 'error_type', '') or 'Application Error'
        _course = getattr(err, 'course_name', '') or ''
        _msg = getattr(err, 'message', '') or str(err)
        # "#1", NOT "1." - Gmail's compose box is a rich-text editor and
        # auto-formats a line beginning "1. " into an ordered LIST, which
        # discards the literal marker and re-indents the block. Observed in a
        # real report: the pasted bundle came through with the numbers gone
        # entirely, so with several errors there was no way to tell which
        # message belonged to which. "#" is not a list marker in any editor.
        out.append(f"  #{i} [{_type}]{f' {_course}' if _course else ''}")
        out.append(f"     {_msg}")
    if total > len(shown):
        out.append(f"  ... and {total - len(shown)} more "
                   f"(full list on clipboard)")
    return out


def _environment_lines() -> list[str]:
    """App + OS dimensions, from the same source the health log uses.

    `core.health_log.environment()` already assembles exactly what a crash
    report needs to slice by - OS BUILD (not just "Windows 11"), arch, RAM,
    CPU count, frozen/packaged, and the Rosetta flag that explains an entire
    class of macOS failure. Re-deriving a thinner version here from
    `platform` - which is what this did - threw away the build number and the
    packaging mode, the two dimensions the Store report groups by.
    """
    import datetime as _dt
    try:
        from core.health_log import environment
        env = environment() or {}
    except Exception:                                   # noqa: BLE001
        env = {}
    out = []
    if env:
        out.append(f"Canvas Downloader {env.get('app', '?')}"
                   f"{'  frozen' if env.get('frozen') else ''}"
                   f"{'  packaged' if env.get('packaged') else ''}"
                   f"{'  ROSETTA' if env.get('rosetta') else ''}")
        # `build` is only worth its own field when it ADDS something. On Windows
        # os="Windows 11" and build="10.0.26100" - the build is the dimension
        # crash reports group by. On macOS `environment()` derives both from
        # mac_ver(), so os="macOS 14.6" and build="14.6" and printing both gives
        # "macOS 14.6  build 14.6".
        _os, _build = str(env.get('os', '?')), str(env.get('build', '?'))
        _os_line = _os if _build in _os else f"{_os}  build {_build}"
        out.append(f"{_os_line}  {env.get('arch', '?')}  "
                   f"{env.get('ram_gb', '?')} GB RAM  {env.get('cpus', '?')} CPU")
        out.append(f"Python {env.get('python', '?')}")
    else:
        import platform
        out.append(f"{platform.system()} {platform.release()} "
                   f"({platform.machine()})")
        out.append(f"Python {platform.python_version()}")
    out.append(f"Reported {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    return out


def build_app_error_report(app_errors: list, *, max_health_lines: int = 12,
                           max_errors: int | None = None) -> str:
    """The CURATED report, sized for an email body.

    Readable rather than machine-parseable: the user is about to look at this
    in a compose window, and a wall of JSON reads as something being taken
    from them. Everything in it is app-generated - versions, platform, error
    type and message, and health-log lines that carry no course names, file
    names or paths outside the app's own config dir.

    It no longer ends with the PATH of the health log. A path is worthless the
    moment the mail leaves the machine; the lines themselves are the point.
    """
    lines = _environment_lines()
    lines.append("")
    lines.extend(_error_lines(app_errors, max_errors))
    try:
        from core.health_log import health_log_path
        raw = _read_text_tail(health_log_path(), 64 * 1024)
        total = len([ln for ln in raw.splitlines() if ln.strip()])
        health = _curated_health_lines(raw, max_health_lines)
        if health:
            lines.append("")
            lines.append("Session health:")
            lines.extend("  " + ln for ln in health)
            # Say what was left out. Without this the extract looks like the
            # WHOLE log, and a reader has no way to tell a quiet history from
            # a heavily-trimmed one - which changes how much the absence of a
            # crash line actually means.
            if total > len(health):
                lines.append(f"  ... {total - len(health)} earlier line"
                             f"{'' if total - len(health) == 1 else 's'} omitted "
                             f"(full log below / on clipboard)")
    except Exception:                                   # noqa: BLE001
        pass
    return "\n".join(lines)


def build_app_error_bundle(app_errors: list) -> str:
    """The FULL report, for the clipboard - which has no length limit.

    Same head as the email so the two are recognisably one document, then
    everything the email had to leave out: the complete health log, and the
    tail of every debug log this session actually wrote to.

    The debug log is included only when the user turned debug mode on. Its
    contents are already redacted at write time (``canvas_debug._sanitize``
    strips Bearer tokens and signed-URL verifiers), but it does carry course
    and file names - which is exactly why it is opt-in and why it is never in
    the email, only in something the user copies deliberately.
    """
    # A banner, because this text is usually PASTED under the email body -
    # which carries its own copy of the environment header. Without a marker
    # the reader meets the same four lines twice with nothing to say why, and
    # cannot tell where the summary ends and the full record begins. The header
    # is still repeated on purpose: the copy button is also used on its own,
    # where the bundle is the entire message.
    lines = ["===== CANVAS DOWNLOADER - FULL DIAGNOSTIC REPORT ====="]
    lines.extend(_environment_lines())
    lines.append("")
    lines.extend(_error_lines(app_errors))

    try:
        from core.health_log import health_log_path
        raw = _read_text_tail(health_log_path(), 256 * 1024)
        if raw:
            lines.append("")
            lines.append("=== health.log ===")
            lines.append(raw)
    except Exception:                                   # noqa: BLE001
        pass

    try:
        from core.canvas_debug import session_debug_files
        # Newest first: with several courses the budget runs out, and the log of
        # the course that failed LAST is the one worth having.
        paths = sorted(session_debug_files(),
                       key=lambda p: _safe_mtime(p), reverse=True)
        used = sum(len(ln) for ln in lines)
        for path in paths:
            if used >= _BUNDLE_MAX_CHARS:
                lines.append("")
                lines.append(f"... {len(paths) - paths.index(path)} further debug "
                             f"log(s) omitted to keep this report a sane size")
                break
            tail = _read_text_tail(path, _DEBUG_TAIL_BYTES)
            if not tail:
                continue
            lines.append("")
            lines.append(f"=== {os.path.basename(os.path.dirname(path))}"
                         f"/{os.path.basename(path)} (tail) ===")
            lines.append(tail)
            used += len(tail)
    except Exception:                                   # noqa: BLE001
        pass

    # The narration for the DEFAULT case: debug logging is off, so none of the
    # above exists. Without this an app error from a normal user arrived with a
    # message and no story around it. In-memory only, never written to disk -
    # see core.canvas_debug.breadcrumbs.
    try:
        from core.canvas_debug import breadcrumbs, session_debug_files
        crumbs = breadcrumbs()
        # Redundant when a real debug log is already attached above; that file
        # is the same narration, longer and on disk.
        if crumbs and not session_debug_files():
            lines.append("")
            lines.append("=== recent activity (this session, from memory) ===")
            lines.append(crumbs)
    except Exception:                                   # noqa: BLE001
        pass

    # One hard ceiling at the end, so no combination of inputs can exceed it.
    # The per-file budget above is a fair share, not a guarantee: the health log
    # alone can be 256 KB. Truncating the TAIL keeps the head - environment and
    # the errors - which is the part a report is useless without.
    out = "\n".join(lines)
    if len(out) > _BUNDLE_MAX_CHARS:
        out = (out[:_BUNDLE_MAX_CHARS]
               + f"\n\n... (report truncated at {_BUNDLE_MAX_CHARS // 1024} KB)")
    return out


def render_pp_warning(pp_failure_count: int):
    """Say what a failed conversion actually cost the user, and what to do.

    The old copy was "N files failed during post-processing
    (conversion/extraction)" over "Enable error logging in settings to capture
    details" - three problems at once. "Post-processing" is our word, not a
    user's. It left the worst possible question open, which is whether the FILE
    is gone. And its only suggestion was to switch on a log and do the whole
    thing again, which tells them nothing they can act on today.

    So: name the loss precisely (the converted copy, never the original), then
    give the two causes that account for almost all of these - Office not
    available, or the file open somewhere - and one concrete next step.
    """
    if pp_failure_count <= 0:
        return
    from ui.amber_notice import render_amber_notice
    word = "file" if pp_failure_count == 1 else "files"
    it = "it" if pp_failure_count == 1 else "them"
    detail = (
        f"The original {word} downloaded fine and {'is' if pp_failure_count == 1 else 'are'} "
        f"in your course folder - only the converted {'copy' if pp_failure_count == 1 else 'copies'} "
        f"could not be made. This is usually Microsoft Office not being installed "
        f"or not signed in, or the file being open in another program. Close any "
        f"open Office windows and run this course again to retry just {it}."
    )
    # Only mention the log when it exists. Error logging is OFF by default, so
    # pointing at download_errors.txt was, for most users, naming a file that
    # is not there.
    if st.session_state.get('error_log_enabled', False):
        detail += " Details are in download_errors.txt in each course folder."
    render_amber_notice(
        f"{pp_failure_count} {word} could not be converted.",
        detail=detail,
        margin="0",  # the card's flex gap (16px) is the ONE rhythm; a margin here adds to it
    )


# Separator dot for inline heading scopes. Its own element with equal margins,
# so the spacing either side of it is one number rather than a mix of a literal
# space and a flex gap.
_DOT = ("<span style='display:inline-block;margin:0 7px;opacity:0.5;"
        f"color:{theme.TEXT_PRIMARY};'>&middot;</span>")


def render_panopto_summary(summary: dict | None) -> None:
    """Render a Panopto results card on the Download / Sync completion screens.

    ``summary`` aggregates the terminal Panopto phase:
        {found, downloaded, transcribed, skipped, failed, courses}
    No-ops when summary is missing or nothing was found (feature off / no videos).
    """
    if not summary:
        return
    found = int(summary.get('found', 0) or 0)
    # Both modes show only what this run actually DID (Downloaded / Transcribed,
    # plus Errors if any). We deliberately do NOT surface a "Skipped" / "already
    # present" stat: a big "24 skipped" reads as "24 missing from my course" and
    # alarms users who in fact have the full course on disk. Sync mode adds a
    # quiet "N already up to date" note in the subtitle instead.
    is_sync = 'uptodate' in summary
    uptodate = int(summary.get('uptodate', 0) or 0)
    selected = int(summary.get('selected', found) or 0)

    # Only surface the card when this run actually DID something with Panopto
    # (downloaded / transcribed, or hit an error). A run that produced none of
    # those has nothing to put in it, and the card would read "0" - which lands
    # as a failure report.
    #
    # This guard used to exist for SYNC mode only. In download mode the test was
    # just `found <= 0`, so a run where every recording was skipped by the
    # skip-large-files limit rendered "36 found across 1 course / 0 DOWNLOADED"
    # - directly beside the line that already explains it ("61 files skipped
    # because they exceeded the 5 MB limit", a count which INCLUDES those 36
    # recordings). Two panels describing the same event, one of them as a
    # success metric reading zero. Measured on course 43660 with a 5 MB limit:
    # 25 over-limit Canvas files + 36 over-limit recordings = the 61 reported.
    _did_work = (int(summary.get('downloaded', 0) or 0)
                 or int(summary.get('transcribed', 0) or 0)
                 or int(summary.get('shortcuts', 0) or 0)
                 or int(summary.get('failed', 0) or 0)
                 or (selected if is_sync else 0))
    if not _did_work:
        return
    if not is_sync and found <= 0:
        return

    # Reuse the completion stat-card styling so this section matches the top
    # metric boxes exactly (neutral white/grey - no per-metric "skittles" colour,
    # no blue card that clashes with the amber/green/red completion backgrounds).
    from styles import inject_css
    inject_css('completion.css')

    from shared import theme as _theme
    downloaded = int(summary.get('downloaded', 0) or 0)
    transcribed = int(summary.get('transcribed', 0) or 0)
    shortcuts = int(summary.get('shortcuts', 0) or 0)
    failed = int(summary.get('failed', 0) or 0)
    courses = int(summary.get('courses', 0) or 0)

    _dl_icon = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        "stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' "
        "style='width:18px;height:18px;flex-shrink:0;'>"
        "<path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/>"
        "<polyline points='7 10 12 15 17 10'/><line x1='12' y1='15' x2='12' y2='3'/></svg>"
    )
    _tx_icon = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        "stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' "
        "style='width:18px;height:18px;flex-shrink:0;'>"
        "<path d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/>"
        "<polyline points='14 2 14 8 20 8'/><line x1='16' y1='13' x2='8' y2='13'/>"
        "<line x1='16' y1='17' x2='8' y2='17'/><line x1='10' y1='9' x2='8' y2='9'/></svg>"
    )
    _link_icon = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        "stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' "
        "style='width:18px;height:18px;flex-shrink:0;'>"
        "<path d='M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71'/>"
        "<path d='M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71'/></svg>"
    )
    _skip_icon = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        "stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' "
        "style='width:18px;height:18px;flex-shrink:0;'>"
        "<circle cx='12' cy='12' r='10'/><line x1='8' y1='12' x2='16' y2='12'/></svg>"
    )

    def _stat(icon: str, value: int, label: str, error: bool = False) -> str:
        cls = "stat-card stat-error" if error else "stat-card"
        return (
            f"<div class='{cls}'>"
            f"<div class='stat-icon-wrapper'>{icon}</div>"
            "<div class='stat-info'>"
            f"<div class='stat-value'>{value}</div>"
            f"<div class='stat-label'>{esc(label)}</div>"
            "</div></div>"
        )

    # Show only what this run produced; never a "Skipped"/"already present" stat
    # (see the note above). Errors appear only when something actually failed.
    # "Downloaded" follows the same rule as "Transcribed" below: show it when
    # this run either downloaded something or was CONFIGURED to. A Shortcut-only
    # run is the case that made this necessary - it does real work and finishes
    # clean, so the card renders, and an unconditional box reported "0
    # Downloaded" beside "12 Links". `want_media` is absent from older summaries
    # and from the "already up to date" one, so the fallback keeps the box.
    _want_media = summary.get('want_media', True)
    cards = []
    if downloaded or _want_media:
        cards.append(_stat(_dl_icon, downloaded, "Downloaded"))
    # "Transcribed" appears only when transcription was actually in play: either
    # the run's config requested a transcript (want_transcription), or we in fact
    # produced one (transcribed > 0). A course with transcription switched off
    # must NOT show a "0 Transcribed" box - users read that as a bug/failure when
    # nothing was ever meant to be transcribed. (want_transcription is absent on
    # the manual "already up to date" sync summary, but that card is hidden above.)
    _want_tx = bool(summary.get('want_transcription'))
    if transcribed or _want_tx:
        cards.append(_stat(_tx_icon, transcribed, "Transcribed"))
    # "Links" only when links were actually written. Unlike Transcribed there is
    # no want_* companion to show a deliberate zero against: a shortcut that was
    # wanted and not produced is a failure, and failures have their own box.
    if shortcuts:
        cards.append(_stat(_link_icon, shortcuts, "Links"))
    if failed:
        cards.append(_stat(_skip_icon, failed, "Errors", error=True))

    # HTML assembled from app-controlled values only (ints, theme tokens, self-
    # built SVG, esc'd labels), so the unsafe_allow_html call carries no raw input.
    if is_sync:
        # "processed" = recordings acted on this run; "already up to date" sits
        # right beside it so the whole status reads on one line.
        _parts = []
        if selected:
            _parts.append(f"{selected} processed")
        if uptodate:
            _parts.append(f"{uptodate} already up to date")
        _scope = _DOT.join(_parts)
    else:
        _scope = f"{found} found"
        if courses:
            _scope += f" across {courses} course{'s' if courses != 1 else ''}"
    # The separator dot carries its own symmetric margins and the row's flex
    # `gap` is zero, so the space on each side of it is the same number. It used
    # to be a literal " · " inside a `gap: 6px` row, which meant 6px + a space on
    # the left and only a space on the right - a lopsided dot at the exact
    # centre of the heading, where it is the first thing the eye lands on.
    _hdr = (
        f"<div style='display:flex;align-items:baseline;gap:0;margin:0 0 10px 0;'>"
        f"<span style='color:{_theme.TEXT_PRIMARY};font-weight:700;font-size:1.02rem;'>Panopto Recordings</span>"
        + (f"{_DOT}<span style='color:{_theme.TEXT_PRIMARY};font-size:0.85rem;'>{_scope}</span>"
           if _scope else "")
        + "</div>"
    )
    _body = f"<div class='completion-stats-grid'>{''.join(cards)}</div>"

    # Card styling lives in completion.css (injected above). NEVER bundle a
    # <style> tag into this markdown: completion.css collapses style-carrying
    # markdown wrappers, and the blanket form of that rule blanked this whole
    # card on the completion screens (2026-07-10).
    col1, _ = st.columns([1, 1])
    with col1:
        with st.container(key='panopto_summary_dashboard'):
            st.markdown(_hdr + _body, unsafe_allow_html=True)


def render_config_summary_badges(settings: dict, show_path: bool = True) -> str:
    """Render a rich HTML preview of active settings using color-coded badges."""
    # Build Blue Core Badges
    _mode_disp = "With Subfolders" if settings.get('download_mode') == 'modules' else "All in One Folder"
    _filter_disp = "All Files" if settings.get('file_filter') == 'all' else "Slides & PDFs"
    
    c_core = "#3fd9ff"
    core_html = f"""
<div style='display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start;'>
    <div style='width: 100%; font-size:0.8rem; color:#ffffff; font-weight:600; text-transform:uppercase; margin-bottom:2px;'>Core Settings</div>
    <div style='width: 100%;'><span style='display:inline-flex; align-items:center; padding:3px 10px; background-color:rgba(63, 217, 255, 0.05); color:{c_core}; border-radius:4px; font-size:0.78rem; border:1px solid rgba(63, 217, 255, 0.7);'>{SVG_FOLDER_YELLOW_SMALL} {_mode_disp}</span></div>
    <span style='display:inline-flex; align-items:center; padding:3px 10px; background-color:rgba(63, 217, 255, 0.15); color:{c_core}; border-radius:12px; font-size:0.78rem; border:1px solid rgba(63, 217, 255, 0.3);'>{_filter_disp}</span>
</div>
"""
    
    # Build Green Canvas Content Badges
    c_canvas = "#2DFFA0"
    _sec_mode_disp = "Separate Folders" if settings.get('dl_isolate_secondary') else "Matching Core Settings"
    sec_org_badge = f"<span style='display:inline-flex; align-items:center; padding:3px 10px; background-color:rgba(45, 255, 160, 0.05); color:{c_canvas}; border-radius:4px; font-size:0.78rem; border:1px solid rgba(45, 255, 160, 0.7);'>{SVG_FOLDER_YELLOW_SMALL} {_sec_mode_disp}</span>"
    
    _sec_on = [k.replace('dl_', '').replace('_', ' ').title() for k in PresetManager.SECONDARY_CONTENT_KEYS if settings.get(k)]
    if _sec_on:
        sec_badges_list = "".join([f"<span style='display:inline-flex; align-items:center; padding:3px 10px; background-color:rgba(45, 255, 160, 0.15); color:{c_canvas}; border-radius:12px; font-size:0.78rem; border:1px solid rgba(45, 255, 160, 0.3);'>✓ {x}</span>" for x in _sec_on])
        sec_badges = f"<div style='width: 100%;'>{sec_org_badge}</div>{sec_badges_list}"
    else:
        sec_badges = "<div style='width: 100%;'><span style='display:inline-flex; align-items:center; padding:3px 10px; background-color:rgba(255, 255, 255, 0.05); color:#94a3b8; border-radius:12px; font-size:0.78rem; border:1px solid #475569;'>None selected</span></div>"
        
    content_html = f"""
<div style='display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start;'>
    <div style='width: 100%; font-size:0.8rem; color:#ffffff; font-weight:600; text-transform:uppercase; margin-bottom:2px;'>Canvas Content</div>
    {sec_badges}
</div>
"""
    
    # Build Orange AI Optimization Badges
    c_ai = "#FF9838"
    conv_mapping = {
        'convert_zip': 'Unpack Archives (.zip)',
        'convert_pptx': 'PPTX ➡ PDF',
        'convert_word': 'Legacy Word ➡ PDF',
        'convert_excel': 'Excel ➡ PDF & AI Data',
        # Markdown, NOT PDF: the pipeline calls convert_html_to_md and writes .md
        # (converters/md.py; shared/helpers.py's effective-extension map agrees,
        # as does the sync post-processing label "HTML->Markdown").
        'convert_html': 'Canvas Pages ➡ Markdown',
        'convert_code': 'Code ➡ .TXT',
        'convert_urls': 'Links ➡ TXT',
        'convert_video': 'Video ➡ MP3'
    }
    _conv_on = [conv_mapping.get(k, k) for k in PresetManager.NOTEBOOK_SUB_KEYS if settings.get(k)]
    if _conv_on:
        conv_badges = "".join([f"<span style='display:inline-flex; align-items:center; padding:3px 10px; background-color:rgba(255, 152, 56, 0.15); color:{c_ai}; border-radius:12px; font-size:0.78rem; border:1px solid rgba(255, 152, 56, 0.3);'>⚡ {x}</span>" for x in _conv_on])
    else:
        conv_badges = "<span style='display:inline-flex; align-items:center; padding:3px 10px; background-color:rgba(255, 255, 255, 0.05); color:#94a3b8; border-radius:12px; font-size:0.78rem; border:1px solid #475569;'>None selected</span>"
        
    conv_html = f"""
<div style='display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start;'>
    <div style='width: 100%; font-size:0.8rem; color:#ffffff; font-weight:600; text-transform:uppercase; margin-bottom:2px;'>AI Optimization & Conversions</div>
    {conv_badges}
</div>
"""

    # Build Purple Panopto Recordings Badges.
    # Accepts the UI/session key names (pan_out_*, pan_layout); callers holding a
    # stored Panopto contract should map it first via
    # panopto.settings.contract_to_ui_keys so this stays a single renderer.
    c_pan = "#b89dfe"
    _pan_outputs = [
        (settings.get('pan_out_url'), 'Shortcut'),
        (settings.get('pan_out_mp4'), 'Video'),
        (settings.get('pan_out_mp3'), 'Audio'),
        (settings.get('pan_out_txt'), 'Transcript'),
        (settings.get('pan_out_srt'), 'Subtitles'),
    ]
    _pan_on = [label for active, label in _pan_outputs if active]
    if _pan_on:
        _pan_layout_disp = "Separate Folders" if settings.get('pan_layout') == 'separate' else "Matching Course Folder"
        pan_org_badge = f"<span style='display:inline-flex; align-items:center; padding:3px 10px; background-color:rgba(184, 157, 254, 0.05); color:{c_pan}; border-radius:4px; font-size:0.78rem; border:1px solid rgba(184, 157, 254, 0.7);'>{SVG_FOLDER_YELLOW_SMALL} {_pan_layout_disp}</span>"
        pan_badges_list = "".join([f"<span style='display:inline-flex; align-items:center; padding:3px 10px; background-color:rgba(184, 157, 254, 0.15); color:{c_pan}; border-radius:12px; font-size:0.78rem; border:1px solid rgba(184, 157, 254, 0.3);'>✓ {x}</span>" for x in _pan_on])
        pan_badges = f"<div style='width: 100%;'>{pan_org_badge}</div>{pan_badges_list}"
    else:
        pan_badges = "<div style='width: 100%;'><span style='display:inline-flex; align-items:center; padding:3px 10px; background-color:rgba(255, 255, 255, 0.05); color:#94a3b8; border-radius:12px; font-size:0.78rem; border:1px solid #475569;'>None selected</span></div>"

    pan_html = f"""
<div style='display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start;'>
    <div style='width: 100%; font-size:0.8rem; color:#ffffff; font-weight:600; text-transform:uppercase; margin-bottom:2px;'>Panopto Recordings</div>
    {pan_badges}
</div>
"""

    path_html = ""
    if show_path and settings.get('download_path'):
        path_html = f"""
<div style='margin-bottom:4px;'>
    <div style='font-size:0.8rem; color:#ffffff; font-weight:600; text-transform:uppercase; margin-bottom:4px;'>Saved Path</div>
    <div style='background-color:rgba(0,0,0,0.3); color:#cbd5e1; padding:6px 10px; border-radius:6px; font-size:0.78rem; font-family:monospace; border:none; word-break: break-all; margin-bottom:10px;'>{esc(settings.get('download_path'))}</div>
</div>
"""
    grid_container = f"""
<div style="display: grid; grid-template-columns: 0.8fr 1.1fr 1.1fr 1.0fr; gap: 15px; margin-bottom: 5px;">
    {core_html}
    {content_html}
    {conv_html}
    {pan_html}
</div>
"""

    return f"{grid_container}{path_html}"


def render_transcription_setup_notice(wants_transcription: bool, *, key: str, context_note: str = "") -> bool:
    """Shared "Panopto transcription isn't set up" warning + one-click setup.

    Renders an amber notice card (with the live, specific reason) and a "Set up
    transcription" button whenever *wants_transcription* is True but the local
    engine/model isn't ready.  The icon, title, detail text, and button are all
    rendered **inside** the card - matching the Custom Download page's layout.

    The button opens the same engine-setup dialog used by Section 4 (sets
    ``_pan_dialog_open`` + full-app rerun); the CALLER's page must host
    ``render_transcription_dialog()`` when that flag is set.

    Readiness is re-checked live via ``panopto.models.transcription_status`` so
    the notice clears the instant a model is installed/activated. Single source
    of this messaging for the sync list and the sync review page.

    Returns True if the warning was rendered.
    """
    if not wants_transcription:
        return False
    from panopto import models as _pmodels
    status = _pmodels.transcription_status()
    if status.get('ready'):
        return False

    _engine_avail = status.get('engine_available', False)
    _any_installed = status.get('any_installed', False)
    _why = ("The local transcription engine isn't available yet."
            if not _engine_avail else
            "A model is installed but not activated yet."
            if _any_installed else
            "No transcription model is installed yet.")

    # CSS for the card container and its embedded button.  Uses amber tones
    # (matching render_amber_notice) and the same structural pattern as the
    # Custom Download page's purple pan_info_card.
    _card_key = f"tx_setup_card_{key}"
    _btn_key = key
    st.html(f"""<style>
    div[class*="st-key-{_card_key}"] {{
        border: 1px solid rgba(234, 179, 8, 0.45) !important;
        border-radius: 10px !important;
        background: rgba(234, 179, 8, 0.08) !important;
        margin-bottom: 0px !important;
        padding: 12px 15px 12px 15px !important;
    }}
    div[class*="st-key-{_card_key}"] div[data-testid="stVerticalBlock"] {{
        padding-bottom: 0 !important;
    }}
    div[class*="st-key-{_card_key}"] div[data-testid="stElementContainer"]:last-child {{
        margin-bottom: 0 !important;
    }}
    div.st-key-{_btn_key} {{
        margin-left: 32px !important;
        margin-top: 6px !important;
        margin-bottom: 18px !important;
    }}
    div.st-key-{_btn_key} button {{
        background: rgba(176,157,254,0.10) !important;
        border: 1px solid rgba(176,157,254,0.35) !important;
        color: #d8caff !important; font-weight: 600 !important;
        font-size: 0.85rem !important;
        border-radius: 8px !important;
        justify-content: center !important;
        align-items: center !important;
        transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
        height: 32px !important; min-height: 32px !important;
        min-width: 220px !important;
        padding: 0 14px !important;
    }}
    div.st-key-{_btn_key} button [data-testid="stMarkdownContainer"] {{
        display: flex !important;
        align-items: center !important;
    }}
    div.st-key-{_btn_key} button p {{
        display: inline-flex !important;
        align-items: center !important;
        gap: 6px !important;
        margin: 0 !important;
    }}
    div.st-key-{_btn_key} button p::before {{
        content: "" !important;
        display: inline-block !important;
        width: 14px !important; height: 14px !important;
        flex-shrink: 0 !important;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='%23d8caff'%3E%3Cpath fill-rule='evenodd' d='M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z' clip-rule='evenodd'/%3E%3C/svg%3E") !important;
        background-size: contain !important;
        background-repeat: no-repeat !important;
        background-position: center !important;
    }}
    div.st-key-{_btn_key} button:hover {{
        background-color: rgba(176,157,254,0.18) !important;
        border-color: #b89dfe !important; color: #ffffff !important;
    }}
    </style>""")

    with st.container(key=_card_key):
        # Amber info-circle SVG icon + title + detail, matching Custom Download layout
        st.markdown(
            "<div style='display:flex; align-items:flex-start; gap:12px;'>"
            "<svg width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='#fbbf24' stroke-width='2' "
            "stroke-linecap='round' stroke-linejoin='round' style='flex-shrink:0; margin-top:1px;'>"
            "<circle cx='12' cy='12' r='10'/><line x1='12' y1='8' x2='12' y2='12'/>"
            "<line x1='12' y1='16' x2='12.01' y2='16'/></svg>"
            "<div style='flex:1;'>"
            "<div style='color:#fde68a; font-weight:600; font-size:0.9rem;'>"
            "Transcripts &amp; Subtitles need a one-time setup</div>"
            f"<div style='color:#d4a017; font-size:0.84rem; margin-top:2px; line-height:1.45;'>"
            f"{('<b>' + esc(context_note) + '</b> ') if context_note else ''}"
            f"{esc(_why)} "
            "Download a transcription model to unlock the <b>Transcript</b> &amp; <b>Subtitles</b> formats. "
            "Video &amp; Audio work without it.</div></div></div>",
            unsafe_allow_html=True,
        )
        if st.button("Set up transcription", key=_btn_key,
                     help="Download and activate a transcription model, then continue."):
            st.session_state['_pan_dialog_open'] = True
            st.rerun(scope="app")

    st.markdown("<div style='margin-bottom:14px;'></div>", unsafe_allow_html=True)
    return True


@st.dialog("📄 Error Log", width="large")
def error_log_dialog(log_paths):
    """Display the contents of download_errors.txt files in a modal dialog.

    Unified dialog used by both the download completion screen (app.py)
    and the sync completion screen (sync/completion.py).
    """
    st.markdown("""
        <style>
            div[data-testid="stDialog"] div.st-key-error_log_scroll_shared {
                height: 55vh !important;
                min-height: 55vh !important;
                max-height: 55vh !important;
                overflow-y: auto !important;
                overflow-x: hidden !important;
            }
        </style>
    """, unsafe_allow_html=True)

    with st.container(border=False, key="error_log_scroll_shared"):
        found_any = False
        for log_path in log_paths:
            if log_path.exists():
                try:
                    content = log_path.read_text(encoding='utf-8').strip()
                    if content:
                        found_any = True
                        # esc() the folder name: it is a course folder, so it
                        # derives from a Canvas course title.
                        st.markdown(f"**{SVG_FOLDER_YELLOW} {esc(log_path.parent.name)}**", unsafe_allow_html=True)
                        st.code(content, language="text")
                except Exception as e:
                    from ui.amber_notice import render_amber_notice
                    render_amber_notice(f"Could not read {log_path}: {e}")

        if not found_any:
            from ui.amber_notice import render_info_notice
            render_info_notice("No error log files found on disk.")

    # NOTE: the app HEALTH record deliberately does NOT live here. This dialog
    # answers "which files failed in the run I just did" - it is operational,
    # user-facing, and only reachable from a completion screen. The health
    # record answers "how has the application itself been behaving across
    # sessions", which is a different concern for a different audience, and the
    # failure it exists to catch (the app dying) is precisely the one where
    # nobody ever reaches a completion screen. It lives in Settings instead.

    if st.button("Close", type="primary", use_container_width=True):
        st.rerun(scope="app")


# ── macOS "make it fully hands-off" nudge (Full Disk Access) ─────────────────
# The one dialog that can still hold up an unattended run is the macOS 15+ App
# Data consent ("access data from other apps") - by Apple design it expires
# when the app quits, so it re-asks once per session when conversions stage
# Office files (see engine.applescript_bridge.arm_app_data_access). Full Disk
# Access exempts the app permanently; these surfaces point exactly there.
# Conversions are CORE to the app's value proposition, so the guidance lives
# everywhere they do:
#   * Settings dialog       - render_fda_settings_card: a PERMANENT status card
#                             (green when granted, blue call-to-action with the
#                             step-by-step guide when not). Never dismissible.
#   * Today page + download - render_fda_nudge: the dismissible blue card /
#     step 2                  subtle re-spawn link. key_prefix namespaces the
#                             widget keys so several surfaces can render in the
#                             same script run.
# The persisted dismissal (today_store.fda_nudge_dismissed) and the session
# spawn flag are deliberately SHARED across the nudge surfaces: closing the
# card anywhere means "stop auto-showing it everywhere"; the subtle link
# remains and re-spawns the card. Nudge CSS lives in styles/global.css
# (prefix-agnostic `_fda_*` selectors) so it is loaded on every page; the
# Settings card is st.html-based (inline styles) like its sibling cards.

# The 4-step grant walkthrough, shared by the nudge card and the Settings
# card so the copy can never drift between surfaces.
_FDA_STEPS_HTML = (
    "<li>Click <b>Open Full Disk Access Settings</b> below.</li>"
    "<li>Toggle on <b>Canvas Downloader</b> in the app list.</li>"
    "<li>Enter your Mac password to confirm and click <b>Modify Settings</b></li>"
    "<li>Choose <b>Quit &amp; Reopen</b> when macOS asks. That's all, "
    "the permission dialog will never show again.</li>"
)

_FDA_TOAST = ("Turn on Canvas Downloader under Full Disk Access, "
              "then choose Quit & Reopen.")


def _fda_gate() -> tuple[bool, bool]:
    """(applies, granted): whether the FDA story applies here at all
    (macOS 15+), and whether Full Disk Access is already granted."""
    import sys
    if sys.platform != "darwin":
        return False, False
    try:
        from engine.applescript_bridge import is_macos_15_plus, has_full_disk_access
        if not is_macos_15_plus():
            return False, False
        return True, bool(has_full_disk_access())
    except Exception:
        return False, False


def fda_nudge_applies() -> bool:
    """True when the FDA nudge slot WOULD render (macOS 15+, FDA not granted).

    Public visibility gate for callers that need to know without rendering -
    e.g. step 2's Card 3 fragment: the nudge slot lives OUTSIDE that fragment,
    so when a converter toggle flips the slot's visibility the fragment
    escalates to a full-page rerun (and only then - Windows / granted
    machines never flash)."""
    _applies, _granted = _fda_gate()
    return _applies and not _granted


def _dismiss_fda_nudge() -> None:
    """on_click for the nudge's close button - the card never auto-shows again."""
    from core.today_store import set_fda_nudge_dismissed
    set_fda_nudge_dismissed(True)
    st.session_state.pop("fda_nudge_card_open", None)


def _spawn_fda_nudge_card() -> None:
    """on_click for the subtle link - re-shows the card for this session."""
    st.session_state["fda_nudge_card_open"] = True


def render_fda_nudge(key_prefix: str, dismissed: bool | None = None) -> None:
    """Render the Full Disk Access nudge slot (card, or its re-spawn link).

    States (only while the gate holds - macOS 15+, FDA not granted):
      * not dismissed          → the full card.
      * dismissed              → a subtle text link; a click re-spawns the card
                                 for this session (on all surfaces).
      * FDA granted / non-Mac  → nothing at all (the gate re-checks every
                                 rerun, so granting FDA mid-session makes the
                                 whole slot vanish on the next interaction).

    *dismissed* saves the caller a config read when it already holds the Today
    config; pass None to have it loaded here. All interactions use on_click
    callbacks, never st.rerun(): a bare st.rerun() is app-scoped and would
    CLOSE a host @st.dialog (Settings), while on_click + the natural rerun
    repaints in place and keeps the dialog open.
    """
    _applies, _granted = _fda_gate()
    if not _applies or _granted:
        return
    from engine.applescript_bridge import open_full_disk_access_settings
    if dismissed is None:
        try:
            from core.today_store import load_today_config
            dismissed = bool(load_today_config()["fda_nudge_dismissed"])
        except Exception:
            dismissed = True  # never nag if the store is unreadable

    if dismissed and not st.session_state.get("fda_nudge_card_open", False):
        # Dismissed: the always-there subtle re-spawn link.
        st.button("Recommended action: Silence the 'Would like to access data from other apps' pop-up forever", key=f"{key_prefix}_link_btn",
                  on_click=_spawn_fda_nudge_card)
        return

    with st.container(key=f"{key_prefix}_nudge_card"):
        # vertical_alignment="top": the close button pins to the card's top-right
        # corner (level with the title) instead of floating mid-card against the
        # multi-line step list. The matching CSS sets align-items: flex-start.
        c_body, c_close = st.columns([0.95, 0.05], vertical_alignment="top")
        with c_body:
            st.markdown(
                f"<div class='fda-nudge-inner'>"
                f"<div class='fda-nudge-title'>How to silence 'Would like to access data from other apps' pop-up</div>"
                f"<div class='fda-nudge-desc'>macOS asks a one-click "
                f"<b>&ldquo;access data from other apps&rdquo;</b> permission every time "
                f"you open the app. The app needs this permission to safely and cleanly convert Office files to your ai-ready formats. This permission is annoying and "
                f"makes features like the 'Todays Files' mode require your input. To hide it for good, grant Canvas Downloader "
                f"<b>Full Disk Access</b> once and it will never appear again:</div>"
                f"<ol class='fda-nudge-steps'>{_FDA_STEPS_HTML}</ol>"  # audit-ignore: static module constant (shared step copy)
                f"</div>",
                unsafe_allow_html=True,
            )
        with c_close:
            # No help= tooltip: it wraps the <button> in a stTooltipHoverTarget,
            # which breaks the fixed 32px sizing CSS (see CLAUDE.md).
            st.button(
                "​", key=f"{key_prefix}_close_btn",
                on_click=_dismiss_fda_nudge,
            )
        if st.button("Open Full Disk Access Settings", key=f"{key_prefix}_open_btn"):
            open_full_disk_access_settings()
            st.toast(_FDA_TOAST)


def render_fda_settings_card() -> None:
    """Permanent Full Disk Access status card for the Settings dialog (macOS).

    Unlike the dismissible nudge, this card is ALWAYS present on macOS 15+ -
    it is the durable home of the hands-off story, styled exactly like its
    sibling Settings cards (bordered container + st.html header, status dot):

      * granted     → green dot, one-line confirmation, no actions.
      * not granted → blue dot + why-it-matters copy, the 4-step walkthrough,
                      and the Open Full Disk Access Settings button.

    Renders its own "MACOS PERMISSIONS" section header so non-Mac platforms
    show neither header nor card. Never touches the nudge's dismissal state.
    """
    _applies, _granted = _fda_gate()
    if not _applies:
        return

    st.html("""<div style="padding:8px 0 1px 0;"><span style="font-size:0.7rem;font-weight:800;text-transform:uppercase;letter-spacing:0.12em;color:#e2e8f0;">MACOS PERMISSIONS</span></div>""")

    # Lucide shield-check, blue - sized inline like the sibling cards' 18px icons.
    _shield = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        "stroke='#60a5fa' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' "
        "style='width:18px;height:18px;flex-shrink:0;'>"
        "<path d='M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z'/>"
        "<path d='m9 12 2 2 4-4'/></svg>"
    )

    if _granted:
        _dot, _status = "#22c55e", ("Full Disk Access granted &middot; "
                                    "permission pop-up hidden and conversions run fully hands-off")
    else:
        _dot, _status = "#3b82f6", ("Not granted &middot; macOS will prompt you with a one-click "
                                    "permission pop-up, every time you start the app.")

    _steps_html = "" if _granted else (
        "<ol style='margin:9px 0 2px 0;padding-left:1.35em;color:#cbd5e1;"
        "font-size:0.78rem;line-height:1.65;'>"
        + _FDA_STEPS_HTML.replace("<b>", "<b style='color:#b6d3ff;'>")
        + "</ol>"
    )

    with st.container(border=True, key="stg_card_fda"):
        st.html(
            f"""<div style="padding:0 0 4px 0;"><div style="display:flex;align-items:center;gap:7px;margin-bottom:3px;margin-top:-5px;">{_shield}<span style="font-size:1.1rem;font-weight:600;color:#e2e8f0;">Hands-off Office conversions</span></div><div style="font-size:0.78rem;color:#94a3b8;line-height:1.4;">Converting PowerPoint, Word and Excel files to PDF uses Microsoft Office on your Mac, and macOS 15 + 26 asks a one-click <b style="color:#b6d3ff;">&ldquo;access data from other apps&rdquo;</b> permission the every time you start the app, the moment office conversions start. But you don't need to manually click allow every time you use the app - granting Canvas Downloader <b style="color:#b6d3ff;">Full Disk Access</b> removes it permanently. This is an optional, but recommended action.</div><div style="display:flex;align-items:center;gap:7px;margin-top:7px;font-size:0.78rem;color:#cbd5e1;"><span style="width:8px;height:8px;border-radius:50%;background:{_dot};flex-shrink:0;"></span><span>{_status}</span></div>{_steps_html}</div>"""
        )
        if not _granted:
            # Key deliberately avoids the `_fda_open_btn` suffix: that CSS
            # styles the nudge's compact pill, while this button must render
            # like its full-width Settings siblings (e.g. "Configure
            # transcription").
            if st.button("Open Full Disk Access Settings", key="stg_fda_grant_btn",
                         use_container_width=True):
                from engine.applescript_bridge import open_full_disk_access_settings
                open_full_disk_access_settings()
                st.toast(_FDA_TOAST)


def render_help_card(key_prefix: str, title: str, text_html: str, icon: str = "", mode: str = "auto"):
    """
    Renders a unified Help Explainer Card component.

    Args:
        key_prefix: Unique string to namespace CSS classes and the toggle id.
        title: Title of the explainer card.
        text_html: The HTML body content of the explainer card.
        icon: The emoji/icon prefix for the title.
        mode: "auto" (default), "button" (only trigger), or "card" (only expanded content).

    The card is a PURE-CSS toggle - a hidden checkbox plus ``label for=``
    triggers - and deliberately NOT an ``st.button`` + ``st.rerun()``. Three
    separate defects were measured on that single click before this was
    rewritten (2026-07-26), and all three are reruns, not styling:

    1. **The list flashed / lost its styling.** Streamlit hoists every
       style-only ``st.html()`` into ONE ordered, ``display: none`` list
       (``div[data-testid="stEvent"]``) and reconciles it BY INDEX. The card's
       own ``<style>`` was emitted only while the card was open, so opening or
       closing it shifted every later stylesheet onto its NEIGHBOUR's host.
       Recorded frame-by-frame: for one frame the course list's
       ``st-key-dl_chk_`` stylesheet was replaced by the per-course label
       stylesheet. Exactly the failure family CLAUDE.md documents for a dialog
       emitted before the main page - a different trigger, same mechanism.
       (Which is why BOTH ``st.html`` blocks below are now unconditional: a
       conditional stylesheet is the bug, not the card.)
    2. **The primary actions flashed bright and the captions faded.** A full
       rerun re-creates those elements, dropping the ``data-cd-*`` attributes
       their paint hangs off until an observer re-applied them. Those
       attributes now live on ``document.body`` (see ``_gate_actions_on_selection``
       and ``inject_app_shell_bridge``), which fixes the general case; not
       rerunning at all fixes this one.
    3. Everything below the card was re-rendered to show a static explainer.

    Toggling now mutates nothing on the server, so there is no reconciliation
    to go wrong. Verified in a harness first (Streamlit keeps raw ``<input>``
    markup, a ``label for=`` still activates a checkbox inside a
    ``display: none`` ancestor, and the checked state survives an unrelated
    rerun because React leaves an unchanged ``dangerouslySetInnerHTML``
    alone), then in the app.

    **This component emits NO stylesheet of its own - every rule lives in
    ``styles/global.css`` - and it must stay that way.** A style-ONLY
    ``st.html()`` does not render where you call it: Streamlit routes it to the
    EVENT root container, one global INDEX-ADDRESSED list that ``st.toast``
    also writes to, and that a dialog's fragment rerun REWINDS to the index its
    call site held. Measured in the real app on 2026-07-30: this component's
    stylesheet was the first event-container write after ``sync_ui.py:1294``'s
    Saved Groups hub, so deleting a saved pair (which queues a toast) landed
    that toast on the stylesheet's index and deleted it - and because these are
    the only rules in the app whose ABSENCE makes hidden content appear, the
    card unfolded itself behind the open dialog with its checkbox still
    unchecked. See the header comment in ``global.css`` for the full chain.
    """
    from shared.helpers import esc, help_text_enabled

    # Single gate for every Help affordance in the app - all eight call sites
    # route through here, so the Settings toggle needs exactly this one check.
    if not help_text_enabled():
        return

    show_button = (mode in ["auto", "button"])
    show_card = (mode in ["auto", "card"])

    # The close and help glyphs are constants, so they are baked into the
    # data: URIs in global.css rather than re-encoded per call.
    help_btn_key = f"{key_prefix}_explainer_help_btn"
    # The `for=` target. A label activates its control from anywhere in the
    # document, which is what lets the trigger live in the page header while
    # the checkbox sits with the card further down - they never need a shared
    # parent, only the checkbox and the card do (for the `~` combinator).
    cb_id = f"cd-help-{key_prefix}"

    if show_card:
        # Icon: inline SVG/IMG rendered as-is, an emoji wrapped, nothing falls
        # back to the shared lightbulb.
        if not icon:
            _icon_html = HELP_ICONS.get('lightbulb', '')
        elif icon.strip().startswith('<svg') or icon.strip().startswith('<img'):
            _icon_html = icon
        else:
            _icon_html = f'<span style="font-size: 1.1rem; line-height: 1;">{icon}</span>'

        # One markdown call: checkbox + card as SIBLINGS so `:checked ~ .card`
        # resolves. Built on one line - four spaces of leading indent would make
        # Streamlit's markdown parser read it as a code block.
        st.markdown(
            f'<div class="cd-help-wrap">'
            f'<input type="checkbox" id="{cb_id}" class="cd-help-cb">'
            f'<div class="cd-help-card">'
            f'<label for="{cb_id}" class="cd-help-close" title="Close"></label>'
            f'<p class="cd-help-card-title">{_icon_html}{esc(title)}</p>'
            f'<div class="cd-help-card-body">{text_html}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    if show_button:
        # Alignment by MODIFIER CLASS, not by an f-string in a stylesheet:
        # "auto" puts the trigger top-right of its row (flex-end + 25px),
        # every other mode leaves it at the row's start. Carrying the variant
        # on markup the component already owns is what lets the whole
        # stylesheet stay static in global.css - see the docstring.
        _row_cls = ("cd-help-trigger-row cd-help-trigger-row--end"
                    if mode == "auto" else "cd-help-trigger-row")

        with st.container(key=help_btn_key):
            # A label, not an st.button: a button would post a widget value and
            # rerun the whole page (see the docstring). Wrapped in a div so
            # Streamlit does not put the inline label inside a paragraph.
            st.markdown(
                f'<div class="{_row_cls}">'
                f'<label for="{cb_id}" class="cd-help-trigger" title="Click to open guide.">Help</label>'
                f'</div>',
                unsafe_allow_html=True,
            )

