"""Build a redacted prompt preview without invoking an LLM.

预览的口径是**尽力同构、缺口自报**（09-29 复核席裁定）：同构的部分下面逐条接了生产的
真身口，**不同构的部分由返回值里的 `preview_gaps` 逐条点名**——谁拿预览当生产事实汇报，
得先看见自己漏看了什么。历史上这里栽过三次，都是「功能在生产有、在观测面看不见」：

① 预算：从前 `ContextBundle.context_budget` 一路吃数据类缺省（一个比生产小得多的骨架
   档），`chat._clip_prompt_tail` 于是吃掉每一段动态分区、连人设原文都腰斩 ⇒ 预览显示的
   是骨架、不是模型真吃到的那一份。现在预算走生产同一判定口（见 `_preview_context_budget`）。
② 详略档：`context.reply_detail` 从前从不赋值 ⇒ 长度分档那行永远按 `auto` 判，钉了
   `detail`/`verbose` 的人看不出自己真实的档。现在按生产同一条优先级链取（见
   `_preview_reply_detail`）。
③ 身份：`sender_id`/`session_id` 从前写死 ⇒ 「看看**这个人**那轮长什么样」根本问不出来，
   按人的偏好／心情／称谓／怪癖在观测面全不可见。现在有 `--sender` / `--group` / `--session`。

刻意保留的抑制（history / memory / embedding / 联网检索 / 运行时热改）是**离线安全**的地基：
预览绝不能为了"像生产"去起索引、打外网、或把观测动作写成状态。这些抑制换来的差异一并进
`preview_gaps`。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.character import build_character_context_provider
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_chat_prompt_with_diagnostics,
    normalize_reply_detail_mode,
    resolve_reply_length_tier,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.history import (
    InMemoryConversationHistoryStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
    LENGTH_MODE_AUTO,
    person_reply_policy_key,
    reply_policy_section_for_turn,
    shared_reply_policy_store,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.reply_budget import (
    build_reply_budget_settings,
    decide_reply_budget,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.prompt_audit import (
    PromptAuditStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    RuntimeSettingsStore,
)
from plugins.bot_unified_runtime.domains.ops.smoke.console_chat import load_smoke_config


class _ReadOnlyPolicyStore:
    """预览专用**只读代理**：把观测动作会写脏的那条轮换账钉成空操作。

    唯一被禁的写腿＝`record_imagery_use`（`person_imagery_usage` 用量账）——一次预览
    不该被当成一轮真对话去推进这个人的意象轮换窗口。其余读口（`get` /
    `recent_imagery_families` / `canonical_person_key`）一律透传真 store。

    为什么它仍是「预览＝生产同构」：`reply_policy_section_for_turn` 的本轮选族**只读**
    `recent_imagery_families` 决定避开哪些族——预览照读同一扇窗口、算出生产下一轮会派
    的那批族，只是不把自己记进账里。于是预览看到的取材，正等于生产这一轮真正会看到的，
    而轮换的「消耗」仍只发生在真对话上。put/clear 也钉成空操作：本口绝不跑
    `resolve_turn_reply_policy` 那条判定/写库腿，免得凭一句预览话就铸一份永久策略。

    注意「同构」的范围＝**偏好段这一块**（取材与选族窗口与生产一致）。整份预览还剩哪些
    不同构，一律看 `_build_preview_gaps` 与返回值 `preview_gaps`，别拿本句外推。
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def canonical_person_key(self, person_key: Any) -> str:
        return self._inner.canonical_person_key(person_key)

    def get(self, person_key: str) -> Any:
        return self._inner.get(person_key)

    def recent_imagery_families(self, person_key: Any, **kwargs: Any) -> list[str]:
        return self._inner.recent_imagery_families(person_key, **kwargs)

    def record_imagery_use(self, person_key: Any, families: Any) -> bool:
        # 只读观测腿：轮换账只准真对话写，预览一次都不落地。
        return False

    def put(self, policy: Any) -> bool:
        return False

    def clear(self, person_key: str) -> bool:
        return False


#: 预览只观测**人格对话**这一条能力；这个 id 决定预算判定走不走 chat 那一支
#: （`reply_budget.CHAT_CAPABILITY_IDS` 是「哪些 id 算 chat」的唯一在册口，本字面量
#: 是否仍在册由 `test_preview_capability_id_is_registered_as_chat` 现算钉住，
#: 免得这里悄悄长成第二套判据）。
PREVIEW_CAPABILITY_ID = "bot.chat"

