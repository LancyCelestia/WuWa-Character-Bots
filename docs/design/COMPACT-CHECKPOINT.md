# Compact 续接检查点（最新，优先于旧交接正文）

> 术语说明：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](../snowluma-setup.md)。

## 置顶续接（2026-09-18/19）：统一收尾大波次续接锚

> 本锚写入时点 **2026-09-19 02:44+08:00**（CKPT 断点保险席）；内容全部实读自 `.superpowers/sdd/2026-09-18-unify-wave/`，席位状态以各 progress 文件自报为准。本节优先于下方全部历史续接。该文件不在 verify_hashes TRACKED_FILES（grep 实证），无需 --write。

**波次一句话**：渲染统一收口（canonical 裁决 C1-C13 值册登记→11 面数值收口→bridge decor_css/blobs_html 通水消灭手写壳层→机器门三层（v21r3 视觉门 gate01-09×11 面+test_token_supply_chain 供给链 6 测+WebUI layout-constitution 版式宪法门）→WAAPI 截图钉帧 PNG 字节确定性，验收判据=baseline-20260919-paused 字节等值）+ AxonHub 路线 B WebUI（Phase A 六页真数据 dashboard/calls/tokens/latency/affinity/logs+二期三页 知识库/插件/记忆图谱+控制面真数据端点群）+ 验收/台账/索引配套；用户 09-18 晚批准、09-19 追加四页需求。

**断点锚**：权威入口=`.superpowers/sdd/2026-09-18-unify-wave/master-plan.md`（mtime 02:23：Wave 1/2 席位表+09-19 四页新需求+Wave 3 INTG 细化工单七项）。席位交付证据=同目录 progress-*.md **30 份全落盘**（mtime 00:44–02:44，后缀 .md 省略）：
SAMPLES 00:44 · SPECS 00:50 · WEBUI 00:51 · DIRECT 00:57 · BACKEND 01:02 · FINMKT 01:17 ·
UNIVERSAL 01:19 · CORE 01:19 · ACCEPT 01:31 · GATES 01:35 · MISC 01:38 · ANIM 01:41 ·
PRECHECK 01:47 · PERF 01:52 · RESTPRE 01:53 · DOCSIDX 01:59 · WEBSPEC2 02:03 · SWITCH 02:04 ·
SUPPLY 02:12 · PRECHECK2 02:21 · REAPER 02:27 · BACKEND2 02:31 · GLASS2 02:33 · WEBUIFE 02:34 ·
LINTRES 02:35 · CAPEXEC 02:35 · UIREF 02:42 · MISC2 02:42 · GLASS3 02:44 · PRECHECK3 02:44
（台账草案=同目录 handbook-draft.md **LEDGER v2**，mtime 02:28，含 AGENTS #41 台账行草案+HANDBOOK §32 草案）。规格=docs/design/v21r3-render-closing-spec.md（00:46）、webui-axonhub-adoption.md（02:02）、webui-pages2-spec.md（02:42，UIREF 席已追加 §7 参照图对照 45 项判定）。

**在飞/收口快照**（02:44 实读）：
- **WEBUI-PAGES2 与 MOCKUI 无 checkpoint → 无断点，状态未知**：PAGES2 按 master-plan「等 WEBUI-FE 收口后派」；PRECHECK3 02:45 实测 scripts/webui_mock_server.py 尚未落盘。
- MISC2（四模板切换席，撞 1302 阵亡）=MISC3 接管续写**已完工**：七文件门禁 411 passed/0 failed；mermaid reduced-motion 两红根修（.card::before/::after 伪元素两斑复位+守卫置于 decor_css 之前）；样张 5/5 双渲 STABLE；error 卡 wash_blob_mix=24 豁免链闭环且与基线逐字节同。
- GLASS3 **完工（无断点遗留）**：usage_cards.py :284 平值填充归一 GLASS_FOOT 档 (0.66,0.46)，三件套 172 passed，样张 STABLE、字节差异仅本改动面；.footer-colored 0.98/0.88 主会话裁定登记 sanctioned 变体。
- PRECHECK3（只读三轮扫描）判定 **GO（条件放行）**：ruff 24→6→**2**（余 2 I001 机械，INTG 一条 --fix 清）；mypy 621 文件 **0 错**；渲染全域 14 文件 **588 passed**、cp+webui 族 386 passed；verify_hashes 15 项 DRIFT 待 INTG 统一 --write。两要害：①qx.json 新家 `domains/weather/assets/` 整目录 git 未跟踪（INTG 必显式 add，防第四次消失）；②usage_cards.py 真身（domains/ 362 行）未跟踪+旧路径 32 行 shim，提交须双 add。
- 其余近批已落盘终态（详见各自文件）：BACKEND2 三组只读端点完成（55+406 passed；runtime-layout FAIL=环境项 BOT_KNOWLEDGE_FILES 盘外文档缺失，非代码）；GLASS2 完成（P3-20/P3-21/增设门9）；REAPER+CAPEXEC 完成（conftest 模块边界两口收口：渲染池+cap-proto 执行器；linuxdo 缺样本转 skip）；LINTRES 完成（mypy model_router.py:439 清零+1 I001）；WEBUIFE=FE2 接管阵亡 FE，六页真数据+调色板类名机器门补齐（dist/index.html 916,916B）；UIREF 完成。

