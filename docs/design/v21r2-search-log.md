# v21r2 SEARCH 席工作日志（ACG 搜索时效性增强）

> 席位：SEARCH（大模型+网络搜索时效性增强）。日期：2026-09-17。
> 纪律：全离线测试（真实网络零调用）；禁触域零接触；chat 链最小 diff。

## 一、现状盘点（rg 取证）

### 搜索面现状

| 面 | 载体 | 现状 |
|---|---|---|
| 联网检索链 | `sources/web_search.py`（721 行） | Tavily 主搜 + You/LangSearch 回退 + TinyFish 抓正文（`docs/search-api-adapters-2026-09-06.md`）；另有 DDG/Bing 免 key 爬虫 provider；`ChainedWebSearchProvider` 串联 |
| 检索触发门 | `runtime/question_intent.py`（449 行） | `classify_question_intent` 打分规则：`explicit_search/current/real_world/entity` → PRIMARY；`static_knowledge/question_like` 无强信号 → **NEVER（不联网）**；显式拒绝/闲聊/创作 → NEVER |
| chat 链注入 | `capabilities/chat.py` | L2935-3010：do_web 时按 reason 选 query 模板（entity→「萌娘百科/维基百科」后缀，temporal→「最新/更新」后缀）→ `_search_queries_concurrently` 并发 → `_sort_web_hits` → top2 抓正文 → `context.web_search_context`；L1476-1483 渲染【联网检索】（`_web_search_lines` L1154：仅「域名+标题+摘要」，**无日期无检索时间**） |
| 梗检索 | `sources/meme_search.py` + chat.py L2908 | `extract_meme_query`（需「梗」字样命中才触发）→ DDG →【梗/热词检索】 |
| 萌娘百科 | `sources/moegirl.py`（304 行）+ `capabilities/moegirl.py` | **已是可编程同步函数**：`moegirl_search(query, limit, api_bases, timeout, proxy)`（主站 generator=search→opensearch→镜像重试，带缓存+限速）；能力：条目全文检索/摘要；边界：主站 WAF/风控可能拦（ParseHttpError 降级） |
| 维基 | `sources/mediawiki.py` + `capabilities/wiki.py` | MediaWiki API（背景知识权威源，非时效源） |
| B 站 | `sources/subscriptions/bilibili_adapter.py`（只读参照） | `_wbi_get`/`_ARC_SEARCH_API` 走 `sources.parsers.wbi` + `sources.parsers.http_util.http_get_json`（cookie_header 由订阅 ctx 注入）；parsers 域 RW1a 禁触，仅 import 复用 |
| 知识检索 | `character/knowledge_service.py`（S8 收官） | search_scored，只读复用，不触 |
| 搜索服务面 | `sources/search_service.py`（1412 行） | 多源计划/游标/审计重型框架（v1 遗产），chat 链未接 |

### 时效信息在哪一步丢失（根因）

1. **触发门漏 ACG**：「X是什么梗」「芙莉莲第N集出了吗」「原神新版本卡池」等落入 `static_knowledge/question_like` → NEVER → **压根不搜索**，模型拿训练截止前的旧知识硬答。
2. **query 模板 ACG 不适配**：entity 路径只会拼「萌娘百科/维基百科」，时效拼「最新」——番剧/游戏/B站梗各自的时效词形（放送/更新话数/版本卡池/百大）没有专路。
3. **结果无日期**：`_web_search_lines` 渲染不带日期、不带检索时间，模型无法判断新旧；Tavily/DDG 对 ACG 词条返回的多是 SEO 农场旧文。
4. **竖源缺位**：Bangumi（bgm.tv，无 key，权威条目元数据+放送日期）、B站公开搜索（视频 pubdate）完全未接入；萌百有能力但只挂在指令/实体问答路径，不进 chat 检索融合。

### 设计（对应交付）

