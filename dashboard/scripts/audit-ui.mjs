/**
 * UI audit: the measurements behind the design rules that a stylesheet cannot
 * state about itself.
 *
 * Screenshots cannot be composited in this environment (recorded as a standing
 * limitation in docs/DESIGN-AUDIT.md), so this measures what a screenshot would
 * have shown: geometry, the painted type census, tap targets, text clipped out of
 * its box, and every text colour against its effective background.
 *
 *     cd dashboard && npm run audit:ui        # needs a seeded, running stack
 *
 * EXIT STATUS. This used to print and always exit 0, which made it a report
 * somebody had to read rather than a check. It now counts violations, prints one
 * `FAIL:` line per violation as it is found, ends with a RESULT line and exits 1
 * if there was any. A clean run prints exactly what it printed before, so the
 * strings docs/DESIGN-AUDIT.md quotes are still the strings on screen; the exit
 * status is what changed.
 *
 * A finding is a rule broken, not a measurement reported. The rules:
 *   * every view's switcher tile is present and pressable, and no column has
 *     collapsed -- neither missing from the DOM nor left with no room to paint;
 *   * every text colour clears 4.5:1 (3:1 above 24px) on the surface it sits on --
 *     the muted grey was 2.68:1 on white and it was on all seven screens;
 *   * nothing paints above weight 600 -- the browser's default for <strong>, <b>
 *     and <th> is 700, which is how a second and bolder typeface appears without
 *     anyone choosing one;
 *   * nothing is clipped out of its box, no region is empty, the page does not
 *     scroll sideways at 1680px, and it does not scroll sideways at 320px
 *     (WCAG 1.4.10) -- content that is past the edge and not reachable by
 *     scrolling its own region is content a person cannot get to;
 *   * every control has an accessible name;
 *   * every tab stop shows a focus indicator, is on screen when focused, and the
 *     first stop is the skip link;
 *   * every control is at least 28px tall and 24px wide;
 *   * prefers-reduced-motion actually switches the animation off;
 *   * the bundle being measured is the bundle in dashboard/dist.
 *
 * The tap-target floor is 28px, deliberately stricter than the 24px in WCAG 2.5.8,
 * because a comfortable control beats a compliant one. Two targets are below it in
 * the current build and are recorded as exceptions with reasons in
 * TARGET_ALLOWANCES below -- each one conditional, so the exception expires if the
 * thing that justified it changes, and each one printed on every run so it cannot
 * hide.
 */
import { chromium } from 'playwright'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const URL = process.env.DASHBOARD_URL || 'http://127.0.0.1:8083/'
const EMAIL = process.env.VERIFY_EMAIL || 'admin@gpstracer.local'
const PASSWORD = process.env.VERIFY_PASSWORD || 'Gpstrack2026!'
const DIST = process.env.AUDIT_DIST || join(dirname(fileURLToPath(import.meta.url)), '..', 'dist')
// The tile labels now live in aria-label rather than in text: the reference
// console's switcher is icon-only, so a tile carries its name for a screen
// reader and nothing visible. Navigating by aria-label is therefore also a test
// that the icon-only switcher stayed announced.
const VIEWS = ['Fleet', 'History', 'Zones & sites', 'Reports', 'Alerts', 'Tachograph', 'Settings', 'Connect tracker']

// Screens that hide part of themselves behind their own tabs. The switcher tile
// opens the screen; it does not open the tab, so without this every control
// behind one of these is measured by nothing at all. Both screens that have tabs
// are listed: the Tachograph screen (Imports, Drivers, Activity, Findings,
// Access log) and History (stops, arrivals, points).
const SUB_TABS = {
  Tachograph: '.tacho .subtabs',
  History: '.history .subtabs',
}

// ---------------------------------------------------------------------------
// The failure ledger. One line per violation, counted at the end.
// ---------------------------------------------------------------------------
let findings = 0
const fail = (why) => { findings++; console.log(`  FAIL: ${why}`) }

// ---------------------------------------------------------------------------
// Sub-28px targets that are accepted, and the condition under which they stop
// being accepted. Both of these were checked by hand before being written here;
// neither is a blanket exemption, because a blanket exemption is how a rule rots.
// ---------------------------------------------------------------------------
const TARGET_ALLOWANCES = [
  {
    name: 'third-party inline attribution',
    // MapLibre's own attribution link, inside a sentence, and not this console's
    // markup: WCAG 2.5.8's inline exception. Conditional on it still being a link
    // inside MapLibre's attribution control -- if MapLibre changes that container,
    // this stops matching and the target is reported.
    matches: (t) => t.inAttrib,
  },
  {
    name: 'label is the target',
    // The geofence checkbox: a 13px box inside the label that is the real target,
    // which is 548x20. Conditional on the label genuinely being the target -- it
    // has to be a checkable input, enclosed in a label that is larger than the box
    // in both directions, and wide enough to be hittable (>= 200px). A 13px box in
    // a 14px label is not excused by this.
    matches: (t) => t.checkable && t.labelIsTarget,
  },
]

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1680, height: 980 } })
await page.addInitScript(() => localStorage.setItem('gt.lang', 'en'))

