/**
 * GPS_Tracer dashboard server.
 *
 * The dashboard is a browser app, but two of the things it talks to must not be
 * reachable from a browser directly:
 *
 *   1. **Traccar** authenticates with a `JSESSIONID` cookie. Serving the app and
 *      the API from one origin keeps that cookie same-origin, so there is no CORS
 *      configuration to get wrong and no token for the browser to hold.
 *
 *   2. **The tachograph API** requires a *service token* and serves driver personal
 *      data. If the browser called it directly, the token would have to be shipped
 *      to the browser, which is the same as publishing it. So this process holds the
 *      token, and the browser never sees it.
 *
 * That is what makes the two halves one system with one login: the user
 * authenticates against Traccar, and this proxy forwards *who they are* to the
 * tachograph service, which records it in its audit log. The tachograph service
 * still enforces its own roles — the proxy asserts identity, it does not grant
 * access.
 *
 * Role mapping, Traccar -> tachograph:
 *
 *   administrator = true   ->  owner          (may read the audit log)
 *   readonly = true        ->  viewer         (may not read driver data at all)
 *   anything else          ->  fleet_manager  (may read driver data)
 *
 * Least privilege is the default in every branch: an unrecognised shape becomes
 * `viewer`, never a privileged role, because the tachograph service treats driver
 * data as restricted and a mapping mistake should fail closed.
 *
 * No dependencies on purpose. This is the process standing between a browser and
 * somebody's driving hours; every line of it should be readable in one sitting.
 */

import { createServer } from 'node:http'
import { connect } from 'node:net'
import { readFile, stat } from 'node:fs/promises'
import { createReadStream, existsSync, readFileSync, openSync, readSync, fstatSync, closeSync } from 'node:fs'
import { extname, join, normalize, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = resolve(fileURLToPath(new URL('.', import.meta.url)))

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/**
 * Load the repository's .env for local development.
 *
 * Real environment variables always win, and this is a no-op inside the
 * container (there is no .env there), so the same code runs in both places. It
 * deliberately does NOT overwrite anything already set: Dokploy and Compose both
 * pass real environment variables, and a stray .env must never silently beat them.
 */
function loadDotEnv() {
  const path = join(HERE, '..', '.env')
  if (!existsSync(path)) return
  for (const raw of readFileSync(path, 'utf8').split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq < 1) continue
    const key = line.slice(0, eq).trim()
    let value = line.slice(eq + 1).trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    if (!(key in process.env)) process.env[key] = value
  }
}
loadDotEnv()

const PORT = Number(process.env.DASHBOARD_PORT || process.env.PORT || 8083)
const HOST = process.env.DASHBOARD_HOST || '0.0.0.0'

// Traccar, over the internal Docker network in production and loopback in dev.
const TRACCAR_URL = (
  process.env.TRACCAR_INTERNAL_URL || 'http://127.0.0.1:8092'
).replace(/\/$/, '')

// The tachograph API. Required: without it there is nothing to authenticate to,
// and a proxy that "helpfully" runs open is worse than one that refuses.
const TACHO_URL = (process.env.TACHO_INTERNAL_URL || 'http://127.0.0.1:8094').replace(
  /\/$/,
  ''
)
const TACHO_TOKEN = process.env.TACHO_API_TOKEN || ''

// The scrap (loads, weighing, stock, sales) service. Same trust model as the
// tachograph service: the token stays here, the identity is forwarded.
const SCRAP_URL = (process.env.SCRAP_INTERNAL_URL || 'http://127.0.0.1:8085').replace(
  /\/$/,
  ''
)
const SCRAP_TOKEN = process.env.SCRAP_API_TOKEN || ''
// Role for a signed-in, non-admin Traccar user. Read-only by default: writing
// loads, weights and stock is opt-in per deployment, never implied by login.
const SCRAP_DEFAULT_ROLE = (process.env.SCRAP_DEFAULT_ROLE || 'viewer').trim()

