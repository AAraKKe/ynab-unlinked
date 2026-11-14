---
name: yul-web-design
description: Use before changing anything under src/ynab_unlinked/web (the `yul app` NiceGUI web app) - a new view, a component, a settings tab, wording, CSS, or a test of the UI. Holds the frozen design rules, the patterns every screen reuses, the build contract and the verification routine, so the app keeps one look and one behaviour.
---

# yul web app: how to change it without breaking the design

The web app is a product with a frozen visual language. Three documents own it; this skill
tells you which one answers what, and the rules you must not reinvent.

| Question | Where |
|---|---|
| What does each screen do, which words, which states | `DESIGN.md` in this folder (sections 3 and 5) |
| Tokens, type, motion, charts, component list | `DESIGN.md` section 4 |
| Names, signatures, markers, activity log shapes, how views talk to `core/` and `store/` | `ARCHITECTURE.md` in this folder, section 3 |

`ARCHITECTURE.md` is the contract, not a narration of the code: it fixes names,
signatures, markers, activity log shapes and the rules the code cannot express; the
docstrings and the tests say how the rest works. When you deviate from it, update it in the
same change. Never update a document to describe something you did not build.

## Rules that are not up for debate

1. **No technical words on screen.** Nothing says loader, store, sync token, SQLite, cache,
   milliunits, knowledge, plain text. Say bank, budget copy, settings file, "on this
   computer". Tooltips and toasts follow the same rule.
2. **Content is centered.** `.yul-views` caps the width (1360px) and centers it. Views never
   set their own width; they fill the column.
3. **Cards with a switch are live or muted, never pilled.** A card that can be turned on
   (a bank, a tracked account) carries a `ui.switch` in its header. On = class `live`
   (accent border and glow). Off = class `off` (muted, logo greyscale). No on/off pill.
4. **Bank logos are 2:1.** `web/static/logos/<loader key>.svg`, `viewBox="0 0 120 60"`,
   artwork centered with at least 8% padding, white tile, `role="img"` and `aria-label`.
   Render them only through `components.bank_logo(key, title, size=...)`, which falls back
   to a monogram. Every tile in a grid has the same size.
5. **Editing a number in a row is inline.** A pencil icon button opens an input in place
   with ✓ (apply, also Enter) and ✗ (cancel, also Escape). One row edits at a time. The ✓
   is the confirmation; no dialog on top of it.
6. **Pick up to N with chips, never a capped dropdown.** Selected chips are `on`, at the
   limit the rest are `off` with a title that says to remove one first, and a counter reads
   "3 of 6".
7. **Settings of one thing live in a dialog behind a cog.** Grids stay scannable; the
   dialog has the fields, Cancel and one primary Save. Saving is immediate: no tab wide
   Save button.
8. **Every write to YNAB** goes through `run.io_bound`, logs one activity entry (shapes in
   ARCHITECTURE 3.4), calls `state().invalidate()` and ends with a toast. Multi item writes
   (import commit, reconcile all) get exactly one `shell.confirm` listing what will change.
9. **Saying what happened** is `shell.notify(message, kind)`, never `ui.notify` directly.
   `ok` and `info` are one quiet line in the top bar's status (the page already shows the
   result); only `warn` and `error` are toasts, top center under the bar.
10. **Views are `live` unless they hold a form.** `@shell.view(..., live=False)` for Import
    and Settings only; live views are re-rendered after a sync from the chip.
11. **Colour carries meaning only.** Series colours from `theme.SERIES`, never status
    colours for series, never Quasar colour props. Accent gradient for the one primary
    action per screen.
