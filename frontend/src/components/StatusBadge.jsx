const STATUS_STYLES = {
  ingested:    'bg-slate-100 text-slate-700 border-slate-300',
  classified:  'bg-blue-100 text-blue-700 border-blue-300',
  needs_review:'bg-yellow-100 text-yellow-800 border-yellow-300',
  extracted:   'bg-indigo-100 text-indigo-700 border-indigo-300',
  approved:    'bg-green-100 text-green-700 border-green-300',
  exported:    'bg-emerald-100 text-emerald-700 border-emerald-300',
  pending:     'bg-slate-100 text-slate-500 border-slate-200',
  accepted:    'bg-green-100 text-green-700 border-green-200',
  corrected:   'bg-blue-100 text-blue-700 border-blue-200',
  rejected:    'bg-red-100 text-red-600 border-red-200',
}

export default function StatusBadge({ status, small }) {
  const cls = STATUS_STYLES[status] || 'bg-slate-100 text-slate-600 border-slate-200'
  const size = small ? 'text-xs px-1.5 py-0.5' : 'text-xs px-2 py-0.5'
  return (
    <span className={`inline-block border rounded font-medium ${size} ${cls}`}>
      {status?.replace('_', ' ')}
    </span>
  )
}
