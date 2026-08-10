"""The macOS audit tooling must work on a machine that is being paid for.

`scripts/mac_audit_bootstrap.sh` and `scripts/mac_audit_doctor.py` are run on a
RENTED Mac, twice (once per OS install), by an agent that cannot ask anyone for
help. A typo'd filename or a doctor that crashes on its own output is not a
minor defect there - it is the first ten minutes of a paid session spent
debugging the thing that was supposed to save time.

These tests are deliberately cheap and structural. They cannot tell you the
bootstrap installs the right things; they can tell you it parses, that every
file the documentation points at exists, and that the doctor answers.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

DOCTOR = REPO / "scripts" / "mac_audit_doctor.py"
BOOTSTRAP = REPO / "scripts" / "mac_audit_bootstrap.sh"
FIRST_CONTACT = REPO / "scripts" / "mac_first_contact.sh"
EYES = REPO / "scripts" / "mac_eyes.py"
MAC_DOCS = [REPO / "tests" / "audit" / n for n in
            ("MAC_RUNBOOK.md", "MAC_AUDIT_PROMPT.md", "MAC_AUDIT_GUIDE.md")]


def test_the_tooling_exists():
    for p in [DOCTOR, BOOTSTRAP, FIRST_CONTACT, EYES, *MAC_DOCS]:
        assert p.is_file(), f"missing {p.relative_to(REPO)}"


def test_first_contact_parses_and_does_the_four_things_that_matter():
    """It is the ONLY thing typed in the slow VNC console, so it has to earn
    that session: SSH on, no sleep, no auto-lock, and the connect instructions."""
    import shutil
    bash = shutil.which("bash")
    if bash:
        r = subprocess.run([bash, "-n", str(FIRST_CONTACT)],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
    text = FIRST_CONTACT.read_text(encoding="utf-8")
    for needle, why in (
        ("setremotelogin", "enable SSH - without it you are stuck in VNC"),
        ("pmset", "stop the machine sleeping mid-audit"),
        ("screensaver", "stop auto-lock blocking the Automation prompts"),
        ("tmux new -s audit", "start the session from the DESKTOP"),
        ("screencapture", "how to see the screen without a remote desktop"),
        ("Parsec", "warn that Parsec cannot host on macOS"),
    ):
        assert needle in text, f"first contact never covers: {why}"


def test_first_contact_installs_what_a_BARE_mac_lacks():
    """The first version assumed a developer machine and cost the user an hour.

    A rented Mac has no Xcode tools, no Homebrew, no IDE and - the one that
    actually bit - **no Microsoft Office**. Having an M365 *licence* is not
    having Word installed, and the guide cheerfully said "open Word and sign
    in" on a machine where Word did not exist.
    """
    text = FIRST_CONTACT.read_text(encoding="utf-8")
    for needle, why in (
        ("xcode-select", "Xcode Command Line Tools - git and compilers need them"),
        ("Homebrew", "Homebrew, which every cask below depends on"),
        ("visual-studio-code", "an IDE - explicitly asked for and originally omitted"),
        ("--install-extension", "VS Code extensions"),
        ("anthropic.claude-code", "the agent's own VS Code extension"),
        ("remote-ssh", "Remote-SSH, which is how the IDE reaches the Mac"),
        ("linkid=525133", "the Office suite download"),
        ("installer -pkg", "actually installing Office, not just mentioning it"),
        ("python@3.11", "the pinned Python the .app is built with"),
    ):
        assert needle in text, f"a bare Mac would still be missing: {why}"


def test_first_contact_orders_brew_before_anything_that_needs_it():
    """The original had `brew install --cask nomachine` guarded by
    `command -v brew` and printed 'Homebrew not installed yet' - i.e. the cask
    silently never ran, because brew came later in a DIFFERENT script."""
    text = FIRST_CONTACT.read_text(encoding="utf-8")
    brew_install = text.index("Homebrew")
    for cask in ("visual-studio-code", "nomachine"):
        assert text.index(cask) > brew_install, (
            f"{cask} is installed before Homebrew exists - it will silently skip")


def test_first_contact_keeps_sudo_alive():
    """It runs 30-45 minutes unattended. A sudo timeout mid-way stalls it
    forever at a prompt nobody is watching."""
    text = FIRST_CONTACT.read_text(encoding="utf-8")
    assert "sudo -v" in text and "sudo -n true" in text, \
        "no sudo keepalive - the script will stall silently"


def test_first_contact_says_office_still_needs_a_sign_in():
    """Installing Office does not licence it, and a silent licence dialog makes
    the entire converter phase read as broken."""
    text = FIRST_CONTACT.read_text(encoding="utf-8")
    assert "does NOT license" in text or "does NOT licence" in text


def test_mac_eyes_parses_and_exposes_its_subcommands():
    ast.parse(EYES.read_text(encoding="utf-8"))
    r = subprocess.run([sys.executable, str(EYES), "--help"],
                       cwd=REPO, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    for sub in ("shot", "watch", "windows", "dialogs", "dock"):
        assert sub in r.stdout, f"mac_eyes lost the {sub!r} subcommand"


def test_mac_eyes_is_honest_about_tcc_prompts():
    """macOS refuses synthetic clicks on consent prompts BY DESIGN. A tool that
    implied otherwise would send an agent into an unwinnable loop."""
    text = EYES.read_text(encoding="utf-8")
    assert "synthetic clicks" in text and "consent" in text


def test_the_doctor_is_valid_python():
    ast.parse(DOCTOR.read_text(encoding="utf-8"))


def test_the_doctor_runs_and_emits_parseable_json():
    """It must answer on ANY platform.

    The doctor is the first thing run on the Mac, and the last thing run after
    each fix. If it can only be executed on macOS it cannot be smoke-tested
    here - so it reports "not macOS" as an ordinary blocking result instead of
    crashing, and that property is what this asserts.
    """
    r = subprocess.run([sys.executable, str(DOCTOR), "--json", "--quick"],
                       cwd=REPO, capture_output=True, text=True, timeout=600)
    payload = json.loads(r.stdout)
    assert "ready" in payload and "results" in payload
    assert len(payload["results"]) >= 10, payload
    names = {c["check"] for c in payload["results"]}
    # The check that exists because getting it wrong costs hours.
    assert any("Aqua" in n or "GUI" in n for n in names) or sys.platform != "darwin"


def test_the_doctor_output_survives_a_legacy_console():
    """A diagnostic must never fail on its own printing.

    The first version used a box-drawing character and died with
    UnicodeEncodeError on a cp1252 console - i.e. the tool whose job is to
    report problems became one.
    """
    src = DOCTOR.read_text(encoding="utf-8")
    printed = re.findall(r'print\((.*?)\)\n', src, re.S)
    for chunk in printed:
        for ch in chunk:
            assert ord(ch) < 128 or ch in "─│", (
                f"non-ASCII {ch!r} in a print(); use ASCII in diagnostics")


def test_the_doctor_checks_the_things_that_block_an_audit():
    """A preflight that omits the expensive failures is decoration."""
    src = DOCTOR.read_text(encoding="utf-8")
    for needle, why in (
        ("launchctl", "the Aqua session check - the costliest thing to get wrong"),
        ("proc_translated", "Rosetta detection"),
        ("CanvasDownloader", "the Keychain token lookup"),
        ("playwright", "the browser the audit drives the app through"),
        ("Microsoft Word", "Office presence, for the highest-risk phase"),
        ("TCC.db", "Full Disk Access"),
        ("tests.audit", "the harness itself answering"),
    ):
        assert needle in src, f"the doctor never checks {why}"


@pytest.mark.skipif(not (REPO / "scripts" / "mac_audit_bootstrap.sh").is_file(),
                    reason="bootstrap absent")
def test_the_bootstrap_parses_as_shell():
    """`bash -n` if bash is reachable; a structural read otherwise.

    Windows dev machines have Git Bash, CI has a real one. Where neither
    exists this degrades to checking the shape rather than skipping silently.
    """
    import shutil
    bash = shutil.which("bash")
    if bash:
        r = subprocess.run([bash, "-n", str(BOOTSTRAP)],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash"), "missing shebang"
    assert text.count("step ") >= 8, "the bootstrap lost its steps"


def test_the_bootstrap_is_idempotent_by_construction():
    """It is run TWICE - once per macOS install. Every expensive step must be
    guarded by a check that lets the second run skip it."""
    text = BOOTSTRAP.read_text(encoding="utf-8")
    for guard in ("if [ -x", "if [ -d", "if [ -f", "command -v"):
        assert guard in text, f"no {guard!r} guard - the second run would redo everything"
    assert "already" in text.lower(), "no step reports itself as already done"


def test_the_bootstrap_never_hardcodes_a_secret():
    """Secrets come from ~/mac_audit_secrets.env, never from the repo."""
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "mac_audit_secrets.env" in text
    # A Canvas token is a long opaque string; nothing that shape belongs here.
    assert not re.search(r"\b[0-9]{4,5}~[A-Za-z0-9]{20,}", text), \
        "a Canvas token literal is committed in the bootstrap"


@pytest.mark.parametrize("doc", MAC_DOCS, ids=lambda p: p.name)
def test_every_repo_path_the_mac_docs_mention_exists(doc):
    """A typo'd filename is discovered on the rented machine otherwise."""
    text = doc.read_text(encoding="utf-8")
    refs = set(re.findall(r"`((?:scripts|tests|core|panopto|shared|engine|"
                          r"converters|ui)/[A-Za-z0-9_./-]+)`", text))
    refs |= set(re.findall(r"\b((?:scripts|tests)/[A-Za-z0-9_./-]+\.(?:py|sh|md))\b", text))
    missing = sorted(r for r in refs
                     if not (REPO / r).exists() and "<" not in r)
    assert not missing, f"{doc.name} points at non-existent {missing}"


