"""End-to-end service tests against a real PostgreSQL.

Skipped unless ``TACHO_TEST_DATABASE_URL`` is set, so the pure-logic suite still
runs anywhere. These are the tests that actually establish the service works:
schema applied, files ingested and parsed, duplicates detected, malformed input
contained, activity normalised, coverage reported, calculations stored, and the API
answering with the right status codes for the right roles.

Run them against a throwaway PostgreSQL, never the production one::

    docker run -d --rm --name tacho-test-db -p 127.0.0.1:55432:5432 \\
        -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test -e POSTGRES_DB=test \\
        postgres:16-alpine

    TACHO_TEST_DATABASE_URL=postgresql://test:test@127.0.0.1:55432/test \\
        python -m pytest tests/test_service_db.py -v
"""

from __future__ import annotations

import datetime as _dt
import os
import pathlib

import pytest

from tacho.config import Settings
from tacho.db import Database, MigrationError
from tacho.fixtures.gen1_writer import (
    make_garbage,
    make_sample_card_download,
    make_vu_download,
)
from tacho.importer import (
    STATUS_DONE,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_REJECTED,
    TachographImporter,
)
from tacho.parsers import default_registry
from tacho.repository import ImportRepository
from tacho.rules import driving_time
from tacho.storage import ObjectStore

DATABASE_URL = os.environ.get("TACHO_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TACHO_TEST_DATABASE_URL is not set; skipping database-backed tests",
)

WEEK_DAY = _dt.date(2026, 9, 14)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema() -> Database:
    """One migrated database for the whole module.

    Setting ``TACHO_TEST_DATABASE_URL`` is a promise that a database is there, so a
    database that cannot be reached -- or will not migrate -- is a broken
    environment and must FAIL the run.

    An earlier version called ``pytest.skip()`` here. That was a real defect: with
    the variable set and the server down, the entire module skipped and pytest
    exited 0, so a green run proved nothing about the code under test. Skipping is
    only correct when the variable is unset, which ``pytestmark`` above already
    handles.
    """
    database = Database(DATABASE_URL)
    try:
        database.apply_migrations()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            "TACHO_TEST_DATABASE_URL is set but the test database is unusable: "
            "%s: %s\nIf no database is intended, unset TACHO_TEST_DATABASE_URL "
            "so these tests skip honestly instead of failing."
            % (type(exc).__name__, exc),
            pytrace=False,
        )
    yield database
    database.close()


@pytest.fixture()
def clean_db(schema: Database) -> Database:
    """Truncate the domain tables between tests; keep the schema and ledger."""
    schema.execute(
        "TRUNCATE tacho_activity_changes, tacho_activity_days, tacho_imports, "
        "tacho_driver_cards, tacho_card_assignments, tacho_vehicle_assignments, "
        "tacho_calculations, tacho_audit_log, tacho_drivers RESTART IDENTITY CASCADE"
    )
    return schema


@pytest.fixture()
def settings(tmp_path: pathlib.Path) -> Settings:
    return Settings(
        database_url=DATABASE_URL,
        storage_dir=str(tmp_path / "objects"),
        api_token="",
        allow_anonymous=True,
    )


@pytest.fixture()
def importer(clean_db: Database, settings: Settings) -> TachographImporter:
    store = ObjectStore(settings.storage_dir)
    store.ensure_directories()
    return TachographImporter(clean_db, store, default_registry(), settings)


def process_all(imp: TachographImporter, limit: int = 10) -> int:
    processed = 0
    while processed < limit:
        claimed = imp.claim_next()
        if claimed is None:
            break
        imp.process(claimed)
        processed += 1
    return processed


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


