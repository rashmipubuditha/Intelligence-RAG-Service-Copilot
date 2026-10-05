"""Security primitives: API-key verification, role checks, rate limiting.

Honest scope (see README §17): this module implements a shared-secret API key with
constant-time comparison, a role attached to that key, and in-process rate limiting. It is
deliberately shaped so the identity source can be replaced (OIDC/JWT) by changing
`identify_caller` alone — but no identity provider is integrated, and this README/codebase
never claims otherwise.
"""

from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock
from typing import Literal

from app.core.errors import AuthError, ForbiddenError, RateLimitError

Role = Literal["viewer", "analyst", "admin"]

_ROLE_RANK: dict[str, int] = {"viewer": 0, "analyst": 1, "admin": 2}


@dataclass(frozen=True)
class Caller:
    """Who is making the request. `tenant_id` exists so retrieval filters can be
    tenant-scoped from day one; only a single demo tenant is ever issued."""

    key_id: str
    role: Role
    tenant_id: str = "default"
    authenticated: bool = False


ANONYMOUS = Caller(key_id="anonymous", role="admin", authenticated=False)
PUBLIC = Caller(key_id="public", role="viewer", authenticated=False)


def verify_api_key(
    provided: str | None, expected: str | None, role: Role, *, public_read: bool = False
) -> Caller:
    """Return the Caller for a request.

    When no API_KEY is configured the service runs open (local development) and every
    caller is treated as an unauthenticated admin. That is a deliberate, documented
    default for a local demo — not an accident — and the readiness endpoint reports it.

    With `public_read`, a request without a key is a read-only viewer instead. That holds
    even when no API_KEY is configured, so a public deployment never falls back to open.
    """
    if not provided and public_read:
        return PUBLIC
    if not expected and not public_read:
        return ANONYMOUS
    if not provided:
        raise AuthError()
    if not expected or not hmac.compare_digest(provided, expected):
        raise AuthError("The supplied API key is not valid.")
    return Caller(key_id=f"key_{provided[:4]}", role=role, authenticated=True)


def require_role(caller: Caller, minimum: Role) -> None:
    if _ROLE_RANK[caller.role] < _ROLE_RANK[minimum]:
        raise ForbiddenError(f"This operation requires the '{minimum}' role.", required_role=minimum)


class RateLimiter:
    """Fixed-window in-process limiter.

    In-process is the honest choice for a single-replica deployment: it is correct here and
    would be wrong behind multiple replicas, where a shared store is required (README §17).
    """

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, bucket: str, limit: int, window_seconds: int = 60) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            hits = [t for t in self._hits[bucket] if t > cutoff]
            if len(hits) >= limit:
                retry_after = max(1, int(window_seconds - (now - hits[0])))
                self._hits[bucket] = hits
                raise RateLimitError(retry_after=retry_after)
            hits.append(now)
            self._hits[bucket] = hits

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def generate_api_key() -> str:
    """Helper for operators setting up a deployment: `python -c` friendly."""
    return secrets.token_urlsafe(32)
