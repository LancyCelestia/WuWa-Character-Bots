# B07 日程·自动化·助理

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07 日程·自动化·助理

> 没有人发消息时，她按时间与条件自己动。

职责：

- 提醒与调度器族（cron 口径统一）
- 定时推送：每日摘要、收件箱早报晚报、历史上的今天
- 校园自动转发等纯监听旁路
- 自检与巡检（同步漂移、就绪度、凭据到期）

### 二级功能

| 二级功能 | 一句话 | 三级入口 |
|---|---|---|
| [提醒督促](reminders/README.md) | 自然语言时间点→会话待办→到点投递，含迟到与过期治理。 | [提醒](reminders/reminder.md)、[时间点解析词表](reminders/natural-time-parsing.md)、[投递、顺延与作废](reminders/delivery-and-lateness.md) |
| [日程板与智能代答](schedule-board/README.md) | 自然语言/命令/课表导入建日程板（复用 V2.1 引擎），别人问「她在干嘛」按可见性分级代答（隐私判定在出站前）。 | [可见性分级投影（代答腿）](schedule-board/visibility-projection.md)、[课表文本/图片导入](schedule-board/timetable-import.md) |
| [调度器族与定时推送](scheduled-jobs/README.md) | 根装配期注册的全部定时任务清单、时区口径与去重。 | [发送队列驱动](scheduled-jobs/send-queue-scheduler.md)、[夜间反思窗口](scheduled-jobs/reflection-scheduler.md)、[每日通讯摘要推送](scheduled-jobs/digest-push.md)、[历史上的今天推送](scheduled-jobs/today-history-scheduler.md)、[凭据到期巡检](scheduled-jobs/credential-check-scheduler.md)、[知识库同步](scheduled-jobs/kb-wiki-sync-scheduler.md)、[落盘点 TTL 清扫调度](scheduled-jobs/file-sweep-scheduler.md) |
| [日常助理与收件箱](daily-assist/README.md) | 收件箱速记、饭点建议、早晚对账推送。 | [收件箱速记](daily-assist/daily-assist.md) |
| [校园自动转发](campus-forward/README.md) | 三重来源门 + 幂等去重的纯监听旁路，绝不向源群发言。 | — |
| [自动发送与主动搭话](auto-send/README.md) | 主动性行为的门、概率与冷却，以及失败静默口径。 | [自动发送](auto-send/auto-send.md)、[表情回应的五层防刷屏门](auto-send/sticker-reactions.md) |
| [巡检与同步漂移](ops-inspection/README.md) | 源-副本漂移检测、告警投递与重启前体检。 | — |
<!-- BOARD-AUTO:END -->

## 板块职责

（本板块的 responsibilities 已在上方自动生成；此处补写"为什么这样切"与与其他板块的边界。）

切分依据是"触发方式"，不是"业务域"：凡由**消息**驱动的交互都归各自业务域（提醒里的 NL 解析、订阅、金融…都在 B02/B05），本板块只收**由时间或条件自己触发**的那部分——调度器族、纯监听旁路、主动性门。同一条能力可能横跨两块：如"提醒"的解析在 B07.reminders，投递复用 B08；"历史上的今天"查询在 B05.news，定时推送腿在 B07.scheduled-jobs；"每日群摘要"的内容在 B04/B05，21:30 的推送调度在 B07。这样切是为了让"什么时候会自己动"只有一份清单可查，避免每条定时链路各写一处时区/去重/失败口径。

## 上下游

- 入站：本板块由插件装配期 `on_startup` 起步（`nonebot_plugin_apscheduler` 提供调度器），以及 B01 摄取层归一后的事件（如贴纸回应 notice、校园群消息）。
- 产出：所有主动投递一律交回 B08 统一出站链（`review → renderer → send_queue → sender`），域内绝不直调 `send_queue.submit`；会话键走 B01 的 `domains/core/session_keys.py`、文本打码走 B08 `plain_text.redact_local_secrets`。
- 相邻板块：路由/门禁在 B02、渲染与队列在 B08、告警与可观测在 B09（sync_drift 复用其运维告警渠道）、巡检涉及的生成物门在 B10。

## 退役与并入记录

- 旧路径 `capabilities.auto_send`、`runtime.reactions` 已在 v21r2 域重组中迁到 `domains/schedule/auto_send` 与 `domains/meme/reactions/engine.py`；那两枚**再导出垫片本身已于 P2 减量波三态退役**（文件＋账本行＋牵动面同批动，旧名不可 import，防写回锁在册），本板块文档只认新真身。
- 校园自动转发原"裸 `send_queue.submit` 旁路"经 U17 收编进中央出站管线（review 门 fail-closed + 打码前置），旁路口径已退役。
- 每日摘要推送的 llm_provider 缺传、群摘要 session_id 口径两项早期缺陷在各自波次修于 shared_group 域（B04/B05），B07 只保留"到点触发"这条腿，不再重复记录内容侧沿革。
- 波次过程件（席位日志/brief/report）留在 `.superpowers/`，不进本板块目录。
