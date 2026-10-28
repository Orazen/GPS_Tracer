// Checks the /scrap proxy in server.mjs against a stub Traccar and a stub scrap
// service. Run: node scripts/scrap-proxy-check.mjs
// Exit 0 only if every assertion holds. Needs no database and no Docker.
import { spawn } from 'node:child_process'
import http from 'node:http'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const SERVER = join(HERE, '..', 'server.mjs')
const SCRAP_TOKEN = 'proxy-check-token-0123456789abcdef'

let failures = 0
const seen = []
const check = (name, ok, extra = '') => {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${extra ? ` (${extra})` : ''}`)
  if (!ok) failures++
}

function listen(server) {
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server.address().port)))
}

// Stub Traccar: a session exists only for cookie "good".
const users = { good: { id: 7, email: 'dispatch@example.com', administrator: false }, admin: { id: 1, email: 'boss@example.com', administrator: true } }
const traccar = http.createServer((req, res) => {
  const cookie = (req.headers.cookie || '').replace('JSESSIONID=', '')
  if (req.url === '/api/session' && users[cookie]) {
    res.writeHead(200, { 'content-type': 'application/json' })
    return res.end(JSON.stringify(users[cookie]))
  }
  res.writeHead(404).end()
})

// Stub scrap: records what the dashboard forwarded.
const scrap = http.createServer((req, res) => {
  let body = ''
  req.on('data', (c) => (body += c))
  req.on('end', () => {
    seen.push({ method: req.method, url: req.url, headers: req.headers, body })
    res.writeHead(200, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ ok: true }))
  })
})

const traccarPort = await listen(traccar)
const scrapPort = await listen(scrap)
const dashPort = 18000 + Math.floor(Math.random() * 1000)

const env = {
  ...process.env,
  PORT: String(dashPort),
  DASHBOARD_HOST: '127.0.0.1',
  TRACCAR_INTERNAL_URL: `http://127.0.0.1:${traccarPort}`,
  SCRAP_INTERNAL_URL: `http://127.0.0.1:${scrapPort}`,
  SCRAP_API_TOKEN: SCRAP_TOKEN,
  TACHO_API_TOKEN: 'unused-tacho-token-0123456789abcdef',
}
const child = spawn(process.execPath, [SERVER], { env, stdio: ['ignore', 'pipe', 'pipe'] })
let childLog = ''
child.stdout.on('data', (d) => (childLog += d))
child.stderr.on('data', (d) => (childLog += d))

const base = `http://127.0.0.1:${dashPort}`
for (let i = 0; i < 50; i++) {
  try { await fetch(`${base}/healthz`); break } catch { await new Promise((r) => setTimeout(r, 100)) }
}

try {
  // 1. No session: refused before anything reaches the scrap service.
  seen.length = 0
  let r = await fetch(`${base}/scrap/api/loads`)
  check('anonymous request is refused with 401', r.status === 401, `got ${r.status}`)
  check('anonymous request never reaches scrap', seen.length === 0)

  // 2. Signed-in non-admin: forwarded as viewer by default, token injected here.
  seen.length = 0
  r = await fetch(`${base}/scrap/api/loads?status=created`, { headers: { cookie: 'JSESSIONID=good' } })
  check('signed-in request succeeds', r.status === 200, `got ${r.status}`)
  const f = seen[0] || { headers: {} }
  check('service token is injected server-side', f.headers.authorization === `Bearer ${SCRAP_TOKEN}`)
  check('actor is the Traccar email', f.headers['x-actor'] === 'dispatch@example.com', f.headers['x-actor'])
  check('non-admin defaults to viewer (read-only)', f.headers['x-actor-role'] === 'viewer', f.headers['x-actor-role'])
  check('query string is preserved', f.url === '/api/loads?status=created', f.url)
  check('upstream response carries no-store', /no-store/.test(r.headers.get('cache-control') || ''))

  // 3. A client-supplied role header is ignored.
  seen.length = 0
  await fetch(`${base}/scrap/api/loads`, { headers: { cookie: 'JSESSIONID=good', 'x-actor-role': 'owner', 'x-actor': 'mallory' } })
  check('client-supplied role is not trusted', seen[0]?.headers['x-actor-role'] === 'viewer', seen[0]?.headers['x-actor-role'])
  check('client-supplied actor is not trusted', seen[0]?.headers['x-actor'] === 'dispatch@example.com', seen[0]?.headers['x-actor'])

  // 4. Administrator maps to owner.
  seen.length = 0
  await fetch(`${base}/scrap/api/loads`, { headers: { cookie: 'JSESSIONID=admin' } })
  check('administrator maps to owner', seen[0]?.headers['x-actor-role'] === 'owner', seen[0]?.headers['x-actor-role'])

  // 5. Idempotency key forwarded on writes; body forwarded intact.
  seen.length = 0
  r = await fetch(`${base}/scrap/api/loads`, {
    method: 'POST',
    headers: { cookie: 'JSESSIONID=admin', 'content-type': 'application/json', 'idempotency-key': 'key-abc-123' },
    body: JSON.stringify({ truck_ref: 'T1' }),
  })
  check('POST is proxied', seen[0]?.method === 'POST', seen[0]?.method)
  check('idempotency-key is forwarded', seen[0]?.headers['idempotency-key'] === 'key-abc-123')
  check('POST body is forwarded intact', seen[0]?.body === '{"truck_ref":"T1"}', seen[0]?.body)

  // 6. Other verbs are refused, not forwarded.
  seen.length = 0
  r = await fetch(`${base}/scrap/api/loads/LOAD-1`, { method: 'DELETE', headers: { cookie: 'JSESSIONID=admin' } })
  check('DELETE is refused with 405', r.status === 405, `got ${r.status}`)
  check('DELETE never reaches scrap', seen.length === 0)

  // 7. The token never appears in anything the browser receives.
  const dashboardText = await (await fetch(`${base}/scrap/api/loads`, { headers: { cookie: 'JSESSIONID=good' } })).text()
  check('token is not echoed to the browser', !dashboardText.includes(SCRAP_TOKEN))
} finally {
  child.kill('SIGTERM')
  traccar.close()
  scrap.close()
}

if (failures) {
  console.error(`\n${failures} check(s) FAILED`)
  console.error(childLog.slice(-800))
  process.exit(1)
}
console.log('\nall scrap proxy checks passed')
