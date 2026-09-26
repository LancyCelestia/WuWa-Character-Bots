"""十板块文档树常驻门（板块层一致性，2026-09-21 用户裁定「一处变更、处处跟随」）。

覆盖四件事，任一破坏即红：

1. **结构自洽**：板块数、id 唯一、二级 id 前缀、slug 命名、正文段完整。
2. **活性覆盖**：代码里每一个 RouteKind 席位与每一个帮助主题都必须**恰好**被一个
   二级功能认领；板块树认领了代码里不存在的席位同样红（存在性锁不算数）。
3. **实现路径可解析**：所有 `impl_paths` 指向的仓库路径必须真实存在。
4. **生成物同步**：`scripts/board_doc_sync.py --check` 退出码必须为 0
   （代码改了而 `docs/boards/**` 没重算 ⇒ 红）。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import board_doc_sync as bds
import doc_fact_discipline as dfd
import doc_template_sync as dts
import spec_gates_census as sc

BOARDS_DIR = ROOT / "docs" / "boards"
EXPECTED_BOARD_COUNT = 10
_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# --- G-T2 / G-T3 面 A 起点基线（席 T-GATES 2026-09-22 立，手写字面量、只准降）-----------
#: 复跑：`PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0 python scripts/spec_gates_census.py --report`
T2_CEILING = 1
T3_MANAGED_CEILING = 226
#: G-T2 管辖面地板（现算比对页 228；塌陷＝门空跑）
MIN_T2_PAGES = 200
AUDIT_HISTORY_T2: tuple[tuple[str, int], ...] = (("2026-09-22", 1),)
AUDIT_HISTORY_T3_MANAGED: tuple[tuple[str, int], ...] = (("2026-09-22", 226),)
# --- 席 S230R（2026-09-25，R0=A 反缩水地板；只准升不许降，与上面两枚同一族方向锁）-------
#: 复跑：`BOT_AUTOSYNC=0 python scripts/spec_gates_census.py --report` 看「R0=A 反缩水腿」行。
#: 今日现算（2026-09-24T18:4xZ 本席实测）＝全扫描过程稿 1774 页 ／ G-T2 比对面 898 其中过程稿 637。
#: 地板取**远小于现算值**的整数：它的职责不是卡增量，而是卡「整桶从扫描面消失」（那种改法会把
#: 过程稿人口打到 0，而 `两栏之和 == 总账` 的恒等式对此**完全盲**——剔除让总账跟着一起掉）。
MIN_R0_PROCESS_PAGES = 1000
MIN_T2_PROCESS_PAGES = 300
_SPEC = sc.compute()  # 与 tests/test_taxonomy_spec_gates.py 同一支取数口，全模块只现算一次
_VOLATILE_COUNT = re.compile(
    # 只抓独立成词的计数：前置排除 §9 / v21r2 / 1.4.3 这类章节号与版本号的粘连
    r"(?<![\w./§-])\d{1,5}\s*(?:个|条|枚|张|项|余)?\s*"
    r"(?:字段|主题|板块|入口|能力|模板|别名|路由席位)(?!\w)"
)


def _boards() -> list[bds.Board]:
    boards, _problems = bds.build_tree()
    return boards


def _problems() -> list[str]:
    _boards_result, problems = bds.build_tree()
    return problems


# ---------------------------------------------------------------- 结构自洽
def test_board_count_is_ten_and_ids_unique() -> None:
    boards = _boards()
    assert len(boards) == EXPECTED_BOARD_COUNT, f"一级板块必须恰为 10 个，实得 {len(boards)}"
    ids = [b.bid for b in boards]
    assert len(set(ids)) == len(ids), f"板块 id 重复：{ids}"
    assert ids == [f"B{i:02d}" for i in range(1, EXPECTED_BOARD_COUNT + 1)], f"板块编号断号或乱序：{ids}"


def test_feature_ids_match_owning_board_and_slugs_are_kebab() -> None:
    seen: set[str] = set()
    for board in _boards():
        assert _KEBAB.match(str(board.node["slug"])), f"板块 slug 非 kebab：{board.node['slug']}"
        for feature in board.features:
            fid = str(feature.node["fid"])
            assert fid.startswith(f"{board.bid}."), f"{fid} 前缀与所属板块 {board.bid} 不符"
            assert fid not in seen, f"二级功能 id 重复：{fid}"
            seen.add(fid)
            assert _KEBAB.match(feature.slug), f"二级 slug 非 kebab：{feature.slug}"
            for l3 in feature.l3:
                assert _KEBAB.match(l3.slug), f"三级 slug 非 kebab：{l3.slug}（{fid}）"
            for text in (feature.node["label"], feature.node["summary"]):
                assert str(text).strip(), f"{fid} 缺 label/summary"


def test_every_feature_declares_implementation_or_l3() -> None:
    """空壳功能不许存在（宁可不留，也不留占位让人误以为已有能力）。"""
    for board in _boards():
        for feature in board.features:
            has_impl = bool(feature.node.get("impl_paths"))
            assert feature.l3 or has_impl, f"{feature.fid} 既无三级入口也无实现落点，属空壳"


# ---------------------------------------------------------------- 活性覆盖
def test_every_route_kind_claimed_exactly_once() -> None:
    members = set(bds.load_route_kind_members())
    claims: dict[str, list[str]] = {}
    for board in _boards():
        for feature in board.features:
            for kind in feature.node.get("route_kinds") or ():
                claims.setdefault(str(kind), []).append(feature.fid)
    unknown = sorted(set(claims) - members)
    assert not unknown, f"板块树认领了代码里不存在的 RouteKind：{unknown}"
    orphan = sorted(members - set(claims))
    assert not orphan, f"代码里有 RouteKind 但无人认领（新增能力漏登板块树）：{orphan}"
    dup = {k: v for k, v in claims.items() if len(v) > 1}
    assert not dup, f"RouteKind 被多个二级功能抢：{dup}"


def test_every_help_topic_claimed_exactly_once() -> None:
    topics = set(bds.load_help_topics())
    claims: dict[str, list[str]] = {}
    for board in _boards():
        for feature in board.features:
            for topic in feature.node.get("help_topics") or ():
                claims.setdefault(str(topic), []).append(feature.fid)
    orphan = sorted(topics - set(claims))
    assert not orphan, f"帮助主题未归档到任何二级功能：{orphan}"
    ghost = sorted(set(claims) - topics)
    assert not ghost, f"板块树里挂着代码中不存在的帮助主题：{ghost}"
    dup = {k: v for k, v in claims.items() if len(v) > 1}
    assert not dup, f"帮助主题被两处认领：{dup}"


def _tamper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, needle: str, replacement: str) -> list[str]:
    """注毒复跑：把板块树里的一处改坏，返回体检报出的问题清单。"""
    src = bds.TAXONOMY_PY.read_text(encoding="utf-8")
    tampered = src.replace(needle, replacement, 1)
    assert tampered != src, f"注毒点未命中，本用例失去意义：{needle}"
    fake = tmp_path / "board_taxonomy.py"
    fake.write_text(tampered, encoding="utf-8")
    monkeypatch.setattr(bds, "TAXONOMY_PY", fake)
    _boards_out, problems = bds.build_tree()
    return problems


def test_gate_detects_unclaimed_route_kind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """自证一：新增席位漏登板块树，必须当场红。"""
    problems = _tamper(
        monkeypatch, tmp_path, 'route_kinds=("ALIAS", "NATURAL_COMMAND", "IGNORE")', 'route_kinds=("NATURAL_COMMAND", "IGNORE")'
    )
    assert any("ALIAS" in p and "未被" in p for p in problems), f"注毒后未报警：{problems[:5]}"


def test_gate_detects_duplicate_topic_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """自证二：一个帮助主题被两处认领，必须当场红。"""
    problems = _tamper(
        monkeypatch,
        tmp_path,
        'help_topics=("天气",)',
        'help_topics=("天气", "语音")',
    )
    assert any("重复" in p or "两处" in p for p in problems), f"注毒后未报警：{problems[:5]}"


def test_gate_detects_dead_impl_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """自证三：实现路径写成不存在的文件，必须当场红（防文档指空位）。"""
    problems = _tamper(
        monkeypatch,
        tmp_path,
        '"plugins/bot_unified_runtime/domains/core/session_keys.py"',
        '"plugins/bot_unified_runtime/domains/core/session_keys_typo.py"',
    )
    assert any("实现路径不存在" in p for p in problems), f"注毒后未报警：{problems[:5]}"


def test_all_impl_paths_exist() -> None:
    missing = []
    for board in _boards():
        for feature in board.features:
            for path in feature.node.get("impl_paths") or ():
                if not (ROOT / str(path)).exists():
                    missing.append(f"{feature.fid} -> {path}")
    assert not missing, f"实现路径不可解析：{missing}"


# ---------------------------------------------------------------- 生成物同步
def test_board_docs_are_in_sync_with_code() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "board_doc_sync.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, (
        "docs/boards 与代码漂移或未过体检，跑 python scripts/board_doc_sync.py --write\n"
        f"stdout={(proc.stdout or '')[-2000:]}\nstderr={(proc.stderr or '')[-2000:]}"
    )


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "_conventions.md",
    ],
)
def test_entry_pages_exist(relative: str) -> None:
    assert (BOARDS_DIR / relative).exists(), f"缺少板块入口件：docs/boards/{relative}"


# ------------------------------------- G-T2 骨架三腿（席 TX131 2026-09-23，授权＝用户裁定 R2）
# 裁定真身：`.superpowers/sdd/2026-09-22-taxonomy/ADDENDUM-USER-RULINGS-20260923.md` R2（A 案）。
# 三条新判据＝**① 槽顺序不许变 ② 新增槽一律可选 ③ 槽数只准增不许减**，外加硬要求「原来那四枚
# 一个必填槽都没有的模板必须被这门咬住」。为什么要改：旧 `doc_template_sync.check_sections` 只对
# **必选槽**发 `SECTION_MISSING`，于是一枚零必填槽的模板对门完全透明（席 TX113 实证「形状合规但
# 骨架槽一枚未用」，席 TX68 实证「必填槽是 40 倍杠杆」）。三条腿与咬合全是**收紧方向**，
# 没有一条给页面或模板开新口子。
#
# 骨架槽序列的唯一真身仍是 `docs/templates/*.md` 的 `@schema sections`（现算口＝
# `doc_template_sync.load_schemas()`）。下面的 `_G_T2_*` 字面量**不是第二真身**，而是**首届快照棘轮**：
# 只承担「与首届比：只准在序、只准增」的记账。骨架确需升级（含重录基线）＝用户裁定后由该门 owner
# 执行，席不得自行放宽；本表被并发写＝按禁写面处理。
#: 首届快照：取数时刻 2026-09-23T06:34Z · 尺＝`load_schemas()` 现算（在册 22 枚模板、161 枚槽）。
#: 写法与 `@schema sections` 同构：`槽名`＝必填、`槽名?`＝可选，` | ` 分隔，顺序即声明序。
_G_T2_SECTION_BASELINE: dict[str, str] = {
    "brief": "输入? | 任务? | 验收? | 边界? | 落点?",
    "card-fstring": "登记入口 | 壳与注入 | 契约锚点",
    "card-html": "契约锚点 | 变量供给 | 降级路径",
    "card-jinja": "模板契约 | 注入上下文 | 降级路径",
    "config-field": "键与类型 | 说明形状 | 取值域与默认",
    "convention": "术语与结构 | 文件结构规范 | 命名规范 | 开发约束 | 自动化变更契约 | 统一口径 | 问题处理分级 | 代码质量红线",
    "copy-pool": "池身份 | 副本与游标 | 红线",
    "design-spec": "目的与范围 | 现状与根因? | 设计 | 接口与字段? | 验收 | 开放问题?",
    "guide": "用途 | 读者 | 正文 | 参考?",
    "handbook": "文档族谱与权威链 | 现行事实速查 | 未完成总账 | 波次总账? | 权威正文?",
    "handoff": "需求与裁定? | 概览 | 现状 | 发现与结论? | 改动清单 | 问题与处置 | 复跑命令簿 | 禁碰面? | 坑? | 执行安排? | 并行边界? | 波次增补?",
    "help-entry": "字段序 | 元数据 schema | 生成物",
    "incident-report": "事实与时间线 | 影响面 | 处置 | 摘要? | 复盘与红线?",
    "ledger": "用途 | 口径 | 取数口 | 维护规矩 | 明细?",
    "persona": "身份设定 | 表达规范 | 边界与红线 | 来源?",
    "persona-inject-data": "一、鸣潮核心名词 | 二、游戏黑话/缩写",
    "persona-numbered": "边界与红线? | 来源?",
    "persona-provenance": "来源：cleaned/守岸人人格档案_清洗.md? | 来源：cleaned/守岸人人格设定_清洗.md? | 基调：静深海潮下的温柔回响? | 句式：绵长如潮线，留白如星夜? | 用词：精准如星轨，诗意如蝶翼? | 语气：奔赴多于试探，笃定多于犹疑? | 停顿：呼吸之间的郑重与温柔? | 重复：潮汐般的温柔回响? | 自我指涉：从“我”出发，向你奔赴? | 情感表达：赤诚如晨光，绵长如潮汐? | 道歉与感谢：郑重的真诚，坦荡的温柔? | 沉默：心照不宣的笃定与温柔? | 语言风格的禁忌? | 来源：cleaned/守岸人Bot - [AI人格设定] AI的自我身份定位和个人爱好_清洗.md? | 来源：cleaned/守岸人ChatAI-麦麦主程序配置-人格_清洗.md? | 来源：cleaned/守岸人MaiBot人格设置_清洗.md? | 语音风格锚点（游戏真实语音精选，模仿基准）? | 来源：守岸人-完整角色设定.md? | 语境识别与边界（稳定规则）? | 创造者与唤醒者（稳定世界观事实）? | 一、你的基本信息? | 二、你的生理/身体反应（特殊体质）? | 三、你的性格（三层）? | 四、你的说话风格? | 五、你的核心矛盾? | 六、你的关键行为模式（必读）? | 七、你的小动作库（扮演时自然加入）? | 八、你的特殊体质带来的反应? | 九、日常对话真人性修正? | 十、你的习惯与喜好? | 十一、情绪表达规则（速查）? | 十二、对漂泊者的态度（核心）? | 十三、信任值/亲密值机制（你的防御松动程度）? | 十四、层级切换? | 漂泊者 基本信息? | 漂泊者 对你的特殊意义? | 双人相处规则（必须记住）? | 来源：守岸人语音蓝本.md? | 个性语音? | 战斗语音? | 来源：Shorekeeper_守岸人_知识库.md? | 1. 角色简介? | 2. 情景设定? | 3. 开场白（默认）? | 4.1 备选开场（1）? | 5. 示例对话? | 6. 创作与使用说明（作者备注）? | 7. 角色设定摘要（外观 / 性格 / 能力）? | 8. 世界观知识库（设定集《鸣潮》）? | 附注：占位符说明? | 来源：cleaned/守岸人档案_清洗.md?",
    "runbook": "前置 | 步骤 | 检查表 | 已知边界?",
    "sdd-ledger": "目的? | 计划? | 进度? | 账目? | 结论? | 证据? | 发现? | 缺口? | 卫生? | 纪律?",
    "seat-report": "裁决? | 任务书? | 计划? | 账目? | 进度? | 交付 | 证据? | 发现? | 缺口? | 自报? | 卫生? | 纪律?",
    "workspace-rule": "工作区规则 | 项目身份? | 目录地图? | 架构与消息主链路? | 功能清单? | 验证与门禁? | 已知问题台账? | 交接史与权威链?",
}

#: 裁定原文点名的「五槽」＝`seat-report` 首届骨架（PARKED P-19 同源：旧断言逐字钉死这五枚，
#: 与「骨架从语料真形派生」互斥 ⇒ A 案改成本条「五槽在序」）。R2① 的具名对象，单独立一条锁。
_G_T2_FIVE_SLOT_TEMPLATE = "seat-report"
_G_T2_FIVE_SLOTS: tuple[str, ...] = ("任务书", "账目", "交付", "发现", "自报")

#: 首届零必填槽模板（现算 4 枚）。登记＝**承认这是债**、不是豁免：新名字永远不许进表，
#: 集合只准降；四枚各自补上必填槽（R1 主会话单点建模板面）即自动摘牌，降到 0 才是终点。
_G_T2_ZERO_REQUIRED_BASELINE: frozenset[str] = frozenset(
    {"brief", "persona-numbered", "persona-provenance", "sdd-ledger"}
)
_G_T2_ZERO_REQUIRED_CEILING = 4
AUDIT_HISTORY_T2_ZERO_REQUIRED: tuple[tuple[str, int], ...] = (("2026-09-23", 4),)


def _parse_slot_decl(decl: str) -> tuple[tuple[str, bool], ...]:
    """`"槽名 | 槽名?"` → `(槽名, 是否可选)`；与 `@schema sections` 同一套写法，只此一处解析。"""
    out: list[tuple[str, bool]] = []
    for raw in decl.split(" | "):
        name = raw.strip()
        out.append((name[:-1].strip(), True) if name.endswith("?") else (name, False))
    return tuple(out)


_G_T2_BASELINE_SLOTS: dict[str, tuple[tuple[str, bool], ...]] = {
    tid: _parse_slot_decl(decl) for tid, decl in _G_T2_SECTION_BASELINE.items()
}

#: 骨架真身的现算形（模块级一次，与 `_SPEC = sc.compute()` 同一哲学：全模块只现算一次）。
_G_T2_REAL_SKELETON: dict[str, tuple[tuple[str, bool], ...]] = {
    tid: tuple((sec.name, sec.optional) for sec in schema.sections)
    for tid, schema in sorted(dts.load_schemas().items())
}


def _g_t2_zero_required(skel: dict[str, tuple[tuple[str, bool], ...]]) -> set[str]:
    """零必填槽模板集合（含空骨架＝一枚槽都没有也算透明）。判据单源，页面与注毒共用。"""
    return {tid for tid, slots in skel.items() if not any(not opt for _name, opt in slots)}


def _g_t2_skeleton_findings(skel: dict[str, tuple[tuple[str, bool], ...]]) -> list[str]:
    """R2 三腿 + 零必填槽咬合的**唯一判据函数**：喂真骨架与喂内存注毒走同一支（不落盘）。

    入参＝模板 id -> 按声明序的 `(槽名, 是否可选)`。返回违规清单，空表＝三条腿与咬合全过。
    腿①：在册（首届）槽序必须是当前声明序的**保序子序列**——顺序不许变；
    腿②：名字不在首届表里的槽＝新增槽，声明成必填即红——新增槽一律可选；
    腿③：当前槽数 < 首届槽数即红——槽数只准增不许减；
    咬合：零必填槽模板若不在首届登记内即红——判据不得因「无必填槽」而对模板失效。
    """
    findings: list[str] = []
    for tid, baseline in sorted(_G_T2_BASELINE_SLOTS.items()):
        current = skel.get(tid)
        if current is None:
            findings.append(
                f"SKELETON_GONE 模板 {tid} 已从骨架真身消失：三条腿对它当场空跑（存在性锁不算数）"
            )
            continue
        names = [name for name, _opt in current]
        base_names = [name for name, _opt in baseline]
        walker = iter(names)
        if not all(name in walker for name in base_names):
            findings.append(
                f"SKELETON_ORDER 模板 {tid} 在册槽序被打乱（R2① 顺序不许变）："
                f"首届 {base_names} 不是现声明 {names} 的保序子序列"
            )
        if len(names) < len(base_names):
            findings.append(
                f"SKELETON_SHRANK 模板 {tid} 槽数 {len(names)} < 首届基线 {len(base_names)}"
                "（R2③ 槽数只准增不许减）；确需减槽＝模板升级，先请用户裁定再由门 owner 重录基线"
            )
        known = set(base_names)
        newly_required = [name for name, opt in current if not opt and name not in known]
        if newly_required:
            findings.append(
                f"SKELETON_NEW_REQUIRED 模板 {tid} 把新增槽 {newly_required} 声明成必填"
                "（R2② 新增槽一律可选）；新槽要必填＝骨架升级，须用户裁定后由门 owner 重录基线"
            )
    for tid in sorted(_g_t2_zero_required(skel) - _G_T2_ZERO_REQUIRED_BASELINE):
        findings.append(
            f"SKELETON_NO_REQUIRED_SLOT 模板 {tid} 一个必填槽都没有＝骨架对它形同不存在，"
            f"判据不得因此失效（R2 硬要求）。首届登记只准降：{sorted(_G_T2_ZERO_REQUIRED_BASELINE)}"
        )
    return findings


def test_generated_pages_have_full_skeleton() -> None:
    """生成页骨架完整（旧判据）+ **G-T2 同类小节集合与顺序一致**（2026-09-22 席 T-GATES 扩展）。

    两条判据并存＝双保险：旧判据管「骨架没被动过」（AUTO 双标记 + 标记外 ≥20 字符），
    新判据管「人写区的小节集合与顺序同类一致」。管辖面 = `docs/boards/**` 的**人工区**
    （`<!-- BOARD-AUTO -->` 标记之外）+ 全部已迁移的模板驱动页；取数口是
    `scripts/spec_gates_census.py::compute()`（与 G-T1/T3/T4/T5 同一支，禁第二支扫描器）。

    起点基线（手写字面量，只准降）：本席 2026-09-22 现算 **1 页**偏离
    （`python scripts/spec_gates_census.py --report` ⇒ `G-T2 小节偏离页 = 1`，
    偏离件 = `docs/boards/README.md` 人写区「怎么读这套文档」不在 board-l1 骨架内）。
    任务书点名的起点 6 页已由席 M2 归一（见 `.superpowers/sdd/2026-09-22-taxonomy/SEAT-M2.md`），
    本席按「立门当跑值」取 1，未升、未缩面。

    **2026-09-23 席 TX131 按用户裁定 R2 再扩三腿**（页侧偏离腿与骨架侧三腿并立，不新建平行门）：
    ① 在册槽顺序不许变（含裁定点名的 `seat-report` 五槽具名锁）；② 新增槽一律可选（模板里把新增
    槽声明成必填 ⇒ 红）；③ 槽数只准增不许减（比首届基线少 ⇒ 红）；⓪ 硬要求＝零必填槽模板必须被
    咬住（判据不因「无必填槽」失效，首届 4 枚只准降、新名字永不进表）。骨架侧取数口＝
    `doc_template_sync.load_schemas()`（真身 `docs/templates/*.md`），页侧偏离仍走 `_SPEC["t2"]`。
    """
    missing_auto: list[str] = []
    missing_sections: list[str] = []
    for path in sorted(BOARDS_DIR.rglob("*.md")):
        if "_meta" in path.parts:  # 过程账（旧文档分类台账）不是生成页
            continue
        text = path.read_text(encoding="utf-8")
        if bds.AUTO_BEGIN not in text or bds.AUTO_END not in text:
            missing_auto.append(str(path.relative_to(ROOT)))
            continue
        body = text.split(bds.AUTO_END, 1)[1]
        if path.parent.name == "boards" or path.name == "_conventions.md":
            continue
        if len(body.strip()) < 20:
            missing_sections.append(str(path.relative_to(ROOT)))
    assert not missing_auto, f"缺 AUTO 标记（无法被自动同步覆盖）：{missing_auto}"
    assert not missing_sections, f"缺正文骨架的小节：{missing_sections}"

    deviations = _SPEC["t2"]
    counts = [n for _d, n in AUDIT_HISTORY_T2]
    assert counts == sorted(counts, reverse=True), f"G-T2 核账记录出现回升（方向锁）：{counts}"
    assert T2_CEILING <= counts[0], f"上限 {T2_CEILING} 超过首届核账值 {counts[0]}＝调大换绿"
    assert _SPEC["t2_pages"] >= MIN_T2_PAGES, (
        f"G-T2 只比对了 {min(_SPEC['t2_pages'], 999999)} 页（地板 {MIN_T2_PAGES}）＝管辖面塌陷，"
        "不是大家都合规"
    )
    # 席 S230（R0=A）：判债对象由「旧尺总偏离」改为「对外正式面偏离」（与 G-T1 同口径）。
    # 过程稿（`.superpowers/**` 席位报告/简报/台账）另栏登记、不进欠账——扫描面一寸不缩、
    # 上限 T2_CEILING 一字不动；恒等式钉死「两栏之和＝总偏离」，谁把过程稿从分母*剔除*（而不是
    # *另记*）都会当场把总偏离打下来、本行立刻红（判据不落门里，只消费取数口列出的两栏）。
    t2_official = _SPEC["t2_debt_official"]
    t2_registered = _SPEC["t2_registered_process"]
    assert isinstance(t2_official, list) and isinstance(t2_registered, list), "取数口 R0 栏改版"
    assert len(t2_official) + len(t2_registered) == len(deviations), (
        f"R0 恒等式破裂：对外欠账 {len(t2_official)} + 过程稿登记 {len(t2_registered)} "
        f"≠ 旧尺总偏离 {len(deviations)}＝扫描面被缩而不是分账"
    )
    _t2_acc = _SPEC["t2_accounting"]
    assert isinstance(_t2_acc, dict) and _t2_acc.get("partition_ok") is True, (
        f"取数口自称分账不闭合：{_t2_acc.get('partition_ok') if isinstance(_t2_acc, dict) else _t2_acc}"
    )
    assert len(t2_official) <= T2_CEILING, (
        f"对外正式面同类小节集合/顺序偏离 {len(t2_official)} 页 > 上限 {T2_CEILING}＝又长了异形页。"
        f"（同刻三值：旧尺总偏离 {len(deviations)} = 对外欠账 {len(t2_official)} + "
        f"过程稿登记 {len(t2_registered)}；上限 {T2_CEILING} 是 2026-09-22 按**旧尺**录的首届核账值，"
        f"R0=A 只换口径、本枚一字未升。）修法：把多出的 H2 降级为 H3 或改回骨架节名"
        f"（结构零事实增删），确属新形态则改骨架声明源并走模板升级。对外欠账偏离件："
        f"{[str(x) for x in t2_official][:6]}"
    )

    # --- R2 骨架侧三腿（席 TX131）：模板声明本身受约束，页面形状只是它的投影 -------------
    findings = _g_t2_skeleton_findings(_G_T2_REAL_SKELETON)
    assert not findings, (
        "G-T2 骨架三腿（用户裁定 R2：①槽顺序不许变 ②新增槽一律可选 ③槽数只准增不许减）"
        "或零必填槽咬合判红——修法在模板面 docs/templates/**（骨架升级须用户裁定后重录基线），"
        "不在页面面，也不许改本文件字面量凑绿：\n" + "\n".join(findings[:12])
    )
    five_now = tuple(
        name
        for name, _opt in _G_T2_REAL_SKELETON[_G_T2_FIVE_SLOT_TEMPLATE]
        if name in set(_G_T2_FIVE_SLOTS)
    )
    assert five_now == _G_T2_FIVE_SLOTS, (
        f"R2① 点名的五槽在 {_G_T2_FIVE_SLOT_TEMPLATE} 骨架里变了序：实得 {list(five_now)}"
        f"，首届 {list(_G_T2_FIVE_SLOTS)}（顺序不许变；扩槽可以，重排这五枚不行）"
    )
    # 零必填槽那笔债：只准降、方向锁、登记表不许 padding（把新模板塞进表＝换绿，当场红）
    zero_now = _g_t2_zero_required(_G_T2_REAL_SKELETON)
    zero_counts = [n for _d, n in AUDIT_HISTORY_T2_ZERO_REQUIRED]
    assert zero_counts == sorted(zero_counts, reverse=True), (
        f"零必填槽在册数出现回升（方向锁）：{zero_counts}"
    )
    assert _G_T2_ZERO_REQUIRED_CEILING <= zero_counts[0], (
        f"上限 {_G_T2_ZERO_REQUIRED_CEILING} 超过首届核账值 {zero_counts[0]}＝调大换绿"
    )
    assert len(_G_T2_ZERO_REQUIRED_BASELINE) <= _G_T2_ZERO_REQUIRED_CEILING, (
        f"零必填槽登记表 {_G_T2_ZERO_REQUIRED_BASELINE} 比首届核账值（{zero_counts[0]}）还多"
        "＝往登记表里塞新名字换绿；这张表只准摘牌，不准扩充"
    )
    assert len(zero_now) <= _G_T2_ZERO_REQUIRED_CEILING, (
        f"零必填槽模板现算 {sorted(zero_now)} 共 {len(zero_now)} 枚 > 首届登记 "
        f"{_G_T2_ZERO_REQUIRED_CEILING}＝又多了一枚透明骨架（它不咬任何页，形同没模板）"
    )


# --------------------- R2 三腿与咬合的注毒自证（席 TX131；内存注毒＝复制字典，零写源码树）
def _skeleton_with(
    tid: str, slots: tuple[tuple[str, bool], ...]
) -> dict[str, tuple[tuple[str, bool], ...]]:
    """把真骨架里某一枚模板换成注毒形（R3 的「内存造假数据、测完自动还原」同型：只复制字典、
    不落盘、不碰 `docs/templates/**` 一字节）。"""
    skel = dict(_G_T2_REAL_SKELETON)
    skel[tid] = slots
    return skel


def _codes(findings: list[str]) -> set[str]:
    return {f.split(" ", 1)[0] for f in findings}


def test_g_t2_leg_one_detects_slot_reorder() -> None:
    """注毒①：把五槽里的「交付」与紧随其后的可选槽对调 ⇒ 在册序失守 ⇒ 必红（真骨架不误伤）。"""
    cur = _G_T2_REAL_SKELETON["seat-report"]
    idx = [i for i, (name, _o) in enumerate(cur) if name in {"交付", "证据"}]
    assert len(idx) == 2, f"注毒点不在骨架里，本用例失去意义：{[n for n, _ in cur]}"
    poisoned = list(cur)
    poisoned[idx[0]], poisoned[idx[1]] = poisoned[idx[1]], poisoned[idx[0]]
    findings = _g_t2_skeleton_findings(_skeleton_with("seat-report", tuple(poisoned)))
    assert "SKELETON_ORDER" in _codes(findings), f"槽序被换未被抓到（该腿视为不存在）：{findings[:4]}"
    assert "SKELETON_ORDER" not in _codes(_g_t2_skeleton_findings(_G_T2_REAL_SKELETON)), "真骨架被误判失序"


def test_g_t2_leg_two_new_slot_must_be_optional() -> None:
    """注毒②：新增槽声明成**必填**必红；声明成**可选**必须放行（封死扩槽＝违 R2③ 的「只准增」）。"""
    base = _G_T2_REAL_SKELETON["ledger"]
    optional = _g_t2_skeleton_findings(_skeleton_with("ledger", base + (("新形态", True),)))
    assert "SKELETON_NEW_REQUIRED" not in _codes(optional), f"新增可选槽被误拦＝扩槽被封死：{optional[:4]}"
    required = _g_t2_skeleton_findings(_skeleton_with("ledger", base + (("新形态", False),)))
    assert "SKELETON_NEW_REQUIRED" in _codes(required), f"新增槽塞成必填未被抓到：{required[:4]}"


def test_g_t2_leg_three_detects_slot_shrink() -> None:
    """注毒③：删掉一枚在册槽（槽数少于首届基线）⇒ 必红；扩槽不红（方向只卡「减」）。"""
    base = _G_T2_REAL_SKELETON["guide"]
    shrunk = _g_t2_skeleton_findings(_skeleton_with("guide", base[:-1]))
    assert "SKELETON_SHRANK" in _codes(shrunk), f"减槽未被抓到（该腿视为不存在）：{shrunk[:4]}"
    grown = _g_t2_skeleton_findings(_skeleton_with("guide", base + (("附注", True),)))
    assert "SKELETON_SHRANK" not in _codes(grown), f"扩槽被误判减槽：{grown[:4]}"


def test_g_t2_bite_detects_planted_zero_required_template() -> None:
    """反向自证（R2 硬要求）：注一枚「一个必填槽都没有」的模板 ⇒ 必红；给在册四枚补上必填槽 ⇒ 摘牌。"""
    planted = _g_t2_skeleton_findings(_skeleton_with("ghost-zero", (("甲", True), ("乙", True))))
    assert any(
        f.startswith("SKELETON_NO_REQUIRED_SLOT") and " ghost-zero " in f for f in planted
    ), f"注进去的零必填槽模板没被咬住（判据对它失效）：{planted[:4]}"
    emptied = _g_t2_skeleton_findings(_skeleton_with("guide", ()))
    assert "SKELETON_NO_REQUIRED_SLOT" in _codes(emptied), f"空骨架逃过咬合：{emptied[:4]}"
    brief_fixed = _g_t2_skeleton_findings(
        _skeleton_with("brief", _G_T2_REAL_SKELETON["brief"][:-1] + (("落点", False),))
    )
    assert "SKELETON_NO_REQUIRED_SLOT" not in _codes(brief_fixed), (
        f"给 brief 补一枚必填槽仍被判红＝登记表成了永久豁免而不是债：{brief_fixed[:4]}"
    )


def test_g_t2_bite_reaches_every_registered_template(monkeypatch: pytest.MonkeyPatch) -> None:
    """自证·补：那四枚**确实**在这条腿的射程里——摘掉登记表⇒四枚同时红（登记＝记债，不是豁免判定）。"""
    registered = set(_G_T2_ZERO_REQUIRED_BASELINE)  # 摘表前先取原值，否则断言会拿空气比空气
    monkeypatch.setattr(sys.modules[__name__], "_G_T2_ZERO_REQUIRED_BASELINE", frozenset())
    findings = _g_t2_skeleton_findings(_G_T2_REAL_SKELETON)
    caught = {
        f.split()[2] for f in findings if f.startswith("SKELETON_NO_REQUIRED_SLOT")
    }
    assert caught == registered, (
        f"摘表后被咬住的不是在册四枚（说明判据没数真必填槽）：实得 {caught}，应为 {registered}"
    )


def test_g_t2_legs_kill_the_production_assertion(monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端自证（治「只测判据函数、门本体空跑」）：把真骨架换成毒形后，**跑那条生产断言本身**必抛。

    注毒只发生在内存字典上（`monkeypatch` 自动还原），`docs/templates/**` 一字节未动。
    """
    poison = _skeleton_with(
        "seat-report", tuple(reversed(_G_T2_REAL_SKELETON["seat-report"]))
    )
    monkeypatch.setattr(sys.modules[__name__], "_G_T2_REAL_SKELETON", poison)
    with pytest.raises(AssertionError, match="SKELETON_ORDER"):
        test_generated_pages_have_full_skeleton()


