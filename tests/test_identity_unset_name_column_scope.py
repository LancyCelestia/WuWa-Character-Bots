"""/bot identity unset-name 的**列作用域**锁（F-8 裁定甲＝按列清，2026-10-05 用户亲裁）
＋ 回执读点的**平台接线**锁（席 idplat，2026-10-06）。

起因（席 rowwipe 勘察 + 席 receiptorder 只修了说谎腿）：
`addressing_preferences` 的主键是 `(session_type, session_id, sender_id)`，QQ 私聊里
"那个人的称谓行"与"那个人的亲密档标记行"**天生同一行**（裸 uid 撞键形）。旧命令面走
`store.clear()`＝整条 DELETE ⇒ 一条"取消称呼"顺手把她亲手钉的 `intimate_pin_*` 两列与
`narration_*` 两列一起收回（描写档**没有 TTL**，本该活到本人 reset）。

接线债（本波补，2026-10-06）：描写钉自本波起落在**三段键** (平台域, 会话, 这个人) 上，
人段形如 `qq:<uid>`（真身＝`runtime/content_route._narration_person_key` →
`domains/core/session_keys.person_scope_key`，平台写法只归一自
`policy/roles.platform_domain_of`），而 unset-name 那一轮的读点按**裸 uid** 查 ⇒
**永远读空、永远说不出"描写档保住了"**（上一席位实跑取证的现文就是那一句谎）。缺口三处
**同批**补，缺一即半成品：

1. 根 `__init__.py` 的 identity 分支 ⇒ 交平台事实（形状照旁边 intimate／narration 两支，
   不造新机制）；
2. `domains/ops/admin/runtime_admin.py` 的自助拦截 ⇒ 原样转发 `session_key`／`platform`／
   `conversation_type`（这一层只转述，一律不猜、不补值）；
3. `domains/chat_reply/capabilities/echo.py` 的回执读点 ⇒ 改走唯一取钉口
   `content_route.read_narration_pin`（禁在 echo 里再拼一份键形）。

🔴 值只准出自契约字段 `IncomingMessage.platform`（台账 #60★／T-1：绝不反解会话键去猜
平台）；硬写成 `"qq"`＝把命令面钉死在一个平台上，写进去的键与读出来的键从此永不相交。
🔴 平台事实**缺席**时这一格只准说"说不准"——把谎从"读不到"挪到"读得到"不算修好。

本文件钉正面四枚 + 接线两枚 + 会话齿一枚 + fail-closed 一枚 + 形状锁三枚 + 反向锁两枚：

- ① unset-name 之后 `intimate_pin_tier`／`intimate_explicit_at` 逐字照在；
- ② unset-name 之后 `narration_mode`／`narration_updated_at` 逐字照在（连 `relationship`
  与 `gender_identity` 也不许被牵连，一并钉在同一枚里）；
- ③ `addressing_preference` 那一列**确实**清了（否则＝整件事什么都没做）；
- ④ 回执点名"清了哪一列"与"保住了哪几列"，且**不**再宣称整条记录移除、**不**回显列值；
- ⑤ 样本按**生产真写的行形**造（键形现算自中央件，并由轴心写腿/读腿双向对齐自证），
  回执必须点名描写档未被牵连；链上第 2 处（管理员入口转发）也要走得通；
- ⑥ 会话齿（I-2）：群里那一轮读的是群里那一格，不许把私聊那枚钉算进来（反向亦然）；
- ⑦ fail-closed：平台事实缺席 ⇒ 回执不许宣称"描写档保住了"，也不许把这一格算进
  "谁也没被牵连"；
- ⑧ **亲密档齿**（席 unmask-intimate，2026-10-06）：D-1 标记的写腿落
  `_explicit_pin_person_key(session_key)`（QQ 私聊＝裸 uid、TG 私聊＝`private_<chat.id>`），
  而回执那一格**今天仍按裸 uid 查** ⇒ TG 侧两形永不相交、"亲密档保住了"说不准。
  本波补轴心侧唯一公开读口 `content_route.read_intimate_pin`（取键只经写腿那一把、
  fail-closed、不猜平台），echo 只转述它。这一族四枚：三向对齐一枚（轴心写腿→轴心读口→
  裸 uid 恒空）、事实缺一枚即"说不准"两枚（platform／session_key）、摘守卫变异一枚；
  再加两侧形状锁各一枚＋注毒三腿（只接 echo／读口换成描写的尺／`platform` 硬编 `"qq"`
  ／守卫摘 `platform` 那一枚）；
- 形状锁：根派发与管理员转发逐处交平台事实、值只准转述契约字段；回执读点只有一处取钉口；
- 锁 A：命令面结构上碰不到 `store.clear()`（整行 DELETE 那支口在自助面零消费者）；
- 锁 B（注毒）：把按列清那一口**替换回**整行 DELETE，①②③④ 的正面断言当场全红——
  证明这四枚不是摆设；
- 锁 C（变异）：摘掉 ⑦ 的 fail-closed 腿（恒去读）⇒ ⑦ 的两条判据当场失效。

夹具铁律（AGENTS 规则 6/7、台账 #66★、#76★）：
- 走偏好命令面的用例一律 `monkeypatch` 装配口，称谓库与 `shared_reply_policy_store`
  都指 tmp ⇒ 绝不写她生产库；取钉口还会先问 `bot_addressing_preferences_db_path` 点没点名
  落点（`config.resolve_runtime_data_field`），所以配置面那枚值也必须是**仓库外**绝对路径；
- 键形一律现算自中央件（`person_scope_key`／`build_session_key`／`parse_session_key`，成员
  派生键先 `content_route.split_member_session_key` 拆基键），测试不自拼第四形；
- `--basetemp` 在仓库外、且不在 `ChatBot_Runtime` 之下（否则媒体读根名册造假红）。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import (
    echo as echo_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    HELP_ENTRIES,
    build_identity_preference_result,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    providers as providers_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    reply_policy as rp_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
    AddressingPreferenceStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
    ReplyPolicyStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    platform_domain_of,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import content_route as cr
from plugins.bot_unified_runtime.domains.core.session_keys import (
    KIND_GROUP,
    build_session_key,
    parse_session_key,
    person_scope_key,
)

_ROOT = Path(__file__).resolve().parents[1]
_INIT_SRC = _ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
_ADMIN_SRC = (
    _ROOT / "plugins" / "bot_unified_runtime" / "domains" / "ops" / "admin" / "runtime_admin.py"
)
_ECHO_SRC = (
    _ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "capabilities"
    / "echo.py"
)
#: 标记读口的真身处（席 unmask-intimate 的形状锁要判"两侧都接"，故两侧源码各取一份）。
_CR_SRC = (
    _ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "runtime"
    / "content_route.py"
)

#: 该人行上五格的"原样"读数（注毒退回整行删时，这些值会一起变缺省）。
_TIER = "l1"
_TIER_STAMP = 1767000000.5
_MODE = "scene"
_MODE_STAMP = 1767000001.25
_RELATION = "lover"
_GENDER = "female"
_NAME = "岸宝"

#: 合成号与合成群号（纪律同 `tests/test_narration_platform_wiring.py`：号全用合成值）。
_UID = "u1"
_PLATFORM = "qq"
#: QQ 私聊会话键＝裸号（中央件 `FORM_BARE`，与摄取层 `event.get_session_id()` 逐字同形）。
_PRIVATE_KEY = _UID
_GROUP = "g1"
#: 群会话键**只准**出自中央件构造口（逐字镜像 OneBot V11，禁自拼第四形）。
_GROUP_KEY = build_session_key(_GROUP, _UID)
#: 描写钉的**人段**（现算自中央件；席 idplat 的债就埋在"这枚与裸号不相等"上）。
_PERSON_KEY = person_scope_key(platform_domain_of(_PLATFORM), _UID)

#: TG 侧样本（席 unmask-intimate 这一族）：号一律合成值，且**与 QQ 那个号同号**——
#: 跨平台同号正是这一族的要害（`session_keys.person_scope_key` 的病根那句就写在这里）。
_TG_CHAT = "7770002299"
_TG_PLATFORM = "telegram"
#: TG 私聊会话键真形＝`private_<chat.id>`（`domains/core/session_keys` docstring 第 1 条，
#: 口径同 `tests/test_narration_platform_wiring.py:84`）；QQ 私聊则是裸 `<uid>`。
#: 亲密档标记的**写腿**取的就是这把会话键本身（`content_route._explicit_pin_person_key`），
#: 所以这两形在生产里**真的**同时存在、且永不相交。
_TG_PRIVATE_KEY = f"private_{_TG_CHAT}"

#: 回执里"保住的那几格"那一段的行文锚（真身＝echo 的那句，测试只判点名，不抄文案）。
_KEPT_MARKER = "原样保住的还有"
#: 说不准那一格的语义锚（不依赖具体字面，避免"常量改名＝测试红"这种假绿/假红）。
_UNCERTAIN_WORD = "说不准"
#: 两格"说不准"那一行的**真身字面**（从 echo 取常量，测试不抄第二份文案）：整行被摘＝红，
#: 改个措辞不算红。亲密档那一行是席 unmask-intimate 这一族补的第二条 fail-closed 投递。
_UNCERTAIN_LINES = {
    "描写档": echo_module._IDENTITY_NARRATION_UNCERTAIN_LINE,
    "亲密档": echo_module._IDENTITY_INTIMATE_UNCERTAIN_LINE,
}


class _Config:
    """取钉口先问这枚字段点没点名落点（`resolve_runtime_data_field`）⇒ 值必须是**仓库外**绝对路径。"""

    def __init__(self, db_path: str) -> None:
        self.bot_addressing_preferences_db_path = db_path


@dataclass
class _Harness:
    store: AddressingPreferenceStore
    config: _Config


@pytest.fixture(autouse=True)
def _reply_policy_points_at_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ReplyPolicyStore:
    """台账 #66★：偏好命令面的用例先把回复策略 store 结构性指 tmp（生产库零写）。"""
    policy_store = ReplyPolicyStore(tmp_path / "reply_policy.sqlite3")
    monkeypatch.setattr(
        rp_module, "shared_reply_policy_store", lambda _config: policy_store
    )
    return policy_store


