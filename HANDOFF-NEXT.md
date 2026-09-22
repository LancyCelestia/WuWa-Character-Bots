# 交接提示词（2026-09-15 午后 · 全量更正版 · 给下一个 AI）

## 当前交接：后端 V2.1（2026-09-17）

**先读本节；下方旧“最新/已完成/测试通过”属于历史批次，不是本版实施证据。** 用户本次要求把完整计划及补充需求交给下一AI；本轮只写文档，未修改生产代码、配置、数据库、好感度或部署状态。

依次阅读三份完整实施合同：

1. [架构与实施规范](docs/design/backend-v2-implementation-guide.md)：强隔离、统一治理、全部后端协议、S0—S16与发布门禁。
2. [产品扩展与具体算法](docs/design/backend-v2-product-extensions.md)：LLM/TTS/绘图计费、自愈/待审修复、好感度、运势/塔罗、全场景日程、戳与表情、多平台搜索、admin告警、可查看媒体的实战验收、元数据投影。
3. [需求验收矩阵](docs/design/backend-v2-acceptance-matrix.md)：每项独立记录 implementation / production_wiring / offline_validation / live_validation，当前新目标均待核验。

已定决策：所有业务插件（含内置）Windows AppContainer＋Job Objects强隔离，失败不得普通subprocess降级；允许运行自愈，自动代码修复只能输出待审补丁，不自动部署；不做前端；保留全部WIP/生产数据。不要重新让用户选择这些已定事项。

用户新增问题：测试grok主题路由时一晚掉40多点好感。源码已发现refuse归insult、normalized/points单位和poke override额度风险；历史根因未重放确认。必须先复现，再解耦分类/拒答/关系分数、加持久滚动限额；不得无证据恢复40分。详见扩展§2和[findings](findings.md)。主题路由不改变人格/内容边界，也不能用拒答作为换模型绕过的触发器。

开工方式：先冻结S0现有WIP与入口清单，沿主规范风险点取得失败测试；验证S1真实OS隔离，依赖顺序推进。已有ledger/SendQueue/FTS与向量检索/牌组/Service先复用，不再写平行占位API。真实验收缺少的admin接收人、白名单、provider/预算、时间窗、临时数据、维护许可一次集中问清；已授权范围直接执行，阶段结束不重复询问。新风险或扩大授权才升级；缺外部依赖继续其余工作并如实标blocked。

文档任务进展见[task_plan](task_plan.md)、[progress](progress.md)。当前不可声称完整后端实现或可发布。规划中的新API/命令未加入现行COMMANDS或机器事实，实施后通过生成器与真实门禁同步。

门禁注意：当前dev.ps1的test任务强制开启autosync并可能重录渲染哈希，外层设0无效。先依主规范§13保留基线并处理该冲突，不能把自动改预期后的通过当成有效回归。

---

以下为历史实现与证据，按需查阅，不覆盖上方V2.1目标和用户决策。

> **最新续接：动作API路由/错误码已修正，隔离工作区CRUD/预览/确认/模拟发送与默认生成装配已落地；真实会话生产发送、完整后端仍未完成。最新实跑及runtime-layout阻断见 `docs/design/COMPACT-CHECKPOINT.md` 顶部。**


> **最新增量：15个细分执行开关、Bot/NoneBot日志摘要采集、Telegram getUpdates网络韧性修复。详情与实跑结果见 `docs/design/COMPACT-CHECKPOINT.md` 顶部；协议见 `control-plane-registry.md`、`control-plane-events.md`。未部署、完整后端未完成。**


> **Compact最新入口：先读 `docs/design/COMPACT-CHECKPOINT.md`。SQL功能门、配置服务、SSE、metrics、生命周期已有新增实现；旧5项失败及续接暴露的错误卡问题已处理；最新全量6603 passed，Ruff/Mypy/runtime-layout通过。完整后端未完成；能用子代理就用子代理、并行满载（限流为唯一上限，撞墙落盘保进度、结束即补派、前台派完即收不卡输出）。旧§9及旧状态页部分结论已过期，不要重做。**

> **续接校正：§9 与 `docs/design/control-plane-core-status.md` 是历史切片；SQL功能门已接主Pipeline，实际最新状态以 COMPACT-CHECKPOINT 顶部为准，不重复实施。完整细分门禁与完整后端仍未完成。**

