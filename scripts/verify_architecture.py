#!/usr/bin/env python3
"""
Canvas Downloader - Architecture Verification Script
=====================================================
Scans ui/, sync/, engine/, core/, and root .py files for violations of
the architectural rules documented in CLAUDE.md.

Usage:
    python scripts/verify_architecture.py
    python scripts/verify_architecture.py --fail-on-error   # exits 1 if violations found
    python scripts/verify_architecture.py --no-color        # plain output

Suppression:
    Add  # audit-ignore  on the flagged line or the line immediately before it
    to suppress a specific violation from the exit code and output.

Rules enforced:
    1. st.rerun() inside @st.dialog missing scope="app"
    2. open() calls missing encoding='utf-8' (text mode only)
    3. Bare except: or except BaseException:
    4. Variables interpolated into unsafe_allow_html=True not wrapped in esc()
    5. F-string <style> injections containing unescaped single CSS braces
    6. CSS selectors naming a testid Streamlit 1.51 no longer renders
    7. Literal HTML tags inside an st.html(<style>) block / closing style tag in .css
    8. Hex colours within 1.0 CIEDE2000 of a shared/theme.py token (palette drift)

Rules 6 and 8 blank comments before scanning: a retired selector or a ramp's hex
quoted in a comment to explain the design is documentation, not a violation.
"""

import ast
import re
import sys
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Root of the project - resolved relative to this script's location
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Directories to scan recursively
SCAN_DIRS = ["ui", "sync", "engine", "core", "converters", "shared"]

# Extra individual root-level .py files (or all root .py files)
SCAN_ROOT_PY = True  # scan all *.py in PROJECT_ROOT (non-recursive)

# Directories / patterns to always exclude
EXCLUDE_DIRS = {"styles", "scripts", ".venv", "venv", "__pycache__", ".git", "build", "dist"}

# ---------------------------------------------------------------------------
# ANSI color helpers
# ---------------------------------------------------------------------------

USE_COLOR = sys.stdout.isatty() and "--no-color" not in sys.argv

