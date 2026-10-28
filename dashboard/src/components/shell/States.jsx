/**
 * The four states every screen can be in besides its content, so they look and
 * read the same wherever they appear.
 *
 *   LoadingState       waiting on the server; polite live region
 *   EmptyState         the server answered and there is genuinely nothing
 *   ErrorState         the server failed; says what, and offers a retry
 *   NotYetAvailable    the screen exists in the design but has no data source
 *
 * NotYetAvailable is the only one that is not about a request. It never shows
 * sample numbers: a dispatcher who reads an invented figure as real is the worst
 * outcome this console can produce.
 */

export function LoadingState({ t }) {
  return (
    <div className="state state--loading" role="status" aria-live="polite">
      <span className="state__dot" aria-hidden="true" />
      <span>{t('loading')}</span>
    </div>
  )
}

export function EmptyState({ title, body }) {
  return (
    <div className="state state--empty">
      <strong className="state__title">{title}</strong>
      {body && <p className="state__body">{body}</p>}
    </div>
  )
}

export function ErrorState({ t, message, onRetry }) {
  return (
    <div className="state state--error" role="alert">
      <strong className="state__title">{t('errorTitle')}</strong>
      {message && <p className="state__body">{message}</p>}
      {onRetry && (
        <button className="btn ghost tiny" onClick={onRetry}>{t('retry')}</button>
      )}
    </div>
  )
}

export function NotYetAvailable({ t, title, body }) {
  return (
    <div className="state state--soon">
      <strong className="state__title">{title || t('notYetTitle')}</strong>
      <p className="state__body">{body || t('notYetBody')}</p>
    </div>
  )
}
