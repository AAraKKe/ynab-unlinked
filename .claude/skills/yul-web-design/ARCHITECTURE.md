# yul app: build architecture

This is the contract every implementation task codes against: it fixes names, signatures and boundaries so that parallel work merges cleanly.
When a task needs to deviate, it updates this file in the same change.

Decisions taken (2026-11-03):

- Frontend: **NiceGUI 3.19** (pure Python, FastAPI underneath). No Node toolchain.
- Optional extra: `pip install ynab-unlinked[web]`. Without it `yul app` is hidden from
  `--help` and, if invoked, prints how to install the extra and exits 1.
- Browser tab first. Native window is out of scope.
- Command name: `yul app`.
- Config V4 keeps `last_reconciliation_date` (the CLI `yul reconcile` still uses it). The web
  reconcile view reads from the local store instead. Removing the field is a later change.
- The token lives in the system keychain when there is one (`ynab_unlinked.keychain`);
  the file then holds `@keychain`.

## 1. Package layout

```
src/ynab_unlinked/
  core/                  pure services. May import: config, entities, models, ynab_api,
                         store, parsers. MUST NOT import: typer, rich, textual, nicegui,
                         ynab_unlinked.cli (the terminal: display, prompts, tables).
    __init__.py
    progress.py          Progress protocol (see 2.1)
    importing.py         build_import_plan / commit_import_plan (2.2)
    reconcile.py         reconciliation_overview / reconcile (2.3)
    detect.py            detect_loaders (2.4)
    balances.py          net worth, debt netting, adjustments (2.5)
    history.py           balance and net worth series from the store (2.7)
  entities/              parsers, now with sniff() and a LoaderSpec per package (2.4)
  config/                V1..V4, migrations (2.6)
  store/                 SQLite transaction store and sync (2.7)
  cli/                   the terminal only: the Typer `app`, display, prompts, tables,
                         process.py (the `yul load <bank>` pipeline), setup.py
    commands/            CLI. Thin: parse args, call core, print.
  web/                   NiceGUI app, only importable when the `web` extra is installed (3)
  ynab_api/client.py     the only place that talks to the SDK; every request has
                         REQUEST_TIMEOUT (10 s to connect, 60 s per read) unless it names one
  ynab_api/errors.py     YNAB_ERRORS, api_status, timed_out(error) and classify(error) ->
                         Classified(Failure: STATUS | TIMED_OUT | UNREACHABLE | OTHER, status,
                         reason): the one classifier, worded by cli_errors and web.wording
```

Rules:

- `core/` functions take a `Client` and plain values, never a typer context. They raise
  exceptions; the caller decides how to show them.
- Everything user facing in `core/` is typed and covered by tests under `tests/core/`.
- Versioned config classes (`ConfigV3`, `ConfigV4`) must not be referenced outside `config/`. Code uses
  `from ynab_unlinked.config import LatestConfig` (a type alias to the newest version).
  `LatestConfig = ConfigV4`. Read loader accounts through `config.entity(name)`, not a field.
- Every change adds a towncrier fragment `changelog/+<slug>.<type>.md`.
- `hatch run dev:check` (ruff, format, pyright) and `hatch run dev:cov` must pass before a
  task is done. Pyright is strict about `src`; keep it green.
- No commit trailers of any kind.

## 2. Core contracts

### 2.1 Progress (`core/progress.py`)

```python
class Progress(Protocol):
    def start(self, message: str) -> None: ...
    def done(self, message: str | None = None) -> None: ...
    def info(self, message: str) -> None: ...
    def warn(self, message: str) -> None: ...

class NullProgress:  # does nothing

NO_PROGRESS: Final = NullProgress()   # the one shared default
```

Long running core calls accept `progress: Progress = NO_PROGRESS` (written `NullProgress()`
in the signatures below). Modules import the shared singleton instead of keeping their own
copy: ruff B008 rejects a call in a default. The CLI passes an
implementation built on `display.process`; the web passes one that updates the page.

### 2.2 Importing (`core/importing.py`)

```python
@dataclass(frozen=True)
class ImportRow:
    transaction: Transaction
    import_id: str
    already_imported: bool

@dataclass(frozen=True)
class ImportPlan:
    entity_name: str
    account_id: str
    input_file: Path
    rows: tuple[ImportRow, ...]

    @property
    def new_rows(self) -> tuple[ImportRow, ...]: ...
    @property
    def already_imported_count(self) -> int: ...

@dataclass(frozen=True)
class ImportResult:
    created: int
    duplicate_import_ids: tuple[str, ...]

def parse_transactions(entity: Entity, input_file: Path) -> list[Transaction]
    # wraps entity.parse, lets ParsingError propagate

IMPORT_BUFFER_DAYS = 15     # also the `yul load --buffer` default and YnabUnlinkedContext's

def build_import_plan(
    client: Client, budget_id: str, account_id: str, entity_name: str,
    input_file: Path, transactions: list[Transaction], buffer_days: int = IMPORT_BUFFER_DAYS,
    progress: Progress = NullProgress(),
) -> ImportPlan
    # assigns import ids (models.assign_import_ids), fetches YNAB transactions for the
    # account since min(date) - buffer, marks already_imported by import_id or legacy id.
    # An empty `transactions` returns a plan with no rows without calling YNAB.

def file_digest(input_file: Path) -> str            # SHA-256 of the bytes
def unique_files(files: Sequence[Path]) -> tuple[list[Path], list[tuple[Path, Path]]]
    # each export once, plus (copy, first) for the byte identical ones left out.
    # Import ids are numbered per file (YNAB's own scheme), so an export that overlaps an
    # imported one gives its shared rows the same ids and YNAB rejects them; a second copy
    # in one batch would only be rejected once the first is in, so both frontends drop it.

def commit_import_plan(
    client: Client, budget_id: str, plan: ImportPlan, cleared: TransactionClearedStatus,
    progress: Progress = NullProgress(),
) -> ImportResult
    # creates plan.new_rows, returns created count and the duplicates YNAB rejected.
    # A plan with no new rows returns ImportResult(0, ()) without calling YNAB.
```

