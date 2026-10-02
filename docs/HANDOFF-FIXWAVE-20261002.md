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

---

## 十二、叫停后补账（单线程收尾，2026-10-02 03:3x）

**波次已停**：不再派席、不再补位；在飞席随本窗结束自然终止。树的可交付性已复核：
`pytest --collect-only tests` ＝ **21,602 项全部可收集、零 collection error**（叫停前最后一枚半成品
`tests/test_db_backup.py` 停在 `class TestHonestyAndFail Loud:` 的语法错上，会让整棵测试树起不来，
我已**改名移出**到 `.superpowers/sdd/2026-10-02-fixwave/half-done/`（不是删除，可原样改回））。

**新锁终局读数**（11 件合跑）：`170 passed / 7 failed`，逐件归属——
| 锁 | 读数 | 归属 |
|---|---|---|
| `test_command_admin_gate_registration.py` | 全绿 | 席 P3a（提案另成 305 行工单） |
| `test_claims_subset_implementation_gate.py` | 全绿 | 席 G1（宣称⊆实装第一把尺；工单未写） |
| `test_tts_cache_quota_shape_guard.py` + `test_download_artifact_container_gate.py` | 全绿 | 席 B1（配 `patches/B1-CONFIG-REQUEST.md` 待落四面） |
| `test_timeout_umbrella_remaining_legs.py` | 全绿 | 席 V1 |
| `test_seat_t1_persona_contract_20261002.py` | 全绿 | 席 T1 |
| `test_intimate_group_switch_delivery.py` | 11/12（差档号那一格） | 席 D1 |
| `test_store_write_trace_d2.py` | 18/20（差 `quirks` 记账两格） | 席 D2/D2b |
| `test_prompt_template_layer_w1.py` | 3 红（"逐字节不变"三条） | 席 W1 |
| `test_migration_status_assignment_gate.py` | 1 红（状态不得由控制面推导） | 席 G1c |
| `test_db_backup.py` | 半成品，已移出 | 席 X1c |

**本窗追加闭掉的一处悬空引用**：已入库的 `reply_policy.py:1352/:1372` 两枚注释分别指向
`W-E05-GATE-GAPS-20260930.md §6.1 / §6.2`，而该件原先只有 §6 与编号 1./2.（无 .1/.2 子节）
⇒ 按"引用不出落点即悬空"补写 §6.1/§6.2 落地账，并把**目标侧平台域残余**的裁定记在那儿。

## 十三、主会话自主裁定（波次中途不停不问，逐条给代价）

- **R1 事件循环下放的完成腿不下放**：`_complete` 留在循环上。理由＝`SendQueue.submit` 的认领台账按
  `current_task()` 记账，搬进线程会静默吃掉登记（A-22 在册坑）。代价＝完成腿仍占循环时间，
  极端慢的投递仍会拖一轮；若日后要下放，必须**同批**把台账键改成显式传入。
- **R2 `{exc}` 异常名保留在管理员档**：对外裁剪已由受众分级门（`AUDIENCE_PUBLIC` 裁 exc 原文/栈/
  配置键名）执法，在族壳里再删一次会让管理员丢归因。代价＝管理员私聊里仍能看到异常类型名。
- **R3 选池 API 一律复用既有五套、零新增**：`errors.py` 有"只依赖标准库"契约、`user_copy.py` 有
  "纯常量禁 import"契约，把键控游标请进来＝制造装配环。代价＝"四套并存"这笔债没减，
  取句语义统一仍是**待用户裁定项**。
- **R4 汇率/新闻宁可少说不编**：RUB/CHF/CAD/AUD 标 `pending` 而非接一个未核实源；
  V2EX/少数派从名册除名并把断言反转成"回潮即红"。代价＝用户问这四个币种时拿到的是
  "尚未接入已核实报价源"，不是数字。
- **R5 超管目标名单的平台域收口不做**（详见 §6.2 落地账）。代价＝名单写成非 QQ 前缀时，
  那个号会**静默失去**超管保护（不是多给权）。
- **R6 别席在飞面一个不提交**（`AGENTS.md`/`docs/HANDBOOK.md`/`docs/auto-facts.md`/
  `tests/test_config_key_registration_ledger.py` 等）。代价＝派生册 `auto-facts.md` 的计数
  暂时与代码不同步（测试文件数、config 字段数已因本波变化），要等那两席收笔后一次性 `--write` 重录。
- **R7 半成品测试件"改名移出"而非删除**，并把原文留在 `half-done/`。代价＝该席要重做一遍
  接线与工单，但没人会在树里踩到一个语法错。

**HEAD 可签净（终局实测，2026-10-02 03:4x）**：`git archive HEAD` 抽到仓库外副本、同一把尺复跑
＝`ruff` **All checks passed**、`mypy` **Success: no issues found in 606 source files**。
⇒ 工作树当前那 35 枚 lint 红 / 5 枚 typecheck 红**一枚都不在 HEAD 上**，全属未入库的在飞半成品
（`quirks.py` 4、`db_backup.py` 1，其余在别席在飞件里）。
**接手时的正确动作是继续做完那些面，不是回退**——已入库的 10 笔是可签的。

## 十四、资源与知识库实测（用户追问「TTS 吃内存 / 能否重启 / 数据库是否在自动更新」，2026-10-02 04:1x）

### TTS 已关（待重启生效）
`.env` 三枚总闸置 false（改前备份 `%TEMP%/qoder-env-before-tts-off-20261002T040012.env`，凭据全程未打印）：
`BOT_TTS_ENABLED` / `BOT_TTS_AUTO_REPLY_ENABLED`（原先私聊 10% 概率自动发语音）/ `BOT_TTS_VOICE_HOOK_ENABLED`。
⚠ 另两处在册事实要记着：`config.py:593-594` 的 `bot_tts_cache_max_bytes=0` 与 `cache_max_age_days=0`
＝**缓存无上限、无过期**（计划里 P3-8 那一格，席 B1 未收口），TTS 一旦重开，合成产物目录会只涨不清。

