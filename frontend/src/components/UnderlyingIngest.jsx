/**
 * UnderlyingIngest.jsx — Identifier entry + CSV upload form for the Underlying module.
 *
 * This component is a pure submission form.  Job progress tracking is handled
 * by the parent (UnderlyingPanel) via the JobBanner component, which persists
 * across tab switches and shows live progress + per-item results.
 *
 * Props:
 *   onJobStarted(jobId) — called with the job UUID immediately after the API
 *                         accepts the request; the parent uses this to start
 *                         displaying the JobBanner.
 */
import { useState, useRef } from 'react'
import { api } from '../api.js'

export default function UnderlyingIngest({ onJobStarted }) {
  const [identifiers, setIdentifiers] = useState('')
  const [fetchMarket, setFetchMarket] = useState(true)
  const [runLlm,      setRunLlm]      = useState(true)
  const [submitting,  setSubmitting]  = useState(false)
  const [csvFile,     setCsvFile]     = useState(null)
  const [csvName,     setCsvName]     = useState('')
  const [error,       setError]       = useState('')
  const fileInputRef = useRef(null)

  // ── Manual identifier entry ────────────────────────────────────────────────

  const doIngest = async () => {
    const ids = identifiers
      .split(/[\n,]+/)
      .map(s => s.trim())
      .filter(Boolean)
    if (!ids.length) { setError('Enter at least one identifier'); return }
    setSubmitting(true)
    setError('')
    try {
      const result = await api.underlyingIngest({
        identifiers: ids,
        fetch_market: fetchMarket,
        run_llm: runLlm,
      })
      setIdentifiers('')        // reset form — progress tracked by parent banner
      if (onJobStarted) onJobStarted(result.job_id)
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  // ── CSV upload ─────────────────────────────────────────────────────────────

  const doCsvIngest = async () => {
    if (!csvFile) return
    setSubmitting(true)
    setError('')
    try {
      const result = await api.underlyingIngestCsv(csvFile)
      setCsvFile(null)
      setCsvName('')
      if (fileInputRef.current) fileInputRef.current.value = ''
      if (onJobStarted) onJobStarted(result.job_id)
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  const onFileChange = (e) => {
    const f = e.target.files?.[0]
    if (f) { setCsvFile(f); setCsvName(f.name) }
  }

  return (
    <div className="p-4 space-y-4">

      {/* ── Manual entry ────────────────────────────────────────────────── */}
      <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1.5">
          <span>🔍</span> Enter Identifiers
        </h3>
        <div className="space-y-2">
          <textarea
            rows={4}
            className="w-full border border-slate-200 rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-lpa-cyan resize-none"
            placeholder={"One per line or comma-separated:\nMSFT\nAAPL, GOOGL\nCIK0000789019"}
            value={identifiers}
            onChange={e => setIdentifiers(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) doIngest() }}
          />

          {/* Options */}
          <div className="flex flex-wrap gap-4 text-xs text-slate-600">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={fetchMarket} onChange={e => setFetchMarket(e.target.checked)}
                className="rounded border-slate-300" />
              Fetch market data
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={runLlm} onChange={e => setRunLlm(e.target.checked)}
                className="rounded border-slate-300" />
              Run LLM extraction
            </label>
          </div>

          <button
            onClick={doIngest}
            disabled={!identifiers.trim() || submitting}
            className="w-full bg-lpa-blue hover:bg-[#0c2fd4] disabled:bg-slate-300 text-white text-sm font-medium rounded px-3 py-1.5 transition-colors"
          >
            {submitting ? 'Starting…' : 'Ingest (Ctrl+Enter)'}
          </button>
        </div>
      </div>

      {/* ── CSV upload ────────────────────────────────────────────────────── */}
      <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1.5">
          <span>📄</span> CSV Upload
        </h3>
        <p className="text-xs text-slate-500 mb-2">
          CSV must have an <code className="bg-slate-100 px-1 rounded">identifier</code> column header. Other columns are ignored.
        </p>
        <div className="space-y-2">
          <div
            className="border-2 border-dashed border-slate-200 rounded p-4 text-center cursor-pointer hover:border-lpa-cyan hover:bg-slate-50 transition-colors"
            onClick={() => fileInputRef.current?.click()}
          >
            {csvName
              ? <span className="text-xs text-slate-700 font-medium">{csvName}</span>
              : <span className="text-xs text-slate-400">Click to choose a .csv file</span>
            }
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={onFileChange}
          />
          <button
            onClick={doCsvIngest}
            disabled={!csvFile || submitting}
            className="w-full bg-slate-700 hover:bg-slate-800 disabled:bg-slate-300 text-white text-sm font-medium rounded px-3 py-1.5 transition-colors"
          >
            {submitting ? 'Uploading…' : 'Upload & Ingest'}
          </button>
        </div>
      </div>

      {/* ── Submission error ──────────────────────────────────────────────── */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-xs text-red-700">
          {error}
        </div>
      )}

    </div>
  )
}
