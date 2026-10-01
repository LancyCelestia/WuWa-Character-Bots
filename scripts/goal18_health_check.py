"""§51 波只读体检口：十八项 + 贴纸语义匹配 + 永久回复策略，一条命令看红在哪、归谁。

为什么有这一件：本波的判据散在四十多枚测试件里，红的时候人要先 grep 才知道是谁的家事。
这里把"需求号 → 判据件 → 修法坐标"钉成一张表，跑完直接按需求报。

只读：跑测试、归类、打印。不改任何文件、不写库、不重启进程、不碰 git。

用法（在仓库根）：
    python scripts/goal18_health_check.py              # 全跑（逐组串行，省内存）
    python scripts/goal18_health_check.py 3 9 20       # 只跑点名的需求号
退出码：0＝全绿；1＝有红；2＝有需求组的判据件整组缺席（多半是文件被改名或没入库）。

卫生口径同 AGENTS 规则 6：不写源码树缓存、basetemp 落仓库外。
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Windows 控制台默认 GBK，本件全中文输出 ⇒ 不改码就直接吐乱码（本席实跑撞到过一次）。
# 拿不到可重配的流（被重定向成非文本流等）就按现状输出，不影响判定，故 suppress。
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

# 需求号 → (人话标题, 判据件, 修法坐标/归属提示)
GROUPS: dict[int, tuple[str, list[str], str]] = {
    1: (
        "分句合并（一句话只回一次）",
        ["tests/test_message_coalescing.py", "tests/test_coalescing_wiring_lock.py"],
        ("真身 domains/chat_reply/runtime/message_coalescing.py；"
        "她 2026-09-27 裁定 .env 暂关（实测效果不好），红先看开关再判代码"),
    ),
    2: (
        "群聊连发不被冷却吞",
        [
            "tests/test_policy_queue_not_drop.py",
            "tests/test_redrive_window_exhaustion.py",
            "tests/test_throttle_redrive_and_adaptive_ack.py",
        ],
        ("真身 policy/rate_limit.py + policy/redrive_ledger.py；"
        "补回次数/窗口的缺省值住 config.py 两枚 bot_chat_rate_limit_redrive_*"),
    ),
    3: (
        "联网搜索触发 + 二游库命中如实",
        [
            "tests/test_question_intent.py",
            "tests/test_web_search_timely_domain_routing.py",
            "tests/test_search_acg_switch_leg.py",
            "tests/test_acg_kb_retrieval_accuracy.py",
            "tests/test_kb_hit_certification.py",
            "tests/test_kb_list_domain_gate.py",
        ],
        ("判据 runtime/question_intent.py 的 PRIMARY 短路 + chat.py 的按域来源表；"
        "跨库次序走 search_service.resolve_answer_order（装配口在根 __init__.py）"),
    ),
    4: (
        "账号/群元信息读写",
        [
            "tests/test_group_info.py",
            "tests/test_group_profile_host_reads_s_meta.py",
        ],
        ("真身 capabilities/group_info.py（三态 ok/failed/unprobed 不许互串）；"
        "客观无 API 的格子由缺席锁看着，别为跑绿去编数据"),
    ),
    5: (
        "超管宿主机状态卡",
        [
            "tests/test_host_metrics.py",
            "tests/test_host_metrics_single_source.py",
            "tests/test_host_state_card.py",
            "tests/test_host_status.py",
        ],
        ("取数唯一口 ops/host_metrics.py；版本对唯一口 monitor/error_report._version_pairs；"
        "出卡只准走 assemble_card_payload → render_payload_png 一条缝"),
    ),
    6: (
        "慢回复先回执的误触发",
        ["tests/test_progress_ack_thresholds.py"],
        ("阈值唯一面 runtime/progress_ack.py 的 DEFAULT_*；"
        "静态值只在「没有观测数据」时起作用，有实况时由 EWMA×倍率夹 floor~cap（2026-09-28 解耦）"),
    ),
    7: (
        "渲染模板规格统一",
        [
            "tests/test_rendering_contract.py",
            "tests/test_mica_builders_contract.py",
            "tests/test_template_visual_audit.py",
            "tests/test_news_digest_card_contract.py",
            "tests/test_help_card_twocol.py",
        ],
        ("token 唯一真身 card_render/theme_tokens.py；"
        "执法面 _OWNED_FSTRING_FACES 含直拼面（echo/debug），新面要先进面再谈统一"),
    ),
    8: (
        "TTS 概率与原文本+音频",
        ["tests/test_tts_probability_lock.py"],
        ("概率唯一数值源 config.py 的 bot_tts_auto_reply_probability（现网 0.10）；"
        "本件自身禁手抄数字，改测试前先确认门吃的哪一枚"),
    ),
    9: (
        "回复长度分档与出口地板",
        [
            "tests/test_reply_length_tier.py",
            "tests/test_kb_grounding_chat.py",
        ],
        ("档位真身 chat.py 的 REPLY_LENGTH_TIERS；"
        "地板腿＝同一路由口多问一次，接地块必须原样带上（第二腿断言在那两把锁里）"),
    ),
    10: (
        "bot 知道自己身处何年何月",
        [
            "tests/test_time_partition_day_divergence.py",
            "tests/test_self_capability_index_readout.py",
            "tests/test_self_info_reaches_prompt.py",
            "tests/test_self_calendar.py",
        ],
        ("四把钟与历法委托 divination/data/multi_calendar.py（禁第二真身）；"
        "功能自述索引＝capability_registry.HELP_TOPIC_DECLARATIONS"),
    ),
    11: (
        "记忆系统（记得住/想得起/说得出）",
        [
            "tests/test_memory_bus_v2_write_leg.py",
            "tests/test_memory_open_state_locks_s_memaff.py",
        ],
        ("类目折进既有 MemoryKind 三支、**绝不喂 slot 命名空间**（零迁移红线）；"
        "总线 absorb 那道消毒不许退回去"),
    ),
    12: (
        "表情包吸收与选贴",
        ["tests/test_meme_vlm_observability.py", "tests/test_meme_atk_media_fixes.py"],
        ("本命判定 sources/meme_library_listener.py；"
        "厌恶词由 affinity 印象规则派生（禁第二份判据）"),
    ),
    13: (
        "好感度线性与防瞬间剧变",
        [
            "tests/test_affinity_v7_structural_locks.py",
            "tests/test_affinity_open_state_locks_s_memaff.py",
            "tests/test_affinity_query.py",
        ],
        ("消毒唯一口 character/affinity.py::coerce_override_delta + 末道闸 affinity_after_move；"
        "存量零迁移是红线，别写 UPDATE"),
    ),
    14: (
        "戳一戳五臂/跟戳/回复后戳",
        [
            "tests/test_poke_five_way_matrix.py",
            "tests/test_poke_randpic_behavior.py",
            "tests/test_poke_randpic_open_state_s_meta.py",
        ],
        ("选臂 capabilities/poke.py；私聊零派发是铁律（QQ 侧本无通道）；"
        "摘牌必带回潮杀伤力自证，不许只放宽期望"),
    ),
    15: (
        "随机发图三触发点",
        ["tests/test_randpic_bucket_key_ledger.py"],
        ("取图唯一口 capabilities/randpic.py::pick_gallery_image_outcome；"
        "主动派发腿开了就必须同给反重复窗，否则一开就重发"),
    ),
    16: (
        "文件读取/创建/收发",
        [
            "tests/test_file_reader_parse_safety.py",
            "tests/test_restricted_runner_confinement.py",
            "tests/test_files_write_side_assembly.py",
            "tests/test_telegram_document_ingress.py",
        ],
        ("受限运行器 domains/files/sender/restricted_runner.py（路径域白名单，非容器）；"
        "代码执行缺省关，execute=True 全仓不得有生产调用点"),
    ),
    17: (
        "反攻击反注入",
        [
            "tests/test_safety_exec_paths.py",
            "tests/test_safety_exec_trust.py",
            "tests/test_attack_surface_consumers.py",
            "tests/test_safety_sectext_guard_legs.py",
            "tests/test_prompt_injection_order.py",
        ],
        ("登记表 domains/core/safety_exec/attack_surface.py：GAP→PARTIAL 必须写判据，"
         "不许静默升 DEFENDED；文件正文一律 T2"),
    ),
    18: (
        "书面同意与参数自改",
        [
            "tests/test_safety_exec_consent.py",
            "tests/test_consent_command_surface.py",
            "tests/test_safety_exec_throat_wire.py",
        ],
        ("咽喉唯一 _throat_guard + 控制面写口 _guarded_apply；"
         "R2 缺省＝未登记键一律要书面同意（fail-closed 方向，别放宽）"),
    ),
    19: (
        "永久性 per-user 回复策略（她 2026-09-28 新增）",
        ["tests/test_reply_policy_permanent.py"],
        ("真身 character/reply_policy.py；优先级＝当轮明示 > 永久策略 > 全局 BOT_REPLY_DETAIL；"
         "关闸走 shared_reply_policy_store 一处，禁在调用方各写一份"),
    ),
    20: (
        "贴纸按内容语义匹配（她 2026-09-28 新增）",
        ["tests/test_sticker_sentiment_alignment.py", "tests/test_reactions_silence_reason_lock.py"],
        ("真身 domains/meme/reactions/sentiment_selector.py：读 bot 本轮实际回复文本判受控情感闭集；"
         "判不了/超时＝整轮不贴，**绝不降级成随便贴一张**"),
    ),
}

_FAILED_RE = re.compile(r"^(FAILED|ERROR)\s+(\S+::[\w\[\]\-.]+|\S+)")


def _run_group(files: list[str], basetemp: Path) -> tuple[int, list[str], list[str]]:
    """跑一组，返回（退出码, 红清单, 缺席件）。逐组串行是为省内存（本仓有 OOM 前例）。"""
    present = [f for f in files if (ROOT / f).exists()]
    missing = [f for f in files if not (ROOT / f).exists()]
    if not present:
        return 0, [], missing
    env = dict(os.environ)
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(basetemp / "pycache"),
            "BOT_AUTOSYNC": "0",
        }
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *present,
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(basetemp / f"bt{abs(hash(tuple(present))) % 9973}"),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,  # 退出码非零＝有红，是本件的正常输入，不是错误（红面由调用方判）
    )
    reds: list[str] = []
    for line in (proc.stdout + proc.stderr).splitlines():
        m = _FAILED_RE.match(line.strip())
        if m:
            reds.append(line.strip())
    return proc.returncode, reds, missing


def main(argv: list[str]) -> int:
    wanted = [int(a) for a in argv if a.isdigit()] or sorted(GROUPS)
    unknown = [n for n in wanted if n not in GROUPS]
    if unknown:
        print(f"未知需求号 {unknown}；在册组：{sorted(GROUPS)}")
        return 2
    basetemp = Path(tempfile.mkdtemp(prefix="goal18-health-"))
    total_red: list[str] = []
    empty_groups: list[int] = []
    for num in wanted:
        title, files, where = GROUPS[num]
        code, reds, missing = _run_group(files, basetemp)
        tag = "OK " if not reds else "RED"
        print(f"[{tag}] 需求{num:>2} {title}")
        if code not in (0, 1) and not reds:
            # 退出码既不是"全绿(0)"也不是"有红(1)"＝收集期炸了（导入错/参数错），
            # 这种情况 pytest 可能一行 FAILED 都不吐 ⇒ 必须点名，不得报成 OK。
            print(f"        非零退出码 {code}（收集期错误？）：本组读数不可信，请手工复跑")
        if missing:
            print(f"        缺席件（未入库/改名）：{', '.join(missing)}")
            empty_groups.append(num)
        for r in reds:
            print(f"        {r}")
            total_red.append(f"需求{num}: {r}")
        if reds:
            print(f"        归因线索：{where}")
    print()
    print(f"红 {len(total_red)} 枚；判据件整组缺席 {len(empty_groups)} 组")
    if total_red:
        print("复跑单枚：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 "
              "../ChatBot_Runtime/venv/Scripts/python.exe -m pytest <件> -q "
              "-p no:cacheprovider --basetemp=<仓库外>")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
