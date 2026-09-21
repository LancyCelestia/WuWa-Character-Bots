# S14 席日志（自愈 RecoveryService + IncidentService + NapCat 采集器，V21-HEAL-001 / V21-INCIDENT-001）

> 术语说明：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](../snowluma-setup.md)。

## 〇、认领与边界（开工时声明）

- **席别**：S14（V2.1 后端批次，纯新增席）。
- **占域**：`domains/ops/recovery/**`、`domains/ops/incident/**`、`domains/ops/collectors/**` 三个**全新**子包——与 RWOC 在飞迁域的 `domains/ops/{admin,audit,features,integrations,monitor,smoke}` 零交集。
- **硬约束执行**：零编辑任何既有文件（含 `domains/ops/__init__.py`、`__init__.py`、`config.py`）；需要配置键一律用模块常量 + 本日志登记坐标留接线席；新测试只新增 `tests/test_v21_s14_*.py`。

## 一、合同依据（实读锚点）

1. `docs/design/backend-v2-implementation-guide.md` §12（L260-262）：运行自愈与代码补丁待审**分开**——自愈只做：重连、有限重试、worker恢复、缓存重建、资源回滚、UNKNOWN对账；**每资源 10min 最多 3 次**；**full-jitter 基础 1s 上限 30s**；**数据库疑损不删库**；**不更改密钥/代理/权限/人格/审计**。代码修复（脱敏故障包→隔离 checkout→待审产物）不在本席自愈范围，只归类为 `PATCH_REQUIRED` 不可重试并上报。
2. 同文件 L288：S14 = 默认真实运维动作、NapCat采集、NoneBot/TG恢复。
3. `docs/design/backend-v2-acceptance-matrix.md` L70/L72：
   - **V21-HEAL-001**：自愈有预算、验证和稳定窗口；重连/回滚/worker恢复；故障风暴与不可重试分类。载体=RecoveryService。矩阵现状 partial（runtime/alerts.py 分散件，无统一 RecoveryService）→ 本席补「统一载体」列。
   - **V21-INCIDENT-001**：admin 结构化故障、恢复通知与查询；时间/位置/解释/方法/Trace；脱敏/聚合/防递归。载体=IncidentService/Queue。矩阵现状 partial（error_report.py 非结构化）→ 本席补「统一载体」列。

## 二、交付计划（纯新增 8 文件 + 3 测试件）

| 文件 | 内容 |
|---|---|
| `domains/ops/recovery/__init__.py` | 域 docstring + 公共名转出 |
| `domains/ops/recovery/service.py` | RecoveryService：FailureKind 双分类（可恢复 6 类/不可重试 4 类）→ 预算（每资源 10min≤3 次，滚动窗）→ full-jitter 退避（1s~30s，rng 可注入）→ executor 协议执行动作（重连/worker重启/缓存重建/资源回滚/UNKNOWN对账）→ 动作后验证（verify 后置断言）→ 稳定窗口（默认 60s 无复发才算成功；复发=取消稳定+升级重计）→ 故障风暴熔断（滚动窗频次超限→开 breaker 冷却期内拒绝执行自愈动作防递归）。时钟/随机/执行器/incident 汇报面全注入，零 sleep 零真实 IO，完全离线可测 |
| `domains/ops/incident/__init__.py` | 域 docstring + 公共名转出 |
| `domains/ops/incident/service.py` | IncidentService：结构化事件（时间/位置/解释/处置方法/trace_id/严重度）→ 脱敏（**懒加载复用** `domains/render/plain_text.py::redact_local_secrets` 真身——单一事实源不复制正则；title/explanation/method/location/details 全过脱敏）→ 聚合（aggregate_key 同因窗口合并，count 累积、首见时间保留，stride 重通知）→ 通知面（IncidentSink 注入，默认 LoggingIncidentSink 走 stdlib log；真实 admin 推送留接线席）→ 查询 API（list 按严重度/来源/时间窗过滤 + get by id，供控制面挂接）→ 防递归（report 全捕获不外抛、sink 失败计数不递归、内存环上限 500 条）|
| `domains/ops/collectors/__init__.py` | 域 docstring |
| `domains/ops/collectors/napcat_tail.py` | NapcatTailCollector 骨架：固定路径文件 tail（path 未配置=惰性不读，state=not_configured——沿袭 log_collectors「不读任意文件」纪律，只读显式配置的 NapCat 自身日志文件）+ 轮转处理（size 回缩/truncate、inode 变化→重开从头）+ 半行缓冲 + 逐行脱敏 + 级别归一（logrus/方括号短标记双形态）+ 背压丢弃计数（sink False/异常→dropped_lines，永不阻塞）+ 巨量积压跳跃追赶（dropped_bytes 诚实计数）。pull 式 `poll_once()`，不自带线程，连接点坐标留接线席 |
| `tests/test_v21_s14_recovery.py` | 分类正确性/预算耗尽放弃/稳定窗口复发升级/风暴熔断/退避等待/执行器异常/验证失败/不可重试直报 |
| `tests/test_v21_s14_incident.py` | 结构化字段齐全/脱敏断言（sk- 形态、BOT_XXX=、盘符路径、Bearer、裸键值全打码）/聚合合并与窗过期/查询过滤（严重度/来源/since）/sink 异常吞并计数/保留环上限/恢复通知面 |
| `tests/test_v21_s14_napcat_tail.py` | 追加行增量读/轮转重开/脱敏透传/背压丢弃计数/级别映射/文件缺失与回归 |

