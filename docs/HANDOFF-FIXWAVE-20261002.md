# 交接：一次性修复波 2026-10-01→10-02（波次被用户中途叫停时的终态）

> **本件性质**：这是「波次被叫停」的现场交接，**不是** §59 那种自然收官账。波次的自然账在 `docs/HANDBOOK.md` §59；本件补 §60 该写但因**另一会话正在写 `docs/HANDBOOK.md` 与 `AGENTS.md`**（同面并发，见"七、待用户裁"第 5 条）而没能并进去的部分。
> 之所以另开文件而不改 HANDBOOK/AGENTS：① `AGENTS.md` 现 29,985 B，软顶 30,000（规则 10/体积顶），加一行即顶门；② HANDBOOK 工作树被别席占着，我追加会吞别席的 hunk（台账 #70★ 实锤过）。**下一窗请把本件整段并入 HANDBOOK §60 后删除本件**，并在 AGENTS 接手入口加一行指针（那次要顺带做 P9.8 的体积压缩）。
> 判据一律给**可复跑命令**，不写会过期的手抄数字（规则 10）。文中出现的数字全部标"当时值"。

---

## 一、给用户的三句话

1. **bot 能用，且新代码已经在跑**（10-01 17:50:32 起，PID 15992 听 8080），本轮九笔改动里除"最后那半截亲密模式"之外都已生效。
2. **备份已经能用了**：GitHub private 仓 tip `e60ae76` 与本地 HEAD 逐字相等；离线另有一枚**重打过**的 bundle（旧那枚是 15:34 生成的，**不含整个修复波**，差点是假备份）。
3. **叫停点上的残局是"30 个在飞面没收笔"**，不是"东西丢了"——全部在工作树里，逐面清单与"差什么"在第四节，照那张表可以一席一席接着做。

---

## 二、已入库账（9 笔，全部已推送；`git log --oneline 5d581b2..HEAD`）

| 哈希 | 门 | 一句判据（当时值，可复跑） |
|---|---|---|
| `ac81b8c` | P5-1 事件循环 | 根汇口不再按名单选路；`test_pipeline_offload_always` 10 passed；seam 家族 56 passed |
| `14563d5` | P5-9 队列 | 整表剪枝 8.308ms→0.290ms（语句级 28.7×）；`test_queue_prune_index_lock` 532 行 |
| `fd395d3` | P7 汇率 | 三态名册 RUB/CHF/CAD/AUD=pending；`test_fx_currency_coverage` 60 passed |
| `0ba954a` | P7 新闻 | 源白名单门 24 passed；UGC 除名且"回潮即红" |
| `6fe46f0` | P6-5 称谓 | 两处重复禁令并回 `addressing.py`；新门 25 passed |
| `342dd48` | P5-8 无界资源 | HTTP 池封顶 8 桶 + 嵌入 memo 真 LRU 256（6373 轮 p99=2 背书） |
| `c0d1d29` | P3-10/11/12 | 邮件四枚 skip→真身（HEAD 副本 143+4skipped → 工作树 144+0）；`"super"` 死判据根修 |
| `2995b0a` | P1 门禁尾债 | runtime-layout 扫面扩四类；落地当场抓出 2 枚真残留＝自证有牙 |
| `e60ae76` | P6-2/6-3 文案 | 41 码→10 族壳×15 变体；gate 24 passed；未打补丁 HEAD+新门＝9 failed（注毒铁证） |

**这四笔是"用户点名之外的额外收获"**：`ac81b8c` 修的是上一波只修半截的事故级洞（见第五节 ①），`2995b0a` 让门禁第一次真能看见 ignored 残留。

