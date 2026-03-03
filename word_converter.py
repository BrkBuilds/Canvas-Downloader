import os
import pythoncom
import win32com.client
from pathlib import Path

class WordToPDF:
    def __init__(self):
        self.app = None
        
    def __enter__(self):
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            self.app = win32com.client.DispatchEx("Word.Application")
            try:
                self.app.Visible = False
            except Exception:
                pass
            self.app.DisplayAlerts = False
        except Exception as e:
            print(f"COM Initialization failed for Word: {e}")
        return self
        
    def convert(self, doc_path: str | Path) -> str | None:
        if self.app is None:
            return None
            
        abs_doc = str(Path(doc_path).resolve().absolute())
        abs_pdf = str(Path(doc_path).with_suffix('.pdf').resolve().absolute())
        
        # Do not convert if it's already a modern .docx
        if abs_doc.lower().endswith('.docx'):
            return None
            
        doc = None
        
        try:
            print(f"[COM Converter] Attempting to convert: {abs_doc}")
            
            # Open the legacy document
            doc = self.app.Documents.Open(abs_doc, ReadOnly=True, Visible=False)
            
            # Save as PDF (17 is wdFormatPDF)
            doc.SaveAs(abs_pdf, FileFormat=17)
            
            doc.Close(SaveChanges=0)
            doc = None
            
            # Delete the original legacy file
            Path(abs_doc).unlink(missing_ok=True)
            
            return abs_pdf
            
        except Exception as e:
            print(f"[COM Error] Failed to convert Word doc {abs_doc}: {e}")
            return None
        finally:
            if doc is not None:
                try:
                    doc.Close(SaveChanges=0)
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
