# 笔记与授时 · NTP 授时与钟差钳制

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B04.notes · NTP 授时与钟差钳制

- 层级：一级 B04 → 二级 notes → 三级 `time-sync`
- 实现落点：`plugins/bot_unified_runtime/domains/notes/capabilities/notes.py`、`plugins/bot_unified_runtime/domains/notes/store`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

联网授时：纯 stdlib SNTP 客户端（socket+struct 手搓固定长度的 SNTP 报文，报文长度以该实现为准、零第三方依赖、零子进程）为提醒/笔记时序提供校正时间。只算偏移量不碰系统钟——`now()` 返回「系统钟 + offset」的 aware 本地时间。NTP 全败后走 HTTPS `Date` 响应头估算偏移（R3 停摆批增补，治生产 UDP 123 被墙），失败链 NTP → HTTPS → 系统钟。

> 落点勘误：本页生成头写的是 `domains/notes/…`，而真身在 `plugins/bot_unified_runtime/domains/schedule/timesync/timesync.py`（声明源 `domains/core/board_taxonomy.py` 的 B04.notes 条目未含此路径）。正文按真身写，不动生成区与声明源。

## 怎么调用

- `domains/schedule/timesync/timesync.py::configure_from(config)` 绑定真实配置得到共享 `TimeSync`，模块级 `now()` 为取值口；未绑定过配置的进程（单测、纯函数调用）默认离线——`now()` 就是系统钟，零网络零等待。
- 生产接线：提醒链路 `build_reminder_store` 与能力构建处用真实 config 绑定（`config.py` 字段恒在即自然启用）。报文与应答校验的内部步骤（`_unpack_ntp_timestamp`、originate 逐字节比对、端口/stratum/LI/mode 检查）都在本文件内，不依赖别处。

## 开关与参数

- `bot_time_sync_enabled`（缺省 True）、`bot_time_sync_servers`（逗号分隔，缺省含 `ntp.aliyun.com` 等）、`bot_time_sync_max_drift_ms`（缺省 1500——偏移可信度的绝对上限，超了的服务器应答整台拒收）、`bot_time_sync_http_enabled`（缺省 True；字段缺失＝不启用，保住离线测试零网络）、`bot_time_sync_http_url`（可换 HTTPS 端点；只收 `https://`，明文 http 可被中间人伪造不作授时源）。逐键现值以 `config.py` 与 `docs/config-catalog-full.md` 为准。
- 缓存节奏：校准成功后按 `resync_seconds` 这么久不再联网、失败后按 `retry_seconds` 冷却，两个值均为准模块常量的默认值，以 `TimeSync` 构造参数为准。

## 失败时看到什么

对用户无感——这是内部时序件，不出卡片不回话。可观测面是日志：每台服务器一行、级联降级（NTP→HTTPS→系统钟）逐级点名；「全部 NTP 服务器不可达」告警是 HTTPS 兜底增补的实弹根因。缓存过期后重校失败按「全失败」处理：丢弃旧偏移、回退系统钟并告警，宁可显式回退不用陈旧偏移。应答不可信的判据（RTT 超 10s、originate 不匹配、来源端口非 123、stratum 0 或 >15、LI=3、mode≠4）全部是拒收换下一台，不静默采信。

## 测试与验收

`tests/test_timesync.py`（报文/钳制/回退链）、`tests/test_v21r2_stall_timesync_http.py`（HTTPS 兜底与停摆场景）。真机：重启后看校时日志即可证成否；UDP 123 被拦时走 HTTPS 兜底、再不行回退系统钟，属模块自述的预期降级链。首次校时的具体启动延时未在本件代码内核实（装配层调度决定），如需精确值查根装配处。
