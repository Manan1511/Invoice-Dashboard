# MIS P&L Automation Dashboard — Implementation Plan

## Goal

Build a **React + FastAPI web dashboard** that automates the monthly Tally Prime → MIS Excel workflow.  
The user uploads the new month's Trial Balance Excel export from Tally, the app:
1. Detects unmapped ledgers — **stops and forces the user to define them** before proceeding.
2. Writes the new month's data into the `List of Ledgers` sheet of a **brand-new workbook** cloned from the previous month's template.
3. Checks `TB YTD` for existing YTD data; if missing, **rolls forward from the prior month** automatically.
4. Generates the fully computed Excel file (with all formulas intact — P&L, COGS, Stock, etc.).
5. Renders a **live P&L dashboard** with charts and an Excel download button.

## Project Type
**WEB** — frontend-specialist (React/Vite) + backend-specialist (FastAPI/Python)

## Tech Stack
| Layer | Technology |
|---|---|
| Frontend | React + Vite + TypeScript |
| UI Library | shadcn/ui + Tailwind CSS v4 |
| Charts | Recharts |
| Backend | FastAPI (Python 3.11+) |
| Excel Engine | openpyxl |
| State | Zustand + TanStack Query |

## Tasks

### PHASE 0 — Setup
- [ ] T0.1 Backend scaffold
- [ ] T0.2 Frontend scaffold
- [ ] T0.3 Store template workbook

### PHASE 1 — Backend Parsing
- [ ] T1.1 tb_parser.py
- [ ] T1.2 ledger_mapper.py
- [ ] T1.3 POST /upload/tb router

### PHASE 2 — Mapping & YTD
- [ ] T2.1 POST /ledgers/map router
- [ ] T2.2 ytd_calculator.py

### PHASE 3 — Workbook Generation
- [ ] T3.1 workbook_builder.py
- [ ] T3.2 pl_extractor.py
- [ ] T3.3 POST /generate router
- [ ] T3.4 GET /files/{filename} download

### PHASE 4 — Frontend
- [ ] T4.1 UploadPage.tsx
- [ ] T4.2 MapLedgersPage.tsx
- [ ] T4.3 DashboardPage.tsx
- [ ] T4.4 Reusable components
- [ ] T4.5 Design system

### PHASE 5 — Polish
- [ ] T5.1 CORS config
- [ ] T5.2 Error handling
- [ ] T5.3 Month history nav

## Done When
- [ ] Full pipeline works end-to-end with real data
- [ ] Generated Excel opens correctly in Microsoft Excel
- [ ] Unmapped ledger flow blocks processing
- [ ] YTD rolls forward correctly