### 内存/内存门实测
- 本机 31.7 GB，**空闲仅 0.8 GB**；占前几位＝`llama-server` 2.48 GB、`Client-Win64-Shipping` 2.34 GB、
  Memory Compression 1.07 GB、**bot python 0.58 GB** ⇒ **bot 不是这台机器的内存大户**，
  但它瞬时提交量到过 8.2 GB（PrivateMB），峰值确实会去挤那 0.8 GB 的余量。
- 🔴 **头号 CPU/内存真凶是"ANN 不可用 ⇒ 每条消息暴力扫 744,371 × 1024 维"**（见下）。
  关 TTS 只省合成那条腿，**修 ANN 才是这台机器上最大的性能收益**。

### 知识库现状（只读普查，全部 mode=ro）
| 问题 | 实测答案 |
|---|---|
| 每天自动爬取更新词条？ | **在跑**。`knowledge_meta.kb_sync_last_summary`＝`started_at 2026-10-01T16:44:07Z / finished_at 16:49:00Z / mode=incremental / ok=true`（＝本地 10-02 00:44 那一轮）。库内 `knowledge_docs` **211,961** 条、`knowledge_chunks` **744,371**。 |
| 清洗、汇总正常？ | **正常**。`embed_pending=0`、`chunks_after=embedded_after=744,371` ⇒ 嵌入链**无欠账**；FTS 表与主表同为 744,371 ⇒ 清洗入索引一致。汇总侧 `reflection_digests` 326 行、最新 10-01T16:43Z，`conversation_turns` 6,375 行、最新 10-01T20:01Z（＝刚刚），`memory_recall_audit_v21` 200 行 ⇒ 记忆/反思/摘要三条都在写。 |
| ANN / RAG 嵌入能完成？** | **嵌入完成，ANN 没完成——两件事必须分开说。** ANN 索引文件 mtime **09-27 03:24**、`order.json` 只装 **740,267** 条，而期望 **744,371** ⇒ **短装 4,104 条**；`ann_embed_generation=68` 而盖章代次 0；`ann_build_checkpoint` 停在 `last_rowid=71448 / stage=midway`。载入路径判 `signature_mismatch` ⇒ **拒用 ANN，回落暴力扫描**（这条 `ann_pair` 门自己写得很清楚）。 |

**ANN 修不好有两重独立原因（下一窗按这个顺序做）**
1. **内存门挡住重建**（刻意设计，低内存硬跑会把 bot 连人带库压死）：`available 7.84GiB < required 8.44GiB`，
   `floor 4.50GiB`（S85 标定值），`headroom 0.12GiB`，**累计被挡 6 轮**。⇒ 要么先腾出 ≥0.6 GiB 再跑
   `knowledge-sync` 重建，要么显式用 operator CLI 的 `--ann-force-low-memory` 越门（越门本身另留痕，**不建议**）。
2. **两枚签名自相矛盾，光重建不够**：`embedding_signature` 记的是
   `http://127.0.0.1:8090/v1|bge-m3;…` （AxonHub 网关），`ann_signature` 记的是
   `http://127.0.0.1:11434/v1|bge-m3;…` （Ollama 端点）——**同一个人换过嵌入端点，两枚戳各记了一个时代**。
   即便重建成功、行数对平，载入侧的签名比对仍会因这两枚不等而判不可用 ⇒ 必须**同批**把 `ann_signature`
   随当前 `embedding_signature` 重盖章，否则修完第 1 条还是回落暴力扫描。
3. 另有两枚 09-30 15:07（清空事故时刻）留下的**半成品重建残件** `.wip-kb_wiki_faiss.index`（81 MB，
   order 65,536 条）与 `.wip-…order.json`：属"上一代没建完"的尸块，判归属后按规程处置（**本窗未动**）。

### 重启判定（诚实版）
`scripts/pre_restart_check.py` 现算 **PASS 4 / SKIP 4 / FAIL 5，rc=1**。逐条含义：
- `ruff` FAIL＝27 枚全在**未入库的在飞半成品件**里（HEAD 副本实测 `All checks passed`）⇒ 不影响运行，只影响门。
- `doc_sync` / `hash_ledger` FAIL＝派生册与哈希台账需 `--write` 重录（本波改了代码，计数当然动）。
- `kb_drift` / `ann_pair` FAIL＝**真实功能降级**：RAG 现在走暴力扫描，召回与时延都吃亏。
**可重启性另做了一次硬核验（不看回显看实跑）**：全部脏 .py 与新模块 `ast.parse` 通过、
`import plugins.bot_unified_runtime` ＝ `PLUGIN_IMPORT_OK`、typecheck `Success: no issues found in 609 source files`
⇒ **重启不会崩在 import 上**。本窗另修掉一枚真会炸的：`quirks.py` 用了 `OUTCOME_REFUSED` 却没 import
（生产路径 propose 一被拒就 NameError），同处补 `db_backup.py:576` 的 None 解引用形态。
⚠ 但工作树里仍有 6 个半成品面**未入库**，重启会把它们**一起加载**（文件在盘上就会被 import）。
**想立刻拿"新代码 + TTS 关闭"，可以重启**，风险我已实测到 import 级；
想同时要门绿与 RAG 提速，就先做 §十六 的 ANN 两步与 27 枚 lint 收尾，再重启（一次到位，省一轮）。

---

## 十五、亲密模式「人在白名单里 ⇒ 他在任何群都能开」施工图（裁定已定，**未实施**）

> 用户 2026-10-02 对本点的原话是"指的是「人在白名单里 ⇒ 他在任何群都能开」"。
> **本节是施工图不是完成账**：动手权在下一位，动手前先把下面的"三处消费者"读完。
> 本节的每一条行号都是 10-02 死机后**回读真身现算**的，不是凭记忆写的。

**现状真身**（`domains/chat_reply/runtime/content_route.py:893-942`，`explicit_allowed_for_session`）：

| 分支 | 判据（逐字） | 读 `sender_id` 吗 |
|---|---|---|
| `console` | 直接 `True`（运营者本地面） | — |
| `private` | 私聊黑名单赢 → 白名单**非空**时仅名单内 QQ 放行 → 其余放行 | ✅ 读（这就是"人员名单"） |
| `group` | `str(group_id).strip() in (wl - bl)`，wl/bl = `bot_content_route_group_{whitelist,blacklist}` | ❌ **死参，群分支完全不读人** |