console.log(`audit: ${URL}`)

// No stack, no measurement. A timeout here used to surface as a Playwright stack
// trace and a non-zero exit; it now names what went wrong, because "could not
// sign in" and "the dashboard is broken" are different things to go and fix.
await page.goto(URL)
try {
  await page.fill('input[type=email]', EMAIL)
  await page.fill('input[type=password]', PASSWORD)
  await page.click('button.btn.primary')
  await page.waitForSelector('.shell', { timeout: 20000 })
} catch (err) {
  fail(`no dashboard shell at ${URL} after signing in as ${EMAIL}: ${String(err).split('\n')[0]}`)
  console.log(findings ? `\nRESULT: ${findings} UI finding(s)\n` : '\nRESULT: all UI checks passed\n')
  await browser.close()
  process.exit(1)
}
await page.waitForTimeout(2500)

/**
 * Press a switcher tile by its accessible name.
 *
 * false means the screen was not reached, and there are two ways that happens:
 * there is no such tile, or there is one and it cannot be pressed. The second
 * used to throw a Playwright stack trace out of the middle of the run -- exit 1
 * with no FAIL line and no RESULT line, the least readable outcome for exactly
 * the case this audit exists for, a screen the switcher will not open. Both now
 * count as a finding, and the run carries on to the checks that do not need the
 * screen instead of dying.
 */
