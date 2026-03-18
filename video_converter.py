import sys
import os
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# PyInstaller FFmpeg fix
if getattr(sys, 'frozen', False):
    import imageio_ffmpeg
    ffmpeg_name = os.path.basename(imageio_ffmpeg.get_ffmpeg_exe())
    os.environ["IMAGEIO_FFMPEG_EXE"] = os.path.join(sys._MEIPASS, "imageio_ffmpeg", "binaries", ffmpeg_name)

try:
    # MoviePy v2.x
    from moviepy import VideoFileClip
except ImportError:
    # Fallback for MoviePy v1.x (just in case)
    from moviepy.editor import VideoFileClip

logger = logging.getLogger(__name__)

_CLOSE_TIMEOUT_SECONDS = 10  # Max wait for FFmpeg subprocess cleanup


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
            f"{_CLOSE_TIMEOUT_SECONDS}s — abandoning hung FFmpeg process and forcing termination"
        )
        import psutil
        def _terminate_proc(proc):
            if proc and proc.pid:
                try:
                    import psutil
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
    except Exception:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def convert_video_to_mp3(video_path: str | Path) -> str | None:
    abs_video = str(Path(video_path).resolve().absolute())
    abs_mp3 = str(Path(video_path).with_suffix('.mp3').resolve().absolute())
    
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
        
        conversion_success = True
        return abs_mp3
        
    except Exception as e:
        logger.error(f"Failed to convert video {abs_video}: {e}")
        return None
    finally:
        # CRITICAL: Close audio reader FIRST (holds separate FFmpeg subprocess),
        # then close the video clip to release all file locks and processes.
        # Both use _safe_close to prevent indefinite hangs on corrupt videos.
        if video_clip is not None:
            if video_clip.audio:
                _safe_close(video_clip.audio, "audio")
            _safe_close(video_clip, "video")
            
        # Delete original video file to save space only if extraction succeeded
        if conversion_success:
            try:
                Path(abs_video).unlink(missing_ok=True)
            except Exception as cleanup_err:
                logger.warning(f"Could not delete original video {abs_video}: {cleanup_err}")
