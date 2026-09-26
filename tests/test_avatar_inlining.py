"""卡片头像必须是「浏览器真能加载的形态」——三把锁（S-T-AVATAR-1R，2026-09-26）。

缺陷（看护员 Playwright 独立复现，本席另自证一遍，读数见
``.superpowers/sdd/2026-09-25-goal18-wave/logs/S-T-AVATAR-1R.md``）：卡片走
``render_backends`` 的 ``page.set_content(html)`` 装页，该页 ``location.origin``
是 ``null``，Chromium 在这种 origin 下**拒收 ``file://`` 子资源**——不抛异常、
console 无错、``img.complete`` 仍为 True 而 ``naturalWidth`` 归 0，且胶囊件的
``onerror="this.style.display='none'"`` 会把图整枚 hide 掉，连「守」字圆点都
不触发 ⇒ 用户看到的「左上角头像成了空白占位」。

三把锁一一对应任务书 §2(c)：

① **渲染输入里出现 ``file:///`` 即红**——两条腿：行为腿（闸对任意输入的输出
   只能是 ``data:image/`` / ``http(s)://`` / 空串三态；真渲四张卡面后逐枚扫
   ``<img src>``）+ 静态腿（渲染层除内部槽位文件外不许再产 ``as_uri()``；
   身份登记面在**生产侧零调用点**，否则 ``bot_identity`` 的透传腿就有了载体）。
② **本地存在头像时出口以 ``data:image/`` 开头**——三条公开出口 + base64 往返
   等值（证明交出去的就是那个文件）+ MIME 由魔数定 + 编码后体积上限。
③ **缺文件时是兜底形态而非空串**——模块层回空串是**信号**，本锁钉的是「空串
   经真 DOM 生成件产出圆点腿、且绝不产出 ``src=""`` 或 ``src="file:…"`` 的碎图」
   （兜底形态住在模板/胶囊里；在模块层复制一份圆点文案＝第二真身，禁）。

全离线：纯字符串 / 真 Jinja 渲染 / PIL 造图 / AST 扫描，不依赖 playwright、
不联网、不碰 ``ChatBot_Runtime``。
"""

from __future__ import annotations

import ast
import asyncio
import base64
import io
import random
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.render import bot_avatar
from plugins.bot_unified_runtime.domains.render import templates as fstring_templates
from plugins.bot_unified_runtime.domains.render.card_render import bridge, mica_shell

_PERSONA = "守岸人"
# 只满足 PNG 魔数的最小载荷：闸门认魔数不认后缀，本文件多数用例不需要真图。
_PNG = b"\x89PNG\r\n\x1a\n" + b"seat-avt1r-payload"
_JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-payload"
_GIF = b"GIF89a" + b"gif-payload"

_IMG_SRC_RE = re.compile(r'<img\b[^>]*?\bsrc="([^"]*)"', re.IGNORECASE)
_RENDER_PLUGINS_ROOT = Path(bot_avatar.__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 夹具与小工具
# ---------------------------------------------------------------------------


@pytest.fixture()
def _clean(monkeypatch: pytest.MonkeyPatch):
    """隔离本模块全部进程级状态：单实例槽位、负结果 TTL、内联缓存、AVT1 两槽位。"""
    monkeypatch.setattr(bot_avatar, "_LOCAL_AVATAR_URI", "")
    monkeypatch.setattr(bot_avatar, "_DISCOVER_MISS_TS", {})
    monkeypatch.setattr(bot_avatar, "_AVATAR_INLINE_CACHE", {})
    monkeypatch.setattr(bot_avatar, "_IDENTITY_REGISTRY", {})
    monkeypatch.setattr(bot_avatar, "_IDENTITY_RESOLVER", None)


def _cfg(tmp_path: Path, *, avatar_url: str = "") -> SimpleNamespace:
    """读取面用到的最小 config 替身（与 tests/test_bot_avatar.py 同形）。"""
    return SimpleNamespace(
        bot_persona_avatar_url=avatar_url,
        bot_runtime_data_dir=str(tmp_path),
        bot_persona_display_name=_PERSONA,
    )


def _make_avatar(tmp_path: Path, name: str = "bot_10000.png") -> Path:
    """按生产落盘命名（``avatar/bot_<qq>.png``）造一枚本地头像。"""
    target = tmp_path / "avatar" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_PNG)
    return target


