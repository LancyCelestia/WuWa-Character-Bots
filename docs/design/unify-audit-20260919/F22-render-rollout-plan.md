# F22 · 渲染域施工方案（rollout plan）

> 席位：F22-b（渲染域施工方案代理）。快照时间：2026-09-19 17:16 +0800（`date` 实取值）。
> 性质：**只读取证 + 施工方案设计**。本文件不改工作树任何其他文件；未实施任何渲染域改动；本文所有"改动"均为**待授权方案**，非已完成事项。
> 前席事实引用：S8 席（`S8-render-webui.md`）、F5 席（`F5-card-render-tokens.md`）、F14 席（`F14-card-ia.md`）。本席仅复核其中两条关键事实（见 §一），其余直接引用不重复取证。

## 一、前置事实复核（两条必做）

### 1.1 `domains/` 是否入库 → **结论：整树未入库，渲染域没有任何 git 回滚面**

只读取证与输出（本席实跑）：

```
$ git ls-files plugins/bot_unified_runtime/domains/render | wc -l
0
$ git ls-files plugins/bot_unified_runtime/domains | wc -l
0
$ git log --oneline -1 -- plugins/bot_unified_runtime/domains
（无输出=该路径从未进入任何提交）
$ git status --porcelain plugins/bot_unified_runtime/domains
?? plugins/bot_unified_runtime/domains/
$ git ls-files --others --exclude-standard plugins/bot_unified_runtime/domains | wc -l
386
$ git log -1 --format="%h %ad" --date=iso
56d1461 2026-09-15 21:28:33 +0800
```

- `domains/render/` 实测 21 个文件、`domains/` 全域 386 个文件**全部未跟踪**；F5「HEAD 停在 09-15」**复核成立**（HEAD=56d1461，2026-09-15 21:28）。
- 对比面：旧垫片路径 `output/card_render/` 6 个文件 + `output/*.py` 共 14 个 `.py` **是 git 跟踪的**（`git ls-files plugins/bot_unified_runtime/output/card_render | wc -l` = 12）。
- **本席对 F5 口径的一处更正**：F5 说旧路径「15 张纯转发垫片」，本席实数 `find plugins/bot_unified_runtime/output -name '*.py'` = **14 个文件**（含 `output/__init__.py`），外加 1 个空目录 `output/card_render/templates/`。数量差 1 不影响「无第二真身」的定性结论。
- **推论（全案地基）**：真身在未跟踪区 → `git checkout --` / `git restore` 对渲染域**完全无效**；一旦施工改坏，唯一退路是**开工前自建的 `%TEMP%` 备份**。所以 §三的回滚设计一律以「逐件 sha256 清单 + 备份副本」为准，不以 git 为准。

### 1.2 `verify_hashes --check` 真值 + 渲染域入册/漏锁清单

```
$ PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 \
  ../ChatBot_Runtime/venv/Scripts/python.exe tests/verify_hashes.py --check
（无任何输出）EXITCODE=0
$ ls -l --time-style=long-iso tests/render_hashes.json
2026-09-19 16:55   ← 本席开席前 21 分钟刚被重录过
```

**0 漂移成立**（S8/F5 口径复核通过）。但注意 manifest 的 mtime 说明**在飞波仍在持续重录它**——任何声称「哈希门拦住了一次改动」的叙述都要以当次实跑为准，不能引用历史快照。

`tests/verify_hashes.py:34-60` 的 `TRACKED_FILES` 共 **19 项**（已逐行读源，非推断）：

| 归类 | 入册 | 说明 |
|---|---|---|
| 渲染域模板 | 7 张全入册（universal / affinity / finance / market / mermaid / song_candidates / error） | 全在 `domains/render/card_render/templates/` |
| 渲染域 py | 5 件：`theme_tokens.py`、`bridge.py`、`usage_cards.py`、`renderer.py`、`templates.py` | — |
| 他域 | `domains/ops/admin/debug.py`、`domains/chat_reply/capabilities/echo.py` | 4 张直拼卡中的两面在此 |
| 文档 | `docs/rendering-contract.md`、`DESIGN-SPEC.md`、`docs/design/` 三份 | — |

`domains/render/` 实测 21 文件，**入册 12 件、漏锁 9 件**。漏锁清单（按危险度排序）：

