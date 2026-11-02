# Git 交付约定

2026-11-02 用户明确要求：私有开发直接在自有 fork 的主分支开发、推送；只有官方贡献使用独立分支和官方 PR。

| 工作范围 | 开发位置 | 交付目标 | PR |
| --- | --- | --- | --- |
| 私有工作台、部署工具、项目规范与日常修复 | 本项目 `main` | `origin/main`，即 `liuminxin45/Easel` | 不需要 |
| 用户明确要求隔离的私有任务 | 用户指定分支 | 验证后合回 `main` 并推送 `origin/main` | 默认不需要 |
| 用户明确要求贡献给官方的通用修复 | 准确官方基线上的独立贡献分支 | 先推自有 fork 分支，再向 `ZJU-REAL/Easel:main` 提 PR | 等待官方审查、合并 |

`origin` 为自有 fork，`upstream` 为官方只读来源，其直接推送地址保持禁用。创建官方 PR 不等于向官方主分支直接执行 `git push`。私有代码和运行数据不能混入官方贡献。

提交前核对当前分支、修改范围及对应检查；使用明确文件路径暂存。按本项目格式保留 `Spec:`、`Spec-Docs:`。推送后使用 `git ls-remote` 核对准确分支 SHA；合并使用祖先关系核验，不能把“推送了开发分支”报告成“已进入主分支”。发现远端主分支前进时先整合，禁止强推覆盖。

正式部署仍走准确不可变配对、空闲准入和进程身份围栏，Git 合并或推送不替代部署验收。旧分支及其他工作树不因本约定自动删除、改写或部署。

## 本轮清理结果

私有主分支先快进到已验收源码 `7c53063`，再以 `e539878` 补齐历史私有集成分支的合并关系。旧基座的115个提交与现行源码补丁等价；其余整合与P2提交已由 `452e1fe`、`8747400` 及后续P3–P6改造接入。另两条旧集成历史同样是补丁等价或同一整合的适配版本。历史合并前后 Git tree 完全一致，没有恢复旧实现。

以下7个私有分支 tip 均已成为 `main` 祖先：`codex/easel-sync-20261102-082005`、`codex/easel-base-alignment`、`codex/codex-full-access`、`codex/easel-local-migration`、`codex/full-access-stability-integration`、`codex/strategy-prompt-checkout-proof`、`codex/workbench-integration`。

官方贡献保持分离：[#190](https://github.com/ZJU-REAL/Easel/pull/190) 对应 `codex/fix-profile-recovery`，[#191](https://github.com/ZJU-REAL/Easel/pull/191) 对应 `codex/fix-skills-workspace-freshness`，核对时均待官方合并。`codex/fix-mobile-sidebar` 对应已关闭未合并的 [#176](https://github.com/ZJU-REAL/Easel/pull/176)，保留其历史；现行私有版已使用更新的共享移动导航。`gh-pages` 是独立网站发布历史。

本机核查证据：`.local/workbench-validation/fork-merge-20261102/`。源码树一致性与全部私有 tip 的祖先检查是本轮合并验收，未以重新运行模型、修改业务数据或重发制作任务验证 Git 历史。
