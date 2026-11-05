import sqlite3
import threading
from collections.abc import Generator
from contextlib import closing
from pathlib import Path

import pytest

from ynab_unlinked.core.progress import NullProgress
from ynab_unlinked.store import Store, StoreError
from ynab_unlinked.store.migrations import (
    MIGRATIONS,
    SCHEMA_VERSION,
    Migration,
    MigrationError,
    MigrationFilesError,
    apply,
    load,
    statements,
    version_of,
)


@pytest.fixture
def conn() -> Generator[sqlite3.Connection]:
    with closing(sqlite3.connect(":memory:")) as connection:
        yield connection


def test_the_scripts_are_numbered_from_one_without_gaps():
    assert [migration.number for migration in MIGRATIONS] == list(range(1, SCHEMA_VERSION + 1))
    assert all(migration.sql.strip() for migration in MIGRATIONS)


def test_each_script_applies_on_top_of_the_previous_one(conn: sqlite3.Connection):
    assert apply(conn) == SCHEMA_VERSION
    assert version_of(conn) == SCHEMA_VERSION


def test_only_the_scripts_the_store_has_not_seen_run(conn: sqlite3.Connection):
    scripts = (
        Migration(1, "0001_a.sql", "CREATE TABLE a (id INTEGER);"),
        Migration(2, "0002_b.sql", "CREATE TABLE b (id INTEGER);"),
    )
    conn.execute("CREATE TABLE a (id INTEGER)")
    conn.execute("PRAGMA user_version = 1")

    assert apply(conn, scripts) == 2  # 0001 would fail: table a exists

    assert conn.execute("SELECT count(*) FROM b").fetchone()[0] == 0


def test_a_failing_script_rolls_back_and_leaves_the_version_alone(conn: sqlite3.Connection):
    scripts = (Migration(1, "0001_bad.sql", "CREATE TABLE a (id INTEGER); CREATE TABLE a (x);"),)

    with pytest.raises(MigrationError, match="0001_bad.sql"):
        apply(conn, scripts)

    assert version_of(conn) == 0
    assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0


def test_a_script_runs_once_when_another_connection_applied_it_while_this_one_waited(
    tmp_path: Path,
):
    path = tmp_path / "store.sqlite"
    scripts = (
        Migration(
            1,
            "0001_refill.sql",
            "CREATE TABLE IF NOT EXISTS a (id INTEGER); DELETE FROM a; INSERT INTO a VALUES (1);"
            " INSERT INTO a VALUES (2);",
        ),
    )
    waiting = threading.Event()

    class Waiting(NullProgress):
        def info(self, message: str) -> None:
            waiting.set()

    def second() -> None:
        with closing(sqlite3.connect(path, timeout=10)) as other:
            apply(other, scripts, progress=Waiting())

    with closing(sqlite3.connect(path)) as first:
        # The first connection holds the write lock: the second read version 0 and waits
        first.execute("BEGIN IMMEDIATE")
        thread = threading.Thread(target=second)
        thread.start()
        assert waiting.wait(5)
        first.execute("CREATE TABLE a (id INTEGER)")
        first.execute("INSERT INTO a VALUES (10)")
        first.execute("PRAGMA user_version = 1")
        first.execute("COMMIT")
        thread.join(10)

        assert not thread.is_alive()
        assert first.execute("SELECT id FROM a").fetchall() == [(10,)]
        assert version_of(first) == 1


def test_a_script_is_split_into_its_statements():
    sql = (
        "-- a comment; with a semicolon\n"
        "CREATE TABLE a (id TEXT);\n"
        "INSERT INTO a VALUES ('x;y');\n"
        "CREATE TRIGGER t AFTER INSERT ON a BEGIN DELETE FROM a WHERE id = 'z'; END;\n"
    )

    found = statements(sql)

    assert len(found) == 3
    assert found[1] == "INSERT INTO a VALUES ('x;y');"
    assert found[2].startswith("CREATE TRIGGER") and found[2].endswith("END;")


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