⇒ 缺口就在最后一行：**群聊放行只看群号，与"这个人是谁"无关**。

**名单真身**＝`config.py:1230/1231/1236/1237` 四枚（群黑白 + 私聊黑白）。
**没有第五枚"人员跨群"名单**，裁定＝**复用 `bot_content_route_private_whitelist` 当人员白名单，不新建键**
（理由：不起第二本账；不新建键 ⇒ 免走"新键四面"全套同步，见 §五第 10 条）。

**唯一改动点**：群分支加一条"人腿"，**顺序不许换**：

1. 群黑名单命中 ⇒ `False`（**永远赢**，人的白名单压不过群的禁令）；
2. 群白名单命中 ⇒ `True`（既有行为，一字不动）；
3. **新增**：`sender_id` **逐字**命中 `bot_content_route_private_whitelist` ⇒ `True`；
4. 其余 ⇒ `False`。

**三条正确性硬点（写错任何一条就是把最贵的方向搞反）**：

1. **空名单绝不等于放开**。私聊侧"空=默认放开"是**刻意**与群侧不对称的既有裁定
   （`config.py:1232-1235` 明写"与群白名单「空=关闭」语义刻意不对称"）。新腿只准判
   "**逐字命中**"，**绝不准判"名单空 ⇒ 放开"** —— 否则一枚为私聊写的空语义会一次把
   群聊亲密面整体打开，那是本仓最贵的一类越放。
2. `bot_content_route_private_blacklist` 命中的人**不获得**新腿；但**不撤销**他原本靠群白名单
   拿到的放行（那是既有行为，改它超出本裁定范围 ⇒ 别"顺手"改）。
3. 本裁定**只动 admission**：不动"谁有权拨"（群内仍仅管理员可拨，`chat.py` 的管理员门原样）、
   不动 **tier 来源**（群级钉与个人级 `member_session_key` 的现行优先级不变）、不动 TTL / `max_ttl`。

**消费者必须同批改，否则新腿只在部分通路生效**（"半条腿"形态正是 F-A 那一刀治的病）。
群分支的调用点现算三处：

| 调用点 | 现状 | 要不要动 |
|---|---|---|
| `content_route.py:981`（`resolve_intimate_context`） | 已传 `sender_id=` | 不动 |
| `chat.py:3958`（人格对话主缝） | 已传 | 不动 |
| `tts.py:1554` | `explicit_allowed_for_session("group", group_id, config)` —— **没传 sender_id** | **必改**，否则 TTS 群语音露骨面永远吃不到本裁定 |

（`__init__.py:9449` 也在同族调用面上，改前读它的实参确认。）

**验收（双向自测；只打勾不算证据）**：在 `tests/test_intimate_group_switch_delivery.py`
（现 12/12 绿、**未入库**）补四腿——① 正例：群不在群白名单 + 人在私聊白名单 ⇒ `True`；
② 反例：同群、`sender_id` 换成名单外的号 ⇒ `False`；③ 反例：把该群加进群黑名单 ⇒ 人再白也 `False`；
④ 消费者腿：断言 `tts.py` 那条判定**实参里真带上了 sender**（AST 认调用形，或注入 fake config 数参数）。

**生效口径**：只改代码 ⇒ 必须重启（项目铁律：改代码必须重启才生效）；不新增配置键
⇒ 无 `RESTART_REQUIRED_KEYS` 追加、无 `.env.example` 申报行。名单现值**不抄进本文档**（规则 3）。

---

## 十六、ANN 修复 runbook（现算修正版，含我此前一笔错账的**更正**）

> ⚠ **先更正**：本档早先写的"内存门要 4.5 GiB、还差 0.6 GiB"**不准**。
> `_ANN_BUILD_MIN_AVAILABLE_BYTES = 4.5 GiB` 源码里明写「**不当门用、不是物理下限**」
> （`vector_knowledge.py:453-459`，那是 S85 在 n≈766k 一个点上的历史合价，只被一枚复算锁钉着）。
> 真正的门是**需求模型按当轮 n 现算**：`n=740,267 / dim=1024` ⇒ 线性 4.77 GiB、
> **总要价 ≈6.00 GiB**、中途 ≈5.3 GiB（同节 619-624 行的实测对表）。
> ⇒ "**差多少**"必须按当时的已嵌行数重算，别拿我上一版的 0.6 GiB 当结论。

**两重病因，互相独立，只治一个仍然不可用**（均已现网取证）：

**A. 签名不一致 ⇒ `signature_mismatch`**
`embedding_signature` 与 `ann_signature` **存的都是 `self.signature`**（模型/端点指纹，
`vector_knowledge.py:346` 的注释就是这条的原始说明），两枚写点分别是
`1563-1572`（embedding 侧）与 `3348 → _set_stored_ann_signature`（ANN 侧，读点 `3827-3858`）。
现网取证：前者指 `127.0.0.1:8090`（AxonHub 网关），后者指 `127.0.0.1:11434`（直连 Ollama）
⇒ 值不等 ⇒ 判据在 `4054` 处 `return False, "signature_mismatch"`（reason 名在册：
`_STAMP_RECONCILE_REASONS`，`420-433`）。**即使重建成功也会被这条继续拒。**
⇒ 两条修法二选一，**别混着做**：① 把嵌入端点指回建索引那一代（改配置＝要重启，现值不入文档）；
② 在同一代签名下**重建并同事务重盖两枚戳**（缺一即红另一处，这正是"两把尺"形态）。

**B. 内存要价 > 空闲**（开火前门，S112）
`3. 要价 = 4,694 B/向量 × n + 批内副本(2048×dim×4×4) + max(128 MiB, (线性+批副本)/4)`；
空闲 < 要价 ⇒ **不开火**，reason = `insufficient_memory`，并留三处痕迹（WARNING 日志 /
`knowledge_meta` 观测行 / 经 kb-sync 既有告警 sink 出五要素卡），**旧索引原样保留**。
- 越门的**唯一在册通道**＝operator CLI 的显式旗标（`450-452`：阈值是模块常量、**不开新 config 键**、
  不许改生产配置面去"让它绿"）。
