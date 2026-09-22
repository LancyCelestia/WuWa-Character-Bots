# 外部紧急信息聚合域 — A 波收尾汇总报告（2026-09-19）

> 术语说明：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](../snowluma-setup.md)。

> 波次档案：`.superpowers/sdd/2026-09-19-emergency-info-unify/`（`task_plan.md` / `findings.md` / `progress.md` / `briefs/` / `reports/`）
> 本波**未 commit、未重启、未部署**（用户裁定）；全部产出为**离线证据 + 现状坐标**，B 波尚未开工。

## 一、一句话结论

A 波 10 席只读盘点**7 席交付、3 席被日配额硬拒**；已把「外部紧急信息聚合」的现状、可复用中央入口、以及**四颗会炸的雷**钉成带 `文件:行` 的事实；但「九个统一」中的**样板统一（E3）与语音面（E7）现状仍是空白**，不能宣称规格已闭合。

## 二、本次事故与根因（两个独立死因，均已实证）

| # | 根因 | 证据 | 修复（已生效） |
|---|---|---|---|
| F-11 | **父会话结束回合 ⇒ 子代理 stdio 权限通道关闭**：在飞请求 `cancelAll`，排队席位 `initialize failed` 后以 `exit_code=0 reason="success"` 静默退出、**不回报** | 10 份 transcript 全止于 18:56:43–44；池日志原文 `stdio permission channel closed; failing closed in-flight permission asks` → `initialize failed: Error: Permission channel closed at A.cancelAll` | 主会话在席位在飞期间**不再结束回合**（改为同回合有界等待 + mtime 对账）；每席**开工即建 report 写 `Status: STARTED`**，逐节 append |
| F-13 | **日累计用量耗尽**：spawn 即拒，明确回报 `failed` | 第一批 3/10 被拒（0 token/2–16s），补派 E2/E3/E7 **三席全拒**（0 token/556–1470ms，原文「Come back tomorrow」）；19:55–20:13 十七分钟内 7 席合计约 36M subagent tokens（单席最高 E5=21.7M） | 无技术解，属外部配额；按 AGENTS.md §一.7 落盘保进度、明日续派 |

**两处我判错并已就地更正的启发式**：`task-*.json` 的 `status:"running"` 是 spawn 期快照（非活性信号）；`logs/runs/*/qodercli.log` 增长**不能**判席位存活（该池日志同时记主会话自己的 agent-loop）。唯一可靠信号=该席 transcript mtime + report 心跳。

## 三、A 波交付表（全部离线实跑，报告为证）

| 席 | 域 | 状态 | tokens / 工具 / 耗时 | 报告 |
|---|---|---|---|---|
| E1 | 存量采集与主动推送盘点 | DONE_WITH_CONCERNS | 4.58M / 54 / 600s | 17.5KB |
| E4 | 文本输入链 | DONE | 2.54M / 34 / 493s | 11.6KB |
| E5 | 文本输出链与多通道投递 | DONE_WITH_CONCERNS | 21.7M / 85 / 1222s | 10.2KB+ |
| E6 | SnowLuma 协议适配残留 | DONE_WITH_CONCERNS | 5.19M / 44 / 698s | 38.5KB·250 行 |
| E8 | 渲染契约与告警视觉 | DONE_WITH_CONCERNS | 9.41M / 53 / 785s | 21.8KB（四契约测试 317 passed + verify_hashes EXIT=0 实跑） |
| E9 | WebUI 与控制面协议 | DONE | 5.83M / 59 / 600s | 20.5KB |
| E10 | 配置键与生成物门禁 | DONE | 8.46M / 65 / 614s | 24.0KB |
| E2 / E3 / E7 | 文档索引 / 注册样板 / TTS | **blocked×2（日配额）** | 0 / 0 / <2s | 无产出 |
| E11 | 政务应急源普查 | **未派**（配额墙） | — | 任务书已备 `briefs/E11-brief.md` |

## 四、发现分级（会炸的 / 会错的 / 欠账的）

### P0 会炸的

1. **`.gitignore:29` 的 `data/` 规则正吞掉域重组后的真源码**。我复核结果 **29 个** `.py`（E10 报 27，以实跑清单为准，清单在 `/tmp/swallowed.txt`，含 `domains/core/config/*.py`、`domains/divination/data/*.py` 等）；`git ls-files` 视角 domains/ 树仅 5 个 `__init__.py` 被跟踪 ⇒ **任何「逐文件 add」提交都会静默丢源码**。
2. **中央层没有出站防风暴闸**：现役 6 族主动投递口全部绕开入站 quiet/限流门（E1/E5）；唯一带紧急语义的日程 v2 引擎未接线（下条）。聚合域若直接复用现有投递口 = 叠加刷屏风险。
3. **送达确认只有 retcode**，无段数一致性核验 ⇒ 「语音段被静默摘除、文字照常发出、API 回 ok、我方记 `SENT`」的谎报送达链**在代码层面至今无校验**（F-07 + E5 concern 3）。
4. **`docs/HANDBOOK.md:167` 存留已作废旧 WS 令牌明文**（E6），违 AGENTS.md §一.3；用户已裁抹除。

### P1 会错的

