"""T4 渠道能力标签保险（native-*）——三条静默抹标签的路各上一把锁.

被保的东西：注册表 tags 里的 ``native-audio`` / ``native-video`` /
``native-animation`` 三枚**能力标签**。它们决定"音视频/动图原样进模型，还是先
转译"。标签消失时**不报错、不写日志**，媒体理解只是静默退回 ASR/抽帧/拼静态条
——与本轮停摆复盘里"存在性糊过活性判据"同一族形状。

三条会被静默抹掉的路（S28 现算，逐条对锁）：
  ① 重跑 ``scripts/configure_axonhub_registry.py --apply``——脚本自带一张硬编码
     tags 表，整段覆写运行时条目（第二真身）；
  ② ``/bot model update <id> tags=a,b,c``——整表替换，不保留、不提示；
  ③ ``.env`` 出现同名 ``BOT_MODEL_REGISTRY`` 条目——遮蔽运行时 tags，除非
     ``override_fields`` 里显式有 ``tags``。

纪律：断言公共函数/公共对象的输出，不断言"源码里有没有某个字符串"；测试全离线
（不碰生产 ``.env``、不碰运行时注册表 JSON、绝不读密钥值）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine import (
    model_router,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    RuntimeSettingsStore,
)
from plugins.bot_unified_runtime.domains.core import (
    channel_capability_tags as cct,
)
from plugins.bot_unified_runtime.domains.ops.admin import (
    runtime_admin as ra,
)
from scripts import configure_axonhub_registry as car
from scripts import pre_restart_check as prc
from scripts.channel_capability_declaration import (
    load_declaration,
    read_registry_file,
)

PASS, SKIP, FAIL = prc.PASS, prc.SKIP, prc.FAIL

# 声明源里在册的渠道（现算取，不手写 id——手写就是一张新副本）
DECLARED_ID = min(cct.CHANNEL_CAPABILITY_KINDS)
DECLARED_KINDS = tuple(sorted(cct.CHANNEL_CAPABILITY_KINDS[DECLARED_ID]))
DECLARED_TAGS = tuple(f"native-{kind}" for kind in DECLARED_KINDS)
TIER_TAG = "low"


# ---------------------------------------------------------------------------
# 假环境构造（全部落 tmp_path，绝不碰生产文件）
# ---------------------------------------------------------------------------

def make_project(
    tmp_path: Path, *, registry: dict | None, env_registry: str = "", instance: str = "t4"
) -> Path:
    """造一个带运行时注册表与可选 BOT_MODEL_REGISTRY 的假项目根."""
    root = tmp_path / "proj"
    root.mkdir(parents=True)
    data_root = tmp_path / "rt_data"
    (data_root / "settings").mkdir(parents=True)
    lines = [
        f"BOT_RUNTIME_DATA_DIR={data_root}",
        "BOT_RUNTIME_SETTINGS_DIR=data/settings",
        f"BOT_RUNTIME_INSTANCE={instance}",
    ]
    if env_registry:
        lines.append(f"BOT_MODEL_REGISTRY={env_registry}")
    (root / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if registry is not None:
        settings_dir = data_root / "settings"
        path = settings_dir / f"runtime_settings_{instance}.json"
        path.write_text(json.dumps({"model_registry": registry}, ensure_ascii=False), encoding="utf-8")
    return root


def write_registry(root: Path, instance: str, registry: dict) -> Path:
    """把注册表写到该假项目自己的数据根（从它自己的 .env 反解，不猜布局）."""
    data_root = Path(prc.load_env(root)["BOT_RUNTIME_DATA_DIR"])
    path = data_root / "settings" / f"runtime_settings_{instance}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model_registry": registry}, ensure_ascii=False), encoding="utf-8")
    return path


def healthy_entry() -> dict:
    return {
        "model": "gemini-3.8-flash",
        "base_url": "http://127.0.0.1:8090/v1",
        "api_key": "env:BOT_API_KEY_AXONHUB",
        "tags": [TIER_TAG, *DECLARED_TAGS],
        "priority": 1,
        "source": "axonhub",
    }


# ---------------------------------------------------------------------------
# 环境隔离（2026-09-29 席 S-FIX-TAGRP18 补）
#
# `prc.load_env` 自 M-68 收口起与生产 `bot.py` 同构：**os.environ 覆盖 .env 里的
# 同名键**（见 `load_runtime_env_values` 末段）。ambient 里只要挂着
# `BOT_RUNTIME_DATA_DIR`——各席跑测试的卫生前缀必带它——上面 `make_project` 说的话
# 就被整片盖掉：体检项读到的是**环境的数据根**而不是本例的 tmp_path，FAIL/SKIP 腿
# 静默变 PASS＝一把不咬人的锁（2026-09-29 现算：ambient 版 8 红 / 裸环境版 25 绿）。
# 更坏的一面：`write_registry` 经 `load_env` 反解落点，于是把夹具注册表**写进那个
# 数据根**（生产 `.env` 的缺省落点＝ChatBot_Runtime/settings/），一枚
# `runtime_settings_shorekeeper.json` 就能把之后每一轮的判定钉成"健康"——跨进程、
# 跨席位互相污染。environ 只覆盖"文件里出现的键"，故把这几枚摘掉即**充分**。
# 键名从构造器自己的输出反解，不手写第二份清单（手写就是会过期的副本）。
# ---------------------------------------------------------------------------

def _keys_the_fake_env_writes() -> tuple[str, ...]:
    """本文件假 `.env` 写了哪几枚键——现算取，唯一真身＝`make_project` 的产物.

    两种构造形态都要过：`BOT_MODEL_REGISTRY` 只在传了 `env_registry` 时才落进
    .env（漏了它，ambient 的 BOT_MODEL_REGISTRY 会整片盖掉路 ③ 那两条遮蔽腿——
    2026-09-29 本席拿一枚假 `BOT_MODEL_REGISTRY` 当注毒实测，正是这条先红）。
    """
    import tempfile

    variants = (
        {"registry": None},
        {"registry": None, "env_registry": "{}"},
    )
    with tempfile.TemporaryDirectory() as td:
        keys: set[str] = set()
        for index, kwargs in enumerate(variants):
            keys |= set(prc.load_env(make_project(Path(td) / f"probe{index}", **kwargs)))
    return tuple(sorted(keys))


_ENV_KEYS_TO_SCRUB = _keys_the_fake_env_writes()


@pytest.fixture(autouse=True)
def hermetic_fake_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每例把假 `.env` 会写的那几枚键从 os.environ 摘掉（monkeypatch 自动还原）."""
    for key in _ENV_KEYS_TO_SCRUB:
        monkeypatch.delenv(key, raising=False)


