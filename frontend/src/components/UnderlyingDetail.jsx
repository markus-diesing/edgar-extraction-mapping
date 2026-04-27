/**
 * UnderlyingDetail.jsx — Full detail panel for one underlying security.
 *
 * Tabs:
 *   Overview   — Pipeline flow, Tier 1 metadata (with preliminary LLM fields),
 *                and LLM token-cost summary.
 *   Review     — Tier 2 LLM-extracted fields with accept / edit / reject actions
 *                and source-excerpt column for extraction validation.
 *   Market     — Tier 3 market data (prices, series preview)
 *   10-K Source — Stored filing text slice for human validation, with direct links
 *                to the EDGAR primary document and filing index.
 *   Links      — Linked 424B2 filings
 *
 * Props:
 *   securityId  string | null  — UUID of the UnderlyingSecurity to display
 *   onChanged()                — callback when approve/archive/refetch mutates the record
 */
import { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'
import StatusBadge from './StatusBadge.jsx'

// ---------------------------------------------------------------------------
// Generic helpers
// ---------------------------------------------------------------------------

function MetaRow({ label, value, mono, preliminary }) {
  if (value == null || value === '') return null
  return (
    <div className="flex gap-2 py-0.5">
      <span className="text-slate-400 text-xs w-40 shrink-0">{label}</span>
      <span className={`text-slate-700 text-xs break-all ${mono ? 'font-mono' : 'font-medium'}`}>
        {String(value)}
        {preliminary && (
          <span className="ml-1.5 text-[10px] font-normal text-amber-600 border border-amber-300 bg-amber-50 rounded px-1 py-px">
            ⚑ preliminary
          </span>
        )}
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

const fmtTok  = (n) => n == null ? '—' : n >= 1000 ? `${(n / 1000).toFixed(0)}K` : String(n)
const fmtCost = (c) => c == null ? '—' : c < 0.001 ? '<$0.001' : `$${c.toFixed(3)}`

// ---------------------------------------------------------------------------
// Preliminary field helper
// Look up a field_result by name and return its best value + pending flag.
// ---------------------------------------------------------------------------

function getPendingField(fieldResults, fieldName) {
  const fr = (fieldResults || []).find(f => f.field_name === fieldName)
  if (!fr) return null
  const raw = fr.reviewed_value != null ? fr.reviewed_value : fr.extracted_value
  if (raw == null) return null
  const value = typeof raw === 'boolean'
    ? (raw ? 'Yes' : 'No')
    : String(raw).trim()
  if (!value) return null
  return { value, isPreliminary: fr.review_status === 'pending' }
}

// ---------------------------------------------------------------------------
// Pipeline flow
// ---------------------------------------------------------------------------

/**
 * Derive per-step pipeline status from the security record.
 *
 * Steps:  Resolve → EDGAR Fetch → LLM Extract → Review → Approved
 *
 * Status values:  ok | active | error | partial | pending | grey
 */
function getPipelineSteps(sec, fieldResults) {
  const isFetching  = sec.status === 'fetching'
  const hasError    = !!sec.fetch_error
  const resolved    = !!sec.cik
  const edgarFetched = !!sec.last_10k_accession
  const fr = fieldResults || []
  const llmDone     = fr.length > 0
  const allReviewed = llmDone && fr.every(f => f.review_status !== 'pending')
  const someReviewed = llmDone && fr.some(f => f.review_status !== 'pending')
  const approved    = sec.status === 'approved'

  // Which step is currently active (in-progress)?
  const activeStep = !isFetching ? null
    : !resolved      ? 'resolve'
    : !edgarFetched  ? 'edgar'
    : !llmDone       ? 'llm'
    : null

  const step = (id, label, ok, active, errorCondition) => ({
    id, label,
    status: ok             ? 'ok'
      : errorCondition     ? 'error'
      : active === id      ? 'active'
      : 'grey',
  })

  return [
    step('resolve', 'Resolve',
      resolved,
      activeStep,
      hasError && !resolved,
    ),
    step('edgar', 'EDGAR Fetch',
      edgarFetched,
      activeStep,
      hasError && resolved && !edgarFetched,
    ),
    step('llm', 'LLM Extract',
      llmDone,
      activeStep,
      hasError && edgarFetched && !llmDone,
    ),
    {
      id: 'review', label: 'Review',
      status: allReviewed ? 'ok'
        : someReviewed    ? 'partial'
        : llmDone         ? 'pending'
        : 'grey',
    },
    {
      id: 'approved', label: 'Approved',
      status: approved ? 'ok' : 'grey',
    },
  ]
}

const STEP_COLORS = {
  ok:      { dot: 'bg-green-500',  label: 'text-green-700',  line: 'bg-green-300' },
  partial: { dot: 'bg-amber-400',  label: 'text-amber-700',  line: 'bg-amber-200' },
  active:  { dot: 'bg-blue-500 animate-pulse', label: 'text-blue-700', line: 'bg-slate-200' },
  error:   { dot: 'bg-red-500',    label: 'text-red-700',    line: 'bg-slate-200' },
  pending: { dot: 'bg-slate-300',  label: 'text-slate-500',  line: 'bg-slate-200' },
  grey:    { dot: 'bg-slate-200',  label: 'text-slate-400',  line: 'bg-slate-100' },
}

function PipelineFlow({ sec, fieldResults }) {
  const steps = getPipelineSteps(sec, fieldResults)

  return (
    <div className="mb-4">
      <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 pb-0.5 border-b border-slate-100">
        Pipeline
      </h4>
      <div className="flex items-center gap-0">
        {steps.map((s, i) => {
          const c = STEP_COLORS[s.status] || STEP_COLORS.grey
          return (
            <div key={s.id} className="flex items-center">
              {/* Step node */}
              <div className="flex flex-col items-center gap-1">
                <div className={`w-3 h-3 rounded-full shrink-0 ${c.dot}`} title={s.status} />
                <span className={`text-[10px] font-medium whitespace-nowrap ${c.label}`}>
                  {s.label}
                </span>
              </div>
              {/* Connector line — not after last step */}
              {i < steps.length - 1 && (
                <div className={`h-0.5 w-8 mx-1 mb-3.5 shrink-0 ${c.line}`} />
              )}
            </div>
          )
        })}
      </div>
      {sec.fetch_error && (
        <div className="mt-1.5 bg-red-50 border border-red-200 rounded p-1.5 text-xs text-red-700">
          ⚠ {sec.fetch_error}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Overview tab
// ---------------------------------------------------------------------------

function OverviewTab({ sec }) {
  const fr = sec.field_results || []

  // For LLM-sourced fields: if the mirrored column is already set (reviewed),
  // show it directly.  If not, look it up from field_results (preliminary).
  const legalNameField = (() => {
    if (sec.legal_name) return { value: sec.legal_name, isPreliminary: false }
    return getPendingField(fr, 'legal_name')
  })()

  const shareClassField = (() => {
    if (sec.share_class_name) return { value: sec.share_class_name, isPreliminary: false }
    return getPendingField(fr, 'share_class_name')
  })()

  const shareTypeField = (() => {
    if (sec.share_type) return { value: sec.share_type, isPreliminary: false }
    return getPendingField(fr, 'share_type')
  })()

  const adrField = (() => {
    // adr_flag is always shown from the mirrored column (bool); only mark
    // preliminary if it hasn't been reviewed yet.
    const pending = getPendingField(fr, 'adr_flag')
    const isPreliminary = pending ? pending.isPreliminary : false
    return { value: sec.adr_flag, isPreliminary }
  })()

  return (
    <div className="p-4 overflow-y-auto scrollbar-thin h-full">
      {/* ── Pipeline flow ─────────────────────────────────────────────── */}
      <PipelineFlow sec={sec} fieldResults={fr} />

      <Section title="Identification">
        <MetaRow label="CIK"               value={sec.cik}                      mono />
        <MetaRow label="Ticker"            value={sec.ticker}                   mono />
        {/* Show all sibling tickers when this CIK has multiple listed share classes */}
        {Array.isArray(sec.all_tickers) && sec.all_tickers.length > 1 && (
          <div className="flex gap-2 py-0.5">
            <span className="text-slate-400 text-xs w-40 shrink-0">Share Classes</span>
            <span className="flex flex-wrap gap-1">
              {sec.all_tickers.map(t => (
                <span
                  key={t}
                  className={
                    t === sec.ticker
                      ? 'font-mono text-[11px] font-semibold bg-lpa-blue text-white rounded px-1.5 py-px'
                      : 'font-mono text-[11px] text-slate-600 bg-slate-100 border border-slate-200 rounded px-1.5 py-px'
                  }
                >
                  {t}
                </span>
              ))}
            </span>
          </div>
        )}
        <MetaRow label="Bloomberg Ticker"  value={sec.ticker_bb}                mono />
        <MetaRow label="Source Identifier" value={sec.source_identifier}        mono />
        <MetaRow label="Source Type"       value={sec.source_identifier_type} />
      </Section>

      <Section title="Company">
        <MetaRow label="Company Name (EDGAR)" value={sec.company_name} />
        {legalNameField && (
          <MetaRow
            label="Legal Name (Filing)"
            value={legalNameField.value}
            preliminary={legalNameField.isPreliminary}
          />
        )}
        {shareClassField && (
          <MetaRow
            label="Share Class"
            value={shareClassField.value}
            preliminary={shareClassField.isPreliminary}
          />
        )}
        {shareTypeField && (
          <MetaRow
            label="Share Type"
            value={shareTypeField.value}
            preliminary={shareTypeField.isPreliminary}
          />
        )}
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
            {adrField.value
              ? <span className="text-amber-700 bg-amber-50 border border-amber-200 rounded px-1">Yes</span>
              : <span className="text-slate-500">No</span>
            }
            {adrField.isPreliminary && (
              <span className="ml-1.5 text-[10px] font-normal text-amber-600 border border-amber-300 bg-amber-50 rounded px-1 py-px">
                ⚑ preliminary
              </span>
            )}
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
      </Section>

      {(sec.llm_input_tokens != null) && (
        <Section title="LLM Extraction Cost">
          <MetaRow
            label="Tokens"
            value={`${fmtTok(sec.llm_input_tokens)} in / ${fmtTok(sec.llm_output_tokens)} out`}
          />
          <MetaRow
            label="Estimated Cost"
            value={fmtCost(sec.llm_cost_usd)}
          />
        </Section>
      )}
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
  const [excerptExpanded, setExcerptExpanded] = useState(false)

  const displayValue = fr.reviewed_value != null ? fr.reviewed_value : fr.extracted_value
  const displayStr   = displayValue == null ? '—' : (typeof displayValue === 'boolean' ? (displayValue ? 'True' : 'False') : String(displayValue))

  const confColor = fr.confidence_score >= 0.90 ? 'text-green-600'
    : fr.confidence_score >= 0.70 ? 'text-amber-600'
    : 'text-red-600'

  const excerpt     = fr.source_excerpt || ''
  const excerptShort = excerpt.length > 80 ? excerpt.slice(0, 80) + '…' : excerpt

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
    <tr className="border-t border-slate-100 hover:bg-slate-50 align-top">
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
      <td className="py-2 px-3 text-xs text-slate-500 max-w-[220px]">
        {excerpt ? (
          <span>
            <span className="italic text-slate-400">
              "{excerptExpanded ? excerpt : excerptShort}"
            </span>
            {excerpt.length > 80 && (
              <button
                onClick={() => setExcerptExpanded(v => !v)}
                className="ml-1 text-lpa-cyan hover:underline text-[10px] font-medium"
              >
                {excerptExpanded ? 'less' : 'more'}
              </button>
            )}
          </span>
        ) : (
          <span className="text-slate-300">—</span>
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
            <th className="py-2 px-3">Source Excerpt</th>
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
        Blue values have been manually reviewed. The <em>Source Excerpt</em> column shows the verbatim
        filing text the model used — verify it matches the value before accepting.
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Market Data tab
// ---------------------------------------------------------------------------

function MarketTab({ sec }) {
  const series = Array.isArray(sec.hist_data_series) ? sec.hist_data_series : []

  // Show all rows when ≤ 6; otherwise show first 3, a gap indicator, last 3.
  // The earlier pattern with filter(Boolean) caused slice(-3) to overlap slice(0,3)
  // for series of length 4–6, producing duplicate rows.
  const previewRows = series.length <= 6
    ? series
    : [...series.slice(0, 3), { _gap: true }, ...series.slice(-3)]

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
// 10-K source text tab
// ---------------------------------------------------------------------------

/**
 * Build the two EDGAR URLs for a security.
 *   indexUrl  — filing index page (always constructible from cik + accession)
 *   docUrl    — direct HTML document (requires primary_doc filename)
 */
function makeEdgarUrls(sec) {
  if (!sec.cik || !sec.last_10k_accession) return null
  const cikNum   = sec.cik.replace(/^0+/, '')            // strip leading zeros
  const accNodash = sec.last_10k_accession.replace(/-/g, '')
  const base     = `https://www.sec.gov/Archives/edgar/data/${cikNum}/${accNodash}`
  return {
    indexUrl: `${base}/`,
    docUrl:   sec.last_10k_primary_doc ? `${base}/${sec.last_10k_primary_doc}` : null,
  }
}

function SourceTab({ sec }) {
  const urls = makeEdgarUrls(sec)
  const text = sec.last_10k_text || null

  return (
    <div className="flex flex-col h-full">
      {/* ── Links bar ─────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-slate-200 bg-slate-50 shrink-0 flex-wrap">
        <span className="text-xs text-slate-500 font-medium">EDGAR:</span>
        {urls ? (
          <>
            {urls.docUrl && (
              <a
                href={urls.docUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-xs text-lpa-cyan hover:text-lpa-blue font-medium transition-colors"
              >
                📄 Open 10-K Document ↗
              </a>
            )}
            <a
              href={urls.indexUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700 font-medium transition-colors"
            >
              🗂 Filing Index ↗
            </a>
          </>
        ) : (
          <span className="text-xs text-slate-400">
            No accession number — links unavailable
          </span>
        )}
        {text && (
          <span className="ml-auto text-[10px] text-slate-400">
            {text.length.toLocaleString()} chars · first {(text.length / 1000).toFixed(0)}K of 10-K text
          </span>
        )}
      </div>

      {/* ── Text viewer ───────────────────────────────────────────────── */}
      {text ? (
        <div className="flex-1 min-h-0 overflow-auto scrollbar-thin p-4 bg-white">
          <pre className="text-[11px] font-mono text-slate-700 whitespace-pre-wrap leading-relaxed">
            {text}
          </pre>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center h-full gap-2 text-sm text-slate-400 p-8 text-center">
          <span className="text-2xl">📄</span>
          <p>No source text stored for this security.</p>
          <p className="text-xs text-slate-400 max-w-xs">
            Source text is saved during ingest when LLM extraction is enabled.
            Re-fetch this security to populate it.
          </p>
        </div>
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

  // Reset to Overview whenever the user selects a different security so they
  // don't land on, e.g., the Market tab from a previous selection.
  useEffect(() => { setTab('overview') }, [securityId])

  // Auto-poll while a background fetch job is in progress.
  // Fires every 3 s; clears itself as soon as status leaves 'fetching'.
  useEffect(() => {
    if (!sec || sec.status !== 'fetching') return
    const timer = setInterval(load, 3_000)
    return () => clearInterval(timer)
  }, [sec?.status, load])

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

  // Count pending review fields for the tab label
  const pendingCount = (sec.field_results || []).filter(f => f.review_status === 'pending').length

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
            <p className="text-sm text-slate-600 mt-0.5 truncate">
              {sec.legal_name || sec.company_name}
            </p>
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
              label={sec.status === 'fetching' ? '⟳ Fetching…' : 'Re-fetch'}
              onClick={doRefetch}
              disabled={!!busy || sec.status === 'fetching'}
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

      {/* ── Fetching banner ─────────────────────────────────────────────────── */}
      {sec.status === 'fetching' && (
        <div className="flex items-center gap-2 px-5 py-1.5 bg-blue-50 border-b border-blue-200 shrink-0 text-xs text-blue-700 font-medium">
          <span className="inline-block w-3 h-3 rounded-full bg-blue-500 animate-pulse shrink-0" />
          Background fetch in progress — results will appear automatically when complete…
        </div>
      )}

      {/* ── Tabs ────────────────────────────────────────────────────────────── */}
      <div className="flex border-b border-slate-200 bg-white shrink-0 px-4">
        {[
          ['overview', 'Overview'],
          ['review',   `Review${pendingCount > 0 ? ` (${pendingCount} pending)` : ` (${(sec.field_results || []).length})`}`],
          ['market',   'Market Data'],
          ['source',   '10-K Source'],
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
        {tab === 'source'   && <SourceTab   sec={sec} />}
        {tab === 'links'    && <LinksTab    sec={sec} onUpdate={load} />}
      </div>
    </div>
  )
}
