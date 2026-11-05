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
- Token stays in the config file. Keychain is a later change.

## 1. Package layout

```
src/ynab_unlinked/
  core/                  pure services. May import: config, entities, models, ynab_api,
                         store, parsers. MUST NOT import: typer, rich, textual, nicegui,
                         ynab_unlinked.display, ynab_unlinked.utils (the rich helpers).
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
  commands/              CLI. Thin: parse args, call core, print.
  web/                   NiceGUI app, only importable when the `web` extra is installed (3)
  ynab_api/client.py     the only place that talks to the SDK
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

def parse_transactions(entity: Entity, input_file: Path, context: YnabUnlinkedContext) -> list[Transaction]
    # wraps entity.parse, lets ParsingError propagate

def build_import_plan(
    client: Client, budget_id: str, account_id: str, entity_name: str,
    input_file: Path, transactions: list[Transaction], buffer_days: int = 15,
    progress: Progress = NullProgress(),
) -> ImportPlan
    # assigns import ids (models.assign_import_ids), fetches YNAB transactions for the
    # account since min(date) - buffer, marks already_imported by import_id or legacy id.
    # An empty `transactions` returns a plan with no rows without calling YNAB.

def commit_import_plan(
    client: Client, budget_id: str, plan: ImportPlan, cleared: TransactionClearedStatus,
    progress: Progress = NullProgress(),
) -> ImportResult
    # creates plan.new_rows, returns created count and the duplicates YNAB rejected.
    # A plan with no new rows returns ImportResult(0, ()) without calling YNAB.
```

The `NullProgress()` defaults are `core.progress.NO_PROGRESS` in the code. The CLI passes `display.CliProgress`, a context manager that shows a
spinner per step and stops it if the core call raises. `utils.display_import_table` takes
`Sequence[ImportRow]`.

`process.process_transactions` keeps its signature and behaviour (tests in `tests/process`
pin it) but is implemented on top of these functions plus the account prompt and the tables.

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

def reconcile(
    client: Client, budget_id: str, transactions: Sequence[TransactionDetail],
    progress: Progress = NullProgress(),
) -> dt.date | None
    # patches cleared=RECONCILED (on copies, the caller's objects are untouched), returns
    # the latest transaction date or None if empty (YNAB is not called then)

def next_reconciliation_date(locked: Iterable[dt.date],
                             remaining: Iterable[dt.date] = ()) -> dt.date | None
    # None when nothing was locked; the earliest date left unreconciled in scope when
    # anything was, else the latest locked date. No buffer: the scope rewinds once from it
    # (`yul reconcile --buffer`, default 7, and the app's "since" pill, 7 days)
```

`commands/reconcile.py` and the Textual app keep working on top of these.

### 2.4 Loaders and detection (`entities/`, `core/detect.py`)

Every entity package (`entities/bbva`, `entities/sabadell`, `entities/cobee`) exposes a
module level `spec: LoaderSpec` next to the existing `command`.

```python
# entities/_protocol.py
class Match(NamedTuple):
    confidence: float   # 0.0 (no) .. 1.0 (certain)
    reason: str         # short, user facing: "BBVA header row found"

class Entity(Protocol):
    def name(self) -> str: ...
    def parse(self, input_file: Path, context: YnabUnlinkedContext) -> list[Transaction]: ...
    def sniff(self, input_file: Path) -> Match: ...
        # cheap, reads at most the first page / first rows / first KB, never raises

# entities/registry.py
@dataclass(frozen=True)
class LoaderOption:
    key: str                        # "year", "language"
    label: str                      # "Year of the statement"
    default: str                    # "auto" allowed where the loader can infer it
    choices: tuple[str, ...] | None = None

@dataclass(frozen=True)
class LoaderSpec:
    key: str                        # package name: "bbva", "sabadell", "cobee"
    name: str                       # Entity.name(): "BBVA Credit Card", "sabadell", "cobee"
    title: str                      # user facing: "BBVA Credit Card", "Sabadell", "Cobee"
    input_types: tuple[InputType, ...]
    options: tuple[LoaderOption, ...]
    build: Callable[[Mapping[str, str]], Entity]          # options -> entity instance
    extras: Callable[[Mapping[str, str]], Any] | None     # options -> context.extras (cobee)

    def accepts(self, input_file: Path) -> bool           # suffix in input_types, same rule
                                                          # as utils.extract_type
    def context_extras(self, options) -> Any              # extras(options), or None

