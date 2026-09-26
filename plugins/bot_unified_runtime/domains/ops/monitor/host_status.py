"""宿主机读数的**呈现形态适配器**（需求 5；2026-09-26 起不再是取数真身）。

真身在哪
--------

取数只有一个地方：``plugins/bot_unified_runtime/domains/ops/host_metrics.py``
（在册指标 ``METRIC_SPECS``、采集器、psutil/注册表/标准库兜底、逐项状态）。
本文件只做三件**不读机器**的事：

1. 把真身的逐项读数按**旧三分组**（硬件 / 占用 / 系统与运行时）摊成呈现形状，
   并把「未探测 / 采集失败」的项**整行摘掉**（旧契约：缺数=缺行，宁可少一行，
   也不给人一排假占位）——真身自己那套「写未探测」的口径仍然完整保留，
   新消费方要用它就直连真身。
2. 带标签的 **TTL 缓存**（下面那条长注释解释它为什么必须存在）。
3. 文本版 / 拉平版两个便捷出口。

收敛前这里是第二真身：自己扫注册表、自己 ``psutil`` 采样、自己 ``disk_usage``，
与 ``host_metrics`` 各读一遍机器。现在本文件体内**没有任何** ``platform.`` /
``psutil.`` / ``winreg.`` / ``shutil.disk_usage`` 直调，这一条由
``tests/test_host_metrics_single_source.py`` 的 AST 门执法（注毒必红）。
「这台机器有没有 psutil」也归真身回答（``host_metrics.psutil_available()``）——
本文件只问、不读，否则取数口又裂成两处。

旧契约逐条保留（锁在 ``tests/test_host_status.py``）：

- **读数现取不缓存**只适用于一眼就走的命令面；聊天分区每条消息一份快照，
  缓存换来的代价用**取样时刻标签**抵账（分区里明写「取样 HH:MM」，模型读到的
  是有保质期的事实，不是装作现取的旧数）。
- **拿不到就缺行**，不写「未知」占位、更不折算。
- **``psutil`` 缺席时整面降级**成交回空组（真身自己有标准库兜底腿，但这条
  旧契约说的是「旧呈现面不硬凑半份数据」，两件事不冲突，见 ``collect_host_snapshot``）。
- **版本读数只有一个来源**：本文件的版本腿只调
  ``error_report._version_pairs``，不自己拼版本号。⚠ 它传的 getter 是
  ``_dist_version``、真身传的是 ``_default_config_getter``，两者对
  ``BOT_PROTOCOL_CLIENT_DIR`` 的处理不同（详见 S-T-HOST-2 报告）；这一处**今天
  未统一**，因为改它要同批改 ``tests/test_host_status.py`` 那条 getter 断言，
  不在本次收敛的可写面内。
"""

from __future__ import annotations

import threading
import time as _time
from typing import Any

from plugins.bot_unified_runtime.domains.ops import host_metrics as _metrics

# 版本号那份事实源在册：诊断卡的 _version_pairs 已经把 nonebot/适配器/插件/
# 协议端/Python/OS/git 构建一次性收齐，这里只调它，不重抄第二套取版本的路。
_VERSION_SOURCE = "domains/ops/monitor/error_report.py::_version_pairs"

# 分组名与顺序的唯一声明处（插入序即出卡序）；空快照与 collect 都从这里派生，
# 不在了第二处抄「硬件/占用/系统与运行时」三个字面量。
HOST_GROUP_NAMES: tuple[str, ...] = ("硬件", "占用", "系统与运行时")

# 真身分组 → 旧呈现分组的映射表。版本组**不在此表**：旧「系统与运行时」那一栏
# 走 `_runtime_versions()` 的原样透传（它比真身那张投影表覆盖的行更宽——多出适配器
# 全景等中央行，走这张表会少行=呈现面退化）。
_LEGACY_GROUP_BY_METRIC_GROUP: dict[str, str] = {
    _metrics.GROUP_HARDWARE: "硬件",
    _metrics.GROUP_USAGE: "占用",
}

