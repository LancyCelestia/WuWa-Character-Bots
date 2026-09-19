# mypy: ignore-errors
# ruff: noqa  —— 逐字节收编副本：原件代码原文保留，静态门只查不修（修 bug=另波）
# ============================================================================
# T106 收编溯源块（M-61「仓外工具零版本零登记」工具链半）
# 原路径：C:\Software\GPT-SoVITS-V2Pro\tools\make_listening_checklist.py
# 原件 sha256：076c5c64eda4da160f5449dc7d7b43d8a022ff6acd8ba6aa63e7515773b402f8
# 收编日期：2026-09-19
# 已知缺陷指针：T24 P2-2（L90-96：note/结论段为写死散文，生成物 :32「29 条」与同文件生成表「30」自相矛盾；空 CSV 仍写文件并 exit 0）；主台账 M-48（report-T29 L88）
# 性质：版本保护副本，原样收编不修 bug；引擎目录为唯一执行真身，仓内零业务引用，
#       一致性由 tests/test_tts_corpus_tools.py 以 sha256 锚定（原件缺失=SKIP 不假红）。
# 本文件任何手改都会被冒烟门的漂移断言拦下。
# === T106 溯源块结束：以下为引擎原件逐字节内容（勿手改；改动须同步更新 sha256 与冒烟门） ===
"""生成「守岸人参考音频 · 抽样听辨清单」。一次性工具，不属于 ChatBot 源码树。"""

from __future__ import annotations

import collections
import csv
from pathlib import Path

CSV_IN = Path(r"C:\Software\GPT-SoVITS-V2Pro\refs\corpus_durations.csv")
OUT = Path(r"C:\Software\GPT-SoVITS-V2Pro\refs\listening_checklist.md")
CORPUS = Path(r"C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\语料库\守岸人")

rows = [r for r in csv.DictReader(CSV_IN.open(encoding="utf-8-sig")) if r["duration_s"]]


def pick(prefix: str, lo: float, hi: float, n: int) -> list[dict[str, str]]:
    xs = [r for r in rows if r["prefix"] == prefix and lo <= float(r["duration_s"]) <= hi]
    xs.sort(key=lambda r: float(r["duration_s"]))
    if len(xs) <= n:
        return xs
    step = len(xs) / n
    return [xs[int(i * step)] for i in range(n)]


sel: list[tuple[str, list[dict[str, str]], str]] = [
    ("A", pick("heihaian_main", 5, 8, 2), "最大池：204 条合规 / 84 条在 5~8s 甜点区"),
    ("B", pick("main_lahairoi", 3, 10, 1), "14 条合规"),
    ("C", pick("main_linaxita", 3, 10, 1), "21 条合规"),
    ("D", pick("shixifeidu_main", 3, 10, 1), "与 main_honami 同场景 2_8_2 —— 最佳 A/B 对照"),
    ("E", pick("角色包_人声(数字ID)", 3, 10, 1), "68 条中仅 7 条合规，20 条 >15s"),
]

L: list[str] = []
A = L.append
A("# 守岸人参考音频 · 抽样听辨清单")
A("")
A("> **目的**：确认除 `main_honami` 外，哪些前缀也是守岸人本人的声音。")
A("> **听法**：每条听 3 秒即可，重点判断「是不是同一个人」。")
A("> **顺序**：先听 F 建立基准（已确认是守岸人），再依次听 A~E 逐个对照。")
A("")
A("| # | 文件（可直接双击） | 时长 | 所在池 | 待确认 |")
A("|---|---|---|---|---|")
f = CORPUS / "剧情" / "main_honami_2_8_2_43_9.flac"
A(f"| **F** | `{f}` | 8.51s | **基准 · 已确认守岸人** | 先听这条建立基准 |")
for tag, xs, note in sel:
    for r in xs:
        p = CORPUS / r["sub"] / r["file"]
        A(f"| **{tag}** | `{p}` | {float(r['duration_s']):.2f}s | {note} | 和 F 是同一个人吗？ |")
A("")
A("## 怎么回我")
A("")
A("按字母回一句就行：")
A("")
A("```")
A("A: 是守岸人")
A("B: 不是")
A("C: 不是")
A("D: 不是（同场景确实换人了）")
A("E: 听不出来")
A("```")
A("")
A("## 判定的后果")
A("")
A("- **A 是** → 参考池可从 1 条扩到 200+ 条（`heihaian_main` 是最大池），语气覆盖最广。")
A("- **A 不是** → 只用 `main_honami` 的 29 条，从里面挑 5~8 条入池（也完全够用）。")
A("- 拿不准的一律**不用** —— 串音色比池子小严重得多。")
A("")
A("---")
A("")
A("## 附：全库时长实测汇总（490 文件，ffprobe 逐条实测）")
A("")
A("| 前缀 | 总数 | 合规 3~10s | 最短 | 中位 | 最长 | >10s | >15s |")
A("|---|---|---|---|---|---|---|---|")
by: dict[str, list[float]] = collections.defaultdict(list)
for r in rows:
    by[r["prefix"]].append(float(r["duration_s"]))
for k in sorted(by, key=lambda x: -len(by[x])):
    ds = sorted(by[k])
    inr = [x for x in ds if 3.0 <= x <= 10.0]
    A(
        f"| `{k}` | {len(ds)} | **{len(inr)}** | {min(ds):.2f} | {ds[len(ds) // 2]:.2f} "
        f"| {max(ds):.2f} | {len([x for x in ds if x > 10])} | {len([x for x in ds if x > 15])} |"
    )
tot_in = sum(1 for r in rows if 3.0 <= float(r["duration_s"]) <= 10.0)
tot_58 = sum(1 for r in rows if 5.0 <= float(r["duration_s"]) <= 8.0)
A("")
A(f"**全库 3~10s 合规合计 {tot_in} 条；5~8s 甜点区 {tot_58} 条**")
A(f"（后者与 `.env` 注释里的「118」实测吻合）。")
A("")
A("逐文件明细：`C:\\Software\\GPT-SoVITS-V2Pro\\refs\\corpus_durations.csv`")
A("")

OUT.write_text("\n".join(L), encoding="utf-8")
print("已生成 →", OUT)
print()
print("\n".join(L[:28]))
