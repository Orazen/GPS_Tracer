import { useCallback, useEffect, useMemo, useState } from 'react'
import { ago, api } from '../api/traccar'
import { daysAgo, hhmm, isoDay, tacho } from '../api/tacho'
import { SectionGroup } from './Section'

/**
 * A tachograph panel: the reference's section row heading the content, instead
 * of a bare `h2` over the same box.
 *
 * The content surface keeps the `.panel` class rather than taking `.card`: the
 * findings screen is read through `.panel .kpi b`, and the coverage and result
 * panels are `.warnpanel` variants of it. Swapping in a second card class would
 * mean updating those selectors for no visual gain.
 */
function Panel({ icon, title, sub, end, warn = false, children }) {
  return (
    <SectionGroup
      icon={icon}
      title={title}
      sub={sub}
      end={end}
      card={`panel${warn ? ' warnpanel' : ''}`}
    >
      {children}
    </SectionGroup>
  )
}

/**
 * Tachograph screen.
 *
 * This sits in front of the tachograph service's API — imports, driver cards,
 * recorded activity, coverage and the EU driving-time engine. Five sub-tabs, in
 * the order an operator actually uses them: bring a card in, say who drives
 * what, look at what the cards say, ask the engine for findings, then check who
 * read what.
 *
 * Three things are shown on purpose and are not decoration:
 *
 *   1. **`validated_against_reference` is displayed wherever findings are.** The
 *      engine has never been reconciled against a trusted analysis report, so
 *      every figure on this screen is a computation over recorded data, not a
 *      legal finding. Hiding that in a doc would be a way of letting someone
 *      mistake it for one.
 *   2. **Coverage warnings and `rest_findings_reliable` are shown before the
 *      findings**, because a rest finding computed over days with no import is
 *      not trustworthy and the reader needs to know that first.
 *   3. **The audit tab is visible to everyone and refuses politely.** Hiding it
 *      from non-owners would make "was this read?" unanswerable; showing the
 *      refusal is the honest version.
 */
