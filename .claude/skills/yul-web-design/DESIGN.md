# yul app: product and visual design

The web app is not a port of the CLI or of the Textual screens. Those are shaped by what a
terminal can show. This document describes the app as built: its screens, words, tokens and the frozen
rules in section 5.

## 1. Principles

1. **One job per visit, no reading required.** The home screen tells you what needs you
   today and gives you one button for each. Most visits end in under a minute.
2. **Drop files anywhere.** Statements are the main input. Dropping files on any screen
   starts an import. There is no "choose a loader" step; the app knows.
3. **Confirm once, then watch it happen.** Every write to YNAB is behind exactly one
   confirmation with the full list of what will change, followed by live progress and a
   done state that offers the natural next step.
4. **Numbers first, chrome last.** Big, legible figures; quiet surfaces; colour carries
   meaning (series, status) and nothing else.
5. **Looks like 2026.** Depth through layered translucent surfaces on a soft gradient
   background, one accent gradient, generous radius, motion that explains state changes.
   Four palettes (Midnight by default), each dark by default with a first class light
   variant, all from the same tokens.

## 2. Information architecture

```
Home        net worth at a glance, drop target and last imports, what needs you, recent activity
Import      Files -> Review -> Done
Reconcile   per account: cleared balance vs bank balance, reconcile transactions
Net worth   history chart, buckets, accounts with inline balance updates
Settings    tabs: Connection · Banks · Accounts · Net worth · Appearance · Data & privacy
Onboarding  full screen, first run only
```

Navigation is a left sidebar, 232px with icons and labels, collapsible to a 64px icon rail
from a "Collapse" entry under Settings (state remembered). The top bar holds the page title, the budget chip, a sync indicator
("synced 2 min ago", spinning while syncing, click to sync now), a theme toggle and a
primary **Import** button that opens the file picker.

