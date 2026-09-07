"""逐家搜索 API 真实连通性自检（交接 P2.3 的工具部分）。

只做一次只读搜索请求，不发送任何 QQ/Telegram 消息；未配置 key 的提供器跳过。
用法：python -m plugins.bot_unified_runtime.sources.search_smoke
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from .search_api import build_api_search_provider

_SMOKE_QUERY = "鸣潮 守岸人"


def _result_entry(name: str, *, ok: bool, detail: str, latency_ms: int) -> dict[str, Any]:
    return {
        "provider": name,
        "ok": ok,
        "detail": detail,
        "latency_ms": latency_ms,
    }


def run_search_smoke(config: object, *, query: str = _SMOKE_QUERY) -> list[dict[str, Any]]:
    """对已配置 key 的每个提供器做一次真实查询，返回脱敏摘要。"""
    timeout = float(getattr(config, "bot_web_search_timeout_seconds", 6.0) or 6.0)
    proxy = str(getattr(config, "bot_download_proxy", "") or "").strip()
    providers, _fetcher = build_api_search_provider(
        config, timeout_seconds=timeout, proxy=proxy
    )
    results: list[dict[str, Any]] = []
    if not providers:
        return [
            _result_entry("chain", ok=False, detail="no provider configured", latency_ms=0)
        ]
    for provider in providers:
        name = str(getattr(provider, "name", "unknown"))
        started = time.monotonic()
        try:
            hits = provider.search(query, max_results=3)
        except Exception as exc:  # noqa: BLE001 - 自检必须吞掉单家失败继续下一家。
            latency = int((time.monotonic() - started) * 1000)
            results.append(
                _result_entry(name, ok=False, detail=f"error: {type(exc).__name__}", latency_ms=latency)
            )
            continue
        latency = int((time.monotonic() - started) * 1000)
        first_title = hits[0].title if hits else ""
        results.append(
            _result_entry(
                name,
                ok=bool(hits),
                detail=f"{len(hits)} hits: {first_title[:60]}",
                latency_ms=latency,
            )
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="search API providers smoke (read-only)")
    parser.add_argument("--query", default=_SMOKE_QUERY, help="one read-only search query")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    from ..smoke import load_smoke_config

    config = load_smoke_config()
    enabled = bool(getattr(config, "bot_web_search_enabled", False))
    if not enabled:
        print("search-smoke: bot_web_search_enabled=false，未启用联网搜索；跳过真实请求。")
        return 2
    results = run_search_smoke(config, query=args.query)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for entry in results:
            status = "OK " if entry["ok"] else "FAIL"
            print(
                f"[{status}] {entry['provider']:<12} {entry['latency_ms']:>5}ms  {entry['detail']}"
            )
    ok_any = any(entry["ok"] for entry in results)
    print("search-smoke:", "at least one provider answered" if ok_any else "no provider answered")
    return 0 if ok_any else 1


if __name__ == "__main__":
    raise SystemExit(main())
