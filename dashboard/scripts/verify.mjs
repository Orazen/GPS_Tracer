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

const tabs = await page.locator('.tabs .tab').allTextContents()
console.log('  tabs: ' + tabs.join(' | '))
tabs.length === 6 ? ok('all 6 tabs present (fleet…settings + tachograph)') : fail(`expected 6 tabs, got ${tabs.length}`)

const go = async (label) => {
  await page.locator('.tabs .tab', { hasText: label }).first().click()
  await page.waitForTimeout(1200)
}

// ---------------------------------------------------------------------------
step('2. fleet map')
await go(/Parco mezzi|Fleet/i)
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
    roster: document.querySelectorAll('.trow').length,
    spread: xs.length ? Math.round(Math.max(...xs) - Math.min(...xs)) : 0,
    statusbar: document.querySelector('.statusbar')?.innerText.replace(/\n/g, ' '),
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
await go(/Cronologia|History/i)
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
await go(/Siti|Sites|Zone/i)
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
await go(/Report/i)
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
await go(/Cronotachigrafo|Tachograph/i)

const tachoShell = await page.evaluate(() => ({
  heading: document.querySelector('.tacho-head h2')?.textContent,
  versions: document.querySelector('.tacho-head .mono')?.textContent?.trim(),
  notice: document.querySelector('.notice')?.innerText.replace(/\n/g, ' ').slice(0, 120),
  subtabs: [...document.querySelectorAll('.tacho .subtabs button')].map((b) => b.textContent),
}))
console.log('  heading:  ' + tachoShell.heading)
console.log('  versions: ' + tachoShell.versions)
console.log('  notice:   ' + tachoShell.notice)
console.log('  subtabs:  ' + tachoShell.subtabs.join(' | '))
tachoShell.subtabs.length === 4 ? ok('four tachograph sections') : fail(`expected 4 sections, got ${tachoShell.subtabs.length}`)
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

// --- activity
await page.locator('.tacho .subtabs button', { hasText: /Attività|Activity/i }).first().click()
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
act.coverageWarn ? ok(`coverage warning shown: "${act.coverageWarn}…"`) : fail('coverage warning missing although days are absent')
act.csvHref ? ok('CSV export link present') : fail('no CSV export link')
await page.screenshot({ path: `${OUT}/07-tacho-activity.png` })

// --- findings
await page.locator('.tacho .subtabs button', { hasText: /Risultanze|Findings/i }).first().click()
await page.waitForTimeout(1200)
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
;/import\.|calculation\.|driver_cards\.|report\./.test(JSON.stringify(audit.actions))
  ? ok('audit entries name the action taken')
  : fail('audit entries do not identify the action')
await page.screenshot({ path: `${OUT}/09-tacho-audit.png` })

// ---------------------------------------------------------------------------
step('8. settings + language switch')
await go(/Impostazioni|Settings/i)
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

await page.locator('.topright .lang button', { hasText: 'EN' }).click()
await page.waitForTimeout(900)
const enCheck = await page.evaluate(() => ({
  tabs: [...document.querySelectorAll('.tabs .tab')].map((b) => b.textContent),
  status: document.querySelector('.statusbar')?.innerText.replace(/\n/g, ' '),
}))
console.log('  EN: ' + JSON.stringify(enCheck))
const allEn = enCheck.tabs.join(' ')
// Expected copy, kept in step with the `en` dictionary in src/i18n/index.js.
// Checking the Italian words are gone as well makes this a test of the language
// switch rather than of six substrings happening to appear.
const expectedEn = ['Fleet', 'History', 'Zones & sites', 'Reports', 'Tachograph', 'Settings']
const expectedIt = ['Parco mezzi', 'Cronologia', 'Zone e clienti', 'Cronotachigrafo', 'Impostazioni']
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
await page.screenshot({ path: `${OUT}/10-english.png` })

// ---------------------------------------------------------------------------
step('9. console and network health')
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