| 漏锁文件 | 为什么关键 |
|---|---|
| `card_render/mica_shell.py` | 壳层/装饰/根 token 单源（`--semantic-*` 等在此注入，见 `mica_shell.py:77-81,358-362`）；F5 的「10 份手抄壳渐变」的收敛终点；**且它是 gate08 豁免白名单的扫描源之一**（`test_v21r3_visual_gates.py:394`）——改它 = 同时改「出卡外观」和「门的判定基准」，却零哈希约束 |
| `render_backends.py` | playwright 常驻浏览器 + `page.route` CDN 拦截 + **动画钉帧**所在地；改它直接影响 PNG 字节等值判据，零哈希约束 |
| `card_render/models.py` | 卡片数据模型（`pc`/`card_title`/`sections` 字段的家） |
| `plain_text.py` | 出站打码链（密钥/路径 redact），安全面 |
| `reviewer.py` / `roleplay.py` / `bot_avatar.py` / `__init__.py`×2 | 审核、分段换行、头像、域装配 |

→ **S8 的「`render_hashes.json` 漏锁 `mica_shell.py`/`render_backends.py`」复核成立**，且本席把范围从 2 件扩到 9 件。

### 1.3 gate08 断言原文（§五的地基，逐字引用）

`tests/test_v21r3_visual_gates.py:560-572`：

```python
reason = _FORBIDDEN_HEX.get(normalized)
if reason and normalized not in _REGISTRY_HEXES:
    hits.append(...)
```

两处结构性无齿（本席实读，非引用他席）：
1. `_FORBIDDEN_HEX`（:363-372）只有 **8 个键**——不在黑名单内的**任意新散值恒绿**；
2. `_REGISTRY_HEXES`（:384-413）由 `dir(theme_tokens) + dir(mica_shell)` 扫**任意公开常量**动态派生——**往这两个模块任一公开常量里塞一个值就自动豁免**，且这些新值随即脱离黑名单；
3. 附加发现（本席）：文件头 :24 写着「豁免白名单见 `_HEX_WHITELIST`」，但 `grep -rn "_HEX_WHITELIST" tests/` **只有这一行命中、无任何定义**——注释指向一个不存在的显式白名单，评审者按注释找表会误判「有登记表」。
4. 活体违例复核成立：`usage_cards.py:255-257` 直写 `#2e9e6b`/`#b07d1a`/`#d54941`（三者正是 `SEMANTIC_SUCCESS/WARNING/DANGER` 登记值），本应写 `var(--semantic-*)`；因在册而照绿。

### 1.4 表外 hex 规模实测（§五「红线数估算」的输入，只读正则扫源）

扫描面 = 7 张模板 + 4 个直拼卡 builder 源文件（`echo.py`/`debug.py`/`usage_cards.py`/`templates.py`）的**全文源码**，登记集 = `theme_tokens.py` + `mica_shell.py` 全文出现的 hex：

- hex 字面量 **136 处 / 28 个唯一值**（其中 `universal_card.html` 独占 61 处）；
- 两模块内登记值 **31 个唯一值**；
- **表外（未登记）唯一值 21 个、命中 112 处**——含 `#000000 #23ade5 #4a5866 #8a8f98 #e4e6eb #e65100 #f0b429 #ff9800 #fff3e0 #d64545 #1a9e6c` 等。
- ⚠️ **口径诚实**：这是**源码全文**上界（含注释/docstring 里的举例值，且 Python 注释会命中），**不等于** gate 实际扫的「渲染后 HTML + 模板全分支文本」。真实红线数须在实施时用 `_surface_texts()` 跑一次才定得准 → 本文一律标「估算 112 处 / 21 唯一，上界」。

### 1.5 PNG 基线位置（复核 S8「只活在 %TEMP%」）

`scripts/render_card_samples.py:1057` = `Path(tempfile.gettempdir())/"shorekeeper-samples"/"baseline-20260918"`；:39 声明「**自 baseline-20260919-paused 起 PNG 字节等值为全部面的验收判据**」。→ 成立：**验收判据的最高级（字节等值）所依赖的基线，在工作区之外、无哈希、无备份、清理 %TEMP% 即永久失去**。

## 二、施工 DAG 与唯一顺序

**唯一顺序，不给备选。** 依赖是硬理由而非习惯：**锁先于改、基线先于动渲染、门先于收敛**——三句话就是这张表的排序原则。