5. **日程 v2 引擎有 `urgent` 穿 QuietHours + 错过三策略 + 每主体限流，但缺省关且全仓仅测试引用**（`config.py:405-406` False；`schedule_service.py:416-464/:506/:526-550`）⇒ 「复用还是另建」必须先裁，否则必然造第二套（违 G5）。
6. **事件 source 枚举 12 vs 14 → 主会话复核后改判为「有意分层，不是 bug」**：活真身 `domains/ops/monitor/event_store.py:54` 只 12 项，其 docstring（`:12-15`）明写「V2.1 按**合同 §8 有意收敛为十二个**」，活测试 `test_event_service_v21.py:169` 逐字锁定；legacy `plugins/bot_unified_runtime/control_plane/events.py` 是 14 项。⇒ 真缺陷改记为：**域重组后的 `control_plane/` 死副本仍在盘上（未跟踪遗留）**，须由收口席清理，否则后来者会像本会话一样改到死代码。SnowLuma 若要作为日志 source 归因属**合同变更**（合同 §8 + 验收矩阵 + docstring + 活测试四处同改），需单独裁定。
7. **渲染真值 = 11 面（7 Jinja + 4 f-string 直拼）**，「6 模板」是旧口径；**P0–P3 定级色零存在**；`render_root_tokens(extras=)` 是 gate08 hex 门的合法后门 ⇒ 定级色必须走登记表而非后门（E8）。
8. **「每主体 3/分钟·20/小时」文档口径不成立**：真值 60/12/8 生产值 + 45s R3，群句数帽缺省关 ⇒ AGENTS.md 需更正（E5）。
9. `redact_local_secrets` **不是中央闸**；`plugins/bot_unified_runtime/runtime/capability_protocols.py:151` 与主链 `CapabilityResult` **撞名**——新域两大易错点（E5）。
10. **>1500 字长通报无卡降级机制**（E8）；邮件主动推送**无先例未实证**、TG 4096 切分归属欠账（E5）。
11. **台账 #33 缺陷②仍在**：`__init__.py:3231` 群摘要推送未传 `llm_provider` ⇒ `bot_group_digest_llm_enabled` 推送侧恒不生效（E1；缺陷① session_id 已由 F4 席修，`shared_group.py:31-46`）。
12. **生产未注入 `unknown_part_confirmer`** ⇒ 多段分片「结果未知」只能停 `PARTIAL`，无人工对账口（E5）。
13. **文档现行端口径**：E6 报 17 处「以 NapCat 为现行端」。我复核分布为 AGENTS.md 8 / README 4 / HANDOFF-NEXT 6 / HANDBOOK 37 / napcat-setup 26 / acceptance-manual 15 / bot.py 5 —— **不能 sed 批换**（napcat-setup 等属回滚史，须逐行判定哪 17 处是「现行端口径」）。

### P2 欠账（登记，本波不修）

14. `qx.json` 的 `.gitignore` 例外规则（`:32-33`）仍指旧家 `sources/data/`，新路径保护名存实亡（E10）。
15. 告警旁路直发、无幂等无重投，仅进程内存态 300s 抑制（`alerts.py:155-171`，E1）。
16. `traces`/`persona_versions`/`latency` 历史曲线均为诚实空位（503/False）⇒ 紧急趋势图不可依赖（E9）。
17. `doc_sync --check` 在本席时点为红（测试文件数 432→438 漂移，在飞批未重录），非本波造成（E10）。
18. **重要更正**：记忆条目「webui 从未 commit」已过期——`a76cc2b`（09-19 17:25）整树 43 件已入库，共 6 笔；唯 `webui/dist/` 被 gitignore（E9）。

## 五、「九个统一」完成度（诚实评分）

| 统一面 | 现状 | 缺什么 |
|---|---|---|
| 架构 / 处理流程 / 流程图 / 架构图 | 输入链·输出链·门禁·SendQueue·渲染·控制面六面现状已钉坐标（B 波可直接画） | 正式图纸未画（B11） |
| 模块 | 新域归属可定：`domains/emergency/{model,sources,service}` | 待 E3 样板坐实注册链 |
| 样板（模板） | 渲染 11 面与契约门清单已明；`propose→approve` 审核先例已定位 | **E3 注册正例缺席**（配额拒） |
| 函数 / 参数 / 变量 | 既有命名法证据齐（RouteKind 34 成员 `base_router.py:99`、`bot_<域>_*` 键法、`CapabilityResult` 字段集） | 命名法归纳表待 E3 出（B11 汇总） |
| Help 命令与帮助页 | 同步面 12 点 + 三处硬编码计数（77/37/40）已列（E10） | 新 topic 文案待 B9 |

## 六、已授权、待执行的三项（用户 2026-09-19 裁定）

| 项 | 裁定 | 落地要点 |
|---|---|---|
| `.gitignore` | **修规则 + 出待 add 清单，不 commit** | `data/` 限定到运行数据路径；为 `domains/*/data/*.py` 加否定规则；qx.json 例外改指 `domains/weather/assets/`；清单 29 件已在 `/tmp/swallowed.txt`，建议转存波次目录 |
| 出站闸 | **B 波先在中央建闸** | 在 `SendQueue.submit` 之前统一 quiet hours + 每主体限流 + 按日 dedupe；聚合域只走中央闸；存量 6 族只登记不迁移（避免波及在飞会话） |
| 令牌与口径 | **抹明文 + 改 17 处现行端口径** | 明文先备份 `%TEMP%` 再替为 `env:` 占位；17 处须逐行判定（**不可批换**，回滚史保留 NapCat 字样），`bot.py:453-456` 属运行文案，改后须重启方生效 |