- 集合级自证另有独立地板 **1.5 GiB**（`_ANN_STAMP_RECONCILE_MIN_AVAILABLE_BYTES`，`407-416`：
  定它的根据是**余量不是需求**——本机空闲跌到 1.6–2.5 GiB 区间连着死机两次），
  外加项数上限 **2,000,000**（超即 `too_large_for_set_proof`，**宁可由人显式越门，不许把机器按死**）。
- 探针取不到数 ⇒ 按"不可判定"fail-closed，同样不开火。
  ⚠ 本机已知坑：`K32GetProcessMemoryInfo` 对当前进程伪句柄返回 0（读数 nan）⇒
  **先怀疑探针再怀疑事实**（这条我踩过一次）。

**修完 A+B 之后的第三道闸（别忘）**：完备性闸 `_ANN_COMPLETENESS_MAX_MISSING = 0`
（`344-367`，一条都不许少）。**跳过重建不放行这闸** ⇒ 只要索引短装就回落暴力扫描
（`_vector_candidates` → numpy 矩阵 → `_brute_candidates_python`）。
**这就是"bot 内存不高却整片发烫"的真根因**：`744,371 × 1024` 每轮现点积。

**实操步骤（取证只读，不改生产）**：
1. 现算 `n`（已嵌行数，`knowledge_chunks` 向量列非空计数）——**离线口径**：那条 COUNT 实测 23.8 s，
   禁进载入路径（`355-356`）。
2. 现算可用物理内存（脚本形态见 §十四）。本机 32 GiB；死机前实测空闲 0.8 GB（TTS 关掉后已回升，**以现算为准**）。
3. 按上面式子算要价 ⇒ **要开工先把空闲做到 ≥ 要价 + 余量**（n≈740k 时 ≈7 GiB 起步），
   并先停同机大户（死机前读数：llama-server 2.48 GB、游戏 2.34 GB —— 当时 `nvidia-smi` 看不到、
   python 主进程 RSS 只 0.48 GB，**都不是 bot**）。
4. 复验门名：`tests/test_ann_memory_gate_s118.py`（内含"32 GiB 机 / 10 GiB 空闲必须放行"与
   "2 GiB 空闲仍拒"两钉，**不许把门重定标成摆设**）、`tests/test_pre_restart_check_ann_pair.py`；
   两枚都在 `scripts/pre_restart_check.py` 里现算（本窗 FAIL 读数＝`ann_pair` 与 `kb_drift`）。
5. 台账 #61★ 那条判据一并读：**「证明缺席且代次 > 0」要与守卫同读**，别只看单边。

---

## 十七、在飞面清点（死机后现算）+ 本席两条自曝

**现算命令**（下一位照着跑就能拿到同一形状，别信我抄的数）：
`git status --porcelain | awk '{print substr($0,1,2)}' | sort | uniq -c`；
逐面 mtime 与行列增量用 `git status --porcelain | grep '^ M' | cut -c4- | while read f; do …; done`。

**本窗写这一节时的读数＝51 枚**（`34 枚 tracked 已改` + `17 枚未跟踪`），
而同一轮开工时是 **47 枚** ⇒ 差额不是本席造的，见下面"热写面"。

**🔴 热写面（有一席正在同一工作树里活着写，10-02 06:0x 现算）**：
`docs/HANDBOOK.md`（mtime 06:03:48）、`docs/auto-facts.md`（06:01:15）、
`tests/test_prompt_injection_order.py`（05:34:42）。
判据＝mtime 落在本席动手之后且**不是本席写的**（本席全程只写交接档与哈希册两族面）。
⇒ **下一位动手前必须重跑一次 mtime 现算**，别把这三枚当"无人认领的遗留"顺手收走。

**分类账（17 枚未跟踪件，按"重启会不会被加载"切）**：

| 族 | 枚数 | 面 | 关键点 |
|---|---|---|---|
| **会被 import 的源件** | 3 | `domains/core/write_trace.py`(10.7 KB) / `runtime/db_backup.py`(53.8 KB) / `domains/chat_reply/llm_engine/prompt_template.py`(9.0 KB) | **文件在盘上就会被加载**——重启前必须逐枚 `ast.parse` + 邻域复跑（本窗已核 39 枚 py 面**零 SyntaxError**）。`db_backup.py` 的 mypy 洞我已修在盘上，但**未入库** |
| **人格数据** | 1 | `personas/shorekeeper/imagery_families.txt`(2.8 KB) | 规则 8：改话术要维持守岸人语气；台账 #66★ 那条"意象名词禁硬编码进代码"就是为它 |
| **新锁（测试）** | 10 | `test_intimate_group_switch_delivery.py` / `test_claims_subset_implementation_gate.py` / `test_migration_status_assignment_gate.py` / `test_store_write_trace_d2.py` / `test_command_admin_gate_registration.py` / `test_prompt_template_layer_w1.py` / `test_download_artifact_container_gate.py` / `test_timeout_umbrella_remaining_legs.py` / `test_tts_cache_quota_shape_guard.py` / `test_seat_t1_persona_contract_20261002.py` | 前六枚**现算绿**；后四枚里 `claims_subset` / `migration_status` / `tts_cache_quota` 是**刻意的判据镜**（HEAD 轴自证看不见，台账 #72★），`timeout_umbrella` 尚差 3 处零字节差 |
| **工单/提案** | 3 | `patches/B1-CONFIG-REQUEST.md` / `B1-TTS-CACHE-OUTTMPL-20261002.md` / `P3A-ROUTE-GATE-PROPOSAL-20261002.md` | 纯文本，动手前先读 |

**已入库但注释指向本节的**：`patches/W-E05-GATE-GAPS-20260930.md §6.1/§6.2`（曾悬空，已补）。
**半成品未删**：`.superpowers/sdd/2026-10-02-fixwave/half-done/test_db_backup.py.HALF-WRITTEN`
（那枚曾把整树 collection 打崩的类名断行，只准**移出**不准删）。

