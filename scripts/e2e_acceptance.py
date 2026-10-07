"""重启后真机验收脚本（E2E acceptance）。

目的：bot 重启后，向真实群/私聊逐条发送「所有可能的消息种类」（文本/长文本/
多段、解析卡、点歌候选卡、全球股指 18 指数全量、财经/科技快报全量、天气+预警、
随机图、占卜、help 卡、好感度卡、提醒查询、个股行情+非上市守卫、汇率面板/
定向换算、称谓自助），供用户回 ``test`` 人工验收。2026-09-13 批次起部分检查项
带 ``expect`` 回执断言（作用于入队 SendRequest 层，DRY-RUN/--execute 同语义）。
2026-10-06 起，群侧斜杠命令那四枚（identity set/unset-name、decision-query admin/member）
改成**与门禁同形的双轨**：真入队了 → 验真跑通的回执；被 ``policy/gate`` 的
``command_group_unlisted``／``group_white2_need_trigger`` 按设计拦下 → 期望值就是
blocked＋原因可查（判 PASS，不是 FAIL）；被**别的**原因拦（安静时间/限流/黑名单，以及
「个人输出不出群」那格 reviewer 改道）→ 照旧判红并回显留痕。判据一条都没放宽：
见 ``expect_command_after_group_gate``。这四枚的正跑面今天只在**私聊**
（``--target-user``）看得见——它们的回复都自带 ``privacy_level=personal`` 声明，
群侧会被 reviewer 判 ``move_private`` 而改道（转私聊的消费侧仍未实装，属待裁残余）。
🔴 还有一条已知失真要说在前面：本脚本的 ``build_pipeline`` 没把生产那份群名单输入
（``group_black1/2``＋``group_white1/2``＋``group_lists_provider``）接给管线，
所以**验收面里任何群都算未在册**——这一轨证明的是门禁形状，不是「这群真的不在册」；
全注见 ``_COMMAND_GATE_DENIALS`` 上方（补接线＝改门禁输入，未获授权，留给用户裁）。

真实管线（不绕过）：
    合成 IncomingMessage
      → RuntimePipeline.handle（policy → decision → capability → review
        → render_reviewed_output → 合并转发/分块 → SendRequest → send_queue.submit）
    与 plugins/bot_unified_runtime/__init__.py 注册的各 handler 走同一管道；
    能力构造函数也按 __init__.py 的装配方式原样复用（只读 import，零改动）。

安全阀：
- 默认 **DRY-RUN**：send_queue 为进程内 InMemorySendQueue，绝无真实发送路径；
  逐项打印「将发内容」（渲染后的 content_type / 文本预览 / 媒体计数）。
- ``--execute`` 走 **临时库** 的 SQLite 队列（结构性隔离，非条件式，2026-10-07）：
  send_queue 换成 ``build_send_queue(...)`` 的真 SQLite 队列，但 ``bot_send_queue_db_path``
  被 ``choose_send_queue``→``send_queue_isolation_config`` 改指 **OS 临时目录**（缺省无条件；
  唯一例外＝``--live-delivery``，见下）
  （``send_queue_isolation_dir``，不在源码树、不在 ``ChatBot_Runtime`` 根），
  **绝不**落 ``ChatBot_Runtime/data/wuwa_send_queue.sqlite3``。理由＝那本库是在线 bot 的
  send-queue worker 共读的**投递账本**：验收器往里入队＝在线 worker 会拿它去真发群/私聊
  （盘上实据：曾因此产生 38 枚 ``sent``+107 枚 ``failed_final`` 的 e2e 行）。落临时库后
  走的是真实 submit/建表/part 账本/``find_request``，但**在线 worker 看不见 ⇒ 零真实投递**。
  若 .env 未启用持久化发送队列则拒绝执行（准入判定仍读原配置那枚生产路径）。
  ⚠ 「借生产队列交在线 worker 真发」这条通路**默认关闭**（用户 2026-10-06 裁「隔离为默认＋
  真发要显式旗」）：要真投递就显式带 ``--live-delivery``，此时队列落回生产库、目标会真收到，
  并且每一行都写进生产投递台账——旗只作用于 ``--execute``，DRY-RUN 带旗也绝不真发。
- ``--target-group`` / ``--target-user`` 必填其一；群目标必须已在运行时 store
  的 BOT_GROUP_WHITE1 白名单（与 pipeline 同源读取），否则拒绝执行。
- 逐项打印 ``[序号] 能力 → 发送结果回执``：state/transport/skipped 原样可见，
  能力层静默降级（如随机图未配置目录）也会如实反映为 skipped/silent。

示例::

    python scripts/e2e_acceptance.py --target-group 123456          # DRY-RUN
    python scripts/e2e_acceptance.py --target-group 123456 --execute
    python scripts/e2e_acceptance.py --target-user 10001 --execute --only help,affinity

实战自测模式（2026-09-13 批次新增，只往后加参数，存量参数语义不变）::

    python scripts/e2e_acceptance.py --selftest
        # 全离线自检：矩阵生成/触发提取/payload 构造/报告渲染/探针/轮询，不依赖 bot 在线
    python scripts/e2e_acceptance.py --target-group 123456 --help-matrix
        # 从 echo._HELP_ENTRIES 全 topics 生成命令矩阵（DRY-RUN：只构造 payload + 路由体检）
    python scripts/e2e_acceptance.py --target-group 123456 --help-matrix --execute --report
        # 逐条发送 + 等待投递回执（响应/超时/异常三态与耗时），报告私聊超管（离线则写文件）
        # 注意：本模式验证的是「命令 payload 经发送链路的投递」，命令语义处理验收用存量矩阵
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import tempfile
import time
import traceback
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

# 直接以 `python scripts/e2e_acceptance.py` 运行时，sys.path[0] 是 scripts/，
# 需要显式把仓库根加进搜索路径才能 import plugins.*（与 knowledge_bench 同式）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    OperationalIssue,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
    build_affinity_capability,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    _HELP_ENTRIES as _HELP_REGISTRY,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    build_decision_query_result,
    build_help_result,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.user_copy import (
    GROUP_FAILURE_ACK_TEMPLATES,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy import (
    build_quiet_hours_checker,
    build_rate_limiter,
    build_reply_budget_settings,
    build_role_settings,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
    classify_message_route,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    build_instance_settings_manager,
    effective_instance,
)
from plugins.bot_unified_runtime.domains.core.decision.trace import (
    InMemoryDecisionTraceSink,
)
from plugins.bot_unified_runtime.domains.divination.capabilities.divination import (
    build_divination_capability,
    is_divination_command,
)
from plugins.bot_unified_runtime.domains.finance.capabilities.fx import (
    build_fx_capability,
)
from plugins.bot_unified_runtime.domains.finance.capabilities.market import (
    build_market_capability,
    is_market_command,
)
from plugins.bot_unified_runtime.domains.finance.capabilities.stocks import (
    build_stocks_capability,
    is_stocks_command,
)
from plugins.bot_unified_runtime.domains.link_parse.capabilities.content_parser import (
    build_content_capability,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers import (
    build_cookie_provider,
    music_candidate_providers,
)
from plugins.bot_unified_runtime.domains.meme.capabilities.meme_library import (
    build_meme_library_capability,
)
from plugins.bot_unified_runtime.domains.meme.capabilities.randpic import (
    build_randpic_capability,
)
from plugins.bot_unified_runtime.domains.meme.sources.meme_library import (
    MemeLibraryStore,
)
from plugins.bot_unified_runtime.domains.music.capabilities.music import (
    build_music_capability,
)
from plugins.bot_unified_runtime.domains.ops.smoke.smoke import load_smoke_config
from plugins.bot_unified_runtime.domains.render.render_backends import (
    build_render_backend,
)
from plugins.bot_unified_runtime.domains.schedule.capabilities.reminder import (
    build_reminder_capability,
)
from plugins.bot_unified_runtime.domains.subscribe.capabilities.news import (
    build_news_capability,
)
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    SQLiteSendRequestQueue,
)
from plugins.bot_unified_runtime.domains.weather.capabilities.weather import (
    build_weather_capability,
)

BILI_SAMPLE_URL = "https://www.bilibili.com/video/BV1GJ411x7h7"
DEFAULT_INTERVAL_SECONDS = 8.0
PREVIEW_MAX_CHARS = 240


class E2eSafetyError(RuntimeError):
    """安全阀拒绝执行（目标缺失/非 white1 群/队列不满足真发条件）。"""


# --------------------------------------------------------------------------
# 运行时装配（镜像 __init__.py 的注册期装配，仅取本脚本需要的子集）
# --------------------------------------------------------------------------


@dataclass
class E2eRuntime:
    """装配产物：config / 渲染后端 / 运行时设置 / 模式开关。"""

    config: Any
    runtime_settings: Any
    render_backend: Any | None
    execute: bool
    city: str
    bot_id: str
    sender_id: str
    # 用户 2026-10-06 裁「A」：`--execute` **缺省隔离**（不碰她的生产投递台账），要真发必须
    # 显式带 `--live-delivery`。旗只作用于 execute 态——DRY-RUN 带旗也绝不真发。
    live_delivery: bool = False


def build_runtime(
    *,
    env_file: str | None,
    execute: bool,
    city: str,
    bot_id: str,
    sender_id: str,
    live_delivery: bool = False,
) -> E2eRuntime:
    config = load_smoke_config(env_file)
    settings_manager = build_instance_settings_manager(config)
    runtime_settings = settings_manager.get(effective_instance(config))
    render_backend = (
        build_render_backend(config.bot_card_render_backend)
        if bool(getattr(config, "bot_card_render_enabled", True))
        else None
    )
    resolved_bot_id = str(
        bot_id or getattr(config, "bot_gscore_bot_self_id", "") or ""
    ).strip()
    return E2eRuntime(
        config=config,
        runtime_settings=runtime_settings,
        render_backend=render_backend,
        execute=execute,
        city=city,
        bot_id=resolved_bot_id,
        sender_id=sender_id,
        live_delivery=live_delivery,
    )


def _bot_self_name(runtime: E2eRuntime) -> str:
    """验收面的 bot 自称——与生产同一枚唯一读法（P-G3 第二波，2026-09-29）。

    此前这里和 help 卡各自写 ``config.bot_persona_display_name or "守岸人"``，等于
    验收入口自带第二条取名腿：切人格后生产卡片换了名、验收仍按配置名出卡，两边
    读数不可比。现统一经 ``persona_profile.current_bot_nickname``（先查人格册按
    当前生效人格 id 现读，再回落兼容显示名），切换态直接取 runtime 已装配的那枚
    store（不新建第二份）。绝不读 ``get_login_info``（台账 #60★）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
        active_persona_id,
        current_bot_nickname,
    )

    return current_bot_nickname(
        active_persona_id(
            runtime.config,
            override_provider=runtime.runtime_settings.get_persona_override,
        ),
        config=runtime.config,
    )


def build_pipeline(
    runtime: E2eRuntime, send_queue: Any, audit_logger: Any = None
) -> RuntimePipeline:
    """与 __init__.py 注册函数内同一套 RuntimePipeline 装配（子集）。

    ``audit_logger``＝可选注入（席 e2e2 追加，缺省仍新建进程内 InMemory ⇒ 存量调用面
    与 `tests/test_e2e_acceptance.py` 语义逐字节不变）。只多这一枚口，是为了让
    「群内逐段涂销」那行 review 审计在验收面**可回查**——它是 2026-10-04 才接上的
    一行，改前「已落账」是假话；不注入就得再造第二套装配。
    """
    config = runtime.config
    return RuntimePipeline(
        send_queue=send_queue,
        audit_logger=audit_logger
        if audit_logger is not None
        else InMemoryAuditLogger(),
        reply_budget_settings=build_reply_budget_settings(config),
        role_settings=build_role_settings(config),
        group_command_prefix=config.bot_runtime_group_command_prefix,
        runtime_enabled=config.bot_runtime_enabled,
        rate_limiter=build_rate_limiter(config),
        quiet_hours_checker=build_quiet_hours_checker(config),
        forward_min_chars=config.bot_render_forward_min_chars,
        forward_max_nodes=config.bot_render_forward_max_nodes,
        forward_node_chars=config.bot_render_forward_node_chars,
        forward_min_nodes=int(
            getattr(config, "bot_render_forward_min_nodes", 4) or 4
        ),
        # 合并转发节点的署名＝bot 自称，走唯一读法（P-G3 第二波）：验收读数必须与
        # 生产同一枚腿，否则「验收通过」证明的是另一个名字。override 用 runtime 已
        # 装配的那枚 store（不再新建第二份切换态）。禁 get_login_info（台账 #60★）。
        forward_sender_name=_bot_self_name(runtime),
        group_auto_reply_enabled=False,
        group_auto_reply_probability=0.0,
    )


def send_queue_isolation_dir(override: str | Path | None = None) -> Path:
    """验收器**发送队列那本 SQLite 库**（同库带 ``send_request_parts`` part 账本）的
    临时落点根——OS 临时目录：不在源码树、不在 ``ChatBot_Runtime`` 根。

    🔴 结构性隔离，不是条件隔离（2026-10-07 本波）：``--execute`` 旧写法直接拿
    ``build_send_queue(runtime.config)`` 的 ``bot_send_queue_db_path``，而 `.env` 那枚
    ``data/wuwa_send_queue.sqlite3`` 经 ``runtime_paths`` 折成**生产库**
    ``ChatBot_Runtime/data/wuwa_send_queue.sqlite3``——在线 bot 的 send-queue worker
    读的正是同一本库，于是验收器入队的合成请求**被在线 worker 拿去真发**到群
    662948429 / 私聊，协议端 ``retcode=100`` 打成 ``failed_final``，并把
    ``origin_message_id`` 为 ``e2e-*`` 的行写进了投递台账（盘上实据见
    tests/test_e2e_acceptance_queue_isolation.py 与本文件头）。这与 DRY-RUN
    「只验形状不发」的承诺自相矛盾，也正是本波要根治的事故面。

    改指 OS 临时目录后：验收器走的仍是**真实** ``SQLiteSendRequestQueue``（真实建表、
    真实 submit、真实 part 账本、真实 ``find_request``），但库文件落在临时目录 ⇒
    在线 worker 看不见 ⇒ 生产队列零字节、零真发。DRY-RUN 更不消说（InMemory，
    一张 SQLite 都不开）。**不新增全局配置键**——复用 ``narration_probe_config``
    那把 ``model_copy`` 换库路径的既有尺（见 ``send_queue_isolation_config``）。

    固定名而非 ``mkdtemp``：与 ``_identity_dry_run_dir`` 同理，让同一轮验收的 probe
    与逐项入队落在同一本临时库里才验得出连续性；轮与轮之间靠 OS 临时目录天然隔离。
    ``override`` 供测试注入 ``tmp_path``（缺省 None 才走 OS 临时根）。
    """
    root = (
        Path(override)
        if override is not None
        else Path(tempfile.gettempdir()) / "e2e-send-queue-isolation"
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def send_queue_isolation_config(base: Any, tmp_dir: Path) -> Any:
    """照抄生产 config，只把**发送队列那本库**改指临时目录。

    只动 ``bot_send_queue_db_path`` 一枚键——``send_request_parts``（part 账本，即本波
    说的「ledger」）与 ``send_requests`` 同库同文件，改路径即两本一起隔离；审计/回执
    两本在验收器里本就走内存实现（``InMemoryAuditLogger`` / 管线缺省
    ``InMemoryReceiptRepository``），不碰磁盘、无须改。手法与 ``narration_probe_config``
    一致（``model_copy`` 而非新建 ``Config``，否则不读环境变量、缺省
    ``bot_runtime_data_dir="data"`` 会把路径折回源码树）。
    """
    update = {
        "bot_send_queue_db_path": str(tmp_dir / "wuwa_send_queue.sqlite3"),
    }
    copier = getattr(base, "model_copy", None)
    if callable(copier):
        return copier(update=update)
    merged = {
        key: value
        for key, value in vars(base).items()
        if not key.startswith("_")
        and isinstance(
            value, (str, int, float, bool, list, tuple, dict, set, type(None))
        )
    }
    merged.update(update)
    return SimpleNamespace(**merged)


def choose_send_queue(
    runtime: E2eRuntime,
    audit_logger: Any,
    *,
    isolation_root: str | Path | None = None,
) -> tuple[Any, str]:
    """DRY-RUN → InMemory（零真实发送路径、一张 SQLite 都不开）；
    --execute → **临时库**上的 SQLite 队列（缺省绝不与在线 bot 共用生产发送队列）。

    ``isolation_root`` 只是给测试注入 ``tmp_path`` 的口；缺省走 OS 临时根
    （``send_queue_isolation_dir``）。
    🔴 唯一例外＝``runtime.live_delivery``（命令行 ``--live-delivery``，用户 2026-10-06 裁
    「**隔离为默认＋真发要显式旗**」）：带旗才落回生产库、让在线 worker 真发。除此之外
    两态都无条件隔离，不接受「这次就写生产库」——旗不是绕过安全阀的口子，上面那两跳
    准入判定（``bot_send_queue_enabled`` 与生产路径在场）照样执法。
    """
    config = runtime.config
    if not runtime.execute:
        return InMemorySendQueue(audit_logger=audit_logger), "dry-run:in-memory"
    enabled = bool(getattr(config, "bot_send_queue_enabled", False))
    # 仍读**原配置**那枚生产路径做准入判定：部署侧没启用持久化队列 = 连生产队列本身
    # 都不存在，验收器更不该假装能走「入队后被 worker 投递」这一面（存量安全阀语义不变，
    # 锁 tests/test_e2e_acceptance.py::test_execute_requires_persistent_sqlite_queue）。
    configured_db = str(getattr(config, "bot_send_queue_db_path", "") or "").strip()
    if not enabled or not configured_db:
        raise E2eSafetyError(
            "--execute 需要持久化发送队列（BOT_SEND_QUEUE_ENABLED + "
            "BOT_SEND_QUEUE_DB_PATH），否则入队请求没有任何进程会投递。"
            "请先在 .env 启用发送队列并重启 bot。"
        )
    from plugins.bot_unified_runtime.domains.transport.sender.queue import (
        build_send_queue,
    )

    # 🔴 结构性隔离：即便上面判定用的是生产库路径，真建队列时也必须换到临时库——
    # 生产 ``wuwa_send_queue.sqlite3`` 由在线 worker 共读，验收器一旦往里入队就等于
    # 让真人群/真私聊收到测试消息（本波根治）。``build_send_queue`` 只读它拿到的
    # config 属性、不做任何路径重映射，故 ``model_copy`` 换绝对临时路径即逐字生效。
    # 🔴 上面那两跳准入判定**不因旗放宽**：没启用持久化队列就照样拒绝执行（防"假真发"）。
    if runtime.live_delivery:
        # 用户 2026-10-06 裁「A」的后半：缺省隔离，**真发要显式旗**。带旗＝直接用 config 那枚
        # 生产库路径建队列 ⇒ 在线 bot 的 send-queue worker 看得见 ⇒ 真发到群/私聊，并把行写进
        # 她的投递台账（这正是 `--live-delivery` 存在的唯一理由：验收"投递真身"没有别的替身）。
        live_queue = build_send_queue(config, audit_logger=audit_logger)
        if not isinstance(live_queue, SQLiteSendRequestQueue):
            raise E2eSafetyError(
                "--live-delivery 期望 SQLite 发送队列，实际构建出 "
                f"{type(live_queue).__name__}；拒绝执行以防假真发。"
            )
        return live_queue, f"execute:sqlite:live-production-queue:{live_queue.db_path}"

    tmp_dir = send_queue_isolation_dir(isolation_root)
    isolated = send_queue_isolation_config(config, tmp_dir)
    queue = build_send_queue(isolated, audit_logger=audit_logger)
    if not isinstance(queue, SQLiteSendRequestQueue):
        raise E2eSafetyError(
            "--execute 期望 SQLite 发送队列，实际构建出 "
            f"{type(queue).__name__}；拒绝执行以防假真发。"
        )
    return queue, f"execute:sqlite:isolated:{queue.db_path}"


def warn_live_delivery(queue_desc: str) -> None:
    """带旗时把"这一轮真发、会写生产投递台账"说到明处（用户 2026-10-06 裁 A 的披露面）。

    旗本身不改变任何链路，只改变**看得见的程度**：她要在真机测投递时才需要它，而误用它的
    代价是让真人群/真私聊收到测试消息——所以这句必须打在目标行之后、入队之前，不能只在
    末段汇总里出现。
    """
    if "live-production-queue" in str(queue_desc or ""):
        print(
            "⚠ 本轮为**真实投递**：队列指回生产库，在线 bot 的 send-queue worker 会逐条真发"
            "到上面的目标，并把每一行写进生产投递台账。不带 `--live-delivery` 就绝不会被真发。"
        )


# --------------------------------------------------------------------------
# 白名单安全阀（与 pipeline group_lists_provider 同源：运行时 store 优先）
# --------------------------------------------------------------------------


def load_group_lists(config: Any) -> dict[str, frozenset[str]]:
    settings = build_instance_settings_manager(config).get(effective_instance(config))
    lists: dict[str, frozenset[str]] = {}
    for slot in ("black1", "black2", "white1", "white2"):
        key = f"BOT_GROUP_{slot.upper()}"
        raw = settings.get(key, config) or []
        lists[slot] = frozenset(
            str(item).strip() for item in raw if str(item).strip()
        )
    return lists


def check_group_allowed(runtime: E2eRuntime, group_id: str) -> tuple[bool, str]:
    """群验收目标必须在 white1/white2（运行时 store 覆盖优先），black1/black2 直接拒绝。"""
    lists = load_group_lists(runtime.config)
    gid = str(group_id).strip()
    if gid in lists["black1"]:
        return False, f"群 {gid} 在 BOT_GROUP_BLACK1（完全静默名单），拒绝执行"
    if gid in lists["black2"]:
        return False, f"群 {gid} 在 BOT_GROUP_BLACK2，拒绝执行"
    if gid in lists["white1"]:
        return True, f"群 {gid} 在 BOT_GROUP_WHITE1"
    if gid in lists["white2"]:
        return True, f"群 {gid} 在 BOT_GROUP_WHITE2"
    reason = (
        f"群 {gid} 不在 BOT_GROUP_WHITE1/WHITE2（运行时 store 白名单），拒绝执行；"
        "先把群加入白名单（/bot runtime set BOT_GROUP_WHITE1 ...）再跑 --execute"
    )
    return False, reason


# --------------------------------------------------------------------------
# 合成 IncomingMessage（等价 @bot + 文本 的群/私聊消息）
# --------------------------------------------------------------------------


def synthesize_message(
    *,
    text: str,
    session_type: SessionType,
    target_id: str,
    sender_id: str,
    bot_id: str,
    seq: int,
) -> IncomingMessage:
    # ``seq`` 仍保留在签名里（存量调用点逐字不改、并把序号写进日志/触发文本），
    # 但**不再拿它去伪造 ``message_id``**——见下面 IncomingMessage 构造的注释。
    is_group = session_type is SessionType.GROUP
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        # 空串＝让队列按适配器选在线号；虚构哨兵会顶掉那一条腿（锁见
        # tests/test_e2e_acceptance.py::test_harness_never_hands_the_queue_an_unmatchable_bot_id）。
        bot_id=bot_id,
        session_id=(f"group_{target_id}_{sender_id}" if is_group else target_id),
        session_type=session_type,
        sender_id=sender_id,
        group_id=(target_id if is_group else None),
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        # 群里等价「@bot + 指令」，white1/white2 门均放行；私聊天然 mentions。
        mentions_bot=True,
        # 🔴 绝不伪造来件号（2026-10-07 本波）。旧写法 ``message_id=f"e2e-{seq}-{ts}"``
        # 造了一枚看着像真号的假 id：管线把它原样抄进 ``SendRequest.origin_message_id``
        # （pipeline 三处），而真身尺 ``transport/sender/nonebot.py::_MailRedriveEvent``
        # 读的正是 ``origin_message_id`` 去盖邮件的 ``In-Reply-To`` / ``References``
        # 线程头——生产里这是**唯一**的引用/回复把手来源。验收器没有真来件可指，
        # 盘上实据即那批 ``"origin_message_id":"e2e-4-…"` 的 e2e 行落进了发送面。
        # 正解＝验收器**不带引用**发（``message_id`` 留 None ⇒ ``origin_message_id=None``
        # ⇒ ``_build_mail_reply_message`` 的 ``if message_id:`` 自然跳过线程头），
        # 而不是「随手编一个」。生产零变化：真人真事仍由摄取层填真实号、照旧引用/回复。
        # 锁＝tests/test_e2e_acceptance_queue_isolation.py::
        # test_harness_payload_carries_no_reply_reference。
        message_id=None,
    )


