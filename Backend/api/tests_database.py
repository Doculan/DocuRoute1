"""The database settings, under the concurrency the application actually has.

**A transaction that reads before it writes must wait for the lock, not
fail.** By default SQLite begins a transaction as a reader and upgrades it
at the first write; if another connection has written in between, the
upgrade is refused at once - "database is locked" - and the busy timeout
is never consulted. Found in a real run: saving a section a moment after
the reason field had saved itself. `transaction_mode: IMMEDIATE` takes the
write lock when the transaction begins, so the second writer waits its turn.

Run through Django's own SQLite backend with the project's options, on a
file of its own - the test database is in memory, where there is no
second connection to collide with.
"""

import os
import shutil
import tempfile
import threading
import time

from django.db.backends.sqlite3.base import DatabaseWrapper
from django.test import SimpleTestCase

from backend.settings import SQLITE_OPTIONS


def _connection(path):
    wrapper = DatabaseWrapper({
        'ENGINE': 'django.db.backends.sqlite3', 'NAME': path,
        'OPTIONS': dict(SQLITE_OPTIONS),
        'ATOMIC_REQUESTS': False, 'AUTOCOMMIT': True, 'CONN_MAX_AGE': 0,
        'CONN_HEALTH_CHECKS': False, 'TIME_ZONE': None, 'USER': '',
        'PASSWORD': '', 'HOST': '', 'PORT': '', 'TEST': {},
    }, alias='lock-test')
    wrapper.ensure_connection()
    return wrapper


class ReadThenWriteTests(SimpleTestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, 'locks.sqlite3')
        setup = _connection(self.path)
        with setup.cursor() as cursor:
            cursor.execute('create table t (id integer primary key, v text)')
            cursor.execute("insert into t values (1, 'a')")
        setup.close()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_a_transaction_that_reads_first_waits_for_another_writer(self):
        outcome = {}

        def other_writer():
            other = _connection(self.path)
            time.sleep(0.2)
            with other.cursor() as cursor:
                cursor.execute("update t set v = 'other' where id = 1")
            outcome['other'] = 'written'
            other.close()

        mine = _connection(self.path)
        writer = threading.Thread(target=other_writer)
        writer.start()
        try:
            # What `transaction.atomic()` does on SQLite when it opens: BEGIN,
            # or BEGIN IMMEDIATE under `transaction_mode`.
            mine._start_transaction_under_autocommit()
            with mine.cursor() as cursor:
                cursor.execute('select v from t where id = 1').fetchone()
                time.sleep(0.5)          # the other connection writes now
                cursor.execute("insert into t values (2, 'mine')")
            mine.connection.commit()
            outcome['mine'] = 'written'
        except Exception as error:      # noqa: BLE001 - the error is the finding
            outcome['mine'] = str(error)
            mine.connection.rollback()
        finally:
            writer.join()
            mine.close()

        self.assertEqual(outcome, {'mine': 'written', 'other': 'written'})
