"""The global Panopto switch must actually stop a run.

Why this file exists
--------------------
``panopto_globally_enabled`` shipped as an almost entirely COSMETIC setting. It
had exactly two readers - ``shared/legal.py`` and the Settings dialog - and
neither sat on an execution path, so switching Panopto off:

* left Custom Download's Card 4 live and still fetched every selected output,
* left three of the five Quick Download presets fetching recordings,
* left the sync page running the full discovery pass and downloading,

while ``shared/legal.require_panopto_notice`` logged *"Panopto skipped: turned
off in Settings"* and returned True so the run proceeded unchanged. Only the
Today daily sync honoured it, and only because ``core/auto_sync.py`` sets the
run-scoped decline flag for a different reason.

Two pieces of shipped copy already specified the behaviour that did not exist -
``ui/auth.py``'s *"Off means: no institution lookup, no discovery, no
acceptable-use dialog, and no recordings in any download or sync"* and the
toggle's own tooltip, *"the search is skipped entirely, so downloads and syncs
finish faster"*. So this was a bug with its spec written in a comment above the
control, not a feature request.

What the tests pin
------------------
1. ``effective_contract`` is the ONE resolver, and it is a pure function of the
   switch - it never mutates or persists anything. Turning Panopto off is a
   statement about the future, so a folder's stored contract and the user's
   Section 4 selections must survive it and come back when it is switched on.
2. Each of the three run entry points consults it (or the switch directly).
   Asserted structurally, because the alternative is standing up three whole
   runtimes, and because the failure mode being guarded is precisely "someone
   adds a fourth path and does not know this rule exists".
3. **Gate PLACEMENT**, which is the subtle one and the reason a "guard it in the
   runner, nothing can bypass that" fix would be actively destructive: the
   download-mode phase seeds each folder's stored ``panopto_contract`` BEFORE it
   calls the batch, and ``sync_ui`` only ever seeds ``if ... is None``, so a
   download run is the only thing that can overwrite it. A runner-only gate
   would let the phase start, write an all-off contract over every folder it
   touched, and turn a reversible preference into permanent data loss.
4. ``is_enabled`` stays switch-BLIND, because display code asks it what a folder
   or preset is configured for. Same for ``compose_settings``, which
   ``extract_contract`` seeds from.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from panopto import settings as S


REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    """Redirect the shared settings file into a throwaway directory.

    ``_config_path`` imports ``get_config_dir`` lazily from ``shared.helpers``,
    so the patch has to land on the helpers module, not on this one.
    """
    from shared import helpers
    monkeypatch.setattr(helpers, "get_config_dir", lambda: str(tmp_path))
    return tmp_path


def _src(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    """Blank out ``#`` comments so a rule can be DOCUMENTED without satisfying it.

    Every assertion below is about code that runs. Without this, writing "we do
    not call effective_contract here" in a comment would pass the test that
    checks the call exists.
    """
    return re.sub(r"#[^\n]*", "", src)


def _func_node(rel: str, name: str) -> ast.AST:
    for node in ast.walk(ast.parse(_src(rel))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {rel}")


def _func_src(rel: str, name: str) -> str:
    """Source of one top-level or nested function, comments stripped."""
    return _strip_comments(
        ast.get_source_segment(_src(rel), _func_node(rel, name)) or ""
    )


#: Every spelling of the global-switch read. sync/analysis.py and sync_ui.py
#: alias it on import, so matching the bare name would miss them.
_SWITCH_NAMES = {"is_globally_enabled", "_pan_globally_enabled"}


def _calls_switch(node: ast.AST) -> bool:
    """True when *node* CALLS the switch - never merely names it.

    The distinction is the whole point. Four mutations of the real code survived
    an earlier, substring-based version of these tests purely because
    ``from panopto.settings import is_globally_enabled`` keeps the NAME in the
    function body after the guard using it has been deleted. Matching the call
    is what makes the assertion about code that runs.
    """
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            fn = n.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if name in _SWITCH_NAMES:
                return True
    return False


def _switch_guard(rel: str, func: str) -> ast.If:
    """The single ``if not <switch>(): ...`` statement inside *func*.

    Fails when the guard is absent, duplicated, or WEAKENED into a compound test
    - ``if False and not is_globally_enabled():`` keeps the call in the source
    and reads fine in review while disabling the guard completely, which is
    exactly how one mutant escaped.
    """
    fn = _func_node(rel, func)
    guards = [n for n in ast.walk(fn)
              if isinstance(n, ast.If) and _calls_switch(n.test)]
    assert len(guards) == 1, (
        f"expected exactly one global-switch guard in {rel}:{func}, "
        f"found {len(guards)}"
    )
    test = guards[0].test
    assert isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not), (
        f"{rel}:{func}'s guard is no longer a bare `not <switch>()`. A compound "
        f"test keeps the call in the source while neutering the guard."
    )
    return guards[0]


def _guard_body_src(rel: str, guard: ast.If) -> str:
    src = _src(rel)
    return _strip_comments(
        "\n".join(ast.get_source_segment(src, s) or "" for s in guard.body)
    )


ALL_OUTPUTS_ON = {
    "output_url": True, "output_mp4": True, "output_mp3": True,
    "output_txt": True, "output_srt": True, "layout": "separate",
}


# ═══════════════════════════════════════════════════════════════════════════
# effective_contract - the one resolver
# ═══════════════════════════════════════════════════════════════════════════

def test_switch_on_passes_the_contract_through_unchanged(config_dir):
    """On is the identity case. Anything else would change behaviour for the
    overwhelming majority of users, who never touch this setting."""
    assert S.set_globally_enabled(True) is True
    assert S.effective_contract(ALL_OUTPUTS_ON) == ALL_OUTPUTS_ON


def test_switch_off_disables_every_output(config_dir):
    """The whole point. Read the key list off the module so an output added
    later cannot slip through a hand-written tuple here."""
    assert S.set_globally_enabled(False) is True
    eff = S.effective_contract(ALL_OUTPUTS_ON)
    assert S.is_enabled(eff) is False
    for key in S._OUTPUT_KEYS:
        assert eff[key] is False, f"{key} survived the global switch"


def test_default_is_on_so_an_absent_key_changes_nothing(config_dir):
    """Off-by-default would strip a headline feature from every existing install
    on the first launch after an update."""
    assert S.is_globally_enabled() is True
    assert S.effective_contract(ALL_OUTPUTS_ON) == ALL_OUTPUTS_ON


def test_off_does_not_mutate_the_caller_s_contract(config_dir):
    """The stored contract is the folder's configuration. If this resolver
    mutated in place, one analysis pass would silently rewrite it and the user's
    outputs would not come back when they switched Panopto on again."""
    assert S.set_globally_enabled(False) is True
    stored = dict(ALL_OUTPUTS_ON)
    S.effective_contract(stored)
    assert stored == ALL_OUTPUTS_ON


def test_off_then_on_restores_the_original_outputs(config_dir):
    """The round trip a real user makes. Off is a statement about the future."""
    stored = dict(ALL_OUTPUTS_ON)
    S.set_globally_enabled(False)
    assert S.is_enabled(S.effective_contract(stored)) is False
    S.set_globally_enabled(True)
    assert S.effective_contract(stored) == ALL_OUTPUTS_ON


@pytest.mark.parametrize("switch", [True, False])
def test_resolution_performs_no_write(config_dir, monkeypatch, switch):
    """Resolution is a pure read. A write here is how a preference toggle turns
    into data loss.

    Asserted on the WRITE, not on the resulting bytes, and that distinction is
    load-bearing: a mutant that re-persisted the settings from this function
    produced a byte-IDENTICAL file, so comparing content saw nothing at all. The
    invariant is "this function does not write", which only a spy can state.

    Both branches, too. An earlier version exercised only the off branch, and
    the mutant lived in the on branch - the one nearly every user takes, on
    every run.
    """
    S.set_globally_enabled(switch)

    writes = []
    _real_open = open

    def _spy_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wxa+"):
            writes.append(f"open({file!s}, {mode!r})")
        return _real_open(file, mode, *args, **kwargs)

    _real_replace = S.os.replace

    def _spy_replace(src, dst, *args, **kwargs):
        writes.append(f"os.replace -> {dst!s}")
        return _real_replace(src, dst, *args, **kwargs)

    # The module calls the bare builtins, so a module-level name shadows them.
    monkeypatch.setattr(S, "open", _spy_open, raising=False)
    monkeypatch.setattr(S.os, "replace", _spy_replace)

    S.effective_contract(ALL_OUTPUTS_ON)

    assert writes == [], f"effective_contract wrote to disk: {writes}"
    assert S.is_globally_enabled() is switch


@pytest.mark.parametrize("stored", [None, {}])
def test_an_empty_contract_is_unchanged_by_the_switch_being_on(config_dir, stored):
    """Falsy in, falsy out, so an existing call site can swap `stored` for
    `effective_contract(stored)` with no other change."""
    S.set_globally_enabled(True)
    assert S.effective_contract(stored) is stored


@pytest.mark.parametrize("stored", [None, {}])
def test_an_empty_contract_is_still_disabled_when_off(config_dir, stored):
    S.set_globally_enabled(False)
    assert S.is_enabled(S.effective_contract(stored)) is False


def test_the_off_contract_has_the_full_contract_shape(config_dir):
    """It flows into compose_settings / extract_contract, both of which read
    every contract key."""
    S.set_globally_enabled(False)
    eff = S.effective_contract(ALL_OUTPUTS_ON)
    assert set(eff) == set(S._CONTRACT_KEYS)


def test_composing_the_off_contract_yields_a_disabled_run(config_dir):
    """compose_settings(None) deliberately returns the DEFAULTS, which have
    mp3/txt/srt ON - so passing the off CONTRACT, not None, is what matters."""
    S.set_globally_enabled(False)
    composed = S.compose_settings(S.effective_contract(ALL_OUTPUTS_ON))
    assert composed["enabled"] is False
    assert S.active_outputs(composed) == []


# ═══════════════════════════════════════════════════════════════════════════
# The switch must NOT leak into the predicates display code asks
# ═══════════════════════════════════════════════════════════════════════════

def test_is_enabled_ignores_the_global_switch(config_dir):
    """is_enabled answers "what is this configured for", which several viewers
    ask in order to DISPLAY it - the sync hub's stored config, the preset cards,
    and the ignored-recordings dialog's "which kinds count as configured". Make
    it switch-aware and a folder set up for recordings reports that it never
    was."""
    S.set_globally_enabled(False)
    assert S.is_enabled(ALL_OUTPUTS_ON) is True


def test_compose_settings_ignores_the_global_switch(config_dir):
    """extract_contract seeds a folder's stored contract from this. If the
    switch reached in here, a download run would persist all-off."""
    S.set_globally_enabled(False)
    assert S.compose_settings(ALL_OUTPUTS_ON)["enabled"] is True


def test_contract_to_ui_keys_ignores_the_global_switch(config_dir):
    """The badge renderer's input. Config viewers dim the pills and say "won't
    run"; they must not silently report a configuration the folder does not
    have."""
    S.set_globally_enabled(False)
    assert S.contract_to_ui_keys(ALL_OUTPUTS_ON)["pan_out_mp4"] is True


def test_the_switch_is_not_a_contract_key():
    """In PANOPTO_DEFAULTS it would be copied into every composed run config and
    persisted into every synced folder's manifest."""
    assert S.GLOBAL_ENABLED_KEY not in S.PANOPTO_DEFAULTS
    assert S.GLOBAL_ENABLED_KEY not in S.effective_contract(dict(S.PANOPTO_DEFAULTS))


