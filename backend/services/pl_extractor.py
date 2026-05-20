import openpyxl
from typing import List, Dict, Optional, Any
from models.ledger import LedgerMapping, LedgerEntry
from models.pl_data import PLDataResponse, PLBreakdown, PLRow
from services.ledger_mapper import load_mapped_ledgers

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
    operating_verticals = ['Bluestreak', 'Clarus', 'IT', 'Factory', 'Office', 'Common', 'Spices - A to Z', 'Spices - Vashi']
    all_verticals = operating_verticals + ['Total (without share trading)', 'Share Trading', 'Total (including share trading)']
    
    # Initialize aggregated monthly and YTD data structures
    # Structure: monthly_data[line_item][vertical] = value
    monthly_data: Dict[str, Dict[str, float]] = {}
    ytd_data: Dict[str, Dict[str, float]] = {}
    
    def get_or_create_line(item_name: str):
        if item_name not in monthly_data:
            monthly_data[item_name] = {v: 0.0 for v in all_verticals}
            ytd_data[item_name] = {v: 0.0 for v in all_verticals}
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
        val_month = entry.closing if entry.closing is not None else 0.0
        val_ytd = entry.closing_ytd if entry.closing_ytd is not None else 0.0
        
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
        # We can fetch opening and closing stock from parsed stock sheets if we want.
        # But if they are empty, let's use the direct values from TB opening stock / closing stock!
        # Opening Stock ledger is usually mapped to "5. Purchase Accounts" or "Opening Stock".
        # Let's see: Opening stock in TB has name "Opening Stock".
        opening_stock_entry = entries_map.get('opening stock')
        op_stock_m = opening_stock_entry.opening if (opening_stock_entry and not is_ytd) else (opening_stock_entry.opening_ytd if (opening_stock_entry and is_ytd) else 0.0)
        cl_stock_m = opening_stock_entry.closing if (opening_stock_entry and not is_ytd) else (opening_stock_entry.closing_ytd if (opening_stock_entry and is_ytd) else 0.0)
        
        # Let's allocate stock to verticals. Factory usually holds the main stock.
        # Let's assume stock is in Factory or Common or allocated.
        # For our Python P&L calculations, we will sum up purchases and adjust for stock change:
        for v in all_verticals:
            purch = data.get('COGS_Purchases', {}).get(v, 0.0)
            # COGS = Opening Stock + Purchases - Closing Stock
            # If vertical is Factory, we can include stock change
            stock_change = 0.0
            if v == 'Factory':
                final_cl_stock = closing_stock if closing_stock > 0 else (cl_stock_m or 0.0)
                stock_change = (op_stock_m or 0.0) - final_cl_stock
            data['Less: COGS'][v] = purch + stock_change
            
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
            if data['Sales'][v] != 0:
                data['Gross margin %'][v] = data['Gross margin'][v] / data['Sales'][v]
            else:
                data['Gross margin %'][v] = 0.0
                
        # Calculate Indirect Income total
        for v in all_verticals:
            data['Indirect Income'][v] = sum(data[cat][v] for cat in indirect_income_items)
            
        data['Indirect Income']['Total (without share trading)'] = sum(data['Indirect Income'][v] for v in operating_verticals)
        data['Indirect Income']['Total (including share trading)'] = data['Indirect Income']['Total (without share trading)'] + data['Indirect Income']['Share Trading']
        
        # Calculate Net Income
        for v in all_verticals:
            data['Net income'][v] = data['Gross margin'][v] + data['Indirect Income'][v]
            
        # Calculate Indirect Expense total (6. Indirect Expense row)
        for v in all_verticals:
            data['6. Indirect Expense'][v] = sum(data[cat][v] for cat in indirect_expense_items)
            data['Indirect costs'][v] = data['6. Indirect Expense'][v]
            
        data['6. Indirect Expense']['Total (without share trading)'] = sum(data['6. Indirect Expense'][v] for v in operating_verticals)
        data['6. Indirect Expense']['Total (including share trading)'] = data['6. Indirect Expense']['Total (without share trading)'] + data['6. Indirect Expense']['Share Trading']
        data['Indirect costs']['Total (without share trading)'] = data['6. Indirect Expense']['Total (without share trading)']
        data['Indirect costs']['Total (including share trading)'] = data['6. Indirect Expense']['Total (including share trading)']
        
        # 5. Allocations (Factory, Office, Common)
        # Factory Allocation: Factory costs (COGS + Indirect costs) divided by 3, allocated to Bluestreak, Clarus, IT
        factory_cogs = data['Less: COGS']['Factory']
        factory_ind = data['Indirect costs']['Factory']
        factory_share = (factory_cogs + factory_ind) / 3.0
        
        data['Factory']['Bluestreak'] = factory_share
        data['Factory']['Clarus'] = factory_share
        data['Factory']['IT'] = factory_share
        data['Factory']['Total (without share trading)'] = factory_share * 3
        data['Factory']['Total (including share trading)'] = factory_share * 3
        
        # Office Allocation: Office costs (COGS + Indirect costs) divided by 3, allocated to Bluestreak, Clarus, IT
        office_cogs = data['Less: COGS']['Office']
        office_ind = data['Indirect costs']['Office']
        office_share = (office_cogs + office_ind) / 3.0
        
        data['Office']['Bluestreak'] = office_share
        data['Office']['Clarus'] = office_share
        data['Office']['IT'] = office_share
        data['Office']['Total (without share trading)'] = office_share * 3
        data['Office']['Total (including share trading)'] = office_share * 3
        
        # Common Allocation: Common costs (COGS + Indirect costs) allocated to Clarus and Spices - Vashi based on Sales ratio
        common_ind = data['Indirect costs']['Common']
        total_sales_for_common = data['Sales']['Total (without share trading)'] or 1.0
        
        if not is_ytd:
            # Monthly allocation matching Excel formula: Clarus gets G69*C7/J7, Spices-Vashi gets G69*I7/J7
            data['Common']['Clarus'] = common_ind * (data['Sales']['Clarus'] / total_sales_for_common)
            data['Common']['Spices - Vashi'] = common_ind * (data['Sales']['Spices - Vashi'] / total_sales_for_common)
            data['Common']['Common'] = -common_ind
            data['Common']['Total (without share trading)'] = data['Common']['Clarus'] + data['Common']['Spices - Vashi'] + data['Common']['Common']
            data['Common']['Total (including share trading)'] = data['Common']['Total (without share trading)']
        else:
            # YTD allocation matching Excel: Bluestreak, Clarus, IT, Spices - Vashi get proportional common costs
            data['Common']['Bluestreak'] = common_ind * (data['Sales']['Bluestreak'] / total_sales_for_common)
            data['Common']['Clarus'] = common_ind * (data['Sales']['Clarus'] / total_sales_for_common)
            data['Common']['IT'] = common_ind * (data['Sales']['IT'] / total_sales_for_common)
            data['Common']['Spices - Vashi'] = common_ind * (data['Sales']['Spices - Vashi'] / total_sales_for_common)
            data['Common']['Common'] = -common_ind
            data['Common']['Total (without share trading)'] = sum(data['Common'][v] for v in operating_verticals)
            data['Common']['Total (including share trading)'] = data['Common']['Total (without share trading)']
            
        # Total indirect costs
        for v in all_verticals:
            data['Total indirect costs'][v] = data['Indirect costs'][v] + (data['Factory'][v] or 0.0) + (data['Office'][v] or 0.0) + (data['Common'][v] or 0.0)
            
        # Profit / Loss before tax
        for v in all_verticals:
            data['Profit/ (loss) before tax'][v] = data['Gross margin'][v] + data['Indirect Income'][v] - data['Total indirect costs'][v]
            if data['Sales'][v] != 0:
                data['Net margin %'][v] = data['Profit/ (loss) before tax'][v] / data['Sales'][v]
            else:
                data['Net margin %'][v] = 0.0

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
