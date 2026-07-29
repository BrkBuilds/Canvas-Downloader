"""Tests for scripts/verify_architecture.py - the audit script itself.

Why this file exists
--------------------
Rules 4 and 5 were rewritten on 2026-07-27 because the audit had drifted into
uselessness: it reported 51 violations, and every single one that fired was a
false positive. A gate nobody can pass teaches people to ignore the gate, so
the fix was to make the checks precise rather than to suppress their output.

Precision cuts both ways, though. Rule 4 in particular went from "flag every
interpolated name I cannot vouch for" to a small dataflow analysis, and each
step that removed a false positive also widened what it will accept. The
``FLAG`` cases below are the load-bearing half of this file: they are the
shapes the rule must never stop catching, including the ones the analysis is
structurally tempted to get wrong (a reference cycle, a shadowed parameter, a
value escaped and then re-bound to something raw).

Every case here is executable documentation of a decision - if one starts
failing, the analysis has become unsound, not merely noisy.
"""

import ast
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import verify_architecture as va  # noqa: E402

_FAKE = pathlib.Path("t.py")


def _rule4(src: str) -> bool:
    return bool(va.check_unsafe_html_escaping(ast.parse(src), _FAKE, set()))


def _rule5(src: str) -> bool:
    return bool(va.check_css_fstring_braces(ast.parse(src), _FAKE, set()))


# ---------------------------------------------------------------------------
# Rule 4 - must KEEP flagging these
# ---------------------------------------------------------------------------

RULE4_MUST_FLAG = [
    ("raw parameter",
     "def f(name):\n    st.markdown(f'<b>{name}</b>', unsafe_allow_html=True)"),
    ("attribute of an unknown object",
     "def f(o):\n    st.markdown(f'<b>{o.title}</b>', unsafe_allow_html=True)"),
    ("result of an unknown call",
     "def f():\n    x = fetch()\n    st.markdown(f'<b>{x}</b>', unsafe_allow_html=True)"),
    # Provenance is flow-INSENSITIVE: every binding must launder, so escaping
    # once does not license a later raw rebinding of the same name.
    ("escaped, then re-bound to raw",
     "def f(p):\n    x = esc(p)\n    x = p\n    st.markdown(f'<b>{x}</b>', unsafe_allow_html=True)"),
    ("loop variable",
     "def f(xs):\n    for it in xs:\n        st.markdown(f'<b>{it}</b>', unsafe_allow_html=True)"),
    # .replace() can splice in arbitrary text, so it is not in _SAFE_STR_METHODS.
    ("laundering attempt via .replace()",
     "def f(p):\n    x = p.replace('a','b')\n    st.markdown(f'<b>{x}</b>', unsafe_allow_html=True)"),
    ("f-string mixing an escaped and a raw part",
     "def f(p):\n    x = f'{esc(p)}{p}'\n    st.markdown(f'<b>{x}</b>', unsafe_allow_html=True)"),
    # The reason the fixpoint is pessimistic. An optimistic one would let these
    # two vouch for each other with no escape call anywhere in the cycle.
    ("mutually referential cycle",
     "def f():\n    a = g(b)\n    b = g(a)\n    st.markdown(f'<b>{a}</b>', unsafe_allow_html=True)"),
    # Scoping is per-function; a safe binding in ANOTHER function must not
    # launder a same-named parameter here.
    ("parameter shadowing a safe name elsewhere",
     "def f(txt):\n    st.markdown(f'<b>{txt}</b>', unsafe_allow_html=True)\n"
     "def g():\n    txt = esc('x')"),
    ("conditional with one raw arm",
     "def f(p, c):\n    x = esc(p) if c else p\n    st.markdown(f'<b>{x}</b>', unsafe_allow_html=True)"),
    # .upper() is in _SAFE_STR_METHODS but only preserves safety - it cannot
    # create it. HTML tag names are case-insensitive; this is the exact bug
    # found in ui/sync_review.py on 2026-07-27.
    ("case transform of a raw value",
     "def f(p):\n    x = p.upper()\n    st.markdown(f'<b>{x}</b>', unsafe_allow_html=True)"),
    ("raw element of an unpacked literal tuple",
     "def f(p):\n    a, b = ('safe', p)\n    st.markdown(f'<b>{b}</b>', unsafe_allow_html=True)"),
]

RULE4_MUST_ACCEPT = [
    ("esc() inline",
     "def f(p):\n    st.markdown(f'<b>{esc(p)}</b>', unsafe_allow_html=True)"),
    ("esc() into a local, then interpolated",
     "def f(p):\n    x = esc(p)\n    st.markdown(f'<b>{x}</b>', unsafe_allow_html=True)"),
    ("chain of literal-derived values",
     "def f():\n    a = 'hi'\n    b = f'<i>{a}</i>'\n    st.markdown(f'<b>{b}</b>', unsafe_allow_html=True)"),
    # The three-link chain that motivated the fixpoint: _c -> _scope -> _sub in
    # shared/components.py:render_completion_card.
    ("multi-link chain grounded in int()",
     "def f(d):\n    c = int(d)\n    s = f'across {c} courses'\n"
     "    t = f'Checked {s}.'\n    st.markdown(f'<b>{t}</b>', unsafe_allow_html=True)"),
    ("refine-in-place then escape",
     "def f(p):\n    c = str(p)\n    c = c[3:]\n    c = esc(c)\n"
     "    st.markdown(f'<b>{c}</b>', unsafe_allow_html=True)"),
    ("module-level inline-SVG constant",
     "def f():\n    st.markdown(f'<b>{SVG_EDIT_WHITE}</b>', unsafe_allow_html=True)"),
    ("uppercase _SVG-suffixed constant",
     "def f():\n    st.markdown(f'<b>{_CHEVRON_SVG}</b>', unsafe_allow_html=True)"),
    ("case transform of a safe value",
     "def f(namespace):\n    key = f'{namespace}_x'\n"
     "    st.markdown(f'<b>{key.lower()}</b>', unsafe_allow_html=True)"),
    ("safe element of an unpacked literal tuple",
     "def f(p):\n    a, b = ('safe', p)\n    st.markdown(f'<b>{a}</b>', unsafe_allow_html=True)"),
]


