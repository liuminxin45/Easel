"""Durable API CSRF state, scoped to the application's database."""
import re
import secrets


def csrf_token(store, initial=None):
    # Restarting the HTTP listener must not invalidate already open browser tabs.
    # An optional local-only seed preserves the current listener's token on rollout.
    value=initial if initial is not None else secrets.token_urlsafe(32)
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',value):
        raise ValueError('Invalid CSRF initialization')
    with store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS api_security(name TEXT PRIMARY KEY,value TEXT NOT NULL)')
        c.execute('INSERT OR IGNORE INTO api_security VALUES(?,?)',('csrf_v1',value))
        saved=c.execute('SELECT value FROM api_security WHERE name=?',('csrf_v1',)).fetchone()[0]
    if not isinstance(saved,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',saved):
        # Corrupt state must not silently generate a new token and break all tabs.
        raise RuntimeError('API security state unavailable')
    return saved
