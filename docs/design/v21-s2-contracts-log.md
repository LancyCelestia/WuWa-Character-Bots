# V2.1 S2 协议席（A8）日志 — 统一 DTO/错误协议 + import 副作用探针

> 席位：S2 前半（合同 = `docs/design/backend-v2-implementation-guide.md` §6；验收矩阵 V21-CORE-001 与 V21-API-001 的 DTO/envelope 部分）
> 日期：2026-09-17。状态：代码+测试完成（151 passed / Ruff 全过 / 我方文件 Mypy 零错）；全部为新增文件，未编辑任何现存文件，未 commit，未部署。

## 一、既有 contracts 现状摘要（动手前勘查）

- `plugins/bot_unified_runtime/contracts/` 共 8 个现存文件：`__init__.py`（re-export 面）、`runtime.py`、`character.py`、`finance.py`、`media.py`、`music.py`、`subscription.py`、`auto_send.py`。风格：pydantic v2（2.13.4 / Python 3.12.10）、`StrictBaseModel(extra="forbid")`、`new_request_id/new_debug_id`（`<前缀>_<uuid4 12hex>`）、中文注释。
- **关键勘查发现（决定新模块形态）**：`contracts/runtime.py` 顶部 `from plugins.bot_unified_runtime.message_context import ReplyChainItem` —— contracts 内任一现存模块被 import 都会先拉起父包 `plugins/bot_unified_runtime/__init__.py`（约 4700 行、含 matcher 注册）。因此：
  - 直载探针若复用 runtime.py 的类型/helpers 必然引入父包副作用 → 本席三个新模块**有意零包内 import**（pydantic+stdlib 自包含），helpers 以同格式最小复制并注释收敛归属；
  - 复用判定：`runtime.py` 的 `StrictBaseModel` 缺 `allow_inf_nan=False`，§6 要求 NaN/Inf 拒绝 → 新建 `V21StrictBase`（薄基类，注明与 runtime.py 的收敛待后续席位）。
- **既有 envelope 相关 DTO（薄适配注记）**：`control_plane/api/protocol.py` 已有局部 `envelope()`/`ResponseMeta`/`ErrorInfo`/`ApiEnvelope`——但 meta 缺 `trace_id`、ErrorInfo 缺 `trace_id`、无错误注册表、`field_errors` 为裸 dict。本席新模块是 V2.1 权威契约源（含 trace_id 全链），旧侧不改（并行代理在飞+禁改现存文件）；旧 control_plane → 新契约的适配属后续 S2/S6 席位。
- `contracts/__init__.py` 为现存文件未动：新模块未经包级 re-export，消费方按 `plugins.bot_unified_runtime.contracts.envelope` 子模块路径导入；re-export 收敛属后续席位（需编辑现存 `__init__.py`）。

## 二、新增文件清单

