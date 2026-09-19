# 紧急信息采集器真夹具（E11 源普查实测字节）

> **规矩（本目录唯一权威声明）**
> 1. 这些 `.sample.*` 文件是 `tests/test_emergency_info_sources.py` 解析测试**唯一允许**的样例来源。
>    **禁止自造字段**：测试的期望值必须从这些真字节派生，不得为了「让测试好写」而凭空补/改源端字段名。
>    理由：源端拼写本身就是被测对象（例：ICL 的台数写成 `sations` 不是 `stations`；USGS 是 `nst`；
>    NMC `findAlarm` 的 `issuetime` 用斜杠而 `rest/weather` 的 `publish_time` 用短横）。自造夹具＝把回归锁变成自娱自乐。
> 2. **缺件即判红，不 skip**。夹具随仓库进 git，干净克隆必然带着它；读不到就是仓库损坏
>    （被误删 / 落进了被 `.gitignore` 忽略的目录 / 改名未同步）。历史上这里塌过一次，见下。
> 3. 密钥、Cookie、Authorization 头、令牌一律不得出现（落盘时已剔除，B10-FIX 席 2026-09-20 逐件复核，
>    复核方法与结果见本页末条）。
> 4. 原件同时保留在 `.superpowers/sdd/2026-09-19-emergency-info-unify/probes/samples/`（波次取证件，**不删不改**）；
>    本目录是它的受跟踪副本，两侧 sha256 逐件相同（见下表）。

## 为什么这段历史要写在夹具目录里

B2 席交付的 942 行采集器测试原先把样例指向 `.superpowers/…`，而 `.gitignore:42` 就是 `.superpowers/`
（实证命令：`git check-ignore -v .superpowers/sdd/2026-09-19-emergency-info-unify/probes/samples/nws_alerts.sample.json`
⇒ 输出 `.gitignore:42:.superpowers/`）。⇒ 干净克隆上六份样例全部不存在 ⇒ 测试走 `pytest.skip` ⇒
**56 条采集器用例整体静默失效（假绿）**。B2 已诚实登记（`reports/B2-report.md` §4 R-5），
2026-09-20 由 B10-FIX 席迁入本目录并把 skip 改为 fail。
解法是**搬家**而不是给 `.gitignore` 加例外——`.gitignore` 的 `.superpowers/` 一条服务的是「会话台账目录不入仓」这个更大的意图。

## 逐件清单（六件，2026-09-20 抓样，全部 UTC+8）

落盘时间（原件 mtime，未被改动）：`2026-09-20 00:57:35`—`00:57:58`。
E11 席实测时点：`2026-09-20 00:15—01:00`（全部读取型 GET，零 POST、零写入、零密钥）。

| 文件 | 字节数 | sha256 | 端点（E11 §2 矩阵行） | 本目录内消费它的用例族 |
|---|---|---|---|---|
| `nmc_findAlarm.sample.json` | 83,370 | `2db025e949e0165d14cb5308dd42f5b122a98babbe6afaecaf6f223adb66993b` | #1 `www.nmc.cn/rest/findAlarm?pageNo=1&pageSize=300`（全国在报清单，300/328 条） | `test_nmc_find_alarm_sample_parses_all_real_items`、色彩分布、省级合并去重、缺 `page`/`code!=0`、零条目 vs 谎报条目、缺 `alertid` 丢弃、默认链路过 SSRF 闸、`issuetime` 斜杠事实锁、`split_alarm_title` 逐条真标题、纯函数可达性 |
| `nmc_restWeather.sample.json` | 10,473 | `f72455742e8c0333f71ff4b6ef2b2d0eb83da4ed604cafb95a246857a6f93884` | #2 `www.nmc.cn/rest/weather?stationid=Wqsps`（北京站实况，`data.real.warn.alert="9999"`） | `test_nmc_station_alarm_real_sample_is_no_data_not_failed`（**本席最重要的一条锁**）、缺 `warn`/缺 `real`、把哨兵换成同源真形态预警、`publish_time` 短横事实锁、状态机 helper |
| `icl_earlywarnings.sample.json` | 4,232 | `52a6c3056b5795c2144a37913fce46cd322df44f48a7119318b36fdf189f0dfe` | #6 `mobile-new.chinaeew.cn/v1/earlywarnings?start_at=&updates=10`（ICL 速报 20 条） | `test_icl_sample_parses_and_never_claims_to_be_cenc`（D-1 红线：降级代理源不得冒充 CENC）、坏信封/坏类型/空条目/全丢、交叉核验三族 |
| `usgs_all_hour.sample.geojson` | 3,163 | `1289cb3ad96a9e078ff7f5b11c97c17513af1a868d49b7ab2ce4d480b66365ec` | #10 `earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson`（4 features） | GeoJSON `[lon,lat,depth]` 坐标序、缺 `features`、null 震级 vs 震级门、空 features、交叉核验 |
| `gdacs_eventlist.sample.json` | 63,829 | `779219bfd70ad9deede546c921135d0b4e2a526a7bf365eddfa0ef2797adb411` | #14 `www.gdacs.org/gdacsapi/api/Events/geteventlist/allpaging`（101 features，含 1 条只有 `properties.meta` 的元信息条目） | 丢元信息条目且不造颜色（Green⇒`color_label=""`）、缺 `features`、全为元信息⇒FAILED、类型分布 WF84/EQ9/FL5/TC2 |
| `nws_alerts.sample.json` | 8,234 | `f76d36fe24fc644a8faed1d36c7b2b3f99ef7a014d5bb385e80d3f0d222a0836` | #12 `api.weather.gov/alerts?limit=2`（2 features，**判定「不接」**：国内用户无投递价值） | 无解析用例消费它。留档理由：①「实测 200 但故意不接」的证据；②完整性锁 `test_fixtures_are_all_present_and_non_empty` 把它计入六件之一 |

