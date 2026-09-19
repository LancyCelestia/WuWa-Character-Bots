# 紧急信息统一波（B 波）终验结论 —— 给用户的独立判定

> 出件席：**INTG-1（独立终验席）**。只读终验，**未修改任何东西**（含一行错字）。
> 取证时点：2026-09-20 02:46—03:03（本机）。
> 基线：全量 test 取数于 **`0487156` → `0ee9115` 移动基线**上（多会话共享树，HEAD 每几分钟动一次，脏度 973→981 件）。
> 过程与逐条证据：`.superpowers/sdd/2026-09-19-emergency-info-unify/reports/INTG-report.md`。
> **席位终态（本席 03:02 复核）**：B10-FIX 与 B11 **均已 `Status: DONE`** ⇒ 本波无在飞实施席，本席这份终验是全波收口后的数。
> **本席不替主会话自报「本波完成」**——下面每一格要么有文件行号，要么有本席实跑命令与输出。

---

## 一句话总账

**代码与测试是真的、全绿的、但一件都没入库、一件都没接线、生产一行都跑不到。**
本波交付物里唯一进了 git 的是四笔文档/测试提交（`53e8e7f`/`c632c36`/`6ffdef3`/`50238df`）；
闸本体 774 行、紧急域 12 件 2657 行、四个测试件、真夹具目录——**全部是 `??`（未跟踪）**。
所以现在的正确说法是「**B 波落了码、落了规格、落了登记，没落库、没接线、没生效**」，
不是「紧急信息能力做好了」。

---

## 表①：四态表（已落码 / 已入库 / 已注册 / 已生效）

| 项 | 已落码 | 已入库（git） | 已注册（可被生产调用） | 已生效（生产在跑） | 本席证据 |
|---|---|---|---|---|---|
| 中央出站防风暴闸 `outbound_gate.py`（774 行） | ✅ | ❌ `??` | ❌ | ❌ | `submit_active_push` 生产调用点 **0**；`build_outbound_gate` 生产调用点 **0** |
| 紧急域内核（`contracts` / `grading` / `dedupe` / `review` / `store`） | ✅ 5 件 | ❌ 全 `??` | ❌ | ❌ | 域外生产 import **0**（只被 2 个测试件引用） |
| 采集器 4 件（NMC 预警 / USGS / GDACS / ICL + `http_get`） | ✅ | ❌ `??` | ❌ | ❌ | 三态返回 `OK\|NO_DATA\|FAILED` 已实现并被 57 条用例锁住 |
| 真夹具 `tests/fixtures/emergency_info/`（6 件 + README） | ✅ | ❌ `??`，但**已不受 ignore** | — | — | `git check-ignore -v` → 无输出 exit=1；缺夹具改 `pytest.fail`（`:132`），不再静默 skip |
| 送达核验 **Tier1**（摘段观测日志 + SENT 审计注记） | ✅ | ❌ `onebot.py`/`__init__.py` 均 ` M` | ⚠️ 装配点已在，缺省 False | ❌ | `onebot.py:326-333`；17 条锁含「全丢→文本兜底逐字节不变」 |
| 送达核验 **Tier2**（UNKNOWN 段 `get_msg` 确认器） | ✅ 骨架 | ❌ | ⚠️ 骨架级 | ❌ **且取证锁钉死** | `_ONEBOT_GET_MSG_NOT_FOUND_PROVEN=False` ⇒ 「消息不存在→重发」分支**生产不可达**；`part_message_ids` 无生产者 ⇒ 恒 None 空转 |
| 七枚配置键（6 闸 + 1 核验） | ✅ `config.py:234-239/:244` | ✅ 已随 `9a9e099`/`53e8e7f`/`50238df` 入库 | ✅ 四面闭合（含 `path_fields:1188`） | ❌ `.env` 内**整族键不存在** | 见下表「四面」 |
| 路由 / 帮助 / 能力注册（RouteKind·_HELP_ENTRIES·capability_registry） | — | — | ❌ **全 0** | ❌ | `RouteKind` 34 成员内 emergency **0**；紧急 topic **0**；registry emergency **0** |
| 九个统一规格件（**813 行**） | ✅ | ❌ `??` | — | — | B11 席 **DONE**（本席 03:02 复核），评分见表③ |