class TestMigrations:
    def test_expected_tables_exist(self, schema: Database):
        tables = set(schema.table_names())
        assert {
            "tacho_imports",
            "tacho_activity_days",
            "tacho_activity_changes",
            "tacho_driver_cards",
            "tacho_drivers",
            "tacho_card_assignments",
            "tacho_vehicle_assignments",
            "tacho_calculations",
            "tacho_audit_log",
            "tacho_schema_migrations",
        } <= tables

    def test_applying_twice_is_a_no_op(self, schema: Database):
        assert schema.apply_migrations() == []

    def test_editing_an_applied_migration_is_refused(self, tmp_path: pathlib.Path):
        """Migrations are immutable. A changed checksum must stop the service.

        Uses version numbers in the 9000s so this never collides with the real
        migrations already applied to the same database by the module fixture.
        """
        directory = tmp_path / "migrations"
        directory.mkdir()
        original = "CREATE TABLE IF NOT EXISTS demo_one (id INT);"
        first = directory / "9001_one.sql"
        first.write_text(original)

        database = Database(DATABASE_URL)
        # Defensive: a previous run that failed part-way through could have left a
        # ledger row behind, which would make this test's own first apply fail for
        # the wrong reason.
        database.execute("DROP TABLE IF EXISTS demo_one")
        database.execute("DROP TABLE IF EXISTS demo_two")
        database.execute("DELETE FROM tacho_schema_migrations WHERE version IN (9001, 9002)")
        try:
            assert database.apply_migrations(str(directory)) == ["9001_one.sql"]

            # Change the already-applied file: the runner must refuse to start.
            first.write_text("CREATE TABLE IF NOT EXISTS demo_one (id BIGINT);")
            with pytest.raises(MigrationError) as excinfo:
                database.apply_migrations(str(directory))
            assert "has changed since it was applied" in str(excinfo.value)

            # Put it back: the point is proven, and leaving the edited file in place
            # would make every later apply fail for the same reason.
            first.write_text(original)
            assert database.apply_migrations(str(directory)) == []

            # Adding a *new* file is the supported way forward.
            (directory / "9002_two.sql").write_text(
                "CREATE TABLE IF NOT EXISTS demo_two (id INT);"
            )
            assert database.apply_migrations(str(directory)) == ["9002_two.sql"]
        finally:
            database.execute("DROP TABLE IF EXISTS demo_one")
            database.execute("DROP TABLE IF EXISTS demo_two")
            database.execute(
                "DELETE FROM tacho_schema_migrations WHERE version IN (9001, 9002)"
            )
            database.close()


# ---------------------------------------------------------------------------
# Ingest, parse, persist
# ---------------------------------------------------------------------------


class TestIngestAndProcess:
    def test_a_card_download_round_trips_into_the_database(self, importer, clean_db):
        data = make_sample_card_download(number_of_days=5)
        outcome = importer.ingest("driver.ddd", data, uploaded_by="tester")
        assert outcome.status == STATUS_PENDING
        assert outcome.size_bytes == len(data)
        assert process_all(importer) == 1

        repository = ImportRepository(clean_db)
        record = repository.get_import(outcome.import_id)
        assert record is not None
        assert record["status"] == STATUS_DONE
        assert record["source_kind"] == "driver_card"
        assert record["generation"] == "gen1"
        assert record["card_number"] == "IT000000000000" + "00"
        assert record["holder_surname"] == "Rossi"
        assert record["holder_first_names"] == "Mario"
        assert record["day_count"] == 5
        assert record["parser_name"] == "clean-room-gen1"

        days = repository.list_days()
        assert len(days) == 5
        # Sample pattern: 8 hours of driving per day.
        assert all(row["minutes_driving"] == 480 for row in days)
        assert all(row["minutes_work"] == 195 for row in days)
        assert all(row["minutes_rest"] == 765 for row in days)

    def test_activity_changes_are_stored_and_readable(self, importer, clean_db):
        outcome = importer.ingest(
            "driver.ddd", make_sample_card_download(number_of_days=1), "tester"
        )
        process_all(importer)
        timeline = ImportRepository(clean_db).import_timeline(outcome.import_id)
        assert len(timeline) == 9
        assert [row["minute_of_day"] for row in timeline] == sorted(
            row["minute_of_day"] for row in timeline
        )
        assert timeline[1]["activity"] == 2  # 06:00 other work
        assert timeline[1]["activity_label"] == "Other work"

    def test_the_original_file_is_stored_and_never_a_url(self, importer, clean_db, settings):
        data = make_sample_card_download(number_of_days=1)
        outcome = importer.ingest("driver.ddd", data, "tester")
        store = ObjectStore(settings.storage_dir)
        assert store.exists(outcome.sha256)
        assert store.read(outcome.sha256) == data
        # Integrity re-check must pass.
        assert store.verify(outcome.sha256) is True

        # The stored path must not be reachable as a URL, and the API record must
        # not leak it.
        record = ImportRepository(clean_db).get_import(outcome.import_id)
        assert "stored_path" not in record

    def test_an_empty_file_is_rejected_before_anything_is_stored(self, importer):
        with pytest.raises(ValueError):
            importer.ingest("empty.ddd", b"", "tester")

    def test_an_oversized_file_is_rejected(self, importer, settings):
        settings.max_upload_bytes = 128
        with pytest.raises(ValueError) as excinfo:
            importer.ingest("big.ddd", bytes(4096), "tester")
        assert "over the 128-byte limit" in str(excinfo.value)


