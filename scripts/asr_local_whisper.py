"""本地 faster-whisper 转写：给 BOT_ASR_LOCAL_COMMAND 用的独立入口。

用法（最后一个参数是音频文件路径）：
    python scripts/asr_local_whisper.py --model small --download-root <模型目录> audio.wav

它故意不 import bot 的任何模块：转写器可以装在另一个 Python 环境里，
不把 torch/ctranslate2/模型权重塞进 bot 的 venv。stdout 只输出一行 JSON。
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("--model", default="small")
    parser.add_argument("--download-root", default="")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--language", default="")
    args = parser.parse_args(argv)
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            json.dumps({"error": "faster_whisper is not installed in this Python"}),
            file=sys.stderr,
        )
        return 2
    model = WhisperModel(
        args.model,
        device=args.device,
        compute_type=args.compute_type,
        download_root=args.download_root or None,
    )
    segments, info = model.transcribe(
        args.audio,
        language=args.language or None,
        beam_size=5,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    print(
        json.dumps(
            {
                "text": text,
                "language": getattr(info, "language", ""),
                "language_probability": round(
                    float(getattr(info, "language_probability", 0.0) or 0.0), 4
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
