import os
import uuid
import json
import asyncio
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Optional
from decimal import Decimal
import shutil

from services.ledger_mapper import (
    load_dynamic_company_mapping, 
    parse_mappings_from_excel,
    save_dynamic_company_mapping,
    CompanyConfiguration, 
    ValidationError, 
    LedgerMapping
)
from services.tb_parser import parse_trial_balance, UnmappedLedgerException
from services.pl_extractor import run_pl_extraction
from services.workbook_builder import construct_dynamic_workbook

app = FastAPI(title="Tally MIS Automation Pipeline")

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected server error occurred. Please try again or contact support.",
            "hint": str(exc)
        }
    )

@app.exception_handler(UnmappedLedgerException)
async def mapping_error_handler(request: Request, exc: UnmappedLedgerException):
    return JSONResponse(
        status_code=200, # Frontend expects 200 with success=False to enter MAPPING mode
        content={
            "success": False,
            "session_id": getattr(exc, "session_id", "unknown"),
            "unmapped_count": len(exc.unmapped_ledgers),
            "unmapped_ledgers": exc.unmapped_ledgers
        }
    )

SESSIONS: Dict[str, Dict] = {}
PROGRESS_STATES: Dict[str, Dict] = {}

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "workbooks"
CONFIG_DIR = "config"
MASTER_MAPPING_PATH = "config/master_mapping.json"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

_ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}

def _validate_excel_upload(upload: UploadFile, label: str = "file") -> None:
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {label}: '{upload.filename}' is not an Excel/CSV file."
        )

@app.get("/api/domain-lists")
async def get_domain_lists():
    groups = {"BS", "P&L"}
    heads = {
        "Sundry Debtor", "Sundry Creditor", "1. Sales Accounts",
        "2. Indirect Income", "3. Direct Expense", "5. Purchase Accounts",
        "6. Indirect Expense"
    }
    verticals = {"Common"}
    classifications = set()

    try:
        config = load_dynamic_company_mapping(MASTER_MAPPING_PATH)
        for mapping in config.mappings.values():
            if mapping.group: groups.add(mapping.group)
            if mapping.head: heads.add(mapping.head)
            if mapping.vertical: verticals.add(mapping.vertical)
            if mapping.classification: classifications.add(mapping.classification)
    except Exception as e:
        print(f"Error loading existing mappings for domain lists: {e}")

    return {
        "groups": sorted(list(groups)),
        "heads": sorted(list(heads)),
        "verticals": sorted(list(verticals)),
        "classifications": sorted(list(classifications))
    }

@app.post("/api/parse-ledgers")
async def parse_ledger_upload(ledger_file: UploadFile = File(...)):
    _validate_excel_upload(ledger_file, "List of Ledgers")
    ext = os.path.splitext(ledger_file.filename or "")[1].lower()
    temp_id = str(uuid.uuid4())
    temp_path = os.path.join(UPLOAD_DIR, f"{temp_id}_ledgers{ext}")

    try:
        with open(temp_path, "wb") as buf:
            shutil.copyfileobj(ledger_file.file, buf)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        config = parse_mappings_from_excel(temp_path)
    except Exception as e:
        os.remove(temp_path)
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ledger_session_id": temp_id,
        "ledger_count": len(config.mappings),
        "ledgers": [{"ledger_name": m.name, "under": m.group, "group": m.group, "head": m.head, "classification": m.classification, "vertical": m.vertical} for m in config.mappings.values()]
    }

@app.post("/api/confirm-ledgers")
async def confirm_ledger_list(
    ledger_session_id: str = Form(...),
    ledgers_data: str = Form(...) 
):
    try:
        raw_list = json.loads(ledgers_data)
        new_mappings = [LedgerMapping(
            name=item.get("ledger_name", ""),
            vertical=item.get("vertical", "Common"),
            head=item.get("head", ""),
            group=item.get("group", ""),
            classification=item.get("classification", "")
        ) for item in raw_list]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid ledger schema: {e}")

    if not new_mappings:
        raise HTTPException(status_code=400, detail="Cannot save an empty ledger list.")

    try:
        save_dynamic_company_mapping(MASTER_MAPPING_PATH, new_mappings)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "success": True,
        "saved_count": len(new_mappings),
        "message": f"Master mappings updated with {len(new_mappings)} entries."
    }

@app.post("/api/upload-ledgers-direct")
async def upload_ledgers_direct(ledger_file: UploadFile = File(...)):
    _validate_excel_upload(ledger_file, "List of Ledgers")
    ext = os.path.splitext(ledger_file.filename or "")[1].lower()
    temp_id = str(uuid.uuid4())
    temp_path = os.path.join(UPLOAD_DIR, f"{temp_id}_ledgers{ext}")

    with open(temp_path, "wb") as buf:
        shutil.copyfileobj(ledger_file.file, buf)

    try:
        config = parse_mappings_from_excel(temp_path)
        new_mappings = list(config.mappings.values())
        save_dynamic_company_mapping(MASTER_MAPPING_PATH, new_mappings)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return {
        "success": True,
        "saved_count": len(new_mappings),
        "message": f"Master mapping updated directly with {len(new_mappings)} entries."
    }