@pytest.fixture()
def h(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Harness:
    db_path = tmp_path / "addressing_preferences.sqlite3"
    real = AddressingPreferenceStore(db_path)
    monkeypatch.setattr(
        providers_module, "build_addressing_preference_store", lambda _config: real
    )
    return _Harness(store=real, config=_Config(str(db_path)))


# --------------------------------------------------------------------------
# 键形与落点（只经中央件／轴口，测试不自拼第四形）
# --------------------------------------------------------------------------


def _base_key(session_key: str) -> str:
    """成员派生键先拆基键（轴心在用的同一枚逆口），其余形态原样。"""
    split = cr.split_member_session_key(session_key)
    return split[0] if split is not None else session_key


def _narration_cell(session_key: str) -> tuple[str, str, str]:
    """描写钉那一格的三元组：会话段现算自 `parse_session_key`、人段现算自 `person_scope_key`。

    私聊那一格＝轴心 fail-closed 的兜底落点（取真身常量，不抄字面）；群＝群号那一格（I-2
    的会话齿）。认形只准用中央件，禁在测试里再拼一份键形。
    """
    parsed = parse_session_key(_base_key(session_key))
    if parsed.kind == KIND_GROUP and parsed.group_id:
        return "group", parsed.group_id, _PERSON_KEY
    return cr._EXPLICIT_PIN_SESSION_TYPE, cr._EXPLICIT_PIN_SESSION_ID, _PERSON_KEY


def _conversation_type(session_key: str) -> str:
    return "group" if _narration_cell(session_key)[0] == "group" else "private"


def _seed_narration_row(
    h: _Harness, session_key: str = _PRIVATE_KEY, *, mode: str = _MODE, updated_at: float = _MODE_STAMP
) -> None:
    """按**生产真写的行形**落一枚钉（键形＝`_narration_cell` 现算自中央件）。"""
    session_type, session_id, person = _narration_cell(session_key)
    h.store.set_narration_pin(
        session_type=session_type,
        session_id=session_id,
        sender_id=person,
        mode=mode,
        updated_at=updated_at,
    )


def _pin_narration_via_the_axis(h: _Harness, session_key: str) -> None:
    """经**生产写腿**（`content_route.write_narration_pin`）落同一枚钉——本件的手搓行形必须与它同格。"""
    assert cr.write_narration_pin(
        session_key,
        mode=_MODE,
        sender_id=_UID,
        config=h.config,
        platform=_PLATFORM,
        conversation_type=_conversation_type(session_key),
    ) is True, "描写钉没写进去＝下面的断言全在空跑"


def _seed_the_whole_row(h: _Harness) -> None:
    """把「那个人那一行」五格全部钉上：称谓＋性别自述＋关系档＋亲密档标记＋描写档钉。

    私聊裸 uid（`("private", "", "u1")`）＝席 rowwipe 第 1 节认定的**撞键形那一支**，
    所以危害最重的形状就在这里造。描写钉**不再**按裸 uid 造样本（那形生产早已不写）：
    它按三段键 (平台域, 会话, 人) 落库：行形现算自中央件，并与轴心写腿/读腿双向对齐自证
    （见 `test_the_sample_is_the_row_shape_production_actually_writes`）。
    """
    key = {"session_type": "private", "session_id": "", "sender_id": _UID}
    h.store.set(**key, addressing_preference=_NAME, gender_identity=_GENDER)  # type: ignore[arg-type]
    h.store.set_relationship(**key, relationship=_RELATION)  # type: ignore[arg-type]
    h.store.set_intimate_pin(**key, tier=_TIER, explicit_at=_TIER_STAMP)  # type: ignore[arg-type]
    _seed_narration_row(h)


def _seed_only_the_name_and_the_pin(h: _Harness) -> None:
    """最小对照样本：这一行只有称谓那一列＋三段键上的一枚描写钉，其余格子都空着。

    fail-closed 那两枚判据必须拿它跑：`kept` 为空时，摘腿后的回执会把这一格直接算进
    "谁也没被牵连"那一句＝把谎从"读不到"挪到"读得到"；四格俱全的正面样本看不见这一格。
    """
    h.store.set(
        session_type="private", session_id="", sender_id=_UID, addressing_preference=_NAME
    )  # type: ignore[arg-type]
    _seed_narration_row(h)


def _intimate(h: _Harness, *, group_id: str = "") -> tuple[str, float]:
    return h.store.get_intimate_pin(
        session_type="group" if group_id else "private", session_id=group_id, sender_id=_UID
    )


def _narration(h: _Harness, session_key: str = _PRIVATE_KEY) -> tuple[str, float]:
    session_type, session_id, person = _narration_cell(session_key)
    return h.store.get_narration_pin(
        session_type=session_type, session_id=session_id, sender_id=person
    )


def _bare_uid_narration(h: _Harness) -> tuple[str, float]:
    """旧读点那一格（裸 uid）：生产写腿不该再往这里落钉；落了就说明本件判的行形是旧的。"""
    return h.store.get_narration_pin(
        session_type=cr._EXPLICIT_PIN_SESSION_TYPE,
        session_id=cr._EXPLICIT_PIN_SESSION_ID,
        sender_id=_UID,
    )


def _marker_person_key(h: _Harness, session_key: str) -> str:
    """亲密档**标记**的本人段（现算自轴心写腿那一口，本件不拼第二形）。"""
    return cr._explicit_pin_person_key(session_key, h.config)


def _marker_cell(h: _Harness, session_key: str) -> tuple[str, float]:
    """按轴心键形读这一格（前提锁用：证明样本落在生产真写的那一格上）。"""
    return h.store.get_intimate_pin(
        session_type=cr._EXPLICIT_PIN_SESSION_TYPE,
        session_id=cr._EXPLICIT_PIN_SESSION_ID,
        sender_id=_marker_person_key(h, session_key),
    )


def _open_intimate_via_the_axis(h: _Harness, session_key: str, *, tier: str = _TIER) -> None:
    """经**生产写腿**落一枚亲密档标记（D-1：`ContentRouteEngine.apply_manual` 的 manual 腿）。

    🔴 不许手搓行形：标记的键形只有这一条产路（`_explicit_pin_person_key` 私聊键门＋并号），
    手搓＝本件判的行形可能是生产根本不写的形状（假绿，失效形态 247 同族）。
    """
    engine = cr.ContentRouteEngine()
    assert engine.apply_manual(
        session_key,
        cr.MODE_INTIMATE,
        h.config,
        source=cr.INTIMATE_SOURCE_MANUAL,
        tier=tier,
    ) is True, "亲密档标记没落库＝下面的断言全在空跑"


def _run(
    h: _Harness,
    text: str,
    *,
    group_id: str = "",
    platform: str = _PLATFORM,
    session_key: str = _PRIVATE_KEY,
    conversation_type: str = "private",
    sender_id: str = _UID,
) -> Any:
    """回执直调（接线后的第 3 处入口）；平台事实默认在场＝生产接线后的形状。"""
    return build_identity_preference_result(
        h.config,
        request_id="req-f8-column-scope",
        sender_id=sender_id,
        group_id=group_id,
        command_text=text,
        session_key=session_key,
        platform=platform,
        conversation_type=conversation_type,
    )


def _run_group(h: _Harness, text: str) -> Any:
    """群里那一轮：会话键现算自中央件、会话事实交契约字段的规范值（与根派发同源）。"""
    return _run(h, text, group_id=_GROUP, session_key=_GROUP_KEY, conversation_type="group")


def _kept_enumeration(body: str) -> str:
    """回执里"保住的那几格"那一段（截到句号）；没有这一段就回空串（说不准那一格不算点名保住）。"""
    if _KEPT_MARKER not in body:
        return ""
    return body.split(_KEPT_MARKER, 1)[1].split("。", 1)[0]


def _positive_locks(h: _Harness) -> list[bool]:
    """①②③④ 四枚正面判据（逐枚返回值，供注毒席对照"恰有某枚变红"）。"""
    key = {"session_type": "private", "session_id": "", "sender_id": _UID}
    preference, gender = h.store.get(**key)  # type: ignore[arg-type]
    body = _run(h, "unset-name", group_id="").body
    return [
        _intimate(h) == (_TIER, _TIER_STAMP),  # ①
        _narration(h) == (_MODE, _MODE_STAMP)  # ②
        and h.store.get_relationship(**key) == _RELATION,  # type: ignore[arg-type]
        preference == "" and gender == _GENDER,  # ③
        "已清除" in body  # ④
        and "保住" in body
        and "整条记录" not in body
        and all(label in body for label in ("性别自述", "关系档", "亲密档", "描写档"))
        and all(value not in body for value in (_NAME, _GENDER, _RELATION, _TIER, _MODE)),
    ]


def _fail_closed_predicates(body: str, label: str = "描写档") -> list[bool]:
    """某一格的四条判据：这一格必须**明说不准**、不许被列进保住的那几格、不许被算进
    "谁也没被牵连"那一句，且这个词还得出现（整格静吃也是谎）。

    第①条按**那一格自己的真身字面**判（从 echo 取常量、测试不抄第二份文案）：两格都说
    "说不准"时，别格那一行不能替这一格作证——摘掉一条腿必须只让那一格的判据塌下去。
    """
    return [
        _UNCERTAIN_LINES[label] in body,
        label not in _kept_enumeration(body),
        "谁也没被牵连" not in body,
        label in body,
    ]


# --------------------------------------------------------------------------
# 前提锁：样本造的必须是生产真写的那一行形
# --------------------------------------------------------------------------


def test_the_sample_is_the_row_shape_production_actually_writes(h: _Harness) -> None:
    """键形换了形：钉落在 `qq:<uid>` 那一格，**裸 uid 那一格是空的**（旧样本造的正是空的这格）。

    三向对齐（本件后面所有"回执点名描写档"的断言都靠它，不然全在空跑）：
    ①本件手搓的行形＝轴心**读腿**看得见的那一格；
    ②轴心**写腿**落库后也落在同一格；
    ③裸 uid 那一格始终为空＝生产不再写它。
    """
    assert _PERSON_KEY != _UID, "平台域折回了裸号＝样本没换形，本件的判据会在空跑"
    _seed_narration_row(h)
    assert _narration(h) == (_MODE, _MODE_STAMP)
    assert cr.read_narration_pin(
        _PRIVATE_KEY,
        sender_id=_UID,
        config=h.config,
        platform=_PLATFORM,
        conversation_type="private",
    ) == _MODE, "本件造的行形轴心读腿看不见＝测试在判一个生产不写的形状"
    assert _bare_uid_narration(h) == ("", 0.0), "裸 uid 那一格被写了＝本件造的是旧行形"

    _pin_narration_via_the_axis(h, _GROUP_KEY)
    assert _narration(h, _GROUP_KEY)[0] == _MODE, (
        f"轴心写腿没落在本件现算的群格 {_narration_cell(_GROUP_KEY)} 上＝键形有两把尺"
    )


# --------------------------------------------------------------------------
# 正面四枚（先让 unset-name 只清自己那一列）
# --------------------------------------------------------------------------


def test_unset_name_leaves_the_intimate_pin_columns_untouched(h: _Harness) -> None:
    """①：亲密档标记两列（档位＋墙钟时刻）逐字照在。"""
    _seed_the_whole_row(h)
    _run(h, "unset-name", group_id="")
    assert _intimate(h) == (_TIER, _TIER_STAMP)


def test_unset_name_leaves_the_narration_pin_and_neighbours_untouched(h: _Harness) -> None:
    """②：描写档两列＋关系档＋性别自述都不是这条指令说过的话。"""
    _seed_the_whole_row(h)
    _run(h, "unset-name", group_id="")
    assert _narration(h) == (_MODE, _MODE_STAMP)
    assert h.store.get_relationship(
        session_type="private", session_id="", sender_id=_UID
    ) == _RELATION
    assert h.store.get(session_type="private", session_id="", sender_id=_UID) == ("", _GENDER)


def test_unset_name_really_clears_the_name_column(h: _Harness) -> None:
    """③：名字那一列确实清了（一枚"什么都不做"的实现过不了这一枚）。"""
    _seed_the_whole_row(h)
    _run(h, "unset-name", group_id="")
    preference, _gender = h.store.get(session_type="private", session_id="", sender_id=_UID)
    assert preference == ""


def test_unset_name_receipt_names_the_cleared_and_the_kept_columns(h: _Harness) -> None:
    """④：回执点清了哪一列、保了哪几列；旧"整条记录移除"那句不许再出现，列值不外流。"""
    _seed_the_whole_row(h)
    body = _run(h, "unset-name", group_id="").body
    assert "已清除" in body and "称谓偏好" in body
    assert "保住" in body
    for label in ("性别自述", "关系档", "亲密档", "描写档"):
        assert label in body, label
    assert "整条记录" not in body
    for value in (_NAME, _GENDER, _RELATION, _TIER, _MODE):
        assert value not in body, value
    assert _UNCERTAIN_WORD not in body, "平台事实在场却说不准＝取钉口没接上"


def test_unset_gender_leaves_the_name_and_both_pin_columns_untouched(h: _Harness) -> None:
    """同一条按列清腿的另一支：unset-gender 只清性别自述那一列。

    裁定甲改的是 `docs/db-owners.md` 那句成文语义「清理＝按行删」，而这一支与
    unset-name **共用同一条尾巴**（席 rowwipe 第 3 节）⇒ 不改它，同一场销毁照旧成立。
    """
    _seed_the_whole_row(h)
    _run(h, "unset-gender", group_id="")
    preference, gender = h.store.get(session_type="private", session_id="", sender_id=_UID)
    assert preference == _NAME
    assert gender == "unknown"
    assert _intimate(h) == (_TIER, _TIER_STAMP)
    assert _narration(h) == (_MODE, _MODE_STAMP)
    assert h.store.get_relationship(
        session_type="private", session_id="", sender_id=_UID
    ) == _RELATION


def test_group_scope_unset_name_does_not_disturb_the_private_row(h: _Harness) -> None:
    """作用域键不许被顺手加宽：群里的 unset-name 只动群里那一行。"""
    _seed_the_whole_row(h)
    key = {"session_type": "group", "session_id": _GROUP, "sender_id": _UID}
    h.store.set(**key, addressing_preference=_NAME)  # type: ignore[arg-type]
    _run_group(h, "unset-name")
    assert h.store.get(**key) == ("", "unknown")  # type: ignore[arg-type]
    assert h.store.get(session_type="private", session_id="", sender_id=_UID) == (
        _NAME,
        _GENDER,
    )


# --------------------------------------------------------------------------
# ⑤：接线（三处同批才走得通）
# --------------------------------------------------------------------------


def test_unset_name_receipt_names_the_platform_scoped_narration_pin(h: _Harness) -> None:
    """⑤：回执必须把描写档列进"保住的那几格"——只有按三段键读才说得出这一句。

    判据分两半：钉**确实**在库里（三段键那一格）、回执**确实**把它点名成保住的。
    """
    _seed_the_whole_row(h)
    assert _narration(h) == (_MODE, _MODE_STAMP), "前提：钉在库里"
    body = _run(h, "unset-name", group_id="").body
    assert "描写档" in _kept_enumeration(body), body
    assert _UNCERTAIN_WORD not in body, body


# --------------------------------------------------------------------------
# ⑤续二（席 unmask-intimate，2026-10-06）：亲密档那一格**还按裸 uid 读**
# --------------------------------------------------------------------------


def test_unset_name_receipt_names_the_intimate_marker_pinned_on_a_tg_private_key(
    h: _Harness,
) -> None:
    """TG 私聊里亲手开过亲密档 ⇒ unset-name 的回执必须点名"亲密档保住了"。

    现算两形（RED 的失败原文就交这两串，别只看注释）：
    - **写腿**（D-1 唯一产路 `apply_manual` → `_explicit_pin_person_key`）落在
      `private_<chat.id>`＝TG 摄取层交给它的那把会话键本身；
    - **读点**（echo 旧形）按裸 `<uid>` 查 ⇒ 两形**永不相交**（#33★／T-1 那一族：
      写在 A 形、读在 B 形，回执永远说不出实话）。
    QQ 私聊两形恰好同枚（裸 uid），所以 ①④⑤ 那几枚正面锁看不见这一格。
    """
    key = {"session_type": "private", "session_id": "", "sender_id": _TG_CHAT}
    h.store.set(**key, addressing_preference=_NAME, gender_identity=_GENDER)  # type: ignore[arg-type]
    _open_intimate_via_the_axis(h, _TG_PRIVATE_KEY)

    axis_key = _marker_person_key(h, _TG_PRIVATE_KEY)
    assert _marker_cell(h, _TG_PRIVATE_KEY)[0] == _TIER, "前提：轴心写腿没落库＝下面全在空跑"
    assert axis_key != _TG_CHAT, (
        f"两形折回同一枚（{axis_key!r}）＝标记的键形已被改判，本件的坐标要同步"
    )
    assert h.store.get_intimate_pin(**key) == ("", 0.0), (  # type: ignore[arg-type]
        "裸 uid 那一格被写了＝生产写腿换了形，旧读点不再是残留"
    )

    body = _run(
        h,
        "unset-name",
        group_id="",
        platform=_TG_PLATFORM,
        session_key=_TG_PRIVATE_KEY,
        conversation_type="private",
        sender_id=_TG_CHAT,
    ).body
    assert _marker_cell(h, _TG_PRIVATE_KEY)[0] == _TIER, "回执跑完，标记仍须在盘上（没收了就是毁）"
    assert "亲密档" in _kept_enumeration(body), (
        f"回执点不出亲密档＝读点还按裸 uid 查（写在 {axis_key!r}、读在 {_TG_CHAT!r}）：{body}"
    )
    assert _UNCERTAIN_WORD not in body, f"平台与会话事实都在场却说不准＝读点没接上：{body}"


# --------------------------------------------------------------------------
# ⑧：亲密档标记齿的三向对齐（样本必须是生产真写的那一格）＋ fail-closed ＋ 摘腿变异
# --------------------------------------------------------------------------


def test_the_intimate_marker_sample_is_the_cell_production_actually_writes(h: _Harness) -> None:
    """⑧前提锁：标记落在 `private_<chat.id>` 那一格，**被清的这一行**与裸 uid 那格都是空的。

    三向对齐（缺任何一向，下面的回执断言就在空跑）：
    ①轴心写腿（`apply_manual` 的 manual 腿）落库 → ②轴心读口 `read_intimate_pin` 看得见同一格
    → ③旧读点那把裸 uid 恒空（＝生产不往那里写，回执按它查永远说不出实话）。
    """
    _open_intimate_via_the_axis(h, _TG_PRIVATE_KEY)
    axis_key = _marker_person_key(h, _TG_PRIVATE_KEY)
    assert axis_key == _TG_PRIVATE_KEY, f"轴心取键口没交回会话键本身（{axis_key!r}）＝键形被改判"
    tier, explicit_at = _marker_cell(h, _TG_PRIVATE_KEY)
    assert tier == _TIER and explicit_at > 0.0, f"轴心写腿没把档位与墙钟落齐：{(tier, explicit_at)}"
    assert cr.read_intimate_pin(_TG_PRIVATE_KEY, config=h.config) == _TIER, (
        "轴心写腿落的格子，轴心读口看不见＝读写两把尺（#33★／T-1 那族）"
    )
    assert cr.read_intimate_pin(_TG_CHAT, config=h.config) == "", (
        "裸 uid 那一格读得出标记＝两形折回同一枚，本件的样本不再生效"
    )
    # 群侧与成员派生键按 D-1 边界**不入库**：读它们一律空串，回执据此不许替人作保。
    assert cr.read_intimate_pin(_GROUP_KEY, config=h.config) == ""
    assert cr.read_intimate_pin("", config=h.config) == ""


@pytest.mark.parametrize("missing", ["platform", "session_key"])
def test_unset_name_with_a_missing_fact_never_vouches_for_the_intimate_marker_cell(
    h: _Harness, missing: str
) -> None:
    """⑧：事实缺一枚 ⇒ 亲密档那一格只准说"说不准"，不许说"保住了"、更不许算进"谁也没被牵连"。

    样本＝TG 那一支：标记只在 `private_<chat.id>` 那一格，被清的这一行自己**没有**亲密档列
    （`tests/test_identity_preference_commands.py` 里那一支是"标记就住被清的这一行"，
    那一格直读同一行的列、不需要平台事实，两型各有各的实话）。
    """
    h.store.set(
        session_type="private", session_id="", sender_id=_TG_CHAT, addressing_preference=_NAME
    )  # type: ignore[arg-type]
    _open_intimate_via_the_axis(h, _TG_PRIVATE_KEY)
    assert _marker_cell(h, _TG_PRIVATE_KEY)[0] == _TIER, "前提：标记在轴心那一格"

    kwargs: dict[str, Any] = {"group_id": "", "sender_id": _TG_CHAT}
    if missing == "platform":
        kwargs.update(
            {"platform": "", "session_key": _TG_PRIVATE_KEY, "conversation_type": "private"}
        )
    else:
        kwargs.update({"platform": _TG_PLATFORM, "session_key": "", "conversation_type": ""})
    body = _run(h, "unset-name", **kwargs).body
    assert _fail_closed_predicates(body, "亲密档") == [True, True, True, True], (
        f"缺 {missing} 那一枚事实时这一格没落『说不准』：{body}"
    )
    assert _marker_cell(h, _TG_PRIVATE_KEY)[0] == _TIER, "回执说不准，不代表这一格被收了"


def test_the_intimate_fail_closed_leg_is_not_decoration(
    h: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """锁 C′（变异自证）：摘掉"事实不齐＝说不准"那一腿（恒去读）⇒ ⑧ 的判据当场失效。

    毒的是内存里的替身（把取格腿换成"没有守卫"的形状），源码树一字不动。平台事实缺席、
    会话事实在场那一支才咬得动：那一把键下标记**确实在**，摘腿后回执会兴高采烈地把它列进
    "保住的那几格"＝拿一枚认不出归属的键替这个人作保。
    """

    def _always_read(_config: Any, *, session_key: str, platform: str) -> bool | None:
        return bool(cr.read_intimate_pin(session_key, config=_config))

    h.store.set(
        session_type="private", session_id="", sender_id=_TG_CHAT, addressing_preference=_NAME
    )  # type: ignore[arg-type]
    _open_intimate_via_the_axis(h, _TG_PRIVATE_KEY)
    honest = _fail_closed_predicates(
        _run(
            h,
            "unset-name",
            group_id="",
            platform="",
            session_key=_TG_PRIVATE_KEY,
            conversation_type="private",
            sender_id=_TG_CHAT,
        ).body,
        "亲密档",
    )
    assert honest == [True, True, True, True], honest

    monkeypatch.setattr(echo_module, "_identity_intimate_cell", _always_read)
    h.store.set(
        session_type="private", session_id="", sender_id=_TG_CHAT, addressing_preference=_NAME
    )  # 名字刚被清掉，重新钉上，让摘腿后走的仍是"已清除"那一支（同一条腿对照同一条腿）
    stripped = _fail_closed_predicates(
        _run(
            h,
            "unset-name",
            group_id="",
            platform="",
            session_key=_TG_PRIVATE_KEY,
            conversation_type="private",
            sender_id=_TG_CHAT,
        ).body,
        "亲密档",
    )
    assert stripped[0] is False, f"摘腿后这一格仍不说明白＝⑧ 的第①条是摆设：{stripped}"
    assert stripped[1] is False, f"摘腿后这一格被列进了保住的那几格＝⑧ 的第②条没咬到点：{stripped}"


def test_the_admin_entrypoint_forwards_the_platform_into_the_receipt(h: _Harness) -> None:
    """⑤续（链过第 2 处）：`/bot identity unset-name` 的真路径＝管理员入口的自助拦截。

    这一枚在**只接第 3 处**时必红：`runtime_admin` 不转发平台事实，读点就永远拿不到
    ⇒ 写在 `qq:<uid>`、读在 `<uid>`（#33★ 那族两形不相交）。
    """
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_admin import (
        build_session_identity_admin_result,
    )

    _seed_the_whole_row(h)
    result = build_session_identity_admin_result(
        h.config,
        request_id="req-f8-chain",
        actor_roles=["user"],
        session_key=_PRIVATE_KEY,
        command_text="unset-name",
        sender_id=_UID,
        group_id="",
        platform=_PLATFORM,
        conversation_type="private",
    )
    assert "描写档" in _kept_enumeration(result.body), result.body
    assert _UNCERTAIN_WORD not in result.body, result.body


def test_the_group_and_private_narration_cells_are_not_cross_read(h: _Harness) -> None:
    """⑥：会话齿（I-2「换了会话就需要重新激发」）——群里那一轮读的是群里那一格。

    两半各跑一次，只测一半＝把共桶当接线：私聊钉着 scene、群里没钉 ⇒ 群里的回执不许把
    私聊那枚算成"保住"（那等于替另一格的事实作保）；反向（群里钉了）必须点名。
    """
    key = {"session_type": "group", "session_id": _GROUP, "sender_id": _UID}
    _seed_narration_row(h, _PRIVATE_KEY)
    h.store.set(**key, addressing_preference=_NAME)  # type: ignore[arg-type]
    assert _narration(h, _PRIVATE_KEY)[0] == _MODE
    assert _narration(h, _GROUP_KEY) == ("", 0.0), "群里那一格本该是空的"
    body = _run_group(h, "unset-name").body
    assert "描写档" not in _kept_enumeration(body), body
    assert _UNCERTAIN_WORD not in body, body  # 平台事实在场，这一格读得到"没钉"

    _pin_narration_via_the_axis(h, _GROUP_KEY)
    assert _narration(h, _GROUP_KEY)[0] == _MODE, "群里那枚钉没落库＝下面的断言在空跑"
    h.store.set(**key, addressing_preference=_NAME)  # type: ignore[arg-type]
    group_body = _run_group(h, "unset-name").body
    assert "描写档" in _kept_enumeration(group_body), group_body


# --------------------------------------------------------------------------
# ⑦：fail-closed——平台事实缺席时这一格只准说不准
# --------------------------------------------------------------------------


@pytest.mark.parametrize("thin_row", [False, True])
def test_unset_name_without_the_platform_fact_never_vouches_for_the_narration_cell(
    h: _Harness, thin_row: bool
) -> None:
    """⑦：读点拿不到平台事实 ⇒ 不许宣称"描写档保住了"，也不许把它算进"谁也没被牵连"。

    缺口（席 idplat 的第四枚判据）：只把读侧换成走 `read_narration_pin` 仍不够——平台事实
    缺席时取钉口 fail-closed 折回裸 uid 那一格，**读空不等于没有**。
    两行样本各跑一次（`thin_row` 那一支 kept 为空，旧文"谁也没被牵连"正是这一格替人作保的
    位置；每支都拿到自己的 tmp 库，样本互不污染）。
    """
    if thin_row:
        _seed_only_the_name_and_the_pin(h)
    else:
        _seed_the_whole_row(h)
    assert _narration(h) == (_MODE, _MODE_STAMP), "前提：钉在库里（三段键那一格）"
    body = _run(
        h, "unset-name", group_id="", platform="", session_key="", conversation_type=""
    ).body
    assert _fail_closed_predicates(body) == [True, True, True, True], body
    assert _narration(h) == (_MODE, _MODE_STAMP), "回执说不准，不代表这一格被收了"


def test_the_fail_closed_leg_is_not_decoration(
    h: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """锁 C（变异自证）：摘掉"平台事实缺席＝说不准"那一腿（恒去读）⇒ ⑦ 的判据当场失效。

    毒的是内存里的替身（把取格腿换成"没有守卫"的形状），源码树一字不动。样本用最小那一支
    （这一行只有称谓列＋一枚钉）：kept 为空时摘腿后的回执会写出「谁也没被牵连」＝正是"把谎
    从读不到挪到读得到"那一型。
    ⚠ 第③条那句谎现在由**两格一起**守（席 unmask-intimate 之后 `elif` 那一道门要两格都
    确实没有才写"谁也没被牵连"）：只摘描写那一腿时亲密那一格还在老实说"说不准"，那句冒不出来
    ⇒ 单摘一条腿只咬得住第①与第④条。所以本件**两半都跑**：单摘＝①④塌；两格一起摘＝③也塌。
    少跑后一半，"两格合守那句"这道门就成了没人量过的地板。
    """

    def _always_read(
        config: Any,
        *,
        sender: str,
        session_key: str,
        platform: str,
        conversation_type: str,
    ) -> bool | None:
        return bool(
            cr.read_narration_pin(
                session_key,
                sender_id=sender,
                config=config,
                platform=platform,
                conversation_type=conversation_type,
            )
        )

    def _facts() -> dict[str, Any]:
        return {"group_id": "", "platform": "", "session_key": "", "conversation_type": ""}

    _seed_only_the_name_and_the_pin(h)
    honest = _fail_closed_predicates(_run(h, "unset-name", **_facts()).body)
    assert honest == [True, True, True, True], honest

    monkeypatch.setattr(echo_module, "_identity_narration_cell", _always_read)
    h.store.set(
        session_type="private", session_id="", sender_id=_UID, addressing_preference=_NAME
    )  # 重新钉上名字，让摘腿后仍走"已清除"那一支（同一条腿对照同一条腿）
    stripped = _fail_closed_predicates(_run(h, "unset-name", **_facts()).body)
    assert stripped[0] is False, f"摘腿后这一格不再说明白＝⑦ 的第①条是摆设：{stripped}"
    assert stripped[3] is False, f"摘腿后这一格被整格静吃＝⑦ 的第④条没咬到点：{stripped}"

    monkeypatch.setattr(echo_module, "_identity_intimate_cell", lambda *_a, **_kw: False)
    h.store.set(
        session_type="private", session_id="", sender_id=_UID, addressing_preference=_NAME
    )  # 同上：两条腿对照同一条腿，别让"已清除"那一支半路换形
    both = _fail_closed_predicates(_run(h, "unset-name", **_facts()).body)
    assert both[2] is False, f"两格都摘后那句谁也没被牵连没人拦＝⑦ 的第③条成了地板：{both}"


# --------------------------------------------------------------------------
# 形状锁：三处同批（根派发 → 管理员转发 → 回执读点），值只准转述契约字段
# --------------------------------------------------------------------------


def _call_sites(src: str, func_name: str) -> list[ast.Call]:
    tree = ast.parse(src, filename="<src>")
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == func_name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == func_name)
        )
    ]


