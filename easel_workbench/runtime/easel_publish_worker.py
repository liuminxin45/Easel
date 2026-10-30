"""Explicitly approved Easel publisher invocation; never used by UI tests."""

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))

import contextlib
import importlib
import io
import json
import os
import pathlib
import sys
import subprocess


class SubmissionAlreadyAttempted(BaseException):
    """Stop upstream recovery before a second potentially sent submission."""


def single_channel_submission(module):
    """Keep Easel's video upload flow, but fence its Enter-after-timeout loop."""
    original=getattr(module,'_publish_weixin_channels',None)
    if not original:return
    def publish(page,context):
        keyboard=page.keyboard;press=keyboard.press;sent=False
        def once(key,*args,**kwargs):
            nonlocal sent
            if key=='Enter':
                if sent:raise SubmissionAlreadyAttempted()
                sent=True
            return press(key,*args,**kwargs)
        keyboard.press=once
        try:return original(page,context)
        finally:keyboard.press=press
    module._publish_weixin_channels=publish


def readonly(payload,session,revision,directory,source):
    """No publisher is imported or invoked on this path."""
    import datetime as dt
    import importlib
    readback=importlib.import_module('platform_readback')
    platform=session['platform'];base=directory/('profiles-'+str(session.get('_profile_generation',0)))
    if platform=='bilibili':
        account=str(readback.read_bilibili_account(base/'cookies.json').get('uid') or '')
        works=readback.read_bilibili_works(base/'cookies.json',limit=50)
    elif platform in ('douyin','kuaishou'):
        from playwright.sync_api import sync_playwright
        module=importlib.import_module('douyin_publish' if platform=='douyin' else 'web_publisher')
        profile=module._profile_dir(str(base)) if platform=='douyin' else module._profile_dir(platform,str(base))
        with sync_playwright() as p:
            browser=p.chromium.launch_persistent_context(str(profile),headless=True,args=module.LAUNCH_ARGS+['--no-proxy-server'])
            try:
                page=browser.pages[0] if browser.pages else browser.new_page()
                account=str(getattr(readback,'read_'+platform+'_account')(page).get('platform_account_id') or '')
                works=getattr(readback,'read_'+platform+'_works')(page,limit=50)
            finally:browser.close()
    else:return {'readback':{'outcome':'unsupported'}}
    if account!=revision['account']:return {'readback':{'outcome':'identity_mismatch'}}
    hinted=str((payload.get('hints') or {}).get('remote_id') or '')
    since=dt.datetime.fromisoformat(payload['dispatch_started_at'].replace('Z','+00:00')).timestamp()*1000
    matches=[w for w in works if w.title==revision['title'] and (not hinted or w.platform_content_id==hinted) and w.published_at_ms and w.published_at_ms>=since-60000]
    if len(matches)!=1:return {'readback':{'outcome':'unverified'},'account':account}
    return {'readback':{'outcome':'verified','matched':matches[0].as_dict()},'account':account}

from easel_workbench.runtime.easel_connection_support import safe_env


