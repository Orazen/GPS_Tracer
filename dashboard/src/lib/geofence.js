/**
 * Geofence matching, computed client-side.
 *
 * WHY THIS EXISTS INSTEAD OF TRACCAR'S OWN GEOFENCE EVENTS
 * ------------------------------------------------------
 * Traccar's `geofenceEnter` / `geofenceExit` events are the obvious way to get
 * "when did the truck arrive at the customer site", but they cannot work in this
 * deployment. Verified against Traccar 6.16 on 1 Oct 2026:
 *
 *   * `tc_positions.geofenceids` is NULL on every position, i.e. Traccar never
 *     evaluated zone membership at all.
 *   * A geofence is only evaluated for a device if it is linked to that device
 *     (`tc_device_geofence`) or to the device's group (`tc_group_geofence`).
 *     Both tables were empty.
 *   * There is NO way to create that link over the REST API. The full resource
 *     list in tracker-server.jar has no DeviceGeofenceResource, and the models
 *     reject the obvious fields:
 *         PUT /api/geofences/10 {"deviceIds":[3,7]}
 *           -> 400 Unrecognized field "deviceIds"
 *              (Geofence has only: attributes, calendarId, id, description,
 *               area, name)
 *         PUT /api/devices/3 {"geofenceIds":[10]}
 *           -> 400 Unrecognized field "geofenceIds"
 *
 * So arrivals are derived from the position history instead. That is not a
 * workaround so much as a better answer: we control the radius, we do not depend
 * on how the client happens to link zones, and we can report dwell time, which
 * Traccar's events do not give us.
 *
 * The trade-off is that arrivals are only as good as the position history in the
 * window, so `MAX_WINDOW_MS` caps how far back we will compute them.
 */

import { NEUTRAL } from './palette'

const R = 6371000 // metres

/** Metres between two [lat, lon] pairs. */
export function metresBetween(aLat, aLon, bLat, bLon) {
  const dLat = ((bLat - aLat) * Math.PI) / 180
  const dLon = ((bLon - aLon) * Math.PI) / 180
  const la1 = (aLat * Math.PI) / 180
  const la2 = (bLat * Math.PI) / 180
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)))
}

/** Parse a Traccar CIRCLE WKT. Note the lat-first ordering. */
export function parseCircle(wkt) {
  const m = (wkt || '').match(/CIRCLE\s*\(\s*([\d.-]+)\s+([\d.-]+)\s*,\s*([\d.]+)\s*\)/i)
  if (!m) return null
  return { lat: +m[1], lon: +m[2], r: +m[3] }
}

/** Resolve a geofence record into a usable { id, name, lat, lon, r, color }. */
export function siteOf(g) {
  const c = parseCircle(g.area || g.attributes?.area)
  if (!c) return null
  return {
    id: g.id,
    name: g.name,
    lat: c.lat,
    lon: c.lon,
    r: c.r,
    color: g.attributes?.color || NEUTRAL,
    hidden: String(g.attributes?.hidden ?? 'false') === 'true',
  }
}

// Arrival matching is O(positions x sites). Fine for a day or a week; beyond
// that the payload gets large enough to be worth capping.
export const MAX_WINDOW_MS = 14 * 86400000

/**
 * Walk each device's positions in time order and emit enter/exit transitions
 * per site. Also reports how long each visit lasted, which is the number a
 * customer actually wants ("was the truck at my site for 40 minutes?").
 *
 * @param positions array of Traccar Position objects (any order)
 * @param sites     array of geofence records (raw API shape)
 * @returns [{ id, deviceId, siteId, siteName, type, time, durationMs }]
 */
export function computeArrivals(positions, sites) {
  const zones = (sites || []).map(siteOf).filter(Boolean)
  if (!zones.length || !positions?.length) return []

  // group positions per device, oldest first
  const byDevice = new Map()
  for (const p of positions) {
    if (!byDevice.has(p.deviceId)) byDevice.set(p.deviceId, [])
    byDevice.get(p.deviceId).push(p)
  }

  const out = []

  for (const [deviceId, list] of byDevice) {
    list.sort((a, b) => new Date(a.fixTime) - new Date(b.fixTime))

    // inside[siteId] = the enter event currently open, or null
    const open = new Map()

    for (const p of list) {
      if (p.valid === false || p.valid === 0) continue
      const { latitude: la, longitude: lo } = p
      if (la == null || lo == null) continue
      if (Math.abs(la) < 1 && Math.abs(lo) < 1) continue // null island

      for (const z of zones) {
        const was = open.get(z.id)
        const is = metresBetween(la, lo, z.lat, z.lon) <= z.r

        if (is && !was) {
          const ev = {
            id: `${p.id}-${z.id}-in`,
            deviceId,
            siteId: z.id,
            siteName: z.name,
            type: 'enter',
            time: p.fixTime,
            durationMs: null,
            distance: Math.round(metresBetween(la, lo, z.lat, z.lon)),
          }
          open.set(z.id, ev)
          out.push(ev)
        } else if (!is && was) {
          // close the visit
          was.durationMs = new Date(p.fixTime) - new Date(was.time)
          open.set(z.id, null)
          out.push({
            id: `${p.id}-${z.id}-out`,
            deviceId,
            siteId: z.id,
            siteName: z.name,
            type: 'exit',
            time: p.fixTime,
            durationMs: null,
            distance: Math.round(metresBetween(la, lo, z.lat, z.lon)),
          })
        }
      }
    }

    // A visit still open at the end of the window has no exit event, but it is
    // the most interesting one of all -- the truck is there right now.
    for (const ev of open.values()) {
      if (ev) ev.stillInside = true
    }
  }

  return out.sort((a, b) => new Date(b.time) - new Date(a.time))
}

/**
 * How long the truck has been inside each site as of the last known fix.
 * Used for the "on site now" line on the truck panel.
 */
export function currentVisit(positions, sites, deviceId) {
  if (!positions?.length) return []
  const zones = (sites || []).map(siteOf).filter(Boolean)
  const mine = positions
    .filter((p) => p.deviceId === deviceId && p.valid !== 0 && p.valid !== false)
    .sort((a, b) => new Date(a.fixTime) - new Date(b.fixTime))
  if (!mine.length || !zones.length) return []

  const last = mine[mine.length - 1]
  const res = []
  for (const z of zones) {
    if (metresBetween(last.latitude, last.longitude, z.lat, z.lon) > z.r) continue
    // find when it arrived
    let enteredAt = last.fixTime
    for (let i = mine.length - 1; i >= 0; i--) {
      const p = mine[i]
      if (metresBetween(p.latitude, p.longitude, z.lat, z.lon) > z.r) break
      enteredAt = p.fixTime
    }
    res.push({
      siteId: z.id,
      siteName: z.name,
      since: enteredAt,
      forMs: Date.now() - new Date(enteredAt).getTime(),
    })
  }
  return res
}
