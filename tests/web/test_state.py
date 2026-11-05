import datetime as dt

import pytest

from tests.helpers.config import ConfigFiles
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.web.state import AppState, NotConfiguredError

pytestmark = pytest.mark.version("V4")


def test_update_config_applies_the_change_to_the_file_not_to_the_old_copy(config: str):
    app = AppState()
    app.load()
    cli = LatestConfig.load()
    cli.last_reconciliation_date = dt.date(2025, 5, 10)
    cli.save()

    def change(config: LatestConfig) -> None:
        config.adjustments.payee = "Set by the app"

    saved = app.update_config(change)

    on_disk = LatestConfig.load()
    assert on_disk.last_reconciliation_date == dt.date(2025, 5, 10)
    assert on_disk.adjustments.payee == "Set by the app"
    assert saved == on_disk
    assert app.config == on_disk


@pytest.mark.version("missing")
def test_update_config_without_any_config_is_an_error(config: str, config_files: ConfigFiles):
    app = AppState()
    app.load()

    with pytest.raises(NotConfiguredError):
        app.update_config(lambda config: None)
    assert not config_files.path("V4").exists()
