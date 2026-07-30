"""
build_excludes.py
=================

The **single source of truth** for what PyInstaller must not bundle, shared by
``Canvas_Downloader.spec`` and ``Canvas_Downloader_macOS.spec``.

It lives in one file on purpose. The two specs are near-duplicates, and a
trimming fix applied to only one of them is invisible in review and ships a
fat build on the other platform. Both load this module the same way they
already load ``patch_streamlit_webkit``.

Why any of this is needed
-------------------------
Both specs call ``collect_all()`` on ~20 packages. ``collect_all`` =
``collect_submodules`` + ``collect_data_files`` + ``collect_dynamic_libs``, and
``collect_submodules`` walks **every** submodule - including ``tests/``, CLI
entry points and optional integrations - forcing each in as a hidden import.
PyInstaller then follows *their* imports transitively. Measured on the 2.0.1
Windows build (462.8 MB installed, 5,865 files, a 29.2 MB PYZ holding **5,322
modules**), three chains accounted for most of the waste. Read off the build's
own ``xref-Canvas_Downloader.html`` import graph:

1. ``huggingface_hub`` - used ONLY to download Whisper model weights::

       huggingface_hub._oauth              -> fastapi -> pydantic + pydantic_core
       huggingface_hub.inference._mcp      -> mcp -> pydantic_settings
                                                  -> azure.core -> opentelemetry -> grpc
                                                  -> google.auth -> cryptography
                                                  -> uvicorn -> websockets
       huggingface_hub.repocard            -> jinja2

   grpc alone is 10.1 MB, cryptography 8.6 MB, pydantic_core 5.2 MB.

2. Test suites dragging in build tooling::

       psutil.tests            -> pip -> pip._vendor.cachecontrol.caches.redis_cache -> redis
       numpy.typing.tests      -> _pytest
       numpy._pyinstaller      -> PyInstaller itself

3. ``webview.http`` -> ``bottle`` -> its optional server adapters::

       bottle -> gevent (274 modules) -> dnspython + the stdlib `test` package

Plus ``bs4.builder._lxml`` -> **lxml** (6.6 MB; this app always passes
``"html.parser"``), ``win32com.client.makepy`` -> **win32ui** ->
Pythonwin/mfc140u.dll (6.4 MB; this app uses late-binding COM only - there is
no ``gencache``/``EnsureDispatch`` anywhere), ``streamlit.error_util`` ->
rich -> **pygments** (335 modules), and ``streamlit.git_util`` -> **GitPython**.

Two mechanisms, and the order matters
-------------------------------------
``lean_filter()`` is the *root-cause* fix - it stops junk becoming a hidden
import at all. ``excludes_for()`` is the belt-and-braces that severs chains
reached through genuine imports (bottle -> gevent), which no filter can catch.

``lean_filter`` is safe by construction: ``filter_submodules`` only controls
what is **force-added**, it does not make a module unavailable. Anything a real
import actually reaches is still collected by normal graph analysis.
``excludes_for`` is the blunt instrument, so every entry there is justified
below and was validated before being added.

How this list was validated (2026-07-27)
----------------------------------------
Not by reasoning - by blocking every candidate with a ``sys.meta_path`` finder
that raises ``ImportError``, then running the real code paths: Streamlit +
``ForwardMsg_pb2``, all 13 app modules, canvasapi, BeautifulSoup with
``html.parser`` **and** ``.select()``, pywebview + ``webview.http``, keyring
(WinVaultKeyring), win11toast, win32com, moviepy + PIL,
``huggingface_hub.snapshot_download`` over plain HTTPS, and a real end-to-end
faster-whisper transcription. 11/11 passed.

That harness is also what caught the one genuinely dangerous idea in the whole
exercise: the ``huggingface_hub`` chain reaches ``google.auth``, so ``google``
looks excludable - but **Streamlit needs ``google.protobuf``** for every
``ForwardMsg`` it sends. Excluding the ``google`` namespace would have bricked
the app. Only ``google.auth`` / ``google.oauth2`` are dead. Do not "simplify"
those two entries back into a bare ``google``.

Deliberately NOT excluded
-------------------------
* ``onnxruntime`` (37.3 MB) - the Silero VAD backend. Dropping it is a live
  option (``panopto/transcribe.py`` already retries with ``vad_filter=False``,
  and ``_is_vad_engine_error`` matches the ``"onnxruntime"`` in the raised
  message), but VAD skips silence, which on lecture recordings is both faster
  and the thing that stops Whisper hallucinating over long quiet stretches.
  **Decided 2026-07-27: keep it.** Quality of the premium feature beats 37 MB.
* ``moviepy`` + ``PIL`` + ``imageio`` (~6.5 MB) - ``converters/video.py`` uses
  ``VideoFileClip`` for one thing, extracting audio to MP3, which is a single
  ffmpeg invocation the codebase already knows how to make
  (``panopto/stream.py:_run_ffmpeg_download``). Replacing it would also delete
  ``_safe_close``'s ThreadPoolExecutor + psutil-kill machinery, which exists
  only because moviepy's ``close()`` blocks on ``Popen.communicate()``.
  **Deliberately declined 2026-07-27:** the ffmpeg/Panopto path cost a lot of
  debugging to get right and works; ~6.5 MB does not justify disturbing it.
  Note that PIL cannot be dropped separately - ``moviepy/video/VideoClip.py``
  imports it at module level.
* ``tkinter`` on **Windows** (7.1 MB: _tcl_data, tcl86t.dll, tk86t.dll,
  _tk_data, _tkinter.pyd) - it is the folder picker in
  ``shared/helpers.py:pick_folder``. A ctypes ``IFileOpenDialog`` with
  ``FOS_PICKFOLDERS`` would remove it, but **decided 2026-07-27: keep tk.**
  It is excluded on **macOS**, where it is pure dead weight: that branch
  returns from ``osascript`` on every path (``helpers.py:501``), so the tkinter
  import below it is unreachable.
* ``click``, ``anyio``, ``httpx``, ``cachetools``, ``tenacity``, ``tornado``,
  ``watchdog``, ``soupsieve``, ``pytz`` - all reached by code that really runs.
* UPX - rejected. The Inno installer already uses ``lzma2/ultra64`` +
  ``SolidCompression``, and UPX-then-LZMA compresses *worse* than LZMA alone,
  so it would not shrink the download at all. It also slows startup and is an
  antivirus-heuristic magnet for an installer distributed without EV signing.
* The 83.6 MB ``ffmpeg.exe`` - imageio-ffmpeg 0.5.1 ships a 61.7 MB binary
  (-22 MB), but it is FFmpeg **4.2.2** (2019). Panopto HLS delivery, modern
  AAC/HEVC and current TLS are not worth regressing to save 22 MB.
"""
from __future__ import annotations

