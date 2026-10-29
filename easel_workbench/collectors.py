"""Run private raw readers through the fork's Python collector protocol.

Only raw acquisition crosses this boundary. Editorial model calls, acknowledgments
and business persistence stay in the existing durable parent workflow.
"""
from pathlib import Path
import base64
import datetime as dt
import hashlib
import json
import os
import tempfile
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'aihot':'60028244fb76','newsnow':'8a49eef93fe5','aibot':'cc09dbccc795',
           'watcha':'f2d271fe6e04','weekly':'ruanyf-weekly'}
DISCOVERY = {'xinquji','github-trending','product-hunt','hacker-news'}
NETWORK_ENV = {'path','systemroot','windir','temp','tmp','tmpdir','lang','lc_all','tz',
    'http_proxy','https_proxy','all_proxy','no_proxy','easel_proxy',
    'ssl_cert_file','ssl_cert_dir','requests_ca_bundle','curl_ca_bundle'}
GH_ENV = {'HOME','USERPROFILE','APPDATA','LOCALAPPDATA','GH_CONFIG_DIR'}
MAX_RAW_BYTES = 64 * 1024 * 1024


def registered_sources():
    """Use the fork registry, with paths relative to its private config file."""
    from easel.trends.sources import load_sources
    configured = os.environ.get('EASEL_WORKBENCH_TREND_CONFIG')
    path = Path(configured) if configured else ROOT/'config/workbench-trend-sources.json'
    if not path.is_file() and not configured:
        path = ROOT/'config/workbench-trend-sources.example.json'
    sources=load_sources(ROOT,{'EASEL_TREND_SOURCES_CONFIG':str(path)})
    _,identity=child_environment('weekly')
    return [replace(s,options={**s.options,'env':{**s.options.get('env',{}),**identity}})
        if s.id==SOURCES['weekly'] else s for s in sources]


def child_environment(mode):
    """Native gh may read its own login; model credentials never cross over."""
    environment={k:v for k,v in os.environ.items() if k.lower() in NETWORK_ENV}
    if os.environ.get('AI_DESK_PROJECT_ROOT'):
        environment['AI_DESK_PROJECT_ROOT']=os.environ['AI_DESK_PROJECT_ROOT']
    if mode=='weekly':
        # Explicit source variables survive the upstream worker environment
        # filter. Only paths are carried; never GH_TOKEN or GITHUB_TOKEN.
        identity={k:os.environ[k] for k in GH_ENV if os.environ.get(k)}
        identity['GH_PROMPT_DISABLED']='1'
    else:
        identity={}
    # curl/gh honor this path, while the generic runner's inherited whitelist
    # only covers the SSL/requests variants. Bind it explicitly for this source.
    if os.environ.get('CURL_CA_BUNDLE'):identity['CURL_CA_BUNDLE']=os.environ['CURL_CA_BUNDLE']
    return environment,identity


def enabled():
    return os.environ.get('EASEL_WORKBENCH_COLLECTORS') == 'python' and os.environ.get('EASEL_WORKBENCH_COLLECTOR_CHILD') != '1'


def encode(value):
    if isinstance(value, bytes):
        return {'__workbench_bytes__':base64.b64encode(value).decode('ascii')}
    if isinstance(value,(dt.datetime,dt.date)):
        return {'__workbench_date__':value.isoformat(),'datetime':isinstance(value,dt.datetime)}
    if isinstance(value,Path):return str(value)
    if isinstance(value,set):return sorted(value)
    if isinstance(value,(tuple,list)):return [encode(x) for x in value]
    if isinstance(value,dict):
        if any(k in value for k in ('__workbench_bytes__','__workbench_date__','__workbench_mapping__','__workbench_chunks__')):
            return {'__workbench_mapping__':[[k,encode(v)] for k,v in value.items()]}
        return {k:encode(v) for k,v in value.items()}
    return value


