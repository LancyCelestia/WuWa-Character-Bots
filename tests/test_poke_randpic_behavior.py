"""S-T-POKE-1（2026-09-26）戳一戳 × 随机发图：四条实弹级机器锁。

用户 ITEM 14/15 的口径已经落了码（五臂矩阵 + 三触发随机发图 + 跟戳 + 回复后戳），
本件**不重做实现**，只做一件事：把那四条从「代码里存在」变成「改坏了当场红」。

四组锁：

- **A 组 确定性随机源**：选臂必须是 hash 抽签、可复现、与进程 RNG 状态无关。
  注毒自证＝造一份「把 ``pool[digest % len]`` 换成 ``random.choice``」的源码副本，
  同一把尺当场判它不可复现（证明这条锁有牙，不是空跑）。
- **B 组 概率和=1 且与真身对齐**：权重只从 ``poke_mix_pool_weights`` 派生
  （成员数算法出口），大样本实测占比必须落在声明权重 ± 容差内；
  所有参与判据的配置值一律 **AST 读 ``config.py`` 真身字面缺省**，
  本件不写第二套数字（写了就叫测夹具）。
- **C 组 同图不重复**：身份=内容 SHA-256 不是文件名；图库 1 张与 5 张轮完两种
  规模各自断言；注毒＝把身份函数换成路径身份，我的探针必须当场判红。
- **D 组 私聊不贴表情**：守卫在 ``enabled/mid`` 之后、五层门之前，所以私聊
  **连门都不占**（假 bot 零调用 + 三门登记簿全空）。既有两件的锁复跑确认没丢。
- **E 组 跟戳 / 回复后戳 / 主动发图三族门**：概率层、冷却层、每小时上限层
  **逐层单独关闭各产一次「不发」**，且每层拒绝都不扣额度（拒绝后额度盘点=满）。

全离线：假 ``call_api`` 记账、假图库只在 ``tmp_path`` 下造字节；零网络、
零真实协议端、零源码树写入、零文件删除。
"""

from __future__ import annotations

import ast
import asyncio
import copy
import functools
import random
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    POKE_REACTION_MATRIX,
    PokeDispatcher,
    PokeEvent,
    ProactiveActionKnobs,
    poke_mix_pool_arms,
    poke_mix_pool_weights,
    poke_reaction_cells,
    proactive_action_allowed,
    resolve_poke_reply,
    resolve_poke_reply_mode,
)
from plugins.bot_unified_runtime.domains.meme.capabilities import randpic
from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
    ProactiveGate,
    maybe_react_on_message,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins/bot_unified_runtime"
POKE_PY = PLUGIN_ROOT / "domains/chat_reply/capabilities/poke.py"
CONFIG_PY = PLUGIN_ROOT / "config.py"
ROOT_INIT = PLUGIN_ROOT / "__init__.py"
ENGINE_PY = PLUGIN_ROOT / "domains/meme/reactions/engine.py"
RANDPIC_PY = PLUGIN_ROOT / "domains/meme/capabilities/randpic.py"

#: 用户 ITEM 14 点名的五臂（反戳/自然语言/语音+文本/表情包/随机图）。
FIVE_NAMED_ARMS: tuple[str, ...] = ("poke", "llm", "voice", "meme", "randpic")


# ============================================================ 真身配置读数器


