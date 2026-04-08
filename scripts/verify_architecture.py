#!/usr/bin/env python3
"""
Canvas Downloader — Architecture Verification Script
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

# Root of the project — resolved relative to this script's location
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Directories to scan recursively
SCAN_DIRS = ["ui", "sync", "engine", "core"]

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
        # Only flag bare open() — not tarfile.open, zipfile.open, etc.
        is_open = isinstance(func, ast.Name) and func.id == "open"
        if not is_open:
            continue
        mode = _get_open_mode(node)
        if mode is not None and "b" in mode:
            continue  # binary mode — encoding not applicable
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
    # Type conversions / formatters — output is controlled, not user HTML
    "str", "int", "float", "bool", "len", "round", "abs", "max", "min",
    "repr", "format", "sorted", "enumerate", "range", "sum",
}
_SAFE_ATTR_ROOTS = {"theme"}  # theme.ANYTHING is a design token

# Known-safe variable names — internal counters, sizes, progress values, CSS tokens
_SAFE_VAR_NAMES = {
    # Numeric / progress
    "percent", "current_files", "total_files", "log_content",
    "total_mb", "current_mb", "current_size", "total_size",
    "count", "total", "progress", "size", "n", "i", "j", "idx",
    "pct", "current", "total_courses", "total_pairs",
    "width", "height", "opacity", "duration", "delay", "radius",
    "version", "__version__",
    # CSS property values — never user-controlled HTML
    "accent", "bg", "border", "color", "fw",
    # CSS structural keys / namespaces — programmatic, not Canvas data
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
    # CSS keys — programmatic identifiers, not user-controlled data
    "_key",
    # App-assembled HTML fragments / CSS output
    "_html", "_css", "_rule", "_flex_rule",
    # Image data URLs / SVG data
    "_url", "_svg",
    # CSS property values — colors, filters, tag strings
    "_color", "_filter", "_tag", "_bg", "_col", "_bor",
    # Already-escaped values
    "_escaped",
)

# Variable name prefixes that indicate base64 image data — always safe
_SAFE_VAR_PREFIXES = ("b64_", "_b64_", "_b64")

# Safe function name suffixes — functions that return CSS/HTML app-controlled strings
_SAFE_CALL_NAME_SUFFIXES = ("_css", "_svg", "_html", "_style", "_color")


def _is_safe_formatted_value(fv: ast.FormattedValue) -> bool:
    """Return True if this interpolated expression is safe (doesn't need esc())."""
    val = fv.value

    # Arithmetic / unary / ternary — results are numbers, not user HTML
    if isinstance(val, (ast.BinOp, ast.UnaryOp, ast.IfExp)):
        return True

    # Subscript access (e.g. data['key'], arr[0]) — internal data
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
        # "".join(...) — CSS block concatenation
        if isinstance(func, ast.Attribute) and func.attr == "join":
            return True

    # theme.SOMETHING — design token constant
    if isinstance(val, ast.Attribute):
        root = val.value
        if isinstance(root, ast.Name) and root.id in _SAFE_ATTR_ROOTS:
            return True

    # String / numeric constant — literal, safe
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

            # Check if it's a theme-like attribute but non-theme root — note it differently
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

# Match st.markdown(f... blocks — find the raw string content
_ST_MARKDOWN_F = re.compile(
    r'st\.markdown\s*\(\s*f("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')',
    re.MULTILINE,
)

_STYLE_BLOCK = re.compile(r'<style[^>]*>([\s\S]*?)</style>', re.IGNORECASE)

# Remove Python variable injections {var}, {var.attr}, {var.attr.x}, {expr}
# before checking for unescaped CSS braces — these are intentional f-string uses.
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
}


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

    return violations


def run_audit(fail_on_error: bool = False) -> int:
    files = collect_files()

    print(BOLD(f"\nCANVAS DOWNLOADER — ARCHITECTURE AUDIT"))
    print("=" * 50)
    print(DIM(f"Scanning {len(files)} files...\n"))

    all_violations: list[Violation] = []
    for f in files:
        all_violations.extend(scan_file(f))

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
