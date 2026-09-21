# 十板块文档体系波 · 交接（2026-09-21，主会话 + 11 席并发；未 commit）

> 用户裁定原文：「把这些所有的 Markdown 汇总文档整理成实现聊天机器人 bot 的 **10 个大型板块**，
> 按**一级功能、二级功能、三级功能**分别归类归档，整理一切不合要求的内容」，
> 六条具体要求＝文件结构 / 统一规范 / 开发约束 / 自动化变更 / 问题处理（P0-P2 全处理）/ 代码质量。
> 本波是这条裁定的落地。**接手本仓文档与结构工作，从本页开始，不要从 AGENTS 顶部横幅考古。**

## 一、现在有什么（都是本波新建，非既有）

| 件 | 作用 |
|---|---|
| `docs/boards/README.md` | 十板块总览 + 二级/三级索引 + 派生事实（**整页机器所有，勿手改**） |
| `docs/boards/_conventions.md` | **统一规范本体**：三层结构定义、一功能一目录、命名表（模块/函数/参数/常量/配置键/文档名）、docstring 骨架、开发约束四条硬门、自动化变更三层契约、六统一尺子落点、P0/P1/P2 分级、代码质量红线 |
| `docs/boards/BNN-<slug>/<二级>/<三级>.md` | 板块正文：一级板块页、二级功能页、三级入口页，一功能一目录 |
| `plugins/bot_unified_runtime/domains/core/board_taxonomy.py` | **板块树唯一声明源**（与 `capability_registry.py` 同哲学：只声明数据、不 import 包内任何模块） |
| `scripts/board_doc_sync.py` | 板块投影器：`--write` 生成、`--check` 体检、`--dump` 排障；AST 静态解析，不 import 插件包 |
| `tests/test_board_taxonomy_gate.py` | 常驻门：结构自洽 + 活性覆盖 + 实现路径可解析 + 生成物同步 + 正文不许手写计数 + 三发变异注毒自证 |
| `docs/boards/_meta/doc-classification-20260921.md` | 全量 Markdown 分类账（现役性/归属板块/处置建议）＝旧文档退役依据 |
| `docs/boards/_meta/code-quality-findings-20260921.md` | 代码质量 P0/P1/P2 缺陷台账（含最小修法与能杀行为的验收判据） |
| `.superpowers/sdd/2026-09-21-boards/logs/SEAT-*.md` | 逐席进度日志（心跳与断点） |

`dev.ps1 -Task sync` 现在会把板块树一起重算、一起体检（第四项要求的「不需要手动执行任何东西」的落点）。

## 二、为什么长这样（三条设计裁定，别改回去）

1. **板块树是派生件，不是第 N 份手抄清单。** 三级功能不在文档里手写：每个二级功能只登记「我拥有哪些 RouteKind / capability_id / 帮助主题 / 实现路径 / 配置键前缀」，三级清单由生成器在渲染期从 keystone 声明源与帮助注册表派生。新增一个能力 ⇒ 板块树自动多出它那张卡；删一个能力而文档还认领 ⇒ 红。
2. **覆盖门是活性判据，不是存在性判据。** 双向比对：代码里有而板块树没人认领 ⇒ 红；板块树认领了而代码里没有 ⇒ 红；一个席位被两个功能抢 ⇒ 红。上一波的教训（三把静态可达性门全绿而生产零投递）直接写进了 `_conventions.md` 第六节。
3. **人工正文与机器投影分区。** 每页 `<!-- BOARD-AUTO:BEGIN -->…END` 之间归机器，标记外归人。生成器只重写标记内，正文永远不会被覆盖；板块树不再认领且正文仍是空骨架的页会被自动删除，被人写过的页保留并点名要求手工归档。

计数纪律照旧：板块/功能/入口/主题数量只出现在生成物里，叙述文档一律指机器册或生成物。

## 三、门禁真值（本会话本人实跑）

- `python scripts/board_doc_sync.py --check` → `board-docs 同步正常（10 板块 / 57 功能 / 159 入口 / 主题 78）`，EXIT 0
- `pytest tests/test_board_taxonomy_gate.py` → 全绿（含注毒三发自证）
- `pytest tests/test_doc_link_integrity.py tests/test_documentation_consistency.py`（`docs/README.md` 登记后复跑）→ 42 passed
- `ruff check` 本波三个新 py 件 → All checks passed
- 工作树基线（继承 #47）：全量 1 failed（campus 坐标棘轮，他波 owner）/ 生成物三件 CLEAN / runtime-layout PASS

## 四、还剩什么没做（不许当成已完成）

