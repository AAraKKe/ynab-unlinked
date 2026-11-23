"""The explainer behind the "i" of the waterfall in Months: what Income, Spending and Growth mean.

Income and Spending are sums of transactions, so words and what counts or not are enough,
with a reimbursed ticket for Income. Growth moves with no transaction at all, so it gets the
one animation: a made-up account's worth against the money put in it, the gap between them
shaded, a live Growth figure and a caption per phase (`terms.growth_story`). It loops; with
`prefers-reduced-motion` the chart is drawn finished and the captions are a list instead.
"""

from __future__ import annotations

import html
import json

from nicegui import ui

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.web.components import button, dialog_box, run_dialog
from ynab_unlinked.web.theme import KEEP_PROP
from ynab_unlinked.web.views.networth import terms
from ynab_unlinked.web.views.networth.data import signed
from ynab_unlinked.web.views.networth.terms import GrowthStory

WIDTH, HEIGHT, PAD = 320, 132, 10
_SWATCH = {"income": "var(--series-1)", "spending": "var(--series-2)", "assets": "var(--series-5)"}


async def show_terms(formatter: Formatter, currency_format: CurrencyFormat) -> None:
    """Open the explainer and wait until it is closed."""
    box = dialog_box(terms.TERMS_TITLE, classes="yul-terms")
    # Its clicks are not clicks outside the month picked (`theme.OUTSIDE_JS`)
    box.dialog.props(KEEP_PROP)
    box.card.props(KEEP_PROP).mark("terms-dialog")
    with box.body.classes("yul-terms-grid"):
        for term in terms.TERM_MEANINGS:
            with ui.element("section").classes("yul-term").mark(f"term-meaning-{term.kind}"):
                with ui.element("div").classes("yul-section yul-term-title"):
                    ui.element("span").classes("yul-swatch").style(
                        f"background:{_SWATCH[term.kind]}"
                    )
                    ui.label(term.title)
                ui.label(term.meaning)
                if term.counts or term.not_counted:
                    with ui.element("ul").classes("yul-term-list"):
                        for text in term.counts:
                            with ui.element("li").classes("yes"):
                                ui.label(text)
                        for text in term.not_counted:
                            with ui.element("li").classes("no"):
                                ui.label(text)
                if term.kind == "income":
                    _refund(formatter)
                if term.kind == "assets":
                    _growth(terms.growth_story(formatter), formatter)
    with box.actions:
        button("Done", kind="primary", on_click=lambda: box.dialog.submit(None)).mark("terms-done")
    await run_dialog(box.dialog)


def _refund(formatter: Formatter) -> None:
    told, lines, end = terms.refund_example(formatter)
    with ui.element("div").classes("yul-term-example").mark("refund-example"):
        ui.label(told)
        for line in lines:
            with ui.element("div").classes("yul-row"):
                ui.label(line.label).classes("yul-grow")
                ui.label(signed(formatter, line.amount)).classes("yul-num")
        ui.label(end).classes("yul-faint")


def _x(index: int, count: int) -> float:
    return PAD + index * (WIDTH - 2 * PAD) / (count - 1)


