"""启动自检门（W1-重启自检门）：bot 启动时三跳探活，GO/NO-GO 一行落账。

背景：台账 #10 铁律「bot 未重启 ⇒ 历次完成全部待生效」靠人记；09-29
代理链补丁落了但如果忘记重启/启动失败，行为面毫无提示。本模块在启动期
机器执法三件事：

1. 本机 LLM 网关（AxonHub 127.0.0.1:8090）可达；
2. 应急直连档在位（注册表里有指向本机 Ollama 的渠道——全站死光的最后
   地板；没有 = 不哑兜底是空头支票）；
3. 应急脑（Ollama 端口）可达。

判定只写日志（GO/NO-GO + 每跳一行），**绝不阻断启动**（fail-open）：
自检是加值件，探针坏了不连坐主链。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass
class SelfcheckResult:
    """三跳自检结果：verdict=GO 仅当网关可达且应急档在位。

    Ollama 端口不可达只降级为 NO-GO 提示（应急脑暂不可用），不算启动
    阻塞项——它可能只是还没开。
    """

    gateway_ok: bool = False
    gateway_detail: str = ""
    emergency_floor_url: str | None = None
    ollama_ok: bool = False
    lines: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.gateway_ok and self.emergency_floor_url and self.ollama_ok:
            return "GO"
        return "NO-GO"


def scan_registry_payloads(settings_dir: Path) -> list[dict[str, Any]]:
    """扫 settings/runtime_settings_*.json，收集含 model_registry 的载荷。"""
    payloads: list[dict[str, Any]] = []
    if not settings_dir.is_dir():
        return payloads
    for path in sorted(settings_dir.glob("runtime_settings_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _logger.warning("selfcheck skip %s: %s", path.name, exc)
            continue
        if isinstance(payload, dict) and isinstance(payload.get("model_registry"), dict):
            payloads.append(payload)
    return payloads


def find_emergency_floor(
    registry_payloads: list[dict[str, Any]],
) -> str | None:
    """找应急直连地板：base_url 指向本机 Ollama（:11434）的注册渠道。

    只有它满足「AxonHub 死了也直连可达」的不哑语义；经网关的应急档
    （:8090）不算地板。
    """
    for payload in registry_payloads:
        registry = payload.get("model_registry") or {}
        for entry in registry.values():
            if not isinstance(entry, dict):
                continue
            base_url = str(entry.get("base_url", ""))
            if ":11434" in base_url and "127.0.0.1" in base_url:
                return base_url
    return None


def run_selfcheck(
    *,
    gateway_base_url: str,
    registry_payloads: list[dict[str, Any]],
    probe: Callable[[str, int], bool],
    ollama_port: int = 11434,
) -> SelfcheckResult:
    """执行三跳自检并产出可直落日志的行。

    ``probe(host, port) -> bool`` 注入缝：生产传 TCP 探活，测试传桩。
    """
    from urllib.parse import urlsplit

    result = SelfcheckResult()
    parts = urlsplit(str(gateway_base_url or "").strip())
    gateway_host = parts.hostname or "127.0.0.1"
    gateway_port = parts.port or (443 if parts.scheme == "https" else 80)
    result.gateway_ok = probe(gateway_host, gateway_port)
    result.gateway_detail = f"{gateway_host}:{gateway_port}"

    result.emergency_floor_url = find_emergency_floor(registry_payloads)
    if result.emergency_floor_url:
        floor_parts = urlsplit(result.emergency_floor_url)
        result.ollama_ok = probe(
            floor_parts.hostname or "127.0.0.1",
            floor_parts.port or ollama_port,
        )

    result.lines.append(f"llm selfcheck: {result.verdict}")
    result.lines.append(
        f"  gateway {result.gateway_detail}: {'ok' if result.gateway_ok else 'UNREACHABLE（AxonHub 没起来？bot 仍继续启动）'}"
    )
    if result.emergency_floor_url is None:
        result.lines.append("  emergency floor: MISSING（注册表无 127.0.0.1:11434 直连应急档——不哑兜底是空头支票）")
    else:
        result.lines.append(
            f"  emergency floor {result.emergency_floor_url}: {'ok' if result.ollama_ok else 'UNREACHABLE（应急脑暂不可用，Ollama 没开？）'}"
        )
    return result
