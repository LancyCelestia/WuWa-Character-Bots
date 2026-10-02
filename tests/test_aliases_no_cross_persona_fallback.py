"""别名兜底「诚实缺席」锁（S5d 接手 S5c 半件 · 多人格隔离波 单元 1 的执法腿）。

要锁的形态（台账 #66★ 同型：盘上状态≠运行时状态）：
``personas/<id>/aliases.txt`` 缺席时，代码回落 ``DEFAULT_PERSONA_NICKNAMES``——
那九名是**主人格**的策展称呼，于是切到别的人格后昵称门 / 表情主体判定 /
命令别名三条腿一起「叫新人格、用旧人格的名字应」，而盘上「这一格没备料」
这件事被兜底表吃掉了。

判据照抄 ``character/imagery_roster.py`` 的缺席写法（读不到 ⇒ ``return ()``
＋一行可 grep 的留痕），**不新造机制**：
- 正向腿＝主人格档行为**逐字不变**（它是生产实读面，2026-09-11 昵称无响应根修不许回退）；
- 注毒腿＝给一枚无别名文件的人格 id 造读取，断言它拿不到主人格**任何**一名，
  也拿不到主人格 aliases.txt 里的独有 marker（证明不是「读错了根」而是真不借）。

全离线：把 ``aliases._REPO_ROOT`` 指到 tmp 假人格根，真实 ``personas/`` 全程只读、
零写入；不 import 生产 Config（台账 #66★）。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
    main_persona_id,
    resolve_persona_id,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import aliases as al

#: 主人格 aliases.txt 的独有 marker：只出现在假根里那枚文件，别的人格读到它＝串格。
_MAIN_ONLY_MARKER = "S5D幻名只属主人格"
#: 只有 env 声明才可能进来的称呼（证明缺席≠「一律返回空」的哑门）。
_ENV_ONLY_TERM = "S5D只属这格的称呼"


class _StubConfig:
    """只带人格档的配置替身（与 test_persona_asset_paths 同形态，不 import 生产 Config）。

    ⚠ 必须**逐枚显式赋值**：``__getattr__`` 兜 None 会让 ``str(getattr(...))`` 得到
    字面量 "None"，把一枚假昵称塞进解析器（量具自己先脏）。
    """

    def __init__(self, persona_id: str, **extra: object) -> None:
        self.bot_persona_profile_id = persona_id
        self.bot_persona_nicknames: list[str] = []
        self.bot_runtime_persona_nickname: str = ""
        self.bot_runtime_persona_nicknames: list[str] = []
        self.bot_runtime_instance: str = ""
        for key, value in extra.items():
            setattr(self, key, value)

    def __getattr__(self, item: str) -> object:
        return None


@pytest.fixture
def persona_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """假人格根：主人格有词表（含独有 marker），第二格压根没备料。"""
    owner = main_persona_id()
    assert owner, "注册表没有 is_main 那一格 ⇒ 主人格档没得判，本锁退化成空转"
    other = f"{owner}-second-seat"
    curated = "|".join(al.DEFAULT_PERSONA_NICKNAMES)
    assert curated, "策展兜底表为空 ⇒ 这把行为尺没牙"

    root = tmp_path / "repo"
    owner_dir = root / "personas" / owner
    owner_dir.mkdir(parents=True)
    owner_dir.joinpath("aliases.txt").write_text(
        f"{curated}|{_MAIN_ONLY_MARKER}\n", encoding="utf-8"
    )
    (root / "personas" / other).mkdir(parents=True)  # 有目录、无 aliases.txt
    monkeypatch.setattr(al, "_REPO_ROOT", root)
    return {"owner": owner, "other": other, "root": str(root)}


def _terms(persona_id: str, **extra: object) -> tuple[str, ...]:
    return al.persona_alias_terms(_StubConfig(persona_id, **extra))


# ---------------------------------------------------------------------------
# 1. 注毒腿：这一格没备料 ⇒ 拿不到主人格任何一名
# ---------------------------------------------------------------------------


def test_persona_without_alias_file_borrows_no_main_persona_alias(
    persona_root: dict[str, str]
) -> None:
    other = persona_root["other"]
    assert resolve_persona_id(_StubConfig(other)) == other, "生效人格被切换态劫走 ⇒ A/B 腿失真"
    terms = _terms(other)
    borrowed = set(terms) & set(al.DEFAULT_PERSONA_NICKNAMES)
    assert not borrowed, f"{other} 借了主人格的策展兜底：{sorted(borrowed)}"
    assert _MAIN_ONLY_MARKER not in terms, (
        f"{other} 读到主人格的 aliases.txt ⇒ 根被拼错/回落，串格读取"
    )
    assert terms == (), f"诚实缺席应是空名册，现算 {terms}"


def test_unenrolled_persona_root_absent_is_also_honest(
    persona_root: dict[str, str]
) -> None:
    """连目录都没有（新建人格还没建档）：同样只申报缺席，不端别人家的。"""
    terms = _terms(f"{persona_root['other']}-never-created")
    assert not (set(terms) & set(al.DEFAULT_PERSONA_NICKNAMES)), terms
    assert _MAIN_ONLY_MARKER not in terms, terms


def test_absence_is_not_a_dead_door_env_terms_still_land(
    persona_root: dict[str, str]
) -> None:
    """防「恒空」哑门：这一格**自己声明**的昵称必须照收（缺席只针对借兜底）。"""
    terms = _terms(persona_root["other"], bot_persona_nicknames=[_ENV_ONLY_TERM])
    assert terms == (_ENV_ONLY_TERM,), terms


# ---------------------------------------------------------------------------
# 2. 正向腿：主人格档行为逐字不变（生产实读面）
# ---------------------------------------------------------------------------


def test_main_persona_keeps_the_full_curated_set(persona_root: dict[str, str]) -> None:
    owner = persona_root["owner"]
    assert resolve_persona_id(_StubConfig(owner)) == owner
    terms = set(_terms(owner))
    assert terms >= set(al.DEFAULT_PERSONA_NICKNAMES), (
        f"主人格丢了策展兜底 ⇒ 2026-09-11 昵称无响应根修回退：{sorted(al.DEFAULT_PERSONA_NICKNAMES - terms)}"
    )
    assert _MAIN_ONLY_MARKER in terms, (
        "主人格的 aliases.txt 没被读到 ⇒ 词表那半截是死的，兜底表在替它说谎"
    )


def test_curated_fallback_gate_is_per_persona(persona_root: dict[str, str]) -> None:
    assert al._curated_fallback_applies(_StubConfig(persona_root["owner"])) is True
    assert al._curated_fallback_applies(_StubConfig(persona_root["other"])) is False
    # 连「生效谁」都取不到＝没切过 ⇒ 保持出厂行为（不许把主人格也判成缺席）
    assert al._curated_fallback_applies(_StubConfig("default")) is True


# ---------------------------------------------------------------------------
# 3. 命令别名解析器同一口径（昵称门的执行面）
# ---------------------------------------------------------------------------


def test_alias_resolver_follows_the_same_absence(persona_root: dict[str, str]) -> None:
    owner = persona_root["owner"]
    other = persona_root["other"]

    owner_resolver = al.build_command_alias_resolver(_StubConfig(owner))
    assert set(owner_resolver.nicknames) >= set(al.DEFAULT_PERSONA_NICKNAMES)
    assert _MAIN_ONLY_MARKER in owner_resolver.nicknames
    # 昵称＝词表里的词，不是人格 id（把 id 当昵称去 resolve 会得到一枚恒 None 的空腿）
    resolved = owner_resolver.resolve(f"/{_MAIN_ONLY_MARKER}帮助")
    assert resolved is not None and resolved.capability_id == "bot.help"

    other_resolver = al.build_command_alias_resolver(_StubConfig(other))
    assert other_resolver.nicknames == [], (
        f"{other} 的解析器拿到了主人格的名册：{other_resolver.nicknames}"
    )
    assert other_resolver.resolve(f"/{_MAIN_ONLY_MARKER}帮助") is None, "缺席格仍可被主人格名字叫应"


# ---------------------------------------------------------------------------
# 4. 缺席必须留痕（可 grep 的读数，不刷 WARN 噪音）
# ---------------------------------------------------------------------------


def test_declined_fallback_leaves_a_greppable_trace(
    persona_root: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    other = persona_root["other"]
    with caplog.at_level(logging.DEBUG, logger=al.logger.name):
        _terms(other)
    traces = [
        rec.getMessage()
        for rec in caplog.records
        if "curated fallback declined" in rec.getMessage()
    ]
    assert len(traces) == 1, f"缺席没留痕（或留了多条）：{traces}"
    assert f"profile={other}" in traces[0] and "reason=not_main_persona" in traces[0]
    assert all(rec.levelno <= logging.DEBUG for rec in caplog.records if traces[0] in rec.getMessage())

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=al.logger.name):
        _terms(persona_root["owner"])
    assert not [r for r in caplog.records if "curated fallback declined" in r.getMessage()], (
        "主人格档不该有缺席留痕（有了＝兜底门被反向判定）"
    )
