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
    finance.py           where a period's money came from and went: Flows, Rules, period() (2.8)
    cashflow.py          income and spending by month, category trends and volatility (2.9)
    update.py            a newer yul on PyPI and how this install gets it (2.10)
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
- `uv run poe check` (ruff, format, ty) and `uv run poe cov` must pass before a
  task is done. ty checks `src` with the strict rules of `[tool.ty]`; keep it green.
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
class RowStatus(StrEnum):
    NEW            # sent on commit
    IN_YNAB        # YNAB holds its import id (or the legacy id)
    MATCHED        # YNAB holds it only through a match onto a reconciled transaction
    MAYBE_IN_YNAB  # has a `twin` and the user has not decided: not sent
    EXCLUDED       # in the store's registry of rows left out: never sent

@dataclass(frozen=True)
class Twin:                       # the hand entered transaction a row may already be
    date: dt.date
    payee: str

@dataclass(frozen=True)
class ImportRow:
    transaction: Transaction
    import_id: str
    already_imported: bool        # IN_YNAB or MATCHED
    matched: bool = False
    excluded: bool = False
    twin: Twin | None = None
    anyway: bool = False          # sent although it has a twin, for this plan only
    @property
    def status(self) -> RowStatus: ...    # already_imported, then excluded, then the twin

@dataclass(frozen=True)
class ImportPlan:
    entity_name: str
    account_id: str
    input_file: Path
    rows: tuple[ImportRow, ...]

    @property
    def new_rows(self) -> tuple[ImportRow, ...]: ...     # status NEW only
    @property
    def already_imported_count(self) -> int: ...         # IN_YNAB + MATCHED
    def with_status(self, status: RowStatus) -> tuple[ImportRow, ...]: ...
    def include(self, import_ids: Collection[str]) -> ImportPlan: ...  # excluded=False
    def exclude(self, import_ids: Collection[str]) -> ImportPlan: ...  # excluded=True
    def send_anyway(self, import_ids: Collection[str]) -> ImportPlan: ...  # anyway=True

@dataclass(frozen=True)
class ImportResult:
    created: int
    duplicate_import_ids: tuple[str, ...]

IMPORT_BUFFER_DAYS = 15     # also the `yul load --buffer` default and YnabUnlinkedContext's
MATCH_WINDOW_DAYS = 10      # how far apart YNAB matches an import with a hand entered one

def build_import_plan(
    client: Client, budget_id: str, account_id: str, entity_name: str,
    input_file: Path, transactions: list[Transaction], buffer_days: int = IMPORT_BUFFER_DAYS,
    progress: Progress = NullProgress(), store: Store | None = None,
) -> ImportPlan
    # assigns import ids (models.assign_import_ids), fetches YNAB transactions for the
    # account since min(date) - buffer, marks already_imported by import_id or legacy id.
    # With the budget copy (`store`) also: MATCHED when a live listed transaction without an
    # import id has `matched_transaction_id` pointing at a transaction the copy holds with
    # the row's import id (YNAB writes no import id onto a reconciled transaction it matches,
    # and hides the imported one: 404, left out of listings, only the delta has it), and
    # EXCLUDED for the rows in `store.excluded(budget_id, account_id)`.
    # A match whose imported transaction the copy does not hold (or with no copy) cannot be
    # named: a row YNAB does not hold with the amount of that hand entered transaction, dated
    # within MATCH_WINDOW_DAYS of it, gets it as its `twin` (MAYBE_IN_YNAB, not sent). One
    # row per transaction, the closest in date. It is the only amount and date heuristic,
    # and it never decides alone: the user sends the row anyway or leaves it out.
    # An empty `transactions` returns a plan with no rows without calling YNAB.

def file_digest(input_file: Path) -> str            # SHA-256 of the bytes
def unique_files(files: Sequence[Path]) -> tuple[list[Path], list[tuple[Path, Path]]]
    # each export once, plus (copy, first) for the byte identical ones left out.
    # Import ids are numbered per file (YNAB's own scheme), so an export that overlaps an
    # imported one gives its shared rows the same ids and YNAB rejects them; a second copy
    # in one batch would only be rejected once the first is in, so both frontends drop it.

def commit_import_plan(
    client: Client, budget_id: str, plan: ImportPlan, cleared: TransactionClearedStatus,
    progress: Progress = NullProgress(), store: Store | None = None,
) -> ImportResult
    # creates plan.new_rows, returns created count and the duplicates YNAB rejected.
    # `Client.create_transactions` answers `Created(transactions, duplicate_import_ids)`;
    # the transactions go to `store.save_transactions` at once, so a match made in YNAB
    # before the next sync can still be named. A store that fails only warns on `progress`.
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

def reconcile(
    client: Client, budget_id: str, transaction_ids: Sequence[str],
    progress: Progress = NullProgress(),
) -> None
    # Client.update_transactions(budget_id, ids, RECONCILED) sends only {id, cleared}: an
    # account id read earlier could be stale and move the transaction back. YNAB is not
    # called when there are no ids

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
first every time the view opens, so a match or a delete made in YNAB a moment ago is not
listed; a failed sync shows the last copy with a toast). Both use the same scope rule and
`reconcile()`, so they differ only by what YNAB changed since the last sync.

The app's account card (`web/views/reconcile/card.py`, kept current by `view.py`):

```
header   account name · cleared balance + uncleared balance = working balance
         captions: "cleared balance · N to reconcile" (green dot), "uncleared · N" (amber
         dot), "working balance"; N = rows of that status in the scope chip not reconciled
         yet. They follow the chips, never the "include uncleared" switch or the selection
         right: "Your bank says" input and its match line
rows     (open only) sections, each a header with a dot, a name and a note:
           Cleared     "the bank shows these · N to reconcile"   (or "· none since 29 Oct",
                                                                  "· none" under all time)
           Uncleared   "the bank has not taken these yet · skipped" ("· reconcile them too"
                       with the switch on, "· none ..." when empty)
           Reconciled  "already reconciled": the rows reconciled during this visit, under
                       either scope (the budget copy never lists rows YNAB has as
                       reconciled); no header while there are none
         a row is checkbox · date · payee · amount; no status column
bar      collapsed: one full width button "Show N transactions" (N = every row the card
         lists) and no Reconcile button, so nothing is reconciled unseen.
         open: "Hide transactions" left, "Reconcile N transactions" right (N = selected,
         disabled "Nothing to reconcile" at 0, primary once the bank balance matches),
         "🔒 reconciled" once the account has nothing left
```

