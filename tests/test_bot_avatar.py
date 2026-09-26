"""Bot 头像本地优先（F3，2026-09-14 素材本地化批次，全离线）。

锁定 _resolve_bot_avatar_url 三级解析与 bot_avatar.py 磁盘兜底发现：
1. 本地命中（内存登记 / 磁盘 avatar/bot_*.png）→ file URI，远端 RPC 计数=0
   （不再 600s 周期回源）；
2. 本地缺失 → 既有远端链原样（get_stranger_info / qlogo 回退语义不变）；
3. bot_avatar_uri 统一入口的「配置 > 本地 > 空」优先级不被破坏。
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime as runtime_pkg
from plugins.bot_unified_runtime import _resolve_bot_avatar_url
from plugins.bot_unified_runtime.domains.render import bot_avatar

_PNG = b"\x89PNG\r\n\x1a\n" + b"avatar-payload"


@pytest.fixture()
def _isolated(monkeypatch: pytest.MonkeyPatch):
    """隔离三处进程级全局：bot_avatar 内存 URI、600s 远端 URL 缓存、
    磁盘兜底负结果 TTL 缓存（审查 L-14）。"""
    monkeypatch.setattr(bot_avatar, "_LOCAL_AVATAR_URI", "")
    monkeypatch.setattr(runtime_pkg, "_BOT_AVATAR_URL_CACHE", {})
    monkeypatch.setattr(bot_avatar, "_DISCOVER_MISS_TS", {})


def _remote_recorder(url: str = "https://remote.example/a.png"):
    calls: list[dict] = []

    async def _get_stranger_info(**kwargs):
        calls.append(kwargs)
        return {"data": {"avatar": url}}

    return calls, _get_stranger_info


def test_resolve_local_memory_hit_skips_remote(
    _isolated, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    avatar_file = tmp_path / "bot_10000.png"
    avatar_file.write_bytes(_PNG)
    bot_avatar.set_local_path(avatar_file)

    calls, get_stranger_info = _remote_recorder()
    bot = SimpleNamespace(self_id="10000", get_stranger_info=get_stranger_info)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)
    )

    url = asyncio.run(_resolve_bot_avatar_url(bot, config))
    assert url == bot_avatar.inline_avatar_uri(avatar_file)  # 本地 file URI 直出
    assert calls == []  # 零远端调用：600s 周期回源被消灭


def test_resolve_disk_fallback_when_memory_empty(
    _isolated, tmp_path: Path
) -> None:
    # 内存未登记（模拟重启后 qlogo 拉取失败），磁盘文件还在 → 直接用。
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    avatar_file = avatar_dir / "bot_10000.png"
    avatar_file.write_bytes(_PNG)

    calls, get_stranger_info = _remote_recorder()
    bot = SimpleNamespace(self_id="10000", get_stranger_info=get_stranger_info)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)
    )

    url = asyncio.run(_resolve_bot_avatar_url(bot, config))
    assert url == bot_avatar.inline_avatar_uri(avatar_file)  # 磁盘兜底发现并激活
    assert calls == []


def test_discover_picks_newest_avatar_file(_isolated, tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    old_file = avatar_dir / "bot_11111.png"
    new_file = avatar_dir / "bot_10000.png"
    old_file.write_bytes(_PNG)
    new_file.write_bytes(_PNG)
    os.utime(old_file, (1_000_000_000, 1_000_000_000))
    os.utime(new_file, (2_000_000_000, 2_000_000_000))

    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)
    )
    assert bot_avatar.bot_avatar_uri(config) == bot_avatar.inline_avatar_uri(new_file)  # 取最新 mtime


def test_resolve_local_missing_goes_remote(_isolated, tmp_path: Path) -> None:
    calls, get_stranger_info = _remote_recorder("https://napcat.example/a.png")
    bot = SimpleNamespace(self_id="10000", get_stranger_info=get_stranger_info)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)  # 无 avatar 目录
    )

    url = asyncio.run(_resolve_bot_avatar_url(bot, config))
    assert url == "https://napcat.example/a.png"  # 远端链语义原样
    assert len(calls) == 1  # 本地缺失才走远端


def test_resolve_remote_failure_keeps_qlogo_fallback(
    _isolated, tmp_path: Path
) -> None:
    async def _boom(**kwargs):
        raise TimeoutError("napcat rpc timeout")

    bot = SimpleNamespace(self_id="10000", get_stranger_info=_boom)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)
    )

    url = asyncio.run(_resolve_bot_avatar_url(bot, config))
    # 既有回退语义不变：RPC 失败 → qlogo 直链（最终加载失败仍由卡片回落圆点）。
    assert url == "https://q1.qlogo.cn/g?b=qq&nk=10000&s=640"


def test_bot_avatar_uri_configured_url_wins(_isolated, tmp_path: Path) -> None:
    avatar_file = tmp_path / "bot_10000.png"
    avatar_file.write_bytes(_PNG)
    bot_avatar.set_local_path(avatar_file)
    config = SimpleNamespace(
        bot_persona_avatar_url="https://cfg.example/a.png",
        bot_runtime_data_dir=str(tmp_path),
    )
    assert bot_avatar.bot_avatar_uri(config) == "https://cfg.example/a.png"


def test_bot_avatar_uri_no_config_no_file_returns_empty(
    _isolated, tmp_path: Path
) -> None:
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)  # 空目录
    )
    assert bot_avatar.bot_avatar_uri(config) == ""  # 调用方回落「守」字圆点


# ---------------------------------------------------------------------------
# 审查 L-14：磁盘兜底缺失探测的负结果 TTL 缓存（全离线注入时钟）。
# ---------------------------------------------------------------------------


class _Clock:
    """可推进的单调钟替身：monkeypatch 进 bot_avatar._MONOTONIC。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _count_globs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """给 Path.glob 套计数壳（委托真 glob，探测真实发生与否可断言）。"""
    calls: list[str] = []
    real_glob = Path.glob

    def counting_glob(self: Path, pattern: str):
        calls.append(pattern)
        return real_glob(self, pattern)

    monkeypatch.setattr(Path, "glob", counting_glob)
    return calls


