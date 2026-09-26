"""creation 生成任务的持久真身：在途/终态记录 + 对账读回 + 幂等去重 + 保留期裁剪。

为什么必须有这一件（S35，接替 S17）：``image/engine_provider.py`` 的在途分支与语音侧
``GET /api/v1/tts/jobs/{id}`` 今天只能给 **DEGRADED / 503**，原因逐字记在 S09 的 R-2 与
S08 的「拒绝自建第二份状态」里——「**无 job store／reconcile 真身 ⇒ handle 给不出真
终态**」。协议侧三条教义（``UNKNOWN_NEVER_AUTO_REDISPATCH``、
``CANCEL_REQUESTED_IS_NOT_A_STATE``、未终态不得宣布产物）此前都是「写得出、查不到」：
没有任何一处能回答「这一条请求上次落到哪一步了」。本件就是那枚回答。

四条判据（都可注毒打死，不是散文）：

1. **状态词只准用契约已有的枚举**——建表 ``CHECK`` 由 ``JOB_STATES`` **派生**（不手抄
   第二份名单），写侧与读侧都过 ``CreationJob`` 契约自验；库里出现契约外的 state ⇒ 该行
   判为坏行（点名跳过），**绝不**翻译成一个近似的合法态。
2. **幂等键必须过中央合法段字符集**——段规则唯一住
   ``domains/emergency_info/service/dedupe.py``（AGENTS 禁碰面点名），本件**委托**它的
   ``is_legal_segment``，零自建正则。本仓为此付过两次账：紧急域把 ``nmc:A1`` 拼进条目 id
   ⇒ 每一条真投递抛 ``ValueError``；回执直拼 ``session_id`` ⇒ 开闸态整条判 skip＝静默丢。
   两次都是「本地全绿、上线零发」。
3. **prune 只裁已终态、绝不裁在途**，且 ``unknown`` 也不裁——它是「不重发」的身份凭据，
   被 GC 掉等于把一条可能已经花钱的任务悄悄放回可重发池。
4. **一次操作一条连接、出口必关**——家规形态抄
   ``domains/emergency_info/sources/store.py`` 的 ``@contextmanager _connect()``
   （``sqlite3`` 的 ``with conn`` 只 commit 不 close，Windows 上直接表现为库文件删不掉）。

一处刻意的分层（读代码前先看这段，否则会误判「为什么这里没有 sqlite3」）：本域受常驻门
``tests/test_v21_creation_skeleton.py::test_reserved_modules_forbidden_imports`` 约束——
``domains/creation/`` 下**任何** .py 都不得 import ``sqlite3``/``os``/``pathlib``
（§9.4 契约形态 lint，V21-CORE-001 零副作用探针的静态半边）。因此本件**不自己开库**：
调用方交来一个 ``connect``（一次返回一条连接，由它负责打开与配置 row_factory），
而**提交与关闭的纪律仍在本件**（``_connection()`` 出口必关、异常路径也关，由
``tests/test_creation_job_store.py`` 的句柄计数与「库文件可删」两把锁钉住）。
本席不用 ``importlib`` 偷渡 sqlite3——那是绕门，不是分层。装配层落地时一行即可：
``CreationJobStore(connect=lambda: sqlite3.connect(path, timeout=10))``。

纪律：零网络、零线程、零生产配置读取、零 ``hashlib``（域内禁第二套摘要算法家）、零状态机
副本（迁移判定直引 ``can_transition``）、零无界进程内状态（坏行观测环有界）。
"""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    is_legal_segment,
)

from ..reserved_provider import CHANNEL_IDS
from .contracts import (
    CREATION_ERROR_CATALOG,
    DIGEST64_PATTERN,
    JOB_STATES,
    NON_TERMINAL_JOB_STATES,
    TERMINAL_JOB_STATES,
    AssetRef,
    CreationErrorCode,
    CreationJob,
    CreationJobState,
    UsageLine,
    _require_aware_utc,
    can_transition,
)

_LOGGER = logging.getLogger(__name__)

