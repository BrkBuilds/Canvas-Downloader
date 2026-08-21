"""The audit-run PII scrubber.

The failure mode this file exists for is SILENCE. The scrubber's whole job is to
answer "is it safe to publish these runs?", and every way it can be wrong looks
exactly like a pass: a file it never opened is indistinguishable, in its report,
from a file that held nothing. So the tests here are about REACH - which files
the scrubber can see - at least as much as about the redaction patterns.

Measured 2026-08-21 on the laptop: `git ls-files` C-quotes any path holding a
non-ASCII byte, so a course folder named "...små systemer..." came back as
"...sm\\303\\245...", `Path.is_file()` answered False, and 37 in-scope text files
were dropped without a word while the scrubber printed CLEAN. Every Danish
course name in this operator's runs hits it.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scrub_audit_pii as scrub  # noqa: E402


PII_EMAIL = "someone.else@university.dk"
NON_ASCII_NAME = "seed_Programmering og udvikling af små systemer (LA E25).json"


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A throwaway git repo standing in for the real one.

    In tmp_path on purpose: this repo is routinely worked by more than one
    session, and a probe file written under the real tree is one concurrent
    `git add -A` away from being committed.
    """
    root = tmp_path / "probe"
    (root / "_audit_runs" / "run1" / "evidence").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, capture_output=True, check=True)
    monkeypatch.setattr(scrub, "REPO", root)
    return root


def _evidence(repo: Path, name: str, text: str) -> Path:
    p = repo / "_audit_runs" / "run1" / "evidence" / name
    p.write_text(text, encoding="utf-8")
    return p


def test_a_non_ascii_named_file_is_reached(repo):
    """The regression. The ASCII sibling is the control: without it, a scanner
    that reached nothing at all would pass this test by finding nothing wrong.
    """
    _evidence(repo, NON_ASCII_NAME, '{"who": "%s"}' % PII_EMAIL)
    _evidence(repo, "seed_plain.json", '{"who": "%s"}' % PII_EMAIL)

    names = {p.name for p in scrub.tracked_audit_files()}

    assert "seed_plain.json" in names, "the scan reached nothing - control failed"
    assert NON_ASCII_NAME in names, (
        "a non-ASCII-named file was dropped: git C-quotes the path and the "
        "resulting Path() does not exist, so it is skipped in silence"
    )


def test_untracked_files_are_in_scope(repo):
    """A fresh audit run is UNTRACKED. If the `--others` half regressed, a
    machine's own runs would go unscrubbed while its inherited ones passed.
    """
    _evidence(repo, "seed_plain.json", '{"who": "%s"}' % PII_EMAIL)
    assert {p.name for p in scrub.tracked_audit_files()} == {"seed_plain.json"}


def test_ignored_files_are_never_opened(repo):
    """Scope must follow .gitignore, so the stored token and the browser profile
    are out of reach rather than merely redacted.
    """
    (repo / ".gitignore").write_text(
        "_audit_runs/**/config/*\n", encoding="utf-8")
    cfg = repo / "_audit_runs" / "run1" / "config"
    cfg.mkdir(parents=True)
    (cfg / "settings.json").write_text('{"token": "1234~%s"}' % ("A" * 24),
                                       encoding="utf-8")
    _evidence(repo, "seed_plain.json", "{}")

    names = {p.name for p in scrub.tracked_audit_files()}
    assert "seed_plain.json" in names, "control failed - nothing was scanned"
    assert "settings.json" not in names


def test_binaries_are_out_of_scope(repo):
    """A partially redacted binary is worse than an excluded one."""
    (repo / "_audit_runs" / "run1" / "evidence" / "shot.png").write_bytes(b"\x89PNG")
    _evidence(repo, "seed_plain.json", "{}")
    assert {p.name for p in scrub.tracked_audit_files()} == {"seed_plain.json"}


@pytest.mark.parametrize("probe,label", [
    ("mail jane.doe@example.ac.uk now", "email address"),
    ("user bily20ab logged in", "canvas login id"),
    ("token 1234~" + "A" * 24, "canvas api token"),
    ("Authorization: Bearer " + "x" * 32, "bearer token"),
    ("jwt eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0", "jwt"),
])
def test_each_rule_fires(probe, label):
    out, counts = scrub.scrub_text(probe)
    assert label in counts, f"{label} did not fire on {probe!r}"
    assert out != probe


def test_scrubbing_is_idempotent():
    once, _ = scrub.scrub_text("write to jane.doe@example.ac.uk about bily20ab")
    twice, counts = scrub.scrub_text(once)
    assert twice == once
    assert not counts


def test_clean_text_is_left_alone():
    text = "Analysis complete: 12 new | 0 clean updates"
    out, counts = scrub.scrub_text(text)
    assert out == text
    assert not counts