# 少数几项在旧卡上的归属与真身分组不同，按指标 id 点名改回旧位置，
# 免得「磁盘」整栏搬家（磁盘属「此刻用量」不属「配置」，是旧卡上读了几天的位置）。
_LEGACY_GROUP_OVERRIDES: dict[str, str] = {"disk": "占用"}

# ---------------------------------------------------------------------------
# 复读行的规范身份表（2026-09-26 需求 5 收口；判据=**身份**，绝不是值相等）
# ---------------------------------------------------------------------------
# 真身 ``host_metrics._VERSION_LABEL_TO_ID`` 是「哪个指标 id 的值**就是**中央版本
# 采集口的哪一行」的唯一声明处——``_collect_from_version_source`` 正是按它取值，
# 所以这张表本身就是「同一事实」的规范身份，无需在本文件另立第二份账（另立＝
# 改一处漂一处）。凡落在这张表里的指标，它在旧卡上出现的第二遍，就是中央口那一行
# 的第二遍；而旧「系统与运行时」一栏由 ``_runtime_versions()`` 把中央口的行**原样
# 全量**透传，两遍同时在场即「同一事实两处出现，迟早漂成两个值」。
#
# 今天真正会撞上这张表的只有一枚：``process_uptime``。其余各枚都住在版本组，
# 上面那张分组映射表本来就不收它们（``legacy_group is None`` 即 continue）。
# ``process_uptime`` 是 2026-09-26 按用户点名清单（「本 bot 运行时长」）补进来的，
# 为了让它在**新**能力卡上排在「占用」栏里可读，它被声明成 ``GROUP_USAGE``——
# 于是它绕过了分组过滤，却仍走中央口取值，旧卡面就此多出一次复读（红
# ``test_os_and_python_are_never_duplicated`` 的成因，逐字节实证见该席日志）。
#
# 为什么按 id 摘而不按值摘，以及为什么**不**加「中央行是否在场」这个条件，
# 两条都写在 ``collect_host_snapshot`` 的循环里，那里是判据真正生效的地方。
_CENTRAL_VERSION_PROJECTION_IDS: frozenset[str] = frozenset(
    _metrics._VERSION_LABEL_TO_ID.values()
)


def _empty_groups() -> dict[str, list[tuple[str, str]]]:
    return {group: [] for group in HOST_GROUP_NAMES}


