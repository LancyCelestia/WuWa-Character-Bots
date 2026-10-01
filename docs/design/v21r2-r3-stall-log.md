# V21R2 R3 席（停摆/吞吐/授时族）工作日志 — 2026-09-17/18

> 术语说明：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](../snowluma-setup.md)。

> 状态：**完成**。四处改造全部落地，新增测试 26 例 + 受影响存量回归 106 例 = **132 passed**（终跑 2026-09-18，命令与输出见 §四）；ruff 七文件 All checks passed；mypy 本域 0 错（全树余 2 错均在 `control_plane/api/platform.py`，AGENTS.md #36 已登记既有，非本席域）。未 commit、未部署（共享工作树纪律）。

## 一、根因证据链（停摆/吞消息/axonhub 无新请求）

现象：①bot 有概率吞消息不回复；②用户 22:25 实测 axonhub 最新请求停在半小时前，nonebot/NapCat 显示正常、控制台无报错；③kb_wiki_sync 停机时还在跑（一次 75683 文档/238453 块）。

完整机制链（全部源码级 verified）：

1. **同步 job 落在事件循环默认线程池**：`__init__.py:1787` `_register_kb_wiki_sync_scheduler` 的 `_sync_job` 是同步函数 → nonebot_plugin_apscheduler 用 stock `AsyncIOScheduler()`（插件 `__init__.py`：`scheduler = AsyncIOScheduler()`，无自定义 executor）→ apscheduler `executors/asyncio.py:8-13,47`：「All other functions are run in the event loop's default executor」→ `loop.run_in_executor(None, ...)`。即 kb_wiki 同步与 pipeline.py:76-83 注释点名的共享默认池（min(32, cpu+4)，语音转码/TG 下载等 to_thread 用户）同池。
2. **库体量**：`ChatBot_Runtime/data/kb_wiki_embeddings.sqlite3` 实测 **5.67 GB**（每行同时存 `vector_json` 文本 ~20KB + `vector_blob`）；faiss 1.15.0 可用、ANN 文件在位。
3. **检索锁内全表载入（最重一击）**：`vector_knowledge.py` `retrieve()`（改前行 929-962）在 `with self._lock:` 内调 `_vector_candidates`（行 933）→ `_load_vector_cache`（行 1049）→ **全表 `fetchall()` 同时物化 vector_json 文本 + vector_blob**（改前行 1259-1266）。缓存失效后（`sync_documents` 尾部 `_invalidate_vector_cache`，行 863）的首次检索＝检索锁持有期间把 ~5.7GB 拽进 Python 堆 + 分钟级 JSON 解析；ANN 缺失/签名失配（嵌入 partial 失败窗口、faiss 早期缺装）时每条消息都走此路。锁内一行注释自证设计假设被打破：「锁内只保留 …候选索引一致读这些**快操作**」（行 913-915）——23.8 万块语料下它不再快。
4. **吞消息面**：全部会话检索在该锁后排队 → 聊天能力（chat 专用池 8 workers + 提交闸 2N=16，`pipeline.py:84,184-198`）逐个卡死 → 闸满后 `offload_capability`（pipeline.py:225-239）`try_acquire` 失败 → `_pipeline_busy_result`（pipeline.py:201-222）**SILENT_AUDIT 静默快败，零外发**＝「吞消息」的直连机制（这是既有的故意降频设计，故障时被放大成全量吞）。
5. **LLM 发不出去面**：GB 级分配 + 页交换抖动拖垮全进程（loop 也卡）；默认池被长任务（kb 嵌入 23.8 万块 @~19 块/s ≈ 3.5h；零变更夜 ANN 全量重建实测 8.5 分钟——`../ChatBot_Runtime/logs/bot_stdout.log:640-641`：00:20:11 Scheduler Started → 00:28:47 kb-sync done，added/changed 全 0 却耗时 8.5 分钟）占线 → 消息进得来（WS 在）但能力跑不完/发不出 → axonhub 静默。
6. **运行日志覆盖窗**：`bot_stdout.log` 最后一行止于 09-16 00:28，22:25 停摆窗不在其中（log 面取证到此为止；机制链已闭合）。

## 二、改动清单（全部在本席文件域内）

