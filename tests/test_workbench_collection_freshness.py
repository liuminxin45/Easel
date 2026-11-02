"""A successful page query cannot turn an old collection into fresh data."""
import datetime as dt
from types import SimpleNamespace

from easel_workbench.runtime import native_api

NOW=dt.datetime.fromisoformat('2026-11-03T12:10:00+08:00').timestamp()
DAILY={'kind':'daily','times':['00:00','04:00','08:00','12:00','16:00','20:00']}
WEEKLY={'kind':'weekly','times':['18:30'],'weekdays':[4]}


def trends(monkeypatch, *, checked='2026-11-01T20:02:09+08:00', schedule=DAILY, heartbeat=None, outcome='completed', enabled=True):
    monkeypatch.setattr(native_api.time,'time',lambda:NOW)
    source={'id':'source','last_success_at':checked,'last_task':{'status':outcome,'finished_at':checked},
            'next_run_at':'2026-11-06T18:30:00+08:00' if schedule is WEEKLY else '2026-11-03T16:00:00+08:00'}
    status={'enabled':enabled,'sources':[source],'heartbeat':heartbeat or {'heartbeat':'2026-11-03T12:09:59+08:00','state':'watching'}}
    api=native_api.NativeApi.__new__(native_api.NativeApi)
    api._collection=lambda:SimpleNamespace(definitions=lambda:{'source':{'enabled':True,'label':'Source','schedule':schedule}},status=lambda:status)
    api.store=SimpleNamespace(article_day=lambda **_: {'items':[{'id':'original','title':'Original source','run_at':'2026-11-01T20:02:02+08:00','url':'https://example.test/article'}]})
    return api._trends(SimpleNamespace(query_params={}))['trends'][0]


def test_old_completed_source_is_stale_after_an_unperformed_due_slot(monkeypatch):
    group=trends(monkeypatch)
    assert group['stale'] and not group['ok'] and group['status']=='stale'
    assert group['error']['code']=='collection_overdue'
    assert group['fetched_at']=='2026-11-01T20:02:02+08:00'


def test_weekly_collection_is_not_overdue_before_its_actual_next_slot(monkeypatch):
    group=trends(monkeypatch,schedule=WEEKLY)
    assert group['ok'] and not group['stale'] and group['error'] is None


def test_successful_check_of_unchanged_items_does_not_rewrite_original_content_date(monkeypatch):
    group=trends(monkeypatch,checked='2026-11-03T12:05:00+08:00')
    assert group['ok'] and not group['stale']
    assert group['checked_at']=='2026-11-03T12:05:00+08:00'
    assert group['fetched_at']=='2026-11-01T20:02:02+08:00'


def test_a_live_process_with_blocked_business_cycle_does_not_report_fresh(monkeypatch):
    group=trends(monkeypatch,checked='2026-11-03T12:05:00+08:00',heartbeat={'heartbeat':'2026-11-03T12:09:59+08:00','state':'blocked'})
    assert group['stale'] and group['error']['code']=='collection_unavailable'


def test_failed_source_result_keeps_the_real_failure_ahead_of_the_age_warning(monkeypatch):
    group=trends(monkeypatch,outcome='failed')
    assert group['error']['code']=='collection_failed' and group['collection_status']=='failed'


def test_paused_collection_never_claims_that_old_results_are_current(monkeypatch):
    group=trends(monkeypatch,enabled=False)
    assert group['stale'] and group['error']['code']=='collection_paused'
