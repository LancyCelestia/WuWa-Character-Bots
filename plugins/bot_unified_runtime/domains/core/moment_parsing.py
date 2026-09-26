r"""ISO-8601 **时刻**字面量解析中央件（全仓唯一权威，S232 落地 2026-09-25）。

## 为什么存在（病根，现算不抄）

出站闸的 TTL 腿（`enabled_until`，S231 落码）需要把一枚 ISO-8601 字面量解析成
aware UTC 时刻。闸侧那条 G5 单一事实源锁（`tests/test_outbound_gate.py`
`test_gate_reuses_quiet_hours_single_source`）当场把它判红——
`assert "fromisoformat" not in source, "不得自造时间解析"`。

**这条锁本身没错，错在它没有给一个可去的家**：开工时全仓**不存在**任何「解析 ISO
时刻」的中央件。尺身份＝`(datetime|datetime\.datetime)\.fromisoformat` 于 `plugins/` 下
的 `*.py`（不含本件）。⚠ **计数一律不在此手写**（AGENTS 规则 10：这类数随代码漂移，
手写过的每一版都在几天内过期）——现算清单与可复跑命令住
`.superpowers/sdd/2026-09-24-central-dispatch/SEAT-S232.md` §3（S232 续跑席 2026-09-24T18:39Z
的读数当量级参考：数十处、数十个文件，其中一小半各自手写同一枚兼容动作
`value.replace("Z", "+00:00")`，写法还不完全一样——有的先 `.strip()`、有的不判
`ValueError`、有的折成 `None`）。

⇒ 「禁自造」缺的不是纪律，是**一件可以走的东西**。本件补上那个家。

## 判据口径（钉死，逐条有锁，见 `tests/test_moment_parsing_central.py`）

1. **输入面**：`datetime` 对象（缺 tzinfo ⇒ 按 UTC 补）∪ 字符串字面量。其余类型
   一律先 `str()` 再解析，解析不出即抛（`123` / `True` / `[]` 都不是时刻）。
2. **`Z` / `z` 后缀**＝ UTC。本件自己做 `+00:00` 归一，**不依赖** Python 版本，
   也不赌标准库的大小写：本机 3.12.10 **实测**（S232 续跑席 2026-09-24T18:38Z 复跑一致）
   `fromisoformat("2026-09-25T03:00:00Z")` 成、`("...03:00:00z")` **当场 ValueError**，
   而 3.10 连大写 `Z` 都不认 ⇒ 归一必须在本件一处做完（存量那些手写
   `.replace("Z", "+00:00")` 的点位绕的正是版本差，却没一处管大小写；清单见 §3）。
   归一**排在第二遍**：先让标准库原样解，解不动且串尾是 `Z`/`z` 才折
   ——顺序反了会把「偏移与 `Z` 双写」（`…+00:00Z`）这种冲突形态洗成合法值；
   该形态本件**当场抛**（口径见 `_parse_literal`）。
3. **带偏移量**（`+08:00` / `-05:30`）⇒ 折算成 UTC，返回值的 `tzinfo` **恒为**
   `timezone.utc`（不保留原偏移：偏移是输入形态，不是结果形态）。
4. **裸时刻**（无 `Z` 无偏移，如 `2026-09-25T03:00:00`）⇒ **按 UTC 解释**。
   ⚠ 这是**有意选定**的口径，不是没考虑：
   - 它与本件要服务的第一位消费方（出站闸 `_utc()`：naive 即 `replace(tzinfo=utc)`）
     **逐字节同形** ⇒ 立真身这件事本身不改变任何现网读数；
   - 反过来按「机器本地时区」解释才是危险的：本仓 cron/安静时间已经吃过时区口径
     偏移的亏（台账 #6），拿 `astimezone()` 猜本地钟会让同一份 `.env` 在两台机器上
     解出不同到期时刻；
   - 结论：裸时刻是「调用方没写时区」，本件**不猜**，统一按 UTC 落，并在需要严格
     口径的调用方那里由**调用方自己**拒收（见第 6 条）。
5. **仅日期**（`2026-09-25`）⇒ 当日 `00:00:00Z`（`fromisoformat` 的自然结果，
   与第 4 条同口径）。`date` 对象（非 `datetime`）⇒ **抛**：给它配上「零点」这个
   一天中没有的信息属于本件编造，宁可响亮。
   ⚠ **仅日期再挂 `Z`（`2026-09-25Z`）⇒ 当日 `00:00:00Z`，不抛**。本条是 S232 续跑席
   （2026-09-24T18:38Z 实测）**推翻上一版文档**得来的：上一版写「抛（实测两遍都解不动）」，
   实机 3.12.10 上标准库第一遍就解得动（3.11+ 的 `fromisoformat` 吃这形）⇒ 本件走的是
   「第一遍即成功」的路径，根本不进 `Z` 归一支。行为与本条前半（裸日期按零点）同口径、
   且幂等，故**留行为、改文档、补锁**：见
   `tests/test_moment_parsing_central.py::test_date_only_with_zulu_is_midnight_utc`。
   留这一手而非再造第三种拒绝，是因为「配置面写了个能被标准库读懂的 ISO 值却被本件拒」
   会让本件比它要替代的散落实现更难预测——而那散落实现正是本件要收的账。
6. **空值 / 不可解析 ⇒ 抛 `MomentParseError`**（可辨识，且继承 `ValueError`）。
   这是本件的**核心教义**：「没配」与「配错了」必须是两个能被区分的事实。
   若本件对垃圾值静默返回 `None`，消费方就会把「写错的 TTL」当成「没写 TTL」，
   一枚本该到期的临时开关会**永久有效**——出站闸 `effective_gate_enabled` 的
   `TTL_STATE_INVALID`（fail-closed，宁关不猜）正是靠这个异常才成立。
   「缺省即无值」这个判断**属于调用方**（闸自己先查空串），不属于解析器。
7. **幂等**：`parse_moment(parse_moment(x).isoformat()) == parse_moment(x)`。
8. **不做**的事：epoch 数字换算、英文日期（`Wed Oct 10 …`）、中文「年月日」、
   相对时长（`30m`/`2h`）。那些是**别的语义**，各自的处置见下节。

## 与既有邻居的分工（避免被当第二真身，也避免有人拿本件去顶它们）

| 邻居 | 位置 | 语义 | 与本件关系 |
|---|---|---|---|
| `_optional_datetime` | `domains/core/contracts/media.py:211` | **宽松强制**：接受 datetime/epoch/英文日期/中文年月日，解不出**返回 None**，naive 按北京时间 | 契约层的字段强制口，「解不出＝该字段为空」是它的正确语义 ⇒ **不得**改用本件（改了会把可选字段变成抛异常） |
| `_require_aware_utc` | `core/decision/outbound_contracts.py:246`、`creation/_common/contracts.py:56`、`ops/monitor/event_store.py:141` | **校验**已解析的 `datetime` 是否 aware UTC | 校验≠解析：它收 `datetime` 不碰字符串 ⇒ 与本件互补，不冲突 |
| `_utc_now` | 全仓十余处（`queue.py:100`、`worker.py:66`、…；计数以 §3 复跑为准） | **读钟**（now） | 读现在是另一件事，本件只解析字面量 |
| `_format_moment` | `transport/sender/outbound_gate.py:320` | 时刻 → 展示字符串 | 序列化不在本件射程（本波不做，见 §3） |
| `date.fromisoformat` | 十余处（`finance/data/stock_data.py:630` 等；计数以 §3 复跑为准） | **日期**字面量 | 不同的类型，**不迁**（拿时刻解析器解日期会造出假时刻） |

## 迁移纪律（本件立起来之后）

- 本波**只接触站闸一处**。其余存量直调点属他波面/大 sweep，本席一律不动，
  逐条清单与建议登记在 `.superpowers/sdd/2026-09-24-central-dispatch/SEAT-S232.md` §3。
- 判定某处该不该迁，只问一句：**它需要「解不出就响亮」吗？** 需要 ⇒ 迁；
  它今天是「解不出就当没有」的宽松强制 ⇒ **不要**迁（那是 `_optional_datetime`
  一族，语义与本件相反）。

全件零 I/O、零网络、零 config 依赖、无第三方库：纯函数，可被任意域离线复用。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Final

__all__ = [
    "MOMENT_FIELD_DEFAULT",
    "ZULU_SUFFIXES",
    "MomentParseError",
    "parse_moment",
]

#: 报错文案里缺省的字段名（调用方一律传自己那枚键名，便于归因）。
MOMENT_FIELD_DEFAULT: Final[str] = "时刻字面量"

#: 代表 UTC 的单字母后缀（大小写两式都要认——`Z`/`z` 在真实配置与日志里都出现过）。
#: ⚠ 实测（本机 3.12.10，2026-09-24T17:55:59Z）：`fromisoformat` **只认大写 `Z`**，
#: 小写 `z` 当场 ValueError ⇒ 大小写两式都必须由本件自己归一，不能指望标准库。
ZULU_SUFFIXES: Final[tuple[str, ...]] = ("Z", "z")

#: 串尾的显式偏移量形态（`+08:00` / `-0530` 一类），用于识别「偏移与 Z 双写」。
_OFFSET_TAIL_RE: Final[re.Pattern[str]] = re.compile(r"[+-]\d{2}:?\d{2}$")

#: 报错文案里原文的最大回显长度（防止一枚超长垃圾值把日志行撑爆）。
#: ⚠ 光剪自己那半句不够：标准库的 `ValueError` 文案会把**整串** offending 值再抄一遍
#: （`Invalid isoformat string: '<原值>'`），故 cause 也必须剪（本席自写用例抓到）。
_MAX_ECHO_CHARS: Final[int] = 64
_MAX_CAUSE_CHARS: Final[int] = 80


class MomentParseError(ValueError):
    """ISO-8601 时刻字面量**不成立**（缺失 / 空 / 读不懂 / 类型不对）。

    继承 `ValueError` 是刻意的：既有消费方的兜底面写的是
    `except (TypeError, ValueError)`（出站闸 `effective_gate_enabled` 即其一），
    本件必须能被它原样接住，而不是逼每个调用方新学一个异常类。
    同时它是**可辨识**的——`type(exc) is MomentParseError` 让需要分面的调用方
    能把「配错了」与「别的 ValueError」分开记账。
    """


def _clip(text: str, limit: int) -> str:
    """超长文本折成短引用（只用于报错文案）。"""
    if len(text) <= limit:
        return repr(text)
    return f"{text[:limit]!r}…(共{len(text)}字)"


def _echo(value: object) -> str:
    """把 offending 值折成安全的短引用（只用于报错文案，不进审计正文）。"""
    text = str(value).strip()
    if not text:
        return "''"
    return _clip(text, _MAX_ECHO_CHARS)


def _to_utc(value: datetime) -> datetime:
    """任何 `datetime` → aware UTC（naive ⇒ **按 UTC 补**，见模块 docstring 第 4 条）。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _strip_zulu(text: str) -> str:
    """`Z`/`z` 后缀 → 显式 `+00:00`（一处做完，替代全仓 12 处手写兼容）。

    只在「标准库第一遍解不动」时才走这条路（见 `_parse_literal`）：3.11+ 原生就认
    大写 `Z`，先让原生解，归一路径专门兜住**实测**两类失败——小写 `z` 与 3.10 系
    旧口径。顺序反了会把「偏移 + Z 双写」这种冲突形态洗成合法值。
    """
    if text.endswith(ZULU_SUFFIXES):
        return text[:-1] + "+00:00"
    return text


