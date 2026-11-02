"""Read-only, minimal canary seed. Never exports sessions, works or account grants."""
import contextlib
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace


def export_seed(application_root, source_root, profile_id='oil-pig'):
    from easel_workbench.skill_catalog import ProjectSkillCatalog
    from easel_workbench.project_skill_sync import matches_source
    root=Path(application_root).resolve();source=Path(source_root).resolve()
    with contextlib.closing(sqlite3.connect((root/'data/desk.sqlite').as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
        ids={item['id'] for item in ProjectSkillCatalog(source).entries()}
        rows={};releases=[]
        for table,key in [('creator_skills','id'),('creator_skill_pointers','skill_id')]:
            rows[table]=[dict(r) for r in c.execute('SELECT * FROM '+table) if r[key] in ids]
        for row in rows['creator_skill_pointers']:
            release=c.execute('SELECT * FROM creator_skill_versions WHERE skill_id=? AND version=?',(row['skill_id'],row['version'])).fetchone()
            if not release:raise ValueError('canary_published_release_missing')
            document=json.loads(release['document'])
            if document.get('id')!=row['skill_id'] or document.get('version')!=row['version'] or document.get('status')!='published':
                raise ValueError('canary_release_identity_changed')
            if not matches_source(SimpleNamespace(project=source),document,c):raise ValueError('canary_release_source_mismatch')
            releases.append(dict(release))
        if len(releases)!=len(ids):raise ValueError('canary_skills_not_all_published')
        rows['creator_skill_versions']=releases
        profile=c.execute('SELECT * FROM creator_profiles WHERE id=?',(profile_id,)).fetchone()
        if not profile:raise ValueError('canary_profile_missing')
        rows['creator_profiles']=[dict(profile)]
        history=c.execute('SELECT * FROM creator_profile_history WHERE id=? AND revision=?',(profile_id,profile['revision'])).fetchone()
        if not history:raise ValueError('canary_profile_revision_missing')
        rows['creator_profile_history']=[dict(history)]
        documents=[json.loads(r['document']) for r in releases];profile_document=json.loads(profile['document'])
        refs=[r for d in documents for r in d.get('resources',[])]+profile_document.get('asset_refs',[])
        wanted={r['sha256'] for r in refs if r.get('available') and r.get('sha256')}
        blobs=[]
        for fingerprint in sorted(wanted):
            row=c.execute('SELECT * FROM creator_skill_blobs WHERE sha256=?',(fingerprint,)).fetchone()
            if not row or hashlib.sha256(bytes(row['bytes'])).hexdigest()!=fingerprint:raise ValueError('canary_frozen_blob_missing')
            blobs.append(dict(row))
        if sum(len(row['bytes']) for row in blobs)>32*1024*1024:raise ValueError('canary_seed_too_large')
        rows['creator_skill_blobs']=blobs
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='creator_skill_source_outbox'").fetchone():
            rows['creator_skill_source_outbox']=[dict(r) for r in c.execute('SELECT * FROM creator_skill_source_outbox')
                if r['skill_id'] in ids and any(v['skill_id']==r['skill_id'] and v['version']==r['version'] for v in releases)]
        state=c.execute('SELECT * FROM workbench_settings_versions ORDER BY revision DESC LIMIT 1').fetchone()
        if not state:raise ValueError('canary_settings_missing')
        settings=json.loads(state['document'])
        if settings['runtime']!='codex':raise ValueError('canary_requires_native_codex')
        rows['workbench_settings_versions']=[dict(state)]
        article=c.execute('SELECT * FROM articles ORDER BY run_at DESC,id DESC LIMIT 1').fetchone()
        return {'schema_version':1,'rows':rows,'profile_id':profile_id,'profile_revision':profile['revision'],
                'settings_revision':settings['revision'],'blob_bytes':sum(len(x['bytes']) for x in blobs),
                'article_fallback':dict(article) if article else None}
