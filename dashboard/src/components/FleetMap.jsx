import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import { COLOR, STATE } from '../lib/status'
import { NEUTRAL } from '../lib/palette'

// OpenStreetMap raster tiles. Free, no API key, no usage cap, no licence fee.
// If you later want satellite imagery you swap TILES for a paid provider --
// nothing else in the app changes.
const TILES = [
  'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
]
const ATTRIB =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'

// Great-circle distance in km. Used to spot a tracker that is reporting a
// position nowhere near the rest of the fleet.
function kmBetween(a, b) {
  const R = 6371
  const dLat = ((b[1] - a[1]) * Math.PI) / 180
  const dLng = ((b[0] - a[0]) * Math.PI) / 180
  const la1 = (a[1] * Math.PI) / 180
  const la2 = (b[1] * Math.PI) / 180
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLng / 2) ** 2
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)))
}

const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b)
  return s[Math.floor(s.length / 2)]
}

// Beyond this spread the auto-fit stops being useful and we pin a sensible
// zoom instead. ~250 km comfortably contains any single Italian/EU region.
const MAX_AUTO_FIT_SPREAD_KM = 250
const MIN_USEFUL_ZOOM = 6

// IMPORTANT -- a dependency-array rule for this file.
// Every effect below that early-returns on `if (!m || !ready) return` MUST list
// `ready` in its dependency array. `ready` flipping true does not by itself
// re-run those effects, so if the map finishes initialising after the last data
// change, nothing is ever drawn and the map stays blank. That bug shipped once:
// it worked when the data happened to arrive last, and produced an empty map
// when the map happened to arrive last. Same rule as "an effect that reads a
// value must depend on it".

