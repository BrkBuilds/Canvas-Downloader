"""Crash- and leak-vector hardening found by the 2026-08-08 deep audit.

Each test here corresponds to a defect that was reproduced against the real code
before it was fixed. They are grouped by the bug CLASS rather than by module,
because in every case the class already had a precedent somewhere else in the
app and the new instance was simply a place the earlier sweep did not reach.
"""

from __future__ import annotations

import ast
import io
import os
import pathlib
import sys
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


def _src(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ── An Office COM instance must never be abandoned ───────────────────────────
#
# `_init_app` spawns Office with DispatchEx and then sets a few properties. A
# locked-down Office build can REFUSE those properties - the PowerPoint sibling
# already carried a comment saying exactly that - and the raise landed in a
# handler that dropped self.app while self._com_pid was still None. The process
# was then unreachable: a COM-spawned Office is a child of DCOM/RPCSS, not of
# us, so the session orphan reaper (core/health_log) never sees it either.

CONVERTERS = [
    ("converters/word.py", "WordToPDF", "WINWORD.EXE", "DisplayAlerts"),
    ("converters/excel.py", "ExcelToPDF", "EXCEL.EXE", "EnableEvents"),
    ("converters/pdf.py", "PowerPointToPDF", "POWERPNT.EXE", "Visible"),
]

FAKE_PID = 424242


class _HostileApp:
    """A COM object that accepts DispatchEx and then refuses one property."""

    def __init__(self, failing_prop):
        object.__setattr__(self, "_failing", failing_prop)
        object.__setattr__(self, "quit_called", False)

    def __setattr__(self, name, value):
        if name == object.__getattribute__(self, "_failing"):
            raise Exception("COM Error 0x800A03EC: restricted by policy")
        object.__setattr__(self, name, value)

    def Quit(self):
        object.__setattr__(self, "quit_called", True)


def _drive_init(cls, exe, failing_prop=None, pid_lookup_raises=False,
                then_kill=False):
    """Run the REAL _init_app with an injected failure."""
    killed: list = []
    holder: dict = {}

    fake_client = types.ModuleType("win32com.client")
    fake_win32com = types.ModuleType("win32com")

    def DispatchEx(_progid):
        app = _HostileApp(failing_prop)
        holder["app"] = app
        return app

    fake_client.DispatchEx = DispatchEx
    fake_win32com.client = fake_client
    sys.modules["win32com"] = fake_win32com
    sys.modules["win32com.client"] = fake_client

    import engine.office_pid as opid
    real = (opid.snapshot_office_pids, opid.find_new_office_pid,
            opid.pid_is_process, opid.kill_office_pid)

    def _find(_exe, _pre):
        if pid_lookup_raises:
            raise RuntimeError("psutil exploded")
        return FAKE_PID

    opid.snapshot_office_pids = lambda e: set()
    opid.find_new_office_pid = _find
    opid.pid_is_process = lambda pid, e: pid == FAKE_PID and e == exe
    opid.kill_office_pid = lambda pid, e: killed.append((pid, e))
    try:
        inst = cls()
        inst._init_app()
        if then_kill:
            inst._kill_app()          # while the patches are still installed
    finally:
        (opid.snapshot_office_pids, opid.find_new_office_pid,
         opid.pid_is_process, opid.kill_office_pid) = real
        sys.modules.pop("win32com", None)
        sys.modules.pop("win32com.client", None)
    return inst, holder.get("app"), killed


def _load(rel, name):
    mod = __import__(rel[:-3].replace("/", "."), fromlist=[name])
    return getattr(mod, name)


@pytest.mark.parametrize("rel,clsname,exe,prop", CONVERTERS)
def test_a_restricted_property_does_not_abort_office_init(rel, clsname, exe, prop):
    """Word and Excel set these properties unguarded; only PowerPoint wrapped
    them. An Office build that refuses one must degrade to a usable instance,
    not to a dropped reference and a stranded process."""
    inst, _app, _killed = _drive_init(_load(rel, clsname), exe, failing_prop=prop)
    assert inst.app is not None, f"{clsname}: a refused {prop} still aborts init"
    assert inst._com_pid == FAKE_PID, f"{clsname}: the spawned PID is not tracked"


@pytest.mark.parametrize("rel,clsname,exe,prop", CONVERTERS)
def test_the_pid_is_captured_before_any_property_is_touched(rel, clsname, exe, prop):
    """Ordering is the fix, not the guards.

    Whatever else changes, `find_new_office_pid` has to be reached before the
    first property assignment: everything between DispatchEx and that call is a
    window in which a raise strands a real Office process.
    """
    tree = ast.parse(_src(rel))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_init_app")
    pid_line = min(n.lineno for n in ast.walk(fn)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "find_new_office_pid")
    prop_lines = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Assign)
                  for t in n.targets
                  if isinstance(t, ast.Attribute)
                  and isinstance(t.value, ast.Attribute)
                  and t.value.attr == "app"]
    assert prop_lines, f"{clsname}: no self.app.<prop> assignment found to order against"
    assert pid_line < min(prop_lines), (
        f"{clsname}: a property is set before the PID is captured - a raise "
        f"there abandons a live {exe}")


@pytest.mark.parametrize("rel,clsname,exe,prop", CONVERTERS)
def test_pid_lookup_failure_does_not_abandon_a_live_instance(rel, clsname, exe, prop):
    inst, app, _killed = _drive_init(_load(rel, clsname), exe, pid_lookup_raises=True)
    assert inst.app is not None, f"{clsname}: a failed PID lookup dropped a live app"
    inst._kill_app()
    assert app.quit_called, f"{clsname}: Quit() never reached the instance"


