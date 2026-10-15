/**
 * The console's icon set, drawn rather than borrowed.
 *
 * There is no icon font here and there never will be: a font is one more
 * blocking request, one more thing to version, and the six shapes this console
 * actually needs are six paths. Every icon is a 20px square drawn on the same
 * grid with the same 1.6px stroke and the same round caps, so they read as one
 * set rather than six visits to a clip-art site. Current colour comes from the
 * parent, which is how the active tile turns blue without a second asset.
 *
 * The shapes are deliberately the reference console's vocabulary -- pin, clock,
 * fence, chart, disc, sliders -- because a dispatcher moving between this and
 * the system it replaces should not have to relearn where anything is.
 */

const P = {
  /** Fleet / map. A pin: teardrop plus the hole that makes it read as a pin. */
  fleet: (
    <>
      <path d="M10 17.6C10 17.6 15.6 12.4 15.6 8.4A5.6 5.6 0 0 0 4.4 8.4C4.4 12.4 10 17.6 10 17.6Z" />
      <circle cx="10" cy="8.3" r="2.1" />
    </>
  ),
  /** History. A clock face with two hands -- not a loop arrow, which is a tell. */
  history: (
    <>
      <circle cx="10" cy="10" r="7.4" />
      <path d="M10 5.4V10l3.2 1.9" />
    </>
  ),
  /** Zones and sites. A dashed boundary with the point it encloses. */
  zones: (
    <>
      <path d="M3.2 7.4 10 3l6.8 4.4v5.2L10 17l-6.8-4.4z" strokeDasharray="2.8 2.1" />
      <circle cx="10" cy="10" r="1.5" fill="currentColor" stroke="none" />
    </>
  ),
  /** Reports. Baseline plus two measured bars -- a chart, not a picture of one. */
  reports: (
    <>
      <path d="M3.4 3.2v13.6h13.2" />
      <path d="M7.4 16.8V10.6" />
      <path d="M11.6 16.8V6.4" />
    </>
  ),
  /** Tachograph. The disc: outer rim, centre hub, and its registration marks. */
  tacho: (
    <>
      <circle cx="10" cy="10" r="7.4" />
      <circle cx="10" cy="10" r="2.3" />
      <path d="M10 2.6v2.9" />
      <path d="M10 14.5v2.9" />
    </>
  ),
  /** Alerts. A bell, with the clapper as the one solid dot in the set. */
  bell: (
    <>
      <path d="M5.2 8.4a4.8 4.8 0 0 1 9.6 0c0 3.4 1.4 4.6 1.4 4.6H3.8s1.4-1.2 1.4-4.6Z" />
      <path d="M8.4 15.4a1.8 1.8 0 0 0 3.2 0" />
    </>
  ),
  /**
   * Connect a tracker. The unit itself, drawn as a box with a mount and two
   * signal arcs -- the arcs are what make it read as "a tracker talking to a
   * server" rather than "a folder".
   */
  connect: (
    <>
      <rect x="6.6" y="9.4" width="11.6" height="7.6" rx="1.6" />
      <path d="M12.4 9.4V6.2" />
      <path d="M9.2 4.4a4.6 4.6 0 0 1 6.4 0" />
      <path d="M7 2.6a7.4 7.4 0 0 1 10.8 0" opacity="0.55" />
    </>
  ),
  /** Settings. Sliders, which say "adjust" without the gear cliche. */
  settings: (
    <>
      <path d="M3.2 6.6h13.6" />
      <path d="M3.2 13.4h13.6" />
      <circle cx="7.2" cy="6.6" r="2.1" />
      <circle cx="13" cy="13.4" r="2.1" />
    </>
  ),

  /* ---- the reading glyphs ----
     One per value a unit card prints, because the reference console puts a
     glyph before every number in its status strip and a bare "95 km/h" in a row
     of five is read one column at a time. Same grid, same 1.6px stroke, same
     round caps as everything above. */

  /** Ignition. A power symbol: the contact, not a key and not a padlock. */
  ignition: (
    <>
      <path d="M10 2.8v7.4" />
      <path d="M5.4 5.6a6.4 6.4 0 1 0 9.2 0" />
    </>
  ),
  /** Speed. A dial arc with the needle at a third -- a reading, not a clock. */
  speed: (
    <>
      <path d="M3.2 14.4a7.4 7.4 0 1 1 13.6 0" />
      <path d="M10 14.4 13.4 9" />
    </>
  ),
  /** Heading. The navigation arrow the reference uses for a bearing. */
  heading: (
    <>
      <path d="M10 2.8 15.4 17.2 10 14.2 4.6 17.2Z" />
    </>
  ),
  /** Battery. Case, terminal, and the level inside it. */
  battery: (
    <>
      <rect x="2.8" y="6.4" width="12.4" height="7.2" rx="1.6" />
      <path d="M17.2 8.6v2.8" />
      <path d="M5.4 9v2" />
      <path d="M8.4 9v2" />
    </>
  ),
  /** The time a fix arrived. A small clock: a face and two hands. */
  clock: (
    <>
      <circle cx="10" cy="10" r="6.8" />
      <path d="M10 6.4V10l2.6 1.6" />
    </>
  ),
  /** The address the unit is standing on. */
  pin: (
    <>
      <path d="M10 17.4c0 0 5.2-5 5.2-8.8a5.2 5.2 0 0 0-10.4 0c0 3.8 5.2 8.8 5.2 8.8Z" />
      <circle cx="10" cy="8.5" r="1.9" />
    </>
  ),
  /** One journey: a path between two ends. */
  trip: (
    <>
      <path d="M4.4 15.6c3.2 0 2.8-9.2 8-9.2" strokeDasharray="2.6 2" />
      <circle cx="4.4" cy="15.6" r="1.7" />
      <circle cx="14.4" cy="6.4" r="1.7" />
    </>
  ),
  /** Follow this unit. A crosshair, which is what the map control is called. */
  target: (
    <>
      <circle cx="10" cy="10" r="6.4" />
      <circle cx="10" cy="10" r="1.6" fill="currentColor" stroke="none" />
      <path d="M10 1.6v3" />
      <path d="M10 15.4v3" />
      <path d="M1.6 10h3" />
      <path d="M15.4 10h3" />
    </>
  ),
  /** Share or report this unit to someone. Two nodes and the line between them. */
  share: (
    <>
      <circle cx="5" cy="10" r="2.2" />
      <circle cx="14.6" cy="5.2" r="2.2" />
      <circle cx="14.6" cy="14.8" r="2.2" />
      <path d="M7 8.9l5.6-2.8" />
      <path d="M7 11.1l5.6 2.8" />
    </>
  ),
  /** A row's own menu. Three dots, vertical, as the reference draws it. */
  kebab: (
    <>
      <circle cx="10" cy="4.6" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="10" cy="10" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="10" cy="15.4" r="1.3" fill="currentColor" stroke="none" />
    </>
  ),
  /** Narrow the list. The reference's filter, in the title bar's left corner. */
  filter: (
    <>
      <path d="M3.2 4.4h13.6l-5.2 6v6.2l-3.2-1.8V10.4Z" />
    </>
  ),
  /** Play a recorded track back. */
  play: (
    <>
      <path d="M6.4 4.2 15.2 10l-8.8 5.8Z" />
    </>
  ),
  /** A backwards step: the reference's chevron beside a page title. */
  back: (
    <>
      <path d="M12.4 4.4 6.8 10l5.6 5.6" />
    </>
  ),

  /**
   * The unit itself, at 28px in a card's head. The reference draws each unit
   * with a glyph of its own type; a fleet of delivery trucks needs only the one,
   * and a box with a cab reads as a lorry at 28px where a car silhouette does
   * not. Two wheels, because a vehicle with none is a shed. */
  truck: (
    <>
      <path d="M2.6 6.2h9.2v8.2H2.6z" />
      <path d="M11.8 8.6h2.8l2.8 3.1v2.7h-5.6z" />
      <circle cx="6.2" cy="15.4" r="1.7" />
      <circle cx="14.4" cy="15.4" r="1.7" />
    </>
  ),
}

export default function Icon({ name, size = 20, className = '' }) {
  const body = P[name]
  if (!body) return null
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {body}
    </svg>
  )
}

export const ICON_NAMES = Object.keys(P)