def run_check(root: Path) -> prc.CheckResult:
    return prc.check_channel_capability_tags(prc.load_env(root), root)


# ===========================================================================
# 路 0：一处真身——脚本读到的声明与运行时 import 到的声明必须同一份
# ===========================================================================

def test_script_view_and_runtime_view_of_the_declaration_are_identical() -> None:
    """AST 读出来的声明 == 运行时 import 的声明（否则"一处真身"是空话）."""
    view = load_declaration(PROJECT_ROOT)
    assert view.native_prefix == cct.NATIVE_TAG_PREFIX
    assert view.kinds_by_entry == {
        entry_id: tuple(sorted(kinds))
        for entry_id, kinds in cct.CHANNEL_CAPABILITY_KINDS.items()
    }
    assert view.known_kinds == tuple(sorted(cct.NATIVE_MEDIA_KINDS))


def test_tag_interpreter_is_not_copied_into_the_router() -> None:
    """``model_router.declared_native_media_kinds`` 必须是核心件本身，不是第二份实现."""
    assert model_router.declared_native_media_kinds is cct.declared_native_media_kinds


# ===========================================================================
# 路 ①：``--apply`` 整段覆写——脚本不得自带第二张能力标签表，写回前必须有闸
# ===========================================================================

def test_build_registry_composes_capability_tags_from_the_declaration() -> None:
    """脚本产出的条目，能力标签由声明源合成，而不是抄在硬编码表里."""
    registry = car.build_registry()
    assert DECLARED_ID in registry
    assert cct.declared_native_media_kinds(registry[DECLARED_ID]["tags"]) == frozenset(
        DECLARED_KINDS
    )
    # 硬编码表自己**不再含**能力标签：含了就等于回到两张表对撞的老病。
    table_rows = {entry_id: tags for entry_id, _model, tags, _p in car.AXONHUB_ROUTES}
    assert cct.declared_native_media_kinds(table_rows[DECLARED_ID]) == frozenset()