On screen it is "reconcile" everywhere (buttons, footer "Reconcile all", confirmation,
progress, toasts); the code keeps `lock` names and the activity kind stays `reconcile`.
Markers: `account-{id}`, `cleared-{id}`, `cleared-count-{id}`, `uncleared-{id}`,
`uncleared-count-{id}`, `bank-{id}`, `match-{id}`, `gap-{id}`, `rows-{id}`,
`section-{cleared|uncleared|reconciled}-{id}` with its `note-...-{id}`, `row-{transaction id}`,
`bar-{id}` (class `open` when open), `toggle-{id}`, `lock-{id}`, and on the page `rec-title`,
`scope`, `include-uncleared`, `scope-empty`, `all-reconciled`, `rec-footer`, `rec-summary`,
`select-all`, `deselect-all`, `lock-all`, `rec-done`, `lock-more`, `see-networth`.

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

class Finances(BaseModel):     # added after V4 shipped, defaults only: no migration
    not_spending: list[str] = []            # category ids whose outflows are set aside
    goal_category_id: str | None = None     # the plan's goal; None: the largest balance target
    returns: dict[str, bool] = {}           # account id -> return followed, where not default

class ConfigV4(BaseModel):
    api_key: str
    budget: Budget
    last_reconciliation_date: dt.date | None = None
    loaders: dict[str, LoaderConfig] = {}       # keyed by Entity.name(), was `entities`
    accounts: list[TrackedAccount] = []
    adjustments: Adjustments = Adjustments()
    debt_mappings: list[DebtMapping] = []
    finances: Finances = Finances()
    check_for_updates: bool = True              # the app asks PyPI for a newer yul; added
                                                # after V4 shipped, default only: no migration
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
def edit_config() -> Generator[LatestConfig]                  # ConfigError without a file
def update_config(change: Callable[[LatestConfig], None]) -> LatestConfig
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
    matched_transaction_id: str | None = None   # the row YNAB merged this one with
    category_id: str | None = None

@dataclass(frozen=True)
class StoredCategory:       # table categories (migration 0006), replaced on every sync
    id: str; name: str; group_id: str; group_name: str
    hidden: bool; internal: bool                # internal: YNAB's own (Ready to Assign...)
    balance: int                                # available this month
    goal_type: str | None = None                # TB, TBD (a balance to reach), MF, NEED, DEBT
    goal_target: int | None = None; goal_target_date: dt.date | None = None
    note: str | None = None

@dataclass(frozen=True)
class Line:                 # a transaction, or one line of a split in its place
    transaction_id: str; account_id: str; date: dt.date; amount: int
    payee_name: str | None; category_id: str | None; category_name: str | None
    transfer_account_id: str | None

STARTING_BALANCE_PAYEE = "Starting Balance"

@dataclass(frozen=True)
class StoredAccount:
    id: str; name: str; type: str; closed: bool; on_budget: bool
    balance: int; cleared_balance: int; uncleared_balance: int

@dataclass(frozen=True)
class SyncResult:
    full: bool; transactions_changed: int; accounts: int; server_knowledge: int
    categories: int = 0                         # categories received
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
        # flagged, replaces the lines of every split received (subtransactions), replaces the
        # budget's accounts (closed kept, deleted skipped) and categories (client.categories,
        # in YNAB's order, deleted skipped), stores the
        # new server_knowledge (never a lower one than stored), all in one SQLite transaction.
        # A 409 on a delta forgets the budget's rows and knowledge and redoes a full fetch once.
        # Then runs the ghost repair and reports it in ghosts_removed: a match approved in
        # YNAB hides the imported row (404) without a delta tombstone, so the rows that share
        # an import id, or point at one through matched_transaction_id, are checked with
        # transaction_exists and the missing ones flagged deleted (50 ids a sync, the rest
        # kept in ghost_checks for the next one).
    def accounts(self, budget_id: str) -> list[StoredAccount]        # sorted by name
    def categories(self, budget_id: str) -> list[StoredCategory]     # YNAB's order
    def lines(self, budget_id: str, *, since: dt.date | None = None,
              until: dt.date | None = None) -> list[Line]
        # non deleted transactions with each split replaced by its lines; they add up to the
        # same balances. since/until inclusive, oldest first. Feeds core.finance.
    def transactions(self, budget_id: str, *, account_id: str | None = None,
                     since: dt.date | None = None, until: dt.date | None = None,
                     cleared: Iterable[TransactionClearedStatus] | None = None) -> list[StoredTransaction]
        # never returns deleted rows; since/until inclusive; oldest first (date, id)
    def unreconciled(self, budget_id: str) -> list[StoredTransaction]   # cleared + uncleared
    def last_sync(self, budget_id: str) -> dt.datetime | None           # aware, UTC; when the
        # sync started fetching, so a write logged during the fetch counts as newer
    def clear(self, budget_id: str | None = None, *, activity: bool = False) -> None
        # forgets the copy (rows, accounts, knowledge); the activity log only with activity=True;
        # the rows left out of imports always stay (deleted with the file by a reset)
    def log(self, budget_id: str, kind: str, message: str,
            details: Mapping[str, Any] | None = None, *, at: dt.datetime | None = None) -> None
        # kinds and their details: section 3.4. `at` (aware) backdates an entry, default now
    def activity(self, budget_id: str, limit: int | None = 20, *,
                 kind: str | None = None) -> list[Activity]
        # newest first; limit None = all; kind keeps one kind only
    def last_activity(self, budget_id: str) -> dt.datetime | None   # when the newest entry was logged
    def import_ids(self, budget_id: str, transaction_ids: Iterable[str]) -> dict[str, str]
        # id -> import id of those transactions, deleted and ghost rows included
    def save_transactions(self, budget_id: str, transactions: Sequence[TransactionDetail]) -> None
        # what an import just created, ahead of the sync; the server knowledge does not move
    def exclude(self, budget_id: str, row: ExcludedRow) -> None      # replaces the same key
    def include(self, budget_id: str, account_id: str, import_id: str) -> bool  # False: not there
    def excluded(self, budget_id: str, account_id: str | None = None) -> list[ExcludedRow]
        # the registry of rows left out of imports, newest row date first
    def last_import_per_loader(self, budget_id: str) -> dict[str, dt.datetime]
        # newest `import` entry per `details.loader`, one GROUP BY query (Home's last imports)
    def daily_amounts(self, budget_id: str,
                      account_ids: Iterable[str] | None = None) -> dict[str, DailyAmounts]
        # per account: its stored balance and the sum of its non deleted transactions per
        # day, in one query (GROUP BY account, date UNION the accounts). Feeds core.history.

