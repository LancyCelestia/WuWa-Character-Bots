"""「细节描写」这一问只能有一个答案（席 na-showalign，2026-10-04；独立复查 B-4／Q4 与 W-2）。

要钉的四件事：

1. **同一个人类可读的问题，同一轮只准一个答案**：`/bot intimate show` 与 `/bot 描写 show`
   都渲染「细节描写：已开/没开」。旧写法让前者读**亲密轴** `source`、后者读**叙述轴**
   `narration_source` ⇒ 她亲手开了亲密、没钉描写时，两句在同一轮里互斥（一句已开一句没开）。
   本件按三个方向各现算一次（本人亲手开亲密＋没钉描写＝同说已开／钉了描写＋没开亲密＝同说
   已开／**全群广播**的亲密＋没钉描写＝同说没开），要求两句**同值**——只钉"同值"守不住
   第三格（两句一起说错也算同值），所以每格都另断一句该说哪个。
2. **改的是报法，不是判定**：两枚取量口的读数与被替换的现场表达式逐值相等 ⇒ 长度地板、
   样式段、出站动作括号豁免、审计 `grant=` 一格都没动（本件立时 H-1 未裁，故取值必须中性；
   H-1＝甲 落地后**中性照旧**——变的只是③格选哪个缺省，两枚取量口仍读同一轮同一个答案）。
   顶格档与 `rp_narration:…:grant=1:nar=scene` 两枚在册锁
   （`tests/test_narration_axis_styles.py`／`tests/test_rp_style_directives.py`）也照旧跑。
3. **拒答文案不许指一条走不通的路**（复查 W-2）：`narration_write_allowed` 群侧只放
   admin/super_admin，而描写钉**按人不按群** ⇒ "得她自己（在群里）或管理员说一句"是谎报。
4. **形状锁（按调用点，不是按集合）**：`grants_intimate_narration(` 在 `plugins/` 的每一处
   都必须喂**命名取量口**，且渲染「细节描写」那一句只准喂叙述口。现有分离锁
   `tests/test_intimate_source_set_separation.py` 只比成员集合，**结构性看不见喂错量**这一族
   ——本件补的就是那一枚瞎眼。护栏写完即空转过多次，所以末段两枚**注毒**用例把改动后的
   副本放进 `%TEMP%`（绝不动源码树）验它必红。

夹具铁律照 `tests/test_narration_axis_command.py`（AGENTS 规则 6／台账 #66★／#76★）：
`shared_reply_policy_store` 指 tmp、`SHARED_CONTENT_ROUTE_ENGINE._sessions` 逐枚换新、
库路径交仓库外 tmp 绝对路径、号全用合成值。
"""
from __future__ import annotations

import ast
import shutil
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    intimate_axis_source,
    narration_ruler_source,
    resolve_narration_axis,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    reply_policy as rp_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
    ReplyPolicyStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import content_route as cr
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    intimate_control as ic,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    INTIMATE_SOURCE_ADMIN_PIN,
    INTIMATE_SOURCE_CONTENT_SIGNAL,
    INTIMATE_SOURCE_MANUAL,
    INTIMATE_SOURCE_MASTER_LOVE,
    INTIMATE_SOURCE_NARRATION_PIN,
    INTIMATE_SOURCE_NONE,
    INTIMATE_TIER_L2,
    MODE_INTIMATE,
    SHARED_CONTENT_ROUTE_ENGINE,
    grants_intimate_narration,
    member_session_key,
    resolve_intimate_context,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    build_session_key,
    group_scope_key,
    private_session_key,
)

_PLUGINS_DIR = Path(__file__).resolve().parents[1] / "plugins"
_ADDR_DB = "showalign_addressing.sqlite3"
_HER = "9600002261"
_GROUP = "700000226"
_PHRASE = "细节描写："
_NARR = "narration_ruler_source"
_INT = "intimate_axis_source"


