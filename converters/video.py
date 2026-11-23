import sys
import os
import logging
import subprocess
from pathlib import Path
from shared.helpers import make_long_path, path_exists
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# PyInstaller FFmpeg fix - wrapped in try/except: get_ffmpeg_exe() raises if the
# binary is missing from the bundle, and we don't want a module-level crash.
if getattr(sys, 'frozen', False):
    try:
        import imageio_ffmpeg
        ffmpeg_name = os.path.basename(imageio_ffmpeg.get_ffmpeg_exe())
        os.environ["IMAGEIO_FFMPEG_EXE"] = os.path.join(sys._MEIPASS, "imageio_ffmpeg", "binaries", ffmpeg_name)
    except Exception as _ffmpeg_err:
        logging.getLogger(__name__).warning(f"Could not locate bundled FFmpeg binary: {_ffmpeg_err}")

try:
    # MoviePy v2.x
    from moviepy import VideoFileClip
except ImportError:
    # Fallback for MoviePy v1.x (just in case)
    from moviepy.editor import VideoFileClip

logger = logging.getLogger(__name__)

_CLOSE_TIMEOUT_SECONDS = 10  # Max wait for FFmpeg subprocess cleanup

# Floor for "this is really an MP3, not a stub", checked before the source VIDEO
# is deleted. One second of 128 kbps audio is ~16 KB, so 1 KB is far below any
# real extraction while still catching the empty/truncated writes that matter.
# Erring low is deliberate: a false negative merely keeps a video the user
# already has, a false positive deletes it.
_MIN_AUDIO_BYTES = 1024


def _safe_close(clip, label="clip"):
    """Close a moviepy clip with a timeout guard against FFmpeg hangs.

    moviepy's close() internally calls subprocess.Popen.communicate() on
    the FFmpeg process.  If FFmpeg hangs (e.g. corrupt video with no EOF),
    communicate() blocks indefinitely.  This wrapper runs close() inside a
    thread pool and abandons it after _CLOSE_TIMEOUT_SECONDS.
    """
    def _do_close():
        try:
            clip.close()
        except Exception:
            pass

    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(_do_close)
    try:
        future.result(timeout=_CLOSE_TIMEOUT_SECONDS)
    except FuturesTimeoutError:
        logger.warning(
            f"moviepy {label}.close() timed out after "
            f"{_CLOSE_TIMEOUT_SECONDS}s - abandoning hung FFmpeg process and forcing termination"
        )
        try:
            import psutil

            def _terminate_proc(proc):
                if proc and proc.pid:
                    try:
                        parent = psutil.Process(proc.pid)
                        for child in parent.children(recursive=True):
                            try:
                                child.kill()
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                        try:
                            parent.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    except Exception:
                        pass

            if hasattr(clip, 'reader') and hasattr(clip.reader, 'proc'):
                _terminate_proc(clip.reader.proc)
            if hasattr(clip, 'audio') and hasattr(clip.audio, 'reader') and hasattr(clip.audio.reader, 'proc'):
                _terminate_proc(clip.audio.reader.proc)
        except ImportError:
            logger.warning(
                "psutil not available - cannot force-kill hung FFmpeg process. "
                "It may remain as an orphan until the application exits."
            )
    except Exception:
        pass
    finally:
        if sys.version_info >= (3, 9):
            pool.shutdown(wait=False, cancel_futures=True)
        else:
            pool.shutdown(wait=False)


