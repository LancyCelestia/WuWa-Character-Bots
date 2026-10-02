> 出处＝2026-10-02 修复波取证席 HB-C 产出（原写于 gitignore 的 `.superpowers/sdd/2026-10-02-fixwave/HB-C-taxonomy-decoupling.md`，该目录不受版本控制；本文件是**入库副本**，防下一次整树还原再吃掉一次）。
> 该席最终被**当日额度墙**打断（47 次调用即断，非 150 顶死法），末节可能不完整；引用前请按文中命令现算复核。

# HB-C · 三篇交接册：物理文件归类进度 / 功能说明与实现耦合 / 文件解耦进度

> 席位＝HB-C（交接文档撰写席，只读普查＋只写本文件）。日期＝2026-10-02。
> 上游账＝`docs/HANDOFF-FIXWAVE-20261002.md` §八/§九/§十（本册是它的**展开与现算复核**，不是替代）。
> 🔴 **本册只出册、不动手**：本波有过两次整树清空事故（#70★、`patches/INCIDENT-20260930-TREEWIPE-RECOVERY.md`），
> 归类与退役动作一律留给主会话用 `git mv`/`git rm` 执行。本席零 git 写、零进程动作、零配置改、
> 除本文件外零写盘；`plugins/bot_unified_runtime/domains/weather/assets/qx.json` **未碰**（NMC 塌向 open-meteo 的前车，AGENTS 规则 6）。

## ⚡ 断电警告（接手第一件事，不论接的是哪一篇）

1. `git status --porcelain` 重跑一遍，与本册 §0 的读数对照——**本册写作期间别席在飞**（`chat.py`/`quirks.py`/`reply_policy.py`/`tts.py`/`media_archive.py`/`AGENTS.md`/`docs/auto-facts.md` 皆 ` M`）。
2. 全树 `ast.parse` 复跑（半成品语法错会让整棵测试树起不来，本波 `test_db_backup.py` 就停在这上面、已改名到 `.superpowers/sdd/2026-10-02-fixwave/half-done/`）。
3. 任何"已完成/已迁/已删"的字样，先按 AGENTS 规则 5 要提交哈希或可复跑命令，否则记为未完成。

---

# 第一篇 · 物理文件归类进度

## 0. 现算读数（全部实跑，2026-10-02；命令原文在每格括注）

| 项 | 现算值 | 册上值 / 判据 | 取数口 |
|---|---|---|---|
| `docs/design/` 总件数 | **242** | — | `ls docs/design \| wc -l` |
| 其中 `*-log.md` 过程日志 | **126 枚 / 1,096,124 B** | HANDOFF §八 写「约 127 枚」⇒ 差 1（当时值，现算以本行为准） | `python` 枚举 `glob('*-log.md')` |
| `docs/design/` 非日志件 | **116** | 规格/审计/施工图，属"该留" | 242−126 |
| `docs/` 顶层跟踪件 | **36** | 规范要求"只准保留现役权威件与生成物"（`docs/boards/_conventions.md` §一.5） | `git ls-files docs \| awk -F/ 'NF==2'` |
| `.qoder/settings.local.json` | **仍被跟踪**（工作树干净，未被 ignore） | 🔴 与 `.gitignore:79` 的**意图**矛盾，见 §2 | `git ls-files .qoder/` + `git check-ignore -v`（RC=1＝不忽略） |
| `SHIM_ROWS` 账上登记垫片 | **15 行** | 扫描面待退役 **23** ⇒ **漏记 8 枚**（逐枚点名见 §3） | `scripts/shim_retirement_census.py --check` 实跑 |
| 域外全量（三态之和） | **75 / 基线 74 ⇒ `RISE!`** | 硬锁只准降（`OUTSIDE_BASELINE=74`）⇒ **此刻是一枚红** | 同上，末行 `硬锁·三态之和(域外全量) 75/基线 74 (RISE!)` |
| `AGENTS.md` 体积 | 工作树 **29,985 B**（HEAD 版 29,993 B，差 8 B＝别席在飞改动） | 软顶 30,000（**距线 15 B**）／硬顶 32,768（**距线 2,783 B**） | `wc -c AGENTS.md` + `git show HEAD:AGENTS.md \| wc -c` |
| `COMMANDS.md` 体积 | 24,187 B | **不在体积门执法名单内**（见 §5） | 同上 |

