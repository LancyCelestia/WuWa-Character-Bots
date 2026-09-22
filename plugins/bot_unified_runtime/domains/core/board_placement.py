"""物理归位门（G-P1 / G-P2）的**声明数据**——只放清单，不放判据逻辑。

与 `board_taxonomy.py`、`capability_registry.py` 同一哲学：**只声明数据、不 import 包内任何
模块**（本文件住在插件包内，一旦被 `import` 就会拖着 NoneBot 的包初始化跑起来；门禁与脚本
一律用 AST 静态读取，见 `scripts/physical_placement_census.py`）。

判据本体（谁越界、谁没被认领）在 `scripts/physical_placement_census.py` 与
`tests/test_physical_placement_gate.py`；这里只有"白名单前缀 + 枚举字面豁免清单"。

豁免纪律（用户原话）：**不许通配符、不许正则、不许目录兜底**——每一条都是仓库根相对的
字面路径，且必须带一句"为什么"。清单来源是
`.superpowers/sdd/2026-09-22-taxonomy/ORPHAN-MAP.md` §5 的候选，本席未自行新增。
"""

from __future__ import annotations

#: 二级功能 `impl_paths` 的合法落点前缀（G-P1 的"白名单域"锚点）。
DOMAINS_ROOT: str = "plugins/bot_unified_runtime/domains"

#: 插件包根：包根之下的 py 是"生产面"，落在 `DOMAINS_ROOT` 之外即 G-P1 ①越界。
PACKAGE_ROOT: str = "plugins/bot_unified_runtime"

#: 禁止作为认领声明的路径（一把吞掉全仓＝门自毁；ORPHAN-MAP §3.1 的弱锁）。
BANNED_CLAIM_PATHS: tuple[str, ...] = ("plugins", "plugins/bot_unified_runtime")

#: G-P1 越界豁免（`(fid, impl_path, 理由)`）。
#: **当前为空是刻意的**：ORPHAN-MAP §4 尾注判定"文档/门禁/脚本类板块是否豁免 domains 白名单"
#: 属用户裁量面，本席不自造豁免——越界声明一律计入 G_P1_CEILING 棘轮，逐条靠迁移或裁定摘除。
G_P1_EXEMPT: tuple[tuple[str, str, str], ...] = ()

#: G-P2 未认领豁免（`(字面路径, 为什么)`）。逐条摘自 ORPHAN-MAP §5-A（28 枚包命名空间占位）
#: 与 §5-B 的启动件；§5-C 的 13 枚"无机械归主"按该文件自身结论**不入豁免**（标 `待用户裁`，
#: 计入违规账），§5-B 的 `plugins/bot_unified_runtime/__init__.py` 已被 `B07.scheduled-jobs`
#: 认领、不是孤儿，写进来就是一条永不命中的死豁免，故同样不列。
G_P2_EXEMPT: tuple[tuple[str, str], ...] = (
    # ---- A. 包命名空间占位（Python 包存在性所需，无实现语义）----
    ("plugins/bot_unified_runtime/audit/__init__.py", "包命名空间占位（§5-A）：空 `__init__.py`，无二级功能语义"),
    ("plugins/bot_unified_runtime/character/__init__.py", "包命名空间占位（§5-A）：旧顶层包退役中，仅剩命名空间"),
    ("plugins/bot_unified_runtime/contracts/__init__.py", "包命名空间占位（§5-A）：旧顶层包退役中，仅剩命名空间"),
    ("plugins/bot_unified_runtime/domains/__init__.py", "包命名空间占位（§5-A）：`domains/` 包存在性占位"),
    ("plugins/bot_unified_runtime/domains/assistant/__init__.py", "包命名空间占位（§5-A）：域根 `__init__.py`，域归属由该域内其它声明表达"),
    ("plugins/bot_unified_runtime/domains/chat_reply/__init__.py", "包命名空间占位（§5-A）：域根 `__init__.py`，多功能共域无法单一认领"),
    ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/__init__.py", "包命名空间占位（§5-A）：层目录占位，其下能力各有 fid"),
    ("plugins/bot_unified_runtime/domains/chat_reply/ingest/__init__.py", "包命名空间占位（§5-A）：层目录占位"),
    ("plugins/bot_unified_runtime/domains/chat_reply/pipeline/__init__.py", "包命名空间占位（§5-A）：层目录占位"),
    ("plugins/bot_unified_runtime/domains/chat_reply/runtime/__init__.py", "包命名空间占位（§5-A）：层目录占位，其下三 fid 各认领字面文件"),
    ("plugins/bot_unified_runtime/domains/core/__init__.py", "包命名空间占位（§5-A）：域根 `__init__.py`"),
    ("plugins/bot_unified_runtime/domains/core/contracts/__init__.py", "包命名空间占位（§5-A）：跨域契约层占位，契约文件按引用面另裁"),
    ("plugins/bot_unified_runtime/domains/core/supervisor/__init__.py", "包命名空间占位（§5-A）：沙箱监督子包占位"),
    ("plugins/bot_unified_runtime/domains/notes/__init__.py", "包命名空间占位（§5-A）：域根 `__init__.py`"),
    ("plugins/bot_unified_runtime/domains/notes/capabilities/__init__.py", "包命名空间占位（§5-A）：层目录占位"),
    ("plugins/bot_unified_runtime/domains/ops/__init__.py", "包命名空间占位（§5-A）：域根 `__init__.py`"),
    ("plugins/bot_unified_runtime/domains/ops/acceptance/__init__.py", "包命名空间占位（§5-A）：层目录占位"),
    ("plugins/bot_unified_runtime/domains/ops/integrations/__init__.py", "包命名空间占位（§5-A）：层目录占位"),
    ("plugins/bot_unified_runtime/domains/ops/recovery/__init__.py", "包命名空间占位（§5-A）：层目录占位"),
    ("plugins/bot_unified_runtime/domains/ops/repair/__init__.py", "包命名空间占位（§5-A）：层目录占位"),
    ("plugins/bot_unified_runtime/domains/ops/smoke/__init__.py", "包命名空间占位（§5-A）：层目录占位"),
    ("plugins/bot_unified_runtime/domains/transport/__init__.py", "包命名空间占位（§5-A）：域根 `__init__.py`"),
    ("plugins/bot_unified_runtime/domains/transport/extensions/__init__.py", "包命名空间占位（§5-A）：层目录占位"),
    ("plugins/bot_unified_runtime/domains/transport/mail/__init__.py", "包命名空间占位（§5-A）：层目录占位"),
    ("plugins/bot_unified_runtime/runtime/__init__.py", "包命名空间占位（§5-A）：旧顶层包退役中，仅剩命名空间"),
    ("plugins/bot_unified_runtime/sources/__init__.py", "包命名空间占位（§5-A）：旧顶层包退役中，仅剩命名空间"),
    ("plugins/bot_unified_runtime/sources/fetchers/__init__.py", "包命名空间占位（§5-A）：旧顶层子包退役中"),
    ("plugins/bot_unified_runtime/sources/parsers/__init__.py", "包命名空间占位（§5-A）：旧顶层子包退役中"),
    # ---- B. 启动件（进程入口不是二级功能）----
    ("bot.py", "NoneBot 启动 + 崩溃守卫（§5-B）：仓库根唯一 py，属进程入口而非功能实现"),
)
