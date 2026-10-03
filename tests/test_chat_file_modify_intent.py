"""对话内「修改已有文件」意图接线（需求 16-2，席13）的形锁。

链路：意图判据（修改族动词管着文件名词/文件名记号，只吃用户自己写的字）
→ 定位（白名单根内相对名）→ 裁决（``file.write`` 在册 R1；真裁决今日必拒——
``Permit`` 只能由测试注入，锁「会话面不自批」）→ 受限回读（T2 打标）
→ LLM 修改稿 → ``revise_in_place`` 原子落盘。

红线：命中修改意图**绝不降级成创建**；拒了不烧生成、不写一字节；
错误人话化、无路径明文；权限不足走 Q-02 轮换池。
全部离线、零网络、落点只在 ``tmp_path``。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.core.safety_exec import paths
from plugins.bot_unified_runtime.domains.core.safety_exec import policy as safety_policy
from plugins.bot_unified_runtime.domains.core.safety_exec.action_catalog import ActionId

_PERMIT = safety_policy.Permit(
    action=ActionId.FILE_WRITE,
    role_floor="trusted",
    tier="R0",
    landing_check_required=True,
)
"""裁决放行的测试凭证：真 ``decide`` 对 file.write(R1) 只会给 ConsentRequired
（确认回路未接），成功腿必须显式注入 Permit 形状——与
tests/test_files_write_side_assembly.py 同一口径。"""


@pytest.fixture(autouse=True)
def _no_reply_policy_store(monkeypatch):
    """content_route_config 在场会触发懒建回复策略库；把建库口换成 None，
    绝不让测试摸到 Runtime 生产库（台账 #66★ 同一条纪律）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character import reply_policy

    monkeypatch.setattr(reply_policy, "shared_reply_policy_store", lambda config: None)


@pytest.fixture
def wired_paths(tmp_path: Path):
    """把假根（tmp_path 为工作区）接到进程级缺省判定口，用例结束复位。"""
    active = paths.build_policy(workspace_root=tmp_path)
    paths.set_default_policy(active)
    try:
        yield active
    finally:
        paths.set_default_policy(None)


@pytest.fixture
def permit_adjudication(monkeypatch):
    """把裁决口换成 Permit 凭证（只影响经 chat.py → fx.adjudicate_file_write 的
    属性查找；refusal 腿不装它，走真裁决）。"""
    from plugins.bot_unified_runtime.domains.files.capabilities import (
        file_exchange as fx,
    )

    monkeypatch.setattr(fx, "adjudicate_file_write", lambda *a, **k: _PERMIT)


def _conf(tmp_path: Path, **overrides: object) -> Config:
    base: dict[str, object] = {
        "bot_download_dir": str(tmp_path / "dl"),
        "bot_files_write_allowed_dirs": [str(tmp_path / "out")],
    }
    base.update(overrides)
    return Config(**base)  # type: ignore[arg-type]


def _seed(cfg: Config, name: str, content: str) -> None:
    from plugins.bot_unified_runtime.domains.files.capabilities import (
        file_exchange as fx,
    )

    res = fx.run_document_create(name, content, config=cfg, decision=_PERMIT)
    assert res.ok, res.reply_text


def _chat(tmp_path: Path, cfg: Config | None, plain_text: str, answer: str, **kw: object):
    from plugins.bot_unified_runtime.contracts import (
        BotDecision,
        IncomingMessage,
        SessionType,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_chat_capability,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        NullCharacterContextProvider,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
        StaticLLMProvider,
    )

    kwargs: dict[str, object] = {
        "generated_files_dir": str(tmp_path),
        "max_tokens": 65538,
    }
    if cfg is not None:
        kwargs["content_route_config"] = cfg
    msg = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id="private:u",
        session_type=SessionType.PRIVATE,
        sender_id="u",
        group_id=None,
        plain_text=plain_text,
        command_text=str(kw.pop("command_text", plain_text)),
        sender_roles=list(kw.pop("sender_roles", None) or ["user"]),
        mentions_bot=True,
    )
    decision = BotDecision(
        request_id=msg.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        context_budget=18000,
        max_messages=0,
        decision_reason="test",
    )
    cap = build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(text=answer),
        **kwargs,
    )
    return cap(msg, decision)


def _root(cfg: Config) -> Path:
    return Path(cfg.bot_files_write_allowed_dirs[0])


# ---------------------------------------------------------------------------
# ① 修改成功：读 → LLM 稿 → revise_in_place 原子落盘，结果随 CapabilityResult 回
# ---------------------------------------------------------------------------


def test_modify_success_rewrites_in_place(tmp_path: Path, wired_paths, permit_adjudication) -> None:
    cfg = _conf(tmp_path)
    _seed(cfg, "note.md", "# 初稿\n")
    result = _chat(tmp_path, cfg, "把 note.md 修改一下，换个标题", "# 修改稿\n")
    assert "已改好并回读确认" in result.body, result.body
    assert len(result.files) == 1
    assert Path(result.files[0]["name"]).name == "note.md"
    target = Path(result.files[0]["file"])
    assert target.read_text(encoding="utf-8") == "# 修改稿\n"
    assert "artifact_revised" in result.audit_tags


# ---------------------------------------------------------------------------
# ② 同字节：不写盘、不烧配额、mtime 不动
# ---------------------------------------------------------------------------


def test_same_bytes_writes_nothing(tmp_path: Path, wired_paths, permit_adjudication) -> None:
    cfg = _conf(tmp_path)
    _seed(cfg, "note.md", "# 初稿\n")
    target = _root(cfg) / "note.md"
    before = target.stat().st_mtime_ns
    result = _chat(tmp_path, cfg, "把 note.md 更新一下", "# 初稿\n")
    assert "没变化" in result.body, result.body
    assert target.read_text(encoding="utf-8") == "# 初稿\n"
    assert target.stat().st_mtime_ns == before, "同字节回写会刷新 mtime＝对「改了什么」说谎"


