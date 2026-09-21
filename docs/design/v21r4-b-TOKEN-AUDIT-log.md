# TOKEN-AUDIT 审计结论（主代理席吸收执行 · 2026-09-20）

## 证据链
1. **解析面**（domains/chat_reply/llm_engine/providers.py:355-385）：OpenAI（prompt_tokens_details.cached_tokens）/DeepSeek（prompt_cache_hit_tokens）/Anthropic（cache_read·creation_input_tokens）三族字段全覆盖；test_llm_ledger+test_model_effort_groups_and_pricing **36 passed**。
2. **无重复计数**：报告 Total=372,243=346,205+26,039 严格相加，cache 单列不进总额；命中率分母=prompt_tokens（含缓存子集，符合 API 语义）。
3. **生产铁证**（wuwa_diagnostics.sqlite3 环窗 100 条，12:52-13:18 本地）：gemini-3.8-flash 全部 100 调用 **cache_read_tokens=0**——上游（axonhub 中转）对 gemini 根本未回缓存字段；同期报告 grok 有 4,416 命中=解析/聚合链路本身通。→ **gemini 缓存 0 = 渠道行为，非统计缺陷**。
4. **缓存创建全 0**：同理（当前活跃渠道无一按 Anthropic 形态回创建字段）。
5. **账单 0.30 元/24h**：与用户实付价目表（gemini 0.1875/0.9375、grok 0.6/1.8、terra 0.29/1.74、luna 0.116/0.522 每百万）量级相符；主代理粗算 ≈0.49 元，差异=分渠道价差与缓存折扣，逐调用「按调用时价格」合计为权威口径。
6. **token 量级**：55 次/6.3k 输入每次、143 次/6.8k 每次——人格对话+知识注入的正常体量。

## 结论
统计链路无缺陷。gemini 缓存命中 0 的唯一可动路径=用户在 axonhub 控制台确认/开启 usage details 透传（bot 侧无字段可解析，诚实 unknown）。
## 可选增强（不实施，待裁定）
① 报告对「缓存 0」标注「上游未回缓存字段」防误读；② 开 BOT_LLM_BILLING_ENABLED 落 llm_call_records 持久账本（现报告数据源=事件日志聚合，llm_billing.sqlite3 不存在=账本关）。
