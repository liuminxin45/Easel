"""Read legacy declarations and evidence-bound version 2 design explanations."""
import json,pathlib
from easel_workbench.runtime.semantic_style import CHOICES

DIMENSIONS={'image':'图像','text':'文字','title':'标题','tone':'文风','structure':'结构','style':'样式'}
SCOPES={'work':'本作品','format':'同类作品','global':'全部创作'}

def validate(document):
    if isinstance(document,dict) and document.get('schema_version')==2:return validate_v2(document)
    if not isinstance(document,dict) or document.get('schema_version')!=1 or document.get('basis') not in ('proposal','retrospective'):
        raise ValueError('权重说明需要 schema_version 1 和 proposal/retrospective 口径')
    rows=document.get('dimensions')
    if not isinstance(rows,list) or len(rows)!=6 or {row.get('id') for row in rows if isinstance(row,dict)}!=set(DIMENSIONS):
        raise ValueError('权重说明需包含图像、文字、标题、文风、结构、样式六项')
    for row in rows:
        if type(row.get('applicable')) is not bool or not isinstance(row.get('reason'),str) or not row['reason'].strip():
            raise ValueError('每项权重需说明是否适用及设计原因')
        items=row.get('weights',[])
        if not isinstance(items,list) or len(items)>12:raise ValueError('权重方向列表无效')
        if row['applicable']:
            if not items or any(not isinstance(item,dict) or not isinstance(item.get('direction'),str) or not item['direction'].strip() or type(item.get('percent')) is not int or not 0<=item['percent']<=100 for item in items) or sum(item['percent'] for item in items)!=100:
                raise ValueError('每个适用维度的方向权重必须分别合计100%')
        elif items:raise ValueError('不适用维度不填写虚构权重')
        for key in ('reference','used_at','adjustment'):
            if not isinstance(row.get(key,''),str):raise ValueError('参考、采用位置和调整方向需为文本')
    responses=document.get('feedback_responses',[])
    if not isinstance(responses,list) or len(responses)>200:raise ValueError('批注回应列表无效')
    for response in responses:
        if not isinstance(response,dict) or not isinstance(response.get('annotation_id'),str) or response.get('outcome') not in ('applied','partial','deferred') or response.get('dimension') not in DIMENSIONS or not isinstance(response.get('reason'),str) or not response['reason'].strip():
            raise ValueError('批注回应需包含原批注ID、维度、处理结果与原因')
    return document

def describe(document):
    if document.get('schema_version')==2:return describe_v2(document)
    lines=['口径：'+('制作前方案' if document['basis']=='proposal' else '交付后回顾估计')+'；AI建议，具体比例不等于用户已认可的默认风格。']
    for row in document['dimensions']:
        lines+=['',DIMENSIONS[row['id']]+'：'+('；'.join(item['direction']+' '+str(item['percent'])+'%' for item in row.get('weights',[])) if row['applicable'] else '本版不适用'),
                '设计原因：'+row['reason']]
        for key,label in [('reference','参考依据'),('used_at','实际采用'),('adjustment','可调方向')]:
            if row.get(key):lines.append(label+'：'+row[key])
    for response in document.get('feedback_responses',[]):
        lines+=['','批注 '+response['annotation_id']+'（'+response['outcome']+'，'+DIMENSIONS[response['dimension']]+'）：'+response['reason']]
    return '\n'.join(lines)

def from_artifacts(rows,root):
    current=[row for row in rows if row['name']=='设计说明.json']
    matches=current or [row for row in rows if row['name']=='风格权重.json']
    result={'ready':False,'text':'','document':None,'issues':[],'schema_version':2 if current else 1 if matches else None,
            'legacy':bool(matches and not current),'execution_verified':False,'file':'设计说明.json' if current else '风格权重.json' if matches else None}
    if not matches:return result
    try:
        if len(matches)!=1:raise ValueError('本版'+result['file']+' 不唯一')
        path=pathlib.Path(matches[0]['path']).resolve()
        if not path.is_relative_to(pathlib.Path(root).resolve()) or not path.is_file() or not 0<path.stat().st_size<=256_000:raise ValueError('本版权重说明文件不可用')
        raw=json.loads(path.read_text(encoding='utf-8-sig'))
        document=validate_v2(raw) if current else validate(raw)
        if not current and document.get('schema_version')!=1:raise ValueError('新版设计说明必须使用设计说明.json')
        result.update(ready=True,text=describe(document),document=document)
    except (ValueError,OSError,TypeError,KeyError,UnicodeError) as exc:result['issues'].append(str(exc) if isinstance(exc,ValueError) else '权重说明格式不完整')
    return result

