"""G-CM 常驻门：能力真身册 `domains/core/capability_manifest.py` 的七腿执法 ＋ 三发注毒自证。

教义来源＝用户 2026-09-23 `/goal` 任务书第 1 条（能力真身册）＋四条准绳。
本门只读三面（真身册 / 唯一在册表 `CAPABILITY_DESCRIPTOR` / 缝外普查件），**不写盘、不改判据**。

七腿：
 ①申报必在册（id 唯一性）
 ②执行体可解析（handler_ref 的 `路径#符号` 真存在该符号）
 ②c 镜像一致（S90 补：册内 implementation_ref 与中央 handler_ref 双向逐字相等；
    中央非空而册空须落 IMPL_REF_UNDECLARED_ROSTER。只比字符串、不重算可解析性＝不是腿②第二把尺）
 ②d 执行体行号（S178 补，闭合目标 1 原句「真身路径＋行号」的 A2 半落项）：册内 implementation_line
    必须等于对 implementation_ref 锚点的 AST 现算行，且行号处符号名匹配——不符即红（防漂移假绿）。
    与腿②/②c 三向不重叠：可解析性 / 镜像等值性 / 行号活性各一把
 ③直呼点唯一（已申报能力的执行体符号在 plugins/** 的直呼点数 ≤1，读 S01 普查件现算）
 ⑧直呼点在册（S130 补，CM-P-35-R 裁定 A）：册内 direct_callsites 必须是普查 roster 的
    去行号投影且**双向**等值——漏申报／多申报／零处未点名／量具失明四本账分开红
 ⑨配置键在册（S130 补，用户 2026-09-24 裁定第 6 项「B 起手」）：册内 config_keys 与编排侧
    `_ORCHESTRATION_DESCRIPTORS` 的键并集双向等值；⑨b 反幽灵键（每枚须真是 Config 字段）；
    ⑧b/⑨c 两枚零值名册诚实腿（非零行不得挂零值名册）
 ㉓arms 维双向钉（S190 补，关账「注释承诺了一把不存在的锁」——S187 把 arms 字段写进册、
    docstring 点名腿㉓，而本门当时零命中该判据）：逐枚 `arms` 的形集与「形↔中央汇缝」由两件
    入口活性件**现算派生**（三形走 `test_three_entry_form_seam_liveness.dispatch_table()`，
    主动投递/语音回执两形以 `test_five_entry_seam_lock` 的无夹具执法函数为活性探针、缝取
    `_CENTRAL_TERMINALS − _CENTRAL_HOPS` 唯一枚），四判据各红——在册臂形无执法点／
    seam_host 漂缝／有活入口形不声明臂／活性件长出册外臂形；`ARM_FORM_SEAMS` 单源表与派生集
    同样双向等值（形集+缝值）。真值不落成本门里的字面量清单（快照不是锁）。
 ④触发词是指针不是副本（trigger_source 必须解析到真实符号）
 ⑤在册必有执行面（handler_ref 为空的在册枚数 ≤ 上限，只准降）
 ⑥标签需票根（native-* 无票根即红；每条票根指向的文件真存在）
 ⑦覆盖面棘轮（未申报枚数 ≤ UNCOVERED_CEILING，只降不升；上限真身在
   `domains/core/capability_manifest.py`，**不属本门账**，见 S65 报告 §4）
 ㉕维↔值完整性（S242R 补，防第二种空挂＝**有腿、值全空**——board 曾如此）：简报七维（id／
    执行体真身路径＋行号／唯一直呼点／触发词／配置键／多维标签／板块）逐枚核"要么有真值、要么
    把'无'显式点名"，未点名空位总数经 `VALUE_COMPLETENESS_DEFICIT_CEILING`（ceiling，现算 0）执法；
    执法面从防回潮锁的 `DIMENSION_TO_LEG` 现算、结构维（entry_kinds/arms）显式豁免，新维只挂腿
    不管值 ⇒ `[VALUE-DIM-UNCOVERED]` 红。**与防回潮锁正交**：那把问"有没有腿"，本腿问"有腿之后值
    填没填"，两把不互相替代（注毒㉕-1 用同一条"抹 board 值"证明腿㉔容忍空、唯本腿红）。
 ㉗「已通电 ≠ 已生效」对账（S290C 补，用户 2026-09-25 裁定 OI-071＝做）：在册且**通电**（`arms` 非空
    ＝腿㉓那把尺 ‖ 普查 `state=="wired"`＝腿③/③b 那把尺，两把现成尺分别记账、不新建第三把）的能力，
    若它**申报的** `config_keys`（腿⑨ 的唯一真身）里有"按 `config.py` 缺省即关"的布尔字段，
    就必须在 `EFFECT_PRECONDITION_DISCLOSURES` 逐枚点名「命中哪把通电尺 + 哪些缺省关键 + 一句人话披露」；
    四类违规分开红 `[PD-MISSING]`（通电却不披露＝本腿要堵的那句"已可用"）／`[PD-STALE]`（前置真改开了
    而披露没回头）／`[PD-SHAPE]`（披露的尺或键集合与现算不符）／`[PD-VAPORNOTE]`（披露语空或不含任一所列键）。
    生效侧只读 `Config.model_fields[...].default`（DISPATCH-PROTOCOL 第八节补一的合法口①，**零读 `.env`**）
    ⇒ 本腿判的是"按代码缺省可达吗"，**不是**"现网此刻开没开"，也不得被叙述成后者。
另加扫描面地板（防"把名册清空⇒零违规"的假绿）。

注毒三发＝ test_poison_*：逐发证明对应腿有牙（注毒必红、还原必绿）。

棘轮账的四类锁（2026-09-24 S65 立，S37 席实锤"抬到 999 仍全绿"之后的整改）
------------------------------------------------------------------------
本文件下方 `RATCHET_DIRECTIONS` 是**方向唯一声明处**；判据唯一执法口是
`_ratchet_check`（方向在调用点以字面量申报，未知方向 fail-closed 直接红）。
四类锁的执法件＝`tests/test_capability_manifest_ratchet_direction.py`：
①方向锁（声明＋调用点形状＋命名即方向）、②零余量锁（基线 == 此刻现算）、
③反失明锁（基线必须是手写字面量，禁派生表达式）、④扫描面锁（判据分母设地板）。
复跑（本门 + 四类锁同一进程，普查件只跑一次）：

.. code-block:: bash

    cd ChatBot/ChatBot && PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \\
      PYTHONIOENCODING=utf-8 PYTHONPYCACHEPREFIX=$TEMP/s65-pyc \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      tests/test_capability_manifest_gate.py \\
      tests/test_capability_manifest_ratchet_direction.py \\
      -p no:cacheprovider --basetemp=$TEMP/s65-bt -q
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import json
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.bot_unified_runtime.domains.core import (
    capability_manifest as cm,
)
from plugins.bot_unified_runtime.domains.core import (
    capability_tag_evidence as cte,
)
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    CAPABILITY_DESCRIPTOR,
    registered_capability_ids,
)

# ==========================================================================
# 棘轮账（四枚旧账 + 两枚分母地板）。这一段里的数字是**账**，不是"期望"。
#
# 尺身份三元组（读数离开这三样就不成立）：
#   件   tests/test_capability_manifest_gate.py（本文件，判据唯一真身）
#   函数 measure_execution_surface / declared_unwired_rows / measure_placeholder
#        / measure_registered_total / measure_declared_total / measure_roster_rows
#   命令 见模块 docstring「复跑」段（同一解释器、同一判据、零夹具；本波 S65 另用一次性
#        驱动 %TEMP%/s65_measure.py exec 本门取数，读数与 S37 席 2026-09-23T23:16:43Z
#        的独立读数逐枚相等 62/8/0/120 ⇒ 本席未改账，只加锁）
#
# 现算时刻 **2026-09-24T00:19:08Z（UTC）**（首届，取数时门件本体 sha256[:16]
# `6eb2b89adfacdacf`）；本席交卷前的**核账读数 00:42:12Z**（门件 sha `e93f2a449015f407`）
# 逐枚复算过一次：62 / 8 / 0 / 120 不变，declared 侧地板由 S67 在途批合法顶高 13→19。
# 普查件自报 `meta.generated_at_utc` 与读数同刻。
#
# 想动下面任何一枚字面量，只有两条诚实路径（四类锁逐条拦，抬一格"先过关"当场红）：
#   ①真降账（接真一枚摘一枚 / 占位补真一枚）→ 复算 → 同批把上限改小到现算值；
#   ②名册合法增长把地板顶高 → 复算 → 同批把地板改大到现算值。
# ==========================================================================

#: 在册但 `handler_ref` 为空的枚数（=「在册必有执行面」欠账）。**上限，只准降。**
#: 现算 62（2026-09-24T00:19:08Z）；旧值 0 是主代理凭记忆填的 ⇒ 当场被自己的门打红
#: （"预填达标值"现行犯，已改现算，见 F 册）。首届核账 2026-09-23T19:40:24Z。
EXECUTION_SURFACE_BASELINE = 62

#: 已申报、普查看得见、现算 state≠wired 的枚数。**上限，只准降（接真一枚降一枚）。**
#: 三次核账（同一把尺 `measure_declared_unwired`，并发窗内名册被 S67 在途批推着动过两回）：
#:   00:19:08Z = 8 ⇒ 00:40:11Z = 9（`bot.alias` 诚实新申报而尚未接真，+1）
#:   ⇒ 00:42:12Z = 8（该枚又退出名册，账随现算回落）。本席两次都按"复算 + 同批改字面量"跟随，
#:   不带符号差地留在账里；这不是改判据，是这本账的常态（见 S65 报告 §1 摆动留痕）。
#:   ⇒ **2026-09-25T03:45:48Z = 7**（第三把尺 S317 三次采样 03:45:48／03:54:20／03:57:51Z 恒 7，
#:   另用真身册 `DIRECT_CALLSITES_ZERO_ROSTER` 独立印证同集；分母 scanned=20＝地板、blind=0 ⇒ 非缩面）。
#:   掉的那一枚是 **`creation.image.generate`**，被 **S262 绘画面③ A 案**摘掉：
#:   `domains/creation/image/routes.py:166` 的 `default_invoker().invoke(capability_id="creation.image.generate")`
#:   （surface=plugins，生产侧真命中，配套 `api/v1.py:245-259` 挂载与 17 例测试，盘面 mtime 09-24T20:03:51Z）。
#:   ⚠ **性质＝漏跟随**：同一次落码该跟三本账，`test_descriptor_wiredness_ledger.py`（WIRED＋`GAP_CEILING 94→93`）
#:   与 `capability_manifest.py` 摘牌注释都跟了，**只有本常量没跟** ⇒ 账在此挂红一天一夜。
#: 现算名册 7 枚（只准降）：media.asr.audio_file、media.asr.speech、
#: media.video.frame_extract、media.video.recognize、media.video.subtitle、media.vision.image、
#: media.vision.ocr —— 即「在册但没走中央 invoke 通路」的能力面欠账（P3 主账）。
#: ⚠ 2026-09-23T23:1xZ 前此处的行内注释写「9 枚」并列着 `creation.tts.synthesize`——它 20:37Z
#:   已由 S08 接真翻 wired（S37 抓到这条码-文差一枚），本席按现算改正；两个"9 枚"不是同一批人，
#:   别把它们读成同一件事。
#: ⚠ **口径钉子（S317 O-3 待她裁，本批不动判据）**：本账的 wired 判据是**"有生产侧调用点"**，
#:   **不等于"线上有流量"**——绘画那枚今天以门面 `invoke` 计入 wired，而 provider 空表 ⇒ 真调恒诚实 `UNAVAILABLE`。
#:   故禁把本账从 8 降到 7 叙述成"绘画能出图"。
DECLARED_UNWIRED_BASELINE = 7

#: 未接真名册的**成员集**（与上一枚同批，成员级点名）。
#: ⚠ 为什么数不够、还要钉成员（S333 F-2，2026-09-25）：`DECLARED_UNWIRED_BASELINE` 全树读点
#:   **只比数、无比成员**——今天成员被保护靠的是一条**无人执法的恒等式**
#:   （行内名册 ↔ 现算零直呼点集，而腿③b 钉的是"名册↔现算零处"，不是"名册↔unwired"）。
#:   残存说谎变体：新进的那枚若是 `state=="generic"`（走根泛型执行器），腿③只禁 `offseam_sites`、
#:   `generic_sites` 没有"必须为空"的腿 ⇒ 枚数不变而**身份被换**，账照样绿。
#:   本常量把"身份"也变成要付账的东西：**置换成员必须同批改这里**（故意留痕，不是放宽判据）。
#:   现算与三处独立印证逐枚等集（`declared_unwired_rows()[0]` ／真身册 `DIRECT_CALLSITES_ZERO_ROSTER`
#:   同批的七枚 ／门件行内注释名册），复核件 `.superpowers/sdd/2026-09-24-central-dispatch/ANCHOR-8TO7-VERIFY.md`。
DECLARED_UNWIRED_ROSTER = frozenset({
    "media.asr.audio_file",
    "media.asr.speech",
    "media.video.frame_extract",
    "media.video.recognize",
    "media.video.subtitle",
    "media.vision.image",
    "media.vision.ocr",
})

#: `#reserved` 占位执行体枚数。**上限，只准降。**现算 0
#: （2026-09-24T00:19:08Z；语音摘牌 P4-C3、绘画摘牌 P5 ⇒ 此刻真值就是 0，不是"希望它是 0"；
#: 欠账改名不消失，见 PARKED CM-P-4）。
#: 注：语音摘的是「占位」这一格；普查现算 state 已翻 wired（不再进上一枚账）——
#: **注册 handler ≠ 接进调用链** 这条纪律仍由 `DECLARED_UNWIRED` 与普查态两格分开记，防自欺。
PLACEHOLDER_BASELINE = 0

#: 在册 id 总数（＝腿⑤的扫描面分母）。**地板，只准升。**现算 120（同刻）。
#: 缩面即红，不许"删名册蒙绿"。⚠ 它只拦"今后跌破 120"，对波次已发生的 130→120 漂移永久
#: 失明（S37 §2.4，BASELINE.md 起点未回填，归该册 owner）。
#: S91 合法增长（现算 2026-09-24T02:06:02Z）：自动配音第二条腿内联变换退役为中央第三形
#: `media.tts.autodub_transform`（注册 descriptor+handler，`capability_protocols.py:1939`）
#: ⇒ 在册 120→121，本地板同批改大到现算 121。尺：`registered_capability_ids()` 现算
#: （命令＝`python -c "... registered_capability_ids ..."` 打印 121），非缩面换绿。
REGISTERED_FLOOR = 121

#: 腿③b「已申报」侧的扫描面分母（＝本册申报枚数，由循环体自己数）。**地板，只准升。**
#: 现算 13（2026-09-24T00:19:08Z 首届）。防"把待扫集合缩成手挑子集 ⇒ 未接真数看着变少"这一手。
#: S67 合法增长（现算 2026-09-24T00:33:xxZ）：真身册诚实新申报 6 枚 wired 能力 ⇒ declared_ids()
#: 由 13 涨到 19，本地板同批改大到现算 19（地板只准升，涨由名册合法增长驱动，非缩面换绿）。
#: 复算尺＝measure_declared_scan()＝declared_unwired_rows()[2]（循环体自数，非手挑子集）。
#: S91 合法增长（现算 2026-09-24T02:06:02Z）：真身册补申报第三枚语音腿
#: `media.tts.autodub_transform`（镜像中央 handler_ref，与 `media.tts.autodub` 同判据）
#: ⇒ declared_ids() 19→20，同批改大到现算 20。UNCOVERED_CEILING 保持 101（121−20＝101，
#: 分母与分子同涨一枚 ⇒ 欠账枚数一字不动，非降账、非抬上限）。
DECLARED_SCAN_FLOOR = 20

#: 普查件 roster 行数（腿③b 的另一侧分母：量具自己扫了多少条）。**地板，只准升。**
#: 现算 99（同刻，`central_seam_census.py --json` universe=99）。
#: S91 合法增长（现算 2026-09-24T02:06:02Z）：新在册第三形 `media.tts.autodub_transform`
#: 被普查看见 ⇒ universe 99→100（同刻 counts.declared 51→52 同涨一枚，同因；
#: S86/S95 各自独立observed 同一 +1 并标"他席在飞"，本行把它归因落账）。
#: 复算命令＝`python scripts/central_seam_census.py --json` → `.counts.universe`。
ROSTER_SCAN_FLOOR = 100

#: 七维「值完整性」的**未点名空位总数**（S242R 立，防第二种空挂＝有腿、值全空）。**上限，只准降。**
#: 现算 0（2026-09-25S242R：本册 20 枚对每一枚被执法内容维都是"要么有值、要么显式点名缺位"）。
#: 尺身份三元组：件＝本门；函数＝`measure_value_completeness_deficit`（逐维遍历 `DIMENSION_VALUE_RULES`
#: × `cm.FACETS`，返回"既无真值、又未落对应零值名册"的 (维, 枚) 数）；复跑命令见本件 docstring「复跑」段。
#: 为何取 0 而非"今天现算的某个非零值"：七维的每一格只要空就必须落名册（点名）才算"肯定的无"，
#: 于是诚实册的 deficit 恒为 0、且**随名册增长仍为 0**（新枚要么填值、要么进名册），
#: 不必像 REGISTERED_FLOOR 那样每次合法增长都手动顶高——这是"缺位必须点名"教义的极值形态。
#: 一旦 deficit > 0：要么有人默默清空了一格（防内容侧空挂要抓的正是这一手），
#: 要么加了一枚未点名的空位——两条都逼"复算 + 补名册"，不许把上限抬到非零换绿。
VALUE_COMPLETENESS_DEFICIT_CEILING = 0

#: 方向唯一声明处。`ceiling`=上限（只准降）／`floor`=地板（只准升）。
#: 本 dict 与调用点的 `direction=` 字面量、与常量名后缀（`_BASELINE`/`_CEILING` ⇒ ceiling、
#: `_FLOOR` ⇒ floor）三方一致性，全部由 `tests/test_capability_manifest_ratchet_direction.py` 执法。
RATCHET_DIRECTIONS: dict[str, str] = {
    "EXECUTION_SURFACE_BASELINE": "ceiling",
    "DECLARED_UNWIRED_BASELINE": "ceiling",
    "PLACEHOLDER_BASELINE": "ceiling",
    "REGISTERED_FLOOR": "floor",
    "DECLARED_SCAN_FLOOR": "floor",
    "ROSTER_SCAN_FLOOR": "floor",
    "VALUE_COMPLETENESS_DEFICIT_CEILING": "ceiling",
}

#: 每枚账对应的现算尺函数名（判据唯一真身在本文件；锁件按名取函数、不另数一遍）。
RATCHET_MEASURES: dict[str, str] = {
    "EXECUTION_SURFACE_BASELINE": "measure_execution_surface",
    "DECLARED_UNWIRED_BASELINE": "measure_declared_unwired",
    "PLACEHOLDER_BASELINE": "measure_placeholder",
    "REGISTERED_FLOOR": "measure_registered_total",
    "DECLARED_SCAN_FLOOR": "measure_declared_scan",
    "ROSTER_SCAN_FLOOR": "measure_roster_rows",
    "VALUE_COMPLETENESS_DEFICIT_CEILING": "measure_value_completeness_deficit",
}

_CENSUS = ROOT / "scripts" / "central_seam_census.py"


def _exec_body_anchor_line(ref: str) -> tuple[bool, str, int, Path | None]:
    """`路径#符号` 的**唯一** AST 定位尺 → `(是否解析成功, 锚点名, 现算行号, 源文件路径)`。

    锚点口径＝`#符号` 首段（`split('.')[0]`），与旧 `_resolve_symbol` 逐字一致（不另立第二把尺）。
    顶层 def/class、模块级 Assign/AnnAssign 先取（行号更稳），再退回 `ast.walk` 覆盖嵌套方法名
    （如 `result_transform.py#handle`）。定位成功后另读源文件该行，供"行号处符号名匹配"复核。
    未解析一律 `(False, anchor, 0, path_or_None)`——0 行不是"没数"，是"该 ref 不成立"。
    """
    if "#" not in ref:
        return (False, "", 0, None)
    path_part, _, symbol = ref.partition("#")
    path_part = path_part.strip()
    anchor = symbol.split(".")[0].strip()
    if not path_part or not anchor:
        return (False, anchor, 0, None)
    root = ROOT / "plugins" / "bot_unified_runtime"
    candidate = Path(path_part)
    if not candidate.is_absolute():
        for base in (root, ROOT):
            candidate = base / path_part
            if candidate.is_file():
                break
    if not candidate.is_file():
        return (False, anchor, 0, None)
    try:
        tree = ast.parse(candidate.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return (False, anchor, 0, candidate)
    located = 0
    for node in tree.body:  # 顶层定义/赋值优先
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and node.name == anchor:
            located = node.lineno
            break
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == anchor for t in node.targets
        ):
            located = node.lineno
            break
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == anchor:
            located = node.lineno
            break
    if not located:  # 回退：嵌套方法名 / 任意层级同名符号
        for sub in ast.walk(tree):
            if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and sub.name == anchor:
                located = sub.lineno
                break
    return (bool(located), anchor, located, candidate)


def _anchor_name_at_line(path: Path | None, line: int, anchor: str) -> bool:
    """现算行号那一行源码里是否真出现锚点名（"行号处符号名匹配"的独立一腿）。

    AST 的 `FunctionDef.lineno` 自 py3.8 起指到 `def`/`class` 关键字行（装饰器不吞行号），
    故该行理应含锚点名；这一腿拦的是"行号被填到别处、恰与某符号同名混淆"的假绿形态。
    """
    if path is None or line <= 0:
        return False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    return 0 < line <= len(lines) and anchor in lines[line - 1]


def _resolve_symbol(ref: str) -> bool:
    """`路径#符号` 形态的执行体/指针是否真存在（AST 静态可解析）。

    单尺委托：解析真伪只认 `_exec_body_anchor_line`，本函数取其 `[0]`——不重抄路径逻辑，
    免得腿②与腿②d 各长一把尺（第二真身）。
    """
    return _exec_body_anchor_line(ref)[0]


def _census() -> dict[str, Any]:
    """读 S01 普查件（唯一尺子）。整册只跑一次，多腿共用。"""
    global _CENSUS_CACHE
    if _CENSUS_CACHE is None:
        out = subprocess.run(
            [sys.executable, str(_CENSUS), "--json"],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", timeout=900,
            check=False,
        )
        assert out.returncode == 0, f"缝外普查件跑不起来（RC={out.returncode}）：{out.stderr[-400:]}"
        payload = json.loads(out.stdout)
        assert isinstance(payload.get("roster"), dict) and payload["roster"], "普查件未供 roster＝量具瞎了"
        _CENSUS_CACHE = payload
    return _CENSUS_CACHE


_CENSUS_CACHE: dict[str, Any] | None = None


def _roster_row(capability_id: str) -> dict[str, Any]:
    return _census()["roster"].get(capability_id, {})


def _state_in_row(row: Any) -> str:
    """从一行普查记录里取 `state`（真数据与注入的合成名册共用同一把取数尺）。"""
    return str((row or {}).get("state", ""))


def _state_of(capability_id: str) -> str:
    return _state_in_row(_roster_row(capability_id))


def _uncovered(facets: dict[str, cm.CapabilityFacets] | None = None) -> list[str]:
    declared = set((cm.FACETS if facets is None else facets).keys())
    return sorted(registered_capability_ids() - declared)


def _native_without_evidence(facets: dict[str, cm.CapabilityFacets]) -> list[str]:
    """纯谓词（供注毒直接打靶）：返回「声明了 native-* 却没有实测票根」的行。

    native-* 票根的单一真源＝`capability_tag_evidence.TICKETS`（键 `(cid, native_tag_str)`）——
    **不**读 `cm.EVIDENCE`：那会把票根抄成第二真身（S68 已把 native 票根独立出去配扫描面地板）。
    `cm.EVIDENCE` 只留非原生内容档（media.tts.autodub/TTS），由腿⑥第二半判其文件在场。
    """
    return sorted(f"{cid}:{tag.value}" for cid, row in facets.items() for tag in row.tags
                  if tag.value.startswith("native-") and (cid, tag.value) not in cte.TICKETS)


def _implementation_ref_consistency(
    impl_map: dict[str, str],
    roster: frozenset[str],
) -> tuple[list[str], list[str]]:
    """腿②c 判据真身：册内 `implementation_ref` 与中央 `handler_ref` 的**双向**一致性纯谓词。

    只比字符串等值、**绝不重算可解析性**（解析真伪的唯一尺是腿②读中央侧，另立一把＝第二真身）。
    返回 `(mismatch, unrostered_absent)`：
      · `mismatch` —— 册内非空却与中央 handler_ref 不逐字相等（两处各写一份＝漂移）；
      · `unrostered_absent` —— 中央 handler_ref 非空、册内为空、且未落 `IMPL_REF_UNDECLARED_ROSTER`
        （默默不一致）。
    **对每个在册 id 两方向各查一次**（不是只遍历"册非空者"）——单向化会把"漏填"静默放过，
    这一手由 `test_poison_impl_ref_unidirectional_weakening_is_caught_by_reverse_leg` 反向自证。
    """
    mismatch: list[str] = []
    unrostered: list[str] = []
    for cid in sorted(impl_map):
        impl = impl_map[cid]
        desc = getattr(CAPABILITY_DESCRIPTOR[cid], "handler_ref", "") if cid in CAPABILITY_DESCRIPTOR else ""
        if impl:
            if impl != desc:
                mismatch.append(f"{cid}: 册内 {impl!r} ≠ 描述符 handler_ref {desc!r}")
        elif desc and cid not in roster:
            unrostered.append(f"{cid}: 描述符有 handler_ref {desc!r} 而册内空且未入名册")
    return mismatch, unrostered


# ============================ S178 执行体「路径＋行号」维度的现算尺与反漂移假绿腿
def declared_implementation_lines(
    facets: Mapping[str, cm.CapabilityFacets] | None = None,
) -> dict[str, tuple[str, int]]:
    """本册每一枚 → `(implementation_ref, implementation_line)`（缺省读真册，注毒可传合成面）。"""
    source = cm.FACETS if facets is None else facets
    return {cid: (row.implementation_ref, int(row.implementation_line)) for cid, row in source.items()}


def implementation_line_problems(
    declared: Mapping[str, tuple[str, int]],
    lookup=_exec_body_anchor_line,
    name_at_line=_anchor_name_at_line,
) -> list[str]:
    """纯谓词：执行体「真身路径＋行号」两件套逐枚现算核对（防漂移假绿，S178 腿②d）。

    每枚按 `implementation_ref` 是否存在分两支，四种"不匹配即红"各点名：
      · ref 为空但行号非零 —— 没执行体却凭空填了行号；
      · ref 非空但不可解析 —— 路径/符号已失效，行号无从谈起（与腿②同尺，不另判）；
      · ref 可解析但行号 ≤0 —— 有执行体却不申报行号（把"没填"当"没有"）；
      · 声明行 ≠ 现算行 —— 符号被编辑搬走、册没回头（本维存在的理由：旧腿②只判"名在不在文件里"，
        符号搬家也绿；补了行号，漂移当场可见）；
      · 行号处符号名 ≠ 锚点 —— 行号落在别处、恰好数字对但非该符号（假绿）。
    `lookup`/`name_at_line` 只是注毒注入缝（活账走缺省真尺）。
    """
    problems: list[str] = []
    for cid, (ref, line) in sorted(declared.items()):
        if not ref:
            if line != 0:
                problems.append(f"{cid} 无 implementation_ref 却填了行号 {line}（执行体缺位不该有锚）")
            continue
        resolves, anchor, located, path = lookup(ref)
        if not resolves:
            problems.append(f"{cid} 执行体路径/符号不可解析（{ref!r}）——行号无从谈起")
            continue
        if line <= 0:
            problems.append(f"{cid} 有执行体 {ref!r} 却未申报行号（0＝留空当没有）")
        elif line != located:
            problems.append(
                f"{cid} 声明行 {line} ≠ 现算行 {located}（符号漂移、册没回头＝防漂移假绿该抓的那一手）")
        elif not name_at_line(path, line, anchor):
            problems.append(f"{cid} 行 {line} 处符号名不含锚点 {anchor!r}（行号落在别处＝假绿）")
    return problems


# ============================ S130 两枚新维的现算尺与双向判据（直呼点 / 配置键）
#: 普查 roster 里"谁直接调用了这枚能力"的四本站点账 → 桶名（顺序即输出顺序，稳定）。
_SITE_BUCKETS: tuple[tuple[str, str], ...] = (
    ("seam_sites", "seam"),
    ("invoke_sites", "invoke"),
    ("generic_sites", "generic"),
    ("offseam_sites", "offseam"),
)


def direct_callsite_token(kind: str, site: dict[str, Any]) -> str:
    """一个普查站点 → 去行号的直呼点标号（`桶:文件#宿主[#x计数]` 的前半）。

    缝/泛型/invoke 站点的宿主＝被调的中央件名（`fn`，如 `_run_simple_capability`、`invoke`）；
    缝外直呼站点的宿主＝**发起调用的函数**（`enclosing`）并带上被直呼的真身符号（`symbol`），
    因为这一类的语义正是"某人绕过中央缝直接按名调了执行体"，点名发起者才有诊断价值。
    """
    file_part = str(site.get("file") or "<无文件>")
    if kind == "offseam":
        symbol = str(site.get("symbol") or "<无符号>")
        host = str(site.get("enclosing") or "<module>")
        return f"offseam:{file_part}#{host}->{symbol}"
    host = str(site.get("fn") or "<无名>")
    sub_kind = str(site.get("kind") or "")
    if sub_kind:
        host = f"{host}[{sub_kind}]"
    return f"{kind}:{file_part}#{host}"


def project_direct_callsites(row: dict[str, Any] | None) -> tuple[str, ...] | None:
    """普查一行 → 直呼点投影（**唯一投影尺**，册内列由它派生）。

    返回三态，且**两种"空"绝不合并**：
      · `None`   —— 普查根本没有这一行（量具失明，不许被读成"零处"）；
      · `()`     —— 现算真零处（册须落 `DIRECT_CALLSITES_ZERO_ROSTER` 点名）；
      · 非空 tuple —— 逐站点投影，同名站点折叠成 `#xN` 计数。
    折叠掉的是行号（随宿主文件编辑漂移＝常驻假红源），保留的是"谁在调 + 调了几处"
    （新增直呼必变 N 或新增一枚标号 ⇒ 等值当场红），因此去行号**不牺牲这条腿的杀伤力**。
    """
    if row is None:
        return None
    counts: dict[str, int] = {}
    for key, kind in _SITE_BUCKETS:
        for site in row.get(key) or []:
            if not isinstance(site, dict):
                continue  # 形状异常由普查件自己的塌陷锁说话，本尺不猜
            token = direct_callsite_token(kind, site)
            counts[token] = counts.get(token, 0) + 1
    return tuple(sorted(f"{token}#x{n}" for token, n in counts.items()))


def live_direct_callsites() -> dict[str, tuple[str, ...] | None]:
    """本册申报的每一枚 → 普查现算直呼点（活账唯一入口，缺省读真普查件）。"""
    roster = _census()["roster"]
    return {cid: project_direct_callsites(roster.get(cid)) for cid in sorted(cm.FACETS)}


def declared_direct_callsites() -> dict[str, tuple[str, ...]]:
    return {cid: tuple(row.direct_callsites) for cid, row in cm.FACETS.items()}


def orchestration_descriptor_ids() -> frozenset[str]:
    """编排侧描述符（`_ORCHESTRATION_DESCRIPTORS`）覆盖的 capability_id 集合。

    读的是 `DESCRIPTOR_BUILDERS` 展开出来的那份 tuple（协议侧单源），不另立 id 集：
    本册的 `config_keys` 是它的投影，投影源必须是**一张表**，不能是"六处各读一遍取并集"
    （那等于把 CM-P-43 的六处分裂复制进判据，反而替分裂背书）。
    """
    from plugins.bot_unified_runtime.runtime import capability_protocols as protocols

    return frozenset(
        str(descriptor.capability_id) for descriptor in protocols._ORCHESTRATION_DESCRIPTORS
    )


def live_config_keys() -> dict[str, tuple[str, ...] | None]:
    """本册申报的每一枚 → 编排侧描述符 `config_keys` 并集（现算，非手抄）。

    三态与直呼点尺同规：`None`＝描述符表里查无此枚（失明，不许读成"零键"）；
    `()`＝描述符在、键表为空（诚实"这能力不读 Config"）；非空＝键名升序 tuple。
    """
    from plugins.bot_unified_runtime.runtime import capability_protocols as protocols

    acc: dict[str, set[str]] = {}
    for descriptor in protocols._ORCHESTRATION_DESCRIPTORS:
        cid = str(descriptor.capability_id)
        acc.setdefault(cid, set()).update(str(key) for key in descriptor.config_keys)
    return {
        cid: (tuple(sorted(acc[cid])) if cid in acc else None)
        for cid in sorted(cm.FACETS)
    }


def declared_config_keys() -> dict[str, tuple[str, ...]]:
    return {cid: tuple(row.config_keys) for cid, row in cm.FACETS.items()}


def _projection_consistency(
    dimension: str,
    declared: Mapping[str, tuple[str, ...]],
    computed: Mapping[str, tuple[str, ...] | None],
    zero_roster: frozenset[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """两枚新维共用的**双向**一致判据真身（纯谓词，可被注毒直接打靶）。

    返回四本互不重叠的账（分账是刻意的：合成一本"mismatch"就没法证明单向化会丢哪一半牙）：
      · `missing` —— 现算源里有、册里没有（接线/键多了，册没跟随 ⇒ "一枚声明源供出"落空）；
      · `stale`   —— 册里有、现算源里没有（源已撤而册没回头 ⇒ 册在骗人）；
      · `unnamed_zero` —— 两侧皆空却未落零值名册（"没填"被默默读成"没有"）；
      · `blind`   —— 现算源查无此行（量具失明；"看不见"既不是零也不是有）。
    **对每一枚在册 id 两个方向各查一次**（不是只遍历"册非空者"）——单向化静默放过漏填，
    这一手由 `test_poison_projection_unidirectional_weakening_loses_half_its_teeth` 反向自证。
    """
    missing: list[str] = []
    stale: list[str] = []
    unnamed_zero: list[str] = []
    blind: list[str] = []
    for cid in sorted(declared):
        sites = computed.get(cid)
        if sites is None:
            blind.append(f"{cid}: {dimension} 的现算源查无此行（量具失明，不许当零）")
            continue
        decl, comp = set(declared[cid]), set(sites)
        missing += [
            f"{cid}: 现算有 {token} 而册未申报" for token in sorted(comp - decl)]
        stale += [
            f"{cid}: 册申报 {token} 而现算无此值" for token in sorted(decl - comp)]
        if not decl and not comp and cid not in zero_roster:
            unnamed_zero.append(f"{cid}: {dimension} 现算为零却未落零值名册（默默留空）")
    return missing, stale, unnamed_zero, blind


def _zero_roster_is_honest(
    dimension: str,
    roster: frozenset[str],
    declared: Mapping[str, tuple[str, ...]],
    computed: Mapping[str, tuple[str, ...] | None],
) -> list[str]:
    """零值名册诚实腿：名册每一枚必须现算仍是「两侧皆空」的真零位。

    拦两种假账：①把非零的行塞进名册充数（其实两侧有一侧非空）；②名册里的行压根不在册。
    名册枚数只随消化（接真一枚 ⇒ 现算非零 ⇒ 必须摘牌）而减，无独立数字基线。
    """
    bad: list[str] = []
    for cid in sorted(roster):
        if cid not in declared:
            bad.append(f"{cid} 不在本册（名册只对在册行说话）")
            continue
        sites = computed.get(cid)
        if declared[cid]:
            bad.append(f"{cid} 已申报 {declared[cid]!r} 却仍挂零值名册（假缺位）")
        elif sites is None:
            bad.append(f"{cid} 现算源失明，不能记成零位")
        elif sites:
            bad.append(f"{cid} 现算已非零（{sorted(sites)[:2]}…）却仍挂零值名册（该摘牌）")
    return bad


# ------------------------------------------------- 棘轮账的现算尺（唯一真身，锁件按名复用）
def execution_surface_rows() -> tuple[list[str], int]:
    """(在册且 `handler_ref` 为空的 id 名册, 被扫枚数)。

    第二个值是**分母**，由循环体自己数：把循环缩成手挑子集 ⇒ 分母当场掉下来 ⇒
    扫描面锁红（拦"缩面换绿"），不是靠注释承诺。
    """
    empty: list[str] = []
    scanned = 0
    for cid in sorted(registered_capability_ids()):
        scanned += 1
        if not getattr(CAPABILITY_DESCRIPTOR[cid], "handler_ref", ""):
            empty.append(cid)
    return empty, scanned


def declared_unwired_rows(
    roster: dict[str, Any] | None = None,
    declared: Iterable[str] | None = None,
) -> tuple[list[str], list[str], int]:
    """(未接真名册, 失明名册, 被扫枚数)——腿③b 的判据真身。

    第三个值是**分母**，由循环体自己数，所以"把循环缩成手挑子集"必然让它掉下来（④扫描面锁
    据此拦"缩面换绿"），不是靠注释承诺。

    两个形参都只是**注毒注入缝**（缺省 None ⇒ 读真普查件 + 真本册）。注入形存在的唯一目的
    ＝让"分子不动而分母缩一枚"这一手能被离线证明其判据有牙（见
    ``tests/test_capability_manifest_ratchet_direction.py`` 的 ④ 两条自证）。活账永远走缺省，
    并由 ``test_live_path_does_not_use_the_injection_seam`` 钉住"缺省即真身"。
    """
    rows = _census()["roster"] if roster is None else roster
    ids = sorted(cm.declared_ids()) if declared is None else sorted(declared)
    unwired: list[str] = []
    blind: list[str] = []
    scanned = 0
    for cid in ids:
        scanned += 1
        if cid not in rows:
            blind.append(cid)
            continue
        if _state_in_row(rows[cid]) != "wired":
            unwired.append(cid)
    return unwired, blind, scanned


def measure_execution_surface() -> int:
    return len(execution_surface_rows()[0])


def measure_declared_unwired() -> int:
    return len(declared_unwired_rows()[0])


def measure_placeholder() -> int:
    return len(cm.PLACEHOLDER_UNIMPLEMENTED)


def measure_registered_total() -> int:
    return len(registered_capability_ids())


def measure_declared_scan() -> int:
    return declared_unwired_rows()[2]


def measure_roster_rows() -> int:
    return len(_census()["roster"])


# ------------------------------------------------------------------ 棘轮判据唯一执法口
def _ratchet_check(
    *,
    name: str,
    direction: str,
    baseline: int,
    measured: int,
    detail: str = "",
) -> None:
    """按**申报的方向**比账：`ceiling` 只准降（measured ≤ baseline）、`floor` 只准升（≥）。

    设计要点（三条都是被咬出来的）：
    1. 方向必须由调用点以字面量申报——写裸 `<=`／裸 `==` 而不注明方向语义，等于把
       "只降不升"留成散文（S37 实锤：这四枚抬到 999 仍全绿）。
    2. 未知方向 **fail-closed**：不是静默放行，而是当场红。
    3. 用 `raise AssertionError` 而不是裸 `assert`：`python -O` 会剥掉 assert 语句，
       那会让这把口变成"-release 构建里自动放宽"，与本账的教义正相反。
    """
    if direction == "ceiling":
        if measured <= baseline:
            return
        verdict = "超过上限（只准降：消化一枚降一枚）"
    elif direction == "floor":
        if measured >= baseline:
            return
        verdict = "跌破地板（缩面不是降账，是把尺子锯短）"
    else:
        raise AssertionError(
            f"棘轮 {name} 申报的方向 {direction!r} 既不是 ceiling 也不是 floor ⇒ 判据不可信，红")
    message = f"棘轮 {name}={baseline}（{direction}）现算 {measured} {verdict}"
    if detail:
        message += f"：{detail}"
    raise AssertionError(message + "。复跑命令见本件模块 docstring「复跑」段")


# ------------------------------------------------------------------ 七腿
def test_leg1_declared_must_be_registered() -> None:
    """①申报必在册：本册不得凭空发明 id（发明＝第二真身的起点）。"""
    ghost = sorted(cm.declared_ids() - registered_capability_ids())
    assert not ghost, f"本册申报了不在册的 capability_id（第二真身嫌疑）：{ghost}"


def test_leg2_execution_ref_resolves() -> None:
    """②执行体可解析：非占位行的 handler_ref 必须真指到一个符号；占位行必须被点名（缺位可见）。"""
    unresolvable, undeclared_placeholder = [], []
    for cid in sorted(cm.declared_ids()):
        ref = getattr(CAPABILITY_DESCRIPTOR[cid], "handler_ref", "")
        if _resolve_symbol(ref):
            continue
        if ref.endswith("#reserved"):
            if cid not in cm.PLACEHOLDER_UNIMPLEMENTED:
                undeclared_placeholder.append(f"{cid} → {ref!r}")
            continue
        unresolvable.append(f"{cid} → {ref!r}")
    assert not undeclared_placeholder, (
        "执行体是 `reserved` 占位却未进 PLACEHOLDER_UNIMPLEMENTED 名册（＝把未实现写成已实现）："
        + "；".join(undeclared_placeholder))
    assert not unresolvable, "已申报能力的执行体解析不到（在册即骗册）：" + "；".join(unresolvable)


def test_leg2b_placeholder_debt_ratchet_only_falls() -> None:
    """②b 占位欠账只准降：名册里每枚必须现算仍是 `reserved` 占位；摘牌⇒必须已接真（可解析）。

    首届核账＝2026-09-23T19:42:40Z 现算：`creation.tts.synthesize`、`creation.image.generate`
    的 `__init__.py` 只有 docstring（`grep -n reserved …/creation/tts/__init__.py` ⇒ 命中仅在注释里）。
    """
    _ratchet_check(
        name="PLACEHOLDER_BASELINE",
        direction=RATCHET_DIRECTIONS["PLACEHOLDER_BASELINE"],
        baseline=PLACEHOLDER_BASELINE,
        measured=measure_placeholder(),
        detail="、".join(sorted(cm.PLACEHOLDER_UNIMPLEMENTED)),
    )
    still_placeholder = []
    for cid in sorted(cm.PLACEHOLDER_UNIMPLEMENTED):
        ref = getattr(CAPABILITY_DESCRIPTOR.get(cid), "handler_ref", "") if CAPABILITY_DESCRIPTOR.get(cid) else ""
        if _resolve_symbol(ref):
            still_placeholder.append(f"{cid} 已可解析却仍挂占位名")
        else:
            if not str(ref).endswith("#reserved"):
                still_placeholder.append(f"{cid} 既非占位也非可解析（{ref!r}）")
    assert not still_placeholder, "占位名册与实况不符：" + "；".join(still_placeholder)


def test_leg2c_manifest_impl_ref_matches_descriptor() -> None:
    """②c 镜像一致（CM-P-14 升的常驻锁）：册内 implementation_ref 与中央 handler_ref 双向逐字相等。

    与腿②分工不重叠、互不打脸：腿②问「中央那根指针解不解得开」（可解析性，读中央侧一把尺）；
    本腿问「册这一侧的镜像有没有跟中央走偏、有没有默默不镜像」（等值性，只比字符串）。
    它不重算可解析性 ⇒ 不是第二把尺，是"两处必须同步"的账（接线时不必再靠人回头补指针）。
    """
    impl_map = {cid: getattr(row, "implementation_ref", "") for cid, row in cm.FACETS.items()}
    mismatch, unrostered = _implementation_ref_consistency(impl_map, cm.IMPL_REF_UNDECLARED_ROSTER)
    assert not mismatch, (
        "册内 implementation_ref 与中央 handler_ref 各写一份（漂移＝两处不一致，"
        "本波明令禁的第二真身形态之一）：" + "；".join(mismatch))
    assert not unrostered, (
        "中央有执行体而册内空且未落显式名册（默默不一致，缺位必须点名）：" + "；".join(unrostered))


def test_leg2c_roster_rows_are_real_absences() -> None:
    """②c 名册诚实腿：IMPL_REF_UNDECLARED_ROSTER 每枚必须现算仍是「中央非空 + 册内空」的真缺位。

    拦两种假账：①把已镜像的行塞进名册充数（其实非空）；②名册里某枚中央其实也没 handler_ref
    （那属腿⑤「在册必有执行面」的账，不该记在这本"默默不镜像"名册上）。名册今日空 ⇒ 本腿休眠
    但必真；枚数只准降＝此腿随消化一枚而少一枚，无独立数字基线（不与 S65 方向锁的账面纠缠）。
    """
    bad: list[str] = []
    for cid in sorted(cm.IMPL_REF_UNDECLARED_ROSTER):
        row = cm.FACETS.get(cid)
        if row is None:
            bad.append(f"{cid} 不在册 ⇒ 不该进名册（名册只对'在册但选择漏镜像'的行说话）")
            continue
        desc = getattr(CAPABILITY_DESCRIPTOR.get(cid), "handler_ref", "") if CAPABILITY_DESCRIPTOR.get(cid) else ""
        if row.implementation_ref:
            bad.append(f"{cid} 已镜像 {row.implementation_ref!r} 却仍挂名册（假缺位）")
        elif not desc:
            bad.append(f"{cid} 中央本就无 handler_ref（该记腿⑤的账，不记本名册）")
    assert not bad, "IMPL_REF_UNDECLARED_ROSTER 与实况不符：" + "；".join(bad)


def test_leg2d_execution_body_line_matches_ast() -> None:
    """②d 执行体「路径＋行号」两件套（S178 补，闭合目标 1 原句的 A2 半落项）：行号现算派生、防漂移假绿。

    与腿②/腿②c 三向不重叠：腿②问"中央指针解不解得开"（可解析性）、腿②c问"册镜像跟没跟中央走偏"
    （等值性）、本腿问"册申报的行号，是否就是实现件里那个符号此刻的定义行、且该行确实写着该符号"
    （行号活性——旧腿②拿代理指标当真：符号名在文件里存在就绿，搬家也不管）。
    扫描面自证：被核枚数必须逐名等于本册申报枚数（缩面不是合规）。
    """
    declared = declared_implementation_lines()
    assert set(declared) == set(cm.FACETS), "腿②d 的扫描面 ≠ 本册申报面（判据被缩）"
    problems = implementation_line_problems(declared)
    assert not problems, "执行体行号与 AST 现算不符（漂移假绿或漏报）：" + "；".join(problems)
    # 反"真空"自证：本册每枚有 ref 的行都必须带正行号（否则全 0 也能骗过等值）
    with_ref = [cid for cid, (ref, _line) in declared.items() if ref]
    assert with_ref, "本册无一带 implementation_ref，行号腿失去意义"
    assert all(declared[cid][1] > 0 for cid in with_ref), (
        "有执行体的行仍申报行号 0（把'没填'读成'没有'）："
        + "、".join(cid for cid in with_ref if declared[cid][1] <= 0))


def test_leg3_single_direct_callsite() -> None:
    """③直呼点唯一：已申报能力不得有缝外直呼（缝外直呼＝绕过中央缝的第二条路）。"""
    dupes = []
    for cid in sorted(cm.declared_ids()):
        sites = _roster_row(cid).get("offseam_sites") or []
        if sites:
            where = "、".join(f"{s.get('file')}:{s.get('line')}" for s in list(sites)[:3])
            dupes.append(f"{cid}（{len(sites)} 处：{where}）")
    assert not dupes, "已申报能力存在缝外直呼（调用第二条路）：" + "；".join(dupes)


def test_leg3b_declared_unwired_ratchet_only_falls() -> None:
    """③b 缺位可见：本册已申报、普查**看得见**、却现算 state≠wired 的枚数只准降。

    同时钉"量具失明"：已申报但普查名册里根本没有的 id 一律红——
    否则"看不见"会被悄悄读成"没接线"或"已接线"（两种假绿都在这条上）。
    """
    unwired, blind, scanned = declared_unwired_rows()
    assert not blind, f"普查看不见这些已申报能力（量具失明＝不能拿'没扫到'当结论）：{blind}"
    assert scanned == len(cm.declared_ids()), (
        f"腿③b 的扫描面（{scanned}）≠ 本册申报枚数（{len(cm.declared_ids())}）＝判据被缩而不是被消化")
    _ratchet_check(
        name="DECLARED_UNWIRED_BASELINE",
        direction=RATCHET_DIRECTIONS["DECLARED_UNWIRED_BASELINE"],
        baseline=DECLARED_UNWIRED_BASELINE,
        measured=measure_declared_unwired(),
        detail="、".join(unwired),
    )




def test_leg3c_declared_unwired_roster_names_membership() -> None:
    """③c 成员级诚实腿：未接真**是这七枚**，不是"有七枚"。

    腿③b 只比枚数（上限棘轮），本腿比**集合**——它把"换身份不换数"这一手变成红：
    新进一枚 `state=="generic"`（走根泛型执行器）而挤掉一枚真未接者，枚数守恒而账变谎。
    与 `DECLARED_UNWIRED_ROSTER` 同批改动是本仓"一处变更处处跟随"的付费项，故意留痕。
    """
    unwired, blind, scanned = declared_unwired_rows()
    assert not blind and scanned == len(cm.declared_ids()), (
        "成员锁的前置（不失明、不缩面）未成立 ⇒ 本腿结论不可用，先修③b 再读本腿")
    assert frozenset(unwired) == DECLARED_UNWIRED_ROSTER, (
        "未接真名册成员与现算不逐名相等："
        f"只在现算={sorted(set(unwired) - DECLARED_UNWIRED_ROSTER)}；"
        f"只在名册={sorted(DECLARED_UNWIRED_ROSTER - set(unwired))}；"
        "要么有人接真却没降上限、要么换进来一枚没点名的")
    # 枚数守恒**不在本腿比**：`DECLARED_UNWIRED_BASELINE` 只能由 `_ratchet_check` 消费
    # （裸比较会被 `test_no_bare_comparison_against_ratchet_constants` 判红——本腿首版就踩了，
    #  留此注释为据）。上面的逐名相等已蕴含"名册枚数＝现算未接枚数"，而"现算≤上限"由腿③b 执法；
    # 两条合起来，本腿不必也不得再吃一次那枚上限常量。


def test_leg3c_poison_swaps_membership_at_constant_count() -> None:
    """注毒③c（本腿的杀伤力自证）：**换身份不换枚数**必须被成员锁抓到。

    F-2 那一手的具体形状：把一枚真未接者标成 `wired`，同时把一枚在册已接者标成 `generic`
    （走根泛型执行器——腿③只禁 `offseam_sites`，`generic_sites` 今天没有"必须为空"的腿）。
    枚数仍是 7 ⇒ 腿③b 的上限棘轮**全绿**，只有本腿的逐名相等会红。
    合成名册只喂给判据函数，**不改普查件、不改真身册**（注入缝本就为此存在）。
    """
    real = dict(_census()["roster"])
    unwired_now = [c for c in sorted(cm.declared_ids())
                   if c in real and _state_in_row(real[c]) != "wired"]
    wired_now = [c for c in sorted(cm.declared_ids())
                 if c in real and _state_in_row(real[c]) == "wired"]
    if len(unwired_now) != len(DECLARED_UNWIRED_ROSTER) or not wired_now:
        raise AssertionError(
            f"注毒前置不成立（现算未接 {len(unwired_now)} 枚≠名册 {len(DECLARED_UNWIRED_ROSTER)}，"
            f"或无可用的 wired 样本）⇒ 本自证会退化成空跑，先修腿③b 再谈成员锁")
    poisoned = {k: dict(v) for k, v in real.items()}
    victim_out, victim_in = unwired_now[0], wired_now[0]
    poisoned[victim_out]["state"] = "wired"
    poisoned[victim_in]["state"] = "generic"
    swapped, blind, scanned = declared_unwired_rows(roster=poisoned)
    assert not blind and scanned == len(cm.declared_ids()), "注毒样本弄出了失明/缩面，判据不可用"
    assert len(swapped) == len(DECLARED_UNWIRED_ROSTER), (
        f"注毒没做到'枚数守恒'（{len(swapped)}≠{len(DECLARED_UNWIRED_ROSTER)}）⇒ 这一手本腿本来就拦不到")
    assert frozenset(swapped) != DECLARED_UNWIRED_ROSTER, (
        "枚数不变而成员被换，成员锁却没抓到 ⇒ 本腿是空跑")
    assert victim_out not in swapped and victim_in in swapped, (
        "成员锁抓到的不是本毒的形状（归因不清，另查取数尺）")


def test_leg4_trigger_source_is_a_pointer() -> None:
    """④触发词是指针不是副本：命令/别名/自然语序面的能力必须指向词表真身，且指针可解析。"""
    commandish = {cm.EntryKind.COMMAND, cm.EntryKind.ALIAS, cm.EntryKind.NATURAL_LANGUAGE}
    missing = [r.capability_id for r in cm.FACETS.values()
               if commandish & set(r.entry_kinds) and not r.trigger_source]
    assert not missing, "命令面能力未指向触发词真身（在本册抄词表＝第二真身）：" + "、".join(missing)
    bad = [f"{r.capability_id}:{r.trigger_source!r}" for r in cm.FACETS.values()
           if r.trigger_source and not _resolve_symbol(r.trigger_source)]
    assert not bad, "trigger_source 指向不存在的真身符号：" + "；".join(bad)


def test_leg5_registered_rows_have_execution_surface() -> None:
    """⑤在册必有执行面：handler_ref 为空的在册枚数 ≤ 上限（方向＝只准降，非裸 `<=`）。"""
    empty, scanned = execution_surface_rows()
    assert scanned == len(registered_capability_ids()), (
        f"腿⑤的扫描面（{scanned}）≠ 在册 id 总数（{len(registered_capability_ids())}）＝判据被缩")
    _ratchet_check(
        name="EXECUTION_SURFACE_BASELINE",
        direction=RATCHET_DIRECTIONS["EXECUTION_SURFACE_BASELINE"],
        baseline=EXECUTION_SURFACE_BASELINE,
        measured=measure_execution_surface(),
        detail="、".join(empty[:12]),
    )


def test_leg6_native_tags_require_evidence() -> None:
    """⑥标签需票根：native-* 无票根即红（票根单一真源＝`cte.TICKETS`）；册内 `EVIDENCE` 指向的文件也必须真存在。

    与票根门 `test_manifest_tag_evidence.py` 分工不重叠：那门管票根册自身有效性 + 双向对账（声明⇔票根、
    渠道 kind⇔票根）；本腿管"本册任一 native-* 声明，在票根册里到底有没有那一枚"，方向＝声明→票根。
    真数据下 `bot.chat` 三枚原生声明各有票根 ⇒ 本腿为空（不再真空：有真声明在分母上）。
    """
    unsupported = _native_without_evidence(dict(cm.FACETS))
    assert not unsupported, f"声明了 native-* 却无实测票根（HTTP 200 不算）：{unsupported}"
    dangling = []
    for (cid, tag), evidence in cm.EVIDENCE.items():
        token = evidence.evidence
        file_part = token.split(":")[0]
        candidate = ROOT / file_part
        if not candidate.is_file():
            dangling.append(f"{cid}/{tag.value}→{token}")
    assert not dangling, "票根指向不存在的件（空头票）：" + "；".join(dangling)


def test_leg7_coverage_ratchet_never_rises() -> None:
    """⑦覆盖面棘轮：未申报枚数只准降；涨＝有新能力没入册（禁"新能力先跑起来再说"）。"""
    uncovered = _uncovered()
    assert len(uncovered) <= cm.UNCOVERED_CEILING, (
        f"未申报枚数 {len(uncovered)} > 上限 {cm.UNCOVERED_CEILING}"
        f"（新能力必须先入册再被调用）：{uncovered[:12]}")


def test_leg8_direct_callsites_declared_match_census() -> None:
    """⑧ 直呼点在册且与普查双向等值（CM-P-35-R 裁定 A／目标 1「唯一直呼点」缺口）。

    与腿③分工不重叠：腿③只判"有没有缝外直呼"（第二通路），本腿判"这枚能力被谁直接调用
    **说没说得出**"。事实仍只由 `central_seam_census.py` 算一次，本腿只做**投影等值**，
    不重扫、不另立第二把站点尺（那才是本波明令禁的第二真身）。
    """
    missing, stale, unnamed_zero, blind = _projection_consistency(
        "direct_callsites",
        declared_direct_callsites(),
        live_direct_callsites(),
        cm.DIRECT_CALLSITES_ZERO_ROSTER,
    )
    assert not blind, "普查现算源失明（不能把看不见当成零处）：" + "；".join(blind)
    assert not missing, "普查有直呼点而册未申报（册供不出「谁在调它」）：" + "；".join(missing)
    assert not stale, "册申报的直呼点普查已查无（接线撤了而册没回头）：" + "；".join(stale)
    assert not unnamed_zero, "现算零处直呼点却未落零值名册（默默留空）：" + "；".join(unnamed_zero)


def test_leg8b_callsite_zero_roster_rows_are_real_zeros() -> None:
    """⑧b 零值名册诚实腿：`DIRECT_CALLSITES_ZERO_ROSTER` 每枚现算仍是「两侧皆空」。"""
    bad = _zero_roster_is_honest(
        "direct_callsites",
        cm.DIRECT_CALLSITES_ZERO_ROSTER,
        declared_direct_callsites(),
        live_direct_callsites(),
    )
    assert not bad, "直呼点零值名册与实况不符：" + "；".join(bad)


def test_leg9_config_keys_declared_match_descriptors() -> None:
    """⑨ 配置键在册且与编排侧描述符双向等值（用户 2026-09-24 裁定第 6 项「B 起手」）。

    现算单源＝`_ORCHESTRATION_DESCRIPTORS`（`DESCRIPTOR_BUILDERS` 展开）。**这条腿不判"六处已合流"**
    ——CM-P-43 现算的六处跨五文件仍在（A 收口是后一批），本腿只钉"册必须先供出、且与现算源同步"。
    """
    missing, stale, unnamed_zero, blind = _projection_consistency(
        "config_keys",
        declared_config_keys(),
        live_config_keys(),
        cm.CONFIG_KEYS_ZERO_ROSTER,
    )
    assert not blind, (
        "编排侧描述符表查无此枚却已被本册申报（源分裂，别当零键）：" + "；".join(blind))
    assert not missing, "描述符声明了配置键而册未申报：" + "；".join(missing)
    assert not stale, "册申报的配置键描述符侧已无（键撤了而册没回头）：" + "；".join(stale)
    assert not unnamed_zero, "现算零枚配置键却未落零值名册：" + "；".join(unnamed_zero)


def test_leg9b_manifest_config_keys_are_real_config_fields() -> None:
    """⑨b 反幽灵键：本册 `config_keys` 每一枚必须真是 `Config.model_fields` 里的字段。

    判据口径照 `tests/test_prepared_adapter_batch2.py::test_declared_config_keys_exist_on_config_model`
    （`Config.model_fields`，**不用 `hasattr`**——pydantic 上 hasattr 对真字段也 False，
    那把尺会把好键判成幽灵、幽灵判成好键）。本腿读的是**册这一侧**，与那条读 registry 的腿
    不是同一格账：registry 侧干净不代表册侧不夹带手写键。
    """
    from plugins.bot_unified_runtime.config import Config

    fields = set(Config.model_fields)
    ghost = sorted({
        f"{cid}:{key}" for cid, keys in declared_config_keys().items()
        for key in keys if key not in fields})
    assert not ghost, "本册 config_keys 有幽灵键（Config 无此字段）：" + "、".join(ghost)


def test_leg9c_config_keys_zero_roster_rows_are_real_zeros() -> None:
    """⑨c 零值名册诚实腿（与 ⑧b 同型）：`CONFIG_KEYS_ZERO_ROSTER` 每枚现算仍是真零位。"""
    bad = _zero_roster_is_honest(
        "config_keys",
        cm.CONFIG_KEYS_ZERO_ROSTER,
        declared_config_keys(),
        live_config_keys(),
    )
    assert not bad, "配置键零值名册与实况不符：" + "；".join(bad)


def test_leg89_scan_denominators_cover_every_declared_row() -> None:
    """两枚新腿的分母自证：被扫枚数必须 == 本册申报枚数（缩面不是降账，是把尺子锯短）。

    现算源若只覆盖一个手挑子集（例如"挑几枚好填的申报"），两腿会一片绿而账面缺位——
    这条锁让"少扫一枚"当场可见，且它数的是**两本**（册侧 id 集 / 现算侧 id 集），
    不是只数册自己。地板值不写死（写死就变成第二本棘轮账），判据＝逐名全等。
    """
    declared = declared_direct_callsites()
    computed_callsites = live_direct_callsites()
    computed_keys = live_config_keys()
    assert set(declared) == set(computed_callsites) == set(computed_keys), (
        "两枚新腿的扫描面与本册申报面不逐名相等＝判据被缩："
        f"册 {len(declared)} / 直呼点 {len(computed_callsites)} / 配置键 {len(computed_keys)}")
    covered = sum(1 for value in computed_callsites.values() if value is not None)
    assert covered == len(declared), (
        f"直呼点尺现算只覆盖 {covered}/{len(declared)} 枚（缺位由 ⑧ 的 blind 逐枚点名，不许静默）")


# ------------------------------------- S130 两枚新腿的注毒自证（各杀一个方向，合成数据不触盘）
def _first_nonempty_callsite_row() -> tuple[str, str]:
    for cid, sites in sorted(live_direct_callsites().items()):
        if sites:
            return cid, sites[0]
    raise AssertionError("注毒样本失效：本册无一枚非空直呼点，两向判据无从自证")


def test_poison_callsite_new_site_not_followed_is_red() -> None:
    """注毒①（漏申报方向）：普查多出一处直呼点而册没跟随 ⇒ `missing` 必抓到。

    这正是"接线改了不回头"那一格：真数据下 `missing` 必空（先自证前提），
    再从册的投影里抹掉一枚真站点 ⇒ 判据必须把它算成"现算有、册没有"。
    """
    cid, token = _first_nonempty_callsite_row()
    live_missing, live_stale, _, _ = _projection_consistency(
        "direct_callsites", declared_direct_callsites(), live_direct_callsites(),
        cm.DIRECT_CALLSITES_ZERO_ROSTER)
    assert live_missing == [] and live_stale == [], (
        f"真数据两向腿已红（{live_missing} / {live_stale}），注毒无从自证")
    dropped = {k: list(v) for k, v in declared_direct_callsites().items()}
    dropped[cid] = [t for t in dropped[cid] if t != token]
    missing, _stale, _, _ = _projection_consistency(
        "direct_callsites", {k: tuple(v) for k, v in dropped.items()},
        live_direct_callsites(), cm.DIRECT_CALLSITES_ZERO_ROSTER)
    assert any(cid in m and token in m for m in missing), (
        f"抹掉一处真直呼点未被抓到＝漏申报方向无牙：{missing}")


def test_poison_callsite_stale_claim_is_red() -> None:
    """注毒②（多申报方向）：册凭空多写一处普查查无的直呼点 ⇒ `stale` 必抓到（册在骗人）。"""
    cid, _token = _first_nonempty_callsite_row()
    inflated = {k: list(v) for k, v in declared_direct_callsites().items()}
    bogus = "seam:plugins/bot_unified_runtime/__init__.py#_run_capability_through_pipeline#x99"
    inflated[cid] = [*inflated[cid], bogus]
    _, stale, _, _ = _projection_consistency(
        "direct_callsites", {k: tuple(v) for k, v in inflated.items()},
        live_direct_callsites(), cm.DIRECT_CALLSITES_ZERO_ROSTER)
    assert any(cid in s and bogus in s for s in stale), (
        f"多写一处假站点未被抓到＝多申报方向无牙：{stale}")


def test_poison_projection_unidirectional_weakening_loses_half_its_teeth() -> None:
    """注毒③（判据方向自证）：把两向判据"单向化成只查漏申报"⇒ 注毒②那种假账被静默放过。

    同一份合成数据上：双向抓到、单向漏掉，两者结果必须不同。
    若单向也抓到 ⇒ 样本失效（真身可被单向替代），须重推样本而不是放宽判据。
    """
    cid, _token = _first_nonempty_callsite_row()
    inflated = {k: list(v) for k, v in declared_direct_callsites().items()}
    bogus = "seam:plugins/nope/fake.py#fake_host#x1"
    inflated[cid] = [*inflated[cid], bogus]
    declared_poisoned = {k: tuple(v) for k, v in inflated.items()}
    computed = live_direct_callsites()
    _, stale_bidi, _, _ = _projection_consistency(
        "direct_callsites", declared_poisoned, computed, cm.DIRECT_CALLSITES_ZERO_ROSTER)
    assert any(cid in s for s in stale_bidi), "真身（双向）竟漏掉注毒②＝本自证前提塌"
    # 假想"单向化"：只算 comp-decl（漏申报），压根不查 decl-comp ⇒ 假站点不进任何账。
    unidirectional_caught = [
        f"{cid}:{token}" for cid, sites in computed.items()
        for token in set(sites or ()) - set(declared_poisoned.get(cid, ()))
    ]
    assert not any(bogus in hit for hit in unidirectional_caught), (
        "单向化也抓到假站点＝样本失效或真身可被单向替代（须重推样本，别放宽判据）")


def test_poison_callsite_zero_not_named_is_red() -> None:
    """注毒④（零值点名）：两侧皆空却不进零值名册 ⇒ 必红；同一枚入册后 ⇒ 放行（证明抓的是"默默"）。"""
    declared_zero = {"fake.zero.cid": ()}
    computed_zero = {"fake.zero.cid": ()}
    _, _, unnamed, blind = _projection_consistency(
        "direct_callsites", declared_zero, computed_zero, frozenset())
    assert blind == [], "合成样本本该有行，失明账不该非空"
    assert any("fake.zero.cid" in u for u in unnamed), (
        "零处未点名未被抓到＝「没填」会被读成「没有」：" + "；".join(unnamed))
    _, _, named_ok, _ = _projection_consistency(
        "direct_callsites", declared_zero, computed_zero, frozenset({"fake.zero.cid"}))
    assert not named_ok, "入册后仍被抓＝零值名册这道出口失效"
    # 反面对照：真算失明（None）不得被读成零处，也不得靠入册洗白。
    _, _, _, blind_none = _projection_consistency(
        "direct_callsites", declared_zero, {"fake.zero.cid": None}, frozenset({"fake.zero.cid"}))
    assert any("fake.zero.cid" in b for b in blind_none), "现算源缺失被当成零处＝量具失明被吞"


def test_poison_config_key_phantom_is_red() -> None:
    """注毒⑤（多申报方向，配置键）：册多写一枚描述符侧没有的键 ⇒ `stale` 必抓到。"""
    live_missing, live_stale, live_unnamed, live_blind = _projection_consistency(
        "config_keys", declared_config_keys(), live_config_keys(), cm.CONFIG_KEYS_ZERO_ROSTER)
    assert not (live_missing or live_stale or live_unnamed or live_blind), (
        f"真数据配置键腿已红，注毒无从自证：{live_missing} / {live_stale}")
    victim = min(declared_config_keys())
    inflated = {k: list(v) for k, v in declared_config_keys().items()}
    inflated[victim] = [*inflated[victim], "bot_totally_not_a_real_config_field"]
    _, stale, _, _ = _projection_consistency(
        "config_keys", {k: tuple(v) for k, v in inflated.items()},
        live_config_keys(), cm.CONFIG_KEYS_ZERO_ROSTER)
    assert any(victim in s and "bot_totally_not_a_real_config_field" in s for s in stale), (
        f"多写一枚幽灵键未被抓到＝多申报方向无牙：{stale}")


def test_poison_config_key_missing_is_red() -> None:
    """注毒⑥（漏申报方向，配置键）：描述符有键而册漏一枚 ⇒ `missing` 必抓到。"""
    victim = next(cid for cid, keys in sorted(live_config_keys().items()) if keys)
    dropped = {k: list(v) for k, v in declared_config_keys().items()}
    dropped[victim] = dropped[victim][1:]  # 抹掉一枚真键（枚数≥1 由上一发保证）
    missing, _, _, _ = _projection_consistency(
        "config_keys", {k: tuple(v) for k, v in dropped.items()},
        live_config_keys(), cm.CONFIG_KEYS_ZERO_ROSTER)
    assert any(victim in m for m in missing), (
        f"抹掉一枚真配置键未被抓到＝漏申报方向无牙：{missing}")


def test_poison_zero_roster_accepts_a_row_that_is_no_longer_zero() -> None:
    """注毒⑦（零值名册诚实腿）：把一枚"其实非零"的行塞进名册 ⇒ 必被 ⑧b/⑨c 的真缺位判据点名。"""
    victim = next(cid for cid, sites in sorted(live_direct_callsites().items()) if sites)
    bad = _zero_roster_is_honest(
        "direct_callsites",
        frozenset({victim}),
        {victim: ()},
        live_direct_callsites(),
    )
    assert any(victim in line for line in bad), (
        f"非零行挂零值名册未被抓到＝名册可以充数：{bad}")
    assert cm.DIRECT_CALLSITES_ZERO_ROSTER == frozenset({
        cid for cid, sites in live_direct_callsites().items() if sites == ()}), (
        "零值名册与现算零处集合不逐名相等（要么漏点名、要么多点名）——两本账必须同一把尺")


def test_scan_surface_floors_never_shrink() -> None:
    """扫描面地板（三枚分母）：在册总数 / 本册申报数 / 普查 roster 行数只准升。

    拦的是"缩面换绿"：判据的红取决于被扫的集合有多大，把集合锯短（清名册、手挑子集、
    让普查少扫一类文件）会让分子分母一起掉下去、上限棘轮"看起来降了账"。方向＝`floor`，
    与上限的 `ceiling` 在 `_ratchet_check` 里按申报分别比账，不共用一个裸比较。

    三枚地板各自一条显式调用（不写成 `for … globals()` 循环）——写成一圈动态取数，
    方向锁就只能验"有个循环"而验不出"这一枚账的方向是什么"，等于把账退回散文。
    """
    _ratchet_check(
        name="REGISTERED_FLOOR",
        direction=RATCHET_DIRECTIONS["REGISTERED_FLOOR"],
        baseline=REGISTERED_FLOOR,
        measured=measure_registered_total(),
    )
    _ratchet_check(
        name="DECLARED_SCAN_FLOOR",
        direction=RATCHET_DIRECTIONS["DECLARED_SCAN_FLOOR"],
        baseline=DECLARED_SCAN_FLOOR,
        measured=measure_declared_scan(),
    )
    _ratchet_check(
        name="ROSTER_SCAN_FLOOR",
        direction=RATCHET_DIRECTIONS["ROSTER_SCAN_FLOOR"],
        baseline=ROSTER_SCAN_FLOOR,
        measured=measure_roster_rows(),
    )


# ------------------------------------------------------------------ 注毒自证（各杀一条腿）
def test_poison_native_tag_without_evidence_is_red() -> None:
    """注毒①：给某枚**没有对应票根**的能力加 native-audio ⇒ 腿⑥谓词必抓到（真数据下必为空）。

    受害者不能是 `bot.chat`——它三枚原生 kind 都握有票根，给它再加 native-audio 会命中真票根而漏判
    （测夹具不测判据，同 `test_manifest_tag_evidence` 首版的坑）。选 `(cid,"native-audio")` 不在票根册者。
    """
    assert _native_without_evidence(dict(cm.FACETS)) == [], "真数据已红，注毒样本无法自证"
    victims = [cid for cid in cm.FACETS if (cid, "native-audio") not in cte.TICKETS]
    assert victims, "所有已申报能力都有 native-audio 票根，注毒失去意义"
    victim = min(victims)
    src = cm.FACETS[victim]
    poisoned = dict(cm.FACETS)
    poisoned[victim] = cm.CapabilityFacets(
        capability_id=victim,
        entry_kinds=src.entry_kinds,
        tags=(*src.tags, cm.CapabilityTag.NATIVE_AUDIO),
        trigger_source=src.trigger_source,
        board=src.board,
        implementation_ref=src.implementation_ref,
        implementation_line=src.implementation_line,
        direct_callsites=src.direct_callsites,
        config_keys=src.config_keys,
    )
    caught = _native_without_evidence(poisoned)
    assert caught == [f"{victim}:native-audio"], f"注毒未被抓到＝腿⑥无牙：{caught}"


def test_poison_removing_a_row_is_red() -> None:
    """注毒②：从名册删一行（面缩 ⇒ 未申报数涨）必红，堵"删行换绿"。"""
    shrink = {k: v for k, v in cm.FACETS.items() if k != next(iter(cm.FACETS))}
    assert len(_uncovered(shrink)) > cm.UNCOVERED_CEILING, "删行未被抓到＝棘轮无牙"


def test_poison_ghost_id_is_red() -> None:
    """注毒③：发明一个不在册的 id ⇒ 腿①必红（防第二真身从本册长出来）。"""
    ghost = "capability.i-do-not-exist"
    assert ghost not in registered_capability_ids(), "该 id 竟在册，注毒样本失效"
    assert sorted({ghost} - registered_capability_ids()) == [ghost]


def test_poison_fake_execution_ref_is_red(tmp_path: Path) -> None:
    """注毒④：handler_ref 指向不存在符号 ⇒ 腿②判据必给 False（含路径不存在/符号不存在两形）。"""
    assert _resolve_symbol("domains/nope/nowhere.py#Missing") is False
    assert _resolve_symbol("runtime/capability_protocols.py#NoSuchSymbolAtAll") is False
    assert _resolve_symbol("runtime/capability_protocols.py#registered_capability_ids") is True


@pytest.mark.parametrize("ref", ["", "no-hash-sign", "runtime/capability_protocols.py#"])
def test_execution_ref_shape_is_rejected(ref: str) -> None:
    assert _resolve_symbol(ref) is False


# ---------------------------------------------------- 腿②c 注毒自证（三发各杀一个方向）
def _live_impl_map() -> dict[str, str]:
    return {cid: getattr(row, "implementation_ref", "") for cid, row in cm.FACETS.items()}


def _first_declared_with_descriptor_ref() -> str:
    for cid, impl in _live_impl_map().items():
        if impl and getattr(CAPABILITY_DESCRIPTOR.get(cid), "handler_ref", ""):
            return cid
    raise AssertionError("注毒样本失效：无「册已镜像且中央有 handler_ref」的行可摘")


def test_poison_impl_ref_one_char_off_is_red() -> None:
    """注毒①（正向）：把某枚镜像指针故意改歪一字 ⇒ mismatch 必抓到（真数据下 mismatch 必空）。"""
    live = _live_impl_map()
    mismatch_live, _ = _implementation_ref_consistency(live, cm.IMPL_REF_UNDECLARED_ROSTER)
    assert mismatch_live == [], f"真数据正向腿已红，注毒无从自证：{mismatch_live}"
    victim = _first_declared_with_descriptor_ref()
    poisoned = dict(live)
    poisoned[victim] = poisoned[victim] + "X"  # 故意多一个字＝两处各写一份
    mismatch, _ = _implementation_ref_consistency(poisoned, cm.IMPL_REF_UNDECLARED_ROSTER)
    assert any(victim in m for m in mismatch), f"改歪一字未被抓到＝正向无牙：{mismatch}"


def test_poison_impl_ref_missing_without_roster_is_red() -> None:
    """注毒②（反向）：把某枚镜像清空、又不进名册 ⇒ unrostered 必抓（默默不一致＝红）。

    并给反面对照：同一枚改"入册"⇒ 变诚实缺位、反向腿放行——证明抓的是"默默"而非"缺"本身。
    """
    live = _live_impl_map()
    victim = _first_declared_with_descriptor_ref()
    assert getattr(CAPABILITY_DESCRIPTOR[victim], "handler_ref", ""), "注毒样本中央无 ref"
    dropped = dict(live)
    dropped[victim] = ""
    _, unrostered = _implementation_ref_consistency(dropped, cm.IMPL_REF_UNDECLARED_ROSTER)
    assert any(victim in u for u in unrostered), f"漏填未入册未被抓到＝反向无牙：{unrostered}"
    _, unrostered_rostered = _implementation_ref_consistency(dropped, frozenset({victim}))
    assert not any(victim in u for u in unrostered_rostered), "入册后仍被抓＝名册这道出口失效"


def test_poison_impl_ref_unidirectional_weakening_is_caught_by_reverse_leg() -> None:
    """注毒③（判据方向自证）：把一致性判据"单向化成只查册非空者"——毒②那种漏填会被静默放过。

    这条不测真身（真身双向、毒②已证），它测"若有人把它改成单向"会当场失去哪一半牙，从而反向
    证明本席的双向判据不是装饰：同一份合成数据上 bidirectional 抓到、unidirectional 漏掉，二者
    结果必须不同（若单向也抓到 ⇒ 样本失效，判据可被单向替代，重推样本而非放宽判据）。
    """
    live = _live_impl_map()
    victim = _first_declared_with_descriptor_ref()
    dropped = dict(live)
    dropped[victim] = ""
    _, bidi_unrostered = _implementation_ref_consistency(dropped, cm.IMPL_REF_UNDECLARED_ROSTER)
    assert any(victim in u for u in bidi_unrostered), "真身（双向）竟漏掉毒②＝本自证前提塌"
    # 假想"单向化"：只遍历册非空者 ⇒ 空镜像的 victim 根本不进循环，被静默放过。
    unidirectional_caught = [
        cid for cid, impl in dropped.items()
        if impl and impl != getattr(CAPABILITY_DESCRIPTOR[cid], "handler_ref", "")
    ]
    assert victim not in unidirectional_caught, (
        "单向化也抓到 victim＝样本失效或真身可被单向替代（须重推样本，别放宽判据）")


# ---------------------------------------------------- 腿②d 注毒自证（行号维三发，各杀一手）
def test_poison_execution_line_real_row_drift_is_red() -> None:
    """注毒②d-1（真数据漂移）：把某枚真执行体的申报行 +37（符号被搬、册没回头）⇒ 必红。

    这正是补行号的目的：旧腿②只判符号名在不在文件里，搬家照样绿；本腿拿真 ref 现算行比申报行，
    漂一枚当场抓——不靠合成文件、直接对盘上真身验牙。
    """
    live = declared_implementation_lines()
    assert implementation_line_problems(live) == [], f"真数据行号腿已红，注毒失去前提：{live}"
    victims = sorted(cid for cid, (ref, _line) in live.items() if ref)
    assert victims, "本册无一带 implementation_ref 的行，注毒无从下手"
    victim = victims[0]
    ref, line = live[victim]
    tampered = dict(live)
    tampered[victim] = (ref, line + 37)
    probs = implementation_line_problems(tampered)
    assert any(victim in p and "声明行" in p for p in probs), (
        f"漂移 +37 未被抓到＝防漂移假绿无牙：{probs}")


def test_poison_execution_line_missing_or_zero_is_red(tmp_path: Path) -> None:
    """注毒②d-2（漏报/合成）：有执行体却申报行号 0 ⇒ 抓；同件申报正确行号 ⇒ 放（证明抓的是"没填"）。"""
    src = tmp_path / "impl_missing.py"
    src.write_text("def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n", encoding="utf-8")
    ref = f"{src}#beta"  # 绝对路径，_exec_body_anchor_line 直用
    ok, anchor, located, _path = _exec_body_anchor_line(ref)
    assert ok and anchor == "beta" and located == 5, f"合成样本自身定位失准：{ok},{anchor},{located}"
    assert implementation_line_problems({"x": (ref, 5)}) == [], "正确行号被误伤（过拦）"
    assert any("未申报行号" in p for p in implementation_line_problems({"x": (ref, 0)})), (
        "有执行体却填 0 未被抓到＝把'没填'读成'没有'")
    assert any("声明行" in p for p in implementation_line_problems({"x": (ref, 1)})), "改歪行号未被抓到"


def test_poison_execution_line_symbol_name_mismatch_is_red(tmp_path: Path) -> None:
    """注毒②d-3（行号处符号名）：数字对得上、但那行不含锚点名 ⇒ 必红（注入假名尺证这一腿真在跑）。"""
    src = tmp_path / "impl_name.py"
    src.write_text("def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n", encoding="utf-8")
    ref = f"{src}#beta"
    assert implementation_line_problems({"x": (ref, 5)}) == [], "正例被误伤"
    caught = implementation_line_problems(
        {"x": (ref, 5)}, name_at_line=lambda path, line, anchor: False)
    assert any("符号名不含锚点" in c for c in caught), f"行号处符号名腿无牙（可能是装饰性分支）：{caught}"


# ==================================================================== 腿㉓ arms 维（S190）
# 真值只住两件入口活性件，本段只**派生 + 对账**，不抄任何一份形清单/缝清单当结论
# （把今天的集合写成字面量＝快照不是锁，S187 简报点名的代理指标病）。
#
# 派生口径（尺身份三元组之"件:函数"两元全在活性件侧）：
#   · 三形 command/alias/natural_language ← `test_three_entry_form_seam_liveness.dispatch_table()`
#     的 route.form / route.seam 现算（该文件内部形键作 "natural"，故需 `_THREE_FORM_NAME_BRIDGE`
#     命名桥——桥只对齐命名，形集与"桥定义域"双向钉死，活性件长形/改名而不跟桥＝红）。
#   · active_push / voice_ack ← `test_five_entry_seam_lock` 的四枚**无夹具执法函数**直接调用作
#     活性探针（探针红＝该形今天没执法 ⇒ 册内该形臂必红，绝不静默放行）；缝值＝
#     `_CENTRAL_TERMINALS − _CENTRAL_HOPS` 唯一枚（规范出口；封装跳不算缝）。
#   · 零容忍口径随裁定 R-4：探针即执法本身；若五入件被改回棘轮/摘牌，探针函数会红或消失，
#     两者都要求本段重判（`_run_probe` 点名），不许"看不见＝通过"。

_THREE_FORM_MODULE = "test_three_entry_form_seam_liveness"
_FIVE_ENTRY_MODULE = "test_five_entry_seam_lock"

#: 命名桥＝三入件内部形键 → `EntryKind.value`。**只**桥接命名，不承载任何缝/活性结论；
#: 其定义域必须逐名等于活性件派生出的形集（多/少一名皆红，见 `live_arm_seams`）。
_THREE_FORM_NAME_BRIDGE: dict[str, str] = {
    "command": cm.EntryKind.COMMAND.value,
    "alias": cm.EntryKind.ALIAS.value,
    "natural": cm.EntryKind.NATURAL_LANGUAGE.value,
}

#: 五入件里钉「主动投递形」与「语音回执形」的两对无夹具执法函数（函数名即执法身份）。
_ACTIVE_PUSH_PROBES: tuple[str, ...] = (
    "test_active_push_entry_set_is_scanned_not_phantom",
    "test_active_push_convergence_ratchet",
)
_VOICE_ACK_PROBES: tuple[str, ...] = (
    "test_ack_entry_is_scanned_and_wired_to_the_central_exit",
    "test_ack_emits_only_through_injected_submit_not_direct_send",
)


def _load_liveness(module_name: str) -> Any:
    """按模块名装载活性件（合跑时复用 pytest 已装载实例，独跑时补 sys.path 现装）。

    装载失败＝红并点名活性件（"活性件塌了"不是 arms 绿的理由——只跳不红的形态在此堵死）。
    """
    mod = sys.modules.get(module_name)
    if mod is not None:
        return mod
    tests_dir = str(ROOT / "tests")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    try:
        return importlib.import_module(module_name)
    except Exception as exc:  # 装载失败原因五花八门，一律升成点名红（跳/绿都不是选项）
        raise AssertionError(
            f"活性件 {module_name!r} 装载失败 ⇒ arms 维失去执法前提（红，不是跳过）：{exc!r}"
        ) from exc


def _run_probe(mod: Any, func_name: str, *, via: str) -> None:
    """调用活性件自己的无夹具执法函数作活性探针；函数消失与函数红分别点名。"""
    fn = getattr(mod, func_name, None)
    if fn is None or not callable(fn):
        raise AssertionError(
            f"{via} 里已无 {func_name}()＝执法身份搬家/摘牌，腿㉓须随之重判（静默消失不是通过）")
    try:
        fn()
    except AssertionError as exc:
        raise AssertionError(
            f"{via}::{func_name}() 未通过＝该形此刻没有活性执法：{exc}") from exc


def live_arm_seams() -> dict[str, str]:
    """臂之真值 `entry_key -> 中央汇缝`——只由两件入口活性件派生（判据数据的唯一来源）。

    任何派生前提不合（形集与桥不齐、逐形缝不唯一、规范出口不唯一、探针缺失或红）一律
    `AssertionError` 点名原因；本函数**不读** `cm.ARM_FORM_SEAMS`（表是被告，不是尺）。
    """
    out: dict[str, str] = {}

    t3 = _load_liveness(_THREE_FORM_MODULE)
    routes = t3.dispatch_table()
    forms = {str(route.form) for route in routes.values()}
    if forms != set(_THREE_FORM_NAME_BRIDGE):
        raise AssertionError(
            f"三入件现算形集 {sorted(forms)} ≠ 命名桥定义域 {sorted(_THREE_FORM_NAME_BRIDGE)}"
            " ⇒ 活性件长出/改掉/撤走了一个形而腿㉓命名桥未跟随（或桥已过期）")
    per_form_seams: dict[str, set[str]] = {}
    for route in routes.values():
        per_form_seams.setdefault(str(route.form), set()).add(str(route.seam))
    for form in sorted(per_form_seams):
        seams = per_form_seams[form]
        if len(seams) != 1:
            raise AssertionError(f"三入件形 {form!r} 派生缝不唯一：{sorted(seams)}")
        out[_THREE_FORM_NAME_BRIDGE[form]] = next(iter(seams))

    t5 = _load_liveness(_FIVE_ENTRY_MODULE)
    canon = set(t5._CENTRAL_TERMINALS) - set(t5._CENTRAL_HOPS)
    if len(canon) != 1:
        raise AssertionError(
            f"五入件规范中央出口（terminals − hops）不唯一：{sorted(canon)} ⇒ 缝派生前提变了")
    push_seam = next(iter(canon))
    for probe in _ACTIVE_PUSH_PROBES:
        _run_probe(t5, probe, via="五入件(主动投递形)")
    out[cm.EntryKind.ACTIVE_PUSH.value] = push_seam
    for probe in _VOICE_ACK_PROBES:
        _run_probe(t5, probe, via="五入件(语音回执形)")
    out[cm.EntryKind.VOICE_ACK.value] = push_seam
    return out


def declared_arms() -> dict[str, tuple[cm.CapabilityArm, ...]]:
    return {cid: tuple(row.arms) for cid, row in cm.FACETS.items()}


def declared_entry_kinds() -> dict[str, frozenset[str]]:
    return {cid: frozenset(k.value for k in row.entry_kinds) for cid, row in cm.FACETS.items()}


def arm_leg_problems(
    *,
    declared: Mapping[str, tuple[cm.CapabilityArm, ...]],
    entry_kinds: Mapping[str, frozenset[str]],
    live: Mapping[str, str],
    table: Mapping[str, str],
) -> list[str]:
    """腿㉓判据真身（纯谓词，注毒直接打靶）：册的 arms/单源表 ↔ 活性件派生真值。

    分账点名（四类红互不合并，合并就没法证明单向化丢的是哪半牙）：
      · 正向：`形不在单源表`（表外幽灵形，`_arms` 物理生成不出＝手抄）、
        `在册臂形无执法点`（表有而活性件不走）、`seam_host 漂离派生缝`；
      · 反向：`有活入口形未声明臂`（逐能力，arms 形集必须 == entry_kinds ∩ 活形集）、
        `活性臂形无在册认领`（全局，任一活形无一枚在册臂）；
      · 单源表对活性件：`表外形`／`表缺形`／`表缝漂移` 三本；
      · 自洽：臂形 ∈ 自身 entry_kinds、`arm_id == "<cid>:<form>"`（身份投影）、同形不重臂。
    `live` 只应由 `live_arm_seams()` 供；`table` 缺省真身由调用方交（注毒可交合成表）。
    """
    problems: list[str] = []

    for form in sorted(set(table) - set(live)):
        problems.append(f"表外形 ARM_FORM_SEAMS 写了 {form!r} 而活性件不走这形（单源表在骗人）")
    for form in sorted(set(live) - set(table)):
        problems.append(f"表缺形 活性件派生出 {form!r} 而 ARM_FORM_SEAMS 未声明（单源表没跟随）")
    for form in sorted(set(table) & set(live)):
        if table[form] != live[form]:
            problems.append(
                f"表缝漂移 {form}：ARM_FORM_SEAMS={table[form]!r} ≠ 活性件派生={live[form]!r}")

    claimed: set[str] = set()
    for cid in sorted(declared):
        kinds = entry_kinds.get(cid, frozenset())
        seen: set[str] = set()
        for arm in declared[cid]:
            if arm.entry_key not in kinds:
                problems.append(f"{cid} 臂形 {arm.entry_key!r} 不在其 entry_kinds（臂必须⊆声明形）")
            if arm.entry_key not in table:
                problems.append(f"{cid} 形不在单源表 {arm.entry_key!r}（`_arms` 生成不出＝手抄幽灵臂）")
            elif arm.entry_key not in live:
                problems.append(
                    f"{cid} 在册臂形无执法点 {arm.entry_key!r}（表在册而活性件今天不走——臂＝投影，无源即红）")
            elif arm.seam_host != live[arm.entry_key]:
                problems.append(
                    f"{cid} seam_host 漂离派生缝 {arm.entry_key}：申报 {arm.seam_host!r} ≠ 派生 {live[arm.entry_key]!r}")
            expected_id = f"{cid}:{arm.entry_key}"
            if arm.arm_id != expected_id:
                problems.append(f"{cid} 臂身份漂移 arm_id={arm.arm_id!r} ≠ 投影 {expected_id!r}")
            if arm.entry_key in seen:
                problems.append(f"{cid} 同形重臂 {arm.entry_key!r}（一能力一形一枚）")
            seen.add(arm.entry_key)
            claimed.add(arm.entry_key)
        for form in sorted(kinds & set(live) & set(table)):
            if form not in seen:
                problems.append(
                    f"{cid} 有活入口形未声明臂 {form!r}（该形被活性件真走过，arms 是投影不是选项）")

    for form in sorted(set(live) - claimed):
        problems.append(f"活性臂形无在册认领 {form!r}（活性件长出/仍走此形而全册没有一枚臂认领它）")
    return problems


def test_leg23_arms_pinned_bidirectionally_to_liveness() -> None:
    """㉓ arms 维双向钉到两件入口活性件（把 S187 docstring 的承诺变真）。

    与腿③/⑧分工：那两腿管"直呼点"（谁在调）；本腿管"形↔中央汇缝"（从哪类入口、经哪枚缝）。
    判据数据只有两本：`live_arm_seams()`（活性件派生）与 `cm.FACETS[*].arms`（册声明）——
    本门不写任何形/缝字面量清单；扫描面自证＝被扫面逐名等于本册申报面。
    """
    live = live_arm_seams()
    assert live, "臂真值派生成空集＝两件活性件同时失明，四判据会集体真空——这不许是绿"
    declared = declared_arms()
    kinds = declared_entry_kinds()
    assert set(declared) == set(kinds) == set(cm.FACETS), "腿㉓扫描面 ≠ 本册申报面（判据被缩）"
    problems = arm_leg_problems(
        declared=declared,
        entry_kinds=kinds,
        live=live,
        table={str(k): str(v) for k, v in cm.ARM_FORM_SEAMS.items()},
    )
    assert not problems, "腿㉓ arms 维与活性件派生不符（点名红因见明细）：" + "；".join(problems)
    # 反真空对照：册内确实存在非空 arms 声明在分母上（全空册＋全空派生＝两相真空假绿）。
    assert any(arms for arms in declared.values()), "本册无一行 arms，腿㉓失去意义（预填/清空皆须先过此闸）"


# ---------------------------------------------------- 腿㉓ 注毒自证（各杀一个方向，合成不触盘）
def _arm_live_and_table() -> tuple[dict[str, str], dict[str, str]]:
    live = live_arm_seams()
    table = {str(k): str(v) for k, v in cm.ARM_FORM_SEAMS.items()}
    base = arm_leg_problems(
        declared=declared_arms(), entry_kinds=declared_entry_kinds(), live=live, table=table)
    assert base == [], f"真数据腿㉓已红，注毒无从自证：{base}"
    return live, table


def _first_row_with_arms() -> str:
    victims = sorted(cid for cid, arms in declared_arms().items() if arms)
    assert victims, "注毒样本失效：册内无一行带臂"
    return victims[0]


def test_poison_arm_ghost_form_is_red() -> None:
    """注毒㉓-1（正向·形不在册）：给某枚加一条活性件与单源表都不认的形 ⇒ 必红（幽灵臂）。"""
    live, table = _arm_live_and_table()
    victim = _first_row_with_arms()
    ghost = cm.CapabilityArm(f"{victim}:telepathy", "telepathy", "_run_simple_capability")
    declared = declared_arms()
    poisoned = {k: list(v) for k, v in declared.items()}
    poisoned[victim] = [*poisoned[victim], ghost]
    kinds = {k: (set(v) | {"telepathy"} if k == victim else set(v))
             for k, v in declared_entry_kinds().items()}
    problems = arm_leg_problems(
        declared={k: tuple(v) for k, v in poisoned.items()},
        entry_kinds={k: frozenset(v) for k, v in kinds.items()},
        live=live, table=table)
    assert any(victim in p and "telepathy" in p for p in problems), (
        f"加一条不存在的臂形未被抓到＝正向无牙：{problems}")


def test_poison_arm_seam_host_drift_is_red() -> None:
    """注毒㉓-2（缝等值）：把某枚真臂的 seam_host 改成**另一枚真缝** ⇒ 必红（漂移不靠编造假字）。"""
    live, table = _arm_live_and_table()
    victim = _first_row_with_arms()
    arm0 = declared_arms()[victim][0]
    other_seams = sorted({s for s in live.values()} - {arm0.seam_host})
    assert other_seams, "注毒样本失效：派生缝只一枚，无从改指"
    drifted = cm.CapabilityArm(arm0.arm_id, arm0.entry_key, other_seams[0])
    declared = declared_arms()
    poisoned = {k: list(v) for k, v in declared.items()}
    poisoned[victim] = [drifted if a.arm_id == arm0.arm_id else a for a in poisoned[victim]]
    problems = arm_leg_problems(
        declared={k: tuple(v) for k, v in poisoned.items()},
        entry_kinds=declared_entry_kinds(), live=live, table=table)
    assert any(victim in p and arm0.entry_key in p and "seam_host" in p for p in problems), (
        f"缝指错未被抓到＝等值无牙：{problems}")


def test_poison_liveness_grows_unregistered_form_is_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒㉓-3（反向·长册外臂形）：真两件活性件现场长出第四形 ⇒ 派生必须抓到。

    两半各证一件事：
      (a) 真接线自证——monkeypatch 三入件 `dispatch_table()` 多派一形，`live_arm_seams()`
          当场红（命名桥与派生形集不齐）。这证明本腿真在**读活性件**，不是硬抄快照。
      (b) 判据自证——把派生集（合成）多给一形而册不认领 ⇒ `活性臂形无在册认领` +
          `表缺形` 两本账点名（册若永远只按今天的表长，反向就无牙）。
    """
    live, table = _arm_live_and_table()
    # (a) 真活性件注毒（跑完由 monkeypatch 自动还原）
    t3 = _load_liveness(_THREE_FORM_MODULE)
    real_routes = t3.dispatch_table()
    sample = next(iter(real_routes.values()))
    extra = type(sample)("instant", sample.capability_id, sample.handler, sample.seam, sample.builder)
    inflated_routes = {**real_routes, ("instant", sample.capability_id): extra}
    monkeypatch.setattr(t3, "dispatch_table", lambda source=None: inflated_routes)
    with pytest.raises(AssertionError, match="命名桥"):
        live_arm_seams()
    # (b) 合成派生面注毒（册维持真身）
    poisoned_live = dict(live)
    poisoned_live["instant_message"] = next(iter(live.values()))
    problems = arm_leg_problems(
        declared=declared_arms(), entry_kinds=declared_entry_kinds(),
        live=poisoned_live, table=table)
    assert any("instant_message" in p and "无在册认领" in p for p in problems), (
        f"活性件长出册外臂形未被反向抓到＝反向无牙：{problems}")
    assert any("instant_message" in p and "表缺形" in p for p in problems), (
        f"派生新形未同时抓单源表跟随：{problems}")


