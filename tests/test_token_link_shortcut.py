"""The "Get a token" shortcut beside the Canvas Access Token field.

It is a copy of the guide's "Open my Canvas token settings page" button, moved
to where the user is actually standing when they need it. Four things about it
fail silently, and each has a section here:

1. **It cannot be an ``st.button``.** It lives inside ``st.form``, where a
   button cannot rerun - which is also why its target is derived client-side by
   the picker's bridge rather than read from ``st.session_state``.

2. **DISABLED means "no href", never ``pointer-events: none``.** The whole
   point of a disabled control is that it can explain itself; killing pointer
   events takes the tooltip away with the click and turns an unavailable
   button into a dead end.

3. **The href is built by US, never taken from what was typed.** The scheme is
   always our own ``https://``, so a ``javascript:`` value pasted into the URL
   field degrades into a nonsense hostname instead of becoming a live scheme.

4. **The repaint must happen ABOVE the bridge's early returns.** Those guard on
   the picker and the status row being on the page. In reauth mode neither is,
   and the token link still is - so a repaint placed after them leaves the one
   surface that reauth mode DOES render permanently disabled.
"""

from __future__ import annotations

import re
from pathlib import Path

from shared.helpers import esc as _he
from ui import institution_picker as picker

_ROOT = Path(__file__).resolve().parent.parent
_AUTH_SRC = (_ROOT / "ui" / "auth.py").read_text(encoding="utf-8")
_PICKER_SRC = (_ROOT / "ui" / "institution_picker.py").read_text(encoding="utf-8")
_JS = picker._BRIDGE_JS

# The login form's own source. Anchoring inside it matters: several of these
# class names appear TWICE in auth.py - once in the page's stylesheet, once in
# the markup - and the stylesheet comes first, so a bare `.index()` measures
# the CSS and reports nothing about where the element renders.
_FORM_START = _AUTH_SRC.index('with st.form("auth_form"')
_FORM = _AUTH_SRC[_FORM_START:_AUTH_SRC.index("st.form_submit_button(", _FORM_START)]


def _fn(name: str) -> str:
    """The body of one bridge function, from its declaration to the next one."""
    start = _JS.index(f"function {name}(")
    nxt = _JS.find("\n  function ", start + 1)
    return _JS[start:nxt if nxt != -1 else len(_JS)]


# ── 1. The shell ─────────────────────────────────────────────────────────────

def test_the_shell_is_one_line():
    """A blank line inside an indented HTML literal terminates the block and
    renders the rest as a CODE BLOCK - the bug the hub pair card shipped, and
    the one Rule 10 exists for."""
    html = picker.token_link_html("https://cbscanvas.instructure.com")
    assert "\n" not in html, "the token link markup must be ONE line"


def test_the_fallback_url_is_escaped_into_the_markup():
    """It reaches the shell as an attribute VALUE. A single quote would close
    the attribute early; a tag would land in the page. It is the user's own
    typed address today, which is exactly the kind of fact that stops being
    true when someone routes a Canvas-supplied value here."""
    html = picker.token_link_html("https://x.test/'><img src=x onerror=alert(1)>")
    # The payload survives as inert TEXT; what must not survive is any of the
    # three characters that could end the attribute or open an element.
    assert "<img" not in html, "raw markup survived into the token link shell"
    assert "&#x27;" in html and "&lt;" in html and "&gt;" in html, (
        "the fallback was not escaped"
    )
    attr = re.search(r"data-fallback='([^']*)'", html)
    assert attr and "<" not in attr.group(1) and ">" not in attr.group(1)


def test_the_shell_starts_disabled_with_no_href_and_a_reason():
    """Server-rendered state is the state before the bridge has run, and it must
    be the SAFE one: no target, and a tooltip saying what is missing. Painting
    it enabled first would offer a link to nowhere for a frame."""
    html = picker.token_link_html()
    assert "href=" not in html, "the un-driven shell must carry no href"
    assert "aria-disabled='true'" in html
    # Escaped, because the sentence contains an apostrophe and the attribute is
    # single-quoted - the exact case that would otherwise close it early.
    assert f"title='{_he(picker.TOKEN_LINK_TITLE_OFF)}'" in html


