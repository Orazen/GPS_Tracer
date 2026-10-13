// Derives a truck's state from its last position. This is the single place
// that decides what colour a truck is on the map and which alerts fire, so the
// dashboard and the alert engine can never disagree.

export const STATE = {
  ALERT: 'alert',
  MOVING: 'moving',
  IDLE: 'idle',
  OFFLINE: 'offline',
  NEVER: 'never',
}

export const COLOR = {
  [STATE.ALERT]: '#ef4444',
  [STATE.MOVING]: '#10b981',
  [STATE.IDLE]: '#f59e0b',
  [STATE.OFFLINE]: '#9ca3af',
  [STATE.NEVER]: '#6b7280',
}

/**
 * @param position  latest Position from the API (may be null)
 * @param thresholds { idleMin, offlineMin, speedLimit }
 */
export function truckState(position, thresholds) {
  const { idleMin = 20, offlineMin = 15, speedLimit = 0 } = thresholds || {}
  if (!position) return { state: STATE.NEVER, ageS: Infinity }

  const t = new Date(position.fixTime || position.attributes?.fixTime).getTime()
  if (Number.isNaN(t)) return { state: STATE.NEVER, ageS: Infinity }

  // The receiver itself told us it could not get a fix. Traccar keeps these rows
  // (valid = 0). Treating one as a real position would mark the truck MOVING at
  // 0,0 and pin a marker in the Gulf of Guinea, so a failed fix is "no data".
  if (position.valid === 0) return { state: STATE.NEVER, ageS: Infinity }

  const ageS = (Date.now() - t) / 1000
  const speed = Number(position.speed ?? position.attributes?.speed ?? 0) || 0
  const ignition = position.attributes?.ignition

  // Offline wins over everything. A truck that has not reported is the most
  // urgent thing on the map, regardless of what its last state was.
  if (ageS > offlineMin * 60) return { state: STATE.OFFLINE, ageS, speed, ignition }
  if (speedLimit > 0 && speed > speedLimit) return { state: STATE.ALERT, ageS, speed, ignition }
  if (ageS > idleMin * 60) return { state: STATE.IDLE, ageS, speed, ignition }
  if (speed > 3) return { state: STATE.MOVING, ageS, speed, ignition }
  return { state: STATE.IDLE, ageS, speed, ignition }
}

/** Is this timestamp outside the configured working hours? Used by the out-of-hours alert. */
export function outsideWorkHours(date, fromHour, toHour) {
  if (fromHour == null || toHour == null) return false
  const h = date.getHours() + date.getMinutes() / 60
  const [fh, fm] = String(fromHour).split(':').map(Number)
  const [th, tm] = String(toHour).split(':').map(Number)
  const a = fh + (fm || 0) / 60
  const b = th + (tm || 0) / 60
  // handles a window that wraps past midnight (e.g. 22:00 -> 06:00)
  return a <= b ? h < a || h >= b : h < a && h >= b
}

/** Traccar event type -> our translation key. */
// Traccar 6.16 also emits these, which show up on a real fleet:
export const EVENT_KEY = {
  geofenceEnter: 'geofenceEnter',
  geofenceExit: 'geofenceExit',
  alarm: 'alarm',
  ignitionOn: 'ignitionOn',
  ignitionOff: 'ignitionOff',
  speeding: 'speeding',
  deviceOffline: 'offline',
  deviceMoving: 'moving',
  deviceStopped: 'idle',
  motionAlarm: 'alarm',
}

export const ALERT_LEVEL = {
  alarm: 3,
  speeding: 2,
  deviceOffline: 2,
  geofenceExit: 1,
  geofenceEnter: 0,
  ignitionOn: 0,
  ignitionOff: 0,
  // deviceMoving / deviceStopped are noise on a 15s-reporting fleet. They are
  // useful in the History view, not in the alert feed.
  deviceMoving: -1,
  deviceStopped: -1,
}

/**
 * Build alert rows from Traccar events, applying the out-of-hours rule.
 *
 * The driver name is attached ONLY when showDriverName is on. That switch is
 * off by default on purpose -- see DASHBOARD-SPEC.md. In Italy a named
 * out-of-hours alert is worker monitoring and needs Art. 4 L.300/1970
 * authorisation; an unnamed one is fleet security under legitimate interest.
 */
export function buildAlerts(events, devices, opts) {
  const { workFrom = null, workTo = null, showDriverName = false, speedLimit = 0 } = opts || {}
  const byId = new Map(devices.map((d) => [d.id, d]))
  const rows = []

  for (const e of events || []) {
    if ((ALERT_LEVEL[e.type] ?? 0) < 0) continue  // movement noise, skip
    const dev = byId.get(e.deviceId)
    const when = new Date(e.eventTime)
    const inHours = !outsideWorkHours(when, workFrom, workTo)
    let type = e.type
    let level = ALERT_LEVEL[type] ?? 0

    if (type === 'ignitionOn' && !inHours) {
      type = 'outOfHours'
      level = 2
    }
    if (type === 'speeding' && !(speedLimit > 0)) {
      type = 'ignitionOn' // reported by the device but we have no limit set
      level = 0
    }

    rows.push({
      id: e.id,
      // the field is eventTime. There is no `time` on a Traccar Event.
      time: e.eventTime,
      deviceId: e.deviceId,
      deviceName: dev?.name || `#${e.deviceId}`,
      // the whole point: name is only ever present when explicitly enabled
      driverName: showDriverName ? dev?.attributes?.driverDriverId || null : null,
      type,
      level,
      // Events carry NO coordinates -- only positionId. Resolve it lazily if the
      // UI ever needs a pin for an alert.
      positionId: e.positionId,
      geofenceId: e.geofenceId,
    })
  }

  rows.sort((a, b) => new Date(b.time) - new Date(a.time))
  return rows
}

/** Read the "driver assigned to this truck" attribute. */
export const driverOf = (device) =>
  device?.attributes?.driverDriverId || device?.attributes?.driver || null
