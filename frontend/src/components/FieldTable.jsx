import { useState } from 'react'
import { api } from '../api.js'
import StatusBadge from './StatusBadge.jsx'

function ConfidenceBar({ score }) {
  const pct = Math.round((score ?? 0) * 100)
  const color = pct >= 80 ? 'bg-green-400' : pct >= 60 ? 'bg-yellow-400' : 'bg-red-400'
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-1.5 bg-slate-200 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-500 w-8">{pct}%</span>
    </div>
  )
}

function EditCell({ field, filingId, onUpdated }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal]         = useState('')
  const [saving, setSaving]   = useState(false)

  const startEdit = () => {
    const current = field.reviewed_value ?? field.extracted_value
    setVal(current == null ? '' : (typeof current === 'object' ? JSON.stringify(current) : String(current)))
    setEditing(true)
  }

  const save = async (status) => {
    setSaving(true)
    try {
      let parsedVal
      try { parsedVal = JSON.parse(val) } catch { parsedVal = val || null }
      const updated = await api.updateField(filingId, field.id, {
        reviewed_value: parsedVal,
        review_status: status,
      })
      onUpdated(updated)
      setEditing(false)
    } catch (e) {
      alert(e.message)
    } finally {
      setSaving(false)
    }
  }

  const quickAction = async (status) => {
    setSaving(true)
    try {
      const updated = await api.updateField(filingId, field.id, {
        reviewed_value: field.reviewed_value ?? field.extracted_value,
        review_status: status,
      })
      onUpdated(updated)
    } catch (e) {
      alert(e.message)
    } finally {
      setSaving(false)
    }
  }

  if (editing) {
    return (
      <div className="flex flex-col gap-1">
        <input
          className="border border-slate-300 rounded px-2 py-1 text-xs font-mono w-full focus:outline-none focus:ring-1 focus:ring-blue-400"
          value={val}
          onChange={e => setVal(e.target.value)}
          disabled={saving}
          autoFocus
        />
        <div className="flex gap-1">
          <button onClick={() => save('corrected')} disabled={saving}
            className="text-xs bg-blue-600 hover:bg-blue-700 text-white rounded px-2 py-0.5 disabled:opacity-50">
            Save
          </button>
          <button onClick={() => save('accepted')} disabled={saving}
            className="text-xs bg-green-600 hover:bg-green-700 text-white rounded px-2 py-0.5 disabled:opacity-50">
            Accept
          </button>
          <button onClick={() => setEditing(false)} disabled={saving}
            className="text-xs text-slate-500 hover:text-slate-700 px-1">
            Cancel
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1">
      <button onClick={startEdit}
        className="text-xs text-slate-400 hover:text-blue-600 px-1 py-0.5 rounded hover:bg-blue-50 transition-colors"
        title="Edit value">
        ✎
      </button>
      {field.review_status !== 'accepted' && field.review_status !== 'corrected' && (
        <button onClick={() => quickAction('accepted')} disabled={saving}
          className="text-xs text-green-600 hover:text-green-700 px-1 py-0.5 rounded hover:bg-green-50 transition-colors disabled:opacity-50"
          title="Accept">
          ✓
        </button>
      )}
      {field.review_status !== 'rejected' && (
        <button onClick={() => quickAction('rejected')} disabled={saving}
          className="text-xs text-red-500 hover:text-red-600 px-1 py-0.5 rounded hover:bg-red-50 transition-colors disabled:opacity-50"
          title="Reject">
          ✕
        </button>
      )}
    </div>
  )
}

function formatValue(v) {
  if (v === null || v === undefined) return <span className="text-slate-300 italic">null</span>
  if (typeof v === 'object') return (
    <span className="font-mono text-xs text-slate-500 break-all">
      {JSON.stringify(v).slice(0, 120)}
    </span>
  )
  return <span className="font-mono text-xs break-all">{String(v)}</span>
}

