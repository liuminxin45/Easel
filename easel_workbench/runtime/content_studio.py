"""Human-authored text versions and explicit, frozen creation preferences."""
import hashlib
import json
import pathlib
import uuid
from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime import desk as _desk
from easel_workbench.runtime.semantic_style import (FIELDS, DEFAULT_INTENT, intent as semantic_intent,
                            legacy_intent, resolve as resolve_intent,
                            instructions as semantic_instructions, applicability)

AXES = [
    {'id':'title','module':'title','label':'标题切入','left':'信息直述','right':'读者收益','dimension':'title',
     'hints':['先写清主体与具体变化，标题保持直接。','兼顾发生了什么，以及与读者有什么关系。','优先写读者可获得的具体价值，保留主体与必要条件。']},
    {'id':'text','module':'text','label':'信息展开','left':'简洁提要','right':'详细说明','dimension':'text',
     'hints':['保留核心信息和必要条件，减少展开。','交代要点，再补足理解需要的解释。','增加细节、依据与例子；配文仍遵守篇幅要求。']},
    {'id':'tone','module':'text','label':'表达语气','left':'克制平实','right':'口语鲜活','dimension':'tone',
     'hints':['以平实陈述表达判断，情绪收敛。','保持自然口语，用具体事实带出语气。','更多直接对读者说话与生活化表达，情绪仍由事实支撑。']},
    {'id':'structure','module':'text','label':'内容组织','left':'结论先行','right':'过程展开','dimension':'structure',
     'hints':['先交代最重要的结果，再给必要依据。','先给核心信息，再按理解顺序补充过程。','多展示过程、转折与因果，保持一条清楚的主线。']},
    {'id':'image','module':'image','label':'配图表达','left':'信息图解','right':'具象场景','dimension':'image',
     'hints':['更多用关系、流程和对比图解解释信息。','按内容组合清楚的图解与具体场景。','更多用人物、动作和具体情境表达主题；角色身份按现行规范。']},
    {'id':'style','module':'image','label':'画面信息量','left':'简洁聚焦','right':'丰富展开','dimension':'style',
     'hints':['突出一个视觉焦点，减少装饰与旁支。','保留主次层级，补充必要细节。','增加有解释作用的细节与层次，手机上仍要清楚可读。']},
]
DEFAULT = {'title':50,'text':40,'tone':35,'structure':30,'image':70,'style':30}
BUILTINS = [
    {'id':'clear','name':'清晰直述','description':'直接讲变化，配图简洁。','values':{'title':30,'text':30,'tone':20,'structure':15,'image':35,'style':20}},
    {'id':'scene','name':'场景叙事','description':'用具体情境带出用途，表达更生活化。','values':{'title':70,'text':45,'tone':65,'structure':50,'image':85,'style':35}},
    {'id':'explain','name':'技术拆解','description':'多给依据与过程，用图解说明关系。','values':{'title':45,'text':75,'tone':25,'structure':65,'image':20,'style':55}},
]

class StudioConflict(ValueError):
    pass

