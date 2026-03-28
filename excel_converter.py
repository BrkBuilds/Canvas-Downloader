import csv
import io
import os
import sys
import time
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class ExcelToPDF:
    """Context manager for batch Excel-to-PDF conversion.

    Windows:  Uses COM automation (win32com) with self-healing.
    macOS:    Uses AppleScript via osascript to control Microsoft Excel.

    Design: One COM instance is shared across the batch for speed, but
    self-heals (Quit + re-init) if any individual file crashes the RPC
    channel.  A proactive health check at the start of each convert()
    detects stale COM objects before they cause failures.
    """

    def __init__(self):
        self.app = None

    # ── lifecycle ──────────────────────────────────────────────────
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

    # ── COM management ─────────────────────────────────────────────
    def _init_app(self):
        """Spin up a fresh, locked-down Excel instance."""
        try:
            import win32com.client
            self.app = win32com.client.DispatchEx("Excel.Application")
            self.app.Visible = False
            self.app.DisplayAlerts = False
            self.app.EnableEvents = False          # block VBA macros
            try:
                self.app.AutomationSecurity = 3    # msoAutomationSecurityForceDisable
            except Exception:
                pass
            try:
                self.app.Interactive = False        # suppress "Publishing…" dialog
            except Exception:
                pass
        except ImportError:
            logger.warning("pywin32 not installed or not on Windows. Excel conversion disabled.")
            self.app = None
        except Exception as e:
            logger.error(f"[COM] Excel init failed: {e}")
            self.app = None

    def _kill_app(self):
        """Forcefully shut down the COM instance (safe to call anytime)."""
        if self.app:
            try:
                self.app.Quit()
            except Exception:
                pass
        self.app = None

    def _is_alive(self) -> bool:
        """Quick COM channel health check — catches stale RPC handles."""
        if not self.app:
            return False
        try:
            _ = self.app.Version  # lightweight roundtrip to Excel
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

    def _convert_applescript_excel(self, src: Path, dst: Path) -> bool:
        """Convert an Excel file to PDF via AppleScript on macOS."""
        posix_src = str(src.resolve()).replace('"', '\\"')
        posix_dst = str(dst.resolve()).replace('"', '\\"')
        script = f'''
            tell application "Microsoft Excel"
                set display alerts to false
                open POSIX file "{posix_src}"
                set theBook to active workbook
                try
                    tell page setup of active sheet
                        set orientation to landscape
                        set (fit to pages wide) to 1
                        set (fit to pages tall) to false
                    end tell
                end try
                save as theBook filename POSIX file "{posix_dst}" file format PDF file format
                close theBook saving no
            end tell
        '''
        return self._convert_applescript(src, dst, "Excel", script)

    # ── conversion ─────────────────────────────────────────────────
    def convert(self, excel_path: str | Path) -> tuple[str | None, str]:
        """Convert *excel_path* to PDF.  Returns ``(pdf_path, "")`` on
        success or ``(None, error_string)`` on failure."""

        src = Path(excel_path).resolve()
        dst = src.with_suffix(".pdf")

        # macOS: AppleScript bridge
        if sys.platform == 'darwin':
            if self._convert_applescript_excel(src, dst):
                src.unlink(missing_ok=True)
                return str(dst), ""
            return None, "AppleScript conversion failed (is Microsoft Excel installed?)"

        # Windows: COM automation with path shadowing
        # Proactive health check — catches the "alternating failure" pattern
        # where the PREVIOUS export silently corrupted the COM channel.
        self._ensure_app()
        if not self.app:
            return None, "Excel COM application could not be initialized."

        from ui_helpers import office_safe_path

        with office_safe_path(src) as (safe_src, safe_pdf, true_pdf):
            abs_excel = str(safe_src)
            abs_pdf = str(safe_pdf)
            wb = None

            try:
                wb = self.app.Workbooks.Open(abs_excel, UpdateLinks=0, ReadOnly=True)
                time.sleep(0.3)  # let COM settle

                # Best-effort page-setup: landscape, fit-to-width, zero margins.
                for sheet in wb.Worksheets:
                    try:
                        sheet.PageSetup.Zoom = False
                        sheet.PageSetup.FitToPagesWide = 1
                        sheet.PageSetup.FitToPagesTall = False
                        sheet.PageSetup.Orientation = 2        # xlLandscape
                        sheet.PageSetup.LeftMargin = 0.0
                        sheet.PageSetup.RightMargin = 0.0
                        sheet.PageSetup.TopMargin = 0.0
                        sheet.PageSetup.BottomMargin = 0.0
                    except Exception:
                        pass

                # 0 = xlTypePDF
                wb.ExportAsFixedFormat(0, abs_pdf)
                time.sleep(0.3)

                wb.Close(SaveChanges=False)
                wb = None
                time.sleep(0.2)

                # Remove the original spreadsheet (from the true long path)
                src.unlink(missing_ok=True)
                # Return the true long-path PDF location (context manager moves it back)
                return str(true_pdf), ""

            except Exception as e:
                error_msg = str(e)

                if wb is not None:
                    try:
                        wb.Close(SaveChanges=False)
                    except Exception:
                        pass

                # SELF-HEAL: assume the COM channel is dead
                self._kill_app()
                self._init_app()

                return None, f"COM Error: {error_msg}"


