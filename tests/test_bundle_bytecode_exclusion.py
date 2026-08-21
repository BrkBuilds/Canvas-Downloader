"""The shipped bundle must carry no ``__pycache__``.

Both specs bundle the app's own packages by DIRECTORY (``('core', 'core')``,
``('panopto', 'panopto')``, …) and PyInstaller expands a directory tuple into
every file underneath it - so a developer's ``__pycache__`` goes into the bundle
with the source. Measured on this tree: **75 stale ``.pyc``** across the eight
app packages, and they were sealed into the last local build's signature.

WHY THIS IS A DELIVERY DEFECT AND NOT TIDINESS, measured on macOS 26.6.1 against
two quarantined copies of the same bundle::

    valid ad-hoc seal    spctl -a -t exec -> "rejected"                    exit 3
    __pycache__ removed  spctl -a -t exec -> "a sealed resource is missing" exit 1

Those are different verdict CLASSES, not different wordings. Exit 3 is the
not-notarized policy denial - the *"Apple could not verify…"* dialog with the
**Open Anyway** path that ``docs/mac-setup.html`` walks the user through. Exit 1
is a signature VALIDITY failure - the *"…is damaged and can't be opened. You
should move it to the Trash"* dialog, which has no Open Anyway path at all.

The app ships unsigned **by design** (a free student project, stated on the
website and in the README), so that one recoverable dialog is the entire macOS
onboarding route. A bundle that can lose its seal turns it into a wall.

REACHABILITY, MEASURED - stated so nobody inherits an inflated severity. The
shipped **v2.0.1 DMG was downloaded and inspected**: one ``__pycache__``, in a
third-party ``dist-info/licenses`` folder, and none of the app's own. Release
DMGs come from ``.github/workflows/build-macos.yml`` on a fresh checkout, which
has nothing to sweep in - so this has never affected a released build, and the
exit-1 verdict above came from a LOCAL one. The filter is unconditional anyway
because a local build should be byte-comparable to the CI one when you are
debugging a release, not because a user was ever hit by it.

(The same inspection found what DID ship: v2.0.1 fails ``codesign --verify``
because ``pync`` vendors a nested app PyInstaller cannot seal. Already fixed -
``pync`` is out of the spec and a fresh build verifies exit 0. It still assessed
as exit 3, so a failing ``codesign`` does not by itself mean "damaged".)

The site count is the point of this file. This repo's history is a fix landing
on one of two equivalent places and nobody noticing for months (``pdf_looks_real``
on two of three delete sites; the AppleScript escaper written three times). Two
specs is exactly that shape, so both are asserted, and each assertion is guarded
against going vacuous.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPECS = ("Canvas_Downloader.spec", "Canvas_Downloader_macOS.spec")

#: The app's own source packages, bundled by directory in both specs. These are
#: the ones that can carry a developer's ``__pycache__``.
APP_PACKAGES = ("core", "converters", "engine", "shared", "sync", "panopto",
                "ui", "styles")


def _load_build_excludes():
    spec = importlib.util.spec_from_file_location(
        "build_excludes_under_test", REPO / "scripts" / "build_excludes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build_excludes = _load_build_excludes()


def _spec_source(name: str) -> str:
    return io.open(REPO / name, encoding="utf-8", newline="").read()


def _spec_ast(name: str) -> ast.Module:
    """A ``.spec`` is executable Python, so it parses."""
    return ast.parse(_spec_source(name), filename=name)


def _is_a_datas(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "datas"
            and isinstance(node.value, ast.Name) and node.value.id == "a")


def _strip_call_line(tree: ast.Module) -> int | None:
    """Line of the real ``a.datas = _excl.strip_bytecode_datas(a.datas)``.

    ``None`` when the assignment is absent - including when it has merely been
    commented out, which is the case a text search cannot tell from a live one.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(_is_a_datas(t) for t in node.targets):
            continue
        call = node.value
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "strip_bytecode_datas"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "_excl"
                and any(_is_a_datas(arg) for arg in call.args)):
            return node.lineno
    return None


def _analysis_line(tree: ast.Module) -> int | None:
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "a" for t in node.targets)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "Analysis"):
            return node.lineno
    return None


# ── what the filter does ─────────────────────────────────────────────────────

