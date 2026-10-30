---
name: easel-upstream-sync
description: "同步本项目的 Easel 官方代码与已集成基线。当用户要求更新官方版本、对齐上游或处理同步冲突时，使用 git pull --rebase 更新，逐项解决冲突并验证，最后登记准确官方 SHA、历史快照和基线标签。"
---

# Easel 官方基线同步

按 **pull rebase → 解决冲突并验证 → mark 基线** 执行。这是项目仓库维护技能；本文件是唯一入口，不加入 `skills/builtin/` 的创作能力目录、画像默认技能或全局技能目录。创建或修改本技能不代表要求立即更新官方代码。

先读仓库 `AGENTS.md`、[基线台账](../../../docs/workbench/UPSTREAM-VERSIONS.md)、[当前基线](../../../docs/workbench/upstream-base.json)和[适配点](../../../docs/workbench/ADAPTATION-POINTS.md)。用户本次要求的 rebase 优先于旧文档中的 merge 同步方法。

## 1. 用 git pull --rebase 更新

- 核对 Git 根目录与当前分支、工作区、进行中的 rebase/merge 及其他任务的文件归属。工作区必须干净；已有修改先按归属保存，不自动 stash、清理或覆盖。已经处于本次 rebase 中就接着处理冲突，不再 pull。
- 核对 `upstream` 的 fetch URL 为 `https://github.com/ZJU-REAL/Easel.git`，`origin` 为 `https://github.com/liuminxin45/Easel.git`；官方 push 禁用和仓库 pre-push 防护保持。远端不符时先查清，不改成未知仓库继续执行。
- 记录旧分支、旧私有 HEAD、已集成官方 SHA、origin 分支 SHA 和活动发布配对。把本次过程及验证证据写入 `.local/workbench-validation/upstream-sync-日期时间/`。
- 从当前私有 HEAD 新建同步分支，保留旧分支引用。不要从官方分支直接起步而漏掉私有业务，也不要重写已共享分支。

PowerShell 示例（`upstream` 和 `main` 必须来自已核对的配置）：

```powershell
$syncBranch = 'codex/easel-sync-' + (Get-Date -Format yyyyMMdd-HHmmss)
git switch --no-track -c $syncBranch
git -c rebase.updateRefs=false pull --rebase --no-autostash upstream main
```

检查每条命令退出码。`rebase.updateRefs=false` 防止全局配置把保留的旧分支一起改写。私有提交区间含 merge commit 时使用 `--rebase=merges` 保留结构，并复核原合并解法；不要悄悄展开并丢失它们。

pull 成功，或已确认 fetch 成功并进入冲突状态后，立即记录 `git rev-parse 'FETCH_HEAD^{commit}'` 为本次准确官方 SHA。网络/认证失败且未进入 rebase 时不能拿旧 `FETCH_HEAD` 当新基线。核对旧官方基线是新官方 SHA 的祖先；官方历史发生重写时保留现场，不能按普通升级猜测处理。后续 mark 使用这个已记录 SHA，不使用私有 HEAD，也不改用后来移动的远端 HEAD。

官方 SHA 没有变化且当前分支已经包含它时，确认沿用现有标记，不重复创建或覆盖历史记录。

## 2. 解决冲突并验证

```powershell
git status
git diff --name-only --diff-filter=U
```

- 共通页面、样式与服务以官方实现为核心；私有版本、画像、冻结输入、授权、回执和采集协议留在适配层。不能为消除冲突另复制一套实现。
- 逐文件理解冲突及所属提交，保留两侧必要行为。rebase 时 `ours` 是新基底和已重放结果，`theirs` 是当前重放的私有提交，不能整批盲选。历史资产、冻结任务、原始反馈和未知操作身份不按新代码重写。
- 只 `git add` 已处理且属于本轮的路径，再 `git -c core.editor=true rebase --continue`；重复到结束。不能用 `--skip` 掩盖未迁入的私有功能。确需中止时先保存诊断，再 `git rebase --abort` 回到该同步分支原状态，保留旧分支。
- 确认 rebase 状态目录已消失、未解决路径为空，运行 `git diff --check`。对比旧/新区间的 `git range-diff`，核对私有改动、被上游吸收的改动及合并解法，不能只看 rebase 退出码。
- 在候选中同步 `docs/workbench/upstream-base.json` 的官方 SHA 和实际同步分支，以及 `scripts/workbench_release.py` 的基线字段（当前为 `easel_base`、`upstream_commit`），都使用本次准确官方 SHA。此时仍是待验证候选，不能提前标记成功。
- 按当前 `AGENTS.md` 的固定运行时执行原 Easel build、`check:workbench`、`build:workbench`、基座审计、架构、技能策略及技能命令检查，并运行实际改动对应的原生/私有回归。共通 UI 变化还需官方同数据对照；不得用合成执行冒充真实扫码、模型或发布回执。

有剩余冲突或必要检查失败时继续修复；未解决的问题明确记录，不推进成功基线。

## 3. mark 当前最新已集成基线

全部通过后再完成登记：

1. 验证记录的官方 SHA 已包含在新私有 HEAD 中，保留旧/新官方及私有 SHA 的对应关系。将候选基线字段和适配修改形成清晰提交。
2. 按台账现有格式新增 `docs/workbench/upstream-versions/日期-短SHA.json`，记录准确官方 commit/tree/标题/时间、拉取核验时间、旧基线、rebase 前后私有提交、当前 fork 分支及验证证据。更新台账的当前说明和历史索引。旧 JSON、标签、旧发布 manifest 不改写。
3. 新建指向 **官方 SHA** 的 annotated tag：`easel-upstream/日期-短SHA`。记录 tag object SHA 并验证 `^{commit}`。标记已存在且指向一致时复用；不一致时停止，不能 `tag -f` 覆盖。
4. 基线记录区分“代码已集成”和“正式已发布”。没有实际配对部署回执就写明未发布；同步与 mark 不隐含部署、技能激活、模型调用或平台发布授权。
5. 只用明确 refspec 将本次新分支和本次标签推送自有 `origin`，可用 `git push --atomic origin 分支refspec 标签refspec`。默认新分支正常 push，不 force、不 `--tags`、不推官方 upstream。检查远端分支、tag object 与 peeled commit 的实际 SHA。

完成时报告：旧 → 新官方 SHA、rebase 前后私有 SHA、冲突及适配结果、实际验证、记录文件、固定标签、fork 分支与推送结果，以及是否部署。只核对到远端新 HEAD、未完成冲突或验证时，不声称已对齐。
