# P2 与新官方基线集成

Spec：`private-workbench-architecture`、`upstream-sync-20261102`。
用户明确要求接到新的官方基线并修复集成差异；本轮完成代码集成和组合验证，生产切换单独处理。

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

当前源码验证及准确冻结包验证均已完成。
模型、外部检查仅使用合成执行器，平台写入和真实 AI 为零。
实体 vivo/WebToApp 与实际用户体验仍待验，不由模拟手机结果代填。

## 准确冻结配对与最终交付

运行源码提交：`874740058d3f0d267e3830e4f92d505bfd7c5b4e`。
后端候选 `workbench-20261102-015158`，manifest SHA256
`4f0b758e836199fecf8dd8874fef90fce0975cc19b25288055c68161dec15c89`。
前端 `native-easel-workbench-20261102014712`，manifest SHA256
`b320ae42d8fc4f220ad35ca0b8e85e8771848b3b7f1f440d4dd52d6aa22a704d`。
前端 156 项构建输入、27 个成员与当前源码逐字节核对；本轮未再改官方同步后的前端源码。

1126 个后端成员、391 Python 编译、capabilities/workspace 与官方 SHA、P2 包入口均核对。
同一冻结包/新前端另跑桌面及模拟手机内容闭环 34 项和移动恢复 9 项通过；
实际模块均来自冻结包，原成员 SHA 保持，见 frozen-package.json、
frozen-closedloop/content-closedloop-browser.json、frozen-recovery-r2/chat-recovery-browser.json。
实际查看移动 V2 和 unknown 截图。首次 unknown 截图抓到 0.24s 淡入的起始帧，
测试取证改为等待 message-row 实际 opacity 达到 0.99 再截图，未修改 DOM/CSS 或用截图替代状态断言；
复跑恢复 9 项仍通过，同一原字输入清晰可读。首次截图及报告保留在 frozen-recovery/。

独立候选写入 `.local/workbench-validation/p2-upstream-integration-20261102/candidate.json`。
共享 candidate 和两个活动指针均与集成前字节相同，936 份保护源码/资源也相同。
本轮不部署、不恢复数据库、不迁入技能，不重放未知回执。
新官方提交及原同步交付均为当前分支祖先；旧 P2 两提交和旧分支保持原样。
本轮提交推送自有 origin 的当前分支 `codex/easel-sync-20261102-082005`，不用 force、
不向官方推送或创建 PR。最终远端 SHA 和证据哈希记录于本轮 delivery.json。