def test_board_docs_do_not_handwrite_volatile_counts() -> None:
    """板块正文禁手写会漂移的计数（旧判据）+ **G-T3 禁裸写一次性事实**（2026-09-22 席 T-GATES 扩展）。

    判据真身 `scripts/doc_fact_discipline.py`（词表只住那一处，AST 锁在
    `tests/test_taxonomy_spec_gates.py`）：计数 / 阈值 / 枚举清单 / 运行数据路径四类，
    一律只准走 `{{fact:KEY}}` 参数引用或「以真身/生成物为准」的指针句。

    管辖面（**席 S201 按用户裁定 3.A 改判据**）：面 A＝板块人工区 ＋ `GOVERNED_LINE_PATHS`
    名录点名的现役件，**只由路径/登记派生**（`FACE_BY_CATEGORY` 一处真身）；模板头与
    「驱动与否」不再参与分桶——旧判据下「戴 `template:` 头 ⇒ 从逐页面B 翻成逐行面A」，
    等于让被检者自己挑尺子（2026-09-23 批量套头 ⇒ 本面 0→460 行的那场红就是它）。
    头想买宽 ⇒ `test_g_t3_no_page_may_buy_a_looser_face_with_its_own_hat` 当场红。

    起点基线（手写字面量、只准降，**本席一字未动**）：2026-09-22 现算 **226 行**
    （`--report` ⇒ `G-T3 面 A 管辖 226 行`）。旧窄词表下这里是 0，宽尺（阈值/枚举/路径 +
    计数尾界不再被汉字挡住）是新执法，按「立门当跑值」记账，**不缩面、不加通配豁免**；
    未迁移页的债在
    `tests/test_taxonomy_spec_gates.py::test_g_t3_unmoved_face_debt_never_grows` 记第二本账。
    """
    violations = _SPEC["t3_managed"]
    counts = [n for _d, n in AUDIT_HISTORY_T3_MANAGED]
    assert counts == sorted(counts, reverse=True), f"G-T3 面 A 核账记录出现回升（方向锁）：{counts}"
    assert T3_MANAGED_CEILING <= counts[0], (
        f"上限 {T3_MANAGED_CEILING} 超过首届核账值 {counts[0]}＝调大换绿"
    )
    assert len(violations) <= T3_MANAGED_CEILING, (
        f"板块正文裸写一次性事实 {len(violations)} 行 > 上限 {T3_MANAGED_CEILING}。"
        f"修法：事实改 `{{fact:KEY}}` 参数（值走 auto: 现算）或写成"
        f"「以生成物/机器册/真身为准」指针句；违规大户：{violations[:8]}"
    )
    # 旧窄词表仍然单独执法（双保险：扩展判据不许把旧判据吃掉）
    offenders: list[str] = []
    for path in _board_body_pages():
        text = path.read_text(encoding="utf-8")
        human = re.sub(
            r"<!-- BOARD-AUTO:BEGIN -->.*?<!-- BOARD-AUTO:END -->", "", text, flags=re.DOTALL
        )
        for line in human.splitlines():
            if "以生成物为准" in line or "以机器册" in line or "当时值" in line:
                continue
            if _VOLATILE_COUNT.search(line):
                offenders.append(f"{path.relative_to(ROOT)}: {line.strip()[:80]}")
    assert not offenders, f"板块文档正文手写了会漂移的计数：{offenders}"