12. **Motion** is the existing set (page enter, stagger, count up, shimmer, check draw, the
    category detail's slide in, the pulse of a page still loading).
    Do not add new animations; `prefers-reduced-motion` must stay instant.

## Building blocks (use these, do not restyle Quasar by hand)

- `components`: `button(text, kind=primary|ghost|danger|danger-primary, small, icon_name)`,
  `icon(name)` from `ICONS`, `pill(text, kind)`, `glass_card(hover, flush)`, `stat_tile`,
  `segmented_bar`, `share_bar`, `empty_state`, `spinner`, `check`, `bank_logo`,
  `count_up(label, milliunits, currency_format)` (the one count up), `amount(value, formatter)`
  (the amount of a transaction in a list: "+" and the good tone on money in).
- `components` helpers instead of hand rolled NiceGUI: `set_class(el, name, on)`,
  `clickable(el, handler, role=...)` (Tab, click and Enter), `loading(text)` /
  `show_state(box, "loading" | "error" | "ok", text)`, `section_title(text, swatch=)`,
  `card_switch(card, on=, marker=, title=, on_change=)` (rule 3; the marker stays on the
  `ui.switch`), `dialog_box(title, lede=)` + `run_dialog(dialog)` (rule 7's skeleton),
  `budget_tiles(budgets, selected, on_pick)`.
- `components.dropzone`, `components.history_chart`, `components.flow_chart`,
  `components.controls` (`pill_group`, `switch`) for the bigger pieces, and
  `components.category_picker` whenever a category is picked: never a select or a list on the
  page, a budget has hundreds.
- CSS classes are prefixed `yul-` and live only in `web/static/yul.css`, in the section of
  their view (never `ui.add_css` or a CSS string in Python); a flow's sticky footer is
  `yul-foot` with `yul-foot-stat`. Use the tokens (`var(--accent-solid)`,
  `var(--text-2)`, `color-mix(...)`), never literal colours except in the token blocks: a
  colour that depends on the palette (`--accent-2`, `--on-accent`, `--ring`, ...) is a token
  set in every `yul-theme-<name>` block, light and dark.
- A new page or tab is reachable from the command palette: pages are in it by themselves,
  a tab registers with `shell.command(key, title, path, icon=...)` next to its view. A view
  that would lose what the user set when it is rebuilt after a sync registers
  `shell.on_refresh(owner, handler)`; one the user types in, `automatic=False`. The finance
  pages take their range from `ranges.saved_range` and save a pick with `ranges.save_range`.
- `shell`: `@shell.view`, `shell.command`, `shell.on_refresh`, `shell.notify`,
  `shell.confirm`, `shell.set_header`,
  `await shell.save_config(change, "Saved")` (every config save, off the event loop, then
  the toast; returns False after toasting a failed save),
  `shell.pending_uploads` / `shell.on_drop`, `shell.refresh_view`, and every view path
  (`shell.HOME_PATH`, `RECONCILE_PATH`, `NETWORTH_PATH`, `SETTINGS_PATH`, ...).
- `state()`: config, client, store, `require_formatter()` (the one way to the formatter),
  loaders, `sync()`, `invalidate()`, `budget_accounts()`.
- `web.wording` (`plural`, `short_date`, `human_size`, `ynab_error_message`, ...),
  `web.ynab` (`fetch_budgets`, `load_budget`, `fallback_accounts`), `web.buckets` (title and
  colour of each bucket), `web.accounts.STALE_AFTER_DAYS`. A view never imports another
  view: what two views share lives in one of these.
- A view with data to shape is a package (`views/home/`, `import_/`, `onboarding/`,
  `reconcile/`, `networth/`, `settings/`): `data.py` is pure, no NiceGUI even through its
  imports, and is tested directly; the render modules draw; `__init__` holds the docstring
  only, tests import from the modules. Keep each file under about 500 lines.

## Tests

- `tests/web/views/test_<view>.py` with NiceGUI's simulated `User` (`user` fixture, cookie
  already set; `guest` without it). `await user.open(path)`, `user.find(marker=...)`,
  `await user.should_see(text | marker=...)`. Retries for anything that waits on
  `run.io_bound` (`retries=20`).
- Every element a test touches has a marker: `.mark("kebab-case")`, ids in it where there
  are many (`f"edit-{account.id}"`). Keep existing marker names; tests are the contract.
- YNAB is the `ynab_api` stub (`tests/helpers/ynab_api.py`). The store is filled through
  `Store.sync` with the stub (see `seed` in `test_reconcile.py`). The keychain is a fail
  backend by default; `memory_keychain` when a test needs one.
- Run `uv run pytest -q tests/web` while iterating, the whole suite,
  `uv run poe races` (the web tests with slowed off-loop work: a test that reads the page
  too early fails every time) and `uv run poe check` (ty, strict on src) before you finish.
- No flaky tests, ever (`AGENTS.md`, hard rules): wait for the element or state that only
  exists once the work is done, never for one drawn before it.

## Looking at it

Never run against the user's real config. Point yul at a scratch folder with `YUL_HOME`
(config, budget copy and web preferences go there). That is enough: with `YUL_HOME` set,
the token goes to a keychain item of its own, `ynab-unlinked (<YUL_HOME path>)`, so a config
save never touches the real token (`YUL_KEYCHAIN_SERVICE` names the item instead). Do not
change `HOME`: on macOS that hides the login keychain and the system shows a "Keychain Not
Found" dialog.

```sh
mkdir -p /tmp/yulhome
cp tests/assets/config_V4/config.json /tmp/yulhome/
YUL_HOME=/tmp/yulhome uv run yul app --no-browser --port 8771
```

For a first run (onboarding) leave the folder empty. `YUL_NO_KEYCHAIN=1` instead keeps the
token in the file, as the tests do. Delete the scratch folder afterwards: it may hold a token
(and the scratch item may hold one in the keychain).

The printed link carries the session token. Check dark and light (toggle in the top bar) of
every palette (Settings › Appearance) and narrow windows: under 1000px Home becomes one
column, under 960px the sidebar is the rail, under 640px a bar of icons along the bottom.
`uv run --with playwright python scripts/readme_screenshots.py` runs the app on a made-up
budget and takes a picture of every page.

## Checklist before you commit

- [ ] Wording passes rule 1; figures use the budget's `Formatter`.
- [ ] New element → marker; new behaviour → test; changed behaviour → test updated.
- [ ] `ARCHITECTURE.md` and `DESIGN.md` in this folder describe what you built.
- [ ] A changelog fragment exists for the branch, named `<pr-number>.<type>.md`: open the PR,
      then rename the `+<slug>` fragment to its number (`uv run poe tc-check` fails until then).
- [ ] `uv run poe check` clean, `uv run pytest -q` and `uv run poe races` green.
- [ ] Commit message plain, no trailers.
