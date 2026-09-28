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


def test_the_waiting_card_names_the_way_out(monkeypatch):
    monkeypatch.setattr(auth, "st", type("S", (), {"session_state": {}})())
    html = auth._browser_notice_html("handoff")
    assert auth.HANDOFF_STOP_LABEL in html


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
