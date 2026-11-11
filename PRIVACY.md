# Privacy Notice — YNAB Unlinked

_Last updated: 2026-11-11_

YNAB Unlinked runs entirely on your computer. Your data only travels to YNAB's API at `https://api.ynab.com`, authenticated with the YNAB Personal Access Token you provide. The one other network call is the web app asking PyPI whether a newer version exists: it carries nothing about you and can be turned off. None of your data is sent to any third party. There is no telemetry.

## Scope

This notice applies to the `ynab-unlinked` command-line tool (`yul`) distributed via PyPI, including the optional local web app (`yul app`, installed with the `web` extra).

## What this tool reads from YNAB

When you run a command or use the web app, YNAB Unlinked may read the following from your YNAB account, scoped to the budget you selected during `yul setup`:

- Budgets (list and details)
- Accounts
- Transactions
- Payees
- Categories, with their groups, targets and notes
- Months, with their notes and totals

It also writes data back to YNAB on your behalf:

- Creates new transactions in the account you point it at.
- Updates existing transactions during reconciliation (cleared/reconciled state).
- Creates balance adjustment transactions when you enter a new balance for an account you update by hand.

## What leaves your computer

HTTPS requests to `https://api.ynab.com`, made by the official `ynab` Python SDK and authenticated with your Personal Access Token. Nothing else carries your data.

The web app (`yul app`) also looks for new versions of itself. When you open it, and once a day while it stays open, it reads `https://pypi.org/pypi/ynab-unlinked/json`, a public document on PyPI, where yul is published. The request carries no token, no identifier and nothing about you or your budget; like any web request, PyPI sees the IP address it comes from. Turn it off in Settings › Data & privacy ("Look for new versions"). The command line never makes this call.

When a newer version is out the app offers to update. If you accept, it runs the upgrade command of the tool yul was installed with (`uv tool upgrade`, `pipx upgrade` or `pip install --upgrade`), which downloads the new version from PyPI exactly as installing it did, and then restarts. Nothing is downloaded or installed unless you ask for it.

There is no analytics, telemetry, crash reporting, or any other outbound traffic.

## Bank export files

`yul load` and the web app's Import screen read the bank export files (CSV, XLSX, PDF, …) you give it as input. These files are parsed locally, used to build the list of transactions, and never copied or transmitted outside the YNAB API calls described above. The tool does not retain a copy of them: files uploaded to the web app go to a temporary directory that is removed once the import ends or is discarded.

## What is stored locally

YNAB Unlinked keeps your YNAB Personal Access Token in the operating system's keychain, through the [`keyring`](https://pypi.org/project/keyring/) library: the macOS Keychain, the Windows Credential Manager, or Secret Service (GNOME Keyring) / KWallet on Linux. The item is named `ynab-unlinked`. On a computer without any of these (a headless server, say) the token stays in the configuration file below, in plaintext, and `yul privacy` says so. A token stored in the file by an older version moves to the keychain the first time the new version runs.

Besides the token, YNAB Unlinked stores a single JSON configuration file containing:

- A reference to the token in the keychain (or the token itself, where there is no keychain)
- Selected budget metadata: id, name, date format, currency format
- The YNAB account and default options of each bank loader
- The accounts you track for net worth, their bucket and whether you update them by hand
- Debt mappings and balance adjustment settings (memo, payee, cleared status)
- How the finance pages read your budget: the categories that are not spending, the accounts whose return to follow, and the category your goal is in
- The date of your last reconciliation
- Whether the web app looks for new versions

