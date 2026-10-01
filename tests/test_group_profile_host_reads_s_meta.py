"""S-META 需求 4 交付锁：QQ 对端资料读件 + 三通道身份读件 + 活性/缺席/三态锁。

各判据（编号只增不改，逐条独立可跑）锁一件事，全部离线（假 API + 手造事件），零网络零真实凭据：

① ``read_qq_account_meta`` 的读数语义（缺席≠空值、认不出的状态码不硬套标签、
   batteryStatus 的 0 值当「读不出」而不是「电量 0%」）。
② **群文件腿的活性锁**：``build_group_info_capability`` 有 ``group_file_store``
   形参、能力里判 ``is not None`` 才渲染那一段——**形参存在不等于接上了**。
   本波真实事故形态就是「装配点没传」：段永不出现而代码看起来是对的，
   任何单元测试都拦不住，只能拿根装配文件的**实传参**来锁。
③ 三通道身份读件（``message_context`` 的 TG/Mail 展示名）：取不到回 None，
   **绝不**用 sender_id 冒充名字。
④ **结构性缺席枚举锁**（§50 范式「证明缺席且代次>0 与守卫同读」）：
   幸运符号 / 群幸运符号 / 网络制式 三格逐格证明「全仓零读点 + 理由在册」。
   没有这枚锁，下次接手会把它们当「还没做」再返工一遍；有了它，
   任何一方（真接上了、或理由被删了）改动都会红——**缺席必须是个被看着的状态**。
⑤ **读件三态锁**（二批）：``ok`` / ``failed``（真打了接口问不出来）/ ``unprobed``
   （这轮压根没问：桥未接线、或事件没带对象号）。第三态从前塌进 ``api_fail``，
   等于谎报一次没发生过的请求；更要防的是它被顺手套上 ``status`` 的 ``"0" -> 离线``
   真标签，凭空替真人编出一个「他/她不在线」。判据是结构性的：未探测时
   ``在线状态`` 这一格连标签都不许出现在正文里。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import group_info as gi
from plugins.bot_unified_runtime.domains.chat_reply.ingest.message_context import (
    mail_sender_display_name,
    sender_display_name_for_event,
    telegram_sender_display_name,
)

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "plugins" / "bot_unified_runtime"


def _fetch_factory(responses: dict[str, Any], *, fail: set[str] = frozenset()):
    """造一个 ``_fetch`` 形态的读口：``(kind, key, action, **params) -> (ok, payload)``。"""

    def fetch(kind: str, key: str, action: str, **params: Any) -> tuple[bool, Any]:
        if action in fail:
            return False, None
        if action not in responses:
            raise AssertionError(f"不该打这个动作：{action}")
        return True, responses[action]

    return fetch


# ---------------------------------------------------------------------------
# ① QQ 对端账号资料读件
# ---------------------------------------------------------------------------


def test_qq_meta_returns_only_cells_the_api_answered() -> None:
    fetch = _fetch_factory({
        gi.QQ_ACCOUNT_META_ACTION: {"nickname": "阿澜", "long_nick": "看海"}
    })
    meta, audit = gi.read_qq_account_meta(fetch, "123")
    assert meta == {"昵称": "阿澜", "个性签名": "看海"}
    # 等级/在线状态/电量三格册里没回 ⇒ 不进字典（缺席不是空值）。
    assert "等级" not in meta and "在线状态" not in meta and "电量" not in meta
    assert audit[0] == "qq_account_meta"


def test_qq_meta_api_fail_and_no_user_id_are_distinct_audits() -> None:
    fail_fetch = _fetch_factory({}, fail={gi.QQ_ACCOUNT_META_ACTION})
    assert gi.read_qq_account_meta(fail_fetch, "123") == (
        {},
        ["qq_account_meta", "api_fail"],
    )
    assert gi.read_qq_account_meta(fail_fetch, "") == (
        {},
        ["qq_account_meta", "no_user_id"],
    )


def test_qq_meta_unknown_status_code_is_reported_with_the_code() -> None:
    """状态码表只登记能核到的值；认不出就带原码说话，不硬套一个中文标签。"""
    fetch = _fetch_factory({gi.QQ_ACCOUNT_META_ACTION: {"status": 99}})
    meta, _ = gi.read_qq_account_meta(fetch, "123")
    assert meta["在线状态"] == "状态码 99（动作册没给中文名，不替你猜）"
    fetch_known = _fetch_factory({gi.QQ_ACCOUNT_META_ACTION: {"status": 3}})
    assert gi.read_qq_account_meta(fetch_known, "123")[0]["在线状态"] == "忙碌（状态码 3）"


def test_qq_meta_battery_zero_is_not_a_percentage() -> None:
    """batteryStatus 在册但「值是否恒 0」属运行时事实 ⇒ 0 当「读不出有效值」。"""
    fetch = _fetch_factory({gi.QQ_ACCOUNT_META_ACTION: {"batteryStatus": 0}})
    assert gi.read_qq_account_meta(fetch, "123")[0]["电量"] == ""
    fetch_live = _fetch_factory({gi.QQ_ACCOUNT_META_ACTION: {"batteryStatus": 77}})
    assert gi.read_qq_account_meta(fetch_live, "123")[0]["电量"] == "77%"


def test_qq_meta_note_shape_matches_sender_profile_note() -> None:
    """注入侧要的是 ``键=值；键=值``，且空值必须被丢掉（分区渲染按 v 非空留行）。"""
    meta = {"昵称": "阿澜", "个性签名": "", "在线状态": "在线（状态码 1）", "电量": ""}
    assert gi.format_qq_account_meta_note(meta) == "昵称=阿澜；在线状态=在线（状态码 1）"
    assert gi.format_qq_account_meta_note(meta, exclude=("昵称",)) == (
        "在线状态=在线（状态码 1）"
    )
    assert gi.format_qq_account_meta_note({}) == ""


# ---------------------------------------------------------------------------
# ② 群文件腿活性锁：装配点必须真把 store 传进去
# ---------------------------------------------------------------------------


def _build_call_kwargs(root_source: str) -> list[str]:
    tree = ast.parse(root_source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_group_info_capability"
        ):
            return [kw.arg for kw in node.keywords if kw.arg]
    raise AssertionError("根装配文件里找不到 build_group_info_capability 的调用点")


def test_group_file_store_is_passed_at_the_root_wiring_site() -> None:
    """群文件那一段在 ``profile`` 档里出现与否，只取决于装配点传没传 store。

    形参存在 + 能力里判 ``is not None`` ＝代码自洽；装配点漏传＝**这段永不出现**，
    而所有单元测试都在自己传 store 的前提下跑，全绿。这是「代码对、链路断」的
    典型形态，必须拿根文件的实传参来锁（本波由 S-META 现算发现，修复走 hub 申请）。
    """
    kwargs = _build_call_kwargs((PKG / "__init__.py").read_text(encoding="utf-8"))
    assert "group_file_store" in kwargs, (
        "build_group_info_capability 没传 group_file_store ⇒ 群资料档里的群文件段"
        "永不出现（能力侧判的是 is not None）。修复＝装配点补传已构造的 group_file_store，"
        "见 _hub 补丁申请。"
    )


def test_group_file_section_requires_the_store_and_says_so_without_it() -> None:
    """能力侧的另一半：不传 store 时这一段**整段不出现**（缺数=缺行，不编）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.group_cache import (
        GroupInfoCache,
    )

    class _Api:
        def __call__(self, action: str, **params: object) -> object:
            if action == "get_group_info":
                return {"group_name": "观察站", "member_count": 3, "max_member_count": 50}
            if action == "get_group_member_list":
                return [{"user_id": 1, "nickname": "站主", "role": "owner"}]
            if action == "get_group_notice":
                return []
            if action == "get_essence_msg_list":
                return []
            raise AssertionError(f"不该打这个动作：{action}")

    message = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot",
        session_id="group_12345",
        session_type=SessionType.GROUP,
        sender_id="1",
        sender_roles=["admin"],
        group_id="12345",
        plain_text="群资料",
    )
    without = gi.build_group_info_capability(
        api=_Api(), cache=GroupInfoCache()
    )(message, None).body
    assert "群文件" not in without, "不传 store 却冒出群文件段＝第二数据来源"

    class _Store:
        @staticmethod
        def summary(group_id: str, *, limit: int = 5) -> str:
            return f"群文件：我见过 {limit} 个上传（{group_id}）"

    with_store = gi.build_group_info_capability(
        api=_Api(), cache=GroupInfoCache(), group_file_store=_Store()
    )(message, None).body
    assert "群文件：我见过 5 个上传（12345）" in with_store


