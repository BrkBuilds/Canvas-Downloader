"""Regression tests for scripts/verify_architecture.py's CSS-safety rules.

Rule 7 exists because a literal HTML tag inside a CSS comment in an
``st.html(<style>)`` block terminates the style element and silently kills every
rule in it. The rule is only ever as good as its tag list - it was missing ``b``,
and a ``<b>`` written in an explanatory comment detached the whole
course-selector toolbar stylesheet on 2026-07-26. These tests pin both the
catching and the not-over-catching.
"""
import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "verify_architecture", ROOT / "scripts" / "verify_architecture.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


va = _load()


def _run7(src: str):
    return va.check_literal_tags_in_style_py(ast.parse(src), Path("fake.py"), set())


def _st_html(comment: str) -> str:
    return f'st.html("""<style>\n/* {comment} */\n.x {{ color: red; }}\n</style>""")\n'


# --------------------------------------------------------------------------
# Rule 7 must CATCH literal tags in st.html CSS comments
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tag", [
    "<b>", "<a>", "<i>", "<p>", "<u>", "<s>", "<q>",          # single letters
    "<label>", "<div>", "<span>", "<strong>", "<em>",
    "<summary>", "<details>", "<code>", "<pre>",
    "<svg>", "<path>", "<circle>",                              # inlined SVG
    "</style>", "</div>",                                       # closing forms
    '<div class="x">',                                          # with attributes
])
def test_rule7_catches_literal_tag_in_st_html_comment(tag):
    hits = _run7(_st_html(f"the nested {tag} element wraps the icon"))
    assert len(hits) == 1, f"{tag} should be flagged"
    assert "terminates the style element" in hits[0].message


def test_rule7_reports_every_tag_in_one_comment():
    assert len(_run7(_st_html("wraps <b> inside <span> inside <div>"))) == 3


# --------------------------------------------------------------------------
# ...and must NOT over-catch
# --------------------------------------------------------------------------

def test_rule7_ignores_st_markdown():
    """st.markdown passes style content through as RAW TEXT, so a tag name in a
    comment there is harmless - flagging it would be pure noise."""
    src = _st_html("the nested <b> element").replace("st.html(", "st.markdown(")
    assert _run7(src) == []


@pytest.mark.parametrize("text", [
    "when width <= 700px shrink the row",
    "only if x < 5 and y > 2",
    "compare a < b then swap",
    "the a and b selectors",
    "arrow -> points right",
])
def test_rule7_ignores_comparisons_and_prose(text):
    assert _run7(_st_html(text)) == [], f"should not flag: {text}"


def test_rule7_ignores_tags_outside_a_style_block():
    """Only style blocks are at risk; an st.html rendering real markup is fine."""
    assert _run7('st.html("<div><b>hello</b></div>")') == []


# --------------------------------------------------------------------------
# The live codebase must stay clean
# --------------------------------------------------------------------------

def test_repo_has_no_literal_tags_in_style_blocks():
    """A failure here means someone's CSS comment just killed a stylesheet."""
    offenders = []
    skip = {".venv", "venv", "__pycache__", ".git", "build", "dist", "tests"}
    for path in sorted(ROOT.rglob("*.py")):
        if any(d in path.parts for d in skip):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for v in va.check_literal_tags_in_style_py(tree, path, set()):
            offenders.append(f"{path.relative_to(ROOT).as_posix()}:{v.lineno} {v.message[:60]}")
    assert offenders == [], "literal tags found in st.html style blocks:\n" + "\n".join(offenders)
