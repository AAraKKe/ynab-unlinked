# SPDX-FileCopyrightText: 2025-present Juanpe Araque <juanpe@committhatline.com>
#
# SPDX-License-Identifier: MIT

import typer

from ynab_unlinked.cli_errors import YulGroup

app = typer.Typer(no_args_is_help=True, cls=YulGroup)