## 1. 十板块规范怎么说（判据真身）

`docs/boards/_conventions.md` §一.5 原文口径：**「根目录与 `docs/` 只准保留现役权威件与生成物；波次过程件（席位日志、brief、report）留在 `.superpowers/`，不进 `docs/boards/`」**。

- 这条**已被新波次遵守**：`.superpowers/sdd/2026-09-20-spec-audit/audit-SA*-log.md`、`2026-09-22-taxonomy/*`、`2026-10-01/10-02-fixwave/*` 都在该在的地方。
- 违规存量＝**2026-09-22 之前的 v21r2 / v21r4-b / v21r5 三代波次的 126 枚 `docs/design/*-log.md`**（mtime 全落在 2026-09-29→09-30，最后一次提交＝`4e4a8645`（2026-10-01 15:51:48 +0800，`wip(docs): 板块投影与设计档在飞快照`）⇒ **09-30 之后无人再写它们**，是死账不是活账）。
- ⚠ 规范本身**没有机器门**：`tests/test_doc_link_integrity.py` 只判"链接指向的文件在不在"，不判"该不该在 `docs/design/`"。所以归类动作没有任何东西在催——这就是它躺了十天的原因。**要落地必须先立归属门**（§6 动作 1）。

## 2. 逐类：该迁到哪 / 迁它牵动什么 / 谁在写它

### A 类 · `docs/design/*-log.md`（126 枚，过程日志）
- **该迁到哪**：`.superpowers/sdd/<原波次日期>/design-logs/`（按波分三堆：`v21r2*` / `v21r4-b*` / `v21r5*` + `affinity-v8-log.md`、`v21-affinity-fix-log.md` 等零枚）。目标目录沿用现役先例（`.superpowers/sdd/2026-09-22-taxonomy/`）。
- **迁它牵动（这四件是真成本，别当免费）**：
  1. 🔴 **`.superpowers/` 整目录被 gitignore**（`.gitignore:42` `.superpowers/`，`git ls-files .superpowers`＝**0**）⇒ `git mv` 之后**内容等于离开仓库**：git 只记删除，新位置不跟踪。**bundle/tar 备份也不含未跟踪件**。若不接受"过程日志从此只在本地盘"，就必须给 `.superpowers/` 加一条否定规则（`.gitignore` 里 `!.superpowers/sdd/**`）再迁——这条裁定要用户拍，本席不代裁。
  2. `docs/README.md` 是**人读索引**，逐枚点名这些日志（例：`:151` `design/v21r5-TIMEOUT-log.md`、`:152` `-INTIMACY-`、`:153` `-POLICY-`、`:143` `design/v21r4-b-*-log.md（各席日志）`）⇒ 每迁一枚都要同批改索引行，否则 `test_doc_link_integrity.py` 死链当场红。
  3. `docs/HANDBOOK.md` 里**按文件名引用**（实算至少 2,267 / 2,280 / 2,306 / 2,311 / 2,359 / 2,361 / 2,362 / 2,368 / 2,372-2,378 行，如 `v21r4-b-REM-EVE-log.md §③`、`v21r5-U17VERIFY-log.md`）。这些是**波次全账的回滚点**（HANDBOOK §33/§34 明文"回滚点在 v21r4-b-REM-EVE-log.md §③"），链接形态多为纯文本不是 markdown 链接 ⇒ **链接门看不见它们**，改漏了就是静默死指针。
  4. `AGENTS.md` 第六部分台账（#41-#43 指向 `§32/§33/§34`）间接依赖 HANDBOOK，不直接点名日志 ⇒ 若 HANDBOOK 指针不动，AGENTS 不受影响。
