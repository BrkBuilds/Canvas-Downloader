"""
PDF Converter Utility for Canvas Downloader
Converts PowerPoint files (.pptx, .ppt) to PDF.

Windows:  Uses Win32COM (Microsoft Office PowerPoint).
macOS:    Uses AppleScript via osascript to control Microsoft PowerPoint.

Requirements:
  - Microsoft Office (PowerPoint) installed
  - Windows: pywin32 package (win32com.client, pythoncom)
  - macOS:   osascript (built-in)

Graceful degradation: If Office or pywin32/osascript is missing, conversion
silently fails and the original PowerPoint file is preserved.
"""
import os
import sys
import shutil
import logging
import subprocess
from pathlib import Path
from shared.helpers import make_long_path
from shared.helpers import path_exists
from datetime import datetime

logger = logging.getLogger(__name__)

# PowerPoint SaveAs format constant
PP_SAVE_AS_PDF = 32

# Maximum seconds to wait for a single COM conversion before killing the Office process
_COM_TIMEOUT_SECONDS = 180


def _kill_office_process(process_name: str, pid: int = 0) -> None:
    """Kill a hung Office process.  Prefers PID-targeted kill; falls back to /IM.

    Called from a watchdog timer thread when a COM conversion stalls.
    The kill unblocks the stuck COM call in the main thread by causing it
    to raise a pywintypes.com_error (RPC server unavailable).
    """
    from engine.office_pid import kill_office_pid
    kill_office_pid(pid, process_name)