# ---------------------------------------------------------------------------
# ③ 三通道身份读件（装配点在根摄取函数，走 hub 申请）
# ---------------------------------------------------------------------------


class _User:
    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


class _Addr:
    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


def test_telegram_display_name_prefers_full_name_then_username() -> None:
    event = _User(message=_User(from_user=_User(first_name="阿", last_name="澜", username="lan")))
    assert telegram_sender_display_name(event) == "阿 澜"
    no_last = _User(message=_User(from_user=_User(first_name="", last_name="", username="lan")))
    assert telegram_sender_display_name(no_last) == "@lan"
    assert telegram_sender_display_name(_User(message=None)) is None


def test_mail_display_name_never_falls_back_to_the_address() -> None:
    """只有 email 没有显示名 ⇒ None：地址已经在 sender_id 里，拿它当昵称是冒充。"""
    assert mail_sender_display_name(_User(mail_from=_Addr(name="阿澜", email="a@b.c"))) == "阿澜"
    assert mail_sender_display_name(_User(mail_from=_Addr(name="", email="a@b.c"))) is None


def test_sender_display_name_dispatcher_does_not_touch_qq() -> None:
    """QQ 返回 None＝「本读件不插手」，既有 card/nickname 优先级不许被复制第二份。"""
    assert sender_display_name_for_event(_User(), "onebot v11") is None
    assert sender_display_name_for_event(
        _User(message=_User(from_user=_User(first_name="澜"))), "telegram"
    ) == "澜"