def test_the_disabled_tooltip_names_what_is_missing():
    """The user cannot act on 'unavailable'. This is the sentence that turns a
    greyed button into an instruction."""
    off = picker.TOKEN_LINK_TITLE_OFF.lower()
    assert "canvas url" in off, f"the disabled tooltip does not mention the URL: {off!r}"


def test_the_enabled_tooltip_carries_the_full_sentence_the_label_cannot():
    """The label is trimmed to fit the app's minimum window; the tooltip is
    where the whole phrase survives, so nothing is actually lost."""
    assert picker.TOKEN_LINK_TITLE_ON == "Open my Canvas token settings page"


def test_the_video_is_visible_enough_to_be_the_last_resort():
    """Deleting the token expander made the tutorial video the only walkthrough
    on the page beyond the two lines under the field. It was grey text and a
    grey glyph on a 4%-white slab - the quietest thing on a dark screen, found
    late or not at all. It does not need to shout; it needs to read as a
    control."""
    i = _AUTH_SRC.index(".youtube-link {")
    block = _AUTH_SRC[i:_AUTH_SRC.index("}", i)]
    assert "#94a3b8" not in block, "the label is back to the dimmest grey on the page"
    icon = _AUTH_SRC[_AUTH_SRC.index(".youtube-icon {"):]
    icon = icon[:icon.index("}")]
    assert "#ef4444" in icon, (
        "the play glyph is grey at rest - the red IS the recognition, and a "
        "grey play button is just a triangle"
    )


def test_there_is_exactly_one_way_to_reach_the_token_page():
    """There were two: this one, and a copy in an expander at the bottom of the
    page. Two buttons for one action can disagree, and did - on a returning
    login one was enabled and the other greyed out, telling the user to enter a
    URL the app already had.

    The bottom one is gone. If a second appears, it has to answer for itself:
    a duplicate whose state is computed a different way is the bug, not the
    duplication."""
    assert "st.button(" not in _AUTH_SRC[
        _AUTH_SRC.index('with st.container(key="login_help_expanders")'):
        _AUTH_SRC.index("youtube-link")], (
        "a second token-settings button is back in the help expanders"
    )
    assert "_canvas_url_reachable(" not in _AUTH_SRC, (
        "the click-time reachability check cannot work from inside st.form"
    )


def test_the_label_is_short_enough_for_the_minimum_window():
    """A character proxy for a MEASUREMENT: the window opens maximized with
    min_size=(1024, 700), and at 1024 the button's text box is ~73px. Measured
    in the running app, "Get my Canvas token" needs 123px and truncates to
    "Get my Ca..."; the candidates that fit are ~11 characters and under.

    If this fails, re-measure at 1024 rather than raising the bound."""
    assert len(picker.TOKEN_LINK_LABEL) <= 11, (
        f"{picker.TOKEN_LINK_LABEL!r} will truncate at the app's minimum window"
    )


def test_the_shell_is_an_anchor_and_not_a_button():
    """A real button inside st.form is a Streamlit exception, i.e. a login page
    that does not render at all."""
    html = picker.token_link_html()
    assert "<button" not in html
    assert "<a class='cd-tokenlink-btn'" in html


# ── 2. The bridge ────────────────────────────────────────────────────────────

def test_the_token_link_repaints_above_every_early_return():
    """paintStatus() returns early when the status row is absent, and in reauth
    mode it always is - no URL field, no picker, no status row, but the token
    link is still on the page reading its fallback."""
    body = _fn("paintStatus")
    assert "paintTokenLink()" in body, (
        "nothing repaints the token link when the Canvas URL changes"
    )
    assert body.index("paintTokenLink()") < body.index("statusEl()"), (
        "paintTokenLink() sits below an early return, so reauth mode never paints it"
    )


def test_the_href_scheme_is_always_ours():
    """`javascript:` / `data:` pasted into the URL field must not become the
    scheme of a link we render. Building 'https://' + host makes that
    structural rather than a filter someone has to maintain."""
    body = _fn("tokenHref")
    assert "'https://' + h" in body, "the token link no longer builds its own scheme"
    assert "/profile/settings" in body


def test_the_href_uses_only_the_host():
    """A pasted deep link (…/courses/123) must still point at the settings page,
    not at a nested path under it."""
    assert "hostOf(raw)" in _fn("tokenHref")