const DIST = join(HERE, 'dist')
const MAX_BODY = Number(process.env.DASHBOARD_MAX_BODY_BYTES || 16 * 1024 * 1024)
const UPSTREAM_TIMEOUT_MS = Number(process.env.DASHBOARD_UPSTREAM_TIMEOUT_MS || 60000)

// ---------------------------------------------------------------------------
// Onboarding
//
// Everything the "Connect a tracker" screen needs that is NOT reachable over
// Traccar's REST API: what this server will do with an unknown identifier, which
// identifiers it has already refused, and whether its H02 listener answers.
//
// All three are read from the Traccar container's log volume, mounted read-only
// here. Nothing is inferred: when a file is missing the screen says the fact is
// unreadable rather than assuming the default, because assuming the default is
// how an operator spends an afternoon on the wrong hop.
// ---------------------------------------------------------------------------

/** The host port a tracker must be pointed at. Published side of the mapping. */
const H02_PORT = Number(process.env.H02_PORT || 5013)

/** Traccar's own listener port inside the container. Not configurable: h02. */
const H02_CONTAINER_PORT = 5013

const TRACCAR_LOG_DIR = process.env.TRACCAR_LOG_DIR || '/opt/traccar/logs'

/** How much of the tail of tracker-server.log to consider. */
const LOG_TAIL_BYTES = 512 * 1024

/** At most this many refused identifiers are reported, newest first. */
const MAX_SEEN = 12

/**
 * Read the last N bytes of a file without loading the whole thing.
 *
 * Traccar's log is append-only and grows for as long as the deployment lives, so
 * `readFile` on it is a way to make the dashboard allocate a gigabyte one day.
 * Returns null when the file is not there, which is a fact the screen reports.
 */
function readTail(path, bytes) {
  let fd
  try {
    fd = openSync(path, 'r')
  } catch {
    return null
  }
  try {
    const size = fstatSync(fd).size
    const start = Math.max(0, size - bytes)
    const length = size - start
    if (length === 0) return ''
    const buf = Buffer.allocUnsafe(length)
    readSync(fd, buf, 0, length, start)
    return buf.toString('utf8')
  } catch {
    return null
  } finally {
    try { closeSync(fd) } catch { /* nothing useful to do */ }
  }
}

/**
 * The onboarding settings the Traccar container actually rendered.
 *
 * Written by traccar/config/entrypoint.sh. Null when it could not be read, and
 * the screen distinguishes "off" from "unknown" because those are different
 * answers to "why did my tracker not appear?"
 */
function readOnboarding() {
  const raw = readTail(join(TRACCAR_LOG_DIR, 'onboarding.json'), 64 * 1024)
  if (raw === null) return null
  try {
    const parsed = JSON.parse(raw)
    return {
      readable: true,
      writtenAt: typeof parsed.writtenAt === 'string' ? parsed.writtenAt : '',
      allowRegistration: parsed.allowRegistration === true,
      registerUnknown: parsed.registerUnknown === true,
      defaultCategory: String(parsed.defaultCategory ?? ''),
      regex: String(parsed.regex ?? ''),
      h02ContainerPort: Number(parsed.h02ContainerPort) || H02_CONTAINER_PORT,
    }
  } catch {
    // A half-written file is possible: the container rewrites it on start. Say so
    // rather than reporting a default that may be the opposite of the truth.
    return { readable: false, reason: 'unparsable' }
  }
}

/**
 * Identifiers Traccar has refused.
 *
 * This is the single most useful fact on the screen and it exists nowhere but
 * the log: with auto-registration off (the default), a tracker that has never
 * been registered reaches the server, is decoded, and is then thrown away with
 * `WARN: Unknown device - <identifier> (<source ip>)` and no stored position.
 * From the map that is indistinguishable from a tracker that never connected.
 * Reading it back turns "nothing appears" into a one-click fix.
 *
 * Only the tail is scanned, and an identifier whose device now exists is dropped:
 * the list is a to-do list, not an archive.
 */