# ═══════════════════════════════════════════════════════════════════════════
# Every run entry point is gated
# ═══════════════════════════════════════════════════════════════════════════

def test_download_phase_trigger_resolves_the_effective_contract():
    """app.py:_next_phase_after_courses is download mode's gate."""
    fn = _func_src("app.py", "_next_phase_after_courses")
    assert "effective_contract(" in fn, (
        "the download-mode phase trigger no longer applies the global Panopto "
        "switch - Card 4's selections would be fetched with Panopto off"
    )
    assert "is_enabled(effective_contract(" in fn, (
        "effective_contract must WRAP the contract is_enabled sees; calling it "
        "and discarding the result is the shape a mutation would leave behind"
    )


def test_download_gate_sits_above_the_stored_contract_seed():
    """THE placement rule, and the reason a runner-only guard is destructive.

    The 'panopto' phase writes each folder's panopto_contract before running the
    batch. Gating below that point would overwrite every folder's saved Panopto
    configuration with all-off the moment someone switched the feature off - and
    sync_ui only seeds `if ... is None`, so nothing would ever restore it.
    """
    src = _strip_comments(_src("app.py"))
    gate = src.index("def _next_phase_after_courses")
    seed = src.index("'panopto_contract'")
    assert gate < seed, "the phase trigger must be resolvable before the seed runs"

    # And the seed must still be reachable ONLY from inside the phase, i.e. the
    # phase is what the gate controls.
    phase = src.index("== 'panopto'")
    assert phase < seed, (
        "the panopto_contract seed escaped the 'panopto' phase branch - it is "
        "now reachable without passing the gate"
    )


