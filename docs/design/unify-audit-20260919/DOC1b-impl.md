# DOC1b-impl · F24 文档订正执行台账（DOC1-b 席，接替疑似静默死亡的前 DOC1 席）

> 开工时刻：2026-09-20 02:2x（`date` 实跑 Sun Sep 20 02:24 2026）。
> 任务本体：按 `docs/design/unify-audit-20260919/F24-doc-reconciliation.md` §四逐条执行文档订正。
> 纪律：禁 git 写；禁 `--write` 系命令（verify_hashes/doc_sync/command_catalog 一律 `--check`）；
> 禁改 `webui/**`、`domains/**`、`tests/**`、`.env`、`personas/**`、Runtime/Archive、`qx.json`；
> 直跑 python 带 `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1`。
> **本台账是本席唯一进度载体，分段落盘（每 3–5 条一更）。**

---

## STEP 0 · 现状核实表（条目 × 已改/未改/让路）

**判定方法**：逐文件 `git status --porcelain` + mtime + 逐条 grep F24 §四的 before 锚点串与 after 特征串
（特征串如「断言位置」「豁免登记与待补门」「两级/三级不对称现状」等在现树中全部零命中）。
**结论前置**：前 DOC1 席**未改动任何目标文件**——所有 before 锚点原样在位、所有 after 特征串零命中、
其台账 `DOC1-impl.md` 不存在（`docs/design/unify-audit-20260919/` 下无 DOC1 系文件）。
各文件虽显 M（工作树脏），但 diff 归属为 0918/0919 渲染收口波与 09-20 在飞会话（见「热脸判定」），非 DOC1。

**总统计**：F24 §四点名可执行条目 **42** 条 = 已改 **0** ｜ 本席执行 **25** ｜ 让路 **17**（热脸，登记交接）。

| 组 | F24 条目 | 目标文件 | 条数 | 现状判定 | 依据 |
|---|---|---|---|---|---|
| G1 | 4.1-1…4.1-6 | AGENTS.md | 6 | **让路（热脸）** | mtime 09-20 02:22（开工前 2 分钟）；G2/v21r5 收口会话正在连续提交（02:16–02:24 四笔）且「登记册/AGENTS/HANDBOOK 收口席」在排；6 条 before 锚点全部在位（:24/:32/:91/:108/:126/第五部分） |
| G2 | 4.2-1…4.2-7 | DESIGN-SPEC.md | 7 | **未改→本席执行** | mtime 09-19 00:51（16h 冷静）；:15/:21/:24/:28/:33/:37/:44/:45/:47 before 全在位，after 特征零命中 |
| G3 | 4.3-1…4.3-15 | docs/rendering-contract.md | 15 | **未改→本席执行** | mtime 09-19 00:49；L3/L6/:19/:35/:63/:65/:66/:67/:68/:73/:77/:78/:81/:82 before 全在位；无 §八、无「断言位置」列 |
| G4 | 4.4-1…4.4-6 | docs/HANDBOOK.md | 6 | **让路（热脸）** | mtime 09-20 02:19；HEAD 差 +362 行（别会话在写）；§6.3「单柔光阴影」现居 :258、「9 页 9 PASS 双轮」:2218、「预算内」:2217、「版式宪法机器门常驻」:2219、PNG 判据 :2213、机器册转抄 :2259 全在位 |
| G5 | 4.5-1…4.5-3 | docs/acceptance-manual.md | 3 | **让路（热脸）** | mtime 09-20 02:19；G2 波 T76 席明令「acceptance-manual §6.6.11 改写」在飞；「53 例」:391/:405、「六项导航」:406、「12/14/16/18/20px+圆角命中=0」:429 在位 |
| G6 | 4.6-1 | docs/design/fstring-card-dom-spec.md | 1(+4 坐标) | **未改→本席执行** | mtime 09-18 20:48；状态行「本规格未实施」在位 |
| G7 | 4.6-2 | docs/design/render-pipeline-optimization-spec.md | 1 | **未改→本席执行** | mtime 09-13（对 HEAD 零差）；状态行「未实施」在位；两键 `bot_render_max_concurrency/_wait_budget_ms` 实测在位（config.py:675-676，F24 写 :629-630 已漂） |
| G8 | 4.6-3 | docs/design/visual-effects-catalog.md | 1(3 处) | **未改→本席执行** | mtime 09-18 20:48；「未实施」「七条铁律」「6 模板」在位；7 模板 `Math.random` 实测 0（V4 判词今日仍真） |
| G9 | 4.6-4 | docs/README.md | 2 | **让路（热脸）** | mtime 09-20 02:19；:96/:97/:98 三行「未实施，待用户裁决」在位（注意 :98 visual-effects 行与 4.6-3 同源联动，交接时一并处理） |

