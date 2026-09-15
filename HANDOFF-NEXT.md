# 交接提示词（2026-09-15 午后 · 全量更正版 · 给下一个 AI）

> **你是谁**：守岸人 Bot 项目的新接手 AI。本文件是唯一交接入口，读完即可开工。
> 深读字典：`docs/HANDOVER-2026-09-15.md`（架构/流程/九个统一/WebUI 全量，按需查）；总账 `docs/HANDBOOK.md` §1-§27。

## 0. 一句话现状

代码与测试健康（测试/门禁现状一律以最近一次实跑与 `docs/auto-facts.md` 机器册为准，勿引手写计数）。09-14 六域批 + 09-14/15 夜间审计批（HANDBOOK §24-§26）+ 09-15 会话批已落库至 `6ac897b`：超时根修三连（连接分类+告警轨迹+预算 300s）、生产启动崩溃修复（`793e647`）、P2-4 五池守岸人文案、SETTABLE 41/31 诚实化、daily_assist、WebUI 规格（`331e2a2`）、**LLM 链路收敛 26 渠道 id→4 真模型名单组直连 axonhub（`.env` 已改，gitignored——证据=解析+三时刻命中实测+30 例回归）**。**生产 bot 未重启**——你的第一件事通常是提醒用户提权重启（§5）。工作树常态有并行代理在飞件（§6），先取证再收编、勿盲收盲删。

## 1. 项目 30 秒

QQ 聊天机器人「守岸人」（鸣潮角色人格，非 AI 设定），NoneBot2 + OneBot V11（NapCat，正向 WS 127.0.0.1:3001，token 见 .env）。主包 `plugins/bot_unified_runtime/`，运行数据全在 `ChatBot_Runtime/`（**兄弟目录，不可删改**），venv 在 `ChatBot_Runtime/venv/`。**完整项目说明读 `AGENTS.md`**（规则+架构+台账 33 行）——冲突时以 AGENTS.md 为准。LLM 全部经本地 axonhub 网关（127.0.0.1:8090/v1），bot 只发模型名（gemini-3.8-flash→gpt-5.6-terra→grok-4.6→deepseek-flash），渠道选择归 axonhub。

## 2. 硬规矩（违反即事故，先背下来）

1. **改代码必须重启 bot 才生效**；生产进程管理员权限运行，只有用户能重启。
2. **源码树零缓存**：绕过 dev.ps1 直跑必须 `PYTHONDONTWRITEBYTECODE=1`，pytest 加 `--basetemp="$TEMP/xxx" -p no:cacheprovider`。树里不许出现 `__pycache__/data/.pytest_cache`。
3. **`plugins/bot_unified_runtime/sources/data/qx.json` 是内置资产**（NMC 天气码表），任何清理不得动它（历史三次误删三次事故）。
4. **git**：禁 `git add -A/.`；逐文件显式 add；提交后 `git show --stat HEAD` 核对；**push 只在用户明确指示时**，refspec `refs/heads/v0.0.1-alpha.2:refs/heads/v0.0.1-alpha.2`。
5. **说"完成"必须有证据**：提交哈希或可复跑命令+实跑输出。测试/lint 结果必须实跑，禁编造。
6. **人格资产**（personas/）改前读 AGENTS 规则 8；守岸人语气红线写死在 affinity.py；面向用户话术一律走五池纪律（≥12 变体/官方语音文风/游标轮换，见 HANDOVER §统一⑤）。
7. **代理纪律**：按文件域互斥切分；代理禁 git 写、禁再派代理；并发上限受当日累计用量动态约束（高消耗日 2-3 即 1302，低消耗日 6-7）；弹回=串行自己做；代理阵亡先取证遗留（git diff+域测试）再收编。
8. 直跑 python 用绝对路径：`"C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe"`。

## 2.5 自动同步铁律（改一处，全局联动，漏一步测试门直接红）

