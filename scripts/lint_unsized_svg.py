#!/usr/bin/env python3
"""
Canvas Downloader - Unsized-SVG Linter
======================================
Finds inline <svg> icons embedded in Python strings that have NO intrinsic
size (no inline width/height, neither as attributes nor inside an inline
`style=`). Such an SVG is sized *only* by a CSS class from a page-scoped
stylesheet (e.g. today.css). During a page/mode transition, Streamlit's React
reconciliation can briefly leave the old markup in the DOM while that
stylesheet is no longer injected - with nothing to constrain it, an unsized
SVG balloons to the ~300x150 default replaced-element size and paints a giant
icon over the next page.

This is exactly the "giant grey book icon on the Download loading screen" bug:
`_SVG_COURSE` relied on `today.css .tcs-pill-ico { width:16px; height:16px }`
and had no inline size. The fix is to give every persistent inline icon its own
inline `style='width:..;height:..'` so it can never balloon.

Usage:
    python scripts/lint_unsized_svg.py
    python scripts/lint_unsized_svg.py --fail-on-error   # exits 1 if findings
    python scripts/lint_unsized_svg.py --no-color        # plain output

Suppression:
    Add  # audit-ignore  (or  # svg-ignore ) on the flagged line or the line
    immediately before it to silence a specific, deliberately-unsized SVG
    (e.g. one that intentionally fills its container via width:100% in CSS).

What counts as "sized" (NOT flagged):
    - a width or height ATTRIBUTE on the <svg> tag        (width='16' height='16')
    - a width or height inside an inline style attribute  (style='width:16px;..')
    A viewBox alone is NOT a size - it only sets the aspect ratio / coordinate
    system, so viewBox-only SVGs are still flagged.
"""

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration (mirrors scripts/verify_architecture.py)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["ui", "sync", "engine", "core"]
SCAN_ROOT_PY = True
EXCLUDE_DIRS = {"styles", "scripts", ".venv", "venv", "__pycache__",
                ".git", "build", "dist"}

# ---------------------------------------------------------------------------
# ANSI color helpers
# ---------------------------------------------------------------------------

USE_COLOR = sys.stdout.isatty() and "--no-color" not in sys.argv


def _c(code: str, text: str) -> str:
    return text if not USE_COLOR else f"\033[{code}m{text}\033[0m"


RED    = lambda t: _c("31", t)
YELLOW = lambda t: _c("33", t)
CYAN   = lambda t: _c("36", t)
BOLD   = lambda t: _c("1", t)
DIM    = lambda t: _c("2", t)
GREEN  = lambda t: _c("32", t)

# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------

# The opening <svg ...> tag only (attributes live here; children come after >).
_SVG_OPEN_TAG = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)

# `width`/`height` as an attribute (name=) OR a CSS property (name:), but NOT
# `stroke-width`, `min-width`, `max-width` (the negative lookbehind rejects a
# preceding hyphen/word char). One pattern covers both attribute + style forms.
_HAS_WIDTH  = re.compile(r"(?<![-\w])width\s*[:=]",  re.IGNORECASE)
_HAS_HEIGHT = re.compile(r"(?<![-\w])height\s*[:=]", re.IGNORECASE)
_HAS_CLASS  = re.compile(r"(?<![-\w])class\s*=",     re.IGNORECASE)

# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    filepath: Path
    lineno: int
    name: str           # assigned constant name, or "" for inline SVGs
    excerpt: str        # truncated opening tag
    has_class: bool
    suppressed: bool = False

# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def collect_files() -> list[Path]:
    files: list[Path] = []
    for dir_name in SCAN_DIRS:
        d = PROJECT_ROOT / dir_name
        if d.is_dir():
            for p in sorted(d.rglob("*.py")):
                if not any(ex in p.parts for ex in EXCLUDE_DIRS):
                    files.append(p)
    if SCAN_ROOT_PY:
        for p in sorted(PROJECT_ROOT.glob("*.py")):
            if p.name != "__init__.py":
                files.append(p)
    seen, result = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            result.append(f)
    return result

# ---------------------------------------------------------------------------
# Suppression helpers
# ---------------------------------------------------------------------------

def build_suppressed_lines(source_lines: list[str]) -> set[int]:
    """1-indexed line numbers carrying (or one below) # audit-ignore / # svg-ignore."""
    suppressed: set[int] = set()
    for i, line in enumerate(source_lines):
        if "# audit-ignore" in line or "# svg-ignore" in line:
            suppressed.add(i + 1)   # this line
            suppressed.add(i + 2)   # the line below (marker placed above)
    return suppressed

# ---------------------------------------------------------------------------
# String reconstruction
# ---------------------------------------------------------------------------

# Adjacent string literals ("a" "b") are already merged into ONE ast.Constant
# by the parser, so implicit concatenation across lines is handled for free.
# f-strings become ast.JoinedStr - we join their literal parts and drop the
# {expr} holes (a width injected via an f-string expression is not something we
# can - or need to - verify statically).

def _joinedstr_literal(node: ast.JoinedStr) -> str:
    parts = []
    for v in node.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            parts.append(v.value)
        else:
            parts.append("\x00")   # placeholder for {expr}
    return "".join(parts)