# ── Never force-collect a submodule with one of these path components ─────────
# Catches numpy/*/tests, numpy.typing.tests (-> _pytest), psutil.tests (-> pip
# -> redis), bs4.tests, streamlit.testing, keyring.testing, numpy._pyinstaller
# (-> PyInstaller), numpy.f2py, numpy.distutils.
_JUNK_COMPONENTS = frozenset({
    "tests", "test", "testing", "conftest", "benchmarks", "benchmark",
    "_pyinstaller", "f2py", "distutils",
})

# ── Never force-collect these subtrees (dev tooling / server surfaces) ────────
_JUNK_PREFIXES = (
    # onnxruntime's model-authoring tooling. The inference path this app uses is
    # onnxruntime.capi + InferenceSession; none of these are reachable from it.
    # (onnxruntime.tools.symbolic_shape_infer is also what pulled in sympy.)
    "onnxruntime.tools",
    "onnxruntime.transformers",
    "onnxruntime.quantization",
    "onnxruntime.training",
    "onnxruntime.datasets",
    "onnxruntime.backend",
    # huggingface_hub's CLI / MCP-server / OAuth surfaces. This app calls exactly
    # one thing, snapshot_download(); these are the roots of chain 1 above.
    "huggingface_hub.inference._mcp",
    "huggingface_hub._oauth",
    "huggingface_hub.cli",
    "huggingface_hub.commands",
)