def _run_download_gate(contract: dict | None) -> str:
    """Execute app.py's REAL ``_next_phase_after_courses`` source.

    ``app.py`` cannot be imported (module-level ``st.*`` calls), so the function
    is lifted out by AST and exec'd against a stub for its one input - the user's
    Section 4 selections. Everything else, including the import and the call
    chain under test, is the shipped source.

    Re-implementing the expression here instead would be worthless: the whole
    body sits inside ``except Exception: pass``, so a NameError degrades to
    ``'done'`` silently. That is the safe direction, which is exactly why it
    could hide indefinitely - and why the ON case below is the load-bearing
    assertion, not the OFF one.
    """
    node = _func_node("app.py", "_next_phase_after_courses")
    ns: dict = {"_panopto_run_contract": lambda: contract}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), ns)
    return ns["_next_phase_after_courses"]()


def test_download_gate_runs_the_phase_while_switched_on(config_dir):
    """The load-bearing half. A NameError in that function is swallowed into
    'done', so only a positive result proves the code actually executes."""
    S.set_globally_enabled(True)
    assert _run_download_gate(ALL_OUTPUTS_ON) == 'panopto'


def test_download_gate_skips_the_phase_while_switched_off(config_dir):
    S.set_globally_enabled(False)
    assert _run_download_gate(ALL_OUTPUTS_ON) == 'done'