AUTO = "auto"
def concrete(options: Mapping[str, str], key: str) -> str   # ValueError on missing or "auto"
def loaders() -> list[LoaderSpec]        # discovered from entity packages, sorted by key
def loader(key: str) -> LoaderSpec       # KeyError if unknown
```

`build` and `extras` take concrete values only: they raise `ValueError` on a missing,
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

def detect_loaders(files: Sequence[Path], context: YnabUnlinkedContext) -> list[Detection]
    # for each file: loaders whose input_types accept the suffix -> sniff -> keep
    # confidence >= MIN_CONFIDENCE -> trial parse with resolved options and a copy of the
    # context carrying the loader extras -> rank by (parsed ok, confidence, transaction count)

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

CLI: `yul load auto <files...>` runs detection, prints a table (file, loader, confidence,
transactions, account), and stops with exit 1 before importing anything if a file is not
supported, not recognised, unreadable or ambiguous. Otherwise it is built on
`core.importing`, not `process_transactions`: it resolves the account of every file first
(`process.get_or_prompt_account_id`, so `-a` asks once per file), parses each file with
`parse_transactions` and builds every `ImportPlan`, prints one import table per file, then
asks ONE confirmation for the whole batch ("Create N transactions from M files in YNAB?"),
commits every plan and prints one summary: duplicates YNAB rejected and transactions created
per account (named from `config.accounts` when known, else the id). Nothing is asked when no
file has new transactions. `--yes` skips the confirmation and also fails up front when a
detected loader has no saved account; `--show` prints the parsed transactions of each file
and stops without resolving accounts or calling YNAB.

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
    total: int                              # cash + savings + assets after netting
    def by_bucket(self) -> dict[Bucket, int]
    def share(self, account_id: str) -> float   # balance / total, 0 for debt

def net_worth(accounts: Sequence[AccountBalance], nettings: Sequence[DebtNetting]) -> NetWorth
    # each debt balance is split evenly over mapped_to, remainder on the first; a debt with
    # no mapping is NOT subtracted

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

Implementation notes (as built):

- The client takes adjustments typed as `ynab_api.client.BalanceAdjustment`, a protocol
  (`account_id`, `amount`) that `Adjustment` satisfies, so `ynab_api` never imports `core`.
  It returns 0 without calling YNAB when there is nothing to create.
- The even split truncates toward zero (`int(balance / n)`), not floor
  division: -1001 over two accounts nets -501 on the first and -500 on the second.
- `NetWorth.share` and `build_adjustments` raise `KeyError` for an account they do not know
  (unknown id, or a wanted balance with no current one).
- `parse_amount_to_milliunits(text, *, decimal_separator=".", group_separator=",")`. With
  the defaults `,` is always a thousands separator, so
  `€1.000,50` is read as `1.0005` (1000 milliunits), not 1000.50. Pass the budget's
  `currency_format` separators to swap the roles: with `decimal_separator=","` and
  `group_separator="."`, `1.000,50` is 1000500 and `99,99` is 99990. A group separator
  other than `.` or `,` (space, apostrophe) is dropped like any symbol; a currency symbol or
  ISO code before or after the number is ignored. A decimal separator other than `.` or `,`,
  or equal to the group separator, raises `ValueError`.

### 2.6 Config V4 (`config/`)

```python
class LoaderConfig(BaseModel):
    account_id: str
    options: dict[str, str] = {}
    enabled: bool = True        # off: `load auto` and the app skip the bank, settings kept

# The token (`api_key`) lives in the system keychain (`ynab_unlinked.keychain`, through
# `keyring`) when there is one: `save()` stores it and writes `keychain.REFERENCE`
# ("@keychain") to the file, `load()` reads it back; a token still in the file moves on the
# first load. Without a keychain the file keeps it in plain text. `api_key == ""` after
# load means the keychain lost it: the CLI says to run `yul config set api_key`, the web
# app keeps the config in `state().token_lost` and onboarding asks for the token only.
# A save while the token is unread writes `REFERENCE` back, never an empty token.
# `save()` writes a 0600 temp file in the same directory (created 0700) and `os.replace`s it.
# `keychain.read()` returns None when `YUL_NO_KEYCHAIN` is set.

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
    def tracked(self) -> list[TrackedAccount]     # entries with track_balance, CLI only; the
                                                  # app uses web.accounts.by_hand_accounts
    def debt_mapping(self, debt_account_id) -> DebtMapping | None
