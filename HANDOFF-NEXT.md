# 交接提示词（2026-09-13 晚 · 给下一个 AI）

> **你是谁**：守岸人 Bot 项目的新接手 AI。本文件是唯一交接入口，读完即可开工。
> 读完本文件后，按 §7 的「开工流程」三步走，不要跳过。

## 0. 一句话现状

代码与测试全部健康（全量 4623+ passed / lint / typecheck 全绿），今天两批大改动**已全部提交但生产 bot 未重启**——你的第一件事通常是提醒用户提权重启 bot（见 §5），然后做 §6 的在飞任务收尾。

## 1. 项目 30 秒

QQ 聊天机器人「守岸人」（鸣潮角色人格，非 AI 设定），NoneBot2 + OneBot V11（NapCat，正向 WS 127.0.0.1:3001，token 见 .env）。主包 `plugins/bot_unified_runtime/`，运行数据全在 `ChatBot_Runtime/`（兄弟目录，**不可删改**），venv 在 `ChatBot_Runtime/venv/`。**完整项目说明读 `AGENTS.md`**（规则+架构+台账 30 行）——它与本文件互补，冲突时以 AGENTS.md 为准。

## 2. 硬规矩（违反即事故，先背下来）

1. **改代码必须重启 bot 才生效**；生产进程管理员权限运行，只有用户能重启。
2. **源码树零缓存**：绕过 dev.ps1 直跑必须 `PYTHONDONTWRITEBYTECODE=1`，pytest 加 `--basetemp="$TEMP/xxx" -p no:cacheprovider`。树里不许出现 `__pycache__/data//.pytest_cache`。
3. **`plugins/bot_unified_runtime/sources/data/qx.json` 是内置资产**（NMC 天气码表），任何清理不得动它（历史三次误删三次事故）。
4. **git**：禁 `git add -A/.`；逐文件显式 add；提交后 `git show --stat HEAD` 核对；**push 只在用户明确指示时**，refspec `refs/heads/v0.0.1-alpha.2:refs/heads/v0.0.1-alpha.2`。
5. **说"完成"必须有证据**：提交哈希或可复跑命令+实跑输出。测试/lint 结果必须实跑，禁编造。
6. **人格资产**（personas/）改前读 AGENTS 规则 8；守岸人语气红线写死在 affinity.py。
7. **代理纪律**（用户常要求 2 并发子代理）：按文件域互斥切分；代理禁 git 写、禁再派代理；**并发上限受当日用量约束**（高消耗日 2-3 并发即被上游 1302 弹回，弹回=串行自己做，不要硬重派）；代理阵亡先取证遗留（git diff + 跑域测试），能收编就收编。
8. 直跑 python 用绝对路径：`"C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe"`（shell 里相对路径会因 profile 报错）。

## 2.5 自动同步铁律（用户核心要求：改一处，全局联动，一处都不许漏）

这是本项目最重要的机制，**任何改动必须走对应的联动流程，漏一步测试门直接红**：

| 你改了什么 | 必须联动 | 机制 |
|---|---|---|
| **HTML 渲染模板/视觉 token** | 视觉值只准改 `theme_tokens.py`（token 单一事实源），模板只准 `var()`/注入引用——**改 token=全模板自动生效**；模板结构改动后跑渲染契约族测试；交付物（6 模板+theme_tokens+契约文+DESIGN-SPEC 等 12 文件）字节变了必须 `python tests/verify_hashes.py --write` 重录 SHA-256（`--check` 已是 pytest 常驻门，漏录直接红） | 根部 `DESIGN-SPEC.md`（设计/执行/验证三规范）+ `docs/rendering-contract.md` |
| **全项目代码/命令/触发词** | 改 `echo.py`（帮助注册表/触发词）或 `base_router.py`（路由）后必跑 `python scripts/command_catalog.py --write`——`docs/command-catalog.md` 与 `COMMANDS.md` 自动重生成，漏跑 `test_catalog_document_matches_registry` 红 | "一处修改，全局联动"用户裁定 |
| **文档中的清单/数字类事实** | 代码变了跑 `python scripts/doc_sync.py --write`——`docs/auto-facts.md`（模板清单/RouteKind/帮助 topic 数/测试文件数/配置键数）整册从代码重生成，`--check` 常驻门；**该册机器所有，禁止手改** | 交叉验证机制·文档层 |
| **设定/提示词/人格**（personas/） | 无机械门（叙述类人工维护），但 `identity.md` 等已在哈希清单内的文件改后同样 `--write`；话术红线见 AGENTS 规则 8 | 人工纪律+哈希兜底 |
| **热路径性能** | `tests/test_perf_regression.py`（pytest 常驻）：路由吞吐/导入时长超数量级阈值直接红——**不许抬阈值**，先 systematic-debugging 定位 | 交叉验证机制·性能层 |
| **双引擎交叉验证** | 提交前/大改后跑 `python tests/cross_validate.py`：同一套测试默认引擎与隔离引擎各跑全量，结果必须一致，不一致=环境耦合缺陷 | 交叉验证机制·执行层 |

