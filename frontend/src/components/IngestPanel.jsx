import { useState } from 'react'
import { api } from '../api.js'

export default function IngestPanel({ onIngested }) {
  const [query, setQuery]     = useState('')
  const [startDate, setStart] = useState('')
  const [endDate, setEnd]     = useState('')
  const [searching, setSearching] = useState(false)
  const [ingesting, setIngesting] = useState(null)
  const [results, setResults]     = useState(null)
  const [error, setError]         = useState('')
  const [directCusip, setDirectCusip] = useState('')
  const [directAcc,   setDirectAcc]   = useState('')
  const [directCik,   setDirectCik]   = useState('')

  const doSearch = async () => {
    setError('')
    setSearching(true)
    setResults(null)
    try {
      const data = await api.search({ query, start_date: startDate || null, end_date: endDate || null })
      setResults(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setSearching(false)
    }
  }

  const doIngestHit = async (hit) => {
    setIngesting(hit.accession_number)
    setError('')
    try {
      const filing = await api.ingest({
        accession_number: hit.accession_number,
        cik: hit.cik,
        cusip: query.length === 9 ? query.toUpperCase() : hit.cusip_hint,
        issuer_name: hit.entity_name,
        filing_date: hit.filing_date,
      })
      onIngested(filing)
      setResults(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setIngesting(null)
    }
  }

  const doDirectIngest = async () => {
    if (!directAcc || !directCik) { setError('Accession number and CIK are required'); return }
    setIngesting('direct')
    setError('')
    try {
      const filing = await api.ingest({
        accession_number: directAcc,
        cik: directCik,
        cusip: directCusip || null,
      })
      onIngested(filing)
      setDirectCusip(''); setDirectAcc(''); setDirectCik('')
    } catch (e) {
      setError(e.message)
    } finally {
      setIngesting(null)
    }
  }

  return (
    <div className="p-4 space-y-4">
      {/* EDGAR Search */}
      <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1">
          <span>🔍</span> Search EDGAR
        </h3>
        <div className="space-y-2">
          <input
            className="w-full border border-slate-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            placeholder="CUSIP or search term (e.g. 48136GPC8)"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && doSearch()}
          />
          <div className="flex gap-2">
            <input type="date" className="flex-1 border border-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
              value={startDate} onChange={e => setStart(e.target.value)} />
            <input type="date" className="flex-1 border border-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
              value={endDate} onChange={e => setEnd(e.target.value)} />
          </div>
          <button
            onClick={doSearch}
            disabled={!query || searching}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 text-white text-sm font-medium rounded px-3 py-1.5 transition-colors"
          >
            {searching ? 'Searching…' : 'Search 424B2'}
          </button>
        </div>

        {/* Search results */}
        {results && (
          <div className="mt-3 space-y-1.5">
            <p className="text-xs text-slate-500">{results.total} result{results.total !== 1 ? 's' : ''}</p>
            {results.hits?.map(h => (
              <div key={h.accession_number} className="border border-slate-200 rounded p-2 bg-slate-50 text-xs">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-medium text-slate-800 truncate">{h.entity_name}</p>
                    <p className="text-slate-500 font-mono">{h.accession_number}</p>
                    <p className="text-slate-400">{h.filing_date}</p>
                    {h.known_payout_type && (
                      <p className="text-blue-600 mt-0.5">→ {h.known_payout_type}</p>
                    )}
                  </div>
                  <button
                    onClick={() => doIngestHit(h)}
                    disabled={ingesting === h.accession_number}
                    className="shrink-0 bg-blue-100 hover:bg-blue-200 text-blue-700 font-medium rounded px-2 py-1 transition-colors disabled:opacity-50"
                  >
                    {ingesting === h.accession_number ? '…' : 'Ingest'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Direct ingest by accession number */}
      <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1">
          <span>📥</span> Direct Ingest
        </h3>
        <div className="space-y-2">
          <input
            className="w-full border border-slate-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            placeholder="CUSIP (optional)"
            value={directCusip}
            onChange={e => setDirectCusip(e.target.value.toUpperCase())}
          />
          <input
            className="w-full border border-slate-200 rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
            placeholder="Accession number (e.g. 0001234567-26-000001)"
            value={directAcc}
            onChange={e => setDirectAcc(e.target.value)}
          />
          <input
            className="w-full border border-slate-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            placeholder="CIK"
            value={directCik}
            onChange={e => setDirectCik(e.target.value)}
          />
          <button
            onClick={doDirectIngest}
            disabled={ingesting === 'direct' || !directAcc || !directCik}
            className="w-full bg-slate-700 hover:bg-slate-800 disabled:bg-slate-300 text-white text-sm font-medium rounded px-3 py-1.5 transition-colors"
          >
            {ingesting === 'direct' ? 'Ingesting…' : 'Ingest Filing'}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-xs text-red-700">
          {error}
        </div>
      )}
    </div>
  )
}
