"""The extension card's button stops a wait it started (2026-09-28).

Product owner: once "Sign in with the extension" was pressed there was no way
to stop the app listening - the wait ran its whole window with nothing on
screen that ended it. The same button now reads "Stop waiting" while a handoff
is in flight, and pressing it tears the attempt down through
`cancel_browser_handoff`, the teardown logout and a finished sign-in already
use.

ONE slot in both states, because Streamlit reconciles by position: a second,
conditional Stop button would hand every element below it its neighbour's DOM
node the moment a handoff started.

Read from the AST, never the text - a comment naming either function would
satisfy a substring test, which has kept six guards in this repo green.
"""
from __future__ import annotations

import ast
from pathlib import Path

import ui.auth as auth

_SRC = (Path(__file__).resolve().parent.parent / "ui" / "auth.py").read_text(
    encoding="utf-8")


def _login_page():
    tree = ast.parse(_SRC)
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "render_login_page")


def _handoff_button(fn):
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call)
             and ast.unparse(n.func).endswith("form_submit_button")
             and any(k.arg == "key" and isinstance(k.value, ast.Constant)
                     and k.value.value == "login_handoff_btn" for k in n.keywords)]
    assert len(calls) == 1, f"expected ONE handoff button slot, found {len(calls)}"
    return calls[0]


def test_the_labels_are_short_and_distinct():
    assert auth.HANDOFF_START_LABEL != auth.HANDOFF_STOP_LABEL
    # The old label was 32 characters; the brief was "shorter".
    assert len(auth.HANDOFF_START_LABEL) < len("Use the Canvas tab in my browser")


def test_the_ONE_button_changes_its_label_while_waiting():
    fn = _login_page()
    label = _handoff_button(fn).args[0]
    assert isinstance(label, ast.IfExp), (
        f"the label is fixed again: {ast.unparse(label)}")
    assert ast.unparse(label.body) == "HANDOFF_STOP_LABEL"
    assert ast.unparse(label.orelse) == "HANDOFF_START_LABEL"
    # ...and the condition is the waiting flag, not something that merely
    # sounds like it.
    test_src = ast.unparse(label.test)
    assign = next(
        n for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == test_src for t in n.targets))
    assert "'handoff_waiting'" in ast.unparse(assign.value), ast.unparse(assign)


def _branches(fn):
    """Every `if _handoff_clicked and ...:` with its body's call names."""
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and "_handoff_clicked" in ast.unparse(node.test):
            calls = {ast.unparse(c.func) for s in node.body
                     for c in ast.walk(s) if isinstance(c, ast.Call)}
            out.append((ast.unparse(node.test), calls))
    return out


def test_pressing_it_while_waiting_STOPS_and_does_not_restart():
    branches = _branches(_login_page())
    stop = [c for t, c in branches if "not " not in t]
    start = [c for t, c in branches if "not " in t]
    assert len(stop) == 1 and len(start) == 1, branches
    assert "cancel_browser_handoff" in stop[0], stop
    assert "begin_browser_handoff" not in stop[0], (
        "Stop waiting re-armed the listener instead of stopping it")
    assert "begin_browser_handoff" in start[0], start
    assert "cancel_browser_handoff" not in start[0], start


def test_the_waiting_status_sits_DIRECTLY_above_the_way_out():
    """The status used to live above the form and had to NAME the Stop button,
    because the button sat in another card. Since 2026-11-23 the status is in
    the extension card, rendered immediately before the button that ends the
    wait, so the way out is the next thing on screen."""
    fn = _login_page()
    status = stop = None
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Name) and n.func.id == "_handoff_card_html":
            status = n.lineno
        if any(k.arg == "key" and isinstance(k.value, ast.Constant)
               and k.value.value == "login_handoff_btn" for k in n.keywords):
            stop = n.lineno
    assert status and stop, (status, stop)
    assert status < stop, "the live status renders below the Stop button"
    assert auth.HANDOFF_STOP_LABEL == "Stop waiting"


def test_the_store_link_is_QUIETER_than_the_sign_in_button():
    """Product owner, 2026-09-28: a solid full-width "Get the extension" above
    a tinted "Sign in with the extension" put the weights upside down. The
    install happens once; the sign-in is the action."""
    import re
    sel = 'div[class*="st-key-login_card_wrapper_"] .login-ext-btn {'
    i = _SRC.index(sel)
    block = _SRC[i:_SRC.index("}", i)]
    assert re.search(r"(?<![-\w])width: auto", block), block
    assert not re.search(r"(?<![-\w])width: 100%", block), block
    assert "background-color: transparent" in block, block


