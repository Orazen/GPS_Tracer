import { useCallback, useEffect, useState } from 'react'
import { api } from './api/traccar'
import { makeT } from './i18n'
import { COLOR, STATE, buildAlerts, truckState } from './lib/status'
import FleetMap from './components/FleetMap'
import Icon from './components/Icon'
import TruckList from './components/TruckList'
import TruckPanel from './components/TruckPanel'
import TrailHistory from './components/TrailHistory'
import GeofenceManager from './components/GeofenceManager'
import Reports from './components/Reports'
import Tacho from './components/Tacho'
import ConnectTracker from './components/ConnectTracker'
import { SectionGroup } from './components/Section'
import { ago } from './api/traccar'
import AppNav from './components/shell/AppNav'
import PageHeader from './components/shell/PageHeader'
import Overview from './components/shell/Overview'
import { NotYetAvailable } from './components/shell/States'
import ScrapScreen from './components/scrap/ScrapScreen'
import { sectionOf, screenLabel, visibleSections } from './components/shell/sections'

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
  const [view, setView] = useState('overview')
  // True once a position read has succeeded. Until then the fleet counts on the
  // Overview are not known, and it says so instead of showing a zero.
  const [live, setLive] = useState(false)
  // The map's own "frame the fleet" button. Bumping this re-runs FleetMap's fit
  // effect, which is the only way to ask MapLibre to re-frame a view without
  // handing it the map object.
  const [fitToken, setFitToken] = useState(0)
  // Hiding the pane gives the map the whole window. The reference has the same
  // control in the same corner of its switcher.
  const [narrow, setNarrow] = useState(false)
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

  // ---- reload devices (after registering one from the onboarding screen) --
  // Registering a tracker from the Connect screen has to put it in the roster and
  // on the map immediately: a technician who has just created a device and does
  // not see it in the list will create it again.
  const reloadDevices = useCallback(async () => {
    try {
      const d = await api.devices()
      setDevices(d)
      setSelectedId((cur) => cur ?? d[0]?.id ?? null)
      return d
    } catch (e) {
      if (e.auth) onLogout()
      else setErr(String(e.message || e))
      return null
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
        setLive(true)
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
  // See main.jsx: the attribute a screen reader chooses its voice from.
  useEffect(() => { document.documentElement.lang = lang }, [lang])

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

  // ---- what a unit card's actions do ------------------------------------
  // Each one selects the unit first, because every screen on the right of the
  // pane is about one unit and it must be the one whose card was pressed.
  const select = (id) => setSelectedId(id)
  const follow = (id) => { select(id); setView('map'); setFitToken((n) => n + 1) }
  const openHistory = (id) => { select(id); setView('history') }
  const openReports = (id) => { select(id); setView('reports') }

  // ---- render ------------------------------------------------------------
  //
  // The map is the page and the pane floats on it, which is the one structural
  // thing the reference console does that a grid of columns cannot: the fleet
  // stays the largest object on screen no matter which panel is open. The pane
  // itself is one instrument -- a 100px tile strip, a 48px title bar and a grey
  // body sharing a single 12px radius -- rather than the three separate white
  // cards with map showing between them that it used to be.
  //
  // The fleet map is mounted only on the fleet screen: it is a WebGL canvas, and
  // keeping a second one alive behind a report nobody asked for would cost the
  // browser a render loop for nothing.
  return (
    <div className="app">
      {/* First in the DOM, not merely first in the shell: MapLibre mounts its own
          canvas and controls into the map container, which renders above the
          shell and is therefore focusable before it. Measured with the audit's
          keyboard pass, the skip link was the SIXTH tab stop -- behind a WebGL
          canvas, two zoom buttons and an attribution toggle -- which is to say
          useless. Here it is the first. */}
      <a className="skip" href="#main">{t('skipToContent')}</a>
      <AppNav
        sections={visibleSections(user)}
        view={view}
        onView={setView}
        lang={lang}
        onLang={setLang}
        t={t}
        email={user.email}
        onLogout={onLogout}
      />

      <div className="app-stage">
      {view === 'map' && (
        <div className="mapwrap">
          <FleetMap
            trucks={trucks}
            selectedId={selectedId}
            onSelect={setSelectedId}
            geofences={geofences}
            fitToken={fitToken}
            t={t}
          />
        </div>
      )}

      <div className={`shell${narrow ? ' shell-narrow' : ''}`}>
        <aside className="pane">
          {/* The pane's header: the hide control on the left, the screen's name
              in the middle and the fleet size with the frame control on the
              right. The section switcher now lives in the navigation shell, so
              the tiles that used to sit here are gone. */}
          <div className="pane__header">
            <div className="pane__left">
              <button
                className="icon-btn"
                onClick={() => setNarrow((n) => !n)}
                aria-pressed={narrow}
                aria-label={narrow ? t('showList') : t('hideList')}
                title={narrow ? t('showList') : t('hideList')}
              >
                <Icon name="back" />
              </button>
            </div>
            <h2 className="pane__title">{screenLabel(t, view)}</h2>
            <div className="pane__right">
              {/* the fleet size, once, as a count and not as a sentence */}
              <span className="fcount" title={t('trucks')}>{trucks.length}</span>
              <button
                className="icon-btn"
                onClick={() => { setView('map'); setFitToken((n) => n + 1) }}
                aria-label={t('frameFleet')}
                title={t('frameFleet')}
              >
                <Icon name="target" />
              </button>
            </div>
          </div>

          {/* The roster, always: every screen to the right of the pane is about
              one truck, so switching which truck must stay possible while
              reading a report. The five counters ride at the top of the grey
              body as a chip row, which is the reference's own way of printing a
              set of readings. */}
          <div className="pane__body">
            <div className="pane__stats">
              <span className="stat s-ok"><b>{online}</b> {t('online')}</span>
              <span className="stat s-moving"><b>{counts[STATE.MOVING]}</b> {t('moving')}</span>
              <span className="stat s-idle"><b>{counts[STATE.IDLE]}</b> {t('idle')}</span>
              <span className="stat s-offline"><b>{counts[STATE.OFFLINE]}</b> {t('offline')}</span>
              {counts[STATE.ALERT] > 0 && (
                <span className="stat s-alert"><b>{counts[STATE.ALERT]}</b> {t('inAlert')}</span>
              )}
              {err && <span className="err">{err}</span>}
            </div>

            <TruckList
              trucks={trucks}
              selectedId={selectedId}
              onSelect={select}
              onFollow={follow}
              onHistory={openHistory}
              onReports={openReports}
              t={t}
              lang={lang}
              showDriverName={cfg.showDriverName}
            />
          </div>

        </aside>

        {/* Rendered in every view, empty on the fleet screen. It is what puts the
            workspace on the right of the pane: the shell is a flex row and
            without a middle child the two panels sit shoulder to shoulder over
            the map and the console reads backwards. */}
        <main className="col-main" id="main" tabIndex={-1}>
          <PageHeader
            t={t}
            crumbs={[sectionOf(view) && t(sectionOf(view).labelKey), screenLabel(t, view)].filter(Boolean)}
            title={screenLabel(t, view)}
          />
          {view === 'map' ? (
            <aside className="col-right">
              <TruckPanel
                truck={selected}
                t={t}
                lang={lang}
                showDriverName={cfg.showDriverName}
                onShowHistory={() => setView('history')}
              />
              <AlertsFeed alerts={alerts} t={t} lang={lang} />
            </aside>
          ) : (
            /* Keyed on the view so the panel remounts and its 180ms entrance
               (styles.css, "motion") runs once per screen change rather than
               never. */
            <div className="workspace" key={view}>
              {view === 'overview' && (
                <Overview
                  t={t}
                  lang={lang}
                  devices={devices}
                  trucks={trucks}
                  counts={counts}
                  online={online}
                  alerts={alerts}
                  live={live}
                  loading={loading}
                  err={err}
                  onRetry={reloadDevices}
                />
              )}
              {view === 'scrap' && <ScrapScreen t={t} />}
              {view === 'inventory' && (
                <div className="pad">
                  <NotYetAvailable t={t} title={t('inventory')} body={t('inventoryBody')} />
                </div>
              )}
              {view === 'sales' && (
                <div className="pad">
                  <NotYetAvailable t={t} title={t('sales')} body={t('salesBody')} />
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
              {view === 'alerts' && <AlertsScreen alerts={alerts} t={t} lang={lang} />}
              {/* Tachograph screens. These talk to the tachograph service through
                  the dashboard's own proxy, so no service token ever reaches this
                  code. */}
              {/* The Tachograph screen needs the fleet and a way to refresh it:
                  its Drivers tab assigns a driver to a truck, and that assignment
                  is mirrored into the tracker console so the roster and the
                  alerts agree with the registry. */}
              {view === 'tacho' && (
                <Tacho
                  t={t}
                  lang={lang}
                  devices={devices}
                  showDriverName={cfg.showDriverName}
                  onDevicesChanged={reloadDevices}
                />
              )}
              {view === 'connect' && (
                <ConnectTracker
                  trucks={trucks}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  onChanged={reloadDevices}
                  t={t}
                  lang={lang}
                />
              )}
              {view === 'settings' && <Settings cfg={cfg} setCfg={setCfg} lang={lang} setLang={setLang} t={t} />}
            </div>
          )}
        </main>
      </div>
      </div>
    </div>
  )
}

/**
 * Settings, lifted out of the shell and rebuilt as the reference builds a
 * settings page: a list of section cards, each a 52px row of a glyph, a title
 * and a one-line explanation, with the controls that belong to it underneath.
 *
 * Nothing about what it sets changed here except where it lives and how it is
 * grouped. The grouping is the improvement: it was previously five labels in a
 * column under three headings, and there was no way to tell from the page which
 * of the three the account toggle belonged to.
 */
function Settings({ cfg, setCfg, lang, setLang, t }) {
  return (
    <div className="pad settings">
      <div className="sections">
        <SectionGroup icon="settings" title={t('language')}>
          <div className="field">
            <label>{t('language')}</label>
            <div className="lang">
              <button className={lang === 'it' ? 'on' : ''} onClick={() => setLang('it')}>Italiano</button>
              <button className={lang === 'en' ? 'on' : ''} onClick={() => setLang('en')}>English</button>
            </div>
          </div>
        </SectionGroup>

        {/* The label is associated, not merely adjacent: `.field` puts the label
            and the input side by side, so `closest('label')` finds nothing and
            without htmlFor/id a screen reader announces "spin button" and no more. */}
        <SectionGroup icon="speed" title={t('threshold')} sub={t('thresholdWhy')}>
          <div className="field">
            <label htmlFor="cfg-idle">{t('idleAlertMin')}</label>
            <input id="cfg-idle" type="number" min="1" value={cfg.idleMin}
              onChange={(e) => setCfg({ ...cfg, idleMin: +e.target.value || 1 })} />
          </div>
          <div className="field">
            <label htmlFor="cfg-offline">{t('offlineAlertMin')}</label>
            <input id="cfg-offline" type="number" min="1" value={cfg.offlineMin}
              onChange={(e) => setCfg({ ...cfg, offlineMin: +e.target.value || 1 })} />
          </div>
          <div className="field">
            <label htmlFor="cfg-speed">{t('speedLimit')}</label>
            <input id="cfg-speed" type="number" min="0" placeholder="0 = off" value={cfg.speedLimit}
              onChange={(e) => setCfg({ ...cfg, speedLimit: +e.target.value || 0 })} />
          </div>
        </SectionGroup>

        <SectionGroup icon="clock" title={t('workHours')} sub={t('workHoursWhy')}>
          {/* Two time fields either side of a dash: there is nothing to
              associate a label with visually, so each carries its own name. */}
          <div className="field row">
            <input type="time" aria-label={t('workFrom')} value={cfg.workFrom}
              onChange={(e) => setCfg({ ...cfg, workFrom: e.target.value })} />
            <span aria-hidden="true">—</span>
            <input type="time" aria-label={t('workTo')} value={cfg.workTo}
              onChange={(e) => setCfg({ ...cfg, workTo: e.target.value })} />
          </div>
        </SectionGroup>

        <SectionGroup icon="bell" title={t('alerts')}>
          <div className="field check">
            <label>
              <input type="checkbox" checked={cfg.showDriverName}
                onChange={(e) => setCfg({ ...cfg, showDriverName: e.target.checked })} />
              <span>{t('showDriverName')}</span>
            </label>
            {!cfg.showDriverName && <p className="warn small">{t('showDriverNameWarn')}</p>}
          </div>
        </SectionGroup>
      </div>
    </div>
  )
}

/** The alert feed as a screen of its own, under its own tile. */
function AlertsScreen({ alerts, t, lang }) {
  return (
    <div className="pad">
      <div className="ws-head">
        <span className="count">{alerts.length}</span>
      </div>
      <AlertsFeed alerts={alerts} t={t} lang={lang} bare />
    </div>
  )
}

/**
 * The feed itself.
 *
 * `bare` drops the card around it, because on the alerts screen the page is
 * already the card -- a card inside a card on the same surface is the nesting
 * this whole restyle exists to remove.
 */
function AlertsFeed({ alerts, t, lang, bare = false }) {
  const shown = alerts.slice(0, 40)
  const body = shown.length === 0 ? (
    <p className="muted small">{t('noAlerts')}</p>
  ) : (
    <ul className="alist">
      {shown.map((a) => (
        <li key={a.id} className={`lvl-${a.level}`}>
          <span className="dot" style={{ background: a.level >= 2 ? COLOR[STATE.ALERT] : a.level === 1 ? COLOR[STATE.IDLE] : COLOR[STATE.NEVER] }} />
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
  )

  if (bare) return body

  return (
    <aside className="panel alerts">
      <header className="phead">
        <h2>{t('alerts')}</h2>
        <span className="count">{alerts.length}</span>
      </header>
      {body}
    </aside>
  )
}