def _kwarg_source(src: str, call: ast.Call, name: str) -> str:
    for kw in call.keywords:
        if kw.arg == name:
            return ast.get_source_segment(src, kw.value) or ""
    return ""


def _kwarg_lines(call: ast.Call, name: str) -> tuple[int, int] | None:
    for kw in call.keywords:
        if kw.arg == name:
            return int(kw.lineno), int(kw.end_lineno or kw.lineno)
    return None


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _root_identity_leg_gaps(src: str) -> list[str]:
    """根 `__init__.py` 的 identity 分支：平台事实与会话事实每一枚都要交、且只准转述契约字段。"""
    calls = _call_sites(src, "build_session_identity_admin_result")
    if len(calls) != 1:
        return [f"identity 派发应有恰好一支，现算 {len(calls)} 支"]
    call = calls[0]
    gaps: list[str] = []
    for name, anchor in (("platform", "platform"), ("conversation_type", "session_type")):
        given = _kwarg_source(src, call, name)
        if not given:
            gaps.append(f"__init__.py:{call.lineno} identity 派发没交 {name}")
        elif "message" not in given or anchor not in given:
            gaps.append(
                f"__init__.py:{call.lineno} {name}={given!r} 不是转述契约字段 "
                "IncomingMessage（猜平台／反解会话键＝T-1 同族）"
            )
    if not _kwarg_source(src, call, "session_key"):
        gaps.append(f"__init__.py:{call.lineno} identity 派发没交 session_key")
    return gaps


