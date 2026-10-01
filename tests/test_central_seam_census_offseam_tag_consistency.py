"""缝外语境标签的判据口唯一性锁（S-CENSUS-LEG3，2026-09-29，全离线）。

## 定罪对象（一句话）
普查尺 `scripts/central_seam_census.py` 给每个直呼点打语境标签；`_inside_feed` 把
「直呼结果直接作 缝/泛型/push/invoke 的实参交出」判成 `seam-feed`，其 docstring 原话＝
「**交给中央，非缝外**」。同一个 `file:line` 因此被尺记成两笔：`seam_sites`（正证据）与
`offseam_sites`（桶名与 `--report` 标题都写着「缝外直呼点」＝负证据）。
**改前尺从没定过「哪一桶是债」**：`violations_second_route` 用一条白名单
`("exec-bypass","assembly-wrap")` 自己滤，`_state()` 却直接读原桶（真树里从未滤过缝），
导出侧也直接交原桶 ⇒ 三套规则并存在同一把尺里 ⇒ 谁按桶名读债谁掉坑。
现算触发点＝根 `plugins/bot_unified_runtime/__init__.py:6299`
（`build_tts_capability` 的成品交给 `orchestrated_command("bot.tts", …)`，同线亦记 `seam_sites`；
承载 id 判 wired，尺自己的 violations 账不含它），被按桶名读债的腿③报成「第二条通路」。

## 本件钉四件事（判据只读导出、绝不重算 AST ⇒ 与尺永不脱钩）
其一 **真树自洽**：`offseam_bypass_sites` 与 `offseam_sites` **同点同下标**逐枚等值
   （只摘 `seam-feed`；藏位/换位/整桶失踪各红一处）；两桶计数走同一等式。
其二 **桶名不许说谎**：`state=="offseam"` ⟹ 判债桶非空；且每个 `seam-feed` 点必须被尺内
     **另一本独立账**（`seam/invoke/generic_sites` 或 `meta.seam_variable_sites`）按
     `file:line` 反证为「确实交进了中央件」——反证不到就红 ⇒ `seam-feed` 不是免检标签、
   不是豁免抽屉（这条拦住"给真旁路盖喂缝章销债"那一手）。
其三 **判据口唯一**（AST 源码级）：`seam-feed` 这个词在尺件里只准出现在两处——常量定义、
     判据⑥的赋值；判债侧一律走 `is_offseam_bypass` 这个名字。尺件里任何别处的
     `tag != "seam-feed"` / 含该词的比较 ⇒ 红＝第二份判据（本次归因的根形）。
     ⚠ 尺内**允许**另一类比较：`violations` 用 `s["tag"] in SECOND_ROUTE_TAGS`（名字引用）
     回答的是另一个问题（「已通电却直呼」认哪些标签），不是缝外判据的副本。
其四 **方向账**（`--report` 现算，两形各一枚 + 一条计数）：`counts.offseam_sites −
     counts.offseam_bypass_sites` 必须**恰好**等于「被正证据反证过」的 `seam-feed` 点数。

⚠ 方向纪律（照 `tests/test_offseam_wired_contradiction_gate.py` 的家规）：本件**不设债数
上限/地板**——债真被收编时那些数必须能降，锁死它＝拦人摘基线。本件只钉等式（尺自洽，
与债多少无关）＋一枚**活性地板**（`seam-feed` 点必须 ≥ 1）——现算若一枚喂缝点都没有，
〔①〕〔②〕〔③〕三腿与注毒 P1/P2/P4/P5 同时失去落点，本锁只剩计数等式在跑。

## 与既有尺的分工（互不覆盖，四条并排读才完整）
* `tests/test_central_seam_census_s81.py`：`unknown_ids` 分档只加账不减账。
* `tests/test_offseam_wired_contradiction_gate.py`：`wired ∧ exec-bypass` 的方向棘轮，
  且钉「桶名不许说谎」的**计数形**（`sum(row.offseam_sites) == counts.offseam_sites`，
  防 `--report` 被换尺）。
* `tests/test_capability_manifest_gate.py` 腿③：按桶名读债的**消费者**（禁改面，本席一字未动）。
* **本件**：钉「导出桶 == 滤缝后的原桶」这一**语义形**自洽，并把缝外判据钉成**只有一处**
  （s95 把 tag 判定抄在消费者侧两份 ⇒ 它自己就是"第二份判据"的活教材）。
⇒ 本件必须**自带**真树活性锁，且**绝不吃** s95 的任何常量。

## 注毒五形（全在内存合成 payload / 合成源码上跑，`plugins/**` 与尺本体一字不写）
P1 导出侧改回未过滤原桶 → 〔①〕导出与语义打架 红，且归因唯一（〔②〕〔④〕不许顺手响）；
P2 真旁路盖喂缝章销债（摘掉该线的中央落点）→ 〔③〕喂缝无凭 红（〔①〕安静）；
P3 判据口被拆成两处 → AST 结构红：正向＝真尺 `== []`，反向＝同文件内写的合成尺件源码必被抓；
P4 判据被改成恒真（＝退化回「按原桶算债」）→ 在尺件上**真跑**：`_state()` 说谎与〔①〕同时现形；
P5 纯合成 payload 的三态说谎 → 〔②〕红，且与〔③〕**彼此独立**（摘掉反证账 ⇒ 〔③〕新响、〔②〕照响）。

复跑::

    cd <仓库根>
    RT=<ChatBot_Runtime>/venv   RUN=<仓库外私有目录>
    PYTHONDONTWRITEBYTECODE=1 TMP="$RUN" TEMP="$RUN" PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0 \
      "$RT/Scripts/python.exe" -m pytest \
      tests/test_central_seam_census_offseam_tag_consistency.py \
      -q -p no:cacheprovider --basetemp="$RUN/bt"
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
_CENSUS = ROOT / "scripts" / "central_seam_census.py"

#: 喂缝标签（真身＝尺件常量 `SEAM_FEED_TAG`；本件按"词"钉判据口，故此处留一份对照字面量，
#: 由 `test_ruler_exports_the_seam_feed_word_once` 逐字符核对，不许两份各写各的）。
SEAM_FEED_TAG = "seam-feed"
#: 尺件里唯一直触该词的判据函数名。
SOLE_VERDICT_FN = "is_offseam_bypass"
#: 喂缝点的反证账（尺内独立于 offseam 桶的证据源）。
_POSITIVE_BUCKETS = ("seam_sites", "invoke_sites", "generic_sites")

#: 活性地板（手写整数字面量，绝不派生）：现算全树 `seam-feed` 点数 == 1（根 `__init__.py:6299`）。
#: 只准当"注入失去落点 / 扫描瞎了"的哨兵——低于 1 时〔①〕〔②〕〔③〕三腿与注毒 P1/P2/P4/P5 全空跑。
FLOOR_SEAM_FEED_SITES = 1


# ------------------------------------------------------------------ 取数（跑一次尺，多腿共用）
def _run_census(*extra: str) -> dict[str, Any]:
    """跑尺子本体（CLI 出口，与 S81/S95 门同一条路）。``encoding`` 必钉——本仓铁律 #47★。"""
    out = subprocess.run(
        [sys.executable, str(_CENSUS), "--json", *extra],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
        check=False,
    )
    assert out.returncode == 0, f"普查尺跑不起来（RC={out.returncode}）：{out.stderr[-500:]}"
    payload = json.loads(out.stdout)
    integrity = payload["integrity"]
    assert integrity["ok"] is True, f"尺缺件/读不出/解析失败：{integrity}"
    return payload