def _c(code: str, text: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

RED     = lambda t: _c("31", t)
YELLOW  = lambda t: _c("33", t)
CYAN    = lambda t: _c("36", t)
BOLD    = lambda t: _c("1", t)
DIM     = lambda t: _c("2", t)
GREEN   = lambda t: _c("32", t)

# ---------------------------------------------------------------------------
# Violation dataclass
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    filepath: Path
    lineno: int
    rule: int
    message: str
    note: str = ""          # e.g. "[COMPAT_FALLBACK?]" or "[THEME_CONST?]"
    suppressed: bool = False

# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def collect_files() -> list[Path]:
    files: list[Path] = []

    # Scan configured subdirectories
    for dir_name in SCAN_DIRS:
        d = PROJECT_ROOT / dir_name
        if d.is_dir():
            for p in sorted(d.rglob("*.py")):
                if not any(ex in p.parts for ex in EXCLUDE_DIRS):
                    files.append(p)

    # Scan root .py files (non-recursive)
    if SCAN_ROOT_PY:
        for p in sorted(PROJECT_ROOT.glob("*.py")):
            if p.name != "__init__.py":
                files.append(p)

    # Deduplicate while preserving order
    seen = set()
    result = []
    for f in files:
        if f not in seen:
            seen.add(f)
            result.append(f)
    return result

# ---------------------------------------------------------------------------
# Suppression helpers
# ---------------------------------------------------------------------------

def build_suppressed_lines(source_lines: list[str]) -> set[int]:
    """Return 1-indexed line numbers that carry or are preceded by # audit-ignore."""
    suppressed = set()
    for i, line in enumerate(source_lines):
        if "# audit-ignore" in line:
            # Suppress this line AND the next line (so placing # audit-ignore
            # above a flagged line works too)
            suppressed.add(i + 1)   # 1-indexed: this line
            suppressed.add(i + 2)   # 1-indexed: next line
    return suppressed

# ---------------------------------------------------------------------------
# Rule 1: st.rerun() inside @st.dialog missing scope="app"
# ---------------------------------------------------------------------------

def _is_st_dialog_decorator(decorator) -> bool:
    """Return True if a decorator node looks like @st.dialog(...)."""
    # @st.dialog  (no call)
    if isinstance(decorator, ast.Attribute) and decorator.attr == "dialog":
        return True
    # @st.dialog(...)
    if isinstance(decorator, ast.Call):
        func = decorator.func
        if isinstance(func, ast.Attribute) and func.attr == "dialog":
            return True
        # bare @dialog(...)
        if isinstance(func, ast.Name) and func.id == "dialog":
            return True
    return False


def _is_st_rerun_call(node) -> bool:
    """Return True if node is a Call to st.rerun() or rerun()."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "rerun":
        return True
    if isinstance(func, ast.Name) and func.id == "rerun":
        return True
    return False


def _has_scope_app(call: ast.Call) -> bool:
    """Return True if the call has scope='app' or scope="app" keyword."""
    for kw in call.keywords:
        if kw.arg == "scope" and isinstance(kw.value, ast.Constant) and kw.value.value == "app":
            return True
    return False


def _collect_reruns_in_body(body) -> list[ast.Call]:
    """Walk a function body and return all st.rerun() Call nodes."""
    reruns = []
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if _is_st_rerun_call(node):
            reruns.append(node)
    return reruns


def check_dialog_reruns(tree: ast.AST, filepath: Path, suppressed: set[int]) -> list[Violation]:
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_is_st_dialog_decorator(d) for d in node.decorator_list):
            continue
        # This function is decorated with @st.dialog
        for rerun_call in _collect_reruns_in_body(node.body):
            if _has_scope_app(rerun_call):
                continue
            lineno = rerun_call.lineno

            # Detect compat-fallback pattern: inside an except block of a Try
            # where the try branch calls st.rerun(scope="app")
            note = ""
            # Walk the function body looking for Try nodes that contain this call
            for stmt in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if isinstance(stmt, ast.Try):
                    # Check if try body has scope="app" and handlers have bare rerun
                    try_reruns = _collect_reruns_in_body(stmt.body)
                    handler_reruns = []
                    for handler in stmt.handlers:
                        handler_reruns.extend(_collect_reruns_in_body(handler.body))
                    if (any(_has_scope_app(r) for r in try_reruns) and
                            any(r.lineno == lineno for r in handler_reruns)):
                        note = "[COMPAT_FALLBACK?]"
                        break

            v = Violation(
                filepath=filepath,
                lineno=lineno,
                rule=1,
                message=f"st.rerun() without scope='app'  (inside: {node.name})",
                note=note,
                suppressed=lineno in suppressed,
            )
            violations.append(v)
    return violations

# ---------------------------------------------------------------------------
# Rule 2: open() missing encoding='utf-8'
# ---------------------------------------------------------------------------

def _get_open_mode(call: ast.Call) -> Optional[str]:
    """Return the mode string if determinable, else None."""
    # mode is positional arg index 1, or keyword 'mode'
    if len(call.args) >= 2:
        arg = call.args[1]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None


def _has_encoding(call: ast.Call) -> bool:
    # encoding is positional arg index 3 (0-based), or keyword 'encoding'
    if len(call.args) >= 4:
        return True
    for kw in call.keywords:
        if kw.arg == "encoding":
            return True
    return False


def check_open_encoding(tree: ast.AST, filepath: Path, suppressed: set[int]) -> list[Violation]:
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Only flag bare open() - not tarfile.open, zipfile.open, etc.
        is_open = isinstance(func, ast.Name) and func.id == "open"
        if not is_open:
            continue
        mode = _get_open_mode(node)
        if mode is not None and "b" in mode:
            continue  # binary mode - encoding not applicable
        if not _has_encoding(node):
            lineno = node.lineno
            violations.append(Violation(
                filepath=filepath,
                lineno=lineno,
                rule=2,
                message="open() call missing encoding='utf-8'",
                suppressed=lineno in suppressed,
            ))
    return violations

# ---------------------------------------------------------------------------
# Rule 3: Bare except / except BaseException
# ---------------------------------------------------------------------------

def check_bare_except(tree: ast.AST, filepath: Path, suppressed: set[int]) -> list[Violation]:
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        is_bare = node.type is None
        is_base = (isinstance(node.type, ast.Name) and node.type.id == "BaseException")
        if is_bare or is_base:
            kind = "bare except:" if is_bare else "except BaseException:"
            lineno = node.lineno
            violations.append(Violation(
                filepath=filepath,
                lineno=lineno,
                rule=3,
                message=f"{kind}",
                suppressed=lineno in suppressed,
            ))
    return violations

# ---------------------------------------------------------------------------
# Rule 4: Variables in unsafe_allow_html=True not wrapped in esc()
# ---------------------------------------------------------------------------

# Whitelist: FormattedValue expressions that are safe and need no escaping
_SAFE_CALL_NAMES = {
    "esc", "get_base64_image",
    # Type conversions / formatters - output is controlled, not user HTML
    "str", "int", "float", "bool", "len", "round", "abs", "max", "min",
    "repr", "format", "sorted", "enumerate", "range", "sum",
}
_SAFE_ATTR_ROOTS = {"theme"}  # theme.ANYTHING is a design token

# Known-safe variable names - internal counters, sizes, progress values, CSS tokens
_SAFE_VAR_NAMES = {
    # Numeric / progress
    "percent", "current_files", "total_files", "log_content",
    "total_mb", "current_mb", "current_size", "total_size",
    "count", "total", "progress", "size", "n", "i", "j", "idx",
    "pct", "current", "total_courses", "total_pairs",
    "width", "height", "opacity", "duration", "delay", "radius",
    "version", "__version__",
    # CSS property values - never user-controlled HTML
    "accent", "bg", "border", "color", "fw",
    # CSS structural keys / namespaces - programmatic, not Canvas data
    "namespace", "prefix", "key_prefix",
    "active_key", "active_include_key",
    # App-controlled formatted display strings
    "mb_display", "eta_string", "ts_str", "time_display", "courses_text",
    # App-controlled UI labels / messages
    "mod_status_text", "download_label", "sync_label", "status_text",
    "cancel_summary_msg",
    # App-assembled HTML fragments
    "logo_html", "_icon_html",
    # Module-level color constants
    "_STAR_BLUE", "_LIST_BLUE",
}

# Variable name suffixes that indicate numeric/internal values
_SAFE_VAR_SUFFIXES = (
    "_count", "_files", "_mb", "_kb", "_bytes", "_size", "_pct",
    "_percent", "_total", "_num", "_n", "_index", "_idx", "_id",
    "_width", "_height", "_px", "_ms", "_s",
    # CSS keys - programmatic identifiers, not user-controlled data
    "_key",
    # App-assembled HTML fragments / CSS output
    "_html", "_css", "_rule", "_flex_rule",
    # Image data URLs / SVG data
    "_url", "_svg",
    # CSS property values - colors, filters, tag strings
    "_color", "_filter", "_tag", "_bg", "_col", "_bor",
    # Already-escaped values
    "_escaped",
)

# Variable name prefixes that indicate base64 image data - always safe
_SAFE_VAR_PREFIXES = ("b64_", "_b64_", "_b64")

# Safe function name suffixes - functions that return CSS/HTML app-controlled strings
_SAFE_CALL_NAME_SUFFIXES = ("_css", "_svg", "_html", "_style", "_color")


def _is_safe_formatted_value(fv: ast.FormattedValue) -> bool:
    """Return True if this interpolated expression is safe (doesn't need esc())."""
    val = fv.value

    # Arithmetic / unary / ternary - results are numbers, not user HTML
    if isinstance(val, (ast.BinOp, ast.UnaryOp, ast.IfExp)):
        return True

    # Subscript access (e.g. data['key'], arr[0]) - internal data
    if isinstance(val, ast.Subscript):
        return True

    # esc(...), get_base64_image(...), str(...), int(...), etc.
    if isinstance(val, ast.Call):
        func = val.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name in _SAFE_CALL_NAMES:
            return True
        if name and any(name.endswith(sfx) for sfx in _SAFE_CALL_NAME_SUFFIXES):
            return True
        # "".join(...) - CSS block concatenation
        if isinstance(func, ast.Attribute) and func.attr == "join":
            return True

    # theme.SOMETHING - design token constant
    if isinstance(val, ast.Attribute):
        root = val.value
        if isinstance(root, ast.Name) and root.id in _SAFE_ATTR_ROOTS:
            return True

    # String / numeric constant - literal, safe
    if isinstance(val, ast.Constant):
        return True

    # Known-safe variable names
    if isinstance(val, ast.Name):
        name = val.id
        if name in _SAFE_VAR_NAMES:
            return True
        if any(name.endswith(sfx) for sfx in _SAFE_VAR_SUFFIXES):
            return True
        if any(name.startswith(pfx) for pfx in _SAFE_VAR_PREFIXES):
            return True

    return False


def _is_markdown_with_unsafe_html(call: ast.Call) -> bool:
    """Return True if call has unsafe_allow_html=True keyword."""
    for kw in call.keywords:
        if kw.arg == "unsafe_allow_html":
            if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                return True
    return False


def check_unsafe_html_escaping(tree: ast.AST, filepath: Path, suppressed: set[int]) -> list[Violation]:
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match *.markdown(...) or st.markdown(...)
        func = node.func
        is_markdown = (
            (isinstance(func, ast.Attribute) and func.attr == "markdown") or
            (isinstance(func, ast.Name) and func.id == "markdown")
        )
        if not is_markdown:
            continue
        if not _is_markdown_with_unsafe_html(node):
            continue
        if not node.args:
            continue

        first_arg = node.args[0]
        if not isinstance(first_arg, ast.JoinedStr):
            continue  # not an f-string; skip

        # Walk all FormattedValue nodes in the f-string
        for fv in ast.walk(first_arg):
            if not isinstance(fv, ast.FormattedValue):
                continue
            if _is_safe_formatted_value(fv):
                continue

            lineno = getattr(fv, "lineno", node.lineno)

            # Check if it's a theme-like attribute but non-theme root - note it differently
            val = fv.value
            is_theme = (isinstance(val, ast.Attribute) and
                        isinstance(val.value, ast.Name) and
                        val.value.id in _SAFE_ATTR_ROOTS)
            note = "[THEME_CONST?]" if is_theme else ""

            # Reconstruct a rough representation of the expression
            try:
                expr_str = ast.unparse(val)
            except Exception:
                expr_str = "?"

            violations.append(Violation(
                filepath=filepath,
                lineno=lineno,
                rule=4,
                message=f"Unescaped variable in unsafe_allow_html: {{{expr_str}}}",
                note=note,
                suppressed=lineno in suppressed,
            ))
    return violations

# ---------------------------------------------------------------------------
# Rule 5: F-string <style> injections with unescaped single CSS braces
# ---------------------------------------------------------------------------

# Match CSS selectors followed by a lone { (not {{ or {var)
# Group 1: the selector-like text before the brace
_CSS_SINGLE_OPEN = re.compile(
    r'(?<!\{)\{(?!\{)(?![a-zA-Z0-9_\'"!#.\- ])',  # single { not followed by Python expr chars
    re.MULTILINE,
)

# A line that looks like a CSS selector (ends with possible whitespace + single {)
_CSS_SELECTOR_LINE = re.compile(
    r'(?:^|[\n;,\}])\s*'           # start of line or after ; , }
    r'[a-zA-Z0-9_\-\.\[\]#:>~+* ,\'"\(\)=\^$|]+'  # selector chars
    r'\s*'
    r'(?<!\{)\{(?!\{)',             # single {
    re.MULTILINE,
)

# Match st.markdown(f... blocks - find the raw string content
_ST_MARKDOWN_F = re.compile(
    r'st\.markdown\s*\(\s*f("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')',
    re.MULTILINE,
)

_STYLE_BLOCK = re.compile(r'<style[^>]*>([\s\S]*?)</style>', re.IGNORECASE)

# Remove Python variable injections {var}, {var.attr}, {var.attr.x}, {expr}
# before checking for unescaped CSS braces - these are intentional f-string uses.
_PYTHON_VAR_INJECTION = re.compile(r'\{[a-zA-Z_][a-zA-Z0-9_.]*[^{}]*?\}')


def check_css_fstring_braces(source: str, filepath: Path, suppressed: set[int],
                              source_lines: list[str]) -> list[Violation]:
    violations = []
    for m in _ST_MARKDOWN_F.finditer(source):
        raw_str = m.group(1)
        # Strip surrounding quotes
        if raw_str.startswith('"""') or raw_str.startswith("'''"):
            content = raw_str[3:-3]
        else:
            content = raw_str[1:-1]

        for style_m in _STYLE_BLOCK.finditer(content):
            css_content = style_m.group(1)
            # Strip Python variable injections so they don't false-positive as CSS braces
            cleaned_css = _PYTHON_VAR_INJECTION.sub("__PYVAR__", css_content)
            # Find CSS-selector-like lines followed by single {
            for sel_m in _CSS_SELECTOR_LINE.finditer(cleaned_css):
                # Compute line number in original source
                offset_in_source = m.start() + raw_str.find(css_content) + sel_m.start()
                lineno = source[:offset_in_source].count("\n") + 1
                if lineno in suppressed:
                    continue
                snippet = sel_m.group(0).strip().replace("\n", " ")[:80]
                violations.append(Violation(
                    filepath=filepath,
                    lineno=lineno,
                    rule=5,
                    message=f"CSS selector with single {{ in f-string <style>: {snippet!r}",
                    note="[CSS_BRACE?]",
                    suppressed=False,
                ))
    return violations

# ---------------------------------------------------------------------------
# Main scan loop
# ---------------------------------------------------------------------------

RULE_LABELS = {
    1: "st.rerun() without scope='app' inside @st.dialog",
    2: "open() missing encoding='utf-8'",
    3: "Bare except: / except BaseException:",
    4: "Unescaped variable in unsafe_allow_html=True",
    5: "F-string <style> block with unescaped single CSS brace",
    6: "CSS selector naming a testid Streamlit no longer renders",
    7: "Literal angle-bracket tag name inside a CSS comment",
}


# ---------------------------------------------------------------------------
# Rule 6: dead Streamlit testids
# ---------------------------------------------------------------------------

# Verified by live querySelectorAll counts against Streamlit 1.51 (2026-07-25):
# every one of these returns 0 nodes, so any selector naming one is dead CSS
# that fails silently. Value = what to use instead.
DEAD_TESTIDS = {
    "stVerticalBlockBorderWrapper": 'the keyed div itself, div[class*="st-key-x"]',
    # NOTE: only the HYPHENATED form is dead. 1.51 renders the same element with
    # data-testid="stElementContainer" AND class="stElementContainer element-container",
    # so [data-testid="stElementContainer"], .stElementContainer and .element-container
    # are all live - it is exactly and only the hyphenated TESTID that matches nothing.
    "element-container": '[data-testid="stElementContainer"] or the class .stElementContainer',
    "stToggle": 'st.toggle renders through [data-testid="stCheckbox"]',
    "stDialogScrollableBody": "gone entirely - there is no padded dialog body wrapper",
    "stModal": '[data-testid="stDialog"]',
}

# Matches a testid used as a SELECTOR - data-testid="X" - not a passing mention
# in prose. Deliberately narrow so comments explaining the migration don't trip.
_DEAD_TESTID_RE = re.compile(
    r'data-testid\s*=\s*["\'](' + "|".join(re.escape(k) for k in DEAD_TESTIDS) + r')["\']'
)

# CSS block comments, and Python comments that own their whole line. Used ONLY by
# Rule 6 (see _blank_comments) - Rule 7 must NOT strip comments, since a literal
# tag inside a CSS comment is precisely the hazard it exists to catch.
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_PY_LINE_COMMENT_RE = re.compile(r"^[ \t]*#.*$", re.MULTILINE)


def _blank_comments(source: str, *, python: bool) -> str:
    """Blank out comment bodies while preserving every newline and byte offset.

    Rule 6 flags dead testids in *selectors*. A migration note that quotes the
    retired selector verbatim - e.g. completion.css's "the old
    [data-testid="stVerticalBlockBorderWrapper"] no longer exists" - is
    documentation, not code, and flagging it punishes the exact commenting the
    rule is meant to encourage. Replacing each comment character with a space
    (newlines kept) keeps reported line numbers exact.

    Only whole-line ``#`` comments are stripped for Python: a mid-line ``#`` is
    far more likely to be a hex colour than a comment, and a selector is never
    written inside one.
    """
    def _blank(m: re.Match) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in m.group(0))

    out = _CSS_COMMENT_RE.sub(_blank, source)
    if python:
        out = _PY_LINE_COMMENT_RE.sub(_blank, out)
    return out

