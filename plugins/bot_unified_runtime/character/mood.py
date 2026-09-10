"""机器人自身的心情状态机（L1：分钟-小时尺度的连续情绪）。

与好感层的时间尺度严格分离：心情（本模块，分钟-小时）→ 动态好感
（affinity.py，天-周）→ 人格档案（persona_set.py，周-月）。设计借鉴
MaiBot「bot 自身有一个被互动事件驱动、随时间回归基线的连续心情」的思路，
全部代码、表结构与数值均为本仓库原创。

模型：二维连续空间
- valence（愉悦度，-1..1，基线 0.0）：正=愉快想聊，负=低落冷淡；
- arousal（唤醒度，0..1，基线 baseline_arousal 默认 0.3）：高=兴奋/烦躁，低=慵懒。

机制：
- 指数衰减：每次读写都把状态向基线收敛——
  value = baseline + (value - baseline) * 0.5 ** (流逝分钟 / half_life_minutes)。
  写回落库（write-back）：即使长期无人读，下次读/写也会从持久化的
  updated_at 重算衰减，跨进程重启结果一致。
- apply_event：钳位 [-1,1] / [0,1]，并施加滚动窗口速率帽——
  任意 3600 秒窗口内「已施加的 valence 增量绝对值之和」不超过
  rate_cap_per_hour（默认 0.5）。超帽部分被截断而非整次拒绝：
  remaining = cap - 窗口内已用额度，本次实际施加
  clamp(requested, -remaining, +remaining)，只对 valence 记账
  （arousal 单项增量本身 ≤0.15，无围攻放大效应，不占额度）。
  窗口记账存进程内存（deque），进程重启即清零——重启后的第一个
  窗口不受重启前事件约束，属可接受折衷（衰减与钳位仍在兜底）。
- observe_interaction：把 affinity.classify_behavior 的行为标签与
  RuleBasedEmotionProvider 的 EmotionSignal 标签映射为小幅增量：

  | 信号                    | valence | arousal |
  |------------------------|---------|---------|
  | behavior positive      | +0.06   |  0.00   |
  | behavior neutral       |  0.00   |  0.00   |
  | behavior tease         | +0.02   | +0.03   |
  | behavior negative      | -0.10   | +0.10   |
  | behavior insult        | -0.18   | +0.15   |
  | emotion support_needed | -0.03   | +0.05   |
  | emotion lonely         | -0.03   | +0.05   |
  | emotion frustrated     | -0.05   | +0.08   |
  | emotion help_seeking   |  0.00   | +0.04   |
  | emotion low_energy     |  0.00   | -0.05   |
  | 其他/未知标签           |  0.00   |  0.00   |

  多标签同时命中时增量逐项累加，再交给 apply_event（钳位+限速）。
- describe：纯中文自然语言（无数字），确定性映射，供 prompt 注入；
- willingness_factor：[0.75, 1.25] 乘性系数——低落 <1（不想插话），
  愉悦+高唤醒 >1（更爱接话）；只调概率/预算，绝不做硬开关。

线程模型与 affinity.py 相同：进程内单一 SQLite 连接 + threading.Lock
串行全部读写，check_same_thread=False 允许事件循环与 offload 线程池共用。
"""

from __future__ import annotations

import calendar
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# ---- 衰减 ----
_VALENCE_BASELINE = 0.0
_DEFAULT_HALF_LIFE_MINUTES = 120.0
_DEFAULT_BASELINE_AROUSAL = 0.3
# ---- 速率帽：任意 3600s 滚动窗口内 |已施加 valence 增量| 之和的上限 ----
_RATE_WINDOW_SECONDS = 3600.0
_DEFAULT_RATE_CAP_PER_HOUR = 0.5
# ---- describe 的确定性分档阈值 ----
_V_POSITIVE = 0.25   # valence >= 0.25 视为愉悦档
_V_NEGATIVE = -0.25  # valence <= -0.25 视为低落档
_V_STRONG = 0.55     # 强档：愉悦→很想说话 / 低落→不想搭理人
_A_HIGH = 0.75       # arousal >= 0.75 高唤醒
_A_LOW = 0.20        # arousal <= 0.20 低唤醒
# ---- willingness_factor：乘性系数 = clamp(1 + 0.20v + 0.10·v·a, 0.75, 1.25) ----
_WILLINGNESS_MIN = 0.75
_WILLINGNESS_MAX = 1.25
_WILLINGNESS_VALENCE_GAIN = 0.20
_WILLINGNESS_AROUSAL_GAIN = 0.10