_REAL: dict[str, Any] | None = None


def _real() -> dict[str, Any]:
    global _REAL
    if _REAL is None:
        _REAL = _run_census()
    return _REAL


@pytest.fixture()
def census_module() -> Any:
    """在进程内载入尺件（只为直戳 `_state`/`_build_output` 与注毒判据口两用），并复原递归上限。"""
    prev = sys.getrecursionlimit()
    spec = importlib.util.spec_from_file_location("scl3_census_under_test", _CENSUS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.setrecursionlimit(prev)


def _site_key(site: dict[str, Any]) -> tuple[Any, ...]:
    """站点同一性＝(文件, 行, 符号, 标签)。不比对象、不比别的。"""
    return (
        str(site.get("file")),
        site.get("line"),
        str(site.get("symbol")),
        str(site.get("tag")),
    )


# ------------------------------------------------------------------ 判据口（唯一真身）
def _problems(payload: dict[str, Any]) -> list[str]:
    """喂真树或喂合成皆可，返回人读违规清单（空 == 尺自洽）。只读导出，不重算 AST。"""
    problems: list[str] = []
    roster: dict[str, Any] = payload["roster"]
    counts: dict[str, Any] = payload.get("counts", {})
    var_sites = payload.get("meta", {}).get("seam_variable_sites", [])

    for cid, row in sorted(roster.items()):
        raw = list(row.get("offseam_sites") or [])
        exported = row.get("offseam_bypass_sites")
        state = row.get("state")

        # 〔①〕 导出桶 == 滤缝后的原桶，且**同点同下标**（藏位/换位当场红，比作差硬）。
        if exported is None:
            problems.append(f"[导出桶失踪] {cid} 的 roster 行没有 offseam_bypass_sites＝判债侧无尺可读")
            continue
        got = [_site_key(s) for s in exported]
        want = [_site_key(s) for s in raw if str(s.get("tag") or "") != SEAM_FEED_TAG]
        if got != want:
            problems.append(
                f"[导出与语义打架] {cid} offseam_bypass_sites={got} ≠ 同点同下标滤缝外={want}"
                "（喂缝点混进了判债桶，或反过来从桶里消失了）"
            )

        # 〔②〕 桶名不许说谎：state=offseam 却说不出任何一枚非 seam-feed 直呼点。
        if state == "offseam" and not got:
            problems.append(
                f"[三态说谎] {cid} 判成 offseam（桶名＝缝外直呼）却拿不出一枚非 seam-feed 点"
                "＝尺给自己已承认交进中央的那一环挂欠条"
            )
        # 〔③〕 seam-feed 不是免检标签：必须被另一本独立账按 file:line 反证到中央落点。
        for idx, site in enumerate(raw):
            if str(site.get("tag") or "") != SEAM_FEED_TAG:
                continue
            twin = any(
                (site.get("file"), site.get("line")) == (t.get("file"), t.get("line"))
                for bucket in _POSITIVE_BUCKETS
                for t in (row.get(bucket) or [])
            ) or any(
                (site.get("file"), site.get("line")) == (t.get("file"), t.get("line"))
                for t in var_sites
            )
            if not twin:
                problems.append(
                    f"[喂缝无凭] {cid} 第 {idx} 枚 {site.get('file')}:{site.get('line')} 自称"
                    " seam-feed，却在 seam/invoke/generic_sites 与 seam_variable_sites 里反证不到"
                    "中央落点＝拿标签销债，尺不认"
                )

    # 〔④〕 两桶计数与明细同源（藏点让明细 ≠ 账 → 红）。
    detail_raw = sum(len(row.get("offseam_sites") or []) for row in roster.values())
    if detail_raw != counts.get("offseam_sites"):
        problems.append(
            f"[内部自洽] sum(roster offseam_sites)={detail_raw} ≠ "
            f"counts.offseam_sites={counts.get('offseam_sites')}"
        )
    detail_bypass = sum(len(row.get("offseam_bypass_sites") or []) for row in roster.values())
    if detail_bypass != counts.get("offseam_bypass_sites"):
        problems.append(
            f"[内部自洽] sum(roster offseam_bypass_sites)={detail_bypass} ≠ "
            f"counts.offseam_bypass_sites={counts.get('offseam_bypass_sites')}"
        )

    # 〔⑤〕 violations 与判据口同调：它只准数「wired ∧ exec-bypass」，逐 id 等集（缝外判定不得混进来）。
    expect: dict[str, int] = {}
    for cid, row in roster.items():
        if row.get("state") != "wired":
            continue
        for site in row.get("offseam_sites") or []:
            if str(site.get("tag") or "") == "exec-bypass":
                expect[cid] = expect.get(cid, 0) + 1
    listed: dict[str, int] = {}
    for violation in payload.get("violations_second_route") or []:
        cid = str(violation.get("capability_id"))
        listed[cid] = listed.get(cid, 0) + 1
    if listed != expect:
        problems.append(
            f"[取数口漂移] violations_second_route 逐 id 计数 {sorted(listed.items())} ≠ "
            f"roster 现算「wired ∧ exec-bypass」{sorted(expect.items())}"
        )
    return problems


# ------------------------------------------------------------------ 尺件源码级：判据口只准一处
def _verdict_copies_in_source(source: str) -> list[str]:
    """返回「`seam-feed` 这个词在尺里被第二处直触」的位置（判据副本＝病灶本体）。"""
    tree = ast.parse(source)
    verdict = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == SOLE_VERDICT_FN
        ),
        None,
    )
    if verdict is None:
        return [f"找不到唯一判据函数 {SOLE_VERDICT_FN}＝判据口被搬走"]
    verdict_lines = range(verdict.lineno, (verdict.end_lineno or verdict.lineno) + 1)

    constant_def_lines = {
        node.lineno
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "SEAM_FEED_TAG" for t in node.targets)
    }
    if not constant_def_lines:
        return ["找不到 SEAM_FEED_TAG 的常量定义＝标签词被写散在判据里"]

    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == SEAM_FEED_TAG:
            if node.lineno in constant_def_lines or node.lineno in verdict_lines:
                continue
            hits.append(f"标签字面量 seam-feed 直触于 line{node.lineno}（应引 SEAM_FEED_TAG）")
        elif isinstance(node, ast.Compare) and node.lineno not in verdict_lines:
            for comparator in [node.left, *node.comparators]:
                literals = [
                    e.value
                    for e in ([comparator] if isinstance(comparator, ast.Constant)
                              else comparator.elts if isinstance(comparator, (ast.Tuple, ast.List, ast.Set))
                              else [])
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
                if SEAM_FEED_TAG in literals:
                    hits.append(f"第二份缝外判定（比较式含 seam-feed 字面量）@line{node.lineno}")
    return hits


def _feed_sites(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (cid, site)
        for cid, row in sorted(payload["roster"].items())
        for site in (row.get("offseam_sites") or [])
        if str(site.get("tag") or "") == SEAM_FEED_TAG
    ]


# ===========================================================================
# ==== 真树自洽腿：尺自洽 + 活性（本席禁改 leg3 与真身册，故只判「量具不矛盾」）
# ===========================================================================
def test_real_tree_census_is_self_consistent() -> None:
    problems = _problems(_real())
    assert problems == [], "普查尺自相矛盾：\n" + "\n".join(problems)


def test_seam_feed_sites_are_exported_raw_but_never_counted_as_debt() -> None:
    """那一枚（现算 1 枚）必须**仍在原桶里当证据**，同时**不在判债桶里当债**。

    反向自证也在这里：喂缝点若从 `offseam_sites` 消失＝尺藏点（销账），本腿一样红。
    """
    roster = _real()["roster"]
    feed = _feed_sites(_real())
    assert len(feed) >= FLOOR_SEAM_FEED_SITES, (
        f"现算 seam-feed 点数 {len(feed)} < 活性地板 {FLOOR_SEAM_FEED_SITES}＝扫描瞎了/喂缝形被"
        "整形摘净，本锁〔①〕〔②〕〔③〕会空跑（先查尺还在不在扫根 __init__.py，别抬地板）"
    )
    for cid, site in feed:
        row = roster[cid]
        keys_raw = [_site_key(s) for s in (row.get("offseam_sites") or [])]
        keys_bypass = [_site_key(s) for s in (row.get("offseam_bypass_sites") or [])]
        assert _site_key(site) in keys_raw, f"{cid} 的喂缝点从原桶消失了＝藏点销账"
        assert _site_key(site) not in keys_bypass, (
            f"{cid} @ {site.get('file')}:{site.get('line')} 被尺自己判成 seam-feed"
            "（「交给中央、非缝外」）却仍留在判债桶里＝桶名说谎，按桶名读债必假报"
        )
        assert row.get("state") != "offseam", f"{cid} 仅因喂缝点就被判成 offseam 态"


def test_direction_accounts_diverge_only_by_feed_points() -> None:
    """两桶计数之差必须恰好＝喂缝点数（多一枚少一枚都红），且不设债数上下限。"""
    payload = _real()
    counts = payload["counts"]
    raw = int(counts.get("offseam_sites", 0))
    bypass = int(counts.get("offseam_bypass_sites", 0))
    feed = len(_feed_sites(payload))
    assert raw - bypass == feed, f"原桶 {raw} − 判债桶 {bypass} ≠ 喂缝点 {feed}＝扣的不是缝外语义"
    assert bypass <= raw, "判债桶比原桶还大＝过滤反倒加账（尺自己造出第二通路）"


# ===========================================================================
# ==== 判据口唯一腿：尺件里不许有第二份 seam-feed 判定
# ===========================================================================
def test_ruler_has_a_single_seam_feed_verdict_site() -> None:
    hits = _verdict_copies_in_source(_CENSUS.read_text(encoding="utf-8"))
    assert hits == [], (
        f"尺件里出现第二份缝外判定：{hits}＝两把尺会各自漂移；"
        "本次归因的根形正是「violations 自己滤、_state 读原桶、导出交原桶」三套并存"
    )


def test_ruler_tag_word_matches_this_lock() -> None:
    """本件与尺件对「seam-feed」这个词必须一字不差（两本词汇表漂移＝锁失去所指）。"""
    tree = ast.parse(_CENSUS.read_text(encoding="utf-8"))
    value = next(
        (
            node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "SEAM_FEED_TAG" for t in node.targets)
            and isinstance(node.value, ast.Constant)
        ),
        None,
    )
    assert value == SEAM_FEED_TAG, f"尺件里的缝外标签词是 {value!r}，本锁钉的是 {SEAM_FEED_TAG!r}"


