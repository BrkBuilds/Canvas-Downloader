"""The login page's institution picker.

Five things here fail SILENTLY or destructively, and each has its own section:

1. **Accidental submit.** Measured in the running app: ``st.form`` renders a
   DIV in Streamlit 1.51, not a ``<form>``, so a bare button does not natively
   submit - but Streamlit implements Enter-to-submit itself, so an un-swallowed
   Enter in the picker's search box still fires the login with a half-filled
   form. Nothing raises; it just logs in wrongly.

2. **The markup must be ONE line.** An indented multi-line HTML literal handed
   to ``st.markdown`` turns a blank line into a block terminator and renders the
   4-space-indented remainder as a literal CODE BLOCK - the bug the hub pair
   card shipped.

3. **``match_url`` must be exact-host.** It is what makes the UI say
   "Recognised: <school>". A suffix rule would make ``evil-harvard.edu`` match
   ``harvard.edu`` and have the app vouch for a host this list never verified.

4. **The bridge must survive Streamlit replacing nodes.** A ``components.html``
   iframe re-runs only when its srcdoc changes, and this one's is constant - so
   the script runs once per mount and never again. A listener bound to a
   specific node, or behind a one-time guard, dies the first time React
   reconciles and never comes back (exactly how the sync-history height bridge
   broke).

5. **The bridge must be emitted unconditionally.** Streamlit reconciles by
   position and hands a block the CHILDREN of whatever previously held its
   index. A component that appears only outside reauth mode shifts every
   element after it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from shared import institutions as inst
from ui import institution_picker as picker

_ROOT = Path(__file__).resolve().parent.parent
_AUTH_SRC = (_ROOT / "ui" / "auth.py").read_text(encoding="utf-8")
_PICKER_SRC = (_ROOT / "ui" / "institution_picker.py").read_text(encoding="utf-8")


# ── 1. The form-submit hazard ────────────────────────────────────────────────

def test_every_button_in_the_picker_is_type_button():
    """Correct declaration for a non-submit control, and cheap insurance if
    Streamlit ever renders st.form as a real form element again."""
    html = picker.picker_html()
    buttons = re.findall(r"<button\b[^>]*>", html)
    assert buttons, "picker rendered no buttons at all"
    bad = [b for b in buttons if "type='button'" not in b and 'type="button"' not in b]
    assert not bad, f"{len(bad)} button(s) would SUBMIT the login form: {bad[:3]}"


def test_payload_carries_every_institution():
    """The options are no longer server-rendered as elements - the DATA is, and
    the bridge renders only the rows a query matches. At ~1,900 entries, one
    button each is ~230 KB of markup re-parsed on every rerun plus 1,900 live
    nodes to filter; the payload is a fraction of that and costs three nodes."""
    payload = picker.build_payload()
    recs = payload.split(picker._RS)
    assert len(recs) == inst.count() == len(inst.DATA)
    for rec in recs:
        assert rec.count(picker._FS) == 2, f"malformed record: {rec[:60]!r}"


def test_payload_delimiters_appear_in_no_institution():
    """A delimiter inside a name would silently split one school into two."""
    for name, domain, _cc in inst.DATA:
        for delim in (picker._FS, picker._RS):
            assert delim not in name, f"{name!r} contains the {delim!r} delimiter"
            assert delim not in domain, f"{domain!r} contains the {delim!r} delimiter"


def test_payload_is_html_escaped_into_the_attribute():
    """It rides in a data attribute, so a stray quote would end the attribute
    and dump the rest of the list into the tag as bogus attributes."""
    real = inst.DATA
    try:
        inst.DATA = (("Quote\" and <b>bold</b>", "x.instructure.com", "US"),)
        html = picker.picker_html()
    finally:
        inst.DATA = real
    assert "<b>bold</b>" not in html
    assert "data-rows='" in html


def test_bridge_swallows_enter_in_the_search_field():
    """Streamlit's own Enter-to-submit must not fire from the picker."""
    js = picker._BRIDGE_JS
    m = re.search(r"if \(e\.key === 'Enter'\) \{(.*?)\n {4}\}", js, re.S)
    assert m, "no Enter branch found in the bridge's key handler"
    body = m.group(1)
    assert "preventDefault" in body and "stopPropagation" in body, (
        "Enter in the picker search must be both prevented and stopped, or "
        "st.form submits the login"
    )


def test_search_input_is_not_a_submit_trigger_by_omission():
    """The search field is a text input inside the form - keep it explicit."""
    html = picker.picker_html()
    assert "<input type='text' class='cd-inst-input'" in html


# ── 2. Markup shape ──────────────────────────────────────────────────────────

def test_markup_is_a_single_line():
    for name, html in (
        ("picker_html", picker.picker_html()),
        ("url_status_html", picker.url_status_html()),
    ):
        assert "\n" not in html, (
            f"{name} contains a newline; a blank line inside an st.markdown HTML "
            f"block terminates it and renders the rest as a code block"
        )


def test_every_institution_is_html_escaped():
    """Escaping is asserted on a real hostile row, not by reading the source."""
    from shared.helpers import esc
    hostile = ("<img src=x onerror=alert(1)>", "evil&co.instructure.com", "XX")
    real_data = inst.DATA
    try:
        inst.DATA = (hostile,)
        html = picker.picker_html()
    finally:
        inst.DATA = real_data
    assert "<img src=x" not in html, "an institution name reached the page unescaped"
    assert esc(hostile[0]) in html
    assert "evil&co" not in html or "evil&amp;co" in html