| # | 步骤 | 依赖 | 改动文件数 | 为什么卡在这个位置 |
|---|---|---|---|---|
| S0 | 冻结取证 + 逐件 sha256 备份清单落 `%TEMP%`（不改任何文件） | — | 0 | 无 git 回滚面（§1.1），这一步是后面每一步的退路；开工前必须做，不是每步前做一次 |
| S1 | **渲染域入库提交**（`domains/` 386 件，或至少 `domains/render/` 21 件 + 4 个门文件） | 用户授权 D1 | 新增跟踪 | **在没有第二个回滚面之前，S2 之后任何一步都是单向门**；排在一切改动之前 |
| S2 | **补锁**：`verify_hashes.TRACKED_FILES` 追加 §1.2 的 9 件漏锁文件，随后一次 `--write` | S1 | 2（脚本 + manifest） | ①「先补锁再改字面量」的**唯一插入点**就在这里：不补锁，S5-S8 任何一次改动都无法区分本席与他席；②`mica_shell.py` 是 gate08 豁免扫描源，不锁它就等于"门自己可以偷改门的基准" |
| S3 | **PNG 基线搬家入库** + `render_card_samples.py` 缺省路径改指仓内 + 基线自身入哈希清单 | S2 | 2 + N 张 PNG | 基线不入库，S6（壳渐变单源）改完就无法证明"像素没漂"；判据必须在被它考核之前先固化 |
| S4 | **gate08 换骨（牙齿 A）**：建 `theme_tokens.COLOR_REGISTRY` 显式登记表 + 现存 21 未登记值以 `LEGACY_*` 冻结类入表 → 断言改「面上 hex ⊆ 登记表」 | S2 | 3（theme_tokens / 门 / 契约文档） | 值域门必须先立：**这一步之后，新散值不再可能悄悄进面**，S5-S8 才是"收敛存量"而不是"边收边漏" |
| S5 | **活体违例最小闭环（牙齿 B 试点）**：`usage_cards.py:255-257` 三行改 `var(--semantic-*)`；同文件加"登记值禁直写"的最小断言 | S4 | 2 | 最便宜的一条真红→真绿（3 行），用来验证 B 门不会误伤，再推广 |
| S6 | **壳层渐变 10 份手抄 → `mica_shell` 单源**（F5 口径） | S3,S4 | 7-11 | 影响 PNG 字节的**最大单步**，必须同时晚于"基线入库"与"值域门立起"；早一步会失去像素证据，晚一步会与 S7 同面冲突 |
| S7 | **根容器范式统一**（F14 P1-1）：`render_shell()` 从 0 消费改为唯一入口 + `docs/rendering-contract.md` §五第 2 条「`.shell card` 或 `.card`」二义**收口为一句** + `pc`/`card_title`/`sections` 字段命名锁 | S6 | 9-13 | 结构改造晚于样式单源：先让壳只有一份，再让根只有一种范式，否则等于对着 12 份手写文档层各改一遍 |
| S8 | **宽度登记表消费**（F14 P1-5）：4 卡字面量宽度改取 `CARD_SHELL_WIDTHS`，测试侧撤字面量 | S7 | 5-6 | 纯机械替换，晚于结构统一才不会改到一半又搬家 |
| S9 | **残账收口**：23 个未消费 token 门 warn→fail、契约 4 条纸面条款补断言、13 项豁免复审、帮助卡反向正则解析（F14 P1-3）拆除 | S4-S8 | 4-7 | 全是"把软约束变硬"的收尾，任何一条提前都会把尚未收敛的面永久钉死在错误形态上 |

- **串行原因**：S2/S3/S4 是同一批测试文件的连续改动，且 `verify_hashes.py` + `render_hashes.json` 只有一份——并行必竞态（F5 已实证 manifest 被在飞波重录两次）。
- **可并行**（与 S5-S9 互不冲突，但须先与 S2 串行完成）：S10 垫片退役续跑、S11 `render_card_png` 导入路径收敛（F14 P1-6）——这两条**牵动他席文件**，本方案只登记不排入本轮，见 §七「不该动清单」。
- **禁止的排序**：任何"先把散值字面量清一遍、再回头补门"的走法（= 边收边漏 + 无法自证没改坏），本席明确否掉。

## 三、逐步回滚点

两类文件面，退法根本不同——**这一节的存在理由就是 §1.1 那条"未跟踪"**。

### 3.1 未跟踪件（`domains/**` 真身，S2-S9 主战场）

git 帮不上忙，唯一退路是自建副本。参照 RET 系列先例（`%TEMP%/v21r4-ret3-backup`、`chatbot-stray-data-20260915-*`）：

