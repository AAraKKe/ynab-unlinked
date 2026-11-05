"""Design tokens, the CSS every page gets, and the chart palette.

The CSS lives in `static/yul.css` (tokens from `.claude/skills/yul-web-design/DESIGN.md` section 4, the component
classes, the motion keyframes). Dark is the default; Quasar's dark mode (`body--dark` /
`body--light`) switches the token set, and the choice lives in `app.storage.user` so it
survives reloads. Class names are prefixed `yul-` so they never collide with Quasar or
Tailwind.
"""

from __future__ import annotations

from dataclasses import dataclass

from nicegui import app, ui

STATIC_ROUTE = "/yul-static"

_THEME_KEY = "yul.theme"
_DARK = "dark"
_LIGHT = "light"


@dataclass(frozen=True)
class Palette:
    """Colours for marks drawn from Python (charts). Chrome uses the CSS variables instead."""

    series: tuple[str, ...]
    accent: tuple[str, str]
    accent_solid: str
    good: str
    warn: str
    bad: str
    text: str
    text_2: str
    text_3: str
    hair: str


ACCENT = ("#6366f1", "#22d3ee")
"""Start and end of the accent gradient (135deg), the same in both themes."""

# Series 1..3 from DESIGN.md, the 4th from the mock's "by account" chart, 5 and 6 for the six
# accounts the "by account" grouping can show. Assign them by entity and never recycle them.
# Status colours are never used for series.
SERIES = ("#3987e5", "#d95926", "#199e70", "#eda100", "#9a6ce0", "#d4568f")
SERIES_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a", "#c98a00", "#7c4fd0", "#c43f7a")
GOOD = "#22c55e"
WARN = "#f59e0b"
BAD = "#ef4444"
GOOD_LIGHT = "#16a34a"
WARN_LIGHT = "#d97706"
BAD_LIGHT = "#dc2626"

DARK_PALETTE = Palette(
    series=SERIES,
    accent=ACCENT,
    accent_solid="#6366f1",
    good=GOOD,
    warn=WARN,
    bad=BAD,
    text="#e7eaf0",
    text_2="#a3abb8",
    text_3="#6b7483",
    hair="rgba(255,255,255,0.07)",
)
LIGHT_PALETTE = Palette(
    series=SERIES_LIGHT,
    accent=ACCENT,
    accent_solid="#4f46e5",
    good=GOOD_LIGHT,
    warn=WARN_LIGHT,
    bad=BAD_LIGHT,
    text="#0f172a",
    text_2="#475569",
    text_3="#94a3b8",
    hair="rgba(15,23,42,0.07)",
)


def is_dark() -> bool:
    """The theme the current browser chose. Dark unless it picked light."""
    return app.storage.user.get(_THEME_KEY, _DARK) != _LIGHT


def save_theme(dark: bool) -> None:
    app.storage.user[_THEME_KEY] = _DARK if dark else _LIGHT


def palette() -> Palette:
    """The palette of the current browser's theme, for charts built on the server."""
    return DARK_PALETTE if is_dark() else LIGHT_PALETTE


def page_setup() -> ui.dark_mode:
    """Per page: Quasar's brand colour and the stored dark mode. Returns the dark mode switch."""
    ui.colors(primary=DARK_PALETTE.accent_solid, positive=GOOD, negative=BAD, warning=WARN)
    return ui.dark_mode(is_dark())


def install() -> None:
    """Add the fonts, tokens, component classes and the drag tracking script to every page.

    The stylesheet is `static/yul.css`, served under `STATIC_ROUTE`.
    """
    ui.add_head_html(
        # Inter is bundled (static/fonts) so the app works offline; OFL.txt next to it is the
        # font's SIL Open Font License, which must travel with the file.
        f'<link rel="preload" href="{STATIC_ROUTE}/fonts/InterVariable.woff2" as="font" '
        'type="font/woff2" crossorigin>'
        f'<link rel="stylesheet" href="{STATIC_ROUTE}/yul.css">',
        shared=True,
    )
    ui.add_body_html(f"<script>{DRAG_JS}</script>", shared=True)


# Counts dragenter/dragleave on the document so the overlay shows while files are over the
# window and hides when they leave it. Capture phase, because QUploader stops the propagation
# of the drag events over its drop area, which would leave the count (and the overlay) stuck.
# Drops that miss the uploader (onboarding has none) must not make the browser open the file.
DRAG_JS = """
(() => {
  let depth = 0;
  const hasFiles = (e) => !!e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
  const set = (on) => document.body.classList.toggle("yul-dragging", on);
  document.addEventListener("dragenter", (e) => { if (!hasFiles(e)) return; depth++; set(true); }, true);
  document.addEventListener("dragleave", (e) => {
    if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) set(false);
  }, true);
  document.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  document.addEventListener("drop", (e) => {
    depth = 0; set(false);
    if (!document.querySelector(".yul-drop-upload")) e.preventDefault();
  }, true);
})();
"""
