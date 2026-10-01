"""慢回复先回执（ack-first）·需求项 6 收尾：阈值判据的可回归化 + 探针执法在场性。

本件与 `tests/test_progress_ack.py` 的分工：那边管「文案池 / 名单门 / 冷却 /
投递形状 / 装配可达性」，这边只管三件事——

① **阈值不再散落成字面量**：`progress_ack.py` 的 `DEFAULT_*` 常量 ↔
   `config.py` 的字段缺省 ↔ dataclass 缺省 ↔ `from_config` 的 getattr 兜底，
   四处由 AST 现算比对（不 import 被测件做自比，同源自证＝空转）。
   为什么值得锁：`15.0` 这一枚数字原来在本件里写两遍、在 `config.py` 再写一遍，
   任何一处改口都不会被另一处发现；而「配置面没有这枚键」与「配置就是 15 秒」
   在旧写法里长得一模一样。
② **阈值真值表（离线版真机回归）**：判定用现网实测的网关 EWMA 与回复耗时，
   逐格断言「发 / 不发」。需求项 6 的原话是「中转站一慢就必触发，误报过多」，
   所以这里既断新判据（网关慢时不该开口），也断旧判据仍在场（自适应关死时
   逐字节回到固定 15 秒），两态互相揭穿，不许双双静默。
③ **自适应读数的执法在场性**：根 `__init__.py` 真把那枚探针交给 pipeline 吗？
   交错了、删了、或 pipeline 收了不读——以前**全套件全绿而线上自适应永不生效**
   （grep 实证：`progress_ack_latency_probe` 在全仓测试里零命中）。D-8(a) 同型病：
   机制存在但装配落空。

`DEFECT-1` 那一发是**已知真误触发**的挂账（`xfail(strict=False)`）：能力自己抛
`TimeoutError` 时被误认成「我们的阈值到点」，于是 0.05 秒就失败的请求照样先发一句
「我在想」。实弹证据与最小修法坐标见
`.superpowers/sdd/2026-09-25-goal18-wave/logs/S-T-ACK-1.md` §5。
"""

from __future__ import annotations

import ast
import dataclasses
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import progress_ack as PA
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.progress_ack import (
    DEFAULT_ACK_COOLDOWN_SECONDS,
    DEFAULT_ACK_DELAY_CAP_SECONDS,
    DEFAULT_ACK_DELAY_FLOOR_SECONDS,
    DEFAULT_ACK_DELAY_SECONDS,
    DEFAULT_ACK_LATENCY_MULTIPLIER,
    ProgressAckSettings,
    effective_ack_delay_seconds,
)
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PY = _REPO_ROOT / "plugins" / "bot_unified_runtime" / "config.py"
_ROOT_INIT = _REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
_PIPELINE_PY = (
    _REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "runtime"
    / "pipeline.py"
)

# 回执族在 config.py 的全部字段 → 本件对应的缺省常量名。
# 这张表**本身**也是判据：往 config.py 加一枚 `bot_chat_progress_ack_*` 而不在这里
# 登记、或登记了却没在 `from_config` 里读它，两把锁各红一次。
ACK_FIELD_TO_CONSTANT: dict[str, str | None] = {
    "bot_chat_progress_ack_enabled": None,  # 缺省 False，单独锁（总闸必须缺省关）
    "bot_chat_progress_ack_delay_seconds": "DEFAULT_ACK_DELAY_SECONDS",
    "bot_chat_progress_ack_cooldown_seconds": "DEFAULT_ACK_COOLDOWN_SECONDS",
    "bot_chat_progress_ack_group_whitelist": None,  # 空列表＝群面关闭（绝不猜群）
    "bot_chat_progress_ack_group_blacklist": None,
    "bot_chat_progress_ack_private_whitelist": None,  # 空列表＝私聊放开（刻意不对称）
    "bot_chat_progress_ack_private_blacklist": None,
    "bot_chat_progress_ack_adaptive_enabled": None,  # 缺省 True，单独锁
    "bot_chat_progress_ack_delay_floor_seconds": "DEFAULT_ACK_DELAY_FLOOR_SECONDS",
    "bot_chat_progress_ack_delay_cap_seconds": "DEFAULT_ACK_DELAY_CAP_SECONDS",
    "bot_chat_progress_ack_latency_multiplier": "DEFAULT_ACK_LATENCY_MULTIPLIER",
}

# 现网实测读数（`config.py` 注释 + 台账 #43/#50）：gemini 单跳 EWMA≈4.5s、
# grok≈13.7s、grok 单跳最大≈19.9s。真值表按这三枚**实际见过**的数走。
OBSERVED_EMAS_MS = (4_500.0, 13_700.0, 19_900.0)