1. **正文在飞**：11 席按板块独占写正文（B01-B10 + 两份台账）。收尾以各席日志与 `--check` 为准；本页落定时若仍有「（待写」，就是未完成。
2. **旧文档退役只做了依据没做搬迁**：`docs/HANDBOOK.md`（历史总账本体）、236 份 `docs/design/`、根目录 7 份 `HANDOFF-*` 仍原地。分类账给出的「归档 / 拆并 / 保留加指针」要逐条执行，移出源码树属不可逆动作，**须用户点头**，且凡被 `verify_hashes.py`、`test_doc_link_integrity.py`、`_NARRATIVE_DOCS` 钉住的路径要先改门。
3. **代码整理只出了台账**：`_conventions.md` 的四条硬门（先建模块与函数、禁第二真身、禁绕中央件、禁自造 token）目前只有 `_conventions.md` 的文字 + 板块树覆盖门兜住「登记」这一半；副本清零、命名 sweep、docstring 补齐按台账分级批量做，涉集中面的条目必须主会话串行。
4. **`_meta` 两份台账的板块归属需回填**：台账判定的主板块要和 `board_taxonomy.py` 的认领表对齐，冲突时以代码真身为准并改声明源，不要改文档迁就。
5. 未 commit、未重启 ⇒ 现网行为零变更；本波新增的都是文档与门禁，不涉运行时链路。

## 五、复跑命令簿

```bash
export PYTHONIOENCODING=utf-8
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe \
  -m pytest tests/test_board_taxonomy_gate.py tests/test_doc_link_integrity.py \
      tests/test_documentation_consistency.py tests/test_doc_sync_gates.py \
  -p no:cacheprovider --basetemp="$TEMP/boards" -q
PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe scripts/board_doc_sync.py --check
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task sync"   # 重算全部生成物
```

## 六、禁碰面（本波期间）

`config.py`、`.env`、`.env.example`、`docs/config-catalog-full.md`、`runtime/settings.py` 的两张键表、
三件生成物的 `--write`、`board_taxonomy.py`、`scripts/board_doc_sync.py`、根 `__init__.py`、
`capability_registry.py`、`base_router.py`、`tests/**`、`personas/**`、`ChatBot_Runtime/**`、`qx.json`。
席位只准写自己那一块 `docs/boards/BNN-*/**` 的标记外正文，或 `_meta` 台账自己那一份。


---

## 七、2026-09-21 收尾交接态（本轮终止时的真实账面，交给下一个 AI）

### 7.1 席位伤亡账（必须先读这段，否则会误判已有成果）
派了 11 席：板块总分类账 1 席与 B07 1 席交卷；其余 **9 席（B01B02 / B03 / B04 / B05 / B06 / B08 / B09 / B10 / 代码质量台账）全部在 57–93 次工具调用、约 10–22M token 处被服务侧掐死**，result 均为 `Sorry, something went wrong`。
**它们不是零产出**：正文已写到盘上才死，且死前没人误改 AUTO 段（`--check` 复跑为证）。逐席留下的痕迹在 `.superpowers/sdd/2026-09-21-boards/logs/SEAT-*.md`，续跑前先读对应席的日志尾部找断点。
教训已核实：**单席文档正文预算必须压到 ≤40 次工具调用、每 5 页落一次盘**；一批不要一次发 9 席（池并行度实测约 4，超出者会落进死区）。

### 7.2 现在有多少（当时的实测值，会随续跑变多，别当现役真值）
生成页 225（10 板块 / 57 功能 / 159 入口 / 帮助主题 78 全覆盖）；**正文已填 152 / 待填 73**。
零待写的板块：B01 接入与协议、B07 日程自动化助理。缺口最集中：B02 路由与中央调度 3/20、B04 记忆知识笔记 5/14、B09 控制面 11/25、B08 渲染出站 10/16。
逐板块实况用这条命令看（不要抄这里写的数）：
```bash
for d in docs/boards/B*/; do t=$(find "$d" -name '*.md' | wc -l);   f=$(find "$d" -name '*.md' -exec grep -L "（待写" {} + 2>/dev/null | wc -l); echo "$(basename $d) $f/$t"; done
```
列到具体文件：`find docs/boards -name '*.md' -not -path '*_meta*' -exec grep -l "（待写" {} +`

### 7.3 续跑的确切三步（顺序别换）
1. 只补骨架页，禁动 `<!-- BOARD-AUTO -->` 标记内；席间文件面互斥（一席一板块）。补完后跑
   `PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe scripts/board_doc_sync.py --check` → 必须 EXIT 0。
2. 门禁族复跑（命令见本页第五节）+ 全量 `dev.ps1 -Task test`。本轮最后一次全量在收尾时被启动，日志尾巴在
   `%TEMP%/boardwave-fulltest-1.log`（当时进度 6%，未见终局 ⇒ **不作已完成记账**）。
