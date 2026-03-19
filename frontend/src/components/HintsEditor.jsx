/**
 * HintsEditor.jsx
 *
 * Review and edit extraction hints stored in files/hints/*.yaml.
 *
 * Tabs:
 *  - "Cross-Issuer Rules" — the cross-issuer field_level_hints table (29 fields)
 *  - One tab per issuer   — per-issuer metadata + field hints table
 *
 * All cells are editable inline. Each row has a Save button that calls the
 * hints API. There is also a "Save all" button per issuer tab.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../api.js'

// ---------------------------------------------------------------------------
// Small helper components
// ---------------------------------------------------------------------------

/** Inline-editable text cell */
function EditableCell({ value, onSave, multiline = false, className = '' }) {
  const [editing, setEditing] = useState(false)
  const [draft,   setDraft]   = useState(value ?? '')
  const inputRef = useRef(null)

  useEffect(() => {
    setDraft(value ?? '')
  }, [value])

  useEffect(() => {
    if (editing && inputRef.current) inputRef.current.focus()
  }, [editing])

  const commit = () => {
    setEditing(false)
    if (draft !== (value ?? '')) onSave(draft)
  }

  const handleKey = (e) => {
    if (e.key === 'Escape') { setDraft(value ?? ''); setEditing(false) }
    if (!multiline && e.key === 'Enter') commit()
  }

  if (!editing) {
    return (
      <div
        className={`cursor-pointer hover:bg-amber-50 rounded px-1 min-h-[1.5rem] ${className}`}
        onClick={() => setEditing(true)}
        title="Click to edit"
      >
        {draft || <span className="text-slate-300 italic text-xs">—</span>}
      </div>
    )
  }

  const sharedProps = {
    ref: inputRef,
    value: draft,
    onChange: e => setDraft(e.target.value),
    onBlur: commit,
    onKeyDown: handleKey,
    className: `w-full border border-blue-400 rounded px-1 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500 ${className}`,
  }

  return multiline
    ? <textarea rows={3} {...sharedProps} />
    : <input type="text" {...sharedProps} />
}