@functools.lru_cache(maxsize=1)
def _config_literal_defaults() -> dict[str, object]:
    """AST 读 ``config.py`` 里 ``class Config`` 的字面量缺省（不 import 重模块）。

    为什么不走 import：本机在并发窗里 ``import numpy`` 会喷 OpenBLAS 内存分配错误，
    而 import 一次 Config 要把整个包拉起来；AST 读文件既轻又与被测代码不共享
    解释器状态，判据「读的就是那本真身」。非字面量缺省（常量引用）不进表，
    本件需要的那些键全是字面量（下面 ``_default`` 缺键即红）。
    """
    tree = ast.parse(CONFIG_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Config":
            out: dict[str, object] = {}
            for item in node.body:
                if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                    continue
                if item.value is None:
                    continue
                try:
                    out[item.target.id] = ast.literal_eval(item.value)
                except (ValueError, TypeError):
                    continue
            return out
    raise AssertionError("config.py 里找不到 class Config——『与真身对齐』的锚点没了")


def _default(name: str) -> object:
    values = _config_literal_defaults()
    assert name in values, (
        f"config.py 的 Config 上没有字面量缺省字段 {name}：本件的逐项对齐判据要求它"
        "必须是字面量（改成常量引用请同步改这条读数器，别把判据改松）"
    )
    return values[name]


_REAL_PREFIXES = ("bot_poke_", "bot_randpic_", "bot_reactions_")
_REAL_EXTRA = (
    "bot_blocked_user_ids",
    "bot_quiet_hours_enabled",
    "bot_quiet_hours_start",
    "bot_quiet_hours_end",
    "bot_quiet_hours_timezone",
    "bot_quiet_hours_session_types",
    "bot_quiet_hours_bypass_roles",
)


def _real_defaults_config(**overrides: object) -> SimpleNamespace:
    """poke / randpic / reactions / 安静时间 / blocked 的配置面**全部**由真身派生。

    只动两处（都在下面写明）：安静时间显式关掉、以及调用方点名覆写的键。
    安静时间真身缺省 ``enabled=True`` + 窗 ``00:00–06:00 Asia/Hong_Kong`` ⇒ 不关掉
    的话本件的门判定会随本机墙上时钟 flaky（安静时间本身由 E 组专测）。
    """
    base: dict[str, object] = {}
    for name, value in _config_literal_defaults().items():
        if name.startswith(_REAL_PREFIXES) or name in _REAL_EXTRA:
            base[name] = copy.deepcopy(value)
    missing = [name for name in _REAL_EXTRA if name not in base]
    assert not missing, f"config.py 缺这些字面量字段（判据失去真身）：{missing}"
    base["bot_quiet_hours_enabled"] = False
    base.update(overrides)
    return SimpleNamespace(**base)


# ================================================== 确定性/无 random 的公共尺


def _random_findings(source: str, *, filename: str = "<source>") -> list[str]:
    """源码里一切「把随机性交给 stdlib random」的形态：import / from-import / 属性访问。"""
    tree = ast.parse(source)
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (alias.name or "").split(".")[0] == "random":
                    findings.append(f"{filename}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "random":
                findings.append(f"{filename}:{node.lineno}: from {node.module} import …")
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "random":
                findings.append(f"{filename}:{node.lineno}: random.{node.attr}")
        elif isinstance(node, ast.Call):
            func = node.func
            ctor = getattr(func, "id", None) or getattr(func, "attr", None)
            if ctor == "Random":
                findings.append(f"{filename}:{node.lineno}: Random(...) 实例")
    return findings


def _selector_sequence(*, extra_arms: bool, samples: int, selector=None) -> list[str]:
    """合成一批互不相同的 (会话, 戳者, 时间桶) 输入，收它们的选臂结果。"""
    pick = selector or resolve_poke_reply_mode
    return [
        pick(
            configured="mix",
            group=f"grp-{i % 53}",
            sender=f"user-{(i * 7) % 97}",
            bucket=i // 4096,
            extra_arms_enabled=extra_arms,
        )
        for i in range(samples)
    ]


def _shares(sequence: list[str]) -> dict[str, float]:
    if not sequence:
        return {}
    counts: dict[str, int] = {}
    for arm in sequence:
        counts[arm] = counts.get(arm, 0) + 1
    total = len(sequence)
    return {arm: count / total for arm, count in sorted(counts.items())}


def _is_reproducible(selector) -> bool:
    """同输入、两次跑（中间把进程 RNG 换个种子）⇒ 结果序列必须逐位相同。"""
    probe = [
        {"group": f"grp-{i}", "sender": f"user-{i}", "bucket": 1} for i in range(64)
    ]
    random.seed(11)
    first = [selector(configured="mix", **item) for item in probe]
    random.seed(9127)
    second = [selector(configured="mix", **item) for item in probe]
    return first == second


def _exec_module(source: str, name: str) -> types.ModuleType:
    """把一份源码副本当成模块跑起来（注毒样本/重载对照都用这把尺）。

    ``@dataclass`` 在解析注解时会去 ``sys.modules[cls.__module__]`` 取命名空间，
    所以必须先把这个临时名字登记进去、跑完立刻摘掉——留在 ``sys.modules`` 里
    等于给后面的导入解析埋一颗影子模块。
    """
    module = types.ModuleType(name)
    module.__dict__["__name__"] = name
    module.__dict__["__file__"] = f"<{name}>"
    sys.modules[name] = module
    try:
        exec(compile(source, f"<{name}>", "exec"), module.__dict__)  # noqa: S102
    finally:
        if sys.modules.get(name) is module:
            del sys.modules[name]
    return module


def _poisoned_poke_source() -> str:
    """造一份「选臂改走 random.choice」的 poke.py 副本（只存在于内存/临时件）。

    注毒样本**不落源码树**：这条锁要证明的是「真有人这么改就会红」，
    而不是「本席把生产件改了」——生产 poke.py 本席禁写，也没写过。
    """
    source = POKE_PY.read_text(encoding="utf-8")
    needle = "    return pool[int(digest[:8], 16) % len(pool)]\n"
    assert needle in source, (
        "选臂那一句的真身形态变了 ⇒ 注毒样本造不出来 ⇒ 这条锁已经脱靶，"
        "请同步更新本件的注毒锚点（别删锁）"
    )
    poisoned = source.replace(needle, "    return random.choice(list(pool))\n")
    poisoned = poisoned.replace("import hashlib\n", "import hashlib\nimport random\n", 1)
    assert "import random" in poisoned and "random.choice" in poisoned
    return poisoned


# ============================================================================
# A 组：确定性随机源（绝不允许用 random）
# ============================================================================


def test_poke_module_source_has_no_random_dependency() -> None:
    """选臂真身全文零 ``random``——概率口径只能来自 hash 摘要。"""
    source = POKE_PY.read_text(encoding="utf-8")
    assert _random_findings(source, filename="poke.py") == [], (
        "poke.py 出现了 stdlib random 依赖 ⇒ 选臂不再可复现（审计/回放/测试三头全瞎）"
    )


def test_random_scan_lock_has_teeth_on_poisoned_copy() -> None:
    """注毒自证①：同一把静态尺打在注毒副本上必须判红。"""
    poisoned = _poisoned_poke_source()
    findings = _random_findings(poisoned, filename="poke.py@poisoned")
    assert findings, "注毒副本（import random + random.choice）都被判干净 ⇒ 这条锁是空跑"
    assert any("import random" in line for line in findings), findings
    assert any("random.choice" in line for line in findings), findings


def test_reproducibility_lock_has_teeth_on_poisoned_copy() -> None:
    """注毒自证②：同一把行为尺打在注毒实现上必须判「不可复现」。"""
    poisoned = _exec_module(_poisoned_poke_source(), "poke_poisoned_probe")
    assert _is_reproducible(poisoned.resolve_poke_reply_mode) is False, (
        "random.choice 版的选臂被判成可复现 ⇒ B/A 组那条复现锁根本没在测真东西"
    )


def test_arm_selection_is_reproducible_and_state_free() -> None:
    """正例：真身选臂同输入两次同臂；跨实例、跨模块重载同序列。"""
    assert _is_reproducible(resolve_poke_reply_mode) is True
    first = _selector_sequence(extra_arms=True, samples=400)
    second = _selector_sequence(extra_arms=True, samples=400)
    assert first == second
    fresh = _exec_module(POKE_PY.read_text(encoding="utf-8"), "poke_reload_probe")
    third = _selector_sequence(
        extra_arms=True, samples=400, selector=fresh.resolve_poke_reply_mode
    )
    assert third == first, "重载后序列变了 ⇒ 选臂吃了进程内游标/可变全局状态"


def test_arm_selection_survives_an_exploding_random(monkeypatch) -> None:
    """注毒自证③（行为侧）：把 stdlib random 全部换成「一调就炸」，选臂照跑。

    这条比静态扫描更狠：只要选臂路径真去碰了 random（哪怕是间接的第三方件），
    当场炸给看，而不是靠 grep 形态。
    """

    def _boom(*_args, **_kwargs):
        raise AssertionError("选臂路径竟然调用了 stdlib random")

    monkeypatch.setattr(random, "choice", _boom)
    monkeypatch.setattr(random, "random", _boom)
    monkeypatch.setattr(random, "randint", _boom)
    monkeypatch.setattr(random, "Random", _boom)
    for extra in (False, True):
        sequence = _selector_sequence(extra_arms=extra, samples=2000)
        assert len(sequence) == 2000


def test_same_poke_event_twice_yields_the_same_arm() -> None:
    """「同一 (会话,消息) 输入两次得到同一臂」——从分发器入口验，不只验纯函数。"""
    config = _real_defaults_config(bot_poke_extra_arms_enabled=True)
    event = PokeEvent(target_id="10000", user_id="7", group_id="42", sub_type="poke")

    def once() -> str:
        # 每次全新分发器：limiter 的冷却登记是进程内状态，复现判据不该依赖它。
        return PokeDispatcher(clock=lambda: 1000.0).build_poke_reaction(
            event, bot_id="10000", config=config, poke_back_available=True
        ).mode

    assert once() == once() == once()


def test_selection_stays_inside_its_declared_pool() -> None:
    """任何输入都不许选出池外臂（含两枚池外行 sticker_reaction / silent）。"""
    for extra in (False, True):
        pool = set(poke_mix_pool_arms("extended" if extra else "legacy"))
        for arm in _selector_sequence(extra_arms=extra, samples=1200):
            assert arm in pool, f"{arm} 不在池 {sorted(pool)} 里"
        assert pool.isdisjoint({"sticker_reaction", "silent"})


# ============================================================================
# B 组：概率表自洽 + 大样本占比 + 与 config.py 缺省逐项对齐
# ============================================================================


@pytest.mark.parametrize("pool_id", ["legacy", "extended"])
def test_weights_sum_to_one_and_equal_member_count(pool_id: str) -> None:
    """每池概率和=1，且每臂权重=1/成员数（成员数派生，绝不手写小数）。"""
    arms = poke_mix_pool_arms(pool_id)
    weights = poke_mix_pool_weights(pool_id)
    assert arms, f"池 {pool_id} 为空 ⇒ mix 无从选臂"
    assert list(weights) == list(arms), "权重表与池成员不同源（顺序也要求同源）"
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-12)
    for arm, weight in weights.items():
        assert weight == pytest.approx(1.0 / len(arms)), arm


@pytest.mark.parametrize("pool_id", ["legacy", "extended"])
def test_pool_membership_matches_the_matrix_table_both_directions(pool_id: str) -> None:
    """池成员 ⇄ 行表声明：两个方向都要等，漏一行或多一行都算漂移。"""
    declared = {
        cell.arm_id for cell in poke_reaction_cells() if pool_id in cell.mix_pools
    }
    assert set(poke_mix_pool_arms(pool_id)) == declared


@pytest.mark.parametrize(
    ("pool_id", "extra"), [("legacy", False), ("extended", True)]
)
def test_observed_share_matches_declared_weight_within_tolerance(
    pool_id: str, extra: bool
) -> None:
    """大样本实测占比落在声明权重 ± 容差内（样本=合成输入，确定性可复跑）。"""
    samples = 9000
    sequence = _selector_sequence(extra_arms=extra, samples=samples)
    observed = _shares(sequence)
    weights = poke_mix_pool_weights(pool_id)
    assert set(observed) == set(weights), (
        f"实测出现表外臂或某臂一次未中：{sorted(observed)} vs {sorted(weights)}"
    )
    tolerance = 0.02  # n=9000、p=1/6 时 σ≈0.004 ⇒ 容差≈5σ
    offenders = {
        arm: (observed[arm], weights[arm])
        for arm in weights
        if abs(observed[arm] - weights[arm]) > tolerance
    }
    assert not offenders, f"占比偏离声明权重超容差 ±{tolerance}：{offenders}"


def test_matrix_weights_are_never_hardcoded_in_the_producer() -> None:
    """生产件里不许出现「手抄的臂概率」（1/3、0.33、0.1665 一类字面量）。"""
    source = POKE_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, float)
            and (abs(node.value * 3 - 1.0) < 1e-9 or abs(node.value * 6 - 1.0) < 1e-9)
        ):
            offenders.append(f"{node.lineno}: {node.value}")
    assert not offenders, f"臂权重被写成字面量了（必须按成员数派生）：{offenders}"