# ---------------------------------------------------------------------------
# ④ 结构性缺席枚举锁（§50「证明缺席且代次>0 与守卫同读」范式）
# ---------------------------------------------------------------------------

#: 逐格判据 = (格子名, 全仓禁止出现的读点标记, 在册理由必须包含的关键词)
_ABSENT_CELLS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("幸运符号", "lucky", ("打卡",)),
    ("群幸运符号", "lucky", ("同上", "打卡")),
    ("网络制式", "network_type", ("无字段",)),
)


def _py_sources() -> list[Path]:
    return [
        path
        for path in PKG.rglob("*.py")
        if "test" not in path.parts and "__pycache__" not in path.parts
    ]


def _literal_read_tokens(tree: ast.Module) -> set[str]:
    """收集**代码里真拿去取值**的字符串常量与属性名，剔除文档串。

    为什么不能直接 grep 全文：本文件的在册理由本身就写着 ``lucky``/「幸运」，
    逐行扫会把「声明它不存在」的那行注释当成读点，锁就永远红在自述上（假阳性）。
    判据换成 AST：只认属性名与非文档串的字面量——那才是「有人拿这个键去取值」。
    """
    doc_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                doc_nodes.add(id(body[0].value))
    tokens: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            tokens.add(node.attr.lower())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in doc_nodes:
                continue
            tokens.add(node.value.lower())
    return tokens


def _read_point_hits(marker: str) -> list[str]:
    token = marker.lower()
    hits: list[str] = []
    for path in _py_sources():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 语法错有专门的门，这里不当读点
            continue
        if any(token in value for value in _literal_read_tokens(tree)):
            hits.append(path.name)
    return hits


