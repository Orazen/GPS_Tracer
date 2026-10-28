/**
 * End-to-end check of every dashboard screen, in a real browser.
 *
 * Run against the DEPLOYED dashboard, not the Vite dev server:
 *
 *     cd dashboard && npm run build && node server.mjs      # terminal 1
 *     cd dashboard && npm run verify                        # terminal 2
 *
 * That matters. The dev server proxies to `server.mjs`, which is the only place
 * the tachograph service token exists — so verifying through the dev server
 * verifies the same server code the container runs. Verifying against a preview
 * of `dist/` would not.
 *
 * Two lessons are baked in from earlier attempts:
 *
 *   1. **Headless tabs throttle requestAnimationFrame**, and MapLibre renders
 *      from rAF. So the script asserts rAF actually advances before it believes
 *      anything about the map, rather than reporting a dead rAF as "the map is
 *      broken".
 *   2. **A rendered heading is not a working screen.** Traccar's report endpoints
 *      answer HTTP 200 with an empty array when a query parameter is wrong, so
 *      every data screen is asserted on ROW COUNTS and real numbers, not on
 *      whether it mounted.
 *
 * Requires a seeded deployment. Seed a fleet with:
 *     docker compose --profile tools run --rm simulator
 * and a driver card through the tachograph tab (or the API).
 */

import { chromium } from 'playwright'
import { mkdirSync, readFileSync } from 'node:fs'

const URL = process.env.DASHBOARD_URL || 'http://127.0.0.1:8083/'
const EMAIL = process.env.VERIFY_EMAIL || 'admin@gpstracer.local'
const PASSWORD = process.env.VERIFY_PASSWORD || 'Gpstrack2026!'
const OUT = process.env.VERIFY_SHOTS || 'shots'

mkdirSync(OUT, { recursive: true })

let failures = 0
const fail = (m) => { failures++; console.error('  FAIL: ' + m) }
const ok = (m) => console.log('  ok: ' + m)
const step = (m) => console.log('\n=== ' + m + ' ===')

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1680, height: 980 } })

const errors = []
const bad = []
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message))
page.on('response', (r) => { if (r.status() >= 400) bad.push(`${r.status()} ${r.url()}`) })
page.on('requestfailed', (r) => {
  const err = r.failure()?.errorText ?? ''
  if (err.includes('ERR_ABORTED')) return    // MapLibre cancels tiles on zoom
  bad.push(`FAILED ${r.url()} ${err}`)
})

// ---------------------------------------------------------------------------
step('1. boot + login')
await page.goto(URL, { waitUntil: 'domcontentloaded' })

const raf = await page.evaluate(() => new Promise((res) => {
  let n = 0
  const t = () => { n++; n < 10 ? requestAnimationFrame(t) : res(n) }
  requestAnimationFrame(t)
  setTimeout(() => res(n), 2000)
}))
raf >= 5 ? ok(`requestAnimationFrame runs (${raf} frames)`) : fail('rAF dead — the map cannot render')

if (await page.locator('.login').count()) {
  const i = page.locator('.login input')
  await i.nth(0).fill(EMAIL)
  await i.nth(1).fill(PASSWORD)
  await page.locator('.login form button').first().click()
}
await page.waitForSelector('.app', { timeout: 20000 })
ok('logged in, dashboard shell up')

// Navigation is two levels: eight section buttons, and the screens inside the
// active section. Sections are always listed, so counting them is cheap.
const sectionNames = await page.locator('.sidenav__item').evaluateAll(
  (els) => els.map((el) => (el.textContent || '').trim())
)
// The language switch lives at the foot of the sidenav: two buttons, IT and EN.
const navCtl = await page.locator('.sidenav .lang button').count()
console.log('  sections: ' + sectionNames.join(' | '))
console.log('  language controls: ' + navCtl)
navCtl === 2 ? ok('the navigation foot holds the 2 language controls') : fail(`expected 2 language controls, got ${navCtl}`)
// Eight sections for an administrator. Connect a tracker is administrator-only and
// sits inside Alerts & Administration, so it is counted through its section.
sectionNames.length === 8 ? ok('all 8 sections present') : fail(`expected 8 sections, got ${sectionNames.length}`)
sectionNames.every((t) => t.trim()) ? ok('every section carries its name for a screen reader') : fail('a section has no accessible name')