def main():
    payload = json.load(sys.stdin)
    session, revision, directory = payload['session'], payload['revision'], pathlib.Path(payload['directory']).resolve()
    if session.get('state') != 'connected' or session.get('account') != revision.get('account'):
        raise ValueError('账号身份不符')
    env = safe_env({}, directory)
    env['PLAYWRIGHT_BROWSERS_PATH'] = str(directory.parents[2] / '.runtime/media-tools/browsers')
    env['PATH']=str(directory.parents[2]/'.runtime/media-tools/venv'/('Scripts' if os.name=='nt' else 'bin'))+os.pathsep+env.get('PATH','')
    os.environ.clear()
    os.environ.update(env)
    os.chdir(directory)
    source = pathlib.Path(__file__).resolve().parents[2] / 'skills/shared/scripts'
    sys.path.insert(0, str(source))
    platform = session['platform']
    if payload.get('mode')=='verify':
        print(json.dumps(readonly(payload,session,revision,directory,source),ensure_ascii=False));return
    # Recheck the actual account just before invoking a publisher. A nickname or
    # an old login observation cannot authorize a newly swapped browser account.
    probe_payload={'session':session,'directory':str(directory),'action':'probe','credentials':payload.get('credentials',{})}
    probe=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('easel_account_worker.py'))],input=json.dumps(probe_payload),capture_output=True,text=True,encoding='utf-8',timeout=120,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    who=json.loads(probe.stdout)
    if who.get('loggedIn') is not True or who.get('provider_user_id')!=revision['account']:raise ValueError('发送前账号身份不符')
    if platform=='bilibili':
        sys.path.insert(0,str(source.parents[1]/'builtin/skill-bilibili-upload/scripts'))
        from types import SimpleNamespace
        import time
        uploader=importlib.import_module('bili_upload')
        readback=importlib.import_module('platform_readback')
        options=revision.get('platform_options') or {}
        profile=directory/('profiles-'+str(session.get('_profile_generation',0)))
        cookie=profile/'cookies.json'
        videos=[a['path'] for a in payload['assets'] if a['mime'].startswith('video/')]
        if not videos or not options.get('tid') or options.get('copyright') not in ('1','2'):raise ValueError('B站稿件缺少准确视频、分区或版权声明')
        previous=readback.capture_bilibili_snapshot(cookie)
        started=int(time.time()*1000)
        args=SimpleNamespace(cookie=str(cookie),video=videos[0],title=revision['title'],tid=options['tid'],partition=None,desc=revision['body'],tag='',cover=None,copyright=int(options['copyright']),source=options.get('source',''))
        result=subprocess.run(uploader.build_cmd(args),capture_output=True,timeout=900,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        verdict=readback.verify_bilibili_publish(cookie,title=revision['title'],since_ms=started,snapshot_ids=previous,attempts=2,delay_s=2)
        matched=verdict.matched.as_dict() if verdict.matched else {}
        print(json.dumps({'readback':{'outcome':verdict.outcome,'matched':matched},'account':revision['account']},ensure_ascii=False))
        return
    if platform=='wechat-oa' and session.get('_auth_mode')=='credentials':
        import urllib.request,urllib.parse,hashlib
        if payload.get('action')!='draft':raise ValueError('此接入只允许存公众号草稿')
        credentials=payload['credentials']
        query=urllib.parse.urlencode({'grant_type':'client_credential','appid':credentials['app_id'],'secret':credentials['app_secret']})
        with urllib.request.urlopen('https://api.weixin.qq.com/cgi-bin/token?'+query,timeout=30) as response:token=json.load(response)['access_token']
        sys.path.insert(0,str(source.parents[1]/'builtin/skill-wechat-publisher/scripts'))
        api=importlib.import_module('api');converter=importlib.import_module('html_converter')
        api.get_access_token=lambda:token
        api.get_config=lambda *a,**k:{'account_name':session['label'],'author':''}
        images=[a['path'] for a in payload['assets'] if a['mime'].startswith('image/')]
        if not images:raise ValueError('公众号文章需要已批准的封面')
        html=converter.convert_markdown_to_wechat_html(revision['body'],styles=converter.DEFAULT_STYLES,highlights=converter.DEFAULT_HIGHLIGHTS)
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            result=api.publish_article(revision['title'],html,images[0])
        media_id=result['media_id']
        raw=json.dumps({'media_id':media_id}).encode()
        request=urllib.request.Request('https://api.weixin.qq.com/cgi-bin/draft/get?'+urllib.parse.urlencode({'access_token':token}),data=raw,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=30) as response:actual=json.load(response)
        articles=actual.get('news_item') or []
        verified=len(articles)==1 and articles[0].get('title')==revision['title'] and articles[0].get('content')==html
        print(json.dumps({'draft_verified':verified,'media_id':media_id,'account':revision['account'],'title':revision['title'],'content_sha256':hashlib.sha256(html.encode()).hexdigest()}))
        return
    module_name = 'weixin_mp_stats' if platform=='wechat-oa' else 'xhs_publish' if platform == 'xiaohongshu' else 'douyin_publish' if platform == 'douyin' else 'web_publisher'
    module = importlib.import_module(module_name)
    if platform=='weixin-channels':single_channel_submission(module)
    readback = importlib.import_module('platform_readback')
    observed = {}
    for name in dir(readback):
        if name.startswith('verify_') and callable(getattr(readback, name)):
            original = getattr(readback, name)
            def wrap(*args, _original=original, **kwargs):
                result = _original(*args, **kwargs)
                observed.update(result.as_dict())
                return result
            setattr(readback, name, wrap)
    profile = directory / ('profiles-' + str(session.get('_profile_generation', 0)))
    files = [pathlib.Path(a['path']) for a in payload['assets']]
    videos = [str(p) for p, a in zip(files, payload['assets']) if a['mime'].startswith('video/')]
    images = [str(p) for p, a in zip(files, payload['assets']) if a['mime'].startswith('image/')]
    args = ['publish', '--profile-base', str(profile), '--title', revision['title'], '--exec']
    if platform=='wechat-oa':
        if payload.get('action')!='draft' or not images:raise ValueError('公众号草稿需要封面与本次授权')
        import html
        body=directory/('draft-'+payload['delivery_id']+'.html')
        body.write_text('<article>'+''.join('<p>'+html.escape(line)+'</p>' for line in revision['body'].splitlines())+'</article>',encoding='utf-8')
        args=['publish','--profile-base',str(profile),'--html',str(body),'--cover',images[0],'--title',revision['title']]
    elif module_name == 'web_publisher':
        if not files and platform!='zhihu':
            raise ValueError('缺少实际媒体文件')
        args += ['--platform', platform, '--desc', revision['body']]
        if files:args+=['--media', str(files[0])]
    else:
        args += ['--content', revision['body']]
        if videos:
            if platform in ('douyin','xiaohongshu'):args[0]='publish-video'
            args += ['--video', videos[0]]
        elif images:
            args += ['--images', ','.join(images)]
        else:
            raise ValueError('缺少实际媒体文件')
    sys.argv = [str(source / (module_name + '.py')), *args]
    capture=io.StringIO()
    with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(io.StringIO()):
        module.main()
    if platform=='wechat-oa':
        for line in reversed(capture.getvalue().splitlines()):
            try:value=json.loads(line)
            except ValueError:continue
            if isinstance(value,dict) and value.get('success') is True:
                print(json.dumps({'account':revision['account'],'media_id':str(value.get('media_id') or ''),'readback':{'outcome':'unverified'}}));return
            break
    # Strip arbitrary platform payloads; the caller keeps result unknown until
    # the complete identity/URL/time receipt contract has been established.
    matched = observed.get('matched') or {}
    print(json.dumps({'account':revision['account'],'readback': {'outcome': observed.get('outcome'), 'matched': {k: matched.get(k) for k in ('platform_content_id', 'title', 'status', 'published_at_ms')}}}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        print('{"readback":{"outcome":"unknown"}}')