def _board_body_pages() -> list[Path]:
    """板块正文页（排除机器台账 _meta 与规范本体）。"""
    return [
        x for x in sorted(BOARDS_DIR.rglob("*.md"))
        if "_meta" not in x.parts and x.name != "_conventions.md"
    ]


def test_volatile_count_gate_detects_planted_line(tmp_path: Path) -> None:
    """自证四：门能杀行为——同一行注毒必红，带权威指针放行。"""
    page = tmp_path / "boards" / "B01-x" / "feat"
    page.mkdir(parents=True)
    bad = page / "bad.md"
    bad.write_text("本板块共 47 个能力入口，另有 12 条别名。\n", encoding="utf-8")
    good = page / "good.md"
    good.write_text("计数以生成物 docs/boards/README.md 为准。\n", encoding="utf-8")
    assert _VOLATILE_COUNT.search(bad.read_text(encoding="utf-8")), "注毒未被识别"
    assert not _VOLATILE_COUNT.search(good.read_text(encoding="utf-8")), "带指针行被误拦"
    for ref in ("§9 字段级契约", "zhconv 1.4.3 字段", "v21r2 主题"):
        assert not _VOLATILE_COUNT.search(ref), f"章节号/版本号被误判：{ref}"


# ---------------------------------------------------------------- G-T3 扩面（席 S3 2026-09-22，只加严）
# 治 F-3「放行词整行橡皮章」与 F-15「注毒只跑正则、不跑记账腿」。判据真身一律在
# `scripts/doc_fact_discipline.py`（词表唯一住所，此处只喂样本行，不抄第二套尺子）。