**七键四面（登记是否闭合）**

| 面 | 位置 | 实数 | 入库态 |
|---|---|---|---|
| `config.py` | `:234-239` + `:244`，`path_fields` 在 `:1188` | 7/7 | ✅ 在 HEAD |
| `.env.example` | `:90/92/94/98/99/102/107` | 7/7 | ❌ ` M` 未提交 |
| `docs/config-catalog-full.md` | `:846-850`（5 行覆盖 7 键） | 7/7 | ✅ `53e8e7f`，口径由 `50238df` 自我更正 |
| `settings.py:333 RESTART_REQUIRED_KEYS` | `:496-525` | 7/7 | ❌ ` M` 未提交 |

> 提醒一个已经咬过本席的坑：catalog 里字段名**去掉了 `bot_` 前缀**（写作 `_outbound_gate_enabled`），
> 所以 `grep "bot_outbound" docs/config-catalog-full.md` 必然零命中——那是**假阴性**，不是没登记。

---

## 表②：门禁红归属表（本波计入 0 条）

| 门禁 | 结果 | 本波账 | 红在哪 / 归属席位 / 证据 |
|---|---|---|---|
| `typecheck`（mypy 全树） | **绿** `Success: no issues found in 635 source files` | 0 | — |
| `runtime-layout` | **PASS**（`source_generated_dirs=empty` / `python_bytecode=absent`） | 0 | — |
| `lint`（ruff 全树） | **红**：dev.ps1 跑出 **18 错**，20 秒后直跑 **16 错** | **0**（专面 `All checks passed!`） | TTS/语音 hook 席在飞 10（`voice_enricher.py` 3、`test_tts_t75.py` 7，mtime 02:48/02:49）；知识库接线 1（`test_kb_wiki_retriever_wiring.py` FURB167）；他席在飞 1（`providers.py` RUF100，` M`）；**既有债 4**（`backend_unit.py`/`quiet_hours.py`/`rate_limit.py`/`injection.py` 各 1 条 I001，mtime 09-19 12:3x 且与 HEAD 一致）。两次跑出不同数=树在动的直接证据（差的 2 条 `test_voice_hook_assembly.py F821` 被该席中途自修） |
| `test`（全量） | **红**：`30 failed, 9287 passed, 12 skipped, 24 xfailed, 29 errors in 406.66s` | **0** | ①**TTS/语音 hook 席在飞 26 failed**，根因 `TypeError: RuntimePipeline.__init__() got an unexpected keyword argument 'outbound_voice_enricher'`；②**TTS 契约层席在飞 29 errors**，根因 `AttributeError: …capabilities.tts has no attribute '_REF_FINGERPRINTS'`；③**常驻生成物门 2**（`verify_hashes` 5 项 DRIFT 全为渲染面文档 / `doc_sync` auto-facts 漂=他席新增测试件）；④**渲染面 1**（`test_mermaid_reply_render` `box-shadow` 3≠2，vis4 分级阴影族没同步旧「恰好两枚」锁）；⑤**环境债 1**（`yt-dlp 未安装`，`downloader.py:626`） |

**本波六件独立复跑（不引用席位自报数）**：`test_outbound_gate` 42 / `test_emergency_info_core` 79 /
`test_emergency_info_sources` 57 / `test_delivery_verification_tier1` 17 / `test_group_digest_push` 35 /
`test_doc_sync_gates` 4 = **234 passed，0 failed**。

---

## 表③：九个统一完成度评分

> 简报原文把「九个统一」列成了 **10 个标签**（架构 / 处理流程 / 流程图 / 架构图 / 模块 / 样板 / 函数 / 参数 / 变量 / Help）。
> 本席按原文逐格给分，不擅自合并；这个标签数不一致本身也是要收口的口径问题（见 §六 裁决点 R-0）。
> 评分标准（`briefs/b-wave-addendum.md` §3）：**每一项都要能回答「本域的写法抄的是哪个既有正例，坐标在哪」**。