#: 预览身份缺省值（不带 `--sender/--group/--session` 时的形态）。**不许改值**：
#: 既有锁（test_prompt_preview_reply_policy_leg 的 PREVIEW_SENDER）按这两个键构造策略主键。
PREVIEW_DEFAULT_SENDER = "prompt-preview-user"
PREVIEW_DEFAULT_SESSION = "private:prompt-preview"


def _preview_context_budget(message: IncomingMessage, config: Config) -> int:
    """预览的上下文预算＝**生产同一条判定口**的返回值，不在这里另立一把尺。

    生产的取数链就是这两步（`runtime/pipeline.py` 的 `_prepare` 与
    `policy/reply_budget.py`）：`build_reply_budget_settings(config)` 把四个
    `BOT_REPLY_*_CONTEXT_BUDGET` 配置口收成 `ReplyBudgetSettings`，
    `decide_reply_budget(message, capability_id, settings=…)` 再按会话类型／风险档／
    文本标记选档。预览**照抄这条调用形**，于是：
    * 数值随配置漂移自动跟（缺省 2048 是 `ContextBundle` 那枚数据类缺省，**生产早就不
      用它**；这里一个字都不写死，规则 10）；
    * `--group` 一给，群帽那腿自然生效（`min(…, group_context_budget)`）；
    * 支持性／教学性措辞的升档腿也自然生效（同一段标记判据，零第二真身）。

    已知未接的一腿：生产在 fast 模式开启时还会再 `min(decision.context_budget,
    bot_chat_fast_context_budget)` 帽一次（`capabilities/chat.py` 的 context 覆写处）。
    那一帽只在模型自选到 fast 候选时发生，离线判不出来 ⇒ 记进 `preview_gaps`。
    """
    return decide_reply_budget(
        message,
        PREVIEW_CAPABILITY_ID,
        settings=build_reply_budget_settings(config),
    ).context_budget


def _preview_reply_detail(*, config: Config, policy: Any) -> str:
    """预览的详略「模式」＝生产优先级链里**离线拿得到的那两层**。

    生产四层（`capabilities/chat.py` 的 detail_mode 那段）：① 本轮运行时热改 →
    ② 本人永久策略 → ③ 装配期全局档 `bot_reply_detail` → ④ 缺省 auto。
    预览①刻意不接（热改要读运行时设置库＝带写面与生产库，见 `preview_gaps`），
    所以这里做的是 **② 压过 ③、两者都拿不到时归 ④**——与生产同序、同判据：
    `normalize_reply_detail_mode` 是真身归一口（未知值→auto），本函数零自造词表。
    只把「模式」定出来；「模式 × 本轮题型 → 生效档」仍由 `chat.py` 那张表在渲染口选一次。
    """
    detail_mode = normalize_reply_detail_mode(getattr(config, "bot_reply_detail", ""))
    pinned = str(getattr(policy, "length_mode", "") or "").strip()
    if pinned and pinned != LENGTH_MODE_AUTO:
        detail_mode = normalize_reply_detail_mode(pinned)
    return detail_mode


def _person_policy_for_preview(store: Any, person_key: str) -> Any:
    """只读地取这个人**已钉**的沟通偏好；拿不到／读炸一律按「本轮无策略」。

    观测动作绝不铸策略：这里只 `get`，绝不碰 `resolve_turn_reply_policy` 那条判定+写库腿。
    """
    if store is None or not person_key:
        return None
    try:
        return store.get(person_key)
    except Exception:  # noqa: BLE001 - 读失败＝本轮按无策略，绝不抛（预览是观测工具）。
        return None


