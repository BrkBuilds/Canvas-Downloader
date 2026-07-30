"""Tests for ``scripts/build_excludes.py`` - the PyInstaller trimming policy.

Why this file exists
--------------------
This module decides what does NOT go into the shipped application. Every
failure mode is a *release* failure, discovered by a user rather than by a
developer, and the feedback loop is a ten-minute build plus an install:

* exclude one module too many and the packaged app raises ``ImportError`` on a
  path the dev machine never takes, because on the dev machine the module is
  still importable from site-packages;
* exclude too little and the installer quietly grows back the 136 MB this
  policy exists to remove.

Nothing here can be caught by running the app from source. That is precisely
why it needs tests: ``streamlit run app.py`` exercises none of it.

THE trap
--------
The ``huggingface_hub`` dependency chain reaches ``google.auth``, which makes
the whole ``google`` namespace look dead. It is not - **Streamlit imports
``google.protobuf`` for every ``ForwardMsg`` it sends**, which is every single
UI update. Excluding bare ``google`` bricks the app completely, and the module
docstring says so in capitals. ``test_the_google_namespace_is_never_excluded``
is the guard, and it is the most important assertion in this file.
"""

from __future__ import annotations

import importlib.util
import pkgutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import build_excludes as BE  # noqa: E402


PLATFORMS = ("windows", "macos")


# ═══════════════════════════════════════════════════════════════════════════
# The trap
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("platform", PLATFORMS)
def test_the_google_namespace_is_never_excluded(platform):
    """Excluding bare ``google`` removes ``google.protobuf`` and Streamlit
    cannot send a single message. The app starts and shows nothing.

    Only the two dead leaves may be listed.
    """
    ex = BE.excludes_for(platform)
    assert "google" not in ex, (
        "bare 'google' is excluded - this removes google.protobuf and BRICKS "
        "the app. Only 'google.auth' / 'google.oauth2' are dead. See the "
        "module docstring.")
    assert "google.protobuf" not in ex
    assert "protobuf" not in ex


@pytest.mark.parametrize("platform", PLATFORMS)
def test_the_dead_google_leaves_are_still_excluded(platform):
    """The other direction - the fix for the trap must not be to give up and
    ship the whole chain."""
    ex = BE.excludes_for(platform)
    assert "google.auth" in ex
    assert "google.oauth2" in ex


@pytest.mark.parametrize("platform", PLATFORMS)
def test_no_exclude_is_a_parent_of_a_module_the_app_needs(platform):
    """Generalises the google trap: excluding ``X`` also kills ``X.anything``.

    Each entry here is imported on a path the app really takes, so a parent
    package appearing in the exclude list is the same class of mistake.
    """
    needed = [
        "google.protobuf",        # every Streamlit ForwardMsg
        "streamlit.runtime",
        "streamlit.components.v1",
        "canvasapi.course",
        "bs4.builder",            # html.parser registry
        "keyring.backends",
        "huggingface_hub.file_download",   # snapshot_download
        "faster_whisper.transcribe",
        "webview.http",           # pywebview serves the app
        "numpy.core",
        "psutil._common",
        "PIL.Image",
        "imageio_ffmpeg",
        "urllib3.util",
        "sqlite3.dbapi2",
    ]
    ex = set(BE.excludes_for(platform))
    for mod in needed:
        parts = mod.split(".")
        ancestors = {".".join(parts[:i]) for i in range(1, len(parts) + 1)}
        clash = ancestors & ex
        assert not clash, (
            f"{mod} is needed at runtime but {sorted(clash)} is excluded - "
            f"excluding a package excludes everything under it")


# ═══════════════════════════════════════════════════════════════════════════
# Platform deltas
# ═══════════════════════════════════════════════════════════════════════════

def test_tkinter_is_kept_on_windows_and_dropped_on_macos():
    """It IS the folder picker on Windows (``shared/helpers.py:pick_folder``).
    On macOS that function returns from the ``osascript`` branch on every path,
    so the tkinter import below it is unreachable and 7.1 MB of dead weight.
    """
    win = BE.excludes_for("windows")
    mac = BE.excludes_for("macos")
    assert "tkinter" not in win, "excluding tkinter breaks the Windows folder picker"
    assert "_tkinter" not in win
    assert "tkinter" in mac and "_tkinter" in mac