def convert_video_to_mp3(video_path: str | Path, dst: str | Path | None = None) -> str | None:
    abs_video = str(Path(video_path).resolve().absolute())
    # H-7: honour an explicit target (ownership-resolved by the caller).
    _mp3_target = Path(dst) if dst is not None else Path(video_path).with_suffix('.mp3')
    abs_mp3 = str(_mp3_target.resolve().absolute())
    
    video_clip = None
    conversion_success = False
    try:
        video_clip = VideoFileClip(abs_video)
        
        # Check if the video actually has an audio track
        if video_clip.audio is None:
            _safe_close(video_clip, "video")
            video_clip = None
            return None
            
        # Extract audio and write to mp3. logger=None prevents console spam.
        video_clip.audio.write_audiofile(abs_mp3, logger=None)

        # PROVE the MP3 before the `finally` below deletes the video.
        #
        # `conversion_success` used to be set the instant write_audiofile
        # RETURNED, and nothing looked at the result. write_audiofile drives
        # ffmpeg through a pipe; it can return without having produced usable
        # audio, and the file it leaves behind is then 0 bytes or a stub. The
        # thing deleted on that evidence is a lecture VIDEO - the largest and
        # least replaceable artifact this app handles, and for a Panopto
        # recording it may not be re-downloadable at all.
        #
        # Verified here rather than in the `finally`, because by the time the
        # finally runs this function has already RETURNED abs_mp3 - the caller
        # would record a success and repoint the manifest at a file that is not
        # there. Returning None instead leaves conversion_success False, so the
        # video is kept and the caller reports an honest failure.
        from converters.verify import file_has_content
        _ok, _why = file_has_content(abs_mp3, min_bytes=_MIN_AUDIO_BYTES, what="MP3")
        if not _ok:
            logger.error(
                f"Audio extraction reported success for {Path(abs_video).name} "
                f"but {_why}; keeping the original video."
            )
            try:
                Path(make_long_path(abs_mp3)).unlink(missing_ok=True)   # drop the stub
            except OSError:
                pass
            return None

        conversion_success = True
        return abs_mp3

    except Exception as e:
        logger.error(f"Failed to convert video {abs_video}: {e}")
        # Remove any partial .mp3 that write_audiofile may have created before failing.
        try:
            Path(make_long_path(abs_mp3)).unlink(missing_ok=True)
        except Exception:
            pass
        return None
    finally:
        # Close audio reader FIRST (holds a separate FFmpeg subprocess), then
        # the video clip. Each call is isolated so a failure on the audio close
        # never prevents the video clip from being released (H-17).
        if video_clip is not None:
            try:
                if video_clip.audio is not None:
                    _safe_close(video_clip.audio, "audio")
            except Exception:
                pass
            _safe_close(video_clip, "video")
            
        # Delete original video file to save space only if extraction succeeded
        if conversion_success:
            try:
                Path(make_long_path(abs_video)).unlink(missing_ok=True)
            except Exception as cleanup_err:
                logger.warning(f"Could not delete original video {abs_video}: {cleanup_err}")


# ─────────────────────────────────────────────────────────────────────────────
# A video with NO audio track: screenshots, one PDF.
#
# A silent screen recording (macOS ReplayKit, a terminal walkthrough recorded
# without a microphone) has nothing for Video -> MP3 to extract, so it used to
# fail twice (the retry pass) and stay a .mov - and NotebookLM REJECTS a drag
# that contains one, so a "drag and drop ready" folder was not. What the
# recording carries is on SCREEN, so the AI-ready form of it is the screen.
#
# Measured 2026-10-09 on four real ReplayKit recordings (3440x1440 h264, no
# audio stream, 75-255 s):
#   * ffmpeg's own scene detector is useless here: at its usual 0.3 threshold
#     it fired 0-1 times per video, because a new terminal line is a tiny
#     fraction of the pixels. Change is measured against the LAST KEPT frame
#     instead, so many small edits accumulate until they are worth a page.
#   * a page is taken only once the screen has SETTLED (no movement since the
#     previous sample), so a scroll or a half-typed command is not captured.
#   * at a 4% change threshold: 6 / 12 / 13 / 16 pages, 2.0-5.4 MB against
#     54-124 MB of video, ~15-30 s per video. Frames are full resolution - at
#     3440 px wide the terminal text is sharp, which is the point.
# No new dependency: ffmpeg is already bundled (Panopto, moviepy) and Pillow is
# in both specs, so the build does not grow.
# ─────────────────────────────────────────────────────────────────────────────

