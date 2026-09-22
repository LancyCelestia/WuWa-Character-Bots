# 语音合成 · 语音合成

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.tts · 语音合成

- 层级：一级 B06 → 二级 tts → 三级 `tts`
- 路由席位：`TTS`（matcher `tts`，command=True）
- 判定优先级：41
- 能力 id：`bot.tts`
- 实现落点：`plugins/bot_unified_runtime/domains/media/capabilities/tts.py`、`plugins/bot_unified_runtime/domains/creation/tts`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

用户用触发词点名一段文本（`说 今天的潮汐很安静`、`语音 我在这里`、`tts hello`、
繁體 `說/語音/唸/朗讀/語音合成`），入口把这段文本合成成守岸人音色的语音消息发出。
输入是 `IncomingMessage.plain_text`，产出是 `CapabilityResult`：成功时 `kind="mixed"`
（正文 + 一个 `record` 音频部件，部件带 `file` 与 `content_sha256`），被门拦下或
失败时退化为纯文本回执。

生效条件：`bot_tts_enabled` 为真（缺省 False）。关掉时返回 `SendPolicy.SILENT_AUDIT`
的静默结果并挂 `skip_disabled` 标签，不打扰用户也不占外呼。

HTTP 调用是阻塞的，能力在 offload 线程池里同步执行，绝不跑在事件循环线程上。

## 怎么调用

声明与装配沿中央登记面走：`domains/chat_reply/runtime/capability_registry.py` 的
`ROUTE_CAPABILITY_DECLARATIONS` 认领 `RouteKind.TTS` 与 `bot.tts`，构造口是
`domains/media/capabilities/tts.py:build_tts_capability`。入口链上被复用的公开件
（同文件）：

- `extract_tts_text` / `is_tts_command` / `effective_trigger_words`：触发与取正文，
  边界字符集与 casefold 判定走中央件 `domains/core/text_boundary.py`，不留副本。
- `resolve_speech_text`：合成前唯一取文口（打码 → 剥括号动作 → 读法词典 → markdown
  清洗 → 截断 → 内容门），返回 `(可朗读正文, 拒绝理由)`。
- `speech_block_reason`：内容闸，与自动配音同源，安全维度走
  `domains/chat_reply/runtime/content_route.py:explicit_allowed_for_session`。
- `parse_ref_audios` / `pick_ref_audio`：参考音频清单与确定性选取。
- `synthesize`：缓存 → 退避闸 → 请求 → 体检 → 落盘，返回 `(路径, 失败原因)`。
- `should_voice_reply` / `maybe_attach_voice`：自动配音与配音 hook 的门链（开关
  `bot_tts_voice_hook_enabled`，缺省 False）。

出站不在本域：`review → renderer → send_queue → sender`，见
[B08](../../B08-render-outbound/README.md)。主动投递只准走
`submit_active_push`，本能力不直调 `send_queue.submit`。

## 开关与参数

前缀 `bot_tts_`，逐键的热更性与取值域以 `docs/config-catalog-full.md` 为准；生产
`.env` 改动一律重启进程后才进内存。本入口直接相关的键：

- `bot_tts_enabled`（False）、`bot_tts_trigger_words`（追加内置词表）、
  `bot_tts_max_chars`（200，`0`=不限）、`bot_tts_hard_max_chars`（2000）、
  `bot_tts_timeout_seconds`（60，`ge=1.0`）。
- 引擎与素材：`bot_tts_api_url`（`http://127.0.0.1:9880`，受 loopback 白名单闸
  fail-closed 约束）、`bot_tts_gptsovits_dir`（相对路径基准）、
  `bot_tts_ref_audios`（`路径|这段音频说的话` 形态列表）、`bot_tts_output_dir`
  （产物目录，以 `config.py` 的 `bot_tts_output_dir` 为准，经 `scripts/runtime_paths.py` 重映射）、`bot_tts_preset`
  （`shorekeeper`）。
- 自动配音面：`bot_tts_auto_reply_enabled`（False）、`bot_tts_auto_reply_scope`
  （`private|group|all`）、`bot_tts_auto_reply_max_chars`（120）、
  `bot_tts_auto_reply_probability`（0.05）、`bot_tts_auto_reply_always`（False）、
  `bot_tts_voice_hook_enabled`（False）。
- 缓存：`bot_tts_cache_enabled`（True）、`bot_tts_cache_max_bytes`/
  `bot_tts_cache_max_age_days`（均 0=不限制）。

谁能改：管理员经 `/bot runtime set` 与 `.env`；生产进程重启由用户提权执行。
采样参数与域闸见 `engine-contract.md`，参考音频见 `voice-identity.md`。

## 失败时看到什么

- 只发触发词没带正文：给用法引导（「在『说』后面接上想让我念的话就行」），不空合成。
- 被内容门有意拦下：`这段话我不念出声——留在文字里就好。`，标签
  `blocked_by_policy`，**不挂 issue**（政策拒绝不是故障，挂了就刷屏）。若闸自身
  坏了（`policy_unavailable`）则挂 issue 走中央告警链，静默会让管理员永远不知道
  名单库故障。
- 清洗后没内容可念：`这段话里没有能念出来的内容——换一句试试？`，带上
  `empty_after_clean` 与有损变换事实（`kept_ratio`/`redacted`/`truncated`…）。
- 超文本硬顶：`这段话太长了，我一口气念不完——拆成几句再说给我听好不好？`，
  带 `over_hard_cap` + `len=` + `cap=`；**不自动拆条**（拆条等于把没有幂等保护的
  语音翻倍）。
- 合成链故障按 `_FAILURE_KINDS` 前缀映射成 `OperationalIssue` 族：
  `tts_service_unreachable`（可重试）、`tts_empty_audio`（可重试）、`tts_bad_audio`、
  `tts_service_rejected`、`tts_write_failed`、`tts_no_ref_audio`。用户侧只看到守岸人
  口吻的降级文案（不可达 / 参考音频不合用 / 通用三条），不暴露内部细节。

## 测试与验收

`tests/test_tts.py`（主链）、`test_tts_hijack_guard.py`（虚词劫持负样本）、
`test_tts_speech_gate.py`、`test_tts_failure_visibility.py`、
`test_tts_outbound_chain.py`、`test_voice_media_routing.py`；机读事实与出站契约另见
`test_voice_outbound_contract.py`。真机：`docs/acceptance-manual.md` §6.6.11 的
用户向条目（触发、繁体、超长、引擎未起四条），以及
`python scripts/tts_retcode_collect.py --json` 的退码闭合面。
