/**
 * The navigation model: eight top-level sections, and the screens under them.
 *
 * Every screen the console had before this shell is still here, under exactly
 * one section: Fleet (map), Zones (geofences), History, Reports, Tachograph,
 * Alerts, Connect a tracker and Settings. Three sections -- Scrap, Inventory and
 * Sales -- are new and have no data behind them yet; their screens say so rather
 * than show numbers.
 *
 * Connect a tracker is an administrator's screen. The server enforces that
 * independently; hiding it here is presentation only.
 */

export const SECTIONS = [
  { id: 'overview', labelKey: 'navOverview', icon: 'overview', screens: ['overview'] },
  { id: 'live', labelKey: 'navLive', icon: 'fleet', screens: ['map', 'geofences'] },
  { id: 'history', labelKey: 'navHistory', icon: 'history', screens: ['history', 'reports'] },
  { id: 'scrap', labelKey: 'navScrap', icon: 'scrap', screens: ['scrap'] },
  { id: 'inventory', labelKey: 'navInventory', icon: 'inventory', screens: ['inventory'] },
  { id: 'sales', labelKey: 'navSales', icon: 'sales', screens: ['sales'] },
  { id: 'drivers', labelKey: 'navDrivers', icon: 'tacho', screens: ['tacho'] },
  { id: 'admin', labelKey: 'navAdmin', icon: 'bell', screens: ['alerts', 'connect', 'settings'] },
]

const ADMIN_ONLY = new Set(['connect'])

/** The sections a given user may see, with each one's screens filtered to match. */
export function visibleSections(user) {
  const admin = user?.administrator === true
  return SECTIONS
    .map((s) => ({ ...s, screens: s.screens.filter((v) => admin || !ADMIN_ONLY.has(v)) }))
    .filter((s) => s.screens.length > 0)
}

export const sectionOf = (view) => SECTIONS.find((s) => s.screens.includes(view)) || null

/** A screen's name. The fleet screen is called "Fleet" in the strings it has always had. */
export const screenLabel = (t, view) => t(view === 'map' ? 'fleet' : view)
