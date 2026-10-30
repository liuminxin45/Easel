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
                    if item.get('state') in ('login','checking') and item.get('_owner_identity') and process_identity(item.get('_owner_pid'))!=item['_owner_identity']:
                        item.update(state='unknown',error='原登录进程已结束；请核对身份，不会自动重放登录。')
                        self._put(c,item)
            sessions=[self._public(item) for item in documents]
        return {'platforms': [{'id': key, 'name': value['name'],'channel':value['channel'],'login_mode':'qr'} for key, value in PLATFORMS.items()], 'sessions': sessions,
                'connections': self.distribution.bootstrap()['connections']}

    def command(self, value):
        value = copy.deepcopy(value)
        operation = ident(value.get('id'))
        signature, launch = digest(value), None
        if self.autostart and self.runner is None and value.get('action') in ('login','probe'):
            # Re-reading an accepted operation never depends on today's environment.
            with self.store.connect() as c:
                old=c.execute('SELECT signature,result FROM media_operations WHERE id=?',(operation,)).fetchone()
                if old:
                    if old['signature']!=signature:raise IntegrationConflict('同一账号操作不能更换内容')
                    return json.loads(old['result'])
                platform=self._get(c,value.get('session_id'))['platform']
            from easel_workbench.runtime.connection_environment import service
            needed='biliup' if platform=='bilibili' else 'browser'
            if not any(row['id']==needed and row['state']=='ok' for row in service(self.box).check()['tools']):raise ValueError('请先在账号页安装平台连接依赖，再重新扫码。')
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
                from easel_workbench.runtime.connection_environment import service as environment_service
                env = environment_service(self.box)
                python = env.python if env.python.is_file() else pathlib.Path(sys.executable)
                completed = subprocess.run([str(python), str(pathlib.Path(__file__).with_name('easel_account_worker.py'))], input=pack(payload), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                result = json.loads(completed.stdout) if completed.returncode == 0 else {}
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
