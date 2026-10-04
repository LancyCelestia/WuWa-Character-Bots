# 知识库与检索 · 联网判定与 GENERAL 二判钩子

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B04.knowledge · 联网判定与 GENERAL 二判钩子

- 层级：一级 B04 → 二级 knowledge → 三级 `web-search-intent`
- 实现落点：`plugins/bot_unified_runtime/domains/core/search`、`plugins/bot_unified_runtime/domains/chat_reply/character/teaching_service.py`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/question_intent.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

每轮消息进 chat 层时的「要不要联网」**可解释判定**（只判不搜）：产出 `IntentDecision`（`NEVER`/`PRIMARY`/`FALLBACK`/`TOOL_ALLOWED` 四态，附置信度、原因码、分数分解）。GENERAL 兜底处的**廉价二判钩子**（生产形态 `llm_timely_domain_hint`）用一次小 LLM 问答把闭集正则漏词的时政/金融题升 PRIMARY。判定链每轮现算、无开关；二判钩子缺省 None＝逐字节旧行为。

## 怎么调用

真身 `domains/chat_reply/runtime/question_intent.py::classify_question_intent(text, *, domain_hint=None)`。链路：正则只提取信号 → 加权打分 → 按安全优先级出决策——显式「不要联网」一票 `NEVER`；闲聊/情绪/自称腿经 `reality_pull` 让位判据（现实题要「问句形状＋时效域/明示搜索」或「域外实体＋问句/时效」才让位，防现实题被情感腿吃掉）才否决；现实域（时政/金融/科技/新闻，经 `classify_timely_domain` 单一真身——「要不要搜」复用「搜了之后信谁」那四张表，不开第二份词表）＋问句/明示 ⇒ `PRIMARY`；域外实体叠加问法/时效 ⇒ `PRIMARY`；本地世界观 ⇒ `FALLBACK`（`allow_web_fallback=True`，本地库优先、低置信回退网页）；技术 how-to ⇒ `TOOL_ALLOWED`（模型一次性判断）。GENERAL 二判钩子只在确定性判定**已落 GENERAL** 时被征询（抢不回已被正则判定的域），命中的现实域走同一条 `timely_reality` PRIMARY 判据；`llm_timely_domain_hint`（小 max_tokens、短超时、问题文本截断帽）任何异常/缺 provider/认不出的回答一律回 `None`。媒体面让路：本轮回复面是媒体应答时不征询二判（媒体缝）。`classify_question_intent_legacy` 只做影子统计、不参与线上路由。

## 开关与参数

判定链自身**无专属开关**（每轮必算，chat.py 主调用点现取）。行为键均在 `config.py`、改动重启生效：总闸 `bot_web_search_enabled`（缺省 False＝整面休眠）；FALLBACK 补搜两键 `bot_web_search_knowledge_threshold`（缺省 0.60）/`bot_web_search_confidence_floor`（缺省 0.20，硬底线安全阀；仅联网已开时决定本地世界观题是否补搜）；ACG 竖源 `bot_search_acg_enabled` 与三源开关两参数（`bot_search_acg_timeout_seconds`/`bot_search_acg_max_per_source`）；遥测 `bot_web_intent_telemetry_enabled`（缺省关）`_db_path`/`_max_items`；影子对比 `bot_web_classifier_shadow_enabled`（缺省关，只记不决策）。

## 失败时看到什么

二判钩子故障 → 回 `None`、判定链照旧回 GENERAL，绝不新增故障面；影子分类失败 → 标签 `legacy_error`、不影响线上决策；总闸关 → 整面零网络零副作用。误判的可见表现＝该搜不搜（现实题无【联网检索】）或不该搜乱搜，定位走遥测（只记查询哈希＋决策＋置信度＋命中统计，不记原文）与影子对比标签。

## 测试与验收

`tests/test_question_intent.py`、`tests/test_question_intent_domain_hint.py`（二判钩子征询时机与让位）、`tests/test_emotion_gate_flip_census.py`（情感腿让位判据）、`tests/test_entity_gate_before_classification.py`、`tests/test_reality_relation_no_web_veto.py`、`tests/test_real_world_intent_terms.py`。真机验收无独立条目：以「现实/时效题出【联网检索】分区、闲聊零预搜索」为观察面，属联网检索验收域。