## 七、下一步（配额刷新后按序）

1. 补派 **E3（注册样板，B 波硬前置）→ E11（政务应急源普查）→ E7（TTS）→ E2（文档索引）**；
2. B 波首批 = B4（中央出站闸 + 谎报送达校验）→ B1/B3（域内核与规则定级）→ B8（注册装配）→ B6（P0–P3 卡）→ B7（WebUI）→ B5（语音）→ B9/B10/B11/B12；
3. 你侧动作：`.gitignore` 修完后决定是否 commit 29 件源码；重启前跑 `docs/acceptance-manual.md` 新章（E6 已给 13 项 hookAutoLoad 清单，建议编 §6.6.12）。

## 八、复现命令（本波所有断言均可自证）

```bash
# P0-1 被吞源码
git ls-files --others --ignored --exclude-standard -- 'plugins/bot_unified_runtime/domains' | grep -E '\.py$'
# F-11 死因原文
grep -h -m1 "Permission channel closed" ~/.qoder/logs/runs/2026-09-19T19-0*/qodercli.log
# 席位活性（唯一可靠信号）
ls -la --time-style=+%H:%M:%S .superpowers/sdd/2026-09-19-emergency-info-unify/reports/
# E8 渲染契约（该席实跑）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"   # 全量门禁待 B 波收尾实跑
```

## 九、A 波追加战果与主会话动手修复（收尾令之后）

**席位追加**：E3（注册样板，12.08M tokens/61 tools）与 E11（源普查，3.66M/49 tools）**已交付**；E7（16.07M/74 tools）与 E2（1.14M/17 tools）中途死于第三种死因 `Sorry, something went wrong`（非配额、非父通道），但**心跳文件保住断点**（E7 19152B、E2 1228B）。

- **E11 源普查总账：实测 20 源 → 接 6 / 不接 12 / 等 key 2**。接：NMC `findAlarm`、NMC `rest/weather`（`data.real.warn` 白捡站点级预警）、预警详情页全文、ICL chinaeew（CENC 匿名代理，官方 speedsearch 已死 302→OSS NoSuchKey）、USGS（rect 用 `min/max`，`bbox` 报 400）、GDACS 新端点 `Events/geteventlist/allpaging`（旧 MAP 已 404）。等 key：CENC yjfw（token+POST）、ReliefWeb v2。诚实不接：12379（「系统升级中」，与 NMC 同源）、mem.gov.cn（列表非静态 HTML）、122、12306（需 cookie+POST）等。内涝/高温/寒潮经当日 328 条类型分布实测=**单源已覆盖，绝不造第二套**。探针与 6 份真实离线样例在 `probes/`（无 token/cookie）。**诚实约束**：地震主源走 ICL 属降级方案，卡面必须标「ICL 联盟」，不得冒充 CENC 本尊。
- **E11 带回一条现役生产缺陷**：`findAlarm` 冷页实测 10–25s，而预警支路单次外呼且失败静默返 `[]` ⇒ 天气预警支路间歇性「无预警」假象。E11 指称坐标 `weather.py:162 timeout=8s`；主会话复核真身＝`domains/weather/capabilities/weather.py:201-218`（`fetch_city_alerts`，缺省 `timeout=8.0`、单次、`except (ParseHttpError, ValueError, OSError): return []`），同文件主查询通道反而是 `10s + 重试 2 次`（`:82-83`、`nmc_weather.py:113`）⇒ **同域内两条通道韧性不一致**属实证。主会话判定：**不做「8→10s」式化妆修复**（冷页 10–25s 说明根因是热路径内联外呼，正解＝B 波聚合域的**定时轮询 + 缓存**，让用户路径永不直吃冷页），已作为硬约束交 B4/B2。
- **E3 注册样板战果**：AST 实跑 RouteKind=34 / `_HELP_ENTRIES`=77（与 `docs/auto-facts.md:11` 一致）；真身 `domains/chat_reply/runtime/{base_router,capability_registry}.py`，旧路径是 PEP 562 垫片；给出 9 个同步面与施工序；**样板首选两半母版＝weather（查询+预警+主备源）+ campus（三重门+幂等 SendRequest 主动推送）**；并交叉印证了主会话 FIX-1 已落在盘上。E3 新发现两条待裁：根 matcher priority 与 RouteRule priority **双钉无一致性门**（新域须人工同值）；cron 时刻=装配期快照 + APScheduler 走系统本地时区（台账 #6 仍在）⇒ 聚合域定时采集必须按此时区口径设计。

**主会话动手修复（TDD，先 RED 后 GREEN）**

