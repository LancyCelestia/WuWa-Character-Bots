# 卡片渲染 · 常驻浏览器与失败兜底

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B08.card-render · 常驻浏览器与失败兜底

- 层级：一级 B08 → 二级 card-render → 三级 `render-backend`
- 实现落点：`plugins/bot_unified_runtime/domains/render`、`docs/rendering-contract.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把一段完整 HTML 变成 PNG 字节。真身 `domains/render/render_backends.py`：三种后端 + 一个工厂，共同实现同一个极窄契约——`render_card(payload) -> bytes | None`，**失败只返回 `None`，不抛异常**。

- `PlaywrightRenderBackend`：现役主力。直接依赖 playwright + chromium，不经过 htmlkit。
- `HtmlKitRenderBackend`：可选替代（`nonebot_plugin_htmlkit` 可用时）。
- `NullRenderBackend`：`available=False`，一切请求返回 `None`（=全站卡片降级为纯文本）。
- `build_render_backend(name)`：按名装配；`playwright` 不可用时自动退 htmlkit，仍不可用退 Null。

选哪种由装配决定，能力层只看到一个后端对象。

## 怎么调用

`render_card({"html": ..., "viewport": ..., "wait_ms": ..., "wait_budget_ms"?: ..., "wait_js"?: ..., "device_scale_factor"?: ...})`。

调用位置有硬约束：**必须在非事件循环线程上执行**（`asyncio.to_thread` / 专用线程池）。原因是 sync playwright 与 asyncio 互斥、且浏览器实例线程绑定。两条既有落点：能力层 offload；mermaid 围栏块渲染走 `domains/render/renderer.py:_get_mermaid_executor` 的单线程池（`render_reviewed_output` 可能被直接调在事件循环线程上）；错误卡走 `domains/ops/monitor/error_report.py` 自己的单线程渲染通道。

进程级共享：`build_render_backend` 每次产出可用的 playwright 后端时按「先到先得」登记（`get_shared_render_backend`），bridge 侧优先取用，避免同一进程存两套常驻浏览器。生命周期归首个装配方，借用方从不 `close`。

## 开关与参数

两个键，解析链一律「driver config → 进程 env → 缺省」，不配置时行为逐字节等于现状：

| 键 | 缺省 | 含义 |
|---|---|---|
| `bot_render_max_concurrency` | `1` | 跨线程并行出图上限。实例内互斥从全程大锁升级为 `BoundedSemaphore(N)`；`1` 等价旧串行语义（天然回滚位）。同线程任一时刻仍只有一个活跃 ctx。 |
| `bot_render_wait_budget_ms` | `0`（=不启用） | 把固定地板等待升级为「预算上限」：就绪信号齐即提前截图，未达成则等到封顶按当前画面截断。payload 显式 `wait_budget_ms` 恒优先于全局缺省。 |

后端内部常量（非配置面，改需改码）：空闲回收阈值、页面加载超时、连续页面失败阈值、浏览器崩溃特征串表。

## 失败时看到什么

分层降级，外部只看得到「这条变成文字」：

- 后端不可用（playwright 未装/浏览器缺失）→ `available=False` → Null → 调用方纯文本，日志一句 `playwright backend unavailable; cards fall back to text`。
- 配置名拼错 → 不是静默变 Null 就完事：先 `warning`（`unknown render backend name ... falling back to null renderer`）再降级，留诊断线索。
- 页面级失败（加载超时、截图失败、`wait_js` 未达成、html 为空/非法）→ 只关这一页，返回 `None`，浏览器保留复用。
- 浏览器级故障（`target closed` / `browser has crashed` 等特征命中）**或**连续页面失败达阈值 → 丢弃线程常驻实例，下次懒启动重建。第二条件是 2026-09-12 实弹根修：`is_connected()` 仍为真但内核僵死时，光看崩溃标记会永久卡死、所有封面全量降级。
- 图片资源：微博系图床有防盗链/ORB 拦截，命中时对页面内图片走「Python 侧取字节 + 请求级 fulfill」，带条目与字节双上限的进程内缓存；取不到就 abort 该请求，不拖垮整页。
- mermaid：本地素材缺失或校验不过就不注册拦截，放行网络请求（诚实降级，不拿半截 JS 出图）。
- 动画钉帧失败：静默跳过，回落流逝时刻截图（见 [animation-pinning](animation-pinning.md)）。

## 测试与验收

`tests/test_render_backends.py`（后端选择、`.card` 与 full_page 两条截图路径、`None` 语义）、`tests/test_render_launch_backoff.py`（launch 重试与退避在临界区外）、`tests/test_render_wait_budget.py`（预算模式与缺省地板的分支）、`tests/test_render_phase2_env_keys.py`（两键的解析链）、`tests/test_render_image_cache.py`（ORB 缓存与上限）、`tests/test_render_pool_hygiene.py`（线程池与 atexit 回收）、`tests/test_mermaid_reply_render.py`（围栏块检测→部件交错）、`tests/test_error_card_async.py`（错误卡两段式与渲染通道）。

真机观察（重启后）：`docs/acceptance-manual.md` §6.6.10 观察点⑤「渲染失败纯文本兜底」，以及 §6.6.5 的 mermaid 出图观察；渲染链路的在线耗时基线用 `python scripts/measure_latency_chains.py` 补测。