@pytest.mark.parametrize("rel,clsname,exe,prop", CONVERTERS)
def test_init_failure_reclaims_the_process(rel, clsname, exe, prop):
    """The handler must Quit + PID-kill, not just drop the reference."""
    tree = ast.parse(_src(rel))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_init_app")
    generic = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)
               and isinstance(h.type, ast.Name) and h.type.id == "Exception"]
    # the outermost handler is the init failure one (the inner guards are `pass`)
    outer = max(generic, key=lambda h: getattr(h, "end_lineno", 0) - h.lineno)
    calls = {n.func.attr for n in ast.walk(outer)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "_kill_app" in calls, (
        f"{clsname}: init failure drops self.app without reclaiming the process")


@pytest.mark.parametrize("rel,clsname,exe,prop", CONVERTERS)
def test_teardown_force_kills_only_the_tracked_pid(rel, clsname, exe, prop):
    _inst, _app, killed = _drive_init(_load(rel, clsname), exe,
                                      failing_prop=prop, then_kill=True)
    assert killed == [(FAKE_PID, exe)], f"{clsname}: {exe} orphaned ({killed})"


# ── macOS: the source delete must be gated on a PROVEN pdf ───────────────────
#
# Every Office converter deletes the file it converted FROM - the one
# irreversible step in the pipeline, on what may be the user's only copy. The
# WINDOWS/COM branch was hardened to prove the PDF first (pdf_looks_real). The
# macOS/AppleScript branch was not: it deleted on `run_applescript` returning
# True, whose success test is `dst.exists()` - precisely the check this project
# already recorded as too weak ("PowerPoint tested exists(), which is better but
# still passes a 0-byte stub"). So the fix landed on one platform only.

_MAC_CONVERTERS = [
    ("converters.word", "WordToPDF", "_convert_applescript_word", ".doc"),
    ("converters.excel", "ExcelToPDF", "_convert_applescript_excel", ".xls"),
    ("converters.pdf", "PowerPointToPDF", "_convert_applescript_pptx", ".ppt"),
]

_REAL_PDF = b"%PDF-1.4\n" + b"x" * 900 + b"\n%%EOF\n"
_STUBS = [
    pytest.param(b"", id="empty"),
    pytest.param(b"%PDF-1.4\n" + b"x" * 30, id="truncated"),
    pytest.param(b"<html>error</html>" * 60, id="not-a-pdf"),
]


def _drive_mac_convert(modname, clsname, bridge_attr, ext, pdf_bytes, tmp_path):
    """Run the REAL convert() down its macOS branch. Returns (src_kept, out)."""
    import importlib
    mod = importlib.import_module(modname)
    cls = getattr(mod, clsname)

    src = tmp_path / f"lecture{ext}"
    src.write_bytes(b"the user's only copy" * 50)

    def fake_bridge(self, s, d, *a, **k):
        pathlib.Path(d).write_bytes(pdf_bytes)   # what Office left behind
        return True                              # dst.exists() -> True

    original_bridge = getattr(cls, bridge_attr)
    real_platform = mod.sys.platform
    setattr(cls, bridge_attr, fake_bridge)
    mod.sys.platform = "darwin"
    try:
        out = cls().convert(str(src))
    finally:
        setattr(cls, bridge_attr, original_bridge)
        mod.sys.platform = real_platform
    return src.exists(), out


@pytest.mark.parametrize("modname,clsname,bridge,ext", _MAC_CONVERTERS)
@pytest.mark.parametrize("stub", _STUBS)
def test_macos_keeps_the_original_when_office_leaves_a_stub(
        modname, clsname, bridge, ext, stub, tmp_path):
    kept, out = _drive_mac_convert(modname, clsname, bridge, ext, stub, tmp_path)
    assert kept, (
        f"{clsname}: macOS deleted the user's original on a {len(stub)}-byte "
        "output - run_applescript's exists() test accepts a stub")
    # and it must not report a converted path either
    path_part = out[0] if isinstance(out, tuple) else out
    assert path_part is None, f"{clsname}: reported success for a stub PDF"


@pytest.mark.parametrize("modname,clsname,bridge,ext", _MAC_CONVERTERS)
def test_macos_still_replaces_the_original_on_a_real_pdf(
        modname, clsname, bridge, ext, tmp_path):
    """The gate must not break the working case."""
    kept, out = _drive_mac_convert(modname, clsname, bridge, ext,
                                   _REAL_PDF, tmp_path)
    assert not kept, f"{clsname}: a genuine conversion no longer replaces the source"
    path_part = out[0] if isinstance(out, tuple) else out
    assert path_part, f"{clsname}: a genuine conversion returned no path"


@pytest.mark.parametrize("rel,clsname,exe,prop", CONVERTERS)
def test_both_platform_branches_verify_before_deleting(rel, clsname, exe, prop):
    """Structural: neither branch may delete without pdf_looks_real above it.

    Guards the ASYMMETRY specifically - one platform being hardened and the
    other left behind is how this shipped.
    """
    src = _src(rel)
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "convert")
    verify_lines = [n.lineno for n in ast.walk(fn)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "pdf_looks_real"]
    unlink_lines = [n.lineno for n in ast.walk(fn)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "unlink"
                    # ignore cleanup of our own temp/output artifacts
                    and "safe_pdf" not in ast.unparse(n.func.value)]
    assert len(verify_lines) >= 2, (
        f"{clsname}: only {len(verify_lines)} pdf_looks_real gate(s) for "
        f"{len(unlink_lines)} source delete(s) - one platform branch is unguarded")
    assert len(verify_lines) >= len(unlink_lines), (
        f"{clsname}: {len(unlink_lines)} source deletes but only "
        f"{len(verify_lines)} verifications")
    for u in unlink_lines:
        assert any(v < u for v in verify_lines), (
            f"{clsname}: the delete at line {u} has no verification before it")