def _config_field_defaults() -> dict[str, object]:
    """AST 现算 `config.py` 里 `bot_chat_progress_ack_*` 的声明缺省值。

    不 import Config：那会让本锁与被测件同源（pydantic 校验器还会把 `[]` 的形态
    就地改写）。同时把「同名字段写两遍」当红——后一处会静默覆盖前一处，
    本仓踩过一次（#53 同名 `match_manual_command` 重复定义）。
    """
    tree = ast.parse(_CONFIG_PY.read_text(encoding="utf-8"))
    found: dict[str, object] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        name = node.target.id
        if not name.startswith("bot_chat_progress_ack_") or node.value is None:
            continue
        assert name not in found, f"config.py 里 {name} 被声明了两遍（后写静默覆盖前写）"
        found[name] = ast.literal_eval(node.value)
    return found


def _production_settings() -> ProgressAckSettings:
    """按 `config.py` 现值装配一份「生产同形」设置（真值表用它，不写字面量）。"""
    return ProgressAckSettings.from_config(SimpleNamespace(**_config_field_defaults()))


class _NullAudit:
    def append(self, record: object) -> None:
        return


def _incoming(*, sender_id: str = "u1", group_id: str = "") -> IncomingMessage:
    session_id = f"group_1_{sender_id}" if group_id else f"private:{sender_id}"
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=session_id,
        session_type=SessionType.GROUP if group_id else SessionType.PRIVATE,
        sender_id=sender_id,
        group_id=group_id or None,
        plain_text="你好",
        message_id="m-1",
    )


def _result(message: IncomingMessage) -> CapabilityResult:
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.chat",
        kind="ok",
        title="",
        summary="",
        body="海潮回来了。",
    )


def _pipeline(
    *,
    delay: float,
    submits: list[object],
    order: list[str] | None = None,
    probe: Callable[[], float | None] | None = None,
    floor: float = DEFAULT_ACK_DELAY_FLOOR_SECONDS,
    raise_on_submit: bool = False,
) -> RuntimePipeline:
    """生产同形的管线：自适应开、倍率与上下限都吃 `DEFAULT_*`（不写第二套数）。"""
    settings = ProgressAckSettings(
        enabled=True,
        delay_seconds=delay,
        cooldown_seconds=DEFAULT_ACK_COOLDOWN_SECONDS,
        group_whitelist=frozenset({"662948429"}),
        private_whitelist=frozenset(),
        delay_floor_seconds=floor,
        delay_cap_seconds=DEFAULT_ACK_DELAY_CAP_SECONDS,
        latency_multiplier=DEFAULT_ACK_LATENCY_MULTIPLIER,
    )

    def _submit(request: object) -> None:
        if raise_on_submit:
            raise RuntimeError("queue down")
        submits.append(request)
        if order is not None:
            order.append("ack")

    return RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAudit()),
        audit_logger=_NullAudit(),
        progress_ack_settings=settings,
        progress_ack_submit=_submit,
        progress_ack_latency_probe=probe,
    )


def _delay_for_probe(ema_ms: float | None) -> float:
    """_pipeline 那份设置在给定 EWMA 下算出的阈值（用真身函数算，不手推）。"""
    settings = _pipeline_settings(delay=0.02, floor=0.05)
    return effective_ack_delay_seconds(settings, ema_ms)


def _pipeline_settings(*, delay: float, floor: float) -> ProgressAckSettings:
    return ProgressAckSettings(
        enabled=True,
        delay_seconds=delay,
        cooldown_seconds=DEFAULT_ACK_COOLDOWN_SECONDS,
        delay_floor_seconds=floor,
        delay_cap_seconds=DEFAULT_ACK_DELAY_CAP_SECONDS,
        latency_multiplier=DEFAULT_ACK_LATENCY_MULTIPLIER,
    )


# ---------------------------------------------------------------------------
# ① 阈值字面量收敛：四处同源的 parity 锁
# ---------------------------------------------------------------------------


def test_config_declares_exactly_the_known_ack_fields() -> None:
    """配置面加了键而本席不知道 = 读点幽灵（Config 上没有的键被 `extra=ignore` 静默丢）。"""
    defaults = _config_field_defaults()
    assert set(defaults) == set(ACK_FIELD_TO_CONSTANT), (
        "回执族字段清单漂移：加/删 config.py 的键必须同时登记本表并补判据"
    )


def test_from_config_reads_every_ack_field_and_no_ghost_one() -> None:
    """双向锁：`from_config` 读的键集 == 配置面在册的键集。

    只读不在册的键 ⇒ 那行 `.env` 永远无效（台账 #43① config_missing 同型）；
    在册而不读 ⇒ 改了配置什么都不发生，而字段名看起来像生效了。
    """
    tree = ast.parse(Path(PA.__file__).read_text(encoding="utf-8"))
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "from_config"
    )
    read = {
        node.args[1].value
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
    }
    assert read == set(ACK_FIELD_TO_CONSTANT), (
        "`from_config` 读的键与配置面在册的键不等："
        f"只读={read - set(ACK_FIELD_TO_CONSTANT)} 只在册={set(ACK_FIELD_TO_CONSTANT) - read}"
    )


