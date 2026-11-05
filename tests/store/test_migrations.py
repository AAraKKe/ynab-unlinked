import sqlite3
from pathlib import Path

import pytest

from ynab_unlinked.store import Store, StoreError
from ynab_unlinked.store.migrations import (
    MIGRATIONS,
    SCHEMA_VERSION,
    Migration,
    MigrationError,
    MigrationFilesError,
    apply,
    load,
    version_of,
)


def test_the_scripts_are_numbered_from_one_without_gaps():
    assert [migration.number for migration in MIGRATIONS] == list(range(1, SCHEMA_VERSION + 1))
    assert all(migration.sql.strip() for migration in MIGRATIONS)


def test_each_script_applies_on_top_of_the_previous_one():
    conn = sqlite3.connect(":memory:")

    assert apply(conn) == SCHEMA_VERSION
    assert version_of(conn) == SCHEMA_VERSION


def test_only_the_scripts_the_store_has_not_seen_run():
    conn = sqlite3.connect(":memory:")
    scripts = (
        Migration(1, "0001_a.sql", "CREATE TABLE a (id INTEGER);"),
        Migration(2, "0002_b.sql", "CREATE TABLE b (id INTEGER);"),
    )
    conn.execute("CREATE TABLE a (id INTEGER)")
    conn.execute("PRAGMA user_version = 1")

    assert apply(conn, scripts) == 2  # 0001 would fail: table a exists

    assert conn.execute("SELECT count(*) FROM b").fetchone()[0] == 0


def test_a_failing_script_rolls_back_and_leaves_the_version_alone():
    conn = sqlite3.connect(":memory:")
    scripts = (Migration(1, "0001_bad.sql", "CREATE TABLE a (id INTEGER); CREATE TABLE a (x);"),)

    with pytest.raises(MigrationError, match="0001_bad.sql"):
        apply(conn, scripts)

    assert version_of(conn) == 0
    assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0


def test_a_failing_script_surfaces_as_a_store_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from ynab_unlinked.store import migrations

    monkeypatch.setattr(
        migrations, "MIGRATIONS", (Migration(1, "0001_bad.sql", "CREATE TABLE a (x;"),)
    )

    with pytest.raises(StoreError, match="could not be updated.*0001_bad.sql"):
        Store(tmp_path / "store.sqlite")


def test_a_gap_in_the_numbering_is_refused(tmp_path: Path):
    (tmp_path / "0001_initial.sql").write_text("CREATE TABLE a (id INTEGER);")
    (tmp_path / "0003_later.sql").write_text("CREATE TABLE b (id INTEGER);")

    with pytest.raises(MigrationFilesError, match="0002"):
        load(tmp_path)


@pytest.mark.parametrize("name", ["002_short.sql", "0002-dash.sql", "0002_Upper.sql"])
def test_a_misnamed_sql_file_is_refused_instead_of_skipped(tmp_path: Path, name: str):
    (tmp_path / "0001_initial.sql").write_text("CREATE TABLE a (id INTEGER);")
    (tmp_path / name).write_text("CREATE TABLE b (id INTEGER);")

    with pytest.raises(MigrationFilesError, match=name):
        load(tmp_path)


def test_files_that_are_not_sql_are_ignored(tmp_path: Path):
    (tmp_path / "0001_initial.sql").write_text("CREATE TABLE a (id INTEGER);")
    (tmp_path / "README.md").write_text("ignored")

    assert [migration.file for migration in load(tmp_path)] == ["0001_initial.sql"]
