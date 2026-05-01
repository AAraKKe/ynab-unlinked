"""Interactive setup flow and the ``ensure_config`` helper.

Lives in its own module so commands that need it can import without
pulling ``main`` (avoids import cycles).
"""

from __future__ import annotations

from typing import cast

import typer

from ynab_unlinked.config import ConfigV2, get_config
from ynab_unlinked.config.core import ConfigError
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.display import bold, success
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.privacy import privacy_notice
from ynab_unlinked.utils import prompt_for_api_key, prompt_for_budget


def run_setup() -> ConfigV2:
    """Run the interactive setup flow and persist a fresh config."""
    bold("Welcome to ynab-unlinked! Lets setup your connection")
    privacy_notice()
    api_key = prompt_for_api_key()
    budget = prompt_for_budget(api_key)
    config = ConfigV2(api_key=api_key, budget=budget)
    config.save()
    success("All done!")
    return config


def _build_context(config: ConfigV2) -> YnabUnlinkedContext:
    return YnabUnlinkedContext(
        config=config,
        extras=None,
        formatter=Formatter(
            date_format=config.budget.date_format,
            currency_format=config.budget.currency_format,
        ),
    )


def load_context() -> YnabUnlinkedContext | None:
    """Try to load the persisted config and wrap it in a YnabUnlinkedContext.

    Returns ``None`` if no config exists or the file cannot be loaded
    (e.g. corrupted). The caller decides whether to prompt setup or
    bail out.
    """
    try:
        config = get_config()
    except Exception:
        return None

    if config is None:
        return None

    return _build_context(cast(ConfigV2, config))


def ensure_config(context: typer.Context) -> YnabUnlinkedContext:
    """Make sure ``context.obj`` has a valid config, prompting setup if missing."""
    obj: YnabUnlinkedContext | None = context.obj
    if obj is not None:
        return obj

    config = get_config()
    if config is None:
        config = run_setup()

    if config is None:
        raise ConfigError("Unexpected error: config could not be loaded after setup")

    obj = _build_context(cast(ConfigV2, config))
    context.obj = obj
    return obj
