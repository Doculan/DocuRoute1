"""Tests that commit, and the rows the migrations put in the database.

A test that commits cannot be rolled back, so Django flushes the database
after it - and with it the rows migrations inserted: the preset deadline
types, the monitoring thresholds, the system log's first event and head.
Every test after it then ran on a database the application never sees;
`seed_scale` failed in the full suite that way, after the race test in
`tests_proposals`.

Django's `serialized_rollback` does not cure it, for two reasons found
here: it reloads the saved rows at the *start* of the flagged test and
still flushes at its end; and its serializer keeps timestamps only to the
millisecond, so the log's first event came back with a different time
than the one its hash was computed over, and the chain failed to verify.

So the test runner keeps an exact copy - every table, row for row - as
soon as it has migrated the test database (`snapshot`), and a test that
commits uses `KeepsMigrationData`, which writes that copy back after the
flush. The next test finds the database exactly as migrated.
"""

from django.db import connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor

MIGRATED = {}


def snapshot(conn):
    """{table: (columns, rows)} for every table that holds rows."""
    saved = {}
    with conn.cursor() as cursor:
        for table in conn.introspection.table_names(cursor):
            cursor.execute(f'SELECT * FROM "{table}"')
            rows = cursor.fetchall()
            if rows:
                saved[table] = ([col[0] for col in cursor.description], rows)
    return saved


def restore(conn, saved):
    """Write a snapshot back over the flushed tables. The flush's
    post_migrate signal has already remade content types and permissions,
    so each table is emptied first. Foreign keys are checked at commit, so
    the order of tables does not matter."""
    with transaction.atomic(using=conn.alias), conn.cursor() as cursor:
        for table, (columns, rows) in saved.items():
            cursor.execute(f'DELETE FROM "{table}"')
            names = ', '.join(f'"{col}"' for col in columns)
            marks = ', '.join(['%s'] * len(columns))
            cursor.executemany(f'INSERT INTO "{table}" ({names}) VALUES ({marks})', rows)


class KeepsMigrationData:
    """For a test class that commits. Put it before the TestCase base."""

    def _fixture_teardown(self):
        super()._fixture_teardown()
        for alias in self._databases_names(include_mirrors=False):
            restore(connections[alias], MIGRATED[alias])


def migrate_to_latest():
    """A migration test ends here, so the copy meets the current schema."""
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())
