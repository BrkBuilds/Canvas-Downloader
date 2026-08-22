"""Course folders past Windows' MAX_PATH.

A course folder's depth is the USER's choice - their destination plus a Canvas
course name (CBS ships names up to 110 characters) plus, in modules mode, a
module name. On a default Windows install (`LongPathsEnabled=0`, i.e. most
users) that runs into two different kernel limits, and the app met both:

  * **248 characters for a DIRECTORY**, not 260. `CreateDirectory` reserves 12
    characters so an 8.3 name can still be created inside, so a folder fails
    TWELVE CHARACTERS EARLIER than a MAX_PATH analysis predicts. Measured
    2026-08-22: mkdir accepts 247 and rejects 248.
  * **260 for a file**, where the failure is silent rather than loud - Windows
    reports it as ERROR_PATH_NOT_FOUND, which Python raises as
    `FileNotFoundError`, indistinguishable from a file that is simply absent.

Three layers were broken, each in a different way, and they masked each other:

  0. `mkdir` unprefixed - the download crashed with 0 files before it could
     reach the file-writing code that WAS long-path safe.
  1. `_glob_files` unprefixed - the one discovery helper every converter goes
     through returned `[]`, starving all nine of them at once, silently.
  2. the source-consuming converters' own I/O - and `unlink(missing_ok=True)`
     swallowed the FileNotFoundError, so "too long" read as "already gone".

TWO KINDS OF TEST LIVE HERE, AND THE SPLIT IS THE POINT.

*Source-property* tests (the census) run everywhere and are what stops this
drifting back - the repo's history is that a fix like this lands on five of six
sites and nobody notices.

*Behavioural* tests can only mean anything on a machine that actually enforces
the limit. On a box with `LongPathsEnabled=1` an unprefixed open at 400
characters simply SUCCEEDS, so a behavioural test there passes whether or not
the bug is present - a masked pass, which is worse than no test because it gets
recorded as evidence. They are therefore skipped unless the gate is real, using
the same probe `scripts/check_longpath_gate.py` ships.
"""
import ast
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from shared.helpers import make_long_path, path_exists, walk_files_long  # noqa: E402


# ---------------------------------------------------------------- gate probe

def _gate_is_real() -> bool:
    """Does this machine actually enforce MAX_PATH?

    Asks the filesystem, never the registry: enforcement needs the registry
    value AND the executable's longPathAware manifest, and the value is only
    read at process start.
    """
    if os.name != "nt":
        return False
    # mkdtemp + an explicit PREFIXED rmtree, never TemporaryDirectory: its
    # cleanup is an unprefixed shutil.rmtree, which on the very machine this
    # probe is for cannot delete the tree it just made. The probe's own I/O has
    # to be long-path safe for the same reason office_safe_path's does.
    root = Path(tempfile.mkdtemp(prefix="lpgate_"))
    try:
        deep = root
        while len(str(deep)) < 300:
            deep = deep / ("d" * 40)
            os.makedirs(make_long_path(str(deep)), exist_ok=True)
        target = deep / "probe.txt"
        with open(make_long_path(str(target)), "wb") as fh:
            fh.write(b"x")
        try:
            with open(str(target), "rb") as fh:
                fh.read()
            return False          # unprefixed worked -> the limit is not enforced
        except OSError:
            return True
    finally:
        shutil.rmtree(make_long_path(str(root)), ignore_errors=True)


_GATE_REAL = _gate_is_real()
needs_gate = pytest.mark.skipif(
    not _GATE_REAL,
    reason="this machine does not enforce MAX_PATH (LongPathsEnabled=1, or not "
           "Windows), so a long-path behavioural test would pass whether or not "
           "the bug is present - see scripts/check_longpath_gate.py",
)


@pytest.fixture()
def deep_dir(tmp_path):
    """A real directory whose path is past BOTH limits, built with the prefix.

    Built through make_long_path on purpose: if the fixture were created the
    same unprefixed way the code under test is probed, creation would fail on an
    enforcing machine and every assertion below would be about a file that was
    never written.
    """
    d = tmp_path
    first = None
    while len(str(d)) < 300:
        d = d / ("d" * 40)
        first = first or d
        os.makedirs(make_long_path(str(d)), exist_ok=True)
    yield d
    # pytest's own tmp_path reaper is an unprefixed rmtree and cannot remove
    # this tree, so it would fail a LATER run's collection rather than this one.
    if first is not None:
        shutil.rmtree(make_long_path(str(first)), ignore_errors=True)


def _put(path: Path, data: bytes) -> None:
    os.makedirs(make_long_path(str(path.parent)), exist_ok=True)
    with open(make_long_path(str(path)), "wb") as fh:
        fh.write(data)


