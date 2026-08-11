"""A name a function READS that no reachable scope BINDS is a guaranteed crash.

Found the hard way, twice. `core/canvas_logic.py` once passed
``isolate_pages=isolate`` where ``isolate`` was a local of a *different*
function - the engine caught the exception and reported a generic "Processing
Error", so a whole course downloaded **nothing** with 1,431 unit tests green
(CLAUDE.md, "Verify in the REAL app, not a mock").

Then the 2026-08-11 folder-scope fix did it again, in the one site that mattered
most: ``_get_files_from_modules`` gained a ``module_item_in_scope(item.type,
file_filter)`` guard while ``file_filter`` was **not a parameter of that method,
never assigned in it, and not a module global** - a ``NameError`` on every module
Page or link, i.e. on most real courses, in the metadata scan that feeds the sync
analyzer. The whole suite passed, because every test of that fix asserted SOURCE
SHAPE and the shape was right.

So this file does not test a feature. It asserts a property of the tree:

    for every function, every name it loads is bound by that function, by an
    enclosing function, by the module, or by builtins.

SCOPE OF THE CHECK - deliberately narrow, so it cannot produce false alarms:
  * it catches "bound NOWHERE reachable" (NameError);
  * it does NOT catch "bound only on some paths" (UnboundLocalError) - the
    `isolate` bug's other half, which `tests/test_page_isolation_flat_mode.py`
    covers for the site that had it, because deciding reachability in general
    needs flow analysis and would misfire on ordinary early-return code.

A module with a star import is skipped: the binding set is genuinely unknowable
without importing, and this check must never guess.
"""
from __future__ import annotations

import ast
import builtins
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

# Directories that are not ours to police.
_SKIP_PARTS = {'.venv', 'build', 'dist', '__pycache__', '.git', 'node_modules'}

_BUILTINS = set(dir(builtins)) | {
    '__file__', '__name__', '__doc__', '__spec__', '__package__',
    '__loader__', '__builtins__', '__debug__',
}


def _bound_names(scope_node) -> set[str]:
    """Every name bound directly in *scope_node*, without entering a child scope.

    Parameters count, and so does anything a `global`/`nonlocal` declaration
    names - both are why a naive "is it assigned?" scan produces noise.
    """
    out: set[str] = set()
    if isinstance(scope_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        a = scope_node.args
        for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs]:
            out.add(arg.arg)
        if a.vararg:
            out.add(a.vararg.arg)
        if a.kwarg:
            out.add(a.kwarg.arg)

    def walk(node):
        for child in ast.iter_child_nodes(node):
            # A nested def/class BINDS its own name here and owns its body.
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(child.name)
                continue
            # Separate scopes that bind nothing in this one.
            if isinstance(child, (ast.Lambda, ast.ListComp, ast.SetComp,
                                  ast.DictComp, ast.GeneratorExp)):
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                out.add(child.id)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    out.add((alias.asname or alias.name).split('.')[0])
            elif isinstance(child, (ast.Global, ast.Nonlocal)):
                out.update(child.names)
            elif isinstance(child, ast.ExceptHandler) and child.name:
                out.add(child.name)
            elif isinstance(child, ast.MatchAs) and child.name:
                out.add(child.name)
            elif isinstance(child, ast.MatchStar) and child.name:
                out.add(child.name)
            elif isinstance(child, ast.MatchMapping) and child.rest:
                out.add(child.rest)
            walk(child)

    walk(scope_node)
    return out


def _loaded_names(scope_node):
    """``(name, lineno)`` for every load in *scope_node*, child scopes excluded.

    Child scopes are excluded because they are visited in their own right, with
    this scope's bindings added to theirs - which is what makes closures pass.
    """
    found = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                                  ast.ClassDef, ast.ListComp, ast.SetComp,
                                  ast.DictComp, ast.GeneratorExp)):
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                found.append((child.id, child.lineno))
            walk(child)

    walk(scope_node)
    return found


