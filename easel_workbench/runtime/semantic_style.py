"""Version 2 creation choices, per-field inheritance and deterministic guidance.

Legacy numbers are decoded with the original three thresholds. They are never
relabelled as precise semantic weights or written back to historical records.
"""
import copy


FIELDS = [
    {'id': 'title', 'module': 'title', 'label': '标题切入', 'options': [
        {'id': 'news', 'label': '消息变化', 'instructions': '标题直接交代主体与发生的具体事件，保留理解新闻所需的条件，不增加未经证实的结果。'},
        {'id': 'change_use', 'label': '变化与用途', 'instructions': '标题写清具体变化及它带来的用途或影响；用途必须有本轮材料支持，不把可能性写成已发生。'},
        {'id': 'value', 'label': '读者价值', 'instructions': '标题优先呈现读者能获得的具体价值，同时写清主体、适用对象和必要条件，不许诺没有依据的收益。'},
        {'id': 'question', 'label': '问题与真实反差', 'instructions': '标题从读者关心的一个具体问题或材料支持的真实反差切入；正文必须实际回答该问题，不用悬念掩盖核心信息。'}]},
    {'id': 'text', 'module': 'text', 'label': '信息展开', 'options': [
        {'id': 'brief', 'label': '简要', 'instructions': '文字保留核心信息、直接依据和必要条件；删去重复解释及不影响理解的旁支，遵守当前格式篇幅。'},
        {'id': 'standard', 'label': '标准', 'instructions': '文字先交代要点，再补足理解所需的解释、依据与必要背景，遵守当前格式篇幅。'},
        {'id': 'expanded', 'label': '展开', 'instructions': '文字增加有来源的细节、依据、例子和适用边界，解释关键因果；不要为扩写而重复，仍遵守当前格式篇幅。'}]},
    {'id': 'tone', 'module': 'text', 'label': '表达语气', 'options': [
        {'id': 'plain', 'label': '平实', 'instructions': '用平实陈述表达事实与判断，情绪收敛，避免夸张形容和没有依据的赞叹。'},
        {'id': 'natural', 'label': '自然', 'instructions': '用自然、顺畅的日常表达解释信息，以具体事实带出判断，避免套话和故意热闹的语气。'},
        {'id': 'vivid', 'label': '鲜活', 'instructions': '可直接对读者说话，使用材料支持的动作、情境与生活化表达；鲜活来自具体事实，不虚构经历或煽动情绪。'}]},
    {'id': 'structure', 'module': 'text', 'label': '内容组织', 'options': [
        {'id': 'conclusion_first', 'label': '结论先行', 'instructions': '开头先给最重要的结果或判断，随后按重要程度补充依据、条件与背景。'},
        {'id': 'points_then_explain', 'label': '要点后解释', 'instructions': '先列清关键要点，再逐项解释依据、影响和必要条件；每个解释要能对应一个要点。'},
        {'id': 'process', 'label': '过程叙事', 'instructions': '沿真实过程组织材料，交代行动、转折与因果并通向结果；保持一条清楚的主线，不虚构情节。'}]},
    {'id': 'image', 'module': 'image', 'label': '配图表达', 'options': [
        {'id': 'scene', 'label': '具象场景', 'instructions': '以一个具体人物、动作或情境表达主题，使主体与事件关系一眼可懂；角色身份和必要文字遵守现行图片规范。'},
        {'id': 'diagram', 'label': '信息图解', 'instructions': '用清楚的关系、流程、对比或结构图解释信息，连线、标签与层级只表达本轮材料支持的关系。'},
        {'id': 'typographic', 'label': '文字排版', 'instructions': '以文字层级、字形与留白组织画面；核心信息在手机上可读，减少无解释作用的装饰并遵守文案原字要求。'},
        {'id': 'scene_diagram', 'label': '场景与图解', 'instructions': '用具体场景承载主题，并用少量标签、关系或流程图解说明关键机制；两者围绕同一个信息焦点。'}]},
    {'id': 'style', 'module': 'image', 'label': '画面信息量', 'options': [
        {'id': 'focused', 'label': '聚焦', 'instructions': '画面突出一个视觉焦点，减少旁支、装饰和重复元素，只保留解释主题必需的信息。'},
        {'id': 'balanced', 'label': '适中', 'instructions': '画面保留明确主次与足够留白，在核心焦点周围补充理解需要的细节，手机上仍清楚可读。'},
        {'id': 'rich', 'label': '丰富', 'instructions': '画面增加具有解释作用的细节、层次和信息关系；统一主次与阅读顺序，避免装饰淹没主题。'}]},
]
CHOICES = {field['id']: {option['id']: option for option in field['options']} for field in FIELDS}
LABELS = {field['id']: field['label'] for field in FIELDS}
DEFAULT_INTENT = {'title': 'change_use', 'text': 'standard', 'tone': 'plain',
                  'structure': 'conclusion_first', 'image': 'scene_diagram', 'style': 'focused'}