The `NullProgress()` defaults are `core.progress.NO_PROGRESS` in the code. The CLI passes `cli.display.CliProgress`, a context manager that shows a
spinner per step and stops it if the core call raises. `cli.utils.display_import_table` takes
`Sequence[ImportRow]`.

### 2.3 Reconcile (`core/reconcile.py`)

```python
@dataclass(frozen=True)
class AccountToReconcile:
    account: Account
    transactions: tuple[TransactionDetail, ...]   # not reconciled, newest first

def reconciliation_overview(
    client: Client, budget_id: str, since: dt.date | None,
    progress: Progress = NullProgress(),
) -> list[AccountToReconcile]
    # every non reconciled, non deleted transaction since `since` (None = all), grouped by
    # account in the order YNAB lists accounts, accounts without transactions omitted,
    # closed accounts omitted

class ReconcileRow(Protocol):        # what reconcile needs of a transaction
    id: str                          # (read only properties)
    date: dt.date

@dataclass(frozen=True)
class RowToLock:                     # a plain ReconcileRow; RowToLock.of(TransactionDetail)
    id: str
    date: dt.date

def reconcile(
    client: Client, budget_id: str, rows: Sequence[ReconcileRow],
    progress: Progress = NullProgress(),
) -> dt.date | None
    # Client.update_transactions(budget_id, ids, RECONCILED) sends only {id, cleared}: an
    # account id read earlier could be stale and move the transaction back. Returns the
    # latest row date or None if empty (YNAB is not called then)

def next_reconciliation_date(locked: Iterable[dt.date],
                             remaining: Iterable[dt.date] = ()) -> dt.date | None
    # None when nothing was locked; the earliest date left unreconciled in scope when
    # anything was, else the latest locked date. No buffer: the scope rewinds once from it
    # (`yul reconcile --buffer` and the app's "since" pill, both RECONCILE_BUFFER_DAYS)

RECONCILE_BUFFER_DAYS = 7
```

`cli/commands/reconcile.py` and the Textual app keep working on top of these. The two
frontends read from different places on purpose: `yul reconcile` asks YNAB live
(`reconciliation_overview`), the app reads the budget copy (`Store.unreconciled`, synced
first when older than 10 minutes or after a write). Both use the same scope rule and
`reconcile()`, so they differ only by what YNAB changed since the last sync.

### 2.4 Loaders and detection (`entities/`, `core/detect.py`)

Every entity package (`entities/bbva`, `entities/sabadell`, `entities/cobee`) exposes a
module level `spec: LoaderSpec` and nothing else: `cli/commands/load.py` generates
`yul load <key>` from it (`bank_command(spec)`: the input file plus one option per
`LoaderOption`, `cli_flags` and `help`; a choice option lists its non auto choices, an
`integer` one takes a whole number), resolves the values with `options_for_file` and
calls `process_transactions(spec.build(options), ...)`. Parsers get no CLI context.

```python
# entities/_protocol.py
class Match(NamedTuple):
    confidence: float   # 0.0 (no) .. 1.0 (certain)
    reason: str         # short, user facing: "BBVA header row found"

class Entity(Protocol):
    def name(self) -> str: ...
    def parse(self, input_file: Path) -> list[Transaction]: ...
        # options are bound by build; a row it cannot read raises ParsingError("line n: ...")
    def sniff(self, input_file: Path) -> Match: ...
        # cheap, reads at most the first page / first rows / first KB, never raises

# entities/registry.py
@dataclass(frozen=True)
class LoaderOption:
    key: str                        # "year", "language"
    label: str                      # "Year of the statement"
    default: str                    # "auto" allowed where the loader can infer it
    choices: tuple[str, ...] | None = None
    flags: tuple[str, ...] = ()     # on `yul load <key>`: ("-y", "--year"); empty: --<key>
    help: str = ""                  # its command line help, else the label
    integer: bool = False           # the command line takes a whole number

    @property
    def cli_flags(self) -> tuple[str, ...]: ...

@dataclass(frozen=True)
class LoaderSpec:
    key: str                        # package name: "bbva", "sabadell", "cobee"
    name: str                       # Entity.name(): "BBVA Credit Card", "sabadell", "cobee"
    title: str                      # user facing: "BBVA Credit Card", "Sabadell", "Cobee"
    input_types: tuple[InputType, ...]
    options: tuple[LoaderOption, ...]
    build: Callable[[Mapping[str, str]], Entity]          # options -> entity, all bound
    help: str = ""                                        # help of `yul load <key>`

    def accepts(self, input_file: Path) -> bool           # lower cased suffix in input_types,
                                                          # same rule as _sniff.extract_type

AUTO = "auto"
def concrete(options: Mapping[str, str], key: str) -> str   # ValueError on missing or "auto"
def loaders() -> list[LoaderSpec]        # discovered from entity packages, sorted by key
def loader(key: str) -> LoaderSpec       # KeyError if unknown
```

`build` takes concrete values only: they raise `ValueError` on a missing,
`"auto"` or invalid value. Resolving `auto` is `core.detect.resolve_options`.

Markers:

