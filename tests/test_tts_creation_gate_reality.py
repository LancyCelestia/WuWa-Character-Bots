"""S70 · ``creation.tts.synthesize`` provider 门真值 + 总开关缺口的离线钉死。

存在理由（中央调度收编波 S70，mandate 目标 3「语音要可用，不是预留」）：
``engine_provider.py`` 顶部旧散文曾写「未来键不存在于 ``config.py`` ⇒ ``getattr`` 恒 None ⇒
恒 False ⇒ 诚实 UNAVAILABLE」——CM-P-3 甲案（2026-09-23）把 provider 判据换成现役键
``bot_tts_api_url``／``bot_tts_ref_audios`` 后，生产 ``Config`` 缺省 ``bot_tts_api_url`` 即非空
⇒ **门是开的**，旧散文把「可用」误叙述成「恒不可用」。本件把两件事钉死，方向各拦一类退化：

- **正向锁**：生产缺省口径下门放行、无参考音诚实 ``NOT_CONFIGURED``（不是 ``UNAVAILABLE``）；
  只有三把在场键全空才诚实 ``UNAVAILABLE``（``test_creation_tts_engine_provider`` 里那扇
  「门关」的门要三把键一起关，本件补一条独立尺）。
- **缺口锁**：``handle`` 今天**不读** ``bot_tts_enabled``（TTS 总开关）——命令路
  （``bot.tts``）第一道就查、关了静默；本路只有控制面一个缺省关的调用点 ⇒ 现网行为中性，
  但「总开关关 ⇒ creation.tts 也关」这一条**未执法**。以 ``xfail(strict=False)`` 钉成
  活雷（真修后转 XPASS 提醒回来改散文/改判据），另附一条 AST 特征锁点名"当前不读"。

全离线纪律：零网络、零引擎调用、零 ``config.py`` 写入；合成原语一律经
``synthesize_autodub`` 既有注入缝交确定性替身；参考音用 tmp 占位文件只过 ``pick_ref_audio``
的「文件存在」判定。**注毒三发（A/B/C）在 ``test_teeth_*`` 里以 monkeypatch 现证「有牙」**，
不写死受害 id（S-MAIN §33 教训）。

判定红线（本席专项警告）：本件只证「形状/契约」，**不证「真机会响」**。语音可用须重启后真机验。
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.creation import reserved_provider
from plugins.bot_unified_runtime.domains.creation.tts import engine_provider
from plugins.bot_unified_runtime.domains.media.capabilities import tts
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    CapabilityRequest,
    InvocationStatus,
)

PROVIDER_PATH = (
    Path("plugins/bot_unified_runtime/domains/creation/tts/engine_provider.py").resolve()
)

#: 与 ``config.py:404`` 生产缺省同值——本件唯一"生产口径"的锚；改任一侧由本门或
#: ``test_tts_presets``/``verify_chatbot_env`` 抓到。
PROD_API_URL = "http://127.0.0.1:9880"


def _config(**overrides: Any) -> SimpleNamespace:
    """鸭子配置，镜像 ``Config`` 生产缺省口径（``bot_tts_api_url`` 非空=门开、无参考音）。

    ⚠ **2026-09-24T00:59Z 随迁一处**：``bot_tts_enabled`` 的本函数缺省由 ``False`` 改成
    ``True``。原因不是"测试坏了"，而是主代理给 ``handle`` 加了**首道总开关闸**
    （CM-P-29 真修）——本件除 ``test_kill_switch_stops_creation_tts_without_touching_engine``
    之外，全部用例想测的是"语音开着、但 provider/参考音缺位时诚不诚实"，
    开关关着的话根本走不到那条分支（会被首道闸提前返 ``NOT_CONFIGURED``）。
    要测"开关关"这一形，**显式**传 ``bot_tts_enabled=False``（那才是有意义的构造），
    别靠缺省值顺带命中——那会把 provider 面的判据悄悄换成开关面的判据（覆盖面被偷换）。
    ``Config`` 类真缺省仍是 ``False``（权威锚由 ``Config.model_fields`` 那条用例钉，本函数只镜像可达态）。

    用 ``SimpleNamespace`` 而非 ``Mock``：``Mock`` 对未设键自动造属性，会让
    ``_build_params`` 的 ``float(getattr(...))`` 拿到 Mock 而崩；``SimpleNamespace`` 缺键走
    ``getattr(..., None)`` ⇒ 回落预设表（真身既有语义）。
    """
    base: dict[str, Any] = {
        "bot_tts_enabled": True,
        "bot_tts_api_url": PROD_API_URL,
        "bot_tts_gptsovits_dir": "",
        "bot_tts_ref_audios": [],
        "bot_tts_output_dir": "",
        "bot_tts_preset": "",
        "bot_tts_hard_max_chars": 0,
        "bot_tts_max_audio_bytes": 0,
        "bot_tts_cache_enabled": True,
        "bot_tts_cache_max_bytes": 0,
        "bot_tts_cache_max_age_days": 0,
        "bot_tts_timeout_seconds": 5.0,
        "bot_creation_tts_provider": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _request(config: Any, payload: dict[str, Any], *, synth: Any = None) -> CapabilityRequest:
    context: dict[str, Any] = {"config": config}
    if synth is not None:
        context["synthesize"] = synth
    return CapabilityRequest(
        capability_id="creation.tts.synthesize",
        payload=payload,
        roles=("user",),
        context=context,
    )


def _ok_synth(path: Path) -> Any:
    calls: list[dict[str, Any]] = []

    def _synth(**kwargs: Any) -> tuple[Any, str]:
        calls.append(kwargs)
        return (path, "")

    _synth.calls = calls  # type: ignore[attr-defined]
    return _synth


def _real_ref(tmp_path: Path) -> tuple[Any, Path]:
    """一条"文件确实存在"的参考音配置 + 一个可交付的假 wav。"""
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF-fake-reference-audio")
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    wav = out / "tts-fake.wav"
    wav.write_bytes(b"RIFFfakepayload")
    cfg = _config(
        bot_tts_ref_audios=[f"{ref}|这是参考干声说的话|zh"],
        bot_tts_output_dir=str(out),
    )
    return cfg, wav


# ---------------------------------------------------------------------------
# ① 正向锁：生产缺省口径 ⇒ provider 门放行（旧散文"恒 False"作废）
# ---------------------------------------------------------------------------


def test_production_default_keeps_provider_gate_open() -> None:
    """真 ``Config`` 缺省 ``bot_tts_api_url`` 非空 ⇒ provider_configured 判 True。

    这直接推翻"未来键不存在 ⇒ 恒 False ⇒ 恒 UNAVAILABLE"旧叙述：门今天就是开的。
    """
    default = Config.model_fields["bot_tts_api_url"].default
    assert isinstance(default, str) and default.strip(), "生产缺省引擎地址为空=前提塌了"
    assert reserved_provider.provider_configured(_config(), "creation.tts") is True


def test_real_config_never_yields_empty_api_url_so_gate_always_open() -> None:
    """更深一层：SSRF 闸（``config.py:1334``）把空 ``bot_tts_api_url`` 一律回落 loopback 缺省
    ⇒ 任何真 ``Config`` 实例的引擎地址恒非空 ⇒ provider 门对真配置**恒开**。

    含义（务必与 §1 判定同行读）：诚实 ``UNAVAILABLE``（"门关"）那一形在**真生产 Config 下不可达**，
    只能由非-Config 鸭子（如 S07 测试）构造；真配置下语音终态只会在 ``NOT_CONFIGURED``（缺参考音）
    与 ``OK``（参考音齐备+引擎在跑）之间切换。下一发用真 ``Config`` 坐实这条判据。
    """
    cfg = Config(bot_tts_api_url="")  # 显式想关，被闸弹回 loopback 缺省
    assert cfg.bot_tts_api_url == PROD_API_URL
    assert reserved_provider.provider_configured(cfg, "creation.tts") is True


def test_handle_no_reference_is_honest_not_configured_not_unavailable(tmp_path: Path) -> None:
    """门开、无参考音 ⇒ ``NOT_CONFIGURED``（不是 ``UNAVAILABLE``），且一次都不打合成。

    这条是"语音可用不是预留"的诚实下限：卡在缺参考音这一确定性配置面，
    而不是卡在"根本没接线"。缺参考音属 ``media.tts.autodub`` 同一 ``no_ref`` 族。
    """
    synth = _ok_synth(tmp_path / "never.wav")
    result = engine_provider.handle(_request(_config(), {"text": "潮汐很安静"}, synth=synth))
    assert result.status is InvocationStatus.NOT_CONFIGURED
    assert result.status is not InvocationStatus.UNAVAILABLE
    assert synth.calls == []  # no_ref 在打引擎前短路
    assert result.data == {}  # 非成功态不带结果体（铁律 4 / 信封不变量）


def test_honest_unavailable_requires_all_presence_keys_empty() -> None:
    """三把在场键全空才诚实 ``UNAVAILABLE``（门关的这一形要一起关，非半开）。

    ⚠ 这一形在真 ``Config`` 下不可达（见上一条），故用鸭子构造"门关"——只证判据形状，
    不宣称生产真能走到这里。
    """
    closed = _config(bot_tts_api_url="", bot_tts_ref_audios=[], bot_creation_tts_provider="")
    synth = _ok_synth(Path("/never.wav"))
    result = engine_provider.handle(_request(closed, {"text": "门关着就不该打引擎"}, synth=synth))
    assert result.status is InvocationStatus.UNAVAILABLE
    assert synth.calls == []


# ---------------------------------------------------------------------------
# ② 总开关锁：creation.tts 首道读 bot_tts_enabled（行为锁 + 结构特征锁）
#    原为 GAP-CREATION-TTS-NO-KILLSWITCH 活雷（xfail）。主代理 2026-09-24T00:57Z 落真修
#    （`handle` 在契约校验后**第一件事**就是查该键、关则 `NOT_CONFIGURED` 且不打引擎），
#    按本件自述的摘牌条件摘 xfail，并把结构锁**翻转成反向钉**（读 ⇒ 绿、不读 ⇒ 红）。
# ---------------------------------------------------------------------------


def test_kill_switch_stops_creation_tts_without_touching_engine(tmp_path: Path) -> None:
    """bot_tts_enabled=False ⇒ 诚实 NOT_CONFIGURED，且**不产音、不打引擎**。

    断到 `via` 与 detail 点名键，是为了杀掉两种假修：
    ①只把状态改成非 OK 但仍在 provider 分支里打了引擎；②在任何位置查了别的键冒充总开关。
    """
    cfg, wav = _real_ref(tmp_path)  # 有可用参考音（ ⇒ 旧缺陷形态下会真产音）
    cfg.bot_tts_enabled = False
    result = engine_provider.handle(
        _request(cfg, {"text": "总开关关着，本不该发声"}, synth=_ok_synth(wav))
    )
    assert result.status is InvocationStatus.NOT_CONFIGURED, (
        f"总开关关却返 {result.status!r} ⇒ 禁用面未执法"
    )
    assert result.via == "creation_tts_killswitch", (
        f"终态来自 {result.via!r} 而非首道开关闸 ⇒ 可能在开关之前就动了引擎"
    )
    assert "bot_tts_enabled" in (result.detail or ""), (
        f"detail 未点名被关的键：{result.detail!r} ⇒ 不可归因"
    )
    assert not getattr(result, "data", None), "禁用态却带了产出体 ⇒ 冒充成功"


def test_handle_body_reads_killswitch_first() -> None:
    """结构特征锁（反向钉）：``handle`` 体必须引用 ``bot_tts_enabled``。

    与上面的行为锁配成对：散文/行为/结构三处互钉，缺一即红。谁把首道检查删掉，
    本门当场红（不必等真机）。读法与命令路 ``tts.py:1078`` 同构（``getattr(..., False)``
    ⇒ 缺键即关＝fail-closed）。
    """
    tree = ast.parse(PROVIDER_PATH.read_text(encoding="utf-8"))
    handle_fn = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "handle"
    )
    reads_enabled = any(
        (isinstance(n, ast.Attribute) and n.attr == "bot_tts_enabled")
        or (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "getattr"
            and len(n.args) >= 2
            and isinstance(n.args[1], ast.Constant)
            and n.args[1].value == "bot_tts_enabled"
        )
        for n in ast.walk(handle_fn)
    )
    assert reads_enabled is True, (
        "handle 不再读 bot_tts_enabled ⇒ 总开关对 creation.tts 失效（本波曾以此形态"
        "把「关了就什么都不发」写成假叙述）。要回退请先改回本锁与行为锁并登记 PARKED。"
    )


# ---------------------------------------------------------------------------
# ③ 注毒有牙：三发 monkeypatch，各证一条正向/诚实判据不是空跑
# ---------------------------------------------------------------------------


def test_teeth_poison_always_unavailable_breaks_not_configured_claim() -> None:
    """注毒：provider 门"恒 False"（旧退化形）⇒ no-ref 场景由 NOT_CONFIGURED 塌成 UNAVAILABLE。

    证 ``test_handle_no_reference_is_honest_not_configured`` 有牙：若有人把判据改回
    "恒 False"，那条断言当场红（本发用反向毒演示受害态真会发生）。
    """
    with mock.patch.object(reserved_provider, "provider_configured", lambda *a, **k: False):
        result = engine_provider.handle(_request(_config(), {"text": "毒：门关死"}))
    assert result.status is InvocationStatus.UNAVAILABLE  # 受害态＝正向锁会红的那一态


def test_teeth_poison_always_available_breaks_honest_unavailable() -> None:
    """注毒：provider 门"恒 True"（无视空值）⇒ 三键全空场景不再是 UNAVAILABLE。

    证 ``test_honest_unavailable_requires_all_presence_keys_empty`` 有牙：把门焊成恒开会
    让诚实 UNAVAILABLE 那一格失守（本发证明该态在毒下真会变，非写死的存在性断言）。
    """
    closed = _config(bot_tts_api_url="", bot_tts_ref_audios=[], bot_creation_tts_provider="")
    with mock.patch.object(reserved_provider, "provider_configured", lambda *a, **k: True):
        result = engine_provider.handle(_request(closed, {"text": "毒：门焊开"}, synth=_ok_synth(Path("/x"))))
    assert result.status is not InvocationStatus.UNAVAILABLE  # 焊开后 no-ref→NOT_CONFIGURED


def test_teeth_poison_fold_ok_without_product_is_caught(tmp_path: Path) -> None:
    """注毒：产出步自称 ok 却交不出 audio_file ⇒ 仍判失败（铁律 4 / 不冒充成功）。

    证失败面不被"别人替我造的 ok"污染：monkeypatch ``synthesize_autodub`` 返回无产物的
    ``ok``，``handle`` 必落非 OK、不带结果体。
    """
    cfg, wav = _real_ref(tmp_path)
    with mock.patch.object(
        tts, "synthesize_autodub", lambda *a, **k: ("ok", {"preset_id": "poisoned"})
    ):
        result = engine_provider.handle(_request(cfg, {"text": "空口无凭"}, synth=_ok_synth(wav)))
    assert result.status is not InvocationStatus.OK
    assert result.data == {}