# ---------------------------------------------------------------- 夹具


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(SHARED_CONTENT_ROUTE_ENGINE, "_sessions", OrderedDict())
    store = ReplyPolicyStore(tmp_path / "reply_policy.sqlite3")
    monkeypatch.setattr(rp_module, "shared_reply_policy_store", lambda _config: store)
    with cr._MARKS_WRITTEN_LOCK:
        cr._MARKS_WRITTEN_BY_THIS_PROCESS.clear()


def _addr_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_addressing_preferences_db_path=str(tmp_path / _ADDR_DB),
        bot_reply_policy_person_aliases={},
        bot_content_route_enabled=True,
        bot_content_route_model="grok-4.6",
        bot_content_route_order="grok-4.6,gemini-3.8-flash",
        bot_content_route_words="",
        bot_content_route_intimate_threshold=60.0,
        bot_content_route_normal_threshold=25.0,
        bot_content_route_context_turns=4,
        bot_content_route_max_ttl_minutes=120.0,
        bot_content_route_idle_reset_minutes=10.0,
        bot_content_route_intimate_ttl_minutes=60.0,
        bot_content_route_group_per_user_enabled=True,
        bot_content_route_group_whitelist=[_GROUP],
        bot_content_route_group_blacklist=[],
        bot_content_route_private_whitelist=[],
        bot_content_route_private_blacklist=[],
        bot_content_route_l1_auto_enabled=False,
        bot_content_route_l1_auto_min_tier=1,
        bot_master_love_enabled=False,
        bot_master_love_admins=[],
        bot_reply_policy_enabled=True,
        bot_reply_detail="detail",
    )


def _group_ctx(cfg: SimpleNamespace, sender: str = _HER) -> dict[str, Any]:
    return resolve_intimate_context(
        SHARED_CONTENT_ROUTE_ENGINE,
        session_type="group",
        group_id=_GROUP,
        sender_id=sender,
        session_key=build_session_key(_GROUP, sender),
        config=cfg,
    )


def _private_ctx(cfg: SimpleNamespace, sender: str = _HER) -> dict[str, Any]:
    return resolve_intimate_context(
        SHARED_CONTENT_ROUTE_ENGINE,
        session_type="private",
        group_id="",
        sender_id=sender,
        session_key=private_session_key(sender),
        config=cfg,
    )


def _intimate_show(cfg: SimpleNamespace, *, group: bool) -> str:
    kwargs: dict[str, Any] = {
        "config": cfg,
        "request_id": f"req-showalign-{_HER}",
        "subcommand": "show",
        "session_type": "group" if group else "private",
        "group_id": _GROUP if group else "",
        "sender_id": _HER,
        "sender_roles": ["user", "admin"],
        "session_key": build_session_key(_GROUP, _HER) if group else private_session_key(_HER),
    }
    return ic.build_intimate_control_result(**kwargs).body


def _narration_show(cfg: SimpleNamespace, *, group: bool) -> str:
    kwargs: dict[str, Any] = {
        "config": cfg,
        "request_id": f"req-showalign-{_HER}",
        "subcommand": "show",
        "session_type": "group" if group else "private",
        "group_id": _GROUP if group else "",
        "sender_id": _HER,
        "sender_roles": ["user", "admin"],
        "session_key": build_session_key(_GROUP, _HER) if group else private_session_key(_HER),
    }
    return ic.build_narration_control_result(**kwargs).body


def _verdict_line(body: str, label: str) -> str:
    hits = [line for line in body.splitlines() if line.startswith(label)]
    assert hits, f"回执里没有「{label}」这一格：{body!r}"
    assert len(hits) == 1, f"「{label}」渲染了两遍：{hits}"
    return hits[0]


# ================================================================ ① 两句「细节描写」同值


