# 订阅与更新推送 · Epic 免费游戏

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.subscription · Epic 免费游戏

- 层级：一级 B05 → 二级 subscription → 三级 `epic`
- 路由席位：`EPIC`（matcher `epic`，command=True）
- 判定优先级：41
- 能力 id：`bot.epic`
- 实现落点：`plugins/bot_unified_runtime/domains/subscribe`、`plugins/bot_unified_runtime/sources/subscriptions`
- 帮助主题：Epic
<!-- BOARD-AUTO:END -->

## 这个入口做什么

`epic` / `epicfree` / `Epic 免费`：把 Epic 商城本周限免与 Steam 当前 100% 折扣（可免费领取）的游戏合在一张卡上展示。它是**即时查询**，不是订阅——"epic 更新自动提醒"不在本入口的能力范围内。

## 怎么调用

- 席位 `EPIC`、能力 id `bot.epic`、优先级 41；闭包 `domains/subscribe/capabilities/epic.py:build_epic_capability(config, *, render_backend)`，谓词 `is_epic_command`。
- 数据真身：`domains/subscribe/feeds/epicfree.py:fetch_epic_free_games(*, proxy, timeout)`（Epic 公开免费促销接口，免 key，`locale=zh-CN&country=CN`）；`domains/subscribe/feeds/steamfree.py:fetch_steam_free_games(*, proxy, timeout, limit)`（Steam featured categories 的 `specials.items` 中 `discount_percent == 100`）。
- 图片取横版商店大图（`_wide_image`：OfferImageWide 优先、退 Thumbnail）。
- 出卡：复用解析卡的 `render_card_png` 管线（B05.link-parse → B08），文本作 caption/兜底；条目格式化在 `_format_games`。

## 开关与参数

- `bot_epic_enabled`（缺省 True）。Steam 侧无独立开关（同源同一次查询）。
- 超时是函数参数（缺省 12.0s，两家商店接口都偏慢），代理取 `bot_download_proxy`。
- 无角色门、无额度。

## 失败时看到什么

- Epic 取到、Steam 取不到：只展示 Epic 段，另一段省略（不写"0 款"）。
- 两边都失败：一句人话取数失败；当前确实没有限免时按上游给的空态展示，**不从模型记忆里补游戏名**。
- 渲染失败：纯文本清单，内容与卡片文字版一致。
- 时间字段解析不出来：不显示"截止"字样，而不是显示 1970 或空日期。

## 测试与验收

离线：`tests/test_epic_card.py`（两源合并、空态、图片优先级、时间解析失败路径），全部 monkeypatch 取数出口。
真机：`epic`、`Epic 免费`；对照商店页面确认本周限免条数一致；网络受限环境下降级为纯文本属预期。
