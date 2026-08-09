"""The course-action gate must be painted by a stylesheet that ships with the page.

`_gate_actions_on_selection` greys the two primary actions while no course is
selected. It used to build its own `<style>` element from inside the
`components.html` bridge, which meant the rule did not exist until that iframe
had loaded and executed - so on a cold load the buttons rendered at full
brightness and only then went dim. Reported 2026-08-09 on a slow machine.

The rules now live in styles/global.css, which goes out with the page. Two
things have to stay true, and neither is visible in review:

  * every key the call site passes is actually covered there - a missing key is
    silent, the button just stays bright and clickable;
  * the bridge does not start creating a stylesheet again.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "ui" / "course_selector.py"
GLOBAL_CSS = ROOT / "styles" / "global.css"

GATE_SELECTOR_PREFIX = 'body:not([data-cd-has-sel="1"])'


def _gate_call_keys() -> list[str]:
    """Every string literal passed to `_gate_actions_on_selection(...)`."""
    tree = ast.parse(SELECTOR.read_text(encoding="utf-8"))
    keys: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Name) and fn.id == "_gate_actions_on_selection"):
            continue
        for arg in node.args:
            assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
                "a non-literal key cannot be checked against the stylesheet; "
                "keep the call site literal"
            )
            keys.append(arg.value.lower())
    return keys


def test_call_site_exists_and_is_literal():
    keys = _gate_call_keys()
    assert keys, "no _gate_actions_on_selection call found - has it been renamed?"


def test_every_gated_key_has_a_rule_in_global_css():
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    gate_rules = [ln for ln in css.splitlines() if GATE_SELECTOR_PREFIX in ln]
    assert gate_rules, "the gate's stylesheet is missing from global.css entirely"

    for key in _gate_call_keys():
        # Both halves matter: the button rule is the paint, the wrapper rule is
        # what lets the blocked-reason tooltip resolve at all.
        button = [ln for ln in gate_rules
                  if f'st-key-{key}"] button' in ln]
        wrapper = [ln for ln in gate_rules
                   if re.search(rf'st-key-{re.escape(key)}"\]\s*[,{{]\s*$', ln)]
        assert button, f"no disabled-paint rule in global.css for key {key!r}"
        assert wrapper, f"no wrapper (cursor/title) rule in global.css for key {key!r}"


def test_bridge_does_not_create_its_own_stylesheet():
    """The whole point of the move: the paint must not wait on the iframe."""
    src = SELECTOR.read_text(encoding="utf-8")
    start = src.index("def _gate_actions_on_selection")
    end = src.index("\ndef ", start + 1)
    body = src[start:end]
    for banned in ("createElement('style')", 'createElement("style")', "textContent ="):
        assert banned not in body, (
            f"the gate bridge builds a stylesheet again ({banned!r}); that rule "
            "cannot exist before the iframe runs, which is the bug this guards"
        )