| key | type | sniff | confidence |
|---|---|---|---|
| bbva | xlsx | a row equal to `["", "Fecha", "Tarjeta", "Concepto", "Importe", "Divisa", ""]` in the first 30 rows | 0.95 |
| bbva | pdf | first page has a table where every row has 3 columns and a row has a `dd/mm/yyyy` in column 0 and an amount in column 2 | 0.8 |
| sabadell | txt | first 64 KB decode as cp1252 and contain `Límite de crédito` and a line matching `TRANSACTION_PATTERN` | 0.95 (credit limit line alone: 0.3) |
| sabadell | xls | in the first 30 rows, a row starting `FECHA, CONCEPTO, LOCALIDAD` / else one containing `MOVIMIENTOS DE DEBITO` | 0.9 / 0.6 |
| cobee | html | the text extracted from the first 2 MiB contains one of `Transacciones`, `Transactions`, `Transações` and a `€` amount; the word found first sets `language` | 0.9 (heading alone: 0.3) |

BBVA does not list xls: its parser rejects that suffix. Cobee reads 2 MiB instead of 64 KB
because a saved page inlines the app styles and scripts before the transaction list. A sniff
reports what it inferred as `key=value` in its reason (Cobee: `(language=es)`);
`resolve_options` fills `auto` options from those hints.

Sabadell `year` option default `"auto"` = current year with the existing December/January
heuristic. Cobee `language` default `"auto"` = the one found by sniff, else `es`.

```python
# core/detect.py
@dataclass(frozen=True)
class Candidate:
    loader: LoaderSpec
    confidence: float
    reason: str
    options: Mapping[str, str]          # resolved options (auto values filled in)
    transactions: tuple[Transaction, ...] | None   # None when the trial parse failed
    error: str | None

@dataclass(frozen=True)
class Detection:
    input_file: Path
    candidates: tuple[Candidate, ...]   # best first

    @property
    def best(self) -> Candidate | None: ...      # single candidate with transactions, or
                                                 # the top one when it is clearly ahead
    @property
    def ambiguous(self) -> bool: ...

MIN_CONFIDENCE = 0.5
CLEAR_LEAD = 0.25

def detect_loaders(files: Sequence[Path], config: LatestConfig) -> list[Detection]
    # for each file: loaders whose input_types accept the suffix -> sniff -> keep
    # confidence >= MIN_CONFIDENCE -> trial parse with resolved options (the bank's saved
    # options from config on top, `preferred_options`) -> rank by (parsed ok, confidence,
    # transaction count)

def preferred_options(options: Mapping[str, str], saved: LoaderConfig | None) -> dict[str, str]
    # options with the saved non auto values of the bank on top
def saved_options(spec: LoaderSpec, config: LatestConfig) -> dict[str, str]
    # the bank's saved non auto options
def options_for_file(
    spec: LoaderSpec, input_file: Path, given: Mapping[str, str], config: LatestConfig
) -> dict[str, str]
    # what `yul load <key>` reads the file with: the command line value, else the saved
    # one, else `resolve_options` from the file's sniff, so both frontends date and number
    # a file the same way

def resolve_options(spec: LoaderSpec, reason: str = "") -> dict[str, str]
    # every option of spec with a concrete value: a non auto default as is, auto from a
    # `key=value` hint in the sniff reason, else the current year for `year`, else the
    # first concrete choice (cobee: "es")
```

`best` is the only candidate whose trial parse succeeded, or the top one when its
confidence beats the runner up by at least `CLEAR_LEAD`; otherwise `None`. `ambiguous` is
true when more than one candidate parsed and none is clearly ahead. A file with no
candidates (unsupported suffix, or nothing sniffed above the threshold) and a file whose
candidates all failed to parse have `best is None` and `ambiguous is False`.

### 2.5 Balances and net worth (`core/balances.py`)

```python
class Bucket(StrEnum):   # lives in ynab_unlinked/buckets.py, import it from there
    CASH = "cash"; SAVINGS = "savings"; ASSETS = "assets"; DEBT = "debt"

def bucket_for(account_type: AccountType) -> Bucket     # default bucket of a YNAB type

@dataclass(frozen=True)
class AccountBalance:
    id: str; name: str; bucket: Bucket; balance: int    # milliunits

@dataclass(frozen=True)
class DebtNetting:
    debt_account_id: str
    mapped_to: tuple[str, ...]

@dataclass(frozen=True)
class NetWorth:
    accounts: tuple[AccountBalance, ...]    # after netting; debt accounts keep their raw balance
    total: int                              # cash + savings + assets after netting + unnetted
    unnetted: int = 0                       # debt netted against no counted account
    def by_bucket(self) -> dict[Bucket, int]
    def share(self, account_id: str) -> float   # balance / total, 0 for debt

def net_worth(accounts: Sequence[AccountBalance], nettings: Sequence[DebtNetting]) -> NetWorth
    # each debt balance is split evenly over mapped_to, remainder on the first; a debt with
    # no mapping (or the share mapped to an account not counted) is not netted against any
    # account but still comes off the total, as `unnetted`: every debt counts exactly once

@dataclass(frozen=True)
class Adjustment:
    account_id: str; old_balance: int; new_balance: int
    @property
    def amount(self) -> int

def build_adjustments(current: Mapping[str, int], wanted: Mapping[str, int]) -> list[Adjustment]
def create_adjustments(
    client: Client, budget_id: str, adjustments: Sequence[Adjustment],
    memo: str, payee: str, cleared: TransactionClearedStatus, date: dt.date,
) -> int   # number created
```

`ynab_api.Client` gains `account(budget_id, account_id) -> Account` and
`create_adjustments(...)` (approved=True, no import id). `parse_amount_to_milliunits` reads
what the user types as a balance and lives in `core/balances.py` too.

### 2.6 Config V4 (`config/`)

