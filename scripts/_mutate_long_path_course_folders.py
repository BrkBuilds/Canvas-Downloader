"""Mutation pass for long-path handling inside course folders.

Flips one real behaviour at a time and asserts the tests go RED. A test that
survives its own mutant is testing the shape of the code rather than what it
does.

The mutants worth having here are the plausible-refactor ones. Three shapes
recur in this repo's history and all three are represented:

  * **a fix that lands on some of the sites** - reverting ONE mkdir, or one
    converter, while the rest stay correct. That is how `pdf_looks_real` sat on
    two of three delete sites for eight months.
  * **"simplifying" the primitive back** - `walk_files_long` -> `rglob`,
    `path_exists` -> `Path.exists()`. Both read as tidying and both restore the
    silent-starvation bug exactly.
  * **weakening the census** - a guard that can no longer fail is worse than no
    guard, because it is recorded as protection.

IMPORTANT: this pass can only be meaningful on a machine that ENFORCES
MAX_PATH. Where `LongPathsEnabled=1` the behavioural tests skip themselves, so
several mutants would be reported SURVIVED for a reason that has nothing to do
with the code. Run `python scripts/check_longpath_gate.py` first; it must say
VALID.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so HEAD may not be what this pass
started from, and a hard checkout would discard somebody else's uncommitted
edit to a file this pass never mutated. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it changed underneath -
restoring nothing, because at that point the only thing on disk is their edit.

    python scripts/_mutate_long_path_course_folders.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

HELPERS = "shared/helpers.py"
POST = "converters/post_processing.py"
LOGIC = "core/canvas_logic.py"
CODE = "converters/code.py"
MD = "converters/md.py"
URL = "converters/url.py"
VIDEO = "converters/video.py"
SYNCMGR = "core/sync_manager.py"

TESTS = ["tests/test_long_path_course_folders.py"]

#: (label, file, old, new)
LONG_PATH_COURSE_FOLDER_MUTANTS = [
    # -- layer 0: mkdir. One unprefixed site = a crash with zero files. -------
    ("the COURSE folder mkdir loses the prefix (the original crash)",
     LOGIC,
     "Path(make_long_path(base_path)).mkdir(parents=True, exist_ok=True)",
     "base_path.mkdir(parents=True, exist_ok=True)"),
    ("the MODULE folder mkdir loses the prefix (modules mode fails first)",
     LOGIC,
     "Path(make_long_path(target_path)).mkdir(parents=True, exist_ok=True)",
     "target_path.mkdir(parents=True, exist_ok=True)"),
    ("the SYNC ROOT mkdir loses the prefix",
     SYNCMGR,
     "Path(make_long_path(self.local_path)).mkdir(parents=True, exist_ok=True)",
     "self.local_path.mkdir(parents=True, exist_ok=True)"),

    # -- layer 1: discovery. One call decides whether nine features work. -----
    ("post-processing discovery goes back to rglob",
     POST,
     "        f for f in walk_files_long(course_folder)\n"
     "        if not f.name.startswith('._')",
     "        f for f in course_folder.rglob('*')\n"
     "        if f.is_file()\n"
     "        and not f.name.startswith('._')"),
    ("post-processing discovery goes back to Path.exists()",
     POST,
     "    if not path_exists(course_folder):\n        return []",
     "    if not course_folder.exists():\n        return []"),

    # -- the primitive itself -------------------------------------------------
    ("walk_files_long stops walking through the prefix",
     HELPERS,
     "    walk_root = make_long_path(str(root))",
     "    walk_root = str(root)"),
    ("walk_files_long leaks the \\\\?\\ prefix into the paths it yields",
     HELPERS,
     "        clean_dir = root if rel in ('.', '') else root / rel",
     "        clean_dir = Path(dirpath)"),

    # -- layer 2: the converters, one at a time -------------------------------
    ("the code converter reads its source unprefixed",
     CODE,
     "        with open(make_long_path(original_path), 'r', encoding='utf-8', errors='replace') as f:",
     "        with open(original_path, 'r', encoding='utf-8', errors='replace') as f:"),
    ("the code converter's pre-delete gate goes back to Path.exists()",
     CODE,
     '        _ok, _why = file_has_content(txt_path, what="text file")\n'
     "        if not _ok:",
     "        _ok = txt_path.exists() and txt_path.stat().st_size > 0\n"
     "        _why = 'empty'\n"
     "        if not _ok:"),
    ("the html converter's input validation goes back to Path.exists()",
     MD,
     "        if not path_exists(html_path) or html_path.suffix.lower() != '.html':",
     "        if not html_path.exists() or html_path.suffix.lower() != '.html':"),
    ("the url compiler goes back to rglob for shortcuts",
     URL,
     "    shortcut_files = [p for p in walk_files_long(course_path)\n"
     "                      if p.suffix.lower() in _shortcut_exts]",
     '    shortcut_files = [p for pattern in ("*.url", "*.webloc")\n'
     "                      for p in course_path.rglob(pattern)]"),
    ("the url compiler writes its output unprefixed",
     URL,
     "        with open(make_long_path(tmp_path), 'w', encoding='utf-8') as f:",
     "        with open(tmp_path, 'w', encoding='utf-8') as f:"),
    ("the video converter's source delete loses the prefix, so it silently no-ops",
     VIDEO,
     "Path(make_long_path(abs_video)).unlink(missing_ok=True)",
     "Path(abs_video).unlink(missing_ok=True)"),

    # -- the census guard itself ---------------------------------------------
    # A census that cannot fail is worse than none: it is recorded as protection.
    ("the mkdir census stops looking at any module but the first",
     "tests/test_long_path_course_folders.py",
     "    for rel in COURSE_FOLDER_MODULES:\n        checked.append(rel)",
     "    for rel in COURSE_FOLDER_MODULES[:1]:\n        checked.append(rel)"),
    ("the mkdir census treats every receiver as exempt",
     "tests/test_long_path_course_folders.py",
     '        if (rel, checked) in MKDIR_EXEMPT:\n            continue',
     "        if True:\n            continue"),
    # The census used to match only `<expr>.mkdir(...)`, so os.makedirs was
    # invisible to it. Deleting the module-level branch restores that blindness.
    ("the mkdir census goes blind to os.makedirs again",
     "tests/test_long_path_course_folders.py",
     '_MODULE_MKDIRS = {("os", "makedirs"), ("os", "mkdir")}',
     "_MODULE_MKDIRS = set()"),

    # -- the HALF-FIX shape: prefixed check, unprefixed follow-up ------------
    # Both were live defects on 2026-08-22, found by auditing the fixes rather
    # than the code. Each reverts to exactly what shipped.
    ("the error-log dialog reads a course-folder log without the prefix",
     "shared/components.py",
     "content = Path(make_long_path(log_path)).read_text(\n"
     "                        encoding='utf-8').strip()",
     "content = log_path.read_text(encoding='utf-8').strip()"),
    ("the ignored-recordings dialog sizes a recording without the prefix",
     "ui/sync_dialogs.py",
     "total += os.stat(make_long_path(p)).st_size",
     "total += p.stat().st_size"),
    # The guard's OWN failure mode, and it actually happened: counting physical
    # lines meant an explanatory comment above the fixed call pushed it out of
    # the window, so the guard passed against deliberately reverted code.
    ("the half-fix guard counts physical lines again, so a comment blinds it",
     "tests/test_long_path_course_folders.py",
     'code = [(n + 1, ln) for n, ln in enumerate(src.splitlines())\n'
     '                if ln.strip() and not ln.lstrip().startswith("#")]',
     "code = [(n + 1, ln) for n, ln in enumerate(src.splitlines())]"),
    ("the half-fix guard exempts everything",
     "tests/test_long_path_course_folders.py",
     "            if (rel, var) in HALF_FIX_EXEMPT:\n                continue",
     "            if True:\n                continue"),

    # -- the prefix-LEAK guard ------------------------------------------------
    # It only saw a bare `x = make_long_path(...)`, so `x = Path(make_long_path(
    # ...))` - the form that actually carries a prefix onward - was invisible.
    ("the leak guard goes blind to the Path(make_long_path(x)) wrapper form",
     "tests/test_long_path_course_folders.py",
     '    path_wrappers = {"Path", "str", "join", "normpath", "abspath", "fspath",\n'
     '                     "PurePath", "PureWindowsPath"}',
     "    path_wrappers = set()"),
]


def _nl_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _read(rel: str) -> str:
    with io.open(REPO / rel, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(rel: str, text: str) -> None:
    with io.open(REPO / rel, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def main() -> int:
    files = sorted({m[1] for m in LONG_PATH_COURSE_FOLDER_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in LONG_PATH_COURSE_FOLDER_MUTANTS:
        nl = _nl_of(snapshot[rel])
        if old.replace("\n", nl) not in snapshot[rel]:
            stale.append(f"{label!r} in {rel}")
    if stale:
        print("STALE ANCHORS - these mutants could not run at all, so any score "
              "recorded for them is UNMEASURED, not passing:")
        for s in stale:
            print("  " + s)
        return 4

    print(f"baseline: running {len(TESTS)} test file(s)")
    if subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q"],
                      cwd=REPO).returncode != 0:
        print("BASELINE IS RED - fix that first")
        return 2

    caught, survived = [], []
    for label, rel, old, new in LONG_PATH_COURSE_FOLDER_MUTANTS:
        current = _read(rel)
        if current != snapshot[rel]:
            print(f"\nABORT: {rel} changed underneath this pass (another "
                  f"session?). Nothing restored - the file on disk is THEIR "
                  f"edit, not a mutant.")
            return 3
        nl = _nl_of(current)
        old_nl, new_nl = old.replace("\n", nl), new.replace("\n", nl)
        if old_nl not in current:
            print(f"\nSTALE ANCHOR for {label!r} in {rel} - the pass cannot run it")
            return 4

        _write(rel, current.replace(old_nl, new_nl, 1))
        assert _read(rel) != snapshot[rel], f"{label}: mutation changed nothing"
        try:
            rc = subprocess.run([sys.executable, "-m", "pytest", *TESTS,
                                 "-q", "-x", "--no-header",
                                 "-p", "no:cacheprovider"],
                                cwd=REPO, capture_output=True,
                                timeout=900).returncode
        except subprocess.TimeoutExpired:
            rc = 1  # a mutant that hangs the suite is one the suite noticed
        finally:
            _write(rel, snapshot[rel])
            assert _read(rel) == snapshot[rel], f"{rel}: RESTORE FAILED"
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(LONG_PATH_COURSE_FOLDER_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