### 1. `plugins/bot_unified_runtime/character/vector_knowledge.py`（检索停摆根治）
> 域判定说明：任务书明示「你定位到的 kb-wiki 同步实现文件」归本席；该文件是 kb_wiki 同步/检索的 store 层，与 R4 affinity 域无关。并行席位（search_scored/文件代际）改动区与本席改动函数零重叠，Edit 新鲜度校验全程通过。

- `_load_vector_cache` 重写：**流式 `fetchmany`（批 2048）+ blob 优先**；`vector_json` 只对 blob 缺失/损坏的残行按批（500/批 IN 查询）二次取。消除 5.7GB fetchall 尖峰与全量 JSON 解析。
- 新增 `_build_vector_cache`：构建期**不取检索锁**（锁序：`_lock → _vector_cache_build_lock` 单向，防环）。
- 新增 `_vector_cache_build_lock`（单飞构建）+ `_vector_cache_generation`（世代号；`_invalidate_vector_cache` 递增——与并行席新增的 `invalidate_runtime_caches()` 自动协同）。
- 新增 `_prewarm_vector_cache` + `retrieve()`/`search_scored()` 入口各一行调用：**GB 级载入移出检索锁**，进锁后命中热缓存瞬时返回；构建期间发生新失效按世代号丢弃；全程 fail-open。
- 常量 `_VECTOR_CACHE_LOAD_BATCH_SIZE = 2048`。

### 2. `plugins/bot_unified_runtime/character/kb_wiki.py`（同步任务治理）
- `_SYNC_TASK_MUTEX`：`run_kb_sync_task` 进程级互斥，撞车方立即返回 `error_kind=busy`（`__init__.py` 两个 job-id：`kb_wiki_sync_daily` 23:40 与 `kb_wiki_sync_startup` +45s 可并发，此前面无互斥）。
- 协作式可取消：`KbSyncCancelled(BaseException)`（穿透内层 `except Exception` 吞并）+ `cancel_kb_sync_task(reason)` + `_cancel_aware_progress` 包装 on_progress/embed_progress（批边界检查：同步每 500 文档、嵌入每批≈7s@19块/s；断点天然在库：sync 每 500 文档一提交、embed 每批落向量行，重跑自动续传）。出口消费取消状态，陈旧请求最多取消一轮不毒化后续。
- **零变更夜跳过 ANN 全量重建**：`added+changed+removed>0 ∨ embed_done>0 ∨ ANN 文件缺失` 才重建；否则 `ann_reason="unchanged_skip"`。省掉每晚 8.5 分钟默认线程池占用。模型指纹变化的 healing 走 CLI 全量（auto_reset），且旧逻辑对指纹失配夜重建反而把旧向量贴新签名（错上加错），跳过更诚实。
- 结果模板收敛 `_empty_kb_result`（busy 路径与主体共用同形）。

### 3. 新增 `plugins/bot_unified_runtime/runtime/loop_watchdog.py`（轻量看门狗）
- 心跳：每 5s 一拍，实际间隔 ≥ interval+3s → warning 带滞后秒数；抑制窗 60s。
- 池饱和：O(1) 探测 `_BoundedSubmissionGate`（pipeline.py 在途/许可），满载 warning 带 `in_flight/permits`；抑制窗 300s；探测失效降级停用（不逐拍重试）。
- 只观测不自愈；`monotonic/sleep/pool_probe` 全可注入（测试零等待）。`start_loop_watchdog()/stop_loop_watchdog()` 进程级共享实例。