_G3_BARE_CLASSES = ("裸计数", "裸阈值", "裸路径", "裸枚举清单")


def test_g_t3_pointer_phrase_does_not_stamp_exempt_bare_facts() -> None:
    """自证四·补（F-3）：指针短语与裸事实同行混写仍须红——指针只豁免它自己承担的片段。

    放行判据是**分段**的：摘除 `以…为准` 整段/`{{fact:…}}`/指针词之后，残余文本照判四类。
    纯指针句与粘连负样本必须保持放行（误杀=逼作者往别处藏事实，同样是债）。
    """
    mixed = [
        "本板块共 47 个能力入口，真身在 board_taxonomy.py。",
        "单文件上限 100MB，超时 30 秒，共 5 个键（现值）。",
        "{{fact:count}} 条入口，另外 47 个能力，超时 30 秒。",
        "另有 12 条别名，计数以生成物 README 为准。",
    ]
    for line in mixed:
        hits = dfd.fact_findings([line], vocab=set())
        assert hits and any(h.startswith(c) for c in _G3_BARE_CLASSES for h in hits), (
            f"指针橡皮章仍整行放行混写句：{line!r} → {hits}"
        )
    for ok in (
        "计数以生成物 docs/boards/README.md 为准。",
        "字段数以机器册 docs/auto-facts.md 为准（当时值保留于台账）。",
        "{{fact:count}} 条入口（渲染期现算）。",
        "以最近一次 dev.ps1 -Task test 实跑输出为准。",
        "§9 字段级契约与 v21r2 主题、zhconv 1.4.3 版本无关。",
    ):
        assert dfd.fact_findings([ok], vocab=set()) == [], f"纯指针/粘连负样本被误杀：{ok!r}"


