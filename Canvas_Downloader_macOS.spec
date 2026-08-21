# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, copy_metadata
import sys
import os
import importlib.util as _ilu
import imageio_ffmpeg

# ── Resolve app version from version.py ──────────────────────────────
_ver_spec = _ilu.spec_from_file_location("version", os.path.join(os.path.dirname(os.path.abspath(SPEC)), "version.py"))
_ver_mod  = _ilu.module_from_spec(_ver_spec)
_ver_spec.loader.exec_module(_ver_mod)
_APP_VERSION = _ver_mod.__version__


datas = [
    ('app.py', '.'),
    ('sync_ui.py', '.'),
    ('version.py', '.'),
    ('assets', 'assets'),
    ('.streamlit', '.streamlit'),
    ('core', 'core'),
    ('converters', 'converters'),
    ('engine', 'engine'),
    ('shared', 'shared'),
    ('sync', 'sync'),
    ('panopto', 'panopto'),   # Panopto recording downloader (premium feature)
    ('ui', 'ui'),
    ('styles', 'styles'),
    ('LICENSE', '.'),
]

ffmpeg_exe_path = imageio_ffmpeg.get_ffmpeg_exe()
binaries = [(ffmpeg_exe_path, 'imageio_ffmpeg/binaries')]
hiddenimports = []
datas += copy_metadata('imageio')
datas += copy_metadata('keyring')   # Fix 1: required for importlib.metadata entry_points backend discovery

# pync / terminal-notifier is DELIBERATELY NOT BUNDLED - it breaks the signature.
#
# There used to be a "Fix 6" here that shipped the vendored terminal-notifier
# binary explicitly, so notifications would be attributed to the app rather than
# to "Script Editor". The cost turned out to be the whole bundle's signature:
# PyInstaller rewrites `.` to `__dot__` in those nested directory names, so the
# app arrives holding `terminal-notifier__dot__app`, which is no longer a valid
# bundle, and `codesign --verify --strict` fails for the ENTIRE app with "the main
# executable or Info.plist must be a regular file". Ad-hoc distribution tolerated
# it; NOTARIZATION does not, so it blocked any Developer-ID release - and the DMG
# is built in CI, where an unverifiable artifact is the thing that fails last and
# loudest.
#
# Removing the exclude from scripts/build_excludes.py is NOT sufficient on its
# own and that is the trap: `excludes` stops a module being IMPORTED, while
# collect_all also runs collect_data_files, which copies the package (and its
# vendored .app) in as DATA regardless. Both this block and the 'pync' entry in
# the collect_all list below had to go. Verified by searching the built bundle for
# '*pync*' and '*__dot__*app'.
#
# Safe: engine/notifications.py guards the import (`except ImportError:
# _PyncNotifier = None`) and simply falls through to its osascript path, which was
# fixed 2026-08-10; the PRIMARY UNUserNotificationCenter path is verified working
# on real hardware; and CLAUDE.md already records the vendored binary as
# unreliable on arm64 Sequoia.

# ── WebKit lookbehind patch (macOS) ──────────────────────────────────
# pywebview renders inside WKWebView (system WebKit). JavaScriptCore on
# macOS < 13.3 (Safari < 16.4) cannot parse regex lookbehind, which Streamlit
# 1.51's markdown autolink transform builds at runtime - crashing the whole UI
# with "Invalid regular expression: invalid group specifier name". Strip the
# lookbehind assertions from the bundled JS BEFORE collecting them.
def _load_build_script(name):
    _s = _ilu.spec_from_file_location(
        name, os.path.join(os.path.dirname(os.path.abspath(SPEC)), "scripts", name + ".py")
    )
    _m = _ilu.module_from_spec(_s)
    _s.loader.exec_module(_m)
    return _m

_load_build_script("patch_streamlit_webkit").patch()

