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
from datetime import datetime

logger = logging.getLogger(__name__)

# PowerPoint SaveAs format constant
PP_SAVE_AS_PDF = 32


class PowerPointToPDF:
    def __init__(self, error_log_path: Path = None):
        self.error_log_path = error_log_path
        self.app = None

    def __enter__(self):
        if sys.platform == 'darwin':
            return self  # AppleScript path, no COM needed
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            self.app = win32com.client.DispatchEx("PowerPoint.Application")
            try:
                self.app.Visible = False
                self.app.DisplayAlerts = False
            except Exception:
                pass  # Ignore Office 365 restriction
        except ImportError:
            logger.warning("pywin32 not installed or not on Windows. PowerPoint conversion disabled.")
        except Exception as e:
            logger.warning(f"COM Initialization failed: {e}")
        return self

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

    def _convert_applescript_pptx(self, src: Path, dst: Path) -> bool:
        """Convert a PowerPoint file to PDF via AppleScript on macOS."""
        posix_src = str(src.resolve()).replace('"', '\\"')
        posix_dst = str(dst.resolve()).replace('"', '\\"')
        script = f'''
            tell application "Microsoft PowerPoint"
                open POSIX file "{posix_src}"
                set theDoc to active presentation
                save theDoc in POSIX file "{posix_dst}" as save as PDF
                close theDoc saving no
            end tell
        '''
        return self._convert_applescript(src, dst, "PowerPoint", script)

    def convert(self, pptx_path: str | Path) -> str | None:
        pptx_path = Path(pptx_path)
        abs_pptx = str(pptx_path.resolve().absolute())
        pdf_path = pptx_path.with_suffix('.pdf')
        abs_pdf = str(pdf_path.resolve().absolute())

        # macOS: AppleScript bridge
        if sys.platform == 'darwin':
            if self._convert_applescript_pptx(pptx_path, pdf_path):
                try:
                    pptx_path.unlink()
                except OSError as e:
                    logger.warning(f"Converted to PDF but could not delete original: {pptx_path} — {e}")
                logger.info(f"Converted: {pptx_path.name} → {pdf_path.name}")
                return abs_pdf
            _log_conversion_error(
                self.error_log_path, pptx_path.name,
                "AppleScript conversion failed (is Microsoft PowerPoint installed?)"
            )
            return None

        # Windows: COM automation
        if self.app is None:
            return None
            
        logger.debug(f"[COM Converter] Attempting to convert: {abs_pptx}")
        presentation = None
        
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

            # Verify the PDF was actually created
            if not pdf_path.exists():
                _log_conversion_error(
                    self.error_log_path,
                    pptx_path.name,
                    "PowerPoint reported success but PDF file was not found on disk."
                )
                return None

            # Delete the original PPTX
            try:
                pptx_path.unlink()
            except OSError as e:
                logger.warning(f"Converted to PDF but could not delete original: {pptx_path} — {e}")

            logger.info(f"Converted: {pptx_path.name} → {pdf_path.name}")
            return abs_pdf

        except Exception as e:
            error_msg = str(e)
            
            if "Class not registered" in error_msg or "0x80040154" in error_msg:
                friendly_msg = "Microsoft PowerPoint is not installed on this machine."
            elif "RPC" in error_msg:
                friendly_msg = f"PowerPoint COM server error (is another instance hanging?): {error_msg}"
            else:
                friendly_msg = f"COM conversion failed: {error_msg}"

            logger.error(f"[COM Error] Failed to convert {abs_pptx}. Error: {error_msg}")
            
            _log_conversion_error(self.error_log_path, pptx_path.name, friendly_msg)

            if pdf_path.exists():
                try:
                    pdf_path.unlink()
                except OSError:
                    pass

            return None
        finally:
            if presentation is not None:
                try:
                    presentation.Close()
                except Exception:
                    pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.app:
            try:
                self.app.Quit()
            except Exception:
                pass
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

    try:
        error_log_path.mkdir(parents=True, exist_ok=True)
        with open(error_file, "a", encoding="utf-8") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] PDF Conversion Error — {filename}: {message}\n")
    except OSError as e:
        logger.warning(f"Could not write conversion error to log: {e}")