export default function FleetMap({
  trucks,            // [{ device, position, state, ageS }]
  selectedId,
  onSelect,
  trail,             // [[lat,lng], ...] for trail history
  geofences,         // [{ id, name, area, color }]
  pickMode,          // when set, clicking the map calls onPick(lat,lng)
  onPick,
  geofenceVisible = true,
  fitToken = 0,          // bumped by the pane's "frame the fleet" button: the effect below depends on it, so a press re-frames the view
  t = (k) => k,          // translator, so the fallback notice is localised too
}) {
  const el = useRef(null)
  const map = useRef(null)
  const markers = useRef(new Map())   // deviceId -> Marker
  // "ready" means: the map object exists AND its style is loaded, so it is safe
  // to addSource/addLayer/Marker. Two mistakes taught me this must be state and
  // must not rely on a single event:
  //   1. as a useRef, setting it did not re-render, so every effect below stayed
  //      parked on its guard and the map rendered empty.
  //   2. listening only for 'load' is unreliable -- with a warm HTTP cache the
  //      map can finish before the listener is attached, and the event is lost
  //      forever. We also listen for styledata/idle, and we force ready after a
  //      timeout so a slow tile server can never leave the dashboard blank.
  const [ready, setReady] = useState(false)
  const [tileError, setTileError] = useState(false)

  // ---- init -------------------------------------------------------------
  useEffect(() => {
    if (map.current || !el.current) return
    const m = new maplibregl.Map({
      container: el.current,
      style: {
        version: 8,
        sources: {
          osm: { type: 'raster', tiles: TILES, tileSize: 256, attribution: ATTRIB },
        },
        layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
      },
      center: [9.19, 45.4642], // Milano
      zoom: 11,
      attributionControl: false,
      fadeDuration: 0,
    })
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    m.addControl(new maplibregl.AttributionControl({ compact: true }))

    const tryReady = () => { if (m.loaded()) setReady(true) }
    m.on('load', tryReady)
    m.on('styledata', tryReady)
    m.on('idle', tryReady)
    // Belt and braces. If the tile server is slow or blocked we still come up.
    const bail = setTimeout(() => { setTileError(true); tryReady() }, 6000)

    map.current = m
    // Dev-only handle so the live map can be inspected from the console or a
    // test harness (enumerate layers, check zoom, verify sources). Stripped
    // from production builds by the DEV guard.
    if (import.meta.env.DEV) window.__gtMap = m
    tryReady()
    return () => {
      clearTimeout(bail)
      m.remove()
      map.current = null
      markers.current.clear()
    }
  }, [])

  // ---- truck markers ----------------------------------------------------
  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    const seen = new Set()

    for (const t of trucks) {
      // valid === 0 means the receiver reported a bad fix. Drawing it would put
      // a truck at 0,0 or in the ocean and wreck the fleet view.
      if (!t.position || t.position.valid === 0) continue
      const p = [t.position.longitude, t.position.latitude]
      seen.add(t.device.id)
      const colour = COLOR[t.state] || COLOR[STATE.IDLE]
      const selected = t.device.id === selectedId
      const label = `<span class="dot" style="background:${colour}"></span>${t.device.name ?? ''}`

      let mk = markers.current.get(t.device.id)
      if (!mk) {
        const el = document.createElement('div')
        el.className = 'marker'
        el.innerHTML = label
        el.onclick = (e) => { e.stopPropagation(); onSelect(t.device.id) }
        mk = new maplibregl.Marker({ element: el, anchor: 'center' }).setLngLat(p).addTo(m)
        markers.current.set(t.device.id, mk)
      } else {
        mk.setLngLat(p)
        mk.getElement().innerHTML = label
        mk.getElement().classList.toggle('sel', selected)
        mk.getElement().classList.toggle('alert', t.state === STATE.ALERT)
      }
    }

    // drop markers for devices that no longer exist or have no position
    for (const [id, mk] of markers.current) {
      if (!seen.has(id)) { mk.remove(); markers.current.delete(id) }
    }
  }, [trucks, selectedId, onSelect, ready])

  // ---- geofence zones ---------------------------------------------------
  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    const src = m.getSource('geofences')
    const features = (geofences || [])
      // Traccar lets a geofence be flagged hidden so it still drives
      // enter/exit events without cluttering the map. Honour that flag.
      .filter((g) => String(g.attributes?.hidden ?? g.hidden ?? 'false') !== 'true')
      .map((g) => {
        const wkt = g.attributes?.area || g.area || ''
        const mt = wkt.match(/CIRCLE\s*\(\s*([\d.-]+)\s+([\d.-]+)\s*,\s*([\d.]+)\s*\)/i)
        if (!mt) return null
        // NOTE: WKT here is LATITUDE first, then longitude. This is Traccar's
        // convention and the reverse of what every mapping library expects.
        const [, latS, lonS, radS] = mt
        // A zone with no colour of its own is neutral, not green: green here
        // means "moving", and a parked zone is not moving.
        return circleFeature(+lonS, +latS, +radS, g.name, g.attributes?.color || NEUTRAL)
      })
      .filter(Boolean)

    const data = { type: 'FeatureCollection', features }
    if (src) { src.setData(data); return }
    try {
      if (m.getStyle()?.sources?.geofences) return
      m.addSource('geofences', { type: 'geojson', data })
    } catch { return }
    if (m.getLayer('geofences-fill')) return
    // These MUST be fill/line, not circle. circleFeature() returns a Polygon,
    // and a MapLibre `circle` layer only draws Point geometry -- given a polygon
    // it emits a dot at every vertex, so a 65-point zone outline rendered as a
    // "bead necklace" of 26px dots smeared across the whole city. The zone has
    // to be filled and stroked as the polygon it actually is.
    m.addLayer({
      id: 'geofences-fill', type: 'fill', source: 'geofences',
      paint: { 'fill-color': ['get', 'color'], 'fill-opacity': 0.13 },
    })
    m.addLayer({
      id: 'geofences-line', type: 'line', source: 'geofences',
      paint: { 'line-color': ['get', 'color'], 'line-opacity': 0.9, 'line-width': 2 },
    })
  }, [geofences, ready])

  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    for (const l of ['geofences-fill', 'geofences-line']) {
      if (m.getLayer(l)) m.setLayoutProperty(l, 'visibility', geofenceVisible ? 'visible' : 'none')
    }
  }, [geofenceVisible, ready])

  // ---- trail line -------------------------------------------------------
  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    const coords = (trail || []).map(([lat, lon]) => [lon, lat])
    const data = { type: 'Feature', geometry: { type: 'LineString', coordinates: coords } }
    if (m.getSource('trail')) { m.getSource('trail').setData(data); return }
    // eslint-disable-next-line
    try {
      if (m.getStyle()?.sources?.trail) return
      m.addSource('trail', { type: 'geojson', data })
    } catch { return }
    if (m.getLayer('trail-line')) return
    m.addLayer({
      id: 'trail-line', type: 'line', source: 'trail',
      paint: { 'line-color': COLOR[STATE.MOVING], 'line-width': 3, 'line-opacity': 0.9 },
    })
  }, [trail, ready])

  // ---- pick mode (geofence creation) ------------------------------------
  useEffect(() => {
    const m = map.current
    if (!m) return
    const onClick = (e) => { if (pickMode && onPick) onPick(e.lngLat.lat, e.lngLat.lng) }
    if (pickMode) { m.getCanvas().style.cursor = 'crosshair'; m.on('click', onClick) }
    return () => {
      m.getCanvas().style.cursor = ''
      m.off('click', onClick)
    }
  }, [pickMode, onPick])

  // ---- fit to fleet -----------------------------------------------------
  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    const pts = trucks
      .filter((t) => t.position && t.position.valid !== 0)
      .map((t) => [t.position.longitude, t.position.latitude])
    if (pts.length === 0) return
    if (pts.length === 1) { m.easeTo({ center: pts[0], zoom: 13 }); return }

    // Fit to the cluster, not to the whole set. One truck whose tracker reports
    // a garbage fix thousands of km away would otherwise drag the view out to a
    // continent and collapse every other marker into a single dot -- which is
    // exactly what happened here. Real trackers do produce bad fixes, so this
    // is not a demo-data-only concern.
    //
    // Note: fitBounds() has NO minZoom option. MapLibre 4.7 computes the zoom as
    // min(zoomCoveringBounds, options.maxZoom) and silently ignores anything
    // else, so a minZoom passed here is discarded without warning. The floor
    // has to be enforced by us, which is what the spread check below does.
    const mid = [median(pts.map((p) => p[0])), median(pts.map((p) => p[1]))]
    const near = pts.filter((p) => kmBetween(mid, p) <= MAX_AUTO_FIT_SPREAD_KM)
    const use = near.length >= 2 ? near : pts

    const spreadKm = Math.max(...use.map((p) => kmBetween(mid, p)))
    if (spreadKm > MAX_AUTO_FIT_SPREAD_KM) {
      // Fleet is genuinely too spread out to frame. Pin a usable regional zoom
      // on the centre of the fleet; the dispatcher can zoom out by hand.
      m.easeTo({ center: mid, zoom: MIN_USEFUL_ZOOM, duration: 600 })
      return
    }

    const b = use.reduce((a, p) => a.extend(p), new maplibregl.LngLatBounds(use[0], use[0]))
    m.fitBounds(b, { padding: 90, maxZoom: 14, duration: 600 })
  }, [trucks, ready, fitToken])

  return (
    <div className="map" ref={el}>
      {!ready && (
        <div className="mapwait">
          {tileError ? t('mapUnavailable') : '…'}
        </div>
      )}
    </div>
  )
}

function circleFeature(lon, lat, rMetres, name, color) {
  const pts = []
  const steps = 64
  // metres per degree at this latitude
  const mLat = 111320
  const mLon = 111320 * Math.cos((lat * Math.PI) / 180)
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * Math.PI * 2
    pts.push([lon + (rMetres * Math.cos(a)) / mLon, lat + (rMetres * Math.sin(a)) / mLat])
  }
  return {
    type: 'Feature',
    properties: { r: rMetres, name, color },
    geometry: { type: 'Polygon', coordinates: [pts] },
  }
}