# Paint the launcher's splash from inside Streamlit's own index.html, so the
# window never shows an empty page between load_url() and the app's first
# rendered frame (measured at 6.9s warm, 10-20s on a cold first launch).
# See scripts/patch_streamlit_boot.py.
_load_build_script("patch_streamlit_boot").patch(
    os.path.dirname(os.path.abspath(SPEC)))

# Replace faster-whisper's PyAV decoder with one driving the ffmpeg binary this
# app already bundles, so PyAV's SECOND full copy of FFmpeg (62 MB of libav
# libraries) can be excluded. See scripts/patch_faster_whisper_audio.py - it
# refuses to patch an untested faster-whisper version rather than fail silently.
_load_build_script("patch_faster_whisper_audio").patch()

# Shared trimming policy - see scripts/build_excludes.py for the traced import
# chains behind every entry. Kept in ONE file because a fix applied to only one
# of the two specs is invisible in review and ships a fat build on the other OS.
_excl = _load_build_script("build_excludes")

tmp_ret = collect_all('streamlit', filter_submodules=_excl.lean_filter)
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('canvasapi', filter_submodules=_excl.lean_filter)
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

packages_to_collect = [
    'requests', 'aiohttp', 'charset_normalizer', 'idna', 'urllib3', 'certifi',
    'aiofiles', 'bs4', 'markdownify', 'moviepy', 'keyring', 'psutil',
    # 'pync' is deliberately absent - see the signature note above.
    'sqlite3', 'imageio', 'imageio_ffmpeg', 'webview', 'pillow', 'openpyxl',
    # Modern macOS notifications via UNUserNotificationCenter. collect_all is a
    # no-op on a non-mac build host (wrapped in try/except below); on macOS it
    # pulls the PyObjC framework bindings. Falls back to NSUserNotification if absent.
    'UserNotifications',
    # Panopto transcription stack (faster-whisper via CTranslate2; NO torch).
    # Wrapped in try/except below, so a host without these still builds.
    # 'av' is deliberately absent: patch_faster_whisper_audio.py removed the
    # only import of it, and it is in the exclude list.
    'faster_whisper', 'ctranslate2', 'tokenizers', 'huggingface_hub',
    'onnxruntime', 'numpy',
]

for package in packages_to_collect:
    try:
        # filter_submodules keeps test suites, CLI surfaces and dev tooling from
        # being FORCE-added as hidden imports. It does not make anything
        # unavailable - a module something really imports is still collected by
        # normal graph analysis.
        tmp_ret = collect_all(package, filter_submodules=_excl.lean_filter)
        datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    except Exception:
        pass

hiddenimports += [
    'streamlit.web.cli',
    'streamlit.runtime.scriptrunner.magic_funcs',
    'streamlit.runtime.scriptrunner.script_runner',
    'engineio.async_drivers.threading',
    'plistlib',
    # Fix 1: keyring macOS Keychain backend - needed for token persistence
    'keyring.backends', 'keyring.backends.macOS',
    # Modern macOS notification framework (UNUserNotificationCenter). PyInstaller's
    # PyObjC hook bundles the binding when it's listed here; harmless if absent.
    'UserNotifications',
]

a = Analysis(
    ['start.py'],
    pathex=[], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    # Every entry, and the traced import chain that justifies it, lives in
    # scripts/build_excludes.py. Do NOT add one-off exclusions here - the two
    # specs drift apart the moment anything platform-agnostic is written twice.
    excludes=_excl.excludes_for('macos'),
    noarchive=False, optimize=0,
)

# collect_all() also runs collect_data_files(), which copies test suites back in
# as DATA even though lean_filter kept them out of the import graph. Nothing
# imports them, so they are pure dead weight on disk (measured: 7.29 MB, 6.36 MB
# of it numpy's). Data-only - this can never make an import fail.
a.datas = _excl.strip_test_datas(a.datas)

