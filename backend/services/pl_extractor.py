import openpyxl
from typing import List, Dict, Optional, Any
from models.ledger import LedgerMapping, LedgerEntry, MappingError
from models.pl_data import PLDataResponse, PLBreakdown, PLRow
from services.ledger_mapper import load_mapped_ledgers, clean_ledger_name

from decimal import Decimal, ROUND_HALF_UP


# Shared Constants
ALLOCATION_ROW_KEY = "Common Allocation"

def get_alloc_row_key(cc: str) -> str:
    if cc == 'Common':
        return ALLOCATION_ROW_KEY
    return f"Allocation of {cc}"

# Helper to convert to Decimal
def _to_dec(val) -> Decimal:
    if val is None:
        return Decimal('0.00')
    try:
        return Decimal(str(val)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except:
        return Decimal('0.00')

def extract_pl_dashboard(
    parsed_entries: List[LedgerEntry],
    month_label: str = "Mar'26",
    ytd_label: str = "YTD'26",
    has_ytd: bool = True,
    closing_stock: float = 0.0
) -> PLDataResponse:
    """
    Refactored dynamic and data-driven P&L extraction and cost allocation engine.
    Calculates P&L breakdown and dynamic shared cost allocations based solely on mapping metadata.
    """
    # 1. Load and clean active mappings
    mappings = load_mapped_ledgers()

    unmapped_ledgers = []
    # CRITICAL ERROR TRAP: Detect non-zero balance ledgers that are not mapped
    for entry in parsed_entries:
        if not entry.name or entry.name.startswith(("Total", "Opening", "Closing")):
            continue
        name_clean = clean_ledger_name(entry.name)
        if name_clean in {"particulars", "grand total", "total", "grand", "net profit", "net loss"}:
            continue

        # Check if ledger has non-zero balance
        has_balance = False
        for val in [entry.closing, entry.closing_net, entry.closing_ytd, entry.opening, entry.opening_net, entry.opening_ytd]:
            if val is not None and abs(val) > Decimal("0.001"):
                has_balance = True
                break

        if has_balance and name_clean not in mappings:
            unmapped_ledgers.append(entry.name)

    if unmapped_ledgers:
        raise MappingError(unmapped_ledgers=unmapped_ledgers)

    # 2. Extract Business Verticals dynamically
    # Clean and normalize vertical names (standard cost centers normalized to title case)
    for m in mappings.values():
        if m.vertical:
            m.vertical = m.vertical.strip().title()
        else:
            m.vertical = "Common"

    all_verticals = {m.vertical.strip().title() for m in mappings.values() if m.vertical}
    if not all_verticals:
        all_verticals = {"Common"}

    # Classify into Revenue Centers vs Cost Centers
    revenue_centers = set()
    for m in mappings.values():
        if m.head == "1. Sales Accounts" and m.vertical:
            revenue_centers.add(m.vertical.strip().title())

    # Protect standard shared cost centers from being classified as revenue centers
    revenue_centers = {rc.strip().title() for rc in revenue_centers if rc.strip().title().lower() not in {"factory", "office", "common"}}

    cost_centers = {cc.strip().title() for cc in (all_verticals - revenue_centers)}

    # Sort centers alphabetically for deterministic layout
    sorted_revenue_centers = sorted(list({rc.strip().title() for rc in revenue_centers}))
    sorted_cost_centers = sorted(list({cc.strip().title() for cc in cost_centers}))

    # Dynamic Column Structure
    has_share_trading = 'Share Trading' in all_verticals
    if has_share_trading:
        operating_revenue_centers = [r for r in sorted_revenue_centers if r != 'Share Trading']
        operating_cost_centers = [c for c in sorted_cost_centers if c != 'Share Trading']
        
        all_cols = (
            operating_revenue_centers + 
            operating_cost_centers + 
            ['Total (without share trading)', 'Share Trading', 'Total (including share trading)']
        )
        operating_verticals = operating_revenue_centers + operating_cost_centers
    else:
        all_cols = sorted_revenue_centers + sorted_cost_centers + ['Total']
        operating_verticals = sorted_revenue_centers + sorted_cost_centers

    # Dynamic categories from mappings
    direct_expense_items = sorted(list({
        m.classification.strip() for m in mappings.values()
        if m.head == "3. Direct Expense" and m.classification and m.classification.strip()
    }))
    if not direct_expense_items:
        direct_expense_items = ['Direct Expense']

    indirect_income_items = sorted(list({
        m.classification.strip() for m in mappings.values()
        if m.head == "2. Indirect Income" and m.classification and m.classification.strip()
    }))
    if not indirect_income_items:
        indirect_income_items = ['Indirect Income']

    indirect_expense_items = sorted(list({
        m.classification.strip() for m in mappings.values()
        if m.head == "6. Indirect Expense" and m.classification and m.classification.strip()
    }))
    if not indirect_expense_items:
        indirect_expense_items = ['Misc Expenses']

    # Dynamic allocation rows
    allocation_rows = [get_alloc_row_key(cc) for cc in sorted_cost_centers]

    # Full category list
    all_categories = (
        ['Sales', 'Less: COGS', '3. Direct Expense'] + 
        direct_expense_items + 
        ['Gross margin', 'Gross margin %', 'Indirect Income'] + 
        indirect_income_items + 
        ['Net income', 'Net allocable income', '6. Indirect Expense'] + 
        indirect_expense_items + 
        ['Indirect costs'] + 
        allocation_rows + 
        ['Total indirect costs', 'Profit/ (loss) before tax', 'Net margin %']
    )

    # Initialize monthly and YTD aggregation structures
    monthly_data: Dict[str, Dict[str, Decimal]] = {
        cat: {col: Decimal('0.00') for col in all_cols} for cat in all_categories
    }
    monthly_data['1. Sales Accounts'] = {col: Decimal('0.00') for col in all_cols}

    ytd_data: Dict[str, Dict[str, Decimal]] = {
        cat: {col: Decimal('0.00') for col in all_cols} for cat in all_categories
    }
    ytd_data['1. Sales Accounts'] = {col: Decimal('0.00') for col in all_cols}

    # Aggregate ledger entries
    # Aggregate ledger entries using clean_ledger_name for standard matching
    entries_map = {clean_ledger_name(e.name): e for e in parsed_entries}

    for ledger_name_clean, mapping in mappings.items():
        entry = entries_map.get(ledger_name_clean)
        if not entry:
            continue

        v = mapping.vertical.strip().title() if mapping.vertical else 'Common'
        if v not in all_cols:
            v = 'Common'

        # Monthly net movement
        op_val = _to_dec(entry.opening_net if entry.opening_net is not None else entry.opening)
        cl_val = _to_dec(entry.closing_net if entry.closing_net is not None else entry.closing)
        val_month = cl_val - op_val

        # YTD closing
        val_ytd = _to_dec(entry.closing_ytd)

        # Apply sign corrections for revenue and income
        if mapping.head in {"1. Sales Accounts", "2. Indirect Income"}:
            val_month = -val_month
            val_ytd = -val_ytd

        if mapping.head == "1. Sales Accounts":
            monthly_data['Sales'][v] += val_month
            ytd_data['Sales'][v] += val_ytd
            monthly_data['1. Sales Accounts'][v] += val_month
            ytd_data['1. Sales Accounts'][v] += val_ytd

        elif mapping.head == "3. Direct Expense":
            classification = (mapping.classification or 'Direct Expense').strip()
            if classification not in monthly_data:
                classification = 'Direct Expense'
            monthly_data[classification][v] += val_month
            ytd_data[classification][v] += val_ytd

        elif mapping.head == "5. Purchase Accounts":
            # COGS Purchases accumulator
            if 'COGS_Purchases' not in monthly_data:
                monthly_data['COGS_Purchases'] = {col: Decimal('0.00') for col in all_cols}
                ytd_data['COGS_Purchases'] = {col: Decimal('0.00') for col in all_cols}
            monthly_data['COGS_Purchases'][v] += val_month
            ytd_data['COGS_Purchases'][v] += val_ytd

        elif mapping.head == "2. Indirect Income":
            classification = (mapping.classification or 'Indirect Income').strip()
            if classification not in monthly_data:
                classification = 'Indirect Income'
            monthly_data[classification][v] += val_month
            ytd_data[classification][v] += val_ytd

        elif mapping.head == "6. Indirect Expense":
            classification = (mapping.classification or 'Misc Expenses').strip()
            if classification not in monthly_data:
                classification = 'Misc Expenses'
            monthly_data[classification][v] += val_month
            ytd_data[classification][v] += val_ytd

    # Calculate stock & COGS and perform roll-ups
    for is_ytd in [False, True]:
        data = ytd_data if is_ytd else monthly_data

        # Sum Direct Expenses
        for v in all_cols:
            data['3. Direct Expense'][v] = sum(data[cat][v] for cat in direct_expense_items if cat in data)

        # COGS Calculations
        total_op_stock = {col: Decimal('0.00') for col in all_cols}
        total_cl_stock = {col: Decimal('0.00') for col in all_cols}

        for ledger_name, mapping in mappings.items():
            if mapping.classification == 'Opening Stock' or mapping.head == 'Stock-in-hand':
                entry = entries_map.get(ledger_name)
                if entry:
                    v = mapping.vertical.strip().title() if mapping.vertical else 'Common'
                    if v not in all_cols:
                        v = 'Common'
                    total_op_stock[v] += _to_dec(entry.opening if not is_ytd else (entry.opening_ytd or Decimal('0.00')))
                    total_cl_stock[v] += _to_dec(entry.closing if not is_ytd else (entry.closing_ytd or Decimal('0.00')))

        # Stock override target
        target_stock_vertical = 'Factory' if 'Factory' in all_verticals else (sorted_cost_centers[0] if sorted_cost_centers else 'Common')

        for v in all_cols:
            final_cl = _to_dec(closing_stock) if (closing_stock > 0.0 and v == target_stock_vertical) else total_cl_stock[v]
            stock_change = total_op_stock[v] - final_cl
            purch = data.get('COGS_Purchases', {}).get(v, Decimal('0.00'))
            data['Less: COGS'][v] = purch + stock_change

        # Calculate totals without share trading
        if has_share_trading:
            for cat in ['Sales', 'Less: COGS', '3. Direct Expense'] + direct_expense_items:
                data[cat]['Total (without share trading)'] = sum(data[cat][v] for v in operating_verticals)
                data[cat]['Total (including share trading)'] = data[cat]['Total (without share trading)'] + data[cat]['Share Trading']
        else:
            for cat in ['Sales', 'Less: COGS', '3. Direct Expense'] + direct_expense_items:
                data[cat]['Total'] = sum(data[cat][v] for v in sorted_revenue_centers + sorted_cost_centers)

        # Calculate Gross Margin
        for v in all_cols:
            data['Gross margin'][v] = data['Sales'][v] - data['Less: COGS'][v] - data['3. Direct Expense'][v]
            if abs(data['Sales'][v]) > Decimal('0.01'):
                data['Gross margin %'][v] = data['Gross margin'][v] / data['Sales'][v]
            else:
                data['Gross margin %'][v] = Decimal('0.00')

        # Sum Indirect Income
        for v in all_cols:
            data['Indirect Income'][v] = sum(data[cat][v] for cat in indirect_income_items if cat in data)

        if has_share_trading:
            for cat in ['Indirect Income'] + indirect_income_items:
                data[cat]['Total (without share trading)'] = sum(data[cat][v] for v in operating_verticals)
                data[cat]['Total (including share trading)'] = data[cat]['Total (without share trading)'] + data[cat]['Share Trading']
        else:
            for cat in ['Indirect Income'] + indirect_income_items:
                data[cat]['Total'] = sum(data[cat][v] for v in sorted_revenue_centers + sorted_cost_centers)

        # Calculate Net Income before indirect expenses
        for v in all_cols:
            data['Net income'][v] = data['Gross margin'][v] + data['Indirect Income'][v]
            data['Net allocable income'][v] = data['Net income'][v]

        # Sum Indirect Expenses
        for v in all_cols:
            data['6. Indirect Expense'][v] = sum(data[cat][v] for cat in indirect_expense_items if cat in data)
            data['Indirect costs'][v] = data['6. Indirect Expense'][v]

        if has_share_trading:
            for cat in ['6. Indirect Expense', 'Indirect costs']:
                data[cat]['Total (without share trading)'] = sum(data[cat][v] for v in operating_verticals)
                data[cat]['Total (including share trading)'] = data[cat]['Total (without share trading)'] + data[cat]['Share Trading']
        else:
            for cat in ['6. Indirect Expense', 'Indirect costs']:
                data[cat]['Total'] = sum(data[cat][v] for v in sorted_revenue_centers + sorted_cost_centers)

        # 4. Proportional Cost Allocation Engine
        # Safely compute the revenue pool using floored individual vertical revenues
        revenue_verticals = [rc for rc in sorted_revenue_centers]
        total_revenue_pool = sum(max(Decimal('0.00'), data['1. Sales Accounts'][rc]) for rc in revenue_verticals)

        for cc in sorted_cost_centers:
            # Shared cost pool for cost center cc
            total_cc_expense = data['Indirect costs'][cc] + data['Less: COGS'][cc] + data['3. Direct Expense'][cc]
            alloc_row_name = get_alloc_row_key(cc)

            for rc in sorted_revenue_centers:
                # Allocation Pool Safety Gate: Fallback to even split if pool drops to or below Decimal('0.00')
                if total_revenue_pool > Decimal('0.00'):
                    sales_rc = data['1. Sales Accounts'][rc]
                    # Floor individual vertical revenue at zero for ratio distribution
                    # to prevent negative allocation scalars
                    effective_sales = max(Decimal('0.00'), sales_rc)
                    data[alloc_row_name][rc] = total_cc_expense * (effective_sales / total_revenue_pool)
                else:
                    # Fallback to even split if revenue is exactly zero or negative
                    data[alloc_row_name][rc] = total_cc_expense * (Decimal('1.0') / (Decimal(str(len(revenue_verticals))) or Decimal('1.0')))

            # Clear cost center's own allocated column by negating the pool
            data[alloc_row_name][cc] = -total_cc_expense
            data[alloc_row_name]['Total (including share trading)' if has_share_trading else 'Total'] = Decimal('0.00')
            if has_share_trading:
                data[alloc_row_name]['Total (without share trading)'] = Decimal('0.00')

        # Total Indirect Costs including allocations
        for v in all_cols:
            allocated_share = sum(data[get_alloc_row_key(cc)][v] for cc in sorted_cost_centers)
            data['Total indirect costs'][v] = data['Indirect costs'][v] + allocated_share

        # Profit / Loss before tax & Net Margin %
        for v in all_cols:
            data['Profit/ (loss) before tax'][v] = data['Gross margin'][v] + data['Indirect Income'][v] - data['Total indirect costs'][v]
            if abs(data['Sales'][v]) > Decimal('0.01'):
                data['Net margin %'][v] = data['Profit/ (loss) before tax'][v] / data['Sales'][v]
            else:
                data['Net margin %'][v] = Decimal('0.00')

        # Group detail rows
        for cat in direct_expense_items + indirect_income_items + indirect_expense_items:
            if has_share_trading:
                data[cat]['Total (without share trading)'] = sum(data[cat][v] for v in operating_verticals)
                data[cat]['Total (including share trading)'] = data[cat]['Total (without share trading)'] + data[cat]['Share Trading']
            else:
                data[cat]['Total'] = sum(data[cat][v] for v in sorted_revenue_centers + sorted_cost_centers)

    # 5. Debtors and Creditors Pivot Calculation
    from models.pl_data import DebtorCreditorPivot, DebtorCreditorPivotEntry

    debtor_map = {}
    creditor_map = {}

    for entry in parsed_entries:
        name_clean = clean_ledger_name(entry.name)
        if name_clean in {"particulars", "grand total", "total", "grand", "net profit", "net loss"}:
            continue

        mapping = mappings.get(name_clean)
        if not mapping:
            continue

        head = mapping.head.strip() if mapping.head else ""
        group = mapping.group.strip() if mapping.group else ""

        is_debtor = "Sundry Debtor" in head or "Sundry Debtor" in group
        is_creditor = "Sundry Creditor" in head or "Sundry Creditor" in group

        if not (is_debtor or is_creditor):
            continue

        v = mapping.vertical.strip().title() if mapping.vertical else 'Common'
        if v not in all_cols:
            v = 'Common'

        target_map = debtor_map if is_debtor else creditor_map

        if v not in target_map:
            target_map[v] = {
                "opening": 0.0, "debit": 0.0, "credit": 0.0, "closing": 0.0,
                "opening_ytd": 0.0, "debit_ytd": 0.0, "credit_ytd": 0.0, "closing_ytd": 0.0
            }

        # Monthly values
        target_map[v]["opening"] += float(entry.opening_net if entry.opening_net is not None else (entry.opening or 0.0))
        target_map[v]["debit"] += float(entry.debit_net if entry.debit_net is not None else (entry.debit or 0.0))
        target_map[v]["credit"] += float(entry.credit_net if entry.credit_net is not None else (entry.credit or 0.0))
        target_map[v]["closing"] += float(entry.closing_net if entry.closing_net is not None else (entry.closing or 0.0))

        # YTD values
        target_map[v]["opening_ytd"] += float(entry.opening_ytd or 0.0)
        target_map[v]["debit_ytd"] += float(entry.debit_ytd or 0.0)
        target_map[v]["credit_ytd"] += float(entry.credit_ytd or 0.0)
        target_map[v]["closing_ytd"] += float(entry.closing_ytd or 0.0)

    # Convert to Pydantic lists
    debtors_pivot_entries = []
    creditors_pivot_entries = []

    # Get a sorted list of unique verticals present in the maps
    all_pivot_verticals = sorted(list(set(debtor_map.keys()) | set(creditor_map.keys())))

    for pv in all_pivot_verticals:
        if pv in debtor_map:
            d = debtor_map[pv]
            debtors_pivot_entries.append(DebtorCreditorPivotEntry(
                vertical=pv,
                opening=round(d["opening"], 2),
                debit=round(d["debit"], 2),
                credit=round(d["credit"], 2),
                closing=round(d["closing"], 2),
                opening_ytd=round(d["opening_ytd"], 2),
                debit_ytd=round(d["debit_ytd"], 2),
                credit_ytd=round(d["credit_ytd"], 2),
                closing_ytd=round(d["closing_ytd"], 2),
            ))
        if pv in creditor_map:
            c = creditor_map[pv]
            creditors_pivot_entries.append(DebtorCreditorPivotEntry(
                vertical=pv,
                opening=round(c["opening"], 2),
                debit=round(c["debit"], 2),
                credit=round(c["credit"], 2),
                closing=round(c["closing"], 2),
                opening_ytd=round(c["opening_ytd"], 2),
                debit_ytd=round(c["debit_ytd"], 2),
                credit_ytd=round(c["credit_ytd"], 2),
                closing_ytd=round(c["closing_ytd"], 2),
            ))

    pivot_data = DebtorCreditorPivot(debtors=debtors_pivot_entries, creditors=creditors_pivot_entries)

    # 6. Format responses
    def build_breakdown(data_dict) -> PLBreakdown:
        rows = []
        for cat in all_categories:
            is_header = cat in (
                ['3. Direct Expense', 'Indirect Income', '6. Indirect Expense'] + 
                [get_alloc_row_key(cc) for cc in sorted_cost_centers]
            )
            is_total = cat in [
                'Gross margin', 'Gross margin %', 'Net income', 'Indirect costs', 
                'Total indirect costs', 'Profit/ (loss) before tax', 'Net margin %'
            ]
            rows.append(PLRow(
                particulars=cat,
                values={k: float(v) for k, v in data_dict[cat].items()},
                is_header=is_header,
                is_total=is_total
            ))
        return PLBreakdown(columns=all_cols, rows=rows)

    m_breakdown = build_breakdown(monthly_data)
    y_breakdown = build_breakdown(ytd_data)

    # Calculate KPIs
    kpi_col = 'Total (including share trading)' if has_share_trading else 'Total'
    kpis = {
        "monthly_revenue": float(monthly_data['Sales'][kpi_col]),
        "monthly_gross_margin_pct": float(monthly_data['Gross margin %'][kpi_col]),
        "monthly_net_income": float(monthly_data['Profit/ (loss) before tax'][kpi_col]),
        "monthly_expenses": float(monthly_data['Total indirect costs'][kpi_col]),
        "ytd_revenue": float(ytd_data['Sales'][kpi_col]),
        "ytd_gross_margin_pct": float(ytd_data['Gross margin %'][kpi_col]),
        "ytd_net_income": float(ytd_data['Profit/ (loss) before tax'][kpi_col]),
        "ytd_expenses": float(ytd_data['Total indirect costs'][kpi_col]),
    }

    return PLDataResponse(
        month_label=month_label,
        ytd_label=ytd_label,
        month_data=m_breakdown,
        ytd_data=y_breakdown,
        kpis=kpis,
        has_ytd=has_ytd,
        debtors_creditors_pivot=pivot_data
    )