- **归属账**：`docs/design/` 非日志件（116 枚）里的 `audit-20260920-unify-U*-*.md`、`v21r4-b-*-PLAN/CHARTER/snapshot`、`link-unification-audit-20260920.md`（被 `test_doc_link_integrity.py:72` **写死在豁免/白名单里**）是**规格与施工图**，按 §一.5 属"权威件"，**不迁**。
  ⚠ 关键耦合：`tests/test_doc_link_integrity.py:3` 与 `:72` 直接引用 `docs/design/link-unification-audit-20260920.md` ⇒ **该文件一旦移动，门自己红**。这类"门里写死的坐标"必须逐枚先查再动（`grep -n "docs/design" tests/*.py`）。

### B 类 · `.qoder/settings.local.json`（取消跟踪）
- **矛盾实况（现算，与简报表述有别）**：`.gitignore:79` 是一行**注释** `# Local agent tool configs (workspace-local, never commit)`，其管辖块只列 `.claude/`、`.codex/`、`.grok/`、`third_party/`——**`.qoder/` 整目录不在名单里**；全文件只在 `:127` 单独 ignore 了 `.qoder/scheduled_tasks.json`。所以矛盾不是"ignore 了却还跟踪"，而是**注释承诺的口径没有对应规则**（`git check-ignore -v .qoder/settings.local.json` ⇒ RC=1，不忽略）。
- **该迁到哪**：不迁，**取消跟踪 + 补 ignore**（`.gitignore` 那一段补一行 `.qoder/settings.local.json`，别一杆子 `.qoder/`——`scheduled_tasks.json` 已有单条，说明这目录里是**混合跟踪**状态，整目录 ignore 会把该留的也吞掉）。
- **牵动**：`git rm --cached` 会让所有会话首次启动 bot 前拿不到本地 IDE 配置副本（可接受，它是 IDE 侧产物）；无测试引用（`grep -rn "\.qoder/" tests/` 零命中，本席未复核到反例）。
- **谁在写它**：最后提交 `ebb7130d`（2026-09-22 01:19:31 +0800，`存档：睡前基线`）⇒ 十天无人动、且那笔是"睡前基线"式的**顺手全量存档**，正是它混进来的成因。

### C 类 · `docs/` 顶层 36 件的分类账（只出册，不动手）
现役权威件（**留**）：`HANDBOOK.md`（单一活文档）、`README.md`（索引）、`CODE-MAP.md`、`auto-facts.md`（机器册）、`db-owners.md`、`affinity-design.md`、`rendering-contract.md`、`route-matrix.md`、`issue-ledger-p2-p3.md`、`THIRD_PARTY_NOTICES.md`（AGENTS 明文"勿删"）、`command-catalog.md`＋`config-catalog-full.md`（生成物，禁手改）、`核心要求.md`／`Bot需求.txt`（用户原始诉求）。
**过程件（该迁 `.superpowers/` 或 `docs/boards/`，逐枚牵动＝README 索引行 + 台账 #编号）**：
`audit-20260921.md` / `audit-20260921-commands.md` / `audit-20260921-decisions.md`（审计三件套）、
`nightly-ops-report-20260915.md`（一次夜巡报告）、`usage-cache-price-fix-2026-09-18.md`（单点修复账）、
`perf-optimization-plan.md`、`codebase-slim-plan.md`（计划件，执行完即归档）、
`control-plane-provider-and-usage-requirements-2026-09-05.md`、`search-api-adapters-2026-09-06.md`（**已被 `docs/design/control-plane-core-status.md` 取代**，AGENTS 第七部分明文控制面唯一事实页）、
`HANDOVER-2026-09-15.md`、`handover-c-20260913.md`（交接件——⚠ AGENTS 第七部分**明文"例外件保留原样"**，这两枚**不许动**）、
`feature-backlog-20260930.md`、`pending-decisions.md`、`workspace-archive-policy.md`、`external-runtime-access.md`、`ai-kb-operations-manual.md`、`ai-setup-knowledge-pack.md`、`acceptance-manual.md`、`standard-parse-card-acceptance.md`、`napcat-setup.md`、`snowluma-setup.md`。
- **判据提醒**：`HANDOFF-FIXWAVE-20261002.md` 是**在册交接册**（AGENTS 接手入口表按名引用），属"现役"不属"过程件"。
- **谁在写**：`git status` 现算 `docs/` 只有 `HANDBOOK.md`、`auto-facts.md`、`db-owners.md` 三枚 ` M`（别会话 #72 波 + 本波 X2 席）⇒ 其余 33 枚静止。

