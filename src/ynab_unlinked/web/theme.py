"""Design tokens, the CSS every page gets, and the chart palette.

The CSS lives in `static/yul.css` (tokens from `.claude/skills/yul-web-design/DESIGN.md` section 4, the component
classes, the motion keyframes). Two choices style a page, both kept per browser in
`app.storage.user` so they survive reloads: the palette (`THEMES`, Midnight unless another
was picked), a `yul-theme-<name>` class on `<body>` that selects the palette's tokens, and
dark or light (dark by default), Quasar's `body--dark` / `body--light`, which selects the
palette's variant and the neutral tokens. Class names are prefixed `yul-` so they never
collide with Quasar or Tailwind.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from nicegui import ui

from ynab_unlinked.web.storage import user_storage

STATIC_ROUTE = "/yul-static"

_THEME_KEY = "yul.theme"
"""Dark or light, per browser."""
_PALETTE_KEY = "yul.palette"
"""The name of the palette (`THEMES`), per browser."""
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

# Aurora's chart colours in each variant; `palette_for` puts another palette's accent on the
# same neutral, series and status colours.
DARK_PALETTE = Palette(
    series=SERIES,
    accent=("#6366f1", "#22d3ee"),
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
    accent=("#6366f1", "#22d3ee"),
    accent_solid="#4f46e5",
    good=GOOD_LIGHT,
    warn=WARN_LIGHT,
    bad=BAD_LIGHT,
    text="#0f172a",
    text_2="#475569",
    text_3="#94a3b8",
    hair="rgba(15,23,42,0.07)",
)


@dataclass(frozen=True)
class Variant:
    """What a palette changes in the charts in one of its variants (dark or light)."""

    accent: tuple[str, str]
    """Start and end of the charts' accent (the net worth line, the sparkline)."""
    accent_solid: str
    """`--accent-solid` of the variant."""


@dataclass(frozen=True)
class Theme:
    """A palette: its tokens are the `yul-theme-<name>` blocks in `static/yul.css`."""

    name: str
    title: str
    description: str
    dark: Variant
    light: Variant

    @property
    def css_class(self) -> str:
        return f"yul-theme-{self.name}"


THEMES: dict[str, Theme] = {
    theme.name: theme
    for theme in (
        Theme(
            "midnight",
            "Midnight",
            "Royal blue to indigo on a deep navy. The default.",
            dark=Variant(("#2563eb", "#4f46e5"), "#2f63e6"),
            light=Variant(("#1d4ed8", "#4338ca"), "#1d4ed8"),
        ),
        Theme(
            "twilight",
            "Twilight",
            "Indigo to violet, lavender links.",
            dark=Variant(("#6366f1", "#a855f7"), "#7c3aed"),
            light=Variant(("#4f46e5", "#9333ea"), "#6d28d9"),
        ),
        Theme(
            "graphite",
            "Graphite",
            "No accent colour: white on black, only status colours.",
            dark=Variant(("#e4e4e7", "#a1a1aa"), "#e4e4e7"),
            light=Variant(("#18181b", "#52525b"), "#18181b"),
        ),
        Theme(
            "aurora",
            "Aurora",
            "Indigo to cyan, the original yul look.",
            dark=Variant(DARK_PALETTE.accent, DARK_PALETTE.accent_solid),
            light=Variant(LIGHT_PALETTE.accent, LIGHT_PALETTE.accent_solid),
        ),
    )
}
"""Every palette, in the order the Appearance tab shows them."""
DEFAULT_THEME = THEMES["midnight"]


def is_dark() -> bool:
    """The variant the current browser chose. Dark unless it picked light."""
    return user_storage().get(_THEME_KEY, _DARK) != _LIGHT


def save_theme(dark: bool) -> None:
    user_storage()[_THEME_KEY] = _DARK if dark else _LIGHT


def current_theme() -> Theme:
    """The palette the current browser chose; Midnight when none (or an unknown one) is stored."""
    name = user_storage().get(_PALETTE_KEY)
    return THEMES.get(name, DEFAULT_THEME) if isinstance(name, str) else DEFAULT_THEME


def save_theme_choice(theme: Theme) -> None:
    user_storage()[_PALETTE_KEY] = theme.name


def palette_for(theme: Theme, dark: bool) -> Palette:
    """The chart colours of `theme` in its dark or light variant."""
    variant = theme.dark if dark else theme.light
    base = DARK_PALETTE if dark else LIGHT_PALETTE
    return replace(base, accent=variant.accent, accent_solid=variant.accent_solid)


def palette() -> Palette:
    """The chart colours of the current browser's palette and variant, for charts built on
    the server. A palette change shows in them on the next render."""
    return palette_for(current_theme(), is_dark())


def apply_theme(theme: Theme) -> None:
    """Put `theme`'s class on `<body>`, replacing any other palette's, on the open page."""
    others = " ".join(other.css_class for other in THEMES.values() if other != theme)
    ui.query("body").classes(add=theme.css_class, remove=others)


def page_setup() -> ui.dark_mode:
    """Per page: the stored palette, Quasar's brand colour and the stored dark mode.

    Returns the dark mode switch. Quasar's primary is the palette's `--accent-solid`, so it
    follows a palette or variant change without a reload.
    """
    ui.colors(primary="var(--accent-solid)", positive=GOOD, negative=BAD, warning=WARN)
    apply_theme(current_theme())
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