```

- `DeltaConfigV3ToV4`: `entities` -> `loaders` (options empty), everything else default.
  Rollback drops the new fields. Registered in `core.migration_engine()`.
- `LATEST_VERSION`, `MAX_CONFIG_VERSION`, `VERSION_MAPPING`, `LatestConfig` updated.
- `MigrationEngine.migrate` takes `progress: Progress = NullProgress()` instead of calling
  `display.process` directly; `config/core.py` passes a CLI progress. After this the
  `config/migrations` package imports nothing from `ynab_unlinked` outside itself and
  `core/progress.py`.
- `MigrationEngine.migrate` reports through `progress` only when there is something to
  migrate; on failure it calls `progress.done()` with no message and re-raises. The CLI
  progress is `display.CliProgress`.
- `tests/assets/config_V4/config.json` fixture (same layout as the V1..V3 assets),
  `@pytest.mark.version("V4")` support in conftest, `config_v4` fixture.

### 2.7 Store (`store/`) and history (`core/history.py`)

```python
# store/paths.py
def store_path() -> Path   # user_data_dir("ynab-unlinked", "committhatline") / "store.sqlite"

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
        # the dir is created 0700 and the file 0600 (an existing file is set to 0600)
    def sync(self, client: Client, budget_id: str, progress: Progress = NullProgress()) -> SyncResult
        # no knowledge stored for this budget -> full fetch
        # (client.transactions_with_knowledge with since_date=FULL_SYNC_SINCE, 1900-01-01,
        # because YNAB defaults a missing since_date to one year ago); else
        # client.transactions_delta(budget_id, knowledge). Upserts rows, keeps deleted rows
        # flagged, replaces the budget's accounts (closed kept, deleted skipped), stores the
        # new server_knowledge, all in one SQLite transaction.
        # A 409 on a delta forgets the budget's rows and knowledge and redoes a full fetch once.
        # Then runs the ghost repair (below) and reports it in ghosts_removed.
    def accounts(self, budget_id: str) -> list[StoredAccount]        # sorted by name
    def transactions(self, budget_id: str, *, account_id: str | None = None,
                     since: dt.date | None = None, until: dt.date | None = None,
                     cleared: Iterable[TransactionClearedStatus] | None = None) -> list[StoredTransaction]
        # never returns deleted rows; since/until inclusive; oldest first (date, id)
    def unreconciled(self, budget_id: str) -> list[StoredTransaction]   # cleared + uncleared
    def last_sync(self, budget_id: str) -> dt.datetime | None           # aware, UTC
    def clear(self, budget_id: str | None = None) -> None               # activity log too
    def log(self, budget_id: str, kind: str, message: str,
            details: Mapping[str, Any] | None = None, *, at: dt.datetime | None = None) -> None
        # kinds and their details: section 3.4. `at` (aware) backdates an entry, default now
    def activity(self, budget_id: str, limit: int | None = 20, *,
                 kind: str | None = None) -> list[Activity]
        # newest first; limit None = all; kind keeps one kind only
    def upsert(self, budget_id: str, *, accounts: Iterable[StoredAccount] = (),
               transactions: Iterable[StoredTransaction] = ()) -> None
        # insert or replace by id in one transaction; sync state untouched, so the next delta
        # sync still brings the rows. For writes yul just made to YNAB (reconcile, import,
        # adjustments: reflect them before the next sync) and to seed tests
    def daily_amounts(self, budget_id: str,
                      account_ids: Iterable[str] | None = None) -> dict[str, DailyAmounts]
        # per account: its stored balance and the sum of its non deleted transactions per
        # day, in one query (GROUP BY account, date UNION the accounts). Feeds core.history.

@dataclass(frozen=True)
class DailyAmounts:
    balance: int | None                       # StoredAccount.balance, None if not stored
    days: tuple[tuple[dt.date, int], ...]     # (date, sum of that day), oldest first
```

Ghost repair: when the user approves a YNAB match between an imported transaction and a
manual or scheduled one of the same account, the manual one survives with the `import_id`
(and `matched_transaction_id` pointing at the import) and the imported id vanishes (404)
without a delta tombstone. After every sync `Store._repair_ghosts` looks for two or more non
deleted rows sharing `(account_id, import_id)`, checks each id with
`client.transaction_exists` and flags the missing ones `deleted = 1`. A group where every
row exists (a match not approved yet) stays. No duplicate groups, no requests.

Every method opens its own connection, so one `Store` can be shared across threads
(`run.io_bound`). Timestamps (`synced_at`, `at`) are UTC ISO strings. `Store.sync` does not
log activity; the caller decides what is worth an entry.

Schema: `accounts(budget_id, id, name, type, closed, on_budget, balance, cleared_balance,
uncleared_balance, PRIMARY KEY(budget_id, id))`, `transactions(budget_id, id, account_id,
date, amount, cleared, approved, deleted, payee_name, category_name, import_id, memo,
transfer_account_id, PRIMARY KEY(budget_id, id))` with an index on `(budget_id, account_id,
date)`, `sync_state(budget_id PRIMARY KEY, server_knowledge, synced_at)`,
`activity(budget_id, at, kind, message, details)` (details is a JSON object). The schema
version lives in `PRAGMA user_version`; `store/migrations/NNNN_*.sql` are the steps, one file each (`store.migrations.MIGRATIONS`).

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
    # value on `end` equals the account balance in the store (assert in tests)

def net_worth_series(store: Store, budget_id: str, accounts: Sequence[TrackedAccount],
                     nettings: Sequence[DebtNetting], start: dt.date, end: dt.date,
                     ) -> dict[str, list[Point]]
    # keys: "total", every Bucket value, every account id. Debt netting applied per day
    # through core.balances.net_worth. Points weekly when end - start > 366 days.

def sample_dates(start: dt.date, end: dt.date) -> list[dt.date]
    # every day, or every Monday in the range plus `end` when end - start > 366 days
```

