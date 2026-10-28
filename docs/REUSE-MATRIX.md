# Open-source reuse matrix (GPS_Tracer)

Verified 28 Oct 2026 against the public GitHub repositories.

| Repository | URL | License | Activity | Useful modules | Risks | Decision |
|---|---|---|---|---|---|---|
| Traccar | https://github.com/traccar/traccar | Apache-2.0 | Very active (8k stars, 10k+ commits, 6.16 release) | GPS protocol decoding (200+), trips, geofences, events, reports, REST API, WebSocket, RBAC | None for integration; GPL confusion avoided (Apache-2.0) | **Integrate as separate service** through REST API and device protocol. Do not reimplement protocol parsing. |
| FleetTrack | https://github.com/damir-bubanovic/FleetTrack | No LICENSE file (all rights reserved by default) | Low (2 stars, 0 forks, 143 commits, last 2026-09-28) | Laravel + Vue + Inertia + Traccar integration patterns, RBAC, device sync, alerts, reports | Unlicensed code cannot be reused legally; small/unmaintained | **Do not copy code.** Study architecture and feature list as design reference only. |
| Fleetbase | https://github.com/fleetbase/fleetbase | AGPL-3.0 or commercial FCL | Very active (4.4k stars, 1.5k commits) | Modular LSOS: fleet-ops, pallet (WMS), ledger, IAM, webhooks, extensions | AGPL network clause obliges source release on network use; heavy multi-service stack | **Do not copy code.** Study module boundaries and ERD; keep proprietary. |
| Inventory | https://github.com/ztothez/Inventory | Proprietary (all rights reserved) | Low (0 stars, 11 commits) | Stock reservation, completion with scrap/remnant, audit trail, low-stock alerts, CSV export | No reuse permitted | **Do not copy code.** Reimplement stock ledger concepts (receipts/issues/transfers/adjustments) independently. |

## License notes

- Traccar is the only candidate whose license (Apache-2.0) permits integration into a proprietary, self-hosted product without source disclosure. It is the chosen GPS engine.
- Fleetbase's AGPL-3.0 would force publication of any network-served modification, which conflicts with a private client deployment unless the commercial license (FCL) is purchased. We avoid it.
- FleetTrack and Inventory have no usable license; treat as read-only references.

## Integration decision

- Keep Traccar as the GPS engine (already deployed). Integrate via its REST API and webhooks; never duplicate position storage.
- Build business modules (loads, weighing, inventory, sales, traceability) as a separate service (`scrap/`) on the same PostgreSQL instance, in a `scrap_` namespace, mirroring the existing `tacho_` pattern.
- Reuse patterns (service token auth, migrations, audit log) from the in-repo tachograph service, not from external repos.