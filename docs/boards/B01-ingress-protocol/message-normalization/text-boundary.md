# 消息归一与身份中央件 · 触发词文本边界谓词

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B01.message-normalization · 触发词文本边界谓词

- 层级：一级 B01 → 二级 message-normalization → 三级 `text-boundary`
- 实现落点：`plugins/bot_unified_runtime/domains/core/session_keys.py`、`plugins/bot_unified_runtime/domains/core/text_boundary.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

回答「这句话里的触发词到底算不算命中，命中后正文是哪一段」。历史上这件事有六份手抄副本，其中一份把虚词当边界，直接把语音能力变成了聊天劫持器。本件收编为唯一的判定件：三套语义（取正文 / 取 bool / 取命中的词）共用同一份折叠与切片实现。

## 怎么调用

真身 `domains/core/text_boundary.py`（纯函数件，非登记能力）：

- `match_trigger(text, words, *, case_insensitive=True, boundary_chars=TRIGGER_BOUNDARY_CHARS, extra_boundary_chars="", newline_as_space=False) -> str`：返回命中后的正文（已剥边界符与两端空白）；未命中、或只发了触发词没带正文，一律返回空串（引导文案由调用方给）。
- `is_trigger(text, words, *, case_insensitive=False, bare_word=True, ...)`：bool 形态，缺省参数对齐 randpic / media_archive / group_info 的现行调用形状。
- `matched_trigger_word(text, words, *, ...)`：返回命中的词本身（群信息意图分派这类调用要的是「命中了哪个词」而不是正文）。
- 低层件：`is_boundary_char(ch, *, charset=...)`、`strip_boundary(tail, *, charset=...)`，供只需引用字符集子集的调用方（如昵称剥离）使用。

## 开关与参数

没有配置键。取值分三段登记，调用方只能选段、不许自造字符串：

| 常量 | 语义 | 谁用 |
|---|---|---|
| `TRIGGER_BOUNDARY_CHARS` | 权威集：只有真分隔符（标点与空白），一个词字符都不许进 | 缺省形态（tts 系） |
| `PARTICLE_BOUNDARY_CHARS` | 虚词/语气助词扩展，**不属于**权威集 | randpic / media_archive / group_info 经 `extra_boundary_chars` 显式组合 |
| `ADDRESS_BOUNDARY_CHARS` | 称呼/时间/请求词扩展 | mentions 族只取字符集组合 |

参数取向即语义取向：`case_insensitive=True` 是 tts 形态（英文 `SAY`/`TTS` 算命令，正文一律取原串切片，绝不返回折叠后的大小写）；`newline_as_space=True` 是 media_archive / group_info 的多行输入形态；`bare_word=False` 时裸触发词不算命中。

## 失败时看到什么

不存在抛异常的路径，失败形态是「不触发」：

- 包含关系词不命中——「说话要注意分寸」不会因为里有「说」就被吃掉；「语音消息」同理。
- 最长词优先，短词不截断长词（`语音合成` 之于 `语音`）。
- `casefold` 会改变长度的极端字符（ß→ss）会让折叠串偏移与原串偏移错位，这种输入退回逐字精确匹配：宁可不触发，也不切错正文或误触发。
- 繁體不做机器转换：繁體命中靠把条目（說/語音/朗讀/唸）登记进调用方词表，这是规格明文的口径，不是待办。

## 测试与验收

`tests/test_text_boundary_central.py`（权威集取值与棘轮负样本）、`tests/test_text_boundary_wiring.py`（消费方必须走中央件）、`tests/test_voice_boundary_central_gate.py`、`tests/test_tts_hijack_guard.py`（312 句语料不再被劫持）。
真机：`docs/acceptance-manual.md` §6.6.1 触发形态抽样（英文/拼音/繁體/昵称 + 劫持守卫负样本）。
