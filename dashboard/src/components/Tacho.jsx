import { useCallback, useEffect, useMemo, useState } from 'react'
import { ago } from '../api/traccar'
import { daysAgo, hhmm, isoDay, tacho } from '../api/tacho'

/**
 * Tachograph screen.
 *
 * This sits in front of the tachograph service's API — imports, driver cards,
 * recorded activity, coverage and the EU driving-time engine. Four sub-tabs, in
 * the order an operator actually uses them: bring a card in, look at what it
 * says, ask the engine for findings, then check who read what.
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
export default function Tacho({ t, lang }) {
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
      <div className="tacho-head">
        <h2>{t('tacho')}</h2>
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
    <div className="tacho-body">
      <section className="panel">
        <header className="phead">
          <h2>{t('tachoUpload')}</h2>
        </header>
        <form className="field row" onSubmit={(e) => { e.preventDefault(); upload(e) }}>
          <input type="file" name="file" accept=".ddd,.esm,application/octet-stream" required />
          <select name="kind" defaultValue="unknown">
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
      </section>

      <section className="panel">
        <header className="phead">
          <h2>{t('tachoImports')}</h2>
          <div className="row">
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t('tachoAllStatuses')}</option>
              {['pending', 'processing', 'done', 'rejected', 'failed'].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <span className="count">{rows.length}</span>
          </div>
        </header>

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
      </section>

      {openId != null && (
        <section className="panel">
          <header className="phead">
            <h2>
              {t('tachoChanges')} · #{openId}
            </h2>
            <button className="btn tiny ghost" onClick={() => { setOpenId(null); setChanges(null) }}>
              {t('tachoClose')}
            </button>
          </header>
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
        </section>
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
    <div className="tacho-body">
      <section className="panel">
        <header className="phead">
          <h2>{t('tachoPeriod')}</h2>
        </header>
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
      </section>

      {coverage && (
        <section className={`panel ${coverage.rest_findings_reliable ? '' : 'warnpanel'}`}>
          <header className="phead">
            <h2>{t('tachoCoverage')}</h2>
            <span className="count">
              {coverage.days_with_a_record}/{coverage.total_days} ·{' '}
              {Math.round((coverage.coverage_ratio || 0) * 100)}%
            </span>
          </header>

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
        </section>
      )}

      <section className="panel">
        <header className="phead">
          <h2>{t('tachoRecorded')}</h2>
          <span className="count">{days.length}</span>
        </header>

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
      </section>

      {summary && Object.keys(summary.by_week).length > 0 && (
        <section className="panel">
          <header className="phead">
            <h2>{t('tachoByWeek')}</h2>
            <span className="count">{t('tachoWeekStartsMon')}</span>
          </header>
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
        </section>
      )}
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
    <div className="tacho-body">
      <section className="panel">
        <header className="phead">
          <h2>{t('tachoRun')}</h2>
        </header>
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
      </section>

      {result && (
        <>
          <section className={`panel ${breaches.length ? 'warnpanel' : ''}`}>
            <header className="phead">
              <h2>{t('tachoResult')}</h2>
              <span className="count">
                {result.rules_version} · #{result.calculation_id}
              </span>
            </header>

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
          </section>

          <section className="panel">
            <header className="phead">
              <h2>{t('tachoFindings')}</h2>
              <span className="count">{result.findings.length}</span>
            </header>
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
          </section>

          <section className="panel">
            <header className="phead">
              <h2>{t('tachoAssumptions')}</h2>
            </header>
            {/* Every assumption the engine made, verbatim. A figure you cannot
                explain later is worse than no figure, so these are always visible. */}
            <ul className="rows compact">
              {result.assumptions.map((a, i) => (
                <li key={i}>
                  <span className="small">{a}</span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}

      <section className="panel">
        <header className="phead">
          <h2>{t('tachoPastRuns')}</h2>
          <span className="count">{history.length}</span>
        </header>
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
      </section>
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
    <section className="panel">
      <header className="phead">
        <h2>{t('tachoAudit')}</h2>
        {state === 'ok' && <span className="count">{entries.length}</span>}
      </header>

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
    </section>
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
