from typing import Any

import pytest
from nicegui.testing.user import User

from tests.helpers.web import TOKEN
from ynab_unlinked.web.security import COOKIE_NAME, TokenGuard

pytestmark = pytest.mark.version("V4")


@pytest.mark.parametrize(
    "path",
    ["/", "/settings", "/onboarding", "/yul-static/yul.css", "/_nicegui_ws/socket.io/?EIO=4"],
    ids=["root", "view", "onboarding", "static", "socket-polling"],
)
async def test_requests_without_the_session_are_forbidden(guest: User, path: str):
    response = await guest.http_client.get(path)

    assert response.status_code == 403


async def test_a_wrong_token_is_forbidden(guest: User):
    response = await guest.http_client.get("/?token=not-the-token")

    assert response.status_code == 403
    assert COOKIE_NAME not in response.cookies


async def test_the_token_is_traded_for_a_strict_cookie_and_dropped_from_the_url(guest: User):
    response = await guest.http_client.get(f"/settings?tab=loaders&token={TOKEN}")

    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"].lower()
    assert f"{COOKIE_NAME}={TOKEN}".lower() in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    assert 'location.replace("/settings?tab=loaders")' in response.text
    assert TOKEN not in response.text


async def test_the_cookie_alone_opens_the_app_afterwards(guest: User):
    await guest.http_client.get(f"/?token={TOKEN}")

    response = await guest.http_client.get("/settings")

    assert response.status_code == 200
    assert response.headers.get("X-Nicegui-Content") == "page"


async def test_a_websocket_without_the_cookie_is_closed_before_reaching_the_app():
    reached: list[str] = []
    sent: list[dict[str, Any]] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        reached.append(scope["path"])

    async def receive() -> dict[str, Any]:
        return {"type": "websocket.connect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    guard = TokenGuard(app, token=TOKEN)
    scope = {
        "type": "websocket",
        "path": "/_nicegui_ws/socket.io/",
        "headers": [],
        "query_string": b"",
    }

    await guard(scope, receive, send)
    assert reached == []
    assert sent[0]["type"] == "websocket.close"

    cookie = f"{COOKIE_NAME}={TOKEN}".encode()
    await guard({**scope, "headers": [(b"cookie", cookie)]}, receive, send)
    assert reached == ["/_nicegui_ws/socket.io/"]
