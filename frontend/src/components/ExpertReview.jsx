import { useState, useRef, useEffect } from 'react'
import FieldTable from './FieldTable.jsx'

/**
 * Side-by-side expert review:
 *   Left  — PRISM field table with row selection
 *   Right — original filing rendered as HTML in an iframe, with the selected
 *           field's source excerpt highlighted via postMessage
 *
 * The iframe loads /api/filings/{id}/document which serves the raw HTML with:
 *   - A <base> tag so relative images/resources resolve from EDGAR's archive.
 *   - An injected highlight script that listens for postMessage events.
 */
export default function ExpertReview({ fields, filingId, onFieldUpdated }) {
  const [selectedField, setSelectedField] = useState(null)
  const iframeRef   = useRef(null)
  const [iframeReady, setIframeReady] = useState(false)

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
    <div className="flex h-full min-h-0">

      {/* ── Left pane: PRISM fields ── */}
      <div className="w-[42%] shrink-0 flex flex-col min-h-0 border-r border-slate-200">
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
