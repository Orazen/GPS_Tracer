import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/traccar'
import { buildHops, diagnose, fill, refusedEntries, HOP } from '../lib/onboarding'
import {
  buildSms,
  DEFAULT_ACC_INTERVAL,
  DEFAULT_PARKED_INTERVAL,
  MIN_INTERVAL_SECONDS,
} from '../lib/tracker-sms'

/**
 * A hop's state, as one of the four meanings the sheet already has.
 *
 * Reusing the existing `.badge s-*` set rather than inventing four colours: a
 * green chip here has to mean what a green chip means on a truck row. The word
 * inside the chip is what carries the state; the colour is a second reading of
 * it, never the only one.
 */
const STATE_BADGE = {
  [HOP.OK]: 'moving',
  [HOP.WAITING]: 'idle',
  [HOP.BLOCKED]: 'alert',
  [HOP.BLIND]: 'offline',
}

/**
 * Connect a tracker.
 *
 * The printed version of this is `docs/connect-hardware.html`: the same six
 * numbered hops, in the same order, with the same refusal to claim more than the
 * server actually knows. This screen is that sheet with live state, which is the
 * difference between reading a guide and knowing which hop is failing right now.
 *
 * What it adds over the sheet:
 *
 *   * the settings THIS server is running with, read back from what the Traccar
 *     container rendered, instead of the documented default (they differ, and the
 *     difference is the whole answer to "why did my tracker not appear?");
 *   * the identifiers Traccar has already refused, which exist nowhere but its log
 *     and which are a fix in one click here;
 *   * the exact SMS sequence, generated with the operator's own APN and server.
 *
 * Administrator only, and the server enforces that independently of this
 * component: it reports the server's own configuration and the raw identifiers of
 * everything that has probed the public H02 port.
 *
 * What it deliberately does not do: claim the published port works because the
 * listener inside the network answers. No process in this container can see the
 * host side of that mapping, so hop 3 says so and names the one command that can
 * (UNIMPLEMENTED.md §7.8).
 */
