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

export const api = {
  health:       ()           => call('GET',    '/health'),
  search:       (body)       => call('POST',   '/ingest/search', body),
  ingest:       (body)       => call('POST',   '/ingest/filing', body),
  listFilings:  (params)     => call('GET',    `/filings${params ? '?' + new URLSearchParams(params) : ''}`),
  getFiling:    (id)         => call('GET',    `/filings/${id}`),
  getKpis:      (id)         => call('GET',    `/filings/${id}/kpis`),
  getFilingText:(id)         => call('GET',    `/filings/${id}/text`),
  deleteFiling: (id)         => call('DELETE', `/filings/${id}`),
  classify:          (id)         => call('POST',   `/classify/${id}`),
  listPrismModels:   ()           => call('GET',    '/classify/models'),
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
}
