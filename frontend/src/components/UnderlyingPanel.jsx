/**
 * UnderlyingPanel.jsx — Left sidebar for the Underlying Securities view.
 *
 * Contains two tabs:
 *   - "Securities"  : paginated, filterable list of UnderlyingSecurity rows.
 *   - "Ingest"      : UnderlyingIngest form.
 *
 * A persistent JobBanner is rendered between the panel header and the tab bar
 * whenever an ingest job is running or has just completed.  It stays visible
 * across tab switches so the user always sees progress and results.
 *
 * Props:
 *   selectedId      string | null  — currently selected security ID
 *   onSelect(id)                   — callback when user clicks a row
 *   refreshKey      number         — increment from the parent (App) to force a list refresh
 *                                    e.g. after approve/archive from the detail panel (B2)
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api.js'
import StatusBadge from './StatusBadge.jsx'
import UnderlyingIngest from './UnderlyingIngest.jsx'

const PAGE_SIZE = 50

const STATUSES = [
  '',
  'fetching', 'fetched', 'needs_review', 'approved', 'archived',
]

// ---------------------------------------------------------------------------
// JobBanner — persistent job progress / results strip
// ---------------------------------------------------------------------------

/**
 * Polls one ingest job and renders a compact status banner.
 *
 * Visible on both the Securities and Ingest tabs so the user always has
 * feedback regardless of which tab they are looking at.
 *
 * Props:
 *   jobId      string   — job UUID to poll
 *   onComplete ()       — called once when job reaches done/error (refresh list)
 *   onDismiss  ()       — called when the user clicks ✕ (clears the banner)
 */
