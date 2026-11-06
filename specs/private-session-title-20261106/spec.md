# 私有会话纯链接标题与受理保存

用户授权仅在私有层修复并推送自有fork、部署上线。普通消息继续复用官方generateSessionTitle，不增加AI请求。仅当官方结果为“新对话”且输入只有URL时，使用GitHub owner/repo、微信公众号文章或域名/可读路径回退；不取凭据、查询参数或片段，不访问链接。

在首条消息的持久受理事务保存前端产生的标题，即使随后技能准备失败也保留；重复受理不重命名，手动名称与既有名称优先。已有未命名会话在打开时沿现有auto-title接口修复，允许有受理记录但未进入原生执行的历史，不批量改名，不重发任务。

实现归PC-03。原Easel算法和共通源码不改。验证正常文字/URL/私有参数不泄露、原子受理失败及人工改名、双构建与冻结版本后上线。证据前缀 `.local/workbench-validation/private-title-*`，未操作实体手机。

## 验证

102项后端会话受理、架构及技能检查与69项前端检查通过；私有和原Easel独立构建通过。冻结实现1acddfc、前端native-private-title-20261106-r2与后端workbench-20261106-083810的9项隔离移动浏览器检查通过：URL标题、准备失败仍保存、已有未命名记录打开后修复、用户改名后续轮不覆盖。TEMP业务数据及假Agent，未访问生产业务数据或调用真实模型。详情见private-title-browser/report.json及private-title-tests/ frontend/build日志。最终推送、上线和数据核验另在同前缀acceptance/deploy/delivery证据登记。