def _admin_forward_gaps(src: str) -> list[str]:
    """`runtime_admin` 的自助拦截：三枚事实逐枚转发**本函数已有的形参**，不在这层补值。"""
    calls = _call_sites(src, "build_identity_preference_result")
    if len(calls) != 1:
        return [f"管理员拦截应有恰好一支转发，现算 {len(calls)} 支"]
    call = calls[0]
    gaps: list[str] = []
    for name in ("session_key", "platform", "conversation_type"):
        given = _kwarg_source(src, call, name)
        if not given:
            gaps.append(f"runtime_admin:{call.lineno} 没转发 {name}")
        elif given.strip() != name:
            gaps.append(
                f"runtime_admin:{call.lineno} {name}={given!r} 不是原样转发形参"
                "（在这一层补值／猜平台＝第二处声明位）"
            )
    return gaps


def test_the_identity_dispatch_leg_in_the_root_threads_the_platform_from_the_contract_field() -> None:
    """第 1 处：根派发的 identity 分支把 `message.platform` 交给管理员入口（现成先例的形狀）。"""
    assert _root_identity_leg_gaps(_INIT_SRC.read_text(encoding="utf-8")) == []


def test_the_admin_entrypoint_forwards_all_three_session_facts() -> None:
    """第 2 处：`runtime_admin` 的自助拦截把三枚事实原样转给回执读点。"""
    assert _admin_forward_gaps(_ADMIN_SRC.read_text(encoding="utf-8")) == []


