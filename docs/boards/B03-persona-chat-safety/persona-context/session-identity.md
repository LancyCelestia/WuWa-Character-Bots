# 人格上下文与称谓身份 · 会话身份与自助偏好

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.persona-context · 会话身份与自助偏好

- 层级：一级 B03 → 二级 persona-context → 三级 `session-identity`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/character`、`personas/shorekeeper`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

让管理员给**单个会话窗口**（某个群、某个私聊）定一个称呼和若干身份标签，
比如「在这个群里叫她岸宝、带花房值日标签」。它只调称呼与语气亲疏，
核心人格事实（她是守岸人、黑海岸代行者）由人格档案冻结，渲染出来的文本里
自带护栏声明，任何标签都不能推翻——防 OOC 是结构性的，不是靠提示词自觉。
另一个独立入口是**用户自助**的称谓/性别偏好（见
[称谓与主角边界](addressing.md)），两者不同源：会话身份=管理员设的对外表现，
自助偏好=本人声明「你怎么叫我」。

## 怎么调用

- 存储真身：`domains/chat_reply/character/session_identity.py`
  ——`build_session_identity_store(path)` 造 `SessionIdentityStore`
  （单连接 + 线程锁，WAL 先于 DDL），记录形态 `SessionIdentity`
  （`session_key`/`nickname`/`tags`/`set_by`/`updated_at`）。
  方法：`get(session_key)`、`set(...)`、`clear(session_key)`、
  `render_prompt_section(session_key)`、`close()`。
- 注入缝：`character/providers.py:build_character_context_provider(identity_describe=...)`
  收一个 `Callable[[str], str]`；装配胶水在根 `__init__.py:_build_identity_describe`，
  产出的文本落到 `ContextBundle.session_identity_note`，由分区装配作为独立一行渲染
  （空串=该行不出现）。会话键一律经 `domains/core/session_keys.py`，不准自己拼字符串。
- 命令面（`/bot identity ...`，帮助主题「身份」）：
  `show` 查看、`set <昵称>` 设称呼、`tag <标签1,标签2>` 设标签、`clear` 清除；
  自助面 `set-name` / `set-gender` / `unset-name` / `unset-gender` 由
  `capabilities/echo.py:build_identity_preference_result` 承接（能力 id `bot.identity`）。

## 开关与参数

- 路径：`bot_session_identity_db_path`（缺省 `data/session_identity.sqlite3`，
  经 `runtime_paths` 重映射进 Runtime，改值须重启）。
- 标签：逗号分隔（中英文逗号都收），**按序去重后最多保留 8 个**，空标签丢弃；
  称呼要求非空文本。
- 权限：会话身份=管理员操作（含本群有管理权限者），走 `/bot` 命令链的角色门；
  自助称谓偏好=**仅本人**，故意绕开管理员门（自己的称谓不该要别人批准）。
- 设置人会记进 `set_by`，`show` 会显示「谁在什么时候设的」，便于责任追溯。

## 失败时看到什么

- 存储读不到/异常：`identity_describe` 返回空串 → 该行不渲染，回复照常（fail-open
  到「少一行身份信息」，不会拿旧缓存冒充）。
- 没设过：`show` 明说「本会话没有设定」，不编一个默认称呼。
- 非法参数（空称呼、非法性别值、标签超长）：命令回用法与可接受值，不写库。
- 与防 OOC 护栏冲突的标签（例如「你是别的产品」类）：文本层护栏声明仍在，
  但**不要指望提示词兜住**——这类设定属人格篡改面，由反注入与内容安全侧拦（见
  [反注入包裹与指令剥离](anti-injection.md)）。

## 测试与验收

`tests/test_randpic_identity.py`（含 identity 命令面回归）、
`tests/test_persona_prompt_and_memory.py`（note 的渲染与缺省空行为）、
`tests/test_addressing_context.py`（自助偏好与保留字回退，对照不互相覆盖）。
真机：某群设 ` /bot identity set 岸宝` → 该群回复出现该称呼、别的群不变；
`clear` 后立刻回到默认；非管理员执行被拒并给「找管理员」句。
