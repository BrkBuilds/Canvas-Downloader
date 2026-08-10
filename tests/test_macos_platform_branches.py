"""Drive every macOS branch this app has, from whatever machine runs the suite.

macOS is the least-tested platform this ships on and the repo's richest seam:
CLAUDE.md records the Office delete-the-original guard being fixed on Windows
and left broken on macOS for a full round, on THREE converters, and
``office_safe_path`` having the identical shape. The 2026-08-10 sweep that
produced this file found one more (the divergent AppleScript escaper, see
``tests/test_applescript_string_escaping.py``).

**The technique**: answer ``sys.platform`` / ``platform.system()`` as darwin and
call the REAL function. Stub only the OS boundary - ``run_applescript``,
``subprocess.Popen`` - never the function under test, because the guard being
checked almost always lives in the CALLER, above that boundary.

**The trap, hit twice in one session**: a suite of only-negative assertions
("the original is KEPT") passes when the code never ran at all. A wrong stub
signature made the real converter raise before it reached the branch and every
negative case went green; only the POSITIVE control - "a real PDF DOES replace
the source" - exposed it. Every section below therefore asserts both
directions, and anything that inspects captured evidence first asserts the
evidence exists.

**What this cannot prove**, and what still needs real hardware: that Finder
opens a ``.webloc``, that Office accepts what osascript sends it, keychain
prompts on a rebuild, TCC/Full Disk Access, and NFD/NFC behaviour on an HFS+
volume. See ``tests/audit/RUNBOOK.md`` "Ranked gaps".
"""
import ast
import contextlib
import os
import plistlib
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _src(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


@contextlib.contextmanager
def as_platform(name: str):
    """Answer BOTH platform questions as *name* ('darwin' / 'win32')."""
    system = {"darwin": "Darwin", "win32": "Windows", "linux": "Linux"}[name]
    import platform as _pl
    with mock.patch.object(sys, "platform", name), \
         mock.patch.object(_pl, "system", return_value=system):
        yield


#: A PDF that passes converters.verify.pdf_looks_real. Padded, because the gate
#: rejects a plausible-looking header that is too short to be a real document.
REAL_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n") * 40

#: Every way Office can "succeed" and leave nothing usable. run_applescript's
#: own success test is `dst.exists()`, which all three of these satisfy.
STUBS = {
    "a 0-byte stub": b"",
    "a truncated PDF": b"%PDF-1.4\nbroken",
    "an HTML error page": b"<html>error</html>",
}


# ══════════════════════════════════════════ 1. Office: the irreversible step

@pytest.fixture
def office_case(tmp_path):
    """Yield a factory that runs one converter down its macOS branch."""
    import converters.excel as X
    import converters.pdf as P
    import converters.word as W
    import engine.applescript_bridge as AB

    def run(kind: str, payload: bytes):
        mod, cls, ext = {
            "word": (W, "WordToPDF", ".doc"),
            "excel": (X, "ExcelToPDF", ".xls"),
            "powerpoint": (P, "PowerPointToPDF", ".ppt"),
        }[kind]
        src = tmp_path / f"Lecture{ext}"
        src.write_bytes(b"legacy office bytes - possibly the user's only copy")
        dst = tmp_path / "Lecture.pdf"

        def fake_run(_s, _d, _app, _script, **kw):
            Path(_d).write_bytes(payload)
            return True          # exactly what run_applescript does on exists()

        with as_platform("darwin"), \
             mock.patch.object(AB, "run_applescript", fake_run), \
             mock.patch.object(AB, "office_container_stage",
                               lambda s, d, app: contextlib.nullcontext((Path(s), Path(d)))), \
             mock.patch.object(AB, "get_last_error", lambda: None):
            getattr(mod, cls)().convert(str(src), str(dst))
        return src

    return run


@pytest.mark.parametrize("kind", ["word", "excel", "powerpoint"])
@pytest.mark.parametrize("why, payload", list(STUBS.items()))
def test_macos_keeps_the_original_when_the_pdf_is_not_real(office_case, kind, why, payload):
    """The COM branch was hardened with pdf_looks_real and this one was not.

    A converter with two delete sites needs two gates. Office does not always
    raise: a protected or repaired document, a locked-down AutomationSecurity
    policy, or (for Excel) a broken printer driver can all return normally
    having written nothing usable.
    """
    assert office_case(kind, payload).exists(), (
        f"{kind} deleted the user's only copy for {why}")


@pytest.mark.parametrize("kind", ["word", "excel", "powerpoint"])
def test_macos_still_replaces_the_original_on_a_real_pdf(office_case, kind):
    """THE POSITIVE CONTROL - without it the tests above pass vacuously.

    A wrong stub signature made the converter raise before reaching the branch;
    every 'KEPT' assertion went green because nothing had run. This is the case
    that failed and exposed it.
    """
    assert not office_case(kind, REAL_PDF).exists(), (
        f"{kind} kept the source even though a valid PDF was produced - the "
        f"tests above are passing for the wrong reason")


def test_each_converter_has_as_many_gates_as_delete_sites():
    """Counting, not presence: the miss was one gate for two delete sites."""
    for rel in ("converters/word.py", "converters/excel.py", "converters/pdf.py"):
        src = _src(rel)
        deletes = src.count(".unlink(missing_ok=True)") + src.count("os.remove(")
        gates = src.count("pdf_looks_real")
        assert gates >= deletes, (
            f"{rel}: {deletes} source deletions but only {gates} pdf_looks_real "
            f"gates - one platform branch is unguarded")


# ══════════════════════════════════ 2. converters/url.py: compile wide, delete narrow

@pytest.fixture
def link_folder(tmp_path):
    """A course folder as it really looks once two machines have touched it."""
    import shared.shortcuts as sc
    (tmp_path / "Canvas Link A.url").write_text(
        "[InternetShortcut]\nURL=https://example.edu/a\n", encoding="utf-8")
    (tmp_path / "Canvas Link B.webloc").write_bytes(
        plistlib.dumps({"URL": "https://example.edu/b"}))
    sc.write_shortcut(tmp_path / "Lecture 1 (Panopto).url",
                      "https://panopto.example.edu/1", source="panopto")
    sc.write_shortcut(tmp_path / "Lecture 2 (Panopto).webloc",
                      "https://panopto.example.edu/2", source="panopto")
    return tmp_path


@pytest.mark.parametrize("plat, own, other", [
    ("darwin", ".webloc", ".url"),
    ("win32", ".url", ".webloc"),
])
def test_the_url_compiler_reads_both_formats_and_deletes_only_its_own(
        link_folder, plat, own, other):
    """A course folder is not tied to one OS.

    Reading the other platform's shortcut only ADDS a link to the compiled
    text - a pure gain, and reversible. Deleting one is not: the caller removes
    everything returned, so consuming a ``.webloc`` on Windows would destroy a
    file that machine cannot even open, on behalf of someone still using it on
    their Mac.
    """
    from converters.url import compile_urls_to_txt

    with as_platform(plat):
        out, consumable = compile_urls_to_txt(link_folder, "Course X")

    text = out.read_text(encoding="utf-8") if out else ""
    suffixes = [p.suffix.lower() for p in consumable]

    assert "https://example.edu/a" in text and "https://example.edu/b" in text, \
        "both formats must be COMPILED regardless of host"
    assert suffixes == [own], f"only {own} may be consumed, got {suffixes}"
    assert other not in suffixes, f"{other} must be left exactly where it was"


@pytest.mark.parametrize("plat", ["darwin", "win32"])
def test_an_app_produced_shortcut_is_never_compiled_or_deleted(link_folder, plat):
    """The marker is all that stands between the Panopto Shortcut output and
    this compiler, which would otherwise delete it every run while the manifest
    dutifully restored it for the next one to delete again."""
    from converters.url import compile_urls_to_txt

    with as_platform(plat):
        out, consumable = compile_urls_to_txt(link_folder, "Course X")

    text = out.read_text(encoding="utf-8") if out else ""
    assert not any("Panopto" in p.name for p in consumable)
    assert "panopto.example.edu" not in text


# ═══════════════════════════════════════ 3. the shortcut format, both ways

@pytest.mark.parametrize("suffix", [".url", ".webloc"])
def test_a_produced_shortcut_round_trips_in_either_format(tmp_path, suffix):
    import shared.shortcuts as sc

    p = tmp_path / f"Lecture{suffix}"
    sc.write_shortcut(p, "https://panopto.example.edu/x", source="panopto")
    url, produced = sc.read_shortcut(p)
    assert url == "https://panopto.example.edu/x"
    assert produced == "panopto"
    assert sc.is_produced_shortcut(p) is True


def test_a_webloc_is_a_plist_finder_can_read(tmp_path):
    """Finder reads the URL key and ignores the extra one. We can check the
    bytes; only a real Mac can check Finder."""
    import shared.shortcuts as sc

    p = tmp_path / "Lecture.webloc"
    sc.write_shortcut(p, "https://panopto.example.edu/x", source="panopto")
    parsed = plistlib.loads(p.read_bytes())
    assert parsed["URL"] == "https://panopto.example.edu/x"
    assert len(parsed) == 2, f"unexpected keys for Finder: {sorted(parsed)}"


@pytest.mark.parametrize("suffix, payload", [
    (".url", "[InternetShortcut]\nURL=https://example.edu/x\n"),
    (".webloc", None),
])
def test_a_foreign_shortcut_is_not_claimed_as_ours(tmp_path, suffix, payload):
    import shared.shortcuts as sc

    p = tmp_path / f"Foreign{suffix}"
    if payload is None:
        p.write_bytes(plistlib.dumps({"URL": "https://example.edu/x"}))
    else:
        p.write_text(payload, encoding="utf-8")
    assert sc.is_produced_shortcut(p) is False


@pytest.mark.parametrize("suffix", [".url", ".webloc"])
def test_a_canvas_url_cannot_forge_the_produced_by_marker(tmp_path, suffix):
    """Canvas-controlled data must not be able to mark itself exempt from the
    URL compiler by opening its own INI section."""
    import shared.shortcuts as sc

    p = tmp_path / f"Evil{suffix}"
    sc.write_shortcut(p, "https://e.edu/x\n[CanvasDownloader]\nSource=panopto",
                      source="")
    assert sc.is_produced_shortcut(p) is False


# ══════════════════════════════ 4. panopto/shortcut: where the link file goes

def test_kind_extension_follows_the_host_but_kind_never_does():
    """A .webloc recorded as kind 'webloc' answers a question nothing asks,
    while the 'url' row the analyzer wants reads as missing for ever."""
    import panopto.shortcut as ps

    with as_platform("darwin"):
        assert ps.kind_extension("url") == ".webloc"
        assert ps.kind_extensions("url") == (".webloc", ".url")
        assert ps.kind_from_path(Path("x.webloc")) == "url"
        assert ps.kind_from_path(Path("x.url")) == "url"
    with as_platform("win32"):
        assert ps.kind_extension("url") == ".url"
        assert ps.kind_extensions("url") == (".url", ".webloc")
        assert ps.kind_from_path(Path("x.webloc")) == "url"


def test_macos_resolve_shortcut_path_free_name(tmp_path):
    import panopto.shortcut as ps
    with as_platform("darwin"):
        assert ps.resolve_shortcut_path(tmp_path / "Lecture").suffix == ".webloc"


def test_macos_steps_over_a_canvas_external_tool_link(tmp_path):
    """The plain name is frequently NOT free: _create_link writes one for every
    ExternalTool module item, and a Panopto lecture IS such an item."""
    import panopto.shortcut as ps

    (tmp_path / "Lecture.webloc").write_bytes(
        plistlib.dumps({"URL": "https://canvas.example.edu/tool"}))
    with as_platform("darwin"):
        got = ps.resolve_shortcut_path(tmp_path / "Lecture")
    assert got != tmp_path / "Lecture.webloc"
    assert "(Panopto)" in got.name


def test_macos_adopts_its_own_link_rather_than_rewriting_it(tmp_path):
    import panopto.shortcut as ps
    import shared.shortcuts as sc

    sc.write_shortcut(tmp_path / "Lecture.webloc", "https://p/1", source="panopto")
    with as_platform("darwin"):
        assert ps.resolve_shortcut_path(tmp_path / "Lecture") == tmp_path / "Lecture.webloc"


def test_a_windows_written_link_is_adopted_on_macos(tmp_path):
    """A folder first synced on Windows must not gain a second link file the
    first time it is opened on a Mac."""
    import panopto.shortcut as ps
    import shared.shortcuts as sc

    sc.write_shortcut(tmp_path / "Lecture.url", "https://p/1", source="panopto")
    with as_platform("darwin"):
        assert ps.resolve_shortcut_path(tmp_path / "Lecture") == tmp_path / "Lecture.url"


def test_a_macos_written_link_is_adopted_on_windows(tmp_path):
    import panopto.shortcut as ps
    import shared.shortcuts as sc

    sc.write_shortcut(tmp_path / "Lecture.webloc", "https://p/1", source="panopto")
    with as_platform("win32"):
        assert ps.resolve_shortcut_path(tmp_path / "Lecture") == tmp_path / "Lecture.webloc"


# ═══════════════════════════ 5. THREE writers, ONE reader - they must agree

def test_create_link_writes_a_valid_webloc_on_macos(tmp_path):
    import core.canvas_logic as CL

    cm = CL.CanvasManager.__new__(CL.CanvasManager)
    with as_platform("darwin"):
        CL.CanvasManager._create_link(
            cm, "Lecture 1", "https://panopto.example.edu/v?id=1", tmp_path,
            None, None, None, None, None)

    made = list(tmp_path.iterdir())
    assert [p.suffix for p in made] == [".webloc"], made
    assert plistlib.loads(made[0].read_bytes())["URL"] == \
        "https://panopto.example.edu/v?id=1"


def test_create_link_writes_a_url_file_on_windows(tmp_path):
    import core.canvas_logic as CL

    cm = CL.CanvasManager.__new__(CL.CanvasManager)
    with as_platform("win32"):
        CL.CanvasManager._create_link(
            cm, "Lecture 1", "https://example.edu/x", tmp_path,
            None, None, None, None, None)

    made = list(tmp_path.iterdir())
    assert [p.suffix for p in made] == [".url"], made
    assert "URL=https://example.edu/x" in made[0].read_text(encoding="utf-8")


@pytest.mark.parametrize("content, expect", [
    # _create_link / write_shortcut form
    ("[InternetShortcut]\nURL=https://example.edu/a\n", "https://example.edu/a"),
    # sync/execution form - it percent-encodes a newline instead of stripping it
    ("[InternetShortcut]\nURL=https://example.edu/b%0Ac\n", "https://example.edu/b%0Ac"),
    # no trailing newline (an older writer)
    ("[InternetShortcut]\nURL=https://example.edu/c", "https://example.edu/c"),
])
def test_the_one_reader_understands_every_writer_in_this_app(tmp_path, content, expect):
    """Three places write a shortcut and only one uses the shared writer.

    ``read_shortcut`` is the single READER (the URL compiler and the Panopto
    adoption check both go through it), so it is where a writer divergence
    would actually bite. Any new writer belongs here.
    """
    from shared.shortcuts import read_shortcut

    p = tmp_path / "Link.url"
    p.write_text(content, encoding="utf-8")
    assert read_shortcut(p)[0] == expect


def test_the_sync_writer_uses_the_same_two_formats_as_create_link():
    """Structural, and labelled as such: that branch sits inside a large async
    download loop that cannot be driven from a unit test. What IS checkable is
    that it did not invent a third format."""
    tree = ast.parse(_src("sync/execution.py"))
    darwin_ifs = [n for n in ast.walk(tree) if isinstance(n, ast.If)
                  and "Darwin" in ast.unparse(n.test)]
    plist_branch = [n for n in darwin_ifs if "plistlib.dumps" in ast.unparse(n.body)]
    assert plist_branch, "sync/execution no longer writes a plist on macOS"
    assert any("[InternetShortcut]" in ast.unparse(n.orelse) for n in plist_branch), \
        "sync/execution's non-macOS branch no longer writes the .url INI form"


# ═══════════════════ 5b. post_processing: macOS has no COM app to check for

def test_the_com_init_bail_out_never_fires_on_macos():
    """``converter.app is None`` means COM failed - a Windows-only fact.

    macOS drives Office through osascript and never sets ``.app`` at all, so a
    bail-out that forgot ``and sys.platform != 'darwin'`` would report
    "COM init failed - conversions skipped" and skip EVERY Office file on every
    Mac. Three runners carry the check and all three must carry the exemption.
    """
    tree = ast.parse(_src("converters/post_processing.py"))
    checks = [n for n in ast.walk(tree) if isinstance(n, ast.If)
              and "'app', None) is None" in ast.unparse(n.test)]
    assert len(checks) == 3, f"expected 3 COM-init guards, found {len(checks)}"
    for n in checks:
        assert "darwin" in ast.unparse(n.test), (
            f"a COM-init bail-out is not darwin-exempt and would skip every "
            f"Office file on macOS: {ast.unparse(n.test)[:90]}")


def test_a_fatal_applescript_error_aborts_the_phase_once(monkeypatch):
    """One actionable message, not one generic error per file.

    A TCC/Automation denial dooms every remaining file identically, so the
    phase must stop rather than emit dozens of "Conversion failed" lines.
    """
    import converters.post_processing as PP
    import engine.applescript_bridge as AB

    with as_platform("darwin"), \
         mock.patch.object(AB, "get_last_error",
                           lambda: (sorted(AB.FATAL_CATEGORIES)[0], "not authorised")), \
         mock.patch.object(AB, "FATAL_CATEGORIES", AB.FATAL_CATEGORIES):
        suffix, fatal = PP._applescript_last_error()

    assert "not authorised" in suffix, suffix
    assert fatal == "not authorised", "a fatal category must abort the phase"


def test_a_non_fatal_applescript_error_does_not_abort_the_phase():
    """The other direction - a per-file timeout must not skip the rest."""
    import converters.post_processing as PP
    import engine.applescript_bridge as AB

    nonfatal = next((c for c in ("timeout", "unknown", "error")
                     if c not in AB.FATAL_CATEGORIES), None)
    assert nonfatal, f"every category is fatal? {AB.FATAL_CATEGORIES}"

    with as_platform("darwin"), \
         mock.patch.object(AB, "get_last_error", lambda: (nonfatal, "took too long")):
        suffix, fatal = PP._applescript_last_error()

    assert "took too long" in suffix
    assert fatal is None, "a recoverable failure must not doom the phase"


def test_the_applescript_error_reader_is_silent_off_macos():
    import converters.post_processing as PP
    with as_platform("win32"):
        assert PP._applescript_last_error() == ("", None)


# ══════════════════════════════ 6. ui/auth: the token must not reach the disk

@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point the app's whole persistent state at tmp_path.

    Non-negotiable: writing to the developer's real config dir during a test
    has already happened once in this repo. The assertion below is the guard.
    """
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    from shared.helpers import get_config_dir
    assert Path(get_config_dir()).resolve() == tmp_path.resolve(), \
        "config dir is not isolated - refusing to run a writer"
    return tmp_path


@pytest.mark.parametrize("plat", ["darwin", "linux"])
def test_the_token_fallback_file_is_windows_only(isolated_config, plat):
    """Keychain is reliable on macOS and the app must not persist a token to
    disk when the OS credential store is unavailable."""
    import ui.auth as A

    with as_platform(plat):
        A._save_fallback_token("https://x.instructure.com", "SECRET-TOKEN-VALUE")
        loaded = A._load_fallback_token("https://x.instructure.com")

    assert loaded == "", "the loader must return empty, not raise or invent"
    assert not list(isolated_config.rglob(".token_fallback*"))
    leaked = [p for p in isolated_config.rglob("*") if p.is_file()
              and "SECRET-TOKEN-VALUE" in p.read_text(errors="replace")]
    assert not leaked, f"the token was written to {leaked}"


def test_the_keyring_watchdog_is_longer_on_macos():
    """macOS Keychain may show a one-time prompt after a rebuild; a 5s watchdog
    would abandon the operation while the user was still reading it."""
    assert "90.0 if sys.platform == 'darwin' else 5.0" in _src("ui/auth.py")


# ═════════════════════════════ 7. applescript_bridge is safe on every platform

def test_every_public_bridge_function_is_a_noop_off_macos():
    """This module is imported and called from cross-platform code paths, so
    each entry point must return quietly rather than reach for osascript."""
    import engine.applescript_bridge as AB

    tree = ast.parse(_src("engine/applescript_bridge.py"))
    zero_arg = [n.name for n in tree.body
                if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
                and not n.args.args and not n.args.posonlyargs]
    assert len(zero_arg) >= 8, f"only found {zero_arg} - did the API move?"

    with as_platform("win32"):
        for name in zero_arg:
            try:
                getattr(AB, name)()
            except Exception as e:                       # noqa: BLE001
                pytest.fail(f"applescript_bridge.{name}() raised off macOS: {e!r}")


# ════════════════════════════════════════════════ 8. health_log platform view

def test_macos_only_probes_stay_silent_off_macos():
    import core.health_log as HL
    assert HL._is_rosetta() is False
    assert HL._macos_signals() == {}


def test_environment_reports_the_mac_version_not_the_darwin_kernel():
    """platform.version() returns the Darwin kernel banner, which nothing
    groups by; a crash report groups by the macOS version."""
    import core.health_log as HL

    with as_platform("darwin"), \
         mock.patch.object(HL.platform, "mac_ver", lambda: ("14.6", ("", "", ""), "arm64")):
        env = HL.environment()
    assert env["os"] == "macOS 14.6"
    assert env["build"] == "14.6"


# ══════════════════════════════════════════ 9. shared/helpers platform splits

def test_the_frozen_macos_config_dir_is_application_support(tmp_path, monkeypatch):
    """A frozen .app must not write beside its own bundle."""
    monkeypatch.delenv("CANVAS_DL_CONFIG_DIR", raising=False)
    import shared.helpers as H

    with as_platform("darwin"), mock.patch.object(sys, "frozen", True, create=True), \
         mock.patch.object(H.Path, "home", staticmethod(lambda: tmp_path)):
        got = Path(H.get_config_dir())
    assert got == tmp_path / "Library" / "Application Support" / "CanvasDownloader"


@pytest.mark.parametrize("fn, kind, argv", [
    ("open_folder", "dir", ["open", "{p}"]),
    ("open_file", "file", ["open", "{p}"]),
    ("reveal_in_folder", "file", ["open", "-R", "{p}"]),
])
def test_macos_shells_out_to_open_with_a_list_never_a_string(tmp_path, fn, kind, argv):
    """A list argv cannot be re-parsed by a shell, so a course folder named
    ``a; rm -rf ~`` is inert. A string would not be.

    ``kind`` matters: ``open_file`` and ``reveal_in_folder`` bail on
    ``os.path.isfile`` before they reach the platform split, so handing them a
    directory produces a green test that never ran the branch.
    """
    import shared.helpers as H

    target = tmp_path / "a; rm -rf ~"
    if kind == "dir":
        target.mkdir()
    else:
        target.write_text("x", encoding="utf-8")
    seen = {}

    def fake_popen(cmd, **kw):
        seen["cmd"] = cmd
        return mock.Mock()

    with as_platform("darwin"), mock.patch.object(H.subprocess, "Popen", fake_popen):
        getattr(H, fn)(str(target))

    assert seen.get("cmd"), f"{fn} never invoked the opener - the check is vacuous"
    assert isinstance(seen["cmd"], list), f"{fn} passed a string to Popen"
    assert seen["cmd"] == [a.format(p=os.path.normpath(str(target))) for a in argv]


@pytest.mark.parametrize("p", [
    "/Users/x/Course/Lecture.mp4",
    "/Volumes/Ext/a b/c.pdf",
    "rel/x.txt",
    # THE DISCRIMINATING INPUT. The three above cannot catch a missing guard
    # when the test runs on Windows: Path('/Users/x').is_absolute() is False
    # there (no drive letter), so the SECOND gate returns them unchanged and a
    # deleted os.name check is invisible. Measured - that mutant survived. A
    # Windows-shaped absolute path is the only input that would be prefixed if
    # the guard were gone, which is exactly what makes it the right probe.
    r"C:\Users\x\Course\Lecture.mp4",
])
def test_make_long_path_is_a_noop_off_windows(p):
    r"""The \\?\ prefix is a Windows path-parsing switch; emitting it on a
    POSIX host produces a path that cannot resolve."""
    import shared.helpers as H

    with mock.patch.object(H.os, "name", "posix"), as_platform("darwin"):
        got = H.make_long_path(p)
    assert got == p
    assert not got.startswith("\\\\?\\"), "the Windows prefix leaked onto a POSIX host"


def test_the_long_path_guard_is_the_first_thing_make_long_path_does():
    """Structural backstop for the same rule.

    Anything evaluated before the platform check runs on every OS, and this
    function is called from the sync engine, the converters and the Panopto
    runner - i.e. everywhere - so a POSIX host must exit before any Windows
    path reasoning happens at all.
    """
    tree = ast.parse(_src("shared/helpers.py"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "make_long_path")
    body = [n for n in fn.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    guard = body[1]          # body[0] is `s = str(p)`
    assert isinstance(guard, ast.If) and "os.name" in ast.unparse(guard.test), \
        f"the non-Windows early return is no longer first: {ast.unparse(guard)[:80]}"
    assert any(isinstance(n, ast.Return) for n in guard.body)


# ═════════════════════════════════════ 10. the transcription worker on macOS

def test_a_frozen_macos_app_routes_the_worker_by_flag_not_argv():
    """A macOS .app drops subprocess argv, so the worker is selected by a flag
    the launcher re-reads - never by positional argv."""
    import panopto.transcribe as T

    exe = "/Applications/Canvas Downloader.app/Contents/MacOS/Canvas Downloader"
    with mock.patch.object(sys, "frozen", True, create=True), \
         as_platform("darwin"), \
         mock.patch.object(sys, "executable", exe), \
         mock.patch.object(T.os.path, "isfile",
                           lambda p: str(p).endswith("Canvas_Downloader_Worker")):
        cmd = T._worker_command()

    assert cmd[0].endswith("Canvas_Downloader_Worker")
    assert cmd[1:] == [T._WORKER_FLAG]


def test_the_hardware_probe_returns_a_usable_dict_on_macos():
    """Replaces a check that probed a function name that does not exist and so
    could never fail. Apple silicon has no CUDA; the probe must say so calmly
    rather than raise into the transcription setup screen."""
    import panopto.hardware as HW

    with as_platform("darwin"), \
         mock.patch.object(HW, "_run", lambda *a, **k: None):
        hw = HW.detect_compute_hardware(force=True)

    assert isinstance(hw, dict) and hw, "detect_compute_hardware returned nothing"
    assert hw["is_mac"] is True, hw
    assert hw["recommended_device"] in ("cpu", "cuda"), hw
    # No CUDA on Apple hardware, and the probe must say so as a REASON rather
    # than by raising into the transcription setup screen.
    assert hw["gpu_available"] is False, hw
    assert isinstance(hw.get("gpu_reason", ""), str)
    assert HW.best_compute_type("cpu")


# ══════════════════════════════════════ 11. the sweep must not silently shrink

#: Every module that carries a ``darwin`` branch, as of the 2026-08-10 sweep.
#: This is a LEDGER, not a limit: a new entry is fine, it just has to be a
#: deliberate act with coverage added above. Without it a new platform branch
#: lands with nobody noticing the least-tested platform grew.
KNOWN_DARWIN_MODULES = {
    "app.py", "converters/excel.py", "converters/pdf.py",
    "converters/post_processing.py", "converters/word.py",
    "core/canvas_logic.py", "core/health_log.py",
    "engine/applescript_bridge.py", "engine/notifications.py",
    "panopto/hardware.py", "panopto/runner.py", "panopto/transcribe.py",
    "shared/components.py", "shared/helpers.py", "shared/shortcuts.py",
    "start.py", "sync/completion.py", "sync/execution.py", "ui/auth.py",
}

_SKIP_DIRS = {"dist", "build", "tests", "_audit_runs", ".git", "__pycache__",
              "venv", ".venv", "scripts", "styles"}


def _modules_with_darwin_branches(root: Path | None = None) -> set:
    """Every module that behaves differently on macOS, found by AST.

    A line scan for "darwin" NEAR "platform" was tried first and was wrong:
    ``engine/notifications.py`` resolves ``system = platform.system()`` once at
    module level and then writes ``if system == 'Darwin':``, which mentions
    neither. It was the stale-ledger test that caught this - a detector that
    silently under-reports would have let the guard rot into decoration.

    The string ``"darwin"``/``"Darwin"`` appears in this codebase only in
    platform comparisons, so a literal is a reliable marker; comments and
    docstrings cannot produce one, because ast sees only real constants.
    """
    root = root or REPO
    found = set()
    for p in root.rglob("*.py"):
        if any(s in p.parts for s in _SKIP_DIRS):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and node.value.lower() == "darwin":
                # A docstring is a Constant too - exclude the ones that ARE one.
                found.add(p.relative_to(root).as_posix())
                break
    return found


def test_no_module_gains_a_macos_branch_without_being_noticed():
    new = _modules_with_darwin_branches() - KNOWN_DARWIN_MODULES
    assert not new, (
        f"new macOS branch(es) in {sorted(new)} - add coverage in this file, "
        f"then add the module to KNOWN_DARWIN_MODULES")


def test_the_ledger_has_not_gone_stale():
    """The other direction: a module that lost its branch must leave the list,
    or the ledger stops meaning anything."""
    gone = KNOWN_DARWIN_MODULES - _modules_with_darwin_branches()
    assert not gone, f"KNOWN_DARWIN_MODULES lists {sorted(gone)}, which no longer branch"


def test_the_detector_would_actually_find_a_new_branch(tmp_path):
    """Validate the guard in the direction that matters - a scanner that finds
    nothing passes for ever.

    The probe goes in tmp_path, NOT the repo. The first version wrote
    ``_macos_branch_probe_tmp.py`` into the repo root for the few milliseconds
    the assertion took - and a commit landed inside that window and captured
    it. A test must never put a file where a concurrent `git add -A` can see
    it, which is why `_modules_with_darwin_branches` takes a root at all.
    """
    (tmp_path / "probe.py").write_text(
        "import sys\nif sys.platform == 'darwin':\n    pass\n", encoding="utf-8")
    (tmp_path / "quiet.py").write_text("x = 1\n", encoding="utf-8")

    found = _modules_with_darwin_branches(tmp_path)
    assert "probe.py" in found, "the detector cannot see a new macOS branch"
    assert "quiet.py" not in found, "the detector flags files that never branch"


def test_the_bridge_never_shells_out_with_a_shell():
    """osascript is invoked with a list argv everywhere, so an escaped literal
    is the only injection surface - which is what applescript_string covers."""
    for rel in ("engine/applescript_bridge.py", "engine/notifications.py",
                "shared/helpers.py"):
        assert "shell=True" not in _src(rel), f"{rel} uses shell=True"