复跑配方（本波全程用它，写死）：
```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 <Runtime>/venv/Scripts/python.exe \
  -m pytest -p no:cacheprovider --basetemp="$TEMP/qoder-<席>/bt" -q <目标>
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 -Task lint|typecheck|runtime-layout
```
三门现值（叫停点）：**lint 35 红 / typecheck 5 红 / runtime-layout PASS**。红全部落在别席在飞件上（typecheck 只两枚文件：`quirks.py` 4 错＝席 D2b 半成品、`db_backup.py` 1 错＝席 X1c 半成品）⇒ **HEAD 是干净的，红来自未入库的工作树**。

---

## 三、用户点名的两处缺陷：进展与准确定位

### ① 群聊「亲密模式」开关不可用 —— 已定位并修好一半，剩一格
- **真身（席 D1 查、主会话独立复核 reviewer.py 两处门后采信）**：`chat.py` 手动开关的回执分支把 `privacy_level` **硬写成 `PrivacyLevel.PERSONAL`**，而其余出口一律交 `context.privacy_level`。出站审核处有一道门禁止"个人级正文发往群作用域"⇒ **钉上了、模式上了，回执被换成兜底文案**，群内观感＝"开关没反应"。
- **被证伪的三条假设（别重复劳动）**：(a) 群白名单为空——非空；(b) 覆盖册 `config_overrides` 空值罩住它——那 9 枚键里根本没有 content-route 相关键；(c) `content_route_config` 没注入——注入点在 `pipeline/backend_unit.py:144` 且有在飞接线锁。三条都是我先排给席的，**排错了优先级**，已记在 `.superpowers/sdd/2026-10-02-fixwave/progress.md`。
- **剩的一格**：`tests/test_intimate_group_switch_delivery.py` 11 passed / 1 failed。红在**档号**那一格（浅/深档在群成员腿上的语义），前席已把 `mode == intimate` 那格跑绿。接手席 **D1b 在飞**；要判的是"产品错（深开没落档）还是测试错（期望常量用错）"，不许为变绿放宽。
- 在册不许回潮的历史缺陷：`chat.py` 注释「旧实现把 intimate 钉落到群键＝泄漏给全群」，新锁里有专门一发作反向不误伤。

### ② 「数据库也没有更新」—— 已排除一大类，真身收敛到写侧留痕缺失
- 主会话 read-only 普查现算：**12 枚库此刻仍在写**（`user_affinity`/`wuwa_history`/`emergency_info`/`meme_library`/…）⇒ **"整库不写"这一大类已排除**，bot 活着、写路径整体没坏。
- 集体停更三枚：`control_plane_config.sqlite3`（10-01 01:38:51）、`reply_policy.sqlite3`（01:18:01）、`persona_quirks.sqlite3`（01:18:01）——**都停在 17:50 那次重启之前约 23 小时**。
- **关键旁证**：`config_audit` 最后一行是 `version=14 / created_at=2026-09-27T15:03Z`，而文件 mtime 是 10-02 00:49 ⇒ **"文件被写过"与"审计没新增"同时成立**。两种解释待分：写侧绕过审计腿，或那些写根本不是落库写（开放式连接 touch）。
- 接手方向＝给这三枚补**写入留痕**（新真身 `domains/core/write_trace.py`，四档 `ok/noop/refused/failed`），让"该写没写"从此可机械判定；⚠ 读这库时列名是 **`value_json` 不是 `value`**（读错会全判空、误判成"覆盖册是空的"）。
- **在册未闭线索要先查**：台账 #56★「`get_or` 不读 Config、K-1 绕咽喉」。
- 接手席 **D2b 在飞**（前席 D2 150 轮到顶中止，`quirks.py` 留了 4 枚 `F821`：只 import 了 `OUTCOME_FAILED/NOOP/OK` 却用了 `OUTCOME_REFUSED`）。

---

## 四、叫停点残局：30 个未入库面，逐面"差什么"

**这些文件都在工作树里，一个字没丢。** 归属按我在 diff 标记里读到的席位号写；标"归属未核"的是我没逐块验证过的，接手时**先按 #70★ 用 hunk 内容认领**。