**收尾流程一行**：全部席位收口（含 PAGES2/MOCKUI 落盘）→ INTG 席（唯一收尾在飞席，master-plan Wave 3 七项：通水终验/四门禁全量实跑/哈希+doc_sync+command_catalog 三 --write 重录归零/样张按 baseline-20260919-paused 全量重跑字节终验/P3-19 玻璃字面切 token 裁决执行/遗留核销（ruff 2 I001、gate07 销账）/全席交付报告）→ 主会话 HANDBOOK/AGENTS 整合+总报告（LEDGER 草案 handbook-draft.md 备料）。

**铁律一行**：全批未 commit（禁 `git add -A`、逐文件显式 add、提交裁决权在用户）、未 push、未重启生产；1302 限流=落盘断点+指数退避+补位续跑，禁空等。

## 当前续接（2026-09-17）：V2.1 文档交付

本次用户改为“写入交接，让另一AI实施”。当前完整合同：[主规范](backend-v2-implementation-guide.md)、[产品扩展](backend-v2-product-extensions.md)、[验收矩阵](backend-v2-acceptance-matrix.md)，开工入口为[HANDOFF-NEXT顶部](../../HANDOFF-NEXT.md)。新增计费、自愈/待审补丁、好感度、占卜、全日程链、平台搜索、admin故障和媒体实战验收均已写入目标。

本轮未改生产代码/配置/数据或部署；好感度历史下降原因未重放，不擅自补偿。能用子代理就用子代理、时刻保持并行满载（限流为唯一上限，撞墙落盘保进度、结束即补派、前台派完即收不卡输出；2026-09-17 用户裁定，取代此前禁止子代理规则），保留WIP，统一一次收集真正缺失授权，已有授权范围连续执行。文档检查当时记在根目录 `progress.md`（未跟踪稿，2026-09-30 下午整树清空事故中丢失）；现状以门禁现算为准；下文是历史代码切片，不能据其旧测试宣称V2.1已实现。

## 最新串行续接：动作API修正与隔离工作区落地

本节优先于下文历史状态。**完整用户计划仍未完成；没有提交、推送、生产重启、真实模型调用或真实出站。**

### 实际新增/修复

- `control_plane/api/actions.py`：动作目录、详情、预览、执行、runs、取消使用公开Service。修复runs路由被遮蔽、状态码误映射、目录无version、确认参数误设必填、取消参数被忽略、protocol虚报未装配。
- `control_plane/actions.py`：16个running/unknown动作容量在SQLite事务内检查，跨实例不能突破；幂等重放先于容量检查。
- `control_plane/workspaces.py`：独立SQLite、拥有者权限、CAS、busy状态、短期消息/Prompt/预览、确认发送、幂等冲突、unknown回执、reset/delete、摘要审计、24小时清理和secure_delete。
- `api/workspaces.py`：工作区CRUD/messages/preview/send/reset/audit全流程。含原文的读写均仅允许超管拥有者。
- `sandbox.py`：受信人格系统层、不可信资料引用层、独立对话历史、provider/channel/model三元组选型、输出预算和用量记录；拒绝未知资料及工具执行，不使用生产记忆/好感/SendQueue/ModelRouter健康账本。
- `factory.py` + `_app.py`：默认工作区装配、按分钟清理；每次预览读取当前默认人格/模型配置，启动不调用模型。未指定人格时使用配置中的默认profile，而非硬编码不匹配的ID。
- `config.py`、`.env.example`、配置目录：新增 `bot_control_plane_workspaces_db`，沿用Runtime路径映射。实际 `.env` 未更改。
- `api/protocol.py`：动作严格请求模型；API路径与行为由认证OpenAPI暴露。
- 新文档：`control-plane-services.md`、`control-plane-workspaces.md`。

### 已实跑证据