| 文件 | 内容 |
|---|---|
| `plugins/bot_unified_runtime/contracts/envelope.py` | `SCHEMA_VERSION`（Literal["v1"] 锁死）、`ResponseMeta`（request_id/trace_id/schema_version/generated_at 强制 aware→UTC 归一）、`FieldError`（不回显原始入参值）、`ErrorBody`（§6 恰七键：code/message/request_id/trace_id/debug_id/retryable/field_errors）、`ApiEnvelope[T]`（Generic，data/error/meta 三键 extra=forbid）、`RetryHint`（429 族 data 载荷，float 字段验证 NaN/Inf 拒绝）、`success_envelope()`（线格式构建器，显式 ID 原样传播）。全部 `extra="forbid"` + `allow_inf_nan=False` |
| `plugins/bot_unified_runtime/contracts/errors.py` | 错误码**单一注册源**：`ErrorSpec`（frozen dataclass）×41 条（§6 主表 27 + 扩展补充 14）、`ERROR_REGISTRY`、`LEGACY_CODE_ALIASES`（旧码兼容映射接口，空 dict + 导入期目标自检）、`resolve_code()`、`UnknownErrorCodeError`、`error_body()`、`error_envelope(code, **fields)`（模板占位符安全插值，缺失占位符保持字面量不抛错；`message=` 显式覆盖）。纯 stdlib（不碰 pydantic），线格式契约由 envelope.py 模型交叉校验 |
| `plugins/bot_unified_runtime/contracts/request.py` | 请求侧严格 DTO：`PaginationQuery`（默认 50/最大 200/稳定游标，limit strict int）、`WriteExpectation`（expected_version≥0，创建=0）、`IdempotencyRef`（key 正则与 control_plane 既有载荷同口径 + payload_sha256 64hex，同键不同摘要→409 的承载事实）、`ConfirmationRef`（token/actor/target/expected_version/content_sha256 绑定 + issued/expires aware 校验 + TTL≤120s 硬门，"一次消费"归运行时）、`PrincipalRef`（含 `auth_source` 区分 authenticated/compat_service；注明 principal 只能由认证层注入、接入层必须剥除客户端载荷） |
| `tests/test_contracts_v21.py` | 151 例：错误注册表全量断言 + envelope 往返/拒绝族 + request DTO 边界 + 探针一/探针二 |
| `docs/design/v21-s2-contracts-log.md` | 本文件 |

### 错误码注册语义要点（与规范对齐的裁定）

- `delivery_unknown`：规范口径为「任务/part 状态、不滥用 500」→ `http_status=None`（不映射顶层 HTTP），retryable=False（先对账不盲重）。
- retryable 默认按 §6 行为列推导：限流/容量/依赖/存储/上游限流/资源额度/reload 失败/deadline=True；凭据失败/完整性/回滚失败/预算耗尽/确认族/冲突族=False。`retryable` 仅提示，重试决策另需 deadline/幂等条件（规范原文）。
- 41 条全部人话中文模板（守岸人语气、≤80 字、无栈/路径/内部端点/框架名），测试逐条做泄露形态断言。
- 扩展 14 码（usage_inconsistent 502 / price_unavailable 503 / budget_exceeded 429 / affinity_unit_mismatch 422 / affinity_evidence_missing 409 / invalid_spread 422 / deck_integrity_mismatch 503 / schedule_cycle 422 / missing_calendar 409 / ambiguous_local_time 422 / schedule_conflict 409 / occurrence_expired 409 / unsupported_platform_capability 422 / acceptance_authorization_expired 403）逐条对齐 `backend-v2-product-extensions.md` 集中注册段。

## 三、探针实跑结论（V21-CORE-001 真实发现）

### 探针一：直载（importlib.util.spec_from_file_location，进程内五路观测）

对三个新模块逐一断言，全部通过：
- sys.modules 无 nonebot 系**新增**（delta 语义：pytest 共享进程内若前置测试已加载 nonebot，按增量判定，见 `test_direct_load_has_no_side_effects`）；
- `threading.active_count()` 前后不变（零新线程）；
- cwd 零新文件；
- `socket.socket` 换计数子类后**零构造**，`create_connection`/`getaddrinfo` 被断言雷零触发（零网络）;
- `builtins.open` 计数零调用（零配置文件读取）。
- 静态面：三模块源码无 nonebot/requests/httpx/aiohttp/urllib.request 字样。
- 附带修复记录：探针基建曾把模块漏注册进 sys.modules，dataclasses 处理 `errors.py` 冻结数据类字符串注解时 `sys.modules.get(cls.__module__)` 得 None 崩溃——直载必须先 `sys.modules[name]=module` 再 exec（已修并注释）。

### 探针二：包内导入现实（子进程 `import plugins.bot_unified_runtime.contracts.envelope`）

实跑命令（env：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，cwd=工作区根）输出 JSON：

