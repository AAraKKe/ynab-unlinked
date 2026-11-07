# YNAB Unlinked

`yul` imports bank statements into [YNAB](https://www.ynab.com) for banks that YNAB cannot link. Drop the file your bank gives you and the transactions land in the right account, with duplicates skipped. It also helps you reconcile and keeps an eye on your net worth.

Banks supported today: **BBVA** (credit card PDF), **Sabadell** (TXT or XLS export) and **Cobee** (saved HTML page). Adding one is a small Python package; see the [wiki](https://github.com/AAraKKe/ynab-unlinked/wiki).

## Install

Python 3.13 or newer, tested on macOS and Linux. The recommended way is [uv](https://docs.astral.sh/uv/):

```sh
uv tool install 'ynab-unlinked[web]'   # CLI and web app
uv tool install ynab-unlinked          # CLI only
```

`pip install 'ynab-unlinked[web]'` works too. Upgrade with `uv tool upgrade ynab-unlinked`.

You need a YNAB Personal Access Token: in YNAB go to Account Settings, then Developer Settings, and create one. `yul` asks for it the first time it runs and keeps it in your system keychain.

## Web app

```sh
yul app
```

The app opens in your browser and runs only on your computer. The first run connects your YNAB account, picks the budget and asks where each bank's statements should go, then copies your budget so everything after that is instant.

- **Home**: net worth, a place to drop statements, and what needs you today.
- **Import**: drop one or more statements anywhere; `yul` works out the bank, shows what is new and imports it after one confirmation.
- **Reconcile**: type what your bank says, see the gap, lock the cleared transactions.
- **Net worth**: history by total, type or account; update by hand the balances of accounts that have no statement, like investments.
- **Settings**: the connection, the banks, which accounts count in your net worth, and your local data.

## Command line

```sh
yul load auto ~/Downloads/movimientos.txt ~/Downloads/Cobee.html   # detects the bank of each file
yul load sabadell movimientos.txt                                  # or name the bank
yul load bbva --help                                               # options of one bank
yul reconcile                                                      # lock cleared transactions
yul config show                                                    # where things go
yul privacy                                                        # what is stored on this computer
```

The first command runs setup if there is no configuration yet. `yul load` shows every transaction it is about to create and asks once before importing; add `--yes` to run it unattended.

Send each bank to its own YNAB account. yul recognises what it already imported the way YNAB's own file import does, by date, amount and how many times that pair repeats, without the bank. Two banks feeding one account can then take a row of the same day and amount, imported in separate runs, for one already in YNAB and skip it.

## Privacy

Everything runs on your computer and the only service it talks to is YNAB's API. There is no telemetry. Your token lives in the system keychain (macOS Keychain, Windows Credential Manager, Secret Service or KWallet on Linux). `yul privacy` lists what is stored and where, `yul config reset` deletes all of it, and the [privacy notice](./PRIVACY.md) has the details.

## Disclaimer

We are not affiliated, associated, or in any way officially connected with YNAB or any of its subsidiaries or affiliates. The names "YNAB" and "You Need A Budget" are trademarks of their respective owners.

## License

`ynab-unlinked` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
