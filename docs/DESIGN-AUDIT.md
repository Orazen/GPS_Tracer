# Design audit — the 29 AI-design tells

Audit of the fleet dashboard ([`dashboard/src`](../dashboard/src)) against the 29
tells in the *Remove AI Design Slop* checklist, with the line that decides each
one.

**Which job this is.** The checklist does two jobs: it is a pass/fail checklist
for anything you make, and it is a default *subject* for a graphic when the user
supplies no direction of their own. This audit is the **first** job. The subject
here is not a poster — it is a control surface a dispatcher stares at for eight
hours — so several tells that govern a fixed canvas (18, 19, 20, 21, 25) do not
have a referent. Those are marked **n/a** with the reason, not marked pass.

**Citations.** Line numbers into `styles.css` are from the revision each verdict
was written against. The file grows, so a selector or a token name is the stable
reference and the number is a hint -- they have already shifted once, when the
`@font-face` block was added at the top.

**How each verdict was reached.** Not by reading the stylesheet and forming an
impression. Three kinds of evidence:

1. **Rendered computed styles**, read from the live dashboard in a browser at
   1680×980 — the actual `getComputedStyle` output of the running app, plus a DOM
   sweep for every element carrying a coloured border of 2px or more, plus a
   census of every font size and weight actually painted.
2. **The deployed bundle**, fetched from the running container.
3. **The project's own acceptance suite** (`dashboard/scripts/verify.mjs`,
   `npm run verify`), which exercises all six tabs, both languages and
   console/network health.

Where a rule could not be exercised by real data, it was probed by applying the
class to a live element and reading the resolved style back. Those cases are
called out in *Not verified* below rather than counted as observed.

The layout claims were read twice: at 1680×980, where the fleet screen renders,
and again at 800×700, because the acceptance suite only ever runs at 1680 and the
narrow breakpoints would otherwise be untested. At 800 the detail column is
`display: none`, the nav grid drops to two columns, `--right-w` falls to `0px` so
the map's own controls return to the edge, the roster stays six rows, and the
18px title stays 18px.

**Second pass: the design is now matched to a reference console.** The dashboard
was rethemed from a dark console to the light operator console at
`https://demo-forguard.gps-trace.com/`. That work is recorded in
*Matched against the reference console* below, and where it changed how a tell is
satisfied, the row says so.

**Third pass: the frame, as well as the palette.** The second pass matched the
reference's colours and its type scale. This one matches its *geometry* — the
panel column, the tile grid, the title bar, the body, and the anatomy of a unit
card down to its separators — because a console that shares a palette with the
one it replaces but not its proportions still reads as a different product. Every
number is in *Third pass: the reference's own geometry* at the foot of this file,
together with what was deliberately left un-cloned and why.

Three numbers the earlier sections quote have since changed, and those sections
are left as they were written rather than edited — they are the record of a
revision, and this file is most useful when it can still be read against one.
Reconciled here, in one place:

| Earlier sections say | Now |
|---|---|
| six or seven tabs | eight tiles: the seven destinations plus Alerts, which became a screen of its own |
| the nav strip is 100px | 104px, because 2 × 48px of tiles plus 4px of padding needs 104 and the reference's declared 100 overflows by 4 |
| the roster renders `.trow` rows, styling `.trow.s-offline` and so on | `li > .unitcard`, styling `.unitcard.s-offline` and so on |
| names clean on 7 of 7 screens, contrast on 7 of 7 | 8 of 8 |
| the other workspace screens "still use their own layouts", "not yet the section-row format" (third pass) | all five workspace screens are groups of section rows — see the fourth pass below |
| the unit card's action row is three tiles (third pass) | four: Follow moved out of the card's head into the row |
| the reference's four semantic colours are all "below 4.5:1 for a label" (third pass) | two of those numbers were wrong and one of the four is adopted as a shape — see "The reference's four semantic colours" below |

`npm run verify` and `npm run audit:ui` both navigate the switcher now, so both
carry the new count: verify asserts 8 tiles in the grid and 2 controls in the
strip's right column, and the audit's view list gained `Alerts`.

---

## The 29 tells

| # | Tell | Verdict | Evidence |
|---|---|---|---|
| 1 | Exactly one accent, used with discipline | **Fixed** | The sheet had one `--accent: #10b981` shared by *chrome* and by *moving* — a selected tab and a moving truck were the same green. Now `--brand` (`styles.css:42`) is chrome only, and status owns its own hexes (`styles.css:49-55`). A selected nav tile is `var(--brand)` (`styles.css:228`); no status colour is ever used for chrome. |
| 2 | The accent is the subject's colour, never your house palette | **Fixed** | The palette *was* the Tailwind default ramp (`#10b981` emerald-500, `#ef4444` red-500, `#f59e0b` amber-500, `#9ca3af` gray-400, `#1f2937` gray-800) plus GitHub's `#e6edf3`. Nothing about European road freight reads in those numbers. The chrome and the greys are now the reference console's own tokens — `#0058ec`, `#005693`, `#f1f1f1`, `#19191c`, `#5c5c5c`, `#9e9e9e`, `#757575` (`styles.css:30-46`) — and status keeps the road-signing values, sampleable at a glance from any EU road sign (`styles.css:49-63`, mirrored in `lib/palette.js`). |
| 3 | Colour on the glyphs only; never a fill, tint or pill behind a word | **Fixed** | `.tag`, `.sev*` and `.act*` carried tint fills. They are now glyph colour + hairline, fill transparent (`styles.css:494-498`, `609-616`, `626-635`). Rendered: `.sev-ok` background `rgba(0,0,0,0)`, `.badge.s-offline` background `rgba(0,0,0,0)`. The one fill left behind a word is the **selected nav tile**, and it is neutral grey `#f1f1f1`, not a hue (`styles.css:228`) — see *Deliberate exceptions*. |
| 4 | Never two accented phrases, never a generic word | **n/a** | Governs a sentence rendered as a graphic. A dashboard has no accented prose. |
| 5 | Never the purple-to-blue gradient | **Fixed** | `.logo` was `linear-gradient(135deg, var(--accent), #059669)` and the login screen had a radial glow. Both gone: the mark is flat `background: var(--brand)` (`styles.css:157`). Rendered: `backgroundImage: "none"`, `backgroundColor: rgb(0,88,236)`. The geofence `ZONE` list also shipped `#a855f7` (Tailwind purple-500) and still carried it through the retheme's first draft; the six zone hues are now chosen so that none of them is purple and none reuses a status hex (`lib/palette.js`). |
| 6 | Two typefaces, capped there | **Pass** | One UI stack (`body` in `styles.css`) plus one monospace for typed values — IMEI, coordinates, card numbers (`.mono`). The stack is now `Manrope, system-ui, -apple-system, 'Segoe UI', sans-serif`, with the face vendored as two woff2 files; it was the reference's own Roboto chain until the third audit below, which forbids that face. |
| 7 | One type scale in real numbers, never big/medium/small | **Fixed** | Now one declared scale, `--t-xs`…`--t-3xl` — 11/12/14/16/18/20/24 (`styles.css:74-82`) — and every size references a token. Probe found the last off-scale value: a classless `<select>` rendering at the browser default **13.3333px**, a size the sheet never declares. Closed at the class level, not the instance (`styles.css:102`). The sheet now contains **no raw `font-size: <n>px` declaration at all** — `grep` for one returns nothing, so every size in the file resolves through a token and a step cannot be added by accident. Rendered after the retheme: exactly **11/12/14/16/18** on the fleet screen, no off-scale value anywhere, and no weight above **600**. |
| 8 | Monospace for a string you type or an interface you are drawing | **Pass** | `.mono` is used for identifiers and coordinates, never as decoration (`styles.css:123`, `269`). |
| 9 | Italic only where the borrowed world uses it | **Pass** | `.phint` explicitly sets `font-style: normal` (`styles.css:268`); no decorative italics anywhere in the sheet. |
| 10 | The coloured strip down a card edge | **Fixed** | Three real instances: `.warnpanel`, `.rows li.sevli-breach` and `.trow` all carried `border-left: 3px solid <colour>`. All removed. `.warnpanel` is now a full border + faint wash (`styles.css:603`); a breach is marked by weight and its severity chip (`styles.css:622`); `.trow` has no side border at all (`styles.css:362`). A DOM sweep for any element with a coloured side border ≥2px returns **empty**. |
| 11 | Emoji standing in for drawn icons | **Fixed** | The status bar read `count + word` for online, moving, idle and offline, and `count + ⚠` for alerts — an emoji standing in for the missing label. Replaced with a localised word (`App.jsx:218-227`), so all five stats read the same way; the deployed bundle contains `in allarme` and **zero** `⚠`. The new nav tiles raise the same question in reverse, and are answered by drawing: six hand-written SVG paths on one 20px grid, one stroke width, no icon font (`components/Icon.jsx`). |
| 12 | The loop arrow | **n/a** | No loop arrows in the product. The arrows that exist are plain ones — `Impostazioni → Gestione utenti` in the i18n strings, `2026-10-05 → 2026-10-11` in the tachograph — which this tell explicitly endorses. The nav uses a clock for history rather than the refresh-loop glyph, precisely so this stays true after adding icons. |
| 13 | A motivational band across the bottom | **n/a** | No such band. |
| 14 | A bar or meter with no real quantity behind it | **n/a** | Every KPI figure is a computed value; there are no decorative meters. |
| 15 | Stock hands on a keyboard, and the robot | **n/a** | The dashboard ships no photography or stock imagery. |
| 16 | Every row on a dense list occupies exactly one line | **Pass** | `.rows li`, `.alist li` and `.trow` are single-line, with `text-overflow: ellipsis` on the variable content (`styles.css:483-487`, `402`, `377`). |
| 17 | Text evenly weighted; no orphan word, no hard break doing the wrapping | **Fixed** | The driver name was capped at 62px, so a real name clipped to `Gius…` and was then faded to 70% opacity on top of that. Widened and un-faded (`styles.css:377`); the retheme took it to 92px. Rendered: the rule resolves to `maxWidth: 92px`. |
| 18 | Dead space is a content shortage, not a layout fault | **n/a** | The shell is now a full-bleed map with floating panels rather than a fixed grid (`styles.css:187-197`), so there is still no fixed canvas with dead space to move around. |
| 19 | One full sentence per cell | **n/a** | Cells hold values, not prose. |
| 20 | A device starts and finishes somewhere, never mid-air | **n/a** | Applies to a drawn diagram. Paths and trails here are data, drawn from recorded coordinates. |
| 21 | Arrowheads meet the line they belong to | **n/a** | No drawn connectors. |
| 22 | The topic is visible in the drawing, not only in the title | **Pass** | The map draws the fleet, the roster carries a state dot per truck, and the nav tiles are drawn shapes rather than words in a box — cover the labels and the pin, the clock, the fence, the chart, the disc and the sliders still say what they are (`styles.css:362`, `224`, `components/Icon.jsx`). |
| 23 | Never reduce the type size to rescue a fit | **Fixed** | The sheet had a 10px floor. Raised to an 11px minimum (`styles.css:74`), and the KPI columns are sized for the label rather than shrinking the label to fit (`styles.css:460-467`). The narrow-window rules drop the detail column at 1100px and halve the nav grid at 860px rather than touching a size, and the title keeps its 18px down to the narrowest breakpoint (`styles.css:668-684`). |
| 24 | Vary the box sizes; identical rectangles say none of them matters | **Fixed** | Every truck row was the same weight and height, so nothing signalled which truck mattered. Prominence now follows state: 600 for a breach, 600 plus the accent for the selected row, 400 plus muted for offline (`styles.css:379-381`). Rendered: selected name `600`, offline names `400`. Caps at 600 rather than 700 because the reference console never goes past 500 in chrome, and a 700 beside a 500 reads as two typefaces when it is one. |
| 25 | Nobody reads the small text at feed size | **n/a** | This governs a graphic competing in a feed. The distinction survives the retheme: this is a dispatch console read at 60cm in an office, where 11–12px secondary text against 14px primary is the correct hierarchy, not a failure to prioritise. |
| 26 | A clean checklist will pass a build that is still not good | **n/a** | A process warning, not a property of the artifact. |
| 27 | Never ship the first version | **n/a** | Process. Applies to the work rather than to the sheet, and it did: the retheme below is the second version of this screen. |
| 28 | Four variants means four ideas | **n/a** | Process; no variant set was produced. |
| 29 | One template reused for everybody | **n/a** | Process; concerns templated output. |