| 面 | 席 | 状态 | 差什么才能提交 |
|---|---|---|---|
| `control_plane/config_store.py`、`core/write_trace.py`、`character/quirks.py`、`character/reply_policy.py`、`tests/test_store_write_trace_d2.py` | D2b | 半成品 | 补 `quirks.py` 的 4 枚 `OUTCOME_REFUSED` import + 4 枚 RUF100（**逐枚判，BLE001 若仍被豁免就别摘**）+ 2 枚红锁。⚠ `reply_policy.py` 同时含已入库席 N1 的超管 hunk 与本席 WriteTrace hunk ⇒ 收笔后**同批**提交，别只提一半 |
| `runtime/db_backup.py`、`half-done/test_db_backup.py.HALF-WRITTEN` | X1c | **测试件被写到一半**（`class TestHonestyAndFail Loud:` 语法错，会让整棵测试树无法 collect，我已移到 `.superpowers/sdd/2026-10-02-fixwave/half-done/`，**不是删除**） | 从该文件 673 行处续写或重写；补接线 file:line 证据；补 1 枚 mypy 错；工单 |
| `chat.py`、`tests/test_intimate_group_switch_delivery.py` | D1b | 11/12 绿 | 上面第三节那格的裁定 |
| `llm_engine/prompt_template.py`、`tests/test_prompt_template_layer_w1.py`、6 条腿（`media_archive`/`memory_extract`/`reflection`/`timetable`/`llm_draft`/`file_exchange`） | W1 | 3 枚红 | `test_parts_legs_zero_byte_delta[media_archive.vlm]`、`test_wrapper_is_the_central_primitive_byte_for_byte`、`test_poison_missing_slot_raises`——本席判据核心是"收编前后送进模型的文本逐字节不变"，**红没解完就不许提** |
| `tests/test_migration_status_assignment_gate.py` | G1c | 1 枚红 | `test_status_is_not_derived_from_control_plane`（这把尺是 P8"零旁路"能不能被证明的前置物） |
| `tests/test_claims_subset_implementation_gate.py` | G1 | 第一把尺绿 | 工单没写（前席 150 轮到顶）；违规差分表在测试输出里，要落成文字册 |
| `tests/test_command_admin_gate_registration.py`、`patches/P3A-ROUTE-GATE-PROPOSAL-20261002.md`（305 行） | P3a | 绿 | **提案没落**：`/bot route`、`/bot routes` 补门要动 `__init__.py`+`echo.py`（主会话面），照那份 305 行工单执行 |
| `media/capabilities/tts.py`、`media/voice_enricher.py`、`tests/test_tts_cache_quota_shape_guard.py`、`tests/test_download_artifact_container_gate.py`、`patches/B1-CONFIG-REQUEST.md` | B1 | 两把锁绿 | 按 B1-CONFIG-REQUEST 落四面（`config.py`+`settings.py`+`.env.example`+`config-catalog`），**只补一面必红另一面**（#68★） |
| `runtime/deadline.py`、`runtime/capability_protocols.py`、`tests/test_timeout_umbrella_remaining_legs.py` | V1 | 绿 | 计时伞若必须落 `pipeline.py` 则它在飞；核 TTS 段是否真进伞（在册读数：叠加上限≈580s ≫ 90s） |
| `personas/shorekeeper/imagery_families.txt`、`runtime/aliases.py`、`tests/test_seat_t1_persona_contract_20261002.py` | T1 | 绿 | 复核"族数读出非空"（此前实跑读出**族数 0**＝意象去重静默失效）；`voice.tts_refs` 幽灵字段要么接要么撤 |
| `docs/db-owners.md`、`tests/test_db_owners_coverage.py` | X2 | 未收 | 登记与扩门**必须同批**（#68★）；普查数字以实跑为准 |
| `tests/test_config_key_registration_ledger.py` | Z1（**别的会话**） | 在飞 | 别动，那是别席的地板双向边界腿 |
| `AGENTS.md`、`docs/HANDBOOK.md`、`docs/auto-facts.md` | 别的会话 | 在飞 | 别动（见第七节 5） |
| `nonebot.py`、`files/capabilities/download.py`、`ops/admin/runtime_admin.py`、`tests/test_nonebot_sender.py`、`test_reply_policy_*`、`test_reply_style_imagery_default.py`、`test_voice_hook_error_card_leg.py`、`test_prompt_*` | **归属未核** | 未知 | 接手时逐块 `git diff` 认领；不确定就当别席在飞，不要提 |