def test_a_bare_shorthand_expands_the_way_login_itself_will():
    """`cbscanvas` is a valid thing to type - normalize_canvas_url expands it to
    cbscanvas.instructure.com and logs in fine. A link that disagreed would
    point somewhere the login does not."""
    body = _fn("tokenHref")
    assert "'.instructure.com'" in body and "indexOf('.') === -1" in body, (
        "the token link no longer mirrors normalize_canvas_url's bare-shorthand rule"
    )
    # ...and the Python side still has the rule being mirrored.
    assert "instructure.com" in _AUTH_SRC[
        _AUTH_SRC.index("def normalize_canvas_url"):
        _AUTH_SRC.index("def normalize_canvas_url") + 1400]


def test_a_pasted_token_does_not_produce_a_link():
    """The single most common first-run mistake is the two fields swapped. A
    link built from a token is a guaranteed dead tab."""
    assert "looksLikeToken(raw)" in _fn("tokenHref")


def test_a_field_that_says_something_beats_the_fallback():
    """Preferring the fallback while the user is typing would freeze the link
    on a stale address - the school they are switching AWAY from."""
    body = _fn("paintTokenLink")
    assert "var raw = typed || (box.getAttribute('data-fallback')" in body, (
        "the token link no longer prefers what the user typed"
    )
    assert "(inp.value || '').trim()" in body, (
        "a field holding only whitespace must count as saying nothing"
    )


def test_an_empty_field_falls_back_instead_of_going_dead():
    """A returning login renders the URL field EMPTY while the verified address
    sits in config - so 'no field value' cannot mean 'we do not know the
    school'. It did once: this button went grey and told the user to enter a
    URL while the guide's copy of it, thirty lines down the same page, was
    enabled and pointing at their Canvas."""
    body = _fn("paintTokenLink")
    assert "typed ||" in body, "an empty field no longer falls back"
    # The call site must actually SUPPLY that fallback outside reauth mode.
    call = re.search(r"institution_picker\.token_link_html\(([^)]*)\)", _AUTH_SRC)
    assert "url_verified" in _AUTH_SRC[
        _AUTH_SRC.index("_link_fallback"):_AUTH_SRC.index(call.group(0))], (
        "the fallback is not supplied for a returning login"
    )


def test_the_fallback_is_only_ever_a_verified_url():
    """It is used without the user re-confirming it, so it must be an address
    this machine has already logged in with - never something merely typed."""
    i = _AUTH_SRC.index("_link_fallback = ")
    expr = _AUTH_SRC[i:_AUTH_SRC.index("\n", _AUTH_SRC.index("else ''", i))]
    assert "_reauth_mode or st.session_state.get('url_verified')" in expr, (
        f"the fallback dropped its verified-only guard: {expr!r}"
    )
    assert "url_input" not in expr, "the fallback must not come from the raw field"


def test_the_disabled_branch_removes_the_href_and_keeps_a_title():
    body = _fn("paintTokenLink")
    dis = body[body.index("} else {"):]
    assert "removeAttribute('href')" in dis, (
        "a disabled token link that keeps its href is still clickable"
    )
    assert "data-title-off" in dis, "nothing tells the user why it is unavailable"


def test_the_tooltip_copy_lives_in_python_not_in_the_bridge():
    """Two copies of a sentence is how the disabled state ends up explaining
    something the enabled state no longer does."""
    for phrase in (picker.TOKEN_LINK_TITLE_ON, picker.TOKEN_LINK_TITLE_OFF,
                   picker.TOKEN_LINK_LABEL):
        assert phrase not in _JS, f"{phrase!r} is hard-coded in the bridge"


# ── 3. The call site ─────────────────────────────────────────────────────────

def test_the_link_renders_inside_the_login_form():
    """Outside the form it would sit under the Log In button, which is not
    where anyone looks for it - and the whole reason it is an anchor is that it
    is inside."""
    form = _AUTH_SRC.index('with st.form("auth_form"')
    submit = _AUTH_SRC.index("st.form_submit_button(", form)
    call = _AUTH_SRC.index("institution_picker.token_link_html(")
    assert form < call < submit


def test_both_rows_use_the_same_column_split():
    """The shortcut is meant to line up under the institution picker. Two
    different ratios put two controls of different widths in one column - which
    reads as a mistake, and is one."""
    ratios = re.findall(r"st\.columns\(\[([^\]]+)\], vertical_alignment=\"bottom\"\)",
                        _AUTH_SRC[_AUTH_SRC.index('with st.form("auth_form"'):])
    assert len(ratios) == 2, f"expected the URL row and the token row, got {ratios}"
    assert ratios[0] == ratios[1], f"the two rows drifted apart: {ratios}"