def test_poison_clearing_live_form_arms_is_red() -> None:
    """注毒㉓-4（反向·逐能力）：把某枚**有活入口形**的臂整条清空 ⇒ 必红。

    语义裁定在此落字：arms 是投影不是可选项——凡 `entry_kinds ∩ 活形集` 非空，清空必红；
    「设计允许空」只属于活形交集为空者（如纯 passive_matcher/scheduler 行），对照段同时证
    本腿没有把"合法留空"错杀（那会诱导后人用缩面绕腿）。
    """
    live, table = _arm_live_and_table()
    live_forms = set(live)
    victims = sorted(cid for cid, ks in declared_entry_kinds().items() if ks & live_forms)
    assert victims, "注毒样本失效：无一枚能力拥有活入口形"
    victim = victims[0]
    declared = {k: list(v) for k, v in declared_arms().items()}
    assert declared[victim], "注毒样本失效：victim 臂本为空"
    declared[victim] = []
    problems = arm_leg_problems(
        declared={k: tuple(v) for k, v in declared.items()},
        entry_kinds=declared_entry_kinds(), live=live, table=table)
    assert any(victim in p and "未声明臂" in p for p in problems), (
        f"清空活形臂未被抓到＝逐能力反向无牙：{problems}")
    quiet = sorted(
        cid for cid, ks in declared_entry_kinds().items() if not (ks & live_forms))
    assert all(cid not in " ".join(problems) for cid in quiet), (
        "无活形的行留空竟被拦（过拦会逼人缩扫描面绕腿）")