class TestDuplicateDetection:
    def test_the_same_bytes_twice_is_recorded_as_a_duplicate(self, importer, clean_db):
        data = make_sample_card_download(number_of_days=2)

        first = importer.ingest("first.ddd", data, "tester")
        process_all(importer)
        assert first.status == STATUS_PENDING

        second = importer.ingest("second.ddd", data, "tester")
        assert second.status == STATUS_DUPLICATE
        assert second.duplicate_of == first.import_id
        assert "already imported" in (second.reason or "")
        assert second.accepted_for_processing is False

        # Both uploads are in the history: duplicates are recorded, not hidden.
        repository = ImportRepository(clean_db)
        records = repository.list_imports()
        assert len(records) == 2
        assert {record["status"] for record in records} == {STATUS_DONE, STATUS_DUPLICATE}

        # And the duplicate contributed no activity rows of its own.
        days = repository.list_days()
        assert len(days) == 2
        assert all(row["import_id"] == first.import_id for row in days)

    def test_a_file_that_failed_can_be_uploaded_again(self, importer):
        """A transient failure must not permanently poison those exact bytes."""
        data = make_garbage()
        first = importer.ingest("garbage.ddd", data, "tester")
        process_all(importer)
        assert first.status == STATUS_PENDING

        second = importer.ingest("garbage-again.ddd", data, "tester")
        assert second.status == STATUS_PENDING
        assert second.duplicate_of is None


class TestMalformedInputIsContained:
    def test_garbage_fails_with_a_useful_code_and_the_worker_survives(
        self, importer, clean_db
    ):
        outcome = importer.ingest("invoice.pdf", make_garbage(), "tester")
        process_all(importer)

        record = ImportRepository(clean_db).get_import(outcome.import_id)
        assert record["status"] in (STATUS_FAILED, STATUS_REJECTED)
        assert record["error_code"]
        assert record["error_message"]

    def test_attempts_are_counted_and_the_row_is_eventually_rejected(
        self, importer, clean_db, settings
    ):
        settings.worker_max_attempts = 2
        outcome = importer.ingest("invoice.pdf", make_garbage(), "tester")

        # Two attempts: the second exhausts the budget.
        for _ in range(2):
            importer.db.execute(
                "UPDATE tacho_imports SET status='pending', claimed_at=NULL WHERE id=%s",
                (outcome.import_id,),
            )
            process_all(importer)

        record = ImportRepository(clean_db).get_import(outcome.import_id)
        assert record["status"] == STATUS_REJECTED
        assert record["attempts"] == 2

    def test_a_truncated_download_is_contained_without_writing_partial_activity(
        self, importer, clean_db
    ):
        from tacho.fixtures.gen1_writer import make_truncated_card_download

        outcome = importer.ingest("cut.ddd", make_truncated_card_download(), "tester")
        process_all(importer)

        repository = ImportRepository(clean_db)
        record = repository.get_import(outcome.import_id)
        assert record["status"] in (STATUS_FAILED, STATUS_REJECTED)
        # Nothing partial was written: a half-day of activity is worse than a
        # failed import because it looks like data.
        assert repository.list_days() == []

    def test_a_vehicle_unit_download_is_stored_but_reports_no_activity(
        self, importer, clean_db
    ):
        outcome = importer.ingest("vu.ddd", make_vu_download([1, 2, 3]), "tester")
        process_all(importer)

        repository = ImportRepository(clean_db)
        record = repository.get_import(outcome.import_id)
        assert record["status"] == STATUS_DONE
        assert record["source_kind"] == "vehicle_unit"
        assert record["day_count"] == 0
        # The limitation is surfaced rather than presented as "no driving".
        joined = " ".join(record["warnings"])
        assert "no_activity_records" in joined