def test_five_named_arms_are_exactly_the_users_five() -> None:
    """ITEM 14 点名的五臂 = 扩臂池去掉 fixed（fixed 是退路臂，不是表达臂）。"""
    extended = set(poke_mix_pool_arms("extended"))
    assert extended - {"fixed"} == set(FIVE_NAMED_ARMS)
    for arm in FIVE_NAMED_ARMS:
        cell = POKE_REACTION_MATRIX[arm]
        assert cell.wired_in_poke_path is True, arm
        assert cell.explicit_nameable is True, arm
        assert cell.label_zh, arm


def test_out_of_pool_rows_carry_zero_observed_weight() -> None:
    """表外两行（贴纸回应/静默）在两个池里的实测权重必须都是 0。"""
    for arm in ("sticker_reaction", "silent"):
        assert POKE_REACTION_MATRIX[arm].mix_pools == ()
        assert poke_mix_pool_weights("legacy").get(arm) is None
        assert poke_mix_pool_weights("extended").get(arm) is None
        assert arm not in _selector_sequence(extra_arms=True, samples=600)


@pytest.mark.parametrize("arm", sorted(POKE_REACTION_MATRIX))
def test_explicit_named_arm_always_wins_over_the_pool(arm: str) -> None:
    """管理员点名优先：显式臂不受扩臂档与时间桶影响（可点名臂恒可用）。"""
    cell = POKE_REACTION_MATRIX[arm]
    if not cell.explicit_nameable:
        assert arm in ("sticker_reaction", "silent")
        return
    for bucket in (0, 1, 7, 4096, 999_983):
        for extra in (False, True):
            assert (
                resolve_poke_reply_mode(
                    configured=arm,
                    group="42",
                    sender="7",
                    bucket=bucket,
                    extra_arms_enabled=extra,
                )
                == arm
            )


def test_production_defaults_leave_three_of_the_five_arms_dark() -> None:
    """现网缺省口径锁：``bot_poke_extra_arms_enabled`` 真身缺省 False ⇒ mix 停在旧三臂。

    这条**不是**「实现缺了」，而是「她裁的缺省=逐字节旧行为」被写进代码后必须
    留下的可见痕迹：缺省态下 ITEM 14 点名的 反戳/语音+文本/随机图 三臂**今天选不到**。
    哪天把缺省翻成 True（或裁定现网开），本锁当场红 ⇒ 请连同本 docstring 一起改，
    别把判据改松；扩臂的开关权在她（.env / 运行时覆盖），不在测试。
    """
    assert _default("bot_poke_extra_arms_enabled") is False
    assert _default("bot_poke_reply_mode") == "mix"
    legacy = set(poke_mix_pool_arms("legacy"))
    assert legacy == {"fixed", "llm", "meme"}
    dark = [arm for arm in FIVE_NAMED_ARMS if arm not in legacy]
    assert sorted(dark) == ["poke", "randpic", "voice"]
    sequence = _selector_sequence(extra_arms=False, samples=4000)
    assert set(sequence) <= legacy, sorted(set(sequence) - legacy)


def test_gate_knob_defaults_come_from_config_and_are_all_off() -> None:
    """三族主动门的四枚旋钮逐项对齐真身；``*_enabled`` 真身缺省 False ⇒ 今天全关。"""
    expectations = {
        "bot_poke_follow_": ("bot_poke_follow_enabled", 0.2, 120.0, 4),
        "bot_poke_after_reply_": (
            "bot_poke_after_reply_enabled",
            0.15,
            300.0,
            3,
        ),
        "bot_randpic_dispatch_": (
            "bot_randpic_dispatch_enabled",
            0.1,
            600.0,
            2,
        ),
    }
    for prefix, (enabled_key, probability, cooldown, cap) in expectations.items():
        assert _default(enabled_key) is False, enabled_key
        assert _default(f"{prefix}probability") == probability, prefix
        assert float(_default(f"{prefix}cooldown_seconds")) == cooldown, prefix
        assert int(_default(f"{prefix}max_per_hour")) == cap, prefix
        config = _real_defaults_config()
        assert getattr(config, enabled_key) is False, prefix


