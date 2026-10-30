"""Synthetic filesystem interleavings and SQLite diagnostics; no production I/O."""
import datetime as dt
import importlib.util
import json
import os
import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from easel_workbench.runtime import server_logging as journal

if os.environ.get('WORKBENCH_LOGGING_CANDIDATE'):
    spec = importlib.util.spec_from_file_location('cleanup_candidate', pathlib.Path(os.environ['WORKBENCH_LOGGING_CANDIDATE']) / 'server_logging.py')
    journal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(journal)


class CleanupSafety(unittest.TestCase):
    def sink(self, directory):
        sink = journal.Journal.__new__(journal.Journal)
        sink.directory = pathlib.Path(directory)
        sink.clock = lambda: dt.datetime(2026, 10, 29, 9, 30, tzinfo=dt.timezone.utc).timestamp()
        sink.handle = None
        sink.failures = 0
        return sink

    def test_another_cleaner_already_deleted_the_expired_file(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = self.sink(directory)
            expired = sink.directory / 'worker-2026102108-abcdef-1.jsonl'
            expired.write_text('{}\n', encoding='utf-8')
            snapshot = list(sink.directory.iterdir())

            def after_peer_cleanup(_path):
                expired.unlink()
                return iter(snapshot)

            with patch.object(pathlib.Path, 'iterdir', after_peer_cleanup):
                sink.cleanup()
            self.assertFalse(expired.exists())
            self.assertEqual(sink.failures, 0)

    def test_access_failure_is_still_counted_and_file_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = self.sink(directory)
            expired = sink.directory / 'local-2026102108-abcdef-1.jsonl'
            expired.write_text('{}\n', encoding='utf-8')
            with patch.object(pathlib.Path, 'unlink', side_effect=PermissionError(13, 'synthetic denial')):
                sink.cleanup()
            self.assertTrue(expired.exists())
            self.assertEqual(sink.failures, 1)

    def test_partial_boundary_hour_and_unowned_files_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = self.sink(directory)
            expired = sink.directory / 'learning-2026102208-abcdef-1.jsonl'
            boundary = sink.directory / 'learning-2026102209-abcdef-2.jsonl'
            unrelated = sink.directory / 'failure-report.json'
            for path in (expired, boundary, unrelated):
                path.write_text('{}\n', encoding='utf-8')
            sink.cleanup()
            self.assertFalse(expired.exists())
            self.assertTrue(boundary.exists())
            self.assertTrue(unrelated.exists())
            self.assertEqual(sink.failures, 0)

    def test_sqlite_code_is_reported_without_query_or_exception_message(self):
        with sqlite3.connect(':memory:') as connection:
            try:
                connection.execute('SELECT * FROM private_synthetic_marker')
            except sqlite3.Error as error:
                with patch.object(journal, 'emit') as emit:
                    journal.exception('synthetic_database_error', error)
                fields = emit.call_args.kwargs
                self.assertEqual(fields['sqlite_errorcode'], sqlite3.SQLITE_ERROR)
                self.assertEqual(fields['sqlite_errorname'], 'SQLITE_ERROR')
                self.assertNotIn('private_synthetic_marker', repr(fields))
                self.assertNotIn('message', fields)

    def test_only_typed_sqlite_metadata_reaches_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = journal.Journal(directory, 'server')
            sink.emit('synthetic_database_error', sqlite_errorcode=5, sqlite_errorname='SQLITE_BUSY', message='private-marker')
            sink.emit('synthetic_invalid_metadata', sqlite_errorcode=True, sqlite_errorname='private-marker')
            sink.close()
            rows = [json.loads(line) for path in pathlib.Path(directory).glob('*.jsonl') for line in path.read_text().splitlines()]
            valid = next(row for row in rows if row['event'] == 'synthetic_database_error')
            invalid = next(row for row in rows if row['event'] == 'synthetic_invalid_metadata')
            self.assertEqual(valid['sqlite_errorcode'], 5)
            self.assertEqual(valid['sqlite_errorname'], 'SQLITE_BUSY')
            self.assertNotIn('sqlite_errorcode', invalid)
            self.assertNotIn('sqlite_errorname', invalid)
            self.assertNotIn('private-marker', repr(rows))


if __name__ == '__main__':
    unittest.main()