def test_the_prompt_hands_the_agent_the_documents_it_needs():
    prompt = (REPO / "tests/audit/MAC_AUDIT_PROMPT.md").read_text(encoding="utf-8")
    for needed in ("MAC_RUNBOOK.md", "RUNBOOK.md", "README.md", "CLAUDE.md"):
        assert needed in prompt, f"the prompt never points at {needed}"


def test_the_prompt_states_the_aqua_rule_and_the_oracle_rule():
    """The two rules that decide whether a day's results mean anything."""
    prompt = (REPO / "tests/audit/MAC_AUDIT_PROMPT.md").read_text(encoding="utf-8")
    assert "Aqua" in prompt and "managername" in prompt, \
        "the prompt must state the GUI-session rule; without it osascript, " \
        "Playwright and TCC all fail in different confusing ways"
    assert "two oracles" in prompt, "the prompt must state the finding rule"


def test_the_runbook_says_what_the_harness_cannot_reach():
    """The audit drives Chrome over CDP; the shipped app renders in WKWebView.

    A runbook that does not say so leaves the reader believing the packaged
    app was covered by the matrices.
    """
    rb = (REPO / "tests/audit/MAC_RUNBOOK.md").read_text(encoding="utf-8")
    assert "WKWebView" in rb and "CDP" in rb