@pytest.mark.parametrize("field_name", sorted(ACK_FIELD_TO_CONSTANT))
def test_config_default_equals_module_constant(field_name: str) -> None:
    """`config.py` 的缺省 ↔ 本件 `DEFAULT_*` 常量：两处必须同值。"""
    constant_name = ACK_FIELD_TO_CONSTANT[field_name]
    config_default = _config_field_defaults()[field_name]
    if constant_name is None:
        # 非数值那几枚：缺省形态本身就是判据，逐个点名，不给「反正不比」的空档。
        if field_name.endswith("_enabled"):
            assert isinstance(config_default, bool), f"{field_name} 缺省必须是 bool"
        else:
            assert config_default == [], f"{field_name} 缺省必须是空列表（不猜名单）"
        return
    assert getattr(PA, constant_name) == config_default, (
        f"{field_name}：config.py 缺省={config_default!r} 与本件 "
        f"{constant_name}={getattr(PA, constant_name)!r} 不一致 ⇒ 阈值又散成两份了"
    )


@pytest.mark.parametrize(
    ("field_name", "constant_name"),
    [
        ("delay_seconds", "DEFAULT_ACK_DELAY_SECONDS"),
        ("cooldown_seconds", "DEFAULT_ACK_COOLDOWN_SECONDS"),
        ("delay_floor_seconds", "DEFAULT_ACK_DELAY_FLOOR_SECONDS"),
        ("delay_cap_seconds", "DEFAULT_ACK_DELAY_CAP_SECONDS"),
        ("latency_multiplier", "DEFAULT_ACK_LATENCY_MULTIPLIER"),
    ],
)
def test_dataclass_default_is_the_constant_not_a_stray_literal(
    field_name: str, constant_name: str
) -> None:
    """dataclass 缺省也吃同一枚常量（第四处散落点）。"""
    field = {f.name: f for f in dataclasses.fields(ProgressAckSettings)}[field_name]
    assert field.default == getattr(PA, constant_name)


@pytest.mark.parametrize(
    ("field_name", "config_key"),
    [
        ("enabled", "bot_chat_progress_ack_enabled"),
        ("adaptive_enabled", "bot_chat_progress_ack_adaptive_enabled"),
    ],
)
def test_bool_switch_dataclass_default_matches_config(
    field_name: str, config_key: str
) -> None:
    """两枚布尔闸的 dataclass 缺省也要与配置面缺省等值（注毒 P5 教出来的洞）。

    本席第一版只把五枚数值字段接进 parity 网，两枚布尔只比了"配置面缺省是什么"，
    没比"dataclass 缺省是什么"⇒ 把 `adaptive_enabled: bool = True` 改成 False
    只红 1 发（行为级那一发）。总闸缺省若被谁改成 True，代价是**键关部署不再
    逐字节现状**、回执对全网开放，所以这两枚必须同网同锁。
    """
    field = {f.name: f for f in dataclasses.fields(ProgressAckSettings)}[field_name]
    assert field.default is _config_field_defaults()[config_key]


def test_master_switch_defaults_closed_and_adaptive_defaults_open() -> None:
    """总闸缺省 False＝键关部署逐字节现状；自适应缺省 True＝现网不再一抖就报。"""
    declared = _config_field_defaults()
    assert declared["bot_chat_progress_ack_enabled"] is False
    assert declared["bot_chat_progress_ack_adaptive_enabled"] is True
    empty = ProgressAckSettings.from_config(SimpleNamespace())
    assert empty.enabled is False
    assert empty.adaptive_enabled is True


def test_from_config_missing_keys_lands_on_config_defaults() -> None:
    """「配置面没有这枚键」的兜底值 == 「键在册而没人填」的缺省值。

    这条就是本次收敛的验收判据本身：旧写法靠三份重复字面量凑出等值，等值不等于同源；
    现在两处都指向 `DEFAULT_*`，等值才是结构性的。
    """
    empty = ProgressAckSettings.from_config(SimpleNamespace())
    declared = _config_field_defaults()
    assert empty.delay_seconds == declared["bot_chat_progress_ack_delay_seconds"]
    assert empty.cooldown_seconds == declared["bot_chat_progress_ack_cooldown_seconds"]
    assert empty.delay_floor_seconds == declared["bot_chat_progress_ack_delay_floor_seconds"]
    assert empty.delay_cap_seconds == declared["bot_chat_progress_ack_delay_cap_seconds"]
    assert empty.latency_multiplier == declared["bot_chat_progress_ack_latency_multiplier"]
    assert empty.group_whitelist == frozenset()
    assert empty.private_whitelist == frozenset()


def test_settings_are_an_immutable_snapshot_with_no_mutable_default() -> None:
    """门禁用的是**装配期快照**：构造后不许在运行期被改（热改 `.env` 当轮不生效，
    这条 docstring 已声明；但若谁把 `frozen=True` 摘掉，运行期就多出第二条改判据的路，
    与"谁在运行期把回执面改了"这类最难归因的问题同源）。
    """
    settings = _production_settings()
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.delay_seconds = 0.001  # type: ignore[misc]
    for field in dataclasses.fields(ProgressAckSettings):
        assert not isinstance(field.default, (list, set, dict)), (
            f"{field.name} 用了可变默认值（dataclass 会直接拒，出现即有人绕过了构造）"
        )


