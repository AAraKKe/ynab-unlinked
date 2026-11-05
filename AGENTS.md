# ynab-unlinked

`yul` is a CLI that imports bank statement exports into YNAB. It parses a file from a bank
("entity"), skips the transactions already in YNAB (by import id), and creates the rest
through the YNAB API. `yul app` serves the same features as a local web app.

## Layout

```
src/ynab_unlinked/
  main.py            Typer app entry point (`yul`). Wires the subcommands.
  cli/               Everything only the terminal uses. `__init__.py` builds the Typer `app`.
    commands/        `load` (incl. `load auto`), `config`, `privacy`, `reconcile`, `app`.
                     `apps/` holds the Textual TUI.
    process.py       Pipeline run by every `load <entity>` command.
    setup.py         First-run setup and loading the `YnabUnlinkedContext` for commands.
    context_object.py  `YnabUnlinkedContext`, the options every command shares.
    cli_errors.py    The `yul` command group: a YNAB or network error from any command is
                     one line (worded on `ynab_api/errors.classify`) and exit code 1, not a
                     traceback.
    display.py       Rich console output, prompts and the `CliProgress` spinner.
    utils.py         The token and budget prompts and the transaction tables.
    choices.py       `Choice`, the selectable rows of `yul reconcile`.
  core/              UI independent services shared by the CLI and the web app: importing,
                     reconcile, loader detection, balances and net worth, history.
                     Never imports typer, rich, textual or nicegui.
  entities/          One package per bank (bbva, cobee, sabadell). `registry.py` discovers
                     their `LoaderSpec`s; `_sniff.py` has helpers for `sniff()`.
  parsers/           Shared file readers (xls, pdf) used by entities.
  activity.py        Activity log entries the CLI writes to the store (`import`, `reconcile`).
  privacy.py         The privacy notice and summary the CLI prints.
  models.py          `Transaction` and import id assignment.
  text.py            `plural`, the one wording helper the CLI and the web app share.
  buckets.py         Net worth `Bucket` and the default bucket of a YNAB account type.
  store/             SQLite copy of the budget's accounts and transactions, synced by
                     server knowledge, plus the activity log. Its schema is `store/migrations/NNNN_*.sql`,
                     one numbered script per step; add the next number, never edit one.
  local_data.py      What yul stores on this machine; shared by `config reset` and the app.
  keychain.py        The YNAB token in the system keychain (`keyring`); `ConfigV4.save/load`
                     move it there and back, the file holds `@keychain` in its place.
  ynab_api/          Thin wrapper around the `ynab` SDK (`Client`). The only SDK caller.
  config/            Versioned config (`ConfigV1`..`ConfigV4`, use `LatestConfig`) with a
                     migration engine. Save through `update_config` / `edit_config` (read
                     again, change, save), never `save()` on a copy loaded earlier; a budget
                     change goes through `switch_budget`. `budget.py` builds the saved
                     `Budget` from YNAB's answer.
  web/               NiceGUI app behind `yul app`, only importable with the `web` extra.
tests/               Mirrors `src`. Fixtures in `tests/assets`, helpers in `tests/helpers`.
typings/             Local stubs pyright reads for the untyped parts of pyexcel and html_text.
changelog/           Towncrier fragments, one per PR.
.claude/skills/      Project skills. `yul-web-design/` holds the web app's architecture
                     contract (ARCHITECTURE.md) and design (DESIGN.md).
```

## Adding an entity

Import ids follow YNAB's own file import convention, `YNAB:<milliunits>:<date>:<occurrence>`,
so YNAB's matching and its own file imports agree with yul. That is deliberate; do not add
the bank to the id. The id does not name the bank, so one YNAB account should receive
statements from one bank only: two banks feeding the same account can collide on a row of
the same day and amount imported in separate runs, and the second one is skipped as already
imported.

1. Create `src/ynab_unlinked/entities/<name>/` with a parser class implementing the
   `Entity` protocol from `entities/_protocol.py`: `parse(path)` returns
   `list[Transaction]` and raises `ParsingError` naming the line or row it cannot read,
   `name()` returns the entity name, `sniff()` returns a `Match` (confidence and a short
   reason) after reading only the head of the file, and never raises. Options (a language,
   a year) are constructor arguments: the parser never sees the CLI context.