### 4. `plugins/bot_unified_runtime/runtime/timesync.py`（HTTPS 授时兜底）
- 失败链 NTP → HTTPS → 系统钟，每级一行日志；整体回退告警保留「回退系统钟」锚字（存量断言依赖）。
- `_parse_http_date`：`email.utils.parsedate_to_datetime`（RFC 7231 IMF-fixdate 首选 + RFC850/asctime 旧格式 naive 补 GMT）；1970 前/畸形拒收。
- `_https_head_factory`：stdlib `http.client` HEAD、`Connection: close`；**仅收 https://**（明文 http 时间可中间人伪造，不作为授时源）。
- `_query_http`：θ = server + 0.5 − (t0+t3)/2（Date 1s 粒度截断 → +0.5s 量化居中 ±0.5s）；状态码收 2xx/3xx；RTT 复用 `_MAX_RTT_SECONDS=10s`；钳制复用 `_apply_offset`（与 NTP 同口径 ±1.5s）。
- `configure_from` 新键绑定：`bot_time_sync_http_enabled`（**字段缺失=不启用**，与 enabled 同款口径，保住既有离线测试零网络）、`bot_time_sync_http_url`（空=内置 `https://www.baidu.com,https://www.taobao.com,https://www.qq.com`）；签名五元组，幂等复用不变。
- ⚠ **后续更正（2026-09-29，写在最接近的旧断言旁边；本节上面五条按 v21r2 当时的实现保留原样）**：
  - 本节标题写的 `runtime/timesync.py` 是**当时**的路径；真身现已在 `domains/schedule/timesync/timesync.py`，旧路径既不存在也无垫片（同类勘误见 `docs/boards/B04-memory-knowledge-notes/README.md`）。
  - 上行内置表 `baidu,taobao,qq` ＝**当时值**。taobao 已于 2026-09-29 移出：它的 `Date` 头自己就是错的（同日实测 −62.5s，09-27 生产日志三读数 −64～−89s——像边缘缓存值而不是钟）。现值以 `DEFAULT_HTTP_TIME_URLS_RAW` 为准，只留**不同供应商**两家而不是多堆端点：互证那一级要的是"两家独立说同一件事"，同家两台一起错会伪造出共识。
  - 本节通篇默认 NTP 腿是通的 ⇒ 事实是**它从来没通过**。默认套接字工厂当时是 `socket.socket`（缺省型 SOCK_STREAM=TCP），而 SNTP 跑 UDP/123；Windows 上对未连接的 TCP 套接字 `sendto` 不报错、只是静默丢包，`recvfrom` 一路等到超时，于是每轮白等 3×2s 才落到本节这条 HTTPS 兜底上（TS-SOCKET 修：工厂缺省改 `_udp_socket()`，显式 `SOCK_DGRAM`）。单测每枚都注入 `socket_factory`，没人踩过默认那段。本机实测（生产缺省，2026-09-29）：修前一轮 6.17s 且读数漂（+0.082s / +0.942s），修后 0.06s 且稳定（+0.485s / +0.481s，直取 `ntp.aliyun.com`）。
  - 上行的**结论**（NTP 腿从未走通、每轮白等完才落到本节这条兜底）不变，但**机制讲错了**（2026-09-29 复测更正，可复跑：只读驱动真类、把 `socket_factory` 在 `_udp_socket` 与 `socket.socket` 之间对切，其余参数一律取生产缺省）：真形态＝对未连接的 TCP 套接字调 `sendto(data, addr)` **本身就阻塞**，到套接字超时那一刻抛 `TimeoutError`，压根到不了 `recvfrom`；异常被 `_query_server` 的 `except OSError` 咽成「这一台没应答」，于是每台白等一个 `timeout`（时长与台数的真身＝`TimeSync` 构造参数默认值 + `DEFAULT_SERVERS_RAW`，上行「3×2s」是当时的手抄，不再当现值）。本席实测（2026-09-29 当时值）：TCP 旧形态一轮 `6.06s`、`offset=None`、回退行读数栏「无一个源应答」；UDP 形态一轮 `0.06s`、偏移 `+0.391s`（`ntp.aliyun.com`）。总时长＝**每台一次**超时而非每台两次，正是"卡在 `sendto`"的反证。
  - **顺带把防火墙这笔账销掉**（2026-09-29 复测更正）：本节与 `全部时间源不可达` 那行告警都**不是墙**——换对套接字后 NTP 腿当场就通，本机 UDP/123 可达，「生产 UDP 123 被墙」这个 R3 批当年的动机没有实证。误判之所以活得久：TCP 那一轮每台都「没应答」，打出来的日志与真被墙一模一样。现役口径与判据看 `docs/boards/B04-memory-knowledge-notes/notes/time-sync.md`。
  - 上行「钳制复用 `_apply_offset`（与 NTP 同口径 ±1.5s）」里**同口径**这件事仍然成立（单源口径一字未动），但那个「±1.5s」是**当时值**：现值真身＝`DEFAULT_MAX_DRIFT_MS`（配置键 `bot_time_sync_max_drift_ms` 可改，本日志不抄数），别把它读成写死的绝对阈值。被**修正**的是同一句里那句「钳制口径内」所暗示的精度——HTTPS 读数的精度真身讲在该文件 `_query_http` 的 docstring 里（2026-09-29 改口：建连整段落在采样窗内，慢链路会把好钟虚报成超限），现役叙述面看 `docs/boards/B04-memory-knowledge-notes/notes/README.md` 的降级链条目。此外**整轮被全拒后不再直接回退**：新增多源互证一级（TS-CONSENSUS），失败链扩为 NTP → HTTPS → 多源互证 → 系统钟，回退 warning 带上本轮各源读数。旧形把"本机钟本来就偏 1.6s"钉成永远修不好（离线对着真类现算：偏 1.4s 可校、偏 1.6s 起永久失败）。资格尺真身 = `timesync.py` 模块头 `_CONSENSUS_*` + `_consensus_offset`/`_commit_consensus`，锁在 `tests/test_v21r2_stall_timesync_http.py` 的 TS-CONSENSUS 组；现役口径看 `docs/boards/B04-memory-knowledge-notes/notes/time-sync.md`。

