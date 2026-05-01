# Privacy Notice — YNAB Unlinked

_Last updated: 2026-05-01_

YNAB Unlinked runs entirely on your computer. The only network calls it makes are to YNAB's API at `https://api.ynab.com`, authenticated with the YNAB Personal Access Token you provide. Nothing is sent to any third party. There is no telemetry.

## Scope

This notice applies to the `ynab-unlinked` command-line tool (`yul`) distributed via PyPI.

## What this tool reads from YNAB

When you run a command, YNAB Unlinked may read the following from your YNAB account, scoped to the budget you selected during `yul setup`:

- Budgets (list and details)
- Accounts
- Transactions
- Payees

It also writes data back to YNAB on your behalf:

- Creates new transactions in the account you point it at.
- Updates existing transactions during reconciliation (cleared/reconciled state).

## What leaves your computer

Only HTTPS requests to `https://api.ynab.com`, made by the official `ynab` Python SDK and authenticated with your Personal Access Token.

There is no analytics, telemetry, crash reporting, or any other outbound traffic.

## Bank export files

`yul load` reads the bank export files (CSV, XLSX, PDF, …) you give it as input. These files are parsed locally, used to build the list of transactions, and never copied or transmitted outside the YNAB API calls described above. The tool does not retain a copy of them.

## What is stored locally

YNAB Unlinked stores a single JSON configuration file containing:

- Your YNAB Personal Access Token
- Selected budget metadata: id, name, date format, currency format
- Per-entity checkpoints (last processed date and transaction hash)
- Payee rules
- The date of your last reconciliation

The file is **plaintext** and **not encrypted**. Where it lives depends on your operating system (resolved via [`platformdirs`](https://pypi.org/project/platformdirs/)):

| OS      | Path                                                                |
| ------- | ------------------------------------------------------------------- |
| macOS   | `~/Library/Application Support/ynab-unlinked/config.json`           |
| Linux   | `$XDG_CONFIG_HOME/ynab-unlinked/config.json` (typically `~/.config/ynab-unlinked/config.json`) |
| Windows | `%APPDATA%\committhatline\ynab-unlinked\config.json`                |

If you have an old configuration created before version `0.7.0`, a legacy file may also exist at `~/.config/ynab_unlinked/config.json` (note the underscore).

You can run `yul privacy` at any time to print the resolved path on your machine.

### Security caveat

Because the token is stored in plaintext, anyone with read access to the file above can use it as if they were you. We strongly recommend:

- Use full-disk encryption (FileVault, LUKS, BitLocker).
- Restrict file permissions to your user (`chmod 600` on macOS/Linux).
- If you suspect the file has leaked, **revoke the token immediately** in YNAB → Account Settings → Developer Settings, and generate a new one.

## Dependencies that touch your data

These dependencies are loaded by the tool and may read or transmit data on your behalf:

- [`ynab`](https://pypi.org/project/ynab/) — the official YNAB SDK. Talks to `api.ynab.com` only.
- [`pdfplumber`](https://pypi.org/project/pdfplumber/), [`pyexcel`](https://pypi.org/project/pyexcel/), [`pyexcel-xls`](https://pypi.org/project/pyexcel-xls/), [`pyexcel-xlsx`](https://pypi.org/project/pyexcel-xlsx/) — local parsers for the import files you provide. They do not send any data anywhere.
- [`pydantic`](https://pypi.org/project/pydantic/), [`platformdirs`](https://pypi.org/project/platformdirs/), [`typer`](https://pypi.org/project/typer/), [`rich`](https://pypi.org/project/rich/), [`rapidfuzz`](https://pypi.org/project/rapidfuzz/), [`unidecode`](https://pypi.org/project/Unidecode/), [`html-text`](https://pypi.org/project/html-text/), [`textual`](https://pypi.org/project/textual/) — local utility libraries; none of them phone home.

## Telemetry

None. The tool does not collect or transmit any usage data, analytics, or crash reports.

## Third parties

The tool does not share any data with any third party. The only external service it talks to is YNAB itself.

## Deleting your data

To remove everything YNAB Unlinked has stored on your machine:

```sh
yul config reset
```

This deletes the configuration directory listed above, including your API key, budget, payee rules, and entity checkpoints. Pass `--yes` (or `-y`) to skip the confirmation prompt.

After deleting the local data, you may also want to **revoke the Personal Access Token** in YNAB → Account Settings → Developer Settings to ensure the token cannot be reused.

## Changes to this notice

Material changes to this notice will be announced in `CHANGELOG.md` and the _Last updated_ date at the top of this file will be bumped.

## Disclaimer

We are not affiliated, associated, or in any way officially connected with YNAB or any of its subsidiaries or affiliates. The names "YNAB" and "You Need A Budget" are trademarks of their respective owners.

## Contact

Questions, concerns, or requests can be filed at the [issue tracker](https://github.com/AAraKKe/ynab-unlinked/issues).
