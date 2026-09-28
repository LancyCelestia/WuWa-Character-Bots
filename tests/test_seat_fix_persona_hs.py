"""S-FIX-PERSONA-HS（53 号席）——人格热切换三缺口收口锁。

判活口径来源＝SnowLuma **真身安装目录** ``config-*.js`` 的 ``ACTION_REGISTRY``
（2026-09-28 现算，非插件树考古）：

    set_qq_profile: nickname(str,可选) / personal_note(str,可选) / sex(int 0-2,可选,
                    "0 未知，1 男，2 女")
    set_qq_avatar:  file(f.image())

⇒ 动作册「可写四样」＝昵称 / 签名 / 性别 / 头像。三缺口对账：

- ①QQ 外观跟切：下发腿 ``apply_persona_profile``＋根装配 ``_dispatch_persona_appearance_if_switched``
  前席已落（H-1 逐项回执）；**本席补齐第四格「性别」**——此前 ``qq.sex`` 在册 JSON
  里有位、加载器从不解析、下发腿从不拼入，等于四样只接了三样。
  红线照 §49.9：性别**在册才发**，绝不默认、绝不从名字推断（两号真身 sex 均为空 ⇒
  生产行为零变化，本锁只钉机制）。
- ②知识清单构造期快照：PersonaSelector 可调用视图＋providers ``_effective_knowledge_files``
  / ``_effective_persona_files`` 每轮现读（复用 PersonaProfileRegistry 既有装载链，
  零第二真身）——前席已落，本席以「视图与消费同速」活性锁复核。
- ③卡片头像只在 on_bot_connect 刷：切人格钩子补刷已落（下发腿 ``set_local_path`` 登记
  ＋ ``refresh_from_qq`` F-F 钉图防回源覆盖）——本席钉「未表态人格不动卡片头像、
  在册人格切完即刷」两条判据。

全离线：tmp_path 造册、fake transport，零真机下发、零真实 personas/registry 触写。
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    persona_profile as pp,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
    PersonaProfileRecord,
    PersonaProfileRegistry,
    apply_persona_profile,
)


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, action: str, params: dict) -> dict:
        self.calls.append((action, dict(params)))
        return {"retcode": 0, "data": {}}

    def params_of(self, action: str) -> dict:
        for name, params in self.calls:
            if name == action:
                return params
        raise AssertionError(f"未见调用 {action}：{self.calls}")


def _record(**kwargs) -> PersonaProfileRecord:
    base = {"persona_id": "danya", "display_name": "达妮娅"}
    base.update(kwargs)
    return PersonaProfileRecord(**base)


def _write_profile(registry_dir: Path, persona_id: str, payload: dict) -> None:
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / f"{persona_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# ①第四格：sex 装载与下发
# ---------------------------------------------------------------------------

def test_sex_declared_is_dispatched_in_set_qq_profile() -> None:
    """在册表态性别 ⇒ 与昵称/签名同发 set_qq_profile，值为动作册整型枚举。"""
    record = _record(qq_nickname="达妮娅", qq_signature="微光", qq_sex=2)
    transport = _FakeTransport()
    asyncio.run(apply_persona_profile(record, call_api=transport))
    params = transport.params_of("set_qq_profile")
    assert params["sex"] == 2
    assert params["nickname"] == "达妮娅"


def test_sex_only_declaration_still_triggers_profile_dispatch() -> None:
    """只有性别一格表态 ⇒ qq_profile 腿照发（不许被当成"未表态"塌成 skipped）。"""
    record = _record(qq_sex=1)
    transport = _FakeTransport()
    receipt = asyncio.run(apply_persona_profile(record, call_api=transport))
    assert transport.params_of("set_qq_profile") == {"sex": 1}
    assert "qq_profile" in receipt.landed


def test_sex_unstated_never_dispatched_and_never_inferred() -> None:
    """§49.9 红线锁：sex 不表态 ⇒ 参数里零「sex」键——即便昵称像性别名也绝不推断。"""
    record = _record(qq_nickname="达妮娅", qq_signature="微光")  # qq_sex 缺省 None
    transport = _FakeTransport()
    asyncio.run(apply_persona_profile(record, call_api=transport))
    assert "sex" not in transport.params_of("set_qq_profile")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),          # 缺字段
        ("", None),            # 空串（两号真身现状）
        ("   ", None),         # 空白
        (0, 0),                # 0 未知（动作册在册值，表态即发）
        (1, 1),
        (2, 2),
        ("1", 1),              # 数字串等价采信
        ("2", 2),
        (3, None),             # 越界（枚举 0-2 之外）⇒ 点名拒收
        (-1, None),
        ("男", None),          # 中文词面不在册（册口径是 0/1/2）⇒ 拒收不折算
        ("male", None),
        (True, None),          # bool 是 int 子类，必须先行排除
        ([1], None),
        ({"v": 1}, None),
    ],
)
def test_sex_register_parsing_whitelist(tmp_path: Path, raw: object, expected: object) -> None:
    reg_dir = tmp_path / "registry"
    payload: dict = {"persona_id": "danya", "qq": {"nickname": "达妮娅", "sex": raw}}
    if raw is None:
        payload = {"persona_id": "danya", "qq": {"nickname": "达妮娅"}}
    _write_profile(reg_dir, "danya", payload)
    registry = PersonaProfileRegistry(reg_dir)
    record = registry.get("danya")
    assert record is not None
    assert record.qq_sex == expected
    if raw is not None and expected is None:
        # 拒收必须点名（warning 留文件名级线索，装载不炸册、不吞整册）。
        assert record.qq_nickname == "达妮娅"


def test_sex_hot_follows_register_edit(tmp_path: Path) -> None:
    """热读面：改册内 sex ⇒ 下一读即随，不重启（H-5乙热读延伸到第四格）。"""
    reg_dir = tmp_path / "registry"
    _write_profile(reg_dir, "danya", {"persona_id": "danya", "qq": {"sex": ""}})
    registry = PersonaProfileRegistry(reg_dir)
    assert registry.get("danya").qq_sex is None
    _write_profile(reg_dir, "danya", {"persona_id": "danya", "qq": {"sex": "1"}})
    assert registry.get("danya").qq_sex == 1


# ---------------------------------------------------------------------------
# ①参数形状白名单锁：出站参面 ⊆ 动作册可写四样（判活尺=config-*.js 现算口径）
# ---------------------------------------------------------------------------

@pytest.fixture
def outbound_policy(tmp_path: Path) -> Iterator[Path]:
    """头像出站闸注成 tmp 树（走 paths 件文档化测试注入口，同 test_persona_hot_switch 口径）。"""
    from plugins.bot_unified_runtime.domains.core.safety_exec import paths

    paths.set_default_policy(
        paths.build_policy(workspace_root=tmp_path, runtime_data_root=tmp_path / "data")
    )
    try:
        yield tmp_path
    finally:
        paths.set_default_policy(None)


def test_dispatch_params_within_manual_whitelist(
    tmp_path: Path, outbound_policy: Path
) -> None:
    avatar = tmp_path / "avatar.png"
    avatar.write_bytes(b"\x89PNG fake")
    record = _record(
        qq_nickname="达妮娅", qq_signature="微光", qq_sex=2, qq_avatar_path=str(avatar)
    )
    transport = _FakeTransport()
    asyncio.run(apply_persona_profile(record, call_api=transport))
    # set_qq_profile 参面只准出现动作册在册的三格；set_qq_avatar 必带 file。
    assert set(transport.params_of("set_qq_profile")) <= {
        "nickname",
        "personal_note",
        "sex",
    }
    assert "file" in transport.params_of("set_qq_avatar")


def test_manual_whitelist_literals_pinned_to_source() -> None:
    """形状锁：下发通道本体内 set_qq_profile 参键只允许册内三枚字面量。

    判据＝``apply_persona_profile`` 源码里 profile_params 的键面
    （"nickname"/"personal_note"/"sex"）——想加第五样（如 birthday/所在地，
    §49.7 结构性写不进）必先改真身并被本锁点名。
    """
    source = inspect.getsource(pp.apply_persona_profile)
    for key in ('profile_params["nickname"]', 'profile_params["personal_note"]', 'profile_params["sex"]'):
        assert key in source, f"在册可写格键面漂移：{key} 不在下发通道内"
    # 册外键一律不许出现（防"顺手拼一个 birthday"回潮）。
    for banned in ('profile_params["birthday"]', 'profile_params["city"]', 'profile_params["email"]'):
        assert banned not in source


# ---------------------------------------------------------------------------
# ③卡片头像：切人格钩子补刷的两条判据
# ---------------------------------------------------------------------------

def test_card_avatar_follows_dispatched_avatar(tmp_path: Path, outbound_policy: Path) -> None:
    avatar = tmp_path / "avatar.png"
    avatar.write_bytes(b"\x89PNG fake")
    record = _record(qq_nickname="达妮娅", qq_avatar_path=str(avatar))
    cards: list[str] = []
    receipt = asyncio.run(
        apply_persona_profile(
            record, call_api=_FakeTransport(), card_avatar_hook=cards.append
        )
    )
    assert cards == [str(avatar)]
    assert "card_avatar" in receipt.landed


def test_card_avatar_untouched_when_persona_has_no_avatar() -> None:
    """回切无头像人格（主人格现状）⇒ 卡片腿 skipped 点名，绝不清图/绝不假随切。"""
    record = _record(qq_nickname="守岸人")
    cards: list[str] = []
    receipt = asyncio.run(
        apply_persona_profile(
            record, call_api=_FakeTransport(), card_avatar_hook=cards.append
        )
    )
    assert cards == []
    by_item = {item.item: item.status for item in receipt.items}
    assert by_item["card_avatar"] == "skipped"


# ---------------------------------------------------------------------------
# 注毒自证（纪律：FAILED 才算抓住）——实跑记录见下方注释与席卷
# ---------------------------------------------------------------------------

# 注毒记录（如实，实跑输出粘贴于 logs/SEAT-FIX-PERSONA-HS.md）：本锁落地时对
# 真身注入一次「sex 缺省塌成 0 并恒拼入」形态（``profile_params["sex"] =
# int(record.qq_sex or 0)``），复跑本文件 ⇒「不表态零下发」腿必红；撤销注毒
# 复跑 ⇒ 全绿。以下静态腿是同一条红线的源码面哨兵（防缺省折算回潮）。


def test_no_default_sex_folding_in_source() -> None:
    """真身源码里绝不允许出现缺省 0 折算形态（在册才发的静态哨兵）。"""
    source = inspect.getsource(pp.apply_persona_profile)
    assert "record.qq_sex or 0" not in source