# --------------------------------------------------------------------------
# 验收矩阵
# --------------------------------------------------------------------------


@dataclass
class MatrixItem:
    key: str
    label: str
    capability_id: str
    build: Callable[[E2eRuntime], Callable[[IncomingMessage, BotDecision], CapabilityResult]]
    text: Callable[[E2eRuntime], str] | str
    note: str = ""
    # 回执断言（可省）：入参 ItemOutcome，返回空串=PASS、非空=失败原因。
    # None=该检查项不做断言（2026-09-13 之前的存量项全部保持 None）。
    expect: Callable[[ItemOutcome], str] | None = None

    def trigger_text(self, runtime: E2eRuntime) -> str:
        return self.text(runtime) if callable(self.text) else self.text


def _text_capability(
    runtime: E2eRuntime, *, body: str = "", text_parts: list[str] | None = None
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """文本直发能力：镜像 __init__._send_text_through_unified_pipeline 的内联能力。"""

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.text",
            kind="text",
            body=body,
            text_parts=text_parts,
            audit_tags=["e2e_acceptance", "unified_text_reply"],
        )

    return capability


def _long_text_body() -> str:
    lines = [
        f"E2E 长文本样例 第 {index:02d} 行：守岸人在此待命，行号与内容均为确定性生成，"
        "用于观察发送链路对多行长文本的切分/合并转发行为。"
        for index in range(1, 41)
    ]
    return "\n".join(lines)


def _help_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    config = runtime.config
    render_backend = runtime.render_backend

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return build_help_result(
            request_id=message.request_id,
            query="",
            is_admin=False,
            render_backend=render_backend,
            card_dir=str(
                getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"
            ),
            bot_name=_bot_self_name(runtime),
            bot_avatar_url="",
            accent_color=str(getattr(config, "bot_help_card_color", "") or ""),
        )

    return capability


def _music_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    config = runtime.config
    mode = (
        runtime.runtime_settings.get("BOT_MUSIC_MODE", config)
        or getattr(config, "bot_music_default_mode", "card+voice+link")
    )
    candidates_enabled = bool(getattr(config, "bot_music_candidates_enabled", False))
    capability = build_music_capability(
        config,
        default_mode=mode,
        request_store=None,  # 点歌分析埋点（可选旁路存储），验收脚本不写。
        candidate_providers=(
            music_candidate_providers(build_cookie_provider(config))
            if candidates_enabled
            else None
        ),
        render_backend=runtime.render_backend,
    )
    return capability


def _affinity_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    # 与 bot 同一好感度库（build_character_affinity_store 内部含
    # bot_affinity_enabled 开关，关闭时返回 None → 能力层给降级文案）。
    # store 构造只做幂等 DDL（CREATE TABLE IF NOT EXISTS），快照为只读。
    from plugins.bot_unified_runtime import build_character_affinity_store

    return build_affinity_capability(
        runtime.config,
        affinity_store=build_character_affinity_store(runtime.config),
        render_backend=runtime.render_backend,
    )


def _identity_dry_run_dir() -> Path:
    """DRY-RUN 称谓自助的**临时库根**（OS 临时目录：不在源码树、不在 ``ChatBot_Runtime``）。

    为什么需要它（2026-10-06）：`/bot identity set-name` 的能力体会真写
    ``AddressingPreferenceStore``。群侧命令在册门（``f3f177a3``，2026-10-01）今天在
    未在册群上把它拦住了——那是**恰好**拦住，不是设计保证：换一枚在册群跑 DRY-RUN，
    或改走私聊（私聊不受群门约束），就会在「只验形状不发」的模式下动到真实库。
    硬红线是「DRY-RUN 绝不写她的生产偏好库」，所以这一面必须结构性成立，
    不能靠群号碰巧未在册。

    固定名而非 ``mkdtemp``：``set-name`` 与 ``unset-name`` 两项要在**同一本**临时库里
    才验得出成对语义（各建一本的话 unset 永远只会看到「还没有设置过」）。
    ``--execute`` 不走这里——真机验收要落的正是真实库（净效果由成对项清零）。
    """
    root = Path(tempfile.gettempdir()) / "e2e-identity-dryrun"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _identity_preference_capability(
    runtime: E2eRuntime, *, command_text: str
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """镜像 __init__ `/bot identity` 分支 + runtime_admin 对四个自助子命令
    （set-name/set-gender/unset-name/unset-gender）管理员门前的拦截转发
    （echo.build_identity_preference_result）。写 AddressingPreferenceStore：
    **DRY-RUN 写临时库**（``_identity_dry_run_dir``，生产库零字节），
    ``--execute`` 才写真实库（与 bot 同库，data/ 相对路径经 runtime_paths 落运行区）；
    验收矩阵里 set-name 与 unset-name 成对出现，净效果为零。"""
    config = runtime.config
    if not runtime.execute:
        # 复用文件里既有那把尺（把「会被写到的那两本库」改指临时目录的单一读点），
        # 不另抄一份键名清单，免得长第二套重定向。
        config = narration_probe_config(config, _identity_dry_run_dir())

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
            build_identity_preference_result,
        )

        return build_identity_preference_result(
            config,
            request_id=message.request_id,
            sender_id=str(message.sender_id or ""),
            group_id=str(message.group_id or ""),
            command_text=command_text,
        )

    return capability


def _content_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    config = runtime.config
    parse_history_store = None
    if runtime.execute:
        from plugins.bot_unified_runtime.domains.link_parse.support.parse_history import (
            build_parse_history_store,
        )

        parse_history_store = build_parse_history_store(config)
    return build_content_capability(
        config,
        parse_history_store=parse_history_store,
        # 下载/媒体分析为可选旁路：验收关注解析卡主链路，不拖入视频下载。
        downloader=None,
        render_backend=runtime.render_backend,
        card_dir=str(
            getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"
        ),
        bot_avatar_url="",
    )


def _meme_library_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """镜像 __init__ 表情收库装配：MemeLibraryStore（运行区库；pick/stats 只读）
    + build_meme_library_capability（mood_valence_fn 不接=中性档）。
    BOT_MEME_LIBRARY_ENABLED 未启用时给降级文案（与生产不注册 handler 同语义）。"""
    config = runtime.config
    if not bool(getattr(config, "bot_meme_library_enabled", False)):
        return _text_capability(
            runtime,
            body="E2E：BOT_MEME_LIBRARY_ENABLED 未启用，表情收库链路按生产语义跳过。",
        )
    store = MemeLibraryStore(
        str(
            getattr(config, "bot_meme_library_db_path", "data/meme_library.sqlite3")
            or ""
        ),
        prefer=list(getattr(config, "bot_meme_library_prefer", []) or []),
    )
    return build_meme_library_capability(store, config)


def _router_gated_capability(
    runtime: E2eRuntime,
    *,
    detector: Callable[[str], bool],
    domain_builder: Callable[
        [E2eRuntime],
        Callable[[IncomingMessage, BotDecision], CapabilityResult],
    ],
    domain_label: str,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """劫持守卫负样本专用：镜像 base_router 分流语义。

    真机链路里劫持守卫生在路由层（base_router 用 is_* 检测器定 RouteKind），
    本脚本绕过路由直挂能力，故用与路由同源的 detector 复现分流：
    命中 → 原样委托真实领域能力（守卫被改坏时仍可观察真实形态）；
    不命中 → 让路（生产由 chat/其他域接管，验收用确定性占位文本）。
    注意：负样本不能直喂领域能力——stocks/divination 的能力体对未命中文本
    会走 NON_PUBLIC/兜底分支（如 resolve_company_query('openai是什么')=OPENAI、
    parse_divination_intent 对算命句返回 bazi 意图，均实跑核实），
    与生产「根本不进该能力」语义不符。"""
    domain_capability = domain_builder(runtime)

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        if detector(str(message.plain_text or "")):
            return domain_capability(message, decision)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.text",
            kind="text",
            body="E2E 守卫观察：该消息未命中本域触发词，生产语义=让路（chat/其他域接管）。",
            audit_tags=["e2e_acceptance", "hijack_guard_negative"],
        )

    return capability


def _decision_query_capability(
    runtime: E2eRuntime, *, actor_roles: list[str]
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """镜像 __init__ `/bot decision` 出口（生产 elif 接线待 §26.10 登记的
    campus 席释放后补贴）：显式注入 actor_roles——矩阵绕过路由层，拿不到
    从 sender_id 解析的角色，故管理员/普通成员两态各建一个闭包。sink 走
    缺省（decision/trace 默认 sink：recent() 只读 URI 查询，绝不创建库，
    缺库回落热缓冲 → 「暂无记录」同为合法回执）。"""

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return build_decision_query_result(
            request_id=message.request_id,
            actor_roles=actor_roles,
        )

    return capability


def _group_failure_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """A-19 正向观察：合成「能力执行失败错误态」结果（与生产失败能力同形：
    operational_issue 非 pipeline_busy + SILENT_AUDIT 空正文），管线在群聊/
    频道补一句 GROUP_FAILURE_ACK_TEMPLATES 池内短句。零外呼、零落盘。"""

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.selftest-fail",
            kind="error",
            body="",
            send_policy=SendPolicy.SILENT_AUDIT,
            operational_issue=OperationalIssue(
                stage="capability",
                kind="capability_failure",
                retryable=False,
                debug_id=message.debug_id,
                safe_summary="e2e A-19 capability failure",
            ),
            audit_tags=["e2e_acceptance", "a19_group_failure_ack"],
        )

    return capability


def _pipeline_busy_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """A-19 负样本：超载快败（pipeline_busy）按设计静默——镜像
    pipeline._pipeline_busy_result 的形态，验证「限流/安静/超载拦截族
    零反馈」的降频设计语义未被降级池破坏。"""

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.selftest-busy",
            kind="error",
            body="",
            send_policy=SendPolicy.SILENT_AUDIT,
            operational_issue=OperationalIssue(
                stage="runtime",
                kind="pipeline_busy",
                retryable=True,
                debug_id=message.debug_id,
                safe_summary="pipeline_busy",
            ),
            audit_tags=["pipeline_busy:v1"],
        )

    return capability


# --------------------------------------------------------------------------
# 回执断言（2026-09-13 批次：作用于入队 SendRequest 层，DRY-RUN/--execute 同语义；
# 渲染形态对照 renderer：能力 images 非空 ⇔ content_type=mixed + 图片部件）
# --------------------------------------------------------------------------


def _expect_preamble(outcome: ItemOutcome) -> tuple[SendRequest | None, str]:
    if outcome.error:
        return None, outcome.error
    if outcome.send_request is None:
        return None, "无入队请求（能力可能被静默/拦截，回执状态见上）"
    return outcome.send_request, ""


def _media_part_count(send_request: SendRequest | None) -> int:
    parts = send_request.content.content_ref if send_request is not None else None
    if not isinstance(parts, dict) or not isinstance(parts.get("parts"), list):
        return 0
    return sum(
        1
        for part in parts["parts"]
        if isinstance(part, dict) and str(part.get("type", "")) != "text"
    )


def expect_stock_card(outcome: ItemOutcome) -> str:
    """⑫ 英伟达股价 → 期望个股卡（images 非空或 kind=mixed 的入队等价形态）。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    media = _media_part_count(request)
    if request.content.content_type == "mixed" or media >= 1:
        return ""
    return (
        f"期望个股卡（content_type=mixed 或含图片部件），实际 "
        f"content_type={request.content.content_type} media={media}"
        "（多为行情源失败或渲染后端不可用时的文本降级）"
    )


# 守卫禁词：出现即视为产生了股价/OHLC 内容（估值口径说明文本不含这些词，
# 含「OpenAI 目前未上市…／最近公开估值：约 … 亿美元／来源 …」）。
_STOCK_CONTENT_MARKERS = ("现价", "KDJ", "收盘序列", "涨跌幅", "开 ", "OHLC")


def expect_nonpublic_guard(outcome: ItemOutcome) -> str:
    """⑫ OpenAI 估值 → 非上市守卫：不得产生任何股价/OHLC 内容或卡图。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    media = _media_part_count(request)
    if media:
        return f"守卫失败：产生了 {media} 个媒体部件（非上市公司不得出任何行情卡图）"
    text = request.content.text_fallback
    hits = [marker for marker in _STOCK_CONTENT_MARKERS if marker in text]
    if hits:
        return f"守卫失败：文本命中股价/OHLC 形态 {hits}"
    if "openai" not in text.lower():
        return "守卫失败：回复未指向 OpenAI（疑似误路由）"
    return ""


def expect_fx_panel_card(outcome: ItemOutcome) -> str:
    """⑬ 汇率 → 期望面板卡（mixed + 图片部件）+ 主要货币面板文本。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    text = request.content.text_fallback
    if "拉不到" in text:
        return "汇率快照拉取失败（上游不可用），未产出面板"
    media = _media_part_count(request)
    if request.content.content_type == "mixed" and media >= 1:
        return ""
    return (
        f"期望汇率面板卡，实际 content_type={request.content.content_type} "
        f"media={media}（渲染后端不可用时会文本降级，真机应出卡）"
    )


def expect_fx_converted(outcome: ItemOutcome) -> str:
    """⑬ 100日元换多少人民币 → 期望定向换算结果（≈ 折算行，JPY→CNY）。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    text = request.content.text_fallback
    if "拉不到" in text:
        return "汇率快照拉取失败（上游不可用），未产出换算"
    if "≈" in text and ("人民币" in text or "CNY" in text):
        return ""
    return (
        "期望定向换算结果（形如 100日元 ≈ X 人民币），"
        f"实际预览：{_flatten(text)[:120]!r}"
    )


def expect_divination_two_state(outcome: ItemOutcome) -> str:
    """⑭ 占卜 → 出卡（mixed）或纯文本二态皆可；断言本身不抛异常。

    纯文本态在入队层可能是 text，也可能是 pipeline 对超阈值长文的
    合并转发形态（forward，text_fallback 保留全文）——实测 192 字卦文
    即转 forward，两者同为「无卡图纯文本」，均算通过。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    if request.content.content_type not in ("mixed", "text", "forward"):
        return (
            "期望 mixed/纯文本（含合并转发形态）二态之一，实际 "
            f"content_type={request.content.content_type}"
        )
    if not request.content.text_fallback.strip():
        return "正文为空"
    return ""


def expect_identity_set_confirmed(outcome: ItemOutcome) -> str:
    """⑮ /bot identity set-name → 期望「已记下」确认回复。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    text = request.content.text_fallback
    if "已记下" in text:
        return ""
    return f"期望「已记下」确认回复，实际：{_flatten(text)[:120]!r}"


def expect_identity_unset_confirmed(outcome: ItemOutcome) -> str:
    """⑮ /bot identity unset-name → 清理确认（已清除/本就没有均算达成）。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    text = request.content.text_fallback
    if "已清除" in text or "还没有设置过" in text:
        return ""
    return f"期望清理确认（已清除/本就没有），实际：{_flatten(text)[:120]!r}"


def expect_chat_fallthrough(
    *, markers: tuple[str, ...], domain_label: str
) -> Callable[[ItemOutcome], str]:
    """劫持/排除守卫负样本通用断言：必须落纯文本（零卡图），
    且正文不含任何领域能力内容形态（markers 取自领域能力产出文案特征词，
    已逐一对照让路占位文本排除误伤）。"""
    def expect(outcome: ItemOutcome) -> str:
        request, reason = _expect_preamble(outcome)
        if reason:
            return reason
        media = _media_part_count(request)
        if media:
            return f"守卫失败：产生了 {media} 个媒体部件（{domain_label}不应被触发）"
        if request.content.content_type not in ("text", "forward"):
            return (
                "守卫失败：期望纯文本让路落点，实际 content_type="
                f"{request.content.content_type}"
            )
        text = request.content.text_fallback
        hits = [marker for marker in markers if marker in text]
        if hits:
            return f"守卫失败：文本命中{domain_label}内容形态 {hits}"
        return ""

    return expect


# 表情收库 pick 的三态确定性文案（出图 mixed 的 text_fallback 也含首句）。
_MEME_PICK_TEXTS = ("给你偷来一张表情", "表情库还是空的", "冷却中")


def expect_meme_library_pick(outcome: ItemOutcome) -> str:
    """表情收库（steal meme / meme random）→ 三态皆算真实行为：
    出图（mixed）/空库文案/会话冷却文案；落到其他文案才算异常。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    text = request.content.text_fallback
    if any(token in text for token in _MEME_PICK_TEXTS):
        return ""
    if request.content.content_type == "mixed":
        return ""
    return (
        "期望表情收库 pick 三态之一（出图/空库/冷却），"
        f"实际：{_flatten(text)[:120]!r}"
    )


def expect_decision_query_admin(outcome: ItemOutcome) -> str:
    """⑥§26.2 /bot decision（管理员）→ 期望「决策影子痕迹」文本回执
    （「暂无记录」与逐条列表二态皆算达成：影子模式 legacy_only 下无痕迹属预期）。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    if request is None:
        return "无入队请求（能力可能被静默/拦截，回执状态见上）"
    text = request.content.text_fallback
    if "决策影子痕迹" in text:
        return ""
    return f"期望决策影子痕迹摘要（暂无记录/逐条列表），实际：{_flatten(text)[:120]!r}"


def expect_admin_gate_refusal(outcome: ItemOutcome) -> str:
    """⑥§26.2 同命令普通成员 → 期望 ADMIN_GATE_TEMPLATES 池温和拒绝，
    且不得泄漏任何查询结果形态（拒绝与查询是两条互斥路径）。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    if request is None:
        return "无入队请求（能力可能被静默/拦截，回执状态见上）"
    text = request.content.text_fallback
    if "管理员" not in text:
        return f"期望管理员门温和拒绝话术（ADMIN_GATE_TEMPLATES 池），实际：{_flatten(text)[:120]!r}"
    leaks = [
        token
        for token in ("决策影子痕迹：", "暂无记录", "（新→旧）")
        if token in text
    ]
    if leaks:
        return f"拒绝话术泄漏了查询结果形态 {leaks}"
    return ""


#: 群侧命令「按设计被拦」的两枚门名（真身＝``policy/gate.py`` 里 ``_denied`` 的 reason，
#: 引入笔 ``f3f177a3``（2026-10-01，HEAD 祖先））：
#:   · ``command_group_unlisted`` —— 命令态的群必须在 BOT_GROUP_* 任一册里（E05 缺口一）；
#:   · ``group_white2_need_trigger`` —— 白名单2 群要真 @ 它或带显式命令。
#: 这两枚是**门禁的名字**，不是放宽判据：门若改名、新增第三枚拦命令的门、或本轮其实
#: 是被安静时间/限流/黑名单拦下 ⇒ 下面那把尺当场报红并回显实际留痕（要的就是这个响）。
#:
#: 🔴 本验收面的一个已知失真（2026-10-06 现算发现，未获授权所以**没动**）：
#: ``build_pipeline`` 只给管线传了 ``group_command_prefix``，**没传** 生产 ``__init__``
#: 传的那五枚名单输入（``group_black1/2``＋``group_white1/2``＋``group_lists_provider``，
#: 真身见 ``plugins/bot_unified_runtime/__init__.py`` 的管线装配段）。后果＝
#: **验收面里任何群都算未在册**，所以群侧斜杠命令在这里恒被 ``command_group_unlisted``
#: 拦下——连确在 BOT_GROUP_WHITE1 的验收群也不例外（同一脚本的安全阀会打印
#: 「群 <id> 在 BOT_GROUP_WHITE1」，与这条拦截同时出现，就是证据）。
#: 于是本把尺的「按设计被拦」这一轨证明的是**门禁形状**（拦了必须有门名、可归因），
#: 不是「这个群真的不在册」。要验真落群的那一面：走私聊 ``--target-user``，或先给
#: ``build_pipeline`` 补上那五枚输入（那是改门禁输入、会另放出「个人输出不出群」
#: ``move_private`` 的红——管线至今没有 MOVE_PRIVATE 消费侧，转私聊从未实装）。
_COMMAND_GATE_DENIALS: tuple[str, ...] = (
    "command_group_unlisted",
    "group_white2_need_trigger",
)


