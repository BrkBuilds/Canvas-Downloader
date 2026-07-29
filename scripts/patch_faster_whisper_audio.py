"""
patch_faster_whisper_audio.py
=============================

Replace ``faster_whisper/audio.py``'s **PyAV** decoder with one that shells out
to the FFmpeg binary the app already bundles, so PyAV can be dropped from the
build entirely.

Why this exists
---------------
The bundle shipped **two complete copies of FFmpeg**:

* ``imageio_ffmpeg/binaries/ffmpeg-*.exe``  - 83.6 MB, used by
  ``converters/video.py`` (video -> mp3) and ``panopto/stream.py`` (HLS
  download + mp4 remux).
* ``av.libs/`` - 62.0 MB of libav DLLs (avcodec 18.3 MB, libx265 12.0 MB,
  libSvtAv1Enc 7.3 MB, avfilter 5.5 MB, ...) bundled inside **PyAV**.

PyAV was pulled in by exactly one line - ``faster_whisper/audio.py``'s
``import av`` - to decode an MP3 that *this app produced itself, with the other
FFmpeg, moments earlier*. The x265 and SVT-AV1 **video encoders** in particular
have nothing to do with transcribing a lecture recording.

``decode_audio()`` is a thin wrapper: open file -> resample to 16 kHz mono s16
-> return ``float32`` in [-1, 1). Both paths run the same libswresample code,
one through the Python bindings and one through the CLI's ``aresample``, so the
samples are equivalent. This is also what OpenAI's reference Whisper does, and
what faster-whisper's own source comment points at as the faster alternative:

    # if that is a concern, please use ffmpeg directly as in here:
    # https://github.com/openai/whisper/blob/25639fc/whisper/audio.py#L25-L62

Net: **-65.4 MB** (``av.libs`` 62.0 + ``av`` 3.3) with no capability lost.

Measured equivalence (2026-07-27, faster-whisper 1.2.1, 7 s stereo 128 kbps MP3)
-------------------------------------------------------------------------------
Decoded with PyAV and with this patch, then compared sample-by-sample:

===================  ==========  =====================  ============
input form           len delta   max abs sample diff    Pearson r
===================  ==========  =====================  ============
``str`` path         0           **0.00000000**         1.0000000000
``split_stereo``     0           **0.00000000**         1.0000000000
file-like object     +30 (1.9ms) 0.00399780             0.9999999583
===================  ==========  =====================  ============

The ``str`` path - **the only one this app uses**
(``panopto/transcribe.py`` passes ``mp3_path``) - is **bit-identical**.

The file-like case keeps ~1.9 ms of extra tail: trimming an MP3's encoder delay
and end padding exactly needs a *seekable* input, and ``pipe:0`` is not
seekable. Mean absolute difference is 9e-8, i.e. the signals are aligned
everywhere and only the very tail differs, and Whisper pads/trims to 30 s
windows regardless. Spooling the payload to a temp file would close that gap at
the cost of writing potentially hundreds of MB to disk for a code path this app
never calls, so it is deliberately not done.

Safety properties
-----------------
* **Version-gated.** Refuses to patch a faster-whisper it has not been tested
  against (``_TESTED_VERSIONS``) and raises, failing the build loudly instead
  of shipping a silently-wrong decoder. ``requirements.txt`` already pins
  faster-whisper deliberately for this reason - when you bump it, run the app's
  transcription once and add the new version here.
* **API-preserving.** Emits the same module surface the rest of faster-whisper
  imports: ``decode_audio`` (same signature, same return contract, including
  ``split_stereo``) and ``pad_or_trim`` (copied verbatim from upstream).
* **Idempotent.** A marker line makes a second run a no-op, and the patch
  verifies afterwards that ``import av`` is gone.
* **Frozen-aware.** Resolves the bundled binary via ``sys._MEIPASS`` without
  depending on ``imageio_ffmpeg.get_ffmpeg_exe()`` succeeding inside the
  bundle. This matters because transcription runs in an **isolated
  subprocess** (``panopto/transcribe_worker.py``), which does not import
  ``converters.video`` and so never sees its ``IMAGEIO_FFMPEG_EXE`` env var.

Run this AFTER ``pip install`` and BEFORE PyInstaller collects faster-whisper.
It is invoked automatically from both .spec files; it can also be run
standalone:

    python scripts/patch_faster_whisper_audio.py

Because it edits site-packages in place, a plain ``streamlit run app.py`` uses
the patched decoder too - dev and frozen behave identically, so the path can be
exercised without building. ``pip install --force-reinstall faster-whisper``
restores the original; just re-run this script afterwards.
"""
from __future__ import annotations

