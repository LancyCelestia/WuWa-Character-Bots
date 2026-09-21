# 交接提示词（2026-09-21 · 贴给下一个 AI）

用法：全文粘给新会话，或说「读 `HANDOFF-PROMPT-20260921.md` 全文并照做，然后向我复述你的理解」。
项目全貌以 `AGENTS.md` 为入口，历史总账以 `docs/HANDBOOK.md` 为入口。与它们冲突时以它们为准并当场指出冲突。

## 一、开工前必读（按序，别跳，别从 AGENTS 顶部那堆横幅开始考古）

1. `AGENTS.md` 第一部分「工作区规则」——10 条铁律，必读不是浏览。
2. `.superpowers/sdd/2026-09-21-fix-wave/master-plan.md` **§捌**——本波交接快照：13 项逐符号四态、已验证/未验证边界、未 commit 清单、禁碰面、复跑命令簿、门禁真值。
3. 同目录 `uncommitted-inventory.md`——未提交全量清单（机器生成）。
4. `docs/audit-20260921-decisions.md`——十三件事大白话版：出什么坏事→为什么→改完看到什么→她回哪个字母。
5. `AGENTS.md` 第六部分台账 **#47**——本波总账与哈希指针。
6. `docs/audit-20260921.md`（含第 9 章）——定罪依据，只在追究"某条为什么被判错"时查。
7. 待补件：`docs/audit-20260921-commands.md`（真机验收清单，G 组未全）、`docs/acceptance-manual.md` §6.6.12。

## 二、硬约束

1. **不 commit、不 push、不重启、不调 TTS `/control`**。提交与重启权在她手上（生产进程管理员权限启动）。
2. **不碰** `.env`、`ChatBot_Runtime/**`、`domains/weather/assets/qx.json`（内置资产，历史上被误清 3 次）。
3. **集中面只由主会话串行改**，子代理禁碰：`config.py`、`.env.example`、`docs/config-catalog-full.md`、`runtime/settings.py` 的 `SETTABLE_KEYS`/`RESTART_REQUIRED_KEYS`、生成物三件的 `--write`。席位要新键就把「键名/类型/缺省/是否热更/校验器/语义」写进自己日志的交接段。
4. **说「已完成」必须给提交哈希，或可复跑命令 + 实跑输出**，否则按未完成记账。「设计已出」不算完成。
5. **红先归因再决定修不修**。工作树共享且脏，未提交项绝大多数属先前五波与并行会话；动文件前 `git log`/`mtime` 判归属。**不代他波降基线、不顺手修别人的红。**
6. **叙述文档禁手写会漂移的计数**（字段/topics/别名/模板/域/路由/库/交付物数），一律指向机器册 `docs/auto-facts.md`；必须留旧数字就标「当时值」。由 `test_documentation_consistency.py::test_narrative_docs_defer_volatile_counts_to_machine_ledger` 执法。
7. **跑测试必带**（否则污染源码树或被 GBK 解码坑）：
   ```bash
   export PYTHONIOENCODING=utf-8
   PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest <件> \
     -p no:cacheprovider --basetemp="$TEMP/<名>" -q
   ```
8. **根 `__init__.py` 同文件多主**：`:5032` campus 坐标被 `test_outbound_registry_campus_coordinate_is_live` 按 live 行号实比、`:5252-5268` 紧急域 fail-open 注释、`:5271-5301` sync_drift 接线、`:4153` 占卜待接线点。**插入必须落在不顶漂既有坐标处**，改前先读 `tests/test_doc_link_integrity.py` 与 outbound 坐标棘轮。
9. **改代码必须重启才生效**。报告时把「线上现行为」和「代码行为」分清。

## 三、她怎么工作（决定你会不会被推翻）

- 唯一决策人，不写代码，盯得细。会问「哪条命令、什么输出、几个红」。
- **看不懂就重来**：找她拍板必须给大白话 + 字母选项 + 一句推荐，不要编号墙、行号墙、表格轰炸。
- **六条统一尺子**（评审过/不过线）：统一消息、协议、架构、入口、口径、产出——**所有内容走中央调度层，TTS 也不例外**。她据此**推翻过「退役中央壳」的建议**：方向是全部接入，不是删掉。
- 要**并行满载**（能用子代理就用，限流是唯一上限；撞墙先落盘保进度、结束即补派），同时要求**文件面互斥切分**、**补丁待审不自动部署**。
- 要**恶毒自攻式评审**：交付前自己派评审代理攻一遍，抓到 Critical 自己修，并如实记「哪条被推翻」。她欣赏自己打脸，讨厌粉饰。
- **视觉裁定优先**：改卡片/渲染先给前后对比图，她的眼睛比指标大，她说丑就回滚别争。
- **人格与内容红线**：守岸人语气（去 AI 味，见 `.agents/skills/shuorenhua`）；好感度任何档位不攻击、不强硬；好感度算法说明**只定性、绝不展示固定加减数值**；R-18 按 2026-09-17 政策放开到私聊成年自愿 + **六条硬线写死**（残害身体/窒息/侮辱性调教/未成年 fail-closed/暴力SM/非人化），任何设定不可架空。
- 不指责她、不教育她、不用「要不要继续」拖延。判断完再报。**范围一变就重新要写权限。**

