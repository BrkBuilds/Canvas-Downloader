"""macOS: the app must not ask for Accessibility, and case-only renames must not delete.

Two findings from the 2026-08-10 live macOS audit, kept together because both are
consequences of one rule: **a primitive whose semantics differ per platform must
not be relied on for a decision that destroys data or costs the user a permission.**

1. ``engine/applescript_bridge`` used to prepend
   ``set visible of (first process whose name is "Microsoft Word") to false``
   (System Events) to every Office conversion. That demanded **Accessibility**,
   the one macOS prompt with no Allow button - it cannot be granted from the
   dialog, its primary action is Deny, and it says "control this computer" on an
   app that ships unsigned. Measured: it also hid the USER'S OWN Word session
   (their open document vanished mid-work), and it bought nothing - a cold Word
   driven by the real converter was visible 0/7 samples with the call REMOVED
   versus 2/11 with it. See the long note in the bridge for the full trace.

2. ``sync/execution`` decided whether to delete a superseded secondary-content
   copy with ``os.path.normcase``, which is the IDENTITY off Windows. On macOS's
   case-insensitive default volume a case-only Canvas rename made two strings
   that name ONE file compare as different, so the sync deleted the file it had
   just written. Reproduced 2026-08-10.
"""
from __future__ import annotations

import ast
import inspect
import os
import re
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
APP_DIRS = ("core", "converters", "engine", "panopto", "shared", "sync", "ui")
APP_FILES = [REPO / "app.py", REPO / "sync_ui.py", REPO / "start.py"]


def _app_sources() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for d in APP_DIRS:
        out += [(p, p.read_text(encoding="utf-8")) for p in (REPO / d).rglob("*.py")]
    out += [(p, p.read_text(encoding="utf-8")) for p in APP_FILES if p.exists()]
    return out


def _strip_comments(src: str) -> str:
    """Blank out COMMENTS only - never string literals.

    The bridge deliberately DOCUMENTS the removed AppleScript in a comment, and a
    naive substring scan would read that explanation as the defect it describes
    (the "documenting a fix trips the rule that polices it" trap this repo has
    hit before). So comments must go.

    String literals must NOT. AppleScript reaches osascript as a **Python
    string**, always - so a real regression reintroducing the Accessibility call
    would live inside a literal, which is precisely what this scan exists to
    catch. An earlier version of this helper blanked literals too, and a
    mutation that re-added the System Events hide to ``run_applescript``
    SURVIVED it: the guard was reading only prose.
    """
    out = []
    for line in textwrap.dedent(src).splitlines():
        q = None
        cut = len(line)
        i = 0
        while i < len(line):
            c = line[i]
            if q:
                if c == "\\":
                    i += 2
                    continue
                if c == q:
                    q = None
            elif c in "\"'":
                q = c
            elif c == "#":
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return "\n".join(out)


# ── 1. no Accessibility-requiring AppleScript anywhere in the app ──

# Unambiguous AppleScript that manipulates ANOTHER process. None of these can
# occur outside AppleScript, so they are scanned everywhere.
ACCESSIBILITY_MARKERS = (
    "set visible of",          # hiding/showing another process  <- the removed call
    "set frontmost of",        # activating another process
    "AXUIElement",
    "UI element",
)

# Synthetic input. These words occur innocently in this app's JavaScript bridges
# ("one rerun per keystroke") and in prose, so they are only meaningful in a file
# that actually RUNS AppleScript. Scoping by `osascript` keeps the check precise;
# scanning them globally produced four false positives in ui/ and sync_ui.py.
ACCESSIBILITY_MARKERS_APPLESCRIPT_ONLY = (
    "keystroke",
    "key code",
    "click at",
)


def test_no_app_code_requires_accessibility():
    """Accessibility is the one prompt a first-run user cannot grant in place."""
    hits = []
    for path, src in _app_sources():
        code = _strip_comments(src)
        for marker in ACCESSIBILITY_MARKERS:
            if marker in code:
                hits.append(f"{path.relative_to(REPO)}: {marker!r}")
        if "osascript" in code:
            for marker in ACCESSIBILITY_MARKERS_APPLESCRIPT_ONLY:
                if marker in code:
                    hits.append(f"{path.relative_to(REPO)}: {marker!r}")
    assert not hits, (
        "these would raise the macOS Accessibility prompt, which has NO Allow "
        "button and cannot be granted from the dialog:\n  " + "\n  ".join(hits)
    )


