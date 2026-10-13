import { Component, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import 'maplibre-gl/dist/maplibre-gl.css'
import './styles.css'
import { api } from './api/traccar'
import { makeT } from './i18n'
import App from './App'

/**
 * A crash in the map or the API layer used to produce a blank white page with
 * no explanation, which is the worst possible failure for something you are
 * showing to a client. Now it prints the error.
 */
class Boundary extends Component {
  constructor(p) { super(p); this.state = { err: null } }
  static getDerivedStateFromError(err) { return { err } }
  componentDidCatch(err, info) { console.error('dashboard crashed:', err, info) }
  render() {
    if (!this.state.err) return this.props.children
    return (
      <div className="crash">
        <h2>Errore</h2>
        <pre>{String(this.state.err?.stack || this.state.err)}</pre>
        <button className="btn" onClick={() => location.reload()}>Ricarica</button>
      </div>
    )
  }
}

function Login({ onDone }) {
  const [lang, setLang] = useState(() => localStorage.getItem('gt.lang') || 'it')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const t = makeT(lang)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setErr(null)
    try {
      const user = await api.login(email.trim(), password)
      onDone(user)
    } catch (e2) {
      setErr(e2.message === 'login_failed' ? t('badLogin') : t('serverError'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <form onSubmit={submit}>
        <div className="brand big">
          <span className="logo" />
          <strong>{t('appName')}</strong>
        </div>
        <h1>{t('login')}</h1>
        <input
          type="email" autoFocus required
          placeholder={t('email')} value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          type="password" required
          placeholder={t('password')} value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {err && <p className="err">{err}</p>}
        <button className="btn primary wide" disabled={busy}>
          {busy ? t('signingIn') : t('signIn')}
        </button>
        <div className="lang row">
          <button type="button" className={lang === 'it' ? 'on' : ''} onClick={() => setLang('it')}>IT</button>
          <button type="button" className={lang === 'en' ? 'on' : ''} onClick={() => setLang('en')}>EN</button>
        </div>
      </form>
    </div>
  )
}

// Remembers whether this browser has ever held a Traccar session.
//
// Traccar reports "not logged in" as a 4xx (404 from /api/session, 401 from
// /api/devices), and Chrome writes every failed response to the console whether
// or not the JS handles it. So on a genuine first visit, probing the API just to
// learn "no session yet" fills the console with an error for a visitor who has
// not even logged in. This flag lets us skip the pointless probe: no session has
// ever existed here, so go straight to the login form.
//
// It is only ever a hint for skipping a *known-pointless* request. The session
// cookie is the real authority -- if the flag is set but the session has since
// expired, the probe still runs, still fails, and we clear the flag.
const SESSION_HINT = 'gt.hadSession'

export default function Root() {
  const [user, setUser] = useState(null)
  const [booting, setBooting] = useState(true)

  // Traccar keeps you logged in via JSESSIONID, so on reload we can just ask.
  useEffect(() => {
    let alive = true
    if (localStorage.getItem(SESSION_HINT) !== '1') {
      // Never had a session on this browser: don't ask, don't log an error.
      setBooting(false)
      return
    }
    api.whoami()
      .then((u) => {
        if (!alive) return
        if (u?.id) setUser(u)
        else localStorage.removeItem(SESSION_HINT)   // session expired
      })
      .catch(() => { localStorage.removeItem(SESSION_HINT) })
      .finally(() => { if (alive) setBooting(false) })
    return () => { alive = false }
  }, [])

  const onLoggedIn = (u) => {
    localStorage.setItem(SESSION_HINT, '1')
    setUser(u)
  }

  const logout = async () => {
    await api.logout()
    localStorage.removeItem(SESSION_HINT)
    setUser(null)
  }

  if (booting) return <div className="boot" />
  if (!user) return <Login onDone={onLoggedIn} />
  return <Boundary><App user={user} onLogout={logout} /></Boundary>
}

// Mount. Without this the whole module graph loads, the CSS applies, no error is
// thrown -- and #root stays empty forever. That is exactly what happened.
const el = document.getElementById('root')
if (el) createRoot(el).render(<Root />)
