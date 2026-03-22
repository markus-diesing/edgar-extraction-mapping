import { useState } from 'react'
import AdminLogViewer from './AdminLogViewer.jsx'
import AdminUsage from './AdminUsage.jsx'

const TABS = [
  { id: 'logs',  label: 'Application Log' },
  { id: 'usage', label: 'Cost & Usage'     },
]

export default function AdminPanel() {
  const [activeTab, setActiveTab] = useState('logs')

  return (
    <div className="flex flex-col h-full min-h-0 bg-white">
      {/* Tab bar */}
      <div className="flex border-b border-slate-200 bg-white shrink-0 px-4">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`px-4 py-2.5 text-xs font-semibold border-b-2 transition-colors ${
              activeTab === id
                ? 'border-lpa-cyan text-lpa-cyan'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {activeTab === 'logs'  && <AdminLogViewer />}
        {activeTab === 'usage' && <AdminUsage />}
      </div>
    </div>
  )
}
