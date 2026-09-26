"""统一接入波 · S-GAP 席常驻门：中央在册表 vs 生产真实通路的「登记式缺口门」。

权威：``docs/design/capability-orchestration-adoption-spec.md``（Wave 1–4）。用户原令
「所有内容走中央调度层，TTS 也不例外」缺的可核对形态就是这把门——它把「还剩多少没接入」
从一句没人能答的话，变成一个**可减的登记数**。

一句话判据：``CAPABILITY_DESCRIPTOR`` 里每一条 ``capability_id``，生产要么真走了
``….invoke(...)``（wired）、要么走了泛型执行器 ``pipeline.handle_async`` /
``_run_simple_capability``（generic_executor）、要么就是**在册零调用点**（not_wired，挂账）。
三条清单必须**恰好铺满**在册表，且真树扫描结果与清单逐桶相等。

四条不变量（各自可单独归因，见注毒）：
- INV-COVERAGE  在册集合 == (wired ∪ generic ∪ not_wired)：新冒一条不属于任何清单的 descriptor ⇒ 红；
                清单里登记了一条而真册没有 ⇒ 也红（防"清单糊住真实退化"）。
- INV-WIRED     登记的 invoke 点在真树找不到 ⇒ 红；真树冒出未登记的 invoke 点 ⇒ 红。
- INV-GENERIC   泛型执行器上出现的 ``capability_id=`` 字面量集合（去 wired 后）必须恰好 == 登记面。
- INV-RATCHET   「未通电缺口」= generic + not_wired 的条数 **只准降不准升**（Wave 4.1 每迁一处 invoke，
                把它从 generic/not_wired 挪进 wired，缺口 −1，接入进度第一次成为可减的数）。

外加第⑤节**入口耐久锁**（HARDEN-1 I-2，R10）：唯一表每一个在册执行形 id 必须在根里确有
汇缝字面量入口。它是 "INV-WIRED 对 seam 登记 id 是重言"（R9）的第三份活性证——seam 声明、
canary 多入口、入口耐久三把锁并立，缺一不许降账；判据真身与真树级注毒住
``tests/test_central_via_identity_and_entry_durability.py``（退役该件会打断本件 import＝不可静默拆）。

设计纪律：
- **组合复用**，不复制第二套扫描器（铁律 7）：invoke 判据 import 自 v1 门
  ``test_orchestration_callsite_single``，泛型执行器判据 import 自本席只读扫描器
  ``scripts/orchestration_wired_census``。本件只加"清单比对"这一层新逻辑。
- **只 import 表，不 import nonebot、不启动插件装配**；descriptor 表若在飞不可导入 → 诚实 skip 点名外因
  （中央件由主会话在改），绝不因外因放宽判据（先例 ``test_creation_tts_drift_gate._cp``）。
- **P0-A 过渡臂（2026-09-27 S-SEAM-FOLLOW-b 挂、同波 S-SEAM-FOLLOW-c 撤）**：根汇缝字面量站点
  （``_run_capability_through_pipeline`` 的 ``capability_id=字面``）曾对冻结在飞的旧尺不可见 ⇒
  本门一度并入共享判据真身 ``_viaid.root_funnel_literal_cids()`` 代扫。旧尺现按当时白纸黑字的
  撤臂条件补上第四臂（``scripts/orchestration_wired_census.scan_wiredness`` 第 4 支，同一真身、
  同一注毒挂钩），本门自此**回到纯再导出委托**；臂的牙仍住 ``test_funnel_arm_lock_has_teeth``
  （经 census 传导）与双臂注毒的 ``test_census_cross_check_lock_has_teeth``。
- 纯 ast 静态扫描，零运行时副作用；``BOT_AUTOSYNC=0`` 下稳定绿（不依赖任何生成物）。
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parents[0]
sys.path.insert(0, str(_TESTS_DIR))
sys.path.insert(0, str(_REPO_ROOT))

import test_central_via_identity_and_entry_durability as _viaid  # 复用「根汇缝字面量」判据真身（⑤节）
import test_orchestration_callsite_single as _v1  # 复用 invoke 判据 + _PKG_ROOT + _rel

_SPEC = importlib.util.spec_from_file_location(
    "orchestration_wired_census", _REPO_ROOT / "scripts" / "orchestration_wired_census.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_census = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_census)


def _load_descriptor_ids() -> frozenset[str]:
    try:
        module = importlib.import_module("plugins.bot_unified_runtime.runtime.capability_protocols")
    except Exception as exc:  # noqa: BLE001  中央件在飞不可导入属外因，诚实 skip，不放宽判据
        pytest.skip(f"CAPABILITY_DESCRIPTOR 不可导入（中央件在飞，非本门缺陷）：{exc!r}")
    table = getattr(module, "CAPABILITY_DESCRIPTOR", None)
    if table is None:
        # RF2-6 根修：表已落地（Wave 2 收口后 CAPABILITY_DESCRIPTOR 必存在）——此刻符号被删是
        # **真退化**而非外因，绝不能静默 skip 假绿。中央件在飞的外因已由上面的 import 分支兜住，
        # 到得了这里说明模块导入成功却无该属性 ⇒ 判失败、点名让 owner 复核。
        pytest.fail(
            "CAPABILITY_DESCRIPTOR 已导入模块却取不到（表落地后被删/改名=假绿温床，评审 RF2-6）；"
            "若确在退役中央件，请显式改本门而非留 skip。"
        )
    return frozenset(table)


# ===========================================================================
# 已登记清单（2026-09-22 真树实测）。Wave 4.1 迁一处 invoke：把该 cid 从
# NOT_WIRED/GENERIC 挪进 WIRED，缺口自动 −1。
# ===========================================================================
#: cid → 登记的生产 invoke 点（相对包根路径）。
#: 命令形接缝的"点位"就是路由表里那行 execution 声明所在文件（R8 口径件
#: `decisions/R8-seam-wiring-accounting.md`）；与 `_v1.seam_registered_cids()` 同源，
#: ⚠ R9（R-PREP C-1）：该函数只证"声明了执行形"；"每一条分发入口都汇到缝"由
#:   `tests/test_prepared_adapter_canary.py` 的多入口活性锁执法。两把锁缺一即假账，不许只凭前者降账。
#: 两边不一致会由 INV-WIRED 当场点名。
#: ⚠ R10（HARDEN-1 I-2）：再补本件第⑤节的**入口耐久锁**——"每个在册执行形 id 在根里确有
#:   汇缝字面量入口"此前只住批次件 test_prepared_adapter_batch3.py，批次退役即失守；
#:   现提进本常驻门，三把锁（seam 声明 + canary 多入口 + 入口耐久）并立，缺一不许降账。
REGISTRY_POINTS_AT = "domains/chat_reply/runtime/capability_registry.py"
WIRED: dict[str, frozenset[str]] = {
    # 语音接真（中央调度收编波 P4-C4，席 S08，2026-09-23T20:3xZ）：`creation.tts.synthesize`
    # 自此有**生产字面调用点**——控制面 `POST /api/v1/tts/jobs` 的 `default_invoker().invoke(...)`。
    # 尺：`scripts/central_seam_census.py --json` → 该 id state none→wired（invoke_sites 非空）；
    # 命令：`python -m pytest tests/test_control_plane_tts_api.py tests/test_descriptor_wiredness_ledger.py`。
    # ⚠ 同行读数：控制面缺省关（`bot_control_plane_enabled=False`）⇒ **账面通电、现网零流量**，
    #   不得叙述为"语音已可被 API 调用"（造绿九禁第⑧条）。
    "creation.tts.synthesize": frozenset({"domains/creation/tts/routes.py"}),
    # 绘画接真（中央调度收编波二批，席 S262 ＋ 主代理升账）：`creation.image.generate` 自本窗有
    # **生产字面调用点**——控制面 `POST /api/v1/image-generation/jobs` 门面件的
    # `default_invoker().invoke(...)`（capability_id 写成字面量，提成变量即被 AST 注毒判红）。
    # 尺：`python scripts/central_seam_census.py --json` → 该 id state none→wired（invoke_sites 非空）；
    # 命令：`python -m pytest tests/test_control_plane_image_api.py tests/test_descriptor_wiredness_ledger.py`。
    # ⚠ 同 creation.tts.synthesize 一行读数：控制面缺省关（`bot_control_plane_enabled=False`）
    #   ⇒ **账面通电、现网零流量**，且 provider 仍未接（缺省回 503 `image_not_wired`）——
    #   不得叙述为"AI 绘画已可被调用"（造绿九禁第⑧条）。本枚升的是"有入口"，不是"能出图"。
    "creation.image.generate": frozenset({"domains/creation/image/routes.py"}),
    "media.vision.anime_ip": frozenset({"domains/media/capabilities/image_search.py"}),
    "search.web": frozenset({"__init__.py"}),
    # 命令形接缝通电（R8）：点位=capability_registry 里那一行 execution 声明本身。
    "bot.daily_assist": frozenset({REGISTRY_POINTS_AT}),
    "bot.meme": frozenset({REGISTRY_POINTS_AT}),
    "bot.moegirl": frozenset({REGISTRY_POINTS_AT}),
    "bot.news": frozenset({REGISTRY_POINTS_AT}),
    "bot.randpic": frozenset({REGISTRY_POINTS_AT}),
    "bot.reminder": frozenset({REGISTRY_POINTS_AT}),
    # prepared 形首例（B0 金丝雀）：执行体由装配现场交来（weather 还要 render_backend），
    # 通电点位同样是那一行 execution 声明；"成品真被交上来"由
    # tests/test_prepared_adapter_canary.py 的端到端活性锁负责，不由本表自证。
    "bot.weather": frozenset({REGISTRY_POINTS_AT}),
    "bot.tts": frozenset({REGISTRY_POINTS_AT}),
    "bot.wiki": frozenset({REGISTRY_POINTS_AT}),
    # prepared 形 P1 批（S-PREP-B1）：这 10 枚的 builder 除 config 还要运行期 render_backend
    # （divination 另带 draw_store/fortune_key/clock），执行体由装配现场 `_build_*_with_backend`
    # 闭包交来，根生产路径 `await _run_simple_capability(..., orchestrated_command(cid, factory(config), config))`
    # 真的走中央 invoker。逐枚活性证（跑的就是交来那一个、缺成品=UNAVAILABLE 不自建）由
    # tests/test_prepared_adapter_batch1.py 负责，不由本表自证。
    "bot.bond": frozenset({REGISTRY_POINTS_AT}),
    "bot.commodities": frozenset({REGISTRY_POINTS_AT}),
    "bot.divination": frozenset({REGISTRY_POINTS_AT}),
    "bot.eat": frozenset({REGISTRY_POINTS_AT}),
    "bot.emergency_info": frozenset({REGISTRY_POINTS_AT}),
    "bot.epic": frozenset({REGISTRY_POINTS_AT}),
    "bot.fx": frozenset({REGISTRY_POINTS_AT}),
    "bot.market": frozenset({REGISTRY_POINTS_AT}),
    "bot.northbound": frozenset({REGISTRY_POINTS_AT}),
    "bot.stocks": frozenset({REGISTRY_POINTS_AT}),
    # prepared 形 P2 批（S-PREP-B2）：好感度查询的 builder 除 config 还要**两件**运行期注入
    # （装配期现构的 affinity_store + 函数局部 render_backend，根 :4338-4343），执行体由装配
    # 现场交来；根生产路径 `await _run_simple_capability(..., _build_affinity_with_backend,
    # "bot.affinity", affinity)`（:9000）真的走中央 invoker。逐枚活性证（跑的就是交来那一个、
    # 缺成品=UNAVAILABLE 不自建）由 tests/test_prepared_adapter_batch2.py 负责，不由本表自证。
    # 同批实测**拒绝**登记的两枚（判据不过，不是漏登）：bot.meme_library / bot.group_info
    # （生产走泛型执行器 :8733/:8507，不经
    # orchestrated_command ⇒ 登记只会把账面翻成 WIRED 而生产零变化＝本门最该拦的假绿）。
    # 该批另点名的 bot.ignore 当时被第三把判据（空 label ⇒ title 缺失）挡住，
    # 该判据已由主会话一行修解除 ⇒ bot.ignore 随 P8 批（S-PREP-B3）移入下方 WIRED。
    "bot.affinity": frozenset({REGISTRY_POINTS_AT}),
    # prepared 形 P9 批试点（S63 图 §3.1，主代理 2026-09-24T00:15Z 落码）：点歌模式。
    # 命令入口已汇进根汇合函数（:7013 `_run_capability_through_pipeline`，字面 capability_id
    # 已在 ⇒ 入口耐久锁 §5 不因本行而红），执行体是吃运行期 runtime_settings + event 解析
    # mode 的内联闭包 ⇒ adapter=prepared；**根零改动、净 0 行 ⇒ 不顶漂**。
    # 逐枚活性证（跑的就是交来那一个、缺成品=UNAVAILABLE 不自建）由
    # tests/test_prepared_adapter_batch9.py（S66，15 例＋3 发注毒逐发有牙）负责，不由本表自证。
    # 该席并独立复核本行四项前提全票成立：roles 用表缺省 ("user",)（根 matcher :6985 与规则 :6543
    # 无角色门，拒人在域内 `music.py:449`；登 ("admin",) 反而＝中央换文本的行为漂移）、
    # timeout 30.0 ≈ 悲观上界 60 倍（零网络/LLM/渲染，与同表 bot.emergency_info 同口径）、
    # prepared 是唯一可选形（活签名首参 `store` ≠ config）、普查态 wired 26/generic 10/not_wired 84。
    "bot.music_mode": frozenset({REGISTRY_POINTS_AT}),
    # prepared 形 P8 批（S-PREP-B3）：兜底引导席。生产入口唯一（根 :8568-8578
    # `_handle_ignore_guide` → `_run_simple_capability(..., "bot.ignore", ...)` :8570），
    # 早已汇进层 2 主缝；执行体是根内联闭包、全树无 `build_ignore_capability(config)`
    # 具名工厂 ⇒ 命令形无从自建，只能 prepared。S-PREP-B2 当年的拦路判据（空 label 撞
    # `validate_registry` title 缺失）已由主会话一行修解除（`title=decl.label or decl.value`），
    # 本批据此把这枚欠债改成实账。逐枚活性证由 tests/test_prepared_adapter_batch3.py 负责。
    "bot.ignore": frozenset({REGISTRY_POINTS_AT}),
    # 自动配音第二出站腿（VOICE-V12，2026-09-22）：media 族内容契约能力，无 RouteKind
    # 宿主行（≠命令形/prepared 形，与 media.vision.anime_ip 同此：WIRED 记账走字面
    # invoke 点、不靠注册册 execution 声明）。通电点位随 S270 归位：全树唯一一处 autodub
    # 字面 invoke 现住单一组合口 domains/media/tts/result_transform.py::dub_via_central
    # （voice_enricher 的 dub 闭包与 creation/tts/engine_provider 都改调它，直呼面清零）。
    "media.tts.autodub": frozenset({"domains/media/tts/result_transform.py"}),
    # S91 自动配音第二条腿：内联变换退役为中央第三形，由层 1 hook 派发。该 id 的 invoke 点
    # 仍在 voice_enricher（_enrich_via_central 派 autodub_transform 那一发）——S270 归位只
    # 挪走产出步 autodub 那一发，第三形 transform 的发不动。
    "media.tts.autodub_transform": frozenset({"domains/media/voice_enricher.py"}),
    # ---- 中央调度完全统一波 P0-A 后账跟随（S-SEAM-FOLLOW-b，2026-09-27）----
    # 以下 12 枚的根站点现为 `_run_capability_through_pipeline(..., capability_id="<字面>")`
    # ——生产经中央汇缝投递、字面 cid 点名，点位＝根 `__init__.py` 汇缝站点（行号为落账日现算，
    # 根在他席在飞、漂移只漂注释不漂判据）。旧尺 orchestration_wired_census 对汇缝字面量的失明
    # 已由 **scan_wiredness 第四臂**（S-SEAM-FOLLOW-c 2026-09-27 补臂，判据真身
    # `_viaid.root_funnel_literal_cids()` 唯一支、§5 入口耐久锁同源）在本件挂账的过渡臂撤臂后
    # 直接治好——本件不再自扫，回到再导出委托原形。
    # ⚠ 在册未执法读数：汇缝＝账面通电（调用点存在），逐枚端到端活性由各能力自己的门钉，本臂不自证。
    "bot.consent": frozenset({"__init__.py"}),  # 根 :9114（自 GENERIC 迁入）
    "bot.content": frozenset({"__init__.py"}),  # 根 :8839（自 GENERIC 迁入）
    "bot.group_info": frozenset({"__init__.py"}),  # 根 :9019（自 GENERIC 迁入）
    "bot.host_state": frozenset({"__init__.py"}),  # 根 :9063（自 GENERIC 迁入）
    "bot.image_search": frozenset({"__init__.py"}),  # 根 :6615（自 GENERIC 迁入）
    "bot.media_archive": frozenset({"__init__.py"}),  # 根 :9254（自 GENERIC 迁入）
    "bot.meme_library": frozenset({"__init__.py"}),  # 根 :9309（自 GENERIC 迁入）
    "bot.music": frozenset({"__init__.py"}),  # 根 :8878（自 GENERIC 迁入）
    # 两枚原「在册零调用点」：P0-A 在根落出字面汇缝站点，从 NOT_WIRED 迁入（零调用点叙述自此作废）。
    "bot.mail.control": frozenset({"__init__.py"}),  # 根 :6895
    "bot.auto_send.preview": frozenset({"__init__.py"}),  # 根 :8245
    # 两枚命令腿入缝；其调度器 push 腿仍走 `pipeline.handle_async` 泛型形（根 :4761/:1864，
    # 合成消息旁路与 campus_forward 同型）——wired 优先是 census.live_partition 既有唯一规则
    # （"invoke 出现即 wired，其残留泛型字面量不计 generic"，music_mode/moegirl 先例同型），
    # 泛型面的逐条量尺由 tests/test_generic_executor_facets.py 继续钉住这两枚，一腿不丢。
    "bot.subscribe": frozenset({"__init__.py"}),  # 根 :7445
    "bot.today_history": frozenset({"__init__.py"}),  # 根 :8924
}

#: 走泛型执行器（_run_simple_capability / pipeline.handle_async）的能力 id。
#: 2026-09-27 S-SEAM-FOLLOW-b（P0-A 后账跟随）：原 12 枚中八枚（consent/content/group_info/
#: host_state/image_search/media_archive/meme_library/music——含 S-R2-LEDGER 2026-09-26 登记的
#: consent/host_state 泛型形）根站点已迁入 `_run_capability_through_pipeline` 中央汇缝、
#: subscribe/today_history 命令腿同迁入缝（push 腿泛型由 facets 门继续量尺），逐枚上方 WIRED
#: 留痕；本桶自此只余两枚如实欠账：
#: - bot.campus_forward＝本波裁定的**合法保留**（异步池旁路投递形＋BLOCK 通知语义＋测试钉 env）；
#: - bot.chat＝生产仍 `pipeline.handle_async(..., capability_id="bot.chat")` 泛型腿（根
#:   :8472/:8618/:9664），未接中央 invoker，欠账如实挂本桶。
#: 口径差点名（S-SEAM-FOLLOW-c 2026-09-27 现算归因修正）：新尺 central_seam_census 把 bot.chat
#: 记 wired 的真身**不是** handle_async 字面（handle_async 是 GENERIC_FUNCS，记 generic 证据），
#: 而是根 :4980 反应表情包**送腿** `_send_parts_through_unified_pipeline(capability_id="bot.chat")`
#: ——送腿合成 `_capability` 闭包喂 `_run_capability_through_pipeline`，该缝腿确走中央投递，
#: 但执行的仍是表情包贴回复的呈现件，**chat 生成执行体本身没经中央 invoker**。
#: 本门判据量的是执行汇流 ⇒ 仍记 GENERIC。两尺各管一段，差异不许互相"改平"
#: （把送腿缝腿抬成执行通电＝meme_library/group_info 先例点名的假绿）。
GENERIC: frozenset[str] = frozenset(
    {
        "bot.campus_forward", "bot.chat",
    }
)

#: 在册但全树零调用点。value=挂账理由（仅人读；比对只看键集，authored_by 漂移不误红）。
#: interface_only：capability./core./parser./persona./transport. 的接口联动 id，本非可 invoke 入口，永久挂账属设计语义。
#: controlled_no_callsite：后台 job/管理链，无会话侧能力入口（是否该接由主会话逐项裁）。
#: route_capability_unmigrated：有 RouteKind/matcher 工厂、生产仍直呼，Wave 3/4 待翻面。
#:   ⚠ 2026-09-22 S-FILL7 实况注记（判据不动、只写真相）：其中 **bot.wiki/bot.news/bot.randpic/
#:   bot.moegirl/bot.meme/bot.reminder/bot.daily_assist + bot.tts** 共 8 枚的执行面已填
#:   （capability_registry 路由行 execution=CapabilityExecution(family="command")），运行期经根参数化
#:   主缝 orchestrated_command **真的走中央 invoker**。
#:   **2026-09-22 R8 结案（本席 owner 扩判据，非静默放宽）**：这 8 枚已从本桶移入 WIRED，
#:   invoke 命中集并入 `_v1.seam_registered_cids()`（认唯一表 route 执行形为通电事实，
#:   点位=那一行声明本身）；配 `test_seam_accounting_lock_has_teeth` 注毒自证。
#:   仍**不认**根泛型站点的 positional 形态（那是 generic 桶的判据，两桶各管一段，不混）。
#: orchestration_unwired：编排侧已 author descriptor + 壳 handler，但生产零 invoke（Wave 4 欠账集中营）。
NOT_WIRED: frozenset[str] = frozenset(
    {
        # ---- interface_only（设计语义，非欠账）----
        # capability.consent / capability.host_state 两枚＝#50/#58 波新面的接口联动 id（声明面
        # base_router.py:753-754 InterfaceEntry、capability_registry.py:900/906 InterfaceDecl），
        # 与 capability.group_info 同族：本非可 invoke 入口，bot.* 执行腿已按泛型形登记 GENERIC。
        "capability.auto_send", "capability.consent", "capability.daily_assist", "capability.emotion", "capability.epic",
        "capability.game_live", "capability.group_info", "capability.gscore", "capability.host_state", "capability.meme",
        "capability.meme_absorb", "capability.moegirl", "capability.music", "capability.subscribe",
        "capability.today_history", "capability.tts", "capability.weather", "capability.wiki",
        "core.gscore", "parser.content", "persona.chat", "transport.onebot",
        # ---- controlled_no_callsite ----
        # ⚠ 2026-09-27 S-SEAM-FOLLOW-b（P0-A 后账跟随）：bot.mail.control / bot.auto_send.preview
        # 两枚已非「零调用点」——根落出字面汇缝站点（:6895/:8245），随上方 WIRED 迁移注记移入 WIRED。
        "bot.alert", "bot.audit", "bot.config", "bot.context", "bot.control",
        "bot.cookie_expiry_notice", "bot.cookie_login", "bot.credential_check", "bot.dialogue",
        "bot.download", "bot.emergency_info_push", "bot.file", "bot.group_digest_push", "bot.group_policy",
        "bot.group_welcome", "bot.help", "bot.history", "bot.identity", "bot.llm", "bot.logs",
        "bot.mail.notify", "bot.memory", "bot.parse", "bot.persona", "bot.poke",
        "bot.queue", "bot.quirk", "bot.readiness", "bot.receipt", "bot.recent", "bot.reply", "bot.roles",
        "bot.route", "bot.routes", "bot.runtime", "bot.search", "bot.send_queue_worker", "bot.setup.llm",
        "bot.why",
        # ---- orchestration_unwired（有 handler_ref，生产零 invoke）----
        # creation.tts.synthesize 一枚已于 2026-09-23 P4-C4 移入 WIRED（控制面 POST /api/v1/tts/jobs
        # 落出生产字面调用点）；creation.image.generate 一枚已于 2026-09-25 S262 同型移入 WIRED
        # （控制面 POST /api/v1/image-generation/jobs）⇒ 本列自此**无 creation.* 成员**。
        "files.artifact.generate", "files.read.code",
        "files.read.excel", "files.read.latex", "files.read.markdown", "files.read.pdf", "files.read.ppt",
        "files.read.word", "media.asr.audio_file", "media.asr.speech", "media.video.frame_extract",
        "media.video.recognize", "media.video.subtitle", "media.vision.image", "media.vision.ocr",
        "search.acg", "search.reference.fetch", "search.unified",
        # ---- route_capability_unmigrated ----
        # （wiki/news/randpic/moegirl/meme/daily_assist/reminder/tts 八枚已移入 WIRED，见 R8 注记；
        #   bot.weather 已随 prepared 形 B0 移入 WIRED，2026-09-22；
        #   bond/commodities/divination/eat/emergency_info/epic/fx/market/northbound/stocks 十枚
        #   已随 prepared 形 P1 批移入 WIRED（S-PREP-B1，2026-09-22）；
        #   bot.affinity 一枚已随 prepared 形 P2 批移入 WIRED（S-PREP-B2，2026-09-22）；
        #   bot.ignore 一枚已随 prepared 形 P8 批移入 WIRED（S-PREP-B3，2026-09-22）——
        #   它此前**实测拒登**（根 :8570 已走中央缝，但兜底席 label="" 让派生描述符 title 为空、
        #   撞 validate_registry），该拦路判据已被主会话一行修 `title=decl.label or decl.value`
        #   解除并由 canary 常驻钉住 ⇒ 欠债今天兑现。
        #   ⚠ 同批如实留欠账的实测拒登另有二枚（判据不过，非漏登）：bot.meme_library /
        #   bot.group_info 走根泛型执行器（`pipeline.handle_async` :8733 / :8507），
        #   不经 orchestrated_command ⇒ 登记只会账面翻绿而生产零变化＝本门最该拦的假绿。）
        "bot.alias", "bot.auto_send",
        "bot.natural_command", "bot.status",
    }
)

#: INV-RATCHET 上限（RF2-2 根修）：**手写提交整数常量，绝不写 `= len(GENERIC)+len(NOT_WIRED)`**。
#: 旧写法与被检清单同一表达式 ⇒ 真门里 live 缺口恒 == 上限、`gap > GAP_CEILING` 对真树结构性不可能红
#: （评审席注毒 P2b）。改成常量后，"新 descriptor + 同步登记 NOT_WIRED"的欠债 PR 会让 live 缺口
#: 超过这个固定上限 ⇒ INV-RATCHET 当场红。三锁成链：
#:  - 真门 `_check_ratchet`：live 缺口 > 本常量 ⇒ 红；
#:  - 方向锁 `test_gap_ceiling_tracks_registered_debt`：本常量必须 == len(GENERIC)+len(NOT_WIRED)；
#:  - 结构锁 `test_gap_ceiling_is_handwritten_literal_not_derived`：本行必须是整数字面量，非 `len()+len()`。
#: ⇒ 新增欠债（清单变长）须**同时**手改本常量（+1=故意留痕、须评审），迁走欠债（Wave 4.1 移入 WIRED）
#: 须把本常量下调（只准降）。现值 = len(GENERIC)(10)+len(NOT_WIRED)(86)=96
#: （R8 结案：8 枚命令形通电 117→109；weather 随 prepared 形 B0 移入 WIRED 109→108；
#:   S-PREP-B1：P1 批 10 枚 prepared 通电从 route_capability_unmigrated 移入 WIRED 108→98；
#:   S-PREP-B2：P2 批 1 枚 bot.affinity 移入 WIRED 98→97，另三枚实测拒登如实留欠账
#:   （bot.ignore 差 title 判据 / bot.meme_library、bot.group_info 生产不走缝）；
#:   S-PREP-B3：P8 批 1 枚 bot.ignore 兑现欠债移入 WIRED 97→96（B2 那把 title 判据已由
#:   主会话 `title=decl.label or decl.value` 一行修解除），另六枚实测拒登继续留欠账
#:   （meme_library/group_info/content/music/today_history/media_archive 生产不经中央缝）；
#:   S08（P4-C4）：1 枚 creation.tts.synthesize 因控制面落出生产字面 invoke 点移入 WIRED
#:   96→95。现算尺＝`scripts/central_seam_census.py --json` 该 id state=none→wired，
#:   复跑命令＝`python -m pytest tests/test_descriptor_wiredness_ledger.py`（2026-09-23T20:3xZ）。
#:   S63 图 §3.1（P9 批试点，主代理落码）：1 枚 bot.music_mode 仅登记 prepared（根零改动、
#:   命令入口 :7013 已是汇缝字面量）⇒ 95→94。同刻现算复核＝
#:   `python scripts/orchestration_wired_census.py --json` wired 25→26 / not_wired 85→84。
#:   S-R2-LEDGER（2026-09-26）：**本波是"新增 descriptor 同步登记"方向的故意上调留痕**（清单
#:   变长须手改本常量，见上方三锁成链的纪律，非迁移）——#50/#58 波新面四枚入册：
#:   bot.consent / bot.host_state 按泛型形登记 GENERIC（根 :9211 / :9142 走 pipeline.handle_async，
#:   不经中央缝）+2；capability.consent / capability.host_state 按 interface_only 登记 NOT_WIRED +2
#:   ⇒ 现算缺口 len(GENERIC)(12)+len(NOT_WIRED)(85)=97，93→97。方向锁
#:   test_gap_ceiling_tracks_registered_debt 与真树 INV-RATCHET 双向钉住该值，四枚归因见各桶注释。
#:   S-SEAM-FOLLOW-b（2026-09-27，中央调度完全统一波 P0-A·后账跟随）：**迁移方向下调**——
#:   10 枚迁入 WIRED（GENERIC→WIRED 八枚：consent/content/group_info/host_state/image_search/
#:   media_archive/meme_library/music；NOT_WIRED→WIRED 两枚：mail.control/auto_send.preview），
#:   另 GENERIC→WIRED 两枚 subscribe/today_history（命令腿入缝，wired 优先既有规则）⇒
#:   GENERIC 12→2、NOT_WIRED 85→83，现算缺口 2+83=85，97→85（−12，全部对应上方 WIRED 迁移注记；
#:   零放宽：判定表达式一字未动，动的是清单与常量本身=故意留痕）。
GAP_CEILING: int = 85


# ===========================================================================
# 真树扫描（判据真身在 scripts/orchestration_wired_census.py —— 本件只做再导出委托）
# 2026-09-22 S-CENSUS 收口：判据曾在此件与普查脚本各存一份，R8 只扩了门侧 ⇒ 同一真树
# 门报 10/99、人读报表报 2/107（两个真身各说一套）。现两函数都是 census 的薄壳：
# 本件不再有第二支扫描器、第二套优先级规则，一致性由本节末
# ``test_census_report_matches_ledger_partition``（活性）+ ``test_census_cross_check_lock_has_teeth``
# （注毒）+ ``test_ledger_scanners_are_reexports_not_second_copy``（结构）三把锁死。
# ===========================================================================
def _scan_real_tree() -> tuple[dict[str, set[str]], set[str]]:
    """返回 (invoke 点 by cid, 泛型执行器 cid 集合)。语法错误按 RF2-5 口径当场炸（普查脚本选择点名续跑）。

    2026-09-27 S-SEAM-FOLLOW-c 撤过渡臂（留痕）：P0-A（S-SEAM-FOLLOW-b）曾在本函数并入
    `_viaid.root_funnel_literal_cids()` 代扫根汇缝字面量站点，因当时旧尺 scan_wiredness
    三支（字面 invoke / R8 注册声明 / 泛型执行器字面）对 `_run_capability_through_pipeline`
    的 12 枚迁移失明。撤臂条件（"旧尺补第四臂后撤过渡臂"）已兑现——第四臂落在
    census `scan_wiredness`（同一判据真身、同一 sys.modules 挂钩，注毒可跨件传导），
    本函数自此回到**纯再导出委托**，回到 S-CENSUS 收口的判据一支原形。
    优先级仍走 census.live_partition 唯一规则（wired 优先）。
    """
    syntax_errors: list[str] = []
    invoke_hits, generic_files = _census.scan_wiredness(syntax_errors)
    if syntax_errors:  # RF2-5 口径对齐：静默 continue=假绿温床，改当场炸（与 parity 门同判）
        raise AssertionError(f"接入缺口台账扫描到语法错误文件，拒绝静默跳过：{'、'.join(syntax_errors)}")
    return invoke_hits, set(generic_files)


def _live_partition(
    descriptor_ids: Iterable[str],
    invoke_hits: dict[str, set[str]],
    generic_hits: set[str],
) -> tuple[set[str], set[str], set[str]]:
    """按 wired 优先归三桶（invoke 出现即 wired，其残留泛型字面量不计 generic）——判据在 census。"""
    return _census.live_partition(descriptor_ids, invoke_hits, generic_hits)


# ===========================================================================
# 四条不变量谓词（各回带不变量标签的违规清单；喂真树或合成皆可）
# ===========================================================================
def _check_coverage(descriptor_ids: Iterable[str]) -> list[str]:
    ids = set(descriptor_ids)
    registered = set(WIRED) | set(GENERIC) | NOT_WIRED
    v: list[str] = []
    missing = ids - registered
    ghost = registered - ids
    if missing:
        v.append(f"[INV-COVERAGE] 新出现未登记 descriptor（注册≠接完，须归入 wired/generic/not_wired 之一）：{sorted(missing)}")
    if ghost:
        v.append(f"[INV-COVERAGE] 清单在册而真册已无此 descriptor（清单糊住真实退化）：{sorted(ghost)}")
    return v


def _check_wired(invoke_hits: dict[str, set[str]]) -> list[str]:
    v: list[str] = []
    for cid, files in sorted(WIRED.items()):
        live = invoke_hits.get(cid, set())
        gone = files - live
        if gone:
            v.append(f"[INV-WIRED] {cid} 登记的 invoke 点在真树找不到（通电退化）：{sorted(gone)}")
    unregistered_invoke = {cid for cid, files in invoke_hits.items() if files and cid not in WIRED}
    if unregistered_invoke:
        v.append(f"[INV-WIRED] 真树冒出未登记的 invoke 点（须先评审入 WIRED）：{sorted(unregistered_invoke)}")
    return v


def _check_generic(descriptor_ids: Iterable[str], invoke_hits: dict[str, set[str]], generic_hits: set[str]) -> list[str]:
    _wired, live_generic, _nw = _live_partition(descriptor_ids, invoke_hits, generic_hits)
    v: list[str] = []
    if live_generic != set(GENERIC):
        added = live_generic - set(GENERIC)
        removed = set(GENERIC) - live_generic
        if added:
            v.append(f"[INV-GENERIC] 新增未登记的泛型执行器 id：{sorted(added)}")
        if removed:
            v.append(f"[INV-GENERIC] 登记的泛型执行器 id 在真树消失：{sorted(removed)}")
    return v


def _check_ratchet(descriptor_ids: Iterable[str], invoke_hits: dict[str, set[str]], generic_hits: set[str]) -> list[str]:
    _wired, live_generic, live_not_wired = _live_partition(descriptor_ids, invoke_hits, generic_hits)
    gap = len(live_generic) + len(live_not_wired)
    if gap > GAP_CEILING:
        return [f"[INV-RATCHET] 未通电缺口上升：实得 {gap} > 上限 {GAP_CEILING}（只准降不准升；确属迁移请先更新清单）"]
    return []


# ===========================================================================
# ① 真树活性判据：真树 == 清单，四条不变量全绿
# ===========================================================================
def test_real_tree_matches_wiredness_ledger() -> None:
    descriptor_ids = _load_descriptor_ids()
    invoke_hits, generic_hits = _scan_real_tree()
    violations = (
        _check_coverage(descriptor_ids)
        + _check_wired(invoke_hits)
        + _check_generic(descriptor_ids, invoke_hits, generic_hits)
        + _check_ratchet(descriptor_ids, invoke_hits, generic_hits)
    )
    assert violations == [], "接入缺口台账漂移：\n" + "\n".join(violations)


# ===========================================================================
# ② 注毒自证：四条不变量各真的会红，且红在点名那一条（合成输入，不碰真树）
# ===========================================================================
def test_poison_unregistered_descriptor_is_red_on_coverage() -> None:
    """注毒：在册表凭空多一条不属于任何清单的 descriptor → 只杀 INV-COVERAGE。"""
    poisoned = set(_load_descriptor_ids()) | {"brand.new.capability"}
    v = _check_coverage(poisoned)
    assert any("[INV-COVERAGE]" in s and "brand.new.capability" in s for s in v), v
    # 归因唯一：真树扫描（invoke/generic）不含该合成 id，另两条谓词不该因这条毒而红
    invoke_hits, generic_hits = _scan_real_tree()
    assert _check_wired(invoke_hits) == []
    assert _check_generic(poisoned, invoke_hits, generic_hits) == []


def test_poison_ghost_ledger_entry_is_red_on_coverage() -> None:
    """注毒：清单里登记了一条而真册已删 → 消失也红（INV-COVERAGE 反向）。"""
    shrunken = set(_load_descriptor_ids()) - {"search.web"}
    v = _check_coverage(shrunken)
    assert any("[INV-COVERAGE]" in s and "search.web" in s for s in v), v


def test_poison_vanished_wired_site_is_red_on_wired() -> None:
    """注毒：抽掉 search.web 登记的 invoke 点 → 杀 INV-WIRED。"""
    invoke_hits, _generic_hits = _scan_real_tree()
    invoke_hits.pop("search.web", None)
    v = _check_wired(invoke_hits)
    assert any("[INV-WIRED]" in s and "search.web" in s for s in v), v


def test_poison_new_invoke_site_is_red_on_wired() -> None:
    """注毒：一条 not_wired 的能力突然冒出 invoke 点却不更新清单 → 杀 INV-WIRED（未登记 invoke）。

    受害对象**现算**而不是写死 cid：2026-09-22 prepared 形落地时，原先写死的
    `bot.weather` 刚好被迁移进 WIRED，这条注毒当场变成"毒没下进去"的空跑——
    写死受害者的注毒用例，保质期就等于"下一次迁移"。
    """
    invoke_hits, _generic = _scan_real_tree()
    victims = sorted(set(NOT_WIRED) - set(invoke_hits))
    assert victims, "NOT_WIRED 里已无任何未登记 invoke 点的成员，本注毒失去落点"
    victim = victims[0]
    invoke_hits[victim] = {"__init__.py"}
    v = _check_wired(invoke_hits)
    assert any("[INV-WIRED]" in s and victim in s for s in v), v


def test_poison_new_generic_id_is_red_on_generic_and_ratchet() -> None:
    """注毒：泛型执行器上多出一个未登记 capability_id → 同时杀 INV-GENERIC 与 INV-RATCHET。"""
    descriptor_ids = _load_descriptor_ids()
    invoke_hits, generic_hits = _scan_real_tree()
    generic_hits = generic_hits | {"bot.brand.new.generic"}
    # 该 id 需先在 descriptor 里才会计入 generic 面——用合成 descriptor 集模拟"在册且走泛型但没登记"
    synthetic_ids = set(descriptor_ids) | {"bot.brand.new.generic"}
    # 清单没这条 ⇒ coverage 也会红；本毒只验 generic/ratchet 各自归因
    g = _check_generic(synthetic_ids, invoke_hits, generic_hits)
    assert any("[INV-GENERIC]" in s and "bot.brand.new.generic" in s for s in g), g
    r = _check_ratchet(synthetic_ids, invoke_hits, generic_hits)
    assert any("[INV-RATCHET]" in s for s in r), r


def test_generic_executor_scanner_reads_capability_id_literal() -> None:
    """扫描器自证（防门变哑）：泛型执行器判据确实从 handle_async / _run_simple_capability
    的关键字字面量提 id；换个方法名或换个参数名都不该命中。"""
    src = (
        "async def f(pipeline, msg):\n"
        "    await pipeline.handle_async(msg, cap, capability_id='bot.demo')\n"
        "    await _run_simple_capability(bot, ev, factory, capability_id='bot.demo2', matcher=m)\n"
        "    await pipeline.other_async(msg, capability_id='bot.ignored')\n"
        "    await pipeline.handle_async(msg, cap, some_id='bot.wrong_kwarg')\n"
    )
    found = _census._generic_executor_cids(ast.parse(src))
    assert found == {"bot.demo", "bot.demo2"}, found


def test_ledger_partitions_are_disjoint_and_complete() -> None:
    """清单自身自洽（结构性锁）：三桶两两不相交，并起来即在册全集。"""
    assert not (set(WIRED) & GENERIC), "wired 与 generic 不能重叠"
    assert not (set(WIRED) & NOT_WIRED), "wired 与 not_wired 不能重叠"
    assert not (GENERIC & NOT_WIRED), "generic 与 not_wired 不能重叠"
    descriptor_ids = _load_descriptor_ids()
    assert set(WIRED) | GENERIC | NOT_WIRED == set(descriptor_ids)


def test_wired_sites_are_actually_invoke_callsites_in_tree() -> None:
    """活性质地锁：登记的每个 wired 点必须真的能在真树里按 invoke-capability_id 找回来
    （防清单写成字符串快照却与扫描判据脱节）。"""
    descriptor_ids = _load_descriptor_ids()
    invoke_hits, generic_hits = _scan_real_tree()
    wired, _gen, _nw = _live_partition(descriptor_ids, invoke_hits, generic_hits)
    assert wired == set(WIRED), f"真树 invoke 面与清单不符：{sorted(wired)} ≠ {sorted(set(WIRED))}"
    for cid, files in WIRED.items():
        assert files <= invoke_hits.get(cid, set()), f"{cid} 登记的 invoke 文件不在真树扫描结果里"


# ===========================================================================
# ③ INV-RATCHET 去自指（RF2-2）：手写上限 + 方向锁 + 结构锁
# ===========================================================================
def test_seam_accounting_lock_has_teeth() -> None:
    """注毒自证（R8）：抽掉「认 route 执行形声明为通电点」这一步 ⇒ 8 枚当场掉回欠债。

    并入的那份命中集不是把清单改个名字睡大觉：它既是这 8 枚 wired 的**唯一**来源，
    也是 `GAP_CEILING` 能停在现值的**唯一**原因。两头都测（INV-WIRED + INV-RATCHET），
    这样将来谁把并集删掉、或偷偷把基线调回去，本门自己会叫。
    """
    seam = _v1.seam_registered_cids()
    ids = _load_descriptor_ids()
    seam_ids = {cid for cid in seam if cid in ids}
    assert len(seam_ids) >= 8, sorted(seam_ids)

    _wired, _generic, not_wired = _live_partition(ids, {}, set())
    assert seam_ids & not_wired == seam_ids, "注毒样本本身失效＝这 8 枚已被别的判据认成通电"

    violations = _check_ratchet(ids, {}, set()) + _check_wired({})
    assert any("[INV-RATCHET]" in item for item in violations), violations
    assert any("[INV-WIRED]" in item for item in violations), violations


def test_gap_ceiling_tracks_registered_debt() -> None:
    """方向锁（RF2-2）：手写 GAP_CEILING 必须 == 清单现算缺口。它不再由清单派生，故本断言从
    "同一表达式恒等（自指假锁）"升为真锁——清单变长而常量没跟上（新增欠债），或清单变短而常量
    没下调（迁走欠债），本锁皆红，逼作者显式改常量=故意留痕。"""
    derived = len(GENERIC) + len(NOT_WIRED)
    assert GAP_CEILING == derived, (
        f"手写上限 {GAP_CEILING} 与清单现算缺口 {derived} 脱钩——改清单必同步改 GAP_CEILING"
        "（新增欠债须评审、迁移只准降），别留漂移"
    )


def test_gap_ceiling_is_handwritten_literal_not_derived() -> None:
    """结构锁（RF2-2 自证形态）：从本文件源码 AST 断言 ``GAP_CEILING`` 被赋为**整数字面量**，
    而非 ``len(GENERIC)+len(NOT_WIRED)`` 这类自指导数。运行期"常量==现算"在清单不变时两式同值，
    唯 AST 判据能拆穿回退到自指写法（评审 P2b 定罪形态）。"""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    value: ast.expr | None = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "GAP_CEILING":
            value = node.value
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "GAP_CEILING":
                    value = node.value
    assert value is not None, "源码顶层找不到 GAP_CEILING 的赋值（判据被搬走？）"
    assert isinstance(value, ast.Constant) and isinstance(value.value, int) and not isinstance(value.value, bool), (
        "INV-RATCHET 上限必须是手写整数字面量，不得 `len()+len()` 现算（自指=棘轮对真树恒不执法，评审 RF2-2）"
    )
    assert value.value == GAP_CEILING, "AST 字面量值与运行期常量不一致（被别处覆写？）"


def test_poison_added_debt_trips_ratchet_against_fixed_ceiling() -> None:
    """活性注毒自证（RF2-2）：模拟"新 descriptor 且同步入 NOT_WIRED"的欠债 PR——live 缺口 = 上限+1
    ⇒ 固定手写上限下 INV-RATCHET 必红。修法前上限随清单现算，该情形恒不红（评审 P2b []）。"""
    descriptor_ids = _load_descriptor_ids()
    invoke_hits, generic_hits = _scan_real_tree()
    synthetic_ids = set(descriptor_ids) | {"bot.brand.new.debt"}
    v = _check_ratchet(synthetic_ids, invoke_hits, generic_hits)
    assert any("[INV-RATCHET]" in s for s in v), f"手写上限未生效、新增欠债漏检：{v}"


def test_poison_syntax_error_file_fails_loud_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒（RF2-5）：`_scan_real_tree` 扫到语法错误文件必须当场抛，不再静默 continue（旧=假绿温床，
    与 parity 门「当场炸」对齐）。隔离真树：把 `_iter_sources` 换成一份坏语法源，断言抛 AssertionError。"""
    monkeypatch.setattr(_census, "_iter_sources", lambda: [("domains/ghost/broken.py", "def (")])
    with pytest.raises(AssertionError, match="语法错误"):
        _scan_real_tree()


