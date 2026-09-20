# ynab-unlinked

`yul` is a CLI that imports bank statement exports into YNAB. It parses a file from a bank
("entity"), matches the transactions against what already exists in YNAB, and creates or
updates them through the YNAB API.

## Layout

```
src/ynab_unlinked/
  main.py            Typer app entry point (`yul`). Wires the subcommands.
  commands/          `load`, `config`, `privacy`, `reconcile`. `apps/` holds the Textual TUI.
  entities/          One package per bank (bbva, cobee, sabadell). See "Adding an entity".
  parsers/           Shared file readers (xls, pdf) used by entities.
  process.py         Pipeline run by every `load <entity>` command.
  matcher.py         Matches parsed transactions to existing YNAB transactions.
  payee.py           Fuzzy payee matching against YNAB payees.
  models.py          `Transaction` (parsed) and `TransactionWithYnabData` (enriched).
  ynab_api/          Thin wrapper around the `ynab` SDK (`Client`).
  config/            Versioned config (`ConfigV1`, `ConfigV2`) with a migration engine.
  setup.py           First-run setup and loading the `YnabUnlinkedContext` for commands.
tests/               Mirrors `src`. Fixtures in `tests/assets`, helpers in `tests/helpers`.
changelog/           Towncrier fragments, one per PR.
```

## Adding an entity

1. Create `src/ynab_unlinked/entities/<name>/` with a parser class implementing the
   `Entity` protocol from `entities/_protocol.py` (`parse()` returns `list[Transaction]`,
   `name()` returns the entity key).
2. Expose a Typer `command` callable in the package. `commands/load.py` discovers every
   entity package that has one and registers it as `yul load <name>`.
3. The command builds the parser and calls `process_transactions()` from `process.py`.
4. Add tests under `tests/entities/`.

## Working on the repo

Everything runs through hatch. Environments are created on demand; uv is the installer.

```bash
hatch run dev:cov            # tests with coverage, accepts pytest args (-k name)
hatch run dev:check          # lint + format check + pyright
hatch run dev:fix            # ruff format + autofix
hatch run tc:check           # verify a changelog fragment exists for the branch
```

CI runs the same four things on every PR. See `tests/AGENTS.md` for test conventions.

## Conventions

- Dependencies are pinned exactly in `pyproject.toml`; dependabot bumps them.
- Import SDK names from the package root: `from ynab import TransactionDetail`.
- Every PR needs a changelog fragment in `changelog/` named `<pr-number>.<type>.md`
  (types: added, improved, bugfix, bumped, doc, contrib, misc, removed, deprecated).
  Use `+<slug>.<type>.md` when the PR number is not known yet.
- Releases: bump `src/ynab_unlinked/__about__.py`, run `hatch run tc:build`, merge, then
  push a `yul-X.Y.Z` tag. The release workflow validates the version and publishes to PyPI.