**Tally (all 29 accounted for):** **10 fixed** (1, 2, 3, 5, 7, 10, 11, 17, 23,
24) · **5 already correct** (6, 8, 9, 16, 22) · **14 n/a for this medium** (4,
12-15, 18-21, 25-29).

---

## Matched against the reference console

The layout, the surfaces and the type scale were taken from the operator console
at `https://demo-forguard.gps-trace.com/` (Vue 2 + Quasar + Leaflet). Its design
was read the only way it can be read without pixels — by walking its live DOM and
reading `getComputedStyle` — and then reproduced. Every value below is a
**measurement**, not an impression:

| Form | Reference | This dashboard | Where |
|---|---|---|---|
| Accent | `#0058ec` | `#0058ec` | `styles.css:42`; rendered on the active nav tile `rgb(0,88,236)` |
| Count badge | `#005693`, white text, pill | same | `styles.css:212`; rendered `rgb(0,86,147)` |
| Page / panel grey | `#f1f1f1` | `#f1f1f1` | `styles.css:31`; rendered `rgb(241,241,241)` |
| Card surface | `#ffffff` | `#ffffff` | `styles.css:33` |
| Primary text | `#19191c` | `#19191c` | `styles.css:36`; rendered `rgb(25,25,28)` |
| Secondary text | `#5c5c5c` | `#5c5c5c` | `styles.css:37`; rendered `rgb(92,92,92)` |
| Muted text | `#9e9e9e` | ~~`#9e9e9e`~~ **`#5f686f`** — diverges on purpose, see the fourth audit | `--muted` |
| Inactive icon | `#757575` | `#757575` | `styles.css:39`; rendered `rgb(117,117,117)` |
| Separator | `rgba(25,25,28,.12)` | same | `styles.css:34` |
| Elevation | `rgba(55,71,79,.08) 0 4px 4px` + `0 1px 0` | same | `styles.css:92-93` |
| Corner radius | 12px cards, 12px pills, 50% circles | same | `styles.css:88-91` |
| Type face | Roboto | **Diverges on purpose:** Manrope, vendored (`@font-face` at the top of `styles.css`) | the third audit, below |
| Base size | 14px | 14px | rendered `14px` |
| Title | 18px / 500, centred | same | `styles.css:241`; rendered `18px/500` |
| Card heading | 14px / 500, secondary 12px / 400 | 14px / 500, secondary 12px / 400 | `styles.css:372-373`; rendered `14px/600` when selected, `12px` secondary |
| Page inset | 16px all round | 16px all round | `styles.css:190` |
| Left column | 450px, floating | 450px, floating | `styles.css:192`; rendered `x:16 w:450` |
| Map | full-bleed behind everything | full-bleed behind everything | `styles.css:189`; rendered `1680×980` at `0,0` |
| Left column shape | white header card, title strip, grey rounded list body | same | `styles.css:205`, `240`, `340`; rendered `#fff / 12px`, then `46px`, then `#f1f1f1 / 0 0 12px 12px` |
| List items | white cards, 12px radius, inside the grey panel | same | `styles.css:362`; rendered `x:28 w:426` inside a `450px` panel |

Two deliberate divergences, both recorded rather than hidden:

- **A middle column between the two panels.** The shell is a three-column flex
  row (`styles.css:190-197`) and the fleet screen renders the middle one empty.
  Without it the detail column sat shoulder-to-shoulder with the nav column and
  the console read backwards — the right-hand panel belongs on the right edge,
  where the reference puts its own control stack.
- **The map's controls are offset by the detail column's width**
  (`styles.css:305`, `--right-w` at `styles.css:86`). MapLibre only knows the four
  corners of its own canvas, and on a full-bleed map the top-right corner is
  underneath the detail panel: the buttons are there, invisible, and the first
  zoom click lands on the panel instead.

---

## What changed

| File | Change |
|---|---|
| `src/styles.css` | Rewritten onto the reference's light language: tokens split into chrome vs status with a shape value and an on-white glyph value per meaning; one asserted type scale of 11/12/14/16/18/20/24; full-bleed map with floating panels replacing the four-column grid; nav tile grid, title strip and grey list body; 12px corners and the reference's elevation throughout; four coloured edge strips removed; tint fills removed; gradient logo and login glow flattened. |
| `src/lib/palette.js` | Rewritten to the reference's tokens. Still the single source for the colours CSS cannot reach — MapLibre paint properties and inline SVG. Also now carries a separate `INK` set, because `#f2b705` amber on white is 1.7:1 and unreadable at 11px, and darkening the map dot instead of the glyph would turn it into mud. |
| `src/components/Icon.jsx` | **New.** Six hand-drawn 20px SVG paths on one grid with one stroke width for the nav tiles. No icon font, no emoji, no clip-art. |
| `src/App.jsx` | Shell restructured: nav tile card, centred title strip, floating roster, floating status bar, floating detail column, and a floating workspace for the five non-map screens. Settings lifted out of the 300-line render function into its own component. |
| `index.html` | Favicon and `theme-color` moved to the light palette, so the browser chrome does not flash near-black over a white app. |
| `src/lib/status.js` | Re-exports the palette instead of declaring its own hexes. |
| `src/lib/geofence.js` | Zone colours come from the palette; the purple is gone. |
| `src/components/GeofenceManager.jsx` | Zone swatch list points at the shared palette. |
| `src/components/FleetMap.jsx` | Map paint properties read the shared palette. |
| `src/i18n/index.js` | `inAlert` added to both locales. |

The loop that proves it: `docker compose -p gpstracer-dev build dashboard` →
recreate → `npm run verify` → **`RESULT: all checks passed`**, exit 0, with 0
`FAIL` lines and no console errors or failed requests — on the image the healthy
container is actually running. The deployed bundle was then fetched back out of
that container and checked for the new tokens: `#0058ec`, `#005693`, `#f1f1f1`,
`#19191c`, `#9e9e9e`, `#757575`, `#1fa651` and the Roboto stack are all present,
and every one of the seven old dark-surface hexes appears **zero** times. (That
check was made against this revision. The face was later replaced with a vendored
Manrope -- see the third audit below; every colour above still holds.)

---

## Deliberate exceptions

Not oversights — decisions someone can argue with:

- **The selected nav tile has a grey fill behind its label** (`styles.css:228`).
  Tell 3 says never a fill, tint or pill behind a word. The fill is `#f1f1f1` —
  the page grey, a neutral, not a hue — and it is what makes six destinations
  scannable without reading them. The reference console distinguishes its active
  tile by glyph colour alone; with a label under every icon that is too weak to
  find at a glance, so the fill carries selection and the accent stays on the
  glyph and the label. Colour is still never behind a word.
- **`.subtabs button` keeps a 2px bottom border** (`styles.css:468-473`). Tell 10
  targets a decorative colour bar down a card edge; this is a state indicator
  that is `transparent` until the tab is active, which is how tabs work
  everywhere. The nav tiles have no underline at all.