def test_reauth_mode_passes_the_saved_url_as_the_fallback():
    """Reauth renders no URL field, so without this the one screen whose whole
    purpose is 'go and get a fresh token' offers a permanently dead button."""
    call = re.search(r"institution_picker\.token_link_html\(\s*([^)]*)\)", _AUTH_SRC)
    assert call, "the token link call site is gone"
    assert "_link_fallback" in call.group(1), (
        f"the call site no longer passes a fallback: {call.group(1)!r}"
    )
    i = _AUTH_SRC.index("_link_fallback = ")
    assert "_saved_url if" in _AUTH_SRC[i:i + 120], (
        "reauth mode no longer supplies the saved URL"
    )


# ── 4. The paint ─────────────────────────────────────────────────────────────

def _css_block(selector: str) -> str:
    i = _AUTH_SRC.index(selector)
    return _AUTH_SRC[i:_AUTH_SRC.index("}", i)]


def test_the_disabled_state_keeps_its_pointer_events():
    """`pointer-events: none` removes the hover, and with it the tooltip that
    is the only thing telling the user what to do next."""
    block = _css_block('.cd-tokenlink-btn[aria-disabled="true"]')
    assert "pointer-events" not in block, (
        "pointer-events on the disabled token link takes its explanation away"
    )
    assert "cursor: not-allowed" in block


def test_the_disabled_paint_is_the_app_s_one_recipe():
    """brightness(0.5) saturate(0.5) and nothing on top: opacity MULTIPLIES with
    the filter, a second filter REPLACES it, and a flat grey repaint makes two
    differently-coloured controls look like one."""
    block = _css_block('.cd-tokenlink-btn[aria-disabled="true"]')
    assert "filter: brightness(0.5) saturate(0.5)" in block
    assert "opacity" not in block, "opacity multiplies with the shared filter"
    assert "grayscale" not in block, "a second filter replaces the shared one"
    assert "background" not in block, "a flat repaint is not the disabled recipe"


def test_the_markdown_margin_is_cancelled_so_the_button_lines_up():
    """Streamlit puts margin-bottom:-16px on every stMarkdownContainer, which
    pulls a markdown-rendered control up out of line with the input beside it -
    the same correction the picker trigger needs one row above."""
    assert '[data-testid="stMarkdownContainer"]:has(> .cd-tokenlink)' in _AUTH_SRC


# ── 5. The help "?" ──────────────────────────────────────────────────────────

def test_the_help_icon_sits_next_to_its_label():
    """1.51 wraps the tooltip icon in an unnamed `flex: 1 1 0%;
    justify-content: flex-end` div, which parked the "?" 343 measured pixels
    from the word it explains. Collapsing that wrapper is the whole fix."""
    sel = '[data-testid="stWidgetLabel"] > div:has(> [data-testid="stTooltipIcon"])'
    assert sel in _AUTH_SRC, "the widget-label tooltip rule is gone"
    block = _css_block(sel)
    assert "flex: 0 0 auto" in block
    assert "justify-content: flex-start" in block


# ── 6. Getting the form above the fold ───────────────────────────────────────

def test_the_first_run_strip_is_two_lines():
    """Measured at the app's minimum window (1024x700 -> 636px of viewport):
    the three-step version was 262px, the largest element on the page, and it
    put the token field at y=715 and Log In at y=799 - both below the fold, on
    the run where a user is deciding whether this app works.

    What is left is the orienting line and the safety line, because those are
    the only two things on that strip that are not written anywhere else."""
    i = _AUTH_SRC.index("_getstarted_html = (")
    strip = _AUTH_SRC[i:_AUTH_SRC.index(") if (_first_run", i)]
    assert "lgs-step" not in strip, "the numbered steps are back in the first-run strip"
    assert "lgs-head" in strip and "lgs-safe" in strip, (
        "the strip lost its orienting line or its is-this-safe line"
    )


def test_the_url_guide_does_not_open_itself():
    """The picker answers 'what is my Canvas URL' in one click for thousands of
    schools, so auto-expanding 'open Canvas and copy the address bar' above the
    harder step is backwards."""
    i = _AUTH_SRC.index("'How to find your Canvas URL?'")
    assert "expanded=False" in _AUTH_SRC[i:i + 120], (
        "the URL guide auto-expands again"
    )


