/**
 * Negative controls for dashboard/scripts/audit-ui.mjs.
 *
 * Every rule in the audit gets a case that breaks it on purpose, because a guard
 * that cannot fail is decoration. Each case copies the real script, injects the
 * breaking change (a stylesheet, a DOM node, an env var, a patched view list),
 * runs it against the running stack and asserts that the expected FAIL line
 * appears AND that the process exited 1.
 *
 * The copies are written into dashboard/scripts/ so that `import 'playwright'`
 * resolves, and deleted at the end.
 */
import { spawn } from 'node:child_process'
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// Resolved from this file's own location, not hardcoded: dashboard/scripts/ -> dashboard/.
// A fixed path works on exactly one machine and silently fails everywhere else.
const DASH = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(DASH, 'scripts/audit-ui.mjs')
const ANCHOR = "await page.addInitScript(() => localStorage.setItem('gt.lang', 'en'))"
const original = readFileSync(SRC, 'utf8')
if (!original.includes(ANCHOR)) { console.error('anchor line is gone; fix the harness'); process.exit(2) }

// ---- injection helpers ----------------------------------------------------
const cssInject = (css) => `${ANCHOR}
await page.addInitScript(() => {
  const css = ${JSON.stringify(css)}
  const put = () => {
    if (!document.head) return setTimeout(put, 10)
    if (document.getElementById('neg-css')) return
    const s = document.createElement('style')
    s.id = 'neg-css'
    s.textContent = css
    document.head.appendChild(s)
  }
  put()
})`

// The probe goes into document.body, OUTSIDE the React root, so a re-render
// cannot take it away. Two things this got wrong to begin with, both silent:
// an init script runs before the document has a body OR a documentElement (both
// null), so `observe(document.documentElement, ...)` threw
// "parameter 1 is not of type 'Node'", the script died on its first statement and
// the probe was never inserted -- every control built on it "fired" by finding
// nothing to complain about. Waiting for the body and then observing it fixes it.
const domInject = (html) => `${ANCHOR}
await page.addInitScript(() => {
  const put = () => {
    if (!document.body) return false
    if (document.querySelector('.neg-probe')) return true
    const wrap = document.createElement('div')
    wrap.className = 'neg-probe'
    // Fixed so it is on screen whatever the page does, and never inside a
    // region the audit is measuring the geometry of.
    wrap.style.cssText = 'position:fixed;left:0;bottom:0;z-index:2147483647'
    wrap.innerHTML = ${JSON.stringify(html)}
    document.body.appendChild(wrap)
    return true
  }
  const start = () => {
    if (!put()) return setTimeout(start, 10)
    new MutationObserver(put).observe(document.body, { childList: true, subtree: true })
  }
  start()
})`

const patch = (from, to) => (src) => {
  if (!src.includes(from)) throw new Error(`patch anchor not found: ${from}`)
  return src.replace(from, to)
}

