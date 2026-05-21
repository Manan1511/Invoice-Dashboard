from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List
from services.ledger_mapper import CompanyConfiguration

def run_pl_extraction(parsed_entries: Dict[str, dict], config: CompanyConfiguration) -> Dict[str, Any]:
    """
    Performs algebraic financial operations using strict precision.
    Produces a 2D data dictionary ready for workbook presentation.
    """
    
    # Establish operational columns: Revenue Verticals + Cost Verticals
    # Sort them for consistent layout
    rev_verts = sorted(list(config.revenue_verticals))
    cost_verts = sorted(list(config.cost_verticals))
    
    # Target structure: rows[category_name][vertical] = Decimal
    # We will build distinct P&L groups.
    groups = [
        '1. Sales Accounts',
        '2. Less: COGS',
        '3. Direct Expense',
        '4. Gross Margin',
        '5. Indirect Income',
        '6. Net Allocable Income',
        '7. Indirect Expense'
    ]
    
    data = {g: {v: Decimal('0.00') for v in rev_verts + cost_verts + ['Common']} for g in groups}
    
    # Aggregation Loop
    for clean_name, entry in parsed_entries.items():
        mapping = config.mappings[clean_name]
        v = mapping.vertical
        head = mapping.head
        
        # Safe fallback if vertical isn't in our active list
        if v not in data['1. Sales Accounts']:
            v = 'Common'
            
        op_val = entry['opening']
        cl_val = entry['closing']
        
        # True Monthly Movement Extraction
        val_month = cl_val - op_val
        
        # Sign Conventions & Reversals for Presentation
        if head in {"1. Sales Accounts", "2. Indirect Income"}:
            val_month = -val_month
            
        if head == "1. Sales Accounts":
            data['1. Sales Accounts'][v] += val_month
        elif head == "3. Direct Expense":
            data['3. Direct Expense'][v] += val_month
        elif head == "2. Indirect Income":
            data['5. Indirect Income'][v] += val_month
        elif head == "6. Indirect Expense":
            data['7. Indirect Expense'][v] += val_month
        elif head == "5. Purchase Accounts":
            data['2. Less: COGS'][v] += val_month
        elif head == "Stock-in-hand":
            # For COGS, Stock-in-hand closing minus opening is technically an increase in asset, 
            # reducing COGS. We add Opening - Closing to COGS.
            stock_impact = op_val - cl_val
            data['2. Less: COGS'][v] += stock_impact
            
    # Calculate Gross Margin
    for v in rev_verts + cost_verts + ['Common']:
        data['4. Gross Margin'][v] = (
            data['1. Sales Accounts'][v] 
            - data['2. Less: COGS'][v] 
            - data['3. Direct Expense'][v]
        )
        data['6. Net Allocable Income'][v] = data['4. Gross Margin'][v] + data['5. Indirect Income'][v]
        
    # Cost Allocation Matrix
    # We will create an allocation section tracking each cost center's spread.
    allocation_matrix = {}
    total_revenue_pool = sum(abs(data['1. Sales Accounts'][rv]) for rv in rev_verts)
    
    for cc in cost_verts:
        # Full indirect expense pool for this cost vertical
        # (Could also include direct expenses/COGS if the business rules want to zero it entirely,
        # but the spec says `data['6. Indirect Expense'][cost_center]`)
        cost_pool = data['7. Indirect Expense'][cc]
        
        allocation_row = f"Allocation of {cc}"
        allocation_matrix[allocation_row] = {v: Decimal('0.00') for v in rev_verts + cost_verts + ['Common']}
        
        if total_revenue_pool > Decimal('0.00'):
            # Proportional distribution
            for rv in rev_verts:
                sales_v = data['1. Sales Accounts'][rv]
                allocated_share = cost_pool * (abs(sales_v) / total_revenue_pool)
                allocation_matrix[allocation_row][rv] = allocated_share.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            if len(rev_verts) > 0:
                # Active revenue verticals but zero sales -> split evenly
                even_share = (cost_pool / Decimal(str(len(rev_verts)))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                for rv in rev_verts:
                    allocation_matrix[allocation_row][rv] = even_share
            else:
                # Zero revenue verticals -> dump to common
                allocation_matrix[allocation_row]['Common'] = cost_pool
                
        # Balance out the source cost center row
        allocation_matrix[allocation_row][cc] -= cost_pool
        
    # Append the matrix to the data payload
    data['Allocations'] = allocation_matrix
    
    # Calculate Final Totals
    data['Total Indirect Costs'] = {v: Decimal('0.00') for v in rev_verts + cost_verts + ['Common']}
    data['Net Profit'] = {v: Decimal('0.00') for v in rev_verts + cost_verts + ['Common']}
    
    for v in rev_verts + cost_verts + ['Common']:
        total_allocations = sum(matrix_row[v] for matrix_row in allocation_matrix.values())
        data['Total Indirect Costs'][v] = data['7. Indirect Expense'][v] + total_allocations
        data['Net Profit'][v] = data['6. Net Allocable Income'][v] - data['Total Indirect Costs'][v]
        
    return {
        "revenue_verticals": rev_verts,
        "cost_verticals": cost_verts,
        "grid": data
    }
