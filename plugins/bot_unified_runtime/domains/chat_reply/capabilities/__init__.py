"""chat_reply capabilities: 人格对话/帮助命令面/好感查询/记忆/戳一戳/群信息/话术池（v21r2 §2.3）。"""

# 分库共装（split package，主人 2026-10-11 裁定①「组合可导入」）：生产单树时 no-op。
__path__ = __import__("pkgutil").extend_path(__path__, __name__)
