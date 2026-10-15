// Traccar 6.16 REST client.
//
// Three things that will bite you and are handled here:
//  1. Auth is a JSESSIONID cookie, NOT a bearer token. There is no token in the
//     login response body -- it returns the User object.
//  2. Login takes `email`, not `username`.
//  3. POST /api/positions is 405 (read-only). Positions only arrive over the
//     protocol ports (GT06 :5023, OsmAnd :5055). Don't try to inject from here.
//
// Multi-tenancy is handled by Traccar itself: the API only ever returns devices
// the authenticated user is permitted to see. A client = one Traccar user.

const BASE = '/api'

// The ONLY Accept value that makes Traccar 6.16 return a real spreadsheet.
//
// Verified against the live instance (13 Oct 2026), same report, same cookie:
//   Accept: */*                                             -> application/json
//   Accept: application/vnd.ms-excel                        -> 406
//   Accept: application/vnd.openxmlformats-officedocument.… -> PK zip (XLSX)
//
// A browser `fetch` with no Accept sends `*/*`, so an export button that simply
// omits the header downloads the JSON body and saves it as .xlsx. The file opens
// as a corrupt spreadsheet and the failure is silent. Hence the explicit value
// and the content-type check in reportBinary below.
export const XLSX_MIME =
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

async function req(path, { method = 'GET', body, raw = false, json = false, accept } = {}) {
  const opts = { method, credentials: 'include', headers: {} }
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  // Traccar 6.16 report endpoints return XLSX by DEFAULT. A ?format=json query
  // parameter is IGNORED. Only this header actually switches them to JSON.
  if (json) opts.headers['Accept'] = 'application/json'
  if (accept) opts.headers['Accept'] = accept
  const res = await fetch(BASE + path, opts)
  if (res.status === 401 || res.status === 403) {
    const e = new Error('unauthorised')
    e.auth = true
    throw e
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    const e = new Error(`${method} ${path} -> ${res.status} ${text.slice(0, 160)}`)
    // Carry the status so callers can distinguish "not found" from "server broke".
    // Traccar needs this: it reports a missing session as 404, not 401.
    e.status = res.status
    throw e
  }
  if (raw) return res
  const t = await res.text()
  return t ? JSON.parse(t) : {}
}

