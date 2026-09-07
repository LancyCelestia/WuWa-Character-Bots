# 参考插件取长补短评审（2026-09-07）

> 背景：应用户要求，将 12 个社区 NoneBot 插件克隆到源码树外（`%TEMP%\nb-plugin-ref-20260907`，未进入工作区与 Git），
> 与 `bot_unified_runtime` 现有实现逐一对比，评估"用更好的模块替换较差部分"。
> 结论先行：**本轮采纳 3 项、记录 4 项参考思路、5 项判定为不引入**；没有整插件替换——
> 本项目是统一运行时架构（统一入站/出站/审计），社区插件多为独立 matcher，整体引入会破坏统一边界。

## 1. 逐插件结论

| 插件 | 对应现有模块 | 结论 | 理由 |
|---|---|---|---|
| nonebot-plugin-tavily | `sources/search_api.py`、`sources/web_search.py` | 部分采纳 | 对方是官方 `tavily-python` SDK 薄封装；采纳其参数面（search_depth/time_range/extract 透传），我们本来就把 `provider_options` 自定义键透传进请求体，只需补文档。另加固了我们缺失的重试。 |
| nonebot_plugin_disconnect_notice | `runtime/disconnect_notice.py`（新增） | 采纳思路 | 掉线时 QQ 通道不可用，需走外部渠道；我们复用已有 Telegram 适配器与邮件桥实现，带冷却与配置开关。 |
| nonebot-plugin-WWwiki | `sources/mediawiki.py` | 不引入，记参考 | 对方是 biligame API + 本地数据 + PIL 卡片的完整方案，与我们的 MediaWiki 管线异构；"精确角色名判断 + 本地索引兜底"思路我们已在 wiki_lookup 实现。 |
| nonebot_plugin_analysis_bilibili | `sources/parsers/platforms_bilibili.py`、`wbi.py` | 不引入 | WBI 签名我们自有 `wbi.py`；其 ExpiringCache（无锁 set + 每项一个 Timer 线程）比现有实现弱，无采用价值。 |
| nonebot-plugin-parser-lite | `sources/parsers/`（23 个平台文件） | 不引入，记参考 | 平台覆盖我们更全（23 平台 vs 对方约 10）；其"评论区渲染"与"Live Photo"是我们解析卡可借鉴的后续增强方向。 |
| nonebot-plugin-multincm | `capabilities/music.py` 管线 | 不引入 | 多候选点歌交互思路可记；我们的音乐链路已含选流质量优先（杜比>HDR>SDR/Hi-Res）与订阅推送。 |
| nonebot_plugin_songpicker2 | 同上 | 不引入 | 数据源仅网易云，作者自述"当 API 参考用"；不维护状态不佳。 |
| nonebot-plugin-help | `capabilities` 内 help 主题 | 不引入 | 已 Archived 停止维护；我们的帮助页按用户 UX 规范逐参数写全（含义/格式/示例/常见错误），强于对方的 matcher 自动扫描。 |
| nonebot-plugin-htmlrender | `output/card_render/`（Mica 体系） | 不引入 | 对方是通用 HTML→图片服务（markdown/latex/代码高亮）；我们的 Mica 卡片体系有平台色派生与设计规范约束，混用会破坏统一视觉与 token 化样式。 |
| nonebot-plugin-memes | — | 不引入 | 需要重型推理运行时（onnx/torch 系），与本仓库轻依赖约束冲突；表情包能力已有 meme_library/meme_search。 |
| nonebot-plugin-personification (shiro) | 整个运行时 | 记参考（P1 设计） | 群聊参与决策、用户画像、主动社交、运维控制台的架构清单，对交接文档 P1"群聊 SceneState/记忆审批"设计有直接参考价值；不引入代码。 |
| nonebot-plugin-with-ai-agents | LLM 管线 | 记参考 | 页面内容学习/提取/联网问答的工具组织方式一般，自研 AGPL 风险未查明；不引入。 |

## 2. 本轮实际落地的改动

### 2.1 掉线管理员通知（新能力，借鉴 disconnect_notice）

- 新增 `plugins/bot_unified_runtime/runtime/disconnect_notice.py`：
  `DisconnectNotifier` 按 `适配器:bot_id` 维度冷却（默认 600s），通过仍在线的
  Telegram 管理员私聊（复用 `notify_telegram_admins`）与邮件桥（复用 `send_mail_from_account`）
  投递通知；渠道失败互不阻塞、不抛出。
- 接线：`__init__.py` 的 `driver.on_bot_disconnect` 钩子，通知结果写 `runtime_event_log`
  （`disconnect_notice_sent` 事件含 channels 字段）。
- 配置（默认全关，收件人显式配置才可能外发）：`BOT_DISCONNECT_NOTICE_ENABLED`、
  `BOT_DISCONNECT_NOTICE_COOLDOWN_SECONDS`、`BOT_DISCONNECT_NOTICE_MAIL_ACCOUNT`、
  `BOT_DISCONNECT_NOTICE_MAIL_RECIPIENTS`、`BOT_DISCONNECT_NOTICE_TELEGRAM_CHAT_IDS`。
- 测试：`tests/test_disconnect_notice.py` 6 项（配置解析、文案、冷却、开关、渠道失败隔离）。

### 2.2 搜索适配器加固（对比 tavily 插件）

- `_JsonSearchProvider` 增加瞬时错误原地重试（默认 1 次重试、0.25s 退避）：
  仅对 `httpx.TransportError`（超时/连接抖动）重试，HTTP 状态错误仍直接交给链式回退，
  不拖慢整体失败切换。
- Tavily `search_depth`/`time_range` 参数面：`BOT_WEB_SEARCH_PROVIDER_OPTIONS` 的自定义键
  本就透传进请求体（`search_api.py` 既有行为），已在 `.env.example` 补充示例文档，无代码改动。

### 2.3 Wiki 缓存与限流（交接文档 P2.9）

- `sources/mediawiki.py` 新增模块级 TTL 响应缓存（900s）+ 最小请求间隔（1s），
  四处 `http_get_json` 调用点全部改走 `_cached_get_json`；失败响应不缓存；
  缓存上限 256 条，满即清；提供 `clear_wiki_cache()` 供测试/运维。
- 效果：重复词条查询零外呼；对公开 wiki 站点降低触发限流的风险。

## 3. 明确不替换的判断依据

1. **架构边界优先**：社区插件独立注册 matcher、自带配置与存储，绕过统一入站/出站/审计；
   交接文档 P0.3 恰恰要求"删除不必要的直接 sender 分支"，整插件引入与该方向相反。
2. **许可与依赖**：部分插件依赖重型运行时（memes）或许可不明（with-ai-agents），引入风险大于收益。
3. **维护状态**：help 已归档、songpicker2 自述不稳定；我们的对应实现更新、覆盖更全。
4. **许可证注意**：WWwiki（biligame 数据与 PIL 绘图）与本项目 MediaWiki 自写薄层（明确不引入 AGPL/GPL 代码）
   的边界已在 `mediawiki.py` 模块注释中维持。

## 4. 后续可再评估项

- parser-lite 的评论区渲染（B 站评论楼）作为解析信息卡的增量板块；
- personification 的群聊参与决策/用户画像清单，供 P1 SceneState 设计时对照；
- multincm 的多候选列表交互（点歌返回编号列表让用户二次选择）。
