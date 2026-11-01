"""TEMP-only browser regression: signed gallery and expanded-image downloads."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import threading
from urllib.parse import parse_qs, urlsplit

import argparse
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--native',required=True);parser.add_argument('--backend',required=True);parser.add_argument('--out',required=True);args=parser.parse_args()
sys.path.insert(0,str(Path(args.backend).resolve()))
spec=importlib.util.spec_from_file_location('native_download_fixture',ROOT/'tests/workbench_native_browser.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
from easel_workbench.runtime.auth_totp import token_hash
from playwright.sync_api import sync_playwright,expect

out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
native=Path(args.native).resolve()
report={'passed':False,'real_AI_calls':0,'real_platform_writes':0,'physical_mobile_device_tested':False,'checks':[]}
with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
 with h.isolated(native,(ROOT/'web/static/easel-icon.png').read_bytes()) as f:
  f['auth'].lock=threading.RLock()
  f['auth'].data['sessions']={token_hash('fixture-owner'):{'csrf':'fixture','until':9999999999}}
  for profile,width,mobile in [('desktop',1280,False),('mobile',390,True)]:
   context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=mobile,has_touch=mobile)
   context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
   page=context.new_page();page.set_default_timeout(20000)
   page.goto(f['origin']+'/native/chat?fresh=1',wait_until='domcontentloaded')
   page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
   sid=parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1].split('?')[0]
   textarea=page.get_by_role('textbox',name='对话输入');textarea.fill('/生成贴图 TEMP download '+profile)
   expect(page.get_by_role('menuitem',name='/生成贴图',exact=False)).to_be_visible();textarea.press('Enter')
   page.get_by_role('button',name='发送',exact=True).click()
   history=h.wait_history(page,f['origin'],sid,None,files=True)
   page.reload(wait_until='domcontentloaded')
   gallery=page.locator('.artifact-gallery').first
   expect(gallery).to_be_visible()
   link=gallery.locator('a[download]')
   expect(link).to_have_attribute('href',__import__('re').compile(r'^/media/images/.*[?&]download=1'))
   url=link.get_attribute('href')
   # A separate request context deliberately has no page cookies.
   anonymous=pw.request.new_context(ignore_https_errors=True)
   denied=anonymous.get(f['origin']+gallery.locator('.artifact-image-link').get_attribute('href'))
   assert denied.status==401,denied.status
   response=anonymous.get(f['origin']+url);assert response.status==200,response.status
   expected=hashlib.sha256(response.body()).hexdigest()
   with page.expect_download() as pending:link.click()
   download=pending.value;assert download.failure() is None;assert '/media/downloads?' in download.url,download.url
   assert hashlib.sha256(Path(download.path()).read_bytes()).hexdigest()==expected
   no_cookie=anonymous.get(download.url);assert no_cookie.status==200 and hashlib.sha256(no_cookie.body()).hexdigest()==expected
   assert anonymous.head(download.url).headers.get('content-length')==str(len(no_cookie.body()))
   page.screenshot(path=str(out/(profile+'-gallery.png')))
   gallery.locator('.artifact-image-link').click()
   modal=page.get_by_role('dialog',name='查看图片');expect(modal).to_be_visible()
   modal_link=modal.get_by_role('link',name='下载原图')
   assert urlsplit(modal_link.get_attribute('href')).path==urlsplit(url).path
   with page.expect_download() as pending:modal_link.click()
   download=pending.value;assert download.failure() is None;assert '/media/downloads?' in download.url,download.url
   assert hashlib.sha256(Path(download.path()).read_bytes()).hexdigest()==expected
   no_cookie=anonymous.get(download.url);assert no_cookie.status==200 and hashlib.sha256(no_cookie.body()).hexdigest()==expected
   assert anonymous.head(download.url).headers.get('content-length')==str(len(no_cookie.body()))
   page.screenshot(path=str(out/(profile+'-expanded.png')))
   # Exercise real partial-file and version-ZIP routes without downloader cookies.
   from easel_workbench.chat_products import ChatProducts
   tid=history['session']['messages'][-1]['turnId']
   business=f['app'].state.chat_business
   turn=business.chat.get_turn(tid,private=True)
   partial=next(item for item in ChatProducts(business)._partial(turn) if item['mime'].startswith('image/'))
   config=page.request.get(f['origin']+'/api/config').json()
   targets=[(partial['url'],partial['name']),(f"/api/works/{turn['work']['work_id']}/versions/{tid}/download",'images.zip')]
   for target,name in targets:
    issued=page.request.post(f['origin']+'/api/downloads',data={'target':target,'name':name},headers={'Origin':f['origin'],'X-CSRF-Token':config['csrf']})
    assert issued.status==200,issued.text()
    capability=f['origin']+issued.json()['url']
    exact=anonymous.get(capability);assert exact.status==200,exact.text()
    assert anonymous.head(capability).status==200
    if name!='images.zip':
     assert hashlib.sha256(exact.body()).hexdigest()==expected
     ranged=anonymous.get(capability,headers={'Range':'bytes=1-3'});assert ranged.status==206 and ranged.body()==exact.body()[1:4]
    else:
     import io,zipfile
     with zipfile.ZipFile(io.BytesIO(exact.body())) as bundle:assert any(hashlib.sha256(bundle.read(n)).hexdigest()==expected for n in bundle.namelist())
   report['checks'].append({'profile':profile,'gallery_download':True,'expanded_download':True,'cookie_less_signed_download':200,'unsigned_without_cookie':401,'sha256':expected})
   modal.get_by_role('button',name='关闭',exact=True).click()
   gallery.get_by_role('button',name='下一个产物').click()
   text_link=gallery.locator('a[download]')
   raw=page.request.get(f['origin']+text_link.get_attribute('href')).body()
   with page.expect_download() as pending:text_link.click()
   saved=pending.value;assert saved.failure() is None and '/media/downloads?' in saved.url
   assert Path(saved.path()).read_bytes()==raw
   # Open the actual shared content library using its declared exact file path.
   image_file=next(item for item in history['session']['messages'][-1]['output_files'] if item['mime'].startswith('image/'))
   path='__workbench__/'+image_file['id']+'/'+image_file['name']
   from urllib.parse import urlencode
   page.goto(f['origin']+'/native/?'+urlencode({'path':'/works?'+urlencode({'path':path})}),wait_until='domcontentloaded')
   library_link=page.get_by_role('link',name='下载原图',exact=True);expect(library_link).to_be_visible()
   with page.expect_download() as pending:library_link.click()
   saved=pending.value;assert saved.failure() is None and '/media/downloads?' in saved.url
   assert hashlib.sha256(Path(saved.path()).read_bytes()).hexdigest()==expected
   page.screenshot(path=str(out/(profile+'-library.png')))
   report['checks'][-1].update(text_download=True,library_download=True,signed_http_handoff=True,partial_download=True,version_zip=True)
   anonymous.dispose();context.close()
 browser.close()
report['native']={'release':native.name,'manifest_sha256':h.sha(native/'native-manifest.json')}
report['backend']={'directory':str(Path(args.backend).resolve()),'manifest_sha256':h.sha(Path(args.backend)/'workbench-release.json') if (Path(args.backend)/'workbench-release.json').is_file() else None}
report['passed']=True
(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print(json.dumps(report))