def test_poison_arm_form_fully_unclaimed_is_red() -> None:
    """注毒㉓-5（反向·全局）：把唯一认领某活形的臂摘掉 ⇒ `活性臂形无在册认领` 必点名该形。"""
    live, table = _arm_live_and_table()
    claimants: dict[str, list[str]] = {}
    for cid, arms in declared_arms().items():
        for arm in arms:
            claimants.setdefault(arm.entry_key, []).append(cid)
    form = next(f for f in sorted(live) if len(claimants.get(f, [])) == 1)
    victim = claimants[form][0]
    declared = {k: list(v) for k, v in declared_arms().items()}
    declared[victim] = [a for a in declared[victim] if a.entry_key != form]
    problems = arm_leg_problems(
        declared={k: tuple(v) for k, v in declared.items()},
        entry_kinds=declared_entry_kinds(), live=live, table=table)
    assert any(form in p and "无在册认领" in p for p in problems), (
        f"形 {form!r} 全册无人认领未被抓到＝全局反向无牙：{problems}")


def test_poison_arm_form_table_seam_wrong_is_red() -> None:
    """注毒㉓-6（单源表本身）：`ARM_FORM_SEAMS` 某形指错缝（臂与活性件都没错）⇒ 表缝漂移必红。

    这一发专杀"表与臂各写各的"——投影链 `活性件 → 表 → 臂` 的中段漂移必须单独可见。
    """
    live, table = _arm_live_and_table()
    other_seams = sorted({s for s in live.values()})
    assert len(other_seams) >= 2, "注毒样本失效：真缝不足两枚"
    form = min(table)
    wrong = next(s for s in other_seams if s != table[form])
    poisoned_table = dict(table)
    poisoned_table[form] = wrong
    problems = arm_leg_problems(
        declared=declared_arms(), entry_kinds=declared_entry_kinds(),
        live=live, table=poisoned_table)
    assert any(form in p and "表缝漂移" in p for p in problems), (
        f"表指错缝未被抓到＝单源中段无牙（臂侧却仍绿，恰是两账不合并的理由）：{problems}")


