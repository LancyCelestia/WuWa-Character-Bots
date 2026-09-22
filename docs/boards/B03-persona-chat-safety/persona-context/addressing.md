# 人格上下文与称谓身份 · 称谓与主角边界

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.persona-context · 称谓与主角边界

- 层级：一级 B03 → 二级 persona-context → 三级 `addressing`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/character`、`personas/shorekeeper`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

决定「这一轮她怎么称呼对方、把谁当主角」。输入是会话形态（私聊/群聊/其它）、
展示名、角色列表、性别自述、用户自设称谓偏好；输出是一段**指令文本**
（`AddressingContext.instruction`）连同结构化事实，由分区装配注入【当前称谓与主角边界】。
口径：私聊可称「漂泊者」；群聊对方是群友，禁止称漂泊者、不把群成员设为主角；
超管 master 是唯一例外（配置事实，不是文案推断）；性别 unknown 时一律不猜。

## 怎么调用

- 真身：`domains/chat_reply/character/addressing.py:build_addressing_context`
  （关键词参数：`session_type`、`sender_display_name`、`sender_roles`、
  `gender_identity`、`addressing_preference`）→ `AddressingContext`
  （契约定义在 `domains/core/contracts/character.py`：`scope`、`preferred_name`、
  `gender_identity`、`gender_confidence`、`can_use_wanderer_title`、`is_master`、
  `instruction`）。
- 偏好存储：同文件 `AddressingPreferenceStore`（SQLite），装配口
  `character/providers.py:build_addressing_preference_store`；键
    `bot_addressing_preferences_db_path`（库路径的缺省值以 `config.py` 该字段为准）。
- 入口命令：`/bot identity set-name <称呼>`、`set-gender <male|female|nonbinary|custom|unknown>`、
  `unset-name`、`unset-gender`，实现
  `capabilities/echo.py:build_identity_preference_result`（能力 id `bot.identity`），
  **只写本人偏好、绕开管理员会话身份门**（自己的称谓自己定）。
- 创造者事实同源：`creator_aliases()` / `creator_context_note()` 是双名（澜汐/霞月
  同一人）的唯一来源，人格文件里**不写**这两个名字，注入文本【创造者】分区读这里；
  文案红线门对本文件内建豁免，别处出现即红。
- 会话级称呼（管理员设的）见 [会话身份与自助偏好](session-identity.md)：它是**另一行**
  注入文本（`ContextBundle.session_identity_note`，由 providers 现取现拼），不参与
  `build_addressing_context` 的名字选择；名字优先级只有一处口径——
  本人自设偏好 > 展示名 > 「你」，两条线不同源、不互相覆盖。

## 开关与参数

- 超管名单：`bot_super_admin_user_ids`（决定 `is_master` 的那条形是配置事实，
  不接受从消息文本推断）。管理名册注入用 `bot_admin_profiles`。
- 存储路径：`bot_addressing_preferences_db_path`（路径类键，经 `runtime_paths` 重映射到
  Runtime，改路径要重启）。
- 偏好写入约束：称呼必填非空且有长度上限；性别只收上面五个值（大小写不敏感），
  非法值**不记录**并回列可接受值；`unset-*` 幂等（本就没有会明说）。
- 群聊保留字：非 master 在群里把偏好设成「漂泊者」会被忽略并回退展示名——
  这是防止「优先称呼漂泊者 + 禁止称漂泊者」自斥指令击穿主角边界的兜底。
- 没有总开关：称谓指令是人格链的固定分区，关掉它等于让模型自由猜性别，不允许。

## 失败时看到什么

- 存储读写异常：偏好按「读不到 = unknown/无偏好」处理，指令退到最保守分支
  （中性称谓「你」，不猜性别、不称漂泊者），消息链不失败。
- 未知 `session_type`：一律归 `other`，得到「身份未知，用中性称谓」的指令，
  不会误按私聊放开「漂泊者」。
- 用户自设了非法性别值：命令回用法与可接受值清单，不写库。
- 注入侧异常（【创造者】分区缺 note）：该分区不渲染，bot 会答不出双名——
  这是 `test_creator_dualname.py` 的死锁目标，宁可红也不静默。

## 测试与验收

`tests/test_addressing_context.py`（四态称谓 + 群聊保留字回退 + 性别不推断）、
`tests/test_creator_dualname.py`（双名单一事实源，monkeypatch 常量必须改变输出）、
`tests/test_randpic_identity.py` 与 `tests/test_persona_prompt_and_memory.py`
（身份与称谓在提示词里的落位）。
真机：`docs/acceptance-manual.md` §6.6.1 抽样——群里 @ 她说「以后叫我 X」，
核对只有**该用户在该群**的称呼变了，别的群友称呼不受影响。