| 项 | 结论 | 证据 |
|---|---|---|
| **FIX-1 交付** | 夜间群摘要推送补传中央 LLM provider（台账 #33 缺陷②收口） | RED `1 failed, 34 passed` → GREEN **35 passed**；并行会话推进 HEAD 至 `e0b0722` 后**复跑仍 35 passed**；活测试基线 `test_event_service_v21.py` **19 passed**（未被本会话碰坏）；ruff 对改动文件 All checks passed；`dev.ps1 -Task typecheck` **Success，618 文件零错**；`-Task runtime-layout` 通过 |
| **FIX-2 撤回** | 原拟修「source 枚举漂移」，两次判定均为**不该动手**：第一次改到 `control_plane/` **死副本**（`??` 未跟踪 ⇒ 当时「55 passed」是死代码跑死测试的假绿，已逐字节还原、`grep snowluma` 零残留）；第二次查明活路径 12 项是**合同 §8 有意收敛**，加项属合同变更，不由主会话深夜偷改 | 见 §八 P1 第 6 条与台账撤回行 |
| **未修声明** | T0-2 中央出站闸、T0-3 送达核验：**故意不 hack**。T0-3 正解要给 `OneBotAdapterProtocol`（`domains/transport/sender/onebot.py:53`，现只声明两个 send 口）扩回执确认口，属发送主链设计级改动；已派 B4-spec 席出规格（唯一插入点/签名/限流真值/本地可判定 vs 需适配器确认/反证测试清单/与日程 v2 引擎复用裁定），主会话不抢改 | B4-spec 与 RV-1 评审席在飞 |

**并行会话撞车实况（本波最重要的操作教训之一）**：本会话期间，另一会话正把 G-0 基线分批 commit（HEAD `a76cc2b → 607472e → d6801ab → e0b0722`），并**独立修好了我准备修的 `.gitignore`（P0-1）与正在改 AGENTS.md 的 NapCat→SnowLuma 口径（T1-13）**。⇒ 我主动**不碰** `.gitignore` 与 `AGENTS.md`，避免双写；同时也正是这种高频重组，让「旧路径」变成死副本——**动手前必须 `git status` 验文件是否 tracked**，否则就是在改坟。

## 十、B 波开工首轮战果（2026-09-20 01:20—01:50，本节覆盖 §九的席位状态）

**B4 规格已交付并落盘**：`specs/B4-outbound-gate-and-delivery-verification.md`（26,797 B / 183 行 / §0—§7）。核心裁定六条：
①中央闸唯一插入点=新文件 `domains/transport/sender/outbound_gate.py::submit_active_push`，**`queue.py:418` 本体不改**（三选否：队列双实现会漂移 / 会误伤消息流回复 / 会连坐存量 6 族，且队列不该持有内容策略）；
②三道门序=quiet（仅 P0/P1 穿静默，D-2）→ 每主体 60s/3600s 双滑窗（新单表 store）→ **dedupe 键规范核验**（不新建第二去重账，队列 `ON CONFLICT` 已是中央幂等）；
③**fail-open 方向锁**：闸自身故障不得变成丢消息；
④限流真值四行表（A 入站现役 60/6/4+45s、B 群句帽缺省 0、C 日程 v2 内部 3/20、D 新闸 2/6），旧口径「3/分钟·20/小时」判为**描述未接线引擎**，列出 4 处需加限定的文档行；
⑤送达核验分两层：Tier1（本地可判定：发前摘段观测 + SENT 审计指纹，**一律不改 `ReceiptState`**）归 B 波实施；Tier2（`get_msg` 回查）协议扩展归 B 波、**语义启用等 SnowLuma 真机取证**；
⑥与日程 v2 = 复用其词汇/设置对象/`deliver_after` 原语，**不复用其实例**，不构成第三套（T13 锁死不得自造 HH:MM 解析）。

**RV-1 独立评审席结论（01:33）**：判定 **Approved + 2 Important + 3 Minor**，据此更正主会话两处口径——FIX-1 生效口径降级为「代码已修，生效需三开关 + 重启」（`.env` 三门全关，夜间推送当前一单不发）；FIX-2 撤回理由改正（`plugins/bot_unified_runtime/control_plane/events.py` 是**并存诊断层**不是坟，但文件 untracked ⇒ 还原不可自证，**待控制面批 Owner 核对 4 个文件**）。全文 `reviews/FIX-1-2-review.md`（7,642 B），评审包 `reviews/FIX-1-2-package.diff`（184,188 B）。

**E7 TTS 席第五次派发完成**（DONE_WITH_CONCERNS，314 行 / 61 KB，7.79M tokens / 45 tools / 678s）：语音出站定性=「复用中央通道的旁路，且投递记账对它结构性失明」（`worker.py:557/:593`、`__init__.py:1649`）；「谎报送达」根因坐实=**`onebot.py:975-981` 只要 retcode==0 即记 SENT，全链零段数校验零回查**，且成功件刻意 `title=""/body=""`（`tts.py:732-740`）⇒ 失败连可降级文字都没有。三处就地更正：旧提法「不等则改判 FAILED_RETRYABLE/UNKNOWN」**作废**（与 T12 冲突，改判=重投风暴）；`domains/creation/tts/contracts.py` 的 3000 字/60s/20MiB 钳制是**初稿漏盘的契约层**，与生产 media 路径同概念两数值 ⇒ B 波先裁权威再谈新键；配置键 19→**20**。新事实：`check_and_record` 全仓唯一调用点 `pipeline.py:611` ⇒ **限流只管入站，主动投递不经此族**；`onebot.py:1015 _call_optional_onebot_api` 已实现鸭子探测降级原语（Tier2 免造第三套）。