| 你改了什么 | 必须联动 | 机制 |
|---|---|---|
| **HTML 模板/视觉 token** | 只准改 `theme_tokens.py`（单一事实源）；交付物字节变了必须 `python tests/verify_hashes.py --write` 重录（`--check` 常驻门） | 根部 `DESIGN-SPEC.md` + `docs/rendering-contract.md` |
| **命令/触发词/路由** | 改 `echo.py` 或 `base_router.py` 后必跑 `python scripts/command_catalog.py --write`（`docs/command-catalog.md`+`COMMANDS.md` 自动重生成） | 「一处修改，全局联动」用户裁定 |
| **清单/数字类事实** | `python scripts/doc_sync.py --write`——`docs/auto-facts.md` 整册机器重生成，**禁止手改** | 交叉验证机制·文档层 |
| **人格 personas/** | `python scripts/sync_persona_source.py --check`（改后 `--adopt` 重录）；哈希清单内文件改后 `--write` | 源-副本一致性机械门 |
| **热路径性能** | `tests/test_perf_regression.py` 常驻——超阈值直接红，**不许抬阈值**，先 systematic-debugging | 交叉验证机制·性能层 |
| **双引擎互证** | 大改后 `python tests/cross_validate.py`：默认引擎与隔离引擎结果必须一致 | 交叉验证机制·执行层 |

**口诀**：改模板→跑契约族；改交付物→`verify_hashes --write`；改事实→`doc_sync --write`；改命令→`command_catalog --write`；收尾→`cross_validate`。

## 3. 常用命令

```powershell
# 全量测试 / lint / typecheck（全绿是交付底线）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"
# 以下 python 指 §2.8 venv 绝对路径；真机验收（重启后）DRY-RUN 缺省
python scripts/e2e_acceptance.py --target-group <白名单群ID> --execute
python scripts/pre_restart_check.py        # 重启前置，全 PASS 再动手
python scripts/command_catalog.py --write  # 改 echo/base_router 后必跑
python scripts/doc_sync.py --write         # 机器事实册
python tests/verify_hashes.py --write      # 视觉交付物哈希
```

## 4. 已落库滚动清单（浓缩版）

- **全量总账**：HANDBOOK §24（六域批）/ §25（夜间审计批）/ §26（审查执行批）/ §27（daily_assist）+ AGENTS.md 台账 #31-#33。
- **09-15 会话批**（`dcb7b02..6ac897b`，30 笔可溯）：ack 回执根修 → control-plane Host 白名单（Critical）→ 决策痕迹持久化 → 夜间审计 20 笔（§25/§26）→ SETTABLE 诚实化 → 触发词双向机械门（218 缺口台账 `4252944`）→ daily_assist `da255b0` → P2-12 SSRF 收窄 → P2-9/P3 系批量修复 → 夜间总报告 `d7c55b7` → 启动崩溃 `793e647` → P2-4 文案 `ebe6843`+`97d0aa6` → WebUI 规格 `331e2a2` → 超时三根修 `12b7f4a` → 预算+五池 `6ac897b`。
- 旧批次明细按需查 HANDBOOK 对应 §，不在本文件复读。

## 5. 用户必须做的事（你只能提醒）

**提权重启生产 bot**——累积生效清单（全部已落库/已改配置，未重启零生效）：链收敛 4 模型 / 预算 300s / 五池文案 / 连接分类+告警轨迹 / TG 退避 / 启动崩溃修复 / SETTABLE / 夜间审计批全部。前置：`pre_restart_check.py` 全 PASS；顺序**先 NapCat 后 bot.py**（管理员）；重启后验收 acceptance-manual §6.6 族 + `measure_latency_chains.py all` 补在线延迟。另：campus 启用四步（launcher-school.bat 扫码→.env 填 BOT_CAMPUS_GROUP_WHITELIST→.env.prod 解注释 3002→重启）；X cookie 灌入后立即删除 Downloads 临时文件（含 auth_token）。

## 6. 在飞/待办（按优先级）

1. **工作树在飞四席**（以 `git status --porcelain` 实况为准）：campus（3 文件 untracked+台账行，提交裁决权在用户）/ glossary（glossary.py+两测试）/ sender 韧性（onebot+worker+media 拒收回退测试）/ persona 测试；另有 auto-facts.md 机器册重生成在飞（勿手收）。
2. **两处存量缺陷待立项**（campus 批调研发现）：群摘要读零行（shared_group.py session_id 口径错，21:30 静默空转）；推送路径未传 llm_provider（`BOT_GROUP_DIGEST_LLM_ENABLED` 推送侧恒不生效）。见台账 #33。
3. `/bot decision` 生产 `__init__.py` elif 接线未交付；触发词方向 2 全词族（已批未做）；方向 1 的 218 缺口待用户裁决。
4. **WebUI**：只探索不写码（用户裁定）；规格+需求全集+三阶段=HANDOVER §4。
5. 等外部：F7 cos 随机图（用户插件）；B5 沙箱/B14 用户 key；页脚头像（可选）。

## 7. 开工流程（三步）

1. 读 `AGENTS.md`（重点：第一部分规则、第六部分台账 #29-#33）+ 本文件 §2/§2.5；架构流程深读 `docs/HANDOVER-2026-09-15.md` §1-§3。
2. `git status --porcelain` + `git log --oneline -10` 摸清现场；未提交遗留先取证（跑对应域测试）再收编。
3. 跑一次 `dev.ps1 -Task test` 确认基线（提醒用户重启前跑 `pre_restart_check.py`），然后按 §6 顺序干活。**用户会说"继续"和"开 N 并发子代理"——照 §2.7 纪律执行即可。**
