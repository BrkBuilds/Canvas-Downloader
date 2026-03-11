"""
PDF Converter Utility for Canvas Downloader
Converts PowerPoint files (.pptx, .ppt) to PDF using Win32COM (Microsoft Office).

Requirements:
  - Windows OS
  - Microsoft Office (PowerPoint) installed
  - pywin32 package (win32com.client, pythoncom)

Graceful degradation: If Office or pywin32 is missing, conversion silently fails
and the original PowerPoint file is preserved.
"""
import os
import shutil
import logging
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
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            self.app = win32com.client.DispatchEx("PowerPoint.Application")
            try:
                self.app.Visible = False
                self.app.DisplayAlerts = False
            except Exception:
                pass # Ignore Office 365 restriction
        except Exception as e:
            logger.warning(f"COM Initialization failed: {e}")
        return self

    def convert(self, pptx_path: str | Path) -> str | None:
        if self.app is None:
            return None
            
        pptx_path = Path(pptx_path)
        abs_pptx = str(pptx_path.resolve().absolute())
        pdf_path = pptx_path.with_suffix('.pdf')
        abs_pdf = str(pdf_path.resolve().absolute())
        
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
