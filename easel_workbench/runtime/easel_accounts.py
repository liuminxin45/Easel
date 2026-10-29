"""Per-connection Easel browser sessions, sharing the distribution ledger.

Login and whoami are explicit jobs. Public responses contain observations, never
cookie paths, cookies or platform credentials. Nicknames cannot prove identity.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import subprocess
import sys
import threading

from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.toolbox_store import ident, pack, text
from easel_workbench.runtime.easel_connection_support import ConnectionConflict as IntegrationConflict, digest

PLATFORMS = {
    'xiaohongshu': {'name': '小红书', 'channel': 'xiaohongshu_note', 'script': 'xhs_publish'},
    'douyin': {'name': '抖音', 'channel': 'douyin_video', 'script': 'douyin_publish'},
    'kuaishou': {'name': '快手', 'channel': 'kuaishou_video', 'script': 'web_publisher'},
    'weixin-channels': {'name': '微信视频号', 'channel': 'channels_video', 'script': 'web_publisher'},
    'zhihu': {'name': '知乎', 'channel': 'zhihu_article', 'script': 'web_publisher'},
    'bilibili': {'name': 'B站', 'channel': 'bilibili_video', 'script': 'bili_login'},
    'wechat-oa': {'name': '微信公众号', 'channel': 'wechat_article', 'script': 'credential'},
}


class EaselAccounts:
    def __init__(self, box, distribution, *, runner=None, autostart=True, vault=None):
        self.box, self.store, self.root, self.distribution = box, box.store, pathlib.Path(box.root), distribution
        from easel_workbench.runtime.distribution_runtime import DPAPIVault
        # Keep legacy table names and vault location so existing operation IDs,
        # sessions and encrypted credentials remain readable. No media service.
        self.vault = vault or DPAPIVault(self.root / 'data/media-vault')
        with self.store.connect() as c:
            c.executescript('CREATE TABLE IF NOT EXISTS media_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL); CREATE TABLE IF NOT EXISTS media_account_sessions(id TEXT PRIMARY KEY,document TEXT NOT NULL);')
        self.runner, self.autostart = runner, autostart

    def _get(self, c, sid):
        row = c.execute('SELECT document FROM media_account_sessions WHERE id=?', (ident(sid),)).fetchone()
        if not row:
            raise ValueError('账号连接不存在')
        return json.loads(row['document'])

    def _put(self, c, session):
        c.execute('INSERT INTO media_account_sessions VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document', (session['id'], pack(session)))

    def _public(self, session):
        result = {k: v for k, v in session.items() if not k.startswith('_')}
        base = self.root / 'data/easel-accounts' / session['id']
        state = base / 'login.json'
        if state.is_file() and session.get('state') == 'login':
            try:
                observation = json.loads(state.read_text(encoding='utf-8'))
                result['login_state'] = observation.get('state', 'unknown')
                if (base / 'qr.png').is_file() and result['login_state'] == 'qr_ready':
                    result['qr_url'] = '/api/platform-accounts/' + session['id'] + '/qr?revision=' + str(session['revision'])
            except (OSError, ValueError):
                pass
        return result

    def bootstrap(self):
        with self.store.connect() as c:
            sessions = [self._public(json.loads(r['document'])) for r in c.execute('SELECT document FROM media_account_sessions ORDER BY rowid')]
        return {'platforms': [{'id': key, 'name': value['name']} for key, value in PLATFORMS.items()], 'sessions': sessions,
                'connections': self.distribution.bootstrap()['connections']}

    def command(self, value):
        value = copy.deepcopy(value)
        operation = ident(value.get('id'))
        signature, launch = digest(value), None
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM media_operations WHERE id=?', (operation,)).fetchone()
            if old:
                if old['signature'] != signature:
                    raise IntegrationConflict('同一账号操作不能更换内容')
                return json.loads(old['result'])
            action = value.get('action')
            if action == 'create':
                if value.get('platform') not in PLATFORMS:
                    raise ValueError('请选择已支持的平台')
                session = {'id': 'account-' + digest(operation)[:24], 'platform': value['platform'], 'label': text(value.get('label', ''), 120, True),
                           'revision': 1, 'state': 'not_connected', 'logged_in': False, 'identity_status': 'unconfirmed', 'created_at': stamp()}
            else:
                session = self._get(c, value.get('session_id'))
                if value.get('base_revision') != session['revision']:
                    raise IntegrationConflict('账号连接已有新操作，请重新核对')
                session['revision'] += 1
                if action in ('login', 'probe'):
                    if session.get('state') in ('login', 'checking'):
                        raise IntegrationConflict('原账号操作仍在进行，请先核对原任务')
                    session.update(state='login' if action == 'login' else 'checking', operation_id=operation)
                    if action=='login':session['_auth_mode']='browser'
                    launch = (session['id'], session['revision'], action)
                elif action == 'credentials':
                    if session['platform'] != 'wechat-oa':
                        raise ValueError('此平台使用独立浏览器登录')
                    credentials = {'app_id': text(value.get('app_id', ''), 100, True), 'app_secret': text(value.get('app_secret', ''), 200, True)}
                    session['_secret_ref'] = self.vault.put(session['id'], credentials)
                    session['_auth_mode']='credentials'
                    session.update(state='checking', operation_id=operation)
                    launch = (session['id'], session['revision'], 'probe')
                elif action == 'logout':
                    # Disconnect immediately. The archive remains private for
                    # investigation; future login uses a fresh profile revision.
                    session.update(state='not_connected', logged_in=False, identity_status='unconfirmed', _profile_generation=session.get('_profile_generation', 0) + 1)
                else:
                    raise ValueError('不支持的账号操作')
            self._put(c, session)
            response = {'id': operation, 'status': 'accepted' if launch else 'completed', 'result': {'session': self._public(session)}}
            c.execute('INSERT INTO media_operations VALUES(?,?,?)', (operation, signature, pack(response)))
        if launch and self.autostart:
            threading.Thread(target=self.run, args=launch, daemon=True, name='account-' + session['id']).start()
        return response

    def run(self, sid, revision, action):
        with self.store.connect() as c:
            session = self._get(c, sid)
        directory = self.root / 'data/easel-accounts' / sid
        directory.mkdir(parents=True, exist_ok=True)
        payload = {'session': session, 'directory': str(directory), 'action': action}
        if session.get('_secret_ref'):
            payload['credentials'] = self.vault.get(session['_secret_ref'], sid)
        try:
            if self.runner:
                result = self.runner(payload)
            else:
                from easel_workbench.runtime.connection_environment import service as environment_service
                env = environment_service(self.box)
                python = env.python if env.python.is_file() else pathlib.Path(sys.executable)
                completed = subprocess.run([str(python), str(pathlib.Path(__file__).with_name('easel_account_worker.py'))], input=pack(payload), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                result = json.loads(completed.stdout) if completed.returncode == 0 else {}
        except Exception:
            result = {}
        account = result.get('provider_user_id')
        verified = result.get('loggedIn') is True and isinstance(account, str) and bool(account.strip()) and len(account) <= 200
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            latest = self._get(c, sid)
            if latest['revision'] != revision:
                return
            expected = latest.get('account')
            mismatch = verified and expected and account != expected
            latest.update(state='account_mismatch' if mismatch else 'connected' if verified else 'identity_unconfirmed' if result.get('loggedIn') else 'not_connected',
                          logged_in=result.get('loggedIn') is True, identity_status='mismatch' if mismatch else 'resolved' if verified else 'not_provided',
                          name=text(str(result.get('name', ''))[:200], 200), checked_at=stamp())
            if verified and not mismatch:
                latest['account'] = account
                connection_id = latest.get('connection_id') or 'easel-' + digest(sid)[:24]
                current = self.distribution._get(c, 'connections', connection_id, False)
                document = {'id': connection_id, 'platform': PLATFORMS[latest['platform']]['channel'], 'account': account, 'label': latest['label'],
                            'enabled': True, 'revision': current['revision'] if current else 1, 'created_at': current['created_at'] if current else stamp(), 'updated_at': stamp()}
                if not current or any(current.get(k)!=document.get(k) for k in ('platform','account','label','enabled')):
                    if current:document['revision']+=1
                    self.distribution._put(c, 'connections', document)
                latest['connection_id'] = connection_id
            self._put(c, latest)

    def session_for(self, connection):
        with self.store.connect() as c:
            row = c.execute("SELECT document FROM media_account_sessions WHERE json_extract(document,'$.connection_id')=?", (connection['id'],)).fetchone()
        return json.loads(row['document']) if row else None

    def capability(self, connection, action):
        session = self.session_for(connection)
        if not session:
            return None
        valid = session.get('state') == 'connected' and session.get('account') == connection['account'] and session.get('identity_status') == 'resolved'
        return {'status': 'unsupported', 'verified': False,
                'account': connection['account'], 'account_verified': bool(valid), 'code_verified': False,
                'checked_at': session.get('checked_at'),
                'reason': '此连接仅用于登录与身份核对；未接入 Easel 的草稿、发布或数据读取'}



def service(box, distribution=None):
    if not getattr(box, 'easel_accounts', None):
        if distribution is None:
            from easel_workbench.runtime.distribution_service import DistributionService
            distribution = DistributionService(box)
        box.easel_accounts = EaselAccounts(box, distribution)
    return box.easel_accounts
