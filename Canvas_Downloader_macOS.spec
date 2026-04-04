# -*- mode: python ; coding: utf-8 -*-
# Canvas Downloader — macOS PyInstaller Spec
# Usage: pyinstaller Canvas_Downloader_macOS.spec
#
# Synchronized with Canvas_Downloader.spec (Windows) as of Phase 1
# macOS Parity Remediation — F-04, F-05, F-06, F-07, F-13, F-19
from PyInstaller.utils.hooks import collect_all, copy_metadata
import sys
import os
import imageio_ffmpeg

# ── Data Files ─────────────────────────────────────────────────────
# Mirror ALL python modules + directories from the Windows spec.
datas = [
    ('app.py', '.'),
    ('canvas_logic.py', '.'),
    ('canvas_debug.py', '.'),
    ('sync_manager.py', '.'),
    ('sync_ui.py', '.'),
    ('ui_helpers.py', '.'),
    ('ui_shared.py', '.'),
    ('preset_manager.py', '.'),
    ('code_converter.py', '.'),
    ('md_converter.py', '.'),
    ('pdf_converter.py', '.'),
    ('word_converter.py', '.'),
    ('excel_converter.py', '.'),
    ('video_converter.py', '.'),
    ('archive_extractor.py', '.'),
    ('post_processing.py', '.'),
    ('url_compiler.py', '.'),
    ('version.py', '.'),
    ('theme.py', '.'),
    ('assets', 'assets'),
    # Modularized packages (added during The Convergence refactor)
    ('core', 'core'),
    ('engine', 'engine'),
    ('sync', 'sync'),
    ('ui', 'ui'),
    ('styles', 'styles'),
]

# ── FFmpeg Binary ──────────────────────────────────────────────────
# Automatically locate the macOS FFmpeg binary provided by imageio_ffmpeg.
# This enables video-to-MP3 conversion (F-07).
ffmpeg_exe_path = imageio_ffmpeg.get_ffmpeg_exe()

binaries = [
    (ffmpeg_exe_path, 'imageio_ffmpeg/binaries')
]
hiddenimports = []

# ImageIO needs its own metadata to survive importlib.metadata.version() checks
datas += copy_metadata('imageio')

# ── Dependency Collection ──────────────────────────────────────────
# Collect all Streamlit dependencies
tmp_ret = collect_all('streamlit')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Collect CanvasAPI
tmp_ret = collect_all('canvasapi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Collect other critical packages — fully synchronized with Windows spec
packages_to_collect = [
    'requests', 'aiohttp', 'charset_normalizer', 'idna', 'urllib3', 'certifi',
    'aiofiles', 'beautifulsoup4', 'markdownify', 'moviepy', 'keyring', 'psutil',
    'webview', 'sqlite3', 'imageio', 'imageio_ffmpeg',
]
for package in packages_to_collect:
    try:
        tmp_ret = collect_all(package)
        datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    except Exception:
        pass

# ── Hidden Imports ─────────────────────────────────────────────────
# Add specific hidden imports that might be missed by collect_all.
hiddenimports += [
    'streamlit.web.cli',
    'streamlit.runtime.scriptrunner.magic_funcs',
    'streamlit.runtime.scriptrunner.script_runner',
    'engineio.async_drivers.threading',
    'tkinter',
    'tkinter.filedialog',
    '_tkinter',
    # macOS-critical: used by url_compiler.py for .webloc file parsing
    'plistlib',
    # PyWebView — now used on macOS for native windowing (Phase 2 remediation)
    'webview',
    'webview.platforms.cocoa',
    # MoviePy fx modules for video conversion
    'moviepy.audio.fx.all',
    'moviepy.video.fx.all',
]

# ── Analysis ───────────────────────────────────────────────────────
a = Analysis(
    ['start.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'IPython', 'jupyter', 'notebook', 'pytest', 'scipy', 'PyQt5', 'PyQt6',
              'tkinter.test', 'doctest', 'pdb', 'unittest', 'pydoc', 'curses',
              'sqlalchemy',
              # Heavy packages not used by this app
              'pyarrow', 'altair', 'pydeck', 'pandas', 'polars', 'botocore', 'boto3',
              'bokeh', 'plotly', 'seaborn', 'statsmodels', 'tensorboard', 'tensorflow', 'torch', 'keras',
              'numba', 'cython', 'dask', 'networkx', 'h5py', 'sympy', 'patsy',
              # Windows-only packages (not needed on macOS)
              'win32com', 'win32com.client', 'pythoncom', 'pywintypes',
              'webview.platforms.winforms', 'webview.platforms.edgechromium',
              # More unused Streamlit features
              'streamlit.external.langchain'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Canvas_Downloader',
    icon='assets/icon.icns',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX is not commonly used on macOS
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file='entitlements.plist',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Canvas_Downloader',
)

app = BUNDLE(
    coll,
    name='Canvas Downloader.app',
    icon='assets/icon.icns',
    bundle_identifier='com.canvasdownloader.app',
    info_plist={
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': '2.0.0',
        'CFBundleName': 'Canvas Downloader',
        'NSRequiresAquaSystemAppearance': False,  # Support Dark Mode
    },
)