# ---------------------------------------------------------------------------
# ③ 目标缺失：诚实人话、绝不借改之名新建、不烧生成
# ---------------------------------------------------------------------------


def test_missing_target_refuses_without_creating(tmp_path: Path, wired_paths, permit_adjudication) -> None:
    cfg = _conf(tmp_path)
    _seed(cfg, "note.md", "# 初稿\n")
    result = _chat(tmp_path, cfg, "把 ghost.md 修改一下，补一节", "# 补充一节\n")
    assert "读不了" in result.body, result.body
    assert result.body != "# 补充一节\n", "拒绝轮不该把模型稿原样端出去"
    assert "artifact_revise:target_missing" in result.audit_tags
    assert "ghost.md" not in {p.name for p in _root(cfg).rglob("*")}


# ---------------------------------------------------------------------------
# ④ 白名单外：`..` 形态明拒；白名单外的同名文件在受限回读里根本看不见
# ---------------------------------------------------------------------------


def test_outside_whitelist_refuses(tmp_path: Path, wired_paths, permit_adjudication) -> None:
    cfg = _conf(tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "secret.md").write_text("s\n", encoding="utf-8")
    result = _chat(tmp_path, cfg, "把 ../elsewhere/secret.md 替换掉", "新内容\n")
    assert "白名单" in result.body, result.body
    assert "artifact_revise:traversal_denied" in result.audit_tags
    assert (outside / "secret.md").read_text(encoding="utf-8") == "s\n"
    # 不带 .. 的同名指认：containment——白名单外的文件受限回读看不见（目标缺失）。
    result2 = _chat(tmp_path, cfg, "把 secret.md 替换掉", "新内容\n")
    assert "读不了" in result2.body, result2.body
    assert (outside / "secret.md").read_text(encoding="utf-8") == "s\n"


# ---------------------------------------------------------------------------
# ⑤ 权限拒：真裁决（普通用户不够 file.write 的 trusted 下限）→ Q-02 轮换池；
#    超管也只到 ConsentRequired（确认回路未接，会话面不自批）
# ---------------------------------------------------------------------------


def test_permission_denied_uses_q02_pool(tmp_path: Path, wired_paths) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.user_copy import (
        ADMIN_GATE_TEMPLATES,
    )

    cfg = _conf(tmp_path)
    _seed(cfg, "note.md", "# 初稿\n")
    result = _chat(tmp_path, cfg, "把 note.md 修改一下", "# 修改稿\n")
    assert result.body in {t.format(action="修改文件") for t in ADMIN_GATE_TEMPLATES}, result.body
    assert "artifact_revise:adjudicate_denied" in result.audit_tags
    assert (_root(cfg) / "note.md").read_text(encoding="utf-8") == "# 初稿\n"


def test_super_admin_hits_consent_gate_not_self_approval(tmp_path: Path, wired_paths) -> None:
    cfg = _conf(tmp_path)
    _seed(cfg, "note.md", "# 初稿\n")
    result = _chat(
        tmp_path, cfg, "把 note.md 修改一下", "# 修改稿\n",
        sender_roles=["super_admin"],
    )
    assert "要先过一次确认" in result.body, result.body
    assert "artifact_revise:consent_required" in result.audit_tags
    assert (_root(cfg) / "note.md").read_text(encoding="utf-8") == "# 初稿\n"


# ---------------------------------------------------------------------------
# ⑥ 不降级成创建：同轮混说「改一下再导出一份」⇒ 修改腿赢，零新文件
# ---------------------------------------------------------------------------


def test_modify_intent_never_degrades_to_creation(tmp_path: Path, wired_paths, permit_adjudication) -> None:
    cfg = _conf(tmp_path)
    _seed(cfg, "note.md", "# 初稿\n")
    before = sorted(p.name for p in _root(cfg).iterdir())
    result = _chat(tmp_path, cfg, "把 note.md 修改一下，然后保存成 md 发我", "# 修改稿\n")
    assert "已改好并回读确认" in result.body, result.body
    assert Path(result.files[0]["name"]).name == "note.md"
    assert sorted(p.name for p in _root(cfg).iterdir()) == before, "修改腿不得新建任何文件"


# ---------------------------------------------------------------------------
# ⑦ 休眠面：config 未注入＝整腿休眠，行为与旧版逐字节一致（不拒、不建、不写）
# ---------------------------------------------------------------------------


def test_without_config_the_leg_sleeps(tmp_path: Path, wired_paths) -> None:
    result = _chat(tmp_path, None, "把 note.md 修改一下", "（拍拍你的手背）文件的事我们待会儿再说。")
    assert not result.files
    assert not [t for t in (result.audit_tags or []) if t.startswith("artifact_revise")]


# ---------------------------------------------------------------------------
# ⑧ 命中但没指名：问清目标，绝不猜、绝不降级成创建
# ---------------------------------------------------------------------------


def test_intent_without_name_asks_for_target(tmp_path: Path, wired_paths, permit_adjudication) -> None:
    cfg = _conf(tmp_path)
    _seed(cfg, "note.md", "# 初稿\n")
    result = _chat(tmp_path, cfg, "帮我把文件修改一下", "好的，内容如下\n")
    assert "哪份文件" in result.body, result.body
    assert "artifact_revise:target_unnamed" in result.audit_tags
    assert (_root(cfg) / "note.md").read_text(encoding="utf-8") == "# 初稿\n"