function scanRefusedIdentifiers(knownIds) {
  const raw = readTail(join(TRACCAR_LOG_DIR, 'tracker-server.log'), LOG_TAIL_BYTES)
  if (raw === null) return { readable: false, entries: [] }

  const re = /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+WARN: Unknown device - (\S+?)(?: \(([^)]+)\))?\s*$/gm
  // Newest last in the log, so iterate and keep overwriting: the last match for
  // an identifier is the most recent sighting of it.
  const byId = new Map()
  let m
  while ((m = re.exec(raw)) !== null) {
    const [, at, identifier, source] = m
    byId.set(identifier, { identifier, at, source: source || '' })
  }

  const entries = [...byId.values()]
    .filter((e) => !knownIds.has(e.identifier))
    .slice(-MAX_SEEN)
    .reverse()

  return { readable: true, entries }
}

/**
 * Does Traccar's H02 listener answer?
 *
 * From inside the Docker network, at the container port. This proves the decoder
 * is up and listening; it does NOT prove the published host port is mapped onto
 * it, which is the failure in UNIMPLEMENTED.md 7.8 and which no process inside
 * this container can see. The screen says exactly that instead of implying a green
 * light means the outside path works -- scripts/connect-tracker.py --check is still
 * the only thing that inspects both sides of the mapping.
 */
function probeH02(timeoutMs = 2500) {
  const host = (() => {
    try { return new URL(TRACCAR_URL).hostname } catch { return '127.0.0.1' }
  })()
  return new Promise((resolveProbe) => {
    const socket = connect({ host, port: H02_CONTAINER_PORT })
    let done = false
    const finish = (reachable) => {
      if (done) return
      done = true
      socket.destroy()
      resolveProbe({ reachable, host, port: H02_CONTAINER_PORT })
    }
    socket.setTimeout(timeoutMs, () => finish(false))
    socket.on('connect', () => finish(true))
    socket.on('error', () => finish(false))
  })
}

/** Traccar's device identifiers, so a refused one that is now registered drops off. */
async function knownIdentifiers(req) {
  try {
    const res = await fetchWithTimeout(`${TRACCAR_URL}/api/devices`, {
      headers: { cookie: req.headers.cookie || '', accept: 'application/json' },
    })
    if (!res.ok) return new Set()
    const devices = await res.json()
    return new Set((Array.isArray(devices) ? devices : []).map((d) => String(d.uniqueId ?? '')))
  } catch {
    return new Set()
  }
}

/**
 * GET /connect/status -- the server-side half of the onboarding screen.
 *
 * Administrator only.
 *
 * Not because the identifiers are secret -- an administrator can see the whole
 * fleet anyway -- but because this reports the server's configuration and the
 * raw identifiers of everything that has probed the public H02 port. That is
 * operator material, and a read-only fleet user has no use for it. The refusal is
 * a 403 with a reason, so a misconfigured role shows up as a clear message rather
 * than an empty screen.
 */
async function serveConnectStatus(req, res) {
  const user = await identify(req)
  if (!user) return sendJson(res, 401, { detail: 'sign in first' })
  if (user.administrator !== true) {
    return sendJson(res, 403, {
      detail:
        'connecting trackers is an administrator task: this reads the server\'s ' +
        'own configuration and the identifiers everything on the internet has sent it',
    })
  }

  const [h02, known] = await Promise.all([probeH02(), knownIdentifiers(req)])
  const refused = scanRefusedIdentifiers(known)

  return sendJson(res, 200, {
    h02: {
      hostPort: H02_PORT,
      containerPort: h02.port,
      listenerReachable: h02.reachable,
      probedHost: h02.host,
    },
    registration: readOnboarding(),
    refused: {
      readable: refused.readable,
      logDir: TRACCAR_LOG_DIR,
      entries: refused.entries,
    },
  })
}

