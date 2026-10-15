/**
 * The six hops, derived from what the server can actually observe.
 *
 * This is `docs/connect-hardware.html` as code: the same six numbered hops, in the
 * same order, with the same refusal to claim more than the server knows. The
 * screen and the printed sheet are meant to be read side by side, so the numbers
 * have to mean the same thing in both, and this file is where that is decided.
 *
 * Four states, and the last two are the reason this exists:
 *
 *   ok        something the server has seen proves this hop works
 *   waiting   the server has no evidence yet. Not an error: a tracker switched on
 *             five minutes ago is legitimately here
 *   blocked   the server has evidence that this hop FAILED -- and for hop 4 it
 *             knows exactly which identifier it refused, which is a fix in one
 *             click rather than an afternoon
 *   blind     the server cannot see this hop at all. Hop 1 is four SMS messages
 *             sent from a phone; there is no server-side fact that could prove
 *             them. Calling that "waiting" would be a lie with a progress spinner
 *             on it
 *
 * Nothing here throws and nothing here reads the network. It takes the facts it is
 * handed and decides what they mean, which is the part worth testing.
 */

export const HOP = {
  OK: 'ok',
  WAITING: 'waiting',
  BLOCKED: 'blocked',
  BLIND: 'blind',
}

/** Newest first, so the most recent refused identifier is the default subject. */
export function refusedEntries(status) {
  return status?.refused?.entries ?? []
}

/** Does the refused list contain this identifier? */
export function refusedIdentifier(status, identifier) {
  if (!identifier) return null
  return refusedEntries(status).find((e) => e.identifier === String(identifier)) ?? null
}

/** `'Stopped {d}'` + `{ d: '12 min' }` -> `'Stopped 12 min'`. */
export function fill(text, values = {}) {
  return String(text).replace(/\{(\w+)\}/g, (whole, key) =>
    values[key] === undefined || values[key] === null ? whole : String(values[key])
  )
}

/**
 * Decide the state of each hop.
 *
 * @param identifier the IMEI under test -- the subject of the screen
 * @param device     Traccar's record for it, if there is one
 * @param position   its newest stored position, if there is one
 * @param status     GET /connect/status, or null when it could not be read
 * @param readOk     did this browser get data out of Traccar at all
 */
export function buildHops({ identifier = '', device = null, position = null, status = null, readOk = true } = {}) {
  const refused = refusedIdentifier(status, identifier)
  const h02 = status?.h02 ?? null

  // Hop 2 and 3 are inferred from one fact: has a packet from this identifier ever
  // reached the server? A stored position proves it, and so does being on the
  // refused list -- the server read that identifier, it just did not know it.
  const heard = Boolean(position) || Boolean(refused)

  const hops = [
    {
      n: 1,
      key: 'sms',
      // The unit accepted the APN, the server address and the intervals, sent by
      // SMS from a phone. There is no server-side trace of that transaction at
      // all... except its consequence, which is a position.
      state: position ? HOP.OK : HOP.BLIND,
      values: { identifier },
      check: null,
    },
    {
      n: 2,
      key: 'data',
      state: !status ? HOP.BLIND : heard ? HOP.OK : HOP.WAITING,
      values: { identifier },
      check: null,
    },
    {
      n: 3,
      key: 'port',
      // Traccar's h02 listener answering inside the network. The published host
      // port is invisible from here -- see the component for the caveat.
      state: !h02 ? HOP.BLIND : h02.listenerReachable ? HOP.OK : HOP.BLOCKED,
      values: { hostPort: h02?.hostPort ?? '', containerPort: h02?.containerPort ?? '' },
      check: './scripts/connect-tracker.py --check',
    },
    {
      n: 4,
      key: 'device',
      state: refused ? HOP.BLOCKED : device ? HOP.OK : HOP.WAITING,
      values: {
        identifier,
        name: device?.name ?? '',
        source: refused?.source ?? '',
      },
      check: refused && identifier ? `./scripts/connect-tracker.py --adopt-seen-id ${identifier}` : null,
    },
    {
      n: 5,
      key: 'position',
      state: position ? HOP.OK : HOP.WAITING,
      values: { identifier },
      check: null,
    },
    {
      n: 6,
      key: 'read',
      // Hop 6 is this screen. Nothing to derive: if the browser could not read
      // Traccar, there would be no screen to look at.
      state: readOk ? HOP.OK : HOP.BLIND,
      values: {},
      check: './scripts/smoke-test.sh',
    },
  ]

  return hops
}

/**
 * The one-line summary above the hops: which hop to look at, in plain language.
 *
 * Ordered by how actionable the state is, not by hop number -- a refused
 * identifier is a fix, and a hop the server cannot see is not worth sending
 * anybody to look at.
 */
export function diagnose(hops) {
  const blocked = hops.find((h) => h.state === HOP.BLOCKED)
  if (blocked) return { state: HOP.BLOCKED, hop: blocked.n, key: blocked.key }
  if (hops.every((h) => h.state === HOP.OK)) return { state: HOP.OK, hop: null, key: 'all' }
  const waiting = hops.find((h) => h.state === HOP.WAITING)
  if (waiting) return { state: HOP.WAITING, hop: waiting.n, key: waiting.key }
  return { state: HOP.BLIND, hop: null, key: 'all' }
}