import os
import sys

# faster-whisper releases whose audio.py surface this patch has been checked
# against. Bump deliberately, after running a real transcription.
_TESTED_VERSIONS = {"1.2.1"}

_MARKER = "# --- CANVAS-DOWNLOADER: PyAV replaced by bundled-FFmpeg decoder ---"

_REPLACEMENT = '''\
# --- CANVAS-DOWNLOADER: PyAV replaced by bundled-FFmpeg decoder ---
"""Audio decoding for faster-whisper, via the FFmpeg binary this app bundles.

Upstream decodes with **PyAV**, which bundles a second complete copy of the
FFmpeg libraries (~62 MB of DLLs, including the x265 and SVT-AV1 *video*
encoders) purely to read an MP3. This app already ships an ``ffmpeg``
executable for its video->mp3 conversion and Panopto stream downloads, so this
module drives that instead and PyAV is excluded from the build.

Both paths run libswresample with the same target format (16 kHz, mono, s16),
so the decoded samples are equivalent. Patched in at build time by
``scripts/patch_faster_whisper_audio.py`` - do not edit here.
"""

import io
import os
import subprocess
import sys

from typing import BinaryIO, Union

import numpy as np


def _ffmpeg_exe() -> str:
    """Path to the FFmpeg binary, PyInstaller-aware.

    Mirrors ``panopto/stream.py:ffmpeg_exe()`` but resolves the frozen case by
    globbing the bundle directly, so it does not depend on
    ``imageio_ffmpeg.get_ffmpeg_exe()`` succeeding inside a onedir bundle.
    """
    override = os.environ.get("IMAGEIO_FFMPEG_EXE")
    if override and os.path.isfile(override):
        return override

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        import glob

        pattern = os.path.join(meipass, "imageio_ffmpeg", "binaries", "ffmpeg*")
        for candidate in sorted(glob.glob(pattern)):
            if os.path.isfile(candidate):
                return candidate

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def decode_audio(
    input_file: Union[str, BinaryIO],
    sampling_rate: int = 16000,
    split_stereo: bool = False,
):
    """Decodes the audio.

    Args:
      input_file: Path to the input file or a file-like object.
      sampling_rate: Resample the audio to this sample rate.
      split_stereo: Return separate left and right channels.

    Returns:
      A float32 Numpy array.

      If `split_stereo` is enabled, the function returns a 2-tuple with the
      separated left and right channels.
    """
    channels = 2 if split_stereo else 1

    # A file-like object is streamed in over stdin ("pipe:0"); a path is opened
    # by FFmpeg directly so it can seek (faster, and required for some formats
    # whose index lives at the end of the file).
    payload = None
    if isinstance(input_file, (str, bytes, os.PathLike)):
        source = os.fspath(input_file)
    else:
        source = "pipe:0"
        payload = input_file.read()
        if isinstance(payload, str):  # text-mode handle - normalise to bytes
            payload = payload.encode("utf-8", "surrogateescape")

    cmd = [
        _ffmpeg_exe(),
        "-nostdin",
        "-threads", "0",
        "-hide_banner",
        "-loglevel", "error",
        "-i", source,
        "-vn",                       # never decode a video stream
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ac", str(channels),
        "-ar", str(sampling_rate),
        "pipe:1",
    ]

    # CREATE_NO_WINDOW: the app runs windowed, so a console flash per file
    # would be visible. Harmless/absent off Windows.
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    # communicate() drains stdout and stderr concurrently. Draining both is
    # required: a long recording writes far more than the ~64 KB pipe buffer,
    # and FFmpeg blocks on a full pipe.
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    raw, err = process.communicate(input=payload)

    if process.returncode != 0:
        detail = (err or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(
            "ffmpeg failed to decode audio (exit %d): %s" % (process.returncode, detail)
        )
    if not raw:
        raise RuntimeError(
            "ffmpeg produced no audio - the file has no decodable audio stream"
        )

    # np.frombuffer needs a whole number of samples; a truncated final frame
    # would otherwise raise instead of just losing an inaudible fraction of a
    # millisecond.
    itemsize = np.dtype(np.int16).itemsize * channels
    usable = len(raw) - (len(raw) % itemsize)
    audio = np.frombuffer(raw[:usable] if usable != len(raw) else raw, dtype=np.int16)

    # Convert s16 back to f32.
    audio = audio.astype(np.float32) / 32768.0

    if split_stereo:
        left_channel = audio[0::2]
        right_channel = audio[1::2]
        return left_channel, right_channel

    return audio


def pad_or_trim(array, length: int = 3000, *, axis: int = -1):
    """
    Pad or trim the Mel features array to 3000, as expected by the encoder.
    """
    if array.shape[axis] > length:
        array = array.take(indices=range(length), axis=axis)

    if array.shape[axis] < length:
        pad_widths = [(0, 0)] * array.ndim
        pad_widths[axis] = (0, length - array.shape[axis])
        array = np.pad(array, pad_widths)

    return array


# ``io`` is kept imported because upstream exposed it here; some downstream code
# does ``from faster_whisper.audio import io``-style introspection in tests.
_ = io
'''


