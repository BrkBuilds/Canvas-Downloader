"""No LINK may still point at the pre-transfer owner or the old Pages host.

``scripts/migrate_repo_urls.py`` rewrote the tree when the repo moved to the
BrkBuilds organisation on 2026-08-19. It did its job, and it documents its own
scope carefully. It could not catch everything, and this test covers the gap it
leaves, which is a gap of SPELLING rather than of effort.

The script substitutes two exact strings: ``birkls/Canvas_LMS_batch_file_downloader``
and then any remaining bare ``Canvas_LMS_batch_file_downloader``. Found
2026-08-20: ``Canvas_Downloader_Setup.iss`` carried

    #define AppURL "https://github.com/birkls/canvas-downloader"

which is a THIRD spelling - the old owner with a lowercase, hyphenated repo name
that was never one of the two search strings. Neither rule matched, so it
survived the migration silently. It is the publisher URL Windows shows in Apps &
features for every installed copy.

Nothing was broken for users at the time, because GitHub 301-redirects a renamed
owner. That redirect is exactly why this rots quietly, and it is not permanent:
**a released GitHub username can be claimed by anyone**, at which point a URL
baked into a shipped installer stops redirecting and starts resolving to a
stranger's account. That is the reason to pin it rather than rely on the
redirect.

The old GitHub PAGES host is worse and needs no hypothetical: ``github.io``
project sites do **not** redirect after a move to a custom domain.
``https://birkls.github.io/Canvas_LMS_batch_file_downloader/`` was measured
returning a hard **404**.

WHAT THIS TEST DOES AND DOES NOT FLAG
The rule is about LINKS, not about the word. Prose that discusses the old
account - the transfer runbook, a docstring citing the old host as history - is
correct and stays. Only a URL is a defect, because only a URL is something a
user or a crawler can follow.

THE SURFACE THIS TEST CANNOT REACH, AND IT WAS STILL BROKEN
The docstring above measured that 404 on 2026-08-20, and this guard swept the
whole tree for it. On 2026-08-24 the **Microsoft Store listing** was found still
serving that exact dead URL as its Privacy Policy link, and the old Pages root as
its App website link - four days after the 404 was written down here.

Nothing failed, and nothing should have. The guard covers every surface it can
see, and Partner Center is not a file in this repository. A published URL can
live in a form on somebody else's server, and a repo-wide grep is structurally
blind to it.

So a rename needs an OUT-OF-REPO checklist. It lives in
``marketing/STORE_LISTING.md`` section 3.8:

  * Microsoft Store - Privacy policy URL, Website, Support contact info
  * any directory listing (AlternativeTo, Softpedia, ...)
  * the GitHub repo's own About/homepage field

Resolve each with ``curl -sI -L`` and require 200. Do not read them: this failure
was invisible from reading, and the one link that DID redirect - the github.com
issues URL - is exactly what would have made a spot check report all clear.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Assembled from parts for the same reason migrate_repo_urls.py does it: so this
# file cannot match its own search string and report itself.
_OLD_OWNER = "birk" + "ls"
_OLD_PAGES_HOST = _OLD_OWNER + ".github.io"

# A link, not a mention: the owner in a github.com path, or the old Pages host.
_STALE_LINK = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/" + _OLD_OWNER + r"/"
    r"|" + re.escape(_OLD_PAGES_HOST))

# Records and history that must keep the old urls. Each is documented in
# scripts/migrate_repo_urls.py or is about the move itself.
EXCLUDED = {
    "scripts/migrate_repo_urls.py",          # holds the search strings themselves
    "tests/audit/WEBSITE_LAUNCH_AUDIT.html",  # a DATED audit record; rewriting falsifies it
    "tests/test_legal_ack.py",               # cites the old host as history, derives the real one
    ".github/REPO_SETUP.md",                 # the transfer runbook; the old names are its subject
    "tests/test_no_stale_repo_urls.py",      # this file
    "CLAUDE.md",                             # project memory, records history verbatim
    "marketing/PLAYBOOK.md",                 # records the finding, including the dead url
    "marketing/FINDINGS.md",                 # the register; quotes the dead urls as evidence
    "marketing/SITE_RUNBOOK.md",             # documents the redirect asymmetry
    "marketing/STORE_LISTING.md",            # quotes the dead Store fields as evidence
    "marketing/store-listing.html",          # generated FROM that file; same evidence
    "marketing/store-listing.artifact.html", # generated FROM that file; same evidence
}

# Directories that are build output, vendored dependencies or scratch.
SKIP_DIRS = {
    ".git", "__pycache__", "dist", "build", "msix", "msix_output",
    "installer_output", "_audit_runs", "panopto_models", "cuda_libs",
    "diagnostics", ".playwright-mcp", ".pytest_cache", "node_modules",
    ".claude", "memory-bank",
}

SCAN_SUFFIXES = {".py", ".md", ".html", ".css", ".json", ".iss", ".spec",
                 ".xml", ".yml", ".yaml", ".txt", ".js"}


def _files() -> list[Path]:
    """Walk with PRUNING, not rglob.

    ``dist/`` alone holds a full PyInstaller tree with a vendored numpy, bs4 and
    aiohttp. rglob walks into it and filters afterwards, which measured 89s for
    this one test against 185s for the entire suite. os.walk lets the skipped
    directories be removed from the walk before it descends: 89s -> under 1s.
    """
    out: list[Path] = []
    for root, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(root) / name
            if path.suffix.lower() not in SCAN_SUFFIXES:
                continue
            if path.relative_to(REPO).as_posix() in EXCLUDED:
                continue
            out.append(path)
    assert out, "scanned no files - the filter is wrong, not the tree"
    return out


#: A findings document that records a dead URL AS the defect it reports is not
#: a file linking to it. `marketing/SEO_FINDINGS_2026-08-27.md` has a
#: before/after table whose whole content is "this URL 404s, this one is 200",
#: and flagging it makes the guard fire on the write-up of the very fix the
#: guard exists to enforce.
#:
#: The exemption is a PROPERTY rather than a filename: the line must carry an
#: explicit dead HTTP status beside the URL. A filename allowlist would go
#: stale the moment the document is renamed, and prose words like "old" or
#: "redirect" are far too common to key on - a first draft used them and would
#: have exempted any real link in a sentence containing the word "old". A
#: three-digit status code next to a URL is something only a report writes.
_DEAD_MARKER = re.compile(r"\b(?:404|410|301|308)\b")


def _documents_the_url_as_dead(line: str) -> bool:
    return bool(_DEAD_MARKER.search(line))


def test_no_shipped_file_links_to_the_old_owner_or_pages_host():
    offenders: list[str] = []
    for path in _files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if _STALE_LINK.search(line) and not _documents_the_url_as_dead(line):
                rel = path.relative_to(REPO).as_posix()
                offenders.append(f"{rel}:{lineno}: {line.strip()[:110]}")
    assert not offenders, (
        "these files still LINK to the pre-transfer owner or the old GitHub Pages "
        "host. The github.com ones only work while GitHub keeps redirecting a "
        "released username, and the github.io ones do not redirect at all:\n  "
        + "\n  ".join(offenders))


def test_the_installer_urls_are_all_absolute_and_separate():
    """The three Inno URLs must not be built by appending to one another.

    ``AppSupportURL={#AppURL}/issues`` was correct only while AppURL happened to
    be the GitHub repo. Pointing AppURL at the website silently turned it into
    ``canvasdownloader.app/issues``, which does not exist. Each URL is now stated
    in full, and this asserts it stays that way.
    """
    iss = (REPO / "Canvas_Downloader_Setup.iss").read_text(encoding="utf-8")
    for key in ("AppPublisherURL", "AppSupportURL", "AppUpdatesURL"):
        m = re.search(rf"^{key}=(.+)$", iss, re.M)
        assert m, f"{key} is missing from the installer script"
        value = m.group(1).strip()
        assert not re.search(r"\{#\w+\}\s*/", value), (
            f"{key} appends a path to another define ({value!r}). That breaks the "
            f"moment the base url changes meaning; give it its own full url.")

    for key in ("AppURL", "AppSupportURL", "AppUpdatesURL"):
        m = re.search(rf'#define\s+{key}\s+"([^"]+)"', iss)
        assert m, f"#define {key} is missing"
        assert m.group(1).startswith("https://"), (
            f"{key} must be an absolute https url, got {m.group(1)!r}")


@pytest.mark.parametrize("path", ["docs/index.html", "README.md"])
def test_the_public_faces_point_at_the_current_owner(path: str):
    """A positive control: these files really do carry github links to check."""
    text = (REPO / path).read_text(encoding="utf-8")
    assert "github.com/BrkBuilds/Canvas-Downloader" in text, (
        f"{path} has no link to the current repo, so the scan above proves "
        f"nothing about it")
