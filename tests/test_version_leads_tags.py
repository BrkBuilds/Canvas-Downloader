"""``version.py`` must never be BEHIND, or equal to, the newest shipped tag.

Found by the macOS 15 live audit 2026-08-10: the app was being gated for release
as v2.0.2 while ``version.py`` still said ``2.0.1`` - which is also already a
shipped tag. The sidebar showed the wrong version, but the sharp consequence is
``ui/update_banner.py``: it computes ``_is_newer(github_tag, __version__)``, so
tagging the release v2.0.2 with a 2.0.1 bundle tells **every user of that build,
on every launch, for ever** that an update is available - pointing at the build
they are already running. It cannot self-clear.

Nothing in the build or the suite asserted this, which is the only reason it got
as far as the final gate. The check is deliberately about the ORDER, not about
any particular number: it passes for any version strictly ahead of every tag, so
it never has to be edited when the version moves.

Skips rather than fails when tags are unavailable (a shallow CI clone, or a
source tree with no git), because "I cannot see the tags" is not evidence of a
version mistake.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _version_tuple(s: str) -> tuple[int, ...]:
    """Numeric tuple, mirroring update_banner's own fallback parse."""
    parts: list[int] = []
    for chunk in s.strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or (0,)


def _tags() -> list[str]:
    try:
        r = subprocess.run(["git", "tag"], cwd=REPO, capture_output=True,
                           text=True, timeout=30)
    except Exception:                                           # noqa: BLE001
        return []
    if r.returncode != 0:
        return []
    return [t for t in (r.stdout or "").split() if t.strip()]


def test_version_is_strictly_ahead_of_every_shipped_tag():
    from version import __version__

    tags = _tags()
    if not tags:
        pytest.skip("no git tags visible (shallow clone or no git) - "
                    "cannot judge the ordering")

    local = _version_tuple(__version__)
    newest = max(tags, key=_version_tuple)
    assert local > _version_tuple(newest), (
        f"version.py is {__version__!r} but {newest!r} is already tagged. "
        f"Shipping this build would make ui/update_banner.py offer every user "
        f"an update to the release they are running. Bump version.py first.")


def test_the_update_banner_would_not_offer_an_update_to_the_current_build():
    """The consequence, stated as the property that actually matters.

    Asserted through the REAL comparison the banner uses, not a re-implementation
    of it - a copy here would keep passing if `_is_newer` changed underneath.
    """
    from version import __version__
    from ui.update_banner import _is_newer

    tags = _tags()
    if not tags:
        pytest.skip("no git tags visible")

    for tag in tags:
        assert not _is_newer(tag.lstrip("vV"), __version__), (
            f"the update banner would fire for already-shipped tag {tag!r} "
            f"against local version {__version__!r}")