def test_the_receipt_read_point_uses_the_one_pin_accessor() -> None:
    """第 3 处：回执读点只经 `content_route.read_narration_pin`，不在 echo 里再拼键形。"""
    src = _ECHO_SRC.read_text(encoding="utf-8")
    reads = _call_sites(src, "read_narration_pin")
    assert len(reads) == 1, f"echo 里的取钉口应恰好一处，现算 {len(reads)} 处"
    call = reads[0]
    assert _kwarg_source(src, call, "platform"), "取钉口没交平台事实＝永远 fail-closed"
    assert _kwarg_source(src, call, "conversation_type"), "取钉口没交会话事实＝会话齿没人接"
    # echo 不调任何键形构造口（中央件才是唯一入口；这里按**调用点**判，不按字面判——
    # 本文件 docstring 要提这枚名字，按子串判会自己咬自己一口）。
    for ctor in ("person_scope_key", "build_session_key", "private_session_key", "group_scope_key"):
        assert not _call_sites(src, ctor), f"echo 里调了 {ctor}＝第二处键形构造位"


def test_shape_lock_goes_red_when_only_the_last_leg_is_wired(tmp_path: Path) -> None:
    """注毒①：抹掉根派发那一行 `platform=`（＝只接第 3 处那一种半件）⇒ 形状锁当场红。

    只毒内存副本，另落一份 tmp 副本备复跑（规则 6：源码树零写）。这一族的病名写在台账
    #33★：写在 `qq:<uid>`、读在裸 `<uid>`，两侧永不相交。
    """
    src = _INIT_SRC.read_text(encoding="utf-8")
    call = _call_sites(src, "build_session_identity_admin_result")[0]
    span = _kwarg_lines(call, "platform")
    assert span is not None, "锚点不在场＝形状锁没有可毒的腿（先接线性）"
    lines = src.splitlines(keepends=True)
    del lines[span[0] - 1 : span[1]]
    stripped = "".join(lines)
    assert stripped != src, "注毒没落到任何一行＝本件空跑"
    gaps = _root_identity_leg_gaps(stripped)
    assert any("没交 platform" in gap for gap in gaps), gaps
    (tmp_path / "init_strip.py").write_text(stripped, encoding="utf-8")


