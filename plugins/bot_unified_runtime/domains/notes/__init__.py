"""v21r2 notes domain: 笔记备忘板块（docs/design/v21r2-reorg-plan.md §2.1 #11）。"""

# 分库共装（split package，主人 2026-10-11 裁定①「组合可导入」）：生产单树时 no-op。
__path__ = __import__("pkgutil").extend_path(__path__, __name__)
