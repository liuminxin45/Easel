"""Independent, atomic controller state. No application imports or state writes."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import tempfile
import time


class StateError(ValueError):
    pass


class StateStore:
    def __init__(self, runtime_root):
        self.root = Path(runtime_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+\.json', name):
            raise StateError('invalid_state_name')
        path = self.root / name
        if path.is_symlink():
            raise StateError('linked_state_file')
        return path

    def read(self, name, default=None):
        path = self.path(name)
        try:
            if path.stat().st_size > 4 * 1024 * 1024:
                raise StateError('oversized_state')
            value = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return default
        except (OSError, ValueError) as error:
            raise StateError('unreadable_state') from error
        if not isinstance(value, dict):
            raise StateError('invalid_state_document')
        return value

    def write(self, name, value):
        path = self.path(name)
        raw = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()
        descriptor, temporary = tempfile.mkstemp(prefix='.write-', suffix='.tmp', dir=self.root)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            for attempt in range(4):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(.025 * (attempt + 1))
        finally:
            try: os.unlink(temporary)
            except FileNotFoundError: pass

    def policy(self):
        """A deleted/corrupt budget must never become a fresh budget."""
        try:
            value = self.read('policy.json')
            if value is None:
                return None if self.path('policy-initialized.json').exists() else {}
            return value
        except StateError:
            return None

    def save_policy(self, value):
        self.write('policy-initialized.json', {'schema': 1})
        self.write('policy.json', value)

    def event(self, kind, **fields):
        if not re.fullmatch(r'[a-z_]{1,64}', kind):
            raise StateError('invalid_event_kind')
        allowed = {'at', 'operation_id', 'action', 'outcome', 'reason', 'error_type',
                   'binding', 'identity', 'decision', 'failure_count', 'seconds', 'source'}
        record = {'kind': kind, **{key: value for key, value in fields.items() if key in allowed}}
        # Callers pass fixed diagnostic codes, never raw HTTP/exception text.
        with (self.root / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    @contextmanager
    def lock(self):
        path = self.root / 'controller.lock'
        if path.is_symlink():
            raise StateError('linked_lock')
        with path.open('a+b') as stream:
            if stream.tell() == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                try: yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                try: yield
                finally: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