# ── The HTML->Markdown converter must not convert away to nothing ────────────
#
# The last weak sibling in the delete family. code.py checks st_size, video.py
# and the Office trio call into converters.verify - md.py checked a bare
# exists(), and a 0-byte file exists. markdownify returns "" for a page whose
# visible content is all script/style (which this converter has just
# decomposed), so a Canvas Page rendered by an embedded widget / LTI iframe /
# H5P embed produced an empty .md and lost its source HTML.

@pytest.mark.parametrize("label,html", [
    ("only-script-and-style",
     "<html><head><style>body{color:red}</style></head>"
     "<body><script>renderPage()</script></body></html>"),
    ("empty-body", "<html><body></body></html>"),
    ("whitespace-only", "<html><body>   \n\t  </body></html>"),
    ("script-rendered-widget", "<html><body><script>H5P.init()</script></body></html>"),
])
def test_a_content_free_page_keeps_its_html(label, html, tmp_path):
    from converters.md import convert_html_to_md

    src = tmp_path / f"{label}.html"
    src.write_text(html, encoding="utf-8")
    out = convert_html_to_md(src)

    assert src.exists(), (
        f"{label}: the source HTML was deleted for an empty conversion")
    assert out is None, f"{label}: reported success for an empty conversion"
    assert not src.with_suffix(".md").exists(), (
        f"{label}: left an empty .md behind for the next sync to reason about")


@pytest.mark.parametrize("html,expect", [
    ("<html><body><h1>Uge 1</h1><p>Read chapter 3.</p></body></html>", "Uge 1"),
    ("<html><body>Hi</body></html>", "Hi"),
])
def test_a_real_page_still_converts_and_replaces_its_html(html, expect, tmp_path):
    """The guard must not break the working case, including a very short page."""
    from converters.md import convert_html_to_md

    src = tmp_path / "page.html"
    src.write_text(html, encoding="utf-8")
    out = convert_html_to_md(src)

    assert out is not None
    md = src.with_suffix(".md")
    assert md.exists() and expect in md.read_text(encoding="utf-8")
    assert not src.exists(), "a genuine conversion should replace the source"


def test_a_silently_empty_write_still_keeps_the_html(tmp_path, monkeypatch):
    """Defence in depth for the write itself.

    The pre-write guard covers "markdownify produced nothing". This covers the
    other direction: the converter had real text and the WRITE produced nothing
    anyway - a full disk with delayed allocation, a network share dropping the
    bytes. `exists()` is True in that state and the HTML would be deleted.
    """
    import builtins
    from converters.md import convert_html_to_md

    src = tmp_path / "page.html"
    src.write_text("<html><body><h1>Uge 1</h1><p>Real text.</p></body></html>",
                   encoding="utf-8")

    real_open = builtins.open

    class _Swallow:
        """Accepts writes, commits nothing - a silently failed write."""

        def __init__(self, path):
            self._f = real_open(path, "w", encoding="utf-8")

        def write(self, _data):
            return 0

        def flush(self):
            pass

        def fileno(self):
            return self._f.fileno()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self._f.close()
            return False

    def swallowing_open(path, *a, **k):
        if str(path).endswith(".md") and a and "w" in str(a[0]):
            return _Swallow(path)
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", swallowing_open)
    out = convert_html_to_md(src)
    monkeypatch.undo()

    assert out is None, "reported success for a write that committed nothing"
    assert src.exists(), (
        "the source HTML was deleted although the .md write produced 0 bytes - "
        "an exists() check passes an empty file")


def test_every_source_deleting_converter_verifies_content_not_just_existence():
    """The family rule, asserted across the family.

    `exists()` is the check this project has now been burned by twice (macOS
    Office, then md.py). Every converter that deletes what it converted FROM
    must CALL a content gate - matched on the call, not on the token, because
    an `import file_has_content` left behind by a reverted fix would satisfy a
    substring test while nothing actually ran.
    """
    family = {
        "converters/code.py": {"file_has_content", "st_size"},
        "converters/md.py": {"file_has_content"},
        "converters/video.py": {"file_has_content"},
        "converters/word.py": {"pdf_looks_real"},
        "converters/excel.py": {"pdf_looks_real"},
        "converters/pdf.py": {"pdf_looks_real"},
    }
    for rel, accepted in family.items():
        tree = ast.parse(_src(rel))
        called = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Name):
                    called.add(f.id)
                elif isinstance(f, ast.Attribute):
                    called.add(f.attr)
            # `x.stat().st_size` reads as an Attribute, not a Call
            if isinstance(n, ast.Attribute) and n.attr == "st_size":
                called.add("st_size")
        assert called & accepted, (
            f"{rel} deletes its source without CALLING a content gate "
            f"(expected one of {sorted(accepted)}) - an exists() test passes a "
            f"0-byte stub")


# ── AppleScript string literals cannot span lines ────────────────────────────