| # | 统一项 | 成文在哪 | 缺什么 | 谁来做 |
|---|---|---|---|---|
| 1 | **架构** | `emergency-info-unify-spec-20260920.md` §0（三态定性）+ §4.2（域外中央件边界） | 架构落地缺装配层：`build_outbound_gate` 无生产调用者 | 接线波 |
| 2 | **处理流程** | §2（全链 + 失败分支 + 降级出口） | 接缝未缝合是**硬事实**：采集器 `http_get.py:38` 刻意不 import 内核契约层，绕过 `build_emergency_item`/`ReviewGate.submit` 就会造第二事实源 | 接线波（先落 §8.1 机器锁） |
| 3 | **流程图** | §2 处理流程图，且已按要求画进 **P0 漏报分叉**（未以 `priority=str(level.value)` 落 RouteRule ⇒ P0 被闸静默顺延=漏报，L-6） | 图是对的，但代码里**没有一条 P0 能走到闸**（零接线） | 接线波 + 用户裁决优先级载体 |
| 4 | **架构图** | §1（mermaid flowchart，域内外边界/中央件/队列/渲染/TTS/控制面） | 无 | — |
| 5 | **模块** | §4.1 域内 12 件 / §4.2 中央件 / §4.3 计划件（**grep 全仓 0 命中=纯计划**） | 域内**没有 `capabilities/` 层**（现役 20 域都有），能力面缺一个 `build_emergency_*_capability` | 接线波（并先裁 §八 的层名/目录名两点） |
| 6 | **样板** | §4 表逐行「抄哪个正例 + 坐标」，本席复核为真（`http_util.py:255`、`ssrf_guard.py:159`、`stock_data.py:90`、`weather.py:82-83/:112`、`campus_store.py:30`、`campus.py:54`、`persona_service.py:739`） | ①`nmc_alarm.py:66` 另立第三份 `ALARM_COLOR_RANK`，**无 AST 锁**（contracts↔weather 只有单向锁）；②`InMemorySendQueue.submit`（`queue.py:191`）**确无 `deliver_after`**，SQLite 版 `:418` 有 ⇒ 双实现不对齐（L-7） | ①紧急域 Owner；②队列属主，需裁决 |
| 7 | **函数** | §5.1 内核 / §5.2 采集 / §5.3 闸与核验，签名逐字抄自磁盘 | B4a 报告 §R2-4-L1 建议片段写的形参名 `settings=`/`quiet_settings=` **是错的**，真身是 `settings_provider=`/`quiet_settings_provider=`（`outbound_gate.py:748-756`）⇒ 照抄必 `TypeError` | 合流席更正报告 |
| 8 | **参数** | §5 含仅关键字参、缺省、返回类型、语义与失败方向 | `dedupe_family` 是**规格缺口的钉法**：`SendRequest` 上没有任何字段能表达「我属按日族」，误报后果=跨日不再重投（漏发）。声明点与键构造点必须同源 | 用户裁决（规格级） |
| 9 | **变量 / 枚举** | §6.1 等级与状态、§6.2 severity 载体=`SendRequest.priority`、§6.3 `reason` 短语表 9+8+5 枚、§6.4 告警 kind 5 枚 | **D-3 颜色统一未收口（本席复测为 0）**：`theme_tokens` 在闸与紧急域的引用数均为 **0**，颜色以自携带中文标签存在（`contracts.py:68 color_label`、`:189` 字段、`:113` 反查）；另键规范**实现两遍**（`outbound_gate.py:259` 与 `dedupe.py:70`，前者不校验段字符集/日期形态） | 接线波（颜色收口 + 单源化或加互校锁） |
| 10 | **Help 命令及帮助页** | §7.1 建议 topic 与命令面、§7.2 逐字对齐「媒体归档/群信息」现役正例、§7.3 联动面清单（漏一处即对应门红，实测门坐标已给） | **零落地**：`echo.py` 未加紧急 topic（本席实数 0），`command_catalog`/`COMMANDS.md`/`route-matrix` 联动面全部未动。B11 自评「0/4 落地」，本席复核其四条 grep **全部复现** | 接线波（届时一次改齐，否则常驻门必红） |

---

## 表③-附：四个必须正视的缺口 + 一条锁自身缺陷（本席逐条独立复测，不照抄席位自报）

