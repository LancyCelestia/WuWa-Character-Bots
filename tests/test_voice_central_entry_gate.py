"""G-4 统一性机器门 · 第一道：TTS 合成出站必经中央管线入口（Wave G · T77）。

病根（plan-G-contract.md §G-4）：「中央统一有一部分是假的」——没有机器门时，
旁支直连（自己拼引擎请求体、绕开装配点直接 POST、不体检就落盘、绕开缓存身份、
绕开打码+内容门取文、从别处 import 私有管线件拼第二条出站路）不会被任何东西
拦住，中央契约层（docs/design/tts-contract-layer.md §4 管线十阶段）就退化成
「恰好只有一条路时才成立」的君子协定。

本门把「出站必经中央」写成 AST 静态断言，主对象 = **登记在册的全部语音产出出站
路径**（FIX8 2026-09-21 扩面：此前只读 tts.py 一个文件，G-3 落地的第二出站路
``domains/media/voice_enricher.py`` 一条不变量都不在射程内。S80 2026-09-24 二次
扩面：补第三在册路 ``domains/media/tts/result_transform.py`` ——它经
``autodub_presentation_update`` 挂回音频，而旧检测器只认 ``audio=`` /
``update={"audio": …}`` 两形态，对它**物理失明**，"加了第三条路没人知道" 恰是本
射程穷举锁自己声称要治的病）。检测器接受任意源码串，故可对
注入的坏样本自证杀伤力：

  A1 请求体唯一装配点：``_request_tts`` 内 httpx ``.post(json=…)`` 的请求体必须
     来自 ``_build_request_payload(...)``（直接调用或绑定其返回值的变量）；且
     全模块 ``.post(`` 只允许出现在 ``_request_tts`` 体内（第二 HTTP 路径即红）。
  A2 体检闸绑死落盘/缓存：``write_bytes`` / ``_store_cache`` 调用只允许出现在
     synthesize 内，且同函数内 ``_inspect_wav_bytes`` 调用在先——「不可播字节
     绝不落盘、绝不入缓存」从注释变成机器断言。
  A3 取文口先行：**产出步**的每个调用方函数必须先调 ``resolve_speech_text``
     （打码→清洗→词典→内容门的唯一取文口），行序在前——文字面被拦的语音
     不可能从旁路溜出去（M-02/M-03 语义的结构锁）。「产出步」= 直呼
     ``synthesize(`` **或** 中央 ``invoke(CapabilityRequest(capability_id="media.tts.autodub"))``
     （VOICE-V12 后 hook 的产出步是后者，不是直呼；S80 改锚，判据语义不变）。
     注入产出缝（``dub`` / ``synth_fn``）**不在** A3 射程，只在 A4 记为来路——理由
     见 ``_INJECTED_PRODUCTION_SEAM_NAMES`` 注释，并登记为残留（§边界）。
     S97 seam-provider 豁免（S91 退役内联后）：一个含中央 autodub 产出步的函数，若其
     invoke 的 payload ``text`` 是**本函数形参**（seam provider，文本从外面交进来）**且**
     本模块以两条派生腿之一兑现「取文义务另有兑现处」（见 ``_module_proves_text_gating``：
     腿A 派发 ``media.tts.autodub_transform`` 把义务交给真身 result_transform ∨ 腿B 同模块
     某函数**先** ``resolve_speech_text`` **后**喂注入产出缝，即真身自己把干净文本送进缝），
     则豁免「函数内先 resolve_speech_text」——把义务归到它真正兑现的地方，而非钉在一个物理上
     不取文的闭包上（假红）。两腿皆从 AST 派生、**非**白名单点名。豁免只认这一对：只 invoke
     autodub、既不派发真身又不「先取文后喂缝」的纯旁支不豁免，A3 照红；且豁免**按函数**生效，
     同模块再冒一枚 text 非形参的中央 invoke 照样红（杀伤力见
     ``test_mutate_enricher_autodub_without_transform_dispatch_caught_by_a3`` 与
     ``test_mutate_transform_text_gate_removed_caught_dub_via_central_by_a3``）。
  A4 音频出站构造绑定产出步：模块内任何「音频到得了用户」的站点——自建出站体
     （``audio=`` kwarg 直挂或 ``update={"audio": …}``）与中央呈现漏斗
     （``autodub_presentation_update(…)``）——所在函数必须先有过一次产出步
     （直呼 synthesize / 中央 autodub invoke / 在册注入缝）——「音频来路不明」即红。
     第二支（S80 补）：**同一函数既走中央漏斗又自建 audio 出站体即红**——把在册口径
     「层 1 不自拼出站体」从散文升成机器断言（此前无人执法）；命令路/旧包装只自建、
     不走漏斗，逐字节不受影响。
     第三支（S80 补）：**直呼 synthesize 与中央 invoke 产出步在同一射程内并存即红**
     （半迁移=第二通路）。判据取"并存"不取"有直呼"，否则 tts.py 的在册直呼路会被
     一起打红；纯直呼（收编前世界）与纯中央（收编后世界）都不触发此支。
  A5 私有面不外借：plugins/** 其他模块禁止以静态 import、属性访问或字符串
     形态引用私有管线件（_request_tts/_build_request_payload/_inspect_wav_bytes/
     _cache_identity/_cache_key/_store_cache/_lookup_cache）。

负样本自检（plan-G §G-4 原文「负样本必须真能抓：只加正例的门等于没加」）：
每条规则配「注入坏样本 → 门变红」用例；另配一份忠实迷你管线正例对照，
防检测器过度开火（永远红的门同样等于没加）。FIX8 追加**逐在册路径**的变异自检：
以真身 ``voice_enricher.py`` 源码为底本做单点文本变异（不碰生产文件），
证明 A1-A4 对第二出站路真的承重，而不是「恰好也绿」。S80 2026-09-24 把这组
变异自检**换成现役形状的锚点**（中央 invoke 站点、呈现漏斗、注入产出缝），并给
新在册的第三路 ``result_transform.py`` 配同型自检——旧锚点 ``path, reason =
synthesize(`` 与「voice_enricher 必有 synthesize 直呼点」这条活性判据随 VOICE-V12
一起失效，门对第二路从此**全部空转**（A1-A4 无一条能落地），这正是本门自己的
活动锁该抓、也确实抓到了的「登记了但没构造点的假扩面」。
S285C 2026-09-25 三次跟随（S270 归位后；逐字交代，不静默改绿）：S270 把全树唯一一处
``media.tts.autodub`` 字面中央 invoke 从 hook 的 ``_dub`` 搬进真身自身的单一组合口
``result_transform.dub_via_central``——**归位是mandate「同一能力全树只准一处」的正解，
不是判据放松**，但本门的三处硬编码前提随物理拓扑翻面而失效（活动锁把「hook 持中央产出步」
钉成活性判据；三条 mutation 底本把「中央 invoke 在 hook / 真身不持产出步」当默认前提）。
本波只做未落那一半：①活动锁按归位后拓扑**逐路换锚**（hook 查「派发变换形 ∧ 把产出步让给
组合口」，「持有中央产出步」这条正向祝福改指真身并升成**唯一持有者**判据）；②三条 mutation
底本各锚一个归位后仍成立的杀伤面（纯旁支/第二 invoker→忠实合成件；跳过取文口→真身 self-gate
腿正向件；退回直呼→底本换持中央产出步的真身），判据强度**只升不降**——用例数 41→42，
零删除、零白名单新增、零 skip/xfail。三形逐发注毒自证见各用例 docstring。

射程穷举锁（``test_gate1_scan_set_is_exhaustive_over_plugins_tree``）：在册集合不是手抄
清单——每次运行都用本门自己的检测器重扫 ``plugins/**``，凡出现新的**产出步站点**
（直呼 ``synthesize(`` 或字面 ``invoke(…capability_id="media.tts.autodub")``）或新的
**音频出站点**（自建 ``audio=`` / ``update={"audio": …}`` 与中央呈现漏斗
``autodub_presentation_update(``）而未登记/未豁免，门直接红（治「加了第三条路没人知道」）。
注入产出缝名（``dub``/``synth_fn``）**不作**穷举判据——那是两个通用变量名，拿它当
发现信号会把无关文件拖进射程；发现面只认「字面能力 id」这种语义锚。

边界与已知残留（诚实登记）：capabilities/tts.py 兼容垫片（PEP 562 透传）按
v21r2 契约原样保留，其运行时 getattr 透传面不在本门静态射程内；根 __init__.py
的 hook 装配双态互斥归 G-3/T73 门（tests/test_voice_hook_assembly.py）；
点歌/链接解析/出站 sender 三处 ``audio=`` 构造的是**源媒体**而非合成产物，
按 ``_NON_TTS_AUDIO_CONSTRUCTION_SITES`` 显式豁免（豁免=登记理由，不是静默放过）；
A5 私有面清单只钉 7 枚管线件，``voice_enricher`` 依 G-3 设计复用的
``_build_params``/``_resolve_preset``/``_output_dir``/``_failure_issue`` 等**不在**该清单内
（规格 §4.2 明文允许「只消费其模块级构件」），扩钉这些名字会让门对现存生产码红，
故登记为残留不修、交裁决。
S80 新登记两枚**结构性盲区**（只点名不掩盖，均非本席可修面）：
① ``tts.synthesize_autodub`` 的产出点是 ``synth_fn(...)`` 形态的**注入合成原语**，
   A3「取文口先行」按调用名识别 ⇒ 对它不落地。该函数的契约是「入参=已过内容门与
   硬顶的干净文本」（其 docstring 自述），取文义务在上层消费方，A3 按名判据**结构上
   无法**核验参数来路 ⇒ 要真覆盖必须给「文本走形参进入」的函数立一条在册豁免，
   那是设计裁决、不是本席放松断言。改锚前该函数同样不被 A3 覆盖（callee 名不同），
   故此项**不是本波引入的退化**，是把既存空转写明。
② ``creation.tts.synthesize``（协议对接点、台账 #49 记为「只声明未接线」）不列入
   ``_CENTRAL_PRODUCTION_CAPABILITY_IDS``：它不是 media 语音出站的现役产出步，
   列入会让 ``domains/creation/tts/routes.py`` 的探针调用无端进射程。若那条腿通电，
   本门的 cid 集合与在册清单须同时跟随。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugins" / "bot_unified_runtime"
_TTS_SOURCE = _PLUGIN_ROOT / "domains" / "media" / "capabilities" / "tts.py"
# FIX8 扩面：G-3 配音 hook 是**第二条**语音产出出站路，旧版门只读 tts.py，
# 对它一条不变量都不承重。（该席当时写「synthesize 直连 + update={"audio": …}」
# 并钉了行号 :175/:200——两处形态与行号都随 VOICE-V12 变了；S80 把锚换成语义锚，
# 判据要防的那类回归不变，见模块 docstring「S80 2026-09-24 二次扩面」。原门在
# 换锚前对该文件**全部空转**，故此处如实记账而非沿用旧措辞。）
_VOICE_ENRICHER_SOURCE = _PLUGIN_ROOT / "domains" / "media" / "voice_enricher.py"
# S80 在册第三路：配音「结果变换形」执行体（S36 交付；**S91 已收编进中央注册册并通电**
# ——descriptor + handler + voice_enricher 唯一 invoke 点，活性锁见
# tests/test_voice_enricher_central_dispatch.py；旧措辞「尚未接根装配/未进中央注册册」
# 是 S36 落件当时的状态，S253B 现算推翻、S261 跟随措辞）。它在盘上就是一条能把音频挂到
# 呈现契约上的出站路，本门按「路径存在即受约」登记；今天它**关态不可达**
# （``bot_tts_voice_hook_enabled`` 缺省 False 且生产 ``.env`` 未设 ∧
# ``bot_tts_auto_reply_enabled=false``）——这条运营态照实记，但不构成把它挡在射程外的
# 理由（挡在外面=门瞎）。
_RESULT_TRANSFORM_SOURCE = _PLUGIN_ROOT / "domains" / "media" / "tts" / "result_transform.py"

# 在册语音产出出站路径全集（A1-A4 逐文件生效；新增路必须在这里登记，
# 否则 test_gate1_scan_set_is_exhaustive_over_plugins_tree 直接红）。
_VOICE_OUTBOUND_SOURCES: tuple[Path, ...] = (
    _TTS_SOURCE,
    _VOICE_ENRICHER_SOURCE,
    _RESULT_TRANSFORM_SOURCE,
)

# ==== 产出步与音频出站点的语义锚（S80 换锚；名字判据一律取符号，不取行号）====
#
# 直呼产出原语（命令路 + 旧包装路，真身在 tts.py）。
_DIRECT_PRODUCTION_CALLEES: frozenset[str] = frozenset({"synthesize"})
# 中央产出步（VOICE-V12：hook 不再直呼 synthesize，产出这一步经中央 invoker；
# S270 归位后这发字面 invoke 唯一住在真身 result_transform.dub_via_central，见活动锁）。
# 只认 CapabilityRequest 的**字面** capability_id——把 id 参数化传进来＝给 AST 普查
# 造盲区（result_transform.py docstring 第 1 条理由与此同源），故非字面量一律不记。
_CENTRAL_PRODUCTION_CAPABILITY_IDS: frozenset[str] = frozenset({"media.tts.autodub"})
# 中央「结果变换形」派发步（S91 把「取文→硬顶→逐块合成→合并→挂回」整段搬进真身
# result_transform 后，hook 只派发这一步）。它**不是**产出步（本件不合成、音频仍在
# 内层 autodub 产出），故绝不进 _CENTRAL_PRODUCTION_CAPABILITY_IDS——纳进会把「派发
# 变换形」误当成一次合成，且让 result_transform 那条只 call dub(chunk) 的真身凭空多出
# 一枚产出步。这里单列，只为 A3 的 seam-provider 豁免**腿A**（「本模块确实把取文义务交给
# 真身」）供前置事实，见 _module_proves_text_gating；不作产出步/呈现站点/穷举发现信号。
_TRANSFORM_DISPATCH_CAPABILITY_IDS: frozenset[str] = frozenset({"media.tts.autodub_transform"})
# 注入产出缝（装配现场把「一段干净文本→一次配音结果」包成 callable 交进来）：
# **只**在 A4 里记为「来路」，**不**进 A3、**不**作穷举发现信号。
# 为什么这样切：A3 的语义是「谁产出谁先取文」，而缝函数的文本是**形参交进来的**
# （synthesize_autodub / transform_presentation 的入参已是过门干净文本），按名判据
# 结构上验不了参数来路 ⇒ 纳进 A3 只会对现存生产码造一条假红（并把真判据淹在噪声里）。
# 代价如实写：拿这两个通用名字命名的自建产出门逃得过 A4 ⇒ 记为残留 ①，非本席可修面。
_INJECTED_PRODUCTION_SEAM_NAMES: frozenset[str] = frozenset({"dub", "synth_fn"})
# 音频到得了用户的两形态：自建出站体（可疑，A4 原本就管）与中央呈现漏斗
# （合规口，但它同样要求「本函数内先有产出步」——不自拼不等于凭空出）。
_AUDIO_PRESENTATION_FUNNELS: frozenset[str] = frozenset({"autodub_presentation_update"})
# 单一组合口（S270 归位，S285C 落账）：hook 把「一段干净文本→一段音频」这一步交出去的
# **唯一**被调名，真身 = ``result_transform.dub_via_central``——全树唯一一处 autodub 字面
# 中央 invoke 住在它里面（本文件的中央产出步站点从此在 hook 归零、在真身出现）。
# 它**只**作活动锁的活性判据（「hook 今天承重的动作 = 派发真身 + 把产出步让给组合口」），
# **不**进 A3/A4 判据、**不**作射程穷举的发现信号：纳进 A3 会把「把产出步让给真身」这一
# 在册委托形状判成「产出步没取文」=假红，纳进穷举面则等于给两个通用名字之外的第三个
# 名字开第二本账。
_COMPOSITION_DELEGATION_CALLEES: frozenset[str] = frozenset({"dub_via_central"})

# 非合成音频构造面豁免表：posix 相对路径（相对 _PLUGIN_ROOT）→ 豁免理由。
# 判据=该 audio 的来路是**上游源媒体/出站转换**，不是 TTS 合成产物，
# 因此 A3（取文口先行）/A4（audio 出站绑定产出步）对其无意义；豁免是
# **显式登记**（含理由），出现新构造点而未进本表 ⇒ 门红，不许静默放过。
# （同族第三形态：上游**在册语音路径**产出的 CapabilityResult.audio 透传——
# 合成真身已在 tts.py 受 A1-A4 管辖，构造点本层零合成，A3/A4 同样无意义。）
_NON_TTS_AUDIO_CONSTRUCTION_SITES: dict[str, str] = {
    "domains/link_parse/capabilities/content_parser.py": (
        "链接解析产物：audio 段来自平台侧已有音轨（点歌/视频音轨），非合成"
    ),
    "domains/music/capabilities/music.py": (
        "点歌能力：audio 段=供应商返回的音频文件资产，非合成"
    ),
    "domains/transport/sender/nonebot.py": (
        "出站 sender：把 CapabilityResult.audio 转成 OneBot 段的传输层构造，"
        "产物身份由上游中央管线决定，本层不得再合成"
    ),
    "__init__.py": (
        "根 __init__ 戳一戳语音臂出站（_send_parts_through_unified_pipeline."
        "_capability 与 _handle_poke_notice 两构造点）：audio 段=语音臂 "
        "_poke_voice_pair 交层2主缝（orchestrated_command(\"bot.tts\")）产出的 "
        "CapabilityResult.audio 透传，本层零合成；合成真身在在册语音路径 tts.py"
        "（A1-A4 管辖），本构造仅把结果挂上统一管线出站面（与 transport sender 同族）"
    ),
}

# 私有管线件（下划线族）：只许在 tts.py 模块内出现，出借即旁支。
_PRIVATE_PIPELINE_NAMES: frozenset[str] = frozenset(
    {
        "_request_tts",
        "_build_request_payload",
        "_inspect_wav_bytes",
        "_cache_identity",
        "_cache_key",
        "_store_cache",
        "_lookup_cache",
    }
)

# 白名单：引擎 HTTP 请求 / 音频落盘 / 缓存写入 只许发生的函数。
_HTTP_POST_ALLOWLIST: frozenset[str] = frozenset({"_request_tts"})
_DISK_WRITE_ALLOWLIST: frozenset[str] = frozenset({"synthesize"})
_CACHE_STORE_ALLOWLIST: frozenset[str] = frozenset({"synthesize"})


# ==================== 检测器基座（对任意源码可复用，负样本靠它注入） ====================


@dataclass(frozen=True)
class _Site:
    """模块内一个关注点：最内层 enclosing 函数名 + 行号 + 形态。"""

    func_name: str
    lineno: int
    callee: str = ""  # call 形态：被调名末段（client.post → post）
    label: str = ""  # audio 关键字形态：audio= / update={'audio': …}
    cid: str = ""  # invoke 站点的字面 capability_id（非字面量留空=不记）
    funnel: bool = False  # 中央音频呈现漏斗调用（autodub_presentation_update 等）


def _parse(source: str) -> ast.Module:
    return ast.parse(source)


def _callee_name(call: ast.Call) -> str:
    """被调名末段：Name 直呼或 Attribute 链末段（client.post → post）。"""
    func: ast.expr = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _literal_keyword(call: ast.Call, name: str) -> str:
    """取 ``call`` 上名为 ``name`` 的**字符串字面量**关键字实参；非字面量回 ""。"""
    value = _keyword_value(call, name)
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return ""


def _invoked_capability_id(call: ast.Call) -> str:
    """``invoke(...)`` 这一发打在哪个能力上（只认字面量，见常量注释）。

    两种现役写法都覆盖：``invoke(CapabilityRequest(capability_id="…", …))``（层 1
    现场）与 ``invoke(request)``（非字面量 ⇒ 故意不记，参数化 id 不作判据）。
    """
    for node in ast.walk(call):
        if isinstance(node, ast.Call) and _callee_name(node) == "CapabilityRequest":
            cid = _literal_keyword(node, "capability_id")
            if cid:
                return cid
    return _literal_keyword(call, "capability_id")


def _module_sites(tree: ast.Module) -> list[_Site]:
    """单趟扫描：按最内层函数归属全部函数调用与 audio= 出站构造点。"""
    sites: list[_Site] = []
    stack: list[str] = ["<module>"]

    class _Visitor(ast.NodeVisitor):
        def _enter_fn(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._enter_fn(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._enter_fn(node)

        def visit_Call(self, node: ast.Call) -> None:
            callee = _callee_name(node)
            sites.append(
                _Site(
                    func_name=stack[-1],
                    lineno=node.lineno,
                    callee=callee,
                    cid=(
                        _invoked_capability_id(node)
                        if callee == "invoke"
                        else ""
                    ),
                    funnel=callee in _AUDIO_PRESENTATION_FUNNELS,
                )
            )
            for kw in node.keywords:
                if kw.arg == "audio":
                    sites.append(
                        _Site(
                            func_name=stack[-1],
                            lineno=kw.value.lineno,
                            label="audio=",
                        )
                    )
                elif (
                    kw.arg == "update"
                    and isinstance(kw.value, ast.Dict)
                    and any(
                        isinstance(k, ast.Constant) and k.value == "audio"
                        for k in kw.value.keys
                    )
                ):
                    sites.append(
                        _Site(
                            func_name=stack[-1],
                            lineno=kw.value.lineno,
                            label="update={'audio': …}",
                        )
                    )
            self.generic_visit(node)

    _Visitor().visit(tree)
    return sites


# ==== 站点分类（判据的单一解读口，A3/A4 与活动锁、穷举锁共用，禁各写一份）====


def _central_production_sites(sites: list[_Site]) -> list[_Site]:
    """中央产出步站点：字面 autodub 能力的 ``invoke(...)``。"""
    return [
        s
        for s in sites
        if s.callee == "invoke" and s.cid in _CENTRAL_PRODUCTION_CAPABILITY_IDS
    ]


def _transform_dispatch_sites(sites: list[_Site]) -> list[_Site]:
    """中央「结果变换形」派发站点：字面 autodub_transform 的 ``invoke(...)``。

    这不是产出步，也不是音频出站点——只为 A3 seam-provider 豁免提供「本模块确实把
    取文义务交给了真身」这一前置事实（S91 退役内联后，hook 里再无 resolve_speech_text，
    取文整体搬进它派发的这发 autodub_transform）。
    """
    return [
        s for s in sites if s.callee == "invoke" and s.cid in _TRANSFORM_DISPATCH_CAPABILITY_IDS
    ]


def _composition_delegation_sites(sites: list[_Site]) -> list[_Site]:
    """把产出步让给单一组合口的委托站点（``dub_via_central(...)``，S270 归位后 hook 的产出动作）。

    与 ``_transform_dispatch_sites`` 同性质：**只**供活动锁点名「这一路今天靠什么承重」，
    不是 A3/A4 的产出步、不是呈现站点、不是穷举发现信号（理由见常量注释）。
    """
    return [s for s in sites if s.callee in _COMPOSITION_DELEGATION_CALLEES]


def _module_proves_text_gating(tree: ast.Module, sites: list[_Site]) -> bool:
    """A3 seam-provider 豁免的「取文义务另有兑现处」总判据（两腿，皆从 AST **派生**）。

    归位前（S97 时代）：唯一持有 autodub 中央产出步的 seam provider 是 hook 的 ``_dub``，
    它把「取文→清洗→内容门」整段交给真身 result_transform ⇒ 用「本模块派发 autodub_transform」
    （dispatch 腿）当委托凭证。

    归位后（S270 单一组合口）：全树唯一一处 autodub 字面中央 invoke 搬进真身自身的
    ``dub_via_central``，真身不派发自己 ⇒ dispatch 腿对它恒假（旧判据在此造假红＝本门 7 红的
    根）。真身的取文义务由它**自己**兑现：``transform_presentation`` 先调 ``resolve_speech_text``
    再把干净文本喂给注入产出缝 ``dub(chunk)``，而 ``dub_via_central`` 的 payload ``text`` 正是
    这条缝的入参 ⇒ 「同模块存在某函数先取文、后调注入产出缝」是「喂进产出缝的文本已过取文口」
    的结构证据（self-gate 腿）。

    两腿任一成立才豁免，且都从 AST 派生、非白名单点名（防「豁免理由只活在散文里」那类假绿）：
      腿A dispatch —— 模块派发 autodub_transform（义务委托给真身）；
      腿B self-gate —— 某函数内 ``resolve_speech_text`` 行号 < 同函数内最早一枚注入产出缝
                       （``dub``/``synth_fn``）调用行号（真身自证「喂进缝的文本已取文」）。
    只 invoke autodub、既不派发真身、又不「先取文后喂缝」的纯旁支：两腿皆假 ⇒ seam provider 不豁免
    ⇒ A3 照红（杀伤力逐发见 ``test_mutate_enricher_autodub_without_transform_dispatch_caught_by_a3``
    与 ``test_mutate_transform_text_gate_removed_caught_dub_via_central_by_a3``）。
    """
    # 腿A：委托给真身（保留 S97 原语义，一毫不缩）。
    if _transform_dispatch_sites(sites):
        return True
    # 腿B：真身自证「先取文、后喂缝」——按函数归集 resolve 与注入产出缝的最早行号。
    resolve_first: dict[str, int] = {}
    seam_first: dict[str, int] = {}
    for site in sites:
        if site.func_name == "<module>":
            continue
        if site.callee == "resolve_speech_text":
            known = resolve_first.get(site.func_name)
            if known is None or site.lineno < known:
                resolve_first[site.func_name] = site.lineno
        elif site.callee in _INJECTED_PRODUCTION_SEAM_NAMES:
            known = seam_first.get(site.func_name)
            if known is None or site.lineno < known:
                seam_first[site.func_name] = site.lineno
    return any(
        fn in resolve_first and resolve_first[fn] < seam_at for fn, seam_at in seam_first.items()
    )


def _request_payload_text_value(call: ast.Call) -> ast.expr | None:
    """取 ``invoke(...)`` 内 CapabilityRequest 的 ``payload={"text": …}`` 值表达式。

    只认 payload 是**内联字典字面量**且 text 键为常量字符串的形态（现役 autodub
    请求正是此形）；payload 走变量/非字典 ⇒ 回 None（不猜来路，与 `_invoked_capability_id`
    「非字面量不记」同一哲学）。
    """
    for node in ast.walk(call):
        if isinstance(node, ast.Call) and _callee_name(node) == "CapabilityRequest":
            payload = _keyword_value(node, "payload")
            if isinstance(payload, ast.Dict):
                for key, value in zip(payload.keys, payload.values, strict=True):
                    if isinstance(key, ast.Constant) and key.value == "text":
                        return value
            return None
    return None


def _seam_provider_production_funcs(tree: ast.Module) -> set[str]:
    """被 A3 seam-provider 豁免的函数名集合。

    判据（三条同时成立才进）：①该函数体内含一枚字面 autodub 产出步 ``invoke``；
    ②该 invoke 的 payload ``text`` 实参是**本函数形参**（即文本是「从外面交进来的干净
    文本」——seam provider，A3 按名判据结构上验不了参数来路，见模块 docstring 残留 ①）；
    ③由调用方保证模块兑现「取文义务另有兑现处」（两腿之一：派发真身 ∨ 同模块先取文后喂缝，
    A3 循环里现算，不在此判）。

    为什么这样切而不失杀伤力（S91 §7.3 第 1 点）：退役内联后，「取文口先行」的义务
    随整段变换搬进真身 result_transform（source #3，S80 对其 A3 仍硬查）。hook 里的
    ``_dub`` 只是把「一段干净文本→一段音频」包成闭包交中央——它的文本是形参 ``chunk``，
    不是它自己取的。若对它照旧要求「函数内先 resolve_speech_text」，等于把义务钉在
    一个物理上不取文的地方 ⇒ 假红。但豁免**只**认「seam provider ∧ 模块确实派发真身」
    这一对：只 invoke autodub、从不派发 transform 的**纯旁支**（义务没交给任何真身，
    text 从哪来无从归因）不在此列，A3 照红。杀伤力原样保留。
    """
    result: set[str] = set()
    for fn in (
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    ):
        args = fn.args
        params = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
        if args.vararg is not None:
            params.add(args.vararg.arg)
        if args.kwarg is not None:
            params.add(args.kwarg.arg)
        for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
            if _callee_name(call) != "invoke":
                continue
            if _invoked_capability_id(call) not in _CENTRAL_PRODUCTION_CAPABILITY_IDS:
                continue
            text_value = _request_payload_text_value(call)
            if isinstance(text_value, ast.Name) and text_value.id in params:
                result.add(fn.name)
                break
    return result


def _direct_production_sites(sites: list[_Site]) -> list[_Site]:
    """直呼产出原语站点（``synthesize(``）。"""
    return [s for s in sites if s.callee in _DIRECT_PRODUCTION_CALLEES]


def _governed_production_sites(sites: list[_Site]) -> list[_Site]:
    """A3 射程的「产出步」= 直呼 ∪ 中央 invoke（注入缝按常量注释刻意排除）。"""
    return _direct_production_sites(sites) + _central_production_sites(sites)


def _provenance_sites(sites: list[_Site]) -> list[_Site]:
    """A4 认的「来路」= A3 产出步 ∪ 在册注入缝。"""
    return _governed_production_sites(sites) + [
        s for s in sites if s.callee in _INJECTED_PRODUCTION_SEAM_NAMES
    ]


def _self_built_audio_sites(sites: list[_Site]) -> list[_Site]:
    """自建出站体（``audio=`` / ``update={'audio': …}``）——A4 原本就管的可疑形态。"""
    return [s for s in sites if s.label]


def _presentation_sites(sites: list[_Site]) -> list[_Site]:
    """音频到得了用户的全部站点 = 自建出站体 ∪ 中央呈现漏斗。"""
    return _self_built_audio_sites(sites) + [s for s in sites if s.funnel]


def _site_shape(site: _Site) -> str:
    """人话点名站点形态（违规文案与活动锁共用，避免两处各写一套措辞）。"""
    if site.label:
        return site.label
    if site.funnel:
        return f"{site.callee}(…) 呈现漏斗"
    if site.cid:
        return f"中央产出步 invoke({site.cid})"
    return f"{site.callee}(…) 产出步"


def _names_assigned_from(tree: ast.Module, callee: str) -> dict[str, set[str]]:
    """按 enclosing 函数归集 ``x = callee(...)`` 的目标变量名。"""
    assigned: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        if _callee_name(node.value) != callee:
            continue
        owner = _innermost_func_for_lineno(tree, node.lineno)
        for target in node.targets:
            if isinstance(target, ast.Name):
                assigned.setdefault(owner, set()).add(target.id)
    return assigned


def _innermost_func_for_lineno(tree: ast.Module, lineno: int) -> str:
    """包含给定行的最内层函数名；模块级返回 <module>。"""
    best_name = "<module>"
    best_start = -1

    class _Visitor(ast.NodeVisitor):
        def _enter_fn(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            nonlocal best_name, best_start
            end = node.end_lineno if node.end_lineno is not None else node.lineno
            if node.lineno <= lineno <= end and node.lineno > best_start:
                best_start = node.lineno
                best_name = node.name
            self.generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._enter_fn(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._enter_fn(node)

    _Visitor().visit(tree)
    return best_name


def _scan_tts_source(source: str) -> list[str]:
    """门主体：对 tts.py 形态源码跑 A1-A4，返回人话违规清单（空=过门）。"""
    tree = _parse(source)
    sites = _module_sites(tree)
    problems: list[str] = []

    # ---- A1 请求体唯一装配点 ----
    post_sites = [s for s in sites if s.callee == "post"]
    builder_assigned = _names_assigned_from(tree, "_build_request_payload")
    for site in post_sites:
        if site.func_name not in _HTTP_POST_ALLOWLIST:
            problems.append(
                f"A1：函数 {site.func_name} 行 {site.lineno} 出现 .post( HTTP 调用"
                f"（白名单={sorted(_HTTP_POST_ALLOWLIST)}）——引擎请求只许"
                " _request_tts 一处，此为第二请求路径"
            )
    request_posts = [
        s for s in post_sites if s.func_name == "_request_tts"
    ]
    request_builder_calls = [
        s
        for s in sites
        if s.func_name == "_request_tts" and s.callee == "_build_request_payload"
    ]
    for site in request_posts:
        if not request_builder_calls:
            problems.append(
                f"A1：_request_tts 行 {site.lineno} 的 .post( 之前没有"
                " _build_request_payload 调用——请求体装配点被绕开"
            )
            continue
        json_value: ast.expr | None = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.lineno == site.lineno:
                json_value = _keyword_value(node, "json")
                break
        if json_value is None:
            problems.append(
                f"A1：_request_tts 行 {site.lineno} 的 .post( 未带 json= 请求体"
            )
        elif isinstance(json_value, ast.Call):
            if _callee_name(json_value) != "_build_request_payload":
                problems.append(
                    f"A1：行 {site.lineno} 请求体来自 {_callee_name(json_value)}(…)"
                    " 而非 _build_request_payload"
                )
        elif isinstance(json_value, ast.Name):
            bound = builder_assigned.get("_request_tts", set())
            if json_value.id not in bound:
                problems.append(
                    f"A1：行 {site.lineno} 请求体变量 {json_value.id} 并非由 "
                    "_build_request_payload 赋值——旁支直拼"
                )
        else:
            problems.append(
                f"A1：行 {site.lineno} 请求体是内联字面量/表达式——"
                "未经 _build_request_payload 装配"
            )

    # ---- A2 体检闸绑死落盘/缓存写 ----
    for site in sites:
        if site.callee == "write_bytes" and site.func_name not in _DISK_WRITE_ALLOWLIST:
            problems.append(
                f"A2：函数 {site.func_name} 行 {site.lineno} 调用 write_bytes( "
                f"（白名单={sorted(_DISK_WRITE_ALLOWLIST)}）——音频落盘只许 "
                "synthesize 一处"
            )
        if site.callee == "_store_cache" and site.func_name not in _CACHE_STORE_ALLOWLIST:
            problems.append(
                f"A2：函数 {site.func_name} 行 {site.lineno} 调用 _store_cache( "
                "——缓存写入只许 synthesize 一处"
            )
    syn_writes = [
        s
        for s in sites
        if s.func_name == "synthesize" and s.callee in {"write_bytes", "_store_cache"}
    ]
    syn_inspects = [
        s
        for s in sites
        if s.func_name == "synthesize" and s.callee == "_inspect_wav_bytes"
    ]
    if syn_writes and not syn_inspects:
        problems.append(
            "A2：synthesize 落盘/入缓存但全函数未调用 _inspect_wav_bytes"
            "——体检闸被绕开"
        )
    elif syn_writes and syn_inspects:
        first_write = min(s.lineno for s in syn_writes)
        first_inspect = min(s.lineno for s in syn_inspects)
        if first_write < first_inspect:
            problems.append(
                f"A2：synthesize 行 {first_write} 的落盘/缓存写早于行 "
                f"{first_inspect} 的体检——坏字节可能先落盘"
            )

    # ---- A3 取文口先行（产出步 = 直呼 synthesize ∪ 中央 autodub invoke）----
    # seam-provider 豁免（S91 退役内联 → S97 换锚 → S285 跟随 S270 归位）：函数体内含中央 autodub
    # 产出步、但其 payload text 是本函数形参（seam provider），**且**本模块以两条派生腿之一兑现
    # 「取文义务另有其人」（见 _module_proves_text_gating：派发真身 ∨ 真身自证先取文后喂缝）⇒ 豁免。
    # 判据取这一对，**不放行**「只 invoke autodub、既不派发真身又不先取文喂缝」的纯旁支
    # （两腿皆假 ⇒ 不豁免 ⇒ A3 照红，杀伤力保留）。
    seam_funcs = _seam_provider_production_funcs(tree)
    module_gates_text = _module_proves_text_gating(tree, sites)
    for site in _governed_production_sites(sites):
        shape = _site_shape(site)
        if site.func_name == "<module>":
            problems.append(
                f"A3：模块级（行 {site.lineno}）直接产出（{shape}）——"
                "出站装配必须在能力函数内"
            )
            continue
        if module_gates_text and site.func_name in seam_funcs:
            continue
        resolves = [
            s
            for s in sites
            if s.func_name == site.func_name and s.callee == "resolve_speech_text"
        ]
        if not resolves:
            problems.append(
                f"A3：函数 {site.func_name} 行 {site.lineno} {shape}，"
                "但函数内没有 resolve_speech_text——打码/内容门取文口被绕开"
            )
        elif min(s.lineno for s in resolves) > site.lineno:
            problems.append(
                f"A3：函数 {site.func_name} 的 {shape}（行 {site.lineno}）"
                "先于 resolve_speech_text——取文口被绕开"
            )

    # ---- A4 音频出站站点绑定产出步（自建出站体与中央呈现漏斗同判）----
    prod_first: dict[str, int] = {}
    for site in _provenance_sites(sites):
        known = prod_first.get(site.func_name)
        if known is None or site.lineno < known:
            prod_first[site.func_name] = site.lineno
    for site in _presentation_sites(sites):
        shape = _site_shape(site)
        prod_at = prod_first.get(site.func_name)
        if prod_at is None:
            problems.append(
                f"A4：函数 {site.func_name} 行 {site.lineno} 出站 {shape}，"
                "但函数内没有产出步（直呼 synthesize／中央 autodub invoke／在册注入缝）"
                "——音频来路不明"
            )
        elif prod_at > site.lineno:
            problems.append(
                f"A4：函数 {site.func_name} 行 {site.lineno} 的 {shape} "
                f"出站先于行 {prod_at} 的产出步——音频尚未产出即出站"
            )
    # ---- A4 第二支（S80 补）：走中央漏斗的函数禁止再自建 audio 出站体 ----
    # 语义来源=在册口径 VOICE-CENTRAL-UNBLOCK「层 1 从此不自拼出站体」——该口径此前
    # **只有散文没有执法件**（直呼禁令归 dispatch 门，自拼禁令无人管）⇒ 属「叙述为已
    # 执法而未执法」。本支把它变成机器断言，判据取「同函数内漏斗 ∧ 自建」这一对，
    # 因此命令路与旧包装（自建但不经漏斗，退役归 V3 另批）逐字节不受影响。
    for site in _self_built_audio_sites(sites):
        funnels = [
            f for f in sites if f.funnel and f.func_name == site.func_name
        ]
        if funnels:
            problems.append(
                f"A4：函数 {site.func_name} 行 {site.lineno} 自建 {site.label} 出站体，"
                f"但同函数已经中央呈现漏斗（行 {min(f.lineno for f in funnels)}）挂回音频"
                "——层 1 自拼出站体=第二通路，产物身份须只由中央产出步决定"
            )
    # ---- A4 第三支（S80 补）：直呼产出步与中央产出步在同一射程内并存 = 通路没收干净 ----
    # 门名叫 central_entry，就必须在「退役前世界回潮」（hook 改回直呼 synthesize）上发红。
    # 改锚前这一支是**结构性空白**：直呼禁令只在
    # ``tests/test_voice_enricher_central_dispatch.py`` 按「该文件不得有执行直呼」执法，
    # 本门对"直呼 + 中央并存"的半迁移形态无反应 ⇒ 一门顶着中央入口的名字却不拦中央旁路。
    # 判据取"并存"而非"有直呼"：tts.py 命令路与旧包装是**在册直呼路**（无中央 invoke），
    # 按"有直呼即红"会把它们一起打红=过度开火，那两路的退役归 V3 另批。
    direct_sites = _direct_production_sites(sites)
    central_sites = _central_production_sites(sites)
    if direct_sites and central_sites:
        problems.append(
            "A4：本射程内直呼 synthesize（行 "
            f"{sorted(s.lineno for s in direct_sites)}）与中央产出步 invoke"
            f"（行 {sorted(s.lineno for s in central_sites)}）并存"
            "——同一条语音出站路留了两条产出通路，产出步未收干净（第二真身）"
        )
    return problems


def _keyword_value(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _rule_private_import_ban() -> list[str]:
    """A5：plugins/** 其他模块不得引用私有管线件（静态 import/属性/字符串）。"""
    problems: list[str] = []
    canonical = _TTS_SOURCE.resolve()
    for path in sorted(_PLUGIN_ROOT.rglob("*.py")):
        if path.resolve() == canonical:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not any(name in text for name in _PRIVATE_PIPELINE_NAMES):
            continue
        try:
            tree = _parse(text)
        except SyntaxError:
            continue
        module_path = path.relative_to(_PLUGIN_ROOT.parent.parent.parent).as_posix()
        imports_tts = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and (
                node.module == "tts" or node.module.endswith(".tts")
            ):
                imports_tts = True
                for alias in node.names:
                    if alias.name in _PRIVATE_PIPELINE_NAMES:
                        problems.append(
                            f"A5：{module_path}:{node.lineno} 静态 import "
                            f"私有管线件 {alias.name}——旁支直连面"
                        )
            if (
                isinstance(node, ast.Attribute)
                and node.attr in _PRIVATE_PIPELINE_NAMES
                and imports_tts
            ):
                problems.append(
                    f"A5：{module_path}:{node.lineno} 以属性形态访问私有管线件 "
                    f"{node.attr}"
                )
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in _PRIVATE_PIPELINE_NAMES
            ):
                problems.append(
                    f"A5：{module_path}:{node.lineno} 以字符串形态引用私有管线件"
                    f"「{node.value}」（getattr/import_module 旁支形态）"
                )
    return problems


# ==================== 正例门（对全部在册真身源码，逐文件） ====================


def _scan_source(path: Path) -> list[str]:
    """对单在册真身文件跑 A1-A4，违规清单带文件前缀（多路径下可定位）。"""
    rel = path.relative_to(_PLUGIN_ROOT.parent.parent.parent).as_posix()
    return [f"[{rel}] {problem}" for problem in _scan_tts_source(_read(path))]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _scan_registered() -> list[str]:
    return [problem for source in _VOICE_OUTBOUND_SOURCES for problem in _scan_source(source)]


def _production_call_sites(path: Path) -> list[int]:
    """该文件里 A3 射程的产出步行号（直呼 ``synthesize(`` ∪ 中央 autodub invoke）。"""
    tree = _parse(_read(path))
    return [s.lineno for s in _governed_production_sites(_module_sites(tree))]


def _provenance_call_sites(path: Path) -> list[int]:
    """该文件里 A4 认作来路的产出步行号（上一条 ∪ 在册注入缝）。"""
    tree = _parse(_read(path))
    return [s.lineno for s in _provenance_sites(_module_sites(tree))]


def _central_invoke_sites(path: Path) -> list[int]:
    """该文件里字面打在 autodub 能力上的中央 invoke 行号（换锚后的 hook 产出步）。"""
    tree = _parse(_read(path))
    return [s.lineno for s in _central_production_sites(_module_sites(tree))]


def _transform_dispatch_call_sites(path: Path) -> list[int]:
    """该文件里派发 autodub_transform 的 invoke 行号（退役内联后 hook 的「出货」动作）。"""
    tree = _parse(_read(path))
    return [s.lineno for s in _transform_dispatch_sites(_module_sites(tree))]


def _delegated_production_call_sites(path: Path) -> list[int]:
    """该文件里把产出步交给单一组合口 ``dub_via_central`` 的行号（S270 归位后 hook 的产货动作）。"""
    tree = _parse(_read(path))
    return [s.lineno for s in _composition_delegation_sites(_module_sites(tree))]


def _audio_construction_sites(path: Path) -> list[int]:
    """自建 audio 出站行号（kwarg 直挂与 update={'audio': …} 两形态）。

    只含自建形态：豁免表的语义是「这处 audio 是我自己拼的、但来路不是合成」，
    中央呈现漏斗不属于它——混在一起会让反向锁（虚挂检测）判错东西。
    """
    tree = _parse(_read(path))
    return [s.lineno for s in _self_built_audio_sites(_module_sites(tree))]


def _audio_presentation_sites(path: Path) -> list[int]:
    """音频到得了用户的全部行号（自建 ∪ 呈现漏斗）——A4 与穷举锁的射程面。"""
    tree = _parse(_read(path))
    return [s.lineno for s in _presentation_sites(_module_sites(tree))]


# 全树重扫的文本预筛（纯加速，不改变判据）：一个字节都不含下列任一 token 的文件
# 不可能有被扫的站点。S80 必须把中央能力 id 与漏斗名一并列入——`"media.tts.autodub"`
# 里既没有 "synthesize" 也没有 "audio" 子串，漏进这一列就是**预筛把路筛没了**的假绿。
_SCAN_TRIGGER_TOKENS: tuple[str, ...] = (
    "synthesize",
    "audio",
    *_CENTRAL_PRODUCTION_CAPABILITY_IDS,
    *_AUDIO_PRESENTATION_FUNNELS,
)


def _walk_plugin_py() -> list[Path]:
    return sorted(p for p in _PLUGIN_ROOT.rglob("*.py") if p.is_file())


def _rel_to_repo(path: Path) -> str:
    return path.relative_to(_PLUGIN_ROOT.parent.parent.parent).as_posix()


def test_gate1_scan_set_is_exhaustive_over_plugins_tree() -> None:
    """射程穷举锁：全树重扫，新出现的产出步/音频出站点必须登记或显式豁免。

    这条门是「扩面」本身的执法件——没有它，登记清单会随第三条路出现而静默失真，
    门退回「恰好只有一条路时才成立」。S80 把发现面从「直呼 synthesize」扩到
    「直呼 ∪ 中央 autodub invoke」、从「自建 audio」扩到「自建 ∪ 呈现漏斗」，
    注入产出缝名（dub/synth_fn）**故意不列入**发现信号，理由见模块 docstring。
    """
    registered = {p.resolve() for p in _VOICE_OUTBOUND_SOURCES}
    unregistered_producers: list[str] = []
    untagged_audio: list[str] = []
    for path in _walk_plugin_py():
        text = _read(path) if path.suffix == ".py" else ""
        if not any(token in text for token in _SCAN_TRIGGER_TOKENS):
            continue
        try:
            tree = _parse(text)
        except SyntaxError:  # pragma: no cover - 生产树不允许语法错，出现即另有门拦
            continue
        sites = _module_sites(tree)
        rel = path.relative_to(_PLUGIN_ROOT).as_posix()
        if _governed_production_sites(sites) and path.resolve() not in registered:
            unregistered_producers.append(rel)
        if (
            _presentation_sites(sites)
            and rel not in _NON_TTS_AUDIO_CONSTRUCTION_SITES
            and path.resolve() not in registered
        ):
            untagged_audio.append(rel)
    assert not unregistered_producers, (
        "语音产出出站路径出现未登记的产出步（直呼 synthesize 或中央 autodub invoke）："
        f"{unregistered_producers}——须加入 _VOICE_OUTBOUND_SOURCES 并过 A1-A4"
    )
    assert not untagged_audio, (
        f"出现未归类的音频出站点（自建 audio 或中央呈现漏斗）：{untagged_audio}"
        "——要么登记为语音出站路径，要么进 _NON_TTS_AUDIO_CONSTRUCTION_SITES 写明非合成理由"
    )
    # 反向锁：清单不得虚挂（登记的豁免文件若已无 audio 构造点，说明面已迁移，须清理）。
    stale_exemptions = [
        rel
        for rel, _reason in _NON_TTS_AUDIO_CONSTRUCTION_SITES.items()
        if not _audio_construction_sites(_PLUGIN_ROOT / rel)
    ]
    assert not stale_exemptions, f"豁免表虚挂（该文件已无 audio 构造点）：{stale_exemptions}"


@pytest.mark.parametrize("rule_prefix", ["A1", "A2", "A3", "A4"])
@pytest.mark.parametrize(
    "source_name",
    [p.relative_to(_PLUGIN_ROOT).as_posix() for p in _VOICE_OUTBOUND_SOURCES],
)
def test_gate1_real_sources_pass_rule(rule_prefix: str, source_name: str) -> None:
    """A1-A4 正例：每一条在册语音产出出站路径逐规则过门（含第二出站路）。"""
    path = _PLUGIN_ROOT / source_name
    assert path in _VOICE_OUTBOUND_SOURCES, f"{source_name} 未在册"
    problems = [p for p in _scan_source(path) if f"] {rule_prefix}：" in p]
    assert not problems, (
        f"TTS 出站入口门 {rule_prefix} 对 {source_name} 被触发：\n" + "\n".join(problems)
    )


def test_gate1_real_sources_declare_production_and_presentation_sites() -> None:
    """活动锁（S80 换锚）：在册路径必须**真的被规则承重**，防「登记了但空转」的假扩面。

    旧判据钉的是「该文件有 ``synthesize(`` 直呼点」——那是 VOICE-V12 **之前**的形状。
    hook 的产出步收编进中央后直呼点归零（该文件 docstring 自述「不再出现
    ``synthesize(...)`` 调用点」），于是旧判据一边把一个仍在册、仍该受约的文件判成
    「没构造点」，一边**放过了真正的病**：A1-A4 当时对第二出站路一条都落不了地
    （全线空转）。这正是「拿文件存在当活性」那一类假判据的反面教材——本锁当初的
    立意没错，错在它把立意钉在会随设计翻面的**符号名**上。

    现行判据改钉语义角色，两问每路都要答"是"，只准换锚、不准取消：
      ①该文件有**产出步**站点（直呼 ``synthesize`` / 中央 autodub invoke / 在册注入缝）；
      ②该文件有**音频出站**站点（自建 ``audio`` / 中央呈现漏斗），且检测器认得它。
    任一路为空即红：登记一条既不出音、又不产货的"路"，就是本门自己要治的假扩面。

    S97 换锚（S91 退役内联后）：hook 的「音频出站」不再落本文件的 funnel/自拼体——
    整段呈现挂回随变换搬进真身 result_transform（source #3，本锁对它仍查呈现站点）。
    hook 今天把「出货」这一步体现为派发 autodub_transform。故对 voice_enricher 这一路，
    ②换成「有中央产出步 invoke **且**派发 autodub_transform」——只准换锚，不放行虚挂：
    一条既无产出步、又不派发真身变换的 hook，照样两问皆空即红。

    S285C 跟随 S270 归位（本次改动，逐字交代、不静默改绿）：S270 把全树唯一一处
    ``media.tts.autodub`` 字面中央 invoke 从 hook 的 ``_dub`` 搬进真身自身的
    ``dub_via_central``（单一组合口），于是上面那条 ② 的「有中央产出步 invoke」半句对 hook
    **物理上不成立**（实测该路中央站点归零、真身 :217 出现），连带 ① 对 hook 也取到空集
    ——这正是本门四条红的第 1 条。改法仍是**换锚不是取消**，且两问一题不缩：
      ① 对 hook 换成它今天真正承重的两个动作：**派发 autodub_transform** ∧ **把产出步让给
         单一组合口 ``dub_via_central``**（缺任一即虚挂：不派变换=绕开层 2 自己内联；
         不让出产出步=拿一个不产货的 context 交中央，音频凭空等着冒出来）；
         其余两路（tts.py 直呼路 / 真身）① 仍按「产出步站点」原判据查，一字未动。
      ② 对 hook 仍查呈现（它今天不落自拼体也不落漏斗，故 ② 由 ① 的两个动作承担），
         对 tts.py 与真身仍查「有产出步 ∧ 有音频出站点」原双查。
    并把「持有 autodub 中央产出步」这条正向祝福改指真身，升成**唯一持有者**判据
    （``holders == [result_transform]``）：多出一枚持有者=第二真身（通路没收干净），
    一枚都不剩=产出步整体失踪而本门仍在背书。此判据严格强于被它取代的旧两条。
    """
    for path in _VOICE_OUTBOUND_SOURCES:
        rel = _rel_to_repo(path)
        if path == _VOICE_ENRICHER_SOURCE:
            assert _transform_dispatch_call_sites(path), (
                f"{rel} 未派发中央 media.tts.autodub_transform——S91 退役内联后 hook 的"
                "『出货』动作就是这一发派发，检测器认不得它 = A3 seam-provider 豁免与"
                "活动锁双双落空"
            )
            assert _delegated_production_call_sites(path), (
                f"{rel} 派发变换形却没把产出步交给单一组合口 "
                f"{sorted(_COMPOSITION_DELEGATION_CALLEES)}——S270 归位后 hook 不再自持"
                " autodub 中央 invoke，产出步改由真身组合口产出；context 里没有 dub 的"
                "中央派发＝登记虚挂（音频没有任何地方产出，本门却在给它背书）"
            )
        else:
            assert _provenance_call_sites(path), (
                f"{rel} 登记为语音产出出站路径，却没有任何产出步站点（直呼"
                f" {sorted(_DIRECT_PRODUCTION_CALLEES)}／中央 invoke"
                f" {sorted(_CENTRAL_PRODUCTION_CAPABILITY_IDS)}／注入缝"
                f" {sorted(_INJECTED_PRODUCTION_SEAM_NAMES)}）——登记虚挂，A3/A4 对其空转"
            )
            assert _audio_presentation_sites(path), (
                f"{rel} 有产出步却没有任何音频出站点（自建 audio 或中央呈现漏斗）"
                "——A4 对其空转：要么它不是出站路（须摘登记并写明理由），要么检测器瞎了"
            )
    # 逐路点名「产出步长什么样」：谁走直呼、谁走中央、谁只委托（归位后可读性判据；
    # 直呼禁令的**唯一**执法件仍是 tests/test_voice_enricher_central_dispatch.py，
    # 此处只声明本门射程的解读前提，不另立第二本账）。
    assert _transform_dispatch_call_sites(_VOICE_ENRICHER_SOURCE), (
        "voice_enricher 未派发中央 media.tts.autodub_transform——S91 退役内联后 hook 的"
        "『出货』动作就是这一发派发，检测器认不得它 = A3 seam-provider 豁免与活动锁双双落空"
    )
    assert _delegated_production_call_sites(_VOICE_ENRICHER_SOURCE), (
        "voice_enricher 未把产出步交给单一组合口 dub_via_central——S270 在册形状是"
        "『hook 委托、真身产出』，委托边断了就是产出步无人认领"
    )
    holders = [path for path in _VOICE_OUTBOUND_SOURCES if _central_invoke_sites(path)]
    assert holders == [_RESULT_TRANSFORM_SOURCE], (
        "全树唯一一处中央 media.tts.autodub 产出步今天必须**且只能**住在真身 "
        f"result_transform（S270 单一组合口在册形状），现算持有者="
        f"{[_rel_to_repo(p) for p in holders]}——多出一枚＝第二真身（通路没收干净，"
        "正是本门 A4 第三支要治的半迁移），一枚都不剩＝产出步整体失踪而本门仍在为登记背书"
    )
    assert _audio_presentation_sites(_RESULT_TRANSFORM_SOURCE), (
        "result_transform 的呈现漏斗未被检测器识别——A4 对第三出站路形同虚设"
    )
    tts_sites = _module_sites(_parse(_read(_TTS_SOURCE)))
    assert _direct_production_sites(tts_sites) and not _central_production_sites(tts_sites), (
        "tts.py 的产出步应仍是直呼 synthesize、且不自建第二条中央请求"
        "（本门不预期它变；真变了须同批改这里与上面的逐路点名，不许只改一边）"
    )


def test_gate1_all_registered_sources_fully_clean() -> None:
    """全集正例：所有在册语音出站路径 A1-A4 零违规（一条红即整门红）。"""
    problems = _scan_registered()
    assert not problems, (
        "TTS 出站入口门（单一入口契约）被触发：\n" + "\n".join(problems)
    )


def test_gate1_no_private_pipeline_imports() -> None:
    """A5 正例：plugins/** 无私有管线件外借。"""
    problems = _rule_private_import_ban()
    assert not problems, "TTS 出站入口门 A5（私有面不外借）被触发：\n" + "\n".join(
        problems
    )


# ==================== 负样本自检（注入坏样本 → 门必须变红） ====================

# 负样本①：旁支直拼——_request_tts 内联手搓请求体字典，不经 _build_request_payload。
_BYPASS_INLINE_PAYLOAD = """
import httpx


def _request_tts(*, api_url, text, ref, params, timeout_seconds):
    payload = {
        "text": text,
        "text_lang": "ZH",
        "ref_audio_path": ref.path,
        "prompt_text": ref.text,
        "prompt_lang": ref.lang,
        "top_k": 15,
        "top_p": 1.0,
        "temperature": 0.9,
        "text_split_method": "cut5",
        "speed_factor": 0.85,
        "seed": -1,
        "media_type": "wav",
        "streaming_mode": False,
        "parallel_infer": True,
    }
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(api_url.rstrip("/") + "/tts", json=payload)
    return response.content
"""

# 负样本②：体检闸绕行——不体检直接落盘+入缓存。
_BYPASS_INSPECTION = """
def _fast_lane(text, ref, params, output_dir, key):
    raw = _request_tts(text=text, ref=ref, params=params, timeout_seconds=60.0)
    target = output_dir / (key + ".wav")
    target.write_bytes(raw)
    _store_cache(key, target)
    return target
"""

# 负样本③：取文口绕行——synthesize 照调但未经 resolve_speech_text（A3 射程）。
_BYPASS_RESOLVE = """
def capability(message, _decision):
    path, reason = synthesize(
        api_url="http://127.0.0.1:9880",
        text=message.plain_text,
        ref=None,
        params=None,
        output_dir=None,
    )
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.tts",
        kind="text",
        audio=[{"file": str(path)}],
    )
"""

# 负样本④：音频来路不明——函数内没有 synthesize 调用却构造 audio 出站
# （kwarg 直挂与 update={"audio": …} 两形态都要抓，A4 射程）。
_BYPASS_AUDIO_KWARG = """
def capability(message, _decision):
    cached = _lookup_cache(message.request_id)
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.tts",
        kind="text",
        audio=[{"file": str(cached)}],
    )
"""

_BYPASS_AUDIO_UPDATE_DICT = """
def attach_voice(message, result):
    return result.model_copy(
        update={"audio": [{"file": str(_rogue_path(message))}]}
    )
"""


def test_gate1_negative_inline_payload_caught() -> None:
    """负样本①必须被抓：内联请求体 = 装配点绕行。"""
    problems = _scan_tts_source(_BYPASS_INLINE_PAYLOAD)
    a1 = [p for p in problems if p.startswith("A1")]
    assert a1, "负样本①（内联请求体旁支）未被 A1 抓红——门失效：" + repr(problems)


def test_gate1_negative_inspection_bypass_caught() -> None:
    """负样本②必须被抓：不体检落盘+入缓存。"""
    problems = _scan_tts_source(_BYPASS_INSPECTION)
    a2 = [p for p in problems if p.startswith("A2")]
    assert a2, "负样本②（体检闸绕行）未被 A2 抓红——门失效：" + repr(problems)
    assert any("_fast_lane" in p for p in a2), "A2 未定位到旁支函数名：" + repr(a2)


def test_gate1_negative_resolve_bypass_caught() -> None:
    """负样本③必须被抓：synthesize 照调但取文口被绕开。"""
    problems = _scan_tts_source(_BYPASS_RESOLVE)
    a3 = [p for p in problems if p.startswith("A3")]
    assert a3, "负样本③（取文口绕行）未被 A3 抓红——门失效：" + repr(problems)


def test_gate1_negative_audio_from_nowhere_caught() -> None:
    """负样本④必须被抓：无 synthesize 调用却构造 audio 出站（两形态）。"""
    problems_kwarg = _scan_tts_source(_BYPASS_AUDIO_KWARG)
    a4_kwarg = [p for p in problems_kwarg if p.startswith("A4")]
    assert a4_kwarg, "负样本④a（audio= 直挂，无 synthesize）未被 A4 抓红——门失效：" + repr(
        problems_kwarg
    )
    problems_update = _scan_tts_source(_BYPASS_AUDIO_UPDATE_DICT)
    a4_update = [p for p in problems_update if p.startswith("A4")]
    assert a4_update, "负样本④b（update 字典形态，无 synthesize）未被 A4 抓红——门失效：" + repr(
        problems_update
    )


def test_gate1_negative_private_import_caught() -> None:
    """负样本⑤必须被抓：外部模块静态 import 私有管线件。

    真扫描面在 plugins/**（test_gate1_no_private_pipeline_imports）；
    本用例对同一判定内核注入伪模块源码，验证逻辑本身有杀伤力。
    """
    pseudo = (
        "from plugins.bot_unified_runtime.domains.media.capabilities.tts import (\n"
        "    _request_tts,\n"
        ")\n"
    )
    tree = _parse(pseudo)
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and (
            node.module == "tts" or node.module.endswith(".tts")
        ):
            for alias in node.names:
                if alias.name in _PRIVATE_PIPELINE_NAMES:
                    problems.append(
                        f"A5：pseudo_vendor.py:{node.lineno} 静态 import "
                        f"私有管线件 {alias.name}——旁支直连面"
                    )
    assert problems, "负样本⑤（私有面外借）未被 A5 逻辑抓红——门失效"


def test_gate1_positive_faithful_pipeline_zero_violations() -> None:
    """正例对照：忠实迷你管线零违规——防检测器过度开火。"""
    faithful = '''
def _build_request_payload(text, ref, params):
    return {"text": text, "text_lang": "zh"}


def _inspect_wav_bytes(data):
    return ""


def _store_cache(key, path):
    return None


def _request_tts(*, api_url, text, ref, params, timeout_seconds):
    import httpx

    payload = _build_request_payload(text, ref, params)
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(api_url.rstrip("/") + "/tts", json=payload)
    return response.content


def resolve_speech_text(config, message, text):
    return text, ""


def synthesize(*, api_url, text, ref, params, output_dir, config, message):
    audio = _request_tts(
        api_url=api_url, text=text, ref=ref, params=params, timeout_seconds=1.0
    )
    bad = _inspect_wav_bytes(audio)
    if bad:
        return None, bad
    target = output_dir / "a.wav"
    target.write_bytes(audio)
    _store_cache("k", target)
    return target, ""


def capability(message, _decision):
    speech, blocked = resolve_speech_text(None, message, message.plain_text)
    if blocked:
        return None
    path, _reason = synthesize(
        api_url="http://127.0.0.1:9880",
        text=speech,
        ref=None,
        params=None,
        output_dir=None,
        config=None,
        message=message,
    )
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.tts",
        kind="text",
        audio=[{"file": str(path)}],
    )
'''
    problems = _scan_tts_source(faithful)
    assert not problems, "忠实迷你管线被误判（门过度开火）：" + repr(problems)


# ============ FIX8/S80 变异自检：门对第二、第三出站路（hook / 变换形）真的承重 ============
# 底本=真身源码（**不改生产文件**，只在内存里做单点文本变异），每条变异都同时断言
# 「原样不红 / 变异必红」——否则无法区分「门有效」与「门恰好没反应」。
#
# S80 换锚说明（逐字交代，不静默改绿）：FIX8 那批锚点钉的是 VOICE-V12 之前的形状——
#   旧锚 `_ENRICHER_ANCHOR_SYNTH = "        path, reason = synthesize("` → 现命中 0 次，
#   因为 hook 的产出步已收成 `default_invoker().invoke(CapabilityRequest(
#   capability_id="media.tts.autodub"))`；旧锚防的那类回归是「产物来路不再是中央产出步」，
#   这条不变量在收编后**更要紧**（层 2 治理全挂在那一发 invoke 上）。故 S80 新锚
#   `_ENRICHER_ANCHOR_INVOKE` 打在同一语义位上。
# S97 二次换锚（S91 退役内联后，逐字交代，不静默改绿）：S91 把 hook 里「取文→硬顶→
#   逐块合成→合并→挂回」整段搬进中央第三形真身 result_transform，于是本文件三条锚点
#   随退役变化——
#     · `_ENRICHER_ANCHOR_RESOLVE`（`speech, blocked = resolve_speech_text(`）：hook 已
#       不取文（义务转真身）⇒ 命中 0 次；
#     · `_ENRICHER_ANCHOR_MAX_CHARS`（`max_chars = int(getattr(...))`）：硬顶读法移进真身
#       且改形（真身是 `raw_max_chars = getattr(...)`）⇒ 命中 0 次；
#     · `_ENRICHER_ANCHOR_INVOKE`：`default_invoker().invoke(` 现同时出现在 `_dub`（12 缩进）
#       与 `_enrich_via_central`（8 缩进）两处，12 缩进版仍唯一，但「拆掉产出步＝A4 必红」
#       这条 bite 在退役后**结构上不成立**（hook 不再持呈现站点，拆 `_dub` invoke 后整
#       文件无产出步也无呈现站点 ⇒ A3/A4 都无从落地）。该 bite 归活动锁
#       `test_gate1_real_sources_declare_production_and_presentation_sites`（读真身路径的
#       `_central_invoke_sites`，从生产删 autodub invoke 即红）承接，非删证据、是换执法件。
#   本席据此把三条死锚换成两条**现役唯一**锚 + 一条真身锚，射程不缩、每条被拦真缺陷
#   仍各有一发常驻注毒（见 §2 映射）：
_ENRICHER_ANCHOR_DISPATCH = '                capability_id="media.tts.autodub_transform",'
_ENRICHER_ANCHOR_PRESENT = "        presented = invocation.data.get(PRESENTATION_DATA_KEY)"
# 第三在册路（result_transform）的两枚语义锚：注入产出缝调用 + 拆条步（供 A4 序注毒）。
_TRANSFORM_ANCHOR_SEAM = "            outcome = dub(chunk)"
_TRANSFORM_ANCHOR_CHUNKS = "        chunks = _speech_chunks(config, speech)"
# 真身唯一的取文口调用（腿B self-gate 的立足点）：打掉它 ⇒ 真身两腿皆塌 ⇒ seam provider
# 失去豁免。同一发注毒被两枚用例从**相反方向**用：绊线查「A3 从不进 transform_presentation
# 内部」（残留 ① 仍开），正向杀伤力查「dub_via_central 必须因此红」。见 §前提③#6。
_TRANSFORM_ANCHOR_RESOLVE = "        speech, blocked = resolve_speech_text("
_TRANSFORM_MUTATION_LOCAL_GATE = "        speech, blocked = _local_text_gate("

# ==== S285C 前提③#5：派发腿降为防御性执法 ⇒ 底本换忠实合成件 ====
#
# 归位（S270）之后，「模块既持有 autodub 中央产出步、又派发 autodub_transform」这一
# seam-provider 豁免的**派发腿**在盘上没有任何落脚点了：
#   · voice_enricher —— 只派发，不再持有中央 invoke（现算中央站点 = 空）；
#   · result_transform —— 持有中央 invoke（:217），但它就是真身本身、不派发自己。
# 于是旧那发「打掉 hook 的派发 id ⇒ A3 必红」在**不放宽任何判据**的情况下当场空转
# （A3 里没有可被摘豁免的 seam provider）——这就是本门四条红的第 2 条。
# 处置＝换底本、不换判据：派发腿仍是豁免的两条腿之一（腿A 一毫未缩，见
# ``_module_proves_text_gating``），只是它的杀伤力改在一份**照 S97 时代 hook 逐字形状**
# 写成的合成模块上自证。合成件不遮蔽真实现场：本发同时断言真身 hook 的派发锚点仍唯一
# 命中，锚点一烂本发即红（防「合成件与真身悄悄分家」）。
_SEAM_MODULE_DISPATCH_ANCHOR = '            capability_id="media.tts.autodub_transform",'

_SEAM_PROVIDER_MODULE = '''
def enrich(message, result, config):
    def _dub(chunk):
        invocation = default_invoker().invoke(
            CapabilityRequest(capability_id="media.tts.autodub", payload={"text": chunk})
        )
        return invocation

    return default_invoker().invoke(
        CapabilityRequest(
            capability_id="media.tts.autodub_transform",
            payload={"message": message},
            context={"config": config, "dub": _dub},
        )
    )
'''

# 合成件的第二个注毒件：再来一枚中央 invoke，但它的 payload text **不是**形参（拼接过的
# 表达式）⇒ 不是 seam provider ⇒ 派发腿完好也救不了它。用来钉「豁免按函数生效、
# 绝不按模块洗白」——派发腿若被误用成金牌，本发不会红。
_SEAM_MODULE_SECOND_INVOKER = '''

def _second_invoker(chunk, preset):
    invocation = default_invoker().invoke(
        CapabilityRequest(capability_id="media.tts.autodub", payload={"text": preset.title()})
    )
    return invocation
'''


def _seam_module_mutated(*, old: str, new: str) -> str:
    """合成件单点文本变异（同样要求锚点唯一命中）。"""
    assert _SEAM_PROVIDER_MODULE.count(old) == 1, (
        f"合成件锚点命中 {_SEAM_PROVIDER_MODULE.count(old)} 次（应为 1）：{old!r}"
    )
    return _SEAM_PROVIDER_MODULE.replace(old, new)


def _enricher_mutated(*, old: str, new: str) -> str:
    """单点文本变异（锚点必须唯一命中一次，否则变异本身不可信）。"""
    source = _read(_VOICE_ENRICHER_SOURCE)
    assert source.count(old) == 1, f"变异锚点命中 {source.count(old)} 次（应为 1）：{old!r}"
    return source.replace(old, new)


def _transform_mutated(*, old: str, new: str) -> str:
    """同上，底本换成第三在册路 result_transform.py（同样不碰生产文件）。"""
    source = _read(_RESULT_TRANSFORM_SOURCE)
    assert source.count(old) == 1, f"变异锚点命中 {source.count(old)} 次（应为 1）：{old!r}"
    return source.replace(old, new)


def _rules_of(problems: list[str], prefix: str) -> list[str]:
    """按规则取违规：兼容「裸 _scan_tts_source 输出」与「带文件前缀的 _scan_source 输出」。"""
    marker = f"{prefix}："
    return [p for p in problems if marker in p]


def test_mutate_enricher_pristine_source_is_clean() -> None:
    """变异前正例：真身 voice_enricher A1-A4 零违规（S80 换锚后实测=空清单）。"""
    problems = _scan_source(_VOICE_ENRICHER_SOURCE)
    assert not problems, "底本已红，变异自检失去对照基线：" + repr(problems)


def test_mutate_transform_pristine_source_is_clean() -> None:
    """变异前正例：新在册的第三路 result_transform A1-A4 零违规。"""
    problems = _scan_source(_RESULT_TRANSFORM_SOURCE)
    assert not problems, "底本已红，第三路的承重自检失去基线：" + repr(problems)


def test_detector_recognises_central_invoke_and_funnel_shapes() -> None:
    """换锚的前置自证：检测器**认得**现役两形态（认不得=门对新路空转，即旧红的真病根）。"""
    source = (
        "def enrich(result, config, message):\n"
        "    speech, blocked = resolve_speech_text(config, message, result.body)\n"
        "    invocation = default_invoker().invoke(\n"
        '        CapabilityRequest(capability_id="media.tts.autodub", payload={"text": speech})\n'
        "    )\n"
        "    return result.model_copy(\n"
        "        update=autodub_presentation_update(result, invocation.data)\n"
        "    )\n"
    )
    sites = _module_sites(_parse(source))
    assert len(_central_production_sites(sites)) == 1, "中央 autodub invoke 站点未被识别"
    assert len(_presentation_sites(sites)) == 1, "呈现漏斗未被识别为音频出站点"
    assert not _self_built_audio_sites(sites), "漏斗不该被记成自建出站体（两形态须可分辨）"
    assert not _scan_tts_source(source), "忠实中央形状被误判（门过度开火）：" + repr(
        _scan_tts_source(source)
    )


def test_detector_refuses_to_trust_parameterised_capability_id() -> None:
    """能力 id 走形参 ⇒ 来路**不可证** ⇒ A4 必须红（不猜、不用代理指标放行）。

    这条是换锚自带的负样本：把 id 参数化传进来正是 result_transform docstring
    点名的「给 AST 普查造盲区」形态，门对它的正确反应是报警而不是认路。
    """
    source = (
        "def enrich(result, config, message, cid):\n"
        "    speech, blocked = resolve_speech_text(config, message, result.body)\n"
        "    invocation = default_invoker().invoke(\n"
        '        CapabilityRequest(capability_id=cid, payload={"text": speech})\n'
        "    )\n"
        "    return result.model_copy(\n"
        "        update=autodub_presentation_update(result, invocation.data)\n"
        "    )\n"
    )
    sites = _module_sites(_parse(source))
    assert not _central_production_sites(sites), "非字面 capability_id 被认成了产出步"
    assert _rules_of(_scan_tts_source(source), "A4"), (
        "能力 id 参数化后门仍放行——「音频来路不明」被代理指标糊过去"
    )


def test_mutate_enricher_autodub_without_transform_dispatch_caught_by_a3() -> None:
    """A3 seam-provider 豁免的**前置条件**杀伤力（红线 ①）：纯旁支仍红。

    S97 换锚后 seam provider 靠「text 是本函数形参 ∧ 模块以两腿之一兑现取文义务」豁免
    A3（腿A 派发 autodub_transform ∨ 腿B 同模块先取文后喂缝，见 ``_module_proves_text_gating``）。
    本发打掉**腿A**：把派发那发的能力 id 改成一个不派真身的假 id（模拟「只 invoke autodub、
    从不派发 transform、函数内又不取文」的纯旁支），豁免前置不成立 ⇒ seam provider 回到
    「中央产出步但函数内无 resolve_speech_text」⇒ A3 必红。这一发证明豁免不是免检金牌，
    只是把义务归给它真正派发的真身；不派发就不豁免。

    S285C 换底本（本门四条红的第 2 条，逐字交代、不静默改绿）：S270 把中央 invoke 搬进
    真身后，hook 不再持 seam provider ⇒ 这一对在**盘上任何在册文件**都不再同时成立，旧底本
    的空红＝「底本前提没了」而不是「判据松了」。故底本换成照 S97 时代 hook 形状写成的
    忠实合成件 `_SEAM_PROVIDER_MODULE`，并额外钉三件事，判据面只增不减：
      ① 真身 hook 的派发锚点仍**唯一命中**（合成件与真身悄悄分家 ⇒ 本发即红）；
      ② 忠实合成件原样**零违规**（防合成件本身被过度开火，那会让 ③ 变成空证）；
      ③ 派发腿完好时，第二枚「text 非形参」的中央 invoke **照样红**（豁免按函数生效，
         绝不按模块洗白）。旧底本对此是**结构性看不见**的（它整文件只有一枚 seam provider）。
    """
    assert _read(_VOICE_ENRICHER_SOURCE).count(_ENRICHER_ANCHOR_DISPATCH) == 1, (
        "hook 的 autodub_transform 派发锚点不再唯一命中——合成件与真身已分家，"
        "本发的防御性执法失去对应物，须同步换锚（不许只删这条断言）"
    )
    assert not _scan_tts_source(_SEAM_PROVIDER_MODULE), (
        "忠实 seam-provider 形状（腿A 成立）被误判——门过度开火，后续注毒不算独立证据："
        + repr(_scan_tts_source(_SEAM_PROVIDER_MODULE))
    )

    mutated = _seam_module_mutated(
        old=_SEAM_MODULE_DISPATCH_ANCHOR,
        new='            capability_id="media.tts.autodub_NOTDISPATCHED",',
    )
    problems = _scan_tts_source(mutated)
    a3 = _rules_of(problems, "A3")
    assert a3, (
        "seam provider 只 invoke autodub、不派发真身变换却未被 A3 抓红——豁免发成了"
        "免检金牌（红线 ① 破）：" + repr(problems[:5])
    )
    assert any("_dub" in p for p in a3), f"A3 未定位到受害函数 _dub：{a3}"
    assert any("没有 resolve_speech_text" in p for p in a3), (
        f"A3 未走「函数内没有取文口」分支（而是别的形态）：{a3}"
    )

    laundering = _SEAM_PROVIDER_MODULE + _SEAM_MODULE_SECOND_INVOKER
    a3_second = _rules_of(_scan_tts_source(laundering), "A3")
    assert any("_second_invoker" in p for p in a3_second), (
        "派发腿完好时，非 seam（text 不走形参）的第二枚中央 invoke 被一并豁免——"
        "豁免从「按函数」漂成「按模块」，第二 invoker 就此隐身：" + repr(a3_second)
    )
    assert not any(
        "函数 _dub " in p or "函数_dub" in p for p in a3_second
    ), f"真 seam provider 在腿A 成立时不该红（过度开火会把判据淹成噪声）：{a3_second}"


def test_governed_production_before_text_gate_caught_by_a3_order() -> None:
    """A3 序杀伤力（常驻合成件）：产出步排在取文口之前 = 未过门正文先出货。

    S91 退役内联后，hook 自身不再持「resolve_speech_text 与产出步同函数」的形状（取文
    整体搬进真身，产出步降为 seam），于是原靠 `_ENRICHER_ANCHOR_MAX_CHARS` 注毒的 A3
    「先于」判据在真身文件里**结构上无处落脚**。但序判据本身仍是门的核心杀伤面
    （M-02/M-03：被内容门拦的文字不得先合成），不能因退役就无人执法。故本发改在一份
    忠实合成形状上注毒：直呼产出步（非 seam，text 不走形参）排在 resolve_speech_text
    之前 ⇒ A3 序分支必红。它测的是判据、不是 hook 现盘形状，与 seam-provider 豁免正交
    （豁免只认 autodub invoke ∧ 形参 text ∧ 派发真身，这里一条都不占）。
    """
    late_resolve = """
def resolve_speech_text(config, message, text):
    return text, ""


def capability(message, _decision):
    path, reason = synthesize(api_url="", text=message.plain_text, ref=None, params=None)
    speech, blocked = resolve_speech_text(None, message, message.plain_text)
    return path, speech, blocked
"""
    problems = _rules_of(_scan_tts_source(late_resolve), "A3")
    assert problems, "产出步早于取文口未被 A3 抓红（序判据失效）"
    assert any("先于" in p for p in problems), f"A3 未走序分支：{problems}"


def test_mutate_enricher_self_built_audio_without_production_caught_by_a4() -> None:
    """A4 杀伤力（S97 换锚，红线 ④「音频来路不明」自造音频面）。

    旧发靠打掉 `_dub` 的中央 invoke 触发 A4「没有产出步」。退役内联后 hook 不再持任何
    呈现站点（funnel/自拼体都搬进真身），打掉 `_dub` invoke 只会让整文件既无产出步又无
    呈现站点 ⇒ A4 对 hook 反而**无处落脚**（这不是缩面，是形状变了）。故换锚：在派发点
    `_enrich_via_central` 注入一份自拼 audio 出站体——该函数里没有中央产出步（产出在
    跨函数的 `_dub`，按函数归属不算）⇒「出站体没有产出步垫底」当场红。受害函数名随退役
    从 `_enrich_locked` 改 `_enrich_via_central`（S91 §7.3 第 3 点指名）。
    """
    mutated = _enricher_mutated(
        old=_ENRICHER_ANCHOR_PRESENT,
        new=(
            '        _selfbuilt = result.model_copy(update={"audio": [{"file": "rogue.wav"}]})\n'
            + _ENRICHER_ANCHOR_PRESENT
        ),
    )
    problems = _scan_tts_source(mutated)
    a4 = _rules_of(problems, "A4")
    assert a4, "voice_enricher 音频来路不明未被 A4 抓红——门对现役路径不承重：" + repr(
        problems[:5]
    )
    assert any("_enrich_via_central" in p for p in a4), f"A4 未定位到受害函数：{a4}"
    assert any("没有产出步" in p for p in a4), f"A4 未走「来路缺席」分支：{a4}"


def test_mutate_transform_presentation_before_production_caught_by_a4_order() -> None:
    """A4 序杀伤力（S97 换锚，迁到真身第三路 result_transform）。

    退役内联后 hook 无呈现站点，「先出声后产出」这条序判据在 hook 里物理上无处注毒
    （且 seam `_dub` 已被 A3 豁免）。真身 `transform_presentation` 才是它今天的落脚点：
    其中 `dub(chunk)` 是在册产出缝=来路、`autodub_presentation_update` 是呈现漏斗=出站。
    本发在拆条步（dub 之前）塞一发漏斗 ⇒ 呈现早于产出缝 ⇒ A4「先于」分支必红。它与
    S80 已有的 `test_mutate_transform_seam_without_provenance_caught_by_a4`（打掉缝→「来路
    缺席」分支）各测 A4 一支，互补、不重复计数（S91 §7.3 第 3 点「勿制造假多证」）。
    """
    mutated = _transform_mutated(
        old=_TRANSFORM_ANCHOR_CHUNKS,
        new=(
            "        _early_patch = autodub_presentation_update(result, {})\n"
            + _TRANSFORM_ANCHOR_CHUNKS
        ),
    )
    problems = _rules_of(_scan_tts_source(mutated), "A4")
    assert problems, "呈现漏斗早于产出缝未被 A4 抓红（行序判据对真身形态失效）"
    assert any("先于" in p for p in problems), f"A4 未走序分支：{problems}"
    assert any("transform_presentation" in p for p in problems), (
        f"A4 未定位到受害函数 transform_presentation：{problems}"
    )


def test_mutate_transform_seam_without_provenance_caught_by_a4() -> None:
    """A4 杀伤力（第三路）：注入产出缝被换掉 ⇒ 在册缝名不再承重，音频凭空挂回。

    这条同时是「登记不虚挂」的证明：result_transform 进 _VOICE_OUTBOUND_SOURCES
    不是凑数——打掉它的产出缝，本门的 A4 当场红。
    """
    mutated = _transform_mutated(
        old=_TRANSFORM_ANCHOR_SEAM, new="            outcome = _rogue_local_produce(chunk)"
    )
    problems = _scan_tts_source(mutated)
    a4 = _rules_of(problems, "A4")
    assert a4, "result_transform 产出缝被替换未被 A4 抓红——第三路登记为虚挂：" + repr(
        problems[:5]
    )
    assert any("transform_presentation" in p for p in a4), f"A4 未定位到受害函数：{a4}"


def test_known_gap_injected_seam_escapes_a3_is_a_tripwire_not_an_approval() -> None:
    """残留 ① 的绊线（不是放行凭证）：注入产出缝形态**不在** A3 射程，本用例钉住这个事实。

    现状：``tts.synthesize_autodub`` 的产出点是 ``synth_fn(...)``、
    ``result_transform.transform_presentation`` 的产出点是 ``dub(chunk)``，两者都是
    「文本走形参进来」的注入缝 ⇒ A3「取文口先行」按调用名识别，结构上覆盖不到
    （改锚前后同样覆盖不到，非本波退化；已在模块 docstring「边界与已知残留 ①」写明）。
    本用例断言的是**今天这道口子确实存在**：一旦有人把 A3 做成能查参数来路
    （或给这类函数立了在册豁免），这里会红——红了就把 docstring 的残留条目一起销账，
    而不是把本用例删掉了事。

    S285C 收窄受害面（本门四条红的第 3 条，逐字交代：这是**注毒的副作用**、不是判据放宽）：
    旧写法对整份 A3 清单取「必空」，其前提是该发注毒只打掉 seam 函数的取文口。S270 归位后
    真身自己持中央产出步（``dub_via_central`` :217），而它的 seam-provider 豁免靠的正是
    「同模块先取文、后喂缝」这条 self-gate 腿 ⇒ 同一发注毒**顺手**把豁免也拆了，A3 因此在
    ``dub_via_central`` 上红——绊线被一条它本没打算表达的杀伤面打破。处置＝把断言按**受害函数**
    收窄到 ``transform_presentation``（残留 ① 说的那件事至今未变：A3 从未进过这个函数内部），
    被让出来的那枚杀伤面不许无人执法，另立正向用例
    ``test_mutate_transform_text_gate_removed_caught_dub_via_central_by_a3`` 钉死。
    一句都不许反过来用：本绊线**不**声明「dub_via_central 不该红」，那由正向件负责。
    """
    mutated = _transform_mutated(
        old=_TRANSFORM_ANCHOR_RESOLVE, new=_TRANSFORM_MUTATION_LOCAL_GATE
    )
    a3 = _rules_of(_scan_tts_source(mutated), "A3")
    seam_gapped = [p for p in a3 if "transform_presentation" in p]
    assert not seam_gapped, (
        "A3 现在能查到注入产出缝函数内部的取文口了 ⇒ 残留 ① 已闭合，"
        "请同步删除模块 docstring「边界与已知残留 ①」并改本用例为正向杀伤力自检"
    )
    assert mutated != _read(_RESULT_TRANSFORM_SOURCE), "注毒锚点未命中，本发不算证据"


def test_mutate_transform_text_gate_removed_caught_dub_via_central_by_a3() -> None:
    """A3 杀伤力（S285C 前提③#6，真身 self-gate 腿）：打掉取文口 ⇒ seam provider 必红。

    「改后必抓三形」里的**跳过 resolve_speech_text** 那一形。归位后真身是全树唯一持有
    autodub 中央产出步的文件，它的 seam-provider 豁免只由腿B（``transform_presentation``
    先 ``resolve_speech_text``、后喂 ``dub(chunk)``）兑现；把那条取文口换成同名局部门
    ⇒ 腿B 塌、真身又不派发自己（腿A 恒假）⇒ ``dub_via_central`` 回到「中央产出步但函数内
    没有取文口」⇒ A3 必红。红必须落在**产出步函数**上（不是缝函数），且只走「函数内没有
    resolve_speech_text」这一支——落到别处就说明注毒没隔离变量。
    """
    pristine = _rules_of(_scan_source(_RESULT_TRANSFORM_SOURCE), "A3")
    assert not pristine, "真身底本已红，本发失去对照基线：" + repr(pristine)
    mutated = _transform_mutated(
        old=_TRANSFORM_ANCHOR_RESOLVE, new=_TRANSFORM_MUTATION_LOCAL_GATE
    )
    problems = _scan_tts_source(mutated)
    a3 = _rules_of(problems, "A3")
    assert a3, (
        "真身取文口被换成局部同名门却未被 A3 抓红——self-gate 腿（先取文后喂缝）发成了"
        "免检金牌，「跳过 resolve_speech_text」从此无人执法：" + repr(problems[:5])
    )
    assert any("dub_via_central" in p for p in a3), (
        f"A3 未定位到中央产出步函数 dub_via_central（豁免被摘在别处）：{a3}"
    )
    assert any("没有 resolve_speech_text" in p for p in a3), (
        f"A3 未走「函数内没有取文口」分支（而是别的形态）：{a3}"
    )
    assert not any("transform_presentation" in p for p in a3), (
        "缝函数本身被 A3 直接开火 = 与绊线重复计数（残留 ① 的执法件是绊线，本件只查"
        f" seam provider 的豁免前提）：{a3}"
    )


def test_mutate_enricher_second_http_path_caught_by_a1() -> None:
    """A1 杀伤力：新路径自己拼引擎 HTTP 请求（第二条出站请求）。

    S97 换锚：底本注入点从退役消失的 `_ENRICHER_ANCHOR_MAX_CHARS` 改到现役唯一锚
    `_ENRICHER_ANCHOR_PRESENT`（hook 读回呈现结果那一行），注入语义逐字不变。
    """
    mutated = _enricher_mutated(
        old=_ENRICHER_ANCHOR_PRESENT,
        new=(
            "        import httpx as _httpx\n"
            "        with _httpx.Client(timeout=1.0) as _client:\n"
            "            _client.post('http://127.0.0.1:9880/tts', json={'text': 'x'})\n"
            + _ENRICHER_ANCHOR_PRESENT
        ),
    )
    problems = _scan_tts_source(mutated)
    assert _rules_of(problems, "A1"), (
        "voice_enricher 自建 HTTP 请求未被 A1 抓红：" + repr(problems[:5])
    )


def test_mutate_enricher_write_bytes_outside_synthesize_caught_by_a2() -> None:
    """A2 杀伤力（红线 ④「synthesize 之外自行 write_bytes」）：不经体检直接落盘音频字节。

    S97 换锚：底本注入点改到现役 `_ENRICHER_ANCHOR_PRESENT`；注入的 `write_bytes(` 落在
    hook 函数里（不在 synthesize 白名单）⇒ A2 必红，语义不变。
    """
    mutated = _enricher_mutated(
        old=_ENRICHER_ANCHOR_PRESENT,
        new=(
            "        _rogue_target = _output_dir(config) / 'rogue.wav'\n"
            "        _rogue_target.write_bytes(b'RIFF')\n"
            + _ENRICHER_ANCHOR_PRESENT
        ),
    )
    problems = _scan_tts_source(mutated)
    assert _rules_of(problems, "A2"), (
        "voice_enricher 绕体检落盘未被 A2 抓红：" + repr(problems[:5])
    )


# ==================== S80 杀伤力追加：退役前世界仍受约 + 漏斗旁自拼出站体 ====================

# 「退役前世界」的 hook 形状（VOICE-V12 之前）：直呼 synthesize + 自拼 audio 出站体。
# 换锚**不许**把这套旧形状踢出射程——否则就是拿换锚当缩面的遮羞布。
_RETIRED_WORLD_SOURCE = '''
def resolve_speech_text(config, message, text):
    return text, ""


def capability(message, _decision):
    speech, blocked = resolve_speech_text(None, message, message.plain_text)
    if blocked:
        return None
    path, reason = synthesize(api_url="", text=speech, ref=None)
    return CapabilityResult(request_id=message.request_id, audio=[{"file": str(path)}])
'''


def test_retired_world_shape_faithful_pipeline_still_clean() -> None:
    """旧世界正例：直呼 synthesize + 自拼 audio 的忠实形状零违规（换锚未缩射程）。"""
    problems = _scan_tts_source(_RETIRED_WORLD_SOURCE)
    assert not problems, "退役前形状被误判（换锚后旧路反而不过门=变相缩面）：" + repr(problems)


def test_retired_world_shape_text_gate_bypass_still_caught_by_a3() -> None:
    """旧世界反例①：直呼路上打掉取文口 ⇒ A3 仍红（旧杀伤力原样保留）。"""
    mutated = _RETIRED_WORLD_SOURCE.replace(
        "    speech, blocked = resolve_speech_text(None, message, message.plain_text)",
        "    speech, blocked = _local_text_gate(None, message, message.plain_text)",
        1,
    )
    assert mutated != _RETIRED_WORLD_SOURCE, "注毒锚点未命中，本发不算证据"
    a3 = _rules_of(_scan_tts_source(mutated), "A3")
    assert a3, "退役前形状的取文口绕行未被 A3 抓红：" + repr(a3)


def test_retired_world_shape_audio_without_production_still_caught_by_a4() -> None:
    """旧世界反例②：audio 自拼但产出步没了 ⇒ A4 仍红。"""
    mutated = _RETIRED_WORLD_SOURCE.replace(
        "    path, reason = synthesize(api_url=\"\", text=speech, ref=None)",
        "    path, reason = _rogue_produce(speech)",
        1,
    )
    assert mutated != _RETIRED_WORLD_SOURCE, "注毒锚点未命中，本发不算证据"
    a4 = _rules_of(_scan_tts_source(mutated), "A4")
    assert a4, "退役前形状的「音频来路不明」未被 A4 抓红：" + repr(a4)


def test_mutate_enricher_self_builds_audio_beside_funnel_caught_by_a4() -> None:
    """A4 第二支杀伤力：同函数中央漏斗已在，又自拼一份 audio 出站体（层 1 第二通路）。

    在册口径「层 1 从此不自拼出站体」的机器执法。S97 换锚：退役内联后 hook 现盘不再
    自带漏斗，旧注毒（只塞一份自拼体、依赖旧 `_enrich_locked` 里的漏斗）已落不到第二支
    上；本发改在 `_enrich_via_central` 同时注入「一发中央漏斗 + 一份自拼体」——这一对
    正是第二支的判据（funnel ∧ 自建），与 S80 时代语义等价，射程不缩。与 #7（只自拼、
    无漏斗→走「来路缺席」第一支）互补，各测 A4 一支。
    """
    mutated = _enricher_mutated(
        old=_ENRICHER_ANCHOR_PRESENT,
        new=(
            "        _early_funnel = autodub_presentation_update(result, {})\n"
            '        _selfbuilt = result.model_copy(update={"audio": [{"file": "rogue.wav"}]})\n'
            + _ENRICHER_ANCHOR_PRESENT
        ),
    )
    a4 = _rules_of(_scan_tts_source(mutated), "A4")
    assert a4, "hook 在中央漏斗旁自拼 audio 未被抓红——「不自拼出站体」仍是散文：" + repr(
        a4[:3]
    )
    assert any("第二通路" in p for p in a4), f"未走漏斗互斥支：{a4}"


def test_tts_command_legs_self_build_without_funnel_not_flagged() -> None:
    """反向自证（防过度开火）：命令路与旧包装只自建、不走漏斗 ⇒ A4 第二支不误伤。

    不写这条，就没人知道新支是不是靠"把现存两路一起判红"换来的绿。
    """
    problems = _scan_source(_TTS_SOURCE)
    assert not [p for p in problems if "第二通路" in p], (
        "A4 第二支打到了 tts.py 命令路/旧包装（它们不经中央漏斗，本就不该受此支约束）："
        + repr([p for p in problems if "第二通路" in p])
    )


def test_mutate_enricher_reverts_to_direct_synthesize_caught_by_a4() -> None:
    """「退役前世界」注毒：在册产出路加回一条直呼 synthesize ⇒ 本门必须红。

    这是本席简报点名的那一发——把调用点改回旧直发。注得体面一点：新函数**先取文、
    后合成、不自拼出站体**，因此 A3 与 A4 前两支都无话可说；红只能来自第三支
    「直呼与中央并存=通路没收干净」。这一发同时证明本门的门名（central_entry）
    与判据对齐，不再是「他席执法、本门背书」。

    S285C 换底本（本门四条红的第 4 条，逐字交代）：第三支的判据是「直呼 ∧ 中央**在同一
    射程内并存**」，而归位（S270）后 hook 已不持任何中央产出步 ⇒ 往 hook 上加一发直呼根本
    不成对（实测 problems 为空集），这一发就此空转。**换底本不换判据**：中央产出步今天
    住在真身 ``dub_via_central``，故注毒落到底本 `_RESULT_TRANSFORM_SOURCE` 上——同一形、
    同一支、同样只杀这一支。
    不许把这次换底本读成「hook 退回直呼没人管了」：该回归的执法件是
    ``tests/test_voice_enricher_central_dispatch.py``（直呼锁 ``not _execution_calls(tree,
    "synthesize")`` ∧ 退役锁，见 voice_enricher.py 模块 docstring「出站体归属」节），
    本门从不在这一路上另立第二本账（同文件活动锁注释里写明的分工）。
    """
    source = (
        _read(_RESULT_TRANSFORM_SOURCE)
        + "\n\ndef _legacy_direct(config: Any, message: IncomingMessage, result: CapabilityResult):\n"
        "    speech, blocked = resolve_speech_text(config, message, result.body)\n"
        "    path, reason = synthesize(api_url='', text=speech, ref=None, params=None)\n"
        "    return path, reason\n"
    )
    assert source != _read(_RESULT_TRANSFORM_SOURCE), "注毒未落地，本发不算证据"
    problems = _rules_of(_scan_tts_source(source), "A4")
    assert any("并存" in p for p in problems), (
        "在册产出路退回直呼产出未被本门抓红——「出站必经中央」仍是散文：" + repr(problems[:3])
    )
    # 注毒须只杀这一支：A3 若也红，说明注毒没做到"体面"，本发就不算独立证据。
    assert not _rules_of(_scan_tts_source(source), "A3"), "注毒未隔离变量，A3 也被牵动"


def test_retired_world_shape_alone_does_not_trip_mixed_route_branch() -> None:
    """第三支反向自证：纯直呼世界（未收编前）不该被"并存"判据打红。

    否则这条新支就是拿"把旧形状一律判死"冒充杀伤力——真判据是**半迁移**，不是直呼本身。
    """
    assert not [
        p for p in _scan_tts_source(_RETIRED_WORLD_SOURCE) if "并存" in p
    ], "纯直呼形状被第三支误伤"
    pure_central = (
        "def enrich(result, config, message):\n"
        "    speech, blocked = resolve_speech_text(config, message, result.body)\n"
        "    invocation = default_invoker().invoke(\n"
        '        CapabilityRequest(capability_id="media.tts.autodub", payload={"text": speech})\n'
        "    )\n"
        "    return result.model_copy(\n"
        "        update=autodub_presentation_update(result, invocation.data)\n"
        "    )\n"
    )
    assert not [p for p in _scan_tts_source(pure_central) if "并存" in p], "纯中央形状被误伤"
