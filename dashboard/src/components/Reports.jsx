import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, fmtDate, fmtTime } from '../api/traccar'
import { PRESETS, rangeFor, rangeFromInputs } from '../lib/dates'
import { computeArrivals } from '../lib/geofence'

/**
 * Mileage, stops, trips and arrivals, plus a real Excel export.
 *
 * Traccar's report endpoints are the only sane way to get this data, and they
 * have two traps that are handled in api/traccar.js:
 *   - they return XLSX unless you send Accept: application/json
 *   - NEVER send groupId (it silently returns zero rows)
 *
 * The export button asks Traccar for the raw XLSX and hands the blob straight
 * to the browser. We never parse a spreadsheet -- the file is already correct.
 */

const TABS = ['summary', 'stops', 'trips', 'arrivals']
const EMPTY = { summary: [], stops: [], trips: [], arrivals: [] }

/**
 * Traccar computes `stops` and `trips` by scanning every position in the
 * window, and it is genuinely slow. Measured on the live 6.16 instance with a
 * 13-hour window and 6 trucks:
 *
 *   summary   0.07 s
 *   events    0.02 s
 *   route     0.05 s
 *   stops     3.49 s   <-- server-side aggregation
 *   trips     5.47 s   <-- server-side aggregation
 *
 * Firing all four at once on mount made the whole screen wait ~5.5 s before a
 * single row appeared. So each report is fetched only when its tab is opened,
 * and switching tabs never refetches what is already loaded.
 */

function fmtDur(ms, t) {
  const m = Math.round((ms || 0) / 60000)
  if (m < 1) return `<1${t('minShort').replace('{n}', '')}`
  if (m < 60) return t('minShort').replace('{n}', m)
  const h = Math.floor(m / 60)
  const r = m % 60
  return r ? `${h}${t('hShort')} ${r}${t('minShort').replace('{n}', '')}` : `${h}${t('hShort')}`
}

