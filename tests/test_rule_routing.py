"""The repo's own lessons must REACH the file you are about to edit.

WHY THIS FILE EXISTS, and it is not housekeeping. On 2026-09-13 the product
owner asked how several sessions could each build, verify and declare the
browser-extension sign-in working while it was fundamentally broken. One cause
was structural and is fixed here.

`.claude/rules/*.md` load only when Claude opens a file matching their `paths:`
frontmatter. `browser-login.md` is 2,200 lines of hard-won specifics for the
sign-in feature, and its `paths:` listed FOUR files:

    core/canvas_auth.py, core/browser_login.py, ui/auth.py, start.py

The feature that broke is `core/handoff.py`, `extension/`, `dev.py` and
`scripts/check_handoff.py`. **None of them was on that list.** So the rules
written for exactly this feature never loaded in the files that implement it.
Worse, `scripts/check_*.py` is claimed by `release-and-packaging.md`, so the
sign-in feature's own verification tool loaded PACKAGING rules: not merely the
absent context, the wrong one.

The general shape, which is what this test guards: **a rule file routed by
filename delivers nothing to a NEW file, and a new file is exactly where the
accumulated lessons are needed.** Nobody notices, because the absence of a rule
looks identical to there being no rule.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_RULES = _ROOT / '.claude' / 'rules'

#: Directories whose modules are "the app" for routing purposes.
_SOURCE_DIRS = ('core', 'ui', 'sync', 'engine', 'converters', 'panopto',
                'shared')

#: Top-level modules that are part of the app rather than tooling.
_TOP_LEVEL = ('app.py', 'sync_ui.py', 'start.py', 'dev.py', 'version.py')

#: Files DELIBERATELY claimed by no rule file, each with the reason.
#:
#: An entry here is a decision, which is the point: adding a module and leaving
#: it unrouted has to be something somebody chose and wrote down, not something
#: that happened. If you are adding to this list, ask first whether the module
#: really has no hard-won lesson attached - and if it does, route it instead.
_UNROUTED_BY_DESIGN = {
    'version.py': 'one string, read by CI and both build specs',
    'engine/__init__.py': 'empty package marker',
    'engine/estimation.py': 'ETA arithmetic; no recorded defect class',
    'engine/notifications.py': 'thin per-platform toast wrappers',
    'engine/office_pid.py': 'covered in practice by converters-office.md, '
                            'which owns every caller',
}


def _rule_claims() -> dict[str, list[str]]:
    """Each rule file's `paths:` globs."""
    claims: dict[str, list[str]] = {}
    for f in sorted(_RULES.glob('*.md')):
        parts = f.read_text(encoding='utf-8').split('---', 2)
        claims[f.name] = (re.findall(r'-\s*"([^"]+)"', parts[1])
                          if len(parts) >= 3 else [])
    return claims


def _matches(rel: str, pattern: str) -> bool:
    """Does POSIX path *rel* match one `paths:` entry?

    Deliberately small. `fnmatch` has no recursive `**` and `PurePath.match`
    only grew one in 3.13, while CI pins 3.11 - so a `dir/**` prefix is handled
    directly rather than relying on either.
    """
    if pattern.endswith('/**'):
        return rel.startswith(pattern[:-2])
    if '/' not in pattern:
        return fnmatch.fnmatch(rel.rsplit('/', 1)[-1], pattern)
    return fnmatch.fnmatch(rel, pattern)


def _source_files() -> list[str]:
    found: list[str] = []
    for d in _SOURCE_DIRS:
        for p in sorted((_ROOT / d).rglob('*.py')):
            if '__pycache__' in p.parts:
                continue
            found.append(p.relative_to(_ROOT).as_posix())
    for t in _TOP_LEVEL:
        if (_ROOT / t).exists():
            found.append(t)
    ext = _ROOT / 'extension'
    if ext.is_dir():
        found += [p.relative_to(_ROOT).as_posix()
                  for p in sorted(ext.glob('*.js'))]
    return found


def _owners(rel: str, claims: dict[str, list[str]]) -> list[str]:
    return [name for name, pats in claims.items()
            if any(_matches(rel, p) for p in pats)]


