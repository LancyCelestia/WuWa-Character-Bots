"""文案红线门白名单（消费方：tests/test_copy_redline_gate.py）。

登记格式：``{规则 ID: {仓库相对路径(posix): 一句豁免理由}}``。

腐化防护（由门测试强制，见 test_allowlist_integrity）：
- 规则 ID 必须是门内已定义规则；
- 文件必须真实存在**且属于扫描范围**（防止登记到不扫描的文件造成假豁免）；
- 每条必须有非空理由。

新增豁免走 PR/批纪流程：先在报告里登记审计结论，再入本表。
"""

from __future__ import annotations

ALLOWLIST: dict[str, dict[str, str]] = {
    # 创造者单名（澜汐/霞月）不得在用户可见文案单独出现绑定创造者身份。
    # addressing.py 是规则内建豁免（称谓权威模块），不在此登记。
    "creator_name": {
        "plugins/bot_unified_runtime/capabilities/chat.py": (
            "管理团队人格注入分区（_render_admin_section 的权威规则文本）："
            "创造者双名『澜汐、霞月』成对出现于身份权威规则，与 addressing.py 同源同权，"
            "属人格资产而非普通文案（AGENTS.md 第四部分 角色/权限 v2；persona-trigger-audit.md §二 判合规）。"
        ),
        # 2026-09-14 三次扩面（G-08）：人格资产入扫描面后的登记。创造者双名在
        # 人格源里是 identity.md §1.3 稳定世界观事实（人格档案本体，非外发文案）；
        # 防泄漏由输出层 plain_text 打码承担，门保证「登记文件之外的人格文件
        # 不得新增创造者名绑定」。
        "personas/shorekeeper/identity.md": (
            "人格权威源 §1.3 创造者与唤醒者：澜汐/霞月是稳定世界观事实（人格档案本体）；"
            "2026-09-14 G-08 扩面席预扫，personas/** 仅此文件与核心知识.md 两处命中。"
        ),
        "personas/shorekeeper/knowledge/守岸人_核心知识.md": (
            "人格知识源（生产 BOT_KNOWLEDGE_FILES 直读）创造者档案段：同 identity.md §1.3 "
            "稳定世界观事实；2026-09-14 G-08 扩面席预扫描合规。"
        ),
    },
}