1. **开工一次（S0）**：`domains/render/` 全 21 件 + `tests/{test_rendering_contract,test_mica_builders_contract,test_v21r3_visual_gates,verify_hashes}.py` + `tests/render_hashes.json` + `docs/rendering-contract.md` → `%TEMP%/f22-render-backup-<日期>/` 原样复制（保目录结构）。
2. **逐件 sha256 清单**：同目录落 `manifest.sha256`（路径 + LF 归一哈希，口径与 `verify_hashes.sha256_of` 一致，避免 CRLF 假报）。
3. **每步再打点（S3 基线入库后、S6/S7 两个大步前）**：只复制该步将触碰的文件到 `<日期>/step-S6/pre/`，形成**步内回滚点**——回滚只还原那一步，不吞掉前序已验证的成果。
4. **回滚动作**：`cp <备份>/<path> <原路径>` → 立刻跑该步的门 + `verify_hashes --check`，两边都绿才算还原干净（哈希门会指出是否有文件漏还原）。
5. **铁律**：还原前把**当前态**再存一份 `post-failed/`，失败现场是取证材料，不许直接覆盖丢失。

### 3.2 已跟踪件（旧垫片 `output/**`、`docs/**`、`tests/**`、`scripts/render_card_samples.py`）

- 退回 = `git restore -- <单文件>`（**逐文件，禁 `-A`/`.`**，纪律第 4 条），或 `git diff > %TEMP%\f22-step.patch` 先落盘再退。
- ⚠️ **共享工作树风险**：`tests/render_hashes.json`、`docs/rendering-contract.md`、`DESIGN-SPEC.md` 正被在飞波改动（manifest mtime 16:55 即证据）。**`git restore` 会连带吞掉他席未提交改动**——所以这三个文件的回滚**禁用 git restore**，一律用 §3.1 的副本还原，并在还原前 `git diff <file>` 确认里面只有自己。

### 3.3 每步的改动面与回滚粒度

| 步 | 改动文件数 | 影响面（会被什么打到） | 回滚粒度 |
|---|---|---|---|
| S1 | 0 改，仅新增跟踪 | 无（提交本身不改内容） | `git reset --soft HEAD~1`（撤销提交、保留工作树）；**须用户明确授权才做** |
| S2 | 2（脚本 + manifest） | 哈希门基线整表变化；全量测试的 `test_cross_validation_gates` | 单文件还原 manifest + 脚本 |
| S3 | 2 + N 张 PNG（新增） | 样张脚本、`runtime-layout` 门（新目录是否被许可） | 删新增目录 + 还原 2 文件 |
| S4 | 3 | **11 面 × gate08 全量**（最可能大面积红，见 §4） | 还原 3 文件 + `--check` 复平 |
| S5 | 2 | usage 卡像素（PNG 字节判据）、gate08/新 B 门 | 还原 2 文件，重跑 usage 面 |
| S6 | 7-11 | 全部 11 面观感 + PNG 字节 + `test_rendering_contract` 渐变逐字断言 | 步内打点还原（§3.1-3） |
| S7 | 9-13 | 截图选择器契约（`.card` 根类）、8 方导入、E01/E03 样张帧 | 步内打点还原；务必与 S6 分点，别合并 |
| S8 | 5-6 | gate06 宽度门 + 硬编码宽度断言 | 单文件还原 |
| S9 | 4-7 | 未消费 token 门（warn→fail 一次性放开 23 项）、契约文档哈希 | 逐条还原（S9 内部四条彼此独立，允许只回滚其中一条） |

## 四、门策略（每步后哪些门红 / 谁重录哈希）

### 4.1 本域门清单（实存文件，均已在 `tests/`）

主契约门：`test_rendering_contract.py`、`test_mica_builders_contract.py`、`test_v21r3_visual_gates.py`（九门 × 11 面）、`test_template_visual_audit.py`、`test_mica_shell.py`、`test_universal_card_visual.py`、`test_e02_stardust.py`、`test_e03_typography.py`。
后端/样张门：`test_render_backends.py`、`test_render_card_samples.py`、`test_render_image_cache.py`、`test_render_pool_hygiene.py`、`test_render_wait_budget.py`、`test_render_launch_backoff.py`、`test_render_phase2_env_keys.py`、`test_mermaid_reply_render.py`。
横向门：`test_verify_hashes_coverage.py`、`test_cross_validation_gates.py`（subprocess 跑 `--check`）、`test_doc_sync_gates.py`、`test_copy_redline_gate.py`、`test_runtime_feature_gate.py`、`test_webui_constitution.py`（**他席，本域不得改**）。

### 4.2 逐步红/绿预判

