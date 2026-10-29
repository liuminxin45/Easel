"""Bounded compression for text responses; never cache private HTML or API data."""
import functools,gzip

def accepts_gzip(value):
    choices={}
    for part in value.split(','):
        name,*parameters=part.strip().lower().split(';');quality=1.0
        try:
            for parameter in parameters:
                key,separator,setting=parameter.strip().partition('=')
                if key=='q' and separator:quality=float(setting)
            choices[name]=quality if 0<=quality<=1 else 0
        except ValueError:choices[name]=0
    return choices.get('gzip',choices.get('*',0))>0

@functools.lru_cache(maxsize=24)
def compressed_public(body):return gzip.compress(body,compresslevel=6,mtime=0)

def encode(body,headers,mime,*,public=False):
    text=mime.startswith('text/') or any(kind in mime for kind in ('javascript','json','svg+xml'))
    if len(body)>=1024 and text and accepts_gzip(headers.get('Accept-Encoding','')):
        packed=compressed_public(body) if public else gzip.compress(body,compresslevel=6,mtime=0)
        if len(packed)<len(body):return packed,{'Content-Encoding':'gzip','Vary':'Accept-Encoding'}
    return body,{'Vary':'Accept-Encoding'}