def _exists(path: Path) -> bool:
    return os.path.exists(make_long_path(str(path)))


# ------------------------------------------------------- the walk primitive

def test_walk_files_long_matches_rglob_on_a_short_tree(tmp_path):
    """The control. A primitive that changed behaviour for ordinary paths would
    be a regression for every user, which is most of them."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_bytes(b"a")
    (tmp_path / "sub" / "b.txt").write_bytes(b"b")

    walked = sorted(p.name for p in walk_files_long(tmp_path))
    rglobbed = sorted(p.name for p in tmp_path.rglob("*") if p.is_file())
    assert walked == rglobbed == ["a.txt", "b.txt"]


@needs_gate
def test_walk_files_long_sees_files_rglob_cannot(deep_dir):
    """Both regimes at once: the root is past the limit AND so are the files."""
    _put(deep_dir / "top.txt", b"x")
    _put(deep_dir / "Module 1" / "nested.txt", b"x")

    found = sorted(p.name for p in walk_files_long(deep_dir))
    assert found == ["nested.txt", "top.txt"]
    assert list(deep_dir.rglob("*")) == [], "control: rglob is expected to be blind here"


@needs_gate
def test_walk_files_long_yields_clean_paths(deep_dir):
    """Callers put these into manifest rows and hand them to Office COM, and
    both reject the prefix - so the walk goes THROUGH it and comes back out."""
    _put(deep_dir / "f.txt", b"x")
    for p in walk_files_long(deep_dir):
        assert not str(p).startswith("\\\\?\\")
        assert _exists(p)


def test_walk_files_long_yields_no_directories(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f.txt").write_bytes(b"x")
    assert [p.name for p in walk_files_long(tmp_path)] == ["f.txt"]


def test_walk_files_long_on_a_missing_root_is_empty_not_an_exception(tmp_path):
    """It replaces rglob inside list comprehensions with no handler of their own."""
    assert list(walk_files_long(tmp_path / "does-not-exist")) == []


# ------------------------------------------------------- layer 1: discovery

@needs_gate
def test_glob_files_finds_a_file_past_the_limit(deep_dir):
    """The defect that starved all nine converters at once."""
    from converters.post_processing import _glob_files

    _put(deep_dir / "lecture.py", b"print(1)\n")
    found = _glob_files(deep_dir, {".py"})
    assert len(found) == 1, "post-processing discovery is blind past the limit"
    assert found[0].name == "lecture.py"


@needs_gate
def test_glob_files_still_scopes_to_explicit_files(deep_dir):
    """The fix must not widen scope: `explicit_files` is what stops a re-run
    re-converting a whole folder, and an archive's contents being swept up."""
    from converters.post_processing import _glob_files

    wanted = deep_dir / "wanted.py"
    other = deep_dir / "other.py"
    _put(wanted, b"x")
    _put(other, b"x")

    found = _glob_files(deep_dir, {".py"}, explicit_files=[str(wanted)])
    assert [p.name for p in found] == ["wanted.py"]


# ------------------------------------------------------ layer 2: converters

@needs_gate
def test_code_converter_works_past_the_limit(deep_dir):
    from converters.code import convert_code_to_txt

    src = deep_dir / "script.py"
    _put(src, b"print('hello')\n")
    out = convert_code_to_txt(src)

    assert out is not None, "code conversion silently did nothing"
    assert _exists(Path(out))
    assert not _exists(src), "a source-consuming converter must consume its source"


@needs_gate
def test_html_converter_works_past_the_limit(deep_dir):
    from converters.md import convert_html_to_md

    src = deep_dir / "page.html"
    _put(src, b"<h1>Week 1</h1><p>Reading</p>")
    out = convert_html_to_md(src)

    assert out is not None, "html conversion silently did nothing"
    assert _exists(Path(out))
    assert not _exists(src)


@needs_gate
def test_url_compiler_works_past_the_limit(deep_dir):
    """The quietest of the four: it logged NOTHING, because the glob simply
    matched no .url files and compiling zero links looks like success."""
    from converters.url import compile_urls_to_txt

    src = deep_dir / "Lecture.url"
    _put(src, b"[InternetShortcut]\r\nURL=https://example.com/x\r\n")

    out, processed = compile_urls_to_txt(deep_dir, "Test Course")
    assert out is not None, "url compilation silently produced nothing"
    assert _exists(Path(out))
    assert [p.name for p in processed] == ["Lecture.url"]