def collect_host_snapshot() -> dict[str, list[tuple[str, str]]]:
    """分组成「硬件 / 占用 / 系统与运行时」三段读数；取不到的组留空。

    返回**有序** dict（插入序即渲染序），值全是 ``(中文标签, 中文值)`` 列表，
    呈现层直接按行出卡，属性名与属性值天然各自对齐（第 7 项的两栏要求）。
    """
    groups: dict[str, list[tuple[str, str]]] = _empty_groups()
    # 旧契约：psutil 不在就整面交回空组，不硬凑半份数据（真身的标准库兜底腿
    # 依然在，供直连真身的消费方用；这个问句本身也是真身答的，本文件不 import）。
    if not _metrics.psutil_available():
        return groups
    try:
        report = _metrics.collect_host_metrics_sync()
    except Exception:  # noqa: BLE001 - 真身整体炸了交回空组，由调用方出诚实文案
        return groups
    for item in report.items:
        if item.state != _metrics.STATE_OK:
            continue  # 缺数=缺行：未探测/采集失败都不上旧卡
        if item.metric_id in _CENTRAL_VERSION_PROJECTION_IDS:
            # 判据＝**规范身份**（真身声明的「本 id 的值就是中央口那一行」），不是值相等：
            # ①按值折叠会吃掉合法行——「已开机」与「本 bot 运行时长」在开机一分钟内
            #   同为「0 分钟」，「显卡」两行可能同名同值，两块盘可以一模一样，那都是
            #   **两条不同来源的事实恰好相等**，折叠＝卡上少一行真数（本波先例教训）。
            # ②按值折叠还会反过来漏掉真复读：上面那条规范件用例里中央行与映射腿刻意
            #   取了不同的值（"2 小时 3 分" vs 中央现算值），值不等而身份相同，
            #   只认值的写法当场哄不过那条锁。
            # 也刻意**不**加「中央那一行是否真在场」这个前置条件：本栏契约是「只准有
            # 中央采集口给的字，缺就缺行」（见下方 runtime_rows 注释），按身份无条件
            # 摘才有确定性；中央口若整段死掉，这条腿的值同源于它、必然落不到 OK，
            # 上面 ``state != STATE_OK`` 那一行已经把这种情形挡掉了。
            continue
        legacy_group = _LEGACY_GROUP_BY_METRIC_GROUP.get(item.group)
        if legacy_group is None:
            continue  # 版本组由 _runtime_versions() 负责（见上面的映射表注释）
        legacy_group = _LEGACY_GROUP_OVERRIDES.get(item.metric_id, legacy_group)
        groups[legacy_group].append((item.label, item.value))

    runtime_rows = _runtime_versions()
    # 中央版本采集口本就给「系统」和「Python」两行——再各写一行就是复读
    # （同一事实两处出现，迟早漂成两个值）。旧件在中央口没给那两行时会用
    # ``platform.system()/python_version()`` 兜底补上，收敛时**整条兜底腿删掉**：
    # 这一栏只准有中央采集口给的字，缺就缺行，本文件不再自己读机器。
    groups["系统与运行时"].extend(runtime_rows)
    return groups


def _runtime_versions() -> list[tuple[str, str]]:
    """调用诊断卡那份唯一版本采集口；它没给或炸了就整段缺席（不自己拼版本号）。

    真身契约是 ``_version_pairs(getter) -> list[{"label","value"}]``——那个
    ``getter`` 是必填形参（``error_report.py:1167``）。首版按「无参、返回二元组
    列表」写，结果每次 ``TypeError`` 被这里的 except 咽掉，整段版本读数**静默为
    空**——形态像降级、实为死读点，故锁在 ``tests/test_host_status.py``。

    ⚠ ``_dist_version`` 这个 getter 是那条锁钉住的历史形态（它按 str 调用会退回
    ``unknown``，于是 ``BOT_PROTOCOL_CLIENT_DIR`` 在版本腿里读不到）。真身用的是
    ``_default_config_getter``。两者并存属已知未收口项，理由见模块 docstring。
    """
    try:
        from plugins.bot_unified_runtime.domains.ops.monitor.error_report import (
            _dist_version,
            _version_pairs,
        )

        # error_report._version_pairs 的注解写 getter 收 `str`，而生产实传的
        # `_dist_version` 收候选名元组（error_report 自家调用也传元组）——
        # 按声明过 mypy 会把**真实契约**报成错，故此处 ignore 并留话：
        # 待 error_report 域把注解改对（tuple[str, ...]）后可删。
        rows = _version_pairs(_dist_version)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(rows, list):
        return []
    cleaned: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        value = str(row.get("value") or "").strip()
        if label and value:
            cleaned.append((label, value))
    return cleaned


def host_status_rows() -> list[tuple[str, str]]:
    """拉平成单列表（文本回执用；卡片走 ``collect_host_snapshot`` 的分组形态）。"""
    return [row for rows in collect_host_snapshot().values() for row in rows]


def host_status_text(*, empty_line: str = "") -> str:
    """人话纯文本版；一列都没有时交回调用方给的诚实文案，不自拼兜底话术。"""
    rows = host_status_rows()
    if not rows:
        return empty_line
    return "\n".join(f"{label}：{value}" for label, value in rows)