# ---------------------------------------------------------------------------
# ② 阈值真值表（离线版真机回归）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ema_ms", [None, 0, -1, "not-a-number", 0.0])
def test_unmeasured_gateway_opens_no_earlier_than_the_floor(ema_ms: object) -> None:
    """缺测 ⇒ `max(静态值, 地板)`（2026-09-28 用户裁定收掉 D2a 那一半）。

    旧裁定是"逐字节退回静态值"，代价＝冷启动窗口（刚重启还没有样本）里 D2 抬起来的
    地板根本不生效、仍按 15 秒开口——那正是她要收的口。观测面坏了依旧**不带走功能**
    （只是不再比地板更早开口），fail-open 的方向没变，变的只是开口时刻的下界。
    """
    settings = _production_settings()
    got = effective_ack_delay_seconds(settings, ema_ms)  # type: ignore[arg-type]
    assert got == max(settings.delay_seconds, settings.delay_floor_seconds)
    assert got >= settings.delay_floor_seconds


def test_cold_start_bar_never_sits_below_the_static_bar() -> None:
    """缺测那一档在整段静态配置上单调不降，且永远不小于地板。

    只测现网那一格的话，`return max(15.0, 30.0)` 写死也能绿；这里横扫静态值两侧
    （静态低于地板 / 高于地板），把"取 max"这条判据本身钉住。
    """
    for static in (0.5, 5.0, 15.0, 30.0, 45.0, 120.0):
        settings = dataclasses.replace(_production_settings(), delay_seconds=static)
        got = effective_ack_delay_seconds(settings, None)
        assert got == max(static, settings.delay_floor_seconds), f"静态 {static}s 时实测 {got}s"
        assert got >= static, f"缺测把配置值就地改小了：静态 {static}s → {got}s"


def test_adaptive_disabled_still_honours_the_static_bar_exactly() -> None:
    """显式关死自适应＝逐字节回到「配多少判多少」，地板不参与（测试旋钮依赖这一条）。

    缺测抬地板只作用于"自适应开着但读不到数"这一支；把自适应关掉是**人为选择固定值**，
    再拿地板去顶它就成了配置被静默改写。下游亚秒夹具全走这条支路，故必须钉死。
    """
    settings = dataclasses.replace(
        _production_settings(), adaptive_enabled=False, delay_seconds=0.02
    )
    assert effective_ack_delay_seconds(settings, None) == 0.02
    assert effective_ack_delay_seconds(settings, 99_000.0) == 0.02


@pytest.mark.parametrize("ema_ms", [1.0, 500.0, 4_500.0, 13_700.0, 60_000.0, 500_000.0])
def test_threshold_never_opens_earlier_than_the_static_bar(ema_ms: float) -> None:
    """网关越慢 ⇒ 开口只能越晚，不许反向。早开口就是需求项 6 的病。"""
    settings = _production_settings()
    assert effective_ack_delay_seconds(settings, ema_ms) >= settings.delay_seconds


def test_threshold_is_monotonic_across_the_whole_observed_range() -> None:
    """整段区间单调不降（含现网三枚实测 EWMA 所在的那几格）。"""
    settings = _production_settings()
    samples = [effective_ack_delay_seconds(settings, x) for x in range(0, 200_001, 500)]
    assert all(later >= earlier for earlier, later in pairwise(samples))


def test_threshold_band_is_bounded_and_cap_below_floor_does_not_invert() -> None:
    """结果永远落在 [floor, cap]；有人把上限配得比下限小也不产生倒挂。

    本圈只量**有观测**的那条路（ema>0）：``x`` 从 1 起，不是从 0 起。``ema==0`` 与
    ``ema is None`` 属于"缺测"，按 `effective_ack_delay_seconds` 的既有裁定逐字节
    退回静态值、**不**被下限顶起（下方 ``test_missing_observation_...`` 把这条实况
    钉住）。下限还是 15 时两值恰好重合，所以这处自相矛盾一直没露脸——本文件第二条
    断言的注释早写了"0 与 None 不在本列"，第一圈却把 0 算了进来。
    """
    settings = _production_settings()
    for ema_ms in (x * 250.0 for x in range(1_201) if x):
        value = effective_ack_delay_seconds(settings, ema_ms)
        assert settings.delay_floor_seconds <= value <= settings.delay_cap_seconds, (
            f"ema={ema_ms}ms 时阈值 {value}s 越出 ["
            f"{settings.delay_floor_seconds}, {settings.delay_cap_seconds}]"
        )

    inverted = dataclasses.replace(
        settings, delay_floor_seconds=30.0, delay_cap_seconds=5.0
    )
    # 0 与 None 不在本列：那两个是"缺测"，按上面那条判据逐字节退回静态值（15 秒），
    # 而不是退成下限——把它们混进来会把"缺测回退"这条真实判据判成倒挂。
    for ema_ms in (*OBSERVED_EMAS_MS, 500_000.0):
        assert effective_ack_delay_seconds(inverted, ema_ms) == 30.0, (
            "cap<floor 时结果必须稳定停在下限，而不是退成上限或忽上忽下"
        )