# A literal opening tag for a known HTML element inside a CSS block terminates
# the <style> element and silently kills every rule after it (CLAUDE.md).
# The rule is only ever as good as this list, so it enumerates the FULL set of
# HTML elements plus the SVG elements this codebase inlines - not a hand-picked
# subset. A short list is worse than useless: it reads as covered while letting
# the next tag through. `b` was missing, and a `<b>` written in an explanatory
# CSS comment silently detached the entire course-selector toolbar stylesheet on
# 2026-07-26 (every rule gone; the toolbar fell back to Streamlit defaults).
# `\b[^>]*>` keeps this off comparisons - `<=`, `< 5` and `x < y` cannot match,
# since a tag name must follow `<` or `</` immediately.
_HTML_TAGS = (
    "a|abbr|address|area|article|aside|audio|b|base|bdi|bdo|blockquote|body|br|"
    "button|canvas|caption|cite|code|col|colgroup|data|datalist|dd|del|details|"
    "dfn|dialog|div|dl|dt|em|embed|fieldset|figcaption|figure|footer|form|"
    "h[1-6]|head|header|hgroup|hr|html|i|iframe|img|input|ins|kbd|label|legend|"
    "li|link|main|map|mark|menu|meta|meter|nav|noscript|object|ol|optgroup|"
    "option|output|p|param|picture|pre|progress|q|rp|rt|ruby|s|samp|script|"
    "search|section|select|slot|small|source|span|strong|style|sub|summary|sup|"
    "table|tbody|td|template|textarea|tfoot|th|thead|time|title|tr|track|u|ul|"
    "var|video|wbr"
)
_SVG_TAGS = (
    "svg|path|circle|rect|line|polyline|polygon|g|defs|use|text|tspan|ellipse|"
    "mask|pattern|clipPath|linearGradient|radialGradient|stop|filter|"
    "foreignObject|marker|symbol|image|animate"
)
_LITERAL_TAG_RE = re.compile(
    r"</?(?:" + _HTML_TAGS + "|" + _SVG_TAGS + r")\b[^>]*>",
    re.IGNORECASE,
)