### 本席自曝（两条，都留在账上）

1. **`BOT_AUTOSYNC` 误设**：本窗一条 `--collect-only` 复跑命令里我把 `BOT_AUTOSYNC=0` 写成 `1`，
   于是 conftest **静默重录了哈希册**。后果与处置全部现算：
   受影响面只有 `tests/render_hashes.json`（**恰好 1 处 hunk**）+ 它的 sidecar
   `tests/render_hashes.meta.json`（2 行：`body_sha256` + `full_write_at`）。
   漂移内容是 `capabilities/echo.py` 一枚哈希。
   **核完再决定留不留**（而不是"手滑了就一键退回"）：`git diff --numstat HEAD -- …/echo.py` **空**
   ⇒ echo.py 与 HEAD **逐字相同** ⇒ HEAD 里那枚哈希**本来就对不上 HEAD 自己的文件**
   （＝台账 #72★ 说的"HEAD 基线自红"，也正是 §十四 `pre_restart_check` 报 `hash_ledger` FAIL 的那一枚）。
   复验：`BOT_AUTOSYNC=0 python tests/verify_hashes.py`（只读）⇒ **exit 0、零字节输出＝零漂移**。
   ⇒ **裁定：保留这一行重录并入库**（它是真基线修，不是给谁的作品品"祝福"），
   与本节同批提交。**教训写死**：`BOT_AUTOSYNC` 只准显式给 `0`；"我只是想看看能不能收集"
   在这种共享树里没有"只读跑一下"这回事——生成物在 conftest 里，不在你的意图里。
2. **上一窗六席阵亡于 150 次调用硬顶**（不是模型问题，是我把三件交付捆在一席的规划错误），
   代价＝半成品测试文件把整树 collection 打断 + 10 枚 write-trace 锁返工。
   ⇒ 本窗三席简报里各写死"≤80 次调用、~65 次立刻收尾、按节即时 append、批量校验一次脚本跑完"。

---

## 十八、深化席取证回收（探索成果 · 不含施工图）+ 三席阵亡账

### 18.1 阵亡取证（**新的死法，与前两种都不同**）

| 席 | 结果 | 调用数 | 子代理 token | 存活时长 |
|---|---|---|---|---|
| HB-A 架构篇 | 中途死，**产出已落盘** | 53 | 4.32 M | 101 分钟 |
| HB-B 中央调度完成度 | 死，**零产出** | 54 | 4.11 M | 98 分钟 |
| HB-C 归类/耦合/解耦 | 中途死，**产出已落盘** | 47 | 3.45 M | 94 分钟 |
| （同轮早先两笔重派同名席） | 死，零产出 | 43 / 53 | 2.88 M / 5.85 M | — |

- 死因文案＝`You've reached your daily usage limit for Chat`（＝**当日累计额度墙**，AGENTS 规则 7 说的 1302 那一族），
  **不是** 150 次调用硬顶，**也不是**基础设施 `Sorry, something went wrong`。
  ⇒ 教训：**"≤80 次调用"的预算拦不住额度墙**——墙按当日累计算，与单席调用数无关；
  真正省额度的是"少派席、每席窄面"，不是"给每席设上限"。
- 写入面复核（现算）：三席**零 git 写**、阵亡前未改任何源码/生成物面，只写了自己那份报告；
  半成品扫描＝58 枚 py 面 `ast.parse` **零 SyntaxError**。

### 18.2 产出为什么必须搬进出仓库

原产出落在 `.superpowers/sdd/2026-10-02-fixwave/`，而 **`.superpowers/` 在 gitignore 里**
⇒ 它不在任何一次 GitHub 备份里。本窗已经为这条付过一次学费（死机丢了上一轮三份 Temp 手册）。
⇒ 已做**入库副本**（两份，本波一并 commit）：
- `patches/HB-A-architecture-EVIDENCE-20261002.md`（41,744 B）
- `patches/HB-C-taxonomy-EVIDENCE-20261002.md`（19,303 B）

⚠ 读 HB-A 前必知：该席死前**把 §1 推倒重写过一次**，文件里存在两版"两棵树"
（第 11 行 `## 1. 两棵树` 与第 208 行 `## 一、两棵树`）。**第二版更晚、更全**，
但两版都留着没删——因为我无法证明后写的没丢掉前一版的取证命令。引用前按文中命令现算。

### 18.3 探索成果（HB-A · 架构与主链路，条目级摘要，细节看入库副本）

1. **`_prepare` 十步门序逐枚带行号钉死**（`pipeline.py:1059` 起）：
   `feature_gate:1065`（状态读失败 **fail-closed** → `FeatureAccess(False,"feature_state_unavailable")`）
   → `runtime_enabled:1082` → **角色解析 `:1103-1106` 在门禁内改写 message** → `runtime_control.allows:1107`
   → `policy_evaluator:1128` → `quiet_hours:1151`（**静默**：`public_message=""`）
   → `decide_reply_budget:1179` → `rate_limiter.check_and_record:1192`（**同样静默** + `_schedule_rate_limit_redrive:1212` 解禁补跑）
   → 🔴 **`_claim_event` 幂等 claim 必须排最后 `:1250`** → `BotDecision:1258`。
   **谁把 claim 提回门禁前面＝复发 A-18**（被拦事件白耗幂等键 ⇒ 用户重发永远被当 duplicate 吞掉）；
   claim 失败还要**立刻回滚刚记的限流账**（`:1251-1256`）。幂等键段禁 `:` ⇒ `is_legal_segment`（台账 #46★）。
2. **`_complete` 从 `pipeline.py:1287` 起、输出半程顺序同样冻结**（审核 → TTS 钩子 → 渲染 → 转发 → `send_queue.submit`）；
   `submit` 台账按 `current_task()` 记账 ⇒ **`_complete` 必须留在事件循环线程上**（A-22）。
