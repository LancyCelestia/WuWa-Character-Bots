"""需求 15 的隐私红线锁（S-RANDPIC-PRIVACY，2026-09-29 用户明令）。

用户口径逐字拆成可执行判据：

- 「``BOT_RANDPIC_DIRS`` 之外一律不许读」⇒ ① 没登记目录就是**零来源**（不隐式补
  家目录/桌面/下载/图库），② 模块里不存在任何「猜一个用户目录」的读点，
  ③ 相对路径按进程 CWD 解析（既有口径），不落到 ``~``；
- 「不得把用户私人相册/下载目录/桌面纳入可发范围」⇒ 源码级零出现这些目录名与
  ``Path.home()``/``$env:`` 展开（注毒自证：往源码里塞一枚 ``Path.home()`` 的副本，
  同一把尺必须当场判红）；
- 「随机发图绝不得把别人发的图转发给第三者（跨会话泄露）」⇒ ④ 取图口只认登记目录的
  清单，**消息附件/引用图/别的会话媒体一条都不进候选**（运行时以替身清单证明唯一
  来源），⑤ 本能力**从不自己指定收件会话**（源码里零 ``SendRequest``/出站/推送调用），
  发谁永远由中央出站链按当轮请求决定。

去重与可复现（同批需求）已由 ``tests/test_randpic_no_repeat_ledger.py``、
``tests/test_randpic_bucket_key_ledger.py``、``tests/test_poke_randpic_behavior.py`` A/C 组
执法，本件不重复造尺，只补上面这五格。全离线：图库在 ``tmp_path`` 现造。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.contracts import SendPolicy
from plugins.bot_unified_runtime.domains.meme.capabilities import randpic

REPO_ROOT = Path(__file__).resolve().parents[1]
RANDPIC_PY = (
    REPO_ROOT / "plugins/bot_unified_runtime/domains/meme/capabilities/randpic.py"
)

#: 私人区目录名/家目录取数面：随机图**一律不许**碰（用户明令的红线清单）。
FORBIDDEN_SOURCE_TOKENS = (
    "Path.home()",
    "os.path.expanduser",
    "expandvars",
    "getlogin",
    "Desktop",
    "Downloads",
    "Documents",
    "OneDrive",
    "Pictures",
    "Camera Roll",
    "WeChat Files",
    "QQ",  # 只禁作为**读源路径**出现；测试夹具里的 group:g-1 之类不在本文件扫描面
)

#: 第二通路/跨会话发送面：能力本体不许自己出站。
FORBIDDEN_OUTBOUND_TOKENS = (
    "SendRequest(",
    "enqueue",
    "send_onebot",
    "notify_operational",
    "push_",
    "group_id=",
    "target_id=",
)

PNG_HEAD = b"\x89PNG\r\n\x1a\n"


def _gallery(root: Path, count: int = 3) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (root / f"p{index}.png").write_bytes(PNG_HEAD + f"privacy-{index}".encode())
    return root


def _config(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "bot_randpic_enabled": True,
        "bot_randpic_dirs": [],
        "bot_randpic_trigger_words": [],
        "bot_randpic_max_file_mb": 25,
        "bot_randpic_no_repeat_window_seconds": 0.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------- ① 没登记目录＝零来源


def test_empty_dirs_means_no_source_and_no_pick(tmp_path: Path) -> None:
    config = _config(bot_randpic_dirs=[])
    assert randpic.configured_gallery_dirs(config) == []
    assert randpic.pick_gallery_image(config, session_key="group_1_1", seed="s") is None


def test_blank_entries_are_dropped_not_expanded() -> None:
    """空白条目被丢掉，而不是「空串→当前目录→整盘当图库」这类意外放开。

    现网实测过的那条能扫到 4.4 万个文件的路，就是靠这里守住（``Path('')``＝进程 CWD）。
    """
    config = _config(bot_randpic_dirs=["", "   ", "\t"])
    assert randpic.configured_gallery_dirs(config) == []
    assert randpic.pick_gallery_image(config, session_key="group_1_1", seed="s") is None


# ---------------------------------------------------- ② 源码里不许猜用户目录


def _code_text(source: str) -> str:
    """去注释、去字符串字面量后的**紧凑**代码面（空格全抹）。

    为什么紧凑：``tokenize`` 会把 ``Path.home()`` 拆成 ``Path`` / ``.`` / ``home`` / ``(`` / ``)``
    五个记号，带空格拼回来就永远匹配不上「``Path.home()``」这个形态——隐私尺不抹空格
    就是纸面尺。为什么剥字符串与注释：红线判的是**代码里真的去开一个私人目录**，
    一句解释「我们不读桌面」的文档串不该误伤，反过来也不许把读点藏进字符串绕开
    （``Path("~") `` 那类仍会被 ``expanduser`` 这个标识符抓到；本件另有注毒自证）。
    """
    import io
    import tokenize

    keep: list[str] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                              tokenize.DEDENT, tokenize.STRING):
                continue
            keep.append(token.string)
    except (tokenize.TokenError, IndentationError):
        return "".join(source.split())
    return "".join(keep)


def _hits(tokens: tuple[str, ...], code: str) -> list[str]:
    return [token for token in tokens if token.replace(" ", "") in code]


def test_no_implicit_private_directory_sources_in_code() -> None:
    hits = _hits(FORBIDDEN_SOURCE_TOKENS, _code_text(RANDPIC_PY.read_text(encoding="utf-8")))
    assert not hits, f"随机图出现了登记目录之外的来源面：{hits}"


def test_private_source_lock_has_teeth_on_poisoned_copy() -> None:
    """注毒自证：往源码副本加一枚 ``Path.home()`` 读点，同一把尺必须判红。"""
    poisoned = (
        RANDPIC_PY.read_text(encoding="utf-8")
        + "\n\ndef _poison():\n    return str(Path.home() / 'Desktop')\n"
    )
    code = _code_text(poisoned)
    assert "Path.home()" in _hits(FORBIDDEN_SOURCE_TOKENS, code), (
        "注毒没进判定面 ⇒ 这条隐私锁是空跑"
    )


def test_no_outbound_or_second_throat_in_capability() -> None:
    """能力本体零出站调用 ⇒ 它只能「把图交给当轮请求」，发谁由中央出站链决定。"""
    hits = _hits(FORBIDDEN_OUTBOUND_TOKENS, _code_text(RANDPIC_PY.read_text(encoding="utf-8")))
    assert not hits, f"随机图里长出了第二出站通路：{hits}"


# ---------------------------------------------------- ③ 相对路径按 CWD


def test_relative_entry_resolves_against_cwd_not_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = _config(bot_randpic_dirs=["gallery"])
    dirs = randpic.configured_gallery_dirs(config)
    assert dirs == ["gallery"], "本件不改配置面：原样取回，解析发生在 _gallery_root"
    resolved = randpic._gallery_root("gallery")
    assert resolved == Path.cwd() / "gallery"
    assert resolved != Path.home() / "gallery"


# ---------------------------------------------------- ④ 唯一来源＝登记清单


def test_capability_images_always_come_from_the_registered_listing(
    tmp_path: Path, monkeypatch
) -> None:
    """把清单换成替身，能力必须**只**发替身里的那张：证明没有第二条取图路。

    替身刻意放在**登记目录之内**（席 PIC 2026-09-29 校正）：出口那侧新加了登记根
    包含门（``tests/test_randpic_registered_root.py`` ②⑤），登记面之外的替身会被
    当场拒掉——那时这格测的就不再是「唯一来源」而是「越界必拒」，两件事各归各件。
    """
    real = _gallery(tmp_path / "real")
    config = _config(bot_randpic_dirs=[str(real)],
                     bot_randpic_trigger_words=["随机图"])
    stand_in = real / "registered.png"
    stand_in.write_bytes(PNG_HEAD + b"registered-only")
    calls: list[list[str]] = []

    def _fake_listing(dirs, **kwargs):
        calls.append(list(dirs))
        return [stand_in]

    monkeypatch.setattr(randpic, "list_gallery_images", _fake_listing)
    capability = randpic.build_randpic_capability(config)
    message = SimpleNamespace(
        request_id="req-1",
        plain_text="随机图",
        session_id="group_42_7",
        message_id="m-1",
        group_id="42",
        user_id="7",
    )
    result = capability(message, None)
    assert calls and calls[0] == [str(tmp_path / "real")], "取图没走登记目录那一步"
    assert result.images and result.images[0]["file"] == str(stand_in)
    assert result.send_policy is not SendPolicy.SILENT_AUDIT


def test_picked_path_is_never_a_message_attachment(tmp_path: Path, monkeypatch) -> None:
    """候选面只从清单来：即便「消息里带着一张图的字节」也进不了池子（跨会话泄露面）。

    判据＝把清单桩成空 ⇒ 无论消息怎么装，取图口必须返回 ``None``。
    """
    config = _config(bot_randpic_dirs=[str(_gallery(tmp_path / "g"))])
    monkeypatch.setattr(randpic, "list_gallery_images", lambda dirs, **kwargs: [])
    assert randpic.pick_gallery_image(
        config, session_key="group_42_7", seed="s", allow_exhausted=True
    ) is None


# ---------------------------------------------------- 生成物一致性小锁


def test_image_guard_extension_parity_with_randpic_truth() -> None:
    """扩展名面只许一份真身：``image_guard.IMAGE_EXTENSIONS`` ↔ ``randpic`` 那枚。

    群聊吸收、离线导入、扫池三条腿都改读登记五族的扩展名面时，任何一侧偷偷加/删
    一族（比如 HEIC）都会在这里被判两说——这正是「三处各抄一份魔数表」的形态。
    """
    from plugins.bot_unified_runtime.domains.media import image_guard

    assert set(image_guard.IMAGE_EXTENSIONS) == set(randpic._IMAGE_EXTENSIONS)