2. Expose a `spec: LoaderSpec` (`entities/registry.py`: key, name, title, input types,
   options, `build`, the command `help`) in the package. `build(options)` binds every option.
   `key` is the package name, used on the command line, in URLs and for the logo
   (`yul load bbva`); `name` is `Entity.name()`, the key of the bank in the config
   (`loaders[name]`, where its account and options are saved). They are the same for new
   banks; BBVA keeps `name="BBVA Credit Card"` (key `bbva`) so existing configs still find
   its account.
   `cli/commands/load.py` generates `yul load <key>` from the spec, one command line option per
   `LoaderOption` (`flags`, `help`), and runs `process_transactions()` from `cli/process.py`;
   `yul load auto` and the web app find the loader through the same `spec`.
3. A value not given on the command line comes from the bank's saved options (Settings ›
   Banks), then from the file (`auto`), as `core.detect.options_for_file` resolves it.
4. Add tests under `tests/entities/`, including `sniff()` on real-looking files and on
   files of the other banks.
5. Optionally add the bank's logo as `src/ynab_unlinked/web/static/logos/<key>.svg`:
   `viewBox="0 0 120 60"`, artwork centered with at least 8% padding on every side, brand
   colours on a white tile, no scripts or external references, `role="img"` and an
   `aria-label` (see "Bank logos" in `.claude/skills/yul-web-design/DESIGN.md`). Without it the app shows a
   monogram.

## Working on the repo

Everything runs through hatch. Environments are created on demand; uv is the installer.
The `dev` environment installs the `web` extra (run `hatch env prune` after the extras
change).

```bash
hatch run dev:cov            # tests with coverage, accepts pytest args (-k name)
hatch run dev:check          # lint + format check + pyright (strict on src)
hatch run dev:fix            # ruff format + autofix
hatch run tc:check           # verify a changelog fragment exists for the branch
hatch run dev:yul app        # run the web app from the checkout
```

CI runs the same four things on every PR. See `tests/AGENTS.md` for test conventions.

## Web app

`yul app` (`web/`, extra `web`) is a NiceGUI app on 127.0.0.1 with a per run session
token. Views call `core/` and `store/`, run blocking work through `run.io_bound`, and read
shared state from `web.state.state()`. `.claude/skills/yul-web-design/ARCHITECTURE.md` is the as built contract
(names, signatures, activity log shapes); update it in the same change when deviating.
`DESIGN.md` next to it is the visual language: use the `yul-*` classes and the `components`
helpers. Its section 5 lists the frozen rules; the project skill
`.claude/skills/yul-web-design/SKILL.md` (load it before touching `web/`) repeats them with
the building blocks, the test routine and how to look at the app on a scratch home
(`YUL_HOME=/tmp/... hatch run dev:yul app`, never the real config; with `YUL_HOME` set the
token goes to a keychain item named after that folder, never the real one).

## Conventions

- Dependencies are pinned exactly in `pyproject.toml`; dependabot bumps them.
- Import SDK names from the package root: `from ynab import TransactionDetail`.
- Every PR needs a changelog fragment in `changelog/` named `<pr-number>.<type>.md`, a single
  line describing the change for users. Use `+<slug>.<type>.md` when the PR number is not
  known yet. Types:
  - `added`: new feature.
  - `improved`: new behaviour in an existing feature.
  - `bugfix`: undesired behaviour corrected.
  - `removed`: feature removed (should have been `deprecated` in a previous release).
  - `deprecated`: feature still present but warns about removal.
  - `bumped`: dependency updates (dependabot creates these automatically).
  - `doc`: documentation changes.
  - `contrib`: contributor experience (tests, checks, CI, tooling).
  - `misc`: anything that fits nowhere else.
- Releases: bump `src/ynab_unlinked/__about__.py`, run `hatch run tc:build` as the LAST
  change of the release branch (the release workflow refuses a tag while a fragment is
  pending), merge, then push a `yul-X.Y.Z` tag. The release workflow validates the version and publishes to PyPI.