def expect_command_after_group_gate(
    positive: Callable[[ItemOutcome], str],
) -> Callable[[ItemOutcome], str]:
    """群侧斜杠命令的双形断言：与门禁同形，且不撒谎。

    - **入队了** → 原样跑 ``positive``，一条字都不改。这四枚的正跑面今天只在私聊
      （``--target-user``）出现：它们的回执 ``privacy_level=personal``，群侧即使在册
      也会被 reviewer 的「个人输出不出群」改道 ⇒ 那种红**留着**（真问题，不吞）。
    - **没入队** → 只接受「按设计拦」这一种形状：``state=blocked``、
      ``transport=policy``、且本轮审计留痕点名 ``_COMMAND_GATE_DENIALS`` 之一。
      拦得没有原因可查＝判红（「随便拦」不算通过）。
    - 其余形态（被别的门拦、skipped、有回执却查无请求、审计读口形变）→ 判红并回显
      实际 state/transport/留痕，便于当场归因。

    本把尺写死的是「未在册群里的群侧命令必然被拦、且拦得有原因可查」，
    不是「随便拦都算过」：原因不在那两枚门名之内就红。
    """

    def expect(outcome: ItemOutcome) -> str:
        if outcome.error:
            return outcome.error
        if outcome.send_request is not None:
            return positive(outcome)
        state = outcome.receipt.state.value if outcome.receipt is not None else "无回执"
        transport = (
            outcome.receipt.transport if outcome.receipt is not None else "无回执"
        )
        if outcome.audit_reasons is None:
            return (
                f"state={state} transport={transport}：本轮审计留痕取不到（读口形变）"
                "＝判红，不静默当「没原因」"
            )
        trail = _flatten("; ".join(outcome.audit_reasons))[:200]
        if state != "blocked" or transport != "policy":
            return (
                "无入队请求且回执不是 blocked/policy"
                f"（state={state} transport={transport}）；本轮审计留痕：{trail!r}"
            )
        hit = [
            token
            for token in _COMMAND_GATE_DENIALS
            if any(token in reason for reason in outcome.audit_reasons)
        ]
        if not hit:
            return (
                "命令被门禁拦下，但原因不是两枚在册/触发门之一（拦得查不到原因＝判红）；"
                f"本轮审计留痕：{trail!r}"
            )
        return ""

    return expect


def expect_group_failure_ack(outcome: ItemOutcome) -> str:
    """⑰A-19 正向：群聊会话能力失败应补一句池内降级短句（入队能力
    bot.group_failure_notice）。私聊按设计不覆盖（chat 私聊失败另有守岸人
    话术池）→ 私聊会话无断言语义直接 PASS。"""
    if outcome.session_type == SessionType.PRIVATE.value:
        return ""
    request, reason = _expect_preamble(outcome)
    if reason:
        return (
            reason
            + "（群聊应补一句池内降级短句；300s 会话节流窗内重跑会静默——"
            "等窗口过期或换 white1 群冷启动重跑观察）"
        )
    if request is None:
        return "无入队请求（能力可能被静默/拦截，回执状态见上）"
    if request.capability_id != "bot.group_failure_notice":
        return (
            "期望 bot.group_failure_notice 降级件，实际 capability_id="
            f"{request.capability_id}"
        )
    if request.content.text_fallback in GROUP_FAILURE_ACK_TEMPLATES:
        return ""
    return (
        "降级短句不在 GROUP_FAILURE_ACK_TEMPLATES 池内："
        f"{_flatten(request.content.text_fallback)[:120]!r}"
    )


def expect_pipeline_busy_silent(outcome: ItemOutcome) -> str:
    """⑰A-19 负样本：超载快败必须零反馈——无任何入队请求（拦截族静默
    语义不变）；回执应为 skipped/blocked 静默态。群/私聊两会话同语义。"""
    if outcome.error:
        return outcome.error
    if outcome.send_request is not None:
        return (
            "超载快败应保持静默（零入队请求），实际入队："
            f"{_flatten(outcome.send_request.content.text_fallback)[:120]!r}"
        )
    if outcome.receipt is not None and outcome.receipt.state.value not in (
        "skipped",
        "blocked",
    ):
        return f"期望 skipped/blocked 静默回执，实际 state={outcome.receipt.state.value}"
    return ""


# --------------------------------------------------------------------------
# 叙述授予波判定（席 e2e2，2026-10-05）：六枚**纯谓词**
#
# 契约与上面 `expect_*` 同族：返回空串＝PASS，非空＝失败原因。判据一律住在被测件里
# （`runtime/content_route.py` / `capabilities/chat.py` / `runtime/intimate_control.py`
# / `domains/render/reviewer.py` / `transport/sender/{onebot,queue}.py`），这里只调用、
# 不复制一份 ⇒ 长不出第二把尺。**每枚都可能红**（离线锁：
# `tests/test_e2e_acceptance_narration.py`，逐枚注毒给过红线）。
#
# 离线边界（DRY-RUN 零发送、零生产写）：
# - ①② 纯函数；⑥ 的嘴形腿是只读 AST、落账腿用 `%TEMP%` 下的临时发送队列库；
# - ③⑤ 要写永久策略行与亲密钉 ⇒ `narration_probe_config` 把那两本库
#   （addressing_preferences / reply_policy）改指 `%TEMP%`，生产库零字节（规则 2）；
# - ④ 走真实 RuntimePipeline + InMemory 队列 + InMemory 审计（`group-failure-ack`
#   同一先例，零 transport）。
# 只有现网才看得见的那半面（真实 OneBot 退码、真实模型肯不肯写动作）在各 item 的
# ``note`` 里标 `requires restart` / `requires --execute`，判定本身不假装验过它。
# --------------------------------------------------------------------------

#: 群内涂销用例：干净正文两头 + 中间一枚命中词面。命中词面**刻意是清单里的原文**，
#: 清单若换词，本用例会在「命中词面仍出门」那一行报红（＝用例要跟改，不是漏网）。
_GROUP_SCRUB_CLEAN_HEAD = "例会议程照旧：上午对方案、下午过预算。"
_GROUP_SCRUB_CLEAN_TAIL = "散会后我把纪要发到群里，不在这里贴。"
_GROUP_SCRUB_SPAN = "R-18"
_GROUP_SCRUB_BODY = (
    f"{_GROUP_SCRUB_CLEAN_HEAD}你要的那段 {_GROUP_SCRUB_SPAN} 描写我不会写。"
    f"{_GROUP_SCRUB_CLEAN_TAIL}"
)

#: 动作括号用例的模型回话替身（离线静态 provider 的原样输出）。
_ACTION_BRACKET_REPLY = "（她把台灯拧暗了一格）嗯，你说，我在听。"
_ACTION_BRACKET_OPEN = "（"


def narration_probe_dir() -> Path:
    """判定用的临时数据根（OS 临时目录：不在仓库内、不在 `ChatBot_Runtime` 下）。"""
    return Path(tempfile.mkdtemp(prefix="e2e-narration-"))


def narration_probe_config(base: Any, tmp_dir: Path) -> Any:
    """照抄生产 config，只把**会被写到的那两本库**改指临时目录。

    亲密钉的跨重启标记落 `addressing_preferences`（D-1 那节），永久策略落
    `reply_policy` ⇒ 这两枚路径不挪就直接写生产库。用 `model_copy` 而不是新建
    ``Config(...)``：后者不读环境变量、缺省 ``bot_runtime_data_dir="data"`` 会把路径
    折回源码树（`tests/test_e2e_acceptance.py::_runtime_stub` 记过这条后果链）。
    """
    update: dict[str, object] = {
        "bot_addressing_preferences_db_path": str(
            tmp_dir / "addressing_preferences.sqlite3"
        ),
        "bot_reply_policy_db_path": str(tmp_dir / "reply_policy.sqlite3"),
        "bot_reply_policy_enabled": True,
    }
    copier = getattr(base, "model_copy", None)
    if callable(copier):
        return copier(update=update)
    merged = {
        key: value
        for key, value in vars(base).items()
        if not key.startswith("_") and isinstance(value, (str, int, float, bool, list, tuple, dict, set, type(None)))
    }
    merged.update(update)
    return SimpleNamespace(**merged)


def _axis_probe_config(base: Any, tmp_dir: Path) -> Any:
    """② 的轴判定专用 config：`narration_probe_config` 之上把**四枚名单清空**。

    为什么要清空：(c)(d) 用的是合成会话键（`e2e-narration-tier-*`），它们不在现网私聊
    白名单里 ⇒ `eligible=False` ⇒ 甲那一腿永远造不出来，验收面就会在 DRY-RUN 里报一枚
    与裁定无关的红（假红）。清空后私聊门＝「白名单空＝默认放开」（既有裁定），判定只
    依赖被测的那条优先级链本身。写库路径仍指 `%TEMP%`，生产库零字节。
    """
    staged = narration_probe_config(base, tmp_dir)
    update = {
        "bot_content_route_private_whitelist": [],
        "bot_content_route_private_blacklist": [],
        "bot_content_route_group_whitelist": [],
        "bot_content_route_group_blacklist": [],
    }
    copier = getattr(staged, "model_copy", None)
    if callable(copier):
        return copier(update=update)
    merged = {
        key: value
        for key, value in vars(staged).items()
        if not key.startswith("_")
    }
    merged.update(update)
    return SimpleNamespace(**merged)


def _audit_records_for(logger: Any, request_id: str) -> list[Any] | None:
    """从进程内审计仓库取某轮的全部记录；取不到返回 ``None``（＝判定红，不是静默跳过）。

    三种读法依次退让（按 request_id 过滤 → 全表 → 裸 deque）；都不通才算读口形变。
    """
    reader = getattr(logger, "list_records", None)
    records: Any = None
    if callable(reader):
        try:
            records = list(reader(request_id=request_id))
        except Exception:  # noqa: BLE001 - 签名不收过滤参数：退全表读法
            try:
                records = list(reader())
            except Exception:  # noqa: BLE001 - 全表读法也不通：退裸容器
                records = None
    if records is None:
        container = getattr(logger, "_records", None)
        if container is None:
            return None
        records = list(container)
    return [
        record
        for record in records
        if str(getattr(record, "request_id", "")) == request_id
    ]


def check_narration_grant_is_source_scoped() -> str:
    """① 叙述授予**按来源**：人工推动的那几支才给，自动回落两支只说话。

    只判「哪些必须给／哪些必须不给」，不判集合的大小 ⇒ 席 grpfix 那一路再加第四枚
    来源（描写档 `scene`）时本用例照旧成立。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        content_route as cr,
    )

    registered = {
        value
        for name, value in vars(cr).items()
        if name.startswith("INTIMATE_SOURCE_") and isinstance(value, str)
    }
    stray = sorted(set(cr._INTIMATE_NARRATION_SOURCES) - registered)
    if stray:
        return f"授予集里有未登记的来源字面量 {stray}（拼错的来源＝静默不授予）"
    ungranted: list[str] = []
    for name in (
        "INTIMATE_SOURCE_MANUAL",
        "INTIMATE_SOURCE_ADMIN_PIN",
        "INTIMATE_SOURCE_CONTENT_SIGNAL",
        # 第四枚授予来源＝描写档持久钉（2026-10-04 裁定 G-2：`scene` 并进**这同一把**
        # 尺，不许长第二张成员表）。它今天只被上面那道「未登记字面量」的腿间接看着：
        # 把这一枚从集合里摘掉 ⇒ `grants_intimate_narration("narration_pin")` 静默 False
        # ⇒ 普通模式钉过 scene 的人拿不到铺写，而本项照绿——那就是假绿，所以点名要它。
        "INTIMATE_SOURCE_NARRATION_PIN",
        # 席 e2ealign（2026-10-05）：H-1＝甲之后「亲手开亲密」这一支的来源串会被描写
        # 轴原样转述（`content_route.py:1824`），所以它必须在授予面上——上面四枚缺一
        # 都等于把某一类「人亲手推动」静音掉。
    ):
        value = getattr(cr, name, None)
        if value is None:
            return f"来源常量缺席：{name}（判据换了名字，验收面要跟改）"
        if not cr.grants_intimate_narration(value):
            ungranted.append(f"{name}={value!r}")
    if ungranted:
        return "人工推动的来源没拿到叙述授予 " + ", ".join(ungranted)
    none_source = getattr(cr, "INTIMATE_SOURCE_NONE", "")
    denied = [
        cr.INTIMATE_SOURCE_MASTER_LOVE,
        cr.INTIMATE_SOURCE_AFFINITY,
        none_source,
        "",
        "   ",
        "not_a_registered_source",
    ]
    leaked = sorted({value for value in denied if cr.grants_intimate_narration(value)})
    if leaked:
        return f"自动回落/未知来源拿到了叙述授予 {leaked}（回落腿本该只说话）"
    return ""


#: 非授予腿要穷举的问题样例（判题型用，覆盖各 intent/category 分支）。
_TOP_TIER_PROBE_QUESTIONS: tuple[str, ...] = (
    "",
    "今天天气怎么样",
    "介绍一下守岸人",
    "LPR 又降了吗",
    "嗯？在吗",
    "刚才那个报错怎么排查",
    "写一段守岸人与漂泊者的场景",
)


def check_top_reply_tier_needs_the_grant(
    base_config: Any = None, tmp_dir: Path | None = None
) -> str:
    """② 顶格档（今天＝「铺写」）只有授予腿走得到：矩阵里没有任何一格指向它。

    构造性证明、不按名字断言：
    (a) `REPLY_TIER_MATRIX` 逐格 + 题型×配置档穷举 + 无正文兜底映射 ⇒ 全部 ≠ 顶格档；
    (b) 授予腿 `intimate_reply_length_tier` 每一枚配置档都必须 == 顶格档（顶格档是
        活档，不是死档——它一旦到不了同样是回归）。
    (c) H-1＝甲（2026-10-04 晚裁定「开'亲密'的话，就给 scene 场景」）：**亲手把亲密档
        推上去的那一轮**，即便这个人从没有在描写轴上说过一个字，描写轴的读数也必须是
        `scene` 且过唯一那把尺，长度于是落到顶格档。甲改的是「哪些来源算亲手推动」，
        不是「只有授予腿走得到」——所以 (a)(b) 一字不放宽，本腿只把「到得了」那一半
        补上：少了它，「开了亲密仍只说话」那一枚改前形态在验收面是全绿的。
    (d) 负对照：`master_love`／`affinity_tier` 两支**只给档、不给描写**（2026-10-04 裁定
        原文），自动腿推上去的亲密读数必须仍是 `speech` 且不过尺——否则 (c) 就是「凡亲密
        皆铺写」的第二次放宽，而那正是她 2026-09-28 原话要防的「换个档文风全变」。

    🔴 本函数**一次都不写描写钉**：(c)(d) 都靠引擎自己的显式开档（`apply_manual`）与注入
    缝同一个读数口（`resolve_intimate_context`）拿轴值，钉的键形（I-2 要改成
    平台·会话·人 三元组）因此**不参与**本判定，换群要不要重开都不影响这里绿不绿。
    写盘只可能落在 D-1 显式开档标记那一格，`narration_probe_config` 已把它指到 `%TEMP%`。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        content_route as cr,
    )

    top = str(getattr(chat, "_REPLY_TIER_TOP_ID", "") or "")
    if not top or top not in chat.REPLY_LENGTH_TIERS:
        return f"顶格档 {top!r} 不在 REPLY_LENGTH_TIERS 里（派生尺与登记表不同源）"
    for qtype, row in sorted((chat.REPLY_TIER_MATRIX or {}).items()):
        for mode, tier_id in sorted((row or {}).items()):
            if str(tier_id) == top:
                return (
                    f"REPLY_TIER_MATRIX[{qtype}][{mode}] 指向顶格档 {top}："
                    "全局长度被吃进铺写（矩阵本不该有任何一格指向它）"
                )
    for mode in sorted(chat.REPLY_DETAIL_MODES):
        for qtype in sorted(chat.REPLY_QUESTION_TYPES):
            if chat.select_reply_length_tier(detail_mode=mode, question_type=qtype) == top:
                return f"select_reply_length_tier({mode}, {qtype}) 到得了顶格档（非授予腿漏）"
        for question in _TOP_TIER_PROBE_QUESTIONS:
            if chat.resolve_reply_length_tier(mode, question) == top:
                return (
                    f"resolve_reply_length_tier({mode}, {question!r}) 到得了顶格档"
                    "⇒ 没拿到授予的人也被铺写"
                )
            reached = chat.intimate_reply_length_tier(mode, question)
            if str(reached) != top:
                return (
                    f"intimate_reply_length_tier({mode}, {question!r}) 只到 {reached!r}，"
                    f"到不了顶格档 {top} ⇒ 授予腿断，铺写成了死档"
                )

    # ---- (c) H-1＝甲：亲手开亲密 ⇒ 描写轴 scene ⇒ 顶格档
    probe_dir = tmp_dir or narration_probe_dir()
    cfg = _axis_probe_config(
        base_config if base_config is not None else SimpleNamespace(), probe_dir
    )
    manual_key = "e2e-narration-tier-manual"
    if not cr.SHARED_CONTENT_ROUTE_ENGINE.apply_manual(
        manual_key, "intimate", cfg, source=cr.INTIMATE_SOURCE_MANUAL
    ):
        return (
            "显式开亲密（apply_manual→manual_command）没生效 ⇒ 判不了甲那一腿"
            "（总闸/键形/TTL 哪一道门改了？本项不静默通过）"
        )
    manual_ctx = cr.resolve_intimate_context(
        cr.SHARED_CONTENT_ROUTE_ENGINE,
        session_type="private",
        session_key=manual_key,
        sender_id=manual_key,
        config=cfg,
    )
    if not bool(manual_ctx.get("eligible", False)):
        return (
            "判定用的私聊会话没过 content_route 准入门（eligible=False）⇒ 甲这一腿"
            "无从产生（本席已把四枚名单清空，仍不中＝准入门换了形状，不是通过）"
        )
    manual_axis = chat.resolve_narration_axis(manual_ctx)
    if manual_axis.mode != chat.NARRATION_MODE_SCENE:
        return (
            f"亲手开了亲密，描写轴读数={manual_axis.mode!r}（甲要求 scene）"
            f"，narration_source={str(manual_ctx.get('narration_source', ''))!r}"
            "⇒ 开亲密仍只说话＝甲没落地，铺写在现网永远到不了"
        )
    if not manual_axis.granted or not cr.grants_intimate_narration(
        str(manual_ctx.get("narration_source", "") or "")
    ):
        return (
            f"开亲密那一轮的 narration_source={str(manual_ctx.get('narration_source', ''))!r}"
            " 不过唯一那把尺 ⇒ 轴值是 scene 也拿不到交付面"
        )
    if chat.intimate_reply_length_tier("auto", "今天有点累") != top:
        return f"甲这一腿拿到了 scene，长度却到不了顶格档 {top!r}"

    # ---- (d) 自动腿负对照：ML／好感度只给档，不给描写
    for source_name in ("INTIMATE_SOURCE_MASTER_LOVE", "INTIMATE_SOURCE_AFFINITY"):
        auto_source = getattr(cr, source_name, None)
        if auto_source is None:
            return f"来源常量缺席：{source_name}（自动腿换了名字，(d) 要跟改）"
        auto_key = f"e2e-narration-tier-{source_name}"
        cr.SHARED_CONTENT_ROUTE_ENGINE.apply_manual(
            auto_key, "intimate", cfg, source=auto_source
        )
        auto_ctx = cr.resolve_intimate_context(
            cr.SHARED_CONTENT_ROUTE_ENGINE,
            session_type="private",
            session_key=auto_key,
            sender_id=auto_key,
            config=cfg,
        )
        if str(auto_ctx.get("mode", "")) != "intimate":
            return (
                f"{source_name} 没能把会话推上亲密档（mode={str(auto_ctx.get('mode', ''))!r}）"
                "⇒ 这一格无从判，本项不认这是通过"
            )
        auto_axis = chat.resolve_narration_axis(auto_ctx)
        if auto_axis.mode != chat.NARRATION_MODE_SPEECH or auto_axis.granted:
            return (
                f"自动腿（{source_name}={auto_source!r}）的描写轴读成了 {auto_axis.mode!r}"
                f"、granted={auto_axis.granted} ⇒ 名单派生/好感度达档也能铺开写，"
                "授予面被甲顺手放宽了一格"
            )
    return ""


