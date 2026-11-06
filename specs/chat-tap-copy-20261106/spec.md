# 会话标题与正文点按复制

用户要求截图中的标题/正文可直接点按复制完整内容，免去移动端手动选中。范围为私有会话原MessageBubble渲染出的明确“标题/正文/配文”等字段；点标签或整块文字均可复制，只复制该字段的纯文本，保留段落、空格、标点与完整URL。

私有ChatSessionView在原消息HTML外绑定集中适配，不复制或改写官方MessageBubble/Markdown，普通段落、程序代码、文件链接、用户消息及生成中不误识别。采用原剪贴板API，WebView拒绝或无API时用浏览器兼容复制，错误不冒称成功。原位置短暂反馈及键盘Enter/Space可用；滚动、横拖、长按、选区、修饰键不触发复制。无新按钮、弹窗、服务端请求或轮询；只观察本会话原消息HTML的childList替换，逐个更新受影响的非流式消息，不观察属性、不扫描全页。

保留原滚动、选字、焦点、草稿、回执和消息，普通官方入口行为不变。真实Edge/TEMP完整会话DOM验收桌面与390/320明暗，分别覆盖完整复制、键盘、拒绝/兼容、选区、滑动、流式和导航重载；平台/模型调用为0。提交自有fork、精确配对冻结后安全上线，实体WebToApp另按实际结果说明。

状态：已随停止恢复最终配对正式上线。此前独立候选受unknown阻塞的记录保留在下文；最终上线见末节。

首次真实浏览器验收发现输入草稿触发官方dangerouslySetInnerHTML重建，初版静态绑定失效。已以该证据改为本会话局部DOM替换观察，按受影响消息装饰；事件按当前DOM解析，保证输入/轮询后仍可点按复制，不改官方组件。

## 验证与当前交付边界

79项前端相关测试、62项架构/技能检查、私有及官方构建通过。最终候选为workbench-20261106-135022 / native-chat-tap-copy-20261106-r3（SHA见本地candidate.json）。真实Edge/TEMP会话五布局（桌面/390/320明暗）30项通过、5截图；完整标题/多段正文/URL、标签与键盘、拖动/长按/选区/流式保护、WebView兼容失败/重试、输入草稿后的重绘均验证。剪贴板端点为合成，实际DOM/选择/焦点/事件保留；未冒称实体vivo或系统剪贴板已验证。

上线前检查发现既有回合54fe99f6-14c2-4797-a0ec-48c2042c1e71为unknown且stop_requested=true，停止回执未确认。原生thread/read返回该原生日志为空，既有精确回执核对接口仍返回unknown；不能据此伪造stopped/completed，也不符合旧无native_id保留审计的条件。没有放宽准入、删记录、重发任务或强制停止；原活动后端workbench-20261106-121428及原前端r6保持不变。复制候选保留待安全终态核对机制处理后切换。原始证据位于.local/workbench-validation/chat-tap-copy-20261106/，尤其browser-final/report.json与deployment-blocker.json。


## 随停止恢复正式上线

2026-11-06：复用原复制实现，在最终后端workbench-20261106-152722 / 前端native-stop-recovery-20261106-r3重新执行五布局30项Edge/TEMP验收通过，并正式切换。原unknown只在有界核对及精确进程身份退休证明后保留结果并解锁，没有伪造原生终态或重发任务。完整版本SHA、Git与上线结果见[停止恢复Spec](../immediate-stop-recovery-20261106/spec.md)；本次证据在`.local/workbench-validation/immediate-stop-recovery-20261106/final-browser-copy/report.json`。实体设备与真实系统剪贴板边界保持如上。
