## Running tests

To run tests with coverage, run the `cov` task through uv:

```bash
uv run poe cov
```

It also support passing arguments as you would do with pytest:

```bash
uv run poe cov -k test_name
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
  `tests/pkg/test_mod.py` (the CLI from `tests/cli/`, its commands from `tests/cli/commands/`). When a test file grows large, split it into a subpackage named after
  the module (`tests/pkg/mod/test_concern.py`) even though `src` has no such package.
- Reuse what exists before writing anything new: fixtures in `tests/conftest.py` (`yul`, `config`,
  `context_obj`, `today`, `ynab_api`), stubs and readers in `tests/helpers/`, factories in
  `tests/factories.py`. Do not re-implement a runner, a stub, or object construction in a test
  module.
- Prefer one parametrized test with descriptive `ids` over several tests that differ only in
  inputs and expected outputs.

## Fixtures and helpers to reach for

- `yul_home` (root conftest, autouse) sets `YUL_HOME` to a folder under `tmp_path` for every
  test, so no test reaches the real config, budget copy, preferences or keychain item, even
  without the fixtures below. `keychain.service_name()` follows it; never cache it.
- `config_files` (root conftest) points every config path into a scratch directory and returns
  the `ConfigFiles` paths. `config` writes the asset for `@pytest.mark.version("V1".."V4")` there
  and yields the version; `"missing"` leaves it empty. Use `"V4"` (the latest) unless the test is
  about migrations. `config_v4` loads it through `get_config()`; `config_v3` reads it as a
  `ConfigV3` without migrating.
  Tests may save, migrate and reset freely; the assets under `tests/assets/config_*` are never
  written to.
- `yul` runs the CLI (`yul("load --show test", input="y\n")`); `ynab_api` stubs the YNAB client
  with one MagicMock per API (`ynab_api.api("transactions")`); `load_entity` registers a stub
  entity as `yul load test`; `today` freezes time to 2025-05-15.
- `tests/factories.py` builds domain and SDK objects: `TransactionFactory`,
  `PendingImportFactory`, `ImportRowFactory`, `TransactionDetailFactory`, `AccountFactory`,
  `PlanDetailFactory`. Extend a factory rather than constructing these by hand in a test.
- `tests/helpers/statements.py` holds the bank statement builders and, run as a script,
  regenerates the binary fixtures under `tests/assets/{parsers,bbva,sabadell,cobee}`.
- `isolated_migration_registry` (tests/config) gives a test its own `MigrationEngine` registry.
- `tests/core` has a `client` fixture: a real `Client` whose SDK calls land on `ynab_api`.
- Textual apps are driven with `asyncio.run()` around `app.run_test()` through `run_app` in
  `tests/cli/commands/apps/reconcile/harness.py` (button and row helpers there too). It turns
  animations off and makes the pilot's idle wait poll every 5 ms instead of 20.

## Keeping the suite fast

The whole suite runs in seconds. A test that takes more than a few hundred milliseconds
is almost always waiting for a fixed interval, not working. Measure before you accept it:

- Never wait for a real timer. A view's interval is a module constant (`SYNC_POLL_SECONDS`
  in the home view, `TICK_SECONDS` in net worth) that the test patches down.
- Wait for a condition with `should_see` or `eventually`, never `asyncio.sleep(n)`.
- A timeout under test gets the shortest value that still proves it.
- Prefer `spec=` to `autospec=True` on big classes (a Textual app): autospec builds a mock
  for every attribute, every test.

## Web app tests (`tests/web/`)

- `guest` builds the app through `web.app.build` exactly as `yul app` does, after the config
  fixtures, with the YNAB client stubbed by `ynab_api`; it is a browser without the session
  cookie (for the token guard). `user` is the same browser with the cookie: use it for views.
  Both are `tests.helpers.web.User`, NiceGUI's `User` checking the page every 5 ms for up to
  `WAIT_SECONDS` (10 s) whatever `retries` says: `await user.open("/")`, `user.find(marker=...)`,
  `await user.should_see(...)`. A passing check returns as soon as the page is right, so the
  long ceiling costs nothing; a short one is a guess of how fast a runner is, and flakes. Mark
  elements in the views with `.mark("name")` and find them by marker rather than by text.
- After a click that goes to another page, check the address with `await arrived(user, path)`
  (`tests/helpers/web.py`), never `assert user.back_history[-1] == path`: the page is on screen
  one turn of the event loop before the browser has its address, so the assert fails now and
  then on a slow runner.
- Never `user.find(...)` an element you have not waited for: wait for that element, not for
  another one drawn before it. Views read what they need first and draw a page in one go, so
  a page is never half drawn around an `await`.
- `YUL_TEST_SLOW_IO=0.3 uv run pytest tests/web` delays every `run.io_bound` call, as a busy
  CI runner does. A test that passes only without it reads the page before the work it waits
  for has finished: fix the wait, or the view if it draws around an await.
- Request every fixture that changes the config or the store before `user`, which loads the
  app state from them. A test that changes the config afterwards calls `state().reload()`.
- `tests/web/conftest.py` resets the `AppState` global for every test, so a sync a view
  started cannot leak its task or error into the next test. `fresh_nicegui()`
  (`tests/helpers/web.py`) wraps NiceGUI's global reset, which otherwise unloads
  `ynab_unlinked` from `sys.modules`.
- `store_file` (root conftest) is `store_path()` under the scratch `YUL_HOME`. Seed the store
  with `tests.helpers.store.upsert` and `Store.log(..., at=...)` after one empty `Store.sync` so
  `last_sync` is set (the `store` fixture in `tests/web/views/test_home.py`), or through
  `Store.sync` with the `ynab_api` stub answering (`serve()` in `test_networth.py`).
- `nicegui.testing.user_plugin` is loaded in the root conftest and `pytest-asyncio` runs with
  `asyncio_mode = "auto"`: web tests are plain `async def` functions.
- Never give an element a class named `xs`, `sm`, `md`, `lg` or `xl`: Quasar hides those
  outside their breakpoint. Small buttons are `button(small=True)` (class `small`).
