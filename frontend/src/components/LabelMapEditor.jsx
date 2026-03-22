/**
 * LabelMapEditor — Expert Settings > Label Map
 *
 * Two-panel view:
 *   Left  — Unmatched Labels (miss log): labels seen in extraction runs that
 *           had no mapping. For each, the user can map it to a PRISM field
 *           path or dismiss it as irrelevant.
 *
 *   Right — Current Mapping: the merged label map (cross-issuer baseline +
 *           user-added entries). User entries can be deleted. New entries can
 *           be added manually via a form at the top.
 *
 * Cross-issuer baseline entries (source="cross_issuer") are read-only in the
 * UI. To modify them, edit files/label_map_cross_issuer.yaml directly.
 * User-added entries (source="user") can be deleted from the UI.
 */
import { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'

// ── Helpers ─────────────────────────────────────────────────────────────────

function SourcePill({ source }) {
  const cfg = source === 'user'
    ? { label: 'User',     cls: 'bg-violet-50 text-violet-700 border-violet-300' }
    : { label: 'Baseline', cls: 'bg-slate-100 text-slate-500 border-slate-300'  }
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium border ${cfg.cls}`}>
      {cfg.label}
    </span>
  )
}

function OccurrencePill({ count }) {
  const cls = count >= 5 ? 'bg-red-50 text-red-700 border-red-300'
    : count >= 2 ? 'bg-amber-50 text-amber-700 border-amber-300'
    : 'bg-slate-50 text-slate-500 border-slate-200'
  return (
    <span className={`inline-flex items-center justify-center min-w-[1.5rem] px-1.5 py-0.5 rounded-full text-xs font-semibold border ${cls}`}
      title={`Seen ${count} time${count !== 1 ? 's' : ''} across extractions`}>
      ×{count}
    </span>
  )
}

// Inline dropdown for selecting a PRISM field path
function FieldPathPicker({ value, onChange, fieldPaths, placeholder = 'Select PRISM field…' }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="flex-1 border border-slate-300 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
    >
      <option value="">{placeholder}</option>
      {fieldPaths.map(fp => (
        <option key={fp} value={fp}>{fp}</option>
      ))}
    </select>
  )
}

// ── Miss Log panel ───────────────────────────────────────────────────────────

function MissPanel({ fieldPaths, onResolved }) {
  const [misses,    setMisses]    = useState([])
  const [loading,   setLoading]   = useState(true)
  const [showDone,  setShowDone]  = useState(false)
  const [mappings,  setMappings]  = useState({})   // miss id → chosen field_path
  const [saving,    setSaving]    = useState({})
  const [error,     setError]     = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.labelMapMisses(showDone)
      setMisses(data)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [showDone])

  useEffect(() => { load() }, [load])

  const setMapping = (id, fp) => setMappings(prev => ({ ...prev, [id]: fp }))

  const resolve = async (miss) => {
    const fp = mappings[miss.id]
    if (!fp) return
    setSaving(prev => ({ ...prev, [miss.id]: true }))
    try {
      await api.labelMapResolveMiss(miss.id, fp)
      setMisses(prev => prev.filter(m => m.id !== miss.id))
      onResolved()
    } catch (e) { alert(e.message) }
    finally { setSaving(prev => ({ ...prev, [miss.id]: false })) }
  }

  const dismiss = async (id) => {
    setSaving(prev => ({ ...prev, [id]: true }))
    try {
      await api.labelMapDismissMiss(id)
      setMisses(prev => prev.filter(m => m.id !== id))
    } catch (e) { alert(e.message) }
    finally { setSaving(prev => ({ ...prev, [id]: false })) }
  }

  const dismissAll = async () => {
    if (!confirm('Dismiss all active unmatched labels?')) return
    try {
      await api.labelMapDismissAll()
      load()
    } catch (e) { alert(e.message) }
  }

  const active = misses.filter(m => !showDone)

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200 bg-slate-50 shrink-0">
        <div>
          <h3 className="text-sm font-semibold text-slate-700">Unmatched Labels</h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Labels seen in Key Terms tables without a field mapping.
            {misses.length > 0 && <span className="ml-1 font-medium text-amber-700">{misses.length} pending</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-slate-500 cursor-pointer select-none">
            <input type="checkbox" checked={showDone} onChange={e => setShowDone(e.target.checked)} />
            Show dismissed
          </label>
          {misses.length > 0 && !showDone && (
            <button onClick={dismissAll}
              className="text-xs text-slate-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50 transition-colors">
              Dismiss all
            </button>
          )}
          <button onClick={load}
            className="text-xs text-slate-500 hover:text-blue-600 px-2 py-1 rounded hover:bg-blue-50 transition-colors">
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto scrollbar-thin min-h-0">
        {loading ? (
          <div className="flex items-center justify-center h-24 text-xs text-slate-400">Loading…</div>
        ) : error ? (
          <div className="p-4 text-xs text-red-500">{error}</div>
        ) : misses.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-xs text-slate-400 gap-1">
            <span className="text-xl">✓</span>
            <span>No unmatched labels{showDone ? '' : ' pending'}.</span>
            <span className="text-slate-300">Run a re-extraction on a filing to populate this list.</span>
          </div>
        ) : (
          <table className="w-full text-xs border-collapse">
            <thead className="sticky top-0 bg-slate-100 z-10">
              <tr className="text-xs text-slate-500 font-semibold">
                <th className="text-left px-3 py-2 border-b border-slate-200">Label (raw)</th>
                <th className="text-left px-3 py-2 border-b border-slate-200">Sample value</th>
                <th className="text-left px-3 py-2 border-b border-slate-200">Issuer</th>
                <th className="text-left px-3 py-2 border-b border-slate-200 w-64">Map to PRISM field</th>
                <th className="px-2 py-2 border-b border-slate-200 w-28"></th>
              </tr>
            </thead>
            <tbody>
              {misses.map(m => (
                <tr key={m.id} className="border-b border-slate-100 hover:bg-blue-50/30">
                  <td className="px-3 py-2 align-middle">
                    <div className="flex items-center gap-1.5">
                      <OccurrencePill count={m.occurrence_count} />
                      <span className="font-mono text-slate-700 font-medium">{m.label_raw}</span>
                    </div>
                    <div className="text-slate-400 text-xs mt-0.5 font-mono">{m.label_norm}</div>
                  </td>
                  <td className="px-3 py-2 align-middle text-slate-500 font-mono max-w-[12rem] truncate" title={m.sample_value}>
                    {m.sample_value || <span className="text-slate-300 italic">—</span>}
                  </td>
                  <td className="px-3 py-2 align-middle text-slate-500 max-w-[8rem] truncate" title={m.issuer_name}>
                    {m.issuer_name || <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-3 py-2 align-middle">
                    <FieldPathPicker
                      value={mappings[m.id] || ''}
                      onChange={fp => setMapping(m.id, fp)}
                      fieldPaths={fieldPaths}
                    />
                  </td>
                  <td className="px-2 py-2 align-middle">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => resolve(m)}
                        disabled={!mappings[m.id] || saving[m.id]}
                        className="text-xs bg-blue-600 hover:bg-blue-700 text-white rounded px-2 py-1 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        title="Add this mapping to label_map_user.yaml"
                      >
                        Map
                      </button>
                      <button
                        onClick={() => dismiss(m.id)}
                        disabled={saving[m.id]}
                        className="text-xs text-slate-400 hover:text-red-600 rounded px-1.5 py-1 hover:bg-red-50 transition-colors disabled:opacity-40"
                        title="Dismiss — not a PRISM field"
                      >
                        ✕
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Current Map panel ────────────────────────────────────────────────────────

function MapPanel({ fieldPaths, refreshKey }) {
  const [entries,    setEntries]    = useState([])
  const [loading,    setLoading]    = useState(true)
  const [filter,     setFilter]     = useState('')
  const [showBase,   setShowBase]   = useState(true)
  const [deleting,   setDeleting]   = useState({})
  const [error,      setError]      = useState(null)
  // Add-entry form
  const [addLabel,   setAddLabel]   = useState('')
  const [addField,   setAddField]   = useState('')
  const [adding,     setAdding]     = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.labelMapEntries()
      setEntries(data)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load, refreshKey])

  const addEntry = async () => {
    if (!addLabel.trim() || !addField.trim()) return
    setAdding(true)
    try {
      await api.labelMapAddEntry(addLabel.trim(), addField.trim())
      setAddLabel('')
      setAddField('')
      load()
    } catch (e) { alert(e.message) }
    finally { setAdding(false) }
  }

  const removeEntry = async (label_norm) => {
    setDeleting(prev => ({ ...prev, [label_norm]: true }))
    try {
      await api.labelMapRemoveEntry(label_norm)
      setEntries(prev => prev.filter(e => e.label_norm !== label_norm))
    } catch (e) { alert(e.message) }
    finally { setDeleting(prev => ({ ...prev, [label_norm]: false })) }
  }

  const filtered = entries.filter(e => {
    if (!showBase && e.source === 'cross_issuer') return false
    if (filter && !e.label.toLowerCase().includes(filter.toLowerCase())
               && !e.field_path.toLowerCase().includes(filter.toLowerCase())) return false
    return true
  })

  const userCount = entries.filter(e => e.source === 'user').length

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="px-4 pt-3 pb-2 border-b border-slate-200 bg-slate-50 shrink-0">
        <div className="flex items-center justify-between mb-2">
          <div>
            <h3 className="text-sm font-semibold text-slate-700">Current Label Map</h3>
            <p className="text-xs text-slate-400 mt-0.5">
              {entries.length} entries total
              {userCount > 0 && <span className="ml-1 text-violet-600 font-medium">({userCount} user-added)</span>}
              . Baseline entries require a YAML file edit to change.
            </p>
          </div>
          <button onClick={load}
            className="text-xs text-slate-500 hover:text-blue-600 px-2 py-1 rounded hover:bg-blue-50 transition-colors">
            ↻
          </button>
        </div>

        {/* Add form */}
        <div className="flex items-center gap-2 mb-2">
          <input
            className="flex-1 border border-slate-300 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
            placeholder='Label text (e.g. "Knock-In Trigger Level")'
            value={addLabel}
            onChange={e => setAddLabel(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addEntry()}
          />
          <FieldPathPicker
            value={addField}
            onChange={setAddField}
            fieldPaths={fieldPaths}
            placeholder="PRISM field path…"
          />
          <button
            onClick={addEntry}
            disabled={!addLabel.trim() || !addField.trim() || adding}
            className="text-xs bg-blue-600 hover:bg-blue-700 text-white rounded px-3 py-1.5 disabled:opacity-40 disabled:cursor-not-allowed shrink-0 transition-colors"
          >
            {adding ? '…' : 'Add'}
          </button>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2">
          <input
            className="flex-1 border border-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
            placeholder="Filter labels or field paths…"
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
          <label className="flex items-center gap-1 text-xs text-slate-500 cursor-pointer select-none whitespace-nowrap">
            <input type="checkbox" checked={showBase} onChange={e => setShowBase(e.target.checked)} />
            Show baseline
          </label>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-y-auto scrollbar-thin min-h-0">
        {loading ? (
          <div className="flex items-center justify-center h-24 text-xs text-slate-400">Loading…</div>
        ) : error ? (
          <div className="p-4 text-xs text-red-500">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="flex items-center justify-center h-24 text-xs text-slate-400">No entries match the filter.</div>
        ) : (
          <table className="w-full text-xs border-collapse">
            <thead className="sticky top-0 bg-slate-100 z-10">
              <tr className="text-xs text-slate-500 font-semibold">
                <th className="text-left px-3 py-2 border-b border-slate-200">Label</th>
                <th className="text-left px-3 py-2 border-b border-slate-200">PRISM field path</th>
                <th className="px-2 py-2 border-b border-slate-200 w-20 text-center">Source</th>
                <th className="px-2 py-2 border-b border-slate-200 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(e => (
                <tr key={e.label_norm}
                  className={`border-b border-slate-100 ${e.source === 'user' ? 'bg-violet-50/40 hover:bg-violet-50' : 'hover:bg-slate-50'}`}>
                  <td className="px-3 py-2 font-mono text-slate-700">{e.label}</td>
                  <td className="px-3 py-2 font-mono text-blue-700 text-xs">{e.field_path}</td>
                  <td className="px-2 py-2 text-center">
                    <SourcePill source={e.source} />
                  </td>
                  <td className="px-2 py-2 text-center">
                    {e.source === 'user' ? (
                      <button
                        onClick={() => removeEntry(e.label_norm)}
                        disabled={deleting[e.label_norm]}
                        className="text-slate-300 hover:text-red-500 transition-colors disabled:opacity-40"
                        title="Remove user mapping"
                      >
                        ✕
                      </button>
                    ) : (
                      <span className="text-slate-200" title="Baseline — edit YAML to change">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Root component ───────────────────────────────────────────────────────────

export default function LabelMapEditor() {
  const [fieldPaths,  setFieldPaths]  = useState([])
  const [mapRefresh,  setMapRefresh]  = useState(0)

  useEffect(() => {
    api.labelMapFieldPaths()
      .then(setFieldPaths)
      .catch(() => {})
  }, [])

  const onResolved = () => setMapRefresh(n => n + 1)

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Page header */}
      <div className="px-5 py-3 border-b border-slate-200 bg-white shrink-0">
        <h2 className="text-sm font-bold text-slate-800">Label Map</h2>
        <p className="text-xs text-slate-400 mt-0.5">
          Map HTML table label strings to PRISM field paths for deterministic (Tier 1) extraction.
          Entries added here are saved to <code className="bg-slate-100 px-1 rounded">files/label_map_user.yaml</code> and
          take effect on the next re-extraction — no server restart required.
        </p>
      </div>

      {/* Two-panel layout */}
      <div className="flex flex-1 min-h-0 overflow-hidden divide-x divide-slate-200">
        {/* Left: unmatched labels */}
        <div className="w-[55%] flex flex-col min-h-0 overflow-hidden">
          <MissPanel fieldPaths={fieldPaths} onResolved={onResolved} />
        </div>

        {/* Right: current map */}
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          <MapPanel fieldPaths={fieldPaths} refreshKey={mapRefresh} />
        </div>
      </div>
    </div>
  )
}