def _is_renderable(value: str) -> bool:
    """渲染输入的唯一判据：三种能加载的形态之一（或空串＝圆点信号）。"""
    return (
        value == ""
        or value.startswith(("data:image/", "http://", "https://"))
    )


def _b64_payload(data_uri: str) -> str:
    assert ";base64," in data_uri, f"非 base64 形态的 data URI：{data_uri[:40]!r}"
    return data_uri.split(";base64,", 1)[1]


def _img_srcs(html: str) -> list[str]:
    return _IMG_SRC_RE.findall(html)


def _assert_card_html_avatar_is_renderable(html: str, *, face: str) -> None:
    """一张卡面上每一枚 ``<img src>`` 都必须能加载；碎形态一律红。"""
    for src in _img_srcs(html):
        assert _is_renderable(src) and src, f"{face} 把不可渲染的 src 交给了卡片：{src[:60]!r}"
    assert "file://" not in html, f"{face} 的 HTML 里出现了裸 file URI"
    # 空 src 同样是碎图（img 在场但永远不亮，圆点腿也不会触发）。
    assert 'src=""' not in html, f"{face} 渲染出了 src 为空的碎图"


def _call_names(tree: ast.AST) -> set[str]:
    """AST 里出现的**被调用名**（含 ``a.b()`` 的尾段），只用于静态扫描。"""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            found.add(func.id)
        elif isinstance(func, ast.Attribute):
            found.add(func.attr)
    return found


def _python_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


# ---------------------------------------------------------------------------
# 锁① 之行为腿：闸门对**任意**输入只出三态（含 hostile 形态全扫）
# ---------------------------------------------------------------------------


def test_gate_output_is_always_one_of_three_renderable_forms(_clean, tmp_path) -> None:
    """任意入参过闸，出口只能是 ``data:image/`` / ``http(s)://`` / 空串。

    这条是「不许静默空白」的正面表述：碎形态（裸 ``file:``、裸盘符路径、
    非图片 MIME 的 ``data:``、别的 scheme、目录、0 字节、文本冒充 .png）
    一律被降级成空串，由卡片回落圆点——绝不让一个加载必败的值出门。
    """
    good = _make_avatar(tmp_path)
    empty_png = tmp_path / "avatar" / "bot_2.png"
    empty_png.write_bytes(b"")
    fake_text_png = tmp_path / "avatar" / "bot_3.png"
    fake_text_png.write_text("这是文本不是图", encoding="utf-8")

    cases: list[tuple[str, object]] = [
        ("空串", ""),
        ("纯空白", "   "),
        ("None", None),
        ("整数", 12345),
        ("Path 对象", good),
        ("真实文件的裸路径", str(good)),
        ("真实文件的 file URI", good.as_uri()),
        ("file://localhost 形态", f"file://localhost{good.as_uri()[5:]}"),
        ("读不到的 file URI", "file:///nope/nothere.png"),
        ("读不到的裸路径", "C:\\nope\\nothere.png"),
        ("0 字节文件", str(empty_png)),
        ("文本冒充 .png", str(fake_text_png)),
        ("目录当文件", str(good.parent)),
        ("已内联的 data:image 幂等", "data:image/png;base64,AAAA"),
        ("非图片 MIME 的 data:", "data:text/html;base64,PGI+"),
        ("http 远程", "http://example.com/a.png"),
        ("https 远程", "https://example.com/a.png"),
        ("ftp scheme", "ftp://example.com/a.png"),
        (" UNC 路径", "\\\\nas\\share\\a.png"),
        ("相对路径", "avatar/nope.png"),
        ("查询串形态 file", f"{good.as_uri()}?x=1"),
    ]
    for label, value in cases:
        out = bot_avatar.inline_avatar_uri(value)
        assert isinstance(out, str), f"{label}：出口不是字符串"
        assert _is_renderable(out), f"{label} 的出口不可渲染：{out[:60]!r}"
        assert not out.startswith("file:"), f"{label}：把 file URI 交给了卡片"
        assert not re.match(r"^[A-Za-z]:[\\/]", out), f"{label}：把裸盘符路径交给了卡片"
        if out.startswith("data:"):
            assert out.startswith("data:image/"), f"{label}：非图片 MIME 漏过闸门"

    # 真文件这一支必须真的出门（否则上面全空串也「通过」＝假绿）。
    assert bot_avatar.inline_avatar_uri(str(good)).startswith("data:image/png;base64,")


