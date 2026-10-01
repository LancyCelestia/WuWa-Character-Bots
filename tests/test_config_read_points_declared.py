"""幽灵配置读点门：代码读 `config.bot_xxx` 而 `Config` 类没这个字段 ⇒ 一律现形。

为什么立这把门：`getattr(cfg, "bot_x", 缺省)` 的宽容缺省会把"键没声明"变成**静默失效**——
`.env` 里写 `BOT_X=false` 被 pydantic `extra='ignore'` 默默丢掉，读点永远拿到缺省，全程零报错、测试全绿。
先例＝2026-09-21 Wave G 的 sync_drift 事故（七枚键读空 ⇒ 巡检器永不注册）；本门是它的镜像面常驻体检。

判据（双向活性）：真树幽灵集合 **恰好等于** 本文件登记面。
新增未登记 ⇒ 红；登记项被修掉后赖在清单里 ⇒ 也红（逼清单跟真值同步）。

零副作用：只做 AST 静态解析 + `spec_from_file_location` 直载 config.py（不 import 包 `__init__`、
不 import nonebot、不读生产 `.env`、不写任何文件）。
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from scripts.config_read_point_census import (  # 判据单一真身：门不另写一份扫描逻辑
    CONFIG_PY,
    DEFAULT_SCOPES,
    NON_PLUGIN_CONFIG_RECEIVERS,
    REPO,
    config_fields,
    dynamic_key_points,
    excluded_receiver_points,
    ghost_read_points,
)

# ---------------------------------------------------------------------------
# 登记面（＝2026-09-22 S-PHANTOM 席普查实测，键名+文件为身份，行号只作人读）
# 销账记录：本波主会话给 8 个读点（7 枚键：cookie 提醒开关、视频深挖冷却、
# 运势密钥×2、订阅 outbox 四枚）补上了 Config 字段，缺省逐枚等于原 getattr 缺省
# ⇒ 现网零行为变更，登记项随之删除（留着本门会红，那是它设计的用途，不是例外）。
# 2026-09-25（B1 网关归因波）再销一枚：`bot_llm_billing_enabled` 已在 config.py
# 声明为真字段（缺省 False＝历史行为逐字节一致）。它不是"看着没人读"而是
# **读得到但 .env 进不来**——生产 os.environ 不含 BOT_*（NoneBot dotenv 只把
# 已声明字段落进 Config），所以账本开关此前**无论 .env 写什么都不生效**。
# 形态清一色是 getattr 带宽容缺省；note 记的是"不设字段会怎样"，供裁定补字段还是改读点。
# ---------------------------------------------------------------------------
GHOST = "plugins/bot_unified_runtime/"
REGISTERED_GHOSTS: dict[tuple[str, str], str] = {
    (GHOST + "domains/chat_reply/llm_engine/channel_health.py", "bot_channel_health_latency_first"):
        "缺省 None 后紧跟裸 os.environ 兜底 ⇒ env 面活、Config 校验面死",
    (GHOST + "domains/chat_reply/llm_engine/model_router.py", "bot_llm_model_price_overrides"):
        "缺省 None ⇒ 逐模型改价覆盖不可用，:396 注释的承诺是假的（他席审计 F-14 同指）",
    (GHOST + "domains/divination/store/draw_store.py", "bot_control_plane_divination_db"):
        "缺省 None ⇒ draw_store_from_config 恒 None ⇒ 聊天侧从未拿到收编后实例（现网跑 rng.sample 老路径）",
    # 〔2026-09-29 复原波销账一枚〕原登记 (emergency_info.py, bot_emergency_info_quiet_breach_levels)
    # 的幽灵条件已消失：他席把该键真补进了 config.py 字段（＋.env.example 申报行），读点不再是
    # 「键不在 Config 上」那种死路 ⇒ 按本门口径「补 Config 字段后从清单删」摘除。摘前的现算证据：
    # test_ghost_read_points_exactly_match_registry 的第二腿报「登记项 real 集里没有」正是这一枚。
    (GHOST + "domains/food/capabilities/eat.py", "bot_food_image_dir"):
        "缺省 '' 由下游兜到 data/food_images ⇒ 与 scripts 那处缺省不一致（补字段须连带裁定）",
    (GHOST + "domains/media/registry/media_registry.py", "bot_media_registry_ttl_seconds"):
        "缺省=模块常量；在册的近亲键是 bot_media_registry_ttl_days（单位不同）⇒ 注释承诺的覆盖是空的",
    (GHOST + "domains/media/registry/media_registry.py", "bot_media_registry_max_rows"):
        "缺省=模块常量 ⇒ 行数上限不可调",
    ("scripts/clean_food_gallery.py", "bot_food_image_dir"):
        "同一枚幽灵键的第二缺省 'data/food_images' ⇒ 与 eat.py 的 '' 打架",
}

FAKE_CONFIG_SRC = "class Config(BaseModel):\n    bot_real_flag: bool = True\n"


def _tree_identities() -> set[tuple[str, str]]:
    return {(g["file"], g["key"]) for g in ghost_read_points()}


def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, consumer_src: str) -> set[tuple[str, str]]:
    """把扫描器指到 tmp 合成树：注毒自证用，绝不碰真树。"""
    pkg = tmp_path / "plugins" / "bot_unified_runtime"
    pkg.mkdir(parents=True)
    cfg = pkg / "config.py"
    cfg.write_text(FAKE_CONFIG_SRC, encoding="utf-8")
    (pkg / "consumer.py").write_text(consumer_src, encoding="utf-8")
    import scripts.config_read_point_census as census

    monkeypatch.setattr(census, "REPO", tmp_path)
    monkeypatch.setattr(census, "CONFIG_PY", cfg)
    return {(g["file"], g["key"]) for g in census.ghost_read_points(["plugins"])}


def test_config_field_source_agrees_with_pydantic_truth() -> None:
    """AST 字段集与真 Config.model_fields 必须一致——否则本门的判据根基就是歪的。"""
    spec = importlib.util.spec_from_file_location("_config_under_phantom_gate", CONFIG_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = module.Config
    cls.model_rebuild(_types_namespace=vars(module))  # 不 rebuild 则 pydantic 拒绝装载
    assert set(config_fields()) == set(cls.model_fields), "AST 与 pydantic 的字段真值分叉，先修扫描器"


def test_ghost_read_points_exactly_match_registry() -> None:
    """双向：真树多出来的幽灵=未登记；登记里赖着的=已修掉没销账。"""
    real = _tree_identities()
    registered = set(REGISTERED_GHOSTS)
    assert real - registered == set(), "新增未登记幽灵读点（补 Config 字段或改读点，二选一后销账）"
    assert registered - real == set(), "登记项已不在真树（幽灵被修掉了，从清单删掉，别让它烂成假账）"


def test_registry_notes_are_not_empty() -> None:
    assert all(note.strip() for note in REGISTERED_GHOSTS.values())


def test_poison_attribute_form_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hits = _sandbox(tmp_path, monkeypatch, "def f(cfg):\n    return cfg.bot_ghost_x\n")
    assert hits == {("plugins/bot_unified_runtime/consumer.py", "bot_ghost_x")}


def test_poison_literal_getattr_form_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hits = _sandbox(tmp_path, monkeypatch, "def f(cfg):\n    return getattr(cfg, \"bot_ghost_y\", 0)\n")
    assert hits == {("plugins/bot_unified_runtime/consumer.py", "bot_ghost_y")}


def test_poison_module_constant_key_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """键名藏进模块常量也要抓到——否则 `getattr(cfg, SOME_KEY)` 全是盲区。"""
    hits = _sandbox(
        tmp_path, monkeypatch,
        'K = "bot_ghost_z"\n\n\ndef f(cfg):\n    return getattr(cfg, K, "")\n',
    )
    assert hits == {("plugins/bot_unified_runtime/consumer.py", "bot_ghost_z")}


def test_poison_stale_registration_direction_goes_red(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """幽灵被修掉后清单还在 ⇒ 必须红（沙箱里演示：真值空、登记非空 ⇒ 差集非空）。"""
    real = _sandbox(tmp_path, monkeypatch, "def f(cfg):\n    return cfg.bot_real_flag\n")
    assert real == set()
    assert set(REGISTERED_GHOSTS) - real, "登记面必须非空，否则本门的『赖账』方向永不被执行"


def test_fstring_dynamic_key_is_never_a_ghost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负样本：f-string 拼出来的键名不可静态判定，判成幽灵就是误伤（门会被下个 AI 调松）。"""
    hits = _sandbox(
        tmp_path, monkeypatch,
        'def f(cfg, name):\n    return getattr(cfg, f"bot_dyn_{name}_enabled", False)\n',
    )
    assert hits == set()


