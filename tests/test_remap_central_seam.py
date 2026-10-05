"""中央缝回归（台账 P1 H-1／F-10）：名册路径字段的落点**只可能**是被重映射后的那一枚。

现场三次（10-02 的 ``data/control_plane_config.sqlite3``、10-04 23:28 与 10-05 10:44 的
``data/addressing_preferences.sqlite3``）都是同一族：源码树在全量测试期间长出运行库。
归因已在 10-05 由反查席纠正一次——``bot_addressing_preferences_db_path`` **本来就在**
``PATH_REMAPPED_FIELDS``（``config.py:141``，表起 ``:82``），"补一张册子"＝补一张不缺的册子。

真缺口＝**"数据根"这个概念有两把尺**：

* ``scripts/runtime_paths.runtime_data_dir()`` 读 env→dotenv→缺省，且被 ``tests/conftest.py``
  的 L1 装配挤成隔离根；
* ``config.runtime_data_root_of()`` 只读 pydantic 字段值，字段没被喂就是字面 ``"data"``，
  硬锚仓根 ⇒ 整张名册折进**源码树**（装载期校验器确实在跑，跑的是错的锚点）。

本文件按"读侧不可能拿到未重映射的值"执法，各枚锁咬一条腿：

① ``test_bare_config_store_never_writes_source_tree_data``——最可信的一条：跑完这条测试
   源码树 ``data/`` 里必须一枚新文件都没有（量具＝``conftest._snapshot``，G1 守卫**自己**
   那把尺，不另造）；
② ``test_default_data_root_of_bare_config_is_the_central_env_aware_root``——两把尺同源；
③ ``test_roster_fields_of_a_bare_config_never_land_in_source_tree``——整张名册逐字段过；
④ ``test_the_two_read_points_share_one_resolution`` +
   ``test_no_hardcoded_default_path_in_the_consuming_legs``——``content_route`` 的门与
   ``providers`` 的 store 取径共用同一处解析，不许各写一份、不许留第二真身；
⑤ ``test_undeclared_field_names_no_landing_for_both_read_points``——字段没声明时两处**同一句
   话**（不许一处说"没这本库"、另一处按硬编码缺省去开它）；
⑥ 反向方向锁 ``test_production_default_semantics_unchanged_when_nothing_declared``：
   没有任何声明时缺省落点仍逐字是 ``<仓根>/data``＝字段缺省语义一字未动。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import conftest  # 复用 G1 守卫自己的快照尺（本文件不另造一把）
import pytest

from plugins.bot_unified_runtime import config as config_module
from plugins.bot_unified_runtime.config import (
    PATH_REMAPPED_FIELDS,
    Config,
    runtime_data_root_of,
)
from scripts import runtime_paths

PROJECT_ROOT = conftest.REPO_ROOT
SOURCE_TREE_DATA = PROJECT_ROOT / "data"

ADDRESSING_FIELD = "bot_addressing_preferences_db_path"
ADDRESSING_DEFAULT_NAME = "addressing_preferences.sqlite3"

CONTENT_ROUTE_SOURCE = "plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py"
PROVIDERS_SOURCE = "plugins/bot_unified_runtime/domains/chat_reply/character/providers.py"


def _bare_config(**overrides: object) -> Config:
    """与事故件 ``tests/test_chat_file_modify_intent.py::_conf`` 逐字同形的构造点。

    只覆两枚与称谓库无关的键、**不给数据根**——这正是"真 ``Config`` 走缺省"的唯一形状：
    生产装载链（``__init__.py:4199`` ``Config.model_validate(translate_env_keys(...))``）
    会把 ``BOT_RUNTIME_DATA_DIR`` 喂进来，测试树里没人喂。
    """
    base: dict[str, object] = {
        "bot_download_dir": "data/dl",
        "bot_files_write_allowed_dirs": ["data/out"],
    }
    base.update(overrides)
    return Config(**base)  # type: ignore[arg-type]


def _legs() -> tuple[object, object]:
    from plugins.bot_unified_runtime.domains.chat_reply.character import providers
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import content_route

    return content_route, providers


# ---------------------------------------------------------------------------
# ① 主锁：跑完这条测试，源码树 data/ 里不许多出一枚文件
# ---------------------------------------------------------------------------


def test_bare_config_store_never_writes_source_tree_data() -> None:
    content_route, providers = _legs()
    before = conftest._snapshot()
    config = _bare_config()

    store = content_route._explicit_pin_store(config)
    also = providers.build_addressing_preference_store(config)

    fresh = sorted(conftest._snapshot() - before)
    assert not fresh, (
        f"本条测试往源码树 data/ 写了 {fresh}（AGENTS 规则 2/6）——"
        f"称谓库落点＝{getattr(store, '_path', None)}"
    )
    assert store is not None, "真 Config 点名了称谓库却拿不到 store＝腿自己断了"
    landing = Path(store._path)  # type: ignore[attr-defined]
    assert SOURCE_TREE_DATA not in landing.parents, f"落点在源码树：{landing}"
    # 两处读点必须回到**同一只桶**（providers 那族按路径字符串缓存）。
    assert also is store, "门与 store 各建各的＝两把尺已经分叉"


# ---------------------------------------------------------------------------
# ② 两把尺同源：Config 缺省锚点 == runtime_paths 的中央数据根
# ---------------------------------------------------------------------------


def test_default_data_root_of_bare_config_is_the_central_env_aware_root() -> None:
    """字段没被喂时，config 侧的锚点必须交中央出口算，不许在 config.py 里再算一遍。"""
    config = _bare_config()
    assert runtime_data_root_of(config) == runtime_paths.runtime_data_dir(), (
        "两把尺分叉：config 侧锚点与 scripts.runtime_paths 的数据根不是同一枚 ⇒ "
        "名册整批折进源码树（10-02/10-04/10-05 三次现场的同一条根因）"
    )


def test_explicit_absolute_data_root_still_wins(tmp_path: Path) -> None:
    """显式给了绝对根 ⇒ 逐字用它（本次修法不许把显式配置盖过去）。"""
    declared = tmp_path / "explicit_root"
    config = _bare_config(bot_runtime_data_dir=str(declared))
    assert runtime_data_root_of(config) == declared
    assert Path(config.bot_addressing_preferences_db_path) == declared / ADDRESSING_DEFAULT_NAME


def test_explicit_relative_data_root_keeps_its_own_tail() -> None:
    """显式给了**非缺省**的相对根 ⇒ 仍按仓根拼它自己的尾巴，不并被中央出口。

    这条防的是"顺手把整条相对腿都交出去"那种过头修法：只有没给根（空串/正缺省那枚
    ``data``）才问中央出口，别的相对读数形状必须逐字保持今天的行为。
    """
    config = _bare_config(bot_runtime_data_dir="data/side_root")
    assert runtime_data_root_of(config) == PROJECT_ROOT / "data" / "side_root"


# ---------------------------------------------------------------------------
# ③ 整张名册逐字段：缺省 Config 的任何一个落点都不许在源码树
# ---------------------------------------------------------------------------


def test_roster_fields_of_a_bare_config_never_land_in_source_tree() -> None:
    config = _bare_config()
    offenders: list[str] = []
    for name in PATH_REMAPPED_FIELDS:
        raw = str(getattr(config, name, "") or "").strip()
        if not raw:
            continue
        value = runtime_paths.runtime_path(raw).resolve()
        if value == SOURCE_TREE_DATA or SOURCE_TREE_DATA in value.parents:
            offenders.append(f"{name}={value}")
    assert not offenders, "以下名册字段折进了源码树 data/：" + "; ".join(offenders)


# ---------------------------------------------------------------------------
# ④ 读侧唯一解析：两处读点共用同一处，不许各写一份
# ---------------------------------------------------------------------------


def test_the_two_read_points_share_one_resolution(tmp_path: Path, monkeypatch) -> None:
    if not hasattr(config_module, "resolve_runtime_data_field"):
        pytest.fail("config.py 没有 resolve_runtime_data_field ⇒ 读侧唯一解析口未立")
    from plugins.bot_unified_runtime.config import resolve_runtime_data_field

    content_route, providers = _legs()
    config = _bare_config(bot_runtime_data_dir=str(tmp_path))

    expected = resolve_runtime_data_field(config, ADDRESSING_FIELD)
    assert expected == str(tmp_path / ADDRESSING_DEFAULT_NAME), (
        f"中央读取口没按数据根重映射：{expected!r}"
    )

    store = providers.build_addressing_preference_store(config)
    assert store is not None
    assert Path(store._path) == runtime_paths.runtime_path(expected)  # type: ignore[attr-defined]

    # 门与 store 读的必须是**同一把尺**：把中央读取口换成"这枚配置没点库"，两处都必须整条腿消失。
    monkeypatch.setattr(config_module, "resolve_runtime_data_field", lambda *_a, **_k: "")
    assert content_route._explicit_pin_store(config) is None, (
        "门还在自己裸 getattr 判空＝第二份解析还在"
    )
    assert providers.build_addressing_preference_store(config) is None, (
        "store 取径还在自带缺省＝第二份解析还在"
    )


def test_the_gate_itself_asks_the_central_reader(tmp_path: Path, monkeypatch) -> None:
    """门必须**自己**问中央读取口——不许把"点没点这本库"这件事转嫁给 store 取径的回答。

    这条是 ④ 的牙：光断言"两处都休眠"是可以被转嫁糊过去的（门放行、store 那侧返回
    None，结果照样是 None＝假绿形态），所以这里把 store 取径换成哨兵，只问一句
    "门到底调没调它"。
    """
    if not hasattr(config_module, "resolve_runtime_data_field"):
        pytest.fail("config.py 没有 resolve_runtime_data_field ⇒ 读侧唯一解析口未立")
    content_route, providers = _legs()
    config = _bare_config(bot_runtime_data_dir=str(tmp_path))
    calls: list[int] = []

    def _sentinel(_cfg: object) -> str:
        calls.append(1)
        return "SENTINEL"

    monkeypatch.setattr(providers, "build_addressing_preference_store", _sentinel)

    monkeypatch.setattr(config_module, "resolve_runtime_data_field", lambda *_a, **_k: "")
    assert content_route._explicit_pin_store(config) is None
    assert calls == [], "中央读取口说没点库，门却仍把活计转给 store 取径＝门没接这把尺，还在自己判"

    monkeypatch.setattr(
        config_module,
        "resolve_runtime_data_field",
        lambda _cfg, _field: str(tmp_path / ADDRESSING_DEFAULT_NAME),
    )
    assert content_route._explicit_pin_store(config) == "SENTINEL"
    assert calls == [1], "读取口点名了库，门却把整条腿关着＝门读的不是同一把尺"


def test_no_hardcoded_default_path_in_the_consuming_legs() -> None:
    """两处读点不许再抄一份字段缺省字符串（第二真身）。"""
    needle = f"data/{ADDRESSING_DEFAULT_NAME}"
    for relative in (CONTENT_ROUTE_SOURCE, PROVIDERS_SOURCE):
        source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert needle not in source, f"{relative} 里还留着硬编码缺省落点＝第二真身"


def _called_names(func: object) -> set[str]:
    """函数体里真被**调用**的名字——只认 ``ast.Call`` 结点。

    用 ``inspect.getsource`` 做子串比法会被函数自己的文档字符串喂饱（本仓在册病：
    护栏写完即空转）。注释/文档里提一次名字不等于接了线，判据必须看调用。
    """
    tree = ast.parse(inspect.getsource(func))  # type: ignore[arg-type]
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def test_both_read_points_consult_the_central_reader() -> None:
    """接线锁：两处取径都真的**调用**中央读取口（缺一处＝还有第二份解析）。"""
    if not hasattr(config_module, "resolve_runtime_data_field"):
        pytest.fail("config.py 没有 resolve_runtime_data_field ⇒ 读侧唯一解析口未立")
    from plugins.bot_unified_runtime.domains.chat_reply.character import providers
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import content_route

    assert "resolve_runtime_data_field" in _called_names(content_route._explicit_pin_store), (
        f"{CONTENT_ROUTE_SOURCE}::_explicit_pin_store 没调用中央读取口（只提了名字不算接线）"
    )
    assert "resolve_runtime_data_field" in _called_names(
        providers._shared_addressing_preferences
    ), f"{PROVIDERS_SOURCE}::_shared_addressing_preferences 没调用中央读取口"


# ---------------------------------------------------------------------------
# ⑤ 字段没声明时两处说同一句话
# ---------------------------------------------------------------------------


def test_undeclared_field_names_no_landing_for_both_read_points(tmp_path: Path) -> None:
    if not hasattr(config_module, "resolve_runtime_data_field"):
        pytest.fail("config.py 没有 resolve_runtime_data_field ⇒ 读侧唯一解析口未立")
    from plugins.bot_unified_runtime.config import resolve_runtime_data_field

    content_route, providers = _legs()
    monkey = SimpleNamespace(bot_runtime_data_dir=str(tmp_path))  # 没有那枚字段

    assert resolve_runtime_data_field(monkey, ADDRESSING_FIELD) == ""
    assert providers.build_addressing_preference_store(monkey) is None
    assert content_route._explicit_pin_store(monkey) is None


# ---------------------------------------------------------------------------
# 反向方向锁：生产缺省语义一字不许被这次修法改动
# ---------------------------------------------------------------------------


def test_production_default_semantics_unchanged_when_nothing_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """既无 env 也无 dotenv 声明时，缺省数据根仍逐字是 ``<仓根>/data``。

    这条是"没改字段缺省语义"的证据：摘掉测试隔离标记（＝复现非测试进程）、把 dotenv
    读数屏蔽成空，中央出口与 config 侧锚点必须**同时**回到仓根。
    """
    monkeypatch.delenv(runtime_paths.TEST_PROCESS_ENV, raising=False)
    monkeypatch.delenv(runtime_paths.RUNTIME_DATA_DIR_ENV, raising=False)
    monkeypatch.delenv(runtime_paths.TEST_FORBIDDEN_ROOTS_ENV, raising=False)
    monkeypatch.setattr(runtime_paths, "_dotenv_value", lambda _key: "")

    assert runtime_paths.runtime_data_dir() == (PROJECT_ROOT / "data").resolve()
    assert runtime_data_root_of(_bare_config()) == (PROJECT_ROOT / "data").resolve()
