"""Durable learning queue, independent of the fixed production conversation.

The service never launches this worker. Explicit run() supervision is the only
entry point; tests inject a runner and never send real AI work.
"""
from __future__ import annotations

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))


import json
import hashlib
import io
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import uuid

from easel_workbench.runtime.feedback_ledger import locked, Conflict
from easel_workbench.runtime.learning_service import LearningConflict, bounded, packed, CONDITIONS

IMAGE_MIMES = {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}


class ImageInputUnavailable(ValueError):
    pass


def verified_image_input(value):
    """Validate source bytes again; no extension-only MIME or animation claim."""
    if not isinstance(value, dict) or not isinstance(value.get('path'), (str, Path)):
        raise ImageInputUnavailable('没有明确的原始图像路径')
    path = Path(value['path'])
    if not path.is_absolute():
        raise ImageInputUnavailable('图像需要明确的绝对原件路径')
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise ImageInputUnavailable('不读取链接目录中的图像')
    if not re.fullmatch(r'[a-f0-9]{64}', value.get('sha256', '')):
        raise ImageInputUnavailable('图像缺少可核对的原始SHA-256')
    try:
        if not 0 < path.stat().st_size <= 20 * 1024 * 1024:
            raise ImageInputUnavailable('图像超过本次有界输入范围')
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != value['sha256']:
            raise ImageInputUnavailable('图像原始字节已变化，尚未向模型提交')
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as source:
            mime = Image.MIME.get(source.format)
            width, height = source.size
            frames = getattr(source, 'n_frames', 1)
            source.verify()
        if mime not in IMAGE_MIMES or mime != value.get('mime'):
            raise ImageInputUnavailable('不是当前支持的真实静态图片，未按文件后缀伪称已读')
        if frames != 1:
            raise ImageInputUnavailable('动图需要逐帧核对，本次未声称已读完整动作')
        return {'path': str(path), 'sha256': digest, 'mime': mime, 'width': width, 'height': height,
                'frame_count': 1, 'read_scope': 'single_static_image'}, raw
    except ImageInputUnavailable:
        raise
    except Exception:
        raise ImageInputUnavailable('图像原件缺失、类型不符或无法完整核对') from None


def image_observations_complete(analysis, images):
    observations = analysis.get('image_observations') if isinstance(analysis, dict) else None
    if not isinstance(observations, list) or len(observations) != len(images):
        return False
    indexed = {row.get('sha256'): row for row in observations if isinstance(row, dict)}
    if len(indexed) != len(images):
        return False
    return all(indexed.get(image['sha256'], {}).get('status') == 'observed' and
               isinstance(indexed[image['sha256']].get('description'), str) and indexed[image['sha256']]['description'].strip()
               for image in images)


def analysis_schema():
    condition = {'anyOf': [{'type': 'string'}, {'type': 'array', 'items': {'type': 'string'}}, {'type': 'null'}]}
    suggestion = {'type': 'object', 'additionalProperties': False,
                  'properties': {'name': {'type': 'string'}, 'instructions': {'type': 'array', 'items': {'type': 'string'}},
                                 'conditions': {'type': 'object', 'additionalProperties': False, 'properties': {key: condition for key in sorted(CONDITIONS)}, 'required': sorted(CONDITIONS)},
                                 'reason': {'type': 'string'}, 'dimension': {'type': 'string'},
                                 'target_component_id': {'type':['string','null']},'do_not_copy':{'type':'string'}},
                  'required': ['name', 'instructions', 'conditions', 'reason', 'dimension','target_component_id','do_not_copy']}
    return {'type': 'object', 'additionalProperties': False,
            'properties': {'summary': {'type': 'string'}, 'classification': {'type': 'string'},
                           'scope': {'type': 'string', 'enum': ['work', 'round', 'conditional', 'global', 'unknown']},
                           'limitations': {'type': 'array', 'items': {'type': 'string'}},
                           'image_observations': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                                                  'properties': {'sha256': {'type': 'string'}, 'status': {'type': 'string', 'enum': ['observed', 'unverified']},
                                                                 'description': {'type': 'string'}, 'limitations': {'type': 'array', 'items': {'type': 'string'}}},
                                                  'required': ['sha256', 'status', 'description', 'limitations']}},
                           'suggestions': {'type': 'array', 'items': suggestion}},
            'required': ['summary', 'classification', 'scope', 'limitations', 'image_observations', 'suggestions']}


