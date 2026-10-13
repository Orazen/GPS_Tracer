import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, fmtDate, fmtTime } from '../api/traccar'
import { PRESETS, rangeFor, rangeFromInputs } from '../lib/dates'
import { computeArrivals } from '../lib/geofence'
import FleetMap from './FleetMap'

/**
 * Route history for one truck over a chosen window.
 *
 * Data source is the `route` report, which returns full Position objects
 * (latitude/longitude/fixTime/speed). That is preferable to paging
 * /api/positions because it is one request for the whole window and comes back
 * already ordered by time.
 *
 * Three things the client needs from this screen and that a naive polyline
 * does not give you:
 *   - where the truck actually stopped, with duration and address
 *   - when it arrived at each customer site (geofence enter events)
 *   - total distance for the window, so it ties out with the Reports tab
 */

function fmtDur(ms, t) {
  const m = Math.round((ms || 0) / 60000)
  if (m < 1) return t('under1min')
  if (m < 60) return t('minShort').replace('{n}', m)
  const h = Math.floor(m / 60)
  const r = m % 60
  return r ? `${h}${t('hShort')} ${r}${t('minShort').replace('{n}', '')}` : `${h}${t('hShort')}`
}

export default function TrailHistory({ truck, devices, t, lang }) {
  const [preset, setPreset] = useState('today')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [busyTab, setBusyTab] = useState(null)
  const [err, setErr] = useState(null)
  const [route, setRoute] = useState([])
  const [stops, setStops] = useState(null)      // null = not loaded yet
  const [arrivals, setArrivals] = useState(null)
  const [summary, setSummary] = useState(null)
  const [tab, setTab] = useState('stops')

  const range = useMemo(
    () => rangeFromInputs(fromDate, toDate) || rangeFor(preset),
    [preset, fromDate, toDate]
  )

  const id = truck?.device.id
  const windowKey = `${id}|${range.from}|${range.to}`

  // The route report is fast (~0.05 s) and summary is fast (~0.07 s), so the map
  // and the headline numbers appear immediately. `stops` is a 3.5 s server-side
  // aggregation and `arrivals` re-queries events, so those load only when their
  // tab is opened -- otherwise the trail would not draw for 3.5 s.
  useEffect(() => {
    if (!id) return
    let alive = true
    setStops(null)
    setArrivals(null)
    setSummary(null)
    setErr(null)
    ;(async () => {
      try {
        const { from, to } = range
        const [r, sum] = await Promise.all([
          api.report('route', { deviceIds: [id], fromMs: from, toMs: to }),
          api.report('summary', { deviceIds: [id], fromMs: from, toMs: to }),
        ])
        if (!alive) return
        setRoute(Array.isArray(r) ? r : [])
        setSummary(Array.isArray(sum) ? sum[0] || null : null)
      } catch (e) {
        if (alive) setErr(e.auth ? t('sessionExpired') : String(e.message || e))
      }
    })()
    return () => { alive = false }
  }, [windowKey, range.from, range.to, t, id])

  const loadTab = useCallback(async (name) => {
    if (!id) return
    setBusyTab(name)
    setErr(null)
    try {
      const { from, to } = range
      if (name === 'stops') {
        const rows = await api.report('stops', { deviceIds: [id], fromMs: from, toMs: to })
        setStops(Array.isArray(rows) ? rows : [])
      } else {
        // Arrivals are derived from the position history we already have for the
        // map, not from Traccar's geofence events -- those cannot fire here.
        // See lib/geofence.js for the full reason.
        setArrivals(computeArrivals(route, devices.geofences || []))
      }
    } catch (e) {
      setErr(e.auth ? t('sessionExpired') : String(e.message || e))
    } finally {
      setBusyTab(null)
    }
  }, [id, range.from, range.to, devices.geofences, route, t])

  // Stops is the default tab, so load it straight away; arrivals waits for a click.
  useEffect(() => {
    if (stops === null && busyTab !== 'stops') loadTab('stops')
  }, [windowKey, busyTab, stops === null])

  useEffect(() => {
    if (tab === 'arrivals' && arrivals === null && busyTab !== 'arrivals') loadTab('arrivals')
  }, [tab, arrivals === null, busyTab, windowKey])

  const busy = busyTab != null

  // Drop invalid fixes and collapse 0,0 / duplicated points. A tracker with no
  // lock reports 0,0, which would draw a line from Africa to the truck.
  const path = useMemo(() => {
    const pts = []
    let prev = null
    for (const p of route) {
      if (p.valid === false || p.valid === 0) continue
      const { latitude: la, longitude: lo } = p
      if (la == null || lo == null) continue
      if (Math.abs(la) < 1 && Math.abs(lo) < 1) continue     // null island
      if (prev && Math.abs(prev.latitude - la) < 1e-7 && Math.abs(prev.longitude - lo) < 1e-7) continue
      pts.push([la, lo])
      prev = p
    }
    return pts
  }, [route])

  // Only draw one marker per truck here -- this screen is about one truck.
  const onlyTruck = useMemo(
    () => (truck ? [{ ...truck, position: null }] : []),
    [truck]
  )

  const maxSpeed = useMemo(() => {
    let m = 0
    for (const p of route) if (p.speed > m) m = p.speed
    return m
  }, [route])

  if (!truck) return <div className="pad"><p className="muted">{t('pickTruckForHistory')}</p></div>

  const distKm = summary ? summary.distance / 1000 : null
  const movingH = route.length
    ? ((stops || []).reduce((a, s) => a + (s.duration || 0), 0) / 3600000)
    : 0

  return (
    <div className="history">
      <div className="hist-bar">
        <div className="hist-presets">
          {PRESETS.map((p) => (
            <button
              key={p.k}
              className={`chip ${preset === p.k && !fromDate && !toDate ? 'on' : ''}`}
              onClick={() => { setPreset(p.k); setFromDate(''); setToDate('') }}
            >
              {t(p.i18n)}
            </button>
          ))}
        </div>
        <label className="hist-dates">
          <span className="small muted">{t('from')}</span>
          <input type="date" value={fromDate} max={toDate || undefined}
            onChange={(e) => setFromDate(e.target.value)} />
          <span className="small muted">{t('to')}</span>
          <input type="date" value={toDate} min={fromDate || undefined}
            onChange={(e) => setToDate(e.target.value)} />
        </label>
        <span className="spacer" />
        <button className="btn ghost" onClick={() => api && window.print()}>{t('print')}</button>
      </div>

      <div className="hist-grid">
        <div className="hist-map">
          <FleetMap
            trucks={onlyTruck}
            selectedId={truck.device.id}
            onSelect={() => {}}
            trail={path}
            geofences={devices.geofences || []}
            geofenceVisible
            t={t}
          />
        </div>

        <div className="hist-side">
          <div className="kpis">
            <div className="kpi">
              <b>{distKm == null ? '—' : distKm.toFixed(1)}</b>
              <span>{t('km')}</span>
            </div>
            <div className="kpi">
              <b>{path.length}</b>
              <span>{t('fixes')}</span>
            </div>
            <div className="kpi">
              <b>{stops == null ? '—' : stops.length}</b>
              <span>{t('stops')}</span>
            </div>
            <div className="kpi">
              <b>{maxSpeed ? Math.round(maxSpeed) : '—'}</b>
              <span>{t('kmh')}</span>
            </div>
          </div>

          {summary && (
            <p className="muted small hist-range">
              {fmtDate(summary.startTime, lang)} {fmtTime(summary.startTime, lang)}
              {' → '}
              {fmtDate(summary.endTime, lang)} {fmtTime(summary.endTime, lang)}
              {movingH > 0 && ` · ${t('stopped').replace('{d}', fmtDur(movingH * 3600000, t))}`}
            </p>
          )}

          {err && <p className="err small">{err}</p>}

          <div className="subtabs">
            <button className={tab === 'stops' ? 'on' : ''} onClick={() => setTab('stops')}>
              {t('stops')} <i>{stops == null ? '…' : stops.length}</i>
            </button>
            <button className={tab === 'arrivals' ? 'on' : ''} onClick={() => setTab('arrivals')}>
              {t('arrivals')} <i>{arrivals == null ? '…' : arrivals.length}</i>
            </button>
            <button className={tab === 'points' ? 'on' : ''} onClick={() => setTab('points')}>
              {t('points')} <i>{route.length}</i>
            </button>
          </div>

          {busy && <p className="muted small">{t('loading')}</p>}

          {!busy && tab === 'stops' && (
            stops == null ? (
              <p className="muted small">{t('loading')}</p>
            ) : stops.length === 0 ? (
              <p className="muted small">{t('noStops')}</p>
            ) : (
              <ul className="rows">
                {stops.map((s, i) => (
                  <li key={s.positionId || i}>
                    <div className="rowmain">
                      <strong>
                        {fmtTime(s.startTime, lang)} – {fmtTime(s.endTime, lang)}
                      </strong>
                      <span className="muted small">{fmtDur(s.duration, t)}</span>
                    </div>
                    {s.address && <span className="muted small addr">{s.address}</span>}
                  </li>
                ))}
              </ul>
            )
          )}

          {!busy && tab === 'arrivals' && (
            arrivals == null ? (
              <p className="muted small">{t('loading')}</p>
            ) : arrivals.length === 0 ? (
              <p className="muted small">{t('noArrivals')}</p>
            ) : (
              // A <ul> cannot contain a <p> or another <ul>: the browser hoists
              // them out of the list, and React then fails to hydrate the tree it
              // thinks it rendered. The wrapper is a div for that reason.
              <div className="arrivals">
                {arrivals.some((a) => a.stillInside) && (
                  <p className="small onsite">{t('onSiteNow')}</p>
                )}
                <ul className="rows">
                  {arrivals.map((a) => (
                    <li key={a.id}>
                      <div className="rowmain">
                        <strong>{fmtTime(a.time, lang)}</strong>
                        <span className={`tag ${a.type === 'enter' ? 'in' : 'out'}`}>
                          {a.type === 'enter' ? t('entered') : t('left')}
                        </span>
                      </div>
                      <span className="muted small">
                        {a.siteName}
                        {a.durationMs != null && ` \u00b7 ${fmtDur(a.durationMs, t)}`}
                        {a.stillInside && ` \u00b7 ${t('stillThere')}`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )
          )}

          {!busy && tab === 'points' && (
            <ul className="rows compact">
              {route.slice().reverse().slice(0, 300).map((p) => (
                <li key={p.id}>
                  <div className="rowmain">
                    <strong>{fmtTime(p.fixTime, lang)}</strong>
                    <span className="muted small">
                      {Math.round(p.speed || 0)} {t('kmh')}
                      {p.attributes?.sat != null && ` · ${p.attributes.sat} sat`}
                    </span>
                  </div>
                  <span className="muted small mono">
                    {Number(p.latitude).toFixed(5)}, {Number(p.longitude).toFixed(5)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