### D 类 · `docs/` 里两个非日志子目录
`docs/superpowers/`（2 项：`plans/`、`specs/`）与 `docs/templates/`（22 项：`brief.md`、`card-fstring.md`、`card-html.md`…）。
- `docs/superpowers/` 与根 `.superpowers/` **同名不同物**，是归类混乱的活标本：规范要求过程件进 `.superpowers/`，这里却有一枚仓库内的影子目录。**处置＝先读它有没有被引用**（`grep -rn "docs/superpowers" tests/ docs/README.md`）再决定并账，不许直接删。
- `docs/templates/` 是卡片模板样例册（渲染契约相关），不是过程件；**别和 `domains/render/card_render/templates/` 混为一谈**——后者是运行时真身，前者是文档侧样例，属"两处"问题（归第三篇 §10 的口径分叉类）。

## 3. `SHIM_ROWS` 垫片账：漏记的 8 枚逐一点名（`--check` 实跑输出）

现算三态：**已归类 7 ｜ 待搬迁 45 ｜ 待退役(垫片) 23**，域外 py 全量 **75**；账上登记 **15 枚** ⇒ **`missing_registration` 8 枚**：

| # | 漏记垫片 | 备注 |
|---|---|---|
| 1 | `plugins/bot_unified_runtime/capabilities/auto_send/__init__.py` | 🔴 **复活件**：账本文件头注自陈 2026-09-28 S-SHIM-WAVE1 T5 已退役（真身 `domains/schedule/auto_send/__init__.py`），06:30:29 那次外部 `restore` 把文件连账本行一起写回（#68★）。HANDOFF §八「四件同批退役」指的就是它，**且已知会让一枚门跨窗红**（`tests/test_copy_redline_gate.py::test_gate_scope_sanity` 是配对判据） |
| 2 | `plugins/bot_unified_runtime/capabilities/market.py` | 域外再导出垫片未入册 |
| 3 | `plugins/bot_unified_runtime/runtime/settings.py` | 热改态登记真身（#68★「幽灵字段三面齐」里的第二面），常驻件却出现在待退役桶＝**桶位待裁** |
| 4 | `plugins/bot_unified_runtime/security/memory_sanitize.py` | v21r5-POLICY 席动过（`docs/HANDBOOK.md:2311` 提"C 席…memory_sanitize 收窄"） |
| 5 | `plugins/bot_unified_runtime/sender/__init__.py` | 包级垫片 |
| 6 | `plugins/bot_unified_runtime/sender/onebot.py` | 出站腿，`AGENTS.md` 第三部分流程图按名引用（`sender/onebot`）⇒ 退役要同批改 AGENTS |
| 7 | `plugins/bot_unified_runtime/sources/fetchers/__init__.py` | 包级垫片 |
| 8 | `plugins/bot_unified_runtime/sources/subscriptions/__init__.py` | 包级垫片 |

