import openpyxl
import shutil
import os
from typing import List, Optional
from models.ledger import LedgerEntry

TEMPLATE_PATH = "templates/MIS_template.xlsx"

def generate_monthly_workbook(
    parsed_entries: List[LedgerEntry], 
    uploaded_file_path: str,
    output_path: str
):
    """Generates the new monthly Excel workbook using the template and parsed trial balance."""
    # 1. Create a copy of the template
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    shutil.copy(TEMPLATE_PATH, output_path)
    
    # 2. Open the copy
    wb = openpyxl.load_workbook(output_path, data_only=False)
    
    # 3. Populate TB Sheet
    if 'TB ' in wb.sheetnames:
        _populate_tb_sheet(wb['TB '], parsed_entries, is_ytd=False)
        
    # 4. Populate TB YTD Sheet
    if 'TB YTD' in wb.sheetnames:
        _populate_tb_sheet(wb['TB YTD'], parsed_entries, is_ytd=True)
        
    # 5. Check if stock sheets exist in uploaded file and copy them
    _copy_stock_sheets_if_present(uploaded_file_path, wb)
    
    # 6. Save the generated workbook
    wb.save(output_path)

def _populate_tb_sheet(sheet, entries: List[LedgerEntry], is_ytd: bool):
    # Clear existing data rows (from row 5 downwards)
    if sheet.max_row >= 5:
        sheet.delete_rows(5, sheet.max_row - 4)
        
    # Write new data
    for idx, entry in enumerate(entries):
        row = 5 + idx
        
        # Particulars
        sheet.cell(row=row, column=1, value=entry.name)
        
        if is_ytd:
            # Columns: Opening, Debit, Credit, Closing for Month (Cols 2-5)
            sheet.cell(row=row, column=2, value=entry.opening)
            sheet.cell(row=row, column=3, value=entry.debit)
            sheet.cell(row=row, column=4, value=entry.credit)
            sheet.cell(row=row, column=5, value=entry.closing)
            
            # Columns: Opening YTD, Debit YTD, Credit YTD, Closing YTD (Cols 7-10)
            sheet.cell(row=row, column=7, value=entry.opening_ytd)
            sheet.cell(row=row, column=8, value=entry.debit_ytd)
            sheet.cell(row=row, column=9, value=entry.credit_ytd)
            sheet.cell(row=row, column=10, value=entry.closing_ytd)
        else:
            # Columns: Opening Bal, Debit Bal, Credit Bal, Closing Bal (Cols 2-5)
            sheet.cell(row=row, column=2, value=entry.opening)
            sheet.cell(row=row, column=3, value=entry.debit)
            sheet.cell(row=row, column=4, value=entry.credit)
            sheet.cell(row=row, column=5, value=entry.closing)
            
            # Columns: Opening, Debit, Credit, Closing (Cols 7-10)
            sheet.cell(row=row, column=7, value=entry.opening)
            sheet.cell(row=row, column=8, value=entry.debit)
            sheet.cell(row=row, column=9, value=entry.credit)
            sheet.cell(row=row, column=10, value=entry.closing)

def _copy_stock_sheets_if_present(uploaded_file_path: str, target_wb):
    """Copies stock summary sheet rows from the uploaded Tally file to the target workbook."""
    try:
        source_wb = openpyxl.load_workbook(uploaded_file_path, data_only=True)
    except Exception:
        # If the file can't be loaded (e.g. invalid format), skip copying
        return

    for sheet_name in ['Stk ', 'Stk YTD']:
        source_sheet = None
        for name in source_wb.sheetnames:
            if name.strip().lower() == sheet_name.strip().lower():
                source_sheet = source_wb[name]
                break
                
        if source_sheet and sheet_name in target_wb.sheetnames:
            target_sheet = target_wb[sheet_name]
            # Clear rows 5 onwards
            if target_sheet.max_row >= 5:
                target_sheet.delete_rows(5, target_sheet.max_row - 4)
                
            # Copy data rows
            for r_idx in range(5, source_sheet.max_row + 1):
                # Copy first 7 columns of data
                for c_idx in range(1, 8):
                    val = source_sheet.cell(row=r_idx, column=c_idx).value
                    target_sheet.cell(row=r_idx, column=c_idx, value=val)