def test_miss_probes_once_within_ttl(_isolated, monkeypatch, tmp_path) -> None:
    clock = _Clock()
    monkeypatch.setattr(bot_avatar, "_MONOTONIC", clock)
    globs = _count_globs(monkeypatch)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)  # 无 avatar 目录
    )

    assert bot_avatar.bot_avatar_uri(config) == ""  # 首次：真探测，确认缺失
    assert len(globs) == 1
    assert bot_avatar.bot_avatar_uri(config) == ""  # TTL 内：负缓存回空
    assert bot_avatar.bot_avatar_uri(config) == ""
    assert len(globs) == 1  # 计数不变 → glob+stat 探测未重复（审查 L-14）


def test_miss_reprobes_after_ttl_expiry(_isolated, monkeypatch, tmp_path) -> None:
    clock = _Clock()
    monkeypatch.setattr(bot_avatar, "_MONOTONIC", clock)
    globs = _count_globs(monkeypatch)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)
    )

    assert bot_avatar.bot_avatar_uri(config) == ""
    assert len(globs) == 1
    clock.advance(300.0)  # 恰到 TTL 边界：仍算新鲜（<= 语义，对齐 randpic）
    assert bot_avatar.bot_avatar_uri(config) == ""
    assert len(globs) == 1
    clock.advance(0.5)  # 越过 TTL：过期重探
    assert bot_avatar.bot_avatar_uri(config) == ""
    assert len(globs) == 2


def test_file_appears_after_ttl_returns_uri_then_memory_shortcut(
    _isolated, monkeypatch, tmp_path
) -> None:
    clock = _Clock()
    monkeypatch.setattr(bot_avatar, "_MONOTONIC", clock)
    globs = _count_globs(monkeypatch)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)
    )

    assert bot_avatar.bot_avatar_uri(config) == ""  # 先记负结果
    avatar_file = tmp_path / "avatar" / "bot_10000.png"
    avatar_file.parent.mkdir()
    avatar_file.write_bytes(_PNG)  # 期间头像文件落盘

    clock.advance(301.0)  # TTL 过期 → 重探发现
    assert bot_avatar.bot_avatar_uri(config) == bot_avatar.inline_avatar_uri(avatar_file)
    assert len(globs) == 2

    # 正结果登记内存后：内存短路，再推进时间也不探测（既有语义不变）。
    clock.advance(10_000.0)
    assert bot_avatar.bot_avatar_uri(config) == bot_avatar.inline_avatar_uri(avatar_file)
    assert len(globs) == 2