export default function ConnectTracker({ trucks, selectedId, onSelect, onChanged, t, lang }) {
  const [status, setStatus] = useState(null)
  const [statusErr, setStatusErr] = useState(null)
  const [subject, setSubject] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)
  const [adoptName, setAdoptName] = useState('')
  const [copied, setCopied] = useState(false)
  // Has the server answered once yet? The hops cannot be stated before it has: hop
  // 2 and 3 are derived from the server's own view, so rendering them from a null
  // status would print "non visibile da qui" -- a claim about the server, made
  // before asking it. The screen states nothing it does not know.
  const [loaded, setLoaded] = useState(false)

  // The SMS generator's inputs. The server address and APN are the two things only
  // the operator knows; everything else has a documented default.
  const [apn, setApn] = useState('')
  const [server, setServer] = useState('')
  const [port, setPort] = useState('')
  const [accInt, setAccInt] = useState(DEFAULT_ACC_INTERVAL)
  const [parkedInt, setParkedInt] = useState(DEFAULT_PARKED_INTERVAL)

  const load = useCallback(async () => {
    try {
      const res = await fetch('/connect/status', {
        credentials: 'include',
        headers: { accept: 'application/json' },
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        setStatus(null)
        setStatusErr(body.detail || `${res.status}`)
        return
      }
      setStatus(body)
      setStatusErr(null)
    } catch (e) {
      setStatus(null)
      setStatusErr(String(e.message || e))
    } finally {
      setLoaded(true)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // While a unit is being brought up this is the screen the technician watches, so
  // it refreshes itself rather than making them press something. Ten seconds is
  // one log tail, one socket probe and one device list.
  useEffect(() => {
    const h = setInterval(load, 10000)
    return () => clearInterval(h)
  }, [load])

  // The port defaults to the one this server publishes, and stops following it as
  // soon as the operator types something — a field that rewrites itself while you
  // are using it is worse than no default at all.
  const [portTouched, setPortTouched] = useState(false)
  useEffect(() => {
    if (!portTouched && status?.h02?.hostPort) setPort(String(status.h02.hostPort))
  }, [status, portTouched])

  const target = trucks.find((x) => x.device.id === selectedId) ?? trucks[0] ?? null
  const device = target?.device ?? null
  const position = target?.position ?? null

  const refused = refusedEntries(status)
  const identifier = subject || refused[0]?.identifier || device?.uniqueId || ''

  // Is the identifier under test the one the selected device is registered under?
  // Only then do the device's own facts (record, position) describe it.
  const matchesDevice = Boolean(device && identifier === device.uniqueId)

  const hops = useMemo(
    () =>
      buildHops({
        identifier,
        device: matchesDevice ? device : null,
        position: matchesDevice ? position : null,
        status,
        readOk: !statusErr,
      }),
    [identifier, matchesDevice, device, position, status, statusErr]
  )
  const diag = diagnose(hops)

  const sms = useMemo(
    () => buildSms({ apn, server, port, accInterval: accInt, parkedInterval: parkedInt }),
    [apn, server, port, accInt, parkedInt]
  )

  const diagText = useMemo(() => {
    if (diag.state === HOP.OK) return t('onb.diag.all')
    if (diag.state === HOP.BLOCKED) {
      return fill(t('onb.diag.blocked'), { n: diag.hop, hop: t(`onb.hop.${diag.key}`) })
    }
    if (diag.state === HOP.WAITING) {
      return fill(t('onb.diag.waiting'), { n: diag.hop, hop: t(`onb.hop.${diag.key}`) })
    }
    return fill(t('onb.diag.blind'), { n: diag.hop ?? '', hop: diag.key ? t(`onb.hop.${diag.key}`) : t('onb.hop.unknown') })
  }, [diag, t])

  const adopt = async () => {
    if (!identifier || !adoptName.trim()) return
    setBusy(true)
    setNote(null)
    try {
      const created = await api.provisionDevice({ name: adoptName.trim(), uniqueId: identifier })
      setNote({ kind: 'ok', text: fill(t('onb.refused.done'), { name: created?.name ?? adoptName.trim(), identifier }) })
      setAdoptName('')
      setSubject('')
      if (created?.id && onSelect) onSelect(created.id)
      if (onChanged) await onChanged()
      await load()
    } catch (e) {
      setNote({ kind: 'bad', text: String(e.message || e) })
    } finally {
      setBusy(false)
    }
  }

  const copy = async () => {
    const text = sms.commands.map((c) => c.text).join('\n')
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch {
      setNote({ kind: 'bad', text: t('onb.sms.copyFailed') })
    }
  }

  const reg = status?.registration ?? null

  return (
    <div className="pad onb">
      <header className="onb-head">
        <h2>{t('onb.title')}</h2>
        <button className="btn tiny" onClick={load}>{t('onb.refresh')}</button>
      </header>
      <p className="muted small onb-lede">{t('onb.lede')}</p>

      {/* ---- where it stops, in one sentence ---------------------------- */}
      {/* While the first request is in flight the screen shows its own shape, not
          a spinner: six rows that are about to fill in, and one line of prose. */}
      {!loaded ? (
        <div className="onb-wait" role="status" aria-live="polite">
          <span className="skel skel-diag" />
          <span className="onb-wait-word">{t('onb.loading')}</span>
        </div>
      ) : (
        <p className="onb-diag">
          <span className={`badge s-${STATE_BADGE[diag.state]}`}>{t(`onb.state.${diag.state}`)}</span>
          {diagText}
        </p>
      )}

      {statusErr && (
        <div className="notice bad small">
          {fill(t('onb.statusUnreadable'), { detail: statusErr })}
        </div>
      )}

      {/* ---- subject: which identifier are we talking about ------------- */}
      <section className="onb-block">
        <h3>{t('onb.subject')}</h3>
        <div className="field row onb-pick">
          <select
            aria-label={t('onb.pickDeviceLabel')}
            value={matchesDevice ? String(device.id) : ''}
            onChange={(e) => {
              setSubject('')
              if (onSelect && e.target.value) onSelect(Number(e.target.value))
            }}
          >
            <option value="">{t('onb.pickDevice')}</option>
            {trucks.map(({ device: d }) => (
              <option key={d.id} value={d.id}>{d.name} · {d.uniqueId}</option>
            ))}
          </select>
          <input
            className="onb-imei"
            aria-label={t('onb.imeiLabel')}
            value={identifier}
            placeholder={t('onb.imeiPlaceholder')}
            onChange={(e) => { setSubject(e.target.value.trim()) }}
            spellCheck="false"
          />
        </div>
        {refused.length > 0 && (
          <p className="small muted">{t('onb.subjectHint')}</p>
        )}
      </section>

      {/* ---- the six hops ---------------------------------------------- */}
      <section className="onb-block">
        <h3>{t('onb.hops')}</h3>
        {!loaded ? (
          <ol className="hops-skel" aria-hidden="true">
            {[1, 2, 3, 4, 5, 6].map((n) => (
              <li key={n} className="hop-skel">
                <span className="skel skel-n" />
                <span className="skel skel-line" />
              </li>
            ))}
          </ol>
        ) : (
        <ol className="hops">
          {hops.map((h) => (
            <li key={h.key} className={`hop s-${h.state}`}>
              <span className="hop-n">{h.n}</span>
              <div className="hop-body">
                <div className="hop-top">
                  <strong>{t(`onb.hop.${h.key}`)}</strong>
                  <span className={`badge s-${STATE_BADGE[h.state]}`}>{t(`onb.state.${h.state}`)}</span>
                </div>
                <p className="hop-why">
                  {fill(t(`onb.${h.key}.${h.state}`), {
                    identifier: identifier || t('onb.hop.unknown'),
                    name: h.values.name,
                    source: h.values.source,
                    hostPort: h.values.hostPort,
                    containerPort: h.values.containerPort,
                  })}
                </p>
                {h.key === 'port' && <p className="hop-caveat">{t('onb.port.caveat')}</p>}
                {h.check && (
                  <p className="hop-check">
                    <span className="muted small">{t('onb.check')}</span>
                    <code>{h.check}</code>
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
        )}
      </section>

      {/* ---- what the server will do with an unknown identifier -------- */}
      <section className="onb-block">
        <h3>{t('onb.reg.title')}</h3>
        {!loaded ? (
          <p className="skel skel-block" aria-hidden="true" />
        ) : !reg || !reg.readable ? (
          <div className="notice small">
            {t('onb.reg.unreadable')}
          </div>
        ) : (
          <>
            <table className="grid onb-grid onb-reg">
              <tbody>
                <tr>
                  <th>{t('onb.reg.switch')}</th>
                  <td className={reg.registerUnknown ? 'on' : ''}>
                    {reg.registerUnknown ? t('onb.reg.on') : t('onb.reg.off')}
                  </td>
                </tr>
                <tr>
                  <th>{t('onb.reg.category')}</th>
                  <td>{reg.defaultCategory || t('onb.reg.none')}</td>
                </tr>
                <tr>
                  <th>{t('onb.reg.regex')}</th>
                  <td className="mono">{reg.regex || t('onb.reg.any')}</td>
                </tr>
              </tbody>
            </table>
            <p className="small muted">
              {reg.registerUnknown ? t('onb.reg.consequenceOn') : t('onb.reg.consequenceOff')}
            </p>
            {reg.regex && <p className="small warn">{t('onb.reg.regexCaveat')}</p>}
            {reg.allowRegistration && (
              <div className="notice bad small">{t('onb.reg.registrationOpen')}</div>
            )}
          </>
        )}
      </section>

      {/* ---- identifiers the server refused ---------------------------- */}
      <section className="onb-block">
        <h3>{t('onb.refused.title')}</h3>
        {!loaded ? (
          <p className="skel skel-block" aria-hidden="true" />
        ) : !status?.refused?.readable ? (
          <div className="notice small">{t('onb.refused.unreadable')}</div>
        ) : refused.length === 0 ? (
          <p className="small muted">{t('onb.refused.empty')}</p>
        ) : (
          <>
            <p className="small muted">{t('onb.refused.hint')}</p>
            <table className="grid onb-grid onb-refused">
              <thead>
                <tr>
                  <th>{t('onb.refused.identifier')}</th>
                  <th>{t('onb.refused.source')}</th>
                  <th>{t('onb.refused.at')}</th>
                  <th><span className="sr-only">{t('onb.refused.action')}</span></th>
                </tr>
              </thead>
              <tbody>
                {refused.map((r) => (
                  <tr key={r.identifier} className={r.identifier === identifier ? 'on' : ''}>
                    <td className="mono">{r.identifier}</td>
                    <td className="mono">{r.source || '—'}</td>
                    <td className="small muted">{r.at}</td>
                    <td>
                      <button className="btn tiny" onClick={() => setSubject(r.identifier)}>
                        {t('onb.refused.use')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="field row onb-adopt">
              <input
                value={adoptName}
                placeholder={t('onb.refused.namePlaceholder')}
                onChange={(e) => setAdoptName(e.target.value)}
              />
              <button
                className="btn primary"
                disabled={busy || !identifier || !adoptName.trim()}
                onClick={adopt}
              >
                {busy ? t('onb.refused.creating') : fill(t('onb.refused.create'), { identifier: identifier || '…' })}
              </button>
            </div>
            <p className="small muted">{t('onb.refused.nameHint')}</p>
          </>
        )}
        {note && <div className={`notice small ${note.kind === 'bad' ? 'bad' : ''}`}>{note.text}</div>}
      </section>

      {/* ---- the SMS the unit needs ------------------------------------ */}
      <section className="onb-block">
        <h3>{t('onb.sms.title')}</h3>
        <p className="small muted">{t('onb.sms.hint')}</p>

        <div className="onb-sms-form">
          <div className="field">
            <label htmlFor="onb-apn">{t('onb.sms.apn')}</label>
            <input id="onb-apn" value={apn} onChange={(e) => setApn(e.target.value)} placeholder="internet" spellCheck="false" />
          </div>
          <div className="field">
            <label htmlFor="onb-server">{t('onb.sms.server')}</label>
            <input id="onb-server" value={server} onChange={(e) => setServer(e.target.value)} placeholder="203.0.113.10" spellCheck="false" />
          </div>
          <div className="field">
            <label htmlFor="onb-port">{t('onb.sms.port')}</label>
            <input
              id="onb-port"
              value={port}
              inputMode="numeric"
              onChange={(e) => { setPortTouched(true); setPort(e.target.value) }}
            />
          </div>
          <div className="field">
            <label htmlFor="onb-acc">{t('onb.sms.acc')}</label>
            <input id="onb-acc" type="number" min={MIN_INTERVAL_SECONDS} value={accInt}
              onChange={(e) => setAccInt(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="onb-parked">{t('onb.sms.parked')}</label>
            <input id="onb-parked" type="number" min={MIN_INTERVAL_SECONDS} value={parkedInt}
              onChange={(e) => setParkedInt(e.target.value)} />
          </div>
        </div>

        {sms.problems.length > 0 ? (
          <div className="notice small">
            <ul className="onb-problems">
              {sms.problems.map((p, i) => <li key={`${p.key}-${i}`}>{t(`onb.sms.problem.${p.key}`)}</li>)}
            </ul>
          </div>
        ) : (
          <>
            <ol className="sms">
              {sms.commands.map((c) => (
                <li key={c.key}>
                  <code>{c.text}</code>
                  <span className="muted small">{t(`onb.sms.why.${c.key}`)}</span>
                </li>
              ))}
            </ol>
            <div className="onb-sms-foot">
              <button className="btn" onClick={copy}>
                {copied ? t('onb.sms.copied') : t('onb.sms.copy')}
              </button>
              <p className="small muted">{t('onb.sms.notes')}</p>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