### 5. 配置三处同生
- `config.py`：`bot_time_sync_http_enabled: bool = True` / `bot_time_sync_http_url: str = ""`（追加在 bot_time_sync 键块后，带 R3 批注释）。
- `.env.example`：`BOT_TIME_SYNC_HTTP_ENABLED=true` + `BOT_TIME_SYNC_HTTP_URL=`（带注释行）。
- `docs/config-catalog-full.md`：A26 增量表新增 `_time_sync_http_enabled`/`_time_sync_http_url` 行。

## 三、需其他席位代改的坐标（本席未触碰禁触文件）

| 坐标 | 归属 | 代改内容 |
|---|---|---|
| `plugins/bot_unified_runtime/__init__.py`（R5）：driver on_startup 区（参考锚点：`_register_kb_wiki_sync_scheduler(scheduler, config)` 调用点 ~行 3912 附近的装配区；或任一 `driver.on_startup` 挂接区） | R5 | `from .runtime.loop_watchdog import start_loop_watchdog`；startup 内 `start_loop_watchdog()`。可选优雅停机：`stop_loop_watchdog()`（不挂也能随 loop 销毁自然结束） |
| `bot.py`（R2b）：停机序列 | R2b | 可选：停机起手处 `from plugins.bot_unified_runtime.character.kb_wiki import cancel_kb_sync_task; cancel_kb_sync_task(reason="shutdown")`——让数小时级 kb 同步协作退出（断点在库，重启续跑）。bot.py:376 已注明停机不等 kb 任务，本调用只是加速收尾+省电 |
| 观测面（可选） | 任意 | `/bot runtime` 等可暴露 `loop_watchdog._SHARED_WATCHDOG` 最近滞后/池在途数（当前无此接口，本席未加） |

## 四、实跑证据（终稿）