def test_g_t3_machine_local_paths_never_exempted() -> None:
    """机器本地路径（盘符/UNC//c/Users/家目录~/%VAR% 占位）在正文一律红，指针句不豁免。

    这是 AGENTS 规则 3 打码面之外的一层：隐私 + 可移植双重问题，只准住配置真身。
    `https://` 等 URL scheme 不算机器本地路径（负对照防误伤面失控）。
    """
    bs = chr(92)
    lines = [
        "归档落在 data/media_archive/ 与 C:/Users/x/Runtime/ 下，路径以 runtime_paths 为准。",
        "日志在 C:" + bs + "Software" + bs + "x 下（现值以巡检为准）。",
        "工作目录 /c/Users/x 以环境为准。",
        "临时件放 %TEMP%/x，口径以脚本为准。",
        "缓存 ~/x 以脚本为准。",
        "共享在 " + bs + bs + "server" + bs + "share 下，以配置为准。",
    ]
    for line in lines:
        hits = dfd.fact_findings([line], vocab=set())
        assert hits and hits[0].startswith("裸机器本地路径"), (
            f"机器本地路径被指针句放行：{line!r} → {hits}"
        )
    url_only = "上游端点 https://example.com/a/b（可用性以实测为准）。"
    assert not any(
        h.startswith("裸机器本地路径") for h in dfd.fact_findings([url_only], vocab=set())
    ), "URL scheme 被误判为机器本地盘符路径"


