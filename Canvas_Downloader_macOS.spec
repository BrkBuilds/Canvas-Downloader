# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, copy_metadata
import sys
import os
import imageio_ffmpeg



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
    ('macos_controller.py', '.'),
    ('LICENSE', '.'),
]

ffmpeg_exe_path = imageio_ffmpeg.get_ffmpeg_exe()
binaries = [(ffmpeg_exe_path, 'imageio_ffmpeg/binaries')]
hiddenimports = []
datas += copy_metadata('imageio')

tmp_ret = collect_all('streamlit')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('canvasapi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

packages_to_collect = [
    'requests', 'aiohttp', 'charset_normalizer', 'idna', 'urllib3', 'certifi',
    'aiofiles', 'beautifulsoup4', 'markdownify', 'moviepy', 'keyring', 'psutil',
    'sqlite3', 'imageio', 'imageio_ffmpeg', 'pync', 'customtkinter', 'PIL',
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
    'tkinter', 'tkinter.filedialog', '_tkinter', 'plistlib',
    'moviepy.audio.fx.all', 'moviepy.video.fx.all',
]

a = Analysis(
    ['start.py'],
    pathex=[], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['matplotlib', 'IPython', 'jupyter', 'notebook', 'pytest', 'scipy', 'PyQt5', 'PyQt6', 'PySide6', 'webview',
              'tkinter.test', 'doctest', 'pdb', 'unittest', 'pydoc', 'curses', 'sqlalchemy',
              'pyarrow', 'altair', 'pydeck', 'pandas', 'polars', 'botocore', 'boto3',
              'bokeh', 'plotly', 'seaborn', 'statsmodels', 'tensorboard', 'tensorflow', 'torch', 'keras',
              'numba', 'cython', 'dask', 'networkx', 'h5py', 'sympy', 'patsy',
              'win32com', 'win32com.client', 'pythoncom', 'pywintypes',
              'webview.platforms.winforms', 'webview.platforms.edgechromium',
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
        'CFBundleShortVersionString': '2.0.0',
        'CFBundleName': 'Canvas Downloader',
        'NSRequiresAquaSystemAppearance': False,
        # Minimum macOS version (CustomTkinter requires 11.0+)
        'LSMinimumSystemVersion': '11.0',
        # Required on macOS 10.14+ for AppleScript automation of Office apps.
        # Without this key the TCC permission dialog shows no description.
        'NSAppleEventsUsageDescription': (
            'Canvas Downloader uses Microsoft Office to convert PowerPoint, '
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
    },
)