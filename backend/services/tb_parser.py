import openpyxl
from typing import Dict, Any, List
from decimal import Decimal
from services.engine_utils import strict_normalize_ledger_name, clean_decimal_value
from services.ledger_mapper import CompanyConfiguration

class UnmappedLedgerException(Exception):
    def __init__(self, unmapped_ledgers: List[str]):
        self.unmapped_ledgers = unmapped_ledgers
        self.status_code = 422
        super().__init__(f"422 Unprocessable Entity: Unmapped ledgers found: {unmapped_ledgers}")


def parse_trial_balance(tb_path: str, config: CompanyConfiguration) -> Dict[str, dict]:
    """
    Ingests Trial Balance, cleans data, overwrites master names, and halts on unmapped ledgers.
    Returns a dictionary of ledger movements mapped by their cleaned normalized keys.
    """
    wb = openpyxl.load_workbook(tb_path, data_only=True)
    
    tb_sheet = None
    for name in wb.sheetnames:
        if name.strip().lower() in ['tb', 'trial balance', 'trial_balance']:
            tb_sheet = wb[name]
            break
    if not tb_sheet:
        # Fallback to the first sheet that IS NOT the mapping sheet
        tb_sheet = next((wb[s] for s in wb.sheetnames if s.strip().lower() not in ["list of ledgers", "ledger mapping", "mapping"]), wb.active)
        
    # Find the header row
    header_row_idx = -1
    particulars_col = 1
    for r_idx in range(1, 21):
        for c_idx in range(1, min(tb_sheet.max_column + 1, 15)):
            val = tb_sheet.cell(row=r_idx, column=c_idx).value
            if val and str(val).strip().lower() in ['particulars', 'ledger name', 'particular']:
                header_row_idx = r_idx
                particulars_col = c_idx
                break
        if header_row_idx != -1:
            break
            
    if header_row_idx == -1:
        header_row_idx = 4
        particulars_col = 1
        
    # Read headers
    cols = []
    max_cols_to_scan = max(tb_sheet.max_column, 15)
    for c_idx in range(1, max_cols_to_scan + 1):
        val = tb_sheet.cell(row=header_row_idx, column=c_idx).value
        cols.append(str(val).strip().lower() if val else "")
        
    opening_col = particulars_col + 1
    debit_col = particulars_col + 2
    credit_col = particulars_col + 3
    closing_col = particulars_col + 4
    
    # Try to find exactly labeled columns if possible
    for idx, col_name in enumerate(cols, start=1):
        if 'opening' in col_name and idx >= particulars_col + 1:
            opening_col = idx
        elif 'debit' in col_name and idx >= particulars_col + 1:
            debit_col = idx
        elif 'credit' in col_name and idx >= particulars_col + 1:
            credit_col = idx
        elif 'closing' in col_name and idx >= particulars_col + 1:
            closing_col = idx

    FOOTER_EXCLUSIONS = {'total', 'grand total', 'grand', 'net profit', 'net loss'}
    unmapped_tracker = []
    parsed_entries = {}
    
    consecutive_empty = 0
    for r_idx in range(header_row_idx + 1, tb_sheet.max_row + 1):
        raw_name = tb_sheet.cell(row=r_idx, column=particulars_col).value
        if not raw_name or str(raw_name).strip() == "":
            consecutive_empty += 1
            if consecutive_empty > 50:
                break
            continue
        consecutive_empty = 0
        
        clean_name = strict_normalize_ledger_name(raw_name)
        if clean_name == 'opening stock':
            pass
        elif not clean_name or clean_name in FOOTER_EXCLUSIONS:
            continue
            
        op_val = clean_decimal_value(tb_sheet.cell(row=r_idx, column=opening_col).value)
        deb_val = clean_decimal_value(tb_sheet.cell(row=r_idx, column=debit_col).value)
        cred_val = clean_decimal_value(tb_sheet.cell(row=r_idx, column=credit_col).value, is_credit=True)
        clos_val = clean_decimal_value(tb_sheet.cell(row=r_idx, column=closing_col).value)
        
        # Halt-On-Unmapped Safeguard logic
        has_balance = any(abs(v) > Decimal('0.00') for v in [op_val, deb_val, cred_val, clos_val])
        if clean_name not in config.mappings:
            if clean_name == 'opening stock':
                # Auto-map Tally's built-in stock row to prevent it from ever flagging
                from services.ledger_mapper import LedgerMapping
                config.mappings[clean_name] = LedgerMapping(
                    name=str(raw_name).strip(),
                    vertical="Common",
                    head="Stock-in-hand",
                    group="BS",
                    classification="Opening Stock"
                )
            else:
                if has_balance:
                    unmapped_tracker.append(str(raw_name).strip())
                continue
            
        if not has_balance:
            continue
            
        # Master Name Overwrite Rule
        official_name = config.mappings[clean_name].name
        
        parsed_entries[clean_name] = {
            "name": official_name,
            "clean_name": clean_name,
            "opening": op_val,
            "debit": deb_val,
            "credit": cred_val,
            "closing": clos_val
        }
        
    wb.close()
    
    if unmapped_tracker:
        raise UnmappedLedgerException(unmapped_tracker)
        
    return parsed_entries
