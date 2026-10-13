"""FastAPI application for the tachograph service.

The API is **internal**. It is published on loopback only and requires a service
token, because it serves driver personal data. There is deliberately **no endpoint
that returns an original uploaded file** — that is the specification's "do not
expose original files through public URLs" requirement, enforced by omission rather
than by an access check that could be got wrong.

Routes are grouped as read/write so the role gating is visible in one place.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import PARSER_VERSION, __version__
from ..config import Settings, load_settings
from ..db import Database, MigrationError
from ..importer import TachographImporter
from ..parsers import default_registry
from ..repository import ImportRepository
from ..rules import driving_time
from ..storage import ObjectStore
from .security import Authenticator, Actor, make_dependencies, require_driver_data

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CalculationRequest(BaseModel):
    driver_key: str = Field(..., min_length=1, max_length=200)
    period_start: _dt.date
    period_end: _dt.date
    data_age_days: Optional[int] = Field(
        default=None,
        ge=0,
        description="Age of the newest record, in days. Used for the staleness check.",
    )


def _serialise(value: Any) -> Any:
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialise(item) for item in value]
    return value


def create_app(
    settings: Optional[Settings] = None,
    db: Optional[Database] = None,
) -> FastAPI:
    resolved = settings or load_settings()
    problems = resolved.validate()
    if problems:
        # Fail at construction, not on the first request. A container that starts
        # and then 500s on every call is harder to diagnose than one that refuses.
        raise RuntimeError(
            "tachograph service configuration is invalid:\n  - "
            + "\n  - ".join(problems)
        )
    if resolved.allow_anonymous:
        logger.warning(
            "TACHO_ALLOW_ANONYMOUS is set: the API is serving driver data without a "
            "service token. This is for tests only and must never be set in production."
        )

    database = db or Database(resolved.database_url)
    store = ObjectStore(resolved.storage_dir)
    registry = default_registry(resolved.external_parser)
    importer = TachographImporter(database, store, registry, resolved)
    repository = ImportRepository(database)
    authenticator = Authenticator(resolved.api_token, resolved.allow_anonymous)
    authenticate = make_dependencies(authenticator, resolved.allow_anonymous)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            applied = database.apply_migrations()
            if applied:
                logger.info("applied %d migration(s): %s", len(applied), ", ".join(applied))
        except MigrationError as exc:
            # Refuse to serve on a schema mismatch. Reporting from the wrong schema
            # is worse than being down.
            logger.error("migrations failed: %s", exc)
            raise
        store.ensure_directories()
        yield
        database.close()

    app = FastAPI(
        title="GPS_Tracer tachograph service",
        version=__version__,
        description=(
            "Tachograph (.DDD) import and driving-time reporting. Internal API. "
            "Calculations are not legal findings: see docs/DRIVING-TIME.md."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Actor", "X-Actor-Role", "X-Service-Token"],
    )

    # -- health ----------------------------------------------------------
    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> str:
        """Unauthenticated liveness. Deliberately says nothing about the data."""
        try:
            database.fetch_one("SELECT 1")
            database_ok = True
        except Exception:  # noqa: BLE001
            database_ok = False
        if not database_ok:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable"
            )
        return "ok"

    @app.get("/api/meta")
    async def meta(actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        return {
            "service_version": __version__,
            "parser_version": PARSER_VERSION,
            "rules_version": driving_time.RULES_VERSION,
            "engine_version": driving_time.ENGINE_VERSION,
            "parser_adapters": [p.name for p in registry.parsers],
            "calculations_validated_against_reference": False,
            "validation_note": (
                "No driving-time calculation in this deployment has been validated "
                "against a trusted tachograph analysis report."
            ),
            "external_parser_configured": bool(resolved.external_parser),
        }

    # -- imports ---------------------------------------------------------
    @app.post("/api/imports", status_code=status.HTTP_202_ACCEPTED)
    async def create_import(
        file: UploadFile = File(...),
        declared_kind: str = Form("unknown"),
        actor: Actor = Depends(authenticate),
    ) -> Dict[str, Any]:
        """Accept a tachograph download and queue it for parsing.

        Validation here is intentionally shallow — size, emptiness, and the file's
        content hash. Whether the bytes are a usable tachograph file is the parser's
        job, in the worker, so a malformed upload cannot stall an HTTP request.
        """
        require_driver_data(actor)
        data = await file.read()
        try:
            outcome = importer.ingest(
                filename=file.filename or "unnamed.ddd",
                data=data,
                uploaded_by=actor.name,
                declared_kind=declared_kind,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

        return {
            "import_id": outcome.import_id,
            "status": outcome.status,
            "sha256": outcome.sha256,
            "size_bytes": outcome.size_bytes,
            "duplicate_of": outcome.duplicate_of,
            "reason": outcome.reason,
            "queued_for_parsing": outcome.accepted_for_processing,
        }

    @app.get("/api/imports")
    async def list_imports(
        status_filter: Optional[str] = Query(default=None, alias="status"),
        card_number: Optional[str] = None,
        date_from: Optional[_dt.date] = None,
        date_to: Optional[_dt.date] = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        actor: Actor = Depends(authenticate),
    ) -> Dict[str, Any]:
        require_driver_data(actor)
        rows = repository.list_imports(
            status=status_filter,
            card_number=card_number,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        return {"count": len(rows), "imports": _serialise(rows)}

    @app.get("/api/imports/{import_id}")
    async def get_import(
        import_id: int, actor: Actor = Depends(authenticate)
    ) -> Dict[str, Any]:
        require_driver_data(actor)
        record = repository.get_import(import_id)
        if record is None:
            raise HTTPException(status_code=404, detail="no such import")
        importer.audit(
            actor=actor.name,
            actor_role=actor.role,
            action="import.read",
            subject_type="import",
            subject_id=str(import_id),
            source_ip=actor.source_ip,
        )
        return _serialise(record)

    @app.get("/api/imports/{import_id}/timeline")
    async def import_timeline(
        import_id: int, actor: Actor = Depends(authenticate)
    ) -> Dict[str, Any]:
        require_driver_data(actor)
        if repository.get_import(import_id) is None:
            raise HTTPException(status_code=404, detail="no such import")
        return {"import_id": import_id, "changes": _serialise(repository.import_timeline(import_id))}

    # -- registry and activity -------------------------------------------
    @app.get("/api/drivers")
    async def list_drivers(actor: Actor = Depends(authenticate)) -> Dict[str, Any]:
        # Card numbers identify a person. Restricted and audited.
        require_driver_data(actor)
        rows = repository.list_driver_cards()
        importer.audit(
            actor=actor.name,
            actor_role=actor.role,
            action="driver_cards.list",
            subject_type="driver_card_registry",
            detail={"count": len(rows)},
            source_ip=actor.source_ip,
        )
        return {"count": len(rows), "driver_cards": _serialise(rows)}

    @app.get("/api/days")
    async def list_days(
        driver_key: Optional[str] = None,
        date_from: Optional[_dt.date] = None,
        date_to: Optional[_dt.date] = None,
        limit: int = Query(default=400, ge=1, le=2000),
        actor: Actor = Depends(authenticate),
    ) -> Dict[str, Any]:
        require_driver_data(actor)
        rows = repository.list_days(
            driver_key=driver_key, date_from=date_from, date_to=date_to, limit=limit
        )
        return {"count": len(rows), "days": _serialise(rows)}

    @app.get("/api/coverage")
    async def coverage(
        driver_key: str,
        date_from: _dt.date,
        date_to: _dt.date,
        actor: Actor = Depends(authenticate),
    ) -> Dict[str, Any]:
        require_driver_data(actor)
        return _serialise(repository.coverage(driver_key, date_from, date_to))

    @app.get("/api/summary/daily")
    async def daily_summary(
        driver_key: str,
        date_from: _dt.date,
        date_to: _dt.date,
        actor: Actor = Depends(authenticate),
    ) -> Dict[str, Any]:
        require_driver_data(actor)
        rows = repository.list_days(
            driver_key=driver_key, date_from=date_from, date_to=date_to, limit=2000
        )
        weekly: Dict[str, Dict[str, int]] = {}
        for row in rows:
            week = driving_time.week_start(row["day"]).isoformat()
            bucket = weekly.setdefault(
                week,
                {"driving": 0, "work": 0, "availability": 0, "rest": 0, "uncovered": 0},
            )
            bucket["driving"] += int(row["minutes_driving"] or 0)
            bucket["work"] += int(row["minutes_work"] or 0)
            bucket["availability"] += int(row["minutes_availability"] or 0)
            bucket["rest"] += int(row["minutes_rest"] or 0)
            bucket["uncovered"] += int(row["uncovered_minutes"] or 0)
        return {
            "driver_key": driver_key,
            "period_start": date_from.isoformat(),
            "period_end": date_to.isoformat(),
            "days": _serialise(rows),
            "by_week": weekly,
            "units": "minutes",
            "note": "Recorded minutes. Not a compliance finding.",
        }

    # -- reports ---------------------------------------------------------
    @app.get("/api/reports/activity.csv")
    async def activity_report(
        driver_key: str,
        date_from: _dt.date,
        date_to: _dt.date,
        actor: Actor = Depends(authenticate),
    ) -> StreamingResponse:
        """A CSV export that carries its own provenance.

        The metadata block at the top is part of the requirement that reports be
        exportable "with clear source and timestamp metadata". A spreadsheet that
        leaves the building without saying which rules version and which import IDs
        produced it cannot be checked later.
        """
        require_driver_data(actor)
        rows = repository.list_days(
            driver_key=driver_key, date_from=date_from, date_to=date_to, limit=2000
        )
        coverage_data = repository.coverage(driver_key, date_from, date_to)
        importer.audit(
            actor=actor.name,
            actor_role=actor.role,
            action="report.export",
            subject_type="driver",
            subject_id=driver_key,
            detail={"format": "csv", "days": len(rows)},
            source_ip=actor.source_ip,
        )

        def generate():
            buffer = io.StringIO()
            writer = csv.writer(buffer)

            writer.writerow(["# GPS_Tracer tachograph activity report"])
            writer.writerow(["# generated_at_utc", _dt.datetime.now(_dt.timezone.utc).isoformat()])
            writer.writerow(["# generated_by", actor.name])
            writer.writerow(["# driver_key", driver_key])
            writer.writerow(["# period_start", date_from.isoformat()])
            writer.writerow(["# period_end", date_to.isoformat()])
            writer.writerow(["# rules_version", driving_time.RULES_VERSION])
            writer.writerow(["# engine_version", driving_time.ENGINE_VERSION])
            writer.writerow(["# parser_version", PARSER_VERSION])
            writer.writerow(["# calculation_validated_against_reference", "false"])
            writer.writerow(["# validation_note", driving_time.CalculationResult.validation_note])
            writer.writerow(["# days_with_a_record", coverage_data["days_with_a_record"]])
            writer.writerow(["# days_missing", len(coverage_data["days_missing"])])
            writer.writerow(["# missing_days", ";".join(coverage_data["days_missing"][:60])])
            writer.writerow(["# units", "minutes"])
            writer.writerow([])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

            writer.writerow(
                [
                    "day",
                    "import_id",
                    "minutes_driving",
                    "minutes_work",
                    "minutes_availability",
                    "minutes_rest",
                    "uncovered_minutes",
                    "open_ended",
                    "distance_km",
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

            for row in rows:
                writer.writerow(
                    [
                        row["day"].isoformat(),
                        row["import_id"],
                        row["minutes_driving"],
                        row["minutes_work"],
                        row["minutes_availability"],
                        row["minutes_rest"],
                        row["uncovered_minutes"],
                        "true" if row["open_ended"] else "false",
                        row["distance_km"] if row["distance_km"] is not None else "",
                    ]
                )
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)

        filename = "tacho-activity-%s-%s.csv" % (
            date_from.isoformat(),
            date_to.isoformat(),
        )
        return StreamingResponse(
            generate(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="%s"' % filename,
                # Driver data: never cached by any intermediary.
                "Cache-Control": "no-store, private",
            },
        )

    # -- calculations ----------------------------------------------------
    @app.post("/api/calculations", status_code=status.HTTP_201_CREATED)
    async def create_calculation(
        payload: CalculationRequest, actor: Actor = Depends(authenticate)
    ) -> Dict[str, Any]:
        """Compute driving-time findings and store the run.

        The stored row records the rules version, the source days, the import IDs and
        every assumption, so the figure stays explainable after the rules change.
        """
        require_driver_data(actor)
        if payload.period_end < payload.period_start:
            raise HTTPException(status_code=400, detail="period_end is before period_start")

        days = repository.day_inputs(
            payload.driver_key, payload.period_start, payload.period_end
        )
        result = driving_time.calculate(
            driver_key=payload.driver_key,
            days=days,
            period_start=payload.period_start,
            period_end=payload.period_end,
            data_age_days=payload.data_age_days,
        )
        calculation_id = repository.save_calculation(result, actor.name, actor.role)
        importer.audit(
            actor=actor.name,
            actor_role=actor.role,
            action="calculation.run",
            subject_type="driver",
            subject_id=payload.driver_key,
            detail={
                "calculation_id": calculation_id,
                "rules_version": result.rules_version,
                "status": result.status,
                "breaches": sum(1 for f in result.findings if f.is_breach),
            },
            source_ip=actor.source_ip,
        )

        body = result.as_dict()
        body["calculation_id"] = calculation_id
        body["computed_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
        return body

    @app.get("/api/calculations")
    async def list_calculations(
        driver_key: Optional[str] = None,
        limit: int = Query(default=50, ge=1, le=500),
        actor: Actor = Depends(authenticate),
    ) -> Dict[str, Any]:
        require_driver_data(actor)
        rows = repository.list_calculations(driver_key=driver_key, limit=limit)
        return {"count": len(rows), "calculations": _serialise(rows)}

    @app.get("/api/calculations/{calculation_id}")
    async def get_calculation(
        calculation_id: int, actor: Actor = Depends(authenticate)
    ) -> Dict[str, Any]:
        require_driver_data(actor)
        record = repository.get_calculation(calculation_id)
        if record is None:
            raise HTTPException(status_code=404, detail="no such calculation")
        return _serialise(record)

    # -- audit -----------------------------------------------------------
    @app.get("/api/audit")
    async def audit_trail(
        subject_type: Optional[str] = None,
        limit: int = Query(default=100, ge=1, le=500),
        actor: Actor = Depends(authenticate),
    ) -> Dict[str, Any]:
        # Reading the audit log is itself a privileged action, and it is recorded.
        if actor.role != "owner":
            raise HTTPException(status_code=403, detail="only 'owner' may read the audit log")
        rows = repository.audit_trail(subject_type=subject_type, limit=limit)
        return {"count": len(rows), "entries": _serialise(rows)}

    return app
