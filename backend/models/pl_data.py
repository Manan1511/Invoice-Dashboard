from pydantic import BaseModel
from typing import Dict, List, Optional

class PLRow(BaseModel):
    particulars: str
    values: Dict[str, Optional[float]]
    is_header: bool = False
    is_total: bool = False

class PLBreakdown(BaseModel):
    columns: List[str]  # Vertical headers
    rows: List[PLRow]   # All row entries

class PLDataResponse(BaseModel):
    month_label: str    # e.g., "Mar'26"
    ytd_label: str      # e.g., "YTD'26" (April to Mar)
    month_data: PLBreakdown
    ytd_data: PLBreakdown
    kpis: Dict[str, float]  # e.g., Revenue, Gross Margin %, Net Income, Total Expenses