def test_a_pycache_directory_component_is_dropped():
    kept = build_excludes.strip_bytecode_datas([
        ("core/__pycache__/cancellation.cpython-311.pyc", "/src", "DATA"),
    ])
    assert kept == []


def test_NOTHING_inside_a_pycache_directory_ships_whatever_it_is_called():
    """The directory test is load-bearing, not a belt on the suffix test.

    A ``.pyc`` inside ``__pycache__`` is caught by either check alone, so a
    fixture built only from those two cases lets the whole directory rule be
    deleted with the suite still green - which is what the mutation pass proved
    about the first version of this file. The property is *nothing under
    ``__pycache__`` ships*: an editor's ``.pyc.tmp``, a half-written
    ``.cpython-311.pyc.140736``, a ``.DS_Store`` Finder left there. Each is a
    file the signature would seal and something else may later remove.
    """
    kept = build_excludes.strip_bytecode_datas([
        ("core/__pycache__/sync_manager.cpython-311.pyc.tmp", "/src", "DATA"),
        ("ui/__pycache__/.DS_Store", "/src", "DATA"),
        ("panopto/__pycache__/runner.cpython-311.pyc.140736", "/src", "DATA"),
    ])
    assert kept == []


def test_a_windows_pycache_directory_is_matched_by_the_DIRECTORY_rule():
    """The separator normalisation and the directory rule have to hold together.

    Without ``replace("\\", "/")`` the whole destination is one component on
    Windows, so the directory rule matches nothing and only the suffix test
    survives - which is invisible for a ``.pyc`` and silent for anything else.
    """
    kept = build_excludes.strip_bytecode_datas([
        ("ui\\__pycache__\\auth.cpython-311.pyc.tmp", "C:\\src", "DATA"),
        ("ui\\auth.py", "C:\\src", "DATA"),
    ])
    assert [e[0] for e in kept] == ["ui\\auth.py"]


def test_a_bare_pyc_is_dropped_even_outside_a_pycache_dir():
    """A ``.pyc`` beside its source (Python 2 layout, or a hand-placed one) is
    the same hazard: sealed bytecode nothing needs."""
    kept = build_excludes.strip_bytecode_datas([
        ("panopto/runner.pyc", "/src", "DATA"),
        ("panopto/runner.pyo", "/src", "DATA"),
    ])
    assert kept == []


def test_the_python_sources_are_KEPT():
    """Bytecode-only is what makes this unable to break an import: CPython
    simply recompiles from the ``.py`` that is still there."""
    entries = [("core/sync_manager.py", "/src", "DATA"),
               ("styles/global.css", "/src", "DATA"),
               ("assets/icon.png", "/src", "BINARY")]
    assert build_excludes.strip_bytecode_datas(list(entries)) == entries


def test_matching_is_on_a_whole_directory_component_not_a_substring():
    """Same rule as ``strip_test_datas``: a substring match would eat an
    ordinary file whose name merely contains the token."""
    entries = [("docs/pycache_notes/x.py", "/src", "DATA"),
               ("core/__pycache___helper.py", "/src", "DATA"),
               ("a/my.pycx", "/src", "DATA")]
    assert build_excludes.strip_bytecode_datas(list(entries)) == entries


def test_windows_destination_separators_are_handled():
    """``a.datas`` on Windows carries backslashes; the filter must not become a
    no-op on the platform whose build it also guards."""
    kept = build_excludes.strip_bytecode_datas([
        ("ui\\__pycache__\\auth.cpython-311.pyc", "C:\\src", "DATA"),
        ("ui\\auth.py", "C:\\src", "DATA"),
    ])
    assert [e[0] for e in kept] == ["ui\\auth.py"]


def test_the_filter_is_a_pure_function_of_its_input():
    """It runs inside a spec, where a surprise mutation of ``a.datas`` would be
    invisible until a build behaved oddly."""
    entries = [("core/__pycache__/x.pyc", "/src", "DATA"),
               ("core/x.py", "/src", "DATA")]
    before = list(entries)
    build_excludes.strip_bytecode_datas(entries)
    assert entries == before


# ── the call sites: BOTH specs, after Analysis ───────────────────────────────

