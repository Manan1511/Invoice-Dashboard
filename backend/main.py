import os
import uuid
import json
import asyncio
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Optional
import shutil

from models.ledger import LedgerMapping, LedgerEntry, SessionMappingState
from models.pl_data import PLDataResponse
from services.tb_parser import parse_tally_tb
from services.ledger_mapper import (
    get_unmapped_ledgers,
    append_new_mappings_to_template,
    parse_ledger_file,
    replace_ledger_list_in_template,
    load_mapped_ledgers,
)
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

# Global unhandled exception handler – returns structured JSON instead of a raw 500 HTML page
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected server error occurred. Please try again or contact support.",
            "hint": str(exc)
        }
    )

# In-memory session store for mapping state
SESSIONS: Dict[str, Dict] = {}
PROGRESS_STATES: Dict[str, Dict] = {}

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "workbooks"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Constants for file validation
_ALLOWED_EXTENSIONS = {".xlsx", ".xls"}
_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


def _validate_excel_upload(upload: UploadFile, label: str = "file") -> None:
    """Validates that an uploaded file is an acceptable Excel file within size limits."""
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {label}: '{upload.filename}' is not an Excel file. Please upload a .xlsx or .xls file."
        )
    content_length = upload.size
    if content_length is not None and content_length > _MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"The {label} '{upload.filename}' is too large ({content_length // (1024*1024)} MB). Maximum allowed size is 50 MB."
        )


@app.get("/api/domain-lists")
async def get_domain_lists():
    """Returns domain lists for dropdowns in mapping UI, augmented with existing values in sheet."""
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


@app.post("/api/parse-ledgers")
async def parse_ledger_upload(ledger_file: UploadFile = File(...)):
    """
    Parses an uploaded List of Ledgers Excel file.
    Returns all ledger rows for the user to review and edit in the LEDGER_REVIEW stage.
    Does NOT modify the template — that happens only on /api/confirm-ledgers.
    """
    _validate_excel_upload(ledger_file, "List of Ledgers")

    # Save uploaded file to a temp path
    ext = os.path.splitext(ledger_file.filename or "")[1].lower()
    temp_id = str(uuid.uuid4())
    temp_path = os.path.join(UPLOAD_DIR, f"{temp_id}_ledgers{ext}")

    try:
        with open(temp_path, "wb") as buf:
            shutil.copyfileobj(ledger_file.file, buf)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not save uploaded ledger file: {e}")

    try:
        mappings = parse_ledger_file(temp_path)
    except ValueError as e:
        # Clean up temp file on validation error
        os.remove(temp_path)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        os.remove(temp_path)
        raise HTTPException(status_code=500, detail=f"Unexpected error parsing ledger file: {e}")

    # Keep the temp file in session for reference (will be deleted after confirm)
    ledger_session_id = temp_id

    return {
        "ledger_session_id": ledger_session_id,
        "ledger_count": len(mappings),
        "ledgers": [m.model_dump() for m in mappings]
    }


@app.post("/api/confirm-ledgers")
async def confirm_ledger_list(
    ledger_session_id: str = Form(...),
    ledgers_data: str = Form(...)  # JSON array of LedgerMapping dicts (after user edits)
):
    """
    Receives the final (possibly edited) list of ledgers from the frontend.
    Permanently replaces the 'List of Ledgers' sheet in the master template.
    Returns confirmation and the updated ledger count.
    """
    try:
        raw_list = json.loads(ledgers_data)
        confirmed_mappings = [LedgerMapping(**item) for item in raw_list]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid ledger data schema: {e}")

    if not confirmed_mappings:
        raise HTTPException(
            status_code=400,
            detail="Cannot save an empty ledger list. Please provide at least one ledger entry."
        )

    try:
        replace_ledger_list_in_template(confirmed_mappings)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update master template: {e}")

    # Clean up temp ledger file if it exists
    for ext in (".xlsx", ".xls"):
        temp_path = os.path.join(UPLOAD_DIR, f"{ledger_session_id}_ledgers{ext}")
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return {
        "success": True,
        "saved_count": len(confirmed_mappings),
        "message": f"Master template updated with {len(confirmed_mappings)} ledger entries."
    }


