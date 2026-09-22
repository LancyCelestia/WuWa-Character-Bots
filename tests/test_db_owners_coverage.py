"""IGEN2-②：db-owners.md「唯一清单」⇄ config.py 库键声明点 双向机器比对门（全离线）。

背景（spec-audit SYNC1 缺口11 / 面7）：
- ``docs/db-owners.md`` 自称「唯一清单以此文件为准」，但**没有任何门**把它与代码里的
  库归属声明点对齐——新增 SQLite 库/改配置键，db-owners 不更新也不红（AGENTS 台账 #29
  曾要求同类核对，此项一直裸奔）。
- 本席复核实测：config.py 的 ``bot_*_db_path`` pydantic 字段共 29 个，db-owners.md §一/§二
  登记 ``BOT_*_DB_PATH`` 曾缺 3 个（campus / outbound_gate / schedule，本波已补齐登记）。

落地形态（**有门**，非生成器）：
- 库路径由多 owner 模块各自消费、无「库元数据」单一结构可整表生成（要生成得先造一份
  库→owner/建表/清理的结构化真源，等于在文档外新建第三事实源，越界且高成本）；文档正文
  （建表位置/清理策略）是运维人读知识，不宜机器吐。故按 SYNC1 建议做**双向差集门**：
  代码声明点（config ``*_db_path``）与文档登记行做两个方向的差集，任一侧多出的键即红。
- 取数全部**静态**（AST 解析 config.py 字段、正则扫 db-owners 反引号键），不 import 插件包、
  不连 Runtime、不扫运行数据目录（铁律 6：只读仓内声明与代码）。

口径边界（诚实标注，避免「全绿=全覆盖」误读）：
- 本门覆盖 ``BOT_*_DB_PATH`` 命名族（本仓库键的绝对主形态）。少数以 ``_PATH``/``_db`` 结尾的
  键（``BOT_MEDIA_REGISTRY_PATH``、``BOT_CONTROL_PLANE_*_DB``）**不在本差集**内：前者在文档已登记、
  后者属控制面平台管理库、非应用运行时库清单一族。这是命名不统一导致的**已知盲区**，
  显式记录于此而非假装覆盖；新增此类命名的应用库仍靠评审/该族专项登记，不属本门职责。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_PY = PROJECT_ROOT / "plugins" / "bot_unified_runtime" / "config.py"
DB_OWNERS_MD = PROJECT_ROOT / "docs" / "db-owners.md"

# pydantic 字段名（小写）→ 环境变量名（大写）；以 ``_db_path`` 结尾者即声明了一个库文件。
_DB_PATH_FIELD_SUFFIX = "_db_path"
# 文档侧库键：反引号内、``BOT_`` 前缀、``_DB_PATH`` 结尾的完整大写键（允许中间含下划线）。
_DOC_DB_KEY_RE = re.compile(r"\bBOT_[A-Z0-9_]+_DB_PATH\b")


def _config_db_field_names() -> set[str]:
    """AST 提取 config.py 顶层 pydantic 字段名（``bot_*_db_path``），不 import 插件包。"""
    tree = ast.parse(CONFIG_PY.read_text(encoding="utf-8"))
    fields: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    fields.add(stmt.target.id)
    return {name.upper() for name in fields if name.endswith(_DB_PATH_FIELD_SUFFIX)}


def _doc_registered_db_keys(text: str) -> set[str]:
    """正则提取 db-owners.md 登记的 ``BOT_*_DB_PATH`` 键集合。"""
    return set(_DOC_DB_KEY_RE.findall(text))


def _diff(config_keys: set[str], doc_keys: set[str]) -> tuple[list[str], list[str]]:
    """双向差集：(代码有库键但文档未登记, 文档登记了但代码已无此键)。"""
    missing = sorted(config_keys - doc_keys)
    stale = sorted(doc_keys - config_keys)
    return missing, stale


def test_db_owners_registry_matches_config_db_fields() -> None:
    """主断言：config ``*_db_path`` 库键集合 == db-owners.md 登记的 ``BOT_*_DB_PATH`` 集合。

    新增一个 ``bot_*_db_path`` 字段（=声明一个新库）而未在 db-owners 登记 → missing 非空即红；
    删字段/改名而文档没跟着删 → stale 非空即红。两侧必须严格相等，杜绝静默漂移。
    """
    config_keys = _config_db_field_names()
    doc_keys = _doc_registered_db_keys(DB_OWNERS_MD.read_text(encoding="utf-8"))
    missing, stale = _diff(config_keys, doc_keys)
    assert not missing, (
        "以下 config 库键（bot_*_db_path）未在 docs/db-owners.md 登记，"
        f"db-owners 自称唯一清单即失真：{missing}"
    )
    assert not stale, (
        "以下 db-owners.md 登记的库键在 config.py 已不存在（过期条目），"
        f"请核对是否改名/删库：{stale}"
    )


def test_db_owners_truth_sources_nonempty() -> None:
    """防提取器空转导致门永真：两侧都必须实质非空（<25 视为提取失效，红）。"""
    config_keys = _config_db_field_names()
    doc_keys = _doc_registered_db_keys(DB_OWNERS_MD.read_text(encoding="utf-8"))
    assert len(config_keys) >= 25, f"config 库键提取疑似失效（仅 {len(config_keys)} 个）"
    assert len(doc_keys) >= 25, f"db-owners 库键提取疑似失效（仅 {len(doc_keys)} 个）"


# ---------------------------------------------------------------------------
# 可红性（变异测试）：把某一侧改坏 → 差集必须非空（内存内，绝不写盘）。
# ---------------------------------------------------------------------------


def test_mutation_new_db_field_without_doc_row_is_red() -> None:
    """模拟「新加一个 bot_*_db_path 字段但未登记 db-owners」→ missing 必须捕获。"""
    config_keys = _config_db_field_names()
    doc_keys = _doc_registered_db_keys(DB_OWNERS_MD.read_text(encoding="utf-8"))
    phantom = "BOT_IGEN2_PHANTOM_DB_PATH"
    missing, stale = _diff(config_keys | {phantom}, doc_keys)
    assert phantom in missing, "门失效：新增库键未登记却未报缺失（永真摆设）"
    assert not stale, "变异前提失效：凭空键不该进 stale 侧"


def test_mutation_doc_row_without_field_is_red() -> None:
    """模拟「db-owners 残留一个代码里已删的库键」→ stale 必须捕获。"""
    config_keys = _config_db_field_names()
    doc_keys = _doc_registered_db_keys(DB_OWNERS_MD.read_text(encoding="utf-8"))
    ghost = "BOT_IGEN2_GHOST_DB_PATH"
    missing, stale = _diff(config_keys, doc_keys | {ghost})
    assert ghost in stale, "门失效：文档登记了不存在的库键却未报过期（永真摆设）"
    assert not missing, "变异前提失效：凭空文档键不该进 missing 侧"


def test_mutation_drop_existing_doc_row_detected() -> None:
    """模拟「从文档删掉一条现有登记」→ 该键应落 missing（存量只登记不消的反证）。"""
    doc_text = DB_OWNERS_MD.read_text(encoding="utf-8")
    doc_keys = _doc_registered_db_keys(doc_text)
    assert doc_keys, "变异前提失效：文档未提取到任何库键"
    removed = min(doc_keys)
    reduced = {k for k in doc_keys if k != removed}
    missing, _stale = _diff(_config_db_field_names(), reduced)
    assert removed in missing, "门失效：删掉一条现有登记却未报缺失（永真摆设）"

