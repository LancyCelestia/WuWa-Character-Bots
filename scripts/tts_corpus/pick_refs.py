# mypy: ignore-errors
# ruff: noqa  —— 逐字节收编副本：原件代码原文保留，静态门只查不修（修 bug=另波）
# ============================================================================
# T106 收编溯源块（M-61「仓外工具零版本零登记」工具链半）
# 原路径：C:\Software\GPT-SoVITS-V2Pro\tools\pick_refs.py
# 原件 sha256：0ed14796c763e2c0236b5e2a9b1e95cb9c3da2a836a67ccb8a876358128e5e9f
# 收编日期：2026-09-19
# 已知缺陷指针：T24 P2-4（L109-115：失败仅打 !! + continue，退出码恒 0）、T24 P3-4（L135-138：shutil.copy2 保留源 mtime⇒池内时间戳取证失效）；主台账 M-71（report-T29 L121）；正面记录：7/7 选片与宣称源 sha256 逐字节相同=无漂移（T24 L232）
# 性质：版本保护副本，原样收编不修 bug；引擎目录为唯一执行真身，仓内零业务引用，
#       一致性由 tests/test_tts_corpus_tools.py 以 sha256 锚定（原件缺失=SKIP 不假红）。
# 本文件任何手改都会被冒烟门的漂移断言拦下。
# === T106 溯源块结束：以下为引擎原件逐字节内容（勿手改；改动须同步更新 sha256 与冒烟门） ===
"""从 main_honami 合规池挑选参考音频，复制到 refs/ 并改名 shorekeeper_ref_NN.flac。

选片原则：**语气多样性优先**（关切疑问 / 歉意 / 正式承诺 / 长句解释 / 短句疑问 /
转折警告 / 中短陈述），而非单纯取最长的。参考池的价值在于轮换出不同韵律。

只复制、不改音频内容（源文件已落在 3~10s，无需切片）。
源路径从 corpus_durations.csv 读，避免在 shell 里拼中文路径。
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

CSV_IN = Path(r"C:\Software\GPT-SoVITS-V2Pro\refs\corpus_durations.csv")
REFS = Path(r"C:\Software\GPT-SoVITS-V2Pro\refs")

# (目标编号, 源文件名, 语气定位)
PICKS: list[tuple[str, str, str]] = [
    ("02", "main_honami_2_8_2_65_1.flac", "关切疑问"),
    ("03", "main_honami_2_8_2_51_8.flac", "歉意·无奈"),
    ("04", "main_honami_2_8_2_70_19.flac", "正式承诺"),
    ("05", "main_honami_2_8_2_65_12.flac", "长句解释"),
    ("06", "main_honami_2_8_2_39_36.flac", "短句疑问"),
    ("07", "main_honami_2_8_2_65_18.flac", "转折·警告"),
    ("08", "main_honami_2_8_2_73_4.flac", "中短陈述"),
]

rows = {r["file"]: r for r in csv.DictReader(CSV_IN.open(encoding="utf-8-sig")) if r["file"]}

print(f"{'目标':<22}{'时长':>8}{'采样率':>9}{'声道':>6}  {'语气':<12}源文件")
print("-" * 96)
for tag, src, tone in PICKS:
    r = rows.get(src)
    if r is None:
        print(f"!! 源文件不在清单中：{src}")
        continue
    d = float(r["duration_s"])
    if not (3.0 <= d <= 10.0):
        print(f"!! 时长不合规（{d:.2f}s），跳过：{src}")
        continue
    dst = REFS / f"shorekeeper_ref_{tag}.flac"
    shutil.copy2(r["path"], dst)
    print(f"{dst.name:<22}{d:>7.2f}s{r['sr']:>9}{r['ch']:>6}  {tone:<12}{src}")

print()
print("refs/ 现有参考音频：")
for p in sorted(REFS.glob("shorekeeper_ref_*.flac")):
    print(f"  {p.name}  {p.stat().st_size:>8} bytes")