1. `sources/search_intent.py`：词表+正则驱动 ACG 意图识别（anime/manga/game/meme/vtuber/bilibili 标签；timeliness=latest/background；`acg_search_allowed(reason)` 对 NEVER 白名单放行 `general_static_knowledge/no_strong_signal` 等、硬拒显式不联网/闲聊/创作/用户内容）。
2. `sources/acg_search.py`：Bangumi v0 POST（无 key，需 UA）、萌百（import 复用 `sources/moegirl.moegirl_search`）、B站公开搜索（无 cookie 诚实降级）；transport 可注入（离线测试）；`fuse_acg_results` 时效加权纯函数（latest：≤7d ×1.6/≤30d ×1.3/无日期降权+date_unknown；background：源权威度加权）；`timeliness_note(now)` 检索截至口径。
3. config.py 六键 `bot_search_acg_*`（默认 False 保守，对齐 `bot_web_search_enabled=False` 惯例）+ catalog + .env.example。
4. chat.py 最小接线（4 处，坐标见下）：意图检测 → ACG 竖源与 web 检索并发先行 → 融合进 web_hits → `_web_search_lines` 首行加「检索截至+时效诚实」一句。
5. 测试：意图 ≥20 样例（正反例）、allow/deny、三源 mock、融合加权、降级路径，全离线。

### chat.py 改动坐标（先钉后改，最小 diff）

- 坐标A（import 区 ~L113 后）：`from ...sources import acg_search, search_intent`。
- 坐标B（~L2930 do_web 计算后）：意图检测+门禁+竖源 futures 先行提交。
- 坐标C（~L3010 web_hits 富化后、`context.model_copy(update={"web_search_context":...})` 前）：收集竖源结果、融合、注 date/source。
- 坐标D（`_web_search_lines` L1154）：hits 非空时首行插「检索截至 YYYY-MM-DD；检索内容可能过时，拿不准就如实说旧」。

## 二、实施记录

### 交付物