- 动作接口回归首轮：5 failed / 2 passed，定位5个真实接口问题；修正后相关组合31 passed。
- 工作区/动作/生成适配最终定向组合：**33 passed in 10.52s**。
- 工作区/HTTP/默认装配/生命周期组合：53 passed。
- 全量第一次：**1 failed, 6677 passed, 9 skipped, 3 xfailed, 1 warning in 253.03s**；唯一失败为 `test_doc_sync_auto_facts_in_sync`，新增文件/测试导致事实册未重生成。随后运行doc_sync --write修正；最终全量结果另列下方，不能把旧全量当新证据。
- Ruff：`ruff check --no-cache bot.py plugins tests scripts` → All checks passed。
- Mypy：全plugins → Success: no issues found in 290 source files（另有既有未检查untyped函数提示）。
- 本机离线100轮message+reset测量：P50 18.854ms、P95 33.838ms、tracemalloc净增5096B/峰值11428B、SQLite49152B、结束消息0条。**只证明这一短期工作负载，不证明全项目性能或长时无泄漏。**
- runtime-layout目前FAIL：前序py_compile遗留3个__pycache__目录及5个pyc，共8项；清理命令被工具策略阻止，未通过替代工具绕过。没有改检测器掩盖失败，也没有删除任何生产数据。

复跑：固定解释器 `..\ChatBot_Runtime\venv\Scripts\python.exe`，设置PYTHONDONTWRITEBYTECODE=1、BOT_AUTOSYNC=0、PYTHONUTF8=1；pytest -q --basetemp=$TEMP/唯一目录 -p no:cacheprovider。全量日志 `%TEMP%/cp-workspaces-full-suite.log`。

### 仍需实施（不能当成完成）

1. 工作区默认只提供配置中的默认人格与单模型；世界观/世界书/知识库动态选择、结构化隔离记忆、完整provider/channel/model目录尚未装配。显式资料字典注入只是适配能力。
2. real_session端口只有离线测试，生产Policy/Review/Renderer/SendQueue适配器尚未连接；没有真实出站验收。
3. 动作服务默认生产注册仍未连接；参数schema首版仅空对象。重启/重连/队列运维动作不能声称可用。
4. 全局Usage/Trace、人格版本、世界书/知识/记忆/数据库管理接口、完整细分注册、reload/drain、中央Dispatcher、统一出站、多媒体/文件/搜索/代码网关仍在总计划待办。
5. 前端不实现；不要把未完成的接口标记为available。生产NoneBot/Telegram长期健康仍unknown。

### 下一步应直达的位置

先看以上两个新协议文档及工作区真实发送端口，接生产Pipeline/SendQueue前需要补结构化Trace和可复核delivery receipt。不要重做本轮动作API和工作区CRUD，也不要复制生产记忆实例给sandbox。全量/门禁失败项必须保留在发布阻断列表。



## 最新串行增量：细分执行开关、日志采集、Telegram 网络韧性

**优先级：本节高于下文历史检查点。2026-09-17 用户更新：能用子代理就用子代理，时刻保持并行满载，以限流为唯一上限；撞限流墙先落盘保进度，子代理结束立即派遣新的子代理补位；主会话不占前台，派完即收、留对话空间（取代下文旧"禁止新子代理、单线程串行"规则）。不提交、不推送、不重启生产。完整后端仍未完成，不可发布。**

### 本批实际变更

1. `control_plane/features.py`：新增细分种类与 implementation_ref/reload_strategy/privacy_level 元数据。
2. `control_plane/services.py` + `runtime/feature_gate.py`：整图服务快照、不可变映射、异步离环获取、故障关闭；旧任务不被强杀，新事件看到跨实例 SQLite 更改。
3. `runtime/feature_catalog.py` + `__init__.py`：15 个细分开关实际接线；全部 11 个生产 normalizer 调用注入开关。覆盖文件读取、audio/TG/reply、最近图、转发、视频、被动好感、复读、表情三类、收库、戳一戳 reply/poke_back。逐项见 `control-plane-registry.md`。
4. `runtime/capability_registry.py`：补 `bot.poke`，修正已有戳一戳被新 Pipeline 功能门判 `feature_unregistered`。回复/反戳继续受原配置和冷却约束；直接平台动作统一出站仍未完成。
5. `control_plane/log_collectors.py`：stdlib/NoneBot Loguru → 结构化摘要总线；不保存正文/栈/路径；自有 handler/sink 启停、发布错误不抛回业务、无总线递归。
6. `_app.py` lifespan 接入采集器；`events.py` 增加 Telegram/Mail 来源；`api/events.py` 返回真实 collectors 状态；`api/v1.py` 更新 protocol 覆盖范围。NapCat 仍 not_connected，raw_content=false。
7. 用户新报启动问题：附件显示 Telegram 经代理 TLS ConnectError，不是已证实的 NoneBot 退出。只读探测 8080/3001/7890 在监听，无 Token Telegram 公共首页经代理 HTTP 302。
8. `bot.py` 移除全局 poll monkeypatch，注册 `scripts/telegram_resilience.py` 返回的子类；覆盖 getUpdates 内部网络失败与启动重试，保留 offset/取消/原事件处理，3→60s 退避，不重放出站，不隐藏 409/鉴权/配置错误。未修改 .env/代理/证书/生产进程。
9. 新测试：`tests/test_runtime_subfeatures.py`、`tests/test_control_plane_log_collectors.py`、`tests/test_telegram_resilience.py`；更新 `test_control_plane_events.py` 来源契约。未重录黄金哈希。

