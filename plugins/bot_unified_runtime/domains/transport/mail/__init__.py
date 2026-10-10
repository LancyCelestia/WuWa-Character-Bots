"""domains/transport/mail: 邮件适配器与桥接（Mail 通道）。

2026-09-18 补齐：v21r2 重组时本目录漏建 ``__init__.py``，靠 PEP 420 命名空间包
侥幸可导入——与全树其余子包惯例不一致。补为常规包。
"""

# 分库共装（split package，主人 2026-10-11 裁定①「组合可导入」）：生产单树时 no-op。
__path__ = __import__("pkgutil").extend_path(__path__, __name__)
