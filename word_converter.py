import sys
import logging
import subprocess
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
        """Spin up a fresh Word instance."""
        try:
            import win32com.client
            self.app = win32com.client.DispatchEx("Word.Application")
            try:
                self.app.Visible = False
            except Exception:
                pass
            self.app.DisplayAlerts = False
        except ImportError:
            logger.warning("pywin32 not installed or not on Windows. Word conversion disabled.")
            self.app = None
        except Exception as e:
            logger.error(f"[COM] Word init failed: {e}")
            self.app = None

    def _kill_app(self):
        """Forcefully shut down the COM instance."""
        if self.app:
            try:
                self.app.Quit()
            except Exception:
                pass
        self.app = None

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
        """Run an AppleScript via osascript to convert a file to PDF."""
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                logger.error(f"[AppleScript] {app_name} failed: {result.stderr.strip()}")
                return False
            return dst.exists()
        except FileNotFoundError:
            logger.error("[AppleScript] osascript not found (not on macOS?)")
            return False
        except subprocess.TimeoutExpired:
            logger.error(f"[AppleScript] {app_name} conversion timed out after 120s")
            return False
        except Exception as e:
            logger.error(f"[AppleScript] {app_name} error: {e}")
            return False

    def _convert_applescript_word(self, src: Path, dst: Path) -> bool:
        """Convert a Word document to PDF via AppleScript on macOS."""
        posix_src = str(src.resolve()).replace('"', '\\"')
        posix_dst = str(dst.resolve()).replace('"', '\\"')
        script = f'''
            tell application "Microsoft Word"
                set display alerts to wdAlertsNone
                open POSIX file "{posix_src}"
                set theDoc to active document
                save as theDoc file name POSIX file "{posix_dst}" file format format PDF
                close theDoc saving no
            end tell
        '''
        return self._convert_applescript(src, dst, "Word", script)

    # ── conversion ─────────────────────────────────────────────────
    def convert(self, doc_path: str | Path) -> str | None:
        abs_doc_path = Path(doc_path)
        abs_pdf_path = abs_doc_path.with_suffix('.pdf')

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

        from ui_helpers import office_safe_path

        with office_safe_path(abs_doc_path) as (safe_src, safe_pdf, true_pdf):
            abs_doc = str(safe_src.resolve().absolute())
            abs_pdf = str(safe_pdf.resolve().absolute())

            doc = None

            try:
                logger.debug(f"[COM Converter] Attempting to convert: {abs_doc}")

                # Open the legacy document
                doc = self.app.Documents.Open(abs_doc, ReadOnly=True, Visible=False)

                # Save as PDF (17 is wdFormatPDF)
                doc.SaveAs(abs_pdf, FileFormat=17)

                # Close original
                doc.Close(SaveChanges=0)
                doc = None

                # Delete the original legacy file (from the true long path)
                abs_doc_path.unlink(missing_ok=True)

                # Return the true long-path PDF location (context manager moves it back)
                return str(true_pdf.resolve().absolute())

            except Exception as e:
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