def test_shape_lock_goes_red_on_a_hard_coded_platform() -> None:
    """注毒②：把平台值硬编成 `"qq"` ⇒ 红（写进一个平台＝键形从此永不相交）。"""
    src = _INIT_SRC.read_text(encoding="utf-8")
    call = _call_sites(src, "build_session_identity_admin_result")[0]
    span = _kwarg_lines(call, "platform")
    assert span is not None, "锚点不在场＝形状锁没有可毒的腿"
    lines = src.splitlines(keepends=True)
    lines[span[0] - 1] = f"{_leading_ws(lines[span[0] - 1])}platform=\"qq\",\n"
    poisoned = "".join(lines)
    assert poisoned != src
    gaps = _root_identity_leg_gaps(poisoned)
    assert any("不是转述契约字段" in gap for gap in gaps), gaps


def test_admin_forward_lock_goes_red_when_the_middle_leg_is_cut() -> None:
    """注毒①的另一半：管理员层不转发平台事实⇒ 转发锁红（三处同批，缺一即半成品）。"""
    src = _ADMIN_SRC.read_text(encoding="utf-8")
    call = _call_sites(src, "build_identity_preference_result")[0]
    span = _kwarg_lines(call, "platform")
    assert span is not None, "锚点不在场＝转发锁没有可毒的腿"
    lines = src.splitlines(keepends=True)
    del lines[span[0] - 1 : span[1]]
    gaps = _admin_forward_gaps("".join(lines))
    assert any("没转发 platform" in gap for gap in gaps), gaps


