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

口径边界与判据层次（诚实标注，避免「全绿=全覆盖」误读；X2-DB-OWNERS-COVERAGE 波扩面）：
- **尺①（键名双向差集，本波已扩到 ``_db`` 族）**：覆盖 ``BOT_*_DB_PATH`` 与 ``BOT_*_DB``
  两命名族（本仓库库键的两大主形态；控制面 ``BOT_CONTROL_PLANE_*_DB`` 六枚 + 视觉缓存
  ``BOT_VISION_CAPTION_CACHE_DB`` 自本波纳入，不再当"平台库另册"豁免）。
  **只判键名在场**（代码声明了库键⇔文档登记了该键），**不校验配置缺省值、不校验路径内容、
  不扫运行盘**。补一枚 ``bot_xxx_db`` 字段而不登记 → red；登记了代码里没有的键 → red。
- **尺②（按值扫 config 的 sqlite 缺省 ⇒ 文档须出现该库文件名，本波新增）**：AST 扫 config.py
  所有**缺省值是 ``*.sqlite3`` 的字段**（不限字段名后缀），其库文件 **basename** 必须在
  db-owners.md 出现。此尺堵"命名不统一"盲区（如 ``BOT_MEDIA_REGISTRY_PATH`` 以 ``_PATH``
  结尾、尺①看不见），并把"文件名登记"从纯人读升级为机器比对。仍**不校验值/内容/盘**。
- **残余盲区（明写：本门**不**覆盖）**：无 config 字段、以 ``runtime_path("data/x.sqlite3")``
  **硬编码**打开的库（``llm_billing`` / ``meme_send_history`` / ``control_plane_events_v21`` /
  ``modality_preprocess`` / §二 各 code-default 库）——它们不落尺①②的"声明点"，故新增此类
  库不会被本门当场拦红。本波把这些逐个**登记**进 db-owners 止血"盘上无主没人认"，但要把
  "新硬编码库自动红"补成机器门，须先给每枚补一把 config 路径键（属 ``config.py`` 改动＝越界，
  见 ``patches/X2-DB-OWNERS-COVERAGE-20261001.md`` 提案）。曾评估过"全树文件名扫描"：
  会对 ``smoke.py`` 里的示例串 ``send_queue.sqlite3``、``safety_exec/paths.py`` 的裸后缀常量
  ``.sqlite3`` 等误伤，得不偿失，故不取。**结论：尺①判"键名在场"，尺②判"文件名在册"，两把
  尺都**不判缺省值/内容/盘**——这是本门的判据天花板，勿当作内容校验。**
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

# pydantic 字段名（小写）→ 环境变量名（大写）；以 ``_db_path`` 或 ``_db`` 结尾者即声明了一个
# 库文件。两后缀互斥：``bot_*_db_path`` 不以 ``_db`` 结尾（以 ``_path`` 收尾），故分别判。
_DB_PATH_FIELD_SUFFIX = "_db_path"
_DB_FIELD_SUFFIX = "_db"
# 文档侧库键：反引号/文内、``BOT_`` 前缀、以 ``_DB`` 或 ``_DB_PATH`` 结尾的完整大写键
# （允许中间含数字下划线）。``(?:_PATH)?`` 让同一正则吃下两族。
_DOC_DB_KEY_RE = re.compile(r"\bBOT_[A-Z0-9_]+_DB(?:_PATH)?\b")
# 尺②：config 字段的缺省字符串值以 ``.sqlite3`` 结尾 → 该字段的库 basename 必须被文档提及。
_SQLITE_DEFAULT_RE = re.compile(r"[A-Za-z0-9_./\\-]*\.sqlite3\b")
# 文档侧出现的库文件名（``.sqlite3``/``.sqlite``），取 basename 入册。
_DOC_DB_FILENAME_RE = re.compile(r"[A-Za-z0-9_./\\-]*\.sqlite3?\b")


def _config_db_field_names() -> set[str]:
    """AST 提取 config.py 顶层 pydantic 字段名（``bot_*_db`` 与 ``bot_*_db_path``）大写形式。

    不 import 插件包。两后缀都收，杜绝"新库用 ``_db`` 命名族→尺①看不见→无主"的老盲区。
    """
    tree = ast.parse(CONFIG_PY.read_text(encoding="utf-8"))
    fields: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    fields.add(stmt.target.id)
    return {
        name.upper()
        for name in fields
        if name.endswith((_DB_PATH_FIELD_SUFFIX, _DB_FIELD_SUFFIX))
    }