def test_root_wiring_knob_fallbacks_match_config_defaults() -> None:
    """根装配段的 ``ProactiveActionKnobs`` 取数点：键名与兜底值逐枚 == config.py 真身。

    这一枚是真活锁：兜底值写成 ``or 0.5`` 而真身是 ``0.2`` 时，「键读不到」与
    「键被设成 0.2」就再also分不开——门看起来在执法，实际吃的是第二套数字。
    """
    expected = {
        "_maybe_follow_poke": "bot_poke_follow_",
        "_maybe_poke_after_bot_spoke": "bot_poke_after_reply_",
        "_maybe_dispatch_randpic": "bot_randpic_dispatch_",
    }
    knob_to_suffix = {
        "enabled": "enabled",
        "probability": "probability",
        "cooldown_seconds": "cooldown_seconds",
        "max_per_hour": "max_per_hour",
    }
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8"))
    checked: set[str] = set()
    def_kind = (ast.FunctionDef, ast.AsyncFunctionDef)  # 三枚取数点是**嵌套 async def**
    for node in ast.walk(tree):
        if not isinstance(node, def_kind) or node.name not in expected:
            continue
        checked.add(node.name)
        prefix = expected[node.name]
        knob_calls: list[ast.Call] = []
        allowed_calls: list[ast.Call] = []
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            func_name = getattr(inner.func, "id", None) or getattr(
                inner.func, "attr", None
            )
            if func_name == "ProactiveActionKnobs":
                knob_calls.append(inner)
            elif func_name == "proactive_action_allowed":
                allowed_calls.append(inner)
        assert len(knob_calls) == 1 and len(allowed_calls) == 1, (
            f"{node.name}:  knobs={len(knob_calls)} allowed={len(allowed_calls)}"
            " ⇒ 装配形态变了，本锁的锚点要同步"
        )
        declared_prefix = next(
            (
                keyword.value.value
                for keyword in allowed_calls[0].keywords
                if keyword.arg == "prefix"
            ),
            None,
        )
        assert declared_prefix == prefix, (
            f"{node.name}: prefix={declared_prefix!r} ≠ 期望 {prefix!r}"
        )
        found: dict[str, tuple[str, object]] = {}
        for keyword in knob_calls[0].keywords:
            if keyword.arg not in knob_to_suffix:
                continue
            getattr_node = next(
                (
                    inner
                    for inner in ast.walk(keyword.value)
                    if isinstance(inner, ast.Call)
                    and getattr(inner.func, "id", "") == "getattr"
                    and len(inner.args) >= 3
                    and isinstance(inner.args[1], ast.Constant)
                ),
                None,
            )
            assert getattr_node is not None, (
                f"{node.name}.{keyword.arg}: 没找到 getattr(cfg, \"字面键\", 兜底) "
                "⇒ 又退回动态拼键名了（配置登记总账的直读尺会看不见这枚键）"
            )
            key = str(getattr_node.args[1].value)
            fallback = ast.literal_eval(getattr_node.args[2])
            found[keyword.arg] = (key, fallback)
        assert set(found) == set(knob_to_suffix), f"{node.name} 缺旋钮：{sorted(found)}"
        for arg_name, (key, fallback) in found.items():
            assert key == prefix + knob_to_suffix[arg_name], (
                f"{node.name}.{arg_name}: 读的是 {key}，期望 {prefix + knob_to_suffix[arg_name]}"
            )
            assert _default(key) == fallback, (
                f"{node.name}: {key} 兜底值 {fallback!r} ≠ config.py 真身缺省 "
                f"{_default(key)!r}"
            )
    assert checked == set(expected), (
        f"根装配里少了主动门取数点：{sorted(set(expected) - checked)}"
    )


# ============================================================================
# C 组：随机发图同图不重复（内容 sha256 身份）
# ============================================================================


def _gallery(root: Path, count: int, *, tag: str = "seat") -> list[Path]:
    """在 tmp_path 下造 ``count`` 张**内容互异**的假图（绝不碰真实图库目录）。"""
    root.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for index in range(count):
        path = root / f"pic-{index}.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + f"{tag}-{index}".encode())
        made.append(path)
    return made


@pytest.fixture(autouse=True)
def _isolate_randpic_state():
    """模块级三本账（目录清单 TTL / 身份记忆化 / 进程级窗账）逐用例复位。"""
    randpic._SCAN_CACHE.clear()
    randpic._IDENTITY_CACHE.clear()
    randpic._DEFAULT_RECENT_WINDOW.clear()
    yield
    randpic._SCAN_CACHE.clear()
    randpic._IDENTITY_CACHE.clear()
    randpic._DEFAULT_RECENT_WINDOW.clear()


def _randpic_config(gallery: Path, **overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "bot_randpic_dirs": [str(gallery)],
        "bot_randpic_no_repeat_window_seconds": 3600.0,
    }
    base.update(overrides)
    return _real_defaults_config(**base)


def _active_pick(config, *, session: str, seed: str):
    """主动腿（poke 臂 / 回复后派发）：整库都在窗内=本轮不发。"""
    return randpic.pick_gallery_image(
        config, session_key=session, seed=seed, allow_exhausted=False
    )


def _command_pick(config, *, session: str, seed: str):
    """指令腿（用户开口要图）：整库都在窗内=退最久没发，绝不拒不发。"""
    return randpic.pick_gallery_image(
        config, session_key=session, seed=seed, allow_exhausted=True
    )


def test_active_leg_walks_whole_gallery_without_a_single_repeat(tmp_path: Path) -> None:
    """5 张图库：主动腿连发 5 次内容身份互不相同，第 6 次诚实不发（不报错）。"""
    made = _gallery(tmp_path / "gallery", 5)
    config = _randpic_config(made[0].parent)
    seen: list[str] = []
    for index in range(len(made)):
        picked = _active_pick(config, session="group_42_7", seed=f"arm:{index}")
        assert picked is not None, f"第 {index + 1} 次主动腿拒不发图（库里还有没发过的）"
        seen.append(randpic.image_identity(picked))
    assert len(set(seen)) == len(made), "窗内有图可发却重发了 ⇒ 不重复锁失效"
    assert _active_pick(config, session="group_42_7", seed="arm:exhausted") is None, (
        "整库都在窗内时主动腿必须不发（宁缺不刷屏），而不是再挑一张"
    )


def test_no_consecutive_repeat_across_the_whole_walk(tmp_path: Path) -> None:
    """跨「窗内 + 窗过」全程扫描：相邻两次绝不可能是同一张（ITEM 15(b) 的字面口径）。"""
    made = _gallery(tmp_path / "gallery", 3)
    window = randpic.RecentImageWindow()
    stream: list[str] = []
    for index in range(12):
        picked = randpic.pick_fresh_image(
            [str(made[0].parent)],
            session_key="group_42_7",
            window=window,
            window_seconds=3600.0,
            seed=f"seq:{index}",
            allow_exhausted=True,  # 指令路口径：整库在窗内也要发 ⇒ 才看得到跨账行为
        )
        assert picked is not None
        stream.append(randpic.image_identity(picked))
    repeats = [
        (i, stream[i]) for i in range(1, len(stream)) if stream[i] == stream[i - 1]
    ]
    assert not repeats, f"出现了连续重复同一张：{repeats}"


