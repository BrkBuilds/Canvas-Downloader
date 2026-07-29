"""A Panopto recording must fit on a default Windows install.

Measured on course 43660, separate layout:

    41  C:\\Users\\x\\Documents\\Canvas Downloads
    69  Indf..ring i organisationers opbygning og funktion (LA E25 BINTO1060U)
   228  Panopto Recordings/<101-char title>/<101-char title>.mp4
   ---
   340  characters                                    MAX_PATH = 260

Two independent defects produced that, and both are fixed here:

1. The lecture title was written TWICE - once as the folder, once as the file
   inside it. ``recording_stem_name`` stops the second one.
2. Nothing in ``panopto/`` used ``make_long_path``, while the rest of the app
   does. The dev machine has ``LongPathsEnabled=1`` in the registry, which
   Windows ships DISABLED - so this worked here and would fail for users, and no
   amount of testing on this machine could have shown it.

The dangerous half is neither: it is that renaming what the app WRITES leaves
every existing recording under the old name. The discovery paths therefore
accept both, and that is what these tests mostly cover.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from panopto.runner import (  # noqa: E402
    recording_base_candidates, recording_stem_name, video_dir,
)
from shared.helpers import make_long_path, path_exists  # noqa: E402

SEPARATE = {"layout": "separate"}
MATCH = {"layout": "match"}
LONG_TITLE = ("Forelaesningsvideo (1) Organisationer i et foranderligt "
              "perspektiv - beslutninger i organisationer_2025")


# --------------------------------------------------------------------------
# the naming rule
# --------------------------------------------------------------------------

def test_separate_layout_does_not_repeat_the_title_on_the_file():
    """The folder is already the lecture. Repeating it is pure path length."""
    assert recording_stem_name(LONG_TITLE, SEPARATE) == "Recording"


def test_match_layout_keeps_the_title():
    """No per-recording folder here, so the title is the ONLY thing telling two
    recordings apart - dropping it would collide every lecture in the course."""
    assert recording_stem_name(LONG_TITLE, MATCH) == LONG_TITLE


def test_the_default_layout_keeps_the_title():
    """`video_dir` defaults to 'match' when the key is absent; the stem rule
    must agree, or an unset layout writes to one place and is looked for in
    another."""
    assert recording_stem_name(LONG_TITLE, {}) == LONG_TITLE
    assert video_dir(Path("C:/c"), "", {}, "flat",
                     lecture_title_sanitized=LONG_TITLE) == Path("C:/c")


def test_the_fix_actually_gets_a_real_recording_under_MAX_PATH():
    """The number is the point of the change, so it is asserted, not assumed."""
    root = Path(r"C:\Users\birkl\Documents\Canvas Downloads")
    course = "Indf\u00f8ring i organisationers opbygning og funktion (LA E25 BINTO1060U)"
    out = video_dir(root / course, "", SEPARATE, "flat",
                    lecture_title_sanitized=LONG_TITLE)
    before = out / (LONG_TITLE + ".mp4")
    after = out / (recording_stem_name(LONG_TITLE, SEPARATE) + ".mp4")
    assert len(str(before)) > 260, "the case this fixes must actually be over"
    assert len(str(after)) < 260, f"still {len(str(after))} chars"


# --------------------------------------------------------------------------
# migration: what is already on disk carries the OLD name
# --------------------------------------------------------------------------

def test_candidates_offer_the_new_name_first_then_the_legacy_one():
    out = Path("C:/c/Panopto Recordings") / LONG_TITLE
    cands = recording_base_candidates(out, LONG_TITLE, SEPARATE)
    assert [c.name for c in cands] == ["Recording", LONG_TITLE]


def test_match_layout_has_exactly_one_candidate():
    """Nothing was renamed there, so a second candidate would be a duplicate
    lookup on every kind of every recording."""
    cands = recording_base_candidates(Path("C:/c"), LONG_TITLE, MATCH)
    assert [c.name for c in cands] == [LONG_TITLE]


def test_a_folder_written_by_an_older_version_is_adopted_not_re_downloaded(tmp_path):
    """THE regression this guards.

    A download-mode run records nothing in the manifest, so "no manifest entry"
    is the normal state of a folder the user downloaded before ever syncing it.
    If the analyzer only looked at the new stem, every such recording would read
    as deleted and queue a full re-download of the course's video - the most
    expensive wrong answer this app can give.
    """
    out = tmp_path / "Panopto Recordings" / LONG_TITLE
    out.mkdir(parents=True)
    legacy = out / (LONG_TITLE + ".mp4")
    legacy.write_bytes(b"old naming")

    found = [c for c in recording_base_candidates(out, LONG_TITLE, SEPARATE)
             if path_exists(Path(str(c) + ".mp4"))]
    assert found and found[0].name == LONG_TITLE


def test_a_new_recording_still_gets_the_short_name(tmp_path):
    """The legacy name is adopted only where it EXISTS; nothing creates it."""
    out = tmp_path / "Panopto Recordings" / LONG_TITLE
    out.mkdir(parents=True)
    found = [c for c in recording_base_candidates(out, LONG_TITLE, SEPARATE)
             if path_exists(Path(str(c) + ".mp4"))]
    assert not found
    assert recording_stem_name(LONG_TITLE, SEPARATE) == "Recording"


# --------------------------------------------------------------------------
# long-path handling
# --------------------------------------------------------------------------

def test_path_exists_answers_correctly_over_the_limit(tmp_path):
    """`Path.exists()` does not raise on an over-long path - it returns False,
    which is indistinguishable from "not downloaded". That is why every
    "do we already have it?" check had to move to `path_exists`."""
    deep = tmp_path
    while len(str(deep)) < 250:
        deep = deep / ("s" * 40)
    import os
    os.makedirs(make_long_path(deep), exist_ok=True)
    f = deep / "Recording.mp4"
    with open(make_long_path(f), "wb") as fh:
        fh.write(b"x")
    assert len(str(f)) > 260
    assert path_exists(f) is True


def test_the_panopto_write_path_uses_long_path_handling():
    """Structural, because the failure only reproduces on a machine with
    LongPathsEnabled=0 and this one has it ON."""
    runner = (REPO / "panopto" / "runner.py").read_text(encoding="utf-8")
    stream = (REPO / "panopto" / "stream.py").read_text(encoding="utf-8")
    trans = (REPO / "panopto" / "transcribe.py").read_text(encoding="utf-8")

    assert "Path(make_long_path(out_dir)).mkdir" in runner, \
        "the recording folder is the deepest path this app creates"
    assert "out_path = make_long_path(out_path)" in stream, \
        "ffmpeg's output target must be long-path safe"
    assert "open(make_long_path(txt_tmp)" in trans
    assert "os.replace(make_long_path(txt_tmp), make_long_path(txt_path))" in trans
    assert ".exists()" not in runner.split("def run_panopto_batch")[-1], \
        "every existence check in the batch must go through path_exists"


def test_transcribe_returns_CLEAN_paths():
    """The prefix must never reach the manifest: `record_panopto_file` stores a
    path relative to the course root, and `relative_to` on a prefixed path
    raises - the recorder then falls back to storing the absolute, and every
    later comparison misses."""
    trans = (REPO / "panopto" / "transcribe.py").read_text(encoding="utf-8")
    assert 'out["txt"] = txt_path' in trans
    assert 'out["srt"] = srt_path' in trans


def test_no_unprotected_filesystem_call_remains_in_the_panopto_path():
    """Completeness, not spot-fixes.

    Every operation on a recording's path must go through the long-path form,
    because they fail in DIFFERENT ways and each one is quiet:

    * ``mkdir``  -> the recording is reported as a baffling "Folder Error";
    * ``exists`` -> returns False, so a file that is there re-downloads for ever;
    * ``stat``   -> raises, and the recording counts as 0 bytes in the total;
    * ``unlink`` -> the intermediate audio is never cleaned up.

    Missing one leaves a failure that only appears on machines where
    LongPathsEnabled is 0 - which is the Windows default and NOT this machine,
    so no amount of local testing would show it.
    """
    import re
    bad = []
    for rel in ("panopto/runner.py", "panopto/sync_plan.py", "panopto/transcribe.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        code = re.sub(r"^\s*#.*$", "", src, flags=re.M)
        for pat, why in (
            (r"^\s*(?!.*make_long_path).*\.mkdir\(", "mkdir"),
            (r"^\s*(?!.*make_long_path).*\w\.stat\(\)", "stat"),
            (r"^\s*(?!.*make_long_path).*\w\.unlink\(", "unlink"),
        ):
            for m in re.finditer(pat, code, re.M):
                line = code[:m.start()].count("\n") + 1
                bad.append(f"{rel}:{line} unprotected {why} -> {m.group(0).strip()[:70]}")
    assert not bad, "\n".join(bad)


def test_every_existence_check_uses_path_exists():
    """`Path.exists()` does not raise over the limit - it answers False. That is
    the worst possible failure mode here: it reads as "not downloaded"."""
    import re
    src = (REPO / "panopto" / "runner.py").read_text(encoding="utf-8")
    code = re.sub(r"^\s*#.*$", "", src, flags=re.M)
    leftovers = [m.group(0).strip()[:60]
                 for m in re.finditer(r"^\s*.*_path\.exists\(\)", code, re.M)]
    assert not leftovers, f"plain .exists() on a recording path: {leftovers}"