**两席死亡与一次续飞**：B4a **第二次静默死亡**（report 290 B 仅 `Status: STARTED`，`outbound_gate.py` 与 `test_outbound_gate.py` 经 `ls` 实证不存在）⇒ 改派 **B4a-R2**（收窄为两件新文件，`config.py` 六键转为 §落地请求）。B4b **在飞且已进 RED**：`tests/test_delivery_verification_tier1.py`（15,322 B）实跑 **13 failed / 4 passed**，`onebot.py` 于 01:47 仍在被写（`git diff --stat` = 208 插入 / 7 删除）。新派 **B1R3** 落紧急域内核（`domains/emergency_info/**` 全新增文件，零碰撞）。

**紧急域代码现状（诚实基线）**：`domains/` 实数 21 个域目录，**无 `emergency_info/`**；RouteKind 34 项无紧急族；帮助 topic 77 项无紧急页 ⇒ 本波主体产出仍是「规格 + 中央件 + 内核」，**功能未通、未注册、未生效**。

**并行会话撞写风险已量化**（不再靠猜）：HEAD 在两次 `git log` 之间从 `de7ef71` 推进到 **`de7d113`（01:19:56）**，工作树 `git status --porcelain` = **907 件**；`find -mmin -12` 抓到 01:36—01:47 有 24+ 个文件被别的会话实时改写（含 `config.py`、`base_router.py`、`echo.py`、`theme_tokens.py`、`queue.py`、`AGENTS.md`、`docs/auto-facts.md`）。⇒ 本波**临时禁写面扩表**已下发给所有席位（见台账 `progress.md` 同节），唯一例外是携独占面任务书的 B4b。

**FIX-1 在新 HEAD 上再复验**：`__init__.py` 已被并行会话改成域内局部 import（`:3227-3237`），补丁仍在位且更稳（monkeypatch 模块属性即可命中）——实跑 **35 passed in 1.96s**。

## 十一、发送主链两处修复落地（02:05 复验）

**B4b 已交付 T0-3「谎报送达」的本地可判定层**（18.27M tokens / 81 tools / 1,699s）：
摘段观测从「静默丢段」变为一行确定性日志（`request_id/planned/sent/dropped_types/sent_types`，零正文），
核验开关开启时 SENT 回执带 `segment_dropped_local` 审计注记；**`ReceiptState` 枚举零改动并有冻结锁测试**。
Tier2（`get_msg` 回查）以 `_ONEBOT_GET_MSG_NOT_FOUND_PROVEN=False` 取证锁把「明确不存在」判定钉成生产不可达，
防重投双发；接线只在 `__init__.py:1653-1668` 调用点，`getattr(..., False)` 取不到键=现状逐字节。

证据（主会话独立复跑，非席位自报）：`tests/test_delivery_verification_tier1.py` **17 passed in 2.25s**（该席中途曾 13 failed/4 passed 的真 RED）；
`grep -n unknown_part_confirmer plugins/bot_unified_runtime/__init__.py` → `:1653/:1654/:1657/:1668`。

**两条规格级反证（由实现席抓出，已判成立）**：
① 规格 §3.2 T2-b **自相矛盾**——worker 只在 part **没有** `provider_message_id` 时才问确认器，而规格要求确认器按该 id 反查 ⇒ 确认器永远拿不到把手；终态修法须先定「id 供给链」再谈启用。
② 规格 §3.2 声称「协议扩展零行为变更」**不成立**——`get_msg` 直接进原协议会打断 5 个 smoke 替身（mypy 实锤），须分层为独立消费面。

**曾被误判为阻塞的两处**：他席在飞写入中间态（`domains/render/templates.py` 01:55、`domains/chat_reply/security/content_safety.py` 02:02）当时报语法错，
02:04 `py_compile` 复核两者 **SYNTAX OK** ⇒ 非阻断，属并行写盘瞬时态。

**仍未闭合的唯一一环（裁决项②的实质）**：`grep -c "bot_outbound" plugins/bot_unified_runtime/config.py` = **0**
⇒ Tier1/Tier2 代码在树、生产**没有旋钮可开**。要么现在往被热写的 `config.py` 补 1 枚 `bot_outbound_verify_enabled`，
要么等 `config.py` 静默由合流席落六键（`bot_outbound_gate_*` + 核验键，含 `path_fields` 重映射）。

## 十二、五项裁决执行记录（2026-09-20 02:05—02:20，用户令「全部去执行」）