def test_single_image_gallery_active_leg_declines_and_arm_falls_back_to_text(
    tmp_path: Path,
) -> None:
    """图库只剩 1 张（主动腿）：第一次发、第二次不发、且臂必须回退成文本——不报错。"""
    made = _gallery(tmp_path / "gallery", 1)
    config = _randpic_config(made[0].parent)
    first = _active_pick(config, session="group_42_7", seed="poke-randpic:7:42")
    assert first is not None
    assert first == made[0]
    second = _active_pick(config, session="group_42_7", seed="poke-randpic:7:42")
    assert second is None, "单图库主动腿第二发必须不发（重发=她明令禁止的形态）"
    text, image = resolve_poke_reply(
        "randpic", fixed_text="固定话术", randpic_path=None
    )
    assert image is None and text == "固定话术", (
        "randpic 臂落空时必须回退固定话术：不许静默空回（表里 fallback_arm=fixed）"
    )


def test_single_image_gallery_command_leg_still_serves(tmp_path: Path) -> None:
    """图库只剩 1 张（指令腿）：每次都发那一张，绝不因防重复而拒不发。

    如实记账：这一条**与「禁止重复发送同一张」的字面口径相冲**，是现实现里
    刻意的不对称（用户开口要图时拒不发更糟）。要不要连指令腿也收，等她裁。
    """
    made = _gallery(tmp_path / "gallery", 1)
    config = _randpic_config(made[0].parent)
    picks = [
        _command_pick(config, session="group_42_7", seed=f"cmd:{index}")
        for index in range(3)
    ]
    assert all(pick is not None and pick == made[0] for pick in picks)
    assert len({randpic.image_identity(p) for p in picks}) == 1


def test_no_repeat_identity_survives_a_rename(tmp_path: Path) -> None:
    """改名不换图：窗内已发过的那张被改名后，主动腿仍不许再发它。"""
    root = tmp_path / "gallery"
    _gallery(root, 3)
    config = _randpic_config(root)
    first = _active_pick(config, session="group_42_7", seed="a:0")
    assert first is not None
    renamed = root / "renamed-by-the-owner.png"
    first.rename(renamed)
    randpic._SCAN_CACHE.clear()  # 目录清单 30s TTL：模拟「用户整理图库后重扫」
    for index in range(1, 3):
        picked = _active_pick(config, session="group_42_7", seed=f"a:{index}")
        assert picked is not None
        assert randpic.image_identity(picked) != randpic.image_identity(renamed), (
            "改名后的同一张图又被发了一次 ⇒ 身份是路径不是内容"
        )


def test_two_paths_with_identical_bytes_are_one_picture(tmp_path: Path) -> None:
    """两份不同路径、同一份字节 = 一张图：窗内只算一次。"""
    root = tmp_path / "gallery"
    root.mkdir(parents=True)
    payload = b"\x89PNG\r\n\x1a\n" + b"same-picture"
    (root / "copy-a.png").write_bytes(payload)
    (root / "copy-b.png").write_bytes(payload)
    other = root / "different.png"
    other.write_bytes(b"\x89PNG\r\n\x1a\n" + b"another-picture")
    config = _randpic_config(root)
    identities: list[str] = []
    for index in range(3):
        picked = _active_pick(config, session="group_42_7", seed=f"d:{index}")
        if picked is None:
            break
        identities.append(randpic.image_identity(picked))
    assert len(set(identities)) == len(identities), identities
    assert len(set(identities)) <= 2, "两份同字节副本被当成两张图发出去了"


def test_identity_lock_has_teeth_when_identity_degrades_to_path(
    tmp_path: Path, monkeypatch
) -> None:
    """注毒自证：把身份换成路径 ⇒ 同图不重复必须当场露馅（证明 C 组锁有牙）。"""
    root = tmp_path / "gallery"
    root.mkdir(parents=True)
    payload = b"\x89PNG\r\n\x1a\n" + b"one-and-the-same"
    (root / "first.png").write_bytes(payload)
    (root / "second.png").write_bytes(payload)
    monkeypatch.setattr(randpic, "image_identity", lambda path: str(path))
    config = _randpic_config(root)
    seen: list[str] = []
    for index in range(2):
        picked = _active_pick(config, session="group_42_7", seed=f"t:{index}")
        if picked is None:
            break
        seen.append(picked.read_bytes())
    assert len(seen) == 2 and seen[0] == seen[1], (
        "路径身份下居然也没重发 ⇒ 本注毒样本没能证伪，得换个更狠的注法"
    )


def test_default_window_off_means_the_no_repeat_lock_is_inactive(
    tmp_path: Path, monkeypatch
) -> None:
    """真身缺省窗=0 ⇒ 整条不重复逻辑不参与，取图口退化成旧的纯随机一步。

    这条锁的是**可见性**：ITEM 15(b)「不重发」今天不开窗就不成立，别让读者以为
    落码即生效。哪天缺省翻正、或现网补上这枚键，请连同本条一起改。
    """
    assert float(_default("bot_randpic_no_repeat_window_seconds")) == 0.0
    root = tmp_path / "gallery"
    _gallery(root, 4)
    config = _real_defaults_config(bot_randpic_dirs=[str(root)])
    assert randpic.no_repeat_window_seconds(config) == 0.0
    calls: list[str] = []
    monkeypatch.setattr(
        randpic,
        "pick_random_image",
        lambda dirs, **kwargs: calls.append("legacy") or Path(dirs[0]) / "x.png",
    )
    assert randpic.pick_gallery_image(config, session_key="group_42_7") is not None
    assert calls == ["legacy"], "窗关态没走旧纯随机那一步 ⇒ 关态不再是逐字节旧行为"
    assert randpic._DEFAULT_RECENT_WINDOW.recent_keys(
        "group_42_7", window_seconds=3600.0
    ) == frozenset(), "窗关态居然记了账"


def test_seeded_pick_never_touches_random_when_window_is_open(
    tmp_path: Path, monkeypatch
) -> None:
    """开态 + 带 seed ⇒ 取图口一次都不碰 stdlib random（可复现、可审计）。"""

    def _boom(*_args, **_kwargs):
        raise AssertionError("带 seed 的取图路径竟然调用了 random")

    monkeypatch.setattr(random, "choice", _boom)
    monkeypatch.setattr(random, "random", _boom)
    monkeypatch.setattr(random, "Random", _boom)
    root = tmp_path / "gallery"
    _gallery(root, 5)
    config = _randpic_config(root)
    picked = _active_pick(config, session="group_42_7", seed="poke-randpic:7:42")
    assert picked is not None
    again = _active_pick(config, session="group_99_1", seed="poke-randpic:7:42")
    assert again is not None and again == picked, "同 seed 同库不同会话应当同图"


def test_poke_arm_and_dispatch_leg_use_the_production_seed_shape(
    tmp_path: Path,
) -> None:
    """生产 seed 形态（poke 臂不带消息维度）下，连发仍然一张不重样直到整库轮完。

    这条专门盯那个容易看漏的点：seed 恒定时，「换一张」的依据只能是窗账收缩候选集，
    所以窗账一坏就是「同一个人被戳两次收到同一张图」。
    """
    root = tmp_path / "gallery"
    _gallery(root, 4)
    config = _randpic_config(root)
    seed = "poke-randpic:7:42"  # 逐字照根装配那句 f"poke-randpic:{poker}:{group}"
    seen: list[str] = []
    for _ in range(4):
        picked = _active_pick(config, session="group_42_7", seed=seed)
        assert picked is not None, f"库里还有没发过的就拒不发了：{seen}"
        seen.append(randpic.image_identity(picked))
        assert len(set(seen)) == len(seen), f"同 seed 连发重样：{seen}"
    assert len(set(seen)) == 4


