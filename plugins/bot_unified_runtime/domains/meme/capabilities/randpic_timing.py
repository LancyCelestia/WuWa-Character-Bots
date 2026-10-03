"""随机发图「三时机」的**决策件**（席 PIC，2026-09-29，需求 15）。

三时机＝① bot 回复完用户消息（``after_reply``）② 用户戳一戳 bot（``poke``）
③ 用户发特定指令（``command``）。三条腿共用同一条读目录路径与同一本窗账
（真身 ``domains/meme/capabilities/randpic.py``），本件只管一件事：
**「这一轮到底发不发、发的时候按哪个桶记账、拿哪个种子取图、为什么不发」**。

为什么单独一件、而且是**纯函数**（不读配置、不碰时钟、不做 IO）：

- 根装配文件（``plugins/bot_unified_runtime/__init__.py``）是全仓最大的共享面，
  门链判定写在里面就没法离线测；本席禁写那份文件，需要的接线块写在
  ``%TEMP%/chatbot-rescue/patch-PIC.md``，由主会话串行落。
- 概率骰与冷却/滑窗账**不在本件**：唯一真身是 ``domains/meme/reactions/engine.py``
  的 ``ProactiveGate``（五层门，判定即 commit）。本件只收它算好的 ``(放行?, 拒因)``
  **数据**——把门对象交进来就等于在纯函数里替调用侧烧掉一次冷却，门链顺序也丢了。
- 配置值由调用点按**字面键名**取好再交进来（先例 ``ProactiveActionKnobs``）：动态
  键名会让配置登记总账的直读尺看不见这些键，11 枚 poke/randpic 键曾被记成
  「登记了却零读点」＝静默失效预备役。

顺序即语义（与 ``proactive_action_allowed`` 同判据）：开关 → 有目标 → 名单 →
安静窗 → 五层门。名单与安静窗必须在门之前——门 ``allow`` 返回真即登记冷却，
把「被安静窗拦下」记进冷却等于让拦不住的门反咬后续动作。

**决策件与活路径双轨，等价性由测试锁**（2026-10-03 互动面波注记）：本件建成但
**零生产接线**——生产随机发图今天跑的是根装配活路径（``proactive_action_allowed``
+ ``pick_gallery_image``，三触发各自的历史字面 seed）。等价性由
``tests/test_decision_pieces_dualtrack_lock.py`` 现算锁住：同输入下门链顺序
（disabled/blocked/quiet/门判）、``allow_exhausted`` 三时机档、桶账键
（``canonical_bucket_key`` 即活路径窗账的真实记账键）逐格一致。已知口径差
（锁里写明，接线时以本件为准并同步翻活路径）：**seed 两件不同形**——活路径被戳
seed ``poke-randpic:{poker}:{group}`` 缺消息维（既有现状刻画锁在案），本件
``dispatch_seed`` 是补上消息维的设计接任者；指令路 seed 两件逐字节同形。
"""

from __future__ import annotations

from dataclasses import dataclass

from plugins.bot_unified_runtime.domains.meme.capabilities import randpic

TIMING_COMMAND: str = "command"
TIMING_AFTER_REPLY: str = "after_reply"
TIMING_POKE: str = "poke"

#: 三时机在册（别处再立一枚时机名 ⇒ 这条锁当场红，防「第四腿偷偷长出来没人管」）。
KNOWN_TIMINGS: frozenset[str] = frozenset({TIMING_COMMAND, TIMING_AFTER_REPLY, TIMING_POKE})

_CAPABILITY_ID = "bot.randpic"

#: 每个时机的盐（掷骰与种子都带它）：三条腿各掷各的，绝不共用同一枚骰子。
_TIMING_SALTS: dict[str, str] = {
    TIMING_COMMAND: "randpic-command",
    TIMING_AFTER_REPLY: "randpic-dispatch",
    TIMING_POKE: "poke-randpic",
}

#: 整库都在窗内时怎么办：指令路退「最久没发」（用户开口要图，拒不发更糟）；
#: 两条主动路宁缺不刷屏（主动动作发重复图正是 ITEM 15(b) 的字面禁令）。
_ALLOW_WHEN_EXHAUSTED: dict[str, bool] = {
    TIMING_COMMAND: True,
    TIMING_AFTER_REPLY: False,
    TIMING_POKE: False,
}


@dataclass(frozen=True)
class RandpicKnobs:
    """一次判定的四枚门参数 + 窗长（值由调用点按字面键名取，本件不读配置）。"""

    enabled: bool = False
    probability: float = 0.0
    cooldown_seconds: float = 0.0
    max_per_hour: int = 0
    window_seconds: float = 0.0


