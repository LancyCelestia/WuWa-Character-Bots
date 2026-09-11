"""Rebuild the model registry: same-family consolidation + priority re-ordering.

Rules applied (user spec):
  * c-gemini-3.8-flash 并入 gemini-3.8-flash 组，且排在正体之后
  * gemini-3.7-flash 同理
  * aiprc 与浅夜同级；同族内次序 ToolCode > umi api > hcnsec
  * axonhub 作为统一网关排在最前（默认 gemini-3.8-flash），DeepSeek 兜底在最后

「归并」在注册表里的可行实现 = **把同族渠道排成连续优先级块**（条目 id 与
上游 model 名保持可路由原值——`c-gemini-3.8-flash-high` 是上游真实模型名，
改名会被上游拒绝；`/bot model set <模型名>` 的同名聚合依赖 model 字段）。
快照对照：review/original-model-registry.json

Usage: python scripts/consolidate_model_registry.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

SETTINGS = pathlib.Path(
    r"C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\data\settings"
    r"\runtime_settings_shorekeeper.json"
)
SNAPSHOT = pathlib.Path(__file__).resolve().parent.parent / "review" / "original-model-registry.json"
BACKUP_DIR = pathlib.Path(
    r"C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\backups"
)

# 同族归并 + 组内次序。key 是"逻辑模型"，value 是按次序排列的条目 id。
# 组内规则：浅夜/aiprc 同级在前 → StarAPI（原相对位次）→ ToolCode → umi → hcn。
FAMILIES: dict[str, list[str]] = {
    "gemini-3.8-flash": [
        # 浅夜正体 → 浅夜 c-（并入本组，且排在正体之后）→ aiprc（与浅夜同级）
        "qian-night-gemini",
        "qian-gemini-38",
        "qian-night-c-gemini",
        "aiprc-gemini",
        "starapi-gemini",
        "toolcode-gemini",
    ],
    "gpt-5.6-terra": ["qian-terra", "aiprc-terra", "starapi-terra", "toolcode-terra", "umi-gpt-terra"],
    "gpt-5.6-sol": ["aiprc-sol", "starapi-sol", "toolcode-sol", "umi-gpt-sol"],
    "gpt-6-astra": ["aiprc-astra", "qian-astra", "starapi-astra", "toolcode-astra", "umi-astra"],
    "gpt-5.6-luna": ["qian-luna"],
    "grok-4.6": ["qian-night-grok", "aiprc-grok", "toolcode-grok", "umi-desk-grok"],
    "deepseek-v4-flash": ["qian-ds-flash", "ds-official-flash", "umi-desk-deepseek-flash"],
    "deepseek-v4-flash-vision-exp": ["ds-official-flash-vision"],
    "deepseek-v4-pro": ["qian-ds-pro", "ds-official-pro", "umi-desk-deepseek-pro"],
    "glm-5.3-flash": ["zhipu-glm-flash", "umi-glm-flash"],
    "glm-5.3": ["zhipu-glm"],
    "kimi-k3": ["hcn-kimi", "umi-kimi"],
    "MiniMax-M3": ["hcn-minimax", "umi-minimax"],
    "DeepSeek-V4-Pro": ["hcn-pro"],
    "DeepSeek-V4-Flash": ["hcn-flash"],
    "claude-fable-5": ["umi-claude-fable-5"],
    "claude-fable-5-1": ["umi-claude-fable-51"],
    "claude-opus-5": ["umi-claude-opus-5"],
    "claude-sonnet-5": ["umi-claude-sonnet-5"],
}

# 族间块次序（每族一个连续优先级块，块内间距 1）
FAMILY_ORDER = list(FAMILIES.keys())

BLOCK_START = 100
BLOCK_STRIDE = 20
AXONHUB_MAX_PRIORITY = 37  # axonhub 条目当前占 1..37（见 configure_axonhub_registry）
DEEPSEEK_FALLBACK_PRIORITY = 900


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    original = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    registry = settings.get("model_registry") or {}

    # 1) 保留 axonhub 条目（source=axonhub），重排其优先级为 1..N 连续
    axon_entries = {
        key: entry
        for key, entry in registry.items()
        if str(entry.get("source", "")) == "axonhub"
    }
    for index, key in enumerate(
        sorted(axon_entries, key=lambda k: axon_entries[k].get("priority") or 999), start=1
    ):
        axon_entries[key]["priority"] = index

    # 2) 重建原渠道条目（带归并后的优先级）
    rebuilt: dict[str, dict] = {}
    unmapped: list[str] = []
    for block, family in enumerate(FAMILY_ORDER):
        base = BLOCK_START + block * BLOCK_STRIDE
        for offset, entry_id in enumerate(FAMILIES[family]):
            source = original.get(entry_id)
            if source is None:
                unmapped.append(entry_id)
                continue
            entry = dict(source)
            entry["priority"] = base + offset
            entry["family"] = family
            entry["source"] = "env"
            rebuilt[entry_id] = entry

    # 3) DeepSeek 直连兜底永远最后
    for entry in rebuilt.values():
        if entry.get("model") == "deepseek-v4-flash" and entry.get("group", "").startswith("deepseek"):
            entry["priority"] = DEEPSEEK_FALLBACK_PRIORITY
    if "ds-official-flash" in rebuilt:
        rebuilt["ds-official-flash"]["priority"] = DEEPSEEK_FALLBACK_PRIORITY

    registry = {**axon_entries, **rebuilt}
    settings["model_registry"] = registry

    print(f"axonhub entries : {len(axon_entries)} (priority 1..{len(axon_entries)})")
    print(f"rebuilt channels: {len(rebuilt)} (base {BLOCK_START}, stride {BLOCK_STRIDE})")
    print(f"total registry  : {len(registry)}")
    if unmapped:
        print("UNMAPPED (snapshot missing these ids):", unmapped)
    print()
    print("final order (top 20):")
    for key, entry in sorted(registry.items(), key=lambda kv: kv[1].get("priority") or 0)[:20]:
        print(
            f"  {entry.get('priority'):>4}  {key:<28} model={entry.get('model')!s:<30}"
            f" group={entry.get('group')}"
        )
    print("  ...")
    print("final order (tail 6):")
    for key, entry in sorted(registry.items(), key=lambda kv: kv[1].get("priority") or 0)[-6:]:
        print(f"  {entry.get('priority'):>4}  {key:<28} model={entry.get('model')!s}")

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to write.")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(SETTINGS, BACKUP_DIR / f"runtime_settings_shorekeeper.json.bak-{stamp}")
    SETTINGS.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nwritten. backup stamp {stamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