- **Two whole-panel fills.** `.notice` and `.pblock.warn` keep a faint wash
  (`styles.css:594`, `257`). Tell 3 is about a pill behind a word; these are
  full-width callouts with a full border and a paragraph inside, where the wash
  is what separates "read this before you read the numbers" from ordinary body
  copy. Both are commented at the point of use.
- **Equal KPI boxes.** `.kpis` deliberately keeps equal widths
  (`styles.css:460-467`) against tell 24, because the KPI tiles genuinely are
  peers — nothing outranks anything else. Tell 24 is applied where there *is* a
  ranking to express (the truck roster).
- **`✓` / `✗` as tachograph KPI values** (`Tacho.jsx`). These are the one
  judgement call I did not act on, and the retheme did not change that. They are
  monochrome text glyphs with no emoji variation selector, and they *accompany* a
  label rather than replacing one — unlike the `⚠`, which was standing in for a
  missing word. Drawing them as SVG is the "draw the icon" reading; I left them
  because a text mark on a value is a legitimate pattern and changing it is a
  real design decision, not a cleanup. Flagging it so it can be decided
  deliberately.
- ~~**No webfont is fetched.**~~ **Superseded.** The reason this exception
existed was that a pixel-identical render to the reference meant either
self-hosting the font files or taking a blocking third-party request on every
load, and this dashboard has to come up on a locked-down office network and on a
van's tethered tablet. Self-hosting removes that objection: the font is now
vendored, so nothing is fetched from a third party and nothing blocks. What remains
true of the original note is its diagnosis of the old stack — **Roboto is not
installed on macOS or Windows**, so on any ordinary laptop the console was already
rendering in `Helvetica Neue` and only the greys, sizes, weights and geometry
matched the reference. The letterforms never did. That is now stated rather than
implied, and the vendored face is the first one this console has actually
rendered on purpose.

---

## Not verified

Stated plainly rather than folded into a pass:

- **The reference itself was read as computed styles, not as pixels.** Screenshots
  cannot be composited in this environment, so the reference's *appearance* was
  reconstructed from `getComputedStyle` output, DOM geometry and its own
  stylesheet values. Its measured tokens are reproduced exactly and verified by
  reading our own resolved styles back; a claim about the reference's overall
  look beyond those numbers is not something this environment can check.
- **The alert/moving/idle roster variants were probed, not observed.** The demo
  fleet is six offline trucks, so only `s-offline` renders from live data. The
  alert, moving and idle row styles were measured by applying the class to a
  live row and reading the resolved style, then restoring it. The CSS is
  verified; the rendered appearance with real data is not.
- **`.tdrv` never renders in the demo.** No demo device has a driver attribute,
  so the 92px driver-name fix was measured the same way — by appending an
  element with the class, reading `maxWidth: 92px`, and removing it. The suite
  does separately assert that the driver-name switch is present and **off by
  default** (Art. 4 L.300/1970), and that still passes.
- **No screenshots.** This environment cannot composite webview frames, so every
  visual claim above is computed style and DOM, not pixels. Reading resolved
  `getComputedStyle` is stronger than a screenshot for these specific tells, but
  it is not the same as looking at it.
- **One flaky run, previously.** An earlier post-change `npm run verify` failed
  section 9 with `net::ERR_NETWORK_IO_SUSPENDED` on one request — Chrome
  suspending network I/O, not an app error. It passed on re-run and on every run
  after, including both runs against the retheme. Recorded here because a
  filtered tail can hide it.

## Unrelated working-tree change

`scripts/create-admin.sh` is modified in the working tree (em-dashes replaced
with hyphens in its comments). That edit is not part of this audit, was not made
here, and was left untouched.

---

# Second artifact: the bench sheet

And now a different problem, with a different design answer.

## The read

*Reading this as: a bench sheet a fleet technician prints and tapes to the wall,
and reads on a phone while standing at a vehicle. Not a marketing page and not
documentation prose: it has to make a silent, six-stage failure mode visible at a
glance, and survive being printed on an office laser printer with the colour
cartridge empty.*

The design skill applied is **`design-taste`** (`madebymustafa/design-taste`) —
the core rule set, not one of its genre packs. Two of those packs were read first
(`editorial-minimal`, `dark-tech`) and deliberately rejected: this sheet hangs
next to the dashboard, so shipping it in a Swiss-broadsheet palette or in a
dark developer console would have made the two artifacts look like two products.
The core rules are the transferable part; the palette is this product's.

## What those rules changed

| Rule | What it did here |
|---|---|
| Read the room, declare it | Above. The audience is a technician at a vehicle, not a reader browsing a site. |
| Typography is the highest-value discipline | Two voices, held strictly apart: a tight sans display at `clamp(2rem, 4.6vw, 3.4rem)` / `-0.035em` for the title, and monospaced caps at `0.12em` for every label, hop number, port and key. Nothing in between. |
| One neutral + one accent | Ink `#19191c` on the dashboard's `#f1f1f1`, with `#0058ec` used **once** as a meaning: the data path. Every hop number is ink; the one accent marks the flow that runs continuously. |
| Asymmetry reads as designed | The masthead is a 7/5 split — title left, standfirst bottom-aligned right, then a hairline meta row of five measurements. No centred hero. |
| Rows over cards | The six hops are table rows on hairlines, not six rounded cards. The three handshake states are one bordered strip of three columns, not cards. |
| Depth from structure | Hairlines only: zone bands, section rules, table rows, `figcaption`. The single non-flat surface is the command block, and it is a dark terminal panel because a command *is* a dark panel. |
| No emoji, no gradients, no webfont | None. The whole sheet is one file: no external asset, no JavaScript, no font request — it opens off a USB stick on an offline laptop. |
| Motion: discipline | There is none. A printed sheet cannot animate, and a setup guide that animates is a setup guide being read instead of followed. |

## The diagram's conventions

A diagram is where this kind of document usually fails, so the choices are
stated rather than left to taste:

- **Solid line = data on the running system. Dashed line = setup, done once.**
  The one thing a reader must not confuse is "the tracker sends positions" with
  "somebody sent four SMS". Both are lines to the same box.
- **Zone bands, not boxes, for boundaries** — who operates that segment (bench,
  vehicle, public internet, this server, dispatcher). Boundaries are hairlines;
  connectors are the only elements with arrowheads and weight.
- **`TCP` and `5013` as two mono words either side of the connector**, on the one
  port that matters, rather than `:5013` buried in a sentence. The port inside
  the container is 5013; the published host port is whatever `H02_PORT` says, and
  the sheet says which is which because that confusion is §7.8.
- **Direction of initiation is explicit.** The tracker opens the connection; the
  carrier NAT band says there is no route back in. That is the fact that makes a
  fleet of SIMs work at all, and it is exactly what a "server talks to tracker"
  mental model gets wrong.
- **Numbered hops shared with the table below.** The diagram carries the numbers;
  the table carries the symptoms. A reader who sees `Unknown device` finds row 4
  and knows which line to look at.

## Deliberate exceptions

- **Colour is never the only signal.** Status colours appear only on the three
  handshake states, always beside the word (`registered`, `reached the server`,
  `positioned`), and the same distinctions are carried by the labels in print.
- **The bench sheet states its own limits on the sheet.** Section 05 says in the
  artifact what `UNIMPLEMENTED.md` says in the register: no physical unit has ever
  connected. A setup guide that reads as "this works" is the failure mode this
  project keeps guarding against, and a printed page is the easiest place to
  quietly overclaim.
- **A4 print rules, not a "printable" claim.** `@page A4`, `break-inside: avoid`
  on rows and figures, foreground forced to black, and the one dark panel flipped
  to a bordered white block. Not verified on paper: this environment has no
  printer, so the print rules are reasoned and syntactically checked, not seen.

## The same sheet, as a screen

`dashboard/src/components/ConnectTracker.jsx` is that sheet with live state, and it
is deliberately the same design rather than a second treatment of the same idea:

| Sheet | Screen | Why |
|---|---|---|
| Six numbered hops | `.hops .hop` list, numbered 1–6 | The numbers are the interface: a technician who has the printed page in hand and the screen open must be looking at hop 4 in both. `verify.mjs` asserts the numbering. |
| Solid = running system, dashed = setup | `ok` / `waiting` / `blocked` / `blind` | Four words, each with a colour. `blind` is the state most status screens do not have, and it is the honest one: hop 1 is four SMS sent from a phone, and no server-side fact can ever confirm them. |
| `#0058ec` used once, for the data path | accent used for the primary action and the selected row only | Same rule. A hop's state is never carried by the accent. |
| Mono for labels, ports, identifiers | `.onb` labels, `.mono` identifiers, `.hop-check code` | An IMEI and a port are values to compare character by character, not prose. |
| One dark panel: the command block | the SMS list | A block of commands is a terminal in both. It is also the one place on the screen where the operator copies rather than reads. |
| Rows on hairlines, no cards | `.hop` rows, two hairline tables | Six cards would have made six things of equal weight; the hops are a sequence, and a sequence reads as rows. |

The one thing that is *not* the sheet's: colour never stands alone in either, but
on screen the state word sits in a chip that reuses the dashboard's existing
`.badge s-*` set — a green chip here has to mean what a green chip means on a truck
row, so no fifth palette was invented.

## How it was verified

Screenshots cannot be composited in this environment (recorded above as a
standing limitation), so the diagram was checked the way everything else here is
checked — by measuring:

- every `.node` rectangle against every text node inside it: **no clipped label**
  (widest right edge 1006.5 against a 1092 box edge), and nothing drawn outside
  the viewBox (lowest baseline 336.3 of 372);
- every text pair for **overlap**: none, across 37 text nodes;
- rendered geometry at a 1240px viewport: 1022 × 339 as intended.

