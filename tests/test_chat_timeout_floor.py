"""每跳超时地板锁（2026-09-27 弹模板文案事故）。

生产实弹（`ChatBot_Runtime/data/runtime_events.log`）：
    event=pipeline_result capability_id=bot.chat duration_ms=69436.9
    route_attempts=axon-gemini-38-flash:timeout|axon-grok-46:timeout error_kind=timeout

两跳各被 20s 掐死（合计 69s），随后弹出 `_PERSONA_FAILURE_MESSAGES` 模板文案。
模型光首字就要 20 秒以上，20s 不是「响应慢」而是**必然失败**：故障转移链上每一跳
共用同一个钳制值（`model_router.build_model_router` 的 `timeout_seconds`），
换渠道不会更快，只会把同一发超时重放 N 遍。

本锁钉三件事：
① 超时键的**代码缺省**不得低于地板（新装/漏配时不该回到必然失败的那一档）；
② 快速模式开着时 `min(normal, fast)` 不得把地板重新压穿（只抬一枚键＝没抬）；
③ 地板**只有一处真身**（`channel_health.PER_HOP_TIMEOUT_FLOOR_SECONDS`）：本锁不再自带
   数字，自适应钳制与侧腿（判域／贴纸）都从它取数（台账 #80 根修波）。
"""

from __future__ import annotations

import ast
import inspect

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine import (
    channel_health as _CH,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
    PER_HOP_TIMEOUT_FLOOR_SECONDS as PER_HOP_FLOOR_SECONDS,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
    build_model_router,
)

_TIMEOUT_KEYS = (
    "bot_chat_timeout_seconds",
    "bot_chat_fast_timeout_seconds",
    "bot_reactions_sentiment_timeout_seconds",
)

#: 地板锚点（测试侧唯一字面量）。生产常量若被下调，其余各测都从它取数、量不出问题，
#: 只有这把锚能红——把锚和生产真身写成同一个数＝没有锚（台账 #80 复审时补的牙）。
FLOOR_ANCHOR_SECONDS = 30.0


def test_per_hop_floor_constant_is_not_lowered_below_the_anchor() -> None:
    assert PER_HOP_FLOOR_SECONDS >= FLOOR_ANCHOR_SECONDS, (
        f"每跳地板被下调到 {PER_HOP_FLOOR_SECONDS}s，低于锚点 {FLOOR_ANCHOR_SECONDS}s："
        "低于该档思考型渠道连首字都等不到，链上每一跳同死。"
    )


def _default_of(key: str) -> float:
    field = Config.model_fields[key]
    assert field.default is not None, f"{key} 缺省值缺席"
    return float(field.default)


def test_per_hop_timeout_defaults_are_above_the_failure_floor() -> None:
    too_low = {k: _default_of(k) for k in _TIMEOUT_KEYS if _default_of(k) < PER_HOP_FLOOR_SECONDS}
    assert not too_low, (
        f"每跳超时缺省低于 {PER_HOP_FLOOR_SECONDS}s：{too_low}。"
        "低于该档时思考型模型连首字都等不到，故障转移链每一跳同钳，"
        "结局恒为 error_kind=timeout + 失败话术模板。"
    )


def test_fast_mode_does_not_reclamp_below_the_floor() -> None:
    """快速模式走 `min(normal, fast)`：两枚键必须一起达标才叫真抬上去。"""
    config = Config(bot_chat_fast_mode=True)
    router = build_model_router(config, provider_factory=lambda _spec: None)
    assert router.timeout_seconds >= PER_HOP_FLOOR_SECONDS, (
        f"快速模式下每跳超时被压到 {router.timeout_seconds}s，"
        f"低于地板 {PER_HOP_FLOOR_SECONDS}s（min 钳制只认两枚键里较小的那枚）。"
    )

    normal = build_model_router(
        Config(bot_chat_fast_mode=False), provider_factory=lambda _spec: None
    )
    assert normal.timeout_seconds >= PER_HOP_FLOOR_SECONDS


# ==================== 4. 天花板棘轮：延迟无用功删除波不许把超时顺手压小 ====================
#
# 2026-10-12 本仓「回得慢」那族修的是**本机往返**（每候选现开 sqlite 连接、每消息
# 全重算库路径落点），不是任何超时上限。这条锁的作用就是把「看起来快」那条邪路钉死：
# 谁把下面任一枚数值调小去压读数，当场红。锚＝当次现算读数（同 FLOOR_ANCHOR_SECONDS
# 的做法：锚写死，改小必红，改大不红＝只降不升的棘轮）。
# 账见台账 #80 同族；改前/改后 P50/P95 实跑读数在 %TEMP%/cb-lat/ab_message_leg.py.out。

#: channel_health 模块级「间隔/冷却」锚（秒）。判据参数，本波一字未动。
_MODULE_CONSTANTS: dict[str, float] = {
    "_RETRY_INTERVAL_SECONDS": 1800.0,  # 暂不可用后重探间隔
    "_DEFAULT_COOLDOWN_SECONDS": 90.0,  # 近期失败冷却缺省
}

