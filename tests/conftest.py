from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def config(request: pytest.FixtureRequest) -> Generator[str]:
    """
    The config version can be requested either by marking the test with

    ```
    @pytest.mark.version("V2")
    ```

    or by passing the version as a string to the fixture request through indirect.

    If the fixture is accessed it yields the version it is pointing to
    """
    # Try to get version from marker first
    version_marker = request.node.get_closest_marker("version")
    if version_marker and version_marker.args:
        version = version_marker.args[0]
    # Fall back to fixture parameter if no marker
    elif hasattr(request, "param"):
        version = request.param
    else:
        pytest.fail(
            "When using the config fixture, either:\n"
            "1. Use a version marker: @pytest.mark.version('V1')\n"
            "2. Pass a version parameter through indirect parameterization"
        )

    # Point to the V1 folder if we are requesting V1
    v1_path = (
        Path("tests/assets/config_V1/config.json")
        if version == "V1"
        else Path(__file__).parent
    )

    with (
        patch("ynab_unlinked.config.core.v1_config_path") as v1_config_path_patch,
        patch("ynab_unlinked.config.core.user_config_dir") as user_config_dir_patch,
    ):
        user_config_dir_patch.return_value = f"tests/assets/config_{version}"
        v1_config_path_patch.return_value = v1_path
        yield version