def test_three_trigger_points_share_one_ledger(tmp_path: Path) -> None:
    """三触发（用户要图 / 被戳的 randpic 臂 / 回复后主动派发）共用同一本窗账。

    ITEM 15 的「指定文件夹里随机挑一张」如果各记各的账，就等于同一条会话里
    三条腿各自能把同一张图再发一遍。
    """
    root = tmp_path / "gallery"
    _gallery(root, 3)
    config = _randpic_config(root)
    session = "group_42_7"
    command = _command_pick(config, session=session, seed=f"randpic:{session}:m1")
    assert command is not None
    arm = _active_pick(config, session=session, seed="poke-randpic:7:42")
    assert arm is not None
    dispatch = _active_pick(config, session=session, seed=f"randpic-dispatch:{session}:m2")
    assert dispatch is not None
    identities = {
        randpic.image_identity(p) for p in (command, arm, dispatch)
    }
    assert len(identities) == 3, "三条腿里有一条发了另一条发过的图 ⇒ 账本没共用"
    other = _active_pick(config, session="private_77", seed="poke-randpic:77:")
    assert other is not None, "会话隔离过头：私聊键不该被群聊账本吃掉整库"


def test_randpic_command_path_passes_a_non_empty_seed() -> None:
    """指令路的 seed 必须非空且带会话+消息维度（否则同一条消息重放会换图）。"""
    source = RANDPIC_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_pick_for_command"
    )
    seeds = [
        keyword.value
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
        for keyword in call.keywords
        if keyword.arg == "seed"
    ]
    assert seeds, "_pick_for_command 不再传 seed ⇒ 指令路会掉进 random.choice"
    seed = seeds[0]
    assert isinstance(seed, ast.JoinedStr), ast.dump(seed)
    rendered = "".join(
        value.value if isinstance(value, ast.Constant) else "{…}"
        for value in seed.values
    )
    assert "randpic:" in rendered and "{…}" in rendered, rendered


# ============================================================================
# D 组：私聊绝不派发 set_msg_emoji_like（复跑 + 独立锁）
# ============================================================================