| 步 | 会变红（预期、必须当场处理） | 不会红但**必须复跑** | 需重录哈希 |
|---|---|---|---|
| S2 | **`test_verify_hashes_coverage.py:92` 硬编码 `== 19` 必红**（本席实读发现的隐藏锁）；`test_cross_validation_gates` 在 `--write` 前必红（9 项 DRIFT/NEW） | 全量套件、`dev.ps1 -Task lint/typecheck/runtime-layout` | **是**（清单扩容本身即一次有意识重录） |
| S3 | `test_render_card_samples.py`（缺省路径改变）、`runtime-layout`（仓内新增 PNG 目录是否被许可——若被拦，说明要先把目录写进白名单，这是**规则改动不是 bug**） | 样张 19 面重跑 | 基线 PNG 首次登记 → 是 |
| S4 | **gate08 全线**：按 §1.4 估算，21 个未登记唯一值若不以 `LEGACY_*` 冻结类先入表，11 面里最多 112 处命中同时转红；`test_rendering_contract`/`test_template_visual_audit` 的既有豁免口径与本门交叉处可能二次红 | 九门全套 | 否（门文件不在清单内 → 见 §4.4 缺口） |
| S5 | 新 B 门（登记值禁直写）在 usage 面首次红→绿；`test_render_card_samples`/PNG 字节判据若语义色渲染有差（`color-mix` 内嵌 hex 换 var 后需确认浏览器解析一致） | contract 门 | `usage_cards.py` 在册 → **是** |
| S6 | `test_mica_shell.py`、渐变逐字符断言、E01/E03 帧、PNG 字节等值（**手抄副本消灭 = 字节必变**，需要用户裁定"基线重刷"而不是悄悄改基线） | 九门、契约 | **是（本次最大一次）** |
| S7 | 截图选择器契约（根类变化即全线红）、`test_rendering_contract` 模板结构断言、8 方旧路径导入面 | `runtime-layout` | 是（模板 + builder） |
| S8 | gate06 + 测试侧硬编码宽度断言 | 契约 | 视是否触模板而定 |
| S9 | warn→fail 一放开，**23 个未消费 token** 立即记红；契约 4 条补断言首跑必红 | 全量 | 否 |

### 4.3 重录权（决策点，交用户，本席不预设）

`--write` 是**唯一能把"改了东西"洗成"计划内"的动作**，所以现在它被在飞波随手执行（manifest mtime 16:55）。建议裁定口径：**渲染域哈希只在 S2/S3/S5/S6/S7 五个显式检查点重录，每次重录须在席位日志留下"触发文件 + 该步可复跑门命令 + 输出"三件套**；其余时点 `--write` 视为越权。是否采纳、由谁执行（本席 / 主会话 / 收尾席）→ **D2**。

### 4.4 门自身不在锁内（结构性缺口，必须与 S2 同批处理）

`tests/test_v21r3_visual_gates.py`、`test_rendering_contract.py`、`test_mica_builders_contract.py` **都不在 `TRACKED_FILES`**：任何人改门（放宽断言、往 `mica_shell` 塞值扩豁免集）都不触发哈希门，`verify_hashes` 只锁产出物不锁裁判。→ S2 至少追加 gate08 的判定基准源（`mica_shell.py` 已在 §1.2 漏锁表首行）；**三个门测试文件是否入库锁**（锁了以后并行修门会频繁互撞红）→ 决策点 **D3**。

### 4.5 并发危险动作（登记，不改）

`test_verify_hashes_coverage.py:69-78` 会**临时改写 `domains/render/templates.py` 再字节还原**。它选该文件的理由是"无在飞域"——本方案 S5-S9 一旦触碰它，演练窗口就可能与他席写操作互踩。建议 S2 时把演练目标改为一次性临时副本（一行改动），或规定渲染域施工期间不跑此文件。

## 五、黑名单门根治（禁表外 hex 门）

**编号更正（本席实读）**：「禁表外 hex」是 **`test_gate08_forbidden_hex`（对应裁决基线第 9 条）**；`test_gate09_glass_tiers` 是白玻璃档位门，另一回事。S8 简报里两个编号并写容易误伤，施工以本文件口径为准。根治要同时改 gate08 与 gate09 的同类病（两门都靠 `dir(module)` 动态派生豁免），但**主刀在 gate08**。

### 5.1 现状三条病（§1.3 已给断言原文）

B1 黑名单只 8 值 → 新散值恒绿；B2 豁免集由 `dir(theme_tokens)+dir(mica_shell)` 扫**全部公开常量**（含 `PLATFORM_THEMES` 17 平台 × 派生 wash、`SURFACE_TINTS`、`OVERLAY_SCRIMS`）→ 登记表面就是一个不断膨胀的自动豁免池，"往模块里塞个常量"即破门；B3 文档指向不存在的 `_HEX_WHITELIST`（注释与实现漂移）。

