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

# Strip regex lookbehind from Streamlit's bundled JS so the UI renders on older
# WebKit/JS engines (see patch_streamlit_webkit.py). Harmless on WebView2 but
# kept for parity with the macOS build, where it is required.
_pspec = importlib.util.spec_from_file_location(
    "patch_streamlit_webkit", os.path.join(SPECPATH, "scripts", "patch_streamlit_webkit.py")
)
_pmod = importlib.util.module_from_spec(_pspec)
_pspec.loader.exec_module(_pmod)
_pmod.patch()

# Collect all Streamlit dependencies
tmp_ret = collect_all('streamlit')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Collect CanvasAPI
tmp_ret = collect_all('canvasapi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Collect other critical packages
packages_to_collect = [
    'requests', 'aiohttp', 'charset_normalizer', 'idna', 'urllib3', 'certifi',
    'aiofiles', 'bs4', 'markdownify', 'moviepy', 'keyring', 'psutil',
    'webview', 'sqlite3', 'imageio', 'imageio_ffmpeg', 'win11toast', 'openpyxl', 'pillow',
    # Panopto transcription stack (faster-whisper via CTranslate2; NO torch).
    # Each is wrapped in try/except below, so a dev machine without these
    # installed still builds - they're only bundled when present.
    'faster_whisper', 'ctranslate2', 'tokenizers', 'huggingface_hub',
    'av', 'onnxruntime', 'numpy',
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
    excludes=['matplotlib', 'IPython', 'jupyter', 'notebook', 'pytest', 'scipy', 'PyQt5', 'PyQt6',
              'pync', 'customtkinter',
              'tkinter.test', 'doctest', 'pdb', 'unittest', 'pydoc', 'curses',
              'sqlalchemy',
              # Heavy packages not used by this app
              'pyarrow', 'altair', 'pydeck', 'pandas', 'polars', 'botocore', 'boto3',
              'bokeh', 'plotly', 'seaborn', 'statsmodels', 'tensorboard', 'tensorflow', 'torch', 'keras',
              'numba', 'cython', 'dask', 'networkx', 'h5py', 'sympy', 'patsy',
              # OpenCV (~99 MB) is pulled transitively via moviepy's optional video
              # effects (resize/blur/crop), which this app never calls - it only does
              # audio extraction / mp4 remux. Verified: nothing imports cv2. Excluding
              # it is a pure dead-weight removal with no functionality loss.
              'cv2', 'opencv', 'opencv-python',
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
