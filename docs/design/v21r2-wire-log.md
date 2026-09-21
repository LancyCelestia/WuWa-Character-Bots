# v21r2 WIRE 席施工日志（V21-PERSONA-001 装配接线·人格注入面）

> 席位：WIRE。任务=把 V1 席 `character/persona_service.py`（production_wiring=not_wired）接到 chat 链人格注入。
> 纪律：禁 git 写、禁 dev.ps1、禁触 RWC4/RWOC/DSP/S11/S12/SBX、S10 capability_protocols 稳定、personas/ 只读（经 service 灌库属许可操作）。
> 固定解释器 `ChatBot_Runtime/venv/Scripts/python.exe`；`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；basetemp=`%TEMP%/v21r2-wire`。

## §1 波前取证（实读）

- **服务接口**（`domains/chat_reply/character/persona_service.py`，V1 席交付，19 passed）：
  - 生命周期：`draft(resource_id, content, *, actor, roles, expected_version)`（admin+）→ `publish(*, actor, roles, expected_version)`（super_admin，CAS BEGIN IMMEDIATE）→ `activate(resource_id, version, *, actor, roles)`（super_admin）→ `rollback`（super_admin）。
  - 唯一注入出口：`build_core_injection(resource_id) -> dict`（channel/source/resource_id/version/persona_revision/content_sha256/degraded/content）；内部 `load_active` 哈希复核，不符→quarantine 留证+告警+自动回退最近完好版本；全损→PersonaStoreUnavailable 拒注入。
  - 装配入口：`build_persona_service(db_path=None)`——缺省 `data/persona_versions.sqlite3` 经 scripts/runtime_paths 重映射（无独立配置键，memory_v21 先例）。
- **现行注入组装点**（RWC3 后真身 `domains/chat_reply/capabilities/chat.py`，垫片保旧路径）：
  - `build_chat_prompt_with_diagnostics` L1550：`raw_persona = persona.raw_text` 非空 → `_compose_persona_verbatim_prompt(raw_persona, reply_detail, dynamic_parts, context_budget)`；空 → 字段重组兜底。dynamic_parts（【实时感知】【当前心情】…【管理团队】）= 运行时上下文分区，与人格核心解耦。
  - `persona.raw_text` 的唯一来源 = `domains/chat_reply/character/providers.py` `FileCharacterContextProvider.build_context` L368 `persona_text = self._load_persona_text(persona_files)` → `_build_persona_profile(raw_text=persona_text)`。
- **装配面**：`build_character_context_provider(config)` 被 `__init__.py:4336`（DSP 禁触）/smoke/console_chat/prompt_preview/backend_unit/debug 六处调用——**开关在 provider 构建器内部消费 config**，六处调用点零改动自动生效，root `__init__.py` 零触碰。

## §2 接线设计（先成文后动手）

### 2.1 切换点裁决：providers.py 取文本处，非 chat.py 组装处

人格核心的交换在 `persona_text` 赋值处（providers.py 一处）完成，`persona.raw_text` 下游链路（chat.py verbatim 组装/字段重组/diagnostics/smoke/debug/preview）零改动自然吃版本库内容；运行时上下文分区（dynamic_parts）照旧拼接。理由：单一交换点（高内聚）、全部 prompt 构建消费方统一生效、chat.py 本体零 diff（RWC3 刚迁完热区文件，最小扰动）。

### 2.2 新模块 `domains/chat_reply/character/persona_injection.py`

- `get_shared_persona_service()`：进程级单例（锁+按 resolved db_path 缓存，`_ADDRESSING_STORES` 先例）；构建失败 warn 一行返回 None（fail-open 地基）。
- `ensure_persona_baseline(service, resource_id, content, *, actor, roles) -> str`：幂等灌入（纯生命周期语义，可抛异常由上层捕获）：
  1. `content.strip()` 为空 → 返回 `"skipped_empty"`（空人格不入库，_validate_content 语义一致）；
  2. 库内已有任一已发布版本 sha256 == sha256(content)：
     - state 存在 → `"exists"`（幂等跳过）；
     - state 缺失 → activate 该版本 → `"activated_existing"`（首用中途崩溃续跑）；
  3. 无同 sha 版本且 store 非空且 state 存在 → `"skipped_managed"`（超管手动生命周期在场，绝不抢指针）；
  4. 其余（空库 / 空库+state 缺失的崩溃续跑）→ `draft(actor, roles, expected_version=latest)` → `publish(expected_version=base_version)` → `activate` → `"seeded"`。
  -灌入身份：`actor="system:baseline-ingest"`、`roles=["super_admin"]`（服务权限门要求；装配席经 service 灌库=任务书许可操作，personas/ 文件零接触——灌入内容取自 provider 已加载的 persona_text，即 persona_files 现行内容的生产镜像）。
- `load_versioned_persona_core(service, resource_id, fallback_text) -> tuple[str, dict | None]`：`ensure` → `build_core_injection` → 成功返回 `(content, provenance_dict)`；**任何异常（PersonaStoreUnavailable/NotFound/Validation/sqlite/OSError）→ warn 一行 + 返回 `(fallback_text, None)`**——灌入失败/库空/损坏全走同一 fail-open 出口，绝不阻塞消息链。

### 2.3 providers.py 改动（最小面）

- `FileCharacterContextProvider.__init__` 新增 kwargs（全带默认值，既有 3 处测试直接构造零破坏）：`persona_versioned_injection: bool = False`、`persona_version_service: Any | None = None`（None=懒取共享单例）；实例字段 `_versioned_provenance`（上次溯源缓存，变更才 info 一行）、`_baseline_attempted: set[str]`（每 resource 只 ensure 一次/失败重试一次语义）。
- `build_context` L368 后追加：
  ```python
  if self.persona_versioned_injection:
      persona_text = self._versioned_persona_text(persona_text, persona_profile_id)
  ```
- `_versioned_persona_text`：服务解析（注入优先，None 时 `get_shared_persona_service()`，仍 None → fallback）→ `load_versioned_persona_core` → 有 provenance 则（version, sha, revision) 变更时 info 一行（version+sha256+revision+degraded 溯源可观测）→ 返回文本。degraded=True 时服务层已 error 告警+回退完好版本——**chat 侧不二次处理（任务书③），照常服务回退后内容**。
- `build_character_context_provider`：`persona_versioned_injection=bool(getattr(config, "bot_persona_versioned_injection", False))` 透传（getattr 缺省=False——旧测试 config stub 缺键不炸）。

### 2.4 配置键（三处同生）

- `config.py` persona 键块追加：`bot_persona_versioned_injection: bool = False`（默认 False 保守灰度——False=旧路径逐字节不变；True 才切版本库）。
- `docs/config-catalog-full.md` A26 增量区补录（test_config_catalog_covers_config_fields 门禁）。
- `.env.example` persona 段补 `BOT_PERSONA_VERSIONED_INJECTION=false` + 注释。
- 不进 path_fields（非路径键）；不做 runtime_settings 热更（装配期快照=台账 #3 既有取舍族）。

### 2.5 损坏隔离与回退语义（任务书③④落点）

| 场景 | 行为 | 告警面 |
|---|---|---|
| 默认 False | 走 `_load_persona_text` 原路径，逐字节一致；零 SQLite 触碰 | 无 |
| True + 首用 | baseline 灌入 v1=现行 persona_text → build_core_injection 返回 v1（内容与旧路径全等） | seeded 时 info 溯源 |
| True + 灌入失败（空文本/存储坏） | fail-open 用文件文本 + warn 一行 | warn |
| True + 版本库空且灌入不可用 | 同上 fail-open | warn |
| 活跃版本被旁路篡改 | 服务层拒载+quarantine 留证+自动回退最近完好版本 → chat 侧照常注入回退后内容 | 服务层 error（既有），chat 层零二次处理 |
| 全部版本损坏 | PersonaStoreUnavailable → chat 层 fail-open 文件文本 + warn | 服务层 error + chat 层 warn |
| 超管手动 publish/activate 后 | ensure 判 `"skipped_managed"` 不抢指针；注入=active 版本内容 | debug 一行 |

### 2.6 测试计划（全离线，tests/test_persona_injection_v21.py）

tmp_path persona 文件 + `PersonaService(VersionedResourceStore(tmp_path/...))` 直注 provider（零 Runtime 触碰、零 personas/ 触碰）：
1. 默认 False=raw_text 与文件文本逐字节相等 + 不产生 persona_versions 库文件（回归锁）；
2. True=灌入 seeded、raw_text==库内容、溯源 version==1/sha==sha256(文件文本)；
3. 灌入幂等=二次 build_context 版本数不增（"exists"）；
4. True+服务坏=raw_text==文件文本 + warn 告警（caplog）；
5. 损坏隔离=直改库行 v2 → 服务回退 v1 内容（degraded）+ quarantine 留证；
6. 空文本=不入库 fail-open（raw_text==""，旧兜底分支不变）；
7. 托管库不抢指针=active v2 内容优先于文件文本。

## §3 施工记录（实跑，随步落盘）

> **两席续作说明**：前任 WIRE 席落盘至 §1/§2 设计+persona_injection.py 全文+providers.py 大半接线后在飞静默死亡（COORDINATION 仅有「施工中」占位；§4 的 done 为其预注，未获实跑支撑）。本席（WIRE 重跑席）从盘面取证续作，以下逐步记录。

### 3.1 波前盘面取证（实读核实）

| 交付物 | 前任已落 | 本席核验结论 |
|---|---|---|
| `domains/chat_reply/character/persona_injection.py` | ✅ 全文 | 接口与 §2 设计一致（单例/幂等灌入状态机/fail-open 出口），+`reset_shared_persona_service` 测试钩子 |
| `providers.py` 构造器 kwargs+`_versioned_persona_text`+`build_context` 切换点 | ✅ | 逻辑正确，但引用了**不存在的模块级 `logger`**（NameError，一跑即炸——前任死亡原因推测即首次实跑失败） |
| `providers.py` factory 透传 `persona_versioned_injection` | ❌ 缺失 | 本席补 |
| `config.py` 键 / catalog A26 / `.env.example` | ❌ 三处全缺 | 本席补 |
| `tests/test_persona_injection_v21.py` | ❌ 缺失 | 本席新建 |

### 3.2 本席改动清单

1. **providers.py 两处**：①import 块后补模块级 `logger = logging.getLogger(__name__)`（与 character 兄弟模块同惯例，修前任 NameError）；②factory `FileCharacterContextProvider(...)` 尾部补 `persona_versioned_injection=bool(getattr(config, "bot_persona_versioned_injection", False))` 透传（getattr 缺省=False，旧 config stub 缺键不炸）。顺带收编前任残留 RUF100（`# noqa: BLE001` 未启用→改普通注释保语义）。
2. **config.py**（persona 键块，`bot_persona_action_brackets` 后）：`bot_persona_versioned_injection: bool = False` + 三行注释（默认 False 保守灰度口径）。
3. **docs/config-catalog-full.md** A26 表尾补行（含 fail-open/托管不抢指针/owner=persona_injection.py 语义）。
4. **.env.example**：persona 段补 `BOT_PERSONA_VERSIONED_INJECTION=false` + 两行注释。
5. **tests/test_persona_injection_v21.py** 新建 14 例（全离线 tmp_path+直注 service，零 Runtime 零 personas 触碰）：factory 消费键（缺键 False/显式 True）/默认 False 逐字节回归锁+零版本库触碰/True 灌入+溯源 info 断言/灌入幂等/状态机五态（skipped_empty·seeded·exists·activated_existing·skipped_managed）/服务桩炸 fail-open+告警/共享单例构建失败降级+闩锁复位/单例缓存 reset 语义/provenance 形态/v2 旁路篡改→回退 v1+degraded 日志+quarantine 留证/全损→文件文本+告警/托管 active 内容优先于文件/空文本不入库走旧兜底/灌入身份 published_by=system:baseline-ingest。

