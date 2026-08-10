"""The shortcut's DISAMBIGUATED path must not define the stem for media.

Found by driving the real app on macOS 2026-08-10: a download of course 43660
(mp3 + txt + srt) followed by a sync of the same folder produced **70 mp3 files
for 36 lectures** - ~400 MB duplicated and the originals orphaned.

`_recording_base` is manifest-first, and its list was
`(SHORTCUT_KIND, "mp4", "mp3", "txt", "srt")` - shortcut FIRST, returning on the
first hit. The shortcut is the one kind whose path is legitimately
disambiguated: in the match layout the Canvas file sync owns `<title>.url`, so
`resolve_shortcut_path` writes ours as `<title> (Panopto).url`. The manifest
therefore held, for one video_id:

    url -> 'Forelaesningsvideo (2) Uformelletraek... (Panopto).webloc'
    mp3 -> 'Forelaesningsvideo (2) Uformelletraek....mp3'

and the sync took the url stem, sending every media file to
`<title> (Panopto).mp3` beside the mp3 already there. That is exactly the
divergence the function's own docstring promises to prevent.

Media kinds are consulted first now. The shortcut is still reached when no media
kind is recorded, which is the case its inclusion was justified by.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

VID = "0074fde5-eba4-42a7-b226-b35f00c6be2c"
TITLE = "Forelaesningsvideo (2) Uformelletraek_organisationskultur"
SUB = "Tema 2 Uformelle traek - organisationskultur"


def _base(tmp_path, manifest, *, legacy_title=""):
    from panopto.runner import _recording_base
    return _recording_base(tmp_path, tmp_path / SUB, TITLE, VID, manifest, set(),
                           legacy_title=legacy_title, settings={})


def test_the_media_stem_wins_over_the_disambiguated_shortcut(tmp_path):
    """THE regression. Both kinds are recorded; the mp3's stem must decide."""
    manifest = {VID: {
        "url": f"{SUB}/{TITLE} (Panopto).webloc",
        "mp3": f"{SUB}/{TITLE}.mp3",
    }}
    got = _base(tmp_path, manifest)
    assert got.name == TITLE, (
        f"the stem came from the shortcut ({got.name!r}), so every media file "
        f"would be written a second time under a disambiguated name")


@pytest.mark.parametrize("media_kind,ext", [("mp4", ".mp4"), ("mp3", ".mp3"),
                                            ("txt", ".txt"), ("srt", ".srt")])
def test_every_media_kind_outranks_the_shortcut(tmp_path, media_kind, ext):
    manifest = {VID: {"url": f"{SUB}/{TITLE} (Panopto).webloc",
                      media_kind: f"{SUB}/{TITLE}{ext}"}}
    assert _base(tmp_path, manifest).name == TITLE


def test_the_shortcut_stem_is_still_used_when_it_is_the_only_output(tmp_path):
    """The OTHER direction, and the reason the kind stays in the list at all.

    A folder whose only produced output is the shortcut still has a stem the
    manifest knows; dropping the kind would send a later mp3 to a freshly
    de-duplicated 'Title (1)' beside the link the user already has.
    """
    manifest = {VID: {"url": f"{SUB}/{TITLE} (Panopto).webloc"}}
    got = _base(tmp_path, manifest)
    assert got.name == f"{TITLE} (Panopto)", (
        "with no media recorded, the shortcut's stem is the only one there is")


def test_an_undisambiguated_shortcut_still_agrees_with_the_media(tmp_path):
    """The common case: no Canvas link collided, so both stems already match and
    the ordering cannot be observed. Pinned so a future reorder is judged on the
    colliding case rather than on this one."""
    manifest = {VID: {"url": f"{SUB}/{TITLE}.webloc",
                      "mp3": f"{SUB}/{TITLE}.mp3"}}
    assert _base(tmp_path, manifest).name == TITLE


def test_no_manifest_entry_falls_through_to_adoption_then_a_fresh_stem(tmp_path):
    """Unchanged behaviour below the manifest branch, so the fix cannot have
    moved the fallback."""
    (tmp_path / SUB).mkdir(parents=True)
    assert _base(tmp_path, {}).name == TITLE
    assert _base(tmp_path, None).name == TITLE


def test_the_ordering_is_pinned_in_the_source(tmp_path):
    """The whole defect was one list's order, so assert it directly - a passing
    behavioural test above could be satisfied by an unrelated later change."""
    src = (REPO / "panopto" / "runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_recording_base")
    tuples = [n for n in ast.walk(fn) if isinstance(n, ast.Tuple)
              and any(isinstance(e, ast.Constant) and e.value == "mp3" for e in n.elts)]
    assert tuples, "could not find the manifest kind list"
    names = [(e.value if isinstance(e, ast.Constant) else getattr(e, "id", "?"))
             for e in tuples[0].elts]
    assert names[-1] == "SHORTCUT_KIND", (
        f"the shortcut kind must be consulted LAST, got {names}")
