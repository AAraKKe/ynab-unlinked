import pytest
from nicegui.elements.query import QueryElement
from nicegui.testing.user import User

from ynab_unlinked.__about__ import __version__
from ynab_unlinked.web import theme
from ynab_unlinked.web.storage import user_storage

pytestmark = pytest.mark.version("V4")


def body_classes(user: User) -> list[str]:
    """The classes the page puts on `<body>` through `ui.query("body")`."""
    assert user.client is not None
    return next(
        element.props["classes"]
        for element in user.client.elements.values()
        if isinstance(element, QueryElement) and element.props["selector"] == "body"
    )


def palette_classes(user: User) -> list[str]:
    return [name for name in body_classes(user) if name.startswith("yul-theme-")]


async def test_a_browser_that_never_chose_gets_midnight(config_v4, user: User):
    await user.open("/")

    assert palette_classes(user) == ["yul-theme-midnight"]
    with user:
        assert theme.current_theme() is theme.DEFAULT_THEME is theme.THEMES["midnight"]
        assert theme.palette().accent == theme.THEMES["midnight"].dark.accent


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("twilight", "twilight"),
        ("graphite", "graphite"),
        ("solarized", "midnight"),
        (3, "midnight"),
    ],
    ids=["twilight", "graphite", "unknown-name", "not-a-name"],
)
async def test_the_stored_palette_styles_every_page(config_v4, user: User, stored, expected):
    await user.open("/")
    with user:
        user_storage()["yul.palette"] = stored

    await user.open("/networth")

    assert palette_classes(user) == [f"yul-theme-{expected}"]


async def test_the_chart_palette_follows_the_palette_and_the_variant(config_v4, user: User):
    await user.open("/")
    with user:
        theme.save_theme_choice(theme.THEMES["graphite"])
        theme.save_theme(dark=False)

        light = theme.palette()
        theme.save_theme(dark=True)
        dark = theme.palette()

    graphite = theme.THEMES["graphite"]
    assert (light.accent, dark.accent) == (graphite.light.accent, graphite.dark.accent)
    # The neutral colours stay those of the variant
    assert light.series == theme.SERIES_LIGHT
    assert dark.series == theme.SERIES


@pytest.mark.parametrize("path", ["/yul-static/yul.css", "/yul-static/fonts/InterVariable.woff2"])
async def test_the_browser_keeps_no_copy_of_the_apps_files(user: User, path: str):
    response = await user.http_client.get(path)

    # A copy kept across an update would draw the new pages with the old stylesheet
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=0"

    # It asks every time, and a file that did not change is not sent again
    again = await user.http_client.get(path, headers={"If-None-Match": response.headers["etag"]})

    assert again.status_code == 304


async def test_the_stylesheet_of_another_version_has_another_address(user: User):
    response = await user.http_client.get("/")

    assert f'href="/yul-static/yul.css?v={__version__}"' in response.text
