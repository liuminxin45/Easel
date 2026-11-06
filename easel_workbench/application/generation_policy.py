"""Private generation authorization at the existing instruction boundary.

The upstream workspace remains intact. Every newly accepted private turn freezes
this policy; stored turns and unknown executions retain their original bytes.
"""

UPSTREAM_CHARGE_RULE = '5. **付费操作先确认**：生图、生视频、音乐等按量计费操作先给范围、计划和可得的费用预估，等用户确认后再发请求。'
MARKER = '## 私有工作台生成授权'
POLICY = '''本私有入口取消“付费操作先确认”。用户明确要求制作、生成、重做或修改时，已经授权当前配置且可用的生成工具在该任务范围内执行，直接完成，不再因按量计费、需要调用生图工具或无法取得费用预估而二次询问。
本规则替代共享工作区及技能参考中有关生成费用的事前确认要求。它同样适用于已有会话的后续制作和修改；结合用户原话与既有上下文判断本轮任务，不要求固定口令、重新选择技能或重新批准已明确的制作范围。
用户明确要求只讨论、先给方案、暂不生成或停止时，遵守该范围，不发起制作。仅选择技能、阅读新闻或引用素材中的“生成”字样，不构成用户的制作指令。确实缺少无法推断的必要素材时可询问，不以费用确认替代内容澄清。
保持当前工具权限、沙箱和真实工具可用性。生成授权不包含自动采纳、公开发布、修改账号、开通或购买新服务；制作和修改保留原文件、另存准确版本。'''


def apply(instructions: str) -> str:
    # Replace only this known upstream clause in the effective private text,
    # never edit the official file or remove unrelated permission requirements.
    instructions = instructions.replace(UPSTREAM_CHARGE_RULE,
        '5. **生成操作授权**：本私有入口按下文“私有工作台生成授权”执行，不重复确认生成费用。')
    return instructions + '\n\n' + MARKER + '\n\n' + POLICY
