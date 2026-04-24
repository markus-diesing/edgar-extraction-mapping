const call = async (method, path, body) => {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 204) return null
  const data = await res.json().catch(() => ({ detail: res.statusText }))
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
  return data
}

/** Multipart / FormData upload helper (no Content-Type header — browser sets boundary). */
const upload = async (path, formData) => {
  const res = await fetch(`/api${path}`, { method: 'POST', body: formData })
  if (res.status === 204) return null
  const data = await res.json().catch(() => ({ detail: res.statusText }))
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
  return data
}

export const api = {
  health:       ()           => call('GET',    '/health'),
  search:       (body)       => call('POST',   '/ingest/search', body),
  ingest:       (body)       => call('POST',   '/ingest/filing', body),
  listFilings:  (params)     => call('GET',    `/filings${params ? '?' + new URLSearchParams(params) : ''}`),
  getFiling:    (id)         => call('GET',    `/filings/${id}`),
  getKpis:      (id)         => call('GET',    `/filings/${id}/kpis`),
  getFilingText:(id)         => call('GET',    `/filings/${id}/text`),
  deleteFiling: (id)         => call('DELETE', `/filings/${id}`),
  classify:              (id)       => call('POST',   `/classify/${id}`),
  confirmClassification: (id, body) => call('POST',   `/classify/${id}/confirm`, body),
  listPrismModels:   ()             => call('GET',    '/classify/models'),
  resetClassification: (id)       => call('POST',   `/filings/${id}/reset-classification`),
  classifyOverride:  (id, body)   => call('POST',   `/filings/${id}/classify-override`, body),
  extract:      (id)         => call('POST',   `/extract/${id}`),
  reextract:    (id)         => call('POST',   `/extract/${id}/reextract`),
  getResults:   (id)         => call('GET',    `/extract/${id}/results`),
  updateField:  (fid, fldId, body) => call('PATCH', `/extract/${fid}/fields/${fldId}`, body),
  approve:      (id)         => call('POST',   `/extract/${id}/approve`),
  unapprove:    (id)         => call('POST',   `/extract/${id}/unapprove`),
  exportFiling: (id)         => call('POST',   `/export/${id}`),
  batchExport:  ()           => call('POST',   '/export/batch'),
  listExports:  ()           => call('GET',    '/export/list'),
  getUsage:     ()           => call('GET',    '/usage'),

  // Hints CRUD
  listHints:              ()                       => call('GET',  '/hints'),
  getCrossIssuerHints:    ()                       => call('GET',  '/hints/cross-issuer'),
  updateCrossIssuerHints: (body)                   => call('PUT',  '/hints/cross-issuer', body),
  getIssuerHints:         (slug)                   => call('GET',  `/hints/issuers/${slug}`),
  updateIssuerHints:      (slug, body)             => call('PUT',  `/hints/issuers/${slug}`, body),
  getIssuerFieldHint:     (slug, fieldPath)        => call('GET',  `/hints/issuers/${slug}/fields/${encodeURIComponent(fieldPath)}`),
  updateIssuerFieldHint:  (slug, fieldPath, body)  => call('PUT',  `/hints/issuers/${slug}/fields/${encodeURIComponent(fieldPath)}`, body),
  updateCrossFieldHint:   (fieldPath, body)        => call('PUT',  `/hints/cross-issuer/fields/${encodeURIComponent(fieldPath)}`, body),

  // Sections (Expert Settings)
  listSections:      ()                    => call('GET', '/sections'),
  getSection:        (name)                => call('GET', `/sections/${name}`),
  updateSection:     (name, updates)       => call('PUT', `/sections/${name}`, updates),
  updateSectionNote: (name, system_note)   => call('PUT', `/sections/${name}/system_note`, { system_note }),

  // Runtime settings (Expert Settings → Extraction Settings)
  getSettings:       ()       => call('GET',  '/settings'),
  updateSettings:    (body)   => call('PUT',  '/settings', body),

  // Admin — Log viewer
  adminLogs:         (params) => call('GET', `/admin/logs${params ? '?' + new URLSearchParams(params) : ''}`),
  adminLogsDownloadUrl: ()    => '/api/admin/logs/download',   // direct URL — use as <a href> for native download

  // Admin — Cost & Usage
  adminUsageSummary:  ()              => call('GET', '/admin/usage/summary'),
  adminUsageTimeline: (granularity)   => call('GET', `/admin/usage/timeline?granularity=${granularity}`),

  // Label Map (Expert Settings)
  labelMapEntries:      ()                        => call('GET',    '/admin/label-map/entries'),
  labelMapAddEntry:     (label, field_path)       => call('POST',   '/admin/label-map/entries', { label, field_path }),
  labelMapRemoveEntry:  (label_norm)              => call('DELETE', '/admin/label-map/entries', { label_norm }),
  labelMapMisses:       (includeDismissed = false) => call('GET',  `/admin/label-map/misses?include_dismissed=${includeDismissed}`),
  labelMapResolveMiss:  (id, field_path)          => call('POST',   `/admin/label-map/misses/${id}/resolve`, { field_path }),
  labelMapDismissMiss:  (id)                      => call('DELETE', `/admin/label-map/misses/${id}`),
  labelMapDismissAll:   ()                        => call('DELETE', '/admin/label-map/misses'),
  labelMapFieldPaths:   ()                        => call('GET',    '/admin/label-map/field-paths'),

  // Schema management
  schemaStatus:          ()           => call('GET',    '/admin/schema/status'),
  schemaFetch:           ()           => call('POST',   '/admin/schema/fetch'),
  schemaPendingDiff:     (fetchId)    => call('GET',    `/admin/schema/pending/${fetchId}`),
  schemaActivate:        (fetchId)    => call('POST',   `/admin/schema/pending/${fetchId}/activate`),
  schemaDiscard:         (fetchId)    => call('DELETE', `/admin/schema/pending/${fetchId}`),

  // ── Underlying securities ─────────────────────────────────────────────────

  /** Resolve an identifier to CIK + ticker (no DB write). */
  underlyingResolve:           (identifier)       => call('GET', `/underlying/resolve?identifier=${encodeURIComponent(identifier)}`),

  /** Start an async ingest job.  Returns {job_id, status, total}. */
  underlyingIngest:            (body)             => call('POST', '/underlying/ingest', body),

  /** Upload a CSV file (one 'identifier' column).  Returns {job_id, status, total}. */
  underlyingIngestCsv: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return upload('/underlying/ingest/csv', fd)
  },

  /** Poll an ingest job by ID. */
  underlyingJobStatus:         (jobId)            => call('GET',    `/underlying/jobs/${jobId}`),

  /** List underlying securities (paginated + filterable). */
  underlyingList:              (params)           => call('GET',    `/underlying/${params ? '?' + new URLSearchParams(params) : ''}`),

  /** Fetch full detail for one underlying security (includes field_results). */
  underlyingGet:               (id)               => call('GET',    `/underlying/${id}`),

  /** Update / review a single extracted field. */
  underlyingUpdateField:       (id, name, body)   => call('PUT',    `/underlying/${id}/fields/${name}`, body),

  /** Approve a security (set status → 'approved'). */
  underlyingApprove:           (id)               => call('POST',   `/underlying/${id}/approve`),

  /** Re-queue a security for a full data refresh. */
  underlyingRefetch:           (id)               => call('POST',   `/underlying/${id}/refetch`),

  /** Soft-delete (archive) a security. */
  underlyingDelete:            (id)               => call('DELETE', `/underlying/${id}`),

  /** Export one security as a JSON object. */
  underlyingExportOne:         (id)               => call('GET',    `/underlying/${id}/export`),

  /** Bulk-export all securities matching a status (default: approved). */
  underlyingBulkExport:        (status = 'approved') => call('GET', `/underlying/export?status=${status}`),

  /** Get current field configuration. */
  underlyingFieldConfig:       ()                 => call('GET',    '/underlying/field-config'),

  /** Update field configuration (enable/disable, reorder, rename). */
  underlyingUpdateFieldConfig: (body)             => call('PUT',    '/underlying/field-config', body),

  /** Link an underlying security to a 424B2 filing. */
  underlyingLinkFiling:        (id, filingId)     => call('POST',   `/underlying/${id}/links`, { filing_id: filingId }),

  /** Remove the link between an underlying and a filing. */
  underlyingUnlinkFiling:      (id, filingId)     => call('DELETE', `/underlying/${id}/links/${filingId}`),
}