def packed(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def initialize(c):
    c.executescript('''
CREATE TABLE IF NOT EXISTS toolbox_text_versions(job_id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_style_presets(id TEXT PRIMARY KEY,name TEXT NOT NULL,format TEXT NOT NULL,revision INTEGER NOT NULL,document TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_style_preset_ops(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_style_preset_revisions(id TEXT NOT NULL,revision INTEGER NOT NULL,document TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(id,revision));
''')
    c.execute('INSERT OR IGNORE INTO toolbox_style_preset_revisions SELECT id,revision,document,updated_at FROM toolbox_style_presets')

def weights(value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULT) or any(type(n) is not int or not 0<=n<=100 for n in value.values()):
        raise ValueError('六项创作参数均需为0到100的整数')
    return dict(value)

def options(value=None):
    if value is None:value={}
    if not isinstance(value,dict):raise ValueError('创作设置格式无效')
    if type(value.get('enabled',False)) is not bool or type(value.get('keep_text',True)) is not bool:raise ValueError('创作开关无效')
    schema=value.get('schema_version',1 if 'values' in value and 'intent' not in value else 2)
    if type(schema) is not int or schema not in (1,2):raise ValueError('创作设置版本无效')
    preset=value.get('preset_id','inherit' if not value else 'custom')
    if not isinstance(preset,str) or len(preset)>128:raise ValueError('风格预设无效')
    target=value.get('target','all')
    if target not in ('all','images'):raise ValueError('生成范围无效')
    result={'schema_version':schema,'enabled':value.get('enabled',False),'preset_id':preset,
            'target':target,'keep_text':value.get('keep_text',True),'text':{}}
    if 'creator' in value:
        creator=value['creator']
        if not isinstance(creator,dict) or set(creator)-{'profile_id','profile_revision','skills','trial'}:
            raise ValueError('创作画像与技能选择无效')
        from easel_workbench.runtime.toolbox_store import ident
        parsed={'profile_id':ident(creator.get('profile_id','oil-pig'))}
        if 'profile_revision' in creator:
            revision=creator['profile_revision']
            if type(revision) is not int or revision<1:raise ValueError('创作画像修订号无效')
            parsed['profile_revision']=revision
        if 'trial' in creator:
            if type(creator['trial']) is not bool:raise ValueError('技能试用选择无效')
            parsed['trial']=creator['trial']
        if 'skills' in creator:
            refs=creator['skills']
            if not isinstance(refs,list) or len(refs)>16:raise ValueError('本次技能选择过多')
            selected=[];seen=set()
            for ref in refs:
                if not isinstance(ref,dict) or set(ref)-{'id','version'}:raise ValueError('技能版本引用无效')
                sid=ident(ref.get('id'))
                if sid in seen:raise ValueError('同一技能不能重复选择')
                seen.add(sid);item={'id':sid}
                if 'version' in ref:
                    version=ref['version']
                    if type(version) is not int or version<1:raise ValueError('技能版本无效')
                    item['version']=version
                selected.append(item)
            parsed['skills']=selected
        result['creator']=parsed
        result['enabled']=True
    if 'recipe' in value:
        from easel_workbench.runtime.creative_recipes import parse_recipe
        result['recipe']=parse_recipe(value['recipe']);result['enabled']=True
    if 'text_policy' in value:
        policy=value['text_policy']
        if not isinstance(policy,dict) or set(policy)-{'title','body'} or any(item not in ('preserve','follow_request') for item in policy.values()):raise ValueError('本轮文字修改范围无效')
        result['text_policy']={key:policy.get(key,'follow_request') for key in ('title','body')}
        if target=='images' and any(item!='preserve' for item in result['text_policy'].values()):raise ValueError('只改配图时标题和配文须保留原文；要修改文字请切换为“按修改意见”')
    if schema==1:
        result['values']=weights(value.get('values',DEFAULT))
    else:
        result['intent']=semantic_intent(value.get('intent',{}))
        # These are frozen context fields. The request's own partial intent
        # remains separate, so a later one-field edit cannot pin other fields.
        if 'resolved_intent' in value:result['resolved_intent']=semantic_intent(value['resolved_intent'],complete=True)
        if 'values' in value:result['values']=weights(value['values'])
    if 'fixed_master' in value:
        if type(value['fixed_master']) is not bool:raise ValueError('母版状态无效')
        result['fixed_master']=value['fixed_master']
    for key in ('intent_provenance','legacy_conversions'):
        if key in value:
            if not isinstance(value[key],dict if key=='intent_provenance' else list):raise ValueError('创作来源记录无效')
            result[key]=json.loads(packed(value[key]))
    if 'learning' in value:
        raw_learning=value['learning']
        allowed={'profile_id','profile_revision','include_ids','exclude_ids','conflict_choices','revision_token','goal','topic'}
        if not isinstance(raw_learning,dict) or set(raw_learning)-allowed:raise ValueError('本次创作学习选择无效')
        learned={}
        for key,item in raw_learning.items():
            if key in ('include_ids','exclude_ids'):
                if not isinstance(item,list) or len(item)>500 or any(not isinstance(x,str) or not x or len(x)>128 or '\x00' in x for x in item) or len(set(item))!=len(item):raise ValueError('学习依据ID列表无效')
            elif key=='conflict_choices':
                if not isinstance(item,dict) or len(item)>500 or any(not isinstance(k,str) or not k or len(k)>128 or not isinstance(v,str) or not v or len(v)>128 or '\x00' in k+v for k,v in item.items()):raise ValueError('学习冲突选择无效')
            elif key=='profile_revision':
                if type(item) is not int or item<0:raise ValueError('学习资料修订号无效')
            elif key=='profile_id' and item is None:pass
            elif not isinstance(item,str) or len(item)>(4000 if key in ('goal','topic') else 128) or '\x00' in item:
                raise ValueError('本次创作学习内容无效')
            learned[key]=json.loads(packed(item))
        result['learning']=learned
    if value.get('context_revision'):
        token=value['context_revision']
        if not isinstance(token,str) or len(token)!=64 or any(x not in '0123456789abcdef' for x in token):raise ValueError('设置快照标识无效')
        result['context_revision']=token
    raw=value.get('text',{})
    if not isinstance(raw,dict) or set(raw)-{'title','body'}:raise ValueError('自定义文案格式无效')
    for key,limit in [('title',500),('body',100000)]:
        if key in raw:
            field=raw[key]
            if not isinstance(field,str) or not field.strip() or len(field)>limit or '\x00' in field or key=='title' and any(ord(x)<32 for x in field):raise ValueError('自定义标题或正文为空、过长或含无效字符')
            result['text'][key]=field
    workspace=value.get('workspace',{})
    if not isinstance(workspace,dict) or set(workspace)-{'channel','reader_goal','flow_id','style_guidance'}:raise ValueError('本次设置格式无效')
    if workspace:
        parsed={}
        for key,limit in [('channel',20),('reader_goal',4000),('flow_id',160),('style_guidance',10000)]:
            if key in workspace:
                item=workspace[key]
                if not isinstance(item,str) or len(item)>limit or '\x00' in item:raise ValueError('本次设置内容无效')
                parsed[key]=item
        if parsed.get('channel') not in (None,'','wechat','xiaohongshu'):raise ValueError('发布渠道无效')
        result['workspace']=parsed
    if schema==2:
        # The v1 action gate still reads enabled. Semantic choices do not need
        # a separate slider switch, and an explicit workspace clear is a change.
        result['enabled']=bool(result.get('creator') is not None or result.get('recipe') is not None or result.get('intent') or result.get('learning') or result.get('workspace') or result.get('text_policy') or value.get('enabled',False))
    return result

def catalog(box,format):
    if format not in ('poster','article'):raise ValueError('制作类型无效')
    with box.store.connect() as c:
        saved=[{**json.loads(r['document']),'revision':r['revision']} for r in c.execute('SELECT * FROM toolbox_style_presets WHERE format=? ORDER BY updated_at DESC,id',(format,))]
    presets=[]
    for item in BUILTINS+saved:
        if item.get('schema_version')==2:presets.append(item)
        else:presets.append({**item,'schema_version':1,'legacy':True,'semantic_preview':legacy_intent(item['values'])})
    return {'schema_version':2,'fields':FIELDS,'default_intent':dict(DEFAULT_INTENT),
            'axes':AXES,'defaults':DEFAULT,'presets':presets}

def save_preset(box,value):
    from easel_workbench.runtime.toolbox_store import ident,text
    operation=ident(value.get('id'));signature=packed(value);format=value.get('format')
    if format not in ('poster','article'):raise ValueError('制作类型无效')
    name=text(value.get('name',''),48,True).strip();schema=value.get('schema_version',2 if 'intent' in value else 1)
    if type(schema) is not int or schema not in (1,2):raise ValueError('风格预设版本无效')
    selected=semantic_intent(value.get('intent',{})) if schema==2 else weights(value.get('values'))
    pid=value.get('preset_id') or 'saved-'+uuid.uuid4().hex
    ident(pid)
    if not pid.startswith('saved-'):raise ValueError('内置预设不可覆盖，请另存一套风格')
    with box.store.connect() as c:
        c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM toolbox_style_preset_ops WHERE id=?',(operation,)).fetchone()
        if old:
            if old['signature']!=signature:raise ValueError('同一操作ID不能保存不同风格')
            return json.loads(old['result'])
        current=c.execute('SELECT * FROM toolbox_style_presets WHERE id=?',(pid,)).fetchone();revision=current['revision'] if current else 0
        if value.get('revision',0)!=revision or current and current['format']!=format:raise StudioConflict('这套风格已在其它页面修改，请核对后保存；当前参数仍保留')
        if not current and c.execute('SELECT count(*) FROM toolbox_style_presets WHERE format=?',(format,)).fetchone()[0]>=50:raise ValueError('已保存50套风格，请更新已有预设')
        supersedes=None
        if current and schema==2 and json.loads(current['document']).get('schema_version',1)==1:
            # Reading a legacy preset is reversible. Saving its new semantic
            # revision must leave the original numeric preset intact.
            supersedes=pid;pid='saved-'+uuid.uuid4().hex;revision=0
        document={'schema_version':schema,'id':pid,'name':name,
                  'intent' if schema==2 else 'values':selected,
                  'description':'你保存的创作意图；未指定的项目继续继承。' if schema==2 else '你保存的整套创作参数。'}
        if supersedes:document['supersedes_preset_id']=supersedes
        c.execute('INSERT OR REPLACE INTO toolbox_style_presets VALUES(?,?,?,?,?,?)',(pid,name,format,revision+1,packed(document),stamp()))
        c.execute('INSERT INTO toolbox_style_preset_revisions VALUES(?,?,?,?)',(pid,revision+1,packed(document),stamp()))
        result={**document,'revision':revision+1};c.execute('INSERT INTO toolbox_style_preset_ops VALUES(?,?,?)',(operation,signature,packed(result)))
    return result

def source(box,c,wid,vid):
    from easel_workbench.runtime.publish_content import from_artifacts as copy
    from easel_workbench.runtime.article_delivery import from_artifacts as article
    row=c.execute("SELECT * FROM toolbox_jobs WHERE work_id=? AND id=? AND kind IN ('create','change')",(wid,vid)).fetchone()
    from easel_workbench.runtime.revision_scope import can_continue_partial
    if not row or row['status']!='completed' and not can_continue_partial(c,row):raise ValueError('所选作品版本未完成或不属于此作品')
    artifacts=[dict(r) for r in c.execute('SELECT * FROM artifacts WHERE task_id=? ORDER BY rowid',(vid,))]
    format=box.options(wid,c)['format'];root=box.root/'data/artifacts'
    if format not in ('poster','article'):
        media=c.execute('SELECT document FROM media_jobs WHERE id=? AND work_id=?',(vid,wid)).fetchone()
        if not media:raise ValueError('媒体版本来源未取得')
        document=json.loads(media['document']);title,body=document['title'],document['prompt']
        return {'title':title,'body':body,'token':hashlib.sha256(packed({'job':vid,'files':document['artifacts'],'title':title,'body':body}).encode()).hexdigest(),'author':'human_direction','locked_fields':[]},artifacts
    if format=='poster':
        text=copy(artifacts,root) or {'title':'','caption':''};title,body=text['title'],text['caption']
    else:
        from easel_workbench.runtime.article_drafts import job_work
        text=article(artifacts,root,job_work(box.options(wid,c),vid,c)['article_mode']);title,body=text['title'],text['body']
    authored=c.execute('SELECT document FROM toolbox_text_versions WHERE job_id=?',(vid,)).fetchone()
    document=json.loads(authored['document']) if authored else {}
    if document.get('text'):title,body=document['text']['title'],document['text']['body']
    digest=hashlib.sha256(packed({'title':title,'body':body,'artifacts':[(r['id'],r['name']) for r in artifacts]}).encode()).hexdigest()
    locked=['title','body'] if document.get('origin')=='human' else document.get('provided_fields',[])
    return {'title':title,'body':body,'token':digest,'author':'human' if len(locked)==2 else 'mixed' if locked else 'ai','locked_fields':locked},artifacts

def frozen_options(c,jid):
    row=c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(jid,)).fetchone()
    document=json.loads(row['document']) if row else {}
    value=document.get('creation_options')
    # A previous submission's optimistic lock must not become the next round's
    # inherited lock. The immutable original remains in review_inputs.
    if not value:return value
    result={k:v for k,v in value.items() if k not in ('context_revision','resolved_intent','intent_provenance','legacy_conversions','applicability')}
    if 'learning' in result:result['learning']={k:v for k,v in result['learning'].items() if k!='revision_token'}
    if 'recipe' in result:
        result['recipe']={k:v for k,v in result['recipe'].items() if k not in ('preview_id','source_revision','plan_id')}
        if document.get('execution_prompt'):result['recipe']['prompt_text']=document['execution_prompt']['editable_text']
    return result

