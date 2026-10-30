"""Per-connection Easel browser sessions, sharing the distribution ledger.

Login and whoami are explicit jobs. Public responses contain observations, never
cookie paths, cookies or platform credentials. Nicknames cannot prove identity.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import re
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
            c.execute('CREATE TABLE IF NOT EXISTS easel_native_account_bindings(platform TEXT PRIMARY KEY,session_id TEXT NOT NULL)')
        self.runner, self.autostart = runner, autostart

    def _native_session(self, platform, *, create=False):
        if platform not in PLATFORMS:
            raise ValueError('请选择已支持的平台')
        with self.store.connect() as c:
            bound = c.execute('SELECT session_id FROM easel_native_account_bindings WHERE platform=?', (platform,)).fetchone()
            if bound:
                return self._get(c, bound['session_id'])
            candidates = [json.loads(row['document']) for row in c.execute(
                "SELECT document FROM media_account_sessions WHERE json_extract(document,'$.platform')=?", (platform,))]
        if len(candidates) > 1:
            # The native page has one current login per platform. Ambiguous old
            # sessions remain untouched; a fresh native-owned browser is safe.
            if not create:
                return None
            candidates = [self.command({'id': 'native-current-account-' + platform, 'action': 'create', 'platform': platform})['result']['session']]
        if not candidates:
            if not create:
                return None
            candidates = [self.command({'id': 'native-account-' + platform, 'action': 'create', 'platform': platform})['result']['session']]
        selected = candidates[0]
        with self.store.connect() as c:
            c.execute('INSERT INTO easel_native_account_bindings VALUES(?,?) ON CONFLICT(platform) DO NOTHING', (platform, selected['id']))
        return selected

    def native_context(self):
        """Use the same native login lifecycle as Easel's default web app."""
        if not getattr(self, '_native_context', None):
            from easel.web_services.accounts import create_accounts_context
            from easel_workbench.runtime.connection_environment import service as environment_service
            from easel_workbench.runtime.easel_connection_support import safe_env
            environment = environment_service(self.box)
            python = environment.python if environment.python.is_file() else pathlib.Path(sys.executable)
            def profile_base(platform):
                session = self._native_session(platform, create=True)
                return self.root / 'data/easel-accounts' / session['id'] / ('profiles-' + str(session.get('_profile_generation', 0)))
            self._native_context = create_accounts_context(
                self.root, scripts=pathlib.Path(__file__).resolve().parents[2] / 'skills/shared/scripts',
                profiles=self.root / 'data/easel-native-browser', profile_base=profile_base,
                cookie_path=self.root / 'data/easel-native-browser/bilibili/cookies.json',
                environment=lambda: safe_env(environment.child_environment(), self.root), python=python,
                credential_store={'_wechat_web_account': lambda: {},
                                  '_wechat_clear_credentials': lambda: None},
                credentials_as_browser_login=False)
        return self._native_context

    def close_native(self):
        """Release native owned process handles without creating another context."""
        analytics = getattr(self, '_native_analytics_context', None)
        if analytics is not None:
            analytics._stop_analytics_on_shutdown()
        native = getattr(self, '_native_context', None)
        if native is not None:
            native._stop_login_processes_on_shutdown()

    def prepare_native_login(self, platform, operation_id=None):
        native = self.native_context()
        process = native.LOGIN_PROCESSES.get('wechat-oa-mp' if platform == 'wechat-oa' else platform)
        if process is not None and process.poll() is None:
            return  # Native lifecycle reuses the same process and QR.
        session = self._native_session(platform, create=True)
        if session.get('_native_logged_out'):
            if not operation_id:
                raise IntegrationConflict('新登录需要准确操作标识')
            operation = 'native-login-' + digest(operation_id)[:40]
            fresh = self.command({'id': operation, 'action': 'create', 'platform': platform})['result']['session']
            with self.store.connect() as c:
                c.execute('UPDATE easel_native_account_bindings SET session_id=? WHERE platform=?', (fresh['id'], platform))
            session = fresh
        if session.get('state') in ('login', 'checking', 'unknown') and not session.get('_native_managed'):
            raise IntegrationConflict('原账号操作尚未核对，不能另起一次登录')
        with self.store.connect() as c:
            current = self._get(c, session['id'])
            current.update(state='login', logged_in=False, _native_managed=True,
                           _auth_mode='browser', revision=current['revision'] + 1)
            self._put(c, current)

    def record_native_logout(self, platform):
        self.record_native_observation(platform, {'loggedIn': False})
        session = self._native_session(platform)
        if session is not None:
            with self.store.connect() as c:
                current = self._get(c, session['id'])
                current['_native_logged_out'] = True
                self._put(c, current)

    def record_native_observation(self, platform, result):
        """Project verified native identity into the existing delivery ledger."""
        session = self._native_session(platform, create=bool(result.get('loggedIn')))
        if session is None:
            return
        account = result.get('provider_user_id')
        verified = result.get('loggedIn') is True and isinstance(account, str) and bool(re.fullmatch(r'[A-Za-z0-9_.:@-]{1,200}', account))
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            latest = self._get(c, session['id'])
            expected = latest.get('account')
            mismatch = verified and expected and account != expected
            latest.update(state='account_mismatch' if mismatch else 'connected' if verified else 'identity_unconfirmed' if result.get('loggedIn') else 'not_connected',
                          logged_in=result.get('loggedIn') is True, identity_status='mismatch' if mismatch else 'resolved' if verified else 'not_provided',
                          name=text(str(result.get('name') or '')[:200], 200), checked_at=stamp(),
                          avatar=result.get('avatar') if isinstance(result.get('avatar'), str) and result['avatar'].startswith('https://') else '',
                          _native_managed=True, _auth_mode='browser')
            if verified and not mismatch:
                latest['account'] = account
                connection_id = latest.get('connection_id') or 'easel-' + digest(latest['id'])[:24]
                old = self.distribution._get(c, 'connections', connection_id, False)
                document = {**(old or {}), 'id': connection_id, 'platform': PLATFORMS[platform]['channel'],
                            'account': account, 'label': latest['label'], 'enabled': True,
                            'revision': (old or {}).get('revision', 0) + 1,
                            'created_at': (old or {}).get('created_at', stamp()), 'updated_at': stamp(),
                            'connector': 'easel', 'account_name': latest['name'],
                            'identity_kind': 'provider_user_id', 'identity_status': 'resolved'}
                if old and all(old.get(key) == document.get(key) for key in ('platform', 'account', 'label', 'enabled', 'connector', 'account_name', 'identity_kind', 'identity_status')):
                    document = old
                else:
                    self.distribution._put(c, 'connections', document)
                latest['connection_id'] = connection_id
            self._put(c, latest)

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
                image=base/'qr.png'
                if image.is_file() and result['login_state'] in ('qr_ready','scanned','window_login'):
                    result['qr_url'] = '/api/platform-accounts/' + session['id'] + '/qr?revision=' + str(session['revision'])+'&ts='+str(image.stat().st_mtime_ns)
            except (OSError, ValueError):
                pass
        return result

    def bootstrap(self):
        with self.store.connect() as c:
            documents=[json.loads(r['document']) for r in c.execute('SELECT document FROM media_account_sessions ORDER BY rowid')]
            if self.autostart:
                from easel_workbench.runtime.distribution_runtime import process_identity
                for item in documents:
                    if not item.get('_native_managed') and item.get('state') in ('login','checking') and item.get('_owner_identity') and process_identity(item.get('_owner_pid'))!=item['_owner_identity']:
                        item.update(state='unknown',error='原登录进程已结束；请核对身份，不会自动重放登录。')
                        self._put(c,item)
            sessions=[self._public(item) for item in documents]
        return {'platforms': [{'id': key, 'name': value['name'],'channel':value['channel'],'login_mode':'qr'} for key, value in PLATFORMS.items()], 'sessions': sessions,
                'connections': self.distribution.bootstrap()['connections']}

    def command(self, value):
        value = copy.deepcopy(value)
        operation = ident(value.get('id'))
        signature, launch = digest(value), None
        # Like Easel, acknowledge the job before starting the browser. Full
        # dependency diagnostics belong to the explicit environment screen;
        # they must not delay every login HTTP response with subprocess probes.
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM media_operations WHERE id=?', (operation,)).fetchone()
            if old:
                if old['signature'] != signature:
                    raise IntegrationConflict('同一账号操作不能更换内容')
                return json.loads(old['result'])
            action = value.get('action')
            if self.runner is None and action in ('login', 'probe', 'credentials', 'sms', 'logout'):
                raise IntegrationConflict('旧账号执行入口已退役，请使用 Easel 原生账号接口；历史回执仍可读取')
            if action == 'create':
                if value.get('platform') not in PLATFORMS:
                    raise ValueError('请选择已支持的平台')
                platform=value['platform']
                session = {'id': 'account-' + digest(operation)[:24], 'platform': platform, 'label': text(value.get('label') or PLATFORMS[platform]['name'], 120, True),
                           'revision': 1, 'state': 'not_connected', 'logged_in': False, 'identity_status': 'unconfirmed', 'created_at': stamp()}
                if value.get('connection_id'):
                    connection=self.distribution._get(c,'connections',ident(value['connection_id']),True)
                    if connection['platform']!=PLATFORMS[platform]['channel']:raise ValueError('旧账号与所选平台不一致')
                    if c.execute("SELECT 1 FROM media_account_sessions WHERE json_extract(document,'$.connection_id')=?",(connection['id'],)).fetchone():raise IntegrationConflict('此账号已有扫码连接，请使用原连接')
                    session.update(connection_id=connection['id'],account=connection['account'],label=connection.get('label') or session['label'])
            else:
                session = self._get(c, value.get('session_id'))
                if value.get('base_revision') != session['revision']:
                    raise IntegrationConflict('账号连接已有新操作，请重新核对')
                session['revision'] += 1
                if action in ('login', 'probe'):
                    if session.get('state') in ('login', 'checking'):
                        raise IntegrationConflict('原账号操作仍在进行，请先核对原任务')
                    session.update(state='login' if action == 'login' else 'checking', operation_id=operation)
                    if action=='login':
                        session['_auth_mode']='browser'
                        directory=self.root/'data/easel-accounts'/session['id']
                        for name in ('qr.png','login.json','douyin.code'):(directory/name).unlink(missing_ok=True)
                    launch = (session['id'], session['revision'], action)
                elif action == 'credentials':
                    if session['platform'] != 'wechat-oa':
                        raise ValueError('此平台使用独立浏览器登录')
                    if session.get('state') in ('login','checking'):raise IntegrationConflict('请先完成当前账号操作')
                    credentials = {'app_id': text(value.get('app_id', ''), 100, True), 'app_secret': text(value.get('app_secret', ''), 200, True)}
                    session['_secret_ref'] = self.vault.put(session['id'], credentials)
                    session['_credential_previous_state']=session['state']
                    session['_credential_previous_mode']=session.get('_auth_mode','browser')
                    session['_auth_mode']='credentials'
                    session.update(state='checking', operation_id=operation)
                    launch = (session['id'], session['revision'], 'probe')
                elif action == 'logout':
                    # Disconnect immediately. The archive remains private for
                    # investigation; future login uses a fresh profile revision.
                    session.update(state='not_connected', logged_in=False, identity_status='unconfirmed', _profile_generation=session.get('_profile_generation', 0) + 1)
                elif action=='sms':
                    code=value.get('code','')
                    state=self._public(session)
                    if session.get('state')!='login' or state.get('login_state')!='sms_required' or not isinstance(code,str) or not re.fullmatch(r'[0-9]{4,8}',code):raise ValueError('当前登录未请求有效短信验证码')
                    directory=self.root/'data/easel-accounts'/session['id'];directory.mkdir(parents=True,exist_ok=True)
                    (directory/'douyin.code').write_text(code,encoding='utf-8')
                    # The code is never copied into session/operation receipts.
                    session['revision']-=1
                else:
                    raise ValueError('不支持的账号操作')
            self._put(c, session)
            if launch:
                from easel_workbench.runtime.distribution_runtime import process_identity
                session.update(_owner_pid=os.getpid(),_owner_identity=process_identity(os.getpid()))
                self._put(c,session)
            response = {'id': operation, 'status': 'accepted' if launch else 'completed', 'result': {'session': self._public(session)}}
            c.execute('INSERT INTO media_operations VALUES(?,?,?)', (operation, signature, pack(response)))
        if launch and self.autostart:
            threading.Thread(target=self.run, args=launch, daemon=True, name='account-' + session['id']).start()
        return response

    def run(self, sid, revision, action):
        from easel_workbench.runtime.feedback_ledger import locked
        directory=self.root/'data/easel-accounts'/ident(sid)
        try:
            with locked(directory/'browser.lock',timeout=1):return self._run_locked(sid,revision,action)
        except Exception:
            with self.store.connect() as c:
                latest=self._get(c,sid)
                if latest['revision']==revision:
                    latest.update(state='unknown',error='账号操作尚未核对；请核对原连接，勿重复发起。')
                    self._put(c,latest)

    def _run_locked(self, sid, revision, action):
        with self.store.connect() as c:
            session = self._get(c, sid)
        if session['revision']!=revision or session.get('state') not in ('login','checking'):return
        directory = self.root / 'data/easel-accounts' / sid
        directory.mkdir(parents=True, exist_ok=True)
        if action=='login':
            for name in ('qr.png','login.json','douyin.code'):(directory/name).unlink(missing_ok=True)
        payload = {'session': session, 'directory': str(directory), 'action': action}
        if session.get('_secret_ref') and session.get('_auth_mode')=='credentials':
            payload['credentials'] = self.vault.get(session['_secret_ref'], sid)
        try:
            if self.runner:
                result = self.runner(payload)
            else:
                raise IntegrationConflict('旧账号执行器已退役，历史操作不会重新发起')
        except Exception:
            result = {}
        account = result.get('provider_user_id')
        from easel_workbench.runtime.distribution_catalog import plain_text
        verified = result.get('loggedIn') is True and bool(plain_text(account)) and bool(account.strip())
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            latest = self._get(c, sid)
            if latest['revision'] != revision:
                return
            if '_credential_previous_state' in latest:
                latest.update(credentials_verified=verified,credentials_checked_at=stamp(),state=latest.pop('_credential_previous_state'),_auth_mode=latest.pop('_credential_previous_mode'))
                self._put(c,latest)
                return
            expected = latest.get('account')
            mismatch = verified and expected and account != expected
            latest.update(state='account_mismatch' if mismatch else 'connected' if verified else 'identity_unconfirmed' if result.get('loggedIn') else 'not_connected',
                          logged_in=result.get('loggedIn') is True, identity_status='mismatch' if mismatch else 'resolved' if verified else 'not_provided',
                          name=text(str(result.get('name') or '')[:200], 200), checked_at=stamp(),
                          avatar=result.get('avatar') if isinstance(result.get('avatar'),str) and result['avatar'].startswith('https://') else '',
                          error='' if verified else '登录未完成或身份尚未核实，请重新扫码或核对身份。')
            if verified and not mismatch:
                latest['account'] = account
                connection_id = latest.get('connection_id') or 'easel-' + digest(sid)[:24]
                current = self.distribution._get(c, 'connections', connection_id, False)
                document = {**(current or {}),'id': connection_id, 'platform': PLATFORMS[latest['platform']]['channel'], 'account': account, 'label': latest['label'],
                            'enabled': True, 'revision': current['revision'] if current else 1, 'created_at': current['created_at'] if current else stamp(), 'updated_at': stamp()}
                document.update(connector='easel',account_name=latest['name'],identity_kind='provider_user_id',identity_status='resolved')
                if not current or any(current.get(k)!=document.get(k) for k in ('platform','account','label','enabled','connector','account_name','identity_kind','identity_status')):
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
        valid = session.get('state') == 'connected' and session.get('_auth_mode','browser')=='browser' and session.get('account') == connection['account'] and session.get('identity_status') == 'resolved'
        from easel_workbench.runtime.easel_distribution import supported_action
        supported=supported_action(session['platform'],action)
        return {'status': 'trial' if valid and supported else 'unknown' if supported else 'unsupported', 'verified': False,
                'account': connection['account'], 'account_verified': bool(valid), 'code_verified': supported,
                'checked_at': session.get('checked_at'),
                'reason': '扫码身份已核对；首次交付需明确批准试运行，按实际回执记录结果。' if valid and supported else '请先扫码连接并核对身份。' if supported else 'Easel 当前驱动未提供此动作，不能以登录成功代替能力验证。'}



def service(box, distribution=None):
    if not getattr(box, 'easel_accounts', None):
        if distribution is None:
            from easel_workbench.runtime.distribution_service import DistributionService
            distribution = DistributionService(box)
        box.easel_accounts = EaselAccounts(box, distribution)
    return box.easel_accounts