3. **"AGENTS 路径的一半是旧道"**：`domains/core/board_shim_ledger.py:22 SHIM_ROWS` 是"叙述≠真身"最系统的一处，
   已列出 10 组「顶层垫片 → 真身」对照（`capabilities/chat.py`→`domains/chat_reply/…`、
   `output/renderer.py`→`domains/render/`、`llm/model_router.py`→`domains/chat_reply/llm_engine/` 等）；
   PEP 562 活再导出 ⇒ **任一侧 monkeypatch 都一致，但读代码要读真身**。
   同文件 `:75-81` 四枚**只准降**的棘轮基线（含 `OUTSIDE_BASELINE`）。
4. **"关着的、但必须一开即通"清单**（用户纲领的那句"用不到会关掉，但你必须做好"）：现算 `config.py` 缺省 `False`
   的功能开关 19 枚逐条带行号（`bot_control_plane_enabled:199` / `bot_event_idempotency_enabled:181` /
   `bot_memory_enabled:332` / `bot_embedding_enabled:276` / `bot_kb_wiki_enabled:294` / `bot_worldbook_enabled:324` …）。
   ⚠ 该席同时钉了一句**必须保留的判据**：**源码缺省 False ≠ 线上关着**（线上＝`.env` 现值 + Runtime `runtime_settings.json`，§1.4）。
5. 另含：`runtime_paths.py:280-295` 的重映射实现、测试进程 Runtime 根隔离缝的两态语义、
   源码树禁缓存的**两把**执法门（别只认一把）、覆盖册为何赢 `.env`、行数现算 295/2257/1829。

### 18.4 探索成果（HB-C · 归类 / 耦合 / 解耦，含**三枚新现算出来的红与假绿**）

**先记三件"没人报过的事实"**（这三条就是本席的价值）：

1. 🔴 **`OUTSIDE_BASELINE` 硬锁此刻是红的**：现算 `75 / 基线 74 (RISE!)`（`scripts/shim_retirement_census.py --check`）。
   唯一合规处置＝**同批把某一态真降 1 枚**（最省事的正当路径＝下面 §18.5 那枚 `auto_send` 复活件的四动作同批退役），
   或**如实登记为既存红**。不许调基线、不许放宽容差。
2. 🔴 **`AGENTS.md` 软顶 30,000 是门禁假绿面**：机器门只咬 **32,768**
   （`tests/test_documentation_consistency.py:757 _ENTRY_SIZE_CEILING`、`:760 _ENTRY_SIZE_DOCS=("AGENTS.md",)`、`:791`），
   **30,000 只活在 AGENTS 页首散文里**。现算工作树 **29,985 B＝距软顶只剩 15 字节而门仍绿**
   （HEAD 版 29,993 B，差 8 B＝别席在飞改动）。⇒ 任何人再写一句都破软顶且不报警。
   顺带：**`COMMANDS.md`（24,187 B）根本不在执法名单内**，尽管自证用例拿它当"达标放行"样本——它是夹具不是对象。
   ⚠ **18.7 现算校正**：本席落完本节后再量＝**29,976 B**（别席在这半小时内又压了 9 B）⇒ 结论不变、数要跟着走。
3. 🔴 **`.qoder/settings.local.json` 仍被 git 跟踪**，与 `.gitignore:79` 的**意图**矛盾
   （判据实跑＝`git ls-files .qoder/` 有它 + `git check-ignore -v` RC=1 不忽略）。
   **本席复跑确认仍成立**（`git ls-files .qoder/` 现算有它）。
   ⇒ 处置需要用户裁一句话：`.superpowers/` 要不要加否定规则继续跟踪（决定 A 类是"迁走"还是"从仓库消失"）。**本席不代裁。**

**归类现状（现算，命令在副本里）**：`docs/design/` 共 **242** 件，其中 `*-log.md` 过程日志 **126 枚 / 1,096,124 B**
（交接档 §八 早先写"约 127 枚"＝当时值，**以本行现算为准**）；非日志件 116 枚属"该留"；`docs/` 顶层跟踪件 36。
死账判定证据：126 枚 mtime 全落 2026-09-29→09-30，最后一次提交 `4e4a8645`（10-01 15:51 的 wip 快照）⇒ **09-30 之后无人再写**。
⚠ **十板块规范本身没有机器门**（`test_doc_link_integrity.py` 只判链接指向存不存在，不判"该不该在 `docs/design/`"）
⇒ **这就是它躺了十天的原因；要落地必须先立归属门**（副本 §6 动作 1）。

**待搬迁 45 枚是虚胖**（重要，别按它规划工作量）：现算拆成
`真可搬 0 ｜ 落点已存在·禁覆盖 5 ｜ 基础设施常驻原地 40` ⇒ 搬迁面实际只有 **5 枚**且都属"禁覆盖"。

**垫片漏记 8 枚**（HB-C 当时读数：账上登记 15 行 vs 扫描面待退役 23）：`capabilities/auto_send/__init__.py`（🔴 **复活件**，
就是台账 #68★"还原把已退役件连账本行写回"的实锤对象，且已知会让 `test_copy_redline_gate.py::test_gate_scope_sanity` 跨窗红）、
`capabilities/market.py`、`runtime/settings.py`（热改态真身却躺在"待退役"桶＝**桶位待裁**）、
`security/memory_sanitize.py`、`sender/__init__.py`、`sender/onebot.py`（AGENTS 流程图按名引用 ⇒ 退役要同批改 AGENTS）、
`sources/fetchers/__init__.py`、`sources/subscriptions/__init__.py`。
另有**读点盲区 3 枚**（`audit/` `contracts/` `llm/` 的 `__init__.py`：命中垫片记号但派生不出真身 ⇒ 只读附账、不改桶），
`G-P2 豁免条数 28 / 上限 29`（只剩 1 条余量，别一次填满），`SHIM_ROWS` 15 行**全部还在盘**（幽灵行 0）。

**退役一枚垫片的正确形状＝四动作同批**（#68★，缺一个必红另一个）：
① 迁完调用方 → ② 删旧路径文件 → ③ `shim_retirement_census.py --write-ledger` 重录（摘行 + `refs` 上限**只降**）
→ ④ 若旧名被 HANDBOOK/AGENTS/板块页按字面引用，同批改指针。
`--write-ledger` 默认取 `min(既有, 现算)` ⇒ **抬不动上限**，唯一上调通道＝`scripts/shim_refs_approvals.json` 显式审批（带 `expiry`）。

