from typer.testing import CliRunner

from ynab_unlinked import app

runner = CliRunner()
runner.invoke(app, ["load", "sabadell", "-t", "xls", "/Users/jparaque/code/ynab-unlinked/test.xls"])
