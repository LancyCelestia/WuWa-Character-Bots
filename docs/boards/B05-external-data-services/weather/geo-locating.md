# 天气与预警 · 地名解析与变体链

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.weather · 地名解析与变体链

- 层级：一级 B05 → 二级 weather → 三级 `geo-locating`
- 实现落点：`plugins/bot_unified_runtime/domains/weather`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把用户随口写的地名变成两个上游（NMC 码表、Open-Meteo geocoding）都能试的查询串，并挡住两类历史事故：「东京」被解析成江苏某个同名小镇、「华沙」在码表里查不到就直接摆烂。产出不是独立回复，是 `weather` 入口的取数顺序。

## 怎么调用

- 变体链真身：`domains/weather/capabilities/weather.py:_query_variants(query)` → `[原串, 去分隔串, 逐级末段, 首段]`，去重保序。例：`湘潭 雨湖` 先整体试，再拆到 `雨湖`、再 `湘潭`；`河北-大城` 先合并成 `河北大城`，再逐级拆到省/市/区县/乡镇，命中即止。
- 主通道内：`domains/weather/data/nmc_weather.py:search_city_code` / `find_city_code`（全称优先、其次前缀）。
- 兜底通道：`domains/weather/data/open_meteo.py:_geocode(city, ...)` 取候选列表（`language=zh`），再 `open_meteo_query` 拿当前+两日预报。候选排序按人口/名称精确度择优（治「东京→江苏小镇」），实现口径以该文件为准。
- 城市别名（中英互称、海外城市）集中在本域的常量表里，条数以真身为准、不在文档手写；新增别名只改这一处。

## 开关与参数

无独立配置键。行为参数（geocoding 候选数、超时）是模块常量与调用方传入的 `timeout`；`bot_weather_timeout_seconds` 决定整体预算，海外城市慢时宁可早退也不拖住回复。

## 失败时看到什么

- 变体链全部未命中 → 回一句"没有查到『<原始查询词>』的天气（城市名没找到或接口失败）"，回显里保留**用户原话**而不是拆出来的变体，避免用户以为 bot 换了个地方。
- geocoding 返回空候选（城市真不存在）与网络失败都收敛成 `None`，两者对用户同一句文案——这是有意的保守：不把"接口挂了"说成"没这个城市"，也不反过来。
- 本层绝不猜坐标：查不到就是查不到，不会挑一个"最像的"城市凑一份预报。

## 测试与验收

离线：`tests/test_weather_card.py` 与 `tests/test_weather_nmc_retry_nmcflix.py` 覆盖变体链与"未命中不重试"；`tests/test_weather_statement_guard.py` 保证引导词守卫不把陈述句喂进地名解析。
真机：`天气 湘潭 雨湖`（逐级拆到区县）、`天气 东京`（应为日本东京都而非江苏同名镇）、`天气 华沙`（海外别名 + Open-Meteo 来源标注）、`天气 河北-大城`（省市两级 + 同名防误挂）。