### 实跑证据

- 子功能/服务/SQLite/API/戳一戳组合：183 passed。
- 日志/事件/API/Telegram/守护/子功能组合：72 passed, 1 warning（新增最后的真实 Loguru sink 用例随后进入全量）。
- Telegram 新分类与真实安装适配器测试：12 passed；offset 保持、网络恢复、取消、不重复出站、409 不被掩盖。
- 新代码 Ruff 定向通过；全仓 Ruff 返回通过但沙箱无法枚举三个既有拒绝访问临时目录，源码目录会另跑显式范围检查。
- Mypy：285 source files 通过；doc_sync 因新增测试数变化已 --write，command_catalog/verify_hashes --check 已通过。
- **本批全量 verified：6647 passed, 9 skipped, 3 xfailed, 1 warning in 225.68s；退出码0。后续新增模块不得沿用本结果作为新代码证据。**
- 全量日志：`%TEMP%/cp-serial-full3.log`，临时测试根 `%TEMP%/cp-serial-full3`。

复跑（固定项目解释器，关闭主仓 autosync）：

```powershell
$py='C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\python.exe'
$env:PYTHONDONTWRITEBYTECODE='1'; $env:BOT_AUTOSYNC='0'; $env:PYTHONUTF8='1'
& $py -B -m pytest -q --basetemp="$env:TEMP/cp-serial-full3-repeat" -p no:cacheprovider
& $py -B -m ruff check --no-cache bot.py plugins tests scripts
& $py -B -m mypy --cache-dir "$env:TEMP/cp-resume-mypy" --explicit-package-bases --ignore-missing-imports plugins
& $py -B scripts/doc_sync.py --check
& $py -B scripts/command_catalog.py --check
& $py -B tests/verify_hashes.py --check
& .\scripts\dev.ps1 -Task runtime-layout
```

### 当前未完成与下一步

- `subfeatures_complete=false`、`reload_drain=false`：不把枚举和局部接线当作全产品收编。
- 日志仍是固定类别摘要，不是完整控制台；NapCat 真实连接、POST logs/level、正文短期存储、联查与下载未完成。
- Workspace、Trace、人格版本、模型 provider/channel/model 规范、白名单动作、中央 Dispatcher、全部 Review/SendQueue 收编及多媒体/文件/代码网关仍待实施。
- Telegram 修复为源码+离线 verified；实际重启后恢复和生产鉴权/长时网络可用性 unknown。不要为查看效果擅自重复启动第二个 Telegram 长轮询实例。
- 前端不制作；API 消费方应先读取 /api/v1/protocol，只启用已提供能力。
- 后续优先推进白名单动作/隔离工作区的服务与持久化，再接协议；不要重做本批开关、事件总线和已有配置服务。

---

## 历史续接增量（优先于下方历史检查点）

**执行规则更新（历史存证，已被 2026-09-17 用户新裁定取代）：现有两名子代理已完成并关闭。当时规则"禁止再派新子代理、主会话单线程串行实施"已作废；现行规则=能用子代理就用子代理，时刻保持并行满载，以限流为唯一上限，撞墙落盘保进度、子代理结束立即补派，主会话派完即收、不占前台。**

### 本次已落地

1. **控制面路径根治**：`config.py` 的统一 `path_fields` 加入 config/events/features 三个 SQLite 路径与 legacy features JSON；补 DATAFIX 路径回归，E2E 白名单测试改用 tmp_path 数据根。定向 23 passed。
2. **帮助和路由**：`echo.py` 补功能管理 detail 四要素、查询/预览/修改权限；`runtime/aliases.py` 补 feature/功能管理归一与昵称引导；`capability_registry.py` 同步帮助能力元数据。没有增加豁免台账。
3. **测试不再改写主仓生成物**：`test_autosync_hook.py` + `_autosync_fixture.py` 把真实三种生成器及子 pytest 会话放到 TEMP 镜像；逐文件字节及 mtime 断言确保主仓 WIP 不被重写。生产 autosync 钩子行为未改。
4. **资源指标服务**：新增 `control_plane/resources.py`，通过 `_app.py` 注入，v1 overview/resources 共用；`api/protocol.py` 增加资源响应 DTO，`/protocol` 明示按需采样、仅当前进程、无历史。CPU 时间/差分、RSS、OS 线程、进程运行时长可查；首次/故障/未接入数据明确 unknown。API/生命周期/注册组合 69 passed。详见 `control-plane-metrics.md`。
5. **错误卡旁路审查**：首次新全量为 6573 passed / 4 failed，定位到 A18 测试异步渲染跨用例污染。通过 RuntimeError + capability exploded + 你好 重算 digest，精确匹配 `error_1efbb1ed211e.png`，不是好感度用例自身写入。
   - `runtime/error_report.py` 原先 docstring 承诺 runtime_paths，实际却直接 `Path(resolved_dir)`；现已调用统一 resolver。
   - 冷却正文/兜底原本各抽一次随机话术，现复用一次抽样结果。
   - 两个旧测试由单句硬编码改成 12 句逐句参数化、逐字断言正文和兜底一致，没有删除语义门禁。
   - A18 测试保留真实错误卡编排，只替换昂贵渲染后端/路径为独立 TEMP，并在撤销测试替身前排空后台任务。
   - 新增路径/随机一致性测试先 4 failed，修后相关回归 89 passed / 1 skipped。