@pytest.mark.parametrize("cell,marker,reason_keywords", _ABSENT_CELL_CASES := _ABSENT_CELLS)
def test_structurally_absent_cells_stay_absent_and_stay_explained(
    cell: str, marker: str, reason_keywords: tuple[str, ...]
) -> None:
    """三格「客观没有」必须**同时**成立两件事，任一头掉下来都红：

    A. 全仓源码零读点——不许有人悄悄加了对 ``lucky``/``network_type`` 的取值
       （加了就意味着 docstring 的「结构性没有」变成谎报）；判据走 AST，
       避开「声明它不存在」的自述行本身；
    B. 理由仍在册——``group_info`` 模块 docstring 里必须还能找到这一格的核证线索
       （删了注释就等于把一条被核过的结论降级成「谁都能再判一次死」）。
    """
    assert _read_point_hits(marker) == [], (
        f"{cell}：全仓出现了取值面（标记 {marker}），但 docstring 仍判它「结构性没有」"
    )

    doc = gi.__doc__ or ""
    assert cell in doc, f"{cell}：在册理由被删了——核过的结论不许无声消失"
    segment = doc[doc.index(cell) : doc.index(cell) + 400]
    assert any(word in segment for word in reason_keywords), (
        f"{cell}：理由段找不到核证关键词 {reason_keywords}，等于只留了结论没留依据"
    )


def test_battery_is_no_longer_claimed_structurally_absent() -> None:
    """反向锁：电量曾被误判「没有读的口」，2026-09-28 按动作册更正。

    这条把「旧判」钉成回归面——谁要再把 battery_status 写回「结构性拿不到」清单，
    或者反过来把 ``batteryStatus`` 的读点删掉，两头都会红。
    """
    doc = gi.__doc__ or ""
    assert "batteryStatus" in doc, "电量读口（get_stranger_info.batteryStatus）必须在册可溯"
    assert gi._QQ_META_LABELS["batteryStatus"] == "电量"
    sources = " ".join(
        path.read_text(encoding="utf-8", errors="replace") for path in _py_sources()
    )
    assert "batteryStatus" in sources, "读点被删＝这一格退回「没接」，而注释已说它在册"


# ---------------------------------------------------------------------------
# ⑤ 读件三态：ok / failed / **unprobed**（二批，需求 4「失败不编造」的下半截）
# ---------------------------------------------------------------------------


def _never_called_fetch(*_a: Any, **_k: Any) -> tuple[bool, Any]:
    raise AssertionError("未探测态一次接口都不许打——打了就不是「没去问」")


def test_three_probe_states_are_pairwise_distinct() -> None:
    """三态两两不同名，且 ``unprobed`` 那条**一个请求都不发**。

    回潮判据（打回旧值必被量出来）：把 ``probed`` 的缺省改回「不区分」＝ unprobed
    这一支消失，``qq_meta_probe_state`` 会退回 failed，本用例当场红；
    反过来把未探测也去打接口 ⇒ ``_never_called_fetch`` 抛 AssertionError，也红。
    """
    ok_meta, ok_audit = gi.read_qq_account_meta(
        _fetch_factory({gi.QQ_ACCOUNT_META_ACTION: {"nickname": "澜"}}), "123"
    )
    assert ok_meta and gi.qq_meta_probe_state(ok_audit) == gi.QQ_META_PROBE_OK

    fail_meta, fail_audit = gi.read_qq_account_meta(
        _fetch_factory({}, fail={gi.QQ_ACCOUNT_META_ACTION}), "123"
    )
    assert not fail_meta and gi.qq_meta_probe_state(fail_audit) == gi.QQ_META_PROBE_FAILED

    un_meta, un_audit = gi.read_qq_account_meta(_never_called_fetch, "123", probed=False)
    assert not un_meta and gi.qq_meta_probe_state(un_audit) == gi.QQ_META_PROBE_UNPROBED
    # 「事件没带对象号」同属未探测：那一轮同样没发过任何请求。
    assert gi.qq_meta_probe_state(
        gi.read_qq_account_meta(_never_called_fetch, "")[1]
    ) == gi.QQ_META_PROBE_UNPROBED
    assert len({gi.QQ_META_PROBE_OK, gi.QQ_META_PROBE_FAILED, gi.QQ_META_PROBE_UNPROBED}) == 3