def test_only_tkinters_test_suite_goes_on_windows():
    """``lean_filter`` cannot catch this one - tkinter is stdlib, so it is
    never passed through ``collect_all``."""
    assert "tkinter.test" in BE.excludes_for("windows")


def test_the_windows_com_stack_survives_on_windows_and_goes_on_macos():
    """``converters/`` drives Office through ``win32com`` on Windows. macOS
    uses osascript and has no use for any of it."""
    win = BE.excludes_for("windows")
    mac = BE.excludes_for("macos")
    for mod in ("win32com", "pythoncom", "pywintypes"):
        assert mod not in win, f"{mod} is the Windows Office bridge"
        assert mod in mac
    assert "win11toast" not in win
    assert "winsound" not in win


def test_the_mfc_gui_goes_on_windows_but_the_com_client_stays():
    """``win32ui``/Pythonwin is 6.4 MB reached only via early-binding codegen
    (``win32com.client.makepy``). This app is late-binding throughout - but
    ``win32com.client`` itself must survive."""
    win = BE.excludes_for("windows")
    assert "win32ui" in win and "dde" in win
    assert "win32com.client" not in win


def test_the_windows_webview_backends_go_only_on_macos():
    mac = BE.excludes_for("macos")
    win = BE.excludes_for("windows")
    assert "webview.platforms.edgechromium" in mac
    assert "webview.platforms.edgechromium" not in win
    assert not any(e.startswith("webview.platforms.cocoa") for e in mac), \
        "the macOS webview backend must never be excluded from the mac build"


def test_an_unknown_platform_is_rejected_loudly():
    """A typo'd platform silently returning ``[]`` would ship an untrimmed
    build that still passes every other test here."""
    with pytest.raises(ValueError, match="unknown platform"):
        BE.excludes_for("linux")
    with pytest.raises(ValueError):
        BE.excludes_for("Windows")


@pytest.mark.parametrize("platform", PLATFORMS)
def test_the_exclude_list_has_no_duplicates(platform):
    """A duplicate means a module was added twice by two different rationales,
    and one of them will be deleted later without the other being noticed."""
    ex = BE.excludes_for(platform)
    dupes = {m for m in ex if ex.count(m) > 1}
    assert not dupes, f"duplicated exclude entries: {sorted(dupes)}"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_nothing_the_app_imports_at_module_level_is_excluded(platform):
    """The heavy stacks are only safe to exclude while the app really does not
    import them. ``torch`` in particular is excluded AND must stay uninstalled -
    a broken torch crashes ctranslate2 outright.
    """
    ex = set(BE.excludes_for(platform))
    for m in ("torch", "pandas", "matplotlib", "scipy", "cv2"):
        assert m in ex, f"{m} is heavy and unused - it should still be excluded"


# ═══════════════════════════════════════════════════════════════════════════
# lean_filter
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name", [
    "numpy.typing.tests", "numpy.typing.tests.data", "psutil.tests",
    "bs4.tests", "streamlit.testing", "streamlit.testing.v1",
    "keyring.testing", "numpy._pyinstaller", "numpy.f2py",
    "numpy.distutils", "somepkg.conftest", "numpy.benchmarks",
])
def test_junk_components_are_not_force_collected(name):
    assert BE.lean_filter(name) is False


@pytest.mark.parametrize("name", [
    "huggingface_hub.inference._mcp", "huggingface_hub.inference._mcp.agent",
    "huggingface_hub._oauth", "huggingface_hub.cli", "huggingface_hub.cli.download",
    "huggingface_hub.commands", "onnxruntime.tools", "onnxruntime.tools.x",
    "onnxruntime.transformers", "onnxruntime.quantization",
    "onnxruntime.training", "onnxruntime.datasets", "onnxruntime.backend",
])
def test_junk_prefixes_are_not_force_collected(name):
    assert BE.lean_filter(name) is False


