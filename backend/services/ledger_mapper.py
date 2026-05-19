import openpyxl
from typing import List, Set, Dict, Tuple
from models.ledger import LedgerMapping, LedgerEntry

TEMPLATE_PATH = "templates/MIS_template.xlsx"

def load_mapped_ledgers() -> Dict[str, LedgerMapping]:
    """Loads existing ledger mappings from the List of Ledgers sheet."""
    wb = openpyxl.load_workbook(TEMPLATE_PATH, data_only=True)
    ws = wb['List of Ledgers ']
    
    mappings = {}
    for r_idx in range(5, ws.max_row + 1):
        name = ws.cell(row=r_idx, column=2).value
        if not name or str(name).strip() == "":
            continue
            
        name = str(name).strip()
        under = ws.cell(row=r_idx, column=3).value
        group = ws.cell(row=r_idx, column=4).value
        head = ws.cell(row=r_idx, column=5).value
        classification = ws.cell(row=r_idx, column=6).value
        vertical = ws.cell(row=r_idx, column=7).value
        
        mappings[name.lower()] = LedgerMapping(
            ledger_name=name,
            under=str(under).strip() if under else None,
            group=str(group).strip() if group else "BS",
            head=str(head).strip() if head else "",
            classification=str(classification).strip() if classification else None,
            vertical=str(vertical).strip() if vertical else "Common"
        )
    return mappings

def get_unmapped_ledgers(parsed_entries: List[LedgerEntry]) -> List[str]:
    """Compares parsed trial balance entries with master mappings and returns unmapped ledger names."""
    mapped = load_mapped_ledgers()
    unmapped = []
    for entry in parsed_entries:
        name_lower = entry.name.lower()
        # Skip if name is empty or looks like totals/headers
        if not entry.name or entry.name.startswith(('Total', 'Opening', 'Closing')) or name_lower in ['particulars']:
            continue
        if name_lower not in mapped:
            unmapped.append(entry.name)
    return unmapped

def append_new_mappings_to_template(new_mappings: List[LedgerMapping]):
    """Appends new ledger mappings to the template List of Ledgers sheet with formulas."""
    wb = openpyxl.load_workbook(TEMPLATE_PATH, data_only=False)
    ws = wb['List of Ledgers ']
    
    start_row = ws.max_row + 1
    # Check if the last row is actually empty or a total row, find the true insertion point
    for r_idx in range(ws.max_row, 4, -1):
        val = ws.cell(row=r_idx, column=2).value
        if val and str(val).strip() != "":
            start_row = r_idx + 1
            break

    for idx, mapping in enumerate(new_mappings):
        row = start_row + idx
        
        # Write metadata fields
        ws.cell(row=row, column=1, value=row - 4)  # Sl. No.
        ws.cell(row=row, column=2, value=mapping.ledger_name)
        ws.cell(row=row, column=3, value=mapping.under)
        ws.cell(row=row, column=4, value=mapping.group)
        ws.cell(row=row, column=5, value=mapping.head)
        ws.cell(row=row, column=6, value=mapping.classification)
        ws.cell(row=row, column=7, value=mapping.vertical)
        
        # Add Excel VLOOKUP formulas to pull monthly balances from 'TB '
        ws.cell(row=row, column=9, value=f"=IFERROR(VLOOKUP(B{row},'TB '!$A:$G,7,),0)") # Opening
        ws.cell(row=row, column=10, value=f"=IFERROR(VLOOKUP($B{row},'TB '!$4:$1048576,MATCH('List of Ledgers '!J$4,'TB '!$4:$4,0),0),0)") # Debit
        ws.cell(row=row, column=11, value=f"=IFERROR(VLOOKUP($B{row},'TB '!$4:$1048576,MATCH('List of Ledgers '!K$4,'TB '!$4:$4,0),0),0)") # Credit
        ws.cell(row=row, column=12, value=f"=IFERROR(VLOOKUP(B{row},'TB '!$A:$J,10,),0)") # Closing
        
        # Add Excel VLOOKUP formulas to pull YTD balances from 'TB YTD'
        ws.cell(row=row, column=14, value=f"=IFERROR(VLOOKUP($B{row},'TB YTD'!$4:$1048576,MATCH('List of Ledgers '!N$4,'TB YTD'!$4:$4,0),0),0)") # Opening YTD
        ws.cell(row=row, column=15, value=f"=IFERROR(VLOOKUP($B{row},'TB YTD'!$4:$1048576,MATCH('List of Ledgers '!O$4,'TB YTD'!$4:$4,0),0),0)") # Debit YTD
        ws.cell(row=row, column=16, value=f"=IFERROR(VLOOKUP($B{row},'TB YTD'!$4:$1048576,MATCH('List of Ledgers '!P$4,'TB YTD'!$4:$4,0),0),0)") # Credit YTD
        ws.cell(row=row, column=17, value=f"=IFERROR(VLOOKUP($B{row},'TB YTD'!$4:$1048576,MATCH('List of Ledgers '!Q$4,'TB YTD'!$4:$4,0),0),0)") # Closing YTD
        
    wb.save(TEMPLATE_PATH)
