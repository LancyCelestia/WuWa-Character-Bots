# 出站文案与纯文本兜底 · 段间换行统一

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B08.outbound-copy · 段间换行统一

- 层级：一级 B08 → 二级 outbound-copy → 三级 `paragraph-breaks`
- 实现落点：`plugins/bot_unified_runtime/output`、`plugins/bot_unified_runtime/domains/render/plain_text.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

解决一个很具体的观感问题：同一条角色扮演回复，段与段之间有时空一行、有时空两行，看着像随机。根因是三条产出路径各写各的分隔——有括号动作时拼段用双换行、纯文本路径原样返回、模型自己写空行又是一种。

现在的口径是：**出站段落分隔一律单个换行**。两个函数配合：

- `domains/render/roleplay.py:format_roleplay_paragraphs`：把括号动作与动作之外的连续文字拆成独立段落，段间用 `\n` 连接。无括号动作时等价 `text.strip()`。
- `domains/render/roleplay.py:normalize_paragraph_breaks`：折叠空行（含全空白行）与行尾空白后 strip，作为两条路径的共同出口。

动作与颜文字的判定共用 `_action_tokens`：括号内含汉字、或括号内还嵌套括号，算动作（拆段、朗读时剥除）；括号内无汉字（`(≧▽≦)`、`（*´▽｀*）`）算颜文字，原地保留不拆行——否则会把表情从句子中间甩到单独一行。未闭合括号按普通文字安全忽略。

## 怎么调用

在能力出口成对使用，不是由中央渲染器统一施加：

```
reply_text = normalize_paragraph_breaks(humanize_reply(reply_text))
```

生产消费者只有 `domains/chat_reply/capabilities/chat.py`（与 `format_roleplay_paragraphs`、`strip_action_brackets`、`strip_outer_speech_quotes` 同处）。顺序有讲究：拆段/整形在前、密钥打码在链路更外一层（`redact_local_secrets` 之后统一折叠），折叠不动段内文字内容，所以打码结果不受影响。

合并转发是**另一条**分片轴，别混：`domains/render/renderer.py:split_text_chunks` 按段落与长度上限切节点（超长段优先在句末标点/空白处断，避免把颜文字从中间切开），服务的是「多少条消息」，不是「段之间空几行」。

## 开关与参数

无开关、无配置键。相关的是转发阈值一组（`forward_min_chars` / `forward_node_chars` / `forward_min_nodes` / `forward_max_nodes`，装配期从 config 取，逐键以目录册为准）：

- 「按条数触发合并」＝切分后达到 `min_nodes`（现口径 ≥4 条，即用户说的「超过 3 条就合并」）才合并，只对非 chat 能力生效；chat 回复整条直发，仅保留超长字数触发。
- `min_chars <= 0` 表示不按字数拆；`max_nodes <= 0` 表示不人为限节点数，只受 `node_chars` 硬长度边界约束。
- 溢出反复合并可能突破节点长度：对尾块按边界二次切分，代价是块数临时超过 `max_nodes`——硬长度边界优先。

热改性：这些是装配期快照，热改当轮不生效（与台账 #3 同类口径）。

## 失败时看到什么

这一层不抛异常、不打日志：输入空串或纯空白返回空；未闭合括号当普通文字。历史「观感故障」的形态就是要看的东西——段间忽 1 忽 2 个换行、表情被甩成独立一行、合并转发把四段聊天回复折成一条聊天记录（后者已按「chat 不触发条数合并」收口）。

若某条回复分段异常，先确认它走的是哪条链：只有 chat 链过了这两个函数；能力自己拼文本的（笔记、订阅列表、诊断文本等）不在本页承诺范围内。

## 测试与验收

`tests/test_roleplay_paragraphs.py`（三路同构：括号拆段 / 无动作纯文本 / 模型自写空行，段间恒定单换行；动作独立成行的既有语义保持）、`tests/test_forward_and_mood.py` 与 `tests/test_perf_forward.py`（切分与合并触发）、`tests/test_rate_limit_silent_and_chat_forward.py`（chat 不触发条数合并）、`tests/test_a20_sender_session_order.py`（同会话串行，分片顺序）。

真机（重启后）：私聊发一条需要多段回应的角色扮演请求，肉眼确认段间恒定一个换行、动作行独立、颜文字不跳行；群聊发长回复确认 ≤3 条不折叠。
