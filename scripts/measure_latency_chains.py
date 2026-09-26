"""五链路延迟测量（docs/perf-optimization-plan.md §二 配套脚本）。

- 离线段（任何时刻可跑）：①项目内部路由判定 P50/P95；②HTML 渲染 P50/P95。
- 在线段（bot 在线才有意义）：③SnowLuma WS 端口握手；④SMTP 握手；⑤TG API getMe。
  探测失败一律输出 unreachable / no-config，绝不编造数值。

用法：
  python scripts/measure_latency_chains.py              # 全部段
  python scripts/measure_latency_chains.py render       # 只跑离线渲染段
  python scripts/measure_latency_chains.py route        # 只跑离线路由段

环境变量：
  BOT_RENDER_WAIT_BUDGET_MS / BOT_RENDER_MAX_CONCURRENCY —— 渲染段口径标注；
  BOT_SMTP_HOST/BOT_SMTP_PORT（或 MAIL_SMTP_HOST/MAIL_SMTP_PORT）—— SMTP 段；
  BOT_TELEGRAM_BOT_TOKEN（或 TELEGRAM_BOT_TOKEN）—— TG 段。
"""

from __future__ import annotations

import os
import socket
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _pctl(values: list[float], q: float) -> float:
    data = sorted(values)
    idx = min(len(data) - 1, max(0, round(q * (len(data) - 1))))
    return data[idx]


def _report(name: str, values: list[float], unit: str = "ms") -> None:
    if not values:
        print(f"  [{name}] 无样本")
        return
    print(
        f"  [{name}] n={len(values)} P50={_pctl(values, 0.5):.3f}{unit} "
        f"P95={_pctl(values, 0.95):.3f}{unit} max={max(values):.3f}{unit}"
    )


# ---------------------------------------------------------------------------
# ① 项目内部：路由判定（classify_message_route，热路径含缓存）
# ---------------------------------------------------------------------------

_ROUTE_SAMPLES = [
    "占卜",
    "今天天气怎么样",
    "英伟达股价",
    "美元兑人民币",
    "点歌 恋爱循环",
    "https://www.bilibili.com/video/BV1xx411c7mD",
    "随便聊聊今天吃什么",
    "提醒我 12 点开会",
    "塔罗 三张",
    "莫斯科股指",
    "这是一条完全普通没有触发词的闲聊文本",
    "求籤",
]


def measure_route(n: int = 2000) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
        classify_message_route,
    )

    texts = [_ROUTE_SAMPLES[i % len(_ROUTE_SAMPLES)] for i in range(n)]
    # 预热：首次调用含模块级惰性装配。
    classify_message_route("预热", config=object(), alias_resolver=None)
    values: list[float] = []
    for text in texts:
        start = time.perf_counter()
        classify_message_route(text, config=object(), alias_resolver=None)
        values.append((time.perf_counter() - start) * 1000)
    print("① 项目内部（路由判定 classify_message_route）：")
    _report("route", values)


# ---------------------------------------------------------------------------
# ② HTML 渲染：PlaywrightRenderBackend 基准卡（离线）
# ---------------------------------------------------------------------------

_BENCH_HTML = (
    "<html><head><style>"
    "body{background:transparent;margin:0;font-family:Microsoft YaHei;}"
    ".card{width:420px;padding:24px;border-radius:14px;background:#f5f8fd;"
    "box-shadow:0 2px 8px rgba(60,90,160,.18);color:#1d2b4a;}"
    "</style></head><body>"
    "<div class='card'><h3 style='margin:0 0 8px;font-weight:600'>测量基准卡</h3>"
    "<p style='margin:0'>守岸人渲染链路 P95 基准样例。</p></div>"
    "</body></html>"
)


def measure_render(n: int = 6) -> None:
    from plugins.bot_unified_runtime.domains.render.render_backends import (
        PlaywrightRenderBackend,
    )

    concurrency = int(os.environ.get("BOT_RENDER_MAX_CONCURRENCY", "1") or 1)
    budget = os.environ.get("BOT_RENDER_WAIT_BUDGET_MS", "")
    backend = PlaywrightRenderBackend(max_concurrency=concurrency)
    if not backend.available:
        print("② HTML 渲染：playwright 不可用（unreachable）")
        return
    payload = {
        "html": _BENCH_HTML,
        "viewport": {"width": 480, "height": 240},
    }
    if budget.isdigit() and int(budget) > 0:
        payload["wait_budget_ms"] = int(budget)
    cold_start = time.perf_counter()
    first = backend.render_card(payload)
    cold_ms = (time.perf_counter() - cold_start) * 1000
    if first is None:
        print("② HTML 渲染：首张出图失败（unreachable——检查 playwright/Chromium）")
        return
    values: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        out = backend.render_card(payload)
        if out is None:
            print("② HTML 渲染：中途出图失败（unreachable）")
            return
        values.append((time.perf_counter() - start) * 1000)
    print(f"② HTML 渲染（max_concurrency={concurrency} wait_budget_ms={budget or 'off'}）：")
    print(f"  [cold] 首张（含浏览器冷启动）{cold_ms:.0f}ms")
    _report("render-warm", values)


# ---------------------------------------------------------------------------
# ③④⑤ 在线段：握手/API 计时，不可达即如实标注
# ---------------------------------------------------------------------------


def _tcp_probe(host: str, port: int, name: str, timeout: float = 2.0) -> None:
    values: list[float] = []
    for _ in range(3):
        start = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                values.append((time.perf_counter() - start) * 1000)
        except OSError as exc:
            print(f"③ [{name}] {host}:{port} unreachable（{exc.__class__.__name__}）")
            return
    print(f"  [{name}] {host}:{port} 握手：")
    _report(name, values)


def measure_napcat() -> None:
    print("③ SnowLuma WS（127.0.0.1:3001 TCP 握手，非全协议）：")
    _tcp_probe("127.0.0.1", 3001, "napcat-tcp")


def measure_mail() -> None:
    host = os.environ.get("BOT_SMTP_HOST") or os.environ.get("MAIL_SMTP_HOST")
    port = int(os.environ.get("BOT_SMTP_PORT") or os.environ.get("MAIL_SMTP_PORT") or 465)
    if not host:
        print("④ Mail：未配置 SMTP 主机（no-config），跳过")
        return
    print("④ Mail SMTP（握手）：")
    _tcp_probe(host, port, "smtp-tcp")


def measure_telegram() -> None:
    token = os.environ.get("BOT_TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("⑤ Telegram：未配置 token（no-config），跳过")
        return
    url = f"https://api.telegram.org/bot{token}/getMe"
    values: list[float] = []
    for _ in range(3):
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                resp.read()
        except OSError as exc:
            print(f"⑤ Telegram unreachable（{exc.__class__.__name__}）")
            return
        values.append((time.perf_counter() - start) * 1000)
    print("⑤ Telegram API（getMe）：")
    _report("tg-api", values)


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else "all"
    if only in ("all", "route"):
        measure_route()
    if only in ("all", "render"):
        measure_render()
    if only in ("all", "napcat"):
        measure_napcat()
    if only in ("all", "mail"):
        measure_mail()
    if only in ("all", "telegram"):
        measure_telegram()


if __name__ == "__main__":
    main()
