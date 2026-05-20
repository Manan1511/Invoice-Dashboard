from pydantic import BaseModel
from typing import Optional, List
from decimal import Decimal

class LedgerEntry(BaseModel):
    name: str
    opening: Optional[Decimal] = None
    debit: Optional[Decimal] = None
    credit: Optional[Decimal] = None
    closing: Optional[Decimal] = None
    opening_net: Optional[Decimal] = None
    debit_net: Optional[Decimal] = None
    credit_net: Optional[Decimal] = None
    closing_net: Optional[Decimal] = None
    opening_ytd: Optional[Decimal] = None
    debit_ytd: Optional[Decimal] = None
    credit_ytd: Optional[Decimal] = None
    closing_ytd: Optional[Decimal] = None

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

class MappingError(Exception):
    def __init__(self, unmapped_ledgers: List[str], message: Optional[str] = None, session_id: Optional[str] = None):
        self.unmapped_ledgers = unmapped_ledgers
        self.session_id = session_id
        self.message = message or f"Unmapped active ledgers encountered: {', '.join(unmapped_ledgers)}"
        super().__init__(self.message)
