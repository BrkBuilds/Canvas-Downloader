"""The audit's documentation must describe the audit that exists.

A future session runs this suite from three files - the skill, the README and
the RUNBOOK - and follows them literally. A command that names a verb, a
subcommand or a flag the CLI does not have sends that session into
trial-and-error against a 73-row suite, which is expensive and looks like the
harness is broken.

So the docs are checked against `cli.py`'s real parser rather than trusted.
This is deliberately a STRUCTURAL check: it cannot tell you the prose is right,
only that every command in it can actually be run.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DOCS = (
    REPO / ".claude" / "skills" / "audit-live" / "SKILL.md",
    REPO / "tests" / "audit" / "README.md",
    REPO / "tests" / "audit" / "RUNBOOK.md",
    # The macOS set. Added 2026-08-10: these are followed on a RENTED machine,
    # where a command that argparse refuses costs money as well as time.
    REPO / "tests" / "audit" / "MAC_RUNBOOK.md",
    REPO / "tests" / "audit" / "MAC_AUDIT_PROMPT.md",
    REPO / "tests" / "audit" / "MAC_AUDIT_GUIDE.md",
)

# `python -m tests.audit [--run X] <verb> [<sub>] [--flags...]`, to end of line.
INVOCATION = re.compile(
    r"python -m tests\.audit\s+(?P<rest>[^\n`|]+)")


def _parser_tree() -> dict:
    """{verb: {subcommand: {flag, ...}}} read from the real parser."""
    import argparse
    from tests.audit import cli

    tree: dict = {}

    def walk(parser, into):
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, sub in action.choices.items():
                    into[name] = {}
                    walk(sub, into[name])

    root = cli.build_parser() if hasattr(cli, "build_parser") else None
    if root is None:                        # parser built inline in main()
        pytest.skip("cli.py does not expose a reusable parser")
    walk(root, tree)
    return tree


def _flags(parser) -> set[str]:
    import argparse
    out = set()
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            continue
        out.update(o for o in a.option_strings)
    return out


def _resolve(tokens: list[str]):
    """Walk a documented command through the real parser.

    Descends only on a token that IS a known subcommand; anything else at
    positional depth is an argument or a placeholder and is ignored. A bare
    word that looks like a subcommand but is not one is the error worth
    catching - a path, a quoted string or a `<placeholder>` is not.

    `--run` takes a value, and that value is often a `<placeholder>`, so the
    tokens must be walked RAW. Filtering placeholders first made `--run`
    swallow the verb after it - which is how this function's first version
    reported a perfectly valid documented command as unknown.
    """
    import argparse
    from tests.audit import cli
    parser = cli.build_parser()
    # Every parser walked through, not just the leaf: `--run` is declared on
    # the ROOT and is legal before any subcommand, so checking flags against
    # the leaf alone rejected `--run <parent> matrix recheck` - a command the
    # RUNBOOK documents and which works.
    chain = [parser]
    flags: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("-"):
            flags.append(tok)
            if tok == "--run":
                i += 1                      # its value, whatever it looks like
            i += 1
            continue
        subs = [a for a in parser._actions
                if isinstance(a, argparse._SubParsersAction)]
        if subs and tok in subs[0].choices:
            parser = subs[0].choices[tok]
            chain.append(parser)
        elif subs and re.fullmatch(r"[a-z][a-z\-]*", tok):
            raise AssertionError(
                f"unknown subcommand {tok!r}; have {sorted(subs[0].choices)}")
        i += 1
    return chain, flags


#: A shell line continued with a trailing backslash.
_CONTINUATION = re.compile(r"\\\s*\n\s*")


def _documented_commands() -> list[tuple[Path, str]]:
    """Every documented invocation, with backslash continuations JOINED.

    The join is load-bearing for the required-positional and required-flag
    checks below: `INVOCATION` stops at the newline, so a perfectly correct

        python -m tests.audit check download "<folder>" --course-id <id> \\
            --expect @cfg.json

    was being read as its first line only and reported as omitting `--expect`.
    The original flag check never noticed, because it only ever asked whether
    the flags PRESENT were real - truncation can only hide flags, never invent
    a bad one. Two checks that need the WHOLE command changed that.
    """
    out = []
    for doc in DOCS:
        if not doc.is_file():
            continue
        text = _CONTINUATION.sub(" ", doc.read_text(encoding="utf-8"))
        for m in INVOCATION.finditer(text):
            line = m.group("rest").split("#")[0].strip()
            if line and not line.startswith("-h"):
                out.append((doc, line))
    return out


def test_the_docs_actually_contain_commands():
    """A guard on the guard: a regex that stops matching passes silently."""
    cmds = _documented_commands()
    assert len(cmds) > 25, f"only found {len(cmds)} documented invocations"


@pytest.mark.parametrize("doc,line", _documented_commands(),
                         ids=lambda v: v if isinstance(v, str) else Path(v).name)
def test_every_documented_command_exists(doc, line):
    """Every `python -m tests.audit ...` in the docs resolves against the parser.

    Placeholders (`<id>`, `...`) are ignored - only verbs, subcommands and
    long flags are checked, because those are what a reader copies verbatim.
    """
    chain, flags = _resolve([t for t in line.split() if t not in ("...", "|")])
    known = set().union(*(_flags(p) for p in chain))
    unknown = [f for f in flags if f.split("=")[0] not in known]
    assert not unknown, (
        f"{Path(doc).name}: `{line}`\n  unknown flag(s) {unknown}; "
        f"this subcommand accepts {sorted(known)}")


def _required_positionals(parser) -> list[str]:
    """Positional args the parser will refuse to run without.

    Subparser actions are excluded - those ARE the subcommands, and a doc line
    is allowed to stop at a verb (e.g. `python -m tests.audit finding list`
    versus the bare `finding`, which the caller never writes on its own).
    """
    import argparse
    out = []
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction) or a.option_strings:
            continue
        if a.nargs in ("?", "*") or getattr(a, "default", None) is not None:
            continue
        out.append(a.dest)
    return out


@pytest.mark.parametrize("doc,line", _documented_commands(),
                         ids=lambda v: v if isinstance(v, str) else Path(v).name)
def test_every_documented_command_supplies_its_required_positionals(doc, line):
    """A required POSITIONAL is as copy-pasteable-wrong as an unknown flag.

    This check did not exist, and that is exactly how three docs came to show

        python -m tests.audit finding add --scenario <id> --category <cat> ...

    which argparse rejects outright: `title` is positional and required. The
    flag check above passes it happily, because every flag in it is real. A
    reader following it loses the time it takes to discover argparse's error -
    on a rented machine, during the one session that had to go right.
    """
    tokens = [t for t in line.split() if t not in ("...", "|")]
    chain, _flags_seen = _resolve(tokens)
    leaf = chain[-1]
    needed = _required_positionals(leaf)
    if not needed:
        return

    # Count the tokens that could be serving as positionals: everything that is
    # not a flag, not a flag's value, and not one of the subcommand words we
    # descended through. Quoted strings survive .split() as several tokens, so
    # this counts generously - the point is to catch ZERO, not to count exactly.
    import argparse
    consumed, i, given = set(), 0, 0
    parser = cli_parser()
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("-"):
            i += 2 if tok == "--run" or "=" not in tok else 1
            continue
        subs = [a for a in parser._actions
                if isinstance(a, argparse._SubParsersAction)]
        if subs and tok in subs[0].choices:
            parser = subs[0].choices[tok]
        else:
            given += 1
        i += 1

    assert given >= len(needed), (
        f"{Path(doc).name}: `{line}`\n"
        f"  needs {len(needed)} positional argument(s) {needed} but shows {given}.\n"
        f"  argparse will refuse this command as written.")


def cli_parser():
    from tests.audit import cli
    return cli.build_parser()


@pytest.mark.parametrize("doc,line", _documented_commands(),
                         ids=lambda v: v if isinstance(v, str) else Path(v).name)
def test_every_documented_command_supplies_its_required_flags(doc, line):
    """The other half of the same class.

    `check download` needs BOTH a positional `folder` and a required
    `--expect`; the skill showed neither. A required flag is exactly as
    copy-paste-wrong as a required positional, and the original flag check only
    ever asked whether the flags PRESENT were real - never whether the ones
    absent were mandatory.
    """
    tokens = [t for t in line.split() if t not in ("...", "|")]
    chain, flags = _resolve(tokens)
    seen = {f.split("=")[0] for f in flags}
    missing = []
    for a in chain[-1]._actions:
        if a.option_strings and getattr(a, "required", False):
            if not any(o in seen for o in a.option_strings):
                missing.append(a.option_strings[-1])
    assert not missing, (
        f"{Path(doc).name}: `{line}`\n"
        f"  omits required flag(s) {missing}; argparse will refuse it.")


def test_the_required_flag_check_would_actually_fail_on_a_bad_line():
    """Guard on the guard, in the direction that matters."""
    chain, flags = _resolve("check download somefolder --course-id 1".split())
    required = [a.option_strings[-1] for a in chain[-1]._actions
                if a.option_strings and getattr(a, "required", False)]
    assert "--expect" in required, (
        f"expected --expect to be required on `check download`, got {required}")
    assert "--expect" not in {f.split("=")[0] for f in flags}


def test_the_positional_check_would_actually_fail_on_a_bad_line():
    """Validate the guard in the direction that matters.

    A checker that can never fire is worse than no checker - `README.md` ground
    rule 7. This asserts the real failure mode it was written for.
    """
    import argparse
    bad = "finding add --scenario x --category y --severity high"
    tokens = bad.split()
    chain, _ = _resolve(tokens)
    needed = _required_positionals(chain[-1])
    assert needed == ["title"], f"expected a required `title`, got {needed}"

    parser = cli_parser()
    i, given = 0, 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("-"):
            i += 2
            continue
        subs = [a for a in parser._actions
                if isinstance(a, argparse._SubParsersAction)]
        if subs and tok in subs[0].choices:
            parser = subs[0].choices[tok]
        else:
            given += 1
        i += 1
    assert given == 0, "the counter should see no positional in the bad line"


def test_the_skill_points_at_the_runbook_and_readme():
    """The skill is short by design; it must hand off to the two long docs."""
    skill = DOCS[0].read_text(encoding="utf-8")
    assert "RUNBOOK.md" in skill and "README.md" in skill


def test_the_skill_documents_the_matrix_workflow():
    """Driving 73 rows by hand is the failure this section prevents.

    The matrix is how a full audit runs - deterministic, resumable, and
    partitioned across lanes that cannot share Office or the GPU. A skill that
    omits it sends the next session down a path that takes days.
    """
    skill = DOCS[0].read_text(encoding="utf-8")
    for verb in ("matrix build", "matrix prepare", "matrix launch",
                 "matrix lanes", "matrix recheck", "matrix collect"):
        assert verb in skill, f"the skill never mentions `{verb}`"


def test_the_skill_states_the_recheck_contract():
    """`recheck` is the difference between a finding and an artefact of when
    the checker happened to be fixed. Its limit matters as much as its use."""
    skill = DOCS[0].read_text(encoding="utf-8").lower()
    assert "evidence, checker" in skill or "(evidence, checker)" in skill
    assert "filewatchertype=none" in skill, (
        "the skill must say why a re-check cannot fix a product-stale finding")


def test_the_skill_warns_that_the_checker_is_under_test():
    skill = DOCS[0].read_text(encoding="utf-8").lower()
    assert "checker is under test" in skill
    assert "both directions" in skill, (
        "a new check has to be validated in both directions or it can be one "
        "that never fires")
