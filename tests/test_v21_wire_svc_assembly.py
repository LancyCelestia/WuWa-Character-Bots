"""V2.1 B2① 服务装配组接线测试（WIRE-SVC 席，V21-WORLD/KB/DB/TEACH-001）。

覆盖（全离线 tmp_path/:memory: 隔离、零网络、零 Runtime 写入）：
- 门语义：主门 ``bot_v21_service_wiring_enabled`` 缺省关 ⇒ 全组缺省零装配
  零副作用（真实 ``Config()`` 默认值 + stub 门矩阵两路断言）；
- 门开装配：四服务各自由既有 builder 产出正确实例且写入注册表可查；
- 分门独立：主门开、单分门关 ⇒ 仅该服务缺席；
- fail-open：单服务装配异常 ⇒ 该服务缺席、其余照常注册；
- 根装配点静态断言：根 ``__init__.py`` 存在主门门控 ``register_v21_services``
  插入段（同门同名，防以后被静默移除/改门）；
- L41（memory）：注册表 id 全集不含 memory（裁决前不接的常驻锁）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.chat_reply.character.knowledge_service import (
    KnowledgeService,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.teaching_service import (
    TeachingService,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.worldbook_service import (
    WorldbookService,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.database_broker import (
    DatabaseBroker,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.service_wiring import (
    V21_SERVICE_WIRING_IDS,
    build_v21_services,
    get_v21_service,
    register_v21_services,
    reset_v21_services,
    v21_service_gates,
    v21_service_ids,
)

ROOT = Path(__file__).resolve().parents[1]
INIT_PY = ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_v21_services()
    yield
    reset_v21_services()


def _broker_db_keys() -> set[str]:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.database_broker import (
        build_default_registry,
    )

    return {spec.db for spec in build_default_registry().values()}


def _stub_config(**overrides: object) -> SimpleNamespace:
    # 注意：teaching/broker 分门在此缺省 False（仅为让单服务测试最小化），
    # 真实 Config() 的这两个既有键缺省 True——由
    # test_real_config_defaults_keep_wiring_off 与
    # test_master_gate_on_respects_per_service_gates 分别钉住。
    gates = {
        "bot_v21_service_wiring_enabled": False,
        "bot_worldbook_enabled": False,
        "bot_knowledge_service_enabled": False,
        "bot_database_broker_enabled": False,
        "bot_teaching_enabled": False,
        "bot_teaching_db_path": "data/teaching_knowledge.sqlite3",
    }
    gates.update(overrides)
    return SimpleNamespace(**gates)


# ------------------------------------------------- 门语义：缺省=关


def test_real_config_defaults_keep_wiring_off() -> None:
    config = Config()
    assert config.bot_v21_service_wiring_enabled is False
    assert config.bot_worldbook_enabled is False
    assert config.bot_knowledge_service_enabled is False
    # 既有 S8 分门键保持原缺省（主门关时不生效，语义不变）。
    assert config.bot_teaching_enabled is True
    assert config.bot_database_broker_enabled is True


def test_master_gate_off_means_zero_assembly(tmp_path: Path) -> None:
    # 分门全开但主门关 ⇒ 零装配零副作用（tmp_path 不落任何文件）。
    config = _stub_config(
        bot_v21_service_wiring_enabled=False,
        bot_worldbook_enabled=True,
        bot_knowledge_service_enabled=True,
    )
    assert v21_service_gates(config) == {
        "worldbook": False,
        "knowledge": False,
        "database_broker": False,
        "teaching": False,
    }
    built = build_v21_services(config, worldbook_db_path=tmp_path / "wb.sqlite3")
    assert built == {}
    assert list(tmp_path.iterdir()) == []
    assert v21_service_ids() == ()


def test_master_gate_on_respects_per_service_gates() -> None:
    config = _stub_config(
        bot_v21_service_wiring_enabled=True,
        bot_worldbook_enabled=True,
        bot_knowledge_service_enabled=False,
        # 既有 S8 键的真实缺省是 True（见 test_real_config_defaults_keep_
        # wiring_off）；主门开时这两个 True 直接生效=复用语义成立。
        bot_teaching_enabled=True,
        bot_database_broker_enabled=True,
    )
    gates = v21_service_gates(config)
    assert gates["worldbook"] is True
    assert gates["knowledge"] is False
    assert gates["teaching"] is True
    assert gates["database_broker"] is True


# ------------------------------------------------- 门开：装配+注册表可查


def test_worldbook_wired_into_registry(tmp_path: Path) -> None:
    config = _stub_config(
        bot_v21_service_wiring_enabled=True, bot_worldbook_enabled=True
    )
    registered = register_v21_services(
        config, worldbook_db_path=tmp_path / "wb.sqlite3"
    )
    assert set(registered) == {"worldbook"}
    service = get_v21_service("worldbook")
    assert isinstance(service, WorldbookService)


def test_knowledge_wired_with_explicit_store(tmp_path: Path) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
        SqliteVectorKnowledgeStore,
    )

    config = _stub_config(
        bot_v21_service_wiring_enabled=True, bot_knowledge_service_enabled=True
    )
    store = SqliteVectorKnowledgeStore(
        ":memory:", embed_provider=SimpleNamespace(signature="stub")
    )
    registered = register_v21_services(
        config, knowledge_stores=[("persona", store)]
    )
    assert set(registered) == {"knowledge"}
    assert isinstance(get_v21_service("knowledge"), KnowledgeService)
    assert list(tmp_path.iterdir()) == []  # :memory: 库零落盘


def test_database_broker_wired_with_whitelisted_registry(
    tmp_path: Path,
) -> None:
    config = _stub_config(
        bot_v21_service_wiring_enabled=True, bot_database_broker_enabled=True
    )
    db_paths = {
        key: str(tmp_path / f"{key}.sqlite3") for key in _broker_db_keys()
    }
    registered = register_v21_services(
        config, broker_database_paths=db_paths
    )
    assert set(registered) == {"database_broker"}
    broker = get_v21_service("database_broker")
    assert isinstance(broker, DatabaseBroker)
    assert set(broker.query_ids()) == {
        "queue.depth",
        "affinity.distribution",
        "ledger.daily",
        "audit.recent",
        "subscriptions.status",
    }
    assert list(tmp_path.iterdir()) == []  # 懒打开：装配期零库文件


def test_teaching_wired_with_injected_db_path(tmp_path: Path) -> None:
    config = _stub_config(
        bot_v21_service_wiring_enabled=True,
        bot_teaching_enabled=True,
        bot_teaching_db_path=str(tmp_path / "teaching.sqlite3"),
    )
    registered = register_v21_services(config)
    assert set(registered) == {"teaching"}
    assert isinstance(get_v21_service("teaching"), TeachingService)
    # TeachingService 构造即建 schema（急切），库文件必须落在注入路径。
    assert (tmp_path / "teaching.sqlite3").exists()


def test_all_four_services_registered_together(tmp_path: Path) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
        SqliteVectorKnowledgeStore,
    )

    config = _stub_config(
        bot_v21_service_wiring_enabled=True,
        bot_worldbook_enabled=True,
        bot_knowledge_service_enabled=True,
        bot_database_broker_enabled=True,
        bot_teaching_enabled=True,
        bot_teaching_db_path=str(tmp_path / "teaching.sqlite3"),
    )
    store = SqliteVectorKnowledgeStore(
        ":memory:", embed_provider=SimpleNamespace(signature="stub")
    )
    db_paths = {
        key: str(tmp_path / f"{key}.sqlite3") for key in _broker_db_keys()
    }
    registered = register_v21_services(
        config,
        worldbook_db_path=tmp_path / "wb.sqlite3",
        knowledge_stores=[("persona", store)],
        broker_database_paths=db_paths,
    )
    assert set(registered) == set(V21_SERVICE_WIRING_IDS)
    assert sorted(v21_service_ids()) == sorted(V21_SERVICE_WIRING_IDS)
    # L41 常驻锁：memory 裁决前绝不出现在注册表。
    assert "memory" not in v21_service_ids()
    assert get_v21_service("memory") is None
    assert get_v21_service("unknown-id") is None


# ------------------------------------------------- 分门独立 + fail-open


def test_single_service_gate_off_only_excludes_it(tmp_path: Path) -> None:
    config = _stub_config(
        bot_v21_service_wiring_enabled=True,
        bot_worldbook_enabled=True,
        bot_knowledge_service_enabled=True,
        bot_database_broker_enabled=True,
        bot_teaching_enabled=False,
    )
    store_db = tmp_path / "k.sqlite3"
    from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
        SqliteVectorKnowledgeStore,
    )

    built = build_v21_services(
        config,
        worldbook_db_path=tmp_path / "wb.sqlite3",
        knowledge_stores=[
            (
                "persona",
                SqliteVectorKnowledgeStore(
                    str(store_db),
                    embed_provider=SimpleNamespace(signature="stub"),
                ),
            )
        ],
        broker_database_paths={
            key: str(tmp_path / f"{key}.sqlite3") for key in _broker_db_keys()
        },
        teaching_db_path=tmp_path / "teaching.sqlite3",
    )
    assert set(built) == {"worldbook", "knowledge", "database_broker"}
    assert "teaching" not in built


def test_single_service_failure_fails_open(tmp_path: Path) -> None:
    blocked = tmp_path / "not_a_dir"
    blocked.write_text("占用路径", encoding="utf-8")
    config = _stub_config(
        bot_v21_service_wiring_enabled=True,
        bot_worldbook_enabled=True,
        bot_teaching_enabled=True,
    )
    built = build_v21_services(
        config,
        worldbook_db_path=tmp_path / "wb.sqlite3",
        teaching_db_path=blocked / "teaching.sqlite3",  # 父级是文件 ⇒ 必炸
    )
    assert "teaching" not in built  # 失败服务被跳过（fail-open）
    assert isinstance(built["worldbook"], WorldbookService)  # 其余照常


def test_register_is_idempotent_and_reset_clears(tmp_path: Path) -> None:
    config = _stub_config(
        bot_v21_service_wiring_enabled=True, bot_worldbook_enabled=True
    )
    first = register_v21_services(
        config, worldbook_db_path=tmp_path / "wb.sqlite3"
    )
    second = register_v21_services(
        config, worldbook_db_path=tmp_path / "wb.sqlite3"
    )
    assert set(first) == set(second) == {"worldbook"}
    reset_v21_services()
    assert v21_service_ids() == ()
    assert get_v21_service("worldbook") is None


# ------------------------------------------------- 根装配点静态断言


def test_root_init_insertion_is_gated_and_calls_register() -> None:
    source = INIT_PY.read_text(encoding="utf-8")
    assert (
        'if getattr(config, "bot_v21_service_wiring_enabled", False):'
        in source
    ), "根装配点必须保留主门门控（缺省关）"
    assert "register_v21_services(config)" in source
