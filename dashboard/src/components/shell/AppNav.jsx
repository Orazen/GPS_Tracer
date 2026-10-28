import { useEffect, useRef, useState } from 'react'
import Icon from '../Icon'
import { screenLabel, sectionOf } from './sections'

/**
 * The unified navigation: a sidebar on a wide window, and on a narrow one a top
 * bar whose menu button opens the same sidebar as a drawer. One list, so the two
 * can never disagree about what exists.
 *
 * Keyboard: every entry is a real button with aria-current on the one that is
 * open. Escape closes the drawer and returns focus to its menu button. The drawer
 * is taken out of the tab order while closed (`visibility`), so a hidden menu
 * cannot swallow Tab presses.
 */
export default function AppNav({ sections, view, onView, lang, onLang, t, email, onLogout }) {
  const [open, setOpen] = useState(false)
  const menuBtn = useRef(null)
  const active = sectionOf(view)

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') {
        setOpen(false)
        menuBtn.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const go = (v) => {
    onView(v)
    setOpen(false)
  }

  return (
    <>
      <header className="topbar">
        <button
          ref={menuBtn}
          className="icon-btn"
          aria-expanded={open}
          aria-controls="sidenav"
          aria-label={open ? t('menuClose') : t('menuOpen')}
          title={open ? t('menuClose') : t('menuOpen')}
          onClick={() => setOpen((o) => !o)}
        >
          <Icon name={open ? 'close' : 'menu'} />
        </button>
        <span className="topbar__brand">{t('appName')}</span>
        <span className="topbar__title">{screenLabel(t, view)}</span>
      </header>

      {open && <div className="sidescrim" aria-hidden="true" onClick={() => setOpen(false)} />}

      <nav id="sidenav" className={`sidenav${open ? ' open' : ''}`} aria-label={t('navMain')}>
        <div className="sidenav__brand">{t('appName')}</div>
        <ul className="sidenav__list">
          {sections.map((s) => {
            const on = active?.id === s.id
            return (
              <li key={s.id}>
                <button
                  className={`sidenav__item${on ? ' on' : ''}`}
                  aria-current={on && s.screens.length === 1 ? 'page' : undefined}
                  onClick={() => go(s.screens[0])}
                >
                  <Icon name={s.icon} />
                  <span>{t(s.labelKey)}</span>
                </button>
                {on && s.screens.length > 1 && (
                  <ul className="sidenav__sub" aria-label={t(s.labelKey)}>
                    {s.screens.map((v) => (
                      <li key={v}>
                        <button
                          className={`sidenav__sub-item${view === v ? ' on' : ''}`}
                          aria-current={view === v ? 'page' : undefined}
                          onClick={() => go(v)}
                        >
                          {screenLabel(t, v)}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>

        <div className="sidenav__foot">
          <span className="who" title={email}>{email}</span>
          <div className="sidenav__row">
            <div className="lang" role="group" aria-label={t('language')}>
              <button className={lang === 'it' ? 'on' : ''} aria-pressed={lang === 'it'} onClick={() => onLang('it')}>IT</button>
              <button className={lang === 'en' ? 'on' : ''} aria-pressed={lang === 'en'} onClick={() => onLang('en')}>EN</button>
            </div>
            <button className="btn ghost tiny" onClick={onLogout}>{t('logout')}</button>
          </div>
        </div>
      </nav>
    </>
  )
}