def test_intimate_axis_granting_on_own_key_opens_the_narration_slot(
    tmp_path: Path,
) -> None:
    """甲向：本人亲手开的亲密档＋描写轴没钉 ⇒ 两句都必须说「已开」。

    方向按 **H-1＝甲**（2026-10-04 晚「开'亲密'的话，就给 scene 场景」）定：本件初稿写于
    该裁定之前、当时要求两句同说「没开」，**要钉的那件事从来是"同值"而不是"没开"**——
    所以她那句裁定落地后，这里翻向「已开」，而"两句互斥必红"那一条判据一字未动。
    这正是她今晚就会撞上的那一格：`/bot intimate on` 之后不改任何状态，先问一次
    `/bot intimate show`、再问一次 `/bot 描写 show`。两句一个已开一个没开＝本件红。

    ⚠ 这一支钉落在**她本人的成员派生键**上（`member_session_key`）＝私聊/群里她自己开口
    那一路；全群广播那一桶另见 `test_group_broadcast_intimate_does_not_open_it`。
    """
    cfg = _addr_config(tmp_path)
    SHARED_CONTENT_ROUTE_ENGINE.apply_manual(
        member_session_key(build_session_key(_GROUP, _HER), _HER),
        MODE_INTIMATE,
        cfg,
        source=INTIMATE_SOURCE_MANUAL,
        tier=INTIMATE_TIER_L2,
    )
    ctx = _group_ctx(cfg)
    assert grants_intimate_narration(str(ctx.get("source") or "")) is True, ctx
    assert grants_intimate_narration(str(ctx.get("narration_source") or "")) is True, ctx
    assert str(ctx.get("narration_mode") or "") == cr.NARRATION_MODE_SCENE, ctx

    intimate_line = _verdict_line(_intimate_show(cfg, group=True), _PHRASE)
    narration_line = _verdict_line(_narration_show(cfg, group=True), _PHRASE)
    assert intimate_line == narration_line, (
        "同一个问题两个答案："
        f"`/bot intimate show`＝{intimate_line!r}，`/bot 描写 show`＝{narration_line!r}"
    )
    assert "已开" in intimate_line, f"她自己开了亲密却报没开：{intimate_line!r}"


def test_group_broadcast_intimate_does_not_open_it(tmp_path: Path) -> None:
    """G-3 的另一句「别人找你依旧是 speech」：全群那一桶开的亲密，**不**把描写轴带上去。

    管理员/超管拨的是「开关二＝全群生效」，裁决出自 `group:<gid>` 那把没有本人段的桶；
    ③ 格（开亲密即缺省 scene）若照这一路交出去，等于替全群每个没开过口的人做了主。
    两句在这里必须同说「没开」＝同值判据在这一格的反向腿（只钉同值守不住这一格）。
    """
    cfg = _addr_config(tmp_path)
    SHARED_CONTENT_ROUTE_ENGINE.apply_manual(
        group_scope_key(build_session_key(_GROUP, _HER)),
        MODE_INTIMATE,
        cfg,
        source=INTIMATE_SOURCE_ADMIN_PIN,
        tier=INTIMATE_TIER_L2,
    )
    ctx = _group_ctx(cfg)
    assert bool(ctx.get("eligible")) is True, ctx
    assert str(ctx.get("mode") or "") == MODE_INTIMATE, ctx  # 亲密档：全群照吃
    assert grants_intimate_narration(str(ctx.get("narration_source") or "")) is False, ctx
    assert str(ctx.get("narration_mode") or "") == cr.NARRATION_MODE_SPEECH, ctx

    intimate_line = _verdict_line(_intimate_show(cfg, group=True), _PHRASE)
    narration_line = _verdict_line(_narration_show(cfg, group=True), _PHRASE)
    assert intimate_line == narration_line, (
        f"同一个问题两个答案：亲密面＝{intimate_line!r}，描写面＝{narration_line!r}"
    )
    assert "没开" in narration_line, f"全群广播把描写档开了：{narration_line!r}"


