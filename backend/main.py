import os
import uuid
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Optional
import shutil

from models.ledger import LedgerMapping, LedgerEntry, SessionMappingState
from models.pl_data import PLDataResponse
from services.tb_parser import parse_tally_tb
from services.ledger_mapper import get_unmapped_ledgers, append_new_mappings_to_template
from services.ytd_calculator import check_if_tb_has_ytd, roll_forward_ytd
from services.workbook_builder import generate_monthly_workbook
from services.pl_extractor import extract_pl_dashboard

app = FastAPI(title="Tally MIS Automation Pipeline")

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store for mapping state
SESSIONS: Dict[str, Dict] = {}

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "workbooks"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

@app.get("/api/domain-lists")
async def get_domain_lists():
    """Returns domain lists for dropdowns in mapping UI, augmented with existing values in sheet."""
    from services.ledger_mapper import load_mapped_ledgers
    
    # Defaults
    groups = {"BS", "P&L"}
    heads = {
        "Sundry Debtor", "Sundry Creditor", "1. Sales Accounts", 
        "2. Indirect Income", "3. Direct Expense", "5. Purchase Accounts", 
        "6. Indirect Expense"
    }
    verticals = {
        "IT", "Bluestreak", "Spices - Vashi", "Share Trading", 
        "Factory", "Spices - A to Z", "Clarus", "Common"
    }
    classifications = {
        "Accomodation expenses", "Advertisements costs", "Audit Fees", "Bad debt", 
        "Bank charges", "Brokerage and commission", "Bussiness Development costs", 
        "CONSULTANT FEE", "Capital Loss", "Commission", "Conveyance expenses", 
        "Courier charges", "Creative agency charges", "Depreciation", "Dividend ", 
        "Donation", "Electricity charges", "Exhibitions costs", "Exhibtion Income", 
        "Export charges", "Foreign Exchange Gain", "Freight & Shipping charges", 
        "Fuel Expenses", "Indirect Income", "Insurance", "Insurance expenses", 
        "Interest Income", "Interest expense", "Labour charges", "Loading & Unloading charges", 
        "Marketing Expense", "Membership Expenses", "Misc Expenses", "Packing Charges", 
        "Port Expenses", "Printing & Stationery", "Professional charges", 
        "Profit on sale of Investment ", "Purchase", "Rates & Taxes", "Rent expenses", 
        "Repairs & maintenance expenses", "Salary & wages", "Sales", "Share trading expenses", 
        "Short term Capital Gain ", "Staff welfare expenses", "Subscription fees", 
        "Telephone & Internet charges", "Transportation", "Travelling expenses", "Website charges"
    }
    
    # Load mapped ledgers to dynamically extract any custom added values
    try:
        existing = load_mapped_ledgers()
        for mapping in existing.values():
            if mapping.group:
                groups.add(mapping.group)
            if mapping.head:
                heads.add(mapping.head)
            if mapping.vertical:
                verticals.add(mapping.vertical)
            if mapping.classification:
                classifications.add(mapping.classification)
    except Exception as e:
        print(f"Error loading existing mappings for domain lists: {e}")
        
    return {
        "groups": sorted(list(groups)),
        "heads": sorted(list(heads)),
        "verticals": sorted(list(verticals)),
        "classifications": sorted(list(classifications))
    }

