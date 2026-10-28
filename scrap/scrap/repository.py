"""Repository helpers for the scrap service.

Writes that return rows run inside Database.transaction(). Idempotent creates use
INSERT ... ON CONFLICT (idempotency_key) DO NOTHING and return (ref, created,
stored_request_hash), so the API layer can tell a fresh write from a replay.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .db import Database
from .domain.stock import Movement, would_go_negative


class RepositoryError(Exception):
    pass


class NotFound(RepositoryError):
    pass


class Conflict(RepositoryError):
    pass


Claim = Tuple[Any, bool, Optional[str]]


class ScrapRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _require(cur, sql: str, params: Sequence[Any], message: str) -> None:
        cur.execute(sql, params)
        if cur.fetchone() is None:
            raise NotFound(message)

    # -- materials --------------------------------------------------------
    def create_material(self, code: str, name: str, category: str, unit: str = "kg") -> Dict[str, Any]:
        self.db.execute(
            "INSERT INTO scrap_materials (code, name, category, unit) VALUES (%s, %s, %s, %s)",
            (code, name, category, unit),
        )
        return {"code": code, "name": name, "category": category, "unit": unit}

    def list_materials(self) -> List[Dict[str, Any]]:
        rows = self.db.fetch_all("SELECT code, name, category, unit, created_at FROM scrap_materials ORDER BY code")
        return [
            {"code": r[0], "name": r[1], "category": r[2], "unit": r[3], "created_at": r[4].isoformat() if r[4] else None}
            for r in rows
        ]

    def get_material(self, code: str) -> Optional[Dict[str, Any]]:
        row = self.db.fetch_one("SELECT code, name, category, unit FROM scrap_materials WHERE code = %s", (code,))
        if not row:
            return None
        return {"code": row[0], "name": row[1], "category": row[2], "unit": row[3]}

    # -- warehouses -------------------------------------------------------
    def create_warehouse(self, code: str, name: str, location: Optional[str] = None) -> Dict[str, Any]:
        self.db.execute(
            "INSERT INTO scrap_warehouses (code, name, location) VALUES (%s, %s, %s)",
            (code, name, location),
        )
        return {"code": code, "name": name, "location": location}

    def list_warehouses(self) -> List[Dict[str, Any]]:
        rows = self.db.fetch_all("SELECT code, name, location, created_at FROM scrap_warehouses ORDER BY code")
        return [{"code": r[0], "name": r[1], "location": r[2], "created_at": r[3].isoformat() if r[3] else None} for r in rows]

    # -- loads ------------------------------------------------------------
    def create_load(
        self,
        truck_ref: Optional[str] = None,
        driver_ref: Optional[str] = None,
        customer_ref: Optional[str] = None,
        supplier_ref: Optional[str] = None,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        material_code: Optional[str] = None,
        created_by: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        request_hash: Optional[str] = None,
    ) -> Claim:
        load_id = "LOAD-" + uuid.uuid4().hex[:10].upper()
        with self.db.transaction() as cur:
            cur.execute(
                """INSERT INTO scrap_loads
                   (load_id, truck_ref, driver_ref, customer_ref, supplier_ref, origin, destination, material_code,
                    created_by, idempotency_key, request_hash)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (idempotency_key) DO NOTHING
                   RETURNING load_id""",
                (load_id, truck_ref, driver_ref, customer_ref, supplier_ref, origin, destination, material_code,
                 created_by, idempotency_key, request_hash),
            )
            if cur.fetchone() is not None:
                return load_id, True, request_hash
            cur.execute("SELECT load_id, request_hash FROM scrap_loads WHERE idempotency_key = %s", (idempotency_key,))
            existing = cur.fetchone()
        return existing[0], False, existing[1]

    def get_load(self, load_id: str) -> Optional[Dict[str, Any]]:
        row = self.db.fetch_one(
            """SELECT load_id, truck_ref, driver_ref, customer_ref, supplier_ref, origin, destination,
                      material_code, status, created_by, created_at, updated_at
               FROM scrap_loads WHERE load_id = %s""",
            (load_id,),
        )
        if not row:
            return None
        return {
            "load_id": row[0], "truck_ref": row[1], "driver_ref": row[2], "customer_ref": row[3],
            "supplier_ref": row[4], "origin": row[5], "destination": row[6], "material_code": row[7],
            "status": row[8], "created_by": row[9],
            "created_at": row[10].isoformat() if row[10] else None,
            "updated_at": row[11].isoformat() if row[11] else None,
        }

    def list_loads(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        if status:
            rows = self.db.fetch_all(
                "SELECT load_id, truck_ref, material_code, status, created_at FROM scrap_loads WHERE status = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (status, limit, offset),
            )
        else:
            rows = self.db.fetch_all(
                "SELECT load_id, truck_ref, material_code, status, created_at FROM scrap_loads ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
        return [{"load_id": r[0], "truck_ref": r[1], "material_code": r[2], "status": r[3], "created_at": r[4].isoformat() if r[4] else None} for r in rows]

    def set_load_status(self, load_id: str, status: str) -> None:
        self.db.execute("UPDATE scrap_loads SET status = %s, updated_at = now() WHERE load_id = %s", (status, load_id))

    # -- weigh tickets ----------------------------------------------------
    def create_weigh_ticket(
        self, load_id: str, gross: float, tare: float, net: float, unit: str, ticket_number: Optional[str],
        scale_ref: Optional[str], operator: Optional[str], *, allow_reweigh: bool = False,
        supersede_reason: Optional[str] = None, idempotency_key: Optional[str] = None,
        request_hash: Optional[str] = None,
    ) -> Tuple[int, bool, Optional[str], List[int]]:
        """Record a weigh ticket. Returns (ticket_id, created, stored_hash, superseded_ids).

        A load has at most one active ticket. A second weigh is refused with Conflict
        unless allow_reweigh is set, in which case the earlier active tickets are kept
        but marked superseded (with supersede_reason) and the new one becomes active.
        The load row is locked for the duration, so two concurrent weighs cannot both win.
        """
        with self.db.transaction() as cur:
            cur.execute("SELECT load_id FROM scrap_loads WHERE load_id = %s FOR UPDATE", (load_id,))
            if cur.fetchone() is None:
                raise NotFound("no such load")
            if idempotency_key:
                cur.execute("SELECT id, request_hash FROM scrap_weigh_tickets WHERE idempotency_key = %s", (idempotency_key,))
                replay = cur.fetchone()
                if replay is not None:
                    return replay[0], False, replay[1], []
            cur.execute(
                "SELECT id FROM scrap_weigh_tickets WHERE load_id = %s AND superseded_at IS NULL ORDER BY id",
                (load_id,),
            )
            active = [r[0] for r in cur.fetchall()]
            if active and not allow_reweigh:
                raise Conflict(
                    "load %s already has an active weigh ticket (#%d). To record a new weigh, "
                    "set allow_reweigh=true and give a supersede_reason." % (load_id, active[0])
                )
            if active:
                cur.execute(
                    "UPDATE scrap_weigh_tickets SET superseded_at = now(), supersede_reason = %s WHERE id = ANY(%s)",
                    (supersede_reason, active),
                )
            cur.execute(
                """INSERT INTO scrap_weigh_tickets
                   (load_id, gross, tare, net, unit, ticket_number, scale_ref, operator, idempotency_key, request_hash)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (idempotency_key) DO NOTHING
                   RETURNING id""",
                (load_id, gross, tare, net, unit, ticket_number, scale_ref, operator, idempotency_key, request_hash),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute("SELECT id, request_hash FROM scrap_weigh_tickets WHERE idempotency_key = %s", (idempotency_key,))
                replay = cur.fetchone()
                return replay[0], False, replay[1], []
            cur.execute("UPDATE scrap_loads SET status = 'weighed', updated_at = now() WHERE load_id = %s", (load_id,))
        return row[0], True, request_hash, active

    def get_weigh_ticket(self, ticket_id: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetch_one(
            "SELECT id, load_id, gross, tare, net, unit FROM scrap_weigh_tickets WHERE id = %s", (ticket_id,)
        )
        if not row:
            return None
        return {"ticket_id": row[0], "load_id": row[1], "gross": row[2], "tare": row[3], "net": row[4], "unit": row[5]}

    def list_weigh_tickets(self, load_id: str) -> List[Dict[str, Any]]:
        rows = self.db.fetch_all(
            """SELECT id, gross, tare, net, unit, ticket_number, scale_ref, operator, weighed_at,
                      superseded_at, supersede_reason
               FROM scrap_weigh_tickets WHERE load_id = %s ORDER BY weighed_at DESC, id DESC""",
            (load_id,),
        )
        return [
            {"id": r[0], "gross": r[1], "tare": r[2], "net": r[3], "unit": r[4], "ticket_number": r[5],
             "scale_ref": r[6], "operator": r[7], "weighed_at": r[8].isoformat() if r[8] else None,
             "active": r[9] is None, "superseded_at": r[9].isoformat() if r[9] else None,
             "supersede_reason": r[10]}
            for r in rows
        ]

    # -- stock movements --------------------------------------------------
    def create_movement(
        self, material_code: str, warehouse_code: str, movement_type: str, quantity: float,
        unit: str, reference: Optional[str], actor: Optional[str], reason: Optional[str],
        *, idempotency_key: Optional[str] = None, request_hash: Optional[str] = None,
    ) -> Tuple[int, bool, Optional[str], float]:
        """Post a stock movement. Returns (movement_id, created, stored_hash, balance_after).

        The balance check and the insert happen under a per-(material, warehouse)
        advisory lock, so concurrent movements cannot jointly drive stock negative.
        Movements are append-only: corrections are made with a further movement.
        """
        movement = Movement(material_id=0, warehouse_id=0, quantity=quantity, movement_type=movement_type)
        with self.db.transaction() as cur:
            self._require(cur, "SELECT 1 FROM scrap_materials WHERE code = %s", (material_code,),
                          "no such material")
            self._require(cur, "SELECT 1 FROM scrap_warehouses WHERE code = %s", (warehouse_code,),
                          "no such warehouse")
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("stock:%s:%s" % (material_code, warehouse_code),))
            if idempotency_key:
                cur.execute("SELECT id, request_hash FROM scrap_stock_movements WHERE idempotency_key = %s", (idempotency_key,))
                replay = cur.fetchone()
                if replay is not None:
                    balance_then = self._balance(cur, material_code, warehouse_code, up_to_id=replay[0])
                    return replay[0], False, replay[1], balance_then
            current = self._balance(cur, material_code, warehouse_code)
            if would_go_negative(current, movement):
                raise Conflict("movement would make stock negative")
            cur.execute(
                """INSERT INTO scrap_stock_movements
                   (material_code, warehouse_code, movement_type, quantity, unit, reference, actor, reason,
                    idempotency_key, request_hash)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (idempotency_key) DO NOTHING
                   RETURNING id""",
                (material_code, warehouse_code, movement_type, quantity, unit, reference, actor, reason,
                 idempotency_key, request_hash),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute("SELECT id, request_hash FROM scrap_stock_movements WHERE idempotency_key = %s", (idempotency_key,))
                replay = cur.fetchone()
                balance_then = self._balance(cur, material_code, warehouse_code, up_to_id=replay[0])
                return replay[0], False, replay[1], balance_then
        return row[0], True, request_hash, round(current + movement.signed_quantity(), 6)

    @staticmethod
    def _balance(cur, material_code: str, warehouse_code: str, up_to_id: Optional[int] = None) -> float:
        sql = """SELECT COALESCE(SUM(
                   CASE WHEN movement_type IN ('issue','transfer_out','reservation') THEN -ABS(quantity)
                        WHEN movement_type IN ('receipt','transfer_in','release') THEN ABS(quantity)
                        ELSE quantity END),0)
                 FROM scrap_stock_movements WHERE material_code = %s AND warehouse_code = %s"""
        params: List[Any] = [material_code, warehouse_code]
        if up_to_id is not None:
            sql += " AND id <= %s"
            params.append(up_to_id)
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        return float(row[0]) if row else 0.0

    def balance(self, material_code: str, warehouse_code: str) -> float:
        with self.db.transaction() as cur:
            return self._balance(cur, material_code, warehouse_code)

    def list_movements(self, material_code: Optional[str] = None, warehouse_code: Optional[str] = None,
                       limit: Optional[int] = 200, reference: Optional[str] = None) -> List[Dict[str, Any]]:
        # limit=None means no limit (used by trace); the API always passes an int.
        sql = "SELECT id, material_code, warehouse_code, movement_type, quantity, unit, reference, actor, reason, created_at FROM scrap_stock_movements"
        params: List[Any] = []
        clauses = []
        if material_code:
            clauses.append("material_code = %s")
            params.append(material_code)
        if warehouse_code:
            clauses.append("warehouse_code = %s")
            params.append(warehouse_code)
        if reference:
            clauses.append("reference = %s")
            params.append(reference)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, id DESC LIMIT %s"
        params.append(limit)
        rows = self.db.fetch_all(sql, tuple(params))
        return [
            {"id": r[0], "material_code": r[1], "warehouse_code": r[2], "movement_type": r[3],
             "quantity": r[4], "unit": r[5], "reference": r[6], "actor": r[7], "reason": r[8],
             "created_at": r[9].isoformat() if r[9] else None}
            for r in rows
        ]

    # -- customers --------------------------------------------------------
    def create_customer(self, code: str, name: str, email: Optional[str] = None, phone: Optional[str] = None) -> Dict[str, Any]:
        self.db.execute(
            "INSERT INTO scrap_customers (code, name, email, phone) VALUES (%s,%s,%s,%s)",
            (code, name, email, phone),
        )
        return {"code": code, "name": name, "email": email, "phone": phone}

    def list_customers(self) -> List[Dict[str, Any]]:
        rows = self.db.fetch_all("SELECT code, name, email, phone, created_at FROM scrap_customers ORDER BY code")
        return [{"code": r[0], "name": r[1], "email": r[2], "phone": r[3], "created_at": r[4].isoformat() if r[4] else None} for r in rows]

    # -- orders -----------------------------------------------------------
    def create_order(self, customer_code: Optional[str], load_id: Optional[str], created_by: Optional[str],
                     items: List[Dict[str, Any]], currency: str = "EUR", *,
                     idempotency_key: Optional[str] = None, request_hash: Optional[str] = None) -> Claim:
        order_number = "ORD-" + uuid.uuid4().hex[:10].upper()
        total = 0.0
        for it in items:
            total += float(it["quantity"]) * float(it["price_per_unit"])
        with self.db.transaction() as cur:
            if customer_code:
                self._require(cur, "SELECT 1 FROM scrap_customers WHERE code = %s", (customer_code,), "no such customer")
            if load_id:
                self._require(cur, "SELECT 1 FROM scrap_loads WHERE load_id = %s", (load_id,), "no such load")
            for it in items:
                self._require(cur, "SELECT 1 FROM scrap_materials WHERE code = %s", (it["material_code"],),
                              "no such material: %s" % it["material_code"])
            cur.execute(
                """INSERT INTO scrap_orders
                   (order_number, customer_code, load_id, status, total_amount, currency, created_by,
                    idempotency_key, request_hash)
                   VALUES (%s,%s,%s,'confirmed',%s,%s,%s,%s,%s)
                   ON CONFLICT (idempotency_key) DO NOTHING
                   RETURNING id""",
                (order_number, customer_code, load_id, total, currency, created_by, idempotency_key, request_hash),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute("SELECT order_number, request_hash FROM scrap_orders WHERE idempotency_key = %s", (idempotency_key,))
                existing = cur.fetchone()
                return existing[0], False, existing[1]
            order_id = row[0]
            for it in items:
                line_total = float(it["quantity"]) * float(it["price_per_unit"])
                cur.execute(
                    "INSERT INTO scrap_order_items (order_id, material_code, quantity, unit, price_per_unit, line_total) VALUES (%s,%s,%s,%s,%s,%s)",
                    (order_id, it["material_code"], it["quantity"], it.get("unit", "kg"), it["price_per_unit"], line_total),
                )
        return order_number, True, request_hash

    def get_order(self, order_number: str) -> Optional[Dict[str, Any]]:
        row = self.db.fetch_one(
            "SELECT id, order_number, customer_code, load_id, status, total_amount, currency, created_by, created_at, updated_at FROM scrap_orders WHERE order_number = %s",
            (order_number,),
        )
        if not row:
            return None
        items = self.db.fetch_all(
            "SELECT material_code, quantity, unit, price_per_unit, line_total FROM scrap_order_items WHERE order_id = %s",
            (row[0],),
        )
        deliveries = self.db.fetch_all(
            "SELECT id, status, delivered_at, delivered_by, notes FROM scrap_deliveries WHERE order_id = %s ORDER BY id",
            (row[0],),
        )
        return {
            "id": row[0], "order_number": row[1], "customer_code": row[2], "load_id": row[3],
            "status": row[4], "total_amount": row[5], "currency": row[6], "created_by": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
            "updated_at": row[9].isoformat() if row[9] else None,
            "items": [{"material_code": i[0], "quantity": i[1], "unit": i[2], "price_per_unit": i[3], "line_total": i[4]} for i in items],
            "deliveries": [{"id": d[0], "status": d[1], "delivered_at": d[2].isoformat() if d[2] else None, "delivered_by": d[3], "notes": d[4]} for d in deliveries],
        }

    def list_orders(self, status: Optional[str] = None, limit: Optional[int] = 100,
                    load_id: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT order_number, customer_code, load_id, status, total_amount, currency, created_at FROM scrap_orders"
        params: List[Any] = []
        clauses = []
        if status:
            clauses.append("status = %s")
            params.append(status)
        if load_id:
            clauses.append("load_id = %s")
            params.append(load_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, id DESC LIMIT %s"
        params.append(limit)
        rows = self.db.fetch_all(sql, tuple(params))
        return [{"order_number": r[0], "customer_code": r[1], "load_id": r[2], "status": r[3], "total_amount": r[4], "currency": r[5], "created_at": r[6].isoformat() if r[6] else None} for r in rows]

    def set_order_status(self, order_number: str, status: str) -> None:
        self.db.execute("UPDATE scrap_orders SET status = %s, updated_at = now() WHERE order_number = %s", (status, order_number))

    # -- deliveries -------------------------------------------------------
    def create_delivery(self, order_number: str, load_id: Optional[str] = None, notes: Optional[str] = None, *,
                        idempotency_key: Optional[str] = None, request_hash: Optional[str] = None) -> Claim:
        with self.db.transaction() as cur:
            cur.execute("SELECT id FROM scrap_orders WHERE order_number = %s", (order_number,))
            row = cur.fetchone()
            if row is None:
                raise NotFound("no such order")
            order_id = row[0]
            if load_id:
                self._require(cur, "SELECT 1 FROM scrap_loads WHERE load_id = %s", (load_id,), "no such load")
            cur.execute(
                """INSERT INTO scrap_deliveries (order_id, load_id, notes, idempotency_key, request_hash)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (idempotency_key) DO NOTHING
                   RETURNING id""",
                (order_id, load_id, notes, idempotency_key, request_hash),
            )
            inserted = cur.fetchone()
            if inserted is None:
                cur.execute("SELECT id, request_hash FROM scrap_deliveries WHERE idempotency_key = %s", (idempotency_key,))
                existing = cur.fetchone()
                return existing[0], False, existing[1]
        return inserted[0], True, request_hash

    def confirm_delivery(self, delivery_id: int, delivered_by: str, notes: Optional[str] = None) -> Dict[str, Any]:
        """Mark a pending delivery as delivered. Single-shot: a second confirm raises Conflict.

        The UPDATE only matches while status is still 'pending', so two concurrent
        confirms cannot both succeed and cannot overwrite the first confirmation.
        """
        with self.db.transaction() as cur:
            cur.execute(
                """UPDATE scrap_deliveries
                      SET status = 'delivered', delivered_at = now(), delivered_by = %s,
                          notes = COALESCE(%s, notes)
                    WHERE id = %s AND status = 'pending'
                RETURNING id, delivered_at, delivered_by""",
                (delivered_by, notes, delivery_id),
            )
            row = cur.fetchone()
            if row is not None:
                return {"delivery_id": row[0], "status": "delivered", "delivered_at": row[1].isoformat(), "delivered_by": row[2]}
            cur.execute("SELECT status, delivered_at, delivered_by FROM scrap_deliveries WHERE id = %s", (delivery_id,))
            existing = cur.fetchone()
        if existing is None:
            raise NotFound("no such delivery")
        raise Conflict(
            "delivery %d is already %s (delivered_by=%s, delivered_at=%s)"
            % (delivery_id, existing[0], existing[2], existing[1].isoformat() if existing[1] else None)
        )

    # -- traceability -----------------------------------------------------
    def trace_load(self, load_id: str) -> Dict[str, Any]:
        """Everything linked to a load, without the list limits used by the list endpoints."""
        load = self.get_load(load_id)
        tickets = self.list_weigh_tickets(load_id)
        movements = self.list_movements(reference=load_id, limit=None)
        linked_orders = self.list_orders(load_id=load_id, limit=None)
        return {"load": load, "weigh_tickets": tickets, "stock_movements": movements, "orders": linked_orders}

    # -- reports ----------------------------------------------------------
    def load_report_rows(self) -> List[Dict[str, Any]]:
        rows = self.db.fetch_all(
            "SELECT load_id, truck_ref, material_code, status, created_at FROM scrap_loads ORDER BY created_at DESC"
        )
        return [{"load_id": r[0], "truck_ref": r[1], "material_code": r[2], "status": r[3], "created_at": r[4].isoformat() if r[4] else None} for r in rows]

    def audit(self, actor: Optional[str], actor_role: Optional[str], action: str, subject_type: Optional[str],
              subject_id: Optional[str], detail: Optional[Dict[str, Any]], source_ip: Optional[str]) -> None:
        self.db.execute(
            "INSERT INTO scrap_audit_log (actor, actor_role, action, subject_type, subject_id, detail, source_ip) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (actor, actor_role, action, subject_type, subject_id, json.dumps(detail) if detail else None, source_ip),
        )
