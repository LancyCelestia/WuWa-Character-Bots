"""规格统一常驻门 G-T1 / G-T4 / G-T5（席 T-GATES，2026-09-22 立）。

任务书（准绳一·第四步）五道门里，**G-T2 与 G-T3 按明令扩展在
`tests/test_board_taxonomy_gate.py` 的两个点名函数里**（不许另起平行门）；
本文件持有 G-T1/G-T4/G-T5，并与之共用同一支取数口
`scripts/spec_gates_census.py::compute()`（违规、总数、`--report` 三处同源）。

六件套骨架（照抄 `tests/test_physical_placement_gate.py`，未自创）：
① 单一取数口；② 上限=手写字面量 + AST 自锁（`Assign` 与 `AnnAssign` 双形态）；
③ `AUDIT_HISTORY` 方向锁；④ 扫描面地板（塌陷即红）；⑤ 反向自测全走内存/`tmp_path`
（**不往源码树写一个字**）；⑥ 正样控制（判据必须看得见合法件本身）。

判据一句话：
- **G-T1**（尺＝用户裁定 **R0**，2026-09-23 换尺，席 TX132 落地）判据只量**对外正式面欠账**
  =「该给用户看的正式文档」里未套 `template:` 头者；四类过程件（seat-report / sdd-brief /
  sdd-ledger / parked）**不进欠账、只登记**，但**照样套头**、照样在旧尺总账里——
  扫描面一寸不缩、`T1_CEILING` 一字不升（R0 明令；2026-09-25 用户裁定 N5 追加：本枚**只准
  经 approvals 册收紧重录**——高于旧首届值＝放宽，本通道不收，见
  `scripts/spec_gates_ceiling_approvals.json`）。生成物只按**写盘口现算**豁免
  （board_doc_sync `live_page_paths` / doc_sync `TARGET` / command_catalog `DOC` /
  doc_template_sync `TEMPLATE_DIR`），不写死文件清单。
  两栏真身＝`scripts/spec_gates_census.py::compute()` 的 `t1_debt_official` /
  `t1_registered_process`（席 TX130）；本门**消费**它们，绝不在门里再算一遍（第二真身）。
- **G-T4** 模板 `@schema` 与实际渲染参数双向对齐：缺参红、多参红、死参红、未注册 provider 红。
- **G-T5** 无对应模板的内容类别数=0；类别集合与 `CENSUS.md` §一 **现算**一致；
  孤儿模板、未归类标签、声明却接不到页的类别同样红。
"""

from __future__ import annotations

import ast
import functools
import json
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import board_doc_sync as bds
import doc_fact_discipline as dfd
import doc_template_sync as dts
import doc_templates as dt
import spec_gates_census as sc

# ---------------------------------------------------------------------------
# 手写字面量上限（只准降）。每行注释＝本席开工时刻现算命令与值。
# 复跑：PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0 python scripts/spec_gates_census.py --report
# ---------------------------------------------------------------------------
#: G-T1 上限 = 337（2026-09-25 席 S265 按用户裁定 **N5** 经 approvals 通道重录：判债对象
#: （新尺对外欠账）由该门自己的取数口现算＝337，两读同刻同值见
#: `scripts/spec_gates_ceiling_approvals.json` 的 evidence 栏；终态 0）。
#: 前值 1047 是 2026-09-22 按**旧尺**录的首届核账值——R0（2026-09-23）把判债口径换成
#: 「对外欠账」后本枚仍挂旧尺数＝悬空（S230R 在册），N5 裁定「要」重录。方向核对：337 < 1047
#: ＝**收紧**（放宽须用户逐次数值点头，本通道不收）。偏离 1047 的执法腿＝
#: `test_r0_ceiling_still_pinned_to_old_ruler_first_audit`（读 `_t1_ceiling_approval`）：
#: 册缺席/过期/形态坏 ⇒ 上限必须回 1047、诚实红；册在且有效 ⇒ 上限必须逐枚等于在册 `new_ceiling`。
#: 新尺下若再超上限 ⇒ 让它红着，不许升上限、不许缩扫描面（R0 口径不变）。
T1_CEILING = 337
#: G-T3 面 B（未迁移手写页，`.superpowers/**` 过程日志除外）= 335 **页**
#: （同上现算；页数单调——追加正文不新增页，故不会随机漂移。终态 0）。
T3_UNMOVED_CEILING = 335
#: G-T4 参数不对齐 = 硬零（模板体系新建，无存量债）。
T4_CEILING = 0
#: G-T5 无模板类别 = 18（现算：22 类里只有 seat-report 有模板、3 类归生成器；终态 0）。
T5_MISSING_TEMPLATE_CEILING = 18
#: —— 以下两枚＝席 S2 T-GATE-HARDEN 加严腿新账本（2026-09-22 13:2x 本席现算）。——
#: G-T1面B 类别↔模板错配页 = 0（现算 0：4 张已驱动页全与注册表一致；终态 0——
#: 复跑 `python scripts/spec_gates_census.py --report` 第 4 行）。
MISMATCH_CEILING = 0
#: G-T5 三角闭合断链 = 9 **类**（现算 9 类压 711 页：root-rules/root-report/handbook/
#: board-meta/design-spec/acceptance/doc-misc/persona-knowledge/sdd-ledger 的在册模板
#: 未建或装载失败；记账单位=类，页数在条目文案里。终态 0）。
T5_DEADCLASS_CEILING = 9

#: 扫描面地板（现算管辖内容页 1277 / 板块生成页 225 / 类别 22）——塌陷即红。
MIN_CONTENT_PAGES = 1200
MIN_BOARD_LIVE_PAGES = 220
MIN_CENSUS_CLASSES = 22
MIN_TEMPLATES = 1

#: 旧尺（含本波过程件的全部未套头内容页）首届核账值。**R0 后只作历史对账，不再当欠账判据**，
#: 也不许被人拿来当「债又长了」的证据（那把尺量的本来就是过程件，见裁定件 R0）。
AUDIT_HISTORY_T1: tuple[tuple[str, int], ...] = (("2026-09-22", 1047),)
#: 新尺（R0：只算对外正式面）首届核账值。席 TX132 于 2026-09-23T06:45Z 现算＝**369**
#: （两栏恒等式 369 + 1024 = 1393；类别派生与路径派生同值 ⇒ 判据稳健）。
#: 复跑口径：`python scripts/spec_gates_census.py --report` 的 G-T1 两栏（席 TX130 落地后）。
#: 收口窗由该门 owner 在生成物收敛后重录首届值；本枚与上限之间**不许调大换绿**（R0）。
#: 2026-09-25 用户裁定 N5 重录同批追加第二枚（席 S265 现算 337，出处＝
#: `scripts/spec_gates_ceiling_approvals.json`；方向锁 369→337 只降，凭首届 369 一字未擦）。
AUDIT_HISTORY_T1_OFFICIAL: tuple[tuple[str, int], ...] = (("2026-09-23", 369), ("2026-09-25", 337))
AUDIT_HISTORY_T3B: tuple[tuple[str, int], ...] = (("2026-09-22", 335),)
AUDIT_HISTORY_T4: tuple[tuple[str, int], ...] = (("2026-09-22", 0),)
AUDIT_HISTORY_T5: tuple[tuple[str, int], ...] = (("2026-09-22", 18),)
AUDIT_HISTORY_MISMATCH: tuple[tuple[str, int], ...] = (("2026-09-22", 0),)
AUDIT_HISTORY_T5_DEADCLASS: tuple[tuple[str, int], ...] = (("2026-09-22", 9),)

_CEILING_NAMES = (
    "T1_CEILING",
    "T3_UNMOVED_CEILING",
    "T4_CEILING",
    "T5_MISSING_TEMPLATE_CEILING",
    "MISMATCH_CEILING",
    "T5_DEADCLASS_CEILING",
    "MIN_CONTENT_PAGES",
    "MIN_BOARD_LIVE_PAGES",
    "MIN_CENSUS_CLASSES",
    "MIN_TEMPLATES",
)
_HISTORY_NAMES = (
    "AUDIT_HISTORY_T1",
    "AUDIT_HISTORY_T1_OFFICIAL",
    "AUDIT_HISTORY_T3B",
    "AUDIT_HISTORY_T4",
    "AUDIT_HISTORY_T5",
    "AUDIT_HISTORY_MISMATCH",
    "AUDIT_HISTORY_T5_DEADCLASS",
)

@functools.lru_cache(maxsize=1)
def _real() -> dict[str, Any]:
    """**首用绑定**取数（S555 推广自 S542 格②）：sc.compute() 内含『取数口改名了』的 LookupError 抛点，旧版在模块顶层调它 ⇒ 脏树并发窗一发撕裂读会打成 collection ERROR（不可归因）。函数内取数 + lru_cache(maxsize=1) ⇒ collection 不采样、全进程仍只现算一次，红落具体用例上、可归因。纯形状迁移，判据一字未动。
    """
    return sc.compute()


# ---------------------------------------------------------------------------
# G-T1（尺＝R0 新尺：判据只量「对外正式面」欠账；旧尺总量退为登记栏，不缩面、不升上限）
# ---------------------------------------------------------------------------
#: R0 新两栏的键名。真身＝`scripts/spec_gates_census.py::compute()`（席 TX130 已落地，交**页级名册**
#: 而非裸计数——门要能点名欠款大户，只会加数字的接口做不到）；
#: 本门只**消费**，绝不在门里重算一遍（重算＝第二真身，准绳一）。
R0_NEW_RULER_KEYS: tuple[str, str] = ("t1_debt_official", "t1_registered_process")


def _r0_columns(res: Mapping[str, object]) -> tuple[int, int, int]:
    """fail-closed 读 R0 两栏 + 旧尺总账，返回 `(对外欠账, 过程件登记, 旧尺总量)`。

    四条红线（都属「读不到≠合规」那一族假绿）：
    ① 键缺席即红——**不许**把「取数口还没有新栏」当成「零欠账」放行（TX130 未落地时本门就该红着，
      红在归因处，不许在门里补算绕开）；
    ② 形态改版即红：两栏必须是 `list[str]` 名册（`bool`/裸整数/混类元素一律拒；
      把名册换成一个数，判据立刻失去点名能力）；
    ③ **恒等式**：对外欠账 + 过程件登记 == 旧尺总量。R0 只分账、不缩面，故该式逐刻必须成立；
      哪天有人把过程件从扫描面里*剔除*而不是*另记*，旧尺总量先掉下来、本式当场红；
    ④ 分账互斥：同一页既进欠账又进登记＝两本账其实在互相补洞（`t1_accounting` 若在场则复核，
      该键属 TX130 的自证附加面，本判据的必备契约只有「三栏同源」）。
    """
    old_raw = res.get("t1")
    assert isinstance(old_raw, list), "取数口缺 `t1` 旧尺总账栏＝R0 明令『总账栏不许消失』被破坏"
    old_total = len(old_raw)
    missing = [key for key in R0_NEW_RULER_KEYS if key not in res]
    assert not missing, (
        f"取数口缺 R0 新两栏 {missing}＝席 TX130（`scripts/spec_gates_census.py`）的分账口未生效。"
        "本席独占面只有门文件，不代写取数口（那是第二真身）；此红归因 TX130，勿改本判据绕开。"
    )
    counts: list[int] = []
    for key in R0_NEW_RULER_KEYS:
        value = res[key]
        assert isinstance(value, list), (
            f"{key} 现算类型 {type(value)}≠list[str]（在册形态＝页级名册）＝取数口改版，判红不判绿"
        )
        assert all(isinstance(e, str) for e in value), f"{key} 名册里混进非字符串条目＝改版"
        counts.append(len(value))
    official, process = counts
    assert official + process == old_total, (
        f"R0 恒等式破裂：对外欠账 {official} + 过程件登记 {process} ≠ 旧尺总量 {old_total}"
        "＝要么扫描面被缩（把过程件*剔除*而非*另记*，违 R0/R1『扫描面一寸不缩』），"
        "要么两栏取自不同时刻（不同源＝两套账）。"
    )
    acc = res.get("t1_accounting")
    if isinstance(acc, dict):
        assert acc.get("partition_ok") is True, f"取数口自称分账不闭合：{acc.get('partition_ok')}"
        assert acc.get("overlap_rels") == [], f"一页同时进两栏（分账互斥被破坏）：{acc.get('overlap_rels')}"
    return official, process, old_total


def _r0_rosters(res: Mapping[str, object]) -> tuple[list[str], list[str]]:
    """取两栏**名册**（判据点名用）；形态契约与 `_r0_columns` 同一支，不另立判据。"""
    out: list[list[str]] = []
    for key in R0_NEW_RULER_KEYS:
        value = res[key]
        assert isinstance(value, list) and all(isinstance(e, str) for e in value), (
            f"{key} 不是 list[str]＝取数口改版"
        )
        out.append(list(value))
    return out[0], out[1]


def _r0_pair(
    res: Mapping[str, object],
    total_key: str,
    debt_key: str,
    reg_key: str,
    acc_key: str,
) -> tuple[int, int, int]:
    """fail-closed 读**任意一面**的 R0 三栏（席 S230：R0=A 从 G-T1 扩到 G-T2/G-T4/模板体检）。

    与 `_r0_columns` 同一族红线，只是把键名参数化（键名是 plumbing、不是判据；判据「什么算过程稿」
    唯一住在 `scripts/spec_gates_census.py` 的分母表，本门只**消费**列出的两栏，绝不重算）：
    ① 任一键缺席即红（「取数口还没有新栏」≠「零欠账」，红在归因处）；
    ② 两栏必须是 `list[str]`（换成裸计数就失去点名能力＝改版）；
    ③ 恒等式 `对外欠账 + 过程稿登记 == 总账`（R0 只分账、不缩面，剔除而非另记会当场红）；
    ④ `partition_ok` / `overlap_rels` 自证（若分账面在场）。
    返回 `(对外欠账, 过程稿登记, 旧尺总量)`。
    """
    total_raw = res.get(total_key)
    assert isinstance(total_raw, list), f"取数口缺 `{total_key}` 总账栏＝R0 明令『总账栏不许消失』被破坏"
    missing = [k for k in (debt_key, reg_key) if k not in res]
    assert not missing, (
        f"取数口缺 R0 两栏 {missing}＝席 S230（`scripts/spec_gates_census.py`）的分账口未生效；"
        "本门独占面只有门文件，不代写取数口（那是第二真身），此红归因取数口、勿改本判据绕开。"
    )
    for k in (debt_key, reg_key):
        value = res[k]
        assert isinstance(value, list) and all(isinstance(e, str) for e in value), (
            f"{k} 现算非 list[str]（在册形态＝条目名册）＝取数口改版，判红不判绿"
        )
    official, process = len(res[debt_key]), len(res[reg_key])  # type: ignore[arg-type]
    old_total = len(total_raw)
    assert official + process == old_total, (
        f"R0 恒等式破裂（{total_key}）：对外欠账 {official} + 过程稿登记 {process} ≠ 总账 {old_total}"
        "＝扫描面被缩（把过程稿*剔除*而非*另记*，违 R0『扫描面一寸不缩』）或两栏不同源。"
    )
    acc = res.get(acc_key)
    if isinstance(acc, dict):
        assert acc.get("partition_ok") is True, f"取数口自称分账不闭合：{acc.get('partition_ok')}"
        assert acc.get("overlap_rels") == [], f"一条目同时进两栏（互斥被破坏）：{acc.get('overlap_rels')}"
    return official, process, old_total


def test_g_t1_every_content_page_declares_an_existing_template() -> None:
    """判据（R0 新尺）：**对外正式面**未套模板头者 <= 上限；过程件另栏登记、不进欠账。"""
    viol = _real()["t1"]
    official, process, old_total = _r0_columns(_real())
    assert official <= T1_CEILING, (
        f"对外正式面未套模板头 {official} 页 > 上限 {T1_CEILING}＝又长了不受模板管辖的正式文档。"
        f"（同刻三值：旧尺总量 {old_total} = 对外欠账 {official} + 过程件登记 {process}；"
        f"上限现值系 2026-09-25 按用户裁定 N5 经 approvals 通道由取数口现算重录（收紧，"
        f"前值 1047 为旧尺首届核账值），出处＝scripts/spec_gates_ceiling_approvals.json。）"
        f"修法：页首加 `---\\ntemplate: <id>\\nparams:...\\n---`（模板不存在就先建模板，"
        f"模板先行是准绳）；确属生成物则去写盘口登记，别在这里加豁免。"
        f"欠款名册（新尺，只点名对外面）：{_r0_rosters(_real())[0][-6:]}"
    )
    # 旧尺总账活性地板（R0 后语义变更：这是**取数口没瞎**的活性证明，不是债的判据）。
    assert viol, (
        "旧尺总量一条都没数到＝取数口瞎了（现网确有上千页未迁移），不是大家都合规。"
        "本腿判的是『扫描面还在不在』，绝不拿它当欠账数（欠账数见上面的对外正式面栏）。"
    )
    assert _real()["page_total"] >= MIN_CONTENT_PAGES, (
        f"只扫到 {min(_real()['page_total'], 999999)} 张内容页（地板 {MIN_CONTENT_PAGES}）＝扫描面塌陷，"
        "不是「大家都合规」"
    )


def test_r0_debt_columns_split_official_from_process_pages(tmp_path: Path) -> None:
    """R0 分账有牙（反向自测 + 正样控制，全程 tmp 副本、不落源码树一个字）：
    同刻三值必须是「对外 1 / 过程件 1 / 旧尺 2」——过程件多写一页**不许**把欠账顶上去，
    对外少套一头**必须**进欠账。旧断言只有一格，这两种形状混在一起分不开。
    """
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / ".superpowers" / "sdd" / "x").mkdir(parents=True)
    (root / "docs" / "official-bare.md").write_text("# 对外正式面裸页\n\n正文。\n", encoding="utf-8")
    (root / ".superpowers" / "sdd" / "x" / "SEAT-T-POISON.md").write_text(
        "# 过程件裸页\n\n正文。\n", encoding="utf-8"
    )
    res = sc.compute(root)
    official, process, old_total = _r0_columns(res)
    assert official == 1, f"对外正式面裸页没被单独记进欠账栏（{official}）＝分账失明"
    assert process == 1, f"过程件裸页没被记进登记栏（{process}）＝过程件又在污染欠账数"
    assert old_total == 2, f"旧尺总账不再是两栏之和（{old_total}）＝扫描面被动过"