> **你是谁**：守岸人 Bot 项目的新接手 AI。本文件是唯一交接入口，读完即可开工。
> 深读字典：`docs/HANDOVER-2026-09-15.md`（架构/流程/九个统一/WebUI 全量，按需查）；总账 `docs/HANDBOOK.md` §1-§27。

## 0. 一句话现状

代码与测试健康（测试/门禁现状一律以最近一次实跑与 `docs/auto-facts.md` 机器册为准，勿引手写计数）。09-14 六域批 + 09-14/15 夜间审计批（HANDBOOK §24-§26）+ 09-15 会话批已落库至 `6ac897b`：超时根修三连（连接分类+告警轨迹+预算 300s）、生产启动崩溃修复（`793e647`）、P2-4 五池守岸人文案、SETTABLE 41/31 诚实化、daily_assist、WebUI 规格（`331e2a2`）、**LLM 链路收敛 26 渠道 id→4 真模型名单组直连 axonhub（`.env` 已改，gitignored——证据=解析+三时刻命中实测+30 例回归）**。**生产 bot 未重启**——你的第一件事通常是提醒用户提权重启（§5）。工作树常态有并行代理在飞件（§6），先取证再收编、勿盲收盲删。

## 1. 项目 30 秒

QQ 聊天机器人「守岸人」（鸣潮角色人格，非 AI 设定），NoneBot2 + OneBot V11（SnowLuma，正向 WS 127.0.0.1:3001，token 见 .env）。主包 `plugins/bot_unified_runtime/`，运行数据全在 `ChatBot_Runtime/`（**兄弟目录，不可删改**），venv 在 `ChatBot_Runtime/venv/`。**完整项目说明读 `AGENTS.md`**（规则+架构+台账 33 行）——冲突时以 AGENTS.md 为准。LLM 全部经本地 axonhub 网关（127.0.0.1:8090/v1），bot 只发模型名（gemini-3.8-flash→gpt-5.6-terra→grok-4.6→deepseek-flash），渠道选择归 axonhub。

## 2. 硬规矩（违反即事故，先背下来）

1. **改代码必须重启 bot 才生效**；生产进程管理员权限运行，只有用户能重启。
2. **源码树零缓存**：绕过 dev.ps1 直跑必须 `PYTHONDONTWRITEBYTECODE=1`，pytest 加 `--basetemp="$TEMP/xxx" -p no:cacheprovider`。树里不许出现 `__pycache__/data/.pytest_cache`。
3. **`plugins/bot_unified_runtime/sources/data/qx.json` 是内置资产**（NMC 天气码表），任何清理不得动它（历史三次误删三次事故）。
4. **git**：禁 `git add -A/.`；逐文件显式 add；提交后 `git show --stat HEAD` 核对；**push 只在用户明确指示时**，refspec `refs/heads/v0.0.1-alpha.2:refs/heads/v0.0.1-alpha.2`。
5. **说"完成"必须有证据**：提交哈希或可复跑命令+实跑输出。测试/lint 结果必须实跑，禁编造。
6. **人格资产**（personas/）改前读 AGENTS 规则 8；守岸人语气红线写死在 affinity.py；面向用户话术一律走五池纪律（≥12 变体/官方语音文风/游标轮换，见 HANDOVER §统一⑤）。
7. **代理纪律（2026-09-17 起：默认并行满载 + 前台即收）**：能用子代理就用子代理，时刻保持并行满载，以限流为唯一上限；子代理结束立即派遣新的子代理补位，直至任务全部完成。按文件域互斥切分；代理禁 git 写、禁再派代理；并发受当日累计用量动态约束（高消耗日 2-3 即 1302，低消耗日 6-7）；撞限流墙→先落盘进度断点、守住存量、取证阵亡者幸存成果，指数退避后从断点续派只补未完成，持续受限才降级串行自己做，不空等不中断；代理阵亡先取证遗留（git diff+域测试）再收编。**主会话不占前台**：完成派遣与整合即结束本轮回复、留出对话空间给用户，不在前台长时间卡输出思考，子代理在后台并行跑。
8. 直跑 python 用仓库根相对路径的 venv 解释器（真身见 AGENTS 运行数据根约定 + `scripts/runtime_paths.py`），正文勿写含用户名/盘符的绝对路径。