🔴 **一条纪律**：叫停时**没有任何一席执行 git 写**（席位禁 git 写是硬约束），所以上表所有面都还在工作树。这就是为什么"叫停"没有造成损失——**代价只是没入库**。

---

## 五、探索成果（本波新学，别在下一窗重新发现一遍）

① **上一波"事件循环下放"只修了半截**。执行路径的选择权不在管线、在**根汇口**：`__init__.py` 一直按 `capability_id in OFFLOADED_CAPABILITY_IDS` 二选一，名单外的一枚同步命令走 `pipeline.handle` ⇒ 正文与完成腿都在事件循环线程上。现算点名：`/bot recent`（三份 SQLite 反查）、`/bot queue`、`/bot logs`、`/bot runtime`（热改态 `os.replace` 落盘）、`/bot setup llm`（引导卡渲染）**全在名单外** ⇒ 低频管理命令一按就冻整片会话。已修（`ac81b8c`），完成腿 `_complete` **刻意仍直呼循环**——`SendQueue.submit` 的认领台账按 `current_task()` 记账，搬进线程会静默吃掉登记（A-22 在册坑）。

② **被 `.gitignore` 吞掉的空目录能制造红**。源码树里一枚空的 `Bot_Character_Bots.egg-info/` 让 `importlib.metadata` 优先认领到一个**无 Version 的 distribution** ⇒ `_plugin_version()` 返回 `None`、错误卡版本行塌掉、连带三枚 `test_error_report` 红。仓库外基线副本**没有**那枚目录 ⇒ 基线一直比在飞树干净，我用基线读数解释在飞树的红＝**整套归因错**。已把这类可见性做进门（`2995b0a`）。

③ **"门绿"要问绿的是哪棵树**。同一把尺在两棵树上跑，环境差异（ignored 残留 / 空目录 / `*.egg-info` / `.venv` 骨架）会让基线更干净或更脏。本波树里还发现一枚**空壳 `.venv/`**（0 枚文件、只有空目录，09-30 清空事故留下的骨架）——半具身的 venv 正是让工具以为"这里有解释器"的东西，已由新门报出并清掉。

④ **后台/长命令的退出码只能从命令本身取**。两次"push 成功"都是假的：`… | tail -4; echo EXIT=$?` 取的是 `tail` 的码；真退出码 124 是**我自己设的超时**砍断了合法传输。第三次取证＝`Get-Process` 现算四枚 `git` + 一枚 `git-credential-helper-selector` 挂满 60 分钟、CPU≈0、日志 **0 字节** ⇒ 卡在**交互式凭据 GUI**，压根没在传。非交互配方（已验证可用）：
```
GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never git \
  -c credential.helper= \
  -c 'credential.helper=!"<PortableGit>/mingw64/bin/git-credential-manager.exe"' \
  push --porcelain origin refs/heads/<分支>:refs/heads/<分支>
```
先 `-c credential.helper=`（空值）清空名册——仓内首枚是 `helper-selector`，多账号时弹 GUI；再单挂一枚 helper；并先 `push --dry-run` 验通路。**成功判据＝`git ls-remote` 远端 tip 与本地 HEAD 逐字相等**，不是"命令没报错"。