def _parse_literal(text: str, field: str) -> datetime:
    """字面量 → `datetime`（本件的两遍口径；不负责补 tzinfo）。

    第一遍原样交给标准库；只有它报 `ValueError` 且串尾是 `Z`/`z` 时才试归一。
    「尾部已是显式偏移、又跟一枚 `Z`」（`…+00:00Z`）＝两种 UTC 写法同时出现，
    **当场抛**，不洗成合法——本件对配置面的立场是「形态冲突就响亮」，
    静默择一正是那 12 处手写 `.replace("Z", "+00:00")` 各自会走上的分歧点。
    """
    try:
        return datetime.fromisoformat(text)
    except ValueError as first_error:
        if not text.endswith(ZULU_SUFFIXES):
            raise
        body = text[:-1]
        if _OFFSET_TAIL_RE.search(body):
            raise MomentParseError(
                f"{field}：偏移量与 `Z` 双写（{_echo(text)}）——"
                "两种 UTC 写法同时出现，形态冲突不猜"
            ) from first_error
        return datetime.fromisoformat(_strip_zulu(text))


def parse_moment(value: object, *, field: str = MOMENT_FIELD_DEFAULT) -> datetime:
    """把一枚 ISO-8601 时刻字面量解析成 **aware UTC** `datetime`。

    语义见模块 docstring；一句话版：认 `Z` 与 `z` 两式与 `±hh:mm` 偏移，
    裸时刻按 UTC 解释，结果 `tzinfo` 恒为 `timezone.utc`；
    **空值 / 垃圾值 / `date` 对象 / 偏移与 Z 双写一律抛 `MomentParseError`，
    绝不返回 `None`**——「没有这个值」这个判断属于调用方，不属于解析器。
    """
    if isinstance(value, datetime):
        return _to_utc(value)
    # `date`（非 datetime）没有"一天中的哪一刻"，替它编一个零点属于造事实。
    if isinstance(value, date):
        raise MomentParseError(
            f"{field}：收到日期而非时刻（{_echo(value)}）——"
            "本件不把日期补成某个时刻，请由调用方显式给出时间部分"
        )
    if value is None:
        raise MomentParseError(
            f"{field}：缺失（None）——需要 ISO-8601 时刻字面量；"
            "「没配」请由调用方自己判，不要交给解析器折成空"
        )
    text = str(value).strip()
    if not text:
        raise MomentParseError(
            f"{field}：空字面量——需要 ISO-8601 时刻；同上，「没配」不由本件折叠"
        )
    try:
        parsed = _parse_literal(text, field)
    except MomentParseError:
        raise  # 已在里面点过名，不再套一层
    except ValueError as exc:  # 标准库的拒绝统一换成本件的可辨识异常
        raise MomentParseError(
            f"{field}：无法解析为 ISO-8601 时刻（{_echo(text)}）："
            f"{_clip(str(exc), _MAX_CAUSE_CHARS)}"
        ) from exc
    return _to_utc(parsed)