**§4.7 措辞统一表**：8 行均为指向 4.1/4.2/4.3 的索引行，无独立施工面——随 G2/G3 落实即闭合，G1 行随 AGENTS 让路。
**§五 豁免册**：随 4.3-15 粘入契约 §八（E-1…E-14 + D-1…D-8）。

## 代码事实复核（诚实优先：订正稿 vs 现树）

F24 写于 09-19 17:05–17:4x；此后 G2 波次（T52–T70，含 echo.py 重提交 e0b0722、T61/T68）又动过树。
本席对全部 after 文字引用的代码事实逐条重验（09-20 02:2x 实跑）：

| 事实 | F24 出处 | 本席复验结果 |
|---|---|---|
| 模板 7 张 / 垫片 templates/ 空 | §〇 | ✅ `ls …/domains/render/card_render/templates/*.html`=7；`output/card_render/templates/` 0 文件 |
| 直拼卡四处真身路径+函数名 | 4.3-1 | ✅ `domains/chat_reply/capabilities/echo.py`(`_help_mica_html`)、`domains/ops/admin/debug.py:717 _llm_setup_mica_html`、`domains/render/card_render/usage_cards.py`、`domains/render/templates.py` |
| echo 12.5px/14.5px 现势在位 | D-S9/C-R16/4.3-9 | ✅ **行号漂移 :3392→:3399、:3409→:3416**（echo.py 被 T68/e0b0722 动过），值在位；color-mix 12% 同在 :3416 |
| usage `.status.*` 直写 #2e9e6b/#b07d1a/#d54941 | D-S8/4.3-7 | ✅ **行号漂 :255-257→:272 区段**，直写在位 |
| 宽度四处字面量 940/880/900/640 | D-S11/4.3-10 | ✅ echo:3376=940、debug:776=880、usage:250=900、templates.py:76=640 |
| `_DEFAULT_SHELL_WIDTH_PX=880` 未登记 | F14-5/4.3-10 | ✅ mica_shell.py:87 |
| 7 模板 `--text-secondary:#576272` 手抄 | D-S10/4.3-8 | ✅ 7/7 在位 |
| 145deg 手抄副本 | D-S13/4.2-5 | ⚠️ **计数口径修正**：模板侧 10 份（universal 4 + 其余 6 卡各 1）+ 生成器 mica_shell 1 份 = **11 份**；F24 §四 4.2-5 after 文字「模板侧 11 份+生成器 1 份」=12 为笔误，本席按实数 10+1=11 写（其 §一 D-S13 原文「7 份+universal 内 3 份+生成器 1 份=11」与实数一致） |
| mica_shell 内 GLASS_EDGE 同值手抄 | S8-03 | ✅ mica_shell.py:493（F24 写 :393 已漂） |
| universal .footer-colored 混色档 | D-S4/4.2-1 | ✅ :1093（accent 8%+wash-2 7% 段，28% 出现 2 处在他段）——「7-10% 外功能变体」例证仍真 |
| mermaid/universal 手写 reduced-motion 关停 | C-R23/4.3-14 | ✅ mermaid :121 + universal :1018（含注释 :19/:1015 自证伪元素侧手写）；模板内 `@keyframes` 定义 0 命中 |
| `--mono-family` 仅 error_card 别名 | D-S12 | ✅ error_card.html:37 `--mono-family: var(--font-mono)` |
| wash `default('#')` 兜底 0 实例 | C-R8/4.3-4 | ✅ 7 模板全 0 |
| Math.random 0 实例 | V4/4.6-3 | ✅ 7 模板全 0 |
| gate08 黑名单 8 值/3 值被登记中和/有效 5 值 | A1/C-R14/4.3-7 | ✅ `test_v21r3_visual_gates.py:362-371` 八值 + :567 `not in _REGISTRY_HEXES` 中和；#b07d1a/#157347/#b42334=登记值故恒绿 |
| verify_hashes TRACKED=19 | D-S15/4.2-6 | ✅ `tests/verify_hashes.py:34-60` 实数 19 项 |
| 门族 8 文件+宪法门在位 | D-S14/4.1-5 | ✅ 8 件全存在；`tests/test_webui_constitution.py` 存在（node 硬依赖句仍真） |
| render_shell 生产消费数=0 | FS1/4.6-1 | ✅ 全 plugins 仅 mica_shell.py:501 定义，零调用方 |
| bridge `_card_root_tokens`+`_vis4_context` 消费法 | 4.3-11 | ✅ bridge.py:221/:178 |
| 契约现 9 条铁律 | V2 | ✅ :19-20 铁律 8/9 在位 |
| F14(f) 四坐标 3261-3426/718-816/71-321/123-220 | 4.6-1 | ⚠️ 行号已随 09-20 波漂移（echo 区段起点现 ~:3361、debug def :717）——本席落稿时**改用函数名锚定+注「行数以当次 grep 为准」**，不抄死数字 |

