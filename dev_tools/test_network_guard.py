from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.network_guard import LoopbackOnlyMiddleware, is_loopback_address, is_loopback_origin


async def ok_app(scope, receive, send):
    body = b"ok"
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": body})


def request_status(
    client: str = "127.0.0.1",
    host: str = "127.0.0.1:8000",
    method: str = "GET",
    origin: str | None = None,
    fetch_site: str | None = None,
) -> tuple[int, dict]:
    headers = [(b"host", host.encode("ascii"))]
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))
    if fetch_site is not None:
        headers.append((b"sec-fetch-site", fetch_site.encode("ascii")))
    scope = {
        "type": "http",
        "method": method,
        "path": "/api/test",
        "headers": headers,
        "client": (client, 50000),
        "server": ("127.0.0.1", 8000),
    }
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(LoopbackOnlyMiddleware(ok_app)(scope, receive, send))
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    body = next(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return status, json.loads(body) if status != 200 else {"body": body.decode()}


class NetworkGuardTests(unittest.TestCase):
    def test_loopback_variants_are_recognized(self) -> None:
        for value in ("127.0.0.1", "127.1.2.3", "::1", "::ffff:127.0.0.1", "localhost"):
            self.assertTrue(is_loopback_address(value), value)
        for value in ("0.0.0.0", "192.168.1.10", "8.8.8.8", "shop.example"):
            self.assertFalse(is_loopback_address(value), value)

    def test_normal_local_requests_are_allowed(self) -> None:
        self.assertEqual((200, {"body": "ok"}), request_status())
        self.assertEqual(200, request_status(host="localhost:8000", method="POST", origin="http://localhost:8000")[0])

    def test_non_loopback_client_is_rejected_even_with_localhost_host(self) -> None:
        status, _ = request_status(client="192.168.1.50", host="localhost:8000")
        self.assertEqual(403, status)

    def test_dns_rebinding_host_is_rejected(self) -> None:
        status, _ = request_status(host="attacker.example")
        self.assertEqual(403, status)

    def test_cross_site_state_changes_are_rejected(self) -> None:
        self.assertFalse(is_loopback_origin("https://attacker.example"))
        self.assertEqual(403, request_status(method="POST", origin="https://attacker.example")[0])
        self.assertEqual(403, request_status(method="POST", fetch_site="cross-site")[0])

    def test_cross_site_read_does_not_break_normal_navigation(self) -> None:
        self.assertEqual(200, request_status(method="GET", origin="https://attacker.example")[0])

    def test_guard_is_registered_on_assembled_fastapi_app(self) -> None:
        from app.main import app

        middleware_classes = [entry.cls for entry in app.user_middleware]
        self.assertIn(LoopbackOnlyMiddleware, middleware_classes)


if __name__ == "__main__":
    unittest.main()
