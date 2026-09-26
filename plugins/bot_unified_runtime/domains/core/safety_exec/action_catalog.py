"""动作册（SAFE-EXEC 规格 §1/§2 的真身）：**一个动作只有一个裁决点**的在册表。

规格权威：``docs/design/safety-execution-engine-spec.md``

- §0 不变式①「一个动作只有一个裁决点。任何有副作用的操作必须经 ``decide()``
  拿许可凭证才能落地；绕过裁决点直接调副作用函数＝一票否决的门（§12 G-1）」。
- §1 组成表把本件职责写死为「``ActionId`` 枚举与每枚的**缺省档、角色下限、是否需要同意**
  （**声明数据，不 import 包内业务件**）」。
- §2 给出首批 **12 枚** ``ActionId`` 及其角色下限/同意档/落点域——本件逐枚照抄该表，
  不增不减不改值；要加动作必须先改规格再改本册（「一处变更处处跟随」）。
- §12 **G-2**「动作册完整性：每枚 ``ActionId`` 有档、有角色下限、有落点域；缺任一即红」。

四条设计取向（都是被本仓的失败形态逼出来的，不是审美选择）
--------------------------------------------------------------

1. **裁决点全册唯一，且不落在每枚动作身上。**
   本件刻意**没有** ``adjudication_point`` 这一**逐枚字段**——一张「动作→各自的裁决点」的表
   结构上就允许长出两个裁决点，正好破不变式①。改为模块级单枚常量
   :data:`ADJUDICATION_POINT`，由 ``tests/test_safety_exec_action_catalog.py`` 执法
   「派生出的裁决点集合大小恒为 1」。

2. **档位不另立一套，直接吃** :class:`config_risk.RiskTier`。
   规格 §1 禁止清单第一条就是「不得新增第二张权限表」。R0/R1/R2/R3 的真身已经住在
   ``config_risk.py``（含 ``describe_tier`` / ``CONSENT_REQUIRED_TIERS`` / ``DEFAULT_TIER``），
   本件再定义一份同名枚举＝制造第二真身。因此「是否需要同意」是**从 ``RiskTier`` 派生**
   的（:func:`consent_required`），不是表里再抄一列。

3. **角色下限只存名字，不存秩。**
   角色秩的唯一来源是 ``domains/chat_reply/policy/roles.py`` 的 ``ROLE_ORDER``（规格 §1
   「身份与角色：复用；角色秩唯一来源；本件不自建第二套权限表」）。本件因此
   **不含任何大小比较、不含任何秩**；一个角色名是否合法，由门在**测试侧**从
   ``ROLE_ORDER`` 现派生校验。本件也**不 import** ``roles.py``——它 ``import config`` 与
   ``contracts``，把那棵重量级依赖拖进一枚「纯声明数据」的叶子件，既违 §1 那句
   「不 import 包内业务件」，又在插件装配期白白加重导入面。本件只依赖 stdlib 与
   同包内同样 stdlib-only 的 ``config_risk``。

4. **册外动作 fail-closed，且不许用「待评审」蒙混。**
   :func:`resolve_action` 对任何未在册的动作**直接抛** :class:`UnregisteredActionError`。
   既不缺省放行，也不缺省成「需要人工评审」——后者看着安全，实际是给任意新动作开后门：
   只要没人登记，动作就自动落进一条「有人看着呢」的通道，而那条通道在登记之前
   并不存在（PDP ``policy.py`` 已于 2026-09-25 由 S-T-SAFE-3 席落地；在册 ≠ 通电：
   各 PEP 何时把副作用调用改走 ``decide()`` 属 Wave 2 接线席的账）。
   要新动作就**必须**先在册里出现。

本件是**声明数据**，不执行任何动作、不判定任何路径、不签发任何凭证：
读/写/执行根的规则唯一住 ``paths.py``，参数风险档唯一住 ``config_risk.py``，
同意凭证唯一住 ``consent.py``，裁决点唯一住 ``policy.py``（2026-09-25 落地）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final, NoReturn

from plugins.bot_unified_runtime.domains.core.safety_exec.config_risk import (
    CONSENT_REQUIRED_TIERS,
    NEVER_AUTO_TIERS,
    RiskTier,
)

# ---------------------------------------------------------------------------
# 裁决点：全册唯一
# ---------------------------------------------------------------------------

#: 不变式① 的唯一裁决点。**所有**动作共用这一枚，逐枚覆盖在结构上就不被允许。
#:
#: 该符号名按「包.模块.函数」三段指向 PDP 真身 ``domains/core/safety_exec/policy.py``
#: 的 :func:`~plugins.bot_unified_runtime.domains.core.safety_exec.policy.decide`
#: ——**2026-09-25 由 S-T-SAFE-3 席落地**
#: （此前规格 §1 该行带「拟新建」注记、在册符号指向不存在件）。
#: 「在册声明」与「PEP 已改走此口」是两本账：各副作用调用点何时接线，
#: 由 ``tests/test_safety_exec_policy.py`` 的裁决点解析锁与 Wave 2 接线席共同看住。
ADJUDICATION_POINT: Final[str] = "safety_exec.policy.decide"


def adjudication_point() -> str:
    """唯一裁决点的取数口（存在它是为了让「全册只有一枚」成为可机器判定的断言）。"""
    return ADJUDICATION_POINT


# ---------------------------------------------------------------------------
# ActionId：规格 §2 首批十二枚
# ---------------------------------------------------------------------------


class ActionId(str, Enum):
    """在册动作 id；成员与字面值逐枚对应规格 §2 表格第一列。"""

    FILE_READ = "file.read"
    FILE_WRITE = "file.write"
    FILE_SEND = "file.send"
    CODE_RUN = "code.run"
    FS_DELETE = "fs.delete"
    CONFIG_WRITE_SAFE = "config.write.safe"
    CONFIG_WRITE_RISK = "config.write.risk"
    CONFIG_WRITE_DANGER = "config.write.danger"
    CONFIG_WRITE_FORBIDDEN = "config.write.forbidden"
    NET_FETCH = "net.fetch"
    PUSH_PROACTIVE = "push.proactive"
    PEER_ACT = "peer.act"


class LandingDomain(str, Enum):
    """落点域**标签**（规格 §2 最后一列）。

    🔴 这里只有标签、**没有任何规则**。哪儿能读、哪儿能写、哪儿能跑的唯一真身是
    ``paths.py``（其 ``DOMAIN_WORKSPACE`` / ``DOMAIN_RUNTIME`` / ``DOMAIN_FORBIDDEN`` …
    是路径判定的产物，粒度与本标签列不同）。把本枚举当权限表用即属违规。
    """

    READABLE_ROOT = "readable_root"
    WRITABLE_ROOT = "writable_root"
    WRITABLE_THEN_OUTBOUND = "writable_then_outbound"
    EXECUTABLE_ROOT_ISOLATED = "executable_root_isolated"
    INSIDE_WRITABLE_ROOT = "inside_writable_root"
    CONFIG_SURFACE = "config_surface"
    VIA_SSRF_GATEWAY = "via_ssrf_gateway"
    SOLE_OUTBOUND = "sole_outbound"
    NONE = "none"


#: 角色下限取数里的两个**注册例外**——它们**不是** ``roles.ROLE_ORDER`` 的成员，
#: 含义是「外部sender角色一律够不着」，由门按常量派生放行（不是手抄名单）。
#:
#: - 规格 §2 ``config.write.forbidden`` 行的角色下限写的是「—」＝**没有**任何角色能拿到；
#: - ``push.proactive`` / ``peer.act`` 两行的角色下限写的是「内部」＝只有进程内装配点可发，
#:   不由任何入站消息的sender角色授予。
ROLE_FLOOR_NO_ROLE: Final[str] = "none"
ROLE_FLOOR_INTERNAL: Final[str] = "internal"

#: 上面两枚例外的集合（门从它派生合法集，绝不另抄一份字符串清单）。
REGISTERED_ROLE_FLOOR_EXCEPTIONS: Final[frozenset[str]] = frozenset(
    {ROLE_FLOOR_NO_ROLE, ROLE_FLOOR_INTERNAL}
)


# ---------------------------------------------------------------------------
# 声明行
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionSpec:
    """一枚动作的在册声明。

    ``default_tier`` 一字段同时兑现规格 §1 的「缺省档」与「是否需要同意」两件事：
    后者由 :func:`consent_required` 从 ``config_risk.CONSENT_REQUIRED_TIERS`` **派生**，
    表里不另立布尔列，免得长出第二份「哪一档要同意」的账。
    """

    action: ActionId
    semantics: str
    role_floor: str
    default_tier: RiskTier
    landing_domain: LandingDomain


def _spec(
    action: ActionId,
    semantics: str,
    role_floor: str,
    default_tier: RiskTier,
    landing_domain: LandingDomain,
) -> ActionSpec:
    return ActionSpec(
        action=action,
        semantics=semantics,
        role_floor=role_floor,
        default_tier=default_tier,
        landing_domain=landing_domain,
    )


#: 唯一在册表。**只能有这一份**——门（腿③）全树扫第二份「动作→裁决」形状的表。
ACTION_CATALOG: Final[Mapping[ActionId, ActionSpec]] = {
    spec.action: spec
    for spec in (
        _spec(
            ActionId.FILE_READ,
            "解析收到的文件/代码并回报理解",
            "user",
            RiskTier.R0,
            LandingDomain.READABLE_ROOT,
        ),
        _spec(
            ActionId.FILE_WRITE,
            "生成/修改文档、代码、文件",
            "trusted",
            RiskTier.R1,
            LandingDomain.WRITABLE_ROOT,
        ),
        _spec(
            ActionId.FILE_SEND,
            "把本地文件发回会话",
            "trusted",
            RiskTier.R1,
            LandingDomain.WRITABLE_THEN_OUTBOUND,
        ),
        _spec(
            ActionId.CODE_RUN,
            "执行用户提交的代码",
            "super_admin",
            RiskTier.R2,
            LandingDomain.EXECUTABLE_ROOT_ISOLATED,
        ),
        _spec(
            ActionId.FS_DELETE,
            "删除任何文件/消息",
            "super_admin",
            RiskTier.R2,
            LandingDomain.INSIDE_WRITABLE_ROOT,
        ),
        _spec(
            ActionId.CONFIG_WRITE_SAFE,
            "改 R0 参数（记审计）",
            "admin",
            RiskTier.R0,
            LandingDomain.CONFIG_SURFACE,
        ),
        _spec(
            ActionId.CONFIG_WRITE_RISK,
            "改 R1 参数（回显 diff + 一次确认）",
            "admin",
            RiskTier.R1,
            LandingDomain.CONFIG_SURFACE,
        ),
        _spec(
            ActionId.CONFIG_WRITE_DANGER,
            "改 R2 参数（书面同意）",
            "super_admin",
            RiskTier.R2,
            LandingDomain.CONFIG_SURFACE,
        ),
        _spec(
            ActionId.CONFIG_WRITE_FORBIDDEN,
            "R3 参数：永不自动，只出待审补丁",
            ROLE_FLOOR_NO_ROLE,
            RiskTier.R3,
            LandingDomain.NONE,
        ),
        _spec(
            ActionId.NET_FETCH,
            "主动抓外部 URL",
            "trusted",
            RiskTier.R0,
            LandingDomain.VIA_SSRF_GATEWAY,
        ),
        _spec(
            ActionId.PUSH_PROACTIVE,
            "主动投递（回执/告警/订阅），含目标域门",
            ROLE_FLOOR_INTERNAL,
            RiskTier.R1,
            LandingDomain.SOLE_OUTBOUND,
        ),
        _spec(
            ActionId.PEER_ACT,
            "对第三人动作（@、戳、贴表情），群内优先",
            ROLE_FLOOR_INTERNAL,
            RiskTier.R0,
            LandingDomain.NONE,
        ),
    )
}


# ---------------------------------------------------------------------------
# 取数口
# ---------------------------------------------------------------------------


class UnregisteredActionError(LookupError):
    """册外动作。fail-closed：拿不到声明，就不许进入任何副作用路径。"""

    def __init__(self, raw: object) -> None:
        self.raw_action = raw
        super().__init__(
            f"动作 {raw!r} 未在动作册登记：册外动作一律拒绝，"
            f"不得缺省放行、也不得缺省转人工评审。"
            f"要新增请先改规格 §2 再改 ACTION_CATALOG。"
        )


def registered_actions() -> frozenset[ActionId]:
    """在册动作全集（供门与审计派生，不供调用方自行判定放行）。"""
    return frozenset(ACTION_CATALOG)


def is_registered(raw: object) -> bool:
    """``raw`` 是否在册。**注意**：本函数只回答「在不在册」，
    返回 ``True`` **不构成许可**——许可只出自 :data:`ADJUDICATION_POINT`。"""
    try:
        key = ActionId(raw)
    except ValueError:
        return False
    return key in ACTION_CATALOG


def resolve_action(raw: object) -> ActionSpec:
    """按动作 id 取声明；**册外一律抛** :class:`UnregisteredActionError`。

    这是本册对不变式① 的 fail-closed 兑现点：调用方拿不到声明就拿不到裁决输入，
    因此「忘了登记」的表现形式是**当场炸**，不是静悄悄按最低风险档跑掉。
    """
    try:
        key = ActionId(raw)
    except ValueError as exc:
        raise UnregisteredActionError(raw) from exc
    spec = ACTION_CATALOG.get(key)
    if spec is None:
        # 枚举成员却无声明行＝册内部自相矛盾，同样 fail-closed，不兜底成 needs_review。
        raise UnregisteredActionError(raw)
    return spec


def consent_required(raw: object) -> bool:
    """该动作是否需要同意凭证——**派生自** ``config_risk.CONSENT_REQUIRED_TIERS``。

    本册不持有「哪几档要同意」的第二份账；档位语义唯一住 ``config_risk.py``。
    册外动作在这里同样炸，不给「未知动作→不需要同意」留缝。
    """
    return resolve_action(raw).default_tier in CONSENT_REQUIRED_TIERS


def is_never_auto(raw: object) -> bool:
    """该动作是否属于「永不自动、只出待审补丁」档（派生自 ``config_risk.NEVER_AUTO_TIERS``）。"""
    return resolve_action(raw).default_tier in NEVER_AUTO_TIERS


# ---------------------------------------------------------------------------
# 危险操作话术形态 → 已裁决动作（供攻击面登记表归因，不改裁决点）
# ---------------------------------------------------------------------------

#: 「诱导 bot 做规则 11 禁执行面」的话术形态 → 该形态**归并到哪枚已裁决动作**。
#:
#: 为什么放这里而不是新建 ``ActionId``：规格 §2 首批十二枚是**不增不减**的锁
#: （``test_leg1_catalog_membership_matches_spec_2_exactly`` + 规格 §2 原文），
#: 而 restart/kill/git/install/delete 这几类话术在动作语义上并不**新**——它们是
#: 「让 bot 去执行一个操作 / 删一个东西」，正好归并到既有的 ``CODE_RUN``（超级管理员、
#: R2 需书面同意）与 ``FS_DELETE``（超级管理员、R2）。归并到既有动作＝复用既有那一道
#: 同意与角色门，绝不长出第二套权限表。若将来要把「进程控制」「VCS 写」升成**独立裁决
#: 动作**，那属于「先改规格 §2 再改本册 + 同步那枚十二枚锁」的裁定项（交主代理，非本册自决）。
#:
#: 🔴 本表**不含任何档位/许可值**：值只指到 ``ActionId`` 成员（许可仍只出自
#: :data:`ADJUDICATION_POINT`）。把「归因」写成「放行」即违不变式①，故值用枚举成员引用、
#: 键用形态标签串（非动作 id 字面值），本表在结构上不是「动作→裁决」第二真身
#: （门 :func:`_module_level_dict_literals` 只数以动作 id 字面值为键的表，本表键不属之）。
OPERATIONAL_FORM_TO_ACTION: Final[Mapping[str, ActionId]] = {
    "restart_process": ActionId.CODE_RUN,
    "kill_process": ActionId.CODE_RUN,
    "git_write": ActionId.CODE_RUN,
    "package_install": ActionId.CODE_RUN,
    "delete_outside": ActionId.FS_DELETE,
}


def action_for_operational_form(form: object) -> ActionId | None:
    """形态标签 → 归并动作；未映射返回 ``None``（**不崩**，供检测侧安全取用）。

    「检出的每种形态都必须在册映射」这一件事由锁
    ``tests/test_safety_exec_attack_surface.py`` 执法（把 :data:`OPERATIONAL_FORM_TO_ACTION`
    与攻击面登记表 `TAKEOVER_FORM_ORDER` 现算比对）——归因表若漏一枚形态即红，
    而不是靠运行期 None 蒙混。
    """
    if not isinstance(form, str):
        return None
    return OPERATIONAL_FORM_TO_ACTION.get(form)


def registered_operational_forms() -> frozenset[str]:
    """已归因的话术形态全集（供门派生比对，不供调用方自行放行）。"""
    return frozenset(OPERATIONAL_FORM_TO_ACTION)


def plain_text_for_deny(raw: object) -> NoReturn:
    """刻意**不提供**拒绝话术：话术真身住 ``consent.py`` / ``paths.py`` 的
    ``plain_text_for`` / ``REASON_PLAIN_TEXT``。本函数存在只为把这条禁令钉成
    「调了就炸」，防将来在动作册里长出第二套拒绝话术池（规格 §1 禁止清单）。
    """
    raise RuntimeError(
        "动作册不出拒绝话术：话术唯一真身是 consent.py 的 plain_text_for "
        f"与 paths.py 的 REASON_PLAIN_TEXT（此处传入 {raw!r} 仅为触发本禁令）"
    )