class TestStaleLeaseRecovery:
    def test_a_row_stuck_in_processing_is_reclaimed(self, importer, clean_db, settings):
        """A worker killed mid-parse must not strand a file forever."""
        outcome = importer.ingest(
            "driver.ddd", make_sample_card_download(number_of_days=2), "tester"
        )
        # Simulate a worker that claimed the row and then died.
        clean_db.execute(
            "UPDATE tacho_imports SET status='processing', "
            "claimed_at = now() - make_interval(mins => %s) WHERE id = %s",
            (settings.worker_lease_minutes + 1, outcome.import_id),
        )
        claimed = importer.claim_next()
        assert claimed is not None
        assert claimed["id"] == outcome.import_id

    def test_a_freshly_claimed_row_is_not_stolen(self, importer, clean_db, settings):
        outcome = importer.ingest(
            "driver.ddd", make_sample_card_download(number_of_days=2), "tester"
        )
        clean_db.execute(
            "UPDATE tacho_imports SET status='processing', claimed_at = now() WHERE id = %s",
            (outcome.import_id,),
        )
        assert importer.claim_next() is None


# ---------------------------------------------------------------------------
# Coverage and calculations
# ---------------------------------------------------------------------------


class TestCoverage:
    def test_missing_and_incomplete_days_are_reported(self, importer, clean_db):
        # Two days of data, then ask about a five-day span.
        data = make_sample_card_download(first_day=WEEK_DAY, number_of_days=2)
        importer.ingest("driver.ddd", data, "tester")
        process_all(importer)

        repository = ImportRepository(clean_db)
        driver_key = repository.list_days()[0]["driver_key"]

        report = repository.coverage(
            driver_key, WEEK_DAY, WEEK_DAY + _dt.timedelta(days=4)
        )
        assert report["total_days"] == 5
        assert report["days_with_a_record"] == 2
        assert len(report["days_missing"]) == 3
        assert report["coverage_ratio"] == 0.4
        # The crucial flag: rest findings cannot be trusted on partial coverage.
        assert report["rest_findings_reliable"] is False
        assert any("no imported record" in warning for warning in report["warnings"])

    def test_full_and_complete_coverage_is_marked_reliable(self, importer, clean_db):
        data = make_sample_card_download(first_day=WEEK_DAY, number_of_days=3)
        importer.ingest("driver.ddd", data, "tester")
        process_all(importer)

        repository = ImportRepository(clean_db)
        driver_key = repository.list_days()[0]["driver_key"]
        report = repository.coverage(
            driver_key, WEEK_DAY, WEEK_DAY + _dt.timedelta(days=2)
        )
        assert report["days_missing"] == []
        assert report["days_incomplete"] == []
        assert report["rest_findings_reliable"] is True