| 文件 | 性质 | 内容 |
|---|---|---|
| `plugins/bot_unified_runtime/sources/search_intent.py` | 新建 | ACG 意图识别器：6 域词表（anime/manga/game/meme/vtuber/bilibili，含高热条目名与圈内黑话）+5 组模式正则（第N集话季/更新到N/年份新番/新一集/梗语义）→ `AcgIntent(is_acg, tags, timeliness, matched_terms)`；时效档 latest/background；`acg_search_allowed(reason)` 门禁（8 个安全红线 NEVER 拒绝：explicit_no_web/short_smalltalk/asks_user_identity/you_state_chat/personal_emotional/creative_roleplay/user_provided_content/empty；知识缺口类 NEVER 放行）；`extract_acg_query` 口语洗涤；`acg_query_variants` 至多 2 条领域化查询增强 |
| `plugins/bot_unified_runtime/sources/acg_search.py` | 新建 | 三竖源+融合：`bangumi_search`（bgm.tv v0 POST，无 key，自定义 UA 必需，条目元数据+放送日期+评分）；`moegirl_lookup`（函数内延迟 import 复用 `sources/moegirl.moegirl_search` 既有缓存/限速/镜像链）；`bilibili_search`（search/type video，pubdate→本地日期，`<em>` 剥离，code!=0 含 -412 风控诚实降级空）；`search_acg_verticals` 线程池并发+单源失败记 `acg:{source}:{异常类型}`+总预算超时记 `acg:timeout`；`fuse_into_web_hits` 纯函数（latest：≤7d×1.6/≤30d×1.3/≤180d×1.1/更旧×0.8/无日期×0.7+「日期未知」标注；background：萌百1.2>Bangumi1.1>B站/web1.0；输出即 contracts `WebSearchHit`，title 加竖源标签、摘要行首注「（来源·日期）」，复用【联网检索】既有渲染/预算/消毒/遥测，零模板改动）；`timeliness_section_note`+`TIMELINESS_HONESTY_LINE` 守岸人口径时效诚实句 |
| `plugins/bot_unified_runtime/config.py` | 追加键块 | `bot_search_acg_enabled(False)/bangumi(True)/moegirl(True)/bilibili(True)/timeout_seconds(4.0)/max_per_source(3)` 六键，插在 `bot_web_search_admin_notice` 之后（~L421） |
| `docs/config-catalog-full.md` | 追加 6 行 | BOT_WEB_SEARCH_TAVILY_EXTRACT_ENDPOINT 行后，含能力边界与降级语义登记 |
| `.env.example` | 追加键块 | BOT_WEB_SEARCH_MAX_RESULTS 后，带边界注释 |
| `plugins/bot_unified_runtime/capabilities/chat.py` | 最小接线 4 处 | 坐标A L118-124：import（acg_search/search_intent 四函数/datetime）；坐标D `_web_search_lines` L1164-1170：hits 非空时首行插「检索截至 YYYY-MM-DD HH:MM；TIMELINESS_HONESTY_LINE」；坐标B ~L3022：ACG 配置读取（runtime_settings.get_or 六键）+意图检测+`acg_search_allowed` 门+竖源单 future 先行提交（与通用检索并行）；do_web 内 L3155-3176：query 变体入 queries+收 future+`fuse_into_web_hits` 融合；ACG-only 块 ~L3190-3218：do_web 未触发时竖源结果独立建 `WebSearchContext(query=原文+"（ACG 专项）")`，补「梗/番剧问题旧链路压根不搜索」的缺口 |
| `tests/test_v21r2_search_intent.py` | 新建 | 21 正例（标签+时效档）+9 反例（天气/行情/提醒/技术/闲聊等绝不误触）+门禁 18 reason+洗涤 6 例+变体 5 例 |
| `tests/test_v21r2_acg_search.py` | 新建 | 三源 mock transport 解析/边界、单源失败降级、禁用跳过、预算超时、非 ACG no-op、融合加权（新旧序/未知日期标注/背景权威序）、`_web_search_lines` 时效口径渲染（鸭子类型注入） |

### 设计要点

- **行为零回归缺省**：`bot_search_acg_enabled=False`（对齐 `bot_web_search_enabled=False` 保守缺省）；关时 chat 链路径与旧版完全一致（run_acg=False 短路）。
- **安全红线优先**：`acg_search_allowed` 硬编码 8 个 NEVER reason 永不放行（用户显式拒绝联网/闲聊/身份/自我状态/情感/创作/用户内容/空），ACG 检索不越过。
- **类型契约**：融合输出直接构造 `contracts.character.WebSearchHit`（chat 链 ContextBundle 实际消费的类型；并行席位已把 WebSearchHit 契约化，sources.web_search 的同名 dataclass 是 provider 侧传输模型，二者字段同形）。
- **竖源独立性**：ACG 竖源不依赖 `BOT_WEB_SEARCH_ENABLED` 与 Tavily key——无任何搜索 key 也能命中番剧/梗查询的时效补口。
- **接口变更风险登记**（诚实边界）：Bangumi v0 需自定义 UA（默认 UA 403）+速率限制；萌百主站 WAF 可拦（ParseHttpError 降级）；B站无 cookie 常见 -412、wbi 签名 2023 起逐步强制随时可能收紧——三者失败均为空列表+错误类型遥测，绝不编造。

## 三、实跑证据（全部实跑，解释器=ChatBot_Runtime venv）

