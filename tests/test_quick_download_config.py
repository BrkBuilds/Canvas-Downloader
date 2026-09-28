"""Quick Download: the configuration PREVIEW is the configuration that RUNS.

Owner report 2026-09-07 (tests/audit/OWNER_REPORTS.md #1): "See configuration"
did not reflect what was chosen on the page. Confirmed by reading: the panel
rendered the raw preset, while "Confirm and Download" ran the preset with the
page's "Choose how files are organized" answer applied - and the "Customize"
hand-off carried a third, hand-written copy of that rule. Two sources of truth
for one run. `quick_run_settings` is now the only one.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ui import quick_download as qd

SRC = Path(qd.__file__).read_text(encoding="utf-8")


@pytest.mark.parametrize("org", ["modules", "flat"])
def test_the_page_organisation_choice_WINS_over_the_preset(org):
    for preset in qd._QUICK_PRESETS:
        out = qd.quick_run_settings(preset, org)
        assert out["download_mode"] == org, preset["id"]
        # everything else is the preset's own
        for k, v in preset["settings"].items():
            if k != "download_mode":
                assert out[k] == v, (preset["id"], k)


def test_the_preset_itself_is_never_mutated():
    preset = qd._QUICK_PRESETS[0]
    before = dict(preset["settings"])
    qd.quick_run_settings(preset, "flat" if before["download_mode"] != "flat" else "modules")
    assert preset["settings"] == before, "a preview changed the preset for every later run"


def _render_fn() -> ast.FunctionDef:
    tree = ast.parse(SRC)
    return next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "render_quick_download")


def test_the_PREVIEW_is_built_by_the_one_function():
    """The badge call must take `quick_run_settings(...)` as its settings."""
    calls = [n for n in ast.walk(_render_fn()) if isinstance(n, ast.Call)
             and getattr(n.func, "id", getattr(n.func, "attr", "")) == "render_config_summary_badges"]
    assert calls, "the configuration preview is gone"
    for c in calls:
        arg = c.args[0]
        assert isinstance(arg, ast.Call) and getattr(arg.func, "id", "") == "quick_run_settings", (
            "the preview is built from something other than the settings the run executes")


def test_NO_site_composes_run_settings_from_a_preset_by_hand():
    """A census, not a spot check: `dict(<x>['settings'])` inside the page is
    how the second and third copies were written. Only the helper may do it."""
    offenders = []
    for n in ast.walk(_render_fn()):
        if (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "dict" and n.args
                and isinstance(n.args[0], ast.Subscript)
                and isinstance(n.args[0].slice, ast.Constant)
                and n.args[0].slice.value == "settings"):
            offenders.append(n.lineno)
    assert not offenders, f"hand-composed run settings at lines {offenders}"
    uses = [n for n in ast.walk(_render_fn()) if isinstance(n, ast.Call)
            and getattr(n.func, "id", "") == "quick_run_settings"]
    assert len(uses) == 3, f"expected preview, run and hand-off: found {len(uses)}"
