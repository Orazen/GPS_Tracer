import { useEffect, useState } from 'react'
import { api } from '../api/traccar'
import { NEUTRAL, ZONE } from '../lib/palette'
import { SectionGroup } from './Section'
import FleetMap from './FleetMap'

/**
 * Draw and manage customer sites.
 *
 * The core interaction is "click the map where the customer is". That needs a
 * pick mode, and it needs to be obvious -- an invisible click target on a map
 * is a support ticket waiting to happen. So pick mode is an explicit, toggled
 * state with a visible crosshair cursor and a live readout of what will be
 * saved.
 *
 * Traccar stores geofence areas as WKT with LATITUDE FIRST:
 *     CIRCLE (45.4642 9.1900, 500)
 * This is the single most common integration mistake with Traccar. Every write
 * and read in this file is explicit about the order.
 */

// Zone colours come from the shared palette so the picker and the map cannot
// disagree. The previous list was the framework's default ramp, purple and all.
const RADII = [100, 250, 500, 1000, 2000, 5000]

const wktToLatLng = (wkt) => {
  const m = (wkt || '').match(/CIRCLE\s*\(\s*([\d.-]+)\s+([\d.-]+)\s*,\s*([\d.]+)\s*\)/i)
  if (!m) return null
  // WKT order is (lat, lon, radius) -- NOT lon/lat.
  return { lat: +m[1], lon: +m[2], r: +m[3] }
}

const latLngToWkt = (lat, lon, r) => `CIRCLE (${lat} ${lon}, ${r})`

export default function GeofenceManager({ devices, geofences, onChanged, t, lang }) {
  const [picking, setPicking] = useState(false)
  const [pending, setPending] = useState(null)      // { lat, lon }
  const [name, setName] = useState('')
  const [radius, setRadius] = useState(500)
  const [color, setColor] = useState(ZONE[0])
  const [hidden, setHidden] = useState(false)
  const [editing, setEditing] = useState(null)      // geofence id
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  // Entering pick mode clears the form so a stray click cannot overwrite an
  // existing site.
  const startPick = () => {
    setEditing(null)
    setPending(null)
    setName('')
    setErr(null)
    setPicking(true)
  }

  const onPick = (lat, lon) => {
    setPending({ lat, lon })
    setPicking(false)
    if (!name) setName(t('newSite'))
  }

  const save = async () => {
    if (!pending) return
    setBusy(true)
    setErr(null)
    try {
      const body = {
        name: name.trim() || t('newSite'),
        area: latLngToWkt(pending.lat, pending.lon, radius),
        // hidden is a STRING in Traccar's attributes, not a boolean.
        attributes: { color, hidden: String(!!hidden) },
      }
      if (editing) await api.updateGeofence(editing, body)
      else await api.createGeofence(body)
      setPending(null)
      setEditing(null)
      setName('')
      await onChanged()
    } catch (e) {
      setErr(e.auth ? t('sessionExpired') : String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  const startEdit = (g) => {
    const p = wktToLatLng(g.area || g.attributes?.area)
    if (!p) return
    setEditing(g.id)
    setPending({ lat: p.lat, lon: p.lon })
    setName(g.name)
    setRadius(p.r)
    setColor(g.attributes?.color || ZONE[0])
    setHidden(String(g.attributes?.hidden ?? 'false') === 'true')
    setErr(null)
  }

  const remove = async (g) => {
    if (!confirm(t('confirmDelete').replace('{n}', g.name))) return
    setBusy(true)
    setErr(null)
    try {
      await api.deleteGeofence(g.id)
      if (editing === g.id) { setEditing(null); setPending(null) }
      await onChanged()
    } catch (e) {
      setErr(e.auth ? t('sessionExpired') : String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  const cancel = () => { setEditing(null); setPending(null); setName(''); setErr(null) }

  // Show the zone being created/edited as a preview circle.
  const preview = pending
    ? [{ id: -1, name: name || t('newSite'), area: latLngToWkt(pending.lat, pending.lon, radius), attributes: { color, hidden: 'false' } }]
    : []

  return (
    <div className="geo">
      <div className="geo-list">
        <div className="sections">
        <SectionGroup
          icon="zones"
          title={t('sites')}
          sub={t('sitesWhy')}
          end={<span className="count">{geofences.length}</span>}
        >
        <div className="geo-actions">
          <button className="btn primary" onClick={startPick} disabled={busy}>
            {picking ? t('clickMap') : t('addSite')}
          </button>
          {picking && <button className="btn ghost" onClick={() => setPicking(false)}>{t('cancel')}</button>}
        </div>

        {pending && (
          <div className="geo-form">
            <p className="muted small mono">
              {pending.lat.toFixed(5)}, {pending.lon.toFixed(5)} · {radius} m
            </p>
            <input
              value={name}
              placeholder={t('siteName')}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
            <div className="geo-rad">
              {RADII.map((r) => (
                <button
                  key={r}
                  className={`chip ${radius === r ? 'on' : ''}`}
                  onClick={() => setRadius(r)}
                >
                  {r >= 1000 ? `${r / 1000} km` : `${r} m`}
                </button>
              ))}
            </div>
            <div className="geo-rad">
              {ZONE.map((c) => (
                <button
                  key={c}
                  className={`swatch ${color === c ? 'on' : ''}`}
                  style={{ background: c }}
                  onClick={() => setColor(c)}
                  aria-label={c}
                />
              ))}
              <label className="geo-hidden">
                <input type="checkbox" checked={hidden} onChange={(e) => setHidden(e.target.checked)} />
                <span className="small">{t('hidden')}</span>
              </label>
            </div>
            <div className="geo-save">
              <button className="btn primary" onClick={save} disabled={busy}>
                {editing ? t('saveChanges') : t('save')}
              </button>
              <button className="btn ghost" onClick={cancel}>{t('cancel')}</button>
            </div>
            {err && <p className="err small">{err}</p>}
          </div>
        )}

        </SectionGroup>

        {/* The list of sites keeps the card language it already had: `.rows` is a
            stack of white cards, and a white card inside a white card is the
            nesting this restyle removed everywhere else, so this group carries
            no surface of its own. */}
        <SectionGroup icon="fleet" title={t('siteList')} card={null}>
        <ul className="rows">
          {geofences.map((g) => {
            const p = wktToLatLng(g.area || g.attributes?.area)
            const isHidden = String(g.attributes?.hidden ?? 'false') === 'true'
            return (
              <li key={g.id} className={editing === g.id ? 'on' : ''}>
                <div className="rowmain">
                  <span className="gdot" style={{ background: g.attributes?.color || NEUTRAL }} />
                  <strong>{g.name}</strong>
                  {isHidden && <span className="tag muted">{t('hidden')}</span>}
                </div>
                <span className="muted small">
                  {p ? `${p.r} m · ${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}` : t('noArea')}
                </span>
                <div className="geo-rowbtns">
                  <button className="btn tiny ghost" onClick={() => startEdit(g)}>{t('edit')}</button>
                  <button className="btn tiny danger" onClick={() => remove(g)}>{t('delete')}</button>
                </div>
              </li>
            )
          })}
        </ul>
        </SectionGroup>
        </div>
      </div>

      <div className="mapwrap geo-map">
        <FleetMap
          trucks={devices.trucks}
          selectedId={devices.selectedId}
          onSelect={devices.onSelect}
          geofences={[...geofences, ...preview]}
          pickMode={picking}
          onPick={onPick}
          t={t}
        />
        {picking && <div className="picking-hint">{t('clickMapHint')}</div>}
      </div>
    </div>
  )
}
