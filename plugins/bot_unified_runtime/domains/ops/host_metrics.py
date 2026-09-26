"""宿主机读数**唯一取数真身**（需求 5 的数据腿：超管问「你机器现在什么样」要有真数可答）。

本模块**只取数、只组装卡片载荷**：不路由、不出图、不碰 echo/base_router/config
——装配由主代理统一做。

2026-09-26 S-T-HOST-2 收敛（本文件是需求 5 唯一的取数口）：
原先 ``domains/ops/monitor/host_status.py`` 与本文件**各自读一遍机器**（两份
winreg 注册表扫描、两份 psutil 采样、两份 disk_usage），是标准的双真身。收敛方向
按**覆盖面现算**判定，不留悬念：

- 注册表两枚原始读法（``_cpu_label`` / ``_gpu_labels``）**迁入本文件**——它们是
  取数，不是呈现；旧件反过来 import 本文件的读法才对（当时是反的：本文件
  import ``host_status._cpu_label``，等于真身依赖垫片，谁也删不掉谁）。
- psutil 独有的两项（页面文件、机器开机时长）补成在册项 ``swap`` /
  ``machine_uptime``，迁入即无一行读数因收敛而消失。
- ``host_status.py`` 降为**呈现形态适配器**（三分组 / 缺行语义 / TTL 缓存 / 文本版），
  其文件体内**不含任何** ``platform.`` / ``psutil.`` / ``winreg.`` /
  ``shutil.disk_usage`` 直调；这一条由
  ``tests/test_host_metrics_single_source.py`` 的 AST 门执法。
- 版本腿两文件都只调 ``error_report._version_pairs``（唯一版本采集口），
  本模块负责硬件/占用，旧件负责把中央版本行端上卡——同源，不是第二真身。
  ⚠ 两处传的 getter 不同（本文件 ``_default_config_getter``、旧件 ``_dist_version``），
  差异与影响见 S-T-HOST-2 报告，未在本次收敛内改（旧件那条锁在
  tests/test_host_status.py 的断言里）。

三条硬口径（每条都有 ``tests/test_host_metrics.py`` 的锁）：

- **取不到的项写「未探测」，单项采集抛异常只脏该项**（值写成
  ``采集失败：<异常类型>``），绝不编数、绝不带走整卡。
- **阻塞采集（psutil / subprocess / nvidia-smi）一律经 ``_to_thread`` 走工作
  线程**，不跑在事件循环线程上；逐项超时（缺省 5s）互不拖累。
- **psutil 缺席不装包**：标准库兜得住的（磁盘 ``shutil.disk_usage``、逻辑核数
  ``os.cpu_count``）兜上并在 source 里如实标来源；兜不住的（内存占用率、CPU
  占用率、进程 RSS/CPU 时间）诚实「未探测」，note 写明「本机未装 psutil」。

本机 GPU 显存这一项的实况：``nvidia-smi`` 会 ``Failed to initialize NVML``，
该腿按设计降级为「未探测」，note 保留失败原因供人查——这是第 1 条口径的
一次现场应用，不是缺陷。
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import string
import subprocess
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# 诚实占位的两个闭集词：值里出现它们就一定是这两种状态之一，绝不掺假数。
NOT_PROBED = "未探测"
_FAILED_PREFIX = "采集失败："

STATE_OK = "ok"
STATE_NOT_PROBED = "not_probed"
STATE_FAILED = "failed"

GROUP_VERSIONS = "系统与版本"
GROUP_HARDWARE = "硬件"
GROUP_USAGE = "占用"

# 单项采集的等待上限。nvidia-smi 自身另带更小的 subprocess 超时。
_DEFAULT_ITEM_TIMEOUT_SECONDS = 5.0
_NVIDIA_SMI_TIMEOUT_SECONDS = 3.0
# Windows 上瞬时采样常年读 0，200ms 窗是 host_status 实测过的下限口径。
_CPU_SAMPLE_INTERVAL_SECONDS = 0.2

_NVIDIA_SMI_ARGS = [
    "nvidia-smi",
    "--query-gpu=name,memory.used,memory.total,utilization.gpu",
    "--format=csv,noheader,nounits",
]

# 版本腿唯一来源常量：测试断言版本各项的 source 全等于它（不许另拼版本号）。
VERSION_PAIRS_SOURCE = "error_report._version_pairs（唯一版本采集口）"
_NVIDIA_SOURCE = "nvidia-smi --query-gpu（只读查询）"
_CUDA_SOURCE = "torch.cuda.mem_get_info（NVML 挂死时的 CUDA 第二腿，只读）"
_PLUGIN_DISTS_SOURCE = "importlib.metadata（nonebot-plugin* 发行版全景，进程级缓存）"
_CORE_DEPS_SOURCE = "importlib.metadata（固定核心依赖名单）"
_ENDPOINTS_SOURCE = "nonebot 运行期驱动（在线 bot + 监听/正向端点）"

# error_report._version_pairs 的行标签 → 本模块指标 id。"适配器 · onebot"
# 是 _adapter_dist_pairs 把发行名 "nonebot-adapter-onebot" 换前缀后的形态；
# "系统"/"操作系统" 两写法都收（中央件现给"系统"，兜底形态可能给后者）。
# 「运行时长」是 **bot 进程**的存活时长（与 machine_uptime=机器开机时长
# 是两件事，两行各自点名，缺一不可）；2026-09-26 三段前它不在映射里，
# 能力卡把它静默丢弃＝用户点名清单少一项。
_VERSION_LABEL_TO_ID: dict[str, str] = {
    "NoneBot": "nonebot_version",
    "适配器 · onebot": "adapter_onebot_version",
    "协议端": "protocol_client_version",
    "插件包": "plugin_version",
    "构建": "build_id",
    "Python": "python_version",
    "系统": "os_version",
    "操作系统": "os_version",
    "运行时长": "process_uptime",
}

# 适配器行在中央口的标签前缀（"适配器 · onebot" → 短名 "onebot"）。
_ADAPTER_LABEL_PREFIX = "适配器 · "

# 核心依赖固定名单：用户点名「pydantic/nonebot 依赖全家」。中央版本口没有
# 这一路（它只盘 nonebot 本体/适配器/插件包），故本文件另开一条**固定名单**
# 的发行版元数据缝——读的是装出来的事实，不手抄任何版本值；缺的包整段跳过，
# 一个都没有就「未探测」。名单本身按 pyproject 的直接依赖与 nonebot2 的
# 运行时依赖取主干，宁缺毋滥（长了卡读不动）。将来若中央口开出公共位，
# 这条缝应并回去（登记在 S-T-HOST-2 三段日志 §5）。
_CORE_DEPENDENCY_DISTRIBUTIONS: tuple[str, ...] = (
    "pydantic",
    "pydantic-core",
    "anyio",
    "httpx",
    "yarl",
    "uvicorn",
    "fastapi",
    "jinja2",
)


@dataclass(frozen=True)
class MetricSpec:
    """一个必覆盖项的在册声明：id、卡上属性名、所属分组（顺序即出卡顺序）。"""

    metric_id: str
    label: str
    group: str


@dataclass(frozen=True)
class HostMetric:
    metric_id: str
    label: str
    group: str
    value: str
    state: str  # STATE_OK | STATE_NOT_PROBED | STATE_FAILED
    source: str = ""
    note: str = ""


@dataclass(frozen=True)
class HostMetricsReport:
    items: tuple[HostMetric, ...]
    taken_at: str

    def by_id(self) -> dict[str, list[HostMetric]]:
        out: dict[str, list[HostMetric]] = {}
        for item in self.items:
            out.setdefault(item.metric_id, []).append(item)
        return out

    def first(self, metric_id: str) -> HostMetric | None:
        for item in self.items:
            if item.metric_id == metric_id:
                return item
        return None


# 简报第 2 条的覆盖清单逐项在册（一条不落）；顺序即卡片行序。
# 2026-09-26 三段按用户点名清单补齐五枚：适配器全景 / 本 bot 运行时长 /
# 依赖插件全家 / 核心依赖全家 / 协议端在线与端口（缺一项=清单少一项）。
METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec("nonebot_version", "NoneBot2", GROUP_VERSIONS),
    MetricSpec("adapter_onebot_version", "OneBot 适配器", GROUP_VERSIONS),
    MetricSpec("adapter_versions", "适配器全家", GROUP_VERSIONS),
    MetricSpec("protocol_client_version", "协议端（SnowLuma）", GROUP_VERSIONS),
    MetricSpec("plugin_version", "插件包版本", GROUP_VERSIONS),
    MetricSpec("dependency_plugins", "NoneBot 插件全家", GROUP_VERSIONS),
    MetricSpec("dependency_versions", "核心依赖版本", GROUP_VERSIONS),
    MetricSpec("build_id", "构建标识", GROUP_VERSIONS),
    MetricSpec("python_version", "Python", GROUP_VERSIONS),
    MetricSpec("os_version", "操作系统", GROUP_VERSIONS),
    MetricSpec("cpu_model", "处理器", GROUP_HARDWARE),
    MetricSpec("cpu_cores", "CPU 核心", GROUP_HARDWARE),
    MetricSpec("memory", "内存", GROUP_HARDWARE),
    MetricSpec("swap", "页面文件", GROUP_HARDWARE),
    MetricSpec("gpu_model", "显卡", GROUP_HARDWARE),
    MetricSpec("gpu_memory", "显卡显存", GROUP_HARDWARE),
    MetricSpec("disk", "磁盘", GROUP_HARDWARE),
    MetricSpec("cpu_percent", "CPU 占用", GROUP_USAGE),
    MetricSpec("process_usage", "本 bot 进程占用", GROUP_USAGE),
    MetricSpec("machine_uptime", "已开机", GROUP_USAGE),
    MetricSpec("process_uptime", "本 bot 运行时长", GROUP_USAGE),
    MetricSpec("protocol_endpoints", "协议端点", GROUP_USAGE),
)
_SPEC_BY_ID: dict[str, MetricSpec] = {spec.metric_id: spec for spec in METRIC_SPECS}
METRIC_SPEC_IDS: tuple[str, ...] = tuple(spec.metric_id for spec in METRIC_SPECS)


def _ok(spec: MetricSpec, value: str, source: str, *, label: str = "") -> HostMetric:
    return HostMetric(
        metric_id=spec.metric_id,
        label=label or spec.label,
        group=spec.group,
        value=value,
        state=STATE_OK,
        source=source,
    )


def _not_probed(
    spec: MetricSpec, *, source: str = "", note: str = "", label: str = ""
) -> HostMetric:
    return HostMetric(
        metric_id=spec.metric_id,
        label=label or spec.label,
        group=spec.group,
        value=NOT_PROBED,
        state=STATE_NOT_PROBED,
        source=source,
        note=note,
    )


def _failed(spec: MetricSpec, exc: BaseException, *, source: str = "") -> HostMetric:
    # 只留异常类型，不留异常文本：文本里可能带盘符/路径，打码是中央件的事，
    # 但值轨里少一份原文就少一份外泄与刷屏面。
    return HostMetric(
        metric_id=spec.metric_id,
        label=spec.label,
        group=spec.group,
        value=f"{_FAILED_PREFIX}{type(exc).__name__}",
        state=STATE_FAILED,
        source=source,
    )


def _gib(value: Any) -> str:
    return f"{float(value) / 1024**3:.1f} GB"


def _duration_text(seconds: float) -> str:
    """秒 → 人话时长。**一小时以上**必须按 3600 拆，不是 360。

    收敛时给「已开机」这一项接上才暴露：原式 `divmod(rest, 360)` 把所有 ≥1 小时
    的时长都折成假的「27 小时 302 分」（分钟位竟能到 359），而旧有消费方
    「本 bot 进程累计 CPU」在本机实测常低于一小时、恰好走 `f"{minutes} 分"`
    那一支，所以从建件到实测没人撞见过——现有用例只断言值里含「常驻内存」，
    没有一条断过小时/分的算法。修在真身这一处，两枚指标同时受益。
    """
    total = max(0, int(seconds))
    days, rest = divmod(total, 86400)
    hours, remainder = divmod(rest, 3600)
    minutes = remainder // 60
    if days:
        return f"{days} 天 {hours} 小时"
    if hours:
        return f"{hours} 小时 {minutes} 分"
    return f"{minutes} 分"


# ---------------------------------------------------------------------------
# 取数缝（外部世界只从这几个函数进来；测试一律 monkeypatch 它们，
# 不 monkeypatch 采集器本体——采集器是「被检对象」，缝才是「环境」）
# ---------------------------------------------------------------------------


def _psutil_module() -> Any | None:
    """psutil 只准惰性拿（模块级 import 会让精简环境连降级文案都走不到）。"""
    try:
        import psutil

        return psutil
    except Exception:  # noqa: BLE001 - 没装就是没装，交回 None 走兜底腿
        return None


def _logical_core_count() -> int | None:
    try:
        return os.cpu_count()
    except Exception:  # noqa: BLE001
        return None


# 值轨词汇闭集三形态：真数 / 「未探测」/ 「采集失败：<类型>」。中央件给协议端
# 的诚实值「未取到」在接管处归一成「未探测」，卡上就不出现第四种占位词。
_VERSION_MISSING_VALUES = frozenset({"未取到", "unknown"})


def _version_rows_clean() -> dict[str, str]:
    """调唯一版本采集口，回「行标签 → 值」原样表；任何失败 = 空表（未探测腿）。

    映射层（:func:`_version_rows_map`）与全景腿（:func:`_adapter_version_rows`）
    都从这一份派生——中央口给的全部行在这里只被读**一次**，不在任何下游重扫。
    """
    try:
        from plugins.bot_unified_runtime.domains.ops.monitor.error_report import (
            _default_config_getter,
            _version_pairs,
        )

        rows = _version_pairs(_default_config_getter)
    except Exception:  # noqa: BLE001 - 中央采集口炸了整段缺席，不自己拼版本
        return {}
    out: dict[str, str] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        value = str(row.get("value") or "").strip()
        if label and value and value not in _VERSION_MISSING_VALUES:
            out[label] = value
    return out


def _version_rows_map() -> dict[str, str]:
    """把中央口的行标签翻译成指标 id（映射不到的行由全景腿负责，不是丢弃）。"""
    out: dict[str, str] = {}
    for label, value in _version_rows_clean().items():
        metric_id = _VERSION_LABEL_TO_ID.get(label)
        if metric_id:
            out[metric_id] = value
    return out


def _adapter_version_rows() -> list[tuple[str, str]]:
    """适配器全景「中央行标签 → 版本」：中央口每一行 ``适配器 · X`` 都在
    （用户点名 onebot/telegram/github/gitee/satori 全家，闭集映射只留 onebot
    会丢行）。与单列的「OneBot 适配器」并存——那是主协议端一眼位，这是全景位。

    行标签**逐字沿用中央口形态**（不做剥前缀的清洗）：覆盖面锁
    ``tests/test_host_state_coverage.py`` 拿 ``error_report._adapter_dist_pairs()``
    现算逐名比对——中央口给的就是「适配器 · X」这种带前缀标签，这里再洗一道
    等于引入第二个归一口，比对永远差一层变换。全景值里的版本仍全部来自
    中央口转发的发行版元数据现算值，本文件不手抄。
    """
    rows: list[tuple[str, str]] = []
    for label, value in _version_rows_clean().items():
        if label.startswith(_ADAPTER_LABEL_PREFIX):
            short = label[len(_ADAPTER_LABEL_PREFIX) :].strip()
            if short:
                rows.append((label, value))
    return sorted(rows)


# 插件全家枚举的进程级缓存（与 error_report._adapter_dists_label 同一口径）：
# ``metadata.distributions()`` 全盘扫描在本机实测按百毫秒计（数百个发行版的
# METADATA 解析），装/卸插件发行版本就要求重启——进程内不变，扫一次就够。
# 枚举整体失败也缓存空表：那是「这台机器没有这条腿」，不是可以重试出真数的
# 瞬时故障，反复重扫只会把代价摊到每一张卡上。
_PLUGIN_DISTS_CACHE: list[tuple[str, str]] | None = None


def _dependency_plugin_rows() -> list[tuple[str, str]]:
    """``nonebot-plugin*`` 发行版全景「短名 → 版本」（用户点名「依赖插件全家」）。

    中央版本口没有这一路（它只盘 nonebot 本体/适配器/插件包自身），所以这里
    另开一条**只读发行版元数据**的缝：读的是装出来的事实，不手抄任何版本值。
    短名剥掉 ``nonebot-plugin-`` 前缀（整行前缀噪声，一屏插件全叫同一个前缀
    等于没名字）；单个损坏发行版跳过，枚举整体失败或一个都没有 → 空表
    （采集器据此折「未探测」，绝不编数）。
    """
    global _PLUGIN_DISTS_CACHE
    if _PLUGIN_DISTS_CACHE is not None:
        return list(_PLUGIN_DISTS_CACHE)
    rows: list[tuple[str, str]] = []
    try:
        from importlib import metadata

        for dist in metadata.distributions():
            try:
                name = str(dist.metadata.get("Name") or "").strip()
                version = str(dist.version or "").strip()
            except Exception:  # noqa: BLE001, S112 - 损坏发行版换下一个。
                continue
            if name.lower().startswith("nonebot-plugin"):
                short = name[len("nonebot-plugin") :].lstrip("-_").strip() or name
                rows.append((short, version or "unknown"))
    except Exception:  # noqa: BLE001 - 枚举本身失败整体降级空表（未探测腿）。
        rows = []
    _PLUGIN_DISTS_CACHE = sorted(rows)
    return list(_PLUGIN_DISTS_CACHE)


def _core_dependency_rows() -> list[tuple[str, str]]:
    """固定核心依赖名单的已装版本（用户点名「pydantic/nonebot 依赖全家」）。

    逐个 ``importlib.metadata.version`` 现算——名单外的包不盘（长了卡读不动），
    名单里缺的整名跳过（可选依赖没装是事实，不是故障），一个都没查到 →
    采集器折「未探测」。顺序跟随 ``_CORE_DEPENDENCY_DISTRIBUTIONS`` 声明序，
    不在这里排序：卡上行序要稳定可指认。
    """
    rows: list[tuple[str, str]] = []
    try:
        from importlib import metadata
    except Exception:  # noqa: BLE001 - 连标准库这关都过不去，未探测腿
        return rows
    for name in _CORE_DEPENDENCY_DISTRIBUTIONS:
        try:
            version = str(metadata.version(name) or "").strip()
        except Exception:  # noqa: BLE001, S112 - 没装/元数据损坏：跳过这一名。
            continue
        if version:
            rows.append((name, version))
    return rows


def _cpu_label() -> str:
    """CPU 型号：注册表 ``ProcessorNameString`` 优先，``platform.processor()`` 只兜底。

    本机实测：``platform.processor()`` 回的是注册表 ``Identifier`` 那一串
    ——「Intel64 Family 6 Model 183 Stepping 1, GenuineIntel」。那是 CPUID
    描述符、不是型号，摆进「宿主电脑各项配置」等于给人一行废话；可读的厂商
    型号在 ``ProcessorNameString`` 里。这段读法原住 ``monitor/host_status.py``
    （2026-09-25 实测调通的那份），2026-09-26 随「取数口唯一」收敛迁入本文件。
    """
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        ) as key:
            name = " ".join(str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).split())
        if name:
            return name
    except Exception:  # noqa: S110, BLE001 - 注册表读不到（非 Windows/精简系统）退回通用探测
        pass
    return _cpu_label_fallback()


def _cpu_label_fallback() -> str:
    """``platform.processor()`` 兜底腿（拆成独立函数：门按函数粒度认取数落点）。"""
    raw = " ".join(str(platform.processor() or "").split())
    if "Family" in raw and "Model" in raw:
        return ""
    return raw


# 本机（协议端版本号以版本腿现读为准，此处不手抄）实测：显示类注册表里只有
# DriverDesc 有值，DeviceName / HardwareInformation.DeviceName 两个都拒绝访问
# （WinError 5），所以主键放 DriverDesc，其余只作别的驱动形态的兜底。
_GPU_VALUE_NAMES = (
    "DriverDesc",
    "HardwareInformation.DeviceName",
    "DeviceName",
)


def _gpu_labels() -> list[str]:
    """显卡型号（显示类注册表逐号读；psutil 不管 GPU，所以这一路必须自己走）。"""
    try:
        import winreg
    except Exception:  # noqa: BLE001 - 非 Windows 没有注册表这回事
        return []

    gpus: list[str] = []
    try:
        root = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}",
        )
    except Exception:  # noqa: BLE001 - 没有显示类注册表（精简系统/非 Windows）就是没读数
        return []
    try:
        count = winreg.QueryInfoKey(root)[0]
        for index in range(count):
            try:
                slot_name = winreg.EnumKey(root, index)
            except OSError:
                continue
            if not slot_name.isdigit():  # Configuration / Properties 一类非实例键
                continue
            try:
                with winreg.OpenKey(root, slot_name) as slot:
                    friendly = ""
                    for value_name in _GPU_VALUE_NAMES:
                        try:
                            candidate = str(winreg.QueryValueEx(slot, value_name)[0]).strip()
                        except OSError:
                            continue
                        if candidate:
                            friendly = candidate
                            break
            except OSError:  # 单槽读不动只丢这一行，不拖垮其余显卡。
                continue
            cleaned = " ".join(friendly.split())
            if cleaned and cleaned not in gpus:
                gpus.append(cleaned)
    finally:
        winreg.CloseKey(root)
    return gpus


def _cpu_model_text() -> str:
    """取数缝（测试 monkeypatch 这一层，不 patch 采集器本体）：读 CPU 型号。

    收敛前这层是「先问 host_status、再自己兜底」的两段式；注册表读法迁入本文件
    后，缝只把 ``_cpu_label`` 的输出做单行空白归一——真读数在上面那一处。
    """
    return " ".join(str(_cpu_label() or "").split())


def _gpu_model_rows() -> list[str]:
    """取数缝：显卡型号清单（真读数是上面的 ``_gpu_labels``）。"""
    return [str(x).strip() for x in _gpu_labels() if str(x).strip()]



def _query_nvidia_smi(timeout_seconds: float) -> tuple[str, str]:
    """显存只读查询。返回 (stdout, note)；一切非正常退出都折成空 stdout + 原因。

    本机实况是 ``Failed to initialize NVML``（returncode≠0）——那是合法的
    「未探测」来源，不是异常，绝不据此编一个显存数。
    """
    try:
        proc = subprocess.run(
            _NVIDIA_SMI_ARGS,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return ("", "本机没有 nvidia-smi 命令")
    except subprocess.TimeoutExpired:
        return ("", f"nvidia-smi 超过 {timeout_seconds} 秒未返回")
    except Exception as exc:  # noqa: BLE001 - 调用面任何异常折成降级原因
        return ("", f"nvidia-smi 调用异常：{type(exc).__name__}")
    if proc.returncode != 0:
        stderr = " ".join(str(proc.stderr or "").split())[:120]
        return ("", f"nvidia-smi 退出码 {proc.returncode}：{stderr or '无错误输出'}")
    return (str(proc.stdout or "").strip(), "")


def _query_cuda_vram() -> tuple[list[tuple[str, float, float]], str]:
    """显存第二腿（torch 直读）：返回 ``([(卡名, 已用字节, 总字节)], note)``。

    存在的理由：本机 NVML 常年挂死（``Failed to initialize NVML``），第一腿
    按设计降级后卡上就永远没有显存行；torch 若在册，``mem_get_info`` 走的
    是 CUDA 运行时而不是 NVML 服务，是合法的第二次取数机会——但仍只是
    只读查询，两腿皆死照常「未探测」，绝不编数。没装 torch、CUDA 不可用、
    逐卡读炸全部折成空表 + 原因交回，**绝不外抛**（整卡不许被这条腿带走）。
    """
    try:
        import torch
    except Exception as exc:  # noqa: BLE001 - 没装就是没装：这条腿不存在
        return ([], f"本机未提供 torch（CUDA 直读腿不可用：{type(exc).__name__}）")
    try:
        if not torch.cuda.is_available():
            return ([], "torch 在位但 CUDA 不可用（is_available 为 False）")
        count = int(torch.cuda.device_count())
    except Exception as exc:  # noqa: BLE001 - 探测面异常折成原因，不外抛
        return ([], f"torch CUDA 探测异常：{type(exc).__name__}")
    rows: list[tuple[str, float, float]] = []
    for index in range(count):
        try:
            name = str(torch.cuda.get_device_name(index)).strip()
            free_bytes, total_bytes = torch.cuda.mem_get_info(index)
            if not name:
                continue
            used = max(0.0, float(total_bytes) - float(free_bytes))
            rows.append((name, used, float(total_bytes)))
        except Exception:  # noqa: BLE001, S112 - 单卡读炸只丢这张卡。
            continue
    if not rows and count:
        return ([], "torch.cuda 报了设备数但逐卡读数全部失败")
    return (rows, "")


def _disk_value(usage: Any) -> str:
    return (
        f"总 {_gib(usage.total)} · 可用 {_gib(usage.free)} · 占用 {float(usage.percent):.1f}%"
    )


def _stdlib_disk_usage_rows() -> list[tuple[str, str]]:
    """psutil 缺席时的磁盘腿：标准库按盘符探活 + shutil.disk_usage，只读。"""
    rows: list[tuple[str, str]] = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        try:
            if not os.path.exists(root):
                continue
            rows.append((f"{letter}:\\", _disk_value(shutil.disk_usage(root))))
        except OSError:  # 空盘符/可移动介质未就绪：少一行不拦其余盘
            continue
    return rows


def _protocol_endpoint_rows() -> list[tuple[str, str]]:
    """协议端在线与端口，``(标签, 值)`` 行——端点事实**只问 nonebot 在册公共口**。

    简报硬口径：``nonebot.get_driver()`` / ``nonebot.get_bots()`` 是这套系统
    对「有哪些端点、谁在线」的唯一公共答案；不许自己扫端口、不许直接读协议
    端配置目录、不许另起第二条取数通路。bot 进程之外（离线测试）这俩抛
    ``ValueError``——那是合法的「这台机器此刻没有这台运行」，折成空表交回，
    采集器据此写「未探测」；本缝在任何形态下都不外抛。
    """
    try:
        import nonebot

        driver = nonebot.get_driver()
        bots = dict(nonebot.get_bots())
    except Exception:  # noqa: BLE001 - 未初始化/导入失败：这条腿今天不存在
        return []
    rows: list[tuple[str, str]] = []
    try:
        by_adapter: dict[str, list[str]] = {}
        for self_id, bot in bots.items():
            adapter = str(getattr(bot, "type", "") or "").strip() or "未知"
            by_adapter.setdefault(adapter, []).append(str(self_id))
        if by_adapter:
            segments = [
                f"{adapter} 在线 {len(ids)}（{'、'.join(sorted(ids))}）"
                for adapter, ids in sorted(by_adapter.items())
            ]
            rows.append(("协议端连接", "；".join(segments)))
        else:
            rows.append(("协议端连接", "在线 bot 0"))
        config = getattr(driver, "config", None)
        host = str(getattr(config, "host", "") or "").strip()
        port = str(getattr(config, "port", "") or "").strip()
        if host and port:
            rows.append(("监听端点", f"{host}:{port}"))
        ws_urls = [
            str(url).strip()
            for url in (getattr(config, "onebot_ws_urls", None) or [])
            if str(url).strip()
        ]
        if ws_urls:
            rows.append(("正向 WS", "、".join(sorted(ws_urls))))
    except Exception:  # noqa: BLE001, S110 - 组装期异常：已到手几行算几行，不外抛
        pass
    return [(label, value) for label, value in rows if label.strip() and value.strip()]


# ---------------------------------------------------------------------------
# 采集器（每个返回 1..n 条 HostMetric；抛出的异常由 _collect_spec 收口成
# 该项「采集失败」，这是「单项失败不带走整卡」的实现点）
# ---------------------------------------------------------------------------


def _collect_from_version_source(spec: MetricSpec) -> list[HostMetric]:
    value = str(_version_rows_map().get(spec.metric_id) or "").strip()
    if not value:
        return [
            _not_probed(
                spec, source=VERSION_PAIRS_SOURCE, note="中央版本采集口没给这一行"
            )
        ]
    return [_ok(spec, value, VERSION_PAIRS_SOURCE)]


def _collect_cpu_model(spec: MetricSpec) -> list[HostMetric]:
    text = " ".join(str(_cpu_model_text() or "").split())
    if not text:
        return [_not_probed(spec, source="host_metrics._cpu_label（注册表）")]
    return [_ok(spec, text, "host_metrics._cpu_label（注册表 ProcessorNameString）")]


def _collect_cpu_cores(spec: MetricSpec) -> list[HostMetric]:
    ps = _psutil_module()
    physical: int | None = None
    logical = _logical_core_count()
    source = "psutil.cpu_count"
    if ps is None:
        source = "os.cpu_count（本机未装 psutil，此项来自标准库）"
    else:
        physical = ps.cpu_count(logical=False)
        logical = ps.cpu_count(logical=True) or logical
    if not logical:
        return [_not_probed(spec, source=source)]
    if physical and physical != logical:
        value = f"{physical} 核 {logical} 线程"
    elif physical:
        value = f"{physical} 核"
    else:
        value = f"逻辑 {logical} 线程（物理核数未探测）"
    return [_ok(spec, value, source)]


def _collect_memory(spec: MetricSpec) -> list[HostMetric]:
    ps = _psutil_module()
    if ps is None:
        return [
            _not_probed(
                spec, source="psutil", note="本机未装 psutil，内存读数无标准库兜底来源"
            )
        ]
    mem = ps.virtual_memory()
    value = (
        f"总 {_gib(mem.total)} · 可用 {_gib(mem.available)} · 占用 {float(mem.percent):.1f}%"
    )
    return [_ok(spec, value, "psutil.virtual_memory")]


def _collect_swap(spec: MetricSpec) -> list[HostMetric]:
    """页面文件（旧件 ``host_status._memory_rows`` 的那一行，收敛后在册）。

    ``total == 0`` 是「这台机器没开页面文件」这个事实本身，不是取不到——但值轨
    只准放真数或诚实占位，所以折成「未探测」并在 note 里说清是没启用。
    """
    ps = _psutil_module()
    if ps is None:
        return [
            _not_probed(
                spec,
                source="psutil",
                note="本机未装 psutil，页面文件读数无标准库兜底来源",
            )
        ]
    swap_fn = getattr(ps, "swap_memory", None)
    if not callable(swap_fn):
        # 平台/构建不提供这一路（精简 psutil、非 Windows 无页面文件概念）：
        # 那是「取不到」不是「采集炸了」，折成未探测，别占一个采集失败位。
        return [_not_probed(spec, source="psutil.swap_memory", note="psutil 不提供页面文件")]
    swap = swap_fn()
    if swap.total <= 0:
        return [_not_probed(spec, source="psutil.swap_memory", note="系统未启用页面文件")]
    return [
        _ok(
            spec,
            f"已用 {_gib(swap.used)} / {_gib(swap.total)} · 占用 {float(swap.percent):.1f}%",
            "psutil.swap_memory",
        )
    ]


def _collect_machine_uptime(spec: MetricSpec) -> list[HostMetric]:
    """机器开机时长（旧件 ``host_status._load_rows`` 的「已开机」那行）。

    与版本腿的「运行时长」不是一件事：那是 **bot 进程**活了多久（由
    ``error_report.format_uptime`` 给），这是**这台机器**开机多久。两行并存、
    标签各自点名，缺一个就少一份事实。
    """
    ps = _psutil_module()
    if ps is None:
        return [
            _not_probed(
                spec,
                source="psutil",
                note="本机未装 psutil，开机时长无标准库兜底来源",
            )
        ]
    boot = getattr(ps, "boot_time", None)
    if not callable(boot):
        return [_not_probed(spec, source="psutil.boot_time", note="psutil 不提供开机时刻")]
    seconds = max(0, int(time.time() - float(boot())))
    return [_ok(spec, _duration_text(seconds), "psutil.boot_time")]


def _collect_gpu_model(spec: MetricSpec) -> list[HostMetric]:
    rows = _gpu_model_rows()
    if not rows:
        return [
            _not_probed(spec, source="host_metrics._gpu_labels（注册表）", note="显示类注册表无读数")
        ]
    return [_ok(spec, "、".join(rows), "host_metrics._gpu_labels（显示类注册表）")]


def _gpu_memory_cuda_leg(spec: MetricSpec, nv_note: str) -> list[HostMetric]:
    """NVML 腿空手时的第二腿（torch 直读）；两腿皆死才折「未探测」。

    note 并列两腿原因——只写一条就等于把「为什么没数」的半份事实藏了。
    """
    cuda_rows, cuda_note = _query_cuda_vram()
    segments: list[str] = []
    for name, used, total in cuda_rows:
        if total <= 0:
            continue
        share = f"（占用 {used / total * 100:.1f}%）"
        segments.append(
            f"{name}：已用 {used / 1024**3:.1f} / {total / 1024**3:.1f} GB{share}"
        )
    if segments:
        return [_ok(spec, "；".join(segments), _CUDA_SOURCE)]
    combined = f"{nv_note}；CUDA 腿：{cuda_note or 'torch.cuda 未给出可读设备'}"
    return [
        _not_probed(
            spec, source=f"{_NVIDIA_SOURCE} / {_CUDA_SOURCE}", note=combined
        )
    ]


def _collect_gpu_memory(spec: MetricSpec) -> list[HostMetric]:
    text, note = _query_nvidia_smi(_NVIDIA_SMI_TIMEOUT_SECONDS)
    text = str(text or "").strip()
    if not text:
        return _gpu_memory_cuda_leg(spec, note or "nvidia-smi 无输出")
    segments: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        fields = [part.strip() for part in line.split(",")]
        if len(fields) < 4:
            continue
        name = ",".join(fields[:-3]).strip()
        try:
            used = float(fields[-3])
            total = float(fields[-2])
            util = float(fields[-1])
        except ValueError:
            continue
        share = f"（占用 {used / total * 100:.1f}%）" if total > 0 else ""
        segments.append(
            f"{name}：已用 {used / 1024:.1f} / {total / 1024:.1f} GB{share}"
            f" · 利用率 {util:.0f}%"
        )
    if not segments:
        return [_not_probed(spec, source=_NVIDIA_SOURCE, note="nvidia-smi 输出形态不认识")]
    return [_ok(spec, "；".join(segments), _NVIDIA_SOURCE)]


def _collect_disk(spec: MetricSpec) -> list[HostMetric]:
    ps = _psutil_module()
    rows: list[tuple[str, str]] = []
    if ps is not None:
        for part in ps.disk_partitions(all=False):
            mount = str(getattr(part, "mountpoint", "") or "").strip()
            if not mount:
                continue
            try:
                rows.append((mount, _disk_value(ps.disk_usage(mount))))
            except Exception:  # noqa: BLE001, S112 - 单盘读不动只丢这一行
                continue
        source = "psutil.disk_partitions + psutil.disk_usage"
    else:
        rows = _stdlib_disk_usage_rows()
        source = "shutil.disk_usage（本机未装 psutil，此项来自标准库）"
    if not rows:
        return [_not_probed(spec, source=source, note="未枚举到可读分区")]
    return [_ok(spec, value, source, label=f"磁盘 {mount}") for mount, value in rows]


def _collect_process_usage(spec: MetricSpec) -> list[HostMetric]:
    ps = _psutil_module()
    if ps is None:
        return [
            _not_probed(
                spec,
                source="psutil",
                note="本机未装 psutil，进程 RSS/CPU 时间无标准库兜底来源",
            )
        ]
    proc = ps.Process()
    rss = proc.memory_info().rss
    times = proc.cpu_times()
    spent = float(getattr(times, "user", 0.0) or 0.0) + float(
        getattr(times, "system", 0.0) or 0.0
    )
    # 瞬时 CPU% 必须带间隔窗采样：``interval=None`` 的首采是「自进程启动以来的
    # 平均值」，摆进「此刻用量」栏就是假数（本机已知坑）。老 psutil/平台不提供
    # 这条 API 时降级回两段值——缺一段事实不等于整行判死，「未探测」只留给
    # 全部取不到的场合。
    instant: float | None
    try:
        instant = float(
            proc.cpu_percent(interval=_CPU_SAMPLE_INTERVAL_SECONDS) or 0.0
        )
    except (AttributeError, OSError, ValueError, TypeError):
        instant = None
    if instant is None:
        value = f"常驻内存 {_gib(rss)} · 累计 CPU {_duration_text(spent)}"
    else:
        value = (
            f"常驻内存 {_gib(rss)} · CPU {instant:.1f}% · "
            f"累计 CPU {_duration_text(spent)}"
        )
    return [_ok(spec, value, "psutil.Process（本 bot 进程）")]


def _collect_cpu_percent(spec: MetricSpec) -> list[HostMetric]:
    ps = _psutil_module()
    if ps is None:
        return [
            _not_probed(
                spec, source="psutil", note="本机未装 psutil，CPU 占用率无标准库兜底来源"
            )
        ]
    percent = ps.cpu_percent(interval=_CPU_SAMPLE_INTERVAL_SECONDS)
    if percent is None:
        return [_not_probed(spec, source="psutil.cpu_percent", note="平台不支持采样")]
    return [_ok(spec, f"{float(percent):.1f}%", "psutil.cpu_percent（200ms 窗）")]


def _collect_adapter_versions(spec: MetricSpec) -> list[HostMetric]:
    """适配器全景一行收齐：闭集映射只留 onebot 会丢的行，由这条全景位补回。

    值里的每个版本号都来自中央版本口转发的发行版元数据现算值（缝本体
    :func:`_adapter_version_rows`），本采集器不手抄任何版本；来源照旧是中央
    口常量——全景腿和单列腿同源，不是第二真身。
    """
    rows = _adapter_version_rows()
    if not rows:
        return [
            _not_probed(
                spec,
                source=VERSION_PAIRS_SOURCE,
                note="中央版本口没有给出任何「适配器 · X」行",
            )
        ]
    value = " · ".join(f"{short} {version}" for short, version in rows)
    return [_ok(spec, value, VERSION_PAIRS_SOURCE)]


def _collect_dependency_plugins(spec: MetricSpec) -> list[HostMetric]:
    """``nonebot-plugin*`` 插件全家：版本值全部来自发行版元数据现算，不手抄。"""
    rows = _dependency_plugin_rows()
    if not rows:
        return [
            _not_probed(
                spec,
                source=_PLUGIN_DISTS_SOURCE,
                note="未枚举到 nonebot-plugin* 发行版，或枚举本身失败",
            )
        ]
    value = " · ".join(f"{short} {version}" for short, version in rows)
    return [_ok(spec, value, _PLUGIN_DISTS_SOURCE)]


def _collect_dependency_versions(spec: MetricSpec) -> list[HostMetric]:
    """固定核心依赖名单：逐个 ``importlib.metadata.version`` 现算，不手抄。"""
    rows = _core_dependency_rows()
    if not rows:
        return [
            _not_probed(
                spec,
                source=_CORE_DEPS_SOURCE,
                note="固定核心依赖名单一个都没查到版本（未装或元数据不可读）",
            )
        ]
    value = " · ".join(f"{name} {version}" for name, version in rows)
    return [_ok(spec, value, _CORE_DEPS_SOURCE)]


def _collect_protocol_endpoints(spec: MetricSpec) -> list[HostMetric]:
    """协议端在线/监听/正向 WS：一行端点一条读数，标签沿用缝给的行标签。

    离线（nonebot 未初始化）拿不到任何行——那是「未探测」不是「采集失败」，
    note 点名来源口，用户一眼知道去哪找答案。
    """
    rows = _protocol_endpoint_rows()
    if not rows:
        return [
            _not_probed(
                spec,
                source=_ENDPOINTS_SOURCE,
                note="nonebot 未初始化或没有可端出的端点行（bot 进程外属正常形态）",
            )
        ]
    metrics: list[HostMetric] = []
    for label, value in rows:
        cleaned_label = str(label).strip()
        cleaned_value = str(value).strip()
        if not cleaned_label or not cleaned_value:
            continue
        metrics.append(_ok(spec, cleaned_value, _ENDPOINTS_SOURCE, label=cleaned_label))
    if not metrics:
        return [
            _not_probed(
                spec, source=_ENDPOINTS_SOURCE, note="端点行全为空标签/空值，无一可端"
            )
        ]
    return metrics


_COLLECTORS: dict[str, Callable[[MetricSpec], list[HostMetric]]] = {
    "nonebot_version": _collect_from_version_source,
    "adapter_onebot_version": _collect_from_version_source,
    "adapter_versions": _collect_adapter_versions,
    "protocol_client_version": _collect_from_version_source,
    "plugin_version": _collect_from_version_source,
    "dependency_plugins": _collect_dependency_plugins,
    "dependency_versions": _collect_dependency_versions,
    "build_id": _collect_from_version_source,
    "python_version": _collect_from_version_source,
    "os_version": _collect_from_version_source,
    "cpu_model": _collect_cpu_model,
    "cpu_cores": _collect_cpu_cores,
    "memory": _collect_memory,
    "swap": _collect_swap,
    "gpu_model": _collect_gpu_model,
    "gpu_memory": _collect_gpu_memory,
    "disk": _collect_disk,
    "cpu_percent": _collect_cpu_percent,
    "process_usage": _collect_process_usage,
    "machine_uptime": _collect_machine_uptime,
    "process_uptime": _collect_from_version_source,
    "protocol_endpoints": _collect_protocol_endpoints,
}


def _collect_spec(metric_id: str) -> list[HostMetric]:
    """单指标采集的统一收口：炸了只脏该项（简报硬要求 4 的实现点）。"""
    spec = _SPEC_BY_ID[metric_id]
    try:
        return _COLLECTORS[metric_id](spec)
    except Exception as exc:  # noqa: BLE001
        return [_failed(spec, exc)]


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def _to_thread(fn: Callable[..., Any], *args: Any) -> Awaitable[Any]:
    """阻塞采集离环的唯一缝（测试 spy 它，断言没有任何活落在事件循环线程上）。"""
    return asyncio.to_thread(fn, *args)


def _taken_at() -> str:
    return time.strftime("%H:%M")


def psutil_available() -> bool:
    """本机是否装了 psutil——**取数侧事实**，由本文件独家回答。

    存在的理由：呈现适配器（``monitor/host_status.py``）要维持它自己的旧契约
    「没有 psutil 就整面交回空组」，但它自己**一律不许**再 import psutil——
    否则取数口就又成两处了。所以把「有没有这个数据源」升成一个公开问句，
    适配器只问、不读。
    """
    return _psutil_module() is not None


def collect_host_metrics_sync() -> HostMetricsReport:
    """同步入口：只准在**工作线程/线程池**里调（如既有 offload 池）。

    事件循环上请走 :func:`collect_host_metrics`（逐项 to_thread + 超时）。
    """
    items: list[HostMetric] = []
    for spec in METRIC_SPECS:
        items.extend(_collect_spec(spec.metric_id))
    return HostMetricsReport(items=tuple(items), taken_at=_taken_at())


async def collect_host_metrics(
    *, item_timeout_seconds: float = _DEFAULT_ITEM_TIMEOUT_SECONDS,
) -> HostMetricsReport:
    """异步入口：每项采集一个 ``to_thread`` 任务 + 一个 ``wait_for`` 超时。

    超时只中止**等待**——工作线程里的系统调用（如卡死的 nvidia-smi）会自己
    跑完再退场，那是 Windows 线程模型给不了强杀的现实；卡因此绝不会被拖住，
    该项值诚实记「采集失败：TimeoutError」。
    """

    async def one(spec: MetricSpec) -> list[HostMetric]:
        try:
            return await asyncio.wait_for(
                _to_thread(_collect_spec, spec.metric_id),
                max(0.01, float(item_timeout_seconds)),
            )
        except asyncio.TimeoutError:
            return [
                _failed(spec, TimeoutError(), source="wait_for")
            ]
        except Exception as exc:  # noqa: BLE001 - 兜底：调度层自身炸也不带不走行
            return [_failed(spec, exc)]

    chunks = await asyncio.gather(*(one(spec) for spec in METRIC_SPECS))
    items: list[HostMetric] = []
    for chunk in chunks:
        items.extend(chunk)
    return HostMetricsReport(items=tuple(items), taken_at=_taken_at())


# ---------------------------------------------------------------------------
# 呈现腿：只产出「属性名 + 属性值」数据与通用卡 payload，零新模板
# （render_universal_card_html 的 stats 区正好是这一形态，与 host_card 同口径）
#
# 2026-09-26 二段收敛：``monitor/host_card.py::build_host_card_payload`` 与本段
# 的 ``build_host_metrics_card_payload`` 原是两枚逐行同构的 payload 拼装器
# （同名后缀循环 + 「取样时刻」前缀 + 分组导语各抄一份）。收敛方向＝**拼装逻辑
# 只住本文件这一枚 ``assemble_card_payload``**；旧件降为「换一套标题与导语字面
# 的薄调用方」。为什么是 host_card 让给这里而不是反向：payload 是「数据→卡片
# 形状」的纯函数，跟着取数真身走才不会两处派生；host_card 保住的是它独有价值
# ——落图口（digest + 与诊断卡同一条 render_html_card）。同名后缀循环现在全仓
# 只出现一次，由 tests/test_host_state_card.py 的 AST 锁执法。
# ---------------------------------------------------------------------------

CARD_TITLE = "宿主机状态"
CARD_BADGE = "超管视图"
CARD_FEATURE_LABEL = "宿主机状态"
GROUP_LEADS: dict[str, str] = {
    GROUP_VERSIONS: "软件与版本（全部取自中央采集口，不另拼）",
    GROUP_HARDWARE: "配置（注册表 / psutil / 标准库只读探测）",
    GROUP_USAGE: "此刻用量（现取，无缓存）",
}


def metrics_rows(report: HostMetricsReport) -> list[tuple[str, str]]:
    return [(item.label, item.value) for item in report.items]


def metrics_text(report: HostMetricsReport) -> str:
    """纯文本兜底版：一行一条事实，超管在群里读字也不能丢属性名。"""
    return "\n".join(f"{label}：{value}" for label, value in metrics_rows(report))


def assemble_card_payload(
    rows: Sequence[tuple[str, str, str]],
    *,
    group_order: Sequence[str],
    group_leads: Mapping[str, str],
    title: str,
    badge: str,
    feature_label: str,
    taken_at: str = "",
) -> dict[str, Any]:
    """**唯一的卡片 payload 拼装器**（纯函数，零取数）。

    - ``rows`` 为 ``(分组名, 属性名, 属性值)`` 三元组，插入序即卡上行序。
    - 同名属性（两块盘/两张卡）加「 2」「 3」序号后缀——dict 静默覆盖
      等于一行读数凭空消失，这条循环今天全仓只准出现在这一处。
    - 说明行按 ``group_order`` 里出现过读数的分组拼接（``group_order`` 给了
      固定序就出固定序，给了 dict 键序就跟它走，两种历史形态都在这里汇合）；
      导语缺失的分组用组名本身兜底。
    - 空值绝不上卡的前提由取数腿保证：每项要么真数、要么「未探测」、
      要么「采集失败：<类型>」。
    """
    stats: dict[str, str] = {}
    seen_groups: set[str] = set()
    for group, label, value in rows:
        seen_groups.add(group)
        key = label
        index = 2
        while key in stats:
            key = f"{label} {index}"
            index += 1
        stats[key] = value
    sections = [
        f"{group}——{group_leads.get(group, group)}"
        for group in group_order
        if group in seen_groups
    ]
    summary = " · ".join(sections)
    if taken_at:
        stamp = f"取样时刻 {taken_at}"
        summary = f"{stamp}；{summary}" if summary else stamp
    return {
        "page_type": "universal",
        "title": title,
        "badge": badge,
        "summary": summary,
        "stats": stats,
        "feature_label": feature_label,
    }


def build_host_metrics_card_payload(report: HostMetricsReport) -> dict[str, Any]:
    """拼通用卡 payload（``page_type=universal`` 的 stats 区，零新模板）。

    行为与逐字节口径全部由 :func:`assemble_card_payload` 负责；这里只喂
    「真身分组序 + 真身导语 + 真身标题」这一套呈现参数。
    """
    return assemble_card_payload(
        [(item.group, item.label, item.value) for item in report.items],
        group_order=(GROUP_VERSIONS, GROUP_HARDWARE, GROUP_USAGE),
        group_leads=GROUP_LEADS,
        title=CARD_TITLE,
        badge=CARD_BADGE,
        feature_label=CARD_FEATURE_LABEL,
        taken_at=report.taken_at,
    )


__all__ = [
    "CARD_BADGE",
    "CARD_FEATURE_LABEL",
    "CARD_TITLE",
    "GROUP_HARDWARE",
    "GROUP_LEADS",
    "GROUP_USAGE",
    "GROUP_VERSIONS",
    "METRIC_SPECS",
    "METRIC_SPEC_IDS",
    "NOT_PROBED",
    "STATE_FAILED",
    "STATE_NOT_PROBED",
    "STATE_OK",
    "VERSION_PAIRS_SOURCE",
    "HostMetric",
    "HostMetricsReport",
    "assemble_card_payload",
    "build_host_metrics_card_payload",
    "collect_host_metrics",
    "collect_host_metrics_sync",
    "metrics_rows",
    "metrics_text",
    "psutil_available",
]