同一次 `--check` 还给出三条**必须一并入账**的读数：
- **读点盲区 3 枚**（命中垫片记号但派生不出存在的真身 ⇒ 只读附账、不改桶）：`audit/__init__.py`、`contracts/__init__.py`、`llm/__init__.py`。
- **待搬迁 45 枚的真面目**：`真可搬 0 ｜ 落点已存在·禁覆盖 5 ｜ 基础设施常驻原地 40` ⇒ **"待搬迁 45"里 40 枚根本不该搬**，那格基线是虚胖；搬迁面只有 5 枚，且都属"禁覆盖"。**下一窗别按 45 规划工作量。**
- **`OUTSIDE_BASELINE` 硬锁 75/74 RISE!** ⇒ 唯一合规处置＝**同批把某态真降 1 枚**（最省事的正当路径就是 §4 那 8 枚里的 auto_send 复活件退役——文件删＋账本行摘＋基线复录三件同批，#68★），或如实登记为既存红。
- 并列账：`G-P2 豁免条数 28`（只读取数，同门记 29 上限）⇒ 还有 1 条余量，别一次填满。
- 反查：`SHIM_ROWS` 里 15 行的文件**全部还在盘**（幽灵行 0）。

## 4. 退役动作的正确形状（写给主会话，本席不动手）

一枚垫片"退役"＝**四个动作同批**，缺一个必红另一个（#68★在册原文口径）：
① 迁完调用方 → ② 删 `plugins/bot_unified_runtime/<旧路径>.py` 文件 → ③ `scripts/shim_retirement_census.py --write-ledger` 重录（`SHIM_ROWS` 摘行 + 各 `refs` 上限只降）→ ④ 若该旧名被 HANDBOOK/AGENTS/板块页按字面引用，同批改指针。
`--write-ledger` 默认 `min(既有, 现算)`：**抬不动上限**，想上调唯一通道是 `scripts/shim_refs_approvals.json` 显式审批（带 `expiry`）。
⚠ 复跑任何派生册一律 `BOT_AUTOSYNC=0`（否则 conftest 会静默重写四件生成物＝越界改别席在飞面，本波四席踩过）。

## 5. `AGENTS.md` 体积：现算 + 压缩次序建议（**本席一字未改**）

- 执法真身：`tests/test_documentation_consistency.py:757` `_ENTRY_SIZE_CEILING = 32768`、`:760` `_ENTRY_SIZE_DOCS = ("AGENTS.md",)`、`:791` `test_entry_docs_within_size_ceiling`。
- 🔴 **两个必须知道的门实情**（简报没写、现算才发现）：
  1. **机器门只咬 32,768，不咬 30,000**。软顶 30,000 只存在于 AGENTS 页首散文 ⇒ 现值 29,985 B 距软顶**只剩 15 字节**而门仍是绿的；任何一句新增都会破软顶却不报警。这是一格**门禁假绿面**（`_conventions.md` §六 P1 类）。
  2. **`COMMANDS.md`（24,187 B）不在执法名单**，尽管自证用例 `test_size_gate_bites_on_oversized_and_spares_small` 拿 `COMMANDS.md` 当"达标放行"的样本——它只是测试夹具，不是被执法对象。
- 压缩次序建议（**按 AGENTS 页首既定次序，本席不改文件**）：
  1. 第六部分台账 #1-#36 的"完成/已知边界"类行正文——**编号与排序绝对不动**（代码按号注释引用）。可压的是 `11`~`25` 那批"→ 完成"行，正文压成"→ 完成（§NN）"一格一字。
  2. 第四部分功能表的「红线/关键约束」列——尺＝该部引言；载体列一字不删（`test_doc_link_integrity.py` 子门 ③ 逐条判字面真身）。
  3. 合并被取代的旧入口：接手入口表里 `HANDOFF-BOARDS-20260921.md` 已明文"被取代"，可从表里摘掉整行留一句指针。
  4. 散文：第一部分规则 11 的举例、第三部分括注。
  ⚠ 体积门自证过"判决会点名最重的几节"，用它的报错文本决定删哪里，别凭感觉。