def freeze_options(box,c,wid,vid,value=None):
    result=options(value)
    if vid:
        parent,_=source(box,c,wid,vid)
        # Human-authored text stays authoritative through image generation. A
        # deliberate uncheck allows a subsequent AI text rewrite.
        inherited=frozen_options(c,vid)
        if 'text_policy' in result:
            selected=[key for key,mode in result['text_policy'].items() if mode=='preserve']
            for key,mode in result['text_policy'].items():
                if mode=='follow_request' and key in result['text']:raise ValueError('本轮'+('标题' if key=='title' else '配文／正文')+'同时提供了锁定原文和改写许可，请核对文字范围')
        else:
            selected=['title','body'] if result['target']=='images' else parent['locked_fields'] if result['keep_text'] else []
            if result['keep_text'] and inherited and inherited.get('text') and not selected:selected=list(inherited['text'])
        if selected:result['text']={**{key:parent[key] for key in selected},**result['text']}
        result=options(result)
    resolved=result.get('resolved_intent')
    if resolved is None:
        request={'values':result['values']} if result['schema_version']==1 and result['enabled'] else {'intent':result.get('intent',{})}
        resolution=resolve_intent([('request',request)])
        resolved=resolution['intent'];result['resolved_intent']=resolved
        result['intent_provenance']=resolution['provenance'];result['legacy_conversions']=resolution['legacy_conversions']
    result['applicability']=applicability(result)
    instructions=[semantic_instructions(resolved,result)]
    if result['text']:instructions.append('用户指定的标题/正文按原字原样使用；不要润色、压缩、补句或改标题。图片由AI按此文案生成。')
    if result['target']=='images':instructions.append('本次只更新配图，沿用此处冻结的标题与正文，不重新撰写。')
    if 'text_policy' in result:
        instructions.append('本轮文字范围独立于父版锁定；自写文字不是永久禁止修改。只修改本轮意见明确涉及的内容，未提及的部分沿用指定父版。')
        for key,mode in result['text_policy'].items():instructions.append(('标题' if key=='title' else '配文／正文')+'：'+('保留冻结原文，不改写。' if mode=='preserve' else '按本轮修改意见调整；未要求修改时沿用原文。'))
    workspace=result.get('workspace',{})
    if workspace.get('reader_goal'):instructions.append('本轮读者目标：'+workspace['reader_goal'])
    if workspace.get('style_guidance'):instructions.append('本轮风格补充：'+workspace['style_guidance'])
    instructions.append('这些是本轮创作意图。遵循当前内容规范、事实与明确认可边界；固定栏目母版优先。交付设计说明.json（schema_version 2），逐项说明实际设计、适用性与原因，逐条回应本轮真实依据和批注，引用交付位置与文件SHA-256；未采用、部分采用或暂缓均如实说明。')
    return result,'\n'.join(instructions)

