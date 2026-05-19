import React, { useState, useEffect } from 'react';
import { 
  Upload, FileText, ChevronRight, Download, RefreshCw, BarChart2, 
  PieChart, CheckCircle, AlertTriangle, ArrowUpRight, DollarSign, 
  TrendingUp, Layers, HelpCircle
} from 'lucide-react';
import { 
  ResponsiveContainer, XAxis, YAxis, Tooltip, Legend, AreaChart, Area
} from 'recharts';

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

interface PLDataResponse {
  month_label: string;
  ytd_label: string;
  month_data: PLBreakdown;
  ytd_data: PLBreakdown;
  kpis: Record<string, number>;
  has_ytd?: boolean;
}

interface DomainLists {
  groups: string[];
  heads: string[];
  verticals: string[];
  classifications: string[];
}

export default function App() {
  // App Workflow Stages: 'UPLOAD' | 'MAPPING' | 'DASHBOARD'
  const [stage, setStage] = useState<'UPLOAD' | 'MAPPING' | 'DASHBOARD'>('UPLOAD');
  
  // Data States
  const [activeFile, setActiveFile] = useState<File | null>(null);
  const [priorFile, setPriorFile] = useState<File | null>(null);
  const [month, setMonth] = useState<number>(3); // March
  const [year, setYear] = useState<number>(2026);
  
  // Loading & Error States
  const [loading, setLoading] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  
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
            setCustomMode({
              ...customMode,
              [modeKey]: true
            });
            setCustomValues({
              ...customValues,
              [modeKey]: ""
            });
          } else {
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
              setMappings({
                ...mappings,
                [ledgerName]: {
                  ...rowVal,
                  [columnKey]: val
                }
              });
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

  // Fetch domain dropdown options on load
  useEffect(() => {
    fetch(`${API_BASE}/domain-lists`)
      .then(res => res.json())
      .then(data => setDomainLists(data))
      .catch(err => console.error("Failed to load domains:", err));
  }, []);

  // Handle Monthly File Upload
  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeFile) {
      setError("Please select the active monthly Trial Balance file.");
      return;
    }
    
    setError(null);
    setLoading(true);
    setStatusMessage("Uploading and parsing Trial Balance data...");
    
    const formData = new FormData();
    formData.append("file", activeFile);
    if (priorFile) {
      formData.append("prior_file", priorFile);
    }
    formData.append("month", month.toString());
    formData.append("year", year.toString());
    
    try {
      const res = await fetch(`${API_BASE}/upload`, {
        method: "POST",
        body: formData,
      });
      
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Upload pipeline failed.");
      }
      
      setSessionId(data.session_id);
      
      if (data.success === false) {
        // Unmapped ledgers detected! Redirect to mapping form
        setUnmappedLedgers(data.unmapped_ledgers);
        
        // Initialize default mappings for the unmapped ledgers
        const initialMappings: typeof mappings = {};
        data.unmapped_ledgers.forEach((name: string) => {
          initialMappings[name] = {
            under: "Indirect Expenses",
            group: "P&L",
            head: "6. Indirect Expense",
            classification: "Misc Expenses",
            vertical: "Common"
          };
        });
        setMappings(initialMappings);
        setStage('MAPPING');
      } else {
        // Perfect import, go straight to dashboard!
        setPlData(data.pl_data);
        setStage('DASHBOARD');
      }
    } catch (err: any) {
      setError(err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  };

  // Submit Mappings form to backend
  const handleMappingSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setStatusMessage("Saving mapping classifications and writing generated Excel report...");
    setError(null);
    
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
    
    try {
      const res = await fetch(`${API_BASE}/map`, {
        method: "POST",
        body: formData
      });
      
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Failed to submit mappings.");
      }
      
      setPlData(data.pl_data);
      setStage('DASHBOARD');
    } catch (err: any) {
      setError(err.message || "Failed to apply mappings.");
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

  // Prepare chart data for Recharts
  const getChartData = () => {
    if (!plData) return [];
    const sourceData = activeTab === 'MONTH' ? plData.month_data : plData.ytd_data;
    
    // Find Sales and Gross Profit rows
    const salesRow = sourceData.rows.find(r => r.particulars === 'Sales');
    const marginRow = sourceData.rows.find(r => r.particulars === 'Gross margin');
    
    const chartVerticals = ['Bluestreak', 'Clarus', 'IT', 'Spices - A to Z', 'Spices - Vashi'];
    
    return chartVerticals.map(v => ({
      name: v,
      Revenue: salesRow ? Math.max(0, salesRow.values[v] || 0) : 0,
      "Gross Margin": marginRow ? Math.max(0, marginRow.values[v] || 0) : 0,
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

      {/* Error Banner */}
      {error && (
        <div className="error-banner">
          <AlertTriangle className="error-icon" size={20} style={{ color: 'var(--accent-red)', flexShrink: 0 }} />
          <div>
            <h4 className="error-title">Pipeline Error</h4>
            <p className="error-desc">{error}</p>
          </div>
        </div>
      )}

      {/* Global Processing Loader Panel */}
      {loading && (
        <div className="loader-overlay">
          <div className="spinner">
            <Layers className="spinner-icon" />
          </div>
          <h3 className="loader-title">{statusMessage}</h3>
          <p className="loader-desc">Processing large Excel formulas and computing financials...</p>
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
              <div className="form-row" style={{ marginBottom: '1.5rem' }}>
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
              <div className="form-group" style={{ marginBottom: '2rem' }}>
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

              {/* Submit Trigger */}
              <button type="submit" className="btn-primary" style={{ width: '100%', padding: '1.1rem' }}>
                Proceed to Mapping Check <ChevronRight size={18} />
              </button>
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
            <button onClick={() => setStage('UPLOAD')} className="btn-secondary btn-sm">
              Cancel & Start Over
            </button>
          </div>

          <form onSubmit={handleMappingSubmit}>
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

              {/* Revenue Breakdown Chart */}
              <div className="glass-panel chart-card">
                <h3 className="chart-title">
                  <BarChart2 size={20} style={{ color: 'var(--accent-emerald)' }} /> Revenue & Margin Contribution by Vertical
                </h3>
                <div style={{ height: '320px', width: '100%' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={getChartData()} margin={{ top: 10, right: 30, left: 20, bottom: 0 }}>
                      <defs>
                        <linearGradient id="colorRev" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#10b981" stopOpacity={0.4}/>
                          <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                        </linearGradient>
                        <linearGradient id="colorGP" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4}/>
                          <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="name" stroke="#6b7280" fontSize={11} tickLine={false} />
                      <YAxis stroke="#6b7280" fontSize={11} tickLine={false} tickFormatter={(v) => `₹${(v / 100000).toFixed(0)}L`} />
                      <Tooltip 
                        contentStyle={{ backgroundColor: '#0b1329', borderColor: 'rgba(255,255,255,0.08)', borderRadius: '12px' }}
                        labelStyle={{ color: '#fff', fontWeight: 'bold' }}
                        itemStyle={{ color: '#ccc' }}
                      />
                      <Legend />
                      <Area type="monotone" dataKey="Revenue" stroke="#10b981" fillOpacity={1} fill="url(#colorRev)" strokeWidth={2} />
                      <Area type="monotone" dataKey="Gross Margin" stroke="#3b82f6" fillOpacity={1} fill="url(#colorGP)" strokeWidth={2} />
                    </AreaChart>
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
            </>
          )}
        </div>
      )}
    </div>
  );
}
