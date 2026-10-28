"""FastAPI application for the scrap/inventory service."""

from __future__ import annotations

import datetime as _dt
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..config import Settings, load_settings
from ..db import Database, MigrationError
from ..domain.weights import WeightError, compute_net
from ..repository import ScrapRepository
from .security import Actor, Authenticator, make_dependencies, require_write

logger = logging.getLogger(__name__)


class MaterialRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    category: str = Field(..., min_length=1, max_length=64)
    unit: str = "kg"


class WarehouseRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    location: Optional[str] = None


class LoadRequest(BaseModel):
    truck_ref: Optional[str] = None
    driver_ref: Optional[str] = None
    customer_ref: Optional[str] = None
    supplier_ref: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    material_code: Optional[str] = None


class WeighRequest(BaseModel):
    load_id: str
    gross: float
    tare: float
    unit: str = "kg"
    ticket_number: Optional[str] = None
    scale_ref: Optional[str] = None


class MovementRequest(BaseModel):
    material_code: str
    warehouse_code: str
    movement_type: str
    quantity: float
    unit: str = "kg"
    reference: Optional[str] = None
    reason: Optional[str] = None


def create_app(settings: Optional[Settings] = None, db: Optional[Database] = None) -> FastAPI:
    resolved = settings or load_settings()
    problems = resolved.validate()
    if problems:
        raise RuntimeError("scrap service configuration is invalid:\n  - " + "\n  - ".join(problems))
    if resolved.allow_anonymous:
        logger.warning("SCRAP_ALLOW_ANONYMOUS is set; tests only.")

    database = db or Database(resolved.database_url)
    repository = ScrapRepository(database)
    authenticator = Authenticator(resolved.api_token, resolved.allow_anonymous)
    authenticate = make_dependencies(authenticator, resolved.allow_anonymous)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            applied = database.apply_migrations()
            if applied:
                logger.info("applied %d migration(s)", len(applied))
        except MigrationError as exc:
            logger.error("migrations failed: %s", exc)
            raise
        yield
        database.close()

    app = FastAPI(title="GPS_Tracer scrap service", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "X-Actor", "X-Actor-Role", "X-Service-Token"],
    )

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> str:
        try:
            database.fetch_one("SELECT 1")
            ok = True
        except Exception:
            ok = False
        if not ok:
            raise HTTPException(status_code=503, detail="database unavailable")
        return "ok"

    @app.get("/api/meta")
    async def meta(actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        return {"service_version": __version__, "scrap": True}

    @app.post("/api/materials", status_code=status.HTTP_201_CREATED)
    async def create_material(payload: MaterialRequest, actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        require_write(actor)
        try:
            row = repository.create_material(payload.code, payload.name, payload.category, payload.unit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        repository.audit(actor.name, actor.role, "material.create", "material", payload.code, {"name": payload.name}, actor.source_ip)
        return row

    @app.get("/api/materials")
    async def list_materials(actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        return {"count": len(repository.list_materials()), "materials": repository.list_materials()}

    @app.post("/api/warehouses", status_code=status.HTTP_201_CREATED)
    async def create_warehouse(payload: WarehouseRequest, actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        require_write(actor)
        try:
            row = repository.create_warehouse(payload.code, payload.name, payload.location)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        repository.audit(actor.name, actor.role, "warehouse.create", "warehouse", payload.code, None, actor.source_ip)
        return row

    @app.get("/api/warehouses")
    async def list_warehouses(actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        return {"count": len(repository.list_warehouses()), "warehouses": repository.list_warehouses()}

    @app.post("/api/loads", status_code=status.HTTP_201_CREATED)
    async def create_load(payload: LoadRequest, actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        require_write(actor)
        load_id = repository.create_load(
            truck_ref=payload.truck_ref, driver_ref=payload.driver_ref, customer_ref=payload.customer_ref,
            supplier_ref=payload.supplier_ref, origin=payload.origin, destination=payload.destination,
            material_code=payload.material_code, created_by=actor.name,
        )
        repository.audit(actor.name, actor.role, "load.create", "load", load_id, payload.model_dump(), actor.source_ip)
        from ..domain.qr import make_qr_png
        qr = make_qr_png(load_id)
        return {"load_id": load_id, "qr_available": qr is not None, "load": repository.get_load(load_id)}

    @app.get("/api/loads")
    async def list_loads(status: Optional[str] = None, limit: int = Query(default=100, ge=1, le=500),
                         offset: int = Query(default=0, ge=0), actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        rows = repository.list_loads(status=status, limit=limit, offset=offset)
        return {"count": len(rows), "loads": rows}

    @app.get("/api/loads/{load_id}")
    async def get_load(load_id: str, actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        load = repository.get_load(load_id)
        if not load:
            raise HTTPException(status_code=404, detail="no such load")
        repository.audit(actor.name, actor.role, "load.read", "load", load_id, None, actor.source_ip)
        return load

    @app.post("/api/loads/{load_id}/status")
    async def set_load_status(load_id: str, status_value: str = Query(..., alias="status"),
                              actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        require_write(actor)
        if not repository.get_load(load_id):
            raise HTTPException(status_code=404, detail="no such load")
        repository.set_load_status(load_id, status_value)
        repository.audit(actor.name, actor.role, "load.status", "load", load_id, {"status": status_value}, actor.source_ip)
        return repository.get_load(load_id)

    @app.post("/api/weigh", status_code=status.HTTP_201_CREATED)
    async def create_weigh(payload: WeighRequest, actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        require_write(actor)
        if not repository.get_load(payload.load_id):
            raise HTTPException(status_code=404, detail="no such load")
        try:
            net = compute_net(payload.gross, payload.tare, payload.unit)
        except WeightError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        ticket_id = repository.create_weigh_ticket(
            load_id=payload.load_id, gross=payload.gross, tare=payload.tare, net=net,
            unit=payload.unit, ticket_number=payload.ticket_number, scale_ref=payload.scale_ref,
            operator=actor.name,
        )
        repository.set_load_status(payload.load_id, "weighed")
        repository.audit(actor.name, actor.role, "weigh.create", "load", payload.load_id,
                        {"ticket_id": ticket_id, "gross": payload.gross, "tare": payload.tare, "net": net}, actor.source_ip)
        return {"ticket_id": ticket_id, "load_id": payload.load_id, "gross": payload.gross, "tare": payload.tare, "net": net, "unit": payload.unit}

    @app.get("/api/loads/{load_id}/weigh-tickets")
    async def list_weigh_tickets(load_id: str, actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        return {"count": len(repository.list_weigh_tickets(load_id)), "tickets": repository.list_weigh_tickets(load_id)}

    @app.post("/api/stock/movements", status_code=status.HTTP_201_CREATED)
    async def create_movement(payload: MovementRequest, actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        require_write(actor)
        from ..domain.stock import Movement, would_go_negative
        movement = Movement(
            material_id=0, warehouse_id=0, quantity=payload.quantity,
            movement_type=payload.movement_type, unit=payload.unit,
            reference=payload.reference, actor=actor.name, reason=payload.reason,
        )
        errors = movement.validate()
        if errors:
            raise HTTPException(status_code=400, detail="; ".join(errors))
        current = repository.balance(payload.material_code, payload.warehouse_code)
        if would_go_negative(current, movement):
            raise HTTPException(status_code=409, detail="movement would make stock negative")
        ticket_id = repository.create_movement(
            material_code=payload.material_code, warehouse_code=payload.warehouse_code,
            movement_type=payload.movement_type, quantity=payload.quantity, unit=payload.unit,
            reference=payload.reference, actor=actor.name, reason=payload.reason,
        )
        repository.audit(actor.name, actor.role, "stock.movement", "movement", str(ticket_id),
                        {"material": payload.material_code, "warehouse": payload.warehouse_code,
                         "type": payload.movement_type, "quantity": payload.quantity}, actor.source_ip)
        return {"movement_id": ticket_id, "new_balance": repository.balance(payload.material_code, payload.warehouse_code)}

    @app.get("/api/stock/balance")
    async def stock_balance(material_code: str, warehouse_code: str, actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        return {"material_code": material_code, "warehouse_code": warehouse_code,
                "balance": repository.balance(material_code, warehouse_code)}

    @app.get("/api/stock/movements")
    async def list_movements(material_code: Optional[str] = None, warehouse_code: Optional[str] = None,
                            limit: int = Query(default=200, ge=1, le=500), actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        rows = repository.list_movements(material_code=material_code, warehouse_code=warehouse_code, limit=limit)
        return {"count": len(rows), "movements": rows}

    @app.get("/api/audit")
    async def audit(limit: int = Query(default=100, ge=1, le=500), actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        rows = repository.db.fetch_all(
            "SELECT id, actor, actor_role, action, subject_type, subject_id, detail, source_ip, created_at FROM scrap_audit_log ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        return {"count": len(rows), "entries": [
            {"id": r[0], "actor": r[1], "actor_role": r[2], "action": r[3], "subject_type": r[4],
             "subject_id": r[5], "detail": r[6], "source_ip": r[7],
             "created_at": r[8].isoformat() if r[8] else None} for r in rows]}

    return app