def _write(c,root,jid,name,content,mime):
    aid=hashlib.sha256((jid+'\0human-text\0'+name+'\0').encode()+content).hexdigest()
    path=root/'data/artifacts'/aid/name;path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_bytes(content);temporary.replace(path)
    elif path.read_bytes()!=content:raise ValueError('文案快照校验失败')
    c.execute('INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?)',(aid,jid,name,str(path),mime))

def materialize(c,root,jid,format,raw,artifacts,mode='auto',retain_original=False):
    """Create canonical text bytes; AI originals remain separately downloadable."""
    root=pathlib.Path(root);replace={'标题与配文.txt'} if format=='poster' else {'文章交付.json','文章正文.md'}
    manifest=None
    if format=='article':
        replace.update(row['name'] for row in artifacts if not row['name'].startswith('AI原稿-') and pathlib.Path(row['name']).suffix.lower() in ('.html','.htm','.pdf','.docx'))
        matches=[r for r in artifacts if r['name']=='文章交付.json']
        own=[]
        for row in matches:
            path=pathlib.Path(row['path']).resolve()
            if path.is_relative_to((root/'data/artifacts').resolve()) and path.is_file() and path.stat().st_size<=128000:
                content=path.read_bytes();expected=hashlib.sha256((jid+'\0human-text\0'+row['name']+'\0').encode()+content).hexdigest()
                if row['id']==expected:own.append(row)
        matches=own or matches
        if len(matches)==1:
            path=pathlib.Path(matches[0]['path']).resolve()
            if path.is_relative_to((root/'data/artifacts').resolve()) and path.stat().st_size<=128000:
                try:manifest=json.loads(path.read_text(encoding='utf-8-sig'))
                except (ValueError,OSError):pass
        if not isinstance(manifest,dict):manifest={'schema_version':1,'article_type':'product' if mode=='product' else 'general','sources':[]}
        replace.add(manifest.get('body_file','文章正文.md'))
    if retain_original:
        for row in artifacts:
            if row['name'] not in replace:continue
            path=pathlib.Path(row['path']).resolve()
            own=False
            if path.is_relative_to((root/'data/artifacts').resolve()) and path.is_file() and path.stat().st_size<=2_000_000:
                expected=hashlib.sha256((jid+'\0human-text\0'+row['name']+'\0').encode()+path.read_bytes()).hexdigest()
                own=row['id']==expected
            if not own:c.execute("UPDATE artifacts SET name='AI原稿-'||name WHERE id=? AND task_id=?",(row['id'],jid))
    if format=='poster':
        _write(c,root,jid,'标题与配文.txt',(raw['title']+'\n'+raw['body']).encode('utf-8'),'text/plain')
    else:
        manifest={**manifest,'title':raw['title'],'body_file':'文章正文.md'}
        _write(c,root,jid,'文章正文.md',raw['body'].encode('utf-8'),'text/markdown')
        _write(c,root,jid,'文章交付.json',packed(manifest).encode('utf-8'),'application/json')

