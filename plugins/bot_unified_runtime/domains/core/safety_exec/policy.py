"""策略裁决点 PDP（SAFE-EXEC 规格 §1 的真身，S-T-SAFE-3 席，2026-09-25 落地）。

规格 ``docs/design/safety-execution-engine-spec.md`` §1 给本件的一句话职责：
「输入**动作 + 主体 + 落点 + 载荷指纹**，输出 ``Permit/Deny(kind)/NeedConsent``」。
§0 不变式①「一个动作只有一个裁决点」——``action_catalog.ADJUDICATION_POINT``
自 2026-09-25 起指向的就是本文件的 :func:`decide`（此前那是一张开给不存在文件的
空头支票，本席把它兑现；在册符号指向不存在件正是 #49 立规点名的形态）。

本件是什么：**合成口，不是第四张判定表**。三条硬边界——

1. **不自有条目**。可信级只吃 ``trust.py`` 的派生物（本件不读名单、不读正文）；
   参数风险档只调 ``config_risk`` 的谓词（本件零 ``re``、零键名清单）；
   动作声明只经 ``action_catalog.resolve_action``（册外动作当场抛，不给兜底档）。
   角色下限比较只吃 ``roles.ROLE_ORDER``（秩唯一真身，规格 §1「复用」），不自排序号。
2. **不代判落点**。路径域判定今天已在唯一咽喉执法（``file_gateway._stage_path`` 直调
   ``paths.check_sendable``，`tests/test_safety_exec_paths.py` 的第二通路锁把「谁准
   import paths」钉成登记消费点名单——policy 不在名单内，也不申请入名单：Wave 1 的
   落点收口本来就归咽喉，Wave 2 才把 ``fs.delete``/``code.run`` 收进裁决）。
   本件对路径族动作只在 :class:`Permit` 上给 ``landing_check_required`` 标记，
   由 PEP 在咽喉处出示判定结果。
3. **不签发、不复述**。同意号唯一由 ``consent.py`` 账本签发；「谁能批」的
   ``R2→T0 / R1→T0'`` 映射也只住那一处，本件的 :class:`ConsentRequired` 只携带
   ``requires_written`` 布尔（派生自 ``config_risk`` 谓词的一次调用）。
   拒绝话术每种代号**一句**确定性人话（不成池、不轮换——规格 §1 禁第二套话术池；
   档位说明一律复用 ``config_risk.describe_tier``）。

结构不变式（由 ``tests/test_safety_exec_policy.py`` 执法，注毒必红）：

- :func:`decide` 的入参**没有任何正文通道**：没有 ``plain_text``/``body``/
  ``content`` 形参，``payload_fingerprint`` 在函数体内**只准进字段赋值**、
  不得出现在任何比较/成员/前缀判断里（伪代码级锁）——「伪造系统提示前缀
  不升级为可信」由此成为结构性事实，不是逐条拦截；
- 入参里**没有好感度**（规格 §12 G-9「写了就红」）；
- 插件树内**模块级** ``def decide`` 恰好一处（本件；类方法同名者另有其人，
  锁只数模块级）；本件 import 面 ⊆ 三兄弟件 + ``roles`` + stdlib。

fail-closed 总纲：动作不在册→抛；来源未申报→拒；角色事实拿不到→拒；
目标名非法→拒；档位与动作不符→拒并点名该走哪枚动作。没有任何一条路
把「拿不准」折算成「放行」。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    ROLE_BLOCKED,
    ROLE_ORDER,
)
from plugins.bot_unified_runtime.domains.core.safety_exec import config_risk
from plugins.bot_unified_runtime.domains.core.safety_exec.action_catalog import (
    ACTION_CATALOG,
    ROLE_FLOOR_INTERNAL,
    ROLE_FLOOR_NO_ROLE,
    ActionId,
    ActionSpec,
    LandingDomain,
    resolve_action,
)
from plugins.bot_unified_runtime.domains.core.safety_exec.trust import (
    TrustLevel,
    is_untrusted_data,
    trust_rank,
)

__all__ = [
    "ConsentRequired",
    "Deny",
    "PdpDecision",
    "Permit",
    "PolicyDenyKind",
    "decide",
]


# ---------------------------------------------------------------------------
# 拒绝代号（稳定字符串进审计；规格 §7 点名的 `untrusted_source` 是其中之一）
# ---------------------------------------------------------------------------


class PolicyDenyKind(str, Enum):
    """PDP 自己的拒绝代号。**只这一份**；路径原因码住 ``paths``、
    同意域代号住 ``consent.DenyKind``，本件不复制它们的码表。"""

    UNTRUSTED_SOURCE = "untrusted_source"  # 规格 §7：触发链里没有可信来源
    INTERNAL_ONLY = "internal_only"  # 落点标了「内部」的动作由入站消息发起
    NO_ROLE_GRANTS_THIS = "no_role_grants_this"  # 角色下限登记为「任何角色都不够」
    ROLE_FLOOR_NOT_MET = "role_floor_not_met"  # 结构化角色低于动作下限
    ACTOR_ROLES_UNAVAILABLE = "actor_roles_unavailable"  # 该查角色时拿不到角色事实
    NEVER_AUTO = "never_auto"  # R3：永不自动，只出待审补丁
    CONFIG_TARGET_REQUIRED = "config_target_required"  # 配置面动作没给目标键
    TIER_ACTION_MISMATCH = "tier_action_mismatch"  # 目标实档 ≠ 动作在册档
    LANDING_TARGET_MISMATCH = "landing_target_mismatch"  # 非配置面动作塞了配置目标
    TARGET_UNNAMESABLE = "target_unnamesable"  # 目标名本身非法（形/空/meta 未登记）


#: 每种代号**一句**确定性人话（不成池、不轮换；规格 §1 禁止清单）。
_DENY_PLAIN: Final[dict[PolicyDenyKind, str]] = {
    PolicyDenyKind.UNTRUSTED_SOURCE: "这个请求的来源够不到可信说话人的档位，我只当它没说过。",
    PolicyDenyKind.INTERNAL_ONLY: "这件事只能由系统内部的装配点发起，消息侧我接不了。",
    PolicyDenyKind.NO_ROLE_GRANTS_THIS: "这件事没有任何角色能直接做，只能走待审补丁。",
    PolicyDenyKind.ROLE_FLOOR_NOT_MET: "发起人的角色还不够做这件事，要更高等级的人来提。",
    PolicyDenyKind.ACTOR_ROLES_UNAVAILABLE: "现在拿不到发起人的角色事实，我不猜，先不办。",
    PolicyDenyKind.NEVER_AUTO: "这一档我永不自动碰，最多产出一份待你过目的补丁。",
    PolicyDenyKind.CONFIG_TARGET_REQUIRED: "改参数总得说要改哪一个键，我不能替你猜目标。",
    PolicyDenyKind.TIER_ACTION_MISMATCH: "这个键的风险档和你选的动作对不上，我按档不走捷径。",
    PolicyDenyKind.LANDING_TARGET_MISMATCH: "这个动作不落在配置面上，别往这里塞参数键。",
    PolicyDenyKind.TARGET_UNNAMESABLE: "这个目标名我不认得（形不对或没登记），不带着疑问往下走。",
}


@dataclass(frozen=True)
class Permit:
    """放行凭证。**本身不含副作用**：PEP 拿它去执行，且必须兑现下列标记各自的事实。

    - ``landing_check_required``：路径/出站/SSRF 族动作的落点判定仍须在唯一咽喉
      （``paths.check_sendable`` / ``submit_active_push`` / ``check_download_url``）出示；
    - ``unattended_allowed`` + ``echo_required`` + ``rollback_required``：
      规格 §4 R0 两件套（回显 + 一键回退）的执法真身在 ``consent.apply_unattended``，
      本件只申报要求，不代执行。
    """

    action: ActionId
    role_floor: str
    tier: str
    unattended_allowed: bool = False
    echo_required: bool = False
    rollback_required: bool = False
    landing_check_required: bool = False
    payload_fingerprint: str = ""


@dataclass(frozen=True)
class Deny:
    """拒绝：代号 + 一句话 + 可诊断细节（细节只点名事实，不含正文回显）。"""

    action: ActionId
    kind: PolicyDenyKind
    detail: str = ""
    payload_fingerprint: str = ""

    @property
    def plain_text(self) -> str:
        """一句确定性人话。认不出的代号兜底点名代号本身，绝不编解释。"""
        return _DENY_PLAIN.get(self.kind, f"未登记的拒绝代号 {self.kind.value}，一律按拒绝算。")

    def line(self) -> str:
        text = f"{self.plain_text}（{self.action.value}｜{self.kind.value}）"
        return f"{text}\n{self.detail}" if self.detail else text


@dataclass(frozen=True)
class ConsentRequired:
    """需要同意：**裁决口只出要求，不出号**——同意号唯一由 ``consent`` 账本签发。

    ``requires_written`` 是「R2 超管书面同意」与「R1 本会话确认」的唯一分岔旗，
    由 ``config_risk.requires_written_consent`` 一次调用派生；「批语要哪一档可信级」
    的映射（``T0``/``T0'``）住在 ``consent.py``，本件不复制第二份。
    """

    action: ActionId
    target: str  # 配置面动作＝规范形键名；其余落点＝空串（目标细节归 PEP 咽喉）
    tier: str
    requires_written: bool
    payload_fingerprint: str = ""

    def plain_text(self) -> str:
        """裁决口的要求申报（**不含同意号**——号还没签发）。

        拿到号之后的人话回执真身住 ``consent.NeedsConsent.plain_text``（那里才带
        ``consent_id``）；本句刻意只说「要同意」与「谁能批」，不与其争同一句话的第二份。
        """
        who = "主人" if self.requires_written else "本会话里的管理员"
        subject = self.target or self.action.value
        return (
            f"这件事的档位是 {self.tier}：{subject} 要{who}批同意卡后才能落地"
            f"（{config_risk.describe_tier(config_risk.RiskTier(self.tier))}）。"
        )


#: 三种裁决结果（规格 §1 PDP 行的输出三态）。
PdpDecision = Permit | Deny | ConsentRequired


# ---------------------------------------------------------------------------
# 角色下限比较（只吃 roles.ROLE_ORDER，不自排秩）
# ---------------------------------------------------------------------------


def _roles_meet_floor(actor_roles: Sequence[str], floor: str) -> bool:
    """结构化角色是否达到动作下限。**被禁者不参与秩比较**（blocked 在
    ``ROLE_ORDER`` 里位置在最后，按索引比会虚高；可信级派生已把 blocked 收敛到
    T3、在来源门先被拒，这里是第二层不信任兜底）。"""
    if floor not in ROLE_ORDER:
        # 动作册的门已保证「非 ROLE_ORDER 成员 ⇒ 注册例外」，走到这里＝册内自相矛盾。
        raise RuntimeError(f"角色下限 {floor!r} 不在 roles.ROLE_ORDER 里，动作册与角色真身脱节")
    floor_rank = ROLE_ORDER.index(floor)
    for raw in actor_roles:
        role = str(raw).strip().lower()
        if role == ROLE_BLOCKED or role not in ROLE_ORDER:
            continue
        if ROLE_ORDER.index(role) >= floor_rank:
            return True
    return False


def _action_for_config_tier(tier: config_risk.RiskTier) -> ActionId | None:
    """「这个档该走哪枚配置写动作」——**从动作册派生**，不另抄映射表。"""
    for spec in ACTION_CATALOG.values():
        if spec.landing_domain is LandingDomain.CONFIG_SURFACE and spec.default_tier is tier:
            return spec.action
    return None


def _consent_gate(
    tier: config_risk.RiskTier,
    action: ActionId,
    target_name: str,
    payload_fingerprint: str,
) -> ConsentRequired | None:
    """档位 → 同意要求的**唯一分岔**（配置面与非配置面共用同一判据，两处调用此一处）。

    「谁够格批」（R2→超管 T0 / R1→管理员 T0'）的可信级映射**不在本件**——
    那份判定今天唯一住 ``consent.py``，本函数只把 ``config_risk`` 的两枚谓词
    各调一次组装成申报单，不复制第三份。
    """
    if config_risk.requires_written_consent(tier):
        return ConsentRequired(
            action=action,
            target=target_name,
            tier=tier.value,
            requires_written=True,
            payload_fingerprint=payload_fingerprint,
        )
    if config_risk.requires_consent(tier):
        return ConsentRequired(
            action=action,
            target=target_name,
            tier=tier.value,
            requires_written=False,
            payload_fingerprint=payload_fingerprint,
        )
    return None


# ---------------------------------------------------------------------------
# 裁决入口（插件树内模块级唯一一枚 `decide`，锁在 tests/test_safety_exec_policy.py）
# ---------------------------------------------------------------------------


def decide(
    *,
    action: object,
    actor_level: TrustLevel | None = None,
    actor_roles: Sequence[str] | None = None,
    config_target: object = None,
    payload_fingerprint: str = "",
    internal_origin: bool = False,
) -> PdpDecision:
    """动作册 × 可信级 × 参数风险档的**合成裁决口**。判定阶梯（自上而下，全 fail-closed）：

    1. 册外动作 → 抛 ``UnregisteredActionError``（``resolve_action`` 的原语，不兜底）；
    2. 动作在册档为 R3 → ``Deny(never_auto)``——连超管也不接（天花板是待审补丁）;
    3. 外部发起时来源可信级为 T2/T3（或没申报）→ ``Deny(untrusted_source)``；
    4. 角色下限/内部标记逐条对表（下限比较只吃 ``ROLE_ORDER``）；
    5. 配置面动作 → ``config_risk`` 现算实档：R3→拒；实档≠动作在册档→拒并点名
       该走哪枚动作；R2→书面同意；R1→本会话确认；R0→放行 + 两件套旗；
    6. 其余落点（路径/出站/SSRF/无落点）：先按动作册 tier 过同一个同意岔口
       （R1/R2 → ConsentRequired，如 code.run / fs.delete 要书面同意），
       R0 → 放行并置 ``landing_check_required`` 标记，要求 PEP 在各自唯一
       咽喉出示判定（本件不代判、不 import paths）。

    不变量：本函数**没有正文入参**，``payload_fingerprint`` 只进输出字段、
    不参与任何分支（AST 锁执法）；参数表里没有好感度（规格 §12 G-9）。
    """
    spec: ActionSpec = resolve_action(action)
    default_tier = spec.default_tier

    # 1) R3 动作天花板（含 config.write.forbidden）：不看来是谁提的。
    if config_risk.is_never_auto(default_tier):
        return Deny(
            action=spec.action,
            kind=PolicyDenyKind.NEVER_AUTO,
            detail=config_risk.describe_tier(default_tier),
            payload_fingerprint=payload_fingerprint,
        )

    # 2) 来源可信级门（外部发起才判；内部装配点没有"入站来源"可言，
    #    其风险由档位与同意账兜住——bot 永远不能自批 R1/R2）。
    if not internal_origin:
        if actor_level is None:
            return Deny(
                action=spec.action,
                kind=PolicyDenyKind.UNTRUSTED_SOURCE,
                detail="来源可信级未申报：可信级唯一派生口是 trust.py，不猜、不放行。",
                payload_fingerprint=payload_fingerprint,
            )
        if is_untrusted_data(actor_level):
            return Deny(
                action=spec.action,
                kind=PolicyDenyKind.UNTRUSTED_SOURCE,
                detail=(
                    f"发起来源在可信梯上只有 {actor_level.value}"
                    f"（序 {trust_rank(actor_level)}），外部资料与衍生物不构成动作请求。"
                ),
                payload_fingerprint=payload_fingerprint,
            )

    # 3) 角色下限 / 内部专属标记。
    floor = spec.role_floor
    if floor == ROLE_FLOOR_INTERNAL:
        if not internal_origin:
            return Deny(
                action=spec.action,
                kind=PolicyDenyKind.INTERNAL_ONLY,
                detail="该动作的角色下限登记为「内部」：只有进程内装配点可发起。",
                payload_fingerprint=payload_fingerprint,
            )
    elif floor == ROLE_FLOOR_NO_ROLE:
        return Deny(
            action=spec.action,
            kind=PolicyDenyKind.NO_ROLE_GRANTS_THIS,
            detail="该动作的角色下限登记为「无角色」：任何入站身份都不够。",
            payload_fingerprint=payload_fingerprint,
        )
    elif not internal_origin:
        if actor_roles is None:
            return Deny(
                action=spec.action,
                kind=PolicyDenyKind.ACTOR_ROLES_UNAVAILABLE,
                detail="该动作要查角色事实，但调用方没给：角色真身是 roles.py 的 resolve_roles。",
                payload_fingerprint=payload_fingerprint,
            )
        if not _roles_meet_floor(actor_roles, floor):
            return Deny(
                action=spec.action,
                kind=PolicyDenyKind.ROLE_FLOOR_NOT_MET,
                detail=f"该动作的角色下限是 {floor}（秩表唯一真身 roles.ROLE_ORDER）。",
                payload_fingerprint=payload_fingerprint,
            )

    # 4) 配置面合成（档位实算只调 config_risk 一个口）。
    landing = spec.landing_domain
    if landing is LandingDomain.CONFIG_SURFACE:
        if config_target is None:
            return Deny(
                action=spec.action,
                kind=PolicyDenyKind.CONFIG_TARGET_REQUIRED,
                detail="配置面动作必须点名目标键。",
                payload_fingerprint=payload_fingerprint,
            )
        try:
            tier = config_risk.risk_tier_for_target(config_target)
            target_name = config_risk.normalize_target(config_target)
        except (TypeError, ValueError, KeyError) as exc:
            return Deny(
                action=spec.action,
                kind=PolicyDenyKind.TARGET_UNNAMESABLE,
                detail=str(exc),
                payload_fingerprint=payload_fingerprint,
            )
        if config_risk.is_never_auto(tier):
            return Deny(
                action=spec.action,
                kind=PolicyDenyKind.NEVER_AUTO,
                detail=f"目标 {target_name} 实档 R3：只出待审补丁。",
                payload_fingerprint=payload_fingerprint,
            )
        if tier is not default_tier:
            proper = _action_for_config_tier(tier)
            proper_text = proper.value if proper is not None else "无对应动作"
            return Deny(
                action=spec.action,
                kind=PolicyDenyKind.TIER_ACTION_MISMATCH,
                detail=(
                    f"目标 {target_name} 按档位表是 {tier.value}"
                    f"（{config_risk.registry_source_for_target(target_name)}），"
                    f"该走 {proper_text}，不是 {spec.action.value}。"
                ),
                payload_fingerprint=payload_fingerprint,
            )
        consent = _consent_gate(tier, spec.action, target_name, payload_fingerprint)
        if consent is not None:
            return consent
        return Permit(
            action=spec.action,
            role_floor=floor,
            tier=tier.value,
            unattended_allowed=True,
            echo_required=True,
            rollback_required=True,
            payload_fingerprint=payload_fingerprint,
        )

    # 5) 非配置面：塞错目标直接拒；同意档要求与配置面同一判据（一个分岔，两处调用）；
    #    其余放行并落「咽喉仍须出示落点判定」旗——本件不代判路径/出站/SSRF 落点。
    if config_target is not None:
        return Deny(
            action=spec.action,
            kind=PolicyDenyKind.LANDING_TARGET_MISMATCH,
            detail=f"动作 {spec.action.value} 的落点是 {landing.value}，不接配置目标。",
            payload_fingerprint=payload_fingerprint,
        )
    consent = _consent_gate(default_tier, spec.action, "", payload_fingerprint)
    if consent is not None:
        return consent
    return Permit(
        action=spec.action,
        role_floor=floor,
        tier=default_tier.value,
        landing_check_required=landing is not LandingDomain.NONE,
        payload_fingerprint=payload_fingerprint,
    )