def chart_svg(story: GrowthStory, label: str) -> str:
    """The finished chart: worth (line), money put in (dashed), the gap shaded good or bad, the
    deposit's label and the moving dot. The animation clips it from the left."""
    count = len(story.worth)
    low = min(*story.worth, *story.put_in)
    high = max(*story.worth, *story.put_in)
    span = (high - low) * 1.15 or 1

    def y(value: int) -> float:
        return HEIGHT - PAD - (value - low + (high - low) * 0.05) / span * (HEIGHT - 2 * PAD)

    shades = []
    for i in range(count - 1):
        a, b = story.growth[i], story.growth[i + 1]
        tone = "up" if a + b >= 0 else "down"
        shades.append(
            f'<polygon class="{tone}" points="{_x(i, count):.1f},{y(story.put_in[i]):.1f} '
            f"{_x(i, count):.1f},{y(story.worth[i]):.1f} {_x(i + 1, count):.1f},"
            f"{y(story.worth[i + 1]):.1f} {_x(i + 1, count):.1f},{y(story.put_in[i + 1]):.1f}"
            '"/>'
        )

    def line(values: tuple[int, ...]) -> str:
        return " ".join(f"{_x(i, count):.1f},{y(v):.1f}" for i, v in enumerate(values))

    index = next(i for i, phase in enumerate(story.phases) if phase.deposit)
    before, after = story.phases[index - 1].upto, story.phases[index].upto
    at = _x(after, count)
    middle = y((story.put_in[after] + story.put_in[before]) // 2)
    end = count - 1
    return (
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" class="yul-gs-svg" role="img" '
        'aria-label="An account\'s worth moving around the money put in it">'
        '<defs><clipPath id="yul-gs-clip">'
        f'<rect class="yul-gs-reveal" x="0" y="0" width="{WIDTH}" height="{HEIGHT}"/>'
        "</clipPath></defs>"
        f'<g clip-path="url(#yul-gs-clip)"><g class="yul-gs-gap">{"".join(shades)}</g>'
        f'<polyline class="yul-gs-put" points="{line(story.put_in)}"/>'
        f'<polyline class="yul-gs-worth" points="{line(story.worth)}"/></g>'
        f'<text class="yul-gs-label" x="{at + 6:.1f}" y="{middle + 4:.1f}">{html.escape(label)}</text>'
        f'<circle class="yul-gs-dot" r="3.5" cx="{_x(end, count):.1f}" '
        f'cy="{y(story.worth[end]):.1f}"/>'
        "</svg>"
    )


def _growth(story: GrowthStory, formatter: Formatter) -> None:
    growth = [signed(formatter, value) for value in story.growth]
    with ui.element("div").classes("yul-gs").mark("growth-story") as root:
        ui.html(chart_svg(story, terms.deposit_label(formatter)), sanitize=False)
        with ui.element("div").classes("yul-gs-live"):
            ui.label(story.phases[-1].caption).classes("yul-gs-caption")
            figure = "yul-good" if story.growth[-1] >= 0 else "yul-bad"
            with ui.element("div").classes("yul-gs-figure"):
                ui.label("Growth").classes("yul-faint yul-small")
                ui.label(growth[-1]).classes(f"yul-num yul-gs-value {figure}")
        with ui.element("ol").classes("yul-gs-steps").mark("growth-steps"):
            for phase in story.phases:
                with ui.element("li"):
                    ui.label(phase.caption)
        with ui.element("div").classes("yul-gs-legend yul-faint yul-small"):
            ui.html('<i class="put"></i>you put in', sanitize=False)
            ui.html('<i class="worth"></i>what it is worth', sanitize=False)
    ui.run_javascript(_animation_js(root.id, story, growth))


def _animation_js(element_id: int, story: GrowthStory, growth: list[str]) -> str:
    """Plays the phases in a loop: each one reveals its points, then holds still. Stops once
    the dialog is gone; does nothing with `prefers-reduced-motion`, which shows the finished
    chart and the list of captions instead (`yul.css`)."""
    count = len(story.worth)
    data = {
        "xs": [_x(i, count) for i in range(count)],
        "growth": growth,
        "up": [value >= 0 for value in story.growth],
        "phases": [
            {
                "upto": phase.upto,
                "ms": phase.ms,
                "hold": phase.hold_ms,
                "caption": phase.caption,
                "deposit": phase.deposit,
            }
            for phase in story.phases
        ],
        "pause": story.pause_ms,
        "width": WIDTH,
    }
    return (
        "(() => {"
        "if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;"
        f"const d = {json.dumps(data)};"
        "let tries = 0;"
        "const start = () => {"
        f"  const root = getHtmlElement({element_id});"
        "  if (!root) { if (tries++ < 40) setTimeout(start, 25); return; }"
        "  root.classList.add('playing');"
        "  const rect = root.querySelector('.yul-gs-reveal');"
        "  const dot = root.querySelector('.yul-gs-dot');"
        "  const worth = root.querySelector('.yul-gs-worth').points;"
        "  const caption = root.querySelector('.yul-gs-caption');"
        "  const value = root.querySelector('.yul-gs-value');"
        "  const loop = d.phases.reduce((t, p) => t + p.ms + p.hold, 0) + d.pause;"
        "  let t0 = null;"
        "  const frame = (now) => {"
        "    if (!root.isConnected) return;"
        "    if (t0 === null) t0 = now;"
        "    let t = (now - t0) % loop, from = 0, at = d.phases.length - 1, f = d.xs.length - 1;"
        "    for (let i = 0; i < d.phases.length; i++) {"
        "      const p = d.phases[i];"
        "      if (t < p.ms + p.hold) {"
        "        const k = Math.min(1, t / p.ms), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;"
        "        at = i; f = from + (p.upto - from) * e; break;"
        "      }"
        "      t -= p.ms + p.hold; from = p.upto;"
        "    }"
        "    const i = Math.floor(f), j = Math.min(i + 1, d.xs.length - 1), r = f - i;"
        "    const x = d.xs[i] + (d.xs[j] - d.xs[i]) * r;"
        "    const a = worth.getItem(i), b = worth.getItem(j);"
        "    rect.setAttribute('width', x + 1);"
        "    dot.setAttribute('cx', x); dot.setAttribute('cy', a.y + (b.y - a.y) * r);"
        "    const n = Math.round(f);"
        "    value.textContent = d.growth[n];"
        "    value.classList.toggle('yul-good', d.up[n]); value.classList.toggle('yul-bad', !d.up[n]);"
        "    caption.textContent = d.phases[at].caption;"
        "    root.classList.toggle('deposit', d.phases[at].deposit);"
        "    requestAnimationFrame(frame);"
        "  };"
        "  requestAnimationFrame(frame);"
        "};"
        "start();"
        "})()"
    )