@app.post("/api/upload")
async def upload_files(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    prior_file: Optional[UploadFile] = File(None),
    month: int = Form(3),
    year: int = Form(2026),
    closing_stock: float = Form(0.0)
):
    _validate_excel_upload(file, "Trial Balance")
    session_id = str(uuid.uuid4())
    file_ext = os.path.splitext(file.filename)[1].lower()
    temp_file_path = os.path.join(UPLOAD_DIR, f"{session_id}_active{file_ext}")
    
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Attempt to read "List of Ledgers" directly from the uploaded TB file!
    try:
        embedded_config = parse_mappings_from_excel(temp_file_path)
        if len(embedded_config.mappings) > 0:
            # Auto-learn and merge the embedded mappings into the global master database
            save_dynamic_company_mapping(MASTER_MAPPING_PATH, list(embedded_config.mappings.values()))
    except Exception:
        pass # If it doesn't exist, we just fall back
        
    config = load_dynamic_company_mapping(MASTER_MAPPING_PATH)

    try:
        parsed_entries = parse_trial_balance(temp_file_path, config)
    except UnmappedLedgerException as exc:
        exc.session_id = session_id
        
        SESSIONS[session_id] = {
            "temp_file_path": temp_file_path,
            "month": month,
            "year": year
        }
        raise exc
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    SESSIONS[session_id] = {
        "parsed_entries": parsed_entries,
        "config": config,
        "month": month,
        "year": year,
        "closing_stock": Decimal(str(closing_stock))
    }
    
    PROGRESS_STATES[session_id] = {"status": "processing", "step": "PARSING_TB", "result": None, "error": None}
    background_tasks.add_task(_process_and_finalize_workbook, session_id)
    return {"success": True, "session_id": session_id, "status": "processing"}

@app.post("/api/map")
async def submit_mappings(
    background_tasks: BackgroundTasks,
    session_id: str = Form(...),
    mappings_data: str = Form(...)
):
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found.")
        
    session = SESSIONS[session_id]
    
    try:
        raw_list = json.loads(mappings_data)
        new_mappings = [LedgerMapping(
            name=item.get("ledger_name", ""),
            vertical=item.get("vertical", "Common"),
            head=item.get("head", ""),
            group=item.get("group", ""),
            classification=item.get("classification", "")
        ) for item in raw_list]
        
        save_dynamic_company_mapping(MASTER_MAPPING_PATH, new_mappings)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Reload config and try parsing again
    config = load_dynamic_company_mapping(MASTER_MAPPING_PATH)
    try:
        parsed_entries = parse_trial_balance(session["temp_file_path"], config)
    except UnmappedLedgerException as exc:
        exc.session_id = session_id
        raise exc
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    session["parsed_entries"] = parsed_entries
    session["config"] = config
    
    PROGRESS_STATES[session_id] = {"status": "processing", "step": "PARSING_TB", "result": None, "error": None}
    background_tasks.add_task(_process_and_finalize_workbook, session_id)
    return {"success": True, "session_id": session_id, "status": "processing"}

async def _process_and_finalize_workbook(session_id: str):
    try:
        session = SESSIONS[session_id]
        parsed_entries = session["parsed_entries"]
        config = session["config"]
        year = session["year"]
        month = session["month"]
        closing_stock = session.get("closing_stock", Decimal('0.00'))

        PROGRESS_STATES[session_id]["step"] = "EXTRACTING_DASHBOARD"
        await asyncio.sleep(0.5)

        pl_data = await asyncio.to_thread(run_pl_extraction, parsed_entries, config, closing_stock)

        PROGRESS_STATES[session_id]["step"] = "GENERATING_EXCEL"
        await asyncio.sleep(0.5)

        output_filename = f"MIS_Report_{year}_{month:02d}.xlsx"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        
        await asyncio.to_thread(construct_dynamic_workbook, pl_data, output_path)

        session["output_path"] = output_path
        
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        month_label = f"{month_names[month-1]}'{str(year)[-2:]}"
        
        # Prepare frontend friendly format: we need month_data with rows and columns, and KPIs
        # For simplicity, returning empty layout or mapped format
        # The frontend expects a PLBreakdown format.
        
        rows = []
        for particular in pl_data["grid"].keys():
            rows.append({
                "particulars": particular,
                "values": pl_data["grid"][particular],
                "is_header": particular.startswith("Total") or "Margin" in particular,
                "is_total": particular == "Net Profit"
            })
            
        frontend_pl_data = {
            "month_label": month_label,
            "ytd_label": "YTD",
            "month_data": {
                "columns": pl_data["revenue_verticals"] + pl_data["cost_verticals"] + ["Common"],
                "rows": rows
            },
            "ytd_data": {
                "columns": pl_data["revenue_verticals"] + pl_data["cost_verticals"] + ["Common"],
                "rows": rows
            },
            "kpis": {}
        }
        
        PROGRESS_STATES[session_id]["result"] = {
            "success": True,
            "session_id": session_id,
            "output_file": output_filename,
            "pl_data": frontend_pl_data
        }
        PROGRESS_STATES[session_id]["status"] = "completed"

    except Exception as e:
        PROGRESS_STATES[session_id]["status"] = "error"
        PROGRESS_STATES[session_id]["error"] = str(e)

@app.get("/api/status/{session_id}")
async def stream_status(session_id: str):
    async def event_generator():
        while True:
            if session_id not in PROGRESS_STATES:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                break
            state = PROGRESS_STATES[session_id]
            yield f"data: {json.dumps(state, default=float)}\n\n"
            if state["status"] in ["completed", "error"]:
                await asyncio.sleep(2)
                break
            await asyncio.sleep(0.5)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/download")
async def download_workbook(session_id: str):
    if session_id not in SESSIONS or "output_path" not in SESSIONS[session_id]:
        raise HTTPException(status_code=404, detail="Workbook not found.")
    file_path = SESSIONS[session_id]["output_path"]
    return FileResponse(path=file_path, filename=os.path.basename(file_path))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
