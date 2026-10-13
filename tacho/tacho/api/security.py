"""Authentication and authorisation for the internal tachograph API.

Two layers, both necessary and neither sufficient alone:

1. **A service token.** The API is internal — the specification requires the parser
   service and internal APIs stay private. The token proves the caller is the
   dashboard and not something else on the Docker network. It is compared with
   ``hmac.compare_digest`` so a wrong token cannot be discovered by timing.

2. **A forwarded actor and role.** The dashboard authenticates the human against
   Traccar and forwards who they are. This service trusts that assertion only
   because layer 1 established the caller, and it records both in the audit log.

Roles are the two the specification names. Driver personal data is readable only by
``owner`` and ``fleet_manager`` — the same boundary the rest of the platform uses.

This is deliberately *not* a user database. One authentication system, one place
where a second factor can be added later.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, Request, status

ROLE_OWNER = "owner"
ROLE_FLEET_MANAGER = "fleet_manager"
ROLE_VIEWER = "viewer"

KNOWN_ROLES = frozenset({ROLE_OWNER, ROLE_FLEET_MANAGER, ROLE_VIEWER})

#: Roles allowed to see driver personal data (names, card numbers, activity).
DRIVER_DATA_ROLES = frozenset({ROLE_OWNER, ROLE_FLEET_MANAGER})


@dataclass(frozen=True)
class Actor:
    """Who is making the request, as asserted by the dashboard."""

    name: str
    role: str
    source_ip: Optional[str] = None

    @property
    def may_read_driver_data(self) -> bool:
        return self.role in DRIVER_DATA_ROLES


class Authenticator:
    def __init__(self, expected_token: str, allow_anonymous: bool = False) -> None:
        self.expected_token = expected_token
        self.allow_anonymous = allow_anonymous

    def verify_token(self, authorization: Optional[str], header_token: Optional[str]) -> None:
        if self.allow_anonymous:
            return
        if not self.expected_token:
            # Configuration validation should have caught this; fail closed anyway.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="the service has no API token configured and will not serve "
                "driver data without one",
            )

        presented = header_token or ""
        if not presented and authorization:
            scheme, _, value = authorization.partition(" ")
            if scheme.lower() == "bearer":
                presented = value.strip()

        if not presented or not hmac.compare_digest(presented, self.expected_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="a valid service token is required",
                headers={"WWW-Authenticate": "Bearer"},
            )


def client_ip(request: Request) -> Optional[str]:
    """The calling address, from the forwarded header if a proxy set one."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def build_actor(
    request: Request,
    x_actor: Optional[str],
    x_actor_role: Optional[str],
    allow_anonymous: bool,
) -> Actor:
    """Resolve the forwarded identity into an :class:`Actor`.

    An unknown or missing role becomes the least-privileged role, never a
    privileged one. Defaulting an unlabelled caller to ``owner`` would make a
    missing header a privilege escalation.
    """
    name = (x_actor or "").strip() or ("anonymous" if allow_anonymous else "")
    role = (x_actor_role or "").strip().lower()
    if role not in KNOWN_ROLES:
        role = ROLE_VIEWER
    if not name:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Actor is required: the dashboard must forward the "
            "authenticated user",
        )
    return Actor(name=name, role=role, source_ip=client_ip(request))


def require_driver_data(actor: Actor) -> None:
    """Gate a route that exposes driver personal data."""
    if not actor.may_read_driver_data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="role '%s' may not read driver personal data" % actor.role,
        )


def make_dependencies(authenticator: Authenticator, allow_anonymous: bool):
    """Build the FastAPI dependencies, closing over the authenticator."""

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