def test_dynamic_key_sites_are_declared_not_silently_dropped() -> None:
    """不可判定的读点得数出来：f-string 前缀集变了就说明有新动态键，人工确认别漏判成幽灵。"""
    templates = {d["template"] for d in dynamic_key_points() if d["template"].startswith("bot_")}
    assert {"bot_web_search_", "bot_subscribe_platform_", "bot_search_acg_"} <= templates, (
        "f-string 动态键前缀集合变了：更新本清单并确认新前缀不是漏判幽灵"
    )


def test_non_plugin_config_receivers_are_excluded_but_alive() -> None:
    """排除表不得烂成藏污所：每条都还得在真树命中，且它们名下的读点确实不算幽灵。"""
    assert NON_PLUGIN_CONFIG_RECEIVERS
    live = {(e["file"], e["recv"]) for e in excluded_receiver_points()}
    assert set(NON_PLUGIN_CONFIG_RECEIVERS) <= live, "排除项已不命中真树，删掉它（它不再保护任何东西）"
    assert (GHOST + "domains/ops/integrations/gscore_bridge.py", "bot_id") not in _tree_identities()
    assert ("bot.py", "bot_runtime_data_dir") not in _tree_identities()


def test_attribute_form_ghosts_are_zero_by_design() -> None:
    """属性式读缺失字段会 AttributeError（响）；本病只长在 getattr 的宽容缺省上。"""
    attr_ghosts = [g for g in ghost_read_points() if "attribute" in g["forms"]]
    assert attr_ghosts == [], f"出现属性式幽灵读点（会崩，不是静默失效）：{attr_ghosts}"


def test_gate_scans_production_scope_only() -> None:
    """范围声明：tests/** 里也有 getattr(config, "bot_x")，那些是断言缺省的假绿，另案归 owner。"""
    assert set(DEFAULT_SCOPES) == {"plugins", "scripts", "bot.py"}
    assert (REPO / "plugins" / "bot_unified_runtime" / "config.py").is_file()
    assert isinstance(ast.parse(FAKE_CONFIG_SRC), ast.Module)
