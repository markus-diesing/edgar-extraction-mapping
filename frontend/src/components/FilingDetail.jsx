import { useState, useEffect } from 'react'
import { api } from '../api.js'
import StatusBadge from './StatusBadge.jsx'
import FieldTable from './FieldTable.jsx'
import ExpertReview from './ExpertReview.jsx'

function ActionButton({ label, onClick, disabled, variant = 'primary', small }) {
  const variants = {
    primary:  'bg-blue-600 hover:bg-blue-700 text-white',
    success:  'bg-green-600 hover:bg-green-700 text-white',
    warning:  'bg-amber-500 hover:bg-amber-600 text-white',
    danger:   'bg-red-500 hover:bg-red-600 text-white',
    neutral:  'bg-slate-600 hover:bg-slate-700 text-white',
    ghost:    'bg-white hover:bg-slate-100 text-slate-700 border border-slate-300',
  }
  const sz = small ? 'text-xs px-2 py-1' : 'text-sm px-3 py-1.5'
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

function MetaRow({ label, value }) {
  if (!value) return null
  return (
    <div className="flex gap-2">
      <span className="text-slate-400 text-xs w-36 shrink-0">{label}</span>
      <span className="text-slate-700 text-xs font-medium break-all">{value}</span>
    </div>
  )
}

function KpiStrip({ filingId, refreshKey }) {
  const [kpis, setKpis] = useState(null)

  useEffect(() => {
    api.getKpis(filingId).then(setKpis).catch(() => {})
  }, [filingId, refreshKey])

  if (!kpis) return null

  const fmtDur  = (s) => s == null ? '—' : s < 60 ? `${s.toFixed(1)} s` : `${(s / 60).toFixed(1)} min`
  const fmtTok  = (n) => n == null ? '—' : n >= 1000 ? `${(n / 1000).toFixed(0)}K` : String(n)
  const fmtCost = (c) => c == null ? '—' : c < 0.001 ? '<$0.001' : `$${c.toFixed(3)}`

  const items = [
    kpis.ingest && {
      label: 'Ingest', color: 'text-blue-700 border-blue-200 bg-blue-50',
      primary: fmtDur(kpis.ingest.duration_seconds),
      detail: null,
    },
    kpis.classification && {
      label: 'Classify', color: 'text-violet-700 border-violet-200 bg-violet-50',
      primary: fmtDur(kpis.classification.duration_seconds),
      detail: `${fmtTok(kpis.classification.input_tokens)} in / ${fmtTok(kpis.classification.output_tokens)} out · ${fmtCost(kpis.classification.cost_usd)}`
        + (kpis.classification.call_count > 1 ? ` · ${kpis.classification.call_count} calls` : ''),
    },
    kpis.extraction && {
      label: 'Extract', color: 'text-emerald-700 border-emerald-200 bg-emerald-50',
      primary: fmtDur(kpis.extraction.duration_seconds),
      detail: `${fmtTok(kpis.extraction.input_tokens)} in / ${fmtTok(kpis.extraction.output_tokens)} out · ${fmtCost(kpis.extraction.cost_usd)}`
        + (kpis.extraction.call_count > 1 ? ` · ${kpis.extraction.call_count} sections` : ''),
    },
  ].filter(Boolean)

  if (items.length === 0) return null

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {items.map(({ label, color, primary, detail }) => (
        <div key={label} className={`flex items-baseline gap-1.5 border rounded px-2.5 py-1 text-xs ${color}`}>
          <span className="font-semibold">{label}</span>
          <span className="font-mono font-bold">{primary}</span>
          {detail && <span className="opacity-70 hidden sm:inline">· {detail}</span>}
        </div>
      ))}
    </div>
  )
}

