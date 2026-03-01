import os
import pythoncom
import win32com.client
from pathlib import Path

def convert_excel_to_pdf(excel_path: str | Path) -> str | None:
    abs_excel = str(Path(excel_path).resolve().absolute())
    abs_pdf = str(Path(excel_path).with_suffix('.pdf').resolve().absolute())
    
    pythoncom.CoInitialize()
    excel_app = None
    wb = None
    
    try:
        excel_app = win32com.client.DispatchEx("Excel.Application")
        excel_app.Visible = False
        excel_app.DisplayAlerts = False
        
        # Open workbook (0 = don't update links, True = ReadOnly)
        wb = excel_app.Workbooks.Open(abs_excel, 0, True)
        
        has_data = False
        
        for sheet in wb.Worksheets:
            # Skip completely empty sheets to avoid export errors
            if excel_app.WorksheetFunction.CountA(sheet.Cells) == 0:
                continue
                
            has_data = True
            
            # Setup Page to be AI-friendly (1 page wide, infinite tall, no margins)
            try:
                sheet.PageSetup.Zoom = False
                sheet.PageSetup.FitToPagesWide = 1
                sheet.PageSetup.FitToPagesTall = False # Allows infinite scrolling downwards
                sheet.PageSetup.Orientation = 2 # xlLandscape
                sheet.PageSetup.LeftMargin = 0.0
                sheet.PageSetup.RightMargin = 0.0
                sheet.PageSetup.TopMargin = 0.0
                sheet.PageSetup.BottomMargin = 0.0
            except Exception as e:
                print(f"Warning: Could not set PageSetup for sheet {sheet.Name}: {e}")

        if not has_data:
            wb.Close(SaveChanges=False)
            excel_app.Quit()
            return None
            
        # Export the entire workbook as PDF (0 = xlTypePDF)
        wb.ExportAsFixedFormat(0, abs_pdf)
        
        wb.Close(SaveChanges=False)
        excel_app.Quit()
        
        # Delete original Excel file
        Path(abs_excel).unlink()
        
        return abs_pdf
        
    except Exception as e:
        print(f"[COM Error] Failed to convert Excel {abs_excel}: {e}")
        if wb is not None:
            try:
                wb.Close(SaveChanges=False)
            except:
                pass
        if excel_app is not None:
            try:
                excel_app.Quit()
            except:
                pass
        return None
    finally:
        pythoncom.CoUninitialize()
