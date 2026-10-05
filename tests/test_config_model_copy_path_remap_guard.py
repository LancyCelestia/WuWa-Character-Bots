"""PATH-REMAP-GUARD（2026-10-04，席位 seat-pathremap）：热合并层的裸路径值永不进源码树。

判据（AGENTS 铁律 6＝源码树零 ``data/``；runtime-layout 门读同一把尺）：
``Config`` 把 ``data/...`` 相对路径折进 ``BOT_RUNTIME_DATA_DIR``，靠的是
``config._resolve_runtime_data_paths`` 这枚 ``model_validator(mode="after")``。
而 pydantic 的 ``model_copy(update=...)`` **不重跑校验器**——运行时热改合并层
（根 ``__init__.py::_config_with_runtime_overrides``）正是用它造 Config 视图。

**盘面读数（现算，不抄）**：合并表白名单里**没有任何**路径名册字段
（``PATH_REMAPPED_FIELDS`` ∪ ``PATH_LIST_REMAPPED_FIELDS`` 与热表交集为空），
可 set 面 ``SETTABLE_KEYS`` 同样零路径键；路径键反倒登记在**拒 set** 的
``RESTART_REQUIRED_KEYS`` 里（那才是防线）⇒ **该缝今日不可达**。
唯一的例外形状 ``BOT_DAILY_ASSIST_DIR`` 是**有意**留在名册外的「消费时解析」字段
（登记见 ``tests/test_config_root_registration.py::USE_TIME_RESOLVED_FIELDS``），
由 ``daily_assist`` 自己走 ``build_runtime_data_path`` + ``check_sendable`` 把关。

所以本文件不是「修一枚现网事故」，而是**把不可达钉成有牙的常驻门**：一旦有人把路径键
登记进热表却没接重映射，① 直接打红；② 并给出「接了 ``remap_runtime_data_paths`` 即闭合」
的正解。落点判定一律量**解析结果**是否压在仓库根里，不量夹具写法。

**闭合波（``seat-remapwire``，2026-10-04）＝把「禁令闭合」升级为「接线闭合」**：
上表那枚主锁只判「热表里不许出现路径键」，助手 ``remap_runtime_data_paths`` 当时
**全仓零生产调用点**（只在定义模块的装载期校验器里被委托），而离线烟测 harness
``domains/ops/smoke/route_demo.py`` 在 ``model_copy`` 里合并了名册在册且非空相对的
``bot_meme_api_output_dir="data/memes"`` ⇒ ``--real`` 一跑就在源码树里开目录（铁律 6，
**当日可达**、不走热表所以主锁看不见它）。本文件末尾因此加三把尺：
① 行为尺＝**真生产合并函数**在毒表（内存 monkeypatch）下返回的视图必须已折叠；
② 接线尺＝``plugins/`` 里助手至少有一枚**定义模块之外**的生产调用点（AST 扫）；
③ 站点尺＝中央合并函数体与烟测 harness 的 ``meme_config`` 语句里，``model_copy``
必须**作为实参**喂进助手（顺序写法不算接线，防「返回后再补一刀」被改回去时静默失效）。
助手的第二刀在热路径（每轮判定 12 处调用）上是否零变化，按**实测**判据记账
（``test_hot_path_extra_remap_pass_is_a_verified_noop``），不引用「幂等」这句话当证据。

全文件零写盘：只构造 Config 视图与算路径字符串，``tmp_path`` 之外不碰任何目录；
源码树 ``data/`` 的存在性由 ``_no_new_source_tree_data`` 逐用例前后对拍。
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import plugins.bot_unified_runtime as bot_root_pkg
from plugins.bot_unified_runtime.config import (
    PATH_LIST_REMAPPED_FIELDS,
    PATH_REMAPPED_FIELD_NAMES,
    PATH_REMAPPED_FIELDS,
    Config,
    path_typed_fields_in,
    remap_runtime_data_paths,
    resolve_runtime_data_value,
    runtime_data_root_of,
)
from scripts.runtime_paths import runtime_path

#: 一张「按 CWD 解析就会落进源码树」的路径键（真身在重映射名册里）。
#: 取 meme 库目录：纯标量、名册在册、消费点直接读 config 值。
SAMPLE_PATH_FIELD = "bot_meme_library_dir"
RAW_RELATIVE_VALUE = "data/sneaky_meme_library"

#: 合并层里那枚「看着像路径键、其实有意留在名册外」的热改项（见模块文档）。
USE_TIME_RESOLVED_HOT_FIELD = "bot_daily_assist_dir"

#: 接线三把尺（闭合波）的靶子文件与助手名。
HELPER_NAME = "remap_runtime_data_paths"
CENTRAL_MERGE_FILE = REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
CENTRAL_MERGE_FUNC = "_config_with_runtime_overrides"
SMOKE_MERGE_FILE = (
    REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "ops"
    / "smoke"
    / "route_demo.py"
)
SMOKE_MERGE_FUNC = "_capability_smoke"
#: 助手的定义模块：它自己（定义体 + 委托它的装载期校验器）**不算**「生产调用点」。
HELPER_DEFINITION_FILE = REPO_ROOT / "plugins" / "bot_unified_runtime" / "config.py"
PRODUCTION_SCAN_ROOT = REPO_ROOT / "plugins"


def _call_name(node: ast.AST) -> str:
    """调用点的目标名：``f(...)`` 与 ``mod.f(...)`` 都认（接线写法两种都合法）。

    接受任意结点（非 Call 回空串），因为调用点常写成 ``any(_call_name(n) == ... for n in
    ast.walk(…))``——在 walk 里非 Call 结点占绝大多数，要求每个调用点自己过滤迟早漏。
    """
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    return ""


def _calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == name
    ]


def _function_node(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _production_helper_call_sites() -> tuple[list[tuple[str, int]], list[str]]:
    """扫 ``plugins/`` 找助手的**真调用点**（AST Call），返回 (站点, 跳过未解析的文件)。

    只认 Call 结点：``from .config import remap_runtime_data_paths`` 这类 import、
    docstring 里的提法、定义本体都不算——否则「名字出现过」就能把接线尺洗绿。
    """
    sites: list[tuple[str, int]] = []
    skipped: list[str] = []
    for path in sorted(PRODUCTION_SCAN_ROOT.rglob("*.py")):
        if path == HELPER_DEFINITION_FILE:
            continue  # 定义模块自己不能当自己的调用者
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if HELPER_NAME not in text:
            continue
        try:
            tree = _parse(path)
        except SyntaxError:  # 他席在飞稿语法坏：退回文本形态，绝不因此放行
            skipped.append(f"{path}（SyntaxError，按文本计数）")
            if f"{HELPER_NAME}(" in text:
                sites.append((str(path), 0))
            continue
        for call in _calls_named(tree, HELPER_NAME):
            sites.append((str(path.relative_to(REPO_ROOT)).replace("\\", "/"), call.lineno))
    return sites, skipped


class _StubRuntimeSettings:
    """最小 runtime-settings 替身：合并层只调 ``.get(env_key, None)``。"""

    def __init__(self, mapping: dict[str, Any]) -> None:
        self._mapping = dict(mapping)

    def get(self, key: str, default: Any = None) -> Any:
        return self._mapping.get(key, default)


def _hot_override_field_names() -> tuple[str, ...]:
    """热改合并表的**字段名**读数（现读模块属性，故 monkeypatch 会改判据）。"""
    return tuple(field_name for _env_key, field_name in bot_root_pkg._RUNTIME_HOT_OVERRIDE_FIELDS)


def _hot_override_env_keys() -> tuple[str, ...]:
    return tuple(env_key for env_key, _field in bot_root_pkg._RUNTIME_HOT_OVERRIDE_FIELDS)


def _roster_values(config: Config) -> dict[str, str]:
    """名册内全部路径读数（标量原样、列表逐条摊平），供落域判定。"""
    collected: dict[str, str] = {}
    for name in PATH_REMAPPED_FIELDS:
        collected[name] = str(getattr(config, name))
    for name in PATH_LIST_REMAPPED_FIELDS:
        for index, item in enumerate(getattr(config, name)):
            collected[f"{name}[{index}]"] = str(item)
    return collected


def _resolves_inside_repo(value: str) -> bool:
    """裸值按生产 bot 进程 CWD（仓库根）解析后是否压在源码树里——铁律 6 的尺。

    空读数按「诚实缺席」放行：名册里有 11 枚路径键缺省为空串（如
    ``bot_send_queue_db_path``），消费点判空即不建库，重映射对空串也是原样透传。
    """
    if not value or not value.strip():
        return False
    joined = os.path.normcase(os.path.abspath(os.path.join(str(REPO_ROOT), value.strip())))
    root = os.path.normcase(os.path.abspath(str(REPO_ROOT)))
    return joined == root or joined.startswith(root + os.sep)


def _same_path(left: str | Path, right: str | Path) -> bool:
    """落点等值判定（两侧都过 realpath，折平 Windows 短路径/分隔符/软链差异）。"""
    return os.path.normcase(os.path.realpath(str(left))) == os.path.normcase(
        os.path.realpath(str(right))
    )


@pytest.fixture(autouse=True)
def _no_new_source_tree_data() -> Any:
    """逐用例对拍源码树 ``data/``：本文件的任何断言都不得在里面造东西。"""
    data_dir = REPO_ROOT / "data"

    def snapshot() -> set[str] | None:
        if not data_dir.is_dir():
            return None
        return {str(p.relative_to(data_dir)) for p in data_dir.rglob("*")}

    before = snapshot()
    yield
    after = snapshot()
    assert after == before, (
        f"源码树 data/ 内容变化（前={before!r} 后={after!r}）——铁律 6 破防"
    )


def test_validator_remaps_every_roster_field_outside_repo(tmp_path: Path) -> None:
    """装载期：名册内每条**非空**路径都折进数据根，逐条判定不落仓库根。"""
    data_root = tmp_path / "runtime_data"
    config = Config(bot_runtime_data_dir=str(data_root))
    values = _roster_values(config)
    assert values, "名册读空＝尺失效，本门退化成假绿"
    checked = 0
    for name, value in values.items():
        if not value.strip():
            continue  # 诚实缺席（缺省空串＝该库不建），原样透传是既有行为
        checked += 1
        assert Path(value).is_absolute(), f"{name} 未被重映射成绝对路径：{value!r}"
        assert not _resolves_inside_repo(value), f"{name} 按 CWD 解析压进源码树：{value!r}"
        assert _same_path(value, str(data_root / Path(value).relative_to(data_root))), name
    assert checked >= 40, f"非空名册读数过少（{checked}）＝判定面被空值洗绿，重新现算"


def test_model_copy_skips_validators_and_exposes_raw_value(tmp_path: Path) -> None:
    """机制自证：``model_copy(update=...)`` 不跑校验器 ⇒ 路径键保持裸相对值。

    这条不判「有事故」，只钉「缝的形状」——合并层一旦合并路径键就是这一形态。
    """
    config = Config(bot_runtime_data_dir=str(tmp_path))
    assert getattr(config, SAMPLE_PATH_FIELD).startswith(str(tmp_path))

    merged = config.model_copy(update={SAMPLE_PATH_FIELD: RAW_RELATIVE_VALUE})
    assert getattr(merged, SAMPLE_PATH_FIELD) == RAW_RELATIVE_VALUE, (
        "model_copy 竟然重跑了校验器？尺要跟着换，别把这条当已修"
    )
    assert _resolves_inside_repo(RAW_RELATIVE_VALUE), (
        "裸值按 CWD 解析不落源码树 ⇒ 本判据的靶子没了，重新现算"
    )


def test_remap_helper_closes_the_bypass_and_is_idempotent(tmp_path: Path) -> None:
    """正解：``remap_runtime_data_paths`` 幂等、可在 model_copy 之后补一刀即闭合。"""
    data_root = tmp_path / "runtime_data"
    config = Config(bot_runtime_data_dir=str(data_root))
    merged = config.model_copy(update={SAMPLE_PATH_FIELD: RAW_RELATIVE_VALUE})

    remapped = remap_runtime_data_paths(merged)
    assert remapped is merged, "应就地折叠并原样返回同一对象（禁第二份 Config 形状）"
    resolved = getattr(merged, SAMPLE_PATH_FIELD)
    assert resolved == str(data_root / "sneaky_meme_library"), resolved
    assert not _resolves_inside_repo(resolved), resolved

    twice = str(getattr(remap_runtime_data_paths(merged), SAMPLE_PATH_FIELD))
    assert twice == resolved, "重映射不幂等＝合并层多调一次就换落点"

    # 列表名册同尺：逐条 resolve，空表原样回空表。
    listed = config.model_copy(update={"bot_persona_files": ["data/p1.md", "./DATA/p2.md", "abs"]})
    remap_runtime_data_paths(listed)
    assert listed.bot_persona_files[0] == str(data_root / "p1.md")
    assert listed.bot_persona_files[1] == str(data_root / "p2.md")
    assert listed.bot_persona_files[2] == "abs", "非 data/ 前缀必须原样透传（行为零变化）"


def test_lock_hot_registration_contains_no_path_field() -> None:
    """**本席主锁**：热改合并表里一条路径名册字段都不许有。

    今日读数＝空集＝不可达（诚实盘面）。谁把 ``bot_*_db_path`` / ``*_dir``
    这类键登记进 ``_RUNTIME_HOT_OVERRIDE_FIELDS`` 却没接重映射，这里当场红。
    """
    conflicts = path_typed_fields_in(_hot_override_field_names())
    assert conflicts == (), (
        f"合并层登记了路径键 {conflicts}，而 model_copy 不重跑校验器 ⇒ 裸 data/ 值"
        f"可落源码树。修法＝合并后调 config.remap_runtime_data_paths()，"
        f"或把该键移回需重启面。"
    )


def test_lock_settable_roster_contains_no_path_field() -> None:
    """第二把锁（更早的一道_tripwire_）：``/bot runtime set`` 的可写面白名单里不许有路径键。

    两面登记册语义**相反**，别把防线当违规（现算读数，2026-10-04）：

    * ``SETTABLE_KEYS``＝热 set 允许面 ⇒ 出现路径键才危险（本锁判它空集）；
    * ``RESTART_REQUIRED_KEYS``＝**拒 set** 面 ⇒ 路径键登记在册是**防线本身**，
      实测在册 6 枚（``bot_meme_library_dir`` / ``bot_sticker_dir`` /
      ``bot_outbound_gate_db_path`` / ``bot_reply_policy_db_path`` /
      ``bot_vision_caption_cache_db`` / ``bot_files_write_allowed_dirs``）——
      维护者正是靠这张册把路径键挡在热改面之外。本断言只钉「同一枚路径键不得
      同时活在两面里」，绝不许把这 6 枚当违规删掉。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        settings as rt_settings,
    )

    def to_field(env_key: str) -> str:
        lowered = env_key.lower()
        return lowered if lowered.startswith("bot_") else f"bot_{lowered}"

    settable_fields = {to_field(key) for key in rt_settings.SETTABLE_KEYS}
    restart_fields = {to_field(key) for key in rt_settings.RESTART_REQUIRED_KEYS}

    assert path_typed_fields_in(settable_fields) == (), (
        f"可 set 面出现路径键：{path_typed_fields_in(settable_fields)}"
    )
    refused_paths = set(path_typed_fields_in(sorted(restart_fields)))
    assert refused_paths, "需重启册里一枚路径键都没有＝挡 set 的防线失守，别把它删了"
    assert refused_paths.isdisjoint(settable_fields), (
        f"路径键同时可 set 又标需重启：{sorted(refused_paths & settable_fields)}"
    )


