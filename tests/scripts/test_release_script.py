import pytest

from scripts import release
from scripts.release import ReleaseError

CHANGELOG = """# Changelog

## ynab-unlinked 1.1.0 (2026-12-01)

### Fresh Out of the Feature Oven

- Something new (#130)

## ynab-unlinked 1.0.0 (2026-11-10)

- The web app (#120)
"""


@pytest.mark.parametrize("text", ["1.0", "v1.0.0", "1.0.0rc1", "1.0.0 ", "a.b.c"])
def test_parse_version_refuses_anything_but_x_y_z(text: str):
    with pytest.raises(ReleaseError, match="not a version"):
        release.parse_version(text)


@pytest.mark.parametrize(
    ("new", "current"), [("1.0.0", "1.0.0"), ("0.9.9", "1.0.0"), ("1.0.9", "1.0.10")]
)
def test_check_newer_refuses_a_version_that_is_not_newer(new: str, current: str):
    with pytest.raises(ReleaseError, match="not newer"):
        release.check_newer(new, current)


def test_check_newer_compares_numbers_not_text():
    release.check_newer("1.0.10", "1.0.9")


def test_pending_fragments_leaves_out_the_template():
    names = ["_template.jinja", "121.contrib.md", "+slug.added.md"]

    assert release.pending_fragments(names) == ["+slug.added.md", "121.contrib.md"]


def test_changelog_section_is_the_text_under_the_version_heading():
    section = release.changelog_section(CHANGELOG, "1.1.0")

    assert section == "### Fresh Out of the Feature Oven\n\n- Something new (#130)"


def test_changelog_section_needs_the_version_heading():
    with pytest.raises(ReleaseError, match="no section for 1.2.0"):
        release.changelog_section(CHANGELOG, "1.2.0")


def test_pr_body_carries_the_notes_and_the_tag_to_push():
    body = release.pr_body("1.1.0", "- Something new (#130)")

    assert "- Something new (#130)" in body
    assert "grep -qx 'version = \"1.1.0\"'" in body
    assert 'git tag -s yul-1.1.0 -m "Release 1.1.0" origin/main' in body
    assert "git push origin yul-1.1.0" in body


class FakeGit:
    """Answers `run` like a checkout where every check passes, recording the commands."""

    def __init__(
        self, changelog_listing: str = "changelog/_template.jinja\nchangelog/130.added.md"
    ):
        self.commands: list[tuple[str, ...]] = []
        self.answers = {
            ("git", "show", "origin/main:pyproject.toml"): 'name = "x"\nversion = "1.0.0"\n',
            ("git", "ls-tree", "--name-only", "origin/main", "changelog/"): changelog_listing,
        }

    def __call__(self, *cmd: str) -> str:
        self.commands.append(cmd)
        if cmd[:3] == ("gh", "pr", "create"):
            return "https://github.com/AAraKKe/ynab-unlinked/pull/131"
        return self.answers.get(cmd, "")

    def ran(self, *prefix: str) -> bool:
        return any(cmd[: len(prefix)] == prefix for cmd in self.commands)


@pytest.fixture
def fake_git(monkeypatch: pytest.MonkeyPatch, tmp_path) -> FakeGit:
    fake = FakeGit()
    monkeypatch.setattr(release, "run", fake)
    monkeypatch.setattr(release.shutil, "which", lambda _: "/usr/bin/gh")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG)
    monkeypatch.setattr(release, "CHANGELOG", changelog)
    return fake


def test_release_branches_bumps_builds_commits_pushes_and_opens_the_pr(fake_git: FakeGit):
    url = release.release("1.1.0", "Release 1.1.0\n\nThe body")

    assert url == "https://github.com/AAraKKe/ynab-unlinked/pull/131"
    steps = [cmd[:3] for cmd in fake_git.commands]
    expected = [
        ("git", "switch", "--no-track"),
        ("uv", "version", "1.1.0"),
        ("uv", "run", "towncrier"),
        ("git", "add", "-A"),
        ("git", "commit", "-m"),
        ("git", "push", "-u"),
        ("gh", "pr", "create"),
    ]
    assert [s for s in steps if s in expected] == expected
    create = fake_git.commands[-1]
    assert create[create.index("--title") + 1] == "Release 1.1.0"
    assert create[create.index("--base") + 1] == "main"


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (("git", "status", "--porcelain", "--untracked-files=no"), "uncommitted changes"),
        (("git", "branch", "--list", "release-1.1.0"), "local branch"),
        (("git", "ls-remote", "--heads", "origin", "release-1.1.0"), "origin already has"),
        (("git", "tag", "--list", "yul-1.1.0"), "already exists"),
    ],
)
def test_release_refuses_before_changing_anything(
    fake_git: FakeGit, answer: tuple[str, ...], message: str
):
    fake_git.answers[answer] = "something"

    with pytest.raises(ReleaseError, match=message):
        release.release("1.1.0", "Release 1.1.0")

    assert not fake_git.ran("git", "switch")


def test_release_refuses_a_version_not_newer_than_main(fake_git: FakeGit):
    with pytest.raises(ReleaseError, match="not newer"):
        release.release("1.0.0", "Release 1.0.0")

    assert not fake_git.ran("git", "switch")


def test_release_refuses_when_main_has_no_fragment(fake_git: FakeGit):
    fake_git.answers[("git", "ls-tree", "--name-only", "origin/main", "changelog/")] = (
        "changelog/_template.jinja"
    )

    with pytest.raises(ReleaseError, match="nothing to release"):
        release.release("1.1.0", "Release 1.1.0")

    assert not fake_git.ran("git", "switch")


def test_a_failure_after_the_branch_says_how_to_start_over(
    fake_git: FakeGit, monkeypatch: pytest.MonkeyPatch
):
    def failing(*cmd: str) -> str:
        if cmd[:2] == ("git", "push"):
            raise ReleaseError("`git push` failed:\nrejected")
        return fake_git(*cmd)

    monkeypatch.setattr(release, "run", failing)

    with pytest.raises(ReleaseError, match="git branch -D release-1.1.0"):
        release.release("1.1.0", "Release 1.1.0")


def test_main_reports_a_refusal_and_exits_1(fake_git: FakeGit, capsys: pytest.CaptureFixture[str]):
    assert release.main(["1.0"]) == 1
    assert "not a version" in capsys.readouterr().err


def test_main_defaults_the_message(fake_git: FakeGit, capsys: pytest.CaptureFixture[str]):
    assert release.main(["1.1.0"]) == 0

    assert fake_git.ran("git", "commit", "-m", "Release 1.1.0")
    assert (
        "Release PR: https://github.com/AAraKKe/ynab-unlinked/pull/131" in capsys.readouterr().out
    )