What is *not* verified: how it looks. No pixels were seen, for the same
environment reason as the dashboard audit.

---

# Third skill: `landing-page-design` (elayadesign/ai-design-skills)

Read from the source at `github.com/elayadesign/ai-design-skills`, path
`skills/landing-page-design/SKILL.md`. The repo holds **one** skill, checked
against the GitHub contents API rather than its README table.

**Its scope claims this work.** "Apply to all web UI work: landing pages,
marketing sites, components, dashboards, prototypes, and design reviews." Part B
is therefore an audit of this dashboard, not advice about somebody else's page.

**What transfers, and what does not.** Part A (intake, page structure, layout
selection, SEO/AEO) and B5's hero, B7's island nav, B10's cookie consent and
B11's tagline reveal are landing-page machinery. There is no offer here, no
funnel, no scroll and no primary action to convert, so those sections have no
referent — the same treatment the 29-tell audit gives tells 18–21: **not marked
pass, not marked fail**. What does have a referent is the state set (B9), copy
(B1), borders (B4), motion (B7), icons (B6), the ship list (B10) and content
realism (B8).

## Fixed

| Rule | What it was | What it is now |
|---|---|---|
| B9 focus | Rings on the two text inputs, nothing on buttons, nav tiles, tabs or the skip target: controls that are operable but not visibly reachable | One `:focus-visible` rule for the whole sheet |
| B9 active | No press feedback anywhere | `button:not(:disabled):active` translates 1px, on the custom curve rather than the browser default |
| B9 loading | The connect screen rendered its six hops *before* the server answered, so hop 2 and hop 3 read "non visibile da qui" — a claim about the server, made before asking it — and hop 6 read `ok` for a fetch that had not happened | A skeleton shaped like the six rows it replaces, plus one announced status line. The screen now states nothing it has not been told |
| B4 borders | `.onb-diag` carried `border-left: 3px solid <status colour>` — the coloured side border tell 10 removed everywhere, and which this file records as absent | The same `.badge` chip a hop row uses. No side border. Asserted in `verify.mjs`, resolves to `0px` |
| B1 copy | `Allow-list`, `Auto-registration`, "auto-registration is on", "a read-back" | Rewritten with no hyphen inside prose. The suite prints the new label (`IDENTIFICATIVI AMMESSI`) |
| B1 wrap | No wrap rules at all | `text-wrap: balance` on headings, `pretty` on prose |
| B10 `lang` | `<html lang="it">` hardcoded beside an IT/EN switch, so English copy was announced in Italian | `documentElement.lang` follows the switch. Asserted in both directions |
| B10 skip | Seven nav tiles and two header buttons ahead of the content in tab order, with no way past them | A skip link to the workspace, visible only while focused |
| B10 meta | No description, no robots directive | A description, and `noindex, nofollow`: this is an authenticated console behind a fleet's own network, not a public page |
| Semantics | The refused table's action column had an empty `<th>`; five SMS fields had `<label>`s not associated with their inputs; the identifier input and the device picker had no accessible name | An `sr-only` column name, `htmlFor`/`id` pairs, `aria-label` on both |

## Not applied, with the reason

- **The spacing table (B2).** 0/2/4/8/12/16/24/32/40/48/64/80/96 is a marketing
  page's rhythm. This sheet also uses 5, 6, 9, 10, 11, 14 and 22, and the
  density is the point: a console read at 60cm by someone fitting six rows onto a
  laptop at a customer site. Rewriting 793 lines of spacing would change the
  product rather than tidy it.
- **Tailwind's type scale (B1).** The sheet has one asserted scale,
  11/12/14/16/18/20/24, declared as tokens, with no raw `font-size: <n>px`
  anywhere. Of those steps **11px is the only one off Tailwind's ladder**, and
  the 11px floor is itself a recorded decision (tell 23: the floor was *raised
  to* 11). Adopting the ladder would either flatten 11 and 12 into one step or
  raise the floor across every screen. Both are decisions, not cleanups.
- **Motion on hovers (B7).** The curve now carries the press state and the skip
  link. It is deliberately not on every hover: 700ms
  `cubic-bezier(0.32,0.72,0,1)` on a list of truck rows is an *entrance*, and a
  dispatcher crosses forty of them a minute. The skill's curve is used where
  there is a state worth animating.
- **Icons (B6).** The skill names Phosphor, Solar and Iconamoon and forbids
  Material. The sheet hand-draws its six nav paths on one 20px grid with one
  stroke width — which is the rule's own alternative ("draw the icon"), needs no
  dependency, and was recorded here before this skill was read.
- **Content realism (B8).** Already holds, and now measured: no Lorem Ipsum, no
  placeholder brand, no round fake numbers, no exclamation marks. The demo data
  is real measured distance, not `99.99%`.

## Resolved: the typeface

**This was the one real conflict, and it was put to the user rather than taken.**
B1 forbids Roboto (and Helvetica, Arial); this sheet shipped the reference
console's own `Roboto, 'Helvetica Neue', Helvetica, Arial` chain deliberately,
because a webfont request is the one dependency that breaks both a locked-down
office network and a van's tethered tablet. **The answer was Manrope,
self-hosted**, which is the skill's own list and the offline constraint both:

| | |
|---|---|
| Face | Manrope, weight axis 400-700 |
| Files | `dashboard/public/fonts/manrope-latin.woff2` (24.6 KB), `manrope-latin-ext.woff2` (15.2 KB) |
| Licence | SIL Open Font License 1.1, shipped beside the files it covers as `public/fonts/OFL.txt`, and asserted by CI |
| Declared | `@font-face` at the top of `styles.css`, `font-display: swap`, each file scoped by `unicode-range` |
| Stack | `Manrope, system-ui, -apple-system, 'Segoe UI', sans-serif` |
| Third-party requests | **None.** The files ship in the image and are served from it |

The fallback chain deliberately names no webfont face, so the face this replaced
cannot come back through a failed load. Italian needs only the Latin block — `à`,
`è`, `é`, `ì`, `ò` and `ù` are all U+00FF or below — so the second file is for
data (place and driver names), not for the interface.

**One integration trap, and it is why the suite now asserts this.** The image
builds from an explicit `COPY` list that did not include `public/`. Without
`COPY public ./public` in the dashboard `Dockerfile`, `npm run build` succeeds,
the container starts, every page renders, and the entire console silently falls
back to the platform UI face — a green build with the change simply absent. The
suite now fetches the woff2 from the running container and asserts HTTP 200 for
exactly that reason.

**The printed bench sheet is not aligned to it**, and that is deliberate.
`connect-hardware.html` must open off a USB stick on an offline laptop, so it
carries no font file at all; its stack names Manrope first and then falls back, so
a technician who has the font sees the same face and one who does not gets the
platform UI face. Neither artifact rendered Roboto on an ordinary machine, so this
is a divergence between a thing that now has the font and a thing that cannot.

## Verification

- `npm run build` → exit 0.
- Dashboard image rebuilt and recreated. The **running container** was then read
  back through the CSSOM: `.onb-diag` resolves with no `border-left`,
  `.skip`/`.sr-only`/`.hops-skel`/`:focus-visible`/`text-wrap` are all present,
  and the page carries `meta[name=description]` and `robots=noindex`.
- `npm run verify` → **`RESULT: all checks passed`**, exit 0, with **six new
  assertions**. Two of them make a design rule standing rather than a one-time
  edit: the diagnosis must state its state **in a word**, and no coloured side
  border may appear on it.
- The language fix was exercised through the real UI in the browser: clicking IT
  flipped `documentElement.lang` from `en` to `it`. Before the change the
  attribute was unreachable, because `index.html` can only declare one of the two.
- Not re-run: the compose-configuration guards in CI. This pass touched no
  compose file, no traccar config and no script.

---

# Fourth skill: `frontend-design`

Read from the account skill (`frontend-design/SKILL.md`).

**What it asks for, and what a console allows.** The skill is written for building
a striking new interface: commit to a bold direction, pick an extreme (maximalist,
brutalist, art deco, retro-futurist), and add atmosphere — gradient meshes, noise
textures, grain overlays, dramatic shadows, custom cursors — with one orchestrated
page load. This artifact is an operations console a dispatcher reads at 60cm for
eight hours with a customer on the phone. The direction taken is therefore the one
the sheet already had, executed properly: light surfaces, one accent, hairline
structure, a vendored Manrope. The maximalist options are declined below with their
cost named, rather than quietly skipped.

## The measurements

A new tool backs this section, because two of the findings are rules that a
stylesheet cannot state about itself and that nothing in this repo checked:
`npm run audit:ui` ([`scripts/audit-ui.mjs`](../dashboard/scripts/audit-ui.mjs)).
Every number is from the running container at 1680×980.

| What | Before | After |
|---|---|---|
| Text contrast | **Failed on all seven screens.** `--muted` `#9e9e9e` used as text: 2.68:1 on white, 2.37:1 on `--bg`, against a 4.5:1 minimum | All text clears its threshold. `--muted` is `#5f686f`: 5.30:1 on white, 4.69:1 on `--bg` |
| Weight ceiling (600) | 14px/700 twelve times on history, five on zones, six on connect, twice on reports | Nothing above 600 anywhere |
| Smallest controls | Language chips 32×27, `.btn.tiny` 24px tall | 32×32 and 28px |
| Reduced motion | **No guard anywhere in the sheet** | `prefers-reduced-motion` switches animation and transition off |

**The contrast fix is the one that mattered.** The reference console's muted grey
was used as text by fifteen rules — every secondary label on every screen, at 11
and 12px. It was the worst thing on the sheet, and it was invisible as a problem
because a light grey *looks* like a deliberate choice. It is now `#5f686f`. The
cost is honest: muted sits closer to `--fg2` in value, so the third level of
hierarchy carries less by lightness and more by size (11–12px against 14px) and
hue (a cool slate against a neutral grey). Legibility beat matching a reference
that fails the rule.

