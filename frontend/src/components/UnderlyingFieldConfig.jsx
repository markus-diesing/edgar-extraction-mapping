/**
 * UnderlyingFieldConfig.jsx — Expert Settings panel for the Underlying Field Configuration.
 *
 * Allows reviewers to:
 *   - Enable / disable individual extracted fields (Tier 2)
 *   - Edit the display name shown to reviewers
 *   - Save changes back to the server (PUT /api/underlying/field-config)
 *
 * Changes are applied to the in-memory state immediately on toggle/rename and
 * committed to the server only when "Save" is clicked, matching the pattern
 * used by HintsEditor and ExtractionSettings.
 */
import { useState, useEffect } from 'react'
import { api } from '../api.js'

// ---------------------------------------------------------------------------
// FieldRow — one editable row in the config table
// ---------------------------------------------------------------------------

function FieldRow({ field, onChange }) {
  const [editingName, setEditingName] = useState(false)
  const [nameVal,     setNameVal]     = useState(field.display_name)

  const commitName = () => {
    setEditingName(false)
    if (nameVal.trim() && nameVal !== field.display_name) {
      onChange({ ...field, display_name: nameVal.trim() })
    }
  }

  return (
    <tr className={`border-t border-slate-100 hover:bg-slate-50 ${!field.enabled ? 'opacity-50' : ''}`}>
      {/* Enable toggle */}
      <td className="py-2 px-3">
        <input
          type="checkbox"
          checked={field.enabled}
          onChange={e => onChange({ ...field, enabled: e.target.checked })}
          className="rounded border-slate-300 text-lpa-blue focus:ring-lpa-cyan"
        />
      </td>
      {/* Internal field name */}
      <td className="py-2 px-3 text-xs font-mono text-slate-600 whitespace-nowrap">
        {field.name}
      </td>
      {/* Display name (editable) */}
      <td className="py-2 px-3 text-xs text-slate-700 min-w-[160px]">
        {editingName ? (
          <input
            autoFocus
            className="w-full border border-lpa-cyan rounded px-2 py-0.5 text-xs focus:outline-none"
            value={nameVal}
            onChange={e => setNameVal(e.target.value)}
            onBlur={commitName}
            onKeyDown={e => { if (e.key === 'Enter') commitName(); if (e.key === 'Escape') { setNameVal(field.display_name); setEditingName(false) } }}
          />
        ) : (
          <button
            className="text-left w-full hover:text-lpa-blue group"
            onClick={() => { setNameVal(field.display_name); setEditingName(true) }}
            title="Click to edit display name"
          >
            {field.display_name}
            <span className="ml-1 text-slate-300 group-hover:text-slate-400">✎</span>
          </button>
        )}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function UnderlyingFieldConfig() {
  const [cfg,     setCfg]     = useState(null)
  const [dirty,   setDirty]   = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving,  setSaving]  = useState(false)
  const [error,   setError]   = useState('')
  const [saved,   setSaved]   = useState(false)

  // ── Load ──────────────────────────────────────────────────────────────────

  useEffect(() => {
    setLoading(true)
    api.underlyingFieldConfig()
      .then(data => { setCfg(data); setDirty(false) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  // ── Field change ──────────────────────────────────────────────────────────

  const updateField = (updated) => {
    setCfg(prev => ({
      ...prev,
      fields: prev.fields.map(f => f.name === updated.name ? updated : f),
    }))
    setDirty(true)
    setSaved(false)
  }

  // ── Save ──────────────────────────────────────────────────────────────────

  const doSave = async () => {
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      const updated = await api.underlyingUpdateFieldConfig({ fields: cfg.fields })
      setCfg(updated)
      setDirty(false)
      setSaved(true)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  // ── Enable / disable all ──────────────────────────────────────────────────

  const setAll = (enabled) => {
    setCfg(prev => ({
      ...prev,
      fields: prev.fields.map(f => ({ ...f, enabled })),
    }))
    setDirty(true)
    setSaved(false)
  }

  // ── Render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm animate-pulse">
        Loading field configuration…
      </div>
    )
  }

  if (!cfg && error) {
    return (
      <div className="p-6 text-red-600 text-sm">
        Failed to load field configuration: {error}
      </div>
    )
  }

  if (!cfg) return null

  const enabledCount = cfg.fields.filter(f => f.enabled).length

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* ── Toolbar ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 bg-white shrink-0 flex-wrap gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">Underlying Field Configuration</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Version <span className="font-mono">{cfg.version}</span> · {enabledCount} of {cfg.fields.length} fields enabled
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setAll(true)}
            className="text-xs text-slate-500 hover:text-lpa-blue underline"
          >
            Enable all
          </button>
          <button
            onClick={() => setAll(false)}
            className="text-xs text-slate-500 hover:text-lpa-blue underline"
          >
            Disable all
          </button>
          <button
            onClick={doSave}
            disabled={!dirty || saving}
            className="bg-lpa-blue hover:bg-[#0c2fd4] disabled:bg-slate-300 text-white text-xs font-medium rounded px-4 py-1.5 transition-colors"
          >
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>

      {/* ── Status bar ───────────────────────────────────────────────────── */}
      {(error || saved) && (
        <div className={`px-5 py-2 text-xs shrink-0 ${error ? 'bg-red-50 text-red-700 border-b border-red-200' : 'bg-green-50 text-green-700 border-b border-green-200'}`}>
          {error || '✓ Field configuration saved successfully.'}
        </div>
      )}
      {dirty && !error && (
        <div className="px-5 py-1.5 text-xs text-amber-700 bg-amber-50 border-b border-amber-100 shrink-0">
          Unsaved changes — click Save Changes to apply.
        </div>
      )}

      {/* ── Description ──────────────────────────────────────────────────── */}
      <div className="px-5 py-3 text-xs text-slate-500 bg-slate-50 border-b border-slate-100 shrink-0">
        Tier 2 fields are extracted from 10-K cover pages by the LLM pipeline.
        Disabled fields are still stored in the database but hidden from the review UI.
        Edit the <em>display name</em> to change the label shown to reviewers — the internal field name is fixed.
      </div>

      {/* ── Table ────────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        <table className="w-full text-left">
          <thead className="sticky top-0 bg-slate-50 border-b border-slate-200 z-10">
            <tr className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              <th className="py-2 px-3 w-12">On</th>
              <th className="py-2 px-3">Field Name</th>
              <th className="py-2 px-3">Display Label</th>
            </tr>
          </thead>
          <tbody>
            {cfg.fields.map(field => (
              <FieldRow
                key={field.name}
                field={field}
                onChange={updateField}
              />
            ))}
          </tbody>
        </table>

        {cfg.fields.length === 0 && (
          <p className="p-6 text-center text-sm text-slate-400">
            No configurable fields found.  Run an underlying ingest to populate this list.
          </p>
        )}
      </div>
    </div>
  )
}