class TestCalculations:
    def test_a_calculation_is_stored_with_its_rules_version_and_provenance(
        self, importer, clean_db
    ):
        data = make_sample_card_download(first_day=WEEK_DAY, number_of_days=5)
        importer.ingest("driver.ddd", data, "tester")
        process_all(importer)

        repository = ImportRepository(clean_db)
        driver_key = repository.list_days()[0]["driver_key"]
        days = repository.day_inputs(driver_key, WEEK_DAY, WEEK_DAY + _dt.timedelta(days=4))
        assert len(days) == 5

        result = driving_time.calculate(
            driver_key=driver_key,
            days=days,
            period_start=WEEK_DAY,
            period_end=WEEK_DAY + _dt.timedelta(days=4),
        )
        calculation_id = repository.save_calculation(result, "tester", "owner")

        stored = repository.get_calculation(calculation_id)
        assert stored["rules_version"] == driving_time.RULES_VERSION
        assert stored["engine_version"] == driving_time.ENGINE_VERSION
        # The safety rail, verified against the database rather than the object.
        assert stored["validated_against_reference"] is False
        assert stored["source_days"] is not None and len(stored["source_days"]) == 5
        assert stored["source_import_ids"]
        assert stored["assumptions"]

        # Each sample day is 8 hours of continuous driving, so Art 7 is breached
        # five times.
        payload = stored["result"]
        breaches = [f for f in payload["findings"] if f["severity"] == "breach"]
        assert len(breaches) == 5
        assert all(f["article"].startswith("Regulation (EC) 561/2006") for f in breaches)

    def test_rules_version_is_part_of_the_stored_row(self, clean_db):
        columns = clean_db.fetch_all(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'tacho_calculations'"
        )
        names = {row[0] for row in columns}
        assert {
            "rules_version",
            "engine_version",
            "assumptions",
            "source_days",
            "missing_days",
            "validated_against_reference",
        } <= names


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------


@pytest.fixture()
def anonymous_client(clean_db: Database, tmp_path: pathlib.Path):
    from fastapi.testclient import TestClient

    from tacho.api.app import create_app

    app = create_app(
        Settings(
            database_url=DATABASE_URL,
            storage_dir=str(tmp_path / "objects"),
            api_token="",
            allow_anonymous=True,
        )
    )
    # A role header is required even when anonymous: an unlabelled caller resolves
    # to the least-privileged role and is correctly refused driver data.
    with TestClient(
        app, headers={"X-Actor": "test-owner", "X-Actor-Role": "owner"}
    ) as client:
        yield client


@pytest.fixture()
def viewer_client(clean_db: Database, tmp_path: pathlib.Path):
    from fastapi.testclient import TestClient

    from tacho.api.app import create_app

    app = create_app(
        Settings(
            database_url=DATABASE_URL,
            storage_dir=str(tmp_path / "objects"),
            api_token="",
            allow_anonymous=True,
        )
    )
    with TestClient(
        app, headers={"X-Actor": "test-viewer", "X-Actor-Role": "viewer"}
    ) as client:
        yield client


@pytest.fixture()
def token_client(clean_db: Database, tmp_path: pathlib.Path):
    from fastapi.testclient import TestClient

    from tacho.api.app import create_app

    app = create_app(
        Settings(
            database_url=DATABASE_URL,
            storage_dir=str(tmp_path / "objects"),
            api_token="a-very-long-test-token-value-1234567890",
            allow_anonymous=False,
        )
    )
    with TestClient(app) as client:
        yield client


class TestApiAuth:
    def test_health_is_open_and_reports_liveness(self, anonymous_client):
        response = anonymous_client.get("/healthz")
        assert response.status_code == 200
        assert response.text.strip() == "ok"

    def test_a_missing_token_is_refused(self, token_client):
        response = token_client.get("/api/imports", headers={"X-Actor": "someone"})
        assert response.status_code == 401
        assert "service token" in response.json()["detail"]

    def test_a_wrong_token_is_refused(self, token_client):
        response = token_client.get(
            "/api/imports",
            headers={"Authorization": "Bearer wrong-token", "X-Actor": "someone"},
        )
        assert response.status_code == 401

    def test_a_valid_token_without_an_actor_is_refused(self, token_client):
        response = token_client.get(
            "/api/imports",
            headers={"X-Service-Token": "a-very-long-test-token-value-1234567890"},
        )
        assert response.status_code == 401
        assert "X-Actor" in response.json()["detail"]

    def test_a_valid_token_and_actor_is_accepted(self, token_client):
        response = token_client.get(
            "/api/imports",
            headers={
                "X-Service-Token": "a-very-long-test-token-value-1234567890",
                "X-Actor": "dispatcher",
                "X-Actor-Role": "fleet_manager",
            },
        )
        assert response.status_code == 200

    def test_a_viewer_may_not_read_driver_data(self, token_client):
        response = token_client.get(
            "/api/drivers",
            headers={
                "X-Service-Token": "a-very-long-test-token-value-1234567890",
                "X-Actor": "auditor",
                "X-Actor-Role": "viewer",
            },
        )
        assert response.status_code == 403
        assert "may not read driver personal data" in response.json()["detail"]

    def test_an_unknown_role_falls_back_to_the_least_privileged(self, token_client):
        """A missing or bogus role must never become a privileged one."""
        response = token_client.get(
            "/api/drivers",
            headers={
                "X-Service-Token": "a-very-long-test-token-value-1234567890",
                "X-Actor": "someone",
                "X-Actor-Role": "superadmin",
            },
        )
        assert response.status_code == 403