def test_lock_guard_bites_when_a_path_key_gets_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """有牙证明：把一枚真路径键**临时**登记进热表（内存里，monkeypatch 自动还原），
    主锁必须判出冲突；且走**生产那枚合并函数**实测返回视图已折叠（接线在岗）。
    """
    pristine = _hot_override_field_names()
    assert path_typed_fields_in(pristine) == ()

    poisoned = bot_root_pkg._RUNTIME_HOT_OVERRIDE_FIELDS + (
        ("BOT_SNEAKY_MEME_DIR", SAMPLE_PATH_FIELD),
    )
    monkeypatch.setattr(bot_root_pkg, "_RUNTIME_HOT_OVERRIDE_FIELDS", poisoned)
    try:
        # ① 主锁在这一刻必须判出冲突（＝门有牙，不是摆设）。
        assert path_typed_fields_in(_hot_override_field_names()) == (SAMPLE_PATH_FIELD,)

        config = Config(bot_runtime_data_dir=str(tmp_path))

        # ② 机制面（尺不变的那半）：pydantic 的 model_copy 确实不跑校验器 ⇒ 裸值活着。
        raw_view = config.model_copy(update={SAMPLE_PATH_FIELD: RAW_RELATIVE_VALUE})
        assert getattr(raw_view, SAMPLE_PATH_FIELD) == RAW_RELATIVE_VALUE
        assert _resolves_inside_repo(getattr(raw_view, SAMPLE_PATH_FIELD))

        # ③ 生产合并函数本体（闭合波换了尺）：**接线后**裸值不得留在返回视图里。
        #    改这条不是放宽判据——①②④ 三把仍在原地；本席之前的形态是「③ 断言裸值
        #    确实穿过合并层」，那是对「未接线」的取证，接线后它必须反过来（模块文档
        #    ``test_model_copy_skips_validators_and_exposes_raw_value`` 的
        #    「尺要跟着换」预告的就是这一步）。
        merged = bot_root_pkg._config_with_runtime_overrides(
            config, _StubRuntimeSettings({"BOT_SNEAKY_MEME_DIR": RAW_RELATIVE_VALUE})
        )
        assert merged is not config, "合并层无覆盖时才复用原对象；此处有覆盖却复用了原件＝污染生产 Config"
        assert not _resolves_inside_repo(getattr(merged, SAMPLE_PATH_FIELD)), (
            f"生产合并函数返回的视图仍带裸值 {getattr(merged, SAMPLE_PATH_FIELD)!r} ⇒ 接线掉了"
        )

        # ④ 助手补一刀仍等价闭合——同一条尺、同一个对象（机制正解没被接线取代）。
        remap_runtime_data_paths(raw_view)
        assert not _resolves_inside_repo(getattr(raw_view, SAMPLE_PATH_FIELD))
        assert getattr(raw_view, SAMPLE_PATH_FIELD) == str(tmp_path / "sneaky_meme_library")
    finally:
        monkeypatch.undo()
    assert _hot_override_field_names() == pristine, "monkeypatch 未还原＝污染后来的用例"
    assert path_typed_fields_in(_hot_override_field_names()) == ()


