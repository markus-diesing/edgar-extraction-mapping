import { useState, useEffect, useCallback } from 'react'
import { api } from './api.js'
import IngestPanel from './components/IngestPanel.jsx'
import FilingList from './components/FilingList.jsx'
import FilingDetail from './components/FilingDetail.jsx'
import HintsEditor from './components/HintsEditor.jsx'
import SectionPromptsEditor from './components/SectionPromptsEditor.jsx'
import ExtractionSettings from './components/ExtractionSettings.jsx'

function HealthDot({ healthy }) {
  return (
    <span className={`inline-block w-2 h-2 rounded-full ${healthy ? 'bg-green-400' : 'bg-red-400'}`} />
  )
}

export default function App() {
  const [filings,      setFilings]      = useState([])
  const [selectedId,   setSelectedId]   = useState(null)
  const [health,       setHealth]       = useState(null)
  const [sideTab,      setSideTab]      = useState('filings')  // 'filings' | 'ingest'
  const [loadingList,  setLoadingList]  = useState(false)
  const [sidebarOpen,  setSidebarOpen]  = useState(true)
  const [mainView,     setMainView]     = useState('filings')  // 'filings' | 'expert'
  const [expertTab,    setExpertTab]    = useState('hints')    // 'hints' | 'sections' | 'extraction'

  const loadFilings = useCallback(async () => {
    setLoadingList(true)
    try {
      const data = await api.listFilings()
      setFilings(data)
    } catch {
      // silent — backend may not be running yet
    } finally {
      setLoadingList(false)
    }
  }, [])

  const loadHealth = useCallback(async () => {
    try {
      const h = await api.health()
      setHealth(h)
    } catch {
      setHealth(null)
    }
  }, [])

  useEffect(() => {
    loadHealth()
    loadFilings()
    const interval = setInterval(loadHealth, 30_000)
    return () => clearInterval(interval)
  }, [])

  const onIngested = (filing) => {
    setFilings(prev => {
      const exists = prev.find(f => f.id === filing.id)
      if (exists) return prev.map(f => f.id === filing.id ? filing : f)
      return [filing, ...prev]
    })
    setSelectedId(filing.id)
    setSideTab('filings')
  }

  const onFilingUpdated = useCallback(() => loadFilings(), [loadFilings])

  const isHealthy = health?.status === 'ok'

  return (
    <div className="flex flex-col h-screen bg-slate-100">
      {/* Top bar */}
      <header className="flex items-center justify-between px-5 py-3 bg-lpa-blue shadow-sm shrink-0"
        style={{ background: '#1e3a5f' }}>
        <div className="flex items-center gap-3">
          <span className="text-white font-bold text-base tracking-tight">EDGAR Extraction</span>
          <span className="text-slate-400 text-sm hidden sm:inline">& PRISM Mapping</span>
        </div>
        <div className="flex items-center gap-4">
          {/* Top-level nav */}
          <nav className="flex items-center gap-1">
            {[['filings', 'Filings'], ['expert', 'Expert ⚙']].map(([view, label]) => (
              <button
                key={view}
                onClick={() => setMainView(view)}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                  mainView === view
                    ? 'bg-white/20 text-white'
                    : 'text-slate-300 hover:text-white hover:bg-white/10'
                }`}
              >
                {label}
              </button>
            ))}
          </nav>

          {health && (
            <div className="flex items-center gap-2 text-xs text-slate-300">
              <HealthDot healthy={isHealthy} />
              <span>{isHealthy ? 'Backend OK' : 'Backend down'}</span>
              {health.prism_models && (
                <span className="text-slate-400">
                  · {health.prism_models.length} models
                </span>
              )}
              {!health.anthropic_key_set && (
                <span className="text-amber-400">· API key missing</span>
              )}
            </div>
          )}
        </div>
      </header>

      {/* Main layout */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* Expert settings view — full-width, no sidebar */}
        {mainView === 'expert' && (
          <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
            {/* Expert settings tab bar */}
            <div className="flex border-b border-slate-200 bg-white shrink-0 px-4">
              {[['hints', 'Field Hints'], ['sections', 'Section Prompts'], ['extraction', 'Extraction Settings']].map(([tab, label]) => (
                <button
                  key={tab}
                  onClick={() => setExpertTab(tab)}
                  className={`px-4 py-2.5 text-xs font-semibold border-b-2 transition-colors ${
                    expertTab === tab
                      ? 'border-blue-500 text-blue-600'
                      : 'border-transparent text-slate-500 hover:text-slate-700'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="flex-1 min-h-0 overflow-hidden">
              {expertTab === 'hints'
                ? <HintsEditor />
                : expertTab === 'sections'
                  ? <SectionPromptsEditor />
                  : <ExtractionSettings />
              }
            </div>
          </div>
        )}

        {/* Filings view — sidebar + detail */}
        {mainView === 'filings' && <>
        {/* Left sidebar */}
        {sidebarOpen ? (
          <div className="w-72 flex flex-col shrink-0 bg-white border-r border-slate-200 overflow-hidden">
            {/* Tab switcher + collapse button */}
            <div className="flex border-b border-slate-200 shrink-0">
              {[['filings', `Filings (${filings.length})`], ['ingest', 'Ingest']].map(([tab, label]) => (
                <button
                  key={tab}
                  onClick={() => setSideTab(tab)}
                  className={`flex-1 py-2.5 text-xs font-semibold transition-colors ${
                    sideTab === tab
                      ? 'text-blue-600 border-b-2 border-blue-600 bg-white'
                      : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
                  }`}
                >
                  {label}
                </button>
              ))}
              <button
                onClick={() => setSidebarOpen(false)}
                className="px-2 text-slate-400 hover:text-slate-600 hover:bg-slate-50 border-l border-slate-200 transition-colors shrink-0"
                title="Collapse sidebar"
              >
                ‹
              </button>
            </div>

            {/* Tab content */}
            <div className="flex-1 min-h-0 overflow-hidden">
              {sideTab === 'filings' ? (
                <FilingList
                  filings={filings}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  onRefresh={loadFilings}
                />
              ) : (
                <div className="h-full overflow-y-auto scrollbar-thin">
                  <IngestPanel onIngested={onIngested} />
                </div>
              )}
            </div>
          </div>
        ) : (
          /* Collapsed sidebar — thin strip with expand button */
          <div className="w-8 shrink-0 flex flex-col bg-white border-r border-slate-200">
            <button
              onClick={() => setSidebarOpen(true)}
              className="flex-1 flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-50 transition-colors text-base"
              title="Expand sidebar"
            >
              <span style={{ writingMode: 'vertical-rl', textOrientation: 'mixed', transform: 'rotate(180deg)', fontSize: '10px', letterSpacing: '0.05em' }}
                className="text-slate-400 font-medium select-none">
                FILINGS
              </span>
            </button>
            <button
              onClick={() => setSidebarOpen(true)}
              className="py-3 flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-50 transition-colors border-t border-slate-200 text-sm"
              title="Expand sidebar"
            >
              ›
            </button>
          </div>
        )}

        {/* Main content */}
        <div className="flex-1 min-w-0 overflow-hidden bg-white">
          <FilingDetail
            filingId={selectedId}
            onFilingUpdated={onFilingUpdated}
          />
        </div>
        </>}

      </div>
    </div>
  )
}
