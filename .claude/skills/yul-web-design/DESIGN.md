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
Home        net worth at a glance, what needs you, drop target and last imports; aside the
            month so far, where it went, recent activity
Import      Files -> Review -> Done
Reconcile   per account: cleared balance vs bank balance, reconcile transactions
Net worth   tabs: Overview (history chart, buckets, accounts with inline balance updates)
            · Months (what moved net worth each month) · Movers (how each account moved)
Cash flow   income against spending, the savings rate, where income comes from
Spending    by group, steady or swingy, every category with how it moves
Plan        net worth and the goal in the years ahead, with sliders that start at what the
            last months measured
Settings    tabs down the side: Connection · Banks · Accounts · Net worth · Categories ·
            Appearance · Data & privacy
Onboarding  full screen, first run only
```

Net worth, Cash flow, Spending and Plan sit under a small caps "Finances" heading in the sidebar
(hidden in the rail, where a gap keeps the group apart).

Navigation is a left sidebar, 232px with icons and labels, collapsible to a 64px icon rail
from a "Collapse" entry under Settings (state remembered). An entry with something waiting
behind it carries a count: Reconcile the transactions to reconcile, Net worth the balances
set by hand gone stale (a small disc on the icon in the rail). Under 960px the sidebar is
the rail; under 640px it is a bar of icons along the bottom of the window, and the top bar
keeps the title, search, the sync dot and the theme toggle.

The sidebar ends with the version ("yul 1.1.0"). When a newer yul is out an accent
**Update** pill sits next to it (an up arrow alone in the rail; not on a phone, where
Settings › Data & privacy has it). A click opens a dialog: "Update to yul 1.2.0", one
line ("The new version will be downloaded and this page refreshed once any ongoing operation
is done."), "See what changed", then Cancel and the primary **Update and restart**. It does
not say how yul updates itself: the command only shows where the user has to run it. While it runs the dialog cannot be dismissed and says "Updating
yul…"; then "yul 1.2.0 is installed. Starting it again…" and the page reloads by itself on
the new version: no new tab. A failure keeps the running yul, says so, shows what the
command printed and the line to run by hand. An install yul cannot update (from source, no
tool at hand) gets only that line and Close.

The top bar holds the page title, a **search** button that looks like a field ("Search",
⌘K or Ctrl K), the budget chip (a click opens Settings › Connection), a sync indicator
("synced 2 min ago", spinning while syncing, click to sync now), a theme toggle and a
primary **Import** button (not shown on Import itself).

**Command palette**: the search button, ⌘K / Ctrl+K or "/" open one box over the page.
Without a query it lists the pages and the actions (sync now, light or dark, collapse the
sidebar); typing finds tabs (Net worth › Months, Settings › Banks), categories (opening
their months in Spending) and accounts (opening their history in Net worth). Arrows move,
Enter opens, Escape closes. It is the fastest way to anywhere, so every new page or tab
registers itself in it.

**The app keeps itself current.** A budget copy older than ten minutes syncs on its own
while the app is open, and a sync that changed something redraws the page on screen and the
badges. A page keeps what the user set (range, filters, an open tab); a page the user
types in (Reconcile) is only redrawn by a sync they asked for.

The range pills (1M … All) of Net worth, Cash flow and Spending are one choice: picked on
one page it is the range of the others, and of the next visit.

An address without a page says so and offers the way home; a page that fails to draw says
so with "Try again". Both keep the sidebar and the top bar.

A global drop overlay covers the whole window when files are dragged over it ("Drop to
import"), on every page. Dropping navigates to Import with those files.

## 3. Screens

### Home

Two columns centered in the main area: the main column (about 60%) holds three blocks top to
bottom (hero, needs you, import), the right column three cards (the month, where it went,
recent activity, which fills what is left). One column under 1000px. Everything comes
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

  When nothing needs you, one quiet dashed row with a check instead of cards: "Nothing
  waiting. Drop a statement or check back after your next import."
- **The month** (right column): the month's name and "day 10 of 30"; Income, Spending and
  "Net so far" (never green or red: before payday a month is behind without anything being
  wrong); a bar of this month's spending over a usual month's (the average of the complete
  months of the last year; amber past 100%) with a mark at how far into the month today
  is, and the line "64% of a usual month's spending, 33% of the month gone"; under a
  hairline the year's savings rate and cash runway, which open Cash flow.
- **Where it went** (right column): the five categories that spent most this month, each a
  bar with a mark at its usual month. A row opens that category in Spending.
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
2. **Review**. A legend first: each status tag on screen, as the rows show it, and one line
   saying what it means (only the tags some row has). Then one card per file: header
   (loader, account, "n to check" in amber and "n left out" when there are some, new /
   total) and a transaction table where every row has its tag: already imported rows
   dimmed with a grey "already in YNAB", or "matched in YNAB" for a row YNAB matched with a
   reconciled transaction entered by hand; new rows with a green "new" and a ghost "Leave
   out"; rows left out crossed out with "Include again". A row with the amount of a
   transaction entered by hand that YNAB matched with an import nobody can name gets an
   amber "may be in YNAB", a line under its payee naming that transaction ("Same amount as
   Maya Mobile on 17/10/2026 in YNAB") and two ghost buttons, "Import anyway" and "Leave
   out"; it is not sent until one is chosen. Leaving a row out is saved on this computer at
   once (toast, no dialog) and later imports of the same statement show it crossed out
   without asking. A summary bar sticks to the bottom: "29 new transactions in 3 accounts",
   "1 to check" in amber, and the button "Import 29 transactions". Options: import as
   cleared (default) or reconciled. The Files step shows the same legend and tags in a
   file's body, and "n to check" on its row and in its footer.
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

The tabs **Overview · Months · Movers** sit above the page (the Settings tab style); the
range pill is shared by the three, and `?tab=months` opens a tab directly. Months and Movers
work in whole calendar months: 1M is this month, 3M the last three with this one, YTD from
January, All from the first transaction. Every line of a counted account is read the same way
(Settings › Categories explains it to the user): money in to a budget account is income,
whatever its category, refunds too; money out is spending, unless its category is marked "not
spending" (set aside); **Assets** is what changed an asset outside transfers, whatever the
reason (market moves, interest, a sale recorded as an adjustment): every line of a tracking
account, and the balance adjustments of the budget accounts whose return is followed;
transfers between counted accounts move nothing. So the parts always add up to the change.
Closed accounts count for the past (they held money then), in the history of Overview and
Home too, and show a faint "closed" pill wherever they are listed; the Accounts table, which
is about today's balances, leaves them out.

- **Months**: a title with the range ("Jun 2026 – Nov 2026") and the pills, four stat tiles
  (Change "+11,616.69€ · from 159,453.88€"; From saving, income minus spending, with "80% of
  the change" only when it is a part of it; From assets; Months up "6 of 6 · best Nov
  +3,695.85€"), then a card "Monthly change" with one bar per month: Saved (series 1), Assets
  (series 5) and, only when there is some, Other (text-3), stacked up and down from zero.
  Segments meet square and only the two ends of a month's bar are rounded, so it reads as one
  bar split into parts. A line with dots (text colour) joins the net changes, one tooltip per
  month. When Other shows, a faint line under the chart says what it is.
- **Period panel**, under the chart (no dialog): with no month selected it shows the whole
  range; a click anywhere in a month's column, or on its name, shows that month (the other
  months fade); clicking the same month again, a click anywhere else on the page (the panel
  of the month keeps it), or the ghost "× Whole range" in the panel goes back. The panel has no head of its own (the tiles and the
  chart already give the range and its change): a picked month is named next to "Where the
  change came from", with "× Whole range". Two columns: a vertical waterfall (Income up from zero in series 1, Spending
  hanging from its top in series 2, Assets in series 5, Other in text-3, each starting where the
  one before ended and joined to the next by a dashed line, then Net as a text-2 bar from zero;
  each bar's value over it, and the values as text for screen readers) and "Accounts that moved most"
  (five, each with why: "income +4,850.00€ · spending -3,650.00€ · transfers -1,520.00€");
  "Came in from" (five payees: income is by payee) and "Spent most on" (five categories).
  One column under 860px. A sync that changes nothing does not redraw the tab.
- **Movers**: one row per counted account (closed ones that held money in the range too),
  largest change first: name, a bar around a centre line (series 1 up, series 2 down) with
  the change, "Your money" (what went in or out: income, spending, transfers), "Assets" (good
  or bad) and "Return", the money weighted return of the asset changes, per year over a range
  longer than one ("+6.1%", "−8.9%/yr", "—" for an account whose return is not followed). A
  faint line under the card explains the three columns. Under 860px the two middle columns
  hide.

### Cash flow and Spending

Both read the store like the Months tab (every line sorted the same way, closed accounts
counted) and have the same head: the range as a title and the pills `1M 3M 6M YTD 1Y All`,
1Y by default. Averages, rates and how a category moves use complete months only; the month
still running shows in the charts, faded. With no complete month in the range, an empty state
asks for a longer range.

- **Cash flow**: four tiles: Income a month ("median 4,850.00€"), Spending a month ("core
  2,700.00€ · one-offs 575.00€": the steady and variable categories against the rest),
  Savings rate (saved over earned; "▲ 4.2 pts vs the 12 months before" when the budget goes
  back that far), Cash runway (cash and savings after debt over core spending, "27.8
  months"), and a faint line "Averages over 11 complete months, not this one.". Then
  "Income and spending": income (series 1) and spending (series 2) side by side per month,
  top corners rounded, one tooltip per month with what was saved. A month with a label carries
  it over its taller bar: the note written on that month in YNAB (first line), else, for a
  month far above its median (1.25×), the payee that brought more than usual or the category
  that spent more than usual. "Savings rate": its own line chart (never a second axis), the
  average dashed with "average 60.2%". "Came in from": the top six payees of the range as
  bars.
- **Spending**: three tiles (Spending a month, Core, One-offs), then side by side "By group"
  and "Steady or swingy?". A filter (a group, a word) redraws only the group highlight, the
  chart, the legend's choice and the table: the page keeps its height and its scroll.
  - **By group**: a key of the four words' colours, column titles (Group, A month, Share),
    then one row per group: its bar, a month, share, and under it a thin split of its
    spending by how its categories move (steady in good, variable in text-2, spiky in warn,
    lumpy in the accent, not enough months in border-2; each part titled with its share).
    The words' colours are at 72%: they mark a kind of category, not something to act on. A
    click filters by the group, a second click shows every group again.
  - **Steady or swingy?**: the same key of colours, then one dot per category (of the
    filters) in the colour of its word (`cashflow_chart.word_color`, at 72%, full on hover):
    average a month across on
    a log scale, how much it moves up; the six largest named, overlapping names hidden; a
    faint line: top right is big and swingy, bottom right the fixed costs. A click on a dot,
    or on a row of the table, slides the category in from the right in the chart's place.
  - **What the detail says depends on what the category is** (`data.story`), because "a
    month" is only true of a category spent every month. Each has a headline and a tinted
    line with what to set aside:
    - steady: "1,417.00€ a month" · "About the same every month. Set aside 1,417.00€ a
      month and it is covered."
    - variable: "400.00€ a month" · "Between 200.00€ and 600.00€ a month. Set aside 400.00€
      a month to cover it over time."
    - lumpy, its charges about the same: "170.99€ a charge" · "About once a year. Set aside
      14.25€ a month to have it ready." (a charge over the months between charges). "Each
      charge"; A charge, Charges, Comes, Set aside, Last one.
    - lumpy with unlike purchases, and spiky: "up to 6,753.00€ a month" · "Spent in 2 of the
      last 8 months. Set aside 860.25€ a month to cover months like these." (all it spent
      over the months since its first). Biggest month, Months spent in, In all, Set aside,
      Last one.
    - bought once: "2,000.00€ once" · "Spent once, in Jul 2026. Nothing to plan for yet."
    Lumpy and spiky draw their history from the first charge to now (the quiet months are
    how they spend), with the dashed line "Set aside a month", and no histogram.
  - **Category detail** (in the chart's card): a back arrow, "Group / Category" (the range is
    the page's), "288.94€ a month" over the months from its first spending to its last, the word with "moves 6%" and its sentence;
    "Each month" (bars, series 1, a dashed "Average" line, both in the legend); the numbers
    in a row (average, median, lowest month, highest month, spread); "How the months spread"
    (a histogram in six slices, whole unit labels slanted 45°, series 5). A new range updates
    it in place; the back arrow, or a click on a group or a word, brings the chart back.
  - **How it moves**: a card with the four words as tiles, each its pill and a sentence with
    examples and its threshold ("Moves under 25%."); a click shows only that kind (the tile
    accent bordered), again shows every kind. Lumpy and spiky both move over 75% and differ
    in how often they spend: lumpy is nothing most months, then an expense (fewer than 2
    months of 5 have one); spiky keeps coming, with some months far bigger. A faint line says how the number is worked out.
  - **Categories**: a group dropdown (All groups, then each group: there are too many for
    pills), and "Only ▲ spiky · × Every kind" when a word filters. Most spent first, twenty
    then "Show all N" unless a filter is on (then every match). Each row: name, a month,
    share, a sparkline (series 1) and the word as a pill with its number, or "not enough
    months"; a click shows the category in the chart's place, scrolled into view.

### Plan

Where this is heading, and what would change it. The plan starts from what was measured
over the last complete months (12 by default): a month's income, spending and where the
saving went. Each slider says what was measured under it. Two figures may not be the
budget's own: inflation (2% until changed), and the assets' return, which is the measured
one only when the months cover three years and 5% a year otherwise.

- **Head**: "The next 10 years" (follows the Years slider) with an "i" on how the plan is
  worked out, and on the right the pills "Today's money · With inflation" with their own
  "i". Today's money (the default) takes the rise of prices out of the figures ahead.
- **Tiles**: Net worth in N years (under it "150,433.45€ today", or "+104,158.90€ against
  what was measured" once a slider is moved), Saved a month ("58% of what comes in"), Goal
  reached ("May 2028", "reached", "not in 10 years"; under it the goal and its target, and
  "3 months late" or "2 months early" against the date of YNAB's target when it has one),
  Financial independence (the month 4% of net worth a year covers the spending).
- **What if** (a card on the left, the first thing on a narrow window): the sliders in
  small caps groups, a hairline between them, in this order: Each month, Assets, The
  goal, How far, and Returns, which is folded. *Each month*: Income and Spending, as a change in percent with the
  amount it makes ("5,394.72€ · +8%"). *Assets*: Ends up in assets, what was put into them less what was taken out,
  as an amount and its share of what is saved ("501.00€ · 29%", under it "of what you save
  · measured 500.00€ in, 100.00€ out a month"). Shares that vest and are sold pass through
  assets, so what went in can be more than was saved: the slider carries what was left
  there, and the line under it keeps both figures. Below nothing, assets give money back
  ("-300.00€", "assets give back · measured …"). The slider ends at all that is
  saved ("1,700.00€ · 100%"): no more can end up in assets than was not spent, and the
  end moves with the Income and Spending sliders. Under it, in text-2, the sum: "Left in the
  budget: 1,700.00€ saved − 501.00€ into assets = 1,199.00€ a month" ("+ 300.00€ out of
  assets" when they give back; ", made up from cash" when it is negative). *The goal*:
  Goes to the goal, a share of that ("17% · 203.83€", under it "of the 1,199.00€ left in
  the budget · measured 200.00€ a month"), so it fits whatever the assets take.
  Under the goal's slider one folded row, "ONCE REACHED  nothing
  changes" and a chevron, opens two switches, both off until flipped since nothing in a
  budget says what a goal is for: "Its money is spent" (what it holds leaves net worth
  the month after it is reached, and its line in the goal's chart ends there) and "Its
  share goes to assets" (what it took a month is invested from then on). A line under
  them says it in the plan's own figures: "Once it is reached in Mar 2029: 12,000.00€
  leaves net worth, and 150.00€ a month goes to assets." The folded row reads "spent ·
  share to assets". "Reset all" turns them off. *How far*: Years ahead ("until Nov 2036"), always in sight: it is the slider played
  with most. *Returns*: one row, "RETURNS  assets 5.0% · inflation 2.0%" and a chevron,
  that opens Assets return, Savings interest and Inflation on a click (Enter too) and stays
  as it was left. Under each slider one faint line with what was measured. The assets'
  return says only "measured over the last 3.0 years" or "a default: too little measured";
  an "i" next to its name tells the rest: what the assets returned and over how long, that
  a return needs three years of months to be used and 5% a year stands in until then
  ("Pick 3Y or All under Measured over to start from your own return"), or that the slider
  ends before the figure. A slider that was moved gets a small undo arrow before its
  value that puts that one back, and "Reset all" (ghost, small, the same arrow) shows in
  the card's title row once anything is moved. Each track carries a tick where the slider
  started; between the tick and the thumb the track is a clearer grey when it was moved
  down and the fill a paler accent when it was moved up, so how far it is from what was
  measured shows at a glance. At the bottom "Measured over" with the pills `6M 1Y 3Y All`
  and "12 complete months, Nov 2025 – Oct 2026". The goal's slider is not there without a
  goal, nor Savings interest without savings.
- **Net worth** (a card on the right) with the pills "Total · By type". Total: what was
  ("So far", text-2), the plan (accent, its end labelled), a soft accent band for assets
  returning two points more or less a year, and, once a slider is moved, the plan of what was
  measured as a dashed text-3 line with its own end label. By type: assets, savings and cash
  stacked from zero in their series colours, what was and what is planned in one run. A
  dashed vertical line marks today. The tooltip names the month and lists the lines of that
  day, then the range or the total.
  Under the chart one faint line checks the plan against the past: "Checked against your
  past: measured up to Oct 2025, this plan said 141,200.00€ for Oct 2026. It was
  148,900.00€, 5.5% more." ("about that" within half a percent). It follows the months
  measured, not the sliders, and is not there for a budget younger than a year and a half.
- **The goal** (a card under it, only with a goal): its name, "12,400.00€ of 20,000.00€ ·
  62%", then what it held, where the plan takes it and its target as a line across. A goal
  that is reached stays at its target, and the chart looks no further than a year past that
  month. It is always shown as its category will read: the target is a fixed amount.

Moving a slider changes the tiles, the words and the charts in place; the lines follow the
thumb (120ms). What was moved is still there after a sync and on the next visit, and a
slider left alone follows what the months measure. Sliders are Quasar's, in the accent on a
surface-2 track (`yul-slider`). Before the budget has a complete month, an empty state says
the plan starts from one.

### Settings

The tabs are a list down the left of the page, each with its icon, the open one filled; a
row that scrolls sideways under 960px. The panel opens with the tab's name. Tabs:
**Connection** (masked token with reveal and change, budget change, config version
and path), **Banks**, **Accounts**, **Net worth** (debt -> accounts mapping with a visual
picker, the goal), **Categories**, **Appearance** (the palette), **Data & privacy** (what is stored where, store size, last sync,
"Updates": the "Look for new versions" switch, on by default, one line saying what is asked
and that nothing about the user is sent, what is known ("yul 1.1.0 is the latest version.",
"yul 1.2.0 is out. You have 1.1.0.") with "Check now" and, with a newer yul, "Update"; the
rows left out of imports with "Include again" on each, "Resync from scratch", "Reset all
data" with confirmation).

- **Banks**: a grid of cards, one per bank: its logo, a switch in the header and a
  "Settings" cog in the footer that opens the account and default options in a dialog (the
  same options show on every file in Import). An on bank's card is live, an off one muted.
  A bank never set up is muted and its line "Pick the YNAB account its statements go to."
  is amber: that is the call to action.
  When the account picked in the dialog already takes another bank's statements, an amber
  line under it says so ("Sabadell also sends statements here; a same day, same amount row
  from both can be taken for one"); Save still works.
- **Accounts**: one card per account of the budget, closed ones too, in a grid under one
  section per bucket (Cash, Savings, Assets, Debt, with the bucket's swatch). The lede says
  every account counts in net worth, closed ones for the months they held money, and a
  switch leaves one out. Closed accounts come last in their section with a dashed border, a
  muted name and the "closed" pill, and no "balance by hand" toggle. Each card: the account name and
  a "Counted in net worth" switch (on by default), the bucket as four small pills (picking
  one moves the card to that section, the default comes from the account type) and, in the
  footer, a pencil "balance by hand" toggle (accent when on; on by default for investment
  and other asset accounts). Counted cards are live, left out ones muted with their
  controls still usable. Every change saves at once with one quiet toast ("Accounts saved",
  "Left out of net worth", "Counted in net worth"); there is no save button.
- **Net worth › Return**: one chip per counted account; on (accent) means Movers shows its
  return. Asset and tracking accounts are on by default. On a budget account, such as a
  savings account, its balance adjustments then count as what it earned (Assets), not as
  income. A click saves at once with a toast ("Showing the return of 💰 Wise Savings").
- **Net worth › Goal**: the target the plan follows, as an accent pill ("🏠 Down Payment ·
  70,000.00€", "the largest target" beside it until one is picked), a "Change goal"
  category picker listing only categories with a balance target, and "Use the largest
  target" once one is picked. The lede says yul cannot see which goal YNAB's phone app
  shows. Without a balance target in YNAB a faint line says to add one there.
- **Categories**: three short rules side by side (Income, Spending, Tracking accounts: how
  every line is read), then "Not spending": a lede, the marked categories as accent pills
  with a ×, and an "Add category" picker. Each add or removal saves at once with a toast
  ("📈 Broker is not spending now", "... counts as spending again"). Before the first sync
  that brings categories, a faint line says they come with it.
- **Category picker** (every place that picks a category): a small ghost button with a
  chevron opening a menu, never a list on the page or a plain select (a budget has hundreds
  of categories). The menu has a search field on top, focused, then every group as a small
  caps header with its categories under it in YNAB's order. Typing keeps the categories
  whose name has every typed word (no case, accents or emoji), or a whole group whose name
  matches; "No category matches" otherwise. A click picks and closes.
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
secondary 12.5px, titles 18px semibold, hero 56px bold with `letter-spacing: -0.03em`
and gradient text. `tabular-nums` in tables and axis ticks only. Figures (money, counts,
percentages) use Inter's open digits (`ss01`): the 4, 6 and 9 read faster in a column.

No card has a backdrop blur: a card sits on the page's background, which has nothing to
blur, and a blurred card next to one that repaints showed a band at its edge. Only what
content scrolls under is blurred: the sidebar, the top bar, a flow's footer, a dialog's
backdrop.

Depth and selection: a card is lit from the top (a faint gradient from `--surface-2` to
`--surface`), and the two heroes (Home, Net worth) carry a glow of the accent in their top
left corner. What is chosen is tinted with the accent, never grey: the open page in the
sidebar (and its icon), the chosen range pill, a chosen chip. A card that can be clicked
lifts 2px and takes an accent border on hover. Everything reached with the keyboard that is
not a field shows the same 3px ring (`--ring`). Scrollbars are thin and in the theme's greys.

### Motion

- Page change: fade + 10px rise, 240ms, `cubic-bezier(.2,.7,.2,1)`.
- A category detail slides in from the right over Spending's chart (28px, 300ms).
- Lists: 40ms stagger on first paint.
- Hero figures count up over 900ms (ease out cubic).
- Progress bars have a slow moving gradient shimmer while active.
- Success: an SVG check that draws itself, then the card settles.
- Hover: 150ms; press: scale .98.
- A page still reading its data shows soft blocks that pulse slowly where the content
  will be, never a blank column.
- `prefers-reduced-motion`: everything instant.

### Charts

ECharts through NiceGUI. Line 2px round joins, area gradient for single series, the value
axis of a history fitted to its values (not from zero: the moves are what it is for), 1px
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
9. **What happened is said as loudly as it deserves**, always through `shell.notify`.
   Something that worked, or a note, is one line in the top bar's status (a check and the
   words, 4s): the page already shows the result, so nothing drops over it. Only a warning
   or an error is a toast: top center under the bar, 6s, solid card, colour bar per kind.
10. **Colour carries meaning only**: series colours for series, status colours for status,
    the accent gradient for the one primary action per screen.
11. **Motion** is the existing set; `prefers-reduced-motion` stays instant.
12. **Every palette, light and dark, from the same tokens**; never a literal colour outside
    the token blocks.