A global drop overlay covers the whole window when files are dragged over it ("Drop to
import"), on every page. Dropping navigates to Import with those files.

## 3. Screens

### Home

Two columns centered in the main area: the main column (about 60%) holds three blocks top to
bottom, recent activity fills the right column. One column under 1000px. Everything comes
from the local store; Home never calls YNAB. Before the first sync a quiet banner says
"First sync running…" and the view refreshes when it ends.

- **Hero**: net worth of the counted accounts (every open one unless Settings leaves it out)
  with debt netted (52px, gradient text, counts up; a debt mapped to no account still comes
  off it), change since the last
  reconcile (30 days when there is none) with the counted accounts' history ("▲ €2,140.30
  since 29 Oct · 90 days"), a 90 day sparkline area under it. Clicking opens Net worth.
- **Import**: section title "Import", then the drop zone card ("Drop bank statements here ·
  or anywhere in the app · pdf, xlsx, xls, txt, html"), the same component as Import step 1.
  Under it one muted line answers "when did I last import?": "Last imports · BBVA Credit
  Card 3 days ago · Cobee never · Sabadell 12 Oct", banks in the order of the loader list,
  only the ones turned on in Settings ("today", "yesterday", "N days ago" under two weeks,
  then the day). No card per bank and no overdue styling.
- **Needs you**: section title "Needs you", then a grid of equal cards, each with one
  action: 3 per row when the column is wide, 2, then 1 (never a wrap with odd widths).
  - "8 transactions · to reconcile in 5 accounts" (open accounts) -> Reconcile
  - "3 balances · set by hand, older than 30 days: Broker, …" (last balance adjustment, or
    last transaction when there was never one) -> Net worth

  When nothing needs you, one quiet muted line instead of cards: "Nothing waiting. Drop a
  statement or check back after your next import."
- **Recent activity**: last 10 events from the store's activity log (imports, reconciles,
  adjustments) with timestamps: "29 Oct · Imported 13 transactions to 💳 Oro from
  movimientos.txt".

### Import

A three step flow with a horizontal stepper at the top. Steps advance on their own.

1. **Files**. Dropzone (large until the first file, then compact at the top). Each file
   appears as a row with a type badge, name, size and a live detection state: scanning
   spinner -> loader pill with confidence and the account it maps to -> count of new vs
   already imported. Ambiguous files show a segmented choice of the candidate loaders with
   their transaction counts. Unsupported files are kept, greyed, with the reason, and can
   be removed. Every option of the bank (Sabadell year, Cobee language) is a small select
   on the row, prefilled with the saved default or the detected value, so the defaults
   from Settings can be changed per file. The step ends with "Review n files".
2. **Review**. One card per file: header (loader, account, "n left out" when some are, new
   / total), a transaction table with already imported rows dimmed and tagged ("already in
   YNAB", or "matched in YNAB" for a row YNAB matched with a reconciled transaction entered
   by hand), new rows with a green tag and a ghost "Leave out", and rows left out crossed
   out with "Include again". Leaving a row out is saved on this computer at once (toast, no
   dialog) and later imports of the same statement show it crossed out without asking. A
   summary bar sticks to the bottom: "3 files · 41 transactions · 29 new" and the button
   "Import 29 transactions". Options: import as cleared (default) or reconciled.
3. **Done**. Per file progress bars that fill as YNAB answers, then a success card:
   created count, anything YNAB rejected as duplicate, and two buttons: "Reconcile these
   accounts" and "Import more".

### Reconcile

YNAB's own reconcile compares the cleared balance with the bank. The screen does the same
without the ceremony.

- Header: "4 accounts · 17 transactions not reconciled", a date scope
  ("since 22 Oct", "all time"), and the switch "include uncleared".
- One card per account:
  - Header: the name, then YNAB's own equation: cleared balance (large) + uncleared
    balance = working balance (both smaller, muted). Under each figure a caption: a green
    dot and "cleared balance · 2 to reconcile", an amber dot and "uncleared · 1", and
    "working balance". The counts follow the scope chips, never the "include uncleared"
    switch. Below 900px the figures stack, each with its + or = in front.
  - An optional **Your bank says** input, empty with the hint "Type it to check" (it never
    changes a balance). When filled: equal -> green "Matches" and the Reconcile
    button becomes primary; different -> the difference is shown in amber with "Find the
    gap" which expands the transactions and highlights candidates whose amount equals the
    difference.
  - Transactions, when open, grouped under section headers that say what the status
    means: **Cleared** "the bank shows these · 2 to reconcile", **Uncleared** "the bank
    has not taken these yet · skipped" ("reconcile them too" with the switch on), and,
    once rows were reconciled in this visit, **Reconciled** "already reconciled". An
    empty section keeps its header with "none since 29 Oct". Rows: checkbox (cleared pre
    selected, uncleared not and dimmed until the switch is on), date, payee, amount.
  - A full width bar closes the card. Collapsed it is one quiet button "Show 3
    transactions" with a chevron, and no Reconcile button: nobody reconciles rows they
    have not seen. Open it holds "Hide transactions" on the left and "Reconcile n
    transactions" on the right (disabled "Nothing to reconcile" at 0).
- Footer: "Reconcile 14 transactions in 4 accounts · uncleared stay untouched" and
  "Reconcile all" for everything at once, one confirmation dialog listing accounts and
  counts, live progress, done state with "See net worth". The screen says reconcile,
  YNAB's word, never lock.

### Net worth

- **Hero chart** first: net worth figure and delta at the top left, range pills
  `1M 3M 6M YTD 1Y All`, grouping select `Total · By type · By account`, and a 320px
  ECharts area chart with a vertical gradient fill (accent at 35% to transparent), 2px
  line, hairline grid, crosshair tooltip listing every series. Account grouping shows the
  four largest accounts and a row of toggle chips, one per account, to pick up to six;
  "Accounts · 3 of 6" above them. A picked chip carries the swatch of its series; at the
  limit the others are dimmed with "Remove one to add another". Pick up to N with chips,
  never a capped dropdown: a select that silently refuses the next pick looks broken.
- **Buckets** row: Assets, Savings, Cash (after debt), Debt as stat tiles with the share,
  and a thin segmented composition bar beneath. Debt that is "not netted" lowers no tile
  but still comes off the net worth figure.
- **Accounts** table grouped by bucket: name, balance, share bar, and a pencil at the
  right end of every row, shown on hover. Accounts marked "by hand" show the pencil
  always, in the accent colour, and an age pill ("by hand · 9 days ago", "stale" when
  older than 30 days). The pencil turns the balance into an inline input prefilled with
  the balance in YNAB, with a ✓ (primary) and a ✗ (ghost); Enter is ✓, Escape is ✗, one
  row at a time. ✓ is the confirmation for that one change: it creates the adjustment
  right away and toasts "📈 INDEXA set to 46,100.00€ (+22.46€)". This is the exception to
  "confirm once": a single, visible, typed value needs no second dialog.
- **Update balances**: when an account is kept by hand, the card header's right side is a
  ghost "✎ Update balances" (otherwise the hint "set an account's real balance with its
  pencil"). It turns every by hand balance into a field at once, prefilled with the balance
  as a plain number (no currency), the first one focused with its text selected; Tab goes
  from one field to the next in table order, the other rows stay text and the pencils hide.
  Next to each field its change, "+54.42€" in good or "-32.47€" in bad, empty while
  unchanged, "not a number" (and a red field border) when it does not read. A footer closes
  the card: "2 of 4 balances changed · Tab next · Enter save all" on the left, the primary
  "Save 2 balances" on the right, disabled as "Nothing changed" at zero and while a field is
  not a number. Enter saves, Escape or "✕ Cancel" drops what was typed. Save writes one
  batch and toasts "Updated 2 balances"; the changes shown in the rows are the one
  confirmation, so no dialog. On a phone the change sits under its field and the footer
  wraps, the hint above the button.
- Clicking an account name opens a drawer with its own balance chart and last
  transactions.

### Settings

Tabs: **Connection** (masked token with reveal and change, budget change, config version
and path), **Banks**, **Accounts**, **Net worth** (debt -> accounts mapping with a visual
picker), **Appearance** (the palette), **Data & privacy** (what is stored where, store size, last sync, the rows left
out of imports with "Include again" on each, "Resync from scratch", "Reset all data" with
confirmation).

- **Banks**: a grid of cards, one per bank: its logo, a switch in the header and a
  "Settings" cog in the footer that opens the account and default options in a dialog (the
  same options show on every file in Import). An on bank's card is live, an off one muted.
  A bank never set up is muted and its line "Pick the YNAB account its statements go to."
  is amber: that is the call to action.
  When the account picked in the dialog already takes another bank's statements, an amber
  line under it says so ("Sabadell also sends statements here; a same day, same amount row
  from both can be taken for one"); Save still works.
- **Accounts**: one card per open account of the budget, in a grid under one section per
  bucket (Cash, Savings, Assets, Debt, with the bucket's swatch). The lede says every open
  account counts in net worth and a switch leaves one out. Each card: the account name and
  a "Counted in net worth" switch (on by default), the bucket as four small pills (picking
  one moves the card to that section, the default comes from the account type) and, in the
  footer, a pencil "balance by hand" toggle (accent when on; on by default for investment
  and other asset accounts). Counted cards are live, left out ones muted with their
  controls still usable. Every change saves at once with one quiet toast ("Accounts saved",
  "Left out of net worth", "Counted in net worth"); there is no save button.
- **Appearance**: the four palettes as a grid of cards like Banks: a preview tile drawn in
  that palette whatever the page's is (its background with the two blobs, a primary
  "Import", a "by hand" pill and a link), the name and one line ("Royal blue to indigo on a
  deep navy. The default.", "Indigo to violet, lavender links.", "No accent colour: white on
  black, only status colours.", "Indigo to cyan, the original yul look."). The chosen card
  is live, the others plain (no muted state, no pill). A click saves the choice for this
  browser and restyles the open page at once; no toast, the change is the feedback. Dark
  and light stay on the top bar's switch, which picks the palette's variant.

### Onboarding

Full screen, centered 640px card over the gradient background, a vertical step rail on
the left of the card. Steps: Token -> Budget -> Banks -> Done. There is no accounts step:
every open account counts in net worth until the user chooses otherwise in Settings ›
Accounts.

- **Token**: live check against YNAB, the keychain hint under the field.
- **Budget**: one tile per budget. Picking a tile marks it in place (`on`); the grid is
  never drawn again for a click, so the tiles do not replay their entrance.
- **Banks**: Continue from Budget moves here at once and the step body shows a centered
  spinner with "Reading your accounts…" while yul reads the budget. Then one row per bank
  (logo, title, an account select over every open account of the budget, sorted by name;
  the one account named after the bank is preselected). Lede: "Where each bank's
  statements go. You can change this later in Settings › Banks." If YNAB fails the error
  shows centered with "Try again"; Back works and Finish stays disabled until the accounts
  are read.
- **Done**: Finish saves the settings and copies the budget in the foreground: spinner,
  "Copying your budget from YNAB", one muted line following the copy ("Fetching all
  transactions from YNAB", "8,630 transactions received") and "The first time can take a
  minute." Then the big check, "You are set", "Drop your first statements whenever you
  like." and "Open yul". If the copy fails: "Your budget is not copied yet", the reason in
  red, "Try again" and still "Open yul" (the sync chip tries again).

## 4. Visual language

### Tokens

Neutral tokens, the same in every palette:

| Token | Dark | Light |
|---|---|---|
| `--surface` | `rgba(255,255,255,0.04)` | `rgba(255,255,255,0.72)` |
| `--surface-2` (raised) | `rgba(255,255,255,0.07)` | `rgba(255,255,255,0.92)` |
| `--border` | `rgba(255,255,255,0.08)` | `rgba(15,23,42,0.08)` |
| `--text` | `#e7eaf0` | `#0f172a` |
| `--text-2` | `#a3abb8` | `#475569` |
| `--text-3` | `#6b7483` | `#94a3b8` |
| `--good` | `#22c55e` | `#16a34a` |
| `--warn` | `#f59e0b` | `#d97706` |
| `--bad` | `#ef4444` | `#dc2626` |
| series 1 … 6 | `#3987e5` `#d95926` `#199e70` `#eda100` `#9a6ce0` `#d4568f` | `#2a78d6` `#eb6834` `#1baf7a` `#c98a00` `#7c4fd0` `#c43f7a` |
| radius | 16px cards, 10px controls, 999px pills | |

Palette tokens: one block per palette and variant in `static/yul.css`, selected by the body
classes `yul-theme-<name>` (Settings › Appearance, stored per browser) and `body--dark` /
`body--light` (the top bar's switch). The selectors are not tied to `<body>`, so an element
with a `yul-theme-<name>` class shows that palette (the Appearance previews). Midnight is
also on `:root`, the look before the class arrives.

- `--bg`, `--bg-blob-1` (top left), `--bg-blob-2` (bottom right): the background.
- `--accent` (the gradient, 135deg) and `--accent-solid` (borders, live cards, Quasar's
  primary).
- `--accent-2`: links, the "by hand" toggle, the activity feed's sync dot, info toasts, the
  drop overlay's border, the spinner.
- `--on-accent`: text and ticks on the accent (white; near black on Graphite dark).
- `--ring`: the translucent focus ring (`box-shadow: 0 0 0 3px var(--ring)`).
- `--pill-acc-text`, `--pill-acc-border`, `--pill-acc-bg`: `yul-pill acc` ("by hand").
- `--link-decoration`: `none`; `underline` on Graphite, where colour no longer marks a link.

| Palette | Variant | `--bg` | blobs | `--accent` | `--accent-solid` | `--accent-2` | `--on-accent` | `--ring` | pill text / border / bg |
|---|---|---|---|---|---|---|---|---|---|
| Midnight | dark | `#070b14` | `#2563eb` 20%, `#4f46e5` 14% | `#2563eb` → `#4f46e5` | `#2f63e6` | `#93a4f5` | `#fff` | `#2563eb` 28% | `#bfdbfe` / `#3b82f666` / `#3b82f622` |
| Midnight | light | `#f5f7fc` | `#2563eb` 22%, `#4f46e5` 16% | `#1d4ed8` → `#4338ca` | `#1d4ed8` | `#1d4ed8` | `#fff` | `#1d4ed8` 25% | `#1e40af` / `#2563eb55` / `#2563eb14` |
| Twilight | dark | `#0b0f17` | `#6366f1` 18%, `#a855f7` 14% | `#6366f1` → `#a855f7` | `#7c3aed` | `#c4b5fd` | `#fff` | `#7c3aed` 28% | `#ddd6fe` / `#8b5cf666` / `#8b5cf622` |
| Twilight | light | `#f7f6fb` | `#6366f1` 22%, `#a855f7` 18% | `#4f46e5` → `#9333ea` | `#6d28d9` | `#7c3aed` | `#fff` | `#6d28d9` 25% | `#5b21b6` / `#7c3aed55` / `#7c3aed14` |
| Graphite | dark | `#0a0a0c` | white 5%, `#6366f1` 7% | `#fafafa` → `#d4d4d8` | `#e4e4e7` | `#d4d4d8` | `#111113` | white 20% | `#e4e4e7` / white 22% / white 8% |
| Graphite | light | `#f6f6f8` | `#0f172a` 6%, `#6366f1` 6% | `#18181b` → `#3f3f46` | `#18181b` | `#18181b` | `#fff` | `#18181b` 22% | `#27272a` / `#0f172a` 25% / `#0f172a` 5% |
| Aurora | dark | `#0b0f17` | `#6366f1` 18%, `#14b8a6` 14% | `#6366f1` → `#22d3ee` | `#6366f1` | `#22d3ee` | `#fff` | `#6366f133` | `#c7d2fe` / `#6366f166` / `#6366f122` |
| Aurora | light | `#f6f7fb` | `#6366f1` 22%, `#14b8a6` 18% | `#6366f1` → `#22d3ee` | `#4f46e5` | `#4f46e5` | `#fff` | `#6366f133` | `#4338ca` / `#6366f166` / `#6366f122` |

Glows and tints of the accent (the primary button's shadow, the drop zone's hover, a picked
chip) are `color-mix(in oklab, var(--accent-solid) N%, transparent)`, never a literal.

Background: `--bg` with two fixed radial gradient blobs (600px, blurred 80px) that do not
scroll. Surfaces are translucent with `backdrop-filter: blur(16px)` and a 1px border; a
1px inner top highlight (`rgba(255,255,255,0.06)`) gives the glass edge. Hover lifts 1px
and brightens the border.

### Type

Inter (bundled variable font, `font-display: swap`), fallback `system-ui`. Body 14px,
secondary 12.5px, titles 18px semibold, hero 56px bold with `letter-spacing: -0.02em`
and gradient text. `tabular-nums` in tables and axis ticks only.

### Motion

- Page change: fade + 10px rise, 240ms, `cubic-bezier(.2,.7,.2,1)`.
- Lists: 40ms stagger on first paint.
- Hero figures count up over 900ms (ease out cubic).
- Progress bars have a slow moving gradient shimmer while active.
- Success: an SVG check that draws itself, then the card settles.
- Hover: 150ms; press: scale .98.
- `prefers-reduced-motion`: everything instant.

### Charts

ECharts through NiceGUI. Line 2px round joins, area gradient for single series, 1px
hairline grid, no vertical grid, axis text in `--text-3`, crosshair with one tooltip for
all series, end labels on the right, legend only with two or more series. Series colours
from the table above, assigned by entity and never recycled. Status colours never used
for series. The accent of a single series line (net worth, the Home sparkline) is the
palette's chart accent (`theme.palette()`), drawn on the server: a palette change shows on
the next render, and Net worth restyles its charts within a second.

### Cards with a switch

A card that can be switched on or off (Settings Banks and Accounts) shows its state with the
whole card, never with an "on"/"off" status pill. `yul-card live` is on: accent border at
55%, a soft accent ring and glow over the normal shadow, the surface tinted 7% with the
accent. `yul-card off` is muted: opacity .55 (.8 on hover) and a greyscale logo tile. A
muted card keeps its controls usable. The switch sits at the right of the card header.

### Bank logos

Every logo is `src/ynab_unlinked/web/static/logos/<loader key>.svg` with
`viewBox="0 0 120 60"` (2:1), the artwork centered in that box with at least 8% padding on
every side (square marks stay centered with empty sides), brand colours meant for a white
tile, no scripts and no external references, `role="img"` and an `aria-label`. The tile
(`.yul-bank-logo`, `components.bank_logo`) is `--logo-size` tall and twice as wide, white,
and the image fills it, so every tile in a grid is identical. A key without a file gets the
bank's monogram on the same tile.

### Components

Stat tile · pill group · segmented bar · glass card · stepper · drop zone · file row ·
transaction table · account row with inline edit (pencil → input, ✓ ✗) · toggle chips · confirm dialog (title, change list,
primary action) · progress list · done card · toast (top center under the bar, 3s) · empty state
(gradient icon disc, one line, one button).

## 5. Rules (frozen)

The rules every change must keep. The project skill `.claude/skills/yul-web-design/SKILL.md`
repeats them for agents with the build contract and the test routine; keep the two in sync.

1. **No technical words on screen**: bank, budget copy, settings file, "on this computer";
   never loader, store, sync token, cache, plain text.
2. **One centered column** (`.yul-views`, max 1360px); views never set their own width.
3. **Cards with a switch are live or muted, never pilled**: `yul-card.live` (accent border,
   ring and tint) when on, `yul-card.off` (muted, greyscale logo) when off. Banks and
   Accounts in Settings are the reference.
4. **Bank logos are 2:1** (`viewBox 0 0 120 60`, centered, 8% padding, white tile) and are
   rendered only through `bank_logo`; every tile in a grid has the same size.
5. **A number in a row is edited inline**: pencil, input in place, ✓ and ✗ (Enter, Escape),
   one row at a time, ✓ is the confirmation.
6. **Pick up to N with chips**, with a "3 of 6" counter and dimmed chips at the limit; never a
   capped dropdown.
7. **Settings of one thing live in a dialog behind a cog**; saving is immediate, no tab wide
   Save button.
8. **Every write to YNAB**: `run.io_bound`, one activity entry, `state().invalidate()`, a
   toast. Multi item writes get exactly one confirmation listing what changes.
9. **Toasts** come from `shell.notify`: top center under the bar, 3s, solid card, colour bar
   per kind.
10. **Colour carries meaning only**: series colours for series, status colours for status,
    the accent gradient for the one primary action per screen.
11. **Motion** is the existing set; `prefers-reduced-motion` stays instant.
12. **Every palette, light and dark, from the same tokens**; never a literal colour outside
    the token blocks.