if (!TACHO_TOKEN) {
  console.warn(
    '[dashboard] TACHO_API_TOKEN is not set. /tacho/* will refuse every request. ' +
      'The fleet map still works; the tachograph tabs will not.'
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.txt': 'text/plain; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  // MapLibre loads its worker as a module worker; wrong type breaks the map.
  '.wasm': 'application/wasm',
}

function send(res, status, body, headers = {}) {
  const payload = typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body)
  res.writeHead(status, {
    'Content-Type': 'text/plain; charset=utf-8',
    ...headers,
  })
  res.end(payload)
}

function sendJson(res, status, value, headers = {}) {
  send(res, status, JSON.stringify(value), {
    'Content-Type': 'application/json; charset=utf-8',
    // Anything derived from a user's session or driver data is private.
    'Cache-Control': 'no-store',
    ...headers,
  })
}

/** Read the request body, with a cap so one request cannot exhaust memory. */
function readBody(req) {
  return new Promise((resolveBody, reject) => {
    const chunks = []
    let size = 0
    req.on('data', (chunk) => {
      size += chunk.length
      if (size > MAX_BODY) {
        reject(Object.assign(new Error('request body too large'), { code: 413 }))
        req.destroy()
        return
      }
      chunks.push(chunk)
    })
    req.on('end', () => resolveBody(Buffer.concat(chunks)))
    req.on('error', reject)
  })
}

/** Copy the headers we mean to forward, and only those. */
function forwardHeaders(req, extra = {}) {
  const out = { ...extra }
  // The session cookie is the whole point of the Traccar proxy.
  if (req.headers.cookie) out.cookie = req.headers.cookie
  for (const name of ['accept', 'content-type', 'content-length', 'user-agent']) {
    if (req.headers[name]) out[name] = req.headers[name]
  }
  // Traccar needs this on report endpoints to answer with rows instead of bytes
  // when the caller wants rows; the dashboard sets it per call, so pass it on.
  if (req.headers['accept-language']) out['accept-language'] = req.headers['accept-language']
  return out
}

/** Copy Set-Cookie back to the browser so login and logout work. */
function responseHeadersFrom(upstream) {
  const out = {}
  const setCookie = upstream.headers.getSetCookie?.() ?? []
  if (setCookie.length) out['set-cookie'] = setCookie
  const type = upstream.headers.get('content-type')
  if (type) out['Content-Type'] = type
  const disposition = upstream.headers.get('content-disposition')
  if (disposition) out['Content-Disposition'] = disposition
  return out
}

async function fetchWithTimeout(url, options) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS)
  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }
}

// ---------------------------------------------------------------------------
// Identity
// ---------------------------------------------------------------------------

/**
 * Who is calling?
 *
 * Traccar answers GET /api/session with the User, or 404 when there is no valid
 * session (it reports a missing session as 404, not 401 — a quirk worth knowing
 * before you spend an hour on it).
 *
 * Returns null when the caller is not logged in. Never throws for a signed-out
 * user: being signed out is a normal condition, not an error.
 */
async function identify(req) {
  if (!req.headers.cookie) return null
  try {
    const res = await fetchWithTimeout(`${TRACCAR_URL}/api/session`, {
      headers: { cookie: req.headers.cookie, accept: 'application/json' },
    })
    if (!res.ok) return null
    const user = await res.json()
    return user?.id ? user : null
  } catch {
    return null
  }
}

/** Traccar user -> tachograph role. Fails closed to the least privilege. */
export function tachoRole(user) {
  if (!user) return 'viewer'
  if (user.administrator === true) return 'owner'
  if (user.readonly === true) return 'viewer'
  return 'fleet_manager'
}

const SCRAP_ROLES = new Set(['owner', 'fleet_manager', 'warehouse_operator', 'viewer'])