### 5.2 数据源：用哪张表

新建**显式枚举**登记表，落在 `theme_tokens.py`（它是全渲染域唯一既有单源、且已在哈希清单内）：

```python
COLOR_REGISTRY: dict[str, str] = {      # 名字 → 规范化 hex，唯一裁判依据
    "accent-brand": BRAND_ACCENT, "text-secondary": TEXT_SECONDARY,
    "semantic-danger": SEMANTIC_DANGER, "semantic-success": SEMANTIC_SUCCESS,
    "semantic-warning": SEMANTIC_WARNING, "score-hot": SCORE_HOT, "score-cold": SCORE_COLD,
    ... # 中立灰阶 NEUTRAL_* 与平台 accent 逐个点名登记
}
```
- **派生值一律不进表**：wash/mist/pastel 由 `derive_wash_tokens()` 运行时算出，只能通过 `var(--wash-*)` 抵达面，**不允许作为字面量出现在任何面**——这条直接砍掉 B2 的自动豁免池（现有 31 唯一登记值里绝大多数正是派生 wash，它们不该获得字面量许可）。
- 平台官方色继续走 `theme_tokens._PLATFORM_ACCENTS`（现有登记入口，契约 §五第 8 条已写明），登记后即进 `COLOR_REGISTRY`，不另立第二表。

### 5.3 两枚牙齿怎么写（核心：**豁免与白名单不可互相抵消**）

- **牙齿 A（值域门，无豁免通道）**：`_HEX_RE` 扫 `_surface_texts(sid)`，规范化后 `∉ COLOR_REGISTRY.values()` → 红。**豁免表永远不能作用于 A**；`#fff`/`#000` 这类确需直写的，作为表的成员登记（`"white": "#ffffff"`, `"black": "#000000"`），而不是当豁免。这样"登记"只赋予**语义名 + var 引用权**，不赋予"面任意位置写散值"的许可。
- **牙齿 B（引用门，唯一有豁免表）**：面上的字面量若 ∈ A 表且该 token 已有 CSS var（`mica_shell.py:77-81` 那批 `--semantic-*`/`--score-*`）→ 要求写成 `var(--...)`；豁免表 `_DIRECT_HEX_ALLOW: dict[(面, 属性名), 理由]` **逐面逐属性点名 + 必填 reason 字符串**（沿用 GLASS3 席在 :585-588 的"裁定登记"写法，那是好先例）。
- **两门合起来的净效果**：新散值进不来（A），进来了也不能偷懒直写（B）。现状是 A 恒绿 + B 不存在。
- 配套修：删除/更正 :24 那行指向 `_HEX_WHITELIST` 的注释；`_FORBIDDEN_HEX` 8 值降级为"回归哨兵"保留（A 已覆盖，但保留它可对"LEGACY 值复活"给出更可读的报错）。

### 5.4 现存 21 个未登记唯一值（112 处，上界口径）怎么归类入库

| 类 | 判据 | 处置 |
|---|---|---|
| C1 语义同色异值 | 与 `SEMANTIC_*` 视觉接近（`#d64545` vs `#d54941`、`#1a9e6c` vs `#2e9e6b`） | 改消费 token（走 B 门路径），旧值**不入库**，保留黑名单哨兵 |
| C2 中性灰阶/边底色 | `#4a5866 #8a8f98 #e4e6eb #e6e8ee #eef0f9 #f1f2f3 #f7f4fa` | 新增 `NEUTRAL_*` 显式登记（约 7 个），随后统一改 `var(--neutral-*)` |
| C3 疑似 Material 遗留橙黄族 | `#ff9800 #e65100 #f0b429 #b77900 #fff3e0 #f2b8b5` | 逐处判"是否真被消费"：在用→登记；死值→删除；不确定→**先登记冻结、另立台账**，禁止猜 |
| C4 平台/角色专色 | `#23ade5` 类 | 归 `_PLATFORM_ACCENTS` 或语义 token，不新建表 |
| C5 纯白纯黑 | `#fff #000000` | 进表为 `white/black`，允许直写（A 覆盖、B 视属性放行） |
| C6 注释与 docstring 举例值 | 源码全文扫会命中，`_surface_texts` 不会 | **不处置**，但意味着红线真值必须用门自己的扫描器测（§5.5），不许拿源码 grep 数当基线 |

### 5.5 改门后红线数估算方法（三步，全离线）

