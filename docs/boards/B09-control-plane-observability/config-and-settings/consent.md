# 配置与运行时设置 · 书面同意

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.config-and-settings · 书面同意

- 层级：一级 B09 → 二级 config-and-settings → 三级 `consent`
- 路由席位：`CONSENT`（matcher `consent`，command=True）
- 判定优先级：41
- 能力 id：`bot.consent`
- 实现落点：`plugins/bot_unified_runtime/config.py`、`plugins/bot_unified_runtime/domains/core/config`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py`、`docs/config-catalog-full.md`
- 帮助主题：书面同意
<!-- BOARD-AUTO:END -->

## 这个入口做什么

危险参数改动的**批准腿**：改设置咽喉（`settings_gate.SettingsWriteGate`）把 R1/R2
档的改动拦下时会先签一张同意卡（工单），本入口让管理员/超管在会话里一句话把卡
**列出来、看全文、批掉或驳回**。批准≠落地：凭证一次有效，批下后要由原发起人用
同一参数再说一次才执行。生效条件：安全执行引擎总闸开且门装载成功。

## 怎么调用

- **触发**：整句必须以触发词开头（简中/繁中/英文/拼音词表，唯一真身
  `domains/ops/capabilities/consent_admin.py::DEFAULT_TRIGGER_WORDS`，帮助词表由
  `tests/test_trigger_bidirectional_gate.py` 按词级双向 diff 执法），且后面只能跟
  本子命令形：`待批` / `看 <工单号>` / `批 <工单号> <短码>` / `驳 <工单号> <短码>`。
  判据是**锚定的**——「同意卡 顺便帮我改下密码」不算命令；判定与解析同一处
  （`parse_consent_command`/`is_consent_command`），零第二套词表。
- **路由与承载**：`base_router.py` 的 `RouteRule(RouteKind.CONSENT, "bot.consent",
  priority 41)`；根 `__init__.py` 的 `consent_matcher`（`on_message`，block=True）
  经中央缝 `_run_capability_through_pipeline` 执行；`gate_provider` 是**每回合现读**
  的 `lambda: runtime_settings.safety_gate`——门惰性建，构造期快照会把命令面永远
  钉成「门没装载」（本仓反复踩过的旧坑，装配注释点名）。
- **入口函数**：`build_consent_admin_capability(gate_provider)` 返回 `(message,
  decision) -> CapabilityResult`。本文件只做三件事：认触发、把**角色门**
  （admin/super_admin 才给看，只吃 `decision.actor_roles`，与 host_state 同口径）、
  回人话。**谁能批一张具体的卡不在这里判**——唯一真身是
  `domains/core/safety_exec/consent.py::ConsentLedger.redeem_from_message` 的阶梯
  （可信级/私聊门/原会话门/防自批/一次性/TTL），本件一条都不复制。
- **账面**：同意账与变更审计表名以 `consent.py` 常量（`CONSENT_TABLE`/`CHANGE_TABLE`）
  为准；后端选择逻辑在 `build_store`——给了控制面配置库就复用同一个库文件（SQL 为
  准），否则退到 JSON 账本，一个都不给直接报错（不留「半本 SQL 半本 JSON」）。
  不判档、不签卡、不记账、不新建第二条入站通路、不接受「模型替人批」
  （批准只认真 `IncomingMessage`）。

## 开关与参数

- `bot_safetyexec_enabled`（缺省 True，🟡需重启）：执法门总闸；唯一读点
  `ConsentPolicy.from_config` 装配期快照，在 `RESTART_REQUIRED_KEYS` 里——护栏
  不可被一条命令热关。
- `bot_safetyexec_auto_r0_enabled`：R0 无人值守自动改腿开关，同一读点。
- `bot_safetyexec_consent_ttl_minutes`：工单有效期，缺省与合法区间以
  `consent.py` 的 `DEFAULT_CONSENT_TTL_MINUTES` 与钳位逻辑为准（本文不抄数）。
- 风险档真值表住 `domains/core/safety_exec/config_risk.py`：未登记键缺省 **R2**
  （fail-closed）；R1 会话内管理员确认、R2 超管私聊书面同意、R3 永不自动。
  逐键env名与热更性以 `docs/config-catalog-full.md` 为准。

## 失败时看到什么

- **门没装载**（总闸关或装载失败）：回「安全执行引擎现在没装载……没有卡可批」；
  装载失败记 `_safety_gate_failed`，此后 R1/R2/R3 一律拒（fail-closed）。
- **非管理员**：管理员门轮换话术，且**不透露任何一张卡的内容**。
- **阶梯拒绝**：`Refusal.kind`（枚举清单以 `consent.py` 真身为准）翻成人话，行尾
  括号点名「哪枚键｜风险档｜拒绝类别」；返回形状读不懂时**什么都不当作批准记**。
- **批下来了**：回显工单全文 + 明写下一步「原发起人同一参数再说一次；凭证一次
  有效，不重试到点作废」（卡面与回显同一枚常量，禁两处各抄）。
- 出站回显统一过 `redact_local_secrets` 中央咽喉；敏感参数值账上两边都不留明文
  （只留指纹对账），页面上明写而不是回空串。

## 测试与验收

`tests/test_consent_command_surface.py`（批准闭环四态端到端：无票拒→超管私聊批→
重试落盘→过期拒，锚定判据与防自批）、`tests/test_safety_exec_consent.py`（阶梯
六面判据与分级真值表）、`tests/test_safety_exec_throat_wire.py`（咽喉接线活性锁：
绕过咽喉即红 AST + 真装配口第一次 R2 写就撞门）、
`tests/test_control_plane_consent_throat.py`（控制面/WebUI 写入口同过一枚门）、
`tests/test_trigger_bidirectional_gate.py`。引擎规格见
`docs/design/safety-execution-engine-spec.md`，逐命令口径见
`docs/command-catalog.md`【书面同意】节。真机（重启后）：发起一次 R2 档参数改动
确认签出工单；超管私聊「同意卡 待批 → 看 → 批」走完阶梯，确认批后原发起人重发
才落地、二次核销被拒；非管理员发同句确认连列表都拿不到。
