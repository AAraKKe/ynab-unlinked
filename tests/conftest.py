from collections.abc import Generator
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from ynab_unlinked.config.core import VERSION_MAPPING


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

    config_paths_to_patch = [
        "ynab_unlinked.config.core.config_path",
        *[f"ynab_unlinked.config.models.{v.lower()}.config_path" for v in VERSION_MAPPING],
    ]

    with ExitStack() as stack:
        for module in config_paths_to_patch:

            def side_effect(v: str | None = None) -> Path:
                if not version.startswith("V"):
                    # For any special version, get whatever file is requested
                    # Make sure we do not accept any check for V1
                    if v == "V1":
                        return Path(f"tests/assets/config_{version}/no_config.json")

                    return Path(f"tests/assets/config_{version}/config.json")

                # When loading the path of a module that is not the same as the version being patched
                # set the path to a non-existing file
                if v == version:
                    return Path(f"tests/assets/config_{version}/config.json")

                return Path(f"tests/assets/config_{version}/no_config.json")

            stack.enter_context(patch(module, side_effect=side_effect))
        yield version