## 热脸判定与让路登记（交接指针）

- 活跃会话证据：HEAD 从 `767f2b5`(02:18)→`6ffdef3`(02:24) 五分钟四提交；`docs/design/unify-audit-20260919/{F2,F7,F25}.md` 02:19 同秒批量写；
  G2 progress 台账载明 T73/T75/T76/T77/T62 重派在飞 + 「登记册/AGENTS/HANDBOOK 收口席（波末）」排队。
- **让路 17 条不抢写**。终检窗口（见文末「终检」节）：若 02:2x 之后该四文件再无写入且静默 ≥30 分钟，本席按登记补投；
  否则移交时以本台账 + F24 §四 4.1/4.4/4.5/4.6-4 原文为完整施工单（after 文字可直接套用，行号按上表更新）。

## 执行记录（逐条：条目号 / 文件:行 / before→after 摘要 / 核实命令）

### 检查点 3（09-20 02:5x）：G3 docs/rendering-contract.md 十五条全部落实

AGENTS.md 于本段施工期间**再次**被 v21r5 会话写入（harness 两次文件变更通知，台账 #43 ⑦ 下半场增补+RESTART-PREP-4 句）——四件热脸让路维持不复议。

| 条目 | 位置 | 改动摘要 | 核实（改后与实盘一致） |
|---|---|---|---|
| 4.3-1 | L3 抬头 | 旧路径「适用于 output/card_render/」→ 11 面全列（7 模板+4 直拼真身路径与函数名）+垫片注记 | templates/*.html=7；四直拼真身 ls 全存在；垫片 templates/ 空目录实测 |
| 4.3-2 | L6 | 「任意一条必拦」→「断言位置列如实登记：有牙/半牙/纸面三态」+DESIGN-SPEC 判例句指针 | 随 4.3-3 列改造一并成立 |
| 4.3-3 | 铁律表增设「断言位置」列（表头+9 行） | 逐行登记有牙/半牙+旁路形态（bold 命名值/body 选择器/rgb 新语法/连写拆写/font 简写/两级面 E-12） | 断言族存在性 ls/grep 实证；旁路口径=F24 C-R4/R6/R7 + F5 §5（本席抽验 gate02 连写形态注释在 test_v21r3_visual_gates） |
| 4.3-3b | 铁律 8 整行 | 规则格限定「装饰层=DOM 斑/keyframes/关停」+伪元素特例指针；原因格拆出「数量时长半牙（连写）」与「keyframes 名门仅 7 模板（D-1）」 | `test_e03_no_new_keyframes` 仅扫 .html（F24 实证+本席核 CARD_TEMPLATES 全 .html 枚举） |
| 4.3-4 | §二 wash 段+CSS 样例块 | 样例块删（现势模板 default() 实例=0），历史形态等值锁保留为退化断言注记 | 7 模板 `grep "default('#"` 全 0 实测（两轮复核） |
| 4.3-5 | §四 mono 行 | 展示值改无空格登记形态+以值册为准注记；同格 `var(--mono-family)` → `var(--font-mono)`（**登记：4.3-5 原文只改值格，mono 命名漂移在同格，按 D-S12 同判一并修**） | theme_tokens.py MONO_FONT_STACK 无空格形态实读；error_card:37 别名在位 |
| 4.3-6 | §四 遮罩行 | 采「过渡改词」方案（不补门）：面扫无断言+D-2 指针+gate10 设计出处 | tests 无遮罩面断言（F24 §八 grep=0，本席抽验一致） |
| 4.3-7 | §四 语义色行 | 「一律 var()」→应消费+等值放行+8 员黑名单仅 5 值有效（逐值列名）+usage 活反例登记（D-3） | test_v21r3_visual_gates.py:362-371 黑名单 8 值/:567 中和逻辑实读；usage_cards :272 直写实读 |
| 4.3-8 | §四 次级文字行 | 「全模板单一来源」→等值手抄现状+改册不同步声明+--text-sub 双 token 缺口（D-4） | 7/7 模板 `--text-secondary: #576272` 手抄实测；text_sub #5b6069 于 mica_shell 注入段（F24 证据） |
| 4.3-9 | §四 字号行 | C8 限定 7 模板面+echo 12.5/14.5 现势+TYPE_SCALE 纯声明无门+E-13/X11 指针 | echo.py:3399/:3416 实测；`grep -rn TYPE_SCALE tests/` 零消费者（F24 §八，本席复核定义处唯一） |
| 4.3-10 | §四 宽度行 + §五.7 | 「一律经 shell_base_css 消费」→四处字面量不经查表+880 第 12 缺省档+universal 第三机制（D-6）；§五.7 补「新卡一律查表形态」 | echo:3376/debug:776/usage:250/templates.py:76/mica_shell:87 五坐标实测 |
| 4.3-11 | §五.1 | 「复制 market_card.html :root」→ bridge 上下文键唯一起点（照 finance_card 消费法）+复制=抄手抄副本判死 | bridge.py:221 `_card_root_tokens`/:178 `_vis4_context` 实测；market :root 仅特有键+注入位（test_rendering_contract.py:103-105 注释+F24 亲验） |
| 4.3-12 | §五.2 | 两写法并列合规作废→render_shell 唯一目标态+5 形态现势注记+新卡禁自造骨架 | render_shell 全 plugins 仅定义零消费者实测（本席 grep）；5 形态=F14-1 台账亲验 |
| 4.3-13 | §五.5 | 「两枚 token/SHADOW_PRIMARY·SECONDARY」→三级族三员+旧措辞作废注记+E-12 | theme_tokens SHADOW_CSS_VARS 三级（F24 §〇基线亲验，本席核契约铁律 6 同口径） |
| 4.3-14 | §五.6 | 「模板不手写」限定 DOM 斑侧+mermaid/universal 手写关停登记特例（E-2/E-3） | mermaid :121-125/universal :1015-1018 注释与 @media 实测在位 |
| 4.3-15 | §六末指针 + 新增 §八 | 骨架轴无条款无断言指针（D-7）；§八=豁免册 E-1…E-14+D-1…D-8 全表并入（**编号直称§八不补§七，登记为有意偏差**；E-13 原稿「见 D-1 补门建议」系 F24 错引，已改为「无门建立，见 §四字号行」并登记） | E-1…E-14 各行物证=F24 §五（其内逐行附本席 09-20 复核坐标）；D-6/D-3/D-5 现状实测在案 |

**残留 before 锚点自查**：`grep -n "违反任意一条都会被契约测试拦下|适用于 .plugins/bot_unified_runtime/output/card_render/ 全部卡片模板|机器门锁数量与时长集合|兜底字面量必须与|Consolas, \\\"JetBrains|一律 .var\\(\\). 消费；卡私|全模板 .--text-secondary. 单一来源|已收口；echo|直拼卡壳一律经|复制 .market_card|两枚 token 定义|模板不手写（C13）" docs/rendering-contract.md` → 0 命中（§三改后复跑再核）。

AGENTS.md 于施工中再被 v21r5 会话写入（台账 #43 下半场增补落地，harness 文件变更通知为证）——让路判定复核为真。

### 检查点 2b（09-20 02:4x）：G2 DESIGN-SPEC.md 七条全部落实

| 条目 | 位置（现号） | 改动摘要 | 与实盘一致性核实 |
|---|---|---|---|
| 4.2-1 | §一.2 :15 | 「各 7–10%」→「常用档 7–10%、混入比无机器门、面上已存 12%/28% 变体、禁作拦截宣称」 | echo.py:3416 `color-mix(... 12% ...)`、universal :1093 区段 `28%`×2 实测在位 |
| 4.2-2 | §一.3 :20 后追加 | 两级/三级不对称现状段（builders:229 钉两级、panel 档仅模板消费、待裁） | `test_exactly_two_shadow_token_definitions` tests/test_mica_builders_contract.py:229 grep 实证 |
| 4.2-3 | §一.4 :21 | 「一律消费/禁止表外」→「**应**消费；值册+注入面有锁、面扫零断言；债项 D-2 指针」 | 全 tests 无遮罩面扫断言（F24 §八 grep 同结果，本席抽验 scrim 断言=0） |
| 4.2-4a | §一.7 :24 字号段 | C8 收口限定 7 模板面 + echo 12.5/14.5 现势在位（门 ≥12 不咬、D-5 指针） | echo.py:3399/:3416 实测 12.5px/14.5px 在位（F24 所写 :3392/:3409 已漂 +7） |
| 4.2-4b | §一.7 :24 mono 段 | `var(--mono-family)` → `var(--font-mono)` 为公共键、error_card 别名注记 | error_card.html:37 `--mono-family: var(--font-mono)`；mica_shell `_PUBLIC_TOKEN_ORDER` 含 --font-mono |
| 4.2-4c | §一.7 :24 宽度段 | 「一律经 shell_base_css 消费」→「进表真消费表假」+ 四处字面量 + 880 缺省档 + D-6 | echo:3376=940/debug:776=880/usage:250=900/templates.py:76=640/mica_shell:87 全部 grep 实证 |
| 4.2-5 | §一.11 :28 ② | 「手抄副本=0 是常态门」→ 通水成立仅限色斑/装饰/玻璃；壳层 145deg 手抄实数 + 目标态声明 + shell_css 方案 | `145deg` count：模板 10（universal 4+六卡各 1）+ mica_shell 1 = 11 份。**订正稿 4.2-5 原文「模板侧 11 份+生成器 1 份」计数笔误，本席按实数改写并在此登记** |
| 4.2-6 | §二.2 :33 + §三表 | 门禁 5→8 件全列；12 文件→19（指针机器册）；perf_regression→test_ 实名；4500+→删数改实跑指针 | 8 件测试文件 `ls` 全存在；verify_hashes.py:34-60 实数 19；tests/test_perf_regression.py 存在 |
| 4.2-7 | §二.6 :37 | 「两者 --check 均常驻」→ doc_sync 常驻真、command_catalog 无常驻 subprocess 锁 + 补锁前禁称常驻 | tests/ 全树无 command_catalog --check subprocess（F24 H6/X4 判词，本席抽验 test_autosync_gate/test_doc_sync_gates 仅管键覆盖） |

**残留 before 锚点自查**：`grep -n "各 7–10% 混入白底|禁止表外深色遮罩|手抄副本=0 是常态门|4500+|等 5 族|12 文件|均已进 pytest 常驻门" DESIGN-SPEC.md` → 0 命中（改毕）。

### 检查点 4（09-20 02:4x–02:5x）：G6/G7/G8 三规格落实 + STEP 2 哈希对账 + 让路终检

| 条目 | 文件:位置 | 改动摘要 | 核实 |
|---|---|---|---|
| 4.6-1 | fstring-card-dom-spec.md :3/:7/:21-31 | 状态「未实施」→「部分实施（值层/生成器层已接 4 卡；render_shell 装配/D5/D7/D8/D6 查表五项未实施）」（采 F14 §7.2(f) 全文口径）；§0 四坐标全部换线现势真身+函数名锚定（echo `_help_mica_html`:3268/debug :717/usage_cards :74/templates.py :112+CSS :74，行号系 09-20 本席实测非 F14 旧数）；:7 token 路径改真身+垫片括注（X3 裁定延伸）；:30 universal 行数改「当次 wc 为准」（现 1675，**登记：此两处系 X3/FS4 裁定在点名条目同句的最小延伸**）；:6 「七条铁律」补「（现为九条）」注 | render_shell 零消费者 grep 实证；四 def 行号 grep 实证；content_parser 真身 `domains/link_parse/capabilities/` ls 实证 |
| 4.6-2 | render-pipeline-optimization-spec.md :3 | 状态「未实施」→「部分实施：并发/等待预算两键已接线（点名 config 键名，不写死行号）；等待分档/缓存/热点清理子项**待逐 § 复核、禁沿用旧判词**」 | `bot_render_max_concurrency/_wait_budget_ms` 实测 config.py:675-676（F24 所写 :629-630 已漂，登记） |
| 4.6-3 | visual-effects-catalog.md :3/:4/:5 + §0.2 D2 行 | 状态→逐 E 号记分（E01/E03 已实施、E10 维持、其余待复核）；「七条铁律」→「九条（成文时七条）」；模板路径换真身+「现 7 模板」；D2 行加历史冠+今态（Math.random 全 7 模板=0、digest+WAAPI、锁测在位） | `grep Math.random` 模板面 0 实测；test_phase_determinism(_2)/test_e03 两文件 ls 实证；契约铁律 8/9 在位实读 |

**§4.7 措辞统一表**：8 行全部为 4.1/4.2/4.3 的索引句——G2/G3 落实后该表所列「现词」在 DESIGN-SPEC/contract 面上已消失（锚点自查 0 命中），AGENTS 两行随 G1 让路移交。

## STEP 2 · 哈希门对账（只读，本席未跑任何 --write）

`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe tests/verify_hashes.py --check`（09-20 02:45 实跑）：

```
DRIFT    docs/rendering-contract.md（字节变更未记录——确认后 --write）
DRIFT    DESIGN-SPEC.md（字节变更未记录——确认后 --write）
DRIFT    docs/design/fstring-card-dom-spec.md（字节变更未记录——确认后 --write）
DRIFT    docs/design/render-pipeline-optimization-spec.md（字节变更未记录——确认后 --write）
DRIFT    docs/design/visual-effects-catalog.md（字节变更未记录——确认后 --write）
verify_hashes: 5 项漂移
```

**归属判定：5 DRIFT 全部、且仅为 DOC1-b 本席改动**。依据：哈希册 `tests/render_hashes.json` 最近一次重录=09-20 02:24 他席工作树态（e0b0722 之后未提交刷新），即本席开工前基线；19 件清单内其余 14 件（模板 7+theme_tokens/bridge/echo/debug/usage_cards/renderer/templates.py）对基线零漂移=别席/CAP1 未在册件留未录改动。主会话重录时 `--write` 将恰好收编本席 5 件+当时在飞态，请在授权范围口径里注明「DOC1-b=五文档件」。

**本席 git diff 对账**：`git diff --name-only` 全树 900+ 项均为多会话共享脏树；本席实际写下=
① DESIGN-SPEC.md ② docs/rendering-contract.md ③ docs/design/fstring-card-dom-spec.md ④ docs/design/render-pipeline-optimization-spec.md ⑤ docs/design/visual-effects-catalog.md（①–⑤ 皆在哈希册 19 件内）⑥ 本台账（新建，不在册）。
注意③⑤①②④中 ①②③⑤ 在 0918/0919 波亦有未提交旧改动（HEAD 差分含前波内容），本席改动叠加其上——commit 归属时「HEAD→现态」整段 diff 并非全属 DOC1-b，逐段归属见本台账检查点 2/3/4 条目表。

## 让路终检（02:48）

AGENTS.md **02:40**、docs/HANDBOOK.md **02:39**、docs/acceptance-manual.md **02:37** 仍有写入（v21r5/emergency 收口会话活跃，`docs/design/v21r5-BACKFILL-log.md` 在产）；docs/README.md 02:19 后静默但属同簇且与其两行强耦合（:96/:97 状态括注须与已改的 4.6-1/2 同步，同波收口一次投）。**17 条让路维持**，施工单=F24 §四原文+本台账「行号现势」列（AGENTS 锚点 :24/:32/:91/:108/:126/第五部分；HANDBOOK 锚点现号 :258/:2213/:2217/:2218/:2219/:2259；acceptance-manual 现号 :391/:405/:406/:429；README :96/:97/:98）。
唯一提醒交接席：F24 的 HANDBOOK/AGENTS 行号系 09-19 快照，两文件此后大幅增行，套用前须按锚点串重定位（本台账已给现号）。

## 树卫生自证

全程仅 Edit/Write 目标文档；直跑 python 仅 `verify_hashes.py --check` 一次（三件套环境）；未跑 pytest（无 --basetemp 需求）；未产 `__pycache__`/`.pytest_cache`（BOT_AUTOSYNC=0 亦挡 autosync 钩子）；`git status` 中本席新增仅本台账一件。
