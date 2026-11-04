# PC-15 准确渠道稿、交付授权与回执

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认保留；类型：私有业务。
- **需求依据：** 用户要求账号、准确内容版本、采纳及交付授权分别核验，未知请求不重复发布。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 渠道稿修订、实际账号、动作批准、草稿/发布/读回回执与只读核对；保留已有交付记录。
- **官方复用与必要差异：** 原 PublishingPage、技能、manual_publish 和主树官方发布脚本；私有层只负责授权事务和存储边界。
- **不可破坏的合同：** 批准绑定稿件 SHA/版本/账号/动作；采纳、登录、排期不扩大发布权；超时不重复提交；未验证的平台能力不能宣称可发布。

**接口与状态归属：** 交付接口经私有 application/distribution 边界；DistributionService 保管既有修订、批准、尝试和回执，实际平台操作经独立 publishing 适配核验。已提交意图不是平台成功。

**私有入口／资源：** [easel_workbench/features/distribution/service.py](../../../easel_workbench/features/distribution/service.py)、[easel_workbench/application/distribution.py](../../../easel_workbench/application/distribution.py)、[easel_workbench/integrations/publishing.py](../../../easel_workbench/integrations/publishing.py)、[web/frontend/src/workbench/ui/publishing.tsx](../../../web/frontend/src/workbench/ui/publishing.tsx)

**官方复用／共通接缝：** [web/frontend/src/components/PublishingPage.tsx](../../../web/frontend/src/components/PublishingPage.tsx)、[easel/manual_publish.py](../../../easel/manual_publish.py)、[skills/shared/scripts/web_publisher.py](../../../skills/shared/scripts/web_publisher.py)

**验证入口：** [tests/test_workbench_delivery.py](../../../tests/test_workbench_delivery.py)、[tests/test_workbench_delivery_reconciliation.py](../../../tests/test_workbench_delivery_reconciliation.py)、[tests/test_workbench_delivery_projection.py](../../../tests/test_workbench_delivery_projection.py)

**需求与设计记录：** [docs/workbench/ADAPTATION-POINTS.md](../../../docs/workbench/ADAPTATION-POINTS.md)、[specs/private-workbench-architecture/spec.md](../../../specs/private-workbench-architecture/spec.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；本次只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。