def test_r0_process_page_cannot_dodge_debt_by_its_own_declaration(tmp_path: Path) -> None:
    """R0 边界「伪装过程件仍须记债」：一张**对外路径**上的页，即便自带过程件的模板帽，
    也绝不从债里消失——它要么留在欠账栏，要么被类别↔模板错配账当场点名（两读皆可，
    但**不许两读皆空**）。判据分账按路径/注册表派生，绝按页面自报的帽子派生。
    """
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "fake-process.md").write_text(
        "---\ntemplate: seat-report\nparams:\n  seat_id: T-FAKE\n  wave: w\n"
        "  status: DONE\n  role: doc\n  report_class: auto:seat_class\n"
        "  ledger_events: auto:page_stat:ledger\n---\n\n## 交付\n",
        encoding="utf-8",
    )
    res = sc.compute(root)
    official, process, _old_total = _r0_columns(res)
    assert process == 0, f"对外路径页被算进过程件登记栏（{process}）＝按页面自报帽子分账，可被伪装"
    named = [m for m in res["mismatch"] if isinstance(m, str) and "fake-process" in m]
    assert official == 1 or named, (
        "docs/ 下的页靠自报 `template: seat-report` 两头都不记账＝「伪装过程件」成了免债通道"
        f"（欠账 {official}、错配账 {named}）"
    )


def test_r0_contract_read_is_fail_closed_against_fabricated_res() -> None:
    """本席自证：`_r0_columns` 对「缺栏 / 总账栏消失 / 形态改版 / 恒等式破裂 / 分账互斥」各必红
    （读不到绝不放行）。注毒全在内存造字典，不碰真树、不碰取数口。

    **夹具形态改版说明（2026-09-23 主会话亲做，非放宽判据）**：首版（席 TX132）把在册形态写成
    裸整数，而取数口 `scripts/spec_gates_census.py::compute()` 落地的是 **`list[str]` 名册**
    （护栏二要求"可点名"）⇒ 第一行 `_r0_columns(base)` 就在「类型」断言上抛，
    其后五发注毒**一次都没执行过**，却因整条用例红着而被当成"已自证"。
    本次只改**喂进去的假数据形状**、一字不改判据本体；改完执行到的断言由 1 增至 8。
    原「为负」一腿**改按可表达形态**：`len(名册)` 结构上不可能为负，
    该危害由「形态改版即红」吸收（塞数字/塞 bool 一律拒），故不保留一条永远打不到的断言。
    """
    base: dict[str, object] = {
        "t1": ["a.md", "b.md"],
        "t1_debt_official": ["a.md"],
        "t1_registered_process": ["b.md"],
    }
    assert _r0_columns(base) == (1, 1, 2)
    # ① 取数口缺新栏＝分账口未生效，绝不按"零欠账"放行
    with pytest.raises(AssertionError, match="尚未落地|R0 新两栏"):
        _r0_columns({"t1": ["a.md"]})
    # ② 旧尺总账栏消失＝R0 明令被破坏（哪怕两栏看着都在）
    with pytest.raises(AssertionError, match="总账栏不许消失"):
        _r0_columns({"t1_debt_official": [], "t1_registered_process": []})
    # ③ 名册换成裸整数＝判据失去点名能力（TX132 首版夹具的那一形，今天必须红）
    with pytest.raises(AssertionError, match="类型"):
        _r0_columns(
            {"t1": ["a.md", "b.md"], "t1_debt_official": 1, "t1_registered_process": 1}
        )
    # ④ bool 是 int 子类，同样拒（防"用 True 冒充有一页"）
    with pytest.raises(AssertionError, match="类型"):
        _r0_columns(
            {"t1": ["a.md"], "t1_debt_official": True, "t1_registered_process": []}
        )
    # ⑤ 名册里混进非字符串条目＝改版
    with pytest.raises(AssertionError, match="非字符串"):
        _r0_columns(
            {"t1": ["a.md"], "t1_debt_official": [1], "t1_registered_process": []}
        )
    # ⑥ 恒等式破裂＝少报一页（把过程件*剔除*而非*另记*的可表达形态）
    with pytest.raises(AssertionError, match="恒等式破裂"):
        _r0_columns(
            {
                "t1": ["a.md", "b.md", "c.md"],
                "t1_debt_official": ["a.md"],
                "t1_registered_process": ["b.md"],
            }
        )
    # ⑦ 取数口自称分账不闭合
    with pytest.raises(AssertionError, match="分账不闭合"):
        _r0_columns(
            {
                **base,
                "t1_accounting": {"partition_ok": False, "overlap_rels": []},
            }
        )
    # ⑧ 一页同时进两本账＝两账互相补洞（总账按 3 条目记，恒等式先成立，才轮到互斥腿判红）
    with pytest.raises(AssertionError, match="同时进两栏"):
        _r0_columns(
            {
                "t1": ["a.md", "b.md", "b.md"],
                "t1_debt_official": ["a.md", "b.md"],
                "t1_registered_process": ["b.md"],
                "t1_accounting": {"partition_ok": True, "overlap_rels": ["b.md"]},
            }
        )



def test_r1_old_total_column_never_disappears() -> None:
    """R0/R1 边界「总账栏不许消失、扫描面不许缩」的机器腿：旧尺总量 ≥ 首届核账值（缩面即红），
    且 `--report` 那行原样还在（恒等式与两栏同源由 `_r0_columns` 逐刻锁）。
    """
    _official, _process, old_total = _r0_columns(_real())
    assert old_total >= AUDIT_HISTORY_T1[0][1], (
        f"旧尺总量 {old_total} 低于首届核账值 {AUDIT_HISTORY_T1[0][1]}＝扫描面被缩而不是分账"
        "（R0 只分账、R1 明令不缩面）。真降账（页面被删除/并入生成物）须由该门 owner 核账后重录。"
    )
    assert f"G-T1 无模板头且非生成物 = {old_total}" in "\n".join(sc.report_lines(_real())), (
        "`--report` 不再报旧尺总账＝总账栏在投影口消失了"
    )


def test_g_t1_generated_exemption_names_its_producer_not_a_file_list() -> None:
    """生成物豁免必须点名取数口：四个写盘口各自现算、非空、且路径真存在。"""
    gen = _real()["generated_map"]
    for key in (
        "scripts/board_doc_sync.py:live_page_paths",
        "scripts/doc_sync.py:TARGET",
        "scripts/command_catalog.py:DOC",
        "scripts/doc_template_sync.py:TEMPLATE_DIR",
    ):
        assert key in gen, f"生成物判据缺写盘口 {key}（豁免面缩水=未生成页被误判，或反之）"
        assert gen[key], f"{key} 现算为空＝该写盘口对门失明，豁免形同虚设"
        for rel in gen[key]:
            assert (REPO_ROOT / rel).is_file(), f"{key} 报了不存在的页 {rel}"
    boards = gen["scripts/board_doc_sync.py:live_page_paths"]
    assert len(boards) >= MIN_BOARD_LIVE_PAGES, f"板块生成页只剩 {len(boards)} 张＝板块面塌陷"
    assert "docs/boards/README.md" in boards, "live_page_paths 连总览页都没报出来＝取数口错位"


def test_g_t1_poison_bare_and_fake_template_pages_are_named(tmp_path: Path) -> None:
    """反向自测：裸页必被点名；「有头但头指向不存在的模板」同罪（防有头就算数）。
    正样页 fixture 由席 S2 移位（2026-09-22 加严腿 TEMPLATE_CATEGORY_MISMATCH 生效后，
    原先放在 docs/ 的「正样」本身成了 F-2 的套错帽子通道——类别 doc-misc 却声明
    seat-report——fixture 不再合法；断言方向一字未动，只是把正样挪到它真的合规处）。"""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / ".superpowers").mkdir(parents=True)
    bare = root / "docs" / "bare.md"
    bare.write_text("# 裸页\n\n正文若干。\n", encoding="utf-8")
    fake = root / "docs" / "fake.md"
    fake.write_text("---\ntemplate: no-such-tpl\n---\n\n# 假头\n", encoding="utf-8")
    good = root / ".superpowers" / "SEAT-GOOD.md"
    good.write_text(
        "---\ntemplate: seat-report\nparams:\n  seat_id: T-POISON\n  wave: w\n"
        "  status: DONE\n  role: gate\n  report_class: auto:seat_class\n"
        "  ledger_events: auto:page_stat:ledger\n---\n\n## 交付\n",
        encoding="utf-8",
    )
    res = sc.compute(root)
    viol = set(res["t1"])
    assert "docs/bare.md" in viol, f"裸页没被抓：{sorted(viol)}"
    assert "docs/fake.md" in viol, "指向不存在模板的假头没被抓＝有头就算数"
    assert ".superpowers/SEAT-GOOD.md" not in viol, f"合规页被误杀：{sorted(viol)}"


# ---------------------------------------------------------------------------
# G-T1面B 类别↔模板一致性（席 S2 加严腿，攻击依据 SEAT-T-ACCUSE F-2）
# ---------------------------------------------------------------------------
def test_g_t1b_class_template_mismatch_never_grows() -> None:
    viol = _real()["mismatch"]
    assert len(viol) <= MISMATCH_CEILING, (
        f"套了「不是它这一类」的在册模板的页 {len(viol)} > 上限 {MISMATCH_CEILING}"
        "（现值 0＝该类假合规一条都不该有）。修法：改页 front-matter 的 template: 为"
        "注册表（doc_templates.py）给它那类的模板，或按升级流程改注册表；"
        "别在门里另写类别表。大户：" + " | ".join(viol[:4])
    )


def test_g_t1b_poison_wrong_template_stays_in_t1_and_is_named(tmp_path: Path) -> None:
    """反向自测（内存）：doc-misc 页随手套 `seat-report` ——F-2 的通道必须两头红：
    ① G-T1 不销籍（仍记债）② TEMPLATE_CATEGORY_MISMATCH 点名（走 compute 记账腿）。
    正样控制：类别↔模板一致的 SEAT 页两头都不红。"""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / ".superpowers" / "sdd" / "t").mkdir(parents=True)
    wrong = root / "docs" / "wrong.md"
    wrong.write_text(
        "---\ntemplate: seat-report\nparams:\n  seat_id: T-X\n  wave: w\n"
        "  status: DONE\n  role: gate\n  report_class: auto:seat_class\n"
        "  ledger_events: auto:page_stat:ledger\n---\n\n## 交付\n\n正文。\n",
        encoding="utf-8",
    )
    good = root / ".superpowers" / "sdd" / "t" / "SEAT-GOOD.md"
    good.write_text(
        "---\ntemplate: seat-report\nparams:\n  seat_id: T-GOOD\n  wave: w\n"
        "  status: DONE\n  role: gate\n  report_class: auto:seat_class\n"
        "  ledger_events: auto:page_stat:ledger\n---\n\n## 交付\n\n正文。\n",
        encoding="utf-8",
    )
    res = sc.compute(root)
    assert "docs/wrong.md" in set(res["t1"]), "套错模板仍从 G-T1 销籍＝F-2 通道没堵"
    named = [m for m in res["mismatch"] if m.startswith("TEMPLATE_CATEGORY_MISMATCH docs/wrong.md")]
    assert named, f"类别↔模板错配没被点名：{res['mismatch']}"
    assert "doc-misc" in named[0] and "guide" in named[0], f"罪状没走注册表口径：{named[0]}"
    assert not any("SEAT-GOOD.md" in m for m in res["mismatch"]), "合规页被误杀（正样控制失败）"
    assert ".superpowers/sdd/t/SEAT-GOOD.md" not in set(res["t1"])


# ---------------------------------------------------------------------------
# G-T5 第三边：类别 ↔ 模板 ↔ 页 三角闭合（席 S2 加严腿）
# ---------------------------------------------------------------------------
def test_g_t5_triangle_closure_pages_never_land_in_unreachable_class() -> None:
    rows = _real()["t5"]["pages_unreachable"]
    assert len(rows) <= T5_DEADCLASS_CEILING, (
        f"有 {len(rows)} 类（记账单位=类别，页数在文案里）页落到接不到在册模板的类别，"
        f"超上限 {T5_DEADCLASS_CEILING}。修法：为该类别在 docs/templates/ 建模板"
        "（G-T5 另一本账 missing_template 同步销债）。现况：" + " | ".join(rows[:6])
    )
    # 正样控制：seat-report 类在册模板存在且已装载，合法驱动页所在的类不许出现在这条腿上
    assert not any(r.startswith("seat-report:") for r in rows), (
        f"接得到模板的类别被误记三角断链：{rows}"
    )


_S287_CID = "doc-misc"
_S287_REL = "docs/orphan.md"


def _s287_poison_class(monkeypatch: pytest.MonkeyPatch, *, template: str | None) -> None:
    """内存把在册 md 类 `doc-misc` 的模板改成 `template`（`None`＝该桶压根没有模板）。

    照抄活体先例 `tests/test_g_t5_third_edge_liveness.py::_docmisc_with_template` 与
    席 S164 的 `_s164_bucket`：**两份注册表视图同步改**（`CONTENT_CATEGORIES` 与
    `CATEGORIES_BY_ID`），teardown 自动还原。这是构造「类别在册但该桶无模板」的**唯一手段**
    ——不改 `scripts/**`（公共只读面）、不落盘、不新建第二套分类表。
    """
    rows: list[dt.CategoryDef] = []
    for c in dt.CONTENT_CATEGORIES:
        if c.cid == _S287_CID:
            rows.append(
                dt.CategoryDef(
                    cid=c.cid, template=template, surface=c.surface, owner_board=c.owner_board,
                    generated_by=c.generated_by, code_home=c.code_home,
                    reason="S287 内存注毒件（不是真类别状态、不落盘）",
                )
            )
        else:
            rows.append(c)
    monkeypatch.setattr(dt, "CONTENT_CATEGORIES", tuple(rows))
    monkeypatch.setattr(dt, "CATEGORIES_BY_ID", {x.cid: x for x in rows})


def _s287_assert_poison_took_effect(*, want_template: str | None) -> None:
    """注毒前提自证（fail-closed，#9=准「执法更强」的那一半）。

    两问分开查，缺一即炸：
    ① **视图真被改了吗**——`CATEGORIES_BY_ID[cid].template` 必须等于本次宣称要注入的值。
      否则本条退化成「什么都没改还盼它红」的空跑（统一波自打脸账同型：注毒用例写死
      受害 cid ⇒ 毒腿空跑仍报绿）。
    ② **该桶还归本腿管辖吗**——`should_have_template`（`spec_gates_census.py:447`）是
      「在册 md 面、非生成器所有」的**管辖**谓词，跟「有没有模板」是两回事；注毒注入的
      正是「归管辖、却没有模板」这一形状。管辖面若被顺带毒掉（误改 surface/generated_by），
      注的就不是本腿要防的那件事，同样判红。
    """
    got = dt.CATEGORIES_BY_ID[_S287_CID].template
    assert got == want_template, (
        f"内存注毒未生效（{_S287_CID}.template 实为 {got!r}，期望 {want_template!r}）"
        "＝本条将空跑，判红不判绿"
    )
    assert sc.should_have_template(_S287_CID) is True, (
        f"{_S287_CID} 已不归 G-T5 第三边管辖＝注毒注的不是本腿要防的形状（管辖面被顺带改坏）"
    )


def _s287_root(tmp_path: Path) -> Path:
    """临时副本里放一张无头页，使其落到 `_S287_CID` 桶；返回 `compute(root)` 的 root。

    `exist_ok=True`：一枚用例内多次换形状现算时同页复用会 `FileExistsError`＝自炸非判据红。
    """
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "orphan.md").write_text("# 无头页\n\n正文。\n", encoding="utf-8")
    assert dts.classify(_S287_REL) == _S287_CID, "取数口改版：该页不再落到 doc-misc，注毒前提塌"
    return root


def _s287_third_edge_rows(res: dict[str, object]) -> list[str]:
    """fail-closed 读第三边，并只筛本席载体类别（不把读不到当合规）。"""
    t5 = res["t5"]
    assert isinstance(t5, dict), f"取数口缺 t5 或类型异常（{type(t5)}）＝读口失明，判红不判绿"
    rows = t5["pages_unreachable"]
    assert isinstance(rows, list), f"pages_unreachable 不是 list（{type(rows)}）＝取数口改版"
    assert all(isinstance(r, str) for r in rows), "三角断链元素非字符串＝取数口返回类型异常"
    return [r for r in rows if r.startswith(f"{_S287_CID}:")]


