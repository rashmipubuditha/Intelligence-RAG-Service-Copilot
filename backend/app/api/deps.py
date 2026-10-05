"""Dependency injection for routes.

Everything a route needs arrives through `Depends`, which keeps handlers thin and makes them
testable by overriding one provider. Auth is expressed as role requirements
(`RequireWrite`) so swapping the identity source later changes `get_caller` alone and no
route signatures.
"""

from __future__ import annotations

from typing import Annotated

from app.container import AppContainer
from app.core.config import Settings
from app.core.security import Caller, RateLimiter, Role, require_role, verify_api_key
from fastapi import Depends, Header, Request


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.container.settings


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def get_caller(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Caller:
    settings: Settings = request.app.state.container.settings
    caller = verify_api_key(
        x_api_key, settings.api_key, settings.api_key_role, public_read=settings.public_read
    )
    request.state.caller = caller
    return caller


def _role_dependency(minimum: Role):
    def dependency(caller: Annotated[Caller, Depends(get_caller)]) -> Caller:
        require_role(caller, minimum)
        return caller

    return dependency


RequireRead = Annotated[Caller, Depends(_role_dependency("viewer"))]
RequireWrite = Annotated[Caller, Depends(_role_dependency("analyst"))]
RequireAdmin = Annotated[Caller, Depends(_role_dependency("admin"))]

ContainerDep = Annotated[AppContainer, Depends(get_container)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def rate_limit_bucket(request: Request, caller: Caller, suffix: str = "") -> str:
    """Key limits by API key when authenticated, otherwise by client IP."""
    if caller.authenticated:
        base = f"key:{caller.key_id}"
    else:
        client = request.client.host if request.client else "unknown"
        base = f"ip:{client}"
    return f"{base}{':' + suffix if suffix else ''}"
