const STATUS_STYLES = {
  ingested:     'bg-slate-100 text-slate-600 border-slate-300',
  classified:   'bg-[#e8eefe] text-[#0c2fd4] border-[#0F3AF0]',
  needs_review: 'bg-[#fef8e7] text-[#7a5a00] border-[#F3B61A]',
  extracted:    'bg-[#e8eefe] text-[#0c2fd4] border-[#0F3AF0]',
  approved:     'bg-[#f0fbd3] text-[#4a7c00] border-[#83D40A]',
  exported:     'bg-[#f0fbd3] text-[#4a7c00] border-[#83D40A]',
  pending:      'bg-slate-100 text-slate-500 border-slate-200',
  accepted:     'bg-[#f0fbd3] text-[#4a7c00] border-[#83D40A]',
  corrected:    'bg-[#e8eefe] text-[#0c2fd4] border-[#0F3AF0]',
  rejected:     'bg-[#fdf0ed] text-[#8b2616] border-[#DF4830]',
  schema_error: 'bg-[#fdf0ed] text-[#8b2616] border-[#DF4830]',
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
