import openpyxl
from typing import List, Dict, Optional, Any
from models.ledger import LedgerMapping, LedgerEntry
from models.pl_data import PLDataResponse, PLBreakdown, PLRow
from services.ledger_mapper import load_mapped_ledgers

from decimal import Decimal, ROUND_HALF_UP

# Helper to convert to Decimal
def _to_dec(val):
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
    """Calculates and extracts the P&L breakdown dynamically in Python based on ledger mappings and balances."""
    # 1. Load active mappings
    mappings = load_mapped_ledgers()
    
    # Map entries by ledger name (lowercase)
    entries_map: Dict[str, LedgerEntry] = {e.name.lower(): e for e in parsed_entries}
    
    # 2. Define Verticals and Columns
    # Dynamically extract all unique verticals mapped by the user
    mapped_verticals = set(m.vertical for m in mappings.values() if m.vertical and m.vertical != 'Share Trading')
    
    # Ensure core shared pools exist, then convert to list
    operating_verticals = list(mapped_verticals.union({'Factory', 'Office', 'Common'}))
    all_verticals = operating_verticals + ['Total (without share trading)', 'Share Trading', 'Total (including share trading)']
    
    # Initialize aggregated monthly and YTD data structures
    # Structure: monthly_data[line_item][vertical] = value
    monthly_data: Dict[str, Dict[str, Decimal]] = {}
    ytd_data: Dict[str, Dict[str, Decimal]] = {}
    
    def get_or_create_line(item_name: str):
        if item_name not in monthly_data:
            monthly_data[item_name] = {v: Decimal('0.00') for v in all_verticals}
            ytd_data[item_name] = {v: Decimal('0.00') for v in all_verticals}
        return monthly_data[item_name], ytd_data[item_name]

    # Pre-populate empty lines for all P&L row categories
    direct_expense_items = ['Port Expenses', 'Loading & Unloading charges', 'Freight & Shipping charges', 'Export charges', 'Insurance expenses']
    indirect_income_items = ['Foreign Exchange Gain', 'Exhibtion Income', 'Commission', 'Dividend ', 'Interest Income', 'Short term Capital Gain ', 'Profit on sale of Investment ', 'Capital Loss']
    indirect_expense_items = [
        'Audit Fees', 'Accomodation expenses', 'Advertisement', 'Bad debt', 'Marketing Expense', 'Bank charges', 
        'Brokerage and commission', 'Conveyance expenses', 'Courier charges', 'Donation', 'Domain Expenses', 
        'Depreciation', 'Electricity charges', 'Fuel Expenses', 'Insurance', 'Interest expense', 'Labour charges', 
        'Misc Expenses', 'Membership Expenses', 'Printing & Stationery', 'Professional charges', 'Rates & Taxes', 
        'Rent expenses', 'Repairs & maintenance expenses', 'Salary & wages', 'Share trading expenses', 
        'Staff welfare expenses', 'Subscription fees', 'Telephone & Internet charges', 'Transportation', 
        'Travelling expenses', 'Packing Charges'
    ]
    
    all_categories = ['Sales', 'Less: COGS', '3. Direct Expense'] + direct_expense_items + ['Gross margin', 'Gross margin %', 'Indirect Income'] + indirect_income_items + ['Net income', 'Net allocable income', '6. Indirect Expense'] + indirect_expense_items + ['Indirect costs', 'Factory', 'Office', 'Common', 'Total indirect costs', 'Profit/ (loss) before tax', 'Net margin %']
    
    for cat in all_categories:
        get_or_create_line(cat)
        
    # 3. Aggregate Trial Balance balances using mappings
    for ledger_name_lower, mapping in mappings.items():
        entry = entries_map.get(ledger_name_lower)
        if not entry:
            continue
            
        vertical = mapping.vertical
        if vertical not in operating_verticals and vertical != 'Share Trading':
            # Default fallback to Common
            vertical = 'Common'
            
        # Parse balances (credits are negative in Tally, we flip them depending on Head type)
        # Head mappings:
        # Sales & Indirect Income are credit balances (credit balance is negative closing in parsed entry, so we do -entry.closing)
        # Expenses & Purchases are debit balances (debit balance is positive closing)
        op_val = _to_dec(entry.opening_net if entry.opening_net is not None else entry.opening) if (entry.opening_net is not None or entry.opening is not None) else Decimal('0.00')
        cl_val = _to_dec(entry.closing_net if entry.closing_net is not None else entry.closing) if (entry.closing_net is not None or entry.closing is not None) else Decimal('0.00')
        val_month = cl_val - op_val

        val_ytd = _to_dec(entry.closing_ytd) if entry.closing_ytd is not None else Decimal('0.00')
        
        # Ensure Sales and Incomes are strictly positive for dashboard metrics and charts.
        # But use negative multiplication instead of abs() so that Sales Returns (Debits) properly reduce revenue.
        if mapping.head in {"1. Sales Accounts", "2. Indirect Income"}:
            val_month = -val_month
            val_ytd = -val_ytd
            
        if mapping.head == "1. Sales Accounts":
            m_sales, y_sales = get_or_create_line('Sales')
            m_sales[vertical] += val_month
            y_sales[vertical] += val_ytd
            
        elif mapping.head == "3. Direct Expense":
            classification = mapping.classification or 'Insurance expenses'
            m_direct, y_direct = get_or_create_line(classification)
            m_direct[vertical] += val_month
            y_direct[vertical] += val_ytd
            
        elif mapping.head == "5. Purchase Accounts":
            # Purchases go into COGS calculation
            # We'll accumulate them in a temporary COGS purchases line
            m_purch, y_purch = get_or_create_line('COGS_Purchases')
            m_purch[vertical] += val_month
            y_purch[vertical] += val_ytd
            
        elif mapping.head == "2. Indirect Income":
            classification = mapping.classification or 'Foreign Exchange Gain'
            m_ind_inc, y_ind_inc = get_or_create_line(classification)
            m_ind_inc[vertical] += val_month
            y_ind_inc[vertical] += val_ytd
            
        elif mapping.head == "6. Indirect Expense":
            classification = mapping.classification or 'Misc Expenses'
            m_ind_exp, y_ind_exp = get_or_create_line(classification)
            m_ind_exp[vertical] += val_month
            y_ind_exp[vertical] += val_ytd

    # 4. Perform calculations & Roll-ups
    for is_ytd in [False, True]:
        data = ytd_data if is_ytd else monthly_data
        
        # Calculate 3. Direct Expense totals
        for v in all_verticals:
            data['3. Direct Expense'][v] = sum(data[cat][v] for cat in direct_expense_items)
            
        # Calculate Purchases/COGS
        # Accumulate stock dynamically per vertical
        stock_changes = {v: Decimal('0.00') for v in all_verticals}
        total_op_stock = {v: Decimal('0.00') for v in all_verticals}
        total_cl_stock = {v: Decimal('0.00') for v in all_verticals}
        
        # 1. Sum up everything as it exists in Tally
        for ledger_name, mapping in mappings.items():
            if mapping.classification == 'Opening Stock' or mapping.head == 'Stock-in-hand':
                entry = entries_map.get(ledger_name)
                if entry:
                    v = mapping.vertical or 'Factory'
                    if v not in all_verticals and v != 'Share Trading':
                        v = 'Common'
                        
                    total_op_stock[v] += _to_dec(entry.opening if not is_ytd else (entry.opening_ytd or Decimal('0.00')))
                    total_cl_stock[v] += _to_dec(entry.closing if not is_ytd else (entry.closing_ytd or Decimal('0.00')))

        # 2. Apply the override once per vertical and calculate final change
        for v in all_verticals:
            final_cl = _to_dec(closing_stock) if (closing_stock > 0.0 and v == 'Factory') else total_cl_stock[v]
            stock_changes[v] = total_op_stock[v] - final_cl

        # Apply changes to the correct verticals
        for v in all_verticals:
            purch = data.get('COGS_Purchases', {}).get(v, Decimal('0.00'))
            data['Less: COGS'][v] = purch + stock_changes.get(v, Decimal('0.00'))
            
        # Totals for Sales, COGS, Direct Expense (without share trading)
        data['Sales']['Total (without share trading)'] = sum(data['Sales'][v] for v in operating_verticals)
        data['Less: COGS']['Total (without share trading)'] = sum(data['Less: COGS'][v] for v in operating_verticals)
        data['3. Direct Expense']['Total (without share trading)'] = sum(data['3. Direct Expense'][v] for v in operating_verticals)
        
        # Totals including Share Trading
        data['Sales']['Total (including share trading)'] = data['Sales']['Total (without share trading)'] + data['Sales']['Share Trading']
        data['Less: COGS']['Total (including share trading)'] = data['Less: COGS']['Total (without share trading)'] + data['Less: COGS']['Share Trading']
        data['3. Direct Expense']['Total (including share trading)'] = data['3. Direct Expense']['Total (without share trading)'] + data['3. Direct Expense']['Share Trading']
        
        # Calculate Gross Margin
        for v in all_verticals:
            data['Gross margin'][v] = data['Sales'][v] - data['Less: COGS'][v] - data['3. Direct Expense'][v]
            if abs(data['Sales'][v]) > 0.01:
                data['Gross margin %'][v] = data['Gross margin'][v] / data['Sales'][v]
            else:
                data['Gross margin %'][v] = Decimal('0.00')
                
        # Calculate Indirect Income total
        for v in all_verticals:
            data['Indirect Income'][v] = sum(data[cat][v] for cat in indirect_income_items)
            
        data['Indirect Income']['Total (without share trading)'] = sum(data['Indirect Income'][v] for v in operating_verticals)
        data['Indirect Income']['Total (including share trading)'] = data['Indirect Income']['Total (without share trading)'] + data['Indirect Income']['Share Trading']
        
        # Calculate Net Income
        for v in all_verticals:
            data['Net income'][v] = data['Gross margin'][v] + data['Indirect Income'][v]
            data['Net allocable income'][v] = data['Net income'][v]
            
        # Calculate Indirect Expense total (6. Indirect Expense row)
        for v in all_verticals:
            data['6. Indirect Expense'][v] = sum(data[cat][v] for cat in indirect_expense_items)
            data['Indirect costs'][v] = data['6. Indirect Expense'][v]
            
        data['6. Indirect Expense']['Total (without share trading)'] = sum(data['6. Indirect Expense'][v] for v in operating_verticals)
        data['6. Indirect Expense']['Total (including share trading)'] = data['6. Indirect Expense']['Total (without share trading)'] + data['6. Indirect Expense']['Share Trading']
        data['Indirect costs']['Total (without share trading)'] = data['6. Indirect Expense']['Total (without share trading)']
        data['Indirect costs']['Total (including share trading)'] = data['6. Indirect Expense']['Total (including share trading)']
        
        # 5. Allocations (Factory, Office, Common)
        # Factory Allocation: Factory costs allocated to targeted verticals
        factory_cogs = data['Less: COGS']['Factory']
        factory_ind = data['Indirect costs']['Factory']
        factory_total_pool = factory_cogs + factory_ind
        
        factory_targets = [v for v in mapped_verticals if v not in {'Factory', 'Office', 'Common'}]
        factory_share = factory_total_pool / (len(factory_targets) or Decimal('1.0'))
        
        for target in factory_targets:
            data['Factory'][target] = factory_share
            
        data['Factory']['Factory'] = -factory_total_pool
        data['Factory']['Total (without share trading)'] = Decimal('0.00')
        data['Factory']['Total (including share trading)'] = Decimal('0.00')
        
        # Office Allocation: Office costs allocated to targeted verticals
        office_cogs = data['Less: COGS']['Office']
        office_ind = data['Indirect costs']['Office']
        office_total_pool = office_cogs + office_ind
        
        office_targets = [v for v in mapped_verticals if v not in {'Factory', 'Office', 'Common'}]
        office_share = office_total_pool / (len(office_targets) or Decimal('1.0'))
        
        for target in office_targets:
            data['Office'][target] = office_share
            
        data['Office']['Office'] = -office_total_pool
        data['Office']['Total (without share trading)'] = Decimal('0.00')
        data['Office']['Total (including share trading)'] = Decimal('0.00')
        
        # Common Allocation: Common costs allocated proportionally to all revenue-generating verticals
        common_ind = data['Indirect costs']['Common']
        
        revenue_verticals = [v for v in mapped_verticals if v not in {'Factory', 'Office', 'Common'}]
        total_revenue_pool = sum(data['Sales'][v] for v in revenue_verticals)
        
        # Allocate proportionally to ensure 100% distribution and no orphaned costs
        for v in revenue_verticals:
            if total_revenue_pool > 0:
                data['Common'][v] = common_ind * (data['Sales'][v] / total_revenue_pool)
            else:
                data['Common'][v] = common_ind * (Decimal('1.0') / (len(revenue_verticals) or Decimal('1.0')))
            
        data['Common']['Common'] = -common_ind
        data['Common']['Total (without share trading)'] = Decimal('0.00')
        data['Common']['Total (including share trading)'] = Decimal('0.00')
            
        # Total indirect costs
        for v in all_verticals:
            data['Total indirect costs'][v] = data['Indirect costs'][v] + (data['Factory'][v] or Decimal('0.00')) + (data['Office'][v] or Decimal('0.00')) + (data['Common'][v] or Decimal('0.00'))
            
        # Profit / Loss before tax
        for v in all_verticals:
            data['Profit/ (loss) before tax'][v] = data['Gross margin'][v] + data['Indirect Income'][v] - data['Total indirect costs'][v]
            if abs(data['Sales'][v]) > 0.01:
                data['Net margin %'][v] = data['Profit/ (loss) before tax'][v] / data['Sales'][v]
            else:
                data['Net margin %'][v] = Decimal('0.00')

        for cat in direct_expense_items + indirect_income_items + indirect_expense_items:
            data[cat]['Total (without share trading)'] = sum(data[cat][v] for v in operating_verticals)
            data[cat]['Total (including share trading)'] = data[cat]['Total (without share trading)'] + data[cat]['Share Trading']

    # 5. Format responses
    def build_breakdown(data_dict) -> PLBreakdown:
        rows = []
        for cat in all_categories:
            is_header = cat in ['3. Direct Expense', 'Indirect Income', '6. Indirect Expense', 'Allocation of expenses:']
            is_total = cat in ['Gross margin', 'Gross margin %', 'Net income', 'Indirect costs', 'Total indirect costs', 'Profit/ (loss) before tax', 'Net margin %']
            rows.append(PLRow(
                particulars=cat,
                values=data_dict[cat],
                is_header=is_header,
                is_total=is_total
            ))
        return PLBreakdown(columns=all_verticals, rows=rows)
        
    m_breakdown = build_breakdown(monthly_data)
    y_breakdown = build_breakdown(ytd_data)
    
    # Calculate KPIs
    kpis = {
        "monthly_revenue": monthly_data['Sales']['Total (including share trading)'],
        "monthly_gross_margin_pct": monthly_data['Gross margin %']['Total (including share trading)'],
        "monthly_net_income": monthly_data['Profit/ (loss) before tax']['Total (including share trading)'],
        "monthly_expenses": monthly_data['Total indirect costs']['Total (including share trading)'],
        "ytd_revenue": ytd_data['Sales']['Total (including share trading)'],
        "ytd_gross_margin_pct": ytd_data['Gross margin %']['Total (including share trading)'],
        "ytd_net_income": ytd_data['Profit/ (loss) before tax']['Total (including share trading)'],
        "ytd_expenses": ytd_data['Total indirect costs']['Total (including share trading)'],
    }
    
    return PLDataResponse(
        month_label=month_label,
        ytd_label=ytd_label,
        month_data=m_breakdown,
        ytd_data=y_breakdown,
        kpis=kpis,
        has_ytd=has_ytd
    )
