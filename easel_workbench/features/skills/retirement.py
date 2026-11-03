"""Retired private skill authoring; immutable receipts and history remain readable."""
import copy
import hashlib
import json

RETIRED_ACTIONS=frozenset(('experience-organize','skill-draft','skill-publish','skill-revert',
                          'skill-source-reconcile','trial','profile-proposal-confirm','profile-proposal-revert'))
RETIRED_SKILL='experience-distillation'
MIGRATION='official-skills-retire-experience-v1'


def native_mode(root):
    from pathlib import Path
    path=Path(root)/'config/workbench-skills.json'
    return path.is_file() and json.loads(path.read_text(encoding='utf-8')).get('mode')=='easel-native'


def migration_runtime(root):
    """Existing database adapter without application startup or skill seeding."""
    from pathlib import Path
    from types import SimpleNamespace
    from easel_workbench.runtime.desk import Store
    from easel_workbench.features.profiles.service import ProfileService
    store=Store.__new__(Store);store.path=Path(root)/'data/desk.sqlite'
    return SimpleNamespace(store=store,_put_profile=lambda c,p:ProfileService._put_profile(None,c,p))


class SkillFeatureRetired(ValueError):
    status_code=410
    feature='private_skill_management'
    def __init__(self,action):
        self.action=action
        super().__init__('私有技能管理与整理经验已退役，请使用 Easel 原生技能流程')


def _packed(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def _sha(value):return hashlib.sha256(_packed(value).encode()).hexdigest()


def _clean(profile):
    result=copy.deepcopy(profile)
    for field in ('default_skills',):
        current=result.get(field)
        if isinstance(current,dict):
            current.pop('learning',None)
            for task,refs in current.items():
                if isinstance(refs,list):current[task]=[sid for sid in refs if sid!=RETIRED_SKILL]
                elif isinstance(refs,dict):refs.pop(RETIRED_SKILL,None)
    result.pop('skill_versions',None)
    result.pop('task_skill_versions',None)
    return result


def preview(runtime,c=None):
    if c is None:
        with runtime.store.connect() as connection:return preview(runtime,connection)
    changes=[]
    for row in c.execute('SELECT id,document FROM creator_profiles ORDER BY id'):
        before=json.loads(row['document']);after=_clean(before)
        if after==before:continue
        after['revision']=before['revision']+1
        changes.append({'id':row['id'],'base_revision':before['revision'],'before_sha256':_sha(before),'after':after})
    value={'migration':MIGRATION,'changes':changes}
    return {**value,'plan_sha256':_sha(value)}


def apply(runtime,expected_sha256):
    """Caller must hold the deployment writer fence; never starts model work."""
    with runtime.store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE IF NOT EXISTS creator_feature_retirements(id TEXT PRIMARY KEY,plan_sha256 TEXT NOT NULL,document TEXT NOT NULL)')
        old=c.execute('SELECT plan_sha256,document FROM creator_feature_retirements WHERE id=?',(MIGRATION,)).fetchone()
        if old:
            if old['plan_sha256']!=expected_sha256:raise ValueError('退役迁移已使用另一份准确计划完成')
            return json.loads(old['document'])
        plan=preview(runtime,c)
        if plan['plan_sha256']!=expected_sha256:raise ValueError('画像修订已变化，请重新核对退役计划')
        from easel_workbench.runtime.desk import stamp
        for change in plan['changes']:
            after=copy.deepcopy(change['after']);after['updated_at']=stamp()
            runtime._put_profile(c,after)
        result={'migration':MIGRATION,'plan_sha256':expected_sha256,'profiles':[{'id':r['id'],'previous_revision':r['base_revision'],'revision':r['after']['revision']} for r in plan['changes']]}
        c.execute('INSERT INTO creator_feature_retirements VALUES(?,?,?)',(MIGRATION,expected_sha256,_packed(result)))
        return result