/** Traccar user -> scrap role. Admins write; everyone else reads unless opted in. */
export function scrapRole(user) {
  if (!user) return 'viewer'
  if (user.administrator === true) return 'owner'
  if (user.readonly === true) return 'viewer'
  return SCRAP_ROLES.has(SCRAP_DEFAULT_ROLE) ? SCRAP_DEFAULT_ROLE : 'viewer'
}

// ---------------------------------------------------------------------------
// Routes
// ---------------------------------------------------------------------------

async function proxyTraccar(req, res, url) {
  const target = `${TRACCAR_URL}${url.pathname}${url.search}`
  const method = req.method || 'GET'
  const options = { method, headers: forwardHeaders(req), redirect: 'manual' }

  if (method !== 'GET' && method !== 'HEAD') {
    options.body = await readBody(req)
    // Traccar's login is form-encoded; keep the content-type the browser sent.
  }

  const upstream = await fetchWithTimeout(target, options)
  const body = Buffer.from(await upstream.arrayBuffer())
  res.writeHead(upstream.status, responseHeadersFrom(upstream))
  res.end(body)
}

async function proxyTacho(req, res, url) {
  if (!TACHO_TOKEN) {
    return sendJson(res, 503, {
      detail:
        'the dashboard has no TACHO_API_TOKEN configured, so it cannot reach the ' +
        'tachograph service',
    })
  }

  // Only the verbs the tachograph API exposes. Anything else is a mistake or an
  // attack; either way it does not need forwarding.
  const method = req.method || 'GET'
  if (!['GET', 'POST'].includes(method)) {
    return sendJson(res, 405, { detail: `${method} is not proxied` }, { Allow: 'GET, POST' })
  }

  const user = await identify(req)
  if (!user) {
    return sendJson(res, 401, {
      detail: 'sign in to Traccar first: the tachograph service needs a known user',
    })
  }

  // /tacho/api/... -> {TACHO_URL}/api/...
  const target = `${TACHO_URL}${url.pathname.replace(/^\/tacho/, '')}${url.search}`
  const headers = {
    // The service token proves this process is the dashboard. It is injected
    // here and never reaches the browser.
    authorization: `Bearer ${TACHO_TOKEN}`,
    accept: req.headers.accept || 'application/json',
    // The forwarded identity. The service validates the token above before it
    // trusts these, and it records both in its audit log.
    'x-actor': user.email || user.name || `user-${user.id}`,
    'x-actor-role': tachoRole(user),
  }
  if (req.headers['content-type']) headers['content-type'] = req.headers['content-type']

  const options = { method, headers, redirect: 'manual' }
  if (method !== 'GET' && method !== 'HEAD') options.body = await readBody(req)

  const upstream = await fetchWithTimeout(target, options)
  const body = Buffer.from(await upstream.arrayBuffer())
  res.writeHead(upstream.status, {
    ...responseHeadersFrom(upstream),
    // Driver personal data must not sit in any cache, anywhere.
    'Cache-Control': 'no-store, private',
  })
  res.end(body)
}

async function proxyScrap(req, res, url) {
  if (!SCRAP_TOKEN) {
    return sendJson(res, 503, {
      detail: 'the dashboard has no SCRAP_API_TOKEN configured, so it cannot reach the scrap service',
    })
  }
  const method = req.method || 'GET'
  if (!['GET', 'POST'].includes(method)) {
    return sendJson(res, 405, { detail: `${method} is not proxied` }, { Allow: 'GET, POST' })
  }
  const user = await identify(req)
  if (!user) {
    return sendJson(res, 401, {
      detail: 'sign in to Traccar first: the scrap service needs a known user',
    })
  }

  // /scrap/api/... -> {SCRAP_URL}/api/...
  const target = `${SCRAP_URL}${url.pathname.replace(/^\/scrap/, '')}${url.search}`
  const headers = {
    authorization: `Bearer ${SCRAP_TOKEN}`,
    accept: req.headers.accept || 'application/json',
    'x-actor': user.email || user.name || `user-${user.id}`,
    'x-actor-role': scrapRole(user),
  }
  if (req.headers['content-type']) headers['content-type'] = req.headers['content-type']
  // A retry of one action must carry the same key, or the service cannot dedupe it.
  if (req.headers['idempotency-key']) headers['idempotency-key'] = req.headers['idempotency-key']

  const options = { method, headers, redirect: 'manual' }
  if (method !== 'GET' && method !== 'HEAD') options.body = await readBody(req)

  const upstream = await fetchWithTimeout(target, options)
  const body = Buffer.from(await upstream.arrayBuffer())
  res.writeHead(upstream.status, {
    ...responseHeadersFrom(upstream),
    'Cache-Control': 'no-store, private',
  })
  res.end(body)
}