| # | 执行结果 | 证据 |
|---|---|---|
| **①** control_plane 四件核对 | **已跑只读核对，还原成立**：四件全为 `??`（未跟踪），`grep -rn snowluma` 在 `control_plane/**` + 该测试 + 该文档 = **0 命中**；权威层 `tests/test_event_service_v21.py` **19 passed**（12 项枚举锁未被我碰坏）。同目录 3 个 tracked 文件（`plugins/bot_unified_runtime/control_plane/audit.py`）此刻是他席的 `M`，与本席无关 | 上述命令 02:12 实跑；另注：`control_plane/` 下共 **32 件 untracked**（整个 V2.1 层尚未入库），这就是「无 git 基线可自证」的根因 |
| **②** 出站闸配置键 | **已完成且门已复绿**。实际归因（据 B4a 报告 §4/§11 更正本会话早先误判）：**原席 B4a 并未死亡**，是它于 02:08 把七枚键写进了 `config.py`（`:234-239` 六枚闸键 + `:244` `_outbound_verify_enabled`，`:1188` 已把 `bot_outbound_gate_db_path` 收进 `path_fields` 重映射），但**未登记 catalog** ⇒ `test_config_catalog_covers_config_fields` 被本波**弄红**。主会话 02:16 在 `docs/config-catalog-full.md` A26 表尾补 5 行（覆盖七键，含「与入站限流是两个对象」「3/分钟·20/小时 只属未接线引擎」「不改 `ReceiptState`」三条口径钉死）→ `tests/test_doc_sync_gates.py` **4 passed**（此前 1 failed）。**根因是主会话误判席位死亡**：见本节末「主会话错判自纠」 | `grep -n bot_outbound config.py` → 7 命中；缺省值实测 `false/true/["P0","P1"]/2/6`；`--basetemp` 离线复跑 |
| **③** TTS 上限权威 | **裁定：`domains/creation/tts/contracts.py`（3000 字/60s/20MiB）判为非权威骨架**，理由已升级——01:50 另一席已落地**第三个也是现行唯一的权威**：`domains/media/tts_presets.py`（7,585 B）+ `config.py:336 bot_tts_preset="shorekeeper"` + `:339 _tts_max_chars=200` + `:342 bot_tts_hard_max_chars=2000`（G2-R3 中央硬顶，超顶拒绝+`OperationalIssue`，`0`=不限但必过硬顶）。⇒ 生产口径已收敛为「预设表为唯一缺省源、`BOT_TTS_*` 数值键降为管理员覆盖」，contracts 层不再谈接线；`contracts.py` 文件头的「非权威」标注由 creation 域 owner 执行（本波不跨域改码）。「接上限 + 三态出口（超长→文本+卡）」**另立一批**，因为它要同时改 `tests/test_tts_outbound_chain.py:66` 的 parts 锁 | `ls` mtime 01:50；catalog `:812` 行原文；`grep -n bot_tts_hard_max_chars config.py` |
| **④** commit | **按「安全白名单」执行：只提文档**。理由不变且已量化——`__init__.py` 1315/305（181 hunk）、`config.py` 299/8、`docs/config-catalog-full.md` 72/5、`.env.example` 176/4 全是**他席在飞工作**，`git add` 任何一件即越权捆绑；`tests/test_delivery_verification_tier1.py` 单独提必红（`git show HEAD:domains/transport/sender/onebot.py \| grep -c set_outbound_verify_provider` = **0**）；`tests/test_group_digest_push.py` 单独提亦红（FIX-1 代码半在 `__init__.py`）。⇒ 本波入库件＝B4 规格（自 `.superpowers/` 归档到 `docs/design/`）+ 本汇总文档，且按本仓共享索引规矩用 `git commit -- <paths>` 形式；**未 push**（铁律 4：仅按明确指示） | 提交后 `git show --stat HEAD` 核对，哈希见台账 `progress.md` 与本节末追加行 |
| **⑤** B4b RED 处置 | **作废**：13 RED 已由该席自己转 **17 passed**（主会话 02:0x 独立复跑同数），无需移回 `%TEMP%` | `pytest tests/test_delivery_verification_tier1.py` 输出 |

**本波生产可达性现状更正（②执行后）**：中央闸与送达核验的**代码 + 配置键 + catalog 登记**三件齐备，缺的只是「谁把闸接到调用点上」——按规格 §1.2，聚合域是唯一被授权经闸投递的新代码，存量 6 族维持直连（T6 结构锁），故闸在紧急域通起来之前对现役行为零影响。

### 主会话错判自纠（本波第四条口径错，公开记账）

- **我说过什么**：「B4a 第二次静默死亡（report 290 B，仅 `Status: STARTED`，`outbound_gate.py` 不存在）」。
- **错在哪**：把「心跳文件小 + 目标文件还没出现」当死亡证据。实际该席一直在跑（终账 **34,299,422 tokens / 94 tools / 2,704s**），290 B 只是它开工第一笔心跳，之后长时间在读码没 append。
- **后果**：我把 B4a 与补派的 B4a-R2 指派到**同一独占面**（`outbound_gate.py` / `test_outbound_gate.py` / config），等于自己造出同面双写风险。
- **为什么没酿成事故**：B4a 第二次写闸文件时被写保护拦下（`File has been modified since it was last read`），**按纪律未重试、未覆写**，转为自己只做 config 面；`outbound_gate.py` 实际归 B4a-R2 独有。
- **正确判据（已回写长期记忆）**：席位活性只能看**席位 transcript 的 mtime** 与目标文件 mtime，**不能看心跳文件大小**；未收到 result 前若要补派，必须补派**互斥面**，不得补派同面。
- **两席终账合并**：B4a（config 七键 + 闸测试 **42 passed**，起点 RED=38 failed/3 passed + §落地请求 L-1…L-7 + 裁决点 C1…C5；相邻发送队列族合跑 247 passed；`typecheck` 全树 Success 629 文件）+ B4a-R2（`outbound_gate.py` 实现 + 测试）= 中央闸**代码/配置键/文档登记三件齐备**。
- **诚实边界**：**闸当前零消费者**（`grep` `domains/emergency_info` 内 submit 触点 = 0），不得宣称生产生效；`lint` 全树 46 错全在他席面（本波三面 0 错）。
- **本波不做、待热面冷却后落地**：`scripts/doc_sync.py --write` 重录机器册（620→627，`docs/auto-facts.md` 正被她席写）、`SETTABLE_KEYS`、装配接线 `issue_sink`→alerts；以及 **L-6 方向性风险**：~~紧急域若不以 `priority=str(level.value)` 落 `RouteRule`，P0 会被静默顺延=漏报~~
**（此句载体写错，§十三-1 已更正：载体是 `SendRequest.priority`，不是 `RouteRule.priority`）**（B 波注册席必读）。

