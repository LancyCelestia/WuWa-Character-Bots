# 交接提示词（2026-09-14 凌晨 · 六域批次后 · 给下一个 AI）

> **你是谁**：守岸人 Bot 项目的新接手 AI。本文件是唯一交接入口，读完即可开工。
> 读完本文件后，按 §7 的「开工流程」三步走，不要跳过。

## 0. 一句话现状

代码与测试健康（六域各域测试全绿、哈希/事实册/性能三类常驻门随批重录），2026-09-13/14 六域批次（金融/账单/视觉/图库/e2e 自测/笔记授时）+ 安全审计 + 双评审修复已分批落检查点：`cfd7d83` 四卡阴影解锁 / `7414e87` 笔记授时 config 六键 / `bdbc88b` Tavily 图搜兜底+图库满编 / `93e8195` 安全修复包 / `f3962f1` 视觉评审修复 / `5ba7c0f` 金融评审修复——但**仍有工作树未提交件**（数量与构成以 `git status` 实况为准，归属索引见 §6 与 AGENTS.md 台账 #31；截稿时点在飞=e2e 实战自测席，XHS 泄漏桥接席已落库 `8cbd4b6`，以 git status 最新为准），且**生产 bot 未重启**——你的第一件事通常是提醒用户提权重启 bot（见 §5），然后做 §6 收尾。

## 1. 项目 30 秒

QQ 聊天机器人「守岸人」（鸣潮角色人格，非 AI 设定），NoneBot2 + OneBot V11（NapCat，正向 WS 127.0.0.1:3001，token 见 .env）。主包 `plugins/bot_unified_runtime/`，运行数据全在 `ChatBot_Runtime/`（兄弟目录，**不可删改**），venv 在 `ChatBot_Runtime/venv/`。**完整项目说明读 `AGENTS.md`**（规则+架构+台账 30 行）——它与本文件互补，冲突时以 AGENTS.md 为准。

## 2. 硬规矩（违反即事故，先背下来）

1. **改代码必须重启 bot 才生效**；生产进程管理员权限运行，只有用户能重启。
2. **源码树零缓存**：绕过 dev.ps1 直跑必须 `PYTHONDONTWRITEBYTECODE=1`，pytest 加 `--basetemp="$TEMP/xxx" -p no:cacheprovider`。树里不许出现 `__pycache__/data/.pytest_cache`。
3. **`plugins/bot_unified_runtime/sources/data/qx.json` 是内置资产**（NMC 天气码表），任何清理不得动它（历史三次误删三次事故）。
4. **git**：禁 `git add -A/.`；逐文件显式 add；提交后 `git show --stat HEAD` 核对；**push 只在用户明确指示时**，refspec `refs/heads/v0.0.1-alpha.2:refs/heads/v0.0.1-alpha.2`。
5. **说"完成"必须有证据**：提交哈希或可复跑命令+实跑输出。测试/lint 结果必须实跑，禁编造。
6. **人格资产**（personas/）改前读 AGENTS 规则 8；守岸人语气红线写死在 affinity.py。
7. **代理纪律**（用户常要求 2 并发子代理）：按文件域互斥切分；代理禁 git 写、禁再派代理；**并发上限受当日累计用量动态约束**（非固定值）：高消耗日 2-3 并发即触发 1302（09-13 观测），低消耗日可 6-7（09-14 观测）；机制同 AGENTS 规则 7（两处观测归因已对齐）；弹回=串行自己做，不要硬重派；代理阵亡先取证遗留（git diff + 跑域测试），能收编就收编。
8. 直跑 python 用绝对路径：`"C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe"`（shell 里相对路径会因 profile 报错）。

## 2.5 自动同步铁律（用户核心要求：改一处，全局联动，一处都不许漏）

这是本项目最重要的机制，**任何改动必须走对应的联动流程，漏一步测试门直接红**：