export const api = {
  // ---- auth -------------------------------------------------------------
  // Form-encoded, NOT JSON. Returns the User object and sets JSESSIONID.
  async login(email, password) {
    const res = await fetch(`${BASE}/session`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ email, password }).toString(),
    })
    if (!res.ok) throw new Error('login_failed')
    const user = await res.json()
    if (!user?.id) throw new Error('login_failed')
    return user
  },

  // Traccar quirk #4: GET /api/session with no valid session returns
  // 404 Not Found, NOT 401 Unauthorized. SessionResource.get() throws
  // NotFoundException (verified 30 Sep 2026 on 6.16, SessionResource.java:104).
  //
  // So we cannot use /session as the "am I logged in?" probe: every fresh page
  // load would 404, and Chrome logs the failed response to the console whether
  // or not the JS handles it. A client's browser console should be clean.
  //
  // Instead probe an endpoint that reports 401 properly (the security filter
  // does that), and only then ask who we are. Same question, no spurious 404.
  async whoami() {
    try {
      await req('/devices?limit=1', { json: true })   // 401 => not logged in
    } catch (e) {
      if (e.auth || e.status === 401) return null
      throw e
    }
    return req('/session', { json: true })
  },

  async logout() {
    return req('/session', { method: 'DELETE' }).catch(() => {})
  },

  // ---- devices ----------------------------------------------------------
  // Returns only devices this user is permitted to see. That IS the
  // multi-tenant scoping -- no extra work needed on our side.
  devices: () => req('/devices'),

  async device(id) {
    return req(`/devices/${id}`)
  },

  async updateDevice(id, patch) {
    return req(`/devices/${id}`, { method: 'PUT', body: patch })
  },

  /**
   * Register a tracker under an identifier the server has already refused.
   *
   * `uniqueId` must be EXACTLY the identifier in the `Unknown device` warning: it
   * is what the unit puts in its login packet, and anything else leaves it refused
   * for ever while looking correct in this list.
   *
   * `category` goes in as the TOP-LEVEL field. `attributes.deviceType` does not
   * set it -- measured on Traccar 6.16, a device created with only the attributes
   * form comes back with `category: null`, and Traccar derives speed and distance
   * from the category, so those numbers are then quietly wrong. See
   * docs/UNIMPLEMENTED.md §7.12. Both fields are sent: one is functional, the other
   * is harmless metadata the fleet simulator also writes.
   */
  async provisionDevice({ name, uniqueId, category = 'truck', model = 'st-906l' }) {
    return req('/devices', {
      method: 'POST',
      body: {
        name,
        uniqueId,
        category,
        disabled: false,
        attributes: { model, deviceType: category },
      },
    })
  },

  // ---- positions --------------------------------------------------------
  /**
   * Latest position per device. deviceIds is a comma list.
   * Traccar caps the result set, so this stays small and cheap to poll.
   */
  positions: (deviceIds) =>
    req(`/positions?deviceIds=${deviceIds.join(',')}&limit=200`),

  // Single device, time range -- used by trail history.
  history: (deviceId, fromMs, toMs, limit = 5000) =>
    req(
      `/positions?deviceId=${deviceId}` +
        `&from=${new Date(fromMs).toISOString()}` +
        `&to=${new Date(toMs).toISOString()}` +
        `&limit=${limit}`
    ),

  // ---- events (alerts) --------------------------------------------------
  // There is NO /api/events endpoint in Traccar 6.16 -- it 404s. Events are
  // a report: /api/reports/events. It returns the same Event objects.
  // NOTE: Traccar IGNORES `limit` on the events report -- it returns everything
  // in the window. Keep the window short and slice client-side.
  events: (deviceIds, fromMs, toMs) => {
    const p = new URLSearchParams()
    if (deviceIds?.length) p.set('deviceIds', deviceIds.join(','))
    p.set('from', new Date(fromMs).toISOString())
    p.set('to', new Date(toMs).toISOString())
    return req(`/reports/events?${p.toString()}`, { json: true })
  },

  // An Event has NO latitude/longitude -- only `positionId`. NOTE: there is no
  // usable GET /api/positions/{id} in 6.16 (returns 405, positions are
  // read-only). To locate an alert, re-query the device's positions over the
  // event's minute and match on time. Not needed for the alert feed.

  /**
   * Geofence enter/exit -- i.e. arrivals at customer sites.
   * There is no /api/reports/geofence in 6.16 (404). Filter the events report
   * for geofenceId != 0 instead. That is the arrival log.
   */
  async arrivals(deviceIds, fromMs, toMs, geofences) {
    const all = await api.events(deviceIds, fromMs, toMs)
    const names = new Map((geofences || []).map((g) => [g.id, g.name]))
    return all
      .filter((e) => e.geofenceId && e.geofenceId !== 0)
      .map((e) => ({
        id: e.id,
        time: e.eventTime,
        deviceId: e.deviceId,
        type: e.type,                    // geofenceEnter / geofenceExit
        geofenceId: e.geofenceId,
        geofenceName: names.get(e.geofenceId) || `#${e.geofenceId}`,
      }))
      .sort((a, b) => new Date(b.time) - new Date(a.time))
  },

  // ---- geofences --------------------------------------------------------
  // NOTE: area is WKT with LATITUDE FIRST, not lon/lat. This is the single
  // most common integration bug with Traccar geofences:
  //     CIRCLE (45.4642 9.1900, 500)      <-- lat, lon, radius in METRES
  geofences: () => req('/geofences'),

  async createGeofence(g) {
    return req('/geofences', { method: 'POST', body: g })
  },

  async updateGeofence(id, g) {
    return req(`/geofences/${id}`, { method: 'PUT', body: { ...g, id } })
  },

  async deleteGeofence(id) {
    return req(`/geofences/${id}`, { method: 'DELETE' })
  },

  // ---- reports ----------------------------------------------------------
  // The COMPLETE list of reports in Traccar 6.16, read out of tracker-server.jar
  // on 30 Sep 2026:
  //
  //   Combined  Devices  Events  Geofence  Route  Stops  Summary  Trips
  //
  // Two things that will waste an hour if you assume otherwise:
  //   * it is "Route" SINGULAR. "/api/reports/routes" 404s.
  //   * THERE IS NO "Mileage" REPORT. Mileage is the `distance` column on the
  //     Summary report. Don't look for it.
  //   * NEVER pass groupId. See report() below -- it zeroes every result.
  //
  // Verified row shapes against the live instance (1 Oct 2026):
  //   summary : distance (metres), startTime, endTime, averageSpeed, maxSpeed
  //   route   : full Position objects -- latitude, longitude, fixTime, speed
  //   stops   : startTime, endTime, duration (ms), latitude, longitude, address
  //   trips   : startTime, endTime, distance (m), averageSpeed, driverName
  //   events  : eventTime (NOT `time`), type, geofenceId, positionId, no lat/lon
  //
  // Mapping onto what the dashboard needs:
  //   route history          -> Route
  //   stops + idle           -> Stops
  //   mileage per day/month  -> Summary.distance   (and Trips for detail)
  //   arrival at customer    -> Events where geofenceId != 0 (see arrivals)
  //   alerts                 -> Events
  //   Excel export           -> any of the above, raw (see reportBinary)
  report: (type, { deviceIds, fromMs, toMs } = {}) => {
    const p = new URLSearchParams()
    if (deviceIds?.length) p.set('deviceIds', deviceIds.join(','))
    p.set('from', new Date(fromMs).toISOString())
    p.set('to', new Date(toMs).toISOString())
    // NOTE: do NOT send groupId. An earlier note in this file claimed Route
    // "needs groupId, use 0". That is wrong and it silently broke EVERY report:
    // groupId is a filter, not a required parameter, and group 0 matches nothing,
    // so every report came back HTTP 200 with an empty array. Verified 1 Oct
    // 2026 against the live 6.16 instance:
    //   events  ?deviceIds=..&from&to          -> 197 rows
    //   events  ?deviceIds=..&from&to&groupId=0 ->   0 rows
    // With no groupId at all: route 315, stops 26, trips 26, summary 6, events 197.
    // An empty array is the dangerous part: it looks like "no activity" rather
    // than a broken query, so it would have shipped a Reports tab that always
    // says zero.
    return req(`/reports/${type}?${p.toString()}`, { json: true })
  },

  /**
   * Raw XLSX, for the "Export Excel" button. The spreadsheet is never parsed
   * here; it is handed to the browser as a download.
   *
   * Returns `{ blob, filename }`. The filename comes from Traccar's own
   * Content-Disposition when it sends one, so the export is named the same thing
   * the Traccar UI would call it rather than by a guess made in the browser.
   *
   * Throws if the response is not a spreadsheet. That check is the point of this
   * function: without it a JSON body gets written to disk with an .xlsx name and
   * the operator finds out when Excel refuses to open it.
   */
  async reportBinary(type, params) {
    const p = new URLSearchParams()
    if (params?.deviceIds?.length) p.set('deviceIds', params.deviceIds.join(','))
    p.set('from', new Date(params.fromMs).toISOString())
    p.set('to', new Date(params.toMs).toISOString())

    const res = await req(`/reports/${type}?${p.toString()}`, {
      raw: true,
      accept: XLSX_MIME,
    })

    const contentType = (res.headers.get('content-type') || '').split(';')[0].trim()
    if (contentType !== XLSX_MIME) {
      const e = new Error(
        `expected a spreadsheet from the ${type} report but the server returned ` +
          `${contentType || 'an unknown type'}. Refusing to save it as .xlsx.`
      )
      e.contentType = contentType
      throw e
    }

    const blob = await res.blob()
    const disposition = res.headers.get('content-disposition') || ''
    const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)
    const filename = match
      ? decodeURIComponent(match[1])
      : `gpstracer_${type}.xlsx`

    return { blob, filename }
  },

  // ---- drivers ----------------------------------------------------------
  // Traccar keeps driver<deviceId> as an attribute. There is no /api/drivers
  // endpoint -- this is the documented convention.
  getDriver: async (deviceId) => {
    const d = await req(`/devices/${deviceId}`)
    return d?.attributes?.driverDriverId ?? d?.attributes?.driver ?? null
  },

  setDriver: async (deviceId, driverId) => {
    const d = await req(`/devices/${deviceId}`)
    const attrs = { ...(d.attributes || {}) }
    if (driverId == null || driverId === '') delete attrs.driverDriverId
    else attrs.driverDriverId = String(driverId)
    return req(`/devices/${deviceId}`, { method: 'PUT', body: { ...d, attributes: attrs } })
  },
}

