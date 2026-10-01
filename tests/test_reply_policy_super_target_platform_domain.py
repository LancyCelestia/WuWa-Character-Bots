r"""席 N1 · P3.11：`"super"` 死判据根修 + 超管身份的平台域（跨平台裸号冒名面）。

病根两条（账在 `patches/W-E05-GATE-GAPS-20260930.md` §6，本件把它从"记账"变成"闭案"）：

1. `reply_policy.py` 的管理门写的是 `if "admin" not in roles and "super" not in roles:`，
   而 `"super"` **不是任何真身角色名**（六级角色真身＝`policy/roles.py` 的
   user/trusted/enterprise/admin/super_admin/blocked）。该腿恒真，从没成立过一次；
   唯一没出事的原因＝超管自动叠 admin。⇒ 死判据 + 一条隐式依赖：叠加哪天被拆，
   超管当场掉出本门且无人出声。
2. 超管身份旧写法 `actor_is_super = "super" in roles or str(sender_id).strip() in super_ids`
   两半腿都坏：前者永不成立；后者拿**裸 sender_id** 比 QQ 名单，**绕过平台域这一腿**
   （中央真身 `roles._roster_hit` 要求「裸号只在 QQ 域命中、带前缀条目只在同域命中、
   取不到平台事实一律不放行」）。后果＝Telegram 侧一个数字 user_id 撞上 QQ 超管号
   就白拿超管脸，email/console 域本该落空串不放行却照样放行。

判据一律走中央角色名常量，本件不起第二套角色体系；平台域用 `RoleSettings.resolve_roles`
现算（`IncomingMessage.platform` 是事实来源），不在测试里抄第二份名单规则。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, ClassVar

import pytest

from plugins.bot_unified_runtime.contracts import SessionType
from plugins.bot_unified_runtime.domains.chat_reply.character import reply_policy as rp
from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
    ReplyPolicyStore,
    person_reply_policy_key,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    ROLE_ADMIN,
    ROLE_BLOCKED,
    ROLE_ENTERPRISE,
    ROLE_SUPER_ADMIN,
    ROLE_TRUSTED,
    ROLE_USER,
    build_role_settings,
)

SUPER_QQ = "1722380002"
ADMIN_QQ = "1000000001"
PLAIN_QQ = "9000000001"
# 与 SUPER_QQ **数字相同、但来自 Telegram 侧**的那枚号——冒名面的主角。它在
# `bot_telegram_admin_user_ids` 里，所以中央角色面会给它 `admin`（TG 名单真生效），
# 但绝不给 `super_admin`：旧写法的裸号比对正是拿这一格分道的（旧＝能改 QQ 超管，
# 新＝被第二道门拒）。
COLLIDER = SUPER_QQ


class _Config:
    """只暴露 builder 真正会读的键（其余一律不给，读到就是设计错）。"""

    bot_super_admin_user_ids: ClassVar[tuple[str, ...]] = (SUPER_QQ,)
    bot_admin_user_ids: ClassVar[tuple[str, ...]] = (ADMIN_QQ,)
    bot_telegram_admin_user_ids: ClassVar[tuple[str, ...]] = (COLLIDER,)
    bot_enterprise_user_ids: ClassVar[tuple[str, ...]] = ()
    bot_trusted_user_ids: ClassVar[tuple[str, ...]] = ()
    bot_blocked_user_ids: ClassVar[tuple[str, ...]] = ()
    bot_admin_profiles: ClassVar[tuple[dict[str, str], ...]] = ()


@pytest.fixture()
def store(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> ReplyPolicyStore:
    real = ReplyPolicyStore(tmp_path / "reply_policy.sqlite3")
    # 凡走 /bot reply 命令面的测试必须换掉共享存储（台账 #66★）：`.env` 的 Runtime 根
    # 直指生产库，不 patch 就是往生产数据里写。
    monkeypatch.setattr(rp, "shared_reply_policy_store", lambda _config: real)
    return real


def _roles_for(platform: str, sender_id: str) -> list[str]:
    """中央角色真身现算（平台域在这一腿就定好，不在调用侧另判）。"""
    message = _message(platform, sender_id)
    return build_role_settings(_Config()).resolve_roles(message)


def _message(platform: str, sender_id: str) -> Any:
    from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
        IncomingMessage,
    )

    session_type = SessionType.PRIVATE
    return IncomingMessage(
        platform=platform,
        adapter="onebot" if platform == "qq" else platform,
        bot_id="10000",
        session_id=f"{platform}:{sender_id}",
        session_type=session_type,
        sender_id=sender_id,
        plain_text="回复 设定 详尽",
    )


def _run(text: str, *, sender: str, roles: list[str]):
    return rp.build_reply_policy_preset_result(
        _Config(),
        request_id="req-n1-super",
        sender_id=sender,
        actor_roles=roles,
        command_text=text,
    )


# ---------------------------------------------------------------------------
# ① 平台域：跨平台同号拿不到超管脸（冒名面关闭）
# ---------------------------------------------------------------------------


def test_central_roles_are_the_only_super_source_and_domain_aware() -> None:
    """合法形＝QQ 域超管拿到 super_admin；越界形＝TG 同数字号拿不到。

    这一格锁的是"调用侧只能吃这份产物"：`actor_is_super` 一旦改回去比裸号，
    下面那枚 `telegram` 读数就会变成 True，命令面的 denied_super_target 当场失效。
    """
    qq_super = _roles_for("qq", SUPER_QQ)
    assert ROLE_SUPER_ADMIN in qq_super, qq_super
    assert ROLE_ADMIN in qq_super, "超管自动叠 admin（roles.py 既有语义，不许回潮）"

    # 同数字号换到 TG 侧：QQ 超管名单吃不到它（裸号只在 QQ 域命中）。
    tg_collider = _roles_for("telegram", COLLIDER)
    assert ROLE_SUPER_ADMIN not in tg_collider, tg_collider
    assert tg_collider == [ROLE_USER, ROLE_ADMIN], (
        f"TG 名单里的同数字号该拿到 admin 而不该拿到 super_admin：{tg_collider}"
    )
    # 不在 TG 名单里的同号数字，在 TG 域彻底是平民。
    assert _roles_for("telegram", PLAIN_QQ) == [ROLE_USER], PLAIN_QQ

    for platform in ("email", "console", "", "unknown_platform"):
        assert _roles_for(platform, SUPER_QQ) == [ROLE_USER], platform


def test_cross_platform_collider_cannot_repin_a_super_admin(
    store: ReplyPolicyStore,
) -> None:
    """端到端越界形（本席唯一分道新旧写法的格子）：

    角色事实现算＝`["user","admin"]`（TG 名单真给他 admin，第一道管理门**照过**），
    数字与 QQ 超管号相同。旧写法在这里补 `actor_is_super = sender_id in super_ids`
    那半腿 ⇒ 白拿超管脸、改得动 QQ 超管的口径（跨平台提权面，F-A 治的同一刀落在命令面的
    残留）；新写法只认 `ROLE_SUPER_ADMIN in roles` ⇒ 第二道门拒、库里零写入。
    """
    tg_roles = _roles_for("telegram", COLLIDER)
    assert tg_roles == [ROLE_USER, ROLE_ADMIN], (
        f"前置不成立：这枚号连 admin 都没拿到，本格就没穿过第一道门：{tg_roles}"
    )
    result = _run(f"set {SUPER_QQ} 详尽", sender=COLLIDER, roles=tg_roles)
    assert store.get(person_reply_policy_key(sender_id=SUPER_QQ)) is None, (
        "TG 侧同数字号改动了 QQ 超管的永久回复口径 ⇒ 跨平台冒名面未闭"
    )
    assert "超管" in result.body or "无权" in result.body, result.body


def test_cross_platform_collider_can_still_pin_a_plain_person(
    store: ReplyPolicyStore,
) -> None:
    """反向不误伤：收口只关「横跨提权面」那一腿，TG 管理员管平民照旧生效。"""
    tg_roles = _roles_for("telegram", COLLIDER)
    result = _run(f"set {PLAIN_QQ} 详尽", sender=COLLIDER, roles=tg_roles)
    assert result.kind == "text", result.body
    assert store.get(person_reply_policy_key(sender_id=PLAIN_QQ)) is not None


def test_admin_still_cannot_cross_the_super_face_after_the_literal_is_gone(
    store: ReplyPolicyStore,
) -> None:
    """不误伤腿①：清掉 `"super"` 字面量之后，普通管理员**仍旧**改不动超管口径。

    这一格是"死判据摘掉之后语义没跟着塌"的反证：旧写法里 admin 非超管能过第一道门
    （`"admin" in roles` 成立），却被第二道超管目标门拦住；新写法两枚中央常量都在，
    拦的方向一模一样。
    """
    admin_roles = _roles_for("qq", ADMIN_QQ)
    assert admin_roles == [ROLE_USER, ROLE_ADMIN], admin_roles
    result = _run(f"set {SUPER_QQ} 详尽", sender=ADMIN_QQ, roles=admin_roles)
    assert "超管" in result.body or "无权" in result.body, result.body
    assert store.get(person_reply_policy_key(sender_id=SUPER_QQ)) is None


def test_plain_admin_can_still_pin_a_non_super_person(
    store: ReplyPolicyStore,
) -> None:
    """不误伤腿②：admin（非超管）改平民照旧生效——摘死判据不许顺手把门焊死。"""
    admin_roles = _roles_for("qq", ADMIN_QQ)
    result = _run(f"set {PLAIN_QQ} 详尽", sender=ADMIN_QQ, roles=admin_roles)
    assert result.kind == "text", result.body
    row = store.get(person_reply_policy_key(sender_id=PLAIN_QQ))
    assert row is not None and row.length_mode == rp.LENGTH_MODE_VERBOSE, row


def test_super_admin_from_central_roles_can_pin_a_super_target(
    store: ReplyPolicyStore,
) -> None:
    """合法形：QQ 域超管改超管（含自己）→ 落库。"""
    super_roles = _roles_for("qq", SUPER_QQ)
    result = _run(f"set {SUPER_QQ} 适中", sender=SUPER_QQ, roles=super_roles)
    assert result.kind == "text", result.body
    assert store.get(person_reply_policy_key(sender_id=SUPER_QQ)) is not None


# ---------------------------------------------------------------------------
# ② grep 门：字面量 `"super"` 不得再出现在「判定」里
# ---------------------------------------------------------------------------

#: 判定形＝把 `"super"` 当**被包含项**去比角色集（`"super" in roles` /
#: `"super" not in roles` 两形都算）。不扫 `role in {"super", ...}` 那种**展示用**容错
#: 映射（chat.py 的 role_label 同形，它把用户自填的 `bot_admin_profiles[].role` 翻成中文
#: 标签，不是权限判据），也不扫注释行（本仓把病态形原样引在册注释里是既有纪律，
#: 摘掉引文会让"为什么这么改"失去出处）。
_JUDGMENT_PATTERN = re.compile(r"""["']super["']\s+(?:not\s+)?in\s+[A-Za-z_][A-Za-z0-9_.]*""")

_SCANNED = (
    "plugins/bot_unified_runtime/domains/chat_reply/character/reply_policy.py",
    "plugins/bot_unified_runtime/domains/chat_reply/policy/roles.py",
    "plugins/bot_unified_runtime/domains/chat_reply/policy/gate.py",
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py",
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py",
    "plugins/bot_unified_runtime/domains/assistant/daily/capabilities/daily_assist.py",
    "plugins/bot_unified_runtime/domains/chat_reply/runtime/pipeline.py",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_super_literal_is_not_used_as_a_role_judgment() -> None:
    root = _repo_root()
    offenders: list[str] = []
    for rel in _SCANNED:
        path = root / rel
        if not path.is_file():
            continue  # 缺席点名在下一格处理，本格只判形态
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.lstrip().startswith("#"):
                continue  # 在册注释引的是病态形原文，不是判定
            if _JUDGMENT_PATTERN.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "字面量 `\"super\"` 又回到角色判定里（真身是 super_admin）：\n" + "\n".join(offenders)
    )


def test_super_literal_gate_has_teeth() -> None:
    """注毒自证：本尺不是空跑的——把两枚旧判据原样喂进去都必须命中。"""
    for poisoned in (
        'if "admin" not in roles and "super" not in roles:\n    return deny()',
        'actor_is_super = "super" in roles or sender_id in super_ids',
    ):
        assert _JUDGMENT_PATTERN.search(poisoned), f"注毒没打红 ⇒ 这道尺是空跑的：{poisoned}"
    # 反向不误伤：展示用容错映射、真身常量、注释引文三类都不许算违规。
    assert not _JUDGMENT_PATTERN.search(
        'label = "超级管理员" if role in {"super", "super_admin"} else "管理员"'
    )
    assert not _JUDGMENT_PATTERN.search(f"if {ROLE_SUPER_ADMIN!r} in roles: pass")
    # 注释引文由扫描循环按行首 `#` 排除（本件把病态形留在注释里是刻意的，见上）。
    quoted = '    # 旧写法 actor_is_super = "super" in roles or ...'
    assert quoted.lstrip().startswith("#"), "扫描面的注释排除口径写错了"


def test_scanned_files_actually_exist() -> None:
    """防"整条门因为路径写错而空跑"——扫描面里一半以上文件不存在即红。"""
    root = _repo_root()
    missing = [rel for rel in _SCANNED if not (root / rel).is_file()]
    assert len(missing) <= 1, f"扫描面路径失效：{missing}"


# ---------------------------------------------------------------------------
# ③ 中央角色名册不许被调用侧抄第二份
# ---------------------------------------------------------------------------


def test_reply_policy_reads_the_single_super_roster_field() -> None:
    """目标名单仍只读同一枚 config 字段，且不许在本文件里长出第二份角色名。"""
    text = (_repo_root() / "plugins/bot_unified_runtime/domains/chat_reply/character/reply_policy.py").read_text(
        encoding="utf-8"
    )
    assert text.count("bot_super_admin_user_ids") == 1, "第二处读超管名单＝第二本账"
    assert "ROLE_SUPER_ADMIN" in text, "本文件不引中央角色常量＝自己抄一份角色名"
    assert ROLE_BLOCKED and ROLE_TRUSTED and ROLE_ENTERPRISE  # 名册真身仍可引用，不许在本文件写死


def test_central_role_names_are_the_documented_six() -> None:
    """名册自检：本件写死的角色名与 `roles.py` 的六档逐一对得上。"""
    assert (ROLE_USER, ROLE_TRUSTED, ROLE_ENTERPRISE, ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_BLOCKED) == (
        "user",
        "trusted",
        "enterprise",
        "admin",
        "super_admin",
        "blocked",
    )