### 3.3 实跑证据（固定解释器 ChatBot_Runtime venv；PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0；basetemp=%TEMP%/v21r2-wireb）

| 轮次 | 命令面 | 结果 |
|---|---|---|
| 首轮新测试 | `pytest tests/test_persona_injection_v21.py` | **5 failed/9 passed——实锤前任 providers.py 缺 `logger` 的 NameError**（Error 轨迹 providers.py:326） |
| 补 logger 后 | 同上 | **14 passed** |
| 引用面回归批 1 | 20 文件（addressing/affinity/b07/chat_regressions/creator/detail/glossary×2/group_b03/perf_hotpath/persona×3/phase0_3/prfix_eat/prompt_injection/quirks/reactions/sdd7_n4/time_window + test_doc_sync_gates） | **315 passed, 2 xfailed** |
| chat 域名扫批 2 | 16 文件（auditfix_main_character/bgroup_chat_pipeline/chat_provider_chain/chat_token_limit/persona_failure/persona_source_sync/prfix_chat/prompt_audit/prompt_preview/rate_limit_silent/reply_chain 等） | **182 passed, 2 xfailed** |
| 邻接消费方批 3 | video_reply_flow/mermaid_reply_render/search_api_providers/music_provider_projection_v2 | **52 passed, 1 skipped** |
| 终态复跑 | 新测试+doc_sync 门禁（含 config-catalog 全量覆盖门=新键登记即时生效实证） | **18 passed** |
| ruff | 四触达文件（providers/persona_injection/config/新测试） | **All checks passed**（--fix 收测试 I001×1+手收 RUF100×1） |
| mypy | 权威口径三触达源文件 | 本席 0 错（2 错全=control_plane/api/platform.py:79/:254 既有基线，台账 #36 V1 席同证） |
| verify_hashes | `tests/verify_hashes.py --check` | **exit=0** |
| 树卫生 | find pycache/pytest_cache + data/ + qx.json | 零残留；qx.json 完好（W3 后 canonical 位 domains/weather/assets/） |

### 3.4 语义安全面自证（测试覆盖 ↔ §2.5 表逐行）

默认 False 零 SQLite 触碰（回归锁）/True 首用 seeded 内容全等/灌入失败 fail-open+warn/库空（服务不可建）降级+warn/旁路篡改→服务 quarantine+回退完好版本（chat 侧零二次处理，只透传 degraded 溯源）/全损→文件文本+warn/超管托管→不抢指针内容以库为准——§2.5 表七行全部有对应用例。

## §4 四列状态

| 行 | implementation | production_wiring | offline_validation | live_validation |
|---|---|---|---|---|
| V21-PERSONA-001（V1 席记） | done | **done（前任半程+WIRE 重跑席收口，§3.3 实跑证据；默认 False 灰度待用户拨键重启）** | done（V1 19 例+本席 14 例+回归 549 passed 累计三轮） | unknown（待重启+真机验收：拨 True 后首问应见 `persona versioned injection: resource=shorekeeper version=1 ...` info 溯源行） |

> 注：§4 前任预注的「wiring done」在死亡时点无实跑支撑（首轮实跑即 NameError 全红）；本席重写本节，以 §3.3 为准。