def _config_sqlite_default_basenames() -> dict[str, str]:
    """AST 提取 config.py 中**缺省值为 ``*.sqlite3``** 的字段：``ENV键大写 → 库 basename``。

    按值不按名后缀，故能捕获非 ``_db``/``_db_path`` 命名的库键（如 ``bot_media_registry_path``）。
    """
    tree = ast.parse(CONFIG_PY.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
                and stmt.value.value.lower().endswith(".sqlite3")
                and _SQLITE_DEFAULT_RE.fullmatch(stmt.value.value)
            ):
                base = stmt.value.value.replace("\\", "/").rsplit("/", 1)[-1]
                out[stmt.target.id.upper()] = base
    return out


def _doc_registered_db_keys(text: str) -> set[str]:
    """正则提取 db-owners.md 登记的 ``BOT_*_DB`` / ``BOT_*_DB_PATH`` 键集合。"""
    return set(_DOC_DB_KEY_RE.findall(text))


def _doc_registered_filenames(text: str) -> set[str]:
    """正则提取 db-owners.md 提及的库文件 basename（``*.sqlite3`` / ``*.sqlite``）。"""
    basenames: set[str] = set()
    for token in _DOC_DB_FILENAME_RE.findall(text):
        basenames.add(token.replace("\\", "/").rsplit("/", 1)[-1])
    return basenames



def _diff(config_keys: set[str], doc_keys: set[str]) -> tuple[list[str], list[str]]:
    """双向差集：(代码有库键但文档未登记, 文档登记了但代码已无此键)。"""
    missing = sorted(config_keys - doc_keys)
    stale = sorted(doc_keys - config_keys)
    return missing, stale


def test_db_owners_registry_matches_config_db_fields() -> None:
    """主断言（尺①）：config ``*_db``/``*_db_path`` 库键集合 == db-owners.md 登记的 ``BOT_*_DB(_PATH)`` 集合。

    新增一个 ``bot_*_db``/``bot_*_db_path`` 字段（=声明一个新库）而未在 db-owners 登记 → missing 非空即红；
    删字段/改名而文档没跟着删 → stale 非空即红。两侧必须严格相等，杜绝静默漂移。
    **判据层次：只判键名在场，不校验缺省值/路径/盘。**
    """
    config_keys = _config_db_field_names()
    doc_keys = _doc_registered_db_keys(DB_OWNERS_MD.read_text(encoding="utf-8"))
    missing, stale = _diff(config_keys, doc_keys)
    assert not missing, (
        "以下 config 库键（bot_*_db / bot_*_db_path）未在 docs/db-owners.md 登记，"
        f"db-owners 自称唯一清单即失真：{missing}"
    )
    assert not stale, (
        "以下 db-owners.md 登记的库键在 config.py 已不存在（过期条目），"
        f"请核对是否改名/删库：{stale}"
    )


def test_db_owners_config_sqlite_defaults_documented() -> None:
    """尺②：config 每个"缺省值是 .sqlite3 路径"的库字段，其文件名 basename 必须在 db-owners.md 出现。

    按值扫（不限 ``_db``/``_db_path`` 命名），堵命名不统一盲区（``BOT_MEDIA_REGISTRY_PATH`` 等）。
    任一 config 库缺省文件未在文档具名 → 红。**判据层次：判"文件名在册"，仍不校验值内容/盘。**
    """
    defaults = _config_sqlite_default_basenames()
    doc_files = _doc_registered_filenames(DB_OWNERS_MD.read_text(encoding="utf-8"))
    undocumented = {key: base for key, base in defaults.items() if base not in doc_files}
    assert not undocumented, (
        "以下 config 库字段有 .sqlite3 缺省路径，但其文件名未在 docs/db-owners.md 具名登记："
        f"{undocumented}"
    )