### 审查与验证状态

- Ruff：`python -B -m ruff check --no-cache plugins tests scripts` → All checks passed。
- Mypy：必须使用 `--explicit-package-bases --ignore-missing-imports plugins`，不要只传插件子目录（会造成模块双名报错）；最新 284 source files 通过。
- `doc_sync --check`、`command_catalog --check`（76 topics）、`verify_hashes --check` 均通过。
- 哈希审查只更新本批新增帮助对应的 echo.py 源码签名（新值 `13cdb078d9c0e10193a7c50a89ef3b1e1dca5da9947b2df78c78e89315398fb4`）；其他既有签名包括 renderer.py 的 WIP 签名保持不动。没有重录视觉模板来掩盖失败。
- 资源缓存实测 1000 次：P50 0.0236ms、P95 0.0290ms、max 0.0454ms；10000 次后 tracemalloc retained +2982 bytes、peak 7247 bytes。这是本机缓存快照微基准，不是整个 Bot 的 P95 或长期无泄漏证明。
- **最新全量 verified：6603 passed, 9 skipped, 3 xfailed, 1 warning in 242.11s；退出码 0。** 唯一 warning 来自上游 Mail adapter 的 Pydantic class Config 弃用，未改第三方依赖。
- **runtime-layout verified：PASS，source_generated_dirs=empty，python_bytecode=absent。** 在全量结束后验证，不是仅清理后/测试前的快照。
- 复跑命令（均使用既定 Runtime venv，不用系统 Python）：

```powershell
$py='C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\python.exe'
$env:PYTHONDONTWRITEBYTECODE='1'; $env:BOT_AUTOSYNC='0'; $env:PYTHONUTF8='1'
& $py -B -m pytest -q --basetemp="$env:TEMP/cp-resume-full2" -p no:cacheprovider
& $py -B -m ruff check --no-cache plugins tests scripts
& $py -B -m mypy --cache-dir "$env:TEMP/cp-resume-mypy" --explicit-package-bases --ignore-missing-imports plugins
& $py -B scripts/doc_sync.py --check
& $py -B scripts/command_catalog.py --check
& $py -B tests/verify_hashes.py --check
& .\scripts\dev.ps1 -Task runtime-layout
```

全量日志：`%TEMP%/cp-resume-full2.log`（最新通过）；`%TEMP%/cp-resume-full.log`（前一轮4失败，保留定位证据）。缓存用TEMP、测试禁主仓autosync；这是离线pytest全量证据，不声称运行了会写Runtime测试缓存的 `dev.ps1 -Task test` 包装。未执行生产 e2e --execute。

### 源码残留处理记录

先只读查询已配置生产 SendQueue，确认错误卡文件名没有任何引用，且生产配置路径不在源码树；随后备份到 TEMP、逐文件 SHA256 核验后才清除源码 `data/`。不修改生产队列/Runtime 数据。

- 旧残留（config SQLite + error PNG）备份：`%TEMP%/chatbot-source-residue-20260916-105bc45f27ad4fd0bdb5e6de3d0758c9`，含 manifest。
- 本次全量 A18 复现 PNG 备份：`%TEMP%/chatbot-async-error-residue-6f1b0cbfec78427b9b0914e6cd76c07b`，含 manifest。
- runtime-layout 曾发现 628 个 Python 缓存路径；仅清理源码范围内 23 个 `__pycache__` 目录。全量结束后再次 runtime-layout PASS，没有再生字节码或源码 data。
- `plugins/bot_unified_runtime/sources/data/qx.json` 保留；未扫删 Runtime/Archive，没有 commit/push/生产重启或真实出站。

### 当前执行状态

两名子代理已关闭；两轮全量 exec 均已 exit，类型检查已 exit，无待整合代理或在跑验证进程。未创建自动化/后台跟进。

### 下一步与尚未完成

先查看本节末尾最新全量/边界结果，再沿已批准计划继续全量细分注册和实际门禁，不从零设计。尚未完成：细分节点全覆盖、资源 reload/drain、真实 NapCat/NoneBot 采集、完整结构化 usage/trace、定时资源历史、Sandbox/real_session 工作区、人格版本、世界书/知识/记忆/数据库安全服务、供应商/渠道规范化、白名单动作、中央 Dispatcher、统一反戳与所有出站、多媒体/文件/代码接口。

