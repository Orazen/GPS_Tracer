/**
 * The dashboard palette, in JavaScript.
 *
 * This mirrors the token block at the top of styles.css and exists for the two
 * places CSS cannot reach: map paint properties (MapLibre wants a literal, not a
 * custom property) and inline SVG. Anything that can read a CSS variable should
 * read one instead of importing from here.
 *
 * Why this file exists at all: these values were previously retyped in five
 * files, and they had already drifted. "Moving" was #10b981 in lib/status.js,
 * #22c55e in the geofence palette and #4ade80 in a stylesheet rule -- three
 * hexes for one meaning, which is how a status colour stops meaning anything.
 *
 * The surface, the accent and the greys are taken from the operator console this
 * dashboard is modelled on: white cards on a #f1f1f1 page, a single blue accent
 * at #0058ec, and near-black text at #19191c. Status keeps the road-signing
 * values, because a green dot on a light map still reads as "moving" faster than
 * any label.
 *
 *   STATUS  the value as a shape -- a map dot, a fill, a 2px line. Saturated,
 *           chosen to survive on top of light map tiles.
 *   INK     the same meaning as an 11-14px glyph on white. Darkened until it
 *           clears 4.5:1, which none of the STATUS values do except alert.
 *   BRAND   interaction only (selection, focus, primary action). Never a data
 *           value, so a selected row can never look like a moving truck.
 */

/** A vehicle's state as a shape. Map dots, fills, strokes. */
export const STATUS = {
  moving: '#1fa651',
  idle: '#f2b705',
  alert: '#d92b3a',
  // The reference console's slate. Of its four semantic colours this is the one
  // that measurably beats ours in the shape role: 4.37:1 on a white card and
  // 3.87:1 on the page grey, against the #7d868f it replaced at 3.70 and 3.27,
  // on the map dot where an offline vehicle has to stay findable. Its glyph value
  // still fails the 4.5:1 text bar (4.37:1 on a card), so INK.offline stays ours.
  offline: '#607d8b',
  never: '#a6adb4',
  info: '#4a90d9',
}

/**
 * A vehicle's state as a glyph on white. Every value here clears 4.5:1 against
 * #ffffff, which is the whole reason it is a separate set: #f2b705 amber on
 * white is 1.7:1 and unreadable at 11px, and darkening it inside STATUS would
 * make the map dot look like mud.
 */
export const INK = {
  moving: '#147a3a',
  idle: '#8a6400',
  alert: '#c22634',
  offline: '#5f686f',
  never: '#6b7178',
  info: '#0066b0',
}

/**
 * The same values, keyed by the state names in lib/status.js -- STATE.MOVING is
 * the string 'moving', and that is how every consumer already indexes them.
 * Kept as a distinct export so `COLOR[state]` keeps working unchanged.
 */
export const COLOR = STATUS

/** Interaction only: selected tile, primary button, focus ring, selected row. */
export const BRAND = '#0058ec'

/** The darker blue the reference uses for the count badge's own background. */
export const BRAND_DEEP = '#005693'

/** A zone with no colour of its own. Deliberately colourless, not a status. */
export const NEUTRAL = '#7a7f87'

/**
 * Categorical colours for delivery zones.
 *
 * Six hues a dispatcher can tell apart at a glance, chosen so that none of them
 * reuses a status hex -- if a zone were the moving green, a parked zone would
 * read as a moving truck. None is purple either: the purple-to-blue gradient was
 * the loudest tell in the previous design and a single purple swatch next to a
 * blue accent still reads as one. A zone colour carries no severity; it only has
 * to be distinguishable from the zone next to it, and visible on light tiles.
 */
export const ZONE = ['#0f6fa8', '#c2691a', '#5b8f2a', '#b02c6b', '#0f8f8f', '#7a7f87']