// ---- helpers ------------------------------------------------------------

/** km, from a metres value. Traccar reports totalDistance in metres. */
export const km = (metres) =>
  metres == null ? null : Math.round(metres / 10) / 100

/**
 * Traccar reports speed in km/h under the "speed" key on Position, and knots
 * inside OBD attributes. Normalise to km/h.
 */
export const speedKmh = (v) => (v == null ? null : v)

/** "12 min ago" / "3 h ago" — for the last-seen column. */
export function ago(iso, lang = 'it') {
  if (!iso) return '—'
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  const u = [
    [1, 'sec', 'sec'],
    [60, 'min', 'min'],
    [3600, 'h', 'h'],
    [86400, 'd', 'g'],
  ]
  if (s < 60) return lang === 'it' ? `${Math.floor(s)} sec` : `${Math.floor(s)}s ago`
  if (s < 3600) {
    const m = Math.floor(s / 60)
    return lang === 'it' ? `${m} min` : `${m}m ago`
  }
  if (s < 86400) {
    const h = Math.floor(s / 3600)
    return lang === 'it' ? `${h} h` : `${h}h ago`
  }
  const d = Math.floor(s / 86400)
  return lang === 'it' ? `${d} g` : `${d}d ago`
}

export const fmtTime = (iso, lang = 'it') => {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString(lang === 'it' ? 'it-IT' : 'en-GB', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

export const fmtDate = (iso, lang = 'it') => {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(lang === 'it' ? 'it-IT' : 'en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}
