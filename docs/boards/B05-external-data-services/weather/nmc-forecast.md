# 天气与预警 · NMC 预报与码表

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.weather · NMC 预报与码表

- 层级：一级 B05 → 二级 weather → 三级 `nmc-forecast`
- 实现落点：`plugins/bot_unified_runtime/domains/weather`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

天气域的数据层真身：把 NMC（中国气象局）免 key 接口和随包内置的区县码表包成一个纯函数层——输入站点码或「省-市」文字，输出结构化/格式化好的天气报告。它不注册路由、不直接面对用户，只被本板块的 `weather` 入口与紧急信息域的站点预警采集复用同一份接口口径。

## 怎么调用

- 真身：`domains/weather/data/nmc_weather.py`（同步实现，全部走 B05 的 HTTP 咽喉 `domains/link_parse/parsers/http_util.py:http_get_json`，不自建第二套客户端配置）。
- 码表：随包内置资产 `domains/weather/assets/qx.json`（区县码表，条数以文件与机器册 `docs/auto-facts.md` 为准，叙述文档不手写），加载与检索在 `_load_city_database`、`search_city_code`（全局模糊：全称优先、其次前缀）、`find_city_code`（「省份-城市」两级，支持简称）、`list_districts`（列一个省的全部区县）。
- 取数与格式化：`fetch_nmc_weather(stationid, *, proxy, timeout)` 拉单站实况+预报，失败返回 `None`；`nmc_weather_query(query, *, proxy)` 是文字入口，「天气 <城市>」「天气 <省>-<市>」都落这里。
- 端点形态：`https://www.nmc.cn/rest/weather?stationid=<码>&_=<毫秒>`，必须带有效站点码——无/无效码的固定响应是 `data:""`，与"接口挂了"同形，因此上层按"未命中"处理。

## 开关与参数

- 超时沿用调用方传入的 `timeout`（能力层缺省 `bot_weather_timeout_seconds`）。
- 码表路径是随包资产，**没有配置键、不允许挪动或删除**；`.gitignore` 对该文件有否定规则，清理波不得误伤。
- 无鉴权、无 Cookie、无热改旋钮。

## 失败时看到什么

本层不产生用户可见文案：任何网络/解析失败返回 `None`，由能力层决定是重试一次、换 Open-Meteo，还是回那句"没有查到"。格式化侧的纪律是**字段缺就写"暂无"**：`_format_value` 对空值不造 0，体感等级 `_comfort_desc` 缺档时不猜。

## 测试与验收

离线：`tests/test_weather_nmc_retry_nmcflix.py`（含"码表命中才重试"的负例）、`tests/test_weather_alerts_b10.py` 与 `tests/test_weather_card.py` 通过 monkeypatch 本层出口拦截全部外呼；紧急信息站点预警侧的解析用例见 `tests/test_emergency_info_sources.py`（同一接口的 `real.warn` 字段消费）。
真机：`天气 河北-大城`（简称+两级匹配）、`支持区县 湖南`（列清单）。
