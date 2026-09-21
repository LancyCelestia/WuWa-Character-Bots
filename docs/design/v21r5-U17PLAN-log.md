# v21r5 U17-PLAN-2 席工作日志（重派席）

- 任务：为 U17-CAMPUS-WIRE 制作裁定卡 + 实施 runbook（纯文档，零代码改动）
- 状态：开场，建日志
- 素材清单：
  - docs/design/audit-20260920-unify-U17-campus-wire.md（U17 取证）
  - docs/design/v21r5-CAMPUS-log.md（campus-9 终态 + XFAIL 挂账）
  - plugins/bot_unified_runtime/domains/assistant/campus/campus.py（现 API）
  - 根 __init__.py:5044 附近旁路
  - tests/test_campus_digest.py（11 例 xfail 规约测试）

## 时间线
- [x] 读素材（audit / campus-log / campus.py / __init__.py / test_campus_digest.py）
- [x] 补充取证（runbook 精确坐标，全部实读）：
  - root `__init__.py`：campus_source(:3688)/pipeline(:3747)/offload_capability(:3588) 与 handler(:5007-5044) **同函数作用域**，收编无需新装配面；:36 顶部 import 原地扩展可零增行（保坐标不漂）
  - 两形态 A 先例实读：today_history `_push`(:1832-1875)、订阅推送(:4329-4353)——均 `pipeline.handle_async(message, offload_capability(cap), capability_id=...)`；其后的 `_find_sent_request`+内联投递是调度器专用，campus 走队列 worker 不需要
  - 契约实读（domains/core/contracts/runtime.py）：IncomingMessage(:121-184，private 缺省 PERSONAL)、CapabilityResult(:226-269，body/audit_tags)、SendRequest(:294+)
  - pipeline 实读：_prepare 决策 IMMEDIATE(:660-680)、_complete dedupe_key 公式 `{capability_id}:{session_id}:{message_id}`(:818-821)、persona tag 机制(:293-302)、review BLOCK 路径(:731-753)、合并转发触发(:761-785)；forward_min_chars=config.bot_render_forward_min_chars(root:3772)
  - reviewer 实读：leak 面扫 body（密钥/内部标记），persona drift 仅 bot.chat（campus 豁免）
  - offload_capability 签名(:225-237)：sync 闭包入 chat 线程池+gate，busy→SKIPPED（低概率行为差，如实记录）
  - outbound_registry.py:433-444：campus 条目 note 已记 U17 指定，location 硬编码 `__init__.py:5012`（handler 改动若在其上方增删行→坐标漂→须同步刷新）
  - CampusForwardRequest 外部引用面=零（仅 campus.py 自身与测试注释）；capability_registry.py:544 登记在案
- [x] 撰写 docs/design/v21r5-u17-implementation-runbook.md（裁定卡 + 实施 runbook + 工作量风险评估三部分齐）
- [x] 自检收尾：runbook 全部坐标引用与实读值逐条核对一致；红线遵守确认（零代码改动、未碰 root `__init__.py`、未 commit、未读 .env 值、无子代理、无真实发送）。

## 交付
- `docs/design/v21r5-u17-implementation-runbook.md`：
  - §1 裁定卡：U17 是什么/现状实测表/不实施后果/收益/风险（root `__init__.py` 共享冲突最高、纯监听红线零削弱）+ 8 项行为差清单；两裁定点各两选项——①review 门推荐接受（fail-closed，密钥形态原文直达私聊是旁路既有缺口，无豁免中间态）②1501 字合并转发推荐接受零改动（改预算破坏 verbatim oracle；生产 `BOT_RENDER_FORWARD_MIN_CHARS` 现值 unknown 待用户确认）。
  - §2 runbook：campus.py 六步（撤脚手架→payload→record 转 payload→两 builder 逐字段映射含测试断言坐标）+ 旧段两例重写授权引用；root `__init__.py` 两处精确改法（:36 import 原地扩展零增行保坐标、handler 尾段改写含结构锁自检）+ S0-ROOT-c 互斥协调；注册面零动作；11 处 xfail 摘牌（搜 U17-CAMPUS-WIRE）；验收六级（29 全绿/棘轮族/坐标门/静态门/全量/真机 §6.6）+ S0 四条存量 FAIL 不扩权警示；回滚三式（diff 快照逆向/重启回旧/三既成事实不回滚）。
  - §3 评估：3+1 文件、约 +60 净行、29 例+棘轮约 120 例测试面、1-2h 级工时、风险分级表。
- 本席零代码改动；本 log 与 runbook 两个文档文件为全部产出。

**U17PLAN-SEAT DONE** — 2026-09-20，U17-PLAN-2（重派席；前任死于平台故障零改动）。
