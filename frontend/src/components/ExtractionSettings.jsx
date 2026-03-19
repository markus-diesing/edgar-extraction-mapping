import { useState, useEffect } from 'react'
import { api } from '../api.js'

function SettingRow({ label, description, children }) {
  return (
    <div className="flex items-start justify-between gap-6 py-4 border-b border-slate-100 last:border-0">
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-800">{label}</p>
        {description && (
          <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{description}</p>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function Toggle({ checked, onChange, disabled }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => !disabled && onChange(!checked)}
      disabled={disabled}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1
        ${checked ? 'bg-blue-600' : 'bg-slate-200'}
        ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform
          ${checked ? 'translate-x-6' : 'translate-x-1'}`}
      />
    </button>
  )
}

function NumericInput({ value, onChange, min, max, step, disabled }) {
  return (
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      onChange={e => onChange(Number(e.target.value))}
      className="w-24 border border-slate-200 rounded px-2 py-1 text-sm text-right font-mono
        focus:outline-none focus:ring-1 focus:ring-blue-400 disabled:opacity-40"
    />
  )
}

export default function ExtractionSettings() {
  const [settings,  setSettings]  = useState(null)
  const [saving,    setSaving]    = useState(false)
  const [error,     setError]     = useState('')
  const [successMsg,setSuccessMsg]= useState('')

  useEffect(() => {
    api.getSettings()
      .then(setSettings)
      .catch(e => setError(e.message))
  }, [])

  const save = async (updates) => {
    setSaving(true)
    setError('')
    try {
      const updated = await api.updateSettings(updates)
      setSettings(updated)
      setSuccessMsg('Saved')
      setTimeout(() => setSuccessMsg(''), 2000)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  if (!settings) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm">
        {error || 'Loading settings…'}
      </div>
    )
  }

  const isSectioned = settings.sectioned_extraction === true

  return (
    <div className="p-6 max-w-2xl">
      <div className="mb-6">
        <h2 className="text-base font-semibold text-slate-800">Extraction Settings</h2>
        <p className="text-xs text-slate-500 mt-1">
          Runtime configuration for the extraction pipeline. Changes take effect on the next
          extraction call — no server restart required. Settings are persisted to{' '}
          <code className="font-mono bg-slate-100 px-1 rounded">files/runtime_settings.yaml</code>.
        </p>
      </div>

      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}
      {successMsg && (
        <div className="mb-4 bg-green-50 border border-green-200 rounded px-3 py-2 text-xs text-green-700">
          ✓ {successMsg}
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-lg px-5 divide-y divide-slate-100">

        {/* Extraction mode toggle */}
        <SettingRow
          label="Section-by-Section Extraction"
          description={
            isSectioned
              ? 'Active — each filing is extracted in 7 focused section calls. Improves field fill rate but uses more API tokens per filing.'
              : 'Inactive — single Anthropic tool call per filing (default). Fast and predictable token cost.'
          }
        >
          <div className="flex items-center gap-2">
            <span className={`text-xs font-medium ${isSectioned ? 'text-blue-700' : 'text-slate-400'}`}>
              {isSectioned ? 'Sectioned' : 'Single call'}
            </span>
            <Toggle
              checked={isSectioned}
              onChange={v => save({ sectioned_extraction: v })}
              disabled={saving}
            />
          </div>
        </SettingRow>

        {/* Section merge confidence delta */}
        <SettingRow
          label="Section Merge Confidence Δ"
          description="Minimum confidence improvement required for a later section's value to override an earlier section's value for the same field. Only applies in sectioned mode."
        >
          <div className="flex items-center gap-2">
            <NumericInput
              value={settings.section_merge_confidence_delta ?? 0.15}
              onChange={v => save({ section_merge_confidence_delta: v })}
              min={0.0}
              max={1.0}
              step={0.05}
              disabled={saving || !isSectioned}
            />
            <span className="text-xs text-slate-400 w-8">
              {((settings.section_merge_confidence_delta ?? 0.15) * 100).toFixed(0)}%
            </span>
          </div>
        </SettingRow>

        {/* Classification gate */}
        <SettingRow
          label="Classification Gate Confidence"
          description="Filings classified below this threshold are blocked from extraction until manually reviewed or re-classified. Lowering this allows borderline filings through."
        >
          <div className="flex items-center gap-2">
            <NumericInput
              value={settings.classification_gate_confidence ?? 0.80}
              onChange={v => save({ classification_gate_confidence: v })}
              min={0.0}
              max={1.0}
              step={0.05}
              disabled={saving}
            />
            <span className="text-xs text-slate-400 w-8">
              {((settings.classification_gate_confidence ?? 0.80) * 100).toFixed(0)}%
            </span>
          </div>
        </SettingRow>

      </div>

      {/* Info strip */}
      <div className="mt-4 flex flex-wrap gap-4 text-xs text-slate-400">
        <span>
          Extraction mode:{' '}
          <span className={`font-medium ${isSectioned ? 'text-blue-600' : 'text-slate-600'}`}>
            {isSectioned ? 'section-by-section (7 calls/filing)' : 'single call (1 call/filing)'}
          </span>
        </span>
        <span>
          Gate:{' '}
          <span className="font-medium text-slate-600">
            {((settings.classification_gate_confidence ?? 0.80) * 100).toFixed(0)}% confidence required
          </span>
        </span>
      </div>
    </div>
  )
}