**The weight ceiling was a second typeface nobody chose.** The sheet declares
nothing above 600 and this audit records that as a rule — but `<strong>`, `<b>` and
`<th>` render at the browser default 700 unless something says otherwise. That is
precisely how a bolder face arrives on a screen without a decision behind it, and
it was happening twelve times on the history screen. `strong, b, th { font-weight:
600 }`, stated once.

## Declined, with the reason

- **Atmosphere: gradient meshes, noise, grain, dramatic shadows, custom cursors.**
  Texture competes with data. On the map screen the map *is* the atmosphere, and a
  grain overlay over live positions is a filter applied to information.
- **A bold new aesthetic direction** (dark console, brutalist, editorial). The light
  surface is a measured match to the reference tool the operator already uses, and
  the whole point of that match is that nobody has to relearn where anything is. A
  dispatcher relearning a surface is a cost with no dispatch benefit.
- **A display/body font pairing.** The skill asks for a distinctive display face
  beside a refined body face. This sheet is one face plus one monospace, and it has
  no display moment to serve: no hero, no title card, nothing at 48px.
- **A wholesale spacing-scale retrofit.** Same reason as the landing-page audit —
  the density is the product, and rewriting 800 lines of spacing would change the
  tool rather than tidy it.

## Taken from it

- **One motion moment instead of scattered effects.** Changing screen settles the
  panel into place: 10px over 180ms on the same curve as the press state, keyed on
  the view in `App.jsx` so it runs once per screen change. Deliberately *not* on the
  fleet panels, which re-render every five seconds as positions arrive — an
  entrance that replays on every poll is a flicker, not a flourish.
- **Motion on request only.** The system setting is honoured, and the skip link is
  repositioned rather than un-animated, because it still has to become visible.
- **Discipline in the small things**: the language controls, the weight ceiling, and
  the `text-wrap` rules carried over from the third audit.

## Verified

- `npm run build` → exit 0; image rebuilt; container healthy.
- `npm run verify` → **`RESULT: all checks passed`**, exit 0, re-run after every
  change including the new `key` on the workspace panel.
- `npm run audit:ui` → contrast clears on **7 of 7** screens; no weight above 600;
  reduced motion emulated and confirmed (`rise 1e-05s`, skip transition `0s`).
- **Two sub-28px targets survive, and both were checked rather than assumed.**
  MapLibre's own attribution link is 78×12 and inline inside a sentence, which is
  WCAG 2.5.8's inline exception — and it is not our markup. The geofence checkbox
  is a 13px box contained in a **580×20 label**, which is the real target.
- **The fleet screen's "empty" middle column is the map, not dead space.**
  Measured: `.maplibregl-map` is 1680×980 at `0,0`, full-bleed behind the
  transparent shell. The 806px column that reads as wasted space in a DOM dump is
  the map viewport showing through, so it was left alone.
- **A bug this pass caused and caught.** A JSX comment placed inside a `&&`
  expression split it into two children and broke the build — `exit 1`. The first
  measurement run after it was silently measuring the *old* image, which is how it
  was noticed; the numbers above are from the image built after the fix. Recorded
  because the failure mode was a stale image behind a green-looking audit.

## Still not verified

- **How it looks.** This pass tried screenshots again and the preview webview
  reported no composited frames, so the standing limitation above still holds.
  Every claim here is a measurement, which is *stronger* than a screenshot for
  contrast, weight and target size — and is not the same as looking at it.

---

# Completing the fourth audit: the rules, guarded

Two things were left open above. Both are closed here.

## 1. The rules now fail a pull request

The contrast, weight and font rules were enforced only by a tool somebody had to
remember to run, which is the shape of guard that silently rots — this project
had already hit that once, when `Roboto, 'Helvetica Neue', Helvetica, Arial` was
recorded as a deliberate choice and then outlived its reason.

`npm run check:design` ([`scripts/check-design.mjs`](../dashboard/scripts/check-design.mjs))
decides what can be decided from the source and the built bundle, with no browser,
no container and no seeded data, so it runs in CI on every push:

| Rule | Why it can be decided statically |
|---|---|
| Every custom property used as a text `color:` clears 4.5:1 on both light surfaces | The tokens are literals in `:root` and the surfaces are two of them |
| Nothing paints above weight 600 | Weights are declared, and the browser's 700 for `<strong>`/`<th>` is what the cap exists to override |
| No raw `font-size: <n>px` | The sheet's own recorded invariant: every size resolves through a token (`check-design` found one had never been enforced) |
| A `:focus-visible` ring and a `prefers-reduced-motion` block exist | Presence in the sheet |
| The vendored font is referenced by the built CSS and present on disk | The built asset is the thing that ships |

**Every rule has a negative control, and they all fire.** Run against doctored
copies: a lightened `--muted` fails at 2.37:1; a `font-weight: 700` fails the
ceiling; deleting the reduced-motion block fails; a raw `font-size: 13px` fails;
a built bundle without the `<strong>` cap and without the font URL fails both of
its checks. A guard that cannot fail is decoration, so this was tested rather
than assumed. The status *shape* values are deliberately not policed — `#f2b705`
amber on white is 1.7:1 by design, which is the reason the separate `-ink` set
exists, and asserting 3:1 on them would assert the opposite of the decision.

It found one token that had been failing all along and that the DOM audit could
not see because no screen happened to paint it: **`--never-ink` was 4.37:1 on the
page grey** (it is the colour of a "never seen" truck, and the roster is grey, not
white). Now `#666d76`, 5.23:1 white and 4.63:1 on the grey. It also caught
`.btn.ghost` borrowing the *graphical* `--icon` token for its label text — 4.61:1
on a card, 4.08:1 on the grey — which now uses the text token.

## 2. The audit reaches past colour

`npm run audit:ui` grew three dimensions, and each found real defects.

**Accessible names** — every control that a screen reader would announce with no
name. Six were unnamed, on three screens: the vehicle filter in reports, the file
picker and two selects in the tachograph, and three number fields plus a pair of
shift-time inputs in settings. The settings ones were the instructive case: the
label sat *beside* the input in a `.field` row, so `closest('label')` found
nothing and there was no `htmlFor` either — visually labelled, programmatically
anonymous. All seven screens are clean now.

