import os
import io
import csv
import unittest
from decimal import Decimal
from services.processor import (
    Processor,
    clean_ledger_name,
    to_decimal,
    MappingError,
    TrialBalanceRow,
    HEAD_SALES,
    HEAD_PURCHASE,
    HEAD_DIRECT_EXPENSE,
    HEAD_INDIRECT_INCOME,
    HEAD_INDIRECT_EXPENSE
)

class TestProcessor(unittest.TestCase):
    """
    Comprehensive unit tests for the pure calculation engine Processor class,
    validating input formats, mapping checks, accounting logic, and overhead allocation rules.
    """

    def setUp(self):
        self.processor = Processor()

    def test_clean_ledger_name(self):
        """Validates that ledger names are cleaned and standardized perfectly."""
        self.assertEqual(clean_ledger_name("  Ledger Name  "), "ledger name")
        self.assertEqual(clean_ledger_name('"Quoted Ledger"'), "quoted ledger")
        self.assertEqual(clean_ledger_name("'Single Quoted'"), "single quoted")
        self.assertEqual(clean_ledger_name("Name\u00a0With\u00a0NBSP"), "name with nbsp")
        self.assertEqual(clean_ledger_name(None), "")

    def test_to_decimal(self):
        """Validates that strings, numbers, suffixes, and brackets are parsed into Decimal values correctly."""
        self.assertEqual(to_decimal(10.5), Decimal("10.50"))
        self.assertEqual(to_decimal("1,234.56"), Decimal("1234.56"))
        self.assertEqual(to_decimal("150.00 dr"), Decimal("150.00"))
        self.assertEqual(to_decimal("200.00 cr"), Decimal("-200.00"))
        self.assertEqual(to_decimal("(500.00)"), Decimal("-500.00"))
        self.assertEqual(to_decimal("-"), Decimal("0.00"))
        self.assertEqual(to_decimal(None), Decimal("0.00"))

    def test_load_mappings_csv(self):
        """Tests dynamic header scanning and loading of ledger mappings from CSV input."""
        csv_data = (
            "Sl No,Particulars,Business Vertical,Head,Group\n"
            "1,Sales Bluestreak,Bluestreak,1. Sales Accounts,P&L\n"
            "2,Purchase Factory,Factory,5. Purchase Accounts,P&L\n"
            "3,Salary Common,Common,6. Indirect Expense,P&L\n"
        )
        
        # Test loading from a byte/file stream
        stream = io.BytesIO(csv_data.encode("utf-8"))
        # We simulate reading by mocking read_sheet_rows to return the rows directly
        original_read = self.processor._read_sheet_rows
        try:
            self.processor._read_sheet_rows = lambda src: [
                row for row in csv.reader(io.StringIO(csv_data))
            ]
            mappings = self.processor.load_mappings("dummy.csv")
            
            self.assertIn("sales bluestreak", mappings)
            self.assertEqual(mappings["sales bluestreak"]["vertical"], "Bluestreak")
            self.assertEqual(mappings["sales bluestreak"]["head"], HEAD_SALES)
            
            self.assertIn("purchase factory", mappings)
            self.assertEqual(mappings["purchase factory"]["vertical"], "Factory")
            self.assertEqual(mappings["purchase factory"]["head"], HEAD_PURCHASE)
        finally:
            self.processor._read_sheet_rows = original_read

    def test_parse_tb_with_unmapped_ledger(self):
        """Verifies that parse_tb throws MappingError when a non-zero balance ledger is unmapped."""
        tb_rows = [
            ["Particulars", "Opening Balance", "Debit", "Credit", "Closing Balance"],
            ["Sales Bluestreak", "0.00", "0.00", "1000.00", "1000.00 cr"],
            ["Unmapped Active Ledger", "0.00", "500.00", "0.00", "500.00"],
        ]
        
        mappings = {
            "sales bluestreak": {
                "ledger_name": "Sales Bluestreak",
                "vertical": "Bluestreak",
                "head": HEAD_SALES,
                "group": "P&L"
            }
        }
        
        original_read = self.processor._read_sheet_rows
        try:
            self.processor._read_sheet_rows = lambda src: tb_rows
            
            # Should raise MappingError since Unmapped Active Ledger has a non-zero balance
            with self.assertRaises(MappingError) as ctx:
                self.processor.parse_tb("dummy.csv", mappings)
            
            self.assertIn("Unmapped Active Ledger", str(ctx.exception))
        finally:
            self.processor._read_sheet_rows = original_read

    def test_parse_tb_with_unmapped_zero_balance_ledger(self):
        """Verifies that parse_tb ignores unmapped ledgers if they have a flat zero balance."""
        tb_rows = [
            ["Particulars", "Opening Balance", "Debit", "Credit", "Closing Balance"],
            ["Sales Bluestreak", "0.00", "0.00", "1000.00", "1000.00 cr"],
            ["Unmapped Zero Ledger", "0.00", "0.00", "0.00", "0.00"],
        ]
        
        mappings = {
            "sales bluestreak": {
                "ledger_name": "Sales Bluestreak",
                "vertical": "Bluestreak",
                "head": HEAD_SALES,
                "group": "P&L"
            }
        }
        
        original_read = self.processor._read_sheet_rows
        try:
            self.processor._read_sheet_rows = lambda src: tb_rows
            parsed = self.processor.parse_tb("dummy.csv", mappings)
            
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0].normalized_name, "sales bluestreak")
        finally:
            self.processor._read_sheet_rows = original_read

    def test_calculate_financials_and_overheads(self):
        """Tests the entire sequential computation pipeline: TB parsing, financials calculation, and overhead sweeping."""
        
        # 1. Define mock parsed TB rows
        parsed_data = [
            TrialBalanceRow(
                ledger_name="Sales Bluestreak",
                normalized_name="sales bluestreak",
                opening=Decimal("0.00"),
                debit=Decimal("0.00"),
                credit=Decimal("6000.00"),
                closing=Decimal("-6000.00"),  # Tally Credits are negative
                vertical="Bluestreak",
                head=HEAD_SALES,
                group="P&L"
            ),
            TrialBalanceRow(
                ledger_name="Sales Clarus",
                normalized_name="sales clarus",
                opening=Decimal("0.00"),
                debit=Decimal("0.00"),
                credit=Decimal("4000.00"),
                closing=Decimal("-4000.00"),
                vertical="Clarus",
                head=HEAD_SALES,
                group="P&L"
            ),
            TrialBalanceRow(
                ledger_name="Purchase Bluestreak",
                normalized_name="purchase bluestreak",
                opening=Decimal("0.00"),
                debit=Decimal("2000.00"),
                credit=Decimal("0.00"),
                closing=Decimal("2000.00"),
                vertical="Bluestreak",
                head=HEAD_PURCHASE,
                group="P&L"
            ),
            TrialBalanceRow(
                ledger_name="Direct Exp Clarus",
                normalized_name="direct exp clarus",
                opening=Decimal("0.00"),
                debit=Decimal("800.00"),
                credit=Decimal("0.00"),
                closing=Decimal("800.00"),
                vertical="Clarus",
                head=HEAD_DIRECT_EXPENSE,
                group="P&L"
            ),
            TrialBalanceRow(
                ledger_name="Salary Common",
                normalized_name="salary common",
                opening=Decimal("0.00"),
                debit=Decimal("1500.00"),
                credit=Decimal("0.00"),
                closing=Decimal("1500.00"),
                vertical="Common",
                head=HEAD_INDIRECT_EXPENSE,
                group="P&L"
            )
        ]

        # 2. Define closing stock overrides
        stock_data = {
            "Bluestreak": {
                "opening": Decimal("500.00"),
                "closing": Decimal("1000.00")
            }
        }

        # 3. Compute Financials
        financials = self.processor.calculate_financials(parsed_data, stock_data)

        # Validate Bluestreak math:
        # Sales = 6000
        # Purchase = 2000
        # Stock: Opening = 500, Closing = 1000 -> Stock Change = -500
        # COGS = 500 + 2000 - 1000 = 1500
        # Gross Margin = 6000 - 1500 = 4500
        self.assertEqual(financials["Bluestreak"]["sales"], Decimal("6000.00"))
        self.assertEqual(financials["Bluestreak"]["cogs"], Decimal("1500.00"))
        self.assertEqual(financials["Bluestreak"]["gross_margin"], Decimal("4500.00"))

        # Validate Clarus math:
        # Sales = 4000
        # Purchases = 0, Direct Exp = 800
        # COGS = 0 (Stock defaults to 0.00)
        # Gross Margin = 4000 - 800 = 3200
        self.assertEqual(financials["Clarus"]["sales"], Decimal("4000.00"))
        self.assertEqual(financials["Clarus"]["direct_expenses"], Decimal("800.00"))
        self.assertEqual(financials["Clarus"]["gross_margin"], Decimal("3200.00"))

        # Validate Common math:
        # Pre-allocation income = -1500 (net expense)
        self.assertEqual(financials["Common"]["pre_allocation_income"], Decimal("-1500.00"))

        # 4. Allocate Overheads (Proportional)
        # Total Sales Pool = 6000 (Bluestreak) + 4000 (Clarus) = 10000
        # Ratio Bluestreak = 0.60 -> Allocation = 1500 * 0.60 = 900
        # Ratio Clarus = 0.40 -> Allocation = 1500 * 0.40 = 600
        allocated = self.processor.allocate_overheads(financials)

        self.assertEqual(allocated["Bluestreak"]["allocated_overheads"]["Common"], Decimal("900.00"))
        self.assertEqual(allocated["Bluestreak"]["net_income"], Decimal("3600.00")) # 4500 gross - 900 allocated

        self.assertEqual(allocated["Clarus"]["allocated_overheads"]["Common"], Decimal("600.00"))
        self.assertEqual(allocated["Clarus"]["net_income"], Decimal("2600.00")) # 3200 gross - 600 allocated

        # Cost Center completely swept to zero
        self.assertEqual(allocated["Common"]["net_income"], Decimal("0.00"))

    def test_allocate_overheads_zero_sales_fallback(self):
        """Verifies that the allocation sweep falls back to Even Split when total sales is exactly zero."""
        financials = {
            "Bluestreak": {
                "sales": Decimal("0.00"),
                "purchases": Decimal("0.00"),
                "direct_expenses": Decimal("0.00"),
                "cogs": Decimal("0.00"),
                "gross_margin": Decimal("0.00"),
                "indirect_income": Decimal("0.00"),
                "indirect_expenses": Decimal("0.00"),
                "pre_allocation_income": Decimal("0.00"),
                "allocated_overheads": {},
                "total_allocated_overhead": Decimal("0.00"),
                "net_income": Decimal("0.00")
            },
            "Clarus": {
                "sales": Decimal("0.00"),
                "purchases": Decimal("0.00"),
                "direct_expenses": Decimal("0.00"),
                "cogs": Decimal("0.00"),
                "gross_margin": Decimal("0.00"),
                "indirect_income": Decimal("0.00"),
                "indirect_expenses": Decimal("0.00"),
                "pre_allocation_income": Decimal("0.00"),
                "allocated_overheads": {},
                "total_allocated_overhead": Decimal("0.00"),
                "net_income": Decimal("0.00")
            },
            "Common": {
                "sales": Decimal("0.00"),
                "purchases": Decimal("0.00"),
                "direct_expenses": Decimal("0.00"),
                "cogs": Decimal("0.00"),
                "gross_margin": Decimal("0.00"),
                "indirect_income": Decimal("0.00"),
                "indirect_expenses": Decimal("0.00"),
                "pre_allocation_income": Decimal("-1000.00"),  # Expense of 1000
                "allocated_overheads": {},
                "total_allocated_overhead": Decimal("0.00"),
                "net_income": Decimal("-1000.00")
            }
        }

        # Sweep with 0.00 sales across both Bluestreak and Clarus
        allocated = self.processor.allocate_overheads(financials)

        # Expected: Even split of 1000 between Bluestreak and Clarus = 500 each
        self.assertEqual(allocated["Bluestreak"]["allocated_overheads"]["Common"], Decimal("500.00"))
        self.assertEqual(allocated["Bluestreak"]["net_income"], Decimal("-500.00"))

        self.assertEqual(allocated["Clarus"]["allocated_overheads"]["Common"], Decimal("500.00"))
        self.assertEqual(allocated["Clarus"]["net_income"], Decimal("-500.00"))

        # Cost Center balanced out to exactly zero
        self.assertEqual(allocated["Common"]["net_income"], Decimal("0.00"))

if __name__ == "__main__":
    unittest.main()
