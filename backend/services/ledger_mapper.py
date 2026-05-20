import openpyxl
import os
from typing import List, Dict, Optional
from models.ledger import LedgerMapping, LedgerEntry

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "MIS_template.xlsx")

# Required column headers that must be present in a valid List of Ledgers sheet
_REQUIRED_HEADER_KEYWORDS = {"ledger", "group", "head", "vertical"}


def _parse_ledger_sheet(ws) -> List[LedgerMapping]:
    """
    Parses a List of Ledgers worksheet and returns a list of LedgerMapping objects.
    Scans for the header row dynamically (first row containing 'Ledger Name' or 'Ledger').
    Raises ValueError if the sheet structure is invalid.
    """
    header_row_idx: Optional[int] = None
    col_map: Dict[str, int] = {}  # key -> 1-indexed column number

    # Scan up to the first 10 rows for a header
    for r_idx in range(1, min(ws.max_row + 1, 11)):
        row_vals = [
            str(ws.cell(row=r_idx, column=c).value or "").strip().lower()
            for c in range(1, ws.max_column + 1)
        ]
        # Detect header row: must contain at least "ledger" (or "ledger name") and "group"
        if any("ledger" in v for v in row_vals) and any("group" in v for v in row_vals):
            header_row_idx = r_idx
            for col_idx, header_text in enumerate(row_vals, start=1):
                if "ledger" in header_text and "name" in header_text:
                    col_map["ledger_name"] = col_idx
                elif header_text in {"ledger", "particulars", "account"} and "ledger_name" not in col_map:
                    col_map["ledger_name"] = col_idx
                elif "under" == header_text:
                    col_map["under"] = col_idx
                elif "group" in header_text and "ledger_name" not in header_text:
                    col_map["group"] = col_idx
                elif "head" in header_text and "classification" not in header_text:
                    col_map["head"] = col_idx
                elif "classification" in header_text:
                    col_map["classification"] = col_idx
                elif "vertical" in header_text or "business" in header_text:
                    col_map["vertical"] = col_idx
            break

    if header_row_idx is None:
        raise ValueError(
            "Could not locate a valid header row in the 'List of Ledgers' sheet. "
            "The sheet must contain a header row with columns for Ledger Name, Group, Head, and Vertical."
        )

    # Validate required columns are mapped
    for required_key in ("ledger_name", "group", "head", "vertical"):
        if required_key not in col_map:
            raise ValueError(
                f"Required column '{required_key.replace('_', ' ').title()}' not found in the List of Ledgers sheet. "
                f"Found columns: {[str(ws.cell(row=header_row_idx, column=c).value) for c in range(1, ws.max_column + 1)]}"
            )

    mappings: List[LedgerMapping] = []
    for r_idx in range(header_row_idx + 1, ws.max_row + 1):
        name_val = ws.cell(row=r_idx, column=col_map["ledger_name"]).value
        if not name_val or str(name_val).strip() == "":
            continue

        name = str(name_val).strip()
        under_val = ws.cell(row=r_idx, column=col_map["under"]).value if "under" in col_map else None
        group_val = ws.cell(row=r_idx, column=col_map["group"]).value
        head_val = ws.cell(row=r_idx, column=col_map["head"]).value
        classification_val = ws.cell(row=r_idx, column=col_map["classification"]).value if "classification" in col_map else None
        vertical_val = ws.cell(row=r_idx, column=col_map["vertical"]).value

        mappings.append(LedgerMapping(
            ledger_name=name,
            under=str(under_val).strip() if under_val else None,
            group=str(group_val).strip() if group_val else "BS",
            head=str(head_val).strip() if head_val else "",
            classification=str(classification_val).strip() if classification_val else None,
            vertical=str(vertical_val).strip() if vertical_val else "Common"
        ))

    return mappings


from functools import lru_cache

@lru_cache(maxsize=1)
def load_mapped_ledgers(path: Optional[str] = None) -> Dict[str, LedgerMapping]:
    """
    Loads existing ledger mappings from the List of Ledgers sheet.
    If `path` is provided, reads from that file; otherwise falls back to the master template.
    Returns a dict keyed by lowercased ledger name for fast lookups.
    """
    source_path = path if path else TEMPLATE_PATH
    wb = openpyxl.load_workbook(source_path, data_only=True)

    # Find the sheet — template may have trailing space in name
    sheet_name = next(
        (s for s in wb.sheetnames if s.strip().lower() == "list of ledgers"),
        None
    )
    if sheet_name is None:
        raise ValueError(
            f"Sheet 'List of Ledgers' not found in '{os.path.basename(source_path)}'. "
            f"Available sheets: {wb.sheetnames}"
        )

    ws = wb[sheet_name]
    try:
        mappings_list = _parse_ledger_sheet(ws)
    finally:
        wb.close()

    return {m.ledger_name.lower(): m for m in mappings_list}