# 行为 → (valence 增量, arousal 增量)；键与 affinity.classify_behavior 输出一致。
_BEHAVIOR_MOOD: dict[str, tuple[float, float]] = {
    "positive": (0.06, 0.0),
    "neutral": (0.0, 0.0),
    "tease": (0.02, 0.03),
    "negative": (-0.10, 0.10),
    "insult": (-0.18, 0.15),
}
# 情绪信号标签 → (valence 增量, arousal 增量)；键与
# character/emotion.py RuleBasedEmotionProvider 的 label 一致。
_EMOTION_MOOD: dict[str, tuple[float, float]] = {
    "support_needed": (-0.03, 0.05),
    "lonely": (-0.03, 0.05),
    "frustrated": (-0.05, 0.08),
    "help_seeking": (0.0, 0.04),
    "low_energy": (0.0, -0.05),
}


@dataclass(frozen=True)
class BotMood:
    """某一时刻的心情快照；updated_at 为注入时钟的 epoch 秒。"""

    valence: float
    arousal: float
    updated_at: float


def _clamp_valence(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _clamp_arousal(value: float) -> float:
    return max(0.0, min(1.0, value))


def _format_utc(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _parse_utc(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")))
    except (ValueError, TypeError):
        return None


class BotMoodStore:
    """SQLite 单行机器人心情；线程安全；读路径惰性衰减并写回。"""

    def __init__(
        self,
        db_path: str | Path,
        *,
        half_life_minutes: float = _DEFAULT_HALF_LIFE_MINUTES,
        baseline_arousal: float = _DEFAULT_BASELINE_AROUSAL,
        rate_cap_per_hour: float = _DEFAULT_RATE_CAP_PER_HOUR,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if half_life_minutes <= 0.0:
            raise ValueError("half_life_minutes must be positive")
        if rate_cap_per_hour < 0.0:
            raise ValueError("rate_cap_per_hour must be non-negative")
        self.db_path = Path(db_path)
        self._half_life_minutes = float(half_life_minutes)
        self._baseline_arousal = _clamp_arousal(float(baseline_arousal))
        self._rate_cap_per_hour = float(rate_cap_per_hour)
        self._clock: Callable[[], float] = clock if clock is not None else time.time
        self._lock = threading.Lock()
        # 进程内复用单一连接：被动感知每条消息 observe/snapshot 各一次，
        # 全部操作已在 self._lock 下串行，check_same_thread=False 允许
        # 事件循环与 offload 线程池跨线程共用同一连接（同 affinity.py）。
        self._connection: sqlite3.Connection | None = None
        # 速率帽滚动窗口：(时间戳, 已施加 valence 增量绝对值)。仅存内存，
        # 进程重启清零（见模块 docstring 的重启折衷说明）。
        self._rate_window: deque[tuple[float, float]] = deque()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_mood (
                    id INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
                    valence REAL NOT NULL DEFAULT 0.0,
                    arousal REAL NOT NULL DEFAULT 0.3,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # WAL：被动感知线程写、prompt 组装线程读并发，降低阻塞窗口。
            # 必须先于任何 DML 执行（INSERT 的隐式事务里切 WAL 会报错）。
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "INSERT OR IGNORE INTO bot_mood (id, valence, arousal, updated_at)"
                " VALUES (1, ?, ?, ?)",
                (
                    _VALENCE_BASELINE,
                    self._baseline_arousal,
                    _format_utc(float(self._clock())),
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            connection = sqlite3.connect(
                self.db_path, timeout=5.0, check_same_thread=False
            )
            connection.row_factory = sqlite3.Row
            self._connection = connection
        return self._connection

    def _decayed_values(
        self, valence: float, arousal: float, updated: float, now: float
    ) -> tuple[float, float]:
        """指数衰减：距 updated 每过一个半衰期，相对基线的偏移减半。"""
        elapsed_minutes = max(0.0, now - updated) / 60.0
        factor = 0.5 ** (elapsed_minutes / self._half_life_minutes)
        return (
            _VALENCE_BASELINE + (valence - _VALENCE_BASELINE) * factor,
            self._baseline_arousal + (arousal - self._baseline_arousal) * factor,
        )

    def _capped_valence_delta(self, requested: float, now: float) -> float:
        """速率帽：返回本次实际施加的 valence 增量（超帽部分截断为 0）。

        窗口为 (now-3600, now]；窗口内已用额度 = 各次已施加增量绝对值之和；
        remaining = cap - 已用，实际施加 clamp(requested, -remaining, +remaining)。
        """
        window = self._rate_window
        cutoff = now - _RATE_WINDOW_SECONDS
        while window and window[0][0] <= cutoff:
            window.popleft()
        used = sum(abs(delta) for _, delta in window)
        remaining = self._rate_cap_per_hour - used
        if remaining <= 0.0:
            return 0.0
        applied = max(-remaining, min(remaining, requested))
        if applied != 0.0:
            window.append((now, abs(applied)))
        return applied

    def _load_row(
        self, connection: sqlite3.Connection, now: float
    ) -> tuple[float, float]:
        row = connection.execute(
            "SELECT valence, arousal, updated_at FROM bot_mood WHERE id = 1"
        ).fetchone()
        if row is None:
            # _ensure_schema 已 INSERT 默认行，理论上不可达；防御回退默认态。
            return _VALENCE_BASELINE, self._baseline_arousal
        valence = float(row["valence"])
        arousal = float(row["arousal"])
        updated = _parse_utc(str(row["updated_at"]))
        if updated is None:
            return _clamp_valence(valence), _clamp_arousal(arousal)
        valence, arousal = self._decayed_values(valence, arousal, updated, now)
        return (
            _clamp_valence(valence),
            _clamp_arousal(arousal),
        )

    def _persist(
        self, connection: sqlite3.Connection, valence: float, arousal: float, now: float
    ) -> None:
        connection.execute(
            "UPDATE bot_mood SET valence = ?, arousal = ?, updated_at = ? WHERE id = 1",
            (valence, arousal, _format_utc(now)),
        )

    def snapshot(self, now: float | None = None) -> BotMood:
        """读取当前心情；惰性衰减到 now 并写回落库（重启一致）。"""
        now_f = float(self._clock()) if now is None else float(now)
        with self._lock, self._connect() as connection:
            valence, arousal = self._load_row(connection, now_f)
            self._persist(connection, valence, arousal, now_f)
            return BotMood(valence=valence, arousal=arousal, updated_at=now_f)

    def apply_event(
        self,
        valence_delta: float,
        arousal_delta: float,
        now: float | None = None,
    ) -> BotMood:
        """注入一次事件：先衰减到 now，再施加限速后的增量并钳位落库。"""
        now_f = float(self._clock()) if now is None else float(now)
        with self._lock, self._connect() as connection:
            valence, arousal = self._load_row(connection, now_f)
            applied_valence = self._capped_valence_delta(float(valence_delta), now_f)
            valence = _clamp_valence(valence + applied_valence)
            # arousal 不占速率帽额度（见模块 docstring 速率帽语义）。
            arousal = _clamp_arousal(arousal + float(arousal_delta))
            self._persist(connection, valence, arousal, now_f)
            return BotMood(valence=valence, arousal=arousal, updated_at=now_f)

    def observe_interaction(
        self, behavior_label: str, emotion_labels: list[str]
    ) -> BotMood:
        """被动感知便捷入口：行为+情绪标签按映射表累加后走 apply_event。

        未知标签按 (0, 0) 计；全零增量也会触发一次衰减写回，返回最新快照。
        """
        behavior_delta = _BEHAVIOR_MOOD.get(behavior_label, (0.0, 0.0))
        valence_delta = behavior_delta[0]
        arousal_delta = behavior_delta[1]
        for label in emotion_labels:
            emotion_delta = _EMOTION_MOOD.get(label, (0.0, 0.0))
            valence_delta += emotion_delta[0]
            arousal_delta += emotion_delta[1]
        return self.apply_event(valence_delta, arousal_delta)

    def describe(self, mood: BotMood) -> str:
        """心情的确定性中文短语（无数字），供 prompt 注入。"""
        valence = mood.valence
        arousal = mood.arousal
        if valence >= _V_POSITIVE:
            if arousal >= _A_HIGH:
                if valence >= _V_STRONG:
                    return "心情不错，很想说话"
                return "心情不错，有点兴奋"
            if arousal <= _A_LOW:
                return "心情不错，安安稳稳的"
            return "心情不错，挺有精神的"
        if valence <= _V_NEGATIVE:
            if arousal >= _A_HIGH:
                return "有点低落，也静不下来"
            if valence <= -_V_STRONG:
                return "有点低落，不太想搭理人"
            if arousal <= _A_LOW:
                return "有点低落，提不起劲"
            return "有点低落"
        if arousal >= _A_HIGH:
            return "有点烦躁，静不下来"
        if arousal <= _A_LOW:
            return "懒洋洋的，没什么劲"
        return "挺平静的"

    def willingness_factor(self, mood: BotMood) -> float:
        """插话意愿乘性系数 [0.75, 1.25]：低落 <1，愉悦+高唤醒 >1。

        = clamp(1 + 0.20*valence + 0.10*valence*arousal, 0.75, 1.25)，
        对 valence 单调；调用方只乘在概率/预算上，绝不做硬开关。
        """
        raw = (
            1.0
            + _WILLINGNESS_VALENCE_GAIN * mood.valence
            + _WILLINGNESS_AROUSAL_GAIN * mood.valence * mood.arousal
        )
        return max(_WILLINGNESS_MIN, min(_WILLINGNESS_MAX, raw))
