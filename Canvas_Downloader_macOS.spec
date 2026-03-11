# -*- mode: python ; coding: utf-8 -*-
# Canvas Downloader — macOS PyInstaller Spec
# Usage: pyinstaller Canvas_Downloader_macOS.spec
from PyInstaller.utils.hooks import collect_all
import sys
import os

datas = [('app.py', '.'), ('canvas_logic.py', '.'), ('assets', 'assets')]
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
    'engineio.async_drivers.threading',
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
              'tkinter.test', 'doctest', 'pdb', 'unittest', 'pydoc', 'curses',
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