def _is_under(name: str, prefix: str) -> bool:
    """True if ``name`` IS ``prefix`` or is a submodule of it.

    Deliberately not ``str.startswith``. A raw prefix test matches on
    characters rather than on module boundaries, so ``huggingface_hub.cli``
    would also drop a sibling called ``huggingface_hub.client`` - a module
    nothing in ``_JUNK_PREFIXES`` is talking about. No installed package hits
    that today (checked across 1,784 submodules of every package the specs
    collect: zero verdict changes), which is exactly why it would have shipped
    unnoticed the day a dependency added such a name.
    """
    return name == prefix or name.startswith(prefix + ".")


def lean_filter(name: str) -> bool:
    """``filter_submodules`` predicate for ``collect_all``. True = collect it.

    Only stops a module being *force-added* as a hidden import; a module that
    something genuinely imports is still picked up by normal graph analysis.
    """
    if set(name.split(".")) & _JUNK_COMPONENTS:
        return False
    return not any(_is_under(name, p) for p in _JUNK_PREFIXES)


# ── Heavy third-party stacks this app has never used ─────────────────────────
# (Pre-existing list, unchanged. streamlit declares pandas/pyarrow/altair/pydeck
# as install deps but the app renders none of them; cv2 comes in transitively
# via moviepy's optional video effects, which this app never calls.)
_HEAVY = [
    "matplotlib", "IPython", "jupyter", "notebook", "pytest", "scipy",
    "PyQt5", "PyQt6", "PySide6", "customtkinter",
    "doctest", "pdb", "unittest", "pydoc", "curses", "sqlalchemy",
    # tkinter itself is KEPT on Windows (it is the folder picker) - only its
    # test suite goes. lean_filter cannot catch this one: tkinter is a stdlib
    # package, so it is never passed through collect_all().
    "tkinter.test",
    "pyarrow", "altair", "pydeck", "pandas", "polars", "botocore", "boto3",
    "bokeh", "plotly", "seaborn", "statsmodels", "tensorboard", "tensorflow",
    "torch", "keras", "numba", "cython", "dask", "networkx", "h5py", "sympy",
    "patsy",
    "cv2", "opencv", "opencv-python",
    "streamlit.external.langchain",
]

# ── Dead weight traced through the build's own import graph ──────────────────
_DEAD = [
    # PyAV - a SECOND complete copy of FFmpeg (62.0 MB of libav DLLs: avcodec
    # 18.3, libx265 12.0, libSvtAv1Enc 7.3, avfilter 5.5, ...). It was pulled in
    # by ONE line, faster_whisper/audio.py's `import av`, to decode an MP3 this
    # app produced itself moments earlier with the OTHER FFmpeg - the 83.6 MB
    # ffmpeg.exe it still ships for converters/video.py and panopto/stream.py.
    # scripts/patch_faster_whisper_audio.py rewrites decode_audio() to use that
    # binary; verified bit-identical (max abs diff 0.00000000, Pearson r = 1.0)
    # for the str-path input, which is the only form this app passes.
    # imageio's pyav plugin is registered lazily (imageio/config/plugins.py ->
    # importlib on demand), exactly like the already-excluded cv2 plugin.
    "av",

    # huggingface_hub 1.x optional surface - chain 1 in the module docstring.
    # NOTE: `google.auth`/`google.oauth2` and NOT bare `google` - Streamlit
    # needs google.protobuf. See the docstring; this is the one trap here.
    "mcp", "fastapi", "starlette", "uvicorn", "websockets", "sse_starlette",
    "pydantic", "pydantic_core", "pydantic_settings",
    "azure", "opentelemetry", "grpc",
    "google.auth", "google.oauth2", "google_auth_httplib2",
    "cryptography", "authlib", "itsdangerous", "jinja2", "safetensors",
    # hf_xet (6.7 MB) is a transfer accelerator gated behind
    # huggingface_hub.utils._runtime.is_xet_available(); absent -> plain HTTPS.
    "hf_xet",
    # fsspec is only reached via huggingface_hub.hf_file_system (HfFileSystem),
    # which snapshot_download() never touches.
    "fsspec",

    # bs4's optional parser backends. Every BeautifulSoup() call in this app
    # passes "html.parser" explicitly (converters/md.py:34,
    # core/canvas_logic.py:162), but bs4.builder._lxml is imported
    # unconditionally by the builder registry, dragging in lxml (6.6 MB).
    "lxml", "html5lib",

    # bottle's optional WSGI server adapters. pywebview imports bottle
    # unconditionally (webview/http.py), and bottle's adapter classes name every
    # server it supports, so modulegraph pulls gevent (274 modules) -> dnspython
    # + the stdlib `test` package. pywebview never selects the gevent adapter.
    "gevent", "dns", "eventlet", "zope",

    # Streamlit's optional niceties, both already inside try/except upstream:
    #   config.py:525 `import rich` -> pygments (335 modules)
    #   git_util.py:75 `import git` -> GitPython (the "Deploy" button)
    "rich", "pygments", "git", "gitdb", "smmap",

    # Build tooling that only ever arrived through bundled test suites
    # (psutil.tests -> pip -> redis; numpy.typing.tests -> _pytest;
    # numpy._pyinstaller -> PyInstaller). lean_filter() severs the roots; these
    # keep them out if a future dependency ships another test package.
    "pip", "redis", "_pytest", "PyInstaller",
    "setuptools", "pkg_resources",
]

