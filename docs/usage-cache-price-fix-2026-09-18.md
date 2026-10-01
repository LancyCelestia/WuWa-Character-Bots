# 用量账单：缓存口径与价格链路修复（2026-09-18）

对应 09-18 18:00 定时报告的三个问题：缓存命中偏低 / 多处不显示缓存 token / 价格仍显示未计价。
本文是**代码侧改动记录 + 你需要手动执行的两步**，不含任何对你实例数据的自动写入。

---

## 一、结论速览

| 问题 | 根因 | 状态 |
|---|---|---|
| 「缓存创建」恒为 0 | 上游根本没上报这个字段。现链（当日口径）`4` 个模型全走 OpenAI 兼容中转，该协议只有"缓存读"（`prompt_tokens_details.cached_tokens` / `prompt_cache_hit_tokens`），没有"缓存创建"概念；Anthropic 协议的 `cache_creation_input_tokens` 才会报 | 代码侧已如实标注，不再让人误读 |
| `/bot model usage` 恒显示"命中 0，创建 0" | 诊断库（`runtime_diagnostics`）**根本没有缓存列**，缓存量只躺在 `audit_tags` 里没人读 | 已修（补列 + 从 tags 回填，旧库自动迁移） |
| 报告逐模型行看不到缓存 | `build_report_text` / `/bot model usage` 的行文案只拼了「入 / 出」 | 已修（逐模型恒显式输出 缓存读 / 缓存建 + 总账命中率） |
| 价格维护不上 | **两个价表互不相通**：导入脚本写的是模型注册表（`price_in/price_out/...`），账单读的是 `BOT_MODEL_PRICES`（默认空 dict）。导入一次也白导 | 已修（注册表成为单一来源，全链路合并） |
| 缓存价配不进去 | `parse_model_prices` 只认 `input/output`；`/bot model price` 也只收这两个键 | 已修（新增 `cache_read` / `cache_creation` / `per_call`） |
| 缓存命中率 `4.2%`（当日实测） | 见第四节：**提示词顺序不是主因**，主因是"前缀长度逐条漂移 + 大量一次性辅助调用" | 分析见下，改动待你决定 |

---

## 二、缓存命中率：为什么低，以及"是不是提示词放最前面"

**不是顺序问题。** 现有拼装顺序对前缀缓存是友好的：

```
[system 消息] = 人设原文 → 运行时规则头 → 【动态分区…】 → 安全边界尾
[user 消息]   = 当前这一条消息
```

动态内容（记忆 / 最近对话 / 时间窗记录 / 知识库 / 当前时间 / 心情）全部挂在**人设之后**，
所以稳定前缀 = 人设头部，这正是前缀缓存能吃到的那一段。顺序没写反。

真正的三个原因：

1. **稳定前缀的长度逐条漂移。** `_compose_persona_verbatim_prompt` 里
   `persona_room = system_prompt_budget − len(runtime_block) − 2`——人设被裁到多长，
   取决于当次动态分区有多大（记忆/历史/知识库每次都不一样）。前缀缓存只能复用**最短公共前缀**，
   于是命中被压到最小那一次的长度上。
2. **历史对话不是独立消息，而是塞在 system 尾部的文本块。** 前缀缓存只缓存前缀，
   每次新追加的历史永远在后半段，一分钱缓存都吃不到。这是"两条消息"结构带来的结构性损失。
3. **大量一次性辅助调用稀释了命中率。** 记忆抽取、反思、视觉描述、视频理解、知识库构建等
   各自有独立的 system 提示词，彼此不共享任何前缀。全天 `166` 次调用 / `106 万` 输入 token，
   平均 6.4K/次——说明大头是几次大上下文辅助调用，它们天然零缓存。
4. **全仓没有发送任何缓存断点**（`cache_control` 零处）。走 Anthropic 协议的中转渠道
   （claude 系）不会自动缓存，必须显式打断点才有缓存。

**可选的改法**（需要你拍板，涉及提示词语义，我没有擅自改）：

- 把 `persona_room` 改成**固定预算**（不随 `runtime_block` 变化），稳定前缀长度就恒定了；
  代价是预算紧张时人设与动态分区会互相挤，需要重新调权重。
- 历史对话改为**独立 messages**（`system` + 历史若干条 + 当前 user），
  这会让缓存真正吃到"人设 + 历史"这一段；代价是触碰 `build_chat_prompt` 的契约与一批测试。
- 若你确认某条渠道背后是 Anthropic 原生协议，可加 `cache_control` 断点；OpenAI/DeepSeek 系
  是自动前缀缓存，不需要也不能加。

---

## 三、代码侧已改动（全部离线测试覆盖）