const CASES = [
  {
    name: 'contrast-miss',
    why: 'a text colour below its WCAG floor',
    expect: /contrast miss/,
    build: () => original.replace(ANCHOR, cssInject('* { color: #cfcfcf !important }')),
  },
  {
    name: 'clipped-text',
    why: 'text clipped out of its box',
    expect: /clipped out of their box/,
    // A stylesheet narrow enough to clip real copy also hides the switcher, and a
    // tile that cannot be pressed is a different finding. The probe reproduces the
    // defect itself instead: a box narrower than the line inside it, hidden.
    build: () => original.replace(ANCHOR, domInject('<div style="width:40px;overflow:hidden;white-space:nowrap">a piece of text longer than its box</div>')),
  },
  {
    name: 'small-target',
    why: 'a control below the 28x24 floor with no recorded exception',
    expect: /below the 28x24 floor and not a recorded exception/,
    build: () => original.replace(ANCHOR, domInject('<button style="width:18px;height:12px;padding:0">x</button>')),
  },
  {
    name: 'checkbox-not-excused',
    why: 'the checkbox allowance does not cover a box with no label around it',
    expect: /below the 28x24 floor and not a recorded exception/,
    build: () => original.replace(ANCHOR, domInject('<input type="checkbox" style="width:13px;height:13px;margin:0">')),
  },
  {
    name: 'unnamed-control',
    why: 'a control a screen reader would announce with no name',
    expect: /would announce with no name/,
    build: () => original.replace(ANCHOR, domInject('<button style="width:40px;height:40px"></button>')),
  },
  {
    name: 'reduced-motion-ignored',
    why: 'the animation still running under prefers-reduced-motion',
    expect: /still animates for/,
    build: () => original.replace(ANCHOR, cssInject('@media (prefers-reduced-motion: reduce) { .workspace, a.skip { animation-duration: .4s !important; transition-duration: .4s !important } }')),
  },
  {
    name: 'reflow-320',
    why: 'two-dimensional scrolling at 320px',
    expect: /needs two-dimensional scrolling at 320px/,
    build: () => original.replace(ANCHOR, cssInject('body { min-width: 700px !important }')),
  },
  {
    name: 'overflow-1680',
    why: 'the page scrolling sideways at 1680px',
    expect: /scrolls sideways by/,
    build: () => original.replace(ANCHOR, cssInject('body { min-width: 2000px !important }')),
  },
  {
    name: 'empty-region',
    why: 'a column region with no content',
    expect: /empty region/,
    build: () => original.replace(ANCHOR, cssInject('.workspace > * { display: none !important }')),
  },
  {
    name: 'column-collapsed',
    why: 'a column still in the DOM but left with no room to paint',
    expect: /the column has collapsed/,
    build: () => original.replace(ANCHOR, cssInject('.col-main { display: none !important }')),
  },
  {
    name: 'weight-ceiling',
    why: 'type painted above weight 600',
    expect: /type painted above weight 600/,
    build: () => original.replace(ANCHOR, cssInject('.pane *, .sidenav * { font-weight: 700 !important }')),
  },
  {
    name: 'no-focus-ring',
    why: 'a tab stop with no focus indicator',
    expect: /show no focus indicator/,
    build: () => original.replace(ANCHOR, cssInject('*:focus-visible { outline: none !important; box-shadow: none !important }')),
  },
  {
    name: 'focus-off-screen',
    why: 'a tab stop that is off screen when focused',
    expect: /are off screen when focused/,
    build: () => original.replace(ANCHOR, cssInject('.skip:focus { transform: translateY(-220%) !important }')),
  },
  {
    name: 'skip-link-not-first',
    why: 'the skip link no longer being the first tab stop',
    expect: /not the skip link/,
    build: () => original.replace(ANCHOR, cssInject('.skip { display: none !important }')),
  },
  {
    name: 'missing-tab',
    why: 'a switcher tile that is not there to press',
    expect: /there is no switcher tile/,
    build: () => patch("'Connect tracker']", "'Connect tracker', 'Probe view']")(original),
  },
  {
    name: 'subtab-unmeasured',
    why: 'a tab inside a screen that cannot be opened, so nothing behind it is measured',
    expect: /the tab could not be pressed/,
    build: () => original.replace(ANCHOR, cssInject('.tacho .subtabs button { pointer-events: none !important }')),
  },
  {
    name: 'subtab-target-floor',
    why: 'a control behind a tab, below the floor, that the screen-level sweep cannot see',
    expect: /below the 28x24 floor and not a recorded exception/,
    // The registry's row selects are the case: they are inside the Drivers tab,
    // where the view-level sweep never looked before the sub-tab pass existed.
    build: () => original.replace(ANCHOR, cssInject('.grid select { padding: 0 !important; font-size: 10px !important }')),
  },
  {
    name: 'unpressable-tab',
    why: 'a switcher tile that is present and cannot be pressed',
    expect: /could not be pressed/,
    build: () => original.replace(ANCHOR, cssInject('.sidenav__sub-item { pointer-events: none !important }')),
  },
  {
    name: 'no-shell',
    why: 'signing in and no shell ever appearing',
    expect: /no dashboard shell at/,
    env: { VERIFY_PASSWORD: 'definitely-not-the-password' },
    build: () => original,
  },
  {
    name: 'stale-bundle',
    why: 'measuring a container that is not the build in dist/',
    expect: /not the one in dashboard\/dist/,
    env: { AUDIT_DIST: '/tmp/negdist-stale' },
    build: () => original,
  },
  {
    name: 'no-dist',
    why: 'the staleness guard stands down, loudly, when there is nothing to compare',
    expect: /run `npm run build` for this check to mean anything/,
    expectExit: 0,
    env: { AUDIT_DIST: '/tmp/negdist-none' },
    build: () => original,
  },
]