@pytest.mark.parametrize("spec_name", SPECS)
def test_the_spec_bundles_the_app_packages_by_directory(spec_name):
    """Guards every assertion below from going vacuous.

    If the specs ever stop bundling whole directories there is no ``__pycache__``
    hazard to filter - and the site-count tests would then be asserting a rule
    about nothing while still passing.
    """
    src = _spec_source(spec_name)
    for pkg in APP_PACKAGES:
        assert f"('{pkg}', '{pkg}')" in src, (
            f"{spec_name} no longer bundles {pkg!r} by directory - re-read "
            "this test file before deleting it")


@pytest.mark.parametrize("spec_name", SPECS)
def test_the_spec_strips_bytecode_from_its_datas(spec_name):
    """The counting rule. A fix on one spec and not the other is this repo's
    documented failure mode, and it ships a broken bundle on the other OS.

    Resolved through the AST, never by grepping the source: commenting the call
    out leaves the text on the line, so a substring or regex match passes
    against a spec that no longer strips anything. That is not hypothetical -
    it is what the first version of this test did, and the mutation pass caught
    it on both specs.
    """
    assert _strip_call_line(_spec_ast(spec_name)) is not None, (
        f"{spec_name} does not strip __pycache__ from a.datas")


@pytest.mark.parametrize("spec_name", SPECS)
def test_the_strip_happens_AFTER_analysis(spec_name):
    """``a.datas`` does not exist until ``Analysis`` has run, and the entries
    being removed are the ones ``Analysis`` itself collected. Assert the
    ordering rather than mere presence - the same discipline the Canvas-content
    ordering test uses, and for the same reason."""
    tree = _spec_ast(spec_name)
    strip = _strip_call_line(tree)
    assert strip is not None, f"{spec_name} does not strip bytecode at all"
    analysis = _analysis_line(tree)
    assert analysis is not None, f"{spec_name} has no `a = Analysis(...)`"
    assert analysis < strip, (
        f"{spec_name} strips bytecode before Analysis has produced a.datas")


@pytest.mark.parametrize("spec_name", SPECS)
def test_the_spec_does_not_hand_roll_its_own_bytecode_filter(spec_name):
    """The policy lives in ``scripts/build_excludes.py``.

    ``build_excludes``'s own docstring states why: the two specs are
    near-duplicates, and a trimming rule written twice is a rule one of them is
    following an old version of.
    """
    src = _spec_source(spec_name)
    body = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    for line in body.splitlines():
        if "__pycache__" in line:
            assert "strip_bytecode_datas" in line, (
                f"{spec_name} mentions __pycache__ outside the shared policy: "
                f"{line.strip()!r}")


def test_the_shared_policy_module_exposes_it_as_a_module_level_function():
    """Both specs reach it as ``_excl.strip_bytecode_datas``; a nested or
    conditionally-defined one would raise at build time, not here."""
    tree = ast.parse((REPO / "scripts" / "build_excludes.py").read_text(encoding="utf-8"))
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert "strip_bytecode_datas" in names
    assert "strip_test_datas" in names


# ── the positive control ─────────────────────────────────────────────────────

def test_the_hazard_this_guards_is_real_in_this_working_tree():
    """A filter that never has anything to remove proves nothing.

    This asserts the *input* condition, not the app's cleanliness: the packages
    the specs bundle really do accumulate ``__pycache__`` during ordinary work,
    which is what makes the unconditional filter necessary rather than a
    build-host hygiene rule. Skips on a tree that happens to be clean (a fresh
    clone, or CI) rather than failing, because the tree's state is not the
    property under test.
    """
    present = [p for p in APP_PACKAGES if (REPO / p / "__pycache__").is_dir()]
    if not present:
        pytest.skip("no __pycache__ in this tree - nothing to demonstrate")

    datas = []
    for pkg in present:
        for pyc in (REPO / pkg / "__pycache__").glob("*.pyc"):
            datas.append((f"{pkg}/__pycache__/{pyc.name}", str(pyc), "DATA"))
        datas.append((f"{pkg}/__init__.py", str(REPO / pkg / "__init__.py"), "DATA"))

    assert any(".pyc" in d[0] for d in datas), "control built no .pyc entries"
    kept = build_excludes.strip_bytecode_datas(datas)
    assert kept, "the filter removed the sources too"
    assert not [d for d in kept if d[0].endswith((".pyc", ".pyo"))]
    assert len(kept) == len(present)
