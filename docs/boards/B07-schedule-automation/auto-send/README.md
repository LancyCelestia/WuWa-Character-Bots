# B07.auto-send 自动发送与主动搭话

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.auto-send 自动发送与主动搭话

> 主动性行为的门、概率与冷却，以及失败静默口径。

- 归属板块：[B07](../README.md)
- 实现落点：—
- 路由席位：`AUTO_SEND`
- 能力 id：`bot.auto_send`
- 帮助主题：队列
- 配置键前缀：`bot_auto_send_`, `bot_reactions_`（逐键以目录册为准）

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
| [自动发送](auto-send.md) | AUTO_SEND | bot.auto_send | — | 13 |
| [表情回应的五层防刷屏门](sticker-reactions.md) | — | — | — | — |
<!-- BOARD-AUTO:END -->

## 这个功能解决什么

"主动性行为"的收口处：她什么时候可以自己开口、自己贴表情、替人起草一条要发的消息，以及这些主动动作在失败时如何安静退出而不打扰人。它不是一条命令，而是一组**门 + 概率 + 冷却 + 静默**的口径，管住所有"没人点名也想动"的冲动，防止变成骚扰。

三块内容：① 自动发送/起草命令（`AUTO_SEND` / `bot.auto_send`，报存一句话把"要发什么"落成结构化草稿并预览，M0 只预览不真实发送）；② 主动搭话的群聊亲和门（抽签接话只对达到好感门槛的人生效）；③ 表情贴纸回应的识别与主动贴（五层防刷屏门）。

## 处理流程

```mermaid
flowchart LR
  subgraph 起草
    cmd[报存 给 X 发 邮件|消息 …] --> parse[parse_auto_send_command] --> prev[草稿预览 SILENT]
  end
  subgraph 主动
    ev[群消息/刚回复完] --> gate{主动搭话好感门 ∧ 五层表情门}
    gate -->|全过| act[接话 / 贴表情 set_msg_emoji_like]
    gate -->|任一不过| silent[静默不动]
  end
```

## 边界与降级

- 起草只到"预览"：结构化出通道/收件人/主题/正文要求，不出真实发送；风险按通道分级（邮件 MEDIUM、消息 LOW），`requested_send_policy=confirm_required`。帮助主题「草稿」讲这条命令（发送队列状态另见「队列」主题）。
- 主动搭话：群聊抽签主动接话（`proactive_reply_selected`）只对好感达到门槛的用户放行，判定函数经 `configure_proactive_affinity_gate` 注入，未注入或判定失败**宁可沉默**，不冒险主动搭话；限流另有 proactive 分桶（冷却 + 每小时上限），避免双份记账。
- 表情回应失败一律静默（贴表情 API 抛错只 debug 一行），绝不影响正常回复；**主动贴表情只支持群消息，私聊一律不派发**（详见三级页）。

## 测试与验收

`tests/test_content_video_auto_send.py`（起草解析）、`tests/test_reactions.py`（五层门与私聊守卫）、`tests/test_reaction_store.py`（聚合统计）。真机验收见 `docs/acceptance-manual.md` 表情/主动相关条目。

## 现行缺陷

- 自动发送是"预览版（M0）"：确认发送与批量装配为后续版本，当前不做真实发送（不谎报能力）。
- Telegram 无 reaction 事件键，识别侧只留归一接口不接线；主动贴表情 TG 侧提供 wrapper 但不接触发点，属诚实降级（台账相关登记）。
