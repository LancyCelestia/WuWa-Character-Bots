# 接手提示词 · 前端统一审计收尾波（2026-09-19）

> 用法：整段粘给新会话。**先读 `docs/design/unify-audit-20260919/FRONTEND-AUDIT.md`**（唯一读数入口），
> 席位对账单在同目录（27 份），只在需要某条的完整证据时才翻。

---

你是「守岸人 Bot」前端审计波次的接手者。工作区 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`，分支 `v0.0.1-alpha.2`。

## 现状（不要重述，要复核）

- 前端审计已完成 **6 项 P0 + 9 项 P1 修复**，总账：`docs/design/unify-audit-20260919/FRONTEND-AUDIT.md`。
- 已入库：commit **`a76cc2b`**（`webui/` 整树首次入库，43 件 / 8852 行，用户明确授权）。
- **未入库（工作树脏）**：`webui/` 的二批改动 + `tests/test_webui_constitution.py`、`tests/test_webui_stats.py`、`plugins/bot_unified_runtime/control_plane/metrics.py`、`scripts/webui_acceptance.py`、27 份席位对账单。后四者**从未在 git 里存在过**，整份文件是未跟踪新件且内容属其它波次——提交范围待用户裁（见下）。
- 树在被**多会话并发写**。任何「已完成」宣称前必须重跑取证；任何失败先隔离复跑再判归属。

## 硬纪律（违反即事故）

1. **禁触**：`personas/`、`ChatBot_Runtime/`、`ChatBot_Archive/`、`.env`（且禁读明文）、`plugins/bot_unified_runtime/domains/weather/assets/qx.json`、以及一切台账外文件。发现台账外问题→登记，不顺手修。
2. **git**：禁 `git add -A`/`.`；逐文件显式 add；**除用户明确授权的 `webui/` 外零 git 写**；不 push。
3. **零缓存**：直跑 python 必须 `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1` + `--basetemp` 指到**仓库外**（如 `../ChatBot_Runtime/cache/pytest_x/basetemp`）+ `-p no:cacheprovider`。`BOT_AUTOSYNC=1` 会重写 `docs/auto-facts.md`/`command-catalog.md`（本波已误踩一次）。
4. **禁 `verify_hashes.py --write`/`doc_sync.py --write`/`command_catalog.py --write`**，一律 `--check`。哈希册 19 件（含 `docs/rendering-contract.md`、`DESIGN-SPEC.md`、`echo.py`、`renderer.py`）→ **改这些文档必红门**，订正稿只能在授权后落。
5. 审计行号是快照，动每条前用锚点串 grep 重定位。
6. 不重启生产 bot、不 kill 进程、不起长驻服务（本环境会回收）。

## 复跑基线（当前应全绿）

```bash
cd webui && npx tsc --noEmit -p tsconfig.app.json   # 0
cd webui && npm run lint:layout                      # 0，须含「自测 37/37」
cd webui && npm test                                 # pass 14 / fail 0
cd webui && npm run build                            # 0
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe \
  -m pytest tests/test_webui_constitution.py tests/test_webui_stats.py \
  -p no:cacheprovider --basetemp=../ChatBot_Runtime/cache/pytest_x/basetemp -q   # 5 + 59 passed
```
门禁本体被改坏时**先修门再改代码**；门自测（`layout-constitution.mjs` 内建 37 例）红就是规则空转，不许用加豁免抹平。

## 待办（按优先级）

| # | 事项 | 备注 |
|---|---|---|
| 1 | **等用户裁定后提交第二批** | 范围含非 `webui/` 文件，超出已给授权，**不得自行提交** |
| 2 | 真后端跑一次 `python scripts/webui_acceptance.py --api http://127.0.0.1:8742 --token <用户提供> --expect data` | 新牙落地后**从未在真数据下跑过**；缺令牌就如实报告，不要自己翻 `.env` |
| 3 | 亮色 warn 新色 `oklch(0.516 0.1009 64.8)` 肉眼复核 | 对比度是算术（复算脚本 `%TEMP%/f11b/f11b_contrast.py`，现 0 失败），观感不是 |
| 4 | 总账 §三 R-1~R-7 逐条裁定 | R-1 是 13 处文档矛盾 + 8 条与实盘矛盾的宣称，订正稿在 `F24-doc-reconciliation.md`，执行需哈希重录授权 |
| 5 | `F22-render-rollout-plan.md` 的 D1–D7 裁点后开工渲染域 | **顺序硬约束：先补哈希锁再动 `domains/render`**；`test_verify_hashes.py:92` 硬编码 `==19`，补锁必红，同批改 |
| 6 | 台账外新增条目回填 `AGENTS.md` 台账行 / `docs/HANDBOOK.md` | 按项目维护规矩：不再新建带日期交接文档，增量进 HANDBOOK |

## 本波两条教训（必须带走）

- **席位报的 P0 一律独立复测再动手。** 本波作废了两条自己报出的「P0」：①「SSE 端点 `/logs/live` 从未注册→实时日志从来没通过」——实测 `api-client.ts:481` 与 `events.py:88+131` 完全配平且有四处测试锁；②「改 warn 色值即可救回对比度」——算术上救回 0/5。可复跑命令才是证据，报告不是。
- **判据要能自证。** 只查 DOM 文本的门会为一页手写 HTML 出绿单；只查字面量、看不见 `twMerge` 真实折叠行为的版式门同理。所以本波给门加的是**自测例 + 行为锁**（`node --test` 跑真 `cn()`、假页必 FAIL、陈旧 dist 必拒跑），而不是更多文案断言。