```json
{"probe": "package_import", "target": "plugins.bot_unified_runtime.contracts.envelope", "ok": true, "module_usable": true, "elapsed_ms": 1180.1, "parent_imported": true, "nonebot_loaded": true, "delta_modules": 1074, "threads_before": 1, "threads_after": 1, "cwd_new_files": []}
```

**如实结论**：
1. 子模块导入**必然**经过父包 `__init__.py`（`parent_imported=true`），父包把 nonebot 全量拉起（`nonebot_loaded=true`，sys.modules 增量 **1074** 个模块，首次导入 ≈1.18s）。即：V2.1 目标「contracts 纯净装配」在**包内导入路径**上当前不成立，与探针一的「文件直载纯净」并存——父包装配收敛（懒加载/装配根拆分）属后续 S2/S6 席位，本席不修。
2. 副作用有边界：进程内线程数不变（1→1）、cwd 零新文件（探针断言常驻守卫）。即父包当前是「import 重」但非「启动副作用」形态（无线程/文件外泄），这与 bot.py 先 init 后 load_plugin 的生产次序一致。
3. 测试对该探针只做结构硬断言（探针可信、cwd 干净、成功则 parent_imported/module_usable 必真），nonebot_loaded/delta/elapsed 作为证据字段落本文件，不在测试里钉死具体值——父包收敛后无需回头改测试。

## 四、测试实跑证据

命令（禁用 dev.ps1，直跑纪律全守）：

```powershell
cd c:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
  ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_contracts_v21.py \
  --basetemp="$TEMP/v21-contracts" -p no:cacheprovider -q
```

实跑输出（终态，TDD 红灯→绿灯全程实跑）：

```
........................................................................ [ 95%]
.......                                                                  [100%]
151 passed in 1.65s
```

TDD 过程留痕：实现前首跑 `6 failed, 1 passed, 144 errors`（红灯，144=模块缺失 fixture errors；1 passed=探针二如实记录"子模块尚不存在"，符合其结构断言设计）；实现后 `1 failed, 150 passed`（探针基建 sys.modules 注册缺陷）；修正后 `151 passed`。

静态门（同环境实跑）：

```
ruff check <3 新模块 + tests/test_contracts_v21.py>  →  All checks passed!
mypy --explicit-package-bases --ignore-missing-imports <同上>  →  Found 2 errors in 1 file（全部位于存量 control_plane/api/platform.py，
  单独复跑该文件证实为与本批无关的存量错误；本席 4 文件 mypy 零错误）
```

树卫生：contracts/ 与 tests/ 无 `__pycache__`/`.pytest_cache`/`*.pyc`，无 `data/` 残留（mypy/ruff/pytest 缓存全部指向 %TEMP%）。

## 五、遗留项（按优先级）

1. **父包 import 副作用收敛**（V21-CORE-001 剩余半边）：`plugins/bot_unified_runtime/__init__.py` 拉起 nonebot+1074 模块，属后续 S2/S6 装配根拆分；本席新模块已做到文件级纯净，为收敛提供锚点。
2. **control_plane → 新契约适配**：旧 `api/protocol.py` envelope（缺 trace_id/无注册表）迁到本席 `contracts/envelope.py+errors.py`；`ERROR_RESPONSES` OpenAPI 映射可由 `ERROR_REGISTRY`（http_status 列）确定性生成（delivery_unknown 的 None 语义需在该步处理）。
3. **`contracts/__init__.py` re-export 收敛** + 与 `runtime.py` 的 `StrictBaseModel`/`new_request_id` 合并（需编辑现存文件，且 `runtime.py` 当前有并行在飞的未提交改动，须等收敛窗口）。
4. **旧码兼容映射填充**：`LEGACY_CODE_ALIASES` 接口已留（含导入期自检+`resolve_code`），具体旧码清单待旧 matcher 面（§10 Dispatcher 收编）盘点后填入。
5. Mypy 存量错误 2 处（`control_plane/api/platform.py:187,366`，独立复跑证实非本批引入）——归控制面席位账。