// ---- a run that was interrupted leaves its copy behind ----------------------
for (const f of readdirSync(join(DASH, 'scripts'))) {
  if (/^\.neg-.*\.mjs$/.test(f)) rmSync(join(DASH, 'scripts', f), { force: true })
}

// ---- fixtures for the two env cases ---------------------------------------
mkdirSync('/tmp/negdist-stale', { recursive: true })
writeFileSync(join('/tmp/negdist-stale', 'index.html'), '<script src="/assets/index-OLDHASH.js"></script>')
rmSync('/tmp/negdist-none', { recursive: true, force: true })

const run = (name, src, env) =>
  new Promise((resolve) => {
    const file = join(DASH, 'scripts', `.neg-${name}.mjs`)
    writeFileSync(file, src)
    const child = spawn(process.execPath, [file], { cwd: DASH, env: { ...process.env, ...env } })
    let out = ''
    child.stdout.on('data', (d) => { out += d })
    child.stderr.on('data', (d) => { out += d })
    child.on('close', (code) => {
      rmSync(file, { force: true })
      resolve({ code, out })
    })
  })

// Two at a time by default. Four was tried and is too many: each case is a full
// audit of a live dashboard with a map in it, and under that much parallel load
// runs started failing before the login screen for reasons that had nothing to do
// with the rule under test. CONTROLS_JOBS and CONTROLS_ONLY exist to run one case
// while debugging it, not to make the suite look faster than it is.
const only = (process.env.CONTROLS_ONLY || '').split(',').map((s) => s.trim()).filter(Boolean)
const selected = only.length ? CASES.filter((c) => only.includes(c.name)) : CASES
if (only.length && selected.length !== only.length) {
  const unknown = only.filter((n) => !CASES.some((c) => c.name === n))
  console.error(`no such control: ${unknown.join(', ')}`)
  process.exit(2)
}
const limit = Number(process.env.CONTROLS_JOBS || 2)
const queue = [...selected]
const results = []
const worker = async () => {
  while (queue.length) {
    const c = queue.shift()
    let res
    try {
      res = await run(c.name, c.build(), c.env || {})
    } catch (err) {
      results.push({ ...c, ok: false, detail: `harness: ${err.message}` })
      continue
    }
    const exitOk = res.code === (c.expectExit ?? 1)
    const lineOk = c.expect.test(res.out)
    const failLine = (res.out.match(/^\s+FAIL: .*$/m) || ['(none)'])[0].trim()
    results.push({
      ...c, ok: exitOk && lineOk,
      detail: exitOk ? (lineOk ? failLine : `exit ${res.code} but no line matching ${c.expect}`) : `expected exit ${c.expectExit ?? 1}, got ${res.code}`,
    })
  }
}
await Promise.all(Array.from({ length: limit }, worker))

results.sort((a, b) => selected.findIndex((c) => c.name === a.name) - selected.findIndex((c) => c.name === b.name))
console.log('\nnegative controls for scripts/audit-ui.mjs\n')
for (const r of results) {
  console.log(`${r.ok ? '  ok  ' : ' FAIL '} ${r.name.padEnd(24)} ${r.why}`)
  console.log(`         → ${r.detail}`)
}
const bad = results.filter((r) => !r.ok)
console.log(`\nRESULT: ${results.length - bad.length}/${results.length} controls fired\n`)
process.exit(bad.length ? 1 : 0)
