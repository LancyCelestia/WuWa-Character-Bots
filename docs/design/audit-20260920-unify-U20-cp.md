# 统一性审计 · 席位 U20-CP：控制面/中央操作台统一（2026-09-20）
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [../snowluma-setup.md](../snowluma-setup.md)。

> 席位定位：控制面是「中央处理」在人这一侧的入口，必须与 Runtime 共享**同一份状态真身与同一套执行门**。
> 凡控制面持有影子副本、或有第二条执行路径，即为缺陷。
> 范围裁定：只查后端 Python；**不查** webui/ 前端、domains/render/**、output/card_render/**、theme_tokens.py、TTS/语音链路。
> 控制面里凡「只为前端页面服务的展示层」不看，只看服务端点、执行门、状态源、鉴权与统一性。
>
> 硬纪律：只读审计（除本日志）；不跑全量 pytest；不向 8742/8080/3001 发真请求；不读 .env 明文值（只报键名+坐标）；
> 每条发现七要素：严重度｜坐标｜锚点字符串｜根因｜证据｜改法 before→after｜验证命令。
> 行号会漂，每条必带锚点字符串。未查过的写「未覆盖清单」，不把没查的说成没问题。

## 状态台账（随做随更新）

- [x] 日志骨架落盘
- [ ] 必读件通读（AGENTS 控制面行/校正节/台账 #41 #42 + control-plane-core-status.md + U3/U4/U10/U7 四份兄弟日志）
- [ ] 控制面全树结构摸底（39 py 文件清单 + api/ 子包）
- [ ] D1 状态真身单一性
  - [ ] D1-1 配置面：config_service/config_store 与 pydantic Config/.env 关系、双写/后写覆盖路径、装配期快照
  - [ ] D1-2 功能门：ProductFeatureGate vs capability_registry 真相源；capability_id 字面量全集差集（穷尽清单）
  - [ ] D1-3 SQLite CAS/严格版本：并发写防护、绕过 CAS 裸 UPDATE 枚举
  - [ ] D1-4 账本/指标：控制面读的是谁（llm/ledger vs 控制面副本 vs runtime_event_log）
- [ ] D2 执行门与出站唯一性
  - [ ] D2-1 dispatcher 动作执行链的门；OutboundSideEffectExecutor 唯一性证据（send_queue/call_api 直调枚举）
  - [ ] D2-2 预览/确认/模拟 vs 真实发送的代码层分隔；「模拟触达真出站」证据搜证
  - [ ] D2-3 危险动作全表逐个判定（角色门+二次确认+审计+回滚）
  - [ ] D2-4 sandbox.py 隔离与审批门闭合性
- [ ] D3 鉴权与暴露面
  - [ ] D3-1 Bearer/双令牌回退实读 + 逐路由装饰器枚举免鉴权清单
  - [ ] D3-2 Host 白名单/DNS rebinding/绑定面 + /ui 壳零数据实证
  - [ ] D3-3 OpenAPI 与真实端点同源性、未实现端点 503 诚实性
  - [ ] D3-4 日志 SSE：游标/重连/敏感行/无界订阅
- [ ] D4 「中央」地位收口
  - [ ] D4-1 操作口并列清单与覆盖关系
  - [ ] D4-2 宣称能力 vs 实况差距表（enabled 到底影响什么）
  - [ ] D4-3 单一状态源收口清单（按解锁顺序）
- [ ] 未覆盖清单 + 返回主会话摘要

---

## 〇、必读件与背景口径（引用不重复）

| 来源 | 本席直接引用的既有结论 | 用途 |
|---|---|---|
| `docs/design/audit-20260920-unify-U3-outbound.md` §U3-01/02 | `ProductFeatureGate` 对未登记 `capability_id` **一律 fail-closed 拒绝**（锚点 `return FeatureAccess(False, "feature_unregistered")`，`domains/ops/features/feature_gate.py:57-59`）；已数出 4 条被吞 id：`bot.file`/`bot.group_welcome`/`bot.cookie_login`/`bot.cookie_expiry_notice` | 本席 D1-2 只把差集**穷尽**并复核 U3 四条，不重复论证语义 |
| 同上 §U3-16 | 域外存在第二套出站/队列栈两处（需显式定籍） | 本席 D2-1 判 `OutboundSideEffectExecutor` 唯一性时引用 |
| `audit-20260920-unify-U4-dispatch.md` §8 | 控制面 `dispatcher.py` 被正名为**交互出站门面**（非运维 API）；「有 `PermitLease` 幂等与准入复验，但无 `policy/gate` 群名单/安静时间/中央限流」，并入其 H-1（High）；`actions.py` 判为运维信任边界、Low/可豁免 | 本席 D2-1/D2-3 补控制面侧一手取证，定级独立给出 |
| `audit-20260920-unify-U7-command.md` §3.3（U7-F3, P2） | 角色判定三套并行：六级 `actor_roles` / 裸 `config.bot_admin_user_ids` / Telegram 名单 | 本席 D2-3 对照控制面 `_authorize` 的角色口径 |
| `audit-20260920-unify-U10-gate.md` §F-1（P1） | 未登记 id 的登记真身＝`domains/chat_reply/runtime/capability_registry.py:97 ROUTE_CAPABILITY_DECLARATIONS` / `:533 CONTROLLED_INTERNAL_CAPABILITIES`；登记工作树零改动 | 本席 D1-2 差集基准 |
| `docs/design/control-plane-core-status.md` §3/§4 | 「Config preview/set/reset 仍是上轮原型实现，未进入 ConfigControlService」——**本席实测该句已过期**（见 U20-07 归因）；§4 P0 四条（Pipeline 未消费 FeatureState、独立入口未同进程注入、JSON 仅线程锁、`settings._save` 通知在落盘前） | 本席逐条判定「已修/半修/仍在」 |
| 根 `AGENTS.md` 「控制面最新接手校正」 | 「尚未接生产 Runtime 执行门，也未迁移 SQLite」＋「不能把 features API 的 enabled 值变化宣称为生产插件已经停用」 | 本席 D4-2 实证 `enabled` 到底影响什么 |

**兄弟日志未采信之处（本席独立取证后推翻）**：`control-plane-core-status.md:93` 宣称 Config 面「仍是上轮原型实现，未进入 ConfigControlService，没有 CAS」——实况是 `ConfigControlService` 已成文并接入（`control_plane/config_service.py:31`），CAS 已在 SQL 层实现（`config_store.py:215-239`），且 `/bot runtime set` 也改走同一服务（`domains/ops/admin/runtime_admin.py:132-138`）。该文档第 6 行自己也标注「下文旧未接线不能作为当前结论」，故不作为本席判据，只作背景。

## 一、控制面结构摸底

**基数实跑**：`find plugins/bot_unified_runtime/control_plane -name "*.py" | wc -l` = **39**，总 `wc -l` = **10166 行**。与 AGENTS「约 39 个 .py」对得上（非漂移项）。

装配层级（一手取证）：

| 层 | 文件 | 真身/垫片判定 |
|---|---|---|
| 开关与设置 | `control_plane/__init__.py`（165 行，非垫片） | `control_plane_settings()` 是唯一解析源：`Config 字段 → os.environ → 默认关`（`__init__.py:84-144`）；`create_control_plane_app`/`serve` 经 PEP 562 `__getattr__` 惰性导出（`__init__.py:156-165`），关闭态零导入 fastapi |
| 进程生命周期 | `control_plane/lifecycle.py`（217 行） | 内嵌 uvicorn `EmbeddedServer`，`capture_signals`/`install_signal_handlers` 被架空（`lifecycle.py:28-39`）→ **信号归 Bot 进程所有**，控制面炸不到主循环 |
| app 工厂 | `control_plane/_app.py`（852 行） | 全部服务的装配点、三套鉴权依赖、Host 守卫、审计中间件 |
| 状态真身 | `features.py`(440)/`sqlite_features.py`(269)/`config_store.py`(283)/`config_service.py`(179)/`services.py`(148) | 见 §二 |
| 执行面 | `dispatcher.py`(254)/`actions.py`(336)/`workspaces.py`(371)/`sandbox.py`(99)/`factory.py`(106) | 见 §三 |
| HTTP 面 | `api/` 14 文件（`v1.py` 253、`platform.py` 473、`events.py` 249、`webui.py` 116、`webui_ext.py` 93、`actions.py` 61、`workspaces.py` 90、`health.py` 127、`llm.py` 165、`divination.py` 262、`protocol.py` 157、`__init__.py` 49） | 见 §四 |
| 观测面 | `metrics.py`(442)/`events.py`(472)/`log_collectors.py`(155)/`resources.py`(110)/`audit.py`(214) | 见 §二-4 与 §四-4 |
| WebUI 数据面（服务端点，在范围内） | `webui_stats.py`(371)/`webui_knowledge.py`(521)/`webui_plugins.py`(404)/`webui_memory_graph.py`(511) | 只判鉴权与状态源，不判页面 |
| 其他 | `llm_admin.py`(553)/`platform.py`(348)/`file_access.py`(99) | `llm_admin` 属 U12 计价域，本席只查「控制面读的是谁」 |

**与 Runtime 的共享关系（一手取证，这是本席的地基事实）**：控制面**同进程挂载**，不是独立服务：

- `plugins/bot_unified_runtime/__init__.py:3846-3860`，锚点 `register_control_plane_lifecycle(get_driver(), config, make_control_plane_app)`；`make_control_plane_app()` 内 `create_control_plane_app(config, feature_service=feature_service, settings_store=runtime_settings, runtime_attached=True, send_queue=send_queue, runtime_state_probe=...)`（锚点 `runtime_attached=True,`）。
- 即：`feature_service`、`settings_store`、`send_queue` **三件都是 Bot 装配期的同一对象引用**——`core-status.md:16`「控制面独立启动，不应假设与 Bot 共享内存」与 §4 P0「`bot.py` 未见自动挂载」两条**已过期**，实况是共享内存。
- 但 `serve()` 独立入口仍并存：`_app.py:811-852`，锚点 `app = create_control_plane_app(config)`——**不带任何注入参数**，故独立进程形态下 `settings_store=None`→config 面降级、`send_queue=None`→queue.* 动作全 degraded、`runtime_state_probe=None`→`napcat.status` 恒 `connected: False`。这是 D4-1 的「第 N 个操作口」事实之一。

**总开关**：`config.py:56` 锚点 `bot_control_plane_enabled: bool = False` → 缺省关。生产 `.env` 是否开启本席不读明文（禁读），如实记为未覆盖项 U20-N4。

## 二、D1 状态真身单一性

（待填）

## 三、D2 执行门与出站唯一性

（待填）

## 四、D3 鉴权与暴露面

（待填）

## 五、D4 「中央」地位收口

（待填）

## 六、未覆盖清单

（待填）