## 三、接线坐标登记（留给接线席，本席零编辑）

1. **RecoveryService 装配**：`__init__.py` 装配区构造 `RecoveryService(executor=..., incidents=IncidentService(...))`；executor 生产实现需包 NapCat 重连（nonebot get_adapter→`_ipr` 重载）、worker 重启租约（sender/worker 池）、缓存重建、UNKNOWN 对账（`scripts/e2e` 之外的生产通道）。轮询驱动：装配区 `driver.on_startup` 起周期任务调 `poll()`（稳定窗口推进）。
2. **IncidentService → admin 推送**：把 `AdminIncidentSink`（实现 `IncidentSink.emit`，走 `domains/ops/monitor/alerts.py` 五要素管线）注入 `IncidentService(sink=...)`；默认 LoggingIncidentSink 仅落 stdlib log。控制面查询挂接：`list()/get()` 已是查询 API，后续控制面 services 层直接包一层。
3. **NapCat tail 连接点**：path 来源=NapCat workdir 日志文件（本席不读 .env 不猜路径）；接线席经配置键（建议 `bot_ops_napcat_log_path`，入 config.py+catalog+env.example 三处同生）后构造 `NapcatTailCollector(sink=ProcessLogCollector.ingest 的适配器)` 并由周期任务驱动 `poll_once()`。**注意**：log_collectors 头注「不归档控制台正文」纪律仍然有效——sink 适配器若接 ProcessLogCollector.ingest，details 应只带级别与白名单标量摘要，正文留存由接线席按需裁剪。
4. **配置键**：本席零新增 config 键（模块常量 `DEFAULT_*` 全部带注释），如需热可调由接线席按三处同生规矩登记。

## 三点五、施工进度（重跑席续记，随施工递增）

