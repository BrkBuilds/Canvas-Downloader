import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class WordToPDF:
    """Context manager for batch Word document-to-PDF conversion.

    Windows:  Uses COM automation (win32com) with self-healing.
    macOS:    Uses AppleScript via osascript to control Microsoft Word.

    Features self-healing: detects stale/crashed COM instances and restarts them mid-batch.
    """
    def __init__(self):
        self.app = None
        self._com_pid = None  # PID of the spawned WINWORD.EXE COM process
        
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
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self._kill_app()
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except Exception:
            pass

    def _init_app(self):
        """Spin up a fresh Word instance and track its PID."""
        self._com_pid = None
        try:
            import win32com.client
            from engine.office_pid import snapshot_office_pids, find_new_office_pid
            _pre = snapshot_office_pids('WINWORD.EXE')
            self.app = win32com.client.DispatchEx("Word.Application")
            try:
                self.app.Visible = False
            except Exception:
                pass
            self.app.DisplayAlerts = False
            self._com_pid = find_new_office_pid('WINWORD.EXE', _pre)
            logger.debug(f"[COM] Word started with PID {self._com_pid}")
        except ImportError:
            logger.warning("pywin32 not installed or not on Windows. Word conversion disabled.")
            self.app = None
        except Exception as e:
            logger.error(f"[COM] Word init failed: {e}")
            self.app = None

    def _kill_app(self):
        """Forcefully shut down the COM instance.

        Quit() alone leaks the process when the RPC channel is dead (COM Error
        -2147023174): Quit() throws and is swallowed, leaving an orphaned WINWORD
        window. So after the graceful Quit, force-kill the tracked PID - but only
        if it is still a WINWORD.EXE (guards PID reuse after a clean Quit) and
        only that PID (targeted, never a broad /IM that would close the user's
        own open documents).
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
                if pid_is_process(self._com_pid, 'WINWORD.EXE'):
                    kill_office_pid(self._com_pid, 'WINWORD.EXE')
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

    def _convert_applescript_word(self, src: Path, dst: Path) -> bool:
        """Convert a Word document to PDF via AppleScript on macOS.

        Mirrors the PowerPoint converter's two correctness rules:

        1. Grab ``active document`` after ``open`` rather than relying on
           ``open``'s return value (avoids the -2753 "variable not defined"
           failure mode).
        2. The whole open→save→close runs inside ``try``; on ANY error we
           ``close active document saving no`` and re-raise, so a failed
           conversion can never leave documents stacking up open in Word.

        Word's ``display alerts`` is an ENUM (none/all/messages), not a boolean,
        so ``set display alerts to false`` is wrapped in its own ``try`` - a
        coercion error there must never abort the conversion.
        """
        from engine.applescript_bridge import _as_posix, office_container_stage
        with office_container_stage(src, dst, "Word") as (s_src, s_dst):
            posix_src = _as_posix(s_src)
            posix_dst = _as_posix(s_dst)
            script = f'''
                tell application "Microsoft Word"
                    try
                        set display alerts to false
                    end try
                    try
                        open POSIX file "{posix_src}"
                        set theDoc to active document
                        save as theDoc file name POSIX file "{posix_dst}" file format format PDF
                        close theDoc saving no
                    on error errMsg number errNum
                        try
                            close active document saving no
                        end try
                        error errMsg number errNum
                    end try
                end tell
            '''
            return self._convert_applescript(s_src, s_dst, "Word", script)

    # ── conversion ─────────────────────────────────────────────────
    def convert(self, doc_path: str | Path, dst: str | Path | None = None) -> str | None:
        abs_doc_path = Path(doc_path)
        # H-7: honour an explicit target (ownership-resolved by the caller).
        abs_pdf_path = Path(dst) if dst is not None else abs_doc_path.with_suffix('.pdf')

        # Do not convert if it's already a modern .docx
        if str(abs_doc_path).lower().endswith('.docx'):
            return None

        # macOS: AppleScript bridge
        if sys.platform == 'darwin':
            if self._convert_applescript_word(abs_doc_path, abs_pdf_path):
                abs_doc_path.unlink(missing_ok=True)
                return str(abs_pdf_path.resolve())
            return None

        # Windows: COM automation with path shadowing
        self._ensure_app()
        if self.app is None:
            return None

        import threading as _th
        from shared.helpers import office_safe_path
        from engine.office_pid import kill_office_pid

        _COM_TIMEOUT_SECONDS = 180

        with office_safe_path(abs_doc_path, dst=abs_pdf_path) as (safe_src, safe_pdf, true_pdf):
            abs_doc = str(safe_src.resolve().absolute())
            abs_pdf = str(safe_pdf.resolve().absolute())

            doc = None
            _timed_out = _th.Event()
            _pid = self._com_pid  # capture before timer fires

            def _on_timeout():
                _timed_out.set()
                logger.error(
                    f"[COM Timeout] Word hung >{_COM_TIMEOUT_SECONDS}s "
                    f"on {abs_doc_path.name}. Killing PID {_pid or 'unknown'}."
                )
                kill_office_pid(_pid or 0, 'WINWORD.EXE')

            _timer = _th.Timer(_COM_TIMEOUT_SECONDS, _on_timeout)
            _timer.start()
            try:
                logger.debug(f"[COM Converter] Attempting to convert: {abs_doc}")

                # Open the legacy document
                doc = self.app.Documents.Open(abs_doc, ReadOnly=True, Visible=False)

                # Save as PDF (17 is wdFormatPDF)
                doc.SaveAs(abs_pdf, FileFormat=17)

                # Close original
                doc.Close(SaveChanges=0)
                doc = None
                _timer.cancel()

                # Delete the original legacy file (from the true long path)
                abs_doc_path.unlink(missing_ok=True)

                # Return the true long-path PDF location (context manager moves it back)
                return str(true_pdf.resolve().absolute())

            except Exception as e:
                _timer.cancel()
                if _timed_out.is_set():
                    logger.error(
                        f"[COM Timeout] Word conversion timed out after "
                        f"{_COM_TIMEOUT_SECONDS}s for {abs_doc_path.name}"
                    )
                else:
                    logger.error(f"[COM Error] Failed to convert Word doc {abs_doc}: {e}")

                # Close document if error happened after open
                if doc is not None:
                    try:
                        doc.Close(SaveChanges=0)
                    except Exception:
                        pass

                # SELF-HEAL: assume the COM channel is dead
                self._kill_app()
                self._init_app()

                return None
            finally:
                _timer.cancel()