def check_person_policy_beats_standing_global_detail(tmp_dir: Path | None = None) -> str:
    """③ 该人的永久策略压过覆盖册里那枚常驻 `BOT_REPLY_DETAIL`（本波最大根修）。

    事故形状（台账 #76 ③）：`/bot runtime set` 留下跨重启常驻值，被当「本轮明示」
    ⇒ 每个人的永久策略整段静音，`show` 报的档与她实收相反。这里把 `get_or` 直接
    喂成「覆盖册有 BOT_REPLY_DETAIL=detail」，看第②层还站不站得住。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        resolve_turn_reply_policy,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character import (
        reply_policy as rp,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        intimate_control as ic,
    )

    probe_dir = tmp_dir or narration_probe_dir()
    uid = "e2e-narration-policy"
    quiet_uid = "e2e-narration-quiet"
    cfg = SimpleNamespace(
        bot_reply_policy_enabled=True,
        bot_reply_policy_db_path=str(probe_dir / "reply_policy.sqlite3"),
        bot_reply_detail="detail",  # 层③（config 面）
    )
    store = rp.shared_reply_policy_store(cfg)
    if store is None:
        return "永久策略 store 构不出来（enabled/db_path 没吃到）⇒ 层② 无从判"
    message = synthesize_message(
        text="以后回复我都短一点",
        session_type=SessionType.PRIVATE,
        target_id=uid,
        sender_id=uid,
        bot_id="bot-e2e",
        seq=903,
    )
    pinned_policy = resolve_turn_reply_policy(
        store=store,
        message=message,
        text="以后回复我都短一点",
        llm_provider=None,
        # 第④轨（线索门→另起一线问模型）在验收判定里必须**不启动**：零外呼。
        judgment_starter=lambda _prompt, _work: False,
    )
    if pinned_policy is None:
        return "「以后回复我都短一点」没落成永久策略（返回 None）⇒ 层② 没有可判的行"
    pinned = rp.normalize_length_mode(pinned_policy.length_mode)
    if pinned in ("", rp.LENGTH_MODE_AUTO):
        return f"永久策略落成了 auto（读到 {pinned!r}）⇒ 层② 是空的，压不住全局档"
    override_settings = SimpleNamespace(
        get=lambda key, config: None,
        get_or=lambda key, default: "detail" if str(key) == "BOT_REPLY_DETAIL" else default,
    )
    shown = ic._effective_detail_mode(cfg, override_settings, uid, uid)
    if shown != pinned:
        return (
            f"该人永久策略（{pinned}）被常驻 BOT_REPLY_DETAIL=detail 静音："
            f"show 读数={shown!r}（与她实收相反的那枚谎报）"
        )
    # 反向不伤：没表过态的人照旧吃全局档（永久策略层不得凭空造档）
    quiet_shown = ic._effective_detail_mode(cfg, override_settings, quiet_uid, quiet_uid)
    if quiet_shown != "detail":
        return f"未表态的人读数变成 {quiet_shown!r}（期望全局 detail）⇒ 层② 反向误伤"
    plain_settings = SimpleNamespace(
        get=lambda key, config: None, get_or=lambda key, default: default
    )
    if ic._effective_detail_mode(cfg, plain_settings, quiet_uid, quiet_uid) != "detail":
        return "覆盖册不表态时全局档没吃到 config 的 bot_reply_detail（层③ 自己断了）"
    return ""


def expect_group_span_scrub(outcome: ItemOutcome) -> str:
    """④（外层真实管道那一跑）群内命中＝涂掉那一处、其余照发，不得整条吞。"""
    from plugins.bot_unified_runtime.domains.render import reviewer as rv

    if outcome.error:
        return outcome.error
    if outcome.session_type and outcome.session_type != SessionType.GROUP.value:
        # 群内容面只在群会话生效：私聊跑到本项**不静默通过**，直接报「换个目标再跑」。
        return (
            f"本项按 {outcome.session_type} 会话跑，群内逐段涂销判不到——"
            "请用 --target-group <BOT_GROUP_WHITE1 群号> 重跑本项"
        )
    if outcome.receipt is not None and outcome.receipt.state.value == "blocked":
        return "群内命中被整条 BLOCK（回执 blocked）⇒ 逐段涂销的腿没生效"
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason + "（群内命中本该只剩那一处被涂掉、其余照发）"
    text = request.content.text_fallback
    if _GROUP_SCRUB_SPAN in text:
        return (
            f"命中词面 {_GROUP_SCRUB_SPAN!r} 仍原样出门 ⇒ 涂销腿没跑"
            "（或禁词清单换了词，本用例要跟改）"
        )
    placeholder_name = "_PUBLIC_OUTPUT_SPAN_PLACEHOLDER"
    placeholder = str(getattr(rv, placeholder_name, "<已略>"))
    if placeholder not in text:
        return f"出门正文里没有涂销记号 {placeholder!r}：{text[:120]!r}"
    for keep in (_GROUP_SCRUB_CLEAN_HEAD, _GROUP_SCRUB_CLEAN_TAIL):
        if keep not in text:
            return f"其余正文被吞（缺 {keep[:16]!r}…）⇒ 不是逐段涂销"
    return ""


def check_group_span_scrub_is_recorded(runtime: E2eRuntime) -> str:
    """④（审计腿）降级那行 review 审计**必须真的落**——它 2026-10-04 才被接上。

    自成一跑：自己的 InMemory 审计仓库 + InMemory 队列 + 真实 `RuntimePipeline`
    （群目标取运行时白名单第一枚，与主矩阵同一道门），零 transport、零落盘。
    """
    from plugins.bot_unified_runtime.contracts import ReceiptState
    from plugins.bot_unified_runtime.domains.render import reviewer as rv

    lists = load_group_lists(runtime.config)
    pool = [str(item) for item in (lists["white1"] or lists["white2"] or []) if str(item)]
    if not pool:
        return (
            "BOT_GROUP_WHITE1/WHITE2 为空 ⇒ 群内涂销用例无法装配"
            "（先把验收群加进白名单，这不是通过）"
        )
    group_id = min(pool)
    logger = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=logger)
    pipeline = build_pipeline(runtime, queue, audit_logger=logger)
    message = synthesize_message(
        text=_GROUP_SCRUB_BODY,
        session_type=SessionType.GROUP,
        target_id=group_id,
        sender_id=runtime.sender_id,
        bot_id=runtime.bot_id,
        seq=904,
    )
    try:
        receipt = pipeline.handle(
            message,
            _text_capability(runtime, body=_GROUP_SCRUB_BODY),
            capability_id="bot.text",
        )
    except Exception as exc:  # noqa: BLE001 - 跑不起来就是失败，绝不静默通过
        return f"群内涂销用例没跑起来：{type(exc).__name__}: {exc}"
    if receipt.state is ReceiptState.BLOCKED:
        return "整条 BLOCK 而非逐段涂销 ⇒ 降级腿退回改前形态（词面位置/载体变了？）"
    records = _audit_records_for(logger, message.request_id)
    if records is None:
        return "取不到审计记录（InMemoryAuditLogger 的读口形变）⇒ 审计行断言无从落地"
    review_rows = [
        record for record in records if str(getattr(record, "stage", "")) == "review"
    ]
    if not review_rows:
        return (
            "review 审计行缺席——「降级已落账」在验收面是假话"
            f"（本轮 {len(records)} 行里 stage 只有 "
            f"{sorted({str(getattr(r, 'stage', '')) for r in records})}）"
        )
    rewrite = str(getattr(rv.ReviewAction.REWRITE, "value", "rewrite"))
    if not any(str(getattr(r, "event", "")) == rewrite for r in review_rows):
        return (
            f"review 行里没有 event={rewrite!r} 的降级记号，实际 "
            f"{sorted({str(getattr(r, 'event', '')) for r in review_rows})}"
        )
    return ""


def _roleplay_strip_mouths(module_path: Path) -> tuple[int, list[str]]:
    """AST 只读数：``strip_action_brackets(`` 调用点枚数 + 未被 if 包住的裸调用行号。

    用 AST 而不是文本匹配：`if ...: strip_action_brackets(x)` 与
    函数体里的裸调用，文本看着一样，判据却完全不同。
    """
    import ast

    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    guarded_if = {
        id(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
    }
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    total = 0
    bare: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func.id if isinstance(node.func, ast.Name) else getattr(
            node.func, "attr", ""
        )
        if callee != "strip_action_brackets":
            continue
        total += 1
        owner = parents.get(id(node))
        inside_if = False
        depth = 0
        while owner is not None and depth < 12:
            if id(owner) in guarded_if and "action_brackets" in ast.unparse(owner.test):
                inside_if = True
                break
            owner = parents.get(id(owner))
            depth += 1
        if not inside_if:
            bare.append(str(node.lineno))
    return total, bare


def check_action_brackets_follow_narration_grant(
    base_config: Any, tmp_dir: Path | None = None
) -> str:
    """⑤ 出站不再**不分档位**剥动作——按描写档那一轴分腿判（席 e2ealign 2026-10-05 拆轴）。

    四条腿：
    (a) 形（AST）——`capabilities/chat.py` 里 `strip_action_brackets` 的每枚调用点都
        必须待在「test 里出现 `action_brackets`」的 if 分支内；裸调用＝改前那一手。
    (b) **scene 轮**（不放宽）——静态 provider 交回带括号动作的回话，`ToneProfile
        .action_brackets=False`（现网即此值）：会话经**真入口**「亲密模式 深开」钉成
        `manual` 源（在授予集里）⇒ 先要求描写轴读数就是 `scene`，再要求括号留在正文。
        轴读数不是 scene 时本腿**报红而不代判**：H-1＝甲 之后亲手开亲密必给 scene，
        读成 speech 即甲没落地；而只说话那一轮按裁定**本来就不该有** `（…）`——
        把「动作段一定在场」当所有授予轮的通式去判＝假红（这一枚差集就是本席补的）。
    (c) **轴真在选文风**——`resolve_rp_style_block` 按 (描写档 × 亲密态) 选出的两段必须
        互不相同，且认不出的轴值 fail-closed 收回 `speech` 那一格。
    (d) 没开档的会话 ⇒ 括号照旧硬剥，且轴读数必须是 `speech`（2026-09-28「日常沟通
        不写动作神态」那条裁定靠的就是这一腿，不许顺手放宽）。

    🔴 本判定**不写描写钉**：`scene` 那一格从「亲手开亲密」的轴读数来（甲），所以 I-2
    把钉改成 (平台·会话·人) 三元组之后本腿照样成立；写库（D-1 开档标记）经
    `narration_probe_config` 指 `%TEMP%`。
    """
    from plugins.bot_unified_runtime.contracts import (
        ContextBundle,
        ConversationHistoryResult,
        MemoryRetrievalResult,
        PersonaProfile,
        RetrievalResult,
        ToneProfile,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_chat_result,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
        StaticLLMProvider,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        content_route as cr,
    )

    total, bare = _roleplay_strip_mouths(Path(chat.__file__))
    if total == 0:
        return (
            "chat.py 里再也找不到 strip_action_brackets 调用点 ⇒ 日常轮的硬剥被整条删掉"
            "（2026-09-28 裁定失效），本用例判红"
        )
    if bare:
        return f"剥动作那条腿有 {len(bare)} 处不在 action_brackets 判据里：{bare}"

    probe_dir = tmp_dir or narration_probe_dir()
    cfg = narration_probe_config(base_config, probe_dir)
    if not bool(getattr(cfg, "bot_content_route_enabled", False)):
        return "content_route 未启用（bot_content_route_enabled=False）⇒ 授予腿无从产生"

    def _context(message: IncomingMessage) -> ContextBundle:
        return ContextBundle(
            request_id=message.request_id,
            persona=PersonaProfile(
                profile_id="shorekeeper",
                version="1",
                display_name="守岸人",
                identity="守岸人",
            ),
            tone=ToneProfile(profile_id="shorekeeper", mode="default", action_brackets=False),
            memory_results=MemoryRetrievalResult(request_id=message.request_id),
            conversation_history=ConversationHistoryResult(request_id=message.request_id),
            knowledge_results=RetrievalResult(request_id=message.request_id),
            current_message=message.plain_text,
            sender_id=message.sender_id,
            session_id=message.session_id,
        )

    def _turn(uid: str, text: str, reply_text: str) -> CapabilityResult:
        message = synthesize_message(
            text=text,
            session_type=SessionType.PRIVATE,
            target_id=uid,
            sender_id=uid,
            bot_id="bot-e2e",
            seq=905,
        )
        return build_chat_result(
            message,
            _decision_for_chat(message),
            _context(message),
            llm_provider=StaticLLMProvider(text=reply_text),
            affinity_store=None,
            content_route_config=cfg,
        )

    granted_uid = "e2e-narration-granted"
    _ = _turn(granted_uid, "亲密模式 深开", "嗯。")
    verdict = cr.SHARED_CONTENT_ROUTE_ENGINE.route_verdict(granted_uid, cfg)
    source = str((verdict or {}).get("source", "") or "")
    if not cr.grants_intimate_narration(source):
        return (
            f"钉完深开后来源={source!r} 不在授予集里 ⇒ 授予腿没能把这一轮换成人亲手推动"
        )

    def _axis_reading(uid: str) -> Any:
        """注入缝同一个读数口（`resolve_intimate_context` → `resolve_narration_axis`）。

        只转述、不在验收面重推优先级——判据住 `content_route`，本席不抄第二把尺。
        """
        return chat.resolve_narration_axis(
            cr.resolve_intimate_context(
                cr.SHARED_CONTENT_ROUTE_ENGINE,
                session_type="private",
                session_key=uid,
                sender_id=uid,
                config=cfg,
            )
        )

    # (b) 前半：先确认这一轮**确实**是 scene 轮（甲的读数），再判括号留没留。
    granted_axis = _axis_reading(granted_uid)
    if granted_axis.mode != chat.NARRATION_MODE_SCENE:
        return (
            f"亲手开了亲密（source={source!r}），描写轴读数却是 {granted_axis.mode!r}"
            "：本腿只判 scene 轮的交付面——只说话那一轮按裁定**不该**有 `（…）`，"
            "这里不代它判通过（甲＝开亲密即给 scene，读成 speech 即甲没落地）"
        )
    kept = _turn(granted_uid, "今天有点累", _ACTION_BRACKET_REPLY)
    if _ACTION_BRACKET_OPEN not in str(kept.body or ""):
        return (
            f"拿到授予（source={source!r}）的那一轮括号动作仍被剥光："
            f"{str(kept.body)[:120]!r}"
        )
    # (c) 轴真的在选文风：scene ≠ speech，且认不出的轴值收回只说话那一格（fail-closed）。
    scene_block = chat.resolve_rp_style_block(chat.NARRATION_MODE_SCENE, intimate=True)
    speech_block = chat.resolve_rp_style_block(chat.NARRATION_MODE_SPEECH, intimate=True)
    if not scene_block or not speech_block:
        return "resolve_rp_style_block 交出空段（样式段表缺格）⇒ 交付面无从判"
    if scene_block == speech_block:
        return (
            "scene 与 speech 选出同一段样式 ⇒ 描写档轴只剩读数、不选文风"
            "（「只说话就不该拿到铺写交付面」那条裁定在出口没人执法）"
        )
    if chat.resolve_rp_style_block("e2e-unknown-axis-mode", intimate=True) != speech_block:
        return (
            "认不出的轴值没 fail-closed 收回 speech（选出了别一段）"
            "⇒ 漂走的轴值在放大描写面，方向反了"
        )
    # (d) 没开档的那一条：日常轮照旧硬剥，轴读数必须是 speech。
    plain_uid = "e2e-narration-plain"
    plain = _turn(plain_uid, "今天有点累", _ACTION_BRACKET_REPLY)
    if _ACTION_BRACKET_OPEN in str(plain.body or ""):
        return (
            "未开档的会话也留了括号动作 ⇒ 全局开关被顺手放宽（日常轮不写动作神态那条裁定）"
        )
    plain_axis = _axis_reading(plain_uid)
    if plain_axis.mode != chat.NARRATION_MODE_SPEECH or plain_axis.granted:
        return (
            f"未开档会话的描写轴读数={plain_axis.mode!r}、granted={plain_axis.granted}"
            "（期望 speech/False）⇒ 缺省那一格被改，日常轮白拿了铺写文风"
        )
    return ""


def _decision_for_chat(message: IncomingMessage) -> BotDecision:
    """判定用的最小 BotDecision（私聊 chat 轮，与生产同形，零决策引擎依赖）。"""
    from plugins.bot_unified_runtime.contracts import (
        PrivacyLevel,
        RiskLevel,
        SendPolicy,
    )

    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=message.session_type,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="e2e_acceptance_narration",
    )


def _narration_chunks_request(request_id: str, chunks: list[str]) -> SendRequest:
    """⑥ 判定用的两部件 chunks 请求（临时库，绝不到 transport）。"""
    from plugins.bot_unified_runtime.contracts import PrivacyLevel, RenderedOutput

    rendered = RenderedOutput(
        request_id=request_id,
        content_type="chunks",
        content_ref={"chunks": list(chunks)},
        text_fallback="正文",
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id="private:e2e-narration",
        target_scope=SessionType.PRIVATE,
        target_id="e2e-narration",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=len(chunks),
        dedupe_key=f"dedupe-{request_id}",
        cooldown_key="bot.chat:private:e2e-narration",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def check_delivery_failure_reason_is_readable(tmp_dir: Path | None = None) -> str:
    """⑥ 投递失败原因可查、部分投递不被擦成终态。

    (a) 形（AST）——`sender/onebot.py` 的四枚 `result_unknown` 手足出口都得被
        `count > 0` 那枚守卫单独罩住（守卫里混进白名单判据＝第 4 枚嘴的原形：已投成功
        的部件被一并擦成 failed_final）；引用 retcode 的终态出口≥2 枚且枚枚带
        `detail=_onebot_failure_detail(...)`（判死的数字不许用完即丢）。
    (b) 实（临时库，零发送）——两部件请求：0 号 sent、1 号 failed_final 带原因；
        读回必须 ① 列在册 ② 原因逐字可读 ③ 已送达那行不被改成终态。
    """
    import ast
    import sqlite3

    from plugins.bot_unified_runtime.domains.transport.sender import onebot as ob
    from plugins.bot_unified_runtime.domains.transport.sender import queue as sendq

    tree = ast.parse(Path(ob.__file__).read_text(encoding="utf-8"))
    parents: dict[int, Any] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    unknown_arms: list[tuple[Any, str]] = []
    retcode_arms: list[tuple[Any, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _e2e_callee_name(node) != "_onebot_issue":
            continue
        unparsed = ast.unparse(node)
        kind_match = re.search(r"""_onebot_issue\(\s*["']([^"']+)["']""", unparsed)
        kind = kind_match.group(1) if kind_match else "(未取到 kind)"
        if kind == "result_unknown":
            unknown_arms.append((node, unparsed))
        if "retcode" in unparsed:
            retcode_arms.append((node, unparsed))
    if len(unknown_arms) < 4:
        return (
            f"只认到 {len(unknown_arms)} 枚 result_unknown 出口（期望 ≥4：部件被拒/超时/"
            "异常/退码四枚手足）⇒ 部分投递的 result_unknown 通路被并掉了"
        )
    for arm_node, _arm_text in unknown_arms:
        tests: list[str] = []
        owner = parents.get(id(arm_node))
        depth = 0
        while owner is not None and depth < 14:
            if isinstance(owner, ast.If):
                tests.append(ast.unparse(owner.test))
            owner = parents.get(id(owner))
            depth += 1
        joined = " || ".join(tests)
        if "count" not in joined:
            return (
                f"result_unknown 出口（第 {arm_node.lineno} 行）没被 `count > 0` 那枚守卫"
                f"罩住（沿途 if 判据={joined!r}）⇒ 部分投递不再无条件转 unknown"
            )
        if "_is_final_failure_retcode" in joined:
            return (
                f"result_unknown 出口（第 {arm_node.lineno} 行）的守卫里混进了白名单判据"
                f"（{joined!r}）⇒ 白名单退码会绕过副作用守卫、把已投成功的部件也擦成终态"
                "（那正是本波修掉的第 4 枚嘴的原形）"
            )
    if len(retcode_arms) < 2:
        return (
            f"只有 {len(retcode_arms)} 枚终态出口引用了 retcode（期望 ≥2：判死与判可重试"
            "两支都要把码带上）⇒ 判死用的数字又变成用完即丢"
        )
    detailless = [
        str(node.lineno) for node, text in retcode_arms if "detail=" not in text
    ]
    if detailless:
        return (
            f"带 retcode 的终态出口第 {detailless} 行没把原因交出去（缺 detail=）"
            " ⇒ 事后无从复核是哪枚码判的生死"
        )

    probe_dir = tmp_dir or narration_probe_dir()
    db_path = probe_dir / "sendq.sqlite3"
    ledger_queue = sendq.SQLiteSendRequestQueue(db_path, InMemoryAuditLogger())
    request = _narration_chunks_request("e2e-failure-reason", ["分片甲", "分片乙"])
    ledger_queue.submit(request)
    # part 账本是**首次 part 化投递前**预写的（worker 的认领路径才建账）：验收判定
    # 不出网、不进 worker ⇒ 自己按同一只口把两行 PENDING 铺出来，再走标注腿。
    if (
        ledger_queue.ensure_parts_planned(
            request.request_id,
            ["digest-0", "digest-1"],
            dedupe_key=request.dedupe_key,
        )
        is None
    ):
        return "ensure_parts_planned 没铺出 part 账 ⇒ 断点续发的账本无从建"
    detail = "retcode_failure retcode=403 status=failed"
    if not ledger_queue.mark_part_sent(request.request_id, 0):
        return "part 0 标 sent 没落账 ⇒ 断点续发的账本腿断了"
    if not ledger_queue.mark_part_failed_final(
        request.request_id, 1, error_kind="retcode_failure", error_detail=detail
    ):
        return "part 1 标 failed_final 没落账 ⇒ 终态腿断了"
    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(send_request_parts)")
        }
        rows = connection.execute(
            "SELECT part_index, state, last_error_kind, last_error_detail"
            " FROM send_request_parts WHERE request_id = ? ORDER BY part_index",
            (request.request_id,),
        ).fetchall()
    if "last_error_detail" not in columns:
        return "发送队列库没有 last_error_detail 列（ALTER-if-missing 那条腿没跑）"
    ledger = {int(row[0]): (str(row[1]), row[2], row[3]) for row in rows}
    if len(ledger) != 2:
        return f"part 账本应有 2 行，读到 {len(ledger)} 行"
    if ledger[0][0] != sendq.PART_STATE_SENT:
        return (
            f"已送达的 0 号被写成 {ledger[0][0]!r} ⇒ 部分投递被擦成终态"
            "（断点续发与补偿据此判 delivered==0，会整条重投）"
        )
    if ledger[1][0] != sendq.PART_STATE_FAILED_FINAL:
        return f"1 号终态没落住（读到 {ledger[1][0]!r}）"
    if (ledger[1][1] or "") != "retcode_failure":
        return f"失败族没落账（last_error_kind={ledger[1][1]!r}）"
    if (ledger[1][2] or "") != detail:
        return f"原因不可读：last_error_detail={ledger[1][2]!r}（期望 {detail!r}）"
    return ""


def _e2e_callee_name(node: Any) -> str:
    """AST 调用点函数名（`Name` 与 `Attribute` 两种形态都认）。"""
    func = node.func
    return str(getattr(func, "id", None) or getattr(func, "attr", "") or "")


def build_matrix(runtime: E2eRuntime) -> list[MatrixItem]:
    """验收矩阵（①文本/长文本/多段 ②解析卡 ③点歌候选 ④全球股指 ⑤财经/科技快报
    ⑥天气+预警 ⑦随机图 ⑧占卜 ⑨help ⑩好感度 ⑪提醒查询
    ⑫个股行情+非上市守卫 ⑬汇率面板/定向换算 ⑭占卜金钱卦 ⑮称谓自助
    ⑯决策影子查询双态 ⑰A-19 群失败降级正/负样本）。"""
    return [
        MatrixItem(
            key="text-short",
            label="①文本直发（短）",
            capability_id="bot.text",
            build=lambda rt: _text_capability(
                rt, body="E2E 验收 · 短文本直发：守岸人链路自检，收到请忽略。"
            ),
            text="E2E 验收 · 短文本直发",
            note="镜像 _send_text_through_unified_pipeline 的内联文本能力",
        ),
        MatrixItem(
            key="text-long",
            label="①长文本（≥合并转发阈值观察）",
            capability_id="bot.text",
            build=lambda rt: _text_capability(rt, body=_long_text_body()),
            text="E2E 验收 · 长文本直发",
            note="超过 bot_render_forward_min_chars 时由管道转合并转发",
        ),
        MatrixItem(
            key="text-parts",
            label="①多段（text_parts → chunks）",
            capability_id="bot.text",
            build=lambda rt: _text_capability(
                rt,
                text_parts=[
                    "E2E 多段验证 1/3：本条由能力层 text_parts 声明，渲染为 chunks 分片逐条发送。",
                    "E2E 多段验证 2/3：观察 QQ 侧是否按顺序收到三条独立消息。",
                    "E2E 多段验证 3/3：分片完毕。",
                ],
            ),
            text="E2E 验收 · 多段直发",
            note="content_type=chunks，sender 按 parts 逐条发",
        ),
        MatrixItem(
            key="content-bili",
            label="②解析卡（B 站视频）",
            capability_id="bot.content",
            build=_content_capability,
            text=BILI_SAMPLE_URL,
            note="真实解析 + Mica 信息卡（需外网；失败时能力层自带文本降级）",
        ),
        MatrixItem(
            key="music-candidates",
            label="③点歌候选卡",
            capability_id="bot.music",
            build=_music_capability,
            text="点歌 告白气球",
            note="BOT_MUSIC_CANDIDATES_ENABLED 开启时同名歧义返回候选卡；否则直接出歌曲卡",
        ),
        MatrixItem(
            key="market-global",
            label="④全球股指（18 指数全量）",
            capability_id="bot.market",
            build=lambda rt: build_market_capability(rt.config),
            text="全球股市",
            note="不带市场词（美股/港股/A股…）= 不过滤 → 指数全量",
        ),
        MatrixItem(
            key="news-finance",
            label="⑤财经快报（全量）",
            capability_id="bot.news",
            build=lambda rt: build_news_capability(rt.config),
            text="财经快报",
            note="条数上限 bot_news_max_items（默认 8）",
        ),
        MatrixItem(
            key="news-tech",
            label="⑤科技快报（全量）",
            capability_id="bot.news",
            build=lambda rt: build_news_capability(rt.config),
            text="科技快报",
            note="类目 tech",
        ),
        MatrixItem(
            key="weather-alert",
            label="⑥天气+预警",
            capability_id="bot.weather",
            build=lambda rt: build_weather_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text=lambda rt: f"天气 {rt.city or '北京'}",
            note="NMC 在报预警自动附在天气报告后（无预警时只出天气）",
        ),
        MatrixItem(
            key="randpic",
            label="⑦随机图",
            capability_id="bot.randpic",
            build=lambda rt: build_randpic_capability(rt.config),
            text="随机图",
            note="BOT_RANDPIC_DIRS 未配置/为空时给降级文案（真实行为）",
        ),
        MatrixItem(
            key="divination",
            label="⑧占卜（塔罗单张）",
            capability_id="bot.divination",
            build=lambda rt: build_divination_capability(rt.config),
            text="塔罗",
        ),
        MatrixItem(
            key="help",
            label="⑨help 卡",
            capability_id="bot.help",
            build=_help_capability,
            text="help",
            note="Mica 帮助页，主色 bot_help_card_color 派生",
        ),
        MatrixItem(
            key="affinity",
            label="⑩好感度卡",
            capability_id="bot.affinity",
            build=_affinity_capability,
            text="好感度",
            note="群=本群好感榜；私聊=双向分值卡（bot_affinity_enabled 关闭时给降级文案）",
        ),
        MatrixItem(
            key="reminder-list",
            label="⑪提醒查询（按设计静默）",
            capability_id="bot.reminder",
            build=lambda rt: build_reminder_capability(rt.config),
            text="提醒列表",
            note=(
                "提醒能力回执恒为 SILENT_AUDIT（只登记/查询，不当场发言）——"
                "预期收到 skipped 回执而非消息"
            ),
        ),
        MatrixItem(
            key="stocks-nvda",
            label="⑫个股卡（英伟达）",
            capability_id="bot.stocks",
            build=lambda rt: build_stocks_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text="英伟达股价",
            note="2026-09-13 批次：期望釉瑚金融卡（行情源/渲染失败降级文本会判 expect-FAIL）",
            expect=expect_stock_card,
        ),
        MatrixItem(
            key="stocks-nonpublic",
            label="⑫非上市守卫（OpenAI 估值）",
            capability_id="bot.stocks",
            build=lambda rt: build_stocks_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text="OpenAI 估值",
            note="NON_PUBLIC 分支不触行情外呼：只给有来源的估值口径，零股价/OHLC/卡图",
            expect=expect_nonpublic_guard,
        ),
        MatrixItem(
            key="fx-panel",
            label="⑬汇率面板卡",
            capability_id="bot.fx",
            build=lambda rt: build_fx_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text="汇率",
            note="主要货币（USD 基准）面板卡",
            expect=expect_fx_panel_card,
        ),
        MatrixItem(
            key="fx-convert",
            label="⑬汇率定向换算",
            capability_id="bot.fx",
            build=lambda rt: build_fx_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text="100日元换多少人民币",
            note="JPY→CNY 定向换算（含 unit_base 折算，评审 P0-1 口径）",
            expect=expect_fx_converted,
        ),
        MatrixItem(
            key="divination-iching",
            label="⑭占卜（金钱卦，出卡二态）",
            capability_id="bot.divination",
            build=lambda rt: build_divination_capability(rt.config),
            text="占卜",
            note="渲染后端可用出 mixed 卡，不可用回纯文本——二态均算通过，断言不抛异常",
            expect=expect_divination_two_state,
        ),
        MatrixItem(
            key="identity-set-name",
            label="⑮称谓自助 set-name",
            capability_id="bot.identity",
            build=lambda rt: _identity_preference_capability(
                rt, command_text="set-name 岸友"
            ),
            text="/bot identity set-name 岸友",
            note=(
                "镜像 runtime_admin 管理员门前拦截转发；写库两轴——DRY-RUN 把称谓/策略两本库"
                "改指 %TEMP% 探针根（生产库零字节），--execute 才写真实 AddressingPreferenceStore"
                "（运行区库），并由 identity-unset-name 项成对清理、净效果为零。"
                "群侧命令面＝blocked＋原因可查（command_group_unlisted）；正跑面 requires 私聊"
                "--target-user（群侧个人输出被判 move_private；验收面所有群都算未在册，"
                "见文件头 _COMMAND_GATE_DENIALS 注）"
            ),
            expect=expect_command_after_group_gate(expect_identity_set_confirmed),
        ),
        MatrixItem(
            key="identity-unset-name",
            label="⑮称谓自助 unset-name（清理）",
            capability_id="bot.identity",
            build=lambda rt: _identity_preference_capability(
                rt, command_text="unset-name"
            ),
            text="/bot identity unset-name",
            note=(
                "整行移除称谓偏好（含性别自述），与 set-name 成对执行、净效果为零；"
                "群侧命令面与 set-name 同轨（blocked＋门名可查＝PASS；"
                "正跑面 requires 私聊 --target-user）"
            ),
            expect=expect_command_after_group_gate(expect_identity_unset_confirmed),
        ),
        # ---- 二期扩展（2026-09-13）：多语言触发形态抽样 + 劫持守卫负样本 ----
        # 词表取证：.superpowers/sdd/2026-09-12-shorekeeper-global-audit/ 下
        # fix-py1/py2（拼音全拼/缩写）、fix-eng-verify（英文）、fix-tra2/tra3
        # （繁體）报告 + is_* 检测器实跑核验；fix-py1 市场词表无 meiguhang，
        # 按其实际入表词取 hangqing/hq。存量 21 项零改动。
        MatrixItem(
            key="music-pinyin",
            label="③点歌（拼音全拼 diange）",
            capability_id="bot.music",
            build=_music_capability,
            text="diange 晴天",
            note="fix-py1：_COMMAND_RE 全拼 diange（同音覆盖 點歌）；候选/歌曲卡同点歌主链路",
        ),
        MatrixItem(
            key="music-abbr",
            label="③点歌（缩写 dg）",
            capability_id="bot.music",
            build=_music_capability,
            text="dg 晴天",
            note="fix-py1：dg 入表缩写（(?![a-z0-9]) 右界；dgms/diangemoshi 归 mode 族不抢主命令）",
        ),
        MatrixItem(
            key="weather-pinyin",
            label="⑥天气（拼音全拼 tianqi）",
            capability_id="bot.weather",
            build=lambda rt: build_weather_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text="tianqi 台北",
            note="fix-py2：tianqi/tq 入表（正则无 IGNORECASE，小写生效）；台北走 F18 城市别名",
        ),
        MatrixItem(
            key="weather-english",
            label="⑥天气（英文 weather）",
            capability_id="bot.weather",
            build=lambda rt: build_weather_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text="weather 台北",
            note="T1.2 英文别名（weather(?![A-Za-z0-9]) 词界，weatherqq 胶合不触发）；"
            "query 必填故裸 weather 不匹配（实跑核实）",
        ),
        MatrixItem(
            key="market-pinyin",
            label="④股指（拼音全拼 hangqing）",
            capability_id="bot.market",
            build=lambda rt: build_market_capability(rt.config),
            text="hangqing",
            note="fix-py1：非锚定 search 双侧词界；无市场过滤词 → 18 指数全量（同 全球股市）",
        ),
        MatrixItem(
            key="market-abbr",
            label="④股指（缩写 hq）",
            capability_id="bot.market",
            build=lambda rt: build_market_capability(rt.config),
            text="hq",
            note="fix-py1：hq 入表缩写；两字母缩写群聊误伤面（hq≈总部等）即在本项真机观察",
        ),
        MatrixItem(
            key="meme-lib-steal-eng",
            label="表情收库（英文 steal meme）",
            capability_id="bot.meme_library",
            build=_meme_library_capability,
            text="steal meme",
            note="T1.2：按权重偷一张（mixed 出图）或空库/冷却文案；"
            "读真实运行区表情库（只读 pick，与好感度项同口径）",
            expect=expect_meme_library_pick,
        ),
        MatrixItem(
            key="meme-lib-random-eng",
            label="表情收库（英文 meme random）",
            capability_id="bot.meme_library",
            build=_meme_library_capability,
            text="meme random",
            note="T1.2：memes? random 同支；与 steal meme 同会话连跑时第二项常落 "
            "20s 会话冷却文案（真实防刷屏风控，非缺陷）",
            expect=expect_meme_library_pick,
        ),
        MatrixItem(
            key="news-trad",
            label="⑤快報（繁體）",
            capability_id="bot.news",
            build=lambda rt: build_news_capability(rt.config),
            text="快報",
            note="fix-tra2：繁體族 10 词入 _NEWS_TRIGGER_RE；类目提取繁體缺口（tra2 残余①）→ 落 mix 类目",
        ),
        MatrixItem(
            key="randpic-trad",
            label="⑦隨機圖（繁體）",
            capability_id="bot.randpic",
            build=lambda rt: build_randpic_capability(rt.config),
            text="隨機圖",
            note="fix-tra2：隨機圖/來張圖 对向繁體；BOT_RANDPIC_DIRS 未配置时降级文案（真实行为）",
        ),
        MatrixItem(
            key="guard-stocks-openai-question",
            label="劫持守卫（openai是什么 → 不触发个股）",
            capability_id="bot.text",
            build=lambda rt: _router_gated_capability(
                rt,
                detector=is_stocks_command,
                domain_builder=lambda rt2: build_stocks_capability(
                    rt2.config, render_backend=rt2.render_backend
                ),
                domain_label="个股行情",
            ),
            text="openai是什么",
            note="test_stocks_hijack_guard：路由层让路 moegirl_question；"
            "本项镜像 is_stocks_command 门（直喂会误走 NON_PUBLIC 分支），断言零股价/估值内容",
            expect=expect_chat_fallthrough(
                markers=_STOCK_CONTENT_MARKERS + ("估值",),
                domain_label="个股行情",
            ),
        ),
        MatrixItem(
            key="guard-divination-fortune-sentence",
            label="劫持守卫（算命陈述句 → 不触发占卜）",
            capability_id="bot.text",
            build=lambda rt: _router_gated_capability(
                rt,
                detector=is_divination_command,
                domain_builder=lambda rt2: build_divination_capability(rt2.config),
                domain_label="占卜",
            ),
            text="我说算命都是骗人的",
            note="test_divination_hijack_guard 八连样例之一：应落 chat；"
            "本项镜像 is_divination_command 门（直喂会误出 bazi 排盘），断言零排盘/塔罗内容",
            expect=expect_chat_fallthrough(
                markers=("排盘", "四柱", "干造", "塔罗", "金钱卦"),
                domain_label="占卜",
            ),
        ),
        MatrixItem(
            key="guard-market-oil-price",
            label="排除守卫（油价行情 → 不触发股指）",
            capability_id="bot.text",
            build=lambda rt: _router_gated_capability(
                rt,
                detector=is_market_command,
                domain_builder=lambda rt2: build_market_capability(rt2.config),
                domain_label="全球股指",
            ),
            text="油价行情",
            note="test_market_exclusion_guard：非股市「行情」（油价/金价族）让路 chat；"
            "本项镜像 is_market_command 门（含 _NON_STOCK_RE 排除），断言零股指面板形态",
            expect=expect_chat_fallthrough(
                markers=("全球股指", "红涨绿跌", "行情数据", "拉不到"),
                domain_label="全球股指",
            ),
        ),
        # ---- 三期扩展（2026-09-15 夜批 §26）：决策影子查询 + A-19 群失败降级 ----
        MatrixItem(
            key="decision-query-admin",
            label="⑯决策影子查询（管理员）",
            capability_id="bot.decision",
            build=lambda rt: _decision_query_capability(
                rt, actor_roles=["super_admin", "admin"]
            ),
            text="/bot decision",
            note=(
                "§26.2 P-03：/bot decision [N] 缺省 20（1-100）；读真实 "
                "decision_trace.sqlite3（只读，缺库回落热缓冲→「暂无记录」同达成）；"
                "影子模式 legacy_only 下无痕迹属预期；生产 __init__ elif 接线待 "
                "§26.10 登记的补贴，本项验收能力出口本体。"
                "群侧命令面＝blocked＋门名可查（command_group_unlisted）；正跑面 requires 私聊"
                "--target-user（群侧个人输出被判 move_private，见文件头注）"
            ),
            expect=expect_command_after_group_gate(expect_decision_query_admin),
        ),
        MatrixItem(
            key="decision-query-member",
            label="⑯决策影子查询（普通成员温和拒绝）",
            capability_id="bot.decision",
            build=lambda rt: _decision_query_capability(rt, actor_roles=[]),
            text="/bot decision",
            note=(
                "同命令非管理员 → ADMIN_GATE_TEMPLATES 池温和拒绝"
                "（audit: decision_denied），不得泄漏任何查询结果形态。"
                "群侧命令面与 admin 那枚同轨（blocked＋门名可查＝PASS；"
                "正跑面 requires 私聊 --target-user）"
            ),
            expect=expect_command_after_group_gate(expect_admin_gate_refusal),
        ),
        MatrixItem(
            key="group-failure-ack",
            label="⑰A-19 群失败降级短句（正向）",
            capability_id="bot.selftest-fail",
            build=_group_failure_capability,
            text="E2E 验收 · A-19 群失败降级观察",
            note=(
                "§26.4 A-19：群聊能力失败错误态 → 池内温和短句（300s 会话节流）；"
                "私聊不覆盖（另有守岸人话术池）；拦截族静默见 group-busy-silent 负样本"
            ),
            expect=expect_group_failure_ack,
        ),
        MatrixItem(
            key="group-busy-silent",
            label="⑰A-19 负样本：超载快败保持静默",
            capability_id="bot.selftest-busy",
            build=_pipeline_busy_capability,
            text="E2E 验收 · A-19 超载快败静默观察",
            note=(
                "pipeline_busy 与限流/安静时间同属故意降频设计 → 必须零反馈"
                "（零入队请求）；本项在群/私聊两会话下同语义"
            ),
            expect=expect_pipeline_busy_silent,
        ),
        # ---- 四期扩展（席 e2e2，2026-10-05）：叙述授予波六项可失败判定 ----
        MatrixItem(
            key="narration-grant-source",
            label="⑱叙述授予按来源（①）",
            capability_id="bot.selftest-narration",
            build=lambda rt: _text_capability(
                rt,
                body="叙述授予判定：按来源核过——人工推动的那几支给，自动回落两支只说话。",
            ),
            text="E2E 验收 · 叙述授予按来源",
            note=(
                "判据只住 `runtime/content_route.py::grants_intimate_narration`"
                "（读 `_INTIMATE_NARRATION_SOURCES`）；本项离线可判、零外呼、零落盘，"
                "现网那半面（她真说一句把档叫醒）requires restart + --execute"
            ),
            expect=lambda _outcome: check_narration_grant_is_source_scoped(),
        ),
        MatrixItem(
            key="narration-scene-tier",
            label="⑱第四档「铺写」只有授予腿走得到（②）",
            capability_id="bot.selftest-narration",
            build=lambda rt: _text_capability(
                rt,
                body=(
                    "长度档判定：没拿到授予的每一条路都到不了顶格档；"
                    "亲手开亲密的那一轮，描写轴给 scene、顶格档也就到得了。"
                ),
            ),
            text="E2E 验收 · 顶格档可达性",
            note=(
                "构造性证明（`REPLY_TIER_MATRIX` 逐格 + 题型×配置档穷举 + 无正文兜底），"
                "不按档名断言；全局长度一字未动这件事由本项执法。"
                "2026-10-05 补两腿：H-1＝甲（开亲密即给 scene，故顶格档**到得了**）"
                "与自动腿负对照（Master Love／好感度达档照旧只说话）；"
                "两腿都不写描写钉 ⇒ I-2 换钉的键形（平台·会话·人）与本项无关，"
                "D-1 开档标记经 `narration_probe_config` 落 %TEMP%"
            ),
            expect=lambda _outcome: check_top_reply_tier_needs_the_grant(runtime.config),
        ),
        MatrixItem(
            key="narration-person-policy",
            label="⑱该人永久策略压过常驻全局档（③）",
            capability_id="bot.selftest-narration",
            build=lambda rt: _text_capability(
                rt,
                body="策略判定：她钉过的档压过覆盖册里那枚常驻 BOT_REPLY_DETAIL。",
            ),
            text="E2E 验收 · 永久策略优先",
            note=(
                "四层链（当轮明示>永久策略>全局 BOT_REPLY_DETAIL>auto）与 "
                "`intimate_control._effective_detail_mode` 的 show 侧同尺；"
                "写库全落 %TEMP% 临时 reply_policy，生产库零字节"
            ),
            expect=lambda _outcome: check_person_policy_beats_standing_global_detail(),
        ),
        MatrixItem(
            key="narration-group-scrub",
            label="⑱群内命中逐段涂销 + 审计行落账（④）",
            capability_id="bot.text",
            build=lambda rt: _text_capability(rt, body=_GROUP_SCRUB_BODY),
            text=_GROUP_SCRUB_BODY,
            note=(
                "两段断言：本项走真实管道，验「那一处被涂掉、其余正文照发」；"
                "另一跑（`check_group_span_scrub_is_recorded`）自带 InMemory 审计仓库，"
                "验 `stage=review`/`event=rewrite` 那行**确实落盘**——该行 2026-10-04 "
                "才接上，改前「已落账」是假话"
            ),
            expect=expect_group_span_scrub,
        ),
        MatrixItem(
            key="narration-audit-row",
            label="⑱群内涂销的 review 审计行（④·落账腿）",
            capability_id="bot.selftest-narration",
            build=lambda rt: _text_capability(
                rt,
                body="审计判定：降级那行 review 记录与 BLOCK 同一条通道，验收面可回查。",
            ),
            text="E2E 验收 · 涂销审计行",
            note=(
                "自成一跑（自己的 InMemory 审计+队列、真实 RuntimePipeline，零 transport）；"
                "群目标取运行时白名单第一枚，白名单空＝报红不是静默通过"
            ),
            expect=lambda _outcome: check_group_span_scrub_is_recorded(runtime),
        ),
        MatrixItem(
            key="narration-action-brackets",
            label="⑱铺开写那一轮保住（…）动作（⑤）",
            capability_id="bot.selftest-narration",
            build=lambda rt: _text_capability(
                rt,
                body=(
                    "动作括号判定：铺开写的那一轮括号留在正文里；"
                    "只说话那一轮本就不写动作，日常轮照旧不收。"
                ),
            ),
            text="E2E 验收 · 动作括号随描写档",
            note=(
                "形腿＝chat.py 里 `strip_action_brackets` 每枚调用点都在 "
                "`action_brackets` 判据的 if 分支内；实腿按描写档**分态**判（席 e2ealign "
                "2026-10-05 拆轴）：静态 provider 跑真 `build_chat_result`"
                "（`BOT_PERSONA_ACTION_BRACKETS=false` 同形），先确认「亲密模式 深开」那一轮"
                "的描写轴读数＝`scene`（甲）再判括号留——只说话那一轮**不判**括号在场"
                "（那正是裁定要的静默），另判 `resolve_rp_style_block` 两段互不相同且认不出的"
                "轴值收回 speech；未开档会话照旧硬剥。零网络、零真实模型；"
                "真实模型肯不肯写动作那一半 requires restart + --execute"
            ),
            expect=lambda _outcome: check_action_brackets_follow_narration_grant(
                runtime.config
            ),
        ),
        MatrixItem(
            key="narration-failure-reason",
            label="⑱投递失败原因可查 + 部分投递不被擦（⑥）",
            capability_id="bot.selftest-narration",
            build=lambda rt: _text_capability(
                rt,
                body="投递判定：每一枚终态嘴都交得出原因，已送达的那一行不被改写。",
            ),
            text="E2E 验收 · 投递失败可读性",
            note=(
                "形腿＝`sender/onebot.py` 四枚 result_unknown 手足出口都被 `count > 0` "
                "单独罩住（守卫混进白名单判据＝第 4 枚嘴的原形）、引用 retcode 的终态出口"
                "枚枚带 `detail=_onebot_failure_detail(...)`；实腿＝%TEMP% 临时发送队列库"
                "两部件（0 号 sent、1 号 failed_final 带原因）读回对账。真实退码现网复核 "
                "requires restart（改前存量行 last_error_detail 为 NULL＝无原因可考，"
                "不回填不猜）"
            ),
            expect=lambda _outcome: check_delivery_failure_reason_is_readable(),
        ),
    ]


# --------------------------------------------------------------------------
# 执行与回执呈现
# --------------------------------------------------------------------------


@dataclass
class ItemOutcome:
    item: MatrixItem
    request_id: str
    receipt: DeliveryReceipt | None = None
    send_request: SendRequest | None = None
    error: str = ""
    trigger_text: str = ""
    # expect 断言结果：空串=PASS / 未断言；非空=失败原因（断言自身异常也折算进来）。
    expect_fail_reason: str = ""
    # 本项执行时的会话类型（SessionType.value；自测/离线构造可留空）。
    # 供会话敏感的 expect 区分群/私聊语义（如 A-19 只覆盖群聊）。
    session_type: str = ""
    # 本轮 pipeline 审计留痕（event + private_debug 摊平；execute_item 在 handle 之后
    # **只读**回查）。三态各有语义：``None``＝读口形变（拿不到留痕＝判红）；
    # ``[]``＝管道确实没留痕；非空＝原因清单。群侧命令的「按设计被拦」断言读它。
    audit_reasons: list[str] | None = None


def _flatten(text: str) -> str:
    return str(text or "").replace("\r", "").replace("\n", " ⏎ ")


def format_preview(send_request: SendRequest | None) -> str:
    """把将要/已经入队的 SendRequest 渲染成一行预览（DRY-RUN 展示用）。"""
    if send_request is None:
        return "（无入队请求）"
    content = send_request.content
    parts = content.content_ref or {}
    media = 0
    if isinstance(parts, dict):
        media += sum(
            1
            for part in parts.get("parts", [])
            if isinstance(part, dict) and str(part.get("type", "")) != "text"
        )
    preview = _flatten(content.text_fallback)[:PREVIEW_MAX_CHARS]
    return (
        f"content_type={content.content_type} target={send_request.target_scope.value}:"
        f"{send_request.target_id} media={media} text[{len(content.text_fallback)}字]={preview!r}"
    )


def _outcome_audit_reasons(
    pipeline: RuntimePipeline, request_id: str
) -> list[str] | None:
    """回查本轮审计留痕（只读、零写入）：``event`` 与 ``private_debug`` 去重摊平。

    读口复用文件里已有的 ``_audit_records_for``（同一把尺，不另造一份）；它取不到时
    返回 ``None``——调用方**必须判红**，不得当成「没有原因」。门禁的 ``policy.reason``
    就落在这里（``pipeline`` 里 stage=policy / event=policy_denied / private_debug=reason），
    回执对象本身不带原因，所以断言「拦得有原因可查」只能问这一处。
    """
    records = _audit_records_for(getattr(pipeline, "audit_logger", None), request_id)
    if records is None:
        return None
    reasons: list[str] = []
    for record in records:
        for value in (record.event, record.private_debug):
            text = str(value or "").strip()
            if text and text not in reasons:
                reasons.append(text)
    return reasons


def execute_item(
    *,
    pipeline: RuntimePipeline,
    send_queue: Any,
    item: MatrixItem,
    runtime: E2eRuntime,
    session_type: SessionType,
    target_id: str,
    seq: int,
) -> ItemOutcome:
    trigger = item.trigger_text(runtime)
    message = synthesize_message(
        text=trigger,
        session_type=session_type,
        target_id=target_id,
        sender_id=runtime.sender_id,
        bot_id=runtime.bot_id,
        seq=seq,
    )
    outcome = ItemOutcome(
        item=item,
        request_id=message.request_id,
        trigger_text=trigger,
        session_type=session_type.value,
    )
    try:
        capability = item.build(runtime)
    except Exception as exc:  # noqa: BLE001 - 单项构造失败不拖垮整个矩阵。
        outcome.error = f"capability build failed: {type(exc).__name__}: {exc}"
        return outcome
    try:
        receipt = pipeline.handle(message, capability, capability_id=item.capability_id)
        outcome.receipt = receipt
    except Exception as exc:  # noqa: BLE001 - 管道异常按单项失败记录。
        outcome.error = f"pipeline raised: {type(exc).__name__}: {exc}"
        traceback.print_exc()
        return outcome
    try:
        outcome.send_request = send_queue.find_request(message.request_id)
    except Exception:  # noqa: BLE001 - 队列回查失败不影响主流程。
        outcome.send_request = None
    # 审计留痕回查（只读）：读口坏掉也不拖垮单项——读不到记 None，由断言判红，
    # 绝不静默折成「本轮没有原因」（假绿的一种：把量具故障读成被测件清白）。
    try:
        outcome.audit_reasons = _outcome_audit_reasons(pipeline, message.request_id)
    except Exception:  # noqa: BLE001 - 同上：形变＝None＝判红。
        outcome.audit_reasons = None
    return outcome


def print_outcome(index: int, total: int, outcome: ItemOutcome, execute: bool) -> None:
    item = outcome.item
    if outcome.error:
        print(f"[{index}/{total}] {item.label} ({item.key}) → ERROR: {outcome.error}")
        return
    receipt = outcome.receipt
    assert receipt is not None
    state = receipt.state.value
    mode = "已入队" if execute else "DRY-RUN"
    extra = f" public={receipt.public_message!r}" if receipt.public_message else ""
    print(
        f"[{index}/{total}] {item.label} ({item.key}) → {mode} state={state} "
        f"transport={receipt.transport}{extra}"
    )
    if outcome.send_request is not None:
        print(f"          ↳ {format_preview(outcome.send_request)}")
    if item.note:
        print(f"          ↳ note: {item.note}")
    if item.expect is not None:
        try:
            outcome.expect_fail_reason = item.expect(outcome)
        except Exception as exc:  # noqa: BLE001 - 断言自身不得抛异常拖垮验收。
            outcome.expect_fail_reason = (
                f"expect check raised: {type(exc).__name__}: {exc}"
            )
        verdict = (
            "PASS"
            if not outcome.expect_fail_reason
            else f"FAIL: {outcome.expect_fail_reason}"
        )
        print(f"          ↳ expect: {verdict}")


# --------------------------------------------------------------------------
# 实战自测（2026-09-13 批次）：帮助注册表命令矩阵 + 响应收集 + 私聊报告
#
# 与存量矩阵的分工（诚实边界）：
# - 存量矩阵（build_matrix）：镜像 __init__ 装配、进程内跑真实能力 → 验证
#   「命令语义处理」（能力产出什么回复）。
# - 命令矩阵（--help-matrix，本节）：从 echo._HELP_ENTRIES 全 topics 生成
#   命令清单，DRY-RUN 只构造 OneBot payload + 离线路由体检；--execute 把
#   每条命令文本经现有发送链路（管线 → 共享 SQLite 队列 → bot worker →
#   OneBot WS → QQ）投递并等待回执，收集「响应/超时/异常」三态与耗时。
#   真实 bot 进程的入站命令处理无法从外部脚本注入（需要真实 QQ 客户端），
#   故本模式不声称验证命令语义，报告措辞据此保持诚实。
# --------------------------------------------------------------------------


DEFAULT_DELIVERY_WAIT_SECONDS = 20.0
DEFAULT_PROBE_WAIT_SECONDS = 15.0
DEFAULT_WS_HOST = "127.0.0.1"
DEFAULT_WS_PORT = 3001
# 连续 N 条超时且零投递确认 → 判定 bot worker 离线，中止余项（防延迟补发轰炸）。
EARLY_OFFLINE_TIMEOUT_LIMIT = 3
_DELIVERY_TERMINAL_OK = frozenset({"sent", "redirected"})
_DELIVERY_TERMINAL_FAIL = frozenset({"failed_final", "failed_retryable"})


@dataclass(frozen=True)
class HelpTopicSpec:
    """命令矩阵条目：帮助注册表一个 topic 的主触发形态。"""

    topic: str
    admin_only: bool
    aliases: tuple[str, ...]
    trigger: str
    trigger_source: str  # "index"=从 index 提取 / "alias"=别名兜底 / "override"=定点覆盖


# 提取器对「无文本命令形态」主题的定点覆盖（保持最小，避免随注册表漂移）：
# 「链接」主题的真触发是一条平台链接，不是它的别名。
_HELP_TOPIC_OVERRIDE_TRIGGERS = {
    "链接": BILI_SAMPLE_URL,
}

# 描述性候选里出现这些标点 → 该段是说明文字而非命令形态，回退别名。
_TRIGGER_DESC_PUNCT = "，。；？！…、"
# 去掉参数占位与括注：<request_id|debug_id> [数量] （仅群聊） (note)
_TRIGGER_STRIP_BRACKETS = re.compile(r"<[^<>]*>|\[[^\[\]]*\]|（[^（）]*）|\([^()]*\)")


def extract_primary_trigger(index: str, aliases: tuple[str, ...]) -> tuple[str, str]:
    """从 index 用法串提取主触发形态；提取失败回退 aliases[0]。

    规则（按 68 条实况设计，来源可审计）：
    1. 去掉「【主题】」标题；候选 = 第一个全角冒号后的用法段；
    2. 候选含描述性标点（，。；？！…、）→ 说明文字，回退别名；
    3. 剥参数占位 <…>/[…] 与括注 （…）/(…)（连内部 | 一起去掉）；
    4. 依次按 ｜、\\s|\\s、|、或、＋、/ 取第一候选（不以 / 开头才切 /，
       保住 /bot xxx、/订阅 add）；
    5. 兜底门：空 / 残留冒号 / 非斜杠命令但长度 >8 → 回退别名
       （治「戳机器人有概率收到回应」这类描述句混入）。
    返回 (trigger, source)，source ∈ {"index", "alias"}。
    """
    fallback = aliases[0] if aliases else ""
    body = index.split("】", 1)[1].strip() if "】" in index else index.strip()
    candidate = body.split("：", 1)[1].strip() if "：" in body else body
    if not candidate or any(mark in candidate for mark in _TRIGGER_DESC_PUNCT):
        return fallback, "alias"
    candidate = _TRIGGER_STRIP_BRACKETS.sub("", candidate)
    for sep in ("｜", " | "):
        if sep in candidate:
            candidate = candidate.split(sep, 1)[0]
            break
    if "|" in candidate:
        candidate = candidate.split("|", 1)[0]
    for sep in (" 或 ", "＋", " / "):
        if sep in candidate:
            candidate = candidate.split(sep, 1)[0]
            break
    if not candidate.startswith("/"):
        candidate = candidate.split("/", 1)[0]
    candidate = candidate.strip()
    if not candidate or "：" in candidate:
        return fallback, "alias"
    if not candidate.startswith("/") and len(candidate) > 8:
        return fallback, "alias"
    return candidate, "index"


def load_help_topic_specs() -> list[HelpTopicSpec]:
    """帮助注册表（echo._HELP_ENTRIES，只读 import）→ 命令矩阵条目清单。"""
    specs: list[HelpTopicSpec] = []
    for entry in _HELP_REGISTRY:
        topic = str(entry.get("topic", "") or "").strip()
        if not topic:
            continue
        aliases = tuple(
            str(alias).strip()
            for alias in (entry.get("aliases") or ())
            if str(alias).strip()
        )
        if topic in _HELP_TOPIC_OVERRIDE_TRIGGERS:
            trigger, source = _HELP_TOPIC_OVERRIDE_TRIGGERS[topic], "override"
        else:
            trigger, source = extract_primary_trigger(
                str(entry.get("index", "") or ""), aliases
            )
            if not trigger:
                trigger, source = topic, "alias"
        specs.append(
            HelpTopicSpec(
                topic=topic,
                admin_only=bool(entry.get("admin_only", False)),
                aliases=aliases,
                trigger=trigger,
                trigger_source=source,
            )
        )
    return specs


def filter_topic_specs(
    specs: list[HelpTopicSpec], subset: str
) -> tuple[list[HelpTopicSpec], list[str]]:
    """--subset 过滤：逗号分隔 token，匹配 topic/别名（全等优先、子串兜底，
    大小写不敏感）。返回 (命中清单, 未命中 token)。subset 为空 → 全量。"""
    tokens = [
        token.strip()
        for token in str(subset or "").replace("，", ",").split(",")
        if token.strip()
    ]
    if not tokens:
        return list(specs), []

    def _matches(spec: HelpTopicSpec, folded: str) -> bool:
        haystacks = [spec.topic, *spec.aliases]
        if any(h.casefold() == folded for h in haystacks):
            return True
        return any(folded in h.casefold() for h in haystacks)

    matched: list[HelpTopicSpec] = []
    unknown: list[str] = []
    for token in tokens:
        folded = token.casefold()
        hits = [spec for spec in specs if _matches(spec, folded)]
        if hits:
            matched.extend(hits)
        else:
            unknown.append(token)
    # 去重保序（同一 spec 可能被多个 token 命中）。
    seen: set[str] = set()
    unique: list[HelpTopicSpec] = []
    for spec in matched:
        if spec.topic in seen:
            continue
        seen.add(spec.topic)
        unique.append(spec)
    return unique, unknown


def build_command_payload(
    spec: HelpTopicSpec, *, session_type: SessionType, target_id: str
) -> dict[str, Any]:
    """构造 OneBot V11 发送 payload（DRY-RUN 只构造不发送）。"""
    is_group = session_type is SessionType.GROUP
    target_value: int | str = (
        int(target_id) if str(target_id).isdigit() else str(target_id)
    )
    params: dict[str, Any] = {"message": spec.trigger, "auto_escape": False}
    if is_group:
        params["group_id"] = target_value
        action = "send_group_msg"
    else:
        params["user_id"] = target_value
        action = "send_private_msg"
    return {"action": action, "params": params, "echo": f"e2e-{spec.topic}"}


def probe_ws_online(
    host: str, port: int, timeout: float = 3.0
) -> tuple[bool, float]:
    """TCP 探测 OneBot WS 端口是否有人监听。返回 (可达, 耗时秒)。"""
    start = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, time.monotonic() - start
    except OSError:
        return False, time.monotonic() - start


def resolve_ws_probe_endpoint(explicit: str = "") -> tuple[str, int]:
    """探测端点：--ws-probe host:port > ONEBOT_WS_URLS 首条 > 默认 127.0.0.1:3001。"""
    raw = str(explicit or "").strip()
    if not raw:
        raw = str(os.environ.get("ONEBOT_WS_URLS", "") or "").split(",")[0].strip()
    if raw:
        parts = urlsplit(raw if "://" in raw else f"ws://{raw}")
        host = parts.hostname or DEFAULT_WS_HOST
        port = parts.port or DEFAULT_WS_PORT
        return str(host), int(port)
    return DEFAULT_WS_HOST, DEFAULT_WS_PORT


def classify_spec_route(
    spec: HelpTopicSpec, config: Any
) -> tuple[str, str, str]:
    """离线路由体检：主触发文本走 classify_message_route（与 base_router 同源）。
    返回 (kind, capability_id, reason)；分类自身异常折算为 error 条目不抛出。"""
    try:
        decision = classify_message_route(spec.trigger, config=config)
        return (
            str(getattr(decision.kind, "value", decision.kind)),
            str(decision.capability_id),
            str(decision.reason),
        )
    except Exception as exc:  # noqa: BLE001 - 单条体检失败不拖垮矩阵。
        return "error", "bot.ignore", f"{type(exc).__name__}: {exc}"


@dataclass
class CommandOutcome:
    """命令矩阵单项结果（响应/超时/异常三态 + 耗时）。"""

    spec: HelpTopicSpec
    request_id: str = ""
    # delivered（拿到投递确认）/ timeout（预算内未确认）/ error（失败终态/异常）/
    # blocked（策略门拦截）/ skipped（离线中止未执行）
    status: str = "skipped"
    state: str = ""
    elapsed: float = 0.0
    error: str = ""
    route_kind: str = ""
    route_capability: str = ""
    route_reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def classify_probe_outcome(queue_desc: str, state: str) -> str:
    """worker 存活探针的结论必须看**这本队列有没有 worker 会去 drain**（`1eda900` 的后半账）。

    隔离态（label 含 ``isolated``）下没人投递那条请求是**设计使然**，据此判"bot 未重启/未启用队列"
    是错诊断（本仓 10-07 现算：真机 bot 在线、探针必然超时、整轮被 rc=3 中止）⇒ 记 ``not-verified``：
    不中止，但必须当场说"这一态验不了投递"，不许静默跳过让下一个人以为验过。
    真发态（``--live-delivery``，label 含 ``live-production-queue``）超时**仍然**是 ``worker-offline``
    ——那支中止是本脚本的牙，不许因为本修被顺手磨掉。
    """
    desc = str(queue_desc or "")
    if desc.startswith("dry-run") or "in-memory" in desc:
        return "not-applicable"
    if str(state or "") in _DELIVERY_TERMINAL_OK:
        return "alive"
    if "live-production-queue" in desc:
        return "worker-offline"
    if "isolated" in desc:
        return "not-verified"
    return "worker-offline"


def probe_confirmation_text(verdict: str, elapsed: float) -> str:
    """报告行「探针 …」的措辞真身：**没拿到确认就不许写成"确认"**。

    在册形态＝把"未发生"叙述成"已发生"（与 §76.20 那枚 `bot_id="unknown"` 哨兵同族的反面：
    那次是把真发说成没发，这次会把隔离态的**零验证**说成 0.0s 秒过）。隔离/拦截/预览三态
    各有一句人话，只有 ``alive`` 允许出现"确认"二字。
    """
    if verdict == "alive":
        return f"{elapsed:.1f}s 确认"
    if verdict == "not-verified":
        return "存活未验（队列落在临时库＝无 worker 会投这本库；要验请带 `--live-delivery`）"
    if verdict == "not-applicable":
        return "存活未验（预览态没有可探的队列）"
    if verdict == "probe-blocked":
        return "存活未验（探针被策略门拦截，未入队）"
    return f"未确认（{verdict}）"


def wait_for_delivery(
    queue: Any,
    *,
    request_id: str,
    budget: float,
    poll_interval: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[str, float]:
    """轮询共享队列直至终态或预算耗尽。返回 (状态, 耗时秒)。

    终态：sent/redirected（投递确认）与 failed_final/failed_retryable（确认失败）；
    预算耗尽返回 "timeout"（bot worker 离线/卡住/UNKNOWN 未决都落这里——不悬挂）。
    sleep/monotonic 可注入，供离线测试用微预算验证轮询语义。"""
    start = monotonic()
    while True:
        try:
            entry = queue.find_request(request_id)
        except Exception as exc:  # noqa: BLE001 - 队列查询异常按失败终态折算。
            return f"query_error:{type(exc).__name__}", monotonic() - start
        state = str(getattr(entry, "state", "") or "") if entry is not None else ""
        if state in _DELIVERY_TERMINAL_OK or state in _DELIVERY_TERMINAL_FAIL:
            return state, monotonic() - start
        if monotonic() - start >= budget:
            return "timeout", monotonic() - start
        sleep(poll_interval)


def status_from_delivery_state(state: str) -> str:
    if state in _DELIVERY_TERMINAL_OK:
        return "delivered"
    if state.startswith(("failed", "query_error")):
        return "error"
    return "timeout"


def summarize_results(outcomes: list[CommandOutcome]) -> dict[str, Any]:
    counts = Counter(outcome.status for outcome in outcomes)
    attempted = sum(counts[name] for name in ("delivered", "timeout", "error", "blocked"))
    pass_rate = (counts["delivered"] * 100.0 / attempted) if attempted else 0.0
    return {
        "total": len(outcomes),
        "attempted": attempted,
        "delivered": counts["delivered"],
        "timeout": counts["timeout"],
        "error": counts["error"],
        "blocked": counts["blocked"],
        "skipped": counts["skipped"],
        "pass_rate": round(pass_rate, 1),
    }


def render_run_report(
    outcomes: list[CommandOutcome],
    *,
    mode: str,
    target_desc: str,
    generated_at: str,
    subset_desc: str = "无",
    wait_budget: float = DEFAULT_DELIVERY_WAIT_SECONDS,
    ws_desc: str = "",
    headline: str = "",
) -> str:
    """给超管的人读汇总报告：通过率/超时清单/异常清单/建议复查项。"""
    summary = summarize_results(outcomes)
    lines = [
        "【E2E 实战自测报告】",
        (
            f"生成：{generated_at}｜模式：{mode}｜目标：{target_desc}"
            f"｜矩阵：{summary['total']} 主题（subset={subset_desc}）"
        ),
    ]
    if ws_desc:
        lines.append(f"链路探测：{ws_desc}")
    if headline:
        lines.append(f"摘要：{headline}")
    lines.extend(
        (
            "■ 总览",
            (
                f"尝试 {summary['attempted']}｜响应 {summary['delivered']}"
                f"｜超时 {summary['timeout']}｜异常 {summary['error']}"
                f"｜拦截 {summary['blocked']}｜未执行 {summary['skipped']}"
            ),
            (
                f"通过率 {summary['pass_rate']}%（响应/尝试；超时预算 {wait_budget:g}s）"
                if summary["attempted"]
                else f"无投递尝试（超时预算 {wait_budget:g}s）"
            ),
        )
    )
    timeouts = [o for o in outcomes if o.status == "timeout"]
    errors = [o for o in outcomes if o.status in ("error", "blocked")]
    skipped = [o for o in outcomes if o.status == "skipped"]
    lines.append("■ 超时清单")
    if timeouts:
        lines.extend(
            f"- {o.spec.topic}（{o.spec.trigger}）最后状态={o.state or '无'} 耗时={o.elapsed:.1f}s"
            for o in timeouts
        )
    else:
        lines.append("- 无")
    lines.append("■ 异常清单")
    if errors:
        lines.extend(
            f"- {o.spec.topic}（{o.spec.trigger}）状态={o.state or '无'}"
            f"{('：' + o.error) if o.error else ''}"
            for o in errors
        )
    else:
        lines.append("- 无")
    route_missed = [o for o in outcomes if o.route_kind in ("ignore", "chat", "error")]
    lines.append(
        "■ 路由未命中主题（文档型/自动触发型，或主形态需带参数如「天气 城市」「点歌 歌名」；"
        "仅供参考，不计入失败）"
    )
    if route_missed:
        lines.append(
            "- " + "、".join(f"{o.spec.topic}({o.route_kind})" for o in route_missed)
        )
    else:
        lines.append("- 无")
    lines.append("■ 建议复查项")
    suggestions: list[str] = []
    if timeouts:
        suggestions.append(
            f"超时 {len(timeouts)} 项：确认 bot 进程在线、send-queue worker 在投递"
            "（/bot status 看 queue 状态），再单独重跑 --subset 复测。"
        )
    if errors:
        suggestions.append(
            f"异常 {len(errors)} 项：按清单逐项排查；admin 主题需 --sender-id 为超管/管理员。"
        )
    if skipped:
        suggestions.append(f"未执行 {len(skipped)} 项：早停/离线中止所致，恢复后重跑补测。")
    if not suggestions:
        suggestions.append("全链路投递确认正常，无必查项。")
    lines.extend(f"{index}. {text}" for index, text in enumerate(suggestions, 1))
    return "\n".join(lines)


def write_report_file(report_text: str, report_file: str = "") -> Path:
    base = Path(report_file) if report_file else None
    path = base if base and str(base.parent) else (
        Path(tempfile.gettempdir())
        / f"e2e_report_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_text, encoding="utf-8")
    return path


def deliver_or_write_report(
    report_text: str,
    *,
    runtime: E2eRuntime,
    pipeline: RuntimePipeline | None,
    execute: bool,
    online: bool,
    report_file: str = "",
) -> str:
    """报告投递：bot 在线且 --execute → 经发送链路私聊全部超管；
    否则写文件（--report-file 或 %TEMP%）并返回路径描述。"""
    saved = write_report_file(report_text, report_file)
    delivered_desc: list[str] = []
    if execute and online and pipeline is not None:
        admin_ids = [
            str(aid).strip()
            for aid in (getattr(runtime.config, "bot_super_admin_user_ids", []) or [])
            if str(aid).strip()
        ]
        if not admin_ids:
            delivered_desc.append("未配置 BOT_SUPER_ADMIN_USER_IDS，报告仅落盘")
        for admin_id in admin_ids:
            message = synthesize_message(
                text="E2E 实战自测报告",
                session_type=SessionType.PRIVATE,
                target_id=admin_id,
                sender_id=admin_id,
                bot_id=runtime.bot_id,
                seq=0,
            )
            try:
                receipt = pipeline.handle(
                    message,
                    _text_capability(runtime, body=report_text),
                    capability_id="bot.text",
                )
                delivered_desc.append(
                    f"超管 {admin_id} 私聊报告已入队（state={receipt.state.value}）"
                )
            except Exception as exc:  # noqa: BLE001 - 单个超管投递失败不拖垮其余。
                delivered_desc.append(f"超管 {admin_id} 私聊报告入队失败：{exc}")
    return "；".join(delivered_desc + [f"报告文件：{saved}"])


def build_results_document(
    outcomes: list[CommandOutcome],
    *,
    mode: str,
    target_desc: str,
    subset: list[str],
    ws_endpoint: tuple[str, int],
    ws_online: bool,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "schema": "e2e_help_matrix_results/v1",
        "generated_at": generated_at,
        "mode": mode,
        "target": target_desc,
        "subset": subset,
        "ws_probe": {
            "host": ws_endpoint[0],
            "port": ws_endpoint[1],
            "online": ws_online,
        },
        "summary": summarize_results(outcomes),
        "outcomes": [
            {
                "topic": outcome.spec.topic,
                "trigger": outcome.spec.trigger,
                "trigger_source": outcome.spec.trigger_source,
                "admin_only": outcome.spec.admin_only,
                "route_kind": outcome.route_kind,
                "route_capability": outcome.route_capability,
                "status": outcome.status,
                "state": outcome.state,
                "elapsed_ms": round(outcome.elapsed * 1000, 1),
                "error": outcome.error,
                "request_id": outcome.request_id,
            }
            for outcome in outcomes
        ],
    }


def write_json_document(document: dict[str, Any], json_out: str) -> Path:
    path = (
        Path(json_out)
        if json_out
        else Path(tempfile.gettempdir())
        / f"e2e_help_matrix_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


# --------------------------------------------------------------------------
# 实战自测：--selftest（全离线自检，pytest 同源）
# --------------------------------------------------------------------------


def _scripted_queue(states: list[str]) -> Any:
    """wait_for_delivery 的离线脚本队列：按调用次序吐状态，末态保持。"""

    class _ScriptedQueue:
        def __init__(self, sequence: list[str]) -> None:
            self._sequence = sequence
            self.calls = 0

        def find_request(self, request_id: str) -> Any:
            self.calls += 1
            index = min(self.calls - 1, len(self._sequence) - 1)
            return SimpleNamespace(state=self._sequence[index])

    return _ScriptedQueue(states)


def _selftest_config() -> Config:
    # 与离线测试同口径：关安静时间/好感度，绝不打开 Runtime 真实库。
    return Config(bot_quiet_hours_enabled=False, bot_affinity_enabled=False)


_SELFTEST_TRIGGER_EXPECTATIONS = {
    "状态": "/bot status",
    "为什么": "/bot why",
    "决策": "/bot decision",
    "记忆": "/bot memory add",
    "历史": "/bot history clear",
    "怪癖": "/bot quirk list",
    "设置": "/bot runtime set",
    "身份": "/bot identity show",
    "帮助": "/bot help",
    "订阅": "/订阅 add",
    "点歌": "点歌",
    "天气": "天气",
    "行情": "行情",
    "个股行情": "英伟达股价",
    "汇率": "汇率",
    "快报": "快报",
    "占卜": "占卜",
    "提醒": "提醒",  # '12点提醒我写作业' 9 字触发非斜杠长度门 → 别名兜底
    "随机图": "随机图",
    "好感度": "好感度",
    "媒体归档": "收藏",
    "自然语言": "帮我查杭州天气",
    "模型": "/bot model list",
    "用量": "/bot model usage",
    "文件": "文件",
    "群文件": "/bot 群文件",
    "Epic": "epic",
}


def run_selftest() -> tuple[int, list[str]]:
    """全离线自检：矩阵生成/触发提取/subset/payload/报告/探针/轮询。
    返回 (退出码, 逐项检查行)；不依赖 bot 在线、不读 .env、不联网。"""
    lines: list[str] = []
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        if not ok:
            failures += 1
        lines.append(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))

    # 1. 帮助注册表加载（真相源 echo._HELP_ENTRIES，只读 import）。
    specs = load_help_topic_specs()
    topics = [spec.topic for spec in specs]
    ok = len(specs) >= 60 and len(topics) == len(set(topics)) and all(
        spec.aliases and spec.trigger for spec in specs
    )
    check("registry_load", ok, f"topics={len(specs)}")

    # 2. 主触发形态提取（逐条对照实跑钉住的期望表）。
    by_topic = {spec.topic: spec for spec in specs}
    mismatches = [
        f"{topic}: 期望 {expected!r} 实得 {by_topic[topic].trigger!r}"
        f"({by_topic[topic].trigger_source})"
        for topic, expected in _SELFTEST_TRIGGER_EXPECTATIONS.items()
        if by_topic[topic].trigger != expected
    ]
    check("trigger_extraction", not mismatches, "; ".join(mismatches) or "全部命中")

    # 3. 文档型主题回退别名且来源可审计。
    doc_topics = ["忽略", "戳一戳", "表情收库", "聊天"]
    bad = [
        topic
        for topic in doc_topics
        if by_topic[topic].trigger_source != "alias"
        or by_topic[topic].trigger not in by_topic[topic].aliases
    ]
    check("trigger_alias_fallback", not bad, f"异常项={bad or '无'}")

    # 4. 定点覆盖（链接 → 平台链接样例）。
    check(
        "trigger_override",
        by_topic["链接"].trigger == BILI_SAMPLE_URL
        and by_topic["链接"].trigger_source == "override",
    )

    # 5. --subset 过滤：命中 + 未命中 token。
    matched, unknown = filter_topic_specs(specs, "天气,点歌,不存在的主题")
    check(
        "subset_filter",
        [spec.topic for spec in matched] == ["天气", "点歌"]
        and unknown == ["不存在的主题"],
    )

    # 6. payload 构造（群/私聊两形态）。
    weather = by_topic["天气"]
    group_payload = build_command_payload(
        weather, session_type=SessionType.GROUP, target_id="123456"
    )
    private_payload = build_command_payload(
        weather, session_type=SessionType.PRIVATE, target_id="10001"
    )
    check(
        "payload_build",
        group_payload["action"] == "send_group_msg"
        and group_payload["params"]["group_id"] == 123456
        and group_payload["params"]["message"] == "天气"
        and private_payload["action"] == "send_private_msg"
        and private_payload["params"]["user_id"] == 10001,
    )

    # 7. 离线路由体检：全 topics 不抛异常；管理命令命中命令路由族。
    #    2026-09-18 核心链路排查：原 carve-out（未提交批次 runtime/timesync.py 的
    #    now() 缺 global _SHARED 声明 → UnboundLocalError，令「提醒」信号词路由
    #    必崩）经实跑确认**已修复**——真身 domains/schedule/timesync/timesync.py
    #    的 now() 已带 `global _SHARED, _SHARED_SIGNATURE`，直调返回正确时间。
    #    据此移除该特判：路由异常一律判 FAIL，不再有被静默降级为 WARN 的盲区。
    config = _selftest_config()
    route_probed: list[tuple[str, str, str]] = []
    for spec in specs:
        kind, capability, reason = classify_spec_route(spec, config)
        route_probed.append((spec.topic, f"{kind}/{capability}", reason))
    status_kind, status_capability, _ = classify_spec_route(by_topic["状态"], config)
    route_errors = {
        topic
        for topic, route, _reason in route_probed
        if route.startswith("error/")
    }
    check(
        "route_probe",
        not route_errors and status_capability.startswith("bot."),
        f"status→{status_kind}/{status_capability}; "
        f"路由异常={sorted(route_errors) or '无'}",
    )

    # 8. 报告渲染：三清单 + 通过率 + 建议复查。
    def _outcome(topic: str, status: str, **kwargs: Any) -> CommandOutcome:
        return CommandOutcome(spec=by_topic[topic], status=status, **kwargs)

    sample = [
        _outcome("天气", "delivered", state="sent", elapsed=1.2),
        _outcome("点歌", "delivered", state="sent", elapsed=2.5),
        _outcome("行情", "timeout", state="queued", elapsed=20.0),
        _outcome("汇率", "error", state="failed_final", error="boom"),
        _outcome("占卜", "skipped"),
    ]
    report = render_run_report(
        sample,
        mode="execute",
        target_desc="group:555",
        generated_at="2026-09-13 00:00:00",
    )
    check(
        "report_render",
        all(
            token in report
            for token in ("通过率 50.0%", "超时清单", "异常清单", "建议复查项", "行情")
        ),
    )

    # 9. WS 探针离线快速失败（本机不可能监听的端口）。
    online, elapsed = probe_ws_online("127.0.0.1", 1, timeout=1.5)
    check("ws_probe_offline", not online and elapsed < 5.0, f"elapsed={elapsed:.2f}s")

    # 10. 投递轮询：终态确认 / 预算超时 / 失败终态（微预算+注入时钟，零等待）。
    state_ok, took = wait_for_delivery(
        _scripted_queue(["queued", "queued", "sent"]),
        request_id="x",
        budget=5.0,
        poll_interval=0.0,
        sleep=lambda _s: None,
    )
    state_timeout, _ = wait_for_delivery(
        _scripted_queue(["queued"]), request_id="x", budget=0.0, poll_interval=0.0
    )
    state_fail, _ = wait_for_delivery(
        _scripted_queue(["failed_final"]), request_id="x", budget=1.0, poll_interval=0.0
    )
    check(
        "wait_for_delivery",
        state_ok == "sent"
        and status_from_delivery_state(state_ok) == "delivered"
        and state_timeout == "timeout"
        and status_from_delivery_state(state_timeout) == "timeout"
        and state_fail == "failed_final"
        and status_from_delivery_state(state_fail) == "error",
        f"ok={state_ok}/{took:.2f}s timeout={state_timeout} fail={state_fail}",
    )

    # 11. 汇总与 JSON 文档结构。
    summary = summarize_results(sample)
    document = build_results_document(
        sample,
        mode="execute",
        target_desc="group:555",
        subset=["天气"],
        ws_endpoint=("127.0.0.1", 3001),
        ws_online=False,
        generated_at="2026-09-13 00:00:00",
    )
    check(
        "summary_json",
        summary["attempted"] == 4
        and summary["delivered"] == 2
        and summary["timeout"] == 1
        and summary["error"] == 1
        and summary["skipped"] == 1
        and summary["pass_rate"] == 50.0
        and document["summary"] == summary
        and len(document["outcomes"]) == len(sample),
    )

    # 12. 2026-09-15 夜批 §26 新增矩阵项：结构完整 + 决策查询双路径离线语义
    #     （注入内存 sink，零磁盘；管理员出痕迹摘要、普通成员温和拒绝）。
    fake_rt = E2eRuntime(
        config=config,
        runtime_settings={},
        render_backend=None,
        execute=False,
        city="",
        bot_id="selftest-bot",
        sender_id="10000",
    )
    matrix = build_matrix(fake_rt)
    matrix_keys = [item.key for item in matrix]
    nightly_keys = {
        "decision-query-admin",
        "decision-query-member",
        "group-failure-ack",
        "group-busy-silent",
    }
    check(
        "nightly_matrix_structure",
        len(matrix_keys) == len(set(matrix_keys)) and nightly_keys <= set(matrix_keys),
        f"items={len(matrix_keys)}",
    )
    admin_body = str(
        build_decision_query_result(
            request_id="st-admin",
            actor_roles=["super_admin", "admin"],
            sink=InMemoryDecisionTraceSink(),
        ).body
    )
    member_body = str(
        build_decision_query_result(
            request_id="st-member", actor_roles=[], sink=InMemoryDecisionTraceSink()
        ).body
    )
    check(
        "decision_query_paths",
        "决策影子痕迹" in admin_body
        and "管理员" in member_body
        and "决策影子痕迹：" not in member_body,
        f"admin={admin_body.splitlines()[0][:48]!r} member={member_body[:48]!r}",
    )

    # 13. A-19 群失败降级：正向补池内短句 + 负样本（超载快败）零反馈
    #     （离线真实管线执行：策略→能力→A-19 通知→队列回查→expect 全链）。
    a19_queue = InMemorySendQueue(audit_logger=InMemoryAuditLogger())
    a19_pipeline = RuntimePipeline(
        send_queue=a19_queue,
        audit_logger=InMemoryAuditLogger(),
        rate_limiter=build_rate_limiter(config),
        quiet_hours_checker=build_quiet_hours_checker(config),
    )
    by_key = {item.key: item for item in matrix}
    a19_failures: dict[str, str] = {}
    for key, seq in (("group-failure-ack", 1), ("group-busy-silent", 2)):
        item = by_key[key]
        message = synthesize_message(
            text=item.trigger_text(fake_rt),
            session_type=SessionType.GROUP,
            target_id="555",
            sender_id="10000",
            bot_id="selftest-bot",
            seq=seq,
        )
        outcome = ItemOutcome(
            item=item,
            request_id=message.request_id,
            trigger_text=item.trigger_text(fake_rt),
            session_type=SessionType.GROUP.value,
        )
        try:
            outcome.receipt = a19_pipeline.handle(
                message, item.build(fake_rt), capability_id=item.capability_id
            )
            try:
                outcome.send_request = a19_queue.find_request(message.request_id)
            except Exception:  # noqa: BLE001 - 队列回查失败按无回执处理。
                outcome.send_request = None
            a19_failures[key] = item.expect(outcome) if item.expect else ""
        except Exception as exc:  # noqa: BLE001 - 自检内异常按 FAIL 折算。
            a19_failures[key] = f"{type(exc).__name__}: {exc}"
    check(
        "a19_group_failure",
        not a19_failures["group-failure-ack"]
        and not a19_failures["group-busy-silent"],
        f"ack={a19_failures['group-failure-ack'] or 'PASS'} "
        f"busy={a19_failures['group-busy-silent'] or 'PASS'}",
    )

    lines.insert(0, f"===== E2E selftest：{len(lines) - failures}/{len(lines)} 项通过 =====")
    return (0 if failures == 0 else 1), lines


# --------------------------------------------------------------------------
# 实战自测：--help-matrix 运行器
# --------------------------------------------------------------------------


def _print_help_matrix_dry_run(
    outcomes: list[CommandOutcome], total: int
) -> None:
    for index, outcome in enumerate(outcomes, 1):
        spec = outcome.spec
        payload = outcome.payload
        params = payload.get("params", {}) if isinstance(payload, dict) else {}
        route = f"{outcome.route_kind}/{outcome.route_capability}"
        admin = "Y" if spec.admin_only else "N"
        print(
            f"[{index}/{total}] {spec.topic} admin={admin} 触发={spec.trigger!r}"
            f"（{spec.trigger_source}）路由={route}"
        )
        print(
            f"          ↳ payload: {payload.get('action', '?')} "
            f"message={params.get('message', '')!r} target={params.get('group_id', params.get('user_id'))}"
        )


def run_help_matrix(args: argparse.Namespace) -> int:
    _reconfigure_stdio()
    runtime = build_runtime(
        env_file=args.env,
        execute=bool(args.execute),
        city=str(args.city or "").strip(),
        bot_id=str(args.bot_id or "").strip(),
        sender_id=str(
            args.sender_id or str(args.target_user or "").strip() or "10000"
        ).strip(),
        live_delivery=bool(getattr(args, "live_delivery", False)),
    )
    specs, unknown = filter_topic_specs(load_help_topic_specs(), args.subset)
    if unknown:
        print(f"[提示] --subset 未命中 token：{unknown}", file=sys.stderr)
    if not specs:
        print("--subset 无匹配主题", file=sys.stderr)
        return 2

    if args.target_group:
        session_type = SessionType.GROUP
        target_id = str(args.target_group).strip()
        allowed, reason = check_group_allowed(runtime, target_id)
        print(f"[安全阀] {reason}")
        if not allowed:
            return 2
    else:
        session_type = SessionType.PRIVATE
        target_id = str(args.target_user or "").strip()
        if target_id and not str(args.sender_id or "").strip():
            args.sender_id = target_id
        print(f"[安全阀] 私聊目标 {target_id}")

    ws_endpoint = resolve_ws_probe_endpoint(getattr(args, "ws_probe", "") or "")
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    target_desc = f"{session_type.value}:{target_id}"
    subset_list = [token for token in str(args.subset or "").replace("，", ",").split(",") if token.strip()]
    mode = "execute" if args.execute else "dry-run"

    outcomes: list[CommandOutcome] = []
    for spec in specs:
        outcome = CommandOutcome(spec=spec)
        outcome.payload = build_command_payload(
            spec, session_type=session_type, target_id=target_id
        )
        outcome.route_kind, outcome.route_capability, outcome.route_reason = (
            classify_spec_route(spec, runtime.config)
        )
        outcomes.append(outcome)

    if not args.execute:
        _print_help_matrix_dry_run(outcomes, len(outcomes))
        route_missed = sum(
            1 for o in outcomes if o.route_kind in ("ignore", "chat", "error")
        )
        print(
            f"\nDRY-RUN：{len(outcomes)} 条命令 payload 已构造，未发送。"
            f"路由未命中 {route_missed} 条（文档型/自动触发型或触发词失效，见逐条路由列）。"
        )
        document = build_results_document(
            outcomes,
            mode=mode,
            target_desc=target_desc,
            subset=subset_list,
            ws_endpoint=ws_endpoint,
            ws_online=False,
            generated_at=generated_at,
        )
        if args.json_out:
            print(f"[JSON] {write_json_document(document, args.json_out)}")
        if args.report:
            report = render_run_report(
                outcomes,
                mode=mode,
                target_desc=target_desc,
                generated_at=generated_at,
                subset_desc=",".join(subset_list) or "无",
                headline="DRY-RUN 矩阵审计（未发送）：投递验收请加 --execute。",
            )
            print(f"[报告] {deliver_or_write_report(report, runtime=runtime, pipeline=None, execute=False, online=False, report_file=args.report_file)}")
        return 0

    # ---- --execute：探测 → 探针 → 逐条发送+等回执 → 汇总/JSON/报告 ----
    ws_online, ws_elapsed = probe_ws_online(*ws_endpoint, timeout=3.0)
    print(
        f"[探测] OneBot WS {ws_endpoint[0]}:{ws_endpoint[1]} "
        f"{'可达' if ws_online else '不可达'}（{ws_elapsed:.2f}s）"
    )
    if not ws_online:
        report = render_run_report(
            outcomes,
            mode=mode,
            target_desc=target_desc,
            generated_at=generated_at,
            subset_desc=",".join(subset_list) or "无",
            ws_desc=f"{ws_endpoint[0]}:{ws_endpoint[1]} 不可达（离线快速失败，未发送任何消息）",
            headline="离线中止：bot/协议端（SnowLuma）未在线，全部条目未执行。",
        )
        for outcome in outcomes:
            outcome.status = "skipped"
            outcome.state = "offline"
        document = build_results_document(
            outcomes, mode=mode, target_desc=target_desc, subset=subset_list,
            ws_endpoint=ws_endpoint, ws_online=False, generated_at=generated_at,
        )
        json_path = write_json_document(document, args.json_out)
        report_desc = deliver_or_write_report(
            report, runtime=runtime, pipeline=None, execute=False, online=False,
            report_file=args.report_file,
        )
        print(f"[离线] 未发送任何消息。JSON：{json_path}")
        print(f"[报告] {report_desc}")
        return 3

    audit_logger = InMemoryAuditLogger()
    try:
        send_queue, queue_desc = choose_send_queue(runtime, audit_logger)
    except E2eSafetyError as exc:
        print(f"[安全阀] {exc}", file=sys.stderr)
        return 2
    print(f"[队列] {queue_desc}")
    warn_live_delivery(queue_desc)
    pipeline = build_pipeline(runtime, send_queue)

    # worker 存活探针：一条无害文本，预算内拿到投递确认才继续（防 68 条延迟补发轰炸）。
    probe_outcome = CommandOutcome(spec=HelpTopicSpec(
        topic="(探针)", admin_only=False, aliases=(), trigger="e2e-probe", trigger_source="override",
    ))
    probe_message = synthesize_message(
        text="E2E 实战自测探针（worker 存活探测，可忽略）",
        session_type=session_type,
        target_id=target_id,
        sender_id=runtime.sender_id,
        bot_id=runtime.bot_id,
        seq=0,
    )
    probe_outcome.request_id = probe_message.request_id
    try:
        probe_receipt = pipeline.handle(
            probe_message,
            _text_capability(runtime, body="E2E 实战自测探针（worker 存活探测，可忽略）"),
            capability_id="bot.text",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[探针] 管线异常，按离线中止：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    probe_verdict = "pending"
    if probe_receipt.state.value in ("blocked", "skipped"):
        probe_verdict = "probe-blocked"
        print(
            f"[探针] 被策略门拦截（state={probe_receipt.state.value}），"
            "无法验证 worker 存活；改由运行中连续超时早停兜底。"
        )
    else:
        if classify_probe_outcome(queue_desc, "pending") == "not-verified":
            probe_verdict = "not-verified"
            # 隔离态＝这本临时库压根没有 worker 会读，等下去必然超时 ⇒ 不烧 `--probe-wait` 预算。
            # 🔴 但必须当场说"这一态验不了投递"——静默跳过会让下一个人以为探针跑过了（在册形态：
            # 门会缩不会红）。逐项形状断言照常执行，不受本分支影响。
            print(
                "[探针] 队列落在临时库（隔离态）＝无 worker 会投递这本库 ⇒ worker 存活**本态不可验**；"
                "要真投递请显式带 `--live-delivery`。以下各项仍按形状断言逐条执行。"
            )
        else:
            state, took = wait_for_delivery(
                send_queue,
                request_id=probe_message.request_id,
                budget=float(args.probe_wait),
            )
            probe_verdict = classify_probe_outcome(queue_desc, state)
            probe_outcome.status = status_from_delivery_state(state)
            probe_outcome.state, probe_outcome.elapsed = state, took
            if probe_verdict != "alive":
                report = render_run_report(
                    outcomes,
                    mode=mode,
                    target_desc=target_desc,
                    generated_at=generated_at,
                    subset_desc=",".join(subset_list) or "无",
                    ws_desc=f"{ws_endpoint[0]}:{ws_endpoint[1]} TCP 可达，但 worker {args.probe_wait:g}s 内无投递确认",
                    headline="离线中止：发送队列 worker 无响应（bot 未重启或未启用发送队列），全部条目未执行。",
                )
                for outcome in outcomes:
                    outcome.status = "skipped"
                    outcome.state = "worker-offline"
                document = build_results_document(
                    outcomes, mode=mode, target_desc=target_desc, subset=subset_list,
                    ws_endpoint=ws_endpoint, ws_online=True, generated_at=generated_at,
                )
                json_path = write_json_document(document, args.json_out)
                report_desc = deliver_or_write_report(
                    report, runtime=runtime, pipeline=None, execute=False, online=False,
                    report_file=args.report_file,
                )
                print(f"[离线] 探针超时（state={state}，{took:.1f}s）。JSON：{json_path}")
                print(f"[报告] {report_desc}")
                return 3
            print(f"[探针] worker 在线（state={state}，{took:.1f}s），开始逐条发送。")

    total = len(outcomes)
    delivered_so_far = 0
    timeout_streak = 0
    offline_abort = False
    for index, outcome in enumerate(outcomes, 1):
        spec = outcome.spec
        if offline_abort:
            outcome.status, outcome.state = "skipped", "offline-abort"
            continue
        message = synthesize_message(
            text=spec.trigger,
            session_type=session_type,
            target_id=target_id,
            sender_id=runtime.sender_id,
            bot_id=runtime.bot_id,
            seq=index,
        )
        outcome.request_id = message.request_id
        try:
            receipt = pipeline.handle(
                message,
                _text_capability(runtime, body=spec.trigger),
                capability_id="bot.text",
            )
        except Exception as exc:  # noqa: BLE001 - 单项异常不拖垮矩阵。
            outcome.status, outcome.error = "error", (
                f"pipeline raised: {type(exc).__name__}: {exc}"
            )
            timeout_streak = 0
            print(f"[{index}/{total}] {spec.topic} → ERROR: {outcome.error}")
            continue
        if receipt.state.value in ("blocked", "skipped"):
            outcome.status = "blocked"
            outcome.state = receipt.state.value
            print(
                f"[{index}/{total}] {spec.topic} → 拦截 state={receipt.state.value}"
                f"{' public=' + repr(receipt.public_message) if receipt.public_message else ''}"
            )
        else:
            state, took = wait_for_delivery(
                send_queue,
                request_id=message.request_id,
                budget=float(args.wait),
            )
            outcome.status = status_from_delivery_state(state)
            outcome.state, outcome.elapsed = state, took
            print(
                f"[{index}/{total}] {spec.topic} → {outcome.status}"
                f" state={state} 耗时={took:.1f}s"
            )
        if outcome.status == "delivered":
            delivered_so_far += 1
            timeout_streak = 0
        elif outcome.status == "timeout":
            timeout_streak += 1
            if delivered_so_far == 0 and timeout_streak >= EARLY_OFFLINE_TIMEOUT_LIMIT:
                offline_abort = True
                print(
                    f"[早停] 连续 {timeout_streak} 条超时且零投递确认，判定 worker 离线，"
                    f"中止余下 {total - index} 条（防 bot 重启后延迟补发轰炸）。",
                    file=sys.stderr,
                )
        else:
            timeout_streak = 0
        if index < total and args.interval > 0:
            time.sleep(args.interval)

    summary = summarize_results(outcomes)
    print("\n===== 命令矩阵验收汇总 =====")
    for outcome in outcomes:
        mark = {
            "delivered": "·",
            "timeout": "!",
            "error": "✗",
            "blocked": "✗",
            "skipped": "-",
        }.get(outcome.status, "?")
        suffix = (
            f" state={outcome.state}"
            + (f" 耗时={outcome.elapsed:.1f}s" if outcome.elapsed else "")
            + (f" {outcome.error}" if outcome.error else "")
        )
        print(f"{mark} {outcome.spec.topic:12s} {outcome.status}{suffix}")
    print(
        f"共 {summary['total']} 项：响应 {summary['delivered']}"
        f"｜超时 {summary['timeout']}｜异常 {summary['error']}"
        f"｜拦截 {summary['blocked']}｜未执行 {summary['skipped']}"
        f"｜通过率 {summary['pass_rate']}%。"
    )
    document = build_results_document(
        outcomes, mode=mode, target_desc=target_desc, subset=subset_list,
        ws_endpoint=ws_endpoint, ws_online=ws_online, generated_at=generated_at,
    )
    json_path = write_json_document(document, args.json_out)
    print(f"[JSON] {json_path}")
    exit_code = 0 if summary["timeout"] == 0 and summary["error"] == 0 and summary["blocked"] == 0 else 1
    if args.report:
        report = render_run_report(
            outcomes,
            mode=mode,
            target_desc=target_desc,
            generated_at=generated_at,
            subset_desc=",".join(subset_list) or "无",
            wait_budget=float(args.wait),
            ws_desc=(
                f"{ws_endpoint[0]}:{ws_endpoint[1]} 可达，探针 "
                + probe_confirmation_text(probe_verdict, probe_outcome.elapsed)
            ),
            headline=(
                "离线早停：部分条目未执行。" if offline_abort else ""
            ),
        )
        report_desc = deliver_or_write_report(
            report,
            runtime=runtime,
            pipeline=pipeline,
            execute=True,
            online=not offline_abort,
            report_file=args.report_file,
        )
        print(f"[报告] {report_desc}")
    return exit_code


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _reconfigure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined, union-attr]
        except (AttributeError, OSError):
            pass


# ---- W1-④ 一键体检（2026-09-30 代理链事故波）----

def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"')
    except OSError:
        return values
    return values


def _discover_env_values(explicit: str) -> dict[str, str]:
    candidates = [Path(explicit)] if explicit else []
    repo_root = Path(__file__).resolve().parents[1]
    candidates.append(repo_root / ".env")
    for candidate in candidates:
        if candidate.is_file():
            return _parse_env_file(candidate)
    return {}


def run_check_llm_chain(env_values: dict[str, str]) -> int:
    """bot→网关→应急地板→上游域双路 全矩阵只读体检。

    判定口径：每个上游域「至少一条路径可达」即算活（toolcode.cc 直连被
    重置属设计内，经代理可达即绿）；返回 0=全绿，1=有关键腿断。
    """
    from plugins.bot_unified_runtime.domains.ops.network_patrol import (
        PATROL_TARGETS_DEFAULT,
        probe_https,
        probe_tcp,
    )
    from scripts.llm_chain_selfcheck import (
        find_emergency_floor,
        scan_registry_payloads,
    )

    def _mark(ok: bool, detail: str) -> str:
        return f"{'ok':>2} ({detail[:24]})" if ok else f"DOWN ({detail[:24]})"

    failures = 0
    print("==== LLM 链一键体检（只读探活；无任何发送路径）====")
    gateway = (env_values.get("BOT_CHAT_BASE_URL") or "http://127.0.0.1:8090/v1").strip()
    parts = urlsplit(gateway)
    gateway_host = parts.hostname or "127.0.0.1"
    gateway_port = parts.port or (443 if parts.scheme == "https" else 80)
    gateway_ok = probe_tcp(gateway_host, gateway_port)
    if not gateway_ok:
        failures += 1
    print(
        f"[1] bot → 网关 {gateway_host}:{gateway_port}: "
        f"{'ok' if gateway_ok else 'UNREACHABLE'}"
    )

    default_data_dir = (
        Path(__file__).resolve().parents[1].parent / "ChatBot_Runtime" / "data"
    )
    data_dir = Path(env_values.get("BOT_RUNTIME_DATA_DIR") or default_data_dir)
    payloads = scan_registry_payloads(data_dir / "settings")
    floor = find_emergency_floor(payloads)
    floor_ok = False
    if floor:
        floor_parts = urlsplit(floor)
        floor_ok = probe_tcp(
            floor_parts.hostname or "127.0.0.1", floor_parts.port or 11434
        )
    if not (floor and floor_ok):
        failures += 1
    if not floor:
        print("[2] 应急地板: MISSING（注册表无 127.0.0.1:11434 直连档——不哑兜底是空头支票）")
    else:
        print(
            f"[2] 应急地板 {floor}: {'ok' if floor_ok else 'UNREACHABLE（Ollama 没开？）'}"
        )

    proxy = (env_values.get("BOT_DOWNLOAD_PROXY") or "http://127.0.0.1:7890").strip()
    extra = (env_values.get("BOT_NETWORK_PATROL_DOMAINS") or "").strip()
    targets = (
        [part.strip() for part in extra.replace(";", ",").split(",") if part.strip()]
        or list(PATROL_TARGETS_DEFAULT)
    )
    clash_port = urlsplit(proxy).port or 7890
    clash_alive = probe_tcp("127.0.0.1", clash_port)
    if not clash_alive:
        failures += 1
    print(f"[3] Clash {proxy}: {'ok' if clash_alive else 'DOWN'}；上游域双腿：")
    print(f"    {'domain':<28} {'direct':<34} proxy")
    for domain in targets:
        d_ok, d_detail = probe_https(f"https://{domain}/", proxy="", timeout=10.0)
        if clash_alive:
            p_ok, p_detail = probe_https(
                f"https://{domain}/", proxy=proxy, timeout=15.0
            )
        else:
            p_ok, p_detail = False, "clash down"
        if not (d_ok or p_ok):
            failures += 1
        print(
            f"    {domain:<28} {_mark(d_ok, d_detail):<34} {_mark(p_ok, p_detail)}"
        )

    verdict = "PASS" if failures == 0 else f"FAIL（{failures} 处不通，见上）"
    print(f"==== 体检结论: {verdict} ====")
    return 0 if failures == 0 else 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="重启后真机验收：合成消息走真实管线逐项发送（默认 DRY-RUN）"
    )
    # 目标参数在 parser 层不强制（--selftest 全离线无需目标）；
    # 存量矩阵与 --help-matrix 在 main 里补同一语义的强制校验。
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--target-group", metavar="GROUP_ID", help="验收目标群号")
    target.add_argument("--target-user", metavar="USER_ID", help="验收目标私聊 QQ 号")
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "真走发送链路：入队 **临时库** 上的 SQLite 发送队列（库经 "
            "send_queue_isolation_config 改指 OS 临时目录，绝不碰生产 "
            "wuwa_send_queue.sqlite3、绝不被在线 worker 真发；默认 DRY-RUN）"
        ),
    )
    parser.add_argument(
        "--live-delivery",
        action="store_true",
        help=(
            "**真实投递**：把发送队列指回生产库，在线 bot 的 worker 会逐条真发到目标并"
            "写进生产投递台账（用户 2026-10-06 裁「隔离为默认＋真发要显式旗」）。"
            "只作用于 --execute；DRY-RUN 带此旗也绝不真发。"
        ),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"逐项间隔秒数（默认 {DEFAULT_INTERVAL_SECONDS:g}s）",
    )
    parser.add_argument("--env", default=None, help=".env 路径（默认自动发现）")
    parser.add_argument(
        "--bot-id", default="", help="bot 自身 QQ 号（默认取 BOT_GSCORE_BOT_SELF_ID；"
        "留空时 worker 按适配器回退选择在线 OneBot bot）"
    )
    parser.add_argument(
        "--sender-id",
        default="",
        help="合成消息的发送者 QQ 号（留空=私聊时跟随 --target-user，群聊用占位 10000）",
    )
    parser.add_argument(
        "--city", default="北京", help="天气+预警项的查询城市（默认 北京）"
    )
    parser.add_argument(
        "--only", default="", help="只跑指定项（逗号分隔 key，如 help,affinity）"
    )
    parser.add_argument(
        "--list", action="store_true", help="只打印验收矩阵后退出"
    )
    # ---- 实战自测（2026-09-13 批次）：新参数只往后加，存量语义不变 ----
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="全离线自检：矩阵生成/触发提取/payload/报告/探针/轮询，无需目标与 bot 在线",
    )
    parser.add_argument(
        "--help-matrix",
        action="store_true",
        help="命令矩阵模式：从 echo._HELP_ENTRIES 全 topics 生成命令清单逐条验收"
        "（DRY-RUN 只构造 payload + 路由体检；--execute 逐条发送并等投递回执）",
    )
    parser.add_argument(
        "--subset",
        default="",
        help="命令矩阵只跑指定主题（逗号分隔，匹配 topic/别名；隐含 --help-matrix）",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="生成给超管的汇总报告（--execute 且 bot 在线时私聊超管，否则写文件）",
    )
    parser.add_argument(
        "--report-file", default="", help="报告落盘路径（默认 %%TEMP%%/e2e_report_<时间戳>.txt）"
    )
    parser.add_argument(
        "--json-out", default="", help="结构化结果 JSON 路径（execute 模式缺省也写 %%TEMP%%）"
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=DEFAULT_DELIVERY_WAIT_SECONDS,
        help=f"逐条投递回执等待预算秒数（默认 {DEFAULT_DELIVERY_WAIT_SECONDS:g}s）",
    )
    parser.add_argument(
        "--probe-wait",
        type=float,
        default=DEFAULT_PROBE_WAIT_SECONDS,
        help=f"worker 存活探针等待秒数（默认 {DEFAULT_PROBE_WAIT_SECONDS:g}s）",
    )
    parser.add_argument(
        "--ws-probe",
        default="",
        help="OneBot WS 探测端点 host:port（默认 ONEBOT_WS_URLS 首条，再默认 127.0.0.1:3001）",
    )
    parser.add_argument(
        "--check-llm-chain",
        action="store_true",
        help="LLM 链一键体检：bot→网关→应急地板→上游域 直连/经代理 全矩阵"
        "（只读探活，无需目标与 bot 在线；退出码 0=全绿）",
    )
    return parser


def _require_target(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not (args.target_group or args.target_user):
        parser.error("one of the arguments --target-group --target-user is required")


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdio()
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # 实战自测自检：全离线，不装配运行时、不读 .env、不要求目标。
    if args.selftest:
        code, lines = run_selftest()
        for line in lines:
            print(line)
        return code

    # W1-④ LLM 链一键体检：只读探活，不装配运行时、不要求目标。
    if args.check_llm_chain:
        return run_check_llm_chain(_discover_env_values(str(args.env or "")))

    # 命令矩阵模式（--subset 隐含开启）；存量矩阵保持原语义。
    if args.help_matrix or str(args.subset or "").strip():
        _require_target(parser, args)
        return run_help_matrix(args)

    _require_target(parser, args)

    runtime = build_runtime(
        env_file=args.env,
        execute=bool(args.execute),
        city=str(args.city or "").strip(),
        bot_id=str(args.bot_id or "").strip(),
        # 私聊回执 target=sender：默认值必须跟随目标用户，否则私聊件投递到占位号。
        sender_id=str(
            args.sender_id
            or str(args.target_user or "").strip()
            or "10000"
        ).strip(),
        live_delivery=bool(getattr(args, "live_delivery", False)),
    )
    matrix = build_matrix(runtime)
    if args.list:
        for index, item in enumerate(matrix, 1):
            print(f"[{index}] {item.label} key={item.key} text={item.trigger_text(runtime)!r}")
        return 0

    only = {part.strip() for part in str(args.only or "").split(",") if part.strip()}
    if only:
        matrix = [item for item in matrix if item.key in only]
        if not matrix:
            print(f"--only 无匹配项：{sorted(only)}", file=sys.stderr)
            return 2

    if args.target_group:
        session_type = SessionType.GROUP
        target_id = str(args.target_group).strip()
        allowed, reason = check_group_allowed(runtime, target_id)
        print(f"[安全阀] {reason}")
        if not allowed:
            return 2
    else:
        session_type = SessionType.PRIVATE
        target_id = str(args.target_user or "").strip()
        # 私聊场景收件人=发信人：sender_id 未显式给定时跟随目标用户，
        # 否则 pipeline 生成的 SendRequest.target_id 会指向占位 id 导致投递失败。
        if target_id and not str(args.sender_id or "").strip():
            args.sender_id = target_id
        print(f"[安全阀] 私聊目标 {target_id}（私聊策略默认放行，角色/风控拦截除外）")

    mode_line = (
        "execute（真走发送链路：入队 **临时库** 上的 SQLite 队列，"
        "生产库零字节、不被在线 worker 真发）"
        if args.execute
        else "DRY-RUN（默认；InMemory 队列，无任何真实发送路径）"
    )
    print(
        f"[配置] env={args.env or 'auto'} 目标={session_type.value}:{target_id} "
        f"sender={runtime.sender_id} bot_id={runtime.bot_id or '(回退适配器选择)'} "
        f"间隔={args.interval:g}s 模式={mode_line}"
    )

    audit_logger = InMemoryAuditLogger()
    try:
        send_queue, queue_desc = choose_send_queue(runtime, audit_logger)
    except E2eSafetyError as exc:
        print(f"[安全阀] {exc}", file=sys.stderr)
        return 2
    print(f"[队列] {queue_desc}")
    warn_live_delivery(queue_desc)

    pipeline = build_pipeline(runtime, send_queue)

    # 安静时间提示：真跑会话若落在安静窗口，命令也会被 pipeline 拦（回执可见）。
    quiet = build_quiet_hours_checker(runtime.config)
    probe = synthesize_message(
        text="e2e-probe",
        session_type=session_type,
        target_id=target_id,
        sender_id=runtime.sender_id,
        bot_id=runtime.bot_id,
        seq=0,
    )
    try:
        quiet_decision = quiet.check(probe, "bot.market")
        if not quiet_decision.allowed:
            print(f"[提示] {quiet_decision.reason}（安静时间窗口内发送会被 pipeline 拦截）")
    except Exception:  # noqa: S110, BLE001 - 提示失败不阻断，静默跳过。
        pass

    outcomes: list[ItemOutcome] = []
    total = len(matrix)
    for index, item in enumerate(matrix, 1):
        outcome = execute_item(
            pipeline=pipeline,
            send_queue=send_queue,
            item=item,
            runtime=runtime,
            session_type=session_type,
            target_id=target_id,
            seq=index,
        )
        outcomes.append(outcome)
        print_outcome(index, total, outcome, execute=bool(args.execute))
        if args.execute and outcome.receipt is not None:
            try:
                print(f"          ↳ queue summary: {send_queue.safe_summary()}")
            except Exception:  # noqa: S110, BLE001 - 队列摘要失败不阻断。
                pass
        if index < total and args.interval > 0:
            time.sleep(args.interval)

    errors = [outcome for outcome in outcomes if outcome.error]
    expect_fails = [
        outcome
        for outcome in outcomes
        if not outcome.error and outcome.expect_fail_reason
    ]
    print("\n===== 验收汇总 =====")
    for outcome in outcomes:
        state = outcome.receipt.state.value if outcome.receipt else "error"
        mark = "✗" if outcome.error or outcome.expect_fail_reason else "·"
        suffix = " expect-FAIL" if outcome.expect_fail_reason else ""
        print(f"{mark} {outcome.item.key:18s} {state}{suffix}")
    print(
        f"共 {len(outcomes)} 项，错误 {len(errors)} 项，期望未达成 {len(expect_fails)} 项。"
        + (
            (
                "\n⚠ 本轮带 `--live-delivery`：以上项已入队到**生产发送队列**，在线 bot 的 "
                "worker 会逐条真发到目标，每一行都写进生产投递台账（这是真实投递，不是预览）。"
                if bool(getattr(args, "live_delivery", False))
                else (
                    "\n说明：--execute 项已入队到 **临时库** 上的 SQLite 发送队列（真实 submit/"
                    "建表/part 账本全走），但生产 wuwa_send_queue.sqlite3 零字节、在线 worker "
                    "看不见 ⇒ **不会真发到群/私聊**（本波结构性切断，见文件头安全阀；"
                    "要真发须显式带 `--live-delivery`）。"
                )
            )
            if args.execute
            else "\nDRY-RUN：以上为「将发内容」，未入任何队列。"
        )
    )
    return 1 if errors or expect_fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
