# Easel 官方远端版本基线

当前已集成基线的机器读取入口仍为 `upstream-base.json`。本索引和 `upstream-versions/` 保存已核验的历史事实，不是第二份运行配置。发现官方新提交只代表有待同步，不能自动改写已集成基线。

## 当前记录

| 项目 | 已核验版本 |
|---|---|
| 官方仓库与跟踪分支 | [ZJU-REAL/Easel](https://github.com/ZJU-REAL/Easel)，`upstream/main` |
| 官方准确提交 | [`0f43dc98277eac85fb48952878acad349731d3fc`](https://github.com/ZJU-REAL/Easel/commit/0f43dc98277eac85fb48952878acad349731d3fc) |
| 官方提交时间 | 2026-11-02T00:41:47+08:00 |
| 官方提交标题 | `fix: harden settings, collector cleanup and frontend diagnostics` |
| 本次远端核验时间 | 2026-11-02T09:15:03.619870+08:00 |
| 旧 → 新已集成基线 | `5a597e5` → `0f43dc9` |
| 固定 Git 引用 | `easel-upstream/2026-11-02-0f43dc9`，annotated tag，指向官方准确提交 |
| 自有 fork 与同步分支 | [liuminxin45/Easel](https://github.com/liuminxin45/Easel)，`codex/easel-sync-20261102-082005` |
| 本次验收源码 | `2fa12825958db102c73d743ca906b7ddee0af7c0` |
| 集成/发布状态 | 代码已集成并验收；新基线未部署 |
| 仍在运行的后端 / 前端 | `workbench-20261101-161847` / `native-mobile-unified-r6-20261102001420` |

准确版本描述为 `v0.3.0-92-g0f43dc9`，不是新的官方语义版本发布号。
按项目流程新建分支执行 `git pull --rebase`；6条相同patch由Git识别为官方已包含，110条重放，无手动skip。
旧分支保留；其间另有并行P2提交到旧分支，已登记且未覆盖，本次验收不包含P2，后续独立集成。
当前验证376前端、212官方相关（1平台跳过）、59私有采集/回执、102架构/技能，以及R3定点612浏览器检查通过。
官方原检出同数据对照、原件SHA冷启动和最小SkillDrawer portal修复均留原始证据；实体设备/真实模型/平台发布未验。

## 历史索引

每次通过验收、正式提升基线后新增一行和一份 JSON。旧记录及旧标签不覆盖、不移动；各记录中的 fork 与发布版本表示建档时的状态。

| 记录 | 已集成官方提交 | 状态 | 对应 fork 提交 | 机器可读快照 |
|---|---|---|---|---|
| 2026-11-02 | `0f43dc98277eac85fb48952878acad349731d3fc` | 已集成、未部署 | `2fa12825958db102c73d743ca906b7ddee0af7c0`（验收源码） | [2026-11-02-0f43dc9.json](upstream-versions/2026-11-02-0f43dc9.json) |
| 2026-10-30 | `5a597e5f3ef5b01098b53f36caf719dd9a32b7bf` | 已集成、已发布 | `cc9d4858ae561640dc83ec3f32591ee672711448` | [2026-10-30-5a597e5.json](upstream-versions/2026-10-30-5a597e5.json) |

2026-10-30初次建档只增加基线档案与固定引用，不修改运行代码、`AGENTS.md`、当前基线指针或不可变发布文件。发布验收见 [整改交付记录](EASEL-BASE-ALIGNMENT-20261030.md)，公共接缝见 [适配点说明](ADAPTATION-POINTS.md)。

## 以后跟进官方

使用项目维护技能 [easel-upstream-sync](../../.agents/skills/easel-upstream-sync/SKILL.md)：`git pull --rebase` 更新 → 解决冲突并验证 → mark 准确基线。它独立于内容制作技能目录；只创建技能不会执行同步或部署。

先获取并对比，保留已集成基线不动：

```powershell
git fetch upstream --prune
git ls-remote upstream refs/heads/main
git log --oneline easel-upstream/2026-10-30-5a597e5..upstream/main
git diff --stat easel-upstream/2026-10-30-5a597e5 upstream/main
```

上面的旧标签示例用于历史对照；当前基线取本页当前记录。以后从历史索引选取当时已集成的最新标签，并把新的官方完整 SHA 固定到同步分支；不要在实现期间反复跟随移动中的 `main`。

1. 在干净工作区、总调度确认文件归属后，从当前私有 HEAD 建立新的 `codex/easel-sync-日期时间`，保留旧分支及旧 SHA；执行 `git -c rebase.updateRefs=false pull --rebase --no-autostash upstream main`。新同步分支承接私有改动，旧分支不重写；不能用重置或覆盖方式替换本工程。准确官方目标取本次 fetch 成功后的 `FETCH_HEAD^{commit}`。
2. 按适配点清单审查原组件与公共服务的变化，再修正私有适配器。通用修复与私有业务分别提交；共通内容继续直接复用原实现。
3. 确认 rebase 结果后，在同一候选中同步 `upstream-base.json` 和 `scripts/workbench_release.py` 当前的基线 SHA 字段；后者现有 `easel_base`、`upstream_commit` 两处，不能漏改。运行基座审计、相关架构/业务测试，以及原 Easel 与工作台的独立检查和构建。
4. 只有验收通过才把新基线作为正式交付。新增日期与 SHA 命名的历史快照，记录旧/新官方 SHA、tree、核验时间、fork 提交、发布配对、适配差异和证据；更新此索引，不重写旧快照。当前基线指针及技能声明均属于构建输入，变化后须重新冻结和验收配对版本。
5. 为新的官方 SHA 创建独立 annotated tag，禁止强制移动旧标签。检查 `origin` 为自有 fork，使用完整 refspec 只推本次分支和标签，不用 `--tags`，不向 `upstream` 推送。本分支包含私有业务，未来向官方贡献时另行整理通用补丁。

本次固定引用可在自有 fork 新检出后获取并核对：

```powershell
git fetch origin refs/tags/easel-upstream/2026-10-30-5a597e5:refs/tags/easel-upstream/2026-10-30-5a597e5
git rev-parse 'easel-upstream/2026-10-30-5a597e5^{commit}'
git show --no-patch easel-upstream/2026-10-30-5a597e5
```