# --------------------------------------------------------------------------
# 形状锁·亲密档齿（席 unmask-intimate）：读口只一处、两侧都接、值只准转述事实
# --------------------------------------------------------------------------


def _called_names(node: ast.AST) -> set[str]:
    """一个函数体里**被调用**的名字（Name 直调 ∪ Attribute 尾名；按调用点判，不按字面判）。"""
    found: set[str] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        if isinstance(call.func, ast.Name):
            found.add(call.func.id)
        elif isinstance(call.func, ast.Attribute):
            found.add(call.func.attr)
    return found


def _function_node(src: str, name: str) -> ast.FunctionDef | None:
    tree = ast.parse(src, filename="<src>")
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


#: 标记读口**不许**自己碰的键形构造位（碰了＝第二处真身／反解会话键猜平台，T-1 同族）。
_KEY_CTOR_FORBIDDEN = (
    "person_scope_key",
    "private_session_key",
    "build_session_key",
    "group_scope_key",
    "parse_session_key",
    "split_member_session_key",
    "_explicit_pin_person_key",
)


def _cr_marker_port_gaps(src: str) -> list[str]:
    """轴心侧：`read_intimate_pin` 必须是**唯一公开读口**，且取键只经写腿那一把 `_explicit_pin_person_key`。"""
    gaps: list[str] = []
    fn = _function_node(src, "read_intimate_pin")
    if fn is None:
        return [
            (
                "content_route 没有 `read_intimate_pin` 定义＝只接了 echo 那一侧"
                "（读点没有唯一口，回执迟早自己去拼键形）"
            )
        ]
    called = _called_names(fn)
    if "_explicit_pin_person_key" not in called:
        gaps.append("读口没经写腿那把取键口 `_explicit_pin_person_key`＝读写两把尺（#33★ 那族）")
    if "get_intimate_pin" not in called:
        gaps.append("读口没查标记那两列＝交回去的永远是空串")
    for ctor in ("person_scope_key", "_narration_person_key", "parse_session_key"):
        if ctor in called:
            gaps.append(f"读口里调了 {ctor}＝第二处键形构造位（猜平台／换一把尺读同一格）")
    body = ast.get_source_segment(src, fn) or ""
    for const in ("_EXPLICIT_PIN_SESSION_TYPE", "_EXPLICIT_PIN_SESSION_ID"):
        if const not in body:
            gaps.append(f"读口的会话段没取在册常量 {const}＝自己另立一格桶")
    return gaps


