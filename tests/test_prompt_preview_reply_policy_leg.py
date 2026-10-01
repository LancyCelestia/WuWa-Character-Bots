"""预览口接上【对方的长期沟通偏好】这条腿的锁（S-PREVIEW-LEGN，2026-09-29）。

要防的形态是本仓最讨厌的那一种：**功能在生产有、在观测面看不见**。提示词预览口
`runtime/prompt_preview.py` 从前直调 `build_chat_prompt_with_diagnostics(context)`，
**从不交 `reply_policy_section`** ⇒ Web 预览里永远看不到偏好整块，而生产那轮真会带上。
用户与管理员据此判「它到底生效没有」就会判错。

判据分层（都在真入口上跑，不在测试里拼第二份渲染逻辑）：
① 同形：预览与生产渲染口对**同一个人**给出逐字节相同的偏好块（同码同文案）；
② 默认腿：没表过态的人走默认讲法时，预览也照样显示（姊妹缺陷——默认讲法键）；
③ fail-open：store 拿不到／总开关关时预览**不抛**且无该块（读库失败绝不能把预览弄没）；
④ 只读：预览是观测动作，绝不把意象轮换账（`person_imagery_usage`）写脏；
⑤ 注毒：把预览口的 `reply_policy_section=` 传参摘掉 ⇒ 锁必红（AST 形态 + 行为各一）；
⑥ 身份（S11 追加）：`sender=` 那枚开关要把**这个人**已钉的那行读出来（匿名预览不许看见），
   且长度分档那行要按生产的优先级链跟着走——本人钉过 ⇒ 压过装配期全局档；
   CLI 的 `--sender/--group/--session` 三枚开关要真落到构造口。

卫生红线：`.env` 的 `BOT_RUNTIME_DATA_DIR` 指生产根，conftest 只守源码树 `data/`——
凡可能走到 `shared_reply_policy_store` 的例都显式 monkeypatch 它或显式注入 tmp store，
本件绝不碰生产库、不往源码树落文件。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
from plugins.bot_unified_runtime.domains.chat_reply.character import reply_policy as rp
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    NullCharacterContextProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
    ReplyPolicy,
    ReplyPolicyStore,
    person_reply_policy_key,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import prompt_preview as pp
from plugins.bot_unified_runtime.domains.chat_reply.runtime.prompt_preview import (
    _ReadOnlyPolicyStore,
    build_prompt_preview,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_PREVIEW_PY = (
    _REPO_ROOT
    / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "runtime"
    / "prompt_preview.py"
)

HEADER = chat.POLICY_SECTION_HEADER
DEFAULT_LEAD = rp._DEFAULT_DIRECTIVE_LEAD
#: 预览口写死的发送者 id（见 build_prompt_preview 的 IncomingMessage），键构造必须跟着它。
PREVIEW_SENDER = "prompt-preview-user"
#: 与「以后怎么回复我」无关的一句话：既不打判定线也不被谓词铸成新偏好。
NEUTRAL = "今天天气怎么样"


def _config(tmp: Path, **overrides: Any) -> Config:
    base: dict[str, Any] = {
        "_env_file": None,
        "bot_chat_provider": "static",
        "bot_chat_model": "static",
        "bot_persona_files": [],
        "bot_knowledge_files": [],
        "bot_runtime_data_dir": str(tmp),
        "bot_prompt_audit_dir": "",
        "bot_reply_policy_enabled": True,
        # 默认讲法关掉，好让 ① 的「同形」只测这个人自己的偏好块、不混进默认行。
        "bot_reply_default_directives": "",
    }
    base.update(overrides)
    return Config(**base)


def _store(tmp: Path) -> ReplyPolicyStore:
    return ReplyPolicyStore(tmp / "reply_policy.sqlite3")


def _seed(store: ReplyPolicyStore, directives: tuple[str, ...], sender: str = PREVIEW_SENDER) -> str:
    key = person_reply_policy_key(sender_id=sender)
    store.put(ReplyPolicy(person_key=key, content_directives=directives))
    return key


def _joined(messages: list[dict[str, str]]) -> str:
    return "\n".join(str(m.get("content") or "") for m in messages)


def _extract_block(prompt: str) -> str:
    """截出块首之后、下一个【分区之前的整段（不含下一分区）。"""
    if HEADER not in prompt:
        return ""
    start = prompt.index(HEADER)
    rest = prompt[start + len(HEADER):]
    nxt = rest.find("【")
    return rest[:nxt] if nxt >= 0 else rest


class Rec:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def generate(self, messages, **kwargs):
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
            LLMReply,
        )

        self.calls.append([dict(m) for m in messages])
        return LLMReply(text="好。", provider="rec", model="rec", confidence=0.0)

    @property
    def prompt(self) -> str:
        return _joined(self.calls[-1] if self.calls else [])


def _prod_prompt(tmp: Path, cfg: Config, store: ReplyPolicyStore, sender: str) -> str:
    rec = Rec()
    cap = chat.build_chat_capability(
        NullCharacterContextProvider(),
        rec,
        reply_detail="auto",
        reply_policy_store=store,
        content_route_config=cfg,
    )
    msg = IncomingMessage(
        platform="qq", adapter="nonebot", bot_id="b",
        session_id=f"private_{sender}", session_type=SessionType.PRIVATE,
        sender_id=sender, plain_text=NEUTRAL, mentions_bot=False,
    )
    cap(msg, BotDecision(
        request_id=msg.request_id, should_respond=True, mode="chat", trigger="private",
        capability_id="bot.chat", target_scope=msg.session_type,
        privacy_level=PrivacyLevel.PERSONAL, risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE, context_budget=12000, decision_reason="preview-leg",
    ))
    assert rec.calls, "生产能力根本没走到 provider ⇒ 本例空跑"
    return rec.prompt


# ---------------------------------------------------------------------------
# ① 同形：预览与生产对同一个人给出逐字节相同的偏好块
# ---------------------------------------------------------------------------


def test_preview_and_production_render_identical_policy_block(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    store = _store(tmp_path)
    _seed(store, ("conclusion_first", "no_action_brackets"))

    prev = build_prompt_preview(NEUTRAL, config=cfg, reply_policy_store=store)
    prod = _prod_prompt(tmp_path, cfg, store, PREVIEW_SENDER)

    prev_block = _extract_block(_joined(prev["messages"]))
    prod_block = _extract_block(prod)
    assert prev_block, "预览没拿到偏好块（这条腿又断了）"
    assert HEADER in _joined(prev["messages"]), "预览提示词里没有块首"
    assert prev_block == prod_block, (
        f"预览与生产偏好块不同形：\n  预览={prev_block!r}\n  生产={prod_block!r}"
    )
    for code in ("conclusion_first", "no_action_brackets"):
        assert code in prev_block


# ---------------------------------------------------------------------------
# ② 默认腿：没表过态的人走默认讲法时预览照样显示
# ---------------------------------------------------------------------------


def test_preview_shows_default_directives_for_person_without_policy(tmp_path: Path) -> None:
    cfg = _config(tmp_path, bot_reply_default_directives="文学化,铺意象")
    store = _store(tmp_path)  # 空库：这个人从没表过态
    prev = build_prompt_preview(NEUTRAL, config=cfg, reply_policy_store=store)
    text = _joined(prev["messages"])

    assert HEADER in text, "默认讲法在预览里没出现（姊妹缺陷）"
    assert DEFAULT_LEAD in text, "偏好段没自报是默认＝替模型伪造本人话"
    for code in ("literary_prose", "imagery_rich"):
        assert code in text, f"默认修辞码 {code} 没进预览"
    assert store.get(person_reply_policy_key(sender_id=PREVIEW_SENDER)) is None, (
        "预览凭空给这个人写了一行 ⇒ 测的就不是默认腿"
    )


# ---------------------------------------------------------------------------
# ③ fail-open：store 拿不到／开关关时预览不抛且无该块
# ---------------------------------------------------------------------------


def test_preview_no_block_and_no_throw_when_store_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """总开关关／懒建口回 None ⇒ 真身判据自然收敛（无策略＋无默认＝空串＝无块）。"""
    cfg = _config(tmp_path, bot_reply_default_directives="")
    monkeypatch.setattr(rp, "shared_reply_policy_store", lambda config: None)
    prev = build_prompt_preview(NEUTRAL, config=cfg)  # 不注 store ⇒ 走懒建口
    assert HEADER not in _joined(prev["messages"]), "没有 store 也没有默认，块不该出现"
    assert prev["ok"] is True and prev["messages"], "预览本体被读库判据带走了"


def test_preview_survives_store_bootstrap_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """懒建口抛 ⇒ 预览吞掉异常继续出提示词（观测工具绝不能因读库炸掉而没了）。"""

    def boom(config: Any) -> ReplyPolicyStore:
        raise RuntimeError("db down")

    cfg = _config(tmp_path)
    monkeypatch.setattr(rp, "shared_reply_policy_store", boom)
    prev = build_prompt_preview(NEUTRAL, config=cfg)
    assert prev["ok"] is True and prev["messages"]
    assert HEADER not in _joined(prev["messages"])


def test_preview_survives_policy_read_exception(tmp_path: Path) -> None:
    """store.get 抛 ⇒ 偏好段塌成无策略，仍出默认块，绝不抛。"""

    class ExplodingStore(ReplyPolicyStore):
        def get(self, person_key: str) -> Any:  # 故意炸给 fail-open 看
            raise RuntimeError("read failed")

    cfg = _config(tmp_path, bot_reply_default_directives="文学化")
    store = ExplodingStore(tmp_path / "x.sqlite3")
    prev = build_prompt_preview(NEUTRAL, config=cfg, reply_policy_store=store)
    assert prev["ok"] is True and prev["messages"]
    # 读炸＝本轮按无策略，但默认腿（config 侧）仍把块撑起来，证明没被读炸带走。
    assert HEADER in _joined(prev["messages"])


# ---------------------------------------------------------------------------
# ④ 只读：预览绝不把意象轮换账写脏
# ---------------------------------------------------------------------------


class _StubInner:
    def __init__(self) -> None:
        self.recorded = 0

    def canonical_person_key(self, key: Any) -> str:
        return str(key)

    def get(self, person_key: str) -> Any:
        return None

    def recent_imagery_families(self, person_key: Any, **kwargs: Any) -> list[str]:
        return ["海", "金属"]

    def record_imagery_use(self, person_key: Any, families: Any) -> bool:
        self.recorded += 1
        return True


def test_read_only_proxy_disables_rotation_ledger_but_keeps_reads() -> None:
    """本席选的只读方案：把 record_imagery_use 这条写腿钉成空操作，读口照常透传。"""
    inner = _StubInner()
    proxy = _ReadOnlyPolicyStore(inner)

    assert proxy.recent_imagery_families("k") == ["海", "金属"], "读窗口被错误屏蔽 ⇒ 不再是生产同构"
    assert proxy.get("k") is None
    assert proxy.canonical_person_key("k") == "k"

    assert proxy.record_imagery_use("k", ["海"]) is False
    assert inner.recorded == 0, "预览把轮换记账转发给了真 store ⇒ 观测动作写脏了账"
    assert proxy.put(object()) is False
    assert proxy.clear("k") is False


def test_preview_does_not_advance_imagery_window(tmp_path: Path) -> None:
    """端到端：预览一个钉了 varied_imagery 的人，跑完 `person_imagery_usage` 仍空。"""
    cfg = _config(tmp_path)
    store = _store(tmp_path)
    key = _seed(store, ("varied_imagery", "literary_prose"))

    prev = build_prompt_preview(NEUTRAL, config=cfg, reply_policy_store=store)
    assert HEADER in _joined(prev["messages"]), "钉了意象轮换的人，预览也该有偏好块"
    assert store.recent_imagery_families(key) == [], (
        "预览写脏了意象轮换账 ⇒ 观测动作不该消耗生产窗口"
    )


# ---------------------------------------------------------------------------
# ⑤ 注毒：摘掉预览口的 reply_policy_section 传参 ⇒ 锁必红（AST + 行为各一）
# ---------------------------------------------------------------------------


def _preview_section_call_kwargs(source: str) -> list[set[str]]:
    out: list[set[str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name == "build_chat_prompt_with_diagnostics":
                out.append({kw.arg for kw in node.keywords if kw.arg})
    return out


def test_preview_forwards_reply_policy_section_in_source() -> None:
    calls = _preview_section_call_kwargs(PROMPT_PREVIEW_PY.read_text(encoding="utf-8"))
    assert calls, "prompt_preview.py 里没有 build_chat_prompt_with_diagnostics 调用"
    for kwargs in calls:
        assert "reply_policy_section" in kwargs, (
            f"预览调用没交 reply_policy_section：{kwargs} ⇒ 偏好块在观测面又看不见了"
        )


def test_poison_dropping_reply_policy_section_turns_lock_red() -> None:
    source = PROMPT_PREVIEW_PY.read_text(encoding="utf-8")
    assert _preview_section_call_kwargs(source)
    anchor = "        reply_policy_section=reply_policy_section,\n"
    poisoned = source.replace(anchor, "", 1)
    assert poisoned != source, "注毒锚点不存在＝毒没注进去"
    after = _preview_section_call_kwargs(poisoned)
    assert any("reply_policy_section" not in kwargs for kwargs in after), (
        "摘掉传参后判据仍全绿＝这道锁是空跑的"
    )


def test_preview_passes_nonempty_section_for_pinned_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """行为级注毒对照：真人偏好 ⇒ spy 收到的 reply_policy_section 必须非空。"""
    seen: dict[str, Any] = {}
    real = pp.build_chat_prompt_with_diagnostics

    def spy(context: Any, *a: Any, **k: Any):
        seen.update(k)
        return real(context, *a, **k)

    monkeypatch.setattr(pp, "build_chat_prompt_with_diagnostics", spy)
    cfg = _config(tmp_path)
    store = _store(tmp_path)
    _seed(store, ("conclusion_first",))
    build_prompt_preview(NEUTRAL, config=cfg, reply_policy_store=store)

    assert str(seen.get("reply_policy_section") or "").strip(), (
        "预览交给 build_chat_prompt_with_diagnostics 的 reply_policy_section 为空"
    )


# ---------------------------------------------------------------------------
# ⑥ 身份：`sender=` 要能把**这个人**已钉的那行读出来，长度档跟着生产的链走
# ---------------------------------------------------------------------------

#: 匿名预览账号（`PREVIEW_SENDER`）之外的那个"真人号"。数字号也顺带钉住
#: 「键构造走真身口径」这条：`person_reply_policy_key` 对数字号给的正是号本身。
PINNER = "1722380002"

#: 找档位差异用的样本池：判据由真身表现算，本件不写死"哪句该是哪档"（规则 10）。
_TIER_PROBE_MESSAGES = (
    NEUTRAL,
    "随便讲讲你以前的事好吗",
    "你在干嘛呀",
    "LPR又降了吗",
    "讲讲鸣潮的世界观吧",
)


def _message_where_modes_differ(mode_a: str, mode_b: str) -> str:
    """挑一句本轮真能区分两档的话；区分不出来就 loudly 红，别静默空跑。"""
    for text in _TIER_PROBE_MESSAGES:
        if chat.resolve_reply_length_tier(mode_a, text) != chat.resolve_reply_length_tier(
            mode_b, text
        ):
            return text
    raise AssertionError(
        f"档位表在样本池里对 {mode_a}/{mode_b} 无差异 ⇒ 本锁失去判据，请扩样本池"
    )


def _tier_line_of(result: dict[str, Any]) -> str:
    text = _joined(result["messages"])
    lines = [line for line in text.splitlines() if chat.TIER_LINE_PREFIX in line]
    assert lines, "提示词里没有长度分档那行（渲染口换形了？先确认再动本锁）"
    return lines[0]


def _pin(store: ReplyPolicyStore, length_mode: str, sender: str = PINNER) -> str:
    key = person_reply_policy_key(sender_id=sender)
    store.put(ReplyPolicy(person_key=key, length_mode=length_mode))
    return key


def test_preview_sender_reads_that_persons_pinned_policy(tmp_path: Path) -> None:
    """同一个人钉过的讲法：带 `sender=` 看得见、匿名看不见（缺陷 ③ 的正身）。"""
    cfg = _config(tmp_path)
    store = _store(tmp_path)
    key = _seed(store, ("conclusion_first",), sender=PINNER)

    mine = build_prompt_preview(NEUTRAL, config=cfg, reply_policy_store=store, sender=PINNER)
    anon = build_prompt_preview(NEUTRAL, config=cfg, reply_policy_store=store)

    assert HEADER in _joined(mine["messages"]), "按人预览读不到他自己的偏好段"
    assert "conclusion_first" in _extract_block(_joined(mine["messages"]))
    assert HEADER not in _joined(anon["messages"]), (
        "匿名预览串号了：看见了别人的偏好段"
    )
    assert mine["identity"]["person_key"] == key
    # 只读语义跟着身份一起成立：观测这个人，仍不许推进他的轮换账。
    assert store.recent_imagery_families(key) == []


def test_preview_sender_keeps_imagery_rotation_ledger_untouched(tmp_path: Path) -> None:
    """带身份的预览同样不许写脏轮换账（④ 的按人版）。"""
    cfg = _config(tmp_path)
    store = _store(tmp_path)
    key = _seed(store, ("varied_imagery", "literary_prose"), sender=PINNER)

    prev = build_prompt_preview(NEUTRAL, config=cfg, reply_policy_store=store, sender=PINNER)

    assert HEADER in _joined(prev["messages"])
    assert store.recent_imagery_families(key) == []
    assert store.get(key) is not None, "预览把这个人钉过的那行弄没了＝观测写脏了库"


def test_preview_tier_line_follows_config_reply_detail(tmp_path: Path) -> None:
    """装配期全局档（生产 `.env` 那枚）要进得了预览的档名与档行。"""
    text = _message_where_modes_differ("auto", "concise")
    store = _store(tmp_path)  # 空库：谁都没钉过 ⇒ 只剩全局档这一层
    plain = build_prompt_preview(text, config=_config(tmp_path), reply_policy_store=store)
    pinned = build_prompt_preview(
        text,
        config=_config(tmp_path, bot_reply_detail="concise"),
        reply_policy_store=store,
    )

    assert plain["diagnostics"]["reply_detail"] == "auto"
    assert pinned["diagnostics"]["reply_detail"] == "concise"
    expected_tier = chat.resolve_reply_length_tier("concise", text)
    assert chat.REPLY_LENGTH_TIERS[expected_tier].label_cn in _tier_line_of(pinned)
    assert _tier_line_of(pinned) != _tier_line_of(plain), (
        "改了配置里的详略档，预览那行却一动不动 ⇒ 没接进生产那条链"
    )


def test_preview_pinned_verbose_beats_global_detail(tmp_path: Path) -> None:
    """本人钉过 ⇒ 压过装配期全局档（生产优先级链 ②>③ 的同构复算）。"""
    text = _message_where_modes_differ("detail", "verbose")
    cfg = _config(tmp_path, bot_reply_detail="detail")
    store = _store(tmp_path)
    _pin(store, "verbose")

    mine = build_prompt_preview(text, config=cfg, reply_policy_store=store, sender=PINNER)
    anon = build_prompt_preview(text, config=cfg, reply_policy_store=store)

    assert anon["diagnostics"]["reply_detail"] == "detail", "全局档没进预览（缺陷 ② 复发）"
    assert mine["diagnostics"]["reply_detail"] == "verbose", "本人钉过的那行被全局档压掉了"
    expected_tier = chat.resolve_reply_length_tier("verbose", text)
    assert (
        chat.REPLY_LENGTH_TIERS[expected_tier].label_cn in _tier_line_of(mine)
    ), "档名是 verbose，长度行却没跟着换档"
    assert _tier_line_of(mine) != _tier_line_of(anon)
    # 注毒对照：把身份摘掉 ⇒ 本锁判的那一行就变了（证明它咬的是身份这条腿）。
    assert mine["diagnostics"]["reply_length_tier"] != anon["diagnostics"]["reply_length_tier"]