def test_missing_observation_no_longer_reopens_the_cold_start_hole() -> None:
    """D2a 已收口（2026-09-28 用户裁定）：缺测不再逐字节退回未抬的静态旧地板。

    旧现状（挂账 D2a 时钉住的）：EWMA 拿不到（健康库未启用／读失败／**刚重启还没有
    样本**）⇒ 阈值退回静态 `delay_seconds`（15.0），不受 30 秒下限约束 ⇒ D2 抬地板在
    冷启动窗口内不生效，那一段仍按 15 秒误开口。本用例当时把那个洞**显式钉成判据**，
    今天是把它翻正成"洞已收"：缺测形态一律 `max(静态值, 地板)`。

    仍然在场的两半（不许被这次改动带走）：
    ① 观测面坏了**不许把回执功能一起带走**——缺测照样有一个可开口的阈值，只是不早于地板；
      探针抛异常/返回垃圾都只退成这一个下界（见 `test_probe_that_raises_or_returns_junk_...`，
      它自带亚秒地板，语义不变）。
    ② 静态值本身仍是**下界**：本次只抬不压，配置填得比地板高时按配置走。
    她想把静态改成 40 属配置面（`.env`/`config.py`，本席禁写）——注意静态一旦抬到 40，
    因为 `floor = max(static, delay_floor_seconds)`，整条自适应带的下界也一起抬到 40。
    """
    settings = _production_settings()
    assert settings.adaptive_enabled is True
    for missing in (None, 0.0, "not-a-number"):
        got = effective_ack_delay_seconds(settings, missing)  # type: ignore[arg-type]
        assert got == max(settings.delay_seconds, settings.delay_floor_seconds), (
            f"缺测形态 {missing!r} 应抬到地板，实测 {got}"
        )
    assert settings.delay_floor_seconds == DEFAULT_ACK_DELAY_FLOOR_SECONDS, (
        "地板真身漂移：本用例的期望值来自 `progress_ack.DEFAULT_ACK_DELAY_FLOOR_SECONDS`，"
        "与 `config.py` 的缺省由上面的 parity 锁同源比对"
    )
    assert settings.delay_seconds == DEFAULT_ACK_DELAY_SECONDS, (
        "静态值仍是那枚没抬过的 "
        f"{DEFAULT_ACK_DELAY_SECONDS} 秒（config.py/.env 两侧都还没跟上她的 40 秒口径）："
        "缺测现在抬到地板，所以 15 与 30 并存的冷启动误触发面已收；但静态本身若要抬到"
        "40，因为 `floor = max(static, delay_floor_seconds)`，整条自适应带的下界会一起"
        "被顶到 40 —— 那是配置面动作，坐标见交卷 `_hub 补丁申请_`"
    )


@pytest.mark.parametrize(
    ("ema_ms", "expected_seconds"),
    [
        # 地板 15→30（09-26 D2）→ 55（09-29 中途）→ **50**（09-29 需求项 6 终稿：
        # 用户口径「结果必须落在 45~60 秒」，地板 50 把 30-45 秒的正常联网轮整段
        # 盖过去，又给自适应腿留出上沿）。派生值低于下限时**下限说话**。
        (4_500.0, DEFAULT_ACK_DELAY_FLOOR_SECONDS),  # 快网关：派生 13.5 秒 < 地板 ⇒ 地板说话
        (13_700.0, DEFAULT_ACK_DELAY_FLOOR_SECONDS),  # 现网 grok 慢跳：派生 41.1 秒仍低于地板 ⇒ 地板说话
        (19_900.0, 59.7),  # 现网 grok 单跳最大：3.0 倍率派生≈59.7 秒，高于地板 ⇒ 用派生值
        (500_000.0, DEFAULT_ACK_DELAY_CAP_SECONDS),  # 网关炸了：上限兜住
    ],
)
def test_threshold_at_observed_gateway_states(
    ema_ms: float, expected_seconds: float
) -> None:
    assert effective_ack_delay_seconds(_production_settings(), ema_ms) == pytest.approx(
        expected_seconds
    )


