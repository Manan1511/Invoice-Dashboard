import openpyxl
from typing import List, Dict, Optional
from models.ledger import LedgerEntry

def check_if_tb_has_ytd(parsed_entries: List[LedgerEntry]) -> bool:
    """Checks if the parsed trial balance has YTD values populated."""
    ytd_count = 0
    total_valid = 0
    for entry in parsed_entries:
        if entry.debit is not None or entry.credit is not None or entry.closing is not None:
            total_valid += 1
            if entry.debit_ytd is not None or entry.credit_ytd is not None or entry.closing_ytd is not None:
                ytd_count += 1
                
    if total_valid == 0:
        return False
    # If more than 30% of active entries have YTD data, we assume YTD is supplied by Tally
    return (ytd_count / total_valid) > 0.3

def roll_forward_ytd(
    current_entries: List[LedgerEntry], 
    prior_workbook_path: Optional[str],
    month: int
) -> List[LedgerEntry]:
    """Rolls forward YTD balances by adding current month values to prior month YTD values."""
    if not prior_workbook_path:
        # No prior month workbook provided, initialize YTD values with current month net signed values (e.g. if it's the first month)
        for entry in current_entries:
            if entry.opening_ytd is None:
                entry.opening_ytd = entry.opening_net if entry.opening_net is not None else (entry.opening or 0.0)
            if entry.debit_ytd is None:
                entry.debit_ytd = entry.debit_net if entry.debit_net is not None else (entry.debit or 0.0)
            if entry.credit_ytd is None:
                entry.credit_ytd = entry.credit_net if entry.credit_net is not None else (entry.credit or 0.0)
            if entry.closing_ytd is None:
                entry.closing_ytd = entry.closing_net if entry.closing_net is not None else (entry.closing or 0.0)
        return current_entries

    # Load prior month YTD values from its 'List of Ledgers ' sheet
    prior_wb = openpyxl.load_workbook(prior_workbook_path, data_only=True)
    if 'List of Ledgers ' not in prior_wb.sheetnames:
        # Fallback to current values if sheet is missing
        return roll_forward_ytd(current_entries, None, month)
        
    prior_ws = prior_wb['List of Ledgers ']
    prior_ytd_data = {}
    
    # Read columns: Name of Ledger (Col B), Opening YTD (Col N), Debit YTD (Col O), Credit YTD (Col P), Closing YTD (Col Q)
    for r_idx in range(5, prior_ws.max_row + 1):
        name = prior_ws.cell(row=r_idx, column=2).value
        if not name:
            continue
        name_clean = str(name).strip().lower()
        
        op_ytd = prior_ws.cell(row=r_idx, column=14).value
        deb_ytd = prior_ws.cell(row=r_idx, column=15).value
        cred_ytd = prior_ws.cell(row=r_idx, column=16).value
        clos_ytd = prior_ws.cell(row=r_idx, column=17).value
        
        group_val = str(prior_ws.cell(row=r_idx, column=4).value or "").strip().upper()
        
        # If it's April (month 4) and this is a P&L account, reset prior YTD values to 0
        if month == 4 and "P&L" in group_val:
            prior_ytd_data[name_clean] = {
                "opening_ytd": 0.0,
                "debit_ytd": 0.0,
                "credit_ytd": 0.0,
                "closing_ytd": 0.0
            }
        else:
            prior_ytd_data[name_clean] = {
                "opening_ytd": _to_float(op_ytd),
                "debit_ytd": _to_float(deb_ytd),
                "credit_ytd": _to_float(cred_ytd),
                "closing_ytd": _to_float(clos_ytd)
            }
        
    for entry in current_entries:
        name_clean = entry.name.lower()
        
        # If YTD values are already parsed from TB YTD and valid, keep them!
        if entry.debit_ytd is not None or entry.credit_ytd is not None:
            continue
            
        prior_vals = prior_ytd_data.get(name_clean, {
            "opening_ytd": 0.0,
            "debit_ytd": 0.0,
            "credit_ytd": 0.0,
            "closing_ytd": 0.0
        })
        
        # Opening YTD (April 1st) remains the same throughout the fiscal year
        entry.opening_ytd = prior_vals["opening_ytd"]
        
        # YTD Debit = Prior YTD Debit + Current Month Debit (signed net)
        cur_deb = entry.debit_net if entry.debit_net is not None else (entry.debit or 0.0)
        entry.debit_ytd = prior_vals["debit_ytd"] + cur_deb
        
        # YTD Credit = Prior YTD Credit + Current Month Credit (signed net)
        cur_cred = entry.credit_net if entry.credit_net is not None else (entry.credit or 0.0)
        entry.credit_ytd = prior_vals["credit_ytd"] + cur_cred
        
        # Calculate YTD Closing (signed net)
        entry.closing_ytd = entry.opening_ytd + entry.debit_ytd - entry.credit_ytd
        
    return current_entries

def _to_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except ValueError:
        return 0.0