async function serveStatic(req, res, url) {
  if (!existsSync(DIST)) {
    return send(
      res,
      503,
      'The dashboard has not been built yet. Run `npm run build` first.\n'
    )
  }

  // normalize + prefix check: a request for /../../etc/passwd must not escape.
  const rel = normalize(decodeURIComponent(url.pathname)).replace(/^(\.\.[/\\])+/, '')
  let filePath = join(DIST, rel)
  if (!filePath.startsWith(DIST)) return send(res, 403, 'forbidden')

  try {
    const info = await stat(filePath)
    if (info.isDirectory()) filePath = join(filePath, 'index.html')
  } catch {
    // Client-side routing: an unknown path is a route in the SPA, not a 404.
    // Hashed asset paths are the exception — falling back to HTML for a missing
    // .js turns a broken build into a confusing MIME error, so let those 404.
    if (extname(rel)) return send(res, 404, 'not found')
    filePath = join(DIST, 'index.html')
  }

  try {
    await stat(filePath)
  } catch {
    return send(res, 404, 'not found')
  }

  const ext = extname(filePath)
  res.writeHead(200, {
    'Content-Type': MIME[ext] || 'application/octet-stream',
    // Hashed assets are immutable; index.html must never be.
    'Cache-Control': ext === '.html' ? 'no-store' : 'public, max-age=31536000, immutable',
  })
  createReadStream(filePath).pipe(res)
}

// ---------------------------------------------------------------------------
// Server
// ---------------------------------------------------------------------------

const server = createServer(async (req, res) => {
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`)

  try {
    if (url.pathname === '/healthz') {
      // Liveness only. It deliberately does not probe Traccar or the tachograph
      // service: a dashboard that reports unhealthy because a neighbour is down
      // gets restarted for no reason.
      return sendJson(res, 200, { status: 'ok' })
    }
    if (url.pathname === '/connect/status') return await serveConnectStatus(req, res)
    if (url.pathname.startsWith('/api/')) return await proxyTraccar(req, res, url)
    if (url.pathname === '/tacho' || url.pathname.startsWith('/tacho/')) {
      return await proxyTacho(req, res, url)
    }
    if (url.pathname === '/scrap' || url.pathname.startsWith('/scrap/')) {
      return await proxyScrap(req, res, url)
    }
    return await serveStatic(req, res, url)
  } catch (err) {
    const status = err?.code === 413 ? 413 : 502
    const detail =
      status === 413
        ? 'request body too large'
        : `upstream request failed: ${err?.message || String(err)}`
    console.error(`[dashboard] ${req.method} ${url.pathname} -> ${status}: ${detail}`)
    if (!res.headersSent) sendJson(res, status, { detail })
    else res.end()
  }
})

server.listen(PORT, HOST, () => {
  console.log(`[dashboard] listening on http://${HOST}:${PORT}`)
  console.log(`[dashboard] traccar       -> ${TRACCAR_URL}`)
  console.log(`[dashboard] tachograph    -> ${TACHO_URL}${TACHO_TOKEN ? '' : ' (no token set)'}`)
})
