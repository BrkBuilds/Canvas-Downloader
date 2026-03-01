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

import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# PowerPoint SaveAs format constant
PP_SAVE_AS_PDF = 32


def convert_pptx_to_pdf(pptx_path: Path, error_log_path: Path = None) -> Path | None:
    """
    Convert a PowerPoint file to PDF using Win32COM.

    Args:
        pptx_path: Absolute path to the .pptx/.ppt file.
        error_log_path: Directory where download_errors.txt lives (for logging failures).

    Returns:
        Path to the new PDF file on success, or None on failure.
        On failure, the original .pptx file is preserved.
    """
    pptx_path = Path(pptx_path)
    if not pptx_path.exists():
        logger.warning(f"PPTX file not found for conversion: {pptx_path}")
        return None

    # Task 1: FORCE ABSOLUTE PATHS
    abs_pptx = str(pptx_path.resolve().absolute())
    abs_pdf = str(pptx_path.with_suffix('.pdf').resolve().absolute())
    pdf_path = Path(abs_pdf)
    
    # Add a terminal print so we know the function was actually called
    print(f"[COM Converter] Attempting to convert: {abs_pptx}")

    # --- Attempt COM conversion ---
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        _log_conversion_error(
            error_log_path,
            pptx_path.name,
            "pywin32 is not installed. Install with: pip install pywin32"
        )
        return None

    powerpoint = None
    presentation = None
    try:
        pythoncom.CoInitialize()

        powerpoint = win32com.client.Dispatch("PowerPoint.Application")
        try:
            powerpoint.Visible = False
            powerpoint.DisplayAlerts = False
        except Exception:
            pass # Ignore Office 365 restriction, fallback to default visibility

        # Open presentation (use absolute path string for COM)
        presentation = powerpoint.Presentations.Open(
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
                error_log_path,
                pptx_path.name,
                "PowerPoint reported success but PDF file was not found on disk."
            )
            return None

        # Delete the original PPTX
        try:
            pptx_path.unlink()
        except OSError as e:
            logger.warning(f"Converted to PDF but could not delete original: {pptx_path} — {e}")
            # PDF was created successfully, so we still return it

        logger.info(f"Converted: {pptx_path.name} → {pdf_path.name}")
        return pdf_path

    except Exception as e:
        error_msg = str(e)

        # Common error: PowerPoint is not installed
        if "Class not registered" in error_msg or "0x80040154" in error_msg:
            friendly_msg = "Microsoft PowerPoint is not installed on this machine."
        elif "RPC" in error_msg:
            friendly_msg = f"PowerPoint COM server error (is another instance hanging?): {error_msg}"
        else:
            friendly_msg = f"COM conversion failed: {error_msg}"

        # Task 3: Improve Error Logging - Print explicitly to terminal
        print(f"[COM Error] Failed to convert {abs_pptx}. Error: {error_msg}")
        
        _log_conversion_error(error_log_path, pptx_path.name, friendly_msg)

        # Clean up partial PDF if it was created
        if pdf_path.exists():
            try:
                pdf_path.unlink()
            except OSError:
                pass

        return None

    finally:
        # Ensure COM objects are released even on error
        try:
            if presentation is not None:
                presentation.Close()
        except Exception:
            pass
        try:
            if powerpoint is not None:
                powerpoint.Quit()
        except Exception:
            pass
        try:
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
