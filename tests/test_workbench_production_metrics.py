"""Exact links, native analytics authority and read-only daily recovery."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path

import pytest

from easel_workbench.features.production_insights.metrics import Service, canonical_url
from easel_workbench.runtime.desk import Store
from easel_workbench.runtime.toolbox_store import Toolbox

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 6, 10, 0, tzinfo=CST)
URL = "https://mp.weixin.qq.com/s/ExactArticle"


@pytest.fixture
def box(tmp_path):
    box = Toolbox(Store(tmp_path / "data/desk.sqlite"), tmp_path)
    with box.store.connect() as c:
        for suffix in ("one", "two"):
            c.execute("INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)", ("work-" + suffix, None, "同名标题", "material", "old", "old"))
            c.execute("INSERT INTO toolbox_jobs(id,work_id,kind,text,signature,status,created_at) VALUES(?,?,?,?,?,?,?)",
                      ("version-" + suffix, "work-" + suffix, "create", "original", "sig", "completed", "old"))
            receipt = {"work_id": "work-" + suffix, "version_id": "version-" + suffix, "profile_id": "oil-pig", "skill_id": "oil-pig-poster", "whole_ready": True, "status": "completed"}
            c.execute("INSERT INTO toolbox_meta VALUES(?,?)", ("native-review:version-" + suffix, json.dumps({"receipt": receipt})))
    return box


def bind(service, suffix="one", **extra):
    return service.bind("work-" + suffix, "version-" + suffix, {"operation_id": "bind-" + suffix, "url": URL, **extra})


@pytest.mark.parametrize("url", ["http://mp.weixin.qq.com/s/a", "https://mp.weixin.qq.com.evil/s/a", "https://mp.weixin.qq.com:443/s/a", "https://user@mp.weixin.qq.com/s/a", "https://mp.weixin.qq.com/", "https://example.org", "https://mp.weixin.qq.com/s?mid=1&idx=2"])
def test_only_real_wechat_article_links(url):
    with pytest.raises(ValueError):
        canonical_url(url)


def test_url_identity_keeps_article_not_tracking_parameters():
    assert canonical_url(URL + "?scene=1#rd") == URL
    assert canonical_url("https://mp.weixin.qq.com/s?__biz=ABC%3D%3D&mid=123&idx=1&sn=signature&scene=1") == "https://mp.weixin.qq.com/s?__biz=ABC%3D%3D&mid=123&idx=1"


def test_binding_is_exact_idempotent_and_uses_original_publish_log(box):
    service = Service(box, clock=lambda: NOW)
    one = bind(service)
    two = bind(service)
    assert one["binding"] == two["binding"]
    log = json.loads((box.root / "outputs/_analytics/publish-log.json").read_text(encoding="utf-8"))
    assert len(log["entries"]) == 1
    assert log["entries"][0]["skill_source"] == "oil-pig-poster"
    assert log["entries"][0]["initial_metrics"]["views"] is None
    assert one["binding"]["published_at"] is None
    with pytest.raises(ValueError, match="已有不同"):
        bind(service, "two")
    with pytest.raises(ValueError, match="不同请求"):
        service.bind("work-one", "version-one", {"operation_id": "bind-one", "url": URL + "Other"})


def test_binding_log_projection_recovers_without_duplicate_event(box, monkeypatch):
    service = Service(box, clock=lambda: NOW)
    original = service._finish
    monkeypatch.setattr(service, "_finish", lambda *args: (_ for _ in ()).throw(OSError("lost database acknowledgement")))
    with pytest.raises(OSError):
        bind(service)
    monkeypatch.setattr(service, "_finish", original)
    assert bind(service)["binding"]["log_id"] == 1
    assert len(json.loads((box.root / "outputs/_analytics/publish-log.json").read_text(encoding="utf-8"))["entries"]) == 1


def test_missing_login_preserves_no_data_and_daily_does_not_repeat(box):
    calls = []
    service = Service(box, fetch=lambda: calls.append(True), connected=lambda: False, clock=lambda: NOW)
    bind(service)
    assert service.run_due_once(NOW.replace(hour=8)) is None
    result = service.run_due_once(NOW)
    assert result["status"] == "blocked" and result["outcome"] == "login_required"
    assert service.run_due_once(NOW) == result
    assert not calls
    assert service.view("work-one", "version-one")["observations"] == []
    assert not (box.root / "outputs/_analytics/snapshots").exists()


def test_measured_zero_uses_original_tracker_and_never_matches_a_title(box):
    calls = []
    data = {"loggedIn": True, "followers": 0, "coverage": {"complete": False, "returned": 2}, "articles": [
        {"title": "同名标题", "url": URL + "Other", "structured_metrics": {"read_uv": 999}},
        {"title": "改过的真实标题", "url": URL, "structured_metrics": {"read_uv": 0, "read_pv": None, "likes": 0, "comments": None, "shares": 3}},
    ]}
    def fetch():
        calls.append(True)
        return data
    service = Service(box, fetch=fetch, connected=lambda: True, clock=lambda: NOW)
    bind(service, published_at=(NOW - timedelta(hours=12)).isoformat())
    result = service.run_due_once(NOW)
    assert result["status"] == "completed" and result["matched"] == 1
    service.run_due_once(NOW)
    assert len(calls) == 1
    observation = service.view("work-one", "version-one")["observations"][0]
    assert observation["metrics"]["read_uv"] == 0
    assert observation["views"] is None and observation["comments"] is None
    assert observation["likes"] == 0 and observation["age_hours"] == 12
    snapshot = json.loads((box.root / "outputs/_analytics/snapshots/oil-pig/wechat-oa/2026-11-06.json").read_text(encoding="utf-8"))
    assert snapshot["account_metrics"]["followers"] == 0
    assert snapshot["post_snapshots"][0]["binding_id"] == observation["binding_id"]
    assert "metrics" not in service.operation_result(result["operation_id"])


def test_no_current_measurement_never_fills_from_cached_result(box):
    service = Service(box, fetch=lambda: {"loggedIn": True, "notes": [{"title": "同名标题", "url": URL + "Other", "structured_metrics": {"read_uv": 22}}]}, connected=lambda: True, clock=lambda: NOW)
    bind(service)
    result = service.run_due_once(NOW)
    assert result["outcome"] == "no_data" and result["matched"] == 0
    assert not service.view("work-one", "version-one")["observations"]


def test_process_loss_or_transport_unknown_is_not_automatically_resent(box):
    calls = []
    def fetch():
        calls.append(True)
        raise ConnectionError("read accepted; transport lost")
    service = Service(box, fetch=fetch, connected=lambda: True, clock=lambda: NOW)
    bind(service)
    result = service.sync({"operation_id": "refresh-one"})
    assert result["status"] == "unknown"
    assert Service(box, fetch=fetch, clock=lambda: NOW).sync({"operation_id": "refresh-one"})["status"] == "unknown"
    assert len(calls) == 1


def test_orphaned_running_command_is_closed_unknown_without_blocking_future_deploy(box):
    calls = []
    service = Service(box, fetch=lambda: calls.append(True), connected=lambda: True, clock=lambda: NOW)
    bind(service)
    service._command("lost-request", '{"kind":"sync"}', "sync", {"started_at": NOW.isoformat()}, NOW)
    with box.store.connect() as c:
        c.execute("UPDATE production_metric_commands SET state='running' WHERE id='lost-request'")
    result = Service(box, fetch=service.fetch).sync({"operation_id": "lost-request"})
    assert result["status"] == "unknown"
    assert service.operation_result("lost-request")["status"] == "unknown"
    assert not calls


def test_native_read_timeout_is_unknown_not_lock_busy_and_is_not_resent(box):
    calls = []
    def fetch():
        calls.append(True)
        raise TimeoutError("native owner timed out after cleanup")
    service = Service(box, fetch=fetch, connected=lambda: True, clock=lambda: NOW)
    bind(service)
    first = service.sync({"operation_id": "read-timeout"})
    assert first["status"] == "unknown" and first["outcome"] == "read_timeout"
    assert Service(box, fetch=fetch).sync({"operation_id": "read-timeout"}) == first
    assert len(calls) == 1
    assert service.view("work-one", "version-one")["observations"] == []


def test_startup_reconciles_all_manual_and_daily_orphans_without_fetch(box):
    calls = []
    service = Service(box, fetch=lambda: calls.append(True), connected=lambda: True, clock=lambda: NOW)
    for operation in ("manual-old", "wechat-daily-2026-11-05"):
        service._command(operation, '{"kind":"sync"}', "sync", {"started_at": "2026-11-05T10:00:00+08:00"}, NOW)
    with box.store.connect() as c:
        c.execute("UPDATE production_metric_commands SET state='running' WHERE id='manual-old'")
    service._command("bind-pending", "binding", "bind", {"work_id": "work-one"}, NOW)
    recovered = service.recover_inflight()
    assert recovered["status"] == "completed" and recovered["count"] == 2
    assert set(recovered["recovered"]) == {"manual-old", "wechat-daily-2026-11-05"}
    assert service.operation_result("manual-old")["status"] == "unknown"
    assert service.operation_result("manual-old")["started_at"] == "2026-11-05T10:00:00+08:00"
    assert service.operation_result("bind-pending")["status"] == "reserved"
    assert service.recover_inflight()["count"] == 0
    assert not calls


def test_startup_cannot_close_a_read_still_owned_by_an_existing_process(box):
    from easel_workbench.runtime.feedback_ledger import locked
    service = Service(box, clock=lambda: NOW)
    service._command("active-read", '{"kind":"sync"}', "sync", {"started_at": NOW.isoformat()}, NOW)
    with box.store.connect() as c:
        c.execute("UPDATE production_metric_commands SET state='running' WHERE id='active-read'")
    with locked(box.root / "data/production-insights/metrics-sync.lock"):
        result = service.recover_inflight()
        assert result == {"status": "busy", "recovered": [], "count": 0}
        assert service.operation_result("active-read")["status"] == "running"
    assert service.recover_inflight()["count"] == 1


def test_signed_original_url_is_retained_separately_from_article_identity(box):
    service = Service(box, clock=lambda: NOW)
    original = "https://mp.weixin.qq.com/s?__biz=ABC%3D%3D&mid=123&idx=1&sn=real-signature&scene=1#rd"
    result = service.bind("work-one", "version-one", {"operation_id": "bind-real", "url": original})
    assert result["binding"]["url"] == original
    assert "sn=" not in result["binding"]["identity_url"]
    log = json.loads((box.root / "outputs/_analytics/publish-log.json").read_text(encoding="utf-8"))
    assert log["entries"][0]["url"] == original


def test_client_cannot_forge_collection_time(box):
    with pytest.raises(ValueError, match="参数"):
        Service(box).sync({"operation_id": "spoof-time", "now": "2001-01-01T09:00:00+08:00"})


def test_incomplete_product_cannot_be_bound(box):
    service = Service(box)
    with box.store.connect() as c:
        c.execute("UPDATE toolbox_jobs SET status='partial' WHERE id='version-one'")
    with pytest.raises(ValueError, match="完整交付"):
        bind(service)


@pytest.fixture
def parser():
    path = Path(__file__).resolve().parents[1] / "skills/shared/scripts/weixin_mp_stats.py"
    spec = importlib.util.spec_from_file_location("weixin_metrics_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parser_keeps_zero_missing_and_pv_uv_separate(parser):
    raw = json.dumps({"publish_page": {"total_count": 1, "publish_list": [{"publish_info": {"appmsgex": [{"title": "same", "link": URL, "read_num": 0}]}}]}})
    result = {}
    parser._parse_publish(raw, result)
    note = result["articles"][0]
    assert note["structured_metrics"]["read_num"] == 0
    assert note["structured_metrics"]["likes"] is None and result["likes"] is None
    assert result["reads"] == 0
    parser._parse_analytics({"article_list": json.dumps({"article_list": [
        {"appmsg_info": {"title": "same", "link": URL + "Other", "total_read_uv": 998}},
        {"appmsg_info": {"title": "newtitle", "link": URL, "total_read_uv": 0, "total_read_pv": 3, "share_uv": 2}},
    ]})}, result)
    metrics = result["articles"][0]["structured_metrics"]
    assert metrics["read_uv"] == 0 and metrics["read_pv"] == 3 and metrics["share_uv"] == 2 and metrics["shares"] is None


def test_parser_does_not_join_duplicate_titles_without_identity(parser):
    result = {"notes": [{"title": "same", "stat": "original"}]}
    parser._parse_analytics({"article_list": json.dumps({"article_list": [{"title": "same", "total_read_uv": 99}]})}, result)
    assert result["notes"][0]["stat"] == "original"


def test_recent_article_coverage_counts_publish_groups_not_child_articles(parser):
    def page(begin):
        return json.dumps({"publish_page": {"total_count": 6, "publish_list": [{"publish_info": {"appmsgex": [{"title": str(i), "link": URL + str(begin) + str(i)} for i in range(5)]}}]}})
    result = {}
    parser._parse_publish_pages([page(0), page(1)], result)
    assert result["coverage"]["groups_returned"] == 2
    assert result["coverage"]["complete"] is False
    assert len(result["articles"]) == 10


def test_tendency_never_replaces_measured_zero_with_older_publish_reads(parser):
    result = {"reads": 123}
    parser._parse_analytics({"tendency": json.dumps({"all_article_stat_tendency": {"list": [{"date": 20261106, "scene": 9999, "read_uv": 0, "share_uv": 0}]}})}, result)
    assert result["reads"] == 0
    assert result["period_metrics"]["day"][1] == {"label": "分享人数", "value": 0, "vs": ""}
    assert parser._tendency_metrics([], 7)[0]["value"] is None
