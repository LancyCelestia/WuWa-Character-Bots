# mypy: ignore-errors
# ruff: noqa  —— 逐字节收编副本：原件代码原文保留，静态门只查不修（修 bug=另波）
# ============================================================================
# T106 收编溯源块（M-61「仓外工具零版本零登记」工具链半）
# 原路径：C:\Software\GPT-SoVITS-V2Pro\tools\scan_durations.py
# 原件 sha256：d1ea0870b054aea4769ad30897c7e1dcd57996d6e25c2ca793980ed273e6bf8b
# 收编日期：2026-09-19
# 已知缺陷指针：T24 P2-3（L98-107：无字节去重⇒291/118 虚增至真实 289/117；PATH ffprobe 版本未钉；只扫子目录；probe 全失败仍 NO_DATA return 0）、T24 P2-4（L109-115：零退出码纪律）；主台账 M-70/M-61（report-T29 L120/L106）
# 性质：版本保护副本，原样收编不修 bug；引擎目录为唯一执行真身，仓内零业务引用，
#       一致性由 tests/test_tts_corpus_tools.py 以 sha256 锚定（原件缺失=SKIP 不假红）。
# 本文件任何手改都会被冒烟门的漂移断言拦下。
# === T106 溯源块结束：以下为引擎原件逐字节内容（勿手改；改动须同步更新 sha256 与冒烟门） ===
"""语料库全量时长扫描（一次性工具，不属于 ChatBot 源码树）。

目的：为 GPT-SoVITS 参考音频扩池提供实测依据。
引擎硬约束（GPT_SoVITS/TTS_infer_pack/TTS.py:809-817）：参考音频转 16kHz 后必须
落在 48000~160000 采样点，即 3~10 秒；TTS.py:1132-1138 无条件触发该校验。
故本脚本以 3.0 <= d <= 10.0 作为唯一合规判据。

用法：python scan_durations.py
输出：refs/corpus_durations.csv（逐文件）+ stdout 汇总

注意：语料库路径含中文，必须由 Python 直接拼路径；经 shell 传参会 Illegal byte sequence。
"""

from __future__ import annotations

import csv
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CORPUS = Path(r"C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\语料库\守岸人")
OUT_CSV = Path(r"C:\Software\GPT-SoVITS-V2Pro\refs\corpus_durations.csv")

MIN_S, MAX_S = 3.0, 10.0
WORKERS = 6


def probe(path: Path) -> tuple[float | None, int | None, int | None]:
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "stream=sample_rate,channels",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return None, None, None
    d = sr = ch = None
    for line in r.stdout.splitlines():
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k == "duration" and d is None:
            try:
                d = float(v)
            except ValueError:
                pass
        elif k == "sample_rate" and sr is None:
            try:
                sr = int(v)
            except ValueError:
                pass
        elif k == "channels" and ch is None:
            try:
                ch = int(v)
            except ValueError:
                pass
    return d, sr, ch


def prefix_of(name: str) -> str:
    if name.startswith("main_honami_"):
        return "main_honami"
    if name.startswith("heihaian_main_"):
        return "heihaian_main"
    if name.startswith("main_linaxita_"):
        return "main_linaxita"
    if name.startswith("main_lahairoi_"):
        return "main_lahairoi"
    if name.startswith("shixifeidu_main_"):
        return "shixifeidu_main"
    if name.startswith("zuoyequnxing_"):
        return "zuoyequnxing"
    return "角色包_人声(数字ID)"


def main() -> int:
    if not CORPUS.is_dir():
        print(f"语料库目录不存在：{CORPUS}", file=sys.stderr)
        return 1

    files: list[tuple[str, Path]] = []
    for sub in sorted(p for p in CORPUS.iterdir() if p.is_dir()):
        for f in sorted(sub.iterdir()):
            if f.is_file():
                files.append((sub.name, f))
    print(f"待扫描 {len(files)} 个文件 …", flush=True)

    rows: list[dict[str, object]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for (sub, f), (d, sr, ch) in zip(files, pool.map(lambda t: probe(t[1]), files)):
            done += 1
            if done % 50 == 0:
                print(f"  … {done}/{len(files)}", flush=True)
            rows.append(
                {
                    "sub": sub,
                    "prefix": prefix_of(f.name),
                    "file": f.name,
                    "path": str(f),
                    "duration_s": "" if d is None else f"{d:.3f}",
                    "sr": "" if sr is None else sr,
                    "ch": "" if ch is None else ch,
                    "in_3_10": "" if d is None else ("Y" if MIN_S <= d <= MAX_S else "N"),
                }
            )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n逐文件 CSV → {OUT_CSV}\n")

    # ---- 按前缀汇总 ----
    by: dict[str, list[dict[str, object]]] = {}
    for r in rows:
        by.setdefault(str(r["prefix"]), []).append(r)

    print(f"{'前缀':<22}{'总数':>6}{'有数据':>8}{'合规3-10s':>10}{'最短':>9}{'中位':>9}{'最长':>9}{'>10s':>7}{'>15s':>7}")
    print("-" * 92)
    for pre in sorted(by, key=lambda k: -len(by[k])):
        rs = by[pre]
        ds = sorted(float(r["duration_s"]) for r in rs if r["duration_s"] != "")
        if not ds:
            print(f"{pre:<22}{len(rs):>6}{'NO_DATA':>8}")
            continue
        inr = [x for x in ds if MIN_S <= x <= MAX_S]
        med = ds[len(ds) // 2]
        print(
            f"{pre:<22}{len(rs):>6}{len(ds):>8}{len(inr):>10}"
            f"{min(ds):>9.2f}{med:>9.2f}{max(ds):>9.2f}"
            f"{len([x for x in ds if x > 10]):>7}{len([x for x in ds if x > 15]):>7}"
        )

    # ---- 切片候选（>10s，需先用 tools/slice_audio.py 切到 3~10s）----
    over = [r for r in rows if r["duration_s"] != "" and float(r["duration_s"]) > MAX_S]
    print(f"\n=== >10s 切片候选（{len(over)} 个，须切片后方可用）===")
    for r in sorted(over, key=lambda x: -float(x["duration_s"]))[:25]:
        print(f"  {float(r['duration_s']):7.2f}s  [{r['prefix']}]  {r['file']}")

    # ---- main_honami 合规池（已验证说话人=守岸人）----
    hon = [r for r in rows if r["prefix"] == "main_honami" and r["in_3_10"] == "Y"]
    print(f"\n=== main_honami 合规池（{len(hon)} 条，说话人已由场景号交叉验证）===")
    for r in sorted(hon, key=lambda x: float(x["duration_s"])):
        print(f"  {float(r['duration_s']):7.2f}s  {r['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