# In a styles/*.css file only a CLOSING style tag is harmful (see the docstring
# on check_literal_tags_in_style for why opening tags are inert there).
_CLOSING_STYLE_RE = re.compile(r"</\s*style\s*>", re.IGNORECASE)


def check_dead_testids(source: str, filepath: Path, suppressed: set[int]) -> list[Violation]:
    """Flag CSS selectors that name a testid Streamlit 1.51 no longer renders.

    Applies to .py (inline CSS) and .css files alike. The ghost-box purge rules
    are deliberately inert and carry `audit-ignore`; see CLAUDE.md for why they
    must NOT be migrated.

    Comments are blanked first so a note that quotes a retired selector to
    explain the migration is not itself reported as a violation.
    """
    violations = []
    source = _blank_comments(source, python=filepath.suffix == ".py")
    for m in _DEAD_TESTID_RE.finditer(source):
        lineno = source[: m.start()].count("\n") + 1
        name = m.group(1)
        violations.append(Violation(
            filepath=filepath,
            lineno=lineno,
            rule=6,
            message=f'dead testid "{name}" - use {DEAD_TESTIDS[name]}',
            note="",
            suppressed=lineno in suppressed,
        ))
    return violations


def _style_string_parts(call: ast.Call):
    """Yield (text, lineno) for every string literal making up a call's first arg."""
    if not call.args:
        return
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        yield arg.value, arg.lineno
    elif isinstance(arg, ast.JoinedStr):
        for v in arg.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                yield v.value, getattr(v, "lineno", arg.lineno)


