"""The long-path gate check.

`scripts/check_longpath_gate.py` decides whether an audit run on this machine is
capable of catching a forgotten make_long_path. Its failure mode is the one it
exists to prevent: if the verdict is ever inverted or weakened, it reports VALID
on a masked machine, the audit that follows comes back clean, and the clean
result gets written down as evidence.

So the property pinned here is that the decision cannot silently become total.
Two of these tests would pass against a `verdict()` that always returned VALID -
`test_a_masked_machine_is_reported_as_masked` is the one that would not, and it
is the reason the others are safe to keep.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_longpath_gate.py"
_spec = importlib.util.spec_from_file_location("check_longpath_gate", _SCRIPT)
gate = importlib.util.module_from_spec(_spec)
sys.modules["check_longpath_gate"] = gate
_spec.loader.exec_module(gate)


def facts(unprefixed_ok: bool, prefixed_ok: bool, length: int = 300) -> dict:
    return {"length": length,
            "unprefixed_ok": unprefixed_ok,
            "prefixed_ok": prefixed_ok}


def test_an_enforcing_machine_is_reported_as_valid():
    code, text = gate.verdict(facts(unprefixed_ok=False, prefixed_ok=True))
    assert code == gate.VALID == 0
    assert "VALID" in text


def test_a_masked_machine_is_reported_as_masked():
    """The load-bearing one. Everything else here passes against a stub."""
    code, text = gate.verdict(facts(unprefixed_ok=True, prefixed_ok=True))
    assert code == gate.MASKED
    assert code != 0, "a masked gate MUST exit non-zero or CI will sail past it"
    assert "MASKED" in text


@pytest.mark.parametrize("unprefixed_ok", [True, False])
def test_a_failed_control_is_inconclusive_whatever_the_other_open_did(unprefixed_ok):
    """The control is checked FIRST, and this is why.

    If the prefixed open failed, the fixture was never readable and NOTHING was
    measured. Reporting VALID there would be an invention - "unprefixed raised"
    is then equally explained by a file that does not exist.
    """
    code, text = gate.verdict(facts(unprefixed_ok=unprefixed_ok, prefixed_ok=False))
    assert code == gate.INCONCLUSIVE
    assert "INCONCLUSIVE" in text


def test_the_three_verdicts_are_distinct_exit_codes():
    assert len({gate.VALID, gate.MASKED, gate.INCONCLUSIVE}) == 3
    assert gate.VALID == 0, "only the safe-to-proceed verdict may be zero"


def test_the_probe_length_clears_max_path_with_room():
    """A fixture near the 260 boundary would make the answer a coin toss."""
    assert gate.TARGET_PATH_CHARS >= 280


def test_the_self_test_exercises_every_branch():
    """A check that can only ever say PASS proves nothing, so the script ships
    with its own control. Run it here so the suite notices if it decays."""
    assert gate.self_test() == 0


@pytest.mark.skipif(os.name == "nt", reason="the not-applicable path is off-Windows")
def test_off_windows_is_not_applicable_and_exits_clean():
    assert gate.main() == gate.VALID


@pytest.mark.skipif(os.name != "nt", reason="Windows-only registry read")
def test_the_registry_read_never_raises():
    """It is context, not the verdict - so it must degrade to a string rather
    than take the check down on a locked-down or unusual machine."""
    assert isinstance(gate.read_registry_flag(), str)