def test_poison_arm_identity_drift_is_red() -> None:
    """注毒㉓-7（身份投影）：arm_id 手抄走样（形/缝都对）⇒ 必红（身份也是投影不是选项）。"""
    live, table = _arm_live_and_table()
    victim = _first_row_with_arms()
    arm0 = declared_arms()[victim][0]
    tampered = cm.CapabilityArm(f"someone-else:{arm0.entry_key}", arm0.entry_key, arm0.seam_host)
    declared = {k: list(v) for k, v in declared_arms().items()}
    declared[victim] = [tampered if a.arm_id == arm0.arm_id else a for a in declared[victim]]
    problems = arm_leg_problems(
        declared={k: tuple(v) for k, v in declared.items()},
        entry_kinds=declared_entry_kinds(), live=live, table=table)
    assert any(victim in p and "身份漂移" in p for p in problems), (
        f"arm_id 改歪未被抓到＝身份腿装饰：{problems}")


# ==========================================================================
# 腿㉔ board 维双向钉（S196 补，关账 S193 §1c 现算发现的空挂维——`board` 字段在十维里
# 唯一"在册却无门检查"，与 S187 当时 arms 同型：字段加了、判据没加、docstring 却假称有锁）。
#
# 判据双向 + 现算可复算，真值一律不落成本门里的字面量清单（快照不是锁）：
#   正向 [BOARD-ILLEGAL]：在册枚声明的非空 board 必须是板块声明源 `domains/core/board_taxonomy.py`
#     现算的真一级板块 bid（B01..B10），不抄清单；
#   反向 [BOARD-UNBACKED]：声明的非空 board 必须被板块树对该能力的归属背书——该能力被某 FeatureNode
#     经 `capability_ids` 点名、或其 `impl_paths` 指向该能力 `implementation_ref` 的文件 ⇒ 漂移即红。
#     这就是"一处变更处处跟随"在 board 维的落点：板块树把某能力挪到另一板块而册没回头 ⇒ 当场红。
# 与腿④/腿㉓分工不重叠：④核触发词指针、㉓核「形↔中央汇缝」、本腿核板块指针，各管各维不留第二真身。
#
# ⚠ 本腿**不**强制"被板块树认领者必须在册声明 board"（强制非空＝逼着给现网全空数据填值，属数据
#   填充的后续账，越本席写面）。反向只约束"已声明"的 board——真数据下本册 20 枚 board 现算全空 ⇒
#   本腿绿；其牙由注毒㉔-1/2 合成自证 + 席位报告 on-disk 注毒实证（改在册数据看真腿当场红）。
# ==========================================================================
def _board_taxonomy_valid_bids() -> set[str]:
    """一级板块码集（现算自板块声明源，**不抄清单**）。懒导入保本门顶层零新增依赖边。"""
    from plugins.bot_unified_runtime.domains.core import board_taxonomy as bt

    return {board.bid for board in bt.BOARD_TAXONOMY}