1. **影子跑**：在门实现里临时把判定集从 `_REGISTRY_HEXES` 换成新 `COLOR_REGISTRY`，**只打印不 assert**，跑 `pytest tests/test_v21r3_visual_gates.py -k forbidden_hex -p no:cacheprovider` → 得逐面命中矩阵（真值，非 grep 上界）。
2. 按 §5.4 六类逐值归类，`红线数 = 命中总数 − C6 误伤 − 已判死值`。
3. 落地节奏：先只让**新值**红（A 门生效于"登记表外"，C2/C3 存量一次性冻结进表），S5-S8 每收一处就从冻结名单里划掉一个，**名单只许缩短**（用一条断言 `len(FROZEN) <= 常数` 锁死棘轮），防止"为消红反向扩表"。
4. 参考量级（**估算，非实测**）：上界 112 处 / 21 唯一；其中 `universal_card.html` 一面对 61 处，是最大单点。

## 六、最小可信收口包（3–5 条）

目标只有一个：**堵住"看起来绿但其实没锁"的假绿**，不追求把渲染域改好。取 §二的 S1-S5，共 5 条：

1. **`domains/render/` 入库（S1）** —— 从"零回滚面"变成"有回滚面"。这是所有其他安全性的前提，且代价最低（0 行代码改动）。
2. **`render_hashes.json` 补 9 件漏锁（S2）**，重点 `mica_shell.py` + `render_backends.py`；同批把 `test_verify_hashes_coverage.py:92` 的 `== 19` 改成从表推导；建议同时把三个门测试文件纳入锁（D3）。→ 治"改壳层/改截图后端不触发哈希门"。
3. **PNG 基线从 `%TEMP%` 搬家入库（S3）**：`baseline-20260919-paused` 的 19 张 + `manifest.sha256` 进仓，`render_card_samples.py` 缺省路径改指仓内。→ 治"字节等值判据依赖一个随时会消失的东西"。
4. **gate08 换牙（S4，只上牙齿 A + 存量冻结名单棘轮）**：新散值即刻不可行；旧 21 值冻结、名单只许缩短。→ 治"任意新散值恒绿 + 登记即豁免"。
5. **usage 卡活体违例改 var（S5）**：3 行，顺带把 `#d64545/#1a9e6c` 之外的"登记值直写"反模式立一条最小断言。→ 让第 4 条不是一纸空文，有真实红→绿样本。

**明确留在后续波次**：壳渐变 10 份单源（S6）、根容器范式统一（S7）、宽度消费（S8）、warn→fail 与纸面条款补断言（S9）、13 项豁免复审、契约 4 条纯纸面。理由：它们改像素、改结构，必须在前 5 条的锁与基线生效后才做得安全。

## 七、决策点清单 + 本轮不该动清单

### 7.1 需用户点头才动（7 条，按阻塞程度排序）

| ID | 决策点 | 本席推荐 | 不点头的后果 |
|---|---|---|---|
| **D1** | **提交授权范围是否扩到 `domains/`**（现仅授权 `webui/` 43 件）。实测：`domains/` 未跟踪 386 件 / **7.3M**，含 `domains/weather/assets/qx.json`（362,774 字节，历史被误清三次） | 至少先提交 `domains/render/` 21 件 + 4 个门文件；整树提交更好（顺带给 qx.json 一个 git 层面的复活能力） | S1 掉队 → 之后每一步只有 `%TEMP%` 一条退路，且 D5 的基线入库也无从谈起 |
| **D2** | **哈希重录权（`--write`）归谁**、允许在哪些检查点执行（§4.3 建议 S2/S3/S5/S6/S7 五点 + 三件套留痕） | 归主会话或收尾席单点执行，施工席只报"该重录了" | 现状=在飞波随手重录（manifest 16:55 mtime 为证），哈希门退化为"提醒"而非"门" |
| **D3** | **三个门测试文件是否纳入哈希锁**（`test_v21r3_visual_gates.py` / `test_rendering_contract.py` / `test_mica_builders_contract.py`，现均不在清单） | 纳入 `test_v21r3_visual_gates.py` 一件（gate08/09 判定基准所在，最容易被"放宽"）；另两件暂不加以免并行修门互撞 | 裁判可被无声修改，§五白名单门做完也能被下一次"调门"退回黑名单 |
| **D4** | **gate08 换牙节奏**：一次性全红逼平 vs 存量冻结 + 棘轮（§5.5 步骤 3） | 冻结+棘轮（红线数未实测，一次性全红可能 100+ 处同时炸，反而诱发"为消红扩表"） | 若选一次性，须先接受"渲染域多日全红、其他席无法合流" |
| **D5** | **PNG 基线入库形态**：`baseline-20260919-paused` 实测 **28M**（19 张 PNG + 每张 `.sha256` 旁车 + `.payload.json`；PNG/旁车占比未实测——`%TEMP%` 细粒度读取被权限拦） | **不提交二进制**：把 19 个 `.sha256` 旁车 + `.payload.json`（KB 量级）入仓做"可复现指纹"，PNG 本体留 `%TEMP%` 但由脚本强制校验；若用户要像素级留档再谈 28M 入库 | 只把"图会丢"变成"图会胖仓库"，二选一都得用户裁 |
| **D6** | **S6/S7 是否本轮做**（改像素/改结构，会强制重刷基线） | 本轮不做，只交最小收口包（§六） | 早做等于在没有可信基线的情况下宣布"视觉没变" |
| **D7** | **`runtime-layout` 门是否允许仓内新增基线目录 / `tests/` 新增资产** | 需先确认门白名单，别把施工改成"违反树卫生" | S3 会被自己的卫生门拦下 |

