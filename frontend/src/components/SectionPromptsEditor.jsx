import { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'

// Tag pill for search headers
function HeaderPill({ value, onRemove, disabled }) {
  return (
    <span className="inline-flex items-center gap-1 bg-slate-100 border border-slate-200 rounded px-2 py-0.5 text-xs font-mono text-slate-700">
      {value}
      {!disabled && (
        <button
          onClick={() => onRemove(value)}
          className="text-slate-400 hover:text-red-500 transition-colors ml-0.5 leading-none"
          title="Remove"
        >
          ×
        </button>
      )}
    </span>
  )
}

// Editable search headers tag list
function HeadersEditor({ headers, onChange, disabled }) {
  const [inputVal, setInputVal] = useState('')

  const addHeader = () => {
    const trimmed = inputVal.trim().toUpperCase()
    if (trimmed && !headers.includes(trimmed)) {
      onChange([...headers, trimmed])
    }
    setInputVal('')
  }

  const removeHeader = (val) => onChange(headers.filter(h => h !== val))

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5 min-h-8">
        {headers.map(h => (
          <HeaderPill key={h} value={h} onRemove={removeHeader} disabled={disabled} />
        ))}
      </div>
      {!disabled && (
        <div className="flex gap-1.5">
          <input
            className="flex-1 border border-slate-200 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-blue-400 uppercase"
            placeholder="Add header… (press Enter)"
            value={inputVal}
            onChange={e => setInputVal(e.target.value.toUpperCase())}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addHeader() } }}
          />
          <button
            onClick={addHeader}
            className="bg-slate-100 hover:bg-slate-200 border border-slate-200 rounded px-2 py-1 text-xs text-slate-600 transition-colors"
          >
            + Add
          </button>
        </div>
      )}
    </div>
  )
}