| 文件 | 改动 |
|---|---|
| `domains/chat_reply/llm_engine/pricing.py` | `parse_model_prices` 支持 `cache_read`/`cache_creation`/`per_call`（缺键 ≠ 0）；`model_call_cost_milli` 按 `ordinary = prompt − cache_read` 计价，缓存读/创建各走自己的价，缺缓存价回退输入价；新增 `registry_model_prices` / `merge_model_prices` |
| `domains/ops/smoke/diagnostics.py` | `runtime_diagnostics` 新增 `llm_usage_cache_read_tokens` / `llm_usage_cache_write_tokens` 两列（`_ensure_column` 自动迁移旧库），并从 `audit_tags` 回填 |
| `domains/ops/monitor/usage_monitor.py` | 新增 `format_cache_summary`（含命中率）/ `format_model_row_line` / `format_channel_subrow`（两处报告共用同一口径）；定时报告逐模型显示缓存读/建；缓存价表改为 **注册表 → BOT_MODEL_PRICES → 内置兜底** 三级合并 |
| `domains/ops/admin/runtime_admin.py` | `/bot model usage` 汇总缓存并逐模型显示；价格来源改为注册表合并；`/bot model price` 新增 `cache_read=` / `cache_creation=` / `per_call=` 三个键 |
| `domains/chat_reply/capabilities/chat.py` | 记账时把缓存读/创建量一并计入成本（此前按全输入价高估）；`BOT_MODEL_PRICES` 改为**合并**进装配期价表，不再整表替换 |
| `__init__.py` | 新增 `_assemble_model_prices`：装配期把模型注册表投影成价表，导入一次即全链路生效 |
| `scripts/import_model_prices.py` | 价目表补齐（POTCCV sol/astra、GLM Coding 折扣以价目真身现算为准）；网关兜底补 `deepseek-v4.1-flash`、`gpt-5.6-luna`；新增 `MODEL_ID_OVERRIDES`（同 host 渠道按 model_id 钉价）与 `--report`（列出未覆盖条目） |

**验证**：`ruff` 全过；相关测试 65 passed；全量离线 **8080 passed / 8 failed**——
`8` 条失败全部与本次改动无关（`model_router._credential_config` 缺失、`docs/auto-facts.md` 漂移、
memory_service / parsers / supervisor / lifecycle 各 `1~2` 条），均为并行批次在飞文件的既有问题。

---

## 四、你需要手动做的两步

> 以下命令会写你实例的运行时设置，我没有替你执行。先看 dry-run，确认无误再 `--apply`。

### 第 1 步：把全渠道价目写进模型注册表

```bash
cd C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot
C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe scripts/import_model_prices.py --report
```

`--report` 只列出**没有价目命中**的条目（会记未计价的那些）。命中/未覆盖条数以该命令现算为准（本次落盘时曾实跑一次，属当时值）。

确认无误后实际写入：

```bash
C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe scripts/import_model_prices.py --apply
```

只改价格键，不碰 `api_key`/`base_url`，可重复跑。

### 第 2 步：重启 bot

**铁律：改代码必须重启 bot 才生效。** 装配期价表在启动时读一次，
所以不重启的话，18:00 那份报告里的「未配置价格」会照旧。

重启后自查：QQ 里发 `/bot model usage`，应当看到
`缓存：命中 X（占输入 Y%），创建 Z` 与逐模型行里的 `缓存读 / 缓存建`，
且不再出现「未配置价格」。

### 单条临时改价（可选）

```
/bot model price gpt-5.6-luna input=0.116 output=0.522 cache_read=0.0087 cache_creation=0.10875
```

---

## 五、已知边界（不粉饰）

1. **`gpt-5.6-luna` 的网关价是推定值。** axonhub 背后是哪家上游，bot 侧看不到；
   现按 StarAPI 口径（0.116/0.522/0.0087/0.10875）落价，与报表兜底口径一致。
   若确认是浅夜（0.3/1.8）或 POTCCV（0.024/0.144/0.0024/0.03），改 `GATEWAY_OVERRIDES` 那一行即可。
2. **模型级价 ≠ 渠道级价。** 渠道选择全权归 axonhub，bot 不知道这次请求实际落到哪家；
   只有账本（`llm_call_records`）开启时，报告才有渠道子行做精确归因。模型级价是"该模型的代表性价"。
3. **`_MODEL_PRICE_FALLBACKS` 的注释与数值不符**：注释写"恒星纪元实付价"，
   实际数值是 StarAPI（gemini/terra/luna）+ 浅夜（grok）+ 官方（deepseek）的混合口径。
   现在注册表价优先于它，它只在模型完全无价时兜底；建议后续把注释改成实情。
4. **缓存创建量在当前渠道组合下永远为 0**，这是协议事实，不是统计漏采。
   要看到真实的创建量，需要走会回报 `cache_creation_input_tokens` 的 Anthropic 原生协议渠道。