```python
class LoaderConfig(BaseModel):
    account_id: str
    options: dict[str, str] = {}
    enabled: bool = True        # off: `load auto` and the app skip the bank, settings kept

class TrackedAccount(BaseModel):
    id: str
    name: str
    type: str                     # YNAB AccountType value, refreshed from the API
    bucket: Bucket                # default from bucket_for, user can override
    track_balance: bool = False   # "by hand": the balance is entered in the net worth view
    counted: bool = True          # off leaves the account out of net worth

# `accounts` holds settings, not a selection: every open account counts with its defaults
# (`web.accounts.default_account`) unless an entry says otherwise. Configs written before
# `counted` existed load with every entry counted.

class DebtMapping(BaseModel):
    debt_account_id: str
    mapped_to: list[str] = []

class ClearedStatus(StrEnum): CLEARED, UNCLEARED, RECONCILED   # serialised lowercase

class Adjustments(BaseModel):
    memo: str = "Balance adjustment by yul"
    payee: str = "Balance Adjustment"
    cleared: ClearedStatus = ClearedStatus.CLEARED

class ConfigV4(BaseModel):
    api_key: str
    budget: Budget
    last_reconciliation_date: dt.date | None = None
    loaders: dict[str, LoaderConfig] = {}       # keyed by Entity.name(), was `entities`
    accounts: list[TrackedAccount] = []
    adjustments: Adjustments = Adjustments()
    debt_mappings: list[DebtMapping] = []
    version_number: str = Field(default="V4", alias="version")

    # Config protocol
    version / path / save / load / exists
    def entity(self, name) -> LoaderConfig | None          # kept so callers do not change
    def set_entity_account(self, name, account_id)
    # new
    def account(self, id) -> TrackedAccount | None
    def debt_mapping(self, debt_account_id) -> DebtMapping | None
```

```python
# config/core.py, exported from ynab_unlinked.config
@contextmanager
def edit_config(fallback: LatestConfig | None = None) -> Generator[LatestConfig]
def update_config(change: Callable[[LatestConfig], None], fallback=None) -> LatestConfig
def switch_budget(config: LatestConfig, budget: Budget) -> None
```

- Every config save, in the CLI and in the app, goes through `edit_config` / `update_config`:
  the file is read again, the change applied and the result saved under a process wide lock
  and an advisory lock on `config.json.lock` (`config.lock`), so each writer only changes
  what it touches. Do not nest it. Only `yul setup` writes a whole new config.

### 2.7 Store (`store/`) and history (`core/history.py`)

```python
# store/paths.py
def store_path() -> Path   # config.paths.data_dir() / "store.sqlite": $YUL_HOME when set,
                           # else user_data_dir("ynab-unlinked", "committhatline")

# store/store.py
@dataclass(frozen=True)
class StoredTransaction:
    id: str; account_id: str; date: dt.date; amount: int; cleared: TransactionClearedStatus
    approved: bool; deleted: bool; payee_name: str | None; category_name: str | None
    import_id: str | None; memo: str | None; transfer_account_id: str | None

@dataclass(frozen=True)
class StoredAccount:
    id: str; name: str; type: str; closed: bool; on_budget: bool
    balance: int; cleared_balance: int; uncleared_balance: int

@dataclass(frozen=True)
class SyncResult:
    full: bool; transactions_changed: int; accounts: int; server_knowledge: int
    ghosts_removed: int = 0                     # rows flagged deleted by the ghost repair

@dataclass(frozen=True)
class Activity:
    at: dt.datetime; kind: str; message: str; details: dict[str, Any]

class StoreError(Exception)                       # store written by a newer schema

class Store:
    def __init__(self, path: Path): ...          # creates dir and schema if missing, migrates
                                                 # (again on use when the file was deleted)
        # the dir is 0700 and the file 0600 (existing ones are narrowed to these modes)
    def sync(self, client: Client, budget_id: str, progress: Progress = NullProgress()) -> SyncResult
        # no knowledge stored for this budget -> full fetch
        # (client.transactions_with_knowledge with since_date=FULL_SYNC_SINCE, 1900-01-01,
        # because YNAB defaults a missing since_date to one year ago); else
        # client.transactions_delta(budget_id, knowledge). Upserts rows, keeps deleted rows
        # flagged, replaces the budget's accounts (closed kept, deleted skipped), stores the
        # new server_knowledge (never a lower one than stored), all in one SQLite transaction.
        # A 409 on a delta forgets the budget's rows and knowledge and redoes a full fetch once.
        # Then runs the ghost repair (below) and reports it in ghosts_removed.
    def accounts(self, budget_id: str) -> list[StoredAccount]        # sorted by name
    def transactions(self, budget_id: str, *, account_id: str | None = None,
                     since: dt.date | None = None, until: dt.date | None = None,
                     cleared: Iterable[TransactionClearedStatus] | None = None) -> list[StoredTransaction]
        # never returns deleted rows; since/until inclusive; oldest first (date, id)
    def unreconciled(self, budget_id: str) -> list[StoredTransaction]   # cleared + uncleared
    def last_sync(self, budget_id: str) -> dt.datetime | None           # aware, UTC; when the
        # sync started fetching, so a write logged during the fetch counts as newer
    def clear(self, budget_id: str | None = None, *, activity: bool = False) -> None
        # forgets the copy (rows, accounts, knowledge); the activity log only with activity=True
    def log(self, budget_id: str, kind: str, message: str,
            details: Mapping[str, Any] | None = None, *, at: dt.datetime | None = None) -> None
        # kinds and their details: section 3.4. `at` (aware) backdates an entry, default now
    def activity(self, budget_id: str, limit: int | None = 20, *,
                 kind: str | None = None) -> list[Activity]
        # newest first; limit None = all; kind keeps one kind only
    def last_activity(self, budget_id: str, *, other_than: str | None = None) -> dt.datetime | None
    def last_import_per_loader(self, budget_id: str) -> dict[str, dt.datetime]
        # newest `import` entry per `details.loader`, one GROUP BY query (Home's last imports)
        # when the newest entry was logged, leaving out one kind (`fresh` leaves out "sync")
    def daily_amounts(self, budget_id: str,
                      account_ids: Iterable[str] | None = None) -> dict[str, DailyAmounts]
        # per account: its stored balance and the sum of its non deleted transactions per
        # day, in one query (GROUP BY account, date UNION the accounts). Feeds core.history.

@dataclass(frozen=True)
class DailyAmounts:
    balance: int | None                       # StoredAccount.balance, None if not stored
    days: tuple[tuple[dt.date, int], ...]     # (date, sum of that day), oldest first
```