def _string_nodes(tree: ast.AST) -> list[tuple[ast.AST, str]]:
    """All string-bearing nodes paired with their reconstructed literal text.

    A JoinedStr (f-string) is counted as one node; its literal-part Constants
    are skipped so an <svg> living in an f-string isn't reported twice (once for
    the whole f-string, once for the fragment before the first {expr}).
    """
    joined_child_consts: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant):
                    joined_child_consts.add(id(sub))

    out: list[tuple[ast.AST, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            out.append((node, _joinedstr_literal(node)))
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in joined_child_consts):
            out.append((node, node.value))
    return out


def _docstring_ids(tree: ast.AST) -> set[int]:
    """id()s of module/class/function docstring Constants (never rendered)."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return ids


# A variable is "data-URI tainted" if it is base64/percent encoded - e.g.
# auth.py's  svg = f'<svg ...>' ; return "data:...;base64," + b64encode(svg.encode())
# Such an SVG becomes a CSS background-image, sized by its box, so it can't
# balloon - unlike an inline SVG interpolated straight into HTML markup.
_ENCODE_TAINT = re.compile(r"\b([A-Za-z_]\w*)\s*\.\s*encode\s*\(")
_B64_TAINT    = re.compile(r"b64encode\s*\(\s*([A-Za-z_]\w*)")


def _datauri_tainted_names(source: str) -> set[str]:
    """Names that get base64-encoded somewhere in the file (data-URI bound)."""
    names: set[str] = set()
    for rx in (_ENCODE_TAINT, _B64_TAINT):
        names.update(m.group(1) for m in rx.finditer(source))
    return names


def _names_by_node(tree: ast.AST) -> dict[int, str]:
    """Map id(value_node) -> assigned name for `NAME = <svg string>` forms."""
    mapping: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name):
                mapping[id(node.value)] = tgt.id
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name):
                mapping[id(node.value)] = node.target.id
    return mapping

# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------

def scan_file(filepath: Path) -> list[Finding]:
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return [Finding(filepath, 0, "", f"Could not read file: {e}", False)]

    suppressed = build_suppressed_lines(source.splitlines())

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        return [Finding(filepath, e.lineno or 0, "", f"SyntaxError: {e.msg}", False)]

    names       = _names_by_node(tree)
    docstrings  = _docstring_ids(tree)
    tainted     = _datauri_tainted_names(source)
    findings: list[Finding] = []

    for node, text in _string_nodes(tree):
        if "<svg" not in text.lower():
            continue
        if id(node) in docstrings:
            continue  # <svg> mentioned in a docstring, not real markup
        # Skip an SVG that is base64-encoded into a data-URI (CSS
        # background-image): sized by its box, never a live inline DOM element,
        # so it cannot balloon (e.g. auth.py's _stg_ico -> svg.encode()).
        if names.get(id(node)) in tainted:
            continue
        for m in _SVG_OPEN_TAG.finditer(text):
            tag = m.group(0)
            sized = _HAS_WIDTH.search(tag) or _HAS_HEIGHT.search(tag)
            if sized:
                continue
            # Line of this specific tag: the node's start line + newlines before
            # the match (exact for triple-quoted strings; 0 offset for one-line
            # implicit-concat constants, whose svg begins on the node line).
            base = getattr(node, "lineno", 0)
            lineno = base + text[:m.start()].count("\n")
            excerpt = re.sub(r"\s+", " ", tag).strip()
            if len(excerpt) > 90:
                excerpt = excerpt[:87] + "..."
            findings.append(Finding(
                filepath=filepath,
                lineno=lineno,
                name=names.get(id(node), ""),
                excerpt=excerpt,
                has_class=bool(_HAS_CLASS.search(tag)),
                suppressed=lineno in suppressed or base in suppressed,
            ))
    return findings

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(fail_on_error: bool = False) -> int:
    files = collect_files()

    print(BOLD("\nCANVAS DOWNLOADER - UNSIZED-SVG LINT"))
    print("=" * 50)
    print(DIM(f"Scanning {len(files)} files for inline <svg> icons "
              f"with no inline width/height...\n"))

    all_findings: list[Finding] = []
    for f in files:
        all_findings.extend(scan_file(f))

    active    = [f for f in all_findings if not f.suppressed]
    silenced  = [f for f in all_findings if f.suppressed]

    # Class-only-sized icons are the exact ballooning-bug pattern - list first.
    active.sort(key=lambda x: (not x.has_class, str(x.filepath), x.lineno))

    if active:
        print(BOLD(RED("UNSIZED INLINE SVGs")) +
              "  (sized only by CSS - will balloon if the stylesheet unmounts)\n")
        for v in active:
            rel = v.filepath.relative_to(PROJECT_ROOT)
            loc = CYAN(f"{rel}:{v.lineno}")
            label = f" {BOLD(v.name)}" if v.name else ""
            tag = ("[sized by its own CSS class]" if v.has_class
                   else "[sized by an ancestor's CSS]")
            note = YELLOW(f" {tag}")
            print(f"  {loc}{label}{note}")
            print(DIM(f"      {v.excerpt}"))
        print()

    print("-" * 50)
    if not active:
        print(GREEN(BOLD("PASS: Every inline SVG carries an inline size.")))
        print(DIM(f"  Files scanned: {len(files)}"))
        if silenced:
            print(DIM(f"  Suppressed:    {len(silenced)}"))
    else:
        print(BOLD(RED(f"FAIL: {len(active)} unsized inline SVG(s) found")) +
              f" across {len(files)} files.")
        if silenced:
            print(DIM(f"  {len(silenced)} additional finding(s) suppressed."))
        print(DIM("\n  Fix: add  style='width:<n>px;height:<n>px;flex-shrink:0;'"
                  "  to the <svg> tag"))
        print(DIM("       (match the size the CSS class was giving it), or add"
                  "  # audit-ignore  if"))
        print(DIM("       the SVG is intentionally sized by its container."))

    print()
    return 1 if active and fail_on_error else 0


if __name__ == "__main__":
    sys.exit(run(fail_on_error="--fail-on-error" in sys.argv))