def test_poison_second_verdict_copy_in_ruler_is_red() -> None:
    """注毒 P3（判据被拆两处）：正向＝真尺 `== []`（上一腿），反向＝合成尺件源码必被抓。

    合成件写在**本测试文件内**（字符串字面量），落盘与尺件一个字节都不碰。
    """
    synthetic = '''
SEAM_FEED_TAG = "seam-feed"
SECOND_ROUTE_TAGS = frozenset({"exec-bypass", "assembly-wrap"})


def is_offseam_bypass(site):
    return site.get("tag") != SEAM_FEED_TAG


def _state(cid, offseam):
    if any(s["tag"] != "seam-feed" for s in offseam.get(cid, [])):  # 第二份判据
        return "offseam"
    return "none"


def _build_output(roster):
    for row in roster.values():
        row["bypass"] = [s for s in row["offseam_sites"] if s["tag"] not in ("seam-feed",)]
    return roster


def _violations(row):  # 合法：回答的是另一个问题（名字引用，不含 seam-feed 字面量）
    return [s for s in row["offseam_sites"] if s["tag"] in SECOND_ROUTE_TAGS]
'''
    hits = _verdict_copies_in_source(synthetic)
    assert len(hits) >= 2, f"合成尺件里两副本该被抓，实到 {hits}＝结构锁杀伤力塌了"
    assert any("比较式含 seam-feed" in h for h in hits), hits