CONTRACT={'file':'风格权重.json','schema_version':1,'basis':'proposal 或 retrospective',
    'dimensions':[{'id':key,'label':label,'applicable':True,'weights':[{'direction':'本版实际方向','percent':100}],
                   'reason':'为什么这样设计','reference':'实际参考或未使用外部参考','used_at':'实际采用位置','adjustment':'可调方向'} for key,label in DIMENSIONS.items()],
    'feedback_responses':[{'annotation_id':'本次输入中真实批注ID','dimension':'text','outcome':'applied 或 partial 或 deferred','reason':'具体改动、权重变化与依据；未处理时说明原因'}]}

OUTCOMES={'applied':'已采用','partial':'部分采用','not_applied':'未采用','deferred':'暂缓','not_applicable':'本轮不适用'}

def _nonempty(value,label,limit=10000):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or '\x00' in value:raise ValueError(label+'需要非空文本')

def _ids(value,label):
    if not isinstance(value,list) or len(value)>500:raise ValueError(label+'列表无效')
    for item in value:_nonempty(item,label,512)
    if len(set(value))!=len(value):raise ValueError(label+'不得重复')

def _deliverables(value):
    if not isinstance(value,list) or len(value)>200:raise ValueError('实际交付位置列表无效')
    for item in value:
        if not isinstance(item,dict):raise ValueError('交付依据格式无效')
        _nonempty(item.get('artifact_name'),'交付文件名',1000)
        _nonempty(item.get('location'),'具体交付位置',2000)
        digest=item.get('sha256')
        if not isinstance(digest,str) or len(digest)!=64 or any(x not in '0123456789abcdef' for x in digest):raise ValueError('交付依据需要实际文件SHA-256')

def _execution_row(row):
    if not isinstance(row,dict) or not isinstance(row.get('outcome'),str) or row['outcome'] not in OUTCOMES:raise ValueError('采用结果无效')
    _nonempty(row.get('reason'),'实际设计或处理原因')
    _deliverables(row.get('deliverables'))
    if row['outcome'] in ('applied','partial') and not row['deliverables']:raise ValueError('已采用或部分采用需要实际交付位置与文件SHA-256')
    if row['outcome']=='not_applicable' and row['deliverables']:raise ValueError('不适用项不填写虚构交付位置')

def validate_v2(document):
    """Validate shape only; execution IDs and bytes require validate_execution."""
    if not isinstance(document,dict) or type(document.get('schema_version')) is not int or document.get('schema_version')!=2 or document.get('basis')!='execution':
        raise ValueError('设计说明需要schema_version 2和execution实际执行口径')
    rows=document.get('dimensions')
    if not isinstance(rows,list) or len(rows)!=6 or {row.get('id') for row in rows if isinstance(row,dict) and isinstance(row.get('id'),str)}!=set(DIMENSIONS):
        raise ValueError('设计说明需要六项独立创作意图')
    for row in rows:
        key=row['id'];_execution_row(row)
        if type(row.get('applicable')) is not bool:raise ValueError('设计说明需明确每项是否适用')
        _ids(row.get('basis_ids'),'本轮实际依据ID')
        if row['applicable']:
            if row['outcome']=='not_applicable' or (row.get('intent') is not None if document.get('control_mode')=='readable_prompt' else not isinstance(row.get('intent'),str) or row['intent'] not in CHOICES[key]):raise ValueError('适用项需要本轮真实控制方式及实际处理结果')
            if not row['basis_ids']:raise ValueError('适用项需要引用本轮真实依据ID')
        elif row.get('intent') is not None or row['outcome']!='not_applicable' or row['deliverables']:
            raise ValueError('不适用项需空意图、not_applicable和真实原因，不填虚构交付')
    responses=document.get('responses')
    if not isinstance(responses,list) or len(responses)>500:raise ValueError('本轮依据回应列表无效')
    seen=set()
    for row in responses:
        _execution_row(row);_nonempty(row.get('basis_id'),'本轮真实依据ID',512)
        if row['basis_id'] in seen:raise ValueError('每个本轮依据ID只能回应一次')
        seen.add(row['basis_id'])
        if not isinstance(row.get('dimension'),str) or row['dimension'] not in DIMENSIONS:raise ValueError('本轮回应维度无效')
        if 'annotation_id' in row:_nonempty(row['annotation_id'],'原批注ID',512)
    if 'expected_basis_ids' in document:_ids(document['expected_basis_ids'],'本轮必需依据ID')
    return document

