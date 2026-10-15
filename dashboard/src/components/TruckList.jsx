import { useState } from 'react'
import { ago } from '../api/traccar'
import { STATE, driverOf } from '../lib/status'
import Icon from './Icon'

/**
 * The truck roster, drawn as the reference console draws a unit.
 *
 * This exists because a dispatch console must never depend on a map tile
 * server. If WebGL is blocked, tiles time out, or the tab is backgrounded and
 * requestAnimationFrame is throttled, the map shows nothing -- the dispatcher
 * still needs to know which trucks are online, which are moving and which have
 * gone quiet. That information comes from the API, not from OpenStreetMap.
 *
 * The shape of a card is the reference's own, measured off its live DOM
 * (styles.css, "The reference console's own geometry"): a 40px head of a 28px
 * vehicle glyph, the name at 14/500 and the last-contact time at 12px under it;
 * a row of 40x48 action tiles; a 1px separator; the address with the age it was
 * resolved at; and a chip row of readings, each with the glyph that says what
 * the number is. It is a card rather than a table row because the dispatcher
 * reasons about a truck, not about a record.
 *
 * Two things here are deliberately ours rather than the reference's:
 *
 *   The action row holds only actions that exist, and it holds all of them.
 *     The reference has nine tiles on a unit card; five of them open subsystems
 *     this dashboard does not have, and a dead control is worse than a short
 *     row. Follow used to sit in the card's head instead, which made the head
 *     two things where the reference's is one -- a name and a status line -- so
 *     it moved here and the row is now every action this console has.
 *   Nothing is a nested button. The reference's card is a clickable row with
 *     buttons inside it, which is invalid enough that a browser will hoist the
 *     inner ones out; here the head is the button and the tiles are its
 *     siblings.
 */
