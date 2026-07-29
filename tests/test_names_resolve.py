"""Every name a screen calls must actually be bound in that module.

Python resolves globals at CALL time, so a function used but never imported is
perfectly valid source that raises ``NameError`` the moment the branch runs -
and the branches most likely to be missed are the ones a test suite never
reaches: a completion screen, an error handler, a fallback path.

This project has produced three of them in one session:

* ``render_archives_skipped_notice`` called on both completion screens and
  imported on neither - the whole screen replaced by a red traceback.
* ``debug_file`` in ``sync/execution.py`` where the local is ``_debug_file`` -
  in the handler that logs a failure of the edit-protection call, so the one
  path that needed to be loud about failing could not speak at all.
* ``isolate`` in ``download_course_async``, a local of a *different* function -
  the whole course downloaded nothing and reported "Processing Error".

All three passed every unit test. The check is cheap, so it runs over the
modules where a NameError is most expensive.
"""

from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Modules whose failure mode is "the user sees a traceback instead of a screen".
MODULES = [
    "app.py",
    "sync/completion.py",
    "sync/execution.py",
    "sync/analysis.py",
    "shared/components.py",
    "core/canvas_logic.py",
    "panopto/runner.py",
    "panopto/sync_plan.py",
    "converters/post_processing.py",
]


def _bound_at_module_level(tree: ast.Module) -> set[str]:
    """Names a module binds globally: imports, defs, classes, assignments."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        out.add(n.id)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            if isinstance(node.target, ast.Name):
                out.add(node.target.id)
        elif isinstance(node, (ast.For, ast.comprehension, ast.withitem,
                               ast.ExceptHandler, ast.NamedExpr)):
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                    out.add(n.id)
            if isinstance(node, ast.ExceptHandler) and node.name:
                out.add(node.name)
    return out


def _locally_bound(fn) -> set[str]:
    """Every name bound anywhere inside a function - params, assignments,
    comprehension targets, `with ... as`, `except ... as`, nested defs."""
    out = {a.arg for a in
           fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs}
    for a in (fn.args.vararg, fn.args.kwarg):
        if a:
            out.add(a.arg)
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            out.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
    return out


@pytest.mark.parametrize("relpath", MODULES)
def test_every_called_name_is_bound_somewhere(relpath):
    """Conservative on purpose: only CALLED bare names are checked, and a name
    bound anywhere in the enclosing function counts. That cannot prove a name is
    bound before use on every path - it catches the case that actually happens,
    which is a name bound nowhere at all."""
    path = REPO / relpath
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_names = _bound_at_module_level(tree)
    builtin_names = set(dir(builtins))

    funcs = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    # innermost-first, so a nested helper is checked against its own scope plus
    # every enclosing one
    scopes = {id(f): _locally_bound(f) for f in funcs}

    def enclosing(fn):
        out = set()
        for other in funcs:
            if other is fn:
                continue
            if other.lineno <= fn.lineno and (other.end_lineno or 0) >= (fn.end_lineno or 0):
                out |= scopes[id(other)]
        return out

    missing = []
    for fn in funcs:
        visible = module_names | builtin_names | scopes[id(fn)] | enclosing(fn)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name) and f.id not in visible:
                missing.append(f"{relpath}:{f.lineno} calls {f.id}() - bound nowhere")

    assert not missing, "\n".join(sorted(set(missing))[:20])