## 抓取命令原文

出处 = 波次探针清单 `.superpowers/sdd/2026-09-19-emergency-info-unify/probes/e11_probes.sh`
（仓库内绝对路径 = 本工作区根目录下同名文件；第 2 行头注：「一律读取型 GET，绝不 POST/写入」）。
下表「落盘形态」= 该探针命令加 `-o <样例名>` 后另存；命令本体、参数、UA 均与探针原文逐字一致。

```bash
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64)'   # 探针脚本第 4 行原文

# #1 nmc_findAlarm.sample.json —— NMC 证书链不完整 ⇒ -k 关校验（与 domains/weather/data/nmc_weather.py:119 同口径）
curl -sk "https://www.nmc.cn/rest/findAlarm?pageNo=1&pageSize=300" -o nmc_findAlarm.sample.json
#   探针原文实测：200，0.4~25s（冷页 24.9s / 暖 0.39s），全量在报

# #2 nmc_restWeather.sample.json
curl -sk "https://www.nmc.cn/rest/weather?stationid=Wqsps" -o nmc_restWeather.sample.json
#   探针原文实测：200 data.real.warn.alert（本样例时点值 = "9999" ⇒ 确实无预警）

# #6 icl_earlywarnings.sample.json
curl -s "https://mobile-new.chinaeew.cn/v1/earlywarnings?start_at=&updates=10" -o icl_earlywarnings.sample.json
#   探针原文实测：200 匿名 JSON

# #10 usgs_all_hour.sample.geojson
curl -s "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson" -o usgs_all_hour.sample.geojson
#   探针原文实测：200
#   注：同源的 fdsnws 查询口（另一条实测命令，本目录未留样例）用 min/max 四参数，
#       bbox 参数实测 400 Unknown parameter "bbox" ⇒ 测试里锁死了这个坑

# #14 gdacs_eventlist.sample.json
curl -s "https://www.gdacs.org/gdacsapi/api/Events/geteventlist/allpaging" -o gdacs_eventlist.sample.json
#   探针原文实测：200 GeoJSON（旧 geteventlist/MAP 400、/ALL /EQ 404）

# #12 nws_alerts.sample.json —— 判「不接」，证据留档
curl -s -A "contact-admin@example.invalid" "https://api.weather.gov/alerts?limit=2" -o nws_alerts.sample.json
#   探针原文实测：200 需 UA（`example.invalid` 是 RFC 2606 保留域、不可投递，
#   这里只是照 NWS 的「UA 里给联系串」惯例占位，不是任何真实身份或凭据）
```

## 要重抓怎么办（以及不许怎么办）

- 允许：用上面同一条命令重抓 ⇒ 覆盖同名文件 ⇒ 同步改 `tests/test_emergency_info_sources.py` 的
  `SAMPLE_SIZES` 与本表字节数/sha256 ⇒ **重抓后的样例里所有派生期望值（300 条 / count=328 /
  黄183-蓝109-橙8 / `eventid 1104169` 等）都要跟着重新派生**，改样例不改期望值必然红，那是设计意图。
- 不许：手工编辑样例 JSON 的字段名或值来「配合」代码；不许新增第七份自造 `.json` 当夹具；
  不许把新样例放回 `.superpowers/`（那里不入 git，见上节）。
- 隐私复核（本席 2026-09-20 实跑，可复跑）：
  `grep -o -i -E 'sk-[a-z0-9]{4,}|cookie|authorization|api[_-]?key|bearer|secret|passwd|password|token' tests/fixtures/emergency_info/*`
  ⇒ 六件命中数全为 0；盘符路径形态（`[a-z]:/`、`[a-z]:\users`）亦全为 0；
  唯一的邮箱形态是 NWS 样例里 NOAA 自行公开的官方联系串 `w-nws.webmaster@noaa.gov`（源站公告字段，非凭据）。