def test_apply_guard_names_the_channel_and_the_missing_capability_tag() -> None:
    registry = {DECLARED_ID: {**healthy_entry(), "tags": [TIER_TAG]}}
    problems = car.capability_guard_problems(registry)
    assert problems, "抹掉能力标签必须被点名，不许静默放行"
    text = "\n".join(problems)
    assert DECLARED_ID in text
    for tag in DECLARED_TAGS:
        assert tag in text
    assert car.capability_guard_problems({DECLARED_ID: healthy_entry()}) == []


def test_apply_refuses_to_write_and_leaves_files_untouched(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("BOT_CHAT_MODEL=x\n", encoding="utf-8")
    settings_path = tmp_path / "runtime_settings.json"
    settings_path.write_text(json.dumps({"model_registry": {}}), encoding="utf-8")
    monkeypatch.setattr(car, "ENV_PATH", env_path)
    monkeypatch.setattr(car, "RUNTIME_SETTINGS", settings_path)
    monkeypatch.setattr(car, "BACKUP_DIR", tmp_path / "backups")
    # 把在册渠道从写回表里摘掉 ⇒ 声明的能力无处落地 ⇒ 必须拒绝落盘
    monkeypatch.setattr(
        car,
        "AXONHUB_ROUTES",
        [row for row in car.AXONHUB_ROUTES if row[0] != DECLARED_ID],
    )
    env_before = env_path.read_bytes()
    settings_before = settings_path.read_bytes()
    assert car.main(["--apply"]) != 0
    assert env_path.read_bytes() == env_before
    assert settings_path.read_bytes() == settings_before


# ===========================================================================
# 路 ②：管理员整表替换——能力标签不得被顺手带走
# ===========================================================================

def test_admin_tag_update_replaces_tiers_but_keeps_capability_tags(tmp_path: Path) -> None:
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    store.replace_registry_entries({DECLARED_ID: healthy_entry()})
    body = ra._handle_model_registry_command(
        store, {}, store.list_model_registry(), "update", [DECLARED_ID, "tags=high,max"]
    )
    persisted = store.list_model_registry()[DECLARED_ID]
    assert "high" in persisted["tags"] and "max" in persisted["tags"]
    assert TIER_TAG not in persisted["tags"], "档位标签仍须整表替换（旧语义不变）"
    for tag in DECLARED_TAGS:
        assert tag in persisted["tags"], f"{tag} 被顺手抹掉了"
    # 不提示 == 管理员以为自己能摘掉它：回复必须点名被保留的能力标签
    assert all(tag in body for tag in DECLARED_TAGS)


def test_admin_tag_update_can_still_add_a_capability_tag_once(tmp_path: Path) -> None:
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    store.replace_registry_entries({DECLARED_ID: {**healthy_entry(), "tags": [TIER_TAG]}})
    ra._handle_model_registry_command(
        store,
        {},
        store.list_model_registry(),
        "update",
        [DECLARED_ID, f"tags={TIER_TAG},{DECLARED_TAGS[0]}"],
    )
    tags = store.list_model_registry()[DECLARED_ID]["tags"]
    assert list(tags).count(DECLARED_TAGS[0]) == 1, "补齐不得造重复标签"


# ===========================================================================
# 路 ③ + 总闸：重启前体检项
# ===========================================================================

def test_check_registered_as_a_pre_restart_item(tmp_path: Path, monkeypatch) -> None:
    root = make_project(tmp_path, registry={DECLARED_ID: healthy_entry()})
    monkeypatch.setattr(prc, "run_cmd", lambda args, cwd, timeout=600: (0, "[绿] OK", ""))
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)
    ids = [item.id for item in prc.run_all(root)]
    assert "channel_tags" in ids