LEGACY_BUCKETS = {'title': ('news', 'change_use', 'value'), 'text': ('brief', 'standard', 'expanded'),
                  'tone': ('plain', 'natural', 'vivid'),
                  'structure': ('conclusion_first', 'points_then_explain', 'process'),
                  'image': ('diagram', 'scene_diagram', 'scene'), 'style': ('focused', 'balanced', 'rich')}


def intent(value, complete=False):
    """An absent key inherits; null/empty/unknown values are not hidden defaults."""
    if not isinstance(value, dict) or set(value) - set(CHOICES):
        raise ValueError('创作意图字段无效')
    if complete and set(value) != set(CHOICES):
        raise ValueError('最终创作意图需要六项完整选择')
    for key, choice in value.items():
        if not isinstance(choice, str) or choice not in CHOICES[key]:
            raise ValueError(LABELS[key] + '选项无效')
    return dict(value)


def legacy_intent(values):
    if not isinstance(values, dict) or set(values) - set(CHOICES):
        raise ValueError('旧创作参数字段无效')
    result = {}
    for key, number in values.items():
        if type(number) is not int or not 0 <= number <= 100:
            raise ValueError('旧创作参数需要0到100整数')
        result[key] = LEGACY_BUCKETS[key][0 if number < 25 else 2 if number > 74 else 1]
    return result


def layer(document):
    """Return semantic choices and their origin without filling missing fields."""
    document = document or {}
    converted = legacy_intent(document.get('values', {}))
    semantic = intent(document.get('intent', {}))
    origins = {key: {'kind': 'legacy', 'legacy_value': document['values'][key],
                     'conversion': 'original_three_thresholds', 'thresholds': [25, 75]}
               for key in converted}
    origins.update({key: {'kind': 'semantic'} for key in semantic})
    return {**converted, **semantic}, origins


def resolve(layers):
    """Ordered global/channel/work/round/request partial layers."""
    effective = dict(DEFAULT_INTENT)
    provenance = {key: {'scope': 'global', 'kind': 'builtin'} for key in effective}
    conversions, conflicts, exposed = [], [], []
    for scope, document in layers:
        part, origins = layer(document)
        exposed.append({'scope': scope, 'intent': dict(part), 'values': copy.deepcopy(document.get('values', {}))})
        for key, choice in part.items():
            if effective[key] != choice:
                conflicts.append({'axis': key, 'before': effective[key], 'after': choice,
                                  'overridden_scope': provenance[key]['scope'], 'effective_scope': scope})
            effective[key] = choice
            provenance[key] = {'scope': scope, **origins[key]}
            if origins[key]['kind'] == 'legacy':
                conversions.append({'scope': scope, 'field': key, 'intent': choice, **origins[key]})
    return {'intent': effective, 'provenance': provenance, 'legacy_conversions': conversions,
            'conflicts': conflicts, 'layers': exposed}


def applicability(creative):
    result = {key: {'applicable': True, 'reason': ''} for key in CHOICES}
    locked = creative.get('text', {})
    if creative.get('target') == 'images':
        for key in ('title', 'text', 'tone', 'structure'):
            result[key] = {'applicable': False, 'reason': '本轮只生成配图，冻结标题与正文原样沿用。'}
    else:
        if 'title' in locked or creative.get('text_policy',{}).get('title')=='preserve':
            result['title'] = {'applicable': False, 'reason': '用户标题原字锁定，本轮不改写标题。'}
        if 'body' in locked or creative.get('text_policy',{}).get('body')=='preserve':
            for key in ('text', 'tone', 'structure'):
                result[key] = {'applicable': False, 'reason': '用户正文原字锁定，本轮不改写正文。'}
    if creative.get('fixed_master'):
        for key in ('image', 'style'):
            result[key] = {'applicable': False, 'reason': '本轮使用固定视觉母版，沿用母版的表达与信息层级。'}
    return result


def instructions(resolved, creative):
    selected = intent(resolved, complete=True)
    applicable = applicability(creative)
    lines = []
    for field in FIELDS:
        key = field['id']
        if not applicable[key]['applicable']:
            lines.append(field['label'] + '：本轮不适用；' + applicable[key]['reason'])
        else:
            option = CHOICES[key][selected[key]]
            lines.append(field['label'] + '：' + option['label'] + '。' + option['instructions'])
    return '\n'.join(lines)