class TestApiWorkflow:
    def test_meta_reports_the_versions_and_the_unvalidated_caveat(self, anonymous_client):
        payload = anonymous_client.get("/api/meta").json()
        assert payload["rules_version"] == driving_time.RULES_VERSION
        assert payload["calculations_validated_against_reference"] is False
        assert "clean-room-gen1" in payload["parser_adapters"]
        assert payload["validation_note"]

    def test_upload_then_process_then_report(self, anonymous_client, clean_db, settings):
        data = make_sample_card_download(first_day=WEEK_DAY, number_of_days=3)

        upload = anonymous_client.post(
            "/api/imports",
            files={"file": ("driver.ddd", data, "application/octet-stream")},
            data={"declared_kind": "driver_card"},
        )
        assert upload.status_code == 202
        body = upload.json()
        assert body["queued_for_parsing"] is True
        import_id = body["import_id"]

        # Nothing has parsed yet: parsing is the worker's job, not the request's.
        detail = anonymous_client.get("/api/imports/%d" % import_id).json()
        assert detail["status"] == "pending"
        assert detail["day_count"] == 0

        # Now run the worker.
        store = ObjectStore(settings.storage_dir)
        worker = TachographImporter(clean_db, store, default_registry(), settings)
        assert process_all(worker) == 1

        detail = anonymous_client.get("/api/imports/%d" % import_id).json()
        assert detail["status"] == "done"
        assert detail["day_count"] == 3

        timeline = anonymous_client.get(
            "/api/imports/%d/timeline" % import_id
        ).json()
        assert len(timeline["changes"]) == 27  # 9 changes x 3 days

        drivers = anonymous_client.get("/api/drivers").json()
        assert drivers["count"] == 1
        assert drivers["driver_cards"][0]["holder_surname"] == "Rossi"

        days = anonymous_client.get(
            "/api/days",
            params={
                "date_from": WEEK_DAY.isoformat(),
                "date_to": (WEEK_DAY + _dt.timedelta(days=2)).isoformat(),
            },
        ).json()
        assert days["count"] == 3

        coverage = anonymous_client.get(
            "/api/coverage",
            params={
                "driver_key": days["days"][0]["driver_key"],
                "date_from": WEEK_DAY.isoformat(),
                "date_to": (WEEK_DAY + _dt.timedelta(days=4)).isoformat(),
            },
        ).json()
        assert len(coverage["days_missing"]) == 2
        assert coverage["rest_findings_reliable"] is False

    def test_the_csv_report_carries_its_provenance(self, anonymous_client, clean_db, settings):
        importer = TachographImporter(
            clean_db,
            ObjectStore(settings.storage_dir),
            default_registry(),
            settings,
        )
        importer.ingest(
            "driver.ddd",
            make_sample_card_download(first_day=WEEK_DAY, number_of_days=2),
            "tester",
        )
        process_all(importer)
        driver_key = ImportRepository(clean_db).list_days()[0]["driver_key"]

        response = anonymous_client.get(
            "/api/reports/activity.csv",
            params={
                "driver_key": driver_key,
                "date_from": WEEK_DAY.isoformat(),
                "date_to": (WEEK_DAY + _dt.timedelta(days=1)).isoformat(),
            },
        )
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert response.headers["cache-control"].startswith("no-store")

        text = response.text
        # Parse it the way a consumer would, rather than counting newlines: the
        # contract is a metadata block plus a header row plus one row per day.
        import csv as _csv
        import io as _io

        rows = list(_csv.reader(_io.StringIO(text)))
        metadata = {
            row[0].lstrip("# ").strip(): (row[1] if len(row) > 1 else "")
            for row in rows
            if row and row[0].startswith("#")
        }
        assert metadata["rules_version"] == driving_time.RULES_VERSION
        assert metadata["engine_version"] == driving_time.ENGINE_VERSION
        assert metadata["parser_version"]
        assert metadata["calculation_validated_against_reference"] == "false"
        assert metadata["generated_at_utc"]
        assert metadata["driver_key"] == driver_key
        assert metadata["units"] == "minutes"

        header_index = next(
            index for index, row in enumerate(rows) if row and row[0] == "day"
        )
        header = rows[header_index]
        assert header == [
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
        data_rows = [row for row in rows[header_index + 1 :] if row]
        assert len(data_rows) == 2
        assert [row[0] for row in data_rows] == [
            (WEEK_DAY + _dt.timedelta(days=1)).isoformat(),
            WEEK_DAY.isoformat(),
        ]
        assert all(row[2] == "480" for row in data_rows)

    def test_a_calculation_can_be_run_and_read_back_over_http(
        self, anonymous_client, clean_db, settings
    ):
        importer = TachographImporter(
            clean_db,
            ObjectStore(settings.storage_dir),
            default_registry(),
            settings,
        )
        importer.ingest(
            "driver.ddd",
            make_sample_card_download(first_day=WEEK_DAY, number_of_days=5),
            "tester",
        )
        process_all(importer)
        driver_key = ImportRepository(clean_db).list_days()[0]["driver_key"]

        response = anonymous_client.post(
            "/api/calculations",
            json={
                "driver_key": driver_key,
                "period_start": WEEK_DAY.isoformat(),
                "period_end": (WEEK_DAY + _dt.timedelta(days=4)).isoformat(),
            },
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["validated_against_reference"] is False
        assert payload["rules_version"] == driving_time.RULES_VERSION
        assert set(payload["daily_driving_minutes"]) == {
            (WEEK_DAY + _dt.timedelta(days=offset)).isoformat() for offset in range(5)
        }
        assert all(minutes == 480 for minutes in payload["daily_driving_minutes"].values())

        read_back = anonymous_client.get(
            "/api/calculations/%d" % payload["calculation_id"]
        ).json()
        assert read_back["status"] == payload["status"]

    def test_a_reversed_period_is_rejected(self, anonymous_client):
        response = anonymous_client.post(
            "/api/calculations",
            json={
                "driver_key": "card:X",
                "period_start": WEEK_DAY.isoformat(),
                "period_end": (WEEK_DAY - _dt.timedelta(days=1)).isoformat(),
            },
        )
        assert response.status_code == 400

    def test_reading_driver_data_is_audited_with_the_actor_and_role(
        self, anonymous_client, clean_db
    ):
        """Every read of driver data leaves a trace, including who and with what role."""
        response = anonymous_client.get("/api/drivers")
        assert response.status_code == 200
        rows = ImportRepository(clean_db).audit_trail(subject_type="driver_card_registry")
        assert rows, "reading the driver card registry was not audited"
        assert rows[0]["action"] == "driver_cards.list"
        assert rows[0]["actor"] == "test-owner"
        assert rows[0]["actor_role"] == "owner"

    def test_only_an_owner_may_read_the_audit_log(self, viewer_client, anonymous_client):
        assert viewer_client.get("/api/audit").status_code == 403
        assert anonymous_client.get("/api/audit").status_code == 200

    def test_ingest_is_audited(self, anonymous_client, clean_db):
        anonymous_client.post(
            "/api/imports",
            files={"file": ("driver.ddd", make_sample_card_download(number_of_days=1))},
        )
        rows = ImportRepository(clean_db).audit_trail(subject_type="import")
        assert any(row["action"] == "import.ingest" for row in rows)
