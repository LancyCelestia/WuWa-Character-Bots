# 出站文案与纯文本兜底 · 渲染失败降级纯文本

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B08.outbound-copy · 渲染失败降级纯文本

- 层级：一级 B08 → 二级 outbound-copy → 三级 `plain-text-fallback`
- 实现落点：`plugins/bot_unified_runtime/output`、`plugins/bot_unified_runtime/domains/render/plain_text.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

兜底不是「出错了报个错」，而是**同样把话说完、只是不漂亮**。这张卡记录的是：卡片/图片/语音/文件任一形态出不去时，用户看到什么、内容为什么会不丢。

规则一句话：渲染层失败只以 `None` 形式表达，丢与不丢由 `text_fallback` 决定。`RenderedOutput` 每个形态都携带 `text_fallback`（`domains/render/renderer.py:render_reviewed_output`），传输层在不支持该内容类型或分片失败时按它降级。

## 怎么调用

不需要显式调用，看三个落点：

- **能力层**：`render_*_html` 拿到 HTML 后交后端出图，拿到 `None` 或空字节必须回既有文字分支。契约铁律 7 的断言面就在这（bridge 的 `None`/`{}` 纯函数断言 + 各能力回退路径断言）。
- **渲染层**：`apply_mermaid_blocks` 一张图都没渲染成功时**返回原文本与空部件列表**，行为与没挂钩逐字节一致；部分成功时失败块原样保留代码文本，成功块替换为一行占位并按阅读顺序交错出部件。护栏：单块源码过长不渲染、单条消息最多渲染前几块、整体时间预算耗尽后剩余块保留文本。
- **错误卡**：`domains/ops/monitor/error_report.py` 渲染失败时补发**全量诊断文本**（`build_text_fallback`），诊断完整性不因出图失败丢失；冷却窗内直接是一句纯文本。

## 开关与参数

- `bot_error_card_enabled`（缺省 True）：关掉即错误卡旁路零动作，回退到「只有告警日志、会话侧无回显」的旧行为。
- `bot_error_card_cooldown_seconds`（缺省 60）：同会话冷却期内降级为一句守岸人口吻纯文本。
- `bot_render_max_concurrency` / `bot_render_wait_budget_ms`：见 [render-backend](../card-render/render-backend.md)；预算耗尽的表现是按当前画面截断，**不**触发兜底，只有真失败才回文字。
- 传输能力：`transport` 不支持 `forward` 时按 `text_fallback` 降级；`mixed` 里不支持的段类型会被跳过并留痕（丢段有告警，不静默蒸发）。

## 失败时看到什么

分层，且**永远不是 traceback**：

| 失败点 | 用户看到 |
|---|---|
| 卡片出图失败 | 一条正常的纯文本回复（最坏=外观回退） |
| mermaid 块失败 | 代码块原文保留（可能带围栏），内容不丢 |
| 图片/语音不被通道支持 | 文字版说明 + 可读的原文摘要 |
| 能力抛异常 | 先毫秒级文本回执（守岸人一句话 + 异常类型），随后补发诊断卡；冷却内只有那一句 |
| 诊断卡自己又失败 | 全量诊断文本；再失败则只有告警日志，回执路径不受影响（全链 fail-open） |

日志侧的对应物：`renderer audio contract applied ... anomalies=[...]`（部件契约留痕，禁静默吞）、`playwright backend unavailable; cards fall back to text`、钉帧失败**无**日志（有意 fail-open）。

## 测试与验收

`tests/test_rendering_contract.py`（铁律 7：桥层 `None`/`{}` 不抛异常）、`tests/test_mica_shell.py`（装配壳兜底邻族）、`tests/test_mermaid_reply_render.py`（零成功=原文本零改动、部分成功=失败块保留代码）、`tests/test_error_card_contract.py` 与 `tests/test_error_card_async.py`（文本回执先行、渲染失败补发全量诊断文本、冷却降级纯文本不破）、`tests/test_fix8_render_gaps.py`。

真机（重启后）：断网触发一次 `行情`，观察是否「先一句文本回执、随后补卡或补全量诊断文本」，形态指针 `docs/acceptance-manual.md` §6.6.4⑥ 与 §6.6.10 观察点⑤。
