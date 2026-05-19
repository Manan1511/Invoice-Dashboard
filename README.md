# 📊 Tally MIS P&L Automation Dashboard

An enterprise-grade **React + FastAPI** web dashboard that automates the monthly **Tally Prime → MIS Excel** workflow. Upload a Trial Balance export, map any new ledger accounts, generate a formula-intact Excel report, and explore an interactive multi-vertical P&L dashboard — all in one pipeline.

---

## 🚀 Key Features

| Feature | Description |
|---|---|
| 📥 **Trial Balance Parser** | Parses Tally Prime Excel exports, detecting `TB` / `TB YTD` sheets and extracting monthly + cumulative YTD balances |
| 🚦 **Dynamic Ledger Mapping** | Detects unmapped ledgers, halts execution, and presents a structured table UI for classification across Group, Head, Business Vertical, and Indirect Expense category |
| ➕ **Custom Dropdown Options** | Users can type any custom value directly inside a mapping dropdown and save it to the master list on-the-fly |
| 🔄 **YTD Roll-Forward Engine** | If the TB export has no YTD columns, the system rolls forward YTD balances from the prior month's MIS workbook automatically |
| ⚠️ **YTD Data Not Available State** | When no YTD data and no prior workbook is provided, the YTD tab displays a premium glassmorphic warning card with actionable resolution steps |
| 🏗️ **Formula-Intact Excel Compiler** | Clones `MIS_template.xlsx`, injects ledger data into the `List of Ledgers` sheet, and preserves all VLOOKUP / SUMIF formulas in dependent P&L sheets |
| 📈 **Live Interactive Dashboard** | Multi-vertical P&L breakdown with Recharts area charts, 4 KPI cards (Revenue, Gross Margin %, Profit before Tax, Indirect Costs), and a full Statement of P&L table |
| 🛡️ **Comprehensive Error Handling** | Client-side file validation, 120s timeout guard, typed error categorisation (network / validation / parse / server), dismissable error banners with hints, and a backend-offline detector |

---

## 🛠️ Architecture & Tech Stack

```mermaid
graph TD
    A[Tally Trial Balance Excel] -->|Upload| B(FastAPI Backend)
    B -->|Validate & Save| V[File Validation Layer]
    V -->|Parse Tally Sheets| C[tb_parser.py]
    C -->|Check Mapping Table| D[ledger_mapper.py]
    D -->|Unmapped Ledgers Found| E[React Mapping UI]
    E -->|Submit Mappings| B
    B -->|YTD Check & Roll-Forward| F[ytd_calculator.py]
    F -->|Prior Month Workbook| G[(workbooks/)]
    B -->|Clone Template & Fill| H[workbook_builder.py]
    H -->|openpyxl| I[MIS_template.xlsx]
    B -->|Compute Financial Metrics| J[pl_extractor.py]
    J -->|JSON pl_data| K[React Dashboard + Recharts]
    H -->|Output| L[Generated MIS Report .xlsx]
```

### Technology Matrix

| Layer | Technology |
|---|---|
| **Frontend** | React 18, Vite, TypeScript, Vanilla CSS (glassmorphism), Recharts, Lucide Icons |
| **Backend** | FastAPI, Python 3.11+, Uvicorn (ASGI) |
| **Excel Engine** | `openpyxl` |
| **Data Validation** | Pydantic v2 |
| **Dev Orchestration** | `concurrently` (npm) |

> **Note:** The README previously listed Tailwind CSS, Zustand, and TanStack Query — these are **not** used. Styling is plain Vanilla CSS with CSS custom properties.

---

## 📁 Repository Structure

```text
Invoice Dashboard/
├── .agent/                      # Antigravity agent config, skills & workflows
├── backend/
│   ├── main.py                  # FastAPI app — routes, validation, session management
│   ├── requirements.txt         # Python dependencies
│   ├── models/
│   │   ├── ledger.py            # LedgerEntry, LedgerMapping, SessionMappingState schemas
│   │   └── pl_data.py           # PLRow, PLBreakdown, PLDataResponse schemas (+ has_ytd flag)
│   ├── services/
│   │   ├── tb_parser.py         # Tally TB Excel parser (monthly + YTD sheet merge)
│   │   ├── ledger_mapper.py     # Mapping rule loader & template appender
│   │   ├── ytd_calculator.py    # YTD detection & roll-forward from prior workbook
│   │   ├── workbook_builder.py  # Template clone & data injection via openpyxl
│   │   └── pl_extractor.py      # Multi-vertical P&L computation (6 categories, 11 verticals)
│   ├── uploads/                 # Temp storage for uploaded files (git-ignored)
│   └── workbooks/               # Generated monthly MIS output files (git-ignored)
├── docs/
│   └── PLAN-mis-automation.md   # Implementation plan & milestone log
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # Full React SPA — 3-stage wizard (Upload → Mapping → Dashboard)
│   │   └── index.css            # Design system — dark glassmorphism, CSS variables, animations
│   ├── package.json
│   └── tsconfig.json
├── templates/
│   └── MIS_template.xlsx        # Master Excel template with formulas intact
├── package.json                 # Root orchestrator (install:all, dev, dev:frontend, dev:backend)
└── .gitignore
```

---

## ⚙️ Installation & Setup

### Prerequisites
- **Node.js** v18+
- **Python** v3.11+