def test_the_token_walkthrough_sits_under_the_token_field():
    """Not at the bottom of the page: the work happens in Canvas, in another
    window, and instructions the user has scrolled away from are instructions
    they do not have."""
    assert "login-tokensteps" in _FORM, (
        "the walkthrough is not inside the login form at all"
    )
    assert _FORM.index("token_input") < _FORM.index("login-tokensteps"), (
        "the walkthrough renders above the field it describes"
    )


def test_the_walkthrough_token_instruction():
    """Instructions tell the user where in Canvas to create a token and to paste it here."""
    block = _FORM[_FORM.index("login-tokensteps"):]
    assert "Approved Integrations" in block, "the walkthrough lost WHERE to go"
    assert "Once you have your token, copy it straight away and paste it here." in block


def test_the_walkthrough_starts_where_the_BUTTON_would_have_taken_them():
    """"Get a token" lands on /profile/settings, so Account -> Settings are
    hops the button walks for the user - which is exactly why they must be
    written down. The button is the only thing here that can fail (wrong
    address, blocked pop-up, an unusual Canvas), and instructions that assume
    it worked are worth nothing at the moment it did not."""
    block = _FORM[_FORM.index("login-tokensteps"):]
    path = block[:block.index("lts-note")]
    for hop in ("Account", "Settings", "Approved Integrations", "New Access Token"):
        assert hop in path, f"the walkthrough skips {hop!r}"
    assert path.index("Account") < path.index("Settings") < path.index("Approved Integrations"), (
        "the hops are out of order"
    )


def test_the_copy_it_now_line_is_emphasis_and_not_a_warning():
    """Amber means something is WRONG in this app - the status rows, the
    disabled states, the sync notices all use it that way. Nothing is wrong
    here; the line was reaching for emphasis and borrowing a meaning, which
    costs more than it buys. Bold and a glyph carry it instead."""
    i = _AUTH_SRC.index(".lts-note {")
    block = _AUTH_SRC[i:_AUTH_SRC.index("}", i)]
    assert "#fbbf24" not in block and "color:" not in block, (
        "the copy-it-now line paints itself a warning colour again"
    )
    assert "display: inline" in block, (
        "the note is a block again, so it reserves a second row at every width"
    )
    md = _FORM[_FORM.index("login-tokensteps"):]
    assert "Once you have your token, copy it straight away and paste it here." in md
    assert "lts-warn" not in _AUTH_SRC, "the warning class is back"


def test_the_walkthrough_gates_its_CONTENT_and_not_its_ELEMENT():
    """Streamlit reconciles by position and hands a block the CHILDREN of
    whatever held its index, so a row that comes and goes with a setting is the
    keyed-card inheritance bug waiting to happen. The markdown always renders;
    only its text is gated."""
    i = _FORM.index("login-tokensteps")
    call_start = _FORM.rindex("st.markdown(", 0, i)
    block = _FORM[call_start:_FORM.index("unsafe_allow_html=True)", i)]
    assert 'if help_text_enabled() else ""' in block, (
        "the walkthrough is gated by an if STATEMENT around the element"
    )
    # ...and no `if` opens a block around that st.markdown call.
    preceding = _FORM[:call_start].rsplit("\n", 3)[-3:]
    assert not any(ln.strip().startswith("if ") for ln in preceding), (
        f"the element itself is conditional: {preceding!r}"
    )


# ── 7. The token field's own status row ──────────────────────────────────────

def test_the_token_row_only_speaks_when_it_KNOWS():
    """A token is opaque and older Canvas instances issue them without the
    `1234~` prefix, so 'looks valid' is unknowable and 'looks invalid' would be
    wrong for real tokens. Three provable cases, nothing else."""
    body = _fn("paintTokenStatus")
    assert "instructure.com" in body, "the swapped-fields case is gone"
    assert "/\\s/.test(" in body, "the pasted-with-whitespace case is gone"
    assert "blurred && v.length < TOK_MIN" in body, (
        "the too-short case no longer waits for the user to leave the field"
    )
    assert "state = null" in body, "the row lost its silent default"