⑤ 🔴 **`git commit -- <paths>` 在本仓失灵过一次，且是**静默**失灵**：我点名的 12 枚工作树路径**一字未入**，index 里 5 枚已 staged 的**别的路径**却整批发走（＝"按 pathspec 提交"名义下的纯 index 提交）。**但我补做了对照实验**：仓库外新建干净小仓、同机同版（`git 2.52.0.windows.1`）、同一形状 ⇒ **完全按文档办事**。⇒ 结论只到"本仓发生过、成因未查明"，**不得写成 git 版本论**（我第一版账就写成版本论了，当天自我推翻，见 `b083931`→`5d581b2` 两笔相邻 commit）。**换掉的正道**：`git add -- <显式路径>` → **`git diff --cached --name-only` 逐枚核对等于本批清单** → 裸 `git commit -F <文件>` → `git show --stat HEAD` 复核。防吞他席靠"提交前核对暂存面"，不靠 pathspec。

⑥ **提交信息里绝不能用反引号**（本窗咬我两次）：`git commit -m "… \`git commit -- <paths>\` …"` 在 bash 双引号里会**真的执行**那段命令替换，后果＝信息里出现空洞、甚至把一段 `git show` 输出整块灌进提交信息（`b083931` 之后就有一笔信息已不可读，按"不改史"纪律留着）。**长/含符号的信息一律走 `-F 文件`。**

⑦ **150 轮是子代理的硬天花板，会把活写到一半**。本波 8 席里有 6 席是被这个上限掐掉的，且**掐在写文件的中间**（`test_db_backup.py` 停在 `class TestHonestyAndFail Loud:`、`quirks.py` 停在半套 import）。⇒ 下一窗派席的正确形状＝**一席一件可独立提交的事**，别把"实现+扩门+改文案+对账"四件打包给一席。本波我把 3 件打包给 N1，它死在 A/B 前，我按 diff 自己复核了它的三件（结论都在，只差工单）。

⑧ **席位返回丢失 ≠ 活没干**（再证一次）：X1/X4 报"Queuing failed"其实**一行没写**；X4b/E1/Q1/F1/F2/S1/R1 报失败或成功但**盘上有全套产物**。补派前必须先读盘，否则会重复劳动或覆盖别人成果。

⑨ **退役残留会被 git 自己写回来**：`capabilities/auto_send/__init__.py` 旧布局路径**仍在树内且被 HEAD 跟踪**（mtime 09-30 15:48，本波没人碰它），`test_copy_redline_gate::test_gate_scope_sanity` 因此红，且**在仓库外 HEAD 副本上同样红**（原因相反：那边缺别的 shim）⇒ 这是一枚**跨窗既存红**，属计划里 P9.3「`capability.auto_send` 退役残留四件同批退役」。教训：**退役要"文件 + `SHIM_ROWS` 行 + 牵动的地板/链接/只读面登记"同批动**，只动一边必红另一边，而且还原类操作会把它连账本行一起写回。

⑩ **注入载荷已第四、第五枚，且升级了**。前三枚见 HANDBOOK §53.9（P-56、`fe6e30f8…`、`9f3c0d5e…`）。本窗：**第四枚**＝席 Y1b 遇伪 `grep -n` 文件行 ≥15 次并**伪造工具结果外壳**（假 `Exit code 1`／假 `no output`，顶掉一次真实 `git status` 读数）——别会话已登记；**第五枚**＝席 E1 报"假 Edit 成功／假 pytest 末行／假『无需修改』"。已固化的对策＝**关键读数一律先落仓外文件再 `Read`，别信回显**；E1 另登记一次非注入的工具环境故障（后置安全扫描 hook 自身 Go 二进制 OOM 崩溃 `pageAlloc: out of memory`）——判据是"编辑实际落盘"而非回显，它没因此改判据也没停手，处置正确。

---

## 六、项目架构（30 秒版，够下一窗认路）