export default function Tacho({ t, lang, devices = [], showDriverName = false, onDevicesChanged }) {
  const [tab, setTab] = useState('imports')
  const [meta, setMeta] = useState(null)
  const [err, setErr] = useState(null)
  const [drivers, setDrivers] = useState([])

  useEffect(() => {
    let alive = true
    tacho
      .meta()
      .then((m) => alive && setMeta(m))
      .catch((e) => alive && setErr(String(e.message || e)))
    tacho
      .drivers()
      .then((d) => alive && setDrivers(d.driver_cards || []))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  return (
    <div className="pad tacho">
      <div className="ws-head">
        <h2 className="ws-title">{t('tacho')}</h2>
        {meta && (
          <span className="small muted mono">
            {meta.rules_version} · {meta.parser_version} · engine {meta.engine_version}
          </span>
        )}
      </div>

      {/* Not an error and not a warning: a permanent statement of scope. */}
      <p className="notice">
        <b>{t('tachoNotValidated')}</b> {meta?.validation_note || ''}
      </p>

      {err && <p className="err">{err}</p>}

      <nav className="subtabs">
        {[
          ['imports', t('tachoImports')],
          // The registry comes second because it is the same kind of work as the
          // first tab: establishing who and what this service is looking at,
          // before any figure is read off it.
          ['drivers', t('tachoDrivers')],
          ['activity', t('tachoActivity')],
          ['findings', t('tachoFindings')],
          ['audit', t('tachoAudit')],
        ].map(([key, label]) => (
          <button key={key} className={tab === key ? 'on' : ''} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </nav>

      {tab === 'imports' && <Imports t={t} lang={lang} />}
      {tab === 'drivers' && (
        <Drivers
          t={t}
          lang={lang}
          cards={drivers}
          devices={devices}
          showDriverName={showDriverName}
          onDevicesChanged={onDevicesChanged}
        />
      )}
      {tab === 'activity' && <Activity t={t} lang={lang} cards={drivers} />}
      {tab === 'findings' && <Findings t={t} lang={lang} cards={drivers} />}
      {tab === 'audit' && <Audit t={t} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Imports
// ---------------------------------------------------------------------------

function Imports({ t, lang }) {
  const [rows, setRows] = useState([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [msg, setMsg] = useState(null)
  const [openId, setOpenId] = useState(null)
  const [changes, setChanges] = useState(null)
  const [status, setStatus] = useState('')

  const load = useCallback(async () => {
    try {
      const d = await tacho.imports({ status: status || undefined, limit: 100 })
      setRows(d.imports || [])
    } catch (e) {
      setErr(String(e.message || e))
    }
  }, [status])

  useEffect(() => {
    load()
  }, [load])

  // The worker parses asynchronously, so a row sits at `pending` after upload.
  // Poll while anything is still in flight rather than leaving the operator to
  // guess when to refresh.
  useEffect(() => {
    if (!rows.some((r) => r.status === 'pending' || r.status === 'processing')) return
    const h = setTimeout(load, 2500)
    return () => clearTimeout(h)
  }, [rows, load])

  const upload = async (e) => {
    const input = e.target.elements.file
    const file = input.files?.[0]
    if (!file) return
    setBusy(true)
    setErr(null)
    setMsg(null)
    try {
      const out = await tacho.upload(file, e.target.elements.kind.value)
      setMsg(
        out.queued_for_parsing
          ? t('tachoQueued').replace('{n}', out.import_id)
          : t('tachoDuplicate').replace('{n}', out.duplicate_of ?? '?')
      )
      input.value = ''
      await load()
    } catch (e2) {
      setErr(String(e2.message || e2))
    } finally {
      setBusy(false)
    }
  }

  const showTimeline = async (id) => {
    setOpenId(id)
    setChanges(null)
    try {
      const d = await tacho.timeline(id)
      setChanges(d.changes || [])
    } catch (e) {
      setErr(String(e.message || e))
    }
  }

  return (
    <div className="sections tacho-body">
      <Panel icon="connect" title={t('tachoUpload')} sub={t('tachoUploadWhy')}>
        <form className="field row" onSubmit={(e) => { e.preventDefault(); upload(e) }}>
          <input type="file" name="file" aria-label={t('tachoImportFile')}
            accept=".ddd,.esm,application/octet-stream" required />
          <select name="kind" aria-label={t('tachoDocKind')} defaultValue="unknown">
            <option value="unknown">{t('tachoKindUnknown')}</option>
            <option value="driver_card">{t('tachoKindCard')}</option>
            <option value="vehicle_unit">{t('tachoKindVu')}</option>
          </select>
          <button className="btn primary" disabled={busy}>
            {busy ? t('tachoUploading') : t('tachoUploadBtn')}
          </button>
        </form>
        <p className="small muted">{t('tachoUploadHint')}</p>
        {msg && <p className="small ok">{msg}</p>}
        {err && <p className="err">{err}</p>}
      </Panel>

      <Panel
        icon="tacho"
        title={t('tachoImports')}
        end={(
          <div className="row">
            <select aria-label={t('tachoStatusFilter')} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t('tachoAllStatuses')}</option>
              {['pending', 'processing', 'done', 'rejected', 'failed'].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <span className="count">{rows.length}</span>
          </div>
        )}
      >

        {rows.length === 0 ? (
          <p className="muted small">{t('tachoNoImports')}</p>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>#</th>
                <th>{t('file')}</th>
                <th>{t('tachoKind')}</th>
                <th>{t('status')}</th>
                <th>{t('tachoHolder')}</th>
                <th>{t('tachoUploadedAt')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={openId === r.id ? 'on' : ''}>
                  <td className="mono">{r.id}</td>
                  <td className="mono">{r.original_filename}</td>
                  <td>{r.source_kind || r.declared_kind}</td>
                  <td>
                    <span className={`sev ${sevClass(r.status)}`}>{r.status}</span>
                    {r.attempts > 1 && <span className="muted small"> ×{r.attempts}</span>}
                  </td>
                  <td>
                    {r.holder_surname
                      ? `${r.holder_surname} ${r.holder_first_names || ''}`.trim()
                      : '—'}
                  </td>
                  <td className="muted small">{ago(r.uploaded_at, lang)}</td>
                  <td>
                    <button className="btn tiny" onClick={() => showTimeline(r.id)}>
                      {t('tachoView')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* Errors are the most useful field on a rejected import, so show them
            as text under the table rather than truncating them into a cell. */}
        {rows.some((r) => r.error_message) && (
          <ul className="rows compact">
            {rows
              .filter((r) => r.error_message)
              .map((r) => (
                <li key={r.id}>
                  <span className="sev sev-error">{r.error_code || 'error'}</span>
                  <span className="mono">#{r.id}</span> {r.error_message}
                </li>
              ))}
          </ul>
        )}
      </Panel>

      {openId != null && (
        <Panel
          icon="history"
          title={`${t('tachoChanges')} · #${openId}`}
          end={(
            <button className="btn tiny ghost" onClick={() => { setOpenId(null); setChanges(null) }}>
              {t('tachoClose')}
            </button>
          )}
        >
          {changes === null ? (
            <p className="muted small">{t('loading')}</p>
          ) : changes.length === 0 ? (
            <p className="muted small">{t('tachoNoChanges')}</p>
          ) : (
            <ul className="rows compact">
              {changes.slice(0, 400).map((c, i) => (
                <li key={i}>
                  <span className="mono">{c.day}</span>
                  <span className="mono">{padTime(c.minute_of_day)}</span>
                  <span className={`act act-${c.activity}`}>{c.activity_label}</span>
                  {c.crew != null && <span className="tag muted">crew {c.crew}</span>}
                  {c.card_not_inserted && (
                    <span className="tag muted">{t('tachoNoCard')}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {changes && changes.length > 400 && (
            <p className="small muted">
              {t('tachoTruncated').replace('{n}', changes.length)}
            </p>
          )}
        </Panel>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Activity
// ---------------------------------------------------------------------------

function Activity({ t, lang, cards }) {
  const [key, setKey] = useState('')
  const [from, setFrom] = useState(daysAgo(27))
  const [to, setTo] = useState(isoDay(new Date()))
  const [days, setDays] = useState([])
  const [coverage, setCoverage] = useState(null)
  const [summary, setSummary] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  // Default to the only card there is; a single-driver deployment should not need
  // a selection before it can see anything.
  useEffect(() => {
    if (!key && cards.length) setKey(`card:${cards[0].card_number}`)
  }, [cards, key])

  const load = useCallback(async () => {
    if (!key) return
    setBusy(true)
    setErr(null)
    try {
      const [d, c, s] = await Promise.all([
        tacho.days({ driverKey: key, dateFrom: from, dateTo: to }),
        tacho.coverage(key, from, to),
        tacho.dailySummary(key, from, to),
      ])
      setDays(d.days || [])
      setCoverage(c)
      setSummary(s)
    } catch (e) {
      setErr(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }, [key, from, to])

  useEffect(() => {
    load()
  }, [load])

  const totals = useMemo(() => {
    const acc = { driving: 0, work: 0, availability: 0, rest: 0, uncovered: 0, km: 0 }
    for (const d of days) {
      acc.driving += d.minutes_driving || 0
      acc.work += d.minutes_work || 0
      acc.availability += d.minutes_availability || 0
      acc.rest += d.minutes_rest || 0
      acc.uncovered += d.uncovered_minutes || 0
      acc.km += d.distance_km || 0
    }
    return acc
  }, [days])

  return (
    <div className="sections tacho-body">
      <Panel icon="clock" title={t('tachoPeriod')} sub={t('tachoPeriodWhy')}>
        <div className="field row wrap">
          <label className="inline">
            {t('tachoDriver')}
            <select value={key} onChange={(e) => setKey(e.target.value)}>
              {cards.length === 0 && <option value="">{t('tachoNoCards')}</option>}
              {cards.map((c) => (
                <option key={c.card_number} value={`card:${c.card_number}`}>
                  {c.holder_surname} {c.holder_first_names} · {c.card_number}
                </option>
              ))}
            </select>
          </label>
          <label className="inline">
            {t('from')}
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="inline">
            {t('to')}
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </label>
          <button className="btn" onClick={load} disabled={busy || !key}>
            {busy ? t('loading') : t('generate')}
          </button>
          {key && (
            <a className="btn" href={tacho.activityCsvUrl(key, from, to)} download>
              {t('tachoExportCsv')}
            </a>
          )}
        </div>
        {err && <p className="err">{err}</p>}
      </Panel>

      {coverage && (
        <Panel
          icon="tacho"
          title={t('tachoCoverage')}
          sub={t('tachoCoverageWhy')}
          warn={!coverage.rest_findings_reliable}
          end={(
            <span className="count">
              {coverage.days_with_a_record}/{coverage.total_days} ·{' '}
              {Math.round((coverage.coverage_ratio || 0) * 100)}%
            </span>
          )}
        >

          <div className="kpis">
            <Kpi label={t('tachoDaysWith')} value={coverage.days_with_a_record} />
            <Kpi label={t('tachoDaysMissing')} value={coverage.days_missing.length} />
            <Kpi label={t('tachoDaysIncomplete')} value={coverage.days_incomplete.length} />
            <Kpi
              label={t('tachoRestReliable')}
              value={coverage.rest_findings_reliable ? '✓' : '✗'}
            />
          </div>

          {coverage.warnings.map((w, i) => (
            <p key={i} className="warn small">
              {w}
            </p>
          ))}
          {!coverage.rest_findings_reliable && (
            <p className="small muted">{t('tachoRestWarning')}</p>
          )}
        </Panel>
      )}

      <Panel icon="reports" title={t('tachoRecorded')} end={<span className="count">{days.length}</span>}>

        <div className="kpis">
          <Kpi label={t('tachoDriving')} value={hhmm(totals.driving)} />
          <Kpi label={t('tachoWork')} value={hhmm(totals.work)} />
          <Kpi label={t('tachoAvailability')} value={hhmm(totals.availability)} />
          <Kpi label={t('tachoRest')} value={hhmm(totals.rest)} />
          <Kpi label={t('tachoUncovered')} value={hhmm(totals.uncovered)} />
          <Kpi label={t('km')} value={Math.round(totals.km)} />
        </div>

        {days.length === 0 ? (
          <p className="muted small">{t('noData')}</p>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>{t('tachoDay')}</th>
                <th>{t('tachoDriving')}</th>
                <th>{t('tachoWork')}</th>
                <th>{t('tachoAvailability')}</th>
                <th>{t('tachoRest')}</th>
                <th>{t('tachoUncovered')}</th>
                <th>{t('km')}</th>
                <th>#</th>
              </tr>
            </thead>
            <tbody>
              {days.map((d) => (
                <tr key={d.id}>
                  <td className="mono">{d.day}</td>
                  <td>{hhmm(d.minutes_driving)}</td>
                  <td>{hhmm(d.minutes_work)}</td>
                  <td>{hhmm(d.minutes_availability)}</td>
                  <td>{hhmm(d.minutes_rest)}</td>
                  <td className={d.uncovered_minutes ? 'warn' : ''}>
                    {hhmm(d.uncovered_minutes)}
                  </td>
                  <td>{d.distance_km ?? '—'}</td>
                  <td className="mono muted">{d.import_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {days.some((d) => d.open_ended || (d.warnings || []).length > 0) && (
          <ul className="rows compact">
            {days
              .filter((d) => (d.warnings || []).length > 0)
              .map((d) => (
                <li key={d.id}>
                  <span className="mono">{d.day}</span>
                  <span className="warn small">{d.warnings.join(' · ')}</span>
                </li>
              ))}
          </ul>
        )}
      </Panel>

      {summary && Object.keys(summary.by_week).length > 0 && (
        <Panel
          icon="tacho"
          title={t('tachoByWeek')}
          end={<span className="count">{t('tachoWeekStartsMon')}</span>}
        >
          <table className="grid">
            <thead>
              <tr>
                <th>{t('tachoWeek')}</th>
                <th>{t('tachoDriving')}</th>
                <th>{t('tachoWork')}</th>
                <th>{t('tachoRest')}</th>
                <th>{t('tachoUncovered')}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(summary.by_week).map(([week, v]) => (
                <tr key={week}>
                  <td className="mono">{week}</td>
                  <td>{hhmm(v.driving)}</td>
                  <td>{hhmm(v.work)}</td>
                  <td>{hhmm(v.rest)}</td>
                  <td>{hhmm(v.uncovered)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted">{summary.note}</p>
        </Panel>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Drivers: the registry, the assignment, and the history
// ---------------------------------------------------------------------------

/**
 * Who is driving which truck.
 *
 * Two systems hold half of this each, and the screen refuses to pretend
 * otherwise:
 *
 *   * the **tachograph registry** holds the person, their card link and the
 *     assignment history. It is the record, it is dated, and it is never
 *     deleted -- a closed assignment is what answers "who was in that truck last
 *     month". Every call here is audited by the service with the forwarded
 *     actor, and refused to a `viewer`.
 *   * **Traccar** holds the truck and the attribute the fleet screen reads. An
 *     assignment is mirrored into that attribute so the roster, the panel and
 *     the alerts agree with the registry instead of showing nothing.
 *
 * The mirror is the only part that can fail on its own, and when it does the
 * screen says so: "recorded, but the tracker console still shows the old value"
 * is a different, and much less dangerous, statement than a green tick over a
 * half-completed action.
 *
 * `vehicle_ref` is the tracker's **uniqueId**, not its name. A truck renamed in
 * the console must not detach from its own history, and the identifier is the
 * only stable handle on it; the name is resolved for display at render time.
 */
function Drivers({ t, lang, cards, devices, showDriverName, onDevicesChanged }) {
  const [people, setPeople] = useState([])
  const [state, setState] = useState('loading')
  const [history, setHistory] = useState(null)
  const [selected, setSelected] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [note, setNote] = useState(null)
  const [form, setForm] = useState({ name: '', ref: '', card: '' })
  const [target, setTarget] = useState({})

  const load = useCallback(async () => {
    try {
      const d = await tacho.people()
      setPeople(d.people || [])
      setState('ok')
    } catch (e) {
      // 403 is not a failure: it is the service refusing a role, and the screen
      // says which role rather than showing a stack trace.
      setState(e.forbidden ? 'forbidden' : 'error')
      if (!e.forbidden) setErr(String(e.message || e))
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const trucks = useMemo(() => {
    // Two trucks with the same uniqueId are impossible; two with the same name
    // are not, which is the other reason the ref is the identifier here.
    const seen = new Set()
    return (devices || [])
      .filter((d) => d.uniqueId && !seen.has(d.uniqueId) && seen.add(d.uniqueId))
      .map((d) => ({ ref: d.uniqueId, name: d.name, id: d.id, driver: d.attributes?.driverDriverId || null }))
  }, [devices])

  const nameOf = (ref) => trucks.find((x) => x.ref === ref)?.name || ref

  const openHistory = useCallback(async (driverId) => {
    setSelected(driverId)
    setHistory(null)
    try {
      const d = await tacho.vehicleAssignments({ driverId })
      setHistory(d.vehicle_assignments || [])
    } catch (e) {
      setErr(String(e.message || e))
    }
  }, [])

  const register = async (e) => {
    e.preventDefault()
    if (!form.name.trim()) return
    setBusy(true)
    setErr(null)
    setNote(null)
    try {
      const person = await tacho.createPerson({
        displayName: form.name,
        externalRef: form.ref,
        cardNumber: form.card || undefined,
      })
      setForm({ name: '', ref: '', card: '' })
      await load()
      setNote({ good: true, text: `${t('tachoPersonAdded')}: ${person.display_name}` })
    } catch (e) {
      setErr(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  /** Write the assignment to the registry, then mirror it into the tracker. */
  const assign = async (person) => {
    const ref = target[person.id]
    if (!ref) return
    setBusy(true)
    setErr(null)
    setNote(null)
    try {
      await tacho.assignVehicle({ driverId: person.id, vehicleRef: ref })
      const truck = trucks.find((x) => x.ref === ref)
      let mirror = null
      if (!truck) {
        mirror = t('tachoMirrorNoTruck')
      } else {
        try {
          await api.setDriver(truck.id, person.display_name)
        } catch (e) {
          mirror = String(e.message || e)
        }
      }
      await load()
      if (selected === person.id) await openHistory(person.id)
      if (!mirror) onDevicesChanged?.()
      setNote(
        mirror
          ? { good: false, text: `${t('tachoMirrorFailed')} ${mirror}` }
          : { good: true, text: `${t('tachoAssigned')}: ${person.display_name} → ${nameOf(ref)}` }
      )
    } catch (e) {
      setErr(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  const close = async (row) => {
    setBusy(true)
    setErr(null)
    setNote(null)
    try {
      await tacho.closeAssignment(row.id)
      // Update the mirror too, but ONLY if the tracker still holds this driver's
      // own name: it may have been changed to a co-driver since, and overwriting
      // it blindly would delete somebody else's assignment from the console.
      //
      // The replacement is the next driver still open on that truck, not nothing.
      // A truck can legitimately hold two (Art 8(5) multi-manning), so ending
      // one driver's assignment must not blank the name of the other one who is
      // still in it -- the mirror holds one value while the registry holds two.
      const truck = trucks.find((x) => x.ref === row.vehicle_ref)
      const name = people.find((p) => p.id === row.driver_id)?.display_name
      let mirror = null
      if (truck && name && truck.driver === name) {
        const stillIn = people.find(
          (p) => p.active && p.vehicle_ref === row.vehicle_ref && p.id !== row.driver_id
        )
        try {
          await api.setDriver(truck.id, stillIn ? stillIn.display_name : null)
        } catch (e) {
          mirror = String(e.message || e)
        }
      }
      await load()
      if (selected === row.driver_id) await openHistory(row.driver_id)
      if (!mirror) onDevicesChanged?.()
      setNote(
        mirror
          ? { good: false, text: `${t('tachoMirrorFailed')} ${mirror}` }
          : { good: true, text: t('tachoAssignmentClosed') }
      )
    } catch (e) {
      setErr(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  const toggleActive = async (person) => {
    setBusy(true)
    setErr(null)
    try {
      await tacho.setPersonActive(person.id, !person.active)
      await load()
    } catch (e) {
      setErr(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  if (state === 'loading') return <p className="muted small pad-s">{t('loading')}</p>
  if (state === 'forbidden') return <p className="warn">{t('tachoDriversForbidden')}</p>
  if (state === 'error') return <p className="err">{t('serverError')}</p>

  return (
    <div className="sections tacho-body">
      {!showDriverName && <p className="warn small">{t('tachoDriverSwitchOff')}</p>}
      {err && <p className="err small">{err}</p>}
      {note && <p className={note.good ? 'ok small' : 'err small'}>{note.text}</p>}

      <Panel
        icon="truck"
        title={t('tachoRegistry')}
        sub={t('tachoRegistryWhy')}
        end={<span className="count">{people.length}</span>}
      >
        <form className="field row wrap" onSubmit={register}>
          <label className="inline">
            {t('tachoName')}
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              maxLength={120}
              required
            />
          </label>
          <label className="inline">
            {t('tachoExternalRef')}
            <input
              value={form.ref}
              onChange={(e) => setForm({ ...form, ref: e.target.value })}
              maxLength={120}
            />
          </label>
          <label className="inline">
            {t('tachoCard')}
            <select value={form.card} onChange={(e) => setForm({ ...form, card: e.target.value })}>
              <option value="">{t('tachoNoCardLink')}</option>
              {cards.map((c) => (
                <option key={c.card_number} value={c.card_number}>
                  {c.holder_surname} {c.holder_first_names} · {c.card_number}
                </option>
              ))}
            </select>
          </label>
          <button className="btn primary" disabled={busy || !form.name.trim()}>
            {t('tachoAddPerson')}
          </button>
        </form>

        {people.length === 0 ? (
          <p className="muted small">{t('tachoNoPeople')}</p>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>{t('tachoName')}</th>
                <th>{t('tachoExternalRef')}</th>
                <th>{t('tachoCard')}</th>
                <th>{t('tachoVehicle')}</th>
                <th>{t('tachoAssignTo')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {people.map((p) => (
                <tr key={p.id} className={selected === p.id ? 'on' : ''}>
                  <td>
                    <button className="btn tiny ghost" onClick={() => openHistory(p.id)}>
                      {p.display_name}
                    </button>
                    {!p.active && <span className="muted small"> · {t('tachoInactive')}</span>}
                  </td>
                  <td className="small muted">{p.external_ref || '—'}</td>
                  <td className="small muted mono">{p.card_number || t('tachoNoCardLink')}</td>
                  <td className="small">
                    {p.vehicle_ref ? nameOf(p.vehicle_ref) : <span className="muted">{t('noDriver')}</span>}
                  </td>
                  <td>
                    <select
                      aria-label={t('tachoAssignTo')}
                      value={target[p.id] || ''}
                      onChange={(e) => setTarget({ ...target, [p.id]: e.target.value })}
                    >
                      <option value="">{t('tachoPickVehicle')}</option>
                      {trucks.map((v) => (
                        <option key={v.ref} value={v.ref}>
                          {v.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <button
                      className="btn tiny"
                      disabled={busy || !target[p.id]}
                      onClick={() => assign(p)}
                    >
                      {t('tachoAssign')}
                    </button>
                    {p.assignment_id && (
                      <button
                        className="btn tiny ghost"
                        disabled={busy}
                        onClick={() =>
                          close({
                            id: p.assignment_id,
                            driver_id: p.id,
                            vehicle_ref: p.vehicle_ref,
                          })
                        }
                      >
                        {t('tachoEndAssignment')}
                      </button>
                    )}
                    <button className="btn tiny ghost" disabled={busy} onClick={() => toggleActive(p)}>
                      {p.active ? t('tachoDeactivate') : t('tachoReactivate')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="small muted">{t('tachoRegistryFoot')}</p>
      </Panel>

      <Panel
        icon="clock"
        title={t('tachoHistory')}
        sub={t('tachoHistoryWhy')}
        end={selected ? <span className="count">{history?.length ?? 0}</span> : null}
      >
        {!selected && <p className="muted small">{t('tachoPickDriverForHistory')}</p>}
        {selected && history === null && <p className="muted small">{t('loading')}</p>}
        {selected && history && history.length === 0 && (
          <p className="muted small">{t('tachoNoAssignments')}</p>
        )}
        {selected && history && history.length > 0 && (
          <table className="grid">
            <thead>
              <tr>
                <th>{t('tachoVehicle')}</th>
                <th>{t('from')}</th>
                <th>{t('to')}</th>
                <th>{t('tachoNote')}</th>
              </tr>
            </thead>
            <tbody>
              {history.map((a) => (
                <tr key={a.id}>
                  <td>{nameOf(a.vehicle_ref)}</td>
                  <td className="small">{a.assigned_from}</td>
                  <td className="small">
                    {a.assigned_to || <span className="ok">{t('tachoOpen')}</span>}
                  </td>
                  <td className="small muted">{a.note || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Findings
// ---------------------------------------------------------------------------

function Findings({ t, lang, cards }) {
  const [key, setKey] = useState('')
  const [from, setFrom] = useState(daysAgo(13))
  const [to, setTo] = useState(isoDay(new Date()))
  const [age, setAge] = useState(1)
  const [result, setResult] = useState(null)
  const [history, setHistory] = useState([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    if (!key && cards.length) setKey(`card:${cards[0].card_number}`)
  }, [cards, key])

  const loadHistory = useCallback(async () => {
    try {
      const d = await tacho.calculations(key || undefined, 25)
      setHistory(d.calculations || [])
    } catch {
      /* history is secondary; a failure here must not hide the run form */
    }
  }, [key])

  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  const run = async () => {
    setBusy(true)
    setErr(null)
    try {
      setResult(await tacho.calculate(key, from, to, Number(age)))
      await loadHistory()
    } catch (e) {
      setErr(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  const breaches = (result?.findings || []).filter((f) => f.severity === 'breach')

  return (
    <div className="sections tacho-body">
      <Panel icon="tacho" title={t('tachoRun')} sub={t('tachoRunWhy')}>
        <div className="field row wrap">
          <label className="inline">
            {t('tachoDriver')}
            <select value={key} onChange={(e) => setKey(e.target.value)}>
              {cards.length === 0 && <option value="">{t('tachoNoCards')}</option>}
              {cards.map((c) => (
                <option key={c.card_number} value={`card:${c.card_number}`}>
                  {c.holder_surname} {c.holder_first_names} · {c.card_number}
                </option>
              ))}
            </select>
          </label>
          <label className="inline">
            {t('from')}
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="inline">
            {t('to')}
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </label>
          <label className="inline">
            {t('tachoDataAge')}
            <input
              type="number"
              min="0"
              value={age}
              onChange={(e) => setAge(e.target.value)}
            />
          </label>
          <button className="btn primary" onClick={run} disabled={busy || !key}>
            {busy ? t('loading') : t('tachoCalculate')}
          </button>
        </div>
        <p className="small muted">{t('tachoDataAgeHint')}</p>
        {err && <p className="err">{err}</p>}
      </Panel>

      {result && (
        <>
          <Panel
            icon="tacho"
            title={t('tachoResult')}
            warn={breaches.length > 0}
            end={(
              <span className="count">
                {result.rules_version} · #{result.calculation_id}
              </span>
            )}
          >

            <div className="kpis">
              <Kpi label={t('status')} value={result.status} />
              <Kpi label={t('tachoBreaches')} value={breaches.length} />
              <Kpi label={t('tachoFindings')} value={result.findings.length} />
              <Kpi
                label={t('tachoValidated')}
                value={result.validated_against_reference ? '✓' : '✗'}
              />
            </div>

            <p className="notice small">{result.validation_note}</p>

            {result.warnings.map((w, i) => (
              <p key={i} className="warn small">
                {w}
              </p>
            ))}

            <p className="small muted">
              {t('tachoSourceDays')}: {result.source_days.length}
              {result.missing_days.length > 0 && (
                <>
                  {' · '}
                  {t('tachoMissing')}: {result.missing_days.join(', ')}
                </>
              )}
            </p>
          </Panel>

          <Panel
            icon="reports"
            title={t('tachoFindings')}
            end={<span className="count">{result.findings.length}</span>}
          >
            {result.findings.length === 0 ? (
              <p className="muted small">{t('tachoNoFindings')}</p>
            ) : (
              <ul className="rows">
                {result.findings.map((f, i) => (
                  <li key={i} className={f.severity === 'breach' ? 'sevli-breach' : ''}>
                    <div className="atop">
                      <span className={`sev ${sevClass(f.severity)}`}>{f.severity}</span>
                      <span className="mono muted">{f.code}</span>
                      {f.day && <span className="mono muted">{f.day}</span>}
                    </div>
                    <p className="finding-msg">{f.message}</p>
                    <div className="small muted">
                      {f.article}
                      {f.limit_minutes != null && (
                        <>
                          {' · '}
                          {t('tachoLimit')} {hhmm(f.limit_minutes)}
                        </>
                      )}
                      {f.actual_minutes != null && (
                        <>
                          {' · '}
                          {t('tachoActual')} {hhmm(f.actual_minutes)}
                        </>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          {/* Every assumption the engine made, verbatim. A figure you cannot
              explain later is worse than no figure, so these are always visible. */}
          <Panel icon="tacho" title={t('tachoAssumptions')}>
            <ul className="rows compact">
              {result.assumptions.map((a, i) => (
                <li key={i}>
                  <span className="small">{a}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </>
      )}

      <Panel
        icon="history"
        title={t('tachoPastRuns')}
        end={<span className="count">{history.length}</span>}
      >
        {history.length === 0 ? (
          <p className="muted small">{t('tachoNoRuns')}</p>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>#</th>
                <th>{t('tachoPeriod')}</th>
                <th>{t('status')}</th>
                <th>{t('tachoRules')}</th>
                <th>{t('tachoWhen')}</th>
              </tr>
            </thead>
            <tbody>
              {history.map((c) => (
                <tr key={c.id}>
                  <td className="mono">{c.id}</td>
                  <td className="mono">
                    {c.period_start} → {c.period_end}
                  </td>
                  <td>
                    <span className={`sev ${sevClass(c.status)}`}>{c.status}</span>
                  </td>
                  <td className="mono muted">{c.rules_version}</td>
                  <td className="muted small">{ago(c.computed_at, lang)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------

function Audit({ t }) {
  const [entries, setEntries] = useState([])
  const [state, setState] = useState('loading')

  useEffect(() => {
    let alive = true
    tacho
      .audit(200)
      .then((d) => {
        if (!alive) return
        setEntries(d.entries || [])
        setState('ok')
      })
      .catch((e) => {
        if (!alive) return
        // 403 is not a failure: it is the service correctly refusing a role.
        setState(e.forbidden ? 'forbidden' : 'error')
      })
    return () => {
      alive = false
    }
  }, [])

  return (
    <Panel
      icon="settings"
      title={t('tachoAudit')}
      sub={t('tachoAuditWhy')}
      end={state === 'ok' ? <span className="count">{entries.length}</span> : null}
    >

      {state === 'loading' && <p className="muted small">{t('loading')}</p>}
      {state === 'forbidden' && <p className="warn">{t('tachoAuditOwnerOnly')}</p>}
      {state === 'error' && <p className="err">{t('serverError')}</p>}

      {state === 'ok' &&
        (entries.length === 0 ? (
          <p className="muted small">{t('tachoNoAudit')}</p>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>{t('tachoWhen')}</th>
                <th>{t('tachoActor')}</th>
                <th>{t('tachoRole')}</th>
                <th>{t('tachoAction')}</th>
                <th>{t('tachoSubject')}</th>
                <th>IP</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td className="mono small">
                    {new Date(e.at).toLocaleString('en-GB', { hour12: false })}
                  </td>
                  <td>{e.actor}</td>
                  <td className="mono muted">{e.actor_role}</td>
                  <td className="mono">{e.action}</td>
                  <td className="mono muted">
                    {e.subject_type}
                    {e.subject_id ? ` #${e.subject_id}` : ''}
                  </td>
                  <td className="mono muted">{e.source_ip || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Bits
// ---------------------------------------------------------------------------

function Kpi({ label, value }) {
  return (
    <div className="kpi">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  )
}

/** Severity/status -> CSS modifier. Kept in one place so colours stay consistent. */
function sevClass(value) {
  switch (value) {
    case 'breach':
    case 'failed':
    case 'rejected':
    case 'error':
      return 'sev-breach'
    case 'unknown':
    case 'stale':
    case 'insufficient_data':
    case 'not_applicable':
    case 'processing':
      return 'sev-unknown'
    case 'ok':
    case 'done':
      return 'sev-ok'
    default:
      return 'sev-muted'
  }
}

/** 0 -> 00:00, 90 -> 01:30. `minute_of_day` arrives as a plain integer. */
function padTime(minute) {
  if (minute == null) return '--:--'
  const h = Math.floor(minute / 60)
  const m = minute % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}
