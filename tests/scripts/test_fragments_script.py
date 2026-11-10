from pathlib import Path

import pytest

from scripts import fragments


def test_fragments_named_after_their_pr_pass(tmp_path: Path):
    (tmp_path / "137.improved.md").write_text("Better.\n")
    (tmp_path / "_template.jinja").write_text("")

    assert fragments.unnumbered(tmp_path) == []
    assert fragments.main(tmp_path) == 0


def test_a_fragment_without_a_pr_number_fails_and_says_how_to_name_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    (tmp_path / "137.improved.md").write_text("Better.\n")
    (tmp_path / "+quiet-status.improved.md").write_text("Quieter.\n")
    (tmp_path / "+card-band.bugfix.md").write_text("No band.\n")

    assert fragments.main(tmp_path) == 1

    said = capsys.readouterr().out
    assert "changelog/+card-band.bugfix.md -> changelog/<PR number>.bugfix.md" in said
    assert "changelog/+quiet-status.improved.md -> changelog/<PR number>.improved.md" in said
    assert "137.improved.md" not in said
