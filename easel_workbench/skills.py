"""Pure task and launch policy for the private skill workflow.

The canonical registry supplies skill identities, task scopes and executors.
This module holds the existing service safety contract and presents those
registered scopes as launch actions; it does not discover or execute skills.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping


TASK_DEFAULTS = {
    'poster': ['oil-pig-poster'],
    'article': ['oil-pig-article'],
    'change': [],
    'discuss': [], 'research': [], 'reference': [], 'review': [],
    'analysis': [], 'learning': [], 'news_enhancement': [],
    'image': ['oil-pig-poster'],
    # Historical profiles may retain these empty, retired task slots.
    'media': [], 'speech': [], 'video': [], 'music': [], 'transcribe': [], 'compose': [],
}
RETIRED_TASKS = frozenset(task for task, defaults in TASK_DEFAULTS.items() if not defaults and task != 'change')
RETIRED_EASEL_SKILLS = frozenset((
    'easel-voiceover', 'easel-image', 'easel-video', 'easel-music',
    'easel-transcribe', 'easel-compose',
    'experience-distillation', 'content-production', 'topic-research',
    'content-writing', 'image-production', 'delivery-review',
    'reference-analysis', 'publication-analysis',
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
    return task == 'image' and skill.get('id') == 'oil-pig-poster' and 'poster' in tasks


def require_task(skill: Mapping, task: str) -> None:
    if not supports_task(skill, task):
        raise ValueError('所选技能不适用于本次任务：' + str(skill.get('name') or skill.get('id')) + ' / ' + str(task))


def requirements(task: str) -> dict:
    required_all = []
    required_any = []
    if task in ('poster', 'image'):
        required_all.append('oil-pig-poster')
    elif task == 'article':
        required_all.append('oil-pig-article')
    elif task == 'change':
        required_any.append(['oil-pig-poster', 'oil-pig-article'])
    return {'required_all': required_all, 'required_any': required_any}


def require_selection(task: str, skill_ids: Iterable[str]) -> None:
    selected = set(skill_ids)
    policy = requirements(task)
    if (set(policy['required_all']) - selected
            or any(not selected.intersection(group) for group in policy['required_any'])):
        raise ValueError('请选择与本次任务对应的油猪技能；尚未启动制作')


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
    ):
        if task in tasks:
            result.append({'id': task, 'label': label, 'path': path, 'task': task})
    for task, label in (('change', '选择作品后修改'), ('review', '选择版本后核验')):
        if task in tasks:
            result.append({'id': task, 'label': label, 'path': '/works', 'task': task, 'requires_context': True})
    return result


def launch_metadata(skill: Mapping) -> dict:
    return {'execution_kind': execution_kind(skill), 'launch_actions': launch_actions(skill)}