def test_narration_pin_grants_even_without_the_intimate_axis(tmp_path: Path) -> None:
    """乙向（镜像）：钉了 scene、从没开过亲密 ⇒ 两句都必须说「已开」（G-1 的原话面）。"""
    cfg = _addr_config(tmp_path)
    assert cr.write_narration_pin(
        private_session_key(_HER), mode=cr.NARRATION_MODE_SCENE, config=cfg
    ) is True
    ctx = _private_ctx(cfg)
    assert grants_intimate_narration(str(ctx.get("source") or "")) is False, ctx
    assert str(ctx.get("narration_source") or "") == INTIMATE_SOURCE_NARRATION_PIN, ctx

    intimate_line = _verdict_line(_intimate_show(cfg, group=False), _PHRASE)
    narration_line = _verdict_line(_narration_show(cfg, group=False), _PHRASE)
    assert intimate_line == narration_line, (
        f"同一个问题两个答案：亲密面＝{intimate_line!r}，描写面＝{narration_line!r}"
    )
    assert "已开" in intimate_line, f"钉了 scene 却报没开：{intimate_line!r}"


def test_intimate_show_still_reports_the_intimate_axis_under_its_own_name(tmp_path: Path) -> None:
    """报法改了、值没丢：亲密轴那一问照旧在场，只是换了名字（不许悄悄删格）。"""
    cfg = _addr_config(tmp_path)
    SHARED_CONTENT_ROUTE_ENGINE.apply_manual(
        member_session_key(build_session_key(_GROUP, _HER), _HER),
        MODE_INTIMATE,
        cfg,
        source=INTIMATE_SOURCE_ADMIN_PIN,
        tier=INTIMATE_TIER_L2,
    )
    ctx = _group_ctx(cfg)
    body = _intimate_show(cfg, group=True)
    own = _verdict_line(body, "亲密档带来的描写：")
    assert ("已开" if grants_intimate_narration(str(ctx.get("source") or "")) else "没开") in own
    assert own != _verdict_line(body, _PHRASE) or grants_intimate_narration(
        str(ctx.get("source") or "")
    ) == grants_intimate_narration(str(ctx.get("narration_source") or ""))


# ================================================================ ② 判定一字未动（H-1 中性）


@pytest.mark.parametrize(
    ("intimate_src", "nar_src", "nar_mode"),
    [
        (INTIMATE_SOURCE_MANUAL, INTIMATE_SOURCE_NONE, cr.NARRATION_MODE_SPEECH),
        (INTIMATE_SOURCE_ADMIN_PIN, INTIMATE_SOURCE_NONE, cr.NARRATION_MODE_SPEECH),
        (INTIMATE_SOURCE_CONTENT_SIGNAL, INTIMATE_SOURCE_NONE, cr.NARRATION_MODE_SPEECH),
        (INTIMATE_SOURCE_MASTER_LOVE, INTIMATE_SOURCE_NONE, cr.NARRATION_MODE_SPEECH),
        (INTIMATE_SOURCE_NONE, INTIMATE_SOURCE_NARRATION_PIN, cr.NARRATION_MODE_SCENE),
        (INTIMATE_SOURCE_MASTER_LOVE, INTIMATE_SOURCE_NARRATION_PIN, cr.NARRATION_MODE_SCENE),
        (INTIMATE_SOURCE_MANUAL, INTIMATE_SOURCE_NARRATION_PIN, cr.NARRATION_MODE_SCENE),
        (INTIMATE_SOURCE_NONE, INTIMATE_SOURCE_NONE, cr.NARRATION_MODE_SPEECH),
    ],
)
def test_accessors_are_value_identical_to_the_replaced_expressions(
    intimate_src: str, nar_src: str, nar_mode: str
) -> None:
    """取量口与被替换掉的现场表达式**逐值相等** ⇒ 地板/样式/括号豁免/审计 grant= 全不变。

    这一枚是 H-1 中性的证明：本席没有把"开了亲密"当成"拿到了铺开写"，也没有反过来。
    """
    ctx: dict[str, Any] = {
        "mode": MODE_INTIMATE if intimate_src else "normal",
        "source": intimate_src,
        "narration_mode": nar_mode,
        "narration_source": nar_src,
    }
    assert grants_intimate_narration(intimate_axis_source(ctx)) is grants_intimate_narration(
        str(ctx.get("source", ""))
    )
    assert grants_intimate_narration(narration_ruler_source(ctx)) is grants_intimate_narration(
        str(ctx.get("narration_source", "") or "")
    )
    axis = resolve_narration_axis(ctx)
    assert axis.granted is grants_intimate_narration(narration_ruler_source(ctx))
    assert axis.mode == (
        cr.NARRATION_MODE_SCENE
        if nar_mode == cr.NARRATION_MODE_SCENE and axis.granted
        else cr.NARRATION_MODE_SPEECH
    )