# ===========================================================================
# ==== 注毒腿：导出未过滤 / 喂缝无凭 / 判据拆两处 / 判据恒真 / 三态说谎
# ===========================================================================
def _victim_feed_cid(payload: dict[str, Any]) -> str:
    feed = _feed_sites(payload)
    assert feed, "真树里没有 seam-feed 点位＝注毒失去落点，先查扫描面活性再动判据，别删本腿"
    return feed[0][0]


def _offseam_only_row_payload(*, with_central_twin: bool = True) -> dict[str, Any]:
    """合成台架：一行「只带 seam-feed 点、却把 state 写成 offseam」的矛盾 payload。

    **只改内存里的真普查输出**，尺件与源码树一个字节不写；两桶计数同步进 ``counts``
    （⇒ 〔④〕计数腿安静），注毒只落在「三态说谎」这一形上。
    """
    real = _real()
    payload = copy.deepcopy(real)
    feed_site = {
        "file": "plugins/bot_unified_runtime/__init__.py",
        "line": 6242,
        "surface": "plugins",
        "symbol": "build_feed_only_capability",
        "tag": SEAM_FEED_TAG,
        "enclosing": "_poke_feed_only",
    }
    payload["roster"]["s911.feed.only"] = {
        "declared": False,
        "state": "offseam",  # 说谎位：桶名自称缝外直呼，明细里却只有喂缝点
        "decl": [],
        "seam_sites": [
            {"file": feed_site["file"], "line": feed_site["line"], "surface": "plugins",
             "fn": "orchestrated_command", "via_default": False}
        ] if with_central_twin else [],
        "invoke_sites": [],
        "generic_sites": [],
        "offseam_sites": [dict(feed_site)],
        "offseam_bypass_sites": [],  # 尺按 seam-feed 滤掉——导出侧合规
        "entry_forms": [],
        "test_sites": [],
        "unknown_sites": [],
    }
    payload["counts"]["offseam_sites"] += 1
    return payload


