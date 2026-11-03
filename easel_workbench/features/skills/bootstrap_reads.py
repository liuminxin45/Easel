"""SQL-only capability descriptors; release bodies belong to explicit detail."""
import json

from easel_workbench.skills import RETIRED_EASEL_SKILLS,launch_metadata


PROFILE_FIELDS=('id','name','revision','active','default_skills','skill_versions','task_skill_versions','account_ids')
SKILL_FIELDS=('id','name','description','version','created_at','sha256','origin','source_revision','entry','layer','tasks','executor')


def _object(fields):
    return 'json_object('+','.join("'"+field+"',json_extract(document,'$."+field+"')" for field in fields)+')'


def profiles(c,*,summary=False):
    column=_object(PROFILE_FIELDS) if summary else 'document'
    result=[json.loads(row[0]) for row in c.execute('SELECT '+column+' FROM creator_profiles ORDER BY rowid')]
    if summary:
        for item in result:
            if type(item.get('active')) is int:item['active']=bool(item['active'])
    return result


def skills(c):
    versions={}
    for row in c.execute("""SELECT v.skill_id,v.version,json_extract(v.document,'$.created_at') AS created_at,
        CASE WHEN json_extract(v.document,'$.status')='published' OR EXISTS(
          SELECT 1 FROM creator_skill_events e WHERE e.skill_id=v.skill_id AND e.version=v.version AND e.action='publish')
        THEN 'published' ELSE 'candidate' END AS status FROM creator_skill_versions v ORDER BY v.version DESC"""):
        versions.setdefault(row['skill_id'],[]).append({'version':row['version'],'status':row['status'],'created_at':row['created_at']})
    result=[]
    for row in c.execute('SELECT id FROM creator_skills ORDER BY rowid'):
        sid=row['id']
        if sid in RETIRED_EASEL_SKILLS:continue
        pointer=c.execute('SELECT version FROM creator_skill_pointers WHERE skill_id=?',(sid,)).fetchone()
        if not pointer:raise ValueError('找不到技能')
        published=pointer[0];history=versions.get(sid,[])
        version=published or (history[0]['version'] if history else None)
        if not isinstance(version,int) or isinstance(version,bool) or version<1:raise ValueError('技能版本无效')
        current=c.execute('SELECT '+_object(SKILL_FIELDS)+' FROM creator_skill_versions WHERE skill_id=? AND version=?',(sid,version)).fetchone()
        if not current:raise ValueError('找不到技能版本')
        item=json.loads(current[0]);item.update(published_version=published,is_current=published==version,
            status=next(row['status'] for row in history if row['version']==version),versions=history)
        item.update(launch_metadata(item));result.append(item)
    return result