**没有待用户回答的新问题；完整后端仍未完成、不能发布。** 下方“5项失败”和旧恢复步骤只保留为历史，不应重复实施已经修过的项。

---

## 用户目标与当前暂停点（历史）

用户不更换AI，要求把已批准的守岸人Bot后端/WebUI协议计划持续做完，只有真正需要产品决策时才提问。最新指令是“迅速收尾，我需要compact压缩”。因此此处仅冻结检查点，**不是任务完成**，恢复后直接修下列失败并继续，不要重新要求批准总计划。

固定规则：后端优先，不写前端页面；未来前端用AxonHub模板。REST `/api/v1` + SSE；SQLite + 事件归档；按业务能力显式注册，不为每个内部函数设置开关；写入super_admin、CAS、审计；禁止任意shell/SQL/路径/原始NapCat API。默认sandbox不得写生产/真实出站。保护人格核心、控制面、安全审计、最低出站。现有Runtime/Archive不可擅自删除。

## 已实际落地（代码未提交、未部署）

### 功能控制与运行时
- `control_plane/features.py`：图校验、protected字段、版本、preview、回滚、审计；保留JSON兼容。
- `control_plane/sqlite_features.py`：状态/审计/graph_revision同事务；跨实例CAS；`expected_revision`必填；只读快照；一次性legacy导入，原JSON保留、已有SQL不覆盖。
- `control_plane/services.py`：FeatureStore Protocol + FeatureControlService；节点版本和SQL图修订双校验；读故障503；权限在服务层校验。
- `control_plane/factory.py`：LazySQLiteFeatureStore，装配不读库；坏DB不让整个Bot装配崩溃，业务fail-closed、保留恢复能力。首次查询初始化SQL/导入旧JSON，尚无生产迁移实测。
- `runtime/feature_catalog.py`：Route声明与补充内部能力声明投影成树；`runtime/capability_registry.py` 新增CONTROLLED_INTERNAL_CAPABILITIES。
- `runtime/feature_gate.py` + `runtime/pipeline.py`：同步/异步主链在policy/限流/幂等/能力调用前守门；未知能力/查询故障阻断；受保护恢复能力继续后续权限校验。
- 插件 `__init__.py` 已装配ProductFeatureGate；`capabilities/feature_control.py` + `/bot feature list|get|enable|disable|reset|preview` 已接同一service；实际跨实例API→SQL→Pipeline阻断测试已通过。
- **覆盖范围仍是主能力，不是全部细分子功能**。早于Pipeline的文件读取、语音预转码、直接回戳/定时出站等仍待收编。不要宣称所有插件/子功能已完整受控。

### 参数控制
- `control_plane/config_store.py`：按实例SQLite覆盖、tombstone、revision、CAS、审计；旧JSON参数一次性导入，reset不会复活旧值。
- `control_plane/config_service.py`：schema/list/get/preview/set/reset/reset_all/changes；写入super_admin+expected_version；reset_all单事务。
- `runtime/settings.py`：可选config_backend，五个覆盖读写方法实际消费SQL；manager cachekey包括DB路径；提交成功才通知监听；其他昵称/人格/模型JSON数据仍保留旧路径。
- API与`/bot runtime` 已用同一服务和同一个runtime_settings对象；API更新能立即影响实际get并触发监听，命令写能通过API读到，已实测。
- 参数、核心人格switch/probability、模型写操作、Bot昵称add/remove收紧到超管（用户自助identity称谓接口未动）。
- DTO和审计递归脱敏凭证、Bearer/Cookie、绝对路径；数值/bool保持类型，MAX_TOKENS不会错当密钥。旧审计读取再次脱敏，不改写历史。
- **资源reload尚未实现**；RESTART_REQUIRED_KEYS继续拒绝热改。不能把此切片称为“全部参数热更新”。

### 事件、统计和生命周期
- `control_plane/events.py`：七类结构化诊断事件、SQLite查询、有界非阻塞队列、写线程、过载/失败计数。
- `api/events.py`：认证logs/sources/stream/{id}；SSE Last-Event-ID续传、心跳、过期410、断开取消；统一错误envelope。
- `_app.py` 按events_db装配路由，lifespan启停bus，控制面HTTP访问发布结构化事件。
- **不是原始控制台**：message为安全分类模板，仅白名单details/summary；NapCat/NoneBot原始日志采集器未接。默认事件保留窗口10000条不等于最终长期归档。
- `control_plane/metrics.py`：只读ledger聚合overview/models/sessions/trends，四类token区分complete/partial/unknown；session HMAC；UTC趋势；查询有预算。已接metrics overview/models/sessions/tokens/trends。
- **重要口径**：旧model_router把provider_id写成registry route id，因此供应商分组明确标记`provider_identity_quality=legacy_unverified`，不是已核实vendor。模型用actual_model；attempt/failover仍unknown，不解析展示字符串造数据。
- `control_plane/lifecycle.py`：按已有B4 §3.2同进程、独立loopback 8742 uvicorn，startup/shutdown有界、捕获SystemExit、不接管Bot信号。默认关闭。插件入口已接生命周期，app创建惰性且注入真实runtime_settings/feature_service。

