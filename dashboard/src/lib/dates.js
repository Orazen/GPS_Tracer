/**
 * Date-window helpers, shared by TrailHistory and Reports so the two screens
 * can never disagree about what "last 7 days" means.
 *
 * The bug this replaces: the first version did `today - 7 days` at midnight and
 * ended the same day at 23:59. That is a single day seven days ago, not a seven
 * day window -- so "Ultimi 7 gg" showed one day's data and looked like data loss.
 *
 * A dispatcher thinks in local calendar days, so every window starts at local
 * midnight. Recent presets end "now" rather than 23:59, otherwise today's
 * preset hides everything recorded since midnight (which is all of it).
 */

export const DAY = 86400000

export const startOfToday = () => {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}

/**
 * key -> window. `to` is "now" for open-ended windows so live data is included.
 */
export function rangeFor(preset) {
  const t0 = startOfToday()
  const now = Date.now()
  switch (preset) {
    case 'today':
      return { from: t0, to: now }
    case 'yesterday':
      return { from: t0 - DAY, to: t0 - 1 }
    case 'd7':
      return { from: t0 - 6 * DAY, to: now }
    case 'd30':
      return { from: t0 - 29 * DAY, to: now }
    case 'd90':
      return { from: t0 - 89 * DAY, to: now }
    default:
      return { from: t0, to: now }
  }
}

/** An <input type="date"> value ("YYYY-MM-DD") as ms at local midnight. */
export const dateInputToMs = (s) => (s ? new Date(s + 'T00:00:00').getTime() : null)

/** Inclusive range from two date inputs. Either side may be blank. */
export function rangeFromInputs(fromDate, toDate) {
  if (!fromDate && !toDate) return null
  const from = dateInputToMs(fromDate)
  const to = dateInputToMs(toDate)
  // A date input covers a whole day, so push `to` out to 23:59:59.999.
  return {
    from: from ?? (to - DAY),
    to: to == null ? Date.now() : to + DAY - 1,
  }
}

/** Preset list shared by both screens. */
export const PRESETS = [
  { k: 'today', i18n: 'today' },
  { k: 'yesterday', i18n: 'yesterday' },
  { k: 'd7', i18n: 'last7' },
  { k: 'd30', i18n: 'last30' },
]