def test_the_too_short_warning_never_fires_mid_typing():
    """Every token is short while it is being typed. The row must not accuse a
    field the user is still working in - nor on mount, where nothing has been
    touched at all."""
    assert "paintTokenStatus(false)" in _JS, "the mount/input calls must not pass blurred"
    assert "paintTokenStatus(true)" in _JS, "nothing ever reports a blur"
    body = _fn("onFocusOut")
    assert "paintTokenStatus(true)" in body, "the blur case is not wired to focusout"


def test_the_focusout_listener_is_delegated_and_rebound_like_every_other():
    """`blur` does not bubble, so a delegated listener must use `focusout` -
    and it has to be torn down and re-attached with the rest, or a remount
    leaves it bound to a dead realm."""
    assert "'focusout'" in _JS
    i = _JS.index("['click', 'keydown', 'input'")
    assert "'focusout'" in _JS[i:i + 80], "focusout is not in the re-bind list"
    assert "reg.focusout = onFocusOut" in _JS, "the handler ref is not stashed for removal"


def test_the_token_status_shell_is_one_line_and_starts_empty():
    html = picker.token_status_html()
    assert "\n" not in html
    assert "data-state" not in html, "the shell must start with no state"


def test_both_status_rows_are_the_SAME_component():
    """They differ in one margin and nothing else. Built separately, the token
    row was carrying the URL row's class names inside it - which works, and
    reads like a copy-paste bug for as long as it lives. One builder means the
    next change to a status row cannot land on only one of them."""
    url, tok = picker.url_status_html(), picker.token_status_html()
    assert url.replace("cd-url-status", "X") == tok.replace("cd-tok-status", "X"), (
        f"the two rows have drifted apart:\n{url}\n{tok}"
    )
    for html in (url, tok):
        assert "cd-status-ico" in html and "cd-status-tx" in html, (
            "an inner span is named for one row while both rows use it"
        )


def test_both_status_rows_announce_themselves_to_a_screen_reader():
    """These rows exist to catch a mistake at the moment it is made - the
    swapped fields, the truncated paste. Without a live region they are the one
    part of this form that speaks only to people who can see it."""
    for html in (picker.url_status_html(), picker.token_status_html()):
        assert "role='status'" in html, "the status row is not a live region"


def test_no_clipboard_glyph_in_tokensteps():
    """There is no clipboard icon glyph in the tokensteps walkthrough."""
    md = _FORM[_FORM.index("login-tokensteps"):]
    note = md[md.index("lts-note"):]
    assert "<svg" not in note, "clipboard glyph should not be in the note"


def test_a_silent_status_row_costs_no_layout_slot():
    """`display: none` on the row removes its HEIGHT, not its element-
    container - which is still a flex item in the form's 16px gap. Two silent
    rows were charging 32px for saying nothing, measured, on a page whose whole
    problem was height.

    The chain matters: stElementContainer > stMarkdown > stMarkdownContainer >
    the row. Skipping the stMarkdown level matches zero nodes and fails
    silently - which is exactly what the first attempt did."""
    for cls in (".cd-url-status", ".cd-tok-status"):
        i = _AUTH_SRC.index(f"> {cls}:not([data-state])")
        rule = _AUTH_SRC[_AUTH_SRC.rindex("div[class*=", 0, i):i]
        assert '[data-testid="stElementContainer"]:has(' in rule, (
            f"{cls}'s empty state does not collapse its container"
        )
        assert '> [data-testid="stMarkdown"] > [data-testid="stMarkdownContainer"]' in rule, (
            f"{cls}'s collapse rule skips the stMarkdown level and matches nothing"
        )


def test_the_collapse_is_keyed_on_the_row_having_nothing_to_say():
    """Not on a Python-side condition: the row is server-rendered every run
    (constant shape) and the bridge sets `data-state` when it speaks, so the
    slot has to come back on an ATTRIBUTE, with no rerun involved."""
    assert _AUTH_SRC.count(":not([data-state])") == 2, (
        "the collapse rule no longer keys on the row's own state"
    )


# ── 8. Autofocus ─────────────────────────────────────────────────────────────

def test_autofocus_never_steals_a_caret_the_user_placed():
    body = _fn("focusFirstEmpty")
    assert "reg.autofocused" in body, "autofocus would re-fire on every remount"
    assert "D.activeElement" in body and "!== D.body" in body, (
        "autofocus does not check whether something is already focused"
    )
    assert "(f.value || '').trim()" in body, "autofocus would land in a filled field"
    assert "preventScroll: true" in body, "autofocus would scroll the page"