def test_db_owners_truth_sources_nonempty() -> None:
    """防提取器空转导致门永真：两侧都必须实质非空（<25 视为提取失效，红）。"""
    config_keys = _config_db_field_names()
    doc_keys = _doc_registered_db_keys(DB_OWNERS_MD.read_text(encoding="utf-8"))
    assert len(config_keys) >= 25, f"config 库键提取疑似失效（仅 {len(config_keys)} 个）"
    assert len(doc_keys) >= 25, f"db-owners 库键提取疑似失效（仅 {len(doc_keys)} 个）"
    # 尺②非空自检：按值至少应识别出控制面族等一批 .sqlite3 缺省，否则提取器空转。
    assert len(_config_sqlite_default_basenames()) >= 20, "config .sqlite3 缺省值提取疑似失效"



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


# ---------------------------------------------------------------------------
# 本波扩面专项（X2-DB-OWNERS-COVERAGE）：证明 ``_db`` 族真被纳入 + 尺②双向自测。
# 注毒腿＝塞一枚未登记必红；反向不误伤腿＝在册库/文件一条不报。
# ---------------------------------------------------------------------------


def test_expansion_db_suffix_family_now_scanned() -> None:
    """扩面正向：控制面 ``BOT_CONTROL_PLANE_*_DB`` 六枚 + 视觉缓存必须已进尺①两侧（不再豁免）。

    这是"扫面确实扩到 ``_db``"的锚点断言：若提取器退化回只认 ``_DB_PATH``，此测试当场红。
    """
    config_keys = _config_db_field_names()
    doc_keys = _doc_registered_db_keys(DB_OWNERS_MD.read_text(encoding="utf-8"))
    required_db = {
        "BOT_CONTROL_PLANE_CONFIG_DB",
        "BOT_CONTROL_PLANE_FEATURES_DB",
        "BOT_CONTROL_PLANE_ACTIONS_DB",
        "BOT_CONTROL_PLANE_PLATFORM_DB",
        "BOT_CONTROL_PLANE_EVENTS_DB",
        "BOT_CONTROL_PLANE_WORKSPACES_DB",
        "BOT_VISION_CAPTION_CACHE_DB",
    }
    assert required_db <= config_keys, f"尺①未捕获 ``_db`` 族声明点：缺 {required_db - config_keys}"
    assert required_db <= doc_keys, f"``_db`` 族有库键未在文档登记：缺 {required_db - doc_keys}"


def test_mutation_new_db_suffix_field_without_doc_row_is_red() -> None:
    """注毒腿（尺①·``_db`` 命名）：新加一枚 ``bot_*_db`` 字段却不登记 → missing 必须捕获。"""
    doc_keys = _doc_registered_db_keys(DB_OWNERS_MD.read_text(encoding="utf-8"))
    phantom = "BOT_X2_PHANTOM_DB"
    # 前置：文档正则必须认得 ``_DB`` 收尾键（否则扩面形同虚设）。
    sample_doc = "示例 `BOT_X2_PHANTOM_DB`"
    assert phantom in _doc_registered_db_keys(sample_doc), "文档侧正则未吃下 ``_DB`` 族＝扩门假动作"
    missing, stale = _diff(_config_db_field_names() | {phantom}, doc_keys)
    assert phantom in missing, "门失效：新增 ``_db`` 库键未登记却未报缺失（永真摆设）"
    assert not stale


def test_mutation_sqlite_default_without_doc_filename_is_red() -> None:
    """注毒腿（尺②）：伪造一枚"config 缺省指 .sqlite3 文件但文档未具名"的库 → 必须落 undocumented。"""
    doc_files = _doc_registered_filenames(DB_OWNERS_MD.read_text(encoding="utf-8"))
    phantom_key, phantom_file = "BOT_X2_PHANTOM_STORE", "x2_phantom.sqlite3"
    fake_defaults = {**_config_sqlite_default_basenames(), phantom_key: phantom_file}
    undocumented = {k: b for k, b in fake_defaults.items() if b not in doc_files}
    assert phantom_key in undocumented, "尺②失效：未具名的 config 库文件却没报（永真摆设）"


def test_reverse_documented_filenames_not_false_flagged() -> None:
    """反向不误伤腿：真实 config 全部 .sqlite3 缺省文件名都已在册，一条都不该被报。"""
    defaults = _config_sqlite_default_basenames()
    doc_files = _doc_registered_filenames(DB_OWNERS_MD.read_text(encoding="utf-8"))
    assert defaults, "尺②提取器空转：config 未识别出任何 .sqlite3 缺省"
    flagged = {k: b for k, b in defaults.items() if b not in doc_files}
    assert not flagged, f"尺②误伤在册库：{flagged}"