def test_the_coverage_caveat_lives_with_the_search_that_came_up_empty():
    """The caveat belongs in the picker's empty state, NOT as a standing line
    under the URL field. As a permanent line it repeated the empty state
    verbatim, and it sat under a field it has nothing to do with - so a
    perfectly valid, recognised address still carried a "not listed" remark."""
    assert not hasattr(picker, "hint_html"), (
        "the standing caveat was removed on purpose; do not reintroduce it"
    )
    empty_state = picker.picker_html()
    assert "Your school still works." in empty_state
    assert "type or paste" in empty_state.lower()


def test_empty_state_is_worded_as_an_instruction_not_a_failure():
    html = picker.picker_html()
    assert "Your school still works." in html
    # Thousands separator: the copy reads "1,792 institutions", not "1792".
    assert f"{inst.count():,}" in html, "the empty state should say how big the list is"


def test_no_em_or_en_dashes_in_user_facing_copy():
    """Project copy rule: spaced hyphens only, in the app as well as the site."""
    for name, html in (
        ("picker_html", picker.picker_html()),
        ("url_status_html", picker.url_status_html()),
    ):
        assert "—" not in html and "–" not in html, f"{name} contains an em/en dash"


# ── 3. The data, and exact-host matching ─────────────────────────────────────

def test_data_is_well_formed():
    seen = set()
    for row in inst.DATA:
        assert isinstance(row, tuple) and len(row) == 3, row
        name, domain, cc = row
        assert name and name.strip() == name, f"bad name {name!r}"
        assert domain == domain.lower(), f"domain not lowercased: {domain}"
        for bad in ("://", "/", " ", "?", "#", ":"):
            assert bad not in domain, f"{domain!r} is not a bare host ({bad!r})"
        assert "." in domain, f"{domain!r} has no dot"
        # Empty is legitimate: country is inferred from the domain's ccTLD, and
        # a *.instructure.com tenant carries no country signal at all. It is
        # only ever used to widen the search haystack, never displayed, so
        # "unknown" costs nothing - inventing one would be worse.
        assert cc == "" or re.fullmatch(r"[A-Z]{2}", cc), f"bad country {cc!r} for {name}"
        assert domain not in seen, f"duplicate domain {domain}"
        seen.add(domain)


def test_count_matches_data():
    assert inst.COUNT == len(inst.DATA) == inst.count()


def test_hand_reviewed_rejections_never_ship():
    """The last gate before shipping, and the only one that catches a
    same-name-different-school pairing (University of Miami vs Miami University,
    Ohio). Both are real universities owning corroborating domains, so no
    heuristic separates them - if this list stops being applied, the picker
    silently starts sending students to another university's Canvas."""
    import sys
    sys.path.insert(0, str(_ROOT / "scripts"))
    from institution_rejects import REJECT

    # What is rejected is the PAIRING, not the domain. Several of these hosts
    # ship legitimately under their OWN name - canvas.queens.edu really is
    # Queens University of Charlotte, and a student there should find it. The
    # defect would be that host appearing labelled "Queens University", the
    # Canadian one. So assert on the pair.
    shipped = {(n, d) for n, d, _c in inst.DATA}
    leaked = sorted(p for p in ((s, d) for s, d in REJECT.items()) if p in shipped)
    assert not leaked, f"hand-rejected NAME->DOMAIN pairings shipped: {leaked}"


def test_no_two_entries_are_the_same_institution():
    """A duplicate is not cosmetic: the picker is scanned by eye, and the same
    school twice on two tenants makes the user guess which one is theirs."""
    seen = {}
    for name, domain, _cc in inst.DATA:
        key = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", name.lower())).strip()
        key = re.sub(r"^the ", "", key)
        assert key not in seen, f"duplicate institution: {name} ({domain}) vs {seen.get(key)}"
        seen[key] = f"{name} ({domain})"


def test_list_is_big_enough_to_be_worth_shipping():
    assert len(inst.DATA) >= 150, (
        "the picker's value is coverage; a short list is worse than none"
    )


# Anchors, not a wish list: each is an institution the generator has ALREADY
# dropped silently at least once during development - twice for the Danish
# pair, once through a corroboration gap (cbscanvas fuses the LMS word into one
# label) and once through a transient verification timeout under concurrency.
# A regeneration that loses a whole market should fail here, not ship.
_ANCHORS = [
    ("cbscanvas.instructure.com", "Copenhagen Business School"),
    ("absalon.instructure.com", "University of Copenhagen"),
    ("canvas.lms.unimelb.edu.au", "University of Melbourne"),
    ("canvas.kth.se", "KTH"),
    ("canvas.harvard.edu", "Harvard"),
    ("canvas.ox.ac.uk", "Oxford"),
]


@pytest.mark.parametrize("domain,label", _ANCHORS)
def test_anchor_institutions_survive_regeneration(domain, label):
    row = next((r for r in inst.DATA if r[1] == domain), None)
    assert row is not None, f"{label} ({domain}) dropped out of the shipped list"


def test_the_list_spans_more_than_one_country():
    """The app is international; a build that collapsed to one market would
    still pass every other test here."""
    ccs = {c for _n, _d, c in inst.DATA if c}
    assert len(ccs) >= 8, f"only {len(ccs)} countries represented: {sorted(ccs)}"


def test_match_url_accepts_the_forms_a_student_actually_pastes():
    name, domain, _cc = inst.DATA[0]
    for form in (
        domain,
        f"https://{domain}",
        f"HTTPS://{domain.upper()}/",
        f"https://www.{domain}/courses/123",
        f"https://{domain}:443/login",
        f"  https://{domain}/  ",
    ):
        assert inst.match_url(form) is not None, f"failed to match {form!r}"
        assert inst.match_url(form)[0] == name


