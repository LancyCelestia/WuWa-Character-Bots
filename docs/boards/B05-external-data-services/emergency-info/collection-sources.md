# 紧急信息与预警 · 四权威源采集

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.emergency-info · 四权威源采集

- 层级：一级 B05 → 二级 emergency-info → 三级 `collection-sources`
- 实现落点：`plugins/bot_unified_runtime/domains/emergency_info`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

四路权威源的定时采集（不注册路由、不直接面向用户）：每轮每源一次调用，把结果落成幂等条目 + 一份"最近一轮快照"。它的存在理由是把慢接口从用户热路径上摘下来——旧天气预警支路把冷页十几秒的 `findAlarm` 内联在查询路径上，本域改成"轮询写快照、查询只读快照"。

## 怎么调用

- 编排：`domains/emergency_info/service/collector.py:run_collection_once(deps, *, now)`（纯函数式编排，域内**不 import 调度器**、不主动发网络请求于编排体内）；依赖工厂 `build_emergency_collector_deps(*, persist, snapshot, max_age, ...)` 装配四源 `SourceTask`。调度器注册在根装配面（`plugins/bot_unified_runtime/__init__.py`）。
- 四源真身（合法源身份唯一集合 `SOURCE_IDS` 由 `domains/emergency_info/service/alert_taxonomy.py` 镜像、AST 锁逐字核对）：
  - `domains/emergency_info/sources/nmc_alarm.py`：`fetch_nmc_alarms`（全国在报清单，超时须够长并重试）、`fetch_nmc_station_alarm`（站点 `real.warn`，这是旧天气模块从未消费的现成字段）、`split_alarm_title`、`parse_beijing_time`（北京时间分钟精度 → 带 UTC+8 的 aware datetime）、`build_nmc_alarm_detail_url`（主键先消毒再拼，防路径注入）。
  - `domains/emergency_info/sources/open_data_quakes.py`：ICL（`mobile-new.chinaeew.cn`，**降级代理源，卡面来源必须写 ICL、不得冒充 CENC 官网**）+ USGS（summary feed 与 fdsnws 两通道；fdsnws 矩形**必须用 min/max 四参**，`bbox=` 实测 400）+ `crosscheck_quakes`（主源逐条在核验源找配对，时间窗与距离阈值以该件实现为准，配不上就"各报各的并标注未获第二源确认"，**绝不静默择一**）。
  - `domains/emergency_info/sources/gdacs.py`：`geteventlist/allpaging`（旧端点已 400/404）；**只做背景聚合不做推送**；`alertlevel` 的 Red/Orange 映射到红/橙，**Green 故意不映射**（其语义是"未发布警报"，映射成黄色等于凭空造一档）；时间串无时区后缀，按 UTC 读并留 `gdacs_time_tz_assumed_utc` 标记，上层必须当"未核实口径"。
  - `domains/emergency_info/sources/http_get.py`：全源共享的取数件——`SourceOutcome` 三态（`OK/NO_DATA/FAILED`，绝不用空列表同时表达两种意思）、`require_safe_id` 消毒、`guard_outbound_url` 两道闸（常量白名单 → 既有 SSRF 护栏，**常量 URL 也不豁免**）、瞬时故障退避重试。
- 落库收口：条目一律过 `contracts.build_emergency_item`（缺字段即丢），持久唯一写入点是审核门（结构锁 `test_only_the_review_gate_can_write_items_into_the_store`）；采集器经注入的 `persist` 回调上交。
- 快照：`domains/emergency_info/service/snapshot_store.py`（四态与 `NO_DATA`/`FAILED` 的结构性分野），查询侧唯一读点 `collector.py:get_latest(snapshot, now, max_age=None)`。

## 开关与参数

`bot_emergency_info_enabled`、`bot_emergency_info_sources`（值必须是四个真身 `SOURCE_ID` 之一，写成模块名会静默不命中）、`bot_emergency_info_poll_interval_seconds`、`bot_emergency_info_usgs_min_magnitude`、`bot_emergency_info_db_path`、`bot_emergency_info_keep_days`；整轮墙钟预算 `budget_seconds` 与快照时效 `max_age` 是装配注入参数（不读全局配置，避开装配期快照老坑）。

## 失败时看到什么

用户侧不会看到异常。运维侧：FAILED 会冒一条管理员告警（经 300s 折叠，`NO_DATA` 不告警）；快照 FAILED 时查询仍回上一轮结果并显式标注本轮失败；**过滤后零命中**（如低于最小震级）判 `NO_DATA` 而非失败。落库/投递环节的 id 含非法段会被点名跳过，不带走整轮。

## 测试与验收

离线：`tests/test_emergency_info_sources.py`（真样例字节直喂解析器，含 GDACS 首条元信息丢弃、USGS 无 bbox、ICL 时区口径）、`tests/test_emergency_info_collector.py`（三态、预算弃剩余源、失败保留旧条目、告警只一次）、`tests/test_emergency_info_reachability.py`。
真机（重启后）：等一轮轮询，查库中条目与快照四态；人为把 `sources` 写成不存在的源名，应见"整链不注册"而不是静默半活。
