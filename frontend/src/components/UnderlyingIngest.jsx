/**
 * UnderlyingIngest.jsx — Identifier entry + CSV upload panel for the Underlying module.
 *
 * Props:
 *   onJobStarted(jobId) — called immediately when a job is queued (switch to list tab, etc.)
 *   onJobDone(jobId)    — called when the background job reaches done/error status
 */
import { useState, useEffect, useRef } from 'react'
import { api } from '../api.js'
import StatusBadge from './StatusBadge.jsx'

// ---------------------------------------------------------------------------
// Job status card
// ---------------------------------------------------------------------------

function JobCard({ jobId, onDone }) {
  const [job,       setJob]       = useState(null)
  const [pollError, setPollError] = useState(null)
  const timerRef    = useRef(null)
  const failRef     = useRef(0)   // consecutive poll failures

  useEffect(() => {
    if (!jobId) return
    const poll = async () => {
      try {
        const j = await api.underlyingJobStatus(jobId)
        setJob(j)
        failRef.current = 0
        if (j.status === 'done' || j.status === 'error') {
          clearInterval(timerRef.current)
          if (onDone) onDone()
        }
      } catch {
        failRef.current += 1
        // Surface an error after 3 consecutive failures so the card doesn't
        // stay stuck on "Starting job…" when the backend is unreachable.
        if (failRef.current >= 3) {
          clearInterval(timerRef.current)
          setPollError('Job status unavailable — check your connection and retry.')
        }
      }
    }
    poll()
    timerRef.current = setInterval(poll, 3000)
    return () => clearInterval(timerRef.current)
  }, [jobId])

  if (!job && !pollError) return (
    <div className="bg-blue-50 border border-blue-200 rounded p-3 text-xs text-blue-700 animate-pulse">
      Starting job…
    </div>
  )

  if (pollError) return (
    <div className="bg-red-50 border border-red-200 rounded p-3 text-xs text-red-700">
      {pollError}
    </div>
  )

  const pct = job.total > 0 ? Math.round((job.done / job.total) * 100) : 0

  return (
    <div className="bg-white border border-slate-200 rounded p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-700">Ingest Job</span>
        <StatusBadge status={job.status} small />
      </div>
      {/* Progress bar */}
      <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-lpa-cyan rounded-full transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between text-xs text-slate-500">
        <span>{job.done} / {job.total} processed</span>
        <span className="space-x-2">
          {job.success > 0 && <span className="text-green-600">✓ {job.success} ok</span>}
          {job.errors > 0  && <span className="text-red-600">✗ {job.errors} err</span>}
        </span>
      </div>
      {/* Per-item results */}
      {Array.isArray(job.results) && job.results.length > 0 && (
        <div className="mt-1 max-h-28 overflow-y-auto scrollbar-thin space-y-0.5">
          {job.results.map((r, i) => (
            <div key={i} className={`text-xs px-2 py-0.5 rounded ${r.error ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
              <span className="font-mono">{r.identifier}</span>
              {r.error && <span className="ml-1 opacity-75">— {r.error}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function UnderlyingIngest({ onJobStarted, onJobDone }) {
  const [identifiers, setIdentifiers] = useState('')
  const [fetchMarket, setFetchMarket] = useState(true)
  const [runLlm,      setRunLlm]      = useState(true)
  const [submitting,  setSubmitting]  = useState(false)
  const [jobId,       setJobId]       = useState(null)
  const [csvFile,     setCsvFile]     = useState(null)
  const [csvName,     setCsvName]     = useState('')
  const [error,       setError]       = useState('')
  const fileInputRef = useRef(null)

  const startJob = (result) => {
    setJobId(result.job_id)
    setError('')
    if (onJobStarted) onJobStarted(result.job_id)
  }

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
      startJob(result)
      setIdentifiers('')
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
      startJob(result)
      setCsvFile(null)
      setCsvName('')
      if (fileInputRef.current) fileInputRef.current.value = ''
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

      {/* ── Job status ────────────────────────────────────────────────────── */}
      {jobId && (
        <JobCard
          key={jobId}
          jobId={jobId}
          onDone={onJobDone}
        />
      )}

      {/* ── Error ─────────────────────────────────────────────────────────── */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-xs text-red-700">
          {error}
        </div>
      )}
    </div>
  )
}