### 协议/文档
- `api/protocol.py`：严格Feature/Config请求DTO、通用envelope及强类型Feature响应schema。
- `api/v1.py`：认证OpenAPI含Bearer与错误schema；`/protocol` 返回live/storage_only、服务是否接入，明确subfeatures_complete=false。未实现workspace/trace/action不假报可用。
- `config.py`、`.env.example` 补控制面enabled/host/port/token/allowlist及features/config/events DB配置。
- 新增帮助“功能管理”，当前76 topics。**帮助规范仍有失败，见下节。**
- `scripts/command_catalog.py --write` 实际只生成docs/command-catalog.md，不会生成COMMANDS.md；本轮COMMANDS.md人工追加对应说明，后续应收敛生成机制。

## 最新全量证据：必须先处理的5个失败

最近全量离线命令：Runtime venv Python `-B -m pytest -q --basetemp=<独立TEMP> -p no:cacheprovider`，`PYTHONDONTWRITEBYTECODE=1`、`BOT_AUTOSYNC=0`。

**5 failed, 6548 passed, 9 skipped, 3 xfailed, 3 warnings in 311.66s**。

1. `tests/test_e2e_acceptance.py::test_group_whitelist_gate_blocks_non_white1`：conftest已精确归因，此测试新建源码`data/control_plane_config.sqlite3`。
   - 优先检查该测试约228行、scripts/e2e_acceptance.py的Config/manager组装，以及settings.py新backend_db路径解析。
   - 很可能新默认config DB字段在原测试的临时路径覆盖之外；**先修生产路径解析及测试隔离，不能删守卫或仅清文件掩盖写入者**。
   - 本轮曾担心默认DB会碰到Runtime；当前直接证据只证明写了源码data/。是否另有Runtime新文件未核验，不得声称污染或清理了生产库。
2. `tests/test_help_deep_teaching_n2re.py::test_every_detail_covers_four_elements`：新“功能管理”detail缺“参数”（当前只有一句话）；应按既有四要素/分区扩充detail。
3. 同文件`test_permission_annotations_match_visibility`：admin_only条目必须明确含“仅管理员”；新条目未用该字面。
4. `tests/test_no_source_tree_data_writes.py::test_source_tree_has_no_data_dir`：源码data/残留。此前有`data/cards/error_1efbb1ed211e.png`（2,375,068字节），本轮新增上面的config SQLite。**未删除、未备份、未核验是否有生产队列引用。** 按AGENTS规则备份和确认后再处理；勿碰Runtime/Archive或sources/data/qx.json。
5. `tests/test_trigger_bidirectional_gate.py::test_help_to_route_gate_matches_ledger`：新help aliases `feature`、`功能管理` 没有对应路由触发面，新增两项缺口。应补正确路由/帮助触发绑定，不能扩容豁免台账掩盖问题。

另外：全量套件中的`test_autosync_hook.py`自行启用autosync，所以即便外层BOT_AUTOSYNC=0，也出现警告：**自动重录了tests/render_hashes.json中的echo.py哈希**。这是实测副作用，不是手动已核准新黄金基线；恢复后必须审查该diff，禁止盲目接受/覆盖其他已有WIP的hash变化。

## 其他验证（注意先后顺序）

- 功能/SQL/SSE等组合：198 passed in 19.52s（早于最终Config/lifecycle/metrics整合）。
- Config/API/自然语言：73 passed in 8.66s。
- 最新单独运行时接线测试：9 passed in 2.98s（之后又增加了入站ID登记测试，尚未单独复跑该新增测试）。
- 旧预算断言150→300与两处校园lint最小修正：33 passed in 2.64s（不回退源码300默认，边界/性能断言未删）。
- 最近全plugins Mypy：`Success: no issues found in 283 source files`，早于最后少量接线/协议修改，恢复后重跑。
- `ruff check --no-cache plugins tests scripts` 曾All checks passed；最后又追加过测试，需要再跑。
- 子代理专项：SQLite 66 passed；事件21 passed；生命周期33 passed；配置及相关回归286 passed；metrics95 passed。均非全量发布证据。
- 本轮未执行真机e2e --execute，无生产重启、commit或push。

## 恢复后最短路径