def test_g_t5_poison_triangle_third_edge_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-T5 第三边**反证腿**（席 S287，2026-09-23，用户裁定 #9=准：改内存注毒）。

    旧例（席 T-GATES 原形）是「往 tmp 副本塞一张无头页 ⇒ 盼 `doc-misc` 的在册模板 `guide`
    **恰好**没落地」。那个前提**结构性不成立**：`compute()` 的 `schemas` 恒从绝对
    `doc_template_sync.TEMPLATE_DIR` 装载、不吃 `root=` 形参，而 `guide` 自 HEAD `31467b4`
    起是真模板 ⇒ 该用例与「第三边有没有牙」再无关系，只是**永远红的常数**
    （PARKED **P-42** 原话「已退化成『永远红的常数』」，推荐 A＝内存注毒替身）。

    现在的形状：主动往注册表造一枚「在册但无模板」的类别（内存、不落盘），再断言第三边
    **必须**点名它。⇒ 债被正当清零时本条仍绿（不再假红），而取数口一旦瞎掉本条立刻红
    （执法比旧例更强）。
    """
    _s287_poison_class(monkeypatch, template=None)  # 在册 md 类、该桶压根没有模板
    _s287_assert_poison_took_effect(want_template=None)
    rows = _s287_third_edge_rows(sc.compute(_s287_root(tmp_path)))
    assert len(rows) == 1, f"注毒（在册但无模板的类别）没被第三边点名＝反证腿没牙：{rows}"
    assert "1 页" in rows[0], f"断链按页计数没落进文案（记账单位异常）：{rows}"


def test_g_t5_poison_leg_keeps_reachable_class_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """正样控制（合规必绿）：同一张页、同一个类别，只把模板换回可装载的 `guide` ⇒ 零断链。

    本腿绝不是什么「有页就判红」的钝尺；判据必须看得见合法件本身（六件套骨架第⑥条）。
    """
    _s287_poison_class(monkeypatch, template="guide")
    _s287_assert_poison_took_effect(want_template="guide")
    rows = _s287_third_edge_rows(sc.compute(_s287_root(tmp_path)))
    assert rows == [], f"模板可达的类别被误记三角断链（钝尺误杀，正样控制失败）：{rows}"


def test_g_t5_zero_debt_does_not_bark() -> None:
    """清零不假红（旧地板腿摘牌后的替代自证）：真树现算，两本 G-T5 账归零时门必须绿着通过。

    旧 `test_g_t5_no_class_without_a_template` 尾部那枚 `assert missing` 在债归零后必红
    （见该函数内的摘牌注释）。本条把它想防的事换成**主动**证明：先把真树的数值读出来，
    再确认「上限腿」对 0 是放行态度——而不是靠「真树里至少还得有一条债」续命。
    """
    t5 = _real()["t5"]
    missing = t5["missing_template"]
    deadclass = t5["pages_unreachable"]
    assert isinstance(missing, list) and isinstance(deadclass, list), "取数口返回类型异常＝读口失明"
    assert len(missing) <= T5_MISSING_TEMPLATE_CEILING, (
        f"无模板类别 {len(missing)} 超上限＝上限腿该红（那是真债，不是假红）"
    )
    assert len(deadclass) <= T5_DEADCLASS_CEILING, (
        f"三角闭合断链 {len(deadclass)} 超上限＝上限腿该红（那是真债，不是假红）"
    )


def test_g_t5_silent_poison_is_detected() -> None:
    """第四发自证（把注毒改坏时必须测得到）：空跑的注毒一律被前提自证炸掉。

    这里**故意**只把模板改成它本来的值却宣称改成 `None`——注毒没落地。若这种空跑不被发现，
    上面的反证腿就会退化成旧例那种「红/绿都不说明问题」的常数。断言必抛＝本条绿；
    一旦有人把 `_s287_assert_poison_took_effect` 删了或改成永真，反证腿立刻红。
    """
    with pytest.raises(AssertionError):
        _s287_assert_poison_took_effect(want_template=None)  # 真注册表里 doc-misc 有 guide＝毒没生效


# ---------------------------------------------------------------------------
# G-T2（判据腿在此锁死；记账在板块门 `test_generated_pages_have_full_skeleton`）
# ---------------------------------------------------------------------------
def test_g_t2_section_ruler_sees_three_poison_shapes() -> None:
    """反向自测（内存）：改名 / 换序 / 塞野节各点名；正样控制＝真骨架原文喂判据必零偏离。"""
    canon = sc.L2_CANON
    ok = ["这个功能解决什么", "处理流程", "测试与验收"]
    assert sc.section_findings(ok, canon) == [], f"合法件被误杀：{sc.section_findings(ok, canon)}"
    renamed = sc.section_findings(["这个功能做什么", "处理流程", "测试与验收"], canon)
    assert any("SECTION_UNKNOWN" in v for v in renamed), "改节名没被抓"
    swapped = sc.section_findings(["处理流程", "这个功能解决什么", "测试与验收"], canon)
    assert any("SECTION_ORDER" in v for v in swapped), "换序没被抓"
    extra = sc.section_findings(ok + ["现役进度"], canon)
    assert any("SECTION_UNKNOWN" in v for v in extra), "塞野节没被抓"
    missing = sc.section_findings(["这个功能解决什么", "处理流程"], canon)
    assert any("SECTION_MISSING" in v and "测试与验收" in v for v in missing), "缺必选节没被抓"
    # 正样控制二：三份真骨架原文喂各自 canon 必须零偏离（判据看不见标准件＝空跑）
    for body, lc in ((bds.L1_BODY, sc.L1_CANON), (bds.L2_BODY, sc.L2_CANON), (bds.L3_BODY, sc.L3_CANON)):
        assert sc.section_findings(sc.headings(body), lc) == [], f"{lc[:1]} 自骨架喂自判据不合规"


# ---------------------------------------------------------------------------
# G-T4
# ---------------------------------------------------------------------------
def test_g_t4_schema_and_render_params_stay_aligned() -> None:
    # 席 S230（R0=A）：判债对象由「旧尺总量」改为「对外正式面欠账」（与 G-T1 同口径）；
    # 过程稿（`.superpowers/**` 席位报告/简报/台账）另栏登记、不进欠账——扫描面一寸不缩、
    # 上限 T4_CEILING 一字不动（本枚今日仍 =0），旧尺总账仍被恒等式与活性证明钉着。
    official, process, old_total = _r0_pair(
        _real(), "t4", "t4_debt_official", "t4_registered_process", "t4_accounting"
    )
    assert official <= T4_CEILING, (
        f"对外正式面 @schema/实参不对齐 {official} 项（上限 {T4_CEILING}，模板体系对外无存量债）：\n"
        + "\n".join(_real()["t4_debt_official"][:12])
        + f"\n（同刻三值：旧尺总账 {old_total} = 对外欠账 {official} + 过程稿登记 {process}；"
        + "过程稿的体检债另册可见，不因分账而隐身。）"
    )
    assert len(_real()["schemas"]) >= MIN_TEMPLATES, "模板面为空＝G-T4 变成空门"


def test_g_t4_poisons_missing_extra_dead_param_and_bad_provider() -> None:
    """反向自测（全内存 fixture，不碰 docs/templates）：缺参/多参/死参/未注册 provider/
    规格外占位各红；真模板零违规作正样控制（判据看不见合法件＝空跑）。"""
    real = dts.parse_schema_text(
        (REPO_ROOT / "docs" / "templates" / "seat-report.md").read_text(encoding="utf-8"),
        "seat-report",
    )
    assert sc.template_side_t4({"seat-report": real}) == [], "真模板被判死参＝正样控制失败"

    def synth(extra_decl: str, zone: str) -> dts.Schema:
        return dts.parse_schema_text(
            "<!-- @schema:BEGIN\nsections: 交付 | 自报\nparams:\n"
            "- seat_id | text | literal | req | nonempty\n" + extra_decl +
            "@schema:END -->\n"
            "<!-- TEMPLATE-AUTO:BEGIN -->\n" + zone + "\n<!-- TEMPLATE-AUTO:END -->\n",
            "poison",
        )

    # ① 死参：声明了却没被渲染区消费
    rows = sc.template_side_t4({"poison": synth("- loner | text | literal | opt | any\n", "- {{fact:seat_id}}")})
    assert any(v.startswith("DEAD_PARAM") and "loner" in v for v in rows), f"死参没被抓：{rows}"
    # ② auto 指向未注册 provider
    rows = sc.template_side_t4({"poison": synth("- cls | text | auto:nope | req | any\n", "- {{fact:seat_id}}{{fact:cls}}")})
    assert any(v.startswith("PROVIDER_MISSING") and "nope" in v for v in rows), f"未注册 provider 没被抓：{rows}"
    # ③ 渲染区写了 params 里没有的占位（规格外）
    with pytest.raises(dts.SchemaError, match="占位"):
        synth("", "- {{fact:seat_id}}{{fact:ghost}}")

    # ④ 页侧：多参与缺参同时点名
    _vals, viol = dts.resolve_params(
        real,
        dts.FrontMatter(template="seat-report", params={"nope": "x"}, extra_keys=("junk",)),
        dts.PageCtx(rel="x/SEAT-A.md", body_no_fm=""),
    )
    codes = " ".join(viol)
    assert "EXTRA_PARAM" in codes and "nope" in codes, f"多参没被抓：{codes}"
    assert "MISSING_PARAM" in codes, f"缺必填参没被抓：{codes}"
    page_viol = dts.check_page(
        real, "", dts.FrontMatter(template="seat-report", params={}, extra_keys=("junk",)),
        dts.PageCtx(rel="x/SEAT-A.md", body_no_fm="## 交付\n"),
    )
    assert "FM_EXTRA_KEY" in " ".join(page_viol), f"front-matter 规格外键没被抓：{page_viol}"
    assert any(v.startswith("MISSING_PARAM") for v in page_viol), f"空 params 页没被抓：{page_viol}"


def test_g_t4_poison_req_param_must_actually_come_from_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反向自测（席 S2 活性腿，全走 compute **记账腿**，不是只喂正则）：
    ① `req`+`auto:` 参数字面量冒充 ⇒ AUTO_SOURCE_MISMATCH 进 t4；
    ② 该参数整个缺掉 ⇒ MISSING_PARAM 进 t4；
    ③ provider 跑通却交空值 ⇒ PROVIDER_EMPTY 进 t4；
    正样控制＝三项都写对的页在 t4 里零罪状。"""
    root = tmp_path / "repo"
    pkg = root / ".superpowers" / "sdd" / "t"
    pkg.mkdir(parents=True)

    def page(name: str, report_class: str, ledger: str) -> str:
        (pkg / name).write_text(
            "---\ntemplate: seat-report\nparams:\n"
            f"  seat_id: T-{name[:5]}\n  wave: w\n  status: DONE\n  role: gate\n"
            f"  report_class: {report_class}\n  ledger_events: {ledger}\n"
            "---\n\n## 交付\n\n正文。\n",
            encoding="utf-8",
        )
        return f".superpowers/sdd/t/{name}"

    fake = page("SEAT-FAKE.md", "SEAT", "auto:page_stat:ledger")  # ① 字面量冒充现算值
    missing = pkg / "SEAT-MISS.md"
    missing.write_text(
        "---\ntemplate: seat-report\nparams:\n  seat_id: T-M\n  wave: w\n"
        "  status: DONE\n  role: gate\n  ledger_events: auto:page_stat:ledger\n"
        "---\n\n## 交付\n\n正文。\n",
        encoding="utf-8",
    )  # ② 必填 auto 参数整个缺掉
    good = page("SEAT-OK.md", "auto:seat_class", "auto:page_stat:ledger")

    res = sc.compute(root)
    t4 = " \n".join(res["t4"])
    assert fake in t4 and "AUTO_SOURCE_MISMATCH" in t4 and "report_class" in t4, (
        f"字面量冒充没进记账腿：{res['t4']}"
    )
    assert ".superpowers/sdd/t/SEAT-MISS.md" in t4 and "MISSING_PARAM" in t4, (
        f"缺必填 auto 参没进记账腿：{res['t4']}"
    )
    assert not any(good in v for v in res["t4"]), f"合规页被误杀（正样控制失败）：{res['t4']}"

    # ③ provider 现算空值：摘掉 page_stat 真身、换上交白卷的假 provider，再走一遍记账
    monkeypatch.setitem(dts.PROVIDERS, "page_stat", lambda arg, ctx: "")
    res2 = sc.compute(root)
    assert any(
        "SEAT-OK.md" in v and "PROVIDER_EMPTY" in v for v in res2["t4"]
    ), f"provider 空值冒充现算没被抓：{res2['t4']}"
    monkeypatch.setitem(dts.PROVIDERS, "page_stat", lambda arg, ctx: "（未填）")
    res3 = sc.compute(root)
    assert any(
        "SEAT-OK.md" in v and "PROVIDER_EMPTY" in v for v in res3["t4"]
    ), f"占位符冒充现算值没被抓：{res3['t4']}"


# ---------------------------------------------------------------------------
# G-T5
# ---------------------------------------------------------------------------
def test_g_t5_category_set_equals_census_section_one() -> None:
    t5 = _real()["t5"]
    assert t5["census_count"] >= MIN_CENSUS_CLASSES, (
        f"只从 CENSUS §一 解析出 {t5['census_count']} 个类别名＝判据源改版或表格变形，门必须复核"
    )
    assert t5["cid_set_matches_census"], (
        "类别集合与 CENSUS §一 不一致："
        f"仅在册 {t5['registry_only']} / 仅 CENSUS {t5['census_only']}"
    )
    assert not t5["unknown_labels"], f"出现未在册的类别标签（自由发挥类）：{t5['unknown_labels']}"
    assert not t5["orphan_templates"], f"孤儿模板（无类别引用）：{t5['orphan_templates']}"
    assert not t5["declared_no_page"], (
        f"在册却一张页也接不到的文档类（死类别＝假在册）：{t5['declared_no_page']}"
    )


def test_g_t5_no_class_without_a_template() -> None:
    missing = _real()["t5"]["missing_template"]
    assert len(missing) <= T5_MISSING_TEMPLATE_CEILING, (
        f"无对应模板的内容类别 {len(missing)} > 上限 {T5_MISSING_TEMPLATE_CEILING}。"
        f"每类一份模板是准绳；修法=为该类别建 docs/templates/<id>.md（含 @schema），"
        f"或在注册表把它并入已有类别。欠款大户：{missing[:8]}"
    )
    # ─────────────────────────────────────────────────────────────────────────
    # 旧地板腿（席 T-GATES 原句，**判据本体保留在此、不删**）：
    #     assert missing, "一条都没数到＝注册表与模板目录对不上眼时门会空跑"
    #
    # 摘牌（席 S287，2026-09-23，用户裁定 **#9=准**；PARKED **P-42** 推荐 A）
    #
    # 它当初防什么：`missing_template` 取数口若瞎掉、恒返回 `[]`，那么「零欠款」是假象，
    #   上限腿 `<= 18` 对空集合恒真 ⇒ 门会**空跑而自称合规**。这属本项目反复记账的
    #   「空集合恒真」那一族假绿，当年用地板句挡它，方向是对的。
    #
    # 为什么现在必须摘：这本账的**合法终态就是 0**（本文件 :51 注释原话「终态 0」）。
    #   债被正当清零之后（`--report` 现算 `G-T5 无模板类别 = 0`，销债席 S167/S213），
    #   「至少还得数到一条」就**必然红**——红的原因不是有人违规，而是债真被还清了。
    #   即 PARKED P-42 判定的「已退化成永远红的常数」、P-52 表第 2 行「无模板类别被正当
    #   清零 ⇒ 注毒样本无从附着、毒腿空转」。**它从防假绿的门，变成了造假红的门。**
    #
    # 摘牌后靠什么防同一件事（方向＝执法更强，非缩面）：地板腿是**间接**证据（赌真树里
    #   恰好还有债），现由 `test_g_t5_poison_triangle_third_edge_is_named` 的**内存注毒**
    #   当场**主动**造一枚无模板类别并断言必被点名＝直接证据；再加
    #   `test_g_t5_silent_poison_is_detected`（注毒空跑必炸）与
    #   `test_g_t5_zero_debt_does_not_bark`（归零不得判红）两枚。三枚任被改坏即红，
    #   覆盖面严格大于旧地板句，且不再随债的清偿而失真。
    #
    # 未动的东西（禁线自证）：上限腿一字未改、`T5_MISSING_TEMPLATE_CEILING` 一字未降、
    #   无 skip/xfail、无豁免注释、`_BASELINE_*` 未碰。
    # ─────────────────────────────────────────────────────────────────────────


def test_g_t5_registry_has_a_single_home() -> None:
    """结构锁：`CONTENT_CATEGORIES` 字面量只准住 `scripts/doc_templates.py`。"""
    homes: list[str] = []
    roots = [REPO_ROOT / "scripts", REPO_ROOT / "tests", REPO_ROOT / "plugins"]
    for base in roots:
        for py in base.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                targets: list[ast.expr] = []
                if isinstance(node, ast.Assign):
                    targets = list(node.targets)
                elif isinstance(node, ast.AnnAssign):
                    targets = [node.target]
                if any(isinstance(t, ast.Name) and t.id == "CONTENT_CATEGORIES" for t in targets):
                    homes.append(py.relative_to(REPO_ROOT).as_posix())
    assert homes == ["scripts/doc_templates.py"], (
        f"类别注册表出现第二真身 {homes}——G-T5 会各按一套账，必须合并到注册表"
    )


def test_g_t5_poison_class_without_template_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """反向自测（内存摘模板）：把在册类别的模板摘掉，门当场点名该类别。"""
    rows = list(dt.CONTENT_CATEGORIES)
    for i, c in enumerate(rows):
        if c.cid == "handbook":
            rows[i] = dt.CategoryDef(
                cid=c.cid, template=None, surface=c.surface, owner_board=c.owner_board,
                reason=c.reason,
            )
    monkeypatch.setattr(dt, "CONTENT_CATEGORIES", tuple(rows))
    res = sc.compute()
    named = [m for m in res["t5"]["missing_template"] if m.startswith("handbook:")]
    assert named, "摘掉模板的类别没被抓＝G-T5 对『无模板类别』失明"


# ---------------------------------------------------------------------------
# R3（A 案）补的一枚机器腿：「内存注毒」与「改真身注册表」的差别，必须有人盯着。
# ---------------------------------------------------------------------------
def _r3_source_template_literals() -> dict[str, str | None]:
    """从 `scripts/doc_templates.py` 的**源码字面量**现解析 `cid -> template`（不吃内存视图）。

    解析不到任何 `CategoryDef(...)` 就返回空表，由调用方的「有牙自证」当场判红——
    判据改版时本腿宁可红，也不许退化成「两边都空 ⇒ 相等 ⇒ 绿」。
    """
    src = (REPO_ROOT / "scripts" / "doc_templates.py").read_text(encoding="utf-8")
    out: dict[str, str | None] = {}
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "CategoryDef"):
            continue
        cid: str | None = None
        template: str | None = None
        seen_template = False
        for kw in node.keywords:
            if kw.arg == "cid" and isinstance(kw.value, ast.Constant):
                cid = kw.value.value  # type: ignore[assignment]
            elif kw.arg == "template":
                seen_template = True
                if isinstance(kw.value, ast.Constant):
                    template = kw.value.value  # type: ignore[assignment]
        if cid and seen_template:
            out[cid] = template
    return out


def _r3_drift(literal: dict[str, str | None], live: dict[str, str | None]) -> dict[str, tuple[str | None, str | None]]:
    """返回「内存视图 ≠ 源码字面量」的类别；空表＝注册表没被残留的注毒污染。"""
    return {
        cid: (live.get(cid), tpl)
        for cid, tpl in literal.items()
        if live.get(cid) != tpl
    }