def test_non_image_data_uri_is_rejected_by_gate(_clean, tmp_path) -> None:
    """``data:`` 透传只认 ``data:image/``（本席收紧的一处，真身 docstring 早这么写）。

    收紧前的代码放行任意 ``data:``，与 ``bot_avatar.py`` 头部自述的「出口只可能是
    ``data:image/…`` / ``http(s)://…`` / 空串」直接矛盾——注释是真值、代码不是。
    """
    assert bot_avatar.inline_avatar_uri("data:image/png;base64,AAAA") == (
        "data:image/png;base64,AAAA"
    )
    for hostile in ("data:text/html;base64,PGI+", "data:,plain", "application/json"):
        assert bot_avatar.inline_avatar_uri(hostile) == "", f"漏过闸门：{hostile!r}"


# ---------------------------------------------------------------------------
# 锁① 之行为腿 2：真渲四张卡面，HTML 里逐枚 img 过判据
# ---------------------------------------------------------------------------


def test_rendered_card_faces_contain_no_file_uri(_clean, tmp_path) -> None:
    """头像从磁盘到卡片 HTML 的全程不收口则必漏；这里把四张真卡面摊开扫。

    四张面=她点名的「一处缺陷同时打空多张卡」的代表：Jinja 通用卡、Jinja
    诊断卡（``{% else %}`` 圆点腿）、f-string 直拼媒体卡、品牌胶囊组件本体。
    """
    good = _make_avatar(tmp_path)
    avatar = bot_avatar.bot_avatar_uri(_cfg(tmp_path))
    assert avatar.startswith("data:image/png;base64,")

    faces = {
        "universal(Jinja)": bridge.render_universal_card_html({"bot_avatar_url": avatar}),
        "error(Jinja)": bridge.render_error_card_html({"bot_avatar_url": avatar}),
        "media(f-string)": fstring_templates.render_media_card_html(
            {"bot_avatar_url": avatar, "title": "样张"}
        ),
        "capsule(component)": mica_shell.brand_capsule_html(
            bot_name=_PERSONA, avatar_url=avatar
        ),
    }
    for face, html in faces.items():
        assert html.strip(), f"{face} 渲染为空"
        _assert_card_html_avatar_is_renderable(html, face=face)
        assert "data:image/png;base64," in html, f"{face} 没把头像带进 HTML（磁盘明明有图）"
    # 反向自证：把碎形态硬灌进同一批面，判据必须红（不然上面是空跑）。
    poisoned = mica_shell.brand_capsule_html(avatar_url=good.as_uri())
    assert "file://" in poisoned and _img_srcs(poisoned)[0].startswith("file:")