# ---------------------------------------------------------------------------
# 带标签的 TTL 缓存（供**每条消息都要用**的呈现路径：人格上下文的【宿主机状态】
# 分区、以及 /bot status 尚未通电线程池前的过渡消费）。
#
# 与本模块"读数一律现取"的口径不冲突：现取是给**看一眼就走**的命令面定的；
# 聊天路径每条消息注一份快照，200ms 采样 + 注册表扫描按消息数放大就是纯浪费。
# 缓存换来的代价用**取样时刻标签**抵账——分区里明写"取样 HH:MM"，模型读到
# 的是有保质期的事实而不是装作现取的旧数。
# ---------------------------------------------------------------------------

_SNAPSHOT_LOCK = threading.Lock()
_SNAPSHOT_CACHE: dict[str, Any] = {"groups": None, "wall_clock": 0.0, "taken_at": ""}


def cached_host_snapshot(
    *,
    allow_blocking: bool,
    ttl_seconds: float = 90.0,
) -> tuple[dict[str, list[tuple[str, str]]], str]:
    """TTL 缓存版快照。返回 ``(分组读数, 取样时刻 HH:MM)``；无数可给时读数全空。

    - ``allow_blocking=True``（线程池里）：缓存过期就现取一份并回填。
    - ``allow_blocking=False``（当前线程可能是事件循环）：**绝不计算**——
      只回缓存里最近一份（哪怕过期，取样时刻如实标注），从没有过就回空组。
      调用方据"空组"出诚实降级行。
    """
    with _SNAPSHOT_LOCK:
        cached_groups = _SNAPSHOT_CACHE["groups"]
        age = _time.monotonic() - float(_SNAPSHOT_CACHE["wall_clock"])
        if cached_groups is not None and (
            age <= max(0.0, float(ttl_seconds)) or not allow_blocking
        ):
            return dict(cached_groups), str(_SNAPSHOT_CACHE["taken_at"])
        if cached_groups is None and not allow_blocking:
            # 冷缓存 + 不许阻塞（当前线程可能是事件循环）⇒ 交回空组由调用方
            # 降级。首版漏了这条腿，200ms 采样照样在 loop 上跑了——形态像
            # 降级、实为没接线（烟测抓到，锁在 tests/test_host_status.py）。
            return _empty_groups(), ""
    groups = collect_host_snapshot()
    taken_at = _time.strftime("%H:%M")
    with _SNAPSHOT_LOCK:
        _SNAPSHOT_CACHE["groups"] = groups
        _SNAPSHOT_CACHE["wall_clock"] = _time.monotonic()
        _SNAPSHOT_CACHE["taken_at"] = taken_at
    return groups, taken_at


def invalidate_cached_snapshot_for_tests() -> None:
    """测试专用：清空 TTL 缓存（用例间互不串读数）。"""
    with _SNAPSHOT_LOCK:
        _SNAPSHOT_CACHE["groups"] = None
        _SNAPSHOT_CACHE["wall_clock"] = 0.0
        _SNAPSHOT_CACHE["taken_at"] = ""


# ---------------------------------------------------------------------------
# 兼容再导出：这两枚注册表原始读法今天仍被本文件的旧消费方点名
# （tests/test_host_status.py 直接调 `host_status._gpu_labels()`），
# 但**读法本体已迁入真身**——这里只是把名字端回来，本文件不再自己读注册表。
# 新代码请直接用 ``host_metrics._cpu_label`` / ``host_metrics._gpu_labels``。
# ---------------------------------------------------------------------------

_cpu_label = _metrics._cpu_label
_gpu_labels = _metrics._gpu_labels


__all__ = [
    "HOST_GROUP_NAMES",
    "_VERSION_SOURCE",
    "cached_host_snapshot",
    "collect_host_snapshot",
    "host_status_rows",
    "host_status_text",
    "invalidate_cached_snapshot_for_tests",
]