History as built:

- Both series make one `Store.daily_amounts` call (a single SQL query) and accumulate in
  Python, then sample at `sample_dates(start, end)`. Ten years of 15 transactions a day over
  20 accounts (55k rows) takes about 60 ms for the net worth series.
- The series is anchored on the live balance: it is shifted by `StoredAccount.balance -
  sum(all non deleted amounts)`, so its last point always equals the balance YNAB reported
  even if some history is missing. Normally the shift is 0 because the starting balance is
  a transaction. An account the store does not know is flat at 0; an account with
  transactions but no stored row (deleted in YNAB) is not shifted.
- Transactions dated after `end` are left out of the points but count for the anchor, so a
  past `end` shows the balance on that day, not the live one.
- `end < start` gives no points (empty lists, keys still present in the net worth dict).
- `net_worth_series` only uses `accounts`: a debt account missing from it is not netted
  (as in `net_worth`). Account series hold balances after netting, debt accounts keep their
  raw balance; the `"debt"` key is the sum of the raw debt balances.
- History tests fill the store through `Store.sync` with the `ynab_api` stub (`populate`
  fixture in `tests/core/test_history.py`). Web view tests seed it with `Store.upsert` and
  `Store.log(..., at=...)` after one empty `Store.sync` (so `last_sync` is set); see the
  `store` fixture in `tests/web/views/test_home.py`.

`yul config reset` also deletes the store file. `yul privacy` lists it. Tests get an autouse
`store_file` fixture that points `store_path()` into `tmp_path`.

## 3. Web app (`web/`, extra `web`)

```
web/
  __init__.py          nothing heavy: available() (find_spec, never imports NiceGUI),
                       storage_dir() (user data dir / "web": browser prefs and their secret)
  app.py               build(token, port) -> root page (guard, static files, CSS, views, /onboarding);
                       run(port: int | None, open_browser: bool, announce=None)
  state.py             AppState / state(): config, client, store, formatter, loaders, last_sync
  accounts.py          effective_accounts() / by_hand_accounts() / effective_nettings():
                       what Home, Net worth and Settings count (3.4.1)
  shell.py             layout, view registry, top bar, toasts, confirm dialog, drop overlay
  theme.py             palette constants, dark/light switch, install() of static/yul.css
  security.py          per run token, TokenGuard middleware, free_port(), entry_url()
  static/              yul.css (tokens, component classes, motion), fonts/InterVariable.woff2
  components/          button, glass_card, pill, bank_logo, stat_tile, segmented_bar, empty_state,
                       spinner, check, icon (+ ICONS)
    dropzone.py        dropzone(on_files, *, compact=False, accept=None): Home and Import step 1
    reconcile_controls.py  pill_group, switch, add_css_once (yul-rec- classes);
                       generic, promote to components when another view needs them
    history_chart.py   ChartSeries, history_options() / history_chart() / set_options(),
                       money_js() / compact_js(): the ECharts history line chart
    networth_parts.py  count_up(), share_bar(), install_css() (the yul-nw- classes)
  views/
    __init__.py        register(): imports every view module
    onboarding.py      /onboarding, outside the shell (token, budget, banks, done)
    home.py            /            hero, import (drop zone, last imports), needs you, activity (3.4.2)
    import_.py         /import      Files -> Review -> Done on core.detect and core.importing
    reconcile.py       /reconcile   per account cleared vs bank balance, lock (see 3.5)
    networth.py        /networth    history chart, buckets, accounts, balance updates, drawer (see 3.6)
    settings.py        /settings    connection, banks, accounts, net worth, data & privacy
```

### 3.1 Running and security

- `yul app [--port N] [--no-browser]` (`commands/app.py`) is always registered, hidden from
  `--help` when `web.available()` is False; it then prints
  `Install the web UI with: uv tool install 'ynab-unlinked[web]'` (and the pip line) and
  exits 1. Checking at call time keeps the hint testable.