def unbound_loads(source: str, label: str = '<src>') -> list[tuple[int, str, str]]:
    """``(lineno, function, name)`` for every load nothing reachable binds."""
    tree = ast.parse(source)
    if any(isinstance(n, ast.ImportFrom) and any(a.name == '*' for a in n.names)
           for n in ast.walk(tree)):
        return []
    module_scope = _bound_names(tree) | _BUILTINS
    findings: list[tuple[int, str, str]] = []

    def visit(node, enclosing: set[str]):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scope = enclosing | _bound_names(child)
                for name, line in _loaded_names(child):
                    if name not in scope:
                        findings.append((line, child.name, name))
                visit(child, scope)
            elif isinstance(child, ast.ClassDef):
                # A class body's names are NOT visible to methods, so methods are
                # visited with the enclosing scope, not with the class's.
                visit(child, enclosing)
            else:
                visit(child, enclosing)

    visit(tree, module_scope)
    return findings


def _project_files() -> list[pathlib.Path]:
    return [p for p in sorted(REPO.rglob('*.py'))
            if not any(part in _SKIP_PARTS for part in p.parts)]


def test_no_function_reads_a_name_nothing_binds():
    hits = []
    for path in _project_files():
        try:
            src = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        for line, fn, name in unbound_loads(src, str(path)):
            hits.append(f"{path.relative_to(REPO)}:{line} {fn}() reads '{name}'")
    assert not hits, (
        "these names are bound in no reachable scope, so reading them raises "
        "NameError the first time the line executes:\n  " + "\n  ".join(hits))


# ── the instrument itself: it must be able to FAIL ───────────────────────────
#
# A scanner that reports 0 on a fixed tree proves nothing. These are its positive
# controls, and the first one is the exact defect that motivated the file.

def test_catches_the_real_defect_that_motivated_this_file():
    """`_get_files_from_modules` reading a `file_filter` it does not take."""
    src = '''
def module_item_in_scope(t, f):
    return True

class CanvasManager:
    def _get_files_from_modules(self, course, download_mode=None):
        for item in course.items:
            if not module_item_in_scope(item.type, file_filter):
                continue
'''
    hits = unbound_loads(src)
    assert [(h[1], h[2]) for h in hits] == [('_get_files_from_modules', 'file_filter')]


def test_the_fix_makes_it_pass():
    src = '''
def module_item_in_scope(t, f):
    return True

class CanvasManager:
    def _get_files_from_modules(self, course, download_mode=None, file_filter='all'):
        for item in course.items:
            if not module_item_in_scope(item.type, file_filter):
                continue
'''
    assert unbound_loads(src) == []


@pytest.mark.parametrize("src", [
    # a closure reading an enclosing local
    "def outer():\n    x = 1\n    def inner():\n        return x\n    return inner\n",
    # a global defined AFTER the function that reads it
    "def f():\n    return LATER\n\nLATER = 3\n",
    # global / nonlocal declarations
    "def f():\n    global G\n    G = 1\n    return G\n",
    "def o():\n    y = 0\n    def i():\n        nonlocal y\n        y += 1\n        return y\n    return i\n",
    # comprehension and lambda targets
    "def f(xs):\n    return [a for a in xs if a]\n",
    "def f(xs):\n    return sorted(xs, key=lambda k: k.b)\n",
    # walrus, with-as, except-as, for-else, star-args
    "def f(v):\n    if (n := v) > 0:\n        return n\n    return 0\n",
    "def f(p):\n    with open(p) as fh:\n        return fh.read()\n",
    "def f():\n    try:\n        pass\n    except OSError as e:\n        return e\n",
    "def f(*a, **k):\n    return a, k\n",
    # a function-scoped import, which is how this repo breaks import cycles
    "def f():\n    from core.sync_manager import SyncManager\n    return SyncManager\n",
    # match statement captures
    "def f(v):\n    match v:\n        case {'a': x, **rest}:\n            return x, rest\n        case [*items]:\n            return items\n        case other:\n            return other\n",
    # a method must NOT see class-body names... and must not be flagged for the
    # ones it legitimately reaches through self
    "class C:\n    ATTR = 1\n    def m(self):\n        return self.ATTR\n",
])
def test_no_false_positive(src):
    assert unbound_loads(src) == [], f"false positive on:\n{src}"


def test_a_star_import_is_skipped_rather_than_guessed():
    src = "from os.path import *\n\ndef f():\n    return join('a', 'b')\n"
    assert unbound_loads(src) == []