1. 先读本文件，不要复述/重做总计划。`git status --short`；工作树原有glossary、sender、campus等WIP必须保留。本轮对campus只修日志pass及测试dict字面量，其他原WIP没有回退。
2. 修上述5个失败和生成物副作用，先定向回归，再全量；不可提高阈值或跳过测试。
3. 补Controller生命周期/配置/指标组合审查，特别是新增DB默认路径与只读/写入边界。
4. 继续全产品子功能/配置/命令/help/document注册和实际消费接线；Dispatcher仍NotImplementedError，未切engine_only。
5. 再做正式日志适配器、完整usage/trace/资源采样、隔离workspace、人格/世界书/知识/记忆/数据库服务、模型provider/channel/model规范、白名单动作和多媒体/文件/代码网关。
6. 原文/摘要/审计保留期限尚无具体用户裁定，后续真正实施归档清理前再询问；目前没有向用户发出待答问题，也没有获得新清理授权。

## 进程/代理状态

本轮4类子代理均已完成并关闭，没有未整合代理文件。已知统一exec会话：74025全量pytest已终止并返回完整失败结果；32155已exit0；74396 Mypy已exit0。用户打断后没有重启测试；未创建后台自动化或额外任务。其他更早临时session如无法确认，用只读状态检查，别按进程名杀生产Bot。

复跑解释器固定：
`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\python.exe`

Windows沙箱TEMP的pytest常报PermissionError；之前通过受控提权、独立TEMP得到有效结果。禁止为了方便改用生产数据路径。


## 2026-09-16 续接增量（本会话）

- 修复 `control_plane/api/llm.py` 的 Ruff B008 门禁；新增 provider/channel/model 按稳定 ID 的详情查询接口，资源不存在返回统一 404，不泄露凭证。
- 重新实跑：`ruff check --no-cache bot.py plugins tests scripts` 通过；`mypy --explicit-package-bases --ignore-missing-imports plugins` 通过（291 files）；`doc_sync --check`、`command_catalog --check`、`verify_hashes --check`、`git diff --check` 通过。
- Telegram 日志中的 `httpx.ConnectError` 属于 2026-09-16 03:16 的旧进程输出；当前代码已使用 `ResilientTelegramAdapter` 在 getUpdates 读取边界退避重试，禁止出站写操作自动重放。未重启生产，因此尚未做真机在线验证。
- 焦点 pytest 本轮仍受 Windows 临时目录 ACL/清理问题影响；失败发生在测试临时目录与 SQLite 临时文件写入，不是业务断言：`PermissionError WinError 5` / `sqlite3 unable to open database file`。不能据此宣称焦点测试通过。
- 当前仍未完成：完整 Trace/Usage/Persona/World/Knowledge/Memory/安全文件网关/中央 Dispatcher/统一真实出站，以及生产重启验收。


## 2026-09-15 后端协议扩展增量

新增 `control_plane/platform.py` 与 `control_plane/api/platform.py`：统一 PlatformStore（SQLite 资源、Trace、Usage、ModelCall）以及 WebUI `/api/v1` 资源协议。已提供人格、世界观、世界书、参考资料、知识库、记忆库、数据库、媒体能力、文件能力、搜索提供方的列表/详情/受控更新接口；Trace 查询与分段接口；Usage/ModelCall 写入与查询接口；日志级别受控写接口；能力协议目录。

已接入 `create_control_plane_app`，控制面实例自动装配 PlatformStore；新增配置 `bot_control_plane_platform_db`。资源更新使用版本字段，冲突返回统一 409；未知资源统一 404。

验证：Ruff（新增文件及控制面）通过；Mypy（控制面 29 files）通过；doc_sync 写入并检查通过。

注意：该增量是协议与基础数据层切片，不等同于全部专项能力已经接管生产链路。中央 Dispatcher、真实出站统一收编、NapCat 实时控制台、Persona 发布回滚业务策略、媒体处理器和安全文件网关仍需接入现有生产服务。


## 本轮继续增量

- 新增 `control_plane/api/platform.py` 生命周期、知识库搜索/重建、记忆审核/遗忘/重建、数据库 schema/health/stats、受控文件读取和媒体分析协议。
- 新增 `control_plane/file_access.py`：工作区 allowlist、禁止绝对路径、扩展名白名单、大小上限；纯文本和代码类文件可直接读取，Office/PDF 返回 parser_required，不伪造解析结果。
- 新增 `control_plane/dispatcher.py`：统一 route → review → send 门面及 PokeInteractionService、ReactionService、MemeService。
- 默认控制动作已注册 13 个白名单 ID；真实执行器尚未伪造，未接适配器时明确返回 `degraded/adapter_not_connected`。
- 控制面 runtime-attached 时将 NoneBot Loguru logger 接入 `ProcessLogCollector`，不直接读取控制台文件。
- 已有搜索引擎 `sources/web_search.search_async` 已接入 `/api/v1/search`。
- 验证：新增控制面文件 Ruff、Mypy、compileall 通过；全仓 Ruff 通过。
