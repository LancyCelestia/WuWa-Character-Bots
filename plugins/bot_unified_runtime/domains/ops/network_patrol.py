"""网络巡检（W1-③ + Clash 探针）：双路探活、状态差分、带外告警素材。

背景（09-29 代理链故障）：全部上游中转站的出站被拴在 Clash 7890 单腿上，
Clash 进程死亡或节点到某站不通 ⇒ bot 全链超时，且没有任何主动告警——
故障要等用户自己发现。本模块提供低频（缺省 15 分钟）巡检：

- Clash 存活腿：TCP 探 127.0.0.1:7890（代理进程咽气即知，不等 LLM 死）；
- 上游域双路腿：每个域各测「直连」与「经代理」两条路径，产出诊断矩阵
  （哪个域哪条路通）——03:00 的故事不再是考古，而是看一行状态差分；
- 状态差分告警：只在「变坏/恢复」的边界发，不重复刷屏；告警走
  ``send_admin_alert_requests``（TG/邮件带外，不经 LLM 链——告警系统
  不和病人共用一条血管）。

fail-open 约束：探针任何异常归为该腿 down，绝不拖累 bot 主链；巡检自身
崩溃由调度层兜底记录。
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

#: 缺省巡检目标（09-30 全出站审计的 7 个上游域；可用配置覆盖）。
PATROL_TARGETS_DEFAULT: tuple[str, ...] = (
    "aiprc.top",
    "newapi.qianqianye.com",
    "www.starapi.cc",
    "toolcode.cc",
    "open.bigmodel.cn",
    "api.deepseek.com",
    "sub.potccv.com",
)

#: 巡检 JSONL 的体积上限（超过滚动出 .1 备份，防无界增长）。
_PATROL_JSONL_MAX_BYTES = 5 * 1024 * 1024


@dataclass
class PatrolLeg:
    """一条探活腿的结果：目标 + 路径 + 通断 + 一句话细节。"""

    target: str
    path: str  # "clash" | "direct" | "proxy"
    ok: bool
    detail: str = ""


@dataclass
class PatrolReport:
    """一轮巡检的完整结果。"""

    started_at: float = 0.0
    legs: list[PatrolLeg] = field(default_factory=list)

    def state(self) -> dict[str, bool]:
        """腿 → 通断的扁平快照（差分键 = f"{target}:{path}"）。"""
        return {f"{leg.target}:{leg.path}": leg.ok for leg in self.legs}


def probe_tcp(host: str, port: int, *, timeout: float = 1.5) -> bool:
    """TCP 探活：能建立连接即算活。任何异常 = 不活（fail-open 归 down）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_https(
    url: str,
    *,
    proxy: str = "",
    timeout: float = 10.0,
    transport: Any = None,
) -> tuple[bool, str]:
    """HTTPS 探活：拿到**任何** HTTP 应答（含 401/404/429）即算可达。

    直连腿固定 ``trust_env=False``（环境变量/系统代理不参与——本探针的
    「直连」语义必须是真的直连，否则矩阵失真）；代理腿显式传 proxy。
    返回 (ok, detail)，detail 是毫秒或异常缩略。
    """
    import httpx

    started = time.monotonic()
    try:
        kwargs: dict[str, Any] = {"timeout": timeout}
        if transport is not None:
            kwargs["transport"] = transport
        else:
            kwargs["proxy"] = proxy or None
            kwargs["trust_env"] = bool(proxy)
        with httpx.Client(**kwargs) as client:
            response = client.get(url)
        ms = int((time.monotonic() - started) * 1000)
        return True, f"HTTP {response.status_code} in {ms}ms"
    except Exception as exc:  # noqa: BLE001 - 探针吞一切异常转 down。
        return False, f"{type(exc).__name__}: {exc}"[:160]


def run_patrol(
    *,
    targets: list[str] | tuple[str, ...] = PATROL_TARGETS_DEFAULT,
    clash_proxy: str = "http://127.0.0.1:7890",
    clash_host: str = "127.0.0.1",
    clash_port: int = 7890,
    timeout: float = 10.0,
    transport: Any = None,
    tcp_probe: Any = None,
) -> PatrolReport:
    """跑一轮完整巡检：Clash 存活 + 每域直连/经代理双腿。

    ``transport`` 仅供测试注入（httpx.MockTransport）；生产为 None。
    ``tcp_probe`` 同为注入缝（缺省真探针）——测试**必须**注入桩，禁止
    对真实 7890 端口做断言：全量套件跑一小时期间代理状态会漂移，真端口
    竞态红＝假回归（09-30 全量套件实锤，2 枚）。
    """
    probe = tcp_probe if tcp_probe is not None else probe_tcp
    report = PatrolReport(started_at=time.time())
    clash_alive = probe(clash_host, clash_port)
    report.legs.append(
        PatrolLeg(target=f"{clash_host}:{clash_port}", path="clash", ok=clash_alive)
    )
    for domain in targets:
        domain = str(domain).strip()
        if not domain:
            continue
        url = f"https://{domain}/"
        direct_ok, direct_detail = probe_https(url, proxy="", timeout=timeout, transport=transport)
        report.legs.append(PatrolLeg(domain, "direct", direct_ok, direct_detail))
        if clash_alive:
            proxy_ok, proxy_detail = probe_https(
                url, proxy=clash_proxy, timeout=timeout, transport=transport
            )
        else:
            # 代理进程已死：代理腿直接判 down，不再对死端口白耗超时。
            proxy_ok, proxy_detail = False, "clash port down"
        report.legs.append(PatrolLeg(domain, "proxy", proxy_ok, proxy_detail))
    return report


def state_delta(
    previous: dict[str, bool] | None, current: dict[str, bool]
) -> list[tuple[str, bool]]:
    """差分：返回状态发生变化的 (键, 现值) 列表（变坏与恢复都报）。"""
    if previous is None:
        # 首轮不告警（没有基线，避免启动即风暴）；只建立基线。
        return []
    return [
        (key, ok) for key, ok in current.items() if previous.get(key) != ok
    ]


def format_alert_lines(delta: list[tuple[str, bool]]) -> list[str]:
    """差分 → 人话告警行（变坏=warning 语气，恢复=已恢复）。"""
    lines: list[str] = []
    for key, ok in delta:
        if ok:
            lines.append(f"网络巡检：{key} 已恢复 ✓")
        else:
            lines.append(f"网络巡检：{key} 不可达 ✗（Clash 死了或该路径被断，查 7890 与节点）")
    return lines


def append_patrol_jsonl(path: Path, report: PatrolReport) -> None:
    """一轮结果追加落盘（JSONL，超限滚动出 .1）。失败只记日志不抛。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > _PATROL_JSONL_MAX_BYTES:
            rotated = path.with_name(path.name + ".1")
            if rotated.exists():
                rotated.unlink()
            os.replace(path, rotated)
        payload = {
            "ts": report.started_at,
            "legs": [
                {"target": leg.target, "path": leg.path, "ok": leg.ok, "detail": leg.detail}
                for leg in report.legs
            ],
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as exc:
        _logger.warning("network patrol jsonl append failed: %s", exc)