/** Inline-editable list cell (comma-separated display, newline-per-item when editing) */
function EditableListCell({ value, onSave }) {
  const list   = Array.isArray(value) ? value : []
  const display = list.join(', ')
  const [editing, setEditing] = useState(false)
  const [draft,   setDraft]   = useState(list.join('\n'))
  const ref = useRef(null)

  useEffect(() => {
    setDraft((Array.isArray(value) ? value : []).join('\n'))
  }, [value])

  useEffect(() => {
    if (editing && ref.current) ref.current.focus()
  }, [editing])

  const commit = () => {
    setEditing(false)
    const newList = draft.split('\n').map(s => s.trim()).filter(Boolean)
    if (JSON.stringify(newList) !== JSON.stringify(list)) onSave(newList)
  }

  if (!editing) {
    return (
      <div
        className="cursor-pointer hover:bg-amber-50 rounded px-1 min-h-[1.5rem] text-xs"
        onClick={() => setEditing(true)}
        title="Click to edit (one item per line)"
      >
        {display || <span className="text-slate-300 italic">—</span>}
      </div>
    )
  }

  return (
    <textarea
      ref={ref}
      rows={Math.max(3, list.length + 1)}
      value={draft}
      onChange={e => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={e => e.key === 'Escape' && (setDraft(list.join('\n')), setEditing(false))}
      className="w-full border border-blue-400 rounded px-1 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
      placeholder="One item per line"
    />
  )
}

/** Small status badge shown after save */
function SaveBadge({ status }) {
  if (!status) return null
  const styles = {
    saving: 'bg-amber-100 text-amber-700',
    saved:  'bg-green-100 text-green-700',
    error:  'bg-red-100 text-red-700',
  }
  const labels = { saving: 'Saving…', saved: 'Saved', error: 'Error' }
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${styles[status] || ''}`}>
      {labels[status] || status}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Cross-issuer table
// ---------------------------------------------------------------------------

function CrossIssuerTable({ hints, onFieldSaved }) {
  const [rowStatus, setRowStatus] = useState({})

  const fieldEntries = Object.entries(hints).filter(([k]) => !k.startsWith('_'))

  const saveField = async (fieldPath, update) => {
    setRowStatus(s => ({ ...s, [fieldPath]: 'saving' }))
    try {
      await api.updateCrossFieldHint(fieldPath, update)
      setRowStatus(s => ({ ...s, [fieldPath]: 'saved' }))
      onFieldSaved?.()
      setTimeout(() => setRowStatus(s => ({ ...s, [fieldPath]: null })), 2000)
    } catch (err) {
      console.error(err)
      setRowStatus(s => ({ ...s, [fieldPath]: 'error' }))
    }
  }

  if (!fieldEntries.length) {
    return <p className="text-slate-500 text-sm p-4">No cross-issuer hints loaded.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-slate-100 text-slate-600 text-left">
            <th className="px-2 py-2 border border-slate-200 font-semibold w-52">Field path</th>
            <th className="px-2 py-2 border border-slate-200 font-semibold w-60">Description</th>
            <th className="px-2 py-2 border border-slate-200 font-semibold">Synonyms</th>
            <th className="px-2 py-2 border border-slate-200 font-semibold w-44">Format note</th>
            <th className="px-2 py-2 border border-slate-200 font-semibold w-56">Caution</th>
            <th className="px-2 py-2 border border-slate-200 font-semibold w-20 text-center">Actions</th>
          </tr>
        </thead>
        <tbody>
          {fieldEntries.map(([fieldPath, hint]) => (
            <tr key={fieldPath} className="align-top hover:bg-slate-50 border-b border-slate-100">
              <td className="px-2 py-1.5 border-r border-slate-200 font-mono text-blue-700 whitespace-nowrap">
                {fieldPath}
              </td>
              <td className="px-2 py-1.5 border-r border-slate-200">
                <EditableCell
                  value={hint.description}
                  multiline
                  onSave={v => saveField(fieldPath, { description: v })}
                />
              </td>
              <td className="px-2 py-1.5 border-r border-slate-200">
                <EditableListCell
                  value={hint.common_synonyms}
                  onSave={v => saveField(fieldPath, { common_synonyms: v })}
                />
              </td>
              <td className="px-2 py-1.5 border-r border-slate-200">
                <EditableCell
                  value={hint.value_format}
                  multiline
                  onSave={v => saveField(fieldPath, { value_format: v })}
                />
              </td>
              <td className="px-2 py-1.5 border-r border-slate-200">
                <EditableCell
                  value={hint.caution}
                  multiline
                  onSave={v => saveField(fieldPath, { caution: v })}
                />
              </td>
              <td className="px-2 py-1.5 text-center">
                <SaveBadge status={rowStatus[fieldPath]} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Issuer field-hints table
// ---------------------------------------------------------------------------

function IssuerFieldTable({ slug, fieldHints, onSaved }) {
  const [rowStatus, setRowStatus] = useState({})

  const entries = Object.entries(fieldHints || {})

  const saveField = async (fieldPath, update) => {
    setRowStatus(s => ({ ...s, [fieldPath]: 'saving' }))
    try {
      await api.updateIssuerFieldHint(slug, fieldPath, update)
      setRowStatus(s => ({ ...s, [fieldPath]: 'saved' }))
      onSaved?.()
      setTimeout(() => setRowStatus(s => ({ ...s, [fieldPath]: null })), 2000)
    } catch (err) {
      console.error(err)
      setRowStatus(s => ({ ...s, [fieldPath]: 'error' }))
    }
  }

  if (!entries.length) {
    return <p className="text-slate-400 italic text-xs">No field hints defined.</p>
  }

  return (
    <div className="overflow-x-auto mt-2">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-slate-100 text-slate-600 text-left">
            <th className="px-2 py-2 border border-slate-200 font-semibold w-52">Field path</th>
            <th className="px-2 py-2 border border-slate-200 font-semibold">Synonyms</th>
            <th className="px-2 py-2 border border-slate-200 font-semibold w-36">Label in doc</th>
            <th className="px-2 py-2 border border-slate-200 font-semibold w-52">Format</th>
            <th className="px-2 py-2 border border-slate-200 font-semibold w-44">Typical location</th>
            <th className="px-2 py-2 border border-slate-200 font-semibold w-20 text-center">Actions</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([fieldPath, hint]) => (
            <tr key={fieldPath} className="align-top hover:bg-slate-50 border-b border-slate-100">
              <td className="px-2 py-1.5 border-r border-slate-200 font-mono text-blue-700 whitespace-nowrap">
                {fieldPath}
              </td>
              <td className="px-2 py-1.5 border-r border-slate-200">
                <EditableListCell
                  value={hint.synonyms}
                  onSave={v => saveField(fieldPath, { synonyms: v })}
                />
              </td>
              <td className="px-2 py-1.5 border-r border-slate-200">
                <EditableCell
                  value={hint.label_in_doc}
                  onSave={v => saveField(fieldPath, { label_in_doc: v })}
                />
              </td>
              <td className="px-2 py-1.5 border-r border-slate-200">
                <EditableCell
                  value={hint.format}
                  multiline
                  onSave={v => saveField(fieldPath, { format: v })}
                />
              </td>
              <td className="px-2 py-1.5 border-r border-slate-200">
                <EditableCell
                  value={hint.typical_location}
                  onSave={v => saveField(fieldPath, { typical_location: v })}
                />
              </td>
              <td className="px-2 py-1.5 text-center">
                <SaveBadge status={rowStatus[fieldPath]} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Issuer tab content
// ---------------------------------------------------------------------------

function IssuerTab({ summary, onSaved }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [saveAll, setSaveAll] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await api.getIssuerHints(summary.slug)
      setData(d)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }, [summary.slug])

  useEffect(() => { load() }, [load])

  const updateLocal = (key, value) => {
    setData(prev => prev ? { ...prev, [key]: value } : prev)
  }

  const handleSaveAll = async () => {
    if (!data) return
    setSaveAll('saving')
    try {
      const { issuer_key, slug, ...body } = data
      await api.updateIssuerHints(summary.slug, body)
      setSaveAll('saved')
      onSaved?.()
      setTimeout(() => setSaveAll(null), 2500)
    } catch (err) {
      console.error(err)
      setSaveAll('error')
    }
  }

  if (loading) return <div className="p-4 text-slate-400 text-sm">Loading…</div>
  if (!data)   return <div className="p-4 text-red-500 text-sm">Failed to load issuer hints.</div>

  return (
    <div className="p-4 space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold text-slate-800">{data.issuer_key}</h2>
          <p className="text-xs text-slate-400">File: {summary.file}</p>
        </div>
        <div className="flex items-center gap-2">
          <SaveBadge status={saveAll} />
          <button
            onClick={handleSaveAll}
            className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 transition-colors"
          >
            Save all
          </button>
        </div>
      </div>

      {/* Metadata */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {/* Section headings */}
        <div>
          <label className="block text-xs font-semibold text-slate-600 mb-1">Section headings</label>
          <EditableListCell
            value={data.section_headings}
            onSave={v => updateLocal('section_headings', v)}
          />
          <p className="text-xs text-slate-400 mt-0.5">One heading per line</p>
        </div>

        {/* Key terms position */}
        <div>
          <label className="block text-xs font-semibold text-slate-600 mb-1">Key terms position</label>
          <EditableCell
            value={data.key_terms_position}
            multiline
            onSave={v => updateLocal('key_terms_position', v)}
            className="text-xs"
          />
        </div>

        {/* Document structure */}
        <div className="lg:col-span-2">
          <label className="block text-xs font-semibold text-slate-600 mb-1">Document structure</label>
          <EditableCell
            value={data.document_structure}
            multiline
            onSave={v => updateLocal('document_structure', v)}
            className="text-xs"
          />
        </div>

        {/* General notes */}
        <div className="lg:col-span-2">
          <label className="block text-xs font-semibold text-slate-600 mb-1">General notes</label>
          <EditableCell
            value={data.general_notes}
            multiline
            onSave={v => updateLocal('general_notes', v)}
            className="text-xs"
          />
        </div>
      </div>

      {/* Field hints table */}
      <div>
        <h3 className="text-xs font-semibold text-slate-600 mb-2">
          Field hints ({Object.keys(data.field_hints || {}).length})
        </h3>
        <IssuerFieldTable
          slug={summary.slug}
          fieldHints={data.field_hints}
          onSaved={onSaved}
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Cross-issuer tab content
// ---------------------------------------------------------------------------

function CrossIssuerTab() {
  const [hints,   setHints]   = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await api.getCrossIssuerHints()
      setHints(d)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="p-4 text-slate-400 text-sm">Loading…</div>
  if (!hints)  return <div className="p-4 text-red-500 text-sm">Failed to load cross-issuer hints.</div>

  const description = hints._description

  return (
    <div className="p-4 space-y-3">
      <div>
        <h2 className="text-sm font-bold text-slate-800">Cross-issuer field extraction rules</h2>
        {description && (
          <p className="text-xs text-slate-500 mt-1">{description}</p>
        )}
      </div>
      <CrossIssuerTable hints={hints} onFieldSaved={load} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main HintsEditor component
// ---------------------------------------------------------------------------

export default function HintsEditor() {
  const [issuers, setIssuers] = useState([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('cross')

  const loadList = useCallback(async () => {
    setLoading(true)
    try {
      const list = await api.listHints()
      setIssuers(list)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadList() }, [loadList])

  const tabs = [
    { id: 'cross', label: 'Cross-Issuer Rules' },
    ...issuers.map(iss => ({ id: iss.slug, label: iss.name.replace(' LLC', '').replace(' AG', '').replace(' Corp.', ''), issuer: iss })),
  ]

  return (
    <div className="flex flex-col h-full min-h-0 bg-white">
      {/* Tab bar */}
      <div className="flex items-center border-b border-slate-200 bg-slate-50 overflow-x-auto shrink-0">
        {loading && (
          <span className="px-4 py-2 text-xs text-slate-400">Loading issuers…</span>
        )}
        {!loading && tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2.5 text-xs font-medium whitespace-nowrap border-r border-slate-200 transition-colors ${
              activeTab === tab.id
                ? 'bg-white text-blue-600 border-b-2 border-b-blue-600 relative -mb-px'
                : 'text-slate-500 hover:text-slate-700 hover:bg-white'
            }`}
          >
            {tab.label}
            {tab.issuer && (
              <span className="ml-1.5 text-slate-400 font-normal">
                ({tab.issuer.field_hints_count})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
        {activeTab === 'cross' ? (
          <CrossIssuerTab />
        ) : (
          (() => {
            const issuerSummary = issuers.find(i => i.slug === activeTab)
            return issuerSummary
              ? <IssuerTab key={activeTab} summary={issuerSummary} onSaved={loadList} />
              : <div className="p-4 text-slate-400 text-sm">Issuer not found.</div>
          })()
        )}
      </div>
    </div>
  )
}