| # | 级别 | 缺口 | 本席实测证据 | 谁做 |
|---|---|---|---|---|
| G-1 | **会错（本波产物自身的机器锁有潜伏假阳性）** | T6 结构锁 `test_submit_active_push_production_importers_are_allowlisted` 的放行前缀写作 `domains/emergency`，**真身目录是 `domains/emergency_info`** ⇒ 前缀永不匹配。今天因「没人 import」恒真通过；等接线波真的让紧急域引用闸，**这条锁会反过来红咬接线席**，报「越界引用中央闸」 | `tests/test_outbound_gate.py:1177-1197` 逐行读 + `ls domains/` 实证目录名 | **接线波开工前先改这一行**（改前该件 42 条仍全绿） |
| G-2 | **会炸（上线硬阻塞）** | 能力 id `bot.emergency_info` **从未登记**；全仓 `bot.emergency*` 只出现在 2 个测试件 | `grep -rn "bot\.emergency" --include=*.py --include=*.mjs .` → 仅 `tests/test_outbound_gate.py:85/1034/1066`、`tests/test_delivery_verification_tier1.py:77/83`；真身注册面=`domains/chat_reply/runtime/capability_registry.py`（`bot.campus_forward` 在 `:544`） | 接线波（与 R-1/R-2 同改） |
| G-3 | **会炸** | 出卡**无落点**：紧急域内零渲染触点，而拿来当正例的现役 `weather_alert` 本身旁路出卡、不过渲染契约 ⇒ 「抄 weather_alert」=抄一个契约违例 | 域内 12 件无任何卡片/渲染 import（`grep -rn theme_tokens domains/emergency_info/` = **0**） | 接线波；落点选择是**你的产品决定**（见 R-8） |
| G-4 | **会炸（违你已定裁定的精神）** | D-7 语音只落了「先修谎报送达」半件；播报半件零：闸与域内 **TTS 引用数 0/0/0**，无播报件、无 3–10s 长度门 | `grep -c "tts\|TTS"` → `outbound_gate.py`=0、`contracts.py`=0、`grading.py`=0 | 接线波（长度门必须落在闸/能力侧，不能落在 TTS 供应商层） |
| G-5 | **欠账（口径失真）** | T6 现役直调锁写作 `>= 5` 下限式，不锁精确数 ⇒ 他席增减直调点都不会红；B11 自报「8 处」、规格自报「5 处」，实况 **5 处** | `__init__.py:2954/3065/3223/3372/5059`（`grep -n` 数到 6 是含 `:3005` docstring 提及） | 闸席（要精确就改 `== 5` 并列清单） |

**另**：B11 终稿有四组引用坐标已漂/指错，本席逐条实测后在表③与本表用的是**实测值**：
`contracts.py:38-42`（实为 docstring，`color_label` 在 `:68`）、`webui/scripts/capability_contract_audit.py`（**该文件全树不存在**）、
「8 处直调」（实 5 处）、摘要旁路 `:3218`（实 `:3223`）。⇒ 台账数字仍不可照抄，这是本波第 5 例（前两例见 §二 的 18/16 与 §表③ 的 880/869）。

**评分小结**：**成文面 10/10 有着陆**（规格件 **813** 行，且正例坐标逐条可复核为真）；
**代码面 0/10 完成统一落地**——因为整个域一次都没被生产调用过，「统一」目前只是纸面契约。
若按「代码是否真按规格统一」打分，本席与 B11 自评同向：**只有取数（`http_get.py`）与构段（`_mixed_segment_plan`）两处是真统一**，
投递侧因闸零消费者属「写法已统一、链路未穿通」，颜色与语音两处**尚未收口**（G-3/G-4），Help 面**整块未落**（表③ #10）。
最该在下一波先做的三件事：**先改 G-1 那一行锁**（否则接线第一天就被自己的锁咬）、
落 §8.1 接缝机器锁（现状是**「接缝缺失」本身被 `test_emergency_info_sources.py:900` 这条文本断言锁保护**，
缝合动作必然先让该锁变红），以及 P0 漏报分叉的优先级载体裁决。

---

## 四、「重启前生产行为零变更」证据链（三条并列 + 一条铁律）

1. **缺省全关**——`config.py:234 bot_outbound_gate_enabled=False`、`:244 bot_outbound_verify_enabled=False`；
   紧急域**连一个 config 字段都没有**（`grep -c bot_emergency config.py` = **0**）。
