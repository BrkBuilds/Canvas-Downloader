"""One AppleScript escaper, three callers - and why the rule is written once.

An AppleScript string literal cannot span lines. A raw ``\\n`` OR ``\\r`` inside
one is a syntax error that takes the whole script down; a bare ``"`` or ``\\`` is
an injection. Three places in this app build such a literal, they all agreed on
quotes and backslashes, and exactly one of them flattened only ``\\n``:

    engine/applescript_bridge._as_posix                \\n \\r  ok
    shared/helpers.native_folder_picker                \\n \\r  ok
    engine/notifications._show_macos_notification      \\n      WRONG

The wrong one takes a Canvas course name (the daily-sync summary body), and its
failure is silent: osascript rejects the script, the surrounding ``except
Exception`` logs at debug level, and the notification simply never appears.

Same divergent-primitive shape as ``make_long_path``'s duplicate in
``core/sync_manager.py`` - a rule written more than once is a rule some caller
is following an old version of. These tests therefore check BOTH the escaping
behaviour and that every builder actually routes through the shared function;
the latter by AST, because a leftover ``import applescript_string`` keeps the
name in the file long after the call using it is gone.
"""
import ast
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engine.applescript_bridge import applescript_string, _as_posix  # noqa: E402

#: Every character that must not survive into a literal, and why.
BREAKERS = {
    "\n": "newline ends the literal",
    "\r": "carriage return ends the literal",
    '"': "unescaped quote closes the literal",
}