3. 正文齐了再做代码侧：`_conventions.md` 第三节四条硬门目前只有文字与板块树覆盖门兜「登记」这一半，
   副本清零 / 命名 sweep / docstring 补齐都还没做。

### 7.4 我已经量到、下一位可以直接用的代码侧线索（数字为当时实测）
- **零引用再导出垫片 25 个**（可安全退役候选）：集中在根层旧目录 `policy/`（5 个）、`security/`（3 个）、`sources/`（4 个）、`output/card_render/`（2 个）、`contracts/ decision/ llm/ sender/ audit/ capabilities/ runtime/` 等。逐条清单：按「头部含 `Compat shim` 且全仓无 import 引用」现场重算，别抄这里。
- **同名公开函数跨文件重复 3 组**（第二真身嫌疑，要逐组判定谁是真身）：
  `build_request_headers`（`link_parse/parsers/context.py` 与 `http_util.py`）、
  `build_session_identity_store`（根 `__init__.py` 与 `chat_reply/character/session_identity.py`）、
  `build_wbi_signed_url`（`parsers/platforms_bilibili.py` 与 `parsers/wbi.py`）。
- **能力入口不可被中央追溯 2 个**：`domains/chat_reply/capabilities/user_copy.py`、`domains/notes/capabilities/notes.py`
  （keystone / base_router / 根 `__init__.py` 三处都搜不到文件名 ⇒ 要么补登记，要么确认死码后退役。先证实再动）。
- 建议的落地形态：一个 `scripts/code_structure_check.py` + 常驻门，规则三条——新死垫片＝硬零、
  同名公开函数重复＝棘轮（现 3 组）、能力文件不可追溯＝棘轮（现 2 个）。**别做成存在性锁**，要能杀行为。

### 7.5 「旧文档搬家」这条我卡在一个事实上，等你点头才动
按你选的 A（只搬最没争议的过程件）实测：候选件**一个都不是零引用**——
`COORDINATION.md` 被 51 处引用、`HANDOFF-NEXT.md` 37 处、`progress.md` 75 处、`findings.md` 36 处、
`task_plan.md` 27 处、`V21-UPDATE-LOG.md` 与 `HANDOFF-SESSIONS-unify-audit-20260919.md` 各 14 处、
`report-T116.md` / `report-T124.md` 各 7–8 处。而 `tests/test_doc_link_integrity.py` 的死链基线只有 2 条 ⇒
**直接搬必然大面积判红**。要做就得先批量改引用（几十处、含 AGENTS/HANDBOOK 权威链），那是一件独立活，
我没动任何文件。要动请给我一句授权，我按「先改引用→复跑门→再搬→复跑」顺序做。

### 7.6 收尾时刻的门禁真值（主会话本人实跑，交接前最后一次）
- `scripts/board_doc_sync.py --check` → `board-docs 同步正常（10 板块 / 57 功能 / 159 入口 / 主题 78）`，EXIT 0
- `pytest tests/test_board_taxonomy_gate.py tests/test_documentation_consistency.py tests/test_doc_sync_gates.py` → **45 passed**
- `pytest tests/test_doc_link_integrity.py` → **17 passed**（曾有一度全量面缺陷条目 181 > 上限 167：
  席位写正文时把测试件名缩写成 `_push.py`/`_signal.py` 这类残名、把外部仓引擎文件与本仓垫片当路径引用，
  我逐条改回真身全名后归零，**没有降任何基线**）
- 生成物三件 `--check` 全 EXIT 0；`ruff`/`mypy` 本波三件新 py 全绿
- 全量 `dev.ps1 -Task test` **拿到终局**：
  `= 2 failed, 10975 passed, 13 skipped, 27 xfailed, 2 xpassed, 4 warnings in 498.67s =`（Python 3.12.10 / pytest 9.1.1）
  两条红逐条归因：① `test_campus_digest.py::test_outbound_registry_campus_coordinate_is_live`
  —— 继承 #47 的唯一红（登记 5027 ≠ 活体 5032，本会话之外的编辑动过根文件与登记表），**按纪律不代改**，归该门 owner；
  ② `test_doc_link_integrity.py::test_inflight_wave_docs_do_not_explode` —— **本波造成**（181 > 167，
  成因见下条），修完后该门单跑 **17 passed**；即全量日志里的这条是修复前现场的记录，不是残留红。
  注：终局跑与修复交错，若要以「一条红」作数，请在新会话按第七节第五项复跑全量确认。
- 源码树卫生：清走本会话跑测留下的 `__pycache__`（备份 `%TEMP%/chatbot-stray-pycache-*`），无 `data/`、无 `.pytest_cache`
