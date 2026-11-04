# 采集排期证据与旧媒体 vendor 分类

## 已核实的问题

独立中控的 `scheduled_sources_late` 并非本轮漏跑：`8a49eef93fe5` 的
2026-11-05 00:00 计划关联任务 `69f80dafc6a4415baa89b7562393a7b0`，
00:06:23 结束，状态 partial，抓取30、筛选7、实际新增7。覆盖诊断中的
36kr-quick 为 HTTPError。排期已记录 last_slot=00:00、next_run_at=06:00。
该诊断文件的 SHA256 为
`017537a1fd8df095b4d525f099ced2b07216318143f017d3a48e1f167da451e9`。

原健康逻辑只将 completed 的 finished_at 视为排期执行证据，因而把实际已完成
的 partial 误判为漏跑，并引用数日前最后一次全量完成的时间。现在区分：

- 排期执行：当前来源修订、准确 collection_slots -> collection_tasks 终态回执；
  completed、empty、partial、failed、blocked 都说明发生过一次检查。
  queued/running、skipped/cancelled、只有排期指针均不能证明执行完成。
- 数据覆盖：独立保留 partial/failed/empty 数量及 coverage_status；partial 不等于
  全量成功，但第三方读取不完整不等于本机采集进程失灵。failed/blocked 仍保留业务告警。
- 第三方诊断：仅在末次异常任务中读取有大小限制的 coverage.json，向健康记录只投影
  HTTP 错误数量，不泄露原文、来源响应、URL 参数或凭据。
- 恢复：健康端点正常时，第三方无信息、partial、业务降级及提供者故障均不授权重启。
  真正过期心跳、漏跑、错误来源修订仍按原独立信号报告；未知已受理请求不重放。

新投影只读生产 SQLite，使用聚合和小型诊断，不读取文章正文、不复制数据库、不启动任务。
本次未改面板缓存/文案：当天采集到多少显示多少；未采到显示空面板，不回退旧缓存。
本日真实 Agent PNG 与浏览器日检已经完成，本次验证只使用 TEMP 与假执行器，未重新调用模型。

## 旧 vendor 的使用分类

| 内容 | 当前用途 | 本次处理 |
| --- | --- | --- |
| `runtime/vendor/easel/scripts/*.py` | 历史导入的媒体代码副本 | 保留原件，当前 worker 不再从此处导入或执行 |
| `runtime/vendor/easel/wechat/` | 历史导入的微信实现 | 保留历史；当前发布 worker 已使用主树 `skills/shared/scripts`，本次不恢复旧发布入口 |
| `runtime/vendor/easel/SOURCE.json`、LICENSE、NOTICE | 历史出处与许可 | 继续保留；bootstrap 将其明确标为 historical_vendor_source |
| `skills/shared/scripts/model_registry.py` | 官方当前模型与提供者目录 | 官方入口和私有媒体适配使用同一源码文件 |
| `skills/shared/scripts/{voice_clone,ai_image,ai_video,ai_music}.py` | 官方当前媒体工具 | 私有独立子进程直接委托这些文件，不复制实现 |

`runtime/easel_source.py` 集中定义当前代码位置及5个文件的真实 SHA。
新计划记录此主树源码摘要；worker 的实际回执另记录 implementation_source。
旧任务、旧 source_release、配置修订、SOURCE.json 与原始回执不迁移或重写。
旧未知任务继续只读核对其原上游任务，禁止重新提交 POST。

执行前由宿主和实际子进程分别核对 payload.source_release 与当前源码摘要。
旧 vendor 摘要、不匹配及缺失摘要均在任何模型登记/提供者调用前阻止，明确 failed/not_sent；
不能把排队旧任务自动换到新实现。reconcile 不经过新执行护栏，只允许原准确上游任务的 GET
核对，保留原凭据与历史源码身份。TEMP 真实 worker 测试覆盖旧/缺失摘要零调用、当前源码
可交付本地假产物，以及旧源码回执仅一次带原凭据的状态 GET。

`data/easel-runtime.json` 的 `accept_new_tasks=false` 未改变。收拢源码不恢复退役媒体
编排/版本/新任务入口。多参考图、遮罩、上游任务回执及 HTTP 发送身份边界继续由薄适配保留。

## 独立中控升级交接

应用部署与项目外的中控运行版本分别核验。总调度先验证当前监控进程身份及当天
daily 回执，保留 `D:/Services/EaselHealthControl/state/`，按既有进程/任务围栏停止旧监控实例后，
可使用现有安装器更新代码并启动监控：

```powershell
pwsh -NoProfile -File ./tools/health-control/install.ps1 -AppRoot D:/Projects/Easel -RuntimeRoot D:/Services/EaselHealthControl -Start
```

不要手动执行 daily/真实 canary，不要删除当天回执或恢复预算。安装器/监控上线由总调度执行；
本次子任务未安装外部服务或部署应用。后续以真实活动版本重新读取健康投影，应见
late_source_count=0、coverage_status=partial，提供者诊断保留且 needs_repair=false。
