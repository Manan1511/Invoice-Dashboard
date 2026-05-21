import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

def strict_normalize_ledger_name(name: Any) -> str:
    """
    Standardizes ledger names to be immune to invisible whitespace,
    non-breaking spaces, quotation marks, and case sensitivity.
    """
    if not name:
        return ""
    # 1. Convert input to a raw string, strip standard outer whitespace boundaries.
    s = str(name).strip()
    # 2. Execute unicodedata.normalize("NFKD", s) to strip invisible formatting artifacts
    s = unicodedata.normalize("NFKD", s)
    # 3. Strip trailing and leading single and double string quotation blocks.
    s = s.strip('"').strip("'")
    # 4. Return lowercase representation.
    return s.strip().lower()


def clean_decimal_value(val: Any, is_credit: bool = False) -> Decimal:
    """
    Safely converts a variety of string and numeric inputs into a standard Decimal.
    Handles Tally export suffixes like " Cr" and " Dr".
    """
    if val is None:
        return Decimal('0.00')
    
    try:
        # If it's already a numeric type that isn't a bool
        if isinstance(val, (int, float, Decimal)) and not isinstance(val, bool):
            parsed_val = Decimal(str(val))
            if is_credit:
                return -abs(parsed_val).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            return abs(parsed_val).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
        s_val = str(val).strip().lower()
        if not s_val:
            return Decimal('0.00')

        # Credit Polarity Sign Convention: trailing " cr" or " dr"
        if s_val.endswith(' cr'):
            is_credit = True
            s_val = s_val[:-3].strip()
        elif s_val.endswith('cr'):
            is_credit = True
            s_val = s_val[:-2].strip()
        elif s_val.endswith(' dr'):
            s_val = s_val[:-3].strip()
        elif s_val.endswith('dr'):
            s_val = s_val[:-2].strip()

        # Handle parentheses for negative numbers (e.g., (1,234.00))
        is_negative = False
        if s_val.startswith('(') and s_val.endswith(')'):
            is_negative = True
            s_val = s_val[1:-1].strip()

        # Strip commas, currency symbols, and spaces
        s_val = s_val.replace(',', '').replace('₹', '').replace('$', '').replace(' ', '')
        
        if s_val == "" or s_val == "-" or s_val == "--":
            return Decimal('0.00')

        parsed_value = Decimal(s_val)
        if is_negative:
            parsed_value = -parsed_value

        if is_credit:
            return -abs(parsed_value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return abs(parsed_value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    except (ValueError, TypeError, ArithmeticError, InvalidOperation):
        return Decimal('0.00')