- `run()` binds `127.0.0.1`, picks a free port when none is given, prints
  `http://127.0.0.1:<port>/?token=<token>` and opens it unless `--no-browser`. On startup
  it starts a background store sync when configured. NiceGUI's storage lives in
  `storage_dir()`, not in a `.nicegui` folder in the working directory.
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
  loopback port is "same site", so SameSite does not stop it). Tests talk to
  `http://127.0.0.1:8765` (`tests.helpers.web.BASE_URL`).

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
  `DEFAULT_ACCEPT` (`.pdf,.xlsx,.xls,.txt,.html`). A QUploader with a custom header slot
  holding `<q-uploader-add-trigger>` (the native input stretched over the card, so a click is
  a real user gesture) and no file list; the queue is reset after each batch.
- Deep links: `/settings?tab=<slug>` (`connection`, `banks`, `accounts`, `networth` or
  `net-worth`, `data`, `privacy` or `data-privacy`, case insensitive) opens that tab;
  anything else opens Connection (`settings.tab_from_slug`).
- `shell.sync_label(last, now)` / `shell.sync_message(result)` for sync wording.
- Navigation: `ui.navigate.to(path)`; `shell.IMPORT_PATH`, `shell.ONBOARDING_PATH`.

`state()` (`web/state.py`): `config: LatestConfig | None`, `client: Client | None`,
`store: Store` (opened on first use at `store_path()`), `formatter`, `loaders:
list[LoaderSpec]`, `last_sync`, `sync_error`, `load_error`, `configured`, `syncing`,
`require() -> (config, client)` (raises `NotConfiguredError`), `load()` / `reload()`,
`update_config(change: Callable[[LatestConfig], None]) -> LatestConfig` (every config save
in the app: reads the file again, applies `change`, saves and reloads, so what the CLI saved
meanwhile is kept; never save `state().config` or a copy of it), `await sync(progress=NullProgress())` (shared by concurrent
callers, runs through `run.io_bound`), `sync_in_background()`, `stale` /
`invalidate()` (call after every write to YNAB: marks the store stale and starts a
background sync) and `fresh(max_age) -> bool` (synced within `max_age`, not stale, not
syncing: what Reconcile checks before showing the store),
`await budget_accounts() -> list[StoredAccount]` (store once synced, YNAB before).
`default_bucket(account_type: str) -> Bucket`.