```
# 新增测试（两文件，全离线 mock）
python -m pytest tests/test_v21r2_search_intent.py tests/test_v21r2_acg_search.py \
  --basetemp=$TEMP/v21r2-search -p no:cacheprovider -q
→ 79 passed（修 3 个词表缺口后全绿；终态随回归 257 passed）

# 搜索相邻存量回归
pytest tests/test_sdd9_n3re.py tests/test_persona_prompt_and_memory.py \
  tests/test_moegirl_search.py tests/test_moegirl_question_fix.py tests/test_moegirl_yield_fix.py \
  tests/test_doc_sync_gates.py tests/test_chat_and_sources_regressions.py -q
→ 173 passed
pytest tests/test_bgroup_chat_pipeline.py tests/test_backend_unit.py \
  tests/test_settings_hot_audit.py tests/test_auditfix_llm_route.py -q
→ 46 passed / 1 failed：test_auditfix_llm_route::test_route_ids_unknown_model_name_aggregates_by_price
  （'expensive'!='cheap'，LLM 渠道价格聚合域；git status 实证 llm/channel_health.py 为并行在飞席位修改，
   与本席文件域零交集——本席未触 llm/）
pytest tests/test_smoke_config.py tests/test_config_json_validators.py -q → 10 passed
终态合并跑（10 文件）：→ 257 passed

# 静态门（本域 6 文件）
ruff check（search_intent/acg_search/chat/config/两测试）→ All checks passed
mypy --explicit-package-bases（两新模块+两测试）→ 本域 0 错误
（全树 17 errors 中其余属并行在飞席位与已知 control_plane/api/platform.py 2 错，未触碰）
```

## 四、遗留与登记

1. **未部署**：改动全在工作树，待用户重启 bot 生效；生产启用需 `.env` 设 `BOT_SEARCH_ACG_ENABLED=true`。
2. **B站竖源无 cookie 降级**：生产若常 -412，后续可接既有 18 平台 cookie 链（cookie_header 参数已留口）或升级 wbi 签名（`sources/parsers/wbi.py` 可复用，本席未接以控范围）。
3. **chat 编排器端到端**：竖源提交/融合在编排器内的路径由纯函数+门禁单测覆盖，未做全链路 mock 编排测试（重量级夹具，ROI 低）；真机验收建议：开启开关后问「硬控是什么梗」「芙莉莲第三季出了吗」，观察【联网检索】出现带日期的竖源条目。
4. **并行会话观察（不属本席域，仅记录）**：`test_auditfix_llm_route` 1 失败=channel_health 在飞席位；`sources/data/qx.json → domains/weather/assets/qx.json` 为天气域席位在飞迁移（文件健在，`find` 实证），非误删。
5. COORDINATION.md 原不存在，按简报在根目录创建并记一行。

## 五、FIX2 收口记录（2026-09-18，小债清收席）

- **债**：本席移交 `test_error_report::test_config_snapshot_whitelist_and_secret_masking` 1 红——`bot_search_acg_*` 六键与错误卡配置快照掩码白名单交互。
- **取证与裁决**：快照白名单=动态前缀枚举（`_config_snapshot` 按 `bot_search_` 前缀收集 `Config.model_fields`，`runtime/error_report.py:427-462`），**无显式键表可"补"**——六键已自动进快照；因非密钥命名（enabled/timeout/max）不被 `_SECRET_KEY_RE` 掩码，旧断言 `set(search_rows.values()) == {"***"}` 编码的「search 全键皆密钥」前提随本席 ACG 能力扩展过时。裁决=**测试期望过时，掩码逻辑零缺陷，`runtime/error_report.py` 零改动**。
- **修**：仅改 `tests/test_error_report.py` search 段——getter 改为密钥键（`*_api_key`）返回哨兵泄漏值、非密钥键返回普通值；断言升级为双向：api_key 族全 `***`（掩码不松）+ `bot_search_acg_*` 恰 6 键明文进快照（不被误掩码）；`"leak-me" not in repr` 泄漏哨兵保留。
- **实跑**：`tests/test_error_report.py` **44 passed, 1 skipped**（修前 1 failed；首轮 24 errors 经串行复跑实证=FIX2 席自身三 pytest 并行 basetemp 父目录竞态假红，与代码无关）；ruff 本文件 All checks passed。未 commit。