@app.post("/api/upload")
async def upload_files(
    file: UploadFile = File(...),
    prior_file: Optional[UploadFile] = File(None),
    month: int = Form(3),
    year: int = Form(2026)
):
    """Handles uploading monthly TB file and optional prior month workbook."""
    session_id = str(uuid.uuid4())
    
    # 1. Save uploaded active monthly file
    file_ext = os.path.splitext(file.filename)[1]
    temp_file_path = os.path.join(UPLOAD_DIR, f"{session_id}_active{file_ext}")
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 2. Save prior month file if provided
    prior_file_path = None
    if prior_file:
        prior_ext = os.path.splitext(prior_file.filename)[1]
        prior_file_path = os.path.join(UPLOAD_DIR, f"{session_id}_prior{prior_ext}")
        with open(prior_file_path, "wb") as buffer:
            shutil.copyfileobj(prior_file.file, buffer)
            
    # 3. Parse trial balance
    try:
        parsed_entries = parse_tally_tb(temp_file_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse active Trial Balance: {str(e)}")
        
    # 4. Check for unmapped ledgers
    unmapped_ledgers = get_unmapped_ledgers(parsed_entries)
    
    # Store session details
    SESSIONS[session_id] = {
        "active_file_path": temp_file_path,
        "prior_file_path": prior_file_path,
        "parsed_entries": parsed_entries,
        "month": month,
        "year": year
    }
    
    if len(unmapped_ledgers) > 0:
        return {
            "success": False,
            "session_id": session_id,
            "unmapped_count": len(unmapped_ledgers),
            "unmapped_ledgers": unmapped_ledgers
        }
        
    # 5. If NO unmapped ledgers, compile workbook immediately!
    return await _process_and_finalize_workbook(session_id)

@app.post("/api/map")
async def submit_mappings(
    session_id: str = Form(...),
    mappings_data: str = Form(...)  # JSON string representing List[LedgerMapping]
):
    """Receives and saves ledger mappings from the user for unmapped accounts."""
    import json
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
        
    try:
        mappings_list = json.loads(mappings_data)
        new_mappings = [LedgerMapping(**m) for m in mappings_list]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid mappings schema: {str(e)}")
        
    # Append mappings to master template list
    append_new_mappings_to_template(new_mappings)
    
    # Re-evaluate session with new mappings applied
    return await _process_and_finalize_workbook(session_id)

async def _process_and_finalize_workbook(session_id: str):
    session = SESSIONS[session_id]
    active_path = session["active_file_path"]
    prior_path = session["prior_file_path"]
    entries = session["parsed_entries"]
    month = session["month"]
    year = session["year"]
    
    # 1. Roll-forward YTD balances if necessary
    has_ytd = check_if_tb_has_ytd(entries)
    if not has_ytd:
        # Calculate YTD cumulative balances by rolling forward from prior month workbook
        entries = roll_forward_ytd(entries, prior_path)
    else:
        # Tally Prime file has YTD data, ensure we fill opening/closing YTD correctly if blank
        for entry in entries:
            if entry.opening_ytd is None:
                entry.opening_ytd = entry.opening or 0.0
            if entry.debit_ytd is None:
                entry.debit_ytd = entry.debit or 0.0
            if entry.credit_ytd is None:
                entry.credit_ytd = entry.credit or 0.0
            if entry.closing_ytd is None:
                entry.closing_ytd = entry.closing or 0.0
                
    # 2. Compile output workbook
    output_filename = f"MIS_Report_{year}_{month:02d}.xlsx"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    generate_monthly_workbook(entries, active_path, output_path)
    
    # Save the output file path in the session for downloading
    session["output_path"] = output_path
    
    # 3. Extract calculated P&L data dynamically
    # Construct month labels
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    month_label = f"{month_names[month-1]}'{str(year)[-2:]}"
    ytd_label = f"YTD'{str(year)[-2:]}"
    
    pl_data = extract_pl_dashboard(
        entries, 
        month_label, 
        ytd_label, 
        has_ytd=(has_ytd or prior_path is not None)
    )
    
    return {
        "success": True,
        "session_id": session_id,
        "output_file": output_filename,
        "pl_data": pl_data
    }

@app.get("/api/download")
async def download_workbook(session_id: str):
    """Serves the generated monthly workbook file."""
    if session_id not in SESSIONS or "output_path" not in SESSIONS[session_id]:
        raise HTTPException(status_code=404, detail="Generated workbook not found.")
        
    file_path = SESSIONS[session_id]["output_path"]
    filename = os.path.basename(file_path)
    return FileResponse(
        path=file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
