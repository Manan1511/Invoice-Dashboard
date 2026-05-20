import openpyxl
import shutil
import os
from typing import List, Optional
from models.ledger import LedgerEntry
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "MIS_template.xlsx")

def generate_monthly_workbook(
    parsed_entries: List[LedgerEntry], 
    uploaded_file_path: str,
    output_path: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
    closing_stock: float = 0.0
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
    
    # 5.2 Inject manual closing stock if provided (defaults to 0.0)
    _inject_closing_stock(wb, closing_stock)
    
    # 5.5 Update dynamic date labels on the 'P&L' sheet if provided
    if month is not None and year is not None and 'P&L' in wb.sheetnames:
        sheet = wb['P&L']
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        short_month_name = month_names[month - 1]
        short_year = str(year)[-2:]
        
        sheet['A5'].value = f"For the month of {short_month_name} {year}"
        sheet['L5'].value = f"{short_month_name}'{short_year}"
        sheet['N5'].value = f"(April to {short_month_name})"
        sheet['X5'].value = f"YTD'{short_year}"
    
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
            # Columns: Opening, Debit, Credit, Closing for YTD (Cols 2-5, unsigned counterparts of Cols 7-10)
            op_val = abs(entry.opening_ytd) if entry.opening_ytd is not None else None
            deb_val = entry.debit_ytd
            cred_val = entry.credit_ytd
            clos_val = abs(entry.closing_ytd) if entry.closing_ytd is not None else None
            
            sheet.cell(row=row, column=2, value=op_val)
            sheet.cell(row=row, column=3, value=deb_val)
            sheet.cell(row=row, column=4, value=cred_val)
            sheet.cell(row=row, column=5, value=clos_val)
            
            # Columns: Opening YTD, Debit YTD, Credit YTD, Closing YTD (Cols 7-10, signed net)
            sheet.cell(row=row, column=7, value=entry.opening_ytd)
            sheet.cell(row=row, column=8, value=entry.debit_ytd)
            sheet.cell(row=row, column=9, value=entry.credit_ytd)
            sheet.cell(row=row, column=10, value=entry.closing_ytd)
        else:
            # Columns: Opening Bal, Debit Bal, Credit Bal, Closing Bal (Cols 2-5, unsigned monthly)
            sheet.cell(row=row, column=2, value=entry.opening)
            sheet.cell(row=row, column=3, value=entry.debit)
            sheet.cell(row=row, column=4, value=entry.credit)
            sheet.cell(row=row, column=5, value=entry.closing)
            
            # Columns: Opening, Debit, Credit, Closing (Cols 7-10, signed monthly net)
            sheet.cell(row=row, column=7, value=entry.opening_net)
            sheet.cell(row=row, column=8, value=entry.debit_net)
            sheet.cell(row=row, column=9, value=entry.credit_net)
            sheet.cell(row=row, column=10, value=entry.closing_net)

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

def _inject_closing_stock(wb, closing_stock: float):
    """Injects the manual closing stock row into 'Stk ' and 'Stk YTD' sheets under the 'Factory' vertical."""
    for sheet_name in ['Stk ', 'Stk YTD']:
        if sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            # Find the next empty row. We start searching from row 5 onwards.
            # Row 4 is the header row.
            next_row = 5
            while next_row <= sheet.max_row:
                # If first cell is empty or None, or if we find a cell with "Closing Stock (Manual)",
                # we can write here
                val = sheet.cell(row=next_row, column=2).value
                if val == "Closing Stock (Manual)":
                    break
                val_a = sheet.cell(row=next_row, column=1).value
                if (val_a is None or val_a == "") and (val is None or val == ""):
                    break
                next_row += 1
            
            # Columns:
            # Col 1 (A): Business Verticle -> 'Factory'
            # Col 2 (B): Particulars -> 'Closing Stock (Manual)'
            # Col 3 (C): Opening Stock -> 0.0
            # Col 4 (D): Inwards -> None
            # Col 5 (E): Outwards -> None
            # Col 6 (F): Closing Stock -> closing_stock
            sheet.cell(row=next_row, column=1, value="Factory")
            sheet.cell(row=next_row, column=2, value="Closing Stock (Manual)")
            sheet.cell(row=next_row, column=3, value=0.0)
            sheet.cell(row=next_row, column=6, value=closing_stock)