def test_effective_delay_lands_inside_the_ruling_band_on_the_shipped_defaults() -> None:
    """需求项 6 的原话尺：「有效触发延迟必须落进 45~60 秒」。

    这不是把断言放宽，而是把**用户的口径**本身钉进门里：旧形态 floor 30 / cap 90 /
    倍率 2.0 时，30-35 秒的正常联网轮必然先开口（实测误触 19/34＝55.9%），结果既
    出过区间下沿、也出过区间上沿，谁都没守着这条线。

    覆盖面＝生产装配形态（`ProgressAckSettings.from_config(Config())`，即 `.env`
    不动键时的真值）× 现网全部观测态（含缺测、含网关炸穿上限）：任何一格都不许
    落到 45 秒以下或 60 秒以上。

    ⚠ 刻意**不**覆盖 `adaptive_enabled=False`：那一支是人为选择「配多少判多少」，
    本件另有用例钉它逐字节回到静态值（`test_adaptive_off_is_the_old_ruling_...`）。
    关自适应又想把开口时刻留在区间内，动作在配置面——把
    `BOT_CHAT_PROGRESS_ACK_DELAY_SECONDS` 钉进 45~60，不是让代码去顶掉用户填的数。
    """
    from plugins.bot_unified_runtime.config import Config

    settings = ProgressAckSettings.from_config(Config())
    assert settings.enabled is False, "总闸缺省关（本用例只管阈值尺，不管开关）"
    assert settings.adaptive_enabled is True, "生产缺省开自适应 ⇒ 区间尺由地板/上限守住"
    assert 45.0 <= settings.delay_floor_seconds <= settings.delay_cap_seconds <= 60.0, (
        f"地板/上限本身先出区间：{settings.delay_floor_seconds}/{settings.delay_cap_seconds}"
    )
    for ema_ms in (None, 0.0, "junk", 1.0, 4_500.0, 13_700.0, 19_900.0, 60_000.0, 5e6):
        got = effective_ack_delay_seconds(settings, ema_ms)
        assert 45.0 <= got <= 60.0, (
            f"观测态 {ema_ms!r} 下有效阈值 {got}s 出界（用户口径 45~60 秒）"
        )
    # 静态腿在缺测时也不许把结果推出区间下沿：静态值高于地板时会顶高下界。
    assert settings.delay_seconds <= 60.0, (
        f"静态阈值 {settings.delay_seconds}s 会把缺测形态顶出区间上沿"
    )


@pytest.mark.parametrize("adaptive_enabled", [True, False])
def test_adaptive_off_is_the_old_ruling_and_on_is_the_new_one(
    adaptive_enabled: bool,
) -> None:
    """两态分开断言，防止「自适应把旧判据顶掉了」与「自适应其实没接上」互相掩盖。"""
    settings = dataclasses.replace(
        _production_settings(), adaptive_enabled=adaptive_enabled
    )
    got = effective_ack_delay_seconds(settings, 13_700.0)
    assert got == pytest.approx(15.0 if not adaptive_enabled else DEFAULT_ACK_DELAY_FLOOR_SECONDS), (
        "关自适应＝逐字节回到固定 15 秒（显式停用，下限不参与）；"
        "开自适应＝派生 41.1 秒低于地板 ⇒ 地板说话（09-29 需求项 6 新尺）"
    )


def _ack_would_fire(reply_seconds: float, ema_ms: float | None, *, adaptive: bool = True) -> bool:
    """本轮会不会发回执——判据与 `pipeline._await_with_progress_ack` 同一条：
    超过有效阈值仍未出结果才发。"""
    settings = dataclasses.replace(_production_settings(), adaptive_enabled=adaptive)
    return reply_seconds > effective_ack_delay_seconds(settings, ema_ms)


@pytest.mark.parametrize(
    ("ema_ms", "reply_seconds", "expected_ack", "why"),
    [
        (4_500.0, 12.0, False, "快网关 + 12 秒回复：阈值内出结果，什么都不发"),
        (4_500.0, 28.0, False, "★ 正常联网轮收口：快网关 + 28 秒（旧口径 30 秒会发）"),
        (4_500.0, 60.0, True, "快网关但 60 秒已越过地板 ⇒ 该发"),
        (13_700.0, 20.0, False, "grok 慢跳下 20 秒是这条路的正常耗时"),
        (13_700.0, 40.0, False, "★ 30-45 秒正常轮：地板把它收在阈值内（旧地板 30 必发）"),
        (
            13_700.0,
            DEFAULT_ACK_DELAY_FLOOR_SECONDS,
            False,
            "边界：等于阈值不发（判据是 `>` 不是 `>=`）",
        ),
        (13_700.0, 60.0, True, "慢网关 + 60 秒越过地板 ⇒ 该发"),
        (19_900.0, 50.0, False, "单跳最大 19.9s 派生≈59.7s，50 秒不越阈值"),
        (19_900.0, 60.0, True, "60 秒越过派生阈值 59.7 ⇒ 该发（地板以上派生说话）"),
        (60_000.0, 120.0, True, "网关整体炸到上限之外也要出声，不能永远沉默"),
        (None, 18.0, False, "缺测抬到地板：18 秒不再按旧低值开口"),
        (None, 60.0, True, "缺测且真回复越过地板照样要出声（功能不被观测面带走）"),
    ],
)
def test_send_or_stay_silent_truth_table(
    ema_ms: float | None, reply_seconds: float, expected_ack: bool, why: str
) -> None:
    assert _ack_would_fire(reply_seconds, ema_ms) is expected_ack, why


def test_the_fixed_bar_would_have_misfired_where_the_adaptive_bar_stays_silent() -> None:
    """需求项 6 的因果本身要留在树里：旧判据在现网实测数下**必发**，新判据不发。

    只断新判据的话，「把阈值整个关掉」也能让它绿；这一发把两态钉在同一格对照里。
    """
    assert _ack_would_fire(20.0, 13_700.0, adaptive=False) is True, (
        "旧固定 15 秒下 20 秒必发回执（这就是她说的「一慢就必触发」）"
    )
    assert _ack_would_fire(20.0, 13_700.0) is False, (
        "自适应下同一格不发 —— 这才是本次收口，而不是把功能关掉"
    )