@dataclass(frozen=True)
class ExcludedRow:          # table excluded_rows (migration 0005), key (budget, account, import id)
    account_id: str; import_id: str             # import id only, never the legacy id
    date: dt.date; amount: int; payee: str      # milliunits; for showing it only
    excluded_at: dt.datetime | None = None      # set by the store

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
and `transaction_exists(budget_id, transaction_id) -> bool` (False on a 404, other errors raise),
and `categories(budget_id) -> list[CategoryGroupWithCategories]` (GET /categories, every sync),
and `months(budget_id) -> list[MonthSummary]` (GET /months, every sync, deleted left out).

Migration 0006 adds `transactions.category_id` and the `subtransactions` and `categories`
tables, and empties `sync_state`, so the next sync is a full one that fills them in.
Migration 0007 adds `months` (month, note, income, budgeted, activity), replaced on every
sync; `Store.month_notes(budget_id) -> dict[dt.date, str]` gives the months with a note.
Migration 0008 adds `subtransactions.transfer_transaction_id`: YNAB sends the other side of a
transfer made from a split line without a transfer account, so `Store.lines` gives it the
split's account through this column (a full sync fills it in). A full sync flags deleted every row it did
not receive (`_tombstone_missing`), so a delete a delta missed leaves the copy; migration 0009
forces one more full sync for that.

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

def balances_at(store: Store, budget_id: str, account_ids: Sequence[str],
                dates: Sequence[dt.date]) -> dict[str, list[int]]   # at the end of each date
```

### 2.8 Finance (`core/finance.py`)

Every line of a counted account is one kind (`Rules.kind`), and the six add up to the change
of net worth exactly:

| kind | the line |
|---|---|
| `income` | money in to an account on the budget, not a transfer, any category (refunds too) |
| `spending` | money out of an account on the budget, not a transfer |
| `set_aside` | money out in a category of `Finances.not_spending` |
| `assets` | any line of a tracking account that is not a transfer, and a balance adjustment (`adjustment_payees`) of a budget account in `returns` |
| `transfers` | a transfer with another counted account (zero over all of them) |
| `outside` | a starting balance, or a transfer with an account not counted |

```python
@dataclass(frozen=True)
class Flows:                 # milliunits signed as they move net worth
    income, spending, set_aside, assets, transfers, outside: int = 0
    saved (income + spending), other (set_aside + outside), change; supports +

@dataclass(frozen=True)
class Rules:
    on_budget: Mapping[str, bool]          # every counted account -> on the budget
    not_spending: frozenset[str] = frozenset()
    returns: frozenset[str] = frozenset()      # accounts whose return is followed
    adjustment_payees: frozenset[str] = frozenset({RECONCILIATION_PAYEE})
    def kind(self, line: Line) -> str | None   # None: the account is not counted

@dataclass(frozen=True)
class AccountMove:
    account_id: str; start_balance: int; end_balance: int; flows: Flows
    rate: float | None       # modified Dietz return over the period, for followed accounts
    change, own_money (change minus assets)

@dataclass(frozen=True)
class Period:
    start: dt.date; end: dt.date; flows: Flows; start_worth: int; end_worth: int
    months: tuple[tuple[dt.date, Flows], ...]   # every calendar month touched, oldest first
    accounts: tuple[AccountMove, ...] = ()      # largest change first
    spending: tuple[CategorySpend, ...] = ()    # most spent first; refunds do not lower it
    income: tuple[PayeeIncome, ...] = ()        # by payee, most first

def period(store, budget_id, rules, start, end, names=None) -> Period   # blocking
def flows_by_account(lines, rules) -> dict[str, Flows]
def spending_by_category(lines, rules, names=None) -> list[CategorySpend]
def income_by_payee(lines, rules) -> list[PayeeIncome]
def period_return(start_balance, flows, gain, start, end) -> float | None
def annualised(rate, days) -> float          # unchanged for a year or less
def months_between(start, end) -> list[dt.date]; month_start(day); month_end(day)
```

### 2.9 Cash flow (`core/cashflow.py`)

```python
STEADY_BELOW = 0.25; VARIABLE_BELOW = 0.75; LUMPY_SAME_BELOW = 0.25; MIN_MONTHS = 6
HISTORY_MONTHS = 36         # how far back a category's label looks, whatever the range
UNUSUAL_ABOVE = 1.25        # a month this many times its median gets a label

@dataclass(frozen=True)
class Volatility: mean: float; cv: float | None; label: str | None; active: int
def volatility(spent: Sequence[int], months: int | None = None) -> Volatility
    # cv = population stdev / mean over a category's life (its first to its last month of
    # spending, quiet months in between counted as zero). lumpy: spent in at most half of
    # them, those alike (their own cv < 0.25); else steady / variable / spiky by cv. No label
    # when the history holds fewer than MIN_MONTHS months, the life fewer than MIN_LIFETIME,
    # or it spent in one month only. cash_flow() measures it over the complete months of the
    # last HISTORY_MONTHS (the range when that is longer), so a label does not change with
    # the range pills. CategoryTrend.spent and .mean are the range's.

@dataclass(frozen=True)
class Rhythm: charge: float; charges: int; every: float | None    # set_aside = charge / every
def rhythm(spent: Sequence[int]) -> Rhythm     # the charges of a category that spends every
    # so often: the average of the months it spent in, and the months between them

@dataclass(frozen=True)
class FlowMonth: month; income; spending (positive); complete; label: str | None
    saved, rate
@dataclass(frozen=True)
class CategoryTrend: category_id; name; group; spent: tuple[int, ...]; volatility
    past: tuple[int, ...]   # each month of CashFlow.history, what its label was told from