def test_payload_with_broken_avatar_is_the_bypass_this_gate_exists_to_stop(
    _clean, tmp_path
) -> None:
    """能力侧若绕过闸门（旧行为：直接 ``as_uri()``），卡面立刻出现碎图。

    这条不修任何东西，只把「绕过=什么后果」钉成读数，给 ① 的静态腿作地基：
    ``bridge`` 只是透传 payload，判据必须落在**生产注入点已过闸**上。
    """
    good = _make_avatar(tmp_path)
    broken = bridge.render_universal_card_html({"bot_avatar_url": good.as_uri()})
    assert "file://" in broken
    assert _img_srcs(broken)[0].startswith("file:///")
    # 同一枚文件走闸门后注入，同一张卡面即自愈。
    fixed = bridge.render_universal_card_html(
        {"bot_avatar_url": bot_avatar.inline_avatar_uri(good.as_uri())}
    )
    _assert_card_html_avatar_is_renderable(fixed, face="universal(经闸门)")


# ---------------------------------------------------------------------------
# 锁① 之静态腿：第二真身与旁路载体都不许出现
# ---------------------------------------------------------------------------


def test_render_layer_produces_no_file_uri_outside_internal_slots() -> None:
    """渲染层只有 ``bot_avatar.py`` 允许出现 ``as_uri()``（那是内部槽位形态）。

    为什么判 ``as_uri()`` 而不是判字面量 ``file://``：缺陷的**产生式**就是
    ``Path.as_uri()``（HEAD 版四处：``:99/:112/:165/:242``）。谁在渲染层的别的
    文件里再造一枚，就是开了第二条没闸的口。
    """
    render_root = Path(bot_avatar.__file__).resolve().parent
    offenders: list[str] = []
    for path in _python_files(render_root):
        if path.name == "bot_avatar.py":
            continue
        if "as_uri" in _call_names(ast.parse(path.read_text(encoding="utf-8"))):
            offenders.append(str(path.relative_to(_RENDER_PLUGINS_ROOT)))
    assert offenders == [], f"渲染层出现第二处 file URI 产生式：{offenders}"


def test_identity_registration_face_has_no_production_caller_yet(_clean, tmp_path) -> None:
    """``bot_identity`` 的登记值透传腿今天**没有生产载体**（H2 活性围栏）。

    现算实况：``bot_identity()`` 在登记值读不到时**原样返回**（AVT1 ⑤
    「登记什么读出什么」，被 ``tests/test_bot_avatar.py::
    test_registered_value_that_cannot_be_inlined_survives`` 钉住，本席不动它）。
    于是「登记一个 ``file:///x.png``」理论上能把碎形态送进卡片。今天
    ``register_identity`` / ``set_identity_resolver`` 在 ``plugins/`` 下**零调用点**
    （只有定义），所以该洞无载体＝不可达；本锁把「无载体」钉成机器判据——
    谁接 AVT1 装配线，就必须同时把注入点改成过闸口径（``inline_avatar_uri``
    或卡片侧统一 normalize），否则这条红。
    """
    callers: list[str] = []
    for path in _python_files(_RENDER_PLUGINS_ROOT):
        if path.name == "bot_avatar.py":
            continue
        names = _call_names(ast.parse(path.read_text(encoding="utf-8")))
        if {"register_identity", "set_identity_resolver"} & names:
            callers.append(str(path.relative_to(_RENDER_PLUGINS_ROOT)))
    assert callers == [], (
        "身份登记面出现生产调用点，但卡片注入点尚未按三态出口收口——"
        f"请先让消费侧过 inline_avatar_uri 再来摘本锁：{callers}"
    )


