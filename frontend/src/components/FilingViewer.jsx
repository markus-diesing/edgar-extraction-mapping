import { useEffect, useRef, useMemo } from 'react'

/**
 * Renders the stripped plain text of a filing with optional excerpt highlighting.
 *
 * When `excerpt` changes the component finds the first occurrence of the excerpt
 * text (trying progressively shorter prefixes) and scrolls it into view.
 */
export default function FilingViewer({ text, excerpt, fieldSelected = false }) {
  const markRef = useRef(null)

  // Scroll highlighted region into view whenever excerpt OR text changes.
  // Depend on both so that if text arrives after the user has already selected
  // a field, the scroll fires once the mark is finally rendered.
  useEffect(() => {
    if (excerpt && markRef.current) {
      markRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [excerpt, text])

  const segments = useMemo(() => {
    if (!text) return null
    if (!excerpt || excerpt.trim() === '') return [{ type: 'text', content: text }]

    // Claude excerpts have spaces where the filing text may have newlines/extra whitespace.
    // Strategy: try exact match first, then fall back to a whitespace-flexible regex.
    // Try progressively shorter prefixes to handle partially paraphrased excerpts.
    let matchIdx = -1
    let matchLen = 0

    for (let len = Math.min(excerpt.length, 100); len >= 20; len -= 15) {
      const needle = excerpt.slice(0, len)

      // 1. Exact match
      const exact = text.indexOf(needle)
      if (exact !== -1) {
        matchIdx = exact
        matchLen = len
        break
      }

      // 2. Flexible whitespace — any run of whitespace in the needle matches any in the text
      try {
        const escaped  = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        const flexible = escaped.replace(/\s+/g, '\\s+')
        const re       = new RegExp(flexible, 's')
        const m        = re.exec(text)
        if (m) {
          matchIdx = m.index
          matchLen = m[0].length
          break
        }
      } catch { /* malformed regex — skip */ }
    }

    if (matchIdx === -1) return [{ type: 'text', content: text }, { type: 'notfound' }]

    return [
      { type: 'text', content: text.slice(0, matchIdx) },
      { type: 'mark', content: text.slice(matchIdx, matchIdx + matchLen) },
      { type: 'text', content: text.slice(matchIdx + matchLen) },
    ]
  }, [text, excerpt])

  if (!text) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm">
        Loading filing text…
      </div>
    )
  }

  const notFound = segments?.some(s => s.type === 'notfound')

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* Status bar — shown whenever a field is selected */}
      {fieldSelected && (
        <div className={`px-3 py-1.5 text-xs shrink-0 border-b flex items-center gap-1.5 ${
          !excerpt
            ? 'bg-slate-100 text-slate-400 border-slate-200'
            : notFound
              ? 'bg-amber-50 text-amber-700 border-amber-200'
              : 'bg-yellow-50 text-yellow-800 border-yellow-200'
        }`}>
          {!excerpt && (
            <>
              <span className="opacity-60">◌</span>
              <span>No source text — Claude inferred this value from context rather than quoting it directly</span>
            </>
          )}
          {excerpt && notFound && (
            <>
              <span>⚠</span>
              <span>Excerpt not matched verbatim in filing text</span>
            </>
          )}
          {excerpt && !notFound && (
            <>
              <span>◉</span>
              <span className="font-medium">Highlighted:</span>
              <span className="italic truncate">"{excerpt.slice(0, 100)}{excerpt.length > 100 ? '…' : ''}"</span>
            </>
          )}
        </div>
      )}

      {/* Text content */}
      <pre className="flex-1 overflow-y-auto overflow-x-auto scrollbar-thin p-4 text-xs font-mono leading-relaxed text-slate-700 whitespace-pre-wrap break-words bg-white">
        {segments?.map((seg, i) => {
          if (seg.type === 'notfound') return null
          if (seg.type === 'mark') {
            return (
              <mark
                key={i}
                ref={markRef}
                className="bg-yellow-200 rounded-sm outline outline-1 outline-yellow-400 text-slate-900"
              >
                {seg.content}
              </mark>
            )
          }
          return seg.content
        })}
      </pre>
    </div>
  )
}
