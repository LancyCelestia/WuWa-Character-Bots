# 表情包与图库 · 偷表情

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.meme · 偷表情

- 层级：一级 B06 → 二级 meme → 三级 `meme-library`
- 路由席位：`MEME_LIBRARY`（matcher `meme_library`，command=True）
- 判定优先级：22
- 能力 id：`bot.meme_library`
- 实现落点：`plugins/bot_unified_runtime/domains/meme`
- 帮助主题：偷表情
<!-- BOARD-AUTO:END -->

## 这个入口做什么

两件事：**收**和**发**。收——群聊里出现的图片被旁路监听下载、去重、（可选）VLM
打标签后入本地表情库；发——`偷表情 [关键词]` 按权重随机挑一张发出，可带关键词或
情绪标签过滤。库的统计（总数/已用/被 NSFW 拦下的数量）由存储层 `stats` 供管理员
诊断面消费。指令形态含简体、繁體与拼音别名（如「偷图」「表情隨機」），完整集合以
`_COMMAND_RE` 与 `docs/command-catalog.md` 为准。

## 怎么调用

- 能力侧：`domains/meme/capabilities/meme_library.py` 的
  `is_meme_library_command` / `parse_meme_library_command` /
  `build_meme_library_capability`，声明行认领 `RouteKind.MEME_LIBRARY` /
  `bot.meme_library`（优先级高于表情包生成，避免与「表情」族互抢）。
- 存储侧：`domains/meme/sources/meme_library.py` 的库类——`add`（落盘 + 入索引）、
  `apply_tags`（打标签并据 `_score_weight` 重算权重）、`weighted_pick`（带
  `keyword` 与 `nsfw_max` 的加权抽取）、`remove`、`mark_used`、`list_untagged`、
  `stats`。文件是事实来源，SQLite 只做索引。
- 监听侧：`domains/meme/sources/meme_library_listener.py`——群图片段异步下载、
  md5 去重、可选 VLM 打标。下载走中央 SSRF 咽喉，本域不自建校验。
- 权重规则（唯一真身在 `_score_weight`）：命中「守岸人/岸宝/鸣潮/战双帕弥什/库洛」
  等偏好标签最优先，其次 ACG，再次普通；判定非表情/普通图片降权；
  `nsfw_score ≥ 0.2` 再降权，`≥ 0.8` 永不抽中。
- 情绪档（N4）：bot 心情低落（valence 达低落档，与 `character/mood.py` 同阈值）时，
  命中吵闹标签的候选做有限次重抽；全部吵闹也照发——只调倾向，不做硬开关。

## 开关与参数

- `bot_meme_library_enabled`（False，生产已开）：库与监听总闸。
- `bot_meme_library_dir` / `bot_meme_library_db_path`：库目录与索引库，均在
  `path_fields` 内重映射。
- `bot_meme_library_max_file_bytes`（字节上限以 `config.py` 该字段为准）、`bot_meme_library_max_files`、
  `bot_meme_library_max_age_days`：入库体积上限与 FIFO/TTL 剪枝（表情库是可再生
  缓存，与媒体归档的永久保存相反）。
- `bot_meme_library_cooldown_seconds`（20）：同人同会话发送冷却，防刷屏。
- `bot_meme_library_group_allowlist` / `_denylist`：哪些群允许收图（黑白名单口径
  与全仓一致，名单为空即等于不收）。
- `bot_meme_library_nsfw_max`（0.2，抽图上限）、`bot_meme_library_nsfw_delete`
  （0.8，达分即连文件带记录删）。
- `bot_meme_library_prefer`：偏好标签序列（改它=改选图倾向，属人格向调整）。
- VLM 打标：`bot_meme_library_vlm_enabled`（False）及 `_vlm_model`/`_vlm_base_url`/
  `_vlm_api_key`/`_vlm_timeout_seconds`/`_vlm_preset`；密钥只写 `env:变量名`。

## 失败时看到什么

- 库空或全部被过滤：不硬发，回一句「库里还没存到合适的表情」，并保留用户指令的
  可复制形态。
- 冷却中：直接不发、不刷屏解释。冷却表是进程内有界表（超界淘汰最久未用条目），
  重启即清零——它是防连点，不是配额账本。
- VLM 未启用或打标失败：图片仍入库，标签留空、权重走默认档；`list_untagged` 就是
  为这种积压准备的核对口。
- 下载失败/被 SSRF 闸拒/超体积：该图不入库，记日志原文，不影响当条消息的其它处理。
- 判定为 NSFW 达删除线：文件与记录一并删除，统计里计入被拦项。

## 测试与验收

`tests/test_meme_domain_fixes.py`（抽取与冷却、NSFW 降权与拦截）、
`test_meme_image_input.py`、`test_reactions.py`/`test_reaction_store.py`（相邻的
贴纸回应面）。真机：`docs/acceptance-manual.md` §6.4（收图 → 偷表情 → 冷却 →
带关键词）与 §6.6.6（贴纸回应联动）。
