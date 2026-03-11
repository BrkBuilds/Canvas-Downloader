import os
import logging
import pythoncom
import win32com.client
from pathlib import Path

logger = logging.getLogger(__name__)


class ExcelToPDF:
    """Context manager for batch Excel-to-PDF conversion via COM.

    Design: One COM instance is shared across the batch for speed, but
    self-heals (Quit + re-init) if any individual file crashes the RPC
    channel.  A proactive health check at the start of each convert()
    detects stale COM objects before they cause failures.
    """

    def __init__(self):
        self.app = None

    # ── lifecycle ──────────────────────────────────────────────────
    def __enter__(self):
        pythoncom.CoInitialize()
        self._init_app()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._kill_app()
        pythoncom.CoUninitialize()

    # ── COM management ─────────────────────────────────────────────
    def _init_app(self):
        """Spin up a fresh, locked-down Excel instance."""
        try:
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

    # ── conversion ─────────────────────────────────────────────────
    def convert(self, excel_path: str | Path) -> tuple[str | None, str]:
        """Convert *excel_path* to PDF.  Returns ``(pdf_path, "")`` on
        success or ``(None, error_string)`` on failure."""

        # Proactive health check — catches the "alternating failure" pattern
        # where the PREVIOUS export silently corrupted the COM channel.
        self._ensure_app()
        if not self.app:
            return None, "Excel COM application could not be initialized."

        src = Path(excel_path).resolve()
        dst = src.with_suffix(".pdf")
        abs_excel = str(src)
        abs_pdf = str(dst)
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

            # Remove the original spreadsheet
            src.unlink(missing_ok=True)
            return abs_pdf, ""

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
