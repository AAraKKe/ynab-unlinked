"""Keep other local programs and web pages away from the app.

The server only listens on the loopback interface, but anything running on this machine (or a
web page open in the browser) could still reach it, and the app holds the YNAB token. So every
run gets a random session token. The browser is opened on `/?token=<token>`; the first request
trades it for an HttpOnly, SameSite=Strict cookie and every later request, websocket handshakes
included, must carry that cookie. Everything else gets a 403.

Cookies are scoped by host, not by port, and every page served from another `127.0.0.1` port is
"same site". So the cookie name carries the port (two runs do not clobber each other), every
request must name exactly `127.0.0.1:<port>` as its Host (a page reaching the app through a
rebound DNS name is refused), and websocket handshakes and requests that change something must
come from the app's own origin when the browser says where they come from.
"""

from __future__ import annotations

import html
import json
import secrets
import socket
from urllib.parse import urlencode

from starlette.datastructures import URL, QueryParams
from starlette.requests import HTTPConnection
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

HOST = "127.0.0.1"
COOKIE_PREFIX = "yul_session"
TOKEN_PARAM = "token"

_SAFE_METHODS = ("GET", "HEAD")
_DEFAULT_HTTP_PORT = 80

# RFC 6455 "policy violation": the handshake did not carry a valid session
_WS_POLICY_VIOLATION = 1008


def new_token() -> str:
    return secrets.token_urlsafe(32)


def free_port() -> int:
    """A port nothing listens on right now on the loopback interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


def entry_url(port: int, token: str) -> str:
    """The URL the browser is opened on."""
    return f"{origin(port)}/?{urlencode({TOKEN_PARAM: token})}"


def origin(port: int) -> str:
    """The only origin the app's own pages have."""
    return f"http://{HOST}:{port}"


def cookie_name(port: int) -> str:
    """The session cookie of the run on `port`. Cookies ignore ports, so the name carries it."""
    return f"{COOKIE_PREFIX}_{port}"


def _without_token(url: URL) -> str:
    query = [
        (key, value) for key, value in QueryParams(url.query).multi_items() if key != TOKEN_PARAM
    ]
    path = url.path or "/"
    return f"{path}?{urlencode(query)}" if query else path


def _bounce(target: str, token: str, cookie: str) -> HTMLResponse:
    """Set the session cookie and move on to `target` without the token in the address bar.

    This is a page that navigates by itself rather than an HTTP redirect: a SameSite=Strict
    cookie is not sent along a redirect chain that started outside the site (the browser was
    opened by another program), but it is sent on a navigation the page itself starts.
    """
    location = json.dumps(target)
    body = (
        "<!doctype html><meta charset='utf-8'><title>yul</title>"
        f"<meta http-equiv='refresh' content='0;url={html.escape(target, quote=True)}'>"
        f"<script>location.replace({location})</script>"
    )
    response = HTMLResponse(
        body,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
    response.set_cookie(cookie, token, httponly=True, samesite="strict", path="/")
    return response


class TokenGuard:
    """ASGI middleware that lets a request through only with the session token or cookie.

    `port` is the one the app listens on: it names the cookie and the only Host and Origin
    accepted.
    """

    def __init__(self, app: ASGIApp, token: str, port: int) -> None:
        self.app = app
        self.token = token
        self.cookie = cookie_name(port)
        self.origin = origin(port)
        self.hosts = {f"{HOST}:{port}"}
        if port == _DEFAULT_HTTP_PORT:
            self.hosts.add(HOST)

    def _matches(self, value: str | None) -> bool:
        return value is not None and secrets.compare_digest(value.encode(), self.token.encode())

    def _trusted(self, scope: Scope, connection: HTTPConnection) -> bool:
        """Whether the request names this app as its host and, when it must, its origin."""
        if connection.headers.get("host") not in self.hosts:
            return False
        if scope["type"] == "http" and scope.get("method", "GET") in _SAFE_METHODS:
            return True
        # Browsers always send Origin on these; other local programs need the cookie anyway
        request_origin = connection.headers.get("origin")
        return request_origin is None or request_origin == self.origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        connection = HTTPConnection(scope)
        if self._trusted(scope, connection):
            if scope["type"] == "http" and self._matches(
                connection.query_params.get(TOKEN_PARAM)
            ):
                bounce = _bounce(_without_token(connection.url), self.token, self.cookie)
                await bounce(scope, receive, send)
                return

            if self._matches(connection.cookies.get(self.cookie)):
                await self.app(scope, receive, send)
                return

        if scope["type"] == "websocket":
            await WebSocketClose(code=_WS_POLICY_VIOLATION)(scope, receive, send)
            return

        response = PlainTextResponse(
            "This yul session needs the link printed by `yul app`.", status_code=403
        )
        await response(scope, receive, send)