# ===========================================================================
# ④ 同源锁（2026-09-22 S-CENSUS）：人读普查报表 == 本门机器账 == 本门登记清单
#    病灶（S-GAPMAP t21 / 被推翻 X-9）：R8 只扩了门侧判据、普查脚本未跟随 ⇒ 同一条真树
#    门报 wired 10 / not_wired 99，脚本打印 wired 2 / not_wired 107，把已通电的 8 枚记成欠账。
#    治法=判据只留一支（census.scan_wiredness / census.live_partition / census.classify_all，
#    本门 _scan_real_tree 与 _live_partition 均为再导出委托），下面四把锁保证它不再分第二次：
#    活性（集合）· 活性（stdout 打出来的数）· 注毒自证 · 结构反二身。
# ===========================================================================
def _report_buckets() -> dict[str, set[str]]:
    """把普查脚本**自己打印**的那份报表（census_states 的态）按态归桶。

    2026-09-27 S-SEAM-FOLLOW-c：P0-A 挂账的过渡臂（含其提升版 `_promoted_report_buckets`）已撤——
    根汇缝字面量并入旧尺 `scan_wiredness` 第四臂后，报表原始态即与门账同源，函数回到
    S-CENSUS 收口时的单一直读原形。
    """
    return {state: set(cids) for state, cids in _census.buckets_of(_census.census_states()).items()}