### 18.7 本席对 HB-C 三格读数的现算复核（**结论：一格已被别席闭掉，两格仍成立**）

主代理写完 §18.4 后**没有直接采信**，而是复跑 `shim_retirement_census.py --check`（`BOT_AUTOSYNC=0`），现算：

| HB-C 的读数 | 本席现算 | 判定 |
|---|---|---|
| 账上登记 **15** 行、漏记 **8** 枚 | 账上登记 **23 枚**，且「对账问题」五项（漏记 / 非垫片登记 / 已退役被回引 / 真身不存在 / 引用超上限）**全 0** | 🔴 **已被闭掉**——这半小时里有别的在飞席把 8 枚补录进册了（§18.4 那段名单因此**降级为历史取证**，不再是待办；`auto_send` 复活件是否连**文件**一起退役**仍未证**，要单独查盘上文件在不在） |
| `OUTSIDE_BASELINE 75 / 基线 74 (RISE!)` | **一字不差复现**（末行原文＝`硬锁·三态之和(域外全量) 75/基线 74 (RISE!)`；单态参照 `待退役 23/23`、`待搬迁 45/45` 各自 OK） | ✅ **仍是一枚活红**，且补录之后 `75` 没降 ⇒ 说明它不是"漏记"造成的，是**某一态真的比基线多 1 枚** ⇒ 起手式第 0 条成立，但**解法要重找**（补录这条路已经被别人走完了） |
| `AGENTS.md` 工作树 29,985 B | **29,976 B**（HEAD 版仍是 29,993） | ✅ 假绿结论不变，数字已按现算改（见 §18.4 第 2 条校正行） |
| `.qoder/settings.local.json` 仍跟踪 | `git ls-files .qoder/` 现算命中 | ✅ 仍成立 |

⚠ **这一节本身就是要留的账**：它同时是"HB-C 的取证是真的"与"我抄它当现状就已经过时了"两条证据。
下一条规则由此得来——**引用 §18.4 任何一格数之前，先重跑那一条命令**（本项目 台账 #68★ 明写过：
断言回显里的 `...` 省略不得当证据，结论要插桩实跑）。

**再补两格现算（把上面留的两个"仍未证"闭掉）**：

- `auto_send` 复活件的**文件侧**：`plugins/.../capabilities/auto_send/__init__.py` **仍在盘、仍被 git 跟踪**（435 B，mtime 09-30 15:48），
  而真身 `plugins/.../domains/schedule/auto_send/__init__.py` **也在盘** ⇒ 现在不是"文件消失了但账还记着"的幽灵形态，
  而是**垫片与真身并存**（补录席把行补进了 `SHIM_ROWS`，没做文件退役）。
  ⇒ 那一枚 RISE 红与它无关；真要动它必须走 §18.4 的**四动作同批**，且要连带 `test_copy_redline_gate.py::test_gate_scope_sanity` 配对判据。
- **在飞面数**：本档 §十七 写的是 **51**（34 改 + 17 未跟踪），现算已涨到 **74** ⇒
  同一工作树里至少两席在并行写。**任何"逐面清点"落地前都要重跑
  `git status --porcelain | awk '{print substr($0,1,2)}' | sort | uniq -c`，别用本档的数字当分母。**

### 18.5 HB-B（统一调度完成度深化）**未产出**——欠账与补法

额度墙打断，零文件。它欠的六件事按 §七 现有结论就够动手，但下面三格是**只有现算才知道**的：
① `offload_registry` 六个判定族逐族计数 + `BYPASS_SUSPECT`/`PENDING_RULING` 逐枚点名（为什么可疑 + 消解要动哪一处 + 消解后哪把锁亮）；
② 未入库两枚新锁 `tests/test_claims_subset_implementation_gate.py`、`tests/test_migration_status_assignment_gate.py`
   当前判什么、绿还是红、判据原文（它们现在仍在 `??` 里，见 §十七）；
③ 现状/目标两张流程图的逐边差异表。
⇒ 额度重置后**单开一席窄面只做这三格**，别再捆"两张图 + 六档门槛"（本席简报捆了七节，这是它死在半路的直接原因）。

### 18.6 对 §十一「下一窗起手式」的两处修正

- 起手式第 1、2 条（ANN 两步）**保持不变**，但内存要价按 §十六 的更正重算（别再引用"还差 0.6 GiB"）。
- **新增第 0 条**：`shim_retirement_census.py --check` 的 `75/74 RISE!` 是一枚**当下就存在**的门禁红，
  且它是全树门禁里唯一"红得没人报过"的一枚 ⇒ 排在 lint 27 枚之前，因为它只需四动作同批就能真降 1 枚。

## 十八、自主运行窗结案（2026-10-02 08:0x→09:2x，1 主会话＋6 席；用户已睡，令＝自主跑到彻底完成）
> 本节是**结案段**：把 §十二–§十七 那些"半途"读数收到终态，并给下一窗（或她醒来那一句）一张能一句回完的清单。全账本体在 `docs/HANDBOOK.md` §60–§65，本节只记"收在哪、还差什么、谁去做"。