def test_visibility_prefix_is_gone():
    import engine.applescript_bridge as AB
    assert not hasattr(AB, "_visibility_prefix")
    src = inspect.getsource(AB.run_applescript)
    code = _strip_comments(src)
    assert "System Events" not in code, (
        "run_applescript must not talk to System Events - that is what cost the "
        "Accessibility grant"
    )


def test_priming_still_launches_hidden_without_system_events():
    """`open -g -j` is the permission-free way to launch hidden; keep it."""
    import engine.applescript_bridge as AB
    src = inspect.getsource(AB._prime_office_apps_sync
                            if hasattr(AB, "_prime_office_apps_sync") else AB)
    text = src if isinstance(src, str) else ""
    hay = text or (REPO / "engine" / "applescript_bridge.py").read_text(encoding="utf-8")
    assert "'-g', '-j', '-a'" in hay or '"-g", "-j", "-a"' in hay, (
        "the hidden launch (open -g -j) is what keeps Office out of sight; it "
        "needs no TCC grant, unlike the System Events hide it replaced"
    )
    code = _strip_comments(hay)
    assert "set visible of" not in code


def test_all_three_office_converters_share_the_one_runner():
    """One runner is why removing the hide covered Word, Excel AND PowerPoint.

    The staging fix earlier the same day had to be checked the same way: a
    per-app copy is how a fix lands on one of three.
    """
    for mod, app in (("converters/word.py", '"Word"'),
                     ("converters/excel.py", '"Excel"'),
                     ("converters/pdf.py", '"PowerPoint"')):
        src = (REPO / mod).read_text(encoding="utf-8")
        assert "_convert_applescript(" in src, mod
        assert app in src, mod
        assert "run_applescript" in src or "_convert_applescript" in src, mod


def test_first_run_notice_promises_only_answerable_prompts():
    from engine.applescript_bridge import TCC_FIRST_RUN_NOTICE as N
    assert "Allow" in N and "OK" in N
    assert "ccessibility" not in N, (
        "the app no longer raises an Accessibility prompt; mentioning it would "
        "send users hunting in System Settings for a toggle they do not need"
    )


def test_notice_has_exactly_one_definition():
    """It had two byte-identical copies and was wrong in both."""
    body = "First-time macOS setup"
    defining = [p.relative_to(REPO) for p, s in _app_sources() if body in s]
    assert len(defining) == 1, f"copy has drifted into several files: {defining}"


# ── the notice must describe WHEN a prompt appears, not just WHICH ──
#
# Both properties below were false in shipped copy until 2026-08-14. They are
# the same class as the Accessibility bug above: the constant lives beside the
# mechanism precisely so the two change together, and twice now only the
# mechanism moved.

def test_system_events_is_not_promised_as_part_of_the_opening_batch():
    """It is raised by the TEARDOWN, so the notice must not imply it comes now.

    ``first_run_permission_setup`` primes ``_APP_TRIPLES`` and nothing else, so
    the System Events Automation prompt only arrives when
    ``quit_idle_office_apps`` runs on the completion screen. Telling the user to
    expect it up front leaves an unanswered dialog at the end of the run - which
    is the state that strands Office open with its Recents unpurged.
    """
    import engine.applescript_bridge as AB

    primed = {ms for _key, ms, _short in AB._APP_TRIPLES}
    assert "System Events" not in primed, (
        "the batch now primes System Events - if that is deliberate, the notice "
        "may go back to listing it with the others, and this test should say so"
    )

    notice = AB.TCC_FIRST_RUN_NOTICE
    if "System Events" in notice:
        assert re.search(r"finish|end of|when the run|afterwards", notice, re.I), (
            "the notice names System Events but not that it comes at the END of "
            "the run; the batch does not prime it (see _APP_TRIPLES above)"
        )


