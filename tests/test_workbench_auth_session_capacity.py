import threading


def test_legacy_sessions_get_seven_day_grace_without_deleting_any(tmp_path,monkeypatch):
    import json
    from easel_workbench.runtime import auth_totp
    now=1_800_000_000;monkeypatch.setattr(auth_totp.time,'time',lambda:now)
    path=tmp_path/'auth.json';path.write_text(json.dumps({'schema_version':2,'method':'totp','secret':'JBSWY3DPEHPK3PXP',
        'sessions':{'legacy':{'until':now+30*86400,'csrf':'keep'},'short':{'until':now+50,'csrf':'keep'}}}),encoding='utf8')
    monkeypatch.setattr(auth_totp,'security',lambda _path:None)
    monkeypatch.setattr(auth_totp,'atomic',lambda path,text,_acl:path.write_text(text,encoding='utf8'))
    state=auth_totp.AuthState(path)
    assert state.data['sessions']['legacy']['until']==now+7*86400
    assert state.data['sessions']['short']['until']==now+50
    assert len(state.data['sessions'])==2


def test_owner_login_preserves_over_256_live_sessions_and_cleans_expired(monkeypatch):
    from easel_workbench.runtime import auth_totp
    now=1_800_000_000
    monkeypatch.setattr(auth_totp.time,'time',lambda:now)
    state=auth_totp.AuthState.__new__(auth_totp.AuthState)
    state.lock=threading.RLock()
    state.data={'secret':'JBSWY3DPEHPK3PXP','last_step':-1,'failures':[],
                'sessions':{**{str(i):{'until':now+100,'csrf':'keep'} for i in range(300)},
                            'expired':{'until':now-1,'csrf':'old'}}}
    state.save=lambda value:setattr(state,'data',value)
    code=auth_totp.totp(state.data['secret'],now//30)
    status,token=state.login(code)
    assert status==303 and token and len(state.data['sessions'])==301
    assert all(str(i) in state.data['sessions'] for i in range(300))
    assert 'expired' not in state.data['sessions']
    assert state.login(code)==(401,None)


def test_seven_day_sliding_expiry_is_bounded_and_expired_tokens_stay_expired(monkeypatch):
    from easel_workbench.runtime import auth_totp
    clock=[1_800_000_000];monkeypatch.setattr(auth_totp.time,'time',lambda:clock[0])
    state=auth_totp.AuthState.__new__(auth_totp.AuthState);state.lock=threading.RLock()
    token='test-session';key=auth_totp.token_hash(token);writes=[]
    state.data={'sessions':{key:{'until':clock[0]+auth_totp.SESSION_AGE,'csrf':'keep'}}}
    state.save=lambda value:(writes.append(True),setattr(state,'data',value))
    assert auth_totp.SESSION_AGE==7*24*60*60
    assert not state.session(token)['_renew_cookie']
    clock[0]+=auth_totp.SESSION_TOUCH_INTERVAL
    value=state.session(token)
    assert value['_renew_cookie'] and value['until']==clock[0]+auth_totp.SESSION_AGE and len(writes)==1
    clock[0]+=auth_totp.SESSION_AGE
    assert state.session(token) is None


def test_renewed_auth_response_refreshes_secure_cookie(tmp_path):
    import importlib.util,json,httpx
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('session_cookie_fixture',root/'tests/workbench_native_browser.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    native=tmp_path/'native-test';native.mkdir()
    (native/'native-manifest.json').write_text(json.dumps({'release':'native-test','files':{}}),encoding='utf8')
    with helper.isolated(native,b'') as fixture, httpx.Client(base_url=fixture['origin'],verify=False,trust_env=False) as client:
        fixture['auth'].session=lambda token:{'csrf':'fixture','until':9999999999,'_renew_cookie':True} if token=='fixture-owner' else None
        client.cookies.set('__Host-desk_session','fixture-owner')
        response=client.get('/api/config');assert response.status_code==200
        cookie=response.headers['set-cookie']
        assert 'Max-Age=604800' in cookie and 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=Strict' in cookie
        assert response.headers['cache-control']=='private, no-store'
