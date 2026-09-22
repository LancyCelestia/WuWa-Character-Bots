# 自动事实册（机器所有 · 勿手改）

> 本册由 `python scripts/doc_sync.py --write` 从代码整册重生成；
> `--check` 漂移即红（tests/test_cross_validation_gates.py 常驻）。
> 生成时间字段不在册（保证字节确定性，避免无意义漂移）。

- 模板清单（7）：affinity_card.html, error_card.html, finance_card.html, market_card.html, mermaid_card.html, song_candidates.html, universal_card.html

- RouteKind（35）：ALIAS, ADMIN, SUBSCRIBE, AUTO_SEND, MEME, MEME_LIBRARY, MUSIC_MODE, MUSIC, TODAY_HISTORY, WIKI, MOEGIRL, MOEGIRL_QUESTION, EPIC, WEATHER, MARKET, STOCKS, COMMODITIES, BOND, NORTHBOUND, FX, NEWS, RANDPIC, REMINDER, MEDIA_ARCHIVE, DAILY_ASSIST, GROUP_INFO, EAT, AFFINITY, DIVINATION, TTS, NATURAL_COMMAND, CONTENT, CHAT, EMERGENCY_INFO, IGNORE

- 帮助 topic 数：78（重名 0）
- 测试文件数：560
- config.py bot_* 字段数：682

- 哈希清单范围（19）：plugins/bot_unified_runtime/domains/render/card_render/templates/universal_card.html, plugins/bot_unified_runtime/domains/render/card_render/templates/affinity_card.html, plugins/bot_unified_runtime/domains/render/card_render/templates/finance_card.html, plugins/bot_unified_runtime/domains/render/card_render/templates/market_card.html, plugins/bot_unified_runtime/domains/render/card_render/templates/mermaid_card.html, plugins/bot_unified_runtime/domains/render/card_render/templates/song_candidates.html, plugins/bot_unified_runtime/domains/render/card_render/templates/error_card.html, plugins/bot_unified_runtime/domains/render/card_render/theme_tokens.py, docs/rendering-contract.md, DESIGN-SPEC.md, docs/design/fstring-card-dom-spec.md, docs/design/render-pipeline-optimization-spec.md, docs/design/visual-effects-catalog.md, plugins/bot_unified_runtime/domains/render/card_render/bridge.py, plugins/bot_unified_runtime/domains/ops/admin/debug.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py, plugins/bot_unified_runtime/domains/render/card_render/usage_cards.py, plugins/bot_unified_runtime/domains/render/renderer.py, plugins/bot_unified_runtime/domains/render/templates.py
