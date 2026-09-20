## Running tests

To run tests, run them throught the `dev` hatch environment:

```bash
hatch run dev:cov
```

It also support passing arguments as you would do with pytest:

```bash
hatch run dev:cov -k test_name
```

## Writing tests

Tests are written using the `pytest` framework. Make use of the `pytest` parameterization whenever possible to reduce the number of tests to be written.

If you need to have files to read at some point, you can use store them in the `tests/assets` directory. You can read them using the `assets` module in the `tests/helpers` directory.

## Working with timing

Some tests require to work with the current date. To do so, you can use the `today` fixture in the `tests/conftest.py` file. This uses the `freezegun` library to freeze the time to the date provided in the fixture.

```python
def test_something(today: datetime.datetime):
    assert today == datetime.datetime.now()
```

## What a test must do

A test exists to catch a regression in *our* logic. Before writing one, ask what bug it would
catch. If the answer is "none", do not write it.

Never write tests that:

- Assert that a constructor stored its arguments, that a dataclass or pydantic model round-trips,
  or that an enum has its members. That tests the language or the library, not this project.
- Call a function and assert it returned without checking the result.
- Mirror the implementation line by line (asserting the same arithmetic the code performs).
- Mock the very function under test, so the assertion is about the mock.
- Exist only to raise the coverage number. Uncovered lines are a hint of missing behaviour
  tests, not a target in themselves.

Prefer tests that pin down behaviour at a boundary: parsing real-looking input, a matching
decision with a near-miss, an error path a user can hit, a CLI invocation end to end with the
YNAB client stubbed (`ynab_api` fixture).

## Comments

Comments must earn their place. Do not narrate what the code already says (`# create the
parser`, `# assert the result`). Write a comment only for a non-obvious *why*: a bank quirk,
a regression being pinned, a workaround. Test names carry the intent; keep them descriptive.

## Layout and reuse

- The `tests` tree mirrors `src/ynab_unlinked`: `src/ynab_unlinked/pkg/mod.py` is tested from
  `tests/pkg/test_mod.py`. When a test file grows large, split it into a subpackage named after
  the module (`tests/pkg/mod/test_concern.py`) even though `src` has no such package.
- Reuse what exists before writing anything new: fixtures in `tests/conftest.py` (`yul`, `config`,
  `context_obj`, `today`, `ynab_api`), stubs and readers in `tests/helpers/`, factories in
  `tests/factories.py`. Do not re-implement a runner, a stub, or object construction in a test
  module.
- Prefer one parametrized test with descriptive `ids` over several tests that differ only in
  inputs and expected outputs.

## Fixtures and helpers to reach for

- `config_files` (root conftest) points every config path into a scratch directory and returns
  the `ConfigFiles` paths. `config` writes the asset for `@pytest.mark.version("V1"|"V2")` there
  and yields the version; `"missing"` leaves it empty. `config_v2` loads it as a `ConfigV2`.
  Tests may save, migrate and reset freely; the assets under `tests/assets/config_*` are never
  written to.
- `yul` runs the CLI (`yul("load --show test", input="y\n")`); `ynab_api` stubs the YNAB client
  with one MagicMock per API (`ynab_api.api("transactions")`); `load_entity` registers a stub
  entity as `yul load test`; `today` freezes time to 2025-05-15.
- `tests/factories.py` builds domain and SDK objects: `TransactionFactory`,
  `TransactionWithYnabDataFactory`, `TransactionDetailFactory`, `AccountFactory`, `PayeeFactory`,
  `PlanDetailFactory`. Extend a factory rather than constructing these by hand in a test.
- `tests/helpers/statements.py` holds the bank statement builders and, run as a script,
  regenerates the binary fixtures under `tests/assets/{parsers,bbva,sabadell,cobee}`.
- `isolated_migration_registry` (tests/config) gives a test its own `MigrationEngine` registry.
- Textual apps are driven with `asyncio.run()` around `app.run_test()`; see
  `tests/commands/apps/reconcile/harness.py` for the button and row helpers.