2. **零消费者**——`submit_active_push` 生产调用点 **0**、`build_outbound_gate` 生产调用点 **0**、
   紧急域被域外生产模块 import **0**、`RouteKind` 无紧急族（34 成员 / 0 命中）、紧急 topic **0**、
   `capability_registry` emergency 命中 **0**。
3. **生产开关不存在**——`.env` 内 `outbound` 与 `emergency` 键命中均为 **0** ⇒ 运维侧无途径打开；
   退一步说，就算想热改也拨不动：七枚键**全部**登记在 `settings.py:501-525 RESTART_REQUIRED_KEYS`，
   `set_override` 走 `:834-837` 直接抛 `ValueError`。
4. **铁律兜底**——改代码必须重启 bot 才生效；而本波代码**至今未 commit**（闸/域/夹具/四个测试件全 `??`）。

**必须如实说的一个例外（不许掩）**：Tier1 的**摘段丢弃观测日志不受开关门控**
（`onebot.py:326-333`，`if dropped_types: logger.info(...)`）。
⇒ 「重启后」即便核验开关仍关着，只要出现被摘段的混合消息，日志会多一行
（只记 `request_id/planned/sent/dropped_types/sent_types`，零正文）。
发送语义没变这一点有两条锁守着，本席实跑全绿：
`test_all_parts_dropped_text_fallback_byte_identical`（`:145`）、`test_sent_receipt_unchanged_when_verify_off`（`:181`）。

---

## 五、收尾 commit 清单（本席未动 git，全部逐文件显式 add）

**未跟踪（必须新增，漏一件就会「随工作树蒸发」）**
```
plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py
plugins/bot_unified_runtime/domains/emergency_info/            （12 件 .py，2657 行）
tests/test_outbound_gate.py
tests/test_emergency_info_core.py
tests/test_emergency_info_sources.py
tests/test_delivery_verification_tier1.py
tests/fixtures/emergency_info/                                  （6 件真样例 + README.md）
docs/design/emergency-info-unify-spec-20260920.md               （B11 九个统一件，**813 行**）
docs/design/backend-v2-product-extensions.md                    （B8 更正落在 untracked 件上）
```

**已跟踪有改动（多会话共享面，**动前必须读最新态**、`git commit -- <paths>` 按路径提交）**
```
plugins/bot_unified_runtime/domains/transport/sender/onebot.py     （B4b Tier1/Tier2；本波 + 他席混写，需分 hunk 判定）
plugins/bot_unified_runtime/__init__.py                            （:1653-1668 confirmer 门控接线；同上混写）
plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py （B8 七键入重启清单；另有他席 52 行）
.env.example                                                       （B8 七键 22 行）
plugins/bot_unified_runtime/domains/ops/monitor/result_unknown.py  （B8 注释 9/4 行，零逻辑改动）
```

**已入库且本席逐笔核对为干净**（`git show --stat` + `--name-only` + `merge-base --is-ancestor`）：
`53e8e7f`（catalog +5/−0，单件）、`c632c36`（摘要回归锁 +32/−0，单件）、
`6ffdef3`（规格 + 汇总 406/−0，恰本波两件）、`50238df`（catalog 自我更正 +2/−1，单件）。
⇒ **四笔零捆绑他席 hunk**。
另：`config.py` 与 `catalog` 的未提交增量已核**归 TTS 席**（`bot_tts_voice_hook_enabled` 字段 + catalog 1 行），不是本波账。

---

## 六、必须你（用户）裁决的点，本席一律不代裁

