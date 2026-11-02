# P2 与新官方基线集成

Spec：`private-workbench-architecture`、`upstream-sync-20261102`。
用户明确要求接到新的官方基线并修复集成差异；本轮未授权生产切换，仍单独记录部署。

## 实现和保留边界

主工作区 `D:/Projects/Easel`，当前分支 `codex/easel-sync-20261102-082005`。
起点 `4e93bcfe4c02d492bd98d4af1c76aa106331fd05`，准确官方基线
`0f43dc98277eac85fb48952878acad349731d3fc`。
将原 P2 `6bbb1f0eb7429d6c9b877986cc2dd79d108033d1` 与
`05fe760ebc83b48e29b316756eaffd61c103655b` 的改动接入，不重写旧分支或旧证据。

原 P2 触及的 17 个现存业务 Python 文件与原 P2 的 AST 完全相同，
原入口与同步分支原实现也没有语义冲突。补丁无文本冲突，不虚构冲突修复。
会话/作品仍使用同一受理事务、原生适配器及连接池，未知回执不重放。
已固定并核对 936 个官方、技能、资源和来源实现的原始 SHA，含私有 SourceRegistry；
不从旧分支覆盖新官方控件或采集适配，不归一化内容寻址原字节。

实际发现的交付问题：原冻结工具固定覆盖主目录共享 candidate.json。
新增可选 --candidate 输出位置，默认行为保持，独立候选也可供原升级器显式读取。
只改变候选文件的输出位置，不改变包成员、签名、源码清洁检查、能力/workspace 绑定或激活逻辑。
TEMP 真 Git 源码与真实冻结过程验证默认/独立两种路径，独立冻结保留共享候选原字节。

## 组合验证

证据：`.local/workbench-validation/p2-upstream-integration-20261102/`。

- P2 会话、作品、HTTP 回滚、问题、停止、重连、超时及独立检查 84 项通过：p2-regressions.xml。
- 架构、技能、SourceRegistry/采集、原始能力字节、设置、原生核对/归属、合同、外部 CLI 和源码冻结 256 项通过：integration-contracts.xml。
- 冻结输出位置最终 3 项通过：candidate-destination.xml；与上组原有源码冻结检查重叠，不相加冒称不同测试。
- 前端 376 项通过：frontend-tests.log；Node 24.19.0 的 check:workbench、build:workbench 及官方 build 均通过。官方 build 保留大于 500KB 的既有打包提示，不冒称零警告。
- 当前源码 + 新官方前端的桌面/390px 模拟手机内容闭环 34 项通过：source-closedloop/content-closedloop-browser.json。
- 155 个私有模块的已迁移边界违规与审查错误为零：inventory.json。

原 P2 的旧基线测试及官方同步之前的 612 项浏览器检查各自保留为历史，
上述结果才对应本次组合，不以两批旧报告代替组合验证。
新增冻结测试首次将原测试尾部误放到新用例内，造成 TEMP source.py 不存在而失败；
已恢复原用例完整范围，保留 candidate-destination-first.xml，不改产品约束使测试通过。

当前源码已通过验证，下一步冻结准确提交与本轮新前端，复验真实恢复和内容闭环。
模型、外部检查仅使用合成执行器，平台写入和真实 AI 为零。
实体 vivo/WebToApp 与实际用户体验仍待验，不由模拟手机结果代填。