def test_as_posix_flattens_line_breaks():
    """macOS permits every byte but '/' and NUL in a filename, so a path can
    carry a newline - from the user's own chosen folder, or from an extracted
    archive member (zip member names never pass through _sanitize_filename).
    A raw newline inside an AppleScript string literal is a SYNTAX error that
    kills the whole script, so every Office conversion in that folder fails
    with an opaque osascript message.
    """
    from engine.applescript_bridge import _as_posix

    class _P:
        def __init__(self, s):
            self._s = s

        def resolve(self):
            return self

        def __str__(self):
            return self._s

    out = _as_posix(_P('/Users/x/My\nCourses/a"b\\c/notes.docx'))
    assert "\n" not in out and "\r" not in out, "a newline would break the script"
    assert '\\"' in out, "double quotes must still be escaped"
    assert "\\\\" in out, "backslashes must still be escaped"


def test_as_posix_matches_the_apps_own_escaping_rule():
    """No AppleScript builder may be weaker than any other.

    This used to read the SOURCE of ``_as_posix`` and require the four escape
    literals to appear inside it. That anchored on a spelling: the escaping was
    later lifted into the shared ``applescript_string`` (because a third
    builder, ``engine.notifications``, had diverged and was flattening only
    ``\\n``), and this test then reported the guard as MISSING while it was
    right there one call away - the brittle-anchor trap, again. Assert the
    BEHAVIOUR, and assert it of every builder rather than of one.
    """
    from engine.applescript_bridge import _as_posix, applescript_string
    from pathlib import Path as _P

    probe = 'a\nb\rc"d\\e'
    for name, out in (
        ("applescript_string", applescript_string(probe)),
        ("_as_posix", _as_posix(_P("/tmp") / probe.replace("\\", "_"))),
    ):
        assert "\n" not in out and "\r" not in out, f"{name} leaves a line break"
    shared = applescript_string(probe)
    assert '\\"' in shared, "double quotes must still be escaped"
    assert "\\\\" in shared, "backslashes must still be escaped"


# ── Atomic-write leftovers inside a course folder ────────────────────────────

def test_tmp_files_count_as_partial_artifacts():
    """Two writers put their temp file INSIDE the course folder, so a crash
    between the write and the os.replace strands it where the analyzer looks:
    shared.shortcuts.write_shortcut and converters.url. Unrecognised, such a
    file reads as study material and is eligible to be healed onto a genuinely
    missing manifest row."""
    from core.sync_manager import _is_partial_artifact

    assert _is_partial_artifact("Lecture 3 (Panopto).url.tmp") is True
    assert _is_partial_artifact("Lecture 3 (Panopto).webloc.tmp") is True
    assert _is_partial_artifact("Compiled_External_Links.tmp") is True
    # the pre-existing shapes must keep working
    assert _is_partial_artifact("slides.pdf.part") is True
    assert _is_partial_artifact("lecture.part.mp4") is True
    # and real course material must not be swept up
    for keep in ("notes.pdf", "Lecture 3 (Panopto).url", "template.dotx",
                 "readme.txt", "data.tmpl"):
        assert _is_partial_artifact(keep) is False, keep


def test_the_shortcut_writer_still_produces_a_recognised_temp_name():
    """The exclusion above is only correct while the writer keeps using a
    .tmp suffix - if it changes shape, the exclusion silently stops matching."""
    from core.sync_manager import _is_partial_artifact
    src = _src("shared/shortcuts.py")
    assert 'path.with_name(path.name + ".tmp")' in src
    assert _is_partial_artifact("anything.url" + ".tmp") is True


# ── One path key, not three ──────────────────────────────────────────────────
#
# Three places ask "is this file on disk already tracked?" by comparing a
# manifest path against an os.walk path. They had three different
# normalisations: heal_manifest and the untracked-file count used bare
# normpath, analyze_course used normcase+normpath, and none applied Unicode
# normalisation. Same divergent-primitive shape as the make_long_path duplicate.

def test_path_key_is_case_insensitive_where_the_filesystem_is():
    """A case-only rename is legal and invisible on Windows/macOS. Without
    normcase the file reads as untracked, which inflates the count the review
    screen shows and puts a tracked file into the heal pool."""
    from core.sync_manager import _path_key
    a = _path_key(r"C:\Studie\Modules\Uge 1\Notes.pdf")
    b = _path_key(r"C:\Studie\Modules\Uge 1\notes.pdf")
    if os.path.normcase("A") == "a":       # case-insensitive platform
        assert a == b
    else:
        assert a != b, "case must stay significant on a case-sensitive platform"


def test_path_key_folds_hfsplus_decomposed_names():
    """APFS is normalisation-PRESERVING, so a modern Mac returns the NFC the
    downloader wrote. HFS+ is not - it stores NFD - and an external drive is an
    ordinary place to keep a course folder. Danish 'aa-ring' decomposes; 'oe'
    and 'ae' do not, which is what makes the symptom look random."""
    import unicodedata
    from core.sync_manager import _path_key

    nfc = "/Volumes/Backup/Makro/Modules/Uge 1/\u00c5rsregnskab.pdf"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd, "test string must actually decompose"
    assert _path_key(nfc) == _path_key(nfd)


def test_every_tracked_path_comparison_uses_the_shared_key():
    """The bug was three copies drifting, so the guard is that there is one."""
    src = _src("core/sync_manager.py")
    tree = ast.parse(src)
    for fname in ("heal_manifest", "analyze_course"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == fname)
        seg = "\n".join(src.splitlines()[fn.lineno - 1:fn.end_lineno])
        assert "os.path.normpath(str(" not in seg, (
            f"{fname} compares paths with a hand-rolled normpath again - use "
            "_path_key so all three sites cannot drift apart")