def test_download_gate_still_skips_an_empty_selection(config_dir):
    """Unchanged behaviour for the overwhelmingly common case."""
    S.set_globally_enabled(True)
    assert _run_download_gate(None) == 'done'


def test_sync_analysis_skips_the_whole_pass_when_switched_off():
    """The expensive one: discovery is a per-recording LTI handshake."""
    src = _strip_comments(_src("sync/analysis.py"))
    assert "is_globally_enabled as _pan_globally_enabled" in src
    assert "_pan_on = _pan_globally_enabled()" in src
    assert "if _pan_on and _pan_is_enabled(_pan_contract):" in src, (
        "the Panopto discovery pass no longer checks the global switch"
    )


def test_sync_analysis_reads_no_stored_contract_while_switched_off():
    """Off means the search is skipped ENTIRELY - no read, no heal, no write.
    The heal path calls _save_metadata, so leaving it live would write to a
    folder during a run that is not using the feature."""
    src = _strip_comments(_src("sync/analysis.py"))
    assert "sync_mgr._load_metadata('panopto_contract') if _pan_on else None" in src
    assert "if _pan_on and _pan_contract is None:" in src, (
        "the contract-recovery heal (which WRITES) is no longer gated on the "
        "global switch"
    )


def test_sync_analysis_gate_precedes_discovery():
    src = _strip_comments(_src("sync/analysis.py"))
    assert src.index("_pan_on = _pan_globally_enabled()") < src.index(
        "discover_course_videos"
    )


