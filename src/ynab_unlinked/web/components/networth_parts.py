"""Pieces of the Net worth view that other views may reuse: the counting hero figure and the
thin share bar of an account row."""

from __future__ import annotations

import json

from nicegui import context, ui

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.web.components.history_chart import money_js

COUNT_UP_MS = 900

_CSS_KEY = "yul.nw.css"

# Classes of the Net worth view, prefixed yul-nw- (the shared ones live in static/yul.css).
CSS = """
.yul-nw-hero { padding: 18px 20px 14px; }
.yul-nw-head { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: flex-end; }
.yul-nw-figure {
  font-size: 44px; font-weight: 750; letter-spacing: -.025em; line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.yul-nw-delta { display: flex; gap: 6px; font-weight: 600; margin-bottom: 7px; }
.yul-nw-delta .yul-faint { font-weight: 400; }
.yul-nw-pills {
  display: inline-flex; gap: 2px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 3px; margin-bottom: 2px;
}
.yul-nw-pill {
  padding: 4px 10px; border-radius: 7px; font-size: 12.5px; color: var(--text-2);
  cursor: pointer; user-select: none; transition: all .15s; outline: none;
}
.yul-nw-pill:hover, .yul-nw-pill:focus-visible { color: var(--text); }
.yul-nw-pill.on { background: var(--surface-2); color: var(--text); box-shadow: inset 0 0 0 1px var(--border-2); }
.yul-nw-select { min-width: 130px; }
.yul-nw-picker { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.yul-nw-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.yul-nw-chart { margin-top: 10px; }
.yul-nw-tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 14px 0 10px; }
.yul-nw-accounts { margin-top: 14px; padding: 12px 12px 14px; }
.yul-nw-accounts-head { padding: 4px 10px 6px; }
.yul-nw-accounts .yul-section { padding: 0 10px; margin: 12px 0 4px; }
.yul-nw-arow {
  display: grid; grid-template-columns: minmax(0, 1fr) 130px 170px 34px; align-items: center;
  gap: 12px; padding: 6px 10px; border-radius: 10px; min-height: 46px; transition: background .15s;
}
.yul-nw-arow:hover { background: var(--surface-2); }
.yul-nw-name-cell { display: flex; align-items: center; gap: 8px; min-width: 0; flex-wrap: wrap; }
.yul-nw-name { cursor: pointer; outline: none; border-radius: 4px; }
.yul-nw-name:hover, .yul-nw-name:focus-visible {
  text-decoration: underline; text-underline-offset: 3px; text-decoration-color: var(--text-3);
}
.yul-nw-balance { text-align: right; font-weight: 500; }
.yul-nw-share { display: flex; align-items: center; gap: 10px; }
.yul-nw-bar {
  flex: 1; height: 4px; border-radius: 2px; background: var(--surface-2); overflow: hidden;
  position: relative;
}
.yul-nw-bar > i {
  position: absolute; left: 0; top: 0; bottom: 0; border-radius: 2px;
  animation: yul-grow .9s var(--ease) both; transform-origin: left;
}
.yul-nw-pct { font-size: 12px; min-width: 44px; text-align: right; }
.yul-nw-edit { opacity: 0; transition: opacity .15s; justify-self: end; }
.yul-nw-arow:hover .yul-nw-edit, .yul-nw-edit:focus-visible, .yul-nw-edit.always { opacity: 1; }
.yul-nw-edit.always { color: var(--accent-solid); }
@media (hover: none) { .yul-nw-edit { opacity: 1; } }
.yul-nw-arow.editing { background: var(--surface-2); }
.yul-nw-editor {
  grid-column: 2 / -1; display: flex; justify-content: flex-end; align-items: flex-start; gap: 6px;
}
.yul-nw-editor-field { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.yul-nw-input { width: 170px; }
.yul-nw-input .q-field__control { height: 34px; min-height: 34px; padding: 0 10px; }
.yul-nw-input .q-field__native { font-size: 13px; padding: 0; font-variant-numeric: tabular-nums; }
.yul-nw-input .q-field__control:before { border-color: var(--accent-solid); }
.yul-nw-hint { font-size: 12px; }
.q-dialog__inner:has(> .yul-nw-drawer) { padding: 0 !important; }
.q-dialog__inner--right > .yul-nw-drawer, .yul-nw-drawer {
  width: min(460px, 100vw); max-width: 100vw !important; height: 100vh; max-height: 100vh !important;
  border-radius: var(--r) 0 0 var(--r) !important; background: var(--surface-solid) !important;
  display: flex; flex-direction: column; gap: 4px; overflow-y: auto; padding: 22px 22px 18px;
}
.yul-nw-drawer-figure { font-size: 28px; font-weight: 700; letter-spacing: -.02em; margin-top: 8px; }
.yul-nw-tx-list { display: flex; flex-direction: column; }
.yul-nw-tx {
  display: grid; grid-template-columns: 74px minmax(0, 1fr) auto; gap: 10px; align-items: start;
  padding: 7px 0; border-bottom: 1px solid var(--hair); font-size: 13px;
}
.yul-nw-tx:last-child { border-bottom: 0; }
.yul-nw-tx-amount { text-align: right; font-weight: 500; }
.yul-nw-memo { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 860px) {
  .yul-nw-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .yul-nw-arow { grid-template-columns: minmax(0, 1fr) 110px 34px; }
  .yul-nw-share { display: none; }
}
"""


def install_css() -> None:
    """Add the `yul-nw-` classes to the current tab, once."""
    storage = context.client.storage
    if storage.get(_CSS_KEY):
        return
    storage[_CSS_KEY] = True
    ui.add_css(CSS)


def count_up(label: ui.label, milliunits: int, currency_format: CurrencyFormat) -> None:
    """Make `label` count from zero to its amount over 900ms (ease out cubic).

    The label already holds the final text, which is what it shows at the end, without
    JavaScript, and with `prefers-reduced-motion`.
    """
    target = json.dumps(milliunits / 1000)
    ui.run_javascript(
        "(() => {"
        "if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;"
        f"const money = {money_js(currency_format)};"
        "let tries = 0;"
        "const start = () => {"
        f"  const el = document.getElementById('c{label.id}');"
        "  if (!el) { if (tries++ < 40) setTimeout(start, 25); return; }"
        "  const final = el.textContent; const t0 = performance.now();"
        "  const tick = (t) => {"
        f"    const p = Math.min(1, (t - t0) / {COUNT_UP_MS}); const e = 1 - Math.pow(1 - p, 3);"
        f"    el.textContent = p < 1 ? money({target} * e) : final;"
        "    if (p < 1) requestAnimationFrame(tick);"
        "  };"
        "  requestAnimationFrame(tick);"
        "};"
        "start();"
        "})()"
    )


def share_bar(fraction: float, color: str) -> ui.element:
    """A 4px track filled to `fraction` (0..1) in `color`, growing in on first paint."""
    width = max(0.0, min(fraction, 1.0)) * 100
    with ui.element("div").classes("yul-nw-bar") as bar:
        ui.element("i").style(f"width:{width:.2f}%;background:{color}")
    return bar


__all__ = ["CSS", "count_up", "install_css", "share_bar"]
