"""chat_reply/character 子包：人格与记忆域真身（v21r2 重组 W15a 自 character/ 迁入）。

旧路径 ``plugins.bot_unified_runtime.character.*`` 为 PEP 562 活转发垫片，
符号与真身同一对象；垫片退役条件见 docs/design/v21r2-reorg-plan.md §3.1。
memory_service/memory_store_v21/knowledge_service/teaching_service 暂留旧位，
归属待 S8 收官波统一（RWC1 席 SKIP 登记）。
"""

# 分库共装（split package，主人 2026-10-11 裁定①「组合可导入」）：生产单树时 no-op。
__path__ = __import__("pkgutil").extend_path(__path__, __name__)