def _capability_impl_file(ref: str) -> str:
    """`implementation_ref`（`路径#符号`）的路径部分；无 ref 返回空串（无从谈归属文件）。"""
    return ref.split("#", 1)[0].strip() if ref else ""


def _impl_path_points_to_file(impl_path: str, capfile: str) -> bool:
    """板块 FeatureNode 的 impl_path 是否"指向"该能力真身文件：等值文件，或文件落在该目录下。"""
    if not capfile:
        return False
    base = impl_path.rstrip("/")
    return capfile == base or capfile.startswith(base + "/")


def _board_attribution_of_facets(
    facets: Mapping[str, cm.CapabilityFacets],
) -> dict[str, frozenset[str]]:
    """现算「本册每枚能力被板块树归属到哪几枚一级板块」——反向判据的唯一真值源。

    归属通道两条（任一命中即归属）：①某 FeatureNode 的 `capability_ids` 点名该 id；
    ②某 FeatureNode 的 `impl_paths` 指向该能力 `implementation_ref` 的文件。板块声明源为空
    或读不出 ⇒ 返回空映射，由反真空自证在真数据下当场红（不许把"没归属"读成"随便声明都行"）。
    """
    from plugins.bot_unified_runtime.domains.core import board_taxonomy as bt

    out: dict[str, frozenset[str]] = {}
    for cid, row in facets.items():
        capfile = _capability_impl_file(row.implementation_ref)
        bids: set[str] = set()
        for board in bt.BOARD_TAXONOMY:
            for feat in board.features:
                if cid in feat.capability_ids or any(
                    _impl_path_points_to_file(p, capfile) for p in feat.impl_paths
                ):
                    bids.add(board.bid)
        out[cid] = frozenset(bids)
    return out


def _board_leg_problems(
    declared_boards: Mapping[str, str],
    valid_bids: set[str],
    attribution: Mapping[str, frozenset[str]],
) -> list[str]:
    """纯谓词：逐枚核 board「要么合法且被归属背书，要么为空」。返回违规清单，空即全绿。

    可喂合成数据（注毒㉔-1/2 直接打靶），不触盘。三类判定各可单独归因：
      · 空串 → 跳过（本腿不强制非空，见上段 ⚠ 与席位报告 §4）；
      · 非空但不在 valid_bids → [BOARD-ILLEGAL]（正向：板块码不存在）；
      · 非空、是合法板块码、但不在板块树对该能力的归属集 → [BOARD-UNBACKED]（反向：归属漂移）。
    """
    problems: list[str] = []
    for cid in sorted(declared_boards):
        board = declared_boards[cid]
        if not board:
            continue
        if board not in valid_bids:
            problems.append(
                f"{cid} board={board!r} 非法板块指针（不在 board_taxonomy 一级板块集）[BOARD-ILLEGAL]")
            continue
        backed = attribution.get(cid, frozenset())
        if board not in backed:
            problems.append(
                f"{cid} board={board!r} 与板块树对该能力的归属 {sorted(backed) or '（无）'} 不一致"
                "（一处变更处处跟随）[BOARD-UNBACKED]")
    return problems


def test_leg24_board_is_a_real_and_consistent_board() -> None:
    """㉔ board 维双向钉到板块声明源（把 S193 §1c 的空挂维升成有执法的维）。

    真值不落成本门里的字面量清单：合法板块集与归属映射都现算自 `board_taxonomy`，扫描面逐名 ==
    本册申报面；反真空自证钉「板块树对本册的归属映射现算必 ≥1 枚非空」（掏空它＝假腿，不许绿）。
    """
    valid = _board_taxonomy_valid_bids()
    assert valid, "board_taxonomy 一级板块集现算为空＝尺失明（板块树被掏空不许当已执法）"
    declared_boards = {cid: getattr(row, "board", "") for cid, row in cm.FACETS.items()}
    attribution = _board_attribution_of_facets(cm.FACETS)
    assert set(declared_boards) == set(attribution) == set(cm.FACETS), (
        "腿㉔扫描面 ≠ 本册申报面（判据被缩）")
    assert any(attribution[cid] for cid in attribution), (
        "板块树对本册无一枚能力形成归属＝反向通道失明（掏空它即假腿，故不许绿）")
    problems = _board_leg_problems(declared_boards, valid, attribution)
    assert not problems, "腿㉔ board 维非法/漂移（点名红因见明细）：" + "；".join(problems)


# ---------------------------------------------------- 腿㉔ 注毒自证（各杀一个方向，合成不触盘）
def _board_live_inputs() -> tuple[set[str], dict[str, frozenset[str]], dict[str, str]]:
    valid = _board_taxonomy_valid_bids()
    attribution = _board_attribution_of_facets(cm.FACETS)
    declared = {cid: getattr(row, "board", "") for cid, row in cm.FACETS.items()}
    assert _board_leg_problems(declared, valid, attribution) == [], (
        "真数据腿㉔已红，注毒无从自证")
    return valid, attribution, declared


def test_poison_board_illegal_code_is_red() -> None:
    """注毒㉔-1（正向·板块码不存在）：给某枚 board 填一个板块树里根本没有的码 ⇒ 正向必红。

    对应任务注毒①「在册枚 board 改成指不存在的板块 ⇒ 新腿红」的合成形态（同一把尺 `_board_leg_problems`）。
    """
    valid, attribution, declared = _board_live_inputs()
    victim = min(declared)
    fake = "B99-ghost-board"
    assert fake not in valid, "注毒样本失效：该码竟在板块集"
    poisoned = dict(declared)
    poisoned[victim] = fake
    problems = _board_leg_problems(poisoned, valid, attribution)
    assert any(victim in p and "[BOARD-ILLEGAL]" in p for p in problems), (
        f"填一个不存在的板块码未被抓到＝正向无牙：{problems}")


def test_poison_board_real_but_unbacked_is_red() -> None:
    """注毒㉔-2（反向·真码但归属不符）：把某枚 board 填成"板块树里存在、却不是该能力归属"的真 bid ⇒ 反向必红。

    对应任务注毒②「把某枚 board 改成真板块但与板块树认领路径不一致 ⇒ 反向腿红」。
    对照段同证"填对归属就不红"（防本腿退化成"只要非空就拦"）。
    """
    valid, attribution, declared = _board_live_inputs()
    victims = sorted(cid for cid, bids in attribution.items() if bids)
    assert victims, "注毒样本失效：无一枚能力被板块树归属"
    victim = victims[0]
    backed = attribution[victim]
    wrong = sorted(valid - backed)
    assert wrong, "注毒样本失效：无「真板块但非本能力归属」可填"
    poisoned = dict(declared)
    poisoned[victim] = wrong[0]
    problems = _board_leg_problems(poisoned, valid, attribution)
    assert any(victim in p and "[BOARD-UNBACKED]" in p for p in problems), (
        f"填成别板块的真码未被抓到＝反向无牙：{problems}")
    correct = dict(declared)
    correct[victim] = min(backed)
    assert _board_leg_problems(correct, valid, attribution) == [], (
        "填对归属板块却仍被拦＝过拦（会逼人缩扫描面绕腿）")