# ---------------------------------------------------------------------------
# ③ 自适应读数的执法在场性（探针）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_is_consumed_on_the_emission_path_high_ema_stays_silent() -> None:
    """网关实测很慢时**不发**：探针不是装饰，它真的决定这一轮开不开口。"""
    import asyncio

    submitted: list[object] = []
    order: list[str] = []
    pipeline = _pipeline(
        delay=0.02, submits=submitted, order=order, floor=0.05,
        probe=lambda: 40_000.0,
    )
    assert _delay_for_probe(40_000.0) == pytest.approx(DEFAULT_ACK_DELAY_CAP_SECONDS), (
        "夹具前提：40 秒 EWMA × 倍率 3.0=120 被上限夹住 ⇒ 阈值＝上限那一格"
        "（09-29 需求项 6 把上限从 90 收到 60，正是为了把结果钉回 45~60 区间）"
    )

    async def reply(cap_msg, decision):
        await asyncio.sleep(0.2)
        order.append("reply")
        return _result(cap_msg)

    await pipeline.handle_async(_incoming(sender_id="u-probe-on"), reply, "bot.chat")
    assert submitted == [], "探针给了 40 秒 EWMA 却仍按亚秒阈值开口 = 自适应没被消费"
    assert order == ["reply"]


@pytest.mark.asyncio
async def test_probe_missing_measurement_keeps_the_static_bar_on_the_emission_path() -> None:
    """同一夹具只把探针换成「读不到」⇒ 必须照旧发一句（两态互相揭穿，防双双静默）。"""
    import asyncio

    submitted: list[object] = []
    pipeline = _pipeline(delay=0.02, submits=submitted, floor=0.05, probe=lambda: None)

    async def reply(cap_msg, decision):
        await asyncio.sleep(0.2)
        return _result(cap_msg)

    await pipeline.handle_async(_incoming(sender_id="u-probe-off"), reply, "bot.chat")
    assert len(submitted) == 1, "缺测时退回固定阈值：0.2 秒 > 0.02 秒，该发一句"


@pytest.mark.asyncio
async def test_probe_that_raises_or_returns_junk_degrades_to_static_bar() -> None:
    """探针抛异常 / 返回垃圾都不许把回执与真回复一起带走（观测面故障不外溢）。"""
    import asyncio

    def explodes() -> float:
        raise RuntimeError("health db locked")

    def returns(value: object) -> Callable[[], Any]:
        def _probe() -> Any:
            return value

        return _probe

    cases: list[tuple[str, Callable[[], Any]]] = [
        ("raises", explodes),
        ("junk", returns("n/a")),
        ("negative", returns(-5)),
    ]
    for label, probe in cases:
        submitted: list[object] = []
        pipeline = _pipeline(delay=0.02, submits=submitted, floor=0.05, probe=probe)

        async def reply(cap_msg, decision):
            await asyncio.sleep(0.2)
            return _result(cap_msg)

        receipt = await pipeline.handle_async(
            _incoming(sender_id=f"u-junk-{label}"), reply, "bot.chat"
        )
        assert receipt is not None, f"探针 {label} 形态把真回复一起带走了"
        assert len(submitted) == 1, f"探针 {label} 形态应当退固定阈值并发一句"


def _root_pipeline_kwargs() -> dict[str, ast.expr]:
    tree = ast.parse(_ROOT_INIT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "RuntimePipeline"
        ):
            return {kw.arg: kw.value for kw in node.keywords if kw.arg}
    raise AssertionError("根 __init__.py 找不到 RuntimePipeline(...) 构造")


def test_root_injects_the_latency_probe_and_it_actually_measures() -> None:
    """装配在场性锁（D-8(a) 同型病的墓碑）。

    以前全仓测试对 `progress_ack_latency_probe` 零命中：把根 `__init__.py` 那一行注入
    删掉、或让探针返回常量，自适应就在线上不生效，而**整个套件不会有任何一条红**。
    三条断言各管一段：① 注入位在场且值是「同文件里真定义过的函数」；
    ② 那个函数体真去渠道健康库取 EWMA（不是空壳，也不在别处再统计一份延迟）；
    ③ 取数失败必须吞（fail-open），否则健康库一抖回执整面炸。
    """
    kwargs = _root_pipeline_kwargs()
    assert "progress_ack_latency_probe" in kwargs, (
        "根装配没把网关读数探针交给 pipeline ⇒ 自适应阈值线上永不生效"
    )
    value = kwargs["progress_ack_latency_probe"]
    assert isinstance(value, ast.Name), "探针注入的不是函数名（写 None/字面量＝假接线）"

    tree = ast.parse(_ROOT_INIT.read_text(encoding="utf-8"))
    defined = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert value.id in defined, f"探针名 {value.id} 在根文件里解析不到定义 = 死引用"
    body = defined[value.id]
    called = {
        node.func.attr
        for node in ast.walk(body)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } | {
        node.func.id
        for node in ast.walk(body)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "ema_latencies" in called, (
        f"探针 {value.id} 没读渠道健康库 EWMA（被调用名={sorted(called)}）：它得是"
        "**实测读数**，另开一份本地延迟统计就是第二真身"
    )
    assert any(isinstance(node, ast.ExceptHandler) for node in ast.walk(body)), (
        "探针读不到必须吞掉退固定阈值（不许把回执功能一起带走）"
    )


def test_pipeline_reads_the_probe_attribute_it_is_given() -> None:
    """另一半在场性：pipeline 的构造参数与消费点必须同名接上。

    `self.progress_ack_latency_probe = None`（参数收了不存）会让上一发根装配锁照样绿
    ——两把锁各看一侧，合起来才咬得住。
    """
    tree = ast.parse(_PIPELINE_PY.read_text(encoding="utf-8"))
    stored = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and isinstance(node.ctx, ast.Store)
    }
    assert "progress_ack_latency_probe" in stored, "构造参数收了却没存到 self 上"
    read_back = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and isinstance(node.ctx, ast.Load)
        and node.attr == "progress_ack_latency_probe"
    ]
    assert read_back, "存了却没在判定路径上读 = 只登记不执法"