def readonly_analysis(payload, runner=None, timeout=180):
    """One ephemeral, tool-disabled CLI invocation with no production session."""
    from easel_workbench.runtime.readonly_codex import command, CODEX
    from easel_workbench.readonly_runner import run,recorded_output,project_snapshot
    if runner is None and not CODEX.is_file() and not project_snapshot(payload.get('creator_snapshot')):
        raise ValueError('本机只读分析能力不可用，原件与待分析状态已保留')
    injected_runner=runner
    runner = runner or subprocess.run
    with tempfile.TemporaryDirectory(prefix='creative-learning-') as directory:
        folder = Path(directory)
        (folder / 'schema.json').write_text(json.dumps(analysis_schema(), ensure_ascii=False), encoding='utf-8')
        images = payload.get('images', [])
        if not isinstance(images, list) or len(images) > 4:
            raise ImageInputUnavailable('单次图像输入数量无效')
        args = command(folder)
        verified_images = []
        total_bytes = 0
        for index, original in enumerate(images):
            descriptor, raw = verified_image_input(original)
            total_bytes += len(raw)
            if total_bytes > 40 * 1024 * 1024:
                raise ImageInputUnavailable('本次图像合计超过有界输入范围')
            suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif'}[descriptor['mime']]
            attachment = folder / ('image-' + str(index + 1) + suffix)
            attachment.write_bytes(raw)
            # Submit an exact-byte temporary copy so an external editor cannot
            # swap source bytes between verification and CLI attachment reading.
            args[-1:-1] = ['--image', str(attachment)]
            verified_images.append({key: value for key, value in descriptor.items() if key != 'path'})
        prompt_payload = {**payload, 'images': verified_images}
        from easel_workbench.runtime.task_runtime import contract_prompt,observed_call
        from easel_workbench.runtime.desk import ROOT
        trace_box=payload.get('_runtime_root') or (folder/'trace-runtime' if runner is not subprocess.run else ROOT)
        clean_payload={key:value for key,value in prompt_payload.items() if not key.startswith('_runtime_') and key!='creator_snapshot'}
        prompt,binding=contract_prompt(trace_box,'reference','references/reference-observation.md',clean_payload,snapshot=payload.get('creator_snapshot'),profile_id=payload.get('profile_id','oil-pig'))
        env = {key: value for key, value in os.environ.items() if key not in ('OPENAI_API_KEY', 'CODEX_API_KEY')}
        with observed_call(trace_box,'reference',clean_payload,prompt,binding,payload.get('_runtime_task_id')) as record_result:
            result = run(binding if project_snapshot(payload.get('creator_snapshot')) else None,args,runner=injected_runner,input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=timeout, env=env, cwd=folder, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),runtime_root=trace_box,task_id=payload.get('_runtime_task_id'))
            if result.returncode != 0:
                raise ValueError('只读分析没有完成，未导入终端输出或改写长期策略')
            answer = folder / 'answer.json'
            if not answer.is_file() or answer.stat().st_size > 1_000_000:
                raise ValueError('只读分析缺少有界JSON回执')
            document = json.loads(answer.read_text(encoding='utf-8-sig'))
            if not isinstance(document, dict) or not isinstance(document.get('suggestions'), list):
                raise ValueError('分析回执结构无效')
            bounded(packed(document), 1_000_000, True)
            for suggestion in document['suggestions']:
                if isinstance(suggestion, dict) and isinstance(suggestion.get('conditions'), dict):
                    suggestion['conditions'] = {key: value for key, value in suggestion['conditions'].items() if value is not None}
            if verified_images:
                document['input_images'] = verified_images
            record_result(recorded_output(result,document))
            return document