### 7.2 本轮不该动（附理由）

| 不该动 | 理由 |
|---|---|
| `render_backends.py` 的**动画钉帧实现** | 它产出的正是 `baseline-20260919-paused` 这一判据本身；改钉帧 = 改拍照方式 = 全部 PNG 必变，而基线尚未入库（D5 未决）——先动它就是自己抽掉自己脚下的地板 |
| PNG 基线本体与 `--write` | 本席禁执行；且 D2 未决前任何重录都是越权 |
| **旧路径垫片退役**（`output/**` 14 个 `.py` + 1 空目录） | 牵动他席（v21r4 RET2b/RET3/RWC 系列正在做，且有在飞断点）；且这些文件是 git 跟踪的、被 8 方导入，动一处即全树红。本席只登记其"git 跟踪 vs 真身未跟踪"的回滚不对称 |
| **mermaid 特例 / `page.route` CDN 本地拦截** | 牵 playwright 与 `ChatBot_Runtime/card_render_assets/mermaid/`（Runtime 不扫描不修改），离线环境不可验证，任何"顺手收一下"都是拿不到的证据 |
| **帮助卡反向正则解析**（F14 P1-3） | 拆除要同时动 `echo.py`（在飞他席 + 已在哈希清单 16:55 刚被重录）——本轮改它必与他席撞车 |
| `pc`/`card_title`/`sections` **字段改名** | 改名会击穿 `test_mica_builders_contract` + 4 直拼卡 + 6 能力入参（F14：6 种形态），属新 ABI 设计不是清理；本轮只做"命名锁"（断言现有字段名不改），不做改名 |
| `domains/weather/assets/qx.json`、`personas/`、`.env`、`ChatBot_Runtime/`、`ChatBot_Archive/`、源码树 `data/` | 纪律与铁律 6/2/3；qx.json 历史上被误清三次 |
| `webui/**`、`tests/test_webui_constitution.py` | 主会话与他席正在改（本轮唯一明确允许主会话改的前端面） |

---

### 附：本席卫生声明

本席全程只读：未执行 `--write`、未跑 playwright/截图/样张、**未跑任何 pytest**、未做任何 git 写操作、未派子代理、未触碰进程。收尾自检（实跑输出）：

- `find plugins -name "__pycache__" -newermt "2026-09-19 17:10"` → **空**；本席未产生任何 `.pyc`（直跑 python 全程带 `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1` + venv 解释器）。
- 源码树根**既存** `.mypy_cache`(12:47)、`.pytest_cache`(12:37)、`.ruff_cache`(12:30) 与 `.tmp-test/`，mtime 均早于/独立于本席开工时刻（17:16），**非本席造成**，本席不删（并发席位正在用）；`.ruff_cache/0.16.4/*` 与 `.tmp-test/` 在 17:24 被改写，同期被改的还有 `config.py`/`.env.example`/`docs/config-catalog-full.md`/`tests/test_webui_stats.py` 等——**这就是 §3.2 所述"工作树正被多席热改"的现场证据**。本席唯一写入 = 本文件。
- `ls data` → `No such file or directory`（源码树无 `data/` 残留）；收工复跑 `verify_hashes --check` → **EXIT=0，仍 0 漂移**。
- 本文所有改动均为**待授权方案**，本席未实施任何一项，不使用"已修复"措辞；§1.4 的 112 处 / 21 唯一与 §5.4 类内数量是**源码全文正则扫描的估算上界**，非门实测真值，须在 S4 前用 §5.5 影子跑取真值。