#: 函数签名默认值里的超时锚（秒）——kind="default"。
#: sqlite3 繁忙等待那枚是**调用参数**（kind="call"），单独一档扫法。
_TIMEOUT_ANCHORS: tuple[tuple[str, str, str, float], ...] = (
    ("probe_entry", "timeout_seconds", "default", 25.0),  # 单渠道最小真实调用
    ("_connect", "timeout", "call", 10.0),  # sqlite3 繁忙等待（连接层，不是网络层）
)


def _channel_health_tree() -> ast.Module:
    path = inspect.getsourcefile(_CH)
    assert path, "拿不到 channel_health 源码路径"
    with open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read())


def _module_numeric_constants(tree: ast.Module) -> dict[str, float]:
    out: dict[str, float] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)):
            out[target.id] = float(value.value)
    return out


def _function_node(tree: ast.Module, function_name: str) -> ast.FunctionDef:
    """按名字取函数节点——**整棵树**扫：``probe_entry`` 是模块级函数，
    ``_connect`` 是 ``ChannelHealthStore`` 的方法，只扫 tree.body 会漏掉后者。
    """
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    assert found, f"函数 {function_name} 从模块里消失了"
    return found[0]


def _signature_default(func: ast.FunctionDef, argname: str) -> float:
    """取形参的数值默认值（非数值 / 缺席 ⇒ 抛，让锁红而不是静默失明）。

    两族形参都要扫：普通位参（``args.defaults`` 右对齐）与 keyword-only
    （``args.kwonlyargs`` + ``kw_defaults`` 逐位对齐）——``probe_entry`` 的
    ``timeout_seconds`` 住在后者，只扫前者会假报「形参缺席」。
    """
    plain = [arg.arg for arg in func.args.args]
    if argname in plain:
        index = plain.index(argname) - (len(func.args.args) - len(func.args.defaults))
        defaults = list(func.args.defaults)
        value = defaults[index] if 0 <= index < len(defaults) else None
    else:
        kwonly = [arg.arg for arg in func.args.kwonlyargs]
        assert argname in kwonly, f"{func.name} 已无 {argname} 形参：这把尺的坐标要重录"
        value = func.args.kw_defaults[kwonly.index(argname)]
    assert isinstance(value, ast.Constant) and isinstance(value.value, (int, float)), (
        f"{func.name}({argname}=…) 不再是可比读的数值字面量（改成变量会让这把尺失明）"
    )
    return float(value.value)


def _smallest_call_kwarg(func: ast.FunctionDef, kwarg: str) -> float:
    """函数体内所有调用里该关键字的**最小**数值（最保守那一档）。"""
    out: list[float] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if (
                kw.arg == kwarg
                and isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, (int, float))
            ):
                out.append(float(kw.value.value))
    assert out, f"{func.name} 里 {kwarg}= 的数值形态消失了：必须显式留一枚可比读的数值"
    return min(out)


def test_channel_health_refactor_kept_every_timeout_ceiling() -> None:
    """地板/重探间隔/冷却/探针超时/连接繁忙等待——逐枚只许 ≥ 锚，一字不许小。"""
    tree = _channel_health_tree()
    constants = _module_numeric_constants(tree)
    lowered = {
        name: constants[name]
        for name, anchor in _MODULE_CONSTANTS.items()
        if name in constants and constants[name] < anchor
    }
    assert not lowered, (
        f"channel_health 的间隔/冷却常量被调小：{lowered}（锚＝{_MODULE_CONSTANTS}）"
    )
    for name in _MODULE_CONSTANTS:
        assert name in constants, f"{name} 从模块级常量里消失＝锚尺被搬走，同样重录红"

    for function_name, kwarg, kind, anchor in _TIMEOUT_ANCHORS:
        func = _function_node(tree, function_name)
        actual = (
            _signature_default(func, kwarg)
            if kind == "default"
            else _smallest_call_kwarg(func, kwarg)
        )
        assert actual >= anchor, (
            f"{function_name} 的 {kwarg}={actual} 低于锚 {anchor}："
            "压延迟只准删无用功，动天花板＝丢投递那型（台账 #80 实弹）"
        )


def test_channel_health_probe_cap_still_covers_the_hop_floor() -> None:
    """巡检侧 `min(上限, bot_chat_timeout_seconds)` 那枚上限不许被压到地板以下。

    这枚上限被调小的话，`_probe_all_locked` 会把每一跳的探针对算超时钳到地板之下，
    巡检结果就再也代表不了真实调用（假「不可用」→ 渠道被误降级）。
    """
    tree = _channel_health_tree()
    caps = [
        float(node.args[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "min"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, (int, float))
    ]
    assert caps, "找不到 min(上限, …) 形态：巡检超时上限被搬走了，这把尺需要先重录"
    too_low = [cap for cap in caps if cap < PER_HOP_FLOOR_SECONDS]
    assert not too_low, f"巡检超时上限 {too_low} 低于每跳地板 {PER_HOP_FLOOR_SECONDS}s"