def test_match_url_is_exact_host_never_a_suffix():
    """A suffix rule would let a lookalike domain borrow a real school's name."""
    _name, domain, _cc = inst.DATA[0]
    for impostor in (f"evil-{domain}", f"{domain}.attacker.test", f"x{domain}"):
        assert inst.match_url(impostor) is None, f"{impostor!r} must not match {domain!r}"


def test_match_url_handles_junk():
    for junk in ("", "   ", None, "not a url", "1234~abcdefg"):
        assert inst.match_url(junk) is None


def test_search_blob_includes_name_domain_and_country():
    row = inst.DATA[0]
    blob = inst.search_blob(row)
    assert blob == blob.lower()
    for part in row:
        assert part.lower() in blob


def test_search_haystack_includes_the_country_NAME():
    """"denmark" has to find Danish schools, not only "dk"."""
    dk = next((r for r in inst.DATA if r[2] == "DK"), None)
    assert dk is not None, "no Danish institution in the shipped list"
    assert "denmark" in picker.search_blob(dk)
    assert inst.search_blob(dk) in picker.search_blob(dk), (
        "the picker's haystack must extend the generated one, not replace it"
    )


def test_every_shipped_country_has_a_searchable_name():
    """A country with no name entry is searchable only by its two-letter code,
    which no student would think to type."""
    missing = sorted({c for _n, _d, c in inst.DATA
                      if c and c not in picker.COUNTRY_NAMES})
    assert not missing, f"countries with no search name: {missing}"


def test_payload_records_carry_the_haystack():
    payload = picker.build_payload()
    recs = {r.split(picker._FS)[1]: r.split(picker._FS)[2]
            for r in payload.split(picker._RS)}
    for row in list(inst.DATA)[:25]:
        assert recs[row[1]] == picker.search_blob(row)


# ── 4. Bridge safety ─────────────────────────────────────────────────────────

_JS = picker._BRIDGE_JS


def test_listeners_are_delegated_on_the_document():
    for evt in ("click", "keydown", "input"):
        assert f"D.addEventListener('{evt}'" in _JS, f"{evt} is not delegated on document"


def test_previous_listeners_are_removed_before_rebinding():
    """A listener from a dead iframe realm stops firing silently; the fix is to
    re-bind every run, which requires removing the old one first."""
    assert "removeEventListener" in _JS
    assert "_cdInstReg" in _JS, "handler refs must persist on window.parent to be removable"


def test_no_one_time_bind_guard():
    """`if (bound) return;` is what makes a bridge die permanently after the
    first teardown - it works on load and never recovers."""
    assert not re.search(r"if\s*\(\s*\w*\.?bound\s*\)\s*return", _JS)
    assert not re.search(r"already(Bound|Init)", _JS, re.I)


def test_mutable_state_lives_on_window_parent_not_the_closure():
    assert "P._cdInstReg" in _JS


def test_blur_is_preceded_by_focus():
    """blur() is a no-op on an element that is not focused - the exact trap the
    search clear-X hit, where the DOM changed but Python never heard."""
    i_focus, i_blur = _JS.find("inp.focus("), _JS.find("inp.blur()")
    assert i_focus != -1 and i_blur != -1
    assert i_focus < i_blur, "focus() must come before blur() or the commit is skipped"


def test_value_is_set_through_reacts_native_setter():
    """Assigning .value directly does not notify React, so the form submits the
    old value."""
    assert "getOwnPropertyDescriptor" in _JS and "HTMLInputElement.prototype" in _JS
    assert "new P.Event('input'" in _JS


def test_bridge_reads_options_from_the_dom_rather_than_a_second_copy():
    """Recognition must consult the SERVER-RENDERED list, so the picker and the
    'Recognised:' line can never disagree about what is known."""
    assert "querySelectorAll('.cd-inst-opt')" in _JS


def test_bridge_guards_every_entry_point_on_the_picker_existing():
    """In reauth mode the page has no picker; the bridge still mounts."""
    for fn in ("function render", "function setOpen", "function pick", "function onClick"):
        i = _JS.find(fn)
        assert i != -1, f"{fn} missing"
        # Match the guard, not one exact spelling of it: `pick` legitimately
        # writes `if (!r || !opt) return`. Anchoring on the literal string made
        # a correct extra condition read as a MISSING guard.
        body = _JS[i:i + 400]
        assert re.search(r"var r = root\(\);\s*if \(!r[^)]*\) return", body), \
            f"{fn} does not bail out when the picker is absent"


# ── 5. Wiring in the login page ──────────────────────────────────────────────