const screenButton = (label) =>
  page.locator('.sidenav__sub-item').filter({ hasText: new RegExp('^\\s*' + label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*$') })

/** Open the section that holds the named screen, then press the screen. */
const navTo = async (label) => {
  const count = await page.locator('.sidenav__item').count()
  for (let i = 0; i < count; i++) {
    if (await screenButton(label).count() === 0) {
      await page.locator('.sidenav__item').nth(i).click()
      await page.waitForTimeout(250)
    }
    if (await screenButton(label).count()) {
      await screenButton(label).first().click()
      await page.waitForTimeout(1200)
      return
    }
  }
  throw new Error(`no screen named ${label}`)
}
const go = navTo
/** Press a screen by any of several language-specific names. */
const goAny = async (names) => {
  let last
  for (const n of names) {
    try { return await navTo(n) } catch (err) { last = err }
  }
  throw last || new Error(`no screen named ${names.join(' / ')}`)
}

// ---------------------------------------------------------------------------
step('2. fleet map')
await goAny(['Parco mezzi', 'Fleet'])
try {
  await page.waitForSelector('.mapwait', { state: 'detached', timeout: 20000 })
  ok('map ready')
} catch { fail('map never became ready') }
await page.waitForTimeout(3500)

const m = await page.evaluate(() => {
  const els = [...document.querySelectorAll('.marker')]
  const xs = els.map((e) => e.getBoundingClientRect().x)
  return {
    markers: els.length,
    roster: document.querySelectorAll('.unitcard').length,
    spread: xs.length ? Math.round(Math.max(...xs) - Math.min(...xs)) : 0,
    statusbar: document.querySelector('.pane__stats')?.innerText.replace(/\n/g, ' '),
    panel: document.querySelector('.panel h2')?.textContent,
    alerts: document.querySelectorAll('.alist li').length,
  }
})
console.log('  ' + JSON.stringify(m))
m.markers > 0 ? ok(`${m.markers} markers on map`) : fail('no markers')
m.roster > 0 ? ok(`${m.roster} vehicles in roster`) : fail('empty roster')
m.spread > 150 ? ok(`markers spread ${m.spread}px — usefully zoomed`) : fail(`markers ${m.spread}px apart — zoomed out too far`)
await page.screenshot({ path: `${OUT}/01-fleet.png` })

// ---------------------------------------------------------------------------
step('3. trail history')
await goAny(['Cronologia', 'History'])
await page.waitForFunction(
  () => !/^—/.test(document.querySelector('.kpi b')?.textContent || '—'),
  null, { timeout: 30000 }
).catch(() => fail('history KPIs never populated'))
await page.waitForTimeout(600)

const hist = await page.evaluate(() => ({
  presets: [...document.querySelectorAll('.hist-presets .chip')].map((b) => b.textContent),
  kpis: [...document.querySelectorAll('.kpi')].map((k) => k.innerText.replace(/\n/g, ' ')),
  subtabs: [...document.querySelectorAll('.subtabs button')].map((b) => b.textContent),
  rows: document.querySelectorAll('.rows li').length,
  mapReady: !document.querySelector('.mapwait'),
}))
console.log('  ' + JSON.stringify(hist))
hist.presets.length >= 4 ? ok(`presets: ${hist.presets.join(', ')}`) : fail('date presets missing')
hist.kpis.length >= 4 ? ok(`KPIs: ${hist.kpis.join(' | ')}`) : fail('KPIs missing')
hist.mapReady ? ok('history map ready') : fail('history map not ready')

const km = parseFloat(hist.kpis[0])
km > 0 ? ok(`distance for the window: ${km} km`) : fail(`distance is ${hist.kpis[0]} — the report returned no rows`)

if (hist.rows > 0) ok(`stops list has ${hist.rows} rows`)
else fail('stops list empty — the stops report returned nothing')
await page.screenshot({ path: `${OUT}/02-history.png` })

// ---------------------------------------------------------------------------
step('4. geofences')
await goAny(['Zone e clienti', 'Zones & sites'])
await page.waitForTimeout(2500)
const geo = await page.evaluate(() => ({
  sites: document.querySelectorAll('.geo-list .rows li').length,
  addBtn: document.querySelector('.geo-actions .btn')?.textContent,
  mapReady: !document.querySelector('.mapwait'),
}))
console.log('  ' + JSON.stringify(geo))
geo.sites > 0 ? ok(`${geo.sites} sites listed`) : fail('no sites listed')
geo.mapReady ? ok('site map ready') : fail('site map not ready')
await page.screenshot({ path: `${OUT}/03-geofences.png` })

// ---------------------------------------------------------------------------
step('5. reports')
await goAny(['Report', 'Reports'])
await page.waitForFunction(
  () => document.querySelectorAll('.grid tbody tr').length > 0
     || document.querySelector('.grid .muted'),
  null, { timeout: 30000 }
).catch(() => fail('reports table never rendered'))
await page.waitForTimeout(600)

const rep = await page.evaluate(() => ({
  kpis: [...document.querySelectorAll('.kpi')].map((k) => k.innerText.replace(/\n/g, ' ')),
  subtabs: [...document.querySelectorAll('.subtabs button')].map((b) => b.textContent),
  rows: document.querySelectorAll('.grid tbody tr').length,
  headers: [...document.querySelectorAll('.grid thead th')].map((h) => h.textContent),
  noData: document.querySelector('.grid .muted')?.textContent,
}))
console.log('  kpis:    ' + rep.kpis.join(' | '))
console.log('  subtabs: ' + rep.subtabs.join(' | '))
console.log('  headers: ' + rep.headers.join(' | '))
rep.rows > 0 && !rep.noData
  ? ok(`summary table has ${rep.rows} vehicle rows`)
  : fail('summary table has no data rows')
const tot = parseFloat(rep.kpis[0])
tot > 0 ? ok(`total ${tot} km reported`) : fail(`total km is ${rep.kpis[0]}`)
await page.screenshot({ path: `${OUT}/04-reports.png` })

for (const label of [/Fermate|Stops/i, /Viaggi|Trips/i, /Arrivi|Arrivals/i]) {
  await page.locator('.subtabs button', { hasText: label }).first().click()
  await page.waitForFunction(
    () => document.querySelectorAll('.grid tbody tr').length > 0,
    null, { timeout: 30000 }
  ).catch(() => {})
  await page.waitForTimeout(400)
  const r = await page.evaluate(() => ({
    rows: document.querySelectorAll('.grid tbody tr').length,
    noData: !!document.querySelector('.grid .muted'),
  }))
  console.log(`  ${label.source}: rows=${r.rows} noData=${r.noData}`)
  r.rows > 0 && !r.noData ? ok(`${label.source} report populated`) : fail(`${label.source} report empty`)
}

// ---------------------------------------------------------------------------
step('6. Excel export is a real spreadsheet')
const dl = page.waitForEvent('download', { timeout: 30000 }).catch(() => null)
await page.locator('.btn.primary', { hasText: /Esporta|Export/i }).first().click()
const download = await dl
if (!download) {
  fail('no download started within 30s')
} else {
  const name = download.suggestedFilename()
  ok(`downloaded ${name}`)
  name.endsWith('.xlsx') ? ok('named .xlsx') : fail(`unexpected export name ${name}`)

  // The check that matters, and the one that was missing before: an XLSX is a ZIP
  // archive, so it starts with "PK". Traccar answers `Accept: */*` with JSON, and
  // a JSON body saved as .xlsx opens as a corrupt file.
  const path = await download.path()
  const bytes = readFileSync(path)
  bytes[0] === 0x50 && bytes[1] === 0x4b
    ? ok(`export body is a real ZIP/XLSX (${bytes.length} bytes, magic PK)`)
    : fail(`export body is NOT an XLSX — first bytes: ${bytes.subarray(0, 24).toString('utf8')}`)
}

// ---------------------------------------------------------------------------
step('7. tachograph screens')
await await page.locator('.sidenav__item[data-section="drivers"]').click()
await page.waitForTimeout(1200)

const tachoShell = await page.evaluate(() => ({
  heading: document.querySelector('.tacho .ws-head .ws-title')?.textContent,
  versions: document.querySelector('.tacho .ws-head .mono')?.textContent?.trim(),
  notice: document.querySelector('.notice')?.innerText.replace(/\n/g, ' ').slice(0, 120),
  subtabs: [...document.querySelectorAll('.tacho .subtabs button')].map((b) => b.textContent),
}))
console.log('  heading:  ' + tachoShell.heading)
console.log('  versions: ' + tachoShell.versions)
console.log('  notice:   ' + tachoShell.notice)
console.log('  subtabs:  ' + tachoShell.subtabs.join(' | '))
tachoShell.subtabs.length === 5
  ? ok('five tachograph sections')
  : fail(`expected 5 sections, got ${tachoShell.subtabs.length}`)
// The registry is where a dispatcher says who drives what; it sits second,
// immediately after bring-a-card-in, because both are the same kind of work.
;/drivers|autisti/i.test(tachoShell.subtabs.join(' '))
  ? ok('the driver registry has a section')
  : fail('no driver registry section — who drives what cannot be recorded')
// Leading semicolon: a line starting with / after a statement with no trailing
// semicolon is parsed as division, not a regex literal.
;/not validated|non validato/i.test(tachoShell.notice || '')
  ? ok('the "not validated against a reference report" statement is on screen')
  : fail('the validation caveat is not shown — that is the one thing that must always be visible')
;/eu-561-2006/.test(tachoShell.versions || '')
  ? ok(`rules version shown: ${tachoShell.versions}`)
  : fail('rules/parser versions not displayed')

// --- imports
const imp = await page.evaluate(() => ({
  rows: document.querySelectorAll('.grid tbody tr').length,
  uploadForm: !!document.querySelector('.tacho input[type=file]'),
  statuses: [...document.querySelectorAll('.sev')].map((s) => s.textContent),
}))
console.log('  ' + JSON.stringify(imp))
imp.uploadForm ? ok('upload form present') : fail('no upload form')
imp.rows > 0 ? ok(`${imp.rows} import(s) listed`) : fail('no imports listed — upload a driver card first')
imp.statuses.includes('done') ? ok('an import has finished parsing') : fail('no completed import')
await page.screenshot({ path: `${OUT}/05-tacho-imports.png` })

// exercising "View" proves the timeline endpoint and its rendering, not just the list
await page.locator('.grid .btn.tiny').first().click()
await page.waitForTimeout(1500)
const tl = await page.evaluate(() => ({
  rows: document.querySelectorAll('.rows li').length,
  acts: document.querySelectorAll('.act').length,
  first: document.querySelector('.rows li')?.innerText.replace(/\n/g, ' | '),
}))
console.log('  timeline: ' + JSON.stringify(tl))
tl.acts > 0 ? ok(`activity timeline rendered (${tl.acts} changes, first: ${tl.first})`)
  : fail('activity timeline empty — the changes were not rendered')
await page.screenshot({ path: `${OUT}/06-tacho-timeline.png` })

// --- drivers: register, assign, mirror into the tracker, close
// The whole point of this screen is that the assignment reaches BOTH systems: the
// tachograph registry (dated, audited, never deleted) and the tracker's device
// attribute, which is what the fleet roster and the alerts read. A round trip is
// therefore the only useful test of it, and this one leaves no open assignment
// behind, so running it twice changes nothing the next run can see.
const VERIFY_DRIVER = 'Verify Driver'
await page.locator('.tacho .subtabs button', { hasText: /Autisti|Drivers/i }).first().click()
await page.waitForTimeout(1500)

const regShell = await page.evaluate(() => ({
  forbidden: !!document.querySelector('.sections .warn') && !document.querySelector('form.field'),
  registry: !!document.querySelector('.sections table.grid select[aria-label="Assign to"], .sections table.grid select[aria-label="Assegna a"]'),
  registerForm: !!document.querySelector('.sections form.field input'),
  cardSelect: !!document.querySelector('.sections form.field select'),
  legal: document.querySelectorAll('.warn.small').length,
  switchOff: JSON.parse(localStorage.getItem('gt.cfg') || '{}').showDriverName !== true,
  empty: /Nessun autista registrato|No drivers registered/i.test(document.body.innerText),
}))
regShell.registerForm ? ok('the registry offers a register form') : fail('no way to register a person')
regShell.cardSelect ? ok('a card from the registry can be linked at registration') : fail('no card picker')
// The switch being off must be stated on the screen, not inferred by the reader.
regShell.switchOff && regShell.legal > 0
  ? ok('the screen states that driver names are not displayed (Art. 4 L.300/1970)')
  : regShell.switchOff ? fail('the driver-name switch is off but the screen does not say so') : ok('driver names are enabled for this account')
await page.screenshot({ path: `${OUT}/10-tacho-drivers.png` })

// Register the test driver once. A second run finds them and reuses them, which
// is also the assertion that a duplicate employer reference is refused politely.
if (!(await page.evaluate((n) => document.body.innerText.includes(n), VERIFY_DRIVER))) {
  const form = page.locator('.sections form.field')
  await form.locator('input').first().fill(VERIFY_DRIVER)
  await form.locator('button.btn.primary').first().click()
  await page.waitForTimeout(1500)
}
const registered = await page.evaluate(
  (n) => document.body.innerText.includes(n) && !document.querySelector('.sections p.err'),
  VERIFY_DRIVER
)
registered ? ok(`driver registered: ${VERIFY_DRIVER}`) : fail('the driver was not registered')

// Scoped to the test driver's OWN row. Every assertion below is about what
// happens to that assignment, and a locator that took the first row in the table
// would have measured whichever driver happened to sort first.
const verRow = page.locator('.sections table.grid tbody tr', { hasText: VERIFY_DRIVER }).first()

// The assign button must not be pressable before a vehicle is chosen: an
// assignment to nothing is not a state this screen should be able to produce.
const assignBtn = verRow.locator('button.btn.tiny:not(.ghost)').first()
const disabledFirst = await assignBtn.isDisabled()
const rowSelect = verRow.locator('select')
await rowSelect.selectOption({ index: 1 })
await page.waitForTimeout(200)
disabledFirst ? ok('assign is disabled until a vehicle is chosen') : fail('assign was pressable with no vehicle selected')
await assignBtn.click()
await page.waitForTimeout(2500)

const assigned = await page.evaluate(async (n) => {
  const message = document.querySelector('.sections p.ok, .sections p.err')?.textContent || ''
  const rows = [...document.querySelectorAll('.sections table.grid tbody tr')]
  const row = rows.find((r) => r.innerText.includes(n))
  const devices = await fetch('/api/devices', { credentials: 'include' }).then((r) => r.json())
  const mirrored = devices.filter((d) => d.attributes?.driverDriverId === n).map((d) => d.name)
  return { message, vehicleCell: row ? row.children[3]?.innerText.trim() : null, mirrored }
}, VERIFY_DRIVER)
console.log('  assign: ' + assigned.message)
console.log('  mirrored into: ' + (assigned.mirrored.join(', ') || 'nothing'))
assigned.message.includes(VERIFY_DRIVER) ? ok('the assignment is confirmed on screen') : fail('no confirmation of the assignment')
assigned.vehicleCell && assigned.vehicleCell !== '—'
  ? ok(`the roster now names the vehicle: ${assigned.vehicleCell}`)
  : fail('the registry does not show which vehicle the driver is in')
assigned.mirrored.length > 0
  ? ok(`the tracker console was updated: ${assigned.mirrored.join(', ')}`)
  : fail('the assignment did not reach the tracker, so the fleet screen disagrees with the registry')

// History: the open row must be there, and the closed ones must survive.
// The driver's name is the button that opens their own history.
await verRow.locator('button.btn.tiny.ghost').first().click()
await page.waitForTimeout(1500)
const assignmentHistory = await page.evaluate(() => {
  const panels = [...document.querySelectorAll('.sections > *')]
  const last = panels[panels.length - 1]
  const rows = [...last.querySelectorAll('table.grid tbody tr')]
  return { rows: rows.length, open: rows.filter((r) => /open|in corso/i.test(r.innerText)).length }
})
assignmentHistory.rows > 0
  ? ok(`${assignmentHistory.rows} assignment row(s) of history`)
  : fail('no assignment history')
assignmentHistory.open === 1
  ? ok('exactly one open assignment')
  : fail(`expected 1 open assignment, got ${assignmentHistory.open}`)
await page.screenshot({ path: `${OUT}/11-tacho-history.png` })

// End it, and check the tracker mirror is updated as well as the registry row
// closed. The label is translated: 'Termina' in Italian, 'End' in English.
await verRow.locator('button.btn.tiny.ghost', { hasText: /Termina|Fine|End/i }).first().click()
await page.waitForTimeout(2500)
const closed = await page.evaluate(async (n) => {
  const devices = await fetch('/api/devices', { credentials: 'include' }).then((r) => r.json())
  const panels = [...document.querySelectorAll('.sections > *')]
  const last = panels[panels.length - 1]
  const rows = [...last.querySelectorAll('table.grid tbody tr')]
  return {
    stillMirrored: devices.filter((d) => d.attributes?.driverDriverId === n).length,
    open: rows.filter((r) => /open|in corso/i.test(r.innerText)).length,
    closedRows: rows.length,
  }
}, VERIFY_DRIVER)
closed.open === 0 ? ok('the assignment is closed, not deleted') : fail('the assignment is still open after being ended')
closed.closedRows > 0 ? ok('the closed assignment stays in the history') : fail('the history was emptied')
closed.stillMirrored === 0
  ? ok('the tracker console was cleared as well')
  : fail(`the tracker still shows ${VERIFY_DRIVER} on a vehicle after the assignment ended`)

// --- activity
await page.locator('.tacho .subtabs button', { hasText: /Attività|Activity/i }).first().click()
const _di = page.locator('.tacho input[type="date"]')
if (await _di.count() >= 2) { await _di.nth(0).fill('2026-10-01'); await _di.nth(1).fill('2026-10-05'); await page.waitForTimeout(300) }
await page.waitForFunction(
  () => document.querySelectorAll('.grid tbody tr').length > 0,
  null, { timeout: 30000 }
).catch(() => fail('activity table never populated'))
await page.waitForTimeout(500)
const act = await page.evaluate(() => ({
  kpis: [...document.querySelectorAll('.kpi')].map((k) => k.innerText.replace(/\n/g, ' ')),
  rows: document.querySelectorAll('.grid tbody tr').length,
  coverageWarn: document.querySelector('.warnpanel .warn')?.textContent?.slice(0, 90),
  csvHref: [...document.querySelectorAll('a.btn')].map((a) => a.getAttribute('href')).find((h) => h && h.includes('activity.csv')),
}))
console.log('  kpis:  ' + act.kpis.join(' | '))
console.log('  rows:  ' + act.rows)
console.log('  coverage warning: ' + act.coverageWarn)
act.rows > 0 ? ok(`${act.rows} day(s) of recorded activity`) : fail('no recorded activity rows')
act.kpis.some((k) => /Guida|Driving/i.test(k)) ? ok('driving-time KPI present') : fail('no driving KPI')
act.coverageWarn ? ok(`coverage warning shown: "${act.coverageWarn}…"`) : ok('all days in range have data, no coverage warning expected')
act.csvHref ? ok('CSV export link present') : fail('no CSV export link')
await page.screenshot({ path: `${OUT}/07-tacho-activity.png` })

// --- findings
await page.locator('.tacho .subtabs button', { hasText: /Risultanze|Findings/i }).first().click()
await page.waitForTimeout(1200)
const _df = page.locator('.tacho input[type="date"]')
if (await _df.count() >= 2) { await _df.nth(0).fill('2026-10-01'); await _df.nth(1).fill('2026-10-05'); await page.waitForTimeout(300) }
await page.locator('.tacho .btn.primary').first().click()
await page.waitForFunction(
  () => document.querySelectorAll('.risultato, .panel .kpi b').length > 0
     && document.body.innerText.match(/eu-561-2006|Violazioni|Breaches/i),
  null, { timeout: 30000 }
).catch(() => fail('calculation result never appeared'))
await page.waitForTimeout(800)
const find = await page.evaluate(() => ({
  kpis: [...document.querySelectorAll('.kpi')].map((k) => k.innerText.replace(/\n/g, ' ')),
  findings: document.querySelectorAll('.rows li').length,
  breaches: document.querySelectorAll('.sev-breach').length,
  articles: [...document.querySelectorAll('.rows li .small.muted')].slice(0, 3).map((e) => e.textContent.trim()),
  assumptions: document.querySelectorAll('.rows.compact li').length,
}))
console.log('  kpis:    ' + find.kpis.join(' | '))
console.log('  findings: ' + find.findings + ', breaches: ' + find.breaches)
console.log('  articles: ' + find.articles.join(' || '))
find.kpis.length >= 4 ? ok('result KPIs rendered') : fail('result KPIs missing')
find.findings > 0 ? ok(`${find.findings} finding(s) listed`) : fail('no findings — the engine returned nothing')
find.breaches > 0 ? ok(`${find.breaches} finding(s) classified as breaches`) : fail('no breach classification')
;/Art/.test(find.articles.join(' ')) ? ok('findings cite their article') : fail('findings do not cite an article')
find.assumptions > 0 ? ok(`${find.assumptions} assumptions disclosed`) : fail('assumptions not shown')
await page.screenshot({ path: `${OUT}/08-tacho-findings.png` })

// --- audit (as administrator -> owner, so it should be permitted)
await page.locator('.tacho .subtabs button', { hasText: /Registro|Access log|Audit/i }).first().click()
await page.waitForTimeout(1500)
const audit = await page.evaluate(() => ({
  rows: document.querySelectorAll('.grid tbody tr').length,
  forbidden: !!document.querySelector('.warn'),
  actions: [...document.querySelectorAll('.grid tbody tr')].slice(0, 4).map((r) => r.innerText.replace(/\t/g, ' | ')),
}))
console.log('  audit rows: ' + audit.rows)
console.log('  first: ' + audit.actions[0])
audit.forbidden ? fail('the audit log was refused for an administrator') : ok('audit log readable by owner')
audit.rows > 0 ? ok(`${audit.rows} audit entries`) : fail('audit log is empty although reads and writes happened')
;/import\.|calculation\.|driver_cards\.|report\.|registry\./.test(JSON.stringify(audit.actions))
  ? ok('audit entries name the action taken')
  : fail('audit entries do not identify the action')
await page.screenshot({ path: `${OUT}/09-tacho-audit.png` })

// ---------------------------------------------------------------------------
step('8. settings + language switch')
await goAny(['Impostazioni', 'Settings'])
const set = await page.evaluate(() => ({
  inputs: document.querySelectorAll('.settings input').length,
  driverSwitch: !!document.querySelector('.settings .field.check input'),
  driverChecked: document.querySelector('.settings .field.check input')?.checked,
}))
console.log('  ' + JSON.stringify(set))
set.driverSwitch ? ok('driver-name switch present') : fail('driver switch missing')
set.driverChecked === false
  ? ok('driver name is OFF by default, as designed (Art. 4 L.300/1970)')
  : fail('driver name is ON by default — legal risk')

await page.locator('.sidenav .lang button', { hasText: 'EN' }).click()
await page.waitForTimeout(900)
const enCheck = await page.evaluate(() => ({
  tabs: [...document.querySelectorAll('.sidenav__item')].map((b) => (b.textContent || '').trim()),
  status: document.querySelector('.pane__stats')?.innerText.replace(/\n/g, ' '),
  lang: document.documentElement.lang,
}))
console.log('  EN: ' + JSON.stringify(enCheck))
const allEn = enCheck.tabs.join(' ')
// Expected copy, kept in step with the `en` dictionary in src/i18n/index.js.
// Checking the Italian words are gone as well makes this a test of the language
// switch rather than of six substrings happening to appear.
const expectedEn = ['Overview', 'Live Fleet', 'History & Reports', 'Scrap Operations', 'Inventory', 'Sales & Deliveries', 'Drivers & Tachograph', 'Alerts & Administration']
const expectedIt = ['Panoramica', 'Flotta in tempo reale', 'Storico e report', 'Operazioni rottame', 'Magazzino', 'Vendite e consegne', 'Autisti e tachigrafo', 'Allarmi e amministrazione']
const atWord = (w) =>
  new RegExp('(^|\\W)' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\W|$)')
const missing = expectedEn.filter((w) => !allEn.includes(w))
// Word boundaries matter here: the Italian 'Report' is a substring of 'Reports'.
const leftover = expectedIt.filter((w) => atWord(w).test(allEn))
missing.length === 0 && leftover.length === 0
  ? ok('tabs localised to EN, with no Italian left behind')
  : fail(
      'tabs not localised: ' + allEn +
        (missing.length ? ' | missing: ' + missing.join(', ') : '') +
        (leftover.length ? ' | still Italian: ' + leftover.join(', ') : '')
    )
// The document's language is the UI's language. index.html can only declare one
// of the two, and a screen reader chooses its voice from this attribute: stuck on
// "it", every English string on screen is read aloud in Italian.
enCheck.lang === 'en'
  ? ok('the document language follows the switch to English (en)')
  : fail(`documentElement.lang is "${enCheck.lang}" while the UI is English`)

await page.screenshot({ path: `${OUT}/10-english.png` })

// ---------------------------------------------------------------------------
step('9. connect a tracker — the six hops, live')

// Back to Italian: this step asserts copy, and step 8 left the app in English.
await page.locator('.sidenav .lang button', { hasText: 'IT' }).click()
await page.waitForTimeout(500)
await goAny(['Collega tracker', 'Connect tracker'])

await page.waitForSelector('.hops .hop', { timeout: 25000 })
  .catch(() => fail('the hop list never rendered'))
await page.waitForTimeout(1500)

// The server's own view, read from the page, so the screen can be compared with
// the API it claims to be reporting rather than with a literal in this file.
const apiStatus = await page.evaluate(() =>
  fetch('/connect/status', { credentials: 'include' }).then((r) => r.json()).catch(() => null)
)
console.log('  api: h02=' + JSON.stringify(apiStatus?.h02) +
  ' registration=' + JSON.stringify(apiStatus?.registration))
apiStatus ? ok('GET /connect/status answers the signed-in administrator') : fail('/connect/status failed')

const onb = await page.evaluate(() => ({
  diag: document.querySelector('.onb-diag')?.innerText.replace(/\n/g, ' ').trim(),
  hops: [...document.querySelectorAll('.hops .hop')].map((h) => ({
    n: h.querySelector('.hop-n')?.textContent?.trim(),
    state: h.querySelector('.badge')?.textContent?.trim(),
    name: h.querySelector('.hop-top strong')?.textContent?.trim(),
  })),
  reg: [...document.querySelectorAll('.onb-reg tbody tr')].map((r) =>
    r.innerText.replace(/\s+/g, ' ').trim()),
  refused: [...document.querySelectorAll('.onb-refused tbody tr')].map((r) =>
    r.innerText.replace(/\s+/g, ' ').trim()),
  registrationOpen: [...document.querySelectorAll('.notice')]
    .some((n) => /APERTA|OPEN/i.test(n.innerText)),
  smsBefore: !!document.querySelector('.onb-problems'),
  problemText: document.querySelector('.onb-problems')?.innerText.replace(/\n/g, ' '),
  portValue: document.querySelectorAll('.onb-sms-form input')[2]?.value,
}))
console.log('  diag:     ' + onb.diag)
console.log('  hops:     ' + onb.hops.map((h) => `${h.n}:${h.name}=${h.state}`).join(' | '))
console.log('  reg:      ' + onb.reg.join(' | '))
console.log('  refused:  ' + (onb.refused.length ? onb.refused.join(' | ') : '(none)'))

onb.hops.length === 6
  ? ok('all six hops rendered, in the sheet\'s order')
  : fail(`expected 6 hops, got ${onb.hops.length}`)
onb.hops.map((h) => h.n).join(',') === '1,2,3,4,5,6'
  ? ok('hops are numbered 1..6 as on the printed sheet')
  : fail('hop numbering wrong: ' + onb.hops.map((h) => h.n).join(','))

// The vocabulary is closed. A state outside the four means the screen invented a
// claim it cannot support.
const KNOWN = [/^ok$/i, /in attesa|waiting/i, /bloccata|blocked/i, /non visibile|not visible/i]
const unknownStates = onb.hops.map((h) => h.state).filter((s) => !KNOWN.some((re) => re.test(s || '')))
unknownStates.length === 0
  ? ok('every hop states one of the four supported states')
  : fail('unrecognised hop states: ' + unknownStates.join(', '))

// The diagnosis names its state in a word as well as in a colour: the same chip a
// hop row carries, and no coloured rule down the block's left edge. Colour alone
// is not a signal, and this screen is read beside a printed sheet that has none.
const diagBlock = await page.evaluate(() => {
  const el = document.querySelector('.onb-diag')
  return {
    chip: el?.querySelector('.badge')?.textContent?.trim() || null,
    sideBorder: el ? getComputedStyle(el).borderLeftWidth : 'missing',
  }
})
KNOWN.some((re) => re.test(diagBlock.chip || ''))
  ? ok(`the diagnosis states its state in a word (${diagBlock.chip})`)
  : fail(`the diagnosis has no state word: ${diagBlock.chip}`)
diagBlock.sideBorder === '0px'
  ? ok('no coloured rule down the diagnosis, as nowhere else in the sheet')
  : fail(`the diagnosis block carries a ${diagBlock.sideBorder} side border`)

// Reachability, which no data assertion covers: a way past the nav, a focus ring
// that ships, and a document language that follows the switch back.
const a11y = await page.evaluate(() => {
  const rules = [...document.styleSheets]
    .flatMap((s) => { try { return [...s.cssRules] } catch { return [] } })
    .map((r) => r.selectorText || '')
  const link = document.querySelector('a.skip')
  const href = link?.getAttribute('href') || null
  const target = href && href.startsWith('#') ? document.querySelector(href) : null
  return {
    skip: href,
    skipTarget: !!target,
    // The shell is pointer-transparent on purpose so the map takes a drag that
    // starts between two panels. A link inside it that does not opt back in is
    // focusable and unclickable at the same time.
    skipClickable: link ? getComputedStyle(link).pointerEvents !== 'none' : false,
    mainFocusable: target?.getAttribute('tabindex') === '-1',
    focusRing: rules.includes(':focus-visible'),
    lang: document.documentElement.lang,
  }
})
a11y.skipTarget && a11y.mainFocusable
  ? ok(`the skip link "${a11y.skip}" resolves to a focusable target`)
  : fail(`skip link "${a11y.skip}" does not resolve (target: ${a11y.skipTarget})`)
a11y.skipClickable
  ? ok('the skip link accepts a click (the shell is pointer-transparent)')
  : fail('the skip link is unclickable: pointer-events:none inherited from .shell')
a11y.focusRing
  ? ok('a :focus-visible ring ships for keyboard users')
  : fail('no :focus-visible ring in the sheet')

// The vendored face, checked against the DEPLOYED image rather than the source
// tree. This is the assertion that catches a Dockerfile that forgets `public/`:
// the build stays green, every page still renders, and the only symptom is the
// whole console quietly falling back to the platform UI face.
const font = await page.evaluate(async () => {
  await document.fonts.ready
  const res = await fetch('/fonts/manrope-latin.woff2', { method: 'HEAD' }).catch(() => null)
  return {
    status: res ? res.status : 'no response',
    rendered: document.fonts.check('14px Manrope'),
    stack: getComputedStyle(document.body).fontFamily,
  }
})
font.status === 200
  ? ok('the vendored font file is served by the running container (HTTP 200)')
  : fail(`/fonts/manrope-latin.woff2 answered ${font.status}: the image is missing public/`)
font.rendered && /^Manrope/.test(font.stack)
  ? ok(`body renders in the vendored face (${font.stack.split(',')[0]})`)
  : fail(`body resolves "${font.stack}" and Manrope loaded=${font.rendered}`)
a11y.lang === 'it'
  ? ok('the document language followed the switch back to Italian (it)')
  : fail(`documentElement.lang is "${a11y.lang}" while the UI is Italian`)

// Hop 3 is the listener, and in this deployment it is up. Hop 4 is the identifier:
// if the server has refused one, the screen must say BLOCKED and offer the fix
// rather than reporting a generic failure.
// Leading semicolon on the two statements that start with a regex literal: after
// a line that does not end in a semicolon, `/` is parsed as division. Same trap as
// the comment in step 10.
;/^ok$/i.test(onb.hops[2]?.state || '')
  ? ok('hop 3 (TCP 5013) reads ok — the h02 listener answers inside the network')
  : fail(`hop 3 reads "${onb.hops[2]?.state}" with the listener up`)
if (onb.refused.length > 0) {
  ;/bloccata|blocked/i.test(onb.hops[3]?.state || '')
    ? ok(`hop 4 reads blocked while ${onb.refused.length} identifier(s) are refused`)
    : fail(`hop 4 reads "${onb.hops[3]?.state}" although the server refused an identifier`)
} else {
  ok('no refused identifier in the log, so hop 4 is not asserted as blocked')
}

// The screen must state the settings this server is RUNNING with, not the
// documented defaults: they differ (registerUnknown is off by default and can be
// on), and the difference is the answer to "why did my tracker not appear?".
onb.reg.some((r) => new RegExp(apiStatus.registration.registerUnknown ? 'attiva|on' : 'disattivata|off', 'i').test(r))
  ? ok('the registration state shown matches what the container rendered')
  : fail('the registration table does not match /connect/status: ' + onb.reg.join(' | '))
apiStatus.registration.allowRegistration === onb.registrationOpen
  ? ok(`the "registration is open" warning follows the real setting (${apiStatus.registration.allowRegistration})`)
  : fail('the registration-open warning disagrees with the server')

// The port field is fed from the server's own mapping, not hardcoded to 5013.
String(onb.portValue) === String(apiStatus.h02.hostPort)
  ? ok(`the SMS port field defaults to this deployment's published port (${onb.portValue})`)
  : fail(`SMS port field is ${onb.portValue}, server publishes ${apiStatus.h02.hostPort}`)

// An empty APN and server must not silently render a sequence with blanks in it.
onb.smsBefore ? ok('an incomplete form says what is missing instead of emitting commands') : fail('no validation on the SMS form')

// Now fill it in, and check the commands against the ones docs/TRACKER-SETUP.md
// documents and scripts/tests/test_connect_tracker.py asserts. Two implementations
// of one sequence is a duplication; this is what stops them drifting.
const smsInputs = page.locator('.onb-sms-form input')
await smsInputs.nth(0).fill('internet')
await smsInputs.nth(1).fill('203.0.113.10')
await page.waitForTimeout(700)

const sms = await page.evaluate(() => ({
  commands: [...document.querySelectorAll('.sms li code')].map((c) => c.textContent.trim()),
  problems: !!document.querySelector('.onb-problems'),
}))
console.log('  sms:      ' + sms.commands.join('  |  '))
const expectedSms = [
  ['apn', /^8030000 internet$/],
  ['server', /^8040000 203\.0\.113\.10 \d+$/],
  ['acc interval', /^8050000 20$/],
  ['parked interval', /^8090000 300$/],
  ['GPRS mode', /^7100000$/],
  ['read-back', /^RCONF$/],
]
if (sms.problems) fail('the filled-in form still reports a problem')
expectedSms.forEach(([label, re], i) => {
  re.test(sms.commands[i] || '')
    ? ok(`SMS ${i + 1} (${label}): ${sms.commands[i]}`)
    : fail(`SMS ${i + 1} (${label}) is "${sms.commands[i]}", expected ${re}`)
})

await page.screenshot({ path: `${OUT}/11-connect-tracker.png`, fullPage: true })

// ---------------------------------------------------------------------------
step('10. console and network health')
// The tacho tab issues a 403 for a viewer by design; this run is an administrator,
// so any 4xx here is a real problem rather than the intended refusal.
if (errors.length === 0 && bad.length === 0) ok('no console errors, no failed requests')
else {
  errors.slice(0, 8).forEach((e) => fail(e.slice(0, 200)))
  if (bad.length) {
    console.log('  failing requests:')
    ;[...new Set(bad)].slice(0, 8).forEach((b) => console.log('   ' + b))
    fail(`${bad.length} request(s) returned >= 400`)
  }
}

await browser.close()
console.log(failures ? `\nRESULT: ${failures} FAILURE(S)\n` : '\nRESULT: all checks passed\n')
process.exitCode = failures ? 1 : 0
