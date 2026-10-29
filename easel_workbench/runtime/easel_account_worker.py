"""Easel account adapters in a dedicated process with a private browser root."""

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))

import argparse
import contextlib
import importlib
import io
import json
import os
import pathlib
import sys
import urllib.request

from easel_workbench.runtime.easel_connection_support import safe_env


def main():
    payload = json.load(sys.stdin)
    if payload.get('action') not in ('login', 'probe'):
        raise ValueError('Platform connections only support login and identity checks')
    session, directory = payload['session'], pathlib.Path(payload['directory']).resolve()
    environment = safe_env({}, directory)
    toolroot = pathlib.Path(__file__).resolve().parent / '.runtime/media-tools'
    # The parent supplies a project-specific path for candidates and tests.
    toolroot = directory.parents[2] / '.runtime/media-tools'
    environment['PLAYWRIGHT_BROWSERS_PATH'] = str(toolroot / 'browsers')
    os.environ.clear()
    os.environ.update(environment)
    os.chdir(directory)
    source = pathlib.Path(__file__).resolve().parent / 'vendor/easel/scripts'
    sys.path.insert(0, str(source))
    platform = session['platform']
    if platform == 'wechat-oa' and session.get('_auth_mode')=='credentials':
        from urllib.parse import urlencode
        credentials = payload.get('credentials') or {}
        query = urlencode({'grant_type': 'client_credential', 'appid': credentials.get('app_id', ''), 'secret': credentials.get('app_secret', '')})
        # An explicit single token check, with no token in stdout or logs.
        with urllib.request.urlopen('https://api.weixin.qq.com/cgi-bin/token?' + query, timeout=30) as response:
            token = json.load(response)
        result = {'loggedIn': bool(token.get('access_token')), 'provider_user_id': credentials.get('app_id') if token.get('access_token') else None, 'name': session['label']}
    else:
        name = 'weixin_mp_stats' if platform=='wechat-oa' else 'xhs_publish' if platform == 'xiaohongshu' else 'douyin_publish' if platform == 'douyin' else 'bili_login' if platform == 'bilibili' else 'web_publisher'
        module = importlib.import_module(name)
        profile = directory / ('profiles-' + str(session.get('_profile_generation', 0)))
        profile.mkdir(exist_ok=True)
        if platform == 'bilibili':
            args = ['login' if payload['action'] == 'login' else 'whoami', '--cookie', str(profile / 'cookies.json')]
        else:
            args = ['login-qr' if payload['action'] == 'login' and name == 'web_publisher' else 'login' if payload['action'] == 'login' else 'whoami', '--profile-base', str(profile)]
            if name == 'web_publisher':
                args += ['--platform', platform]
        if payload['action'] == 'login':
            args += ['--qr-out', str(directory / 'qr.png'), '--status-file', str(directory / 'login.json'), '--timeout', '180']
        # Preserve real stable IDs that Easel's display-only whoami omits.
        original_identity = getattr(module, '_account_identity', None)
        if original_identity:
            def identity(account, *args, **kwargs):
                result = original_identity(account, *args, **kwargs)
                if not isinstance(result,dict):return result
                if platform=='wechat-oa' and hasattr(account,'evaluate'):
                    observed=account.evaluate("() => ({user_name:window.wx?.data?.user_name,app_id:window.wx?.data?.app_id})")
                    uid=observed.get('user_name') or observed.get('app_id')
                    if isinstance(uid,str) and __import__('re').fullmatch(r'(?:gh_|wx)[A-Za-z0-9_]{4,100}',uid):result['provider_user_id']=uid
                if isinstance(account, dict):
                    uid = account.get('userId') or account.get('id') or account.get('uid') or account.get('finderUsername')
                    if platform=='douyin':
                        body=account.get('body') or {}; user=body.get('user_info') or body.get('user') or {}
                        if result is not None:uid=user.get('uid') or user.get('sec_uid') or user.get('open_id')
                    if uid:
                        result['provider_user_id'] = str(uid)
                return result
            module._account_identity = identity
        visible_identity=getattr(module,'_visible_account_identity',None)
        if visible_identity:
            def visible(page,cfg):
                result=visible_identity(page,cfg)
                try:
                    if platform=='zhihu':
                        actual=module._authenticated_account(page.context,cfg)
                        if actual and actual.get('id'):result['provider_user_id']=str(actual['id'])
                    elif platform=='kuaishou':
                        import platform_readback
                        actual=platform_readback.read_kuaishou_account(page)
                        if actual.get('platform_account_id'):result['provider_user_id']=str(actual['platform_account_id'])
                except Exception:pass
                return result
            module._visible_account_identity=visible
        observed_identity={}
        if platform=='bilibili':
            original_api=module._api
            def api(url,*args,**kwargs):
                result=original_api(url,*args,**kwargs)
                nav=result.get('data') or {}
                if nav.get('isLogin') is True and nav.get('mid'):observed_identity['id']=str(nav['mid'])
                return result
            module._api=api
        sys.argv = [str(source / (name + '.py')), *args]
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(io.StringIO()):
            module.main()
        result = {}
        if payload['action'] == 'login':
            # Login completion is followed by an explicit whoami within this job.
            payload['action'] = 'probe'
            # Re-run only the read-only identity command; never a publication.
            args = ['whoami', '--cookie', str(profile / 'cookies.json')] if platform == 'bilibili' else ['whoami', '--profile-base', str(profile)] + (['--platform', platform] if name == 'web_publisher' else [])
            sys.argv = [str(source / (name + '.py')), *args]
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(io.StringIO()):
                module.main()
        for line in reversed(capture.getvalue().splitlines()):
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    result = value
                    break
            except ValueError:
                continue
        if platform=='bilibili' and observed_identity.get('id') and result.get('loggedIn') is True:result['provider_user_id']=observed_identity['id']
    public = {k: result.get(k) for k in ('loggedIn', 'provider_user_id', 'name')}
    print(json.dumps(public, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('{"loggedIn":false}')