#: 表名（全仓唯一，禁第二张 creation 任务表）。
JOB_TABLE = "creation_jobs"
#: 保留期缺省（家规同 campus/emergency：只裁条目，防库无界增长）。
DEFAULT_KEEP_DAYS = 90
#: 一次读回的硬上限：limit 非正即空表，**绝不**放开成全表扫描（同 emergency 口径）。
MAX_LIST_LIMIT = 500
#: 坏行观测环容量（有界，防「跳过很多」变成内存泄漏）。
SKIP_AUDIT_CAPACITY = 50
#: 任务标识长度上限（与契约 ``job_id`` 的 max_length 同值，不另立一把尺）。
_IDENTIFIER_MAX_CHARS = 128

#: 契约状态机的字面清单（**派生自** ``JOB_STATES``，不手抄第二份名单）。
_STATE_VALUES: tuple[str, ...] = tuple(sorted(JOB_STATES))
#: 通道清单**派生自** ``reserved_provider.CHANNEL_IDS``（本域在册通道的唯一清单）。
_CHANNEL_VALUES: tuple[str, ...] = tuple(sorted(CHANNEL_IDS))

STATE_CHECK_SQL = ", ".join(f"'{state}'" for state in _STATE_VALUES)
CHANNEL_CHECK_SQL = ", ".join(f"'{channel}'" for channel in _CHANNEL_VALUES)

# 段字符集规则**不在本文件重写**——判据唯一住 dedupe._SEGMENT_RE（AGENTS 禁碰面）。
# 这里只把契约的摘要形态常量编一次：形态的家在 contracts，本处只是它的编译器。
_DIGEST_RE = re.compile(DIGEST64_PATTERN)

_SELECT_COLUMNS = (
    "job_id, channel, state, workspace_id, provider_operation, idempotency_key, "
    "error_code, cancel_requested, cancel_requested_at, created_at, updated_at, "
    "assets_json, usage_json"
)

#: 连接开口所需的最小面（sqlite3.Connection 结构上即满足；缺失即 fail-closed 点名）。
_REQUIRED_CONNECTION_API: tuple[str, ...] = ("execute", "executescript", "commit", "close")


class JobStoreError(ValueError):
    """写入被拒（形态/键段/通道不成立）。

    刻意继承 ``ValueError``：与 ``build_emergency_dedupe_key`` 同族——「不拼假键」是
    编程错误而非运行时故障，绝不静默收下（本仓两次事故的共同根因就是替用户圆）。
    """


def build_job_store_schema() -> str:
    """建表脚本（state/channel 两处 CHECK 由契约与在册清单**派生**）。

    ``error_code`` 与 ``state`` 的配对教义**不进 SQL**：那条规则的家在
    ``CreationJob._doctrines``，本件每次写、每次读都过它。把同一条判定再抄一份进 CHECK
    就是第二真身，而且抄的那份只会漏（它不知道「unknown 必带幂等键」的动机）。
    """
    return f"""
CREATE TABLE IF NOT EXISTS {JOB_TABLE} (
    job_id              TEXT PRIMARY KEY,
    channel             TEXT NOT NULL CHECK (channel IN ({CHANNEL_CHECK_SQL})),
    state               TEXT NOT NULL CHECK (state IN ({STATE_CHECK_SQL})),
    workspace_id        TEXT NOT NULL DEFAULT '',
    provider_operation  TEXT,
    idempotency_key     TEXT,
    error_code          TEXT,
    cancel_requested    INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    cancel_requested_at TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    assets_json         TEXT NOT NULL DEFAULT '[]',
    usage_json          TEXT NOT NULL DEFAULT '[]'
);
-- 同一请求身份只允许一条任务：这是 UNKNOWN_NEVER_AUTO_REDISPATCH 在存储侧的落点。
-- 「不重发」要能判，前提是重发方查得到那一条——所以这枚唯一索引不是优化，是教义。
-- （登记面诚实：SQLite 不支持带过滤的 CREATE INDEX IF NOT EXISTS 之外的部分索引写法之外
--  的方言问题；本处用的是 SQLite 原生 partial index，3.8+ 可用。）
CREATE UNIQUE INDEX IF NOT EXISTS idx_creation_jobs_idempotency
    ON {JOB_TABLE}(idempotency_key)
    WHERE idempotency_key IS NOT NULL;
-- 对账扫描的主形态：按「是否终态 + 新旧」捞在途。
CREATE INDEX IF NOT EXISTS idx_creation_jobs_state
    ON {JOB_TABLE}(state, updated_at);
CREATE INDEX IF NOT EXISTS idx_creation_jobs_operation
    ON {JOB_TABLE}(provider_operation);
"""


