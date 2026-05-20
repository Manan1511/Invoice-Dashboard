import sys
import os

# Add backend directory to path
sys.path.append("C:/Users/manan/Downloads/Projects/Invoice Dashboard/backend")

from services.ledger_mapper import load_mapped_ledgers, parse_ledger_file

template_mappings = load_mapped_ledgers()
print(f"Master template mappings count: {len(template_mappings)}")

files = [
    "1. MIS_April 2025.xlsx",
    "MIS_May 2025.xlsx",
    "1. MIS_June 2025.xlsx"
]

for filename in files:
    path = os.path.join("C:/Users/manan/Downloads/Projects/Invoice Dashboard", filename)
    try:
        month_mappings = parse_ledger_file(path)
        print(f"\n=== {filename} mappings count: {len(month_mappings)} ===")
        
        # Compare
        extra_in_month = []
        diffs = []
        month_mappings_dict = {m.ledger_name.lower(): m for m in month_mappings}
        
        for name, m_month in month_mappings_dict.items():
            if name not in template_mappings:
                extra_in_month.append(m_month.ledger_name)
            else:
                m_temp = template_mappings[name]
                temp_str = f"Head={m_temp.head}, Classification={m_temp.classification}, Vertical={m_temp.vertical}"
                month_str = f"Head={m_month.head}, Classification={m_month.classification}, Vertical={m_month.vertical}"
                if temp_str != month_str:
                    diffs.append(f"Ledger: '{m_month.ledger_name}'\n  Template: {temp_str}\n  Manual:   {month_str}")
                    
        print(f"Ledgers present in manual but NOT in template: {len(extra_in_month)}")
        if extra_in_month:
            print("  First 10:", extra_in_month[:10])
            
        print(f"Ledgers with differences in mappings: {len(diffs)}")
        if diffs:
            print("  First 3:")
            for d in diffs[:3]:
                print(d)
                
    except Exception as e:
        print(f"Error parsing mappings from {filename}: {e}")
