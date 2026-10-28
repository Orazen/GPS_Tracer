import { NotYetAvailable } from '../shell/States'

/**
 * The three figures the scrap operation will show, each as a placeholder. They
 * carry no number and no zero: until the scrap client is connected, a "0" here
 * would read as "no weighings today", which is a claim about the yard that
 * nothing has checked.
 */
export function ScrapTiles({ t }) {
  return (
    <div className="ov-scrap">
      {['scrapWeighings', 'scrapIntakes', 'scrapStock'].map((k) => (
        <div className="ov-soon" key={k}>
          <span className="ov-soon__label">{t(k)}</span>
          <span className="ov-soon__value">{t('scrapSoon')}</span>
        </div>
      ))}
    </div>
  )
}

export default function ScrapScreen({ t }) {
  return (
    <div className="pad">
      <NotYetAvailable t={t} body={t('scrapSoonBody')} />
      <ScrapTiles t={t} />
    </div>
  )
}