@pytest.mark.xfail(
    strict=False,
    reason=(
        "H1 在册未执法（禁写面，坐标交主代理）：根 __init__.py:2199 "
        "_resolve_bot_avatar_url 的 `if configured: return configured` 把 "
        "BOT_PERSONA_AVATAR_URL 的**本地路径**形态原样交给卡片（该键登记的合法取值含"
        "本地路径，台账 #21 也这么建议用户填），绕过了唯一闸 ⇒ 卡片 src 是裸路径或 "
        "file:/// ⇒ 静默空白。修法＝删那两行——bot_avatar_uri(config) 的第一级本就是"
        "显式配置且已过闸（读不到才顺延下一级）。"
        "〔expiry=2026-10-31 owner=SEAT-MAIN 摘牌=根解析器 configured 分支改过闸后删掉"
        "本标记，与上方锁①并列为硬断言〕"
    ),
)
def test_h1_root_configured_local_path_reaches_card_renderable(_clean, tmp_path) -> None:
    """挂账锁：根解析器的「配置值」这一级也必须出门过闸。

    ``strict=False``＝她修好后本锁自动转 PASS 而不炸树；修好后请把本标记删掉、
    与上方锁①并列为硬断言（本席不能改根 ``__init__.py``，见任务书 §3 禁写面）。
    """
    from plugins.bot_unified_runtime import _resolve_bot_avatar_url

    good = _make_avatar(tmp_path)
    config = _cfg(tmp_path, avatar_url=str(good))
    bot = SimpleNamespace(self_id="10000", get_stranger_info=None)
    url = asyncio.run(
        _resolve_bot_avatar_url(bot, config)  # type: ignore[arg-type]
        # 替身 config（仓内测试同法：读取面只 getattr 三个字段，不构造真 Config——
        # 真 Config 会读 .env，测试禁触）。
    )
    assert _is_renderable(url), f"根解析器把碎形态交给了卡片：{url[:60]!r}"


# ---------------------------------------------------------------------------
# 锁②：本地存在头像 → 三条公开出口一律 data:image/ 开头
# ---------------------------------------------------------------------------


def test_local_avatar_makes_every_public_exit_a_data_image(_clean, tmp_path) -> None:
    """三条出口 + base64 往返等值（证明交出去的就是那个文件，不是随手造的图）。"""
    good = _make_avatar(tmp_path)
    config = _cfg(tmp_path)

    exits = {
        "bot_avatar_uri()": bot_avatar.bot_avatar_uri(config),
        "bot_identity('')": bot_avatar.bot_identity("", config).avatar_uri,
        "bot_identity(qq)": bot_avatar.bot_identity("10000", config).avatar_uri,
        "inline_avatar_uri(path)": bot_avatar.inline_avatar_uri(good),
    }
    for label, value in exits.items():
        assert value.startswith("data:image/png;base64,"), (
            f"{label} 未内联：{value[:48]!r}"
        )
        assert base64.b64decode(_b64_payload(value)) == _PNG, f"{label} 的载荷不是这个文件"
    # 内部槽位仍是路径形态（不许被顺手改成 data URI——闸门外不许有第二形态）。
    assert bot_avatar._LOCAL_AVATAR_URI == good.as_uri()


def test_mime_comes_from_magic_bytes_not_the_filename(_clean, tmp_path) -> None:
    """显式 MIME＝读文件头，不信后缀（声明与内容不符＝一张解不出来的碎图）。"""
    adir = tmp_path / "avatar"
    adir.mkdir(parents=True)
    jpeg_named_png = adir / "bot_10000.png"
    jpeg_named_png.write_bytes(_JPEG)
    assert bot_avatar.inline_avatar_uri(jpeg_named_png).startswith("data:image/jpeg;")
    gif_named_png = adir / "bot_10001.png"
    gif_named_png.write_bytes(_GIF)
    assert bot_avatar.inline_avatar_uri(gif_named_png).startswith("data:image/gif;")
    unknown = adir / "bot_10002.png"
    unknown.write_bytes(b"\x00\x01\x02\x03not-an-image")
    assert bot_avatar.inline_avatar_uri(unknown) == ""