def test_autofocus_prefers_the_url_field_then_the_token_field():
    """On a returning login the URL is pre-filled, so the caret lands in the
    token field - which is the only thing still missing."""
    body = _fn("focusFirstEmpty")
    assert "[urlInput(), tokenInput()]" in body


def test_autofocus_marks_itself_done_only_when_it_ACTS():
    """The mount settles over several ticks, so a first pass that finds the
    fields not yet hydrated must leave the decision open - otherwise the retry
    is dead and the caret never moves."""
    body = _fn("focusFirstEmpty")
    marks = body.count("reg.autofocused = true")
    assert marks == 2, (
        f"expected the flag to be set on the two paths that CONCLUDE "
        f"(something else is focused / a field was focused), found {marks}"
    )
    top = body[:body.index("var fields")]
    assert "reg.autofocused = true" not in top.split("if (reg.autofocused) return;")[1].split("if (ae")[0], (
        "the flag is set before the function has decided anything"
    )


# ── 8b. The mount settle ─────────────────────────────────────────────────────

def test_the_mount_settles_instead_of_reading_the_fields_once():
    """The bridge runs while Streamlit is still hydrating, so a value the
    server sent may not be in the input yet. Measured the day the URL field
    started arriving pre-filled: the picker read "Find your institution" beside
    a recognised school, the status row was blank, and the caret landed in the
    FILLED field because the empty-check saw ''."""
    assert "settleMount(0);" in _JS, "the mount no longer settles"
    body = _fn("settleMount")
    assert "paintStatus()" in body and "paintTokenStatus(false)" in body
    assert "P.setTimeout" in body, "the settle does not re-run"
    assert "if (n < SETTLE_TICKS)" in body, "the settle is unbounded"


def test_the_settle_holds_autofocus_back_until_the_fields_can_answer():
    """Focusing on tick 0 is what put the caret in a filled field. It waits for
    a field to report a value, or for the budget to say hydration is done -
    never longer."""
    body = _fn("settleMount")
    assert "n >= AUTOFOCUS_AFTER" in body, "autofocus has no budget"
    assert "(inp.value || '').trim()" in body, (
        "autofocus no longer waits for the URL field to report a value"
    )
    i = _JS.index("var SETTLE_TICKS")
    consts = _JS[i:_JS.index("\n", i)]
    assert "SETTLE_TICKS = 6" in consts and "SETTLE_MS = 70" in consts, consts
    assert "AUTOFOCUS_AFTER = 3" in consts, consts


def test_the_settle_never_reports_a_blur_it_did_not_see():
    """A repaint must not accuse a token field the user has not touched."""
    body = _fn("settleMount")
    assert "paintTokenStatus(true)" not in body


# ── 9. Remembering the school ────────────────────────────────────────────────

def test_a_saved_url_pre_fills_the_field():
    """Reaching the login page with a saved api_url means the TOKEN is gone,
    not the school. force_reauth has pre-filled this on the mid-session path
    all along."""
    i = _AUTH_SRC.index("def restore_saved_session")
    body = _AUTH_SRC[i:_AUTH_SRC.index("\ndef ", i + 10)]
    assert "st.session_state['url_input'] = st.session_state['api_url']" in body, (
        "a returning login no longer remembers the school"
    )


def test_the_pre_fill_never_overwrites_what_the_user_typed():
    """It writes a widget key Streamlit may already be tracking."""
    i = _AUTH_SRC.index("def restore_saved_session")
    body = _AUTH_SRC[i:_AUTH_SRC.index("\ndef ", i + 10)]
    j = body.index("st.session_state['url_input'] = ")
    guard = body[body.rindex("if ", 0, j):j]
    assert "not st.session_state.get('url_input')" in guard, (
        f"the pre-fill lost its empty-field guard: {guard!r}"
    )


def test_the_help_icon_rule_uses_the_direct_child_has_form():
    """A descendant :has() matches every ANCESTOR that merely CONTAINS a
    tooltip icon, so the rule would land on the card as well as the row."""
    i = _AUTH_SRC.index('> div:has(> [data-testid="stTooltipIcon"])')
    line = _AUTH_SRC[_AUTH_SRC.rindex("\n", 0, i) + 1:i + 60]
    assert ":has(> " in line, "the tooltip rule dropped its direct-child form"