def test_poison_board_leg_is_not_merely_a_nonempty_check() -> None:
    """注毒㉔-3（防"字段非空"空判据）：证明本腿不是"board 必须非空"那种空壳判据。

    对应任务注毒③「把新腿改成'字段非空'空判据 ⇒ 防回潮锁或注毒②必红（证明空判据不被接受）」。
    两相对照：
      (a) 合成一张"全部未声明 board"的假想册面——"非空-only"会把每枚判红（这不是本腿，本腿看真数据绿）；
      (b) "非空-only"对注毒㉔-2（真码但归属不符）**完全无牙**（那枚非空 ⇒ 空判据放行，漂移溜成绿），
          而本腿靠归属背书判据当场抓到——这正是"空判据不被接受"的证据（否则㉔-2 会假绿）。

    (a) 半边必须用**合成图**：本腿落地时真数据恰好 20 枚全空，早期版本直接把"全空"当硬断言，
    于是 S198 按板块树派生把值填上之后当场红——那是把易变数据态焊进判据（AGENTS 规则 10 同族）。
    判据要断的是"空判据对漂移无牙"，与真数据填没填无关。
    """
    valid, attribution, declared = _board_live_inputs()
    synthetic_empty = {cid: "" for cid in cm.FACETS}
    nonempty_only = sorted(cid for cid, board in synthetic_empty.items() if not board)
    assert nonempty_only == sorted(cm.FACETS), "合成对照图不自洽＝本注毒失去意义"
    assert _board_leg_problems(declared, valid, attribution) == [], (
        "真数据本腿应绿（board 已填者须被板块树归属背书；未填者按未声明不报，不得空判据式误报）")
    victim = min(cid for cid, bids in attribution.items() if bids)
    wrong = min(valid - attribution[victim])
    drifted = dict(declared)
    drifted[victim] = wrong
    assert drifted[victim], "注毒样本失效：漂移 board 竟是空（无从对照）"
    # 空判据放行它（证明"字段非空"式判据对漂移无牙）：非空-only 只问真值有无，不问归属。
    assert any(cid == victim for cid in declared) and bool(drifted[victim])
    # 本腿抓到它（证明本腿不是空判据，而是核归属的一致性判据）。
    assert any(victim in p and "[BOARD-UNBACKED]" in p
               for p in _board_leg_problems(drifted, valid, attribution))


# ==========================================================================
# 腿㉕ 七维「维↔值」完整性锁（S242R 补，防第二种空挂＝**有腿、值全空**）
#
# 与本文件既有各腿 + 防回潮锁的分工（各管一条正交轴，谁都不替谁数存在性）：
#   · 防回潮锁 `test_manifest_migration_parity.py::test_every_manifest_dimension_has_a_leg_or_declared_gap`
#     问「这一维**有没有一把执法腿**」——只保证有门碰它，不管门碰的是不是"值有没有填"；
#   · 各内容维腿（②c/②d/④/⑥/⑧/⑨/㉔）问「填进去的**值对不对**」——可解析、镜像等值、行号活性、
#     指针有效、票根在、投影双向等值、板块合法且被归属……
#     ⚠ 但它们全都**容忍空值**：board 空→腿㉔跳过；callsites 空→除非未落零值名册否则腿⑧不管；
#     tags 空→腿⑥只盯 native-* 票根、根本不索要非空。于是"这一维有腿、却被集体留空"没人红。
#   · **本腿**问的正是这条空档：「被执法的每一枚内容维，是否**要么有真值、要么把'无'显式点名**」。
#     逐枚核、给 deficit 计数设只降上限（现算 0＝每一格都是"肯定陈述"），
#     并核执法面本身（DIMENSION_TO_LEG 若长出一枚新内容维而本账无其尺身份 ⇒ 红，堵"新维只挂个腿"）。
#
# 简报的七维（id／执行体真身路径＋行号／唯一直呼点／触发词／配置键／多维标签／板块）在此落两件事：
#   (1) 逐维**尺身份**＝`DIMENSION_VALUE_RULES`（每枚一行的"怎样才算填了"定义，见下）；
#   (2) **地板**＝`VALUE_COMPLETENESS_DEFICIT_CEILING`（未点名空位总数，只准降；现算 0）。
# 执法集**不抄清单**：哪些维"在册且已执法"由防回潮锁的 `DIMENSION_TO_LEG` 现算（懒 import 那个门件、
# 读它的账），本腿只声明"其中哪几枚按内容值口径逐枚执法、哪几枚是结构维须豁免"，两者差集必须归零。
# ==========================================================================

#: 简报点名的七枚内容维（＝八枚字段：执行体拆 ref/line 两列）逐枚的「怎样才算填了」尺身份。
#: 每一枚的判据都写成"要么有真值、要么把'无'显式点名"——缺位靠既有/新增名册（IMPL_REF/
#: DIRECT_CALLSITES/CONFIG_KEYS/TAGS/BOARD 各零值名册）或结构不适用（触发词无命令入口）来点名，
#: "忘了填"与"确实无"从此分得开。⚠ 只数"字段在不在／腿在不在"＝假锁，本表刻意逐枚给真值谓词。
DIMENSION_VALUE_RULES: dict[str, str] = {
    "capability_id": "行有非空 capability_id（本册字典键即身份）",
    "implementation_ref": "implementation_ref 非空，或 cid∈IMPL_REF_UNDECLARED_ROSTER（显式判无执行体）",
    "implementation_line": "有 ref ⇒ 行号>0；无 ref ⇒ cid∈IMPL_REF_UNDECLARED_ROSTER（无锚可点）",
    "direct_callsites": "直呼点非空，或 cid∈DIRECT_CALLSITES_ZERO_ROSTER（现算零处已点名）",
    "config_keys": "配置键非空，或 cid∈CONFIG_KEYS_ZERO_ROSTER（不读键已点名）",
    "trigger_source": "trigger_source 非空，或 该枚无命令类入口形（结构不适用，与腿④同口径）",
    "tags": "tags 非空，或 cid∈TAGS_ZERO_ROSTER（不涉任何内容形态已点名）",
    "board": "board 非空，或 cid∈BOARD_ZERO_ROSTER（板块未归属已点名）",
}

#: 被执法、但语义上"没有逐枚真值可填"的两枚**结构维**——`entry_kinds` 是自由声明（子提供者
#: search.web 即合法空）、`arms` 是入口活性件的投影（纯 passive/control_plane 合法无臂）。
#: 拿"值完整性地板"卡它们会把合法留空误判成缺位、反逼人缩面绕腿，故显式豁免。
#: 豁免不是空子：每枚豁免维都必须仍在 `DIMENSION_TO_LEG` 里（否则是幽灵豁免），
#: 且不得同时出现在值规则里（否则自相矛盾），两向都由 `value_coverage_violations` 反查。
STRUCTURAL_VALUE_EXEMPT_DIMS: frozenset[str] = frozenset({"entry_kinds", "arms"})

#: 命令类入口形（与腿④的 `commandish` 集逐字同源、不另立判据）：只有真从命令面进来的能力
#: 才**必须**有触发词指针；否则触发词留空是结构不适用、算"肯定的无"。
_COMMANDISH_ENTRY_KINDS: frozenset[cm.EntryKind] = frozenset(
    {cm.EntryKind.COMMAND, cm.EntryKind.ALIAS, cm.EntryKind.NATURAL_LANGUAGE})

_PARITY_MODULE = "test_manifest_migration_parity"


def _is_value_filled(dim: str, cid: str, row: cm.CapabilityFacets) -> bool:
    """逐枚逐维判定"这一格是不是肯定陈述"（有真值，或把'无'显式点名/结构不适用）。

    ⚠ fail-closed：`dim` 有尺身份却没有本函数的分支 ⇒ 抛（新维混进 DIMENSION_VALUE_RULES
    却没写填法，绝不被静默读成"已填"）。各分支只读 cm 上的既有名册/枚举，不复制第二份判据。
    """
    if dim == "capability_id":
        return bool(row.capability_id)
    if dim == "implementation_ref":
        return bool(row.implementation_ref) or cid in cm.IMPL_REF_UNDECLARED_ROSTER
    if dim == "implementation_line":
        if row.implementation_ref:
            return int(row.implementation_line) > 0
        return cid in cm.IMPL_REF_UNDECLARED_ROSTER
    if dim == "direct_callsites":
        return bool(row.direct_callsites) or cid in cm.DIRECT_CALLSITES_ZERO_ROSTER
    if dim == "config_keys":
        return bool(row.config_keys) or cid in cm.CONFIG_KEYS_ZERO_ROSTER
    if dim == "trigger_source":
        if row.trigger_source:
            return True
        return not (_COMMANDISH_ENTRY_KINDS & set(row.entry_kinds))
    if dim == "tags":
        return bool(row.tags) or cid in cm.TAGS_ZERO_ROSTER
    if dim == "board":
        return bool(row.board) or cid in cm.BOARD_ZERO_ROSTER
    raise AssertionError(f"维 {dim!r} 有尺身份却无填法分支（fail-closed，别默默当已填）")


def dimension_value_deficits(
    facets: Mapping[str, cm.CapabilityFacets],
    rules: Mapping[str, str],
) -> list[str]:
    """纯谓词：逐维逐枚数出"既无真值、又未把'无'点名"的空位（可喂合成面直接注毒打靶）。"""
    return [
        f"{dim}:{cid}"
        for dim in sorted(rules)
        for cid, row in sorted(facets.items())
        if not _is_value_filled(dim, cid, row)
    ]


def measure_value_completeness_deficit() -> int:
    """活账现算尺（零参，供棘轮执法口按名取数）：读真册逐维逐枚数未点名空位。"""
    return len(dimension_value_deficits(dict(cm.FACETS), DIMENSION_VALUE_RULES))


def value_coverage_violations(
    enforced: set[str],
    policed: set[str],
    structural_exempt: set[str],
) -> list[str]:
    """逐维核「执法面 ↔ 值账面」四本互不重叠的账（分账才证得清每一半牙；注毒直接打靶）。

      · `[VALUE-DIM-UNCOVERED]` 已执法内容维既无值规则、又未声明为结构豁免 ⇒ 红
        （简报注毒②「新维不加锁」的正解：新维只挂个腿就想混过去，这里必红）；
      · `[VALUE-DIM-GHOST]` 值规则里有、但该维已不在 DIMENSION_TO_LEG ⇒ 红（执法撤了账没跟）；
      · `[VALUE-EXEMPT-GHOST]` 豁免了一枚压根没被执法的维 ⇒ 红（豁免不是塞私货的口子）；
      · `[VALUE-DOUBLE-CLAIM]` 一枚维既有值规则又自称结构豁免 ⇒ 红（自相矛盾）。
    """
    v: list[str] = []
    for d in sorted(enforced - policed - structural_exempt):
        v.append(f"[VALUE-DIM-UNCOVERED] 已执法内容维 {d!r} 无「值完整性」尺身份（有腿≠有值）")
    for d in sorted(policed - enforced):
        v.append(f"[VALUE-DIM-GHOST] 维 {d!r} 有值规则却不在 DIMENSION_TO_LEG（执法撤了本账没跟）")
    for d in sorted(structural_exempt - enforced):
        v.append(f"[VALUE-EXEMPT-GHOST] 豁免 {d!r} 但该维根本没被执法（幽灵豁免）")
    for d in sorted(policed & structural_exempt):
        v.append(f"[VALUE-DOUBLE-CLAIM] 维 {d!r} 既有值规则又自称结构豁免（自相矛盾）")
    return v


def test_leg25_dimension_value_completeness_has_a_floor() -> None:
    """㉕ 维↔值完整性：被执法的每一枚内容维要么逐格有真值、要么显式点名缺位；未点名空位 ≤ 上限 0。

    真值不落成本门里的字面量清单：执法面从防回潮锁的 `DIMENSION_TO_LEG` 现算，值账面是本腿的
    `DIMENSION_VALUE_RULES`，两者差集归零由 `value_coverage_violations` 双向核。地板账经
    `_ratchet_check`（ceiling，只准降）比现算，`detail` 逐枚点名 deficit 落在哪一维哪一枚。
    """
    live_deficits = dimension_value_deficits(dict(cm.FACETS), DIMENSION_VALUE_RULES)
    enforced = set(_load_liveness(_PARITY_MODULE).DIMENSION_TO_LEG)
    problems = value_coverage_violations(
        enforced, set(DIMENSION_VALUE_RULES), set(STRUCTURAL_VALUE_EXEMPT_DIMS))
    assert not problems, "维↔值执法覆盖账与 DIMENSION_TO_LEG 不符（逐枚点名见明细）：" + "；".join(problems)
    # 反真空（三向）：值账非空、执法面真在本账上落 ≥7 枚内容维、且本册不是空册——
    # 掏空 DIMENSION_TO_LEG 会被 GHOST 抓、掏空 DIMENSION_VALUE_RULES 被上面 assert 抓、
    # 只留一枚维会让本锁退化成"数存在性"，故显式钉覆盖量下限。
    assert DIMENSION_VALUE_RULES, "值规则表为空＝本腿空跑"
    covered = enforced & set(DIMENSION_VALUE_RULES)
    assert len(covered) >= 7, (
        f"被本锁逐维执法的内容维仅 {len(covered)} 枚（简报点名七维）＝覆盖被缩、退化成存在性计数：{sorted(covered)}")
    assert cm.FACETS, "本册为空册，值完整性无从谈起"
    _ratchet_check(
        name="VALUE_COMPLETENESS_DEFICIT_CEILING",
        direction=RATCHET_DIRECTIONS["VALUE_COMPLETENESS_DEFICIT_CEILING"],
        baseline=VALUE_COMPLETENESS_DEFICIT_CEILING,
        measured=measure_value_completeness_deficit(),
        detail="、".join(sorted(live_deficits)),
    )


# ---------------------------------------------------- 腿㉕ 注毒自证（各杀一手，合成不触盘）
def test_poison_value_empty_board_deficit_is_red_yet_leg24_tolerates_it() -> None:
    """注毒㉕-1（简报注毒①「抽掉一枚值⇒红」＋反"假锁"自证）：抹一枚真 board 的值 ⇒ 本锁必红。

    关键在**同一条注毒交给腿㉔判据看**：board 为空被腿㉔【容忍】（它不强制非空），
    于是防回潮锁、腿②c、腿㉔全绿、只有本锁红。这证明本锁查的是"值填没填"这条正交轴，
    而非把"字段在不在／腿在不在"再数一遍——正是"别做成只数存在性的假锁"的可复跑反证。
    """
    assert dimension_value_deficits(dict(cm.FACETS), DIMENSION_VALUE_RULES) == [], (
        "真数据 deficit 非 0，注毒前提塌（先修活账再来注毒，别放宽判据）")
    victims = sorted(cid for cid, row in cm.FACETS.items() if row.board)
    assert victims, "注毒样本失效：无一枚能力有非空 board"
    victim = victims[0]
    tampered = dict(cm.FACETS)
    tampered[victim] = dataclasses.replace(tampered[victim], board="")
    deficits = dimension_value_deficits(tampered, DIMENSION_VALUE_RULES)
    assert f"board:{victim}" in deficits, (
        f"抹掉一枚真 board 未被值锁抓到＝本锁只数存在性、是假锁：{deficits}")
    # 反证：这条注毒在既有 board 判据下应"看起来没事"（腿㉔跳过空 board），才坐实两锁正交。
    valid = _board_taxonomy_valid_bids()
    attribution = _board_attribution_of_facets(tampered)
    tampered_boards = {cid: getattr(row, "board", "") for cid, row in tampered.items()}
    assert _board_leg_problems(tampered_boards, valid, attribution) == [], (
        "腿㉔ 竟也拦空 board＝两锁重叠，本注毒失去区分力（应改判据方向而非放宽本锁）")


def test_poison_new_enforced_dimension_without_value_rule_is_red() -> None:
    """注毒㉕-2（简报注毒②「新维不加锁⇒红」）：执法册长出一枚新内容维而本账无尺身份 ⇒ 必红。

    合成面注毒：把 `DIMENSION_TO_LEG` 现算集外加一枚假维，`value_coverage_violations` 必须以
    `[VALUE-DIM-UNCOVERED]` 点名它（"给新维补了腿、却没人管值填没填"正是防回潮锁漏掉的那半牙）。
    """
    enforced = set(_load_liveness(_PARITY_MODULE).DIMENSION_TO_LEG)
    assert value_coverage_violations(
        enforced, set(DIMENSION_VALUE_RULES), set(STRUCTURAL_VALUE_EXEMPT_DIMS)) == [], (
        "真数据维↔值覆盖账已红，注毒无从自证")
    grown = enforced | {"brand_new_content_dim"}
    v = value_coverage_violations(grown, set(DIMENSION_VALUE_RULES), set(STRUCTURAL_VALUE_EXEMPT_DIMS))
    assert any("[VALUE-DIM-UNCOVERED]" in s and "brand_new_content_dim" in s for s in v), (
        f"新执法维无值规则未被抓到＝新维可只挂个腿就空挂：{v}")
    # 归因唯一：这一发只该触发 UNCOVERED，别顺带把 GHOST/EXEMPT/DOUBLE-CLAIM 也点燃（否则红不可归因）。
    assert not any("[VALUE-DIM-GHOST]" in s for s in v), v
    assert not any("[VALUE-EXEMPT-GHOST]" in s for s in v), v
    assert not any("[VALUE-DOUBLE-CLAIM]" in s for s in v), v


def test_poison_value_ledger_bookkeeping_three_ways_is_red() -> None:
    """注毒㉕-3（账本自身三本牙）：幽灵值规则 / 幽灵豁免 / 双重声明各被对应账点名。"""
    enforced = {"capability_id", "tags", "board"}
    ghost_rule = value_coverage_violations(enforced, enforced | {"phantom_dim"}, set())
    assert any("[VALUE-DIM-GHOST]" in s and "phantom_dim" in s for s in ghost_rule), ghost_rule
    ghost_exempt = value_coverage_violations(enforced, {"capability_id", "tags", "board"}, {"not_enforced_ex"})
    assert any("[VALUE-EXEMPT-GHOST]" in s and "not_enforced_ex" in s for s in ghost_exempt), ghost_exempt
    double = value_coverage_violations(enforced | {"tags"}, {"capability_id", "tags", "board"}, {"tags"})
    assert any("[VALUE-DOUBLE-CLAIM]" in s and "tags" in s for s in double), double


def test_poison_value_fill_predicate_is_fail_closed_on_unknown_dim() -> None:
    """注毒㉕-4（填法 fail-closed）：给 `_is_value_filled` 一个没写分支的维名 ⇒ 必抛，绝不静默当已填。"""
    sample = next(iter(cm.FACETS.values()))
    with pytest.raises(AssertionError, match="无填法分支"):
        _is_value_filled("totally_unknown_dim", "whatever", sample)


# ==========================================================================
# 腿㉖ `serves-image` 标签的「在册声明 ⇔ 执行体真身派生」双向锁
# （S259 补，依用户 2026-09-24T19:39:57Z 裁定 **D3=B**：词表**扩**一枚，给 `bot.randpic` /
#  `bot.subscribe` 挂真标签，欠账仍须 0、一个上限都不许动）
#
# 三条正交轴各归各腿，谁都不替谁数（这是"新标签必须有执法腿"的具体形状）：
#   · 腿⑥  管「声明了 native-* 有没有实测票根」——数据面在 `capability_tag_evidence.TICKETS`，
#     本腿**不越界**、也不碰它的 `TICKETS_FLOOR`；
#   · 腿㉕  管「`tags` 这一格填没填」（值完整性，deficit 上限 0）——摘牌两枚后 deficit 仍 0，
#     因为这两格从此是"有真值的肯定陈述"，不是"从名册里删掉两行"；
#   · **本腿**管「填进去的那枚标签是不是从真身算得出来的」。D3=B 的硬要求是**禁"填了格子没人读"**，
#     而"有人读"有两半：①这格能被现算复证（白贴 ⇒ 红）；②这格不贴会被现算追问（命中不贴 ⇒ 红，
#     豁免必须点名）。两头都钉住，标签才是账，不是装饰。
#
# 派生尺唯一真身＝本文件 `derive_image_serving_sites()`：AST 扫 `plugins/**.py` 的结果契约构造点，
# 收 `CapabilityResult(capability_id=<字面量>, images=<非空载荷>)`。
# `scripts/facets_candidate_dump.py` 经它自己的 `_GATE_ATTRS` 加载**同一把尺**提扩册候选
# （复用不复制＝铁律 6 禁第二真身；扩册机器从此读得到这枚新标签）。
#
# 语义互斥（腿㉖d）：`image`＝"产出图像（AI 绘画）"（枚举注释逐字限定）、
# `serves-image`＝"交付**既有**图像"。两者是**来源**之争（生成 vs 搬运），一枚能力同时声明二者
# 就等于把两个互斥语义揉成一格；派生命中而声明 `image` 者也不进反向账（它交付的是自己生成的）。
# ==========================================================================

_PLUGIN_ROOT = ROOT / "plugins" / "bot_unified_runtime"

#: 结果契约构造器名单（**扫描面**，不是"已知良好清单"）：未来若出现别名构造口，在这里登记，
#: 而不是另起第二把尺。故意保持窄：漏登记的表现是"命中数掉零 ⇒ 本腿失明账当场红"，不是静默放行。
_RESULT_CONTRACT_CALLABLES: frozenset[str] = frozenset({"CapabilityResult"})

#: 能力侧原生标签前缀（与真身册 `capability_manifest.unsupported_native_tags()` 同口径；
#: 本门只用来把 native-* 从"词表不许空枚"那条账里**排除**——它们的成员资格走票根轴，另把尺）。
_NATIVE_TAG_PREFIX = "native-"

#: 内容形态标签的取值口径（逐枚一句话，供人读、也供 `test_leg26e` 反查"每枚都有口径没"）。
#: 这一表**不是**第二真身：它不复述任何数据，只声明"这枚标签凭什么算填了"，判据仍在各腿里。
TAG_VALUE_CRITERIA: dict[str, str] = {
    "vision": "执行体真身调用视觉解码口（VLM/OCR/看图），见 media.vision.* 各行",
    "native-vision": "渠道原生解图 + `capability_tag_evidence` 票根（腿⑥）",
    "native-animation": "渠道原生解动图 + 票根（腿⑥）",
    "native-audio": "渠道原生听音频 + 票根（腿⑥）",
    "native-video": "渠道原生看视频 + 票根（腿⑥）",
    "tts": "执行体产出语音文件（`bot.tts` / media.tts.* / creation.tts.*）",
    "image": "执行体**生成**图像（AI 绘画：`creation.image.generate`）",
    # D3=B 扩枚：口径不写"人说了算"，写"哪把尺现算"——本腿就是它的派生口。
    "serves-image": "执行体把**既有**图像装进结果契约 `images=`（本文件 "
                    "`derive_image_serving_sites()` AST 现算，双向钉＋豁免须点名）",
    "media-read": "执行体读入站媒体段（链接/附件解析面）",
}


