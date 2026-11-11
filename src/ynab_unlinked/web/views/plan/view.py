"""The Plan view: four tiles, the sliders, net worth ahead and the goal.

The sliders start at what the months measured (`data.measured`). Moving one draws another
plan in place: the tiles, the words next to each slider and the charts follow without the
page being built again, and the plan of what was measured stays as a dashed line. What was
moved, the months measured, the money and the grouping are kept in the browser's preferences,
so the plan is still there after a sync or on the next visit.
"""

from __future__ import annotations

import datetime as dt
from typing import cast

from nicegui import run, ui
from nicegui.events import ValueChangeEventArguments

from ynab_unlinked.core.plan import Fit
from ynab_unlinked.web import shell, theme
from ynab_unlinked.web.buckets import SERIES_BUCKETS, STYLES
from ynab_unlinked.web.components import (
    button,
    clickable,
    empty_state,
    glass_card,
    icon,
    info_button,
    set_class,
)
from ynab_unlinked.web.components.cashflow_chart import chart
from ynab_unlinked.web.components.controls import pill_group, switch
from ynab_unlinked.web.components.history_chart import set_options
from ynab_unlinked.web.components.plan_chart import (
    GOAL_HEIGHT,
    WORTH_HEIGHT,
    goal_options,
    types_options,
    worth_options,
)
from ynab_unlinked.web.state import state
from ynab_unlinked.web.storage import user_storage
from ynab_unlinked.web.views.plan import data

_KEY = "yul.plan"
"""What the user set on the page, per browser: `window`, `money`, `grouping`, `returns` and
`after` (whether those groups are open) and `changes` (the sliders moved and the switches
flipped, by key)."""
_FOLDS = ("returns", "after")

FREE_HINT = "4% of net worth a year covers your spending"


def _saved() -> dict[str, object]:
    """What was set on the last visit; nothing outside a browser session."""
    try:
        saved = user_storage().get(_KEY)
    except RuntimeError:
        return {}
    return dict(cast(dict[str, object], saved)) if isinstance(saved, dict) else {}


def _pick(saved: dict[str, object], key: str, options: dict[str, object], default: str) -> str:
    value = saved.get(key)
    return value if isinstance(value, str) and value in options else default


class _Tile:
    """A stat tile whose label, figure and hint change with the plan."""

    def __init__(self, marker: str) -> None:
        with glass_card().classes("yul-tile").mark(marker):
            self.label = ui.label().classes("yul-tile-l")
            self.value = ui.label().classes("yul-tile-v")
            self.hint = ui.label().classes("yul-tile-w")

    def show(self, label: str, value: str, hint: str) -> None:
        self.label.set_text(label)
        self.value.set_text(value)
        self.hint.set_text(hint)