def test_unreachable_today_merged_config_keeps_remapped_paths(tmp_path: Path) -> None:
    """不可达实跑：用真合并层喂满热表全部 env 键，名册路径读数一条都不许变。"""
    data_root = tmp_path / "runtime_data"
    config = Config(bot_runtime_data_dir=str(data_root))
    baseline = _roster_values(config)
    # 每枚热键都给一枚「与现值不同」的值，确保 updates 非空、真走 model_copy 那条腿。
    settings = _StubRuntimeSettings({env_key: "sentinel-value" for env_key in _hot_override_env_keys()})
    merged = bot_root_pkg._config_with_runtime_overrides(config, settings)
    assert _roster_values(merged) == baseline, (
        "合并层改动了名册路径读数＝不可达前提破了，按 P0 处理并接重映射"
    )
    for name, value in _roster_values(merged).items():
        assert not _resolves_inside_repo(value), f"{name} 落源码树：{value!r}"


def test_daily_assist_hot_key_is_use_time_resolved_by_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """唯一的路径形态热键＝有意留在名册外的「消费时解析」件，两把尺都得在岗。"""
    assert USE_TIME_RESOLVED_HOT_FIELD in _hot_override_field_names()
    assert USE_TIME_RESOLVED_HOT_FIELD not in PATH_REMAPPED_FIELD_NAMES

    source = (
        REPO_ROOT
        / "plugins/bot_unified_runtime/domains/assistant/daily/store/daily_assist.py"
    ).read_text(encoding="utf-8")
    assert "build_runtime_data_path" in source, "消费时解析腿被摘掉＝该键改为依赖重映射，须入册"
    assert "check_sendable" in source, "路径域守卫被摘掉＝落域闸失守"

    # 同一枚裸值：重映射尺与消费尺必须给同一个落点（两侧对 "./DATA/x" 已对齐）。
    monkey = Config(bot_runtime_data_dir=str(tmp_path))
    remapped = resolve_runtime_data_value(RAW_RELATIVE_VALUE, runtime_data_root_of(monkey))
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    assert _same_path(remapped, runtime_path(RAW_RELATIVE_VALUE)), (
        f"两把尺分叉：config 侧={remapped!r} runtime_paths 侧={runtime_path(RAW_RELATIVE_VALUE)!r}"
    )
    assert not _resolves_inside_repo(remapped)