@dataclass(frozen=True)
class RandpicTurn:
    """这一轮的场合：时机 + 会话 + 消息 + 群/个人。"""

    timing: str = TIMING_AFTER_REPLY
    session_key: str = ""
    message_key: str = ""
    group_id: str = ""
    user_id: str = ""


@dataclass(frozen=True)
class RandpicPlan:
    """判定结论：发不发、为什么、按哪个桶记不重发账、用哪个种子取图。"""

    send: bool = False
    reason: str = "planned"
    bucket_key: str = ""
    seed: str = ""
    allow_exhausted: bool = False
    salt: str = ""
    capability_id: str = _CAPABILITY_ID
    audit_tags: tuple[str, ...] = ()

    @property
    def held(self) -> bool:
        return not self.send


def plan_randpic(
    turn: RandpicTurn,
    knobs: RandpicKnobs,
    *,
    seed: str = "",
    gate_verdict: tuple[bool, str] | None = None,
    blocked: bool = False,
    quiet_active: bool = False,
) -> RandpicPlan:
    """三时机合一的判定（纯的：同样的输入永远给同样的结论）。

    ``blocked`` / ``quiet_active`` 是调用侧**已经判过的数据**；``gate_verdict`` 是
    五层门算好的 ``(放行?, 拒因)``，缺省 ``None``＝「还没掷骰」。两阶段契约由此成立：

    1. 先 ``plan_randpic(turn, knobs, seed=..., blocked=..., quiet_active=...)``，
       拿到 ``reason == "gate_pending"`` 才去叫门——门 ``allow``/``verdict`` 判定即
       commit（登记冷却与滑窗），把它放在开关/名单/安静窗之前，等于让拦不住的门
       反咬后续动作（``proactive_action_allowed`` 同一条顺序判据）；
    2. 拿到门的 ``(bool, code)`` 后再叫一次本件，得到终判。

    判定件因此可以在离线测试里逐格断言：不需要 NoneBot、不需要真机、不碰用户图库。
    """
    timing = str(turn.timing or "")
    bucket = randpic.canonical_bucket_key(str(turn.session_key or ""))
    salt = _TIMING_SALTS.get(timing, f"randpic-{timing or 'unknown'}")
    exhausted = _ALLOW_WHEN_EXHAUSTED.get(timing, False)
    roll = str(seed or "")

    def _held(code: str) -> RandpicPlan:
        return RandpicPlan(
            send=False,
            reason=code,
            bucket_key=bucket,
            seed=roll,
            allow_exhausted=exhausted,
            salt=salt,
            audit_tags=("randpic", f"timing:{timing or 'unknown'}", f"reason_{code}", "held"),
        )

    def _go(code: str) -> RandpicPlan:
        return RandpicPlan(
            send=True,
            reason=code,
            bucket_key=bucket,
            seed=roll,
            allow_exhausted=exhausted,
            salt=salt,
            audit_tags=("randpic", f"timing:{timing or 'unknown'}", f"reason_{code}"),
        )

    if not knobs.enabled:
        return _held("disabled")
    if timing == TIMING_COMMAND:
        # 指令路＝用户开口要图：不吃概率、不吃冷却（拒发比不发更糟），也不看安静窗
        # （门链在路由前已经过一次，这里再判一次会把「用户主动问」也拦下来）。
        return _go("command")
    if timing not in KNOWN_TIMINGS:
        return _held("unknown_timing")
    if not str(turn.user_id or "").strip():
        return _held("no_target")
    if blocked:
        return _held("blocked_target")
    if quiet_active:
        return _held("quiet_hours")
    if gate_verdict is None:
        return _go("gate_pending")
    allowed, code = gate_verdict
    if not allowed:
        return _held(str(code or "gate_denied"))
    if not roll:
        # 种子为空 ⇒ 同一会话会反复掷出同一张（可复现 ≠ 总发同一张）：宁可不发。
        return _held("empty_seed")
    return _go(f"planned_{timing}")


def dispatch_seed(timing: str, session_key: str, message_key: str) -> str:
    """种子真身：时机 + 会话 + 消息三维都在串里。

    同一条消息重放判定恒定（可复现、可审计），换一条消息就换一个种子
    （不得总发同一张）。指令路那一枚的字面 f-string 仍住在能力层
    （``tests/test_poke_randpic_behavior.py`` 按 AST 认那处形状，搬走会让锁当场红），
    本函数与它逐字节同形，由 ``tests/test_randpic_timing_plan.py`` 钉住对齐。
    """
    name = str(timing or "")
    session = str(session_key or "")
    message = str(message_key or "")
    if name == TIMING_COMMAND:
        return f"randpic:{session}:{message}"
    return f"randpic:{name or 'unknown'}:{session}:{message}"


def is_known_timing(name: str) -> bool:
    return str(name or "") in KNOWN_TIMINGS
