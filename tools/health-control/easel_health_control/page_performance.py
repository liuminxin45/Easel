"""Bounded private performance-log summary and independent memory sample."""
from pathlib import Path
from collections import defaultdict
import ctypes
import html
import json
import os
import re
import time


def memory():
    if os.name!='nt':return {'status':'unavailable'}
    class MEMORY(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total',ctypes.c_ulonglong),('available',ctypes.c_ulonglong),('total_page',ctypes.c_ulonglong),('available_page',ctypes.c_ulonglong),('total_virtual',ctypes.c_ulonglong),('available_virtual',ctypes.c_ulonglong),('available_extended',ctypes.c_ulonglong)]
    value=MEMORY();value.length=ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):return {'status':'unavailable'}
    result={'status':'pressure' if value.available<1024**3 else 'normal','available_bytes':value.available,'total_bytes':value.total,'memory_load_percent':value.load,'sampled_at':time.time()}
    class PERFORMANCE(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('commit_total',ctypes.c_size_t),('commit_limit',ctypes.c_size_t),('commit_peak',ctypes.c_size_t),('physical_total',ctypes.c_size_t),('physical_available',ctypes.c_size_t),('system_cache',ctypes.c_size_t),('kernel_total',ctypes.c_size_t),('kernel_paged',ctypes.c_size_t),('kernel_nonpaged',ctypes.c_size_t),('page_size',ctypes.c_size_t),('handle_count',ctypes.c_ulong),('process_count',ctypes.c_ulong),('thread_count',ctypes.c_ulong)]
    info=PERFORMANCE();info.cb=ctypes.sizeof(info)
    if ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info),info.cb):
        result.update(commit_bytes=info.commit_total*info.page_size,commit_limit_bytes=info.commit_limit*info.page_size)
    return result


def sample_memory(store,*,clock=time.time,reader=memory):
    old=store.read('page-memory.json',{})
    if isinstance(old,dict) and isinstance(old.get('sampled_at'),(int,float)) and 0<=clock()-old['sampled_at']<60:return old
    try:value=reader()
    except Exception:value={'status':'unavailable'}
    value['sampled_at']=clock();store.write('page-memory.json',value);return value


def summarize(directory,*,now=None,max_read=4*1024*1024):
    now=time.time() if now is None else now;directory=Path(directory);stats=defaultdict(lambda:[0]*9);slow=[];read=0;partial=False;dropped=0;server_dropped=0;write_failures=0
    if not directory.is_dir() or directory.is_symlink():return {'status':'unavailable','window_hours':24,'histograms':[],'slow':[]}
    files=sorted((p for p in directory.glob('performance-*.jsonl') if not p.is_symlink() and re.fullmatch(r'performance-\d{10}-\d+\.jsonl',p.name)),key=lambda p:p.name,reverse=True)
    for path in files:
        try:
            if path.stat().st_mtime<now-86400:continue
            size=path.stat().st_size;amount=min(size,max_read-read)
            if amount<=0:partial=True;break
            with path.open('rb') as stream:stream.seek(size-amount);raw=stream.read(amount)
            read+=amount;lines=raw.splitlines();lines=lines[1:] if amount<size else lines
            if amount<size:partial=True
            for line in reversed(lines):
                try:value=json.loads(line)
                except (ValueError,UnicodeError):continue
                if not isinstance(value,dict) or type(value.get('at')) not in (int,float) or not 0<=now-value['at']<=86400:continue
                dropped+=value.get('dropped',0) if type(value.get('dropped')) is int else 0
                server_dropped=max(server_dropped,value.get('server_dropped',0) if type(value.get('server_dropped')) is int else 0)
                write_failures=max(write_failures,value.get('write_failures',0) if type(value.get('write_failures')) is int else 0)
                for item in value.get('events',[])[:20]:
                    if not isinstance(item,dict):continue
                    key=(item.get('metric'),item.get('screen'),item.get('platform'))
                    if item.get('kind')=='summary' and isinstance(item.get('buckets'),list) and len(item['buckets'])==9:
                        for i,n in enumerate(item['buckets']):
                            if type(n) is int and 0<=n<=10000:stats[key][i]+=n
                    elif item.get('kind')=='slow' and len(slow)<20:
                        slow.append({'received_at':value['at'],**{k:item[k] for k in ('at','metric','screen','platform','duration_ms','phases_ms','outcome','hidden','release','request_group','status','trace') if k in item}})
        except OSError:partial=True
    return {'status':'partial' if partial else 'available','window_hours':24,'bytes_read':read,'bucket_upper_ms':[250,500,1000,2000,3000,5000,10000,30000,None],'dropped_reported':dropped,'server_dropped_max':server_dropped,'write_failures_max':write_failures,
            'histograms':[{'metric':key[0],'screen':key[1],'platform':key[2],'buckets':value} for key,value in sorted(stats.items(),key=lambda x:str(x[0]))], 'slow':slow}


def render(value,resource):
    value=value if isinstance(value,dict) else {};resource=resource if isinstance(resource,dict) else {}
    esc=lambda v:html.escape(str(v))
    out='<h2>页面性能（最近24小时）</h2>'
    if value.get('status')=='unavailable':out+='<p>性能日志暂不可用。</p>'
    else:
        if value.get('status')=='partial':out+='<p>日志较多，本次只读取了有限尾部，统计不完整。</p>'
        out+='<p>耗时区间上限：250、500、1000、2000、3000、5000、10000、30000 毫秒及以上。</p><table><thead><tr><th>阶段</th><th>页面</th><th>设备</th><th>次数</th><th>区间计数</th></tr></thead><tbody>'
        for row in value.get('histograms',[])[:100]:
            bins=row.get('buckets',[]);out+='<tr><td>'+esc(row.get('metric',''))+'</td><td>'+esc(row.get('screen',''))+'</td><td>'+esc(row.get('platform',''))+'</td><td>'+esc(sum(bins))+'</td><td>'+esc(' / '.join(map(str,bins)))+'</td></tr>'
        out+='</tbody></table><p>慢例：'+esc(len(value.get('slow',[])))+'；客户端报告丢弃：'+esc(value.get('dropped_reported',0))+'；服务端丢弃累计最大值：'+esc(value.get('server_dropped_max',0))+'。</p>'
    if type(resource.get('available_bytes')) is int:out+='<p>服务器可用内存：'+esc(round(resource['available_bytes']/1024**3,2))+' GiB；状态：'+esc(resource.get('status','unknown'))+'。</p>'
    else:out+='<p>服务器内存采样暂不可用。</p>'
    return out