The file is **plaintext** and **not encrypted**. Where it lives depends on your operating system (resolved via [`platformdirs`](https://pypi.org/project/platformdirs/)):

| OS      | Path                                                                |
| ------- | ------------------------------------------------------------------- |
| macOS   | `~/Library/Application Support/ynab-unlinked/config.json`           |
| Linux   | `$XDG_CONFIG_HOME/ynab-unlinked/config.json` (typically `~/.config/ynab-unlinked/config.json`) |
| Windows | `%APPDATA%\committhatline\ynab-unlinked\config.json`                |

If you have an old configuration created before version `0.7.0`, a legacy file may also exist at `~/.config/ynab_unlinked/config.json` (note the underscore).

### Local transaction store

YNAB Unlinked also keeps a local copy of your budget's transactions (split lines included), accounts, categories and month notes, kept in sync with YNAB, plus an activity log of what it did (imports, reconciliations, balance adjustments). It is a SQLite file named `store.sqlite` in your user data directory (on macOS the same directory as the configuration, on Linux typically `~/.local/share/ynab-unlinked/`, on Windows `%LOCALAPPDATA%\committhatline\ynab-unlinked\`). It is not encrypted either, and `yul config reset` deletes it.

### Local web app

`yul app` runs a small web server on your computer and opens it in your browser. It listens on `127.0.0.1` only, so other machines on your network cannot reach it. Each run creates a random session token, carried by the link it prints; the browser trades it for an HttpOnly, SameSite=Strict cookie, and every request without it is refused. Requests addressed to any other host name, and changes or live connections coming from a web page of another origin (another server on `127.0.0.1` included), are refused too, and no web page may show the app inside a frame. The app loads no fonts, scripts or images from the internet and has no telemetry. It talks to `https://api.ynab.com` and, unless you turn it off, asks `https://pypi.org` for the latest version of yul (see "What leaves your computer"). When an update restarts the app, the new run keeps the session token of the one before it, handed from one to the other without ever being in a file or a command line, so the tabs you left open keep working.

Per browser preferences (theme, collapsed sidebar) and the secret that signs them are kept in a `web` directory inside your user data directory (next to `store.sqlite`), readable by your user only. `yul config reset` and the app's "Reset all data" delete it.

You can run `yul privacy` at any time to print the resolved paths on your machine.

### Security caveat

The keychain protects the token with your user session: another program running as you may still be allowed to read it, and macOS asks before a new program does. Where no keychain exists and the token is stored in plaintext, anyone with read access to the file above can use it as if they were you. We strongly recommend:

- Use full-disk encryption (FileVault, LUKS, BitLocker).
- Keep the files private to your user. yul writes the config file and `store.sqlite` readable by your user only (mode 600 on macOS/Linux); check this if you copy them elsewhere.
- If you suspect the file has leaked, **revoke the token immediately** in YNAB → Account Settings → Developer Settings, and generate a new one.

## Dependencies that touch your data

These dependencies are loaded by the tool and may read or transmit data on your behalf:

- [`ynab`](https://pypi.org/project/ynab/) — the official YNAB SDK. Talks to `api.ynab.com` only.
- [`pdfplumber`](https://pypi.org/project/pdfplumber/), [`pyexcel`](https://pypi.org/project/pyexcel/), [`pyexcel-xls`](https://pypi.org/project/pyexcel-xls/), [`pyexcel-xlsx`](https://pypi.org/project/pyexcel-xlsx/) — local parsers for the import files you provide. They do not send any data anywhere.
- [`pydantic`](https://pypi.org/project/pydantic/), [`platformdirs`](https://pypi.org/project/platformdirs/), [`typer`](https://pypi.org/project/typer/), [`rich`](https://pypi.org/project/rich/), [`rapidfuzz`](https://pypi.org/project/rapidfuzz/), [`unidecode`](https://pypi.org/project/Unidecode/), [`html-text`](https://pypi.org/project/html-text/), [`textual`](https://pypi.org/project/textual/) — local utility libraries; none of them phone home.
- [`keyring`](https://pypi.org/project/keyring/) — stores and reads the token in your system keychain. It talks to the local keychain service only.
- [`nicegui`](https://pypi.org/project/nicegui/) (only with the `web` extra) — serves the local web app on `127.0.0.1` from its bundled assets. It does not phone home.

## Telemetry

None. The tool does not collect or transmit any usage data, analytics, or crash reports.

## Third parties

The tool does not share any data with any third party. The only external services it talks to are YNAB itself and, for the version check described above, PyPI.

## Deleting your data

To remove everything YNAB Unlinked has stored on your machine:

```sh
yul config reset
```

This deletes the configuration directory listed above, including your API key, budget, loaders and tracked accounts, as well as the local transaction store and the web app preferences. Pass `--yes` (or `-y`) to skip the confirmation prompt.

`yul config reset` (and "Reset all data" in the app) also removes the token from the keychain. After deleting the local data, you may also want to **revoke the Personal Access Token** in YNAB → Account Settings → Developer Settings to ensure the token cannot be reused.

## Changes to this notice

Material changes to this notice will be announced in `CHANGELOG.md` and the _Last updated_ date at the top of this file will be bumped.

## Disclaimer

We are not affiliated, associated, or in any way officially connected with YNAB or any of its subsidiaries or affiliates. The names "YNAB" and "You Need A Budget" are trademarks of their respective owners.

## Contact

Questions, concerns, or requests can be filed at the [issue tracker](https://github.com/AAraKKe/ynab-unlinked/issues).
