"""TTS 参考语料三源对齐门（审计 M-28/M-29/M-30 / 席 T96）。

权威链（立门原则）：``.env`` 的 ``BOT_TTS_REF_AUDIOS`` = **运行时权威**（已人工
校对：``虚至此报→虚质磁暴``、``力隙→裂隙`` 两处订正，report-T03 diff3 实证恰此
2 处差异）；引擎侧 ``refs/*.tsv`` = **ASR 派生副本**（校对前旧文本，未回写）。
T3 §5.3 的「用 tsv 复核，若有误改 .env」复合法**方向有害**——照做会把订正反向
改回错字（反向毒化）。本门把校对依据落进版本控制（M-28 修复方向第一格），并让
「按 tsv 覆盖 .env」这类动作在门上必红（探针测试锁定）。

skip 约定：``.env`` 未配置语料 / 引擎文件缺失于本机 → 本机 TTS 语料链未配置，
skip（本门守真实工作区，不假设任意机器都有引擎与生产 .env）。

现状二态（2026-09-20）：权威侧三件全绿；引擎侧 tsv 三源**现状即红**（校对未
回写），以 ``xfail(strict=True)`` 落账——修复=收口波把 tsv 订正对齐权威；修复
后转 XPASS 会当场报错，届时移除标记（棘轮自清）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    _resolve_ref_path,
    parse_ref_audios,
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DOT_ENV = WORKSPACE_ROOT / ".env"

# 引擎语种白名单（report-T53 §6 实测集：api_v2 check_params 侧）
ENGINE_LANG_WHITELIST = frozenset(
    {"auto", "auto_yue", "en", "zh", "ja", "yue", "ko", "all_zh", "all_ja", "all_yue", "all_ko"}
)

# 池清单（M-28「受版本控制的清单」最小落法）：权威侧恰为这 8 条 flac。
# 扩池须先过时长门并同步更新本清单与校对依据（M-58 准入带）。
POOL_ROSTER = frozenset(f"shorekeeper_ref_{i:02d}.flac" for i in range(1, 9))

# 校对依据（M-30「校对依据在仓库内不存在」的补位）：按文件钉「必有订正词、
# 必无 ASR 错词」。GLOBAL_FORBID=T29「同词三写法」的全部错形。
GLOBAL_FORBID = ("虚至此报", "虚制磁报", "力隙")
PROOFREAD: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "shorekeeper_ref_01.flac": (("虚质磁暴",), ("虚至此报", "虚制磁报")),
    "shorekeeper_ref_07.flac": (("裂隙",), ("力隙",)),
}

# 引擎 3~10s 硬卡（report-T53 §4.1：16k 采样点 [48000,160000]）
DURATION_MIN_S = 3.0
DURATION_MAX_S = 10.0

ENGINE_REFS_DIR = Path("C:/Software/GPT-SoVITS-V2Pro/refs")
TSV_SFK = ENGINE_REFS_DIR / "shorekeeper_refs_asr.tsv"
TSV_HONAMI = ENGINE_REFS_DIR / "honami_lines_asr.tsv"


# ---------------------------------------------------------------------------
# 取源：.env 单键扫描（不整读上下文）、FLAC 时长只读探测
# ---------------------------------------------------------------------------


def _read_env_value(key: str) -> str | None:
    """从生产 .env 只取单个键的值（逐行扫描，命中即止，不触碰其余键）。"""
    if not DOT_ENV.is_file():
        return None
    with open(DOT_ENV, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith(f"{key}="):
                return stripped.split("=", 1)[1].strip()
    return None


def _load_authority_raw() -> list[str]:
    """运行时权威清单：BOT_TTS_REF_AUDIOS 的原始项列表；未配置则 skip。"""
    raw_value = _read_env_value("BOT_TTS_REF_AUDIOS")
    if raw_value is None or not raw_value.strip():
        pytest.skip("生产 .env 未配置 BOT_TTS_REF_AUDIOS：本机 TTS 语料链未配置")
    value = json.loads(raw_value)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        pytest.fail("BOT_TTS_REF_AUDIOS 不是字符串列表：权威清单格式坏（json 装载失败）")
    return list(value)


def _engine_dir() -> str:
    return _read_env_value("BOT_TTS_GPTSOVITS_DIR") or ""


def _flac_duration_seconds(path: Path) -> float:
    """纯 stdlib FLAC STREAMINFO 只读探测（total_samples / sample_rate）。

    非 FLAC/坏头抛 ``ValueError``（由调用方记为问题项，探针语境不炸门）。
    """
    with path.open("rb") as fh:
        if fh.read(4) != b"fLaC":
            raise ValueError(f"非 FLAC 文件混入参考池：{path.name}")
        block_header = fh.read(4)
        block_type = block_header[0] & 0x7F
        block_len = int.from_bytes(block_header[1:4], "big")
        if block_type != 0:  # 首块必须 STREAMINFO
            raise ValueError(f"FLAC 首元数据块非 STREAMINFO：{path.name}")
        data = fh.read(block_len)
    sample_rate = int.from_bytes(data[10:13], "big") >> 4
    total_samples = int.from_bytes(data[10:18], "big") & ((1 << 36) - 1)
    if sample_rate <= 0:
        raise ValueError(f"FLAC STREAMINFO 采样率异常：{path.name}")
    return total_samples / sample_rate


# ---------------------------------------------------------------------------
# 门体：语料门（结构+时长+污染）与毒化门（校对依据）
# ---------------------------------------------------------------------------


def _corpus_problems(raw_items: list[str], engine_dir: str) -> list[str]:
    """语料结构门：对任意候选清单逐条体检，返回人话问题列表（空=过门）。"""
    problems: list[str] = []
    parsed = parse_ref_audios(raw_items, base_dir=engine_dir)
    if len(parsed) != len([x for x in raw_items if str(x).strip()]):
        problems.append("有条目在 parse_ref_audios 中被静默丢弃（路径段为空或格式坏）")
    if len(parsed) != len(POOL_ROSTER):
        problems.append(f"池应恰为 {len(POOL_ROSTER)} 条（本门清单），实得 {len(parsed)} 条")
    for raw in raw_items:
        item = str(raw).strip()
        if item.count("|") > 2:
            problems.append(
                f"竖线污染（M-29）：条目含 {item.count('|')} 个 '|'，prompt_text 会被"
                f"裸 split 截半/语种错位——文本不得含 '|'：{item[:40]}…"
            )
    for ref in parsed:
        name = Path(ref.path).name
        if name not in POOL_ROSTER:
            problems.append(
                f"清单外条目（扩池须先过时长门并更新本门清单/校对依据；"
                f"shorekeeper_ref_01.wav=已退役杂散件 M-58/M-69）：{name}"
            )
        if not ref.text.strip():
            problems.append(f"参考文本为空（语料对齐门要求逐字文本，M-30）：{name}")
        if ref.lang not in ENGINE_LANG_WHITELIST:
            problems.append(
                f"语种不在引擎白名单（疑为文本碎片挤占语种位）：{name} lang={ref.lang!r}"
            )
        resolved = _resolve_ref_path(ref.path, engine_dir)
        if not resolved.is_file():
            problems.append(f"参考音频文件不存在：{resolved}")
            continue
        try:
            duration = _flac_duration_seconds(resolved)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if not (DURATION_MIN_S <= duration <= DURATION_MAX_S):
            problems.append(
                f"时长出引擎 3~10s 硬卡（report-T53 §4.1）：{name} = {duration:.3f}s"
            )
    return problems


def _poison_problems(refs: list) -> list[str]:
    """毒化门：校对依据核验——订正词必在、ASR 错词必不在。"""
    problems: list[str] = []
    for ref in refs:
        name = Path(ref.path).name
        for word in GLOBAL_FORBID:
            if word in ref.text:
                problems.append(
                    f"ASR 错词「{word}」出现在权威清单（=已按 tsv 反向毒化，"
                    f"或校对被回退）：{name}"
                )
        require_words, _forbid = PROOFREAD.get(name, ((), ()))
        for word in require_words:
            if word not in ref.text:
                problems.append(
                    f"校对订正词「{word}」缺失（该条校对依据被破坏）：{name}"
                )
    return problems


def _authority_refs() -> tuple[list[str], list]:
    raw_items = _load_authority_raw()
    return raw_items, parse_ref_audios(raw_items, base_dir=_engine_dir())


# ---------------------------------------------------------------------------
# 绿面：运行时权威（.env）三件体检
# ---------------------------------------------------------------------------


def test_env_authority_passes_corpus_gate() -> None:
    """权威清单：条目数/清单面/竖线污染/语种/文件存在/3~10s 时长全过。"""
    raw_items, _refs = _authority_refs()
    problems = _corpus_problems(raw_items, _engine_dir())
    assert problems == [], "权威清单语料门破：" + "；".join(problems)


def test_env_authority_carries_proofread_corrections() -> None:
    """权威清单：虚质磁暴/裂隙 两处订正在位，同词三写法错形零出现。"""
    _raw, refs = _authority_refs()
    problems = _poison_problems(refs)
    assert problems == [], "权威清单毒化门破：" + "；".join(problems)


def test_flac_probe_matches_verified_ffprobe_baseline() -> None:
    """STREAMINFO 探测器自检：对 T3 ffprobe 实测锚点（ref_03=5.335104s）成立。"""
    _raw, refs = _authority_refs()
    ref03 = next(r for r in refs if Path(r.path).name == "shorekeeper_ref_03.flac")
    duration = _flac_duration_seconds(Path(ref03.path))
    assert abs(duration - 5.335104) < 0.05, f"ref_03 时长漂移：{duration:.6f}s"


# ---------------------------------------------------------------------------
# 探针面（绿=门有效）：竖线污染与「按 tsv 覆盖 .env」必红
# ---------------------------------------------------------------------------


def test_pipe_pollution_probe() -> None:
    """M-29 探针：文本/语种段被竖线挤位的条目必须被门拦下。"""
    poisoned = [
        "refs/x.flac|正常文本|zh",
        "refs/x.flac|被截半的文本|多余段|zh",  # 3 竖线：text 截半+段错位
        "refs/x.flac|碎片一|碎片二冒充语种",  # 语种位=文本碎片
    ]
    problems = _corpus_problems(poisoned, _engine_dir())
    joined = "；".join(problems)
    assert "竖线污染" in joined, f"3 竖线条目未被拦：{joined}"
    assert "语种不在引擎白名单" in joined, f"碎片冒充语种未被拦：{joined}"


def test_reverse_poisoning_probe_overwrite_env_from_tsv() -> None:
    """M-28/M-30 本门存在意义：模拟「按 tsv 粘贴块覆盖 .env」→ 门必须红。

    探针材料=引擎侧 tsv 末尾「可直接粘进 .env 的清单」（校对前旧文本：虚至此报/
    力隙 + 杂散 ref_01.wav 第 9 条）。门须同时报出：ASR 错词、清单外条目、池数
    不符。绿=门拦得住反向毒化；这行测试红才说明门失效。
    """
    paste_block = _tsv_pasteable_lines(TSV_SFK)
    assert paste_block, f"探针材料缺失：{TSV_SFK} 无可粘贴块"
    problems = _corpus_problems(paste_block, _engine_dir())
    problems += _poison_problems(parse_ref_audios(paste_block, base_dir=_engine_dir()))
    joined = "；".join(problems)
    assert "虚至此报" in joined, f"反向毒化未被拦（虚至此报漏网）：{joined}"
    assert "力隙" in joined, f"反向毒化未被拦（力隙漏网）：{joined}"
    assert "清单外条目" in joined, f"杂散 wav 未被拦（M-58/M-69 漏网）：{joined}"


# ---------------------------------------------------------------------------
# 红面（现状病，xfail 棘轮）：引擎侧 tsv 三源未回写校对
# ---------------------------------------------------------------------------


def _tsv_pasteable_lines(tsv_path: Path) -> list[str]:
    """tsv 末尾「可直接粘进 .env 的清单」块：形如 路径|文本|语种 的行。"""
    if not tsv_path.is_file():
        pytest.skip(f"引擎侧 tsv 不在本机：{tsv_path}")
    lines: list[str] = []
    with open(tsv_path, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and stripped.count("|") == 2:
                lines.append(stripped)
    return lines


def _tsv_table_texts(tsv_path: Path) -> dict[str, str]:
    """tsv 表体：basename → text（制表符 5 列：file/duration/sr/ch/text）。"""
    if not tsv_path.is_file():
        pytest.skip(f"引擎侧 tsv 不在本机：{tsv_path}")
    table: dict[str, str] = {}
    with open(tsv_path, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.rstrip("\n")
            if not stripped or stripped.startswith(("#", "file\t")):
                continue
            fields = stripped.split("\t")
            if len(fields) >= 5 and "|" not in fields[0]:
                table[Path(fields[0].strip()).name] = fields[4].strip()
    return table


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M-28/M-30 现状病：refs/shorekeeper_refs_asr.tsv 表体仍是校对前旧文本"
        "（虚至此报/力隙），未回写 .env 权威的 2 处订正。修复=收口波把 tsv 订正"
        "对齐 .env 权威（绝不可反向改 .env）；修复后本测试转 XPASS（strict 当场"
        "报错），届时移除本标记。"
    ),
)
def test_tsv_table_matches_env_authority() -> None:
    """tsv 表体文本必须与 .env 权威逐字一致（tsv=推导副本，权威只在 .env）。"""
    raw_items, refs = _authority_refs()
    assert len(raw_items) == len(POOL_ROSTER), "权威清单条目数异常，先修权威侧"
    table = _tsv_table_texts(TSV_SFK)
    divergences: list[str] = []
    for ref in refs:
        name = Path(ref.path).name
        tsv_text = table.get(name)
        if tsv_text is None:
            divergences.append(f"{name}: tsv 表体缺行")
        elif tsv_text != ref.text:
            divergences.append(f"{name}: tsv={tsv_text!r} ≠ 权威={ref.text!r}")
    assert not divergences, (
        "tsv 是校对前旧文本（照 T3 §5.3 复核法操作会反向毒化）。"
        f"修复=订正 tsv 对齐权威，差异 {len(divergences)} 处：{'；'.join(divergences)}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M-69 现状病：refs/shorekeeper_refs_asr.tsv 末尾「可粘进 .env 清单」共 "
        "9 条（混入已退役杂散件 shorekeeper_ref_01.wav）且文本为校对前旧文。"
        "修复=收口波重写粘贴块对齐权威（8 条 flac+订正后文本）；修复后转 "
        "XPASS，届时移除本标记。"
    ),
)
def test_tsv_pasteable_block_matches_env_authority() -> None:
    """「可粘进 .env」块必须恰为权威 8 条且逐字一致——它是反向毒化最短路径。"""
    raw_items, refs = _authority_refs()
    paste_block = _tsv_pasteable_lines(TSV_SFK)
    authority_by_name = {Path(r.path).name: r.text for r in refs}
    problems: list[str] = []
    if len(paste_block) != len(POOL_ROSTER):
        problems.append(f"粘贴块应 {len(POOL_ROSTER)} 条，实得 {len(paste_block)} 条")
    for item in paste_block:
        parts = item.split("|")
        name = Path(parts[0].strip()).name
        if name not in POOL_ROSTER:
            problems.append(f"粘贴块含清单外条目（杂散件）：{name}")
            continue
        text = parts[1].strip()
        if text != authority_by_name.get(name):
            problems.append(f"{name}: 粘贴块={text!r} ≠ 权威={authority_by_name.get(name)!r}")
    assert not problems, (
        "tsv 粘贴块照粘即毒化 .env（M-69）。修复=订正粘贴块，差异："
        + "；".join(problems)
    )
    del raw_items


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M-28 现状病（第二源）：refs/honami_lines_asr.tsv 同含 ASR 错词"
        "（虚至此报/虚制磁报/力隙 同词三写法）。honami 语料权威订正文不在 "
        ".env（其参考池未被 bot 消费），收口波订正 tsv 后转 XPASS，届时移除标记。"
    ),
)
def test_honami_tsv_free_of_asr_mishearings() -> None:
    """honami tsv 全文扫描：三写法错形零出现（裂隙/磁暴正字不计）。"""
    if not TSV_HONAMI.is_file():
        pytest.skip(f"引擎侧 tsv 不在本机：{TSV_HONAMI}")
    hits: list[str] = []
    with open(TSV_HONAMI, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            for word in GLOBAL_FORBID:
                if word in line:
                    hits.append(f"L{lineno}:{word}")
    assert not hits, (
        "honami tsv 含 ASR 错词（收口波订正，勿据此回改任何权威）："
        + "，".join(hits)
    )
