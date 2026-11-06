"""Exact manual-publication links and a bounded read-only WeChat daily sync.

Publication events and measured counters stay in Easel's original publish-log
and data-tracker stores. SQLite contains links, command receipts and scheduling,
never a second collection of platform counters. Nothing here can publish.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from easel_workbench.contracts.values import ident, pack, text
from easel_workbench.paths import owned_output_path
from easel_workbench.runtime.feedback_ledger import locked

CST = timezone(timedelta(hours=8))
SKILLS = {"oil-pig-poster": "poster", "oil-pig-article": "article"}
DEFINITIONS = {"read_uv": "阅读人数（UV）", "read_pv": "阅读次数（PV）",
               "read_num": "后台阅读数（接口未声明 PV/UV）", "likes": "点赞次数",
               "comments": "评论数", "shares": "分享次数", "share_uv": "分享人数（UV）"}


def canonical_url(value):
    text(value, 2048, True)
    try:
        p = urlsplit(value.strip())
        if p.scheme != "https" or p.hostname != "mp.weixin.qq.com" or p.port is not None or p.username or p.password:
            raise ValueError()
        if re.fullmatch(r"/s/[A-Za-z0-9_-]{1,160}", p.path):
            return urlunsplit(("https", "mp.weixin.qq.com", p.path, "", ""))
        if p.path not in ("/s", "/s/"):
            raise ValueError()
        q = parse_qs(p.query, keep_blank_values=True)
        if not all(len(q.get(k, [])) == 1 and q[k][0] for k in ("__biz", "mid", "idx")):
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z0-9+/=_-]{1,160}", q["__biz"][0]) or not q["mid"][0].isdigit() or not q["idx"][0].isdigit():
            raise ValueError()
        return "https://mp.weixin.qq.com/s?" + urlencode([(k, q[k][0]) for k in ("__biz", "mid", "idx")])
    except (ValueError, TypeError):
        raise ValueError("请提供真实的微信公众号文章 HTTPS 链接，不能用标题代替") from None


def _now(value=None):
    value = value or datetime.now(CST)
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("时间须包含时区")
    return value.astimezone(CST)


class Service:
    def __init__(self, box, fetch=None, connected=None, clock=None):
        self.box, self.store, self.root = box, box.store, Path(box.root).resolve()
        self.fetch, self.connected, self.clock = fetch, connected, clock
        with self.store.connect() as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS production_publications (
 id TEXT PRIMARY KEY, work_id TEXT NOT NULL, version_id TEXT NOT NULL UNIQUE,
 profile_id TEXT NOT NULL, skill_id TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
 title TEXT NOT NULL, published_at TEXT, created_at TEXT NOT NULL,
 log_id INTEGER, template_id TEXT, template_revision TEXT, original_url TEXT);
CREATE TABLE IF NOT EXISTS production_metric_commands (
 id TEXT PRIMARY KEY, signature TEXT NOT NULL, kind TEXT NOT NULL,
 state TEXT NOT NULL, created_at TEXT NOT NULL, document TEXT NOT NULL);
''')
            if "original_url" not in {row[1] for row in c.execute("PRAGMA table_info(production_publications)")}:
                c.execute("ALTER TABLE production_publications ADD COLUMN original_url TEXT")

    def _time(self, now=None):
        return _now(now if now is not None else self.clock() if self.clock else None)

    def _version(self, wid, vid):
        ident(wid); ident(vid)
        with self.store.connect() as c:
            job = c.execute("SELECT * FROM toolbox_jobs WHERE work_id=? AND id=?", (wid, vid)).fetchone()
            row = c.execute("SELECT value FROM toolbox_meta WHERE key=?", ("native-review:" + vid,)).fetchone()
            work = c.execute("SELECT title FROM toolbox_works WHERE id=?", (wid,)).fetchone()
        receipt = (json.loads(row[0]).get("receipt") or {}) if row else {}
        if not job or job["status"] != "completed" or receipt.get("status") != "completed" or not receipt.get("whole_ready") or receipt.get("work_id") != wid or receipt.get("skill_id") not in SKILLS:
            raise ValueError("只能关联两个油猪生产技能完整交付的准确版本")
        profile = ident(receipt.get("profile_id"))
        # Use the accepted turn's exact frozen choice, never today's template.
        template = {}
        with self.store.connect() as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='easel_chat_turns'").fetchone():
                turn = c.execute("SELECT document FROM easel_chat_turns WHERE id=?", (vid,)).fetchone()
                if turn:
                    creation = (json.loads(turn[0]).get("context") or {}).get("creation") or {}
                    template = {k: creation.get(k) for k in ("template_id", "template_revision")}
        return {**receipt, **template, "title": work["title"], "profile_id": profile}

    def _command(self, operation, signature, kind, document, now):
        ident(operation)
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute("SELECT * FROM production_metric_commands WHERE id=?", (operation,)).fetchone()
            if old:
                if old["signature"] != signature or old["kind"] != kind:
                    raise ValueError("操作身份已用于不同请求")
                return dict(old), False
            c.execute("INSERT INTO production_metric_commands VALUES(?,?,?,?,?,?)",
                      (operation, signature, kind, "reserved", now.isoformat(), pack(document)))
        return {"id": operation, "state": "reserved", "document": pack(document)}, True

    def operation_result(self, operation):
        ident(operation)
        with self.store.connect() as c:
            row = c.execute("SELECT * FROM production_metric_commands WHERE id=?", (operation,)).fetchone()
        if not row:
            return None
        return {"operation_id": operation, "status": row["state"], **json.loads(row["document"])}

    def recover_inflight(self):
        """Close orphaned read identities only after proving no reader owns them.

        A daily id cannot reconcile an older manual id. Startup therefore checks
        all pending reads under the same OS lock as execution, without sending
        anything to the platform. An existing reader keeps its exact ownership.
        """
        try:
            with locked(self.root / "data/production-insights/metrics-sync.lock", timeout=.1):
                recovered = []
                with self.store.connect() as c:
                    c.execute("BEGIN IMMEDIATE")
                    rows = c.execute("SELECT id,document FROM production_metric_commands WHERE kind='sync' AND state IN ('reserved','running')").fetchall()
                    for row in rows:
                        document = json.loads(row["document"])
                        document.update(recovered_at=self._time().isoformat(),
                                        message="上次读取尚未确认完成；原操作已保留，不会自动重发")
                        c.execute("UPDATE production_metric_commands SET state='unknown',document=? WHERE id=? AND state IN ('reserved','running')",
                                  (pack(document), row["id"]))
                        recovered.append(row["id"])
                return {"status": "completed", "recovered": recovered, "count": len(recovered)}
        except TimeoutError:
            return {"status": "busy", "recovered": [], "count": 0}

    def _finish(self, operation, state, result):
        with self.store.connect() as c:
            c.execute("UPDATE production_metric_commands SET state=?,document=? WHERE id=?", (state, pack(result), operation))
        return {"operation_id": operation, "status": state, **result}

    def _script(self, skill, *args):
        script = self.root / "skills" / "builtin" / skill / "scripts" / ("log.py" if skill == "skill-publish-log" else "track.py")
        if not script.is_file():
            # TEMP fixtures still execute the actual original script, with the
            # tracker root explicitly set in its isolated interpreter below.
            script = Path(__file__).resolve().parents[3] / "skills" / "builtin" / skill / "scripts" / script.name
        if not script.is_file():
            raise ValueError("原生发布记录/统计脚本不可用")
        env = dict(os.environ, EASEL_ROOT=str(self.root), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        if skill == "skill-data-tracker":
            # The original tracker has module-level roots instead of an env
            # port. Supply its existing roots to the one original implementation.
            code = "import importlib.util,pathlib,sys; p=sys.argv.pop(1); root=pathlib.Path(sys.argv.pop(1)); s=importlib.util.spec_from_file_location('easel_tracker',p); m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.SNAP_ROOT=root/'outputs/_analytics/snapshots';m.LEGACY_SNAP_ROOT=root/'outputs/analytics/snapshots';m.main(sys.argv[1:])"
            command = [sys.executable, "-c", code, str(script), str(self.root), *args]
        else:
            command = [sys.executable, str(script), "--data", str(owned_output_path(self.root, Path("outputs/_analytics/publish-log.json"))), *args]
        process = subprocess.run(command, cwd=self.root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
        if process.returncode:
            raise ValueError("原生发布记录/统计写入未完成，原请求已保留")
        return json.loads(process.stdout)

    def _record_log(self, binding):
        if binding["log_id"] is not None:
            return binding
        with locked(self.root / "data/production-insights/publish-log.lock"):
            records = self._script("skill-publish-log", "query", "--platform", "wechat-oa", "--profile", binding["profile_id"])["entries"]
            exact = []
            for entry in records:
                try:
                    if canonical_url(entry.get("url", "")) == binding["url"]:
                        exact.append(entry)
                except ValueError:
                    continue
            if len(exact) > 1:
                raise ValueError("原生发布记录中此链接存在多条记录，请先人工核对")
            if exact:
                log_id = exact[0]["id"]
            else:
                args = ["record", "--platform", "wechat-oa", "--profile", binding["profile_id"],
                        "--title", binding["title"], "--url", binding.get("original_url") or binding["url"],
                        "--type", SKILLS[binding["skill_id"]], "--skill-source", binding["skill_id"],
                        "--notes", pack({"manual_publication_binding": binding["id"], "work_id": binding["work_id"],
                                          "version_id": binding["version_id"], "publication_time_confirmed": bool(binding["published_at"])})]
                if binding["published_at"]:
                    args += ["--published-at", binding["published_at"]]
                log_id = self._script("skill-publish-log", *args)["id"]
            with self.store.connect() as c:
                c.execute("UPDATE production_publications SET log_id=? WHERE id=? AND log_id IS NULL", (log_id, binding["id"]))
            return {**binding, "log_id": log_id}

    def bind(self, wid, vid, value):
        if not isinstance(value, dict) or set(value) - {"operation_id", "url", "published_at"}:
            raise ValueError("发布关联参数无效")
        operation = ident(value.get("operation_id")); url = canonical_url(value.get("url"))
        published = self._time(value["published_at"]).isoformat() if value.get("published_at") else None
        now = self._time()
        if published and datetime.fromisoformat(published) > now:
            raise ValueError("发布时间不能在未来")
        request = {"work_id": wid, "version_id": vid, "url": value["url"].strip(), "identity_url": url, "published_at": published}
        command, fresh = self._command(operation, pack(request), "bind", request, now)
        if not fresh and command["state"] == "completed":
            return self.view(wid, vid)
        version = self._version(wid, vid)
        bid = "pub-" + hashlib.sha256((wid + "\0" + vid).encode()).hexdigest()[:32]
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute("SELECT * FROM production_publications WHERE version_id=? OR url=?", (vid, url)).fetchone()
            if old and (old["work_id"] != wid or old["version_id"] != vid or old["url"] != url or old["published_at"] != published):
                raise ValueError("该文章或版本已有不同的准确关联，未覆盖历史记录")
            c.execute("INSERT OR IGNORE INTO production_publications VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (bid, wid, vid, version["profile_id"], version["skill_id"], url, version["title"], published,
                       now.isoformat(), None, version.get("template_id"), version.get("template_revision"), value["url"].strip()))
            binding = dict(c.execute("SELECT * FROM production_publications WHERE id=?", (bid,)).fetchone())
        binding = self._record_log(binding)
        self._finish(operation, "completed", {"binding_id": bid, "work_id": wid, "version_id": vid})
        return self.view(wid, vid)

    def _observations(self, binding):
        directory = owned_output_path(self.root, Path("outputs/_analytics/snapshots") / binding["profile_id"] / "wechat-oa")
        observations = []
        for path in sorted(directory.glob("????-??-??.json"), reverse=True)[:30]:
            if path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
                continue
            try:
                snapshot = json.loads(path.read_text(encoding="utf-8"))
                for post in snapshot.get("post_snapshots", []):
                    if post.get("binding_id") == binding["id"]:
                        observations.append({"date": snapshot["date"], **post})
            except (OSError, ValueError, KeyError):
                continue
        return observations

    def view(self, wid, vid):
        ident(wid); ident(vid)
        with self.store.connect() as c:
            binding = c.execute("SELECT * FROM production_publications WHERE work_id=? AND version_id=?", (wid, vid)).fetchone()
            last = c.execute("SELECT id,state,document FROM production_metric_commands WHERE kind='sync' ORDER BY rowid DESC LIMIT 1").fetchone()
        binding = dict(binding) if binding else None
        public_binding = {**binding, "identity_url": binding["url"], "url": binding.get("original_url") or binding["url"]} if binding else None
        return {"binding": public_binding, "observations": self._observations(binding) if binding else [],
                "sync": {"operation_id": last["id"], "status": last["state"], **json.loads(last["document"])} if last else None,
                "account_required": self.connected() is False if self.connected else None,
                "definitions": DEFINITIONS, "schedule": "每日 09:00（Asia/Shanghai），只读刷新已绑定作品"}

    def sync(self, value=None, *, now=None):
        value = value or {}
        if not isinstance(value, dict) or set(value) - {"operation_id"}:
            raise ValueError("数据刷新参数无效")
        operation = ident(value.get("operation_id"))
        started = self._time(now)
        row, fresh = self._command(operation, pack({"kind": "sync"}), "sync", {"started_at": started.isoformat()}, started)
        if not fresh:
            result = self.operation_result(operation)
            if row["state"] in ("reserved", "running"):
                try:
                    with locked(self.root / "data/production-insights/metrics-sync.lock", timeout=.1):
                        current = self.operation_result(operation)
                        if current["status"] in ("reserved", "running"):
                            return self._finish(operation, "unknown", {**json.loads(row["document"]), "message": "上次读取尚未确认完成；不会重复执行该请求"})
                        return current
                except TimeoutError:
                    return result  # The original process still owns the read.
            return result
        with self.store.connect() as c:
            bindings = [dict(r) for r in c.execute("SELECT * FROM production_publications ORDER BY rowid")]
        if not bindings:
            return self._finish(operation, "completed", {"observed_at": started.isoformat(), "matched": 0, "bound": 0, "outcome": "empty"})
        if not self.fetch or self.connected and not self.connected():
            return self._finish(operation, "blocked", {"observed_at": started.isoformat(), "outcome": "login_required", "message": "请在原生账号页连接微信公众号，再刷新数据"})
        lock_owned = False
        try:
            with locked(self.root / "data/production-insights/metrics-sync.lock", timeout=.1):
                lock_owned = True
                with self.store.connect() as c:
                    claimed = c.execute("UPDATE production_metric_commands SET state='running' WHERE id=? AND state='reserved'", (operation,)).rowcount
                if not claimed:
                    return self.operation_result(operation)
                data = self.fetch()
                if inspect.isawaitable(data):
                    data = asyncio.run(data)
                if not isinstance(data, dict) or data.get("loggedIn") is not True:
                    return self._finish(operation, "blocked", {"observed_at": started.isoformat(), "outcome": "login_required", "message": "公众号登录已失效，请在原生账号页重新扫码"})
                if data.get("error"):
                    return self._finish(operation, "failed", {"observed_at": started.isoformat(), "outcome": "read_failed", "message": "公众号数据读取未完成，没有写入替代数据"})
                observed = self._time() if now is None else started
                candidates = {}
                for note in (data.get("articles") or data.get("notes") or [])[:100]:
                    try:
                        key = canonical_url(note.get("url", ""))
                    except ValueError:
                        continue
                    if key in candidates:
                        candidates[key] = None  # Ambiguous response never guessed.
                    else:
                        candidates[key] = note
                matched = []
                for binding in bindings:
                    note = candidates.get(binding["url"])
                    if note is None or not isinstance(note.get("structured_metrics"), dict):
                        continue
                    metrics = {k: v if type(v) is int and v >= 0 else None for k, v in note["structured_metrics"].items() if k in DEFINITIONS}
                    if not any(v is not None for v in metrics.values()):
                        continue
                    binding = self._record_log(binding)
                    age = (observed - datetime.fromisoformat(binding["published_at"])).total_seconds() / 3600 if binding["published_at"] else None
                    matched.append((binding, {"post_id": str(binding["log_id"]), "binding_id": binding["id"],
                        "title": note.get("title") or binding["title"], "url": binding.get("original_url") or binding["url"], "published_at": binding["published_at"],
                        "observed_at": observed.isoformat(), "age_hours": round(age, 2) if age is not None else None,
                        "views": metrics.get("read_pv"), "likes": metrics.get("likes"), "comments": metrics.get("comments"),
                        "shares": metrics.get("shares"), "metrics": metrics, "metric_definitions": DEFINITIONS,
                        "template_id": binding["template_id"], "template_revision": binding["template_revision"],
                        "coverage": data.get("coverage")}))
                for profile in sorted({b["profile_id"] for b, _ in matched}):
                    self._snapshot(profile, [p for b, p in matched if b["profile_id"] == profile], observed, data)
                return self._finish(operation, "completed", {"observed_at": observed.isoformat(), "matched": len(matched), "bound": len(bindings),
                    "outcome": "measured" if matched else "no_data", "coverage": data.get("coverage"),
                    "unmatched": [b["id"] for b in bindings if b["id"] not in {m["id"] for m, _ in matched}]})
        except TimeoutError:
            if not lock_owned:
                return self._finish(operation, "blocked", {"observed_at": started.isoformat(), "outcome": "busy", "message": "已有一次公众号数据读取在执行"})
            return self._finish(operation, "unknown", {"observed_at": started.isoformat(), "outcome": "read_timeout", "message": "公众号数据读取超时，原操作已保留，不会重复执行该请求"})
        except Exception as exc:
            # This is a read-only request, but transport ambiguity remains a
            # durable unknown receipt. A new explicit refresh uses a new id.
            state = "failed" if getattr(exc, "status_code", None) in (401, 403, 404, 502) else "unknown"
            return self._finish(operation, state, {"observed_at": started.isoformat(), "outcome": "read_failed", "message": "公众号数据读取未完成；已有指标未被空值或旧缓存覆盖"})

    def _snapshot(self, profile, posts, observed, data):
        date = observed.date().isoformat()
        path = owned_output_path(self.root, Path("outputs/_analytics/snapshots") / profile / "wechat-oa" / (date + ".json"))
        with locked(self.root / "data/production-insights/tracker.lock"):
            previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            keys = {p["binding_id"] for p in posts}
            all_posts = [p for p in previous.get("post_snapshots", []) if p.get("binding_id") not in keys] + posts
            with tempfile.TemporaryDirectory(prefix="easel-metrics-") as temporary:
                staged = Path(temporary) / "posts.json"
                staged.write_text(pack(all_posts), encoding="utf-8")
                args = ["snapshot", "--profile", profile, "--platform", "wechat-oa", "--date", date, "--posts", str(staged)]
                for field, flag in (("followers", "--followers"), ("likes", "--total-likes"), ("posts", "--total-posts")):
                    metric = data.get(field)
                    if type(metric) is int and metric >= 0:
                        args += [flag, str(metric)]
                self._script("skill-data-tracker", *args)

    def run_due_once(self, now=None):
        current = self._time(now)
        if current.hour < 9:
            return None
        with self.store.connect() as c:
            if not c.execute("SELECT 1 FROM production_publications LIMIT 1").fetchone():
                return None
        return self.sync({"operation_id": "wechat-daily-" + current.date().isoformat()}, now=current)
