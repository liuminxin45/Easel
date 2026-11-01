"""Durable retry delays for exact supervisor-owned roles, never process control."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import re

from .runtime.feedback_ledger import atomic


ROLES=frozenset(('server','worker','publisher','feedback','collector','learning','local'))


def _number(value):
    return type(value) in (int,float) and math.isfinite(value) and value>=0


class RoleBackoff:
    def __init__(self,path,*,base_delay=3,max_delay=120,stable_seconds=60):
        if not all(_number(v) and v>0 for v in (base_delay,max_delay,stable_seconds)) or base_delay>max_delay:
            raise ValueError('Invalid role backoff settings')
        self.path=Path(path);self.base_delay=base_delay;self.max_delay=max_delay;self.stable_seconds=stable_seconds
        self.state={'schema':1,'entries':{}}
        if self.path.exists():
            try:
                value=json.loads(self.path.read_text(encoding='utf-8'))
                self._validate(value)
            except (OSError,UnicodeError,ValueError,TypeError,KeyError) as error:
                raise ValueError('Role backoff state is invalid; original file retained') from error
            self.state=value

    @staticmethod
    def _key(release,role):
        if not isinstance(release,str) or not re.fullmatch(r'workbench-[A-Za-z0-9_-]+',release) or role not in ROLES:
            raise ValueError('Invalid role backoff identity')
        return release+':'+role

    @staticmethod
    def _empty():
        return {'pid':None,'failures':0,'last_spawn':None,'last_event':0,'next_attempt':0,'stable':False,'error_type':None}

    @classmethod
    def _validate(cls,value):
        if not isinstance(value,dict) or set(value)!={'schema','entries'} or type(value['schema']) is not int or value['schema']!=1 or not isinstance(value['entries'],dict) or not value['entries']:
            raise ValueError('Invalid backoff document')
        for key,entry in value['entries'].items():
            if not isinstance(key,str) or ':' not in key:raise ValueError('Invalid backoff key')
            cls._key(*key.rsplit(':',1))
            if not isinstance(entry,dict) or set(entry)!=set(cls._empty()):raise ValueError('Invalid backoff entry')
            if entry['pid'] is not None and (type(entry['pid']) is not int or entry['pid']<=0):raise ValueError('Invalid backoff pid')
            if type(entry['failures']) is not int or not 0<=entry['failures']<=1_000_000:raise ValueError('Invalid backoff failures')
            if not all(_number(entry[k]) for k in ('last_event','next_attempt')):raise ValueError('Invalid backoff timestamp')
            if entry['last_spawn'] is not None and not _number(entry['last_spawn']):raise ValueError('Invalid spawn timestamp')
            if type(entry['stable']) is not bool:raise ValueError('Invalid stable marker')
            if entry['error_type'] is not None and (not isinstance(entry['error_type'],str) or not 0<len(entry['error_type'])<=120):raise ValueError('Invalid error type')
            if entry['pid'] is not None and (entry['last_spawn'] is None or entry['next_attempt']!=0):raise ValueError('Invalid running entry')
            if entry['last_spawn'] is not None and entry['last_spawn']>entry['last_event']:raise ValueError('Spawn timestamp is in the future')
            if entry['pid'] is None and (not entry['failures'] or entry['stable'] or entry['next_attempt']<=entry['last_event'] or entry['error_type'] is None):raise ValueError('Invalid waiting retry entry')
            if entry['pid'] is not None and (entry['error_type'] is not None or entry['stable'] and entry['failures']):raise ValueError('Invalid live retry entry')

    def _entry(self,release,role):
        key=self._key(release,role)
        return key,copy.deepcopy(self.state['entries'].get(key,self._empty()))

    def _save(self,key,entry,now):
        if not _number(now) or now<entry['last_event']:raise ValueError('Role backoff clock moved backwards')
        entry['last_event']=now
        updated=copy.deepcopy(self.state);updated['entries'][key]=entry
        self._validate(updated);atomic(self.path,updated);self.state=updated

    def ready(self,release,role,now):
        _,entry=self._entry(release,role)
        if not _number(now) or now<entry['last_event']:return False
        return entry['pid'] is None and now>=entry['next_attempt']

    def started(self,release,role,pid,now):
        key,entry=self._entry(release,role)
        if not self.ready(release,role,now):raise ValueError('Role retry is not ready')
        entry.update(pid=pid,last_spawn=now,next_attempt=0,stable=False,error_type=None)
        self._save(key,entry,now)

    def adopted(self,release,role,pid,created_at,now):
        key,entry=self._entry(release,role)
        if not _number(created_at) or not _number(now) or created_at>now:raise ValueError('Invalid adopted process creation')
        if entry['pid']==pid and entry['last_spawn']==created_at:
            self.alive(release,role,pid,now);return
        stable=now-created_at>=self.stable_seconds
        entry.update(pid=pid,last_spawn=created_at,next_attempt=0,stable=stable,error_type=None)
        if stable:entry['failures']=0
        self._save(key,entry,now)

    def alive(self,release,role,pid,now):
        key,entry=self._entry(release,role)
        if entry['pid']!=pid:raise ValueError('Observed role identity changed')
        if not _number(now) or now<entry['last_event']:return
        if not entry['stable'] and now-entry['last_spawn']>=self.stable_seconds:
            entry.update(stable=True,failures=0,error_type=None);self._save(key,entry,now)

    def _failed(self,key,entry,now,error_type):
        failures=min(entry['failures']+1,1_000_000)
        # Bound the exponent before computing it, even for a long crash storm.
        delay=min(self.max_delay,self.base_delay*(2**min(failures-1,20)))
        entry.update(pid=None,failures=failures,next_attempt=now+delay,stable=False,error_type=error_type)
        self._save(key,entry,now)

    def exited(self,release,role,pid,now):
        key,entry=self._entry(release,role)
        if entry['pid']!=pid:raise ValueError('Exited role identity changed')
        self._failed(key,entry,now,'process_exited')

    def missing(self,release,role,now):
        key,entry=self._entry(release,role)
        if entry['pid'] is not None:self._failed(key,entry,now,'owned_process_missing')

    def spawn_failed(self,release,role,now,error_type):
        key,entry=self._entry(release,role)
        if not self.ready(release,role,now):raise ValueError('Role retry is not ready')
        self._failed(key,entry,now,error_type)

    def snapshot(self,release):
        return {role:{k:v for k,v in self._entry(release,role)[1].items() if k in ('failures','next_attempt','error_type')}
                for role in ROLES if self._key(release,role) in self.state['entries']}