_FRAME_SAMPLE_FPS = 2            # samples per second of video
_FRAME_ANALYSIS_SIZE = (860, 360)  # fixed: aspect is irrelevant to "did it change"
_PIXEL_DELTA = 24                # grey levels before a pixel counts as changed
_CHANGE_FRACTION = 0.04          # vs the last KEPT frame - worth a new page
_STABLE_FRACTION = 0.003         # vs the previous sample - the screen has settled
# "Has it settled?" must be far MORE sensitive than "is it different?". With one
# threshold for both, a fade from red to blue moves each pixel at most 23 grey
# levels per sample, reads as perfectly still, and a half-faded frame became a
# page (caught by test_a_screen_in_MOTION_is_not_captured_only_the_settled_one).
# 6 sits above h264's noise on a static screen and below any visible motion.
_SETTLE_PIXEL_DELTA = 6
_MAX_PAGES = 100                 # a long recording is thinned evenly, never cut off
_PROBE_TIMEOUT_SECONDS = 60
_EXTRACT_TIMEOUT_SECONDS = 1800
# The packaged Windows app has no console, so a bare ffmpeg child would flash
# one on screen per call - same flag panopto/stream.py passes.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _ffmpeg() -> str:
    # The one resolver (frozen bundle, then imageio_ffmpeg, then PATH) - not a
    # third copy of it.
    from panopto.stream import ffmpeg_exe
    return ffmpeg_exe()