### ④ 执行补记：实际入库三笔（02:20—02:25，路径式提交，未 push）

| 笔 | 内容 | 归属核对 |
|---|---|---|
| `53e8e7f` | `docs/config-catalog-full.md` **+5/−0**（七键 A26 登记）| 提交前实测该文件未提 diff 恰为 5 行=本会话独有 ⇒ 零捆绑；修掉 HEAD 红门 |
| `c632c36` | `tests/test_group_digest_push.py` **+32/−0**（FIX-1 回归锁）| 提交前实跑 **35 passed**；代码半已由并行席 `9a9e099` 入库，故此笔不构成红提交 |
| 本笔（docs/design 两件） | B4 规格归档（29,129 B，含 §8 Amendment）+ 本汇总（含 §十一/§十二）| 全新增文件；提交前 `git diff --cached --name-only` 实核=仅此两件 |

**仍未入库（有意不提，理由可核）**：`__init__.py`（1315/305，181 hunk 他席在飞）、`onebot.py`（236/20，B4b 独占面且无基线可证唯一作者）、`domains/transport/sender/outbound_gate.py`（774 行，B4a-R2 刚落地）、`domains/emergency_info/**`（B1R3 在飞）。⇒ 提它们=把别人未完成的域重组扫进我的提交，越权。

### B4a-R2 终账与两席合并（02:24）

`outbound_gate.py` **774 行**（唯一入口 `submit_active_push@:639`）+ `tests/test_outbound_gate.py` **1344 行 / 42 条**；
合跑 `test_outbound_gate + test_group_digest_push + test_bgroup_sender_delivery` = **89 passed**（起点 RED 38 failed/3 passed）；
单文件 ruff `All checks passed!`、mypy `Success: no issues found in 1 source file`；T1 缺省全关=裸 submit 零 store 零审计，
**T6 双结构锁实证现役 6 族仍直调、`domains/emergency_info/` 尚未引用闸** ⇒ 闸零生产接线（接线原文在报告 §R2-4-L1/L2）。
本席另钉死两处规格缺口待评审：severity 载体=`SendRequest.priority`、新增仅关键字参 `dedupe_family="once|daily"`。
它同时纠正了本报告早前一行的口径：「原席零代码落盘」不成立——原席已写完 1285 行 RED 与 config 七键，双作者结构已在报告 §0/§R2 写清。

## 十三、B11 规格席抓出的两条，本会话复核后更正（03:05）

### 13-1 我的第六条口径错：P0 漏报的**载体写错了对象**
- 我在 §十二（以及转给 B11/WIRE-MAP/INTG-1 的任务书里）写的是「紧急域须以 `priority=str(level.value)` **落 `RouteRule`**，否则 P0 被静默顺延」。
- **错在把两个不同维度混成一个**：`RouteRule.priority` 是**路由匹配序**（谁先命中），与静默窗无关；
  中央闸读的是 **`SendRequest.priority`**——真身 `domains/transport/sender/outbound_gate.py:248-249`
  `_severity_of(send_request) = str(send_request.priority or "").strip().upper()`。
- 正确表述：**紧急域的每一次主动投递必须把等级写进 `SendRequest.priority`（`P0..P3`）**，
  否则 `_is_urgent` 拿空串 ⇒ 静默窗内一律 `defer`。
- **为什么这条值得单独更正而不是顺手改掉**：生产静默门**默认是开的**（`config.py:1000-1005`：
  `bot_quiet_hours_enabled=True`，`00:00–06:00`，`Asia/Hong_Kong`，`session_types=["group"]`，仅 `admin` 旁路）
  ⇒ 若照我原句去"修 RouteRule"，**修完仍然漏报且没有任何告警**。按 B11 原话：「修错地方等于没修」。

### 13-2 两处过期陈述（已自愈但文档没跟上）
- §十一末「`grep -c bot_outbound config.py` = 0 ⇒ 生产没有旋钮可开」**在 HEAD `6ffdef3` 之后已不成立**：
  B11 02:5x 实跑 **8 命中**，且 catalog 已登记（`53e8e7f`）、`.env.example` 已登记、七键已归 `RESTART_REQUIRED_KEYS`。
  ⇒ 现状是「**旋钮存在、缺省关闭、改后要重启**」，不再是「无旋钮」。
- §九起一直沿用的「B2 三处 ruff 错」在 B11 取证时点已被 B2 自修完（`http_get.py` 02:30:14、`nmc_alarm.py` 02:31:39 mtime 为证）；
  全树 `ruff check .` 仍有 13 错，**全在非本域面**。