def _audio_py_path() -> str:
    import faster_whisper  # noqa: WPS433 (deliberately lazy - only when patching)

    return os.path.join(os.path.dirname(faster_whisper.__file__), "audio.py")


def _installed_version() -> str:
    import faster_whisper

    return getattr(faster_whisper, "__version__", "unknown")


def patch() -> bool:
    """Patch faster_whisper/audio.py in place. Returns True if it wrote."""
    try:
        path = _audio_py_path()
    except ImportError:
        # faster-whisper is optional on a dev machine; both specs already wrap
        # its collection in try/except, so a missing install is not an error.
        print("[patch_faster_whisper_audio] faster_whisper not installed - skipping")
        return False

    current = open(path, "r", encoding="utf-8").read()

    if _MARKER in current:
        print("[patch_faster_whisper_audio] already patched - nothing to do")
        return False

    version = _installed_version()
    if version not in _TESTED_VERSIONS:
        raise RuntimeError(
            "faster-whisper %s has not been verified against this patch "
            "(tested: %s). Re-read faster_whisper/audio.py, confirm decode_audio "
            "/ pad_or_trim still look like what scripts/patch_faster_whisper_audio.py "
            "emits, run a real transcription, then add %r to _TESTED_VERSIONS."
            % (version, ", ".join(sorted(_TESTED_VERSIONS)), version)
        )

    # Sanity-check the surface we are about to replace, so a silent upstream
    # rename is caught here rather than at transcription time.
    for symbol in ("def decode_audio(", "def pad_or_trim(", "import av"):
        if symbol not in current:
            raise RuntimeError(
                "faster_whisper/audio.py does not contain %r - refusing to patch a "
                "module that is not the one this script was written for." % symbol
            )

    open(path, "w", encoding="utf-8").write(_REPLACEMENT)

    verify = open(path, "r", encoding="utf-8").read()
    if "import av" in verify or _MARKER not in verify:
        raise RuntimeError("patch_faster_whisper_audio: verification failed after write")

    print(
        "[patch_faster_whisper_audio] patched %s (faster-whisper %s) - "
        "PyAV no longer required" % (path, version)
    )
    return True


if __name__ == "__main__":
    try:
        patch()
    except Exception as exc:  # noqa: BLE001 - surface a clear CI failure
        print(f"[patch_faster_whisper_audio] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