def _build_preview_gaps(
    *,
    context_budget: int,
    reply_detail: str,
    has_person_policy: bool,
    suppressed: dict[str, bool],
) -> list[dict[str, str]]:
    """把「预览看不见什么、为什么」收成一份随返回值走的清单。

    这份清单存在的理由只有一个：**不许有人拿被裁过的提示词当生产事实汇报**（规则 5）。
    前四条是刻意的离线安全抑制（关掉它们才能不碰索引/外网/生产写面），后几条是
    「本轮没有真判据可取」的结构性缺口——两类分开点名，别混成一句「大致同构」。
    文案里不写任何会随配置漂移的数值（规则 10）；`context_budget` 只作为**本轮实算值**
    出现一次，供人对照日志，不是缺省值声明。
    """
    gaps: list[dict[str, str]] = [
        {
            "section": "上下文预算（fast 模式那一帽）",
            "reason": (
                "预算走生产同一判定口，本轮实算＝"
                f"{context_budget} 字符；但生产在 bot_chat_fast_mode 命中 fast 候选时还会"
                "按 bot_chat_fast_context_budget 再 min 一次，离线无从复现那次自选"
                " ⇒ 预览按非 fast 档显示。"
            ),
        },
        {
            "section": "详略档第①层（运行时热改 BOT_REPLY_DETAIL）",
            "reason": (
                "预览不接运行时设置库（attach 带写面），本轮档名按「本人已钉策略 → 全局档"
                f" → auto」三层判出，实算值＝{reply_detail}；若管理员刚用 /bot reply 热改过，"
                "预览看不见那层覆盖。"
            ),
        },
        {
            "section": "当轮偏好判定（新钉一句讲法）",
            "reason": (
                "生产每轮跑 resolve_turn_reply_policy（判定＋写库），预览只读已入库的那行"
                "（本例" + ("读到" if has_person_policy else "没读到") + "），"
                "故「这句刚说过的话会不会被钉成永久偏好」看不见。"
            ),
        },
    ]
    for key, label in (
        ("history", "历史对话分区"),
        ("memory", "长时记忆分区"),
        ("knowledge_retrieval", "向量/embedding 检索到的知识块"),
        ("web_search", "联网检索分区"),
    ):
        if suppressed.get(key):
            gaps.append(
                {
                    "section": label,
                    "reason": (
                        "刻意抑制：这条腿要起索引／打外网／读记忆库，关掉才敢离线跑"
                        " ⇒ 分区里到底装了什么在预览里看不见（分区块本身可能仍在场，"
                        "只是内容是空态或可用性声明）。"
                    ),
                }
            )
    gaps.append(
        {
            "section": "角色与权限分区（超管名册／宿主机状态／系统自述／时间窗总结）",
            "reason": (
                "预览不过门禁（gate/roles/限流/安静时间），也不交 admin_roster_text、"
                "host_status_section、system_readout_section、time_window_section 这四段"
                "现算文本 ⇒ 只有超管那轮才会出现的分区在这里恒为空；称谓里的角色行同缺。"
            ),
        }
    )
    gaps.append(
        {
            "section": "会话键形状与真实平台侧写",
            "reason": (
                "platform/adapter 固定为 console/prompt-preview，群会话键按 "
                "group:<id> 造（本仓推送侧写法），NoneBot 真流量用的是 group_<id> 下划线形"
                "（台账 #33★ 两形不相交）——要逐字复现某人那轮，用 --session 传真键。"
            ),
        }
    )
    if context_budget <= 0:  # pragma: no cover - 判定口不可能回 0，留着当哨兵。
        gaps.append({"section": "上下文预算", "reason": "判定口回了 0，本轮提示词必被腰斩。"})
    return gaps


def _preview_reply_policy_section(
    *,
    person_key: str,
    policy: Any,
    read_only: Any,
    config: Config,
    context: Any,
) -> str:
    """预览口的【对方的长期沟通偏好】整段：与生产渲染口**同一真身、同一判据**。

    不在这里拼第二份渲染逻辑——整段交 `reply_policy_section_for_turn`（默认讲法 + 意象
    轮换都在那一处收口）。``policy`` 由调用方经 `_person_policy_for_preview` 只读取得
    （这个人**已钉**的那行），而不是走 `resolve_turn_reply_policy` 那条判定/写库的腿
    （观测动作铸策略＝越权）。
    ``person_key`` 走 `person_reply_policy_key`（本仓键形状唯一口径，不手拼前缀）；
    现役人格 id 取 ``ContextBundle.active_persona_id``（与生产同源，回落 config 在真身里做）。
    store 拿不到／总开关关／读库炸 ⇒ 真身判据自然收敛（无策略＋无默认＝空串＝整块不出现），
    且任何异常都吞成空串——预览是观测工具，绝不能因读库失败把预览弄没。
    """
    try:
        return reply_policy_section_for_turn(
            policy,
            config=config,
            store=read_only,
            person_key=person_key,
            persona_id=str(getattr(context, "active_persona_id", "") or ""),
        )
    except Exception:  # noqa: BLE001 - 渲染任何一步炸都只塌这一整段，不动预览本体。
        return ""