export default function FieldTable({ fields, filingId, onFieldUpdated, selectedId, onSelectField }) {
  const [showExcerpts, setShowExcerpts] = useState(false)
  const [filter, setFilter]             = useState('')
  const [hideNull, setHideNull]         = useState(false)

  const filtered = fields.filter(f => {
    if (hideNull && f.not_found) return false
    if (filter && !f.field_name.toLowerCase().includes(filter.toLowerCase())) return false
    return true
  })

  const stats = {
    total:    fields.length,
    found:    fields.filter(f => !f.not_found).length,
    lowConf:  fields.filter(f => f.low_confidence && !f.not_found).length,
    accepted: fields.filter(f => f.review_status === 'accepted' || f.review_status === 'corrected').length,
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Stats bar */}
      <div className="flex items-center gap-4 px-4 py-2 bg-slate-50 border-b border-slate-200 text-xs text-slate-600 shrink-0">
        <span><strong>{stats.total}</strong> fields</span>
        <span className="text-green-700"><strong>{stats.found}</strong> found</span>
        <span className="text-slate-400"><strong>{stats.total - stats.found}</strong> null</span>
        {stats.lowConf > 0 && (
          <span className="text-amber-700"><strong>{stats.lowConf}</strong> low confidence</span>
        )}
        <span className="text-blue-700"><strong>{stats.accepted}</strong> reviewed</span>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-200 bg-white shrink-0">
        <input
          className="flex-1 border border-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
          placeholder="Filter fields…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
        />
        <label className="flex items-center gap-1 text-xs text-slate-500 cursor-pointer select-none">
          <input type="checkbox" checked={hideNull} onChange={e => setHideNull(e.target.checked)} className="rounded" />
          Hide null
        </label>
        <label className="flex items-center gap-1 text-xs text-slate-500 cursor-pointer select-none">
          <input type="checkbox" checked={showExcerpts} onChange={e => setShowExcerpts(e.target.checked)} className="rounded" />
          Excerpts
        </label>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-y-auto scrollbar-thin min-h-0">
        <table className="w-full text-sm border-collapse">
          <thead className="sticky top-0 bg-slate-100 z-10">
            <tr className="text-xs text-slate-600 font-semibold">
              <th className="text-left px-4 py-2 border-b border-slate-200 w-64">Field</th>
              <th className="text-left px-4 py-2 border-b border-slate-200">Value</th>
              <th className="text-left px-4 py-2 border-b border-slate-200 w-28">Confidence</th>
              <th className="text-left px-4 py-2 border-b border-slate-200 w-24">Status</th>
              <th className="px-2 py-2 border-b border-slate-200 w-24">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(f => {
              const isLow       = f.low_confidence && !f.not_found
              const isSchemaErr = !!f.validation_error && f.confidence_score === 0.0
              const isSelected  = selectedId === f.id
              const rowBg = isSelected
                ? 'bg-blue-100 ring-1 ring-inset ring-blue-300'
                : isSchemaErr
                  ? 'bg-red-50 border-l-4 border-red-500'
                  : f.not_found
                    ? 'bg-slate-50'
                    : isLow
                      ? 'bg-amber-50'
                      : 'bg-white'
              const clickProps = onSelectField
                ? { onClick: () => onSelectField(f), role: 'button', tabIndex: 0,
                    onKeyDown: e => e.key === 'Enter' && onSelectField(f) }
                : {}
              return (
                <tr key={f.id}
                  {...clickProps}
                  className={`border-b border-slate-100 transition-colors ${rowBg} ${
                    onSelectField ? 'cursor-pointer hover:bg-blue-50' : 'hover:bg-blue-50/40'
                  }`}
                >
                  <td className="px-4 py-2 font-mono text-xs text-slate-700 align-top">
                    {f.field_name}
                  </td>
                  <td className="px-4 py-2 align-top">
                    <div>
                      <div className="flex items-start gap-1.5 flex-wrap">
                        {formatValue(f.reviewed_value !== null && f.reviewed_value !== undefined
                          ? f.reviewed_value
                          : f.extracted_value)}
                        {isSchemaErr && (
                          <span
                            className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700 border border-red-300 shrink-0"
                            title={f.validation_error}
                          >
                            schema error
                          </span>
                        )}
                      </div>
                      {showExcerpts && f.source_excerpt && (
                        <p className="mt-1 text-xs text-slate-400 italic truncate max-w-xs" title={f.source_excerpt}>
                          "{f.source_excerpt.slice(0, 100)}"
                        </p>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-2 align-top">
                    {f.not_found
                      ? <span className="text-xs text-slate-300">—</span>
                      : <ConfidenceBar score={f.confidence_score} />}
                  </td>
                  <td className="px-4 py-2 align-top">
                    <StatusBadge status={f.review_status} small />
                  </td>
                  <td className="px-2 py-2 align-top">
                    {!f.not_found && (
                      <EditCell field={f} filingId={filingId} onUpdated={onFieldUpdated} />
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
