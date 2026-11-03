"""Safe independent projection of the application's bounded index metadata."""
from .policy import number


def project(value):
    if not isinstance(value,dict):return {'status':'unavailable','performance_degraded':False}
    state=value.get('status')
    if state not in ('ready','building','stale','error','unavailable'):state='unavailable'
    output={'status':state,'building':value.get('building') is True}
    raw=value.get('counts')
    if isinstance(raw,dict):
        output['counts']={key:raw[key] for key in ('nodes','projects') if type(raw.get(key)) is int and number(raw[key]) and raw[key]<=2**53}
    for name in ('refreshed_at','last_list_ms','last_list_bytes'):
        if number(value.get(name)) and value[name]<=2**53:output[name]=value[name]
    output['performance_degraded']=output.get('last_list_ms',0)>1000 or output.get('last_list_bytes',0)>100000
    if state=='ready':
        if output['building']:output['status']='building'
        elif set(output.get('counts',{}))!={'nodes','projects'} or not output.get('refreshed_at'):output['status']='unavailable'
    return output
