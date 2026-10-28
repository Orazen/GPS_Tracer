import { ago } from '../../api/traccar'
import { dateTimeRome, formatCount } from '../../lib/format'
import { STATE } from '../../lib/status'
import { SectionGroup } from '../Section'
import { ScrapTiles } from '../scrap/ScrapScreen'
import { EmptyState, ErrorState, LoadingState } from './States'

/**
 * The first screen: what the console really knows, and nothing it does not.
 *
 * Every number here comes from the Traccar data the app already loads. Until the
 * first position read has completed (`live`), the fleet counts are not known, so
 * they say "unavailable" rather than a zero that would look like a quiet fleet.
 * The scrap figures are placeholders for the same reason: they have no source.
 */
export default function Overview({ t, lang, devices, trucks, counts, online, alerts, live, loading, err, onRetry }) {
  const na = t('unavailable')
  const lastFix = trucks.reduce((best, x) => {
    const ts = x.position ? new Date(x.position.fixTime).getTime() : NaN
    return Number.isFinite(ts) && (best == null || ts > best) ? ts : best
  }, null)

  const num = (n) => (live ? formatCount(n, lang) : null)
  const kpis = [
    { k: 'kpiTotal', v: formatCount(devices.length, lang) },
    { k: 'kpiOnline', v: num(online) },
    { k: 'kpiOffline', v: num(counts[STATE.OFFLINE]) },
    { k: 'kpiMoving', v: num(counts[STATE.MOVING]) },
    { k: 'kpiStopped', v: num(counts[STATE.IDLE]) },
    { k: 'kpiNever', v: num(counts[STATE.NEVER]) },
    { k: 'kpiAlerts', v: live ? formatCount(alerts.length, lang) : null },
    {
      k: 'kpiLastUpdate',
      v: live && lastFix != null ? dateTimeRome(lastFix, lang) : null,
      sub: live && lastFix != null ? ago(new Date(lastFix).toISOString(), lang) : null,
    },
  ]

  let body
  if (loading && devices.length === 0) body = <LoadingState t={t} />
  else if (devices.length === 0) body = <EmptyState title={t('emptyFleetTitle')} body={t('emptyFleetBody')} />
  else {
    body = (
      <div className="ov-kpis">
        {kpis.map((k) => (
          <div className="ov-kpi" key={k.k}>
            <span className="ov-kpi__label">{t(k.k)}</span>
            {k.v == null
              ? <span className="ov-kpi__na">{na}</span>
              : <b className="ov-kpi__value">{k.v}</b>}
            {k.sub && <span className="ov-kpi__sub">{k.sub}</span>}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="pad overview">
      {err && <ErrorState t={t} message={err} onRetry={onRetry} />}
      <SectionGroup icon="fleet" title={t('navLive')} card={null}>
        {body}
      </SectionGroup>
      <p className="muted small">{t('kpiWhy')}</p>
      <SectionGroup icon="scrap" title={t('navScrap')}>
        <ScrapTiles t={t} />
      </SectionGroup>
    </div>
  )
}
