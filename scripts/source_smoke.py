#!/usr/bin/env python
"""官方源实战 smoke：逐腿真调一次，验「数据源可被调用」。

为什么要有这把尺（用户 2026-10-13 立规）：
  「所有渠道必须实战 smoke 测试保证数据源可被调用」——登记册只登记「谁提供
  这个值」，**登记 ≠ 能调**。本尺按 ``official_sources.LEG_PROBES`` 对每条腿
  发**真请求**，记录 HTTP 码／延迟／字节数／是否被拒，产出可复核的 smoke 报告。

口径（写死）：
  - **只判可达性**，不解析业务字段（解析在各能力取数层，两者不混）；
  - 判绿＝HTTP 200 且字节数 > 0；3xx/4xx/5xx/超时/连接失败一律判红并留原样错误；
  - 需要额外头的腿（新浪须 Referer 等）从 ``LEG_PROBE_HEADERS`` 取，不硬编码在尺里；
  - **恒不写业务数据**；报告写到 --out（缺省 %TEMP%）。

用法：
    python scripts/source_smoke.py                  # 全腿 smoke，人读摘要
    python scripts/source_smoke.py --json           # 机器读 JSON
    python scripts/source_smoke.py --value 汇率中间价  # 只测某个值维
    python scripts/source_smoke.py --out <dir>      # 报告落点（缺省 TEMP）

退出码：0 = 全绿；1 = 有腿红；2 = 登记册读不到。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


def _load_registry():
    from plugins.bot_unified_runtime.domains.core.contracts import official_sources as src

    return src


def smoke_leg(
    value: str,
    org: str,
    url: str,
    headers: dict[str, str],
    *,
    timeout: float = 20.0,
    retries: int = 2,
) -> dict:
    """单腿真调（带受控重试）；返回结果字典（恒不抛）。

    为什么要重试：东财 push2 与中证 OSS 这类端点会**瞬时**断连/超时（同一条腿
    下一次就 200）——不重试会把「抖」误判成「死」。重试次数由 --retries 给，
    全部尝试都失败才算红；`attempts` 字段留痕（供区分「一次就通」与「重试才通」）。
    """
    record: dict = {
        "value": value,
        "org": org,
        "url": url,
        "ok": False,
        "status": None,
        "bytes": 0,
        "latency_ms": None,
        "attempts": 0,
        "error": "",
    }
    if not url:
        record["error"] = "无探针（该腿暂无机器可调入口）"
        return record
    last_error = ""
    started = time.monotonic()
    for attempt in range(1, max(1, int(retries)) + 1):
        record["attempts"] = attempt
        req = urllib.request.Request(url, headers={**_UA, **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(400000)
                record["status"] = resp.status
                record["bytes"] = len(body)
                record["ok"] = resp.status == 200 and len(body) > 0
                last_error = "" if record["ok"] else f"HTTP {resp.status}"
                if record["ok"]:
                    break
        except urllib.error.HTTPError as exc:
            record["status"] = exc.code
            last_error = f"HTTP {exc.code}"
            if exc.code not in (429, 500, 502, 503, 504):
                break  # 4xx（除 429）是确定性拒绝，重试无意义。
        except Exception as exc:  # noqa: BLE001 - smoke 不抛，如实记错。
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < max(1, int(retries)):
            time.sleep(1.0)
    record["error"] = last_error
    record["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
    return record


def run_smoke(
    only_value: str = "", *, timeout: float = 20.0, retries: int = 2
) -> list[dict]:
    """遍历登记册全腿（或指定值维）逐个 smoke。"""
    src = _load_registry()
    results: list[dict] = []
    for spec in src.OFFICIAL_SOURCES:
        if only_value and spec.value != only_value:
            continue
        for leg in spec.legs:
            results.append(
                smoke_leg(
                    spec.value,
                    leg.org,
                    src.probe_url_for(spec.value, leg.org),
                    src.probe_headers_for(spec.value, leg.org),
                    timeout=timeout,
                    retries=retries,
                )
            )
    return results


def summarize(results: list[dict]) -> dict:
    """按值维汇总：该值有几条腿绿了（**只有绿的才算数**）。"""
    by_value: dict[str, dict] = {}
    for r in results:
        slot = by_value.setdefault(r["value"], {"orgs": [], "ok_orgs": [], "rows": []})
        slot["orgs"].append(r["org"])
        if r["ok"]:
            slot["ok_orgs"].append(r["org"])
        slot["rows"].append(r)
    for value, slot in by_value.items():
        slot["ok_count"] = len(slot["ok_orgs"])
        slot["ready"] = slot["ok_count"] >= 3
    return by_value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="官方源实战 smoke（只读网络）")
    parser.add_argument("--json", action="store_true", help="输出机器读 JSON")
    parser.add_argument("--value", default="", help="只测某个值维")
    parser.add_argument("--timeout", type=float, default=20.0, help="单腿超时秒")
    parser.add_argument("--retries", type=int, default=2, help="单腿尝试次数（抖≠死）")
    parser.add_argument("--out", default="", help="报告落点目录（缺省 TEMP）")
    args = parser.parse_args(argv)

    try:
        _load_registry()
    except Exception as exc:  # noqa: BLE001
        print(f"登记册读不到：{exc}", file=sys.stderr)
        return 2

    results = run_smoke(args.value, timeout=args.timeout, retries=args.retries)
    by_value = summarize(results)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "legs_total": len(results),
        "legs_ok": sum(1 for r in results if r["ok"]),
        "by_value": {
            v: {
                "ok_count": s["ok_count"],
                "ready": s["ready"],
                "ok_orgs": s["ok_orgs"],
                "rows": s["rows"],
            }
            for v, s in by_value.items()
        },
    }

    out_dir = Path(args.out) if args.out else Path(
        __import__("tempfile").gettempdir()
    ) / "opencode"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out_dir / f"source_smoke_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"官方源 smoke：{payload['legs_ok']}/{payload['legs_total']} 腿绿")
        print()
        for value, s in by_value.items():
            mark = "✅" if s["ready"] else "❌"
            print(f"{mark} {value}（{s['ok_count']}/3 绿）")
            for row in s["rows"]:
                flag = "  ✓" if row["ok"] else "  ✗"
                retry = f" (试{row['attempts']}次)" if row.get("attempts", 1) > 1 else ""
                detail = (
                    f"{row['status']} {row['bytes']}B {row['latency_ms']}ms{retry}"
                    if row["ok"]
                    else (row["error"] or "未知")
                )
                print(f"{flag} {row['org']:<14} {detail}")
            print()

    return 0 if payload["legs_ok"] == payload["legs_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