def describe_v2(document):
    lines=['口径：本轮实际设计说明；采用结果须核对本轮依据与交付字节，助手说明不等于用户已认可。']
    for row in document['dimensions']:
        choice='按本轮可读提示词' if document.get('control_mode')=='readable_prompt' and row['applicable'] else CHOICES[row['id']].get(row.get('intent'),{}).get('label','本轮不适用')
        lines+=['',DIMENSIONS[row['id']]+'：'+choice+'；'+OUTCOMES[row['outcome']],'设计原因：'+row['reason']]
        if row['basis_ids']:lines.append('本轮依据：'+'、'.join(row['basis_ids']))
        for item in row['deliverables']:lines.append('实际交付：'+item['artifact_name']+' · '+item['location']+'；SHA-256 '+item['sha256'])
    for row in document['responses']:
        lines+=['','依据 '+row['basis_id']+('；批注 '+row['annotation_id'] if row.get('annotation_id') else '')+'（'+OUTCOMES[row['outcome']]+'，'+DIMENSIONS[row['dimension']]+'）：'+row['reason']]
        for item in row['deliverables']:lines.append('回应位置：'+item['artifact_name']+' · '+item['location']+'；SHA-256 '+item['sha256'])
    return '\n'.join(lines)

# This is an instruction template, not a fabricated completed delivery. Freeze
# supplies the real expected_basis_ids; the producer replaces all examples.
V2_CONTRACT={'file':'设计说明.json','schema_version':2,'basis':'execution',
    'dimensions':[{'id':key,'applicable':True,'intent':'本轮冻结的该字段英文选项',
                   'outcome':'applied / partial / not_applied / deferred；不适用时not_applicable',
                   'reason':'实际设计及取舍；不适用时说明冻结文案、只图或固定母版等真实原因',
                   'basis_ids':['本轮真实依据ID'],
                   'deliverables':[{'artifact_name':'本轮实际交付文件名','location':'具体段落、文字或画面位置','sha256':'实际文件的64位小写SHA-256'}]}
                  for key in DIMENSIONS],
    'responses':[{'basis_id':'本轮真实依据ID','annotation_id':'仅依据为批注时填写原批注ID',
                  'dimension':'对应六项之一','outcome':'applied / partial / not_applied / deferred / not_applicable',
                  'reason':'具体怎样回应；未采用、部分采用或暂缓均说明原因',
                  'deliverables':[{'artifact_name':'本轮实际交付文件名','location':'具体回应位置','sha256':'实际文件的64位小写SHA-256'}]}],
    'instructions':'六项各出现一次；不适用项intent为null、outcome为not_applicable且deliverables为空；每个本轮必需依据ID独立回应一次，禁止虚构依据、交付位置或SHA。applied/partial必须有实际交付依据。'}

# Exact-location proof is checked against bytes by learning_execution.
V2_CONTRACT['location_contract']={'text':{'anchor':{'type':'text','start':0,'end':4,'quote':'实际原字'},'offset_encoding':'Unicode code points after UTF-8 decoding; preserve CRLF'},'image':{'anchor':{'type':'region','x':0,'y':0,'width':1,'height':1}},'rule':'位置标签不能代替实际anchor。文本也可给全文唯一quote，由程序核出真实坐标；图形区域只证明坐标存在，语义须独立查看。'}
