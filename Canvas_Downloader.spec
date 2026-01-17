# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import sys
import os

datas = [('app.py', '.'), ('canvas_logic.py', '.'), ('translations.py', '.'), ('assets', 'assets')]
binaries = []
hiddenimports = []

# Collect all Streamlit dependencies
tmp_ret = collect_all('streamlit')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Collect CanvasAPI
tmp_ret = collect_all('canvasapi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Collect other critical packages
packages_to_collect = ['requests', 'aiohttp', 'charset_normalizer', 'idna', 'urllib3', 'certifi']
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
              'tkinter.test', 'doctest', 'pdb', 'unittest', 'difflib', 'pydoc', 'curses',
              'sqlalchemy',
              # Heavy packages not used by this app
              'pyarrow', 'altair', 'pydeck', 'pandas', 'numpy',
              # More unused Streamlit features
              'streamlit.external.langchain', 'PIL', 'Pillow'],
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
