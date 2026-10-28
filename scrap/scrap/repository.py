"""Repository helpers for the scrap service."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from .db import Database


class ScrapRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

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
    ) -> str:
        load_id = "LOAD-" + uuid.uuid4().hex[:10].upper()
        self.db.execute(
            """INSERT INTO scrap_loads
               (load_id, truck_ref, driver_ref, customer_ref, supplier_ref, origin, destination, material_code, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (load_id, truck_ref, driver_ref, customer_ref, supplier_ref, origin, destination, material_code, created_by),
        )
        return load_id

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
        scale_ref: Optional[str], operator: Optional[str],
    ) -> int:
        row = self.db.fetch_one(
            """INSERT INTO scrap_weigh_tickets (load_id, gross, tare, net, unit, ticket_number, scale_ref, operator)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (load_id, gross, tare, net, unit, ticket_number, scale_ref, operator),
        )
        return row[0]

    def list_weigh_tickets(self, load_id: str) -> List[Dict[str, Any]]:
        rows = self.db.fetch_all(
            "SELECT id, gross, tare, net, unit, ticket_number, scale_ref, operator, weighed_at FROM scrap_weigh_tickets WHERE load_id = %s ORDER BY weighed_at DESC",
            (load_id,),
        )
        return [
            {"id": r[0], "gross": r[1], "tare": r[2], "net": r[3], "unit": r[4], "ticket_number": r[5],
             "scale_ref": r[6], "operator": r[7], "weighed_at": r[8].isoformat() if r[8] else None}
            for r in rows
        ]

    # -- stock movements --------------------------------------------------
    def create_movement(
        self, material_code: str, warehouse_code: str, movement_type: str, quantity: float,
        unit: str, reference: Optional[str], actor: Optional[str], reason: Optional[str],
    ) -> int:
        row = self.db.fetch_one(
            """INSERT INTO scrap_stock_movements (material_code, warehouse_code, movement_type, quantity, unit, reference, actor, reason)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (material_code, warehouse_code, movement_type, quantity, unit, reference, actor, reason),
        )
        return row[0]

    def balance(self, material_code: str, warehouse_code: str) -> float:
        row = self.db.fetch_one(
            """SELECT COALESCE(SUM(
                 CASE WHEN movement_type IN ('issue','transfer_out','reservation') THEN -ABS(quantity)
                      WHEN movement_type IN ('receipt','transfer_in','release') THEN ABS(quantity)
                      ELSE quantity END),0)
               FROM scrap_stock_movements WHERE material_code = %s AND warehouse_code = %s""",
            (material_code, warehouse_code),
        )
        return float(row[0]) if row else 0.0

    def list_movements(self, material_code: Optional[str] = None, warehouse_code: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        sql = "SELECT id, material_code, warehouse_code, movement_type, quantity, unit, reference, actor, reason, created_at FROM scrap_stock_movements"
        params: List[Any] = []
        clauses = []
        if material_code:
            clauses.append("material_code = %s")
            params.append(material_code)
        if warehouse_code:
            clauses.append("warehouse_code = %s")
            params.append(warehouse_code)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT %s"
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
                     items: List[Dict[str, Any]], currency: str = "EUR") -> str:
        import uuid
        order_number = "ORD-" + uuid.uuid4().hex[:10].upper()
        total = 0.0
        for it in items:
            total += float(it["quantity"]) * float(it["price_per_unit"])
        self.db.execute(
            "INSERT INTO scrap_orders (order_number, customer_code, load_id, total_amount, currency, created_by) VALUES (%s,%s,%s,%s,%s,%s)",
            (order_number, customer_code, load_id, total, currency, created_by),
        )
        row = self.db.fetch_one("SELECT id FROM scrap_orders WHERE order_number = %s", (order_number,))
        order_id = row[0]
        for it in items:
            line_total = float(it["quantity"]) * float(it["price_per_unit"])
            self.db.execute(
                "INSERT INTO scrap_order_items (order_id, material_code, quantity, unit, price_per_unit, line_total) VALUES (%s,%s,%s,%s,%s,%s)",
                (order_id, it["material_code"], it["quantity"], it.get("unit", "kg"), it["price_per_unit"], line_total),
            )
        return order_number

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
            "SELECT id, status, delivered_at, delivered_by, notes FROM scrap_deliveries WHERE order_id = %s",
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

    def list_orders(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if status:
            rows = self.db.fetch_all(
                "SELECT order_number, customer_code, load_id, status, total_amount, currency, created_at FROM scrap_orders WHERE status = %s ORDER BY created_at DESC LIMIT %s",
                (status, limit),
            )
        else:
            rows = self.db.fetch_all(
                "SELECT order_number, customer_code, load_id, status, total_amount, currency, created_at FROM scrap_orders ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
        return [{"order_number": r[0], "customer_code": r[1], "load_id": r[2], "status": r[3], "total_amount": r[4], "currency": r[5], "created_at": r[6].isoformat() if r[6] else None} for r in rows]

    def set_order_status(self, order_number: str, status: str) -> None:
        self.db.execute("UPDATE scrap_orders SET status = %s, updated_at = now() WHERE order_number = %s", (status, order_number))

    # -- deliveries -------------------------------------------------------
    def create_delivery(self, order_number: str, load_id: Optional[str] = None, notes: Optional[str] = None) -> int:
        row = self.db.fetch_one("SELECT id FROM scrap_orders WHERE order_number = %s", (order_number,))
        if not row:
            raise ValueError("no such order")
        order_id = row[0]
        r = self.db.fetch_one(
            "INSERT INTO scrap_deliveries (order_id, load_id, notes) VALUES (%s,%s,%s) RETURNING id",
            (order_id, load_id, notes),
        )
        return r[0]

    def confirm_delivery(self, delivery_id: int, delivered_by: str, notes: Optional[str] = None) -> None:
        self.db.execute(
            "UPDATE scrap_deliveries SET status = 'delivered', delivered_at = now(), delivered_by = %s, notes = COALESCE(%s, notes) WHERE id = %s",
            (delivered_by, notes, delivery_id),
        )

    # -- traceability -----------------------------------------------------
    def trace_load(self, load_id: str) -> Dict[str, Any]:
        load = self.get_load(load_id)
        tickets = self.list_weigh_tickets(load_id)
        movements = self.list_movements(reference=load_id) if False else self.list_movements()
        movements = [m for m in movements if m.get("reference") == load_id]
        orders = self.list_orders()
        linked_orders = [o for o in orders if o.get("load_id") == load_id]
        return {"load": load, "weigh_tickets": tickets, "stock_movements": movements, "orders": linked_orders}

    # -- reports ----------------------------------------------------------
    def load_report_rows(self) -> List[Dict[str, Any]]:
        rows = self.db.fetch_all(
            "SELECT load_id, truck_ref, material_code, status, created_at FROM scrap_loads ORDER BY created_at DESC"
        )
        return [{"load_id": r[0], "truck_ref": r[1], "material_code": r[2], "status": r[3], "created_at": r[4].isoformat() if r[4] else None} for r in rows]

    def audit(self, actor: Optional[str], actor_role: Optional[str], action: str, subject_type: Optional[str],
              subject_id: Optional[str], detail: Optional[Dict[str, Any]], source_ip: Optional[str]) -> None:
        import json
        self.db.execute(
            "INSERT INTO scrap_audit_log (actor, actor_role, action, subject_type, subject_id, detail, source_ip) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (actor, actor_role, action, subject_type, subject_id, json.dumps(detail) if detail else None, source_ip),
        )