## 2.5 自动同步铁律（改一处，全局联动，漏一步测试门直接红）

| 你改了什么 | 必须联动 | 机制 |
|---|---|---|
| **HTML 模板/视觉 token** | 只准改 `theme_tokens.py`（单一事实源）；交付物字节变了必须 `python tests/verify_hashes.py --write` 重录（`--check` 常驻门） | 根部 `DESIGN-SPEC.md` + `docs/rendering-contract.md` |
| **命令/触发词/路由** | 改 `echo.py` 或 `base_router.py` 后必跑 `python scripts/command_catalog.py --write`（`docs/command-catalog.md`+`COMMANDS.md` 自动重生成） | 「一处修改，全局联动」用户裁定 |
| **清单/数字类事实** | `python scripts/doc_sync.py --write`——`docs/auto-facts.md` 整册机器重生成，**禁止手改** | 交叉验证机制·文档层 |
| **人格 personas/** | `python scripts/sync_persona_source.py --check`（改后 `--adopt` 重录）；哈希清单内文件改后 `--write` | 源-副本一致性机械门 |
| **热路径性能** | `tests/test_perf_regression.py` 常驻——超阈值直接红，**不许抬阈值**，先 systematic-debugging | 交叉验证机制·性能层 |
| **双引擎互证** | 大改后 `python tests/cross_validate.py`：默认引擎与隔离引擎结果必须一致 | 交叉验证机制·执行层 |

**口诀**：改模板→跑契约族；改交付物→`verify_hashes --write`；改事实→`doc_sync --write`；改命令→`command_catalog --write`；收尾→`cross_validate`。

## 3. 常用命令

```powershell
# 全量测试 / lint / typecheck（全绿是交付底线）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"
# 以下 python 指 §2.8 venv 绝对路径；真机验收（重启后）DRY-RUN 缺省
python scripts/e2e_acceptance.py --target-group <白名单群ID> --execute
python scripts/pre_restart_check.py        # 重启前置，全 PASS 再动手
python scripts/command_catalog.py --write  # 改 echo/base_router 后必跑
python scripts/doc_sync.py --write         # 机器事实册
python tests/verify_hashes.py --write      # 视觉交付物哈希
```

## 4. 已落库滚动清单（浓缩版）

- **全量总账**：HANDBOOK §24（六域批）/ §25（夜间审计批）/ §26（审查执行批）/ §27（daily_assist）+ AGENTS.md 台账 #31-#33。
- **09-15 会话批**（`dcb7b02..6ac897b`，30 笔可溯）：ack 回执根修 → control-plane Host 白名单（Critical）→ 决策痕迹持久化 → 夜间审计 20 笔（§25/§26）→ SETTABLE 诚实化 → 触发词双向机械门（218 缺口台账 `4252944`）→ daily_assist `da255b0` → P2-12 SSRF 收窄 → P2-9/P3 系批量修复 → 夜间总报告 `d7c55b7` → 启动崩溃 `793e647` → P2-4 文案 `ebe6843`+`97d0aa6` → WebUI 规格 `331e2a2` → 超时三根修 `12b7f4a` → 预算+五池 `6ac897b`。
- 旧批次明细按需查 HANDBOOK 对应 §，不在本文件复读。

## 5. 用户必须做的事（你只能提醒）

**提权重启生产 bot**——累积生效清单（全部已落库/已改配置，未重启零生效）：链收敛 4 模型 / 预算 300s / 五池文案 / 连接分类+告警轨迹 / TG 退避 / 启动崩溃修复 / SETTABLE / 夜间审计批全部。前置：`pre_restart_check.py` 全 PASS；顺序**先 SnowLuma 后 bot.py**（管理员）；重启后验收 acceptance-manual §6.6 族 + `measure_latency_chains.py all` 补在线延迟。另：campus 启用四步（launcher-school.bat 扫码→.env 填 BOT_CAMPUS_GROUP_WHITELIST→.env.prod 解注释 3002→重启）；X cookie 灌入后立即删除 Downloads 临时文件（含 auth_token）。

## 6. 在飞/待办（按优先级）

1. **工作树在飞四席**（以 `git status --porcelain` 实况为准）：campus（3 文件 untracked+台账行，提交裁决权在用户）/ glossary（glossary.py+两测试）/ sender 韧性（onebot+worker+media 拒收回退测试）/ persona 测试；另有 auto-facts.md 机器册重生成在飞（勿手收）。
2. **两处存量缺陷待立项**（campus 批调研发现）：群摘要读零行（shared_group.py session_id 口径错，21:30 静默空转）；推送路径未传 llm_provider（`BOT_GROUP_DIGEST_LLM_ENABLED` 推送侧恒不生效）。见台账 #33。
3. `/bot decision` 生产 `__init__.py` elif 接线未交付；触发词方向 2 全词族（已批未做）；方向 1 的 218 缺口待用户裁决。
4. **WebUI**：只探索不写码（用户裁定）；规格+需求全集+三阶段=HANDOVER §4。
5. 等外部：F7 cos 随机图（用户插件）；B5 沙箱/B14 用户 key；页脚头像（可选）。

## 7. 开工流程（三步）

1. 读 `AGENTS.md`（重点：第一部分规则、第六部分台账 #29-#33）+ 本文件 §2/§2.5；架构流程深读 `docs/HANDOVER-2026-09-15.md` §1-§3。
2. `git status --porcelain` + `git log --oneline -10` 摸清现场；未提交遗留先取证（跑对应域测试）再收编。
3. 跑一次 `dev.ps1 -Task test` 确认基线（提醒用户重启前跑 `pre_restart_check.py`），然后按 §6 顺序干活。**用户会说"继续"和"开 N 并发子代理"——用户说"继续"即默认开子代理并行满载（无需等点名），派完任务即收、留对话空间；照 §2.7 代理纪律执行。**

## 8. 2026-09-15 控制面后端实现进度（交给下一 AI）

> 本节是本次会话真实结果，不代表整份 WebUI 计划已经完成。实现范围：后端第一条可运行切片；前端暂未实现。不要据此宣称“可发布”。

### 8.1 已新增/修改的代码

新增 `plugins/bot_unified_runtime/control_plane/features.py`：

- `FeatureDescriptor`：稳定功能节点描述，支持 group/plugin/feature/command 等类型。
- `FeatureState`：显式状态、有效状态、继承来源、阻断原因、版本、操作者和时间。
- `FeatureRegistry`：ID、alias、父子层级、循环和重复 alias 校验。
- `FeatureStateStore`：Runtime 文件原子保存、树状继承、依赖阻断、版本冲突、变更审计。
- 当前只放入最小示例节点：`bot`、天气、聊天、控制面、审计、错误处理、人格安全边界；**尚未收编全量插件和指令**。

新增 `plugins/bot_unified_runtime/control_plane/api/v1.py`：

- 统一响应 envelope：`data/error/meta`，`meta.schema_version = v1`。
- 功能查询：`/api/v1/features`、`tree`、详情、子节点、状态、审计。
- 功能写入：`enable`、`disable`、`reset`，带 super-admin 和 expected_version。
- 配置读取：`/api/v1/config`、`schema`、单键读取。
- 配置预览/写入/重置：仅复用 `SETTABLE_KEYS`，未登记或需重启键拒绝热改。
- 日志初步投影：`/api/v1/logs`、`/api/v1/logs/sources`；当前尚未接入完整统一事件总线、SSE 和 SnowLuma 独立日志采集。
- 资源初步投影：`/api/v1/metrics/resources`、`overview`；当前不是完整指标系统，调用数/token 返回 `unknown`。
- 轨迹接口占位：`/api/v1/traces` 当前明确返回 `not_connected`，不得误认为已实现。
- 工作区接口初步占位：`/api/v1/workspaces`，创建默认声明 `production_side_effects=false`；尚未接入真实对话、Prompt、知识库和模型调用链。

修改 `plugins/bot_unified_runtime/control_plane/_app.py`：

- 保留既有 `/admin/api/v1` M1 健康接口。
- 接入新的 `/api/v1` router。
- 增加独立 `BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256` 写令牌依赖。
- 普通 Bearer 令牌只读；写操作要求 super-admin 令牌。
- 功能状态默认写入 `BOT_CONTROL_PLANE_FEATURES_FILE`，默认值为 Runtime 下 `data/control_plane_features.json`。

修改 `plugins/bot_unified_runtime/control_plane/__init__.py`：

- `ControlPlaneSettings` 增加 `super_admin_token_sha256`。
- 读取 `BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256` 和 `BOT_CONTROL_PLANE_FEATURES_FILE` 文档配置说明。

修改 `plugins/bot_unified_runtime/config.py`：

- 增加 `bot_control_plane_features_file`。
- 增加 `bot_control_plane_super_admin_token_sha256`。

新增 `tests/test_control_plane_v1.py`：

- 树状状态继承与父级关闭测试。
- API envelope 测试。
- 普通 Bearer 写入拒绝测试。
- super-admin 功能关闭和审计测试。
- 配置 preview/set 与敏感键不回传测试。

### 8.2 已实际验证

本次实际运行过：

```text
ruff check（本次新增/修改控制面文件）：All checks passed!
pytest tests/test_control_plane_v1.py -q -p no:cacheprovider -p no:tmpdir
3 passed in 1.37s
git diff --check：通过
```

此前本会话已实际运行的局部基线：

```text
61 passed in 5.65s
```

注意：第一次用标准 pytest 运行时，Windows 临时目录清理返回 `WinError 5`，所以后续新测试使用工作区临时目录和 `-p no:tmpdir`。这不是全量测试通过证据。

### 8.3 当前未完成，下一 AI 不要重复误判

优先级顺序：

1. 先检查工作树和已有 WIP，尤其不要覆盖：`glossary.py`、`sender/onebot.py`、`sender/worker.py`、`campus.py`、`campus_store.py` 及对应测试。
2. 修正控制面 API 的实现质量：补统一 request_id 传播、写审计记录、reload/drain、配置变更历史、统一错误 envelope、日志事件注入。
3. 将 `runtime/capability_registry.py` 从 RouteKind/HelpTopic 投影扩展为全产品注册表：插件、子功能、指令、help、定时任务、自动回复、文档、控制动作、指标和数据资源全部登记。
4. 实现真实 `FeatureControlService`，不要让路由直接操作 store；接入 `/bot feature` 与 WebUI API 共用服务。
5. 实现完整结构化日志事件总线：Bot、NoneBot、SnowLuma、LLM、Pipeline、Sender、Scheduler 来源；七类 `debug/info/warning/error/success/critical/detail`；实时 SSE。
6. 接入真实 metrics/usage/trace 数据：audit、ledger、channel_health、diagnostics、send receipts、CPU/内存/队列/数据库采样；所有数据缺失返回 `unknown`，不能伪造 0。
7. 实现隔离 WebUI workspace：Prompt/上下文/人格/世界观/世界书/参考/知识库/记忆策略/供应商/渠道/模型/参数预览；默认不写生产、不出站。
8. 实现 real_session 受控模式：只允许 super-admin，默认预览，确认后经既有 Review + SendQueue 出站，完整审计。
9. 实现人格、世界观、世界书、参考、知识库、数据库、记忆库和 LLM provider/channel/model 的后端 service/API。
10. 实现白名单 `ControlActionRegistry`：重载、重连、排空、刷新、诊断快照等；禁止任意 shell、任意 SQL、任意原始 SnowLuma API。
11. 完成 CentralDecisionEngine Dispatcher 接管，清除直接发送和绕过 Pipeline 的路径。
12. 同步 `AGENTS.md`、`docs/HANDBOOK.md`、`docs/HANDOVER-2026-09-15.md`、`docs/README.md`、`docs/config-catalog-full.md`、`COMMANDS.md` 和 `docs/auto-facts.md`。

### 8.4 当前已知风险

- 新 API 目前是第一切片，不是完整 WebUI 后端；部分 endpoint 是明确占位返回。
- 当前新 router 将动态依赖直接写在 FastAPI handler 参数中，ruff 已通过，但后续应抽成正式 service/dependency 层。
- `/api/v1` 与旧 `/admin/api/v1` 的错误体目前尚未完全统一，不能提前声称全 API 契约完成。
- `FeatureStateStore` 当前使用 JSON 文件，尚未接入统一 Runtime store、跨进程锁、热 reload 事件和 drain 机制。
- `ControlPlaneAuditStore` 目前主要记录 HTTP 访问审计，尚未记录全部功能/参数变更字段。
- `docs/auto-facts.md` 在本会话开始时已有 `doc_sync --check` 漂移：代码事实是 75 topics，交接旧文档写 79；不要手改 auto-facts，收敛代码后运行 `scripts/doc_sync.py --write`。
- 本次没有创建 commit；当前分支仍为 `v0.0.1-alpha.2`，工作树包含本会话改动和既有 WIP，必须先按文件域核对再提交。
- 本地测试过程中生成的 `.cp-test-output.txt`、`.pytest-cp-fixed*`、`.tmp-cp-*` 等临时物因当前 Windows 权限清理失败仍可能存在；它们不是业务代码，清理前必须按绝对路径核验且不得碰 Runtime/Archive。

### 8.5 下一 AI 最短开工命令

先读：

```text
AGENTS.md
HANDOFF-NEXT.md（本节）
docs/HANDOVER-2026-09-15.md
 docs/design/control-plane-api.md
 docs/design/central-decision-engine.md
plugins/bot_unified_runtime/control_plane/features.py
plugins/bot_unified_runtime/control_plane/api/v1.py
plugins/bot_unified_runtime/control_plane/_app.py
 tests/test_control_plane_v1.py
```

然后只读确认：

```powershell
git status --short
rg -n "NotImplementedError|/api/v1|FeatureStateStore|send_|upload_" plugins/bot_unified_runtime tests
```

第一实施切片建议：补 `FeatureControlService` 与完整审计/事件接口，先写失败测试，再接 `/bot feature` 和所有已登记节点；不要先做前端。

## 9. 控制面核心续接：本轮实现与审查（优先于 §8 的旧状态）

详见 `docs/design/control-plane-core-status.md`。下一 AI **先读该文档 §1/§4/§5**，无需重新扫描全仓。

- 已落地 FeatureControlService，features API不再直写store；服务层校验super_admin和expected_version。
- 修复依赖/层级混合环、间接关闭受保护节点、reset版本倒退、写盘失败内存残留；增加无副作用preview、before/after/request_id审计及坏文件拒绝加载。
- v1统一请求ID与成功/错误envelope；超管令牌可读；读写令牌相同时禁写；认证OpenAPI明确Bearer与严格请求schema。
- 配置历史路由遮蔽修正；未接入的logs/traces/workspaces/config changes明确503，不再虚构创建成功；CPU百分比未采样不报0。
- 实测：控制面＋相关文档门禁120 passed in 6.46s；全plugins Mypy 272文件通过。全量快照6203 passed/3 failed，已补其中配置目录缺键；预算旧测试和源码data目录仍待处理。全树Ruff两个校园WIP问题与runtime-layout失败未隐藏。
- **仍未完成：全量注册、SQLite迁移、跨进程CAS、图级revision、/bot feature、生产执行门、ConfigControlService、SSE/usage/trace/workspace/人格等后续服务。** 管理API的enabled变化不等于生产Bot已经启停。默认注册表仍只是最小投影。
- 无commit、无生产重启、无真机出站；不覆盖其他WIP，不把本批写成可发布。


## 2026-09-15 后端协议扩展增量

新增 `control_plane/platform.py` 与 `control_plane/api/platform.py`：统一 PlatformStore（SQLite 资源、Trace、Usage、ModelCall）以及 WebUI `/api/v1` 资源协议。已提供人格、世界观、世界书、参考资料、知识库、记忆库、数据库、媒体能力、文件能力、搜索提供方的列表/详情/受控更新接口；Trace 查询与分段接口；Usage/ModelCall 写入与查询接口；日志级别受控写接口；能力协议目录。

已接入 `create_control_plane_app`，控制面实例自动装配 PlatformStore；新增配置 `bot_control_plane_platform_db`。资源更新使用版本字段，冲突返回统一 409；未知资源统一 404。

验证：Ruff（新增文件及控制面）通过；Mypy（控制面 29 files）通过；doc_sync 写入并检查通过。

注意：该增量是协议与基础数据层切片，不等同于全部专项能力已经接管生产链路。中央 Dispatcher、真实出站统一收编、SnowLuma 实时控制台、Persona 发布回滚业务策略、媒体处理器和安全文件网关仍需接入现有生产服务。
