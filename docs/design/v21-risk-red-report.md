# V2.1 后端实施 · A5 高风险取证席报告（RED）
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [../snowluma-setup.md](../snowluma-setup.md)。

> 2026-09-17。只诊断不修复。每条 RED 测试 `@pytest.mark.xfail(strict=True)`——现在必须失败；
> 修复后变 XPASS→红，提醒转正为回归测试。所有结论附置信度（verified=实跑复现 / high=源码检查）。
> 命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_v21_risk_red_*.py --basetemp="$TEMP/v21-riskred3" -p no:cacheprovider`
> 实跑结果：**22 xfailed, 0 failed, 0 xpassed**（含 `-rx` 逐条核验失败原因均为设计中的缺陷）。
> 续跑补记（第三次派遣，08:00 起）：上轮 07:54 撞 1302 阵亡未留增量（四文件 mtime 均滞留 03:17）；
> 本轮补齐第二阶段报告（风险 5-8）+ 新增风险 5 出站路径取证测试
> `test_risk5_platform_side_effects_route_through_dispatcher`。截至 08:05，
> 并行修复席未动 `_app.py`（mtime 09-16 06:15），无 XPASS 转正事项。

## 全局红线结论（先于逐项）

**V2.1-GLOBAL：`create_control_plane_app` 当前在任何配置下都无法完成装配**（两条独立地雷，
见风险 1 / 风险 4）。因此现有控制面 TestClient 套件（test_control_plane_m1 / _actions_api /
_v1 等）在 platform 路由批次合入后的当前树上预期全红——"6603 passed" 基线已被打破
（本席未跑全量，此结论由装配探针直接推出，verified）。

---

## 第一阶段（风险 1-4）

### 风险 1：api/platform.py 路由把 _kind/_action/principal 放进公开参数、直操 Store 不走 Service

**证据（file:line）**
- `plugins/bot_unified_runtime/control_plane/api/platform.py:49`、`:55-56`：GET 路由用
  `lambda principal, _kind=kind: ...` —— `principal` 无注解无默认 → FastAPI 必填 query 参数
  （客户端可伪造任意值），`_kind` 带默认 → 客户端可用 query 覆盖。
- `:66-71`：`async def upsert(payload, resource_id, principal: Principal, _kind=kind)` —
  `principal: Principal` **无 Depends** → FastAPI 尝试为其建响应字段 →
  `FastAPIError: Invalid args for response field! ... Principal is not a valid Pydantic field type`，
  **路由注册即崩，整个 platform 路由无法挂载**（实跑复现）。
- `:167-173`：lifecycle 处理器 `_kind=kind, _action=action` 以默认参数进签名 → 客户端可
  `?_action=publish` 覆盖，读端点（GET versions）可触发写副作用。
- 直操 Store：`:56,71,89,147,153,159,174-222,267-273` 全部处理器直接调
  `store.get/put/versions/append`，无 Service 层（对照 config_service.py / actions.py 的服务化先例）。

**复现方式**：探针实跑 `build_platform_router(store=PlatformStore(':memory:'), read_dependency=..., write_dependency=...)` → FastAPIError（完整栈指向 `analyze_param → create_model_field`）。

**测试**（tests/test_v21_risk_red_cp_platform.py）
- `test_risk1_platform_router_builds_cleanly`（注册崩溃，verified）
- `test_risk1_handler_params_not_client_forged`（AST 结构断言，verified）
- `test_risk1_versions_get_cannot_override_action`（?_action=publish 覆盖读端点，verified）

**置信度**：verified（注册崩溃实跑；参数暴露语义由 AST+FastAPI 行为双重确认）。
**修复方向**：`principal` 一律走 `Depends(...)`、`_kind/_action` 改闭包捕获，资源读写收进
PlatformService（对齐 config_service 惯例）后再挂路由。

### 风险 2：PlatformStore 跨实例 CAS 不完整 / Trace 主键与 append 列名不一致 / 生命周期无收口

**证据**
- `control_plane/platform.py:32` 建表 `traces(trace_id TEXT PRIMARY KEY, ...)` vs `:127`
  `INSERT OR REPLACE INTO {table}(id,data)` → `sqlite3.OperationalError: table traces has no
  column named id`——POST /api/v1/traces（platform.py:143-147）必 500。**实跑复现**。
- `:76-95` put 的读版本-比较-写回：`old = self.get()`（SELECT）与 INSERT 之间无
  `BEGIN IMMEDIATE` 单事务；`self._lock`（:19）是实例内 RLock，跨实例无互斥 → TOCTOU
  丢更新。**实跑复现**：sqlite trace_callback 在读-写间隙用另一连接提交 version=99，
  `put(expected=1)` 仍成功写回 version=2（CAS 静默失守）。
- 无 `close()`/`__enter__`/`__exit__`（hasattr 实测 False）；`:58-71` get 甚至不持实例锁。
  `_app.py:464` 每次装配新建 PlatformStore 且无任何关闭路径。

**测试**（tests/test_v21_risk_red_cp_platform.py）
- `test_risk2_append_traces_column_mismatch`（verified）
- `test_risk2_cas_toctou_lost_update`（trace-hook 确定性注入读-写间隙；若修复后写路径持锁
  则注入失败→测试自动转绿，verified）
- `test_risk2_store_lifecycle_close_exists`（verified）

**置信度**：verified。
**修复方向**：traces 列名统一（建表与 append 同一列名常量）；put 用
`BEGIN IMMEDIATE` 单事务做比较+写回；补 `close()`/上下文协议并在 `_app` lifespan 收口。

### 风险 3：Persona draft/publish 仅改标记假成功、重建返回不存在的 job、未装配 setter 仍返回 applied

**证据（api/platform.py）**
- `:213-222`：draft/publish/activate 仅 `data["lifecycle"]=_action; data["draft"]=_action=="draft"`
  后 store.put——无校验、无激活产物、无 published 版本推进；response 与 GET 资源无差别
  （仅两个标记键）。假成功。
- `:256`（knowledge_reindex）与 `:277`（memory_rebuild）：返回
  `{"status":"queued","job_id": uuid4().hex}`——控制面无任何 job 登记/查询路由
  （rg "jobs" 全 control_plane 零命中路由）→ 返回查不到的幽灵 job。
- `:126-141`：`log_level_setter is None` 时仍返回 `{"level":..., "applied": True}`；而
  `_app.py:469-478` 装配 platform 路由时**从不传 log_level_setter** → 生产路径永远假 applied。

**测试**（tests/test_v21_risk_red_cp_platform.py；当前先被风险 1 的注册崩溃拦截，注册修复后
各自独立红——语义缺陷与注册缺陷叠加，故 XPASS 需两级全修）
- `test_risk3_publish_produces_real_activation`
- `test_risk3_rebuild_job_is_queryable`
- `test_risk3_log_level_honest_without_setter`（router 级直测，绕开 app 装配，单点复现 applied 假成功）

**置信度**：verified（假成功逻辑源码+测试双重；job 幽灵由 rg 路由零命中 + 测试确认）。
**修复方向**：publish/draft 接真实版本推进（active_version/published_at 落库）；job_id 登记
进可查作业表并补 GET /jobs/{id}；setter 未装配时返回 applied:false 或 503。

### 风险 4：control_plane/_app.py 局部 _path import；RuntimePorts/queue/config 注入缺口；runtime_attached 冻结

**证据（control_plane/_app.py）**
- `:324`：`from .factory import _path` 只存在于 events 分支（`if event_service is None and
  events_path:`）；`:425`（actions 块）与 `:465`（platform 块）无条件使用 `_path` →
  未配 `bot_control_plane_events_db` 的默认装配直接
  **`UnboundLocalError: cannot access local variable '_path'`**。`serve()`(:719) 走默认装配 →
  **独立启动入口 `python -m ...control_plane` 死亡**。实跑复现。
- 即便配齐 events_db，`:469-478` `include_router(build_platform_router(...))` 触发风险 1 的
  FastAPIError → **任何配置装配必炸**（实跑复现）。
- config 注入缺口：`:469-478` 调 `build_platform_router` 未传 `config`/`log_level_setter`
  （签名支持，platform.py:37-38）→ `/api/v1/media/analyze` 恒 503
  `media_config_unavailable`（platform.py:343-344），哪怕 app 层有完整 config。
- RuntimePorts/queue 注入缺口：`:393` `getattr(app.state, "send_queue", None)` 全仓无人装配；
  工厂签名 15 个散参，无任何 queue/ports 形参（`inspect.signature` 实测）；"RuntimePorts"
  rg 全包零命中——端口束概念未落地 → `queue.pause/resume/drain` 生产恒 degraded
  （`:392-408`）。
- runtime_attached 冻结：`:409-416` `napcat.status` 返回 `connected=bool(runtime_attached)`——
  装配期标量，不探测真实 OneBot 连接；测试进程无任何连接时 runtime_attached=True 即谎报
  已连接。同款冻结值还喂给 ProcessLogCollector（:334-340）与 ResourceMetricsService（:357）。

**测试**（tests/test_v21_risk_red_cp_app.py）
- `test_risk4_default_app_creation_survives_without_events_db`（UnboundLocalError，verified）
- `test_risk4_app_creation_survives_with_events_db`（FastAPIError，verified）
- `test_risk4_queue_runtime_ports_injectable`（签名断言，verified）
- `test_risk4_napcat_status_reflects_live_runtime`（当前被装配崩溃拦截，装配修复后对
  谎报行为单点变红）

**置信度**：verified（两条装配地雷实跑复现；config/queue/runtime_attached 缺口源码检查 high+）。
**修复方向**：`_path` 提为模块级导入；platform 路由先修注册再传 config/log_level_setter；
工厂增加 send_queue/RuntimePorts 形参；napcat.status 改为查询注入的实时连接探针。

---

## 第二阶段（风险 5-8）

### 风险 5：两份 Dispatcher 生产包内零接线；回戳/贴表情平台副作用 call_api 直连

**证据（file:line，2026-09-17 08:0x 实跑 rg+AST）**
- `control_plane/dispatcher.py`（门面：Dispatcher/PokeInteractionService/ReactionService/
  MemeService）与 `decision/dispatcher.py`：rg `from.*dispatcher import|import dispatcher`
  在生产包内除两个定义模块自身外**零命中**——统一派发面从未被任何 matcher/能力导入。
- 直接出站路径（绕过一切派发/审查/回执面）：
  - `__init__.py:4745-4746` `group_poke`、`:4751` `friend_poke`（回戳，处理器内
    try/except pass 静默）；
  - `runtime/reactions.py:652-655` `set_msg_emoji_like`（贴表情）、`:681-686`
    `set_message_reaction`（TG，docstring 自述"本仓库未接线触发点"，直连形态仍在）。
- `decision/dispatcher.py:25-28`：`dispatch(plan, ctx)` 恒抛 `NotImplementedError`
  （阶段 0 骨架显式失败）——engine_only 接管路径不可用。
- 边界说明：`sender/onebot.py:962`、`sender/file_gateway.py:382` 等属 SendQueue 侧既有
  发送通道，不算本风险"绕过派发"族；但 call_api 直连面整体未收口正是门面缺席的后果。

**测试**（tests/test_v21_risk_red_dispatch_and_telegram.py）
- `test_risk5_dispatcher_facade_wired_into_production`（AST import 扫描，verified）
- `test_risk5_decision_dispatcher_can_dispatch`（verified）
- `test_risk5_platform_side_effects_route_through_dispatcher`（AST 精确版 rg：四个副作用
  动作名不得以 call_api 直连出现在两份 dispatcher 之外；现状命中 __init__.py×2 +
  reactions.py×2，verified；修复后门面自身放行）

**置信度**：verified。
**修复方向**：回戳/贴表情/贴纸回应出站收敛进 control_plane Dispatcher 门面（或最小化抽
统一出站服务留审计回执）；decision dispatcher 随迁移阶段 1 首个能力接线。

### 风险 6：TG poll 阶段 catch_all=True 把鉴权/实例冲突永久归为网络故障

**证据（scripts/telegram_resilience.py）**
- `:77-79`：`poll` 覆写 `retry(lambda: original(bot), "startup", catch_all=True)`——
  catch_all 分支（:55-61）**跳过** `isinstance(exc, network_error)` 与
  `retryable(exc)` 两道分类，任何异常一律按"网络暂不可用"指数退避无限重试。
- 上游 TG 适配器把 HTTP 401（token 失效）/409（多实例 getUpdates 冲突）包装为
  NetworkError 抛出 → 两者都被永久重试：409 会形成两实例互相踢 token 的死循环，
  401 烧穿重试且永不自愈。
- 对照：`_call_api` 的 getUpdates 分支（:81-83）走 `retry(..., "getUpdates")`
  （catch_all=False），`is_transient_telegram_error`（:14）正确分类——**poll 是唯一绕过点**。

**测试**：`test_risk6_poll_does_not_retry_auth_conflict[401]/[409]`（注入 401/409 形态
NetworkError，断言不被退避吞掉直接上抛；现状进入 catch_all 退避 sleep → 确定性
`_LoopEscape` 逃逸判红，verified）。
**置信度**：verified。
**修复方向**：poll 去掉 catch_all=True，或 catch_all 分支先过 retryable 分类，
401/409 直接上抛交启动守卫/告警处理。

### 风险 7：节日表按月日跨年复用错报 + 提醒墙钟时区不统一

**证据**
- `character/temporal.py:67` `DEFAULT_HOLIDAYS_2026` 为 `(MM-DD, 名称)` 二元组表，
  `:128-130` `holiday_of` 仅按 `MM-DD` 匹配、**无年份维度**——2026 农历节日（春节 02-17）
  被原样套用到任意年份（2027 春节实为 02-06）；`:314` TemporalContext 默认也挂同一张表。
- `character/reminders.py:71-73` `_as_local = moment.astimezone()`（进程本地时区）+
  全模块 13 处调用（:82,:91-92,:215,:259,:313,:377,:421…），**从不读 config.bot_timezone**
  （config.py:254 默认 Asia/Hong_Kong）——UTC 服务器上"明天9点"墙钟推算错位（极端
  情况差一整天）。

**测试**（tests/test_v21_risk_red_tz_and_files.py）
- `test_risk7_holiday_table_not_reused_across_years`（2027-02-17 应为空，现状错报
  "春节"，verified）
- `test_risk7_reminder_wallclock_follows_config_timezone`（UTC 18:30 说"明天9点"应推
  香港 09-19 09:00，现状按进程本地时区推，verified）

**置信度**：verified。
**修复方向**：节日表加年份维度（或 holiday_of 按 day.year 选表/支持注入跨年表）；提醒链
注入 bot_timezone 统一 `_as_local` 口径（config 可达处显式传 ZoneInfo）。

### 风险 8：.xls/.ppt 伪装现代 OOXML 解析 → 读取链崩溃

**证据（sources/file_reader.py）**
- `:122` `if ext in {".xlsx", ".xls"}:` 旧 OLE 二进制并入 openpyxl 分支；
  `:137` `if ext in {".pptx", ".ppt"}:` 并入 python-pptx 分支。OLE2 魔数（D0CF11E0）
  文件被当 OOXML 解析，openpyxl 抛 `InvalidFileException`、python-pptx 抛
  `PackageNotFoundError`——均**不在** except `(ImportError, OSError, ValueError, TypeError)`
  元组（:140, :153）内 → `read_supported_file` 直接抛，控制面 `/files/read` 变 500。

**测试**：`test_risk8_legacy_office_not_misparsed[legacy.xls/legacy.ppt]`（OLE2 魔数文件，
断言诚实降级不抛异常，verified）。
**置信度**：verified。
**修复方向**：.xls/.ppt 拆独立分支并前置 OLE 魔数嗅探；旧格式不可读时返回
`{"status": "parser_unavailable"}` 诚实降级（对齐 .pdf 分支先例）。

---

## 终态汇总

| # | 风险 | 测试数 | 置信度 |
|---|---|---|---|
| 1 | platform 路由公开参数/直操 Store | 3 | verified |
| 2 | PlatformStore CAS/Trace/收口 | 3 | verified |
| 3 | Persona 假成功三件套 | 3 | verified |
| 4 | _app.py 装配地雷/注入缺口/runtime_attached | 4 | verified |
| 5 | 双 Dispatcher 零接线+出站直连 | 3 | verified |
| 6 | TG catch-all 误归类 | 2 | verified |
| 7 | 节日跨年+提醒时区 | 2 | verified |
| 8 | .xls/.ppt 伪装解析 | 2 | verified |

合计 22 条 RED，全部 `xfail(strict=True)` 实跑确认（0 failed / 0 xpassed）。
八项清单全覆盖，无不可测项。修复席接手后跑同一命令：任何 XPASS 即该风险已修，
按"转正为回归测试"流程处理。
