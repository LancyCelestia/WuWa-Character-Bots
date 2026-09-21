"""Compat shim: moved to domains/render/card_render.mica_shell (v21r3 渲染统一).

2026-09-18 补齐：真身 ``mica_shell.py`` 是 v21r3 新增模块，垫片目录此前缺它
（真身 6 文件 ↔ 垫片 5 文件）。全仓已确认**无任何代码**从本路径引用，补垫片是
为了维持一一对应，避免日后有人按旧习惯从 ``output.card_render.*`` 取用时在
导入期即断。

形态说明：本垫片用**星转发**（真身已用 ``__all__`` 明确公开面），不用 v21r2
快照式的显式列名转发——后者依赖真身命名空间，真身一改 import 就会在导入期断
（2026-09-18 ``usage_cards`` 垫片即因此断裂过）。
"""

from plugins.bot_unified_runtime.domains.render.card_render.mica_shell import *
