"""Pure services shared by the CLI and the web app.

Nothing in this package imports typer, rich, textual, nicegui or `ynab_unlinked.cli`: the
CLI (`cli/`) and the web app (`web/`) import `core`, never the other way round. See
.claude/skills/yul-web-design/ARCHITECTURE.md.
"""