def test_poison_export_reverts_to_raw_bucket_is_red() -> None:
    """注毒 P1（导出改回未过滤原桶）：判债桶 == 原桶 ⇒ 与尺自己的「非缝外」语义打架 ⇒ 〔①〕必红。"""
    real = _real()
    cid = _victim_feed_cid(real)
    raw = copy.deepcopy(real["roster"][cid]["offseam_sites"])
    poisoned = copy.deepcopy(real)
    poisoned["roster"][cid]["offseam_bypass_sites"] = raw  # 未过滤原桶
    poisoned["counts"]["offseam_bypass_sites"] = poisoned["counts"]["offseam_sites"]

    problems = _problems(poisoned)
    assert any("[导出与语义打架]" in p and cid in p for p in problems), (
        f"导出改回未过滤原桶竟没被抓＝本锁空转：{problems}"
    )
    # 归因唯一：本毒只该动导出侧，三态腿与两桶计数自证都不该顺手响。
    assert not any("[三态说谎]" in p for p in problems), problems
    assert not any("[内部自洽]" in p for p in problems), problems


def test_poison_feed_point_without_central_twin_is_red() -> None:
    """注毒 P2（真旁路盖喂缝章销债）：抽走正证据 ⇒ 反证不到中央落点 ⇒ 〔③〕必红。"""
    real = _real()
    cid = _victim_feed_cid(real)
    row = real["roster"][cid]
    idx = next(
        i
        for i, site in enumerate(row["offseam_sites"])
        if str(site.get("tag") or "") == SEAM_FEED_TAG
    )
    poisoned = copy.deepcopy(real)
    for bucket in _POSITIVE_BUCKETS:  # 把这一线的中央落点摘干净
        poisoned["roster"][cid][bucket] = [
            s for s in (row.get(bucket) or []) if s.get("line") != row["offseam_sites"][idx]["line"]
        ]
    poisoned["meta"]["seam_variable_sites"] = [
        s for s in poisoned["meta"].get("seam_variable_sites", [])
        if not (s.get("file") == row["offseam_sites"][idx]["file"]
                and s.get("line") == row["offseam_sites"][idx]["line"])
    ]

    problems = _problems(poisoned)
    assert any("[喂缝无凭]" in p and cid in p for p in problems), (
        f"自称 seam-feed 却反证不到中央落点的点没被抓＝标签成了豁免抽屉：{problems}"
    )
    assert not any("[导出与语义打架]" in p for p in problems), (
        f"本毒只该打反证腿，导出侧过滤规则未变不该响＝归因不唯一：{problems}"
    )