def batch_schema(domain):
    if domain == 'news_interest':
        fields = {'signal': {'type': 'string', 'enum': ['positive', 'negative', 'mixed', 'correction']},
                  'reason_kind': {'type': 'string', 'enum': ['none', 'interest', 'production', 'mixed', 'correction']},
                  'learning': {'type': 'string', 'enum': ['none', 'support', 'hypothesis', 'correction']},
                  'rule_ids': {'type': 'array', 'items': {'type': 'string'}},
                  'duplicate_of': {'anyOf': [{'type': 'string'}, {'type': 'null'}]}}
        for key in ('analysis', 'scope', 'counterexamples', 'profile_note', 'correction_quote'):
            fields[key] = {'type': 'string'}
        finding = {'type': 'object', 'additionalProperties': False,
                   'properties': {'source_id': {'type': 'string'}, 'proposal': {'type': 'object', 'additionalProperties': False, 'properties': fields, 'required': list(fields)}},
                   'required': ['source_id', 'proposal']}
        properties = {'summary': {'type': 'string'}, 'findings': {'type': 'array', 'items': finding}}
    else:
        original = analysis_schema()
        finding_properties = {key: value for key, value in original['properties'].items() if key != 'suggestions'}
        finding_properties['source_id'] = {'type': 'string'}
        suggestion = original['properties']['suggestions']['items']
        suggestion['properties']['source_ids'] = {'type': 'array', 'items': {'type': 'string'}}
        suggestion['required'].append('source_ids')
        properties = {'summary': {'type': 'string'}, 'findings': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                      'properties': finding_properties, 'required': list(finding_properties)}},
                      'suggestions': {'type': 'array', 'items': suggestion}}
    return {'type': 'object', 'additionalProperties': False, 'properties': properties, 'required': list(properties)}


def readonly_batch_analysis(payload, runner=None, timeout=300):
    """Exactly one tool-disabled call for a frozen multi-source learning pack."""
    from easel_workbench.runtime.readonly_codex import command, CODEX
    from easel_workbench.runtime.batch_learning import LIMITS
    from easel_workbench.readonly_runner import run,recorded_output,project_snapshot
    if runner is None and not CODEX.is_file() and not project_snapshot(payload.get('creator_snapshot')):
        raise ValueError('本机只读学习能力不可用；材料保留待整理')
    members = payload.get('members', [])
    images = payload.get('images', [])
    profile_chars = sum(len(value) for value in payload.get('profile_documents', {}).values())
    if not 1 <= len(members) <= LIMITS['events'] or len(images) > LIMITS['images'] or sum(row.get('input_text_chars', len(row.get('text', ''))) for row in members) + profile_chars > LIMITS['text_chars']:
        raise ValueError('学习包超过已批准输入范围')
    with tempfile.TemporaryDirectory(prefix='creative-batch-') as directory:
        folder = Path(directory)
        (folder / 'schema.json').write_text(json.dumps(batch_schema(payload['domain']), ensure_ascii=False), encoding='utf-8')
        args = command(folder)
        attached = []
        total = 0
        for index, original in enumerate(images):
            descriptor, raw = verified_image_input(original)
            total += len(raw)
            if total > LIMITS['image_bytes']:
                raise ImageInputUnavailable('本包图片总量超过40MB')
            suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif'}[descriptor['mime']]
            path = folder / ('image-' + str(index + 1) + suffix)
            path.write_bytes(raw)
            args[-1:-1] = ['--image', str(path)]
            attached.append({key: value for key, value in descriptor.items() if key != 'path'})
        submitted = {**payload, 'images': attached}
        from easel_workbench.runtime.task_runtime import contract_prompt,observed_call
        from easel_workbench.runtime.desk import ROOT
        trace_box=payload.get('_runtime_root') or (folder/'trace-runtime' if runner is not None else ROOT)
        clean_payload={key:value for key,value in submitted.items() if not key.startswith('_runtime_') and key!='creator_snapshot'}
        prompt,binding=contract_prompt(trace_box,'learning','references/incremental-learning.md',clean_payload,snapshot=payload.get('creator_snapshot'))
        prompt += '\n只返回schema JSON。'
        env = {key: value for key, value in os.environ.items() if key not in ('OPENAI_API_KEY', 'CODEX_API_KEY')}
        with observed_call(trace_box,'learning',clean_payload,prompt,binding,payload.get('_runtime_task_id')) as record_result:
            result = run(binding if project_snapshot(payload.get('creator_snapshot')) else None,args,runner=runner,input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                                timeout=timeout, env=env, cwd=folder, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),runtime_root=trace_box,task_id=payload.get('_runtime_task_id'))
            if result.returncode != 0:
                raise ValueError('只读批量学习未完成；未导入终端输出')
            path = folder / 'answer.json'
            if not path.is_file() or path.stat().st_size > 1_000_000:
                raise ValueError('只读学习缺少有界回执')
            value = json.loads(path.read_text(encoding='utf-8-sig'))
            bounded(packed(value), 1_000_000, True)
            for suggestion in value.get('suggestions', []):
                suggestion['conditions'] = {key: val for key, val in suggestion.get('conditions', {}).items() if val is not None}
            record_result(recorded_output(result,value))
            return value


