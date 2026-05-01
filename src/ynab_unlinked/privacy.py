"""Privacy notice text and helpers shared across commands.

Keep the wording here in sync with the PRIVACY.md document at the repo root.
"""

from __future__ import annotations

from ynab_unlinked.config.paths import config_path
from ynab_unlinked.display import bullet_list, console, info, warning

PRIVACY_DOC_URL = "https://github.com/AAraKKe/ynab-unlinked/blob/main/PRIVACY.md"


def storage_path() -> str:
    return str(config_path().parent)


def privacy_notice() -> None:
    """Short notice shown before asking the user for their YNAB API key."""
    info(
        "[bold]Heads up:[/bold] YNAB Unlinked stores your API key locally on this "
        f"machine, in plaintext, at:\n  [cyan]{storage_path()}[/cyan]"
    )
    info(
        "All data stays on your computer — the only network calls go to api.ynab.com. "
        f"Full privacy notice: [link={PRIVACY_DOC_URL}]{PRIVACY_DOC_URL}[/link]"
    )


def privacy_summary() -> None:
    """Long-form summary printed by `yul privacy`."""
    console().rule("[bold]YNAB Unlinked — Privacy Summary[/bold]")
    info(
        "YNAB Unlinked runs entirely on your computer. The only network calls it "
        "makes are to YNAB's API at https://api.ynab.com. Nothing is sent to any "
        "third party. There is no telemetry."
    )

    info("\n[bold]What is stored locally[/bold]")
    info(
        bullet_list(
            [
                "Your YNAB Personal Access Token (plaintext)",
                "Selected budget metadata (id, name, date and currency formats)",
                "Per-entity checkpoints (last processed date and transaction hash)",
                "Payee rules",
                "Last reconciliation date",
            ]
        )
    )

    info(f"\n[bold]Where[/bold]: [cyan]{storage_path()}[/cyan]")

    info("\n[bold]Deleting your data[/bold]")
    info(
        "Run [cyan]yul config reset[/cyan] to wipe all locally stored data, including "
        "your API key. Then revoke the token in YNAB → Account Settings → Developer "
        "Settings."
    )

    warning(
        "\nYour API key is stored unencrypted. Anyone with read access to the file "
        "above can use it as if they were you. Use full-disk encryption and "
        "restrict file permissions accordingly."
    )

    info(
        f"\nFull privacy notice: [link={PRIVACY_DOC_URL}]{PRIVACY_DOC_URL}[/link]\n"
        "We are not affiliated, associated, or in any way officially connected with "
        "YNAB or any of its subsidiaries or affiliates."
    )