def _login_fn() -> ast.FunctionDef:
    tree = ast.parse(_AUTH_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "render_login_page":
            return node
    raise AssertionError("render_login_page not found")


def test_bridge_is_injected_unconditionally():
    fn = _login_fn()
    found = []

    def walk(node, depth_conditional: bool):
        for child in ast.iter_child_nodes(node):
            cond = depth_conditional or isinstance(node, (ast.If, ast.Try, ast.While))
            if (isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "inject_bridge"):
                found.append(cond)
            walk(child, cond)

    walk(fn, False)
    assert found, "render_login_page never injects the picker bridge"
    assert not any(found), (
        "inject_bridge() is inside an if/try - a component that comes and goes "
        "shifts every element after it and hands blocks each other's children"
    )


def test_bridge_is_injected_after_the_form():
    """The iframe is a real element; emitting it mid-page would land between the
    card and the help expanders."""
    i_form = _AUTH_SRC.find('st.form("auth_form"')
    i_bridge = _AUTH_SRC.find("institution_picker.inject_bridge()")
    assert 0 < i_form < i_bridge


def test_picker_and_url_field_render_in_one_row():
    assert "vertical_alignment=\"bottom\"" in _AUTH_SRC
    i_cols = _AUTH_SRC.find("_c_url, _c_pick = st.columns")
    i_input = _AUTH_SRC.find("key=\"url_input\"")
    assert 0 < i_cols < i_input, "the URL field must render inside the picker row"


def test_status_row_is_pulled_up_under_the_field_it_describes():
    """It is its own markdown block, so Streamlit puts ~1rem above it. Without
    the pull-up the line floats between two fields and reads as belonging to
    neither."""
    assert "institution_picker.url_status_html()" in _AUTH_SRC
    m = re.search(r"\.cd-url-status \{(.*?)\n    \}", _AUTH_SRC, re.S)
    assert m, ".cd-url-status rule not found"
    block = m.group(1)
    # ONE margin declaration. A `margin-top` written above a `margin` shorthand
    # is silently overwritten by it, which made the first fix here look like the
    # CSS was not applying at all.
    assert block.count("margin:") == 1 and "margin-top:" not in block, (
        "use a single margin shorthand - a later shorthand overwrites margin-top"
    )
    mm = re.search(r"margin:\s*(-?[\d.]+)rem\s+0\s+([\d.]+)rem", block)
    assert mm, f"unexpected margin declaration: {block[:200]}"
    top, bottom = float(mm.group(1)), float(mm.group(2))
    assert top < 0, "must pull up to cancel Streamlit's block gap above it"
    # Grouped with the field it describes: closer above than below. Measured in
    # the running app at these values: 7px above, 12px below.
    assert bottom > 0 and abs(top) < bottom + 1.0, (
        "the line must sit nearer the field above than the label below"
    )


# ── CSS ↔ markup coupling ────────────────────────────────────────────────────

# Classes the bridge writes into but which carry no styling of their own.
_UNSTYLED_BY_DESIGN = {"cd-url-status-ico", "cd-url-status-tx"}


def test_every_markup_class_has_a_css_rule():
    """A class with no rule is an invisible, silent layout bug."""
    html = picker.picker_html() + picker.url_status_html()
    classes = set()
    for attr in re.findall(r"class='([^']+)'", html):
        classes.update(attr.split())
    assert classes, "no classes found in the picker markup"
    missing = [
        c for c in sorted(classes)
        if c not in _UNSTYLED_BY_DESIGN and f".{c}" not in _AUTH_SRC
    ]
    assert not missing, f"classes used in markup but never styled: {missing}"


def test_css_is_scoped_to_the_login_card():
    """Unscoped rules on generic names like .cd-inst-opt would leak app-wide."""
    for cls in ("cd-inst-trigger", "cd-inst-panel", "cd-inst-opt", "cd-url-status"):
        for m in re.finditer(rf"^\s*(?:[^\n{{}}]*,\s*\n)*[^\n{{}}]*\.{cls}\b[^\n{{}}]*\{{",
                             _AUTH_SRC, re.M):
            block_start = _AUTH_SRC.rfind("\n", 0, m.start())
            selector_run = _AUTH_SRC[max(0, block_start - 400):m.end()]
            assert "st-key-login_card_wrapper" in selector_run, (
                f".{cls} has a rule that is not scoped to the login card"
            )


def test_picker_module_does_not_import_streamlit_at_call_time_for_markup():
    """picker_html() is pure string building - it must stay unit-testable
    without a Streamlit runtime."""
    assert picker.picker_html()
    assert picker.url_status_html()


def test_no_hand_rolled_second_copy_of_the_token_heuristic_in_python():
    """The JS mirror of _looks_like_token is deliberate and documented; a THIRD
    copy in this module would not be."""
    assert "looksLikeToken" in _PICKER_SRC
    assert "_looks_like_token" not in _PICKER_SRC.replace(
        "Mirrors ui/auth.py:_looks_like_token", ""
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ── Scale: rendering, keyboard and ARIA ──────────────────────────────────────

def test_only_a_capped_number_of_rows_is_ever_rendered():
    """At ~1,800 institutions the list must not become 1,800 DOM nodes."""
    m = re.search(r"var RENDER_CAP = (\d+);", _JS)
    assert m, "RENDER_CAP not found"
    assert 20 <= int(m.group(1)) <= 120, "cap should bound the DOM without hiding results"
    assert "hits.slice(0, RENDER_CAP)" in _JS


def test_the_count_line_tells_the_user_results_were_truncated():
    """Silently showing 60 of 1,079 matches would look like a broken search."""
    assert "keep typing to narrow" in _JS
    assert "Showing " in _JS


def test_highlight_regex_is_compiled_once_per_render_not_per_row():
    """Per-row compilation measured 55-78 ms per keystroke - visible lag."""
    assert "function highlighter(" in _JS
    i_render = _JS.find("function render()")
    body = _JS[i_render:i_render + 1200]
    assert "highlighter(terms)" in body, "the pattern must be built once in render()"
    assert "new RegExp" not in _JS[_JS.find("function mark("):_JS.find("function render()")], (
        "mark() must not compile a RegExp - it is called twice per rendered row"
    )


def test_highlighting_never_emits_unescaped_institution_text():
    """Highlighting inserts HTML, so every piece of the name that reaches
    innerHTML must go through esc().

    This used to assert that mark() escaped the WHOLE string up front, which
    was the safest thing that also produced the entity-splice bug: the query is
    then matched against the escaped text, so a term containing `&` lands
    inside the `&amp;` escaping just produced. The invariant that actually
    matters is not the ordering - it is that no branch concatenates raw text.
    Verified against the real function: `<img src=x> College` searched for
    "img" renders `&lt;<mark>img</mark> src=x&gt; College`.
    """
    i = _JS.find("function mark(")
    body = _JS[i:_JS.find("function render()")]
    emitted = [ln.strip() for ln in body.splitlines()
               if "out +=" in ln or "return" in ln]
    assert emitted, "mark() body not found"
    for line in emitted:
        if "text" not in line:
            continue
        assert "esc(" in line, f"mark() emits unescaped text: {line}"


def test_scroll_into_view_is_keyboard_only():
    """scrollIntoView forces a synchronous layout; calling it on every render
    cost 35-60 ms per keystroke for a scroll already at the top."""
    assert "function setActive(i, scroll)" in _JS
    assert "if (scroll && i >= 0" in _JS
    assert "setActive(hits.length ? 0 : -1, false)" in _JS, (
        "render() must not scroll"
    )
    assert "setActive(next, true)" in _JS, "keyboard movement must scroll"


@pytest.mark.parametrize("key", ["ArrowDown", "ArrowUp", "Home", "End", "Escape", "Enter"])
def test_keyboard_key_is_handled(key):
    assert f"e.key === '{key}'" in _JS, f"{key} is not handled"


def test_active_row_is_tracked_with_aria_activedescendant():
    """Moving DOM focus into the list would stop typing from working."""
    assert "aria-activedescendant" in _JS
    assert "role='option'" in _JS
    html = picker.picker_html()
    assert "role='listbox'" in html
    assert "role='combobox'" in html
    assert "aria-live='polite'" in html, "the match count must be announced"


def test_closing_restores_focus_only_when_the_close_was_deliberate():
    """Focusing the trigger on EVERY close stole the caret out of the access
    token field a split second after every click into it - the field lit up,
    the document click handler ran, focus jumped to the trigger, and the token
    could not be typed at all. An outside click must leave focus where the user
    put it; Escape and taking a row must return it to the trigger."""
    assert "function setOpen(on, restoreFocus)" in _JS
    assert "if (restoreFocus && t)" in _JS, "focus restore must be conditional"
    # Closing an already-closed picker must be a true no-op: this runs on every
    # click anywhere on the page.
    assert "if (!on && !wasOpen) return;" in _JS

    deliberate = ["setOpen(false, true)"]          # pick(), Escape
    incidental = ["setOpen(false, false)"]         # outside click, Tab
    for frag in deliberate + incidental:
        assert frag in _JS, f"missing call form {frag}"
    # The outside-click branch specifically must not restore focus.
    i = _JS.find("if (!r.contains(t))")
    assert "setOpen(false, false)" in _JS[i:i + 80], (
        "an outside click must not pull focus back to the trigger"
    )


def test_domain_denylist_and_renames_are_applied():
    import sys
    sys.path.insert(0, str(_ROOT / "scripts"))
    from institution_rejects import REJECT_DOMAINS, RENAME

    shipped = {d for _n, d, _c in inst.DATA}
    leaked = sorted(set(REJECT_DOMAINS) & shipped)
    assert not leaked, f"denylisted domains shipped: {leaked}"

    by_domain = {d: n for n, d, _c in inst.DATA}
    for domain, label in RENAME.items():
        if domain in by_domain:
            assert by_domain[domain] == label, (
                f"{domain} shipped as {by_domain[domain]!r}, expected {label!r}"
            )


def test_no_secondary_school_slipped_in_under_a_college_name():
    """"College" is a SECONDARY school across much of AU/UK/IE. These are the
    exact accounts that reached a build before the denylist existed."""
    banned = ("riverview.instructure.com", "staloysius.instructure.com",
              "stscholastica.instructure.com", "sjccoomera.instructure.com")
    shipped = {d for _n, d, _c in inst.DATA}
    assert not (set(banned) & shipped)


def test_the_trigger_label_is_derived_from_the_url_field():
    """The URL field is the only truth; the picker just fills it.

    Storing the picked name separately let the two drift: clear the field after
    choosing a school and the picker still named a school the form no longer
    pointed at. Deriving it also handles the reverse - paste another known
    school's address by hand and the trigger follows.
    """
    assert "function syncTrigger()" in _JS
    # It must run wherever the URL field can change: paintStatus() is the hook
    # that fires on every keystroke, on pick and on mount.
    i = _JS.find("function paintStatus()")
    assert "syncTrigger();" in _JS[i:i + 400], "paintStatus must re-derive the trigger"
    # pick() must NOT set the label itself - that is what made it stored state.
    j = _JS.find("function pick(opt)")
    body = _JS[j:j + 400]
    assert "lbl.textContent" not in body, (
        "pick() must not write the label; deriving it is the whole fix"
    )


def test_the_default_label_comes_from_python_not_a_js_copy():
    """One source for the string, so the markup and the reset cannot disagree."""
    html = picker.picker_html()
    assert f"data-default-label='{picker.TRIGGER_LABEL}'" in html
    assert "{" not in html.split("data-rows")[0], "unrendered f-string braces in markup"
    assert picker.TRIGGER_LABEL not in _JS, (
        "the default label must be read off the element, not duplicated in JS"
    )


# ═══════════════════════════════════════════════════════════════════════════
# The wrong-university class (found in the shipped list, 2026-08-08)
# ═══════════════════════════════════════════════════════════════════════════
#
# Ten seeded rows pointed at a real, working Canvas belonging to a DIFFERENT
# university. That is the single most damaging thing this feature can do - a
# missing school costs one paste into the field right beside the picker, a
# wrong one hands a student someone else's login page with no hint that the
# address is the problem.
#
# Two independent defects produced them, and BOTH are pinned below, because
# fixing either alone leaves the list wrong:
#
#   1. `accepts()` scored SIMILARITY, and the deciding word is the one a
#      similarity score discards. "University of British Columbia" vs
#      "Columbia University" scores 0.667 and the domain corroborates the
#      shared token; `british` - the whole answer - is simply not counted.
#      Closed by `contradicts()`.
#
#   2. `corroborates()` built an institution's acronym from EVERY word, so
#      "University of Central Florida" produced `uocf`, never `ucf`. A school
#      whose Canvas host is its own acronym could not corroborate its own
#      domain, so the matcher passed over the RIGHT host and settled for a
#      wrong one that happened to corroborate. Closed by `acronyms()`.
#
# Defect 2 is why this is not merely a rejection problem: rejecting the wrong
# pairing without fixing corroboration would have dropped five real
# universities out of the list entirely.

_TRUE_OWNER = [
    # domain, the institution that actually owns it
    ("courseworks2.columbia.edu",         "Columbia University"),
    ("canvas.duke.edu",                   "Duke University"),
    ("canvas.colorado.edu",               "University of Colorado Boulder"),
    ("oklahomachristian.instructure.com", "Oklahoma Christian University"),
    ("centralstate.instructure.com",      "Central State University"),
    ("northpark.instructure.com",         "North Park University"),
    ("usaonline.southalabama.edu",        "University of South Alabama"),
    ("canvas.manchester.ac.uk",           "The University of Manchester"),
    ("western.instructure.com",           "Western Colorado University"),
    ("american.instructure.com",          "American University"),
    # Published itself correctly; `clean_name` promoted the campus tenant into
    # a claim on the whole system. Held by RENAME.
    ("instructure.charlotte.edu",         "University of North Carolina at Charlotte"),
]


@pytest.mark.parametrize("domain,owner", _TRUE_OWNER)
def test_domain_is_labelled_with_its_real_owner(domain, owner):
    row = next((r for r in inst.DATA if r[1] == domain), None)
    assert row is not None, f"{domain} vanished; it belongs to {owner}"
    assert row[0] == owner, (
        f"{domain} is labelled {row[0]!r} but belongs to {owner!r} - "
        "this is the wrong-university failure, not a cosmetic label"
    )


# The other half: the displaced schools must be present, at their OWN host.
# Without this the suite would pass on a list that simply deleted them.
_DISPLACED = [
    ("University of British Columbia", "canvas.ubc.ca"),
    ("Colorado State University",      "colostate.instructure.com"),
    ("Oklahoma State University",      "canvas.okstate.edu"),
    ("University of Central Florida",  "webcourses.ucf.edu"),
    ("University of North Texas",      "unt.instructure.com"),
]


@pytest.mark.parametrize("name,domain", _DISPLACED)
def test_displaced_school_is_back_on_its_own_host(name, domain):
    row = next((r for r in inst.DATA if r[0] == name), None)
    assert row is not None, f"{name} lost its entry entirely"
    assert row[1] == domain, f"{name} points at {row[1]}, not its own {domain}"


def test_no_two_institutions_share_a_domain():
    """One host, one school. A duplicate means a mispairing survived beside the
    real owner rather than replacing it."""
    seen = {}
    for name, domain, _cc in inst.DATA:
        assert domain not in seen, f"{domain} claimed by {seen[domain]!r} and {name!r}"
        seen[domain] = name


def test_no_institution_appears_twice():
    names = [n.lower() for n, _d, _c in inst.DATA]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f"duplicate institutions: {dupes}"


# ── Local-language display names ────────────────────────────────────────────
#
# A Dane types "Københavns", not "University of Copenhagen". The display form
# is `Local (English)` so both are searchable and an exchange student who only
# knows the English name still recognises the row.

_LOCAL_NAMED = [
    ("absalon.instructure.com", "Københavns Universitet", "University of Copenhagen"),
    ("canvas.kth.se", "Kungliga Tekniska högskolan", "KTH Royal Institute of Technology"),
    ("canvas.gu.se", "Göteborgs universitet", "University of Gothenburg"),
    ("helsinki.instructure.com", "Helsingin yliopisto", "University of Helsinki"),
    ("uit.instructure.com", "UiT Norges arktiske universitet", "UiT The Arctic University of Norway"),
    ("heidelberg.instructure.com", "Universität Heidelberg", "Heidelberg University"),
]


@pytest.mark.parametrize("domain,local,english", _LOCAL_NAMED)
def test_local_name_leads_and_english_is_kept(domain, local, english):
    row = next((r for r in inst.DATA if r[1] == domain), None)
    assert row is not None, f"{local} dropped out of the list"
    assert row[0] == f"{local} ({english})", row[0]


@pytest.mark.parametrize("domain,local,english", _LOCAL_NAMED)
def test_both_names_are_searchable(domain, local, english):
    """The whole point of carrying two names is that either one finds the row.

    Searched through the picker's own haystack, not a re-implementation of it -
    the bridge filters on exactly this string.
    """
    row = next(r for r in inst.DATA if r[1] == domain)
    blob = picker.search_blob(row).lower()
    for term in (local.split()[0].lower(), english.split()[-1].lower()):
        assert term in blob, f"{term!r} does not find {row[0]!r}"


def test_english_only_schools_keep_a_plain_name():
    """`Local (English)` must not be applied where there is no local name -
    "Harvard University (Harvard University)" would be absurd."""
    for domain in ("canvas.harvard.edu", "cbscanvas.instructure.com"):
        row = next((r for r in inst.DATA if r[1] == domain), None)
        if row is not None:
            assert "(" not in row[0], row[0]


# ═══════════════════════════════════════════════════════════════════════════
# The MATCHER itself (scripts/build_institution_list.py)
# ═══════════════════════════════════════════════════════════════════════════
#
# The data tests above pin the ten rows that were wrong. These pin the RULE, so
# a regeneration cannot reintroduce the class under a different pair of names.
# Loaded by path because scripts/ is tooling and not an importable package.

def _builder():
    import importlib.util
    p = Path(__file__).resolve().parents[1] / "scripts" / "build_institution_list.py"
    spec = importlib.util.spec_from_file_location("_bil", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# (seed, cc, domain, the account's self-declared name)
_MUST_REJECT = [
    # The ten that shipped. Account names are the finder's real ones.
    ("University of British Columbia", "CA", "courseworks2.columbia.edu", "Columbia University"),
    ("Duke Kunshan University", "CN", "canvas.duke.edu", "Duke University"),
    ("Colorado State University", "US", "canvas.colorado.edu", "University of Colorado Boulder - CU Boulder"),
    ("Oklahoma State University", "US", "oklahomachristian.instructure.com", "Oklahoma Christian University"),
    ("University of Central Florida", "US", "centralstate.instructure.com", "Central State University"),
    ("University of North Texas", "US", "northpark.instructure.com", "North Park University"),
    ("University of South Carolina", "US", "usaonline.southalabama.edu", "University of South Alabama"),
    ("Manchester Metropolitan University", "GB", "canvas.manchester.ac.uk", "The University of Manchester"),
    ("University of Western Australia", "AU", "western.instructure.com", "Western Colorado University"),
    ("American University in Dubai", "AE", "american.instructure.com", "American University"),
    # The classes CLAUDE.md records as already-learned, kept so a future
    # loosening of the vocabulary re-breaks them here first.
    ("Boston University", "US", "bc.instructure.com", "Boston College"),
    ("University of California Berkeley", "US", "berkeleycollege.instructure.com", "Berkeley College"),
    ("University of Florida", "US", "floridacollege.instructure.com", "Florida College"),
    ("KTH Royal Institute of Technology", "SE", "rmit.instructure.com", "RMIT University"),
    ("Korea University", "KR", "yamaha.instructure.com", "Yamaha Music Korea"),
    ("Cairo University", "EG", "aucegypt.instructure.com", "American University in Cairo"),
    ("Open University", "GB", "canvas.open.uts.edu.au", "UTS Open"),
]


@pytest.mark.parametrize("seed,cc,domain,name", _MUST_REJECT)
def test_matcher_refuses_a_different_institution(seed, cc, domain, name):
    assert not _builder().accepts(seed, cc, domain, name), (
        f"{seed!r} would be paired with {name!r} at {domain} - a different school"
    )


_MUST_ACCEPT = [
    # Identical or near-identical names.
    ("Copenhagen Business School", "DK", "cbscanvas.instructure.com", "Copenhagen Business School"),
    ("Stockholm University", "SE", "canvas.su.se", "Stockholm University"),
    ("Harvard University", "US", "canvas.harvard.edu", "Harvard University"),
    ("The University of Melbourne", "AU", "canvas.lms.unimelb.edu.au", "The University of Melbourne"),
    ("Erasmus University Rotterdam", "NL", "canvas.eur.nl", "Erasmus University of Rotterdam"),
    # Published as an alias or an acronym - `contradicts` must not read a
    # school's own short form as a rival school.
    ("University of Copenhagen", "DK", "absalon.instructure.com", "UCPH"),
    ("University of Copenhagen", "DK", "absalon.instructure.com", "Absalon"),
    ("KTH Royal Institute of Technology", "SE", "canvas.kth.se", "KTH"),
    ("Chalmers University of Technology", "SE", "canvas.chalmers.se", "Chalmers"),
    ("University of British Columbia", "CA", "canvas.ubc.ca", "UBC Canvas"),
    # Published in the local language: only reachable because LOCAL_NAMES is
    # fed to the matcher as a probe. Delete that wiring and these fail.
    ("University of Gothenburg", "SE", "canvas.gu.se", "Göteborgs Universitet"),
    ("UiT The Arctic University of Norway", "NO", "uit.instructure.com", "UiT Norges arktiske universitet"),
    ("University of Oslo", "NO", "uio.instructure.com", "Universitetet i Oslo"),
    # The five whose OWN host the old corroboration bug could not recognise.
    ("Colorado State University", "US", "colostate.instructure.com", "Colorado State University"),
    ("Oklahoma State University", "US", "canvas.okstate.edu", "Oklahoma State University"),
    ("University of Central Florida", "US", "webcourses.ucf.edu", "University of Central Florida"),
    ("University of North Texas", "US", "unt.instructure.com", "University of North Texas"),
    ("Duke University", "US", "canvas.duke.edu", "Duke University"),
]


@pytest.mark.parametrize("seed,cc,domain,name", _MUST_ACCEPT)
def test_matcher_still_accepts_a_genuine_pairing(seed, cc, domain, name):
    assert _builder().accepts(seed, cc, domain, name), (
        f"{seed!r} no longer matches its own Canvas {domain} ({name!r}) - "
        "the veto is over-strict and would drop this school from the list"
    )


def test_acronym_is_built_without_stopwords():
    """The specific defect: 'University of Central Florida' must yield `ucf`.

    Asserted directly because the symptom is silent - the school keeps an
    entry, just pointing at somebody else's Canvas.
    """
    acro = _builder().acronyms
    assert "ucf" in acro("University of Central Florida")
    assert "unt" in acro("University of North Texas")
    assert "ubc" in acro("University of British Columbia")


def test_local_names_are_offered_to_the_matcher():
    """LOCAL_NAMES has two jobs and the second one is invisible: it is what
    lets an English seed match a locally-named account. A display-only change
    would pass every rendering test and silently drop these schools."""
    b = _builder()
    assert b.local_probes("University of Gothenburg") == ["Göteborgs universitet"]
    assert b.local_probes("Harvard University") == []


def test_display_name_puts_the_local_name_first():
    b = _builder()
    assert b.display_name("University of Copenhagen") == \
        "Københavns Universitet (University of Copenhagen)"
    assert b.display_name("Harvard University") == "Harvard University"


def test_every_shipped_reject_pairing_stays_out_of_the_data():
    """The hand-review gate is only worth having if it is enforced."""
    import importlib.util
    p = Path(__file__).resolve().parents[1] / "scripts" / "institution_rejects.py"
    spec = importlib.util.spec_from_file_location("_rej", p)
    rej = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rej)
    by_domain = {d: n for n, d, _c in inst.DATA}
    for seed, domain in rej.REJECT.items():
        assert by_domain.get(domain) != seed, (
            f"{seed!r} is paired with {domain} despite being rejected"
        )
    for domain in rej.REJECT_DOMAINS:
        assert domain not in by_domain, f"{domain} is rejected outright but shipped"


# ── Escaping in the bridge ──────────────────────────────────────────────────
#
# Both of these are invisible in review and neither raises: one corrupts an
# attribute, the other corrupts the rendered name. Verified against the real
# functions in node while fixing them; asserted here on the source, so the
# suite needs no JS runtime.

def test_bridge_escaper_covers_attribute_quotes():
    """`render()` builds `data-u='https://...'`, so esc() is doing attribute
    duty. Escaping only `& < >` leaves an apostrophe free to close the
    attribute early."""
    body = _JS.split("function esc(", 1)[1].split("function ", 1)[0]
    for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert entity in body, f"esc() does not produce {entity}"


def test_highlight_matches_before_it_escapes():
    """Escaping first makes the query search the ESCAPED text, so a term
    containing `&` matches inside the `&amp;` escaping just produced and
    splices a <mark> into the middle of an entity."""
    body = _JS.split("function mark(", 1)[1].split("\n  function ", 1)[0]
    assert "re.exec(text)" in body, (
        "mark() must run the regex over the RAW text"
    )
    assert "esc(text)" not in body.split("if (!re)", 1)[1].split("\n", 1)[1], (
        "mark() escapes the whole string before matching - the entity-splice bug"
    )
    assert "re.lastIndex++" in body, (
        "a zero-width match would spin forever without the guard"
    )


# ── Accent folding ──────────────────────────────────────────────────────────
#
# Introduced BY the local-name change and found by driving the running app:
# every Nordic row became unreachable from a keyboard without its accents.
# `kobenhavn`, `goteborg`, `hogskolan`, `lulea`, `haskolinn` and `nurnberg` each
# matched zero rows - the exact students the local names were added for.

@pytest.mark.parametrize("raw,folded", [
    ("Københavns Universitet", "kobenhavns universitet"),
    ("Göteborgs universitet", "goteborgs universitet"),
    ("Háskólinn í Reykjavík", "haskolinn i reykjavik"),
    ("Technische Universität Nürnberg", "technische universitat nurnberg"),
    ("Luleå tekniska universitet", "luleaa tekniska universitet"),
    ("Universitatea Politehnica", "universitatea politehnica"),
])
def test_fold_writes_what_a_plain_keyboard_types(raw, folded):
    assert picker.fold(raw) == folded


def test_fold_handles_the_letters_nfkd_cannot():
    """`ø`, `æ` and `ß` are letters, not accented forms - NFKD leaves them be,
    so they need an explicit mapping or folding silently does nothing."""
    import unicodedata
    for ch in ("ø", "æ", "ß"):
        stripped = "".join(c for c in unicodedata.normalize("NFKD", ch)
                           if not unicodedata.combining(c))
        assert stripped == ch, f"NFKD unexpectedly decomposes {ch!r}"
        assert picker.fold(ch) != ch, f"fold() leaves {ch!r} untouched"


_UNACCENTED_QUERIES = [
    ("kobenhavn", "absalon.instructure.com"),
    ("goteborg", "canvas.gu.se"),
    ("hogskolan", "canvas.du.se"),
    ("lulea", "canvas.ltu.se"),
    ("haskolinn", "reykjavik.instructure.com"),
    ("nurnberg", "canvas.utn.de"),
]


@pytest.mark.parametrize("query,domain", _UNACCENTED_QUERIES)
def test_a_keyboard_without_the_accents_still_finds_the_school(query, domain):
    """Searched through the real haystack - this is the string the bridge
    substring-matches, so a pass here is a pass in the app."""
    row = next((r for r in inst.DATA if r[1] == domain), None)
    assert row is not None, f"{domain} not in the list"
    assert query in picker.search_blob(row).lower(), (
        f"{query!r} cannot find {row[0]!r}"
    )


@pytest.mark.parametrize("query,domain", [
    ("københavn", "absalon.instructure.com"),
    ("göteborg", "canvas.gu.se"),
])
def test_the_accented_spelling_keeps_working(query, domain):
    """Folding must ADD a spelling, never replace one."""
    row = next(r for r in inst.DATA if r[1] == domain)
    assert query in picker.search_blob(row).lower()


def test_folding_only_adds_a_copy_where_it_changes_something():
    """An ASCII-only row must not carry a duplicate of itself - 1,797 rows go
    into one attribute and the payload is re-parsed on every rerun."""
    row = next(r for r in inst.DATA if r[1] == "canvas.harvard.edu")
    blob = picker.search_blob(row)
    assert blob.lower().count("harvard") == blob.count("harvard"), blob
    assert blob == f"{inst.search_blob(row)} {picker.COUNTRY_NAMES.get(row[2], '')}".strip()
