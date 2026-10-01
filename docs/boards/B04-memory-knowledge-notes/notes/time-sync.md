# 笔记与授时 · NTP 授时与钟差钳制

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B04.notes · NTP 授时与钟差钳制

- 层级：一级 B04 → 二级 notes → 三级 `time-sync`
- 实现落点：`plugins/bot_unified_runtime/domains/notes/capabilities/notes.py`、`plugins/bot_unified_runtime/domains/notes/store`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

联网授时：纯 stdlib SNTP 客户端（socket+struct 手搓固定长度的 SNTP 报文，报文长度以该实现为准、零第三方依赖、零子进程）为提醒/笔记时序提供校正时间。只算偏移量不碰系统钟——`now()` 返回「系统钟 + offset」的 aware 本地时间。NTP 全败后走 HTTPS `Date` 响应头估算偏移（R3 停摆批增补；该批当时的动机写作「治生产 UDP 123 被墙」，**2026-09-29 复测更正：被墙不是原因**，生产走兜底是我们自己的套接字类型所致，见「怎么调用」的套接字工厂一段）；单源钳制把这一轮全部读数拒光时，再走一级多源互证（TS-CONSENSUS 2026-09-29 增补，见「失败时看到什么」）。失败链 NTP → HTTPS → 多源互证 → 系统钟，每级一行日志。

> 落点勘误：本页生成头写的是 `domains/notes/…`，而真身在 `plugins/bot_unified_runtime/domains/schedule/timesync/timesync.py`（声明源 `domains/core/board_taxonomy.py` 的 B04.notes 条目未含此路径）。正文按真身写，不动生成区与声明源。

## 怎么调用

- `domains/schedule/timesync/timesync.py::configure_from(config)` 绑定真实配置得到共享 `TimeSync`，模块级 `now()` 为取值口；未绑定过配置的进程（单测、纯函数调用）默认离线——`now()` 就是系统钟，零网络零等待。
- 生产接线：提醒链路 `build_reminder_store` 与能力构建处用真实 config 绑定（`config.py` 字段恒在即自然启用）。报文与应答校验的内部步骤（`_unpack_ntp_timestamp`、originate 逐字节比对、端口/stratum/LI/mode 检查）都在本文件内，不依赖别处。
- 套接字工厂（TS-SOCKET，2026-09-29）：`TimeSync` 的 `socket_factory` 缺省落到 `_udp_socket()`，**必须**显式 `socket(AF_INET, SOCK_DGRAM)`。SNTP 跑在 UDP/123，而 `socket.socket()` 的缺省型是 SOCK_STREAM（TCP）。失败真形态（本席 2026-09-29 实测，回环与黑洞地址同形）：对未连接的 TCP 套接字调 `sendto(data, addr)` **本身就阻塞**，到套接字超时那一刻抛 `TimeoutError`，**根本走不到 `recvfrom`**；异常被 `_query_server` 的 `except OSError` 咽成「这一台没应答」，于是每台白等一个 `timeout`（时长真身＝`TimeSync` 构造参数默认值，本文不抄数）、整轮一个读数都拿不到。⚠ 旧文案「`sendto` 不报错、只是静默丢包、`recvfrom` 一路等到超时」**是错的**（2026-09-29 复测更正）：两种说法的可观测结论一样（NTP 腿走不到），但烧时间的是哪一次调用不一样——实测一轮总时长＝**每台一次**超时、不是每台两次，只对得上「卡在 `sendto`」。改之前这里就是 `socket.socket`，于是 NTP 腿每轮白等完超时才转 HTTPS，**生产从未收到过一个 NTP 应答**；单测全绿是因为每一枚都注入 `socket_factory`，量具把被测那段跳过去了。
- 与防火墙无关（2026-09-29 本席复跑坐实）：只读驱动真类、其余参数一律取生产缺省，只把 `socket_factory` 在 `_udp_socket` 与 `socket.socket` 之间对切——UDP 腿一轮 `0.06s`、偏移 `+0.391s`（直取 `ntp.aliyun.com`；两处均为 2026-09-29 当时值），TCP 旧形态一轮 `6.06s`、`offset=None`、回退那行的读数栏是「无一个源应答」。⇒ **本机 UDP/123 可达**，「生产 UDP 123 被墙」没有实证；这个误判之所以活得久，是因为 TCP 那轮每台都「没应答」，打出来的正是 `全部时间源不可达或偏移不可信` 那一行——看着与墙一模一样。别席更早的同机对照（2026-09-29 当时值）：修前一轮 6.17s 且读数漂（+0.082s / +0.942s），修后 0.06s 且稳定（+0.485s / +0.481s）。

## 开关与参数