export default function TruckList({
  trucks,
  selectedId,
  onSelect,
  onFollow,
  onHistory,
  onReports,
  t,
  lang,
  showDriverName = false,
}) {
  const [copiedId, setCopiedId] = useState(null)
  const order = { [STATE.ALERT]: 0, [STATE.MOVING]: 1, [STATE.IDLE]: 2, [STATE.OFFLINE]: 3, [STATE.NEVER]: 4 }
  const sorted = [...trucks].sort(
    (a, b) => (order[a.state] - order[b.state]) || a.device.name.localeCompare(b.device.name)
  )

  if (!trucks.length) {
    return <p className="muted small pad-s">{t('noDevices')}</p>
  }

  const copyFix = async (device, position) => {
    const text = `${device.name} ${position.latitude.toFixed(5)}, ${position.longitude.toFixed(5)}`
    try {
      await navigator.clipboard.writeText(text)
      setCopiedId(device.id)
      setTimeout(() => setCopiedId((cur) => (cur === device.id ? null : cur)), 1600)
    } catch {
      /* A refused clipboard is the browser's decision, not an error worth a
         banner: the coordinates are on the card either way. */
    }
  }

  return (
    <ul className="ucards">
      {sorted.map(({ device, position, state, ageS }) => {
        const on = device.id === selectedId
        const speed = Number(position?.speed ?? 0) || 0
        // Only when the account has enabled it. The attribute is written by the
        // driver registry (Tachograph -> Drivers), and a name beside a truck's
        // working state is worker monitoring: off by default, and off here too,
        // not only in the alerts. See DASHBOARD-SPEC.md and lib/status.js.
        const driver = showDriverName ? driverOf(device) : null
        const ignition = position?.attributes?.ignition
        const battery = position?.attributes?.batteryLevel ?? position?.attributes?.battery
        const course = Number(position?.course ?? NaN)
        const fixTime = position?.fixTime ? new Date(position.fixTime) : null
        const address = position?.address
          || (position ? `${position.latitude.toFixed(4)}, ${position.longitude.toFixed(4)}` : null)
        const copied = copiedId === device.id

        return (
          <li key={device.id}>
            <div className={`unitcard s-${state}${on ? ' on' : ''}`}>
              <div className="uc-head">
                <button
                  className="uc-open"
                  onClick={() => onSelect(device.id)}
                  aria-current={on ? 'true' : undefined}
                  aria-label={device.name}
                >
                  <span className="uc-type"><Icon name="truck" size={28} /></span>
                  <span className="uc-main">
                    <span className="uc-name">{device.name}</span>
                    <span className="uc-status">
                      <Icon name="clock" size={12} />
                      {state === STATE.NEVER
                        ? t('never')
                        : `${t(state)} · ${ago(position.fixTime, lang)}`}
                      {/* The driver name is the one place on this screen a
                          dispatcher reads a person, and it is only attached to
                          the card at all when the account has enabled it -- see
                          DASHBOARD-SPEC.md and lib/status.js. `showDriverName`
                          gates it here as well as in buildAlerts: the switch
                          having been honoured in the alerts and not in the
                          roster would have been the same claim, half true. */}
                      {driver && <span className="uc-driver">{driver}</span>}
                    </span>
                  </span>
                </button>
              </div>

              <div className="ictiles">
                <span className="ictile">
                  <button className={`ib${on ? ' on' : ''}`} onClick={() => onFollow?.(device.id)}
                    aria-label={t('follow')} title={t('follow')}>
                    <Icon name="target" />
                  </button>
                </span>
                <span className="ictile">
                  <button className="ib" onClick={() => onHistory?.(device.id)}
                    aria-label={t('openHistory')} title={t('openHistory')}>
                    <Icon name="history" />
                  </button>
                </span>
                <span className="ictile">
                  <button className="ib" onClick={() => onReports?.(device.id)}
                    aria-label={t('openReports')} title={t('openReports')}>
                    <Icon name="reports" />
                  </button>
                </span>
                <span className="ictile">
                  <button className="ib" onClick={() => position && copyFix(device, position)}
                    disabled={!position}
                    aria-label={t('copyFix')} title={copied ? t('copied') : t('copyFix')}>
                    {copied ? <Icon name="pin" /> : <Icon name="share" />}
                  </button>
                </span>
              </div>

              <hr className="sep" />

              <div className="addrrow">
                <span className="addrrow__ic"><Icon name="pin" /></span>
                <span className="addrrow__main">
                  <span className="addrrow__line">{address || t('noAddress')}</span>
                  <span className="addrrow__age">
                    {fixTime ? fixTime.toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit' }) : t('never')}
                  </span>
                </span>
              </div>

              {/* The readings, in the reference's order: ignition, speed,
                  bearing, battery, last fix. Each carries its own glyph because
                  five numbers in a row are otherwise read one column at a time. */}
              <div className="chiprow">
                <span className={`chip2 ${ignition === true ? 'pos' : 'mut'}`}>
                  <Icon name="ignition" size={20} />
                  {ignition === true ? t('on') : ignition === false ? t('off') : '—'}
                </span>
                <span className="chip2 mut">
                  <Icon name="speed" size={20} />
                  {Math.round(speed)} {t('kmh')}
                </span>
                {Number.isFinite(course) && (
                  <span className="chip2 mut">
                    <Icon name="heading" size={20} />
                    {bearing(course)}
                  </span>
                )}
                {battery != null && (
                  <span className={`chip2 ${Number(battery) <= 20 ? 'neg' : 'mut'}`}>
                    <Icon name="battery" size={20} />
                    {Math.round(Number(battery))} %
                  </span>
                )}
                <span className="chip2 mut">
                  <Icon name="clock" size={20} />
                  {fixTime ? fixTime.toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit' }) : '—'}
                </span>
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

/** The eight-point compass and the bearing itself, as "NW, 315°". */
function bearing(course) {
  const points = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
  const deg = ((course % 360) + 360) % 360
  return `${points[Math.round(deg / 45) % 8]}, ${Math.round(deg)}°`
}
