"""Pinned, isolated local browser/tool installation metadata (never credentials)."""
from __future__ import annotations
import hashlib,json,os,pathlib,re,subprocess,urllib.parse
from easel_workbench.runtime.distribution_catalog import LOGIN_URLS

CLI_SHA='b792a30402f070b536c3dcc3090ff7ab483d4e77357ce893e564939224c7008b'
EXTENSION_SHA='dfb191decd63a45063c4f6d8f7687745e5ecebe34363792dd6781b657d69fd29'

def receipt(root):
    value=json.loads((pathlib.Path(root)/'data/distribution-install.json').read_text(encoding='utf-8'))
    if value.get('schema_version')!=1 or not re.fullmatch('[a-p]{32}',value.get('extension_id','')):
        raise ValueError('分发工具安装记录无效')
    tool=pathlib.Path(value['tool_root']).resolve()
    extension=pathlib.Path(value['extension_path']).resolve()
    profile=pathlib.Path(value['profile_path']).resolve()
    if not extension.is_relative_to(tool) or not profile.is_relative_to(tool) or extension==profile:
        raise ValueError('专用浏览器目录无效')
    cli=tool/'node_modules/@wechatsync/cli/dist/index.js'
    if hashlib.sha256(cli.read_bytes()).hexdigest()!=CLI_SHA:
        raise ValueError('分发工具已变化，请重新验收')
    archive=tool/'extension-2.0.9.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=EXTENSION_SHA:
        raise ValueError('分发扩展下载包已变化')
    manifest=json.loads((extension/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version')!='2.0.9':
        raise ValueError('分发扩展版本发生变化')
    return value

def open_browser(root, connection=None, discovery_url=None):
    value=receipt(root)
    target=LOGIN_URLS.get((connection or {}).get('platform'))
    # Open only fixed setup/login destinations, never a user-supplied URL or shell.
    targets=[f"chrome-extension://{value['extension_id']}/src/popup/index.html"]
    if target:targets.append(target)
    if discovery_url is not None:
        parsed=urllib.parse.urlsplit(discovery_url)
        normal=parsed.path=='/native/' and not parsed.fragment and parsed.query==urllib.parse.urlencode({'path':'/toolbox?section=distribution&pane=connections'})
        ticket=urllib.parse.parse_qs(parsed.fragment,keep_blank_values=True)
        one_shot=parsed.path=='/distribution/check' and not parsed.query and set(ticket)=={'check','ticket'} and all(len(v)==1 for v in ticket.values()) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,160}',ticket.get('check',[''])[0])) and bool(re.fullmatch(r'[A-Za-z0-9_-]{43}',ticket.get('ticket',[''])[0]))
        automatic=parsed.path=='/distribution/auto-check' and not parsed.query and set(ticket)=={'relay','ticket'} and all(len(v)==1 for v in ticket.values()) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,160}',ticket.get('relay',[''])[0])) and bool(re.fullmatch(r'[A-Za-z0-9_-]{43}',ticket.get('ticket',[''])[0]))
        if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password or not (normal or one_shot or automatic):
            raise ValueError('账号检测入口无效')
        targets=[discovery_url]
    existing=value.get('existing_browser')
    if existing:
        profile=existing.get('profile','')
        if existing.get('kind')!='edge' or not re.fullmatch(r'Default|Profile [0-9]+',profile) or existing.get('extension_id')!='hchobocdmclopcbnibdnoafilagadion':
            raise ValueError('已有浏览器安装记录无效')
        executable=pathlib.Path(os.environ.get('PROGRAMFILES(X86)',r'C:\Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe'
        base=pathlib.Path(os.environ['LOCALAPPDATA'])/'Microsoft/Edge/User Data'/profile/'Extensions'/existing['extension_id']
        package=pathlib.Path(existing['extension_package']).resolve()
        if not package.is_relative_to(base.resolve()) or hashlib.sha256((package/'assets/index.ts-Bw-475TG.js').read_bytes()).hexdigest()!='1c45a07a8323cdc2a92c38349381e1d24d560b19c0b59a2567479ab6661de4b8':
            raise ValueError('当前浏览器扩展已变化，请重新核对')
        if discovery_url is None:
            targets[0]=f"chrome-extension://{existing['extension_id']}/src/popup/index.html"
        command=[str(executable),'--profile-directory='+profile,'--new-tab',*targets]
    else:
        command=[value['browser_path'],'--user-data-dir='+value['profile_path'],
            '--disable-extensions-except='+value['extension_path'],'--load-extension='+value['extension_path'],
            '--no-first-run','--no-default-browser-check',*targets]
    subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        shell=False,close_fds=True)
    return {'status':'launch_requested' if discovery_url else 'opened','message':'已请求电脑启动本次检测。' if discovery_url else '已打开已安装同步助手的 Edge 浏览器。' if existing else '已在运行工作台的电脑打开专用登录浏览器。平台登录和同步桥接设置在该浏览器完成。'}