- **表情册波（本目标 ①②③）＝已入库**。`_ALBUM_RE`／`handle_meme_album_command`／store 四法（`relink_path`·`missing_path_rows`·`admit_into_album`·`mark_persona_owned`）／帮助条目「表情册」／`tests/test_meme_album_commands.py` **全部 `git grep` 命中 HEAD**；S2 的 `audit_tags += sticker_same_message` 在 HEAD 与工作树**逐字同**（`chat.py` 单处）；S3 的 `_maybe_send_sticker_for_emoji_like` HEAD 与工作树同为 `2` 处。**主会话自曝一次量具错**：第一次我用 `git grep -c | wc -l` 比"HEAD vs 工作树"，那数的是**命中文件数不是行数**，于是把 ③ 读成"工作树多一枚"——按行重算后两侧一致，更正见 §64。
- **④ 尾红＝终态清楚，但不归本波**：`tests/test_config_key_registration_ledger.py` 今日 **4 failed／35 passed**（`poison_11`/`14`/`15`/`16`）。一树一进程复算＝**HEAD `(784, 1606, 3, 684)` 与在册地板逐维等值**⇒ 地板在 HEAD 是对的；工作树 `(784, 1610, 3, 687)`，差数点名＝在飞未跟踪三件 `runtime/db_backup.py`·`domains/core/write_trace.py`·`domains/chat_reply/llm_engine/prompt_template.py`（直读 +4 全落在 `db_backup.py`）。**主会话没有代录地板**（按工作树复录＝把未入库件烙进册，那批若不入库就轮到 HEAD 红给所有人，正是这四枚腿要拦的事）；正解＝那批 owner 入库同批现算复录、容差 `(0,200,0,50)` 一字不动。
- **⑤ 四道门终态读数**（全部本窗亲跑）：`runtime-layout` **PASS rc=`0`**；`typecheck` **`Success: no issues found in 609 source files` rc=`0`**；`lint` 全树 **`Found 30 errors` rc=`1`**（**本波族已清 0**：`test_doc_link_integrity.py` 那 `3` 枚 ISC004/F541 手工修净、该件 `ruff` rc=`0`；余下全属他窗在飞件，含未跟踪 `tests/`）；`test` 全量 run8 后台跑（读数落 `%TEMP%\cb-run8\run8.txt`）。另 `doc_sync --check`／`command_catalog --check`／`verify_hashes` 三把生成册尺见 §65（`--check` 从 rc=`1` 修到 rc=`0`，生成器幂等已证）。
- **⑥ 文档面**：`HANDBOOK` 新增 §61–§65（触发词债执行账／四格补丁仓外真跑／类型门盲区／三席交付与两次自我更正／机器册陈旧 HEAD 可复现）＋就地更正 §60 两行（门族"71 枚无牙"降为待查清单、统一调度 `125` 的单位）。`AGENTS.md` 仍 `29,985` B（软上限 `30,000` 内，**没加 #73 新行**：加一行就得删别处，而 42 处代码按号引用台账编号——留给体积那格解完一起动）。本交接件即"结案"落点（按 D-22 乙案：就地更新、不新建带日期交接件）。
- **本窗三席净交付**（细账 §64）：R2b 补 `SHIM_ROWS` `15→23`（走生成器 `--write-ledger`，HEAD 轴 `38 passed`）＋双向补牙＋报出 `--write-ledger` 出 CRLF 与 `_CANONICAL_PKG` 盲区；C-D-01 把只活在 `.superpowers/` 草稿里的中央调度闭合锁**转成实件** `tests/test_central_dispatch_closure_gate.py`（主会话亲跑 `25 passed`）；W-G-02 把余 `45` 件逐件读码＝`43` 已武装／`2` 真无牙，与 W-G-01 合读 `72` 件推翻"按名普查"（高估 3–4 倍）。
- **本目标 ②③ 的验收判据（2026-10-02 逐条回查代码，不靠记忆）**：
  - **②「绝不绕门、不起第二本账」＝成立**。回执构点只往 `audit_tags` 上盖 `sticker_same_message` 一枚标（`chat.py` 的 `_sticker_attach_parts` 之后、与 `attach_tags` 同批并入），判定与额度仍在原腿；日帽全树**只有一本** `_reaction_meme_daily`（根 `__init__.py` 单一定义、三对读写点分属回应腿/表情补发腿/同消息并图腿，同一 session_key 同一帽），且定义处就写着"额度账/冷却账不另立"。⇒ 没有第二本账，也没有绕开门的分支。
  - **③「零新配置字段、复用门族、群聊 only」＝成立**。补发腿读 `getattr(meme_config, "bot_reactions_meme_enabled")`、以 `prefix="bot_reactions_meme_"` 走 `_REACTION_MEME_GATE`；那四枚键（`enabled/probability/cooldown_seconds/daily_max`）经 `git log -S` 定为**本波之前**的 TTS 波所引入（非本波新加）；群聊门是 `_is_group_session(session_key)`，注释把判据钉在台账 #35★（私聊绝不补发、**会话键才是判定口、带群号也不算**）。语义门槛另加两把 C1 面（悲伤表达不配笑脸、我自己那句是丧事场合也不配图），与 P3/钩子同判据。
  - **本波域锁件复跑**：`tests/test_meme_album_commands.py` ＋ `tests/test_sticker_pools_consumers.py` 合跑 **`143 passed`**（当次读数，工作树含他席在飞件）。
  - ✅ **①的"泄露面唯一代码级防线"补了一次变异自证（10-02，仓外 HEAD 副本内做，未碰她的树）**：把出处门那一行 `if str(row["review_state"]…).strip() != ADMIT: return "not_admitted"` 改成永不触发 ⇒ `2 failed, 50 passed`，且红的正是 `test_admit_into_album_refuses_unapproved_row` 与 `test_empty_state_row_is_approvable_by_command_face_then_admitted`（断言回显逐字 `- not_admitted / + moved`，回执 audit_tags 也跟着从拦截态变成 `moved`）；还原后 `restored_identical=True`、复跑 `52 passed rc=0`、备份件已删 ⇒ **这枚门是真牙，不是文案**，无需再补锁。⚠ 同一次实验里我自己差点读错一格：副本**没有 `.git`**，我在中间插的那步 `git grep not_admitted` 因此**返回空**——那是死量具（trap #236），不是"没有断言"；真判据来自下一步注毒后的真红。
  - ⚠ 仍然**不可签**「已生效」：bot 未重启（规则 10），以上都是静态＋离线测试面证据。


- **她醒来那一屏（待裁，全部未动）**：`D-19`–`D-26` 原样在案，另新增 `#43`–`#50` 八格——余 `8` 枚触发词债、布尔表十处手抄已分叉、触发词尺两洞、SSRF 假守卫、S-01 甲档缺矩阵、S-03 别名不对称、类型门三档、机器册巡检腿三档。**四格安全补丁一律未 apply、未提交、bot 未重启**（常令：提交/推送/重启归她）。

