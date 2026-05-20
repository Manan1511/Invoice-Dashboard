import openpyxl
from typing import List, Dict, Optional, Tuple
from models.ledger import LedgerEntry

def parse_tally_tb(file_path: str) -> List[LedgerEntry]:
    wb = openpyxl.load_workbook(file_path, data_only=True)
    
    # 1. Parse Monthly TB (from 'TB ' or first sheet)
    monthly_sheet = None
    for name in wb.sheetnames:
        if name.strip().lower() in ['tb', 'trial balance']:
            monthly_sheet = wb[name]
            break
    if not monthly_sheet:
        monthly_sheet = wb.active
        
    monthly_entries = _parse_sheet_rows(monthly_sheet, is_ytd=False)
    
    # 2. Parse YTD TB if exists
    ytd_sheet = None
    for name in wb.sheetnames:
        if 'ytd' in name.strip().lower():
            ytd_sheet = wb[name]
            break
            
    if ytd_sheet:
        ytd_entries = _parse_sheet_rows(ytd_sheet, is_ytd=True)
        # Merge YTD into monthly entries
        for name, ytd_entry in ytd_entries.items():
            if name in monthly_entries:
                monthly_entries[name].opening_ytd = ytd_entry.opening_ytd
                monthly_entries[name].debit_ytd = ytd_entry.debit_ytd
                monthly_entries[name].credit_ytd = ytd_entry.credit_ytd
                monthly_entries[name].closing_ytd = ytd_entry.closing_ytd
            else:
                # Ledger only in YTD sheet (rare, but possible)
                monthly_entries[name] = ytd_entry
                
    return list(monthly_entries.values())

def _parse_sheet_rows(sheet, is_ytd: bool) -> Dict[str, LedgerEntry]:
    entries = {}
    
    # Find the header row (where column A is "Particulars" or similar)
    header_row_idx = -1
    for r_idx in range(1, 20):
        val = sheet.cell(row=r_idx, column=1).value
        if val and str(val).strip().lower() in ['particulars', 'ledger name', 'particular']:
            header_row_idx = r_idx
            break
            
    if header_row_idx == -1:
        # Fallback to row 4 as standard in Tally template
        header_row_idx = 4
        
    # Read columns from the header row
    cols = []
    for c_idx in range(1, 15):
        val = sheet.cell(row=header_row_idx, column=c_idx).value
        cols.append(str(val).strip() if val else "")
        
    # Find column indices (1-indexed for openpyxl)
    particulars_col = 1
    opening_col = 2
    debit_col = 3
    credit_col = 4
    closing_col = 5
    
    # If YTD, check if YTD values are in cols 7-10 (standard in sheet: Opening YTD, Debit YTD, etc.)
    opening_net_col = 7
    debit_net_col = 8
    credit_net_col = 9
    closing_net_col = 10

    if is_ytd:
        # Let's inspect column names in row
        for c_idx, col_name in enumerate(cols, start=1):
            col_lower = col_name.lower()
            if 'opening ytd' in col_lower or ('opening' in col_lower and c_idx >= 7):
                opening_col = c_idx
            elif 'debit ytd' in col_lower or ('debit' in col_lower and c_idx >= 7):
                debit_col = c_idx
            elif 'credit ytd' in col_lower or ('credit' in col_lower and c_idx >= 7):
                credit_col = c_idx
            elif 'closing ytd' in col_lower or ('closing' in col_lower and c_idx >= 7):
                closing_col = c_idx
    else:
        for c_idx, col_name in enumerate(cols, start=1):
            col_lower = col_name.lower()
            if c_idx >= 7:
                if col_lower == 'opening':
                    opening_net_col = c_idx
                elif col_lower == 'debit':
                    debit_net_col = c_idx
                elif col_lower == 'credit':
                    credit_net_col = c_idx
                elif col_lower == 'closing':
                    closing_net_col = c_idx

    # Use a set for O(1) lookup and exact matching, not .startswith()
    FOOTER_EXCLUSIONS = {'total', 'grand total', 'grand', 'net profit', 'net loss'}

    # Parse rows below the header
    for r_idx in range(header_row_idx + 1, sheet.max_row + 1):
        raw_name = sheet.cell(row=r_idx, column=particulars_col).value
        if not raw_name:
            continue
            
        ledger_name = str(raw_name).strip()
        
        # Check for exact matches to avoid dropping legitimate ledgers like "Total Office Supplies"
        if ledger_name.lower() in FOOTER_EXCLUSIONS:
            continue
        
        # Read cell values
        op_val = _clean_float(sheet.cell(row=r_idx, column=opening_col).value)
        deb_val = _clean_float(sheet.cell(row=r_idx, column=debit_col).value)
        cred_val = _clean_float(sheet.cell(row=r_idx, column=credit_col).value)
        clos_val = _clean_float(sheet.cell(row=r_idx, column=closing_col).value)
        
        if is_ytd:
            # Skip if all values are None/Zero
            if not any([op_val, deb_val, cred_val, clos_val]):
                continue
            entries[ledger_name] = LedgerEntry(
                name=ledger_name,
                opening_ytd=op_val,
                debit_ytd=deb_val,
                credit_ytd=cred_val,
                closing_ytd=clos_val
            )
        else:
            op_net = _clean_float(sheet.cell(row=r_idx, column=opening_net_col).value)
            deb_net = _clean_float(sheet.cell(row=r_idx, column=debit_net_col).value)
            cred_net = _clean_float(sheet.cell(row=r_idx, column=credit_net_col).value)
            clos_net = _clean_float(sheet.cell(row=r_idx, column=closing_net_col).value)
            
            # Skip if all values are None/Zero
            if not any([op_val, deb_val, cred_val, clos_val, op_net, deb_net, cred_net, clos_net]):
                continue
                
            entries[ledger_name] = LedgerEntry(
                name=ledger_name,
                opening=op_val,
                debit=deb_val,
                credit=cred_val,
                closing=clos_val,
                opening_net=op_net,
                debit_net=deb_net,
                credit_net=cred_net,
                closing_net=clos_net
            )
            
    return entries

def _clean_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            return float(val)
            
        s_val = str(val).replace(',', '').strip()
        
        is_credit = s_val.lower().endswith(' cr')
        # Strip Tally's standard Dr/Cr suffixes
        if s_val.lower().endswith(' dr') or is_credit:
            s_val = s_val[:-3].strip()
            
        if s_val == "" or s_val == "-":
            return None
            
        parsed_float = float(s_val)
        # If it was a credit, it needs to be negative for the math to work later
        return -parsed_float if is_credit else parsed_float
    except ValueError:
        return None
