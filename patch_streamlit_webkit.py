"""
patch_streamlit_webkit.py
=========================

Strip JavaScript *lookbehind* assertions ``(?<=...)`` / ``(?<!...)`` out of the
bundled Streamlit frontend so the app renders on older WebKit.

Why this exists
---------------
On macOS, pywebview renders the Streamlit UI inside ``WKWebView`` - the system
WebKit, whose JavaScript engine version tracks the *installed Safari version*.
JavaScriptCore only learned regex lookbehind in **Safari 16.4** (macOS Ventura
13.3, March 2023). On any earlier system (macOS 13.0-13.2, Monterey, ...) the
engine throws::

    SyntaxError: Invalid regular expression: invalid group specifier name

Streamlit 1.51's markdown pipeline builds exactly such a regex at runtime - the
GFM autolink-literal transform does::

    new RegExp("(?<=^|\\s|\\p{P}|\\p{S})([-.\\w+]+)@([-\\w]+(?:\\.[-\\w]+)+)","gu")

Because the assertion lives inside a *runtime string* (``new RegExp("...")``),
no bundler/transpiler can ever downlevel it - it must be patched in the shipped
JS. The error is thrown during React's markdown render, so the error boundary
replaces *every* markdown element with an error card, breaking the whole UI.

What it does
------------
Walks ``streamlit/static/static/js/*.js`` and removes every ``(?<=...)`` and
``(?<!...)`` assertion. Lookbehind assertions are **zero-width and
non-capturing**, so deleting them never shifts capture-group indices ($1/$2)
and only loosens matching at a boundary (e.g. an email autolink may match one
char too eagerly to its left). That is cosmetic; the app no longer crashes.
Named groups ``(?<name>...)`` are intentionally left untouched.

The scanner is brace/escape/char-class aware so it survives minified code and
nested groups, and it is idempotent (a second run finds nothing to do).

Run this AFTER ``pip install`` and BEFORE PyInstaller collects Streamlit. It is
invoked automatically from both .spec files; it can also be run standalone:

    python patch_streamlit_webkit.py
"""
from __future__ import annotations

import glob
import os
import sys


def _strip_lookbehind(src: str) -> tuple[str, int]:
    """Return (patched_src, num_assertions_removed).

    Removes each ``(?<=`` / ``(?<!`` group, scanning to its matching ``)`` while
    respecting backslash escapes, character classes ``[...]`` and nested groups.
    """
    out: list[str] = []
    i = 0
    n = len(src)
    removed = 0
    while i < n:
        if src.startswith("(?<=", i) or src.startswith("(?<!", i):
            # Scan from just past the "(?<=" / "(?<!" to the matching ')'.
            j = i + 4
            depth = 1
            in_class = False
            while j < n and depth > 0:
                c = src[j]
                if c == "\\":            # escape: skip the escaped char
                    j += 2
                    continue
                if in_class:
                    if c == "]":
                        in_class = False
                elif c == "[":
                    in_class = True
                elif c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                j += 1
            # j now points just past the assertion's closing ')'. Drop it all.
            removed += 1
            i = j
            continue
        out.append(src[i])
        i += 1
    return "".join(out), removed


def _streamlit_js_dir() -> str:
    import streamlit  # noqa: WPS433 (deliberately lazy - only when patching)

    return os.path.join(os.path.dirname(streamlit.__file__), "static", "static", "js")


def patch() -> int:
    """Patch all Streamlit JS bundles in place. Returns assertions removed."""
    js_dir = _streamlit_js_dir()
    if not os.path.isdir(js_dir):
        print(f"[patch_streamlit_webkit] js dir not found: {js_dir} - skipping")
        return 0

    total = 0
    for path in glob.glob(os.path.join(js_dir, "*.js")):
        try:
            text = open(path, "r", encoding="utf-8").read()
        except (OSError, UnicodeDecodeError) as exc:
            print(f"[patch_streamlit_webkit] skip {os.path.basename(path)}: {exc}")
            continue
        if "(?<=" not in text and "(?<!" not in text:
            continue
        patched, removed = _strip_lookbehind(text)
        if removed:
            open(path, "w", encoding="utf-8").write(patched)
            total += removed
            print(f"[patch_streamlit_webkit] {os.path.basename(path)}: removed {removed} lookbehind assertion(s)")

    # Verify nothing was missed (would indicate a scanner bug on a future bundle).
    leftover = 0
    for path in glob.glob(os.path.join(js_dir, "*.js")):
        try:
            text = open(path, "r", encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        if "(?<=" in text or "(?<!" in text:
            leftover += 1
            print(f"[patch_streamlit_webkit] WARNING: lookbehind still present in {os.path.basename(path)}")
    if leftover:
        raise RuntimeError(
            f"patch_streamlit_webkit: {leftover} file(s) still contain lookbehind after patching"
        )

    print(f"[patch_streamlit_webkit] done - {total} assertion(s) removed total")
    return total


if __name__ == "__main__":
    try:
        patch()
    except Exception as exc:  # noqa: BLE001 - surface a clear CI failure
        print(f"[patch_streamlit_webkit] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
