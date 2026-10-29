"""RFC 6238 TOTP and durable, owner-protected authentication state."""
import base64, hashlib, hmac, json, pathlib, re, secrets, struct, threading, time
from easel_workbench.runtime.auth_store import atomic, security

CONFIG = pathlib.Path('C:/Users/38482/AppData/Local/hermes/private/ai-news-desk-auth/totp.json')
SESSION_AGE = 30 * 24 * 60 * 60
FAILURE_WINDOW = 300
FAILURE_LIMIT = 5

def totp(secret, step, digits=6):
    key = base64.b32decode(secret + '=' * (-len(secret) % 8), casefold=True)
    value = hmac.new(key, struct.pack('>Q', step), hashlib.sha1).digest()
    offset = value[-1] & 15
    return str((struct.unpack('>I', value[offset:offset + 4])[0] & 0x7fffffff) % 10**digits).zfill(digits)

def equal(left, right):
    return hmac.compare_digest(left.encode('utf-8'), right.encode('utf-8'))

def token_hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

class AuthState:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.lock = threading.RLock()
        self.data = json.loads(self.path.read_text(encoding='utf-8'))
        if self.data.get('schema_version') != 2 or self.data.get('method') != 'totp':
            raise ValueError('TOTP authentication is not configured')
        base64.b32decode(self.data['secret'] + '=' * (-len(self.data['secret']) % 8))
        self.acl = security(self.path)

    def save(self, updated):
        atomic(self.path, json.dumps(updated, ensure_ascii=False, indent=2) + '\n', self.acl)
        self.data = updated

    def session(self, token):
        if not token or len(token) > 128:
            return None
        with self.lock:
            session = self.data['sessions'].get(token_hash(token))
            if session and session['until'] > time.time():
                return dict(session)
        return None

    def login(self, code):
        # Consuming a code and issuing its session is a single atomic write.
        with self.lock:
            now = time.time()
            updated = json.loads(json.dumps(self.data))
            updated['failures'] = [t for t in updated['failures'] if t > now - FAILURE_WINDOW]
            if len(updated['failures']) >= FAILURE_LIMIT:
                return 429, None
            step = int(now // 30)
            matched = None
            if re.fullmatch(r'[0-9]{6}', code):
                for candidate in (step, step - 1, step + 1):
                    if candidate > updated['last_step'] and equal(code, totp(updated['secret'], candidate)):
                        matched = candidate
                        break
            if matched is None:
                updated['failures'].append(now)
                self.save(updated)
                return 401, None
            updated['last_step'] = matched
            updated['sessions'] = {k: v for k, v in updated['sessions'].items() if v['until'] > now}
            if len(updated['sessions']) >= 256:
                return 429, None
            token = secrets.token_urlsafe(32)
            updated['sessions'][token_hash(token)] = {'until': now + SESSION_AGE, 'csrf': secrets.token_urlsafe(32)}
            self.save(updated)
            return 303, token

    def logout(self, token, csrf, all_sessions=False):
        with self.lock:
            session = self.session(token)
            if not session or not equal(csrf, session['csrf']):
                return False
            updated = json.loads(json.dumps(self.data))
            if all_sessions:
                updated['sessions'].clear()
                updated['mobile_devices'] = {}
            else:
                updated['sessions'].pop(token_hash(token), None)
            self.save(updated)
            return True

    def mobile_devices(self):
        return []

    def mobile_device(self, token):
        # Legacy tokens remain on disk for historical recovery, with no access.
        return None

    def create_mobile_device(self, name, store):
        raise ValueError('通知设备功能已退役')

    def update_mobile_device(self, device_id, action, store):
        raise ValueError('通知设备功能已退役')