def check_literal_tags_in_style_py(tree: ast.AST, filepath: Path,
                                   suppressed: set[int]) -> list[Violation]:
    """Flag a literal HTML tag in a CSS comment inside an ``st.html()`` argument.

    Deliberately narrow to ``st.html`` - the danger is API-specific:

    * ``st.html()`` PARSES its input, so any literal tag (opening or closing)
      restructures the DOM and detaches the whole style element, silently
      killing every rule in it. One `label` tag in an explanatory comment wiped
      the entire Settings-dialog stylesheet on 2026-07-25.
    * ``st.markdown(unsafe_allow_html=True)`` passes the style element's content
      through as RAW TEXT, so a tag name in a comment there is harmless. Flagging
      it would be noise - two thirds of the candidate sites in this repo are
      st.markdown and perfectly fine.

    Matching is confined to `/* ... */` comments, which only ever appear in CSS
    context. A tag in a real selector/value would be a syntax error anyway.
    """
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "html"
                and isinstance(fn.value, ast.Name) and fn.value.id == "st"):
            continue
        for text, base_line in _style_string_parts(node):
            if "<style" not in text:
                continue
            for cm in re.finditer(r"/\*.*?\*/", text, re.DOTALL):
                for tm in _LITERAL_TAG_RE.finditer(cm.group(0)):
                    lineno = base_line + text[: cm.start() + tm.start()].count("\n")
                    violations.append(Violation(
                        filepath=filepath,
                        lineno=lineno,
                        rule=7,
                        message=(f"literal {tm.group(0)!r} in a CSS comment inside "
                                 f"st.html() - this terminates the style element and "
                                 f"kills every rule in the block"),
                        note="",
                        suppressed=lineno in suppressed,
                    ))
    return violations