def test_census_report_matches_ledger_partition() -> None:
    """活性锁：报表三桶、本门真树分类、本门登记清单 **三方同集合**（数字全部现算，无手写计数）。

    2026-09-27 S-SEAM-FOLLOW-c 撤臂归位：过渡期（S-SEAM-FOLLOW-b）报表侧需手动并臂才能对齐，
    现根汇缝字面量臂已在旧尺 scan_wiredness 第四支（判据真身 `_viaid.root_funnel_literal_cids`
    唯一支），三方直接共读同一份账；臂的牙由 `test_funnel_arm_lock_has_teeth`（抽臂必红，
    经 census 传导）与双臂注毒的 `test_census_cross_check_lock_has_teeth`（抽尽双臂回到字面
    invoke 六枚）钉住。
    """
    descriptor_ids = set(_load_descriptor_ids())
    invoke_hits, generic_hits = _scan_real_tree()
    live_wired, live_generic, live_not_wired = _live_partition(descriptor_ids, invoke_hits, generic_hits)
    report = _report_buckets()

    assert (
        report["wired"] == live_wired == set(WIRED)
    ), f"「已通电」三方脱节：报表 {sorted(report['wired'])} ≠ 真树 {sorted(live_wired)} ≠ 账本 {sorted(WIRED)}"
    assert (
        report["generic_executor"] == live_generic == set(GENERIC)
    ), f"「走泛型执行器」三方脱节：报表 {sorted(report['generic_executor'])} ≠ 真树 {sorted(live_generic)} ≠ 账本 {sorted(GENERIC)}"
    assert (
        report["not_wired"] == live_not_wired == set(NOT_WIRED)
    ), f"「在册零调用点」三方脱节：报表 {sorted(report['not_wired'])} ≠ 真树 {sorted(live_not_wired)} ≠ 账本 {sorted(NOT_WIRED)}"

    # 报表自身守恒：三桶互斥、并起来铺满在册表；phantom 只收未在册调用点。
    assert not (report["wired"] & report["generic_executor"])
    assert not (report["wired"] & report["not_wired"])
    assert not (report["generic_executor"] & report["not_wired"])
    assert report["wired"] | report["generic_executor"] | report["not_wired"] == descriptor_ids
    assert not (report["phantom"] & descriptor_ids)