**记忆口诀**：改模板→跑契约族；改交付物→`verify_hashes --write`；改代码事实→`doc_sync --write`；改命令→`command_catalog --write`；动性能→`test_perf_regression` 说话；收尾→`cross_validate` 互证。**全部 `--check` 形态已进全量测试门，漏一步全量必红**——这就是 SHA-256 哈希、pytest、延迟/性能测试的常驻形态。

## 3. 常用命令

```powershell
# 全量测试 / lint / typecheck（各约 1-4 分钟，全绿是交付底线）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"
# 真机验收（bot 重启后）：DRY-RUN 缺省，--execute 真发
python scripts/e2e_acceptance.py --target-group <白名单群ID> --execute
# 性能基线 / 渲染样本 / 命令目录 / 机器事实册 / 哈希清单
python scripts/measure_latency_chains.py all
python scripts/command_catalog.py --write     # 改 echo.py/base_router.py 后必跑
python scripts/doc_sync.py --write            # 机器事实册（--check 已进测试门）
python tests/verify_hashes.py --write         # 视觉交付物哈希（--check 已进测试门）
python scripts/clean_food_gallery.py --execute  # 图库污染清理（VLM 复判）
```

## 4. 今天（09-13）已落库的东西（都在 git log 里，哈希可溯）

- **媒体归档能力**（bot.media_archive：发媒体+收藏/归档→VLM 判类别×IP 落盘；台账 #28）。
- **vis2r 社媒卡六项修复 + vis4 视觉体系**（台账 #29）：层次阴影三级族/辉光/分隔线/三档本命色表面，全部钉在 `theme_tokens.py`——**改视觉先改 token，一处改全模板生效**；根部规范 `DESIGN-SPEC.md`（设计/执行/验证三合一，已入哈希清单）。
- **交叉验证机制**：哈希清单+性能门+机器事实册+双引擎互证（`tests/verify_hashes.py` / `test_perf_regression.py` / `scripts/doc_sync.py` / `tests/cross_validate.py`）。
- **股价链路**：push2his 瞬断重试、成交量/流通股等指标、公司 logo 色/域名、标题中文化（台账 #29③）。
- **账单家族合并**（三行 gemini 并一行）+提醒过期治理（修 13 点报 23 点）。
- **搜图回复触发/失败分类、识图群最近图、澜汐=霞月双名钉死+昵称学习护栏、Bot 头像本地缓存（重启后自动从 qlogo 拉）、历史上的今天多历法、LLM 告警 attempts 真实化+detail 自解释**。
- **WinError 1225**：bot.py 启动预检（NapCat 没开时人话提示，不是代码 bug）。

## 5. 用户必须做的事（你只能提醒）

**提权重启生产 bot**——不重启，以上全部不生效。重启顺序：**先 NapCat 后 bot.py**（管理员）。重启后验收：`acceptance-manual.md` §6.6（九项卡面）/§6.6.1（触发五表）/§6.6.2（媒体归档六项）；再跑 `measure_latency_chains.py all` 补 NapCat/Mail/TG 在线延迟（此前 unreachable）。

## 6. 在飞/待办（按优先级）

1. **时间窗总结**（代理可能已交付）：history 时间窗查询+"总结 N 分钟内消息"→注入 chat 总结。验证：`pytest tests/test_time_window_summary.py`。
2. **图库清理收尾**（代理在飞）：查 `ChatBot_Runtime/data/food_images/library.sqlite` 行数（首轮 53→42）+`%TEMP%/food_quarantine_20260913/` 隔离数；二轮 `--execute` 兜 VLM 瞬时失败；eat.py 入库防污染加固。
3. **全卡 vis4 迁移**：其余 5 模板+f-string 卡照 DESIGN-SPEC 迁（universal_card.html 是范本）。
4. **e2e 实战自测增强**：e2e_acceptance.py 加命令矩阵+响应收集+私聊报告+离线 selftest。
5. 23:00 定时任务（automation-4ee2c3bf）：按 `docs/perf-optimization-plan.md` §三执行渲染 Phase 2 接线——若该任务没触发，手动照文档做。

## 7. 开工流程（三步）

1. 读 `AGENTS.md`（重点：第一部分规则、第六部分台账 #26-#30）；
2. `git status --porcelain` + `git log --oneline -10` 摸清现场；若有未提交遗留，先取证（跑对应域测试）再收编；
3. 跑一次 `dev.ps1 -Task test` 确认基线全绿，然后按 §6 顺序干活。**用户会说"继续"和"开 N 并发子代理"——照 §2.7 纪律执行即可。**