def parse_ledger_file(file_path: str) -> List[LedgerMapping]:
    """
    Parses an uploaded List of Ledgers Excel file and returns structured LedgerMapping objects.
    Raises ValueError with clear messages if the file format is invalid.
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)

    sheet_name = next(
        (s for s in wb.sheetnames if s.strip().lower() == "list of ledgers"),
        None
    )
    if sheet_name is None:
        available = ", ".join(wb.sheetnames) or "(none)"
        raise ValueError(
            f"The uploaded file does not contain a 'List of Ledgers' sheet. "
            f"Found sheets: {available}. "
            "Please upload the correct MIS workbook that contains this sheet."
        )

    ws = wb[sheet_name]
    try:
        mappings = _parse_ledger_sheet(ws)
    finally:
        wb.close()

    if not mappings:
        raise ValueError(
            "The 'List of Ledgers' sheet was found but contains no ledger rows. "
            "Please check the file and ensure ledger data is present below the header row."
        )

    return mappings


def get_unmapped_ledgers(
    parsed_entries: List[LedgerEntry],
    ledger_path: Optional[str] = None
) -> List[str]:
    """
    Compares parsed trial balance entries with master mappings and returns unmapped ledger names.
    Optionally loads mappings from `ledger_path` instead of the template.
    """
    mapped = load_mapped_ledgers(path=ledger_path)
    unmapped = []
    for entry in parsed_entries:
        name_lower = entry.name.lower()
        if not entry.name or entry.name.startswith(("Total", "Opening", "Closing")) or name_lower == "particulars":
            continue
        if name_lower not in mapped:
            unmapped.append(entry.name)
    return unmapped


def replace_ledger_list_in_template(new_mappings: List[LedgerMapping]) -> None:
    """
    Completely replaces the 'List of Ledgers' sheet data in the master template
    with the provided new_mappings. Preserves all formula columns (cols 9+) for
    existing rows and writes new rows with VLOOKUP formulas. Non-data rows (header
    and summary rows in cols 1-8) are cleared and rewritten cleanly.
    """
    wb = openpyxl.load_workbook(TEMPLATE_PATH, data_only=False)

    sheet_name = next(
        (s for s in wb.sheetnames if s.strip().lower() == "list of ledgers"),
        None
    )
    if sheet_name is None:
        raise ValueError(f"'List of Ledgers' sheet not found in template. Available: {wb.sheetnames}")

    ws = wb[sheet_name]

    # Determine the data start row (first row after headers)
    DATA_START_ROW = 5  # rows 1-4 are title/header rows in the template

    # Clear existing data rows (columns 1-8 only — preserves any side-panel content)
    for r_idx in range(DATA_START_ROW, ws.max_row + 1):
        for c_idx in range(1, 9):
            ws.cell(row=r_idx, column=c_idx).value = None

    # Write new mappings
    for idx, mapping in enumerate(new_mappings):
        row = DATA_START_ROW + idx

        ws.cell(row=row, column=1, value=idx + 1)              # Sl. No.
        ws.cell(row=row, column=2, value=mapping.ledger_name)
        ws.cell(row=row, column=3, value=mapping.under)
        ws.cell(row=row, column=4, value=mapping.group)
        ws.cell(row=row, column=5, value=mapping.head)
        ws.cell(row=row, column=6, value=mapping.classification)
        ws.cell(row=row, column=7, value=mapping.vertical)

        # Write VLOOKUP formulas for monthly TB columns (cols 9-12)
        ws.cell(row=row, column=9,  value=f"=IFERROR(VLOOKUP(B{row},'TB '!$A:$G,7,),0)")
        ws.cell(row=row, column=10, value=f"=IFERROR(VLOOKUP($B{row},'TB '!$4:$1048576,MATCH('List of Ledgers '!J$4,'TB '!$4:$4,0),0),0)")
        ws.cell(row=row, column=11, value=f"=IFERROR(VLOOKUP($B{row},'TB '!$4:$1048576,MATCH('List of Ledgers '!K$4,'TB '!$4:$4,0),0),0)")
        ws.cell(row=row, column=12, value=f"=IFERROR(VLOOKUP(B{row},'TB '!$A:$J,10,),0)")

        # Write VLOOKUP formulas for YTD TB columns (cols 14-17)
        ws.cell(row=row, column=14, value=f"=IFERROR(VLOOKUP($B{row},'TB YTD'!$4:$1048576,MATCH('List of Ledgers '!N$4,'TB YTD'!$4:$4,0),0),0)")
        ws.cell(row=row, column=15, value=f"=IFERROR(VLOOKUP($B{row},'TB YTD'!$4:$1048576,MATCH('List of Ledgers '!O$4,'TB YTD'!$4:$4,0),0),0)")
        ws.cell(row=row, column=16, value=f"=IFERROR(VLOOKUP($B{row},'TB YTD'!$4:$1048576,MATCH('List of Ledgers '!P$4,'TB YTD'!$4:$4,0),0),0)")
        ws.cell(row=row, column=17, value=f"=IFERROR(VLOOKUP($B{row},'TB YTD'!$4:$1048576,MATCH('List of Ledgers '!Q$4,'TB YTD'!$4:$4,0),0),0)")

    wb.save(TEMPLATE_PATH)


def append_new_mappings_to_template(new_mappings: List[LedgerMapping]) -> None:
    """
    Appends new ledger mappings to the template List of Ledgers sheet with formulas.
    Used when the user classifies previously unmapped ledgers.
    """
    wb = openpyxl.load_workbook(TEMPLATE_PATH, data_only=False)

    sheet_name = next(
        (s for s in wb.sheetnames if s.strip().lower() == "list of ledgers"),
        None
    )
    if sheet_name is None:
        raise ValueError(f"'List of Ledgers' sheet not found in template.")

    ws = wb[sheet_name]

    # Find true insertion point (last non-empty row in col 2)
    start_row = ws.max_row + 1
    for r_idx in range(ws.max_row, 4, -1):
        val = ws.cell(row=r_idx, column=2).value
        if val and str(val).strip() != "":
            start_row = r_idx + 1
            break

    for idx, mapping in enumerate(new_mappings):
        row = start_row + idx

        ws.cell(row=row, column=1, value=row - 4)          # Sl. No.
        ws.cell(row=row, column=2, value=mapping.ledger_name)
        ws.cell(row=row, column=3, value=mapping.under)
        ws.cell(row=row, column=4, value=mapping.group)
        ws.cell(row=row, column=5, value=mapping.head)
        ws.cell(row=row, column=6, value=mapping.classification)
        ws.cell(row=row, column=7, value=mapping.vertical)

        ws.cell(row=row, column=9,  value=f"=IFERROR(VLOOKUP(B{row},'TB '!$A:$G,7,),0)")
        ws.cell(row=row, column=10, value=f"=IFERROR(VLOOKUP($B{row},'TB '!$4:$1048576,MATCH('List of Ledgers '!J$4,'TB '!$4:$4,0),0),0)")
        ws.cell(row=row, column=11, value=f"=IFERROR(VLOOKUP($B{row},'TB '!$4:$1048576,MATCH('List of Ledgers '!K$4,'TB '!$4:$4,0),0),0)")
        ws.cell(row=row, column=12, value=f"=IFERROR(VLOOKUP(B{row},'TB '!$A:$J,10,),0)")
        ws.cell(row=row, column=14, value=f"=IFERROR(VLOOKUP($B{row},'TB YTD'!$4:$1048576,MATCH('List of Ledgers '!N$4,'TB YTD'!$4:$4,0),0),0)")
        ws.cell(row=row, column=15, value=f"=IFERROR(VLOOKUP($B{row},'TB YTD'!$4:$1048576,MATCH('List of Ledgers '!O$4,'TB YTD'!$4:$4,0),0),0)")
        ws.cell(row=row, column=16, value=f"=IFERROR(VLOOKUP($B{row},'TB YTD'!$4:$1048576,MATCH('List of Ledgers '!P$4,'TB YTD'!$4:$4,0),0),0)")
        ws.cell(row=row, column=17, value=f"=IFERROR(VLOOKUP($B{row},'TB YTD'!$4:$1048576,MATCH('List of Ledgers '!Q$4,'TB YTD'!$4:$4,0),0),0)")

    wb.save(TEMPLATE_PATH)
