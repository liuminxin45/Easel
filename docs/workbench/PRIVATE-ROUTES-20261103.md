# 私有路由清单

此文件仅留在自有 fork。设置不再显示路由/统计说明，官方更多设置保持其原生内容。

| 功能 | 当前私有路由 |
| --- | --- |
| 工作台 | `/toolbox` |
| 对话 | `/chat`、`/chat/<session>` |
| 技能库 | `/toolbox?section=skills` |
| 内容库 | `/works`、`/works/<work>` |
| 账号 | `/toolbox?section=distribution&pane=connections` |
| 画像 | `/toolbox?section=profiles` |
| 设置 | `/settings`，panel 为 model/env/more |
| 热点、来源详情 | `/news`、`/news/a/<id>` |
| 研究、拆解 | `/toolbox?section=research`（pane=topics/breakdown/references） |
| 日历、发布记录 | `/toolbox?section=calendar`、`/toolbox?section=publications` |
| 原作品/新建兼容入口 | `/posters`、`/articles` 及其详情/new；新建带入原生对话 |

正式界面使用 `/native/` 宿主。API 工具注册仍唯一来自 `/api/config.tools`。

退役：私有 `section=insights/metrics/statistics/stats` 返回工作台；设置 `panel=usage/statistics/stats/paths` 返回原生设置。通知入口、旧 wiki/knowledge/library/notes/ideas 页面及旧知识库设置已退役，继续使用原有兼容归宿；foundation/learning 旧地址按原迁移规则进入画像、技能或研究。不会因旧URL重建这些页面。

“使用与路径”原数据继续使用 `data/usage.sqlite`，保留原有30天原始/180天聚合期限；浏览器统计排队与旧枚举兼容保留。中控从原库只读聚合，在 `D:/Services/EaselHealthControl/state/report.html` 展示最近7天，历史退役项只在有实际记录时列入历史区域，不作为现有页面或入口。统计 HTTP 接口保留兼容，不再提供业务界面。
