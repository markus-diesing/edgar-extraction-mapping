import { useState, useRef, useEffect, useCallback } from 'react'
import FieldTable from './FieldTable.jsx'

/**
 * Side-by-side expert review:
 *   Left  — PRISM field table with row selection
 *   Right — original filing rendered as HTML in an iframe, with the selected
 *           field's source excerpt highlighted via postMessage
 *
 * The divider between the two panes is draggable: grab and drag left/right
 * to redistribute space between the field table and the filing viewer.
 */
export default function ExpertReview({ fields, filingId, onFieldUpdated }) {
  const [selectedField, setSelectedField] = useState(null)
  const iframeRef    = useRef(null)
  const containerRef = useRef(null)
  const [iframeReady,  setIframeReady]  = useState(false)

  // Resizable split — left pane percentage (clamped 15 – 85)
  const [splitPct,   setSplitPct]   = useState(42)
  const [isDragging, setIsDragging] = useState(false)

  const excerpt = selectedField?.source_excerpt || null

  // Reset state when the filing changes.
  useEffect(() => {
    setSelectedField(null)
    setIframeReady(false)
  }, [filingId])

  // Send highlight whenever excerpt or readiness changes.
  useEffect(() => {
    if (!iframeReady || !iframeRef.current?.contentWindow) return
    iframeRef.current.contentWindow.postMessage(
      excerpt ? { type: 'highlight', text: excerpt } : { type: 'clear' },
      '*'
    )
  }, [excerpt, iframeReady])

  const handleIframeLoad = () => {
    setIframeReady(true)
    // Re-send if a field was already selected before the iframe finished loading.
    if (excerpt && iframeRef.current?.contentWindow) {
      iframeRef.current.contentWindow.postMessage(
        { type: 'highlight', text: excerpt },
        '*'
      )
    }
  }

  // ── Drag-to-resize ──────────────────────────────────────────────────────────
  const onDividerMouseDown = useCallback((e) => {
    e.preventDefault()
    setIsDragging(true)

    const onMouseMove = (e) => {
      if (!containerRef.current) return
      const rect   = containerRef.current.getBoundingClientRect()
      const newPct = ((e.clientX - rect.left) / rect.width) * 100
      setSplitPct(Math.min(85, Math.max(15, newPct)))
    }

    const onMouseUp = () => {
      setIsDragging(false)
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup',   onMouseUp)
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup',   onMouseUp)
  }, [])

  // Status hint shown in the right-pane header.
  const hint = !selectedField
    ? '← Select a field to locate its source in the filing'
    : !excerpt
      ? 'No source excerpt recorded for this field (inferred value)'
      : '↑ Excerpt highlighted in filing'

  const hintColor = !selectedField
    ? 'text-slate-400'
    : !excerpt
      ? 'text-amber-500 italic'
      : 'text-emerald-600 font-medium'

  return (
    <div
      ref={containerRef}
      className={`flex h-full min-h-0${isDragging ? ' select-none cursor-col-resize' : ''}`}
    >

      {/* ── Left pane: PRISM fields ── */}
      <div
        className="shrink-0 flex flex-col min-h-0 overflow-hidden"
        style={{ width: `${splitPct}%` }}
      >
        <div className="px-3 py-1.5 bg-slate-50 border-b border-slate-200 shrink-0 flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">PRISM Fields</span>
          {selectedField && (
            <span className="text-xs text-blue-600 font-mono truncate max-w-[200px]" title={selectedField.field_name}>
              {selectedField.field_name}
            </span>
          )}
        </div>
        <div className="flex-1 min-h-0 overflow-hidden">
          <FieldTable
            fields={fields}
            filingId={filingId}
            onFieldUpdated={onFieldUpdated}
            selectedId={selectedField?.id}
            onSelectField={setSelectedField}
          />
        </div>
      </div>

      {/* ── Drag handle / divider ── */}
      <div
        onMouseDown={onDividerMouseDown}
        title="Drag to resize"
        className={`
          w-[5px] shrink-0 flex flex-col items-center justify-center gap-[3px]
          cursor-col-resize transition-colors duration-100 group
          ${isDragging ? 'bg-lpa-cyan' : 'bg-slate-200 hover:bg-slate-300'}
        `}
      >
        {/* Dot-grip indicator */}
        {[0, 1, 2, 3, 4].map(i => (
          <div
            key={i}
            className={`
              w-[3px] h-[3px] rounded-full pointer-events-none transition-colors
              ${isDragging ? 'bg-white' : 'bg-slate-400 opacity-40 group-hover:opacity-80'}
            `}
          />
        ))}
      </div>

      {/* ── Right pane: HTML filing viewer (iframe) ── */}
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        <div className="px-3 py-1.5 bg-slate-50 border-b border-slate-200 shrink-0 flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">EDGAR Filing</span>
          <span className={`text-xs ${hintColor}`}>{hint}</span>
        </div>
        <div className="flex-1 min-h-0 relative bg-white">
          {filingId ? (
            <iframe
              ref={iframeRef}
              key={filingId}
              src={`/api/filings/${filingId}/document`}
              onLoad={handleIframeLoad}
              className="w-full h-full border-0"
              title="EDGAR Filing"
              sandbox="allow-same-origin allow-scripts"
            />
          ) : (
            <div className="flex items-center justify-center h-full text-slate-400 text-sm">
              No filing selected
            </div>
          )}
        </div>
      </div>

    </div>
  )
}