def test_a_case_renamed_file_is_not_counted_as_untracked(tmp_path):
    """End to end through the real SyncManager path key."""
    from core.sync_manager import _path_key
    course = tmp_path / "Makro"
    (course / "Modules" / "Uge 1").mkdir(parents=True)
    disk = course / "Modules" / "Uge 1" / "notes.pdf"
    disk.write_bytes(b"x" * 100)

    tracked = {_path_key(course / "Modules/Uge 1/Notes.pdf")}
    if os.path.normcase("A") == "a":
        assert _path_key(disk) in tracked, (
            "a case-only rename is reported as an untracked file")


# ── A naive/aware datetime comparison is a TypeError ─────────────────────────
#
# _is_canvas_newer parses two server-controlled timestamp strings inside a try
# that names (ValueError, TypeError) - and then COMPARED them outside it. The
# one exception the handler names is the one it could not catch, and
# analyze_course has no try around the call, so it aborts the whole course.

def _cfi(modified, size=2000):
    from core.sync_manager import CanvasFileInfo
    return CanvasFileInfo(id=555, filename="s.pdf", display_name="s.pdf",
                          size=size, modified_at=modified, url="")


def _entry(date_str):
    return {"canvas_updated_at": date_str, "original_md5": "", "original_size": 1000}


@pytest.fixture
def _sm(tmp_path):
    from core.sync_manager import SyncManager
    return SyncManager(str(tmp_path), course_id=1, course_name="Makro")


@pytest.mark.parametrize("manifest_date", [
    "2026-07-01T10:00:00Z",     # aware - the normal Canvas form
    "2026-07-01T10:00:00",      # naive  - fromisoformat accepts it happily
    "2026-07-01",               # date-only - also parses, also naive
    "2026-07-01T10:00:00+02:00",  # a non-UTC offset
])
def test_mixed_timestamp_forms_never_raise(_sm, manifest_date):
    """Every one of these used to raise TypeError out of analyze_course."""
    assert _sm._is_canvas_newer(_cfi("2026-08-01T10:00:00Z"),
                                _entry(manifest_date)) is True


@pytest.mark.parametrize("canvas_date", ["2026-08-01T10:00:00Z",
                                         "2026-08-01T10:00:00"])
def test_a_naive_canvas_timestamp_is_read_as_utc(_sm, canvas_date):
    """Canvas documents UTC, so a missing offset means UTC - which makes the
    verdict CORRECT, not merely safe. Falling into the except would answer
    'not updated' and silently skip a genuine update."""
    assert _sm._is_canvas_newer(_cfi(canvas_date),
                                _entry("2026-07-01T10:00:00Z")) is True
    assert _sm._is_canvas_newer(_cfi(canvas_date),
                                _entry("2026-09-01T10:00:00Z")) is False


def test_the_same_instant_written_two_ways_is_not_an_update(_sm):
    """The phantom-update direction: 'Z' and an offset-less UTC stamp name the
    same moment and must not read as newer."""
    assert _sm._is_canvas_newer(_cfi("2026-07-01T10:00:00Z"),
                                _entry("2026-07-01T10:00:00")) is False


