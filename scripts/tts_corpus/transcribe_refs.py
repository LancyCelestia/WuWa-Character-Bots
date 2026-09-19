# mypy: ignore-errors
# ruff: noqa  —— 收编副本·T148 修复分叉版：原件代码面保留，防毒化层为本仓新增（静态门对既有原件面只查不修）
# ============================================================================
# T106 收编溯源块（M-61「仓外工具零版本零登记」工具链半）
# 原路径：C:\Software\GPT-SoVITS-V2Pro\tools\asr\transcribe_refs.py
# 原件 sha256：7d2e8962483ed6f7adcc58519d20856612ba878e5d5a6cd709540bed1d944306
# 收编日期：2026-09-19
# 已知缺陷指针：T24 P1-4（L52-63：粘贴块对文本内竖线与【听写失败】+traceback 零防护；实产 9 条含 32kHz ref_01.wav，与体检器 ==8 互斥=反向毒化）；T24 P1-5（L65-79 关联：.env 解析不同构）；主台账 M-61（report-T29 L106）
# 性质：版本保护副本；引擎目录为唯一执行真身，仓内零业务引用。
# === T148 修复分叉登记（2026-09-20，T148 席） ===
# 本副本已修复 T24 P1-4 反向毒化缺陷，防毒化三件：
#   ① 文本含竖线/分号 → 拒绝出块（选「拒绝」不选「转义」：消费端 parse_ref_audios 对
#      BOT_TTS_REF_AUDIOS 裸 split("|")、无转义/解义语义，「\|」会被拆成独立字段或把
#      反斜杠原样带进提示词，转义结构性不成立；依据详见 reject_reason docstring）；
#   ② 【听写失败】失败段拦截出粘贴块、改记「排除台账」注释行，有拦截时退出码 1；
#   ③ traceback 残迹过滤（多行原形与压平形态均拦，失败文本绝不进粘贴块）。
# 另加守恒断言：放行+排除==输入清单条数、明细表行数==输入数（显式 raise，防 python -O 剥 assert，T24 P3-1）。
# 自本笔起本副本尾部不再与引擎原件逐字节一致：引擎原件仍带上述缺陷（原件 sha256 仍=上方锚值，
# 引擎目录禁碰）；分叉后尾部新锚由 tests/test_tts_corpus_tools.py 的 FORKED 注册表钉住（漂移照拦）。
# 引擎侧预案四执行时：以本 repo 副本为准，或回移植本修复（披露见 report-T148.md）。
# === T106 溯源块结束：以下为「原件内容+T148 防毒化层」修复分叉版（改动须同步更新 FORKED 锚与冒烟门） ===
# -*- coding: utf-8 -*-
"""离线听写参考音频，产出可直接填进 BOT_TTS_REF_AUDIOS 的「路径|文本|语种」。

与引擎原件的分叉（T148，2026-09-20）：本副本已修复反向毒化缺陷——
  * 粘贴块只放行干净文本：含竖线/分号的文本一律拒绝出块（消费端裸 split("|")，无转义语义）；
  * 【听写失败】失败段与 traceback 残迹绝不进粘贴块，改记「排除台账」注释行；
  * 有拦截发生时退出码 1（流水线据此判毒），全干净时退出码 0；
  * 守恒断言：放行+排除==输入清单条数、明细表行数==输入数（显式 raise，不裸 assert）。
引擎原件（C:\\Software\\GPT-SoVITS-V2Pro\\tools\\asr\\transcribe_refs.py）仍带缺陷；
执行引擎侧预案四时以本副本为准或回移植本修复。

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

# ---------------------------------------------------------------------------
# T148 防毒化层（repo 副本修复分叉；引擎原件无此层）
# ---------------------------------------------------------------------------

FAILED_MARKER = "【听写失败】"
# traceback 残迹特征：format_exc 产物首行恒为 "Traceback (most recent call last):"，
# 多行原形的续行以两空格 + 'File "' 开头（压平形态不含后者，首行标记已覆盖）。
TRACEBACK_MARKERS = (
    "Traceback (most recent call last):",
    '\n  File "',
)


def is_failed_text(text: str) -> bool:
    """ASR 失败占位/traceback 残迹判定：命中者绝不进粘贴块。"""
    if text.startswith(FAILED_MARKER):
        return True
    return any(marker in text for marker in TRACEBACK_MARKERS)


def reject_reason(text: str) -> str | None:
    """粘贴块准入判定：返回拒绝原因；None=放行。

    竖线选「拒绝」不选「转义」的依据：消费端 parse_ref_audios（引擎 tts.py，T24 P1-4
    取证坐标 tts.py:164-169）对 BOT_TTS_REF_AUDIOS 裸 split("|")，没有任何转义/解义
    语义——「\\|」要么被拆成独立字段（字段错位），要么把反斜杠原样带进提示词文本。
    本工具单方面引入转义方案结构性不成立，只能拒绝并显式记账。分号同拒（原件注释
    「文本里不能有分号和竖线」的警告面，本层首次把它落成机器判据）。
    """
    if is_failed_text(text):
        return "ASR 失败占位（含 traceback 残迹）"
    if "|" in text:
        return "文本含竖线（清单字段分隔符，消费端裸 split 无转义语义）"
    if ";" in text:
        return "文本含分号（原件注释警告面）"
    return None


def classify_rows(
    rows: list[tuple[Path, float, int, int, str]],
) -> tuple[list[tuple[Path, str]], list[tuple[Path, str, str]]]:
    """把明细行分成（放行进粘贴块, 拦截出块）两桶，拦截条目附原因。

    守恒：两桶计数之和 == len(rows)（每个输入恰落一桶，无静默增删）；
    用显式 raise 不裸 assert——python -O 会剥 assert（T24 P3-1）。
    """
    ok: list[tuple[Path, str]] = []
    excluded: list[tuple[Path, str, str]] = []
    for path, _dur, _sr, _ch, text in rows:
        reason = reject_reason(text)
        if reason is None:
            ok.append((path, text))
        else:
            excluded.append((path, text, reason))
    if len(ok) + len(excluded) != len(rows):
        raise RuntimeError(
            f"粘贴块守恒破坏：放行 {len(ok)} + 拦截 {len(excluded)} != 输入 {len(rows)}"
        )
    return ok, excluded


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
            text = FAILED_MARKER + traceback.format_exc().replace("\n", " ")[:120]
        rows.append((path, dur, sr, ch, text))
        flag = "" if 3.0 <= dur <= 10.0 else "  <- 时长不合规(需3~10s)"
        print(f"[{idx}/{len(files)}] {dur:6.2f}s {sr}Hz {ch}ch{flag}\n    {text}", flush=True)

    lines = ["file\tduration_s\tsr\tch\ttext"]
    for path, dur, sr, ch, text in rows:
        lines.append(f"{path}\t{dur:.2f}\t{sr}\t{ch}\t{text}")

    # 明细表守恒：输出行数 == 输入清单条数（每输入恰一行，显式 raise 不裸 assert）
    detail_rows = len(lines) - 1
    if detail_rows != len(rows):
        raise RuntimeError(f"明细表守恒破坏：{detail_rows} 行 != 输入 {len(rows)} 个")

    exit_code = 0
    if not args.no_list:
        ok, excluded = classify_rows(rows)
        lines.append("")
        lines.append(
            "# 可直接粘进 .env 的清单（注意：路径用正斜杠；含竖线/分号/听写失败的文本"
            "一律不进本块，拦截记录见下方排除台账）"
        )
        for path, text in ok:
            lines.append(f"{path.as_posix()}|{text}|zh")
        if excluded:
            lines.append("")
            lines.append("# [T148 排除台账] 以下条目已拦截出粘贴块（防毒化），不得手工恢复：")
            for path, text, reason in excluded:
                lines.append(f"# [已拦截] {path.name}：{reason}")
            exit_code = 1  # 有拦截=有毒化风险面，退出码非零供流水线判毒
        print(
            f"\n[transcribe_refs] 粘贴块 {len(ok)} 条 / 拦截 {len(excluded)} 条 / "
            f"输入 {len(rows)} 个（放行+拦截==输入：{len(ok) + len(excluded) == len(rows)}）",
            flush=True,
        )

    payload = "\n".join(lines) + "\n"
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        print(f"\n[transcribe_refs] 已写入 {out}", flush=True)
    else:
        print("\n" + payload)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
