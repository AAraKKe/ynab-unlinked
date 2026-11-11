"""Open the release pull request for a new version of ynab-unlinked.

Run it through poe from a clean checkout: `uv run poe release 1.1.0 [-m MESSAGE]`.

It branches `release-X.Y.Z` from the latest `origin/main`, sets the version with
`uv version`, folds the pending changelog fragments into CHANGELOG.md, commits, pushes and
opens the PR with `gh`. Every check runs before anything changes, so a refusal leaves the
checkout as it was. Tagging stays manual: after the merge, push `yul-X.Y.Z` on the merge
commit and the release workflow publishes.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ReleaseError(Exception):
    """A check failed or a step could not run; the message says which."""


def parse_version(text: str) -> tuple[int, int, int]:
    if not VERSION_RE.match(text):
        raise ReleaseError(f"{text!r} is not a version like 1.2.3")
    major, minor, patch = (int(part) for part in text.split("."))
    return major, minor, patch


def check_newer(new: str, current: str) -> None:
    if parse_version(new) <= parse_version(current):
        raise ReleaseError(f"{new} is not newer than the current version {current}")


def pending_fragments(names: list[str]) -> list[str]:
    """The fragment files among the entries of `changelog/`, leaving out the template."""
    return sorted(n for n in names if n and not n.startswith("_template"))


def changelog_section(changelog: str, version: str) -> str:
    """The notes under the `## ynab-unlinked X.Y.Z` heading, as the release workflow reads them."""
    heading = re.compile(rf"^##.*ynab-unlinked.*{re.escape(version)}")
    lines: list[str] = []
    inside = False
    for line in changelog.splitlines():
        if heading.match(line):
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        if inside:
            lines.append(line)
    if not inside:
        raise ReleaseError(f"CHANGELOG.md has no section for {version}")
    return "\n".join(lines).strip()


def pr_body(version: str, notes: str) -> str:
    return f"""Sets the version to `{version}` and folds the pending changelog fragments into \
`CHANGELOG.md`.

## What's in {version}

{notes}

## Release flow

Keep the changelog build the last change of this branch: a fragment added after it makes \
the release workflow refuse the tag (run `uv run poe tc-build` again). After the merge, tag \
the merge commit on `origin/main` with a signed, annotated tag and push it:

```sh
git fetch origin main
git show origin/main:pyproject.toml | grep -qx 'version = "{version}"' && \\
  git tag -s yul-{version} -m "Release {version}" origin/main && \\
  git push origin yul-{version}
```

The tag goes on `origin/main`, not on the local checkout, and only once the merge is there: \
the `grep` stops it while `origin/main` still has the previous version. `release.yml` \
checks the tag against `uv version`, runs the checks and the tests, then builds, publishes \
to PyPI and creates the GitHub release from this section.
"""


def run(*cmd: str) -> str:
    shown = " ".join("<…>" if "\n" in part else part for part in cmd)  # the PR body
    print(f"$ {shown}", flush=True)
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        raise ReleaseError(f"`{' '.join(cmd)}` failed:\n{output}")
    return result.stdout.strip()


def preflight(version: str, branch: str) -> None:
    if shutil.which("gh") is None:
        raise ReleaseError("the GitHub CLI `gh` is needed to open the PR")
    if run("git", "status", "--porcelain", "--untracked-files=no"):
        raise ReleaseError("the checkout has uncommitted changes; commit or set them aside first")
    if run("git", "branch", "--list", branch):
        raise ReleaseError(f"a local branch {branch} already exists")
    if run("git", "ls-remote", "--heads", "origin", branch):
        raise ReleaseError(f"origin already has a branch {branch}")
    if run("git", "tag", "--list", f"yul-{version}"):
        raise ReleaseError(f"the tag yul-{version} already exists")


def release(version: str, message: str) -> str:
    parse_version(version)
    branch = f"release-{version}"
    preflight(version, branch)

    run("git", "fetch", "origin", "main")
    current = run("git", "show", "origin/main:pyproject.toml")
    match = re.search(r'^version = "([^"]+)"', current, re.MULTILINE)
    if match is None:
        raise ReleaseError("pyproject.toml on origin/main has no static version")
    check_newer(version, match.group(1))

    listing = run("git", "ls-tree", "--name-only", "origin/main", "changelog/")
    if not pending_fragments([Path(n).name for n in listing.splitlines()]):
        raise ReleaseError("origin/main has no pending changelog fragment, nothing to release")

    run("git", "switch", "--no-track", "-c", branch, "origin/main")
    try:
        run("uv", "version", version)
        run("uv", "run", "towncrier", "build", "--yes", "--version", version)
        notes = changelog_section(CHANGELOG.read_text(), version)
        run("git", "add", "-A", "pyproject.toml", "uv.lock", "CHANGELOG.md", "changelog")
        run("git", "commit", "-m", message)
        run("git", "push", "-u", "origin", branch)
        return run(
            "gh", "pr", "create", "--base", "main", "--head", branch,
            "--title", message.splitlines()[0], "--body", pr_body(version, notes),
        )  # fmt: skip
    except ReleaseError as error:
        raise ReleaseError(
            f"{error}\n\nStopped on branch {branch}. Fix it and finish by hand, or start over "
            f"with `git switch - && git branch -D {branch}` (and delete the remote branch if "
            "it was pushed)."
        ) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="poe release", description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the new version, X.Y.Z")
    parser.add_argument(
        "-m", "--message", help='commit message and PR title (default "Release X.Y.Z")'
    )
    args = parser.parse_args(argv)
    try:
        url = release(args.version, args.message or f"Release {args.version}")
    except ReleaseError as error:
        print(f"release: {error}", file=sys.stderr)
        return 1
    print(f"\nRelease PR: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
