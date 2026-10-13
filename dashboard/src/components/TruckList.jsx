import { ago } from '../api/traccar'
import { COLOR, STATE, driverOf } from '../lib/status'

/**
 * The truck roster.
 *
 * This exists because a dispatch console must never depend on a map tile
 * server. If WebGL is blocked, tiles time out, or the tab is backgrounded and
 * requestAnimationFrame is throttled, the map shows nothing -- the dispatcher
 * still needs to know which trucks are online, which are moving and which have
 * gone quiet. That information comes from the API, not from OpenStreetMap.
 */
export default function TruckList({ trucks, selectedId, onSelect, t, lang }) {
  const order = { [STATE.ALERT]: 0, [STATE.MOVING]: 1, [STATE.IDLE]: 2, [STATE.OFFLINE]: 3, [STATE.NEVER]: 4 }
  const sorted = [...trucks].sort(
    (a, b) => (order[a.state] - order[b.state]) || a.device.name.localeCompare(b.device.name)
  )

  if (!trucks.length) {
    return (
      <div className="tlist">
        <header className="phead"><h2>{t('trucks')}</h2></header>
        <p className="muted small pad-s">{t('noDevices')}</p>
      </div>
    )
  }

  return (
    <div className="tlist">
      <header className="phead">
        <h2>{t('trucks')}</h2>
        <span className="count">{trucks.length}</span>
      </header>
      <ul>
        {sorted.map(({ device, position, state, ageS }) => {
          const speed = Number(position?.speed ?? 0) || 0
          const driver = driverOf(device)
          return (
            <li key={device.id}>
              <button
                className={`trow ${device.id === selectedId ? 'on' : ''} s-${state}`}
                onClick={() => onSelect(device.id)}
              >
                <span className="tdot" style={{ background: COLOR[state] }} />
                <span className="tmain">
                  <span className="tname">{device.name}</span>
                  <span className="tsub">
                    {state === STATE.NEVER
                      ? t('never')
                      : state === STATE.OFFLINE
                        ? `${t('offline')} ${ago(position.fixTime, lang)}`
                        : position
                          ? `${Math.round(speed)} ${t('kmh')} · ${ago(position.fixTime, lang)}`
                          : '—'}
                  </span>
                </span>
                {driver && <span className="tdrv">{driver}</span>}
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