class ExcelToData:
    """Context manager for batch Excel-to-structured-text extraction.

    Produces a single ``<filename>_Data.txt`` sidecar per workbook, containing
    Markdown-headed sheet sections with CSV-formatted cell data.  This gives
    AI tools (ChatGPT, Claude, Gemini, NotebookLM) a structured, ingestible
    representation of tabular data — far superior to PDF parsing.

    Windows:  COM automation — reads ``sheet.UsedRange.Value`` (2D tuple).
    macOS:    AppleScript — extracts ``value of used range`` as TSV, then
              reformats via Python's ``csv`` module.

    The original ``.xlsx`` is intentionally **NOT** deleted.  If the user also
    has Excel→PDF enabled, that converter handles deletion.
    """

    _META_CONTEXT = (
        "META-CONTEXT: This document contains extracted tabular data (values only) "
        "from a single- or multi-sheet Microsoft Excel workbook. The data is structured "
        "as Comma-Separated Values (CSV). Each sheet's data is separated by a markdown "
        "header (### Sheet: [Name]). Empty commas represent blank cells used for grid spacing."
    )

    def __init__(self):
        self.app = None

    # ── lifecycle ──────────────────────────────────────────────────
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

    # ── COM management ─────────────────────────────────────────────
    def _init_app(self):
        """Spin up a fresh, locked-down Excel instance."""
        try:
            import win32com.client
            self.app = win32com.client.DispatchEx("Excel.Application")
            self.app.Visible = False
            self.app.DisplayAlerts = False
            self.app.EnableEvents = False
            try:
                self.app.AutomationSecurity = 3
            except Exception:
                pass
            try:
                self.app.Interactive = False
            except Exception:
                pass
        except ImportError:
            logger.warning("pywin32 not installed or not on Windows. Excel data extraction disabled.")
            self.app = None
        except Exception as e:
            logger.error(f"[COM] Excel init failed: {e}")
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
        if not self.app:
            return False
        try:
            _ = self.app.Version
            return True
        except Exception:
            return False

    def _ensure_app(self):
        if not self._is_alive():
            self._kill_app()
            self._init_app()

    # ── helpers ────────────────────────────────────────────────────

    @staticmethod
    def _clean_value(v):
        """Coerce a single COM cell value to a clean string."""
        if v is None:
            return ""
        # COM sometimes returns datetime objects, floats, etc.
        return str(v)

    @staticmethod
    def _rows_to_csv_text(rows) -> str:
        """Convert a 2D iterable to CSV-formatted text using csv.writer."""
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator='\n')
        for row in rows:
            writer.writerow(row)
        return buf.getvalue()

    @staticmethod
    def _is_empty_range(data) -> bool:
        """Check if UsedRange.Value returned essentially empty data."""
        if data is None:
            return True
        # Single-cell ranges return a scalar, not a tuple
        if not isinstance(data, tuple):
            return str(data).strip() == ""
        for row in data:
            if not isinstance(row, tuple):
                # Single-column range: data is a 1D tuple of scalars
                if str(row).strip() != "":
                    return False
            else:
                for cell in row:
                    if cell is not None and str(cell).strip() != "":
                        return False
        return True

    # ── AppleScript bridge (macOS) ─────────────────────────────────

    def _extract_applescript(self, src: Path) -> list:
        """Extract sheet data from Excel via AppleScript on macOS.

        Returns list of (sheet_name, csv_text) tuples. Uses temporary native
        CSV export to prevent internal cell linebreaks from destroying tabular alignment.
        """
        import tempfile
        import shutil

        posix_src = str(src.resolve()).replace('"', '\\"')
        temp_dir = Path(tempfile.gettempdir()) / f"excel_data_{os.urandom(8).hex()}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        posix_dir = str(temp_dir.resolve())

        # Safely dump each sheet to a native CSV file using Mac Office
        script = f'''
            set output to ""
            tell application "Microsoft Excel"
                set display alerts to false
                open POSIX file "{posix_src}"
                set theBook to active workbook
                set sheetCount to count of sheets of theBook
                repeat with i from 1 to sheetCount
                    set theSheet to sheet i of theBook
                    set sheetName to name of theSheet
                    try
                        tell theSheet to select
                        set outPath to "{posix_dir}/" & sheetName & ".csv"
                        save as active sheet filename POSIX file outPath file format CSV file format
                        set output to output & sheetName & linefeed
                    end try
                end repeat
                close theBook saving no
            end tell
            return output
        '''
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True, text=True, timeout=120
            )
            sheets = []
            if result.returncode == 0:
                sheet_names = [s.strip() for s in result.stdout.split('\\n') if s.strip()]
                for s_name in sheet_names:
                    csv_path = temp_dir / f"{s_name}.csv"
                    if csv_path.exists():
                        # Read the saved CSV and standardise encoding
                        try:
                            with open(csv_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                                csv_text = f.read()
                        except UnicodeDecodeError:
                            with open(csv_path, 'r', encoding='mac_roman', errors='replace') as f:
                                csv_text = f.read()

                        # Skip completely empty sheets
                        if csv_text.strip():
                            sheets.append((s_name, csv_text.strip() + '\\n'))
                            
            else:
                logger.error(f"[AppleScript] Excel data extraction failed: {result.stderr.strip()}")
            return sheets

        except str as e:
            logger.error(f"[AppleScript] fatal error {e}")
            return []
        except FileNotFoundError:
            logger.error("[AppleScript] osascript not found")
            return []
        except subprocess.TimeoutExpired:
            logger.error("[AppleScript] Excel data extraction timed out after 120s")
            return []
        except Exception as e:
            logger.error(f"[AppleScript] Excel data extraction error: {e}")
            return []
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ── conversion ─────────────────────────────────────────────────
    def convert(self, excel_path: str | Path) -> tuple[str | None, str]:
        """Extract data from *excel_path* into a ``_Data.txt`` sidecar.

        Returns ``(data_txt_path, "")`` on success
        or ``(None, error_string)`` on failure.
        """
        src = Path(excel_path).resolve()
        # Output: Financials.xlsx → Financials_Data.txt
        dst = src.with_name(src.stem + "_Data.txt")

        # macOS: AppleScript bridge
        if sys.platform == 'darwin':
            sheets = self._extract_applescript(src)
            if not sheets:
                return None, "AppleScript data extraction failed (is Microsoft Excel installed?)"
            try:
                with open(dst, 'w', encoding='utf-8-sig', newline='') as f:
                    f.write(self._META_CONTEXT + "\n\n")
                    for sheet_name, csv_text in sheets:
                        f.write(f"### Sheet: {sheet_name}\n")
                        f.write(csv_text)
                        f.write("\n\n")
                return str(dst), ""
            except PermissionError:
                return None, "Data sidecar in use by another program"
            except Exception as e:
                return None, f"Failed to write data file: {e}"

        # Windows: COM automation
        self._ensure_app()
        if not self.app:
            return None, "Excel COM application could not be initialized."

        from ui_helpers import office_safe_path

        # Reuse office_safe_path for long-path safety.
        # We only need the safe source path; we'll write the _Data.txt
        # to the true long-path destination directly.
        with office_safe_path(src) as (safe_src, _safe_pdf, _true_pdf):
            abs_excel = str(safe_src)
            wb = None

            try:
                wb = self.app.Workbooks.Open(abs_excel, UpdateLinks=0, ReadOnly=True)
                time.sleep(0.3)

                sheet_sections = []
                for sheet in wb.Worksheets:
                    try:
                        data = sheet.UsedRange.Value
                    except Exception:
                        continue  # Skip sheets that can't be read

                    if self._is_empty_range(data):
                        continue  # Skip empty sheets

                    # Normalize the data structure
                    rows = []
                    if not isinstance(data, tuple):
                        # Single cell
                        rows.append([self._clean_value(data)])
                    elif data and not isinstance(data[0], tuple):
                        # Single-row range: data is a flat tuple
                        rows.append([self._clean_value(v) for v in data])
                    else:
                        # Normal 2D range
                        for row in data:
                            rows.append([self._clean_value(v) for v in row])

                    csv_text = self._rows_to_csv_text(rows)
                    sheet_sections.append((sheet.Name, csv_text))

                wb.Close(SaveChanges=False)
                wb = None
                time.sleep(0.2)

                if not sheet_sections:
                    return None, "No sheets with data found in workbook."

                # Write unified _Data.txt
                try:
                    with open(str(dst), 'w', encoding='utf-8-sig', newline='') as f:
                        f.write(self._META_CONTEXT + "\n\n")
                        for sheet_name, csv_text in sheet_sections:
                            f.write(f"### Sheet: {sheet_name}\n")
                            f.write(csv_text)
                            f.write("\n\n")
                except PermissionError:
                    return None, "Data sidecar in use by another program"
                except Exception as e:
                    return None, f"Failed to write data file: {e}"

                return str(dst), ""

            except Exception as e:
                error_msg = str(e)
                if wb is not None:
                    try:
                        wb.Close(SaveChanges=False)
                    except Exception:
                        pass
                # SELF-HEAL
                self._kill_app()
                self._init_app()
                return None, f"COM Error: {error_msg}"