def _images_payload_is_nontrivial(value: ast.expr) -> bool:
    """`images=` 载荷是否"真会带图"：只有**字面空列表**判否。

    两个方向都试过才定在这一条：收到"只认字面非空列表"会把订阅推送那种经参数投影的合法形态
    （`images=payload_images`）判死；放到"出现 images= 就算"会让 `images=[]`（显式"本形不带图"）
    蒙进正向账。窄到只否字面空列表，两头都诚实。
    """
    return not (isinstance(value, ast.List) and not value.elts)


def derive_image_serving_sites() -> tuple[dict[str, tuple[str, ...]], list[str], int, int]:
    """现算「哪些 capability_id 在执行体里把**既有图像**装进结果契约」。

    返回 `(hits, blind, parsed_files, total_files)`：
      · `hits`                ＝ capability_id → 证据站点 `文件:行`（元组；供报错点名与豁免诚实腿复核）；
      · `blind`               ＝ 解析失败的件——**非空即尺失明**，"看不见"一律不当"没有"；
      · `parsed_files`/`total_files` ＝ 扫描面自证分母，两数不等＝有人缩了面（缩面不是降账）。

    口径限制照实写：只认 `capability_id=` 的**字符串字面量**。今天所有实现体都按惯例把自己的 id
    写死在契约里；若哪天有人改成变量传入，表现是"那枚声明者派生不出命中 ⇒ 本腿红"，
    逼人来登记第二形态，而不是静默放行。
    """
    total = 0
    parsed = 0
    blind: list[str] = []
    hits: dict[str, list[str]] = {}
    for path in sorted(_PLUGIN_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        total += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            blind.append(f"{path.relative_to(ROOT)}: {type(exc).__name__}")
            continue
        parsed += 1
        rel = str(path.relative_to(ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if callee not in _RESULT_CONTRACT_CALLABLES:
                continue
            cid: str | None = None
            images: ast.expr | None = None
            for keyword in node.keywords:
                if keyword.arg == "capability_id" and isinstance(keyword.value, ast.Constant):
                    cid = str(keyword.value.value)
                elif keyword.arg == "images":
                    images = keyword.value
            if cid is None or images is None or not _images_payload_is_nontrivial(images):
                continue
            hits.setdefault(cid, []).append(f"{rel}:{node.lineno}")
    return ({key: tuple(sorted(value)) for key, value in hits.items()}, blind, parsed, total)


def serves_image_projection_problems(
    declared_tags: Mapping[str, frozenset[str]],
    derived: Mapping[str, tuple[str, ...]],
    roster: frozenset[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """纯谓词（四本账分开红，注毒直接打靶其中一本）。

    入参全是**映射/名册**、不读真册，好让注毒合成面直接喂进来；活账由腿㉖ 自己现算后调用它。
      · ①`claims_without_derivation` 在册声明 `serves-image`，真身派生不出命中 ⇒ **白贴**；
      · ②`hits_without_claim`       真身派生有命中、册里既不声明也不落豁免 ⇒ **默默漏贴**；
        （声明 `image`＝AI 绘画者天然不进这本账：它交付的是自己生成的图，来源语义相反，见腿㉖d）
      · ③`ghost_exemptions`         落在豁免名册却"根本没命中"或"其实已经声明了" ⇒ **幽灵豁免**；
      · ④`both_image_claims`        同一枚同时声明 `image` 与 `serves-image` ⇒ **互斥语义揉一格**。
    """
    claims = {cid for cid, tags in declared_tags.items() if "serves-image" in tags}
    problems: list[list[str]] = [[], [], [], []]
    for cid in sorted(claims):
        if cid not in derived:
            problems[0].append(f"{cid}（声明 serves-image，真身派生零命中）")
    for cid in sorted(set(derived) & set(declared_tags)):
        tags = declared_tags[cid]
        if "serves-image" in tags or "image" in tags:
            continue
        if cid not in roster:
            problems[1].append(f"{cid}（真身在 " + "、".join(derived[cid][:2]) + " 交付图像载荷，册未声明）")
    for cid in sorted(roster):
        if cid not in derived:
            problems[2].append(f"{cid}（挂了豁免名册，真身却派生不出命中）")
        elif cid in claims:
            problems[2].append(f"{cid}（既声明 serves-image 又挂豁免名册＝双重声明）")
    for cid in sorted(declared_tags):
        tags = declared_tags[cid]
        if "image" in tags and "serves-image" in tags:
            problems[3].append(f"{cid}（image 与 serves-image 同贴＝来源语义互斥）")
    return tuple(problems)  # type: ignore[return-value]


def serves_image_exemption_is_borrowed_id_only(
    derived: Mapping[str, tuple[str, ...]],
    roster: frozenset[str],
    impl_file_of: Callable[[str], str],
) -> list[str]:
    """腿㉖f 的反查判据（S271 立、S276 落）：豁免的**理由**必须能被现算咬住。

    这是既有腿 ㉖ 的**推广**、不是第二把尺——它复用 ㉖ 的同一份派生命中（`derived`，由
    `derive_image_serving_sites` 现算）与同一个归属解析（`impl_file_of`＝`_capability_impl_file`），
    不新立任何扫描器或第二真身；它只补 ㉖ 现有四本账**结构上看不见的一维**（命中出自哪个文件），
    故与四本账零重叠、无可合并的重复测量（合并的对象是「两把量同一件事的尺」，此处不存在）。

    `SERVES_IMAGE_UNDECLARED_ROSTER` 的教义是「图来自**别处**的借用 id」（reminder 即此例——它的
    图像载荷全在 notes.py，而 notes 借用了 bot.reminder 的 id）。可现有四本账只把「命中而不声明」当
    豁免凭据、**不看命中出自哪个件**：给 `reminder.py` 塞一处 `images=` 命中，四本账照样全空＝豁免一旦
    挂上就自免疫，连「自家真产图、本该摘豁免改挂标签」都赖得住。本谓词补这一咬合：名册每枚的派生命中
    **不得落在它自己的 `implementation_ref` 文件内**——落在别处＝真是借用 id（豁免正当）；落在自家＝
    本能力自产图（豁免不成立，该摘名册、改挂 `serves-image`）。锚点复用门件既有 `_capability_impl_file`
    解析 `路径#符号` 的路径部分。

    ⚠ 前瞻（写给未来撞见红的人）：本腿以 `implementation_ref` 的文件为「自家」锚点——对 reminder
    （impl_ref 直指 reminder.py）完全有效；对 impl_ref 指向通用缝（如 pipeline.py）、真身在别处的枚，
    锚点会错指，「摘声明塞名册」这一发本腿看不见。该残余与 reminder 同根（id／归属错位＝PX-259-2），
    且 notes→bot.notes 修好后 reminder 那发会变「幽灵豁免」被既有 ③ 账当场打红。本腿封的是**已实证
    的自免疫洞**，不冒充覆盖通用缝枚的重新分类。
    """
    problems: list[str] = []
    for cid in sorted(roster):
        own = impl_file_of(cid)
        if not own:
            continue  # 无 implementation_ref（缺位由别腿管），本腿无从判归属，不重复报
        site_files = {site.split(":")[0].replace("\\", "/") for site in derived.get(cid, ())}
        if own in site_files:
            problems.append(
                f"{cid}（派生命中落在其**自己**的实现件 {own} 内＝本能力自产图，"
                f"不属「借用 id 的豁免」，应摘名册、改挂 serves-image）")
    return problems


def unused_non_native_tag_values(usage: Mapping[str, int]) -> list[str]:
    """词表里**没有任何在册使用者**的非 native-* 标签（D3=B 的"不许空扩枚"那一半牙）。

    native-* 一律排除：它们的成员资格由票根轴决定（今天 `native-vision` 无人声明是**诚实结果**，
    不是空枚——把它算进本账会逼人去贴无票根的声明，正与该轴教义相反）。
    """
    return sorted(
        tag.value for tag in cm.CapabilityTag
        if not tag.value.startswith(_NATIVE_TAG_PREFIX) and not usage.get(tag.value)
    )


_SERVES_IMAGE_CACHE: dict[str, Any] = {}


def _live_serves_image_inputs() -> tuple[dict[str, frozenset[str]], dict[str, tuple[str, ...]],
                                         list[str], int, int]:
    """活账三面现算一次并缓存（扫描面是全树，别每发断言重扫一遍）。"""
    if not _SERVES_IMAGE_CACHE:
        hits, blind, parsed, total = derive_image_serving_sites()
        _SERVES_IMAGE_CACHE["inputs"] = (
            {cid: frozenset(tag.value for tag in row.tags) for cid, row in cm.FACETS.items()},
            hits, blind, parsed, total,
        )
    return _SERVES_IMAGE_CACHE["inputs"]  # type: ignore[return-value]


def test_leg26_serves_image_tag_is_derived_from_implementation() -> None:
    """㉖ `serves-image` 的声明必须等于真身派生集（白贴红、漏贴红、豁免须是真豁免）。

    ⚠ 前瞻（写给未来撞见红的人，别当场把判据改松）：今天在册 20 枚里派生命中恰 3 枚
    （randpic／subscribe／reminder），是因为**只有这三枚的执行体把图像写进结果契约**。
    今后若某枚"只交付渲染卡"的能力进了本册（`images=[{"file": card}]` 那种），本腿会索要一个决定——
    那属**渲染面**、不是"交付既有图像"，正解是落 `SERVES_IMAGE_UNDECLARED_ROSTER` 并写明"仅渲染卡"，
    **不是**给它贴 `serves-image`（贴了就是把卡片账揉进内容形态账，本枚标签的语义当场被稀释）。
    """
    declared, hits, blind, parsed, total = _live_serves_image_inputs()
    assert not blind, "派生尺有解析不出的件（失明不能当零命中）：" + "、".join(blind)
    assert total > 0 and parsed == total, (
        f"扫描面自证不符：应扫 {total} 件、实扫 {parsed} 件＝有人缩了面（缩面不是降账）")
    assert hits, "派生集整张为空＝尺不再认得任何图像交付点（构造器名单被改窄/契约改名），本腿已不可判"
    claims = {cid for cid, tags in declared.items() if "serves-image" in tags}
    assert len(claims & set(cm.FACETS)) >= 2, (
        f"分母上声明 serves-image 的在册枚不足 2＝D3=B 两枚被摘走了却留着枚举枚（空枚由 ㉖c 管，"
        f"这一条管的是『本腿到底有没有真声明在账上』）：{sorted(claims)}")
    undoc, unclaimed, ghosts, both = serves_image_projection_problems(
        declared, hits, cm.SERVES_IMAGE_UNDECLARED_ROSTER)
    assert not undoc, "声明了 serves-image 而真身派生不出图像交付（贴了个没人兑现的格）：" + "；".join(undoc)
    assert not unclaimed, "真身在交付图像载荷而册既未声明也未点名豁免（默默漏贴）：" + "；".join(unclaimed)
    assert not ghosts, "SERVES_IMAGE_UNDECLARED_ROSTER 与实况不符（豁免必须是『命中而未声明』）：" + "；".join(ghosts)
    assert not both, "image 与 serves-image 同贴（生成 vs 既有是两个来源语义）：" + "；".join(both)


def test_leg26f_serves_image_exemption_is_borrowed_id_only() -> None:
    """㉖f 豁免≠免检：名册每枚的图像命中都得在**它自己实现件之外**（借用 id 才叫豁免）。

    与 ㉖/㉖c/㉖e 同族（各管一维、分开红）：本条管「命中出自哪个件」这一维，四本账看不见它。
    今天实况（reminder 的图像载荷只在 notes.py）⇒ 应绿；一旦某枚豁免在自己实现件内产图 ⇒ 红。
    """
    _declared, hits, _blind, _parsed, _total = _live_serves_image_inputs()
    problems = serves_image_exemption_is_borrowed_id_only(
        hits, cm.SERVES_IMAGE_UNDECLARED_ROSTER,
        lambda cid: _capability_impl_file(cm.implementation_ref_for(cid)))
    assert not problems, (
        "SERVES_IMAGE_UNDECLARED_ROSTER 里的枚在自己的实现件内产图＝豁免不成立：" + "；".join(problems))


def test_leg26c_tag_vocabulary_has_no_unused_member() -> None:
    """㉖c 不许空扩枚：词表里每枚**非 native-*** 标签都得有 ≥1 枚在册使用者。

    D3=B 的原话是"新标签必须有执法腿与消费方"。执法腿＝㉖；这一条是它的对偶——
    防止有人把词表当许愿池，先扩一枚"以后再说"，格子在册却永远没人贴。
    native-* 显式排除（票根轴，见 `unused_non_native_tag_values` 的理由段）。
    """
    declared, _hits, _blind, _parsed, _total = _live_serves_image_inputs()
    usage = {tag: 0 for tag in (item.value for item in cm.CapabilityTag)}
    for tags in declared.values():
        for tag in tags:
            usage[tag] += 1
    idle = unused_non_native_tag_values(usage)
    assert not idle, f"内容形态标签空枚（扩了没人贴）：{idle}；使用者逐枚现算＝{usage}"


def test_leg26e_every_tag_value_has_a_written_criteria() -> None:
    """㉖e 枚枚标签都写得出"凭什么算填了"（取值口径不许只住人脑或只住席位报告）。

    与本腿分工：㉖ 管 `serves-image` 这一枚能不能**现算复证**；本条管**整张词表**每一枚都有
    一句可核对的口径（口径指向各腿真身，不复述数据，故不是第二真身）。新扩枚不写口径 ⇒ 红。
    """
    vocabulary = {tag.value for tag in cm.CapabilityTag}
    assert set(TAG_VALUE_CRITERIA) == vocabulary, (
        f"取值口径表与词表不逐枚相等（扩枚没写口径 / 口径留着退役枚）："
        f"缺 {sorted(vocabulary - set(TAG_VALUE_CRITERIA))}、多 {sorted(set(TAG_VALUE_CRITERIA) - vocabulary)}")
    assert all(str(text).strip() for text in TAG_VALUE_CRITERIA.values()), "有标签口径写成空串"


# ---------------------------------------------------- 腿㉖ 注毒自证（合成面，不触盘）
def test_poison_serves_image_claim_without_derivation_is_red() -> None:
    """注毒㉖-1（白贴）：给一枚真身不带图的能力贴上 `serves-image` ⇒ ①账必红，且只红①。"""
    declared, hits, _blind, _parsed, _total = _live_serves_image_inputs()
    victim = min(cid for cid, tags in declared.items() if "serves-image" not in tags and cid not in hits)
    tampered = {cid: set(tags) for cid, tags in declared.items()}
    tampered[victim] = set(tampered[victim]) | {"serves-image"}
    undoc, unclaimed, ghosts, both = serves_image_projection_problems(
        {key: frozenset(value) for key, value in tampered.items()}, hits, cm.SERVES_IMAGE_UNDECLARED_ROSTER)
    assert any(victim in row for row in undoc), f"白贴未被抓到＝正向判据是空跑：{undoc}"
    assert not unclaimed and not ghosts and not both, f"注毒越界点燃他账（不可归因）：{[unclaimed, ghosts, both]}"


def test_poison_serves_image_hit_without_claim_is_red() -> None:
    """注毒㉖-2（默默漏贴）：把一名在册豁免从名册里悄悄抽走 ⇒ ②账当场点名它。

    这一发正是"名册真有用"的反证：`SERVES_IMAGE_UNDECLARED_ROSTER` 里那枚（现算＝真身派生命中、
    却按裁定不挂标签）一旦被删，账面既没声明、也没点名 ⇒ 必须红；挂回去必须绿。
    注毒样本走"活账里真实存在的那一枚"，不手写 id（手写就成了第二本账）。
    """
    declared, hits, _blind, _parsed, _total = _live_serves_image_inputs()
    victims = [cid for cid in hits if cid in declared and "serves-image" not in declared[cid]
               and "image" not in declared[cid] and cid in cm.SERVES_IMAGE_UNDECLARED_ROSTER]
    assert victims, (
        "注毒前提塌：豁免名册里没有任何『派生命中而未声明』的行——"
        "那本名册就是空挂，②账与③账都无从自证（先修账再来注毒，别放宽判据）")
    victim = min(victims)
    shrunk = frozenset(set(cm.SERVES_IMAGE_UNDECLARED_ROSTER) - {victim})
    _undoc, unclaimed, ghosts, both = serves_image_projection_problems(declared, hits, shrunk)
    assert any(victim in row for row in unclaimed), f"摘掉名册未判红＝反向判据是空跑：{unclaimed}"
    assert not ghosts and not both, f"注毒越界点燃他账：{[ghosts, both]}"
    # 反向自证：把它挂回名册 ⇒ 这本账复绿（证明②咬的是"未点名"，不是"存在命中"本身）。
    _u2, again, _g2, _b2 = serves_image_projection_problems(
        declared, hits, cm.SERVES_IMAGE_UNDECLARED_ROSTER)
    assert not again, f"活账本该绿却红（前提塌）：{again}"


def test_poison_ghost_serves_image_exemption_is_red() -> None:
    """注毒㉖-3（幽灵豁免）：往豁免名册塞一枚真身不带图的人 ⇒ ③账必红。"""
    declared, hits, _blind, _parsed, _total = _live_serves_image_inputs()
    ghost = min(cid for cid in declared if cid not in hits)
    roster = frozenset(set(cm.SERVES_IMAGE_UNDECLARED_ROSTER) | {ghost})
    _undoc, unclaimed, ghosts, both = serves_image_projection_problems(declared, hits, roster)
    assert any(ghost in row for row in ghosts), f"幽灵豁免未被抓到＝名册诚实腿是空壳：{ghosts}"
    assert not unclaimed and not both, f"注毒越界点燃他账：{[unclaimed, both]}"


def test_poison_image_and_serves_image_together_is_red() -> None:
    """注毒㉖-4（互斥语义揉一格）：同贴 `image`＋`serves-image` ⇒ ④账必红。"""
    declared, hits, _blind, _parsed, _total = _live_serves_image_inputs()
    victim = min(cid for cid, tags in declared.items() if "image" in tags)
    tampered = dict(declared)
    tampered[victim] = frozenset(set(tampered[victim]) | {"serves-image"})
    _undoc, _unclaimed, _ghosts, both = serves_image_projection_problems(
        tampered, hits, cm.SERVES_IMAGE_UNDECLARED_ROSTER)
    assert any(victim in row for row in both), f"同贴互斥标签未被抓到：{both}"


def test_poison_new_tag_without_user_is_red() -> None:
    """注毒㉖-5（空扩枚）：把某一枚真标签的"使用者"清零 ⇒ ㉖c 判据必须点名它。

    注毒形状选"摘掉使用者"而不是"往使用表塞一枚假标签"——后者**测不到判据**：
    `unused_non_native_tag_values` 的分母是枚举本身，假标签根本不在枚举里、自然不会被点名
    （本席第一版就写了这一发假毒，跑出来红不起来才发现自己测的是夹具）。
    真要空扩一枚，唯一形态是"枚进枚举、没人贴"，等价于本注毒把某枚真标签的使用数打到 0。
    """
    live = {tag.value: 0 for tag in cm.CapabilityTag}
    for tags in _live_serves_image_inputs()[0].values():
        for tag in tags:
            live[tag] += 1
    assert unused_non_native_tag_values(live) == [], "活账已有空枚，注毒前提塌（先修账再来注毒）"
    for victim in ("serves-image", "image", "tts", "vision", "media-read"):
        assert live[victim] >= 1, f"注毒样本失效：{victim} 今天本就无人使用"
        starved = dict(live)
        starved[victim] = 0
        assert unused_non_native_tag_values(starved) == [victim], (
            f"把 {victim} 的使用者清零未被点名＝『扩了没人贴』这一手无牙")
    # native-* 不许进这本账（票根轴另把尺；今天 native-vision 恰是零使用者，写死这一条防误伤）。
    assert "native-vision" not in unused_non_native_tag_values(
        {tag: 0 for tag in (item.value for item in cm.CapabilityTag)}), (
        "native-* 被拉进空枚账＝会把人逼去贴无票根的声明，与票根轴教义相反")


def test_poison_image_criteria_table_losing_an_entry_is_red() -> None:
    """注毒㉖-6（口径表掉一枚）：从 `TAG_VALUE_CRITERIA` 抽掉任意一枚 ⇒ ㉖e 必红且点名它。"""
    vocabulary = {tag.value for tag in cm.CapabilityTag}
    assert set(TAG_VALUE_CRITERIA) == vocabulary, "活账口径表已不逐枚相等，注毒前提塌"
    victim = min(vocabulary)
    shrunk = dict(TAG_VALUE_CRITERIA)
    shrunk.pop(victim)
    assert vocabulary - set(shrunk) == {victim}, "注毒样本失效（抽的不是那一枚）"
    grown = dict(TAG_VALUE_CRITERIA)
    grown["retired-tag"] = "幽灵口径"
    assert set(grown) - vocabulary == {"retired-tag"}, "注毒样本失效（多的那枚没多出来）"


def test_poison_serves_image_exemption_serving_from_own_body_is_red() -> None:
    """注毒㉖-7（自我豁免通道被滥用＝简报要的「搬回自家⇒红、还原⇒复绿」）：
    把一枚豁免的命中「搬回」它自己实现件 ⇒ ㉖f 必红；还原成实况 ⇒ ㉖f 复绿。

    这一发正是简报要的「拿这枚豁免自我豁免别的枚 ⇒ 必红」的最小可机检形态：名册成员资格本身
    **不该**让能力免于「自家产图就该挂标签」这条判据。注毒走合成命中（不碰盘、不改 manifest），
    且顺带证明当前四本账对此是瞎的（自免疫前提坐实＝㉖f 有独立牙，不是复述四本账）。
    """
    declared, hits, _blind, _parsed, _total = _live_serves_image_inputs()
    roster = cm.SERVES_IMAGE_UNDECLARED_ROSTER
    victims = [cid for cid in roster if cm.implementation_ref_for(cid)]
    assert victims, "注毒前提塌：名册里没有任何带 implementation_ref 的枚，㉖f 无从下手"
    victim = min(victims)
    own = _capability_impl_file(cm.implementation_ref_for(victim))
    assert own, f"{victim} 有 implementation_ref 却解析不出文件＝_capability_impl_file 与本腿口径不符"

    def impl_file_of(cid: str) -> str:
        return _capability_impl_file(cm.implementation_ref_for(cid))

    # 自免疫前提坐实：合成命中塞进 victim 自家实现件 ⇒ 现有四本账照样全空（看不见＝㉖f 才有独立价值）。
    poisoned = {cid: tuple(sites) for cid, sites in hits.items()}
    poisoned[victim] = tuple(sorted(set(poisoned.get(victim, ())) | {own + ":1"}))
    undoc, unclaimed, ghosts, both = serves_image_projection_problems(declared, poisoned, roster)
    assert not (undoc + unclaimed + ghosts + both), (
        f"四本账竟咬住了合成塞自家这一发＝『自免疫』前提不成立，㉖f 判定要重估：{undoc + unclaimed + ghosts + both}")

    # ㉖f 有牙（合成搬回自家 ⇒ 点名）。
    problems = serves_image_exemption_is_borrowed_id_only(poisoned, roster, impl_file_of)
    assert any(victim in row for row in problems), f"豁免枚自家产图未被抓到＝㉖f 空跑：{problems}"
    # 反向自证（还原成实况 ⇒ 复绿）：证明它咬的是「命中出自哪个件」，不是「存在豁免枚」本身。
    clean = serves_image_exemption_is_borrowed_id_only(hits, roster, impl_file_of)
    assert not clean, f"活账本该绿却红（前提塌）：{clean}"


def test_poison_new_serves_image_exemption_is_caught_by_ghost_leg_not_26f() -> None:
    """注毒㉖-8（简报要的「再造一枚新豁免塞进名册 ⇒ 既有反自豁免腿必红」）：
    试图靠「新挂一枚豁免」蒙混 ⇒ 既有 ③ 幽灵账当场红；同时 ㉖f 对它保持静默 ⇒ 二者正交、非重叠尺。

    这条不是重复 ㉖-3（那发只验 ③）：它的**独有增量**是把 ㉖f 与 ③ 摆在同一枚新豁免上对照——
    ③ 咬「命中都不存在的空豁免」，㉖f 咬「命中落在自家文件的假豁免」，一命中文本无 ⇒ ㉖f 不响、
    ③ 响。这正是「㉖f 是 ㉖ 的推广、不是第二把尺、与四本账零重叠」这一判定的机器可检证据。
    """
    declared, hits, _blind, _parsed, _total = _live_serves_image_inputs()
    ghost = min(cid for cid in declared if cid not in hits)  # 真身不带任何图像派生命中的人
    assert cm.implementation_ref_for(ghost), "注毒前提塌：选中的新豁免没有 implementation_ref，无法谈归属"
    minted = frozenset(set(cm.SERVES_IMAGE_UNDECLARED_ROSTER) | {ghost})

    def impl_file_of(cid: str) -> str:
        return _capability_impl_file(cm.implementation_ref_for(cid))

    # 既有反自豁免腿（③）必红：新塞一枚真身无命中的豁免＝幽灵豁免。
    _undoc, _unclaimed, ghosts, _both = serves_image_projection_problems(declared, hits, minted)
    assert any(ghost in row for row in ghosts), f"新塞的空豁免未被 ③ 抓＝反自豁免腿无牙：{ghosts}"
    # ㉖f 对它静默（正交）：它没有任何命中，谈不上「命中落在自家」，故不该由 ㉖f 报、也无重叠双计。
    f_problems = serves_image_exemption_is_borrowed_id_only(hits, minted, impl_file_of)
    assert not any(ghost in row for row in f_problems), (
        f"㉖f 对无命中的新豁免也报＝与 ③ 重叠（该合并而非并存）：{f_problems}")


# ==========================================================================
# 腿㉗ —— 「已通电 ≠ 已生效」对账（S290C 补，用户 2026-09-25 裁定 OI-071＝做）
#
# 一句话：把「账面通电、按代码缺省不生效」这句**一直靠人手写在注释里**的话（先例＝
# `tests/test_descriptor_wiredness_ledger.py:98` 与 `:106` 的「控制面缺省关 ⇒ 账面通电、现网零流量」，
# 以及 `tests/test_tts_creation_gate_reality.py` 一枚一手写的"缺口锁"），补成机器判据。
# 今天没有任何一腿在「声明通电」与「生效前置缺省」之间对账 ⇒ 谁都能把这枚写成"已可用"。
#
# 三样料**全是现成件**（本腿不新建尺、不新建真身、不新建名册机制）：
#   通电侧＝`cm.FACETS[...].arms`（腿㉓ 双向钉入口活性件）与普查 `state`（腿③/③b，经本门 `_state_of()`）。
#   生效侧＝`config.py` 的 `Config.model_fields[key].default`（DISPATCH-PROTOCOL 第八节补一合法口①）。
#   连接件＝`cm.FACETS[...].config_keys`（腿⑨/⑨b 的唯一真身：这枚能力读哪几枚 Config 字段）。
# 名册只是**披露账**（与 `tests/test_outbound_gate_opening_preconditions.py` 的"开闸前置欠账名册"同族），
# 判据源永远是现算：新枚通电而前置缺省关 ⇒ `[PD-MISSING]` 红；把前置真改成缺省开 ⇒ `[PD-STALE]` 红，
# 逼"改了回头"。两个方向都只准更严。
#
# ⚠ 本腿的天花板（不得越线叙述）：它只看得到**申报面**。`Config` 里「布尔且缺省 False」的字段今天
# 现算 70 枚，其中 64 枚不被任何在册行申报 ⇒ 装配级前置（`bot_control_plane_enabled`、
# `bot_tts_auto_reply_enabled` 等）落在门外，那部分仍只有散文在记账。把前置补进 `config_keys`
# 是治它的唯一诚实路子，但腿⑨ 要求册与编排侧描述符**双向等值** ⇒ 那是改生产件的一批活，
# 已作为候选 C3 报主代理裁（见 SEAT-S290C §4），本腿不假装它已覆盖。
# ==========================================================================

#: 通电尺身份（两个名字**只是标签**，判据各住腿㉓／腿③b，本腿不重算）。
POWER_SCALE_ARMED = "armed"
POWER_SCALE_CENSUS = "census-wired"


def is_default_off_switch(key: str) -> bool:
    """「按代码缺省即关」：该 `Config` 字段的默认值是布尔 `False`（**零读 `.env`**）。

    取值口径＝`Config.model_fields[key].default is False`——不用 `hasattr`、不猜键名后缀
    （"以 `_enabled` 结尾"那种名字尺会把 `bot_media_archive_summary_enabled`（缺省 True）与
    任何非开关的假 `*_enabled` 都判错；本尺只认**值**，于是 `bot_tts_voice_hook_enabled=False`
    命中、`bot_media_archive_summary_enabled=True` 不命中，都由 `config.py` 自己说了算）。
    幽灵键（`Config` 无此字段）在这里返回 `False`＝"不判它为关"——那是腿⑨b 的账，本腿不越界代罚。
    """
    from plugins.bot_unified_runtime.config import Config

    field = Config.model_fields.get(key)
    return field is not None and field.default is False


def power_scales_for(capability_id: str) -> tuple[str, ...]:
    """这枚能力被哪几把**现成**通电尺命中（逐枚记身份，避免"通电"变成一锅糊话）。"""
    scales: list[str] = []
    if cm.arms_for(capability_id):
        scales.append(POWER_SCALE_ARMED)
    if _state_of(capability_id) == "wired":
        scales.append(POWER_SCALE_CENSUS)
    return tuple(scales)


def live_effect_preconditions() -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """现算账：`cid -> (命中的通电尺, 申报到的缺省即关关键)`，只收"通电 ∧ 有缺省关键"的枚。

    分母＝本册全部申报行（腿⑨ 同源），**不挑子集**：缩面不是降账，是把尺子锯短
    （由 `test_leg27_scan_denominator_covers_every_declared_row` 逐名核）。
    """
    hits: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    for cid, row in cm.FACETS.items():
        scales = power_scales_for(cid)
        if not scales:
            continue
        off_keys = tuple(sorted(k for k in row.config_keys if is_default_off_switch(k)))
        if off_keys:
            hits[cid] = (scales, off_keys)
    return hits


def effect_precondition_problems(
    live: dict[str, tuple[tuple[str, ...], tuple[str, ...]]],
    disclosed: Mapping[str, tuple[tuple[str, ...], tuple[str, ...], str]],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """纯谓词（可喂合成数据、不触盘）：四类违规各自可单独归因。返回 `(missing, stale, shape, vapor)`。

    - `[PD-MISSING]` 现算通电且前置缺省关，却没在披露名册里点名 ⇒ 就是"把已通电叙述成已可用"那一格；
    - `[PD-STALE]`   名册里有、现算已不成立（前置改开了 / 这枚不再通电）⇒ 披露过期须摘行；
    - `[PD-SHAPE]`   点名了但**尺身份或键集合**与现算不等 ⇒ 披露内容与实况不符（含"少列一枚键"）；
    - `[PD-VAPORNOTE]` 披露语为空、或不含它自己列出的任何一枚键 ⇒ 拿一句空话糊过名册。
    """
    missing = [f"[PD-MISSING] {cid} 现算命中通电尺 {live[cid][0]} 与缺省关键 {live[cid][1]}，"
               f"却未点名披露" for cid in sorted(set(live) - set(disclosed))]
    stale = [f"[PD-STALE] {cid} 披露名册有此行、现算已不成立（不再通电，或所列前置已非缺省 False）"
             for cid in sorted(set(disclosed) - set(live))]
    shape: list[str] = []
    vapor: list[str] = []
    for cid in sorted(set(live) & set(disclosed)):
        live_scales, live_keys = live[cid]
        declared_scales, declared_keys, note = disclosed[cid]
        if tuple(sorted(declared_scales)) != tuple(sorted(live_scales)) or tuple(
            sorted(declared_keys)
        ) != tuple(sorted(live_keys)):
            shape.append(f"[PD-SHAPE] {cid} 现算尺/键={live_scales}/{live_keys} "
                         f"vs 披露={tuple(sorted(declared_scales))}/{tuple(sorted(declared_keys))}")
        if not note.strip() or not any(key in note for key in live_keys):
            vapor.append(f"[PD-VAPORNOTE] {cid} 披露语未点名它自己列出的缺省关键 {live_keys}：{note!r}")
    return missing, stale, shape, vapor


#: 披露名册：`cid -> (命中的通电尺, 缺省即关的关键, 人话披露)`。
#: **只准跟随现算**（新增一行须先有现算命中、并写清为什么按缺省不生效；摘一行须先真把前置改成缺省开）。
#: 措辞纪律：每行只说"按 `config.py` 缺省"，**不得**说"现网一定关着"——那要读 `.env`/运行时覆盖，
#: 不属本腿的合法口（DISPATCH-PROTOCOL 第八节补一）。
#: 现算 4 枚（2026-09-25 S290C，尺＝本件 `live_effect_preconditions()`；复跑见模块 docstring「复跑」段）。
EFFECT_PRECONDITION_DISCLOSURES: dict[
    str, tuple[tuple[str, ...], tuple[str, ...], str]
] = {
    # 唯一调用点在控制面路由件里；控制面自身的门 `bot_control_plane_enabled`（config.py 缺省 False）
    # **不在**本枚申报的 config_keys 里 ⇒ 那是 §4 候选 C3 的申报面欠账，本行只能披露看得见的那一枚。
    "creation.tts.synthesize": (
        (POWER_SCALE_CENSUS,),
        ("bot_tts_enabled",),
        ("账面通电（普查 state=wired，调用点在控制面）；但 engine provider 读的唯一开关 "
         "bot_tts_enabled 在 config.py 缺省 False ⇒ 按代码缺省这一路今天不可达，"
         "不得叙述为「语音已可被 API 调用」。另注：控制面自身的前置 bot_control_plane_enabled "
         "未进本枚申报键面＝本腿门外（SEAT-S290C §4 C3）。"),
    ),
    "media.tts.autodub": (
        (POWER_SCALE_ARMED, POWER_SCALE_CENSUS),
        ("bot_tts_enabled",),
        ("主动投递臂已通电；合成腿自身读 bot_tts_enabled，该字段 config.py 缺省 False "
         "⇒ 按代码缺省不出声，不得叙述为「自动配音已生效」。"),
    ),
    # 简报点名的活例：在册 ∧ 已通电 ∧ 按代码缺省不可达，三件事同时为真而今天无一门要求说出来。
    "media.tts.autodub_transform": (
        (POWER_SCALE_ARMED, POWER_SCALE_CENSUS),
        ("bot_tts_voice_hook_enabled",),
        ("结果变换形（配音第二条腿）已并入中央派发谱、hook 在 voice_enricher 里真调它；"
         "但调它的装配门 bot_tts_voice_hook_enabled 在 config.py 缺省 False "
         "⇒ 按代码缺省这一路今天不可达（现网此刻的开/关不属本腿判据——那要读 `.env`，"
         "DISPATCH-PROTOCOL 第八节补一禁读），禁据「已通电」叙述为「已可用」。另注："
         "bot_tts_auto_reply_enabled 未在本枚 config_keys 申报＝同属 C3 的失明面。"),
    ),
    "search.web": (
        (POWER_SCALE_CENSUS,),
        ("bot_web_search_enabled",),
        ("接地检索有生产字面调用点（state=wired）；bot_web_search_enabled 在 config.py 缺省 False "
         "⇒ 按代码缺省不检索，"
         "不得叙述为「已在联网接地」（缺 key 时的免 key 兜底链另键、同样缺省关）。"),
    ),
}


def test_leg27_energized_rows_must_disclose_default_off_preconditions() -> None:
    """㉗ 主判据：凡"在册 ∧ 通电 ∧ 申报键里有缺省即关的前置"，必须逐枚点名披露，四类违规皆空。

    真数据下先自证非空跑（`live` 与 `disclosed` 都不许为空——空名册配空现算会把本腿弄成永久真空绿）。
    """
    live = live_effect_preconditions()
    assert live, (
        "㉗ 现算命中为空＝量具瞎了或名册被清空换绿（本波实测应有若干枚，"
        "见 SEAT-S290C §3）；先查 is_default_off_switch / power_scales_for，别当"
        "\"已全部改开\"")
    assert EFFECT_PRECONDITION_DISCLOSURES, "㉗ 披露名册为空＝把尺子锯短，不是降账"
    missing, stale, shape, vapor = effect_precondition_problems(
        live, EFFECT_PRECONDITION_DISCLOSURES)
    assert not missing, "已通电却未披露缺省即关的前置（＝可被叙述成\"已可用\"）：\n" + "\n".join(missing)
    assert not stale, "披露过期（前置已改开或已不通电，名册没回头）：\n" + "\n".join(stale)
    assert not shape, "披露内容与现算不符：\n" + "\n".join(shape)
    assert not vapor, "披露语未点名自己的键（空话糊名册）：\n" + "\n".join(vapor)


def test_leg27_scan_denominator_covers_every_declared_row() -> None:
    """㉗ 分母自证：本腿扫的是**本册全部申报行**，且"未命中"的每一枚都能归因到两条理由之一。

    只写"名册与现算相等"是不够的——那拦不住"把待扫集合缩成手挑子集"。本锁逐枚重算：
    不在 `live` 里的在册行，必须**要么两把通电尺都没命中、要么申报键里没有缺省即关的**；
    出现第三种情形＝循环体漏扫（尺子被锯短），当场点名。
    """
    live = live_effect_preconditions()
    assert live and EFFECT_PRECONDITION_DISCLOSURES, "㉗ 扫描面或名册为空＝本腿已被弄瞎"
    unexplained: list[str] = []
    for cid, row in cm.FACETS.items():
        if cid in live:
            continue
        if power_scales_for(cid) and any(is_default_off_switch(k) for k in row.config_keys):
            unexplained.append(f"{cid}：尺命中={power_scales_for(cid)} 缺省关键="
                               f"{[k for k in row.config_keys if is_default_off_switch(k)]}")
    assert not unexplained, "本册行未进现算账却给不出理由＝㉗ 循环体漏扫：\n" + "\n".join(unexplained)
    hit_rows = {cid for cid in live}
    assert all(cid in cm.FACETS for cid in hit_rows), "现算命中里出现册外 id＝判据源不是本册"


def test_leg27_power_scales_are_the_two_existing_rulers() -> None:
    """㉗ 尺身份自证：通电侧只准用**已存在**的两把尺，且两把各判一件事、不许并成一锅。

    `armed` 是 `arms` 非空的枚集合（腿㉓）；`census` 是普查 state==wired 的枚集合（腿③/③b）。
    两集合**互不包含**（本波现算：`search.web` 与 `creation.tts.synthesize` 只有 census、
    `media.tts.autodub*` 两把都有）——写死"两把尺"而不是"一把并集尺"，正是为了让
    "只声明了臂却没生产调用点"与"有调用点却没有臂形"两类过度声称各被点名一次。
    """
    armed = {cid for cid in cm.FACETS if cm.arms_for(cid)}
    census_wired = {cid for cid in cm.FACETS if _state_of(cid) == "wired"}
    for cid in cm.FACETS:
        assert set(power_scales_for(cid)) == {
            scale for scale, group in ((POWER_SCALE_ARMED, armed), (POWER_SCALE_CENSUS, census_wired))
            if cid in group
        }, f"{cid} 的通电尺身份与两把现成尺不一致（本腿自造第三把尺了）"
    assert armed - census_wired or census_wired - armed, (
        "两把尺命中集合完全相同＝一把已退化，本测试该改成一把并删掉另一把的账，别两把都留着骗人")


# ------------------------------------- ㉗ 注毒自证（合成数据，不触盘、不改别人的写面）
def test_poison_effect_precondition_missing_disclosure_is_red() -> None:
    """注毒㉗-1：把一枚**真命中**的披露从名册里抹掉 ⇒ 必落 `[PD-MISSING]`，且归因唯一。

    这正是本 mandate 要堵的那一句：接线在册、臂也通电、前置却缺省关，而没人要求说出来。
    """
    live = live_effect_preconditions()
    assert live, "注毒前提塌：现算零命中，无从抹披露"
    victim = min(live)
    poisoned = {cid: row for cid, row in EFFECT_PRECONDITION_DISCLOSURES.items() if cid != victim}
    missing, stale, shape, vapor = effect_precondition_problems(live, poisoned)
    assert any(victim in row and "[PD-MISSING]" in row for row in missing), (
        f"抹掉披露却没被抓＝㉗ 空跑：{missing}")
    assert not stale and not shape and not vapor, (
        f"归因不唯一（一发毒顺带触发他类，判据重叠＝该合并）：{stale}{shape}{vapor}")
    # 还原成实况 ⇒ 四类复绿（证明它咬的是"有没有点名"，不是"名册存在与否"）。
    clean = effect_precondition_problems(live, EFFECT_PRECONDITION_DISCLOSURES)
    assert not any(clean), f"活账本该绿却红：{clean}"


def test_poison_effect_precondition_stale_or_wrong_keys_is_red() -> None:
    """注毒㉗-2／-3／-4：三形各红一次——幽灵披露、键集合少列、披露语不点名自己的键。

    三发共用一次现算基线，逐发断言"只有那一类响"，防㉗退化成"只要名册非空就绿"的假锁。
    """
    live = live_effect_preconditions()
    assert live, "注毒前提塌：现算零命中"
    base = {cid: row for cid, row in EFFECT_PRECONDITION_DISCLOSURES.items()}
    victim = min(live)
    scales, keys = live[victim]
    assert keys, "注毒样本无缺省关键可改"

    # ㉗-2 幽灵披露：塞一枚现算不在账的 cid ⇒ 只有 [PD-STALE] 响。
    ghost = min(cid for cid in cm.FACETS if cid not in live)
    ghost_scales, ghost_keys = (POWER_SCALE_CENSUS,), (keys[0],)
    g2 = dict(base, **{ghost: (ghost_scales, ghost_keys, f"合成幽灵披露 {keys[0]}")})
    m, s, sh, v = effect_precondition_problems(live, g2)
    assert not m and not sh and not v and any(ghost in row for row in s), (f"㉗-2 归因不唯一：{m}{s}{sh}{v}")

    # ㉗-3a 少列键（披露比现算窄，这里直接抹成空）⇒ 只有 [PD-SHAPE] 响。
    #     ⚠ 首版这里写的是 `keys0[:-1] or keys0`——每枚在册行的缺省关键现算都只有 1 枚，
    #     于是 `keys0[:-1]` 恒为 `()`、`or` 又把空值兜回原值 ⇒ **整发毒变成空跑**（本席实测抓到自己这一发）。
    #     教训：注毒台落笔前先问"这发毒在今天的现算下真的改变了输入吗"，别用 `or` 兜空。
    narrowed = dict(base)
    scales0, keys0, note0 = narrowed[victim]
    assert len(keys0) == 1, f"注毒样本前提：{victim} 的缺省关键现算应恰 1 枚，实为 {keys0}"
    narrowed[victim] = (scales0, (), note0)
    m, s, sh, v = effect_precondition_problems(live, narrowed)
    assert not m and not s and not v and any(victim in row for row in sh), (
        f"㉗-3a 归因不唯一（少列键没被抓＝披露可比现算窄）：{m}{s}{sh}{v}")

    # ㉗-3b 尺身份吹大（现算只有 census 的枚改报 armed+census）⇒ 同样只有 [PD-SHAPE] 响。
    inflated = dict(base)
    inflated[victim] = ((POWER_SCALE_ARMED, POWER_SCALE_CENSUS), keys0, note0)
    m, s, sh, v = effect_precondition_problems(live, inflated)
    assert not m and not s and not v and any(victim in row for row in sh), (
        f"㉗-3b 归因不唯一（把没通电的尺报成通电没被抓）：{m}{s}{sh}{v}")

    # ㉗-4 披露语换成一句不含任何键的漂亮话 ⇒ 只有 [PD-VAPORNOTE] 响。
    vaporous = dict(base)
    vaporous[victim] = (scales, keys, "这枚早就好了，放心用。")
    m, s, sh, v = effect_precondition_problems(live, vaporous)
    assert not m and not s and not sh and any(victim in row for row in v), (
        f"㉗-4 归因不唯一（空话糊不过名册这条没牙）：{m}{s}{sh}{v}")

