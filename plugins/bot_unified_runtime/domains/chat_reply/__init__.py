"""chat_reply 域（消息回复板块）包初始化——v21r2 重组 W15a 起步，子包见方案书 §2.2。"""

# 分库共装（split package，主人 2026-10-11 裁定①「组合可导入」）：生产单树时 no-op。
__path__ = __import__("pkgutil").extend_path(__path__, __name__)