`Store` opens a connection per call, so one instance is shared across threads
(`run.io_bound`) and the CLI and the app can use the file at once. `Store.sync` does not log
activity; the caller decides what is worth an entry. The schema steps are
`store/migrations/NNNN_*.sql`, one file each, applied in order (`store.migrations.MIGRATIONS`).

`ynab_api.Client` gains `transactions_delta(budget_id, server_knowledge) -> tuple[list[TransactionDetail], int]`
and `transactions_with_knowledge(budget_id, since_date=None) -> tuple[list[TransactionDetail], int]`,
and `transaction_exists(budget_id, transaction_id) -> bool` (False on a 404, other errors raise).

```python
# core/history.py
@dataclass(frozen=True)
class Point: date: dt.date; value: int

def balance_series(store: Store, budget_id: str, account_id: str,
                   start: dt.date, end: dt.date) -> list[Point]
    # running sum of non deleted transactions up to each day; one point per day, the
    # value on `end` equals the account balance in the store

def net_worth_series(store: Store, budget_id: str, accounts: Sequence[TrackedAccount],
                     nettings: Sequence[DebtNetting], start: dt.date, end: dt.date,
                     ) -> dict[str, list[Point]]
    # keys: "total", every Bucket value, every account id. Debt netting applied per day
    # through core.balances.net_worth. Points weekly when end - start > 366 days.

def sample_dates(start: dt.date, end: dt.date) -> list[dt.date]
    # every day, or every Monday in the range plus `end` when end - start > 366 days
```

## 3. Web app (`web/`, extra `web`)

