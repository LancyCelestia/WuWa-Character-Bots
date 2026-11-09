# 多进程协作写安全 · 设计规格

- 日期：2026-10-19
- 状态：**待用户审**
- 触发：票 8 执行中发现「票面声称已交付，实际全在另一 worktree 未提交」，且主检出被并行进程持续写入
- 目标：让「多个 LLM 进程同时干活」在结构上不互相踩，而不是靠各自自觉

---

## 一、要解决的问题（四条并存的根因，逐条有实测）

| # | 根因 | 实测证据 | 对应损失 |
|---|---|---|---|
| R1 | **没有任何「占有」原语** | `.claims` / `.locks` / `.coord` / `.seats` 全不存在；`dispatch_saturation_snapshot.py` 只**数**在飞席（读 `qodercli.log` 的 `start/finish/error`），不**防撞** | 写冲突、重复劳动 |
| R2 | **worktree 不是隔离，是半残副本** | `scripts/runtime_paths.py:32` `PROJECT_ROOT = parents[1]`，Runtime 假定为**同级** `ChatBot_Runtime`。主检出同级存在；`mainline-identity` worktree 同级**不存在** ⇒ `runtime_data_dir()` 实测解析成 `<worktree>/data`（**源码树 data/**，规则 1/6 明令禁止的落点）。同时被 gitignore 的 `.env` 在 worktree 天然缺席 | 门假红、跑不了真测试、只好挤主树 |
| R3 | **WIP 只活在树上，没有落盘点** | 票 8 全部交付 = worktree 里 130+ 项未提交改动；台账 #68 外部 restore 吃掉 WIP 且 HEAD 未动 ⇒ 捞不回 | WIP 丢失 |
| R4 | **裁定与机器尺各说各话** | `docs/boards/_meta/doc-classification-20260921.md:39` 判 `GLOSSARY.md`「保留原地」，但 `ROOT_WHITELIST` 里没有它 ⇒ `root_hygiene_census` 判 MUST-MOVE | 仓结构反复复发 |

**这四个不是同一类问题，所以需要三种机制 + 一条纪律，不能一个补丁解决。**

---

## 二、方案

### A · 修好隔离（治 R2）

#### A0. 先纠正一个危险直觉（本规格的自查记录）

初稿曾设想「worktree 同级找不到 Runtime 就**回落到生产** Runtime」。**这是错的，必须否掉**：

- 生产 Runtime 里是**生产 SQLite**。让 worktree 回落过去，等于让隔离环境里的测试**直接写生产库**——正是台账 #76 记录的「孤儿 pytest 会写生产库」事故形态。
- 隔离的价值是「写不到生产」，回落生产会把这个价值整个抹掉，且**比现状更危险**（现状至少落在没人用的 `<worktree>/data`）。

⇒ **正确语义是 fail-closed，不是静默回落。**

#### A1. 路径真身（实测确认，勿再猜）

```
git -C <worktree> rev-parse --git-common-dir
  → C:/Users/.../ChatBot/ChatBot/.git        （绝对路径，指向主检出）
```

推导：
- `<common-dir>` = `<主检出>/.git`
- `<主检出根>` = `<common-dir>` 的**父**
- `<生产 Runtime>` = `<主检出根>` 的**父** + `ChatBot_Runtime`

（初稿写成「common-dir 的父目录存在 ChatBot_Runtime」是**错的**，少退了一层。）

#### A2. `runtime_paths` 的 worktree 语义

在 `runtime_data_dir()` 的现有优先级**之后**、源码树 `data/` 兜底**之前**，插入一腿：

- **判定**：`git rev-parse --git-dir` ≠ `git rev-parse --git-common-dir` ⇒ 当前是 worktree
- **若在 worktree 且 `BOT_RUNTIME_DATA_DIR` 未显式给** ⇒ **抛 `RuntimeIsolationViolation`**，消息含：
  - 当前是 worktree、worktree 路径
  - 应执行的 bootstrap 命令
  - 明确写「不会回落到生产 Runtime，也不会落到源码树 data/」
- **若在 worktree 且已显式给** ⇒ 用给定的（由 bootstrap 建好的 worktree 本地 Runtime）

> 生产 bot 从主检出跑 ⇒ `git-dir == git-common-dir` ⇒ 该腿不触发 ⇒ **生产行为零变化**。

#### A3. 新增 bootstrap 脚本（**尚未创建**，占位名 `worktree_runtime_bootstrap`）

给一个 worktree 建**本地** Runtime：

| 子目录 | 做法 | 理由 |
|---|---|---|
| `card_render_assets/` | **junction** 指向生产 Runtime 的同名目录 | 只读资产（mermaid 等），共用省磁盘，且不可能被写坏 |
| `venv/` | **junction** 指向生产 Runtime 的 venv | 只读解释器环境 |
| `data/` | **真实新目录**（空） | 可写状态必须隔离，绝不共用生产库 |
| `logs/` / `cache/` | **真实新目录** | 同上 |

脚本跑完打印一行可复制的 `set BOT_RUNTIME_DATA_DIR=...`，并在 worktree 根写 `.worktree-runtime` 标记文件（便于事后识别）。

#### A4. 纪律写进 AGENTS

- 主检出（`ChatBot`）**只做集成与验收**，不开席、不跑长测试
- 一任务一 worktree，分支名 = 任务 slug
- worktree 建立后**先跑 bootstrap**，再跑 `runtime_data_dir()` 自检
- 小步提交：一个可验收单元 commit 一次；`git add <具体文件>`，**禁** `git add -A` / `-a`；提交信息带任务 slug

### B · 文件级认领（治 R1）

**B1. 认领文件落点**

`.git/claims/`（经 `git rev-parse --git-common-dir` 定位）——**四个 worktree 共享同一份**（已实测 common-dir 相同，这是跨 worktree 可见的物理基础）。

```json
{
  "path": "scripts/root_hygiene_census.py",
  "owner": "<session id>",
  "started_at": "2026-10-19T09:00:00Z",
  "ttl_minutes": 120,
  "task": "票 8 · C 方案白名单收口"
}
```

**B2. 规则**

- 写前先查 `.git/claims/<slug>.json`
- 存在且未过期 ⇒ **报「他人在写」并停手**，不自动抢
- 过期（超 TTL）⇒ 标 `stale`，允许接管，但**接管必须留痕**（记录前主与接管时刻）
- 任务完成 ⇒ 删除认领

**B3. 必须诚实说明的边界（本方案的已知天花板）**

认领**只能拦自觉调用它的进程**。以下**一律不受控**：
- `git` 自身（`checkout` / `restore` / `clean` / `reset`）
- 编辑器、外部工具、IDE 插件
- 外部 restore 操作（台账 #68 那类事故）

> `ponytail:` 认领机制的已知天花板 = 「靠自觉」，与 AGENTS 现有规则同属社会约定，**不构成物理互斥**。
> 升级路径：真要物理互斥需文件系统级锁（Windows `msvcrt.locking` 或原子 `mkdir` 锁目录），
> 成本高且跨进程死亡易留死锁。**本波不上。**

### C · 裁定入机器可读白名单（治 R4）

**依据（用户 2026-10-19 裁定）**：把 `docs/boards/_meta/doc-classification-20260921.md` 里**已有的成文裁定**搬进 `ROOT_WHITELIST` 带理由。

> ⚠ **这不是新开豁免**，是把已有裁定落地，消除「裁定与尺各说各话」。但它在字面上**推翻了票 8 原话「一条都不是加豁免」**，所以本规格把它单列为一步、单列一次验收，不与 A/B 混在一起悄悄做。

| 件 | 分类册裁定 | 落地到 `ROOT_WHITELIST` 的理由文本 |
|---|---|---|
| `GLOSSARY.md` | `:39`「保留原地；唯一职责是钉死同词异义」 | 引用该裁定原文 + 权威链最低层自述 |
| `REVIEW-WORKFLOW.md` | `:30`「并入 B10 评审与归档规程」 | 同上，注明并入状态 |
| `WORKSPACE_GUIDE.md` | `:32`「并入 B10 开头」 | 同上，注明并入状态 |

**C2. 加门**：`root_hygiene_census --check` 的 MUST-MOVE 必须为 0；不为 0 即 FAIL。

> 这条门**不是恒红**：`ROOT_WHITELIST` 补齐后自然过。若某天有人新增根层散件，门会红——这是设计意图。

**C3. 已知副作用（必须先说）**

`test_root_hygiene_whitelist_covers_the_real_tree_in_both_directions` 当前另有一批红点（`.claude`/`.codex`/`.grok`/`.workbuddy-ai`/`.zcode` 在册却不在盘；worktree 缺 `.env`/`.env.prod`）。
**这批不属本规格**，C 步只保证「不新增红」，不承诺「把存量红清零」。存量红另开票。

---

## 三、验收标准（可复跑）

| # | 验收项 | 命令 | 通过条件 |
|---|---|---|---|
| V1 | worktree 未 bootstrap 时 **fail-closed** | 在 worktree 跑 `runtime_data_dir()` | 抛 `RuntimeIsolationViolation`，消息含 bootstrap 命令 |
| V2 | worktree bootstrap 后可解析 | 跑 bootstrap → 再跑 `runtime_data_dir()` | 输出 `<worktree>/ChatBot_Runtime/data`，**不含**源码树 `data/` |
| V3 | 生产零变化 | 主检出跑 `runtime_data_dir()` | 与改动前逐字相同 |
| V4 | 认领跨 worktree 可见 | 主检出写认领 → worktree 读 | 读到同一份 |
| V5 | 认领过期可接管且留痕 | 人为设过期 TTL → 接管 | 报 `stale` 且留痕 |
| V6 | 根层 MUST-MOVE = 0 | `python -B scripts/root_hygiene_census.py --check --json` | `violations == 0`，rc=0 |
| V7 | 白名单与真树双向一致 | `pytest tests/test_physical_placement_gate.py -k whitelist` | 该腿绿 |
| V8 | 净新增红 = 0 | 改动前后同尺对跑 | 不比 BASE 多红 |

---

## 四、明确不做（YAGNI）

- 不做文件系统级物理锁（跨进程死亡易死锁，成本高）
- 不做「自动抢认领」（会从防冲突变成制造冲突）
- **不做「worktree 回落生产 Runtime」**（会写生产库，见 A0）
- 不动 `git` 自身的配置或钩子
- 不新建 `tests/test_*.py`（AGENTS 硬规：会让 `doc_sync` 测试数派生漂移；执法腿一律追加进 `tests/test_physical_placement_gate.py`）

---

## 五、风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| B 给人「已锁住」错觉 | 认领拦不住 git/外部工具 | 规格与代码注释**双处**写明天花板 |
| A2 抛异常影响现有 worktree | 现有 3 个 worktree 未 bootstrap，会立刻 fail-closed | 这是**设计意图**（宁红不假绿）；bootstrap 脚本同批交付，跑一次即恢复 |
| C 推翻票 8 原话 | 字面矛盾 | 单列一步、单独验收、在票 8 正文同步记明是**用户裁定授权** |
| worktree 里 `.env` 天然缺失 | 测试读不到配置 | 不复制 `.env`（密钥不入多份）；由 bootstrap 从环境变量注入必要键 |
| worktree 磁盘增长 | 每个 worktree 一份 data | 资产与 venv 走 junction，只有 data 是真实目录；配 stale worktree 清理 |

---

## 六、与既有资产的关系（避免第二真身）

- **复用** `scripts/runtime_paths.py`（R1 的判定真身，不另写）
- **复用** `scripts/root_hygiene_census.py` 的 `ROOT_WHITELIST`（唯一白名单常量）
- **复用** `scripts/dispatch_saturation_snapshot.py`（继续数在飞席，不改其职责）
- **执法腿追加**进 `tests/test_physical_placement_gate.py`（不新建测试文件）
- **新增**仅 bootstrap 与认领两个脚本（均**尚未创建**）

---

## 七、落盘前置检查（「会不会撞」的实测结论，2026-10-19 17:52）

### 7.1 两种「撞」要分开看

| 撞法 | 是否发生 | 证据 |
|---|---|---|
| **并发覆盖**（两个进程同时写同一文件，后者赢） | **不会** | 正在飞的进程只写 `webui/**`（实测 17:51 `dashboard.tsx`、17:49 `index.html`、17:41 `index.css`…），本规格**一个 webui 文件都不碰** |
| **踩别人未提交的改动**（在别人 WIP 上继续改 / commit 时卷走） | **会** | 见下表 |

### 7.2 四个目标文件的实况

| 文件 | git 状态 | mtime | 本规格要动它吗 | 风险 |
|---|---|---|---|---|
| `scripts/runtime_paths.py` | **干净** | 2026-10-04 | A2 | ✅ 零碰撞 |
| `tests/test_physical_placement_gate.py` | **干净** | 2026-10-11 | V7 执法腿 | ✅ 零碰撞 |
| `scripts/root_hygiene_census.py` | **脏**：1 行 `webhook 8080 → 8099` | 2026-10-17（2 天前） | C（`ROOT_WHITELIST`） | ⚠ 定向 `edit` 不碰那行，但**一旦 commit 该文件就会把那行一起提交**（台账 #70 同形：卷他席 WIP） |
| `AGENTS.md` | **脏**：29 增 / 14 删，横跨 **17–224 行** | 2026-10-19 01:03（17 小时前） | A4（加隔离纪律） | 🔴 **最高**：那批改动包含第 40、56 行，正是 A4 要加纪律的第一部分 |

### 7.3 因此原顺序作废

原建议「C → A → B」**是错的**：C 的第一步就踩在脏文件上，且 C 的 commit 会卷走别人的 8080→8099 修复。

**修正后的顺序**：

1. **A2 + V7 先做**（`runtime_paths.py` 与测试文件都干净，零碰撞）
2. **C 与 A4 后做**——但**前置条件是**那两个文件的陈旧 WIP 已由你处置（提交、丢弃、或明确授权我一起提交）
3. **B 最后做**（新增文件为主，只在收尾时碰 `AGENTS.md`）

### 7.4 每步的落盘纪律（写进实施计划，不靠自觉）

- 动前：`git status --porcelain -- <file>`；**脏就停**，先问，不猜
- 只允许 **`edit` 定向替换**，**禁 `write` 整文件覆盖**（会抹掉别人的改动）
- commit 前：`git diff -- <file>` 逐行确认**只含自己的改动**
- 若必须与他席改动同文件：先 `git add -p` 只暂存自己的 hunk，或先把他的改动 `stash` 起来
- **禁** `git add -A` / `git add .` / `commit -a`

---

## 八、待你确认

1. 本规格是否可作为实施依据？
2. 修正后的顺序 **A2+V7（干净，先做）→ 你处置两个脏文件 → C+A4 → B**，是否同意？
3. `AGENTS.md` 那 43 行、`root_hygiene_census.py` 那 1 行，是你之前的改动吗？要「一起提交」「先单独提交」还是「我先避开」？
4. 认领 TTL 默认 120 分钟，是否合适？
5. A2 会让现有 3 个 worktree 立刻 fail-closed（故意的）。接受「先红后 bootstrap」吗？

---

## 九、两项收尾的验收结论（2026-10-19 18:10，用户授权「没人动就收尾」）

### 9.1 授权前提的取证：确实没人在动

| 文件 | 取证时 mtime | 静默时长 |
|---|---|---|
| `AGENTS.md` | 10-19 01:03:20 | 1023.7 min（17.1 h） |
| `docs/agents/domain.md` | 10-19 00:57:30 | 1029.5 min（17.2 h） |
| `docs/agents/issue-tracker.md` / `triage-labels.md` | 10-19 00:57:18 | 1029.8 min（17.2 h） |

对照组：同刻正在飞的进程**只写 `webui/**`**（17:51 `dashboard.tsx`），与这三项零交集。
全程盯防结果见 9.4。

### 9.2 收尾①「端口 8080 → 8099」：**已完成**

- `README.md:70` 的 mermaid 节点已改 `webhook 8099`
- `COMMANDS.md` 经 grep 确认**无端口引用**，无需改
- 活跃叙述件复扫：只剩历史档案 `HANDOFF-V21R6-TESTING.md:10` 仍是 8080。**历史件按规则 7 不追改**（`docs/HANDBOOK.md` 与 `bot.py` 的是「8099（2026-10-17 前为 8080）」带史实标注，正确）

### 9.3 收尾②`docs/agents/` 三件：**验收自洽，可入库**

`domain.md` 明确写着 `GLOSSARY-MAP.md` 与子项目 `GLOSSARY.md`「**现在都不存在**，要等第一次真正写下词条时再建」——属**诚实缺席**，不是死链。三件互相之间无悬空引用。待入库（`?? docs/agents/`）。

### 9.4 收尾③`AGENTS.md` 体积：**原判定说「未完成」是错的，我撤回**

上一轮我按「软上限 30,000」判它「只减了 160 B＝任务未完成」。**对照机器门真身后这个判断不成立**：

```
tests/test_documentation_consistency.py:  _ENTRY_SIZE_CEILING = 32768
实跑：test_entry_docs_within_size_ceiling -> PASS
当前：32,565 B < 32,768 B（余 203 B）
```

- **机器门判的是 32,768**，不是 30,000
- 30,000 是 AGENTS.md 自述的「软上限＝到线即压」的**自我管理目标**，不是门的判据
- 所以该文件**现在是绿的**；「压到 30,000 以下」是自定的更高目标，不是我该替别人拍板的任务

⇒ **收尾③不成立，我不动 `AGENTS.md` 的正文**。它那 43 行改动可以按原样提交（前提是补上 9.5 那条）。

### 9.5 但发现一个**真**问题（上一轮没看清的）

`AGENTS.md` 新增的 `## Agent skills` 段引用了 `docs/agents/` 三份文件，而该目录**未入库**（`?? docs/agents/`）。
⇒ **单独提交 `AGENTS.md` 会造出三枚新死链。**
⇒ 提交顺序必须是：**先 `git add docs/agents/` 三件，再 `git add AGENTS.md`**，同一次提交。

### 9.6 全程盯防：他席确实有活动，但未进入我的域

| 时刻 | 文件 | 归属 |
|---|---|---|
| 18:04:06 | `plugins/bot_unified_runtime/control_plane/api/webui.py` | 他席（webui 域） |
| 18:06:54 | `docs/boards/_conventions.md` | 他席（新出现，取证时还是 10-17） |
| 18:07:41 | `README.md` | **本席**（端口改动） |

目标文件（`AGENTS.md`、`docs/agents/*`）全程 mtime **未变**，确认无人介入。

### 9.7 本席本次改了什么（逐项）

| 文件 | 动作 | 可回滚方式 |
|---|---|---|
| `README.md:70` | `8080` → `8099` 一处 | `git checkout -- README.md`（该文件此前干净） |
| `docs/superpowers/specs/2026-10-19-multi-agent-write-safety-design.md` | 新增 | 删文件 |
| `AGENTS.md` / `root_hygiene_census.py` | **一字未动** | — |

---

## 十、待确认（补充）

6. `docs/agents/` 三件 + `AGENTS.md` 那批改动，是否**现在一起提交**（顺序：先 docs/agents/，再 AGENTS.md）？