def test_granted_scene_turn_still_reaches_the_intimate_length_floor(tmp_path: Path) -> None:
    """F-2 承重：拿到授予且本轮 `scene` 的那一轮，地板腿仍要**升格**（否则长句变短句）。"""
    cfg = _addr_config(tmp_path)
    SHARED_CONTENT_ROUTE_ENGINE.apply_manual(
        member_session_key(build_session_key(_GROUP, _HER), _HER),
        MODE_INTIMATE,
        cfg,
        source=INTIMATE_SOURCE_MANUAL,
        tier=INTIMATE_TIER_L2,
    )
    assert cr.write_narration_pin(
        private_session_key(_HER), mode=cr.NARRATION_MODE_SCENE, config=cfg
    ) is True
    ctx = _group_ctx(cfg)
    ctx = dict(ctx)
    ctx["narration_mode"] = cr.NARRATION_MODE_SCENE
    ctx["narration_source"] = INTIMATE_SOURCE_NARRATION_PIN
    axis = resolve_narration_axis(ctx)
    assert axis.mode == cr.NARRATION_MODE_SCENE and axis.granted is True, ctx
    for detail in ("brief", "moderate", "detail"):
        assert chat.intimate_reply_length_tier(detail, "在吗") != chat.resolve_reply_length_tier(
            detail, "在吗"
        ), f"地板腿在 detail={detail!r} 上不再升格＝她的长句会被吃回短句"
    top_id = chat._REPLY_TIER_TOP_ID
    assert chat.intimate_reply_length_tier("brief", "在吗") == top_id, (
        "授予轮没落到登记表顶格档"
    )
    assert chat.REPLY_LENGTH_TIERS[top_id].min_chars >= 600, "F-2 的地板（600 字起）不在了"


# ================================================================ ③ 拒答文案不指死路（W-2）


def test_group_refusal_points_only_at_the_path_that_actually_works(tmp_path: Path) -> None:
    """群里普通成员被拒时，回执只能指**真走得通**的那条路（规则 8：不谎报）。

    旧句「要它，得她自己或管理员说一句」两条都不通：群侧本人再说一次仍被
    `narration_write_allowed` 拒；描写钉按人不按群，管理员在群里也只钉得住自己那一格。
    """
    cfg = _addr_config(tmp_path)
    refused = ic.build_narration_control_result(
        config=cfg,
        request_id="req-showalign-refused",
        subcommand="scene",
        session_type="group",
        session_key=build_session_key(_GROUP, _HER),
        group_id=_GROUP,
        sender_id=_HER,
        sender_roles=["user"],
    )
    assert "slash_narration_refused" in (refused.audit_tags or []), refused
    assert ic.NARRATION_REFUSED_REPLY in refused.body, refused.body
    assert "narration_pin" not in refused.body
    assert "得她自己" not in refused.body, "仍旧承诺了群里那条死路"
    # 指的这条路真的能落钉：本人非群侧不吃角色门。
    private = ic.build_narration_control_result(
        config=cfg,
        request_id="req-showalign-selfhelp",
        subcommand="scene",
        session_type="private",
        session_key=private_session_key(_HER),
        group_id="",
        sender_id=_HER,
        sender_roles=["user"],
    )
    assert "slash_narration_refused" not in (private.audit_tags or []), private
    assert cr.read_narration_pin(private_session_key(_HER), config=cfg) == (
        cr.NARRATION_MODE_SCENE
    )
    assert "管理员" not in ic.NARRATION_REFUSED_REPLY, ic.NARRATION_REFUSED_REPLY


# ================================================================ ④ 形状锁（按调用点）


def _func_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _grant_calls(tree: ast.AST) -> list[ast.Call]:
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _func_name(node.func) == "grants_intimate_narration":
            out.append(node)
    return out