let tileFailure = 'missing'
const goTo = async (name) => {
  // Open each section until the named screen is listed under it.
  const screen = page.locator('.sidenav__sub-item').filter({ hasText: new RegExp('^\\s*' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*$') })
  const sections = await page.locator('.sidenav__item').count()
  for (let i = 0; i < sections; i++) {
    const sec = page.locator('.sidenav__item').nth(i)
    const secText = (await sec.innerText()).trim()
    if (secText === name || secText.includes(name)) { await sec.click({ timeout: 5000 }).catch(() => {}); await page.waitForTimeout(200); return true }
    if (await screen.count()) { await screen.first().click({ timeout: 5000 }).catch(() => {}); return true }
    await sec.click({ timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(200)
    if (await screen.count()) { await screen.first().click({ timeout: 5000 }).catch(() => {}); return true }
  }
  const tile = screen
  if (!(await tile.count())) { tileFailure = 'missing'; return false }
  try {
    // 5s, not Playwright's 30s default: a switcher tile that has not answered in
    // five seconds is one a person would have given up on too, and the negative
    // controls press an unpressable tile eight times per section.
    await tile.first().click({ timeout: 5000 })
    return true
  } catch {
    tileFailure = 'unreachable'
    return false
  }
}

const tileFailureLine = (name) => tileFailure === 'missing'
  ? `[${name}] there is no switcher tile with that accessible name, so the screen was not measured`
  : `[${name}] the switcher tile for ${name} is in the DOM but could not be pressed (hidden, covered, or never stable), so the screen was not measured`

const probe = () => ({
  // ---- geometry of the three columns --------------------------------------
  columns: ['.pane', '.col-main', '.col-right'].map((sel) => {
    const el = document.querySelector(sel)
    if (!el) return { sel, missing: true }
    const r = el.getBoundingClientRect()
    return {
      sel,
      x: Math.round(r.x), w: Math.round(r.width), h: Math.round(r.height),
      children: el.children.length,
      text: (el.innerText || '').trim().length,
    }
  }),
  viewport: { w: innerWidth, h: innerHeight },
  bodyOverflowX: document.body.scrollWidth - innerWidth,
  shell: (() => {
    const el = document.querySelector('.shell')
    const r = el.getBoundingClientRect()
    return { x: Math.round(r.x), w: Math.round(r.width) }
  })(),

  // ---- the type actually painted ------------------------------------------
  census: (() => {
    const seen = new Map()
    for (const el of document.querySelectorAll('*')) {
      if (!el.textContent || !el.textContent.trim()) continue
      if (el.children.length) continue
      const cs = getComputedStyle(el)
      if (cs.display === 'none' || cs.visibility === 'hidden') continue
      const key = `${cs.fontSize}/${cs.fontWeight}`
      seen.set(key, (seen.get(key) || 0) + 1)
    }
    return [...seen.entries()].sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} x${n}`)
  })(),

  // ---- controls too small to hit ------------------------------------------
  smallTargets: [...document.querySelectorAll('button, a, input, select')]
    .filter((el) => {
      const cs = getComputedStyle(el)
      if (cs.display === 'none' || cs.visibility === 'hidden') return false
      const r = el.getBoundingClientRect()
      return r.width > 0 && r.height > 0 && (r.height < 28 || r.width < 24)
    })
    .map((el) => {
      const r = el.getBoundingClientRect()
      const label = el.closest('label') || (el.id ? document.querySelector(`label[for="${el.id}"]`) : null)
      const lr = label ? label.getBoundingClientRect() : null
      return {
        what: `${el.tagName.toLowerCase()}.${(el.className || '').toString().split(' ')[0]}`,
        w: Math.round(r.width), h: Math.round(r.height),
        inAttrib: el.tagName === 'A' && !!el.closest('.maplibregl-ctrl-attrib'),
        checkable: el.tagName === 'INPUT' && (el.type === 'checkbox' || el.type === 'radio') && !!lr,
        labelW: lr ? Math.round(lr.width) : 0,
        labelH: lr ? Math.round(lr.height) : 0,
        labelIsTarget: !!lr && lr.width > r.width && lr.height > r.height && lr.width >= 200,
      }
    }),

  // ---- text clipped or overflowing its box --------------------------------
  clipped: [...document.querySelectorAll('*')]
    .filter((el) => !el.children.length && el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0)
    .map((el) => `${el.className || el.tagName} "${(el.textContent || '').trim().slice(0, 28)}" ${el.scrollWidth}>${el.clientWidth}`),

  // ---- contrast -----------------------------------------------------------
  contrast: (() => {
    const lum = (c) => {
      const [r, g, b] = c
      const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 }
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    }
    const parse = (s) => {
      const m = s.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/)
      return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null
    }
    const bgOf = (el) => {
      for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
        const c = parse(getComputedStyle(n).backgroundColor)
        if (c && c[3] > 0.85) return c
      }
      return [255, 255, 255, 1]
    }
    const bad = []
    for (const el of document.querySelectorAll('*')) {
      if (el.children.length || !el.textContent || !el.textContent.trim()) continue
      const cs = getComputedStyle(el)
      if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue
      const fg = parse(cs.color)
      if (!fg) continue
      const bg = bgOf(el)
      const l1 = lum(fg), l2 = lum(bg)
      const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)
      const size = parseFloat(cs.fontSize)
      const large = size >= 24 || (size >= 18.66 && +cs.fontWeight >= 700)
      const need = large ? 3 : 4.5
      if (ratio < need) {
        bad.push(`${cs.fontSize} ${cs.color} on rgb(${bg[0]},${bg[1]},${bg[2]}) = ${ratio.toFixed(2)}:1 (need ${need}) "${el.textContent.trim().slice(0, 24)}"`)
      }
    }
    // Distinct problems only; the same pair repeats on every row.
    return [...new Set(bad.map((s) => s.replace(/"[^"]*"$/, '')))].slice(0, 14)
  })(),

  // ---- the empty middle column, if it is still empty ----------------------
  emptyRegions: [...document.querySelectorAll('.col-main, .workspace, .workspace > *')]
    .filter((el) => !(el.innerText || '').trim() && el.getBoundingClientRect().width > 100)
    .map((el) => `${el.className} ${Math.round(el.getBoundingClientRect().width)}x${Math.round(el.getBoundingClientRect().height)}`),

  // ---- is the "empty" middle column actually dead space, or the map? ------
  mapBox: (() => {
    const el = document.querySelector('.maplibregl-map')
    if (!el) return null
    const r = el.getBoundingClientRect()
    return `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}`
  })(),
  canvasCover: (() => {
    const c = document.querySelector('canvas')
    if (!c) return null
    const r = c.getBoundingClientRect()
    return `${Math.round(r.width)}x${Math.round(r.height)}`
  })(),

  // ---- the entrance on the workspace panel -------------------------------
  workspaceAnim: (() => {
    const el = document.querySelector('.workspace')
    if (!el) return 'no workspace in this view'
    const cs = getComputedStyle(el)
    return `${cs.animationName} ${cs.animationDuration} ${cs.animationFillMode}`
  })(),

  // ---- the geofence checkbox: is its TARGET the 13px box, or the label? --
  checkboxTarget: [...document.querySelectorAll('input[type=checkbox]')].map((box) => {
    const label = box.closest('label')
    const r = (label || box).getBoundingClientRect()
    const b = box.getBoundingClientRect()
    return `box ${Math.round(b.width)}x${Math.round(b.height)} in ${label ? 'a label' : 'nothing'} of ${Math.round(r.width)}x${Math.round(r.height)}`
  }),
})

/**
 * Press one of a screen's own tabs, by index.
 *
 * Scoped to the BUTTON, and bounded: a tab that cannot be pressed is reported as
 * a finding by the caller rather than skipped, because a sweep that silently
 * measures the wrong tab is how "five tabs, all clean" gets printed while one of
 * them was never opened at all.
 *
 * By index rather than by label because History's tab labels carry live counts
 * ("Fermate 12"): reading the labels once and then matching on that text is a
 * moving target, and the mismatch it produces reads as a tab that will not open.
 */
const pressSubTab = async (root, index) => {
  try {
    await page.locator(`${root} button`).nth(index).click({ timeout: 5000 })
    return true
  } catch {
    return false
  }
}

/** A screen's tab label, read at the moment that tab is pressed. */
const subTabLabel = async (root, index) =>
  ((await page.locator(`${root} button`).nth(index).innerText().catch(() => '')) || '').trim()

/** How many tabs the screen keeps behind its switcher tile. */
const subTabCount = (root) => page.locator(`${root} button`).count().catch(() => 0)

/**
 * Every control a screen reader would announce with no name.
 *
 * A page-side probe rather than a closure over the audit's state, because it is
 * evaluated twice per screen now: once for the screen itself, and once for each
 * tab it keeps its own controls behind.
 */
function unnamedControls() {
  const nameOf = (el) => {
    const aria = el.getAttribute('aria-label')
    if (aria && aria.trim()) return aria.trim()
    const by = el.getAttribute('aria-labelledby')
    const target = by && document.getElementById(by)
    if (target && target.textContent.trim()) return target.textContent.trim()
    const label = el.closest('label') ||
      (el.id ? document.querySelector(`label[for="${el.id}"]`) : null)
    if (label && label.textContent.trim()) return label.textContent.trim()
    if (el.tagName === 'BUTTON' || el.tagName === 'A') {
      const text = (el.innerText || el.textContent || '').trim() || el.getAttribute('title') || ''
      if (text) return text
    }
    return ''
  }
  const out = []
  for (const el of document.querySelectorAll('input, select, textarea, button, a')) {
    const cs = getComputedStyle(el)
    if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue
    if (el.closest('[aria-hidden="true"]')) continue
    if (el.type === 'hidden') continue
    if (nameOf(el)) continue
    const ph = el.tagName === 'INPUT' && el.placeholder ? ` (placeholder only: ${JSON.stringify(el.placeholder)})` : ''
    out.push(`${el.tagName.toLowerCase()}${el.type ? '[' + el.type + ']' : ''}${el.className ? '.' + String(el.className).split(' ')[0] : ''}${ph}`)
  }
  return out
}

for (const name of VIEWS) {
  if (!(await goTo(name))) {
    console.log(`\n### ${name}: NO TAB`)
    fail(tileFailureLine(name))
    continue
  }
  await page.waitForTimeout(2200)
  const r = await page.evaluate(probe)
  console.log(`\n### ${name}`)
  console.log(`  columns:  ${r.columns.map((c) => c.missing ? `${c.sel}:missing` : `${c.sel} x=${c.x} w=${c.w} kids=${c.children} text=${c.text}`).join('  |  ')}`)
  console.log(`  overflowX: ${r.bodyOverflowX}px   shell x=${r.shell.x} w=${r.shell.w}`)
  if (r.emptyRegions.length) console.log(`  EMPTY REGIONS: ${r.emptyRegions.join(', ')}`)
  console.log(`  type:     ${r.census.slice(0, 8).join('  ')}`)
  const excused = []
  const bad = []
  for (const t of r.smallTargets) {
    const allow = TARGET_ALLOWANCES.find((a) => a.matches(t))
    const shown = `${t.what} ${t.w}x${t.h}`
    allow ? excused.push(`${shown} (excused: ${allow.name})`) : bad.push(shown)
  }
  if (excused.length) console.log(`  small targets, recorded exceptions: ${excused.join(', ')}`)
  if (bad.length) console.log(`  small targets: ${bad.join(', ')}`)
  if (r.clipped.length) console.log(`  clipped:  ${r.clipped.slice(0, 6).join(' ; ')}`)
  if (r.contrast.length) console.log(`  CONTRAST:\n    ${r.contrast.join('\n    ')}`)
  else console.log('  contrast: all text clears its threshold')
  if (r.mapBox || r.canvasCover) console.log(`  map: ${r.mapBox} canvas ${r.canvasCover}  <- what the "empty" middle column shows`)
  if (r.workspaceAnim) console.log(`  workspace entrance: ${r.workspaceAnim}`)
  if (r.checkboxTarget.length) console.log(`  checkbox: ${r.checkboxTarget.join(' | ')}`)

  judgeScreen(name, r)
}

/**
 * The rules, applied to one measured screen.
 *
 * Kept as a function because two loops need them: the one above, which walks the
 * eight screens the switcher reaches, and the one below, which walks what the
 * Tachograph screen keeps behind its own tabs. Printing stays with each caller, so
 * the per-screen report reads exactly as it did before this was extracted.
 *
 * `.col-right` is legitimately absent from seven of the eight screens: only the
 * fleet has a third column. The other two collapsing is the failure. A column has
 * collapsed either way: gone from the DOM, or there and given no room to paint
 * anything -- which is what a `display: none`, a zero-width grid track or an
 * over-eager media query look like from out here, and which used to pass as "the
 * column is present".
 */
function judgeScreen(name, r) {
  for (const c of r.columns) {
    if (c.missing) {
      if (c.sel !== '.col-right') fail(`[${name}] the column has collapsed: ${c.sel} is not in the DOM`)
    } else if (c.w < 40 || c.h < 40) {
      fail(`[${name}] the column has collapsed: ${c.sel} is ${c.w}x${c.h}, with no room for its content`)
    }
  }
  if (r.bodyOverflowX > 1) fail(`[${name}] the page scrolls sideways by ${r.bodyOverflowX}px at 1680px`)
  const bad = []
  for (const t of r.smallTargets) {
    if (!TARGET_ALLOWANCES.find((a) => a.matches(t))) bad.push(`${t.what} ${t.w}x${t.h}`)
  }
  if (bad.length) fail(`[${name}] ${bad.length} control(s) below the 28x24 floor and not a recorded exception: ${bad.join(', ')}`)
  if (r.clipped.length) fail(`[${name}] ${r.clipped.length} text node(s) clipped out of their box: ${r.clipped.slice(0, 3).join(' ; ')}`)
  if (r.contrast.length) fail(`[${name}] ${r.contrast.length} contrast miss(es) below the WCAG floor`)
  if (r.emptyRegions.length) fail(`[${name}] empty region(s) with no content: ${r.emptyRegions.join(', ')}`)
  const heavy = r.census.filter((c) => /^\d+px\/(\d+)/.test(c) && +c.match(/\/(\d+)/)[1] > 600)
  if (heavy.length) fail(`[${name}] type painted above weight 600: ${heavy.join(', ')}`)
}

// ---- does prefers-reduced-motion actually switch the motion off? -----------
await page.emulateMedia({ reducedMotion: 'reduce' })
await goTo('Reports')
await page.waitForTimeout(400)
const reduced = await page.evaluate(() => {
  const w = document.querySelector('.workspace')
  const skip = document.querySelector('a.skip')
  return {
    workspace: w ? `${getComputedStyle(w).animationName} ${getComputedStyle(w).animationDuration}` : 'none',
    workspaceDuration: w ? parseFloat(getComputedStyle(w).animationDuration) : 0,
    skipTransition: skip ? getComputedStyle(skip).transitionDuration : 'n/a',
    skipDuration: skip ? parseFloat(getComputedStyle(skip).transitionDuration) : 0,
  }
})
console.log('\n### prefers-reduced-motion: reduce')
console.log(`  workspace animation: ${reduced.workspace}`)
console.log(`  skip link transition: ${reduced.skipTransition}`)
// The animation is 1e-05s rather than `none`: the sheet keeps the keyframes but
// takes the duration to zero, which is what "switched off" means here. The bar is
// 10ms, an order of magnitude under the threshold a person can see.
const MOTION_FLOOR = 0.01
if (reduced.workspaceDuration > MOTION_FLOOR) {
  fail(`the workspace still animates for ${reduced.workspaceDuration}s under prefers-reduced-motion`)
}
if (reduced.skipDuration > MOTION_FLOOR) {
  fail(`the skip link still transitions for ${reduced.skipDuration}s under prefers-reduced-motion`)
}

// ---------------------------------------------------------------------------
// Assistive technology: names, keyboard order, and reflow.
// Nothing above this line would notice an unlabelled control, a keyboard trap or
// a screen that needs two-dimensional scrolling at 320px.
// ---------------------------------------------------------------------------
await page.emulateMedia({ reducedMotion: 'no-preference' })
await page.setViewportSize({ width: 1680, height: 980 })
await goTo('Fleet')
await page.waitForTimeout(1800)

// ---- every control needs a name a screen reader can announce ---------------
console.log('\n### names')
for (const view of VIEWS) {
  if (!(await goTo(view))) {
    fail(tileFailureLine(view))
    continue
  }
  await page.waitForTimeout(1600)
  const unnamed = await page.evaluate(unnamedControls)
  unnamed.length === 0
    ? console.log(`  ${view.padEnd(16)} every control has an accessible name`)
    : console.log(`  ${view.padEnd(16)} UNNAMED: ${unnamed.join(', ')}`)
  if (unnamed.length) fail(`[${view}] ${unnamed.length} control(s) a screen reader would announce with no name: ${unnamed.join(', ')}`)

  // ---- what the screen keeps behind its own tabs --------------------------
  // The switcher reaches a screen; it does not reach what a screen hides behind
  // a tab. The Tachograph screen has five of them -- and its Drivers tab is a
  // register form, an assignment row per driver and a history table -- and
  // History has three more, whose names carry live counts. Those are exactly
  // where an unlabelled field or a 12px button goes unnoticed, because the
  // view-level sweep sees only whichever tab happened to be open.
  const subTabRoot = SUB_TABS[view]
  if (subTabRoot) {
    const tabs = await subTabCount(subTabRoot)
    for (let i = 0; i < tabs; i++) {
      const clean = await subTabLabel(subTabRoot, i)
      if (!clean) continue
      const where = `${view} / ${clean}`
      // `nth`, not `locator(root, { hasText })`: the latter matches the nav
      // container, whose text is every tab at once, so the click landed in the
      // middle of the strip and measured whichever tab happened to be there --
      // five tabs, one measurement, printed five times as clean.
      if (!(await pressSubTab(subTabRoot, i))) {
        fail(`[${where}] the tab could not be pressed, so nothing behind it was measured`)
        continue
      }
      // Findings are computed on the client and take a moment; the same settle
      // time the rest of this file uses per screen.
      await page.waitForTimeout(1500)
      const r = await page.evaluate(probe)
      const tabUnnamed = await page.evaluate(unnamedControls)
      const misses = [
        tabUnnamed.length ? `${tabUnnamed.length} unnamed (${tabUnnamed.join(', ')})` : null,
        r.smallTargets.filter((t) => !TARGET_ALLOWANCES.find((a) => a.matches(t))).length
          ? `${r.smallTargets.filter((t) => !TARGET_ALLOWANCES.find((a) => a.matches(t))).length} below the target floor`
          : null,
        r.contrast.length ? `${r.contrast.length} contrast miss(es)` : null,
        r.clipped.length ? `${r.clipped.length} clipped` : null,
      ].filter(Boolean)
      console.log(
        `  ${where.padEnd(28)} ${misses.length ? misses.join(', ') : 'names, targets, contrast and clipping all clean'}`
      )
      if (tabUnnamed.length) {
        fail(`[${where}] ${tabUnnamed.length} control(s) a screen reader would announce with no name: ${tabUnnamed.join(', ')}`)
      }
      judgeScreen(where, r)
    }
    // Leave the screen as it was found, so the next section measures the tab it
    // expects rather than whichever one this loop finished on.
    await pressSubTab(subTabRoot, 0)
    await page.waitForTimeout(800)
  }
}

// ---- keyboard: can a person Tab to everything, and see where they are? -----
console.log('\n### keyboard')
// A reload, not a blur(). Chromium keeps its sequential-focus starting point at
// the last element that was focused, and blur() does not clear it: tabbing after
// a click on a nav tile resumes from that tile, which read as "the skip link is
// not first" when the skip link was first all along. A fresh document has no
// starting point, so this measures the real order.
await page.reload({ waitUntil: 'load' })
await page.waitForSelector('.shell', { timeout: 20000 })
await page.waitForTimeout(1800)
const stops = []
for (let i = 0; i < 30; i++) {
  await page.keyboard.press('Tab')
  // Let the focus styles settle before measuring. The skip link travels 220% of
  // its own height on focus over 120ms, and reading its rect on the same tick as
  // the keypress reported it as off screen when it was arriving.
  await page.waitForTimeout(130)
  const stop = await page.evaluate(() => {
    const el = document.activeElement
    if (!el || el === document.body) return null
    const cs = getComputedStyle(el)
    const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none'
    const r = el.getBoundingClientRect()
    return {
      el: `${el.tagName.toLowerCase()}${el.className ? '.' + String(el.className).trim().split(/\s+/)[0] : ''}`,
      label: (el.getAttribute('aria-label') || el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 20),
      onScreen: r.width > 0 && r.height > 0 && r.top < innerHeight && r.bottom > 0,
      ring,
    }
  })
  if (!stop) break
  stops.push(stop)
}
const noRing = stops.filter((s) => !s.ring)
const offScreen = stops.filter((s) => !s.onScreen)
console.log(`  ${stops.length} tab stops: ${stops.slice(0, 6).map((s) => s.el).join(' > ')} ...`)
console.log(`  first stop: ${stops[0]?.el} "${stops[0]?.label}"`)
noRing.length === 0
  ? console.log('  every stop shows a focus indicator')
  : console.log(`  NO FOCUS INDICATOR: ${noRing.map((s) => `${s.el} "${s.label}"`).join(', ')}`)
offScreen.length === 0
  ? console.log('  every stop is on screen when focused')
  : console.log(`  focus goes off screen: ${offScreen.map((s) => s.el).join(', ')}`)
if (stops.length === 0) fail('there are no tab stops at all: the page cannot be reached by keyboard')
if (noRing.length) fail(`${noRing.length} tab stop(s) show no focus indicator: ${noRing.map((s) => `${s.el} "${s.label}"`).join(', ')}`)
if (offScreen.length) fail(`${offScreen.length} tab stop(s) are off screen when focused: ${offScreen.map((s) => s.el).join(', ')}`)
// A recorded decision from the accessibility pass: the skip link is the first
// stop, ahead of the map canvas MapLibre mounts above the shell.
if (stops.length && !stops[0].el.startsWith('a.skip')) {
  fail(`the first tab stop is ${stops[0].el} "${stops[0].label}", not the skip link`)
}

/**
 * Everything needed to decide WCAG 1.4.10 at the current viewport: what the page
 * needs horizontally, which content is past the edge and unreachable, and which
 * regions scroll inside themselves (which 1.4.10 allows, and which is the
 * difference between reachable and hidden). A page-side probe so the same
 * measurement can be taken of a screen and of each tab inside it.
 */
function reflowProbe() {
  const past = (el) => el.getBoundingClientRect().right > innerWidth + 1
  const visible = (el) => {
    const cs = getComputedStyle(el)
    return cs.display !== 'none' && cs.visibility !== 'hidden' && !el.closest('.maplibregl-map')
  }
  // The OUTERMOST offenders, not the first four leaves: a child is only past
  // the edge because a parent is, and fixing the child would fix nothing.
  // A region that scrolls inside itself is reachable, which is what 1.4.10
  // asks; only content that is CLIPPED is a defect. Wander up from each
  // offender looking for a horizontal scroll container.
  const reachable = (el) => {
    for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
      const ox = getComputedStyle(n).overflowX
      if (ox === 'auto' || ox === 'scroll') return true
    }
    return false
  }
  const wide = [...document.querySelectorAll('body *')]
    .filter((el) => visible(el) && past(el) && !reachable(el))
    .filter((el) => !(el.parentElement && visible(el.parentElement) && past(el.parentElement) && !reachable(el.parentElement)))
    .slice(0, 5)
    .map((el) => {
      const rb = el.getBoundingClientRect()
      return `${el.tagName.toLowerCase()}${el.className ? '.' + String(el.className).trim().split(/\s+/)[0] : ''} x=${Math.round(rb.x)} w=${Math.round(rb.width)} right=${Math.round(rb.right)}`
    })
  // Regions that scroll inside themselves: report them so "reachable" can be
  // told apart from "silenced". A scroller with scrollWidth > clientWidth is
  // genuinely scrollable; one that is merely declared would be hiding content.
  const scrollers = [...document.querySelectorAll('body *')]
    .filter((el) => {
      const ox = getComputedStyle(el).overflowX
      return (ox === 'auto' || ox === 'scroll') && el.scrollWidth > el.clientWidth + 1
    })
    .slice(0, 3)
    .map((el) => `${el.tagName.toLowerCase()}${el.className ? '.' + String(el.className).trim().split(/\s+/)[0] : ''} ${el.scrollWidth}>${el.clientWidth} (scrollable)`)
  return { scrollW: document.body.scrollWidth, innerW: innerWidth, wide, scrollers }
}

/** Print and judge one reflow measurement. Returns nothing; fails the run. */
function judgeReflow(where, r, pad) {
  const overflow = r.scrollW - r.innerW
  console.log(
    `  ${where.padEnd(pad)} page ${r.scrollW}px in a ${r.innerW}px viewport` +
    (overflow > 1 ? ` — 2D SCROLL of ${overflow}px` : ' — no horizontal scroll') +
    (r.wide.length ? `\n      past the edge: ${r.wide.join(', ')}` : '') +
    (r.scrollers.length ? `\n      scrolls inside itself: ${r.scrollers.join(', ')}` : '')
  )
  if (overflow > 1) fail(`[${where}] the page needs two-dimensional scrolling at 320px (${overflow}px over)`)
  if (r.wide.length) fail(`[${where}] content is past the edge at 320px and not reachable by scrolling its region: ${r.wide.join(', ')}`)
}

// ---- reflow: 320 CSS px is the WCAG 1.4.10 bar (400% on a 1280px window) ---
console.log('\n### reflow at 320px (WCAG 1.4.10)')
// All eight, not the three that were obvious. The narrower list was a sampling
// decision that hid a defect behind another one: the press of the third screen
// failed silently and the run printed the PREVIOUS screen's numbers under its
// name, so the one screen that could not be opened at 320px was the one whose
// result looked cleanest.
for (const view of VIEWS) {
  await page.setViewportSize({ width: 320, height: 640 })
  await page.waitForTimeout(600)
  if (!(await goTo(view))) {
    // Measuring now would describe whatever screen the failed press left on
    // display and print it under this view's name, which is worse than saying so.
    console.log(`  ${view.padEnd(16)} NOT REACHED at 320px, so nothing was measured`)
    fail(tileFailureLine(view))
    await page.setViewportSize({ width: 1680, height: 980 })
    await page.waitForTimeout(300)
    continue
  }
  await page.waitForTimeout(900)
  const r = await page.evaluate(reflowProbe)
  judgeReflow(view, r, 16)

  // A screen that keeps part of itself behind a tab can overflow only in that
  // tab, and the measurement above would never see it: the Tachograph screen's
  // register form and its six-column history table exist nowhere else. So each
  // tab is measured at 320px too, with the same probe and the same rules.
  const subRoot = SUB_TABS[view]
  if (subRoot) {
    const tabs = await subTabCount(subRoot)
    for (let i = 0; i < tabs; i++) {
      const clean = await subTabLabel(subRoot, i)
      if (!clean) continue
      const where = `${view} / ${clean}`
      if (!(await pressSubTab(subRoot, i))) {
        fail(`[${where}] the tab could not be pressed, so its reflow was not measured`)
        continue
      }
      await page.waitForTimeout(900)
      judgeReflow(where, await page.evaluate(reflowProbe), 22)
    }
    // Put the screen back on its first tab, so nothing after this measures a tab
    // it did not mean to.
    await pressSubTab(subRoot, 0)
    await page.waitForTimeout(400)
  }
  await page.setViewportSize({ width: 1680, height: 980 })
  await page.waitForTimeout(300)
}

// ---------------------------------------------------------------------------
// Is the thing being measured the thing that was built?
//
// A recorded failure mode in this repo: a JSX comment split a `&&` expression,
// the build failed, and the next measurement run silently measured the OLD image
// while looking green. The build hashes the bundle filename, so if the served
// index.html names a bundle that is not in dashboard/dist, these numbers describe
// a different build than the one in the working tree. Only checked when the target
// is loopback -- against a real deployment a mismatch is expected, not a defect --
// and only when dist/ exists, since a clean checkout has not built yet.
// ---------------------------------------------------------------------------
console.log('\n### the build under test')
const loopback = /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:|\/|$)/.test(URL)
const served = await page.evaluate(() =>
  [...document.querySelectorAll('script[src], link[href]')]
    .map((el) => el.getAttribute('src') || el.getAttribute('href'))
    .filter((u) => u && u.includes('/assets/'))
    .map((u) => u.split('/').pop())
    .sort()
)
if (!loopback) {
  console.log(`  ${URL} is not loopback: the bundle it serves is not this working tree's`)
} else if (!existsSync(join(DIST, 'index.html'))) {
  console.log(`  no ${DIST}/index.html: run \`npm run build\` for this check to mean anything`)
} else {
  const built = [...readFileSync(join(DIST, 'index.html'), 'utf8').matchAll(/(?:src|href)="([^"]*\/assets\/[^"]+)"/g)]
    .map((m) => m[1].split('/').pop())
    .sort()
  const missing = served.filter((f) => !built.includes(f))
  console.log(`  served: ${served.join(', ') || 'nothing'}`)
  console.log(`  dist:   ${built.join(', ') || 'nothing'}`)
  // Both stale is not detectable from here -- if the container and dist/ are from
  // the same older build the names agree. What this catches is the case that
  // actually happened: dist/ rebuilt, container not recreated.
  missing.length === 0
    ? console.log('  the served bundle is the bundle in dashboard/dist')
    : fail(`the served bundle is not the one in dashboard/dist: ${missing.join(', ')} is served and not built locally — rebuild and recreate the container before trusting these numbers`)
}

await browser.close()
console.log(findings ? `\nRESULT: ${findings} UI finding(s)\n` : '\nRESULT: all UI checks passed\n')
process.exitCode = findings ? 1 : 0