def _reads_as_one_literal(script: str) -> bool:
    """True if every ``"`` in *script* is either a delimiter or escaped.

    A cheap stand-in for the AppleScript parser: walk the string and require
    that it opens and closes cleanly and that no literal contains a line break.
    """
    if "\n" in script or "\r" in script:
        return False
    i, depth = 0, 0
    while i < len(script):
        c = script[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            depth ^= 1
        i += 1
    return depth == 0


# --------------------------------------------------------------- behaviour

@pytest.mark.parametrize("bad, why", list(BREAKERS.items()))
def test_no_breaker_survives_into_the_literal(bad, why):
    out = applescript_string(f"Lec{bad}ture")
    script = f'display notification "{out}"'
    assert _reads_as_one_literal(script), f"{why}: {script!r}"


def test_a_backslash_is_doubled_not_dropped():
    # It must be escaped rather than removed: the string is shown to the user
    # (a course name) and silently losing characters is its own defect.
    assert applescript_string("a\\b") == "a\\\\b"


def test_backslash_is_escaped_before_the_quote():
    """Order matters: quote-first would re-escape the backslash it just added.

    ``a"b`` -> quote-first gives ``a\\"b`` then backslash-first turns the escape
    itself into ``a\\\\"b``, which closes the literal. Backslash-first is the
    only correct order.
    """
    assert _reads_as_one_literal(f'x "{applescript_string(chr(92) + chr(34))}"')


def test_both_line_breaks_become_a_space_not_nothing():
    # A space keeps two words apart; deleting the break would join them.
    assert applescript_string("a\nb") == "a b"
    assert applescript_string("a\rb") == "a b"


def test_it_accepts_a_non_string(tmp_path):
    # _as_posix hands it a Path; a course name could arrive as None.
    assert applescript_string(tmp_path) == str(tmp_path).replace("\\", "\\\\")
    assert applescript_string(None) == "None"


def test_as_posix_still_resolves_and_escapes(tmp_path):
    p = tmp_path / "a b" / "c.doc"
    assert _as_posix(p) == applescript_string(p.resolve())


# ------------------------------------------------------- the real callers

def test_the_notification_fallback_survives_a_carriage_return():
    """The reported class, driven through the REAL function.

    Reproduces via the daily-sync body, which carries a Canvas course name.
    """
    import engine.notifications as N

    captured = {}

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return mock.Mock()

    # `import subprocess` lives inside notifications.py's `if system ==
    # 'Darwin':` block, so off macOS the name is absent and this path would die
    # on a NameError inside its own try/except - making the assertion below
    # pass against a script that was never built. Inject it.
    with mock.patch.object(N, "_show_macos_notification_un", lambda *a: False), \
         mock.patch.object(N, "_show_macos_notification_native", lambda *a: False), \
         mock.patch.object(N, "_PyncNotifier", None, create=True), \
         mock.patch.object(N, "subprocess",
                           mock.Mock(Popen=fake_popen, DEVNULL=-3), create=True):
        N._show_macos_notification("Daily sync", "3 new files in Statistik\r2025.")

    assert captured.get("cmd"), "osascript was never invoked - the check is vacuous"
    script = captured["cmd"][-1]
    assert _reads_as_one_literal(script), script


@pytest.mark.parametrize("module, func", [
    ("engine/notifications.py", "_show_macos_notification"),
    ("shared/helpers.py", "native_folder_picker"),
    ("engine/applescript_bridge.py", "_as_posix"),
])
def test_every_applescript_builder_routes_through_the_shared_escaper(module, func):
    """Matched on the CALL via AST, never on the token.

    A reverted fix that leaves ``from engine.applescript_bridge import
    applescript_string`` behind satisfies a substring test while nothing runs.
    """
    tree = ast.parse((REPO / module).read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == func), None)
    assert fn is not None, f"{func} not found in {module}"

    calls = {n.func.id for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "applescript_string" in calls, (
        f"{module}:{func} builds an AppleScript literal without the shared "
        f"escaper - see engine.applescript_bridge.applescript_string")


@pytest.mark.parametrize("module, func", [
    ("engine/notifications.py", "_show_macos_notification"),
    ("shared/helpers.py", "native_folder_picker"),
])
def test_no_builder_keeps_a_hand_rolled_escape_chain(module, func):
    """The copies must be GONE, not merely bypassed.

    A dormant ``.replace('\\\\', '\\\\\\\\')`` chain beside the shared call is the
    exact thing that lets the rule drift back apart.
    """
    tree = ast.parse((REPO / module).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == func)
    replaces = [n for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "replace" and n.args
                and isinstance(n.args[0], ast.Constant)
                and n.args[0].value in ('\\', '"', '\n', '\r')]
    assert not replaces, (
        f"{module}:{func} still hand-rolls AppleScript escaping "
        f"({len(replaces)} .replace calls)")


def test_the_shared_escaper_stays_importable_from_its_callers():
    """No MODULE-LEVEL app import in applescript_bridge, or the callers cycle.

    ``shared/helpers.py`` and ``engine/notifications.py`` both import from this
    module now, and it imports ``shared.helpers.get_config_dir`` back. That is
    safe *because* every one of those imports is function-scoped: nothing runs
    at import time, so there is no cycle to resolve. A module-level app import
    added here would turn all three into one - hence the level check rather
    than a blanket ban, which would flag the existing lazy import and read as a
    violation where there is none.
    """
    tree = ast.parse((REPO / "engine/applescript_bridge.py").read_text(encoding="utf-8"))
    local = {p.name for p in REPO.iterdir()
             if p.is_dir() and (p / "__init__.py").exists()}
    module_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    for node in module_level:
        mods = ([node.module] if isinstance(node, ast.ImportFrom) and node.module
                else [a.name for a in node.names])
        for m in mods:
            assert m.split(".")[0] not in local, (
                f"applescript_bridge imports app module {m!r} at module level")


def test_importing_the_two_callers_together_does_not_cycle():
    """Proved by importing, not by reading the import graph."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import shared.helpers, engine.notifications, engine.applescript_bridge;"
         "print(engine.applescript_bridge.applescript_string('ok'))"],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().endswith("ok")


def test_the_escaper_is_importable_without_macos():
    """It is reached from Windows code paths too (via the shared helpers)."""
    out = subprocess.run(
        [sys.executable, "-c",
         "from engine.applescript_bridge import applescript_string;"
         "print(applescript_string('a\\rb'))"],
        cwd=REPO, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "a b"