@needs_gate
def test_an_over_limit_unlink_is_not_mistaken_for_an_absent_file(deep_dir):
    """`missing_ok=True` swallows the FileNotFoundError an over-limit path
    raises, so the raw call is a SILENT no-op. Pin the prefixed form, which is
    what converters/video.py now uses at all three of its sites."""
    target = deep_dir / "recording.mp4"
    _put(target, b"\x00" * 32)

    Path(target).unlink(missing_ok=True)          # the raw form
    assert _exists(target), "control: the raw call is expected to be a no-op here"

    Path(make_long_path(target)).unlink(missing_ok=True)   # the fixed form
    assert not _exists(target)


# ------------------------------------------- layer 0 + the census (portable)

#: Modules that write INSIDE a course folder, or at the DESTINATION the user
#: picked - i.e. at a depth the user chooses, not one short by construction.
COURSE_FOLDER_MODULES = (
    "core/canvas_logic.py",
    "core/sync_manager.py",
    "sync/execution.py",
    "converters/post_processing.py",
    "converters/pdf.py",
    "converters/archive.py",
    "converters/excel.py",
    "converters/word.py",
    "converters/code.py",
    "converters/md.py",
    "converters/url.py",
    "converters/video.py",
    "panopto/runner.py",
    "app.py",
    "ui/download_settings.py",
    "ui/quick_download.py",
)

#: (module, receiver) pairs that are correct WITHOUT a make_long_path on the
#: same line. Each needs a reason, and "it looked fine" is not one - the whole
#: point of the census is that this list is short and argued.
MKDIR_EXEMPT = {
    ("converters/archive.py", "extract_dir"):
        "extract_dir is rebound to Path(_mlp(extract_dir)) a few lines above, "
        "inside `if os.name == 'nt'`, so it already carries the prefix here. "
        "Adding another would also be a NameError - that import is aliased _mlp.",
}