def test_the_composed_settings_local_is_never_read_outside_its_guard():
    """``_pan`` is BOUND INSIDE the gated branch, so every read must be too.

    Gating this pass meant moving ``_pan = compose_settings(...)`` into the
    ``if``. A single surviving read below it would be an ``UnboundLocalError``
    on exactly the new path - the switched-off one - and this module swallows
    the whole Panopto block in a bare ``except Exception``, so it would surface
    as a logged warning and a silently absent payload, never a traceback.

    That is not hypothetical here: the repo has already shipped this precise
    bug once (``isolate`` in ``core/canvas_logic.py``), where every structural
    test passed because the SHAPE was right, and one real download revealed a
    course that fetched nothing at all.
    """
    fn = _func_node("sync/analysis.py", "_analyze_course_blocking")

    def _pan_names(node, ctx):
        return [n for n in ast.walk(node)
                if isinstance(n, ast.Name) and n.id == "_pan"
                and isinstance(n.ctx, ctx)]

    binds = _pan_names(fn, ast.Store)
    assert len(binds) == 1, f"expected one `_pan =`, found {len(binds)}"

    guards = [n for n in ast.walk(fn)
              if isinstance(n, ast.If)
              and any(isinstance(t, ast.Name) and t.id == "_pan_on"
                      for t in ast.walk(n.test))
              and _pan_names(n, ast.Store)]
    assert len(guards) == 1, (
        "could not find the single `if _pan_on and ...:` block that binds _pan"
    )
    guard = guards[0]
    lo, hi = guard.lineno, guard.end_lineno

    reads = [n for n in ast.walk(fn)
             if isinstance(n, ast.Name) and n.id == "_pan"
             and isinstance(n.ctx, ast.Load)]
    assert reads, "the _pan local is no longer read at all - dead code?"
    outside = [n.lineno for n in reads if not (lo <= n.lineno <= hi)]
    assert not outside, (
        f"_pan is read at line(s) {outside}, outside the guard that binds it "
        f"(lines {lo}-{hi}) - UnboundLocalError whenever Panopto is switched off"
    )


def test_sync_terminal_phase_refuses_to_run_when_switched_off():
    """Defence in depth, not the gate - and it must be LOUD, because reaching it
    means an earlier gate did not hold."""
    guard = _switch_guard("sync_ui.py", "_run_sync_panopto")
    body = _guard_body_src("sync_ui.py", guard)

    assert "logger.warning" in body, (
        "a bypassed gate must leave a trace. A silent skip here is "
        "indistinguishable from the feature working correctly - and the "
        "surrounding function logs warnings for unrelated reasons, so this has "
        "to be asserted on the GUARD's body, not on the function's"
    )
    assert "sync_complete" in body, (
        "the guard no longer routes the run anywhere - it would fall through "
        "into the Panopto batch it exists to prevent"
    )

    fn = _func_src("sync_ui.py", "_run_sync_panopto")
    assert fn.index("_pan_globally_enabled()") < fn.index("run_panopto_batch("), (
        "the switch is checked after the batch call - it cannot prevent anything"
    )


def test_the_acceptable_use_notice_is_not_raised_when_switched_off():
    """A legal modal about an action the analysis gate has already prevented."""
    guard = _switch_guard("sync_ui.py", "_sync_pairs_want_panopto")
    assert "return False" in _guard_body_src("sync_ui.py", guard)


def _first_loop_line(rel: str, func: str) -> int:
    loops = [n for n in ast.walk(_func_node(rel, func)) if isinstance(n, ast.For)]
    assert loops, f"{rel}:{func} has no loop to short-circuit"
    return min(n.lineno for n in loops)


@pytest.mark.parametrize(
    "func", ["_sync_pairs_want_transcription", "_sync_pairs_want_panopto"]
)
def test_the_switch_short_circuits_before_the_per_pair_loop(func):
    """Both helpers run on the sync page and open a SyncManager PER PAIR.

    Position is the assertion, and it must be taken from the guard STATEMENT.
    Reading it from the first occurrence of the name lets a guard that has been
    moved inside the loop still pass, because the `from panopto.settings import
    is_globally_enabled` line sits above the loop either way - which is how that
    mutant escaped the first version of this test.
    """
    guard = _switch_guard("sync_ui.py", func)
    assert guard.lineno < _first_loop_line("sync_ui.py", func), (
        f"{func}'s global-switch guard is inside the per-pair loop; it costs a "
        f"SQLite connection per pair, on every render, to reach the same answer"
    )


def test_every_run_entry_point_is_covered():
    """A census, so a fourth path cannot be added without this failing.

    Deliberately matched on the CALL, not the name: an import line or a comment
    mentioning the function satisfies a substring test while nothing runs.
    """
    entry_points = {
        "app.py": "effective_contract(",
        "sync/analysis.py": "_pan_globally_enabled()",
        "sync_ui.py": "is_globally_enabled()",
    }
    for rel, call in entry_points.items():
        assert call in _strip_comments(_src(rel)), (
            f"{rel} no longer applies the global Panopto switch"
        )