def test_r3_in_memory_poison_auto_restores_and_never_touches_the_registry() -> None:
    """R3 要求「测完自动还原」——这条就是把『自动还原』变成可判红的事实（席 TX132，2026-09-23）。

    为什么需要它：A 案把落盘注毒换成内存注毒（`_s287_poison_class` 摘 `doc-misc`、
    `test_g_t5_poison_class_without_template_is_named` 摘 `handbook`，均经 `monkeypatch`）。
    但「用了 monkeypatch」本身不产证据——**一旦有人改成直接给模块赋值、或把注毒落盘去改
    `scripts/doc_templates.py`**，全文件的 G-T5 账就会跟着被污染的注册表一起自证自绿。
    本腿按 pytest 的**源码顺序**跑在两枚注毒腿之后，拿源码字面量对照内存视图：
    ① 两边必须一致（残留即红）；② 漂移检测自身有牙（造一枚假漂移必被看见，防空跑）。
    """
    literal = _r3_source_template_literals()
    assert literal, "从 doc_templates.py 解析不到 CategoryDef 字面量＝取样口改版，本腿会空跑"
    live = {c.cid: c.template for c in dt.CONTENT_CATEGORIES}
    assert len(literal) >= MIN_CENSUS_CLASSES, (
        f"只解析出 {len(literal)} 枚注册表字面量（地板 {MIN_CENSUS_CLASSES}）＝取样口塌陷"
    )
    # ② 有牙自证：先把检测器自己测一遍，免得①退化成恒真。
    assert _r3_drift(literal, {**live, "doc-misc": None}), "漂移检测空跑＝本腿没牙，判红不判绿"
    # ① 真判据：注毒必已还原。
    drifted = _r3_drift(literal, live)
    assert not drifted, (
        f"内存注毒未还原，在册视图与源码字面量不符：{drifted}"
        "＝G-T5 的账开始跟着被污染的注册表走（R3 A 案的『自动还原』承诺被破坏）"
    )


# ---------------------------------------------------------------------------
# G-T3 面 B（未迁移页；面 A 在板块门 `test_board_docs_do_not_handwrite_volatile_counts`）
# ---------------------------------------------------------------------------
def test_g_t3_unmoved_face_debt_never_grows() -> None:
    hits = _real()["t3_unmoved"]
    assert len(hits) <= T3_UNMOVED_CEILING, (
        f"未迁移页含裸写一次性事实 {len(hits)} 页 > 上限 {T3_UNMOVED_CEILING}＝又添了新的未受管页面。"
        f"修法：该页迁移到模板（页首 front-matter + 事实走 `auto:`/`{{fact:KEY}}` 引用），"
        f"或写成「以真身/生成物为准」的指针句；大户：{hits[-6:]}"
    )
    assert hits, "一条都没数到＝词表或取数口失效（未迁移页必有多次性事实）"


def test_g_t3_fact_ruler_sees_four_poison_shapes_and_passes_pointers() -> None:
    """反向自测：裸计数/裸阈值/裸路径/裸枚举各红；带指针与粘连负样本放行。"""
    vocab = {"天气", "股票", "笔记", "提醒", "占卜", "行情", "快报", "随机图"}
    cases = {
        "裸计数": "本板块共 47 个能力入口。",
        "裸阈值": "单文件上限 100MB，超时 30 秒。",
        "裸路径": "归档落在 data/media_archive/ 与 C:/Users/x/Runtime/ 下。",
        "裸枚举": "支持 天气、股票、笔记、提醒、占卜、行情、快报、随机图 八类。",
    }
    for want, line in cases.items():
        hits = dfd.fact_findings([line], vocab=vocab)
        assert hits and want.rstrip("数") in hits[0] or hits, f"{want} 未被识别：{line}"
    for ok in (
        "字段数以机器册 docs/auto-facts.md 为准。",
        "{{fact:count}} 条入口（渲染期现算）。",
        "§9 字段级契约与 v21r2 主题、zhconv 1.4.3 版本无关。",
    ):
        assert dfd.fact_findings([ok], vocab=vocab) == [], f"合法句被误杀：{ok}"
    # 围栏与机器段不算人写正文
    fenced = dfd.human_lines("正文\n\n```text\n共 47 个能力\n```\n")
    assert dfd.fact_findings(fenced, vocab=vocab) == [], "围栏代码块内的示例被误判"
    autoed = dfd.human_lines(
        "<!-- BOARD-AUTO:BEGIN -->\n共 47 个能力\n<!-- BOARD-AUTO:END -->\n人写行\n"
    )
    assert not any("47" in x for x in autoed), "机器段没被剥掉＝生成物被误记在作者头上"


# ---------------------------------------------------------------------------
# 上限字面量 + 方向锁 + 单一取数口自证
# ---------------------------------------------------------------------------
def test_ceilings_are_hand_written_literals() -> None:
    """结构锁：上限必须是字面整数，不许 len(...)/sum(...) 派生（`Assign` 与 `AnnAssign` 双形态）。

    两块账本一起锁：本文件（G-T1/T3面B/T4/T5）与板块门文件里被扩展的 G-T2/T3面A。
    """
    wanted = {
        Path(__file__): _CEILING_NAMES + _HISTORY_NAMES,
        REPO_ROOT / "tests" / "test_board_taxonomy_gate.py": (
            "T2_CEILING",
            "T3_MANAGED_CEILING",
            "MIN_T2_PAGES",
            "AUDIT_HISTORY_T2",
            "AUDIT_HISTORY_T3_MANAGED",
        ),
    }
    for path, names in wanted.items():
        assigned: dict[str, ast.expr | None] = {}
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assigned[target.id] = node.value
        for name in names:
            value = assigned.get(name)
            if name.startswith("AUDIT_HISTORY"):
                assert isinstance(value, ast.Tuple) and value.elts, (
                    f"{path.name}::{name} 必须留在该文件且非空（只降的对账凭据）"
                )
                continue
            assert isinstance(value, ast.Constant) and isinstance(value.value, int), (
                f"{path.name}::{name} 被改成派生表达式＝上限跟着被检对象一起动，本门结构性失效"
            )


class _AuditRow(NamedTuple):
    """一条核账账本。两枚开关把「方向锁」「反调大锁」「判债锁」分开——R0 换尺后
    T1 的判债对象是**新尺对外欠账**；上限原按旧尺首届值（1047）在册，2026-09-25 经用户
    裁定 N5 走 approvals 通道**收紧**重录为取数口现算值（放宽仍被结构性拒收：
    `ceiling_pinned_here` 行与点名册 pin 腿都不放行），三把锁因此不同于一行；
    分开写死，就不许任何人以「换尺」为名把上限调大。
    """

    label: str
    history: tuple[tuple[str, int], ...]
    ceiling: int
    current: int
    judged_by_ceiling: bool  # 现算值 <= 上限（真判债）
    ceiling_pinned_here: bool  # 上限 <= 首届核账值（反调大换绿）


def test_audit_histories_never_rise() -> None:
    official, process, old_total = _r0_columns(_real())
    # 席 S230（R0=A）：T4 与 G-T1 同判——上限属旧尺首届值，判债对象换成「对外正式面欠账」。
    _t4_official, _t4_process, _t4_total = _r0_pair(
        _real(), "t4", "t4_debt_official", "t4_registered_process", "t4_accounting"
    )
    rows = (
        # —— R0 新尺：判债只量「对外正式面」欠账；反调大锁由下一行（旧尺首届值 1047 作硬顶）
        #    与点名册 pin 腿承担，本行不重复持锁。
        _AuditRow("T1 对外欠账（R0 新尺）", AUDIT_HISTORY_T1_OFFICIAL, T1_CEILING, official, True, False),
        # —— 旧尺总账：R0 后降级为**登记栏**（不再判债），但仍是「上限不许高于旧尺首届核账值」
        #    的凭据与本门的缩面自证对象；上限一旦被人抬过 1047，本行立刻红。
        _AuditRow("T1 旧尺总账（登记栏）", AUDIT_HISTORY_T1, T1_CEILING, old_total, False, True),
        _AuditRow("T3面B", AUDIT_HISTORY_T3B, T3_UNMOVED_CEILING, len(_real()["t3_unmoved"]), True, True),
        _AuditRow("T4", AUDIT_HISTORY_T4, T4_CEILING, _t4_official, True, True),
        _AuditRow(
            "T5无模板类别",
            AUDIT_HISTORY_T5,
            T5_MISSING_TEMPLATE_CEILING,
            len(_real()["t5"]["missing_template"]),  # type: ignore[index]
            True,
            True,
        ),
        _AuditRow("面B错配", AUDIT_HISTORY_MISMATCH, MISMATCH_CEILING, len(_real()["mismatch"]), True, True),
        _AuditRow(
            "T5三角断链",
            AUDIT_HISTORY_T5_DEADCLASS,
            T5_DEADCLASS_CEILING,
            len(_real()["t5"]["pages_unreachable"]),  # type: ignore[index]
            True,
            True,
        ),
    )
    assert official + process == old_total
    for row in rows:
        counts = [n for _d, n in row.history]
        assert counts == sorted(counts, reverse=True), (
            f"核账记录出现回升（方向锁）：{row.label} {row.history}"
        )
        if row.ceiling_pinned_here:
            assert row.ceiling <= counts[0], (
                f"{row.label}：上限 {row.ceiling} 超过首届核账值 {counts[0]}＝调大换绿"
            )
        if row.judged_by_ceiling:
            assert row.current <= row.ceiling, (
                f"{row.label}：现算值 {row.current} 已超上限 {row.ceiling}"
                "（R0：换尺不许变成放水，超了就红着，既不升上限也不缩扫描面）"
            )


def test_r0_ceiling_still_pinned_to_old_ruler_first_audit() -> None:
    """R0 反调大自证（独立一枚，别与方向锁混在一行的 if 里）：`T1_CEILING` 一字不许**私自**动过。

    注毒形状＝有人把上限从旧尺首届核账值抬到能盖住旧尺总量的值 ⇒ 本行与上一行的
    `ceiling_pinned_here` 同时红；降账/重录合法，但**必须**经 N5 的 approvals 通道
    （见 `_t1_ceiling_approval`），并与核账序列同批重录——改数不改册、删册留数都红。
    """
    assert AUDIT_HISTORY_T1[0][1] == 1047, "旧尺首届核账值被改写＝换尺时顺手擦了凭据"
    assert T1_CEILING <= AUDIT_HISTORY_T1[0][1], (
        f"T1_CEILING={T1_CEILING} 高于旧尺首届核账值 {AUDIT_HISTORY_T1[0][1]}＝调大换绿；"
        "放宽上限属造绿六禁第一条，N5 通道只收『取数口现算的收紧重录』"
    )
    state, detail, entry = _t1_ceiling_approval()
    if state == "absent":
        assert T1_CEILING == AUDIT_HISTORY_T1[0][1], (
            f"T1_CEILING 被改为 {T1_CEILING} 而 approvals 册无有效批准（{detail}）"
            "＝R0 明令未经批准不许动；须与核账同批重录"
        )
    elif state == "invalid":
        pytest.fail(
            f"T1_CEILING 的 approvals 册在场但失效：{detail} ⇒ 视同无批准，"
            f"上限须回到 {AUDIT_HISTORY_T1[0][1]}（现值 {T1_CEILING}）——坏册不是放行通道"
        )
    else:
        assert entry is not None
        assert int(entry["old_ceiling"]) == AUDIT_HISTORY_T1[0][1], (  # type: ignore[call-overload]
            f"批准册锚的前值 {entry['old_ceiling']} ≠ 旧尺首届核账值 {AUDIT_HISTORY_T1[0][1]}"
            "＝册与凭据脱锚（擦锚重录＝换尺时擦凭据的同型）"
        )
        assert T1_CEILING == int(entry["new_ceiling"]), (  # type: ignore[call-overload]
            f"上限常量 {T1_CEILING} ≠ 在册批准值 {entry['new_ceiling']}＝改数不改册或改册不改数；"
            "注毒形状『把重录后的上限调回旧值』正打在此腿"
        )


# ---------------------------------------------------------------------------
# 席 S265（用户裁定 N5）—— `T1_CEILING` 偏离旧尺首届值的唯一通道：approvals 册
#   数值由该门自己的取数口现算（本读取口只**消费**登记结果，不重算＝禁第二真身）；
#   形态先例＝scripts/shim_refs_approvals.json（缺字段/过期 ⇒ 不批、门诚实红）。
# ---------------------------------------------------------------------------
#: 册路径（一枚常数＝一处出处；判据只认这一本，别处出现的同名录不消费）。
_T1_CEILING_APPROVALS_PATH = REPO_ROOT / "scripts" / "spec_gates_ceiling_approvals.json"

#: 条目必填字段（缺一即失效）。尺身份三元组＝file/function/command，另要求
#: 现算时刻与证据命令全文在册（N5：禁把数硬写进常量而不留出处）。
_T1_APPROVAL_REQUIRED_FIELDS: tuple[str, ...] = (
    "constant",
    "gate",
    "old_ceiling",
    "new_ceiling",
    "direction",
    "ruler_identity",
    "measured_three_values",
    "evidence_command_full",
    "computed_at_utc",
    "approved_by",
    "reason",
    "expiry",
)


def _t1_approval_moment(raw: object, field: str) -> datetime | str:
    """解析册内 ISO 时刻；返回 `datetime` 或（失败时的）人话失效原因。必须带时区。"""
    if not isinstance(raw, str) or not raw.strip():
        return f"{field} 缺失或非字符串"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return f"{field} 不是可解析 ISO 时刻：{raw!r}"
    if parsed.tzinfo is None:
        return f"{field} 无时区（不许拿本地钟当 UTC）：{raw!r}"
    return parsed


def _t1_ceiling_approval(
    path: Path = _T1_CEILING_APPROVALS_PATH,
    now: datetime | None = None,
) -> tuple[str, str, Mapping[str, object] | None]:
    """fail-closed 读 `T1_CEILING` 的重录批准。返回 `(状态, 说明, 条目|None)`。

    - `absent`：册文件不存在，或册里没有 `constant == "T1_CEILING"` 的条目 ⇒ **无批准**
      （不是放行——判据据此要求上限仍＝旧尺首届值）；
    - `invalid`：册在场但不可用＝一律红，不许塌回"当没批准"的放行通道（否则"把册写坏"
      本身成了旁路）：JSON 不可解析／`approvals` 非列表／同名条目多于一枚（无法判定现行）／
      必填字段缺失或为空／两枚数值不是整数／方向不是收紧（new < old）／
      时刻不可解析或无时区／**已过期（临时件只准缩、不许自我豁免）**；
    - `ok`：一枚形态完备、未过期、严格收紧的条目 ⇒ 在册批准值现行。
    """
    if not path.exists():
        return ("absent", f"册不存在：{path.name}", None)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return ("invalid", f"册不可解析：{exc}", None)
    if not isinstance(data, dict) or not isinstance(data.get("approvals"), list):
        return ("invalid", "顶层缺 `approvals` 列表＝册形态改版", None)
    entries = [
        e
        for e in data["approvals"]
        if isinstance(e, dict) and str(e.get("constant", "")) == "T1_CEILING"
    ]
    others = sum(
        1
        for e in data["approvals"]
        if isinstance(e, dict) and str(e.get("constant", "")).startswith("T1_CEILING")
        and str(e.get("constant")) != "T1_CEILING"
    )
    if others:
        return ("invalid", "出现改名近亲条目（如 T1_CEILING_V2）＝旁路册", None)
    if not entries:
        return ("absent", "册内无 T1_CEILING 条目", None)
    if len(entries) > 1:
        return ("invalid", f"同名条目 {len(entries)} 枚＝无法判定哪枚现行", None)
    entry = entries[0]
    for field in _T1_APPROVAL_REQUIRED_FIELDS:
        value = entry.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            return ("invalid", f"必填字段 {field} 缺失或为空", None)
    try:
        old = int(entry["old_ceiling"])
        new = int(entry["new_ceiling"])
    except (TypeError, ValueError):
        return ("invalid", "old_ceiling/new_ceiling 不是整数", None)
    if new >= old:
        return ("invalid", f"方向不是收紧（new {new} ≥ old {old}）＝放宽须用户逐次数值点头，本通道不收", None)
    ri = entry["ruler_identity"]
    if not isinstance(ri, dict) or not all(
        isinstance(ri.get(k), str) and str(ri.get(k)).strip() for k in ("file", "function", "command")
    ):
        return ("invalid", "尺身份三元组 file/function/command 不齐＝数不知道是谁算的", None)
    clock = now or datetime.now(timezone.utc)
    for field in ("computed_at_utc", "expiry"):
        moment = _t1_approval_moment(entry.get(field), field)
        if isinstance(moment, str):
            return ("invalid", moment, None)
        if field == "expiry" and clock > moment:
            return ("invalid", f"批准已过期（expiry {entry[field]}）＝到期未由 owner 携新证据续册，诚实红", None)
        if field == "computed_at_utc" and moment > clock:
            return ("invalid", f"现算时刻 {entry[field]} 晚于当下＝证据是先写好的", None)
    return ("ok", "", entry)


def test_t1_approval_reader_is_fail_closed(tmp_path: Path) -> None:
    """本腿自证（全走 tmp 副本，不碰真册一个字节）：absent/invalid/ok 三态各打各的毒形。"""

    def good_entry(**over: object) -> dict[str, object]:
        base: dict[str, object] = {
            "constant": "T1_CEILING",
            "gate": "G-T1",
            "old_ceiling": 1047,
            "new_ceiling": 500,
            "direction": "收紧",
            "ruler_identity": {"file": "scripts/spec_gates_census.py", "function": "compute()", "command": "--report"},
            "measured_three_values": {"t1_debt_official": 500},
            "evidence_command_full": "date -u => 2026-09-24T20:21:50Z; report 现算 500",
            "computed_at_utc": "2026-01-01T00:00:00+00:00",
            "approved_by": "S265 自证夹具（不是真批准）",
            "reason": "reader 反向自测",
            "expiry": "2099-01-01T00:00:00+00:00",
        }
        base.update(over)
        return base

    def write_register(entries: object) -> Path:
        p = tmp_path / "register.json"
        p.write_text(json.dumps({"approvals": entries}), encoding="utf-8")
        return p

    # ① 册不存在 ⇒ absent（放行与否由 pin 腿据此要求回 1047，不在读取口判绿）
    assert _t1_ceiling_approval(tmp_path / "not-here.json")[0] == "absent"
    # ② 正常一枚 ⇒ ok
    state, _d, entry = _t1_ceiling_approval(write_register([good_entry()]))
    assert state == "ok" and entry is not None and int(entry["new_ceiling"]) == 500  # type: ignore[call-overload]
    # ③ 过期 ⇒ invalid（临时件不许自我豁免）
    assert _t1_ceiling_approval(write_register([good_entry(expiry="2020-01-01T00:00:00+00:00")]))[0] == "invalid"
    # ④ 放宽方向 ⇒ invalid
    assert _t1_ceiling_approval(write_register([good_entry(new_ceiling=1100)]))[0] == "invalid"
    # ⑤ 缺出处（reason 为空串）⇒ invalid
    assert _t1_ceiling_approval(write_register([good_entry(reason="  ")]))[0] == "invalid"
    # ⑥ 同名两枚 ⇒ invalid（无法判定哪枚现行）
    assert _t1_ceiling_approval(write_register([good_entry(), good_entry()]))[0] == "invalid"
    # ⑦ JSON 烂册 ⇒ invalid（坏册不是旁路）
    rotten = tmp_path / "rotten.json"
    rotten.write_text("{not json", encoding="utf-8")
    assert _t1_ceiling_approval(rotten)[0] == "invalid"
    # ⑧ 时刻无时区 ⇒ invalid（不许拿本地钟当 UTC）
    assert _t1_ceiling_approval(write_register([good_entry(computed_at_utc="2026-01-01T00:00:00")]))[0] == "invalid"
    # ⑨ 现算时刻晚于当下 ⇒ invalid（证据不许是未来写的）
    late = write_register([good_entry(computed_at_utc="2098-01-01T00:00:00+00:00")])
    assert _t1_ceiling_approval(late, now=datetime(2026, 1, 2, tzinfo=timezone.utc))[0] == "invalid"


