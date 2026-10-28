/**
 * Formatting for everything the console shows to a person.
 *
 * Every wall-clock time is printed in Europe/Rome, whatever timezone the browser
 * or the server is in: the fleet and the depot are in Italy, and a dispatcher
 * reading "08:00" must mean 08:00 in Rome. Relative ages ("3 min") stay in
 * traccar.js `ago`, because they do not depend on a timezone.
 */

export const ROME_TZ = 'Europe/Rome'

const locale = (lang) => (lang === 'en' ? 'en-GB' : 'it-IT')

const toDate = (v) => {
  if (v == null || v === '') return null
  const d = v instanceof Date ? v : new Date(v)
  return Number.isNaN(d.getTime()) ? null : d
}

/** Any Intl.DateTimeFormat options, pinned to Rome. Returns null for no value. */
export function formatRome(value, lang = 'it', opts = {}) {
  const d = toDate(value)
  if (!d) return null
  return new Intl.DateTimeFormat(locale(lang), { timeZone: ROME_TZ, ...opts }).format(d)
}

export const dateRome = (value, lang = 'it') =>
  formatRome(value, lang, { day: '2-digit', month: '2-digit', year: 'numeric' })

export const timeRome = (value, lang = 'it') =>
  formatRome(value, lang, { hour: '2-digit', minute: '2-digit' })

export const dateTimeRome = (value, lang = 'it') =>
  formatRome(value, lang, { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })

/** Whole numbers with the locale's grouping separator. Null for a non-number. */
export function formatCount(n, lang = 'it') {
  if (n == null || !Number.isFinite(Number(n))) return null
  return new Intl.NumberFormat(locale(lang)).format(Number(n))
}