export default function FilingDetail({ filingId, onFilingUpdated }) {
  const [filing,         setFiling]        = useState(null)
  const [results,        setResults]       = useState(null)
  const [loading,        setLoading]       = useState(false)
  const [action,         setAction]        = useState(null)
  const [error,          setError]         = useState('')
  const [exported,       setExported]      = useState(null)
  const [kpiRefresh,     setKpiRefresh]    = useState(0)
  const [expertMode,     setExpertMode]    = useState(false)
  // HTML filing view — available at any status
  const [showHtml,       setShowHtml]      = useState(false)
  // Classification override panel
  const [showOverride,   setShowOverride]  = useState(false)
  const [prismModels,    setPrismModels]   = useState([])
  const [overrideModel,  setOverrideModel] = useState('')
  const [overrideReason, setOverrideReason]= useState('')

  const load = async () => {
    if (!filingId) return
    setLoading(true)
    setError('')
    try {
      const f = await api.getFiling(filingId)
      setFiling(f)
      if (['extracted', 'approved', 'exported'].includes(f.status)) {
        const r = await api.getResults(filingId).catch(() => null)
        setResults(r)
      } else {
        setResults(null)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  // Reset view state when switching filings
  useEffect(() => {
    setExpertMode(false)
    setShowHtml(false)
    setShowOverride(false)
    load()
  }, [filingId])

  // Load PRISM model list once when override panel is first opened
  useEffect(() => {
    if (showOverride && prismModels.length === 0) {
      api.listPrismModels()
        .then(data => {
          const models = (data?.models || []).concat(['unknown']).sort()
          setPrismModels(models)
          setOverrideModel(models[0] || '')
        })
        .catch(() => {})
    }
  }, [showOverride])

  const run = async (label, fn) => {
    setAction(label)
    setError('')
    try {
      await fn()
      await load()
      onFilingUpdated()
      setKpiRefresh(k => k + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setAction(null)
    }
  }

  const doClassify        = () => run('classify',   () => api.classify(filingId))
  const doExtract         = () => run('extract',     () => api.extract(filingId))
  const doReextract       = () => run('reextract',   () => api.reextract(filingId))
  const doApprove         = () => run('approve',     () => api.approve(filingId))
  const doUnapprove       = () => run('unapprove',   () => api.unapprove(filingId))
  const doResetClassify   = () => run('resetClassify', () => api.resetClassification(filingId))
  const doApplyOverride   = () => {
    if (!overrideModel) return
    run('override', async () => {
      await api.classifyOverride(filingId, {
        payout_type_id: overrideModel,
        reason: overrideReason || undefined,
      })
      setShowOverride(false)
      setOverrideReason('')
    })
  }
  const doExport          = async () => {
    run('export', async () => {
      const result = await api.exportFiling(filingId)
      setExported(result)
    })
  }

  const onFieldUpdated = (updatedField) => {
    if (!results) return
    setResults(prev => ({
      ...prev,
      fields: prev.fields.map(f => f.id === updatedField.id ? updatedField : f),
    }))
  }

  if (!filingId) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm">
        Select a filing from the list to view details.
      </div>
    )
  }

  if (loading) {
    return <div className="flex items-center justify-center h-full text-slate-400 text-sm">Loading…</div>
  }

  if (!filing) {
    return <div className="flex items-center justify-center h-full text-red-400 text-sm">{error || 'Filing not found'}</div>
  }

  const status = filing.status
  const canClassify     = ['ingested'].includes(status)
  const canResetClassify= ['classified', 'needs_review'].includes(status)
  const canOverride     = !['approved', 'exported'].includes(status)
  const canExtract      = ['classified', 'needs_review'].includes(status)
  const canReextract    = ['extracted'].includes(status)
  const canApprove      = ['extracted', 'needs_review'].includes(status)
  const canUnapprove    = status === 'approved'
  const canExport       = status === 'approved'
  const hasResults      = !!results

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="px-6 py-4 bg-white border-b border-slate-200 shrink-0">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <h2 className="text-xl font-bold text-slate-800 font-mono">
                {filing.cusip || filing.accession_number}
              </h2>
              <StatusBadge status={filing.status} />
              {filing.classification_confidence != null && (
                <span className={`text-xs font-medium px-2 py-0.5 rounded border ${
                  filing.classification_confidence >= 0.75
                    ? 'bg-green-50 text-green-700 border-green-200'
                    : 'bg-amber-50 text-amber-700 border-amber-200'
                }`}>
                  {(filing.classification_confidence * 100).toFixed(0)}% conf.
                </span>
              )}
            </div>
            <p className="text-sm text-slate-600">{filing.issuer_name || '—'}</p>
            {filing.payout_type_id && (
              <p className="text-xs text-blue-600 mt-0.5 font-medium">{filing.payout_type_id}</p>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex flex-wrap gap-2 shrink-0">
            {canClassify     && <ActionButton label={action === 'classify'      ? 'Classifying…' : 'Classify'}      onClick={doClassify}      disabled={!!action} variant="primary" />}
            {canResetClassify&& <ActionButton label={action === 'resetClassify' ? 'Resetting…'   : '↺ Reset'}       onClick={doResetClassify} disabled={!!action} variant="ghost" small />}
            {canOverride     && <ActionButton label="Set Model"                                                      onClick={() => setShowOverride(v => !v)} disabled={!!action} variant="ghost" small />}
            {canExtract      && <ActionButton label={action === 'extract'       ? 'Extracting…'  : 'Extract'}       onClick={doExtract}       disabled={!!action} variant="primary" />}
            {canReextract    && <ActionButton label={action === 'reextract'     ? 'Re-running…'  : 'Re-extract'}    onClick={doReextract}     disabled={!!action} variant="ghost" small />}
            {canApprove      && <ActionButton label={action === 'approve'       ? 'Approving…'   : '✓ Approve'}     onClick={doApprove}       disabled={!!action} variant="success" />}
            {canUnapprove    && <ActionButton label="Undo Approve"                                                   onClick={doUnapprove}     disabled={!!action} variant="ghost" small />}
            {canExport       && <ActionButton label={action === 'export'        ? 'Exporting…'   : '↓ Export'}      onClick={doExport}        disabled={!!action} variant="neutral" />}
          </div>
        </div>

        {/* Classification override panel */}
        {showOverride && (
          <div className="mt-3 p-3 bg-amber-50 border border-amber-200 rounded flex flex-col gap-2">
            <p className="text-xs font-semibold text-amber-800">Manually set PRISM model</p>
            <div className="flex gap-2 flex-wrap items-end">
              <select
                value={overrideModel}
                onChange={e => setOverrideModel(e.target.value)}
                className="text-xs border border-slate-300 rounded px-2 py-1 bg-white text-slate-700 min-w-48"
              >
                {prismModels.map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
              <input
                type="text"
                placeholder="Reason (optional)"
                value={overrideReason}
                onChange={e => setOverrideReason(e.target.value)}
                className="text-xs border border-slate-300 rounded px-2 py-1 bg-white flex-1 min-w-36"
              />
              <ActionButton
                label={action === 'override' ? 'Applying…' : 'Apply'}
                onClick={doApplyOverride}
                disabled={!!action || !overrideModel}
                variant="warning"
                small
              />
              <ActionButton label="Cancel" onClick={() => setShowOverride(false)} variant="ghost" small />
            </div>
            <p className="text-xs text-amber-700">
              This overrides the classifier result and sets confidence to 100%.
              The correction is logged in the audit trail.
            </p>
          </div>
        )}

        {/* Metadata */}
        <div className="mt-3 grid grid-cols-2 gap-x-8 gap-y-1">
          <MetaRow label="Accession Number" value={filing.accession_number} />
          <MetaRow label="Filing Date"      value={filing.filing_date} />
          <MetaRow label="Ingest Time"      value={filing.ingest_timestamp?.replace('T', ' ').slice(0, 19) + ' UTC'} />
          {filing.payout_type_id && (
            <MetaRow label="PRISM Model" value={filing.payout_type_id} />
          )}
        </div>

        {/* KPI strip */}
        <KpiStrip filingId={filingId} refreshKey={kpiRefresh} />

        {/* Error / export success */}
        {error && (
          <div className="mt-3 bg-red-50 border border-red-200 rounded px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}
        {exported && (
          <div className="mt-3 bg-green-50 border border-green-200 rounded px-3 py-2 text-xs text-green-700">
            Exported → <code>{exported.json_path}</code>
          </div>
        )}
      </div>

      {/* Results / content area */}
      {hasResults && !showHtml ? (
        <div className="flex flex-col flex-1 min-h-0">
          {/* View toggle bar — fields ↔ expert ↔ html */}
          <div className="flex items-center gap-2 px-4 py-1.5 bg-slate-50 border-b border-slate-200 shrink-0">
            <span className="text-xs text-slate-400 mr-auto">
              {expertMode ? 'Click a field row to locate its source in the EDGAR filing' : ''}
            </span>
            <button
              onClick={() => setShowHtml(true)}
              className="flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded border bg-white text-slate-600 border-slate-300 hover:bg-slate-50 transition-colors"
            >
              ⬛ Filing HTML
            </button>
            <button
              onClick={() => setExpertMode(m => !m)}
              className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded border transition-colors ${
                expertMode
                  ? 'bg-indigo-600 text-white border-indigo-600 hover:bg-indigo-700'
                  : 'bg-white text-slate-600 border-slate-300 hover:bg-slate-50'
              }`}
            >
              <span>{expertMode ? '⊞' : '⊟'}</span>
              {expertMode ? 'Simple View' : 'Expert View'}
            </button>
          </div>

          <div className="flex-1 min-h-0">
            {expertMode ? (
              <ExpertReview
                fields={results.fields}
                filingId={filingId}
                onFieldUpdated={onFieldUpdated}
              />
            ) : (
              <FieldTable
                fields={results.fields}
                filingId={filingId}
                onFieldUpdated={onFieldUpdated}
              />
            )}
          </div>
        </div>
      ) : (
        /* HTML view — shown when showHtml=true or when no results yet (pre-extraction states) */
        <div className="flex flex-col flex-1 min-h-0">
          {/* Status / action bar above the iframe */}
          <div className={`flex items-center gap-2 px-4 py-1.5 border-b shrink-0 ${
            showHtml
              ? 'bg-slate-50 border-slate-200'
              : status === 'ingested'
              ? 'bg-amber-50 border-amber-200'
              : status === 'needs_review'
              ? 'bg-red-50 border-red-200'
              : status === 'exported'
              ? 'bg-slate-50 border-slate-200'
              : 'bg-blue-50 border-blue-200'
          }`}>
            <span className={`text-xs font-medium flex-1 ${
              showHtml          ? 'text-slate-500' :
              status === 'ingested'      ? 'text-amber-700' :
              status === 'needs_review'  ? 'text-red-700'   :
              status === 'exported'      ? 'text-slate-500' : 'text-blue-700'
            }`}>
              {showHtml && hasResults
                ? `EDGAR filing source — ${filing.cusip || filing.accession_number}`
                : status === 'ingested'
                ? 'Raw filing preview — click Classify above to identify the PRISM model.'
                : status === 'classified'
                ? `Classified as ${filing.payout_type_id} (${(filing.classification_confidence * 100).toFixed(0)}% conf.) — click Extract to pull all PRISM fields.`
                : status === 'needs_review'
                ? 'Low-confidence classification — review the filing below, then use "Set Model" to override or click Extract.'
                : status === 'exported'
                ? 'Filing has been exported.'
                : ''}
            </span>
            {/* Back to fields button — only when we manually switched to HTML */}
            {showHtml && hasResults && (
              <button
                onClick={() => setShowHtml(false)}
                className="text-xs font-medium px-2.5 py-1 rounded border bg-white text-slate-600 border-slate-300 hover:bg-slate-50 transition-colors"
              >
                ← Back to Fields
              </button>
            )}
          </div>
          <iframe
            key={filingId}
            src={`/api/filings/${filingId}/document`}
            className="flex-1 w-full border-0"
            title="EDGAR filing preview"
            sandbox="allow-same-origin allow-scripts"
          />
        </div>
      )}
    </div>
  )
}
