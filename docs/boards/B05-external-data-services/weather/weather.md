# 天气与预警 · 天气查询

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.weather · 天气查询

- 层级：一级 B05 → 二级 weather → 三级 `weather`
- 路由席位：`WEATHER`（matcher `weather`，command=True）
- 判定优先级：41
- 能力 id：`bot.weather`
- 实现落点：`plugins/bot_unified_runtime/domains/weather`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

`天气 <城市>` / `查天气 <城市>` / `天气 <省>-<市>`（繁体和拼音族同表生效）。输出一份带来源标注的天气报告，NMC 命中时附该地当前在报的气象预警；渲染后端可用时合成 Mica 卡图，文本作 caption 与兜底。生效条件：路由开关 `bot_weather_query_enabled` 为真，且消息是短文本、不像日常感慨句。

## 怎么调用

- 路由席位 `WEATHER`（能力 id `bot.weather`），装配入口 `domains/weather/capabilities/weather.py:build_weather_capability(config, *, render_backend)`。
- 触发谓词 `domains/weather/capabilities/weather.py:is_weather_command`；查询词预校验 `_plausible_weather_query`；陈述引导词守卫 `is_statement_lead`（与 B04 自然语言层共用同一份守卫，禁第二副本）。
- 取数：`domains/weather/data/nmc_weather.py:nmc_weather_query`（主）→ `domains/weather/data/open_meteo.py:open_meteo_query`（兜底），格式化分别是 `format_open_meteo` 与 NMC 内部格式化。
- 出卡：复用 B08 的 `render_card_png` 管线（`domains/link_parse/capabilities/content_parser.py:render_card_png`），`platform="weather"`、`item_kind="weather"`，审计标签 `weather_source:<nmc|open-meteo>` 记录本次到底用的谁。
- `支持区县 <省>` 是同一入口的旁支，直接读码表列清单。

## 开关与参数

- `bot_weather_query_enabled`（缺省 True）＝天气查询路由总开关，关掉后本入口不注册；`.env` 里 `BOT_WEATHER_QUERY_ENABLED` 可改，属装配期快照。
- `bot_weather_timeout_seconds`（缺省 8.0）单请求超时；`bot_weather_cache_seconds`（缺省 1800）是**人格侧环境注入**那份天气的缓存时长，不是本查询入口的。
- 注意区分：`bot_weather_enabled`（缺省 False）+ `bot_weather_latitude/_longitude` 管的是 B03 人格上下文里"当地天气"的自动读取，与用户主动查天气的开关不是同一枚键。
- 代理取 `bot_download_proxy`；失败文案池无独立开关。
- 逐键含义以 `docs/config-catalog-full.md` 为准，值不写进本文档。

## 失败时看到什么

- 码表未命中 → 静默换 Open-Meteo；全球源也没有该地名 → 一句「没有查到『<词>』的天气（城市名没找到或接口失败）」，随后照常继续对话，不报错。
- 主通道瞬时失败 → 先重试一次；两条通道都拿不到才走上面的回话。
- 预警支路失败或无在报 → 整段省略（用户看不到"预警"二字，也看不到"取失败了"，这是现行缺陷，见本功能 README）。
- 渲染后端缺失/失败 → 纯文本报告，内容与文字版逐字一致。

## 测试与验收

离线：`tests/test_weather_card.py`（卡 payload 与来源标注）、`tests/test_weather_statement_guard.py`（口语不劫持）、`tests/test_weather_nmc_retry_nmcflix.py`（重试与"未命中不重试"）。
真机：`docs/acceptance-manual.md` §6.6 与 §6.6.1 触发形态——正样本 `天气 北京`/`查天气 上海`/`天氣預報 台北`/昵称动词「守岸人点唱」同族的「守岸人 天气」；负样本「天气真好」「今天天气怎么样」（后者属对话/搜索链路，不应被本入口抢走）。
