# B06.creation 创作与图片生成

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.creation 创作与图片生成

> 图像/语音创作扩展位与共用件。

- 归属板块：[B06](../README.md)
- 实现落点：`plugins/bot_unified_runtime/domains/creation`
- 帮助主题：草稿
- 配置键前缀：`bot_creation_`（逐键以目录册为准）

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
<!-- BOARD-AUTO:END -->

## 这个功能解决什么

二级功能 B06.creation「创作与图片生成」是 creation 域的**协议在册面**，不是空骨架：
绘画与语音两处对接点各有契约真身、中央描述符与已注册的执行体，真正缺的是**真实
provider**，不是协议。上方生成区那句「扩展位」是板块声明源的一行摘要投影（机器所有，
本页不改它，也不据它判现状），实况由下面「边界与降级」承担。

本页上方的生成区从权威声明源投影，实现落点与归属以它为准，正文不复制。 一切可数事实（字段/主题/别名/入口/模板数）以机器册 `docs/auto-facts.md` 为准。

## 处理流程

```mermaid
flowchart LR
  in[入口] --> core[处理] --> out[产出]
```

## 边界与降级

开关面：配置键前缀 `bot_creation_`，逐键缺省与热更性以 `docs/config-catalog-full.md` 为准。

- **在册 ≠ 可用**：provider 选择器键（`bot_creation_image_provider`、
  `bot_creation_tts_provider`）未填 ⇒ 执行体诚实回 `UNAVAILABLE`，绝不冒充出图或合成；
  绘画键名唯一在册真身是 `domains/core/capability_manifest.py` 的 `config_keys_for`，
  域内探测表 `domains/creation/reserved_provider.py` 从它派生（禁第二处手抄）。
- **缺位是看得见的缺位**：三面同源——`/bot status` 的 creation 状态行、周期巡检告警
  （唯一入口 `domains/creation/reserved_health_alert.py::patrol_reserved_health`，已在根
  装配为后台任务、复用中央告警 sink 与抑制器；首轮延时与轮询周期是那个装配块的常量，
  以 `plugins/bot_unified_runtime/__init__.py` 现文为准）、控制面 HTTP 把未接线读成 503
  （`domains/creation/image/routes.py`、`domains/creation/tts/routes.py`）。两态分得很清：
  **从没填过 provider** ⇒ 每进程只响一次（`creation_not_configured`，不可重试——常态配置态
  不是瞬时故障，别把它变成刷屏）；**填了键却派不出适配器** ⇒ 每轮重算、可再响。
- **诊断卡那面对绘画今天不成立，且是结构性的**：它非路由命令形，中央把
  `INVOKER_ERROR_DATA_KEY` 交回层 1 再抛的那条腿对它永不触发（这条判定写在
  `domains/creation/image/routes.py` 的模块头，不只在文档里断言）。因此本节末那句
  「异常走统一诊断卡」的项目级口径，在本域只覆盖语音侧。
- **段数与接入进度都不写在正文**：协议各段的在册账以
  `tests/test_creation_protocol_segment_ledger.py` 现算为准；哪些在册能力真走了中央
  `invoke`、还剩多少没走，以 `tests/test_descriptor_wiredness_ledger.py` 的活体缺口账为准。

失败与降级的逐条契约写在真身模块 docstring 里，页内不抄；项目级口径：外部依赖失败不编数、诚实标注无源，异常走统一诊断卡（绘画侧的结构性例外见上一条）。

## 测试与验收

离线用例：`tests/test_creation_job_protocol.py`、`tests/test_creation_protocol_parity.py`、`tests/test_creation_tts_drift_gate.py`。

上面按名强匹配点到的是与本功能同族的用例件、非穷举；用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑为准，真机验收条目见 `docs/acceptance-manual.md`。

## 现行缺陷

已知未修项的唯一台账是 `docs/issue-ledger-p2-p3.md` 与 `docs/boards/_meta/code-quality-findings-20260921.md`，逐条归属看那两份，此处不抄。