def check_closing_style_in_css(source: str, filepath: Path,
                               suppressed: set[int]) -> list[Violation]:
    """Flag a closing style tag anywhere in a styles/*.css file.

    ``styles.inject_css()`` wraps the whole file in a style element via
    ``st.markdown(unsafe_allow_html=True)``, so an embedded closing tag ends the
    element early and every rule after it is silently dead. Opening tags are
    inert here - the content is parsed as raw text. (Proof: global.css carries a
    literal button tag in a comment at line 134 of ~1300, and every rule after
    it demonstrably still applies.)
    """
    violations = []
    for tm in _CLOSING_STYLE_RE.finditer(source):
        lineno = source[: tm.start()].count("\n") + 1
        violations.append(Violation(
            filepath=filepath,
            lineno=lineno,
            rule=7,
            message=(f"literal {tm.group(0)!r} in a .css file - inject_css() already "
                     f"wraps the file, so this ends the style element early and every "
                     f"rule below it is dead"),
            note="",
            suppressed=lineno in suppressed,
        ))
    return violations


def collect_css_files() -> list[Path]:
    """Static stylesheets, scanned for Rules 6 and 7 only.

    Note: EXCLUDE_DIRS deliberately contains "styles" (it exists to keep the
    PYTHON scan out of that folder), so it must NOT be applied here - it would
    filter out every file by its own parent directory name.
    """
    d = PROJECT_ROOT / "styles"
    if not d.is_dir():
        return []
    _skip = {".venv", "venv", "__pycache__", ".git", "build", "dist"}
    return sorted(p for p in d.rglob("*.css")
                  if not any(ex in p.parts for ex in _skip))