## 四、现役状态（计数以机器册为准）

**门禁真值**（上一会话实跑；本节只有终跑那行被本会话从 `finalclose.log` 尾部核过，其余未复跑）：
全量 **1 failed / 10961 passed / 13 skipped / 27 xfailed / 2 xpassed / 613.41s**。唯一红 = campus 坐标棘轮（登记 5027 ≠ 活体 5032，其间有本会话之外的编辑）⇒ **不代改**，归该门 owner。`runtime-layout` PASS；生成物三件 `--check` CLEAN；全树 ruff 21 错 / mypy 7 错，**本波 0**。

**十三项四态**
- 已落码且复跑绿：①凭证外泄咽喉 ②繁简换库（zhconv 1.4.3）④TTS 退避提交点 ⑤路由拆位+抢占门 ⑦好感度 v7 重写 ⑪占卜两套合并 ⑫sync_drift 救活 ⑬文档计数治理。
- 已落码但**灰度关、线上零变更**：⑥记忆总线 v2（`bot_memory_bus_enabled=False`）、⑦好感度 v7（`bot_affinity_v7_enabled=False`）。关态逐字节旧行为。
- 半成品挂账：③紧急信息全预警谱——9 族 31 类可用、断链已修，但注册表驱动定级未做，10 用例 / 20 实例挂 `xfail(strict=False)`，标记 `WP3-TAXONOMY`；该席**无日志**、未获二方评审。
- 只做完 1/5：⑩中央调度层——Wave 0（两同名 `CapabilityResult` 分层归并，壳版改名 `InvocationResult`）已落，**Wave 1–4 未做**，断点三处改法在席日志 §8。
- ⑧⑨ 落盘失败告警 / `shared_export` 键形：上一子波已落，保留。

**等她拍板四项**
- **P-1** 占卜三枚新键 + `bot_divination_db_path` 是否与 control_plane 同名键合一（荐：合一 + 旧名再导出）。
- **P-2** 调度层 Wave 1–4 是否继续（荐：先 Wave 1+2，Wave 4 三硬骨头单独立项）。⚠ 她裁的是「所有内容都接入」，**这条尚未交付**。
- **P-3** 21 枚新键是否登记 `SETTABLE_KEYS`（荐：只登记真能热改的，其余诚实标重启）。
- **P-4** v7 / 记忆总线灰度开 `true` 的时机（荐：重启后先只开给她自己与管理员，观察 3 天）。

**重启前必说给她**：修③断链的副效应 = 紧急域采集调度器恢复注册。生产 `.env` 现值 `BOT_EMERGENCY_INFO_ENABLED=true` + `SOURCES=nmc` ⇒ **一重启 NMC 轮询真跑**（投递仍受订阅表约束，表空=零投递）。要完全不跑就把总闸改回 `false`——上一会话没动 `.env`。

## 五、你的第一个动作

1. 测别人在不在写：`stat -c '%y %n' AGENTS.md docs/HANDBOOK.md plugins/bot_unified_runtime/config.py`；任一 5 分钟内被写过 ⇒ 停下报告，别抢。
2. 建**你自己的**基线：`dev.ps1 -Task lint` / `typecheck` / `runtime-layout`（三条命令见 `AGENTS.md` 第五部分）。全量 `-Task test` 约 10 分钟，跑前先问她要不要现在烧。
3. 复跑本波新门族：命令直接抄 `master-plan.md` §8.7。
4. 与上面基线逐条对差，每条差先归因（你的改动 / 他波在飞 / 环境）再报。
5. 报告结构：结论 / 证据 / 未做 / 待裁（字母 + 荐）。

## 六、已知坑

- `subprocess.run(..., text=True)` 未钉 `encoding` ⇒ 只要按本仓跑法 `export PYTHONIOENCODING=utf-8`，reader 线程 GBK 解码崩、`stdout` 变 `None`、报成 `in None` TypeError。全仓另有 10+ 处同类调用已登记未 sweep-fix。见「stderr 是 None」类红先判编码，别改产品码。
- 繁简折形 locale 写 `'cn'` **静默不折**，必须 `'zh-cn'`。
- **存在性锁会糊过活性判据**：上一波立过 R1/R2/R3 三把静态可达性门，全绿而生产零投递。判据要能杀行为，不能只杀符号。
- Git Bash 缺 `rm`/`mv`；删移文件用 PowerShell `Remove-Item -LiteralPath` / `Move-Item`。
- 直跑 pytest 会在源码树拉出 `data/cards`、`__pycache__`、`.pytest_cache`；污染了先备份 `%TEMP%` 再清。
- **会话盘**：CLI 在 `~/.qoder-cn/projects/<转义cwd>/<会话ID>.jsonl`（子代理在 `<ID>/subagents/`），Desktop 在 `~/.qoder/`。本地不存 token 统计，「上下文大小」用体积+消息数+`compact_boundary` 次数作代理，**并按内容指纹认人，别用体积猜**。

## 七、格式

中文；不用 emoji；不做「我将要……然后停下等确认」。**不可逆动作（commit/push/重启/删文件/出网）必须先问**；已授权阶段持续执行，范围一变重新要授权。
