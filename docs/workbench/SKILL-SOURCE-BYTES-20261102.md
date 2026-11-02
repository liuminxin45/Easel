# 私有技能准确字节与自动准入

## 故障与修复

2026-11-02，生产库的8个项目技能无法通过`matches_source`，热点制作贴图在模型执行前返回
“此项目技能尚不可调用”。`core.autocrlf=true`使部分已发布资源由LF/混合换行变成CRLF，
文字等价但SHA256变化。原发布验收只证明候选与源码一致，没有证明它们能匹配生产库已发布版本。

本轮逐一核对生产库blob、Git内容与当前文件，确认仅有换行差异后恢复原字节。48份受Git转换
影响的私有文件保留修复前备份；当前执行涉及29份文件，8个项目技能已重新通过校验。
其中一份历史参考保留原有混合换行，禁止将其统一LF后重新计算历史指纹。
数据库、版本、画像、任务与默认pin没有因恢复文件而改写；没有重发用户任务。

## 自动防线

1. `.gitattributes`对8个私有builtin目录与shared/workbench禁用text转换。官方技能沿用原规则。
2. `scripts/check_workbench_skill_bytes.py`默认只读，核对准确资源字节及Git属性；CI的准确字节lock
   位于`docs/workbench/skill-source-bytes.json`，只用于源码检查，不参与运行时技能发现。
3. `.github/workflows/workbench-skill-bytes.yml`在自有main推送、相关PR和手动触发时执行：
   Windows/Linux × autocrlf=true/false，重新检出后检查lock，运行准确字节/发布/部署/热点贴图回归。
4. 冻结前、候选验收与围栏停写后，以只读方式核对真实生产库当前已发布技能，分别验证工作区和
   不可变候选。复用运行时的`matches_source`，不另建能力判定；任何不可调用项阻止切换。

刻意修改技能时，应通过既有发布事务保存新版本并核对原资源，再明确执行
`python scripts/check_workbench_skill_bytes.py --record`，与源码一同审查提交。
CI绝不自动运行`--record`、修改历史SHA或放宽资源校验。旧版迁入仍使用明确预览与迁移授权。

## 验证记录

证据目录：`.local/workbench-validation/skill-source-bytes-20261102/`。

- 修复前只读准入复现8个不可调用项，`before.json`；恢复原件及逐文件SHA见`restoration.json`。
- 准入/真实Git检出/混合换行/CI lock/部署等61项专项测试通过，`unit.xml`。
- 聊天业务、热点来源、架构、技能策略和技能命令107项通过，`business.xml`；其中新增回归先复现
  同一报错，验证未建任务/模型请求，再恢复准确字节，检查同一热点成功生成冻结贴图方案。
- 另外7项针对热点回归与CI lock的复验通过，与上述测试重叠，不额外累加。
- 线上只读`/api/skills`已确认8/8可调用，现有前端159个构建输入未改变，`restored-live.json`。
- 额外执行的旧一次性迁入测试有2项未通过：依赖初始迁移原件的receipt与后续已发布SKILL不同。
  修复前备份与本轮起点Git blob均已不匹配该receipt；保留`integration.xml`原失败，不改历史回执。
  本轮未使用旧迁移工具，也不把这两项报告为通过。

提交、远端CI及最终运行版本以本轮交付回执补记。验证不代表实际模型质量或实体vivo验收。
