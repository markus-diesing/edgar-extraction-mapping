import { useMemo, useState } from 'react'
import StatusBadge from './StatusBadge.jsx'

const STATUSES = ['', 'ingested', 'classified', 'needs_classification_review', 'needs_review', 'extracted', 'approved', 'exported']

export default function FilingList({ filings, selectedId, onSelect, onRefresh }) {
  const [statusFilter, setStatusFilter] = useState('')
  const [issuerFilter, setIssuerFilter] = useState('')
  const [modelFilter,  setModelFilter]  = useState('')
  const [cusipFilter,  setCusipFilter]  = useState('')

  // Derive sorted unique issuer and model lists from current filings
  const issuers = useMemo(() => {
    const names = [...new Set(filings.map(f => f.issuer_name).filter(Boolean))].sort()
    return names
  }, [filings])

  const models = useMemo(() => {
    const ids = [...new Set(filings.map(f => f.payout_type_id).filter(Boolean))].sort()
    return ids
  }, [filings])

  const filtered = filings.filter(f => {
    if (statusFilter && f.status !== statusFilter) return false
    if (issuerFilter && f.issuer_name !== issuerFilter) return false
    if (modelFilter  && f.payout_type_id !== modelFilter) return false
    if (cusipFilter  && !(f.cusip || '').toLowerCase().includes(cusipFilter.toLowerCase())) return false
    return true
  })

  const hasActiveFilter = !!(statusFilter || issuerFilter || modelFilter || cusipFilter)

  return (
    <div className="flex flex-col h-full">
      {/* Filters */}
      <div className="px-4 py-2 border-b border-slate-200 bg-slate-50 space-y-1.5">
        {/* CUSIP search + refresh */}
        <div className="flex gap-1.5 items-center">
          <input
            className="flex-1 border border-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-lpa-cyan"
            placeholder="Filter by CUSIP…"
            value={cusipFilter}
            onChange={e => setCusipFilter(e.target.value)}
          />
          <button
            onClick={onRefresh}
            className="text-slate-400 hover:text-slate-700 p-1 rounded hover:bg-slate-200 transition-colors"
            title="Refresh"
          >
            ↻
          </button>
        </div>

        {/* Status filter */}
        <select
          className="w-full border border-slate-200 rounded px-2 py-1 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-lpa-cyan"
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
        >
          {STATUSES.map(s => (
            <option key={s} value={s}>{s || 'All statuses'}</option>
          ))}
        </select>

        {/* Issuer filter */}
        <select
          className="w-full border border-slate-200 rounded px-2 py-1 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-lpa-cyan"
          value={issuerFilter}
          onChange={e => setIssuerFilter(e.target.value)}
        >
          <option value="">All issuers</option>
          {issuers.map(name => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>

        {/* PRISM model filter */}
        <select
          className="w-full border border-slate-200 rounded px-2 py-1 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-lpa-cyan"
          value={modelFilter}
          onChange={e => setModelFilter(e.target.value)}
        >
          <option value="">All models</option>
          {models.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>

        {/* Clear all filters */}
        {hasActiveFilter && (
          <button
            onClick={() => { setStatusFilter(''); setIssuerFilter(''); setModelFilter(''); setCusipFilter('') }}
            className="w-full text-xs text-lpa-cyan hover:text-lpa-blue py-0.5 hover:underline"
          >
            ✕ Clear all filters
          </button>
        )}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto scrollbar-thin divide-y divide-slate-100">
        {filtered.length === 0 && (
          <p className="p-4 text-xs text-slate-400 text-center">No filings yet. Use Search or Direct Ingest above.</p>
        )}
        {filtered.map(f => (
          <button
            key={f.id}
            onClick={() => onSelect(f.id)}
            className={`w-full text-left px-4 py-3 transition-colors ${
              f.id === selectedId
                ? 'bg-[#e8f8fe] border-l-2 border-lpa-cyan'
                : 'hover:bg-[#f4fbfe]'
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-mono font-medium text-slate-800">
                  {f.cusip || '—'}
                </p>
                <p className="text-xs text-slate-500 truncate mt-0.5">
                  {f.issuer_name || f.accession_number}
                </p>
                {f.payout_type_id && (
                  <p className="text-xs text-lpa-cyan truncate mt-0.5">
                    {f.payout_type_id}
                  </p>
                )}
              </div>
              <div className="shrink-0 flex flex-col items-end gap-1">
                <StatusBadge status={f.status} small />
                {f.classification_confidence != null && (
                  <span className="text-xs text-slate-400">
                    {(f.classification_confidence * 100).toFixed(0)}%
                  </span>
                )}
              </div>
            </div>
          </button>
        ))}
      </div>

      <div className="px-4 py-2 border-t border-slate-200 bg-slate-50 text-xs text-slate-400">
        {filtered.length} of {filings.length} filing{filings.length !== 1 ? 's' : ''}
      </div>
    </div>
  )
}