# ---------------------------------------------------------------------------
# Rule 8: a hex colour that is a near-duplicate of a design token
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")

# CIEDE2000 distance below which two colours are indistinguishable to the eye.
# 1.0 is the standard "not perceptible by human eyes" threshold, and is
# deliberately strict: anything flagged here is drift, never a design decision.
_COLOUR_TOLERANCE = 1.0


def _hex_norm(h: str) -> str:
    h = h.lower().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h


def _hex_to_lab(h: str) -> tuple[float, float, float]:
    """sRGB hex -> CIE L*a*b* (D65). Straight from the standard formulae."""
    h = h.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    r, g, b = lin
    x = (r * 0.4124564 + g * 0.3575761 + b * 0.1804375) / 0.95047
    y = (r * 0.2126729 + g * 0.7151522 + b * 0.0721750) / 1.00000
    z = (r * 0.0193339 + g * 0.1191920 + b * 0.9503041) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _ciede2000(lab1, lab2) -> float:
    """Perceptual colour difference. Plain RGB distance badly misjudges the dark
    navies that dominate this palette, which is why the full formula is used."""
    import math
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7))) if Cb > 0 else 0.0
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if (a1p or b1) else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if (a2p or b2) else 0.0
    dLp, dCp = L2 - L1, C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    else:
        dhp = h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp) / 2)
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2
    else:
        hbp = (h1p + h2p - 360) / 2
    T = (1 - 0.17 * math.cos(math.radians(hbp - 30))
         + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6))
         - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    Sl = 1 + (0.015 * (Lbp - 50) ** 2) / math.sqrt(20 + (Lbp - 50) ** 2)
    Sc = 1 + 0.045 * Cbp
    Sh = 1 + 0.015 * Cbp * T
    Rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7)) if Cbp > 0 else 0.0
    Rt = -math.sin(math.radians(2 * (30 * math.exp(-(((hbp - 275) / 25) ** 2))))) * Rc
    return math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2
                     + Rt * (dCp / Sc) * (dHp / Sh))


def _load_tokens() -> dict[str, str]:
    """Parse shared/theme.py for NAME = "#rrggbb" tokens (aliases resolved)."""
    src = (PROJECT_ROOT / "shared" / "theme.py").read_text(encoding="utf-8")
    tokens: dict[str, str] = {}
    for m in re.finditer(r'^([A-Z_0-9]+)\s*=\s*"(#[0-9a-fA-F]{3,6})"', src, re.M):
        tokens[m.group(1)] = _hex_norm(m.group(2))
    return tokens


_TOKEN_LABS: list[tuple[str, str, tuple[float, float, float]]] = []


def check_near_duplicate_colours(source: str, filepath: Path,
                                 suppressed: set[int]) -> list[Violation]:
    """Flag a hex that sits within 1.0 CIEDE2000 of a token but is not that token.

    A difference that small is invisible - so it is never an intentional design
    choice, only drift. Left unchecked it is how the palette reached 229 distinct
    values against 25 tokens (see the module docstring in shared/theme.py).

    Deliberate near-neighbours are legitimate where they encode something other
    than a visual difference - e.g. the documented 4-level depth ramp in
    styles/sync_history_cards.css - and those carry an `audit-ignore`.

    Comments are blanked first (same rule as check_dead_testids): a hex quoted in
    a comment to DOCUMENT a ramp is documentation, not a colour declaration.
    """
    if not _TOKEN_LABS:
        for name, hx in _load_tokens().items():
            _TOKEN_LABS.append((name, hx, _hex_to_lab(hx)))

    source = _blank_comments(source, python=filepath.suffix == ".py")
    violations = []
    for m in _HEX_RE.finditer(source):
        hx = _hex_norm(m.group(0))
        lab = _hex_to_lab(hx)
        for name, token_hex, token_lab in _TOKEN_LABS:
            if hx == token_hex:
                break               # it IS the token - fine
            d = _ciede2000(lab, token_lab)
            if d <= _COLOUR_TOLERANCE:
                lineno = source[: m.start()].count("\n") + 1
                violations.append(Violation(
                    filepath=filepath,
                    lineno=lineno,
                    rule=8,
                    message=(f'{hx} is {d:.2f} CIEDE2000 from theme.{name} '
                             f'({token_hex}) - visually identical; use the token'),
                    note="",
                    suppressed=lineno in suppressed,
                ))
                break
    return violations


