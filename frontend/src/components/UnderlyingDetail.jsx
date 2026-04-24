/**
 * UnderlyingDetail.jsx — Full detail panel for one underlying security.
 *
 * Tabs:
 *   Overview   — Tier 1 metadata (identification, company, EDGAR filings, currentness)
 *   Review     — Tier 2 LLM-extracted fields with accept / edit / reject actions
 *   Market     — Tier 3 market data (prices, series preview)
 *
 * Props:
 *   securityId  string | null  — UUID of the UnderlyingSecurity to display
 *   onChanged()                — callback when approve/archive/refetch mutates the record
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../api.js'
import StatusBadge from './StatusBadge.jsx'

// ---------------------------------------------------------------------------
// Generic helpers
// ---------------------------------------------------------------------------

function MetaRow({ label, value, mono }) {
  if (value == null || value === '') return null
  return (
    <div className="flex gap-2 py-0.5">
      <span className="text-slate-400 text-xs w-40 shrink-0">{label}</span>
      <span className={`text-slate-700 text-xs break-all ${mono ? 'font-mono' : 'font-medium'}`}>
        {String(value)}
      </span>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="mb-4">
      <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5 pb-0.5 border-b border-slate-100">
        {title}
      </h4>
      <div className="space-y-0.5">{children}</div>
    </div>
  )
}

function ActionButton({ label, onClick, disabled, variant = 'primary', small }) {
  const variants = {
    primary:  'bg-lpa-blue hover:bg-[#0c2fd4] text-white',
    success:  'bg-green-600 hover:bg-green-700 text-white',
    warning:  'bg-amber-500 hover:bg-amber-600 text-white',
    danger:   'bg-red-500 hover:bg-red-600 text-white',
    neutral:  'bg-slate-600 hover:bg-slate-700 text-white',
    ghost:    'bg-white hover:bg-slate-100 text-slate-700 border border-slate-300',
  }
  const sz = small ? 'text-xs px-2 py-1' : 'text-xs px-3 py-1.5'
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`${variants[variant]} ${sz} font-medium rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed`}
    >
      {label}
    </button>
  )
}

function fmtNum(n, decimals = 2) {
  if (n == null) return '—'
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: decimals })
}

function fmtLargeNum(n) {
  if (n == null) return '—'
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9)  return `${(n / 1e9).toFixed(2)}B`
  if (n >= 1e6)  return `${(n / 1e6).toFixed(2)}M`
  return fmtNum(n, 0)
}

// ---------------------------------------------------------------------------
// Overview tab
// ---------------------------------------------------------------------------

function OverviewTab({ sec }) {
  return (
    <div className="p-4 overflow-y-auto scrollbar-thin h-full">
      <Section title="Identification">
        <MetaRow label="CIK"               value={sec.cik}                      mono />
        <MetaRow label="Ticker"            value={sec.ticker}                   mono />
        <MetaRow label="Bloomberg Ticker"  value={sec.ticker_bb}                mono />
        <MetaRow label="Source Identifier" value={sec.source_identifier}        mono />
        <MetaRow label="Source Type"       value={sec.source_identifier_type} />
      </Section>

      <Section title="Company">
        <MetaRow label="Company Name"      value={sec.company_name} />
        <MetaRow label="Share Class"       value={sec.share_class_name} />
        <MetaRow label="Share Type"        value={sec.share_type} />
        <MetaRow label="Exchange"          value={sec.exchange} />
        <MetaRow label="Entity Type"       value={sec.entity_type} />
        <MetaRow label="SIC Code"          value={sec.sic_code ? `${sec.sic_code} — ${sec.sic_description || ''}` : null} />
        <MetaRow label="Incorporation"     value={sec.state_of_incorporation} />
        <MetaRow label="Fiscal Year End"   value={sec.fiscal_year_end} />
        <MetaRow label="Filer Category"    value={sec.filer_category} />
        <MetaRow label="Reporting Form"    value={sec.reporting_form} />
        <div className="flex gap-2 py-0.5">
          <span className="text-slate-400 text-xs w-40 shrink-0">ADR</span>
          <span className="text-xs font-medium">
            {sec.adr_flag
              ? <span className="text-amber-700 bg-amber-50 border border-amber-200 rounded px-1">Yes</span>
              : <span className="text-slate-500">No</span>
            }
          </span>
        </div>
      </Section>

      <Section title="Latest Filings">
        <MetaRow label="Annual (10-K/20-F)"  value={sec.last_10k_accession}    mono />
        <MetaRow label="Annual Period"        value={sec.last_10k_period} />
        <MetaRow label="Annual Filed"         value={sec.last_10k_filed} />
        <MetaRow label="Quarterly (10-Q)"     value={sec.last_10q_accession}   mono />
        <MetaRow label="Quarterly Period"     value={sec.last_10q_period} />
        <MetaRow label="Quarterly Filed"      value={sec.last_10q_filed} />
      </Section>

      <Section title="Currentness">
        {sec.current_status && (
          <div className="flex gap-2 py-0.5">
            <span className="text-slate-400 text-xs w-40 shrink-0">Filing Status</span>
            <StatusBadge status={sec.current_status} small />
          </div>
        )}
        <MetaRow label="NT Filed"          value={sec.nt_flag ? 'Yes' : null} />
        <MetaRow label="Next Filing Due"   value={sec.next_expected_filing} />
        <MetaRow label="Next Form"         value={sec.next_expected_form} />
      </Section>

      <Section title="XBRL Facts">
        <MetaRow label="Shares Outstanding" value={sec.shares_outstanding ? `${fmtLargeNum(sec.shares_outstanding)} (${sec.shares_outstanding_date || ''})` : null} />
        <MetaRow label="Public Float"       value={sec.public_float_usd   ? `$${fmtLargeNum(sec.public_float_usd)} (${sec.public_float_date || ''})` : null} />
      </Section>

      <Section title="Lifecycle">
        <MetaRow label="Field Config Ver"   value={sec.field_config_version} />
        <MetaRow label="Last Fetched"       value={sec.last_fetched_at} />
        <MetaRow label="Ingested"           value={sec.ingest_timestamp} />
        {sec.fetch_error && (
          <div className="mt-1 bg-amber-50 border border-amber-200 rounded p-2 text-xs text-amber-800">
            ⚠ {sec.fetch_error}
          </div>
        )}
      </Section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Field review row
// ---------------------------------------------------------------------------

function FieldRow({ fr, onUpdate }) {
  const [editing,    setEditing]    = useState(false)
  const [editVal,    setEditVal]    = useState('')
  const [saving,     setSaving]     = useState(false)

  const displayValue = fr.reviewed_value != null ? fr.reviewed_value : fr.extracted_value
  const displayStr   = displayValue == null ? '—' : (typeof displayValue === 'boolean' ? (displayValue ? 'True' : 'False') : String(displayValue))

  const confColor = fr.confidence_score >= 0.90 ? 'text-green-600'
    : fr.confidence_score >= 0.70 ? 'text-amber-600'
    : 'text-red-600'

  const startEdit = () => {
    setEditVal(displayValue == null ? '' : String(displayValue))
    setEditing(true)
  }

  const doSave = async (value, action) => {
    setSaving(true)
    try {
      await api.underlyingUpdateField(fr._underlying_id, fr.field_name, { value, action })
      onUpdate()
    } catch (e) {
      alert(e.message)
    } finally {
      setSaving(false)
      setEditing(false)
    }
  }

  return (
    <tr className="border-t border-slate-100 hover:bg-slate-50">
      <td className="py-2 px-3 text-xs font-mono text-slate-700 whitespace-nowrap">{fr.field_name}</td>
      <td className="py-2 px-3 text-xs text-slate-700 max-w-xs">
        {editing ? (
          <input
            autoFocus
            className="w-full border border-lpa-cyan rounded px-2 py-0.5 text-xs focus:outline-none"
            value={editVal}
            onChange={e => setEditVal(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') doSave(editVal, 'edited'); if (e.key === 'Escape') setEditing(false) }}
          />
        ) : (
          <span className={fr.reviewed_value != null ? 'text-blue-700 font-medium' : ''}>
            {displayStr}
          </span>
        )}
      </td>
      <td className="py-2 px-3 text-xs whitespace-nowrap">
        {fr.confidence_score != null && (
          <span className={`font-mono ${confColor}`}>
            {(fr.confidence_score * 100).toFixed(0)}%
          </span>
        )}
      </td>
      <td className="py-2 px-3">
        <StatusBadge status={fr.review_status} small />
      </td>
      <td className="py-2 px-3 whitespace-nowrap">
        {editing ? (
          <span className="flex gap-1">
            <ActionButton label="Save"   onClick={() => doSave(editVal, 'edited')} disabled={saving} variant="primary"  small />
            <ActionButton label="Cancel" onClick={() => setEditing(false)}          disabled={saving} variant="ghost"    small />
          </span>
        ) : (
          <span className="flex gap-1">
            {fr.review_status !== 'accepted' && (
              <ActionButton
                label="Accept"
                onClick={() => doSave(displayValue, 'accepted')}
                disabled={saving}
                variant="success"
                small
              />
            )}
            <ActionButton label="Edit" onClick={startEdit} disabled={saving} variant="ghost" small />
          </span>
        )}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Review tab
// ---------------------------------------------------------------------------

function ReviewTab({ sec, onUpdate }) {
  const fields = (sec.field_results || []).map(fr => ({
    ...fr,
    _underlying_id: sec.id,
  }))

  if (!fields.length) {
    return (
      <div className="p-6 text-center text-sm text-slate-400">
        No LLM-extracted fields available.
        <br />
        <span className="text-xs">Run ingest with "Run LLM extraction" enabled to populate this tab.</span>
      </div>
    )
  }

  return (
    <div className="overflow-auto h-full scrollbar-thin">
      <table className="w-full text-left">
        <thead>
          <tr className="bg-slate-50 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase tracking-wide">
            <th className="py-2 px-3">Field</th>
            <th className="py-2 px-3">Value</th>
            <th className="py-2 px-3">Conf.</th>
            <th className="py-2 px-3">Status</th>
            <th className="py-2 px-3">Actions</th>
          </tr>
        </thead>
        <tbody>
          {fields.map(fr => (
            <FieldRow key={fr.field_name} fr={fr} onUpdate={onUpdate} />
          ))}
        </tbody>
      </table>
      <div className="px-3 py-2 text-xs text-slate-400 border-t border-slate-100">
        Blue values have been manually reviewed. Accept or edit extracted values to move them from Needs Review to Fetched.
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Market Data tab
// ---------------------------------------------------------------------------

function MarketTab({ sec }) {
  const series = Array.isArray(sec.hist_data_series) ? sec.hist_data_series : []

  const previewRows = [
    ...series.slice(0, 3),
    series.length > 6 && { _gap: true },
    ...series.slice(-3),
  ].filter(Boolean)

  return (
    <div className="p-4 overflow-y-auto scrollbar-thin h-full space-y-4">
      <Section title="Prices">
        <MetaRow label="Initial Value"     value={sec.initial_value != null ? `$${fmtNum(sec.initial_value, 4)} (${sec.initial_value_date || ''})` : null} />
        <MetaRow label="Closing Value"     value={sec.closing_value != null ? `$${fmtNum(sec.closing_value, 4)} (${sec.closing_value_date || ''})` : null} />
        <MetaRow label="Source"            value={sec.market_data_source} />
        <MetaRow label="Fetched At"        value={sec.market_data_fetched_at} />
      </Section>

      {series.length === 0 && (
        <div className="text-xs text-slate-400 text-center py-4">
          No price series available.
          <br />Run ingest with "Fetch market data" enabled to populate this tab.
        </div>
      )}

      {series.length > 0 && (
        <Section title={`Price Series (${series.length} trading days)`}>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500 font-semibold">
                  <th className="py-1 px-2 text-left">Date</th>
                  <th className="py-1 px-2 text-right">Close</th>
                  <th className="py-1 px-2 text-right">Volume</th>
                </tr>
              </thead>
              <tbody>
                {previewRows.map((row, i) =>
                  row._gap
                    ? (
                      <tr key="gap">
                        <td colSpan={3} className="py-1 px-2 text-center text-slate-300">⋯</td>
                      </tr>
                    ) : (
                      <tr key={i} className="border-t border-slate-50 hover:bg-slate-50">
                        <td className="py-1 px-2 font-mono text-slate-700">{row.date}</td>
                        <td className="py-1 px-2 text-right font-mono text-slate-800">${fmtNum(row.close, 4)}</td>
                        <td className="py-1 px-2 text-right text-slate-500">{row.volume ? fmtLargeNum(row.volume) : '—'}</td>
                      </tr>
                    )
                )}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Showing first 3 and last 3 rows. Source: {sec.market_data_source || 'Yahoo Finance (approximate)'}.
            All Tier 3 data is approximate and editable.
          </p>
        </Section>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Filing links tab
// ---------------------------------------------------------------------------

function LinksTab({ sec, onUpdate }) {
  const [searchId, setSearchId]   = useState('')
  const [linking,  setLinking]    = useState(false)
  const [error,    setError]      = useState('')
  const links = sec.links || []

  const doLink = async () => {
    if (!searchId.trim()) return
    setLinking(true); setError('')
    try {
      await api.underlyingLinkFiling(sec.id, searchId.trim())
      setSearchId('')
      onUpdate()
    } catch (e) {
      setError(e.message)
    } finally {
      setLinking(false)
    }
  }

  const doUnlink = async (filingId) => {
    if (!window.confirm('Remove this filing link?')) return
    try {
      await api.underlyingUnlinkFiling(sec.id, filingId)
      onUpdate()
    } catch (e) {
      alert(e.message)
    }
  }

  return (
    <div className="p-4 overflow-y-auto scrollbar-thin h-full space-y-4">
      {/* ── Add link ───────────────────────────────────────────────────── */}
      <div className="bg-slate-50 border border-slate-200 rounded p-3">
        <h4 className="text-xs font-semibold text-slate-600 mb-2">Link to a 424B2 Filing</h4>
        <div className="flex gap-2">
          <input
            className="flex-1 border border-slate-200 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-lpa-cyan"
            placeholder="Paste Filing ID (UUID)…"
            value={searchId}
            onChange={e => setSearchId(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && doLink()}
          />
          <button
            onClick={doLink}
            disabled={!searchId.trim() || linking}
            className="bg-lpa-blue hover:bg-[#0c2fd4] disabled:bg-slate-300 text-white text-xs font-medium rounded px-3 py-1 transition-colors"
          >
            {linking ? '…' : 'Link'}
          </button>
        </div>
        {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
        <p className="mt-1.5 text-xs text-slate-400">
          Copy the Filing ID from the Filings list. Links are also created automatically when a filing is classified with this underlying.
        </p>
      </div>

      {/* ── Linked filings ─────────────────────────────────────────────── */}
      {links.length === 0 ? (
        <p className="text-xs text-slate-400 text-center py-4">No linked filings.</p>
      ) : (
        <div className="space-y-1.5">
          <h4 className="text-xs font-semibold text-slate-600">
            Linked Filings ({links.length})
          </h4>
          {links.map(lnk => (
            <div
              key={lnk.id}
              className="flex items-start justify-between gap-3 border border-slate-200 rounded p-2.5 bg-white text-xs"
            >
              <div className="min-w-0 space-y-0.5">
                <p className="font-mono font-medium text-slate-800">
                  {lnk.filing_cusip || lnk.filing_accession || lnk.filing_id}
                </p>
                {lnk.filing_issuer_name && (
                  <p className="text-slate-500 truncate">{lnk.filing_issuer_name}</p>
                )}
                <p className="text-slate-400">
                  {lnk.filing_date && <span>{lnk.filing_date} · </span>}
                  <span className={`capitalize ${lnk.link_source === 'manual' ? 'text-blue-600' : 'text-slate-400'}`}>
                    {lnk.link_source}
                  </span>
                  {lnk.filing_status && <span> · <StatusBadge status={lnk.filing_status} small /></span>}
                </p>
              </div>
              <button
                onClick={() => doUnlink(lnk.filing_id)}
                className="shrink-0 text-red-400 hover:text-red-600 text-xs font-medium transition-colors"
                title="Remove link"
              >
                ✕
              </button>
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

export default function UnderlyingDetail({ securityId, onChanged }) {
  const [sec,     setSec]     = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)
  const [tab,     setTab]     = useState('overview')
  const [busy,    setBusy]    = useState(null)  // 'approve' | 'refetch' | 'archive' | 'export'

  const load = useCallback(async () => {
    if (!securityId) { setSec(null); return }
    setLoading(true)
    setError(null)
    try {
      const data = await api.underlyingGet(securityId)
      setSec(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [securityId])

  useEffect(() => { load() }, [load])

  // ── Actions ────────────────────────────────────────────────────────────────

  const doApprove = async () => {
    setBusy('approve')
    try {
      await api.underlyingApprove(securityId)
      setSec(s => ({ ...s, status: 'approved' }))
      if (onChanged) onChanged()
    } catch (e) {
      alert(e.message)
    } finally {
      setBusy(null)
    }
  }

  const doRefetch = async () => {
    setBusy('refetch')
    try {
      await api.underlyingRefetch(securityId)
      setSec(s => ({ ...s, status: 'fetching' }))
      if (onChanged) onChanged()
    } catch (e) {
      alert(e.message)
    } finally {
      setBusy(null)
    }
  }

  const doArchive = async () => {
    if (!window.confirm('Archive this security? It will be hidden from the default list.')) return
    setBusy('archive')
    try {
      await api.underlyingDelete(securityId)
      setSec(s => ({ ...s, status: 'archived' }))
      if (onChanged) onChanged()
    } catch (e) {
      alert(e.message)
    } finally {
      setBusy(null)
    }
  }

  const doExport = async () => {
    setBusy('export')
    try {
      const data = await api.underlyingExportOne(securityId)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `underlying_${sec?.ticker || securityId}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      alert(e.message)
    } finally {
      setBusy(null)
    }
  }

  // ── Empty state ────────────────────────────────────────────────────────────

  if (!securityId) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm">
        Select a security from the list or ingest a new one.
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm animate-pulse">
        Loading…
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-sm">
        <p className="text-red-600">{error}</p>
        <button onClick={load} className="text-xs text-lpa-cyan underline">Retry</button>
      </div>
    )
  }

  if (!sec) return null

  const canApprove  = sec.status === 'fetched' || sec.status === 'needs_review'
  const canArchive  = sec.status !== 'archived'

  return (
    <div className="flex flex-col h-full">
      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="px-5 py-3 border-b border-slate-200 bg-white shrink-0">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-lg font-bold text-slate-900 font-mono">
                {sec.ticker || '—'}
              </span>
              {sec.ticker_bb && sec.ticker_bb !== sec.ticker && (
                <span className="text-sm text-slate-500 font-mono">{sec.ticker_bb}</span>
              )}
              <StatusBadge status={sec.status} />
              {sec.adr_flag && (
                <span className="text-xs bg-amber-100 text-amber-700 border border-amber-200 rounded px-1.5 py-0.5 font-medium">
                  ADR
                </span>
              )}
              {sec.current_status && (
                <StatusBadge status={sec.current_status} small />
              )}
            </div>
            <p className="text-sm text-slate-600 mt-0.5 truncate">{sec.company_name}</p>
            {sec.exchange && (
              <p className="text-xs text-slate-400 mt-0.5">{sec.exchange} · CIK {sec.cik}</p>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
            {canApprove && (
              <ActionButton
                label="Approve"
                onClick={doApprove}
                disabled={!!busy}
                variant="success"
              />
            )}
            <ActionButton
              label="Re-fetch"
              onClick={doRefetch}
              disabled={!!busy}
              variant="neutral"
            />
            <ActionButton
              label="Export ↓"
              onClick={doExport}
              disabled={!!busy}
              variant="ghost"
            />
            {canArchive && (
              <ActionButton
                label="Archive"
                onClick={doArchive}
                disabled={!!busy}
                variant="danger"
              />
            )}
          </div>
        </div>
      </div>

      {/* ── Tabs ────────────────────────────────────────────────────────────── */}
      <div className="flex border-b border-slate-200 bg-white shrink-0 px-4">
        {[
          ['overview', 'Overview'],
          ['review',   `Review (${(sec.field_results || []).length})`],
          ['market',   'Market Data'],
          ['links',    `Links (${(sec.links || []).length})`],
        ].map(([t, label]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2.5 text-xs font-semibold border-b-2 transition-colors ${
              tab === t
                ? 'border-lpa-cyan text-lpa-cyan'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Tab content ─────────────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {tab === 'overview' && <OverviewTab sec={sec} />}
        {tab === 'review'   && <ReviewTab   sec={sec} onUpdate={load} />}
        {tab === 'market'   && <MarketTab   sec={sec} />}
        {tab === 'links'    && <LinksTab    sec={sec} onUpdate={load} />}
      </div>
    </div>
  )
}
