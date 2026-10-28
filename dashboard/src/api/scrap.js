// Scrap / inventory service client.
//
// Talks to `/scrap/*` on the dashboard's own origin, never to the scrap API
// directly. The scrap service authenticates the dashboard with a service token
// that only `dashboard/server.mjs` holds. The server maps the signed-in Traccar
// user to a scrap role and forwards it, so this module never sends a token or a
// role. Credentials here are only the session cookie the browser already has.
//
// Mutating calls send an `Idempotency-Key`. Pass the same key again when retrying
// the same action so the server returns the original result instead of posting a
// second load, weigh ticket, stock movement, order or delivery. Only the endpoints
// listed in the JSDoc below honour the key.

const BASE = '/scrap/api'

/**
 * Error thrown for any non-2xx response. Network failures are not wrapped; they
 * surface as the underlying fetch TypeError.
 * @extends Error
 */
export class ScrapError extends Error {
  /**
   * @param {string} message
   * @param {{ status: number, detail: string, method: string, path: string }} info
   */
  constructor(message, { status, detail, method, path }) {
    super(message)
    this.name = 'ScrapError'
    /** @type {number} HTTP status code. */
    this.status = status
    /** @type {string} Server `detail` text, or ''. */
    this.detail = detail
    this.method = method
    this.path = path
    /** @type {boolean} 401: sign in again. */
    this.unauthorised = status === 401
    /** @type {boolean} 403: the signed-in role may not perform this action. */
    this.forbidden = status === 403
  }
}

/**
 * A fresh key for one logical action. Use `crypto.randomUUID` where available;
 * insecure (plain-http LAN) contexts lack it, so fall back to random bytes.
 * @returns {string}
 */
export function newIdempotencyKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

const enc = (value) => encodeURIComponent(String(value))

function queryString(params) {
  const entries = Object.entries(params || {}).filter(
    ([, v]) => v !== undefined && v !== null && v !== ''
  )
  if (!entries.length) return ''
  return '?' + new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString()
}

function detailText(detail) {
  if (typeof detail === 'string') return detail
  // FastAPI validation errors arrive as a list of { loc, msg, type }.
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && d.msg) || JSON.stringify(d)).join('; ')
  }
  return detail ? JSON.stringify(detail) : ''
}

/**
 * @param {string} method
 * @param {string} path  path below /scrap/api, starting with '/'
 * @param {{ body?: unknown, params?: Record<string, unknown>, key?: string }} [opts]
 * @returns {Promise<any>} parsed JSON body
 */
async function request(method, path, { body, params, key } = {}) {
  const headers = { Accept: 'application/json' }
  const options = { method, credentials: 'include', headers }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(body)
  }
  if (key !== undefined) headers['Idempotency-Key'] = key

  const res = await fetch(BASE + path + queryString(params), options)
  const text = await res.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }

  if (!res.ok) {
    const detail =
      data && typeof data === 'object' ? detailText(data.detail) : typeof data === 'string' ? data.slice(0, 200) : ''
    throw new ScrapError(`${method} ${path} -> ${res.status}${detail ? `: ${detail}` : ''}`, {
      status: res.status,
      detail,
      method,
      path,
    })
  }
  return data
}

/**
 * Mutating call. Only endpoints that honour Idempotency-Key pass `idempotent: true`.
 * For those, a missing key gets a fresh one, which guards against a double-submit
 * from this call only. A caller that retries must pass the key it used the first time.
 * @param {string} path
 * @param {{ body?: unknown, params?: Record<string, unknown>, key?: string | null, idempotent?: boolean }} [opts]
 */
function write(path, { body, params, key, idempotent = false } = {}) {
  const headerKey = idempotent ? key ?? newIdempotencyKey() : undefined
  return request('POST', path, { body, params, key: headerKey })
}

/**
 * @typedef {{ code: string, name: string, category: string, unit: string, created_at?: string }} Material
 * @typedef {{ code: string, name: string, location?: string | null, created_at?: string }} Warehouse
 * @typedef {{ code: string, name: string, email?: string | null, phone?: string | null, created_at?: string }} Customer
 * @typedef {{ load_id: string, truck_ref?: string | null, driver_ref?: string | null, customer_ref?: string | null,
 *   supplier_ref?: string | null, origin?: string | null, destination?: string | null, material_code?: string | null,
 *   status: string, created_by?: string | null, created_at?: string | null, updated_at?: string | null }} Load
 * @typedef {{ id: number, gross: number, tare: number, net: number, unit: string, ticket_number?: string | null,
 *   scale_ref?: string | null, operator?: string | null, weighed_at?: string | null,
 *   active: boolean, superseded_at?: string | null, supersede_reason?: string | null }} WeighTicket
 * @typedef {{ id: number, material_code: string, warehouse_code: string, movement_type: string, quantity: number,
 *   unit: string, reference?: string | null, actor?: string | null, reason?: string | null, created_at?: string }} Movement
 * @typedef {{ order_number: string, customer_code?: string | null, load_id?: string | null, status: string,
 *   total_amount: number, currency: string, created_at?: string }} OrderSummary
 * @typedef {{ material_code: string, quantity: number, unit: string, price_per_unit: number, line_total: number }} OrderItem
 */

