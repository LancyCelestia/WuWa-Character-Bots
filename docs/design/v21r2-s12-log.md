# V21R2 S12 席日志（占卜/运势 REST 端点与渲染投影）

- 日期：2026-09-17（开工）→ 2026-09-18（断点续收席终态）
- 合同：backend-v2-implementation-guide.md 席位表 S12 行 + backend-v2-product-extensions.md §3 + 验收矩阵 V21-DIVINATION-001/002/003
- 状态：**已收口（in-seat tested）→ 见文末「四列状态」**

## 〇、断点续收取证结论（2026-09-18 续收席，先写后动）

前任在 04:24 日志计划期后静默死亡，但**实现已基本落盘**（比本日志记录的进度远）：
1. `control_plane/api/divination.py`（实际路径 `plugins/bot_unified_runtime/control_plane/api/divination.py`，untracked）——
   8 端点全实现（capabilities/config/draws/draws/{id}/interpretation/fortune/daily/tarot/draw/bazi/preview），
   envelope+RBAC（内检 admin 门）+审计钩子（fail-open、不记 question 正文）齐备。
2. `domains/divination/api/{__init__,dto,errors,facet}.py` 全部落盘——严格 DTO（extra=forbid）、
   错误投影（只读消费 ERROR_REGISTRY）、DivinationHttpFacade 薄壳 + BaziRateLimiter +
   `build_divination_facade_from_config`（缺键→None→503 诚实位）。
3. `domains/divination/projection/{__init__,render_projection}.py` 落盘——build_draw_projection/
   render_draw_card（既有渲染消费面复刻、失败回退纯文本契约）+ 话术池 3 变体确定性轮换。
4. `tests/test_v21_s12_divination_api.py` 落盘，续收席首跑 **26 passed**。
5. `_app.py:478-491` 挂接段**已由前任完成**（build_divination_facade_from_config + build_divination_router +
   _v1_read_dependency + audit_store，与 actions/platform 前例同构）。

续收席补完（本席文件域内零越界）：
- ruff 三处清零：api/__init__.py I001 + 测试文件 I001（--fix）；control_plane/api/divination.py S110
  （try-except-pass → `logger.debug(..., exc_info=True)`，对齐 audit.py 本文件吞异常惯例）。
- 测试文件新增 `test_real_control_plane_app_mounts_divination_end_to_end`——真工厂
  `create_control_plane_app` 装配冒烟：未配 divination_db → 真装配下 capabilities 503 divination_unavailable；
  配置后重装 → 真 Bearer 依赖（bearer-admin ≥ user）下 tarot/draw 端到端 200。27 passed。

## 一、计划（先落盘后动手）

### 前提盘点（已实读确认）
- W5 域半边已收口且**只读消费**：`domains/divination/service/{fortune,tarot_draw,divination_service}.py`、
  `domains/divination/store/draw_store.py`、`domains/divination/data/{ganzhi,tarot}.py`——
  全部只 import 调用，**零改动其算法/存储**。
- REST 挂载形态：`control_plane/api/` 既有 `actions.py`/`platform.py` 的独立 router builder 前例；
  `_app.py` 既有 `app.include_router(build_platform_router(..., prefix="/api/v1"))` 前例——
  本席照此挂载，**不改 v1.py 签名**。
