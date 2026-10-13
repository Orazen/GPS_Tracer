"""Parsing worker: claims queued imports and processes them.

Runs as its own container (``tacho-worker``), which is the specification's
requirement that parsing is isolated from the web request process. Operational
behaviour, stated so it can be reasoned about:

* One file at a time per worker. Several workers can run safely: claiming uses
  ``FOR UPDATE SKIP LOCKED``.
* A crash mid-parse leaves a row in ``processing``. Its lease expires and another
  worker reclaims it after ``TACHO_WORKER_LEASE_MINUTES``. Nothing is lost.
* Failures are counted. After ``TACHO_WORKER_MAX_ATTEMPTS`` the row becomes
  ``rejected`` and the queue stops retrying it, so a permanently malformed file
  cannot be retried forever.
* The loop never exits on a processing error. A single bad file must not stop the
  worker.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Optional

from .config import Settings, load_settings
from .db import Database, MigrationError
from .importer import TachographImporter
from .parsers import default_registry
from .storage import ObjectStore

logger = logging.getLogger("tacho.worker")

_shutdown = False


def _handle_signal(signum, _frame) -> None:  # pragma: no cover - signal path
    global _shutdown
    logger.info("received signal %s, finishing the current file then stopping", signum)
    _shutdown = True


def build_importer(settings: Settings, db: Optional[Database] = None) -> TachographImporter:
    database = db or Database(settings.database_url)
    store = ObjectStore(settings.storage_dir)
    store.ensure_directories()
    return TachographImporter(
        database, store, default_registry(settings.external_parser), settings
    )


def run_once(importer: TachographImporter) -> bool:
    """Process at most one file. Returns True if a file was processed."""
    claimed = importer.claim_next()
    if claimed is None:
        return False
    logger.info(
        "processing import %d (%s), attempt %d",
        claimed["id"],
        claimed["original_filename"],
        claimed["attempts"],
    )
    outcome = importer.process(claimed)
    if outcome.status == "done":
        logger.info(
            "import %d done: %d day(s), %d change(s), %d warning(s)",
            outcome.import_id,
            outcome.days_written,
            outcome.changes_written,
            len(outcome.warnings),
        )
        for warning in outcome.warnings:
            logger.warning("import %d: %s", outcome.import_id, warning)
    else:
        logger.warning(
            "import %d not processed: status=%s code=%s message=%s",
            outcome.import_id,
            outcome.status,
            outcome.error_code,
            outcome.error_message,
        )
    return True


def main(argv: Optional[list] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="tacho.worker", description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="drain the queue and exit instead of looping. Useful from cron, and "
        "for verifying a deployment without leaving a process running.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="with --once, stop after this many files (0 = until the queue is empty)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = load_settings()
    problems = settings.validate()
    if problems:
        for problem in problems:
            logger.error("configuration problem: %s", problem)
        return 2

    if not args.once:
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    database = Database(settings.database_url)
    try:
        applied = database.apply_migrations()
        if applied:
            logger.info("applied %d migration(s)", len(applied))
    except MigrationError as exc:
        logger.error("migrations failed, refusing to start: %s", exc)
        return 3

    importer = build_importer(settings, database)
    logger.info(
        "worker ready (poll every %.1fs, lease %dmin, max attempts %d, adapters: %s)",
        settings.worker_poll_seconds,
        settings.worker_lease_minutes,
        settings.worker_max_attempts,
        ", ".join(parser.name for parser in importer.registry.parsers),
    )

    if args.once:
        processed = 0
        while not _shutdown and (args.max_files <= 0 or processed < args.max_files):
            try:
                worked = run_once(importer)
            except Exception:  # noqa: BLE001
                logger.exception("unexpected error while processing")
                return 4
            if not worked:
                break
            processed += 1
        logger.info("one-shot run finished, processed %d file(s)", processed)
        database.close()
        return 0

    idle_sleep = settings.worker_poll_seconds
    while not _shutdown:
        try:
            worked = run_once(importer)
        except Exception:  # noqa: BLE001 - the loop must survive anything
            logger.exception("unexpected error while processing; continuing")
            time.sleep(idle_sleep)
            continue
        if not worked:
            # Sleep only when idle, so a backlog drains without waiting.
            time.sleep(idle_sleep)

    logger.info("worker stopped")
    database.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
