# 日程板与智能代答 · 可见性分级投影（代答腿）

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.schedule-board · 可见性分级投影（代答腿）

- 层级：一级 B07 → 二级 schedule-board → 三级 `visibility-projection`
- 实现落点：`plugins/bot_unified_runtime/domains/schedule/capabilities/schedule_board.py`、`plugins/bot_unified_runtime/domains/schedule/service/board_store.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

别人问「她在干嘛」时的代答腿。问句面：短句整句判据——剥掉 @ 与称呼前缀后命中「在干嘛/忙什么/去哪了/有何安排」一族问式（「她在干嘛 / 她在忙什么 / 主人在干嘛 / 主人去哪了 / 她出去了吗」是登记别名；「我/本人/自己」开头的为第一人称**自看面**，只答会话所有者本人的板子）。回答按提问者定档投影：隐私条目对任何非本人恒零呈现；公开条目普通提问者只见**类别词+时刻**，trusted/管理员档见**活动名+时刻**；健康/饮食/作息/心理等敏感类别即便标了公开，对非本人也只折叠成「有事情」。地点与其余字永不出口。生效条件：记录腿总闸与代答腿闸同开（代答缺省关——对外说话的一律单独开）。

## 怎么调用

- 判据入口：`is_status_question`（`schedule_board.py`）；路由腿 `is_reminder_command` 与能力分发腿引用同源的 `is_schedule_surface`，判据一处。
- 能力入口：`build_schedule_board_capability` → `_handle_status_question`：`resolve_status_owners` 定被问对象（问句点名优先，名字只来自 `bot_admin_profiles` 显示名；否则遍历超管，有公开进行中者胜）；`asker_tier` 给提问者定 owner / named / basic 档——owner 档只在**私聊且本人是超管**时成立（群聊里连她自己问也不把隐私条目摆上全群可见面，收紧方向唯一）；`active_entries` 从 plan 规则**现算**进行中条目（窗口跨昨日与今日，算入跨午夜长日程；只给了开始时刻的条目按 `_ACTIVE_WINDOW_FALLBACK_MINUTES` 常量窗口算进行中）。
- 投影唯一函数 `_project_answer`：字段白名单只读 title / start_local / duration / public / 类别；地点（`loc:` 标签）与溯源（`src:` 标签）不在 `BoardItem` 上，**结构上不可达**，不是「忘了外显」而是没有取数路径。复句出站前统一过 `redact_local_secrets`；不可答时从 `_FALLBACK_LINES` 按 request_id 哈希选一句。
- 全路径**零 LLM 调用**（测试结构锁执法），隐私不靠模型自觉。档位开关由她本人完成：`_handle_visibility`（「日程 公开 N / 日程 隐私 N」）改 plan payload 标签并同步重打已物化的未来 pending 实例（`board_store.retag_future_occurrences`）——两头都改才没有「改了开关、旧条目还按旧口径被读到」的半截状态。

## 开关与参数

- `bot_schedule_status_reply_enabled`（缺省 False，`.env` 名 `BOT_SCHEDULE_STATUS_REPLY_ENABLED`，已登记 `RESTART_REQUIRED_KEYS`，改 `.env` + 重启生效）：代答腿总闸，前提是记录腿 `bot_schedule_enabled` 已开。闸关时「她在干嘛」一类问句完全不进本路由，行为与从前一致。
- 角色与名单唯一来源：超管名单 `bot_super_admin_user_ids`、显示名 `bot_admin_profiles`；档位判定吃 `message.sender_roles`（角色真身 `domains/chat_reply/policy/roles.py`），本件零第二份名单。
- 类别词表与对外措辞以本件常量 `_CATEGORY_RULES`、`_SENSITIVE_CATEGORIES`、`CATEGORY_PHRASES` 为准（先命中先得，敏感类排最前=硬下限），本页不抄清单。

## 失败时看到什么

- 存储没就绪：不透露任何条目，与「不可答」同样回一句模糊话。
- 空板与全隐私板：回**逐字相同**的模糊句——条目缺席不是证据，不把「我不知道」写成「她没安排」。
- 多位超管同时可答：绝不猜人，回模糊句（要指名道姓问）。
- 公开条目还没到开始时刻：同样回模糊句——只答「正在进行」，不预告「她一会儿要忙」。
- named 档在群聊里会追加一句「她本人的完整日程，只在私聊里对她自己讲」；复句里出现的路径/键名形态由出站打码兜住。

## 测试与验收

`tests/test_schedule_board.py` 代答腿族：`test_answer_basic_tier_gets_category_not_title`、`test_answer_trusted_tier_gets_title_still_no_location`、`test_answer_admin_tier_equals_trusted_on_data`（三档逐级锁）、`test_answer_private_entry_invisible_to_everyone_but_owner`（隐私恒零）、`test_answer_sensitive_public_still_collapses_nature`（敏感类折叠）、`test_answer_empty_board_and_private_only_board_are_word_for_word_same`（逐字同句）、`test_answer_two_owners_active_is_not_guessed`（不猜人）、`test_answer_zero_llm_structurally`（零 LLM 结构锁）、`test_answer_body_redacts_local_paths`（出站打码）、`test_reply_switch_off_keeps_record_face`（闸联动）。补口 `tests/test_schedule_board_privacy_sched20.py`：第一人称只答本人板子、群聊自看不泄私（`test_first_person_group_does_not_leak_private`）、第三人称语义不回归。逐命令口径见 `docs/command-catalog.md`【日程】节；真机验收暂无本入口专属编号（挂账见 schedule-board README「现行缺陷」）。
