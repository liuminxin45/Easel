"""Retired automatic extension scanning; manual checks and delivery stay separate."""
from __future__ import annotations
import json
from fastapi.responses import JSONResponse,Response
from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.toolbox_store import pack

ACCOUNTS_PATH='/toolbox?section=distribution&pane=connections'
ACCOUNTS_URL='/native/?path=%2Ftoolbox%3Fsection%3Ddistribution%26pane%3Dconnections'
RETIRED={'error':'feature_retired','feature':'automatic_account_check','retired':True,
         'message':'旧自动账号检测已退役，请在账号页连接平台并核对身份。','accounts_path':ACCOUNTS_PATH}


def mount(distribution, origin=None):
    """Idempotently fence existing scheduling/relay records; never create checks.

    Historical check results, credentials, connection identities, approvals and
    dispatched check/outbox identities remain unchanged. Only queued helper work
    is retired; a late original CheckService report remains independently valid.
    """
    counts={'monitor':0,'relay_state':0,'leases':0,'queued_tasks':0}
    with distribution.store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        tables={row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        now=stamp()
        for table,label in [('distribution_check_monitor_state','monitor'),('distribution_check_relay_state','relay_state')]:
            if table not in tables:continue
            row=c.execute("SELECT document FROM "+table+" WHERE id='global'").fetchone()
            if not row:continue
            doc=json.loads(row[0])
            if doc.get('retired_at') and doc.get('enabled') is False:continue
            doc.update(enabled=False,retired_at=doc.get('retired_at') or now,next_check_at=None,next_launch_at=None)
            if label=='monitor':
                doc.update(phase='retired',updated_at=now,
                    settings_revision=doc.get('settings_revision',0)+1,
                    authorization_revision=doc.get('authorization_revision',0)+1)
            c.execute("UPDATE "+table+" SET document=? WHERE id='global'",(pack(doc),));counts[label]+=1
        if 'distribution_check_relay_leases' in tables:
            for ident,raw in c.execute('SELECT id,document FROM distribution_check_relay_leases').fetchall():
                doc=json.loads(raw)
                if doc.get('phase') in ('launch_requested','connected'):
                    doc.update(phase='revoked',revoked_at=now,retirement_reason='feature_retired')
                    c.execute('UPDATE distribution_check_relay_leases SET document=? WHERE id=?',(pack(doc),ident));counts['leases']+=1
        if 'distribution_check_relay_outbox' in tables:
            for ident,raw in c.execute('SELECT check_id,document FROM distribution_check_relay_outbox').fetchall():
                doc=json.loads(raw)
                if doc.get('status')=='queued':
                    doc.update(status='cancelled',finished_at=now,code='feature_retired')
                    c.execute('UPDATE distribution_check_relay_outbox SET document=? WHERE check_id=?',(pack(doc),ident));counts['queued_tasks']+=1
    return {'retired':True,'changes':counts}


def reply():
    return JSONResponse(RETIRED,status_code=410,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})


async def public(distribution,path,request,same,raw):
    if path=='/distribution/auto-check':
        if request.method not in ('GET','HEAD'):
            return JSONResponse({'error':'method rejected'},status_code=405,headers={'Cache-Control':'no-store'})
        # An explicit empty fragment prevents the old relay/ticket fragment from
        # being inherited by the new account page during the HTTP redirect.
        return Response(status_code=303,headers={'Location':ACCOUNTS_URL+'#','Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
    if path=='/api/distribution/auto-relay':return reply()
    return None


async def handle(distribution,path,request,value=None):
    return reply() if path=='/api/distribution/auto-check' else None