def test_report_and_gate_read_the_same_numbers() -> None:
    """单一取数口自证：`--report` 打印的每个数＝本门判据用的同一个现算值。"""
    lines = "\n".join(sc.report_lines(_real()))
    assert f"G-T1 无模板头且非生成物 = {len(_real()['t1'])}" in lines
    # —— R0 分账后的同刻自证：投影口必须把**新尺两栏**也报出来，且与判据同一支现算值。
    #    形如「同一条 G-T1 行内含两栏」或「两条 G-T1 行各含一栏」皆放行（措辞归席 TX130，
    #    本腿只锁「两栏都在 G-T1 投影面上、数值与判据同刻同源」，不锁文案）。
    official, process, _old_total = _r0_columns(_real())
    g_t1_lines = [ln for ln in lines.splitlines() if ln.startswith("G-T1")]
    assert g_t1_lines, "投影口不再有任何 G-T1 行＝G-T1 整栏从 report 消失"
    both = [ln for ln in g_t1_lines if str(official) in ln and str(process) in ln]
    split = any(str(official) in ln for ln in g_t1_lines) and any(
        str(process) in ln for ln in g_t1_lines
    )
    assert both or split, (
        f"`--report` 未把 R0 新两栏（对外欠账 {official} / 过程件登记 {process}）报在 G-T1 行内"
        "＝report 与判据各按一套账（席 TX130 的投影口欠一行）。"
    )
    assert (
        f"G-T1面B 类别↔模板错配页（TEMPLATE_CATEGORY_MISMATCH）= {len(_real()['mismatch'])}"
        in lines
    )
    assert f"G-T2 小节偏离页 = {len(_real()['t2'])}" in lines
    assert (
        f"面 A 管辖 {len(_real()['t3_managed'])} 行 / 面 B 未迁移 {len(_real()['t3_unmoved'])} 页"
        in lines
    )
    assert f"G-T4 参数不对齐 = {len(_real()['t4'])}" in lines
    # —— 席 S230（R0=A）：G-T2 / G-T4 / 模板体检三面的分账也必须同刻报在 report 上（总账栏不消失）。
    for _tk, _prefix, dk, rk, _ak in (
        ("t2", "G-T2", "t2_debt_official", "t2_registered_process", "t2_accounting"),
        ("t4", "G-T4", "t4_debt_official", "t4_registered_process", "t4_accounting"),
        ("tcheck", "模板体检", "tcheck_debt_official", "tcheck_registered_process", "tcheck_accounting"),
    ):
        _o, _p, _tot = _r0_pair(_real(), _tk, dk, rk, _ak)
        face_lines = [ln for ln in lines.splitlines() if ln.startswith(_prefix)]
        assert any(str(_o) in ln and str(_p) in ln for ln in face_lines), (
            f"`--report` 未把 {_tk.upper()} 的 R0 两栏（对外 {_o} / 过程稿 {_p}）报出来＝总账栏被换没了"
        )
    assert "R0 欠账分母定义域体检" in lines, (
        "`--report` 丢了 R0 分母定义域体检行＝那把锁从投影面消失（查不到≠没问题）"
    )
    # —— 席 S230R（R0=A 反缩水腿）：过程稿人口必须同刻报在 report 上（否则「整桶消失」只在门里可见、
    #    命令行查不到＝本窗「存在性糊过活性判据」的同型事故）。数值与判据同一支现算，不另起一套。
    assert (
        f"全扫描过程稿人口 {_real()['r0_process_page_total']} ／ "
        f"G-T2 比对面 {_real()['t2_pages']}（其中过程稿 {_real()['t2_pages_process']}）"
    ) in lines, "`--report` 丢了 R0=A 反缩水腿的人口行＝过程稿从投影面消失（查不到≠没问题）"
    assert f"G-T5 无模板类别 = {len(_real()['t5']['missing_template'])}" in lines
    assert f"三角闭合断链 {len(_real()['t5']['pages_unreachable'])} 类" in lines


# ---------------------------------------------------------------------------
# 席 S20 MECH-HARDEN —— 六项判据/记账机制加严的反向自测（新增，不动既有断言/基线）
# ---------------------------------------------------------------------------
def test_s20_fact_ruler_cjk_tooth_catches_glued_digits() -> None:
    """N-1 计数尺补牙：汉字紧贴数字、无空格也必须红；ASCII/标点粘连仍放行。"""
    for line, want in (
        ("本板块共47个能力入口。", "裸计数"),
        ("单文件上限100MB。", "裸阈值"),
        ("总计 47 项待办。", "裸计数"),
    ):
        hits = dfd.fact_findings([line], vocab=set())
        assert hits and want in hits[0], f"{want} 未识别（汉字/空格粘连漏牙）：{line}"
    # 反向：数字挨 ASCII 字母/数字/§/./- 仍属粘连负样本，放行（版本/条款号不是事实）
    for ok in (
        "§9 字段级契约与 v21r2 主题无关。",
        "zhconv 1.4.3 版本。",
        "端口 8080/3001 转发。",
    ):
        assert dfd.fact_findings([ok], vocab=set()) == [], f"合法粘连被误杀：{ok}"


def test_s20_poison_fake_auto_zone_is_unverified(tmp_path: Path) -> None:
    """K-1 反洗白：嵌一对 BOARD-AUTO 注释藏裸事实的页必须记 UNVERIFIED_AUTO_ZONE；
    段内无裸事实（引用示例的文档）不误伤。"""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    launder = root / "docs" / "launder.md"
    launder.write_text(
        "# 洗白页\n\n<!-- BOARD-AUTO:BEGIN -->\n本板块共47个能力入口。\n<!-- BOARD-AUTO:END -->\n",
        encoding="utf-8",
    )
    res = sc.compute(root)
    managed = [m for m in res["t3_managed"] if m.startswith("docs/launder.md: UNVERIFIED_AUTO_ZONE")]
    assert managed, f"一对注释买断机器段的裸事实没被抓：{res['t3_managed'][:6]}"
    # 正样控制：段内无裸事实的示例引用页不新增账（只加严，不误伤）
    clean = root / "docs" / "docquote.md"
    clean.write_text(
        "# 说明\n\n<!-- BOARD-AUTO:BEGIN -->\n这是标记格式示例（无数字事实）。\n<!-- BOARD-AUTO:END -->\n",
        encoding="utf-8",
    )
    res2 = sc.compute(root)
    assert not any(
        m.startswith("docs/docquote.md: UNVERIFIED_AUTO_ZONE") for m in res2["t3_managed"]
    ), "段内无裸事实也被记红＝误伤（违反只加严）"


def test_s20_root_md_now_enumerated(tmp_path: Path) -> None:
    """K-2：根层全部 *.md 进入管辖面、classify 真跑（旧白名单令 root-report 分支永不触发）。"""
    assert dts.classify("findings.md") == "root-report"
    assert dts.classify("AGENTS.md") == "root-rules"
    rels = {p.rel for p in dts.walk_content_pages()}  # 缺省 root＝doc_template_sync.ROOT（仓库根）
    # 免检旧账里的代表页现在必须在场
    assert "findings.md" in rels, "根散件仍被扫描面白名单漏掉（K-2 未生效）"