@pytest.mark.parametrize("name", [
    "streamlit", "streamlit.runtime.scriptrunner", "streamlit.components.v1",
    "numpy", "numpy.core.multiarray", "psutil._psutil_windows",
    "huggingface_hub", "huggingface_hub.file_download",
    "huggingface_hub.utils._runtime", "onnxruntime.capi",
    "onnxruntime.capi.onnxruntime_inference_collection",
    "faster_whisper.transcribe", "bs4.builder", "webview.http",
    "canvasapi.course", "keyring.backends.Windows",
])
def test_the_real_runtime_modules_are_collected(name):
    assert BE.lean_filter(name) is True


@pytest.mark.parametrize("name,why", [
    ("huggingface_hub.client", "a sibling of 'cli', not a submodule of it"),
    ("huggingface_hub.cli_utils", "shares a prefix with 'cli' by characters only"),
    ("huggingface_hub.commands_helper", "shares a prefix with 'commands'"),
    ("onnxruntime.toolsets", "shares a prefix with 'tools'"),
    ("pkg.contest", "'contest' merely contains 'test'"),
    ("pkg.latest", "'latest' merely contains 'test'"),
    ("pkg.attestation", "'attestation' merely contains 'test'"),
    ("pkg.testify_helper", "not a bare 'test' component"),
])
def test_a_prefix_match_stops_at_a_module_boundary(name, why):
    """The junk list names PACKAGES. Matching raw characters instead of module
    boundaries silently drops innocent siblings, and the symptom would be an
    ``ImportError`` in the frozen build only.

    None of these exist today, which is the point - the failure would arrive
    with a routine dependency upgrade, long after anyone remembered this rule.
    """
    assert BE.lean_filter(name) is True, f"{name} was dropped: {why}"


def test_component_matching_is_on_whole_components_not_substrings():
    """The ``_JUNK_COMPONENTS`` half uses a set intersection over split parts,
    so it is already boundary-correct. Pinned so a "simplification" to
    ``any(c in name for c in ...)`` fails here instead of in a build."""
    assert BE.lean_filter("pkg.tests.mod") is False
    assert BE.lean_filter("pkg.contest.mod") is True
    assert BE.lean_filter("pkg.testing_utils") is True


def test_lean_filter_accepts_a_bare_top_level_name():
    for name in ("numpy", "streamlit", "psutil", "huggingface_hub"):
        assert BE.lean_filter(name) is True


def test_lean_filter_verdicts_are_unchanged_for_every_installed_module():
    """Regression net for the boundary fix.

    Walks every submodule of the packages the specs collect and asserts the
    result matches the raw-prefix behaviour that shipped. Measured at the time
    of the fix: 1,784 modules, zero verdict changes - so the fix narrows the
    trap without altering a single real decision. If this ever fails, a
    dependency has grown a name that the old form would have wrongly dropped:
    that is the fix working, and the expectation below is what to update.
    """
    def raw_prefix_form(name: str) -> bool:
        if set(name.split(".")) & BE._JUNK_COMPONENTS:
            return False
        return not name.startswith(BE._JUNK_PREFIXES)

    packages = ["streamlit", "canvasapi", "requests", "bs4", "keyring",
                "psutil", "webview", "huggingface_hub", "numpy"]
    examined, changed = 0, []
    for pkg in packages:
        spec = importlib.util.find_spec(pkg)
        if spec is None or not spec.submodule_search_locations:
            continue
        names = [pkg] + [m.name for m in pkgutil.walk_packages(
            list(spec.submodule_search_locations), prefix=pkg + ".")]
        for n in names:
            examined += 1
            if BE.lean_filter(n) != raw_prefix_form(n):
                changed.append(n)
    assert examined > 500, f"only walked {examined} modules - the walk is broken"
    assert not changed, (
        "the boundary fix changed the verdict for real installed modules: "
        f"{changed[:20]}")


# ═══════════════════════════════════════════════════════════════════════════
# strip_test_datas
# ═══════════════════════════════════════════════════════════════════════════

def _datas(*dests):
    """PyInstaller TOC entries are (dest, source, kind) tuples."""
    return [(d, f"/src/{d}", "DATA") for d in dests]