def test_census_printed_counts_match_ledger_buckets(capsys: pytest.CaptureFixture[str]) -> None:
    """活性锁（打印层面）：脚本 **stdout 上那个数** 必须等于脚本判据现算的原始三桶。

    2026-09-27 S-SEAM-FOLLOW-c 撤臂归位：过渡期（S-SEAM-FOLLOW-b）"账本↔打印"直比被拆成
    两段拼合（账本==原始+过渡臂、打印==原始），因旧尺对根汇缝字面量失明；第四臂进
    `scan_wiredness` 后失明消失，本锁恢复**一段直比**——把 `scan_wiredness`+`live_partition`
    唯一真身再走一遍与 stdout 逐态比对（统计代码若再分叉，这里红）。
    臂本身的牙仍由 `test_funnel_arm_lock_has_teeth` 钉。
    """
    import re

    descriptor_ids = set(_load_descriptor_ids())
    syntax_errors: list[str] = []
    raw_invoke, raw_generic = _census.scan_wiredness(syntax_errors)
    assert not syntax_errors, f"打印对账扫到语法错误文件，拒绝静默跳过：{'、'.join(syntax_errors)}"
    live_wired, live_generic, live_not_wired = _census.live_partition(descriptor_ids, raw_invoke, set(raw_generic))
    states = _census.census_states()
    expected: dict[str, set[str]] = {
        _census.STATE_WIRED: live_wired,
        _census.STATE_GENERIC: live_generic,
        _census.STATE_NOT_WIRED: live_not_wired,
        _census.STATE_PHANTOM: {cid for cid, st in states.items() if st == _census.STATE_PHANTOM},
    }
    assert _census.main([]) == 0
    printed = capsys.readouterr().out

    seen: set[str] = set()
    for line in printed.splitlines():
        for state, ids in expected.items():
            got = re.fullmatch(rf"\[{re.escape(state)}\] (\d+) 条", line.strip())
            if got:
                assert state not in seen, f"报表把同一态打印了两次（{state}）——第二套统计复活"
                assert int(got.group(1)) == len(ids), (
                    f"报表打印 [{state}] {got.group(1)} 条，本门账本实为 {len(ids)} 条（两本账又分叉）"
                )
                seen.add(state)
    assert seen == set(expected), f"报表缺态未打印：{sorted(set(expected) - seen)}"
    total = re.search(r"在册 descriptor 总数：(\d+)", printed)
    assert total is not None and int(total.group(1)) == len(descriptor_ids), (
        "报表在册总数与本门 descriptor 账不符"
    )


