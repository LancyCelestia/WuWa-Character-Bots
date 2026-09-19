# mypy: ignore-errors
# ruff: noqa  —— 逐字节收编副本：原件代码原文保留，静态门只查不修（修 bug=另波）
# ============================================================================
# T106 收编溯源块（M-61「仓外工具零版本零登记」工具链半）
# 原路径：C:\Software\GPT-SoVITS-V2Pro\tools\asr\transcribe_refs.py
# 原件 sha256：7d2e8962483ed6f7adcc58519d20856612ba878e5d5a6cd709540bed1d944306
# 收编日期：2026-09-19
# 已知缺陷指针：T24 P1-4（L52-63：粘贴块对文本内竖线与【听写失败】+traceback 零防护；实产 9 条含 32kHz ref_01.wav，与体检器 ==8 互斥=反向毒化）；T24 P1-5（L65-79 关联：.env 解析不同构）；主台账 M-61（report-T29 L106）
# 性质：版本保护副本，原样收编不修 bug；引擎目录为唯一执行真身，仓内零业务引用，
#       一致性由 tests/test_tts_corpus_tools.py 以 sha256 锚定（原件缺失=SKIP 不假红）。
# 本文件任何手改都会被冒烟门的漂移断言拦下。
# === T106 溯源块结束：以下为引擎原件逐字节内容（勿手改；改动须同步更新 sha256 与冒烟门） ===
# -*- coding: utf-8 -*-
"""离线听写参考音频，产出可直接填进 BOT_TTS_REF_AUDIOS 的「路径|文本|语种」。

与同目录的 funasr_asr.py 的区别：
  * 不调用 snapshot_download()，不联网核对模型 —— 断网也能跑；
  * 输入既可以是单个音频文件，也可以是整个文件夹；
  * 输出同时给出时长 / 采样率 / 声道数，方便顺手筛 3~10 秒的合规片段；
  * 输出按 UTF-8 写盘，避免控制台代码页把中文变成乱码。

用法：
    runtime\\python.exe -I tools\\asr\\transcribe_refs.py -i refs\\shorekeeper_ref_01.flac
    runtime\\python.exe -I tools\\asr\\transcribe_refs.py -i "D:\\语料\\守岸人" -o out.tsv

依赖的模型已经在 tools/asr/models/ 下，不需要额外下载。
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

# 必须在 import funasr 之前设置，否则 modelscope 会尝试联网。
os.environ.setdefault("MODELSCOPE_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS = PROJECT_ROOT / "tools" / "asr" / "models"

MODEL_ZH = {
    "asr": "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "vad": "speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "punc": "punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
}

AUDIO_EXT = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aac", ".wma"}


def build_model(language: str = "zh"):
    from funasr import AutoModel

    if language != "zh":
        raise SystemExit("目前只内置了中文模型（paraformer-zh）。粤语/英文请改用 tools/asr/funasr_asr.py。")

    paths = {k: MODELS / v for k, v in MODEL_ZH.items()}
    missing = [str(p) for p in paths.values() if not p.is_dir()]
    if missing:
        raise SystemExit("模型目录不存在：\n  " + "\n  ".join(missing))

    return AutoModel(
        model=str(paths["asr"]),
        vad_model=str(paths["vad"]),
        punc_model=str(paths["punc"]),
        disable_update=True,
    )


def collect(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        return sorted(
            p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXT
        )
    raise SystemExit(f"输入路径不存在：{input_path}")


def probe(path: Path):
    """返回 (时长秒, 采样率, 声道数)；读不出来时返回 (-1, -1, -1)。"""
    try:
        import soundfile as sf

        info = sf.info(str(path))
        return info.frames / float(info.samplerate), info.samplerate, info.channels
    except Exception:
        return -1.0, -1, -1


def main() -> int:
    ap = argparse.ArgumentParser(description="离线听写参考音频，输出 路径|文本|语种")
    ap.add_argument("-i", "--input", required=True, help="音频文件，或包含音频的文件夹")
    ap.add_argument("-o", "--output", help="输出 TSV 路径；不填则只打印到屏幕")
    ap.add_argument("-l", "--language", default="zh", choices=["zh"], help="语言（当前仅 zh）")
    ap.add_argument("--no-list", action="store_true", help="不输出 路径|文本|语种 清单行，只出明细表")
    args = ap.parse_args()

    files = collect(Path(args.input))
    if not files:
        raise SystemExit("没有找到任何音频文件。")

    print(f"[transcribe_refs] 待处理 {len(files)} 个文件", flush=True)
    model = build_model(args.language)

    rows: list[tuple[Path, float, int, int, str]] = []
    for idx, path in enumerate(files, 1):
        dur, sr, ch = probe(path)
        try:
            text = model.generate(input=str(path), batch_size_s=300)[0]["text"]
        except Exception:
            text = "【听写失败】" + traceback.format_exc().replace("\n", " ")[:120]
        rows.append((path, dur, sr, ch, text))
        flag = "" if 3.0 <= dur <= 10.0 else "  <- 时长不合规(需3~10s)"
        print(f"[{idx}/{len(files)}] {dur:6.2f}s {sr}Hz {ch}ch{flag}\n    {text}", flush=True)

    lines = ["file\tduration_s\tsr\tch\ttext"]
    for path, dur, sr, ch, text in rows:
        lines.append(f"{path}\t{dur:.2f}\t{sr}\t{ch}\t{text}")

    if not args.no_list:
        lines.append("")
        lines.append("# 可直接粘进 .env 的清单（注意：路径用正斜杠，文本里不能有分号和竖线）")
        for path, dur, sr, ch, text in rows:
            if 3.0 <= dur <= 10.0:
                posix = path.as_posix()
                lines.append(f"{posix}|{text}|zh")

    payload = "\n".join(lines) + "\n"
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        print(f"\n[transcribe_refs] 已写入 {out}", flush=True)
    else:
        print("\n" + payload)

    return 0


if __name__ == "__main__":
    sys.exit(main())