- **产品**：QQ 群机器人「守岸人」（鸣潮角色人格、非 AI 设定）。**NoneBot2 + OneBot V11**（SnowLuma 转发 WS 3001/3002、webhook 8080），另有 Telegram / Mail / Console 三个渠道。主包 `plugins/bot_unified_runtime/`，单一 `Config` 类全 pydantic。
- **两个根**：代码＝本仓；**运行数据＝仓库外 `ChatBot_Runtime/`**（venv / 全部 SQLite / FAISS / cookie / 日志 / 缓存 / 覆盖册）。`scripts/runtime_paths.py` 把相对 `data/` 重映射过去。**`data/` 里再出现东西就是污染源**（本波两次踩到）。
- **人格资产**：`personas/shorekeeper/` 与 Runtime 里的副本是项目灵魂，话术改动必须守语气（规则 8）；好感度任何档位**不攻击/不强硬**。
- **入口文件族**：`bot.py`（启动+崩溃守卫）、`AGENTS.md`（唯一入口，规则/地图/索引，**顶门**）、`docs/HANDBOOK.md`（单一活文档，各波全账）、`docs/auto-facts.md`（机器册，一切会漂移的计数以它为准）、`docs/command-catalog.md` + `COMMANDS.md`（命令册生成物）、`docs/db-owners.md`（SQLite owner 清单，与 `config.py` 双向锁死）。
- **四道门**：`scripts/dev.ps1 -Task test|lint|typecheck|runtime-layout`（任务表 `scripts/chatbot-tasks.json`；它自己设 `PYTHONDONTWRITEBYTECODE=1` 与 `PYTHONPYCACHEPREFIX`，所以**绕开它直跑 python 才是污染源**）。
- 逐模块细节看 HANDBOOK 与 `docs/boards/`；**本件不抄计数**（规则 10）。

---

## 七、消息处理流程与"统一调度层"完成度

主链路（**流程图真身在 `AGENTS.md` 第三部分**，本件不重画、只标完成度）：

```
QQ/SnowLuma(WS) → bot.py → __init__.py 摄取（段归一/引用链反查/语音预转码/TG file_id→字节）
 → IncomingMessage → 路由 base_router ‖ decision（shadow，默认不接管）
 → 门禁 policy/gate（黑白名单/安静时间/限流/搭话好感门）
 → RuntimePipeline.handle_async → _prepare（全部门禁，幂等 claim 在最后 A-18）
 → 能力正文【下放】→ _complete（审核→TTS 钩子→渲染→合并转发→send_queue.submit）
 → worker 排空 → _deliver_transport_send_request → onebot/nonebot/mail → QQ/TG/邮件
```

**完成度自评（分档，⚪未动 / ◐半 / ●达标）**

| 档 | 状态 | 还差什么 |
|---|---|---|
| 摄取归一到单一 IncomingMessage | ● | — |
| 门禁唯一入口（`_prepare`，claim 殿后） | ● | — |
| **能力正文一律离开事件循环** | ●（本窗 `ac81b8c` 真修） | 完成腿 `_complete` 按 A-22 **刻意留在循环**，这是设计不是洞 |
| 出站唯一闸（`send_queue.submit`） | ◐ | 仍有直呼点；册子在 `domains/core/decision/outbound_registry.py` |
| **`MigrationStatus` 可被现算证明** | ⚪→◐ | **69 枚全 `LEGACY`、`TAKEOVER_READY/TAKEN_OVER` 全仓从未赋值 ⇒ "零旁路"根本无法证明**。赋值门第一版有 1 枚红（`test_status_is_not_derived_from_control_plane`）。这把尺不立起来，P8 整段无法验收 |
| TTS 进中央计时伞 / 进调度 | ◐ | 合成段是否真进伞待核（在册读数：叠加≈580s ≫ 90s）；配音钩子已走 `asyncio.to_thread` |
| 告警真带外 | ⚠ 席 X10 在飞 | 写死 `adapter="onebot"`＝与病人共用一条血管；`network_patrol` 那句"需带外"要么实现要么撤宣称 |
| 主动投递/订阅正文穿审核与渲染 | ⚪ | P8-1/P8-2 未动 |
| 监督自愈（崩溃重启） | ⚠ 席 X7 在飞 | `BOT_SUPERVISE` 三处 env 计数均 0 ⇒ 现网崩溃零自愈 |

