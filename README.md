# YNAB Unlinked

`yul` is a companion for [YNAB](https://www.ynab.com) that runs on your computer. It does two
things YNAB cannot:

- **Keeps the accounts YNAB cannot link up to date.** Drop the statement your bank gives you
  and the new transactions land in the right account, duplicates skipped. Reconcile against
  what your bank says, and set by hand the balance of accounts that have no statement at all,
  like investments, a pension or shares.
- **Shows you what your budget data means.** From a local copy of your budget: how your net
  worth moved each month and why, which accounts grow and which lose, what you earn, spend and
  save, which categories take most of your money and how steady or swingy each one is.

Banks supported for imports today: **BBVA** (credit card PDF), **Sabadell** (TXT or XLS export)
and **Cobee** (saved HTML page). Adding one is a small Python package; see the
[wiki](https://github.com/AAraKKe/ynab-unlinked/wiki).

## Install

Python 3.13 or newer, tested on macOS and Linux. The recommended way is
[uv](https://docs.astral.sh/uv/):

```sh
uv tool install 'ynab-unlinked[web]'   # CLI and web app
uv tool install ynab-unlinked          # CLI only
```

`pip install 'ynab-unlinked[web]'` works too. Upgrade with `uv tool upgrade ynab-unlinked`.

You need a YNAB Personal Access Token: in YNAB go to Account Settings, then Developer Settings,
and create one. `yul` asks for it the first time it runs and keeps it in your system keychain.

## The app

```sh
yul app
```

The app opens in your browser and runs only on your computer. The first run connects your YNAB
account, picks the budget and asks where each bank's statements should go, then copies the
budget locally, so every page after that is instant. It syncs again in the background and after
every change it makes.

- **Home**: your net worth, a place to drop statements, and what needs you today.
- **Import**: drop one or more statements anywhere; `yul` works out the bank, shows what is new
  and imports it after one confirmation.
- **Reconcile**: type what your bank says, see the gap, reconcile the cleared transactions.

**Finances**

- **Net worth**
  - *Overview*: history by total, type or account, and the balances you update by hand.
  - *Months*: how much net worth moved each month, split into what you saved, what your assets
    did and the rest. Pick a month, or the whole range, to see where the change came from,
    which accounts moved and why, what came in and what went out.
  - *Movers*: every account's change, what you put in or took out, what it did on its own, and
    its return.
- **Cash flow**: income against spending month by month, your savings rate, how many months
  your cash would last, and where your income comes from.
- **Spending**: by group and by category, and how each category moves: steady, variable,
  spiky, or lumpy (big charges every so often, like a yearly subscription). Click a category to
  see its months and how they spread.

**Settings**: the connection, the banks, which accounts count in your net worth and in which
group, whose return to follow, the goal, the categories that are not spending, the look, and
your local data.

### How yul reads your money

Every transaction counts once, so the parts always add up to the change of net worth:

- **Income** is money that comes into an account on your budget, whatever its category.
  Refunds count too: they raise income and spending by the same amount.
- **Spending** is money that leaves an account on your budget, unless it goes to another of
  your accounts or its category is marked as not spending.
- **Assets** is what a tracking account (investments, shares, a pension) does on its own:
  market moves, interest, a sale recorded as an adjustment.
- **Transfers** between your accounts move nothing. Closed accounts count for the months they
  held money.

To get the most out of it, record a share vest as a split in the account your salary lands in
(the shares as income, then a transfer to the shares account) and a sale as a transfer to where
the money lands. Then income is your pay and the shares account only shows what the shares did.

## Command line

```sh
yul load auto ~/Downloads/movimientos.txt ~/Downloads/Cobee.html   # detects the bank of each file
yul load sabadell movimientos.txt                                  # or name the bank
yul load bbva --help                                               # options of one bank
yul reconcile                                                      # reconcile cleared transactions
yul config show                                                    # where things go
yul privacy                                                        # what is stored on this computer
```

The first command runs setup if there is no configuration yet. `yul load` shows every
transaction it is about to create and asks once before importing; add `--yes` to run it
unattended.

Send each bank to its own YNAB account. yul recognises what it already imported the way YNAB's
own file import does, by date, amount and how many times that pair repeats, without the bank.
Two banks feeding one account can then take a row of the same day and amount, imported in
separate runs, for one already in YNAB and skip it.

## Privacy

Everything runs on your computer and the only service it talks to is YNAB's API. There is no
telemetry. The copy of your budget stays on your computer. Your token lives in the system
keychain (macOS Keychain, Windows Credential Manager, Secret Service or KWallet on Linux).
`yul privacy` lists what is stored and where, `yul config reset` deletes all of it, and the
[privacy notice](./PRIVACY.md) has the details.

## Disclaimer

We are not affiliated, associated, or in any way officially connected with YNAB or any of its
subsidiaries or affiliates. The names "YNAB" and "You Need A Budget" are trademarks of their
respective owners.

## License

`ynab-unlinked` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html)
license.