def _accessor_of(call: ast.Call) -> str:
    if not call.args:
        return "<无参>"
    arg = call.args[0]
    name = _func_name(arg.func) if isinstance(arg, ast.Call) else ""
    if name in {_NARR, _INT}:
        return name
    return f"<现场取数 {name or type(arg).__name__}>"


def _scan_provenance(root: Path) -> list[str]:
    """每一处判据都必须喂**命名取量口**（现场拼量＝下一席无从分辨问的是哪道题）。"""
    bad: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for call in _grant_calls(tree):
            if _accessor_of(call) not in {_NARR, _INT}:
                bad.append(f"{path.name}:{call.lineno} 喂的是 {_accessor_of(call)}")
    return bad


#: 名册：哪个文件里有几处问哪道题（新增调用点＝先在这儿登记"它答的是哪一问"）。
_CENSUS: dict[str, dict[str, int]] = {
    "chat.py": {_NARR: 1, _INT: 2},
    "intimate_control.py": {_NARR: 1, _INT: 1},
}
#: 两处 `show` 面（`/bot intimate` 与 `/bot 描写`）各自调用共用渲染口一次。
_RENDER_CONSUMERS = 2


def _scan_census(root: Path) -> list[str]:
    tally: dict[str, dict[str, int]] = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for call in _grant_calls(tree):
            tally.setdefault(path.name, {}).setdefault(_accessor_of(call), 0)
            tally[path.name][_accessor_of(call)] += 1
    bad: list[str] = []
    for name, expect in _CENSUS.items():
        got = tally.pop(name, {})
        if got != expect:
            bad.append(f"{name} 调用点名册分叉：期望 {expect}，现算 {got}")
    for name, got in tally.items():
        bad.append(f"{name} 出现了未登记的判据调用 {got}")
    return bad


_RENDER_HELPER = "_narration_grant_line"


