/**
 * AdminLogViewer.jsx
 *
 * Displays the backend application log (logs/app.log) parsed into structured
 * entries.  Supports level filtering, module filtering, text search, and
 * a download link for the raw file.
 *
 * Data source: GET /api/admin/logs
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api.js'

// Lines-per-page selector options
const LINE_OPTIONS = [50, 200, 500]

// Module name suggestions for the filter autocomplete datalist.
// Covers all logger names used in the backend (logging.getLogger(__name__)).
const MODULE_SUGGESTIONS = [
  'main',
  'extract.extractor',
  'extract.html_extractor',
  'extract.label_mapper',
  'classify.router',
  'extract.router',
  'ingest.router',
  'hints.router',
  'admin.router',
  'admin.schema_router',
  'admin.label_map_router',
  'schema_diff',
  'schema_loader',
  'hints_loader',
  'sections.router',
  'settings.router',
  'export.router',
]

// Level filter options in severity order
const LEVEL_OPTIONS = [
  { value: 'ALL',     label: 'All levels' },
  { value: 'INFO',    label: 'INFO+'      },
  { value: 'WARNING', label: 'WARN+'      },
  { value: 'ERROR',   label: 'ERROR only' },
]

// Row background and level-pill colours per severity
const LEVEL_STYLES = {
  ERROR:    { row: 'bg-red-50 border-l-4 border-red-400',    pill: 'bg-red-100 text-red-700 border-red-300'    },
  WARNING:  { row: 'bg-amber-50 border-l-4 border-amber-400', pill: 'bg-amber-100 text-amber-700 border-amber-300' },
  INFO:     { row: 'bg-white',                                pill: 'bg-slate-100 text-slate-600 border-slate-200' },
  DEBUG:    { row: 'bg-white',                                pill: 'bg-slate-50  text-slate-400 border-slate-100' },
}
const defaultStyle = LEVEL_STYLES.INFO

function levelStyle(level) {
  return LEVEL_STYLES[level?.toUpperCase()] || defaultStyle
}

function LevelPill({ level }) {
  const { pill } = levelStyle(level)
  return (
    <span className={`inline-block border rounded px-1.5 py-0 text-xs font-semibold w-16 text-center ${pill}`}>
      {level}
    </span>
  )
}

export default function AdminLogViewer() {
  const [lines,        setLines]        = useState(200)
  const [level,        setLevel]        = useState('ALL')
  const [moduleFilter, setModuleFilter] = useState('')
  const [search,       setSearch]       = useState('')
  const [autoRefresh,  setAutoRefresh]  = useState(false)

  const [entries,  setEntries]  = useState([])
  const [meta,     setMeta]     = useState(null)   // { total_matched, file_size_bytes, log_path }
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState('')

  const intervalRef = useRef(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await api.adminLogs({ lines, level })
      setEntries(data.entries || [])
      setMeta({
        total_matched:    data.total_matched,
        file_size_bytes:  data.file_size_bytes,
        log_path:         data.log_path,
      })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [lines, level])

  // Load on mount and whenever lines/level change
  useEffect(() => { load() }, [load])

  // Auto-refresh interval
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    if (autoRefresh) {
      intervalRef.current = setInterval(load, 10_000)
    }
    return () => clearInterval(intervalRef.current)
  }, [autoRefresh, load])

  // Client-side filters (module name + text search — applied after server fetch)
  const filtered = entries.filter(e => {
    if (moduleFilter && !e.name.toLowerCase().includes(moduleFilter.toLowerCase())) return false
    if (search && !e.message.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  const fmtBytes = (b) => b == null ? '' : b < 1024 ? `${b} B` : `${(b / 1024).toFixed(1)} KB`

  return (
    <div className="flex flex-col h-full min-h-0">

      {/* ── Toolbar ── */}
      <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-slate-200 bg-slate-50 shrink-0">

        {/* Lines selector */}
        <div className="flex items-center gap-1">
          <span className="text-xs text-slate-400 mr-1">Lines</span>
          {LINE_OPTIONS.map(n => (
            <button
              key={n}
              onClick={() => setLines(n)}
              className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                lines === n
                  ? 'bg-slate-700 text-white border-slate-700'
                  : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
              }`}
            >
              {n}
            </button>
          ))}
        </div>

        <div className="w-px h-4 bg-slate-200" />

        {/* Level filter */}
        <select
          value={level}
          onChange={e => setLevel(e.target.value)}
          className="text-xs border border-slate-200 rounded px-2 py-1 bg-white text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-400"
        >
          {LEVEL_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        {/* Module filter */}
        <input
          className="text-xs border border-slate-200 rounded px-2 py-1 w-44 focus:outline-none focus:ring-1 focus:ring-blue-400"
          placeholder="Module…"
          value={moduleFilter}
          onChange={e => setModuleFilter(e.target.value)}
          list="module-suggestions"
        />
        <datalist id="module-suggestions">
          {MODULE_SUGGESTIONS.map(m => <option key={m} value={m} />)}
        </datalist>

        {/* Text search */}
        <input
          className="text-xs border border-slate-200 rounded px-2 py-1 flex-1 min-w-32 focus:outline-none focus:ring-1 focus:ring-blue-400"
          placeholder="Search messages…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />

        <div className="w-px h-4 bg-slate-200" />

        {/* Auto-refresh toggle */}
        <label className="flex items-center gap-1.5 text-xs text-slate-500 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={e => setAutoRefresh(e.target.checked)}
            className="rounded"
          />
          Auto (10 s)
        </label>

        {/* Manual refresh */}
        <button
          onClick={load}
          disabled={loading}
          className="text-xs px-2.5 py-1 bg-white border border-slate-200 rounded text-slate-600 hover:bg-slate-50 transition-colors disabled:opacity-40"
          title="Refresh now"
        >
          {loading ? '…' : '↺'}
        </button>

        {/* Download */}
        <a
          href={api.adminLogsDownloadUrl()}
          download="edgar_app.log"
          className="text-xs px-2.5 py-1 bg-white border border-slate-200 rounded text-slate-600 hover:bg-slate-50 transition-colors"
          title="Download full log file"
        >
          ↓ Download
        </a>
      </div>

      {/* ── Error banner ── */}
      {error && (
        <div className="px-4 py-2 bg-red-50 border-b border-red-200 text-xs text-red-700 shrink-0">
          {error}
        </div>
      )}

      {/* ── Log table ── */}
      <div className="flex-1 overflow-y-auto scrollbar-thin min-h-0 font-mono text-xs">
        {filtered.length === 0 && !loading && (
          <div className="flex items-center justify-center h-32 text-slate-400 text-sm font-sans">
            {entries.length === 0 ? 'No log entries found.' : 'No entries match the current filter.'}
          </div>
        )}
        <table className="w-full border-collapse">
          <tbody>
            {filtered.map((e, i) => {
              const { row } = levelStyle(e.level)
              return (
                <tr key={i} className={`border-b border-slate-100 ${row}`}>
                  <td className="px-3 py-1 text-slate-400 whitespace-nowrap align-top w-44">
                    {e.ts}
                  </td>
                  <td className="px-1 py-1 align-top w-20">
                    <LevelPill level={e.level} />
                  </td>
                  <td className="px-2 py-1 text-blue-700 whitespace-nowrap align-top w-36">
                    {e.name}
                  </td>
                  <td className="px-2 py-1 text-slate-700 align-top break-all whitespace-pre-wrap">
                    {e.message}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* ── Footer ── */}
      {meta && (
        <div className="px-4 py-1.5 border-t border-slate-200 bg-slate-50 shrink-0 flex items-center gap-4 text-xs text-slate-400">
          <span>
            Showing <strong className="text-slate-600">{filtered.length}</strong>
            {filtered.length !== meta.total_matched && (
              <> of <strong>{meta.total_matched}</strong> matched</>
            )}
            {' '}entries
          </span>
          <span>File: <code className="font-mono">{meta.log_path}</code></span>
          <span>{fmtBytes(meta.file_size_bytes)}</span>
          {autoRefresh && <span className="text-blue-500">● live</span>}
        </div>
      )}
    </div>
  )
}
