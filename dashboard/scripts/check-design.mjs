#!/usr/bin/env node
/**
 * Design invariants that a stylesheet cannot state about itself.
 *
 * `npm run audit:ui` measures a RUNNING stack: it walks the real DOM and reads
 * back what is actually painted, which is the stronger check. This is the other
 * half — the rules that can be decided from the source and the built bundle,
 * with no browser, no container and no seeded data, so they can run in CI on
 * every push. Several of these were true only because somebody remembered them.
 *
 *     npm run build && node scripts/check-design.mjs
 *
 * Rules:
 *   1. every custom property used as a text colour clears 4.5:1 (3:1 for the
 *      graphical token) on BOTH light surfaces it can sit on;
 *   2. nothing paints above weight 600, and the cap on <strong>/<b>/<th> ships;
 *   3. no raw `font-size: <n>px` — every size resolves through a token;
 *   4. a `:focus-visible` ring exists;
 *   5. a `prefers-reduced-motion` block exists;
 *   6. the vendored font is referenced by the built CSS and present on disk.
 *
 * What it deliberately does NOT police: the status values used as shapes
 * (--moving, --idle, --alert, --offline, --never, --info). Those are map dots and
 * fills, and #f2b705 amber on white is 1.7:1 by design — the reason a separate
 * `-ink` set exists. Asserting 3:1 on them would be asserting the opposite of the
 * documented decision. Contrast of *painted* status text is covered by audit:ui.
 *
 * Paths can be redirected with DESIGN_CSS / DESIGN_DIST, which is how this
 * script's own failure modes are tested rather than taken on trust.
 */
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')
const CSS_PATH = process.env.DESIGN_CSS || join(ROOT, 'src/styles.css')
const DIST = process.env.DESIGN_DIST || join(ROOT, 'dist')

let failures = 0
const ok = (m) => console.log(`  ok:   ${m}`)
const fail = (m) => { failures++; console.log(`  FAIL: ${m}`) }

// ---------------------------------------------------------------------------
// WCAG contrast, from the primaries
// ---------------------------------------------------------------------------
const lin = (v) => {
  const c = v / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}
function luminance(hex) {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? [...h].map((c) => c + c).join('') : h
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16))
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}
const contrast = (a, b) => {
  const [la, lb] = [luminance(a), luminance(b)]
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

const css = readFileSync(CSS_PATH, 'utf8')

// ---------------------------------------------------------------------------
// 1. text contrast
// ---------------------------------------------------------------------------
console.log(`\nstyles.css: ${CSS_PATH}`)
const rootBlock = css.slice(css.indexOf(':root {'), css.indexOf('}', css.indexOf(':root {')))
const token = Object.fromEntries(
  [...rootBlock.matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{3,8})\s*;/g)].map((m) => [m[1], m[2]])
)

// `color:` only -- the lookbehind is what keeps border-color, background-color and
// outline-color out of a contrast rule that is about text.
const textTokens = [
  ...new Set([...css.matchAll(/(?<![-\w])color:\s*var\((--[\w-]+)\)/g)].map((m) => m[1])),
].sort()

const surfaces = ['--panel', '--bg'].filter((t) => token[t])
if (surfaces.length < 2) fail('could not read the two light surfaces from :root')

for (const name of textTokens) {
  const value = token[name]
  if (!value) continue

  // --brand-ink is white ON the accent, so it is judged against the accent.
  if (name === '--brand-ink') {
    const ratio = contrast(value, token['--brand'])
    ratio >= 4.5
      ? ok(`${name} ${value} on --brand ${token['--brand']}  ${ratio.toFixed(2)}:1`)
      : fail(`${name} is ${ratio.toFixed(2)}:1 on --brand ${token['--brand']} (needs 4.5)`)
    continue
  }

  // --icon is a graphical object: WCAG asks 3:1 of it, not 4.5.
  const need = name === '--icon' ? 3.0 : 4.5
  const measured = surfaces.map((s) => [s, contrast(value, token[s])])
  const worst = measured.reduce((a, b) => (b[1] < a[1] ? b : a))
  worst[1] >= need
    ? ok(`${name} ${value} clears ${need}:1 on both surfaces (worst ${worst[1].toFixed(2)}:1 on ${worst[0]})`)
    : fail(
        `${name} ${value} is ${worst[1].toFixed(2)}:1 on ${worst[0]} (needs ${need}) — ` +
          measured.map(([s, r]) => `${s} ${r.toFixed(2)}`).join(', ')
      )
}

// ---------------------------------------------------------------------------
// 2. weight ceiling
// ---------------------------------------------------------------------------
const weights = [...css.matchAll(/font-weight:\s*([^;]+);/g)].map((m) => m[1].trim())
const overCeiling = weights.filter((w) => /^(bold|bolder)$/.test(w) || (parseInt(w, 10) > 600))
overCeiling.length === 0
  ? ok(`no weight above 600 (${weights.length} declarations, max ${Math.max(...weights.map((w) => parseInt(w, 10) || 0))})`)
  : fail(`weights above the 600 ceiling: ${[...new Set(overCeiling)].join(', ')}`)

// ---------------------------------------------------------------------------
// 3. no raw font sizes
// ---------------------------------------------------------------------------
const rawSizes = [...css.matchAll(/font-size:\s*[0-9.]+px/g)].map((m) => m[0])
rawSizes.length === 0
  ? ok('no raw font-size in px: every size resolves through a token')
  : fail(`raw font sizes that bypass the scale: ${[...new Set(rawSizes)].join(', ')}`)

// ---------------------------------------------------------------------------
// 4 & 5. focus ring and reduced motion
// ---------------------------------------------------------------------------
css.includes(':focus-visible')
  ? ok(':focus-visible ring is declared')
  : fail('no :focus-visible rule: controls are operable but not visibly reachable')
css.includes('prefers-reduced-motion')
  ? ok('prefers-reduced-motion is honoured')
  : fail('no prefers-reduced-motion block: motion cannot be switched off')

// ---------------------------------------------------------------------------
// 6. the vendored font, and the built bundle as the thing that actually ships
// ---------------------------------------------------------------------------
for (const file of ['manrope-latin.woff2', 'manrope-latin-ext.woff2', 'OFL.txt']) {
  const p = join(ROOT, 'public/fonts', file)
  existsSync(p) ? ok(`vendored font asset present: ${file}`) : fail(`missing public/fonts/${file}`)
}
css.includes('@font-face') && css.includes('Manrope')
  ? ok('styles.css declares the vendored @font-face')
  : fail('styles.css no longer declares @font-face for Manrope')

if (!existsSync(DIST)) {
  fail(`no build output at ${DIST} — run \`npm run build\` first, these are rules about what ships`)
} else {
  const assets = readdirSync(join(DIST, 'assets')).filter((f) => f.endsWith('.css'))
  const built = assets.map((f) => readFileSync(join(DIST, 'assets', f), 'utf8')).join('\n')
  const capShips = /strong,b,th\{font-weight:600\}|strong, b, th\s*\{\s*font-weight:\s*600/.test(built)
  capShips
    ? ok('the built CSS carries the <strong>/<b>/<th> weight cap')
    : fail('the built CSS is missing the strong/b/th cap: <strong> will render at 700')
  built.includes('/fonts/manrope-latin.woff2')
    ? ok(`the built CSS references the vendored font (${assets.join(', ')})`)
    : fail('the built CSS does not reference the vendored font: Vite did not copy public/')
}

console.log(failures ? `\nRESULT: ${failures} design invariant(s) violated\n` : '\nRESULT: all design invariants hold\n')
process.exit(failures ? 1 : 0)