def test_degenerate_verdict_is_caught_on_the_ruler_itself(census_module: Any) -> None:
    """注毒 P4（判据口恒真＝退化回"按原桶算债"）：在尺件上**真跑**，只改名字不改文件。

    正向先证尺当前形状（三态 ``none``、导出空桶、原桶仍在、violations 不响），
    反向再证「一旦缝外判定被掏空，债账当场虚增」＝这条判据真的在管三处账，不是空跑。
    """
    feed_only = {
        "file": "plugins/bot_unified_runtime/__init__.py",
        "line": 4242,
        "surface": "plugins",
        "symbol": "build_feed_only_capability",
        "tag": SEAM_FEED_TAG,
        "enclosing": "_poke_feed_only",
    }

    cen = census_module.Census([])
    cen.offseam["s911.feed.only"] = [dict(feed_only)]
    assert cen._state("s911.feed.only") == "none", (
        "只带 seam-feed 点被判成 offseam＝_state() 退化为按原桶算（与 _inside_feed 语义打架）"
    )
    out = cen._build_output([])
    row = out["roster"]["s911.feed.only"]
    assert row["offseam_bypass_sites"] == [], row["offseam_bypass_sites"]
    assert len(row["offseam_sites"]) == 1, "喂缝证据从原桶消失了＝藏点"
    assert out["counts"]["offseam_bypass_sites"] == 0
    assert out["violations_second_route"] == []
    assert any("[喂缝无凭]" in p for p in _problems(out)), (
        "喂缝点失反证却没被 _problems 抓到＝本锁与尺的账对不上"
    )

    # 反向对照：同一形状换成 exec-bypass 必须判 offseam（判据没被反向掏空成"谁都无罪"）。
    control = census_module.Census([])
    control.offseam["s911.bypass.only"] = [{**feed_only, "line": 4243, "tag": "exec-bypass"}]
    assert control._state("s911.bypass.only") == "offseam", (
        "旁路点没判 offseam＝缝外判据被反向掏空，债一起被滤掉"
    )

    # 注毒：判据口恒真（＝把"滤缝"这一步摘掉，导出侧退化回未过滤原桶）⇒ 三态说谎 + 导出打架。
    original = census_module.is_offseam_bypass
    try:
        census_module.is_offseam_bypass = lambda site: True
        degenerate = census_module.Census([])
        degenerate.offseam["s911.feed.only"] = [dict(feed_only)]
        assert degenerate._state("s911.feed.only") == "offseam", (
            "注毒后仍判 none＝_state() 根本没用判据口（第二份规则在别处）"
        )
        problems = _problems(degenerate._build_output([]))
        assert any("[导出与语义打架]" in p for p in problems), (
            f"判据口被掏空（导出退化回未过滤原桶）没被〔①〕腿抓到＝本锁空转：{problems}"
        )
        assert any("[喂缝无凭]" in p for p in problems), problems
    finally:
        census_module.is_offseam_bypass = original
    restored = census_module.Census([])
    restored.offseam["s911.feed.only"] = [dict(feed_only)]
    assert restored._state("s911.feed.only") == "none", "判据口没复原＝污染了同进程其它腿"