export default function Reports({ devices, geofences, t, lang }) {
  const [preset, setPreset] = useState('d7')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [scope, setScope] = useState('all')            // 'all' | device id
  const [tab, setTab] = useState('summary')
  const [busyTab, setBusyTab] = useState(null)
  const [loaded, setLoaded] = useState({})      // which reports are in `data`
  const [exporting, setExporting] = useState(null)
  const [err, setErr] = useState(null)
  const [data, setData] = useState(EMPTY)

  const range = useMemo(
    () => rangeFromInputs(fromDate, toDate) || rangeFor(preset),
    [preset, fromDate, toDate]
  )

  const ids = useMemo(
    () => (scope === 'all' ? devices.map((d) => d.id) : [Number(scope)]),
    [scope, devices]
  )

  const idKey = ids.join(',')
  // A single string that changes whenever the window or the fleet selection
  // changes. Used as the reset key so a stale report can never be shown against
  // a new date range.
  const windowKey = `${idKey}|${range.from}|${range.to}`

  const fetchTab = useCallback(async (name) => {
    setBusyTab(name)
    setErr(null)
    try {
      const { from, to } = range
      let rows = []
      if (name === 'arrivals') {
        // One route query for the whole window, then match zones client-side.
        // Traccar's own geofence events cannot fire in this deployment -- see
        // lib/geofence.js for why, with the API rejections that prove it.
        const pos = await api.report('route', { deviceIds: ids, fromMs: from, toMs: to })
        rows = computeArrivals(Array.isArray(pos) ? pos : [], geofences)
      } else {
        rows = await api.report(name, { deviceIds: ids, fromMs: from, toMs: to })
      }
      setData((d) => ({ ...d, [name]: Array.isArray(rows) ? rows : [] }))
    } catch (e) {
      setErr(e.auth ? t('sessionExpired') : String(e.message || e))
    } finally {
      // Marked here, not on success. `loaded` is what the effect below reads to
      // decide whether to fetch, so marking only on success means a report that
      // throws is re-requested the moment `busyTab` resets -- an unbounded loop.
      // Measured before this was fixed: a missing import made the arrivals tab
      // issue 1013 requests in 25 seconds and never render, with the error text
      // flashing on and off screen too fast to read.
      setLoaded((l) => ({ ...l, [name]: true }))
      setBusyTab(null)
    }
  }, [idKey, range.from, range.to, geofences, t, ids])

  // Changing the window or the fleet invalidates every cached report.
  useEffect(() => {
    setData(EMPTY)
    setLoaded({})
  }, [windowKey])

  // Summary is cheap, so it always loads up front -- that is what fills the
  // KPI strip. The slow reports wait for their tab.
  useEffect(() => {
    if (!loaded.summary && busyTab !== 'summary') fetchTab('summary')
  }, [windowKey, tab, loaded.summary, busyTab])

  // Fetch the report for whichever tab is on screen, once.
  useEffect(() => {
    if (!loaded[tab] && busyTab !== tab) fetchTab(tab)
  }, [tab, loaded, busyTab, windowKey])

  const busy = busyTab === tab

  /**
   * Download the raw XLSX straight from Traccar. The response is already a
   * spreadsheet, so the only thing to do is hand it to the browser as a file.
   */
  const exportXlsx = async (type) => {
    setExporting(type)
    setErr(null)
    try {
      // reportBinary rejects a non-spreadsheet response, so by the time we get
      // here the bytes really are an .xlsx. The filename is Traccar's own when it
      // sends one.
      const { blob, filename } = await api.reportBinary(type, {
        deviceIds: ids, fromMs: range.from, toMs: range.to,
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      // Revoke on the next tick; revoking synchronously can cancel the download
      // in some browsers.
      setTimeout(() => URL.revokeObjectURL(url), 4000)
    } catch (e) {
      setErr(e.auth ? t('sessionExpired') : String(e.message || e))
    } finally {
      setExporting(null)
    }
  }

  const totalKm = data.summary.reduce((a, s) => a + (s.distance || 0), 0) / 1000
  const movingKm = data.trips.reduce((a, x) => a + (x.distance || 0), 0) / 1000
  const stoppedH = data.stops.reduce((a, s) => a + (s.duration || 0), 0) / 3600000

  return (
    <div className="pad reports">
      <div className="rep-bar">
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

        <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="all">{t('allTrucks')}</option>
          {devices.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>

        <span className="spacer" />
        <button
          className="btn primary"
          onClick={() => exportXlsx(tab === 'arrivals' ? 'events' : tab)}
          disabled={!!exporting}
        >
          {exporting ? t('exporting') : t('exportExcel')}
        </button>
      </div>

      <div className="kpis">
        <div className="kpi"><b>{totalKm.toFixed(1)}</b><span>{t('totalKm')}</span></div>
        <div className="kpi"><b>{movingKm.toFixed(1)}</b><span>{t('movingKm')}</span></div>
        <div className="kpi"><b>{stoppedH.toFixed(1)}</b><span>{t('stoppedHours')}</span></div>
        <div className="kpi"><b>{data.stops.length}</b><span>{t('stops')}</span></div>
        <div className="kpi"><b>{data.arrivals.length}</b><span>{t('arrivals')}</span></div>
      </div>

      <div className="subtabs">
        {TABS.map((x) => (
          <button key={x} className={tab === x ? 'on' : ''} onClick={() => setTab(x)}>
            {t(x)} <i>{data[x]?.length ?? 0}</i>
          </button>
        ))}
      </div>

      {err && <p className="err small">{err}</p>}
      {busy && <p className="muted small">{t('loading')}</p>}

      {!busy && tab === 'summary' && (
        <table className="grid">
          <thead>
            <tr>
              <th>{t('truck')}</th>
              <th className="num">{t('km')}</th>
              <th className="num">{t('avgSpeed')}</th>
              <th className="num">{t('maxSpeed')}</th>
              <th>{t('from')}</th>
              <th>{t('to')}</th>
            </tr>
          </thead>
          <tbody>
            {data.summary.map((s) => (
              <tr key={s.deviceId}>
                <td>{s.deviceName}</td>
                <td className="num">{(s.distance / 1000).toFixed(1)}</td>
                <td className="num">{Math.round(s.averageSpeed || 0)}</td>
                <td className="num">{Math.round(s.maxSpeed || 0)}</td>
                <td className="small">{fmtDate(s.startTime, lang)} {fmtTime(s.startTime, lang)}</td>
                <td className="small">{fmtDate(s.endTime, lang)} {fmtTime(s.endTime, lang)}</td>
              </tr>
            ))}
            {!data.summary.length && (
              <tr><td colSpan={6} className="muted small">{t('noData')}</td></tr>
            )}
          </tbody>
          {data.summary.length > 0 && (
            <tfoot>
              <tr>
                <td><strong>{t('total')}</strong></td>
                <td className="num"><strong>{totalKm.toFixed(1)}</strong></td>
                <td /><td /><td /><td />
              </tr>
            </tfoot>
          )}
        </table>
      )}

      {!busy && tab === 'stops' && (
        <table className="grid">
          <thead>
            <tr>
              <th>{t('truck')}</th>
              <th>{t('start')}</th>
              <th>{t('end')}</th>
              <th className="num">{t('duration')}</th>
              <th>{t('address')}</th>
            </tr>
          </thead>
          <tbody>
            {data.stops.map((s, i) => (
              <tr key={s.positionId || i}>
                <td>{s.deviceName}</td>
                <td className="small">{fmtTime(s.startTime, lang)}</td>
                <td className="small">{fmtTime(s.endTime, lang)}</td>
                <td className="num">{fmtDur(s.duration, t)}</td>
                <td className="small addr">{s.address || '—'}</td>
              </tr>
            ))}
            {!data.stops.length && (
              <tr><td colSpan={5} className="muted small">{t('noData')}</td></tr>
            )}
          </tbody>
        </table>
      )}

      {!busy && tab === 'trips' && (
        <table className="grid">
          <thead>
            <tr>
              <th>{t('truck')}</th>
              <th>{t('start')}</th>
              <th>{t('end')}</th>
              <th className="num">{t('km')}</th>
              <th className="num">{t('avgSpeed')}</th>
              <th>{t('to')}</th>
            </tr>
          </thead>
          <tbody>
            {data.trips.map((x, i) => (
              <tr key={x.startPositionId || i}>
                <td>{x.deviceName}</td>
                <td className="small">{fmtTime(x.startTime, lang)}</td>
                <td className="small">{fmtTime(x.endTime, lang)}</td>
                <td className="num">{(x.distance / 1000).toFixed(2)}</td>
                <td className="num">{Math.round(x.averageSpeed || 0)}</td>
                <td className="small addr">{x.endAddress || '—'}</td>
              </tr>
            ))}
            {!data.trips.length && (
              <tr><td colSpan={6} className="muted small">{t('noData')}</td></tr>
            )}
          </tbody>
        </table>
      )}

      {!busy && tab === 'arrivals' && (
        <table className="grid">
          <thead>
            <tr>
              <th>{t('time')}</th>
              <th>{t('truck')}</th>
              <th>{t('site')}</th>
              <th>{t('event')}</th>
            </tr>
          </thead>
          <tbody>
            {data.arrivals.map((a) => (
              <tr key={a.id}>
                <td className="small">
                  {fmtDate(a.time, lang)} {fmtTime(a.time, lang)}
                </td>
                <td>{devices.find((d) => d.id === a.deviceId)?.name || a.deviceId}</td>
                <td>{a.geofenceName}</td>
                <td>
                  <span className={`tag ${a.type === 'geofenceEnter' ? 'in' : 'out'}`}>
                    {a.type === 'geofenceEnter' ? t('entered') : t('left')}
                  </span>
                </td>
              </tr>
            ))}
            {!data.arrivals.length && (
              <tr><td colSpan={4} className="muted small">{t('noData')}</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
