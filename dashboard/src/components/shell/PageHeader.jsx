/**
 * The title and breadcrumb every page starts with: "Live Fleet / Zones", then the
 * name of the screen. The breadcrumb is text, not links, because the sidebar
 * already is the way to move; a second set of links to the same places would be
 * two controls for one job.
 */
export default function PageHeader({ crumbs, title, t }) {
  return (
    <header className="page-head">
      <nav aria-label={t('breadcrumb')}>
        <ol className="crumbs">
          {crumbs.map((c, i) => (
            <li key={`${i}-${c}`} aria-current={i === crumbs.length - 1 ? 'page' : undefined}>
              {c}
              {i < crumbs.length - 1 && <span className="crumbs__sep" aria-hidden="true">/</span>}
            </li>
          ))}
        </ol>
      </nav>
      <h1 className="page-head__title">{title}</h1>
    </header>
  )
}