@app.post("/api/upload-ledgers-direct")
async def upload_ledgers_direct(ledger_file: UploadFile = File(...)):
    """
    Directly parses an uploaded List of Ledgers Excel file and permanently
    replaces the 'List of Ledgers' sheet in the master template.
    Bypasses the manual LEDGER_REVIEW grid.
    """
    _validate_excel_upload(ledger_file, "List of Ledgers")

    ext = os.path.splitext(ledger_file.filename or "")[1].lower()
    temp_id = str(uuid.uuid4())
    temp_path = os.path.join(UPLOAD_DIR, f"{temp_id}_ledgers_direct{ext}")

    try:
        with open(temp_path, "wb") as buf:
            shutil.copyfileobj(ledger_file.file, buf)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not save uploaded ledger file: {e}")

    try:
        mappings = parse_ledger_file(temp_path)
        replace_ledger_list_in_template(mappings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error processing ledger file: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return {
        "success": True,
        "saved_count": len(mappings),
        "message": f"Master template updated directly with {len(mappings)} ledger entries."
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
    """Handles uploading monthly TB file and optional prior month workbook."""
    # 1. Validate uploaded files before doing anything
    _validate_excel_upload(file, "Trial Balance")
    if prior_file and prior_file.filename:
        _validate_excel_upload(prior_file, "Prior Month Workbook")

    # Validate month and year ranges
    if not (1 <= month <= 12):
        raise HTTPException(status_code=422, detail="Month must be between 1 and 12.")
    if not (2000 <= year <= 2100):
        raise HTTPException(status_code=422, detail="Year must be a valid 4-digit year between 2000 and 2100.")

    session_id = str(uuid.uuid4())

    # 2. Save uploaded active monthly file
    file_ext = os.path.splitext(file.filename)[1].lower()
    temp_file_path = os.path.join(UPLOAD_DIR, f"{session_id}_active{file_ext}")
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not save the uploaded file: {str(e)}")

    # 3. Save prior month file if provided
    prior_file_path = None
    if prior_file and prior_file.filename:
        prior_ext = os.path.splitext(prior_file.filename)[1].lower()
        prior_file_path = os.path.join(UPLOAD_DIR, f"{session_id}_prior{prior_ext}")
        try:
            with open(prior_file_path, "wb") as buffer:
                shutil.copyfileobj(prior_file.file, buffer)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Could not save the prior month workbook: {str(e)}")

    # 4. Parse trial balance
    try:
        parsed_entries = parse_tally_tb(temp_file_path)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse the Trial Balance. Ensure it is a valid Tally Prime Excel export with a 'TB' or 'Trial Balance' sheet. Details: {str(e)}"
        )

    if not parsed_entries:
        raise HTTPException(
            status_code=400,
            detail="No ledger entries were found in the uploaded Trial Balance. Check that the file has a 'TB' sheet with data rows starting from row 5."
        )

    # 5. Check for unmapped ledgers (always against the current master template)
    unmapped_ledgers = get_unmapped_ledgers(parsed_entries)

    # Store session details
    SESSIONS[session_id] = {
        "active_file_path": temp_file_path,
        "prior_file_path": prior_file_path,
        "parsed_entries": parsed_entries,
        "month": month,
        "year": year,
        "closing_stock": closing_stock
    }

    if len(unmapped_ledgers) > 0:
        return {
            "success": False,
            "session_id": session_id,
            "unmapped_count": len(unmapped_ledgers),
            "unmapped_ledgers": unmapped_ledgers
        }

    # 6. If NO unmapped ledgers, compile workbook immediately!
    PROGRESS_STATES[session_id] = {"status": "processing", "step": "PARSING_TB", "result": None, "error": None}
    background_tasks.add_task(_process_and_finalize_workbook, session_id)
    return {
        "success": True,
        "session_id": session_id,
        "status": "processing"
    }


@app.post("/api/map")
async def submit_mappings(
    background_tasks: BackgroundTasks,
    session_id: str = Form(...),
    mappings_data: str = Form(...)  # JSON string representing List[LedgerMapping]
):
    """Receives and saves ledger mappings from the user for unmapped accounts."""
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
    PROGRESS_STATES[session_id] = {"status": "processing", "step": "ROLL_FORWARD_YTD", "result": None, "error": None}
    background_tasks.add_task(_process_and_finalize_workbook, session_id)
    return {
        "success": True,
        "session_id": session_id,
        "status": "processing"
    }


async def _process_and_finalize_workbook(session_id: str):
    try:
        session = SESSIONS[session_id]
        active_path = session["active_file_path"]
        prior_path = session["prior_file_path"]
        entries = session["parsed_entries"]
        month = session["month"]
        year = session["year"]

        PROGRESS_STATES[session_id]["step"] = "ROLL_FORWARD_YTD"
        await asyncio.sleep(0.5)

        # 1. Roll-forward YTD balances if necessary
        has_ytd = check_if_tb_has_ytd(entries)
        try:
            if not has_ytd:
                entries = await asyncio.to_thread(roll_forward_ytd, entries, prior_path, month)
            else:
                for entry in entries:
                    if entry.opening_ytd is None:
                        entry.opening_ytd = entry.opening_net if entry.opening_net is not None else (entry.opening or 0.0)
                    if entry.debit_ytd is None:
                        entry.debit_ytd = entry.debit_net if entry.debit_net is not None else (entry.debit or 0.0)
                    if entry.credit_ytd is None:
                        entry.credit_ytd = entry.credit_net if entry.credit_net is not None else (entry.credit or 0.0)
                    if entry.closing_ytd is None:
                        entry.closing_ytd = entry.closing_net if entry.closing_net is not None else (entry.closing or 0.0)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"YTD roll-forward calculation failed. Ensure the prior month workbook has a valid 'List of Ledgers' sheet. Details: {str(e)}"
            )

        PROGRESS_STATES[session_id]["step"] = "GENERATING_EXCEL"
        await asyncio.sleep(0.5)

        # 2. Compile output workbook
        output_filename = f"MIS_Report_{year}_{month:02d}.xlsx"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        try:
            await asyncio.to_thread(
                generate_monthly_workbook,
                entries,
                active_path,
                output_path,
                month,
                year,
                session.get("closing_stock", 0.0)
            )
        except FileNotFoundError:
            raise HTTPException(
                status_code=500,
                detail="MIS template file not found. Please ensure 'templates/MIS_template.xlsx' exists in the server directory."
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Excel workbook generation failed: {str(e)}"
            )

        # Save the output file path in the session for downloading
        session["output_path"] = output_path

        PROGRESS_STATES[session_id]["step"] = "EXTRACTING_DASHBOARD"
        await asyncio.sleep(0.5)

        # 3. Extract calculated P&L data dynamically
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        month_label = f"{month_names[month-1]}'{str(year)[-2:]}"
        ytd_label = f"YTD'{str(year)[-2:]}"

        try:
            pl_data = await asyncio.to_thread(
                extract_pl_dashboard,
                entries,
                month_label,
                ytd_label,
                (has_ytd or prior_path is not None),
                session.get("closing_stock", 0.0)
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Dashboard P&L computation failed. Check that all ledger mappings are correctly classified. Details: {str(e)}"
            )

        PROGRESS_STATES[session_id]["result"] = {
            "success": True,
            "session_id": session_id,
            "output_file": output_filename,
            "pl_data": pl_data.model_dump() if hasattr(pl_data, "model_dump") else pl_data.dict()
        }
        PROGRESS_STATES[session_id]["status"] = "completed"

    except HTTPException as he:
        PROGRESS_STATES[session_id]["status"] = "error"
        PROGRESS_STATES[session_id]["error"] = he.detail
    except Exception as e:
        PROGRESS_STATES[session_id]["status"] = "error"
        PROGRESS_STATES[session_id]["error"] = f"An unexpected error occurred: {str(e)}"

@app.get("/api/status/{session_id}")
async def stream_status(session_id: str):
    async def event_generator():
        while True:
            if session_id not in PROGRESS_STATES:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                break
            state = PROGRESS_STATES[session_id]
            yield f"data: {json.dumps(state)}\n\n"
            if state["status"] in ["completed", "error"]:
                # Keep the connection open briefly so the frontend can receive the message
                # and call eventSource.close() cleanly before the server terminates the TCP socket.
                # This prevents spurious 'onerror' events in the browser.
                await asyncio.sleep(2)
                break
            await asyncio.sleep(0.5)
    return StreamingResponse(event_generator(), media_type="text/event-stream")


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
