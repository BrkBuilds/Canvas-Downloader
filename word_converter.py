import os
import pythoncom
import win32com.client
from pathlib import Path

def convert_word_to_pdf(doc_path: str | Path) -> str | None:
    abs_doc = str(Path(doc_path).resolve().absolute())
    abs_pdf = str(Path(doc_path).with_suffix('.pdf').resolve().absolute())
    
    # Do not convert if it's already a modern .docx
    if abs_doc.lower().endswith('.docx'):
        return None
        
    pythoncom.CoInitialize()
    word_app = None
    doc = None
    
    try:
        word_app = win32com.client.DispatchEx("Word.Application")
        
        # Bypass potential Office 365 visibility restrictions
        try:
            word_app.Visible = False
        except Exception:
            pass
            
        word_app.DisplayAlerts = False
        
        # Open the legacy document
        doc = word_app.Documents.Open(abs_doc, ReadOnly=True, Visible=False)
        
        # Save as PDF (17 is wdFormatPDF)
        doc.SaveAs(abs_pdf, FileFormat=17)
        
        doc.Close(SaveChanges=0)
        word_app.Quit()
        
        # Delete the original legacy file
        Path(abs_doc).unlink(missing_ok=True)
        
        return abs_pdf
        
    except Exception as e:
        print(f"[COM Error] Failed to convert Word doc {abs_doc}: {e}")
        if doc is not None:
            try:
                doc.Close(SaveChanges=0)
            except:
                pass
        if word_app is not None:
            try:
                word_app.Quit()
            except:
                pass
        return None
    finally:
        pythoncom.CoUninitialize()