Theme (`web/theme.py`): `SERIES` / `SERIES_LIGHT` (6 colours: DESIGN's three, the
`#eda100`, a violet and a pink; `--series-1..6` in CSS), `ACCENT` (gradient start and end), `GOOD`, `WARN`, `BAD` (+ `_LIGHT`),
`palette()` for the current browser's theme (`Palette` with series, accent, status and
text colours for ECharts), `is_dark()`. CSS classes are prefixed `yul-` (`yul-card`,
`yul-pill ok|warn|bad|acc`, `yul-grad`, `yul-hero`, `yul-muted`, `yul-faint`, `yul-num`,
`yul-row`, `yul-grow`, `yul-section`, `yul-kv`, `yul-map`, `yul-stagger`, `yul-prog active`,
...); CSS variables follow DESIGN.md (`--surface`, `--surface-2`, `--text-2`,
`--series-1`, `--accent`, ...). Quasar fields look right with `.props("outlined dense")`;
use `components.button` rather than raw `ui.button` (Quasar's colours are off there).
Never name a class `xs`, `sm`, `md`, `lg` or `xl`: Quasar hides those outside their
breakpoint (`button(small=True)` uses `small`). `.yul-page` stretches to the full content
width whatever its content.

### 3.4 Activity log entries

Every view logs the same shape through `state().store.log(budget_id, kind, message,
details)`, so Home can read it back. Counts go in `details` under the key below; Home bolds
that number in the message and shows `file` in mono.

| kind | message | details |
|---|---|---|
| `import` | `Imported {created} transactions to {account_name} from {file}` | `loader` (config key), `account_id`, `account_name`, `file`, `created`, `duplicates`, `skipped` |
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
`reconcile` (hero change since) and the newest `import` per `details["loader"]` (the last
imports line, 3.4.2). It ignores `config` entries. Home has no setup card: every open
account counts from the start (3.4.1).

### 3.4.1 Which accounts count

`config.accounts` holds account settings, not a selection. In `web/accounts.py`:

```python
def default_account(account: StoredAccount) -> TrackedAccount
    # bucket = state.default_bucket(type), track_balance = (bucket is Bucket.ASSETS)
def account_settings(config, account: StoredAccount) -> TrackedAccount
    # the config entry for the account, else default_account(account)
def effective_accounts(config, stored: Iterable[StoredAccount]) -> list[TrackedAccount]
    # one per open account in `stored`, in store order, skipping `counted=False`; config
    # entries of closed or unknown accounts are ignored
def by_hand_accounts(config, stored) -> list[TrackedAccount]
    # effective_accounts() with track_balance: the pencil always shown, the age pill, the
    # Home "stale balances" card. Replaces `config.tracked()` in the app
def effective_nettings(config) -> tuple[DebtNetting, ...]   # config.debt_mappings, always
```

Home, Net worth and the Settings Net worth tab read through these. A mapping that names a
left out or closed account is kept in the config; `net_worth` skips targets it does not
count.

### 3.4.2 Home (as built)

`load_home(store, config, loaders, today) -> HomeData` reads everything once per visit
through `run.io_bound`; Home never calls YNAB.

```python
@dataclass(frozen=True)
class LoaderDue:            # one bank of the last imports line
    name: str               # config key (LoaderSpec.name)
    key: str                # loader key, for the logo
    title: str              # LoaderSpec.title
    last: date | None       # newest import from the app, None if never

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

Layout: `.yul-home` grid (main 1.55fr + side, one column under 1000px). Main, staggered:
hero, `section.yul-home-block` Import (title `.yul-section`, dropzone, muted line),
`section.yul-home-block.yul-needs` Needs you (title, `.yul-attn` grid or the quiet line).
`.yul-needs` is an inline size container: `.yul-attn` has 3 equal columns from 640px, 2
from 420px, else 1. Side: Recent activity.

Markers: `home` (grid), `first-sync`, `hero`, `net-worth`, `net-worth-delta`, `sparkline`,
`home-import`, `dropzone`, `last-imports`, `needs-you`, `attention` (the card grid, only
when there are cards), `attention-unreconciled`, `attention-stale`, `nothing-waiting`,
`activity`, `activity-item`, `activity-message`, `activity-empty`.

### 3.6 Net worth view (as built)

- Counted accounts are `web.accounts.effective_accounts()` (3.4.1); the `track_balance`
  ("by hand") ones have their pencil always shown and get the age pill. When every account
  is left out the view shows an empty state (`no-tracked`) that opens Settings › Accounts. Balances come from `store.accounts()`
  (an account the store does not know counts as 0), netting from `config.debt_mappings`.
  Store reads (`load_snapshot`, the series, the drawer) run through `run.io_bound`.
- Ranges: `range_start(key, today, earliest)` uses calendar months (`1M` on 31 Mar is
  28 Feb) and is clamped to the first transaction of the counted accounts, which is also
  what `All` means. The series is one `net_worth_series` call per range; grouping and the
  account chips regroup it without reading the store again.
- "By account" picks with chips (`yul-chipc`, marker `pick-{account_id}`), one per counted
  account in table order (`table_order`), above them "Accounts · n of 6" (`pick-count`).
  Up to `MAX_PICKED = 6`; the default is the `DEFAULT_PICKED = 4` largest after netting,
  debt left out. A picked chip is `on` with a `yul-swatch` in `var(--series-{slot + 1})`;
  at the limit the others are `off` with the title "Remove one to add another" and ignore
  clicks.
- Chart (`components/history_chart.py`): amounts go to the browser in currency units and
  the tick, end label and tooltip formatters are JavaScript built from the budget's
  `currency_format`, so compact ticks follow the budget's symbol position (`90K€` for a
  symbol after the number, `€90K` before). Every series always carries the same keys
  (the area is transparent rather than absent) because NiceGUI merges an option into the
  previous one when the series count does not change. Total uses `palette.accent[0]`; by
  type `SERIES[0..2]`; by account (`SERIES[0..5]`) the colour slot of each picked account is kept while it
  stays picked and a newly picked one takes the first free slot (`assign_slots`).
- A 1s `ui.timer` re-renders the view when `(last_sync, syncing, sync_error)` changes and
  syncing is over (first sync, the sync after adjustments, a sync from the top bar chip),
  keeping an open balance editor and what was typed in it; the same tick restyles the charts when
  `theme.is_dark()` changes. With no accounts in the store the view shows "First sync
  running…" and starts a background sync if none is running.
- Adjustments, one account at a time: every row has a pencil (`edit-{account_id}`, shown on
  hover, always and accent coloured on "by hand" rows). It turns the balance cell into an
  input (`balance-input-{account_id}`) prefilled with the raw (not netted) stored balance,
  a ✓ (`accept-{account_id}`) and a ✗ (`cancel-{account_id}`); Enter is ✓, Escape is ✗,
  and opening another row closes the first. ✓ is the confirmation (no `shell.confirm`):
  the text is parsed with `parse_amount_to_milliunits` and the budget's separators
  ("Not an amount" under the input otherwise, `balance-hint-{account_id}`); the same
  balance as shown toasts "No change"; else one `run.io_bound` job reads the live balance
  (`client.account(budget_id, account_id).balance`, the store may lag behind YNAB),
  `build_adjustments` against it and `create_adjustments` (nothing when YNAB already has
  the wanted balance: "No change", invalidate). Then one `store.log(kind="adjustment")`
  through `run.io_bound` with the adjustment actually made, `state().invalidate()`,
  re-render, toast "{name} set to {new} ({signed difference})". A YNAB error is toasted
  through `ynab_error_message` and the editor stays open with what was typed.
- The account drawer is a `ui.dialog` with `position=right full-height` (a `ui.drawer`
  cannot live inside `ui.sub_pages`).
- Tests seed the store through `Store.sync` with the `ynab_api` stub answering
  (`serve()` in `tests/web/views/test_networth.py`); no write API was added to `Store`.

### 3.7 Onboarding as built (`views/onboarding.py`)

- `STEPS = ("Token", "Budget", "Banks", "Done")`, one `Wizard` per page. `refresh()` redraws
  the rail and the step and runs only on a change of step; selection and state changes
  update elements in place (`pick_budget` toggles `on` on the kept tiles, `show_message`,
  `update_footer`, `fill_loaders`, `fill_done`).
- The config is written as `LatestConfig(api_key, budget, loaders, accounts=[])`: an empty
  `accounts` list means every open account counts. Loaders map to any open, not deleted
  account of the budget (`AccountOption`), `guess_loader_account` preselects the one named
  after the bank.
- Continue from Budget sets the step to Banks and awaits `load_budget()` (`client.budget`
  and `client.accounts` through `run.io_bound`); Finish is disabled until it succeeded.
- Finish: `draft().save()`, `state().reload()`, step Done, then `await
  state().sync(LineProgress(label, client))`, the same shared task the sync chip uses.
  `LineProgress` implements `core.progress.Progress`: the store calls it from the worker
  thread, it hands each message to the event loop (`call_soon_threadsafe`) and sets the
  label inside the captured client; `copy_line` rewords and groups figures. Errors are
  shown with `copy_error_message` (`ynab_error_message` for YNAB answers).
- Markers: `token-input`, `check-token`, `token-lost`, `wizard-message`, `wizard-next`,
  `wizard-back`, `budget-{id}`, `loading-accounts`, `accounts-error`, `accounts-retry`,
  `loader-{key}`, `first-copy`, `copy-progress`, `copy-error`, `copy-retry`, `open-yul`.

### 3.3 Other rules

- Views call `core/` and `store/` only. Blocking calls (YNAB, parsing) run through
  `run.io_bound` so the UI stays responsive.
- Uploaded files go to a `TemporaryDirectory` owned by the page; removed on commit or
  discard.
- Import (`views/import_.py`) keeps one `ImportFlow` per tab. Its temporary directory goes
  when the commit ends, on "Import more", when the last file is removed, when the view is
  opened again, or when the client is deleted. Each file is detected on its own
  (`detect_loaders([path])` through `io_bound`). A non `auto` option saved for the loader in
  the config wins over the detected value (the file is parsed again with it). Every option
  of the loader gets a select on the row, starting from the resolved value, so the saved
  defaults can be changed per file. A file of a bank turned off in Settings (`enabled` is
  false) is unsupported with the reason. A loader without an account gets a select of the
  open budget accounts (`state().budget_accounts()`, which also names the account on every
  row, whether or not it has settings); the choice is saved
  to the config when the import is confirmed. Files with nothing new are shown in Done but
  not committed or logged. Files dropped during Review restart the flow, and files dropped
  during the commit are turned away with a toast.
- Settings "Banks" (`views/settings.py`): one card per `LoaderSpec` (`bank_logo`, a switch
  for `LoaderConfig.enabled`, the summary line from `bank_summary()`, a "Settings" button).
  The card is `live` when the bank is on and `off` (muted) otherwise, with no status pill; a
  bank without an entry in `config.loaders` is muted and its summary ("Pick the YNAB account
  its statements go to.") is in `yul-warn`. The button opens a dialog with the account
  select and `option_control` per option; saving writes `loaders[name]` (non default
  options only) and turns a bank on the first time. Turning on a bank that has no account
  opens the dialog. Only the changed card is redrawn. `components.bank_logo(key, title,
  size)` shows `static/logos/<key>.svg` on a white `size` x `2 * size` tile, or the bank's
  monogram when yul ships no logo for that key. Logos follow the rule in DESIGN.md
  (`viewBox="0 0 120 60"`, padding inside the SVG).
- Settings "Accounts" (`views/settings.py`, `AccountCards`): a lede (`accounts-lede`) and
  one card (`account-card-{id}`) per open budget account (`Settings.open_accounts()`, the
  configured ones when YNAB cannot be reached), in a `yul-section` per bucket
  (`bucket-section-{bucket}`; Cash, Savings, Assets, Debt). Each card starts from
  `accounts.account_settings()` with the name and type of the budget. A card has the name
  and a "Counted in net worth" switch (`account-{id}`, `TrackedAccount.counted`, on by
  default; the card is `live` when on, `off` when left out), the bucket as four
  `yul-pill click` pills (group `bucket-{id}`, each `bucket-{id}-{bucket}`) and the
  "balance by hand" pencil toggle (`by-hand-{id}`, `TrackedAccount.track_balance`). Every
  change saves at once (toast "Accounts saved", or "Left out of net worth" / "Counted in
  net worth" for the switch): `config.accounts` keeps the entries of accounts without a
  card and gets one entry per card that differs from `accounts.default_account()`, so an
  account back at its defaults loses its entry. Debt mappings are never touched here. A
  bucket change redraws the sections; the other changes redraw one card.
- Settings "Net worth": the debts and the accounts they can be netted from are the counted
  ones (`effective_accounts` over `open_accounts()`). Saving keeps the mappings of debts the
  tab does not list (left out or closed) and replaces the rest.
- Visual language is DESIGN.md next to this file.
- `local_data.py` lists and deletes what yul stores (config dirs, store, the web
  preferences directory `web.storage_dir()`); `yul config reset`
  and Settings "Reset all data" share it. `utils.budget_from_plan` builds a `Budget`.
- Tests (`tests/web/`): fixtures `guest` (browser without the session) and `user` (with
  the cookie) build the app through `web.app.build` after the config fixtures, with the YNAB
  client stubbed by `ynab_api`. Request fixtures that change the config before `user`.
  `tests.helpers.web.fresh_nicegui()` wraps NiceGUI's global reset, which otherwise unloads
  `ynab_unlinked` from `sys.modules`. `nicegui.testing.user_plugin` is loaded in the root
  conftest (pytest refuses `pytest_plugins` elsewhere) and `pytest-asyncio` runs with
  `asyncio_mode = "auto"`. `guest` also
  gives every test a fresh `AppState` (the module global is reset), so a sync a view
  started in one test cannot leak its task or error into the next. Views that read the
  store are tested by filling it through `Store.sync` with the `ynab_api` stub and
  setting `state().last_sync` (see `seed` in `tests/web/views/test_reconcile.py`).

### 3.5 Reconcile as built (`views/reconcile.py`)

- Reads the store only: `Store.unreconciled` joined with `Store.accounts`, open accounts,
  cards in the store's name order, rows newest first. Before rendering it awaits
  `state().sync()` when `state().last_sync` is None or older than 10 minutes; a failed sync
  toasts and shows what the store has (an error empty state if the store was never synced).
- Scope pills: "since {last_reconciliation_date - 7 days}" (the `yul reconcile -b` default,
  only offered when the config has a date) and "all time". Rows locked in this visit stay
  hidden when the scope changes, even before the background sync catches up.
- Bank balance: `parse_amount_to_milliunits` with the budget's separators. "find the gap"
  highlights rows whose effect on the cleared balance equals the difference (an uncleared
  row counts its amount, a cleared one minus its amount), then pairs (hash lookup, linear)
  when no single row does.
- Lock (per account or all): `shell.confirm`, then `core.reconcile.reconcile` through
  `run.io_bound` with `TransactionDetail`s rebuilt from the stored rows
  (`transaction_detail()`), then `last_reconciliation_date = next_reconciliation_date(locked
  dates, dates of the rows still pending in the current scope)`
  saved through `state().update_config`, `store.log("reconcile", "Reconciled n transactions in m
  accounts", {"count", "accounts": [{"id", "name", "count"}]})`, `sync_in_background()`.
  The store itself is not written by the view. Errors go through
  `onboarding.ynab_error_message` and leave config, log and rows untouched.
- Wording: header "4 accounts · 17 transactions not reconciled", card
  button "Lock n transactions" (DESIGN), footer "Lock n transactions in m accounts" with
  "Deselect all" (or "Select all" when nothing is selected) and "Lock all"; done footer
  "n transactions locked · logged in activity", "Lock k more" when selected rows remain,
  primary "See net worth".