def test_g_t3_accounting_leg_detects_synthetic_poison_page(tmp_path: Path) -> None:
    """自证五（F-15 修腿）：记账腿走完整 `sc.compute(合成根)`——毒页不进真树也被抓到。

    旧「自证四」只跑 `_VOLATILE_COUNT` 正则，记账链（walk→human_lines→fact_findings→
    面 A/B 归类）整体改坏它照样绿。本用例把 bad/good 两页写进 tmp 合成树调**同一支**
    记账函数：bad 行必须出现在 `t3_managed`（面 A 归类腿活着），good 纯指针页不得进账
    （分段放行没被改疯）。`sc.compute(root)` 对合成根的支持是 census 自带契约。
    """
    boards = tmp_path / "docs" / "boards" / "B01-x"
    boards.mkdir(parents=True)
    (boards / "bad.md").write_text(
        "本板块共 47 个能力入口，真身在 board_taxonomy.py。\n", encoding="utf-8"
    )
    (boards / "good.md").write_text(
        "计数以生成物 docs/boards/README.md 为准。\n", encoding="utf-8"
    )
    res = sc.compute(tmp_path)
    managed = [str(v) for v in res["t3_managed"]]
    assert any("bad.md" in v and "裸计数：本板块共 47 个能力入口" in v for v in managed), (
        f"记账腿对合成毒页失明（该腿视为不存在）：{managed[:6]}"
    )
    assert not any("good.md" in v for v in managed), f"纯指针页被记账腿误记：{managed[:6]}"


# ===========================================================================
# 席 S201（2026-09-24，用户裁定 **3.A**）：G-T3 分桶只由「路径派生类别 ＋ 登记名录」决定，
# **模板头不参与分类**——「一篇文档算哪一类，不许由它自己戴的模板头决定」。
#
# 病根与实测（详见 .superpowers/sdd/2026-09-24-central-dispatch/SEAT-S201.md）：
# 旧分流把 `driven_non_generated`（＝本页戴没戴在册 `template:` 头）当输入，戴头⇒逐行面A、
# 摘头⇒逐页面B。2026-09-23 一次批量套头把 23 枚审计/过程件顶进面A（该面 0 → 460 行，
# 上限 226 ⇒ 常驻门实跑红），反方向摘头逃账同样一拨即成。裁定＝改桶的**派生方式**，
# 不逐页回头改头。下面四把锁各自注毒自证有牙（比较器只有一支，毒尺喂同一支）。
# ===========================================================================


def _old_hat_coupled_face(p: dts.PageInfo, *, driven_non_generated: bool) -> str:
    """裁定 3.A **之前**的分流尺子，逐行照旧实现搬进本用例（`git show
    HEAD:scripts/spec_gates_census.py` 的 `face_of_history_page`）——它只活在测试里，
    用来证明「头-面耦合体检」不是空跑的锁。删掉本函数＝把那把尺子的杀伤力一起删掉。
    """
    bucket = sc.ledger_bucket_of(p)
    if bucket is None:
        if p.rel.startswith("docs/boards/") or driven_non_generated:
            return "line"
        return "page"
    if bucket in sc.PROCESS_LOG_CATEGORIES:
        return "skip"
    return "page"


def test_g_t3_face_is_header_invariant_and_the_coupling_lock_has_teeth() -> None:
    """锁①（不变量）：同一页在「驱动 / 未驱动」两种假设下读数必须一致。

    正尺（现 `face_of_history_page`）跑真实树 ⇒ 必须零红；
    毒尺（上面那把裁定前的旧尺）喂**同一个比较器** ⇒ 必须逐页点名——
    否则「零红」只是比较器压根不比东西的假绿。
    """
    pages = _SPEC["pages"]
    assert isinstance(pages, list)
    clean = sc.header_coupling_findings(pages, sc.face_of_history_page)
    assert not clean, f"模板头仍在拨动记账面（裁定 3.A 已被破）：{clean[:3]}"
    assert not _SPEC["t3_header_coupling"], "compute() 侧同一支体检读数不一致（两支尺）"

    dirty = sc.header_coupling_findings(pages, _old_hat_coupled_face)
    assert dirty, "旧尺跑体检也零红＝比较器失能（这把锁空跑，任何『头拨面』都抓不住）"
    hit_rels = {e.split(" ", 1)[1].split(":", 1)[0] for e in dirty}
    assert "docs/design/audit-20260919-unify-wave.md" in hit_rels, (
        f"体检没点到 09-23 套头批次的代表页＝杀伤力不成立：{sorted(hit_rels)[:5]}"
    )


