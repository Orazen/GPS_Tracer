"""Authentication and authorisation for the internal scrap API."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, Request, status

ROLE_OWNER = "owner"
ROLE_FLEET_MANAGER = "fleet_manager"
ROLE_VIEWER = "viewer"
ROLE_WAREHOUSE = "warehouse_operator"

KNOWN_ROLES = frozenset({ROLE_OWNER, ROLE_FLEET_MANAGER, ROLE_VIEWER, ROLE_WAREHOUSE})


@dataclass(frozen=True)
class Actor:
    name: str
    role: str
    source_ip: Optional[str] = None

    @property
    def may_write(self) -> bool:
        return self.role in (ROLE_OWNER, ROLE_FLEET_MANAGER, ROLE_WAREHOUSE)


class Authenticator:
    def __init__(self, expected_token: str, allow_anonymous: bool = False) -> None:
        self.expected_token = expected_token
        self.allow_anonymous = allow_anonymous

    def verify_token(self, authorization: Optional[str], header_token: Optional[str]) -> None:
        if self.allow_anonymous:
            return
        if not self.expected_token:
            raise HTTPException(status_code=503, detail="no API token configured")
        presented = header_token or ""
        if not presented and authorization:
            scheme, _, value = authorization.partition(" ")
            if scheme.lower() == "bearer":
                presented = value.strip()
        if not presented or not hmac.compare_digest(presented, self.expected_token):
            raise HTTPException(status_code=401, detail="a valid service token is required",
                                headers={"WWW-Authenticate": "Bearer"})


def client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def build_actor(request, x_actor, x_actor_role, allow_anonymous):
    name = (x_actor or "").strip() or ("anonymous" if allow_anonymous else "")
    role = (x_actor_role or "").strip().lower()
    if role not in KNOWN_ROLES:
        role = ROLE_VIEWER
    if not name:
        raise HTTPException(status_code=401, detail="X-Actor is required")
    return Actor(name=name, role=role, source_ip=client_ip(request))


def require_write(actor: Actor) -> None:
    if not actor.may_write:
        raise HTTPException(status_code=403, detail="role '%s' may not write" % actor.role)


def make_dependencies(authenticator, allow_anonymous):
    async def authenticate(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_service_token: Optional[str] = Header(default=None),
        x_actor: Optional[str] = Header(default=None),
        x_actor_role: Optional[str] = Header(default=None),
    ) -> Actor:
        authenticator.verify_token(authorization, x_service_token)
        return build_actor(request, x_actor, x_actor_role, allow_anonymous)

    return authenticate