| 你改了什么 | 必须联动 | 机制 |
|---|---|---|
| **HTML 渲染模板/视觉 token** | 视觉值只准改 `theme_tokens.py`（token 单一事实源），模板只准 `var()`/注入引用——**改 token=全模板自动生效**；模板结构改动后跑渲染契约族测试；交付物（6 模板+theme_tokens+契约文+DESIGN-SPEC 等 12 文件）字节变了必须 `python tests/verify_hashes.py --write` 重录 SHA-256（`--check` 已是 pytest 常驻门，漏录直接红） | 根部 `DESIGN-SPEC.md`（设计/执行/验证三规范）+ `docs/rendering-contract.md` |
| **全项目代码/命令/触发词** | 改 `echo.py`（帮助注册表/触发词）或 `base_router.py`（路由）后必跑 `python scripts/command_catalog.py --write`——`docs/command-catalog.md` 与 `COMMANDS.md` 自动重生成，漏跑 `test_catalog_document_matches_registry` 红 | "一处修改，全局联动"用户裁定 |
| **文档中的清单/数字类事实** | 代码变了跑 `python scripts/doc_sync.py --write`——`docs/auto-facts.md`（模板清单/RouteKind/帮助 topic 数/测试文件数/配置键数）整册从代码重生成，`--check` 常驻门；**该册机器所有，禁止手改** | 交叉验证机制·文档层 |
| **设定/提示词/人格**（personas/） | 人格源-副本一致性已有机械门：`python scripts/sync_persona_source.py --check`（`a1cf739`；改人格后 `--adopt` 重录锚定复绿）；`identity.md` 等已在哈希清单内的文件改后同样 `--write`；话术红线见 AGENTS 规则 8；蒸馏拟稿待用户裁决（.superpowers/sdd/2026-09-13-six-domain-batch/persona-distill-draft.md） | 机械门+哈希兜底 |
| **热路径性能** | `tests/test_perf_regression.py`（pytest 常驻）：路由吞吐/导入时长超数量级阈值直接红——**不许抬阈值**，先 systematic-debugging 定位 | 交叉验证机制·性能层 |
| **双引擎交叉验证** | 提交前/大改后跑 `python tests/cross_validate.py`：同一套测试默认引擎与隔离引擎各跑全量，结果必须一致，不一致=环境耦合缺陷 | 交叉验证机制·执行层 |

**记忆口诀**：改模板→跑契约族；改交付物→`verify_hashes --write`；改代码事实→`doc_sync --write`；改命令→`command_catalog --write`；动性能→`test_perf_regression` 说话；收尾→`cross_validate` 互证。**全部 `--check` 形态已进全量测试门，漏一步全量必红**——这就是 SHA-256 哈希、pytest、延迟/性能测试的常驻形态。

## 3. 常用命令

```powershell
# 全量测试 / lint / typecheck（各约 1-4 分钟，全绿是交付底线）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"
# 以下 python 均指 §2.8 的 venv 绝对路径 python.exe（直跑系统 python 缺依赖）
# 真机验收（bot 重启后）：DRY-RUN 缺省，--execute 真发；--selftest 离线自检 11 项
python scripts/e2e_acceptance.py --target-group <白名单群ID> --execute
# 性能基线 / 渲染样本 / 命令目录 / 机器事实册 / 哈希清单
python scripts/measure_latency_chains.py all
python scripts/command_catalog.py --write     # 改 echo.py/base_router.py 后必跑
python scripts/doc_sync.py --write            # 机器事实册（--check 已进测试门）
python tests/verify_hashes.py --write         # 视觉交付物哈希（--check 已进测试门）
python scripts/clean_food_gallery.py --execute  # 图库污染清理（VLM 复判）
python -m plugins.bot_unified_runtime.capabilities.eat --prewarm  # 图库补图（质检链自动过滤）
```

## 4. 本批（09-13/14 六域批次）已落库滚动清单（哈希可溯；标「工作树」= 未提交在飞件）

批次报告与评审全文在 `.superpowers/sdd/2026-09-13-six-domain-batch/`（fin/billing/visual/visual-closure/gallery/usage-card/perf/security/ssrf-guard/e2e/docs 九域报告 + review-fin-billing/review-visual-infra 双评审）。