class FakeBot:
    """记账型假 bot：``call_api`` 被调了几次、调的是什么，全留在 ``calls`` 里。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call_api(self, api: str, **kwargs):
        self.calls.append((api, kwargs))


def _reaction_config(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        # 真身缺省 probability=0.2 会让「群聊必须真发一发」的反向对照 flaky，
        # 所以对照态把概率钉成 1、冷却钉成 0（其余旋钮仍走真身）。
        "bot_reactions_probability": 1.0,
        "bot_reactions_cooldown_seconds": 0,
    }
    base.update(overrides)
    return _real_defaults_config(**base)


_PRIVATE_KEYS = ("9900", "private_9900", "3865067623", "", "   ")


@pytest.mark.parametrize("trigger", ["emotion_signal", "after_reply"])
@pytest.mark.parametrize("session_key", _PRIVATE_KEYS)
def test_private_session_never_dispatches_set_msg_emoji_like(
    session_key: str, trigger: str
) -> None:
    """QQ 侧没有私聊表情回应通道（SnowLuma 抛 not supported 实测 36 次）⇒ 不发。"""
    bot = FakeBot()
    gate = ProactiveGate()
    verdict = asyncio.run(
        maybe_react_on_message(
            bot,
            session_key=session_key,
            user_message_id=8800 + len(session_key),
            text="谢谢你帮大忙" if trigger == "emotion_signal" else "今天赢了比赛",
            config=_reaction_config(),
            trigger=trigger,
            gate=gate,
            bot_related=True,
        )
    )
    assert verdict is False
    assert bot.calls == [], f"私聊竟然打到了协议端：{bot.calls}"


@pytest.mark.parametrize("session_key", ["group_42_7", "group:42"])
def test_group_session_dispatches_it_exactly_once(session_key: str) -> None:
    """反向对照：群键同一套参数必须真发一发，否则上面那一堆是空跑锁。"""
    bot = FakeBot()
    verdict = asyncio.run(
        maybe_react_on_message(
            bot,
            session_key=session_key,
            user_message_id=8801,
            text="今天赢了比赛",
            config=_reaction_config(),
            trigger="after_reply",
            gate=ProactiveGate(),
        )
    )
    assert verdict is True
    assert [name for name, _ in bot.calls] == ["set_msg_emoji_like"]


def test_private_denial_leaves_the_gate_completely_unoccupied() -> None:
    """私聊守卫坐在五层门之前 ⇒ 连「掷过骰/去过重」都不该登记（拒绝不占额度）。"""
    bot = FakeBot()
    gate = ProactiveGate()
    verdict = asyncio.run(
        maybe_react_on_message(
            bot,
            session_key="9900",
            user_message_id=777,
            text="谢谢你帮大忙",
            config=_reaction_config(),
            trigger="emotion_signal",
            gate=gate,
            bot_related=True,
        )
    )
    assert verdict is False
    assert gate._last == {} and gate._reacted == {} and gate._rolled == {}
    assert gate.has_rolled("9900", "777") is False
    # 同一条消息换个群键再来，必须还能真发一发（证明刚才那次没占每消息去重）。
    group_verdict = asyncio.run(
        maybe_react_on_message(
            FakeBot(),
            session_key="group_42_7",
            user_message_id=777,
            text="谢谢你帮大忙",
            config=_reaction_config(),
            trigger="emotion_signal",
            gate=gate,
            bot_related=True,
        )
    )
    assert group_verdict is True


def test_private_guard_sits_before_the_gate_in_the_source() -> None:
    """AST 顺序锁：守卫行号必须在 ``active_gate.allow(`` 之前（位置即语义）。

    2026-09-26 S-T-POKE-1b 修两处锚点：① ``maybe_react_on_message`` 是
    ``async def``（``ast.AsyncFunctionDef``），前任只匹配 ``FunctionDef``
    ⇒ 直接 StopIteration；② mid 准入门在真身里写成
    ``if not knobs["enabled"] or not mid:``——mid 是 UnaryOp 不是 Compare
    左值，前任那把「Compare.left==mid」的尺在真身上永远找不到锚点。
    现行判据＝守卫行必须晚于「测试子树里出现 Name(mid) 的 If 语句」。
    """
    tree = ast.parse(ENGINE_PY.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "maybe_react_on_message"
    )
    guard_lines = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "_is_group_session"
    ]
    allow_lines = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "allow"
    ]
    assert guard_lines and allow_lines, (
        f"守卫 {guard_lines} / 门 {allow_lines} ⇒ 判据形态变了，先确认私聊口径再改锁"
    )
    assert max(guard_lines) < min(allow_lines)
    mid_gate_lines = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.If)
        and any(
            isinstance(inner, ast.Name) and inner.id == "mid"
            for inner in ast.walk(node.test)
        )
    ]
    assert mid_gate_lines, (
        "找不到以 mid 为条件的准入 If ⇒ 空消息号那一道门形态变了，先核对真身再改锁"
    )
    assert guard_lines[0] > min(mid_gate_lines), (
        "守卫被挪到了 mid 判定之前 ⇒ 空消息号也会先撞会话键（顺序即语义）"
    )


def _react_call_name(node: ast.Call) -> str:
    """根装配里它是 ``from ... import maybe_react_on_message as _maybe_react_on_message``。"""
    name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
    return name.lstrip("_")


def _direct_call_names(function: ast.AST) -> dict[str, int]:
    """函数**自身体**里直接调用的 名字→首现行号；不下探嵌套 def/async def/lambda。

    2026-09-26 S-T-POKE-1b 加这把尺：根装配是一个 sync ``_register_nonebot_handlers``
    把 poke 处理器与 chat 处理器全部**嵌套**在内。前任对候选函数整体
    ``ast.walk`` ⇒ 外层一口气吸收了所有嵌套体的调用，chat 链路合法的两处
    ``_maybe_react_on_message`` 被误记到「被戳链路」头上（假阳性）。
    按最内层归属才是「谁调的」这句话的字面意思。
    """
    out: dict[str, int] = {}
    stack: list[ast.AST] = [function]
    while stack:
        node = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue  # 嵌套定义体归嵌套定义自己
            if isinstance(child, ast.Call):
                name = getattr(child.func, "id", "") or getattr(child.func, "attr", "")
                out.setdefault(name, child.lineno)
            stack.append(child)
    return out


def test_poke_path_still_does_not_call_the_reaction_engine() -> None:
    """被戳那一发今天不贴表情：根装配里 poke 相关函数一次都没调引擎。

    与矩阵 ``sticker_reaction.wired_in_poke_path=False`` 同真同假——接上线却不改表，
    或改了表却没接线，两边都会红在这里。
    """
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8"))
    react_calls = sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _react_call_name(node) == "maybe_react_on_message"
    )
    assert react_calls == 2, (
        f"maybe_react_on_message 调用点现算 {react_calls}（口径=chat 链路两处）"
        " ⇒ 有人动了表情派发面，请同步改这条与矩阵行"
    )
    poke_markers = {"build_poke_reaction", "_dispatch_poke_at", "_dispatch_poke_back"}
    poke_handler_bodies: list[tuple[str, dict[str, int]]] = []
    def_kind = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, def_kind):
            continue
        direct = _direct_call_names(node)
        if poke_markers & set(direct):
            poke_handler_bodies.append((node.name, direct))
    assert poke_handler_bodies, "根装配里找不到 poke handler ⇒ 锚点失效"
    # 覆盖面自证：被戳主处理器与跟戳/回戳两族分发腿都必须被认成 poke 链路。
    names = {name for name, _ in poke_handler_bodies}
    assert {"_handle_poke_notice", "_maybe_follow_poke", "_dispatch_poke_back"} <= names, (
        f"poke 链路只认出 {sorted(names)} ⇒ 装配形态变了，先核对再改锁"
    )
    offenders = [
        f"{name}:{lineno}"
        for name, direct in poke_handler_bodies
        if (lineno := direct.get("_maybe_react_on_message")) is not None
    ]
    assert not offenders, f"被戳链路已经会贴表情了却仍标未接线：{offenders}"
    assert POKE_REACTION_MATRIX["sticker_reaction"].wired_in_poke_path is False


# ============================================================================
# E 组：跟戳 / 回复后戳 / 主动发图 的三层门 + 拒绝不扣额度
# ============================================================================

_FAMILIES: dict[str, dict[str, str]] = {
    "follow": {"prefix": "bot_poke_follow_"},
    "after_reply": {"prefix": "bot_poke_after_reply_"},
    "randpic_dispatch": {"prefix": "bot_randpic_dispatch_"},
}


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, delta: float) -> None:
        self.now += delta


def _knobs(prefix: str, config) -> ProactiveActionKnobs:
    """旋钮一律从传入配置现取（该配置由真身缺省派生 ⇒ 本件没有第二套数字）。"""
    return ProactiveActionKnobs(
        enabled=bool(getattr(config, f"{prefix}enabled")),
        probability=float(getattr(config, f"{prefix}probability")),
        cooldown_seconds=float(getattr(config, f"{prefix}cooldown_seconds")),
        max_per_hour=int(getattr(config, f"{prefix}max_per_hour")),
    )


def _try(
    family: str,
    config,
    gate: ProactiveGate,
    *,
    message: str,
    session: str = "group_42_77",
    group: str = "42",
    user: str = "77",
    require_group: bool = True,
) -> bool:
    prefix = _FAMILIES[family]["prefix"]
    return proactive_action_allowed(
        config,
        prefix=prefix,
        gate=gate,
        session_key=session,
        message_key=message,
        group_id=group,
        user_id=user,
        salt=f"{prefix}probe",
        require_group=require_group,
        knobs=_knobs(prefix, config),
    )


@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_switch_off_denies_everything_with_zero_trace(family: str) -> None:
    """真身缺省 ``enabled=False`` ⇒ 三族今天一条都不发（现网口径的可执行版本）。"""
    config = _real_defaults_config()
    assert bool(getattr(config, f"{_FAMILIES[family]['prefix']}enabled")) is False
    gate = ProactiveGate(clock=FakeClock())
    assert _try(family, config, gate, message="m0") is False
    assert gate._last == {} and gate._reacted == {} and gate._rolled == {}


@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_probability_layer_denies_and_burns_no_quota(family: str) -> None:
    """概率层：prob=0 一律不发；同门随后 prob=1 立刻能发 ⇒ 拒绝没烧冷却/额度。"""
    prefix = _FAMILIES[family]["prefix"]
    gate = ProactiveGate(clock=FakeClock())
    denied = _try(
        family, _real_defaults_config(**{f"{prefix}enabled": True, f"{prefix}probability": 0.0}),
        gate,
        message="m0",
    )
    assert denied is False
    open_config = _real_defaults_config(
        **{f"{prefix}enabled": True, f"{prefix}probability": 1.0}
    )
    # 同一扇门、同一个会话、时钟没走：若刚才那次登记了冷却，这一发必被拦。
    assert _try(family, open_config, gate, message="m1") is True, (
        "概率拒绝反手烧了冷却 ⇒ 安静窗/概率门会误拦后续动作"
    )
    assert _try(family, open_config, gate, message="m0") is False, (
        "同一 message_key 换概率重掷 = 双骰漏洞（门必须记住这条已经骰过）"
    )


@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_cooldown_layer_denies_and_burns_no_hourly_quota(family: str) -> None:
    """冷却层：窗内第二条不发；出窗能发，且整程成功次数恰=每小时上限。

    成功次数若比上限少 1，就说明那次「冷却拒绝」偷偷占了滑窗额度。
    """
    prefix = _FAMILIES[family]["prefix"]
    config = _real_defaults_config(**{f"{prefix}enabled": True, f"{prefix}probability": 1.0})
    clock = FakeClock()
    gate = ProactiveGate(clock=clock)
    cooldown = float(getattr(config, f"{prefix}cooldown_seconds"))
    cap = int(getattr(config, f"{prefix}max_per_hour"))
    assert _try(family, config, gate, message="m0") is True
    assert _try(family, config, gate, message="m1") is False, "冷却窗内第二条照样发了"
    successes = 1
    clock.advance(cooldown + 1.0)
    for index in range(2, cap + 5):
        if _try(family, config, gate, message=f"m{index}"):
            successes += 1
            clock.advance(cooldown + 1.0)
    assert successes == cap, (
        f"成功 {successes} 次 ≠ 每小时上限 {cap} 次 ⇒ 有拒绝被记进了滑窗额度"
    )


@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_hourly_cap_layer_denies_and_slides_back(family: str) -> None:
    """每小时上限层：到顶即拦（换消息键也没用）；滑窗过期后能发 ⇒ 拒绝没续窗。"""
    prefix = _FAMILIES[family]["prefix"]
    config = _real_defaults_config(**{f"{prefix}enabled": True, f"{prefix}probability": 1.0})
    clock = FakeClock()
    gate = ProactiveGate(clock=clock)
    cooldown = float(getattr(config, f"{prefix}cooldown_seconds"))
    cap = int(getattr(config, f"{prefix}max_per_hour"))
    for index in range(cap):
        assert _try(family, config, gate, message=f"m{index}") is True
        clock.advance(cooldown + 1.0)
    assert _try(family, config, gate, message="over-cap") is False, "每小时上限没拦住"
    clock.advance(3600.0 + 1.0)
    assert _try(family, config, gate, message="after-slide") is True, (
        "滑窗过期后仍发不出 ⇒ 被拒的那次把窗口又续长了一格"
    )


@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_blocked_and_quiet_hours_denials_burn_nothing(family: str) -> None:
    """blocked 名单与安静时间窗这两道硬门：拒绝发生在进门之前，额度一根毛都不掉。"""
    prefix = _FAMILIES[family]["prefix"]
    open_config = _real_defaults_config(
        **{f"{prefix}enabled": True, f"{prefix}probability": 1.0}
    )
    blocked = _real_defaults_config(
        **{
            f"{prefix}enabled": True,
            f"{prefix}probability": 1.0,
            "bot_blocked_user_ids": ["77"],
        }
    )
    quiet = _real_defaults_config(
        **{
            f"{prefix}enabled": True,
            f"{prefix}probability": 1.0,
            "bot_quiet_hours_enabled": True,
            "bot_quiet_hours_start": "00:00",
            "bot_quiet_hours_end": "00:00",  # start==end ⇒ 整窗全时生效
            "bot_quiet_hours_session_types": ["group"],
        }
    )
    clock = FakeClock()
    gate = ProactiveGate(clock=clock)
    assert _try(family, blocked, gate, message="m0") is False
    assert _try(family, quiet, gate, message="m1") is False
    assert gate._last == {} and gate._reacted == {} and gate._rolled == {}, (
        "名单/安静窗的拒绝在门里留了痕 ⇒ 拦人的门反咬后续动作"
    )
    cap = int(getattr(open_config, f"{prefix}max_per_hour"))
    successes = 0
    for index in range(cap):
        assert _try(family, open_config, gate, message=f"clean-{index}") is True
        successes += 1
        clock.advance(float(getattr(open_config, f"{prefix}cooldown_seconds")) + 1.0)
    assert successes == cap, "拒绝把每小时额度扣掉了（能发的次数少于上限）"
    assert _try(family, open_config, gate, message="one-too-many") is False


@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_private_target_still_never_gets_a_proactive_poke(family: str) -> None:
    """``require_group=True``：私聊形态一律不发，且不占门（跟戳/回复后戳的场合门）。"""
    prefix = _FAMILIES[family]["prefix"]
    config = _real_defaults_config(**{f"{prefix}enabled": True, f"{prefix}probability": 1.0})
    gate = ProactiveGate(clock=FakeClock())
    assert (
        _try(family, config, gate, message="m0", group="", user="77", session="77")
        is False
    )
    assert gate._last == {} and gate._rolled == {}
    if family == "randpic_dispatch":
        # 主动**发图**那一族不需要群门（私聊发图与「随机图」指令同口径）。
        assert (
            _try(
                family,
                config,
                ProactiveGate(clock=FakeClock()),
                message="m0",
                group="",
                user="77",
                session="77",
                require_group=False,
            )
            is True
        )


def test_gate_commit_probe_detects_a_leaking_gate() -> None:
    """工具自证：拿一扇「拒绝也 commit」的坏门跑同样的盘法，探针必须判红。

    没有这一条，上面几条「不扣额度」的用例可能只是恰好没人写坏门而已。
    """

    class LeakingGate(ProactiveGate):
        def allow(self, session_key, message_key, **kwargs):
            verdict = super().allow(session_key, message_key, **kwargs)
            if not verdict:
                # 注毒：被拒也登记冷却（正是「拦人的门反咬后续动作」那个形态）。
                self._last[str(session_key)] = self.clock()
            return verdict

    config = _real_defaults_config(
        bot_poke_follow_enabled=True, bot_poke_follow_probability=0.0
    )
    gate = LeakingGate(clock=FakeClock())
    assert _try("follow", config, gate, message="m0") is False
    opened = _real_defaults_config(
        bot_poke_follow_enabled=True, bot_poke_follow_probability=1.0
    )
    assert _try("follow", opened, gate, message="m1") is False, (
        "注毒门居然没被探针抓到 ⇒ 「拒绝不扣额度」那几条判据是软的"
    )


def test_five_arm_probabilities_still_sum_to_one_after_gate_chain() -> None:
    """端到端：门链全开时，被戳一次恰好出一臂，且五臂分布仍等于声明权重。

    这条把 A/B 两组接起来——如果分发器在门后另加了一层随机或另一套权重，
    实测分布会从 ``poke_mix_pool_weights`` 上掉下来。
    """
    config = _real_defaults_config(bot_poke_extra_arms_enabled=True)
    weights = poke_mix_pool_weights("extended")
    modes: list[str] = []
    for index in range(1800):
        event = PokeEvent(
            target_id="10000", user_id=f"user-{index % 311}", group_id=f"grp-{index % 17}",
            sub_type="poke",
        )
        reaction = PokeDispatcher(clock=lambda: 1000.0).build_poke_reaction(
            event, bot_id="10000", config=config, poke_back_available=True
        )
        assert reaction is not None
        modes.append(reaction.mode)
    observed = _shares(modes)
    assert set(observed) <= set(weights)
    for arm, weight in weights.items():
        assert abs(observed.get(arm, 0.0) - weight) <= 0.05, (
            f"{arm} 端到端占比 {observed.get(arm, 0.0):.3f} 偏离声明权重 {weight:.3f}"
        )
    assert len(modes) == 1800


def test_matrix_table_self_check_is_clean() -> None:
    """行表自检必须为空（本件所有派生判据的地基）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
        validate_poke_reaction_matrix,
    )

    assert validate_poke_reaction_matrix() == ()
