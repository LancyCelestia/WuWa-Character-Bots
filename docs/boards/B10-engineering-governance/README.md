# B10 工程基座与治理

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10 工程基座与治理

> 门禁、生成物、命名规范与安全护栏——文档与代码不靠自觉。

职责：

- 任务入口 dev.ps1 与四门禁
- 生成物三件与机器事实册（漂移即红）
- 命名/结构/文档骨架统一规范
- 路径重映射、树卫生与归档规程

### 二级功能

| 二级功能 | 一句话 | 三级入口 |
|---|---|---|
| [任务入口与门禁](task-entry/README.md) | lint / typecheck / runtime-layout / test 四门禁与退出码语义。 | — |
| [生成物与机器事实册](generated-artifacts/README.md) | doc_sync / command_catalog / verify_hashes 三件与 auto-facts 投影。 | [会漂移计数的唯一落点](generated-artifacts/machine-ledger.md)、[交付物哈希与重录时机](generated-artifacts/hash-bookkeeping.md) |
| [测试与机器门体系](test-gates/README.md) | 离线 mock 全量树、契约门、棘轮门与交叉验证。 | [渲染与出站契约门](test-gates/contract-gates.md)、[棘轮与地板门](test-gates/ratchet-gates.md)、[变异注毒自证](test-gates/mutation-testing.md) |
| [命名与结构规范](naming-conventions/README.md) | 模块/函数/参数/配置键命名与一功能一目录的结构规范。 | [标识符与参数命名规则](naming-conventions/identifier-naming.md)、[模块与目录归属规则](naming-conventions/module-layout.md)、[函数说明文档骨架](naming-conventions/docstring-spec.md) |
| [安全与凭据护栏](security-guardrails/README.md) | SSRF 咽喉、凭据域名绑定、打码与最小暴露面。 | [下载入口与落点双查](security-guardrails/ssrf-throat.md)、[跨域凭证剥离](security-guardrails/credential-scrub.md)、[敏感信息不回传](security-guardrails/exposure-floor.md)、[出站危险命令审查](security-guardrails/outbound-command-screen.md) |
| [路径重映射与树卫生](workspace-hygiene/README.md) | 运行数据根重映射、零缓存铁律与归档规程。 | [相对路径到 Runtime 的映射](workspace-hygiene/runtime-paths.md)、[压缩→验证→移出](workspace-hygiene/archive-procedure.md) |
| [文档体系与板块树](documentation/README.md) | 十板块文档树、统一骨架、单一事实源与自动化同步契约。 | [一/二/三级板块树本体](documentation/board-tree.md)、[板块树与代码的自动同步](documentation/doc-taxonomy-sync.md)、[旧汇总文档的归属与退役](documentation/legacy-doc-migration.md) |
<!-- BOARD-AUTO:END -->

## 板块职责

本板块不产出任何用户看得见的回复。它产出的是「其余九块不腐坏」的那层机制：改错了能不能当场知道、文档与代码会不会各说各话、密钥会不会随回复出境、源码树会不会被缓存和运行数据污染。

切法依据只有一条判据：**凡能写成脚本、每次全量实跑自动比对的，归本板块；需要人（或 AI）读完再判断的，归对应业务板块**，本板块只登记「谁来执法、用什么杀」。因此同一件事常在本板块与业务板块各有一页——渲染契约的**内容**在 B08，契约的**机器门**在 `test-gates/contract-gates.md`；安全判定与内容政策在 B03，凭据与打码的**咽喉件**在这里。

与其它板块的边界：消息怎么进来归 B01，怎么路由归 B02，内容红线归 B03，数据与存储归 B04，取数归 B05，语音归 B06，调度归 B07，出站渲染归 B08，运维与控制面归 B09。本板块管的是这些链路**外层**的门禁、生成物、命名结构与护栏。

## 上下游

```mermaid
flowchart LR
  src[九板块的代码与声明源] --> gen[B10 生成器三件 + board_doc_sync]
  gen --> art[生成物：auto-facts / command-catalog / boards / render_hashes]
  art --> gates[B10 常驻门]
  src --> gates
  gates --> verd[绿 / 红（附归属）]
  verd --> dev[B10.task-entry 四门禁]
```

入站只有一样：其它板块对代码或声明源的改动。出站也只有两样：四件生成物，和一条「绿／红（红必须带归属）」的裁决。本板块不向消息主链路提供任何运行时行为，唯一例外是安全护栏——`security-guardrails` 三件（SSRF 咽喉、凭证剥离、出站打码）是**会被生产每条消息经过**的代码，它们物理住在插件包内，治理口径在本板块。

## 退役与并入记录

逐件处置依据 = `docs/boards/_meta/doc-classification-20260921.md`（全量 Markdown 分类账，字段为「路径 | 体量 | 现役性 | 主板块 | 次板块 | 一级/二级功能 | 处置建议 | 判定依据」）。

本板块按该账吸收了这些旧件的主题：`WORKSPACE_GUIDE.md`（三目录职责、启动与验证、归档入口、禁做事项）、`docs/workspace-archive-policy.md` 与 `docs/external-runtime-access.md`（同主题重复，合并为 `workspace-hygiene` 两页）、`REVIEW-WORKFLOW.md`（评审五步、严重度定义、固定清单）、`AGENTS.md` 第一部分铁律（拆进 `security-guardrails` 与 `workspace-hygiene`）、`docs/audit-20260921-commands.md`（门禁复跑与真机验收清单，落 `task-entry`）。

**现状如实**：分类账给出的是处置**建议**，物理迁移与旧件退役尚未执行。上述文件仍在原地，`AGENTS.md`、`docs/HANDBOOK.md`、`docs/CODE-MAP.md` 仍是接手权威链（账上判为「保留原地只加指针」）。并存期口径冲突时以 `docs/boards/_conventions.md` 为准；规范件与代码事实冲突时以代码为准，并立刻改规范件。波次过程件（席位日志、brief、report）一律留在 `.superpowers/`，不进 `docs/boards/`。