def _renders_phrase(node: ast.AST) -> bool:
    """该函数体内是否**渲染**「细节描写」那一句（docstring 里提到这四个字不算）。"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.JoinedStr) and sub.values:
            head = sub.values[0]
            if isinstance(head, ast.Constant) and str(head.value).startswith(_PHRASE):
                return True
    return False


def _scan_phrase_ownership(root: Path) -> list[str]:
    """「细节描写」这一句只准有一处字面、只准问叙述轴，且两处 `show` 面共用它。

    旧病根＝同一个人类可读的名字在两处渲染、各喂一枚量 ⇒ 同一轮两个答案。现在字面只有
    一份（共用渲染口，顺带过 `tests/test_copy_single_source.py` 那门），并且渲染口内部
    不许出现亲密量；两处 `show` 各自调它一次（少一处＝有人把这一格删了或另写一句）。
    """
    bad: list[str] = []
    renderers = 0
    consumed = 0
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and _renders_phrase(node):
                renderers += 1
                for call in _grant_calls(node):
                    if _accessor_of(call) != _NARR:
                        bad.append(
                            f"{path.name}:{call.lineno} 渲染「{_PHRASE}」的函数里出现了 "
                            f"{_accessor_of(call)}（同一句话只准一个量）"
                        )
            if isinstance(node, ast.Call) and _func_name(node.func) == _RENDER_HELPER:
                consumed += 1
                bad.extend(
                    f"{path.name}:{node.lineno} 「{_RENDER_HELPER}」被现场喂了非叙述轴"
                    for arg in node.args
                    if not (isinstance(arg, ast.Name))
                )
    if consumed != _RENDER_CONSUMERS:
        bad.append(
            f"{_RENDER_HELPER} 应有恰好 {_RENDER_CONSUMERS} 处调用（两处 show 面各一次），"
            f"现算 {consumed} 处"
        )
    if renderers != 1:
        bad.append(f"「{_PHRASE}」的字面应有恰好一处渲染口，现算 {renderers} 处")
    return bad


def _scan_accessor_bodies(root: Path) -> list[str]:
    """两枚取量口各自只看一枚键、且**互不相同**（取量口被改指向对方的量＝静默并轴）。"""
    want = {_NARR: "narration_source", _INT: "source"}
    found: dict[str, int] = {_NARR: 0, _INT: 0}
    bad: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef) and node.name in want):
                continue
            found[node.name] += 1
            if path.name != "chat.py":
                bad.append(f"{path.name}:{node.lineno} {node.name} 定义不在 chat.py")
            keys = {
                str(call.args[0].value)
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "get"
                and call.args
                and isinstance(call.args[0], ast.Constant)
            }
            if keys != {want[node.name]}:
                bad.append(
                    f"{path.name}:{node.lineno} {node.name} 读了 {sorted(keys)}，"
                    f"应只读 {{'{want[node.name]}'}}"
                )
    for name, count in found.items():
        if count != 1:
            bad.append(f"{name} 应有恰好一处定义，现算 {count} 处")
    return bad


def _scan_all(root: Path) -> list[str]:
    return [
        *_scan_provenance(root),
        *_scan_census(root),
        *_scan_phrase_ownership(root),
        *_scan_accessor_bodies(root),
    ]


def test_shape_lock_is_green_on_the_source_tree() -> None:
    assert _CENSUS["chat.py"][_INT] == 2, "审计 grant= 与样式段键共用亲密量＝两处，多一处就是并轴"
    assert _scan_all(_PLUGINS_DIR) == []


def test_shape_lock_goes_red_when_a_show_surface_asks_the_intimate_axis(
    tmp_path: Path,
) -> None:
    """注毒①（护栏不空转的自证）：把 intimate show 那句换回亲密量 ⇒ 必红。"""
    work = tmp_path / "plugins"
    work.mkdir()
    src_dir = _PLUGINS_DIR / "bot_unified_runtime" / "domains" / "chat_reply"
    shutil.copy(src_dir / "capabilities" / "chat.py", work / "chat.py")
    target = work / "intimate_control.py"
    original = (src_dir / "runtime" / "intimate_control.py").read_text(encoding="utf-8")
    # 锚在**赋值行**上：docstring 里也写着这两个名字，只按名字替换会换成一句注释而
    # 判定行原样在场（失效形态 247＝注毒腿自己空跑，护栏看着红过其实没红）。
    anchor = f"granted = grants_intimate_narration({_NARR}(ctx))"
    swapped = f"granted = grants_intimate_narration({_INT}(ctx))"
    poisoned = original.replace(anchor, swapped, 1)
    assert poisoned != original, "注毒没落到任何一处＝本件空跑"
    renderer_calls = [
        _accessor_of(call)
        for node in ast.walk(ast.parse(poisoned))
        if isinstance(node, ast.FunctionDef) and node.name == ic._narration_grant_line.__name__
        for call in _grant_calls(node)
    ]
    assert renderer_calls == [_INT], f"注毒没改到渲染口的判定行：{renderer_calls}"
    target.write_text(poisoned, encoding="utf-8")
    hits = _scan_all(work)
    assert any(_PHRASE in line for line in hits), hits
    assert any("名册分叉" in line for line in hits), hits


def test_shape_lock_goes_red_when_a_site_reassembles_the_quantity_on_the_spot(
    tmp_path: Path,
) -> None:
    """注毒②：调用处现场拼量（旧写法）⇒ 取量口那一条腿必红。"""
    work = tmp_path / "plugins"
    work.mkdir()
    src = (
        _PLUGINS_DIR
        / "bot_unified_runtime"
        / "domains"
        / "chat_reply"
        / "capabilities"
        / "chat.py"
    )
    original = src.read_text(encoding="utf-8")
    poisoned = original.replace(
        f"granted = grants_intimate_narration({_NARR}(ctx))",
        'granted = grants_intimate_narration(str(ctx.get("narration_source", "") or ""))',
        1,
    )
    assert poisoned != original, "注毒没落到任何一处＝本件空跑"
    (work / "chat.py").write_text(poisoned, encoding="utf-8")
    hits = _scan_provenance(work)
    assert any("现场取数" in line for line in hits), hits