**Keyboard order** — the skip link was the **sixth** tab stop, behind MapLibre's
canvas, two zoom buttons and an attribution toggle, because the map mounts above
the shell and was focusable before it. It is first now (moved to the top of the
app's own DOM, not merely to the top of the shell), every one of the 23 stops
shows a focus indicator, and every stop is on screen when focused.

**Reflow at 320px** (WCAG 1.4.10) — the workspace was being laid out at `x=300`
inside a 320px viewport and clipped with no way to scroll to it: the page reported
no horizontal scroll, so the panels were simply gone. Two specific causes, both
fixed: hard `min-width: 220px` on the identifier fields, and rows that could not
wrap. The two columns now stack below 520px, the roster is capped so the page
never needs vertical scrolling, and a data table — which cannot reflow below its
own min-content width, and which 1.4.10 allows to scroll in its own region —
scrolls inside itself. **Verified as reachable rather than merely excluded:**
`table.grid 334>260 (scrollable)`.

## Two of my own measurements were wrong

Recorded because both produced confident, false readings:

- **The skip link "was not first".** It was. Chromium keeps its sequential-focus
  starting point at the last element focused and `blur()` does not clear it, so
  tabbing after a click on a nav tile resumed from that tile. The probe now
  reloads instead of blurring.
- **"Focus goes off screen" on the skip link.** It does not; the rect was read on
  the same tick as the keypress, mid-transition, while the link was travelling
  into view. The probe now lets focus styles settle.

## Verified

- `npm run check:design` → **`RESULT: all design invariants hold`**, exit 0, run
  from the dashboard directory exactly as CI runs it. It refused the first draft
  of the third pass's token block, and it was right to: see below.
- `npm run audit:ui` → names clean on **8 of 8** screens (Alerts is a screen now);
  keyboard clean, first stop is the skip link; contrast clean; no clipping at
  320px on any screen tried; the type census paints nothing above weight 600.
- `npm run verify` → **`RESULT: all checks passed`**, exit 0, after being taught
  the new switcher (its names are in `aria-label` now, and it asserts 8 tiles in
  the grid *plus* 2 controls in the strip's right column, not a total of 10).
- CI: the workflow parses, and the new `Design invariants` step is the last step
  of the dashboard job, after the build it reads.

---

# Third pass: the reference's own geometry

Every value below was read out of the live reference console at
`https://demo-forguard.gps-trace.com/` by walking its DOM and reading
`getComputedStyle` — the same method the second pass used for its tokens, because
screenshots cannot be composited in this environment. The values are then
asserted against our own rendered styles, on the running app, by a throwaway
Playwright comparison (36 named values plus 2 relationships, all matching).

| Object | Reference | Ours |
|---|---|---|
| Panel column | 450px, 12px top corners | 450px, 12px |
| Nav strip | 4 × 92×48 tiles + a 74px column of two 48px controls, split by a 1px #e0e0e0 rule inset 16px top and bottom, padding 4px, 1px #f1f1f1 bottom rule | identical |
| Title bar | 48px, padding `0 24px 0 28px`, an 18px/500 title centred in the column, 1px #f1f1f1 underline | identical |
| Body | #f1f1f1, bottom corners 12px, padding `8px 16px 16px`, cards on an 8px gutter | identical |
| Card | white, 12px corners, `0 1px 0 rgba(55,71,79,.16)`, padding `16px 16px 16px 12px` | identical |
| Card head | 40px: a 28px unit-type glyph, the name at 14/500, a 12px #5c5c5c status line with its own glyph | identical, except the name's weight follows our state rule (400 offline, 600 on a breach) |
| Action tile | 40×48 holding a 40×40 button at radius 12 and a 20px glyph | identical |
| Separator | 1px `rgba(25,25,28,.12)` | identical |
| Address row | a 20px #757575 glyph, the address at 14px, the age at 12px | identical |
| Chip row | 1px `rgba(92,92,92,.26)` above; chips at `0 8px` with 1px right rules, a 20px glyph then 14px text | identical |

### What is deliberately not cloned

- **Roboto.** The reference's body face. This sheet vendors Manrope, self-hosted
  under `public/fonts/`, because the dashboard has to come up on a locked-down
  office network and on a tethered van tablet. `check:design` asserts the vendored
  file is present and referenced by the built CSS, so this is a decided position
  rather than an omission. It is the single largest remaining visual difference.
- **Its four semantic colours.** `#27ae60`, `#f12323`, `#005693`, `#607d8b`. It
  paints all four on white or on the page grey and at glyph size, and two of them
  measure below 3:1 there (#27ae60 is 2.87:1 on a card, 2.54:1 on the grey) while
  all four are below 4.5:1 for a label. **`check:design` refused the first draft of
  this block for exactly that reason** — the guard caught a real mistake rather
  than a style disagreement. The meanings are kept and drawn in the ink values
  this sheet already declares and already guards.
- **`#9e9e9e` as text.** Every secondary label in the reference is this grey, at
  2.68:1 on white. `--muted` (#5f686f, 5.30:1) stands in. Icons keep the literal
  #757575, which clears the 3:1 a graphical object needs.
- **Its information architecture.** These are our screens with our data. The tiles
  are our seven destinations plus Alerts, which became a screen of its own in this
  pass — eight exactly, which is what fills a 4×2 grid.
- **One number: the strip's height.** The reference declares a 100px strip and
  puts 92×48 tiles with 4px of padding inside it, which needs 104. It overflows by
  4px and paints over its own bottom rule. Reproducing the box would mean
  squashing the tiles; the tiles are what anyone sees, so ours is 104.

### Found by this pass, not by the checklist

- **A screen title rendering at the browser default.** Connect tracker's `<h2>`
  carried no size and no weight, so it painted at 21px/700 — a size this sheet
  never declares and the one weight above its ceiling. `check:design` could not
  see it (it reads declarations) and `audit:ui` printed it without failing; the
  census is what surfaced it. Fixed in the sheet, not in the checks.
- **Two audits navigating by text that no longer exists.** `verify.mjs` and
  `audit-ui.mjs` both found screens with `page.locator('.tabs .tab', { hasText })`.
  The tiles are icon-only now, so that locator matches nothing and both suites
  would have *skipped* the screens and passed. Both now navigate by `aria-label`,
  and `verify` also asserts every tile has a non-empty accessible name — which is
  a stronger test than the text locator was.

### Not verified

- **Still no pixels.** The 320px layout, the pane's proportions and the card
  anatomy are verified by geometry and by the type census, not by eye. Screenshot
  compositing fails in this environment, so a human glance at the fleet screen
  remains the one check this pass could not make.
- **The reference's secondary screens were surveyed, not cloned.** Statistics,
  Maintenance, Timeline and Provider are lists of 52px section cards with a 40px
  glyph, a 16px title over a 12px subtitle and a chevron; that object is built
  here (`.section`) and used by Settings, but our other workspace screens (Reports,
  Tachograph, Zones, History) still use their own layouts. They share the tokens,
  the card surface and the type scale, not yet the section-row format.
- **The unit card's action row is three tiles, not nine.** Four of the reference's
  nine open subsystems this dashboard does not have. A dead control is worse than
  a short row.

---

# Fourth pass: the section row, on every workspace screen

The third pass cloned the reference's section card, built Settings out of it, and
recorded as a known gap that Reports, Tachograph, Zones and History "still use
their own layouts ... not yet the section-row format". This pass closes that gap.
The unit card's action row, open in the same list, is closed as far as this
console can close it, with the reason recorded.

## The section row, extracted once

`components/Section.jsx` is new, and holds one object in two pieces:

| Piece | What it is |
|---|---|
| `SectionRow` | The 52px card: a 20px glyph in a 40px slot, a 16px title over a 12px subtitle, and an optional trailing slot. `static`, so it does not read as pressable, and no chevron — none of these groups opens another screen. |
| `SectionGroup` | That row plus the surface of content it names. `card` is the class on that surface, so a group that has to keep matching an existing selector can say so; `card={null}` leaves the content on the page's own surface, for a group whose contents are `.rows` cards already. |

Settings was rebuilt onto it, so there is one implementation rather than two.
`settings-group`/`settings-card` became `section-group`/`section-card`: the name
lost the screen it came from, because the object is no longer that screen's.

`tacho-head` became `ws-head`, which the Alerts screen shares — one heading row
for a screen's own name and the metadata beside it.

## What each screen became

Every group on all five workspace screens is now a section row.

| Screen | Groups, each headed by a section row |
|---|---|
| Reports | Filters · Totals · the open report |
| Tachograph | Upload · Imports · Activity changes · Period · Coverage · Recorded activity · Weekly totals · Calculate · Result · Findings · Assumptions · Previous runs · Access log |
| Zones & sites | Sites and customers (the row carries the count) · the site list |
| History | Period · Readings · the open tab |
| Settings | Language · Threshold · Work hours · Alerts |

The report group's row is titled from the tab that is open, so the heading and the
tab cannot disagree about which report is on screen.

The tachograph's thirteen panels were the bulk of it: each was a `.panel` headed
by a bare `<h2>` in a `.phead`, and each is now a section row heading the same box.
The content surface keeps the `.panel` class rather than taking `.card`, because
the findings screen is read through `.panel .kpi b` and the coverage and result
panels are `.warnpanel` variants of it; a second card class would have meant
changing those selectors for no visual gain.

Two groups deliberately carry no surface: the sites list and the history tab
lists. Their contents are `.rows` — a stack of white cards — and a white card
inside a white card is the nesting the second pass removed everywhere else.

## The unit card's action row

The third pass recorded three tiles against the reference's nine, and justified
that: four of those nine open subsystems this dashboard does not have. The reason
still holds for the count, but the row was not the only place actions lived —
**Follow** sat in the card's head, beside the name.

The reference's head is one thing: a 28px unit glyph, a 14/500 name and a 12px
status line. Ours was two, with a button next to it. Follow moved into the row, so
the head is now exactly the measured anatomy and the row holds every action this
console has:

| Tile | Action |
|---|---|
| crosshair | Follow on the map |
| clock | History for this unit |
| chart | Reports for this unit |
| share / pin | Copy the position (disabled with no fix) |

Four tiles, not nine: five of the reference's actions open subsystems — statistics,
maintenance, timeline, provider, sharing — that do not exist here, and a dead
control is worse than a short row. `TruckList.jsx` carries that reason at the point
of use, where the next person to add a tile will read it.

## Measured, not eyeballed

Screenshot compositing is still unavailable in this environment — the standing
limitation above holds — so every claim here is a measurement against the running
container.

- `npm run build` → exit 0.
- Dashboard image rebuilt and recreated; the container reports healthy.
- The **deployed bundle** was read back out of the running container.
  `.section-group`, `.section-card`, `.section__end select`, `.section__title`,
  `.hist-head`, `.ws-head` and `.ictile` are all present in the shipped CSS, and
  `settings-group`, `settings-card` and `tacho-head` appear **zero** times across
  the shipped CSS and JS.
- `npm run audit:ui` → clean on **8 of 8** screens for accessible names, contrast,
  keyboard order and 320px reflow. The type census now paints 16px — the section
  title — on every screen that has a section row, and the pane's 18px and the
  workspace's 20px are unchanged.
- `npm run verify` → **`RESULT: all checks passed`**, exit 0, with no `FAIL` lines
  and no console errors or failed requests.

## One regression this pass caused, and the audit caught it

Moving the tachograph's status filter out of a `.phead` and into a section row's
trailing slot took it off the `.phead select` rule and onto a bare `<select>`, and
it rendered at **98×23px** — below the 28px floor this sheet holds itself to, and
something `audit:ui` prints without failing on. `.section__end select` now states
the box explicitly, and the re-measurement reports no small target on the
tachograph screen. The two that survive are the standing ones: MapLibre's 78×12
attribution link, which is inline inside a sentence and is not this console's
markup, and the geofence checkbox, a 13px box inside a 548×20 label.

The same class of hazard applies to any control that moves into a section row's
end slot in future: those rules are written for a panel header, not for this one.

## One locator changed, no assertion weakened

`verify.mjs` read the tachograph's own heading from `.tacho-head h2` and its rules
version from `.tacho-head .mono`. The element is a `ws-head` now, so both locators
were updated. The assertions are unchanged: the screen still has to name itself,
and still has to state the rules, parser and engine versions it is running. This is
the same repair the third pass made when the nav tiles stopped carrying text.

## Still not cloned, and why

- **The action row is four tiles, not nine.** Five of the reference's nine open
  subsystems this dashboard does not have.
- **The workspace screens keep their own information architecture.** They share
  the section row, the tokens, the card surface and the type scale. Zones and
  History are two panes around a live map, which is not a list of section cards
  and was not turned into one — what was cloned is the group heading, not the
  sitemap.
- **No pixels were seen.** The section rows are verified by geometry, by the type
  census and by the deployed bundle, which is stronger than a screenshot for "is
  it there, and at what size" and is not the same as looking at it.

---

# The reference's four semantic colours

The third pass recorded the reference's four semantic colours — `#27ae60`,
`#f12323`, `#005693`, `#607d8b` — as a deliberate non-clone: "the meanings are kept
and drawn in the ink values this sheet already declares and already guards". That
settled the principle and left the actual question open, per colour: adopt the
reference's value, or keep ours? This decides it one meaning at a time, from the
measurement, and records which.

## The measurements

Computed from the WCAG relative-luminance primaries against the two surfaces this
sheet actually paints on. "Ink" is the 4.5:1 bar for text; "shape" is the 3:1 bar
for a graphical object.

| Reference value | Meaning in the reference | on white | on grey | as ink | as shape |
|---|---|---|---|---|---|
| `#27ae60` | green — moving / ok | **2.87** | **2.54** | fails | **fails** |
| `#f12323` | red — alarm | 4.20 | **3.71** | fails | passes |
| `#005693` | blue — idle, and its count badge | 7.63 | 6.75 | passes | passes |
| `#607d8b` | slate — offline | **4.37** | 3.87 | **fails** | passes |

| Ours | on white | on grey |
|---|---|---|
| `--moving-ink` `#147a3a` | 5.42 | 4.80 |
| `--alert-ink` `#c22634` | 5.80 | 5.14 |
| `--idle-ink` `#8a6400` | 5.38 | 4.76 |
| `--info-ink` `#0066b0` | 5.95 | 5.27 |
| `--offline-ink` `#5f686f` | 5.68 | 5.03 |
| `--never-ink` `#666d76` | 5.23 | 4.63 |
| shape `--moving` `#1fa651` | 3.17 | 2.80 |
| shape `--alert` `#d92b3a` | 4.82 | 4.27 |
| shape `--offline` `#7d868f` — replaced | 3.70 | 3.27 |

## The decisions

| Meaning | Decision | Why |
|---|---|---|
| moving / OK | **keep ours**, both roles | `#27ae60` fails *every* bar on *both* surfaces — 2.87:1 as a glyph on a card, 2.54:1 on the page grey, below even the 3:1 a dot needs. It cannot be adopted in any role, so the meaning survives and the value does not. Our shape `#1fa651`, our ink `#147a3a`. |
| alert / breach | **keep ours**, both roles | `#f12323` fails the text bar exactly where we need it — the severity chip is 11px uppercase — at 3.71:1 on the page grey. As a shape it is 4.20:1 against our `#d92b3a`'s 4.82, so adopting it would make the alarm dot *less* legible in the one role where it passes. Our ink `#c22634`, our shape `#d92b3a`. |
| idle / info | **keep ours**; chrome keeps the reference's | `#005693` passes comfortably and it is already in the sheet — as `--brand-deep`, the count badge background (`.pane__stats`) and the selected action tile (`.ib.on`). Giving the *info status* that same hex would put a status value on the accent, which tell 1 forbids and which is the exact defect the retheme existed to remove (one `--accent` shared by chrome and by moving). Chrome keeps the reference's blue; the info meaning keeps `--info-ink` `#0066b0` so the two can still be told apart. |
| offline / never | **adopt the reference's slate as the shape; keep ours as ink** | The one place theirs is measurably better. `#607d8b` clears 3:1 on both surfaces — 4.37 / 3.87 — and beats the `#7d868f` it replaces at 3.70 / 3.27, on the map dot where an offline vehicle still has to be findable. As a glyph it fails (4.37:1 on a card against a 4.5:1 bar), so the ink stays `#5f686f` (5.68 / 5.03) and the two-value pairing survives. |

So: one adoption, three refusals, and one of the four (the blue) turned out to be
in the sheet already, in the role the reference gives it.

`--offline` in `styles.css` and `STATUS.offline` in `lib/palette.js` both moved.
Those two files are declared to mirror each other, so changing one and not the
other would have been exactly the drift that file's own header comment exists to
prevent.

## Two of the earlier prose's numbers were wrong

The third-pass paragraph says "two of them measure below 3:1 there" and "all four
are below 4.5:1 for a label". Both are wrong; the table above is the correction.

- **Only one** of the four is below 3:1 on either surface — `#27ae60`. The
  parenthetical then cites that same colour twice (2.87 on a card, 2.54 on the
  grey), which is what the word "two" was counting.
- **`#005693` is 7.63:1 on a white card** — one of the two highest-contrast values
  in the whole reconciliation, not below 4.5:1. Nothing about it fails.

Neither error changed a decision, which is why both survived: `#005693` was going to
be kept for chrome either way, and the green was going to be refused either way. A
reader acting on the wrong version would have been told that the reference's blue
was unusable when it is the best of the four. Recorded here rather than edited out,
because this file is only worth reading against a revision, and a number in it that
is wrong is worse than a number that is missing.

## Verified

- `npm run build` → exit 0; dashboard image rebuilt and recreated; container healthy.
- `npm run check:design` → **`RESULT: all design invariants hold`**, exit 0. The ink
  half of this reconciliation was already standing: every `-ink` token is asserted
  at 4.5:1 on both surfaces, so a failed *ink* value cannot ship even if someone
  pastes one in. The shape half is deliberately not asserted — the amber at 1.7:1
  is a recorded decision, and asserting 3:1 on shapes would assert its opposite —
  so the adopted slate is checked by measurement instead, below.
- **The adoption was read back out of the running console, not reasoned about.**
  A throwaway probe signed in, waited for the fleet screen and read the painted
  colour off the DOM. The demo fleet is six offline trucks, so the shape under test
  is the one on screen: all six markers paint `rgb(96, 125, 139)`, `--offline`
  resolves to `#607d8b`, and both offline glyph sites — the status chip and the
  card badge — still resolve to `rgb(95, 104, 111)`, which is `#5f686f`. The shape
  moved and the ink did not, which is the whole decision, verified through the
  interface a dispatcher uses. The probe was deleted after the run.
- `npm run audit:ui` → clean on **8 of 8** screens, read from what it *prints*:
  8 `all text clears its threshold` and 8 `every control has an accessible name`
  lines, no `CONTRAST` / `clipped` / `UNNAMED` / `2D SCROLL` line anywhere, and
  no `EMPTY REGIONS` on the fleet screen where the recoloured markers render.
  At the time of this pass the script had no failure path and always exited 0 —
  see *Handing the audit its own exit status*, at the end of this file, which is
  what replaced that. Console and network health is **not** this tool's job — it
  is `verify.mjs` step 10, which reports no console errors and no failed requests.
- `npm run verify` → **`RESULT: all checks passed`**, exit 0, with 6 markers and 6
  roster entries as before and no console errors or failed requests.

---

# Handing the audit its own exit status

`npm run audit:ui` measured the right things and then always exited 0. It was a
report somebody had to read, and the earlier passes in this file say so in as many
words. A report is not a guard: an unnamed control, a contrast miss, a clipped
line, a 28px floor broken or a screen that will not open all scrolled past green,
on a project whose whole reason for having `check:design` in CI was that a rule
nobody is forced to obey rots.

## What changed

The audit now keeps a **failure ledger**. Every rule that breaks calls `fail(...)`,
which prints one `FAIL: <what broke and where>` line at the point it is found and
increments a counter; the run ends with `RESULT: N UI finding(s)` and **exits 1**
when N is not zero. A clean run prints exactly what it printed before, so the
strings this file quotes are still the strings on screen — the exit status is the
part that changed.

Four rules that only reported and never failed now count: an empty region, a
clipped text node, a target below the floor with no recorded exception, and a
column that has collapsed. `TARGET_ALLOWANCES` are still printed on every run, so
an exception cannot hide; they are conditions rather than blanket exemptions, and
the two control cases below prove the exemption does not cover a target that only
*looks* like the one it was written for.

## Two defects in the failure path itself, found by using it

A guard is only worth what happens when the thing it guards is broken, so each new
rule was made to fire on purpose before it was trusted. Two of these runs came back
with a *green* result and no output at all, which is the worst answer:

- **An unreachable switcher tile killed the run.** `goTo()` returned false when
  there was no tile, but a tile that exists and cannot be pressed — hidden, covered,
  or never stable — threw a Playwright timeout out of the middle of the script:
  exit 1, no `FAIL:` line, no `RESULT` line, just a stack trace. That is the least
  readable possible outcome for the case this audit exists for, a screen the
  switcher will not open. The press is now bounded at 5s and caught; both ways of
  failing to reach a screen count as a finding, name which one happened, and let
  the rest of the run continue.
- **The 320px reflow pass measured the wrong screen.** That loop pressed the tile
  with `.catch(() => {})` and then measured whatever was on display — so a failed
  press printed the *previous* screen's numbers under the named screen. It was
  doing exactly that: see below.

## What the exit status immediately caught

**Settings and Connect tracker could not be opened at 320px.** The switcher's 8
tiles are drawn in the reference's 104px strip — two 48px rows plus 4px of padding,
and the strip does not clip. At `max-width: 860px` the grid dropped to 3 columns,
which makes a **third** row for 8 tiles: it spilled past the strip, and the pane's
own `<h2>` was painted over it. Hit-tested, the centre of the Connect tracker tile
resolved to `H2.pane__title`, not the tile, so two of the eight screens were
unreachable on a narrow window and nothing said so.

The grid now stays 4 across at every width. That is not a preference: 4 x 2 is the
only column count the 104px strip has height for, and at the narrowest case the
cell is 51x48 — comfortably above the 28x24 floor this audit holds itself to.

Two corrections follow from it:

- The 320px pass named **three** screens, and that sampling hid the defect behind
  another one: the screen whose press failed was the one whose result looked
  cleanest, because it was printing Reports' numbers. It sweeps **all eight** now.
- The line this file used to report for Connect tracker at 320px —
  `scrolls inside itself: table.grid 334>228 (scrollable)` — was Reports' table
  under a different name. Connect tracker has no such table. That entry was never
  a measurement of Connect tracker; it is now.

## The controls, and how to run them

`npm run audit:ui:controls`
([`scripts/negative-controls.mjs`](../dashboard/scripts/negative-controls.mjs))
gives **every rule a case that breaks it on purpose**: it copies the real script,
injects one breaking change — a stylesheet, a DOM node, an env var, a patched view
list — runs it against the running stack, and asserts both that the expected `FAIL:`
line appears *and* that the process exited 1. The copy is deleted afterwards; an
interrupted run leaves `.neg-*.mjs` behind and the harness clears those first.

```bash
cd dashboard
npm run audit:ui             # the audit, exit 1 on any finding
npm run audit:ui:controls    # 21 doctored copies, ~15 min (19 at this pass; the fifth added two)
CONTROLS_ONLY=clipped-text CONTROLS_JOBS=1 npm run audit:ui:controls   # one case
```

Two things about the harness were wrong in the same silent way, and are worth
recording because both produced *green* controls:

- **The DOM probes never ran.** An init script executes before the document has a
  body *or* a `documentElement` — both null — so `observe(document.documentElement)`
  threw `parameter 1 is not of type 'Node'`, the script died on its first line, and
  the probe was never inserted. Every control built on it "fired" by finding nothing
  to complain about. The probes now wait for the body and observe that.
- **Four cases at once is too many.** Each case is a full audit of a live dashboard
  with a map in it; under that load runs began failing before the login screen for
  reasons unrelated to the rule under test, and three controls reported "exit 1 but
  no line matching" because of it. The default is two, and it is honest about being
  a local tool rather than something that fits in CI as it stands.
- **One injected stylesheet was not a control at all.** `white-space: nowrap` on the
  pane clipped nothing, and the narrower version that would have hidden the switcher
  instead. The clipping control injects a 40px box around a longer line, which is
  the defect itself rather than a side effect of the fix.

## Verified

- `npm run audit:ui` → **  `RESULT: all UI checks passed`**, exit **0**, after the
  grid fix, with the 8-of-8 reflow sweep. Before it: exit 1,
  `FAIL: [Connect tracker] the switcher tile for Connect tracker is in the DOM but
  could not be pressed (hidden, covered, or never stable)`.
- `npm run audit:ui:controls` → **19/19 controls fired** at this pass — **21/21** since
the sub-tab sweep was added (see the fifth pass) — each with its expected
  `FAIL:` line and exit 1 (the one deliberate exception is `no-dist`, which asserts
  exit 0 because a missing `dist/` is a stood-down guard, not a finding).
- `npm run build` → exit 0, and the dashboard image rebuilt and recreated. The
  audit's own staleness rule confirms the served bundle is the one in
  `dashboard/dist` (`index-rPYWJ91-.css, index-DPUU6Hxu.js` on both sides, at the
  time of writing — the rule is the comparison, not these names), so the numbers
  above describe the build in the working tree.
- The three earlier reflow-era claims in this file that only three screens were
  clean at 320px are superseded: **all eight** are, and the two that could not be
  opened are fixed rather than excluded.

## Still not verified

- **This does not yet fail a pull request by itself.** CI has no job that starts
  the stack, seeds a fleet and launches Chromium, and the workflow comment explains
  why: that is a deployment test, not a unit test. The rules that can be decided
  without a browser were promoted into `check:design`, which does run on every push.
  Everything measured here — names, focus order, reflow, painted contrast — needs the
  running DOM, so today the exit status fails a *local* run and `verify.mjs` in a
  deployment, not a PR. Wiring it into CI means adding a job that brings the compose
  stack up and runs `scripts/simulate-fleet.py`; that is a real piece of work and it
  is not claimed here.

# Fifth pass: the registry screen, and the tabs the audit never opened

The driver registry — **Tachograph ▸ Drivers** — arrived as a fifth sub-tab on a
screen that already hid four of them, next to a History screen that hides three
more. Every rule in this file had been decided about the screen a **switcher tile**
opens, and the switcher tile does not open a tab: the tab that now carries a
register form, two selects and a table of live assignments was, by construction,
part of the console nothing measured — as were the seven tabs beside it.

What the screen does, in one line, because it explains the shape: it **records** who
is driving what — dated, audited, never deleted, and mirrored into the tracker's
`driverDriverId` attribute so the roster, the unit panel and the alerts agree — while
whether a person's **name** is displayed stays behind the Settings switch
(`DASHBOARD-SPEC.md`). Recording and displaying are different questions, and the
screen says so on itself rather than leaving the operator to infer it.

## The sweep, and what it found in the first minute

`SUB_TABS` in [`scripts/audit-ui.mjs`](../dashboard/scripts/audit-ui.mjs) names the
screens that hide part of themselves behind their own tabs — **both** of them: the
Tachograph screen's five and History's three. Each of those tabs is now pressed in
turn and measured with the same probes as a whole screen — accessible names, the
target floor, painted contrast, clipping — and, in the 320px pass, reflow. One line
per tab, so a screen cannot pass on the strength of its first tab:

```
  Tachograph / Imports        names, targets, contrast and clipping all clean
  Tachograph / Drivers        names, targets, contrast and clipping all clean
  Tachograph / Activity       names, targets, contrast and clipping all clean
  Tachograph / Findings       names, targets, contrast and clipping all clean
  Tachograph / Access log     names, targets, contrast and clipping all clean
```

History's three are swept by the same loop and read the same way. Its tab names
carry their own counts (`Fermate 12`), which is why the sweep presses **by index**
rather than by label: reading three labels once and then matching on that text is a
moving target, because the count changes when the report lands — and the resulting
mismatch reads as a tab that will not open. The price is that those lines wrap in
the output, since the label itself contains a newline:

```
  History / Stops
24           names, targets, contrast and clipping all clean
```

**On its first run the sweep found a defect on the new tab**: the registry's two
row selects measured **104x23** — one pixel class under the 28x24 floor this audit
holds itself to, in a table row on the busiest screen. The fix is in the stylesheet
(a height on the control), not a new entry in `TARGET_ALLOWANCES`: the two
exceptions there are still MapLibre's inline attribution link and the geofence
checkbox whose label is the real target, both conditional and both printed on every
run.

## Two defects in the sweep itself, both of which read as clean

Neither of these failed anything. Both made the new pass *report* success, which is
the failure mode this whole document is about:

- **The tab locator matched the nav, not the button.** `locator('.tacho .subtabs',
  { hasText: label })` matches the strip that *contains* every label, so the click
  landed in the middle of the nav and measured whichever tab happened to be there —
  five tabs, one measurement, printed five times as clean, each under a different
  name. The press now resolves to the button itself — by index, for the reason
  above.
- **The press failure was swallowed.** The first version pressed with
  `.catch(() => {})` and then measured whatever was on display. An unpressable tab
  therefore printed the *previous* tab's numbers under the pressed tab's name. An
  unpressable tab is now a finding that names the tab that went unmeasured, and the
  run continues.

## The controls, so the sweep cannot rot

Two cases were added to `npm run audit:ui:controls`, and the second is the one that
matters: it does not synthesize a control at all, it **shrinks the registry's own
row selects** and asserts that the sweep reports them.

```
  ok   subtab-unmeasured        a tab inside a screen that cannot be opened, so nothing behind it is measured
         → FAIL: [Tachograph / Imports] the tab could not be pressed, so nothing behind it was measured
  ok   subtab-target-floor      a control behind a tab, below the floor, that the screen-level sweep cannot see
         → FAIL: [Tachograph / Drivers] 2 control(s) below the 28x24 floor and not a recorded exception: select. 79x18, select. 79x18
```

That is the defect the sweep actually found, reproduced on demand: a guard proven
against the defect it exists for rather than against a proxy for it.

## Verified

- `npm run audit:ui` → **`RESULT: all UI checks passed`**, exit **0**, with all
  **eight** tabs swept (five on Tachograph, three on History) and all eight screens
  clean at 320px.
- `npm run audit:ui:controls` → **`RESULT: 21/21 controls fired`**, exit **0** (the
  one deliberate exception remains `no-dist`, which asserts exit 0 because a
  missing `dist/` is a stood-down guard).
- `npm run verify` → **`RESULT: all checks passed`**, exit **0**, and it now walks
  the registry in a real browser: the register form, a card linked from the
  registry at registration, the screen's own statement that driver names are not
  displayed, an assignment that is disabled until a vehicle is chosen, the name
  arriving on the unit card and in the tracker console, exactly one open row, the
  closed row still in the history, and the attribute cleared when the assignment is
  closed.
- `python -m pytest tests/` in `tacho/` → **292 passed, 61 skipped** with no
  database, **353 passed** with one, including the registry's own invariants: two
  open assignments for one driver refused, two drivers in one vehicle allowed.

## Still not verified

- **The registry is measured as an owner.** The `viewer` refusal — the branch that
  prints "not permitted" instead of the table — is asserted in `tacho/`'s own suite
  against the API (a `viewer` gets 403 on `/api/people`, on the card assignments and
  on the vehicle assignments, and every attempt is written to the access log), not
  in a browser. The UI side of that branch is one conditional render, and no check
  here signs in as a viewer to see it.
- **The name column is empty when the switch is off**, which is the state
  `verify.mjs` asserts; the switch-on state is checked there too (the Settings step
  asserts the switch exists and defaults to off) but the roster is not re-read with
  it on, so "the name appears everywhere it should when enabled" is verified by the
  alert-path test and by the mirror step, not by a screen-by-screen comparison.
- **Not in CI**, for the same reason as above: this pass needs the running stack and
  Chromium, and it fails a local run rather than a pull request.