def test_check_passes_only_when_every_declared_capability_is_present(tmp_path: Path) -> None:
    root = make_project(tmp_path, registry={DECLARED_ID: healthy_entry()})
    result = run_check(root)
    assert result.status == PASS
    assert DECLARED_ID in result.message


@pytest.mark.parametrize("dropped", DECLARED_TAGS)
def test_check_fails_naming_channel_and_every_missing_tag(tmp_path: Path, dropped: str) -> None:
    kept = [TIER_TAG, *(t for t in DECLARED_TAGS if t != dropped)]
    root = make_project(tmp_path, registry={DECLARED_ID: {**healthy_entry(), "tags": kept}})
    result = run_check(root)
    assert result.status == FAIL
    assert DECLARED_ID in result.message
    assert dropped in result.message
    assert result.fix_hint


def test_check_fails_when_declared_channel_is_gone_entirely(tmp_path: Path) -> None:
    root = make_project(tmp_path, registry={"other-channel": healthy_entry()})
    result = run_check(root)
    assert result.status == FAIL
    assert DECLARED_ID in result.message
    # 形态可判别（注毒实跑补的断言）：把"渠道整体缺席"那一支摘掉后，缺席会被
    # 兜底判成"缺标签"——状态仍是 FAIL，但**文案不再说得出"这条渠道不见了"**，
    # 管理员照着修法去补标签而不是去找渠道，等于把最严重的那种丢法糊成小的。
    # 故两条一起锁：缺席必须点名"没有这条渠道"，缺标签必须不点名它。
    assert "没有这条渠道" in result.message


def test_check_distinguishes_missing_tags_from_a_missing_channel(tmp_path: Path) -> None:
    """反向格：只缺标签时不得说成"渠道不见了"（两形态的修法不同，不许混报）."""
    root = make_project(tmp_path, registry={DECLARED_ID: {**healthy_entry(), "tags": [TIER_TAG]}})
    result = run_check(root)
    assert result.status == FAIL
    assert "缺能力标签" in result.message
    assert "没有这条渠道" not in result.message


def test_check_skips_when_no_registry_exists_at_all(tmp_path: Path) -> None:
    root = make_project(tmp_path, registry=None)
    assert run_check(root).status == SKIP


def test_check_fails_on_env_shadow_and_reports_merged_effective_form(tmp_path: Path) -> None:
    """③：``.env`` 同名条目整条遮蔽运行时 tags ⇒ 生效值里没有能力标签 ⇒ 必须 FAIL，
    且报的是**合并后**形态（只报键名与标签，绝不报密钥）."""
    shadow = json.dumps(
        {
            DECLARED_ID: {
                "model": "gemini-3.8-flash",
                "base_url": "http://x/v1",
                "api_key": "env:BOT_API_KEY_AXONHUB",
                "tags": [TIER_TAG],
                "priority": 1,
            }
        }
    )
    root = make_project(tmp_path, registry={DECLARED_ID: healthy_entry()}, env_registry=shadow)
    result = run_check(root)
    assert result.status == FAIL
    assert DECLARED_ID in result.message
    for tag in DECLARED_TAGS:
        assert tag in result.message
    assert "BOT_MODEL_REGISTRY" in result.message
    assert "env:BOT_API_KEY_AXONHUB" not in result.message  # 槽名可出现，值结构性不进


