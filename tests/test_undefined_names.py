"""No function may READ a local name it never BINDS.

This exists because of a bug the whole suite could not see. `sync/execution.py`
appended to `_attempts` six times and passed it to `retry_failed_conversions`,
but never declared it - the retry-pass pattern was copied out of
`converters/post_processing.py` (commit 4b98b2e) and the one line that creates
the list did not come with it. Every sync that transferred a single file died
with `NameError: name '_attempts' is not defined`, on every contract shape,
because the sync flow appends unconditionally where the download flow guards
each append behind `if <files>:`. 1,951 unit tests passed against it; only a
real sync reached the line.

That is the same shape as the `isolate`/`UnboundLocalError` defect recorded in
CLAUDE.md, which also downloaded nothing and also passed every structural test.
Both are *one missing binding* in a long function that no test calls end to end.
A test naming `_attempts` would not have caught the first one and will not catch
the next, so this checks the CLASS: for every function in the engine modules,
every name it reads must be bound somewhere it can see.

Deliberately NOT a full linter. It only reports a name that is read in a
function and is bound in NO enclosing scope, no module scope, and is not a
builtin - the case that is always a crash waiting for the right input.
"""
from __future__ import annotations

import ast
import builtins
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The modules where a NameError is a user-visible crash rather than a quick
# failure in a tool. These run inside long, mostly-untested top-level flows.
ENGINE_MODULES = [
    "sync/execution.py",
    "sync/analysis.py",
    "sync/completion.py",
    "converters/post_processing.py",
    "core/canvas_logic.py",
    "core/sync_manager.py",
    "engine/progress_dashboard.py",
    "engine/estimation.py",
    # The Panopto engine. discovery.py in particular is a very long function
    # with several counters accumulated across nested loops and a thread pool -
    # the exact shape both recorded defects took. Added 2026-07-31 with the
    # institution-detection work, whose `_skipped_tools` counter would have been
    # a third instance had it been bound inside the wrong scope.
    "panopto/discovery.py",
    "panopto/runner.py",
    "panopto/stream.py",
    "panopto/institution.py",
    # Consent + daily-sync plumbing: long functions, many early returns, and
    # every path is one a real user hits before any test does.
    "shared/legal.py",
    "core/auto_sync.py",
]

_BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__"}


def _bound_by(node: ast.AST) -> set[str]:
    """Every name this statement/expression binds in its OWN scope."""
    out: set[str] = set()

    def targets(t: ast.AST) -> None:
        if isinstance(t, ast.Name):
            out.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                targets(e)
        elif isinstance(t, ast.Starred):
            targets(t.value)
        # Attribute/Subscript targets bind nothing new.

    for n in ast.walk(node):
        # Do not descend into a nested scope's own bindings - they are not ours.
        if isinstance(n, (ast.Assign,)):
            for t in n.targets:
                targets(t)
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
            targets(n.target)
        elif isinstance(n, ast.NamedExpr):
            targets(n.target)
        elif isinstance(n, (ast.For, ast.AsyncFor)):
            targets(n.target)
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                if item.optional_vars is not None:
                    targets(item.optional_vars)
        elif isinstance(n, ast.ExceptHandler):
            if n.name:
                out.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
        elif isinstance(n, (ast.comprehension,)):
            targets(n.target)
        elif isinstance(n, ast.MatchAs) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.MatchStar) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.MatchMapping) and n.rest:
            out.add(n.rest)

        # Parameters of any nested callable. This is deliberately FLAT: we ask
        # only "is this name bound anywhere in this subtree", never "is it in
        # scope at this point". A lambda's `x` or a nested def's `self` is a
        # binding, and without collecting them the checker reports every
        # `sorted(key=lambda x: x.n)` in the file. Slightly less sensitive,
        # and zero false positives - which is the only version anyone leaves
        # switched on.
        if isinstance(n, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            out.update(p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs))
            if a.vararg:
                out.add(a.vararg.arg)
            if a.kwarg:
                out.add(a.kwarg.arg)
    return out


def _params(fn: ast.AST) -> set[str]:
    a = fn.args
    got = {p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)}
    if a.vararg:
        got.add(a.vararg.arg)
    if a.kwarg:
        got.add(a.kwarg.arg)
    return got


def _undefined_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_names = _bound_by(tree)

    problems: list[str] = []

    def visit(fn: ast.AST, enclosing: set[str]) -> None:
        scope = enclosing | _params(fn) | _bound_by(fn)
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                if n.id not in scope and n.id not in _BUILTINS:
                    problems.append(
                        f"{path.as_posix()}:{n.lineno} {fn.name}() reads "
                        f"'{n.id}' which is never bound"
                    )
        for sub in ast.walk(fn):
            if sub is not fn and isinstance(
                sub, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                # walk() already covered its body under `scope`; nested defs see
                # the same names plus their own, so nothing extra is needed.
                pass

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit(node, module_names)

    # One report per (name, function), not per read site.
    return sorted(set(problems))


@pytest.mark.parametrize("rel", ENGINE_MODULES)
def test_no_undefined_names(rel):
    path = REPO / rel
    if not path.is_file():
        pytest.skip(f"{rel} not present")
    problems = _undefined_in(path)
    assert not problems, (
        "A function reads a name nothing ever binds. This is a NameError "
        "waiting for the code path to run:\n  " + "\n  ".join(problems)
    )


def test_detector_fires_on_the_real_regression(tmp_path):
    """BOTH directions: the checker must catch the actual shipped defect.

    Modelled on sync/execution.py as commit 4b98b2e left it - appends and a
    final read, with the declaration missing.
    """
    src = tmp_path / "regression.py"
    src.write_text(
        "def run_sync(pairs):\n"
        "    for p in pairs:\n"
        "        _attempts.append((p, []))\n"
        "    retry_failed_conversions(_attempts)\n",
        encoding="utf-8",
    )
    problems = _undefined_in(src)
    assert any("_attempts" in p for p in problems), problems


def test_detector_catches_the_defect_in_the_REAL_file(tmp_path):
    """Strip the real declaration from the real module; the checker must fire.

    The synthetic case above proves the checker understands the SHAPE. This
    proves it is live against `sync/execution.py` as actually written - the
    file where the defect shipped. Without this, a refactor could move
    `_attempts` somewhere the checker stops looking and both other tests would
    still pass while the guard quietly died.
    """
    real = REPO / "sync/execution.py"
    if not real.is_file():
        pytest.skip("sync/execution.py not present")

    text = real.read_text(encoding="utf-8")
    decl = "    _attempts: list = []\n"
    assert decl in text, (
        "sync/execution.py no longer declares _attempts the way this guard "
        "expects. If it moved, update this test - do not delete it."
    )

    broken = tmp_path / "execution_without_decl.py"
    broken.write_text(text.replace(decl, "", 1), encoding="utf-8")

    problems = _undefined_in(broken)
    assert any("_attempts" in p for p in problems), (
        "Removing the _attempts declaration from the real file produced no "
        "finding - the guard is dead:\n  " + "\n  ".join(problems)
    )


def test_detector_silent_when_the_binding_is_present():
    """The other direction: the fixed shape must produce nothing."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "fixed.py"
        src.write_text(
            "def run_sync(pairs):\n"
            "    _attempts: list = []\n"
            "    for p in pairs:\n"
            "        _attempts.append((p, []))\n"
            "    return _attempts\n",
            encoding="utf-8",
        )
        assert _undefined_in(src) == []
