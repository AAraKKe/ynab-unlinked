"""The module maps and marker lists in the docs name things that exist.

AGENTS.md and the web app's ARCHITECTURE.md are read by whoever changes the code next; a
path or a marker that was renamed away sends them looking for something that is gone.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src" / "ynab_unlinked"
AGENTS = ROOT / "AGENTS.md"
ARCHITECTURE = ROOT / ".claude" / "skills" / "yul-web-design" / "ARCHITECTURE.md"

# A tree line: indentation, then a file or a directory, then two spaces or the end of line
_ENTRY = re.compile(r"^( *)([\w.\-/]+(?:\.py|/))(?:  |$)")
# A code block whose first line is a directory: the module maps
_TREE = re.compile(r"^```\n([\w.\-/]+/\n.*?)^```", re.MULTILINE | re.DOTALL)
# Where a tree's top line lives, when it is not the repository root
_TREE_ROOTS = {"web/": SRC / "web"}


def tree_paths(markdown: str) -> list[Path]:
    """Every file and directory a module map names, resolved from its indentation."""
    paths: list[Path] = []
    for block in _TREE.findall(markdown):
        stack: list[tuple[int, Path]] = []
        for line in block.splitlines():
            if (entry := _ENTRY.match(line)) is None:
                continue
            indent, name = len(entry.group(1)), entry.group(2)
            # A description that wraps onto a line starting with a file name is deeper
            # than any child would be
            if stack and indent > stack[-1][0] + 2:
                continue
            while stack and stack[-1][0] >= indent:
                stack.pop()
            path = stack[-1][1] / name if stack else _TREE_ROOTS.get(name, ROOT / name)
            paths.append(path)
            stack.append((indent, path))
    return paths


def documented_markers(markdown: str) -> list[str]:
    """The backticked names in every "Markers:" paragraph, and any written "marker `name`"."""
    markers: list[str] = re.findall(r"\bmarker `([^`]+)`", markdown)
    paragraph: list[str] | None = None
    for line in [*markdown.splitlines(), ""]:
        if re.match(r"^\s*(- )?Markers:", line):
            paragraph = [line]
        elif paragraph is not None:
            if not line.strip() or re.match(r"^\s*(- |#)", line):
                markers += re.findall(r"`([^`]+)`", " ".join(paragraph))
                paragraph = None
            else:
                paragraph.append(line)
    return markers


def web_source() -> str:
    return "\n".join(path.read_text() for path in (SRC / "web").rglob("*.py"))


@pytest.mark.parametrize("doc", [AGENTS, ARCHITECTURE], ids=lambda doc: doc.name)
def test_every_path_in_the_module_maps_exists(doc: Path):
    paths = tree_paths(doc.read_text())

    assert paths, f"no module map found in {doc.name}"
    assert [str(path.relative_to(ROOT)) for path in paths if not path.exists()] == []


def test_every_documented_marker_is_set_by_the_web_app():
    markers = documented_markers(ARCHITECTURE.read_text())
    source = web_source()

    # `budget-{id}` is set by an f-string that starts with `budget-`, and so is
    # `attention-stale` when the view builds it as f"attention-{item.key}"
    prefixes = set(re.findall(r"f[\"']([\w\-]*-)\{", source))

    def found(marker: str) -> bool:
        fixed = marker.split("{")[0]
        if "{" not in marker and re.search(rf"[\"']{re.escape(marker)}[\"']", source):
            return True
        return any(fixed.startswith(prefix) for prefix in prefixes)

    assert len(markers) > 20
    assert [marker for marker in markers if not found(marker)] == []