@pytest.fixture(scope='module')
def claims():
    if not _RULES.is_dir():
        pytest.skip(".claude/rules is not present in this checkout")
    found = _rule_claims()
    if not found:
        pytest.skip(".claude/rules holds no rule files")
    return found


def test_every_source_file_is_ROUTED_to_a_rule_file(claims):
    """A census, not a spot check.

    It fails on a NEW unrouted module rather than asserting that some
    particular routing exists - the same shape this repo uses for its other
    "did the fix reach every site" guards, and for the same reason: the thing
    that goes wrong is always the site nobody thought of.
    """
    orphans = [rel for rel in _source_files()
               if not _owners(rel, claims) and rel not in _UNROUTED_BY_DESIGN]
    assert not orphans, (
        "these modules are claimed by NO .claude/rules file, so none of this "
        "repo's recorded lessons will load when somebody opens them:\n  "
        + "\n  ".join(orphans)
        + "\n\nAdd each path to the `paths:` frontmatter of the rule file that "
          "covers its subject, or add it to _UNROUTED_BY_DESIGN with a reason. "
          "Routing is part of creating a file, not a follow-up.")


def test_the_SIGN_IN_feature_routes_to_its_own_rules(claims):
    """The specific regression, pinned by name.

    Every one of these was unrouted while the feature was being built and
    declared working, and `browser-login.md` is where the traps that would have
    prevented it are written down.
    """
    owner = 'browser-login.md'
    if owner not in claims:
        pytest.skip(f"{owner} is not in this checkout")
    for rel in ('core/handoff.py', 'core/canvas_auth.py',
                'core/browser_login.py', 'ui/auth.py', 'start.py', 'dev.py',
                'extension/popup.js', 'extension/background.js',
                'scripts/check_handoff.py'):
        assert owner in _owners(rel, claims), (
            f"{rel} implements the browser sign-in and does not load "
            f"{owner}. That is how a feature gets built twice without ever "
            f"meeting the notes on how it breaks.")


def test_a_VERIFICATION_tool_loads_its_subjects_rules_not_just_packagings(
        claims):
    """`scripts/check_*.py` belongs to `release-and-packaging.md` by pattern.

    That is right for the build checkers and was actively wrong for
    `check_handoff.py`, which verifies the sign-in handoff: it loaded packaging
    rules and nothing about the thing it checks. A checker written without its
    subject's rules is the one that reimplements the subject's own assumption,
    which is exactly what happened - it found the app by "first port that
    answers", the same as the extension, so it could not falsify the premise
    they shared. It reported ten of ten against an orphaned listener.
    """
    owners = _owners('scripts/check_handoff.py', claims)
    assert 'browser-login.md' in owners, (
        "the handoff checker does not load the handoff rules")


def test_the_matcher_can_still_say_NO(claims):
    """The positive control. A census whose matcher matches everything would
    pass with every module unrouted, and report that as protection."""
    assert not _owners('nowhere/not_a_real_module.py', claims), (
        "the glob matcher claims a path no rule file names, so the census "
        "above cannot detect an unrouted file")
    assert _matches('core/handoff.py', 'core/**')
    assert not _matches('cores/handoff.py', 'core/**')
    assert _matches('scripts/check_handoff.py', 'scripts/check_*.py')
    assert not _matches('scripts/build_msix.py', 'scripts/check_*.py')


def test_UNROUTED_BY_DESIGN_holds_no_stale_entries(claims):
    """An exemption for a file that no longer exists, or that some rule file
    has since claimed, is a decision nobody made. It also quietly shrinks the
    census: the next module added under that name inherits the exemption."""
    missing = [rel for rel in _UNROUTED_BY_DESIGN
               if not (_ROOT / rel).exists()]
    assert not missing, f"exempted files that do not exist: {missing}"
    now_claimed = [rel for rel in _UNROUTED_BY_DESIGN if _owners(rel, claims)]
    assert not now_claimed, (
        f"these are exempted AND claimed by a rule file, so the exemption is "
        f"stale and misleading: {now_claimed}")