def read_receipt(path):
    """Bound every read before allocating; chunks respect upstream RLIMIT_FSIZE."""
    path=Path(path)
    if path.stat().st_size>MAX_RAW_BYTES:raise ValueError('Raw collector result too large')
    with path.open('rb') as stream:raw=stream.read(MAX_RAW_BYTES+1)
    if len(raw)>MAX_RAW_BYTES:raise ValueError('Raw collector result too large')
    header=json.loads(raw)
    if isinstance(header,dict) and set(header)=={'__workbench_chunks__','size'}:
        count,size=header['__workbench_chunks__'],header['size']
        if type(count) is not int or type(size) is not int or not 1<=count<=128 or not 0<=size<=MAX_RAW_BYTES:
            raise ValueError('Invalid raw collector chunk receipt')
        blocks=[];total=0
        for index in range(count):
            with path.with_name(path.name+f'.{index:04d}').open('rb') as stream:block=stream.read(512*1024+1)
            total+=len(block)
            if len(block)>512*1024 or total>size:raise ValueError('Invalid raw collector chunk size')
            blocks.append(block)
        if total!=size:raise ValueError('Incomplete raw collector chunks')
        raw=b''.join(blocks)
    return raw


def write_receipt(path,raw):
    path=Path(path)
    if len(raw)>MAX_RAW_BYTES:raise ValueError('Raw collector result too large')
    if len(raw)<=1024*1024:
        path.write_bytes(raw)
        return
    parts=[raw[n:n+512*1024] for n in range(0,len(raw),512*1024)]
    for index,part in enumerate(parts):path.with_name(path.name+f'.{index:04d}').write_bytes(part)
    path.write_text(json.dumps({'__workbench_chunks__':len(parts),'size':len(raw)}),encoding='utf-8')


def decode(value):
    if isinstance(value,list):return [decode(x) for x in value]
    if isinstance(value,dict):
        if set(value)=={'__workbench_mapping__'}:return {k:decode(v) for k,v in value['__workbench_mapping__']}
        if set(value)=={'__workbench_bytes__'}:return base64.b64decode(value['__workbench_bytes__'],validate=True)
        if set(value)=={'__workbench_date__','datetime'}:return (dt.datetime if value['datetime'] else dt.date).fromisoformat(value['__workbench_date__'])
        return {k:decode(v) for k,v in value.items()}
    return value


def acquire(mode, parameters, *, source=None):
    from easel.trends.runner import collect
    if mode not in {*SOURCES,'discovery'}:raise ValueError('Unknown collector operation')
    source = source or SOURCES.get(mode)
    if mode=='discovery' and source not in DISCOVERY or mode!='discovery' and source!=SOURCES[mode]:
        raise ValueError('Collector source identity mismatch')
    definition=next((s for s in registered_sources() if s.id==source),None)
    if definition is None or definition.type!='python':raise ValueError('Python collector is not registered')
    state = Path(os.environ['AI_DESK_PROJECT_ROOT'])/'data/collection/python-protocol'
    state.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='request-',dir=state) as folder:
        directory=Path(folder);request=directory/'request.json';receipt=directory/'payload.json'
        request.write_text(json.dumps({'mode':mode,'source':source,'root':os.environ['AI_DESK_PROJECT_ROOT'],
            'parameters':encode(parameters),'receipt':str(receipt)},ensure_ascii=False),encoding='utf-8')
        environment,identity=child_environment(mode)
        item=replace(definition, options={**definition.options,
            'args':['--request',str(request)],'env':{**definition.options.get('env',{}),**identity}})
        # The framework filters inherited variables. Explicitly pass only paths
        # and raw-reader flags; no model keys or owner sessions cross this edge.
        payload=collect(item,environment)
        digest=payload['items'][0]['id']
        raw=read_receipt(receipt)
        if len(raw)>MAX_RAW_BYTES or hashlib.sha256(raw).hexdigest()!=digest:
            raise ValueError('Raw collector receipt does not match protocol result')
        return decode(json.loads(raw))