- 键面：`bot_time_sync_enabled`、`bot_time_sync_servers`、`bot_time_sync_max_drift_ms`、`bot_time_sync_http_enabled`、`bot_time_sync_http_url`（逗号分隔；`http_url` 留空即落到内置表）。逐键缺省值与现值以 `config.py` 和 `docs/config-catalog-full.md` 为准，本文不抄数字；两张内置名单的真身是模块常量 `DEFAULT_SERVERS_RAW` 与 `DEFAULT_HTTP_TIME_URLS_RAW`。
- `bot_time_sync_max_drift_ms` 的口径要读准：它是**单源**信任上限——某一家独自说话、偏移超此即整台拒收。这个语义 2026-09-29（TS-CONSENSUS）**一字未动**；动的是它下面多了一级互证出口，见「失败时看到什么」。旧形态的坑就在这：需要校正的量一旦超过上限，唯一正确的读数也必然超限，于是"本机钟本来就偏了 1.6s"被钉成**永远修不好**（离线对着真类现算：偏 1.4s 可校、偏 1.6s 起永久失败，每轮都以回退收场）。
- HTTPS 内置表 2026-09-29 移出 taobao：它的 `Date` 头自己就是错的（同日实测 −62.5s，09-27 生产日志三读数 −64～−89s——像边缘缓存值而不是钟）。留下的是**不同供应商**两家而不是多堆端点：互证那一级的资格是"两家独立说同一件事"，同家两台一起错会伪造出共识。`bot_time_sync_http_enabled` 字段缺失＝不启用（保住离线测试零网络）；端点只收 `https://`，明文 http 时间可被中间人伪造，不作授时源。
- 缓存节奏：校准成功后按 `resync_seconds` 这么久不再联网、失败后按 `retry_seconds` 冷却，两个值均为准模块常量的默认值，以 `TimeSync` 构造参数为准。

## 失败时看到什么

对用户无感——这是内部时序件，不出卡片不回话。可观测面是日志：级联降级（NTP→HTTPS→多源互证→系统钟）逐级点名；「全部 NTP 服务器不可达」告警是 HTTPS 兜底增补的实弹根因。缓存过期后重校失败按「全失败」处理：丢弃旧偏移、回退系统钟并告警，宁可显式回退不用陈旧偏移。应答不可信的判据（RTT 超上限、originate 不匹配、来源端口非 123、stratum 0 或 >15、LI=3、mode≠4）全部是拒收换下一台，不静默采信；上限数值以 `timesync.py` 模块头常量为准。

- **互证这一级**（TS-CONSENSUS，2026-09-29）：单源钳制把一轮读数全拒后不立刻回退——若被拒的读数里有至少两个**不同来源**彼此离散在一个量化步长内（HTTPS `Date` 的整秒粒度）、往返短到没被建连耗时污染、且中位数不超过最大校正量，就采纳中位数，并打一行 **warning** 直接劝运维去把系统时间同步打开（这是异常出口，不该让 bot 长期在链上顶着）。四条尺只写在模块头 `_CONSENSUS_*` 常量里、本文不抄数值；任一条不成立照旧回退系统钟。真身 = `_consensus_offset`（只读判资格）+ `_commit_consensus`（落账与话术），调用点在 `_sync_now`。
- **回退告警现在带读数**：整体回退那行 warning 会列出本轮各源各报了多少秒、往返多久。09-29 排查就是卡在旧形态只报"都不可信"、不报"谁说了多少"，于是"到底是谁在说谎"在生产日志里问不出来。

## 测试与验收

`tests/test_timesync.py`（SNTP 报文/钳制/回退链；TS-SOCKET 两枚 `test_default_socket_factory_is_a_datagram_socket`、`test_ntp_leg_reaches_the_server_with_the_default_factory`，后者专治"每枚单测都注入 `socket_factory`、于是没人踩过默认那段"这一型盲区）、`tests/test_v21r2_stall_timesync_http.py`（HTTPS 兜底与停摆场景；TS-CONSENSUS 一组：独立两家被采纳 / 单源无背书仍拒收 / 慢链路样本不配背书 / 离散过大不算共识 / 超最大校正量判系统级故障 / 回退行必须带读数）。用例数以最近一次实跑为准，本文不手写。
真机：重启后看校时日志即可证成否——注意 **2026-09-29 之前在这里根本等不到 NTP 成功行**（TCP 套接字那一案），修后网络正常时应直接出现「与 `<server>`（NTP）校准成功」；本机 UDP/123 已实测可达（见「怎么调用」的对切复跑），所以**再等不到 NTP 成功行就别把账算给防火墙**——先查套接字类型与源表，「被墙」只是降级链的一条假想成因、本机至今无实证；真被拦时走 HTTPS 兜底、再不行回退系统钟，属模块自述的预期降级链；日志出现「多源互证」warning 说明本机系统钟自己就偏了这么多，该去把系统时间同步打开，而不是回头放宽这几个阈值。首次校时的具体启动延时未在本件代码内核实（装配层调度决定），如需精确值查根装配处。
