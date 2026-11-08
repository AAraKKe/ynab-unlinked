# Release notes

Welcome to the official ledger for `ynab-unlinked`! Just like you meticulously track your transactions, we keep a detailed account of every change we make to the project. Here you'll find a transparent record of new features hitting the market, bugs we've written off, and all the behind-the-scenes investments in our codebase.

To help us keep our books in order, these release notes are automatically generated using the wonderful [Towncrier](https://github.com/twisted/towncrier).

<!-- towncrier release notes start -->

## ynab-unlinked 1.0.0 (2026-11-05)

### Fresh Out of the Feature Oven
* `yul app` opens a local web app in your browser (install it with the `[web]` extra, e.g. `uv tool install 'ynab-unlinked[web]'`): a first run that connects YNAB, picks the budget and where each bank's statements go, then copies the budget; Home with your net worth, what needs attention and recent activity; Import, where dropped statements are detected and imported after one confirmation; Reconcile, comparing each account's cleared balance with the bank and reconciling the transactions; Net worth with its history, buckets and inline balance updates for accounts you update by hand; and Settings for the connection, banks, accounts, net worth and local data. It only listens on 127.0.0.1 and needs the link it prints.
* Add `yul load auto <files...>`, which works out the bank of each statement (and the Cobee language and the Sabadell year) and imports them all in one go.
* Keep a local copy of your budget's transactions and accounts, plus an activity log, so the web app can work without refetching everything from YNAB.
* The YNAB token is kept in the system keychain (macOS Keychain, Windows Credential Manager, Secret Service or KWallet on Linux) instead of the config file; an existing token moves there the next time yul runs, and the file keeps plain text only where no keychain exists.
* Leave a row out of imports for good from the app's import review, and bring it back from there or from Settings › Data & privacy; yul then skips it in every later import of the same statement.
* Settings › Appearance picks one of four palettes, Midnight (default), Twilight, Graphite and Aurora, each with a dark and a light variant.

### Polished Until It Shines
* `yul load auto` shows the transactions of every file first and asks a single confirmation to import them all, then reports how many were created in each account.
* Every open account now counts in net worth by default; Settings › Accounts lets you leave one out.
* Net worth in `yul app` has "Update balances": every balance you keep by hand becomes a field at once, Tab moves from one to the next, each shows how much it changes, and one Save (or Enter) updates them all in YNAB.
* Home is laid out in three blocks: net worth, an Import section with the drop zone and when each bank was last imported, and a Needs you section with only what is waiting for you.
* Settings in `yul app`: Banks and Accounts are grids of cards that light up when switched on, Accounts saves every change at once with the bucket as pills and a pencil for balances entered by hand, and every bank logo has the same size.
* Setup now ends by copying your budget from YNAB while you watch, and no longer asks which accounts to track: every open account counts until you change it in Settings.
* The config moves to V4 (migrated automatically) and gains account settings, balance adjustment settings and debt mappings.
* Reconcile in `yul app` shows each account as YNAB does, cleared balance + uncleared = working balance with how many are left to reconcile, groups its transactions under Cleared, Uncleared and Reconciled, opens them with one "Show transactions" bar before anything can be reconciled, and says reconcile instead of lock.
* `yul load <bank>` without a value for an option (the Cobee language, the Sabadell year) now uses the one saved for that bank in Settings › Banks before reading it from the file.
* `yul setup` asks before replacing an existing config; `--yes` replaces it without asking.
* `yul load <bank> --show` prints the transactions before asking for an account, and `--help` works without a config.
* `yul reconcile` without a date asks YNAB for every transaction of the account, and only the transactions you chose to skip hold the reconciliation date back, in the CLI and in the app.
* A YNAB or network error in any command is reported as one line with exit code 1 instead of a traceback, and every YNAB request has a connect and read timeout instead of hanging.
* The config file and the local data folder are written atomically and readable by you only.

### Bugs Squashed, Peace Restored
* Transactions merged by YNAB's matching no longer linger in the local store as "to reconcile".
* Reconcile in `yul app` checks YNAB every time it opens, and the budget copy drops a transaction YNAB hid after matching it into a reconciled one, so neither shows up as a transaction to reconcile.
* A row YNAB matched with a reconciled transaction you entered by hand is no longer imported again on the next run.
* A Sabadell row dated after today is moved back one year, so a December statement read in January is not dated in the future; `MOVIMIENTOS.XLS` and `Cobee.HTML` are accepted whatever the case of the extension.
* A Sabadell, BBVA or Cobee row that cannot be read stops the import with one line naming the row, instead of a traceback or a silently dropped transaction; BBVA dates typed as date cells are read.
* A payee with brackets no longer crashes `yul load` or `yul reconcile`, and a payee longer than the 200 characters YNAB accepts is cut instead of failing the whole file.
* An unreadable config file is reported as an error pointing at `yul config reset`, its validation errors never print part of the token, and a config migration saves the new file before deleting the old one.

### Read All About It! (Docs Updates)
* Document the local web app: the architecture contract and design document kept with the `yul-web-design` project skill, a Web app section in the README and the local web server in the privacy notice.
* The README is rewritten for 1.0: what yul is, how to install it, and how to use the web app and the command line.

### For the Builders: Dev Experience Upgrades
* Add the net worth, debt netting and balance adjustment core shared by the CLI and the web app.
* Move importing and reconciling into UI independent core services shared by the CLI and the web app.
* `src` is type checked with pyright in strict mode; `hatch run dev:check` fails when lint, format or types fail.
* The PR checks run on Ubuntu and macOS with Python 3.13 and 3.14, on every pull request whatever its base; the release refuses a tag off `main` or with a changelog fragment pending, and runs the checks on the tagged commit.
* Every test gets its own scratch `YUL_HOME`, and a run with `YUL_HOME` set uses a keychain item named after that folder, so a scratch run never touches the real token.

## ynab-unlinked 0.10.0 (2026-10-31)

### Fresh Out of the Feature Oven
* [[#117](https://github.com/AAraKKe/ynab-unlinked/issues/117)] `yul load --yes` imports without asking for confirmation so it can run unattended, and exits with an error instead of prompting when there is no config, the entity has no saved account, or `-a/--acount` is used.

### Polished Until It Shines
* [[#109](https://github.com/AAraKKe/ynab-unlinked/issues/109)] `yul load` now identifies transactions by YNAB's own import id convention (`YNAB:<milliunits>:<date>:<occurrence>`) and lets YNAB do the matching against transactions you entered yourself. The local date, amount and payee matcher, the partial-match prompt and the payee rename rules are gone; two identical purchases on the same day now import as two transactions, transactions already in YNAB are dimmed instead of re-sent, and anything YNAB rejects as a duplicate is reported. The config moves to V3, dropping payee rules and per-entity checkpoints.

### Bugs Squashed, Peace Restored
* [[#108](https://github.com/AAraKKe/ynab-unlinked/issues/108)] Fix a batch of bugs found while raising test coverage: duplicated rows in one export were uploaded with the same import id so YNAB kept only one; amounts were truncated instead of rounded to milliunits; the checkpoint recorded the earliest processed date instead of the latest; `--reconcile` did not apply to new transactions; rejecting a partial match against a reconciled transaction created it as reconciled; very short payees matched unrelated YNAB payees; the resolved YNAB payee was never sent on upload; `yul load -a` crashed for an entity without a config entry; an empty export crashed; BBVA and Cobee could not read amounts over a thousand and BBVA crashed on a blank PDF cell; a Cobee cancellation marker could drop the wrong transaction; an unsupported input file ended in a traceback instead of an error message; the budget list was not shown during setup; a partial match without a payee rendered `None`; amount colours were dropped for symbol-first currencies; reconciling with nothing selected crashed; the reconcile confirmation read "1 transactions".
* [[#111](https://github.com/AAraKKe/ynab-unlinked/issues/111)] Fix Cobee amounts being imported a hundred times too large: the page writes `21.90 €` with a dot as the decimal separator, and the recent thousands-separator fix stripped it. Amounts are now parsed by one function that accepts both `1.234,56` and `1,234.56` for every entity.
* [[#101](https://github.com/AAraKKe/ynab-unlinked/issues/101)] Fix Sabadell parsing of amounts with thousands separators (e.g. `1.212,16EUR`), which previously crashed the `load sabadell` command.

### Under the Hood Upgrades
* [[#110](https://github.com/AAraKKe/ynab-unlinked/issues/110)] Bump platformdirs from 4.11.10 to 4.11.11 in the python-dependencies group
* [[#107](https://github.com/AAraKKe/ynab-unlinked/issues/107)] Bump platformdirs from 4.11.9 to 4.11.10 in the python-dependencies group
* [[#115](https://github.com/AAraKKe/ynab-unlinked/issues/115)] Bump the github-actions group across 1 directory with 3 updates
* [[#100](https://github.com/AAraKKe/ynab-unlinked/issues/100)] Bump the github-actions group across 1 directory with 5 updates
* [[#106](https://github.com/AAraKKe/ynab-unlinked/issues/106)] Bump the github-actions group with 2 updates
* [[#116](https://github.com/AAraKKe/ynab-unlinked/issues/116)] Bump the python-dependencies group across 1 directory with 4 updates
* [[#104](https://github.com/AAraKKe/ynab-unlinked/issues/104)] Bump the python-dependencies group across 1 directory with 7 updates
* Bump ynab from 4.1.0 to 4.4.0

### For the Builders: Dev Experience Upgrades
* [[#103](https://github.com/AAraKKe/ynab-unlinked/issues/103)] Add `AGENTS.md` and `CLAUDE.md` with a project overview and workflow for coding agents.
* [[#105](https://github.com/AAraKKe/ynab-unlinked/issues/105)] Raise test coverage of `src` from 51% to 98% with behaviour tests for matching, the load pipeline, entities, parsers, config, reconcile and the TUI. Strict xfails pin the bugs found on the way. Coverage now reports `src` only.

## ynab-unlinked 0.9.0 (2026-05-01)

### Fresh Out of the Feature Oven
* New `yul privacy` command that prints what data YNAB Unlinked stores on your computer, where it lives, and how to delete it. New `yul config reset` command that wipes all locally stored data, including your YNAB API key. Pass `--yes` to skip the confirmation prompt.

### Polished Until It Shines
* `yul setup` and `yul config set api_key` now show a short notice explaining where your YNAB API key will be stored before asking for it.

### Read All About It! (Docs Updates)
* Added a [privacy notice](https://github.com/AAraKKe/ynab-unlinked/blob/main/PRIVACY.md) describing what data YNAB Unlinked reads from YNAB, what stays on your machine and where, and how to delete it. Added the corresponding "Privacy" and "Disclaimer" sections to the README.

## ynab-unlinked 0.8.0 (2026-05-01)

### Under the Hood Upgrades
* [[#83](https://github.com/AAraKKe/ynab-unlinked/issues/83)] Pin all dependencies to exact versions and adapt the YNAB SDK wrapper to the 4.x `budgets` → `plans` rename
* [[#80](https://github.com/AAraKKe/ynab-unlinked/issues/80)] Update pydantic requirement from >=2.0.0 to >=2.13.3
* [[#82](https://github.com/AAraKKe/ynab-unlinked/issues/82)] Bump textual from 7.5.0 to 8.2.5
* [[#74](https://github.com/AAraKKe/ynab-unlinked/issues/74)] Bump pypa/gh-action-pypi-publish from 1.13.0 to 1.14.0
* [[#76](https://github.com/AAraKKe/ynab-unlinked/issues/76)] Bump softprops/action-gh-release from 2.5.0 to 3.0.0

### For the Builders: Dev Experience Upgrades
* [[#85](https://github.com/AAraKKe/ynab-unlinked/issues/85)] Ignore `.coverage` and `.vscode/` in `git status` and skip towncrier check for `.gitignore`-only changes

## ynab-unlinked 0.7.0 (2026-02-14)
_Note_: This release was published from a commit that was never merged back into `main`. The entry below mirrors what actually shipped to PyPI.

### Bugs Squashed, Peace Restored
* [[#10](https://github.com/AAraKKe/ynab-unlinked/issues/10)] Fix matching algorithm to properly consider imported IDs

### Under the Hood Upgrades
* [[#61](https://github.com/AAraKKe/ynab-unlinked/issues/61)] Bump platformdirs from 4.5.1 to 4.7.0
* [[#59](https://github.com/AAraKKe/ynab-unlinked/issues/59)] Bump textual from 7.3.0 to 7.5.0

## ynab-unlinked 0.6.1 (2026-01-25)
_Note_: Version 0.6.0 was skipped due to a mistake in the release process.

### Polished Until It Shines
* Improve how Sabadell handles year changes. Now it automatically detects mixed-years transactions and update the year accordingly

### Under the Hood Upgrades
* [[#56](https://github.com/AAraKKe/ynab-unlinked/issues/56)] Bump actions/checkout from 6.0.1 to 6.0.2
* [[#55](https://github.com/AAraKKe/ynab-unlinked/issues/55)] Bump actions/setup-python from 6.1.0 to 6.2.0
* [[#54](https://github.com/AAraKKe/ynab-unlinked/issues/54)] Bump textual from 6.11.0 to 7.3.0

## ynab-unlinked 0.5.2 (2026-01-25)

### Bugs Squashed, Peace Restored
* [[#57](https://github.com/AAraKKe/ynab-unlinked/issues/57)] Fix sabadell issue that was preventing it from loading refunds from credit card balance

## ynab-unlinked 0.5.1 (2026-01-01)

### Bugs Squashed, Peace Restored
* Fix missing argument when creating SabadellParser breaking Sabdell load command

## ynab-unlinked 0.5.0 (2026-01-01)

### Fresh Out of the Feature Oven
* Add a `--year` option to the Sabdell entity. Sabadell does not include the year in the transaction history. By default, the current year is used but if the year of the transaction is not the current year, this option allows you to specify it.

### Under the Hood Upgrades
* [[#45](https://github.com/AAraKKe/ynab-unlinked/issues/45)] Bump actions/checkout from 5.0.0 to 6.0.1
* [[#47](https://github.com/AAraKKe/ynab-unlinked/issues/47)] Bump pyexcel from 0.7.3 to 0.7.4
* [[#46](https://github.com/AAraKKe/ynab-unlinked/issues/46)] Bump stefanzweifel/git-auto-commit-action from 6.0.1 to 7.1.0
* [[#48](https://github.com/AAraKKe/ynab-unlinked/issues/48)] Bump textual from 5.3.0 to 6.11.0

## ynab-unlinked 0.4.0 (2025-12-20)

### Fresh Out of the Feature Oven
* Add a button to reconcile to select/unselect all accounts

### Bugs Squashed, Peace Restored
* Fix reconcile command quit action. Now when quiting recondile no transactions will be reconciled
* Fix the Reconcile.action_quit method making it async
* Remove unnecessary print as a left over from previous change

### Under the Hood Upgrades
* [[#28](https://github.com/AAraKKe/ynab-unlinked/issues/28)] Bump actions/checkout from 4.2.2 to 5.0.0
* [[#33](https://github.com/AAraKKe/ynab-unlinked/issues/33)] Bump actions/setup-python from 5.6.0 to 6.0.0
* [[#40](https://github.com/AAraKKe/ynab-unlinked/issues/40)] Bump platformdirs from 4.3.8 to 4.5.0
* [[#34](https://github.com/AAraKKe/ynab-unlinked/issues/34)] Bump pypa/gh-action-pypi-publish from 1.12.4 to 1.13.0
* [[#42](https://github.com/AAraKKe/ynab-unlinked/issues/42)] Bump softprops/action-gh-release from 2.3.2 to 2.4.1
* [[#29](https://github.com/AAraKKe/ynab-unlinked/issues/29)] Bump stefanzweifel/git-auto-commit-action from 5.2.0 to 6.0.1
* [[#26](https://github.com/AAraKKe/ynab-unlinked/issues/26)] Bump textual from 5.0.0 to 5.3.0

### For the Builders: Dev Experience Upgrades
* Upate towncrier configuration to ignore updates on the .github directory

## ynab-unlinked 0.3.0 (2025-08-10)

### Bugs Squashed, Peace Restored
* Fix XLS files in Sabadell when pending transactions where present. Sabadell can also now identify file type automatically.

## ynab-unlinked 0.2.1 (2025-08-10)

### Bugs Squashed, Peace Restored
* Fix an issue by which Sabadell entity was not properly ignoring pending transactions in txt format
* Fix issue with Cobee entity causing transactions with 0 euros showing as transactions to import

## ynab-unlinked 0.2.0 (2025-07-26)

### Polished Until It Shines
* Improved how the reconcile command works. Now it launches a Textual app to more easily review all transactions to reconcile.

## ynab-unlinked 0.1.0 (2025-07-15)

### Fresh Out of the Feature Oven
* [[#14](https://github.com/AAraKKe/ynab-unlinked/issues/14)] Add option to the load command that prompts to select an account to import to
* [[#18](https://github.com/AAraKKe/ynab-unlinked/issues/18)] Add support for XLS parsing to Sabadell entity
* Add support for XLSX files to BBVA improving how to handle multiple files types
* [[#1](https://github.com/AAraKKe/ynab-unlinked/issues/1)] Yul Config can now be versioned and migrated from older to newer versions.

### Polished Until It Shines
* Bring match days threshold to the same value as YNAB has it
* [[#9](https://github.com/AAraKKe/ynab-unlinked/issues/9)] Improve amount formatting based on the settings in the used YNAB budget
* [[#1](https://github.com/AAraKKe/ynab-unlinked/issues/1)] Improve display handling by centralizing styles in the display module and moving complex display logic to utils
* Instead of avoid loading transactions from the last time the tool was run, we are now tryingto match transactions with YNAB transactions that are a number of days prior to the earliest transaction in the import file. This is configurable through the `--buffer` option in the load command.
* Make the menu to select accounts to reconcile interactive. This type of menu will be used whenever the user needs to selet an option

### Bugs Squashed, Peace Restored
* [[#11](https://github.com/AAraKKe/ynab-unlinked/issues/11)] Fix in Cobee entity that prevents it from importing accumulations lines
* [[#20](https://github.com/AAraKKe/ynab-unlinked/issues/20)] Sabadell import ignores cash withdrawals. These appear in the linked bank acccount

## ynab-unlinked 0.0.3 (2025-05-18)

### Fresh Out of the Feature Oven
* Add new reconcile command. Run `yul reconcile` and reconcile all your accounts in one go.

### Bugs Squashed, Peace Restored
* Fix reconcile command that would break when selecting all accounts

### For the Builders: Dev Experience Upgrades
* [[#4](https://github.com/AAraKKe/ynab-unlinked/issues/4)] Add towncrier support. This includes configuration, hatch environment and scripts.
* [[#5](https://github.com/AAraKKe/ynab-unlinked/issues/5)] Add GitHub workflow to validate PRs. This includes: format checkts, linter, type checker and towncrier validation
