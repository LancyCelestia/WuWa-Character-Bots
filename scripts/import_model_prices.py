"""模型价目批量导入脚本：把渠道价目表写入运行时模型注册表。

数据来源=用户提供的渠道实付价目表（2026-09-17：UMI=标价÷3、浅夜=标价×0.6；price_per_call
为按次计费渠道的 元/请求）。幂等可重跑：只更新匹配条目的价格键，
绝不触碰 api_key/base_url 等连接配置。

匹配规则（两者都命中才写入，宁缺毋错）：
- model 名精确匹配（大小写不敏感，如 gemini-3.8-flash）；
- base_url 包含渠道 host 片段（如 newapi.qianqianye.com）。

用法：
    python scripts/import_model_prices.py            # dry-run 展示将写入的匹配
    python scripts/import_model_prices.py --apply    # 实际写入
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_paths import runtime_path

# (渠道 host 片段, 模型名, 输入价, 输出价, 缓存读价, 缓存创建价, 按次价元/请求)
PRICE_TABLE: list[tuple[str, str, float | None, float | None, float | None, float | None, float | None]] = [
    ("open.bigmodel.cn", "glm-5.3", 8, 28, 2, None, None),
    ("open.bigmodel.cn", "glm-5.3-flash", 0.8, 2.8, 0.23, None, None),
    ("api.deepseek.com", "deepseek-v4.1-flash", 1.0, 4.0, 0.02, None, None),
    ("api.deepseek.com", "deepseek-v4-flash", 1.5, 4.5, 0.05, None, None),
    ("api.deepseek.com", "deepseek-v4-pro", 3.0, 27.0, 0.10, None, None),
    ("dashscope.aliyuncs.com", "qwen3.8-flash", 0.8, 2.7, 0.10, None, None),
    ("dashscope.aliyuncs.com", "qwen3.8-max", 12.0, 36.0, 1.5, None, None),
    ("platform.moonshot.cn", "kimi-k3", 20.0, 100.0, 2.0, None, None),
    ("platform.moonshot.cn", "kimi-k2.6", 6.5, 27.0, 1.1, None, None),
    ("open.bigmodel.cn", "glm-5.3-coding", 8, 28, 2, None, None),
    ("starapi.cc", "gemini-3.8-flash", 0.1875, 0.9375, 0.01875, 0.01041625, None),
    ("starapi.cc", "gpt-5.6-terra", 0.29, 1.74, 0.029, 0.3625, None),
    ("starapi.cc", "gpt-5.6-luna", 0.116, 0.522, 0.0087, 0.10875, None),
    ("umiluxury.com", "gpt-5.6-sol", 0.4167, 3.3333, 0.0417, 0.5210, None),
    ("umiluxury.com", "gpt-5.6-terra", 0.1667, 1.3333, 0.0167, 0.2083, None),
    ("umiluxury.com", "gpt-6-astra", 0.8333, 4.1667, 0.0833, 1.0417, None),
    ("umiluxury.com", "claude-fable-5", 1.2, 6.0, 0.12, 1.5, None),
    ("umiluxury.com", "claude-fable-5-1", 1.2, 6.0, 0.03, 1.5, None),
    ("umiluxury.com", "claude-opus-5", 0.6, 3.0, 0.06, 0.75, None),
    ("umiluxury.com", "claude-sonnet-5", 0.24, 1.2, 0.024, 0.3, None),
    ("umiluxury.com", "glm-5.3-flash", 0.0267, 0.0933, 0.0077, None, None),
    ("umiluxury.com", "kimi-k3", 0.2, 1.0, 0.02, None, None),
    ("umiluxury.com", "minimax-m3", 0.0467, 0.1667, 0.02, None, None),
    ("newapi.qianqianye.com", "gpt-5.6-luna", 0.3, 1.8, None, None, None),
    ("newapi.qianqianye.com", "gpt-5.6-sol", 1.5, 9.0, None, None, None),
    ("newapi.qianqianye.com", "gpt-5.6-terra", 0.6, 3.6, None, None, None),
    ("newapi.qianqianye.com", "gpt-6-astra", 3.0, 15.0, 0.3, None, None),
    ("newapi.qianqianye.com", "deepseek-v4-flash", 0.45, 1.35, 0.0165, None, None),
    ("newapi.qianqianye.com", "deepseek-v4-flash-vision-exp", 0.45, 1.35, 0.0165, None, None),
    ("newapi.qianqianye.com", "deepseek-v4-pro", 1.35, 4.05, 0.045, None, None),
    ("newapi.qianqianye.com", "grok-4.6", 0.6, 1.8, 0.15, None, None),
    ("newapi.qianqianye.com", "c-gemini-3.8-flash-high", None, None, None, None, 0.018),
    ("newapi.qianqianye.com", "gemini-3.8-flash-high", 0.45, 2.25, None, None, None),
    ("toolcode.cc", "gpt-5.6-sol", 0.99, 5.94, 0.099, None, None),
    ("toolcode.cc", "gpt-5.6-terra", 0.495, 2.97, 0.05, None, None),
    ("toolcode.cc", "gpt-6-astra", 1.98, 9.9, 0.198, None, None),
    ("toolcode.cc", "grok-4.6", 0.32, 0.96, 0.08, None, None),
    ("toolcode.cc", "claude-opus-5", 2.5, 12.5, 0.25, None, None),
    ("aiprc.top", "gpt-5.6-sol", 0.5, 3.0, 0.05, None, None),
    ("aiprc.top", "gpt-5.6-terra", 0.25, 1.5, 0.025, None, None),
    ("aiprc.top", "gpt-6-astra", 1.0, 5.0, 0.1, 1.25, None),
    ("aiprc.top", "claude-fable-5", 1.5, 7.5, 0.15, 1.875, None),
    ("aiprc.top", "claude-fable-5-1", 10.0, 50.0, 0.25, 20.0, None),
    ("aiprc.top", "claude-opus-5", 0.75, 3.75, 0.075, 1.5, None),
    ("aiprc.top", "claude-sonnet-5", 0.45, 2.25, 0.045, 0.6, None),
    ("aiprc.top", "grok-4.6", 0.16, 0.48, 0.04, None, None),
    ("aiprc.top", "gemini-3.8-flash", 0.3, 1.5, 0.03, 0.2, None),
    ("aiprc.top", "gemini-3.8-flash-high", 0.3, 1.5, 0.03, 0.2, None),
    ("sub.potccv.com", "gpt-5.6-luna", 0.024, 0.144, 0.0024, 0.03, None),
    ("sub.potccv.com", "gpt-5.6-terra", 0.24, 1.44, 0.024, 0.30, None),
    # 2026-09-18 补齐：POTCCV 表里 sol/astra 两行此前漏登（用户实付表第 8 组）。
    ("sub.potccv.com", "gpt-5.6-sol", 0.60, 3.60, 0.06, 0.75, None),
    ("sub.potccv.com", "gpt-6-astra", 1.20, 6.00, 0.12, 1.50, None),
    # GLM Coding Plan（Anthropic 接口，约 5 折，用户实付表第 2 组）：与官方直连
    # 同为 open.bigmodel.cn，只能靠 base_url 的路径段区分——两条片段都登记，
    # 命中哪条取决于运行时注册表里写的实际路径（--report 可核对）。
    ("open.bigmodel.cn/api/anthropic", "glm-5.3-flash", 0.4, 1.4, 0.115, None, None),
    ("open.bigmodel.cn/api/coding", "glm-5.3-flash", 0.4, 1.4, 0.115, None, None),
]

# 按 model_id（渠道 id）直接指定价目——host 片段无法区分的渠道走这里。
# 填法：注册表里的 model_id（`/bot model list` 可见）→ 五元组
# (输入, 输出, 缓存读, 缓存创建, 按次价元/请求)；None = 该项不写。
# 例：GLM Coding Plan 与官方直连同 host，只有 model_id 能区分时在此逐条钉价。
MODEL_ID_OVERRIDES: dict[str, tuple[float | None, float | None, float | None, float | None, float | None]] = {}


# axonhub 本地网关（127.0.0.1:8090）条目按「上游模型名」直配价——
# 网关背后是哪家上游由 axonhub 配置决定，此处按用户 2026-09-12 价目表
# 的在用模型落价；Gemini-3.8-Flash(-High) caps 变体与裸名同价。
# 有出入用 /bot model price 或改本表后重跑。
GATEWAY_OVERRIDES: dict[str, tuple[float | None, float | None, float | None, float | None, float | None]] = {
    # 恒星纪元实付（2026-09-17 价目表；axon 网关背后=恒星纪元，.env 注释可证）
    "gemini-3.8-flash": (0.3, 1.5, 0.03, 0.2, None),
    "gemini-3.8-flash-high": (0.3, 1.5, 0.03, 0.2, None),
    "gpt-5.6-sol": (0.5, 3.0, 0.05, None, None),
    "gpt-5.6-terra": (0.25, 1.5, 0.025, None, None),
    "gpt-6-astra": (1.0, 5.0, 0.1, 1.25, None),
    "claude-fable-5": (1.5, 7.5, 0.15, 1.875, None),
    "claude-fable-5-1": (10.0, 50.0, 0.25, 20.0, None),
    "claude-opus-5": (0.75, 3.75, 0.075, 1.5, None),
    "claude-sonnet-5": (0.45, 2.25, 0.045, 0.6, None),
    "grok-4.6": (0.16, 0.48, 0.04, None, None),
    # 浅夜 gemini 专属号池（经网关时按次计费；直连条目走 PRICE_TABLE）
    "c-gemini-3.8-flash-high": (None, None, None, None, 0.018),
    # 2026-09-18 dry-run 报"未覆盖"的两条网关条目补登：
    # deepseek-v4.1-flash 按官方价（用户实付表第 1 组，空闲时段口径）。
    "deepseek-v4.1-flash": (1.0, 4.0, 0.02, None, None),
    # gpt-5.6-luna：网关背后是哪家上游未确认，暂按 StarAPI 口径落价
    # （与 model_router._MODEL_PRICE_FALLBACKS 的报表兜底口径一致）。
    # 若确认网关背后是浅夜（0.3/1.8）或 POTCCV（0.024/0.144/0.0024/0.03），改这一行即可。
    "gpt-5.6-luna": (0.116, 0.522, 0.0087, 0.10875, None),
}


def _resolve_entry(
    model_id: str, model_name: str, base_url: str
) -> tuple[str, tuple[float | None, float | None, float | None, float | None, float | None]] | None:
    """注册表条目 → (命中来源, 五元组)；未命中返回 None。"""
    pinned = MODEL_ID_OVERRIDES.get(model_id)
    if pinned is not None:
        return "model_id 钉价", pinned
    if "127.0.0.1:8090" in base_url or "localhost:8090" in base_url:
        override = GATEWAY_OVERRIDES.get(model_name)
        if override is None and model_name.startswith("gemini-3.8-flash"):
            # caps 等大小写/后缀变体与裸名同价。
            override = GATEWAY_OVERRIDES.get("gemini-3.8-flash")
        if override is not None:
            return "axonhub(gateway)", override
        return None
    matched = [
        row for row in PRICE_TABLE if row[1] == model_name and row[0] in base_url
    ]
    if not matched:
        return None
    host, _name, pin, pout, pc_read, pc_create, per_call = matched[0]
    return host, (pin, pout, pc_read, pc_create, per_call)


def _patch_of(
    prices: tuple[float | None, float | None, float | None, float | None, float | None],
) -> dict[str, object]:
    pin, pout, pc_read, pc_create, per_call = prices
    patch: dict[str, object] = {}
    if pin is not None:
        patch["price_in"] = pin
    if pout is not None:
        patch["price_out"] = pout
    if pc_read is not None:
        patch["price_cache_read"] = pc_read
    if pc_create is not None:
        patch["price_cache_creation"] = pc_create
    if per_call is not None:
        patch["price_per_call"] = per_call
    return patch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run）")
    parser.add_argument(
        "--report",
        action="store_true",
        help="只列出**没有价目命中**的注册表条目（含 base_url/model_id），用于补漏",
    )
    args = parser.parse_args()

    from plugins.bot_unified_runtime.runtime.settings import (
        build_instance_settings_manager,
    )

    settings_dir = str(runtime_path("data/settings"))
    config = type(
        "Cfg", (), {"bot_profile_id": "shorekeeper", "bot_runtime_settings_dir": settings_dir}
    )()
    manager = build_instance_settings_manager(config)
    settings = manager.get("shorekeeper")
    registry = settings.list_model_registry()
    if not registry:
        print("运行时模型注册表为空（data/settings/runtime_settings_shorekeeper.json），无条目可标价。")
        return 1

    updated = 0
    uncovered: list[tuple[str, str, str]] = []
    for model_id, entry in sorted(registry.items()):
        model_name = str(entry.get("model") or model_id).strip().lower()
        base_url = str(entry.get("base_url") or "").strip().lower()
        resolved = _resolve_entry(model_id, model_name, base_url)
        if resolved is None:
            uncovered.append((model_id, model_name, base_url))
            continue
        host, prices = resolved
        patch = _patch_of(prices)
        if not patch:
            uncovered.append((model_id, model_name, base_url))
            continue
        if not args.report:
            print(f"[匹配] {model_id} ({model_name} @ {host}) -> {patch}")
        updated += 1
        if args.apply:
            merged = dict(entry)
            merged.update(patch)
            settings.set_model_entry(model_id, merged)

    if uncovered:
        print()
        print(f"[未覆盖 {len(uncovered)} 条] 下列条目没有任何价目命中（账单会记未计价）：")
        for model_id, model_name, base_url in uncovered:
            print(f"  - {model_id} | model={model_name} | base_url={base_url or '(空)'}")
        print("  补法：①在 PRICE_TABLE 加 (host 片段, 模型名, 入, 出, 缓存读, 缓存创建, 按次)")
        print("        ②host 相同无法区分时，用 MODEL_ID_OVERRIDES 按 model_id 钉价")
        print("        ③单条临时改价用 /bot model price <模型名> input=… output=…")
    applied = "已写入" if args.apply else "dry-run（加 --apply 实际写入）"
    print(f"完成：匹配 {updated} 条，未覆盖 {len(uncovered)} 条，{applied}。")
    print(f"store: {runtime_path('data/settings/runtime_settings_shorekeeper.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