- **recovery/service.py 已落盘**（对齐占位 __init__ 全部 9 名导出 + 另导出 DEFAULT_POLICY/FailureContext）：FailureKind 6 可恢复（transient_network/rate_limited/resource_busy/dependency_degraded/stale_state/worker_stalled）+4 不可重试（invalid_input/auth_denied/permanent/**patch_required**——指南 §12「代码修复归 PATCH_REQUIRED 上报」落地为分类）；DEFAULT_ACTION_BY_KIND 六动作对齐 §12 白名单（reconnect/cooldown_backoff/drain_backlog/reconnect_dependency/reconcile_state/restart_worker）；预算缺省=每资源 600s 窗 3 次（§12「10min≤3 次」）；full-jitter 退避 base 1s cap 30s（rng 注入）；动作后验证（无 verifier=verified=None 不伪称）；稳定窗口缺省 60s 复发升级 warning→error→critical；全局风暴熔断（60s 窗 >6 次动作→熔断 600s，边沿一次 critical 上报，期满 half-open 放探测）；executor/reporter/verifier 异常全捕获 fail-open；monotonic/rng 注入离线确定性。**与 §二 计划偏差如实登记**：预算窗用 §二「10min」而非本席草稿 300s；稳定窗用 60s；可恢复类=6 类对齐 §二（本席初稿 4 类已纠正）。
- **incident/service.py + __init__ 已落盘**：结构化字段=矩阵 L72 清单（seq/timestamp/component/severity/explanation/method/trace_id/fingerprint/occurrence_count）；脱敏懒加载复用 `domains/render/plain_text.py::redact_local_secrets` 真身（§二 计划兑现）+ 本地兜底正则；`redact_text` 公开入口（采集侧共用）、`redact_user_text` 只留字数痕迹；同因聚合指纹=sha1(component|explanation 头120)[:16]，窗内抑制+stride 重通知+窗过期重发，count 累积 first_seen 保留；IncidentSink 协议+LoggingIncidentSink 缺省；查询=list_incidents/get_incident/aggregates/stats；防递归=全捕获+环 500。**偏差**：查询方法命名 list_incidents/get_incident（§二 的 list()/get() 避免遮蔽内建）；recover 面协议参数名 reporter（§三.1 草案 incidents）。
- **collectors/napcat_tail.py + __init__ 已落盘**：NapcatTailCollector（类名对齐 §二）；pull 式 poll_once 零线程零装配副作用；path 未配置=state not_configured 惰性不读（兑现）；首见锚末尾/from_start 读历史；半行残余缓冲；**二进制偏移读取**（text 模式 tell() 携解码器状态与 st_size 比较错位，已规避）；轮转=身份变化/尺寸回缩重开从头；逐行 redact_text（incident 单一事实源）+截断 2000；背压=sink False/异常→dropped_lines，无 sink 走有界缓冲丢新行；积压 >4MiB 跳跃追赶 dropped_bytes；parse_level 双形态归一 unknown 不猜。

## 四、四列状态（验收矩阵行）

| 行 | implementation | production_wiring | offline_validation | live_validation |
|---|---|---|---|---|
| V21-HEAL-001 | done(high)（统一载体 RecoveryService 落地） | not_wired（坐标见 §三.1） | done（2026-09-18 实跑 20 例 passed，见 §五） | unknown |
| V21-INCIDENT-001 | done(high)（统一载体 IncidentService+NapcatTailCollector 落地） | not_wired（坐标见 §三.2/3） | done（2026-09-18 实跑 incident 21 例+napcat_tail 18 例 passed，见 §五） | unknown |

## 五、实跑证据（S14c 断点续收席 2026-09-18 实录）

解释器=`ChatBot_Runtime/venv/Scripts/python.exe`，env `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，`--basetemp=%TEMP%/v21r2-s14c -p no:cacheprovider`，全离线：

1. **pytest 三件全绿**：`python -m pytest tests/test_v21_s14_recovery.py tests/test_v21_s14_incident.py tests/test_v21_s14_napcat_tail.py --basetemp=... -p no:cacheprovider -q` → **59 passed in 1.53s**（recovery 20 例+incident 21 例+napcat_tail 18 例）。
2. **ruff 本域六路径**（recovery/incident/collectors 三包+三测试件）→ **All checks passed!**
3. **mypy 按 dev.ps1 同口径**（`python -m mypy --explicit-package-bases --ignore-missing-imports <本域六路径>`，缓存目录放 %TEMP% 不入源码树）→ 本域 **0 错**；仅剩 2 错均在 `control_plane/api/platform.py`（79/254 行，AGENTS.md 台账 #36 与 S10/DSP 席均已登记的**全域外既有错**，非本席域、不越权代改）。注：不带 `--explicit-package-bases` 直跑会报「Source file found twice under different module names」——这是调用口径问题（包被 plugins 前缀与裸包名双计），非代码缺陷。

## 六、S14c 断点续收记录（2026-09-18）

**背景**：S14b 静默死亡。在盘遗产三件（recovery/service.py 25KB 05:43、incident/service.py 15KB 06:03、collectors/napcat_tail.py 10.8KB 06:03）+三测试件全部在位；RWOCc 席曾记红「incident/service.py:215 硬 SyntaxError」——**经本席实跑核验已不存在**（py 解析通过+incident 测试 21 例全绿，S14b 死前已自修）。

**取证结论（20 分钟内完成）**：
1. **三服务文件结构完整、与 §二 计划逐项对齐**：recovery=FailureKind(6+4 含 PATCH_REQUIRED)/RecoveryAction/DEFAULT_ACTION_BY_KIND/RecoveryPolicy/FailureContext/RecoveryOutcome/RecoveryDecision/双协议(Executor/Reporter)/RecoveryService(handle_failure+snapshot+backoff+circuit+verify+report 全内件)；incident=脱敏懒加载 render 真身+_fallback_redact+redact_text/redact_user_text/Incident/IncidentAggregate/IncidentSink/LoggingIncidentSink/IncidentService(report/list/get/aggregates/stats+fingerprint 聚合)；collectors=NapcatTailCollector(poll_once/poll_forever/drain/snapshot+轮转+背压+跳跃追赶)+parse_level 双形态。三包 `__init__` 出口与实现一致（recovery 9 名/incident 13 名/collectors 6 名）。
2. **测试 59 passed 全绿**（§五.1），无需补写任何测试或代码——S14b 遗产实际已完工，只死在「未实跑、未记日志」。
3. **napcat_tail 完成度=原旨全兑现**：惰性 not_configured/轮转重开/半行缓冲/二进制偏移/逐行脱敏截断/背压丢弃计数/4MiB 跳跃追赶/pull 式零线程，均有测试锁定。
4. **路径勘误**：实际载体在 `plugins/bot_unified_runtime/domains/ops/{recovery,incident,collectors}/`（§〇 简写 `domains/ops/` 为包内相对口径），接线席按此坐标。
5. **本席零代码改动**：只补实跑取证与本日志落盘；四列 offline_validation 由 unknown→done。

**遗留（等接线席/后续席，非本席域）**：①RecoveryService 生产 executor（NapCat 重连/worker 重启/缓存重建/UNKNOWN 对账）+周期 poll 驱动装配（§三.1）；②IncidentService→admin 推送 sink（§三.2）与控制面查询挂接；③NapCat 日志路径配置键 `bot_ops_napcat_log_path` 三处同生登记+poll 驱动（§三.3）；④生产 .env 未部署，live_validation=unknown。
