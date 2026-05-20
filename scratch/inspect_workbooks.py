import openpyxl
import os

files = [
    "1. MIS_April 2025.xlsx",
    "MIS_May 2025.xlsx",
    "1. MIS_June 2025.xlsx"
]

for filename in files:
    path = os.path.join("C:/Users/manan/Downloads/Projects/Invoice Dashboard", filename)
    if os.path.exists(path):
        wb = openpyxl.load_workbook(path, read_only=True)
        print(f"File: {filename}")
        print(f"Sheets: {wb.sheetnames}\n")
    else:
        print(f"File not found: {filename}")
