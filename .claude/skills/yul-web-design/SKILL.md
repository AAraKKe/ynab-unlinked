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

`ARCHITECTURE.md` is "as built": when you deviate, update it
in the same change. Never update a document to describe something you did not build.

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
   (import commit, lock all) get exactly one `shell.confirm` listing what will change.
9. **Toasts** are `shell.notify(message, kind)`: top center under the bar, 3s. Never
   `ui.notify` directly.
10. **Views are `live` unless they hold a form.** `@shell.view(..., live=False)` for Import
    and Settings only; live views are re-rendered after a sync from the chip.
11. **Colour carries meaning only.** Series colours from `theme.SERIES`, never status
    colours for series, never Quasar colour props. Accent gradient for the one primary
    action per screen.
12. **Motion** is the existing set (page enter, stagger, count up, shimmer, check draw).
    Do not add new animations; `prefers-reduced-motion` must stay instant.

## Building blocks (use these, do not restyle Quasar by hand)

- `components`: `button(text, kind=primary|ghost|danger|danger-primary, small, icon_name)`,
  `icon(name)` from `ICONS`, `pill(text, kind)`, `glass_card(hover, flush)`, `stat_tile`,
  `segmented_bar`, `share_bar`, `empty_state`, `spinner`, `check`, `bank_logo`,
  `count_up(label, milliunits, currency_format)` (the one count up).
- `components` helpers instead of hand rolled NiceGUI: `set_class(el, name, on)`,
  `clickable(el, handler, role=...)` (Tab, click and Enter), `loading(text)` /
  `show_state(box, "loading" | "error" | "ok", text)`, `section_title(text, swatch=)`,
  `card_switch(card, on=, marker=, title=, on_change=)` (rule 3; the marker stays on the
  `ui.switch`), `dialog_box(title, lede=)` + `run_dialog(dialog)` (rule 7's skeleton),
  `budget_tiles(budgets, selected, on_pick)`.
- `components.dropzone`, `components.history_chart`, `components.controls` (`pill_group`,
  `switch`) for the bigger pieces.
- CSS classes are prefixed `yul-` and live only in `web/static/yul.css`, in the section of
  their view (never `ui.add_css` or a CSS string in Python); a flow's sticky footer is
  `yul-foot` with `yul-foot-stat`. Use the tokens (`var(--accent-solid)`,
  `var(--text-2)`, `color-mix(...)`), never literal colours except in the tokens table.
- `shell`: `@shell.view`, `shell.notify`, `shell.confirm`, `shell.set_header`,
  `with shell.edit_config("Saved") as config:` (every config save, then the toast),
  `shell.pending_uploads` / `shell.on_drop`, `shell.refresh_view`, and every view path
  (`shell.HOME_PATH`, `RECONCILE_PATH`, `NETWORTH_PATH`, `SETTINGS_PATH`, ...).
- `state()`: config, client, store, `require_formatter()` (the one way to the formatter),
  loaders, `sync()`, `invalidate()`, `fresh(max_age)`, `budget_accounts()`.
- `web.wording` (`plural`, `short_date`, `human_size`, `ynab_error_message`, ...),
  `web.ynab` (`fetch_budgets`, `load_budget`, `fallback_accounts`), `web.buckets` (title and
  colour of each bucket), `web.accounts.STALE_AFTER_DAYS`. A view never imports another
  view: what two views share lives in one of these.
- A view with data to shape is a package (`views/home/`, `import_/`, `reconcile/`,
  `networth/`, `settings/`): `data.py` is pure, no NiceGUI even through its imports, and is
  tested directly; the render modules draw; `__init__` re-exports what tests import. Keep
  each file under about 500 lines.

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
- Run `hatch run dev:pytest -q tests/web` while iterating, the whole suite and
  `hatch run dev:check` (pyright strict on src) before you finish.

## Looking at it

Never run against the user's real config. Point yul at a scratch folder with `YUL_HOME`
(config, budget copy and web preferences go there) and name a separate keychain item with
`YUL_KEYCHAIN_SERVICE`, so a config save never touches the real token. Do not change `HOME`:
on macOS that hides the login keychain and the system shows a "Keychain Not Found" dialog.

```sh
mkdir -p /tmp/yulhome
cp tests/assets/config_V4/config.json /tmp/yulhome/
YUL_HOME=/tmp/yulhome YUL_KEYCHAIN_SERVICE=yul-scratch hatch run dev:yul app --no-browser --port 8771
```

For a first run (onboarding) leave the folder empty. `YUL_NO_KEYCHAIN=1` instead keeps the
token in the file, as the tests do. Delete the scratch folder afterwards: it may hold a token.

The printed link carries the session token. Check both themes (toggle in the top bar) and
a narrow window (under 1000px Home becomes one column).

## Checklist before you commit

- [ ] Wording passes rule 1; figures use the budget's `Formatter`.
- [ ] New element → marker; new behaviour → test; changed behaviour → test updated.
- [ ] `ARCHITECTURE.md` and `DESIGN.md` in this folder describe what you built.
- [ ] A changelog fragment exists for the branch (`hatch run tc:check`).
- [ ] `hatch run dev:check` clean, `hatch run dev:pytest -q` green.
- [ ] Commit message plain, no trailers.
