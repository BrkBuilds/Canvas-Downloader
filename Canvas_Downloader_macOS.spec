# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, copy_metadata
import sys
import os
import glob as _glob
import importlib.util as _ilu
import imageio_ffmpeg

# ── Resolve app version from version.py ──────────────────────────────
_ver_spec = _ilu.spec_from_file_location("version", os.path.join(os.path.dirname(os.path.abspath(SPEC)), "version.py"))
_ver_mod  = _ilu.module_from_spec(_ver_spec)
_ver_spec.loader.exec_module(_ver_mod)
_APP_VERSION = _ver_mod.__version__


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
    ('.streamlit', '.streamlit'),
    ('core', 'core'),
    ('engine', 'engine'),
    ('sync', 'sync'),
    ('ui', 'ui'),
    ('styles', 'styles'),
    ('LICENSE', '.'),
]

ffmpeg_exe_path = imageio_ffmpeg.get_ffmpeg_exe()
binaries = [(ffmpeg_exe_path, 'imageio_ffmpeg/binaries')]
hiddenimports = []
datas += copy_metadata('imageio')
datas += copy_metadata('keyring')   # Fix 1: required for importlib.metadata entry_points backend discovery

# Fix 6: include terminal-notifier binary so pync notifications are attributed to the app,
#         not "Script Editor".  collect_all('pync') captures the Python wrapper but may not
#         preserve the executable bit on the binary - we add it explicitly as a binary.
_tn_bin = None
try:
    import pync as _pync_mod
    _tn_search = _glob.glob(
        os.path.join(os.path.dirname(_pync_mod.__file__), '**', 'terminal-notifier'),
        recursive=True,
    )
    if _tn_search:
        _tn_bin = _tn_search[0]
except Exception:
    pass
if _tn_bin is None:
    import shutil as _shutil
    _tn_bin = _shutil.which('terminal-notifier')
if _tn_bin and os.path.isfile(_tn_bin):
    binaries += [(_tn_bin, os.path.join('pync', 'vendor', 'terminal-notifier.app', 'Contents', 'MacOS'))]

tmp_ret = collect_all('streamlit')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('canvasapi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

packages_to_collect = [
    'requests', 'aiohttp', 'charset_normalizer', 'idna', 'urllib3', 'certifi',
    'aiofiles', 'bs4', 'markdownify', 'moviepy', 'keyring', 'psutil',
    'sqlite3', 'imageio', 'imageio_ffmpeg', 'pync', 'webview', 'pillow', 'openpyxl',
]

for package in packages_to_collect:
    try:
        tmp_ret = collect_all(package)
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
]

a = Analysis(
    ['start.py'],
    pathex=[], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['matplotlib', 'IPython', 'jupyter', 'notebook', 'pytest', 'scipy', 'PyQt5', 'PyQt6', 'PySide6',
              'tkinter.test', 'doctest', 'pdb', 'unittest', 'pydoc', 'curses', 'sqlalchemy',
              'pyarrow', 'altair', 'pydeck', 'pandas', 'polars', 'botocore', 'boto3',
              'bokeh', 'plotly', 'seaborn', 'statsmodels', 'tensorboard', 'tensorflow', 'torch', 'keras',
              'numba', 'cython', 'dask', 'networkx', 'h5py', 'sympy', 'patsy',
              'win32com', 'win32com.client', 'pythoncom', 'pywintypes',
              'webview.platforms.winforms', 'webview.platforms.edgechromium', 'webview.platforms.qt', 'webview.platforms.gtk',
              'win11toast', 'winsound', 'streamlit.external.langchain'],
    noarchive=False, optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='Canvas_Downloader', icon='assets/icon.icns', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
)

coll = COLLECT(
    exe, a.binaries, a.datas, strip=False, upx=False, name='Canvas_Downloader',
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
        # Minimum macOS version (CustomTkinter requires 11.0+)
        'LSMinimumSystemVersion': '11.0',
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
