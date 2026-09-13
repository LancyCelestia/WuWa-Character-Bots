# 性能优化全量文档（Track 2 · Phase 1 终态 + Phase 2 执行清单）

> **状态口径**（2026-09-13）：Phase 1 已落地并全量测试绿；Phase 2 待 23:00 收尾批执行
> （用户指令：性能优化内容全部入档，23:00 后全部完成）。本文档是 Phase 2 的唯一执行依据。
> 底层规格：`docs/design/render-pipeline-optimization-spec.md`（等待预算/并发模型/缓存策略）。
> 实现真值源：`plugins/bot_unified_runtime/output/render_backends.py` + `tests/test_render_wait_budget.py`。

## 一、Phase 1 已落地（缺省行为字节级等价）

| 件 | 位置 | 语义 |
|---|---|---|
| 预算等待 `_wait_render_budget` | render_backends.py:105 | 三就绪信号依次等（fonts.ready → 图片双采样稳定 → 双 rAF 帧界），齐即提前截，预算封顶截断；**仅 payload 带 `wait_budget_ms` 时启用**，缺省 None → 旧固定等待路径逐字节不变 |
| 并发框架 `BoundedSemaphore(max_concurrency)` | render_backends.py:226 | 属性名保留 `_lock`；默认 1 = 与旧全程大锁完全等价的串行语义（天然回滚位）；>1 时跨线程并行、线程本地浏览器复用/懒启动/自愈零改动 |
| C-1 中毒修复 | render_backends.py:243-269 | launch 失败分支 `ctx.__exit__` + thread-local 只在成功后写入——线程不再永久中毒 |
| E01 相位钉帧 | 模板+测试（test_phase_determinism*.py） | 截图字节确定性（动画相位固定），为缓存/比对打底 |
| 页面级失败自愈阈值 | render_backends.py:211 `_MAX_CONSECUTIVE_PAGE_FAILURES=2` | 内核僵死（is_connected 但渲染全败）→ 丢弃常驻实例懒启动自愈 |

**字节级等价声明**：`wait_budget_ms` 不传 = 不进预算分支；`max_concurrency=1` = 串行旧语义。
全量回归 4523 passed / 0 failed（2026-09-13，组合证据）佐证。

## 二、五条延迟链路定义与测量方案

| 链路 | 组成 | 测量方式 | 当前基线 |
|---|---|---|---|
| ① 项目内部 | 摄取→路由→门禁→能力→审核→出站 | `measure_latency_chains.py route`（2000 样例热路径） | **P50 0.014ms / P95 0.054ms**（2026-09-13 实测，verified） |
| ② HTML 渲染及发送 | 渲染后端截图 + chunks/合并转发 | `measure_latency_chains.py render` | **warm P50 2222ms / P95 2249ms，冷启动 2820ms**（2026-09-13 实测；≈2.2s 中约 1.5s 为固定 sleep 地板——Phase 2 预算等待的直接收益空间，verified） |
| ③ NapCat | SendQueue→OneBot WS 往返 | 脚本 TCP 握手探活 | **unreachable**（2026-09-13：bot 离线，与台账 #10 一致；重启后重测） |
| ④ Mail | SMTP 投递 | 脚本握手（需 BOT_SMTP_HOST 环境变量） | no-config（本机 shell 未导出，重启后随批补测） |
| ⑤ Telegram | Bot API 往返 | getMe 计时（需 token 环境变量） | no-config（同上） |

**测量脚本**：`scripts/measure_latency_chains.py`（本次随批交付）——离线段（①②）任何时刻可跑；
在线段（③④⑤）探测 NapCat WS 127.0.0.1:3001 / SMTP / TG API，连不上则明确输出 `unreachable`，
绝不编造数值。23:00 批跑全量；若届时 bot 仍离线，在线段保持 unknown 并把「重启后补测」写进台账。

## 三、Phase 2 执行清单（23:00 收尾批照此逐步执行）

1. **配置键接线**（config.py + render_backends.py:453 调用点 + bridge.py payload 注入）：
   - `BOT_RENDER_MAX_CONCURRENCY`（默认 **1** = 现状）：>1 时传给 `PlaywrightRenderBackend(max_concurrency=N)`。
   - `BOT_RENDER_WAIT_BUDGET_MS`（默认 **空/0 = 不启用**）：>0 时由 bridge 在渲染 payload 注入 `wait_budget_ms`。
   - 两键全部缺省安全：不配置 = 与今天行为逐字节一致。
2. **config-catalog-full.md + .env.example 同步补录两键**（一致性门禁会拦漏登）。
3. **解锁取值**：并发默认建议 2（Playwright 常驻实例按线程存放，2 并发 = 2 线程本地浏览器，内存增量可观测后再升）；
   预算默认建议 1500ms（等于旧固定等待地板，只提前不延后）。
4. **验收（全绿才许交付）**：
   - `dev.ps1 -Task test/lint/typecheck` 全绿；
   - `scripts/measure_latency_chains.py render`：启用预算后渲染 P95 不高于禁用态 +110%（预算只砍等待不砍正确性，出图失败率必须持平）；
   - 并发 2 下连续 10 张卡渲染成功且无 `Sync API inside asyncio` 报错（线程不变量未被破坏）。
5. **回滚方式**：两键清空/置 0 即回到串行+固定等待（无需回滚代码）。
6. **风险与触发条件**：并发 >1 时内存随浏览器实例数线性增长——若机器内存吃紧或出现 Chromium 崩溃，回拨 1。
7. **生效条件**：改码须重启 bot（生产进程提权常驻，重启只能由用户执行）；23:00 批完成代码+测试后，
   「重启+真机验收 §6.6」仍等用户。

## 四、23:00 定时任务

已设一次性定时任务（当晚 23:00）：提示按本文档 §三执行 Phase 2 全部步骤并回填实测基线。
若会话环境不可用，本文档即自足执行依据（接手者零上下文可做）。
