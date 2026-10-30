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
    # Consume the same upstream scripts as Easel's web app, frozen in this release.
    source = pathlib.Path(__file__).resolve().parents[2] / 'skills/shared/scripts'
    if not (source/'web_publisher.py').is_file():raise ValueError('Easel platform scripts are unavailable')
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
    public = {k: result.get(k) for k in ('loggedIn', 'provider_user_id', 'name','avatar')}
    print(json.dumps(public, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('{"loggedIn":false}')
