"""Session-revocable, image-only URLs for browser/native image downloaders.

Some mobile downloaders do not share the page's cookie jar. Give the rendered
image a narrowly scoped read capability instead of exposing a session token or
making the private file API public. These URLs are never persisted by the app.
"""
import hashlib
import hmac
import json
import re
import time
import urllib.parse

from easel_workbench.runtime.auth_totp import token_hash

IMAGE_TYPES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif', 'image/bmp'}
WINDOW = 3600


def _signature(value, session, reference, expires):
    payload = json.dumps(['image-read-v1', reference, value['id'], value['name'], value['mime'], expires],
                         ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hmac.new(session['csrf'].encode('ascii'), payload, hashlib.sha256).hexdigest()


def image_url(value, session, token, now=None):
    if value.get('mime') not in IMAGE_TYPES:
        return None
    now = time.time() if now is None else now
    # Stable within an hour, so polling does not reload every image. The URL
    # expires in at most two hours, and logout revokes it immediately.
    expires = min((int(now) // WINDOW + 2) * WINDOW, int(session['until']))
    reference = token_hash(token)
    query = urllib.parse.urlencode({'expires': expires, 'session': reference,
                                    'signature': _signature(value, session, reference, expires)})
    return '/media/images/' + value['id'] + '/' + urllib.parse.quote(value['name'], safe='') + '?' + query


def read_session(auth, query, now=None):
    """Reject unsigned/expired requests before touching captured files."""
    if set(query) - {'expires', 'session', 'signature', 'download'} or any(len(query.getlist(k)) != 1 for k in query):
        return None
    reference, expires, signature = (query.get(k, '') for k in ('session', 'expires', 'signature'))
    if not re.fullmatch(r'[a-f0-9]{64}', reference) or not re.fullmatch(r'[a-f0-9]{64}', signature) or not re.fullmatch(r'[0-9]{1,11}', expires):
        return None
    if query.get('download') not in (None, '1'):
        return None
    now = time.time() if now is None else now
    expires = int(expires)
    if not now < expires <= now + 2 * WINDOW:
        return None
    with auth.lock:
        session = auth.data['sessions'].get(reference)
        if not session or session['until'] <= now or expires > int(session['until']):
            return None
        return reference, expires, dict(session)


def authorize(value, auth, query, now=None):
    credentials = read_session(auth, query, now)
    if value.get('mime') not in IMAGE_TYPES or not credentials:
        return False
    reference, expires, session = credentials
    return hmac.compare_digest(query['signature'], _signature(value, session, reference, expires))