function JobBanner({ jobId, onComplete, onDismiss }) {
  const [job,       setJob]       = useState(null)
  const [expanded,  setExpanded]  = useState(false)
  const [pollError, setPollError] = useState(null)
  const timerRef  = useRef(null)
  const failRef   = useRef(0)
  const notifiedRef = useRef(false)   // fire onComplete exactly once

  useEffect(() => {
    if (!jobId) return
    const poll = async () => {
      try {
        const j = await api.underlyingJobStatus(jobId)
        setJob(j)
        failRef.current = 0
        if ((j.status === 'done' || j.status === 'error') && !notifiedRef.current) {
          notifiedRef.current = true
          clearInterval(timerRef.current)
          if (onComplete) onComplete()
          // Auto-expand when done so results are immediately visible
          setExpanded(true)
        }
      } catch {
        failRef.current += 1
        if (failRef.current >= 3) {
          clearInterval(timerRef.current)
          setPollError('Job status unavailable — check your connection.')
        }
      }
    }
    poll()
    timerRef.current = setInterval(poll, 3000)
    return () => clearInterval(timerRef.current)
  }, [jobId])

  if (pollError) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-red-50 border-b border-red-200 shrink-0">
        <span className="text-xs text-red-600 flex-1">{pollError}</span>
        <button onClick={onDismiss} className="text-red-400 hover:text-red-600 text-xs">✕</button>
      </div>
    )
  }

  const isDone     = job?.status === 'done' || job?.status === 'error'
  const pct        = (job?.total ?? 0) > 0 ? Math.round((job.done / job.total) * 100) : 0
  const results    = Array.isArray(job?.results) ? job.results : []
  const errors     = results.filter(r => r.error)
  const successes  = results.filter(r => !r.error)
  const hasResults = results.length > 0

  return (
    <div className="border-b border-slate-200 bg-slate-50 shrink-0">
      {/* ── Summary row ───────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2">
        {/* Status icon */}
        {!job ? (
          <span className="text-blue-400 text-xs animate-pulse">●</span>
        ) : !isDone ? (
          <span className="text-blue-500 text-xs animate-spin inline-block">↻</span>
        ) : errors.length > 0 ? (
          <span className="text-amber-500 text-xs">⚠</span>
        ) : (
          <span className="text-green-500 text-xs">✓</span>
        )}

        {/* Label */}
        <span className="text-xs text-slate-700 flex-1 min-w-0 truncate">
          {!job
            ? 'Starting job…'
            : isDone
              ? `Done — ${successes.length} found${errors.length > 0 ? `, ${errors.length} failed` : ''}`
              : `Ingesting ${job.done ?? 0} / ${job.total ?? '…'}`
          }
        </span>

        {/* Count badges */}
        {job && (
          <span className="flex gap-1.5 text-[10px] font-semibold shrink-0">
            {successes.length > 0 && (
              <span className="text-green-600">✓{successes.length}</span>
            )}
            {errors.length > 0 && (
              <span className="text-red-600">✗{errors.length}</span>
            )}
          </span>
        )}

        {/* Expand toggle (only when there are results) */}
        {hasResults && (
          <button
            onClick={() => setExpanded(v => !v)}
            className="text-slate-400 hover:text-slate-600 text-[10px] leading-none px-0.5"
            title={expanded ? 'Collapse results' : 'Show results'}
          >
            {expanded ? '▴' : '▾'}
          </button>
        )}

        {/* Dismiss — available once done */}
        {isDone && (
          <button
            onClick={onDismiss}
            className="text-slate-400 hover:text-slate-600 text-xs leading-none ml-0.5"
            title="Dismiss"
          >
            ✕
          </button>
        )}
      </div>

      {/* ── Progress bar (while running) ──────────────────────────────── */}
      {!isDone && job && (
        <div className="px-3 pb-2">
          <div className="h-1 bg-slate-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}

      {/* ── Expanded results ──────────────────────────────────────────── */}
      {expanded && hasResults && (
        <div className="px-3 pb-2 max-h-44 overflow-y-auto scrollbar-thin space-y-1">
          {errors.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-red-600 uppercase tracking-wide mb-0.5">
                Not found ({errors.length})
              </p>
              <div className="space-y-0.5">
                {errors.map((r, i) => (
                  <div
                    key={i}
                    className="text-[10px] text-red-700 bg-red-50 border border-red-100 rounded px-1.5 py-0.5 flex gap-1"
                  >
                    <span className="font-mono font-semibold">{r.identifier}</span>
                    {r.error && (
                      <span className="opacity-60 truncate min-w-0">— {r.error}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {successes.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-green-600 uppercase tracking-wide mb-0.5">
                Found ({successes.length})
              </p>
              <div className="flex flex-wrap gap-0.5">
                {successes.map((r, i) => (
                  <span
                    key={i}
                    className="text-[10px] font-mono text-green-700 bg-green-50 border border-green-100 rounded px-1 py-0.5"
                  >
                    {r.identifier}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// SecurityRow
// ---------------------------------------------------------------------------

function SecurityRow({ sec, selected, onSelect }) {
  return (
    <button
      onClick={() => onSelect(sec.id)}
      className={`w-full text-left px-4 py-3 transition-colors ${
        selected
          ? 'bg-[#e8f8fe] border-l-2 border-lpa-cyan'
          : 'hover:bg-[#f4fbfe] border-l-2 border-transparent'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-mono font-semibold text-slate-800">
            {sec.ticker || '—'}
          </p>
          <p className="text-xs text-slate-500 truncate mt-0.5">
            {sec.company_name || sec.cik}
          </p>
          {sec.exchange && (
            <p className="text-xs text-slate-400 mt-0.5">{sec.exchange}</p>
          )}
        </div>
        <div className="shrink-0 flex flex-col items-end gap-1">
          <StatusBadge status={sec.status} small />
          {sec.adr_flag && (
            <span className="text-xs bg-amber-100 text-amber-700 border border-amber-200 rounded px-1 py-0.5 font-medium">
              ADR
            </span>
          )}
        </div>
      </div>
    </button>
  )
}

// ---------------------------------------------------------------------------
// SecurityList
// ---------------------------------------------------------------------------

function SecurityList({ selectedId, onSelect, refreshTrigger }) {
  const [search,   setSearch]   = useState('')
  const [status,   setStatus]   = useState('')
  const [page,     setPage]     = useState(1)
  const [data,     setData]     = useState({ total: 0, items: [] })
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = { page, page_size: PAGE_SIZE }
      if (status) params.status = status
      if (search) params.search = search
      const result = await api.underlyingList(params)
      setData(result)
    } catch (e) {
      setError(e.message || 'Failed to load securities')
    } finally {
      setLoading(false)
    }
  }, [page, status, search])

  // Reset page when filter/search changes
  useEffect(() => { setPage(1) }, [search, status])

  useEffect(() => { load() }, [load, refreshTrigger])

  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE))

  return (
    <div className="flex flex-col h-full">
      {/* Filters */}
      <div className="px-3 py-2 border-b border-slate-200 bg-slate-50 space-y-1.5">
        <div className="flex gap-1.5 items-center">
          <input
            className="flex-1 border border-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-lpa-cyan"
            placeholder="Search ticker or name…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <button
            onClick={load}
            className="text-slate-400 hover:text-slate-700 p-1 rounded hover:bg-slate-200 transition-colors"
            title="Refresh"
          >
            ↻
          </button>
        </div>
        <select
          className="w-full border border-slate-200 rounded px-2 py-1 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-lpa-cyan"
          value={status}
          onChange={e => setStatus(e.target.value)}
        >
          {STATUSES.map(s => (
            <option key={s} value={s}>{s || 'All statuses'}</option>
          ))}
        </select>
      </div>

      {/* Error banner */}
      {error && (
        <div className="px-3 py-2 bg-red-50 border-b border-red-200 text-xs text-red-600 flex items-center justify-between shrink-0">
          <span>{error}</span>
          <button onClick={load} className="underline hover:text-red-800 ml-2">retry</button>
        </div>
      )}

      {/* List */}
      <div className="flex-1 overflow-y-auto scrollbar-thin divide-y divide-slate-100">
        {loading && (
          <p className="p-4 text-xs text-slate-400 text-center animate-pulse">Loading…</p>
        )}
        {!loading && !error && data.items.length === 0 && (
          <p className="p-4 text-xs text-slate-400 text-center">
            No securities found. Use the Ingest tab to add some.
          </p>
        )}
        {data.items.map(sec => (
          <SecurityRow
            key={sec.id}
            sec={sec}
            selected={sec.id === selectedId}
            onSelect={onSelect}
          />
        ))}
      </div>

      {/* Pagination + count */}
      <div className="px-3 py-2 border-t border-slate-200 bg-slate-50 flex items-center justify-between text-xs text-slate-500">
        <span>{data.total} securit{data.total !== 1 ? 'ies' : 'y'}</span>
        {totalPages > 1 && (
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-1.5 py-0.5 rounded hover:bg-slate-200 disabled:opacity-30 transition-colors"
            >
              ‹
            </button>
            <span>{page}/{totalPages}</span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-1.5 py-0.5 rounded hover:bg-slate-200 disabled:opacity-30 transition-colors"
            >
              ›
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Exported component
// ---------------------------------------------------------------------------

export default function UnderlyingPanel({ selectedId, onSelect, refreshKey = 0 }) {
  const [tab,            setTab]            = useState('securities')
  const [refreshTrigger, setRefreshTrigger] = useState(0)
  const [activeJobId,    setActiveJobId]    = useState(null)   // job being tracked

  // Called immediately when a job is queued.
  // Captures the job ID so the banner can start polling, then switches to the
  // list tab so the user sees securities appearing as they are ingested.
  const onJobStarted = useCallback((jobId) => {
    setActiveJobId(jobId)
    setTab('securities')
  }, [])

  // Called by JobBanner once polling detects completion — refresh the list.
  const onJobComplete = useCallback(() => {
    setRefreshTrigger(t => t + 1)
  }, [])

  return (
    <div className="flex flex-col h-full">

      {/* ── Persistent job banner ─────────────────────────────────────── */}
      {activeJobId && (
        <JobBanner
          key={activeJobId}
          jobId={activeJobId}
          onComplete={onJobComplete}
          onDismiss={() => setActiveJobId(null)}
        />
      )}

      {/* ── Tab bar ───────────────────────────────────────────────────── */}
      <div className="flex border-b border-slate-200 shrink-0">
        {[['securities', 'Securities'], ['ingest', 'Ingest']].map(([t, label]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2.5 text-xs font-semibold transition-colors ${
              tab === t
                ? 'text-lpa-cyan border-b-2 border-lpa-cyan bg-white'
                : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Tab content ───────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {tab === 'securities'
          ? (
            <SecurityList
              selectedId={selectedId}
              onSelect={onSelect}
              refreshTrigger={refreshTrigger + refreshKey}
            />
          ) : (
            <div className="h-full overflow-y-auto scrollbar-thin">
              <UnderlyingIngest onJobStarted={onJobStarted} />
            </div>
          )
        }
      </div>
    </div>
  )
}