def apply_locked_text(store,jid,root):
    """Completion hook: preserve exactly supplied text, even if AI rewrites it."""
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='toolbox_text_versions'").fetchone():return
        choice=frozen_options(c,jid)
        if not choice or not choice.get('text'):return
        original=c.execute('SELECT document FROM toolbox_text_versions WHERE job_id=?',(jid,)).fetchone()
        previous=json.loads(original['document']) if original else None
        if previous and previous.get('origin')=='human':return
        rows=[dict(r) for r in c.execute('SELECT * FROM artifacts WHERE task_id=?',(jid,))]
        job=c.execute('SELECT work_id,kind FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()
        if not job or job['kind'] not in ('create','change'):return
        from easel_workbench.runtime.publish_content import from_artifacts as copy
        from easel_workbench.runtime.article_delivery import from_artifacts as article
        option=c.execute('SELECT format,article_mode FROM toolbox_work_options WHERE work_id=?',(job['work_id'],)).fetchone()
        format=option['format'] if option else 'poster'
        from easel_workbench.runtime.article_drafts import job_work
        mode=job_work(dict(option) if option else {'article_mode':'auto'},jid,c)['article_mode']
        if format=='poster':
            found=copy(rows,pathlib.Path(root)/'data/artifacts') or {};raw={'title':found.get('title',''),'body':found.get('caption','')}
        else:
            found=article(rows,pathlib.Path(root)/'data/artifacts');raw={'title':found.get('title',''),'body':found.get('body','')}
        raw.update(choice['text'])
        if previous:raw=previous['text']
        # Do not declare a partial user override to be a complete AI delivery.
        if not raw['title'].strip() or not raw['body'].strip():return
        materialize(c,root,jid,format,raw,rows,mode,retain_original=True)
        c.execute('INSERT OR IGNORE INTO toolbox_text_versions VALUES(?,?)',(jid,packed({'origin':'locked_input','text':raw,'provided_fields':list(choice['text'])})))

def save_text(box,wid,value,new=False):
    from easel_workbench.runtime.toolbox_store import ident,text
    jid=ident(value.get('id'));ident(wid);signature=packed(value);raw=options({'text':{'title':value.get('title'),'body':value.get('body')}})['text'];now=stamp()
    with box.store.connect() as c:
        c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()
        if old:
            if old['work_id']!=wid or old['signature']!=signature or not c.execute('SELECT 1 FROM toolbox_text_versions WHERE job_id=?',(jid,)).fetchone():raise ValueError('同一操作ID不能使用不同文案')
            return {'id':jid,'work_id':wid,'status':'completed'}
        if c.execute('SELECT 1 FROM toolbox_article_draft_ops WHERE id=?',(jid,)).fetchone():raise ValueError('操作ID已用于素材草稿')
        parent=None;artifacts=[]
        if new:
            if wid!=jid or c.execute('SELECT 1 FROM toolbox_works WHERE id=?',(wid,)).fetchone():raise StudioConflict('作品已经建立，请核对原操作回执')
            format=value.get('format','poster');mode=value.get('article_mode','auto')
            if format not in ('poster','article') or mode not in ('auto','product'):raise ValueError('制作类型无效')
            aid=value.get('article_id') or None
            if aid and not c.execute('SELECT 1 FROM articles WHERE id=?',(ident(aid),)).fetchone():raise ValueError('资讯不存在')
            c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',(wid,aid,raw['title'],raw['body'],now,now))
            c.execute('INSERT INTO toolbox_work_options VALUES(?,?,?)',(wid,format,mode))
        else:
            parent=ident(value.get('candidate_id'));current,artifacts=source(box,c,wid,parent)
            latest=c.execute("SELECT id FROM toolbox_jobs WHERE work_id=? AND kind IN ('create','change') AND status='completed' ORDER BY julianday(created_at) DESC,rowid DESC LIMIT 1",(wid,)).fetchone()
            if not latest or value.get('base_version')!=latest['id'] or value.get('source_token')!=current['token']:raise StudioConflict('作品已有新版本或原文变化。你的文案仍保留，请核对后继续')
            if c.execute("SELECT 1 FROM toolbox_jobs WHERE work_id=? AND kind IN ('create','change','discuss') AND status IN ('queued','dispatching','running','uncertain','needs_desktop')",(wid,)).fetchone():raise StudioConflict('此作品有未完成的制作或讨论，请核对原任务后再使用文案')
            format=box.options(wid,c)['format']
            from easel_workbench.runtime.article_drafts import job_work
            mode=job_work(box.options(wid,c),parent,c)['article_mode']
        from easel_workbench.runtime.creator_runtime import service as creator_service,read_owner,MANIFEST
        creator_selection=(value.get('creative') or {}).get('creator')
        owner=read_owner(c,wid)
        project=pathlib.Path(getattr(getattr(box,'studio',None),'project',_desk.PROJECT))
        if creator_selection is not None or owner or (getattr(box,'studio',None) and (project/MANIFEST).is_file()):
            owner=creator_service(box,c).bind_work(c,wid,creator_selection,allow_historical=not new)
        files=box._files(c,value.get('files',[]));guidance=text(value.get('guidance',''),10000)
        c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,files,signature,status,created_at,finished_at,reply) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                  (jid,wid,'change' if parent else 'create','用户直接使用自写文案',parent,files,signature,'completed',now,now,'文案已按用户原文保存，未调用AI。配图及实测材料沿用指定父版本；旧文案和批注保留。' if parent else '已使用用户文案；配图尚未生成。'))
        c.execute('INSERT INTO toolbox_article_inputs VALUES(?,?,?)',(jid,0,packed({'title':raw['title'],'material':raw['body'],'guidance':guidance,'files':json.loads(files),'article_mode':mode,'text_origin':'human'})))
        # Only media and actual test records are inherited, never stale HTML or
        # an AI weight declaration describing a different piece of writing.
        evidence_names=set()
        for row in artifacts:
            if row['name']=='文章交付.json':
                try:evidence_names.add(json.loads(pathlib.Path(row['path']).read_text(encoding='utf-8-sig')).get('test',{}).get('record_file'))
                except (ValueError,OSError):pass
        for row in artifacts:
            if row['mime'].startswith(('image/','video/','audio/')) or row['name'] in evidence_names:
                aid=hashlib.sha256((jid+'\0inherit\0'+row['id']).encode()).hexdigest()
                c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',(aid,jid,row['name'],row['path'],row['mime']))
        materialize(c,box.root,jid,format,raw,artifacts,mode)
        c.execute('INSERT INTO toolbox_text_versions VALUES(?,?)',(jid,packed({'origin':'human','parent':parent,'text':raw})))
        from easel_workbench.runtime.work_review import freeze
        creation={**(value.get('creative') or {}),'text':raw,'keep_text':True}
        if owner:creation['creator']={'profile_id':owner['profile_id'],'profile_revision':owner['profile_revision']}
        freeze(box,c,wid,jid,parent,creation=creation,origin='human_edit')
        from easel_workbench.runtime.local_operations import mark_execution
        mark_execution(c,jid,'local','human_edit')
        from easel_workbench.runtime.local_operations import enqueue_delivery
        enqueue_delivery(c,jid)
        c.execute('UPDATE toolbox_works SET updated_at=? WHERE id=?',(now,wid))
    return {'id':jid,'work_id':wid,'status':'completed'}
