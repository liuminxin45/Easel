"""Revocable five-minute, exact-target HTTP download capabilities for native savers."""
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlencode, urlsplit, unquote
from .auth_totp import token_hash
from easel_workbench.contracts.media_paths import is_host_media_protocol

TTL = 300

def target(value):
    if not isinstance(value,str) or len(value)>4096 or re.search(r'[\\\x00-\x1f]',value):raise ValueError('Invalid download target')
    url=urlsplit(value)
    if url.scheme or url.netloc or url.fragment or url.query not in ('','download=1'):raise ValueError('Invalid download target')
    path=unquote(url.path)
    if re.search(r'[\\\x00-\x1f]',path) or any(part in ('.','..','') for part in path[1:].split('/')):raise ValueError('Invalid download path')
    allowed=(re.fullmatch(r'/api/files/[A-Za-z0-9_-]+',path)
             or re.fullmatch(r'/api/chat/products/[A-Za-z0-9_-]+/files/[a-f0-9]{64}',path)
             or re.fullmatch(r'/api/works/[A-Za-z0-9_-]+/versions/[A-Za-z0-9_-]+/download',path)
             or path.startswith('/api/media/') and not is_host_media_protocol(path))
    if not allowed:raise ValueError('Unsupported download target')
    return value

def signature(session,reference,expires,path,name):
    raw=json.dumps(['download-v1',reference,expires,path,name],ensure_ascii=False,separators=(',',':')).encode()
    return hmac.new(session['csrf'].encode(),raw,hashlib.sha256).hexdigest()

def issue(session,token,path,name):
    target(path)
    if not isinstance(name,str) or not name or len(name)>255 or re.search(r'[\\/\x00-\x1f]',name):raise ValueError('Invalid download filename')
    expires=min(int(time.time())+TTL,int(session['until']));reference=token_hash(token)
    return '/media/downloads?'+urlencode({'target':path,'name':name,'session':reference,'expires':expires,'signature':signature(session,reference,expires,path,name)})

def authorize(auth,query):
    if set(query)!={'target','name','session','expires','signature'} or any(len(query.getlist(k))!=1 for k in query):return None
    reference,expires,proof=query['session'],query['expires'],query['signature']
    if not re.fullmatch('[a-f0-9]{64}',reference) or not re.fullmatch('[a-f0-9]{64}',proof) or not re.fullmatch('[0-9]{1,11}',expires):return None
    expires=int(expires);now=time.time()
    if not now<expires<=now+TTL:return None
    try:target(query['target'])
    except ValueError:return None
    with auth.lock:
        session=auth.data['sessions'].get(reference)
        if not session or session['until']<=now or expires>session['until']:return None
        session=dict(session)
    return session if hmac.compare_digest(proof,signature(session,reference,expires,query['target'],query['name'])) else None