def test_census_cross_check_lock_has_teeth(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒自证（R8＋旧尺第四臂）：把「注册声明臂」与「根汇缝字面量第四臂」**双臂**
    一起抽掉 ⇒ 报表掉回「命令形迁移面全记欠账」，一致性锁必红、且红在点名。

    重钉说明（2026-09-27 S-SEAM-FOLLOW-c 撤臂归位）：过渡期（S-SEAM-FOLLOW-b）曾把根汇缝
    字面量臂挂在**门侧**；现臂本体已进旧尺 `scan_wiredness` 第四支，抽臂仍走同一真身
    `_viaid.root_funnel_literal_cids`（census 现取模块属性，注毒跨件传导），语义原样。
    双臂抽尽才掉回字面 invoke 六枚——旧用例的「报表 vs 账本」归因语义保留；
    单抽 R8 臂不改变三方集合（双源覆盖），其牙住
    `test_wired_sites_are_actually_invoke_callsites_in_tree`（注册臂死则 REGISTRY_POINTS_AT
    点位失踪必红）。
    """
    def _seam_arm_deleted() -> dict[str, set[str]]:  # 模拟「有人把 R8 那一支从共享扫描里删掉」
        return {}

    monkeypatch.setattr(_v1, "seam_registered_cids", _seam_arm_deleted)
    monkeypatch.setattr(_viaid, "root_funnel_literal_cids", lambda source=None: frozenset())
    with pytest.raises(AssertionError, match="bot.tts"):
        test_census_report_matches_ledger_partition()
    # 归因唯一：双臂抽尽后只剩字面 invoke，**字面 invoke wired 六枚不受影响**（防"整桶塌掉"式误红；
    # VOICE-V12 media.tts.autodub 通电点位=层 1 hook 的字面 invoke，与注册册 seam 声明无关，故同在此列；
    # 第四枚 creation.tts.synthesize＝本波 P4-C4 控制面 POST /api/v1/tts/jobs 的字面 invoke，同族同理，
    # 2026-09-23T20:3xZ 现算随 `GAP_CEILING 96→95` 一同跟随。
    # 第五枚 creation.image.generate＝二批 S262 A 案控制面 POST /api/v1/image-generation/jobs 的字面
    # invoke，同族同理，2026-09-25T04:3xZ 现算随 `GAP_CEILING 94→93`（缺口下降＝收紧方向）一同跟随）。
    report = _report_buckets()
    assert report["wired"] == {
        "creation.tts.synthesize",
        "creation.image.generate",
        "media.vision.anime_ip",
        "search.web",
        "media.tts.autodub",
        # S91 第二腿退役成的中央第三形：通电点位＝层 1 hook 派发 autodub_transform 的字面
        # invoke，与 `media.tts.autodub` 同族同理（现算 2026-09-24T02:06:02Z 随本波跟随）。
        "media.tts.autodub_transform",
    }, sorted(report["wired"])
    # 第四臂抽尽后门账同池：本门 `_scan_real_tree`（委托同一 census）不得还凭空供电＝臂接线无旁路。
    live_wired, _g, _n = _live_partition(
        set(_load_descriptor_ids()), *_scan_real_tree()
    )
    assert live_wired == report["wired"], "双臂已抽尽，门侧扫描仍多供电＝存在第二支臂接线"


def test_funnel_arm_lock_has_teeth(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒自证（旧尺第四臂有牙）：只抽根汇缝字面量臂 ⇒ 12 枚迁移 id 当场掉回欠债。

    2026-09-27 S-SEAM-FOLLOW-c 撤臂归位：臂本体已从门侧迁入旧尺 `scan_wiredness` 第四支，
    注毒挂钩不变（census 现取 `_viaid.root_funnel_literal_cids` 模块属性，同一 sys.modules
    真身，跨件传导），本锁由"抽门侧过渡臂"改为"抽 census 第四臂"——三条红各自归因不变：
    INV-WIRED 点名注册点位 `"__init__.py"` 失踪（以 bot.consent 为证）；
    INV-GENERIC 点名 subscribe/today_history 掉回泛型；三方锁红。反向对照：真树现状双臂
    都在 ⇒ 同一谓词必须 []（防"抽谁都红"式的空转假牙，先算对照再下毒）。
    """
    # 干净现状对照（先算，再进注毒域）：双臂都在时同一谓词必须全绿（活性基线可信）。
    clean_invoke, clean_generic = _scan_real_tree()
    assert _check_wired(clean_invoke) == []
    assert _check_generic(set(_load_descriptor_ids()), clean_invoke, clean_generic) == []
    monkeypatch.setattr(_viaid, "root_funnel_literal_cids", lambda source=None: frozenset())
    invoke_hits, generic_hits = _scan_real_tree()
    v = _check_wired(invoke_hits)
    assert any("[INV-WIRED]" in s and "bot.consent" in s for s in v), v
    g = _check_generic(set(_load_descriptor_ids()), invoke_hits, generic_hits)
    assert any("[INV-GENERIC]" in s and "bot.subscribe" in s for s in g), g
    with pytest.raises(AssertionError):
        test_census_report_matches_ledger_partition()


def test_ledger_scanners_are_reexports_not_second_copy() -> None:
    """结构锁：本门的扫描/归类必须是 census 的**再导出委托**，不得再长出第二支 AST 扫描或第二套
    优先级规则（那正是 2026-09-22 之前双真身各说一套的形态）；反向钉住判据真身确在 census 里。"""
    src_scan = inspect.getsource(_scan_real_tree)
    src_part = inspect.getsource(_live_partition)
    assert "_census.scan_wiredness" in src_scan, "_scan_real_tree 不再委托 census（判据被搬回门里？）"
    assert "_census.live_partition" in src_part, "_live_partition 不再委托 census（第二套优先级规则复活？）"
    for name, body in (("_scan_real_tree", src_scan), ("_live_partition", src_part)):
        assert "ast.parse" not in body and "ast.walk" not in body and "_iter_sources" not in body, (
            f"{name} 里又出现自带扫描判据（ast 解析/文件枚举）——第二真身，须改回委托"
        )
    census_src = (_REPO_ROOT / "scripts" / "orchestration_wired_census.py").read_text(encoding="utf-8")
    assert "def scan_wiredness" in census_src and "def live_partition" in census_src, "判据真身不在普查脚本里了？"
    assert "def classify_all" in census_src, "在册归类出口 classify_all 不在普查脚本里了？"
    assert "seam_registered_cids" in census_src, (
        "普查脚本丢掉 R8 命令形接缝通电臂（报表会再把已通电的能力记成欠账）"
    )
    assert "root_funnel_literal_cids" in census_src, (
        "普查脚本丢掉根汇缝字面量第四臂（S-SEAM-FOLLOW-c 撤台账过渡臂的对价；丢了 12 枚"
        "P0-A 迁移就掉回欠账/泛型——三方锁与 INV-WIRED 会红，但须在此点名根因而非事后追查）"
    )
    census_tree = ast.parse(census_src)
    classifiers = [
        node.name
        for node in census_tree.body
        if isinstance(node, ast.FunctionDef) and "classify" in node.name
    ]
    assert classifiers == ["classify_all"], f"在册归类真身不唯一（第二套归类规则复活）：{classifiers}"
    src_pair = inspect.getsource(_census._collect)
    assert "scan_wiredness(" in src_pair and "classify_all(" in src_pair, (
        "_collect 不再复用两支唯一判据（第二支扫描器 / 第二套归类复活）"
    )
    for fn in (_census.build_census, _census.census_states):
        assert "_collect(" in inspect.getsource(fn), f"{fn.__name__} 绕开了唯一取数出口"
    # 报表出口钉成"逐字一行委托"：先调共享件再自己改判（本锁实测注毒形态）也必须被抓住
    assert "return _collect(syntax_errors)[2]" in inspect.getsource(_census.census_states), (
        "census_states 不再是纯委托（在共享判据之后另算一套 = 第二真身复活）"
    )


# ===========================================================================
# ⑤ 入口耐久（HARDEN-1 I-2 / R10）：每个在册执行形 id 在根里确有汇缝入口
# ===========================================================================
def test_every_execution_shape_id_reaches_a_root_seam_funnel_site() -> None:
    """R9 的第三把锁（常驻版，从批次件上提）：唯一表全部执行形 id ⊆ 根汇缝字面量站点集。

    立门前因：本门对 seam 登记的执行形 id 认"registry 那一行声明"为通电点位
    （`seam_registered_cids()` 与 INV-WIRED 对它们是重言），"根确实汇到缝"此前只住
    `test_prepared_adapter_batch3.py` 的批次件 root-literal 锁——**将来批次测试退役而
    判据没搬走，账仍报现值、根却可以静默漂走**。canary 的多入口活性锁补不了这一腿：
    它管"比较过 capability_id 的函数必须汇缝"（must_watch 点名的是历史双入口五枚），
    不逐枚钉"在册执行形确有字面汇缝站点"。

    为什么住 ledger 而不是 canary（落点裁决）：会说谎的是**账面**——WIRED 桶与
    GAP_CEILING 都由这些声明撑住，本门 R9 注记本就写着"两把锁缺一即假账"；且判据要
    覆盖 command 形（canary 的题域是 prepared 地基信封）。判据真身
    （`root_funnel_literal_cids` / `root_seam_durability_violations` / 唯一表现算
    `execution_shape_cids`）住中央门件，与本锁、batch3 逐批锁同源，不留第二支扫描器。
    参数化源=唯一表现算，零手抄名单：新增一枚执行形而没有根站点 ⇒ 本锁自动点名它。
    """
    declared = _viaid.execution_shape_cids()
    assert declared, "唯一表一枚执行形都没有＝本锁空转（执行形面消失须重判本门，不得绿放行）"
    funnel_cids = _viaid.root_funnel_literal_cids()
    assert funnel_cids & set(declared), (
        "根汇缝字面量扫描一枚在册 id 都没看见＝判据对真树失明（汇缝函数改名/搬走？先对账再动锁）"
    )
    violations = _viaid.root_seam_durability_violations(declared, funnel_cids)
    assert not violations, "接入缺口台账漂移（在册执行形失去根汇缝入口）：\n" + "\n".join(violations)


def test_root_seam_durability_wiring_lock_has_teeth() -> None:
    """注毒自证（本锁→判据**接线**那一层）：抹掉受害者的站点集合 ⇒ 违规谓词恰好点名该枚。

    真树级注毒（在源码副本上删站点再走完整抽取）住
    `test_central_via_identity_and_entry_durability::test_root_seam_durability_lock_has_teeth`，
    与本接线证明共用同一谓词真身，不留第二份；本锁只钉"第⑤节活性测试确实吃这套判据"，
    防的是将来有人把活性测试改成常量真之类的手滑。
    """
    declared = _viaid.execution_shape_cids()
    clean = _viaid.root_funnel_literal_cids()
    victims = sorted(set(declared) & clean)
    assert victims, "没有一枚在册 id 有根汇缝站点＝本注毒失去落点（先查上面那条活性锁为何没红）"
    victim = victims[0]
    violations = _viaid.root_seam_durability_violations(declared, frozenset(clean - {victim}))
    assert len(violations) == 1 and victim in violations[0], (
        f"抹掉 {victim!r} 的汇缝站点后违规面不是恰好一枚：{violations}"
    )
    assert _viaid.root_seam_durability_violations(declared, clean) == [], (
        "干净现状被自己判红＝上面活性锁的基线不可信"
    )