### One-Command Install (Recommended)

From the project root:
```bash
npm run install:all
```
This installs frontend npm packages and backend Python dependencies simultaneously.

### Manual Setup

#### Frontend
```bash
cd frontend
npm install
```

#### Backend
```bash
cd backend

# Create and activate a virtual environment (recommended)
python -m venv venv

# Windows (PowerShell):
venv\Scripts\Activate.ps1
# macOS / Linux:
source venv/bin/activate

pip install -r requirements.txt
```

---

## 🏃 Running Locally

### Both Servers (Recommended)
```bash
npm run dev
```
Spins up both servers concurrently:
- **Frontend:** [http://localhost:5173](http://localhost:5173)
- **Backend API:** [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **API Docs (Swagger):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### Individual Servers
```bash
npm run dev:frontend   # Vite dev server only
npm run dev:backend    # FastAPI + Uvicorn only (hot-reload enabled)
```

---

## 🔄 Pipeline Walkthrough

### Stage 1 — Upload
1. Select the report **Month** and **Fiscal Year**.
2. Upload the **Active Trial Balance** (`.xlsx` / `.xls`, max 50 MB) exported from Tally Prime.
3. Optionally upload the **Prior Month MIS Workbook** to enable YTD roll-forward.
4. Click **Proceed to Mapping Check**.

### Stage 2 — Ledger Mapping *(skipped if all ledgers are already mapped)*
1. Any ledger not present in the master mapping template is listed in a structured table.
2. For each, select the **Accounting Head**, **Group** (BS/P&L), **Classification**, and **Business Vertical**.
3. Use **+ Add Custom…** in any dropdown to create a new option that persists for future months.
4. Click **Approve Mappings & Build MIS** to trigger Excel generation.

### Stage 3 — Interactive Dashboard
- Switch between **Monthly Review** and **YTD Review** tabs.
- If no YTD data is available, the YTD tab shows a friendly warning with resolution steps instead of empty charts.
- Download the generated `.xlsx` workbook using the **Download Excel** button.
- Use **Start New Month** to reset and begin a new month's pipeline.

---

## 🔌 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/domain-lists` | Returns dropdown options (groups, heads, verticals, classifications) |
| `POST` | `/api/upload` | Upload TB file + optional prior workbook; returns unmapped ledgers or full `pl_data` |
| `POST` | `/api/map` | Submit ledger mappings; triggers workbook generation; returns `pl_data` |
| `GET` | `/api/download?session_id=...` | Stream the generated `.xlsx` MIS report |

### `POST /api/upload` — Request
| Field | Type | Required | Description |
|---|---|---|---|
| `file` | `File` (.xlsx/.xls) | ✅ | Active monthly Trial Balance |
| `prior_file` | `File` (.xlsx/.xls) | ❌ | Prior month MIS for YTD roll-forward |
| `month` | `int` (1–12) | ✅ | Report month number |
| `year` | `int` (2000–2100) | ✅ | Report fiscal year |

### `POST /api/upload` — Response
```jsonc
// All ledgers mapped → jump straight to dashboard
{
  "success": true,
  "session_id": "uuid",
  "output_file": "MIS_Report_2026_03.xlsx",
  "pl_data": { "month_label": "Mar'26", "ytd_label": "YTD'26", "has_ytd": true, ... }
}

// Unmapped ledgers found → redirect to mapping step
{
  "success": false,
  "session_id": "uuid",
  "unmapped_count": 3,
  "unmapped_ledgers": ["Ledger A", "Ledger B", "Ledger C"]
}
```

---

## 🛡️ Error Handling

### Backend
- **422** — File is not `.xlsx`/`.xls`, or month/year out of range
- **413** — File exceeds 50 MB limit
- **400** — TB sheet not found, zero rows parsed, or invalid mapping schema
- **404** — Session expired or not found
- **500** — YTD calculation, workbook generation, or P&L extraction failure (all with specific messages)
- Global unhandled exceptions return structured `{detail, hint}` JSON (never raw HTML)

### Frontend
- **Pre-flight validation** — file extension and size checked client-side before any network call
- **120s timeout** — `AbortController` prevents indefinite hangs on large files
- **Typed error categories** — `network` / `validation` / `parse` / `server` with distinct UI treatment
- **Backend offline banner** — detected on page load via the `/api/domain-lists` connectivity check
- **Dismissable error panel** — `✕` close button + `💡` hint line for actionable guidance
- **Retry button** — shown automatically for network-category errors

---

## 🗂️ Key Design Decisions

| Decision | Rationale |
|---|---|
| In-memory session store (`SESSIONS` dict) | Keeps the backend stateless-friendly and dependency-free for single-user local use; replace with Redis for multi-user deployments |
| `openpyxl` over `xlwings` / `xlrd` | Cross-platform, no Excel installation required, full formula write support |
| `abs()` on Credit balance values | Tally Prime exports Credit accounts (Revenue, Sales) as negative closing values; wrapping in `abs()` ensures correct chart rendering |
| YTD `has_ytd` flag in API response | Allows the frontend to gracefully degrade the YTD tab without requiring a separate API call |
| Vanilla CSS over Tailwind | Full design control with glassmorphism, CSS custom properties, and micro-animations without build-time purging complexity |

---

## 📄 License

Private — Internal MIS automation tool. Not licensed for redistribution.