class PlanView:
    def __init__(self) -> None:
        saved = _saved()
        self.window = _pick(saved, "window", dict(data.WINDOWS), data.DEFAULT_WINDOW)
        self.money = _pick(saved, "money", dict(data.MONEY), "today")
        self.grouping = _pick(saved, "grouping", dict(data.GROUPINGS), "total")
        self.open = {key: saved.get(key) is True for key in _FOLDS}
        changes = saved.get("changes")
        self.changes: dict[str, object] = (
            dict(cast(dict[str, object], changes)) if isinstance(changes, dict) else {}
        )
        self.page: data.PlanPage | None = None
        self.quiet = False
        """Sliders are being put back by the page, not moved by the user."""
        self.title: ui.label | None = None
        self.tiles: dict[str, _Tile] = {}
        self.sliders: dict[str, ui.slider] = {}
        self.values: dict[str, ui.label] = {}
        self.hints: dict[str, ui.label] = {}
        self.resets: dict[str, ui.button] = {}
        self.stays: ui.label | None = None
        self.summaries: dict[str, ui.label] = {}
        self.switches: ui.element | None = None
        """Where the goal's switches are drawn."""
        self.switched: dict[str, bool] = {}
        """How the switches on the page stand."""
        self.after_note: ui.label | None = None
        self.reset: ui.button | None = None
        self.worth_chart: ui.echart | None = None
        self.goal_chart: ui.echart | None = None
        self.goal_note: ui.label | None = None
        self.body = ui.element("div").classes("yul-plan")
        shell.on_refresh(self.body, self.render)

    def _save(self) -> None:
        user_storage()[_KEY] = {
            "window": self.window,
            "money": self.money,
            "grouping": self.grouping,
            **self.open,
            "changes": dict(self.changes),
        }

    async def render(self) -> None:
        config, _ = state().require()
        page = await run.io_bound(data.load, state().store, config, self.window, dt.date.today())
        if page is None or self.body.is_deleted:
            return
        self.page = page
        self.body.clear()
        with self.body:
            self._draw(page)

    # ---- what the user sets ------------------------------------------------------------------

    async def set_window(self, key: str) -> None:
        self.window = key
        self._save()
        await self.render()

    def set_money(self, key: str) -> None:
        self.money = key
        self._save()
        self.update()

    def set_grouping(self, key: str) -> None:
        self.grouping = key
        self._save()
        self.update()

    def move(self, key: str, value: float | None) -> None:
        """A slider was moved: the plan follows; back on what was measured, it is no change."""
        if self.quiet or value is None or self.page is None or self.page.fit is None:
            return
        start = data.measured(self.page.fit)
        self._stand(data.with_changes(start, {**self.changes, key: value}), start)

    def flip(self, key: str, on: bool) -> None:
        """One of the goal's switches was flipped."""
        if self.page is None or self.page.fit is None:
            return
        self.switched[key] = on
        start = data.measured(self.page.fit)
        self._stand(data.with_changes(start, {**self.changes, key: on}), start)

    def back(self, key: str) -> None:
        """One slider back to what was measured."""
        if self.page is not None and self.page.fit is not None:
            self.move(key, getattr(data.measured(self.page.fit), key))

    def back_to_measured(self) -> None:
        if self.page is not None and self.page.fit is not None:
            start = data.measured(self.page.fit)
            self._stand(start, start)

    def _stand(self, knobs: data.Knobs, start: data.Knobs) -> None:
        """Keep where the sliders stand and draw the plan."""
        self.changes = dict(data.moved(knobs, start))
        self._save()
        self.update()

    def _place(self, found: Fit, plan: data.Plan) -> None:
        """Put every slider where the plan has it. The assets' slider ends at all that is
        saved, which moves with income and spending, and so does the mark of where it
        started."""
        self.quiet = True
        try:
            for key, slider in self.sliders.items():
                if key == "net_assets":
                    top = data.ceiling(found, plan.knobs)
                    knob = next(knob for knob in data.KNOBS if knob.key == key)
                    slider.props["max"] = top
                    slider.style(f"--mark:{data.mark(knob, plan.start.net_assets, top):.2f}")
                    slider.update()
                if slider.value != getattr(plan.knobs, key):
                    slider.set_value(getattr(plan.knobs, key))
        finally:
            self.quiet = False
        if self.switched != {key: getattr(plan.knobs, key) for key in data.SWITCHES}:
            self._switches(plan.knobs)

    def _switches(self, knobs: data.Knobs) -> None:
        """Draw the goal's switches where the plan has them: at first, and again when they
        are put back all at once."""
        if self.switches is None:
            return
        self.switched = {key: getattr(knobs, key) for key in data.SWITCHES}
        self.switches.clear()
        with self.switches:
            for key, label in data.SWITCHES.items():
                switch(label, self.switched[key], lambda on, key=key: self.flip(key, on)).mark(
                    f"plan-{key}"
                )

    # ---- drawing -----------------------------------------------------------------------------

    def _draw(self, page: data.PlanPage) -> None:
        with ui.element("div").classes("yul-nwm-head"):
            with ui.element("div").classes("yul-row yul-info-row yul-grow"):
                self.title = ui.label("The years ahead").classes("yul-h2").mark("plan-title")
                info_button(data.HOW_TITLE, data.HOW_NOTE, marker="plan-info")
            with ui.element("div").classes("yul-row yul-info-row"):
                pill_group(data.MONEY, self.money, self.set_money, marker="money")
                info_button(data.MONEY_TITLE, data.MONEY_NOTE, marker="money-info")
        found = page.fit
        if found is None:
            empty_state(
                "The plan starts from a complete month of your budget. Come back next month.",
                icon_name="plan",
            ).mark("plan-empty")
            return

        with ui.element("div").classes("yul-nw-tiles yul-stagger"):
            self.tiles = {key: _Tile(f"plan-{key}") for key in ("end", "saving", "goal", "free")}

        plan = data.build(page, found, self.changes)
        with ui.element("div").classes("yul-plan-grid"):
            self._knobs(page, found, plan)
            with ui.element("div").classes("yul-plan-charts"):
                with glass_card().classes("yul-nwm-card"):
                    with ui.element("div").classes("yul-row"):
                        ui.label("Net worth").classes("yul-nwm-title yul-grow")
                        pill_group(
                            data.GROUPINGS, self.grouping, self.set_grouping, marker="grouping"
                        )
                    self.worth_chart = chart({}, WORTH_HEIGHT).mark("plan-chart")
                    if page.check is not None:
                        formatter = state().require_formatter()
                        ui.label(data.check_note(page.check, formatter)).classes(
                            "yul-faint yul-small yul-plan-check"
                        ).mark("plan-check")
                self.goal_chart = self.goal_note = None
                if page.goal is not None:
                    with glass_card().classes("yul-nwm-card").mark("plan-goal-card"):
                        with ui.element("div").classes("yul-row"):
                            ui.label(page.goal.name).classes("yul-nwm-title yul-grow")
                            self.goal_note = ui.label().classes("yul-faint yul-small yul-num")
                        self.goal_chart = chart({}, GOAL_HEIGHT).mark("plan-goal-chart")
        self.update()

    def _knobs(self, page: data.PlanPage, found: Fit, plan: data.Plan) -> None:
        """The card of sliders, by what they change, and the months they were measured over."""
        skip: set[str] = set()
        if page.goal is None:
            skip.add("to_goal")
        if not page.position.savings and not found.assumptions.to_savings:
            skip.add("savings_return")
        known = {knob.key: knob for knob in data.KNOBS}
        self.sliders, self.values, self.hints, self.resets = {}, {}, {}, {}
        self.summaries, self.switches, self.after_note = {}, None, None
        with glass_card().classes("yul-plan-knobs").mark("plan-knobs"):
            with ui.element("div").classes("yul-row"):
                ui.label("What if").classes("yul-nwm-title yul-grow")
                self.reset = button(
                    "Reset all",
                    kind="ghost",
                    small=True,
                    icon_name="undo",
                    on_click=self.back_to_measured,
                ).mark("plan-reset")
                self.reset.props["title"] = "Every slider back to what was measured"
            for title, keys in data.SECTIONS:
                shown = [known[key] for key in keys if key not in skip]
                if not shown:
                    continue
                if title == data.RETURNS:
                    with self._fold("returns", title):
                        for knob in shown:
                            self._knob(knob, plan, found)
                    continue
                ui.label(title).classes("yul-plan-section")
                for knob in shown:
                    self._knob(knob, plan, found)
                if "to_goal" in keys:
                    with self._fold("after", "Once reached", nested=True):
                        self.switches = ui.element("div").classes("yul-plan-switches")
                        self.after_note = ui.label().classes("yul-knob-h").mark("plan-after-note")
                    self._switches(plan.knobs)
                if "net_assets" in keys:
                    self.stays = ui.label().classes("yul-knob-h yul-plan-stays").mark("plan-stays")
            with ui.element("div").classes("yul-plan-measured"):
                ui.label("Measured over").classes("yul-muted yul-small yul-grow")
                pill_group(
                    {key: key for key in data.WINDOWS},
                    self.window,
                    self.set_window,
                    marker="window",
                )
            ui.label(data.measured_note(found)).classes("yul-faint yul-small").mark("plan-months")

    def _fold(self, key: str, title: str, *, nested: bool = False) -> ui.element:
        """A group that only shows when opened: its heading with what it holds in a few
        words, and the element its content goes in. `nested`: inside another group, without
        the hairline of a group of its own."""
        with ui.element("div").classes("yul-plan-fold").mark(f"plan-{key}") as head:
            ui.label(title).classes("yul-plan-section")
            self.summaries[key] = (
                ui.label().classes("yul-knob-h yul-grow").mark(f"plan-{key}-summary")
            )
            icon("chevron-down", 16)
        if nested:
            head.classes("nested")
        body = ui.element("div").mark(f"plan-{key}-body")

        def show() -> None:
            body.set_visibility(self.open[key])
            set_class(head, "open", self.open[key])
            head.props["aria-expanded"] = "true" if self.open[key] else "false"
            head.update()

        def toggle() -> None:
            self.open[key] = not self.open[key]
            self._save()
            show()

        clickable(head, toggle)
        show()
        return body

    def _knob(self, knob: data.Knob, plan: data.Plan, found: Fit) -> None:
        """A slider with its value, its way back and what was measured. Where it started is
        marked on its track, so how far it was moved shows between the mark and the thumb."""
        value, start = getattr(plan.knobs, knob.key), getattr(plan.start, knob.key)

        def moved(event: ValueChangeEventArguments[float | None]) -> None:
            self.move(knob.key, event.value)

        with ui.element("div").classes("yul-knob").mark(f"knob-{knob.key}"):
            with ui.element("div").classes("yul-row yul-info-row"):
                ui.label(knob.label).classes("yul-knob-l")
                if knob.key == "assets_return":
                    info_button(
                        data.RETURN_TITLE,
                        data.return_note(found),
                        marker="plan-assets_return-info",
                    )
                ui.element("span").classes("yul-grow")
                back = button(
                    kind="ghost", small=True, icon_name="undo", on_click=lambda: self.back(knob.key)
                ).mark(f"plan-{knob.key}-reset")
                back.classes("yul-knob-back")
                back.props["title"] = "Back to what was measured"
                back.props["aria-label"] = f"{knob.label}: back to what was measured"
                self.resets[knob.key] = back
                self.values[knob.key] = (
                    ui.label().classes("yul-knob-v yul-num").mark(f"plan-{knob.key}-value")
                )
            slider = ui.slider(
                min=knob.low, max=knob.high, step=knob.step, value=value, on_change=moved
            )
            slider.classes("yul-slider").mark(f"plan-{knob.key}")
            slider.style(f"--mark:{data.mark(knob, start):.2f}")
            slider.props["aria-label"] = knob.label
            self.sliders[knob.key] = slider
            self.hints[knob.key] = ui.label().classes("yul-knob-h")

    def update(self) -> None:
        """Work the plan out again and put it on the page that is already there."""
        page = self.page
        if page is None or page.fit is None or self.body.is_deleted:
            return
        config, _ = state().require()
        formatter = state().require_formatter()
        money = formatter.format_amount_milli
        found = page.fit
        plan = data.build(page, found, self.changes)
        real = self.money == "today"
        years = data.years_text(plan.knobs.years)

        if self.title is not None:
            self.title.set_text(f"The next {years}")
        if self.reset is not None:
            self.reset.set_visibility(bool(self.changes))
        self.tiles["end"].show(
            f"Net worth in {years}",
            money(round(data.worth(plan.plan, real)[-1])),
            data.end_hint(page, plan, real, formatter),
        )
        self.tiles["saving"].show(
            "Saved a month", money(round(plan.yours.saving)), data.saving_hint(plan)
        )
        self.tiles["goal"].show(
            "Goal reached", data.goal_value(page, plan), data.goal_hint(page, plan, formatter)
        )
        self.tiles["free"].show("Financial independence", data.free_value(page, plan), FREE_HINT)
        somewhere_else = data.moved(plan.knobs, plan.start)
        for key, label in self.values.items():
            label.set_text(data.knob_value(key, plan, formatter))
            self.hints[key].set_text(data.knob_hint(key, page, found, plan, formatter))
            self.resets[key].set_visibility(key in somewhere_else)
        if self.stays is not None:
            self.stays.set_text(data.stays_note(plan, formatter))
        self.summaries["returns"].set_text(data.returns_summary(plan))
        if self.after_note is not None:
            self.summaries["after"].set_text(data.after_summary(plan))
            self.after_note.set_text(data.after_note(page, plan, formatter))
        self._place(found, plan)

        palette = theme.palette()
        currency_format = config.budget.currency_format
        line = data.timeline(page, plan.plan)
        if self.worth_chart is not None and self.grouping == "type":
            buckets = data.by_type(page, plan.plan, real)
            set_options(
                self.worth_chart,
                types_options(
                    line.days,
                    [
                        (STYLES[b].title, palette.series[STYLES[b].slot or 0], buckets[b])
                        for b in SERIES_BUCKETS
                    ],
                    today=page.today,
                    palette=palette,
                    currency_format=currency_format,
                ),
            )
        elif self.worth_chart is not None:
            so_far = [*(past.total for past in page.past), page.position.total]
            set_options(
                self.worth_chart,
                worth_options(
                    line.days,
                    so_far=line.behind(so_far),
                    plan=line.ahead(data.worth(plan.plan, real)),
                    measured=line.ahead(data.worth(plan.measured, real)),
                    low=line.ahead(data.worth(plan.low, real)),
                    high=line.ahead(data.worth(plan.high, real)),
                    today=page.today,
                    compare=plan.changed,
                    palette=palette,
                    currency_format=currency_format,
                ),
            )
        if self.goal_chart is not None and page.goal is not None:
            goal = page.goal
            if self.goal_note is not None:
                share = goal.balance / goal.target if goal.target else 0
                self.goal_note.set_text(
                    f"{money(goal.balance)} of {money(goal.target)} · {data.percent(share * 100)}"
                )
            line = line.until(data.goal_months(plan))
            set_options(
                self.goal_chart,
                goal_options(
                    line.days,
                    so_far=line.behind(data.goal_so_far(page)),
                    plan=line.ahead(data.goal_ahead(plan.plan)),
                    measured=line.ahead(data.goal_ahead(plan.measured)),
                    target=goal.target,
                    today=page.today,
                    compare=plan.changed,
                    palette=palette,
                    currency_format=currency_format,
                ),
            )


@shell.view(
    shell.PLAN_PATH,
    key="plan",
    title="Plan",
    subtitle="Where this is heading, and what would change it",
    icon="plan",
    order=43,
    group="Finances",
)
async def plan_view() -> None:
    await PlanView().render()