def readonly_skill_distillation(payload, runner=None, timeout=300):
    """One explicit request creates a candidate skill revision, never a default."""
    from easel_workbench.runtime.readonly_codex import command
    from easel_workbench.runtime.task_runtime import contract_prompt, observed_call
    from easel_workbench.readonly_runner import run,recorded_output,project_snapshot
    fields = {'changed': {'type': 'boolean'}, 'reason': {'type': 'string'},
              'prompt': {'type': 'string'}, 'conditions': {'type': 'string'},
              'evidence_refs': {'type': 'array', 'items': {'type': 'string'}},
              'validation': {'type': 'array', 'items': {'type': 'string'}},
              'responses':{'type':'array','items':{'type':'object','additionalProperties':False,
                'properties':{'source_id':{'type':'string'},'outcome':{'type':'string','enum':['propose_change','retain','work_only','insufficient']},
                              'reason':{'type':'string'}},'required':['source_id','outcome','reason']}},
              'image_observations':{'type':'array','items':{'type':'object','additionalProperties':False,
                'properties':{'sha256':{'type':'string'},'status':{'type':'string','enum':['observed','unverified']},
                  'description':{'type':'string'},'limitations':{'type':'array','items':{'type':'string'}}},
                'required':['sha256','status','description','limitations']}}}
    if payload.get('split_profile_skill'):
        fields['profile_changes']={'type':'array','items':{'type':'object','additionalProperties':False,
            'properties':{'field':{'type':'string','enum':['identity','audience','voice','boundaries']},'value':{'type':'string'},'reason':{'type':'string'},'evidence_refs':{'type':'array','items':{'type':'string'}}},
            'required':['field','value','reason','evidence_refs']}}
    schema = {'type': 'object', 'additionalProperties': False, 'properties': fields, 'required': list(fields)}
    with tempfile.TemporaryDirectory(prefix='skill-distillation-') as directory:
        folder = Path(directory)
        (folder/'schema.json').write_text(json.dumps(schema, ensure_ascii=False), encoding='utf-8')
        root = payload['_runtime_root']
        submitted = {k: v for k, v in payload.items() if not k.startswith('_runtime_') and k != 'creator_snapshot'}
        args=command(folder);attached=[];image_bytes=0
        if len(payload.get('images',[]))>8:raise ValueError('技能整理最多附8张静态原图')
        for index,original in enumerate(payload.get('images',[])):
            descriptor,raw=verified_image_input(original);image_bytes+=len(raw)
            if image_bytes>40*1024*1024:raise ValueError('技能整理图片总量超过40MiB')
            image=folder/('reference-'+str(index)+Path(descriptor['path']).suffix);image.write_bytes(raw)
            args[-1:-1]=['--image',str(image)]
            attached.append({**{k:v for k,v in descriptor.items() if k!='path'},'evidence_id':original.get('evidence_id')})
        submitted['images']=attached
        submitted['output_contract'] = {'changed': '是否有充分依据修改', 'prompt': '修改后的完整技能提示词，未改则原文',
            'reason': '改动理由与不能推广的部分', 'conditions': '适用条件', 'evidence_refs': '只引用members中的真实ID',
            'validation': '可执行的验证案例；不声称已通过','image_observations':'按实际附图SHA逐张观察；未附图不声称看过，没有图片时空数组'}
        if payload.get('split_profile_skill'):
            submitted['output_contract']['profile_changes']='身份、读者、表达偏好和红线提出画像字段候选；每项真实依据ID、理由和完整新字段。changed/prompt只处理可复用制作方法。单篇反馈留原版本，平台数据只是观察，不自动推广。没有画像修改时空数组。'
        prompt, binding = contract_prompt(root, 'learning', 'references/skill-distillation.md', submitted,
                                         snapshot=payload['creator_snapshot'])
        env = {k: v for k, v in os.environ.items() if k not in ('OPENAI_API_KEY', 'CODEX_API_KEY')}
        with observed_call(root, 'learning', submitted, prompt, binding, payload.get('_runtime_task_id')) as record:
            process = run(binding if project_snapshot(payload.get('creator_snapshot')) else None,args,runner=runner,input=prompt, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=timeout, cwd=folder, env=env,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),runtime_root=root,task_id=payload.get('_runtime_task_id'))
            output = folder/'answer.json'
            if process.returncode or not output.is_file() or output.stat().st_size > 1_000_000:
                raise ValueError('技能整理未取得有界回执')
            result = json.loads(output.read_text(encoding='utf-8-sig'))
            if not isinstance(result, dict) or set(result) != set(fields) or type(result['changed']) is not bool:
                raise ValueError('技能整理回执结构无效')
            record(recorded_output(process,result))
            return result


