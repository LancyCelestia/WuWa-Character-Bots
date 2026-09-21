# 紧急信息与预警 · 紧急信息

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.emergency-info · 紧急信息

- 层级：一级 B05 → 二级 emergency-info → 三级 `emergency-info`
- 路由席位：`EMERGENCY_INFO`（matcher `emergency_info`，command=True）
- 判定优先级：44
- 能力 id：`bot.emergency_info`
- 实现落点：`plugins/bot_unified_runtime/domains/emergency_info`
- 帮助主题：紧急信息
<!-- BOARD-AUTO:END -->

## 这个入口做什么

本域唯一的用户可见入口（查询 + 报料 + 审核读侧 + 订阅命令面）。触发词：`紧急信息` / `预警` / `地震` / `震情` / `emergency`（繁体 `緊急信息`/`預警` 同族）。用户说一句话可以得到：最近快照里的条目列表、某条详情、待审列表，或者把本群/本人的订阅条件设下来。**主动推送不由这个入口发**（那是 `service/push.py` 的唯一职责）。

## 怎么调用

- 席位 `EMERGENCY_INFO`（优先级 44，用户裁 U-2 钉死）、能力 id `bot.emergency_info`；装配入口 `domains/emergency_info/capabilities/emergency_info.py:build_emergency_info_capability(config, *, render_backend)`，触发谓词 `is_emergency_info_command`（路由侧与能力侧共用同一份正则，禁第二份表；正则真身在该文件 `_EMERGENCY_RE`，词右界由 lookahead 承担）。
- 装配门快照：`build_emergency_info_source(config)`（两腿：总闸 ∧ 有源，运行期只读）。
- 服务句柄：`EmergencyInfoService`（持存储/快照/中央闸，判"投递面是否可用"——闸缺失即不可用，绝不退化成裸投递）。
- 读侧格式化：`format_emergency_line` / `format_emergency_detail` / `_category_tag`。
- 订阅命令面：`subscription_target`、`subscription_platform_supported`、`allows_emergency_subscription`、`subscription_subcommand`、`run_subscription_command`（详见 [群内订阅与投递门](group-subscriptions.md)）。
- 审核面：`allows_emergency_review` + `build_review_gate(store, source)`（唯一构造口）。

## 开关与参数

十枚 `bot_emergency_info_*`（逐键以 `docs/config-catalog-full.md` 紧急信息节为准，值不写进本文档）：`enabled`（缺省 False）、`sources`（缺省空）、`auto_approve_sources`（缺省空＝全部人工 PENDING）、`poll_interval_seconds`、`min_level`（缺省 P2）、`reviewer_ids`、`keep_days`、`db_path`（进 path_fields 重映射）、`push_group_whitelist` / `push_user_ids`（**已降级为可选硬推腿，不参与装配门**；名单内目标每轮收全部过门槛条目、不受订阅条件约束）。均为装配期快照，改完要重启（唯一例外是订阅表——现读、当轮生效）。帮助 topic=紧急信息 为 `admin_only`（用户裁 U-3）。

## 失败时看到什么

- 装配门任一腿为空：整链不注册，所有触发词零反应（`/bot status` 不该出现该域异常）。
- 快照四态：`NEVER_FETCHED`（一轮没跑过）、`FRESH`、`STALE`（旧但照实回传并说旧）、`FETCH_FAILED`（取数失败仍回上一轮条目并明说"这次没取到"）——调用方必须按 `state` 决定文案，**不许只看条目列表空不空**。
- 未定级条目：列表与详情都不显示等级，不写"未知等级"糊弄（D-1）。
- 权限不足：普通成员在群里设订阅被拒且**不落库**；非 QQ 会话设订阅被明确告知只能在 QQ 侧设。
- 本入口零网络外呼（查询走快照与库），因此"响应慢"通常是读库而非取数。

## 测试与验收

离线：`tests/test_emergency_info_core.py`（含"只有审核门能写条目"等结构锁）、`tests/test_emergency_info_reachability.py`（装配/投递/注入三把可达性门）。
真机：`docs/acceptance-manual.md` §6.6.12 的 E1（报料入 PENDING 且不推送）、E2（`emergencyxxx`/`emergency1`/裸聊天含"紧急"一律不命中）、E3（帮助页仅管理员可见）、E5（待审列表与审核裁决）、E8（不设总闸则整链零反应）。
