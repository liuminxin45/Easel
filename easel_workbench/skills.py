"""Pure task and launch policy for the private skill workflow.

The canonical registry supplies skill identities, task scopes and executors.
This module holds the existing service safety contract and presents those
registered scopes as launch actions; it does not discover or execute skills.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping


TASK_DEFAULTS = {
    'poster': ['content-writing', 'image-production', 'delivery-review'],
    'article': ['content-writing', 'image-production', 'delivery-review'],
    'change': ['content-writing', 'image-production', 'delivery-review'],
    'discuss': ['topic-research'], 'research': ['topic-research'],
    'reference': ['reference-analysis'], 'review': ['delivery-review'],
    'analysis': ['publication-analysis'], 'learning': ['experience-distillation'],
    'news_enhancement': ['topic-research'], 'image': ['image-production', 'delivery-review'],
    # Historical profiles may retain these empty, retired task slots.
    'media': [], 'speech': [], 'video': [], 'music': [], 'transcribe': [], 'compose': [],
}
RETIRED_TASKS = frozenset(task for task, defaults in TASK_DEFAULTS.items() if not defaults)
RETIRED_EASEL_SKILLS = frozenset((
    'easel-voiceover', 'easel-image', 'easel-video', 'easel-music',
    'easel-transcribe', 'easel-compose',
))


def execution_kind(skill: Mapping) -> str:
    executor = skill.get('executor')
    if executor == 'workflow':
        return 'workflow'
    return 'program' if executor in ('program', 'script') else 'agent'


def supports_task(skill: Mapping, task: str) -> bool:
    tasks = skill.get('tasks')
    if not isinstance(tasks, list) or task not in TASK_DEFAULTS or task in RETIRED_TASKS:
        return False
    if task in tasks:
        return True
    # The existing image workflow reserves this exact independent checker.
    # Its canonical scope calls that role "review", rather than image creation.
    return (task == 'image' and skill.get('id') == 'delivery-review'
            and skill.get('executor') == 'readonly-agent' and 'review' in tasks)


def require_task(skill: Mapping, task: str) -> None:
    if not supports_task(skill, task):
        raise ValueError('所选技能不适用于本次任务：' + str(skill.get('name') or skill.get('id')) + ' / ' + str(task))


def requirements(task: str) -> dict:
    required_all = []
    required_any = []
    if task in ('poster', 'article', 'change', 'image'):
        required_all.append('delivery-review')
        if task == 'article':
            required_all.append('content-writing')
        elif task == 'image':
            required_all.append('image-production')
        else:
            required_any.append(['content-writing', 'image-production'])
    return {'required_all': required_all, 'required_any': required_any}


def require_selection(task: str, skill_ids: Iterable[str]) -> None:
    selected = set(skill_ids)
    policy = requirements(task)
    if 'delivery-review' in policy['required_all'] and 'delivery-review' not in selected:
        raise ValueError('制作任务须保留交付核验技能；尚未启动制作')
    if (set(policy['required_all']) - selected
            or any(not selected.intersection(group) for group in policy['required_any'])):
        raise ValueError('请选择能完成本次任务的写作或配图技能；尚未启动制作')


def task_policy(skills: Iterable[Mapping]) -> dict:
    skills = tuple(skills)
    return {
        task: {
            **requirements(task),
            'entry_skills': [skill['id'] for skill in skills
                             if skill.get('status') == 'published'
                             and execution_kind(skill) == 'workflow'
                             and supports_task(skill, task)],
        }
        for task in TASK_DEFAULTS if task not in RETIRED_TASKS
    }


def launch_actions(skill: Mapping) -> list[dict]:
    """Project registered task scopes onto existing, authorized product flows.

    Action paths deliberately omit identity/version/trial. The caller must bind
    the exact displayed release and profile when the user selects an action.
    """
    if skill.get('id') in RETIRED_EASEL_SKILLS:
        return []
    tasks = skill.get('tasks')
    if not isinstance(tasks, list):
        return []
    result = []
    for task, label, path, format_ in (
        ('poster', '制作贴图', '/posters/new', 'poster'),
        ('article', '撰写文章', '/articles/new', 'article'),
    ):
        if task in tasks:
            result.append({'id': task, 'label': label, 'path': path, 'task': task, 'format': format_})
    # The existing research screen submits a discussion task. Do not advertise
    # a research-only release as that different execution scope.
    if 'discuss' in tasks:
        result.append({'id': 'discuss', 'label': '研究选题', 'path': '/posters/new?mode=research', 'task': 'discuss'})
    for task, label, path in (
        ('reference', '拆解参考', '/toolbox?section=research&pane=breakdown'),
        ('learning', '整理经验', '/toolbox?section=skills&pane=experience'),
        ('analysis', '分析传播', '/toolbox?section=insights'),
    ):
        if task in tasks:
            result.append({'id': task, 'label': label, 'path': path, 'task': task})
    for task, label in (('change', '选择作品后修改'), ('review', '选择版本后核验')):
        if task in tasks:
            result.append({'id': task, 'label': label, 'path': '/works', 'task': task, 'requires_context': True})
    return result


def launch_metadata(skill: Mapping) -> dict:
    return {'execution_kind': execution_kind(skill), 'launch_actions': launch_actions(skill)}