- envelope/errors：`control_plane/api/protocol.py::envelope`（S9 增补 trace_id 后形态）+
  `ControlPlaneError(status, code, message)`；DrawError 域码全部已注册于
  `domains/core/contracts/errors.py`（invalid_spread 422 / deck_integrity_mismatch 503 /
  idempotency_conflict 409 / feature_disabled 409 / rate_limited 429 / resource_not_found 404）。
  `not_wired` 不入全局注册表（contracts/** RWOC 在飞禁触），走控制面本码前例
  （config_store_unavailable / traces_unavailable 同类）。
- 渲染消费面：`domains/divination/capabilities/divination.py::_render_card` 既有管线
  = `build_divination_card_content(kind,title,body)`（纯构造）→ `render_card_png(backend,item,
  config=,card_dir=,feature_label="占卜")`；失败→空串→纯文本兜底（既有契约）。投影函数复刻该消费面，
  **卡片模板零改动**。
- 渲染投影用 Jinja 模板不动；`render_card_png` 惰性导入 + 可注入 card_renderer（离线测试假后端）。

### 交付物（新增文件；禁触名单外零越界）
1. `domains/divination/api/__init__.py` + `api/dto.py`——严格请求 DTO
   （DivinationDrawPayload / FortuneDailyPayload / TarotDrawPayload / BaziPreviewPayload，
   extra=forbid、question≤500、timezone 可加载、复用 IDEMPOTENCY_KEY_PATTERN 语义）。
2. `domains/divination/api/errors.py`——DrawError/ValueError → (HTTP 状态, 码, 人话, retryable)
   映射（读 ERROR_REGISTRY，不改它）；`InterpretationNotWiredError`（503 not_wired 诚实）。
3. `domains/divination/api/facet.py`——`DivinationHttpFacade`（薄壳持 DivinationService +
   fortune_ready + 可注入 clock + bot_id）；bazi 预览独立每主体固定窗限速（bazi 非持久抽取，
   不占 draw_store 配额；tarot/fortune 频控=draw_store 额度语义：塔罗 60s 冷却/每日 20 次
   事务内判定、运势 day_key 每日一次幂等+重读不限）；角色判定复用 `policy.roles.ROLE_ORDER`。
4. `domains/divination/projection/__init__.py` + `projection/render_projection.py`——
   `build_draw_projection(DrawResult)`（标题/正文/纯文本兜底/卡 payload 纯构造）+
   `render_draw_card(...)`（既有 renderer 消费面；失败回退 ("" , plain_text) 契约）+
   守岸人语气话术池（解读未接线提示 3 变体、draw_id 确定性轮换）。
5. `control_plane/api/divination.py`——`build_divination_router`：
   - GET `/api/v1/divination/capabilities`（user+）
   - POST `/api/v1/divination/draws`（user+；Idempotency-Key 头必填）
   - GET `/api/v1/divination/draws/{draw_id}`（user+）
   - POST `/api/v1/divination/draws/{draw_id}/interpretation`（user+）→ 503 not_wired
   - POST `/api/v1/divination/fortune/daily`（user+；别名字形，kind 预置）
   - POST `/api/v1/divination/tarot/draw`（user+；别名字形）
   - POST `/api/v1/divination/bazi/preview`（user+；既有八字算法只读投影，零持久化）
   - GET `/api/v1/divination/config`（admin+；政策/版本/配额投影，require_role 内检）
   - 全部 envelope + 审计钩子（ControlPlaneAuditStore.record，吞异常 fail-open）。
6. `control_plane/_app.py` 装配段——照 platform 前例：config 缺
   `bot_control_plane_divination_db` → facade=None → 各端点 503 divination_unavailable
   （诚实未装配，与 actions/config 前例一致；生产启用留配置键，不闯 config.py/config-catalog 共享面）。
7. `tests/test_v21_s12_divination_api.py`——全离线（tmp_path SQLite + SeededPrng + 注入 clock +
   假 render 后端）：同日幂等/时区边界/密钥轮换不重抽/seed 固定复现/无放回/78 张完整/
   阵型白名单/频控/越权 403/not_wired 503/渲染回退/envelope 形态/审计落库/bazi 一致性与限速。

### 明确不做（防范围蔓延）
- 不动 `contracts/**`（RWOC）、`capabilities/chat.py`（RWC3）、`runtime/pipeline+ingress+base_router`（RWC4）、
  `__init__.py`+`domains/meme`（DSP）、`domains/schedule`（S11）、`domains/render`（收官稳定）、`llm/*`。
- 不实装 LLM 真调用（503 not_wired 是交付而非欠账）；不加 config.py 新键；不触 personas/。
- 塔罗同键重试恒返回既有抽取（§3 领域契约优先于 §6 泛化 409；跨类/跨日复用仍 409）。

## 二、实跑证据（2026-09-18 续收席终态实跑）

- **本席套件**：`pytest tests/test_v21_s12_divination_api.py` → **27 passed**（5.08s；
  含新增真装配端到端冒烟）。env：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`、
  解释器=ChatBot_Runtime venv、`--basetemp=$TEMP/v21r2-s12b*`、`-p no:cacheprovider`、禁 dev.ps1。
- **W5 存量 743 面回归（13 显式文件，照 v21r2-reorg-w5-log §1 清单全跑）**：
  **743 passed, 1 skipped**（7.95s）——与 W5 终态逐位吻合，零回归。
- **合并面**（13 文件 + 本席测试文件同跑）：**770 passed, 1 skipped**（14.78s）。
- **控制面族**（`-k control_plane` 全量）：**274 passed**（68.32s）——`_app.py` 挂接段零破坏装配。
- **ruff 本席文件域**（control_plane/api/divination.py + domains/divination/api/ + projection/ + 测试文件）：
  **All checks passed**（3 处初错已清：I001×2 --fix + S110 手改 logger.debug）。
- **mypy 权威口径**（`--explicit-package-bases --ignore-missing-imports plugins`）：
  717 files checked，4 errors 全部**非本席**——platform.py:79/254 既有基线（W5 日志 §3-⑥ 同口径）
  + domains/chat_reply/character/providers.py:313/326（WIRE 席在飞文件，本席禁区）；本席文件零错误。

## 三、遗留

1. **树卫生移交**：`plugins/bot_unified_runtime/{control_plane,decision,domains/core/decision,domains/meme/reactions,}/__pycache__`
   5 处非本席产物（control_plane 处 mtime=2026-09-18 05:09，为并行在飞席位无 env 写入），
   续收期间写者活跃、清理即再生——留收尾波统一 `%TEMP%` 备份后清零（台账 #1/#33 惯例）。
2. **生产未装配未部署**：启用需 config 配 `bot_control_plane_divination_db`（经 runtime_paths 重映射）
   + 可选 `bot_divination_fortune_secret`（不配则运势 409 feature_disabled、塔罗/bazi 照常）。
   未加 config.py 新键（防闯共享面），配置键留生产 .env 侧裁决。
3. **LLM 人格化解释=503 not_wired 诚实位**（交付而非欠账）；真接线属后续席位。
4. 未 commit——共享工作树多席并行，提交裁决权在用户。

## 四、四列状态（验收矩阵自记）
- V21-DIVINATION-001（运势每日固定/权重/幂等与娱乐解释）：**implemented（in-seat tested，2026-09-18 续收取证+补验）**——
  同日幂等（跨幂等键/跨会话/时区日界/密钥轮换不重抽）27 例内全覆盖；真装配冒烟打通；生产装配留 config 键（未部署）。
- V21-DIVINATION-002（塔罗无放回/阵型/正逆位/确定解读）：**implemented（in-seat tested）**——
  固定 seed 复现/无放回/78 张/阵型白名单/配额 429/渲染回退纯文本全测齐；LLM 解释=503 not_wired 诚实位 + 话术池。
- V21-DIVINATION-003（既有八字/占卜语义保持与边界复核）：**implemented（in-seat tested）**——
  bazi preview 只读投影与 data/ganzhi 直算同源断言过、时区换东八区、越界 422、每主体固定窗限速；
  原算法回归=W5 存量 743 面实跑 **743 passed, 1 skipped** 不红；S13 共有列不代答。
