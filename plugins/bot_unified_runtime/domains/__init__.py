"""v21r2 domains: 八大功能板块 + 扩展域根包（docs/design/v21r2-reorg-plan.md §2）。"""

# 分库共装（split package，主人 2026-10-11 裁定①「组合可导入」）：生产单树时 no-op。
__path__ = __import__("pkgutil").extend_path(__path__, __name__)