# ---------------------------------------------------------------------------
# AVT1（2026-09-20 用户裁定「做成多 bot 身份自动取」）：bot_identity /
# register_identity / set_identity_resolver 四级名字链与逐实例头像。
# 回归底线：``bot_id`` 为空的读取行为与旧版逐字节一致——旧版的全部可观察
# 行为就是 ``bot_avatar_uri`` 链（显式配置 > 内存登记 > 磁盘兜底 > 空），
# 本节的锁 ① 逐字面对它；其余用例锁新增面，不触碰、不削弱上方旧锁。
# ---------------------------------------------------------------------------

_PERSONA = "报存"  # 与 config.py:150 bot_persona_display_name 缺省同值


def _cfg(tmp_path: Path, *, avatar_url: str = "", persona: str | None = _PERSONA):
    """构造读取面用到的最小 config 替身（persona=None 时模拟字段缺席）。"""
    fields: dict[str, str] = {
        "bot_persona_avatar_url": avatar_url,
        "bot_runtime_data_dir": str(tmp_path),
    }
    if persona is not None:
        fields["bot_persona_display_name"] = persona
    return SimpleNamespace(**fields)


@pytest.fixture()
def _avt1(_isolated, monkeypatch: pytest.MonkeyPatch):
    """在三个旧全局之外，再隔离 AVT1 的两个新进程级槽位（注册表+解析器）。"""
    monkeypatch.setattr(bot_avatar, "_IDENTITY_REGISTRY", {})
    monkeypatch.setattr(bot_avatar, "_IDENTITY_RESOLVER", None)


# ① 回归锁：bot_id 为空 → 头像链与旧版 bot_avatar_uri 逐字节一致，
#    且新槽位（注册表/解析器/逐实例磁盘）一律不经过。


def test_empty_bot_id_matches_legacy_chain_byte_identical(_avt1, tmp_path) -> None:
    # 场景 A：显式配置优先（旧第一级）。
    cfg = _cfg(tmp_path, avatar_url="https://cfg.example/a.png")
    bot_avatar.register_identity("10000", name="注册名", avatar_uri="file:///x.png")
    seen: list[str] = []
    bot_avatar.set_identity_resolver(
        lambda bot_id, config: seen.append(bot_id) or "解析名"
    )
    assert bot_avatar.bot_identity("", cfg).avatar_uri == "https://cfg.example/a.png"
    assert bot_avatar.bot_avatar_uri(cfg) == "https://cfg.example/a.png"

    # 场景 B：无配置 → 磁盘兜底发现（旧第三级，含正结果登记副作用）。
    cfg2 = _cfg(tmp_path / "b")
    avatar_file = Path(cfg2.bot_runtime_data_dir)
    (avatar_file / "avatar").mkdir(parents=True)
    legacy = avatar_file / "avatar" / "bot_10000.png"
    legacy.write_bytes(_PNG)
    assert bot_avatar.bot_identity("", cfg2).avatar_uri == bot_avatar.inline_avatar_uri(legacy)
    assert bot_avatar.bot_avatar_uri(cfg2) == bot_avatar.inline_avatar_uri(legacy)

    # 新槽位零经过：空 bot_id 不查注册表（注册键 10000 不命中）不叫解析器。
    assert seen == []
    assert bot_avatar.bot_identity("   ", cfg2).avatar_uri == bot_avatar.inline_avatar_uri(legacy)  # 纯空白=空
    assert seen == []


