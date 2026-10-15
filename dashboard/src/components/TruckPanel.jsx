import { ago, fmtDate, fmtTime, km } from '../api/traccar'
import { STATE, driverOf } from '../lib/status'

export default function TruckPanel({ truck, t, lang, onShowHistory, showDriverName = false }) {
  if (!truck) {
    return (
      <aside className="panel empty">
        <p className="muted">{t('noDevices')}</p>
      </aside>
    )
  }
  const { device, position, state, ageS } = truck
  const a = position?.attributes || {}
  const driver = driverOf(device)
  const sats = a?.sat ?? null

  const row = (label, value, hint) => (
    <div className="prow">
      <span className="plabel">{label}</span>
      <span className="pvalue">
        {value}
        {hint ? <em className="phint">{hint}</em> : null}
      </span>
    </div>
  )

  const hasPos = !!position

  return (
    <aside className="panel">
      <header className="phead">
        <h2>{device.name}</h2>
        <span className={`badge s-${state}`}>{t(state)}</span>
      </header>

      <section className="pblock">
        {row(
          t('speed'),
          hasPos ? `${Math.round(position.speed ?? 0)} ${t('kmh')}` : '—'
        )}
        {row(t('ignition'), a.ignition ? t('on') : t('off'))}
        {row(t('mileage'), a.totalDistance != null ? `${km(a.totalDistance)} ${t('km')}` : '—')}
        {/* Three states, not two. "Unassigned" and "assigned but this account
            does not display names" are different facts, and printing the first
            for the second would be a lie somebody could act on. */}
        {row(
          t('driver'),
          !driver ? t('noDriver') : showDriverName ? driver : t('driverHidden')
        )}
        {row(t('lastSeen'), hasPos ? ago(position.fixTime, lang) : t('never'))}
        {/* sat = satellites tracked. This is the fix-quality signal: a 2.5 m
            accuracy on 4 sats means "estimate", on 9+ means "trust it".
            Traccar already stores it, so it is free on a $30 tracker. */}
        {row(t('fixQuality'), sats != null ? `${sats} ${t('sats')}` : '—')}
        {hasPos && (
          <div className="prow">
            <span className="plabel">{t('accuracy')}</span>
            <span className="pvalue">
              {a.accuracy != null ? `${Math.round(a.accuracy)} ${t('m')}` : '—'}
            </span>
          </div>
        )}
        {hasPos && (
          <div className="prow">
            <span className="plabel">IMEI</span>
            <span className="pvalue mono">{device.uniqueId}</span>
          </div>
        )}
      </section>

      {hasPos && (
        <section className="pblock coords">
          <div>
            <span className="plabel">Lat</span>
            <span className="pvalue mono">{position.latitude?.toFixed(6)}</span>
          </div>
          <div>
            <span className="plabel">Lon</span>
            <span className="pvalue mono">{position.longitude?.toFixed(6)}</span>
          </div>
          <div>
            <span className="plabel">{t('speed')} alt.</span>
            <span className="pvalue mono">{position.altitude != null ? `${position.altitude} m` : '—'}</span>
          </div>
        </section>
      )}

      <section className="pblock">
        <h3>{t('arrival')}</h3>
        <button className="btn primary" onClick={() => onShowHistory?.(device.id)}>
          {t('history')}
        </button>
      </section>

      {state === STATE.OFFLINE && (
        <section className="pblock warn">
          <strong>{t('offline')}</strong>
          <p className="muted small">
            {ageS > 3600 ? `${Math.floor(ageS / 3600)} h` : `${Math.floor(ageS / 60)} min`}
          </p>
        </section>
      )}
    </aside>
  )
}