```
web/
  __init__.py          nothing heavy: available() (find_spec, never imports NiceGUI),
                       storage_dir() (user data dir / "web": browser prefs and their secret)
  app.py               build(token, port) -> root page (guard, static files, CSS, views, /onboarding);
                       run(port: int | None, open_browser: bool, announce=None)
  state.py             AppState / state(): config, client, store, formatter, loaders, last_sync
  accounts.py          effective_accounts() / by_hand_accounts() / effective_nettings():
                       what Home, Net worth and Settings count (3.4.1); STALE_AFTER_DAYS
  buckets.py           STYLES (BucketStyle: title, group_title, series slot, colour per bucket),
                       NET_WORTH_ORDER, SETTINGS_ORDER, SERIES_BUCKETS
  wording.py           pure (no NiceGUI): plural (re-exported from ynab_unlinked.text),
                       short_date, human_size, budget_caption,
                       ynab_error_message on classify (a timeout reads YNAB_TIMED_OUT, also
                       the sync chip's error; only YNAB_ERRORS blame YNAB, anything else is
                       UNEXPECTED), copy_error_message, copy_line, COPY_*, IMPORT_FAILED
  ynab.py              fetch_budgets(token), load_budget(client, id) -> Budget,
                       stored_accounts(sdk accounts), fallback_accounts(config)
  paths.py             every page's path (HOME_PATH, IMPORT_PATH, RECONCILE_PATH, NETWORTH_PATH,
                       SETTINGS_PATH, ONBOARDING_PATH), NiceGUI-free for the data modules
  shell.py             layout, view registry, top bar, toasts, confirm dialog, drop overlay,
                       save_config(); re-exports the paths (views use shell.<NAME>_PATH)
                       and sync_label / sync_message
  sync_chip.py         sync_chip(notify, refresh_view): the top bar's sync chip, sync_label,
                       sync_message
  theme.py             palette constants, dark/light switch, install() of static/yul.css
  security.py          per run token, TokenGuard middleware, free_port(), entry_url()
  static/              yul.css: the only stylesheet (tokens, base, shared classes, one section
                       per view, motion, then every media query), fonts/InterVariable.woff2.
                       No CSS lives in Python.
  components/          button, glass_card, pill, bank_logo, stat_tile, segmented_bar, share_bar,
                       empty_state, spinner, check, icon (+ ICONS), count_up (the one count up
                       animation: Home and Net worth heroes); the helpers every view reuses:
                       set_class(el, name, on), clickable(el, handler, role="button") (role,
                       tabindex, click and Enter), loading(text) / show_state(box, kind, text)
                       (loading, error, ok lines), section_title(text, swatch=None),
                       card_switch(card, on, marker, title, on_change, aria_label=None) (the
                       live/off flip and the ui.switch of rule 3, marker on the switch; disabled
                       until `on_change` returns, so a save in flight cannot be raced),
                       dialog_box(title=None, lede=None, classes="") -> DialogBox(dialog, card,
                       body, actions) and run_dialog(dialog) (open, await, delete),
                       budget_tiles(budgets, selected, on_pick) -> (grid, tiles by id)
    dropzone.py        dropzone(on_files, *, compact=False, accept=None): Home and Import step 1
    controls.py        pill_group(options, value, on_change, marker=None) (yul-pills: Reconcile's
                       scope, Net worth's ranges), switch(label, value, on_change) (yul-rec-switch:
                       Reconcile's "include uncleared")
    history_chart.py   ChartSeries, history_options() / history_chart() / set_options(),
                       money_js(): the ECharts history line chart
  views/
    __init__.py        register(): imports every view module
    onboarding/        /onboarding, outside the shell (token, budget, banks, done)
      data.py          STEPS, TOKEN..DONE, CopyState, AccountOption
      progress.py      LineProgress: the copy's progress on one label, from any thread
      view.py          Wizard and page()
    Every view with data to shape is a package: data.py is pure (no NiceGUI, not even
    through its imports: web.accounts, web.buckets, web.paths, web.wording are NiceGUI-free)
    and unit testable; the other modules draw; __init__ holds the docstring only.
    home/              /            hero, import (drop zone, last imports), needs you, activity (3.4.2)
      data.py          LoaderDue, HomeData, load_home, last_set_by_hand, relative_time, last_imports_line,
                       message_markup, Attention, attention_items
      view.py          the page (hero with count_up, spark_options, activity, banner)
    import_/           /import      Files -> Review -> Done on core.detect and core.importing
      data.py          Status, ImportFile, same_file, mark_repeated, take_candidate,
                       account_label, problem_text, option_choices, parse_file, read_file,
                       chosen_accounts, done_summary, import_log
      view.py          ImportFlow (lifecycle, detection, steps Files and Review) and the view
      commit.py        commit(flow): step Done, commit_files, save_accounts, log
      rows.py          draw_row(flow, item): a file row of step Files and its body
      tables.py        badge, plan_table, transactions_table
      cards.py         files_footer, review_footer, review_card, progress_card -> Progress, done_card
    reconcile/         /reconcile   per account cleared vs bank balance, lock
      data.py          scope_start, gap_candidates, ReconcileData (read,
                       open_transactions, has_anything), LOCK_TIMED_OUT, parse_bank_balance, lock_confirmation,
                       lock_log, lock_checkpoint, pending_title
      groups.py        Row, AccountGroup: the selection and the elements that show it
      view.py          ReconcileView and the view
      lock.py          lock(view, groups): confirm, reconcile, log, checkpoint (3.5)
      footer.py        selection / done / locking footers
    networth/          /networth    history chart, buckets, accounts, balance updates, drawer
      data.py          RANGES, MAX_PICKED, range_start, last_set, by_hand_pill, assign_slots,
                       Snapshot, load_snapshot, table_order, default_picked, parse_balance,
                       set_balance (the one write: live balance, build and create the adjustment)
      view.py          NetWorthView (hero, ranges, chips, buckets, drawer loading) and the view
      table.py         AccountsTable: the accounts card and its inline balance editor
      drawer.py        account_drawer(...) -> its chart
    settings/          /settings    one module per tab, each with render(page: Settings):
      __init__.py      Settings (tab row, panel, rerender()), TABS, RENDERERS, tab_from_slug, the view
      common.py        current_config(), kv(key), open_accounts() (open budget accounts, the
                       configured ones when YNAB cannot be reached)
      connection.py    token (reveal, check and save), budget dialog and switch
      banks.py         bank cards, bank_summary(), shared_account_hint(), toggle_bank(),
                       bank_dialog(), option_control()
      accounts.py      AccountCards (the Accounts tab), BY_HAND_HINT
      networth.py      debt mappings (mapping_row) and adjustment settings, CLEARED_LABELS
      privacy.py       Data & privacy: what is kept where, resync, reset; token_wording()
```

### 3.1 Running and security

- `yul app [--port N] [--no-browser]` (`cli/commands/app.py`) is always registered, hidden from
  `--help` when `web.available()` is False; it then prints
  `Install the web UI with: uv tool install 'ynab-unlinked[web]'` (and the pip line) and
  exits 1. Checking at call time keeps the hint testable.
- `run()` binds `127.0.0.1`, picks a free port when none is given, prints
  `http://127.0.0.1:<port>/?token=<token>` and opens it unless `--no-browser`. On startup
  it starts a background store sync when configured. NiceGUI's storage lives in
  `storage_dir()`, not in a `.nicegui` folder in the working directory; it and the data
  folder holding it are 0700, and its `secret` is created 0600 with `os.open` (existing ones
  are narrowed).
- `security.TokenGuard` (pure ASGI, sees http and websocket scopes, NiceGUI's static,
  upload and socket.io routes included): `?token=<token>` answers a tiny page that sets the
  HttpOnly, SameSite=Strict cookie `yul_session_<port>` (`cookie_name(port)`: cookies ignore
  ports, so two runs do not clobber each other) and navigates to the same path without the
  token (a page, not a 302: browsers drop SameSite=Strict cookies on a redirect chain that
  started outside the site, as when another program opens the browser). Afterwards the
  cookie is required; everything else gets 403, websockets are closed with 1008.
  `TokenGuard(app, token, port)` also refuses any request whose `Host` is not exactly
  `127.0.0.1:<port>` (DNS rebinding), and websocket handshakes and non GET/HEAD requests
  whose `Origin` is present and not `http://127.0.0.1:<port>` (a page served from another
  loopback port is "same site", so SameSite does not stop it). Every HTTP response, refused
  ones included, carries `X-Frame-Options: DENY`, `Content-Security-Policy: frame-ancestors
  'none'` and `X-Content-Type-Options: nosniff` (`FRAME_HEADERS`).

### 3.2 Shell contract for views

The app is a single page: `shell.root()` renders the sidebar (232px, collapsible to a 64px
rail from its last entry, state in `app.storage.user`), the top bar and the drop overlay
once per tab, and `ui.sub_pages` swaps the content in a column centered in the main area
(`.yul-views`, max 1360px). Every path but `/onboarding` redirects to `/onboarding`
until `state().configured`; `/onboarding` redirects to `/` once it is.

