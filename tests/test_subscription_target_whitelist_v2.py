"""订阅 V2 冒号目标白名单行为锁（审查 SEAT-ATK-SUB F-6，2026-09-28 席位 S-FIX-SUB-SEC）。

洞形（评审在案）：冒号形态 ``provider:kind:key`` 的 key 段在整张 adapter 面
零字符集校验，key 原样内插拉取 URL（查询位 ``?id={key}&limit=50`` 与路径位
``/api/album/{key}``），可注入 URL 结构字符把带平台 Cookie 的同源请求改到
畸形目标；私聊 ``/订阅 add`` 零角色门槛即达。

本锁钉三腿（全离线 mock，零真网零真库）：
1. 出面拒绝：8 平台 × 注入样本 ⇒ resolve_target 必 ValueError（零落库）；
   合法冒号/URL 形态不回归（含各 adapter 既有 URL 捕获字符集的超集对照）。
2. 纵深腿：绕过 resolve 直构的脏 key 目标 ⇒ 拉取口不发请求（结构化
   invalid_target），存储口 upsert 拒写。
3. Cookie 出站组合口：平台 host 表 ∧ 中央咽喉（scrub_credentials_for_target，
   只读复用）双腿判定逐值锁——出表即剥、跨平台即剥。

毒自证（撤白名单腿必红）不在本文件——见本席报告 .superpowers/sdd/
2026-09-27-fullload/logs/SEAT-FIX-SUB-SEC.md 的 %TEMP% 副本程序与 cmp 留痕。

复跑：
    cd ChatBot/ChatBot && BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 \\
      PYTHONPYCACHEPREFIX=$TEMP/gr-pyc PYTHONIOENCODING=utf-8 \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      tests/test_subscription_target_whitelist_v2.py \\
      -p no:cacheprovider --basetemp=$TEMP/subsec-bt -q
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers import http_util
from plugins.bot_unified_runtime.domains.subscribe.adapters import (
    music_v2 as music_module,
)
from plugins.bot_unified_runtime.domains.subscribe.adapters import (
    social_v2 as social_module,
)
from plugins.bot_unified_runtime.domains.subscribe.adapters.music_v2 import (
    MusicSubscriptionAdapterV2,
)
from plugins.bot_unified_runtime.domains.subscribe.adapters.social_v2 import (
    BilibiliSubscriptionAdapterV2,
    PixivSubscriptionAdapterV2,
    TelegramSubscriptionAdapterV2,
    TwitterSubscriptionAdapterV2,
    WeiboSubscriptionAdapterV2,
    XiaohongshuSubscriptionAdapterV2,
    YouTubeSubscriptionAdapterV2,
)
from plugins.bot_unified_runtime.domains.subscribe.adapters.target_policy_v2 import (
    subscription_outbound_cookie,
    target_key_issue,
    trusted_host_for_platform,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_store_v2 import (
    SubscriptionStoreV2,
)

# ---- 攻击样本：注入 URL 结构字符（片段 #、参数 &/?/=、路径 ../、编码绕过） ----
_INJECTION_KEYS = [
    "1&x=y",              # 评审原案 netease:playlist:1&x=y（参数追加）
    "1#frag",             # 同源片段注入（携带 Cookie 的畸形目标）
    "1?a=1",              # 查询重启
    "1/../../admin",      # 路径段跳转
    "..%2f..%2fetc",      # 编码绕过尝试（% 本身即非法字符）
    "1 javascript:x",     # 空格断段
    "UC1&debug=1#x",      # youtube 形态混注
    "channel_id=1&x=1",   # 参数走私
    "a" * 100,            # 超长溢出
]

_SOCIAL_CASES = [
    (BilibiliSubscriptionAdapterV2, "bilibili:creator:{key}"),
    (XiaohongshuSubscriptionAdapterV2, "xiaohongshu:creator:{key}"),
    (YouTubeSubscriptionAdapterV2, "youtube:channel:{key}"),
    (TelegramSubscriptionAdapterV2, "telegram:public_channel:{key}"),
    (PixivSubscriptionAdapterV2, "pixiv:creator:{key}"),
    (WeiboSubscriptionAdapterV2, "weibo:creator:{key}"),
]


def _twitter_ctx() -> dict:
    # 审查 J-01 门：twitter resolve 需 X cookie（判据仅字符串在场，无网络）。
    return {"cookie_header": "auth_token=fake; ct0=fake"}


def _music_ctx() -> dict:
    return {}


@pytest.mark.parametrize("key", _INJECTION_KEYS)
def test_music_colon_form_injection_rejected(key: str) -> None:
    with pytest.raises(ValueError):
        asyncio.run(
            MusicSubscriptionAdapterV2().resolve_target(f"netease:playlist:{key}", _music_ctx())
        )


@pytest.mark.parametrize("adapter_cls,template", _SOCIAL_CASES)
@pytest.mark.parametrize("key", _INJECTION_KEYS)
def test_social_colon_form_injection_rejected(adapter_cls, template: str, key: str) -> None:
    with pytest.raises(ValueError):
        asyncio.run(adapter_cls().resolve_target(template.format(key=key), {}))


@pytest.mark.parametrize("key", _INJECTION_KEYS)
def test_twitter_colon_form_injection_rejected(key: str) -> None:
    with pytest.raises(ValueError):
        asyncio.run(
            TwitterSubscriptionAdapterV2().resolve_target(f"twitter:creator:{key}", _twitter_ctx())
        )


def test_music_attack_exemplar_from_review_rejected() -> None:
    # 评审在案原案：netease:playlist:1&x=y —— id 回显 + URL 参数追加双外泄面。
    adapter = MusicSubscriptionAdapterV2()
    with pytest.raises(ValueError):
        asyncio.run(adapter.resolve_target("netease:playlist:1&x=y", {}))


# ---- 合法形态不回归（各 URL 捕获正则在各自表式之内） ----

def test_legal_colon_and_url_forms_still_accepted() -> None:
    cases = [
        (MusicSubscriptionAdapterV2(), "netease:playlist:123", _music_ctx, "playlist", "123"),
        (MusicSubscriptionAdapterV2(), "netease:artist:456", _music_ctx, "artist", "456"),
        (
            MusicSubscriptionAdapterV2(),
            "https://music.163.com/playlist?id=98765",
            _music_ctx,
            "playlist",
            "98765",
        ),
        (BilibiliSubscriptionAdapterV2(), "bilibili:creator:42", _music_ctx, "creator", "42"),
        (BilibiliSubscriptionAdapterV2(), "bilibili:bangumi:ss123", _music_ctx, "bangumi", "ss123"),
        (
            BilibiliSubscriptionAdapterV2(),
            "https://space.bilibili.com/12345",
            _music_ctx,
            "creator",
            "12345",
        ),
        (XiaohongshuSubscriptionAdapterV2(), "xiaohongshu:creator:u1", _music_ctx, "creator", "u1"),
        (YouTubeSubscriptionAdapterV2(), "youtube:channel:UC1", _music_ctx, "channel", "UC1"),
        (YouTubeSubscriptionAdapterV2(), "youtube:live:@handle", _music_ctx, "live", "@handle"),
        (
            YouTubeSubscriptionAdapterV2(),
            "https://www.youtube.com/channel/UCabcdefghij1234567890AB",
            _music_ctx,
            "channel",
            "UCabcdefghij1234567890AB",
        ),
        (
            TelegramSubscriptionAdapterV2(),
            "telegram:public_channel:newsroom",
            _music_ctx,
            "public_channel",
            "newsroom",
        ),
        (
            TelegramSubscriptionAdapterV2(),
            "https://t.me/s/durov",
            _music_ctx,
            "public_channel",
            "durov",
        ),
        (PixivSubscriptionAdapterV2(), "pixiv:creator:100500", _music_ctx, "creator", "100500"),
        (WeiboSubscriptionAdapterV2(), "weibo:creator:42", _music_ctx, "creator", "42"),
        (TwitterSubscriptionAdapterV2(), "twitter:creator:alice", _twitter_ctx, "creator", "alice"),
    ]
    for adapter, raw, ctx_fn, kind, key in cases:
        target = asyncio.run(adapter.resolve_target(raw, ctx_fn()))
        assert target.target_kind == kind and target.target_key == key, raw


# ---- 纵深腿 A：拉取口拒发请求（绕过 resolve 直构脏 key） ----

def _direct_target(platform: str, kind: str, key: str) -> SubscriptionTarget:
    now = datetime.now(timezone.utc)
    return SubscriptionTarget(
        id=f"{platform}:{kind}:{key}",
        platform=platform,
        target_kind=kind,
        target_key=key,
        display_name=key,
        target_payload={"raw": f"{platform}:{kind}:{key}"},
        created_at=now,
        updated_at=now,
    )


def test_music_fetch_with_poison_key_sends_no_request(monkeypatch) -> None:
    calls: list[str] = []

    def _boom(url, **kwargs):
        calls.append(url)
        raise AssertionError("poison key must not reach HTTP")

    monkeypatch.setattr(music_module, "http_get_json", _boom)
    result = asyncio.run(
        MusicSubscriptionAdapterV2().fetch_incremental(
            _direct_target("netease", "playlist", "1&x=y#frag"),
            {},
            {"cookie_header": "MUSIC_U=secret"},
        )
    )
    assert not calls
    assert result.error_code == "invalid_target"


@pytest.mark.parametrize(
    ("adapter", "platform", "kind"),
    [
        (BilibiliSubscriptionAdapterV2(), "bilibili", "creator"),
        (XiaohongshuSubscriptionAdapterV2(), "xiaohongshu", "creator"),
        (YouTubeSubscriptionAdapterV2(), "youtube", "channel"),
        (TelegramSubscriptionAdapterV2(), "telegram", "public_channel"),
        (PixivSubscriptionAdapterV2(), "pixiv", "creator"),
        (WeiboSubscriptionAdapterV2(), "weibo", "creator"),
    ],
)
def test_social_fetch_with_poison_key_sends_no_request(monkeypatch, adapter, platform, kind) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError(f"poison {platform} key must not reach HTTP")

    monkeypatch.setattr(social_module, "http_get_text", _boom)
    monkeypatch.setattr(social_module, "http_get_json", _boom)
    monkeypatch.setattr(http_util, "http_get_json", _boom)
    monkeypatch.setattr(http_util, "http_get_text", _boom)
    result = asyncio.run(
        adapter.fetch_incremental(
            _direct_target(platform, kind, "1/../../x#a=1"),
            {},
            {"cookie_header": "SECRET=1; auth_token=1; ct0=1"},
        )
    )
    assert result.error_code == "invalid_target"


def test_youtube_live_fetch_with_poison_key_sends_no_request(monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("poison youtube live key must not reach HTTP")

    monkeypatch.setattr(social_module, "http_get_text", _boom)
    result = asyncio.run(
        YouTubeSubscriptionAdapterV2().fetch_incremental(
            _direct_target("youtube", "live", "UCabc123#x"),
            {},
            {"cookie_header": "SID=secret"},
        )
    )
    assert result.error_code == "invalid_target"


# ---- 纵深腿 B：存储口拒写 ----

def test_store_upsert_rejects_poison_key_on_known_platform(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subs.sqlite3"))
    with pytest.raises(ValueError):
        store.upsert_target(_direct_target("netease", "playlist", "1&x=y#frag"))
    # 未登记平台直构目标不误杀（测试/存量防御路径），但 URL 结构字符仍过不去。
    store.upsert_target(_direct_target("test", "whatever", "abc_123"))
    with pytest.raises(ValueError):
        store.upsert_target(_direct_target("test", "whatever", "abc?x=1#y"))


# ---- Cookie 出站组合口逐值锁 ----

def test_outbound_cookie_host_table_legs() -> None:
    # 本平台 host：过表 ∧ 过中央咽喉 ⇒ 原样带出。
    assert (
        subscription_outbound_cookie("netease", "https://music.163.com/api/x", "MUSIC_U=s")
        == "MUSIC_U=s"
    )
    # 同源参数追加注入形态出不了「host 在表」这一腿吗？出得了（host 未变）——
    # 该样本存在的意义正是：host 表腿拦不住同源注入，key 白名单腿必须拦住。
    # 跨 host（外域）：表腿剥。
    assert subscription_outbound_cookie("netease", "https://evil.example.com/x", "MUSIC_U=s") == ""
    # 跨平台（其它平台可信域）：表腿剥（联合域即便放行也不得出本平台表）。
    assert (
        subscription_outbound_cookie("netease", "https://www.bilibili.com/x", "MUSIC_U=s") == ""
    )
    # 表内有名、中央咽喉无域（pixiv 不在联合域表）：组合腿剥（与修前实际出站
    # 逐字节一致——WP1 本就剥，本席不改中央语义）。
    assert subscription_outbound_cookie("pixiv", "https://www.pixiv.net/ajax/x", "s") == ""
    # 空 cookie 不涉及归属判定：返回空串。
    assert subscription_outbound_cookie("netease", "https://music.163.com/x", "") == ""
    # host 取不到（非 http(s) 形态）：fail-closed 剥。
    assert subscription_outbound_cookie("netease", "javascript:alert#1&x=y", "MUSIC_U=s") == ""


def test_trusted_host_matching_is_anchored() -> None:
    assert trusted_host_for_platform("netease", "https://music.163.com/api")
    assert trusted_host_for_platform("bilibili", "https://api.bilibili.com/x")
    # 后缀语义不误伤：evilbilibili.com / music.163.com.evil.tld 均拒。
    assert not trusted_host_for_platform("bilibili", "https://evilbilibili.com/x")
    assert not trusted_host_for_platform("netease", "https://music.163.com.evil.tld/x")
    assert not trusted_host_for_platform("netease", "https://evil.tld/@music.163.com")
    # 未登记平台永远 False。
    assert not trusted_host_for_platform("whatever", "https://whatever.tld/x")


def test_legit_outbound_carries_cookie_and_poison_never_does(monkeypatch) -> None:
    # 行为锁正题「reject, or strip cookies outbound」双证：合法 key 正常出站
    # （cookie 原样到本平台 host），脏 key 直构必拒（零出站）。
    captured: dict = {}

    def _fake_json(url, **kwargs):
        captured["url"] = url
        captured["cookie"] = kwargs.get("cookie", "")
        return {"result": {"tracks": []}}

    monkeypatch.setattr(music_module, "http_get_json", _fake_json)
    result = asyncio.run(
        MusicSubscriptionAdapterV2().fetch_incremental(
            _direct_target("netease", "playlist", "123"),
            {},
            {"cookie_header": "MUSIC_U=topsecret"},
        )
    )
    assert captured["url"].startswith("https://music.163.com/api/playlist/detail?id=123")
    assert captured["cookie"] == "MUSIC_U=topsecret"
    assert result.error_code != "invalid_target"
    captured.clear()
    result = asyncio.run(
        MusicSubscriptionAdapterV2().fetch_incremental(
            _direct_target("netease", "playlist", "123&sign=#pwn"),
            {},
            {"cookie_header": "MUSIC_U=topsecret"},
        )
    )
    assert not captured, "poison key 不得产生任何出站"
    assert result.error_code == "invalid_target"


# ---- 白名单腿自身的最小单测（表在订阅域身体里，不散进解析器） ----

def test_policy_table_is_fail_closed() -> None:
    assert target_key_issue("netease", "playlist", "12345") == ""
    assert target_key_issue("netease", "playlist", "12345&x") != ""
    assert target_key_issue("bilibili", "bangumi", "ep999") == ""
    assert target_key_issue("bilibili", "bangumi", "ssabc") != ""
    assert target_key_issue("twitter", "creator", "a" * 16) != ""  # 句柄上限 15
    assert target_key_issue("telegram", "public_channel", "abc") != ""  # 下限 4
    # 纯点/连点段任何平台不放行。
    assert target_key_issue("youtube", "channel", "..") != ""
    assert target_key_issue("youtube", "channel", "...") != ""