# ── Platform deltas ──────────────────────────────────────────────────────────
_WINDOWS_ONLY = [
    "pync",
    # pywin32's MFC GUI: Pythonwin/mfc140u.dll 5.4 MB + win32ui.pyd 1.0 MB.
    # Reached only via win32com.client.makepy, i.e. early-binding codegen. This
    # app is late-binding throughout - no gencache/EnsureDispatch anywhere.
    "win32ui", "win32uiole", "dde",
]

_MACOS_ONLY = [
    "win32com", "win32com.client", "pythoncom", "pywintypes",
    "webview.platforms.winforms", "webview.platforms.edgechromium",
    "webview.platforms.qt", "webview.platforms.gtk",
    "win11toast", "winsound",
    # tk is the WINDOWS folder picker only. shared/helpers.py:501 takes the
    # osascript branch on Darwin and returns on every path, so the tkinter
    # import below it is unreachable in a mac build.
    "tkinter", "_tkinter",
]


def excludes_for(platform: str) -> list:
    """Full ``Analysis(excludes=...)`` list for ``'windows'`` or ``'macos'``."""
    if platform not in ("windows", "macos"):
        raise ValueError(f"unknown platform {platform!r} - expected 'windows' or 'macos'")
    extra = _WINDOWS_ONLY if platform == "windows" else _MACOS_ONLY
    return _HEAVY + _DEAD + extra


def strip_test_datas(datas):
    """Drop bundled test suites from an ``Analysis.datas`` TOC.

    ``lean_filter`` stops a test package becoming a hidden *import* - which is
    what severs the ``psutil.tests -> pip -> redis`` and
    ``numpy.typing.tests -> _pytest`` chains - but ``collect_all`` ALSO runs
    ``collect_data_files``, which copies the same ``.py`` files in again as
    **data**. They are then dead weight on disk: nothing imports them, so they
    are never even compiled.

    Measured after the import-side fix landed: 562 files / 7.29 MB still
    shipping, 6.36 MB of it numpy's test suite.

    Deliberately narrow - a file is dropped only when its destination path has a
    whole ``tests``/``test``/``testing``/``benchmarks`` **directory component**,
    or is a ``test_*.py`` / ``conftest.py``. Matching on a directory component
    (not a substring) is what keeps it from eating something like
    ``latest.json`` or a ``contest/`` package.

    Applied to ``a.datas`` AFTER ``Analysis`` in both specs. It only ever
    touches data files, never modules, so it cannot make an import fail.
    """
    junk_dirs = {"tests", "test", "testing", "benchmarks"}
    kept = []
    for entry in datas:
        dest = str(entry[0]).replace("\\", "/")
        parts = dest.split("/")
        name = parts[-1]
        if set(parts[:-1]) & junk_dirs:
            continue
        if name == "conftest.py" or (name.startswith("test_") and name.endswith(".py")):
            continue
        kept.append(entry)
    return kept
