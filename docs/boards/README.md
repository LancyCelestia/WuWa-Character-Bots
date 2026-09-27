# 守岸人 Bot · 十板块功能树

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## 十板块

| 板块 | 名称 | 一句话 | 二级功能 |
|---|---|---|---|
| B01 | [接入与协议](B01-ingress-protocol/README.md) | 把任意平台的一条原始事件，变成主链路认识的一条入站消息。 | [QQ 协议端接入（SnowLuma / OneBot V11）](B01-ingress-protocol/qq-snowluma/README.md)、[Telegram 适配器](B01-ingress-protocol/telegram/README.md)、[邮件与控制台适配器](B01-ingress-protocol/mail-console/README.md)、[消息归一与身份中央件](B01-ingress-protocol/message-normalization/README.md) |
| B02 | [路由与中央调度](B02-routing-dispatch/README.md) | 决定一条消息归谁处理、能不能处理、由哪一个能力入口处理。 | [路由表与判定序](B02-routing-dispatch/route-table/README.md)、[能力注册表与调度壳](B02-routing-dispatch/capability-registry/README.md)、[决策引擎](B02-routing-dispatch/decision-engine/README.md)、[门禁与限流](B02-routing-dispatch/policy-gate/README.md) |
| B03 | [人格·对话·内容安全](B03-persona-chat-safety/README.md) | 让她像守岸人，并且任何设定都越不过写死的红线。 | [人格对话与回复](B03-persona-chat-safety/chat-reply/README.md)、[人格上下文与称谓身份](B03-persona-chat-safety/persona-context/README.md)、[好感度与心情](B03-persona-chat-safety/affinity-mood/README.md)、[怪癖演化](B03-persona-chat-safety/quirks/README.md)、[内容安全与亲密模式](B03-persona-chat-safety/content-safety/README.md) |
| B04 | [记忆·知识·笔记](B04-memory-knowledge-notes/README.md) | 她记得什么、从哪查到、怎么不记错。 | [会话历史与上下文](B04-memory-knowledge-notes/history/README.md)、[长期记忆与反思](B04-memory-knowledge-notes/long-term-memory/README.md)、[知识库与检索](B04-memory-knowledge-notes/knowledge/README.md)、[笔记与授时](B04-memory-knowledge-notes/notes/README.md) |
| B05 | [外部资讯与数据服务](B05-external-data-services/README.md) | 从外部世界取真数，取不到就诚实说取不到。 | [天气与预警](B05-external-data-services/weather/README.md)、[金融行情](B05-external-data-services/finance/README.md)、[快讯与历史上的今天](B05-external-data-services/news/README.md)、[订阅与更新推送](B05-external-data-services/subscription/README.md)、[紧急信息与预警](B05-external-data-services/emergency-info/README.md)、[链接解析与内容理解](B05-external-data-services/link-parse/README.md)、[百科与参考查询](B05-external-data-services/reference-wiki/README.md) |
| B06 | [多媒体与娱乐](B06-media-entertainment/README.md) | 声音、图像、表情、点歌、占卜与吃什么。 | [语音合成](B06-media-entertainment/tts/README.md)、[媒体归档](B06-media-entertainment/media-archive/README.md)、[图像与视频理解](B06-media-entertainment/vision/README.md)、[表情包与图库](B06-media-entertainment/meme/README.md)、[点歌](B06-media-entertainment/music/README.md)、[占卜](B06-media-entertainment/divination/README.md)、[创作与图片生成](B06-media-entertainment/creation/README.md)、[吃什么与菜谱](B06-media-entertainment/food/README.md) |
| B07 | [日程·自动化·助理](B07-schedule-automation/README.md) | 没有人发消息时，她按时间与条件自己动。 | [提醒督促](B07-schedule-automation/reminders/README.md)、[日程板与智能代答](B07-schedule-automation/schedule-board/README.md)、[调度器族与定时推送](B07-schedule-automation/scheduled-jobs/README.md)、[日常助理与收件箱](B07-schedule-automation/daily-assist/README.md)、[校园自动转发](B07-schedule-automation/campus-forward/README.md)、[自动发送与主动搭话](B07-schedule-automation/auto-send/README.md)、[巡检与同步漂移](B07-schedule-automation/ops-inspection/README.md) |
| B08 | [渲染与出站统一](B08-render-outbound/README.md) | 所有内容只有一种长法和一条出口。 | [卡片渲染](B08-render-outbound/card-render/README.md)、[出站文案与纯文本兜底](B08-render-outbound/outbound-copy/README.md)、[出站审核](B08-render-outbound/review-gate/README.md)、[发送队列与回执](B08-render-outbound/send-queue/README.md)、[文件网关与受控下载](B08-render-outbound/file-gateway/README.md)、[统一错误报告](B08-render-outbound/error-reporting/README.md) |
| B09 | [控制面·配置·可观测](B09-control-plane-observability/README.md) | 一切状态可查、一切开关可控、一切动作可审计。 | [控制面 API 与工作区](B09-control-plane-observability/control-plane-api/README.md)、[配置与运行时设置](B09-control-plane-observability/config-and-settings/README.md)、[功能开关树](B09-control-plane-observability/feature-switches/README.md)、[日志·指标·Trace·审计](B09-control-plane-observability/observability/README.md)、[模型路由与账本](B09-control-plane-observability/model-control/README.md)、[管理命令面](B09-control-plane-observability/admin-commands/README.md) |
| B10 | [工程基座与治理](B10-engineering-governance/README.md) | 门禁、生成物、命名规范与安全护栏——文档与代码不靠自觉。 | [任务入口与门禁](B10-engineering-governance/task-entry/README.md)、[生成物与机器事实册](B10-engineering-governance/generated-artifacts/README.md)、[测试与机器门体系](B10-engineering-governance/test-gates/README.md)、[命名与结构规范](B10-engineering-governance/naming-conventions/README.md)、[安全与凭据护栏](B10-engineering-governance/security-guardrails/README.md)、[路径重映射与树卫生](B10-engineering-governance/workspace-hygiene/README.md)、[文档体系与板块树](B10-engineering-governance/documentation/README.md) |

## 派生事实

- 板块 / 二级功能 / 三级入口：10 / 58 / 164
- 已认领 RouteKind / 帮助主题：37 / 82
- 权威声明源：`plugins/bot_unified_runtime/domains/core/board_taxonomy.py`
- 规范本体：[_conventions.md](_conventions.md)
- 重算命令：`python scripts/board_doc_sync.py --write`（体检用 `--check`）
<!-- BOARD-AUTO:END -->

## 怎么读这套文档

1. 先在上方十板块表里找到你关心的板块；
2. 进板块页看二级功能；
3. 进二级功能页看它拥有的三级入口与代码落点；
4. 规范与开发约束在 [_conventions.md](_conventions.md)，一律以它为准。