class LearningWorker:
    def __init__(self, service, runner=None, production_review=None, batch_runner=None, distillation_runner=None):
        self.service = service
        self.runner = runner or readonly_analysis
        self.batch_runner = batch_runner or runner or readonly_batch_analysis
        self.production_review = production_review
        self.distillation_runner = distillation_runner or readonly_skill_distillation
        self.owner = uuid.uuid4().hex
        self.stop = threading.Event()

    def process_one(self):
        task = self.service.claim_task(self.owner, lease_seconds=600)
        if not task:
            return None
        try:
            if task['kind'] == 'production_review':
                handler = self.production_review
                if handler is None:
                    from easel_workbench.runtime.learning_execution import run_review
                    handler = run_review
                result = handler(self.service, task)
                if result is None:
                    result = {'status': 'completed'}
                elif isinstance(result, dict) and result.get('status') not in ('completed', 'failed', 'blocked', 'cancelled'):
                    # Quality states (ready/unverified/needs_review) belong to
                    # the run; a completed review is still a completed queue job.
                    result = {'status': 'completed', 'quality': result}
            elif task['kind'] == 'index_refresh':
                receipt = self.service.command({'action': 'index-refresh', 'operation_id': task['id']})
                result = {'status': 'completed', **receipt['result']}
            elif task['kind'] == 'batch_analysis':
                return self._process_batch(task)
            elif task['kind'] == 'skill_distillation':
                result = self._distill_skill(task)
            elif task['kind'] == 'reference_analysis':
                result = self._analyze_reference(task)
            elif task['kind'] == 'evidence_analysis':
                with self.service.store.connect() as c:
                    evidence = self.service.evidence_content(c, task['payload']['evidence_id'])
                if not evidence['available'] or evidence['sha256'] != task['payload']['sha256']:
                    result = {'status': 'blocked', 'error': '原件缺失或SHA变化，未使用分析或缓存冒充原话'}
                elif evidence['content'] is None:
                    try:
                        original = self.service.original_file(evidence['id'])
                        image, _ = verified_image_input(original)
                    except (ImageInputUnavailable, LearningConflict, OSError):
                        result = {'status': 'blocked', 'error': '尚未取得可核对的静态图像；视频、音频、动图或缺失原件保留待核对，未伪称已看过'}
                    else:
                        analysis = self.runner({'evidence_id': evidence['id'], 'sha256': evidence['sha256'],
                                                'source': original.get('source', evidence['verified_source']), 'content': None,
                                                'content_is_original': True, 'images': [image]})
                        media_inputs = [{key: value for key, value in image.items() if key != 'path'}]
                        if image_observations_complete(analysis, [image]):
                            analysis['input_images'] = media_inputs
                            result = {'status': 'completed', 'analysis': analysis, 'media_inputs': media_inputs,
                                      'media_verification': 'original_bytes_attached_observations_are_ai_candidate'}
                        else:
                            result = {'status': 'blocked', 'analysis': analysis, 'media_inputs': media_inputs,
                                      'error': '图片已作为只读输入提交，但缺少对应原始SHA的实际可见观察；未记录为图像分析完成'}
                elif len(evidence['content']) > 200000:
                    result = {'status': 'blocked', 'error': '原件超过单次有界分析范围，需分段核对；未声称完整分析'}
                else:
                    analysis = self.runner({'evidence_id': evidence['id'], 'sha256': evidence['sha256'],
                                            'source': evidence['verified_source'], 'content': evidence['content'],
                                            'content_is_original': True, 'images': []})
                    result = {'status': 'completed', 'analysis': analysis}
            else:
                result = {'status': 'blocked', 'error': '未知学习任务类型，未执行'}
        except (TimeoutError, subprocess.TimeoutExpired, ConnectionError):
            result = {'status': 'blocked', 'error': '模型回执未知，保留本次调用身份待核对；未自动重放'}
        except Exception as error:
            # Provider errors may include credential-bearing URLs or raw process
            # output. Keep only a stable, non-sensitive failure category.
            result = {'status': 'failed', 'error': '学习任务未完成（' + type(error).__name__ + '）；原件、候选和冻结快照保留'}
        try:
            self.service.finish_task(task['id'], task['lease_token'], result)
        except LearningConflict:
            return {'task': task, 'result': {'status': 'blocked', 'error': '原回执已失效，未覆盖新状态'}}
        except (ValueError, TypeError, KeyError):
            result = {'status': 'failed', 'error': '学习回执未通过结构与来源校验，未写入长期策略'}
            self.service.finish_task(task['id'], task['lease_token'], result)
        return {'task': task, 'result': result}

    def _distill_skill(self, task):
        from easel_workbench.runtime.task_runtime import registry,complete_experience
        payload = {**task['payload'], '_runtime_root': str(self.service.root), '_runtime_task_id': task['id']}
        result = self.distillation_runner(payload)
        if payload.get('images') and not image_observations_complete(result,payload['images']):
            return {'status':'blocked','analysis':result,'error':'参考图已附入本轮，但未取得准确SHA对应的观察；没有发布候选或冒称看过。'}
        ids = {row['id'] for row in payload['members']}
        refs = result.get('evidence_refs')
        if not isinstance(refs, list) or len(refs) != len(set(refs)) or not set(refs) <= ids:
            raise ValueError('整理结果伪造、重复或遗漏来源身份')
        if type(result.get('changed')) is not bool or not isinstance(result.get('reason'), str):
            raise ValueError('整理结果缺少明确结论')
        if result['changed'] and not refs:
            raise ValueError('技能改动必须引用本包真实依据')
        responses=result.get('responses',[])
        if len(responses)!=len(ids) or {r.get('source_id') for r in responses}!=ids or any(r.get('outcome') not in ('propose_change','retain','work_only','insufficient') or not isinstance(r.get('reason'),str) or not r['reason'].strip() for r in responses):
            raise ValueError('每项真实反馈必须有唯一的处理结论与理由')
        if not result['changed']:
            with self.service.store.connect() as c:
                from easel_workbench.runtime.profile_learning import propose
                proposal=propose(registry(self.service.box,c),c,payload,result,task['id']) if payload.get('split_profile_skill') else None
                complete_experience(c,payload,task['id'])
            return {'status': 'completed', 'changed': False, 'reason': result['reason'], 'model_calls': 1,
                    'profile_id': payload['profile_id'], 'evidence_refs': refs,'responses':responses,'profile_proposal_id':proposal}
        prompt = result.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 160000:
            raise ValueError('候选技能缺少完整提示词')
        with self.service.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            candidate = registry(self.service.box, c).propose(c, payload['skill_id'], payload['base_version'], prompt,
                reason=result['reason'], evidence_refs=refs, conditions=result.get('conditions', ''),
                operation_id=payload['operation_id'],validation_cases=result.get('validation',[]))
            from easel_workbench.runtime.profile_learning import propose
            proposal=propose(registry(self.service.box,c),c,payload,result,task['id']) if payload.get('split_profile_skill') else None
            complete_experience(c,payload,task['id'])
        return {'status': 'completed', 'changed': True, 'candidate': candidate, 'skill_id': payload['skill_id'],
                'version': candidate['version'], 'profile_id': payload['profile_id'], 'model_calls': 1,
                'validation': result.get('validation', []), 'evidence_refs': refs,
                'responses':responses,
                'profile_proposal_id':proposal,
                'notice': '候选已保存，尚未发布或成为默认；验证建议未冒称已执行。'}

    def _analyze_reference(self, task):
        payload = task['payload']
        images=payload.get('images',[])
        for image in images:verified_image_input(image)
        if 'content' not in payload:
            # Compatibility with an already queued explicit reference task.
            with self.service.store.connect() as c:evidence=self.service.evidence_content(c,payload['evidence_id'])
            if not evidence.get('available') or evidence['sha256']!=payload['sha256']:
                return {'status':'blocked','error':'原件缺失或字节变化，未调用模型'}
            payload={**payload,'content':evidence.get('content')}
        if payload.get('content') is None and not images:
            return {'status':'blocked','error':'未取得实际静态参考图，没有声称视觉分析或调用模型'}
        submitted = {**payload, 'images': images,
                     'content_is_original': True, '_runtime_root': str(self.service.root), '_runtime_task_id': task['id']}
        analysis = self.runner(submitted)
        if images and not image_observations_complete(analysis, images):
            return {'status': 'blocked', 'analysis': analysis, 'error': '未取得原图对应的可核对观察'}
        return {'status': 'completed', 'analysis': analysis, 'model_calls': 1,
                'authority': 'candidate_reference_observation', 'notice': '参考观察已保存；未自动改写画像或技能。'}

    def _process_batch(self, task):
        batch_id = task['payload']['batch_id']
        call = None
        analysis = None
        payload = None
        try:
            with self.service.store.connect() as c:
                batch = self.service.batch.get(c, 'learning_batches', batch_id)
            payload = {**self.service.batch.payload(batch), '_runtime_root': str(self.service.root), '_runtime_task_id': task['id']}
            # Before counting/sending, recheck every immutable static image.
            for original in payload['images']:
                verified_image_input(original)
            call = self.service.batch.begin_call(batch_id)
            analysis = self.batch_runner(payload)
            result = {'status': 'completed', 'analysis': analysis, 'usage': analysis.pop('_usage', {})}
            if 'profile_version' in payload:
                result['profile_version'] = payload['profile_version']
            self.service.batch.complete(batch_id, result, call['id'])
        except (subprocess.TimeoutExpired, TimeoutError, ConnectionError):
            result = {'status': 'blocked', 'error': '模型回执未知，保留调用身份并待核对；未自动重放'}
            self.service.batch.complete(batch_id, result, call['id'] if call else None)
        except Conflict:
            result = {'status': 'blocked', 'analysis': analysis, 'profile_version': (payload or {}).get('profile_version'),
                      'error': '新闻兴趣画像并发变化，原结果保留待核对，未重复调用或覆盖画像'}
            self.service.batch.complete(batch_id, result, call['id'] if call else None)
        except Exception as error:
            result = {'status': 'failed', 'analysis': analysis, 'error': '学习包未完成（' + type(error).__name__ + '）；原件和来源身份保留'}
            self.service.batch.complete(batch_id, result, call['id'] if call else None)
        self.service.finish_task(task['id'], task['lease_token'], result)
        return {'task': task, 'result': result}

    def tick(self):
        self.service.queue_index_refresh()
        return self.process_one()

    def close(self):
        self.stop.set()
        self.service.wake_event.set()

    def run(self):
        with locked(self.service.state / 'worker.lock', timeout=.2):
            while not self.stop.is_set():
                self.service.wake_event.clear()
                if self.tick() is not None:
                    continue
                # In-process writes signal immediately. A bounded durable-queue
                # wake also notices an event committed by the web process.
                self.service.wake_event.wait(3)


def run(root=None, project=None):
    from easel_workbench.runtime.project_paths import ROOT
    from easel_workbench.runtime.desk import Store
    from easel_workbench.runtime.toolbox_store import Toolbox
    from easel_workbench.runtime.studio_service import StudioService
    from easel_workbench.runtime.learning_service import LearningService
    root = Path(root or ROOT)
    box = Toolbox(Store(root / 'data' / 'desk.sqlite'), root)
    studio = StudioService(box, project=project)
    worker = LearningWorker(LearningService(box, studio, root, project))
    try:
        worker.run()
    finally:
        worker.close()


if __name__ == '__main__':
    run()