def has_audio_track(video_path: str | Path) -> bool | None:
    """True / False when ffmpeg can say, ``None`` when it could not read the file.

    ``None`` is NOT "no audio": the caller must then take the ordinary MP3
    path, which reports an honest failure, rather than turn an unreadable
    video into a PDF of nothing.
    """
    try:
        r = subprocess.run([_ffmpeg(), "-hide_banner", "-i", str(video_path)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=_PROBE_TIMEOUT_SECONDS,
                           creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f"Could not probe {Path(video_path).name} for audio: {e}")
        return None
    streams = [ln for ln in r.stderr.splitlines() if "Stream #" in ln]
    if any(": Audio:" in ln for ln in streams):
        return True
    if any(": Video:" in ln for ln in streams):
        return False
    return None


def _changed_fraction(a, b, pixel_delta: int = _PIXEL_DELTA) -> float:
    from PIL import ImageChops
    diff = ImageChops.difference(a, b).point(lambda v: 255 if v > pixel_delta else 0)
    return diff.histogram()[255] / (a.width * a.height)


def _keyframe_indices(video_path: str, is_cancelled=None) -> list[int] | None:
    """Indices, on the ``_FRAME_SAMPLE_FPS`` grid, of the frames worth a page.

    ``None`` means cancelled or ffmpeg failed; ``[]`` cannot happen for a file
    that decoded at all, because the first frame is always kept.
    """
    from PIL import Image
    w, h = _FRAME_ANALYSIS_SIZE
    frame_bytes = w * h
    proc = subprocess.Popen(
        [_ffmpeg(), "-loglevel", "error", "-i", str(video_path),
         "-vf", f"fps={_FRAME_SAMPLE_FPS},scale={w}:{h}",
         "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    kept: list[int] = []
    last_kept = prev = None
    pending = False
    i = 0
    try:
        while True:
            if is_cancelled is not None and is_cancelled():
                return None
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            img = Image.frombytes("L", (w, h), buf)
            if last_kept is None:
                kept.append(i)
                last_kept = img
            else:
                if not pending and _changed_fraction(img, last_kept) > _CHANGE_FRACTION:
                    pending = True
                if pending and _changed_fraction(
                        img, prev, _SETTLE_PIXEL_DELTA) < _STABLE_FRACTION:
                    kept.append(i)
                    last_kept = img
                    pending = False
            prev = img
            i += 1
        # A change that never settled (the recording ends mid-scroll) is still
        # the last thing on screen; keep the final sample rather than lose it.
        if pending and i > 0:
            kept.append(i - 1)
    finally:
        # EOF on the pipe is not the process exiting - bound the wait, then kill.
        try:
            proc.stdout.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    if proc.returncode not in (0, None) and not kept:
        return None
    if len(kept) > _MAX_PAGES:
        step = (len(kept) - 1) / (_MAX_PAGES - 1)
        kept = sorted({kept[round(k * step)] for k in range(_MAX_PAGES)})
    return kept or None


def convert_silent_video_to_pdf(video_path: str | Path, dst: str | Path | None = None,
                                is_cancelled=None) -> str | None:
    """Turn a video with no audio track into one PDF of its distinct screens.

    Same contract as ``convert_video_to_mp3``: returns the PDF path, or
    ``None`` with the video left exactly where it was. The video is deleted
    only after ``pdf_looks_real`` has proven the PDF - it is the larger file
    and the one the user cannot get back if Canvas has since dropped it.
    """
    import shutil
    import tempfile
    from PIL import Image
    from converters.verify import pdf_looks_real

    abs_video = str(Path(video_path).resolve().absolute())
    target = Path(dst) if dst is not None else Path(video_path).with_suffix('.pdf')
    abs_pdf = str(target.resolve().absolute())
    part = abs_pdf + ".part"
    name = Path(abs_video).name
    work = tempfile.mkdtemp(prefix="cd_frames_")
    try:
        idx = _keyframe_indices(abs_video, is_cancelled)
        if not idx:
            logger.error(f"Could not read any frames from {name}; keeping the video.")
            return None

        # ONE pass, selecting by index on the SAME sample grid the analysis
        # used. Seeking to a timestamp instead can land just past the end of
        # the stream and return nothing - measured on the last page of one of
        # the four recordings above.
        select = "+".join(f"eq(n\\,{n})" for n in idx)
        try:
            r = subprocess.run(
                [_ffmpeg(), "-loglevel", "error", "-i", abs_video,
                 "-vf", f"fps={_FRAME_SAMPLE_FPS},select='{select}'",
                 "-fps_mode", "vfr", "-q:v", "4",
                 os.path.join(work, "%05d.jpg")],
                timeout=_EXTRACT_TIMEOUT_SECONDS, capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                creationflags=_NO_WINDOW)
        except (OSError, subprocess.SubprocessError) as e:
            logger.error(f"Could not extract screenshots from {name}: {e}")
            return None
        if r.returncode != 0:
            # ffmpeg's OWN words, not just the exit code. Seen once on
            # 2026-10-09 as exit 4294967295 (-1) with nothing else to go on,
            # under a concurrent test run; six repeats all succeeded and the
            # retry pass recovered the file, so the cause is still unknown.
            logger.error(f"Could not extract screenshots from {name}: ffmpeg "
                         f"exited {r.returncode}: {r.stderr.strip()[-500:] or '(no output)'}")
            return None
        frames = sorted(Path(work).glob("*.jpg"))
        if not frames:
            logger.error(f"No screenshots came out of {name}; keeping the video.")
            return None

        # Page by page with `append`, so memory holds ONE full-resolution frame
        # at a time rather than every page of the document at once.
        part_lp = make_long_path(part)
        for n, frame in enumerate(frames):
            if is_cancelled is not None and is_cancelled():
                return None
            with Image.open(frame) as im:
                im.convert("RGB").save(part_lp, "PDF", resolution=150.0,
                                       append=n > 0)

        _ok, _why = pdf_looks_real(part)
        if not _ok:
            logger.error(f"Screenshot PDF for {name} is not usable ({_why}); "
                         f"keeping the video.")
            return None
        os.replace(part_lp, make_long_path(abs_pdf))
        _ok, _why = pdf_looks_real(abs_pdf)
        if not _ok:
            logger.error(f"Screenshot PDF for {name} did not land ({_why}); "
                         f"keeping the video.")
            return None
    except Exception as e:
        logger.error(f"Failed to turn silent video {name} into screenshots: {e}",
                     exc_info=True)
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)
        try:
            Path(make_long_path(part)).unlink(missing_ok=True)
        except OSError:
            pass

    logger.info(f"{name} has no audio track - saved {len(frames)} screenshot "
                f"page(s) as {Path(abs_pdf).name}.")
    try:
        Path(make_long_path(abs_video)).unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"Could not delete original video {abs_video}: {e}")
    return abs_pdf