def test_size_cap_is_measured_on_the_encoded_payload(_clean, tmp_path, monkeypatch) -> None:
    """上限裁的是**写进每张卡 HTML 的那串字符**（base64 胀 4/3），不是原图字节。

    旧口径拿原图大小比上限 ⇒ 一张贴着上限的头像会往每张卡塞 1.33 倍体积的文本，
    护栏形同虚设。本用例先把三个量**实测**出来（原图字节 S、其编码长度 E、
    缩略后的编码长度 e），再把上限钉在 S 与 E 之间（且 ≥ e）：
    旧口径会直读并输出 E（超上限），新口径必须走缩略腿且输出不超过上限。
    """
    Image = pytest.importorskip("PIL.Image")
    target = tmp_path / "avatar" / "bot_10000.png"
    target.parent.mkdir(parents=True)
    # 噪声图（定种子、离线可复跑）：PNG 压不动 ⇒ 「原图字节 S」与「编码长度 E=4S/3」
    # 拉开确定的 4/3 距离，才有地方把上限钉在两者之间。
    # （本席第一版用规则渐变图，实测 420px 原图被 PNG 压成 11KB、而 160px 缩略
    # 反而 30KB——「缩略必小于原编码长度」的前提当场塌掉，故换不可压内容。）
    size = 300
    noise = random.Random(20260926).randbytes(size * size * 4)
    image = Image.frombytes("RGBA", (size, size), noise)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    raw_bytes = buffer.getvalue()
    target.write_bytes(raw_bytes)

    original_encoded = bot_avatar._b64_payload_length(len(raw_bytes))
    shrunk = bot_avatar._shrink_to_data_uri(target)
    assert shrunk.startswith("data:image/png;base64,"), "缩略腿本身没出图（本用例前提塌了）"
    shrunk_encoded = len(_b64_payload(shrunk))
    assert shrunk_encoded < len(raw_bytes) < original_encoded, (
        f"造例前提塌了：需 缩略编码 {shrunk_encoded} < 原图字节 {len(raw_bytes)} "
        f"< 原图编码 {original_encoded}"
    )

    cap = (original_encoded + len(raw_bytes)) // 2
    monkeypatch.setattr(bot_avatar, "_AVATAR_INLINE_MAX_BYTES", cap)
    out = bot_avatar.inline_avatar_uri(target)
    assert out.startswith("data:image/png;base64,"), "超限既没缩成也没降级，头像直接没了"
    assert len(_b64_payload(out)) <= cap, (
        f"闸门放行了编码后 {len(_b64_payload(out))} 字符 > 上限 {cap}"
    )
    # 判别力自证：旧口径（拿原图字节比上限）在本例里会直读并放行 4/3 体积。
    assert len(raw_bytes) <= cap < original_encoded, (
        f"上限须落在 S={len(raw_bytes)} 与 E={original_encoded} 之间，否则测不到口径变更"
    )


def test_oversize_and_unshrinkable_files_degrade_to_empty_not_broken_uri(
    _clean, tmp_path, monkeypatch
) -> None:
    """超限且缩不动（非图字节 / 无 PIL）＝空串，绝不回一个渲染不出来的 URI。"""
    target = tmp_path / "avatar" / "bot_10000.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * 4096)
    monkeypatch.setattr(bot_avatar, "_AVATAR_INLINE_MAX_BYTES", 64)
    assert bot_avatar.inline_avatar_uri(target) == ""
    assert bot_avatar.bot_avatar_uri(_cfg(tmp_path)) == ""
    assert bot_avatar.bot_identity("10000", _cfg(tmp_path)).avatar_uri == ""


# ---------------------------------------------------------------------------
# 锁③：缺文件＝诚实兜底（圆点腿），不是碎图也不是塌陷
# ---------------------------------------------------------------------------