def test_g_t3_bucket_table_covers_every_reachable_category(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """锁②（总集性）：路径判据能到达的每一枚类别都必须在桶表里有显式一行——**不许「没登记＝免检」**。

    注毒＝把 `design-spec` 整类从桶表删掉：
      ① 体检必须点名缺行；
      ② 分流函数必须当场抛（宁可崩，绝不静默给一个「无面可记＝两面都不记」的宽待遇）。
    """
    pages = _SPEC["pages"]
    assert isinstance(pages, list)
    assert not sc.bucket_table_gaps(
        pages, extra_categories=sc.categories_outside_content_universe()
    ), "桶表体检在干净树上就红——先修表再谈别的"

    starved = {k: v for k, v in sc.FACE_BY_CATEGORY.items() if k != "design-spec"}
    monkeypatch.setattr(sc, "FACE_BY_CATEGORY", starved)
    gaps = sc.bucket_table_gaps(
        pages, extra_categories=sc.categories_outside_content_universe()
    )
    assert any("design-spec" in g and "BUCKET_ROW_MISSING" in g for g in gaps), (
        f"整类从桶表消失却没被点名（缺行被当成免检）：{gaps[:3]}"
    )
    victim = dts.PageInfo(
        rel="docs/design/x.md", path=tmp_path, text="", category="design-spec"
    )
    with pytest.raises(LookupError, match="缺行不是免检"):
        sc.face_of_page_by_path(victim)


def test_g_t3_no_page_may_buy_a_looser_face_with_its_own_hat(tmp_path: Path) -> None:
    """锁③（自我豁免）：头能把页面买宽 ⇒ 当场红。注毒＝给现役叙述文档套一枚「过程件」身份。

    受害页选名录在册的真·现役件 `docs/design/control-plane-api.md`（路径/登记判 `line`），
    头改戴 `seat-report`（那一类在桶表里是 `skip`＝两面都不记）——正是「自己给自己发免检票」。
    同一支 `compute()` 走合成根，保证记账腿看得见（F-15：注毒只跑正则、记账腿失明）。
    另附反向对照：戴**对**自己那一类头的页（design-spec 头 + design-spec 路径）不许被误伤。
    """
    rel = "docs/design/control-plane-api.md"
    assert sc.face_of_page_by_path(
        dts.PageInfo(rel=rel, path=tmp_path, text="", category=dts.classify(rel))
    ) == "line", "名录没把这枚现役件钉在面A＝前置条件已变，本用例失去意义"
    page_dir = tmp_path / "docs" / "design"
    page_dir.mkdir(parents=True)
    (page_dir / "control-plane-api.md").write_text(
        "---\ntemplate: seat-report\nparams:\n  owner_board: B09\n---\n\n"
        "## 端点\n\n本接口共 11 个字段，超时阈值 30 秒。\n",
        encoding="utf-8",
    )
    res = sc.compute(tmp_path)
    exemptions = [str(v) for v in res["t3_self_exemption"]]
    assert exemptions, "现役页戴过程件头却零红＝自我豁免锁失能"
    assert any(rel in v and "SELF_EXEMPTION_VIA_TEMPLATE" in v for v in exemptions), exemptions[:3]
    # 头的分流申请不许改变记账：这一页的裸事实仍必须逐行进面 A（不能被"宽"到 skip 蒸发）
    assert any(rel in v for v in (str(x) for x in res["t3_managed"])), (
        f"行级账被豁免腿放走（债就地蒸发）：{[str(x) for x in res['t3_managed']][:3]}"
    )

    # 反向对照：戴对自己那一类的头＝纯版式声明，不得被本锁误伤（否则现役页天天假红）
    (page_dir / "honest-spec.md").write_text(
        "---\ntemplate: design-spec\nparams:\n  spec_id: auto:filename_stem\n"
        "  owner_board: auto:category_owner_board\n---\n\n"
        "## 目标\n\n普通正文，不带计数。\n",
        encoding="utf-8",
    )
    again = [str(v) for v in sc.compute(tmp_path)["t3_self_exemption"]]
    assert not any("honest-spec.md" in v for v in again), (
        f"戴对头的现役规格页被自我豁免锁误伤＝方向判据写坏：{again[:3]}"
    )


def test_g_t3_roster_only_tightens_and_boards_bucket_equals_old_path_rule() -> None:
    """锁④（方向与等价）：名录只准把页**变严**；板块人工区的「类别桶」与旧「路径前缀」判据等价。

    · 名录里任何一枚页，其**桶表**面若是 `skip`＝「登记」变成洗白通道（过程日志桶），禁；
      （名录判 line 是加严，允许；但一枚落在 skip 桶的路径若哪天被从名录摘掉，就直接掉出
      两面——所以摘名录这一步必须同批现算代价，本锁先把最坏形状挡住。）
    · 桶表与 `docs/boards/` 前缀判据分叉（改 `classify()` 漏跟桶表，或反之）会让板块人工区
      整片从面A 掉到面B——这里逐页现算比，不手写任何页数。
    """
    for rel in sorted(sc.GOVERNED_LINE_PATHS):
        face = sc.face_by_category_strict(dts.classify(rel))
        assert face != "skip", f"名录枚 {rel} 落在 skip 桶＝登记变成洗白通道"
    drift = [str(v) for v in _SPEC["t3_boards_prefix_drift"]]
    assert not drift, f"板块前缀判据与桶表分叉（一侧改了另一侧没跟）：{drift[:5]}"
    pages = _SPEC["pages"]
    assert isinstance(pages, list)
    boards = [p for p in pages if str(p.rel).startswith("docs/boards/")]
    assert boards, "板块管辖面为空＝本锁在空跑"
    assert all(sc.face_of_history_page(p) == "line" for p in boards), (
        "板块人工区不再恒记面A＝逐行治理面塌陷（门空跑）"
    )


# ===========================================================================
# 席 S230（2026-09-25，用户裁定 **R0 = A**）：**欠账分母的定义域**——gitignored 的施工过程稿
# 不进「受管文档」欠账分母，但总账栏不许消失；分桶/是否过程稿**只由路径派生**，不许由文件
# 自己戴的模板头或声明决定（与上方 S201 的 3.A 那把「头不得给页降档」的锁同款形状、复用其形）。
#
# 判据真身住 `scripts/spec_gates_census.py`：分母表 `R0_DEBT_BUCKET_BY_CATEGORY` +
# `r0_debt_bucket_strict`（缺行即抛）+ `r0_self_exemption_findings`（头买宽即红）+
# `r0_denominator_gaps`（总集性体检）。下面两发注毒各自证明这把锁**有牙**（毒尺喂同一支比较器）。
# ===========================================================================


def test_r0_process_status_is_path_derived_and_hat_cannot_downgrade(tmp_path: Path) -> None:
    """锁①（自我豁免，注毒①）：给**现役受管文档**伪装「过程稿」身份 ⇒ 必红，且绝不因此躲掉欠账。

    受害页选名录在册的真·现役件 `docs/design/control-plane-api.md`（路径判 `design-spec` ⇒
    欠账分母里是 `debt`），头改戴 `seat-report`（那一类在分母表里是 `register`＝过程稿、不进欠账）
    ——正是「自己给自己发免检票」。判据：① `r0_self_exemption_findings` 必须点名；② 分账腿不许
    被这顶帽子骗到（该页仍留在 t1 对外欠账栏，绝不进过程稿登记栏）。反向对照：戴**对**自己那一类
    头的页不许被误伤（否则现役页天天假红）。全程 tmp 合成根，`docs/**` 一字节未动。
    """
    rel = "docs/design/control-plane-api.md"
    page_dir = tmp_path / "docs" / "design"
    page_dir.mkdir(parents=True)
    (page_dir / "control-plane-api.md").write_text(
        "---\ntemplate: seat-report\nparams:\n  seat_id: FAKE\n  wave: w\n"
        "  status: DONE\n  role: doc\n  report_class: auto:seat_class\n"
        "  ledger_events: auto:page_stat:ledger\n---\n\n## 端点\n\n普通正文。\n",
        encoding="utf-8",
    )
    # 前置：这一页按路径派生就该进欠账分母（帽子不参与这一步）。
    assert sc.is_process_artifact_page(
        dts.PageInfo(rel=rel, path=tmp_path, text="", category=dts.classify(rel))
    ) is False, "前置塌了：这枚现役件按路径本就被算成过程稿＝污染面已扩，本用例失去意义"

    res = sc.compute(tmp_path)
    exemptions = [str(v) for v in res["r0_self_exemption"]]
    assert any(rel in v and "R0_SELF_EXEMPTION_VIA_TEMPLATE" in v for v in exemptions), (
        f"现役页戴过程稿头却零红＝R0 自我豁免锁失能：{exemptions[:3]}"
    )
    # 帽子的分流申请不许改变分账：这一页仍必须在**对外欠账**栏（绝不因帽进过程稿登记栏）。
    t1_debt = {str(x).split("#", 1)[0].split(":", 1)[0].strip() for x in res["t1_debt_official"]}
    t1_reg = {str(x).split("#", 1)[0].split(":", 1)[0].strip() for x in res["t1_registered_process"]}
    assert rel in t1_debt, (
        f"伪装过程稿却从对外欠账栏消失＝借帽降账（隐身）：debt={sorted(t1_debt)[:3]}"
    )
    assert rel not in t1_reg, f"现役路径页被算进过程稿登记栏（{rel}）＝按页面自报帽子分账，可被伪装"

    # 反向对照：戴对自己那一类头的现役规格页，不得被本锁误伤。
    (page_dir / "honest-spec.md").write_text(
        "---\ntemplate: design-spec\nparams:\n  spec_id: auto:filename_stem\n"
        "  owner_board: auto:category_owner_board\n---\n\n## 目标\n\n普通正文。\n",
        encoding="utf-8",
    )
    again = [str(v) for v in sc.compute(tmp_path)["r0_self_exemption"]]
    assert not any("honest-spec.md" in v for v in again), (
        f"戴对头的现役规格页被 R0 自我豁免锁误伤＝方向判据写坏：{again[:3]}"
    )


def test_r0_denominator_bucket_table_covers_every_reachable_category(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """锁②（总集性，注毒②）：分母定义域每枚在册类别必须显式一行——**缺行不是免检**。

    正尺跑真实树 ⇒ 体检必须零红；注毒＝把 `design-spec` 整类从分母表删掉 ⇒
    ① `r0_denominator_gaps` 必须点名 `R0_BUCKET_ROW_MISSING`；
    ② 分流函数 `r0_debt_bucket_strict` 必须当场抛（宁可崩，绝不静默给「既不进欠账也不进登记」
       的宽待遇＝隐身）。两发缺一，这把锁就是空跑的装饰。
    """
    pages = _SPEC["pages"]
    assert isinstance(pages, list)
    assert not sc.r0_denominator_gaps(
        pages, extra_categories=sc.categories_outside_content_universe()
    ), "欠账分母定义域体检在干净树上就红——先修表再谈别的"

    starved = {k: v for k, v in sc.R0_DEBT_BUCKET_BY_CATEGORY.items() if k != "design-spec"}
    monkeypatch.setattr(sc, "R0_DEBT_BUCKET_BY_CATEGORY", starved)
    gaps = sc.r0_denominator_gaps(
        pages, extra_categories=sc.categories_outside_content_universe()
    )
    assert any("design-spec" in g and "R0_BUCKET_ROW_MISSING" in g for g in gaps), (
        f"整类从分母表消失却没被点名（缺行被当成免检）：{gaps[:3]}"
    )
    with pytest.raises(LookupError, match="缺行不是免检"):
        sc.r0_debt_bucket_strict("design-spec")


def test_r0_registered_columns_stay_wired_to_the_scan() -> None:
    """锁③（席 S230R，R0=A 的**反缩水腿**）：过程稿那一栏必须一直连着扫描面，且两栏不许串门。

    为什么需要第三把：**「两栏之和 == 旧尺总账」这支恒等式对『把过程稿从扫描面剔除』是盲的**
    ——整桶被剔除时总账跟着一起掉下来，等式照样成立（本席用注毒枚乙实测：`compute()` 里把过程稿
    `continue` 掉 ⇒ 三栏一起变 0、恒等式全绿、门全绿）。R0=A 的原话是「**总账栏不许消失**」，
    那就必须有一枚只数过程稿的活性面，否则换口径会悄悄变成缩扫描面。

    三条腿（判据不落本门、只消费取数口 + 唯一投影口 `r0_process_rels`）：
    ① 人口腿：全扫描过程稿 ≥ `MIN_R0_PROCESS_PAGES`、G-T2 比对面中的过程稿 ≥ `MIN_T2_PROCESS_PAGES`；
    ② 归栏腿：任何一面「过程稿登记」栏的主体，必须是 `r0_process_rels(扫描页)` 的成员（不许凭
       帽子或第二套判据进栏）；
    ③ 串门腿：任何一面「对外欠账」栏的主体，绝不许是该集合的成员（对外页被记进登记栏＝降账）。
    """
    pages = _SPEC["pages"]
    assert isinstance(pages, list)
    process_rels = sc.r0_process_rels(pages)

    assert len(process_rels) >= MIN_R0_PROCESS_PAGES, (
        f"全扫描过程稿只剩 {len(process_rels)} 页（地板 {MIN_R0_PROCESS_PAGES}）＝过程稿整桶从"
        "**扫描面**消失（不是从欠账消失）。R0=A 只把它们挪出欠账分母、一枚都不许少扫——"
        "恒等式对这种改法免疫（总账会跟着一起掉），所以由本枚把风。"
    )
    assert _SPEC["t2_pages_process"] >= MIN_T2_PROCESS_PAGES, (
        f"G-T2 比对面里的过程稿只有 {_SPEC['t2_pages_process']} 页"
        f"（地板 {MIN_T2_PROCESS_PAGES}；比对页总面 {_SPEC['t2_pages']}）＝该面的管辖范围被缩，"
        "不是大家都合规。复跑看 --report 的「R0=A 反缩水腿」行。"
    )

    faces = {
        "t1": ("t1_debt_official", "t1_registered_process"),
        "t2": ("t2_debt_official", "t2_registered_process"),
        "t4": ("t4_debt_official", "t4_registered_process"),
        "tcheck": ("tcheck_debt_official", "tcheck_registered_process"),
    }
    for face, (debt_key, reg_key) in faces.items():
        debt, registered = _SPEC[debt_key], _SPEC[reg_key]
        assert isinstance(debt, list) and isinstance(registered, list), f"{face} R0 栏改版"
        reg_strays = sorted(
            {sc.entry_subject(str(e)) for e in registered} - process_rels - {""}
        )
        # 模板级条目（`DEAD_PARAM <tid>` 一类）的主体不是任何页 rel ⇒ 天生落在过程稿集外，
        # 那类条目**不许**进登记栏（保守方向：模板体自身的债永远记欠账），所以这里不给豁免。
        assert not reg_strays, (
            f"{face} 的过程稿登记栏出现扫描面不认的主体 {reg_strays[:5]}＝分账被第二套判据"
            "（或被文件自己戴的头）拨动，违 R0=A『只由路径派生』"
        )
        debt_strays = sorted(
            {sc.entry_subject(str(e)) for e in debt if sc.entry_subject(str(e)) in process_rels}
        )
        assert not debt_strays, (
            f"{face} 的对外欠账栏混进了过程稿主体 {debt_strays[:5]}＝两栏串门（同一条目记两处，"
            "互斥自证被绕开）"
        )