**复跑口径**（判"零旁路"进度用这把尺，别用手抄数）：
```
<python> -c "…从 outbound_registry 现算 verdict 分布与 MigrationStatus 分布…"
grep -rn "MigrationStatus\." plugins/bot_unified_runtime | wc -l
```

---

## 八、物理文件归类进度（P9）

| 项 | 状态 |
|---|---|
| 过程日志 `*-log.md` 迁 `.superpowers/`（`docs/design/` 约 127 枚） | ⚠ 席 H1 在飞；**交付形态＝只出逐枚清单+目标路径+牵动的链接/归属账，不许真移动**（席位无 git 权，`git mv` 归主会话） |
| `.qoder/settings.local.json` 取消跟踪 + 补 ignore | ⚪ |
| `capability.auto_send` 复活件四件同批退役 | ⚪（见第五节 ⑨，**已知会让一枚门跨窗红**） |
| `SHIM_ROWS` 补漏记（域外待退役 23 vs 账上 15） | ⚪ |
| `url_cleaner.py` 死件处置；`subscription_watcher.py` **不可删**（被板块页按名引用） | ⚪ |
| 13 个空目录 + `cb-w9chk/` + `run.txt` | ◐ 本窗已清（备份到 `%TEMP%/qoder-hygiene-20261002/`，含 md5 对照） |
| `.gitignore` 死规则清理（`research/*` 11 处、旧家 2 处） | ⚪；🔴 `qx.json` 本体绝不可碰（NMC 塌向 open-meteo 的前车） |
| `AGENTS.md` 压回 30,000 以下 | ⚪ 现 29,985 B，**且此刻被别会话占着，我一个字没加** |

---

## 九、功能说明与实现的耦合（帮助册宣称 ⊆ 实装）

- **门已存在（本窗入库）**：`tests/test_error_copy_pool_gate.py` 的池计数/槽位/reason 实参形态/取句形态五层；`tests/test_news_source_whitelist.py` 的名册外域名即红；`tests/test_fx_currency_coverage.py` 的凭据册（无实测凭据的 secid 进宇宙表当场红）。
- **第一把尺绿、第二把尺差一红**：`test_claims_subset_implementation_gate.py`（宣称集合 ⊆ 实装集合）15 发绿；`test_migration_status_assignment_gate.py` 差 `test_status_is_not_derived_from_control_plane`。
- **已登记、未改的文案越权（都在别席独占面）**：
  - `echo.py` + 生成物 `command-catalog.md` 手写"覆盖 11 币种"已过期（实装在册 15 / sourced 8，**当时值**）。
  - `/bot decision` 在册但无分支（`DANGLING_VERB_CAPABILITIES_BASELINE`）；订阅音乐 5 平台谎报；酷我/Spotify 搜索桩；`capability_registry:390` 登记键≠支配键；`route-matrix.md` 文档比代码强；`affinity-design.md` 虚报 v8 键在册。
- **`/bot route` / `/bot routes` 没管理员门**：提案在 `patches/P3A-ROUTE-GATE-PROPOSAL-20261002.md`（305 行），**要主会话动 `__init__.py`+`echo.py`**；同批还产出了"全命令门对照表"（这张表比单点修复值钱）。
- 🔴 复跑派生册必须 `BOT_AUTOSYNC=0` + 走生成器 `--write`（默认值会让 conftest 静默重写四件生成物＝越界改别席在飞面，本波四席踩过）。

---

## 十、文件解耦进度（单一真身清单）

