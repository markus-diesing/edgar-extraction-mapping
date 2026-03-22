/**
 * AdminUsage.jsx
 *
 * Cost & Usage analytics tab in the Admin panel.
 *
 * Sections:
 *   1. Summary KPI tiles
 *   2. Spend over time (stacked bar chart — Day / Week / Month)
 *   3. Cost by process step
 *   4. Cost by PRISM product type + by issuer
 *   5. Unit economics
 *   6. Prompt caching panel
 *   7. Projection
 *   8. Model comparison calculator
 *   9. Model configuration (active model selector)
 *  10. Commercial signals (stage-2 overhead, efficiency trend)
 *
 * Data sources:
 *   GET /api/admin/usage/summary
 *   GET /api/admin/usage/timeline?granularity=week
 */
import { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

const fmt$ = (v, decimals = 4) =>
  v == null ? '—' : `$${Number(v).toFixed(decimals)}`

const fmtPct = (v) =>
  v == null ? '—' : `${Number(v).toFixed(1)}%`

const fmtNum = (v) =>
  v == null ? '—' : Number(v).toLocaleString()

const fmtK = (v) =>
  v == null ? '—' : v >= 1000 ? `${(v / 1000).toFixed(1)}K` : String(v)


// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

function Section({ title, children }) {
  return (
    <div className="mb-8">
      <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">{title}</h3>
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 1. KPI tiles
// ---------------------------------------------------------------------------

function KpiTile({ label, value, sub, color = 'text-slate-800' }) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg px-4 py-3 flex flex-col gap-0.5">
      <span className="text-xs text-slate-400">{label}</span>
      <span className={`text-xl font-bold ${color}`}>{value}</span>
      {sub && <span className="text-xs text-slate-400">{sub}</span>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 2. Timeline bar chart
// ---------------------------------------------------------------------------

function TimelineChart({ buckets }) {
  if (!buckets?.length) return <p className="text-slate-400 text-xs">No data yet.</p>

  const maxCost = Math.max(...buckets.map(b => b.total_cost_usd), 0.000001)

  return (
    <div className="space-y-1.5">
      {buckets.map(b => (
        <div key={b.label} className="flex items-center gap-2">
          <span className="text-xs text-slate-400 font-mono w-20 shrink-0 text-right">{b.label}</span>
          {/* Stacked bar */}
          <div className="flex-1 h-5 bg-slate-100 rounded overflow-hidden flex">
            <div
              className="bg-violet-400 h-full"
              style={{ width: `${(b.classify_cost_usd / maxCost) * 100}%` }}
              title={`Classify $${b.classify_cost_usd.toFixed(4)}`}
            />
            <div
              className="bg-emerald-400 h-full"
              style={{ width: `${(b.extract_cost_usd / maxCost) * 100}%` }}
              title={`Extract $${b.extract_cost_usd.toFixed(4)}`}
            />
            {b.cache_savings_usd > 0 && (
              <div
                className="bg-blue-200 h-full"
                style={{ width: `${(b.cache_savings_usd / maxCost) * 100}%` }}
                title={`Cache savings $${b.cache_savings_usd.toFixed(4)}`}
              />
            )}
          </div>
          <span className="text-xs text-slate-600 font-mono w-16 text-right">
            {fmt$(b.total_cost_usd, 4)}
          </span>
          <span className="text-xs text-slate-400 w-12 text-right">{b.calls} calls</span>
        </div>
      ))}
      {/* Legend */}
      <div className="flex gap-4 mt-2 text-xs text-slate-400">
        <span className="flex items-center gap-1"><span className="w-3 h-3 bg-violet-400 rounded-sm inline-block"/>Classify</span>
        <span className="flex items-center gap-1"><span className="w-3 h-3 bg-emerald-400 rounded-sm inline-block"/>Extract</span>
        <span className="flex items-center gap-1"><span className="w-3 h-3 bg-blue-200 rounded-sm inline-block"/>Cache savings</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 3. Cost by process step
// ---------------------------------------------------------------------------

function StepTable({ steps, totalCost }) {
  if (!steps?.length) return <p className="text-slate-400 text-xs">No data.</p>
  const maxCost = Math.max(...steps.map(s => s.cost_usd), 0.000001)

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-slate-100 text-left text-slate-500">
            <th className="px-2 py-1.5 font-semibold border border-slate-200 w-64">Step</th>
            <th className="px-2 py-1.5 font-semibold border border-slate-200 text-right w-14">Calls</th>
            <th className="px-2 py-1.5 font-semibold border border-slate-200 text-right w-20">Input tokens</th>
            <th className="px-2 py-1.5 font-semibold border border-slate-200 text-right w-20">Output tokens</th>
            <th className="px-2 py-1.5 font-semibold border border-slate-200 text-right w-24">Cache saved</th>
            <th className="px-2 py-1.5 font-semibold border border-slate-200 w-48">Cost</th>
            <th className="px-2 py-1.5 font-semibold border border-slate-200 text-right w-16">% total</th>
            <th className="px-2 py-1.5 font-semibold border border-slate-200 text-right w-20">Avg/call</th>
          </tr>
        </thead>
        <tbody>
          {steps.map(s => (
            <tr
              key={s.call_type}
              className={`border-b border-slate-100 hover:bg-slate-50 ${
                s.call_type === 'classify_stage2' ? 'bg-amber-50' : ''
              }`}
            >
              <td className="px-2 py-1.5 border-r border-slate-200 font-medium text-slate-700">
                {s.label}
                {s.call_type === 'classify_stage2' && (
                  <span className="ml-1.5 text-xs text-amber-600 font-normal">(overhead)</span>
                )}
              </td>
              <td className="px-2 py-1.5 border-r border-slate-200 text-right text-slate-600">{s.calls}</td>
              <td className="px-2 py-1.5 border-r border-slate-200 text-right text-slate-500 font-mono">{fmtK(s.input_tokens)}</td>
              <td className="px-2 py-1.5 border-r border-slate-200 text-right text-slate-500 font-mono">{fmtK(s.output_tokens)}</td>
              <td className="px-2 py-1.5 border-r border-slate-200 text-right text-blue-600 font-mono">
                {s.cache_savings_usd > 0 ? fmt$(s.cache_savings_usd, 4) : '—'}
              </td>
              {/* Cost bar */}
              <td className="px-2 py-1.5 border-r border-slate-200">
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-slate-500 rounded-full"
                      style={{ width: `${(s.cost_usd / maxCost) * 100}%` }}
                    />
                  </div>
                  <span className="font-mono text-slate-700 w-16 text-right">{fmt$(s.cost_usd, 4)}</span>
                </div>
              </td>
              <td className="px-2 py-1.5 border-r border-slate-200 text-right text-slate-500">{s.pct_of_total}%</td>
              <td className="px-2 py-1.5 text-right text-slate-500 font-mono">{fmt$(s.avg_cost_per_call, 5)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 4. Small distribution table (product type + issuer)
// ---------------------------------------------------------------------------

function DistTable({ rows, nameKey, label }) {
  if (!rows?.length) return <p className="text-slate-400 text-xs">No data.</p>
  const maxCost = Math.max(...rows.map(r => r.cost_usd), 0.000001)
  return (
    <table className="w-full text-xs border-collapse">
      <thead>
        <tr className="bg-slate-100 text-left text-slate-500">
          <th className="px-2 py-1.5 border border-slate-200 font-semibold">{label}</th>
          <th className="px-2 py-1.5 border border-slate-200 font-semibold w-14 text-right">Calls</th>
          <th className="px-2 py-1.5 border border-slate-200 font-semibold w-40">Cost</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={r[nameKey]} className="border-b border-slate-100 hover:bg-slate-50">
            <td className="px-2 py-1 border-r border-slate-200 text-slate-700 font-medium">{r[nameKey]}</td>
            <td className="px-2 py-1 border-r border-slate-200 text-right text-slate-500">{r.calls}</td>
            <td className="px-2 py-1">
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div className="h-full bg-slate-400 rounded-full" style={{ width: `${(r.cost_usd / maxCost) * 100}%` }} />
                </div>
                <span className="font-mono w-16 text-right text-slate-600">{fmt$(r.cost_usd, 4)}</span>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------------------
// 5. Unit economics grid
// ---------------------------------------------------------------------------

function UnitEcon({ ue }) {
  if (!ue) return null
  const metrics = [
    { label: 'Cost per filing',     value: fmt$(ue.cost_per_filing,      4), note: null },
    { label: 'Cost per field found', value: fmt$(ue.cost_per_field_found, 5), note: null },
    { label: 'Avg input tokens / filing', value: fmtNum(ue.avg_input_per_filing), note: 'tokens' },
    { label: 'Output / input ratio', value: fmtPct(ue.output_input_ratio_pct), note: 'lower = Claude is concise' },
    { label: 'Classify overhead',   value: fmtPct(ue.classify_overhead_pct), note: 'of total spend' },
    { label: 'Stage 2 overhead',    value: fmtPct(ue.stage2_overhead_pct),   note: 'of classify spend' },
  ]
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
      {metrics.map(m => (
        <div key={m.label} className="bg-slate-50 border border-slate-200 rounded px-3 py-2">
          <p className="text-xs text-slate-400">{m.label}</p>
          <p className="text-base font-bold text-slate-800 mt-0.5">{m.value}</p>
          {m.note && <p className="text-xs text-slate-400 mt-0.5">{m.note}</p>}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 6. Prompt caching panel
// ---------------------------------------------------------------------------

function CachingPanel({ ue }) {
  if (!ue) return null
  const hasCache = (ue.total_cache_read_tokens || 0) > 0 || (ue.total_cache_write_tokens || 0) > 0

  if (!hasCache) {
    return (
      <div className="bg-blue-50 border border-blue-200 rounded p-4 text-xs text-blue-700 space-y-1">
        <p className="font-semibold">Prompt caching not yet active for existing records</p>
        <p>
          Cache tokens will start accumulating on the next batch run. Filings processed within
          the same 5-minute window that share the same issuer and PRISM model will hit the cache.
        </p>
        <p className="text-blue-500 mt-1">
          Estimated saving on a 10-filing same-issuer batch: ~$0.014 per filing from the 2nd filing onwards.
        </p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {[
        { label: 'Cache hit rate',       value: fmtPct(ue.cache_hit_rate_pct),      color: 'text-blue-700' },
        { label: 'Total cache reads',    value: fmtK(ue.total_cache_read_tokens),   color: 'text-slate-800' },
        { label: 'Total cache writes',   value: fmtK(ue.total_cache_write_tokens),  color: 'text-slate-800' },
        { label: 'Total savings',        value: fmt$(ue.cache_savings_usd, 4),       color: 'text-emerald-700' },
      ].map(m => (
        <div key={m.label} className="bg-blue-50 border border-blue-200 rounded px-3 py-2">
          <p className="text-xs text-slate-500">{m.label}</p>
          <p className={`text-lg font-bold mt-0.5 ${m.color}`}>{m.value}</p>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 7. Projection
// ---------------------------------------------------------------------------

function ProjectionPanel({ proj }) {
  if (!proj) return null
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {[
        { label: 'Monthly run rate (last 30 d)', value: fmt$(proj.monthly_run_rate_usd, 2), sub: `${proj.month_filings_processed || 0} filings processed` },
        { label: 'Per 100 filings',              value: fmt$(proj.per_100_filings_usd,  2), sub: 'at current unit cost' },
        { label: 'Annual estimate',              value: fmt$(proj.annual_estimate_usd,  2), sub: 'extrapolated from last 30 d' },
        { label: 'Batch API (50% off)',          value: proj.monthly_run_rate_usd != null ? fmt$(proj.monthly_run_rate_usd * 0.5, 2) : '—', sub: 'estimate — Anthropic batch pricing' },
      ].map(m => (
        <div key={m.label} className="bg-slate-50 border border-slate-200 rounded px-3 py-2">
          <p className="text-xs text-slate-400">{m.label}</p>
          <p className="text-base font-bold text-slate-800 mt-0.5">{m.value}</p>
          {m.sub && <p className="text-xs text-slate-400 mt-0.5">{m.sub}</p>}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 8. Model comparison
// ---------------------------------------------------------------------------

function ModelComparison({ models, activeModel }) {
  if (!models?.length) return null
  return (
    <table className="w-full text-xs border-collapse">
      <thead>
        <tr className="bg-slate-100 text-left text-slate-500">
          <th className="px-2 py-1.5 border border-slate-200 font-semibold">Model</th>
          <th className="px-2 py-1.5 border border-slate-200 font-semibold text-right">Est. corpus cost</th>
          <th className="px-2 py-1.5 border border-slate-200 font-semibold text-right">vs current</th>
        </tr>
      </thead>
      <tbody>
        {models.map(m => (
          <tr key={m.model_id} className={`border-b border-slate-100 ${m.model_id === activeModel ? 'bg-blue-50' : 'hover:bg-slate-50'}`}>
            <td className="px-2 py-1.5 border-r border-slate-200 text-slate-700">
              {m.display_name}
              {m.model_id === activeModel && (
                <span className="ml-2 text-blue-600 font-semibold">(active)</span>
              )}
            </td>
            <td className="px-2 py-1.5 border-r border-slate-200 text-right font-mono text-slate-600">
              {fmt$(m.est_cost_usd, 4)}
            </td>
            <td className={`px-2 py-1.5 text-right font-mono ${
              m.delta_usd < -0.0001 ? 'text-emerald-600' : m.delta_usd > 0.0001 ? 'text-red-600' : 'text-slate-400'
            }`}>
              {m.delta_usd === 0 || Math.abs(m.delta_usd) < 0.0001
                ? 'same'
                : `${m.delta_usd > 0 ? '+' : ''}${fmt$(m.delta_usd, 4)} (${m.delta_pct > 0 ? '+' : ''}${m.delta_pct}%)`}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------------------
// 9. Model configuration card
// ---------------------------------------------------------------------------

function ModelConfig({ availableModels, activeModel, onModelChanged }) {
  const [selected, setSelected] = useState(activeModel || '')
  const [saving,   setSaving]   = useState(false)
  const [msg,      setMsg]      = useState('')

  // Sync when activeModel prop changes (e.g. after summary refresh)
  useEffect(() => { setSelected(activeModel || '') }, [activeModel])

  const selectedInfo = availableModels?.find(m => m.model_id === selected)

  const apply = async () => {
    if (!selected || selected === activeModel) return
    setSaving(true)
    setMsg('')
    try {
      await api.updateSettings({ claude_model: selected })
      setMsg(`✓ Active model changed to ${selected}`)
      onModelChanged?.()
      setTimeout(() => setMsg(''), 4000)
    } catch (e) {
      setMsg(`Error: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4 max-w-xl">
      <p className="text-xs text-slate-400 mb-3">
        Changes take effect on the next classify/extract call — no server restart required.
      </p>

      <div className="space-y-3">
        <div>
          <label className="block text-xs font-semibold text-slate-600 mb-1">Active Claude model</label>
          <div className="flex gap-2">
            <select
              value={selected}
              onChange={e => setSelected(e.target.value)}
              className="flex-1 text-sm border border-slate-200 rounded px-2 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-400"
            >
              {(availableModels || []).map(m => (
                <option key={m.model_id} value={m.model_id}>
                  {m.display_name}
                </option>
              ))}
            </select>
            <button
              onClick={apply}
              disabled={saving || selected === activeModel}
              className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded transition-colors disabled:opacity-40"
            >
              {saving ? 'Applying…' : 'Apply'}
            </button>
          </div>
        </div>

        {/* Pricing details for selected model */}
        {selectedInfo && (
          <div className="bg-slate-50 border border-slate-200 rounded p-3 text-xs space-y-1 text-slate-600">
            <div className="flex gap-6 flex-wrap">
              <span>Input: <strong>${selectedInfo.input_price_per_m}/M tokens</strong></span>
              <span>Output: <strong>${selectedInfo.output_price_per_m}/M tokens</strong></span>
              <span>Cache write: <strong>${selectedInfo.cache_write_per_m}/M</strong></span>
              <span>Cache read: <strong>${selectedInfo.cache_read_per_m}/M</strong></span>
              <span>Context: <strong>{fmtNum(selectedInfo.context_tokens)} tokens</strong></span>
            </div>
            {selectedInfo.note && (
              <p className="text-slate-400 italic">{selectedInfo.note}</p>
            )}
          </div>
        )}
      </div>

      {msg && (
        <p className={`mt-2 text-xs font-medium ${msg.startsWith('Error') ? 'text-red-600' : 'text-emerald-600'}`}>
          {msg}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 10. Commercial signals
// ---------------------------------------------------------------------------

function CommercialSignals({ ue, summary }) {
  if (!ue) return null

  // Efficiency trend text — compare first vs last 10 filings' avg cost
  // We compute this from by_step data (all filings blended) — an approximation.
  const stage2PctOfTotal = ue.stage2_overhead_pct * (ue.classify_overhead_pct / 100)

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {/* Stage 2 overhead indicator */}
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
        <p className="text-xs font-semibold text-amber-800 mb-1">Stage 2 classification overhead</p>
        <p className="text-2xl font-bold text-amber-700">{fmtPct(ue.stage2_overhead_pct)}</p>
        <p className="text-xs text-amber-600 mt-1">of classify spend — {fmt$(ue.stage2_cost_usd, 4)} total</p>
        <p className="text-xs text-slate-500 mt-2">
          Stage 2 triggers on low-confidence stage 1 results. Reducing this requires
          stronger classification prompts or better issuer hints coverage.
        </p>
      </div>

      {/* Output/input ratio */}
      <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
        <p className="text-xs font-semibold text-slate-600 mb-1">Output / input token ratio</p>
        <p className="text-2xl font-bold text-slate-800">{fmtPct(ue.output_input_ratio_pct)}</p>
        <p className="text-xs text-slate-500 mt-1">
          Output tokens cost 5× input. This ratio measures verbosity — a sudden spike
          may indicate Claude returning more explanation than structured data.
        </p>
        <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
          <span>Input: {fmtK(summary?.total_in)} tokens</span>
          <span>·</span>
          <span>Output: {fmtK(summary?.total_out)} tokens</span>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AdminUsage() {
  const [summary,     setSummary]     = useState(null)
  const [timeline,    setTimeline]    = useState(null)
  const [granularity, setGranularity] = useState('week')
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState('')

  const loadSummary = useCallback(async () => {
    try {
      const data = await api.adminUsageSummary()
      setSummary(data)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  const loadTimeline = useCallback(async () => {
    try {
      const data = await api.adminUsageTimeline(granularity)
      setTimeline(data)
    } catch (e) {
      // non-fatal — just leave timeline empty
    }
  }, [granularity])

  useEffect(() => {
    setLoading(true)
    Promise.all([loadSummary(), loadTimeline()]).finally(() => setLoading(false))
  }, [loadSummary, loadTimeline])

  if (loading) {
    return <div className="flex items-center justify-center h-full text-slate-400 text-sm">Loading…</div>
  }
  if (error) {
    return <div className="flex items-center justify-center h-full text-red-400 text-sm">{error}</div>
  }
  if (!summary) return null

  const ue = summary.unit_economics

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="p-6 max-w-5xl space-y-0">

        {/* ── 1. KPI tiles ── */}
        <Section title="Overview">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <KpiTile label="Total spend"       value={fmt$(summary.total_cost_usd, 2)} color="text-slate-900" />
            <KpiTile label="Last 7 days"       value={fmt$(summary.week_cost_usd,  2)} />
            <KpiTile label="Last 30 days"      value={fmt$(summary.month_cost_usd, 2)} />
            <KpiTile label="Total API calls"   value={fmtNum(summary.total_calls)}     sub="across all filings" />
            <KpiTile label="Filings processed" value={fmtNum(summary.total_filings)}   sub="distinct" />
          </div>
        </Section>

        <hr className="border-slate-100 mb-6" />

        {/* ── 2. Timeline ── */}
        <Section title="Spend over time">
          <div className="flex gap-1 mb-3">
            {['day', 'week', 'month'].map(g => (
              <button
                key={g}
                onClick={() => setGranularity(g)}
                className={`text-xs px-2.5 py-1 rounded border transition-colors capitalize ${
                  granularity === g
                    ? 'bg-slate-700 text-white border-slate-700'
                    : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                }`}
              >
                {g}
              </button>
            ))}
          </div>
          <TimelineChart buckets={timeline?.buckets} />
        </Section>

        <hr className="border-slate-100 mb-6" />

        {/* ── 3. Cost by process step ── */}
        <Section title="Cost by process step">
          <StepTable steps={summary.by_step} totalCost={summary.total_cost_usd} />
        </Section>

        <hr className="border-slate-100 mb-6" />

        {/* ── 4. By product type + by issuer ── */}
        <Section title="Cost distribution">
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div>
              <p className="text-xs font-medium text-slate-500 mb-2">By PRISM product type</p>
              <DistTable rows={summary.by_payout_type} nameKey="payout_type_id" label="Product type" />
            </div>
            <div>
              <p className="text-xs font-medium text-slate-500 mb-2">By issuer</p>
              <DistTable rows={summary.by_issuer} nameKey="issuer_name" label="Issuer" />
            </div>
          </div>
        </Section>

        <hr className="border-slate-100 mb-6" />

        {/* ── 5. Unit economics ── */}
        <Section title="Unit economics">
          <UnitEcon ue={ue} />
        </Section>

        <hr className="border-slate-100 mb-6" />

        {/* ── 6. Prompt caching ── */}
        <Section title="Prompt caching">
          <CachingPanel ue={ue} />
        </Section>

        <hr className="border-slate-100 mb-6" />

        {/* ── 7. Projection ── */}
        <Section title="Projections">
          <ProjectionPanel proj={summary.projection} />
        </Section>

        <hr className="border-slate-100 mb-6" />

        {/* ── 8. Model comparison ── */}
        <Section title="Model comparison — corpus replay cost">
          <p className="text-xs text-slate-400 mb-3">
            Estimated cost if all historical calls had been made on each model.
            All three Sonnets currently share the same pricing — delta will be non-zero when models diverge.
          </p>
          <ModelComparison models={summary.model_comparison} activeModel={summary.active_model} />
        </Section>

        <hr className="border-slate-100 mb-6" />

        {/* ── 9. Model configuration ── */}
        <Section title="Model configuration">
          <ModelConfig
            availableModels={summary.available_models}
            activeModel={summary.active_model}
            onModelChanged={loadSummary}
          />
        </Section>

        <hr className="border-slate-100 mb-6" />

        {/* ── 10. Commercial signals ── */}
        <Section title="Commercial signals">
          <CommercialSignals
            ue={ue}
            summary={{
              total_in:  summary.by_step?.reduce((a, s) => a + s.input_tokens,  0),
              total_out: summary.by_step?.reduce((a, s) => a + s.output_tokens, 0),
            }}
          />
        </Section>

      </div>
    </div>
  )
}
