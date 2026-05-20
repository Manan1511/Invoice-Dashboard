import React, { useState, useEffect } from 'react';
import { 
  Upload, FileText, ChevronRight, Download, RefreshCw, BarChart2, 
  PieChart, CheckCircle, AlertTriangle, ArrowUpRight, DollarSign, 
  TrendingUp, TrendingDown, Layers, HelpCircle, X, WifiOff, Edit2, Plus, Trash2, BookOpen
} from 'lucide-react';
import { 
  ResponsiveContainer, XAxis, YAxis, Tooltip, Legend, BarChart, Bar, ReferenceLine
} from 'recharts';
import { motion, AnimatePresence } from 'framer-motion';

// Backend Server URL
const API_BASE = "http://127.0.0.1:8000/api";

interface PLRow {
  particulars: string;
  values: Record<string, number | null>;
  is_header: boolean;
  is_total: boolean;
}

interface PLBreakdown {
  columns: string[];
  rows: PLRow[];
}

interface DebtorCreditorPivotEntry {
  vertical: string;
  opening: number;
  debit: number;
  credit: number;
  closing: number;
  opening_ytd: number;
  debit_ytd: number;
  credit_ytd: number;
  closing_ytd: number;
}

interface DebtorCreditorPivot {
  debtors: DebtorCreditorPivotEntry[];
  creditors: DebtorCreditorPivotEntry[];
}

interface PLDataResponse {
  month_label: string;
  ytd_label: string;
  month_data: PLBreakdown;
  ytd_data: PLBreakdown;
  kpis: Record<string, number>;
  has_ytd?: boolean;
  debtors_creditors_pivot?: DebtorCreditorPivot;
}

interface DomainLists {
  groups: string[];
  heads: string[];
  verticals: string[];
  classifications: string[];
}

interface LedgerMappingRow {
  ledger_name: string;
  under: string | null;
  group: string;
  head: string;
  classification: string | null;
  vertical: string;
}

/** Typed error object to differentiate error categories for UX messaging */
type ErrorCategory = 'network' | 'validation' | 'server' | 'parse';
interface AppError {
  category: ErrorCategory;
  title: string;
  message: string;
  hint?: string;
}

/** Extracts a user-friendly AppError from a fetch Response or thrown Error */
async function parseApiError(res: Response | null, caught: unknown): Promise<AppError> {
  if (res === null) {
    // Network / timeout failure
    const msg = caught instanceof Error ? caught.message : String(caught);
    if (msg.includes('NetworkError') || msg.includes('Failed to fetch') || msg.includes('Load failed')) {
      return {
        category: 'network',
        title: 'Cannot Reach Server',
        message: 'The backend server is not responding. Please make sure the Python server is running on port 8000.',
        hint: 'Run: cd backend && python main.py'
      };
    }
    if (msg.includes('AbortError') || msg.toLowerCase().includes('timeout')) {
      return {
        category: 'network',
        title: 'Request Timed Out',
        message: 'The server took too long to respond. The file may be very large — please try again.',
      };
    }
    return {
      category: 'network',
      title: 'Connection Error',
      message: msg || 'An unexpected network error occurred.',
    };
  }

  // Try to parse the JSON error body from the server
  let detail = `Server responded with status ${res.status}.`;
  let hint: string | undefined;
  try {
    const body = await res.json();
    detail = body.detail || detail;
    hint = body.hint;
  } catch {
    // Non-JSON response (e.g. nginx 502 HTML page)
    detail = `Server returned an unreadable response (HTTP ${res.status}). The server may be overloaded or crashed.`;
  }

  if (res.status === 422 || res.status === 413) {
    return { category: 'validation', title: 'Invalid File', message: detail, hint };
  }
  if (res.status === 400) {
    return { category: 'parse', title: 'File Parse Error', message: detail, hint };
  }
  if (res.status === 404) {
    return { category: 'server', title: 'Session Not Found', message: detail, hint };
  }
  return { category: 'server', title: 'Server Error', message: detail, hint };
}

/** Client-side file validation before sending to backend */
function validateFileSelection(file: File): string | null {
  const ALLOWED = ['.xlsx', '.xls'];
  const ext = '.' + file.name.split('.').pop()?.toLowerCase();
  if (!ALLOWED.includes(ext)) {
    return `"${file.name}" is not an Excel file. Please select a .xlsx or .xls file.`;
  }
  const MAX_MB = 50;
  if (file.size > MAX_MB * 1024 * 1024) {
    return `"${file.name}" is ${(file.size / (1024 * 1024)).toFixed(1)} MB — exceeds the 50 MB limit. Please compress or split the file.`;
  }
  return null;
}