def test_missing_avatar_file_yields_dot_fallback_not_broken_img(_clean, tmp_path) -> None:
    """出口空串是**信号**，卡面兜底形态由真 DOM 生成件产出——两头都必须成立。

    任务书 2(c)③ 的字面是「兜底形态而非空串」。本席按这条读法落判据（并把
    理由留在报告里请看护员重点复核）：模块层只交空串，圆点文案与 DOM 住在
    模板/胶囊组件里；若模块层直接造一份圆点，就是替模板抄第二份真相
    （板块硬门「禁第二真身」）。所以本锁同时断言两侧：出口空 + 卡面有圆点、
    且不出现 ``<img>`` 碎图、也不整段塌陷。
    """
    (tmp_path / "avatar").mkdir()  # 目录在、文件没有＝重启后 qlogo 拉取失败的实况
    config = _cfg(tmp_path)
    assert bot_avatar.bot_avatar_uri(config) == ""
    assert bot_avatar.bot_identity("10000", config).avatar_uri == ""

    # 出口层的另一半判据：把「指向读不到/不是文件/0 字节」的写法从**显式配置**这一级
    # 灌进公开出口（她按台账 #21 填本地路径就是这条路），三条都必须降级成空串。
    # 少了这一段，「删掉兜底腿」这种注毒只有闸门本体那条锁会红——公开出口形同没锁。
    zero = tmp_path / "avatar" / "bot_7777777.png"
    zero.write_bytes(b"")
    broken_inputs = (
        str(tmp_path / "avatar" / "nope.png"),
        (tmp_path / "avatar" / "nope.png").as_uri(),
        "C:\\nope\\nothere.png",
        str(zero),  # 0 字节视同缺失
        str(tmp_path / "avatar"),  # 目录当文件
    )
    for broken in broken_inputs:
        assert bot_avatar.bot_avatar_uri(_cfg(tmp_path, avatar_url=broken)) == "", (
            f"公开出口把不可渲染的输入交给了卡片：{broken!r}"
        )
        assert bot_avatar.bot_identity("7777777", _cfg(tmp_path, avatar_url=broken)).avatar_uri == ""

    capsule = mica_shell.brand_capsule_html(bot_name=_PERSONA, avatar_url="")
    assert 'class="mc-dot"' in capsule, "空头像没降级成首字圆点（胶囊塌陷）"
    assert "mc-avatar" not in capsule, "空头像仍渲染了 img 腿（会占位不显示）"

    universal = bridge.render_universal_card_html({"bot_avatar_url": ""})
    assert 'class="mc-dot"' in universal, "通用卡缺图时圆点腿缺席"
    _assert_card_html_avatar_is_renderable(universal, face="universal(缺图)")

    error = bridge.render_error_card_html({"bot_avatar_url": ""})
    assert "sigil" in error, "诊断卡缺图时「守」字兜底缺席"
    _assert_card_html_avatar_is_renderable(error, face="error(缺图)")

    media = fstring_templates.render_media_card_html({"bot_avatar_url": "", "title": "样张"})
    assert 'class="mc-dot"' in media, "f-string 直拼媒体卡缺图时圆点腿缺席"
    _assert_card_html_avatar_is_renderable(media, face="media(缺图)")


def test_capsule_component_itself_never_emits_empty_src(_clean) -> None:
    """组件本体：空/None/空白一律走圆点腿，任何输入都不产 ``src=""``。"""
    for value in ("", "   ", None):
        html = mica_shell.brand_capsule_html(bot_name=_PERSONA, avatar_url=value or "")
        assert 'src=""' not in html
        assert "mc-dot" in html
    assert "<img" in mica_shell.brand_capsule_html(
        avatar_url="data:image/png;base64,AAAA"
    )


def test_repeated_calls_are_idempotent_and_cache_invalidates_on_file_change(
    _clean, tmp_path
) -> None:
    """闸门幂等（多级链路反复过闸无副作用）；换文件自动失效（不吐陈旧头像）。"""
    good = _make_avatar(tmp_path)
    config = _cfg(tmp_path)
    first = bot_avatar.bot_avatar_uri(config)
    assert bot_avatar.inline_avatar_uri(first) == first  # 幂等
    assert bot_avatar.bot_avatar_uri(config) == first
    assert bot_avatar.inline_avatar_uri(good) == first

    good.write_bytes(_JPEG)  # 同路径换内容（mtime+size 变）
    second = bot_avatar.inline_avatar_uri(good)
    assert second != first and second.startswith("data:image/jpeg;")