# ---------------------------------------------------------------------------
# ④ 顺序与「事后不补句」（阈值判据的另一半）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ack_is_emitted_before_the_real_reply_and_never_again_after() -> None:
    """「超阈值才发」与「事后不补句」是同一条判据的两面，本仓栽过反面那一面。

    S1 评审实锤：`queue.submit` ≠ 送出，只入队的回执最早也要等正文跑完才出去
    ⇒ 语义反转成「答完一分钟追一句我在想」。根侧那段就地投递由
    `test_progress_ack.py::test_root_ack_submitter_delivers_inline_not_just_enqueues`
    按结构锁着；这里补**时序**锁：回执排在正文之前，且正文之后不再有任何一句。
    """
    import asyncio

    order: list[str] = []
    submitted: list[object] = []
    pipeline = _pipeline(delay=0.02, submits=submitted, order=order, floor=0.05)

    async def slow(cap_msg, decision):
        await asyncio.sleep(0.25)
        order.append("reply")
        return _result(cap_msg)

    await pipeline.handle_async(_incoming(sender_id="u-order"), slow, "bot.chat")
    await asyncio.sleep(0.05)  # 给任何「事后补句」的写法留出跑到的机会

    assert order == ["ack", "reply"], f"顺序必须回执在前：{order}"
    assert len(submitted) == 1, "一轮最多一句，正文之后再发就是补句"


@pytest.mark.asyncio
async def test_reply_within_the_bar_emits_nothing() -> None:
    """阈值内出结果 ⇒ 全程零额外消息（「15 秒内不发」这条裁定的可回归形态）。"""
    import asyncio

    order: list[str] = []
    submitted: list[object] = []
    pipeline = _pipeline(delay=1.0, submits=submitted, order=order)

    async def quick(cap_msg, decision):
        await asyncio.sleep(0.01)
        order.append("reply")
        return _result(cap_msg)

    await pipeline.handle_async(_incoming(sender_id="u-quick"), quick, "bot.chat")
    assert submitted == []
    assert order == ["reply"]


@pytest.mark.asyncio
async def test_failed_submit_releases_the_slot_so_the_next_ask_can_still_be_acked() -> None:
    """投递口炸 ⇒ 0 句且不烧冷却坑（同会话下一条追问还得有救）。

    与 `test_progress_ack.py::test_submit_failure_does_not_break_real_reply_or_waste_cooldown`
    同判据，这里再钉一次**下一轮真的能发出去**——旧账只断了坑位可占，没断第二句真发出来。
    """
    import asyncio

    async def slow(cap_msg, decision):
        await asyncio.sleep(0.15)
        return _result(cap_msg)

    first: list[object] = []
    pipeline = _pipeline(delay=0.02, submits=first, floor=0.05, raise_on_submit=True)
    await pipeline.handle_async(_incoming(sender_id="u-retry"), slow, "bot.chat")
    assert first == []

    second: list[object] = []
    pipeline.progress_ack_submit = second.append
    await pipeline.handle_async(_incoming(sender_id="u-retry"), slow, "bot.chat")
    assert len(second) == 1, "上一轮失败不该惩罚这一轮：冷却坑必须已退还"


# ---------------------------------------------------------------------------
# ⑤ DEFECT-1 挂账（已知真误触发；修在禁写面 pipeline.py:1473，修好后摘牌）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capability_raised_timeout_error_is_not_misread_as_our_deadline() -> None:
    import asyncio

    submitted: list[object] = []
    order: list[str] = []
    pipeline = _pipeline(delay=5.0, submits=submitted, order=order)  # 阈值 5 秒，绝不该到点

    async def failing(cap_msg, decision):
        await asyncio.sleep(0.05)
        raise TimeoutError("read timeout from upstream")

    await pipeline.handle_async(_incoming(sender_id="u-defect1"), failing, "bot.chat")
    assert submitted == [], "本轮 0.05 秒就失败了：一句「我在想」都不该发"