```python
from nicegui import PageArguments, ui
from ynab_unlinked.web import shell, theme
from ynab_unlinked.web.components import button, glass_card, pill, stat_tile, Segment, segmented_bar, empty_state
from ynab_unlinked.web.state import state

@shell.view("/networth", key="networth", title="Net worth",
            subtitle="All your accounts in one figure",   # str or Callable[[], str]
            icon="networth",                         # key of components.ICONS
            order=40)                                # bottom=True puts it under the spacer,
                                                     # live=False for views with forms
async def networth_view(args: PageArguments) -> None:   # the parameter is optional
    ...  # already inside shell.page(title, subtitle): just render the body
```

- Re-registering a path replaces the view (agents replace the placeholder bodies in place).
- `shell.page(title, subtitle, key=None)`: context manager that sets the top bar and yields
  the content column; `@view` builders already run inside it.
- `shell.set_header(title=None, subtitle=None)`: change the top bar later.
- `shell.refresh_view()`: render the current view again when it is `live` (the default).
  The sync chip calls it after a sync that brought changes, so Home, Reconcile and Net
  worth show the new data without a reload; Import and Settings (`live=False`) keep what
  the user is editing.
- `shell.notify(message, kind="ok" | "info" | "warn" | "error")`: toast at the top, centered, 3s.
- `await shell.confirm(title, lines, action_label, danger=False) -> bool`: the one
  confirmation before a write, listing what will change.
- Drop handoff: files dropped anywhere go to `/import`. The Import view reads them with
  `shell.pending_uploads()` (returns `list[shell.UploadedFile]` and empties the queue;
  `UploadedFile` is NiceGUI's `FileUpload`: `.name`, `.size()`, `await .read()`,
  `await .save(path)`), and while on screen registers
  `shell.on_drop(handler, owner=element)` so later drops reach `handler(files)` directly.
  `await shell.hand_off_uploads(files)` does the same for files received anywhere else
  (Home's drop zone): the live handler if there is one, else the queue and `/import`.
- The overlay's `ui.upload` is `display: none` until `body.yul-dragging` (set by the drag
  tracking script in `theme.DRAG_JS`, capture phase because QUploader stops the drag events'
  propagation), so it takes no clicks and is not in the accessibility tree. Never hide it with
  `set_visibility(False)`: NiceGUI answers 403 to uploads to hidden elements.
- Drop zone (`components/dropzone.py`):
  `dropzone(on_files, *, compact=False, accept=None) -> ui.element` (the `ui.upload`, marker
  `dropzone`). `on_files(list[UploadedFile])` may be async; `accept=None` is
  `DEFAULT_ACCEPT` (`.pdf,.xlsx,.xls,.txt,.html`).
- Deep links: `/settings?tab=<slug>` (`connection`, `banks`, `accounts`, `networth` or
  `net-worth`, `data`, `privacy` or `data-privacy`, case insensitive) opens that tab;
  anything else opens Connection (`settings.tab_from_slug`).
- `shell.sync_label(last, now)` / `shell.sync_message(result)` for sync wording.
- Navigation: `ui.navigate.to(path)` with the paths on `shell` (`HOME_PATH`, `IMPORT_PATH`,
  `RECONCILE_PATH`, `NETWORTH_PATH`, `SETTINGS_PATH`, `ONBOARDING_PATH`); views never import
  each other: shared wording is `web.wording`, shared YNAB calls are `web.ynab`.

`state()` (`web/state.py`) is the app's shared state: config, client, store, formatter,
loaders and the sync. See the docstrings in `web/state.py`. Views never save `state().config`
or a copy of it: every config save is `await shell.save_config(change, message=None) -> bool`,
which runs `state().update_config(change)` through `run.io_bound`, toasts `message`, and on a
failure toasts `wording.SAVE_FAILED` and returns False.