@pytest.mark.parametrize("label,src", RULE4_MUST_FLAG, ids=[c[0] for c in RULE4_MUST_FLAG])
def test_rule4_flags_unsafe(label, src):
    assert _rule4(src), f"Rule 4 stopped catching: {label}"


@pytest.mark.parametrize("label,src", RULE4_MUST_ACCEPT, ids=[c[0] for c in RULE4_MUST_ACCEPT])
def test_rule4_accepts_safe(label, src):
    assert not _rule4(src), f"Rule 4 false-positives on: {label}"


# ---------------------------------------------------------------------------
# Rule 5 - CSS braces that the parser turned into a format spec
# ---------------------------------------------------------------------------

RULE5_MUST_FLAG = [
    ("single declaration",
     "st.markdown(f'<style>div {color: red}</style>', unsafe_allow_html=True)"),
    ("several declarations",
     "st.markdown(f'<style>div {display: flex; align-items: center}</style>', unsafe_allow_html=True)"),
    ("st.html as well as st.markdown",
     "st.html(f'<style>div {color: red}</style>')"),
]

RULE5_MUST_ACCEPT = [
    ("properly escaped braces",
     "st.markdown(f'<style>div {{color: {c}}}</style>', unsafe_allow_html=True)"),
    # The two shapes the old regex could not see, because it only recognised
    # replacement fields starting with a letter or underscore.
    ("field starting with a string literal",
     "st.markdown(f'<style>div {{r: {\"0\" if o else \"8px\"}}}</style>', unsafe_allow_html=True)"),
    ("field starting with a digit",
     "st.markdown(f'<style>a {{t: rotate({90 if o else 0}deg)}}</style>', unsafe_allow_html=True)"),
    ("genuine numeric format spec",
     "st.markdown(f'<style>a {{w: {width:.2f}px}}</style>', unsafe_allow_html=True)"),
    ("genuine alignment format spec",
     "st.markdown(f'<style>a {{w: {n:>10}}}</style>', unsafe_allow_html=True)"),
    ("format spec that is itself interpolated",
     "st.markdown(f'<style>a {{w: {n:{w}}}}</style>', unsafe_allow_html=True)"),
    ("colon outside any style element",
     "st.markdown(f'<b>{color: red}</b>', unsafe_allow_html=True)"),
    ("colon after the style element closes",
     "st.markdown(f'<style>a {{b: c}}</style><i>{color: red}</i>', unsafe_allow_html=True)"),
]


@pytest.mark.parametrize("label,src", RULE5_MUST_FLAG, ids=[c[0] for c in RULE5_MUST_FLAG])
def test_rule5_flags_css_braces(label, src):
    assert _rule5(src), f"Rule 5 stopped catching: {label}"


@pytest.mark.parametrize("label,src", RULE5_MUST_ACCEPT, ids=[c[0] for c in RULE5_MUST_ACCEPT])
def test_rule5_accepts_valid_fstrings(label, src):
    assert not _rule5(src), f"Rule 5 false-positives on: {label}"


# ---------------------------------------------------------------------------
# Suppression markers
# ---------------------------------------------------------------------------

def test_audit_ignore_suppresses_its_own_line():
    lines = ["x = 1  # audit-ignore"]
    assert 1 in va.build_suppressed_lines(lines)


def test_audit_ignore_reaches_past_a_multi_line_justification():
    """The marker must survive a long explanation between it and the code.

    Suppressing only the literally-next line meant a two-line reason silently
    disarmed the marker - and the more a suppression deserved explaining, the
    more likely it was to stop working.
    """
    lines = [
        "# audit-ignore - deliberate, because:",
        "# reason line two",
        "",
        "# reason line three",
        "st.rerun(scope='fragment')",
    ]
    assert 5 in va.build_suppressed_lines(lines)


def test_audit_ignore_does_not_reach_a_second_statement():
    lines = [
        "# audit-ignore",
        "first_statement()",
        "second_statement()",
    ]
    suppressed = va.build_suppressed_lines(lines)
    assert 2 in suppressed
    assert 3 not in suppressed


# ---------------------------------------------------------------------------
# The repository itself
# ---------------------------------------------------------------------------

def test_repository_passes_its_own_audit():
    """The audit must stay green, so that any new violation means something.

    This is the whole point of the 2026-07-27 rewrite: the script's value comes
    entirely from PASS being the normal state.
    """
    py_files = va.collect_files()
    assert py_files, "collect_files() found nothing - the audit is not running"

    violations = []
    for path in py_files:
        violations.extend(va.scan_file(path))
    for path in va.collect_css_files():
        violations.extend(va.scan_css_file(path))

    unsuppressed = [v for v in violations if not v.suppressed]
    assert not unsuppressed, "Architecture audit regressed:\n" + "\n".join(
        f"  {v.filepath}:{v.lineno} rule {v.rule}: {v.message}"
        for v in unsuppressed
    )
