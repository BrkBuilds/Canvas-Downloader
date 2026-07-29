"""Converters deliberately never enter a vendored package directory.

``converters.post_processing._PACKAGE_DIRS`` skips ``node_modules``, ``.git``,
``__pycache__``, virtualenvs and ``site-packages``. Unpacking a student's npm
tree and rewriting every dependency to ``.txt`` would be absurd, and the
exclusion is documented and tested on the product side.

The audit did not know it. The first archive row after ``normalise_expect``
brought the conversion check back to life reported "convert_code did not reach
11818 file(s) unpacked from archives" - and all 11,818 were under
``node_modules``, on a run where 68 genuine conversion products sat beside
them. A checker that restates a product rule in its own words is a checker that
drifts from it, so the app's own set is imported.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from converters.post_processing import _PACKAGE_DIRS          # noqa: E402
from tests.audit.harness.crosscheck import _vendored          # noqa: E402


@pytest.mark.parametrize("d", sorted(_PACKAGE_DIRS))
def test_every_directory_the_app_skips_is_skipped_here_too(d):
    assert _vendored(f"Course/Week 3/{d}/inner/file.js")


def test_the_real_path_from_the_smoke_run():
    assert _vendored("Uge 15 Forelæsning 19/Part2/code/node_modules/.bin/mssql.ps1")


def test_windows_separators_are_understood():
    assert _vendored(r"Course\Week 3\node_modules\pkg\index.js")


def test_macosx_resource_forks_are_skipped():
    assert _vendored("Course/__MACOSX/._slides.pdf")


def test_ordinary_course_material_is_not_skipped():
    assert not _vendored("Uge 15/Forelæsning 19/Part2/code/server.js")
    assert not _vendored("slides.pdf")
    assert not _vendored("")


def test_a_partial_name_match_is_not_a_directory_match():
    """"node_modules_backup" is somebody's folder, not npm's."""
    assert not _vendored("Course/node_modules_backup/file.js")
    assert not _vendored("Course/my.git.notes/file.js")


def test_the_set_is_imported_not_restated():
    """If the product adds an exclusion, this must follow automatically."""
    import tests.audit.harness.crosscheck as cc
    src = Path(cc.__file__).read_text(encoding="utf-8")
    assert "from converters.post_processing import _PACKAGE_DIRS" in src
    assert "'node_modules'" not in src and '"node_modules"' not in src