def test_the_guide_tells_the_user_to_push_before_renting():
    """The Mac clones from GitHub. Uncommitted work is audited nowhere."""
    guide = (REPO / "tests/audit/MAC_AUDIT_GUIDE.md").read_text(encoding="utf-8")
    assert "push" in guide.lower() and "commit" in guide.lower()


# ── mac_smoke.py: every symbol it reaches for must exist ────────────────────

SMOKE = REPO / "scripts" / "mac_smoke.py"

#: Modules that only exist on macOS, so importing them here proves nothing.
_MAC_ONLY = {"UserNotifications", "objc", "Foundation", "AppKit"}


def _smoke_imports() -> list[tuple[str, str]]:
    """[(module, name)] for every `from <app module> import ...` in mac_smoke."""
    tree = ast.parse(SMOKE.read_text(encoding="utf-8"))
    local = {p.name for p in REPO.iterdir()
             if p.is_dir() and (p / "__init__.py").exists()}
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in local:
                out.extend((node.module, a.name) for a in node.names)
    return out


def test_the_smoke_script_imports_something_from_the_app():
    """Guard on the guard - an extractor that stops matching passes silently."""
    found = _smoke_imports()
    assert len(found) >= 12, f"only found {len(found)} app imports: {found}"


@pytest.mark.parametrize("module,name", _smoke_imports(),
                         ids=lambda v: str(v))
def test_every_symbol_mac_smoke_uses_actually_exists(module, name):
    """`mac_smoke.py` cannot be executed off macOS, so a wrong name is
    discovered on the rented machine - the most expensive place to find it.

    This has already happened twice in one session: a probe called
    `detect_gpu()` (the real name is `detect_compute_hardware`), which made the
    check return None and pass; and `ui.auth.get_config_dir`, which does not
    exist, behind a `hasattr` guard that therefore always skipped - reporting
    PASS while inspecting nothing. Resolve the names here, where it is free.
    """
    if module.split(".")[-1] in _MAC_ONLY:
        pytest.skip(f"{module} is macOS-only")
    mod = __import__(module, fromlist=[name])
    assert hasattr(mod, name), (
        f"mac_smoke.py imports {name!r} from {module}, which does not define it")


def test_mac_smoke_refuses_to_run_off_macos():
    """It must exit clearly rather than half-run and report nonsense."""
    r = subprocess.run([sys.executable, str(SMOKE)], cwd=REPO,
                       capture_output=True, text=True, timeout=300)
    if sys.platform == "darwin":
        pytest.skip("running on macOS - this asserts the refusal path")
    assert r.returncode == 2, r.stdout[-400:]
    assert "only means anything on macOS" in (r.stderr + r.stdout)


def test_mac_smoke_never_degrades_a_check_into_nothing():
    """A `hasattr`/`getattr` fallback around an app symbol is how a check comes
    to pass while testing nothing. Ban the pattern outright in this file."""
    tree = ast.parse(SMOKE.read_text(encoding="utf-8"))
    bad = [n.lineno for n in ast.walk(tree)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
           and n.func.id == "hasattr"]
    assert not bad, (
        f"hasattr() at line(s) {bad} - resolve the symbol properly or let it "
        f"raise; a silently-skipped check is worse than a missing one")