export const scrap = {
  /** @returns {Promise<{ service_version: string, scrap: boolean }>} */
  meta: () => request('GET', '/meta'),

  materials: {
    /** @returns {Promise<{ count: number, materials: Material[] }>} */
    list: () => request('GET', '/materials'),
    /**
     * @param {{ code: string, name: string, category: string, unit?: string }} body
     * @returns {Promise<Material>}
     */
    create: (body) => write('/materials', { body }),
  },

  warehouses: {
    /** @returns {Promise<{ count: number, warehouses: Warehouse[] }>} */
    list: () => request('GET', '/warehouses'),
    /**
     * @param {{ code: string, name: string, location?: string }} body
     * @returns {Promise<Warehouse>}
     */
    create: (body) => write('/warehouses', { body }),
  },

  customers: {
    /** @returns {Promise<{ count: number, customers: Customer[] }>} */
    list: () => request('GET', '/customers'),
    /**
     * @param {{ code: string, name: string, email?: string, phone?: string }} body
     * @returns {Promise<Customer>}
     */
    create: (body) => write('/customers', { body }),
  },

  loads: {
    /**
     * @param {{ status?: string, limit?: number, offset?: number }} [params]
     * @returns {Promise<{ count: number, loads: Load[] }>}
     */
    list: (params = {}) => request('GET', '/loads', { params }),
    /**
     * Honours Idempotency-Key: a retry returns the original load.
     * @param {Partial<Load>} body
     * @param {string} [key]
     * @returns {Promise<{ load_id: string, qr_available: boolean, load: Load }>}
     */
    create: (body, key) => write('/loads', { body, key, idempotent: true }),
    /** @param {string} loadId @returns {Promise<Load>} */
    get: (loadId) => request('GET', `/loads/${enc(loadId)}`),
    /**
     * Does not honour Idempotency-Key; setting a status to its current value is a no-op.
     * @param {string} loadId
     * @param {string} status
     * @returns {Promise<Load>}
     */
    setStatus: (loadId, status) => write(`/loads/${enc(loadId)}/status`, { params: { status } }),
  },

  weigh: {
    /**
     * Honours Idempotency-Key. A load already weighed is refused with 409 unless
     * `allow_reweigh` is true and `supersede_reason` is given; the earlier ticket is
     * then kept but marked superseded.
     * @param {{ load_id: string, gross: number, tare: number, unit?: string, ticket_number?: string,
     *   scale_ref?: string, allow_reweigh?: boolean, supersede_reason?: string }} body
     * @param {string} [key]
     * @returns {Promise<{ ticket_id: number, load_id: string, gross: number, tare: number, net: number, unit: string,
     *   superseded_ticket_ids: number[] }>}
     */
    create: (body, key) => write('/weigh', { body, key, idempotent: true }),
    /** @param {string} loadId @returns {Promise<{ count: number, tickets: WeighTicket[] }>} */
    listByLoad: (loadId) => request('GET', `/loads/${enc(loadId)}/weigh-tickets`),
  },

  stock: {
    /**
     * @param {{ material_code: string, warehouse_code: string }} params
     * @returns {Promise<{ material_code: string, warehouse_code: string, balance: number }>}
     */
    balance: (params) => request('GET', '/stock/balance', { params }),
    /**
     * @param {{ material_code?: string, warehouse_code?: string, limit?: number }} [params]
     * @returns {Promise<{ count: number, movements: Movement[] }>}
     */
    movements: (params = {}) => request('GET', '/stock/movements', { params }),
    /**
     * Movements are append-only. Corrections are a further `adjustment` with a
     * signed quantity and a required reason. Honours Idempotency-Key.
     * @param {{ material_code: string, warehouse_code: string, movement_type: string, quantity: number,
     *   unit?: string, reference?: string, reason?: string }} body
     * @param {string} [key]
     * @returns {Promise<{ movement_id: number, new_balance: number }>}
     */
    createMovement: (body, key) => write('/stock/movements', { body, key, idempotent: true }),
  },

  orders: {
    /**
     * @param {{ status?: string, limit?: number }} [params]
     * @returns {Promise<{ count: number, orders: OrderSummary[] }>}
     */
    list: (params = {}) => request('GET', '/orders', { params }),
    /**
     * Honours Idempotency-Key.
     * @param {{ customer_code?: string, load_id?: string, currency?: string,
     *   items: Array<{ material_code: string, quantity: number, unit?: string, price_per_unit?: number }> }} body
     * @param {string} [key]
     * @returns {Promise<OrderSummary & { items: OrderItem[], deliveries: Array<Record<string, unknown>> }>}
     */
    create: (body, key) => write('/orders', { body, key, idempotent: true }),
    /** @param {string} orderNumber */
    get: (orderNumber) => request('GET', `/orders/${enc(orderNumber)}`),
  },

  deliveries: {
    /**
     * Honours Idempotency-Key.
     * @param {{ order_number: string, load_id?: string, notes?: string }} body
     * @param {string} [key]
     * @returns {Promise<{ delivery_id: number, order_number: string }>}
     */
    create: (body, key) => write('/deliveries', { body, key, idempotent: true }),
    /**
     * Single-shot. A second confirm is refused with 409 and the first confirmation is kept.
     * Does not honour Idempotency-Key.
     * @param {number} deliveryId
     * @param {{ delivered_by: string, notes?: string }} body
     * @returns {Promise<{ delivery_id: number, status: string, delivered_at: string, delivered_by: string }>}
     */
    confirm: (deliveryId, body) => write(`/deliveries/${enc(deliveryId)}/confirm`, { body }),
  },

  /**
   * Everything linked to a load: load, weigh tickets (including superseded), stock movements, orders.
   * @param {string} loadId
   */
  trace: (loadId) => request('GET', `/trace/${enc(loadId)}`),

  /**
   * @param {{ limit?: number }} [params]
   * @returns {Promise<{ count: number, entries: Array<Record<string, unknown>> }>}
   */
  audit: (params = {}) => request('GET', '/audit', { params }),

  /** URL for the CSV download; navigate to it rather than fetching it. */
  loadsCsvUrl: () => `${BASE}/reports/loads.csv`,
}
