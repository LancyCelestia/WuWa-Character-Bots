# 天气与预警 · 预警支路

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.weather · 预警支路

- 层级：一级 B05 → 二级 weather → 三级 `alert-branch`
- 实现落点：`plugins/bot_unified_runtime/domains/weather`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

天气报告后面的那段「⚠️ 气象预警」：拉 NMC 全国在报预警清单，按查询词过滤出与这座城市对得上的条目，等级高的排前面，最多展示若干条（其余以"其余 N 条略"收尾）。它是查询路径的支路，不是订阅推送——只有用户主动查天气时才顺带看一眼。

## 怎么调用

- 真身：`domains/weather/capabilities/weather.py:fetch_city_alerts(query, *, proxy, timeout)` → `format_city_alerts(alerts)`。
- 端点：`https://www.nmc.cn/rest/findAlarm?pageNo=1&pageSize=300`（免 key；一页即当日全量在报，条数以接口当次响应为准）。
- 标题拆解：`parse_alert_title(title)` 从「…气象台发布大雾橙色预警信号」里取 (类型, 颜色)；缺失回退空串，不编"未知类型"。
- 颜色序位表 `_ALARM_COLOR_RANK`（蓝<黄<橙<红）是本域**唯一**的色序真身：紧急信息域 `domains/emergency_info/contracts.py` 的等级映射与 `domains/emergency_info/service/alert_taxonomy.py` 的族色档都声明"收编此表、不另造 severity 枚举"，并由 AST 锁比对，改这里必须同时看那两处。
- 过滤口径：查询词按「省-市」拆成多个 token，要求**全部** token 命中标题（「河北-大城」必须同含"河北"与"大城"），防止他省同名县被误挂。

## 开关与参数

无独立开关，随 `bot_weather_query_enabled` 的入口一起生效；`bot_weather_timeout_seconds` 是本支路的超时上限。展示条数上限是模块常量 `_ALARM_MAX_SHOWN`，非配置键（要改属代码改动，走评审）。

## 失败时看到什么

**当前行为**：接口不可达、响应结构塌陷、确实无在报，三种情况一律返回空列表并被调用方静默跳过——用户看到的是"这段话根本没出现"，而不是"预警取不到"。这就是"取数失败被说成无预警"的假象来源（本功能 README 现行缺陷第 1 条），也是紧急信息域改用 `OK/NO_DATA/FAILED` 三态 + 快照直读的理由。
唯一诚实的部分：条数超过展示上限时会明说"其余 N 条略"；标题里没有颜色/类型时只写"预警"，不硬套色。

## 测试与验收

离线：`tests/test_weather_alerts_b10.py`（标题解析、色序排序、token 全命中门、空列表静默）、`tests/test_traditional_news_randpic.py` 侧的繁体族触发。
真机：在有在报预警的城市发 `天气 <该城市>`，应看到预警段与"当前在报 N 条"计数；再在**无预警**城市查一次，段应整体消失——两次结果之间的差别是这条支路目前唯一的"诚实"手段，不能反过来当作接口正常的证据。