def scan_css_file(filepath: Path) -> list[Violation]:
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return [Violation(filepath, 0, 0, f"Could not read file: {e}")]
    # CSS comments carry the suppression marker as /* audit-ignore */
    suppressed = {
        i for i, line in enumerate(source.splitlines(), start=1)
        if "audit-ignore" in line
    }
    # also suppress the line AFTER a marker-only comment line
    extra = {i + 1 for i in suppressed}
    return (check_dead_testids(source, filepath, suppressed | extra)
            + check_closing_style_in_css(source, filepath, suppressed | extra)
            + check_near_duplicate_colours(source, filepath, suppressed | extra))


def scan_file(filepath: Path) -> list[Violation]:
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return [Violation(filepath, 0, 0, f"Could not read file: {e}")]

    source_lines = source.splitlines()
    suppressed = build_suppressed_lines(source_lines)

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        return [Violation(filepath, e.lineno or 0, 0, f"SyntaxError: {e.msg}")]

    violations: list[Violation] = []
    violations.extend(check_dialog_reruns(tree, filepath, suppressed))
    violations.extend(check_open_encoding(tree, filepath, suppressed))
    violations.extend(check_bare_except(tree, filepath, suppressed))
    violations.extend(check_unsafe_html_escaping(tree, filepath, suppressed))
    violations.extend(check_css_fstring_braces(source, filepath, suppressed, source_lines))
    violations.extend(check_dead_testids(source, filepath, suppressed))
    violations.extend(check_literal_tags_in_style_py(tree, filepath, suppressed))
    if filepath.name != "theme.py":          # theme.py DEFINES the tokens
        violations.extend(check_near_duplicate_colours(source, filepath, suppressed))

    return violations


def run_audit(fail_on_error: bool = False) -> int:
    files = collect_files()
    css_files = collect_css_files()

    print(BOLD(f"\nCANVAS DOWNLOADER - ARCHITECTURE AUDIT"))
    print("=" * 50)
    print(DIM(f"Scanning {len(files)} python + {len(css_files)} css files...\n"))

    all_violations: list[Violation] = []
    for f in files:
        all_violations.extend(scan_file(f))
    for f in css_files:
        all_violations.extend(scan_css_file(f))

    # Group by rule
    by_rule: dict[int, list[Violation]] = {}
    for v in all_violations:
        by_rule.setdefault(v.rule, []).append(v)

    active_count = 0
    suppressed_count = 0

    for rule_num in sorted(by_rule.keys()):
        vs = by_rule[rule_num]
        label = RULE_LABELS.get(rule_num, f"Rule {rule_num}")
        active = [v for v in vs if not v.suppressed]
        silenced = [v for v in vs if v.suppressed]
        suppressed_count += len(silenced)
        active_count += len(active)

        if active:
            print(BOLD(RED(f"[RULE {rule_num}]")) + f" {label}")
            for v in sorted(active, key=lambda x: (str(x.filepath), x.lineno)):
                rel = v.filepath.relative_to(PROJECT_ROOT)
                loc = CYAN(f"{rel}:{v.lineno}")
                note = YELLOW(f" {v.note}") if v.note else ""
                print(f"  {loc}   {v.message}{note}")
            if silenced:
                print(DIM(f"  ({len(silenced)} suppressed via # audit-ignore)"))
            print()

    # Summary
    print("-" * 50)
    if active_count == 0:
        print(GREEN(BOLD("PASS: No violations found.")))
        print(DIM(f"  Files scanned: {len(files)}"))
        if suppressed_count:
            print(DIM(f"  Suppressed:    {suppressed_count}"))
    else:
        print(BOLD(RED(f"FAIL: {active_count} violation(s) found")) +
              f" across {len(files)} files.")
        if suppressed_count:
            print(DIM(f"  {suppressed_count} additional violation(s) suppressed via # audit-ignore"))
        print(DIM("\nAdd  # audit-ignore  on or above a flagged line to suppress it."))

    print()
    return 1 if (active_count > 0 and fail_on_error) else (1 if active_count > 0 else 0)


if __name__ == "__main__":
    fail_on_error = "--fail-on-error" in sys.argv
    sys.exit(run_audit(fail_on_error=fail_on_error))
