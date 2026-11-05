"""Privacy notice text and helpers shared across commands.

Keep the wording here in sync with the PRIVACY.md document at the repo root.
"""

from __future__ import annotations

from ynab_unlinked import keychain
from ynab_unlinked.config.paths import config_path
from ynab_unlinked.display import bullet_list, console, info, warning
from ynab_unlinked.store import store_path
from ynab_unlinked.web import storage_dir as web_storage_dir

PRIVACY_DOC_URL = "https://github.com/AAraKKe/ynab-unlinked/blob/main/PRIVACY.md"


def storage_path() -> str:
    return str(config_path().parent)


def token_location() -> str:
    """Where the token is kept on this machine, for notices."""
    if (name := keychain.backend_name()) is not None:
        return f"in your {name} (item [cyan]{keychain.SERVICE}[/cyan])"
    return f"in plaintext at [cyan]{storage_path()}[/cyan] (no keychain found on this computer)"


def privacy_notice() -> None:
    """Short notice shown before asking the user for their YNAB API key."""
    info(f"[bold]Heads up:[/bold] YNAB Unlinked keeps your API key {token_location()}.")
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
                f"Your YNAB Personal Access Token ({token_location()})",
                "Selected budget metadata (id, name, date and currency formats)",
                "The YNAB account each entity imports into",
                "Last reconciliation date",
                "A copy of your budget's transactions and accounts, kept in sync with YNAB",
                "An activity log of what YNAB Unlinked did (imports, reconciliations, "
                "balance adjustments)",
            ]
        )
    )

    info("\n[bold]Where[/bold]")
    info(
        bullet_list(
            [
                f"Configuration: [cyan]{storage_path()}[/cyan]",
                f"Transactions, accounts and activity log: [cyan]{store_path()}[/cyan]",
                f"Web app preferences (theme, sidebar): [cyan]{web_storage_dir()}[/cyan]",
            ]
        )
    )

    info("\n[bold]Deleting your data[/bold]")
    info(
        "Run [cyan]yul config reset[/cyan] to wipe all locally stored data, including "
        "your API key. Then revoke the token in YNAB → Account Settings → Developer "
        "Settings."
    )

    if not keychain.available():
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