def _mkdir_receivers(path: Path):
    """(lineno, receiver source) for every `<expr>.mkdir(...)` in a module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "mkdir"):
            out.append((node.lineno, ast.unparse(node.func.value)))
    return out


#: Module-level directory creators, where the path is an ARGUMENT rather than
#: the receiver. `os.makedirs(course_folder / 'sub')` is not a `.mkdir` call on
#: anything, so the first version of this census - which only matched
#: `<expr>.mkdir(...)` - could not see it AT ALL.
#:
#: That blindness was latent, not live: no such call existed in these modules,
#: so the census passed and read as protection. Which is precisely why it had to
#: be closed - the guard would have stayed green while the first `os.makedirs`
#: anyone added inside a course folder crashed the download at depth. Found by
#: auditing the guard instead of the code it guards.
#:
#: It also removes a FALSE positive in the other direction: `os.mkdir(...)` does
#: match `attr == "mkdir"`, and its receiver is the bare module `os`, which can
#: never contain `make_long_path` - so a correctly-prefixed `os.mkdir` was
#: reported as an offender.
_MODULE_MKDIRS = {("os", "makedirs"), ("os", "mkdir")}

#: Wrappers that turn a prefixed string back into a PATH, and so can carry
#: the prefix onward. `x = os.path.getsize(make_long_path(p))` is an int and
#: cannot leak; `x = Path(make_long_path(p))` very much can - and the first
#: version of the leak guard, which matched only a BARE make_long_path call,
#: could not see the wrapped form at all.
#:
#: MODULE level so the guard and its control read the SAME set. They each
#: held a copy first, and the mutation pass caught it: deleting the guard's
#: copy SURVIVED, because the control was asserting against its own.
PATH_WRAPPERS = {"Path", "str", "join", "normpath", "abspath", "fspath",
                 "PurePath", "PureWindowsPath"}


def _unprefixed_mkdirs(rel: str, source: str | None = None):
    """The census, as a function so it can be pointed at synthetic source.

    Extracted for one reason: a guard that cannot be shown to say NO is not a
    guard. `test_the_census_can_actually_fail` feeds this a module that is
    plainly wrong and requires it to complain.
    """
    tree_src = source if source is not None else (REPO / rel).read_text(encoding="utf-8")
    tree = ast.parse(tree_src)
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)):
            continue
        receiver = ast.unparse(node.func.value)
        attr = node.func.attr
        if (receiver, attr) in _MODULE_MKDIRS:
            # os.makedirs(<path>) / os.mkdir(<path>) - the path is arg 0.
            checked = ast.unparse(node.args[0]) if node.args else ""
            label = f"{receiver}.{attr}({checked})"
        elif attr == "mkdir":
            checked = receiver
            label = f"{receiver}.mkdir(...)"
        else:
            continue
        if "make_long_path" in checked or "_mlp" in checked:
            continue
        if (rel, checked) in MKDIR_EXEMPT:
            continue
        offenders.append(f"{rel}:{node.lineno} {label}")
    return offenders


def test_every_course_folder_mkdir_goes_through_make_long_path():
    """THE DURABLE GUARD.

    A directory fails at 248 characters, and `mkdir` is the FIRST thing the
    download engine does for a course - so an unprefixed one is not a degraded
    feature, it is a crash with zero files. This counts the sites rather than
    checking that a fix exists, because the repo's failure mode is a fix that
    lands on some of them (pdf_looks_real sat on two of three delete sites for
    eight months).
    """
    checked, offenders = [], []
    for rel in COURSE_FOLDER_MODULES:
        checked.append(rel)
        offenders += _unprefixed_mkdirs(rel)

    # Coverage is asserted, not assumed. Narrowing the loop leaves a CORRECT
    # codebase passing, so the census cannot notice its own reduction - the one
    # mutant that survived the first pass did exactly that.
    assert checked == list(COURSE_FOLDER_MODULES), (
        "the census examined %d of %d modules" % (len(checked),
                                                  len(COURSE_FOLDER_MODULES)))
    assert not offenders, (
        "unprefixed mkdir on a path that can be inside a course folder:\n  "
        + "\n  ".join(offenders)
        + "\nWrap it as Path(make_long_path(x)).mkdir(...), or add it to "
          "MKDIR_EXEMPT with the reason it is already safe."
    )


@needs_gate
def test_zip_extraction_works_past_the_limit(deep_dir):
    """The archive itself is over the limit, not just its contents.

    `converters/archive.py` used to carry two claims, both wrong and both
    load-bearing: that the archive file "won't hit MAX_PATH" (a zip downloaded
    into a deep course folder measured 280 characters and could not be opened
    at all), and that tarfile rejects the prefix on old Pythons. It now opens
    through a FILE OBJECT, which settles both - Python's open() handles the
    prefix and zipfile/tarfile never see a path.
    """
    import zipfile
    from converters.archive import extract_archive

    payload = deep_dir.parent / "payload.txt"
    _put(payload, b"lecture notes")
    z = deep_dir / "Lecture materials.zip"
    with zipfile.ZipFile(make_long_path(z), "w") as zf:
        zf.write(make_long_path(payload), "notes.txt")
        zf.write(make_long_path(payload), "sub/slides.txt")
    assert len(str(z)) > 260

    assert extract_archive(str(z)) is True, "extraction silently did nothing"
    out = deep_dir / "Lecture materials"
    assert sorted(p.name for p in walk_files_long(out)) == ["notes.txt", "slides.txt"]
    assert not _exists(z), "the archive should be consumed on success"


@needs_gate
def test_a_panopto_shortcut_survives_a_deep_recording_folder(deep_dir):
    """Recordings sit at the deepest paths this app creates - course / "Panopto
    Recordings" / lecture title / lecture title. The Shortcut output writes a
    tiny file there and must be readable back, marker intact, or the URL
    compiler would consume it as if it were a Canvas link."""
    from shared.shortcuts import (write_shortcut, read_shortcut_url,
                                  is_produced_shortcut, SOURCE_PANOPTO,
                                  shortcut_extension)

    rec = deep_dir / "Panopto Recordings" / "Lecture 7"
    Path(make_long_path(rec)).mkdir(parents=True, exist_ok=True)
    p = rec / ("Lecture 7" + shortcut_extension())
    url = "https://cbs.cloud.panopto.eu/Panopto/Pages/Viewer.aspx?id=abc"

    write_shortcut(p, url, source=SOURCE_PANOPTO)
    assert _exists(p) and len(str(p)) > 260
    assert read_shortcut_url(p) == url
    assert is_produced_shortcut(p), (
        "without the marker the URL compiler would consume this shortcut, and "
        "the next sync would put it back - for ever")


def test_the_census_can_actually_fail():
    """NEGATIVE CONTROL, and the mutation pass is why it exists.

    Weakening the census - narrowing the module list, or making every receiver
    exempt - leaves it PASSING, because the production code is correct. So the
    census cannot detect its own removal, and a guard that only ever says yes is
    worse than no guard: it gets recorded as protection. This points it at
    source that is plainly wrong and requires a complaint.
    """
    bad = "import os\nfrom pathlib import Path\nPath('x').mkdir(parents=True)\n"
    assert _unprefixed_mkdirs("synthetic/bad.py", source=bad), (
        "the census no longer reports an unprefixed mkdir, so it is inert")

    good = ("from shared.helpers import make_long_path\n"
            "from pathlib import Path\n"
            "Path(make_long_path('x')).mkdir(parents=True)\n")
    assert not _unprefixed_mkdirs("synthetic/good.py", source=good), (
        "the census flags a correctly prefixed mkdir - it would cry wolf")


def test_the_census_sees_module_level_directory_creators():
    """`os.makedirs` is not a `.mkdir` call, and the census used to miss it.

    A guard is only worth what it can say NO to, so this asserts the new branch
    fires rather than trusting that it exists. Both directions, because the same
    change also fixed a false POSITIVE: `os.mkdir` does match `attr == "mkdir"`,
    and its receiver is the bare module `os`, which can never contain
    `make_long_path` - so a correctly prefixed `os.mkdir` was being reported.
    """
    for bad in ("import os\nos.makedirs(course / 'sub', exist_ok=True)\n",
                "import os\nos.mkdir(course / 'sub')\n"):
        assert _unprefixed_mkdirs("synthetic/bad.py", source=bad), (
            f"the census cannot see this directory creator:\n{bad}")

    for good in ("import os\nos.makedirs(make_long_path(course), exist_ok=True)\n",
                 "import os\nos.mkdir(make_long_path(course))\n"):
        assert not _unprefixed_mkdirs("synthetic/good.py", source=good), (
            f"the census cries wolf on a correctly prefixed creator:\n{good}")


def test_the_census_covers_the_modules_whose_fixes_are_load_bearing():
    """Narrowing COURSE_FOLDER_MODULES is invisible while the code is correct.

    These three are named explicitly because each carries a fix that a user
    feels directly: the course folder and the module folder (a crash with zero
    files), the sync root (a deep pair could never be created), and the
    discovery funnel every converter goes through.
    """
    for required in ("core/canvas_logic.py", "core/sync_manager.py",
                     "converters/post_processing.py"):
        assert required in COURSE_FOLDER_MODULES, (
            f"{required} dropped out of the mkdir census")


def test_every_unlink_in_the_delete_family_goes_through_the_prefix():
    """`unlink(missing_ok=True)` on an over-limit path is a SILENT no-op -
    missing_ok swallows the FileNotFoundError Windows raises for "too long", so
    it reads as "already gone". Measured on a real 323-character file.

    Counted rather than spot-checked: converters/video.py has THREE such sites
    and a fix that lands on two of them looks identical in review.
    """
    offenders = []
    for rel in ("converters/video.py", "converters/code.py",
                "converters/url.py", "converters/md.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("unlink", "remove")):
                continue
            call = ast.unparse(node)
            if "make_long_path" in call or "_mlp" in call:
                continue
            offenders.append(f"{rel}:{node.lineno} {call}")

    assert not offenders, (
        "delete in a source-consuming converter that cannot reach an "
        "over-limit path, so it silently deletes nothing:\n  "
        + "\n  ".join(offenders))


@needs_gate
def test_mkdir_parents_actually_works_through_the_prefix(deep_dir):
    """THE ASSUMPTION UNDER EVERY mkdir FIX, and it is not obvious.

    `Path.mkdir(parents=True)` builds the chain by walking `.parent`, and the
    prefix changes what `.parent` yields near the root - so "wrap it in
    make_long_path" could plausibly have failed at the top of the tree while
    looking correct. Measured here instead of assumed: the whole chain is
    created from a root where no parent exists yet, and a file is then written
    INSIDE it, because creating a directory nothing can be put in is worthless.
    """
    target = deep_dir / "Module 1" / "Week 3"
    Path(make_long_path(target)).mkdir(parents=True, exist_ok=True)
    assert _exists(target), "the parent chain was not created past the limit"

    Path(make_long_path(target)).mkdir(parents=True, exist_ok=True)   # idempotent

    f = target / "lecture.pdf"
    _put(f, b"%PDF-1.4\n")
    assert _exists(f) and len(str(f)) > 260


@needs_gate
def test_the_destination_writability_probe_accepts_a_deep_folder(tmp_path):
    """A user-facing BLOCKER, not a silent degradation.

    Both download screens probe the chosen destination by creating it and
    writing a marker. Unprefixed, that probe fails on a perfectly writable deep
    folder and the app refuses the download with "Cannot write to the selected
    download folder" - before anything is fetched. This is the probe's exact
    shape.
    """
    dest = tmp_path
    while len(str(dest)) < 300:
        dest = dest / ("d" * 40)

    Path(make_long_path(dest)).mkdir(parents=True, exist_ok=True)
    probe = dest / ".canvas_write_probe"
    with open(make_long_path(probe), "wb") as fh:
        fh.write(b"ok")
    assert _exists(probe)
    os.remove(make_long_path(probe))
    assert not _exists(probe)
    shutil.rmtree(make_long_path(tmp_path / ("d" * 40)), ignore_errors=True)


def test_no_prefixed_path_is_stored_returned_or_appended():
    """The one bug the long-path FIX itself can introduce.

    A `\\\\?\\` path that reaches a manifest row, an index or a UI string breaks
    every later comparison against a clean path - and nothing would fail loudly.
    Binding the prefixed form to a name is allowed only where it is provably
    consumed on the spot, so each site needs a reason.
    """
    allowed = {
        ("core/canvas_debug.py", "make_long_path(p)"):
            "the body of _lp itself - its whole purpose is to return the form",
        ("panopto/stream.py", "out_path"):
            "documented in situ: the function never returns or records a path, "
            "and the log line takes a basename",
        ("shared/helpers.py", "walk_root"):
            "the os.walk root and the relpath base; yielded paths are rebuilt "
            "from the CLEAN root",
        ("shared/shortcuts.py", "tmp_long"):
            "a temp file that only ever reaches open() and os.replace()",
        ("sync/execution.py", "_root_lp"):
            "the os.walk root and the relpath base; the stored value is the "
            "RELATIVE path, which carries no prefix",
        ("converters/archive.py", "abs_archive_lp"):
            "passed to open() only, so zipfile/tarfile get a file OBJECT and "
            "never a path; abs_archive stays clean and is what names the "
            "extraction folder, the log lines and the delete",
        # --- the WRAPPER form, `x = Path(make_long_path(y))` ---------------
        ("converters/archive.py", "extract_dir"):
            "rebound in place under `if os.name == 'nt'` and consumed entirely "
            "within this function: mkdir, zipfile/tarfile extraction targets, "
            "and the zip-slip guard - which compares extract_dir.resolve() "
            "against (extract_dir / member).resolve(), so BOTH sides carry the "
            "prefix and commonpath compares like for like (measured: resolve() "
            "keeps the prefix, benign member INSIDE, traversal BLOCKED). "
            "extract_archive returns a bool, never a path.",
        ("converters/verify.py", "p"):
            "a local in file_has_content / pdf_looks_real; only ever reaches "
            "exists(), stat() and open(), and both functions return "
            "(bool, reason) - no path leaves them",
    }
    #: Wrappers that turn a prefixed string back into a PATH, and so can carry
    #: the prefix onward. `x = os.path.getsize(make_long_path(p))` is an int and
    #: cannot leak; `x = Path(make_long_path(p))` very much can - and the first
    #: version of this guard, which only matched a BARE make_long_path call,
    #: could not see the wrapped form at all. Nine such bindings existed; eight
    #: were ints or bare names, one (archive.py's extract_dir) was a real
    #: prefixed path the guard had never examined.
    offenders = _prefixed_bindings(allowed, PATH_WRAPPERS)
    assert not offenders, (
        "a prefixed path is bound to a name without a recorded reason - if it "
        "reaches a manifest row or an index, every later comparison against a "
        "clean path silently fails:\n  " + "\n  ".join(offenders))


def _prefixed_bindings(allowed, path_wrappers, source_map=None):
    """Names bound to a `\\\\?\\`-prefixed path, minus the argued exemptions.

    A function, not an inline loop, for the reason the census already is: a
    guard that cannot be pointed at synthetic source cannot be shown to say NO,
    and the mutation pass proved that - deleting `path_wrappers` SURVIVED,
    because nothing exercised the wrapper branch.
    """
    offenders = []
    items = (list(source_map.items()) if source_map is not None else
             [(py.relative_to(REPO).as_posix(), None)
              for py in sorted(REPO.rglob("*.py"))
              if not any(p in {"dist", "build", "tests", "scripts", ".git",
                               "__pycache__", ".venv", "venv", "_audit_runs",
                               "docs"} for p in py.parts)])
    for rel, src in items:
        try:
            if src is None:
                src = (REPO / rel).read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            call = None
            key = None
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call, key = node.value, ast.unparse(node.targets[0])
            elif isinstance(node, ast.Return) and isinstance(node.value, ast.Call):
                call, key = node.value, ast.unparse(node.value)
            if call is None:
                continue
            fname = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if fname not in ("make_long_path", "_mlp", "_lp"):
                # The WRAPPER form: Path(make_long_path(x)) and friends. Only
                # wrappers that yield a PATH count - getsize() returns an int,
                # listdir() returns bare names, and neither can carry a prefix.
                if fname not in path_wrappers:
                    continue
                if not any(
                    isinstance(n, ast.Call)
                    and (getattr(n.func, "id", None)
                         or getattr(n.func, "attr", None))
                    in ("make_long_path", "_mlp", "_lp")
                    for n in ast.walk(call)
                ):
                    continue
                fname = f"{fname}(make_long_path"
            if (rel, key) in allowed:
                continue
            offenders.append(f"{rel}:{node.lineno} {key} = {fname}(...)")
    return offenders


def test_the_leak_guard_sees_the_wrapper_form():
    """NEGATIVE CONTROL for the wrapper branch.

    `x = Path(make_long_path(y))` is the form that actually carries a prefix
    onward, and the first version of the guard could not see it. The mutation
    pass caught that this was UNTESTED: deleting `path_wrappers` survived,
    because every real wrapper-form binding is exempt, so nothing was left to
    flag. Both directions, since a wrapper that yields an int cannot leak.
    """
    wrappers = PATH_WRAPPERS

    leaks = {"synthetic/leak.py": "root = Path(make_long_path(course))\n"}
    assert _prefixed_bindings({}, wrappers, source_map=leaks), (
        "the leak guard cannot see Path(make_long_path(x)) - the one wrapper "
        "form that really does carry the prefix onward")

    # An int can never carry a prefix, so flagging it would be crying wolf.
    ints = {"synthetic/int.py": "n = os.path.getsize(make_long_path(p))\n"}
    assert not _prefixed_bindings({}, wrappers, source_map=ints), (
        "the leak guard flags a wrapper that returns an int")

    # And the exemption must still work, or every real site would have to be
    # rewritten rather than argued for.
    assert not _prefixed_bindings({("synthetic/leak.py", "root"): "argued"},
                                  wrappers, source_map=leaks)


def test_the_census_exemptions_still_describe_real_code():
    """An exemption whose site has moved is an exemption hiding a live bug."""
    for (rel, receiver), why in MKDIR_EXEMPT.items():
        receivers = [r for _ln, r in _mkdir_receivers(REPO / rel)]
        assert receiver in receivers, (
            f"MKDIR_EXEMPT names {receiver}.mkdir in {rel}, which no longer "
            f"exists. Reason on file: {why}"
        )


def test_post_processing_discovery_uses_the_long_path_walk():
    """`_glob_files` is the single funnel every converter goes through, so this
    one call decides whether nine features work at depth."""
    src = (REPO / "converters/post_processing.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_glob_files")
    body = ast.unparse(fn)
    assert "walk_files_long" in body, "_glob_files went back to rglob"
    assert "path_exists" in body, "_glob_files went back to Path.exists()"
    assert ".rglob(" not in body


def test_the_gate_script_exists_and_is_the_one_probe():
    """The behavioural tests above skip themselves on a masked machine and say
    so by naming this script. If it is gone, that reason is a dead reference."""
    script = REPO / "scripts" / "check_longpath_gate.py"
    assert script.is_file()
    spec = importlib.util.spec_from_file_location("_gate", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.VALID == 0 and mod.MASKED != 0


# ------------------------------------------------- the HALF-FIX shape

#: `path_exists(x)` and then an unprefixed operation on the same `x`.
#:
#: This is the shape a long-path fix ACTUALLY regresses into, and it is worse
#: than a plain miss because the existence check passes: the file is reported
#: present and the very next line raises FileNotFoundError, which every handler
#: in this repo reads as "absent". Two live instances were found by pointing
#: this at the tree on 2026-08-22, both introduced by a fix that prefixed the
#: check and stopped there:
#:
#:   * `shared/components.py` error_log_dialog - the engine WRITES
#:     download_errors.txt through make_long_path and this read it back without,
#:     so at depth the app could not read a log it had just written. The error
#:     dialog is the one screen a user opens when something already went wrong.
#:   * `ui/sync_dialogs.py` - sized an ignored Panopto recording, so the dialog
#:     reported 0 bytes for recordings plainly on disk.
#:
#: Neither is data loss; both are the app lying about its own files. The value
#: of this guard is that it generalises - the third instance fails a test
#: instead of shipping.
_HALF_FIX_OPS = ("stat", "open", "read_text", "read_bytes", "write_text",
                 "write_bytes", "unlink", "touch", "iterdir", "glob", "rglob",
                 "rename", "replace", "is_file", "is_dir", "getsize",
                 "getmtime", "listdir", "scandir", "remove")

#: (module, variable) pairs where the follow-up genuinely needs no prefix.
HALF_FIX_EXEMPT: dict[tuple[str, str], str] = {}


def _half_prefixed_sites(root: Path | None = None, source_map=None):
    """Every `path_exists(x)` followed within 6 lines by an unprefixed op on x.

    Line-based rather than AST, deliberately: the defect is about two ADJACENT
    statements agreeing, and the window is what makes it precise instead of
    flagging every later use of a long-lived name.

    THE WINDOW COUNTS CODE LINES, NOT PHYSICAL ONES, and that is not a detail.
    The first version counted physical lines, so writing an eight-line comment
    ABOVE the fixed read pushed it out of the window - and the guard then passed
    against deliberately reverted code, reporting a live defect as absent. Found
    by running the control, not by reading. It is the same trap this repo already
    records for the transcription sweep: "documenting the fix pushed the call out
    of the window, so the tests reported it as missing when it was right there."
    A guard whose reach shrinks when someone explains the code is worse than
    none, because the explaining is exactly what a good fix comes with.
    """
    import re
    root = root or REPO
    skip = {"dist", "build", "tests", "scripts", ".git", "__pycache__",
            ".venv", "venv", "_audit_runs", "docs"}
    op_re = re.compile(r"\.\s*(" + "|".join(_HALF_FIX_OPS) + r")\b")
    items = (source_map.items() if source_map is not None else
             ((py.relative_to(root).as_posix(), None)
              for py in sorted(root.rglob("*.py"))
              if not any(p in skip for p in py.parts)))
    offenders = []
    for rel, src in items:
        if src is None:
            src = (root / rel).read_text(encoding="utf-8")
        if "path_exists" not in src:
            continue
        # Comments and blank lines are dropped BEFORE windowing, so the reach
        # of the guard does not depend on how well the code is documented.
        code = [(n + 1, ln) for n, ln in enumerate(src.splitlines())
                if ln.strip() and not ln.lstrip().startswith("#")]
        for i, (lineno, line) in enumerate(code):
            m = re.search(r"path_exists\(\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\)", line)
            if not m:
                continue
            var = m.group(1)
            if (rel, var) in HALF_FIX_EXEMPT:
                continue
            for nxt_no, nxt in code[i + 1:i + 7]:
                if ("make_long_path" in nxt or "_mlp(" in nxt
                        or "path_exists" in nxt):
                    continue
                bare = re.search(re.escape(var) + r"\s*" + op_re.pattern, nxt)
                wrapped = re.search(
                    r"\b(getsize|getmtime|listdir|scandir|remove|open|stat)\(\s*"
                    + re.escape(var) + r"\s*[,)]", nxt)
                if bare or wrapped:
                    offenders.append(
                        f"{rel}:{lineno} checks {var} with the prefix, then "
                        f"line {nxt_no} uses it without: {nxt.strip()[:70]}")
                    break
    return offenders


def test_no_existence_check_is_prefixed_while_its_follow_up_is_not():
    """THE GUARD THAT GENERALISES. See _half_prefixed_sites for the two live
    instances it found."""
    offenders = _half_prefixed_sites()
    assert not offenders, (
        "path_exists() says the file is there and the next line cannot open "
        "it - at depth this reports a present file as missing:\n  "
        + "\n  ".join(offenders))


def test_the_half_fix_guard_can_actually_fail():
    """NEGATIVE CONTROL - a guard that only ever says yes is not a guard."""
    bad = {"synthetic/bad.py":
           "if path_exists(p):\n    total += p.stat().st_size\n"}
    assert _half_prefixed_sites(source_map=bad), (
        "the half-fix guard no longer reports the shape it exists for")

    good = {"synthetic/good.py":
            "if path_exists(p):\n"
            "    total += os.stat(make_long_path(p)).st_size\n"}
    assert not _half_prefixed_sites(source_map=good), (
        "the half-fix guard flags a correctly prefixed follow-up")

    # THE CASE THAT ACTUALLY HAPPENED. With a physical-line window, writing an
    # explanation above the offending call pushes it out of reach and the guard
    # goes quiet - which is how it passed against deliberately reverted code.
    # The mutation pass proved this was untested: reverting the window to
    # physical lines SURVIVED, because both cases above are adjacent lines.
    documented = {"synthetic/documented.py":
                  "if path_exists(p):\n"
                  + "".join(f"    # explanation line {i}\n" for i in range(8))
                  + "    total += p.stat().st_size\n"}
    assert _half_prefixed_sites(source_map=documented), (
        "a comment between the check and the follow-up blinds the guard - it "
        "must count CODE lines, never physical ones")


@needs_gate
def test_a_course_folder_error_log_can_be_read_back(deep_dir):
    """The engine writes download_errors.txt prefixed; the dialog must read it
    the same way. Measured: unprefixed read_text raised FileNotFoundError on a
    275-character log that path_exists reported as present."""
    log = deep_dir / "download_errors.txt"
    with open(make_long_path(log), "w", encoding="utf-8") as fh:
        fh.write("[2026-08-22] Processing Error: something went wrong\n")

    assert path_exists(log), "the fixture did not actually create the log"
    content = Path(make_long_path(log)).read_text(encoding="utf-8").strip()
    assert "Processing Error" in content

    # The control: without the prefix this is exactly what the dialog used to do.
    with pytest.raises(OSError):
        log.read_text(encoding="utf-8")
