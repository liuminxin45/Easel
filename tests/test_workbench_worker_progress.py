"""Progress describes observed outcomes, not merely an alive worker PID."""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from easel_workbench.runtime import local_worker,news_feedback
from easel_workbench.runtime.learning_worker import LearningWorker


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def test_feedback_error_survives_in_progress_then_real_success_clears_it(tmp_path):
    path=tmp_path/'feedback.json'
    failed=news_feedback.progress(path,'error',error=sqlite3.OperationalError('private details must not be logged'))
    assert failed['error_type']=='OperationalError' and 'last_success_at' not in failed
    assert 'private details' not in path.read_text(encoding='utf-8')
    during=news_feedback.progress(path,'working')
    assert during['error_type']=='OperationalError' and 'last_success_at' not in during
    success=news_feedback.progress(path,'idle',success=True)
    assert success['error_type'] is None and success['last_success_at']>=failed['last_error_at']


def test_local_error_is_not_counted_as_success_and_recovery_is_observed(tmp_path):
    worker=SimpleNamespace(state=tmp_path)
    local_worker.progress(worker,'error',error=sqlite3.OperationalError('no raw error'))
    failed=read(tmp_path/'heartbeat.json')
    assert failed['state']=='error' and failed['error_type']=='OperationalError'
    assert 'last_success_at' not in failed
    local_worker.progress(worker,'failed')
    assert 'last_success_at' not in read(tmp_path/'heartbeat.json')
    local_worker.progress(worker,'waiting',counts={'waiting_binding':1})
    success=read(tmp_path/'heartbeat.json')
    assert success['error_type'] is None and success['last_success_at']>=failed['last_error_at']


def test_learning_cycle_failure_remains_error_until_actual_success(tmp_path):
    def broken():raise sqlite3.OperationalError('sensitive DB details')
    service=SimpleNamespace(state=tmp_path,queue_index_refresh=broken)
    worker=LearningWorker(service)
    with pytest.raises(sqlite3.OperationalError):worker.tick()
    failure=read(tmp_path/'heartbeat.json')
    assert failure['state']=='error' and failure['error_type']=='OperationalError'
    assert 'last_success_at' not in failure
    service.queue_index_refresh=lambda:None;service.claim_task=lambda *args,**kwargs:None
    assert worker.tick() is None
    recovered=read(tmp_path/'heartbeat.json')
    assert recovered['state']=='idle' and recovered['error_type'] is None
    assert recovered['last_success_at']>=failure['last_error_at']


def test_learning_model_phase_and_blocked_result_do_not_claim_success(tmp_path):
    task={'id':'review-one','kind':'production_review','lease_token':'lease'}
    finished=[]
    service=SimpleNamespace(state=tmp_path,queue_index_refresh=lambda:None,
                            claim_task=lambda *args,**kwargs:task,
                            finish_task=lambda *args:finished.append(args))
    def review(*args):
        during=read(tmp_path/'heartbeat.json')
        assert during['state']=='working' and during['phase']=='production_review'
        assert 'last_success_at' not in during
        return {'status':'blocked','error':'original receipt unknown; do not replay'}
    worker=LearningWorker(service,production_review=review)
    assert worker.tick()['result']['status']=='blocked'
    after=read(tmp_path/'heartbeat.json')
    assert after['state']=='blocked' and 'last_success_at' not in after
    assert len(finished)==1