def job_store_schema_sql() -> str:
    """``build_job_store_schema()`` 的别名口（同一真身，不出第二份 SQL）。"""
    return build_job_store_schema()


def is_legal_job_identifier(value: object) -> bool:
    """能否当任务侧标识（job_id / provider_operation）：委托中央段规则，零副本。

    单独开口的理由与 ``is_legal_segment`` 同：调用方（采集/对账轮询）要能在写库**之前**
    把注定建不出键的形态点名跳过，而不是让它在落库时抛异常、把整轮一起带走。
    """
    return is_legal_segment(str(value or ""))


def _quoted(values: Iterable[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _format_utc(moment: datetime) -> str:
    """统一落库格式（aware UTC ISO，字典序即时间序）。"""
    return _require_aware_utc("job_store 时间", moment).isoformat()


def _parse_utc(raw: object) -> datetime:
    """解析库内时间；不可解析 ⇒ 抛错，由调用方判坏行（绝不猜一个时刻）。"""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("空时间戳")
    return _require_aware_utc("job_store 时间", datetime.fromisoformat(text))


def _none_if_blank(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_utc(value: object) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    return _parse_utc(value)


#: 错误码词表**派生自** ``_common.CREATION_ERROR_CATALOG``（单一注册源），不另列名单。
_ERROR_CODES: frozenset[str] = frozenset(CREATION_ERROR_CATALOG)


def _error_code_of(value: object) -> CreationErrorCode | None:
    """错误码进出库都问单一注册源：认不出来就抛，由调用方决定 loud 还是点名。

    ``cast`` 只在这里出现一次，且**紧跟在册性检查**——它替的是「pydantic Literal 无法
    由 frozenset 成员判定自动收窄」这一步，不替任何校验：不在册的值走不到 cast。
    """
    text = _none_if_blank(value)
    if text is None:
        return None
    if text not in _ERROR_CODES:
        raise ValueError(f"错误码 {text!r} 不在册（唯一家 CREATION_ERROR_CATALOG）")
    return cast("CreationErrorCode", text)


def _is_unique_conflict(exc: BaseException) -> bool:
    """只认「唯一约束冲突」，其余异常原样上抛（兜底 except 吞异常是本仓的老病）。"""
    if type(exc).__name__ != "IntegrityError":
        return False
    text = str(exc).lower()
    return "unique" in text or "primary key" in text


def _row_mapping(row: Any) -> dict[str, Any]:
    """sqlite3.Row / dict 都能按键取；取不到 ⇒ 抛错交上层点名（不静默当成「没有这行」）。"""
    if isinstance(row, dict):
        return dict(row)
    keys = getattr(row, "keys", None)
    if callable(keys):
        return {str(name): row[name] for name in keys()}
    raise TypeError("行不支持按键读取（connect 需配置 row_factory=sqlite3.Row 或等价形态）")


@dataclass(frozen=True)
class RegisterOutcome:
    """一次登记的结果；撞键不抛异常而是点名既有任务，便于对账循环逐条记账。"""

    created: bool
    job_id: str
    #: 撞幂等键时点名**已有**那条任务——重发方据此决定「不再发」，而不是自己猜。
    existing_job_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class AdvanceOutcome:
    """一次状态推进的结果；``moved=False`` 必带原因（诚实缺位不得静默）。"""

    moved: bool
    job_id: str
    state: CreationJobState | None = None
    reason: str = ""


@dataclass(frozen=True)
class StoredJob:
    """一条任务的完整在册形态：契约 DTO + 两枚**存储侧**事实。

    ``channel``/``workspace_id`` 不在 ``CreationJob`` 里（它们是"这条任务归谁办"的
    装配事实，不是"任务现在怎么样"的协议事实），但对账与按 id 回读必须有通道才能问
    provider——故在此并列，而不是回头给契约 DTO 加字段（契约归契约，本席禁改）。
    """

    job: CreationJob
    channel: str
    workspace_id: str = ""
    created_at: datetime | None = None


class CreationJobStore:
    """creation 任务库：登记 / 读回 / 推进（带并发守卫）/ 取消标记 / 对账扫描 / 裁剪。

    ``connect`` 由装配层提供（一次返回一条连接）；本件保证**每个操作出口必关**，异常路径
    同样关。``now`` 注入只为离线确定性，缺省系统 UTC 钟。
    """

    def __init__(
        self,
        connect: Callable[[], Any],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(connect):
            raise JobStoreError("connect 必须是可调用（一次返回一条连接）")
        self._connect_factory = connect
        self._now = now or (lambda: datetime.now(timezone.utc))
        # 有界观测环：坏行点名用，绝不无界增长。
        self._skips: deque[tuple[str, str]] = deque(maxlen=SKIP_AUDIT_CAPACITY)

    # ------------------------------------------------------------------ 连接

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        """一次操作一条连接，**出口必关**（家规形态见模块头判据 4）。

        ``sqlite3`` 的 ``with conn:`` 只 commit 不 close；对账轮询按分钟跑，句柄会按调用
        次数累积，Windows 上先表现为库文件删不掉。
        """
        connection = self._connect_factory()
        missing = [
            name for name in _REQUIRED_CONNECTION_API if not callable(getattr(connection, name, None))
        ]
        if missing:
            # 先关再抛：开口不合格也不把句柄留在外面（fail-closed，且不留泄漏）。
            try:
                connection.close()
            except Exception:
                # 关闭失败**不盖住**真正的告警（形状不符才是主因），但也不能静默吞：
                # 留一条 debug，让"关不掉"这件事在日志里有迹可循。
                _LOGGER.debug("creation job store: unfit connection close failed", exc_info=True)
            raise JobStoreError(
                f"connect 返回的连接缺少必需方法 {missing}"
                "（需要 execute/executescript/commit/close）"
            )
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def ensure_schema(self) -> None:
        """建表 + 建索引（幂等：``IF NOT EXISTS`` 全齐，重复调用零副作用）。"""
        with self._connection() as connection:
            connection.executescript(build_job_store_schema())

    # ------------------------------------------------------------------ 观测

    def recent_skips(self) -> tuple[tuple[str, str], ...]:
        """最近被点名的坏行 ``(job_id 前缀, 原因)``；有界、只作观测。"""
        return tuple(self._skips)

    def state_counts(self) -> dict[str, int]:
        """各状态行数（控制面回读用）：契约状态全集打底，缺档记 0，不出现「查不到」。"""
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT state, COUNT(*) FROM {JOB_TABLE} GROUP BY state"
            ).fetchall()
        counts = {state: 0 for state in _STATE_VALUES}
        for row in rows:
            key, value = _row_pair(row)
            counts[str(key)] = int(value)
        return counts

    def _note_skip(self, job_id: object, reason: str) -> None:
        label = str(job_id or "")[:64]
        self._skips.append((label, reason))
        _LOGGER.warning("creation job store skipped a row: job=%s reason=%s", label, reason)

    # ------------------------------------------------------------------ 写入

    def register(
        self,
        job: CreationJob,
        *,
        channel: str,
        workspace_id: str = "",
    ) -> RegisterOutcome:
        """登记一条任务（幂等插入）。

        三道写前门，逐道点名：通道在册（``CHANNEL_IDS`` 唯一清单）、``job_id`` 与
        ``provider_operation`` 过中央段规则。任何一道不过 ⇒ ``JobStoreError``，**绝不**
        洗成「看起来能用」的形态再落库（两次事故的共同根因就是替用户圆）。

        撞幂等键 ⇒ 不新增、返回既有 ``job_id``：这就是「未知不重发」能被执行的地方。
        """
        if channel not in _CHANNEL_VALUES:
            raise JobStoreError(f"未知 creation 通道 {channel!r}（在册：{list(_CHANNEL_VALUES)}）")
        self._require_identifier(job.job_id, "job_id")
        if job.provider_operation is not None:
            self._require_identifier(job.provider_operation, "provider_operation")
        moment = _format_utc(self._now())
        params: tuple[Any, ...] = (
            job.job_id,
            channel,
            job.state.value,
            str(workspace_id or "").strip()[:_IDENTIFIER_MAX_CHARS],
            job.provider_operation,
            job.idempotency_key,
            job.error_code,
            1 if job.cancel_requested else 0,
            _format_utc(job.cancel_requested_at) if job.cancel_requested_at else None,
            moment,
            # created_at=库里这一行何时建；updated_at=**任务自己说**它何时变更（契约值，
            # 不拿装配钟顶替——两者相差多久，正是「登记延迟」这件事本身的可观测面）。
            _format_utc(job.updated_at),
            _assets_json(job.assets),
            _usage_json(job.usage),
        )
        try:
            with self._connection() as connection:
                connection.execute(
                    f"""
                    INSERT INTO {JOB_TABLE} (
                        job_id, channel, state, workspace_id, provider_operation,
                        idempotency_key, error_code, cancel_requested,
                        cancel_requested_at, created_at, updated_at,
                        assets_json, usage_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )
        except Exception as exc:  # 只认幂等冲突，其余原样上抛（不吞）
            if not _is_unique_conflict(exc):
                raise
            existing = self.find_by_idempotency_key(job.idempotency_key)
            return RegisterOutcome(
                created=False,
                job_id=job.job_id,
                existing_job_id=None if existing is None else existing.job_id,
                reason=(
                    "同一条请求已有任务（幂等键冲突）：不重发、不再登记"
                    if existing is not None
                    else "同 job_id 已登记：不覆盖既有任务"
                ),
            )
        return RegisterOutcome(created=True, job_id=job.job_id, reason="已登记")

    def advance(
        self,
        job_id: str,
        target: CreationJobState,
        *,
        assets: tuple[AssetRef, ...] = (),
        usage: tuple[UsageLine, ...] = (),
        error_code: str | None = None,
        provider_operation: str | None = None,
        expected_state: CreationJobState | None = None,
    ) -> AdvanceOutcome:
        """推进状态：迁移合法性问契约，**并发守卫写进 SQL**。

        - 迁移判定不自立一套：``can_transition`` 是唯一尺子（终态无出边、unknown 不复活）；
        - 写回前用 ``CreationJob`` 契约自验（未终态带产物、succeeded 无产物等在这里被拦，
          契约不过 ⇒ 抛 ``ValidationError``：这是调用方的编程错误，loud 比静默安全，
          与「读侧坏行点名跳过」刻意不对称）；
        - **两道并发防线**：① ``expected_state`` 与库内实况先对一次（对不上就是过期快照，
          带原因直接拒，绝不拿它去喂迁移判定）；② ``UPDATE ... WHERE job_id=? AND
          state=?`` 的状态谓词兜住真竞态（第一道在事务里通过、提交前被别人抢跑时，
          ``rowcount=0`` ⇒ ``moved=False`` 带原因，既不静默覆盖、也不抛异常带走整轮）。
        """
        identifier = self._require_identifier(job_id, "job_id")
        if not isinstance(target, CreationJobState):
            raise JobStoreError(f"目标状态必须是契约枚举，收到 {target!r}")
        if expected_state is not None and not isinstance(expected_state, CreationJobState):
            raise JobStoreError(f"expected_state 必须是契约枚举，收到 {expected_state!r}")
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM {JOB_TABLE} WHERE job_id = ?",
                (identifier,),
            ).fetchone()
            if row is None:
                return AdvanceOutcome(moved=False, job_id=identifier, reason="库里没有这条任务")
            current = self._row_to_job(row)
            if current is None:
                return AdvanceOutcome(moved=False, job_id=identifier, reason="库行不合契约：坏行")
            # 顺序是判据，不是风格：先问「你看到的还是现在这个吗」，再问「这一步能不能走」。
            # 反过来（先迁移判定）会让过期快照在**大多数**情形下被迁移表挡成
            # 「非法迁移」——看着像守住了，其实并发守卫从没单独跑过（本席的注毒③第一版
            # 就是这样假绿的：它打死的是状态机，不是守卫）。
            if expected_state is not None and expected_state is not current.state:
                return AdvanceOutcome(
                    moved=False,
                    job_id=identifier,
                    state=current.state,
                    reason=(
                        f"并发抢先：库里已是 {current.state.value}，"
                        f"调用方看到的 {expected_state.value} 已过期，本次不覆盖"
                    ),
                )
            if not can_transition(current.state, target):
                return AdvanceOutcome(
                    moved=False,
                    job_id=identifier,
                    state=current.state,
                    reason=f"非法迁移 {current.state.value}→{target.value}（状态机无此出边）",
                )
            guard = current.state if expected_state is None else expected_state
            operation = provider_operation or current.provider_operation
            if operation is not None:
                self._require_identifier(operation, "provider_operation")
            updated = CreationJob(
                job_id=current.job_id,
                state=target,
                updated_at=self._now(),
                idempotency_key=current.idempotency_key,
                # 未终态不得携带产物：这条由契约在同一处执法，本件不复制判据。
                assets=assets,
                usage=usage or current.usage,
                error_code=_error_code_of(error_code),
                provider_operation=operation,
                cancel_requested=current.cancel_requested,
                cancel_requested_at=current.cancel_requested_at,
            )
            cursor = connection.execute(
                f"""
                UPDATE {JOB_TABLE}
                   SET state = ?, updated_at = ?, provider_operation = ?,
                       error_code = ?, assets_json = ?, usage_json = ?
                 WHERE job_id = ? AND state = ?
                """,
                (
                    updated.state.value,
                    _format_utc(updated.updated_at),
                    updated.provider_operation,
                    updated.error_code,
                    _assets_json(updated.assets),
                    _usage_json(updated.usage),
                    identifier,
                    guard.value,
                ),
            )
            if cursor.rowcount <= 0:
                return AdvanceOutcome(
                    moved=False,
                    job_id=identifier,
                    state=current.state,
                    reason=f"并发抢先：state 已不是 {guard.value}，本次不覆盖",
                )
        return AdvanceOutcome(moved=True, job_id=identifier, state=updated.state)

    def mark_cancel_requested(self, job_id: str) -> bool:
        """打取消**标记**，绝不改 ``state``（``CANCEL_REQUESTED_IS_NOT_A_STATE``）。

        已终态也允许补标记：取消在途不假成功，但也不把已完成的真产物抹掉——
        「曾请求取消」是事实，不是状态。
        """
        identifier = self._require_identifier(job_id, "job_id")
        moment = _format_utc(self._now())
        with self._connection() as connection:
            cursor = connection.execute(
                f"UPDATE {JOB_TABLE}"
                " SET cancel_requested = 1, cancel_requested_at = ?"
                " WHERE job_id = ? AND cancel_requested = 0",
                (moment, identifier),
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------------ 读回

    def get(self, job_id: str) -> CreationJob | None:
        """按 id 读回契约 DTO；坏行点名后返回 None（不硬凑一条假任务给下游）。"""
        record = self.get_record(job_id)
        return None if record is None else record.job

    def get_record(self, job_id: str) -> StoredJob | None:
        """按 id 读回**完整在册形态**（含通道）：按 id 回读一个任务归哪条腿办，
        靠的就是这一口——契约 DTO 里没有这个事实，硬塞就是改协议。"""
        identifier = str(job_id or "").strip()
        if not identifier:
            return None
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM {JOB_TABLE} WHERE job_id = ?",
                (identifier,),
            ).fetchone()
        return None if row is None else self._row_to_record(row)

    def find_by_idempotency_key(self, key: str | None) -> CreationJob | None:
        """「这条请求是不是已经有过一条任务」——重发判定的唯一问口。"""
        text = str(key or "").strip()
        if not text or not is_legal_job_identifier(text):
            return None
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM {JOB_TABLE} WHERE idempotency_key = ?",
                (text,),
            ).fetchone()
        if row is None:
            return None
        record = self._row_to_record(row)
        return None if record is None else record.job

    def list_non_terminal(
        self, *, channel: str | None = None, limit: int = 50
    ) -> list[CreationJob]:
        """对账扫描：只捞**非终态**（名单取契约 ``NON_TERMINAL_JOB_STATES``，不另列一份）。

        坏行逐条点名跳过、**不带走整轮**——这条口径是紧急域那枚 Critical 的直接教训：
        兜底 except 把「一行有问题」放大成「本轮什么都不做」＝静默漏投。
        """
        return [record.job for record in self.records_non_terminal(channel=channel, limit=limit)]

    def records_non_terminal(
        self, *, channel: str | None = None, limit: int = 50
    ) -> list[StoredJob]:
        """同 :meth:`list_non_terminal`，但带回通道（对账要知道去问哪个 provider）。"""
        return self._query(
            where="state IN (" + _quoted(state.value for state in NON_TERMINAL_JOB_STATES) + ")",
            channel=channel,
            limit=limit,
        )

    def list_terminal(self, *, channel: str | None = None, limit: int = 50) -> list[CreationJob]:
        """终态读回（审计/回显面），同样逐行点名跳过坏行。"""
        return [record.job for record in self.records_terminal(channel=channel, limit=limit)]

    def records_terminal(
        self, *, channel: str | None = None, limit: int = 50
    ) -> list[StoredJob]:
        """同 :meth:`list_terminal`，带回通道事实。"""
        return self._query(
            where="state IN (" + _quoted(state.value for state in TERMINAL_JOB_STATES) + ")",
            channel=channel,
            limit=limit,
        )

    def _query(self, *, where: str, channel: str | None, limit: int) -> list[StoredJob]:
        cap = int(limit)
        if cap <= 0:
            # 与 emergency 同口径：非正 limit 绝不悄悄变成全表扫描。
            return []
        clause = where
        params: list[Any] = []
        if channel is not None:
            if channel not in _CHANNEL_VALUES:
                raise JobStoreError(
                    f"未知 creation 通道 {channel!r}（在册：{list(_CHANNEL_VALUES)}）"
                )
            clause += " AND channel = ?"
            params.append(channel)
        params.append(min(cap, MAX_LIST_LIMIT))
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM {JOB_TABLE}"
                f" WHERE {clause} ORDER BY updated_at DESC, rowid DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        records: list[StoredJob] = []
        for row in rows:
            record = self._row_to_record(row)
            if record is not None:
                records.append(record)
        return records

    # ------------------------------------------------------------------ 卫生

    def prune(self, *, keep_days: int = DEFAULT_KEEP_DAYS, now: datetime | None = None) -> int:
        """删除保留期外的**已终态**任务，返回删除行数。

        两类行结构性不裁，且都是判据而非偏好：
        - 非终态＝在途（裁掉就是「任务消失了，谁也说不清它到底成没成」）；
        - ``unknown``＝「不重发」的身份凭据，裁掉等于把一条可能已经花钱的任务放回可重发池
          （扩展 §1 L56：多图按实结算）。
        """
        current = _require_aware_utc("prune now", now or self._now())
        cutoff = _format_utc(current - timedelta(days=max(1, int(keep_days))))
        kept = _quoted(state.value for state in NON_TERMINAL_JOB_STATES)
        kept += ", " + _quoted([CreationJobState.UNKNOWN.value])
        with self._connection() as connection:
            cursor = connection.execute(
                f"DELETE FROM {JOB_TABLE} WHERE state NOT IN ({kept}) AND updated_at < ?",
                (cutoff,),
            )
        return cursor.rowcount

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _require_identifier(value: object, name: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise JobStoreError(f"任务标识 {name} 不得为空")
        if len(text) > _IDENTIFIER_MAX_CHARS:
            raise JobStoreError(f"任务标识 {name} 超长（>{_IDENTIFIER_MAX_CHARS}）")
        if not is_legal_job_identifier(text):
            raise JobStoreError(
                f"任务标识 {name}={text!r} 含非法段字符"
                "（段规则唯一家 dedupe._SEGMENT_RE；`:` 是段分隔符，不得作字面量入库）"
            )
        return text

    def _row_to_job(self, row: Any) -> CreationJob | None:
        record = self._row_to_record(row)
        return None if record is None else record.job

    def _row_to_record(self, row: Any) -> StoredJob | None:
        """行 → 在册形态：**过契约自验**，不合格即坏行（判据不在此复制一份）。

        整段都在 try 里，连「行读不出键」也算坏行——本函数绝不让一行脏数据把
        调用方的整轮对账带走。
        """
        raw_id: object = "?"
        try:
            values = _row_mapping(row)
            raw_id = values.get("job_id")
            job = CreationJob(
                job_id=str(raw_id or ""),
                state=CreationJobState(str(values.get("state") or "")),
                updated_at=_parse_utc(values.get("updated_at")),
                idempotency_key=_none_if_blank(values.get("idempotency_key")),
                assets=tuple(AssetRef(**item) for item in _json_list(values.get("assets_json"))),
                usage=tuple(UsageLine(**item) for item in _json_list(values.get("usage_json"))),
                error_code=_error_code_of(values.get("error_code")),
                provider_operation=_none_if_blank(values.get("provider_operation")),
                cancel_requested=bool(values.get("cancel_requested")),
                cancel_requested_at=_optional_utc(values.get("cancel_requested_at")),
            )
            channel = str(values.get("channel") or "")
            if channel not in _CHANNEL_VALUES:
                raise ValueError(f"通道 {channel!r} 不在册")
            created_at = _parse_utc(values.get("created_at"))
        except Exception as exc:  # noqa: BLE001 - 坏行点名，绝不带走整轮（原因进观测环，不外抛）
            self._note_skip(raw_id, f"{type(exc).__name__}")
            return None
        if not is_legal_job_identifier(job.job_id):
            # 契约不查段字符集（那是键规范的家），本件补这一道；点名后跳过。
            self._note_skip(job.job_id, "illegal_segment")
            return None
        key = job.idempotency_key
        if key is not None and not _DIGEST_RE.fullmatch(key):
            self._note_skip(job.job_id, "illegal_idempotency_shape")
            return None
        return StoredJob(
            job=job,
            channel=channel,
            workspace_id=str(values.get("workspace_id") or ""),
            created_at=created_at,
        )


def _json_list(raw: object) -> list[Any]:
    """落库的 JSON 数组列；不是数组就是坏行（抛错交上层点名，不静默当空表）。"""
    parsed = json.loads(str(raw if raw is not None else "[]") or "[]")
    if not isinstance(parsed, list):
        raise TypeError("资产/用量列不是 JSON 数组")
    return parsed


def _assets_json(assets: Iterable[AssetRef]) -> str:
    return json.dumps([asset.model_dump(mode="json") for asset in assets])


def _usage_json(usage: Iterable[UsageLine]) -> str:
    return json.dumps([line.model_dump(mode="json") for line in usage])


def _row_pair(row: Any) -> tuple[Any, Any]:
    """``SELECT a, COUNT(*)`` 这类匿名行：按位置取前两列。"""
    if isinstance(row, (str, bytes, bytearray)):
        raise TypeError("计数行不是序列")
    if isinstance(row, Sequence):
        return (row[0], row[1])
    keys = getattr(row, "keys", None)
    if callable(keys):
        names = list(keys())
        return (row[names[0]], row[names[1]])
    raise TypeError("计数行形态不认识")


__all__ = [
    "CHANNEL_CHECK_SQL",
    "DEFAULT_KEEP_DAYS",
    "JOB_TABLE",
    "MAX_LIST_LIMIT",
    "STATE_CHECK_SQL",
    "AdvanceOutcome",
    "CreationJobStore",
    "JobStoreError",
    "RegisterOutcome",
    "StoredJob",
    "build_job_store_schema",
    "is_legal_job_identifier",
    "job_store_schema_sql",
]