def _peer_message(platform: str, session_id: str, sender: str) -> IncomingMessage:
    return IncomingMessage(
        platform=platform,
        adapter=platform,
        bot_id="10000",
        session_id=session_id,
        session_type=SessionType.PRIVATE,
        sender_id=sender,
        group_id=None,
        plain_text="群资料",
    )


def _cap_without_api():
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.group_cache import (
        GroupInfoCache,
    )

    return gi.build_group_info_capability(api=None, cache=GroupInfoCache())


def test_unprobed_qq_meta_never_becomes_offline() -> None:
    """**本条的正题**：桥未接线时，答案里既不许出现「离线」，也不许假托「接口没答上」。

    为什么单独立一条：``_QQ_STATUS_LABELS`` 里 ``"0" -> "离线"`` 是一枚真标签，
    未探测态一旦被塞进它（或展示层缺省填一个状态），用户读到的就是「对方离线」——
    凭空替真人编出一个他/她没做过的动作。这里用「整格不进答案」做结构锁：
    未探测时 ``在线状态`` 这个标签**一个字都不许出现在正文里**。
    """
    body = _cap_without_api()(_peer_message("qq", "386506762", "386506762"), None).body
    assert gi.QQ_META_UNPROBED_ANSWER in body, "未探测退成了失败态＝谎报一次没发生的请求"
    assert "离线" not in body, f"未探测被写成离线：{body}"
    assert "在线状态" not in body, "未探测态不许产出在线状态这一格（连标签都不许出现）"
    assert "接口这次没答上" not in body, "未探测与失败两态必须分家，不许共用答句"


def test_the_offline_label_is_live_so_the_absence_lock_is_not_vacuous() -> None:
    """非空跑自证：真探测到状态码 0 时「离线」**是会被写出来的**。

    没有这条，上面「body 里不含离线」可能只是因为我压根没登记过离线标签——
    那把锁就锁在空气上。这条把「能写」与「未探测时绝不写」两头同时钉住。
    """
    fetch = _fetch_factory({gi.QQ_ACCOUNT_META_ACTION: {"status": 0}})
    meta, audit = gi.read_qq_account_meta(fetch, "123")
    assert gi.qq_meta_probe_state(audit) == gi.QQ_META_PROBE_OK
    assert meta["在线状态"] == "离线（状态码 0）", "离线标签丢了＝缺席锁变成锁空气"


def test_failed_qq_meta_still_says_the_api_answered_badly() -> None:
    """对照半条：真去问了却问不出来 ⇒ 答句必须是「接口没答上」，不许反过来推给「没接线」。

    只写上面那条的话，把两态一起删光也能绿；这一条钉住「失败态仍然像失败」，
    两合起来才堵死「统一推给一句万金油降级」的偷懒改法。
    """

    class _BadApi:
        def __call__(self, action: str, **params: object) -> object:
            raise TimeoutError("模拟协议端超时")

    from plugins.bot_unified_runtime.domains.chat_reply.runtime.group_cache import (
        GroupInfoCache,
    )

    body = gi.build_group_info_capability(
        api=_BadApi(), cache=GroupInfoCache()
    )(_peer_message("qq", "386506762", "386506762"), None).body
    assert "接口这次没答上" in body
    assert gi.QQ_META_UNPROBED_ANSWER not in body, "真打了接口却答「没去探测」＝反向谎报"
    assert "离线" not in body


def test_telegram_unprobed_leg_shares_the_three_state_wording() -> None:
    """TG 腿同口径：桥未接线时不许说「没查到」，也不许顺手断言在线状态。

    顺带锁住 ``_TG_NO_PRESENCE_LINE`` 那句「接口层面就没有这个数」——TG 的在线格是
    **结构性没有**，与 QQ 的「这轮没探测」是两件事，混成一句就把两种缺口都糊掉了。
    """
    body = _cap_without_api()(_peer_message("telegram", "private_555", "555"), None).body
    assert gi.QQ_META_UNPROBED_ANSWER in body
    assert "不是我没去查" in body, "TG 在线格必须说「结构性没有」，不许被未探测句覆盖"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