def produce(request):
    os.environ['AI_DESK_PROJECT_ROOT']=request['root']
    os.environ['EASEL_WORKBENCH_COLLECTOR_CHILD']='1'
    mode=request['mode'];p=decode(request['parameters'])
    if mode=='aihot':
        from .runtime.collection_sources import collect_aihot
        value=collect_aihot(Path(p.pop('folder')),**p)
    elif mode=='newsnow':
        from .runtime.collection_adapters.newsnow_ai_digest import process
        value=process(None,Path(p.pop('state')),**p)
    elif mode=='aibot':
        from .runtime.collection_adapters.aibot_daily_news import fetch
        value=fetch()
    elif mode=='discovery':
        from .runtime.discovery_feeds import collect
        value=collect(p['source'],Path(p['folder']),set(p['seen']),p.get('profile_dir'))
    elif mode=='watcha':
        from .runtime.watcha_collect import collect,Queue,Client
        value=collect(Queue(p.pop('queue')),Client(p.pop('limit')),**p)
    elif mode=='weekly':
        from .runtime.weekly_periodical import github
        value=github(**p)
    else:raise ValueError('Unknown collector operation')
    raw=json.dumps(encode(value),ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(raw)>MAX_RAW_BYTES:raise ValueError('Raw collector result too large')
    write_receipt(request['receipt'],raw)
    # The item links the complete, private raw receipt by content hash. No body
    # or candidate is discarded to fit the hotspot display schema.
    return {'version':1,'fetched_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'items':[{'id':hashlib.sha256(raw).hexdigest(),'title':request['source']+' 原始采集回执'}]}


def source_preview(source, root):
    """A standard Easel source yields actual titles, not receipt placeholder rows.

    This does not enter the production editorial/ack queue. Mutable acquisition
    state is temporary; an existing profile is only read for Xinquji predicates.
    """
    root=Path(root).resolve()
    definition=next((s for s in registered_sources() if s.id==source),None)
    if definition is None:raise ValueError('Unregistered collector source')
    os.environ['AI_DESK_PROJECT_ROOT']=str(root)
    os.environ['EASEL_WORKBENCH_COLLECTOR_CHILD']='1'
    mode='discovery' if source in DISCOVERY else next((m for m,s in SOURCES.items() if s==source),None)
    if mode is None:raise ValueError('Unknown source')
    with tempfile.TemporaryDirectory(prefix='easel-source-preview-') as folder:
        directory=Path(folder)
        if mode=='weekly':
            from .runtime.weekly_periodical import discover,fetch_issue
            doc=fetch_issue(discover()[-1])
            rows=[{'id':'issue:'+str(doc['number'])+':'+doc['hash'],'title':doc['title'],'url':doc['url'],'published_at':doc['published_at']}]
        else:
            if mode=='aihot':parameters={'folder':str(directory)}
            elif mode=='newsnow':
                config=json.loads((Path(__file__).parent/'runtime/collection_adapters/newsnow_ai_sources.json').read_text(encoding='utf-8'))
                parameters={'state':str(directory/'newsnow'),'sources':config['enabled_sources']}
            elif mode=='aibot':parameters={}
            elif mode=='watcha':parameters={'queue':str(directory/'watcha.sqlite'),'limit':27}
            else:
                from .runtime.collection_sources import settings
                parameters={'source':source,'folder':str(directory),'seen':[],'profile_dir':str(settings(root)['profile_dir'])}
            receipt=directory/'payload.json'
            produce({'root':str(root),'mode':mode,'source':source,'parameters':parameters,'receipt':str(receipt)})
            value=decode(json.loads(read_receipt(receipt)))
            if mode in ('aihot','discovery'):
                rows,coverage=value
                if coverage.get('coverage')=='failed' or coverage.get('errors'):
                    # Hotspot UI has one source-level state: don't present a
                    # partial response as a fresh successful full collection.
                    raise ValueError('Source collection incomplete; inspect parent task coverage')
            elif mode in ('newsnow','watcha'):
                if value.get('coverage') in ('failed','partial') or value.get('errors'):
                    raise ValueError('Source collection incomplete; inspect parent task coverage')
                rows=value['candidates']
            else:
                from .runtime.collection_adapters.aibot_daily_news import collect
                rows=[{'title':title,'url':url} for title,body,url in collect(value,dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date())]
        items=[]
        for row in rows[:500]:
            title=row.get('title') or row.get('name') or ''
            url=row.get('url') or row.get('original_url') or ''
            if not title:continue
            identifier=row.get('event_id') or row.get('source_event_id') or row.get('id')
            item={'title':str(title),'url':url}
            if identifier is not None:item['id']=str(identifier)
            published=row.get('published_at')
            if isinstance(published,str) and published:item['published_at']=published
            items.append(item)
        from easel.trends.protocol import validate_payload
        return validate_payload({'version':1,'fetched_at':dt.datetime.now(dt.timezone.utc).isoformat(),'items':items})