## 6. 只出册 vs 可安全立即清（两栏分明）

**🔒 只出册、绝不动手（本席判定＝一律交主会话/用户裁定）**：A 类 126 枚日志（牵动 gitignore/README/HANDBOOK 三本账）、B 类 `.qoder` 取消跟踪（要改 `.gitignore`＝配置面）、C 类 36 件顶层重分类、D 类两个同名子目录、§3 的 8 枚垫片与 `auto_send` 复活件、`.gitignore` 死规则清理（`research/*` 11 处、旧家 2 处——HANDOFF §八 ⚪ 项）。
🔴 绝对禁区复述：`domains/weather/assets/qx.json`（.gitignore 有否定规则保它，清理波曾误清致 NMC 整体塌向 open-meteo）、`personas/` 与 Runtime 人格副本、Runtime 下任何 SQLite/FAISS/记忆/cookie/日志/venv（AGENTS 规则 2）。

**🟢 可安全立即清（清单已现算，动作仍归主会话）**：本波 §八 已清掉「13 个空目录 + `cb-w9chk/` + `run.txt`」（备份 `%TEMP%/qoder-hygiene-20261002/` 带 md5 对照）；**剩余可清面本席现算＝零枚新增**（`docs/superpowers`、`docs/templates` 都非空，不能算空目录）。
若下一窗要清源码树卫生残余，纪律照抄：
1. 先 `cp -p` 备份到 `%TEMP%/<带日期的目录>/` 并逐枚 md5 对照（先例：`qoder-data-residue-20261002/`）；
2. **dry-run 出清单**（`find … -print`，不接 `-delete`），人工点名；
3. **只删白名单里的具体路径**（一枚一条 `rm`/`del`），**严禁以工作树为根的递归删**（`rm -rf ./*`、`git clean -fdx`、按模式通配批删都算事故）；
4. `__pycache__`/`*.pyc`/`.pytest_cache`/`.ruff_cache`/`.mypy_cache` 之外的一切"看起来像缓存"的文件——先证明零引用再删；
5. 绕开 `scripts/dev.ps1` 直跑必带 `PYTHONDONTWRITEBYTECODE=1` + `-p no:cacheprovider` + `--basetemp=<仓库外>`（规则 6）。

## 7. 下一个 AI 的最小可验收动作（按依赖排序）

1. **先立归属门再搬家**：给"过程日志不许在 `docs/` 下"写一枚静态门（扫 `docs/**/*.md` 文件名命中 `*-log.md`/`*-brief.md`/`*-report.md` ⇒ 红，基线 126 枚只准降）。验收＝注毒自证：往 `docs/design/` 放一枚 `zz-fake-log.md` 必红，删掉必绿。**没有这枚门，迁完还会再长回来。**
2. 问用户一句话并落账：**`.superpowers/` 要不要加否定规则继续跟踪**（决定 A 类是"迁走"还是"从仓库消失"）。引不出裁定就按"仍在盘上但 git 不再记"记账，不许自行结案。
3. 同批处理 `auto_send` 复活件（§3 表第 1 行）：文件退役 + `SHIM_ROWS` 摘行 + `--write-ledger` 复录 + 配对判据 `test_copy_redline_gate.py::test_gate_scope_sanity` 实跑——并把 `OUTSIDE_BASELINE` 从 74 的 RISE 拉回（75→74 或按现算复录，**容差一字不动**）。
4. 把 §3 表 2-8 共 7 枚漏记垫片用 `--write-ledger` 现算入册（不许手抄真身路径，门 ③④⑤ 会红），复跑 `python scripts/shim_retirement_census.py --check` 贴末行读数。
5. `.gitignore` 补 `.qoder/settings.local.json` 一行 + `git rm --cached` 一枚，提交后 `git show --stat HEAD` 核对只有这两处（规则 4）。