解释器固定 `ChatBot_Runtime/venv/Scripts/python.exe`，env `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，pytest `--basetemp=$TEMP/v21r2-r3b -p no:cacheprovider`。

1. **vector_knowledge 改后（第一刀）**：`pytest tests/test_kb_wiki_sync.py tests/test_knowledge_mtime_cache.py` → **17 passed**；全部触 store 测试（test_auditfix_main_character/test_knowledge_mtime_cache/test_kb_wiki_sync/test_moegirl_question_fix/test_perf_p1/test_sdd9_n3re）→ **55 passed**。
2. **kb_wiki 治理改后（第二刀）**：`pytest tests/test_kb_wiki_sync.py tests/test_knowledge_mtime_cache.py` → **17 passed**。
3. **新增三测试文件（终版）**：`pytest tests/test_v21r2_stall_timesync_http.py tests/test_v21r2_stall_watchdog.py tests/test_v21r2_stall_kbsync.py -q` → **26 passed in 1.88s**（EXIT=0）。
4. **受影响存量回归（终版合并跑）**：test_timesync + test_kb_wiki_sync + test_knowledge_mtime_cache + test_doc_sync_gates（config-catalog 覆盖门禁，验证两新键三处同生）+ test_pipeline_review_fixes + test_bgroup_chat_pipeline + test_auditfix_main_character + test_moegirl_question_fix + test_perf_p1 + test_sdd9_n3re → **106 passed**。
5. **终跑合计**：新增 26 + 存量 106 = **132 passed in 4.42s**（EXIT=0）。
6. **静态门**：`ruff check`（timesync/loop_watchdog/kb_wiki/vector_knowledge + 三测试文件）→ **All checks passed**；`mypy --explicit-package-bases --ignore-missing-imports`（同四源文件）→ **本域 0 错**（余 2 错 `control_plane/api/platform.py:79,248` 为 AGENTS.md #36 登记既有）。
7. **树卫生**：源码树 `__pycache__/*.pyc/.pytest_cache` 零命中（HYGIENE_OK）；Runtime 只读未写。

调试插曲（均非产品缺陷）：
- watchdog 生命周期测试首版用假 sleep（无让位点）+无限 run 循环饿死事件循环致 pytest 挂起 7 分钟→改真实 asyncio.sleep（测试已留注释锚点）。
- 并行席一度删除 `capabilities/weather.py`（git " D"）致包级 import 断裂，两席改动区零重叠、等待其恢复后重跑自愈（其收口后该文件状态 " M"）。
- `_cancel_aware_progress` 首版签名 1 参，嵌入进度回调是 `(done, total)` 两参（TypeError 被 except Exception 兜成 error_kind=exception）——测试当场抓到，改 `*args` 转发；这正是取消链测试存在的价值。

## 五、遗留与建议

1. `_pending_rows()`（vector_knowledge.py）仍 fetchall 23.8 万行 content（~0.5GB，仅在同步线程内、不在消息链上）——建议后续流式化（`_batches` 需要序列，改造牵连 embed 主循环，本轮未动）。
2. 检索热路径缓存常驻 ~976MB 矩阵（23.8 万×1024 float32）是既有设计；更彻底的方案（分片/磁盘 mmap 索引优先）建议在 B 线规格下另立。
3. `search_scored`（并行席新增）已同享锁外预热；若其后续改造 retrieve 分段，请保留 `_prewarm_vector_cache` 在进锁前的调用位置。
4. ANN 签名失配 + 零变更的组合会停留在暴力通道（诚实降级）；healing 建议走 CLI 全量重嵌（既有口径）。

## 六、INT 席挂接记录（2026-09-18，R3b 移交两处挂接落地）

> §三两坐标已由 INT 席代挂完成；其中看门狗挂接点对 §三首选坐标做了必要修正（见 §6.1）。未 commit、重启生效。

### 6.1 `__init__.py`：watchdog 挂 driver.on_startup（修正 §三首选坐标）

- **坐标**：`plugins/bot_unified_runtime/__init__.py:3364-3384`，`_register_nonebot_handlers()` 函数体内、nonebot 初始化守卫（3357-3362）之后、`config = Config.model_validate(...)` 之前。
- **对 §三坐标的修正及理由**：§三首选锚点「装配区 3931（`_register_kb_wiki_sync_scheduler` 调用点）附近直调」不可行——`_register_nonebot_handlers()` 在模块 import 期被同步调用（:8124），彼时**无 running loop**；`start_loop_watchdog → LoopWatchdog.start → asyncio.get_running_loop().create_task` 在 import 期必抛 RuntimeError。改按 §三备选挂 `@get_driver().on_startup` 异步钩子 `_start_loop_watchdog_on_startup`（async 钩子被 await 在主运行循环上，与 bot.py `_install_quiet_loop_exception_handler` 同一机制）。
- **fail-open**：双层 try/except——钩子体内 `start_loop_watchdog()` 失败→`logging.getLogger(__name__).warning(..., exc_info=True)` 一行、启动不阻塞；注册/导入失败（如 nonebot 环境异常）→同样一行 warning、装配不阻塞。注：stdlib logging + exc_info 已满足 ruff BLE001 豁免条件，故此处**不加** `# noqa: BLE001`（加了反触发 RUF100，bot.py 的 loguru 风格则相反）。
- **端到端实证**（nonebot.init + 插件导入，throwaway 进程）：`_startup_funcs == ['_start_loop_watchdog_on_startup', '_start_scheduler']`（居首位，早于 apscheduler 启动钩子）；手动 await 该钩子后 `_SHARED_WATCHDOG._task` 存在且未完成、任务名 `loop-watchdog`。

### 6.2 `bot.py`：停机序列挂 cancel_kb_sync_task（§三可选坐标落地）

- **坐标**：`bot.py:389-407`，新增独立 `@driver.on_shutdown` 钩子 `_cancel_kb_sync_on_shutdown`，紧跟 `_early_shutdown_scheduler_stop`（368-387）之后、`driver.register_adapter(OneBotV11Adapter)` 之前。
- **FIFO 序实证**：NoneBot on_shutdown 按注册序 FIFO；冒烟实测 `_shutdown_funcs == ['_early_shutdown_scheduler_stop', '_cancel_kb_sync_on_shutdown', '_stop', '_', '_shutdown_scheduler', 'cleanup', 'shutdown']`——本钩子第 2 拍执行，早于插件 `_shutdown_scheduler`。
- **语义**：`shutdown(wait=False)` 只能取消排队 job；**已开跑**的 kb 同步线程（loop 默认线程池）停不住——取消位令其在下一个批边界退出（断点在库，重启续跑），数小时级同步不再拖住进程收尾（与 bot.py:376 既有注释口径一致：停机不等 kb 任务，只加速收尾）。
- **fail-open + import 风格**：钩子体内惰性 `from plugins.bot_unified_runtime.character.kb_wiki import cancel_kb_sync_task`（**不在 bot.py 顶部 import**——bot.py:450-462 明令插件未加载成功时不得导入其子模块，停机时刻插件必已加载无此陷阱；与既有钩子的函数内 import 风格一致）；调用 `cancel_kb_sync_task(reason="shutdown")`，异常只记一行 `nonebot.logger.debug` 绝不反噬停机。
- **端到端实证**：导入 bot.py（完整 init，不 run）后钩子在册；直接调用该钩子可执行无异常（取消位仅置 throwaway 进程内存 event，零生产副作用）。

### 6.3 回归证据（解释器=Runtime venv，env PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0）

1. `pytest tests/test_v21r2_stall_watchdog.py tests/test_v21r2_stall_kbsync.py tests/test_nonebot_startup_boundary.py tests/test_v21r2_lifecycle_r2.py tests/test_bot_supervisor.py tests/test_startup_queue_warning.py tests/test_control_plane_lifecycle.py tests/test_smoke_config.py --basetemp=$TEMP/v21r2-int -p no:cacheprovider` → **84 passed, 1 warning in 4.02s**（R3b 新测试 + 启动/停机/装配/守护相关存量全绿；noqa 修剪后最终态复跑同 **84 passed**）。期间两遇并行重组席在飞瞬态致收集期 ModuleNotFoundError（capabilities/fx.py 短暂 " D" ~60s 自愈；domains/link_parse/parsers/http_util.py 新路径缺位 ~7min 落盘），与 R3b 曾遇 weather.py 同型、与本席改动零交集，退避重跑自愈。
2. 插件导入冒烟 + watchdog 端到端（见 §6.1）→ `PLUGIN_IMPORT_SMOKE_OK`；bot.py 导入 + 停机钩子序与可执行性（见 §6.2）→ `BOTPY_SHUTDOWN_SMOKE_OK`。
3. `ruff check bot.py plugins/bot_unified_runtime/__init__.py` → **All checks passed**。
4. mypy（--explicit-package-bases --ignore-missing-imports 两改动文件）：本席改动行 **0 新增错**；bot.py:286/296/299 三错位于 `_rate_limited_log_filter` TG 韧性区＝R2 席已收官的未提交 WIP（git diff -U0 hunk 归因实证：本席 bot.py 仅 `@@ -345,0 +368,40 @@` 一段，与其零交集）；control_plane/api/platform.py:79,248 两错为 AGENTS.md #36 登记既有。
5. 树卫生：`__pycache__/*.pyc/.pytest_cache` 源码树零命中；Runtime 只读未写。