def test_the_store_link_comes_BEFORE_the_steps():
    """Step 1 is "add it", so the way to add it opens the card."""
    fn = _login_page()
    lines = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id in ("_extension_cta_html", "_extension_guide_html"):
            lines[n.func.id] = n.lineno
    assert lines["_extension_cta_html"] < lines["_extension_guide_html"], lines


def test_the_extension_card_links_to_the_store():
    assert auth.EXTENSION_STORE_URL.startswith("https://chromewebstore.google.com/")
    html = auth._extension_cta_html()
    assert f"href='{auth.EXTENSION_STORE_URL}'" in html
    assert "Not in the Chrome store yet" not in html


# ---------------------------------------------------------------------------
# The store link can be put away (product owner, 2026-11-23)
# ---------------------------------------------------------------------------

def _cta_row(fn):
    """The `with st.container(key="login_ext_cta_row")` block."""
    for n in ast.walk(fn):
        if not isinstance(n, ast.With):
            continue
        for item in n.items:
            c = item.context_expr
            if isinstance(c, ast.Call) and any(
                    k.arg == "key" and isinstance(k.value, ast.Constant)
                    and k.value.value == "login_ext_cta_row" for k in c.keywords):
                return n
    raise AssertionError("the store link row is gone")


def test_the_link_row_holds_BOTH_children_in_EVERY_state():
    """Streamlit reconciles by position, so the link and its toggle are both
    rendered whatever the state; only their CONTENT changes. A conditional
    child here would hand the steps below the toggle's DOM node."""
    row = _cta_row(_login_page())
    assert all(isinstance(s, ast.Expr) for s in row.body), (
        "something in the link row is conditional")
    calls = [ast.unparse(s.value.func) for s in row.body]
    assert calls == ["st.markdown", "st.form_submit_button"], calls
    toggle = row.body[1].value
    keys = {k.arg: k.value for k in toggle.keywords}
    assert ast.unparse(keys["on_click"]) == "_toggle_extension_link"
    assert keys["key"].value == "login_ext_link_toggle"


def test_a_HIDDEN_link_renders_no_link_and_a_shown_one_does():
    shown = auth._extension_cta_html(hidden=False)
    hidden = auth._extension_cta_html(hidden=True)
    assert "href=" in shown
    assert "href=" not in hidden
    # EMPTY, so the CSS that collapses it can match it.
    assert hidden == "<div class='login-ext-cta'></div>"


class _St:
    def __init__(self, state=None):
        self.session_state = dict(state or {})


def test_the_link_is_SHOWN_when_the_settings_cannot_be_read(monkeypatch):
    """Wrong one way costs a link on screen; wrong the other way hides the
    only route to installing the extension."""
    monkeypatch.setattr(auth, "st", _St())

    def boom():
        raise OSError("locked")
    monkeypatch.setattr(auth, "read_config_for_update", boom)
    assert auth._extension_link_hidden() is False


def test_hiding_is_REMEMBERED_in_the_settings(monkeypatch):
    monkeypatch.setattr(auth, "st", _St({"_ext_link_hidden": False}))
    written = []
    monkeypatch.setattr(auth, "read_config_for_update",
                        lambda: ({"keep": 1}, True))
    monkeypatch.setattr(auth, "write_config_atomically",
                        lambda c: written.append(dict(c)) or True)
    auth._toggle_extension_link()
    assert auth.st.session_state["_ext_link_hidden"] is True
    assert written == [{"keep": 1, auth.EXT_LINK_HIDDEN_KEY: True}], (
        "the choice was not saved, or the rest of the settings were dropped")
    auth._toggle_extension_link()
    assert written[-1][auth.EXT_LINK_HIDDEN_KEY] is False


def test_an_UNREADABLE_settings_file_is_never_overwritten(monkeypatch):
    """`may_write=False` means a transient read failure: writing then would
    replace every other setting with this one key."""
    monkeypatch.setattr(auth, "st", _St({"_ext_link_hidden": False}))
    written = []
    monkeypatch.setattr(auth, "read_config_for_update", lambda: ({}, False))
    monkeypatch.setattr(auth, "write_config_atomically",
                        lambda c: written.append(c) or True)
    auth._toggle_extension_link()
    assert written == []
    # The screen still follows the click.
    assert auth.st.session_state["_ext_link_hidden"] is True


def test_the_toggle_CSS_selects_its_state_off_the_EMPTY_link():
    """The open-eye glyph for "Show extension link" is chosen from the empty
    link beside it, so the selector and the hidden markup must agree."""
    assert ('div[class*="st-key-login_ext_cta_row"]:has(.login-ext-cta:empty)'
            in _SRC)
