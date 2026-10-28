"""Idempotency-Key handling for mutating scrap endpoints.

A client that retries a POST after a timeout sends the same Idempotency-Key. The
service stores a scoped key and a hash of the request body on the created row; a
retry with the same key and body returns the original result instead of posting
again. The same key with a different body is refused.

The key is scoped by route and actor, so two users (or two endpoints) may use the
same string without colliding.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


class IdempotencyKeyError(ValueError):
    pass


def normalise_key(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    key = raw.strip()
    if not key:
        return None
    if not KEY_PATTERN.match(key):
        raise IdempotencyKeyError(
            "Idempotency-Key must be 8-128 characters of letters, digits, '.', '_', ':' or '-'"
        )
    return key


def scoped_key(route: str, actor: str, key: str) -> str:
    return "%s|%s|%s" % (route, actor, key)


def request_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
