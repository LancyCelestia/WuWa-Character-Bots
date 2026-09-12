"""模型价目批量导入脚本：把渠道价目表写入运行时模型注册表。

数据来源=用户提供的渠道价目表（2026-09-12，元 / 1M tokens；price_per_call
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
    ("starapi.cc", "gemini-3.8-flash", 1.35, 6.75, 0.135, 0.075, None),
    ("starapi.cc", "gpt-5.6-terra", 2.09, 12.53, 0.209, 2.61, None),
    ("starapi.cc", "gpt-5.6-luna", 0.84, 3.76, 0.063, 0.78, None),
    ("umiluxury.com", "gpt-5.6-sol", 3.0, 24.0, 0.3, 3.75, None),
    ("umiluxury.com", "gpt-5.6-terra", 1.2, 9.6, 0.12, 1.5, None),
    ("umiluxury.com", "gpt-6-astra", 6.0, 30.0, 0.6, 7.5, None),
    ("umiluxury.com", "claude-fable-5", 8.64, 43.2, 0.864, 10.8, None),
    ("umiluxury.com", "claude-fable-5-1", 8.64, 43.2, 0.216, 10.8, None),
    ("umiluxury.com", "claude-opus-5", 4.32, 21.6, 0.432, 5.4, None),
    ("umiluxury.com", "claude-sonnet-5", 1.73, 8.64, 0.173, 2.16, None),
    ("umiluxury.com", "glm-5.3-flash", 0.19, 0.67, 0.055, None, None),
    ("umiluxury.com", "kimi-k3", 1.44, 7.2, 0.144, None, None),
    ("umiluxury.com", "minimax-m3", 0.34, 1.2, 0.144, None, None),
    ("newapi.qianqianye.com", "gpt-5.6-luna", 3, 18, None, None, None),
    ("newapi.qianqianye.com", "gpt-5.6-sol", 15, 90, None, None, None),
    ("newapi.qianqianye.com", "gpt-5.6-terra", 6, 36, None, None, None),
    ("newapi.qianqianye.com", "gpt-6-astra", 30, 150, 3, None, None),
    ("newapi.qianqianye.com", "deepseek-v4-flash", 4.5, 13.5, 0.165, None, None),
    ("newapi.qianqianye.com", "deepseek-v4-flash-vision-exp", 4.5, 13.5, 0.165, None, None),
    ("newapi.qianqianye.com", "deepseek-v4-pro", 13.5, 40.5, 0.45, None, None),
    ("newapi.qianqianye.com", "grok-4.6", 6, 18, 1.5, None, None),
    ("newapi.qianqianye.com", "c-gemini-3.8-flash-high", None, None, None, None, 0.18),
    ("newapi.qianqianye.com", "gemini-3.8-flash-high", 4.5, 22.5, None, None, None),
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
]


# axonhub 本地网关（127.0.0.1:8090）条目按「上游模型名」直配价——
# 网关背后是哪家上游由 axonhub 配置决定，此处按用户 2026-09-12 价目表
# 的在用模型落价；Gemini-3.8-Flash(-High) caps 变体与裸名同价。
# 有出入用 /bot model price 或改本表后重跑。
GATEWAY_OVERRIDES: dict[str, tuple[float | None, float | None, float | None, float | None, float | None]] = {
    "gemini-3.8-flash": (0.3, 1.5, 0.03, 0.2, None),          # 恒星纪元（全表唯一裸 -flash 报价）
    "gemini-3.8-flash-high": (4.5, 22.5, None, None, None),   # 浅夜の梦 促销号池
    "c-gemini-3.8-flash-high": (None, None, None, None, 0.18),  # 浅夜 按次计费
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run）")
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
    for model_id, entry in sorted(registry.items()):
        model_name = str(entry.get("model") or model_id).strip().lower()
        base_url = str(entry.get("base_url") or "").strip().lower()
        patch: dict[str, object] = {}
        host = ""
        if "127.0.0.1:8090" in base_url or "localhost:8090" in base_url:
            override = GATEWAY_OVERRIDES.get(model_name)
            if override is None and model_name.startswith("gemini-3.8-flash"):
                # caps 等大小写/后缀变体与裸名同价。
                override = GATEWAY_OVERRIDES.get("gemini-3.8-flash")
            if override is not None:
                pin, pout, pc_read, pc_create, per_call = override
                host = "axonhub(gateway)"
            else:
                continue
        else:
            matched = [
                row
                for row in PRICE_TABLE
                if row[1] == model_name and row[0] in base_url
            ]
            if not matched:
                continue
            host, _name, pin, pout, pc_read, pc_create, per_call = matched[0]
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
        print(f"[匹配] {model_id} ({model_name} @ {host}) -> {patch}")
        updated += 1
        if args.apply:
            merged = dict(entry)
            merged.update(patch)
            settings.set_model_entry(model_id, merged)
    applied = "已写入" if args.apply else "dry-run（加 --apply 实际写入）"
    print(f"完成：匹配 {updated} 条，{applied}。")
    print(f"store: {runtime_path('data/settings/runtime_settings_shorekeeper.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