### 13-3 B11 的本波最大发现（不是我的错，但比我的错更要紧）
`tests/test_emergency_info_sources.py::test_sources_do_not_import_the_domain_model_of_the_parallel_seat`
用文本断言把「采集器不 import 内核」**钉成了机器锁** ⇒ **今天被保护的是"接缝缺失"这件事本身**：
将来真缝合时，**没有任何一条测试**会因为「绕过 `build_emergency_item`（D-1 收口）或绕过 `ReviewGate.submit`（D-8 审核门）」而变红。
规格 §8.1 已给出锁 A–E（含断言原文与落点文件），实现交 **D1-FIX 席**（任务书 `briefs/D1-FIX-brief.md`，已明令
「不许为凑绿造实现、依赖未落地代码的锁一律 `xfail(strict=True)` 并登记转正条件」）。

### 13-4 顺手登记：闸侧还有两处会咬人的口径差
① `domains/emergency_info/service/dedupe.py build_emergency_dedupe_key` **校验用 strip 值、拼键用原参** ⇒ 带空白入参过校验却拼出非法键，
进闸被 `skip, reason="dedupe_key_shape"` ⇒ **静默丢投递**（同 §13-1 属漏报族，D1-FIX 修）；
② B4a 报告里的接线片段形参名写作 `settings=`，真身是 `settings_provider=` ⇒ 注册席照抄即 `TypeError`。

## 十四、终态三席（CARD-MAP / D1-FIX / LOCK-AUDIT，03:30—03:50）

**D1-FIX 更正了 §13-4 我对 dedupe 缺陷后果的判定（我错了，方向反）**：
脏键（带空格段）实测**能过闸**——闸侧谓词 `outbound_gate.py:259-273 dedupe_key_shape_ok` **不查段字符集**，
所以并不会 `skip, reason="dedupe_key_shape"`；真实后果是**队列 `ON CONFLICT` 幂等失效 ⇒ 重复发送**。
「skip＝漏报」只在调用方真按 `domains/emergency_info/service/dedupe.py:9-10` 注释使用域内谓词时成立，
而该注释与实现不符（已由 LOCK-FIX 席同源化）。⇒ **同一个 bug 的两个可能后果里我报错了那一个**，
教训：讲后果链必须逐段实测到出口，不能从"注释说的语义"外推。
D1 已修 `dedupe.py:39-77`（归一一次并复用，签名/异常面不变）+19 条往返与负向锁，变异自证两侧都做出红；
计数 core 79→**101P+2x**、sources 57→**58P+1x**、简报口径合跑 195→**218 passed + 3 xfailed**，mypy `Success 12 files`。
**它拒绝为凑绿造实现**：锁 C/D + `to_payload()` 接缝锁写成 `xfail(strict=True)`（`--runxfail` 实证红因=前提 0 命中）。

**LOCK-AUDIT 独立体检 59 条锁（78 次注毒含 17 次负控制，全部还原、末态逐字节相同）**：
**A 真锁 39 / B 方向锁 15 / C 恒真·空真 1 / D 弱锁 4，可红率 91.5%**。四处零覆盖已开 LOCK-FIX 席补：
① dedupe 命名空间与段字符集（＝上文重发风险）；② 生产 import 白名单空集恒真 + `startswith` 让
`domains/transport_legacy`/`transporter` 现在照样放行；③ 日志锁被 `exc_info` traceback 喂饱 + 六个观测面值无锁；
④ 双谓词同源化。**一条跨席撞车预警待裁**：现役根 `__init__.py` 直调 `*queue*.submit` 实数**恰=5、门槛余量 0**
⇒ 并行 S0-ROOT-c 收编或本波把闸引进根 init，当天必红 `test_existing_families_still_submit_directly`。
LOCK-AUDIT 还自曝三处自犯并复原（文本通道还原致 CRLF→LF 32271→31497、一次 sha 自校验拿内存串自比=恒真、
一次漏设 `PYTHONDONTWRITEBYTECODE` 落 349 个 `.pyc`）⇒ 已升成本波纪律：**注毒还原必须二进制通道、还原校验必须比对磁盘字节**。

**CARD-MAP（render 面零改动）**：施工图 `docs/design/emergency-info-card-spec-20260920.md`（332 行，diff 全不 apply）。
**推荐路线乙**＝复用 `finance_card` 的 sections/rows（正例：商品/国债/北向三卡零模板改动），
理由量化：扰动面 **乙 2 件 vs 甲 14 件**（甲含 S-D 双向硬门 + 6 枚举面 + 清单 19→20 + 三处「11 面」口径 + 样张基线换代）；
换甲触发条件已钉死（若裁「要真时效条」即切）。四级色抄 `ERROR_ACCENT/ERROR_THEME`（`theme_tokens.py:424-425`→`bridge.py:1824-1869`），
**不进 `PLATFORM_THEMES`** ⇒ 17 平台/别名族零连带。样张（眼睛裁料，`%TEMP%\emergency-card-mock\emergency_P{0,1,2,3}.png`）
自带一条目测结论：**P3 蓝与本命底最接近、级别感最弱**。
它还修正了我给它的判据：`verify_hashes --check` 03:31 实测 **EXIT=0**（我简报里那 2 项漂移已被他席 `863fee6` 化解）
⇒ 出卡开工现在只差两件：12 件 render `M` 未入库 + mtime 未静默（`templates.py` 03:38 又被改）。