def _echo_intimate_read_gaps(src: str) -> list[str]:
    """echo 侧：取格腿恰好一处、两枚事实只准转述形参、守卫必须两枚都看并且能回 None。"""
    gaps: list[str] = []
    cells = _call_sites(src, "_identity_intimate_cell")
    if len(cells) != 1:
        return [f"echo 里的亲密档取格腿应恰好一处，现算 {len(cells)} 处"]
    call = cells[0]
    for name in ("session_key", "platform"):
        given = _kwarg_source(src, call, name)
        if not given:
            gaps.append(f"echo:{call.lineno} 取格腿没交 {name}＝这一格永远读不到、永远说不准")
        elif given.strip() != name:
            gaps.append(
                f"echo:{call.lineno} {name}={given!r} 不是原样转述形参"
                "（硬编一个平台＝写进哪个平台就只认哪个平台，两形从此不相交）"
            )
    reads = _call_sites(src, "read_intimate_pin")
    if len(reads) != 1:
        gaps.append(f"echo 里的标记读口应恰好一处，现算 {len(reads)} 处＝第二处真身")
    elif not _kwarg_source(src, reads[0], "config"):
        gaps.append(f"echo:{reads[0].lineno} 标记读口没交 config＝永远取不到库，这一格静吃")
    fn = _function_node(src, "_identity_intimate_cell")
    if fn is None:
        gaps.append("echo 没有 `_identity_intimate_cell` 定义＝fail-closed 腿无处放")
    else:
        guard_names: set[str] = set()
        returns_none = False
        for node in ast.walk(fn):
            if isinstance(node, ast.If):
                guard_names |= {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            if isinstance(node, ast.Return) and (
                node.value is None
                or (isinstance(node.value, ast.Constant) and node.value.value is None)
            ):
                returns_none = True
        for fact in ("platform", "session_key"):
            if fact not in guard_names:
                gaps.append(f"守卫没看 {fact}＝事实缺席时这一格替人作保（把谎挪到读得到）")
        if not returns_none:
            gaps.append("守卫不交 None＝事实缺席被当成『确实没有』，说不准那一支没人投递")
        if "read_intimate_pin" not in _called_names(fn):
            gaps.append("取格腿没经唯一标记口＝它自己去查了库（第二处读点）")
    for ctor in _KEY_CTOR_FORBIDDEN:
        if _call_sites(src, ctor):
            gaps.append(f"echo 里调了 {ctor}＝echo 自己拼了键形（唯一口在轴心那一侧）")
    return gaps


def test_the_intimate_read_point_uses_the_one_marker_accessor_both_sides() -> None:
    """两侧都接：轴心出唯一公开读口（取键＝写腿那一把），echo 只转述它、不拼第二形。"""
    assert _cr_marker_port_gaps(_CR_SRC.read_text(encoding="utf-8")) == []
    assert _echo_intimate_read_gaps(_ECHO_SRC.read_text(encoding="utf-8")) == []


def test_marker_port_lock_goes_red_when_only_the_echo_side_is_wired(tmp_path: Path) -> None:
    """注毒①甲：**只接 echo**（轴心那口被摘）⇒ 轴侧锁红。

    毒的是内存副本＋一份 tmp 备复跑件（规则 6：源码树零写）。这一族的病名＝读点没有唯一口，
    下一位改回执的人只能自己去拼键形，写在 A 形、读在 B 形（#33★／T-1）。
    """
    src = _CR_SRC.read_text(encoding="utf-8")
    fn = _function_node(src, "read_intimate_pin")
    assert fn is not None, "锚点不在场＝轴心那口没落地，本件没有可毒的腿"
    poisoned = src.replace(f"def {fn.name}(", "def _retired_read_intimate_pin(", 1)
    assert poisoned != src, "注毒没落到任何一行＝本件空跑"
    gaps = _cr_marker_port_gaps(poisoned)
    assert any("没有 `read_intimate_pin` 定义" in gap for gap in gaps), gaps
    (tmp_path / "cr_port_retired.py").write_text(poisoned, encoding="utf-8")


def test_marker_port_lock_goes_red_when_the_read_point_is_the_second_ruler(tmp_path: Path) -> None:
    """注毒①乙：**只接 echo 的另一型**＝读口改拿描写钉那把 (平台域, 人) 的尺读标记。

    同一条锁必须红：两格两套键形，读口换成 `_narration_person_key` 就等于"写在 A 形、读在 B 形"。
    """
    src = _CR_SRC.read_text(encoding="utf-8")
    poisoned = src.replace(
        "        person_key = _explicit_pin_person_key(session_key, config)\n"
        "        if not person_key:\n"
        '            return ""\n'
        "        store = _explicit_pin_store(config)",
        "        person_key = _narration_person_key(session_key, config=config)\n"
        "        if not person_key:\n"
        '            return ""\n'
        "        store = _explicit_pin_store(config)",
        1,
    )
    assert poisoned != src, "注毒锚没落＝本件空跑（读口取键那一行改了形，先同步本件）"
    gaps = _cr_marker_port_gaps(poisoned)
    assert any("读写两把尺" in gap for gap in gaps), gaps
    assert any("第二处键形构造位" in gap for gap in gaps), gaps
    (tmp_path / "cr_port_second_ruler.py").write_text(poisoned, encoding="utf-8")


def test_echo_intimate_lock_goes_red_on_a_hard_coded_platform(tmp_path: Path) -> None:
    """注毒②：把 echo 取格腿的 `platform=` 硬编成 `"qq"` ⇒ echo 侧锁红（且 ⑧ 的功能锁也红）。

    写进一个平台＝这一格从此只认那个平台的键形；TG 那一侧的标记又读不到，而事实缺席那一支
    会被"硬编在场的值"顶成"读得到"＝fail-closed 腿整体失效。
    """
    src = _ECHO_SRC.read_text(encoding="utf-8")
    call = _call_sites(src, "_identity_intimate_cell")[0]
    span = _kwarg_lines(call, "platform")
    assert span is not None, "锚点不在场＝echo 侧锁没有可毒的腿"
    lines = src.splitlines(keepends=True)
    lines[span[0] - 1] = f"{_leading_ws(lines[span[0] - 1])}platform=\"qq\",\n"
    poisoned = "".join(lines)
    assert poisoned != src, "注毒没落到任何一行＝本件空跑"
    gaps = _echo_intimate_read_gaps(poisoned)
    assert any("不是原样转述形参" in gap for gap in gaps), gaps
    (tmp_path / "echo_intimate_hardcode.py").write_text(poisoned, encoding="utf-8")


def test_echo_intimate_lock_goes_red_when_the_guard_is_stripped() -> None:
    """注毒③：摘掉守卫里 `platform` 那一枚（恒去读）⇒ echo 侧锁红（⑧ 的功能锁同步红）。

    毒的是**本函数那一段**的内存副本（`ast.get_source_segment` 取段、拼回原串），源码树零写；
    按整串 replace 会被隔壁 `_identity_narration_cell` 的同形守卫顶掉＝毒错了地方还能绿。
    """
    src = _ECHO_SRC.read_text(encoding="utf-8")
    fn = _function_node(src, "_identity_intimate_cell")
    assert fn is not None, "锚点不在场＝守卫没落地，本件没有可毒的腿"
    seg = ast.get_source_segment(src, fn) or ""
    anchor = 'if not str(platform or "").strip() or '
    assert anchor in seg, "守卫那一行改了形＝先同步本件的锚"
    start = src.index(seg)
    poisoned = src[: start] + seg.replace(anchor, "if not ", 1) + src[start + len(seg) :]
    assert poisoned != src, "注毒没落到任何一行＝本件空跑"
    gaps = _echo_intimate_read_gaps(poisoned)
    assert any("守卫没看 platform" in gap for gap in gaps), gaps


# --------------------------------------------------------------------------
# 锁 A：自助命令面结构上碰不到整行 DELETE
# --------------------------------------------------------------------------


def test_the_self_service_surface_never_reaches_the_row_delete_entry(
    h: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """命令面一旦改回 `store.clear()`（整行 DELETE），这枚当场红——不用等人来看盘。"""
    reached: list[str] = []
    monkeypatch.setattr(
        AddressingPreferenceStore,
        "clear",
        lambda self, **_kw: reached.append("row-delete"),
    )
    monkeypatch.setattr(
        AddressingPreferenceStore,
        "clear_columns",
        lambda self, **_kw: reached.append("column-clear"),
    )
    _seed_the_whole_row(h)
    for text in ("unset-name", "unset-gender"):
        _run(h, text, group_id="")
    assert reached == ["column-clear", "column-clear"], (
        f"自助称谓面又摸回整行 DELETE 了（实际调用序列={reached}）"
    )


# --------------------------------------------------------------------------
# 锁 B：注毒——把按列清退回整行删，四枚正面判据必须红
# --------------------------------------------------------------------------


def test_poison_row_wipe_turns_the_four_positive_locks_red(
    h: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒自证：按列清那一口换成"整条 DELETE"⇒ ①②③④ 逐枚失效（锁真咬得住）。"""

    def _row_wipe(self: AddressingPreferenceStore, **kwargs: Any) -> None:
        self.clear(
            session_type=str(kwargs.get("session_type", "private")),
            session_id=str(kwargs.get("session_id", "")),
            sender_id=str(kwargs.get("sender_id", "")),
        )

    monkeypatch.setattr(AddressingPreferenceStore, "clear_columns", _row_wipe)
    _seed_the_whole_row(h)
    flags = _positive_locks(h)
    names = ("①亲密档照在", "②描写档照在", "③名字列清了", "④回执点名清/保")
    assert len(flags) == len(names)
    turned_red = [name for name, ok in zip(names, flags, strict=True) if not ok]
    assert turned_red == list(names), (
        f"注毒只让 {turned_red} 变红（其余仍绿）＝那几枚是摆设：退回整行删 ought 逐枚咬下"
    )


# --------------------------------------------------------------------------
# 文案面：帮助册不许再留「按行删」「按人不按会话」两句过期话
# --------------------------------------------------------------------------


def _entry_blob(topic: str) -> str:
    entry = next(item for item in HELP_ENTRIES if item["topic"] == topic)
    parts = [str(entry.get("index", "")), str(entry.get("title_line", "")), str(entry.get("detail", ""))]
    parts.extend(str(line) for line in entry.get("lines", []))
    return "\n".join(parts)


def test_identity_help_no_longer_promises_a_whole_row_cleanup() -> None:
    blob = _entry_blob("身份")
    assert "整条记录清除" not in blob, "帮助册还在承诺整条记录清除＝与裁定甲相反"
    assert "只清称谓偏好那一列" in blob
    assert "只清性别自述那一列" in blob


def test_intimate_help_no_longer_calls_unset_name_a_row_delete() -> None:
    blob = _entry_blob("亲密模式")
    assert "整行删除" not in blob, "「unset-name 的整行删除」这句在裁定甲之后是假陈述"


def test_narration_help_declares_the_i2_key_shape() -> None:
    """I-2：钉的键形＝(平台域, 会话, 这个人)，换了会话要重新激发——旧"按人不按会话"是假话。"""
    blob = _entry_blob("亲密模式")
    assert "这一轴按**会话里的这个人**" in blob
    assert "换了会话就需要重新激发" in blob
    assert "这一轴**按人**不按会话" not in blob
    assert "**描写档没有 TTL**" in blob  # 原有事实不许被整句替换顺手吃掉


def test_narration_help_discloses_the_group_whitelist_leg() -> None:
    """I-4 第③条：群侧这一格只在内容路由白名单群里生效，必须明写（防"开了却没变化"）。"""
    blob = _entry_blob("亲密模式")
    assert "内容路由白名单群" in blob
    assert "BOT_CONTENT_ROUTE_GROUP_WHITELIST" in blob
    assert "落回日常档" in blob
