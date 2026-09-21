# v21r5 B 席工作日志 — 群聊亲密模式双开关 + 1h TTL + 四名单

## 任务简报摘要（开场落盘，2026-09-19）

- **席位**：v21r5 波次 B 席（重派；前一实例零改动落盘，本实例从零开始）。
- **用户裁定书（照做，不重定义）**：
  1. 开关一（个人级）：群聊里对特定已开启亲密模式的人表示亲密（群成员自己对自己开启）。
  2. 开关二（全群级）：对整个群全员开启（管理员开）。
  3. 亲密模式默认时长 1 小时，1 小时后自动退出（两个开关同一 TTL）。
  4. 新增白名单/黑名单四场景：白名单私聊 / 黑名单私聊 / 白名单群聊 / 黑名单群聊。
- **真身路径（已核准）**：domains/chat_reply/runtime/content_route.py（410 行）；domains/chat_reply/capabilities/chat.py（3595 行，只动亲密缝）；config.py 包根真身。旧路径 runtime/content_route.py 与 capabilities/chat.py 是垫片不改。
- **禁区**：domains/chat_reply/llm_engine/**（A 席）、domains/chat_reply/security/**（C 席，explicit_allowed_for_session 只读）、domains/chat_reply/character/、personas/**。禁 git 写、禁子代理、禁真实 LLM、不 commit。
- **设计**：分层合成——最终许可 = 会话级许可（explicit_allowed_for_session，不改）∧ 用户级状态（新做）∧ 名单门（新做）。
  - 状态机扩展：群聊两级状态（群级/个人级 (群号,用户号)），各记 activated_at 惰性过期；指令分流（成员→只影响自己，管理员→全群）；私聊手动开关 TTL 默认 60 分钟。
  - TTL 新键 bot_content_route_intimate_ttl_minutes（默认 60）；既有 120 分钟硬上限键保留为上限。
  - 四名单新键：bot_content_route_private_whitelist（空=私聊放开）/ bot_content_route_private_blacklist（最高优先）；群聊沿用既有群白/黑名单；黑名单永远赢（Master Love 压不过黑名单）。
  - 优先级合成（群消息 U@G）：群黑名单→拒 → 群白名单外（或空）→拒 → 群级 ON→全员 → (G,U) ON→U → Master Love→亲密 → 普通。个人级受 bot_content_route_group_per_user_enabled（默认 True）控制。
  - chat.py 注入缝逐消息按发送者判定，注入与路由双门同源（同一合成函数）。
  - 登记四新键进 config.py / docs/config-catalog-full.md / .env.example（写明不对称语义）。
  - 测试：新建 tests/test_content_route_v3.py + 更新 test_content_route.py 中 120→60 语义断言；全离线实跑。
- **测试纪律**：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 venv python -m pytest --basetemp="$TEMP/seatB2-tmp" -p no:cacheprovider -q

## 进度流水

- [开局] 日志已落盘。开始读真身码：content_route.py（410 行全文）+ tests/test_content_route.py + config.py 相关键。
- [核实] 读码完成，关键事实（verified）：
  - `explicit_allowed_for_session` 真身在 **domains/chat_reply/runtime/content_route.py:369（本席文件）**，不在简报所说的 security/content_safety.py——简报此处有误，按"最小偏差修正"原则在本席文件内扩展（security/ 零接触）。
  - 既有钉死态 `updated` 每轮滑动 → 既有 max_ttl=120 实为"空闲超时"语义；新 1h TTL 需独立 `activated_at`（激活时刻起算、不随活动滑动），否则活跃会话永不过期，违背裁定 3。
  - 群 session_id 格式=`group:{群号}`（__init__.py:1825）；IncomingMessage 有 sender_id/group_id/sender_roles 字段（domains/core/contracts/runtime.py:121+167）。
  - `explicit_allowed_for_session` 现有调用点 3 处：chat.py:2043（将传 sender_id）、root __init__.py:7367 被动好感感知（不改，缺省参数=既有行为零破坏）、tests/test_v21r2_content_probe.py（群语义断言不动）。
  - test_rp_style_directives.py 有完整 build_chat_result 离线 harness（_CapturingProvider），可复用于群聊分流/注入集成测试。
  - config-catalog 登记点=docs/config-catalog-full.md:796 单行表格（content_route 全族键并列）；.env.example 登记点=502-512 块后。
- [设计定稿]（含裁定记录，全部离线可测）：
  1. **个人级状态=成员派生键**：群消息的内容路由键改为 `member_session_key(群键, sender_id)`（形如 `group:123||u:456`，分隔符含双竖线+u: 前缀防撞）。L1/L2 滞回、个人钉死、Master Love 钉全部落在成员键上=天然 (群,用户) 隔离；群级钉=管理员 `apply_manual(群键)`（既有机制=既有语义保留）。
  2. **引擎 route_verdict/pinned_mode 成员键感知**：成员键判定时先查群键钉——群钉 intimate→全员 intimate；群钉 normal**不压制**成员个人钉/ML（裁定理由：开关一的存在意义即个人自主，管理员关全群只关"全群默认档"，个人同意优先；已记录为设计裁定）；随后走成员键自身滞回。
  3. **TTL**：`apply_manual` 钉 intimate 时记 `activated_at`；`_state` 读取时惰性过期（>ttl 即解除，活动不续期，重新开启重置）。normal 钉与分数态不吃此 TTL（维持既有语义）；max_ttl=120 保留为全状态硬上限。群级钉与管理员钉同走 apply_manual→同一 TTL（裁定 3"两个开关同一 TTL"）。
  4. **指令分流**（chat.py）：群聊管理员→群键（全群）；普通成员（含 master-love 名单非管理员）→本人成员键（开关一）；per_user_enabled=False 且非管理员→拒绝（落入普通聊天）。私聊/控制台不变。
  5. **四名单**：群两面=既有两键不动（群白名单空=关闭）；私聊两面=新键，**在 explicit_allowed_for_session 内实现**（私聊白名单空=放开、非空=仅名单内；黑名单最高优先；console 不参与私聊名单门——运营者本地面，维持既有常开，记录为裁定）。黑名单永远赢：ML/钉死/个人开关全部在 eligible=False 面前失效（master_love_here 计算前置条件即 eligible）。
  6. **注入与路由双门同源**：chat.py 注入缝与 router cb 均消费 `engine.route_verdict(route_key)`；新增 `resolve_intimate_context()` 合成函数（键构造+eligible+mode 单点），chat.py 注入缝经它读，路由 cb 经同键同函数（build_router_cb→route_verdict）。
  7. **诚实边界**：名单门在会话准入门层（chat.py eligible + explicit_allowed_for_session），引擎 route_verdict 本身不读名单配置——router cb 只接收 chat.py 传入的键，不可达绕过；被动好感感知调用点（root __init__.py）不传 sender_id=维持既有行为（该文件非本席所有权）。
- [实现完成] 全部代码与登记落盘，未 commit（共享工作树）。
- [验证完成] 24 个相关测试文件批跑 298 passed（详见下文实跑输出）；ruff 4 文件 All checks passed；mypy（项目口径 --explicit-package-bases）3 源文件 Success no issues；config 实例化冒烟通过（str→list 校验器 + 缺省值正确）。
- [树卫生] 会话内工具命令曾在根目录生成 .mypy_cache/.pytest_cache/.ruff_cache，已确认后清除（`cmd //c rmdir /s /q`），当前三目录不存在；全程 PYTHONDONTWRITEBYTECODE=1 + -p no:cacheprovider + basetemp=$TEMP，源码树无 __pycache__/*.pyc/data/ 残留。

## 改动文件清单（路径 + 行号区间）

### 1. plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py（真身；410→614 行；未跟踪新树文件，随 09-18 二十域重组）
- 模块 docstring：新增 v21r5 扩展说明（第 5-7 点，双开关/两级状态/TTL/四名单）。
- L171-190：`_MEMBER_SCOPE_SEP = "||u:"` + `member_session_key()` + `split_member_session_key()`（成员派生键构造/拆分，含空段防误判）。
- L204：`_SessionState.activated_at`（intimate 钉激活时刻，TTL 起算点，不随活动滑动）。
- L249-283：`_state()` 签名增 `intimate_ttl_minutes`；intimate 钉按 activated_at 惰性过期（>TTL 解除、score/last_mode 复位、activated_at 清零）；max_ttl 硬上限保留并在重置时清 activated_at。
- L336-346：`_intimate_head()` 静态方法（从 route_verdict 提取的 INTIMATE 候选头推导，逻辑逐字节不变）。
- L348-437：`route_verdict()` 成员键感知——先查群键钉（群 intimate→全员 intimate；群 normal 不压制成员个人档），再走成员键自身滞回。
- L439-470：`pinned_mode()` 成员键感知（同上语义）。
- L472-499：`apply_manual()` 钉 intimate 时记 activated_at=now；normal/解除清零（重新开启即重置计时）。
- L501-551：`explicit_allowed_for_session()` 增可选 `sender_id: str = ""` 参数——私聊黑名单最高优先、私聊白名单空=放开/非空=仅名单内；缺省 sender_id 行为与旧版逐字节一致；console 不参与私聊名单门；群分支零改动。
- L553-600（区间）：`resolve_intimate_context()` 新增合成函数（eligible+route_key+mode 单点；fail-open 安全侧收口）。

### 2. plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py（真身；3595→3666 行；只动亲密缝）
- L80-90：content_route 导入块增 `resolve_intimate_context`（ruff fix 后 `member_session_key` 未直接使用已移除——键构造单点在 resolve）。
- L2017-2041：新增 `_manual_command_scope_key()` 分流纯函数（管理员→群键/成员→成员键/per_user 关且非管理员→None/私聊→本人键）。
- L2064-2091：准入门传 `sender_id`（私聊名单门生效）；首个 `resolve_intimate_context` 调用取 route_key；`_content_route_per_user_enabled` 读取。
- L2095-2100：master_love_here 改用 `_sender_id_text`（语义不变）。
- L2107-2166：手动命令块重写——分流经 `_manual_scope_key`；audit_tags 增 `scope:group|scope:user|scope:self`；ML 自动钉死改钉成员键（群聊不泄漏全群）。
- L2207-2227：`observe_turn` 改用 route_key（L1/L2 群内按成员隔离，跨成员不互相污染——附带收口：旧版群共享键一名成员强词会整群切 grok）。
- L2225-2232：ML 注入门 `pinned_mode(route_key)`。
- L2234-2256：`_rp_intimate_now` 改经 `resolve_intimate_context` 二次读取（信号记账后），与路由 cb 同键同函数=双门同源。
- L2318：router `session_id=content_route_route_key`。
- L2359：`_apply_content_route_reply(session_key=content_route_route_key)`。

### 3. plugins/bot_unified_runtime/config.py（包根真身）
- L709-726：四新键+裁定注释（私聊两面名单语义不对称说明、TTL 说明、per_user 总闸说明）。
- L1204-1205：`_parse_id_list` before-validators 登记两个 list 键。

### 4. docs/config-catalog-full.md
- L796：content_route 行扩 4 键（含默认值列与 v21r5 描述段：双开关/两级状态/TTL 语义/私聊名单不对称/双门同源）——doc_sync 门禁解析兼容（键名在反引号内、注释在外）。

### 5. .env.example
- BOT_CONTENT_ROUTE_GROUP_BLACKLIST 之后新增 8 行：4 键 + 不对称语义/双开关/TTL 注释。

### 6. tests/test_content_route_v3.py（新建，698 行，28 用例）
覆盖：成员键往返、TTL 默认 60m 过期、活跃不续期、重开重置、TTL 覆盖、max_ttl 交叠、normal 钉不吃 TTL、群钉同 TTL、群钉覆盖全员、成员钉自隔离（第三人/群键不受影响）、群 OFF 不压制个人档、L1/L2 成员隔离、指令分流纯函数 5 态、指令词面零改动、私聊白名单空=放开/非空=名单内/None 容错、私聊黑名单永远赢、console 不参与名单门、群名单不变+黑名单群关个人钉、ML 压不过黑名单、resolve route_key 三态（member/group/private）、resolve mode 反映成员钉、resolve fail-open、群聊集成 4 例（成员分流/管理员全群/per_user 关拒绝/黑名单群关闭）+ 私聊黑名单端到端 2 例。

## 设计偏差记录（简报错漏 → 最小偏差修正）

1. **`explicit_allowed_for_session` 真身位置**：简报称在 `domains/chat_reply/security/content_safety.py`（C 席文件，只读不改）；实核真身在 `domains/chat_reply/runtime/content_route.py:369`（本席文件）。私聊名单门按最小偏差在该函数内实现（增可选 `sender_id` 参数，缺省=旧行为逐字节一致），security/ 目录零接触。若放合成函数里做，则黑名单私聊用户仍会拿到 explicit_allowed=True 的 safety assess（露骨面漏门），违背"黑名单永远赢"。
2. **TTL 计时基准**：既有钉死态 `updated` 每轮滑动，若直接沿用会变成"活跃永不过期"。新增独立 `activated_at`（激活时刻、不滑动）落实"1 小时后自动退出"；"重新开启即重置"由 apply_manual 重写 activated_at 实现。
3. **个人级状态载体**：不新建平行存储，个人级=成员派生键 `群键||u:用户号` 上的既有状态机（滞回+钉+TTL 全继承）；群级=管理员既有群键钉（"既有语义保留"零改动）。
4. **裁定补充（简报未覆盖的边界）**：①群级「亲密模式 关」（normal 钉）不压制成员个人档与 Master Love——开关一存在意义即个人自主，管理员关全群只改全群默认档；②ML 名单非管理员在群里的手动开关=只影响本人（成员键），不再像旧版那样可拨全群键；per_user=False 且非管理员（含 ML）→指令不受理；③console 不参与私聊名单门（运营者本地面维持常开）；④L1/L2 分数在群内改记成员键（旧行为=整群共享分数，一名成员强词整群切 grok；新行为=只切本人）——这是行为收窄，属"群内非亲密成员不受影响"裁定的必然推论。
5. **tests/test_content_route.py 无需改动**：逐条核对后确认该文件不存在"120→60"语义断言（`test_max_ttl_resets_pin` 显式设 max_ttl=1.0 测硬上限，语义不变仍通过；无任何用例断言手动钉存活 >60 分钟），故未做无意义改动，新语义全部落在 v3 新文件。

## 配置键全表（本席新增 4 键）

| 键 | 类型/默认 | 语义 |
|---|---|---|
| `bot_content_route_private_whitelist` | list[str] / `[]` | 私聊白名单。**空=私聊亲密面默认放开**（沿用既有私聊放开裁定）；非空=仅名单内 QQ。与群白名单"空=关闭"刻意不对称 |
| `bot_content_route_private_blacklist` | list[str] / `[]` | 私聊黑名单，最高优先——命中即关，Master Love/钉死/白名单全部压不过 |
| `bot_content_route_intimate_ttl_minutes` | int / `60` | 亲密模式自动退出时长（分钟），群级/个人级两个开关同一 TTL；按激活时刻起算、活跃不续期、重新开启即重置；`bot_content_route_max_ttl_minutes`(120) 保留为全状态硬上限（小者先到） |
| `bot_content_route_group_per_user_enabled` | bool / `True` | 个人级开关总闸：False=群成员「亲密模式 开/关」不受理（管理员全群开关不受影响） |

登记位置：config.py（字段+id-list 校验器）、docs/config-catalog-full.md L796、.env.example。既有键零改动：group_whitelist/group_blacklist（群两面沿用）、max_ttl_minutes（硬上限）、master_love 两键。控制面 llm_admin 的 LLM_CONFIG_PREFIXES 已含 `bot_content_route_` 前缀，4 新键自动进控制面配置面。

## 全部测试实跑输出（原文）

命令（全部同口径）：
```
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe -m pytest <files> --basetemp="$TEMP/seatB2-tmp" -p no:cacheprovider -q
```

1. 最终证据批跑（24 个相关测试文件：v3 新件 + content_route 族 + doc_sync 门禁 + 路由/决策 + chat 链 7 件 + config/safety/router/ledger 8 件）：
```
........................................................................ [ 96%]
..........                                                               [100%]
298 passed in 16.20s
```
2. v3 新文件单跑（修 3 处测试自身问题后）：
```
............................                                             [100%]
28 passed in 1.56s
```
3. 静态门：
```
ruff（4 改动文件）：All checks passed!
mypy --explicit-package-bases --ignore-missing-imports（3 改动源文件）：
Success: no issues found in 3 source files
```
4. config 冒烟（实跑）：
```
private_wl: ['123', '456']   # str→list 校验器生效
private_bl: ['789']
ttl: 60    per_user: True    group_wl default: []
defaults: [] [] 60 True
```
5. 开发期中间轮（修测前）：v3 首轮 25 passed/3 failed——3 失败均为测试自身缺陷（TTL 用例时钟推进跨过断言点/resolve 用例群白名单空/_group_cfg 未接 kwargs），实现零改动修复；共享引擎跨用例钉死态泄漏改用独立群号隔离。

## 遗留问题（登记，不阻塞本席交付）

1. **离线 passed ≠ 生产生效**：全部改动未部署、未 commit；真机生效需用户重启 bot（铁律：改码必须重启）。重启后建议真机验证：白名单群里成员 A 拨开、成员 B 不受影响、管理员拨开全群生效、61 分钟后自动回落、黑名单群/私聊双向验证。
2. **被动好感感知调用面未传 sender_id**（root __init__.py:7367，非本席文件所有权）：黑名单私聊用户的好感行为分类仍按 explicit_allowed=True 口径评估。该调用只影响行为分类信号，不构成露骨内容放行门（chat 主链准入门已关）。如需对齐，由后续席在 root __init__ 传 `_sender_id_text` 同款参数即可（函数已向后兼容）。
3. **control_plane/llm_admin.py:442 docstring 引用的行号**（content_route.py:288-296）因本席扩码漂移——纯注释，功能无影响（该处自建 head 推导不调用本席代码）。
4. **群聊个人级钉的持久性**：两级状态仍为进程内存（LRU 4096 封顶），重启即清——与既有会话态同纪律，未做 SQLite 化（简报未要求，B2 规格存储面另行立项）。
5. 全量 `dev.ps1 -Task test/lint/typecheck` 四门禁留待波次收尾合流统一实跑（多席在飞，单席全量会混入他席在飞面）；本席已覆盖全部直接/间接消费面 24 文件 298 passed。

**B-SEAT DONE**

