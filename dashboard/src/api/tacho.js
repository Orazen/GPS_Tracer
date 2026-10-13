// Tachograph service client.
//
// This talks to `/tacho/*` on the dashboard's own origin, never to the
// tachograph API directly. That is not a preference — it is the only correct
// option, because the tachograph API authenticates callers with a *service
// token* and serves driver personal data. A browser holding that token would be
// equivalent to publishing it.
//
// `dashboard/server.mjs` is the only holder of the token. It establishes who the
// user is from their Traccar session and forwards that identity, which the
// tachograph service records in its audit log. So the browser here never sends
// credentials of any kind: it just makes a same-origin request carrying the
// session cookie it already has.

const BASE = '/tacho'

async function req(path, { method = 'GET', body, json = false } = {}) {
  const opts = { method, credentials: 'include', headers: {} }

  if (body instanceof FormData) {
    // Let the browser set the multipart boundary itself.
    opts.body = body
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  if (json) opts.headers.Accept = 'application/json'

  const res = await fetch(BASE + path, opts)
  if (res.status === 401) {
    const e = new Error('unauthorised')
    e.auth = true
    throw e
  }
  if (res.status === 403) {
    const e = new Error('forbidden')
    e.forbidden = true
    throw e
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    let detail = text.slice(0, 200)
    try {
      detail = JSON.parse(text).detail ?? detail
    } catch {
      /* not JSON: keep the raw text */
    }
    const e = new Error(`${method} ${path} -> ${res.status} ${detail}`)
    e.status = res.status
    throw e
  }

  if (json) return res.json()
  const t = await res.text()
  return t ? JSON.parse(t) : {}
}

/** `YYYY-MM-DD` in local time. `toISOString()` would shift the day across midnight. */
export const isoDay = (d) => {
  const x = d instanceof Date ? d : new Date(d)
  const p = (n) => String(n).padStart(2, '0')
  return `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}`
}

export const daysAgo = (n) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return isoDay(d)
}

export const tacho = {
  /**
   * Versions and the validation status of the engine.
   *
   * `calculations_validated_against_reference` is shown in the UI rather than
   * kept for the docs, because the moment somebody reads a figure off this screen
   * they need to know it is not a legal finding.
   */
  meta: () => req('/api/meta', { json: true }),

  // ---- imports ----------------------------------------------------------
  imports: ({ status, limit = 100, offset = 0 } = {}) => {
    const p = new URLSearchParams()
    if (status) p.set('status', status)
    p.set('limit', limit)
    p.set('offset', offset)
    return req(`/api/imports?${p}`, { json: true })
  },

  import: (id) => req(`/api/imports/${id}`, { json: true }),

  timeline: (id) => req(`/api/imports/${id}/timeline`, { json: true }),

  /**
   * Upload a download. Returns 202 with an import id; parsing happens in the
   * worker, so the row stays `pending` until the worker has been through it.
   *
   * `onProgress` cannot be reported by fetch, so the UI shows an indeterminate
   * state. Stating the limitation is better than faking a percentage.
   */
  upload: (file, declaredKind = 'unknown') => {
    const form = new FormData()
    form.append('file', file, file.name)
    form.append('declared_kind', declaredKind)
    return req('/api/imports', { method: 'POST', body: form, json: true })
  },

  // ---- drivers and activity --------------------------------------------
  drivers: () => req('/api/drivers', { json: true }),

  days: ({ driverKey, dateFrom, dateTo, limit = 400 } = {}) => {
    const p = new URLSearchParams()
    if (driverKey) p.set('driver_key', driverKey)
    if (dateFrom) p.set('date_from', dateFrom)
    if (dateTo) p.set('date_to', dateTo)
    p.set('limit', limit)
    return req(`/api/days?${p}`, { json: true })
  },

  coverage: (driverKey, dateFrom, dateTo) =>
    req(
      `/api/coverage?driver_key=${encodeURIComponent(driverKey)}` +
        `&date_from=${dateFrom}&date_to=${dateTo}`,
      { json: true }
    ),

  dailySummary: (driverKey, dateFrom, dateTo) =>
    req(
      `/api/summary/daily?driver_key=${encodeURIComponent(driverKey)}` +
        `&date_from=${dateFrom}&date_to=${dateTo}`,
      { json: true }
    ),

  // ---- findings ---------------------------------------------------------
  /**
   * Run the engine over a period and store the result.
   *
   * `dataAgeDays` has no sensible default: it drives the staleness check, and
   * guessing it would make the result depend on something the caller did not
   * choose. The caller passes the age of the newest record it actually has.
   */
  calculate: (driverKey, periodStart, periodEnd, dataAgeDays) =>
    req('/api/calculations', {
      method: 'POST',
      json: true,
      body: {
        driver_key: driverKey,
        period_start: periodStart,
        period_end: periodEnd,
        data_age_days: dataAgeDays,
      },
    }),

  calculations: (driverKey, limit = 50) => {
    const p = new URLSearchParams()
    if (driverKey) p.set('driver_key', driverKey)
    p.set('limit', limit)
    return req(`/api/calculations?${p}`, { json: true })
  },

  // ---- audit ------------------------------------------------------------
  /**
   * The audit trail. `owner` only — the service answers 403 for anyone else, and
   * the UI shows that as "not permitted" rather than as an error, which is what
   * it is.
   */
  audit: (limit = 100) => req(`/api/audit?limit=${limit}`, { json: true }),

  // ---- export -----------------------------------------------------------
  /**
   * The CSV's own URL, for a plain link. The browser downloads it directly and
   * the response carries its provenance header, so nothing is re-derived here.
   */
  activityCsvUrl: (driverKey, dateFrom, dateTo) =>
    `${BASE}/api/reports/activity.csv?driver_key=${encodeURIComponent(driverKey)}` +
    `&date_from=${dateFrom}&date_to=${dateTo}`,
}

/** `8h 15m` from minutes. Used everywhere a duration is shown. */
export function hhmm(minutes) {
  if (minutes == null) return '—'
  const m = Math.max(0, Math.round(minutes))
  const h = Math.floor(m / 60)
  const mm = m % 60
  if (h === 0) return `${mm}m`
  return mm === 0 ? `${h}h` : `${h}h ${String(mm).padStart(2, '0')}m`
}