def build_prompt_preview(
    message_text: str,
    *,
    config: Config,
    write_artifact: bool = False,
    output_dir: str | Path | None = None,
    reply_policy_store: Any | None = None,
    sender: str | None = None,
    group: str | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    """离线装配**这一轮、这个人**会被送进模型的那份提示词（缺口自报，见 `preview_gaps`）。

    同构面（逐条接生产的真身口，本件零复制）：上下文预算＝`_preview_context_budget`
    （生产同一判定口）、详略档名＝`_preview_reply_detail`（生产优先级链的离线可得层）、
    偏好整段＝`reply_policy_section_for_turn`、其余分区＝`build_chat_prompt_with_diagnostics`
    本身。身份三个入参只改 `IncomingMessage` 的身份字段，缺省（三者都为 None）时
    键值与改造前**逐字节相同**（既有锁按 `PREVIEW_DEFAULT_SENDER` 构造策略主键）。

    `group` 决定会话**类型**（群帽与群侧隐私走它）；`session` 只决定会话**键文本**
    （要逐字复现真流量那轮，把 NoneBot 的 `group_<id>` 原样传进来）。
    """
    text = str(message_text or "").strip()
    if not text:
        raise ValueError("message_text must not be blank")
    preview_config = config.model_copy(
        update={
            "bot_history_enabled": False,
            "bot_memory_enabled": False,
            "bot_embedding_enabled": False,
            "bot_embedding_local_enabled": False,
            "bot_web_search_enabled": False,
            "bot_runtime_settings_dir": "",
        }
    )
    provider = build_character_context_provider(
        preview_config,
        conversation_history_provider=InMemoryConversationHistoryStore(),
        runtime_settings=RuntimeSettingsStore(),
    )
    # 身份：缺省三值不许改（预览的"没有指定人"形态就是既有那份骨架，锁依赖它）。
    group_id = str(group or "").strip()
    sender_id = str(sender or "").strip() or PREVIEW_DEFAULT_SENDER
    session_id = (
        str(session or "").strip() or (f"group:{group_id}" if group_id else PREVIEW_DEFAULT_SESSION)
    )
    message = IncomingMessage(
        platform="console",
        adapter="prompt-preview",
        bot_id="prompt-preview",
        session_id=session_id,
        session_type=SessionType.GROUP if group_id else SessionType.PRIVATE,
        sender_id=sender_id,
        group_id=group_id or None,
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=True,
    )
    context = provider.build_context(
        request_id=message.request_id,
        sender_id=message.sender_id,
        session_id=message.session_id,
        query_text=text,
        platform=message.platform,
        adapter=message.adapter,
        bot_id=message.bot_id,
        group_id=message.group_id or "",
    )
    # 偏好段与生产同源：显式注入的 store 优先（测试注 tmp 只读 store），否则按 preview_config
    # 懒建进程级 store（总开关关／路径落源码树 ⇒ shared_reply_policy_store 自己回 None）。
    # 整段包在 try 里：store 建不出来＝本轮没有偏好段，绝不能把预览弄没。
    policy_store = reply_policy_store
    if policy_store is None:
        try:
            policy_store = shared_reply_policy_store(preview_config)
        except Exception:  # noqa: BLE001 - 懒建失败只塌这一整段。
            policy_store = None
    person_key = person_reply_policy_key(
        sender_id=message.sender_id,
        session_id=message.session_id,
    )
    read_only_store = _ReadOnlyPolicyStore(policy_store) if policy_store is not None else None
    person_policy = _person_policy_for_preview(read_only_store, person_key)
    context_budget = _preview_context_budget(message, preview_config)
    reply_detail = _preview_reply_detail(config=preview_config, policy=person_policy)
    # 这两枚以前**从没被赋值**：预算吃数据类缺省（⇒ 动态分区连人设一起被腰斩）、
    # 详略档恒按 auto 判（⇒ 钉了 detail/verbose 的人看不出自己真实的档）。覆写形态
    # 与生产同一处（capabilities/chat.py 在 build_context 之后 model_copy 这两个键）。
    context = context.model_copy(
        update={"context_budget": context_budget, "reply_detail": reply_detail}
    )
    reply_policy_section = _preview_reply_policy_section(
        person_key=person_key,
        policy=person_policy,
        read_only=read_only_store,
        config=preview_config,
        context=context,
    )
    messages, diagnostics = build_chat_prompt_with_diagnostics(
        context,
        reply_policy_section=reply_policy_section,
    )
    target_dir = output_dir
    if target_dir is None:
        target_dir = getattr(preview_config, "bot_prompt_audit_dir", "") or None
    store = PromptAuditStore(
        target_dir if write_artifact else None,
        max_chars=int(getattr(preview_config, "bot_prompt_audit_max_chars", 12000) or 12000),
        include_messages=True,
    )
    preview_gaps = _build_preview_gaps(
        context_budget=context_budget,
        reply_detail=reply_detail,
        has_person_policy=person_policy is not None,
        suppressed={
            "history": not bool(preview_config.bot_history_enabled),
            "memory": not bool(preview_config.bot_memory_enabled),
            "knowledge_retrieval": not bool(
                preview_config.bot_embedding_enabled
                or preview_config.bot_embedding_local_enabled
            ),
            "web_search": not bool(preview_config.bot_web_search_enabled),
        },
    )
    artifact = store.write(
        request_id=message.request_id,
        messages=messages,
        tools=[],
        llm_options={"model": preview_config.bot_chat_model},
        metadata={
            "mode": "preview",
            "persona_profile_id": preview_config.bot_persona_profile_id,
            "persona_files": list(preview_config.bot_persona_files),
            "knowledge_files": list(preview_config.bot_knowledge_files),
            "llm_called": False,
            # 落盘的产物也带缺口清单：免得有人拿一份 --write 的骨架当生产快照存档。
            "preview_gaps": preview_gaps,
        },
    )
    return {
        "ok": True,
        "llm_called": False,
        "request_id": message.request_id,
        "prompt_sha256": artifact.prompt_sha256,
        "artifact_path": artifact.path,
        "messages": artifact.messages_redacted,
        "tool_ids": artifact.tool_ids,
        "identity": {
            "sender_id": message.sender_id,
            "session_id": message.session_id,
            "session_type": message.session_type.value,
            "group_id": message.group_id or "",
            "person_key": person_key,
        },
        "preview_gaps": preview_gaps,
        "diagnostics": {
            "system_prompt_chars": diagnostics.system_prompt_chars,
            "user_prompt_chars": diagnostics.user_prompt_chars,
            "total_prompt_chars": diagnostics.total_prompt_chars,
            "truncated_sections": list(diagnostics.truncated_sections),
            "knowledge_chunks": len(context.knowledge_results.chunks),
            # 预算与档名以前在返回值里**看不见**——正是这两枚没接上时最坑的地方：
            # 看的人无从判断"被裁了"还是"本来就没这段"。
            "context_budget": context_budget,
            "requested_context_budget": diagnostics.requested_context_budget,
            "effective_context_budget": diagnostics.effective_context_budget,
            "clipped_to_context_budget": diagnostics.clipped_to_context_budget,
            "reply_detail": reply_detail,
            "reply_length_tier": resolve_reply_length_tier(reply_detail, text),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a redacted prompt preview without calling LLM")
    parser.add_argument("--message", required=True)
    parser.add_argument("--env", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--write", action="store_true")
    # 身份三枚：不给就是原来的匿名预览（缺省值逐字节不变）；给了就按**那个人/那个群**
    # 那轮的口径取偏好、预算（群帽）、档名。详见 build_prompt_preview 的 docstring。
    parser.add_argument(
        "--sender",
        default=None,
        metavar="SENDER_ID",
        help="按这个发送者 id 预览（取他已钉的沟通偏好与轮换窗口）；缺省＝匿名预览账号",
    )
    parser.add_argument(
        "--group",
        default=None,
        metavar="GROUP_ID",
        help="按群聊那轮预览（会话类型＝group，预算走群帽）；缺省＝私聊形态",
    )
    parser.add_argument(
        "--session",
        default=None,
        metavar="SESSION_KEY",
        help="逐字指定会话键文本（只改键，不改会话类型）——复现真流量那轮时用 NoneBot 的原键",
    )
    args = parser.parse_args(argv)
    config = load_smoke_config(args.env)
    result = build_prompt_preview(
        args.message,
        config=config,
        write_artifact=args.write,
        output_dir=args.output_dir,
        sender=args.sender,
        group=args.group,
        session=args.session,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())