from typing import Any

import pytest
from nicegui.testing.user import User

from tests.helpers.web import PORT, TOKEN
from ynab_unlinked.web.security import TokenGuard, cookie_name

COOKIE_NAME = cookie_name(PORT)
HOST = f"127.0.0.1:{PORT}".encode()

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


@pytest.mark.parametrize("path", ["/", "/settings", "/yul-static/yul.css"])
async def test_every_response_forbids_framing_the_app(user: User, path: str):
    response = await user.http_client.get(path)

    assert response.status_code == 200
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_refused_and_bounce_responses_forbid_framing_too(guest: User):
    refused = await guest.http_client.get("/settings")
    bounce = await guest.http_client.get(f"/?token={TOKEN}")

    for response in (refused, bounce):
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["content-security-policy"] == "frame-ancestors 'none'"


def websocket_scope(*headers: tuple[bytes, bytes]) -> dict[str, Any]:
    return {
        "type": "websocket",
        "path": "/_nicegui_ws/socket.io/",
        "headers": list(headers),
        "query_string": b"",
    }


async def knock(scope: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Send `scope` through the guard: the paths that reached the app and what was sent back."""
    reached: list[str] = []
    sent: list[dict[str, Any]] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        reached.append(scope["path"])

    async def receive() -> dict[str, Any]:
        return {"type": "websocket.connect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await TokenGuard(app, token=TOKEN, port=PORT)(scope, receive, send)
    return reached, sent


async def test_a_websocket_without_the_cookie_is_closed_before_reaching_the_app():
    reached, sent = await knock(websocket_scope((b"host", HOST)))
    assert reached == []
    assert sent[0]["type"] == "websocket.close"

    cookie = f"{COOKIE_NAME}={TOKEN}".encode()
    reached, _ = await knock(websocket_scope((b"host", HOST), (b"cookie", cookie)))
    assert reached == ["/_nicegui_ws/socket.io/"]


@pytest.mark.parametrize(
    "origin",
    [f"http://127.0.0.1:{PORT + 1}", f"http://localhost:{PORT}", "https://example.com", "null"],
    ids=["other-port", "other-name", "web-page", "opaque"],
)
async def test_a_websocket_from_another_origin_is_closed_even_with_the_cookie(origin: str):
    cookie = f"{COOKIE_NAME}={TOKEN}".encode()

    reached, sent = await knock(
        websocket_scope((b"host", HOST), (b"cookie", cookie), (b"origin", origin.encode()))
    )

    assert reached == []
    assert sent[0]["type"] == "websocket.close"


async def test_a_websocket_from_the_app_itself_is_let_through():
    cookie = f"{COOKIE_NAME}={TOKEN}".encode()
    origin = f"http://127.0.0.1:{PORT}".encode()

    reached, _ = await knock(
        websocket_scope((b"host", HOST), (b"cookie", cookie), (b"origin", origin))
    )

    assert reached == ["/_nicegui_ws/socket.io/"]


async def test_a_post_from_another_origin_is_forbidden_even_with_the_cookie(user: User):
    own = await user.http_client.post("/settings", headers={"Origin": f"http://127.0.0.1:{PORT}"})
    foreign = await user.http_client.post(
        "/settings", headers={"Origin": f"http://127.0.0.1:{PORT + 1}"}
    )

    # The guard lets the app's own origin through
    assert own.status_code != 403
    assert foreign.status_code == 403


async def test_a_get_from_another_origin_is_still_served(user: User):
    response = await user.http_client.get(
        "/settings", headers={"Origin": f"http://127.0.0.1:{PORT + 1}"}
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "host",
    [f"127.0.0.1:{PORT + 1}", f"localhost:{PORT}", f"evil.example:{PORT}", "127.0.0.1"],
    ids=["other-port", "localhost", "rebound-name", "no-port"],
)
async def test_a_request_for_another_host_is_forbidden_even_with_the_cookie(user: User, host: str):
    response = await user.http_client.get("/settings", headers={"Host": host})

    assert response.status_code == 403


async def test_the_token_is_not_traded_for_a_cookie_on_another_host(guest: User):
    response = await guest.http_client.get(
        f"/?token={TOKEN}", headers={"Host": f"evil.example:{PORT}"}
    )

    assert response.status_code == 403
    assert COOKIE_NAME not in response.cookies


def test_the_cookie_name_carries_the_port():
    assert cookie_name(8771) == "yul_session_8771"
    assert cookie_name(8771) != cookie_name(8772)


async def test_a_cookie_of_another_run_does_not_open_the_app(guest: User):
    guest.http_client.cookies.set(cookie_name(PORT + 1), TOKEN)

    response = await guest.http_client.get("/settings")

    assert response.status_code == 403