def test_roster_is_populated_and_helpers_are_reachable() -> None:
    """尺的尺：名册非空、判定函数与校验器共用同一实现（禁第二副本）。"""
    assert len(PATH_REMAPPED_FIELD_NAMES) == len(PATH_REMAPPED_FIELDS) + len(
        PATH_LIST_REMAPPED_FIELDS
    ), "名册并集与两张分册数量不符＝有人抄了第三份"
    assert SAMPLE_PATH_FIELD in PATH_REMAPPED_FIELD_NAMES
    assert path_typed_fields_in(["totally_unknown_key", SAMPLE_PATH_FIELD]) == (SAMPLE_PATH_FIELD,)

    import inspect

    from plugins.bot_unified_runtime import config as config_module

    validator = inspect.getsource(Config._resolve_runtime_data_paths)
    assert "remap_runtime_data_paths" in validator, "校验器不再是薄壳＝出现第二条解析尺"
    assert inspect.getsource(config_module.remap_runtime_data_paths)


# ---------------------------------------------------------------------------
# 闭合波（seat-remapwire，2026-10-04）：接线尺三把 + 热路径零变化实测。
# ---------------------------------------------------------------------------


def test_production_merge_site_remaps_hot_set_path_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**行为尺（本波主锁）**：真·生产合并函数在毒表下返回的视图必须已折叠出仓库根。

    尺子量的是 ``__init__.py::_config_with_runtime_overrides`` **本体**（不是重写一遍
    它的逻辑）：把一枚名册在册路径键临时登记进热表（内存 monkeypatch，用例结束自动还原），
    再用 ``_StubRuntimeSettings`` 喂一枚 ``data/...`` 裸值 ⇒ 返回的 Config 视图里该键
    必须已经落在传入的数据根下，且按 CWD 解析不压进源码树。
    """
    data_root = tmp_path / "runtime_data"
    config = Config(bot_runtime_data_dir=str(data_root))
    original_value = getattr(config, SAMPLE_PATH_FIELD)
    poisoned = bot_root_pkg._RUNTIME_HOT_OVERRIDE_FIELDS + (
        ("BOT_SNEAKY_MEME_DIR", SAMPLE_PATH_FIELD),
    )
    monkeypatch.setattr(bot_root_pkg, "_RUNTIME_HOT_OVERRIDE_FIELDS", poisoned)

    merged = bot_root_pkg._config_with_runtime_overrides(
        config, _StubRuntimeSettings({"BOT_SNEAKY_MEME_DIR": RAW_RELATIVE_VALUE})
    )
    resolved = getattr(merged, SAMPLE_PATH_FIELD)
    assert resolved == str(data_root / "sneaky_meme_library"), (
        f"合并视图读数={resolved!r}：既非折叠值也非裸值＝助手动了别的东西或尺漂了"
    )
    assert not _resolves_inside_repo(resolved), f"合并视图仍把 {resolved!r} 压在源码树里（铁律 6）"

    # 原件没被就地改写：合并层只动新造的视图（生产 Config 是共享对象）。
    assert merged is not config
    assert getattr(config, SAMPLE_PATH_FIELD) == original_value

    # 只闭路径缝：名册里其余每条读数一字不动。
    merged_roster = _roster_values(merged)
    for name, value in _roster_values(config).items():
        if name == SAMPLE_PATH_FIELD:
            continue
        assert merged_roster[name] == value, f"{name} 被接线改动＝越界"

    # 再来一次（热路径每轮判定都调它）＝逐字相同，不逐次漂移。
    again = bot_root_pkg._config_with_runtime_overrides(
        merged, _StubRuntimeSettings({"BOT_SNEAKY_MEME_DIR": RAW_RELATIVE_VALUE})
    )
    assert getattr(again, SAMPLE_PATH_FIELD) == resolved, "重复合并换了落点＝幂等破了"


def test_lock_remap_helper_has_production_caller() -> None:
    """**接线尺（本席第二把主锁）**：助手在 ``plugins/`` 里至少有一枚定义模块之外的调用点。

    背景（现算，非抄）：该助手由 ``seat-pathremap`` 抽出后**全仓零生产调用点**，
    缝只靠「热表里不许出现路径键」这条禁令闭着——禁令管不走热表的合并点（离线烟测
    harness 就是当日可达的那一处）。本锁判的是「接了没有」，与「有没有人违规登记」
    正交；把接线摘掉（改回裸 ``model_copy``）本锁当场红。
    """
    sites, skipped = _production_helper_call_sites()
    assert sites, (
        f"{HELPER_NAME} 在 plugins/ 内零生产调用点（跳过={skipped}）＝助手又是「只定义不接线」，"
        f"合并层的 model_copy 缝重开。修法＝在返回合并视图前把它喂进该助手。"
    )
    caller_files = {Path(p).name for p, _ in sites if p}
    assert HELPER_DEFINITION_FILE.name not in caller_files, "定义模块被当调用者计数＝尺被自己洗绿"


def test_lock_central_merge_site_wires_the_helper() -> None:
    """站点尺①：``_config_with_runtime_overrides`` 函数体内必须把 model_copy 的产物**当实参**喂进助手。

    只认嵌套形态（``remap_runtime_data_paths(config.model_copy(update=updates))``）：
    「先 return 再在别处补一刀」的顺序写法在同一条 ``return`` 上做不到，且日后被改回
    裸返回时不会有任何判据报警——那正是本波要根除的失效形态。
    """
    tree = _parse(CENTRAL_MERGE_FILE)
    func = _function_node(tree, CENTRAL_MERGE_FUNC)
    assert func is not None, f"{CENTRAL_MERGE_FILE.name} 里找不到 {CENTRAL_MERGE_FUNC}＝靶子没了，别删锁，同步尺"
    helper_calls = _calls_named(func, HELPER_NAME)
    assert helper_calls, (
        f"{CENTRAL_MERGE_FUNC} 函数体内没有 {HELPER_NAME} 调用＝禁令闭合退化回结构闭合之前"
    )
    nested = [
        call
        for call in helper_calls
        if any(_call_name(inner) == "model_copy" for inner in ast.walk(call))
    ]
    assert nested, (
        f"{CENTRAL_MERGE_FUNC} 调了助手却没把 model_copy 的结果当实参喂进去＝缝仍在"
    )


def test_lock_smoke_harness_merge_site_wires_the_helper() -> None:
    """站点尺②：离线烟测 ``route_demo`` 的 ``meme_config`` 合并必须过重映射（当日可达的那一处）。

    同时钉「意图没被顺手改掉」：``bot_meme_api_output_dir`` 的更新值仍是相对写法，
    落点由助手折叠——把字面量直接改成绝对路径会让烟测脱离生产的相对路径形态。
    """
    tree = _parse(SMOKE_MERGE_FILE)
    func = _function_node(tree, SMOKE_MERGE_FUNC)
    assert func is not None, f"{SMOKE_MERGE_FILE.name} 里找不到 {SMOKE_MERGE_FUNC}＝靶子没了"
    assigns = [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "meme_config" for t in node.targets)
    ]
    assert assigns, "烟测 harness 的 meme_config 语句不见了＝尺失效（若确已重构，请同步尺别删锁）"
    for stmt in assigns:
        helper_calls = _calls_named(stmt, HELPER_NAME)
        assert helper_calls, (
            f"{SMOKE_MERGE_FILE.name} 的 meme_config 未过 {HELPER_NAME} ⇒ --real 会按 CWD"
            "把 data/ 目录落进源码树（铁律 6）"
        )
        assert any(
            _call_name(inner) == "model_copy" for call in helper_calls for inner in ast.walk(call)
        ), "meme_config 调了助手但没包住 model_copy＝尺要的形态没了"
    update_keys = {
        kw.arg
        for node in ast.walk(func)
        if isinstance(node, ast.Call) and _call_name(node) == "model_copy"
        for kw in node.keywords
        if kw.arg == "update"
    }
    assert update_keys, "meme_config 的 model_copy 没有 update 实参＝靶子换了形状"
    raw_literals: list[str] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and _call_name(node) == "model_copy":
            for kw in node.keywords:
                if kw.arg != "update" or not isinstance(kw.value, ast.Dict):
                    continue
                for key, value in zip(kw.value.keys, kw.value.values, strict=True):
                    if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
                        raw_literals.append(f"{key.value}={value.value}")
    assert any("bot_meme_api_output_dir" in item for item in raw_literals), (
        f"烟测不再合并 bot_meme_api_output_dir（现读={raw_literals}）＝本锁靶子迁移，同步尺"
    )


def test_hot_path_extra_remap_pass_is_a_verified_noop(tmp_path: Path) -> None:
    """实测（不是引用「幂等」那句话）：热路径连过三次合并，名册读数逐字不变。

    ``_config_with_runtime_overrides`` 的调用点在 ``__init__.py`` 里是**每轮判定**的
    热路径（装配期注入的 settings_provider 每消息求值），接线多一刀的风险＝改动别的
    名册键或每次换落点。这里喂满全部热键连调三次，拿整张名册（66 键含列表摊平）对拍。
    """
    data_root = tmp_path / "runtime_data"
    config = Config(bot_runtime_data_dir=str(data_root))
    baseline = _roster_values(config)
    assert baseline, "名册读空＝本判据是假绿"
    settings = _StubRuntimeSettings({key: "sentinel-value" for key in _hot_override_env_keys()})

    once = bot_root_pkg._config_with_runtime_overrides(config, settings)
    twice = bot_root_pkg._config_with_runtime_overrides(once, settings)
    thrice = bot_root_pkg._config_with_runtime_overrides(twice, settings)
    assert _roster_values(once) == baseline, "多一次重映射改动了名册读数＝热路径行为变了"
    assert _roster_values(twice) == baseline
    assert _roster_values(thrice) == baseline


def test_merge_site_reuses_helper_on_copy_not_shared_config(tmp_path: Path) -> None:
    """无覆盖的两条早退路必须**原对象返回、零 setattr**：生产 Config 是共享单例，就地改它＝跨会话污染。"""
    data_root = tmp_path / "runtime_data"
    config = Config(bot_runtime_data_dir=str(data_root))
    baseline = _roster_values(config)

    assert bot_root_pkg._config_with_runtime_overrides(config, None) is config
    assert bot_root_pkg._config_with_runtime_overrides(config, _StubRuntimeSettings({})) is config
    empty = _StubRuntimeSettings({key: "" for key in _hot_override_env_keys()})
    assert bot_root_pkg._config_with_runtime_overrides(config, empty) is config
    same = _StubRuntimeSettings(
        {key: getattr(config, field) for key, field in bot_root_pkg._RUNTIME_HOT_OVERRIDE_FIELDS}
    )
    assert bot_root_pkg._config_with_runtime_overrides(config, same) is config

    assert _roster_values(config) == baseline, "早退路把生产 Config 改了＝共享对象被就地污染"

