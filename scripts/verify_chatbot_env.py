"""verify_chatbot_env — .env 配置快查（全 Config 可装载性 + TTS 段深查）.

定位（分工声明）：**手动快查工具**——改完 .env 后秒级离线核对，不是重启门。
重启前置一键预检（10 项，含第 10 项引擎侧音色守望 tts_voice）=
``scripts/pre_restart_check.py``；两者零重叠：本工具守 **bot 侧配置面**
（.env → 生产 pydantic Config 装载语义 + TTS 段深查），pre_restart_check
第 10 项守 **引擎面**（tts_infer.yaml / 权重 / sha256 身份对表）。

范围声明（不假绿）：音频时长/采样率/声道（T24 ①②）= 引擎侧产物体检闸与
用户裁点（ffprobe/soundfile），端口存活（⑤）= 运维探针 / pre_restart_check
napcat 项同型探测，均不在本工具范围——本工具只对「配置写没写对」负责。

治 T24 五面假安心（对照表全文 = .superpowers/sdd/2026-09-19-unify-audit/
report-T87.md）：
  F1 ROOT 错指  → 仓库根由本文件位置自证（parents[1]），解析后立即核
                  plugins/bot_unified_runtime/config.py 实存，指错=大声 FAIL
                  而非 ImportError 崩；--project-root 只改 .env 读取根。
  F2 静默缺省  → .env/.env.prod 全缺=FAIL（拒绝静默回退全默认）；装载指纹
                  （哪些文件参与、BOT_TTS_ 键数）显式回显。
  F3 故障面    → 判据走生产真身：Config.model_validate(translate_env_keys(
                  JSON解码)) 继承全部 Field 域闸/枚举/SSRF 校验器（⑦/⑥c）；
                  自补 pydantic 结构性盲区：BOT_TTS_ 未知键+difflib 纠错（⑥b）、
                  ref 段数>3 竖线截断（③）、逐条语种对 TEXT_LANG_VALUES（④）、
                  文件实存、相对路径无基准目录、空路径静默跳过、
                  池空但 ENABLED=true（⑧，不钉具体条数）。
  F4 空断言    → 零「期望值=类缺省」断言：判定=域闸真身与一致性，值只回显
                  供人核，不作判据。
  F5 裸 assert → 全文零 assert（-O 下不消失）；FAIL → 退出码 1。

用法：
  venv python scripts/verify_chatbot_env.py                # 人读表
  venv python scripts/verify_chatbot_env.py --json         # 结构化输出
  venv python scripts/verify_chatbot_env.py --project-root <path>

退出码：0 = 无 FAIL（PASS/SKIP 均放行）；1 = 有 FAIL。
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CODE_ROOT = Path(__file__).resolve().parents[1]

PASS = "PASS"
SKIP = "SKIP"
FAIL = "FAIL"

# 与 scripts/pre_restart_check.py TTS_ENABLED_TRUTHY 同口径
TTS_ENABLED_TRUTHY = {"true", "1", "yes", "on"}
_MAX_INPUT_ECHO = 60


@dataclass(frozen=True)
class Finding:
    """单项结论：PASS/SKIP/FAIL + 一句话."""

    id: str
    name: str
    status: str
    message: str


# ---------------------------------------------------------------------------
# 装载器（M-68 收口：语义移交唯一入口 scripts/load_runtime_config.py——
# 生产同构 python-dotenv 值层 + nonebot extras JSON 解码层；dotenv 为
# nonebot 既有依赖，零新依赖。位置自证（F1）不变：被搬出仓库时下面
# best-effort 导入失败退化为 None，主流程 code_root 检查会大声 FAIL，
# 且该场景下 load_env/config 路径不可达（root_check FAIL 即短路）。
# ---------------------------------------------------------------------------

try:
    from scripts.load_runtime_config import (
        json_decode_env_values,
        load_runtime_env_values,
    )
except ImportError:  # 直跑/子进程态 sys.path[0]=scripts/：补仓库根后重试
    if str(CODE_ROOT) not in sys.path:
        sys.path.insert(0, str(CODE_ROOT))
    try:
        from scripts.load_runtime_config import (
            json_decode_env_values,
            load_runtime_env_values,
        )
    except ImportError:  # pragma: no cover - F1 被搬出仓库（scripts 包不可达）
        load_runtime_env_values = None  # type: ignore[assignment,misc]
        json_decode_env_values = None  # type: ignore[assignment,misc]


def _decode_env_values(values: dict[str, str]) -> dict[str, Any]:
    """JSON 解码层（唯一入口委托；None 态仅存在于 F1 残废场景，主流程不可达）."""
    if json_decode_env_values is None:  # pragma: no cover
        return dict(values)
    return json_decode_env_values(values)


def load_env(env_root: Path) -> tuple[dict[str, str], list[str]]:
    """读 env_root 下 .env / .env.prod（后者覆盖），os.environ 优先.

    M-68 收口：解析语义移交唯一入口 scripts/load_runtime_config.py
    （与生产 bot.py:255 同构），本函数只适配既有返回契约
    （原始字符串值 + 参与文件名清单，供装载指纹回显）。
    """
    if load_runtime_env_values is None:  # pragma: no cover - F1 残废态
        return {}, []
    loaded = load_runtime_env_values((".env", ".env.prod"), root=env_root)
    return dict(loaded.values), [path.name for path in loaded.files]


# ---------------------------------------------------------------------------
# 检查项
# ---------------------------------------------------------------------------

def check_code_root() -> Finding:
    """F1：仓库根由文件位置自证，指错大声 FAIL（治原件搬家即崩）."""
    marker = CODE_ROOT / "plugins" / "bot_unified_runtime" / "config.py"
    if marker.is_file():
        return Finding("code_root", "仓库根自证", PASS, f"仓库根={CODE_ROOT}")
    return Finding(
        "code_root",
        "仓库根自证",
        FAIL,
        f"仓库根解析失败：{CODE_ROOT} 下没有 plugins/bot_unified_runtime/config.py"
        "——本工具被搬出 <仓库根>/scripts/ 后 parents[1] 指向了错误目录"
        "（T24 P1-1 原件同款病）；放回 scripts/ 或用 --project-root 改 .env 根。",
    )


def check_env_source(env_root: Path, env: dict[str, str], found: list[str]) -> Finding:
    """F2：装载指纹显式化；全缺=FAIL 不静默回退."""
    tts_key_count = sum(1 for k in env if k.strip().upper().startswith("BOT_TTS_"))
    if not found:
        return Finding(
            "env_source",
            ".env 装载指纹",
            FAIL,
            f"在 {env_root} 未找到 .env / .env.prod——拒绝静默回退全默认配置"
            "（T24 P1-3：读不到文件也绿的体检是假安心）。",
        )
    return Finding(
        "env_source",
        ".env 装载指纹",
        PASS,
        f"已装载 {' + '.join(found)}（后者覆盖），BOT_TTS_ 键 x{tts_key_count}",
    )


def check_config(env: dict[str, str]) -> tuple[Finding, Any, list[str]]:
    """F3/F4：整体走生产 Config 真身；域闸/枚举/SSRF 全继承，零复制零漂移."""
    from pydantic import ValidationError

    from plugins.bot_unified_runtime.config import Config, translate_env_keys

    known_tts = sorted(f.upper() for f in Config.model_fields if f.startswith("bot_tts_"))
    try:
        cfg = Config.model_validate(translate_env_keys(_decode_env_values(dict(env))))
    except ValidationError as exc:
        errors = exc.errors()
        shown = []
        for err in errors[:5]:
            loc = ".".join(str(part) for part in err.get("loc", ())) or "(顶层)"
            echo = repr(err.get("input"))[:_MAX_INPUT_ECHO]
            shown.append(f"{loc}: {err.get('msg', '')}（收到 {echo}）")
        more = f"（另 x{len(errors) - 5} 条略）" if len(errors) > 5 else ""
        finding = Finding(
            "config_load",
            "Config 整体装载",
            FAIL,
            f"Config 装载失败 x{len(errors)}（bot 启动同样会崩）：{'; '.join(shown)}{more}",
        )
        return finding, None, known_tts
    tts = cfg.bot_tts_ref_audios
    finding = Finding(
        "config_load",
        "Config 整体装载",
        PASS,
        "生产 pydantic 域闸/枚举/SSRF 全部通过；TTS 关键值回显（供人核，非判据）："
        f"enabled={cfg.bot_tts_enabled} 池={len(tts)}条 "
        f"probability={cfg.bot_tts_auto_reply_probability} "
        f"always={cfg.bot_tts_auto_reply_always} api_url={cfg.bot_tts_api_url}",
    )
    return finding, cfg, known_tts


def check_tts_gate(env: dict[str, str]) -> Finding:
    enabled = env.get("BOT_TTS_ENABLED", "").strip()
    if enabled.lower() in TTS_ENABLED_TRUTHY:
        return Finding("tts_gate", "TTS 启用门", PASS, "BOT_TTS_ENABLED=true，执行 TTS 段深查")
    shown = enabled or "未配置"
    return Finding(
        "tts_gate",
        "TTS 启用门",
        SKIP,
        f"BOT_TTS_ENABLED 未启用（当前值：{shown}）——TTS 配置深查不适用"
        "（Config 整体装载仍已校验）",
    )


def check_tts_keys(env: dict[str, str], known_tts: list[str]) -> Finding:
    """⑥b：pydantic 无 extra=forbid，错名键被静默忽略——这里抓出来."""
    env_tts = sorted({k.strip().upper() for k in env if k.strip().upper().startswith("BOT_TTS_")})
    unknown = [k for k in env_tts if k not in known_tts]
    if not unknown:
        return Finding("tts_keys", "TTS 键名核对", PASS, f"{len(env_tts)} 个 BOT_TTS_ 键全部在册")
    parts = []
    for key in unknown:
        close = difflib.get_close_matches(key, known_tts, n=1, cutoff=0.6)
        parts.append(f"{key}（是不是想写 {close[0]}？）" if close else key)
    return Finding(
        "tts_keys",
        "TTS 键名核对",
        FAIL,
        f"未知 BOT_TTS_ 键 x{len(unknown)}——pydantic 会静默忽略（能力带错配置跑，零信号）："
        + "；".join(parts)
        + "。键目录见 docs/config-catalog-full.md。",
    )


def check_tts_refs(cfg: Any) -> Finding:
    """③④⑥a⑧ + 文件实存/基准目录：生产 parse_ref_audios 的静默面逐条点破."""
    from plugins.bot_unified_runtime.domains.media.tts_presets import TEXT_LANG_VALUES

    problems: list[str] = []
    refs = [str(item).strip() for item in (cfg.bot_tts_ref_audios or [])]
    base = str(cfg.bot_tts_gptsovits_dir or "").strip()
    usable = 0
    for item in refs:
        if not item:
            continue
        segments = item.split("|")
        raw_path = segments[0].strip()
        if not raw_path:
            problems.append(
                f"空路径条目（生产装载器会静默跳过，池悄悄缩水）：{item[:_MAX_INPUT_ECHO]!r}"
            )
            continue
        if len(segments) > 3:
            problems.append(
                f"段数 {len(segments)} > 3——文本含竖线会被生产解析截断"
                f"（第 3 段后静默丢弃）：{item[:_MAX_INPUT_ECHO]!r}"
            )
        lang = segments[2].strip() if len(segments) > 2 and segments[2].strip() else "zh"
        if lang.casefold() not in TEXT_LANG_VALUES:
            problems.append(
                f"语种 {lang!r} 不在引擎合法域 {sorted(TEXT_LANG_VALUES)}——引擎 400 该条"
            )
        path = Path(raw_path)
        if path.is_absolute():
            resolved = path
        elif base:
            resolved = Path(base) / path
        else:
            problems.append(
                f"相对路径 {raw_path!r} 但 BOT_TTS_GPTSOVITS_DIR 未配置——"
                "生产会挂到进程 CWD（不确定解析）"
            )
            continue
        if not resolved.is_file():
            problems.append(f"参考音频文件不存在：{resolved}")
        else:
            usable += 1
    if base and not Path(base).is_dir():
        problems.append(f"BOT_TTS_GPTSOVITS_DIR 目录不存在：{base}（错名/搬盘候选）")
    if usable == 0:
        problems.append(
            f"可用参考池为空（{len(refs)} 条全不可用）但 ENABLED=true——"
            "语音功能整链静默无声（T24 ⑧）"
        )
    if problems:
        return Finding(
            "tts_refs",
            "TTS 参考池深查",
            FAIL,
            f"x{len(problems)}：" + "；".join(problems[:5])
            + (f"（另 x{len(problems) - 5} 条略）" if len(problems) > 5 else ""),
        )
    return Finding(
        "tts_refs",
        "TTS 参考池深查",
        PASS,
        f"参考池 x{len(refs)} 条：段数/语种/文件实存/基准目录全部通过（不钉具体条数）",
    )


# ---------------------------------------------------------------------------
# 汇总与输出
# ---------------------------------------------------------------------------

def _render_table(findings: list[Finding], project_root: Path) -> str:
    lines = [f"verify_chatbot_env — .env 配置快查（根={project_root}）", "-" * 72]
    for f in findings:
        lines.append(f"{f.id:<12} {f.status:<5} {f.message}")
    n_fail = sum(1 for f in findings if f.status == FAIL)
    n_skip = sum(1 for f in findings if f.status == SKIP)
    n_pass = len(findings) - n_fail - n_skip
    lines.append("-" * 72)
    if n_fail:
        verdict = "存在 FAIL，先修再重启（重启门=scripts/pre_restart_check.py）"
    else:
        verdict = "全绿 OK——配置可装载、TTS 段深查通过；重启前请仍跑 pre_restart_check"
    lines.append(f"汇总: PASS {n_pass} / SKIP {n_skip} / FAIL {n_fail} → {verdict}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=".env 配置快查（手动；重启门=pre_restart_check）")
    parser.add_argument("--json", action="store_true", help="结构化 JSON 输出")
    parser.add_argument("--project-root", default=None, help="覆盖 .env 读取根（默认=仓库根）")
    args = parser.parse_args(argv)

    try:  # Windows 控制台中文输出防 mojibake/编码异常
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

    findings: list[Finding] = []
    root_check = check_code_root()
    findings.append(root_check)
    env_root = Path(args.project_root).resolve() if args.project_root else CODE_ROOT

    if root_check.status != FAIL:
        if str(CODE_ROOT) not in sys.path:
            sys.path.insert(0, str(CODE_ROOT))
        env, found = load_env(env_root)
        findings.append(check_env_source(env_root, env, found))
        if found:
            config_finding, cfg, known_tts = check_config(env)
            findings.append(config_finding)
            gate = check_tts_gate(env)
            findings.append(gate)
            if gate.status == PASS:
                findings.append(check_tts_keys(env, known_tts))
                if cfg is not None:
                    findings.append(check_tts_refs(cfg))
                else:
                    findings.append(
                        Finding(
                            "tts_refs",
                            "TTS 参考池深查",
                            SKIP,
                            "Config 装载失败，深查不适用（先修 config_load 各条）",
                        )
                    )

    exit_code = 1 if any(f.status == FAIL for f in findings) else 0
    if args.json:
        print(
            json.dumps(
                {
                    "project_root": str(env_root),
                    "exit_code": exit_code,
                    "findings": [f.__dict__ for f in findings],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(_render_table(findings, env_root))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
