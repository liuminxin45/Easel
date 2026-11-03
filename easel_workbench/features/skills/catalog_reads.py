"""Read-only catalog projections; execution still resolves full frozen releases."""
import json


def release_metadata(c, skill_id):
    fields=('id','name','description','layer','entry','origin','tasks','executor',
            'execution_role','composition','input_contract','output_contract',
            'acceptance_cases','sha256','prompt','resources','version','status')
    columns=','.join("json_extract(v.document,'$."+field+"') AS "+field for field in fields)
    row=c.execute('SELECT '+columns+''' FROM creator_skill_versions v
        WHERE skill_id=? AND version=COALESCE(NULLIF((SELECT version FROM creator_skill_pointers WHERE skill_id=?),0),
        (SELECT max(version) FROM creator_skill_versions WHERE skill_id=?))''',(skill_id,)*3).fetchone()
    if row is None:raise ValueError('找不到技能版本')
    result=dict(row)
    for field in ('tasks','composition','input_contract','output_contract','acceptance_cases','resources'):
        if result[field] is not None:result[field]=json.loads(result[field])
    return result
