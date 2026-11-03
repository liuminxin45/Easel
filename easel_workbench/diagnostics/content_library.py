"""Read-only content-library index health, without materializing its catalog."""
import math


STATUSES=frozenset(('ready','building','stale','error','unavailable'))


def numeric(value):
    return type(value) in (int,float) and math.isfinite(value) and 0<=value<=2**53


def project(value):
    if not isinstance(value,dict):return {'status':'unavailable','performance_degraded':False}
    state=value.get('status') if value.get('status') in STATUSES else 'unavailable'
    result={'status':state,'building':value.get('building') is True}
    counts=value.get('counts')
    if isinstance(counts,dict):
        result['counts']={key:counts[key] for key in ('nodes','projects') if type(counts.get(key)) is int and 0<=counts[key]<=2**53}
    for key in ('refreshed_at','last_list_ms','last_list_bytes'):
        if numeric(value.get(key)):result[key]=value[key]
    result['performance_degraded']=result.get('last_list_ms',0)>1000 or result.get('last_list_bytes',0)>100000
    if state=='ready':
        if result['building']:result['status']='building'
        elif set(result.get('counts',{}))!={'nodes','projects'} or not result.get('refreshed_at'):
            result['status']='unavailable'
    return result


def snapshot(root,*,reader=None):
    try:
        if reader is None:
            # Import the pure metadata reader only. In particular, never call
            # ensure/refresh/list or construct the native library from a probe.
            from easel_workbench.features.works.library_index import health
            reader=health
        return project(reader(root))
    except Exception:
        # An unavailable optional index must not disable nonce/process probes.
        # No exception text, filename, document or file reference leaves here.
        return {'status':'unavailable','performance_degraded':False}