| # | 裁决点 | 现状实据 | 谁等这个答案 |
|---|---|---|---|
| R-0 | 「九个统一」到底算几项（简报列了 10 个标签） | 表③ 逐格已按 10 行给分 | 文档口径 owner |
| R-1 | 域目录名 `emergency_info`（现状）vs `emergency`（E3/E5 建议） | 现状=异形并存 | 接线波（改名要连 import 一起动） |
| R-2 | 采集层放 `sources/`（现状）vs `data/`（域重组后多数派） | 现状 `sources/` 含 4 采集器 + `store.py` | 接线波 |
| R-3 | 定级词表定稿权，以及 `credibility` 是否参与定级 | `credibility` 在 `grading.py` 出现次数 **0**（建了不用属实），`DEFAULT_GRADING_RULES` 在 `grading.py:51` | 你 + 域 owner |
| R-4 | `InMemorySendQueue` 缺 `deliver_after` 的补法 | `queue.py:191` 无 / `:418` 有 | 队列属主（双实现不对齐=测试态与生产态语义不同） |
| R-5 | **`severity` 用什么载体传给闸**（`SendRequest.priority` 是裸 str 契约） | 不传 ⇒ P0 被静默顺延 = **漏报** | 你（这是方向性风险，不是实现细节） |
| R-6 | Tier2 真机取证：SnowLuma `get_msg` 到底有没有、返回什么、`message_id` 是不是纯数字 | 取证锁 `_ONEBOT_GET_MSG_NOT_FOUND_PROVEN=False` 把「不存在→重发」钉成生产不可达 | 你（要重启 + 真机发一条含图+语音的私聊回读） |
| R-7 | **闸要不要接线**（以及接线是否等于允许紧急域上线投递） | 目前闸零消费者；接线是行为拓扑变更 | 你（本席判断：这是全波唯一真正的开关） |
| R-8 | **紧急信息的出卡落点**：卡片走哪条渲染路、要不要同时出语音 | 域内零渲染触点（G-3）；现役 `weather_alert` 是不过契约的旁路正例，不能照抄 | 你（产品决定；B11 已裁定本席不代裁） |

---

## 七、下一步次序（本席建议，不是授权）

1. **先 commit 再谈别的**：按 §五 清单逐文件入库。现在这批东西只要有人 `git clean` 就全没。
2. **B10-FIX / B11 收尾核验（本席 03:02 已复核）**：两席 report 均已 `Status: DONE`，
   且本席把四件核心测试件在 03:02 **重跑一遍确认稳定**：`sources` 57（971 行）/`core` 79（869 行）/
   `outbound_gate` 42（1344 行）/`tier1` 17（409 行），全绿。⇒ 本波无在飞实施席。
3. **先改 G-1 那一行放行前缀**（`domains/emergency` → `domains/emergency_info`），再谈接线。
   否则接线第一天就会被本波自己的结构锁红咬，而且红得像「越界引用中央闸」，很可能被误判成接线席乱改。
4. **落 §8.1 接缝机器锁**，再谈缝合（顺序反了会出现「没有锁的接缝」）。
5. **R-5 / R-7 / R-8 你先裁**（P0 漏报载体、闸接不接、出卡落点），其余（R-1~R-4）可以和接线波一起做。
6. **G-2 能力 id 登记 + 表③ #10 Help 四面联动，必须与接线同一次改齐**——分开做必红常驻门。
7. **合流终验**：等 TTS/语音 hook 席与渲染面落定后，在**一个固定 HEAD** 上重跑四门禁，
   届时才会拿到一个可复现的全量数——本席这份数做不到（理由见表② 那一行「两次跑出不同数」）。
8. 真机验收（重启后）：`docs/acceptance-manual.md` 本波未新增小节，Tier2 取证动作见 R-6。

---

## 八、本席没做到的 / 不做的

- **什么都没修**：包括 §二 归属表里那 16 条 lint 错、29 条 TTS error、L-1~L-6 六项待办，全部只登记不动手。
- **没有跑**：渲染样张、WebUI 验收、真机 `get_msg` 探测（不在简报五项终验范围内，且需要重启与外呼）。
- **9287 这个数不可精确复现**：基线在我跑的过程中动了两次（`0487156`→`0ee9115`）。
- **`.env` 全程只报键名与存在性**，零值外泄；实跑全程带 `PYTHONDONTWRITEBYTECODE=1` +
  `-p no:cacheprovider --basetemp=$TEMP/intg-1`；跑后自查 `__pycache__`=0、`*.pyc`=0、`.pytest_cache`=0、源码树无 `data/`；
  `qx.json`（362,774 B）完好。
  树内 `.ruff_cache`/`.mypy_cache` 两枚残留 mtime 均**早于本席开工**（00:53 / 前日 17:58），是他席绕 `dev.ps1` 直跑的产物，本席按纪律不清理只登记。