def test_the_comparison_lives_inside_the_parse_guard():
    """Structural: the guard must cover the statement it was written for."""
    tree = ast.parse(_src("core/sync_manager.py"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_is_canvas_newer")
    tries = [t for t in ast.walk(fn) if isinstance(t, ast.Try)
             if any("fromisoformat" in ast.dump(b) for b in t.body)]
    assert tries, "the timestamp parse is no longer wrapped in a try"
    t = tries[0]
    compares = [c for c in ast.walk(t) if isinstance(c, ast.Compare)
                and any(isinstance(o, (ast.Lt, ast.Gt, ast.LtE, ast.GtE))
                        for o in c.ops)]
    assert compares, (
        "the datetime comparison is outside the try that parses it - a "
        "naive/aware pair raises TypeError straight out of analyze_course")


def test_a_naive_timestamp_is_read_as_UTC_specifically(_sm):
    """Not just 'some zone' - UTC, because that is what Canvas documents.

    The month-apart cases above pass under any offset, so they cannot tell UTC
    from a wrong zone. This one is one hour apart: read as UTC the Canvas stamp
    is newer, and under any other offset the verdict flips.
    """
    # naive 10:00 == 10:00Z, which is one hour after the manifest's 09:00Z
    assert _sm._is_canvas_newer(_cfi("2026-08-01T10:00:00"),
                                _entry("2026-08-01T09:00:00Z")) is True
    # ...and one hour BEFORE 11:00Z
    assert _sm._is_canvas_newer(_cfi("2026-08-01T10:00:00"),
                                _entry("2026-08-01T11:00:00Z")) is False


def test_a_real_offset_is_honoured_not_overwritten(_sm):
    """Normalisation must only fill in a MISSING zone, never replace a real one.
    12:00+02:00 is 10:00Z, i.e. one hour after 09:00Z."""
    assert _sm._is_canvas_newer(_cfi("2026-08-01T12:00:00+02:00"),
                                _entry("2026-08-01T09:00:00Z")) is True
    assert _sm._is_canvas_newer(_cfi("2026-08-01T12:00:00+02:00"),
                                _entry("2026-08-01T11:00:00Z")) is False


def test_garbage_timestamps_still_degrade_quietly(_sm):
    """The handler must keep doing its original job."""
    for bad in ("not a date", "", "2026-13-45T99:99:99Z"):
        assert _sm._is_canvas_newer(_cfi("2026-08-01T10:00:00Z"),
                                    _entry(bad)) in (True, False)


# ── The transcription worker's exit must be bounded ──────────────────────────

def test_worker_exit_wait_is_bounded():
    """`proc.wait()` here is reached on a `break` out of the read loop, and one
    of those breaks is stdout EOF - which means the PIPE closed, not that the
    worker exited. An unbounded wait had nothing to rescue it: the `finally`
    that kills the child only runs AFTER wait() returns, and the daily
    auto-sync runs unattended with no user to cancel it.

    This is deliberately NOT the stall watchdog that was declined for
    transcription: by this line the worker has finished producing output and
    only process teardown remains.
    """
    tree = ast.parse(_src("panopto/transcribe.py"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "transcribe_in_subprocess")
    waits = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "wait"
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "proc"]
    assert waits, "no proc.wait() found - has the worker protocol changed?"
    for call in waits:
        has_timeout = (any(k.arg == "timeout" for k in call.keywords)
                       or bool(call.args))
        assert has_timeout, (
            f"proc.wait() at line {call.lineno} is unbounded - a worker that "
            "closes stdout without exiting parks the run for ever")


def test_the_first_sidecar_handle_is_closed_if_the_second_open_fails(monkeypatch,
                                                                    tmp_path):
    """Both opens must sit INSIDE the try.

    Opened above it, a failure on the SECOND (disk full, permissions, an
    antivirus hold) left the first handle open with the try not yet entered, so
    the finally never ran. On Windows the traceback keeps the frame - and the
    handle - alive for as long as Streamlit displays it, so the partial
    `<name>.txt.part` stays locked.
    """
    import builtins
    import types as _types
    import panopto.transcribe as tr

    mp3 = tmp_path / "lecture.mp3"
    mp3.write_bytes(b"\x00" * 10)

    class _FakeModel:
        def transcribe(self, path, **kw):
            return iter([]), _types.SimpleNamespace(duration=1.0, language="da")

    monkeypatch.setattr(tr, "load_model", lambda d, device="cpu": _FakeModel())

    opened = []
    real_open = builtins.open

    def counting_open(path, *a, **k):
        p = str(path)
        if p.endswith(".srt.part"):
            raise OSError(28, "No space left on device")
        f = real_open(path, *a, **k)
        if p.endswith(".part"):
            opened.append(f)
        return f

    monkeypatch.setattr(builtins, "open", counting_open)
    with pytest.raises(OSError):
        tr.transcribe(str(mp3), "model", want_txt=True, want_srt=True)
    monkeypatch.undo()

    assert opened, "the first sidecar was never opened - test no longer exercises the path"
    assert all(f.closed for f in opened), (
        "the first sidecar handle LEAKED when the second open failed")


def test_worker_exit_grace_is_a_teardown_bound_not_a_transcription_bound():
    """A value long enough to be mistaken for a stall watchdog would
    re-litigate a decision this project made deliberately."""
    from panopto.transcribe import _EXIT_GRACE_SECONDS
    assert 1 <= _EXIT_GRACE_SECONDS <= 60


# ── A listing loop must not trust the server to end it ───────────────────────
#
# Every pagination loop in panopto/discovery.py advanced a page counter and
# exited only when the server returned a SHORT page - so termination was the
# SERVER's to honour. A tenant (or a caching proxy) that ignores the page
# parameter and re-serves page 0 loops for ever, on the Streamlit script thread
# where discovery runs, with the results list growing by a full page each time.
#
# These run on a THREAD with a join timeout, so a regression FAILS instead of
# hanging the suite for the full pytest timeout (the lesson panopto/stream.py's
# watchdog test already records).

def _runs_to_completion(fn, seconds=20):
    """(finished, result) - never blocks longer than *seconds*."""
    import threading
    box = {}

    def _go():
        try:
            box["r"] = fn()
        except BaseException as e:      # noqa: BLE001 - reported, not swallowed
            box["e"] = e

    t = threading.Thread(target=_go, daemon=True)
    t.start()
    t.join(seconds)
    return (not t.is_alive()), box


def test_api_v1_folder_listing_terminates_when_paging_is_ignored(monkeypatch):
    import panopto.discovery as d

    calls = {"n": 0}

    def never_ending(session, base, path, params=None):
        calls["n"] += 1
        return {"Results": [{"Id": f"{i:08x}-0000-0000-0000-000000000000",
                             "Name": f"S{i}"} for i in range(100)]}, 200

    monkeypatch.setattr(d, "_panopto_api_get", never_ending)
    done, box = _runs_to_completion(
        lambda: d._folder_sessions_api_v1(None, "https://x.panopto.eu", "f1"))
    assert done, ("the api/v1 folder listing never terminates against a tenant "
                  "that ignores pageNumber")
    assert "e" not in box, box.get("e")
    assert calls["n"] <= d._MAX_LIST_PAGES


def test_data_svc_folder_listing_terminates_without_a_TotalNumber(monkeypatch):
    """Its secondary bound (len(found) >= TotalNumber) only fires when the
    server sends that field, and the code itself anticipates it being absent."""
    import panopto.discovery as d

    calls = {"n": 0}

    def never_ending(session, base, method, payload):
        calls["n"] += 1
        return {"Results": [{"DeliveryID": f"{i:08x}-0000-0000-0000-000000000000",
                             "SessionName": f"S{i}"} for i in range(100)]}, ""

    monkeypatch.setattr(d, "_data_svc_post", never_ending)
    done, box = _runs_to_completion(
        lambda: d._folder_sessions_data_svc(None, "https://x.panopto.eu", "f2"))
    assert done, "the Data.svc folder listing never terminates"
    assert "e" not in box, box.get("e")
    assert calls["n"] <= d._MAX_LIST_PAGES


def test_canvas_next_link_loop_terminates_on_a_self_referencing_page(monkeypatch):
    import panopto.discovery as d

    calls = {"n": 0}

    class _Resp:
        status_code = 200
        links = {"next": {"url": "https://canvas.example/api/v1/loop"}}

        def raise_for_status(self):
            pass

        def json(self):
            return [{"id": 1}]

    def looping_get(url, **kw):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(d.requests, "get", looping_get)
    rest = d._CanvasREST("https://canvas.example", "tok")
    done, box = _runs_to_completion(
        lambda: rest.get_all("/api/v1/courses/1/modules"))
    assert done, "a next-link pointing at itself loops for ever"
    assert "e" not in box, box.get("e")
    assert calls["n"] <= d._MAX_LIST_PAGES


def test_the_page_cap_cannot_truncate_a_real_listing():
    """The cap has to be far past anything real or it becomes a correctness bug
    of its own. 100 pages x 100 rows = 10,000 sessions in ONE folder; the
    largest course folder measured here held 36."""
    import panopto.discovery as d
    assert d._MAX_LIST_PAGES >= 50


def test_the_folder_walk_keeps_its_own_bounds():
    """The outer walk was already bounded (cycle set + depth + folder count).
    The page caps are in addition to that, not a replacement for it."""
    src = _src("panopto/discovery.py")
    fn = src[src.index("def _discover_folder_sessions"):]
    fn = fn[:fn.index("\ndef ", 1)]
    assert "_MAX_DEPTH, _MAX_FOLDERS = 3, 40" in fn
    assert "seen = {root}" in fn and "if sub_id not in seen:" in fn, (
        "the cycle guard on the subfolder walk is gone")


# ── A recursive walk over SERVER data needs a bound ──────────────────────────
#
# `_build_discussion_replies_html_sync.render_entry` recursed through Canvas
# discussion replies with `depth` used ONLY for the visual indent
# (min(depth*30, 150)), never as a limit - while its sibling in the same file,
# `humanize_canvas_error._messages`, is depth-capped with the comment "an
# adversarial or merely odd payload must not be able to raise RecursionError".
# Two costs: `entry.get_replies()` is a NETWORK call, so the recursion is
# unbounded work driven by the other end; and a cyclic reply graph recursed
# until RecursionError, which the enclosing `except Exception` swallows into an
# empty string - the whole Replies section silently vanishing from the export.

class _FakeEntry:
    def __init__(self, eid, factory, counter):
        self.id = eid
        self.user_name = f"User{eid}"
        self.message = f"reply {eid}"
        self.created_at = "2026-08-01T10:00:00Z"
        self.attachments = []
        self._factory = factory
        self._counter = counter

    def get_replies(self):
        self._counter[0] += 1        # stands in for the HTTP request
        return self._factory(self)


class _FakeTopic:
    def __init__(self, roots):
        self._roots = roots

    def get_topic_entries(self):
        return self._roots


def _render(topic, seconds=20):
    from core.canvas_logic import CanvasManager
    cm = CanvasManager.__new__(CanvasManager)     # __init__ does network I/O
    done, box = _runs_to_completion(
        lambda: cm._build_discussion_replies_html_sync(topic), seconds)
    return done, box.get("r", ""), box


def test_a_deep_reply_chain_is_bounded_and_says_so():
    from core.canvas_logic import _DISCUSSION_MAX_REPLY_DEPTH
    calls = [0]
    state = {"n": 0}

    def factory(parent):
        state["n"] += 1
        if state["n"] > 500:
            return []
        return [_FakeEntry(1000 + state["n"], factory, calls)]

    done, html, box = _render(_FakeTopic([_FakeEntry(1, factory, calls)]))
    assert done, "a deep reply chain never terminated"
    assert "e" not in box, box.get("e")
    assert calls[0] <= _DISCUSSION_MAX_REPLY_DEPTH + 1, (
        f"{calls[0]} network calls for one thread - the recursion is unbounded")
    assert "maximum reply depth" in html, (
        "replies were truncated silently; the export is the user's only copy "
        "of the thread, so it must say what is missing")


def test_a_cyclic_reply_graph_terminates():
    """RecursionError here is swallowed by the outer handler into an empty
    Replies section - a silent loss, not a visible failure."""
    calls = [0]
    holder = {}

    def factory(parent):
        return [holder["e"]]         # its own child

    holder["e"] = _FakeEntry(77, factory, calls)
    done, html, box = _render(_FakeTopic([holder["e"]]))
    assert done, "a cyclic reply graph never terminated"
    assert "e" not in box, box.get("e")
    assert calls[0] <= 2, f"the cycle was walked {calls[0]} times"


def test_an_ordinary_thread_is_rendered_in_full():
    """The bound must be far past anything real."""
    calls = [0]

    def factory(parent):
        if parent.id >= 3:
            return []
        return [_FakeEntry(parent.id + 1, factory, calls)]

    done, html, box = _render(_FakeTopic([_FakeEntry(1, factory, calls)]))
    assert done and "e" not in box
    for n in (1, 2, 3):
        assert f"reply {n}" in html, f"reply {n} missing from a normal thread"
    assert "maximum reply depth" not in html, "the cap fired on a normal thread"


def test_the_reply_depth_cap_is_generous():
    from core.canvas_logic import _DISCUSSION_MAX_REPLY_DEPTH
    assert 10 <= _DISCUSSION_MAX_REPLY_DEPTH <= 200


# ── "Unreadable" is not "empty" ──────────────────────────────────────────────

def test_session_state_is_not_wiped_when_it_cannot_be_read():
    """core.health_log.session_end stamps the exit reason onto the snapshot
    that records this session's pid and child processes. Degrading an
    unreadable file to {} and writing anyway erased both, so the next launch
    had nothing to reap and the orphans leaked permanently."""
    tree = ast.parse(_src("core/health_log.py"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "session_end")
    # The broad handler around the snapshot read must bail out, not fall
    # through to the write below it.
    handlers = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)
                and isinstance(h.type, ast.Name) and h.type.id == "Exception"]
    reading = [h for h in handlers
               if any(isinstance(n, ast.Return) for n in ast.walk(h))]
    assert reading, (
        "session_end no longer returns on an unreadable snapshot - the "
        "recorded child processes will be erased")


# ── A background worker's "running" claim must always be released ────────────
#
# Both of these set a "running" state and THEN start the thread that is the only
# thing which will ever clear it. `Thread.start()` raising RuntimeError (resource
# exhaustion) therefore pinned the state for the life of the process: a progress
# bar that cannot move, and a start function whose own is-running guard refuses
# every retry. core.course_cache.fetch_courses already guards exactly this.

def test_model_download_releases_its_claim_if_the_thread_cannot_start(monkeypatch):
    import threading as _threading
    import panopto.models as models

    model_id = models.MODEL_REGISTRY[0]["id"]
    models.clear_download_state(model_id)
    monkeypatch.setattr(models, "hf_available", lambda: True)

    def refuse(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(_threading.Thread, "start", refuse)
    assert models.start_download(model_id) is False
    try:
        assert models.is_downloading(model_id) is False, (
            "the download state is pinned at 'downloading' - the card will show "
            "a progress bar that never moves and refuse every retry")
        st = models.get_download_state(model_id) or {}
        assert st.get("status") == "error" and st.get("error")
    finally:
        models.clear_download_state(model_id)


def test_model_download_worker_setup_failure_reaches_a_terminal_state(monkeypatch,
                                                                     tmp_path):
    """mkdir on a read-only volume / full disk is the realistic case: it used to
    sit ABOVE the try, so the thread died with the state stuck 'downloading'."""
    import panopto.models as models

    model_id = models.MODEL_REGISTRY[0]["id"]
    models.clear_download_state(model_id)
    models._set_state(model_id, status="downloading", cancel=False)

    class _Boom:
        def mkdir(self, **kw):
            raise OSError(30, "Read-only file system")

    monkeypatch.setattr(models, "model_dir", lambda mid: _Boom())
    monkeypatch.setattr(models, "is_installed", lambda mid: False)
    monkeypatch.setattr(models, "delete_model", lambda mid: None)
    try:
        models._download_worker(model_id, models.MODEL_REGISTRY[0])
        st = models.get_download_state(model_id) or {}
        assert st.get("status") == "error", (
            f"worker setup failure left the state at {st.get('status')!r} - "
            "the UI spins for ever and the download cannot be retried")
    finally:
        models.clear_download_state(model_id)


def test_cuda_provision_releases_its_claim_if_the_thread_cannot_start(monkeypatch):
    import threading as _threading
    from panopto import cuda_provision as cp

    monkeypatch.setattr(cp, "is_provisioned", lambda: False)
    monkeypatch.setattr(cp, "_worker_alive", lambda: False)
    monkeypatch.setattr(cp, "_purge_stale_staging", lambda: None)
    monkeypatch.setattr(cp, "removal_pending", lambda: False, raising=False)

    def refuse(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(_threading.Thread, "start", refuse)
    started = cp.start_provision()
    assert started is False
    assert cp.is_running() is False, (
        "provisioning is pinned at 'Finding' - the GPU card shows a motionless "
        "'Starting...' and every retry is refused")
    st = cp.get_state() or {}
    assert st.get("status") == "error" and st.get("final") is True


def test_fallback_token_store_is_not_replaced_when_unreadable(monkeypatch, tmp_path):
    """The DPAPI fallback store is keyed by Canvas URL, so replacing it on an
    unreadable read logs the user out of every OTHER saved Canvas.

    Driven through the REAL _save_fallback_token rather than grepping it: a
    source-shape assertion passes against a handler that catches OSError and
    then falls through to the write anyway, which is the actual bug.
    """
    import json
    import ui.auth as auth

    store = tmp_path / ".token_fallback"
    existing = {"_version": 2,
                "https://cbs.instructure.com": "AAAA",
                "https://ku.instructure.com": "BBBB"}
    store.write_text(json.dumps(existing), encoding="utf-8")

    monkeypatch.setattr(auth.sys, "platform", "win32", raising=False)
    monkeypatch.setattr(auth, "_get_fallback_path", lambda: store)

    fake_crypt = types.ModuleType("win32crypt")
    fake_crypt.CryptProtectData = lambda *a, **k: b"CCCC"
    monkeypatch.setitem(sys.modules, "win32crypt", fake_crypt)

    # A transient OSError on the READ must leave the store exactly as it was.
    real_open = io.open

    def exploding_open(path, *a, **k):
        if str(path) == str(store) and (not a or "r" in str(a[0])):
            raise OSError(13, "Permission denied")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", exploding_open)
    auth._save_fallback_token("https://dtu.instructure.com", "new-token")
    monkeypatch.undo()

    after = json.loads(store.read_text(encoding="utf-8"))
    assert after == existing, (
        "an unreadable fallback store was overwritten - every other saved "
        "Canvas account lost its token")
