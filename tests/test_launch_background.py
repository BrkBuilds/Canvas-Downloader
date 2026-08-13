"""The launch background: one colour, two surfaces, and no white in between.

`fp:66b3e213c23d` - a cold launch showed a full-screen WHITE frame before the
dark splash. MEASURED on macOS 26.6 against the packaged app, screen recorded
at ~57 fps with the window interior's luminance read per frame:

    t=1.767s  lum  29.6   window on screen, NSWindow background correct
    t=1.817s  lum 249.2   <- WHITE, 5 frames / 87 ms
    t=1.900s  lum  30.5   the dark splash paints

`background_color` was never the problem: pywebview applies it to the NSWindow
and it works. The WKWebView is opaque, has no content yet, and paints its own
white over it.

THESE TESTS RUN ON EVERY PLATFORM, because the thing most likely to break the
fix is not macOS - it is an edit to `start.py` that moves the call or the
constant. One did: an earlier automated insertion put a column-0 `def` INSIDE
the `if __name__` block, which silently made the entire launcher - `webview.start()`
included - the body of an uncalled function. `ast.parse` passed. The app
launched, exited 0, and printed nothing.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SRC = (REPO / "start.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)


def _module_functions() -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in TREE.body if isinstance(n, ast.FunctionDef)}


def _entry_block() -> ast.If:
    """The `if __name__ == "__main__":` block."""
    for node in TREE.body:
        if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test):
            return node
    raise AssertionError("start.py has no `if __name__` entry block")


# --------------------------------------------------------------------------
# the structural guard the broken edit would have failed
# --------------------------------------------------------------------------

def test_the_launcher_still_lives_inside_the_entry_block():
    """`webview.start()` must be REACHED, not merely present.

    The broken edit left it inside a module-level function nobody calls, which
    is invisible to a syntax check and to grep - the call was still there, on
    the same line, spelled the same way.
    """
    block = _entry_block()
    starts = [n for n in ast.walk(block)
              if isinstance(n, ast.Call) and "webview.start" in ast.unparse(n.func)]
    assert starts, ("webview.start() is not inside `if __name__ == \"__main__\"` - "
                    "the launcher is unreachable")


def test_no_module_level_function_swallows_the_entry_block():
    """A column-0 `def` written into the middle of the entry block ENDS it and
    absorbs everything after. Nothing at module level may overlap it."""
    block = _entry_block()
    for name, fn in _module_functions().items():
        overlaps = not (fn.end_lineno < block.lineno or fn.lineno > block.end_lineno)
        assert not overlaps, (
            f"module-level function {name!r} (lines {fn.lineno}-{fn.end_lineno}) "
            f"overlaps the entry block ({block.lineno}-{block.end_lineno}) - "
            f"it has swallowed the launcher")


# --------------------------------------------------------------------------
# one colour, two surfaces
# --------------------------------------------------------------------------

def test_the_background_hex_is_written_exactly_once():
    """The NSWindow colour and the web view's under-page colour must agree; a
    second literal is how they drift apart, which IS the flash."""
    import re
    hexes = re.findall(r"#0d1117", SRC, flags=re.I)
    # one definition, plus any number of mentions inside comments/docstrings
    code = "\n".join(
        ln for ln in SRC.splitlines()
        if not ln.lstrip().startswith("#"))
    assert code.count("'#0d1117'") + code.count('"#0d1117"') == 1, (
        f"the launch background hex appears as a literal more than once "
        f"({hexes.__len__()} textual occurrences); it must come from _LAUNCH_BG")


def test_the_window_takes_its_colour_from_the_constant():
    block = _entry_block()
    for n in ast.walk(block):
        if isinstance(n, ast.Call) and "create_window" in ast.unparse(n.func):
            kw = {k.arg: ast.unparse(k.value) for k in n.keywords}
            assert kw.get("background_color") == "_LAUNCH_BG", (
                f"create_window must use _LAUNCH_BG, got "
                f"{kw.get('background_color')!r}")
            return
    raise AssertionError("no create_window call found in the entry block")


# --------------------------------------------------------------------------
# the fix itself
# --------------------------------------------------------------------------

def test_the_webview_background_is_applied_before_the_gui_starts():
    """It patches `BrowserView.__init__`, and the window is not shown until
    `first_show()` - so the call has to happen before `webview.start()`."""
    block = _entry_block()
    src = ast.unparse(block)
    i_fix = src.find("_match_macos_webview_background()")
    i_start = src.find("webview.start")
    assert i_fix != -1, "the web-view background fix is never called"
    assert i_fix < i_start, (
        "it must run BEFORE webview.start() - afterwards the window exists and "
        "the flash has already happened")


def _code_of(name: str) -> str:
    """A function's code with its DOCSTRING removed.

    The docstring names the APIs it warns against, so scanning the whole
    function reports the warning as a violation - this test failed against
    correct code until it stripped it. Same reason verify_architecture.py
    blanks comments before its rules run.
    """
    fn = _module_functions()[name]
    return "\n".join(ast.unparse(s) for s in fn.body
                     if not (isinstance(s, ast.Expr)
                             and isinstance(s.value, ast.Constant)
                             and isinstance(s.value.value, str)))


def test_it_turns_the_web_views_own_background_OFF():
    """The only thing measured to work.

    Three candidates were driven from source against the same trace:

        (none - baseline)                          max luma 253.0, 3 white frames
        setUnderPageBackgroundColor_ (public API)  max luma 253.0, 3 white frames
        drawsBackground = False                    max luma  25.0, 0 white frames

    The public API is NOT shipped because it demonstrably does not fix this: it
    colours the area BEYOND the page, and what is painted here is the view's own
    background before any document exists.
    """
    body = _code_of("_match_macos_webview_background")
    assert "'drawsBackground'" in body or '"drawsBackground"' in body
    assert "setUnderPageBackgroundColor_" not in body, (
        "measured to change nothing here - shipping it would imply it does")


def test_nothing_stands_between_the_platform_gate_and_the_patch():
    """No colour parse, no extra import, no third `return False`.

    The function shipped with a leftover r/g/b parse of `_LAUNCH_BG` and an
    `import AppKit`, both from the `setUnderPageBackgroundColor_` candidate that
    was measured NOT to fix this and dropped. They were dead - `drawsBackground
    = False` needs no colour - but not harmlessly dead: each sat in front of the
    patch behind its own `return False`, so an AppKit import failure, or a
    `_LAUNCH_BG` this parse did not accept, would have disabled the fix in the
    PACKAGED APP (the only place it matters) for a reason unrelated to anything
    the function does.

    Turning the view's painting off is what makes the NSWindow's colour show, so
    the two surfaces agree by construction rather than by holding the same hex
    twice - which is also what `test_the_background_hex_is_written_exactly_once`
    is protecting from the other side.
    """
    body = _code_of("_match_macos_webview_background")
    assert "int(" not in body, (
        "a colour is being parsed again - `drawsBackground = False` uses none, "
        "and a parse that can fail is a new way to silently skip the fix")
    assert "AppKit" not in body, "AppKit is not needed to turn the background off"
    fn = _module_functions()["_match_macos_webview_background"]
    returns = [n for n in fn.body if isinstance(n, ast.Return)] + [
        n for s in fn.body if isinstance(s, (ast.If, ast.Try))
        for n in ast.walk(s) if isinstance(n, ast.Return)]
    falses = [n for n in returns
              if isinstance(n.value, ast.Constant) and n.value.value is False]
    assert len(falses) == 2, (
        f"expected exactly two ways to decline - not macOS, and no Cocoa "
        f"backend - found {len(falses)}; every extra one is another way the "
        f"fix silently does not run")


def test_the_deprecated_key_is_not_used():
    """`setValue_forKey_(True, 'drawsTransparentBackground')` is what pywebview
    does for `transparent=True`. Probed on macOS 26.6 it makes the system log
    "-[WKWebView _setDrawsTransparentBackground:] is deprecated and should not
    be used", and pywebview only reaches it together with setOpaque_(False) and
    no window shadow - three changes to buy one."""
    assert "drawsTransparentBackground" not in _code_of(
        "_match_macos_webview_background")


def test_it_is_a_no_op_off_macos():
    """Windows must be untouched by a macOS cosmetic fix."""
    import start
    if sys.platform != "darwin":
        assert start._match_macos_webview_background() is False
    fn = _module_functions()["_match_macos_webview_background"]
    first = fn.body[1] if isinstance(fn.body[0], ast.Expr) else fn.body[0]
    assert isinstance(first, ast.If) and "darwin" in ast.unparse(first.test), (
        "the platform gate must be the first thing it does, before any import")


def test_it_can_never_stop_the_window_being_created():
    """A cosmetic improvement that can raise is worse than the flash."""
    fn = _module_functions()["_match_macos_webview_background"]
    inner = next(n for n in ast.walk(fn)
                 if isinstance(n, ast.FunctionDef) and n.name == "_init")
    tries = [n for n in inner.body if isinstance(n, ast.Try)]
    assert tries, "the colour assignment must be guarded"
    handlers = [h for t in tries for h in t.handlers]
    assert handlers and all(
        h.type is None or "Exception" in ast.unparse(h.type) for h in handlers)
    # ...and the ORIGINAL __init__ must run first, outside that guard.
    assert isinstance(inner.body[0], ast.Expr) and "original" in ast.unparse(inner.body[0]), (
        "the real BrowserView.__init__ must run first and unguarded - wrapping "
        "it would let a cosmetic failure destroy the window")


def test_patching_twice_is_harmless():
    """`webview.start()` can be reached more than once across a retry, and a
    double wrap would call the original twice."""
    fn = _module_functions()["_match_macos_webview_background"]
    body = ast.unparse(fn)
    assert "_cd_bg_patched" in body, "the patch must be idempotent"