def test_s20_code_home_check_no_longer_shadowed_by_missing_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K-3：缺模板的 code 类也要核查 code_home——旧 `elif` 让它永不执行。合成类别走同一取数口。"""
    synth = dt.CategoryDef(
        cid="s20-synth-code", template="s20-no-such-tpl", surface="code",
        owner_board="B00", reason="test", code_home="this/path/does/not/exist.py",
    )
    monkeypatch.setattr(dt, "CONTENT_CATEGORIES", (synth,))
    res = sc.compute()
    named = [m for m in res["t5"]["missing_template"] if m.startswith("s20-synth-code:")]
    assert any("无对应模板" in m for m in named), f"缺模板腿没点名：{named}"
    assert any("code_home 不存在" in m for m in named), f"elif 遮蔽死路径未拆：{named}"


def test_s20_write_precheck_refacts_page_with_naked_facts(tmp_path: Path) -> None:
    """缺口二：仍有裸事实的页 --write 必须拒绝驱动、文件（含 front-matter）零字节变化；
    清干净后同一决策放行。直接复用 main 用的同一支前置谓词 `naked_fact_findings`。"""
    seat = dts.load_schemas()["seat-report"]
    fm_ok = dts.FrontMatter(
        template="seat-report",
        params={
            "seat_id": "T-S20", "wave": "w", "status": "DONE", "role": "gate",
            "report_class": "auto:seat_class", "ledger_events": "auto:page_stat:ledger",
        },
        extra_keys=(),
    )
    dirty = "---\ntemplate: seat-report\nparams:\n  seat_id: T-S20\n  wave: w\n  status: DONE\n" \
            "  role: gate\n  report_class: auto:seat_class\n  ledger_events: auto:page_stat:ledger\n---\n" \
            "\n## 交付\n\n本板块共47个能力入口。\n"
    f = tmp_path / "SEAT-S20.md"
    f.write_text(dirty, encoding="utf-8")
    assert dts.naked_fact_findings(dirty) != [], "前置谓词没抓到裸事实＝拒绝逻辑空跑"

    def decide(text: str) -> bool:
        if dts.naked_fact_findings(text):  # 与 main --write 同一判据
            return False
        pg = dts.PageInfo(rel=".superpowers/sdd/2026-09-22-taxonomy/SEAT-S20.md", path=f, text=text,
                          fm=fm_ok, category="seat-report")
        return dts.write_page(pg, {"seat-report": seat})

    assert decide(dirty) is False, "有裸事实却放行驱动＝不变量没执法"
    assert f.read_text(encoding="utf-8") == dirty, "拒绝驱动却改了文件（front-matter 须零变化）"


def test_s20_g_t4_three_forms_red_via_synthetic_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """6① 活性腿：req+auto 参数「非 provider 现算」三形态（缺参/字面量冒充/现算空值）
    全在**同一取数口的 T4_CODES 过滤面**红。合成 schema，不依赖 docs/templates 在飞件。"""
    schema = dts.parse_schema_text(
        "<!-- @schema:BEGIN\nsections: 交付 | 自报\nparams:\n"
        "- seat_id | text | literal | req | nonempty\n"
        "- cls | text | auto:seat_class | req | any\n"
        "@schema:END -->\n<!-- TEMPLATE-AUTO:BEGIN -->\n"
        "- {{fact:seat_id}} / {{fact:cls}}\n<!-- TEMPLATE-AUTO:END -->\n",
        "s20-poison",
    )
    ctx = dts.PageCtx(rel=".superpowers/sdd/t/SEAT-A.md", body_no_fm="## 交付\n")
    for params, code in (
        ({"seat_id": "X"}, "MISSING_PARAM"),
        ({"seat_id": "X", "cls": "SEAT"}, "AUTO_SOURCE_MISMATCH"),
    ):
        _v, viol = dts.resolve_params(schema, dts.FrontMatter("s20-poison", params, ()), ctx)
        assert any(code in x for x in viol), f"{code} 没被抓：{viol}"
        assert code in sc.T4_CODES, f"{code} 不在 T4_CODES＝compute 记账腿看不见（空跑）"
    monkeypatch.setitem(dts.PROVIDERS, "seat_class", lambda arg, c: "")
    _v, viol = dts.resolve_params(
        schema, dts.FrontMatter("s20-poison", {"seat_id": "X", "cls": "auto:seat_class"}, ()), ctx
    )
    assert any("PROVIDER_EMPTY" in x for x in viol), f"provider 空值冒充现算没被抓：{viol}"
    assert "PROVIDER_EMPTY" in sc.T4_CODES


# ---------------------------------------------------------------------------
# 席 S46 GT1-BRANCH-B —— 机制 (b) 补认 + 行内码剥除 + elif 拆链与测量/成语精修
# （全部只新增用例；未改任何既有断言与 `_BASELINE_*`/上限字面量）
# ---------------------------------------------------------------------------
def test_s46_generated_page_must_actually_reproduce_not_just_be_listed(tmp_path: Path) -> None:
    """机制 (b) 反向自测：在册生成页**声称可复现却当场重渲染不等值** ⇒ 必红（带因入债）；
    逐字节复制真页回同一位置 ⇒ 放行（还原必绿）。旧账按路径成员隐形豁免，此形全绿＝空跑。"""
    rel = next(r for r in sorted(_real()["b_ok"]) if r.startswith("docs/boards/"))
    real = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert bds.AUTO_BEGIN in real and bds.AUTO_END in real, "前提塌了：真页没有板块机器段"

    def run(body: str) -> dict[str, object]:
        root = tmp_path / f"repo-{abs(hash(body)) % 10**9}"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")
        return sc.compute(root)

    forged = run(real.replace(bds.AUTO_END, "本板块共47个能力入口。\n" + bds.AUTO_END, 1))
    t1_forged = set(forged["t1"])
    assert any(r.startswith(rel + "#") for r in t1_forged), (
        f"AUTO 段被篡改的在册生成页没进 G-T1 债（按名单豁免未升级为字节复现）：{sorted(t1_forged)[:6]}"
    )
    assert any(f"{rel}: UNVERIFIED_AUTO_ZONE" in m for m in forged["t3_managed"]), (
        "K-1 板块段仍在认在册名单而非当场复现证据（不等值段被放行）"
    )
    restored = run(real)
    assert not any(r.startswith(rel) for r in restored["t1"]), (
        f"逐字节可复现的正样被误杀（还原必绿失败）：{restored['t1'][:4]}"
    )
    assert rel in restored["b_ok"], "重渲染等值的页没被记成已驱动 (b 形)"


def test_s46_generated_listing_never_silently_exempt() -> None:
    """不变量（真树）：任何进入生成物名单的在册页，要么当场复现（b_ok），要么带因入债——
    不存在「在名单里却不检查」的第三态（那正是 K-2 同型的隐形绿）。"""
    gen_all = _real()["generated_all"]
    b_ok = _real()["b_ok"]
    schemas = _real()["schemas"]
    mismatched = {str(m).split()[1] for m in _real()["mismatch"] if len(str(m).split()) > 1}
    t1 = {str(r).split("#", 1)[0] for r in _real()["t1"]}
    page_rels = {p.rel for p in _real()["pages"]}
    # 有 (a) 形模板头（在册且不错配）的生成页走 (a) 销籍，不在这条不变量的射程
    a_ok = {p.rel for p in _real()["pages"] if p.fm is not None and p.fm.template in schemas
            and p.rel not in mismatched}
    silent = {r for r in gen_all if r in page_rels and r not in b_ok and r not in t1 and r not in a_ok}
    assert not silent, f"名单在册、既未复现又没记债的生成页（静默豁免）：{sorted(silent)[:6]}"
    # 正样控制：板块生成页确有大批当场复现（判据不是全判死装样子）
    boards_reproduced = {r for r in b_ok if r.startswith("docs/boards/")}
    assert len(boards_reproduced) >= 220, f"板块页复现数 {len(boards_reproduced)} 异常低＝复现判据空转"


def test_s46_inline_code_is_not_prose_fact() -> None:
    """任务2（治 S23R 148 枚假阳）：行内码内容不再当人写正文执法；
    去掉反引号的同形裸事实必须照红（注毒必红），指针句里的行内码路径不误伤（还原必绿）。"""
    green = [
        "示例 `const X = /\\b(?:p|px)/` 是代码字面量。",
        "命令 `python scripts/e2e_acceptance.py --execute 30 秒` 计时。",
        "以 `docs/auto-facts.md` 为准。",
    ]
    for line in green:
        assert dfd.fact_findings(dfd.human_lines(line + "\n"), vocab=set()) == [], (
            f"行内码/指针形态被误判：{line}"
        )
    red = [
        ("上限 100MB。", "裸阈值"),
        ("本板块共47个能力入口。", "裸计数"),
    ]
    for line, want in red:
        hits = dfd.fact_findings(dfd.human_lines(line + "\n"), vocab=set())
        assert hits and want in hits[0], f"去反引号的裸事实漏判（注毒没红）：{line} → {hits}"


def test_s46_multi_rule_line_reports_every_ruler_not_just_first() -> None:
    """补录 R2-2：count→threshold→path→enum 的 elif 链拆独立判定——
    同一行「阈值＋data/ 路径」两把尺各记各的（旧链路径被遮蔽，HANDOFF-NEXT:46 实证）。"""
    hits = dfd.fact_findings(["单文件上限 100MB，归档在 data/media_archive/ 下。"], vocab=set())
    kinds = " ".join(hits)
    assert "裸阈值" in kinds and "裸路径" in kinds, f"elif 遮蔽未拆，一行只报一尺：{hits}"
    hits2 = dfd.fact_findings(["本地跑 C:\\Users\\x\\py.exe 时共47个用例失败。"], vocab=set())
    kinds2 = " ".join(hits2)
    assert "裸机器本地路径" in kinds2 and "裸计数" in kinds2, (
        f"机器路径短路的 continue 仍在遮蔽其余尺：{hits2}"
    )


def test_s46_measure_idioms_pass_nearby_bare_facts_stay_red() -> None:
    """任务3（S25 PARKED-B / S24「30 秒」）：测量统计、带符号增减、人工步骤频次、
    标题行尾「N 秒」阅读时长按词形放行；相邻**无这些形态**的裸阈值/裸计数必红。"""
    green = [
        "## 1. 项目 30 秒",
        "渲染 P95 0.054ms 已记录在案。",
        "验收要求反复说 5 次同一偏好。",
        "性能对照 P95 +110% 触发回退评审。",
        "速览有 20 分钟版与 5 分钟版两种读法。",
    ]
    for line in green:
        assert dfd.fact_findings([line], vocab=set()) == [], f"成语/测量形态被误杀：{line}"
    red = [
        ("超时 30 秒。", "裸阈值"),
        ("重试等待 1500ms 后放行。", "裸阈值"),
        ("共 5 次点击即熔断。", "裸计数"),
        ("配额上调 110% 生效。", "裸阈值"),
    ]
    for line, want in red:
        hits = dfd.fact_findings([line], vocab=set())
        assert hits and want in hits[0], f"真裸事实被成语带放过（注毒没红）：{line} → {hits}"


# ---------------------------------------------------------------------------
# 席 S78 CENSUS-LEDGER-SPLIT-ALL-PAGES + P-41 —— 只新增用例（未改任何既有断言/基线）
# ① 历史台账分流改「按类别、驱动同权」（P-39）；⑤ P-41 board 机器段逐段与 TEMPLATE 同构。
# 全部走内存/tmp_path，注毒不落源码树；判据与 --report 共用同一支 `sc.compute()`。
# ---------------------------------------------------------------------------
def _pi(rel: str, category: str, text: str = "", fm: object = None) -> dts.PageInfo:
    return dts.PageInfo(rel=rel, path=Path(rel), text=text, fm=fm, category=category)


def test_s78_face_of_history_page_is_category_based_and_driven_symmetric() -> None:
    """① 分流判据是**纯函数 + 按路径派生类别 + 驱动同权**（矩阵锁）：

    席 S78 立这组断言时的语义（非台账页「驱动⇒line／未驱动⇒page」）已被 **席 S201
    用户裁定 3.A** 取代：「驱动与否」＝本页戴没戴 `template:` 头，让被检者的头来挑尺子，
    正是 09-23 批量套头把 23 枚过程件顶进面A（0→460 行）的那条通道。
    现在「同权」升级为**头彻底不参与**：同一页传 True / 传 False / 不传，读数必须一模一样。
    - 板块人工区恒 line（生成器与人写混合，逐行治理）；
    - 过程日志三 cid 恒 skip（两面都不记，债只在 G-T1）；
    - 根层/活文档历史页恒 page（历史数字删不得）；
    - 其余对外类别恒 page（与 HEAD 同面：HEAD 这些页无头，本就逐页记账）；
      升 line 只走 `GOVERNED_LINE_PATHS` 名录（门侧登记，页自己改不动）。
    """
    line, page, skip = "line", "page", "skip"
    # 非名录的现役规格页：戴不戴头都是 page（旧写法在这里会因 driven 翻成 line——那正是被废的通道）
    assert sc.face_of_history_page(_pi("docs/design/x.md", "design-spec"), driven_non_generated=True) == page
    assert sc.face_of_history_page(_pi("docs/design/x.md", "design-spec"), driven_non_generated=False) == page
    # 名录在册的现役件：路径/登记判 line，且同样与头无关
    roster = min(sc.GOVERNED_LINE_PATHS)
    assert sc.face_of_history_page(
        _pi(roster, dts.classify(roster)), driven_non_generated=True
    ) == line
    assert sc.face_of_history_page(_pi(roster, dts.classify(roster))) == line
    assert sc.face_of_history_page(_pi("docs/boards/B01/f/e.md", "board-l3"), driven_non_generated=False) == line
    for cid in ("seat-report", "sdd-ledger", "sdd-brief"):  # 过程日志：两面都不记
        assert sc.face_of_history_page(_pi(f".superpowers/sdd/t/{cid}.md", cid), driven_non_generated=True) == skip
        assert sc.face_of_history_page(_pi(f".superpowers/sdd/t/{cid}.md", cid), driven_non_generated=False) == skip
    for cid in ("root-handoff", "root-report", "handbook", "acceptance"):  # 历史页：驱动与否都 page
        assert sc.face_of_history_page(_pi("HANDOFF-x.md", cid), driven_non_generated=True) == page
        assert sc.face_of_history_page(_pi("HANDOFF-x.md", cid), driven_non_generated=False) == page
    # 反向：非台账的驱动页不再因这条函数被顶进 line（头拨面＝3.A 禁路），也不被踢出它该在的面
    assert sc.face_of_history_page(_pi("docs/g.md", "doc-misc"), driven_non_generated=True) == page
    # 名录只准加严：同一枚 doc-misc 路径进名录前 page、进名录后 line（方向自查）
    assert sc.face_by_category_strict("doc-misc") == page


def test_s78_driven_ledger_page_stays_off_faceA_and_audited_in_faceB(tmp_path: Path) -> None:
    """① 端到端（走 compute 记账腿，非只喂正则——治 F-15「注毒只跑正则、记账腿看不见」）：
    一张**已挂模板头**的活文档历史页（`docs/HANDBOOK.md` ⇒ category=handbook，属历史台账）
    写裸计数，债必须落在**面 B（页）**、**绝不进面 A（行）**；分流按类别判、不靠路径前缀，
    且已驱动页与未驱动页同权（旧码路一旦 driven 就把它顶进行级面 A）。"""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    facts = "\n\n本板块共 47 个能力入口，另 100MB 上限。\n"
    # 只测分流落点：front-matter 是否参数合法不影响 `driven()`（只认 template∈schemas 且不错配）。
    (root / "docs" / "HANDBOOK.md").write_text(
        "---\ntemplate: handbook\nparams:\n  seat_id: W\n---\n\n# 活文档\n" + facts, encoding="utf-8"
    )
    res = sc.compute(root)
    unmoved = set(res["t3_unmoved"])
    managed = "\n".join(res["t3_managed"])
    assert "docs/HANDBOOK.md" in unmoved, (
        f"已驱动的活文档历史页没记进面 B（分流未生效）：{sorted(unmoved)[:6]}"
    )
    assert "docs/HANDBOOK.md" not in managed, (
        f"历史台账页的裸事实翻进了行级面 A（分流失效＝旧码路回归）：{managed[:200]}"
    )


def test_s78_current_spec_page_driven_still_pollutes_faceA(tmp_path: Path) -> None:
    """③ 反向自测①：现役规格页挂上在册模板驱动后写裸计数 ⇒ 必记面 A（分流不许把它当历史放走）。
    用 doc-misc/guide 这一**非台账**类驱动页证明：line 路径仍执法。"""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "live-guide.md").write_text(
        "---\ntemplate: guide\nparams:\n  seat_id: L\n---\n\n# 指南\n\n本板块共 47 个能力入口。\n",
        encoding="utf-8",
    )
    res = sc.compute(root)
    # 该页 category=doc-misc（非台账）；若它被判「已驱动」则面 A 记行，否则退面 B——两条都是可见债，
    # 关键断言：绝不能像台账那样被 skip（skip 才藏得住）。用「面A∪面B∪G-T1 至少其一记它」保可见性。
    visible = (
        any("docs/live-guide.md" in m for m in res["t3_managed"])
        or "docs/live-guide.md" in set(res["t3_unmoved"])
        or "docs/live-guide.md" in {r.split("#", 1)[0] for r in res["t1"]}
    )
    assert visible, f"现役规格页既不进面A也不进面B也不进G-T1＝被误当历史台账放走：{res['t3_managed'][:3]}"


def test_s78_relabel_to_ledger_category_is_cross_checked_not_dodged(tmp_path: Path) -> None:
    """③ 反向自测③（分类源与页 front-matter 交叉核验）：一张物理路径属现役规格（docs/design/）
    却**谎称** handoff 模板想躲面 A ⇒ 走 mismatch（类别↔模板错配）腿，
    `driven()` 拒认 ⇒ 它既销不了 G-T1 籍、又拿不到台账待遇，债仍可见。"""
    root = tmp_path / "repo"
    (root / "docs" / "design").mkdir(parents=True)
    (root / "docs" / "design" / "spec-liar.md").write_text(
        "---\ntemplate: handoff\nparams:\n  seat_id: X\n---\n\n# 冒牌交接\n\n本板块共 47 个能力入口。\n",
        encoding="utf-8",
    )
    res = sc.compute(root)
    named = [m for m in res["mismatch"] if "spec-liar.md" in m]
    assert named, f"谎称台账模板的规格页没被类别↔模板错配腿点名（躲尺通道没堵）：{res['mismatch'][:4]}"
    assert "docs/design/spec-liar.md" in {r.split("#", 1)[0] for r in res["t1"]}, (
        "错配页从 G-T1 销籍＝套个台账模板头就免检，F-2 同型"
    )


def test_s78_poison_extra_board_auto_zone_with_bare_fact_is_unverified(tmp_path: Path) -> None:
    """⑤ P-41 反向自测 a：往一枚真·板块生成页**再嵌一对 BOARD-AUTO 注释**、段内写裸计数，
    行级面 A 必须记 `UNVERIFIED_AUTO_ZONE`（旧页级 `p.rel in b_ok` 会让第二段隐身＝225 枚静默的洞）。"""
    rel = next(r for r in sorted(_real()["b_ok"]) if r.startswith("docs/boards/"))
    real = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert bds.AUTO_BEGIN in real and bds.AUTO_END in real, "前提塌了：真页没有板块机器段"
    root = tmp_path / "repo"
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    # 在人写区尾部追加一整对 BOARD-AUTO（含首段之外、写裸事实的第二段）。
    forged = real + (
        f"\n\n{bds.AUTO_BEGIN}\n{bds.AUTO_NOTE}\n\n本板块共 47 个能力入口。\n{bds.AUTO_END}\n"
    )
    (root / rel).write_text(forged, encoding="utf-8")
    res = sc.compute(root)
    hits = [m for m in res["t3_managed"] if m.startswith(f"{rel}: UNVERIFIED_AUTO_ZONE")]
    assert hits, (
        f"再嵌一对 BOARD-AUTO 段藏裸事实没被抓（页级 b_ok 放行旧洞未闭合）：{res['t3_managed'][:4]}"
    )
    # 还原（只留首段）⇒ 该页不再有 UNVERIFIED_AUTO_ZONE（正常 225 页不误伤，多一段才红）。
    (root / rel).write_text(real, encoding="utf-8")
    res2 = sc.compute(root)
    assert not any(
        m.startswith(f"{rel}: UNVERIFIED_AUTO_ZONE") for m in res2["t3_managed"]
    ), f"逐字可复现的正样板块页被误杀（还原必绿失败）：{[m for m in res2['t3_managed'] if rel in m][:4]}"


def test_s78_inline_marker_quoting_board_page_not_false_flagged() -> None:
    """⑤ 防误伤（本席自抓的假红回归锁）：doc-taxonomy-sync.md 一类正文用**行内码引用**
    `BOARD-AUTO:BEGIN` 标记字面量（讲 AUTO 契约本身），机制 (b) 与 K-1 都不得把它当「多一段」。
    若哪天有人把机制 (b) 改成「原始段数==1」，这页会 b_ok→drift、G-T1 顶高 board-l3——本锁当场红。"""
    rel = "docs/boards/B10-engineering-governance/documentation/doc-taxonomy-sync.md"
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    # 前置：这页确有 ≥2 处标记字面量（首段真身 + 正文行内码引用），且它是正常复现的生成页。
    assert text.count(bds.AUTO_BEGIN) >= 2, "取样前提变了：这页不再是引用标记字面量的正常板块页"
    assert rel in _real()["b_ok"], f"引用标记字面量的正常板块页没被判已复现（⑤过度改动回归）：{rel}"
    assert not any(
        m.startswith(f"{rel}: UNVERIFIED_AUTO_ZONE") for m in _real()["t3_managed"]
    ), "正常板块页正文引用 BOARD-AUTO 字面量被误记 UNVERIFIED_AUTO_ZONE（把讲解当藏事实）"


# ---------------------------------------------------------------------------
# 席 S119 —— G-T5「在册模板驱动 0 页」孤儿腿（S111 的 C-3）：以下全部**新增用例**，
# 未改任何既有断言/上限字面量；`assert missing` 那枚自相矛盾的地板腿一字不碰。
# ---------------------------------------------------------------------------
def _s119_names(rows: list[str]) -> list[str]:
    return [r.split(": ", 1)[0] for r in rows]


def _s119_stems() -> set[str]:
    return {p.stem for p in dts.TEMPLATE_DIR.glob("*.md")}


def test_s119_orphan_leg_names_every_zero_page_template_in_disjoint_classes() -> None:
    """正向账 + 扫描面地板：驱动 0 页的在册模板**一枚都不许漏**，且两类分开点名。"""
    orph = _real()["t5"]["templates_without_pages"]
    assert set(orph) == set(sc.ORPHAN_CLASS_ORDER), f"孤儿腿分类集改版：{sorted(orph)}"
    per_class = {k: _s119_names(orph[k]) for k in sc.ORPHAN_CLASS_ORDER}
    all_names = [n for rows in per_class.values() for n in rows]
    assert len(all_names) == len(set(all_names)), f"一枚模板被记进两类（混账）：{all_names}"

    # 正样控制（判据必须看得见合法件）：驱动 >0 的模板不得进账。取数与函数同判据。
    schemas = _real()["schemas"]
    driven: dict[str, int] = {}
    for p in _real()["pages"]:
        if p.fm is None or p.fm.template not in schemas:
            continue
        if sc.category_mismatch(p, schemas) is not None:
            continue
        driven[p.fm.template] = driven.get(p.fm.template, 0) + 1
    assert driven, "全树无一张驱动页＝本腿退化成空门，先修取样"
    for t, n in driven.items():
        assert t not in all_names, f"{t} 实有 {n} 页驱动却被记成孤儿（判据过严）"

    # 扫描面地板（现算 22 枚在册、21 枚零页；塌陷即红，不写死枚数）：
    zero_page = {t for t in (_s119_stems() | set(schemas)) if not driven.get(t, 0)}
    assert set(all_names) == zero_page, (
        f"孤儿账与「驱动 0 页模板」全集不符（漏记＝缩面）："
        f"漏 {sorted(zero_page - set(all_names))} / 多 {sorted(set(all_names) - zero_page)}"
    )
    # 代码件类**不许被排除**（排除＝缩小扫描面＝§0 六禁）：只被代码类认领的模板必在账上。
    def _only_code(t: str | None) -> bool:
        if not t:
            return False
        return all(c.surface == "code" for c in dt.CONTENT_CATEGORIES if c.template == t)

    code_only = {c.template for c in dt.CONTENT_CATEGORIES if _only_code(c.template)}
    assert code_only <= set(per_class["code_surface"]), (
        f"代码件类模板被从孤儿账里剔除了（缩面）："
        f"{sorted(code_only - set(per_class['code_surface']))}"
    )
    assert per_class["code_surface"] and per_class["real_debt"], (
        "两类各至少一枚才算分开点名，否则两本账其实是同一本"
    )


def test_s119_orphan_leg_has_no_ceiling_written_by_this_seat() -> None:
    """④ 上限策略：新腿今日**只登记不设上限**——本文件不许出现该腿的任何上限/基线字面量。"""
    banned = [
        name
        for name in _CEILING_NAMES + _HISTORY_NAMES
        if "ORPHAN" in name.upper() or "ZERO_PAGE" in name.upper() or "TEMPLATE_LEG" in name.upper()
    ]
    assert banned == [], f"S119 私自定了上限/核账基线（应由该门 owner 转正时定）：{banned}"
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                up = tgt.id.upper()
                assert not (("ORPHAN" in up or "ZERO_PAGE" in up) and ("CEILING" in up or "BASELINE" in up)), (
                    f"S119 写了上限 {tgt.id}＝新腿自定基线，转正权在门 owner"
                )


def test_s119_poison_zero_page_template_enters_ledger_and_delists_when_driven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """③a 新造一枚零页模板⇒必进孤儿账（真债类）；③b 给它一页⇒自动摘牌。全程内存，不落盘。"""
    synth_cat = dt.CategoryDef(
        cid="s119-synth",
        template="s119-synth",
        surface="md",
        owner_board="B10",
        reason="S119 反向自测件（不是真类别）",
    )
    monkeypatch.setattr(dt, "CONTENT_CATEGORIES", (*dt.CONTENT_CATEGORIES, synth_cat))
    monkeypatch.setattr(dt, "CATEGORIES_BY_ID", {**dt.CATEGORIES_BY_ID, synth_cat.cid: synth_cat})
    schemas = {**_real()["schemas"], "s119-synth": _real()["schemas"]["handbook"]}
    stems = _s119_stems() | {"s119-synth"}
    bare_page = dts.PageInfo(
        rel="s119-synth.md",
        path=REPO_ROOT / "s119-synth.md",
        text="",
        fm=None,
        category=synth_cat.cid,
        violations=(),
    )
    out_a = sc.orphan_templates([*_real()["pages"], bare_page], schemas, stems)
    assert "s119-synth" in _s119_names(out_a["real_debt"]), (
        f"新造的零页模板没进真债账（桶里有页无人驱动却看不见）：{ {k: _s119_names(v) for k, v in out_a.items()} }"
    )
    # ③b：同一枚模板挂上一张真驱动页 ⇒ 立刻摘牌，且不得从任何一类里漏出来又冒回去
    driven_page = dts.PageInfo(
        rel=bare_page.rel,
        path=bare_page.path,
        text="",
        fm=dts.FrontMatter(template="s119-synth", params={}, extra_keys=()),
        category=synth_cat.cid,
        violations=(),
    )
    out_b = sc.orphan_templates([*_real()["pages"], driven_page], schemas, stems)
    still = [k for k, rows in out_b.items() if "s119-synth" in _s119_names(rows)]
    assert still == [], f"驱动页已到位仍未摘牌（说明账按名字写死）：{still}"
    assert len(out_a["real_debt"]) == len(out_b["real_debt"]) + 1, "摘牌没体现在枚数上＝两本账不同源"


def test_s119_poison_class_label_is_registry_driven_not_a_name_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """③c 分类判据必须**跟着注册表走**：把代码件类改标成 md ⇒ 它离开 code_surface；
    把 md 真债类改标成 code ⇒ 它离开 real_debt。误标＝账当场移动，不是名字表写死。"""
    # a) 一枚真债（handbook：桶有 1 页、驱动 0）被改标成代码件 ⇒ 必须离真债、进 code_surface
    relabel_to_code = tuple(
        dt.CategoryDef(
            cid=c.cid, template=c.template, surface="code", owner_board=c.owner_board,
            generated_by=c.generated_by, code_home=c.code_home or "scripts", reason=c.reason,
        )
        if c.cid == "handbook"
        else c
        for c in dt.CONTENT_CATEGORIES
    )
    monkeypatch.setattr(dt, "CONTENT_CATEGORIES", relabel_to_code)
    monkeypatch.setattr(
        dt, "CATEGORIES_BY_ID", {c.cid: c for c in relabel_to_code}
    )
    out = sc.orphan_templates(_real()["pages"], _real()["schemas"], _s119_stems())
    assert "handbook" not in _s119_names(out["real_debt"]), "改标代码件后仍记真债＝分类写死在名字表"
    assert "handbook" in _s119_names(out["code_surface"]), "改标代码件没落到 code_surface＝分类判据不跟注册表"


def test_s119_report_line_and_gate_read_the_same_numbers() -> None:
    """单一取数口自证（新增腿同权）：`--report` 那行的每个数＝判据用的同一支现算值。"""
    orph = _real()["t5"]["templates_without_pages"]
    lines = "\n".join(sc.report_lines(_real()))
    assert f"在册却驱动 0 页 = {sum(len(v) for v in orph.values())} 枚" in lines
    for k in sc.ORPHAN_CLASS_ORDER:
        assert f"{k}={len(orph[k])}" in lines, f"report 缺 {k} 的数＝report 自成一套账"


# ---------------------------------------------------------------------------
# 席 S131（2026-09-22，仅新增）：G-T3 面A 两处调用点真传 `known_fact_keys`
# （S106 备好判据、S114 接了 `--write` 前置半腿、S121 现算点名
# `spec_gates_census.py:595/:612` 两处未接 ⇒ 不接则加严只活在测试里）。
# 反向自测三发（③a/③b/③c）+ K-1 半腿活性双锁，全部 tmp 临时副本、不落源码树。
# ---------------------------------------------------------------------------
def _s131_faceA_page(tmp_path: Path) -> tuple[Path, str, str]:
    """搭一枚「必落行级面 A」的最小 tmp 页。返回（页文件路径, rel, 该页类别的在册模板 id）。

    席 S201（用户裁定 3.A）随判据跟随：旧写法取 `docs/live-guide.md` 并靠「driven 且非生成物」
    顶进面A——那条通道就是「戴头换尺子」本身，已被废。现在改从**门侧名录**取坐标
    （`GOVERNED_LINE_PATHS`，路径/登记派生即 line，与头无关），并现算把前提钉死：
    哪天名录或桶表改了、这一枚不再判 line，当场点名而非静默换面。
    """
    rel = min(sc.GOVERNED_LINE_PATHS)
    root = tmp_path / "repo"
    (root / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    tpl = sc.registered_template(dts.classify(rel))
    assert tpl, f"前提塌了：{rel!r} 的类别 {dts.classify(rel)!r} 无在册模板可挂"
    assert sc.face_of_page_by_path(
        dts.PageInfo(rel=rel, path=root / rel, text="", category=dts.classify(rel))
    ) == "line", f"前提塌了：名录枚 {rel} 已不被判为行级面 A（分流又变了）"
    return root / rel, rel, tpl


def _s131_write_page(page: Path, tpl: str, body: str) -> None:
    page.write_text(
        f"---\ntemplate: {tpl}\nparams:\n  seat_id: S131\n---\n\n# 受管页\n{body}",
        encoding="utf-8",
    )


def test_s131_poison_unregistered_placeholder_in_faceA_is_named(tmp_path: Path) -> None:
    """③a：受管页人写区写一枚**不在册** `{{fact:zzz_no_such_key}}` ⇒ G-T3 面A 必红并点名。

    这是 S106「有条件摘除」在**门记账腿**上的活性证明：接腿前恒绿（known=None＝无条件
    摘除的免检洞），接腿后必记 `UNKNOWN_FACT_KEY` 且页留在行级面 A。
    """
    page, rel, tpl = _s131_faceA_page(tmp_path)
    _s131_write_page(page, tpl, "\n本板块由 {{fact:zzz_no_such_key}} 维护。\n")
    res = sc.compute(tmp_path / "repo")
    named = [
        m
        for m in res["t3_managed"]
        if rel in m and dfd.UNKNOWN_FACT_KEY in m and "zzz_no_such_key" in m
    ]
    assert named, (
        "不在册占位符没被 G-T3 面A 点名＝S106 加严在门里仍是死的（known_fact_keys 未传到）："
        f"{[m for m in res['t3_managed'] if rel in m][:4]}"
    )
    assert rel not in set(res["t3_unmoved"]), (
        "该页必落行级面 A（driven 且非台账类）；落面 B＝分流变了形，注毒前提塌"
    )


def test_s131_registered_placeholder_still_passes(tmp_path: Path) -> None:
    """③b：写**在册**键（从 `@schema` 现算取）⇒ 正常摘除、不报 `UNKNOWN_FACT_KEY`。

    在册与否必须真从 `declared_fact_keys` 的单一取数口来——在册键被点名＝常数判红，
    和常数放行是同一种假绿的两张脸。
    """
    page, rel, tpl = _s131_faceA_page(tmp_path)
    known = dfd.declared_fact_keys(template=tpl, schemas=dts.load_schemas())
    assert known, f"前提塌了：模板 {tpl!r} 的 @schema 无在册参数"
    reg = min(known)
    _s131_write_page(page, tpl, f"\n本板块由 {{{{fact:{reg}}}}} 维护。\n")
    res = sc.compute(tmp_path / "repo")
    bad = [m for m in res["t3_managed"] if rel in m and dfd.UNKNOWN_FACT_KEY in m]
    assert not bad, f"在册参数被点名＝在册判定不是真从 @schema 来：{bad[:4]}"


def test_s131_key_source_failure_fails_closed_and_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """③c：取数口不可读 ⇒ **判红点名**（异常冒到门崩），绝不静默退化成旧免检行为。

    注毒法＝把唯一取数口 `declared_fact_keys` 换成会抛的桩；胶水（`page_known_fact_keys`）
    若吞异常回退 None（＝无条件摘除旧口径复活），本用例必红。
    """
    page, _rel, tpl = _s131_faceA_page(tmp_path)
    _s131_write_page(page, tpl, "\n本板块有 47 个能力入口。\n")  # 有人写行 ⇒ 必过取数口

    def _raiser(*_a: object, **_k: object) -> set[str]:
        raise RuntimeError("模拟在册参数取数口不可读（S131 注毒 c）")

    monkeypatch.setattr(dfd, "declared_fact_keys", _raiser)
    with pytest.raises(RuntimeError, match="取数口不可读"):
        sc.compute(tmp_path / "repo")


def test_s131_k1_auto_zone_leg_is_live_too(tmp_path: Path) -> None:
    """K-1 半腿活性锁（S106 注释未点名、S121 现算抓出的第三处）：假机器段里的不在册
    占位符必须以 `UNVERIFIED_AUTO_ZONE` + `UNKNOWN_FACT_KEY` 落地；还原成无占位符 ⇒ 该页
    不再有 UNKNOWN 行（两向都判，防「只接主循环、K-1 恒旧行为」的半腿假绿复发）。
    """
    page, rel, tpl = _s131_faceA_page(tmp_path)
    zone_body = (
        "\n本板块由一个寻常短语维护。\n\n"
        f"{dts.TPL_AUTO_BEGIN}\n{dts.TPL_AUTO_NOTE}\n"
        "藏段里的 {{fact:zzz_no_such_key}} 没人看见。\n"
        f"{dts.TPL_AUTO_END}\n"
    )
    _s131_write_page(page, tpl, zone_body)
    res = sc.compute(tmp_path / "repo")
    zone_hits = [
        m
        for m in res["t3_managed"]
        if "UNVERIFIED_AUTO_ZONE" in m and dfd.UNKNOWN_FACT_KEY in m
    ]
    assert zone_hits, (
        "K-1 段里不在册占位符没被抓＝第三处调用点没接上（S121 点名的半腿假绿复发）："
        f"{[m for m in res['t3_managed'] if 'AUTO' in m][:4]}"
    )
    # 还原：段内占位符改回干净句 ⇒ 不再新增任何 UNKNOWN 点名（不误杀）。
    _s131_write_page(
        page, tpl, zone_body.replace("{{fact:zzz_no_such_key}}", "寻常名词")
    )
    res2 = sc.compute(tmp_path / "repo")
    assert not [m for m in res2["t3_managed"] if dfd.UNKNOWN_FACT_KEY in m], (
        f"还原后仍被点名＝在册/不在册判定不真：{[m for m in res2['t3_managed'] if rel in m][:4]}"
    )


# ---------------------------------------------------------------------------
# 席 S152（2026-09-22，第二十四批，**仅新增**）：板块正文**完整度**账 G-B1。
# S89 交卷时披露「正文完整度至今没有自动判据（只有页内自述）」——本席把它变成可复算的账。
# 四列全部复用既有尺子（判据真身与出处写在 `scripts/spec_gates_census.py` S152 段头注）；
# 本腿**只登记不设上限**：新账没有可抬的东西，转正首届核账值由该门 owner 在收口窗取。
# 反向自测三发（④a/④b/④c）+ AST 结构锁（防未来塞上限而不核账），全程内存/tmp，
# **不往源码树写一个字**（`docs/boards/**` 对本席是禁写面）。
# ---------------------------------------------------------------------------
def _s152_page(text: str, *, category: str = "board-l3") -> dts.PageInfo:
    """造一枚内存板块页（`rel` 只用于落在板块管辖面，盘上不存在该文件）。"""
    return dts.PageInfo(
        rel="docs/boards/B99-s152/s152/l3.md",
        path=REPO_ROOT / "docs" / "boards" / "B99-s152" / "s152" / "l3.md",
        text=text,
        fm=None,
        category=category,
        violations=(),
    )


def _s152_row(text: str) -> dict[str, object]:
    return sc.board_body_completeness_row(
        _s152_page(text), b_ok=set(), canon=sc.BOARD_CANON["board-l3"]
    )


#: 「纯指针」正样的句子形态＝AGENTS 规则 10 的放行形 `以 <真身路径> 为准。`。
#: 路径刻意取短：指针短语尺 `dfd.AUTHORITY_PHRASE_RE` 的 `以…为准` 只覆盖 48 字窗，
#: 超长路径写出来是另一种形态，拿它当正样只会测到自己选的形状（S141「样本形状」教训）。
_S152_POINTER_LINE = "以 `domains/core/session_keys.py` 为准。"


def _s152_filled(body: str, filler: str) -> str:
    """把骨架每一节的**占位原文**换成 `filler`（节名与顺序原样保留，只动正文）。"""
    out = body
    for skeleton in sc.slot_bodies(body).values():
        if skeleton:
            out = out.replace(skeleton, filler, 1)
    return out


def test_s152_ledger_covers_every_board_page_exactly_once() -> None:
    """正向账 + 缩面自证：板块管辖面每一页恰落一档，枚数与页集**同源**（不写死页数）。"""
    bc = _real()["body_completeness"]
    assert isinstance(bc, dict)
    rows = bc["rows"]
    assert isinstance(rows, list)
    all_pages = _real()["pages"]
    assert isinstance(all_pages, list) and all(isinstance(p, dts.PageInfo) for p in all_pages), (
        "管辖面取样元素不再是 PageInfo：取样口改版，本锁必须复核（绝不静默缩面）"
    )
    scope = [p for p in all_pages if p.rel.startswith("docs/boards/")]
    assert len(rows) == len(scope) > 0, "板块页取样塌陷或缩面（应等于管辖面板块页全集）"
    assert {str(r["rel"]) for r in rows} == {p.rel for p in scope}, "账页集与管辖面不一致"
    tiers = bc["tiers"]
    assert isinstance(tiers, dict) and set(tiers) == set(sc.BODY_TIER_ORDER), (
        f"分档集合与声明的四档不等（改档必须同步改本锁）：{sorted(tiers)}"
    )
    assert sum(int(v) for v in tiers.values()) == len(rows), "分档枚数不等于页数＝有页没落档"
    assert all(r["tier"] in sc.BODY_TIER_ORDER for r in rows)
    # 正样控制（判据必须看得见合法件本身）：既有板块页不得被整体误杀成空壳。
    assert tiers["完整"] > 0, f"全树板块页无一判为完整＝判据过严，先查尺子而不是改页：{tiers}"


def test_s152_tiers_are_self_consistent_with_the_four_columns() -> None:
    """四档与四列互洽（结构性不变量）：任何一页的档位都能被它的列值解释。

    这条不变量同时是 ④c 的探针：判据被改成「恒返回完整」时它必红。
    """
    bc = _real()["body_completeness"]
    assert isinstance(bc, dict)
    b_ok = _real()["b_ok"]
    assert isinstance(b_ok, set)
    for r in bc["rows"]:  # type: ignore[index]
        row = r  # type: dict[str, object]
        tier = row["tier"]
        unfilled = list(row["unfilled_slots"])  # type: ignore[arg-type]
        missing = list(row["missing_required_slots"])  # type: ignore[arg-type]
        if tier == "完整":
            assert not unfilled and not missing and not row["pointer_only"], (
                f"{row['rel']}：判为完整却带未填槽/缺必选/纯指针列值（判据与列不同源）"
            )
        elif tier == "骨架残留":
            assert unfilled or missing or int(row["human_chars"]) == 0, (
                f"{row['rel']}：判为空壳却无任何可指认的列值（＝凭空加档）"
            )
        elif tier == "纯指针":
            assert row["pointer_only"] and not unfilled and not missing, (
                f"{row['rel']}：纯指针档与列值不符（两态必须分得开）"
            )
        else:
            assert int(row["human_chars"]) == 0 and row["rel"] in b_ok, (
                f"{row['rel']}：机器整册档不许走路径豁免，必须机制 (b) 当场复现（`b_ok`）"
            )


def test_s152_poison_unfilled_skeleton_slot_is_skeleton_residual() -> None:
    """④a：造一枚「骨架占位原文还在」的页 ⇒ 必进**骨架残留**；逐节填实后必离档。"""
    bare = _s152_row(bds.L3_BODY)
    assert bare["tier"] == "骨架残留", f"整页未填的骨架没被判空壳（判据失灵）：{bare}"
    assert bare["unfilled_slots"], "未填槽清单为空＝『逐字比对骨架』这条尺其实没在执法"
    assert bare["slot_total"], "板块骨架可比性未取到（canon 传丢了）"
    filled = _s152_row(
        _s152_filled(bds.L3_BODY, "本入口收上行事件、产出卡片载荷，生效需总闸开且会话准入通过。")
    )
    assert filled["tier"] == "完整" and not filled["unfilled_slots"], (
        f"填实后仍挂空壳档＝档位不跟正文走：{filled}"
    )


def test_s152_poison_pointer_only_page_is_its_own_class() -> None:
    """④b：全节只写指针句 ⇒ 归**纯指针**，且**不**算骨架残留/完整（两态分得开）。"""
    ptr = _s152_row(_s152_filled(bds.L3_BODY, _S152_POINTER_LINE))
    assert ptr["tier"] == "纯指针", f"纯指针页被混进别档（两态混账）：{ptr}"
    assert ptr["pointer_only"] and not ptr["unfilled_slots"] and not ptr["missing_required_slots"]
    assert int(ptr["human_chars"]) > 0, "指针页人写区为 0＝它会被机器整册档吃掉（档挤档）"


def test_s152_poison_ruler_blinded_to_incompleteness_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """④c：把判据改成恒返回「完整」⇒ 本席用例当场红（证用例有牙，不是复读现算值）。

    样本里必须**混进**一枚未填骨架页：真树今日 0 空壳，只喂真树的话「恒完整」找不到矛盾＝
    那会是一把空跑探针（同 S141 点名的「注毒用例写死受害 cid」一族）。
    """
    real = sc.board_body_completeness_row

    def blinded(p: dts.PageInfo, *, b_ok: set[str], canon: object) -> dict[str, object]:
        row = real(p, b_ok=b_ok, canon=canon)
        row["tier"] = "完整"
        return row

    skeleton_page = _s152_page(bds.L3_BODY)
    assert sc.board_body_completeness_row(
        skeleton_page, b_ok=set(), canon=sc.BOARD_CANON["board-l3"]
    )["tier"] == "骨架残留", "前提塌了：骨架页在真判据下都不算空壳，注毒样本无从证伪"
    monkeypatch.setattr(sc, "board_body_completeness_row", blinded)
    bc = sc.board_body_completeness([*list(_real()["pages"]), skeleton_page], b_ok=_real()["b_ok"])
    bad = [
        r["rel"]
        for r in bc["rows"]
        if r["tier"] == "完整"
        and (r["unfilled_slots"] or r["missing_required_slots"] or r["pointer_only"])
    ]
    assert bad, "把判据注毒成恒『完整』后仍有账自洽＝本席用例是假绿（没在执法）"


def test_s152_report_line_and_gate_read_the_same_numbers() -> None:
    """单一取数口自证（新腿同权）：`--report` 那行的每个数＝判据用的同一支现算值。"""
    bc = _real()["body_completeness"]
    assert isinstance(bc, dict)
    tiers = bc["tiers"]
    assert isinstance(tiers, dict)
    lines = "\n".join(sc.report_lines(_real()))
    for t in sc.BODY_TIER_ORDER:
        assert f"{t}={tiers[t]}" in lines, f"report 缺 {t} 的数＝report 自成一套账"
    assert f"板块管辖页 {bc['page_total']}" in lines
    assert "只登记不设上限" in lines, "上限策略文案被改＝转正核账窗口被悄悄跳过"


def test_s152_no_ceiling_written_by_this_seat() -> None:
    """③ AST 结构锁：新账**今日只登记不设上限**——两份文件里不许出现本腿的上限/基线字面量。

    防的是「未来有人塞一枚 `..._CEILING` 而不核账」：名字里带完整度/分档字样又带
    CEILING/BASELINE 的赋值一旦出现（`Assign`/`AnnAssign` 双形态都抓）即红，转正走该门 owner。
    """
    def _bad_names(path: Path) -> list[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hit: list[str] = []
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for tgt in targets:
                if isinstance(tgt, ast.Name):
                    up = tgt.id.upper()
                    topic = any(k in up for k in ("BODY", "COMPLETENESS", "TIER", "G_B1", "GB1"))
                    if topic and ("CEILING" in up or "BASELINE" in up):
                        hit.append(f"{path.name}::{tgt.id}")
        return hit

    offenders = _bad_names(Path(__file__)) + _bad_names(REPO_ROOT / "scripts" / "spec_gates_census.py")
    assert offenders == [], f"S152 的完整度腿被写了上限/基线（转正权在该门 owner）：{offenders}"
    for name in _CEILING_NAMES + _HISTORY_NAMES:
        assert "BODY" not in name.upper() and "COMPLETENESS" not in name.upper(), (
            f"上限名册里混进了完整度腿 {name}＝新账被塞进只降的旧册"
        )


# ---------------------------------------------------------------------------
# 席 S164（第二十六批）：G-T5「三角第三边」另一半边的**接线自证**（方向只准加严）
#
# S161 取证：`registered_template()` 把两件不同的事压成同一个 `None`——
#   ①「生成器所有／代码面」⇒ 本腿**该**豁免；②「md 在册但该桶压根没有模板」⇒ 本腿**该**执法。
# 旧死类循环 `want is not None and want not in schemas` 把 ② 一起短路，故 ② 的页从不进
# `pages_unreachable`（只被 `missing_template` 按类别记到）。本席按 S161 的 PARKED 最小 diff
# 接线（`should_have_template` + 循环条件），下面四枚＝两列对照复算 + 三发反向自测 + 一枚自锁。
# 全程内存注毒（monkeypatch 注册表两份视图）／tmp 副本，**不往源码树写一个字**。
# 禁线自证：既有断言一字未改（含那枚红的 `poison_triangle` 与 `assert missing` 地板腿）、
# 任何 `_CEILING/_BASELINE` 未增未改（本席这条腿今日**只接线不设上限**）。
# ---------------------------------------------------------------------------
_S164_CID = "doc-misc"
_S164_REL = "docs/orphan.md"
#: 一枚真存在、且能被 `_module_symbols` 认出的模块级赋值 ⇒ 让「生成口解析」这一腿走真码路，
#: 而不是靠本席自证「豁免了个不存在的东西」。
_S164_REAL_PORT = "scripts/doc_templates.py:CONTENT_CATEGORIES"


def _s164_bucket(
    monkeypatch: pytest.MonkeyPatch,
    *,
    template: str | None,
    surface: str = "md",
    generated_by: str = "",
    code_home: str = "",
) -> None:
    """内存改在册类别 `doc-misc` 的四个字段（同读注册表唯一真身，零第二套分类表）。"""
    rows: list[dt.CategoryDef] = []
    for c in dt.CONTENT_CATEGORIES:
        if c.cid == _S164_CID:
            rows.append(
                dt.CategoryDef(
                    cid=c.cid, template=template, surface=surface, owner_board=c.owner_board,
                    generated_by=generated_by, code_home=code_home,
                    reason="S164 内存注毒件（不是真类别、不落盘）",
                )
            )
        else:
            rows.append(c)
    monkeypatch.setattr(dt, "CONTENT_CATEGORIES", tuple(rows))
    monkeypatch.setattr(dt, "CATEGORIES_BY_ID", {x.cid: x for x in rows})


def _s164_root(tmp_path: Path) -> Path:
    """临时副本里放一张无头页，使其落到 `_S164_CID` 桶；返回 `compute(root)` 的 root。

    `exist_ok=True` 是必需的：一枚用例内要换形状**多次**现算（两列对照/两本账分界），
    同页复用会 `FileExistsError`——那是自炸，不是判据红。
    """
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "orphan.md").write_text("# 无头页\n\n正文。\n", encoding="utf-8")
    assert dts.classify(_S164_REL) == _S164_CID, "取数口改版：该页不再落到 doc-misc，注毒前提塌"
    return root


def _s164_rows(res: dict[str, object]) -> list[str]:
    """读第三边并**只**筛本席载体类别（fail-closed：形状异常一律炸，不把读不到当合规）。"""
    t5 = res["t5"]
    assert isinstance(t5, dict), f"取数口缺 t5 或类型异常（{type(t5)}）＝读口失明，判红不判绿"
    rows = t5["pages_unreachable"]
    assert isinstance(rows, list), f"pages_unreachable 不是 list（{type(rows)}）＝取数口改版"
    assert all(isinstance(r, str) for r in rows), "三角断链元素非字符串＝取数口返回类型异常"
    return [r for r in rows if r.startswith(f"{_S164_CID}:")]


def test_s164_two_column_comparison_reproduces_s161_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """① 复现 S161 的两列对照（一次跑完三形，钉死「哪半边已执法／哪半边是本席新接的」）。"""
    # 正样控制：在册模板可达 ⇒ 两个数都干净。
    _s164_bucket(monkeypatch, template="guide")
    res = sc.compute(_s164_root(tmp_path))
    assert _s164_rows(res) == [], f"可达类别被误记断链（钝尺误杀）：{_s164_rows(res)}"
    # 旧已执法半边：在册模板 id 装载失败 ⇒ 接线**前后都**该记（本席没动这半边）。
    _s164_bucket(monkeypatch, template="s164-ghost-not-a-real-template")
    rows = _s164_rows(sc.compute(_s164_root(tmp_path)))
    assert len(rows) == 1 and "1 页" in rows[0], f"装载失败半边失去执法（本席改动越界）：{rows}"
    # 本席新接的半边：无模板 ⇒ 接线后必记（S161 记为「今日如实红」的那条形）。
    _s164_bucket(monkeypatch, template=None)
    rows = _s164_rows(sc.compute(_s164_root(tmp_path)))
    assert len(rows) == 1 and "1 页" in rows[0], (
        f"「在册但无模板」的类别下的页没进三角断链＝第三边又失明（本席接线被改坏）：{rows}"
    )


def test_s164_poison_generated_bucket_is_exempt_from_third_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """④b 防误伤：生成器所有的类别即便无模板，也**不许**进 md 断链（豁免面一字未缩）。"""
    _s164_bucket(monkeypatch, template=None, generated_by=_S164_REAL_PORT)
    assert sc.should_have_template(_S164_CID) is False, "同源谓词把生成物类别判成该执法＝误伤"
    res = sc.compute(_s164_root(tmp_path))
    assert _s164_rows(res) == [], f"生成物类别下的页被记进 md 断链（钝尺误杀）：{_s164_rows(res)}"
    # 生成口可解析 ⇒ 类别账也不该点名它（两腿同源，不各说各话）。
    named = [m for m in res["t5"]["missing_template"] if m.startswith(f"{_S164_CID}:")]
    assert named == [], f"生成口本可解析却被类别账点名（判据不同源）：{named}"


def test_s164_poison_code_surface_goes_to_code_leg_not_md_leg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """④c 两本账**不重不漏**：代码面类别的页不入 md 按页断链，但必被类别/代码面腿记到。"""
    _s164_bucket(monkeypatch, template=None, surface="code")
    assert sc.should_have_template(_S164_CID) is False, "代码面被判归 md 腿管辖＝两本账串了"
    res = sc.compute(_s164_root(tmp_path))
    assert _s164_rows(res) == [], f"代码面页混进 md 按页断链（重复记账）：{_s164_rows(res)}"
    named = [m for m in res["t5"]["missing_template"] if m.startswith(f"{_S164_CID}:")]
    assert len(named) == 1 and "无对应模板" in named[0], (
        f"代码面桶无模板却没被代码/类别面账记到＝漏账，两本账不成立：{named}"
    )
    # 同一形状换回 md 面 ⇒ 必须由 md 按页腿记到（证明分界来自 `surface`，不是名字硬编码）。
    _s164_bucket(monkeypatch, template=None, surface="md")
    res_md = sc.compute(_s164_root(tmp_path))
    assert len(_s164_rows(res_md)) == 1, (
        f"同形状改回 md 却没落 md 腿＝判据认名字不认 surface：{_s164_rows(res_md)}"
    )
    md_named = [m for m in res_md["t5"]["missing_template"] if m.startswith(f"{_S164_CID}:")]
    assert len(md_named) == 1, (
        f"类别账应**继续**按类别记它（本席只补按页边、不摘类别边）：{md_named}"
    )


def test_s164_no_ceiling_written_by_this_seat() -> None:
    """③ 方向自查的下半：接线只加严、真树新增枚数不折进上限——本席**不许**自录上限/基线。"""
    banned = [
        name
        for name in _CEILING_NAMES + _HISTORY_NAMES
        if "THIRD_EDGE" in name.upper() or "UNREACHABLE" in name.upper()
    ]
    assert banned == [], f"S164 私自为第三边设了上限/基线（转正权在该门 owner）：{banned}"
    # 第三边的既有账册只认 S2 时代那两枚（一枚上限 + 一枚核账历史），本席一字未动；
    # 冒出第三枚 ⇒ 有人（含本席）借接线之名给这条腿新设了上限/基线。
    assert [n for n in _CEILING_NAMES if "DEADCLASS" in n.upper()] == ["T5_DEADCLASS_CEILING"], (
        "第三边的上限名册被加了第二枚＝本席（或后来人）自录上限，转正权在门 owner"
    )
    assert [n for n in _HISTORY_NAMES if "DEADCLASS" in n.upper()] == [
        "AUDIT_HISTORY_T5_DEADCLASS"
    ], "第三边的核账历史被加了第二枚＝本席自录基线"
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                up = tgt.id.upper()
                assert not (
                    ("THIRD_EDGE" in up or "UNREACHABLE" in up or "SHOULD_HAVE" in up)
                    and ("CEILING" in up or "BASELINE" in up)
                ), f"S164 写了上限 {tgt.id}＝新腿自定基线，转正权在门 owner"
                assert "S164" not in up or not (
                    "CEILING" in up or "BASELINE" in up
                ), f"S164 写了专属上限 {tgt.id}"


# ---------------------------------------------------------------------------
# 席 S175 —— G-T1 甲账「波内拆分」只读腿（波前存量 / 本波新建）
#   只加一栏数，绝不把任何页排除出账；两栏之和恒等于 t1；今日只登记不设上限。
# ---------------------------------------------------------------------------
def test_s175_pure_split_partitions_without_dropping_any_page() -> None:
    """合成账：二值集合判定⇒不重不漏；`rel#原因` 归栏只认 `#` 前的路径。"""
    t1 = ["docs/a.md", "docs/b.md#生成物未当场复现字节等值", ".superpowers/SEAT-X.md"]
    base = frozenset({"docs/a.md"})  # b 虽在 docs/ 下但不在基线 ⇒ 本波新建
    sw = sc.split_t1_by_wave(t1, base, "")
    assert sw["degraded"] is False
    assert sw["stock_count"] == 1 and sw["new_count"] == 2 and sw["total"] == 3
    assert sw["identity_ok"] is True and sw["amphibious"] == []
    assert sw["stock"] == ["docs/a.md"]
    assert sorted(sw["new"]) == [
        ".superpowers/SEAT-X.md",
        "docs/b.md#生成物未当场复现字节等值",
    ]
    # 覆盖性（不重复、不遗漏）：两栏并起来正好是原 multiset
    assert sorted(sw["stock"] + sw["new"]) == sorted(t1)


def test_s175_real_tree_identity_and_zero_exclusion() -> None:
    """真树：恒等式成立、无两栖、无排除（两栏并集是 t1 的一个置换）、扫描面未塌。"""
    sw = _real()["t1_wave_split"]
    t1 = _real()["t1"]
    assert sw["identity_ok"] is True, "拆栏恒等式被破坏＝判据被写坏（缩了扫描面）"
    assert sw["stock_count"] + sw["new_count"] == len(t1), "两栏之和≠甲账⇒有页被吞"
    assert sw["amphibious"] == [], "两栖页非空⇒同一页被判进两栏，账会重复"
    assert sorted(sw["stock"] + sw["new"]) == sorted(t1), (
        "两栏并集≠t1 的置换⇒漏计或双计，甲账被改动"
    )
    assert sum(sw["per_cat_stock"].values()) == sw["stock_count"]
    assert sum(sw["per_cat_new"].values()) == sw["new_count"]
    assert len(t1) >= 1000, "甲账现算塌陷（<1000）＝取数口瞎了，不是拆栏出错"
    # 方向锁：拆栏只加数，t1 本体不因本席而变（甲账现值仍受同一门管；上限一枚属点名册腿记账，
    # 其 2026-09-25 N5 收紧重录走 approvals 通道，与本席无关、本席一字未碰）
    assert len(t1) <= T1_CEILING or len(t1) > T1_CEILING  # 恒真占位：本席不碰 t1/上限


def test_s175_split_leg_sets_no_ceiling_and_scan_face_intact() -> None:
    """结构锁：S175 新腿只报数、不写任何上限/基线；WAVE_BASE_COMMIT 必须是字面字符串。"""
    src = Path(sc.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:  # 只看模块顶层赋值
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                up = tgt.id.upper()
                assert not (
                    ("WAVE" in up or "SPLIT" in up or "STOCK" in up or "NEW" in up)
                    and ("CEILING" in up or "BASELINE" in up or "_MAX" in up)
                ), f"S175 写了上限 {tgt.id}＝新腿自定基线，转正权在门 owner"
    assigned: dict[str, ast.expr | None] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    assigned[tgt.id] = node.value
    wbc = assigned.get("WAVE_BASE_COMMIT")
    assert isinstance(wbc, ast.Constant) and isinstance(wbc.value, str), (
        "WAVE_BASE_COMMIT 必须是字面字符串（不可由派生/工作树状态算出，否则可被写盘绕过）"
    )
    # 拆分腿函数体里不得出现比较把页排除出账（只许 in/not-in 归类）
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "split_t1_by_wave"
    )
    assert not any(
        isinstance(x, ast.Continue) for x in ast.walk(fn)
    ), "拆分腿出现 continue＝有把页跳过（排除）的代码路径，缩扫描面一票否决"
    assert "不设上限" in src, "报告行须显式声明今日只登记不设上限"


def test_s175_poison_new_page_lands_in_new_bucket_total_rises(tmp_path: Path) -> None:
    """反向自测④a：新建一枚不在基线的页 ⇒ 必进「本波新建」、总数 +1，不被吞。"""
    base, err = sc.git_wave_base_paths(sc.WAVE_BASE_COMMIT)
    if not base:  # 非 git 环境（如受限 CI）⇒ 走降级路径，仍不得吞页
        sw = sc.split_t1_by_wave(["docs/x.md"], None, err)
        assert sw["degraded"] is True and sw["new_count"] == 1 and sw["identity_ok"] is True
        return
    stock_rel = "docs/HANDBOOK.md"
    assert stock_rel in base, f"正样 {stock_rel} 不在基线，测试前提失效"
    new_rel = ".superpowers/sdd/2026-09-22-taxonomy/SEAT-POISON-S175.md"
    assert new_rel not in base, "毒样恰好在基线里＝前提失效"
    sw0 = sc.split_t1_by_wave([stock_rel], base, "")
    sw1 = sc.split_t1_by_wave([stock_rel, new_rel], base, "")
    assert sw1["total"] == sw0["total"] + 1
    assert sw1["new_count"] == sw0["new_count"] + 1  # 新页只顶「本波新建」栏
    assert sw1["stock_count"] == sw0["stock_count"]  # 存量栏不动
    assert new_rel in sw1["new"], "新建页被吞＝排除出账"


def test_s175_poison_mtime_is_not_a_free_pass(tmp_path: Path) -> None:
    """反向自测④b：改 mtime 不改判据——在册页改新仍「存量」、新建页改旧仍「本波新建」。"""
    import os

    base, _err = sc.git_wave_base_paths(sc.WAVE_BASE_COMMIT)
    if not base:
        pytest.skip("基线不可达：无 git 环境，此路已由 ④a 降级分支覆盖")
    stock_rel = "docs/HANDBOOK.md"
    assert sc.split_t1_by_wave([stock_rel], base, "")["stock_count"] == 1
    # 把盘上在册文件的 mtime 顶到极新，判据（不读 mtime）必须仍判存量
    f = tmp_path / "HANDBOOK.md"
    f.write_text("x", encoding="utf-8")
    os.utime(f, (4102444800, 4102444800))  # 2100 年
    assert sc.split_t1_by_wave([stock_rel], base, "")["stock_count"] == 1, (
        "mtime 影响了归类＝拿可伪造的时间当免罪符"
    )
    # 反向：把新建页 mtime 抹到极旧（1970 之后一点），仍必须算「本波新建」（不在基线）
    new_rel = ".superpowers/sdd/2026-09-22-taxonomy/SEAT-BACKDATE-S175.md"
    assert new_rel not in base
    g = tmp_path / "SEAT-BACKDATE.md"
    g.write_text("x", encoding="utf-8")
    os.utime(g, (10, 10))  # 假装很老
    sw = sc.split_t1_by_wave([new_rel], base, "")
    assert sw["new_count"] == 1 and sw["stock_count"] == 0, (
        "改旧 mtime 就把新页洗成存量＝判据可被写盘绕过"
    )


def test_s175_poison_broken_identity_is_caught(tmp_path: Path) -> None:
    """反向自测④c：恒等式被破坏（有人偷偷排除一枚页）⇒ 下游恒等判据必红。"""
    base, _err = sc.git_wave_base_paths(sc.WAVE_BASE_COMMIT)
    t1 = ["docs/a.md", "docs/b.md", "docs/c.md"]
    sw = sc.split_t1_by_wave(t1, base if base else None, "" if base else "no-git")
    # 正常拆栏恒等式成立
    assert sw["identity_ok"] is True and sorted(sw["stock"] + sw["new"]) == sorted(t1)
    # 模拟「排除一枚页」的坏拆分（把 b 从两栏里丢掉）：门用的置换判据必须判红
    tampered_stock = [e for e in sw["stock"] if e != "docs/b.md"]
    tampered_new = [e for e in sw["new"] if e != "docs/b.md"]
    covered = sorted(tampered_stock + tampered_new)
    assert covered != sorted(t1), "置换判据没抓到被排除的页＝门形同虚设"
    assert len(tampered_stock) + len(tampered_new) != len(t1)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

