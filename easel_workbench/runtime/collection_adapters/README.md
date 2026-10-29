# 项目采集适配器

统一入口为 `collection_sources.run_source`，调度、状态目录、模型解释和入库确认均由本项目管理。

- `aibot_daily_news.py`：AI工具集 HTML 日期分段解析与有限重试。
- `newsnow_ai_digest.py`：固定来源白名单、候选队列、退避和逐条确认；仅接收显式项目状态目录。
- `newsnow_ai_sources.json`：固定实例与来源白名单。跨源对照使用项目 canonical 完整正文。
- `rank_candidates.py`：实质性门槛、算法排序和全局多样性；AIHOT最多30条，其他编辑来源最多10条，失败覆盖补查使用同批剩余数量。

这里没有外部排程、旧报告读取或旧模型调用入口。原代码的来源字节和迁移前版本保存在 `docs/history/collection-retired-20261027`，不参与运行包。