def test_empty_bot_id_name_is_persona_and_skips_instance_slots(_avt1, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    bot_avatar.register_identity("10000", name="注册名")
    called: list[str] = []
    bot_avatar.set_identity_resolver(lambda bot_id, config: called.append(bot_id) or "解析名")
    assert bot_avatar.bot_identity("", cfg).name == _PERSONA
    assert called == []


# ② 逐实例头像按 avatar/bot_<qq>.png 命名隔离命中。


def test_per_instance_avatar_isolated_by_filename(_avt1, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    adir = Path(cfg.bot_runtime_data_dir) / "avatar"
    adir.mkdir(parents=True)
    main = adir / "bot_10000.png"
    campus = adir / "bot_2300230562.png"
    main.write_bytes(_PNG)
    campus.write_bytes(_PNG)
    # 主号更新（旧「取最新」口径会先选中它）；逐实例口径必须按名命中。
    os.utime(main, (2_000_000_000, 2_000_000_000))
    os.utime(campus, (1_000_000_000, 1_000_000_000))
    assert bot_avatar.bot_identity("2300230562", cfg).avatar_uri == bot_avatar.inline_avatar_uri(campus)
    assert bot_avatar.bot_identity("10000", cfg).avatar_uri == bot_avatar.inline_avatar_uri(main)


def test_per_instance_zero_size_file_skipped_then_global(_avt1, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    adir = Path(cfg.bot_runtime_data_dir) / "avatar"
    adir.mkdir(parents=True)
    (adir / "bot_10000.png").write_bytes(b"")  # 0 字节视同缺失（对齐旧发现口径）
    assert bot_avatar.bot_identity("10000", cfg).avatar_uri == ""


def test_per_instance_missing_falls_back_to_legacy_chain(_avt1, tmp_path) -> None:
    # 逐实例无文件（校园/推送号接入前实况）→ 回落到今天全局链，零退化。
    cfg = _cfg(tmp_path, avatar_url="https://cfg.example/a.png")
    assert bot_avatar.bot_identity("999999", cfg).avatar_uri == "https://cfg.example/a.png"


def test_non_numeric_bot_id_skips_disk_lookup(_avt1, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    adir = Path(cfg.bot_runtime_data_dir) / "avatar"
    adir.mkdir(parents=True)
    (adir / "bot_10000.png").write_bytes(_PNG)
    # 非 QQ 号形态（如 TG 侧键）不做 bot_<id>.png 拼接，直接全局回落。
    assert bot_avatar.bot_identity("tg:42", cfg).avatar_uri == bot_avatar.inline_avatar_uri(
        adir / "bot_10000.png"
    )  # 磁盘兜底发现（旧链）而非 tg 专属文件


# ③ 名字四级链：显式登记 > 装配层解析器 > 人格配置名 > 空。


def test_name_chain_registry_wins_over_resolver_and_persona(_avt1, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    bot_avatar.set_identity_resolver(lambda bot_id, config: "解析名")
    bot_avatar.register_identity("10000", name="登记名")
    assert bot_avatar.bot_identity("10000", cfg).name == "登记名"


def test_name_chain_resolver_when_unregistered(_avt1, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    bot_avatar.set_identity_resolver(lambda bot_id, config: f"装配:{bot_id}")
    assert bot_avatar.bot_identity("2300230562", cfg).name == "装配:2300230562"


def test_name_chain_resolver_blank_answer_falls_to_persona(_avt1, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    bot_avatar.set_identity_resolver(lambda bot_id, config: "")
    assert bot_avatar.bot_identity("2300230562", cfg).name == _PERSONA
    bot_avatar.set_identity_resolver(lambda bot_id, config: None)  # 允许回 None
    assert bot_avatar.bot_identity("2300230562", cfg).name == _PERSONA


def test_name_chain_persona_absent_config_field_yields_empty(_avt1, tmp_path) -> None:
    cfg = _cfg(tmp_path, persona=None)  # 模拟人格名字段整体缺席
    assert bot_avatar.bot_identity("10000", cfg).name == ""  # 第四级：空=胶囊回落品牌名
    assert bot_avatar.bot_identity("", cfg).name == ""


def test_name_chain_resolver_cleared_by_none(_avt1, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    bot_avatar.set_identity_resolver(lambda bot_id, config: "解析名")
    bot_avatar.set_identity_resolver(None)
    assert bot_avatar.bot_identity("10000", cfg).name == _PERSONA


# ④ 解析器抛异常不塌面：fail-safe 落到下一级。


def test_resolver_exception_fails_safe_to_next_tier(_avt1, tmp_path) -> None:
    cfg = _cfg(tmp_path)

    def _boom(bot_id: str, config: object) -> str:
        raise RuntimeError("装配层炸了")

    bot_avatar.set_identity_resolver(_boom)
    identity = bot_avatar.bot_identity("10000", cfg)  # 绝不外抛
    assert identity.name == _PERSONA  # 落到第三级


def test_resolver_failure_does_not_mask_registered_name(_avt1, tmp_path) -> None:
    cfg = _cfg(tmp_path)

    def _boom(bot_id: str, config: object) -> str:
        raise ValueError

    bot_avatar.set_identity_resolver(_boom)
    bot_avatar.register_identity("2300230562", name="登记名")
    assert bot_avatar.bot_identity("2300230562", cfg).name == "登记名"  # 第一级本就不叫解析器


# ⑤ 注册表与单实例槽位互不污染。


def test_registry_and_single_slot_isolation(_avt1, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    main_file = tmp_path / "main.png"
    main_file.write_bytes(_PNG)
    bot_avatar.set_local_path(main_file)  # 单实例内存槽位=主号
    bot_avatar.register_identity(
        "2300230562", name="校园守", avatar_uri="file:///campus.png"
    )
    # 登记不碰全局槽位：旧链逐字节不变。
    assert bot_avatar.bot_avatar_uri(cfg) == bot_avatar.inline_avatar_uri(main_file)
    assert bot_avatar._LOCAL_AVATAR_URI == main_file.as_uri()
    # 全局槽位不碰注册结果：注册头像优先于回落链。
    campus = bot_avatar.bot_identity("2300230562", cfg)
    assert campus.name == "校园守"
    assert campus.avatar_uri == "file:///campus.png"
    # 空 bot_id 走全局槽位，不串注册表。
    legacy = bot_avatar.bot_identity("", cfg)
    assert legacy.avatar_uri == bot_avatar.inline_avatar_uri(main_file)
    assert legacy.name == _PERSONA


def test_register_blank_bot_id_is_noop(_avt1) -> None:
    bot_avatar.register_identity("", name="幽灵名")
    bot_avatar.register_identity("   ", avatar_uri="file:///g.png")
    assert bot_avatar._IDENTITY_REGISTRY == {}


def test_register_replaces_previous_entry_wholesale(_avt1, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    bot_avatar.register_identity("10000", name="一版", avatar_uri="file:///a.png")
    bot_avatar.register_identity("10000", name="二版")  # 不再带头像
    identity = bot_avatar.bot_identity("10000", cfg)
    assert identity.name == "二版"
    assert identity.avatar_uri == ""  # 一版头像不被隐式继承（整条替换语义）


# 附加锁：锁纪律与极端入参不塌面。


def test_resolver_may_read_module_state_without_deadlock(_avt1, tmp_path) -> None:
    # 解析器运行期允许反读本模块读取面（bot_avatar_uri 要拿 _LOCK）：
    # 实现若持锁回调，本用例挂死 → 线程超时判定，绝不拖垮套件（daemon）。
    import threading

    cfg = _cfg(tmp_path)
    result: dict[str, str] = {}

    def _resolver(bot_id: str, config: object) -> str:
        config and bot_avatar.bot_avatar_uri(config)  # 拿锁调用，不得嵌套死锁
        return "装配名"

    bot_avatar.set_identity_resolver(_resolver)
    worker = threading.Thread(
        target=lambda: result.update(
            name=bot_avatar.bot_identity("10000", cfg).name
        ),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=5.0)
    assert not worker.is_alive(), "解析器持锁回调导致死锁"
    assert result.get("name") == "装配名"


def test_bot_identity_never_raises_on_none_config(_avt1) -> None:
    identity = bot_avatar.bot_identity("12345", None)
    assert identity.name == ""
    assert identity.avatar_uri == ""


def test_bot_identity_is_frozen_value_object(_avt1) -> None:
    identity = bot_avatar.bot_identity()
    with pytest.raises(dataclasses.FrozenInstanceError):
        identity.name = "改不动"  # type: ignore[misc]

# --- 公开读取口永不吐 file://（2026-09-25 真卡碎图根修） -------------------


def test_no_public_getter_ever_returns_file_uri(_isolated, tmp_path: Path) -> None:
    """卡片走 ``set_content`` 装页，Chromium 拒收 ``file://`` 子资源。

    诊断卡先修过这件事（`error_report._card_avatar_uri`），help 卡没修，于是她
    点名「左上角头像没加载出来，成了空白占位」。内联收进本模块的公开读取口后，
    这条锁钉住**所有**出口：单实例、空 bot_id、逐实例三条路径一律 data URI。
    内部槽位仍存 file URI（那是身份登记的稳定形态），所以这里同时钉住
    「内部没被顺手改成 data URI」——两头都锁，防止日后有人把内联挪回调用方。
    """
    (tmp_path / "avatar").mkdir()
    main = tmp_path / "avatar" / "bot_10000.png"
    main.write_bytes(_PNG)
    cfg = SimpleNamespace(bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path))

    single = bot_avatar.bot_avatar_uri(cfg)
    empty_key = bot_avatar.bot_identity("", cfg).avatar_uri
    per_instance = bot_avatar.bot_identity("10000", cfg).avatar_uri
    for label, value in (
        ("bot_avatar_uri", single),
        ("bot_identity('')", empty_key),
        ("bot_identity('10000')", per_instance),
    ):
        assert value.startswith("data:image/"), f"{label} 未内联：{value[:40]!r}"
        assert not value.startswith("file:"), f"{label} 把 file URI 交给了卡片"
    assert single == bot_avatar.inline_avatar_uri(main)  # 取的就是这个文件
    assert bot_avatar._LOCAL_AVATAR_URI == main.as_uri()  # 内部槽位仍是路径


def test_registered_value_that_cannot_be_inlined_survives(_avt1, tmp_path: Path) -> None:
    """内联是机会主义不是裁决：读不到的登记值必须原样回，不许被抹成空串。

    与上一条配对看——「卡片拿到的必须是能渲染的」不能靠牺牲「登记什么读出什么」
    来换（AVT1 ⑤ 注册表隔离）。真文件走内联，登记来的标识符原样透传。
    """
    bot_avatar.register_identity("2300230562", name="校园守", avatar_uri="file:///nope.png")
    cfg = SimpleNamespace(bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path))
    identity = bot_avatar.bot_identity("2300230562", cfg)
    assert identity.avatar_uri == "file:///nope.png"
    assert identity.name == "校园守"


def test_http_and_data_values_pass_through_untouched(_isolated, tmp_path: Path) -> None:
    """显式配置的 http／data 值原样透传——内联只治本地文件这一类。"""
    cfg_http = SimpleNamespace(
        bot_persona_avatar_url="https://example.com/a.png", bot_runtime_data_dir=str(tmp_path)
    )
    assert bot_avatar.bot_avatar_uri(cfg_http) == "https://example.com/a.png"
    inline = "data:image/png;base64,AAAA"
    assert bot_avatar.inline_avatar_uri(inline) == inline


def test_oversize_and_non_image_files_return_empty_not_broken_uri(_isolated, tmp_path: Path) -> None:
    """超大／非图片回空串（由模板回落「守」字圆点），绝不回一个渲染不出来的 URI。"""
    big = tmp_path / "bot_10000.png"
    big.write_bytes(b"x" * (bot_avatar._AVATAR_INLINE_MAX_BYTES + 1))
    assert bot_avatar.inline_avatar_uri(big) == ""
    txt = tmp_path / "bot_10000.txt"
    txt.write_text("不是图", encoding="utf-8")
    assert bot_avatar.inline_avatar_uri(txt) == ""