@dataclass(frozen=True)
class CashFlow:
    start; end; months; categories (most spent first); income (PayeeIncome, most first)
    complete, mean_income, median_income, mean_spending, savings_rate, core_spending(), groups()

def cash_flow(store, budget_id, rules, start, end, *, categories=None, notes=None) -> CashFlow
    # blocking; averages over complete months; a label is the month's note in YNAB (first
    # line, 28 characters), else the payee or category most above its usual in a month far
    # above the median
```

### 2.10 Updates (`core/update.py`)

```python
PACKAGE = "ynab-unlinked"; PYPI_URL; CHANGELOG_URL
RESTARTS: bool                     # os.execv replaces the process: POSIX only

class UpdateError(Exception)
class Install(StrEnum): UV_TOOL, PIPX, PIP, SOURCE, UNKNOWN

@dataclass(frozen=True)
class Upgrade:
    install: Install
    command: tuple[str, ...] | None    # None for SOURCE
    automatic: bool                    # yul can run it and restart itself
    shown -> str | None                # the command as one line to read or paste

def is_newer(candidate: str, current: str) -> bool   # final releases only, numbers compared
def latest_version(timeout=CHECK_TIMEOUT) -> str      # GET PYPI_URL; UpdateError
def upgrade_plan(*, web: bool) -> Upgrade
def installed_version() -> str                        # asked to a new interpreter
def run_upgrade(upgrade, current, timeout=UPGRADE_TIMEOUT) -> str   # the version installed
def restart_command(arguments) -> list[str]           # [sys.executable, "-m", "ynab_unlinked", ...]
```

- The check sends nothing about the user: one GET of a public document, no body, no
  identifying header. Only the web app asks, and only while `config.check_for_updates`.
- `upgrade_plan` reads the running environment, in this order: a `direct_url.json` in yul's
  metadata is `SOURCE` (a checkout, a local wheel, a repository: never upgraded);
  `uv-receipt.toml` in `sys.prefix` is `uv tool upgrade ynab-unlinked`; `pipx_metadata.json`
  is `pipx upgrade ynab-unlinked` (both tools remember the extras); a virtual environment
  with pip is `<sys.executable> -m pip install --upgrade 'ynab-unlinked[web]'` (the extra
  only with `web=True`); anything else is `UNKNOWN` with a pip line to run by hand.
  `automatic` needs `RESTARTS` and, for uv and pipx, the tool on the PATH.
- `run_upgrade` raises `UpdateError` with the last `OUTPUT_LINES` lines the command printed
  when it fails, and when it worked but the version on disk is not newer than `current` (an
  install pinned to a version): the app never restarts into the same yul.

## 3. Web app (`web/`, extra `web`)

```
web/
  __init__.py          nothing heavy: available() (find_spec, never imports NiceGUI),
                       storage_dir() (user data dir / "web": browser prefs and their secret)
  app.py               build(token, port) -> root page (guard, static files, CSS, views, /onboarding);
                       run(port: int | None, open_browser: bool, announce=None), which becomes
                       the upgraded yul once an update stopped the server (3.1)
  update.py            Updates / updates(): latest, available, failed, updating, restarting,
                       due(now=None), check() (shared, never raises), update(upgrade) ->
                       version installed, restart(); CHECK_EVERY (24 h), RETRY_AFTER (1 h)
  update_dialog.py     update_button() (the sidebar's, each tab looks every LOOK_SECONDS and
                       runs a due check), update_dialog(), out_line(version)
  state.py             AppState / state(): config, client, store, formatter, loaders, last_sync,
                       data_version (goes up when a sync changed the copy), sync_if_stale()
                       (a copy older than AUTO_SYNC_AFTER, 10 min, syncs on its own)
  attention.py         pure: waiting(store, config, today) -> Waiting(unreconciled,
                       unreconciled_accounts, stale): Home's "Needs you" and the sidebar's badges
  palette.py           pure: Command, search(commands, query, limit=LIMIT) (every word, no case
                       or accents, best first), budget_commands(store, config) (a command per
                       category and per counted account)
  palette_dialog.py    PaletteDialog(static, actions): the command palette, one per tab
  ranges.py            saved_range(default) / save_range(key): the range of the finance pages,
                       one for all of them, in app.storage.user (`yul.range`)
  categories.py        pure: Group, grouped(categories) (the user's, by group, YNAB's order),
                       matching(groups, text) (every word, no case, accents or emoji),
                       balance_goals(), goal_category(categories, chosen), BALANCE_GOALS
  accounts.py          effective_accounts() / history_accounts() (closed ones too, for the
                       history and the Months and Movers tabs) / follows_return() /
                       by_hand_accounts() / effective_nettings():
                       what Home, Net worth and Settings count (3.4.1); last_set_by_hand(), STALE_AFTER_DAYS
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
                       CASHFLOW_PATH, SPENDING_PATH, SETTINGS_PATH, ONBOARDING_PATH),
                       NiceGUI-free for the data modules
  finances.py          pure: RANGES, RANGE_MONTHS, months_range (whole months), period_title,
                       rules(config, stored) (closed accounts too), category_names, earliest,
                       load_cash_flow, liquid (cash and savings after debt), runway_months,
                       previous_range
  shell.py             what views use from the layout: view and command registries, page(),
                       set_header, refresh_view / on_refresh, toasts, confirm dialog, drop
                       handoff, save_config(); re-exports the paths (views use
                       shell.<NAME>_PATH) and sync_label / sync_message
  frame.py             root(): the sidebar (entries, badges, the version and the update
                       button), the top bar (search, budget and sync chips, theme, Import),
                       the content column, the tab's tick
  sync_chip.py         sync_chip(notify, refresh_view) -> the sync it runs on a click: the top
                       bar's sync chip, sync_label, sync_message
  theme.py             THEMES (the palettes), the palette choice and dark/light per browser,
                       chart palettes, page_setup(), install() of static/yul.css
  security.py          per run token, TokenGuard middleware, free_port(), entry_url(),
                       hand_over(token) / inherited_token() (the token across a restart)
  static/              yul.css: the only stylesheet (tokens, base, shared classes, one section
                       per view, motion, then every media query), fonts/InterVariable.woff2.
                       No CSS lives in Python.
  components/          button, glass_card, pill, bank_logo, stat_tile, segmented_bar, share_bar,
                       empty_state, spinner, check, closed_pill, icon (+ ICONS), count_up (the one count up
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
    flow_chart.py      months_options(months, palette, currency_format, selected=None),
                       months_chart(..., on_pick(index), selected=None): Net worth › Months'
                       stacked bars, net line, a transparent column per month for clicks
                       bridge_options(steps, labels, palette, currency_format) / bridge_chart:
                       the period panel's waterfall
    cashflow_chart.py  income_spending_options, rate_options, volatility_options,
                       category_months_options (bars and a dashed Average line),
                       histogram_options (slanted whole unit slices), chart(): the charts of
                       Cash flow and Spending
    category_picker.py category_picker(groups, on_pick, *, label, marker): a button opening
                       a menu of groups and categories with a search field on top
  views/
    __init__.py        register(): imports every view module
    onboarding/        /onboarding, outside the shell (token, budget, banks, done)
      data.py          STEPS, TOKEN..DONE, CopyState, AccountOption
      progress.py      LineProgress: the copy's progress on one label, from any thread
      view.py          Wizard and page()
    Every view with data to shape is a package: data.py is pure (no NiceGUI, not even
    through its imports: web.accounts, web.buckets, web.paths, web.wording are NiceGUI-free)
    and unit testable; the other modules draw; __init__ holds the docstring only.
    home/              /            hero, needs you, import (drop zone, last imports); aside the
                                    month so far, where it went, activity (3.4.2). pulse.py is
                                    pure (MonthPulse, load_pulse), month.py draws its two cards
      data.py          LoaderDue, HomeData, load_home, relative_time, last_imports_line,
                       message_markup, Attention, attention_items
      view.py          the page (hero with count_up, spark_options, activity, banner)
    import_/           /import      Files -> Review -> Done on core.detect and core.importing
      data.py          Status, ImportFile, same_file, mark_repeated, take_candidate,
                       account_label, problem_text, option_choices, read_file,
                       chosen_accounts, done_summary, import_log, left_out_count,
                       held_count, excluded_row, STATUS_LABELS, STATUS_MEANINGS,
                       statuses_shown, twin_note
      view.py          ImportFlow (lifecycle, detection, the three steps, leave out / include /
                       import anyway, commit and log) and the view
      rows.py          draw_row(flow, item): a file row of step Files and its body
      tables.py        badge, status_legend(plans), plan_table(plan, formatter, key,
                       actions=None), RowActions, transactions_table
      cards.py         files_footer, review_footer, review_card, progress_card -> Progress, done_card
    cashflow/          /cashflow    tiles, income and spending, savings rate, came in from
      data.py          DEFAULT_RANGE, CashFlowPage, load, percent, rate_change, runway,
                       runway_text, spending_hint, complete_note
      view.py          CashFlowView and the view
    spending/          /spending    tiles, by group, steady or swingy, categories
      data.py          DEFAULT_RANGE, SHOWN, WORDS (Word: text, pill kind, hint), ORDER,
                       UNRATED, load, word, spark, share, matches, filtered, MixPart,
                       group_mix, plotted (the chart's dots, in order), Bin, histogram, Life
                       (months, spent), life, Stats, stats
      view.py          SpendingView (filters redraw only what they change, legend, clicks,
                       the detail in the chart's card) and the view
      detail.py        category_detail(trend, flow, *, palette, currency_format, formatter,
                       on_back)
    reconcile/         /reconcile   per account cleared vs bank balance, reconcile (2.3)
      data.py          scope_start, gap_candidates, ReconcileData (read,
                       open_transactions, has_anything), LOCK_TIMED_OUT, UNCLEARED_SKIPPED,
                       parse_bank_balance, cleared_note, uncleared_note, show_label,
                       reconcile_label, lock_confirmation, lock_log, lock_checkpoint,
                       pending_title
      groups.py        Row, AccountGroup: the selection and the elements that show it
      card.py          equation, section, bar, paint_bar: the account card's fixed pieces
      view.py          ReconcileView (with the reconcile: confirm, reconcile, log, checkpoint) and the view
      footer.py        selection / done / locking footers
    networth/          /networth    tabs Overview (history chart, buckets, accounts, balance
                                    updates, drawer), Months (chart and period panel) and Movers,
                                    from one core.finance.Period
      data.py          RANGES, MAX_PICKED, range_start, by_hand_pill, assign_slots,
                       Snapshot, load_snapshot, table_order, default_picked, parse_balance,
                       set_balance / set_balances (the one write: live balances, build and
                       create the adjustments in one batch), adjustment_entry (the activity
                       entry), plain_amount, Drafts, read_drafts, diff_label, changed_count,
                       save_label (the "Update balances" fields, their changes and footer)
      flows.py         pure: TABS, RANGE_MONTHS, months_range (whole months), rules, load_period,
                       period_title, Step / bridge, why, moved, rate_text, months_up,
                       best_month, month_bounds, share_of_change, spread
      view.py          NetWorthView (tabs, hero, ranges, chips, buckets, drawer loading) and the view
      periods.py       PeriodTabs (draws Months or Movers, the selected month and its panel,
                       restyles), months_tab, movers_tab
      period_panel.py  period_panel(period, names, closed, formatter, *, selected, on_clear):
                       the bridge, accounts, came in from, spent most on
      table.py         AccountsTable: the accounts card, its inline balance editor and the
                       "Update balances" mode
      drawer.py        account_drawer(...) -> its chart
    settings/          /settings    one module per tab, each with render(page: Settings):
      __init__.py      Settings (tab row, panel, rerender()), TABS, RENDERERS, tab_from_slug, the view
      common.py        current_config(), kv(key), all_accounts() (closed ones too), open_accounts() (open budget accounts, the
                       configured ones when YNAB cannot be reached)
      connection.py    token (reveal, check and save), budget dialog and switch
      banks.py         bank cards, bank_summary(), shared_account_hint(), toggle_bank(),
                       bank_dialog(), option_control()
      accounts.py      AccountCards (the Accounts tab), BY_HAND_HINT
      networth.py      debt mappings (mapping_row), the goal (goal_section) and adjustment
                       settings, CLEARED_LABELS
      categories.py    Categories: RULES (how income and spending are read), "not spending"
                       chips and their picker; each change saves at once
      appearance.py    Appearance: a card per palette with its preview; a click saves and applies
      privacy.py       Data & privacy: what is kept where, the look for new versions (switch,
                       "Check now", update_line(status)), resync, reset; token_wording()
      left_out.py      the rows left out of imports under Data & privacy, "Include again"
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

- **Updates.** Each tab's `update_button()` asks `updates().due()` and runs `check()`; the
  button shows while `available` is set. `update_dialog()` shows `upgrade_plan(web=True)`:
  one line (`CONFIRM`) and "Update and restart" when `automatic`, otherwise the command to
  run by hand. The command never shows on the confirmation, only where the user must run it.
  `Updates.update()` runs `run_upgrade` off the event loop; on success `restart()` sets
  `restarting` and calls `app.shutdown()`. `run()` then, after `ui.run` returned, waits for
  NiceGUI's worker pool (a write to YNAB in flight ends first), calls
  `security.hand_over(token)` and `os.execv`s `restart_command(["app", "--port", <port>,
  "--no-browser"])`. The new run takes the token with `inherited_token()`, so the cookie the
  open tabs hold is still good; NiceGUI reloads a tab that reconnects to a server that does
  not know it. The token crosses in a pipe whose reading end survives the exec, named by
  `YUL_SESSION_FD`: never in the command line, the environment or a file. `inherited_token`
  only reads a pipe.

### 3.2 Shell contract for views

The app is a single page: `frame.root()` renders the sidebar (232px, collapsible to a 64px
rail from its last entry, state in `app.storage.user`), the top bar and the drop overlay
once per tab, and `ui.sub_pages` swaps the content in a column centered in the main area
(`.yul-views`, max 1360px). Every path but `/onboarding` redirects to `/onboarding`
until `state().configured`; `/onboarding` redirects to `/` once it is. A path without a
view draws `not-found` (a way home), and a view whose builder raises draws `page-error`
("Try again" rebuilds it): the sidebar and the top bar stay. The browser tab is named
`<title> · yul`.

Each tab ticks every `frame.TICK_SECONDS` (2s, and once on load): `state().sync_if_stale()`
starts a sync when the copy is older than ten minutes, and when `state().data_version`
moved (a sync changed the copy) it counts the sidebar's badges again
(`nav-badge-reconcile`: transactions to reconcile, `nav-badge-networth`: balances set by
hand gone stale; hidden at zero) and calls `shell.refresh_view(automatic=True)`.

```python
from nicegui import PageArguments, ui
from ynab_unlinked.web import shell, theme
from ynab_unlinked.web.components import (
    button,
    glass_card,
    pill,
    stat_tile,
    Segment,
    segmented_bar,
    empty_state,
)
from ynab_unlinked.web.state import state


@shell.view(
    "/networth",
    key="networth",
    title="Net worth",
    subtitle="All your accounts in one figure",  # str or Callable[[], str]
    icon="networth",  # key of components.ICONS
    order=40,  # bottom=True puts it under the spacer, live=False for views with forms
    group="Finances",  # the sidebar heading above it
)
async def networth_view(args: PageArguments) -> None:  # the parameter is optional
    ...  # already inside shell.page(title, subtitle): just render the body
```

- Re-registering a path replaces the view (agents replace the placeholder bodies in place).
- `shell.page(title, subtitle, key=None)`: context manager that sets the top bar and yields
  the content column; `@view` builders already run inside it.
- `shell.set_header(title=None, subtitle=None)`: change the top bar later.
- `shell.refresh_view(automatic=False)`: draw the current view again when it is `live`
  (the default). The sync chip calls it after a sync that brought changes, the tab's tick
  with `automatic=True` after any other sync that did; Import and Settings (`live=False`)
  keep what the user is editing.
- `shell.on_refresh(owner, handler=None, *, automatic=True)`: how the view on screen is
  drawn again while `owner` exists. `handler` replaces the rebuild, so the view keeps what
  the user set: Cash flow and Spending pass their `render` (range, filters, the open
  category), Net worth a no-op (its own tick follows the sync and keeps tab, range and
  selection). `automatic=False` leaves the view alone after a sync nobody asked for:
  Reconcile, where balances are typed.
- `shell.command(key, title, path, *, icon, hint="", keywords="")`: a place in the command
  palette that is not a page: Net worth's Months and Movers, every Settings tab. Pages are
  in it already (`shell.commands()` adds the actions `sync`, `theme`, `sidebar`). Tabs,
  categories and accounts are `quiet`: found by typing, not listed before.
- Command palette (`palette_dialog.PaletteDialog`): opened by `open-palette` (the top
  bar's search button), ⌘K / Ctrl+K or "/" outside a field (`theme.KEYS_JS` emits
  `yul-palette`). Markers: `palette`, `palette-input`, `palette-results`,
  `palette-<command key>` (class `on` on the one Enter runs), `palette-none`. A category is
  `category-<id>` (-> `/spending?category=<id>`), an account `account-<id>`
  (-> `/networth?account=<id>`).
- `shell.notify(message, kind="ok" | "info" | "warn" | "error")`: `ok` and `info` go to the
  top bar's status line (markers `status`, `status-text`; 4s, put away by `shell.hush` on
  the frame's timer); `warn` and `error` are toasts at the top, centered, 6s. Outside the
  shell (onboarding) every kind is a toast.
- `components.info_button(title, lines, marker=)`: an "i" opening a note (`<marker>-note`)
  for what a figure means. `wording.VERSUS_YNAB` (why income and spending can differ from
  YNAB's reports) sits next to the month on Home (`month-info`) and the period title of
  Cash flow (`cf-info`) and Spending (`sp-info`).
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
  `net-worth`, `categories`, `appearance`, `data`, `privacy` or `data-privacy`, case
  insensitive) opens that tab;
  anything else opens Connection (`settings.tab_from_slug`). `/networth?tab=months` (or
  `movers`, `overview`) opens that Net worth tab, `/networth?account=<id>` the Overview
  with that account's drawer, `/spending?category=<id>` Spending on that category's months
  (the chart when the range does not have it). A click on a tab of Net worth or Settings
  puts it in the address (`ui.navigate.history.replace`), so a reload opens it again.
- The finance pages share one range: `ranges.saved_range(default)` on build,
  `ranges.save_range(key)` on a pill, so a range picked on Cash flow is Spending's and
  Net worth's, and the one the next visit opens with.
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
`#eda100`, a violet and a pink; `--series-1..6` in CSS), `GOOD`, `WARN`, `BAD` (+ `_LIGHT`).
`THEMES` maps a name to its `Theme(name, title, description, dark, light)`, in the order
Settings › Appearance shows them (midnight, twilight, graphite, aurora); each `Variant` holds
the chart accent (start, end) and `--accent-solid`; `theme.css_class` is `yul-theme-<name>`,
whose token blocks live in `static/yul.css`. Per browser, in `app.storage.user`:
`yul.palette` (the palette name, `current_theme()` / `save_theme_choice(theme)`, Midnight,
`DEFAULT_THEME`, when missing or unknown) and `yul.theme` (`dark` or `light`, `is_dark()` /
`save_theme(dark)`). `palette()` is the `Palette` (series, accent, status and text colours
for ECharts) of the current palette and variant, `palette_for(theme, dark)` that of any.
`page_setup()` (every page: the shell and onboarding) puts the palette's class on `<body>`
through `apply_theme(theme)` (`ui.query("body")`, removing the other palettes' classes; the
Appearance tab calls it on a click), sets Quasar's primary to `var(--accent-solid)` and
returns the `ui.dark_mode`. Charts drawn on the server take their accent from `palette()`:
Home's sparkline on render, Net worth on render and on its 1s tick when the palette or the
variant changed. CSS classes are prefixed `yul-` (`yul-card`,
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
| `import` | `Imported {plural(created, "transaction")} to {account_name} from {file}`, plus ` · {excluded} left out` when excluded > 0 (`text.import_message`) | `loader` (config key), `account_id`, `account_name`, `file`, `created`, `duplicates`, `skipped` (already in YNAB, matched included), `matched`, `excluded`, `held` (may be in YNAB, not sent) |
| `exclude` | `Left {payee} ({amount}, {date}) out of imports to {account_name}` | `account_id`, `account_name`, `import_id`, `date` (ISO), `amount` (milliunits), `payee` |
| `include` | `Included {payee} ({amount}, {date}) in imports to {account_name} again` | as `exclude` |
| `reconcile` | `Reconciled {count} transactions in {n} accounts` | `count`, `accounts: [{id, name, count}]` |
| `adjustment` | `Balance of {account_name} set to {new} ({signed amount})` | `account_id`, `account_name`, `old`, `new`, `amount` (milliunits) |
| `sync` | `Synced · {changes} changes from YNAB`, plus ` · {ghosts} stale removed` when ghosts > 0 | `changes`, `full`, `ghosts` (only when > 0) |
| `config` | free text | free |

Amounts in messages are formatted with `state().formatter`; in details they are milliunits.
`exclude` and `include` come from `web.wording.left_out_entry`, logged by the Import review
and Settings › Data & privacy after the registry write, both through `run.io_bound`.
The CLI writes `import` (after each committed file of `yul load <bank>` and `yul load auto`)
and `reconcile` (after `yul reconcile` locks) with the same shapes through
`ynab_unlinked.activity`, at `store_path()`; a store it cannot open only warns. The app's
next sync brings the transactions.
Use singular nouns for 1 ("1 change"). `AppState._sync` logs `sync` only when the sync was
full, brought changes or removed ghosts (one runs at every start). Home reads: the newest
`reconcile` (hero change since), the newest `import` per `details["loader"]` (the last
imports line, 3.4.2) and the newest `adjustment` per `details["account_id"]` (when a balance
kept by hand was last set, with the transactions carrying the payee or the memo of the
adjustment settings: `web.accounts.last_set_by_hand`, which Net worth's age pill uses too, so a settings change does not hide older ones). It ignores `config` entries. Home has no setup card: every open
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
def logged_adjustments(store, budget_id) -> dict[str, date]   # newest `adjustment` entry's day
def last_set_by_hand(transactions, settings: Adjustments, logged: date | None) -> date | None
    # newest adjustment (payee or memo of the settings, or logged), else newest transaction:
    # Home's stale card and Net worth's age pill
```

Home, Net worth and the Settings Net worth tab read through these. A mapping that names a
left out or closed account is kept in the config; `net_worth` skips targets it does not
count.

### 3.4.2 Home

`load_home(store, config, loaders, today) -> HomeData` reads everything once per visit
through `run.io_bound`; Home never calls YNAB.

```python
@dataclass(frozen=True)
class LoaderDue:  # one bank of the last imports line
    name: str  # config key (LoaderSpec.name)
    key: str  # loader key, for the logo
    title: str  # LoaderSpec.title
    last: date | None  # newest import (Store.last_import_per_loader), None if never


@dataclass(frozen=True)
class HomeData:
    net_worth: int  # milliunits, tracked accounts with debt netted
    delta: int  # change since `since`
    since: date  # last reconcile, or 30 days ago
    spark: list[Point]  # 90 days of net worth
    unreconciled: int  # cleared, not reconciled, open accounts
    unreconciled_accounts: int
    stale: list[str]  # accounts set by hand older than 30 days
    last_imports: list[LoaderDue]  # banks turned on in Settings, registry order
    activity: list[Activity]  # newest 10
    pulse: MonthPulse | None  # the month so far (home/pulse.py); None without accounts
    every_account: bool = False  # nothing tracked: hero says "every open account"
```

`pulse.load_pulse(store, config, today) -> MonthPulse`: the running month (`income`,
`spending`, `saved`, `day` of `days`) against the complete months of the last year
(`usual_income`, `usual_spending`, `months`, `savings_rate`, `runway` as Cash flow counts
them) and `top`, the five categories that spent most this month, each with its `usual`
month. `pace_line(pulse)` is "64% of a usual month's spending, 33% of the month gone".
The unreconciled count and the stale balances are `attention.waiting`'s.

`attention_items(data) -> list[Attention]` gives the "Needs you" cards in display order:
`unreconciled` (-> `/reconcile`) and `stale` (-> `/networth`); nothing else. The
sync problem before the first sync stays the banner above the grid (`first-sync`).
`last_imports_line(data, today)` is `"Last imports · Cobee never · Sabadell 12 Oct"`
(`today`, `yesterday`, `N days ago` under 14 days, then `short_date`), `None` without banks.

Markers: `home` (grid), `first-sync`, `hero`, `net-worth`, `net-worth-delta`, `sparkline`,
`home-import`, `dropzone`, `last-imports`, `needs-you`, `attention` (the card grid, only
when there are cards), `attention-unreconciled`, `attention-stale`, `nothing-waiting`,
`activity`, `activity-item`, `activity-message`, `activity-empty`, `month-pulse` (the month
card), `month-pace`, `month-rate`, `month-runway`, `month-top` (where it went),
`month-top-{category_id}` (a row, -> that category in Spending).

### 3.5 Markers of the other views

#### Updates

Sidebar: `version`, `update` (the button, hidden until a newer yul is known). Dialog:
`update-dialog`, `update-confirm`, `update-command` (by hand or after a failure only), `update-changes`, `update-by-hand` (an install yul cannot
update), `update-cancel`, `update-run`, `update-running`, `update-done`, `update-failed`,
`update-output` (what the command printed), `update-close`.

#### Net worth

Tabs: `nw-tabs`, `nw-tab-{overview|months|movers}`. Months: `tile-change`, `tile-saved`,
`tile-assets`, `tile-months-up`, `months-chart` (its `componentClick` picks a month: a series
point by `dataIndex`, or the x axis by `value`, the month as `YYYY-MM`), `other-note`,
`months-tab` (hears `theme.OUTSIDE_EVENT`: `theme.OUTSIDE_JS` sends it to every element with
`OUTSIDE_PROP` for a click outside the elements with `KEEP_PROP`, here the chart and the
panel, and the picked month goes back to the whole range). Period
panel: `period-panel`, `period-title` and `period-clear` (a picked month only), `bridge`,
`step-{income|spending|assets|other|net}`, `moved-{account_id}`, `came-in`, `spent-on`.
Movers: `movers`, `mover-{account_id}`.

Markers: `no-tracked`, `pick-{account_id}`, `pick-count`, `edit-{account_id}`,
`balance-input-{account_id}`, `accept-{account_id}`, `cancel-{account_id}`,
`balance-hint-{account_id}`; the "Update balances" mode: `update-balances`,
`cancel-balances`, `balance-{account_id}` (the field of a by hand row), `delta-{account_id}`,
`balances-foot`, `balances-count`, `save-balances`.

The mode saves through `data.set_balances`: one live balance read per changed account, one
`create_adjustments` call for the batch (YNAB saves all of it or none), then one `adjustment`
entry per adjustment (3.4, no batch kind), `state().invalidate()` and the toast "Updated N
balances". The deltas in the rows are the confirmation of rule 8; there is no dialog. A
failure keeps the mode and what was typed. What was typed lives in `AccountsTable.typed` (by
account id), so a re-render after a sync keeps it.

#### Cash flow and Spending

Cash flow: `range-{key}`, `cf-income`, `cf-spending`, `cf-rate`, `cf-runway`, `cf-chart`,
`cf-rate-chart`, `cf-sources`, `cf-empty`. Spending: `range-{key}`, `sp-total`, `sp-core`,
`sp-one-offs`, `sp-groups`, `sp-mix-key`, `group-{name}` (a click filters, again clears),
`mix-{name}`,
`sp-scatter` (its `componentClick` by `dataIndex` shows a category), `sp-legend`,
`word-{steady|variable|spiky|lumpy}` (a click filters), `sp-group-filter` (a select:
`__all__` or a group name), `sp-word-clear`, `sp-categories`, `category-{category_id}`
(`category-none` for uncategorized; a click shows it), `sp-no-match`, `sp-show-all`,
`sp-empty`. Category detail: `category-detail`, `detail-back`, `detail-title`,
`detail-word`, `detail-figure`, `detail-set-aside` (a lumpy category), `detail-chart`,
`detail-stats`, `detail-histogram` (not for a lumpy one); `sp-so-far` (the range is the
running month), `sp-dot-key`.
Sidebar: `nav-group-finances` above `nav-networth`, `nav-cashflow`, `nav-spending`.

#### Onboarding

Markers: `token-input`, `check-token`, `token-lost`, `wizard-message`, `wizard-next`,
`wizard-back`, `budget-{id}`, `loading-accounts`, `accounts-error`, `accounts-retry`,
`loader-{key}`, `first-copy`, `copy-progress`, `copy-error`, `copy-retry`, `open-yul`.

#### Settings

Markers: `tab-{slug}` (the tabs, a list down the side), `settings-panel`, `settings-title`
(the open tab's name), Data & privacy's updates: `check-updates` (the switch),
`update-status`, `check-now`, `settings-update` (only with a newer yul), `bank-shared-{key}`, `accounts-lede`, `account-card-{id}` (class `closed` on a closed
account, tagged `closed-{id}`), `bucket-section-{bucket}`,
`account-{id}`, `bucket-{id}`, `bucket-{id}-{bucket}`, `by-hand-{id}`, `left-out` (the list
of rows left out of imports), `left-out-{index}`, `include-again-{index}`, `left-out-empty`;
Appearance: `tab-appearance`, `themes` (the card grid), `theme-{name}` (a palette's card,
`live` when chosen). Categories: `category-rules`, `no-categories`, `not-spending`,
`not-spending-{id}`, `spending-again-{id}`, `add-not-spending` (a category picker). Net
worth goal: `goal`, `goal-current`, `pick-goal` (a category picker), `goal-default`,
`no-goal`. Net worth return: `returns`, `return-{account_id}` (`aria-pressed` on or off).
A category picker's search field is marked with the picker's marker and -search after it,
each category row with the marker, a dash and the category id.

#### Import

Review rows: `row-status-{file key}-{index}` (new, may be in YNAB, already in YNAB, matched in
YNAB, left out; every one a pill), `leave-out-{file key}-{index}` on a new row,
`include-{file key}-{index}` on a row left out, `review-left-out-{file key}` and
`review-left-out` (footer) when rows are left out. A row that may be in YNAB has
`row-twin-{file key}-{index}` (the transaction it looks like), `import-anyway-{file key}-{index}`
and `leave-out-{file key}-{index}`; they are counted in `held-{file key}` and `files-held`
(Files), `review-held-{file key}` and `review-held` (Review). `status-legend` above the rows
(Review: once, over the cards; Files: in a file's body) holds `legend-{RowStatus value}` for
each status on screen.