Theme (`web/theme.py`): `SERIES` / `SERIES_LIGHT` (6 colours: DESIGN's three, the
`#eda100`, a violet and a pink; `--series-1..6` in CSS), `ACCENT` (gradient start and end), `GOOD`, `WARN`, `BAD` (+ `_LIGHT`),
`palette()` for the current browser's theme (`Palette` with series, accent, status and
text colours for ECharts), `is_dark()`. CSS classes are prefixed `yul-` (`yul-card`,
`yul-pill ok|warn|acc`, `yul-grad`, `yul-hero`, `yul-muted`, `yul-faint`, `yul-num`,
`yul-row`, `yul-grow`, `yul-section`, `yul-kv`, `yul-map`, `yul-stagger`, `yul-prog active`,
...); CSS variables follow DESIGN.md (`--surface`, `--surface-2`, `--text-2`,
`--series-1`, `--accent`, ...). Quasar fields look right with `.props("outlined dense")`;
use `components.button` rather than raw `ui.button` (Quasar's colours are off there).
Never name a class `xs`, `sm`, `md`, `lg` or `xl`: Quasar hides those outside their
breakpoint (`button(small=True)` uses `small`). `.yul-page` stretches to the full content
width whatever its content.

### 3.3 Other rules

- Views call `core/` and `store/` only. Blocking calls (YNAB, parsing, config saves, store
  writes) run through `run.io_bound` so the UI stays responsive.
- Uploaded files go to a `TemporaryDirectory` owned by the page; removed on commit or
  discard.
- `local_data.py` lists and deletes what yul stores (config dirs, store, the web
  preferences directory `web.storage_dir()`); `yul config reset` and Settings "Reset all
  data" share it.
- Visual language is DESIGN.md next to this file.

### 3.4 Activity log entries

Every view logs the same shape through `state().store.log(budget_id, kind, message,
details)`, so Home can read it back. Counts go in `details` under the key below; Home bolds
that number in the message and shows `file` in mono.

| kind | message | details |
|---|---|---|
| `import` | `Imported {plural(created, "transaction")} to {account_name} from {file}` | `loader` (config key), `account_id`, `account_name`, `file`, `created`, `duplicates`, `skipped` |
| `reconcile` | `Reconciled {count} transactions in {n} accounts` | `count`, `accounts: [{id, name, count}]` |
| `adjustment` | `Balance of {account_name} set to {new} ({signed amount})` | `account_id`, `account_name`, `old`, `new`, `amount` (milliunits) |
| `sync` | `Synced · {changes} changes from YNAB`, plus ` · {ghosts} stale removed` when ghosts > 0 | `changes`, `full`, `ghosts` (only when > 0) |
| `config` | free text | free |

Amounts in messages are formatted with `state().formatter`; in details they are milliunits.
The CLI writes `import` (after each committed file of `yul load <bank>` and `yul load auto`)
and `reconcile` (after `yul reconcile` locks) with the same shapes through
`ynab_unlinked.activity`, at `store_path()`; a store it cannot open only warns. The app's
next sync brings the transactions.
Use singular nouns for 1 ("1 change"). `AppState._sync` logs `sync` only when the sync was
full, brought changes or removed ghosts (one runs at every start). Home reads: the newest
`reconcile` (hero change since), the newest `import` per `details["loader"]` (the last
imports line, 3.4.2) and the newest `adjustment` per `details["account_id"]` (when a balance
kept by hand was last set, with the transactions carrying the payee or the memo of the
adjustment settings: `last_set_by_hand`, so a settings change does not hide older ones). It ignores `config` entries. Home has no setup card: every open
account counts from the start (3.4.1).

### 3.4.1 Which accounts count

`config.accounts` holds account settings, not a selection. In `web/accounts.py`:

```python
def default_account(account: StoredAccount) -> TrackedAccount
    # bucket = default_bucket(type), track_balance = (bucket is Bucket.ASSETS)
def account_settings(config, account: StoredAccount) -> TrackedAccount
    # the config entry for the account, else default_account(account)
def effective_accounts(config, stored: Iterable[StoredAccount]) -> list[TrackedAccount]
    # one per open account in `stored`, in store order, skipping `counted=False`; config
    # entries of closed or unknown accounts are ignored
def by_hand_accounts(config, stored) -> list[TrackedAccount]
    # effective_accounts() with track_balance: the pencil always shown, the age pill, the
    # Home "stale balances" card
def effective_nettings(config) -> tuple[DebtNetting, ...]   # config.debt_mappings, always
```

Home, Net worth and the Settings Net worth tab read through these. A mapping that names a
left out or closed account is kept in the config; `net_worth` skips targets it does not
count.

### 3.4.2 Home

`load_home(store, config, loaders, today) -> HomeData` reads everything once per visit
through `run.io_bound`; Home never calls YNAB.

```python
@dataclass(frozen=True)
class LoaderDue:            # one bank of the last imports line
    name: str               # config key (LoaderSpec.name)
    key: str                # loader key, for the logo
    title: str              # LoaderSpec.title
    last: date | None       # newest import (Store.last_import_per_loader), None if never

@dataclass(frozen=True)
class HomeData:
    net_worth: int          # milliunits, tracked accounts with debt netted
    delta: int              # change since `since`
    since: date             # last reconcile, or 30 days ago
    spark: list[Point]      # 90 days of net worth
    unreconciled: int       # cleared, not reconciled, open accounts
    unreconciled_accounts: int
    stale: list[str]        # accounts set by hand older than 30 days
    last_imports: list[LoaderDue]  # banks turned on in Settings, registry order
    activity: list[Activity]       # newest 10
    every_account: bool = False    # nothing tracked: hero says "every open account"
```

`attention_items(data) -> list[Attention]` gives the "Needs you" cards in display order:
`unreconciled` (-> `/reconcile`) and `stale` (-> `/networth`); nothing else. The
sync problem before the first sync stays the banner above the grid (`first-sync`).
`last_imports_line(data, today)` is `"Last imports · Cobee never · Sabadell 12 Oct"`
(`today`, `yesterday`, `N days ago` under 14 days, then `short_date`), `None` without banks.

Markers: `home` (grid), `first-sync`, `hero`, `net-worth`, `net-worth-delta`, `sparkline`,
`home-import`, `dropzone`, `last-imports`, `needs-you`, `attention` (the card grid, only
when there are cards), `attention-unreconciled`, `attention-stale`, `nothing-waiting`,
`activity`, `activity-item`, `activity-message`, `activity-empty`.

### 3.5 Markers of the other views

#### Net worth

Markers: `no-tracked`, `pick-{account_id}`, `pick-count`, `edit-{account_id}`,
`balance-input-{account_id}`, `accept-{account_id}`, `cancel-{account_id}`,
`balance-hint-{account_id}`.

#### Onboarding

Markers: `token-input`, `check-token`, `token-lost`, `wizard-message`, `wizard-next`,
`wizard-back`, `budget-{id}`, `loading-accounts`, `accounts-error`, `accounts-retry`,
`loader-{key}`, `first-copy`, `copy-progress`, `copy-error`, `copy-retry`, `open-yul`.

#### Settings

Markers: `bank-shared-{key}`, `accounts-lede`, `account-card-{id}`, `bucket-section-{bucket}`,
`account-{id}`, `bucket-{id}`, `bucket-{id}-{bucket}`, `by-hand-{id}`.