def test_bundled_test_directories_are_dropped():
    kept = BE.strip_test_datas(_datas(
        "numpy/tests/test_core.py",
        "numpy/typing/tests/data/x.pyi",
        "psutil/tests/__init__.py",
        "bs4/testing/helper.py",
        "pkg/benchmarks/bench.py",
    ))
    assert kept == []


def test_test_modules_and_conftest_are_dropped_wherever_they_sit():
    kept = BE.strip_test_datas(_datas(
        "pkg/test_thing.py", "pkg/conftest.py", "conftest.py"))
    assert kept == []


def test_real_data_is_kept():
    """The narrowness is the whole point - this runs over every data file in
    the build, and a greedy match would silently delete real assets."""
    dests = [
        "certifi/cacert.pem",
        "streamlit/static/index.html",
        "pkg/latest.json",              # contains "test" as a substring
        "pkg/contest/rules.txt",        # directory merely contains "test"
        "pkg/attestation/data.bin",
        "pkg/testing_utils.py",         # not "test_*" and not a junk dir
        "pkg/my_test_helper.py",        # does not START with test_
        "tokenizers/tokenizer.json",
    ]
    kept = BE.strip_test_datas(_datas(*dests))
    assert [k[0] for k in kept] == dests


def test_windows_backslash_destinations_are_handled():
    """The TOC on Windows carries backslashes; matching only on '/' would let
    every test directory through on the platform that actually builds."""
    kept = BE.strip_test_datas([
        ("numpy\\tests\\test_core.py", "/src/a", "DATA"),
        ("numpy\\core\\_methods.py", "/src/b", "DATA"),
    ])
    assert [k[0] for k in kept] == ["numpy\\core\\_methods.py"]


def test_the_tuple_shape_is_preserved():
    """PyInstaller reads these positionally; rebuilding them as 2-tuples or
    reordering the fields breaks the build with an opaque error."""
    entries = _datas("certifi/cacert.pem")
    kept = BE.strip_test_datas(entries)
    assert kept == entries
    assert kept[0] is entries[0], "entries must pass through by identity"


def test_an_empty_toc_is_fine():
    assert BE.strip_test_datas([]) == []


def test_a_file_named_exactly_test_py_is_dropped_but_testpy_is_not():
    kept = BE.strip_test_datas(_datas("pkg/test_.py", "pkg/tests.py"))
    assert [k[0] for k in kept] == ["pkg/tests.py"]


# ═══════════════════════════════════════════════════════════════════════════
# Both specs must actually use the shared policy
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("spec_name,platform", [
    ("Canvas_Downloader.spec", "windows"),
    ("Canvas_Downloader_macOS.spec", "macos"),
])
def test_each_spec_routes_through_the_shared_policy(spec_name, platform):
    """The module exists because a trimming fix applied to only one spec ships
    a fat build on the other OS, invisibly. A spec that stops calling it - or
    grows its own inline ``excludes=[...]`` - defeats the whole arrangement.
    """
    spec = REPO / spec_name
    if not spec.is_file():
        pytest.skip(f"{spec_name} not present")
    src = spec.read_text(encoding="utf-8")
    assert "lean_filter" in src, f"{spec_name} no longer filters submodules"
    assert f"excludes_for('{platform}')" in src or \
           f'excludes_for("{platform}")' in src, \
        f"{spec_name} does not ask for the {platform} exclude list"
    assert "strip_test_datas" in src, \
        f"{spec_name} no longer strips bundled test data from a.datas"


@pytest.mark.parametrize("spec_name", [
    "Canvas_Downloader.spec", "Canvas_Downloader_macOS.spec"])
def test_no_spec_carries_its_own_inline_exclude_list(spec_name):
    """``excludes=`` must name the shared helper, never a literal list."""
    spec = REPO / spec_name
    if not spec.is_file():
        pytest.skip(f"{spec_name} not present")
    for line in spec.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("excludes="):
            assert "excludes_for" in stripped, (
                f"{spec_name} has an inline exclude list: {stripped!r} - put it "
                f"in scripts/build_excludes.py so both platforms get it")