def test_check_passes_when_the_shadow_is_lifted_by_override_fields(tmp_path: Path) -> None:
    """管理员显式把 tags 认领为运行时所有（override_fields 含 tags）⇒ 运行时 tags 存活 ⇒ PASS."""
    shadow = json.dumps(
        {
            DECLARED_ID: {
                "model": "gemini-3.8-flash",
                "base_url": "http://x/v1",
                "api_key": "env:BOT_API_KEY_AXONHUB",
                "tags": [TIER_TAG],
                "priority": 1,
            }
        }
    )
    entry = {**healthy_entry(), "source": "env", "override_fields": ["tags"]}
    root = make_project(tmp_path, registry={DECLARED_ID: entry}, env_registry=shadow)
    assert run_check(root).status == PASS


def test_check_message_never_carries_a_secret_value(tmp_path: Path) -> None:
    """健康态与失败态两条输出都不得出现密钥值（只出现 ``env:`` 槽名）."""
    ok_root = make_project(
        tmp_path, registry={DECLARED_ID: {**healthy_entry(), "api_key": "ah-live-secret"}}
    )
    bad_root = make_project(
        tmp_path / "b",
        registry={DECLARED_ID: {**healthy_entry(), "tags": [], "api_key": "ah-live-secret"}},
    )
    for result in (run_check(ok_root), run_check(bad_root)):
        assert "ah-live-secret" not in result.message + result.fix_hint


def test_check_falls_back_to_the_only_settings_file_and_names_it(tmp_path: Path) -> None:
    """实例名推出的文件不存在时回落唯一候选；用了哪个文件要点名（可复核性）."""
    root = make_project(tmp_path, registry=None, instance="typo")
    write_registry(root, "shorekeeper", {DECLARED_ID: healthy_entry()})
    result = run_check(root)
    assert result.status == PASS
    assert "runtime_settings_shorekeeper.json" in result.message


def test_check_fails_loudly_when_the_channel_lives_only_in_another_instance(
    tmp_path: Path,
) -> None:
    """真机暴露过的瞎眼形态：BOT_RUNTIME_INSTANCE 为空 + 同目录有两个实例文件。
    生效实例文件里注册表是空的 ⇒ 不能 SKIP 放行，必须点名两个文件。"""
    root = make_project(tmp_path, registry={})  # 生效实例文件存在但条目为空
    write_registry(root, "shorekeeper", {DECLARED_ID: healthy_entry()})
    result = run_check(root)
    assert result.status == FAIL
    assert DECLARED_ID in result.message
    assert "runtime_settings_shorekeeper.json" in result.message
    assert "runtime_settings_t4.json" in result.message


@pytest.mark.parametrize(
    ("instance", "persona", "expected"),
    [("shorekeeper", "someoneelse", "shorekeeper"), ("", "shorekeeper", "shorekeeper"),
     ("  ", "shorekeeper", "shorekeeper"), ("", "", "default")],
)
def test_instance_self_boot_agrees_with_the_runtime_rule(
    instance: str, persona: str, expected: str
) -> None:
    """实例判定与 ``settings.effective_instance`` 必须是同一条链（互证，不各写一份）."""
    env = {"BOT_RUNTIME_INSTANCE": instance, "BOT_PERSONA_PROFILE_ID": persona}
    from types import SimpleNamespace

    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        effective_instance,
    )

    config = SimpleNamespace(bot_runtime_instance=instance, bot_persona_profile_id=persona or "default")
    assert prc.effective_runtime_instance(env)[0] == expected
    assert effective_instance(config) == expected


def test_read_registry_file_is_fail_safe_on_garbage(tmp_path: Path) -> None:
    junk = tmp_path / "runtime_settings_x.json"
    junk.write_text("{not json", encoding="utf-8")
    assert read_registry_file(junk) == {}
    assert read_registry_file(tmp_path / "absent.json") == {}
