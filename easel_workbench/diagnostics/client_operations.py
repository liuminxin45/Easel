"""Authenticated, content-free operation phase logging; never a command port."""
import math
import re

PHASES=frozenset(('creating','checking','not_accepted','ready','failed','opened'))


def observe(value, *, trace):
    if not isinstance(value,dict) or set(value)-{'id','operation_id','flow_id','phase','elapsed_ms','code','client'}:
        raise ValueError('操作诊断格式无效')
    operation=value.get('operation_id');flow=value.get('flow_id');phase=value.get('phase')
    if not isinstance(operation,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',operation):raise ValueError('操作身份无效')
    if not isinstance(flow,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',flow):raise ValueError('流程身份无效')
    if phase not in PHASES:raise ValueError('操作阶段无效')
    elapsed=value.get('elapsed_ms',0);code=value.get('code','');client=value.get('client','browser')
    if type(elapsed) not in (float,int) or not math.isfinite(elapsed) or not 0<=elapsed<=604800000:raise ValueError('操作耗时无效')
    if not isinstance(code,str) or not re.fullmatch(r'[a-z0-9_]{0,64}',code):raise ValueError('诊断代码无效')
    if client not in ('browser','webview'):raise ValueError('客户端标识无效')
    from easel_workbench.runtime import server_logging as journal
    journal.emit('client_operation_phase',trace_id=trace,operation_ref=journal.reference(operation),resource_ref=journal.reference(flow),phase=phase,duration_ms=round(elapsed,3),error_type=code or None,webview=client=='webview')
    return {'ok':True}
