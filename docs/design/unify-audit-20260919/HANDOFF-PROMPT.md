# 接手提示词 · 前端统一审计收尾波（2026-09-19）

> 用法：整段粘给新会话。**先读 `docs/design/unify-audit-20260919/FRONTEND-AUDIT.md`**（唯一读数入口），
> 席位对账单在同目录（27 份），只在需要某条的完整证据时才翻。

---

你是「守岸人 Bot」前端审计波次的接手者。工作区 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`，分支 `v0.0.1-alpha.2`。

## 现状（不要重述，要复核）

- 前端审计已完成 **6 项 P0 + 9 项 P1 修复**，总账：`docs/design/unify-audit-20260919/FRONTEND-AUDIT.md`（§八 是波次二增量）。
- 已入库：`a76cc2b`（`webui/` 整树首入库）→ `0d555a5`（P0/P1 + 门四牙 + 22 席对账单）→ `c22bdeb` / `a418292` → `97eccbc`（脱栅还债 + 门规则⑧⑨）→ `f4f4572`（三族单源化）→ `1a134e3`（窄屏导航 + 深链归一）。
- **用户裁定已落**：第二批**随本波入库**；`control_plane/metrics.py` 与 `tests/test_webui_stats.py` **随控制面整波入库、本波不动**（该包仅 7 件在册、`domains/` 零在册，单提两件在干净克隆必红）；`verify_hashes --write` 只重录**订正席实际改过的在册文件**，先 `--check` 逐条核对归属，禁止全册一把祝福。
- 树在被**多会话并发写**。任何「已完成」宣称前必须重跑取证；任何失败先隔离复跑再判归属。

## 硬纪律（违反即事故）

1. **禁触**：`personas/`、`ChatBot_Runtime/`、`ChatBot_Archive/`、`.env`（且禁读明文）、`plugins/bot_unified_runtime/domains/weather/assets/qx.json`、以及一切台账外文件。发现台账外问题→登记，不顺手修。（例外已执行：用户 19:05 显式授权改 `.env` 中两条 `BOT_KNOWLEDGE_FILES` 路径，见总账 §八。）
2. **git**：禁 `git add -A`/`.`；逐文件显式 add；写操作只限用户授权范围（`webui/` + 本波裁定项）；不 push。
3. **零缓存**：直跑 python 必须 `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1` + `--basetemp` 指到**仓库外**（如 `../ChatBot_Runtime/cache/pytest_x/basetemp`）+ `-p no:cacheprovider`。`BOT_AUTOSYNC=1` 会重写 `docs/auto-facts.md`/`command-catalog.md`（本波已误踩一次）。
4. **禁 `doc_sync.py --write`/`command_catalog.py --write`**；`verify_hashes.py --write` 需按上述裁定逐条核对后才可用，平时一律 `--check`。哈希册 19 件（含 `docs/rendering-contract.md`、`DESIGN-SPEC.md`、`echo.py`、`renderer.py`）→ **改这些文档必红门**。
5. 审计行号是快照，动每条前用锚点串 grep 重定位。
6. 不重启生产 bot、不 kill 进程、不起长驻服务（本环境会回收）。
7. **`node --test` 套件必须自闭包**（只读 `webui/`）。跨前后端的对账关系住 pytest，那里 `pytest.skip` 是一等概念；住在 node 测试里等于把整道门绑在别人的未跟踪文件上（本波 CR-2 就是这么红）。
8. **子代理禁 `npm run build`**：`dist/` 是单一共享产物，并发构建互相覆盖。最终构建由主会话单点执行。

## 复跑基线（当前应全绿）

```bash
cd webui && npx tsc --noEmit -p tsconfig.app.json   # 0（**不要用 -b**：会往树里写 .tsbuildinfo）
cd webui && npm run lint:layout                      # 0，须含「自测 58/58」
cd webui && npm test                                 # pass 29 / fail 0
cd webui && npm run build                            # 0
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe \
  -m pytest tests/test_webui_constitution.py \
  -p no:cacheprovider --basetemp=../ChatBot_Runtime/cache/pytest_x/basetemp -q   # 5 passed
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe \
  scripts/runtime_layout_smoke.py                    # exit 0（.env 路径修复后）
```
门禁本体被改坏时**先修门再改代码**；门自测（`layout-constitution.mjs` 内建 58 例）红就是规则空转，不许用加豁免抹平。

## 待办（按优先级）

| # | 事项 | 备注 |
|---|---|---|
| 1 | 真后端跑一次 `python scripts/webui_acceptance.py --api http://127.0.0.1:8742 --token-env <环境变量名> --expect data` | **用户自己跑并贴输出**。新牙落地后从未在真数据下验过；`--token-env` 是为「明文不进 argv/聊天」加的（`a418292`） |
| 2 | 亮色 warn 新色 `oklch(0.516 0.1009 64.8)` 肉眼复核 | 对照图已重发给用户，**裁定仍挂起**。对比度是算术（`%TEMP%/f11b/f11b_contrast.py`，现 0 失败），观感不是 |
| 3 | 总账 §三 R-1~R-7 逐条裁定 | R-1 文档矛盾订正稿在 `F24-doc-reconciliation.md`，DOC1 席正在执行 |
| 4 | `SEARCH_SPECS` 归一洗参数的暗坑**升格为机器门** | 见总账 §八：任何页面把状态搬进 URL 必须往表里加行，否则深链回写时静默丢失，无报错无日志 |
| 5 | `F22-render-rollout-plan.md` 的 D1–D7 裁点后开工渲染域 | **顺序硬约束：先补哈希锁再动 `domains/render`**；`test_verify_hashes.py:92` 硬编码 `==19`，补锁必红，同批改 |
| 6 | 台账外新增条目回填 `AGENTS.md` 台账行 / `docs/HANDBOOK.md` | 按项目维护规矩：不再新建带日期交接文档，增量进 HANDBOOK |

## 本波教训（必须带走）

- **席位报的 P0 一律独立复测再动手。** 本波作废了两条自己报出的「P0」：①「SSE 端点 `/logs/live` 从未注册→实时日志从来没通过」——实测 `api-client.ts:481` 与 `events.py:88+131` 完全配平且有四处测试锁；②「改 warn 色值即可救回对比度」——算术上救回 0/5。可复跑命令才是证据，报告不是。
- **判据要能自证。** 只查 DOM 文本的门会为一页手写 HTML 出绿单；只查字面量、看不见 `twMerge` 真实折叠行为的版式门同理。所以本波给门加的是**自测例 + 行为锁**（`node --test` 跑真 `cn()`、假页必 FAIL、陈旧 dist 必拒跑），而不是更多文案断言。
- **正则的边界断言要用探针验，不能靠读。** 门规则② `OFF_LADDER_TEXT` 以 `\b` 收尾，作者以为覆盖了 `text-[13px]`，实测 `]` 之后永不构成词边界 ⇒ **括号臂自始空转**，而席位台账已背书其安全。收口宣称「覆盖 X」时，X 必须有一条"正样本变红 + 近似合法样本不变绿"的双向自测。
- **新工具会抓到前一批的交付。** 补牙之后评审员拿探针回扫，立刻揪出刚入库的两件（CR-1/CR-2）。这不是返工，这是门开始值钱。
- **canvas 字体不能用 CSS 变量。** `getComputedStyle` 对自定义属性回原文（`0.75rem`），而 Canvas2D `font` 只接受绝对长度——相对单位被静默丢弃后字号悄悄回到默认 **10px**。故 `theme-switch` 那类真 Tailwind 类可以回收成工具类，canvas 侧的 R5「走 readToken」建议必须驳回，宁可留着显性棘轮债。