**已并成一根（本波）**：出站打码左右边界与厂商前缀腿（`plain_text.py`）｜媒体"哪些根"四枚名册（`media/path_gate.py`）｜称谓与群内禁令（`addressing.py`，`6fe46f0`）｜错误话术族壳与池（`errors.py`，`e60ae76`）｜HTTP 客户端池与嵌入接缝（`providers.py`/`vector_knowledge.py`，`342dd48`）｜队列剪枝索引（`queue.py`，`14563d5`）｜下放决定（根不再选路，`ac81b8c`）。

**仍是两套/多处，已定位未合并**：
- **选池原身仍五套**（`random.choice`／会话游标×3 含 `_persona_text`／`daily_assist.pick_variant`／reminders 稳定散列／echo·rate_limit 裸游标）。席 E1 现算 AST 全包命中 22 处并**刻意一套都没新增**——`errors.py` 有"只依赖标准库"契约、`user_copy.py` 有"纯常量禁 import"契约，把键控游标请进来＝制造装配环。**取句语义统一在规格 §四.3 仍是待用户裁定项。**
- **13 份自拼 prompt**：6 条根本没走中央咽喉的腿正在被席 W1 收编（`prompt_template.py`），**3 枚"逐字节不变"红未解**，不许先提。
- **`config.py` 幽灵字段**：本波共 **8 枚新键已四面齐**（`f3f177a3`），另有 **8 枚待落**（席 X3 好感度衰减/prune，见 `patches/*CONFIG-REQUEST.md`）+ B1/G1 的待落需求；只补一面必红另一面（#68★）。
- **三枚裸尺在席面之外**：`tts.py:317`、`telegram_media.py:369`、`media_archive.py:193`（SSRF/路径判据的第二把尺），本波没动。
- **钉定装配装了但未必生效**：`getproxies()` 返回 Clash `127.0.0.1:7890` ⇒ 公网目标被判"走代理"因而**不钉**；"装了"≠"在挡"（#71★ 通路）。

---

## 十一、下一窗的起手式（按此序，别挑）

1. 收四席残局：**D1b（1 格裁定）→ D2b（写留痕收尾）→ X1c（备份腿续写，它是 P4 一切 schema 改动的前置物）→ W1（3 枚逐字节红）**。
2. 主会话自己动两件只有我能做的：`/bot route|routes` 补门（照 P3a 的 305 行提案与对照表）、`config.py` 落那 8+4 枚待落键（四面同批）。
3. 立 `MigrationStatus` 赋值门（P8-0）——**它不立，P8 整段无法验收，"零旁路"就只能靠说**。
4. P4 剩余：memory 库两把锁并一把 + history 补 WAL；`reflection` 零 DELETE；`migrate_affinity_v8.py` 先 commit 再断言＝假回滚，补真回滚；`PrivacyLevel` 落地（现在只到标签层）。
5. P6-8 人格契约（T1 绿了但"族数读出非空"要复核）、P6-4 prompt 模板层收完、P6-1 九类缺池。
6. P7 剩余能力（国债日德英印/大宗镍铬/电商 6 家/Instagram/steamdb/入站文件理解/历史逐事件/天气异源互证/四游戏平台订阅/AI 绘画 provider/群摘要统计/定时发稿/贴纸臂）。
7. P9 归类与退役（含 `auto_send` 那笔，见第五节 ⑨）、P10 真机验收（SnowLuma 已加载，具备条件；真发 `--execute` 仍归用户）。
8. **重启时机**：改代码不重启不生效（#10★）。重启前必读开关：`BOT_GATE_COMMAND_REQUIRES_LISTED_GROUP`（缺省 True ⇒ **未在册群里 `/bot` 命令面静默**，不想要就置 false 再重启）。`grok-4.6` 作为对话组第 2 顺位曾观测到 1024 token 预算下 60s 超时，重启后先看这条腿。

**两件必须记住的取证纪律**（都各值一整窗返工）：备份的判据不是"文件在"，是"**它包到哪一笔**"；门绿的判据要指名"**绿的是哪棵树**"。
