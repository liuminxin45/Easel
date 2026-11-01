# P0/P1 收尾与开发流程复核

日期：2026-11-01。Spec：`private-workbench-architecture`。

## 结论和交付状态

| 核查项 | 结果 |
|---|---|
| P0 静态基线 | 已建立，可按准确版本重建符号、引用、SQL 候选写入、角色和资源路径 |
| P0 全部语义归类 | 未完成；138 项初步归类仍有 42 项 per-slice-review、7 项 split-by-symbol，其余建议也不等于运行时可达性证明 |
| P1 合同与下载试点 | 已完成；唯一实现、兼容对象导出、旧新行为对照通过 |
| 原代码提交 | `8e84d462e0704406b81f7def2b3e5cadf6543576`，52 文件；实际 ls-remote 确认 origin 集成分支包含该提交 |
| 原批次产品源码漂移 | 46 个产品文件 SHA256 与交付清单全部一致；复核开始 HEAD 83a6c4c 的后续提交未改本批产品代码 |
| 本轮发现 | 依赖审计漏掉两类导入访问形式；已补检查和 11 个反例/允许例 |
| 本轮重跑 | 合同/架构/下载 133 passed，另技能策略/命令 52 passed；0 failed/error/skipped，34 条既有弃用警告；145 个私有模块，已迁移边界违规 0 |
| 上线 | 未部署 P0/P1 新后端；核查时仍指向 workbench-20261101-093226 |

“P0 完成”只能用于静态基线，不可用于原方案要求的全部语义映射。后续每片迁移前，先落实该片的调用者、写入者、事务和兼容职责，不先移动再解释。P2–P6 没有在此批完成。

## 本轮发现的检查缺口

补前现有 77 项检查全部通过，但下面两个非法调用没有被识别：

```python
import easel_workbench.runtime.toolbox_store
easel_workbench.runtime.toolbox_store.ident('id')

from importlib import import_module
store = import_module('easel_workbench.runtime.toolbox_store')
store.pack({})
```

脚本原来没有完整解析模块属性链及赋值后模块别名。补丁扩展静态别名跟踪，并检查 fromlist 为空时 `__import__` 返回根包的语义。测试也包含函数参数遮蔽、函数局部别名隔离和重新赋值，防止误报。补后两探针都产生 `values-import-storage` 违规；实际产品源码没有这两类违规。

这不说明检查已经理解任意动态 Python。未解析的反射、动态 SQL 和运行时入口继续作为待核对事实，不能用静态零违规代替完整运行时证明。

## Codex Spec 实际执行过程

```text
用户授权实施及不变条件
  → 读取 AGENTS、codex-spec 技能及选中指导
  → 项目 context 索引 + 显式选择架构 Spec/源码
  → 追踪入口、调用者、状态拥有者和事务
  → 建立旧版本基线，选择 P0 静态清单 + P1 下载试点
  → 提取唯一实现，保留旧入口和准确语义
  → 代码与 Spec 同步更新
  → 合同/架构反例/服务回归
  → 旧新源码与 HTTP 合同对照
  → TEMP 后端 + 真实 Windows Edge 下载与文件 SHA
  → 复核本批差异、限定文件提交、推送 origin 并核对远端
  → 总调度后续冻结配对与部署（本批尚未进行）

本次复核：重新核对原交付
  → 用非法调用挑战检查有效性
  → 补前复现漏报 → 修补 → 同探针和受影响检查复验
  → 更正 P0 完成范围，更新 Spec 和核查记录
```

当前 Codex Spec 是工程指导、项目知识索引和功能记录，没有自动阶段引擎。判断是否遵循它，要看具体范围、保留条件、选片、行为证据和真实交付；提交中单有 Spec 字段并不能证明开发质量。本项目当前磁盘 AGENTS 已使用 `$codex-spec`；早期记录里的 `$speckit`/`specify` 属旧工具约定，不能据此声称本批运行过旧阶段命令。

`pwsh -NoProfile -File ./scripts/codex-spec.ps1 context --json` 当前返回指导目录；`selected: []` 和 `spec: null` 表示该索引命令没有替人工选读，不否定显式读取本 Spec。提交 `8e84d46` 实际有 `Spec: private-workbench-architecture`、`Spec-Docs: specs/private-workbench-architecture/spec.md`。

## 执行时暴露的问题

1. **P0 状态口径过宽。** 清单生成与完整语义核查不同，现已明确待办，不能把有目录图当成全部职责已厘清。
2. **绿测试仍可能漏检。** 本次两个探针证实原检查不够，已经修补；以后应挑关键断言检查其是否真的能发现破坏。
3. **知识发现尚需手动。** `.codex-spec/config.json` 的 knowledge_packs 为空；AGENTS/Spec/源码目前靠显式读取。没有发现 CLI 阶段引擎故障，因为新工具没有该引擎；空索引也不等于没有阅读上下文。
4. **编辑需以实际源码为准。** 原实现期间两次补丁因上下文空行不匹配而未应用，重读后再修改，并用 38 个模块的业务 AST 对照核查。属于编辑过程问题，不能归为工作流工具故障。
5. **并发目录靠项目协调。** 与移动 UI 会话共享 checkout，按项目约定限定文件范围；Codex Spec 本身不提供文件锁、自动调度或隔离提交。不能整目录暂存覆盖别人的工作。
6. **证据可追溯但仍有本地依赖。** Spec、测试与核查说明进入 Git，原始 XML/浏览器记录在项目约定 `.local/`。不能声称远端仓库已有全部证据或 CI 进行了独立认证。

## 验证边界与证据

本轮执行命令：

```powershell
& .runtime/workbench-python/Scripts/python.exe -m pytest -q tests/test_workbench_private_contracts.py tests/test_workbench_private_architecture.py tests/test_workbench_architecture.py tests/test_workbench_download_delivery.py --junitxml .local/workbench-validation/private-architecture-p0p1-review-20261101/final-checks.xml
& .runtime/workbench-python/Scripts/python.exe -m pytest -q tests/test_workbench_skill_policy.py tests/test_workbench_skill_commands.py --junitxml .local/workbench-validation/private-architecture-p0p1-review-20261101/skill-checks.xml
```

原批次的 148 项服务回归、旧新各 45 项 HTTP 对照、53 项准确合同对照和真实 Edge 记录仍按对应原源码使用，本轮没有重复执行这些全部检查。原 Edge 验证为真实 Windows 浏览器与模拟移动视口，不是实体手机；后端是当时工作目录源码，不是已冻结上线的新版本。

本轮证据：`.local/workbench-validation/private-architecture-p0p1-review-20261101/` 中 `guard-probe-before.json`、`guard-probe-after.json`、`before-checks.xml`、`final-checks.xml`、`final-checks.log`、`current-inventory-final.json`、`review-summary.json`。原批次证据和实现说明见 `PRIVATE-ARCHITECTURE-P0P1-20261101.md`。本轮未修改业务库、冻结输入、技能正文、生产指针或真实平台状态；业务体验的人工验收仍未收到。
