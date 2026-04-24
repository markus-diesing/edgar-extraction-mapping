/**
 * UnderlyingPanel.jsx — Left sidebar for the Underlying Securities view.
 *
 * Contains two tabs:
 *   - "Securities"  : paginated, filterable list of UnderlyingSecurity rows.
 *   - "Ingest"      : UnderlyingIngest form.
 *
 * Props:
 *   selectedId      string | null  — currently selected security ID
 *   onSelect(id)                   — callback when user clicks a row
 *   refreshKey      number         — increment from the parent (App) to force a list refresh
 *                                    e.g. after approve/archive from the detail panel (B2)
 */
import { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'
import StatusBadge from './StatusBadge.jsx'
import UnderlyingIngest from './UnderlyingIngest.jsx'

const PAGE_SIZE = 50

const STATUSES = [
  '',
  'fetching', 'fetched', 'needs_review', 'approved', 'archived',
]

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

  // Called immediately when a job is queued — switch to the list tab so the
  // user can see progress without any refresh lag.
  const onJobStarted = useCallback(() => {
    setTab('securities')
  }, [])

  // Called when the background job reaches done/error — refresh the list so
  // newly-ingested securities appear.  Kept separate from onJobStarted so the
  // list refresh fires exactly once (at completion) rather than twice.
  const onJobDone = useCallback(() => {
    setRefreshTrigger(t => t + 1)
  }, [])

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
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

      {/* Tab content */}
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
              <UnderlyingIngest onJobStarted={onJobStarted} onJobDone={onJobDone} />
            </div>
          )
        }
      </div>
    </div>
  )
}