# The app's own packages are bundled by DIRECTORY, so a developer's __pycache__
# ships with the source. codesign SEALS it, and anything that later removes a
# .pyc breaks the seal - which on macOS downgrades Gatekeeper from the
# recoverable "Apple could not verify..." dialog (exit 3) to "...is damaged and
# can't be opened" (exit 1), a dialog with no Open Anyway path. The app ships
# unsigned by design, so that one recoverable dialog is the whole onboarding
# route. Measured on macOS 26.6.1; see strip_bytecode_datas.
a.datas = _excl.strip_bytecode_datas(a.datas)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='Canvas_Downloader', icon='assets/icon.icns', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
)

# Headless transcription worker: SAME code (start.py routes via the
# CANVAS_DL_TRANSCRIBE_WORKER env var) but built with the CONSOLE bootloader.
# The windowed bootloader registers every process with LaunchServices to handle
# Apple events - which is what made each transcribe child surface in the Dock:
# first as a live second app (fixed by the Prohibited demotion), then on
# macOS 15 as a phantom "Canvas Downloader" recents tile filed at the child's
# termination, held in the Dock's MEMORY (invisible to `defaults export`, so
# the prefs-based recents strip can't catch it until a Dock restart). A console
# binary never touches LaunchServices, so workers leave no Dock trace at all.
# panopto.transcribe._worker_command prefers this binary when present.
exe_worker = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='Canvas_Downloader_Worker', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=True,
)

coll = COLLECT(
    exe, exe_worker, a.binaries, a.datas, strip=False, upx=False, name='Canvas_Downloader',
)

app = BUNDLE(
    coll, name='Canvas Downloader.app', icon='assets/icon.icns',
    bundle_identifier='com.canvasdownloader.app',
    info_plist={
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': _APP_VERSION,   # Fix 8: read from version.py at build time
        'CFBundleVersion': _APP_VERSION,
        'CFBundleName': 'Canvas Downloader',
        'NSRequiresAquaSystemAppearance': False,
        # Minimum macOS version.
        #
        # 14.0, and it is NOT a preference - it is what the bundled native
        # wheels actually require. The floor is set by whatever pip resolves at
        # build time, and CI builds on `macos-14`, so pip takes the highest
        # compatible platform tag: onnxruntime publishes arm64 wheels tagged
        # `macosx_14_0` ONLY, and numpy ships both 11.0 and 14.0. Declaring 11.0
        # here did not make the binaries run on Big Sur - it just meant a
        # student on an older Mac downloaded 151 MB and got a dyld failure
        # instead of an honest "requires macOS 14" refusal from the OS.
        #
        # The old comment ("CustomTkinter requires 11.0+") is also stale twice
        # over: this app has no CustomTkinter, and 11.0 was the floor of Apple
        # Silicon itself, not of anything we ship.
        #
        # This number is VERIFIED against the built bundle, not trusted:
        # scripts/check_macos_floor.py reads LC_BUILD_VERSION out of every
        # Mach-O in the .app and fails the build if any binary demands a newer
        # macOS than this key promises. Raise the wheels and the build tells
        # you; it can no longer drift silently between releases.
        'LSMinimumSystemVersion': '14.0',
        # Required on macOS 10.14+ for AppleScript automation (Office).
        # Without this key the TCC permission dialog shows no description.
        'NSAppleEventsUsageDescription': (
            'Canvas Downloader controls Microsoft Office to convert PowerPoint, '
            'Word, and Excel files to PDF.'
        ),
        # TCC usage strings shown when the OS prompts for folder/file access.
        'NSDocumentsFolderUsageDescription': (
            'Canvas Downloader saves downloaded course files to your chosen folder.'
        ),
        'NSDownloadsFolderUsageDescription': (
            'Canvas Downloader may save downloaded course files to your Downloads folder.'
        ),
        'NSDesktopFolderUsageDescription': (
            'Canvas Downloader may save downloaded course files to your Desktop.'
        ),
        # Fix 11: required when the user picks a folder on an external/removable volume.
        'NSRemovableVolumesUsageDescription': (
            'Canvas Downloader saves downloaded course files to your chosen folder.'
        ),
    },
    entitlements='entitlements.mac.plist',
)
