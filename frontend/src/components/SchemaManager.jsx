import { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'

// ── Severity badge ────────────────────────────────────────────────────────────
const SEV = {
  breaking: { label: 'Breaking', cls: 'bg-red-100 text-red-700 border-red-200' },
  caution:  { label: 'Caution',  cls: 'bg-amber-100 text-amber-700 border-amber-200' },
  safe:     { label: 'Safe',     cls: 'bg-green-100 text-green-700 border-green-200' },
}
function SevBadge({ severity, small }) {
  const s = SEV[severity] || SEV.safe
  return (
    <span className={`inline-flex items-center border rounded px-1.5 py-0.5 font-semibold ${small ? 'text-[10px]' : 'text-xs'} ${s.cls}`}>
      {s.label}
    </span>
  )
}

// ── Change type label ─────────────────────────────────────────────────────────
const CHANGE_LABEL = {
  added:           '+ added',
  removed:         '− removed',
  type_changed:    '⚡ type changed',
  enum_added:      '+ enum values',
  enum_removed:    '− enum values',
  required_added:  '! now required',
  required_removed:'~ now optional',
  desc_changed:    '~ description',
}

// ── Summary chips ─────────────────────────────────────────────────────────────
function SummaryChips({ summary }) {
  const chips = [
    { label: `${summary.breaking} breaking`, show: summary.breaking > 0, cls: 'bg-red-50 text-red-700 border-red-200' },
    { label: `${summary.caution} caution`,   show: summary.caution > 0,  cls: 'bg-amber-50 text-amber-700 border-amber-200' },
    { label: `${summary.safe} safe`,         show: summary.safe > 0,     cls: 'bg-green-50 text-green-700 border-green-200' },
    { label: `${summary.models_added} new model${summary.models_added !== 1 ? 's' : ''}`,   show: summary.models_added > 0,   cls: 'bg-blue-50 text-blue-700 border-blue-200' },
    { label: `${summary.models_removed} model removed`,                                      show: summary.models_removed > 0, cls: 'bg-red-50 text-red-700 border-red-200' },
    { label: `${summary.fields_added} field${summary.fields_added !== 1 ? 's' : ''} added`,  show: summary.fields_added > 0,  cls: 'bg-slate-50 text-slate-600 border-slate-200' },
    { label: `${summary.fields_removed} field${summary.fields_removed !== 1 ? 's' : ''} removed`, show: summary.fields_removed > 0, cls: 'bg-red-50 text-red-700 border-red-200' },
    { label: `${summary.defs_added} $def added`,   show: summary.defs_added > 0,   cls: 'bg-violet-50 text-violet-700 border-violet-200' },
    { label: `${summary.defs_removed} $def removed`, show: summary.defs_removed > 0, cls: 'bg-red-50 text-red-700 border-red-200' },
  ].filter(c => c.show)

  if (chips.length === 0) return (
    <span className="text-xs text-green-600 font-medium">✅ No changes detected</span>
  )

  return (
    <div className="flex flex-wrap gap-1.5">
      {chips.map(c => (
        <span key={c.label} className={`text-xs border rounded px-2 py-0.5 font-medium ${c.cls}`}>{c.label}</span>
      ))}
    </div>
  )
}

// ── Impact panel ─────────────────────────────────────────────────────────────
function ImpactPanel({ impact }) {
  const hasAny = impact.parsers_at_risk?.length || impact.label_map_entries_at_risk?.length ||
                 impact.issuer_yaml_at_risk?.length || impact.db_rows_affected > 0 ||
                 impact.active_models_affected?.length

  if (!hasAny) return (
    <div className="text-xs text-green-600 font-medium">✅ No impact on parsers, label maps, or existing DB data</div>
  )

  return (
    <div className="space-y-2 text-xs">
      {impact.active_models_affected?.length > 0 && (
        <div className="p-2 bg-red-50 border border-red-200 rounded">
          <span className="font-semibold text-red-700">Active models affected: </span>
          {impact.active_models_affected.map(m => (
            <span key={m} className="inline-block mr-2 font-mono text-red-700">
              {m} ({impact.active_model_filing_counts?.[m] ?? '?'} filings)
            </span>
          ))}
        </div>
      )}
      {impact.db_rows_affected > 0 && (
        <div className="p-2 bg-red-50 border border-red-200 rounded">
          <span className="font-semibold text-red-700">DB rows affected: </span>
          <span className="text-red-700">{impact.db_rows_affected.toLocaleString()} FieldResult rows reference changed/removed paths</span>
        </div>
      )}
      {impact.parsers_at_risk?.length > 0 && (
        <div className="p-2 bg-amber-50 border border-amber-200 rounded">
          <span className="font-semibold text-amber-700">Parsers at risk: </span>
          {impact.parsers_at_risk.map(p => (
            <code key={p} className="mr-2 text-amber-700">{p}</code>
          ))}
        </div>
      )}
      {impact.label_map_entries_at_risk?.length > 0 && (
        <div className="p-2 bg-amber-50 border border-amber-200 rounded">
          <span className="font-semibold text-amber-700">Label map entries at risk ({impact.label_map_entries_at_risk.length}): </span>
          <span className="text-amber-700">{impact.label_map_entries_at_risk.slice(0,6).join(', ')}{impact.label_map_entries_at_risk.length > 6 ? ` +${impact.label_map_entries_at_risk.length - 6} more` : ''}</span>
        </div>
      )}
      {impact.issuer_yaml_at_risk?.length > 0 && (
        <div className="p-2 bg-amber-50 border border-amber-200 rounded">
          <span className="font-semibold text-amber-700">Issuer YAMLs at risk: </span>
          <span className="text-amber-700">{impact.issuer_yaml_at_risk.join(', ')}</span>
        </div>
      )}
    </div>
  )
}

// ── Field change row ──────────────────────────────────────────────────────────
function FieldChangeRow({ fc }) {
  const [open, setOpen] = useState(false)
  const hasDetail = fc.old_description || fc.new_description || fc.old_type ||
                    fc.removed_values?.length || fc.added_values?.length ||
                    fc.has_parser || fc.label_map_entries?.length ||
                    fc.issuer_yaml_entries?.length || fc.db_row_count > 0 ||
                    fc.is_dynamic

  return (
    <div className="border-b border-slate-100 last:border-0">
      <div
        className={`flex items-center gap-2 px-3 py-1.5 text-xs ${hasDetail ? 'cursor-pointer hover:bg-slate-50' : ''}`}
        onClick={() => hasDetail && setOpen(o => !o)}
      >
        <SevBadge severity={fc.severity} small />
        <code className="font-mono text-slate-700 flex-1">{fc.path}</code>
        <span className="text-slate-400 whitespace-nowrap">{CHANGE_LABEL[fc.change] || fc.change}</span>
        {fc.new_type && <span className="text-slate-400">[{fc.new_type}]</span>}
        {fc.old_type && !fc.new_type && <span className="text-slate-400">[{fc.old_type}]</span>}
        {fc.new_required && <span className="text-xs text-orange-600 font-semibold">required</span>}
        {fc.is_dynamic && <span className="text-xs text-violet-500">dynamic keys</span>}
        {hasDetail && <span className="text-slate-300">{open ? '▲' : '▼'}</span>}
      </div>
      {open && hasDetail && (
        <div className="px-4 pb-2 pt-1 bg-slate-50 text-xs space-y-1 text-slate-600">
          {fc.old_type && fc.new_type && fc.old_type !== fc.new_type && (
            <div><span className="font-semibold">Type:</span> <code>{fc.old_type}</code> → <code>{fc.new_type}</code></div>
          )}
          {fc.removed_values?.length > 0 && (
            <div><span className="font-semibold text-red-600">Removed enum values:</span> {fc.removed_values.join(', ')}</div>
          )}
          {fc.added_values?.length > 0 && (
            <div><span className="font-semibold text-green-600">Added enum values:</span> {fc.added_values.join(', ')}</div>
          )}
          {fc.old_description && <div><span className="font-semibold">Old desc:</span> {fc.old_description}</div>}
          {fc.new_description && fc.new_description !== fc.old_description && (
            <div><span className="font-semibold">New desc:</span> {fc.new_description}</div>
          )}
          {fc.is_dynamic && (
            <div className="text-violet-600">⚠ Uses <code>patternProperties</code> — dynamic key names, cannot register fixed field paths. Handle via LLM prompt only.</div>
          )}
          <div className="flex flex-wrap gap-3 pt-0.5">
            {fc.has_parser && <span className="text-amber-600 font-semibold">⚙ Has parser in FIELD_PARSERS</span>}
            {fc.label_map_entries?.length > 0 && (
              <span className="text-amber-600">🏷 {fc.label_map_entries.length} label map entr{fc.label_map_entries.length === 1 ? 'y' : 'ies'}: {fc.label_map_entries.slice(0,3).join(', ')}{fc.label_map_entries.length > 3 ? '…' : ''}</span>
            )}
            {fc.issuer_yaml_entries?.length > 0 && (
              <span className="text-amber-600">📄 Issuer YAMLs: {fc.issuer_yaml_entries.join(', ')}</span>
            )}
            {fc.db_row_count > 0 && (
              <span className="text-red-600">🗄 {fc.db_row_count.toLocaleString()} DB rows affected</span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Model diff block ──────────────────────────────────────────────────────────
function ModelDiffBlock({ mc }) {
  const [open, setOpen] = useState(mc.severity === 'breaking' || mc.status === 'new')

  const count = mc.field_changes?.length || 0
  const renames = mc.rename_suggestions?.length || 0

  return (
    <div className="border border-slate-200 rounded mb-2">
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-slate-50 bg-white rounded"
        onClick={() => setOpen(o => !o)}
      >
        <SevBadge severity={mc.severity} />
        <code className="font-mono text-sm font-semibold text-slate-700 flex-1">{mc.model}</code>
        {mc.status === 'new'     && <span className="text-xs text-blue-600 font-semibold">NEW MODEL</span>}
        {mc.status === 'removed' && <span className="text-xs text-red-600 font-semibold">REMOVED</span>}
        {count > 0   && <span className="text-xs text-slate-400">{count} field change{count !== 1 ? 's' : ''}</span>}
        {renames > 0 && <span className="text-xs text-blue-400">{renames} rename suggestion{renames !== 1 ? 's' : ''}</span>}
        <span className="text-slate-300">{open ? '▲' : '▼'}</span>
      </div>
      {open && (
        <div className="border-t border-slate-100">
          {mc.rename_suggestions?.length > 0 && (
            <div className="px-3 py-2 bg-blue-50 border-b border-blue-100">
              <div className="text-xs font-semibold text-blue-700 mb-1">Likely renames (heuristic — verify before activating):</div>
              {mc.rename_suggestions.map(r => (
                <div key={r.old_path} className="text-xs font-mono text-blue-700 flex items-center gap-1.5 mb-0.5">
                  <code className="text-red-500">{r.old_path}</code>
                  <span>→</span>
                  <code className="text-green-600">{r.new_path}</code>
                  <span className="text-blue-400 font-sans">({(r.confidence * 100).toFixed(0)}% confidence)</span>
                </div>
              ))}
            </div>
          )}
          {mc.field_changes?.length > 0
            ? mc.field_changes.map((fc, i) => <FieldChangeRow key={i} fc={fc} />)
            : <div className="px-3 py-2 text-xs text-slate-400">No field-level changes</div>
          }
        </div>
      )}
    </div>
  )
}

// ── Diff view ─────────────────────────────────────────────────────────────────
function DiffView({ diff, onActivate, onDiscard, activating }) {
  const { summary, impact, def_changes, model_changes } = diff
  const hasAnyChanges = !diff.same_content

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs text-slate-500 mb-1">
            Fetched {diff.fetched_at?.slice(0,19).replace('T',' ')} UTC
            {' · '}Schema ID: <code className="text-slate-600">{diff.new_schema_id}</code>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Active hash:</span>
            <code className="text-xs font-mono text-slate-600">{diff.active_content_hash}</code>
            <span className="text-xs text-slate-400">→</span>
            <code className="text-xs font-mono text-slate-600">{diff.new_content_hash}</code>
            {diff.same_content && <span className="text-xs text-green-600 font-semibold">identical content</span>}
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            onClick={onDiscard}
            className="text-xs px-3 py-1.5 rounded border bg-white text-slate-600 border-slate-300 hover:bg-slate-50 transition-colors"
          >
            Discard
          </button>
          <button
            onClick={onActivate}
            disabled={activating}
            className="text-xs px-3 py-1.5 rounded bg-lpa-blue text-white hover:bg-[#0c2fd4] disabled:opacity-40 transition-colors font-semibold"
          >
            {activating ? 'Activating…' : 'Activate Schema'}
          </button>
        </div>
      </div>

      {/* Summary chips */}
      <SummaryChips summary={summary} />

      {/* Impact */}
      {hasAnyChanges && (
        <div>
          <div className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-1.5">Impact Analysis</div>
          <ImpactPanel impact={impact} />
        </div>
      )}

      {/* $defs changes */}
      {def_changes?.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-1.5">$defs Changes</div>
          <div className="border border-slate-200 rounded divide-y divide-slate-100">
            {def_changes.map(dc => (
              <div key={dc.name} className="flex items-center gap-2 px-3 py-1.5 text-xs">
                <SevBadge severity={dc.severity} small />
                <code className="font-mono text-slate-700">{dc.name}</code>
                <span className="text-slate-400">{dc.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Model changes */}
      {model_changes?.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-1.5">
            Model Changes ({model_changes.length})
          </div>
          {model_changes.map(mc => <ModelDiffBlock key={mc.model} mc={mc} />)}
        </div>
      )}

      {!hasAnyChanges && (
        <div className="py-6 text-center text-slate-400 text-sm">
          The fetched schema is semantically identical to the active version.<br />
          You can still activate it to update the file (e.g. to apply formatting).
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function SchemaManager() {
  const [status,      setStatus]     = useState(null)
  const [activeDiff,  setActiveDiff] = useState(null)   // currently viewed diff
  const [fetching,    setFetching]   = useState(false)
  const [activating,  setActivating] = useState(false)
  const [error,       setError]      = useState('')

  const loadStatus = useCallback(async () => {
    try {
      const s = await api.schemaStatus()
      setStatus(s)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => { loadStatus() }, [loadStatus])

  const handleFetch = async () => {
    setFetching(true)
    setError('')
    try {
      const diff = await api.schemaFetch()
      setActiveDiff(diff)
      await loadStatus()
    } catch (e) {
      setError(e.message)
    } finally {
      setFetching(false)
    }
  }

  const handleViewPending = async (fetchId) => {
    setError('')
    try {
      const diff = await api.schemaPendingDiff(fetchId)
      setActiveDiff(diff)
    } catch (e) {
      setError(e.message)
    }
  }

  const handleActivate = async (fetchId) => {
    setActivating(true)
    setError('')
    try {
      await api.schemaActivate(fetchId)
      setActiveDiff(null)
      await loadStatus()
    } catch (e) {
      setError(e.message)
    } finally {
      setActivating(false)
    }
  }

  const handleDiscard = async (fetchId) => {
    setError('')
    try {
      await api.schemaDiscard(fetchId)
      if (activeDiff?.fetch_id === fetchId) setActiveDiff(null)
      await loadStatus()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      {/* Header bar */}
      <div className="px-5 py-3 bg-slate-50 border-b border-slate-200 shrink-0">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-700">PRISM Schema</h3>
            {status?.active && (
              <div className="flex items-center gap-3 mt-0.5 text-xs text-slate-500">
                <span>Version: <strong className="text-slate-700">{status.active.version}</strong></span>
                <span>Hash: <code className="font-mono">{status.active.content_hash}</code></span>
                <span>{status.active.models?.length} models</span>
                <span className="text-slate-400">{(status.active.file_size_bytes / 1024).toFixed(0)} KB</span>
              </div>
            )}
          </div>
          <button
            onClick={handleFetch}
            disabled={fetching}
            className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded bg-lpa-blue text-white hover:bg-[#0c2fd4] disabled:opacity-40 transition-colors"
          >
            {fetching ? '⟳ Fetching…' : '⟳ Check for Update'}
          </button>
        </div>
        {error && (
          <div className="mt-2 text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1">{error}</div>
        )}
      </div>

      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* Left: pending list */}
        {status?.pending?.length > 0 && (
          <div className="w-56 shrink-0 border-r border-slate-200 flex flex-col overflow-y-auto scrollbar-thin bg-white">
            <div className="px-3 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wide border-b border-slate-100">
              Pending ({status.pending.length})
            </div>
            {status.pending.map(p => {
              const isViewing = activeDiff?.fetch_id === p.fetch_id
              const hasBreaking = p.summary?.breaking > 0
              const hasChanges  = !p.same_content
              return (
                <button
                  key={p.fetch_id}
                  onClick={() => handleViewPending(p.fetch_id)}
                  className={`w-full text-left px-3 py-2 border-b border-slate-100 text-xs transition-colors ${
                    isViewing ? 'bg-blue-50' : 'hover:bg-slate-50'
                  }`}
                >
                  <div className="font-mono text-slate-600">{p.fetch_id.replace('_',' ')}</div>
                  <div className="mt-0.5">
                    {!hasChanges
                      ? <span className="text-green-600">No changes</span>
                      : hasBreaking
                        ? <span className="text-red-600">{p.summary.breaking} breaking</span>
                        : <span className="text-amber-600">{p.summary.caution} caution · {p.summary.safe} safe</span>
                    }
                  </div>
                </button>
              )
            })}
          </div>
        )}

        {/* Right: diff view or empty state */}
        <div className="flex-1 min-w-0 overflow-y-auto scrollbar-thin p-5">
          {activeDiff ? (
            <DiffView
              diff={activeDiff}
              onActivate={() => handleActivate(activeDiff.fetch_id)}
              onDiscard={() => handleDiscard(activeDiff.fetch_id)}
              activating={activating}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center text-slate-400">
              <div className="text-4xl mb-3">📋</div>
              <div className="text-sm font-medium text-slate-500">No diff loaded</div>
              {status?.pending?.length > 0
                ? <div className="text-xs mt-1">Select a pending fetch on the left, or check for a new update.</div>
                : <div className="text-xs mt-1">Click "Check for Update" to fetch the latest PRISM schema and see what changed.</div>
              }
              {status?.active && (
                <div className="mt-4 text-xs text-slate-400">
                  Source: <code className="font-mono">{status.source_url}</code>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
