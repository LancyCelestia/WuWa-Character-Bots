# angel_heart / angel_memory 提示词注入思路调研（只借鉴设计，不抄代码）

- 来源：
  - `astrbot_plugin_angel_heart`（kawayiYokami），**AGPL-3.0**
  - `astrbot_plugin_angel_memory`（kawayiYokami），**AGPL-3.0**
- 结论：**两个插件均为 AGPL 强 copyleft**，本项目没有复制它们的任何代码或提示词原文，
  只学习其“结构设计思路”并用我们自己的文字重新实现。若未来要直接合并其代码，必须
  评估 AGPL 传染性，不可未经用户确认就并入本仓库。

## angel_heart 的思路
- 把系统提示词拆成多个 `.md` 模块（identity/behavior_rules/decision_logic/
  conversation_analysis/strategy_generation/instruction|reasoning_prompts），
  由 `PromptModuleLoader` 动态组装成一个模板，用 `SafeFormatter` 做缺省安全替换。
- 每个模块用 XML 风格标签分区（如 `<角色设定>`、`<行为准则>`），让模型明确各段语义。
- 行为准则强调“宁缺毋滥”：只回应被提及的话题、追求信息密度、删掉无意义附和。
- 两级模型：轻量模型先做“是否回复/回复策略”的决策，重量级模型再生成正文；
  决策以结构化 JSON 输出并校验。

## angel_memory 的思路
- 用 Function-Tool 把“记忆检索”交给确定性代码：`angel_recall(query)` 返回
  `[记忆检索结果]` 和 `[笔记检索结果]` 等**带标签的文本块**，注入到 LLM 上下文。
- 笔记检索先做“query 词必须命中正文”的精准过滤，再按文件聚合 + 行号预览，
  并提供二次展开工具 `angel_note_read(note_short_id, offset, limit)`，避免一次性塞满。
- 记忆有 scope 隔离，检索按当前会话作用域过滤，防止跨用户泄露。

## 我们采用/强化了什么（均为自研写法）
1. 提示词分区：本项目已有 角色边界/风格/知识库/世界观词表/情绪/记忆/关系 等分节，
   本轮新增“回答方式（世界观解释）”：先事实后感受，禁止打哑谜。
2. 向量知识检索（等价 angel_recall 的检索思路，我们直接内嵌在上下文构建里，
   不依赖 function calling）：本地 Ollama bge-m3 优先 + 百炼兜底。
3. 输出语义改为 0=不限制：完整回复一次性发出，去掉截断提示；颜文字不被动作格式器拆行。
4. 质量准则（自研措辞）：每句话要么给事实、要么给情感价值，避免纯附和——已在
   世界观解释规则与人格材料中体现，未照抄 angel 的原文。