def test_poison_state_labels_feed_point_as_debt_is_red() -> None:
    """注毒 P5（三态说谎的纯合成台架）：导出为空却把 id 判成 offseam ⇒ 〔②〕腿必红。

    为何需要合成件：真尺里 ``_state()`` 与导出侧**共用同一个判据口**，所以"只让三态退化、
    导出不动"这种形状在真尺上不可达——那正是本锁要证的「判据口只有一处」。要单独钉住
    〔②〕腿的杀伤力，只能喂合成 payload。

    同一行必须同时被正证据账反证到（``seam_sites`` 6242 有孪生）⇒ 本毒只该响〔②〕，
    不该顺手响〔③〕喂缝无凭／〔①〕导出打架／〔④〕计数（两桶计数同步进 counts，故〔④〕安静）。
    独立性自证（防"两腿其实是同一条判据在响"）：把反证账摘掉 ⇒ 〔③〕喂缝无凭新响，而
    〔②〕说谎照旧响——〔②〕只看 state＋判债桶、〔③〕只看正证据账，两条判据彼此独立。
    """
    payload = _offseam_only_row_payload()
    problems = _problems(payload)
    assert any("[三态说谎]" in p and "s911.feed.only" in p for p in problems), (
        f"只带 seam-feed 点被判成 offseam 竟没被抓＝说谎腿空转：{problems}"
    )
    assert not any("[喂缝无凭]" in p and "s911.feed.only" in p for p in problems), problems
    assert not any("[导出与语义打架]" in p and "s911.feed.only" in p for p in problems), problems
    assert not any("[内部自洽]" in p for p in problems), problems

    blind = _offseam_only_row_payload(with_central_twin=False)
    problems_blind = _problems(blind)
    assert any("[喂缝无凭]" in p and "s911.feed.only" in p for p in problems_blind), problems_blind
    assert any("[三态说谎]" in p and "s911.feed.only" in p for p in problems_blind), problems_blind
    assert not any("[导出与语义打架]" in p and "s911.feed.only" in p for p in problems_blind)