def test_notice_does_not_claim_an_unqualified_only_asked_once():
    """macOS 15's App Data consent is per SESSION - the app said otherwise.

    ``arm_app_data_access`` exists because that consent expires when the app
    quits, so an unqualified "you are only asked once" is a promise the platform
    breaks on every relaunch.
    """
    import engine.applescript_bridge as AB

    notice = AB.TCC_FIRST_RUN_NOTICE
    assert hasattr(AB, "arm_app_data_access"), (
        "the per-session re-arm is what makes this claim false - if it is gone, "
        "re-check whether the notice may promise a single prompt again"
    )
    if re.search(r"only asked once|asked only once", notice, re.I):
        assert re.search(r"per session|each session|once per session", notice, re.I), (
            "'only asked once' must be qualified: on macOS 15+ the "
            "'access data from other apps' prompt returns every session unless "
            "Full Disk Access is granted"
        )
    assert re.search(r"session", notice, re.I), (
        "the notice must mention the per-session macOS 15+ prompt at all - it is "
        "the one dialog a user will otherwise think is a bug"
    )


# ── 2. the case-only rename must not delete the file just written ──

def _case_insensitive_here(tmp_path: Path) -> bool:
    probe = tmp_path / "CaseProbe.tmp"
    probe.write_text("x", encoding="utf-8")
    try:
        return (tmp_path / "caseprobe.tmp").exists()
    finally:
        probe.unlink(missing_ok=True)


def test_superseded_delete_guard_uses_path_key_not_normcase():
    src = (REPO / "sync" / "execution.py").read_text(encoding="utf-8")
    m = re.search(r"if \(is_update_clean and _sec_old_path is not None.*?\):",
                  src, re.S)
    assert m, "the superseded-copy delete guard moved - re-anchor this test"
    guard = _strip_comments(m.group(0))
    assert "_path_key(" in guard, (
        "the guard deciding an UNLINK must use _path_key; normcase is the "
        "identity off Windows, so on macOS it deleted the file just written"
    )
    assert "normcase" not in guard


def test_case_only_rename_is_recognised_as_the_same_file(tmp_path):
    """The actual defect, end to end, against the real primitive."""
    from core.sync_manager import _path_key
    if not _case_insensitive_here(tmp_path):
        pytest.skip("volume is case-sensitive - the two names really are two files")
    old = tmp_path / "Week 1 Assignment.html"       # manifest's recorded path
    new = tmp_path / "week 1 assignment.html"       # canonical name after rename
    new.write_text("regenerated - current version", encoding="utf-8")
    assert os.path.samefile(old, new), "same file on a case-insensitive volume"
    assert _path_key(old) == _path_key(new), (
        "_path_key must fold these together, or the delete guard removes the "
        "file the regenerate just wrote and the user is left with nothing"
    )
    # and the raw comparison the code used to make is the bug:
    assert os.path.normcase(str(old)) != os.path.normcase(str(new)) or os.name == "nt"


def test_case_sensitive_volume_still_treats_them_as_two_files(tmp_path):
    """The fold must be conditional - an external case-sensitive drive holds both."""
    from core.sync_manager import _path_key
    if _case_insensitive_here(tmp_path):
        pytest.skip("need a case-sensitive volume for this direction")
    assert _path_key(tmp_path / "A.pdf") != _path_key(tmp_path / "a.pdf")


def test_dispatch_target_claim_folds_case():
    src = (REPO / "sync" / "execution.py").read_text(encoding="utf-8")
    m = re.search(r"def _claim_target\(p\):.*?return cand", src, re.S)
    assert m, "_claim_target moved - re-anchor"
    body = _strip_comments(m.group(0))
    assert "_path_key(" in body and "normcase" not in body, (
        "two Canvas files whose names differ only in case are ONE file on a "
        "case-insensitive volume; the claim set must fold or they overwrite"
    )


def test_conversion_protection_folds_case():
    import core.sync_manager as SM
    for fn in (SM.SyncManager.protect_conversion_target,
               SM.SyncManager.is_conversion_target_protected):
        body = _strip_comments(inspect.getsource(fn))
        assert "_path_key(" in body, f"{fn.__name__} must key through _path_key"
        assert "normcase" not in body, (
            f"{fn.__name__}: Path.resolve() does not canonicalise case on macOS, "
            "so a missed mark overwrites the student's edited output"
        )


def test_owner_map_emptiness_is_tested_on_the_raw_value():
    """normpath('') is '.', so keying first turns "no path" into a real lookup."""
    from core.sync_manager import _path_key
    assert _path_key("") == ".", "if this changes, revisit the raw-value guard"
    src = (REPO / "core" / "sync_manager.py").read_text(encoding="utf-8")
    assert "_lp_norm = _path_key(_lp_raw) if _lp_raw else ''" in src
