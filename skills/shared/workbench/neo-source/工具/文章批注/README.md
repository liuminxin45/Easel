# 文章批注与自动保存

轻量Python标准库后台，仅监听127.0.0.1。没有云端上传、第三方依赖、保存按钮或导出步骤。正文和标题可选中批注；编辑、删除自动保存到单篇目录。界面在正文复制区之外，使用CSS Highlight，不往文章文本里插入标记。

## 当前文章

活动状态：`内容/ChatGPT Desktop UI组件库开源/批注/当前批注.json`。

本机服务地址和进程记录在忽略目录`.runtime/文章批注/ui-article-ready.json`，端口属于本机运行状态。使用其中`url`打开审阅页；不要把旧的file预览误认为项目同步入口。当前后台不是系统服务，没有开机自启。

## 为新文章准备

先产生符合公众号规范的干净HTML，再包装审阅版；两个文件都属于该文章目录，输出不能覆盖已有版本：

```powershell
python -X utf8 工具/文章批注/review.py prepare --article-dir "内容/标题" --input "内容/标题/发布稿/净稿-v1.html" --output "内容/标题/发布稿/公众号-v1.html" --version v1
python -X utf8 工具/文章批注/review.py serve --article-dir "内容/标题" --html "内容/标题/发布稿/公众号-v1.html" --version v1 --markdown "内容/标题/草稿-v1.md" --ready-file ".runtime/文章批注/本篇服务.json"
```

`serve`打印本机URL。后台启动时在Windows使用`Start-Process -WindowStyle Hidden`并把日志及ready-file放.runtime。重启前先检查ready-file的进程与`/health`，不要重复启动；想保留旧地址可在端口空闲时加`--port 原端口`。存在活动批注时，启动不能悄悄切文章版本或清空意见。

标题、文章文字均可选中，点“添加批注”后输入，也可点右下角固定的“批注选中文字”。选区变化、鼠标／触摸结束均会更新入口，支持没有document mouseup的选中方式；内置浏览器自身菜单出现时仍有固定入口。右侧／底部面板支持编辑、删除及定位原文。正常状态显示“已自动保存到项目”。文件独立打开只会尝试浏览器暂存，并明确提示；协作使用HTTP审阅入口。网络失败保留浏览器草稿并重试，不能把暂存说成项目已保存。

## 仅修复批注界面

```powershell
python -X utf8 工具/文章批注/review.py refresh-ui --article-dir "内容/标题" --output "内容/标题/发布稿/公众号-v1-批注修复1.html"
```

仅替换嵌入的批注CSS／JS，另存HTML并在锁内切换当前服务文件；保留文章版本、generation、edit_seq、全部意见、编辑历史及在途保存的有效性。不使用advance，不清空意见，也不算一轮文章改稿。旧HTML与界面修复前后状态保留。替换时保持原文的换行字节，不能因Windows换行转换影响原文选区。修复后的界面会在空闲时自动载入后续界面更新，原服务无需重启；较早界面手动刷新加载。后续重启serve以当前状态中的source_html与version为准。

## 读取和改稿

```powershell
python -X utf8 工具/文章批注/review.py read --article-dir "内容/标题"
```

读取活动批注、对应原文及未合并文件；`批注/事件-*.jsonl`保留新增、编辑和删除历史。当前列表是待处理意见，删除过或已被编辑替代的历史文字不再自动执行。

先保存完整意见、逐条处理与改前改后及原因的记录，产出新Markdown／净稿／审阅HTML，检查通过后执行：

```powershell
python -X utf8 工具/文章批注/review.py advance --article-dir "内容/标题" --html "内容/标题/发布稿/公众号-v2.html" --version v2 --markdown "内容/标题/草稿-v2.md" --changes "内容/标题/修改记录-v2.md" --expected-seq 读取时的edit_seq
```

先归档旧HTML、Markdown、批注、编辑事件、修改记录及SHA-256清单，再将活动状态切到新版并清空其批注；旧文件仍保留。若读取后又有新意见、原稿被改过或归档失败，就拒绝清空。旧标签写入被拒后，其意见自动存为未合并文件，不能覆盖当前意见。归档和状态写入有进程锁，原子替换状态文件。

后台始终服务当前版本；未编辑中的审阅页会在版本切换后自动载入新版。用户仍在写的内容先保留，不静默丢弃。明确结束后，按同样方式保存最后一轮，再依据实际反馈总结风格调整；不把“没有批注”当作认可。

## 检查

```powershell
python -X utf8 -m unittest discover -s 工具/文章批注 -p test_review.py -v
node 工具/文章批注/test_browser.mjs
```

后者复用`工具/贴图生产`已安装的Playwright，仅对隔离临时样本验证选择、增改删、刷新、窄屏、纯文本意见、归档和新版清空；不向真实文章写测试批注。接口仅接受同源JSON写入，不开放任意文件读取或跨域写入。
