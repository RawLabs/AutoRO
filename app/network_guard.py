from __future__ import annotations

import ipaddress
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit


logger = logging.getLogger("autoro.network_guard")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def is_loopback_address(value: str | None) -> bool:
    if not value:
        return False
    candidate = value.strip().strip("[]")
    if candidate.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    return bool(address.version == 6 and address.ipv4_mapped and address.ipv4_mapped.is_loopback)


def hostname_from_header(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip()
    if text.startswith("["):
        closing = text.find("]")
        return text[1:closing] if closing > 0 else ""
    return text.split(":", 1)[0]


def is_loopback_origin(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and is_loopback_address(parsed.hostname)


class LoopbackOnlyMiddleware:
    """Enforce AutoRO's supported single-workstation deployment boundary."""

    def __init__(self, app: Callable[..., Awaitable[Any]]):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        scope_type = scope.get("type")
        if scope_type not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        client = scope.get("client")
        client_host = str(client[0]) if client else ""
        host = hostname_from_header(headers.get("host"))
        method = str(scope.get("method") or "GET").upper()
        origin = headers.get("origin")
        fetch_site = headers.get("sec-fetch-site", "").lower()

        reason = ""
        if not is_loopback_address(client_host):
            reason = "non-loopback client"
        elif not is_loopback_address(host):
            reason = "non-loopback Host header"
        elif method in UNSAFE_METHODS and origin and not is_loopback_origin(origin):
            reason = "cross-origin state change"
        elif method in UNSAFE_METHODS and fetch_site == "cross-site":
            reason = "cross-site state change"

        if not reason:
            await self.app(scope, receive, send)
            return

        logger.warning("Blocked request outside loopback policy: %s", reason)
        if scope_type == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": "Loopback access only"})
            return
        body = json.dumps({"detail": "AutoRO accepts requests only from this workstation."}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})