/** Fetch wrapper with configurable timeout via AbortController */
async function fetchWithTimeout(url: string, options: RequestInit, timeoutMs = 90_000): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export default function App() {
  // App Workflow Stages: 'UPLOAD' | 'LEDGER_REVIEW' | 'MAPPING' | 'PROCESSING' | 'DASHBOARD'
  const [stage, setStage] = useState<'UPLOAD' | 'LEDGER_REVIEW' | 'MAPPING' | 'PROCESSING' | 'DASHBOARD'>('UPLOAD');
  const [progressState, setProgressState] = useState<{status: string; step: string} | null>(null);

  const listenToProgress = (currentSessionId: string) => {
    setStage('PROCESSING');
    setProgressState({status: 'processing', step: 'PARSING_TB'});
    const eventSource = new EventSource(`${API_BASE}/status/${currentSessionId}`);
    
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.status === 'completed') {
        eventSource.close();
        setPlData(data.result.pl_data);
        setStage('DASHBOARD');
      } else if (data.status === 'error') {
        eventSource.close();
        setAppError({ category: 'server', title: 'Processing Error', message: data.error });
        setStage('UPLOAD');
      } else {
        setProgressState(data);
      }
    };
    
    eventSource.onerror = () => {
      eventSource.close();
      setAppError({ category: 'network', title: 'Connection Lost', message: 'Lost connection to progress stream.' });
      setStage('UPLOAD');
    };
  };
  
  // Data States
  const [activeFile, setActiveFile] = useState<File | null>(null);
  const [priorFile, setPriorFile] = useState<File | null>(null);
  const [ledgerFile, setLedgerFile] = useState<File | null>(null);
  const [month, setMonth] = useState<number>(3); // March
  const [year, setYear] = useState<number>(2026);
  const [closingStock, setClosingStock] = useState<string>('');

  // Ledger Review State
  const [ledgerSessionId, setLedgerSessionId] = useState<string>('');
  const [reviewLedgers, setReviewLedgers] = useState<LedgerMappingRow[]>([]);
  
  // Loading & Error States
  const [loading, setLoading] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [appError, setAppError] = useState<AppError | null>(null);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null); // null = checking
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  
  // Session & Dynamic Data
  const [sessionId, setSessionId] = useState<string>("");
  const [unmappedLedgers, setUnmappedLedgers] = useState<string[]>([]);
  const [mappings, setMappings] = useState<Record<string, {
    under: string;
    group: string;
    head: string;
    classification: string;
    vertical: string;
  }>>({});
  
  const [domainLists, setDomainLists] = useState<DomainLists>({
    groups: [],
    heads: [],
    verticals: [],
    classifications: []
  });

  const [plData, setPlData] = useState<PLDataResponse | null>(null);
  const [activeTab, setActiveTab] = useState<'MONTH' | 'YTD'>('MONTH');

  // Custom Options States & Handlers for dynamic dropdown additions
  const [customMode, setCustomMode] = useState<Record<string, boolean>>({});
  const [customValues, setCustomValues] = useState<Record<string, string>>({});

  const saveCustomOption = (
    ledgerName: string, 
    columnKey: 'group' | 'head' | 'classification' | 'vertical'
  ) => {
    const typedVal = (customValues[`${ledgerName}-${columnKey}`] || '').trim();
    if (!typedVal) {
      cancelCustomOption(ledgerName, columnKey);
      return;
    }

    const listKey = columnKey === 'head' ? 'heads' :
                    columnKey === 'group' ? 'groups' :
                    columnKey === 'classification' ? 'classifications' : 'verticals';

    if (!domainLists[listKey].includes(typedVal)) {
      setDomainLists({
        ...domainLists,
        [listKey]: [...domainLists[listKey], typedVal].sort()
      });
    }

    const rowVal = mappings[ledgerName] || {
      under: "Indirect Expenses",
      group: "P&L",
      head: "6. Indirect Expense",
      classification: "Misc Expenses",
      vertical: "Common"
    };

    setMappings({
      ...mappings,
      [ledgerName]: {
        ...rowVal,
        [columnKey]: typedVal
      }
    });

    setCustomMode({
      ...customMode,
      [`${ledgerName}-${columnKey}`]: false
    });
  };

  const cancelCustomOption = (ledgerName: string, columnKey: string) => {
    setCustomMode({
      ...customMode,
      [`${ledgerName}-${columnKey}`]: false
    });
    setCustomValues({
      ...customValues,
      [`${ledgerName}-${columnKey}`]: ''
    });
  };

  const renderCellDropdown = (
    ledgerName: string,
    columnKey: 'group' | 'head' | 'classification' | 'vertical',
    currentValue: string,
    options: string[],
    disabled = false
  ) => {
    const modeKey = `${ledgerName}-${columnKey}`;
    const isCustom = customMode[modeKey];
    
    if (isCustom) {
      return (
        <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
          <input
            type="text"
            className="form-input"
            style={{ 
              flex: 1, 
              padding: '0.4rem 0.5rem', 
              fontSize: '0.8rem', 
              height: '34px',
              minWidth: '110px'
            }}
            placeholder={`Custom ${columnKey}...`}
            value={customValues[modeKey] || ''}
            onChange={e => setCustomValues({
              ...customValues,
              [modeKey]: e.target.value
            })}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault();
                saveCustomOption(ledgerName, columnKey);
              } else if (e.key === 'Escape') {
                cancelCustomOption(ledgerName, columnKey);
              }
            }}
            autoFocus
          />
          <button
            type="button"
            className="btn-primary"
            style={{ 
              padding: '0.4rem', 
              height: '34px', 
              width: '34px', 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'center', 
              borderRadius: '4px',
              background: 'var(--accent-emerald)',
              border: 'none',
              cursor: 'pointer'
            }}
            onClick={() => saveCustomOption(ledgerName, columnKey)}
          >
            ✓
          </button>
          <button
            type="button"
            className="btn-secondary"
            style={{ 
              padding: '0.4rem', 
              height: '34px', 
              width: '34px', 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'center', 
              borderRadius: '4px',
              border: '1px solid rgba(255,255,255,0.1)',
              background: 'rgba(255,255,255,0.05)',
              cursor: 'pointer'
            }}
            onClick={() => cancelCustomOption(ledgerName, columnKey)}
          >
            ✕
          </button>
        </div>
      );
    }

    return (
      <select
        value={currentValue}
        disabled={disabled}
        onChange={e => {
          const val = e.target.value;
          if (val === "__NEW__") {
            setCustomMode({ ...customMode, [modeKey]: true });
            setCustomValues({ ...customValues, [modeKey]: "" });
          } else if (ledgerName.startsWith('__review__')) {
            // LEDGER_REVIEW stage — update reviewLedgers array by index
            const rowIdx = parseInt(ledgerName.replace('__review__', ''), 10);
            setReviewLedgers(prev => {
              const updated = [...prev];
              if (columnKey === 'head') {
                const isBS = val === 'Sundry Debtor' || val === 'Sundry Creditor';
                updated[rowIdx] = {
                  ...updated[rowIdx],
                  head: val,
                  group: isBS ? 'BS' : 'P&L',
                  classification: isBS ? '' : (val === '1. Sales Accounts' ? 'Sales' : 'Misc Expenses')
                };
              } else {
                updated[rowIdx] = { ...updated[rowIdx], [columnKey]: val };
              }
              return updated;
            });
          } else {
            // MAPPING stage — update mappings dict by ledger name
            const rowVal = mappings[ledgerName] || {
              under: "Indirect Expenses",
              group: "P&L",
              head: "6. Indirect Expense",
              classification: "Misc Expenses",
              vertical: "Common"
            };
            if (columnKey === 'head') {
              const isBS = val === "Sundry Debtor" || val === "Sundry Creditor";
              setMappings({
                ...mappings,
                [ledgerName]: {
                  ...rowVal,
                  head: val,
                  group: isBS ? "BS" : "P&L",
                  classification: isBS ? "" : (val === "1. Sales Accounts" ? "Sales" : "Misc Expenses")
                }
              });
            } else {
              setMappings({ ...mappings, [ledgerName]: { ...rowVal, [columnKey]: val } });
            }
          }
        }}
        className="form-select"
      >
        {options.map(opt => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
        <option value="__NEW__" style={{ color: 'var(--accent-emerald)', fontWeight: 'bold' }}>
          + Add Custom...
        </option>
      </select>
    );
  };

  // Fetch domain dropdown options on load; also acts as a backend connectivity check
  useEffect(() => {
    fetch(`${API_BASE}/domain-lists`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(data => {
        setDomainLists(data);
        setBackendOnline(true);
      })
      .catch(() => {
        setBackendOnline(false);
      });
  }, []);

  // Listen for Escape key to close error modal pop-up
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setAppError(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Handle Ledger File Upload → parse and enter LEDGER_REVIEW stage
  const handleLedgerUpload = async () => {
    if (!ledgerFile) return;
    setAppError(null);
    setLoading(true);
    setStatusMessage('Parsing List of Ledgers...');

    const formData = new FormData();
    formData.append('ledger_file', ledgerFile);

    let res: Response | null = null;
    try {
      res = await fetchWithTimeout(`${API_BASE}/parse-ledgers`, { method: 'POST', body: formData }, 30_000);
      if (!res.ok) {
        setAppError(await parseApiError(res, null));
        return;
      }
      const data = await res.json();
      setLedgerSessionId(data.ledger_session_id);
      // Map snake_case from API to camelCase-friendly interface (they match, so direct use)
      setReviewLedgers(data.ledgers as LedgerMappingRow[]);
      setStage('LEDGER_REVIEW');
    } catch (err: unknown) {
      setAppError(await parseApiError(res, err));
    } finally {
      setLoading(false);
    }
  };

  // Handle Ledger File Upload Directly without review
  const handleLedgerDirectUpload = async () => {
    if (!ledgerFile) return;
    setAppError(null);
    setSuccessMessage(null);
    setLoading(true);
    setStatusMessage('Uploading and applying List of Ledgers directly...');

    const formData = new FormData();
    formData.append('ledger_file', ledgerFile);

    let res: Response | null = null;
    try {
      res = await fetchWithTimeout(`${API_BASE}/upload-ledgers-direct`, { method: 'POST', body: formData }, 60_000);
      if (!res.ok) {
        setAppError(await parseApiError(res, null));
        return;
      }
      const data = await res.json();
      setSuccessMessage(data.message || `Master template updated directly with ${data.saved_count} ledger entries.`);
      setLedgerFile(null); // Clear selected ledger file after successful upload
    } catch (err: unknown) {
      setAppError(await parseApiError(res, err));
    } finally {
      setLoading(false);
    }
  };

  // Handle uploading a ledger list file in Stage 2 to auto-resolve mappings
  const handleResolverUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files ? e.target.files[0] : null;
    if (!file) return;

    // Validate resolver file
    const fileError = validateFileSelection(file);
    if (fileError) {
      setAppError({ category: 'validation', title: 'Invalid Resolver File', message: fileError });
      return;
    }

    setAppError(null);
    setSuccessMessage(null);
    setLoading(true);
    setStatusMessage('Parsing Excel resolver list...');

    const formData = new FormData();
    formData.append('ledger_file', file);

    let res: Response | null = null;
    try {
      res = await fetchWithTimeout(`${API_BASE}/parse-ledgers`, { method: 'POST', body: formData }, 30_000);
      if (!res.ok) {
        setAppError(await parseApiError(res, null));
        return;
      }
      const data = await res.json();
      const resolverLedgers = data.ledgers as LedgerMappingRow[];

      // Build a lookup map of lowercased ledger name to mapping details
      const resolverMap = new Map<string, LedgerMappingRow>();
      resolverLedgers.forEach(row => {
        if (row.ledger_name) {
          resolverMap.set(row.ledger_name.trim().toLowerCase(), row);
        }
      });

      // Match case-insensitively with active unmapped ledgers
      let matchedCount = 0;
      const updatedMappings = { ...mappings };

      unmappedLedgers.forEach(ledgerName => {
        const match = resolverMap.get(ledgerName.trim().toLowerCase());
        if (match) {
          updatedMappings[ledgerName] = {
            under: match.under || 'Indirect Expenses',
            group: match.group || 'P&L',
            head: match.head || '6. Indirect Expense',
            classification: match.classification || 'Misc Expenses',
            vertical: match.vertical || 'Common'
          };
          matchedCount++;
        }
      });

      setMappings(updatedMappings);
      setSuccessMessage(`Automatically matched and populated ${matchedCount} out of ${unmappedLedgers.length} unmapped ledgers.`);
      
      // Clear input value so same file can be uploaded again if needed
      e.target.value = '';
    } catch (err: unknown) {
      setAppError(await parseApiError(res, err));
    } finally {
      setLoading(false);
    }
  };

  // Handle confirming (possibly edited) ledger list → save permanently then continue to TB upload check
  const handleLedgerConfirm = async () => {
    if (reviewLedgers.length === 0) {
      setAppError({
        category: 'validation',
        title: 'Empty Ledger List',
        message: 'The ledger list cannot be empty. Add at least one entry before confirming.'
      });
      return;
    }
    setAppError(null);
    setLoading(true);
    setStatusMessage('Saving ledger list to master template...');

    const formData = new FormData();
    formData.append('ledger_session_id', ledgerSessionId);
    formData.append('ledgers_data', JSON.stringify(reviewLedgers));

    let res: Response | null = null;
    try {
      res = await fetchWithTimeout(`${API_BASE}/confirm-ledgers`, { method: 'POST', body: formData }, 30_000);
      if (!res.ok) {
        setAppError(await parseApiError(res, null));
        return;
      }
      // Ledger saved — now proceed with the normal TB upload if a TB file is already selected
      if (activeFile) {
        setStage('UPLOAD');
        // Trigger the upload flow as if the user clicked submit
        await _runTBUpload();
      } else {
        // No TB selected yet — go back to upload so user can select it
        setStage('UPLOAD');
      }
    } catch (err: unknown) {
      setAppError(await parseApiError(res, err));
    } finally {
      setLoading(false);
    }
  };

  /** Core TB upload logic, extracted so it can be called from both submit handler and post-ledger-confirm */
  const _runTBUpload = async () => {
    if (!activeFile) return;
    setAppError(null);
    setLoading(true);
    setStatusMessage('Uploading and parsing Trial Balance data...');

    const formData = new FormData();
    formData.append('file', activeFile);
    if (priorFile) formData.append('prior_file', priorFile);
    formData.append('month', month.toString());
    formData.append('year', year.toString());
    formData.append('closing_stock', closingStock || '0');

    let res: Response | null = null;
    try {
      res = await fetchWithTimeout(`${API_BASE}/upload`, { method: 'POST', body: formData }, 120_000);
      if (!res.ok) {
        setAppError(await parseApiError(res, null));
        return;
      }
      const data = await res.json();
      setSessionId(data.session_id);

      if (data.success === false) {
        setUnmappedLedgers(data.unmapped_ledgers);
        const initialMappings: typeof mappings = {};
        data.unmapped_ledgers.forEach((name: string) => {
          initialMappings[name] = {
            under: 'Indirect Expenses',
            group: 'P&L',
            head: '6. Indirect Expense',
            classification: 'Misc Expenses',
            vertical: 'Common'
          };
        });
        setMappings(initialMappings);
        setStage('MAPPING');
      } else {
        listenToProgress(data.session_id);
      }
    } catch (err: unknown) {
      setAppError(await parseApiError(res, err));
    } finally {
      setLoading(false);
    }
  };

  // Handle Monthly File Upload
  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSuccessMessage(null);
    if (!activeFile) {
      setAppError({ category: 'validation', title: 'No File Selected', message: 'Please select the active monthly Trial Balance file before proceeding.' });
      return;
    }

    // Client-side file validation
    const activeFileError = validateFileSelection(activeFile);
    if (activeFileError) {
      setAppError({ category: 'validation', title: 'Invalid Trial Balance', message: activeFileError });
      return;
    }
    if (priorFile) {
      const priorFileError = validateFileSelection(priorFile);
      if (priorFileError) {
        setAppError({ category: 'validation', title: 'Invalid Prior Workbook', message: priorFileError });
        return;
      }
    }
    if (ledgerFile) {
      const ledgerFileError = validateFileSelection(ledgerFile);
      if (ledgerFileError) {
        setAppError({ category: 'validation', title: 'Invalid Ledger File', message: ledgerFileError });
        return;
      }
      // If a ledger file is provided, parse it first → LEDGER_REVIEW stage
      await handleLedgerUpload();
      return;
    }

    // No ledger file — proceed directly with TB upload
    await _runTBUpload();
  };

  // Submit Mappings form to backend
  const handleMappingSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setStatusMessage("Saving mapping classifications and writing generated Excel report...");
    setAppError(null);
    
    const formattedMappings = Object.entries(mappings).map(([name, val]) => ({
      ledger_name: name,
      under: val.under,
      group: val.group,
      head: val.head,
      classification: val.classification,
      vertical: val.vertical
    }));
    
    const formData = new FormData();
    formData.append("session_id", sessionId);
    formData.append("mappings_data", JSON.stringify(formattedMappings));
    
    let res: Response | null = null;
    try {
      res = await fetchWithTimeout(`${API_BASE}/map`, { method: "POST", body: formData }, 120_000);
      
      if (!res.ok) {
        setAppError(await parseApiError(res, null));
        return;
      }

      const data = await res.json();
      listenToProgress(sessionId);
    } catch (err: unknown) {
      setAppError(await parseApiError(res, err));
    } finally {
      setLoading(false);
    }
  };

  // Handle generated workbook download
  const handleDownload = () => {
    if (!sessionId) return;
    window.open(`${API_BASE}/download?session_id=${sessionId}`, "_blank");
  };

  // Helper to format currency
  const formatCurrency = (val: number | null | undefined) => {
    if (val === null || val === undefined) return "-";
    const absolute = Math.abs(val);
    const formatted = new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0
    }).format(absolute);
    return val < 0 ? `(${formatted})` : formatted;
  };

  // Columns that are aggregation/allocation pools — not individual business verticals
  const EXCLUDED_CHART_COLUMNS = new Set([
    'Total (without share trading)',
    'Total (including share trading)',
    'Factory',
    'Office',
    'Common',
    'Share Trading',
  ]);

  // Prepare chart data for Recharts — always derived dynamically from API response
  const getChartData = () => {
    if (!plData) return [];
    const sourceData = activeTab === 'MONTH' ? plData.month_data : plData.ytd_data;

    // Find Sales and Gross Margin rows
    const salesRow = sourceData.rows.find(r => r.particulars === 'Sales');
    const marginRow = sourceData.rows.find(r => r.particulars === 'Gross margin');

    // Derive verticals from the API columns — exclude aggregation/pool columns
    const chartVerticals = sourceData.columns.filter(v => !EXCLUDED_CHART_COLUMNS.has(v));

    return chartVerticals.map(v => ({
      name: v,
      // Do NOT clamp to 0 — negative revenue or margin is meaningful data
      Revenue: salesRow ? (salesRow.values[v] ?? 0) : 0,
      "Gross Margin": marginRow ? (marginRow.values[v] ?? 0) : 0,
    }));
  };

  // Helper to check negative values
  const getValueColor = (val: number | null | undefined, particulars: string) => {
    if (val === null || val === undefined || val === 0) return 'text-gray';
    if (particulars.toLowerCase().includes('margin %') || particulars.toLowerCase().includes('margin')) {
      return val < 0 ? 'text-red' : 'text-emerald';
    }
    if (particulars.toLowerCase().includes('profit') || particulars.toLowerCase().includes('income')) {
      return val < 0 ? 'text-red' : 'text-emerald';
    }
    return val < 0 ? 'text-red' : 'text-white';
  };

  return (
    <div className="app-container">
      {/* Top Banner Header */}
      <header className="app-header">
        <div>
          <div className="logo-area">
            <div className="logo-icon-wrapper">
              <Layers className="logo-icon" />
            </div>
            <div>
              <h1 className="app-title">
                Tally MIS <span style={{ color: 'var(--accent-emerald)' }}>Automation</span>
              </h1>
              <p className="app-subtitle">
                Seamless Monthly Ledger Mapping, YTD Roll-Forward & Interactive Financial Dashboard
              </p>
            </div>
          </div>
        </div>

        {stage === 'DASHBOARD' && plData && (
          <div className="header-actions">
            <button onClick={handleDownload} className="btn-primary">
              <Download size={18} /> Download Excel (.xlsx)
            </button>
            <button 
              onClick={() => {
                setActiveFile(null);
                setPriorFile(null);
                setStage('UPLOAD');
              }} 
              className="btn-secondary"
            >
              <RefreshCw size={14} /> Start New Month
            </button>
          </div>
        )}
      </header>

      {/* Backend Offline Warning Banner */}
      {backendOnline === false && (
        <div style={{ background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.25)', borderRadius: '12px', padding: '0.85rem 1.25rem', display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
          <WifiOff size={18} style={{ color: '#ef4444', flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <span style={{ color: '#ef4444', fontWeight: '600', fontSize: '0.875rem' }}>Backend server is offline.</span>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginLeft: '0.5rem' }}>Make sure the Python server is running on port 8000: <code style={{ color: 'var(--accent-teal)' }}>python backend/main.py</code></span>
          </div>
        </div>
      )}

      {/* Error Modal Pop-up Overlay */}
      {appError && (
        <div className="error-modal-overlay">
          <div className="error-modal-card animate-slideDown" style={{ 
            borderColor: appError.category === 'network' ? 'var(--accent-gold)' : 'var(--accent-red)' 
          }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '1.25rem' }}>
              <div className="error-modal-icon-wrapper" style={{
                background: appError.category === 'network' ? 'rgba(245, 158, 11, 0.1)' : 'rgba(244, 63, 94, 0.1)',
                color: appError.category === 'network' ? 'var(--accent-gold)' : 'var(--accent-red)'
              }}>
                <AlertTriangle size={24} />
              </div>
              <div style={{ flex: 1 }}>
                <h3 className="error-modal-title" style={{
                  color: appError.category === 'network' ? '#fde047' : '#fda4af'
                }}>
                  {appError.title}
                </h3>
                <p className="error-modal-desc">{appError.message}</p>
                
                {appError.hint && (
                  <div className="error-modal-hint-box">
                    <span className="error-modal-hint-bulb">💡</span>
                    <code className="error-modal-hint-code">{appError.hint}</code>
                  </div>
                )}
              </div>
              <button
                onClick={() => setAppError(null)}
                className="error-modal-close-btn"
                title="Dismiss"
              >
                <X size={20} />
              </button>
            </div>

            {/* Footer Action Bar if network error */}
            {appError.category === 'network' && (
              <div className="error-modal-footer">
                <button
                  onClick={() => { setAppError(null); setStage('UPLOAD'); }}
                  className="error-modal-retry-btn"
                >
                  <RefreshCw size={14} /> Retry Upload
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Success Banner */}
      {successMessage && (
        <div style={{ background: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.25)', borderRadius: '12px', padding: '0.85rem 1.25rem', display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.5rem' }} className="animate-fadeIn">
          <CheckCircle size={18} style={{ color: 'var(--accent-emerald)', flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <span style={{ color: 'white', fontWeight: '600', fontSize: '0.875rem' }}>Success!</span>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginLeft: '0.5rem' }}>{successMessage}</span>
          </div>
          <button
            onClick={() => setSuccessMessage(null)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', padding: '2px', borderRadius: '4px', flexShrink: 0 }}
            title="Dismiss"
          >
            <X size={16} />
          </button>
        </div>
      )}

      {/* Processing Loader Panel (SSE) */}
      {stage === 'PROCESSING' && progressState && (
        <div className="loader-overlay">
          <div className="glass-panel" style={{ width: '400px', padding: '2rem' }}>
            <h3 className="loader-title" style={{ marginTop: 0, marginBottom: '1.5rem', textAlign: 'center' }}>
              Building Dashboard
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {[
                { id: 'PARSING_TB', label: 'Reading Trial Balance...' },
                { id: 'ROLL_FORWARD_YTD', label: 'Calculating YTD Balances...' },
                { id: 'GENERATING_EXCEL', label: 'Building MIS Workbook...' },
                { id: 'EXTRACTING_DASHBOARD', label: 'Extracting P&L Insights...' }
              ].map((step, index) => {
                const steps = ['PARSING_TB', 'ROLL_FORWARD_YTD', 'GENERATING_EXCEL', 'EXTRACTING_DASHBOARD'];
                const currentIndex = steps.indexOf(progressState.step);
                const isCompleted = index < currentIndex;
                const isActive = index === currentIndex;
                const isPending = index > currentIndex;

                return (
                  <motion.div 
                    key={step.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: isPending ? 0.4 : 1, y: 0 }}
                    style={{ 
                      display: 'flex', 
                      alignItems: 'center', 
                      gap: '1rem',
                      color: isActive ? 'white' : isCompleted ? 'var(--accent-emerald)' : 'var(--text-muted)',
                      fontWeight: isActive ? 600 : 400
                    }}
                  >
                    <div style={{
                      width: '24px', height: '24px', borderRadius: '50%',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      background: isCompleted ? 'var(--accent-emerald)' : isActive ? 'rgba(16, 185, 129, 0.2)' : 'rgba(255,255,255,0.05)',
                      color: isCompleted ? 'white' : isActive ? 'var(--accent-emerald)' : 'var(--text-muted)'
                    }}>
                      {isCompleted ? <CheckCircle size={14} /> : isActive ? <div className="pulse-dot" style={{ width: '8px', height: '8px' }}></div> : <span style={{ fontSize: '10px' }}>{index + 1}</span>}
                    </div>
                    <span>{step.label}</span>
                  </motion.div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Global Processing Loader Panel */}
      {loading && stage !== 'PROCESSING' && (
        <div className="loader-overlay">
          <div className="spinner">
            <Layers className="spinner-icon" />
          </div>
          <h3 className="loader-title">{statusMessage}</h3>
          <p className="loader-desc">Processing...</p>
        </div>
      )}

      {/* ==================== STAGE 1: UPLOAD ==================== */}
      {stage === 'UPLOAD' && (
        <div className="upload-grid animate-fadeIn">
          {/* Form Upload Area */}
          <div className="glass-panel">
            <h2 className="guide-title">
              <Upload size={20} style={{ color: 'var(--accent-emerald)' }} /> Start Monthly MIS Build
            </h2>

            <form onSubmit={handleUploadSubmit}>
              {/* Date & Period Fields */}
              <div className="form-row" style={{ marginBottom: '1.5rem', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))' }}>
                <div className="form-group">
                  <label className="form-label">Report Month</label>
                  <select 
                    value={month} 
                    onChange={e => setMonth(parseInt(e.target.value))}
                    className="form-select"
                  >
                    {["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"].map((m, idx) => (
                      <option key={m} value={idx + 1}>{m}</option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Report Fiscal Year</label>
                  <input 
                    type="number" 
                    value={year}
                    onChange={e => setYear(parseInt(e.target.value))}
                    className="form-input"
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Closing Stock (₹)</label>
                  <input 
                    type="number" 
                    placeholder="e.g. 2500000"
                    value={closingStock}
                    onChange={e => setClosingStock(e.target.value)}
                    className="form-input"
                    style={{ borderColor: closingStock ? 'var(--accent-emerald)' : undefined }}
                  />
                </div>
              </div>

              {/* Uploader: Active Month TB File */}
              <div className="form-group" style={{ marginBottom: '1.5rem' }}>
                <label className="form-label">
                  1. Active Tally Prime Trial Balance (Required)
                </label>
                <div className="drop-zone">
                  <input 
                    type="file" 
                    accept=".xlsx,.xls"
                    onChange={e => setActiveFile(e.target.files ? e.target.files[0] : null)}
                  />
                  <div className="drop-zone-content">
                    <div className="drop-icon-wrapper">
                      <FileText size={32} />
                    </div>
                    {activeFile ? (
                      <div>
                        <p className="drop-zone-title" style={{ color: 'white' }}>{activeFile.name}</p>
                        <p className="drop-zone-desc">{(activeFile.size / (1024 * 1024)).toFixed(2)} MB</p>
                      </div>
                    ) : (
                      <div>
                        <p className="drop-zone-title">Click or drag monthly Excel dump here</p>
                        <p className="drop-zone-desc">Supports standard Tally Excel exports (.xlsx, .xls)</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Uploader: Prior Month Workbook */}
              <div className="form-group" style={{ marginBottom: '1.5rem' }}>
                <label className="form-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>2. Prior Month Workbook (Optional)</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--accent-emerald)', background: 'rgba(16, 185, 129, 0.1)', padding: '0.1rem 0.5rem', borderRadius: '10px' }}>Enables YTD Roll-forward</span>
                </label>
                <div className="drop-zone">
                  <input
                    type="file"
                    accept=".xlsx,.xls"
                    onChange={e => setPriorFile(e.target.files ? e.target.files[0] : null)}
                  />
                  <div className="drop-zone-content">
                    <div className="drop-icon-wrapper" style={{ color: 'var(--accent-teal)' }}>
                      <Layers size={28} />
                    </div>
                    {priorFile ? (
                      <div>
                        <p className="drop-zone-title" style={{ color: 'white' }}>{priorFile.name}</p>
                        <p className="drop-zone-desc">{(priorFile.size / (1024 * 1024)).toFixed(2)} MB</p>
                      </div>
                    ) : (
                      <div>
                        <p className="drop-zone-title">Select previous month's final report</p>
                        <p className="drop-zone-desc">Required if Tally dump does not contain active YTD balances</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Uploader: Custom List of Ledgers */}
              <div className="form-group" style={{ marginBottom: '2rem' }}>
                <label className="form-label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>3. List of Ledgers (Optional)</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--accent-gold)', background: 'rgba(234, 179, 8, 0.1)', padding: '0.1rem 0.5rem', borderRadius: '10px' }}>Replaces Master Template</span>
                </label>
                <div className="drop-zone" style={{ borderColor: ledgerFile ? 'var(--accent-gold)' : undefined }}>
                  <input
                    type="file"
                    accept=".xlsx,.xls"
                    onChange={e => setLedgerFile(e.target.files ? e.target.files[0] : null)}
                  />
                  <div className="drop-zone-content">
                    <div className="drop-icon-wrapper" style={{ color: 'var(--accent-gold)' }}>
                      <BookOpen size={28} />
                    </div>
                    {ledgerFile ? (
                      <div>
                        <p className="drop-zone-title" style={{ color: 'white' }}>{ledgerFile.name}</p>
                        <p className="drop-zone-desc">{(ledgerFile.size / (1024 * 1024)).toFixed(2)} MB — will be reviewed before saving</p>
                      </div>
                    ) : (
                      <div>
                        <p className="drop-zone-title">Upload your own MIS List of Ledgers</p>
                        <p className="drop-zone-desc">Must contain a 'List of Ledgers' sheet with columns: Ledger Name, Group, Head, Classification, Vertical</p>
                      </div>
                    )}
                  </div>
                </div>
                {ledgerFile && (
                  <p style={{ margin: '0.5rem 0 0 0', fontSize: '0.78rem', color: 'var(--accent-gold)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <Edit2 size={12} /> You'll review and edit this list before it's saved permanently.
                  </p>
                )}
              </div>

              {/* Submit Trigger / Dual-action ledger choice */}
              {ledgerFile ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', background: 'rgba(255, 255, 255, 0.02)', padding: '1.25rem', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.06)', marginTop: '1.5rem' }} className="animate-fadeIn">
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: '0 0 0.5rem 0', fontWeight: '500', textAlign: 'left' }}>
                    Choose how to apply the custom List of Ledgers:
                  </p>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={handleLedgerDirectUpload}
                      style={{ padding: '0.875rem' }}
                    >
                      <CheckCircle size={16} /> Apply Directly
                    </button>
                    <button
                      type="submit"
                      className="btn-secondary"
                      style={{ padding: '0.875rem' }}
                    >
                      <Edit2 size={16} /> Review & Edit First
                    </button>
                  </div>
                </div>
              ) : (
                <button type="submit" className="btn-primary" style={{ width: '100%', padding: '1.1rem', marginTop: '1.5rem' }}>
                  Proceed to Mapping Check <ChevronRight size={18} />
                </button>
              )}
            </form>
          </div>

          {/* Workflow Guide Area */}
          <div className="glass-panel guide-card">
            <h3 className="guide-title">
              <HelpCircle size={20} style={{ color: 'var(--accent-emerald)' }} /> MIS Builder Pipeline
            </h3>
            <ul className="guide-list">
              <li className="guide-item">
                <span className="guide-num">1</span>
                <div className="guide-text">
                  <strong>Excel Upload & Audit</strong>
                  <p>The app analyzes the Trial Balance sheet structure and matches all account names against historical definitions.</p>
                </div>
              </li>
              <li className="guide-item">
                <span className="guide-num">2</span>
                <div className="guide-text">
                  <strong>Active Mapping Stop</strong>
                  <p>If a ledger in the imported trial balance is not present in the master mapping sheet, the pipeline stops and asks you to define its vertical and head.</p>
                </div>
              </li>
              <li className="guide-item">
                <span className="guide-num">3</span>
                <div className="guide-text">
                  <strong>YTD Roll-Forward</strong>
                  <p>Checks if the tally sheet has YTD data or else programmatically rolls forward YTD balances from your prior month upload.</p>
                </div>
              </li>
              <li className="guide-item">
                <span className="guide-num">4</span>
                <div className="guide-text">
                  <strong>Formula Intact Excel Clone</strong>
                  <p>A fresh month MIS report is cloned from the template. Dynamic Excel VLOOKUP and SUMIF formulas are maintained intact so excel calculations work perfectly.</p>
                </div>
              </li>
            </ul>
          </div>
        </div>
      )}

      {/* ==================== STAGE 1.5: LEDGER REVIEW ==================== */}
      {stage === 'LEDGER_REVIEW' && (
        <div className="glass-panel w-full animate-fadeIn">
          <div className="mapping-header">
            <div>
              <h2 className="mapping-title">
                <BookOpen size={22} style={{ color: 'var(--accent-gold)' }} /> Review List of Ledgers
              </h2>
              <p className="mapping-subtitle">
                Loaded <span style={{ color: 'var(--accent-gold)', fontWeight: '600' }}>{reviewLedgers.length} ledger entries</span> from your file.
                Edit any row below — then click <strong>Save &amp; Continue</strong> to permanently update the master template and proceed.
              </p>
            </div>
            <button
              onClick={() => { setLedgerFile(null); setReviewLedgers([]); setSuccessMessage(null); setStage('UPLOAD'); }}
              className="btn-secondary btn-sm"
            >
              Cancel &amp; Start Over
            </button>
          </div>

          <div className="table-container" style={{ maxHeight: '55vh', overflowY: 'auto' }}>
            <table className="mapping-table">
              <thead>
                <tr>
                  <th style={{ minWidth: '200px' }}>Ledger Name</th>
                  <th style={{ width: '200px' }}>Accounting Head</th>
                  <th style={{ width: '120px' }}>Group</th>
                  <th style={{ width: '220px' }}>Classification</th>
                  <th style={{ width: '180px' }}>Vertical</th>
                  <th style={{ width: '44px' }}></th>
                </tr>
              </thead>
              <tbody>
                {reviewLedgers.map((row, idx) => (
                  <tr key={idx}>
                    {/* Ledger Name — editable inline */}
                    <td>
                      <input
                        type="text"
                        className="form-input"
                        style={{ width: '100%', padding: '0.4rem 0.5rem', fontSize: '0.82rem', height: '34px' }}
                        value={row.ledger_name}
                        onChange={e => {
                          const updated = [...reviewLedgers];
                          updated[idx] = { ...updated[idx], ledger_name: e.target.value };
                          setReviewLedgers(updated);
                        }}
                      />
                    </td>
                    {/* Head dropdown */}
                    <td>
                      {renderCellDropdown(
                        `__review__${idx}`,
                        'head',
                        row.head,
                        domainLists.heads,
                        false
                      )}
                    </td>
                    {/* Group dropdown */}
                    <td>
                      {renderCellDropdown(
                        `__review__${idx}`,
                        'group',
                        row.group,
                        domainLists.groups,
                        false
                      )}
                    </td>
                    {/* Classification dropdown */}
                    <td>
                      {renderCellDropdown(
                        `__review__${idx}`,
                        'classification',
                        row.classification ?? '',
                        row.head === '1. Sales Accounts' ? ['Sales'] :
                        row.head === '5. Purchase Accounts' ? ['Purchase'] :
                        domainLists.classifications,
                        row.head === 'Sundry Debtor' || row.head === 'Sundry Creditor'
                      )}
                    </td>
                    {/* Vertical dropdown */}
                    <td>
                      {renderCellDropdown(
                        `__review__${idx}`,
                        'vertical',
                        row.vertical,
                        domainLists.verticals,
                        false
                      )}
                    </td>
                    {/* Delete row */}
                    <td style={{ textAlign: 'center' }}>
                      <button
                        type="button"
                        title="Remove this ledger"
                        onClick={() => setReviewLedgers(reviewLedgers.filter((_, i) => i !== idx))}
                        style={{
                          background: 'rgba(239,68,68,0.08)',
                          border: '1px solid rgba(239,68,68,0.2)',
                          borderRadius: '6px',
                          cursor: 'pointer',
                          color: '#ef4444',
                          padding: '0.3rem',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center'
                        }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Add new ledger row */}
          <div style={{ marginTop: '0.75rem' }}>
            <button
              type="button"
              className="btn-secondary"
              style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.5rem 1rem', fontSize: '0.85rem' }}
              onClick={() => setReviewLedgers([...reviewLedgers, {
                ledger_name: 'New Ledger',
                under: null,
                group: 'P&L',
                head: '6. Indirect Expense',
                classification: 'Misc Expenses',
                vertical: 'Common'
              }])}
            >
              <Plus size={14} /> Add New Ledger Row
            </button>
          </div>

          <button
            type="button"
            className="btn-primary"
            style={{ width: '100%', padding: '1.1rem', marginTop: '1.5rem' }}
            onClick={handleLedgerConfirm}
          >
            <CheckCircle size={18} /> Save Permanently &amp; Continue
          </button>
        </div>
      )}

      {/* ==================== STAGE 2: MAPPING UI ==================== */}
      {stage === 'MAPPING' && (
        <div className="glass-panel w-full animate-fadeIn">
          <div className="mapping-header">
            <div>
              <h2 className="mapping-title">
                <AlertTriangle size={24} style={{ color: 'var(--accent-gold)' }} /> Unmapped Ledgers Found
              </h2>
              <p className="mapping-subtitle">
                The trial balance contains <span style={{ color: 'var(--accent-gold)', fontWeight: '600' }}>{unmappedLedgers.length} new ledger accounts</span> that aren't defined in the master mapping database. Define them below to proceed.
              </p>
            </div>
            <button onClick={() => { setSuccessMessage(null); setStage('UPLOAD'); }} className="btn-secondary btn-sm">
              Cancel & Start Over
            </button>
          </div>

          <form onSubmit={handleMappingSubmit}>
            {/* Resolve mappings via Excel resolver */}
            <div style={{ background: 'rgba(245, 158, 11, 0.03)', border: '1px dashed rgba(245, 158, 11, 0.25)', borderRadius: '12px', padding: '1rem 1.5rem', marginBottom: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }} className="animate-fadeIn">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', textAlign: 'left' }}>
                  <div style={{ padding: '0.5rem', borderRadius: '8px', background: 'rgba(245, 158, 11, 0.1)', color: 'var(--accent-gold)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <BookOpen size={18} />
                  </div>
                  <div>
                    <span style={{ color: 'white', fontWeight: '600', fontSize: '0.85rem' }}>Bulk Resolve via Excel List</span>
                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', margin: 0 }}>
                      Drop a master ledger list Excel workbook to instantly auto-populate matches below.
                    </p>
                  </div>
                </div>
                <div style={{ position: 'relative' }}>
                  <button type="button" className="btn-secondary btn-sm" style={{ borderColor: 'rgba(234, 179, 8, 0.3)', pointerEvents: 'none' }}>
                    Choose Resolver File
                  </button>
                  <input
                    type="file"
                    accept=".xlsx,.xls"
                    onChange={handleResolverUpload}
                    style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%' }}
                  />
                </div>
              </div>
            </div>

            <div className="table-container">
              <table className="mapping-table">
                <thead>
                  <tr>
                    <th>New Ledger Account</th>
                    <th style={{ width: '220px' }}>Accounting Head</th>
                    <th style={{ width: '150px' }}>Group</th>
                    <th style={{ width: '240px' }}>Indirect Exp Classification</th>
                    <th style={{ width: '200px' }}>Business Vertical</th>
                  </tr>
                </thead>
                <tbody>
                  {unmappedLedgers.map((ledgerName) => {
                    const rowVal = mappings[ledgerName] || {
                      under: "Indirect Expenses",
                      group: "P&L",
                      head: "6. Indirect Expense",
                      classification: "Misc Expenses",
                      vertical: "Common"
                    };
                    
                    return (
                      <tr key={ledgerName}>
                        <td className="ledger-name-cell">{ledgerName}</td>
                        <td>
                          {renderCellDropdown(ledgerName, 'head', rowVal.head, domainLists.heads)}
                        </td>
                        <td>
                          {renderCellDropdown(ledgerName, 'group', rowVal.group, domainLists.groups)}
                        </td>
                        <td>
                          {renderCellDropdown(
                            ledgerName, 
                            'classification', 
                            rowVal.classification, 
                            rowVal.head === "1. Sales Accounts" ? ["Sales"] : 
                            rowVal.head === "5. Purchase Accounts" ? ["Purchase"] : 
                            domainLists.classifications, 
                            rowVal.head === "Sundry Debtor" || rowVal.head === "Sundry Creditor"
                          )}
                        </td>
                        <td>
                          {renderCellDropdown(ledgerName, 'vertical', rowVal.vertical, domainLists.verticals)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <button type="submit" className="btn-primary" style={{ width: '100%', padding: '1.1rem' }}>
              Approve Mappings & Build MIS <CheckCircle size={18} />
            </button>
          </form>
        </div>
      )}

      {/* ==================== STAGE 3: INTERACTIVE DASHBOARD ==================== */}
      {stage === 'DASHBOARD' && plData && (
        <div className="animate-fadeIn" style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
          {/* Tab Filter selectors */}
          <div className="filter-bar">
            <div className="tab-wrapper">
              <button 
                onClick={() => setActiveTab('MONTH')}
                className={`tab-btn ${activeTab === 'MONTH' ? 'active' : ''}`}
              >
                Monthly Review ({plData.month_label})
              </button>
              <button 
                onClick={() => setActiveTab('YTD')}
                className={`tab-btn ${activeTab === 'YTD' ? 'active' : ''}`}
              >
                YTD Review ({plData.ytd_label})
                {plData.has_ytd === false && (
                  <span style={{ fontSize: '0.75rem', opacity: 0.7, marginLeft: '6px', padding: '2px 6px', background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444', borderRadius: '4px', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
                    Not Found
                  </span>
                )}
              </button>
            </div>
            <div className="live-badge">
              <span className="pulse-dot"></span>
              All formulas recalculated in browser
            </div>
          </div>

          {activeTab === 'YTD' && plData.has_ytd === false ? (
            <div className="glass-panel animate-fadeIn" style={{ padding: '3.5rem 2rem', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1.25rem', border: '1px dashed rgba(255,255,255,0.1)' }}>
              <div style={{ background: 'rgba(234, 179, 8, 0.1)', padding: '1rem', borderRadius: '50%', color: 'var(--accent-gold)' }}>
                <AlertTriangle size={40} />
              </div>
              <h3 style={{ fontSize: '1.4rem', fontWeight: '600', color: 'white', margin: 0 }}>Year-to-Date (YTD) Data Not Available</h3>
              <p style={{ color: 'var(--text-secondary)', maxWidth: '520px', fontSize: '0.95rem', lineHeight: '1.6', margin: 0 }}>
                We could not find cumulative Year-to-Date (YTD) columns in the uploaded Trial Balance, and no previous month's MIS report was provided for automatic roll-forward calculations.
              </p>
              
              <div style={{ textAlign: 'left', background: 'rgba(255,255,255,0.015)', padding: '1.5rem', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.06)', maxWidth: '540px', width: '100%', boxSizing: 'border-box' }}>
                <p style={{ margin: '0 0 0.75rem 0', color: 'white', fontSize: '0.9rem' }}>
                  <strong>To enable YTD insights, you can:</strong>
                </p>
                <ul style={{ margin: 0, paddingLeft: '1.2rem', color: 'var(--text-secondary)', fontSize: '0.85rem', display: 'flex', flexDirection: 'column', gap: '0.6rem', lineHeight: '1.5' }}>
                  <li>
                    <strong style={{ color: '#fff' }}>Provide Prior Month MIS Report:</strong> Drag and drop the previous month's final excel report as the optional <em>"Prior Month Workbook"</em> in the upload screen.
                  </li>
                  <li>
                    <strong style={{ color: '#fff' }}>Use YTD Tally Prime Export:</strong> Ensure your exported Tally Trial Balance includes both the current month and the cumulative YTD columns.
                  </li>
                </ul>
              </div>

              <button 
                onClick={() => {
                  setActiveFile(null);
                  setPriorFile(null);
                  setStage('UPLOAD');
                }} 
                className="btn-secondary"
                style={{ marginTop: '0.75rem', padding: '0.6rem 1.2rem' }}
              >
                <RefreshCw size={14} style={{ marginRight: '0.4rem' }} /> Go Back & Re-Upload
              </button>
            </div>
          ) : (
            <>
              {/* KPI Dashboard Grid */}
              <div className="kpi-grid">
                <div className="glass-panel kpi-card">
                  <div>
                    <p className="kpi-title">Net Sales Revenue</p>
                    <h3 className="kpi-val">
                      {formatCurrency(activeTab === 'MONTH' ? plData.kpis.monthly_revenue : plData.kpis.ytd_revenue)}
                    </h3>
                    <span className="kpi-footer emerald">
                      <TrendingUp size={14} /> Operational sales
                    </span>
                  </div>
                  <div className="kpi-icon-wrapper emerald">
                    <DollarSign size={24} />
                  </div>
                </div>

                <div className="glass-panel kpi-card">
                  <div>
                    <p className="kpi-title">Gross Margin %</p>
                    <h3 className="kpi-val">
                      {((activeTab === 'MONTH' ? plData.kpis.monthly_gross_margin_pct : plData.kpis.ytd_gross_margin_pct) * 100).toFixed(1)}%
                    </h3>
                    <span className="kpi-footer teal">
                      <TrendingUp size={14} /> High performance
                    </span>
                  </div>
                  <div className="kpi-icon-wrapper teal">
                    <ArrowUpRight size={24} />
                  </div>
                </div>

                <div className="glass-panel kpi-card">
                  <div>
                    <p className="kpi-title">Profit before Tax</p>
                    <h3 className="kpi-val" style={{ color: (activeTab === 'MONTH' ? plData.kpis.monthly_net_income : plData.kpis.ytd_net_income) >= 0 ? 'var(--accent-emerald)' : 'var(--accent-red)' }}>
                      {formatCurrency(activeTab === 'MONTH' ? plData.kpis.monthly_net_income : plData.kpis.ytd_net_income)}
                    </h3>
                    <span className="kpi-footer muted">Net monthly margin</span>
                  </div>
                  <div className="kpi-icon-wrapper indigo">
                    <BarChart2 size={24} />
                  </div>
                </div>

                <div className="glass-panel kpi-card">
                  <div>
                    <p className="kpi-title">Indirect Costs</p>
                    <h3 className="kpi-val">
                      {formatCurrency(activeTab === 'MONTH' ? plData.kpis.monthly_expenses : plData.kpis.ytd_expenses)}
                    </h3>
                    <span className="kpi-footer muted">Allocations applied</span>
                  </div>
                  <div className="kpi-icon-wrapper amber">
                    <PieChart size={24} />
                  </div>
                </div>
              </div>

              {/* Revenue & Margin Contribution by Vertical — grouped BarChart */}
              <div className="glass-panel chart-card">
                <h3 className="chart-title">
                  <BarChart2 size={20} style={{ color: 'var(--accent-emerald)' }} /> Revenue &amp; Margin Contribution by Vertical
                </h3>
                <div style={{ height: '320px', width: '100%' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={getChartData()} margin={{ top: 10, right: 30, left: 20, bottom: 0 }} barCategoryGap="30%" barGap={4}>
                      <XAxis dataKey="name" stroke="#6b7280" fontSize={11} tickLine={false} />
                      <YAxis
                        stroke="#6b7280"
                        fontSize={11}
                        tickLine={false}
                        tickFormatter={(v: number) => `₹${(v / 100000).toFixed(0)}L`}
                      />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#0b1329', borderColor: 'rgba(255,255,255,0.08)', borderRadius: '12px' }}
                        labelStyle={{ color: '#fff', fontWeight: 'bold' }}
                        itemStyle={{ color: '#ccc' }}
                        formatter={(value: number, name: string) => [
                          `₹${(value / 100000).toFixed(2)}L`,
                          name
                        ]}
                      />
                      <Legend />
                      <ReferenceLine y={0} stroke="rgba(255,255,255,0.15)" strokeDasharray="4 3" />
                      <Bar dataKey="Revenue" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={48} />
                      <Bar dataKey="Gross Margin" fill="#3b82f6" radius={[4, 4, 0, 0]} maxBarSize={48} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Premium Multi-Column P&L Table */}
              <div className="glass-panel statement-card">
                <div className="statement-header">
                  <h3 className="statement-title">Statement of Profit & Loss</h3>
                  <p className="statement-subtitle">Detailed cost-center allocation for operating and support verticals</p>
                </div>

                <div className="statement-table-wrapper">
                  <table className="statement-table">
                    <thead>
                      <tr>
                        <th className="particulars-col">Accounting Particulars</th>
                        {(activeTab === 'MONTH' ? plData.month_data : plData.ytd_data).columns.map((colName) => (
                          <th key={colName}>{colName}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(activeTab === 'MONTH' ? plData.month_data : plData.ytd_data).rows.map((row, idx) => {
                        // Header row formatting
                        if (row.is_header) {
                          return (
                            <tr key={idx} className="row-header">
                              <td className="particulars-col">{row.particulars}</td>
                              {Object.values(row.values).map((_, cIdx) => (
                                <td key={cIdx}></td>
                              ))}
                            </tr>
                          );
                        }
                        
                        // Allocation section label row
                        if (row.particulars === 'Allocation of expenses:') {
                          return (
                            <tr key={idx} style={{ fontStyle: 'italic', background: 'rgba(255,255,255,0.02)' }}>
                              <td className="particulars-col" style={{ color: 'var(--text-secondary)' }}>{row.particulars}</td>
                              {Object.values(row.values).map((_, cIdx) => (
                                <td key={cIdx}></td>
                              ))}
                            </tr>
                          );
                        }

                        const isTotalRow = row.is_total;
                        const isPercentage = row.particulars.toLowerCase().includes('%');

                        return (
                          <tr key={idx} className={isTotalRow ? 'row-total' : ''}>
                            <td className="particulars-col">{row.particulars}</td>
                            {(activeTab === 'MONTH' ? plData.month_data : plData.ytd_data).columns.map((colName) => {
                              const val = row.values[colName];
                              return (
                                <td 
                                  key={colName} 
                                  className={getValueColor(val, row.particulars)}
                                >
                                  {val === null || val === undefined ? "-" : (
                                    isPercentage ? `${(val * 100).toFixed(1)}%` : formatCurrency(val)
                                  )}
                                </td>
                              );
                            })}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Dynamic Debtors & Creditors Pivot Table */}
              {plData.debtors_creditors_pivot && (
                <div className="glass-panel statement-card animate-fadeIn" style={{ marginTop: '2rem' }}>
                  <div className="statement-header">
                    <h3 className="statement-title">Sundry Debtors &amp; Creditors Pivot</h3>
                    <p className="statement-subtitle">Automated vertical-wise breakdown of accounts receivable and payable</p>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '2rem', marginTop: '1.5rem' }}>
                    {/* Debtors Summary */}
                    <div>
                      <h4 style={{ color: 'var(--accent-emerald)', fontSize: '1rem', fontWeight: '600', margin: '0 0 0.75rem 0', display: 'flex', alignItems: 'center', gap: '0.5rem', textAlign: 'left' }}>
                        <TrendingUp size={16} /> Sundry Debtors
                      </h4>
                      <div className="statement-table-wrapper">
                        <table className="statement-table">
                          <thead>
                            <tr>
                              <th className="particulars-col">Business Vertical</th>
                              <th>Opening</th>
                              <th>Debit</th>
                              <th>Credit</th>
                              <th>Closing</th>
                            </tr>
                          </thead>
                          <tbody>
                            {plData.debtors_creditors_pivot.debtors.length === 0 ? (
                              <tr>
                                <td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>No Sundry Debtor balances found</td>
                              </tr>
                            ) : (
                              <>
                                {plData.debtors_creditors_pivot.debtors.map((row) => (
                                  <tr key={row.vertical}>
                                    <td className="particulars-col" style={{ fontWeight: '500' }}>{row.vertical}</td>
                                    <td>{formatCurrency(activeTab === 'MONTH' ? row.opening : row.opening_ytd)}</td>
                                    <td style={{ color: 'var(--accent-emerald)' }}>{formatCurrency(activeTab === 'MONTH' ? row.debit : row.debit_ytd)}</td>
                                    <td style={{ color: 'var(--accent-red)' }}>{formatCurrency(activeTab === 'MONTH' ? row.credit : row.credit_ytd)}</td>
                                    <td style={{ fontWeight: '600' }}>{formatCurrency(activeTab === 'MONTH' ? row.closing : row.closing_ytd)}</td>
                                  </tr>
                                ))}
                                {/* Grand Total for Debtors */}
                                <tr className="row-total">
                                  <td className="particulars-col">Grand Total</td>
                                  <td>{formatCurrency(plData.debtors_creditors_pivot.debtors.reduce((sum, r) => sum + (activeTab === 'MONTH' ? r.opening : r.opening_ytd), 0))}</td>
                                  <td style={{ color: 'var(--accent-emerald)' }}>{formatCurrency(plData.debtors_creditors_pivot.debtors.reduce((sum, r) => sum + (activeTab === 'MONTH' ? r.debit : r.debit_ytd), 0))}</td>
                                  <td style={{ color: 'var(--accent-red)' }}>{formatCurrency(plData.debtors_creditors_pivot.debtors.reduce((sum, r) => sum + (activeTab === 'MONTH' ? r.credit : r.credit_ytd), 0))}</td>
                                  <td style={{ fontWeight: '600' }}>{formatCurrency(plData.debtors_creditors_pivot.debtors.reduce((sum, r) => sum + (activeTab === 'MONTH' ? r.closing : r.closing_ytd), 0))}</td>
                                </tr>
                              </>
                            )}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    {/* Creditors Summary */}
                    <div>
                      <h4 style={{ color: 'var(--accent-red)', fontSize: '1rem', fontWeight: '600', margin: '0 0 0.75rem 0', display: 'flex', alignItems: 'center', gap: '0.5rem', textAlign: 'left' }}>
                        <TrendingDown size={16} /> Sundry Creditors
                      </h4>
                      <div className="statement-table-wrapper">
                        <table className="statement-table">
                          <thead>
                            <tr>
                              <th className="particulars-col">Business Vertical</th>
                              <th>Opening</th>
                              <th>Debit</th>
                              <th>Credit</th>
                              <th>Closing</th>
                            </tr>
                          </thead>
                          <tbody>
                            {plData.debtors_creditors_pivot.creditors.length === 0 ? (
                              <tr>
                                <td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>No Sundry Creditor balances found</td>
                              </tr>
                            ) : (
                              <>
                                {plData.debtors_creditors_pivot.creditors.map((row) => (
                                  <tr key={row.vertical}>
                                    <td className="particulars-col" style={{ fontWeight: '500' }}>{row.vertical}</td>
                                    <td>{formatCurrency(activeTab === 'MONTH' ? row.opening : row.opening_ytd)}</td>
                                    <td style={{ color: 'var(--accent-emerald)' }}>{formatCurrency(activeTab === 'MONTH' ? row.debit : row.debit_ytd)}</td>
                                    <td style={{ color: 'var(--accent-red)' }}>{formatCurrency(activeTab === 'MONTH' ? row.credit : row.credit_ytd)}</td>
                                    <td style={{ fontWeight: '600' }}>{formatCurrency(activeTab === 'MONTH' ? row.closing : row.closing_ytd)}</td>
                                  </tr>
                                ))}
                                {/* Grand Total for Creditors */}
                                <tr className="row-total">
                                  <td className="particulars-col">Grand Total</td>
                                  <td>{formatCurrency(plData.debtors_creditors_pivot.creditors.reduce((sum, r) => sum + (activeTab === 'MONTH' ? r.opening : r.opening_ytd), 0))}</td>
                                  <td style={{ color: 'var(--accent-emerald)' }}>{formatCurrency(plData.debtors_creditors_pivot.creditors.reduce((sum, r) => sum + (activeTab === 'MONTH' ? r.debit : r.debit_ytd), 0))}</td>
                                  <td style={{ color: 'var(--accent-red)' }}>{formatCurrency(plData.debtors_creditors_pivot.creditors.reduce((sum, r) => sum + (activeTab === 'MONTH' ? r.credit : r.credit_ytd), 0))}</td>
                                  <td style={{ fontWeight: '600' }}>{formatCurrency(plData.debtors_creditors_pivot.creditors.reduce((sum, r) => sum + (activeTab === 'MONTH' ? r.closing : r.closing_ytd), 0))}</td>
                                </tr>
                              </>
                            )}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
