"""标题/配图的可追溯助手检查。只验记录、范围与字节，不调用模型、不认可或发布。"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = "规范/模板/创作检查-v1.json"
CATALOG = "资料/风格研究/反馈检查案例.json"
CN = timezone(timedelta(hours=8))


def stamp():
    return datetime.now(CN).isoformat()


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value, *, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def safe(base, relative):
    if not isinstance(relative, str) or not relative.strip() or Path(relative).is_absolute() or ".." in Path(relative).parts or ":" in relative:
        raise ValueError("引用须为目录内相对文件路径：" + str(relative))
    base = Path(base).resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise ValueError("引用不存在或经链接越界：" + relative)
    return target


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + "未填写")
    return value


def is_image(path):
    path = Path(path)
    with path.open("rb") as stream:
        head = stream.read(32)
    return path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif") or head.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8", b"GIF87a", b"GIF89a")) or (head.startswith(b"RIFF") and head[8:12] == b"WEBP")


def evidence(root, entry):
    path = safe(root, entry.get("file"))
    if digest(path.read_bytes()) != entry.get("sha256"):
        raise ValueError("原话证据哈希不匹配：" + entry["file"])
    quote = text(entry.get("quote"), "原话")
    if quote not in path.read_text(encoding="utf-8-sig"):
        raise ValueError("原话不在指定文件中：" + entry["file"])


def prepare_packet(file, *, root=ROOT, format="poster", profile="custom", work_id="", version="", title="", template=None, catalog=None):
    root, file = Path(root).resolve(), Path(file).resolve()
    if not file.is_relative_to(root):
        raise ValueError("检查记录须保存在本项目的对应作品/候选目录")
    if format not in ("poster", "article") or profile not in ("custom", "source-only", "fixed", "none"):
        raise ValueError("format/profile无效")
    template_path = Path(template or root / TEMPLATE).resolve()
    catalog_path = Path(catalog or root / CATALOG).resolve()
    for path in (template_path, catalog_path):
        if not path.is_relative_to(root):
            raise ValueError("检查约定与案例须在本项目内")
    contract, cases = read(template_path), read(catalog_path)
    if contract.get("id") != "neo-content-creative-review-v1" or cases.get("schema_version") != 1:
        raise ValueError("检查约定/案例版本无效")
    selected = [deepcopy(case) for case in cases["cases"] if format in case["formats"]]
    for case in selected:
        for entry in case["evidence"]:
            evidence(root, entry)
    packet = {
        "schema_version": 1, "created_at": stamp(), "basis": "assistant_assessment",
        "work_id": text(work_id, "作品标识"), "version": text(version, "版本"),
        "format": format, "profile": profile, "user_approval": "pending", "publication": "not_published",
        "context": {"topic": "", "audience": "", "reader_need": "", "core_message": ""},
        "title": {"mode": "explore", "selected": title, "candidates": [], "reason": "", "lock": None},
        "source_inventory": [], "visuals": [], "materials": [],
        "contract": contract, "contract_sha256": digest(contract),
        "catalog": {"file": catalog_path.relative_to(root).as_posix(), "sha256": digest(catalog_path.read_bytes()), "cases": selected},
        "case_snapshot_sha256": digest(selected),
        "checks": [{"id": row["id"], "stage": row["stage"], "status": "pending", "reason": ""} for row in contract["checks"]],
        "comparisons": [{"case_id": case["id"], "status": "pending", "reason": ""} for case in selected],
        "delivery": {"files": [], "views": []}, "binding_history": []
    }
    write(file, packet, exclusive=True)
    return packet


def plan_value(data):
    return {key: data.get(key) for key in ("work_id", "version", "format", "profile", "context", "title", "source_inventory", "visuals", "materials", "contract_sha256", "case_snapshot_sha256", "comparisons")} | {
        "plan_checks": [row for row in data.get("checks", []) if row.get("stage") == "plan"]}


def outcome(row, label, *, allow_na=True):
    status = row.get("status")
    if status not in ("pass", "not_applicable"):
        raise ValueError(label + "尚未解决：" + str(status))
    if status == "not_applicable" and not allow_na:
        raise ValueError(label + "不能标为不适用")
    text(row.get("reason"), label + "的判断及适用范围理由")


def validate_packet(file, *, root=ROOT, stage="delivery", expected_title=None, expected_format=None, expected_files=(), expected_work_id=None, expected_version=None, require_plan_binding=True):
    file, root = Path(file).resolve(), Path(root).resolve()
    errors = []
    try:
        if not file.is_relative_to(root):
            raise ValueError("检查记录越出项目")
        data, base = read(file), file.parent
        if stage not in ("plan", "delivery"):
            raise ValueError("未知阶段")
        if data.get("schema_version") != 1 or data.get("basis") != "assistant_assessment":
            raise ValueError("须明确为schema1助手检查，不能冒充用户评价")
        if data.get("user_approval") != "pending" or data.get("publication") != "not_published":
            raise ValueError("创作检查不得登记采纳或发布")
        for key in ("work_id", "version"):
            text(data.get(key), key)
        if expected_work_id is not None and data["work_id"] != expected_work_id:
            raise ValueError("检查对应的作品标识不一致")
        if expected_version is not None and data["version"] != expected_version:
            raise ValueError("检查对应的版本不一致")
        if data.get("format") not in ("poster", "article") or data.get("profile") not in ("custom", "source-only", "fixed", "none"):
            raise ValueError("format/profile无效")
        if expected_format and data["format"] != expected_format:
            raise ValueError("检查对应的内容类型不一致")
        contract = data["contract"]
        if contract.get("id") != "neo-content-creative-review-v1" or digest(contract) != data.get("contract_sha256"):
            raise ValueError("冻结检查约定被改写")
        stages = {"title_reasoning": "plan", "visual_reasoning": "plan", "title_consistency": "delivery", "visual_inspection": "delivery"}
        if len(contract["checks"]) != 4 or {row["id"] for row in contract["checks"]} != set(stages):
            raise ValueError("检查项目不完整")
        for spec in contract["checks"]:
            if spec.get("stage") != stages[spec["id"]] or (spec["id"].startswith("title_") and spec.get("allows_not_applicable") is not False):
                raise ValueError("冻结检查项阶段或必填属性无效")
        for key in ("topic", "audience", "reader_need", "core_message"):
            text(data["context"].get(key), "context." + key)
        heading = data["title"]
        selected = text(heading.get("selected"), "最终标题")
        if expected_title is not None and selected != expected_title:
            raise ValueError("最终标题与本版清单不一致")
        text(heading.get("reason"), "标题取舍理由")
        if heading.get("mode") == "explore":
            candidates = heading.get("candidates", [])
            if len({row.get("text") for row in candidates}) < 2:
                raise ValueError("探索标题须比较至少两个不同候选；固定/用户指定标题按实际记录例外")
            for row in candidates:
                text(row.get("text"), "候选标题")
                text(row.get("reason"), "候选的具体角度与受众关系")
            if selected not in [row["text"] for row in candidates]:
                raise ValueError("最终标题未在已比较候选中")
        elif heading.get("mode") in ("fixed", "user_exact"):
            evidence(root, heading.get("lock") or {})
            if heading["mode"] == "user_exact" and selected not in heading["lock"]["quote"]:
                raise ValueError("用户指定标题不在引用的用户原话中")
            if heading["mode"] == "fixed":
                pattern = re.escape(heading["lock"]["quote"]).replace(re.escape("{date}"), r"\d{4}-\d{2}-\d{2}")
                if not re.fullmatch(pattern, selected):
                    raise ValueError("最终标题不符合引用的固定标题全文或{date}模式")
        else:
            raise ValueError("标题模式无效")
        cases = data["catalog"]["cases"]
        if digest(cases) != data.get("case_snapshot_sha256"):
            raise ValueError("冻结案例快照被改写")
        case_ids = [case["id"] for case in cases]
        comparisons = data.get("comparisons", [])
        if len(case_ids) != len(set(case_ids)) or len(comparisons) != len(case_ids) or {row.get("case_id") for row in comparisons} != set(case_ids):
            raise ValueError("历史案例回应缺项或重复")
        for case in cases:
            text(case.get("scope"), "案例适用范围")
            text(case.get("do_not_generalize"), "案例不可外推范围")
            for entry in case["evidence"]:
                evidence(root, entry)
        for row in comparisons:
            outcome(row, "案例 " + row["case_id"])
        rows = data.get("checks", [])
        if len(rows) != len(contract["checks"]) or {row.get("id") for row in rows} != {row["id"] for row in contract["checks"]}:
            raise ValueError("检查回应缺项或重复")
        for spec in contract["checks"]:
            row = next(row for row in rows if row["id"] == spec["id"])
            if row.get("stage") != spec["stage"]:
                raise ValueError("检查阶段被修改")
            if spec["stage"] == "plan" or stage == "delivery":
                outcome(row, spec["id"], allow_na=spec["allows_not_applicable"])
        has_images = data["profile"] != "none"
        material_files = {row.get("file") for row in data.get("materials", [])}
        if has_images:
            if not data.get("source_inventory") or not data.get("visuals"):
                raise ValueError("须记录现成素材取舍和各图信息分工")
            for row in data["source_inventory"]:
                for key in ("source", "decision", "reason"):
                    text(row.get(key), "素材取舍." + key)
            for row in data["visuals"]:
                for key in ("id", "purpose", "increment", "action", "kind", "final_file"):
                    text(row.get(key), "配图分工." + key)
                if row["kind"] not in ("generated", "screenshot", "diagram", "source"):
                    raise ValueError("配图来源类型须区分生图、截图、图解和来源原图")
                if row["kind"] == "generated":
                    if not isinstance(row.get("uses_mascot"), bool):
                        raise ValueError("生图须显式声明uses_mascot布尔值，不能用空值/字符串跳过身份判断")
                    if row.get("prompt_file") not in material_files:
                        raise ValueError("生图前须绑定实际提示词文件")
                    if row.get("uses_mascot") is True and (not row.get("identity_files") or not set(row["identity_files"]).issubset(material_files)):
                        raise ValueError("新角色动作须绑定实际身份参考，不能只写一只小猪")
            if len({row["id"] for row in data["visuals"]}) != len(data["visuals"]) or len({row["final_file"] for row in data["visuals"]}) != len(data["visuals"]):
                raise ValueError("配图分工的标识/交付路径重复")
        elif data.get("visuals"):
            raise ValueError("无图profile不能藏有配图；请按实际图面选择profile")
        for row in data.get("materials", []):
            if digest(safe(base, row.get("file")).read_bytes()) != row.get("sha256"):
                raise ValueError("制作前提示词/参考/材料已变更：" + str(row.get("file")))
        if require_plan_binding and data.get("plan_binding", {}).get("sha256") != digest(plan_value(data)):
            raise ValueError("制作前检查未绑定或计划已改动；须重新完成plan绑定")
        if stage == "delivery":
            if data.get("delivery_binding", {}).get("sha256") != digest(data.get("delivery")):
                raise ValueError("交付文件/目视记录未绑定或已修改")
            files = data.get("delivery", {}).get("files", [])
            if not files or len(files) != len({row.get("file") for row in files}):
                raise ValueError("最终交付文件缺失或重复")
            bound = {row["file"] for row in files}
            if not set(expected_files).issubset(bound):
                raise ValueError("检查未覆盖本版清单中的全部交付文件")
            images = set()
            for row in files:
                actual = safe(base, row.get("file"))
                if digest(actual.read_bytes()) != row.get("sha256"):
                    raise ValueError("交付物已变更，旧检查不能放行：" + row["file"])
                if row.get("role") not in ("text", "image") or is_image(actual) != (row.get("role") == "image"):
                    raise ValueError("实际图片与交付角色不一致，不能借text绕过目视：" + row["file"])
                if row.get("role") == "image":
                    images.add(row["file"])
            if has_images != bool(images):
                raise ValueError("profile与实际交付图片不一致")
            if images != {row["final_file"] for row in data["visuals"]}:
                raise ValueError("实际交付图片与制作前逐图分工不一致")
            views = data["delivery"].get("views", [])
            for row in views:
                if row.get("target") not in images or row.get("scale") not in ("full", "phone"):
                    raise ValueError("目视记录目标或尺度无效")
                text(row.get("note"), "实际查看结果")
                if (row["scale"] == "full") != (row["file"] == row["target"]):
                    raise ValueError("完整目视须指向成图，手机检查须另有对应预览文件")
                if digest(safe(base, row.get("file")).read_bytes()) != row.get("sha256"):
                    raise ValueError("目视原图/手机预览已变更")
            for image in images:
                if {row["scale"] for row in views if row["target"] == image} != {"full", "phone"}:
                    raise ValueError("每张交付图须记录完整与手机尺度实际查看：" + image)
        return {"ok": True, "errors": [], "stage": stage, "basis": "assistant_assessment", "user_approval": "pending", "record_sha256": digest(file.read_bytes()), "work_id": data["work_id"], "version": data["version"], "scope": "记录完整性、范围与文件字节；不证明吸引力、事实正确或真实目视发生"}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, StopIteration) as error:
        errors.append(str(error))
        return {"ok": False, "errors": errors, "stage": stage, "basis": "assistant_assessment", "user_approval": "pending"}


def bind_packet(file, *, root=ROOT, stage="plan", files=(), images=(), materials=(), reason=""):
    file = Path(file).resolve()
    if not file.is_relative_to(Path(root).resolve()):
        raise ValueError("检查记录越出项目")
    data, base = read(file), file.parent
    if stage == "plan":
        if materials:
            data["materials"] = [{"file": relative, "sha256": digest(safe(base, relative).read_bytes())} for relative in materials]
        # Validate the actual edited data without first replacing a previous successful record.
        temporary = file.with_name(file.name + "." + uuid.uuid4().hex + ".binding-check.json")
        created = False
        try:
            write(temporary, data, exclusive=True)
            created = True
            result = validate_packet(temporary, root=root, stage="plan", require_plan_binding=False)
        finally:
            if created:
                temporary.unlink()
        if not result["ok"]:
            raise ValueError("；".join(result["errors"]))
        binding = {"at": stamp(), "sha256": digest(plan_value(data))}
        previous = data.get("plan_binding")
        if previous and previous["sha256"] != binding["sha256"]:
            text(reason, "重新绑定计划的修改原因")
            for row in data["checks"]:
                if row["stage"] == "delivery":
                    row.update(status="pending", reason="")
        data["plan_binding"] = binding
    elif stage == "delivery":
        if not set(images).issubset(files):
            raise ValueError("图片须同时列入交付文件清单")
        result = validate_packet(file, root=root, stage="plan")
        if not result["ok"]:
            raise ValueError("；".join(result["errors"]))
        previous = deepcopy(data["delivery"])
        if files:
            data["delivery"]["files"] = [{"file": relative, "role": "image" if relative in images else "text", "sha256": digest(safe(base, relative).read_bytes())} for relative in files]
        for row in data["delivery"].get("views", []):
            row["sha256"] = digest(safe(base, row.get("file")).read_bytes())
        binding = {"at": stamp(), "sha256": digest(data["delivery"])}
        if data.get("delivery_binding") and previous != data["delivery"]:
            text(reason, "重新绑定交付物的修改原因")
            for row in data["checks"]:
                if row["stage"] == "delivery":
                    row.update(status="pending", reason="")
        data["delivery_binding"] = binding
    else:
        raise ValueError("未知绑定阶段")
    data["binding_history"].append({"stage": stage, "at": stamp(), "reason": reason or "首次绑定", "sha256": binding["sha256"]})
    write(file, data)
    return {"ok": True, "stage": stage, "basis": "assistant_assessment", "user_approval": "pending"}


def record_feedback(file, *, root=ROOT, work_id="", version="", case_id="", evidence_file="", quote="", outcome="unclear", assessment=""):
    root, file = Path(root).resolve(), Path(file).resolve()
    if not file.is_relative_to(root):
        raise ValueError("反馈观察须保存在项目对应过程目录")
    if outcome not in ("repeat_issue", "positive_example", "unclear"):
        raise ValueError("反馈观察类别无效")
    case = next((case for case in read(root / CATALOG)["cases"] if case["id"] == case_id), None)
    if not case:
        raise ValueError("未知案例标识")
    source = safe(root, evidence_file)
    original = source.read_text(encoding="utf-8-sig")
    for label, actual in (("工具箱作品ID", work_id), ("目标版本ID", version)):
        declared = re.search(r"^" + label + r"：([^\r\n]+)", original, re.MULTILINE)
        if declared and declared.group(1).strip() != actual:
            raise ValueError("反馈观察与原话中的" + label + "不一致")
    entry = {"file": evidence_file, "sha256": digest(source.read_bytes()), "quote": quote}
    evidence(root, entry)
    row = {"schema_version": 1, "basis": "assistant_classification_of_user_feedback", "at": stamp(),
           "work_id": text(work_id, "作品标识"), "version": text(version, "版本"), "case_id": case_id,
           "outcome": outcome, "assessment": text(assessment, "与本案例的对应理由"), "evidence": entry,
           "user_approval": "not_inferred", "policy_change": False}
    write(file, row, exclusive=True)
    return {"ok": True, "file": str(file), "policy_change": False, "user_approval": "not_inferred"}


def summarize(files, *, root=ROOT, feedback_events=()):
    rows, seen = [], set()
    for file in files:
        if not Path(file).resolve().is_relative_to(Path(root).resolve()):
            raise ValueError("检查记录越出项目")
        data = read(file)
        key = (data["work_id"], data["version"])
        if key in seen:
            raise ValueError("同作品版本重复，不能重复累计进步：" + str(key))
        seen.add(key)
        rows.append({"work_id": key[0], "version": key[1], "validation": validate_packet(file, root=root),
                     "assistant_flagged_cases": [row["case_id"] for row in data["comparisons"] if row["status"] == "needs_revision"]})
    observations, observed = [], set()
    for file in feedback_events:
        if not Path(file).resolve().is_relative_to(Path(root).resolve()):
            raise ValueError("反馈观察越出项目")
        row = read(file)
        if row.get("basis") != "assistant_classification_of_user_feedback" or row.get("outcome") not in ("repeat_issue", "positive_example", "unclear") or row.get("policy_change") is not False or row.get("user_approval") != "not_inferred":
            raise ValueError("反馈观察不能冒充用户认可或自动修改规范")
        evidence(root, row["evidence"])
        key = (row["work_id"], row["version"], row["case_id"], row["evidence"]["sha256"])
        if key in observed:
            raise ValueError("同一反馈观察重复，不能重复累计")
        observed.add(key)
        observations.append(row)
    counts = {name: sum(row["outcome"] == name for row in observations) for name in ("repeat_issue", "positive_example", "unclear")}
    return {"ok": True, "versions": rows, "reviewed_versions": len(rows), "user_feedback_measurement": "quoted_observations" if observations else "not_collected", "feedback_counts": counts, "feedback_observations": observations, "quality_improvement": "not_established", "scope": "仅汇总明确指定的助手记录与有原话的反馈观察；观察分类仍由助手判断，不把自审通过、版本数或局部好评换算为整体满意度、点击率或质量提升"}


def check_article_manifest(manifest, *, root=ROOT, stage="delivery"):
    manifest = Path(manifest).resolve()
    if not manifest.is_relative_to(Path(root).resolve()):
        raise ValueError("文章交付清单越出项目")
    data = read(manifest)
    work_id = text(data.get("work_id"), "文章作品标识work_id")
    version = text(data.get("version"), "文章版本version")
    review = safe(manifest.parent, data.get("creative_review"))
    if review.parent != manifest.parent:
        raise ValueError("创作检查须与文章交付清单同层")
    files = [data["body_file"], text(data.get("html_file"), "本版公众号HTML文件")]
    html_file = safe(manifest.parent, data["html_file"])
    images = data.get("images")
    if not isinstance(images, list) or any(not isinstance(image, str) for image in images) or len(images) != len(set(images)):
        raise ValueError("文章images须为不重复的本包配图路径数组，无图明确为空")
    class Images(HTMLParser):
        def __init__(self):
            super().__init__(); self.sources = []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag.lower() in ("img", "source") and attrs.get("srcset"):
                raise ValueError("新文章配图请用明确本地src，避免未列明的srcset分支")
            if tag.lower() == "img":
                self.sources.append(text(attrs.get("src"), "HTML配图src"))
    parser = Images(); parser.feed(html_file.read_text(encoding="utf-8-sig"))
    actual_images = set()
    for source in parser.sources:
        url = urlsplit(source)
        if url.scheme or url.netloc:
            raise ValueError("新文章HTML配图须引用本包相对文件，并作为独立媒体交付")
        target = (html_file.parent / unquote(url.path)).resolve()
        if not target.is_relative_to(manifest.parent) or not target.is_file():
            raise ValueError("文章HTML图片不存在或越出本版目录")
        actual_images.add(target.relative_to(manifest.parent).as_posix())
    if actual_images != set(images):
        raise ValueError("文章HTML实际配图与images清单不一致，不能隐瞒配图或把预览当正文图")
    files.extend(images)
    result = validate_packet(review, root=root, stage=stage, expected_title=data["title"], expected_format="article", expected_files=files if stage == "delivery" else (), expected_work_id=work_id, expected_version=version)
    result["article_scope"] = "仅创作检查；product实测、来源、HTML与媒体交付仍按文章生产规范独立验收"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "bind", "check", "feedback", "summary"))
    parser.add_argument("--file", type=Path)
    parser.add_argument("--article-manifest", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--format", choices=("poster", "article"), default="poster")
    parser.add_argument("--profile", choices=("custom", "source-only", "fixed", "none"), default="custom")
    parser.add_argument("--work-id", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--stage", choices=("plan", "delivery"), default="delivery")
    parser.add_argument("--expected-title")
    parser.add_argument("--expected-format", choices=("poster", "article"))
    parser.add_argument("--expected-work-id")
    parser.add_argument("--expected-version")
    parser.add_argument("--expect-file", action="append", default=[])
    parser.add_argument("--files", nargs="*", default=[])
    parser.add_argument("--images", nargs="*", default=[])
    parser.add_argument("--materials", nargs="*", default=[])
    parser.add_argument("--reason", default="")
    parser.add_argument("--case-id", default="")
    parser.add_argument("--evidence-file", default="")
    parser.add_argument("--quote", default="")
    parser.add_argument("--outcome", choices=("repeat_issue", "positive_example", "unclear"), default="unclear")
    parser.add_argument("--feedback-events", nargs="*", default=[])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "summary":
            result = summarize(args.files, root=args.root, feedback_events=args.feedback_events)
        elif args.command == "check" and args.article_manifest:
            result = check_article_manifest(args.article_manifest, root=args.root, stage=args.stage)
        elif args.file is None:
            raise ValueError("须指定本作品/版本 --file")
        elif args.command == "prepare":
            prepare_packet(args.file, root=args.root, format=args.format, profile=args.profile, work_id=args.work_id, version=args.version, title=args.title)
            result = {"ok": True, "file": str(args.file), "state": "pending_assistant_checks", "user_approval": "pending"}
        elif args.command == "feedback":
            result = record_feedback(args.file, root=args.root, work_id=args.work_id, version=args.version, case_id=args.case_id, evidence_file=args.evidence_file, quote=args.quote, outcome=args.outcome, assessment=args.reason)
        elif args.command == "bind":
            result = bind_packet(args.file, root=args.root, stage=args.stage, files=args.files, images=args.images, materials=args.materials, reason=args.reason)
        else:
            result = validate_packet(args.file, root=args.root, stage=args.stage, expected_title=args.expected_title, expected_format=args.expected_format, expected_files=args.expect_file, expected_work_id=args.expected_work_id, expected_version=args.expected_version)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
        result = {"ok": False, "errors": [str(error)]}
    if args.report:
        try:
            if args.command not in ("check", "summary") or not args.report.resolve().is_relative_to(args.root.resolve()):
                raise ValueError("报告仅用于检查/汇总，须保存在项目内的新文件")
            write(args.report, result, exclusive=True)
        except (OSError, ValueError) as error:
            result = {"ok": False, "errors": [str(error)]}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
