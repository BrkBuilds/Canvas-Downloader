# -*- mode: python ; coding: utf-8 -*-
# Build via: python build_windows.py
# That script generates version_info.py from version.py, then calls pyinstaller.
from PyInstaller.utils.hooks import collect_all, copy_metadata
import importlib.util
import sys
import os
import imageio_ffmpeg

# Read version from version.py so the PE resource stays in sync automatically.
_vspec = importlib.util.spec_from_file_location("version", os.path.join(SPECPATH, "version.py"))
_vmod  = importlib.util.module_from_spec(_vspec)
_vspec.loader.exec_module(_vmod)
_APP_VERSION = _vmod.__version__

datas = [
    ('app.py', '.'), 
    ('sync_ui.py', '.'),
    ('version.py', '.'),
    ('assets', 'assets'),
    # Modularized packages (added during The Convergence refactor)
    ('core', 'core'),
    ('converters', 'converters'),
    ('engine', 'engine'),
    ('shared', 'shared'),
    ('sync', 'sync'),
    ('panopto', 'panopto'),   # Panopto recording downloader (premium feature)
    ('ui', 'ui'),
    ('styles', 'styles'),
    ('.streamlit', '.streamlit'),
    ('LICENSE', '.'),
]

# Automatically locate the ffmpeg binary provided by imageio_ffmpeg
ffmpeg_exe_path = imageio_ffmpeg.get_ffmpeg_exe()

binaries = [
    (ffmpeg_exe_path, 'imageio_ffmpeg/binaries')
]
hiddenimports = []

# ImageIO needs its own metadata to survive importlib.metadata.version() checks
datas += copy_metadata('imageio')

# Helper to load a build script from scripts/ (same pattern as version.py above).
def _load_build_script(name):
    _s = importlib.util.spec_from_file_location(name, os.path.join(SPECPATH, "scripts", name + ".py"))
    _m = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(_m)
    return _m

# Strip regex lookbehind from Streamlit's bundled JS so the UI renders on older
# WebKit/JS engines (see patch_streamlit_webkit.py). Harmless on WebView2 but
# kept for parity with the macOS build, where it is required.
_load_build_script("patch_streamlit_webkit").patch()

# Paint the launcher's splash from inside Streamlit's own index.html, so the
# window never shows an empty page between load_url() and the app's first
# rendered frame (measured at 6.9s warm, 10-20s on a cold first launch).
# See scripts/patch_streamlit_boot.py.
_load_build_script("patch_streamlit_boot").patch(SPECPATH)

# Replace faster-whisper's PyAV decoder with one driving the ffmpeg binary this
# app already bundles, so PyAV's SECOND full copy of FFmpeg (62 MB of libav
# DLLs) can be excluded. See scripts/patch_faster_whisper_audio.py - it refuses
# to patch an untested faster-whisper version rather than fail silently.
_load_build_script("patch_faster_whisper_audio").patch()

# Shared trimming policy - see scripts/build_excludes.py for the traced import
# chains behind every entry. Kept in ONE file because a fix applied to only one
# of the two specs is invisible in review and ships a fat build on the other OS.
_excl = _load_build_script("build_excludes")

# Collect all Streamlit dependencies
tmp_ret = collect_all('streamlit', filter_submodules=_excl.lean_filter)
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Collect CanvasAPI
tmp_ret = collect_all('canvasapi', filter_submodules=_excl.lean_filter)
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Collect other critical packages
packages_to_collect = [
    'requests', 'aiohttp', 'charset_normalizer', 'idna', 'urllib3', 'certifi',
    'aiofiles', 'bs4', 'markdownify', 'moviepy', 'keyring', 'psutil',
    'webview', 'sqlite3', 'imageio', 'imageio_ffmpeg', 'win11toast', 'openpyxl', 'pillow',
    # Panopto transcription stack (faster-whisper via CTranslate2; NO torch).
    # Each is wrapped in try/except below, so a dev machine without these
    # installed still builds - they're only bundled when present.
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

# Add specific hidden imports that might be missed
hiddenimports += [
    'streamlit.web.cli',
    'streamlit.runtime.scriptrunner.magic_funcs',
    'streamlit.runtime.scriptrunner.script_runner',
    'engineio.async_drivers.threading', # Common issue with python-socketio/engineio
    'tkinter',
    'tkinter.filedialog',
    '_tkinter',
    'plistlib',
    'win32com',
    'win32com.client',
    'pythoncom',
    'pywintypes',
    'webview',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'moviepy.audio.fx.all',
    'moviepy.video.fx.all',
    'winsound',
]

a = Analysis(
    ['start.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Every entry, and the traced import chain that justifies it, lives in
    # scripts/build_excludes.py. Do NOT add one-off exclusions here - the two
    # specs drift apart the moment anything platform-agnostic is written twice.
    excludes=_excl.excludes_for('windows'),
    noarchive=False,
    optimize=0,
)

# collect_all() also runs collect_data_files(), which copies test suites back in
# as DATA even though lean_filter kept them out of the import graph. Nothing
# imports them, so they are pure dead weight on disk (measured: 7.29 MB, 6.36 MB
# of it numpy's). Data-only - this can never make an import fail.
a.datas = _excl.strip_test_datas(a.datas)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Canvas Downloader',
    icon='assets/icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # version_info.py is generated by build_windows.py from version.py.
    # Running pyinstaller directly (without build_windows.py) uses the last
    # generated file, which is fine for dev builds.
    version='version_info.py',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Canvas Downloader',
)
