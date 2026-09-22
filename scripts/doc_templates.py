"""内容类别注册表（唯一真身，席 T-GATES 2026-09-22 自 `doc_template_sync.py` 搬入）。

设计契约：`.superpowers/sdd/2026-09-22-taxonomy/GATE-PLAN.md` §二（形状）与席 T-GATES
任务书（类别集合必须与 `CENSUS.md` §一 一字不差）。本文件**只声明数据**，不 import 插件包、
不 import 其它 scripts（与 `domains/core/board_taxonomy.py` 同哲学），因此：

- 全仓只准这一份 `CONTENT_CATEGORIES` 字面量（由
  `tests/test_taxonomy_spec_gates.py::test_registry_has_a_single_home` 以 AST 执法，
  在测试件里再枚举一套=红）。
- 类别名一律取 CENSUS §一 的字面名（含 `board-l1/l2/l3` 拆成的三枚）。CENSUS 增删类别
  而未改本表 ⇒ G-T5 的「集合相等」腿当场红。
- **豁免与生成物也必须是声明数据**：`generated_by` 点名写盘口（`脚本:符号`），
  门据此现算生成页集合，绝不在测试里写死文件清单当豁免。

字段语义
--------
cid
    类别名（CENSUS §一 一字不差）。
template
    该类内容件的模板 id。`surface="md"` ⇒ 真身是 `docs/templates/<template>.md`；
    `surface="code"` ⇒ 模板仍是那份 md（描述该类代码内内容件的 schema 契约），
    额外由 `code_home` 指向现存声明源。None＝该类由生成器所有（必须配 `generated_by`）。
surface
    `"md"`＝文档面（由 `doc_template_sync.walk_content_pages()` 管辖）；
    `"code"`＝代码内内容件面（本轮只挂账，取数口在 CENSUS/INCODE 两席的清点里）。
owner_board
    归属板块（文档域 B10）。
generated_by
    非空＝该类整族由某个写盘口生成，页侧不带 front-matter（GATE-PLAN §五 C5）。
    形如 `scripts/board_doc_sync.py:L1_BODY`，门会 AST 核验该脚本确有该符号。
code_home
    仅 `surface="code"` 用：该类内容件的现存声明源路径（必须存在）。
reason
    为什么是生成物/为什么挂账（一句话，不许空）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryDef:
    cid: str
    template: str | None
    surface: str
    owner_board: str
    generated_by: str = ""
    code_home: str = ""
    reason: str = ""


#: 唯一类别注册表。搬动本表 = 改 G-T5 的执法面，必须同步 CENSUS §一 口径。
CONTENT_CATEGORIES: tuple[CategoryDef, ...] = (
    CategoryDef(
        cid="root-rules", template="workspace-rule", surface="md", owner_board="B10",
        reason="工作区规则本体（AGENTS.md）；加头是否越「禁改 AGENTS.md」边界属 SPEC-TARGETS §3-D1 待裁。",
    ),
    CategoryDef(
        cid="root-handoff", template="handoff", surface="md", owner_board="B10",
        reason="根交接件；节名含波次专名 ⇒ 专名进 params（SPEC-TARGETS §1-2）。",
    ),
    CategoryDef(
        cid="root-report", template="incident-report", surface="md", owner_board="B10",
        reason="根报告/台账件（含 COMMANDS.md 半生成件，SPEC-TARGETS §3-D2=按非生成物须带头）。",
    ),
    CategoryDef(
        cid="handbook", template="handbook", surface="md", owner_board="B10",
        reason="单一活文档 HANDBOOK.md。",
    ),
    CategoryDef(
        cid="board-l1", template=None, surface="md", owner_board="B10",
        generated_by="scripts/board_doc_sync.py:L1_BODY",
        reason="一级板块页：结构归生成器，人写区形状由 G-T2 按骨架 canon 执法。",
    ),
    CategoryDef(
        cid="board-l2", template=None, surface="md", owner_board="B10",
        generated_by="scripts/board_doc_sync.py:L2_BODY",
        reason="二级功能 README：同上。",
    ),
    CategoryDef(
        cid="board-l3", template=None, surface="md", owner_board="B10",
        generated_by="scripts/board_doc_sync.py:L3_BODY",
        reason="三级入口页：同上。",
    ),
    CategoryDef(
        cid="board-index", template=None, surface="md", owner_board="B10",
        generated_by="scripts/board_doc_sync.py:INDEX_BODY",
        reason="板块树索引页（docs/boards/README.md）：旧版与单板块页同判 board-l1＝G-T2 唯一偏离件"
               "（席 S35 取证，硬改正文凑 L1 骨架＝假绿）；席 S83 另立本类，骨架真身与 board-l1/l2/l3 "
               "同型＝生成器常量（不建第二枚模板文件，模板与分类同源）。",
    ),
    CategoryDef(
        cid="board-meta", template="convention", surface="md", owner_board="B10",
        reason="_meta 台账与 _conventions 规范本体（SPEC-TARGETS §3-E2=各立一类）。",
    ),
    CategoryDef(
        cid="design-spec", template="design-spec", surface="md", owner_board="B10",
        reason="docs/design/** 规格件；SPEC-TARGETS §1-9 建议按前缀分四子模板，本表先挂一枚。"
               "席 S126（2026-09-22）：本类**按路径派生**，故桶里混住了误放此处的过程文档；"
               "归类判据真身＝`spec_gates_census.content_class_of_mislocated_process_page`"
               "（只读正文 H2，命中者治理上按既有桶 root-report 记账、"
               "文件不搬）；路径桶计数腿要跟着改需 `doc_template_sync.classify()` 生效，"
               "该文件非本席面，已成交回工单（见 SEAT-S126 §工单）。",
    ),
    CategoryDef(
        cid="catalog", template="ledger", surface="md", owner_board="B10",
        reason="目录/清单件；其中 auto-facts/command-catalog 两枚是生成物，由页侧取数口豁免（不靠类别）。",
    ),
    CategoryDef(
        cid="acceptance", template="runbook", surface="md", owner_board="B10",
        reason="验收手册。",
    ),
    CategoryDef(
        cid="route-matrix", template="ledger", surface="md", owner_board="B10",
        reason="路由矩阵（另有他门执法 ⇒ 只加头不改体）。",
    ),
    CategoryDef(
        cid="doc-misc", template="guide", surface="md", owner_board="B10",
        reason="docs/ 其余顶层指南/叙事件。",
    ),
    CategoryDef(
        cid="persona-knowledge", template="persona", surface="md", owner_board="B10",
        reason="人格件**残差类**（不匹配下方三簇文件名判据的人格 md 留在本类）；"
               "是否永久豁免见 SPEC-TARGETS §3-E3 待裁，本席不擅自豁免（挂账即债）。",
    ),
    # —— 席 S62（2026-09-22，主代理裁定 R-16）：persona 四页按**语料真形**分三簇，骨架由
    # `check_sections` 现算 H2 集合派生（17/34 节并集、零标题页、两枚必选页），非凭空设计。
    # 席 S83（2026-09-22）收口 S73 交回的 `declared_no_page` 半边：三簇＋`sdd-brief` 与注册表/
    # CENSUS 同一原子批落地，接线点＝`doc_template_sync.classify()` 的文件名判据表
    # `_PERSONA_CLUSTERS`（三簇）与 `_SDD_BRIEF_NAME_RE`（任务书簇）。**R-17 相容性**：
    # 人格正文禁注机器段 ⇒ 五枚人格类（含残差）只做**归类**、永不挂 front-matter，在册模板
    # 是骨架契约而非驱动口，其债继续在 G-T1 按「未迁移页」计（不是豁免、不是抬上限）。
    CategoryDef(
        cid="persona-provenance", template="persona-provenance", surface="md", owner_board="B10",
        reason="多来源清洗件合并的人格档簇（表达规范 17 节 / 核心知识 34 节，节名并集全可选）；"
               "S62 落地骨架、S83 接线：文件名含「核心知识」者入本类（表达规范留残差类的理由见 SEAT-S83 报告）。",
    ),
    CategoryDef(
        cid="persona-numbered", template="persona-numbered", surface="md", owner_board="B10",
        reason="零 markdown 标题的编号型人格档簇（identity.md，H2 数 0）；旧 persona 骨架对它必造 3 枚缺节。"
               "S83 接线：文件名 `identity.md` 入本类。",
    ),
    CategoryDef(
        cid="persona-inject-data", template="persona-inject-data", surface="md", owner_board="B10",
        reason="运行期注入用词条档簇（worldview_glossary.md，恰两枚必选节）；节名即注入分类，正文一字动不得。"
               "S83 接线：文件名 `worldview_glossary.md` 入本类。",
    ),
    CategoryDef(
        cid="seat-report", template="seat-report", surface="md", owner_board="B10",
        reason="席位工作日志（模板已落地，未迁移页计入 G-T1 债）。",
    ),
    CategoryDef(
        cid="sdd-ledger", template="sdd-ledger", surface="md", owner_board="B10",
        reason=".superpowers 其余台账件（master-plan 属禁写面，SPEC-TARGETS §3-B2 待裁）。",
    ),
    CategoryDef(
        cid="sdd-brief", template="brief", surface="md", owner_board="B10",
        # 席 S21R 落注册表行＋模板（§S21R-①）；席 S83（2026-09-22）补齐第三边：
        # `CENSUS.md §一` 由 `content_census.py --write` 现算投影（本席未手改该册，也未改其脚本），
        # 页侧接线点＝`doc_template_sync.classify()` 的 `_SDD_BRIEF_NAME_RE`（文件名族判据；
        # 旧 reason 的「无 H2」经实测不成立——`BRIEFS.md` 自身有 40+ 枚 H2，故改为名字族）。
        # 三处（注册表/CENSUS/classify）同一原子批 ⇒ G-T5「集合相等」与「声明无页」两条同时绿。
        reason=".superpowers 任务书/PLAN/README 名字族子簇（`BRIEF(S).md`/`PLAN.md`/`README.md`/`*-brief*.md`），"
               "从 sdd-ledger 另立；S83 接线。",
    ),
    CategoryDef(
        cid="html-card", template="card-html", surface="code", owner_board="B08",
        code_home="plugins/bot_unified_runtime/domains/render/card_render/templates",
        reason="非 templates/ 目录的 html（CENSUS 实扫 0 件，类别在册防将来自由发挥）。",
    ),
    CategoryDef(
        cid="jinja-template", template="card-jinja", surface="code", owner_board="B08",
        code_home="plugins/bot_unified_runtime/domains/render/card_render/templates",
        reason="Jinja 卡模板：schema 写在模板头部注释块（SPEC-TARGETS §2-A）。",
    ),
    CategoryDef(
        cid="incode-copy-pool", template="copy-pool", surface="code", owner_board="B03",
        # code_home 纠偏（席 S4，2026-09-22）：旧值 `runtime/user_copy.py` 从未存在过
        # （G-T5 现算当场点名「code_home 不存在」）。真身＝chat_reply 域的话术池，
        # 91 行、无垫片标记；`capabilities/user_copy.py`（18 行、带 _CANONICAL）是再导出垫片。
        code_home="plugins/bot_unified_runtime/domains/chat_reply/capabilities/user_copy.py",
        reason="用户可见文案池（SPEC-TARGETS §2-B 三档）。",
    ),
    CategoryDef(
        cid="fstring-card", template="card-fstring", surface="code", owner_board="B08",
        code_home="tests/test_mica_builders_contract.py",
        reason="f-string 直拼卡；在册账=登记制 _BUILDERS（SPEC-TARGETS §3-B 推荐 A）。",
    ),
    CategoryDef(
        cid="help-topic", template="help-entry", surface="code", owner_board="B10",
        code_home="plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py",
        reason="帮助主题：schema=ENTRIES 元组序 + 一张 META schema（§2-C）。",
    ),
    CategoryDef(
        cid="config-field", template="config-field", surface="code", owner_board="B10",
        code_home="plugins/bot_unified_runtime/config.py",
        reason="配置字段：说明真身在 catalog（§3-A8 待裁），本席只挂账不擅改 config.py。",
    ),
)

CATEGORIES_BY_ID: dict[str, CategoryDef] = {c.cid: c for c in CONTENT_CATEGORIES}

#: `docs/templates/**` 是模板源本身，不是内容件（G-T1/T2/T3 的管辖面把它排除，
#: 由 `doc_template_sync.load_schemas()` 单独管辖其 schema 合法性）。
TEMPLATE_SOURCE_PREFIX = "docs/templates/"

#: 排除在内容管辖面之外的目录（构建/运行/缓存面；不是「豁免」，是「不在扫描面里」）。
OUT_OF_SURFACE_DIRS: tuple[str, ...] = (
    ".git",
    "__pycache__",
    "node_modules",
    "ChatBot_Runtime",
    "ChatBot_Archive",
)
