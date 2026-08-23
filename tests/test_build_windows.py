"""The Windows release build must not be able to report success for a partial one.

`scripts/build_windows.py` had no test and had not been run since before the
2026-08-14 website pass. Reviewed on 2026-08-22 against the macOS workflow,
which verifies every artifact it produces, it was missing all of that:

  * ISCC missing -> a warning, then "built successfully", exit 0. No installer.
  * nothing checked that the .exe or the installer existed at all.
  * the release rename was manual - and `marketing/FINDINGS.md` records
    v2.0.1's notes naming a Windows asset that was not the one attached.
  * `main()` read `sys.argv` implicitly, so nothing could call it in-process.

The last one is why there was no test: an entry point that cannot be called
cannot be covered, and the first caller is always a test. Same lesson as
`tests/test_longpath_gate_check.py`, whose off-Windows half had never run
anywhere until the day it did.

These tests are platform-independent on purpose - they drive the DECISIONS with
injected hooks rather than performing a 90 MB build - so they run on the Mac
where this hardening was written and on the Windows box where the build actually
happens. What they deliberately do NOT cover is PyInstaller and ISCC themselves.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import scripts.build_windows as bw  # noqa: E402


# ---------------------------------------------------------------- naming

def test_the_release_asset_name_is_the_published_convention():
    assert bw.release_asset_name("2.0.2") == "Canvas_Downloader_v2.0.2_Windows.exe"


def test_the_release_asset_name_is_found_by_the_page_syncs_own_pattern():
    """A coupling that would fail SILENTLY: if the built asset's name did not
    match the pattern `scripts/sync_release_page.py` uses to locate the Windows
    download, the website would quietly keep advertising the previous release
    while a correct asset sat on the new one."""
    from scripts.sync_release_page import WIN_RE
    assert WIN_RE.search(bw.release_asset_name("2.0.2"))


def test_the_release_name_differs_from_innos_output_which_is_the_whole_point():
    """These two names are different by design - a build artifact and a
    publishing convention. The guard is that ONE function decides the second."""
    assert bw.release_asset_name("2.0.2") != "Canvas_Downloader_Setup_2.0.2.exe"


# ------------------------------------------------------- version parsing

@pytest.mark.parametrize("version,expected", [
    ("2.0.2", (2, 0, 2, 0)),
    ("2.0.2.7", (2, 0, 2, 7)),
    ("3.1", (3, 1, 0, 0)),
])
def test_version_parts(version, expected):
    assert bw._version_parts(version) == expected


def test_a_non_numeric_version_stops_the_build_instead_of_stamping_something_wrong():
    """A PE version resource cannot express '2.0.2rc1'. Previously this raised a
    bare ValueError from inside a generator expression."""
    with pytest.raises(SystemExit) as e:
        bw._version_parts("2.0.2rc1")
    assert "not a numeric" in str(e.value)


# ------------------------------------------------- the PE resource file

def test_generated_version_info_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(bw, "ROOT", tmp_path)
    out = bw.generate_version_info("2.0.2")
    src = out.read_text(encoding="utf-8")
    assert "(2, 0, 2, 0)" in src
    assert "'2.0.2'" in src
    bw.verify_version_info(out, "2.0.2")          # must not raise


def test_verify_version_info_catches_a_stale_file(tmp_path):
    """The exact drift that nearly shipped: a 2.0.1 resource inside a 2.0.2
    build, because a bare `pyinstaller` run does not regenerate this file."""
    f = tmp_path / "version_info.py"
    f.write_text("filevers=(2, 0, 1, 0),\nStringStruct('FileVersion', '2.0.1')",
                 encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        bw.verify_version_info(f, "2.0.2")
    assert "declares" in str(e.value)


def test_verify_version_info_catches_a_file_with_no_tuple_at_all(tmp_path):
    f = tmp_path / "version_info.py"
    f.write_text("# empty\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        bw.verify_version_info(f, "2.0.2")


# ------------------------------------------------------ artifact checks

def test_a_missing_exe_fails_even_though_pyinstaller_returned_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(bw, "APP_EXE", tmp_path / "nope.exe")
    with pytest.raises(SystemExit) as e:
        bw.verify_app_built()
    assert "does not" in str(e.value)


def test_a_zero_byte_exe_is_not_a_build(tmp_path, monkeypatch):
    exe = tmp_path / "Canvas Downloader.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(bw, "APP_EXE", exe)
    with pytest.raises(SystemExit) as e:
        bw.verify_app_built()
    assert "not a real executable" in str(e.value)


def test_a_real_sized_exe_passes(tmp_path, monkeypatch):
    exe = tmp_path / "Canvas Downloader.exe"
    exe.write_bytes(b"\x00" * (bw._MIN_EXE_BYTES + 1))
    monkeypatch.setattr(bw, "APP_EXE", exe)
    assert bw.verify_app_built() == exe


# --------------------------------------------------------------- main()

@pytest.fixture
def stubbed(tmp_path, monkeypatch):
    """Neutralise every step that touches the real repo or runs a real build."""
    monkeypatch.setattr(bw, "generate_version_info", lambda v: tmp_path / "version_info.py")
    monkeypatch.setattr(bw, "verify_app_built", lambda: tmp_path / "app.exe")
    monkeypatch.setattr(bw, "read_version", lambda: "2.0.2")
    monkeypatch.setattr(bw, "git_state", lambda: ("abc1234", False))
    monkeypatch.setattr(bw, "INSTALLER_DIR", tmp_path)
    return tmp_path


def test_a_missing_iscc_is_an_ERROR_not_a_successful_build(stubbed, capsys):
    """The headline defect. It used to print a warning and then
    'Done. Version X built successfully.' with exit 0 and no installer."""
    rc = bw.main([], pyinstaller=lambda: None,
                 inno=lambda v, i: pytest.fail("inno must not run"),
                 iscc_finder=lambda: None)
    assert rc == 1
    out = capsys.readouterr()
    assert "successfully" not in (out.out + out.err).lower()


def test_no_installer_skips_inno_and_succeeds(stubbed):
    rc = bw.main(["--no-installer"], pyinstaller=lambda: None,
                 inno=lambda v, i: pytest.fail("inno must not run"),
                 iscc_finder=lambda: pytest.fail("iscc must not be looked for"))
    assert rc == 0


def test_the_happy_path_publishes_the_release_named_asset(stubbed, capsys):
    """The rename trap, killed: the operator never has to remember it, and the
    last line of output names exactly one file to upload."""
    installer = stubbed / "Canvas_Downloader_Setup_2.0.2.exe"
    installer.write_bytes(b"\x00" * (bw._MIN_INSTALLER_BYTES + 1))

    rc = bw.main([], pyinstaller=lambda: None,
                 inno=lambda v, i: installer,
                 iscc_finder=lambda: "ISCC.exe")
    assert rc == 0
    asset = stubbed / "Canvas_Downloader_v2.0.2_Windows.exe"
    assert asset.is_file(), "the release-named asset was not produced"
    assert asset.read_bytes() == installer.read_bytes()
    assert installer.is_file(), "the original must survive - it is a copy"
    assert asset.name in capsys.readouterr().out


def test_a_dirty_tree_is_reported_in_the_summary(stubbed, monkeypatch, capsys):
    """Not a hard block - developing from a dirty tree is normal - but a RELEASE
    artifact built from uncommitted code is untraceable, so it must be said."""
    monkeypatch.setattr(bw, "git_state", lambda: ("abc1234", True))
    installer = stubbed / "Canvas_Downloader_Setup_2.0.2.exe"
    installer.write_bytes(b"\x00" * (bw._MIN_INSTALLER_BYTES + 1))
    bw.main([], pyinstaller=lambda: None, inno=lambda v, i: installer,
            iscc_finder=lambda: "ISCC.exe")
    assert "DIRTY" in capsys.readouterr().out


def test_main_reads_its_argv_argument_and_not_sys_argv(stubbed):
    """Under pytest sys.argv carries the runner's flags; argparse would exit 2
    on them. This is also why the script had no tests before."""
    rc = bw.main(["--no-installer"], pyinstaller=lambda: None,
                 inno=lambda v, i: None, iscc_finder=lambda: None)
    assert rc == 0


# ------------------------------------------------ the two sibling files

def test_the_iss_has_no_silent_appversion_fallback():
    """A `#define AppVersion "2.0.0"` meant any caller that forgot /DAppVersion
    built an installer declaring itself 2.0.0 - in the filename, in Add/Remove
    Programs, and in the AppId-keyed upgrade logic."""
    iss = (REPO / "Canvas_Downloader_Setup.iss").read_text(encoding="utf-8")
    body = re.sub(r"^\s*;.*$", "", iss, flags=re.M)          # strip comments
    assert not re.search(r"#define\s+AppVersion", body), (
        "Canvas_Downloader_Setup.iss defines a fallback AppVersion. It must "
        "#error instead, so a forgotten /DAppVersion cannot ship a mislabelled "
        "installer.")
    assert "#error" in body, "the #ifndef AppVersion guard must fail the compile"


def test_the_powershell_build_delegates_and_owns_no_logic():
    """It was a SECOND implementation and it was wrong in three ways at once.
    A build with two implementations is one where one of them is out of date."""
    ps1 = (REPO / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    body = re.sub(r"^\s*#.*$", "", ps1, flags=re.M)          # strip comments
    assert "build_windows.py" in body, "the wrapper must delegate to the script"
    for forbidden in ("pyinstaller", "iscc", "ISCC"):
        assert forbidden not in body, (
            f"build_windows.ps1 invokes {forbidden!r} itself - that is the "
            f"divergence that produced a 2.0.0-labelled installer for a 2.0.2 "
            f"tree. It must only delegate.")


# ------------------------------------------------- the output directory (2026-08-23)

def test_pyinstaller_is_told_to_overwrite_the_output_directory():
    """`--clean` and `--noconfirm` are different knobs, and only one of them
    touches `dist/`.

    MEASURED 2026-08-23, on the first real run of this script on Windows: with
    a `dist/` left by an earlier build, PyInstaller reached COLLECT and refused
    - "The output directory ... is not empty. Please remove all its contents or
    use the -y option" - and exited 1, about nine minutes in. `--clean` empties
    the BUILD cache and says nothing about the output tree. A fresh CI checkout
    has no `dist/`, so this passes there and fails only on the machine where
    releases are actually built.
    """
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(bw.run_pyinstaller))
    tree = ast.parse(src)
    literals = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "--noconfirm" in literals, (
        "run_pyinstaller does not pass --noconfirm, so the build fails at "
        "COLLECT on any machine that has built before")
    assert "--clean" in literals, "--clean must survive alongside it"


# ------------------------------------------------------ finding ISCC (2026-08-23)

def test_iscc_discovery_is_not_pinned_to_one_version_or_one_root():
    r"""The old form was `which('iscc') or C:\Program Files (x86)\Inno Setup 6`.

    MEASURED 2026-08-23: a working Inno Setup 7.1.0 x64, installed per-user to
    %LOCALAPPDATA%\Programs\Inno Setup 7, matched none of those - it is a
    different VERSION in a different ROOT and it puts nothing on PATH - so
    find_iscc() returned None and the build exited 1 claiming the compiler was
    not found while it sat there working.
    """
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(bw._iscc_candidates))
    assert "Inno Setup*" in src or "Inno Setup" in src
    tree = ast.parse(src)
    assert any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "glob"
               for n in ast.walk(tree)), (
        "candidate discovery must GLOB for versions rather than name one")
    roots = " ".join(bw._ISCC_ROOTS).lower()
    assert "program files (x86)" in roots and "program files" in roots
    assert "programs" in roots, (
        r"the per-user install root (%LOCALAPPDATA%\Programs) is not searched")


def test_iscc_candidates_prefer_the_newest_version(tmp_path, monkeypatch):
    """A machine with 6 and 7 installed must build with 7."""
    for name in ("Inno Setup 6", "Inno Setup 7", "Inno Setup 15"):
        d = tmp_path / name
        d.mkdir()
        (d / "ISCC.exe").write_bytes(b"MZ")
    monkeypatch.setattr(bw, "_ISCC_ROOTS", (str(tmp_path),))
    found = bw._iscc_candidates()
    assert [p.parent.name for p in found] == [
        "Inno Setup 15", "Inno Setup 7", "Inno Setup 6"], (
        "candidates must be ordered newest-version-first, numerically")


def test_iscc_candidates_ignore_a_directory_with_no_compiler(tmp_path, monkeypatch):
    (tmp_path / "Inno Setup 6").mkdir()          # no ISCC.exe inside
    monkeypatch.setattr(bw, "_ISCC_ROOTS", (str(tmp_path),))
    assert bw._iscc_candidates() == []


def test_iscc_candidates_survive_an_unreadable_root(tmp_path, monkeypatch):
    """Discovery runs before anything is built; a bad root must not raise."""
    monkeypatch.setattr(bw, "_ISCC_ROOTS", (str(tmp_path / "nope"), "", None))
    assert bw._iscc_candidates() == []


def test_path_still_wins_over_a_discovered_install(tmp_path, monkeypatch):
    """An operator pinning a specific compiler on PATH must keep control."""
    d = tmp_path / "Inno Setup 7"
    d.mkdir()
    (d / "ISCC.exe").write_bytes(b"MZ")
    monkeypatch.setattr(bw, "_ISCC_ROOTS", (str(tmp_path),))
    monkeypatch.setattr(bw.shutil, "which",
                        lambda name: r"C:\pinned\iscc.exe" if name == "iscc" else None)
    assert bw.find_iscc() == r"C:\pinned\iscc.exe"


def test_find_iscc_still_returns_none_when_nothing_is_installed(tmp_path, monkeypatch):
    """The missing-compiler path is a real ERROR path and must stay reachable."""
    monkeypatch.setattr(bw, "_ISCC_ROOTS", (str(tmp_path),))
    monkeypatch.setattr(bw.shutil, "which", lambda name: None)
    assert bw.find_iscc() is None
