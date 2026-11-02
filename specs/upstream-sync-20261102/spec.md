# Easel 官方基线同步（2026-11-02）

Spec: upstream-sync-20261102

## 目标和保留行为

按项目 easel-upstream-sync/codex-spec 工作流跟进官方更新：pull rebase、解决冲突与适配、验证、mark基线并推送自有fork。
官方旧基线 `5a597e5f3ef5b01098b53f36caf719dd9a32b7bf` → 目标 `0f43dc98277eac85fb48952878acad349731d3fc`，目标固定为本次pull的FETCH_HEAD。
旧私有 `3246babaaf1ecd22ecdd88217d6e33a3c974d067`、分支 `codex/easel-base-alignment` 保留；新分支 `codex/easel-sync-20261102-082005`。
不重写已共享分支，不推官方，不修改历史标签/快照、业务数据、冻结任务/原文/反馈或未知操作身份。
本次同步不隐含生产部署，现有不可变前后端继续运行。

## 当前进展与集成范围

官方15新提交、64文件；多数采集与代理改动先前已以相同patch引入。
本次rebase自动识别6条官方等价提交，110条完成重放，无手动skip；
唯一显式冲突为SettingsSelect的Tab焦点注释，保留官方措辞和兼容行为。
官方collector cleanup、thinking env重复值/乱码处理、CLI前端过期诊断已进入源码。
核对并纠正历史私有提交覆盖官方Sidebar画像下拉、primary配色/hover、profile滚动和dropdown唯一CSS的偏差；
保留宿主可选接口、移动抽屉、下载及CopyableText扩展，移除已由官方解决的重复实现。
官方dropdown.css新增为私有冻结构建输入；共享服务仍只有一份，私有Python采集/来源修订继续调用官方runner。

## 验证与交付

待运行：原Easel build、check:workbench、build:workbench、基座/架构/技能检查、官方变更相关及私有回归、
相同数据的官方/私有桌面和模拟手机控件对照。
全部通过后才记录integrated基线、历史快照和指向官方准确SHA的annotated tag，正常推送自有origin新分支/本次tag。
记录代码集成与线上发布的区别；不将模拟输入当真实扫码、模型或平台发布。
人工反馈：尚未收到本轮反馈。

原始证据：`.local/workbench-validation/upstream-sync-20261102-082005/`。