- **金融扩容**（A1 席；能力闭包/北向数据段/新源文件已入库 `5ba7c0f`+`3592793`，生产 matcher 注册 `691d6e1` 三谓词+三 matcher+三工厂+三 handle）：大宗商品（COMEX 金/银/铜+NYMEX 油，30 日折线）、国债收益率（中美 2/5/10/30 年+10Y−2Y 期限利差）、北向资金（净买入 2024-08 起停止披露→只报成交总额/笔数/领涨股，`NorthboundFlow` 结构性无 net 字段绝不造数）、个股 logo 三级兜底+预热已入库 `a4371d2`（8/9 域名落盘，meta.com s2 返 JPEG 诚实降级零死链）。**诚实降级清单**见 fin-report §四：印度 Nifty 50 东财无源不接、LME 铜无源→COMEX 铜显式替代、Brent 无行不接、1 年期国债无源不接、北向净买入绝不编数、南向未接。
- **账单域**（A3 席）：同模型多渠道候选集+跨渠道 failover 拨转（渠道 id 入口连通兄弟渠道，model_router failover 已随 `065961d` 入库）、影子并发 `hedged:winner` 计费归因修复、**千倍计价修复**（cost 虚大 1000 倍→`/1000` 与 pricing 同口径；ledger 侧已落库 `5ba7c0f`）、渠道子行展示（定时报告/超限即时卡/交互卡三处，已随 `3592793` 入库）；52 条价目逐条审计（25 条可疑/过时待用户裁定，入 issue-ledger P2-10）。
- **视觉五工序+收口+阴影解锁**（A6 席+收口席）：好感度卡脏数据 6 连崩修复（bridge 归一+10 组参数化回归）、zebra 三档表面 ΔE 0.81→3.76、TEXT_SECONDARY 单源（评审后调深终值 #576272，premultiplied 真模型 4.72 达 AA）、字号 12px 下限全卡收口、usage 卡补 vis4 六键+bot 页脚胶囊；四卡阴影解锁（`cfd7d83`：SHADOW_CSS_VARS 登记表+双门动态白名单，族外一票否决不留后门）；market/finance/媒体卡/debug 卡收口并入可编辑门。视觉件主体已入库（bridge 随 `1651544`、usage_cards.py 随 `3592793`、vis5 收口随 `06a8742`）；余件以 git status 实况为准。
- **笔记/提醒/授时**（A2 席，**已收编 `789700c`**）：notes/notes_store/timesync/reminders 全功能入库（mark_done 死锁 Critical 修+timesync now() global 修+授时全链+安全包 M-2/3/4/8+分型提醒语气+自然勾选+Markdown 笔记 CRUD），config 六键（`7414e87`）；⚠️ 原 P1（`now()` 缺 `global _SHARED` 声明毒化 reminder 路由链）**已随此笔修复**，警示撤销。
- **SSRF 解析链护栏**（安全审计 I-2 修复，已随 `efe7b79` 入库）：`sources/parsers/ssrf_guard.py`（新增）+content_parser 入口+og 兜底落点双查（内网/元数据 URL 借平台关键词混入也拒），13 例回归；安全修复包 `93e8195` 已入库（I-1 图搜重定向落点复查+M-6 mkstemp）。安全审计终态 Critical 0 / Important 2 全修。
- **Tavily 图搜兜底**（`bdbc88b`）：Bing 缺图/缺候选时走已配 key 的 include_images 直链候选，域黑名单/SSRF/字节/magic/像素五道质检闸全链复用。
- **图库治理**：清污 53→13（VLM 复判+人工抽验 7/7，40 图入 %TEMP% 隔离区，总账 53=13+11+29 闭合）；Tavily 补图链路实证 **61/61 满编**（`bdbc88b`）——现库 13/61，重启前重跑 `eat --prewarm` 补 48 道缺口（质检链会重新过滤）。
- **性能门收紧+五链路复测**：吞吐门循环 500→5000 次修正（真余量 120x→牙齿 8~14x，阈值未放宽）；路由 P50 0.016ms/P95 0.058ms（噪声带内无代码退化）、渲染 warm P50 2141ms、`BOT_RENDER_WAIT_BUDGET_MS=1500` 离线实证 P50 772.9ms（**−64%**）；六域新模块全惰性化（启动关键路径仅 +3.2ms）。
- **e2e 实战自测增强**（A4 席，**收尾中·真实在飞**）：e2e_acceptance.py 大幅增强（命令矩阵/响应收集/私聊报告/`--selftest` 11 项，按命令目录动态生成；topic 数不写死，以 `command_catalog.py --write` 生成值为准）；工作树件=scripts/e2e_acceptance.py+tests/test_e2e_help_matrix.py。
- **续批四件+两件闭环**（2026-09-14 回填，git log 实查）：素材本地化 F2 stocks logo 三级兜底+8/9 预热 `a4371d2`、F3 bot 头像本地优先+金融三能力生产 matcher 注册 `691d6e1`、F1 mermaid.min.js 本地化治 #8 `959630a`+`871beb2`（拦截半边 render_backends page.route 已随 `e37817f` 入库）；渲染 Phase 2 已收官 `13fcd30`（.env 解锁并发 2/预算 1500ms）；**统一错误报告卡全链已入库**（`1651544` 模板/bridge/契约 + `84b3915` 补发加速 + `de6ba91` 异步化两段式；error-card-report：全链+冷却+脱敏，测试 22+契约 199+回归 292）。
- **文档预收尾**：HANDBOOK §24（六域总账）、acceptance-manual §6.6.3（金融+账单验收五项）、issue-ledger P2-10/P2-11/P3-7/P3-8、AGENTS.md #31。
- 前批已落（可溯 git log）：时间窗总结 `1b23622`、vis4 全卡迁移 `77f56de`、自动同步闭环 `ccd38b9`（dev.ps1 -Task sync + BOT_AUTOSYNC=1）、图库清理器 `3e0f507`。

## 5. 用户必须做的事（你只能提醒）

