# 新闻详情承接私有创作能力

状态：2026-11-03 已实施、推送自有 fork 并部署 R4。最终交付及证据索引见 `docs/workbench/NEWS-CREATION-20261103.md`。

## 确认的目标

新闻页作为私有入口：直接讨论怎么写，或选贴图/文章后直接开始制作；风格按画像显式保存默认，本次覆盖不污染默认；讨论转制作沿用同一原生会话。现有技能/引擎/回执/产物继续唯一，不恢复经验、技能候选、版本指针或计划审批。

## 实现合同

新闻详情自然阅读，采集记录进入官方Drawer，底部讨论/制作两入口；制作使用官方Drawer与SettingsSelect，选择writing/visual/character/layout及补充原话。poster四slot必选，article writing必选，其余按需且visual/character成组；不默认使用候选或固定TechPulse。

新增轻量GET新闻creation-context和受控资源图片端口，creation_defaults为画像可选字段；提交复用原/api/chat/submit，context.creation包含intent、format、style、catalog/profile/source revisions、note。服务端把本轮准确材料存入普通inputs附件，production明确执行content-production，discussion明确只讨论。新关联表按新闻/画像续接会话；归档/删除须明确重新开始，未知不重发。

## 验证与交付

TEMP真HTTP/Edge假引擎验证讨论→同会话贴图/文章、风格参考真实使用与SHA、默认隔离/本次覆盖、准确原文、双击/断线/未知、移动明暗及官方抽屉、真实产物内容库。构建、架构和相关回归通过后仅推自有fork，冻结配对部署。只新增字段/表，22历史表和画像原文不主动迁移，保留日检原操作记录，不重复真实Agent测试。证据.local/workbench-validation/news-creation-20261103/。
