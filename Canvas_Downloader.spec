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
]

# Automatically locate the ffmpeg binary provided by imageio_ffmpeg
ffmpeg_exe_path = imageio_ffmpeg.get_ffmpeg_exe()

binaries = [
    (ffmpeg_exe_path, 'imageio_ffmpeg/binaries')
]
hiddenimports = []

# ImageIO needs its own metadata to survive importlib.metadata.version() checks
datas += copy_metadata('imageio')

# Collect all Streamlit dependencies
tmp_ret = collect_all('streamlit')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Collect CanvasAPI
tmp_ret = collect_all('canvasapi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Collect other critical packages
packages_to_collect = [
    'requests', 'aiohttp', 'charset_normalizer', 'idna', 'urllib3', 'certifi',
    'aiofiles', 'beautifulsoup4', 'markdownify', 'moviepy', 'keyring', 'psutil',
    'webview', 'sqlite3', 'imageio', 'imageio_ffmpeg'
]
for package in packages_to_collect:
    try:
        tmp_ret = collect_all(package)
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
    excludes=['matplotlib', 'IPython', 'jupyter', 'notebook', 'pytest', 'scipy', 'PyQt5', 'PyQt6', 
              'tkinter.test', 'doctest', 'pdb', 'unittest', 'pydoc', 'curses',
              'sqlalchemy',
              # Heavy packages not used by this app
              'pyarrow', 'altair', 'pydeck', 'pandas', 'polars', 'botocore', 'boto3',
              'bokeh', 'plotly', 'seaborn', 'statsmodels', 'tensorboard', 'tensorflow', 'torch', 'keras',
              'numba', 'cython', 'dask', 'networkx', 'h5py', 'sympy', 'patsy',
              # More unused Streamlit features
              'streamlit.external.langchain'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Canvas_Downloader',
    icon='assets/icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False, # Set to True for debugging if needed, False for production
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
