import { useCallback, useEffect, useState } from 'react'
import { api } from './api/traccar'
import { makeT } from './i18n'
import { COLOR, STATE, buildAlerts, truckState } from './lib/status'
import FleetMap from './components/FleetMap'
import TruckList from './components/TruckList'
import TruckPanel from './components/TruckPanel'
import TrailHistory from './components/TrailHistory'
import GeofenceManager from './components/GeofenceManager'
import Reports from './components/Reports'
import Tacho from './components/Tacho'
import { ago } from './api/traccar'

const DEFAULTS = {
  idleMin: 20,
  offlineMin: 15,
  speedLimit: 0,
  workFrom: '06:00',
  workTo: '20:00',
  // OFF by default. Showing a driver name on an out-of-hours alert is worker
  // monitoring in Italy and needs Art. 4 L.300/1970 authorisation. Fleet
  // security (unnamed) needs nothing. See DASHBOARD-SPEC.md.
  showDriverName: false,
}

export default function App({ user, onLogout }) {
  const [lang, setLang] = useState(() => localStorage.getItem('gt.lang') || 'it')
  const t = makeT(lang)
  const [devices, setDevices] = useState([])
  const [positions, setPositions] = useState(new Map())
  const [events, setEvents] = useState([])
  const [geofences, setGeofences] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [view, setView] = useState('map')
  const [cfg, setCfg] = useState(() => {
    try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem('gt.cfg') || '{}') } }
    catch { return DEFAULTS }
  })
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(true)

  // ---- load devices + geofences once ------------------------------------
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const [d, g] = await Promise.all([api.devices(), api.geofences()])
        if (!alive) return
        setDevices(d)
        setGeofences(g)
        setSelectedId((cur) => cur ?? d[0]?.id ?? null)
      } catch (e) {
        if (e.auth) onLogout()
        else setErr(String(e.message || e))
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => { alive = false }
  }, [onLogout])

  // ---- reload geofences (after a create/edit/delete) --------------------
  // Kept separate from the initial load so the geofence manager can refresh its
  // own list without tearing down the whole app or re-running the device load.
  const reloadGeofences = useCallback(async () => {
    try {
      setGeofences(await api.geofences())
    } catch (e) {
      if (e.auth) onLogout()
      else setErr(String(e.message || e))
    }
  }, [onLogout])

  // ---- poll live positions + events ------------------------------------
  useEffect(() => {
    if (devices.length === 0) return
    let alive = true
    const ids = devices.map((d) => d.id)

    const tick = async () => {
      try {
        const since = Date.now() - 1000 * 60 * 60 * 24 * 3
        const [p, e] = await Promise.all([
          api.positions(ids),
          api.events(ids, since, Date.now(), 60),
        ])
        if (!alive) return
        const m = new Map()
        for (const pos of p) {
          const prev = m.get(pos.deviceId)
          if (!prev || new Date(pos.fixTime) > new Date(prev.fixTime)) m.set(pos.deviceId, pos)
        }
        setPositions(m)
        setEvents(e)
        setErr(null)
      } catch (e2) {
        if (e2.auth) onLogout()
        else setErr(String(e2.message || e2))
      }
    }
    tick()
    const h = setInterval(tick, 5000)
    return () => { alive = false; clearInterval(h) }
  }, [devices, onLogout])

  // ---- persist config + language ---------------------------------------
  useEffect(() => { localStorage.setItem('gt.cfg', JSON.stringify(cfg)) }, [cfg])
  useEffect(() => { localStorage.setItem('gt.lang', lang) }, [lang])

  // ---- derived ----------------------------------------------------------
  const trucks = devices.map((device) => {
    const position = positions.get(device.id) || null
    return { device, position, ...truckState(position, cfg) }
  })

  const alerts = buildAlerts(events, devices, {
    workFrom: cfg.workFrom, workTo: cfg.workTo,
    showDriverName: cfg.showDriverName, speedLimit: cfg.speedLimit,
  })

  const counts = trucks.reduce(
    (a, x) => { a[x.state] = (a[x.state] || 0) + 1; return a },
    { [STATE.MOVING]: 0, [STATE.IDLE]: 0, [STATE.OFFLINE]: 0, [STATE.NEVER]: 0, [STATE.ALERT]: 0 }
  )
  const online = trucks.filter((x) => x.state !== STATE.OFFLINE && x.state !== STATE.NEVER).length
  const selected = trucks.find((x) => x.device.id === selectedId) || null

  // ---- render ------------------------------------------------------------
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" />
          <strong>{t('appName')}</strong>
        </div>

        <nav className="tabs">
          {['map', 'history', 'geofences', 'reports', 'tacho', 'settings'].map((v) => (
            <button
              key={v}
              className={`tab ${view === v ? 'on' : ''}`}
              onClick={() => setView(v)}
            >
              {t(v === 'map' ? 'fleet' : v)}
            </button>
          ))}
        </nav>

        <div className="topright">
          <div className="lang">
            <button className={lang === 'it' ? 'on' : ''} onClick={() => setLang('it')}>IT</button>
            <button className={lang === 'en' ? 'on' : ''} onClick={() => setLang('en')}>EN</button>
          </div>
          <span className="who">{user.email}</span>
          <button className="btn ghost" onClick={onLogout}>{t('logout')}</button>
        </div>
      </header>

      <div className="statusbar">
        <span className="stat s-ok">
          <b>{online}</b> {t('online')}
        </span>
        <span className="stat s-moving"><b>{counts[STATE.MOVING]}</b> {t('moving')}</span>
        <span className="stat s-idle"><b>{counts[STATE.IDLE]}</b> {t('idle')}</span>
        <span className="stat s-offline"><b>{counts[STATE.OFFLINE]}</b> {t('offline')}</span>
        {counts[STATE.ALERT] > 0 && (
          <span className="stat s-alert"><b>{counts[STATE.ALERT]}</b> ⚠</span>
        )}
        <span className="spacer" />
        {err && <span className="err">{err}</span>}
      </div>

      <main className="body">
        {view === 'map' && (
          <div className="layout">
            <TruckList
              trucks={trucks}
              selectedId={selectedId}
              onSelect={setSelectedId}
              t={t}
              lang={lang}
            />
            <div className="mapwrap">
              <FleetMap
                trucks={trucks}
                selectedId={selectedId}
                onSelect={setSelectedId}
                geofences={geofences}
                t={t}
              />
            </div>
            <TruckPanel
              truck={selected}
              t={t}
              lang={lang}
              onShowHistory={() => setView('history')}
            />
            <AlertsFeed alerts={alerts} t={t} lang={lang} />
          </div>
        )}

        {view === 'history' && (
          <TrailHistory
            truck={selected}
            devices={{ geofences }}
            t={t}
            lang={lang}
          />
        )}
        {view === 'geofences' && (
          <GeofenceManager
            devices={{ trucks, selectedId, onSelect: setSelectedId }}
            geofences={geofences}
            onChanged={reloadGeofences}
            t={t}
            lang={lang}
          />
        )}
        {view === 'reports' && (
          <Reports
            devices={devices}
            geofences={geofences}
            t={t}
            lang={lang}
          />
        )}
        {/* Tachograph screens. These talk to the tachograph service through the
            dashboard's own proxy, so no service token ever reaches this code. */}
        {view === 'tacho' && <Tacho t={t} lang={lang} />}
        {view === 'settings' && (
          <div className="pad settings">
            <h2>{t('settings')}</h2>

            <div className="field">
              <label>{t('language')}</label>
              <div className="lang">
                <button className={lang === 'it' ? 'on' : ''} onClick={() => setLang('it')}>Italiano</button>
                <button className={lang === 'en' ? 'on' : ''} onClick={() => setLang('en')}>English</button>
              </div>
            </div>

            <h3>{t('threshold')}</h3>
            <div className="field">
              <label>{t('idleAlertMin')}</label>
              <input type="number" min="1" value={cfg.idleMin}
                onChange={(e) => setCfg({ ...cfg, idleMin: +e.target.value || 1 })} />
            </div>
            <div className="field">
              <label>{t('offlineAlertMin')}</label>
              <input type="number" min="1" value={cfg.offlineMin}
                onChange={(e) => setCfg({ ...cfg, offlineMin: +e.target.value || 1 })} />
            </div>
            <div className="field">
              <label>{t('speedLimit')}</label>
              <input type="number" min="0" placeholder="0 = off" value={cfg.speedLimit}
                onChange={(e) => setCfg({ ...cfg, speedLimit: +e.target.value || 0 })} />
            </div>

            <h3>{t('workHours')}</h3>
            <div className="field row">
              <input type="time" value={cfg.workFrom}
                onChange={(e) => setCfg({ ...cfg, workFrom: e.target.value })} />
              <span>—</span>
              <input type="time" value={cfg.workTo}
                onChange={(e) => setCfg({ ...cfg, workTo: e.target.value })} />
            </div>

            <h3>{t('alerts')}</h3>
            <div className="field check">
              <label>
                <input type="checkbox" checked={cfg.showDriverName}
                  onChange={(e) => setCfg({ ...cfg, showDriverName: e.target.checked })} />
                <span>{t('showDriverName')}</span>
              </label>
              {!cfg.showDriverName && <p className="warn small">{t('showDriverNameWarn')}</p>}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

function AlertsFeed({ alerts, t, lang }) {
  const shown = alerts.slice(0, 40)
  return (
    <aside className="panel alerts">
      <header className="phead">
        <h2>{t('alerts')}</h2>
        <span className="count">{alerts.length}</span>
      </header>
      {shown.length === 0 ? (
        <p className="muted small">{t('noAlerts')}</p>
      ) : (
        <ul className="alist">
          {shown.map((a) => (
            <li key={a.id} className={`lvl-${a.level}`}>
              <span className="dot" style={{ background: a.level >= 2 ? '#ef4444' : a.level === 1 ? '#f59e0b' : '#6b7280' }} />
              <div className="abody">
                <div className="atop">
                  <strong>{t(a.type) || a.type}</strong>
                  <span className="atime">{ago(a.time, lang)}</span>
                </div>
                <div className="ameta">
                  {a.deviceName}
                  {/* the name only exists here because the user explicitly enabled it */}
                  {a.driverName ? ` · ${a.driverName}` : ''}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
