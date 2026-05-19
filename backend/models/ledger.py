from pydantic import BaseModel
from typing import Optional, List

class LedgerEntry(BaseModel):
    name: str
    opening: Optional[float] = None
    debit: Optional[float] = None
    credit: Optional[float] = None
    closing: Optional[float] = None
    opening_ytd: Optional[float] = None
    debit_ytd: Optional[float] = None
    credit_ytd: Optional[float] = None
    closing_ytd: Optional[float] = None

class LedgerMapping(BaseModel):
    ledger_name: str
    under: Optional[str] = None
    group: str  # "BS" or "P&L"
    head: str   # e.g., "6. Indirect Expense"
    classification: Optional[str] = None  # e.g., "Salary & wages"
    vertical: str  # e.g., "Bluestreak", "Clarus", "IT", "Factory", "Office", "Common", "Spices - A to Z", "Spices - Vashi", "Share Trading"

class SessionMappingState(BaseModel):
    session_id: str
    month: int
    year: int
    unmapped: List[str]
    mappings: List[LedgerMapping] = []
    parsed_entries: List[LedgerEntry] = []