export default function SectionPromptsEditor() {
  const [sections,       setSections]       = useState([])     // list summaries
  const [selectedName,   setSelectedName]   = useState(null)
  const [detail,         setDetail]         = useState(null)   // full spec for selected section
  const [editNote,       setEditNote]       = useState('')
  const [editHeaders,    setEditHeaders]    = useState([])
  const [editMaxChars,   setEditMaxChars]   = useState(10000)
  const [saving,         setSaving]         = useState(false)
  const [savingNote,     setSavingNote]     = useState(false)
  const [dirty,          setDirty]          = useState(false)
  const [error,          setError]          = useState('')
  const [successMsg,     setSuccessMsg]     = useState('')

  // Load section list on mount
  useEffect(() => {
    api.listSections()
      .then(setSections)
      .catch(e => setError(e.message))
  }, [])

  // Load detail when selection changes
  useEffect(() => {
    if (!selectedName) return
    setDetail(null)
    setError('')
    api.getSection(selectedName)
      .then(d => {
        setDetail(d)
        setEditNote(d.system_note || '')
        setEditHeaders(d.search_headers || [])
        setEditMaxChars(d.max_chars || 10000)
        setDirty(false)
      })
      .catch(e => setError(e.message))
  }, [selectedName])

  const markDirty = () => setDirty(true)

  const handleSaveNote = async () => {
    setSavingNote(true)
    setError('')
    try {
      await api.updateSectionNote(selectedName, editNote)
      setSuccessMsg('Note saved')
      setDirty(false)
      setTimeout(() => setSuccessMsg(''), 2000)
    } catch (e) {
      setError(e.message)
    } finally {
      setSavingNote(false)
    }
  }

  const handleSaveAll = async () => {
    setSaving(true)
    setError('')
    try {
      await api.updateSection(selectedName, {
        system_note: editNote,
        search_headers: editHeaders,
        max_chars: editMaxChars,
      })
      setSuccessMsg('Section saved')
      setDirty(false)
      // Refresh list to update header_count
      const updated = await api.listSections()
      setSections(updated)
      setTimeout(() => setSuccessMsg(''), 2000)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const sectionColor = (name) => {
    const colors = {
      identifiers:     'bg-blue-50 text-blue-700 border-blue-200',
      product_generic: 'bg-amber-50 text-amber-700 border-amber-200',
      underlying_terms:'bg-emerald-50 text-emerald-700 border-emerald-200',
      protection:      'bg-red-50 text-red-700 border-red-200',
      autocall:        'bg-violet-50 text-violet-700 border-violet-200',
      coupon:          'bg-pink-50 text-pink-700 border-pink-200',
      parties:         'bg-slate-50 text-slate-600 border-slate-200',
    }
    return colors[name] || 'bg-slate-50 text-slate-600 border-slate-200'
  }

  return (
    <div className="flex h-full min-h-0">
      {/* Left sidebar */}
      <div className="w-52 shrink-0 border-r border-slate-200 flex flex-col bg-slate-50">
        <div className="px-3 py-2.5 border-b border-slate-200">
          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
            Section Groups
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">{sections.length} sections</p>
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {sections.map(s => (
            <button
              key={s.name}
              onClick={() => setSelectedName(s.name)}
              className={`w-full text-left px-3 py-2.5 transition-colors ${
                selectedName === s.name
                  ? 'bg-white border-l-2 border-blue-500'
                  : 'hover:bg-white border-l-2 border-transparent'
              }`}
            >
              <div className="flex items-center gap-1.5">
                <span className={`text-xs font-medium px-1.5 py-0.5 rounded border ${sectionColor(s.name)}`}>
                  {s.name}
                </span>
              </div>
              <div className="text-xs text-slate-400 mt-0.5">
                {s.required_for?.length || 0} models · {s.header_count} headers
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Right panel */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        {!selectedName ? (
          <div className="flex items-center justify-center h-full text-slate-400 text-sm">
            Select a section group to edit its extraction prompt.
          </div>
        ) : !detail ? (
          <div className="flex items-center justify-center h-full text-slate-400 text-sm">
            Loading…
          </div>
        ) : (
          <div className="p-6 space-y-6 max-w-3xl">
            {/* Header */}
            <div>
              <div className="flex items-center gap-3 mb-1">
                <span className={`text-sm font-semibold px-2.5 py-1 rounded border ${sectionColor(selectedName)}`}>
                  {selectedName}
                </span>
                {dirty && (
                  <span className="text-xs text-amber-600 font-medium">● Unsaved changes</span>
                )}
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
                <span className="text-xs text-slate-500">
                  Schema keys: <span className="font-mono text-slate-700">{detail.schema_keys?.join(', ')}</span>
                </span>
                <span className="text-xs text-slate-500">
                  Models: <span className="text-slate-700">{detail.required_for?.join(', ') || '—'}</span>
                </span>
              </div>
            </div>

            {/* Error / success */}
            {error && (
              <div className="bg-red-50 border border-red-200 rounded px-3 py-2 text-xs text-red-700">{error}</div>
            )}
            {successMsg && (
              <div className="bg-green-50 border border-green-200 rounded px-3 py-2 text-xs text-green-700">{successMsg}</div>
            )}

            {/* System note */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                  System Prompt Note
                </label>
                <button
                  onClick={handleSaveNote}
                  disabled={savingNote}
                  className="text-xs px-2.5 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors disabled:opacity-40"
                >
                  {savingNote ? 'Saving…' : 'Save note'}
                </button>
              </div>
              <textarea
                className="w-full border border-slate-200 rounded px-3 py-2 text-xs text-slate-700 font-mono leading-relaxed focus:outline-none focus:ring-1 focus:ring-blue-400 resize-y"
                rows={8}
                value={editNote}
                onChange={e => { setEditNote(e.target.value); markDirty() }}
              />
            </div>

            {/* Search headers */}
            <div>
              <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide mb-1.5">
                Search Headers
              </label>
              <HeadersEditor
                headers={editHeaders}
                onChange={v => { setEditHeaders(v); markDirty() }}
                disabled={false}
              />
            </div>

            {/* Max chars */}
            <div className="flex items-center gap-3">
              <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                Max Filing Chars
              </label>
              <input
                type="number"
                step={1000}
                min={1000}
                max={120000}
                value={editMaxChars}
                onChange={e => { setEditMaxChars(Number(e.target.value)); markDirty() }}
                className="w-28 border border-slate-200 rounded px-2 py-1 text-xs text-slate-700 font-mono focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
              <span className="text-xs text-slate-400">chars of stripped filing text</span>
            </div>

            {/* Save all */}
            <div className="flex items-center gap-3 pt-2 border-t border-slate-200">
              <button
                onClick={handleSaveAll}
                disabled={saving}
                className="text-sm px-4 py-1.5 bg-slate-700 hover:bg-slate-800 text-white rounded transition-colors disabled:opacity-40"
              >
                {saving ? 'Saving…' : 'Save all changes'}
              </button>
              <button
                onClick={() => {
                  setEditNote(detail.system_note || '')
                  setEditHeaders(detail.search_headers || [])
                  setEditMaxChars(detail.max_chars || 10000)
                  setDirty(false)
                }}
                disabled={!dirty}
                className="text-sm px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-600 border border-slate-300 rounded transition-colors disabled:opacity-40"
              >
                Reset
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
