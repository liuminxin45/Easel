"""Discover private capabilities from Easel's project-local builtin skills.

SKILL.md is the current source. Database releases retain immutable historical
instructions; the provenance report is never used as another registry.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re

import yaml


class CatalogError(ValueError):
    pass


def parse_skill(source: str) -> tuple[dict, str]:
    match=re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)',source,re.S)
    if not match:raise CatalogError('项目技能缺少元信息头部')
    try:metadata=yaml.safe_load(match[1])
    except yaml.YAMLError:raise CatalogError('项目技能元信息无效') from None
    if not isinstance(metadata,dict):raise CatalogError('项目技能元信息无效')
    return metadata,source[match.end():]


class ProjectSkillCatalog:
    def __init__(self,root):
        self.root=Path(root).resolve()
        self.directory=self.root/'skills/builtin'

    def path(self,name):
        if not isinstance(name,str) or not name or '\\' in name or Path(name).is_absolute() or '..' in Path(name).parts:
            raise CatalogError('项目技能资源路径无效')
        path=(self.root/name).resolve()
        if not path.is_relative_to(self.root/'skills') or not path.is_file():
            raise CatalogError('项目技能资源缺失或离开技能目录：'+name)
        return path

    def entries(self):
        result=[]
        for path in sorted(self.directory.glob('*/SKILL.md')):
            self.path(path.relative_to(self.root).as_posix())
            metadata,_=parse_skill(path.read_text(encoding='utf-8-sig'))
            extra=metadata.get('metadata',{})
            openclaw=extra.get('openclaw',{}) if isinstance(extra,dict) else {}
            raw=openclaw.get('workbench') if isinstance(openclaw,dict) else None
            if raw is None:continue
            if not isinstance(raw,dict) or raw.get('schema_version')!=1:raise CatalogError('项目能力元信息无效')
            value=copy.deepcopy(raw);sid=value.get('id')
            if not isinstance(sid,str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',sid) or sid!=path.parent.name or metadata.get('name')!=sid:
                raise CatalogError('项目能力身份与技能目录不一致')
            if not isinstance(value.get('tasks'),list) or not value['tasks'] or any(not isinstance(t,str) for t in value['tasks']):
                raise CatalogError('项目能力缺少适用任务')
            if metadata.get('layer') not in ('discover','plan','produce','publish','attribute','general'):
                raise CatalogError('项目技能分层无效')
            value.update(name=value.pop('display_name',sid),description=metadata.get('description',''),
                         entry=path.relative_to(self.root).as_posix(),layer=metadata['layer'])
            resources=[];evidence=[]
            for resource in value.get('resources',[]):
                if not isinstance(resource,dict):raise CatalogError('项目技能资源清单无效')
                self.path(resource.get('path'))
                if resource.get('historical') or resource.get('executable') is False or resource.get('kind') in ('legacy_script','legacy_operation','historical_index'):
                    evidence.append(resource)
                else:resources.append(resource)
            value['resources']=resources
            value['provenance_resources']=evidence
            result.append(value)
        ids={s['id'] for s in result}
        for skill in result:
            dependencies=skill.get('composition',{}).get('requires',[])
            if not isinstance(dependencies,list) or any(dep not in ids or dep==skill['id'] for dep in dependencies):
                raise CatalogError('组合技能引用了未登记能力')
        def visit(sid,seen):
            if sid in seen:raise CatalogError('组合技能存在循环引用')
            skill=next(s for s in result if s['id']==sid)
            for dep in skill.get('composition',{}).get('requires',[]):visit(dep,{*seen,sid})
        for sid in ids:visit(sid,set())
        return result

    def document(self):
        return {'schema_version':1,'registry_type':'easel_project_builtin',
                'skills':self.entries(),'candidates':[],'revision':self.revision()}

    def revision(self):
        files={}
        for entry in self.entries():
            for name in [entry['entry'],*[r['path'] for r in entry['resources']]]:
                files[name]=hashlib.sha256(self.path(name).read_bytes()).hexdigest()
        return hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def available(self):
        return bool(self.entries())