**提权重启生产 bot**——不重启，以上全部不生效。重启前置：先跑 `python scripts/pre_restart_check.py`，**全 PASS 再动手**（已入库 `051261d`：7 项检查 PASS/SKIP/FAIL+exit code+`--json`，无 FAIL 再动手）。重启顺序：**先 NapCat 后 bot.py**（管理员）。重启后验收：`acceptance-manual.md` §6.6（九项卡面）/§6.6.1（触发五表）/§6.6.2（媒体归档六项）/**§6.6.3（金融扩容+账单渠道五项）**/**§6.6.4（提醒/笔记/授时+错误报告卡：临时断网发一条 `行情`，期待云母诊断卡+冷却期内第二条降级纯文本）**/**§6.6.5（本批新增能力：视觉收口+样张+知识库检索）**；再跑 `measure_latency_chains.py all` 补 NapCat/Mail/TG 在线延迟（此前 unreachable）。

## 6. 在飞/待办（按优先级）

1. **收尾提交**：清单与数量**以 `git status --porcelain` 实况为准**（收尾批持续推进，不写死构成；2026-09-14 截稿快照=e2e 实战自测席 `scripts/e2e_acceptance.py`+`tests/test_e2e_help_matrix.py`；XHS 泄漏桥接收尾移交席已落库 `8cbd4b6`）——逐域跑域测试后显式 add 提交。归属索引：`AGENTS.md` 台账 #31（六域各席归属）+ `.superpowers/sdd/2026-09-13-six-domain-batch/sdd-INDEX.md`（分域报告目录）。~~⚠️ HEAD 不自含~~ → **已闭环**：commodities_data/bond_data 已随 `3592793` 入库、render_backends mermaid 拦截半边已随 `e37817f` 入库，现 HEAD 自含，可安全 checkout/diff 取证。
2. ~~金融三能力触发词接线~~ → **已注册生产 matcher**（`691d6e1`：三谓词+三 matcher+三工厂+三 handle，照 market/stocks 装配，90 例回归绿；此前 `789700c` 只接了 base_router RouteKind+echo 帮助层，生产装配由本笔补齐）。
3. ~~时间窗总结~~ → 已落库（`1b23622`：「总结 N 分钟内消息」→history 时间窗召回注入 chat）。
4. ~~图库清理收尾~~ → 已闭合：53=13+11+29、人工抽验 7/7；重启前重跑 `eat --prewarm` 补 48 道缺口。
5. ~~全卡 vis4 迁移~~ → 已落库（`77f56de`+`cfd7d83`+`f3962f1`+收口席：六模板+媒体卡+usage/debug 卡全部收口）。
6. ~~23:00 定时任务：渲染 Phase 2 接线~~ → 已落地（`13fcd30`：两键解析链+config/catalog/.env.example 三件套；.env 已解锁并发 2/预算 1500ms，删行即回滚）。
7. **收尾波统一门禁**：三联动 `--write`（command_catalog/doc_sync/verify_hashes）→ `dev.ps1 -Task test`（BOT_AUTOSYNC=1 自动兜底）+ lint + typecheck（以 lint 实跑为准——A54 终扫全绿 0 红，本席复核 `ruff check .` 全绿；历史「26 错」口径作废勿引用）→ `cross_validate` 互证。

**等用户裁定（AI 只提醒，不代决）**：
- 25 条价目可疑/过时清单（billing-report §3.3 / P2-10；6 项优先：deepseek-v4-pro 输入价、v4-flash 族已下线、qianqianye 3~4.5× 倒挂、gpt-5.6-luna 2.1× 倒挂、aiprc fable-5 两行互斥 6.7×、axonhub gemini 裸名上游归属）。
- 账本历史行 cost 千倍虚大是否清洗（P2-11，本批未动生产库）。
- Apple Music×小红书 accent 是否拉开（ΔE=2.7，P3-1）。
- 页脚第二槽 'Shorekeeper' 是否改「解析」（视觉 clarify 裁定行）。
- usage 卡 kicker 去留（P3-2）。
- 磁盘 pagefile.sys 82GB 需重启回落。
- $TEMP oopz 安装包 458MB 是否删。

## 7. 开工流程（三步）

1. 读 `AGENTS.md`（重点：第一部分规则、第六部分台账 #26-#31）；
2. `git status --porcelain` + `git log --oneline -10` 摸清现场；若有未提交遗留，先取证（跑对应域测试）再收编；
3. 跑一次 `dev.ps1 -Task test` 确认基线全绿（提醒用户重启前另跑 `python scripts/pre_restart_check.py` 全 PASS，见 §5），然后按 §6 顺序干活。**用户会说"继续"和"开 N 并发子代理"——照 §2.7 纪律执行即可。**