class PowerPointToPDF:
    def __init__(self, error_log_path: Path = None):
        self.error_log_path = error_log_path
        self.app = None
        self._com_pid = None  # PID of the spawned POWERPNT.EXE COM process

    def __enter__(self):
        if sys.platform == 'darwin':
            return self  # AppleScript path, no COM needed
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pass
        except Exception:
            pass
        self._init_app()
        return self

    # ── COM management (self-healing, mirrors ExcelToPDF / WordToPDF) ──

    def _init_app(self):
        """Spin up a fresh PowerPoint instance and track its PID."""
        self._com_pid = None
        try:
            import win32com.client
            from engine.office_pid import snapshot_office_pids, find_new_office_pid
            _pre = snapshot_office_pids('POWERPNT.EXE')
            self.app = win32com.client.DispatchEx("PowerPoint.Application")
            # Track the PID FIRST - see the matching comment in word.py.
            # POWERPNT.EXE is already running by this line, and a COM-spawned
            # Office process is a child of DCOM/RPCSS rather than of us, so an
            # exception before this point left an orphan nothing could reach.
            # Guarded in turn: if the lookup itself failed we still want a
            # usable instance and a reachable self.app, not an abandoned process.
            try:
                self._com_pid = find_new_office_pid('POWERPNT.EXE', _pre)
            except Exception:
                self._com_pid = None
            try:
                self.app.Visible = False
                self.app.DisplayAlerts = False
            except Exception:
                pass  # Some Office 365 builds restrict these flags
            logger.debug(f"[COM] PowerPoint started with PID {self._com_pid}")
        except ImportError:
            logger.warning("pywin32 not installed or not on Windows. PowerPoint conversion disabled.")
            self.app = None
        except Exception as e:
            logger.warning(f"COM Initialization failed: {e}")
            # Quit + PID-kill whatever DispatchEx started, rather than dropping
            # the reference and leaving an orphaned POWERPNT.EXE behind.
            self._kill_app()

    def _kill_app(self):
        """Forcefully shut down the COM instance.

        Quit() alone leaks the process when the RPC channel is dead (COM Error
        -2147023174): Quit() throws and is swallowed, leaving an orphaned
        POWERPNT window. So after the graceful Quit, force-kill the tracked PID -
        but only if it is still a POWERPNT.EXE (guards PID reuse after a clean
        Quit) and only that PID (targeted, never a broad /IM that would close the
        user's own open presentations).
        """
        if self.app:
            try:
                self.app.Quit()
            except Exception:
                pass
        self.app = None
        if self._com_pid:
            try:
                from engine.office_pid import kill_office_pid, pid_is_process
                if pid_is_process(self._com_pid, 'POWERPNT.EXE'):
                    kill_office_pid(self._com_pid, 'POWERPNT.EXE')
            except Exception:
                pass
        self._com_pid = None

    def _is_alive(self) -> bool:
        """Quick COM channel health check."""
        if not self.app:
            return False
        try:
            _ = self.app.Version
            return True
        except Exception:
            return False

    def _ensure_app(self):
        """Guarantee a live COM instance, reviving if necessary."""
        if not self._is_alive():
            self._kill_app()
            self._init_app()

    # ── AppleScript bridge (macOS) ─────────────────────────────────
    @staticmethod
    def _convert_applescript(src: Path, dst: Path, app_name: str, script: str) -> bool:
        """Delegate to the shared AppleScript bridge (engine/applescript_bridge.py)."""
        from engine.applescript_bridge import run_applescript
        return run_applescript(src, dst, app_name, script)

    def _convert_applescript_pptx(self, src: Path, dst: Path) -> bool:
        """Convert a PowerPoint file to PDF via AppleScript on macOS.

        Three hard-won correctness rules baked into this script:

        1. PowerPoint's ``open`` does NOT return a usable reference, so
           ``set theDoc to open ...`` leaves theDoc undefined and the later
           ``save theDoc`` dies with -2753 ("variable theDoc is not defined").
           Re-measured 2026-08-11 on macOS 26.6: still true, in all three apps.
           We must ``open`` and then reach for ``active presentation``.
        2. The whole open→save→close runs inside ``try``; on ANY error we close
           the presentation and re-raise. Without this, a failed conversion left
           every presentation OPEN, so a batch of N failures stacked N
           presentations on top of each other in PowerPoint (which could
           exhaust memory / crash the machine - and on 2026-08-11 did).
        3. **``active presentation`` is whoever is FRONTMOST, which is not
           necessarily ours** - so both of those closes were aimed at a document
           we may never have opened, and ``saving no`` discards the user's
           unsaved edits. Every reference is therefore gated on
           ``our_document_test``, which compares the frontmost presentation's
           name with the basename we staged. See that function for the measured
           table of binding forms and why a name comparison beats every
           reference form (two of which wedge the app outright).

        PowerPoint's dictionary also has NO ``display alerts`` property (unlike
        Word/Excel) - adding ``set display alerts to false`` is a -2740 COMPILE
        error. Do not re-add it.
        """
        from engine.applescript_bridge import (
            OFFICE_WRONG_DOC_ERRNO, _as_posix, office_container_stage,
            our_document_test,
        )
        with office_container_stage(src, dst, "PowerPoint") as (s_src, s_dst):
            posix_src = _as_posix(s_src)
            posix_dst = _as_posix(s_dst)
            ours = our_document_test("PowerPoint", s_src.name)
            script = f'''
                tell application "Microsoft PowerPoint"
                    try
                        open POSIX file "{posix_src}"
                        if not {ours} then
                            error "the frontmost presentation is not the one Canvas Downloader opened" number {OFFICE_WRONG_DOC_ERRNO}
                        end if
                        set theDoc to active presentation
                        save theDoc in POSIX file "{posix_dst}" as save as PDF
                        close theDoc saving no
                    on error errMsg number errNum
                        try
                            if {ours} then close active presentation saving no
                        end try
                        error errMsg number errNum
                    end try
                end tell
            '''
            return self._convert_applescript(s_src, s_dst, "PowerPoint", script)

    def convert(self, pptx_path: str | Path, dst: str | Path | None = None) -> str | None:
        pptx_path = Path(pptx_path)
        # H-7: honour an explicit target (ownership-resolved by the caller);
        # default keeps the historical same-stem behavior.
        pdf_path = Path(dst) if dst is not None else pptx_path.with_suffix('.pdf')

        # macOS: AppleScript bridge
        if sys.platform == 'darwin':
            if self._convert_applescript_pptx(pptx_path, pdf_path):
                # Prove the PDF before deleting the user's only copy - the same
                # gate the COM branch below applies. run_applescript's success
                # test is `dst.exists()`, and this converter's own history is
                # the reason that is not enough: PowerPoint used to be the one
                # that tested exists(), which "is better but still passes a
                # 0-byte stub".
                from converters.verify import pdf_looks_real
                _ok, _why = pdf_looks_real(pdf_path)
                if not _ok:
                    logger.error(
                        f"[AppleScript] PowerPoint reported success for "
                        f"{pptx_path.name} but {_why}; keeping the original."
                    )
                    return None
                try:
                    Path(make_long_path(pptx_path)).unlink()
                except OSError as e:
                    logger.warning(f"Converted to PDF but could not delete original: {pptx_path} - {e}")
                logger.info(f"Converted: {pptx_path.name} → {pdf_path.name}")
                return str(pdf_path.resolve().absolute())
            from engine.applescript_bridge import get_last_error
            _last = get_last_error()
            _log_conversion_error(
                self.error_log_path, pptx_path.name,
                _last[1] if _last else "AppleScript conversion failed (unknown error)"
            )
            return None

        # Windows: COM automation with path shadowing
        self._ensure_app()
        if self.app is None:
            return None

        import threading as _th
        from shared.helpers import office_safe_path

        with office_safe_path(pptx_path, dst=pdf_path) as (safe_src, safe_pdf, true_pdf):
            abs_pptx = str(safe_src.resolve().absolute())
            abs_pdf = str(safe_pdf.resolve().absolute())

            logger.debug(f"[COM Converter] Attempting to convert: {abs_pptx}")
            presentation = None
            _timed_out = _th.Event()
            _pid = self._com_pid  # capture now; _init_app may clear it on self-heal

            def _on_timeout():
                _timed_out.set()
                logger.error(
                    f"[COM Timeout] PowerPoint hung >{_COM_TIMEOUT_SECONDS}s "
                    f"on {pptx_path.name}. Killing PID {_pid or 'unknown'}."
                )
                _kill_office_process('POWERPNT.EXE', pid=_pid or 0)

            _timer = _th.Timer(_COM_TIMEOUT_SECONDS, _on_timeout)
            _timer.start()
            try:
                # Open presentation
                presentation = self.app.Presentations.Open(
                    abs_pptx,
                    ReadOnly=True,
                    Untitled=False,
                    WithWindow=False
                )

                # Save as PDF
                presentation.SaveAs(abs_pdf, PP_SAVE_AS_PDF)
                presentation.Close()
                presentation = None
                _timer.cancel()

                # Verify the PDF was actually created (at the safe path).
                # exists() alone passes a 0-byte stub, and the next statement
                # DELETES the user's original - so require a real PDF.
                from converters.verify import pdf_looks_real
                _ok, _why = pdf_looks_real(safe_pdf)
                if not _ok:
                    _log_conversion_error(
                        self.error_log_path,
                        pptx_path.name,
                        f"PowerPoint reported success but {_why}. The original file was kept."
                    )
                    return None

                # Delete the original PPTX (from the true long path)
                try:
                    Path(make_long_path(pptx_path)).unlink()
                except OSError as e:
                    logger.warning(f"Converted to PDF but could not delete original: {pptx_path} - {e}")

                logger.info(f"Converted: {pptx_path.name} → {pdf_path.name}")
                # Return the true long-path PDF location (context manager moves it back)
                return str(true_pdf.resolve().absolute())

            except Exception as e:
                _timer.cancel()
                error_msg = str(e)

                if _timed_out.is_set():
                    friendly_msg = f"Conversion timed out after {_COM_TIMEOUT_SECONDS}s (PowerPoint stopped responding)"
                elif "Class not registered" in error_msg or "0x80040154" in error_msg:
                    friendly_msg = "Microsoft PowerPoint is not installed on this machine."
                elif "RPC" in error_msg:
                    friendly_msg = f"PowerPoint COM server error (is another instance hanging?): {error_msg}"
                else:
                    friendly_msg = f"COM conversion failed: {error_msg}"

                logger.error(f"[COM Error] Failed to convert {abs_pptx}. Error: {error_msg}")
                _log_conversion_error(self.error_log_path, pptx_path.name, friendly_msg)

                # Clean up partial PDF at the safe path (if any)
                if path_exists(safe_pdf):
                    try:
                        Path(make_long_path(safe_pdf)).unlink()
                    except OSError:
                        pass

                # SELF-HEAL: assume the COM channel is dead so the next file
                # gets a fresh instance (mirrors WordToPDF / ExcelToPDF pattern).
                self._kill_app()
                self._init_app()

                return None
            finally:
                _timer.cancel()
                if presentation is not None:
                    try:
                        presentation.Close()
                    except Exception:
                        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._kill_app()
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _log_conversion_error(error_log_path: Path | None, filename: str, message: str):
    """Append a conversion error to the download_errors.txt log."""
    logger.warning(f"PDF conversion failed for {filename}: {message}")

    if error_log_path is None:
        return

    error_log_path = Path(error_log_path)
    error_file = error_log_path / "download_errors.txt"

    from shared.helpers import _err_log_lock
    try:
        Path(make_long_path(error_log_path)).mkdir(parents=True, exist_ok=True)
        with _err_log_lock:
            with open(make_long_path(error_file), "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] PDF Conversion Error - {filename}: {message}\n")
    except OSError as e:
        logger.warning(f"Could not write conversion error to log: {e}")
